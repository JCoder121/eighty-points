"""GameEngine — shared game loop for both Upgrade and Find Friends modes.

The engine is the single source of mutation for GameState.  It validates
every incoming action, applies the change, and returns a list of events
that the network layer can broadcast.

Usage
-----
    engine = GameEngine(state, mode_strategy)
    await engine.start_dealing(broadcast_fn)

Each action method is *synchronous* except start_dealing, which drives the
async deal loop.  Callers supply a broadcast callback so the engine stays
decoupled from WebSocket details.
"""
from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING, Callable, Awaitable

from shengji.engine.scoring import count_attacking_points, compute_rank_advancement
from shengji.engine.tricks import (
    find_beatable_components,
    is_valid_follow,
    resolve_trick_winner,
)
from shengji.models.bid import Bid
from shengji.models.deck import Deck, NUM_PLAYERS, BOTTOM_SIZE, HAND_SIZE
from shengji.models.game_state import GamePhase, GameState
from shengji.models.card import Card, Rank, Suit
from shengji.models.groups import classify_play, Throw
from shengji.models.trump import TrumpContext

if TYPE_CHECKING:
    from shengji.modes.base import ModeStrategy

# Seconds to wait between dealing individual cards.  0 in tests; ~0.5 in prod.
DEAL_DELAY_SECONDS: float = 0.5

# ---------------------------------------------------------------------------
# Event helpers
# ---------------------------------------------------------------------------

def _event(kind: str, **data) -> dict:
    return {"event": kind, **data}


def _cards_match_any(cards: list[Card], options: list[list[Card]]) -> bool:
    """Return True if *cards* equals any option as a multiset."""
    def _key(lst: list[Card]) -> list:
        return sorted(repr(c) for c in lst)

    cards_key = _key(cards)
    return any(_key(opt) == cards_key for opt in options)


# ---------------------------------------------------------------------------
# GameEngine
# ---------------------------------------------------------------------------

class GameEngine:
    """Drives a single game session.

    Parameters
    ----------
    state:
        The mutable GameState shared by all players.
    mode_strategy:
        Injected strategy for Upgrade vs. Find Friends differences.
    deal_delay:
        Seconds between each dealt card.  Override to 0 in tests.
    """

    def __init__(
        self,
        state: GameState,
        mode_strategy: "ModeStrategy",
        deal_delay: float = DEAL_DELAY_SECONDS,
        rng: "random.Random | None" = None,
    ) -> None:
        self.state = state
        self.mode = mode_strategy
        self.deal_delay = deal_delay
        self.rng = rng  # deterministic deals when seeded (CLI harness, tests)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _player(self, player_id: str):
        """Return the Player with this id, or raise ValueError."""
        for p in self.state.players:
            if p.id == player_id:
                return p
        raise ValueError(f"Unknown player_id: {player_id!r}")

    def _next_player_id(self, after_id: str) -> str:
        """Return the player_id seated counter-clockwise from *after_id*.

        Players are stored in counter-clockwise order, so the next player
        is simply index + 1 (mod NUM_PLAYERS).
        """
        ids = [p.id for p in self.state.players]
        idx = ids.index(after_id)
        return ids[(idx + 1) % NUM_PLAYERS]

    # ------------------------------------------------------------------
    # Dealing
    # ------------------------------------------------------------------

    def start_dealing(self) -> None:
        """Synchronous portion of deal setup.

        Validates preconditions, shuffles a new deck, stores the draw pile
        and bottom on the GameState, and transitions to DEALING.

        The actual card-by-card loop is driven by deal_all_cards(), which is
        async so it can sleep between cards.  Separating the two lets unit
        tests exercise start_dealing without needing an event loop.

        Raises
        ------
        ValueError
            If the game mode is not set or the phase is wrong.
        """
        state = self.state
        if state.mode is None:
            raise ValueError("Game mode must be set before dealing starts.")

        # Phase handling:
        #   WAITING       → first round; transition to DEALING.
        #   ROUND_OVER    → subsequent round; transition to DEALING.
        #   DEALING       → re-deal after no-bid; already in DEALING (close_bidding
        #                   did the transition), so no further transition needed.
        #   anything else → reject.
        if state.phase == GamePhase.DEALING:
            pass  # re-deal: already in DEALING
        elif state.phase in (GamePhase.WAITING, GamePhase.ROUND_OVER):
            state.transition_to(GamePhase.DEALING)
        else:
            raise ValueError(
                f"Cannot start dealing from phase {state.phase.value!r}. "
                "Expected WAITING, ROUND_OVER, or DEALING (re-deal)."
            )

        deck = Deck(rng=self.rng)
        draw_pile, bottom_deck = deck.prepare_deal()

        state.draw_pile = list(draw_pile)
        state.bottom_deck = list(bottom_deck)
        state.cards_dealt_count = 0

        # Clear per-round fields
        state.bids = []
        state.trump_context = None
        state.current_trick = []
        state.tricks_won = {p.id: [] for p in state.players}
        state.last_winning_play = []
        state.attacking_points = 0
        state.throw_penalties = {}
        state.trick_number = 1
        state.current_leader_id = state.round_leader_id
        state.current_turn_id = ""  # not used during dealing

    def deal_next_card(self) -> tuple[str, Card] | None:
        """Pop one card from the draw pile and add it to the next player's hand.

        Cards are dealt counter-clockwise starting from the player *after* the
        round leader.

        Returns
        -------
        (player_id, card)
            The recipient and the card they received.
        None
            When the draw pile is exhausted (all 100 cards have been dealt).

        Side effects
        ------------
        Increments state.cards_dealt_count.  When the draw pile empties,
        transitions phase to BIDDING_AFTER_DEAL.
        """
        state = self.state
        if not state.draw_pile:
            return None

        # Determine which player receives this card.
        # Deal order: start from the player after the round leader,
        # cycling counter-clockwise.  cards_dealt_count tells us whose turn it is.
        ids = [p.id for p in state.players]
        round_leader_idx = ids.index(state.round_leader_id)
        recipient_idx = (round_leader_idx + 1 + state.cards_dealt_count) % NUM_PLAYERS
        recipient_id = ids[recipient_idx]

        card = state.draw_pile.pop(0)
        self._player(recipient_id).hand.append(card)
        state.cards_dealt_count += 1

        if not state.draw_pile:
            state.transition_to(GamePhase.BIDDING_AFTER_DEAL)

        return recipient_id, card

    # ------------------------------------------------------------------
    # Bidding helpers (module-level functions exposed as statics for tests)
    # ------------------------------------------------------------------

    @staticmethod
    def _bid_strength(cards: list[Card]) -> int:
        """Return the strength tier of a bid.

        1 — suited single (1 trump-rank card)
        2 — suited pair   (2 identical trump-rank cards)
        3 — small joker pair
        4 — big joker pair
        """
        if len(cards) == 1:
            return 1
        if len(cards) == 2:
            if cards[0].rank == Rank.BIG_JOKER:
                return 4
            if cards[0].rank == Rank.SMALL_JOKER:
                return 3
            return 2
        raise ValueError(f"Invalid bid card count: {len(cards)}")

    @staticmethod
    def _validate_bid_cards(cards: list[Card], trump_rank: Rank) -> None:
        """Raise ValueError if *cards* do not form a legal bid."""
        if len(cards) not in (1, 2):
            raise ValueError("A bid must consist of 1 or 2 cards.")

        if len(cards) == 1:
            card = cards[0]
            if card.suit == Suit.JOKER:
                raise ValueError(
                    "A single joker cannot be used as a bid; only joker pairs are valid."
                )
            if card.rank != trump_rank:
                raise ValueError(
                    f"Bid card must be the trump rank ({trump_rank.value}), "
                    f"got {card.rank.value}."
                )

        else:  # len == 2
            c0, c1 = cards
            if c0.rank != c1.rank or c0.suit != c1.suit:
                raise ValueError("A pair bid must consist of two identical cards.")
            if c0.suit != Suit.JOKER and c0.rank != trump_rank:
                raise ValueError(
                    f"Bid card must be the trump rank ({trump_rank.value}), "
                    f"got {c0.rank.value}."
                )

    @staticmethod
    def _can_overtake(
        new_cards: list[Card],
        new_player_id: str,
        current_bid: Bid | None,
    ) -> bool:
        """Return True if the proposed bid legally supersedes *current_bid*.

        Overtaking rules (strength = 1 < 2 < 3 < 4):
          • No current bid    → always valid.
          • Strictly stronger → valid (any player, any suit).
          • Same strength     → NEVER valid (a single cannot beat another single;
                                a suited pair cannot beat another suited pair).

        Implication: to overtake an existing single bid, you must hold a pair or
        better.  To raise your own single to a pair, that is strength 2 > 1 and
        is already covered by the "strictly stronger" rule.
        """
        if current_bid is None:
            return True
        new_str = GameEngine._bid_strength(new_cards)
        cur_str = GameEngine._bid_strength(current_bid.cards)
        return new_str > cur_str

    # ------------------------------------------------------------------
    # Bidding
    # ------------------------------------------------------------------

    def place_bid(self, player_id: str, cards: list[Card]) -> Bid:
        """Attempt to place a bid.

        Parameters
        ----------
        player_id:
            The bidding player.
        cards:
            The card(s) the player is showing.  Either:
            • 1 trump-rank suited card  → single bid
            • 2 identical trump-rank suited cards → pair bid (reinforcement or new)
            • 2 identical small jokers → no-trump (strength 3)
            • 2 identical big jokers   → no-trump (strength 4)

        Returns
        -------
        The Bid that was recorded.

        Raises
        ------
        ValueError
            On any rule violation.
        """
        state = self.state
        if state.phase not in (GamePhase.DEALING, GamePhase.BIDDING_AFTER_DEAL):
            raise ValueError(
                f"Cannot bid in phase {state.phase.value!r}. "
                "Bidding is only allowed during DEALING or BIDDING_AFTER_DEAL."
            )

        player = self._player(player_id)

        # The trump rank for this round is the round leader's current rank.
        # round_leader_id is still the original leader during the bidding phase —
        # it only changes in close_bidding() after a winner is determined.
        trump_rank = self._player(state.round_leader_id).rank

        # Validate card legality
        self._validate_bid_cards(cards, trump_rank)

        # Validate player actually holds the cards
        hand_copy = list(player.hand)
        for card in cards:
            if card not in hand_copy:
                raise ValueError(
                    f"Player {player_id!r} does not hold {card!r}."
                )
            hand_copy.remove(card)

        # Validate bid is stronger than current
        current_bid = state.bids[-1] if state.bids else None
        if not self._can_overtake(cards, player_id, current_bid):
            raise ValueError(
                "Bid is not strong enough to overtake the current bid."
            )

        # Determine the resulting TrumpContext
        if cards[0].suit == Suit.JOKER:
            resulting_trump = TrumpContext(trump_rank=trump_rank, trump_suit=None)
        else:
            resulting_trump = TrumpContext(
                trump_rank=trump_rank, trump_suit=cards[0].suit
            )

        bid = Bid(
            player_id=player_id,
            cards=list(cards),
            resulting_trump=resulting_trump,
        )
        state.bids.append(bid)
        # Update the live trump context immediately so players can see the current bid
        state.trump_context = resulting_trump
        return bid

    def close_bidding(self) -> None:
        """Finalise the bidding phase after all cards are dealt.

        If no bids were placed, re-deal (transition back to DEALING via
        start_dealing()).  Otherwise the last bid wins: the winning bidder
        becomes the round leader (they will exchange the bottom deck), the
        trump context is locked in, and the phase advances to BOTTOM_EXCHANGE.

        Raises
        ------
        ValueError
            If called outside the BIDDING_AFTER_DEAL phase.
        """
        state = self.state
        if state.phase != GamePhase.BIDDING_AFTER_DEAL:
            raise ValueError(
                f"close_bidding() called in phase {state.phase.value!r}; "
                "expected BIDDING_AFTER_DEAL."
            )

        if not state.bids:
            # Nobody bid — re-deal this round.
            for p in state.players:
                p.hand = []
            # BIDDING_AFTER_DEAL → DEALING is a valid transition (re-deal case).
            # start_dealing() also accepts DEALING as its entry phase now.
            state.transition_to(GamePhase.DEALING)
            self.start_dealing()
            return

        # Winning bid is the last entry in the bid history.
        winning_bid = state.bids[-1]
        if state.round_number == 1:
            state.round_leader_id = winning_bid.player_id
        state.current_leader_id = state.round_leader_id
        state.trump_context = winning_bid.resulting_trump

        # Assign teams now that the round leader (bid winner) is known.
        self.mode.assign_teams(state)

        # Find Friends: declare friend before seeing the bottom deck.
        # Upgrade: go straight to bottom exchange.
        if self.mode.needs_friend_declaration():
            state.transition_to(GamePhase.FRIEND_DECLARATION)
        else:
            state.transition_to(GamePhase.BOTTOM_EXCHANGE)

    # ------------------------------------------------------------------
    # Bottom exchange
    # ------------------------------------------------------------------

    def exchange_bottom(self, player_id: str, cards_to_put_back: list[Card]) -> None:
        """The bid winner picks up the 8 bottom cards and buries 8 of their own.

        Flow:
          1. Add all 8 bottom cards to the round leader's hand (33 cards total).
          2. Player chooses 8 cards to put back as the new bottom.
          3. Remove those 8 from hand; hand returns to HAND_SIZE (25).
          4. Transition to FRIEND_DECLARATION (Find Friends) or PLAYING (Upgrade).

        Parameters
        ----------
        player_id:
            Must equal state.round_leader_id.
        cards_to_put_back:
            Exactly 8 cards from the leader's post-pickup hand.

        Raises
        ------
        ValueError
            On wrong phase, wrong player, wrong card count, or player doesn't
            hold a card they claim to bury.
        """
        state = self.state
        if state.phase != GamePhase.BOTTOM_EXCHANGE:
            raise ValueError(
                f"exchange_bottom() called in phase {state.phase.value!r}; "
                "expected BOTTOM_EXCHANGE."
            )
        if player_id != state.round_leader_id:
            raise ValueError(
                f"Only the round leader ({state.round_leader_id!r}) can exchange "
                f"the bottom deck; got {player_id!r}."
            )
        if len(cards_to_put_back) != BOTTOM_SIZE:
            raise ValueError(
                f"Must put back exactly {BOTTOM_SIZE} cards; "
                f"got {len(cards_to_put_back)}."
            )

        leader = self._player(player_id)

        # Step 1: Pick up all bottom cards
        leader.hand.extend(state.bottom_deck)
        state.bottom_deck = []

        # Step 2 & 3: Bury the chosen 8 cards
        hand_copy = list(leader.hand)
        for card in cards_to_put_back:
            if card not in hand_copy:
                raise ValueError(
                    f"Card {card!r} is not in the leader's hand after picking up "
                    "the bottom deck."
                )
            hand_copy.remove(card)

        leader.hand = hand_copy
        state.bottom_deck = list(cards_to_put_back)

        # Sanity check
        assert len(leader.hand) == HAND_SIZE, (
            f"Leader hand size after exchange should be {HAND_SIZE}, "
            f"got {len(leader.hand)}"
        )

        # Step 4: Phase transition (friend declaration already done before exchange)
        state.transition_to(GamePhase.PLAYING)
        state.current_turn_id = state.round_leader_id

    # ------------------------------------------------------------------
    # Friend declaration
    # ------------------------------------------------------------------

    def declare_friends(
        self, player_id: str, declarations: list
    ) -> None:
        """Record friend declarations (Find Friends mode only).

        Delegates validation to the mode strategy, stores the declarations,
        and transitions to PLAYING.

        Parameters
        ----------
        player_id:
            Must equal state.round_leader_id (only the leader declares friends).
        declarations:
            List of FriendDeclaration objects; validated by mode strategy.

        Raises
        ------
        ValueError
            On wrong phase, wrong player, or strategy validation failure.
        """
        state = self.state
        if state.phase != GamePhase.FRIEND_DECLARATION:
            raise ValueError(
                f"declare_friends() called in phase {state.phase.value!r}; "
                "expected FRIEND_DECLARATION."
            )
        if player_id != state.round_leader_id:
            raise ValueError(
                f"Only the round leader ({state.round_leader_id!r}) can declare "
                f"friends; got {player_id!r}."
            )

        self.mode.validate_friend_declaration(state, declarations)
        state.friend_declarations = list(declarations)
        state.transition_to(GamePhase.BOTTOM_EXCHANGE)

    # ------------------------------------------------------------------
    # Playing tricks
    # ------------------------------------------------------------------

    def play_cards(self, player_id: str, cards: list[Card]) -> dict:
        """Play cards into the current trick.

        Validates the play, removes cards from the player's hand, appends to
        the current trick, and resolves the trick once all 4 players have
        played.

        Returns a result dict with keys:
          "trick_complete": bool — True when all 4 players have played.
          "trick_winner":   str | None — player_id of winner if trick complete.
          "round_over":     bool — True when all 25 tricks have been played.

        Failed throw (甩牌) handling
        ---------------------------
        A leader's throw whose components can be beaten is NOT rejected.
        Instead the leader is forced to lead only the smallest beatable
        component (fewest cards; tie-break: weakest by max card_order) and
        concedes a penalty of 10 pts per card in the ATTEMPTED throw.  The
        penalty accumulates in state.throw_penalties and is attributed to
        teams at round end (end_round) using FINAL team membership.  When
        this happens the result dict additionally contains:
          "throw_failed":    True
          "attempted_cards": list[Card] — the original throw attempt
          "forced_cards":    list[Card] — what was actually led
          "penalty":         int — points conceded (10 × attempted cards)

        Raises
        ------
        ValueError
            On wrong phase, out-of-turn play, cards not in hand, or illegal
            follow.
        """
        state = self.state
        if state.phase != GamePhase.PLAYING:
            raise ValueError(
                f"play_cards() called in phase {state.phase.value!r}; "
                "expected PLAYING."
            )

        if player_id != state.current_turn_id:
            raise ValueError(
                f"It is not {player_id!r}'s turn; "
                f"expected {state.current_turn_id!r}."
            )

        player = self._player(player_id)

        # Validate cards are in hand
        hand_copy = list(player.hand)
        for card in cards:
            if card not in hand_copy:
                raise ValueError(
                    f"Card {card!r} is not in {player_id!r}'s hand."
                )
            hand_copy.remove(card)

        ctx = state.trump_context
        if ctx is None:
            raise ValueError("Cannot play cards: trump context is not set.")

        is_leader = len(state.current_trick) == 0
        throw_failure: dict | None = None

        if is_leader:
            # Leader can play any valid format
            led_fmt = classify_play(cards, ctx)

            # If it's a throw, check whether any component can be beaten.
            # A failed throw is not rejected: the leader is forced to lead
            # only the smallest beatable component and concedes 10 pts per
            # attempted card (attributed to teams in end_round).
            if isinstance(led_fmt, Throw):
                all_hands = {p.id: p.hand for p in state.players}
                beatable = find_beatable_components(cards, player_id, all_hands, ctx)
                if beatable:
                    penalty = 10 * len(cards)
                    # Smallest beatable component: fewest cards; tie-break
                    # weakest (lowest max card_order).
                    _, forced_cards = min(
                        beatable,
                        key=lambda bc: (
                            len(bc[1]),
                            max(ctx.card_order(c) for c in bc[1]),
                        ),
                    )
                    state.throw_penalties[player_id] = (
                        state.throw_penalties.get(player_id, 0) + penalty
                    )
                    throw_failure = {
                        "throw_failed": True,
                        "attempted_cards": list(cards),
                        "forced_cards": list(forced_cards),
                        "penalty": penalty,
                    }
                    # Substitute the forced component; the rest of the
                    # attempted cards stay in the leader's hand.
                    cards = list(forced_cards)
                    hand_copy = list(player.hand)
                    for card in cards:
                        hand_copy.remove(card)
                    led_fmt = classify_play(cards, ctx)

            state._led_format = led_fmt  # store for followers to check against
            state._led_suit = ctx.effective_suit(cards[0])

        else:
            # Follower must adhere to following rules
            led_fmt = getattr(state, "_led_format", None)
            led_suit = getattr(state, "_led_suit", None)

            if led_fmt is None or led_suit is None:
                raise ValueError("Internal error: led format/suit not set.")

            # Validate follow: check invariants directly (allows any valid follow,
            # not just the single arbitrary option returned by get_legal_plays)
            if not is_valid_follow(cards, player.hand, led_fmt, led_suit, ctx):
                raise ValueError(
                    f"Illegal follow: {player_id!r}'s play does not satisfy "
                    "the following rules for the led format."
                )

        # Remove cards from hand
        player.hand = hand_copy

        # Notify mode strategy of each card played (e.g. friend reveal in Find Friends).
        for card in cards:
            self.mode.resolve_friend(state, player_id, card)

        # Append to current trick
        state.current_trick.append((player_id, list(cards)))

        # Advance turn
        if len(state.current_trick) < NUM_PLAYERS:
            state.current_turn_id = self._next_player_id(player_id)
            result = {"trick_complete": False, "trick_winner": None, "round_over": False}
            if throw_failure:
                result.update(throw_failure)
            return result

        # All 4 players have played — resolve the trick
        led_suit = getattr(state, "_led_suit", ctx.effective_suit(state.current_trick[0][1][0]))
        winner_id = resolve_trick_winner(state.current_trick, led_suit, ctx, state._led_format)

        # Award the trick to the winner
        trick_cards = [c for _, play in state.current_trick for c in play]
        state.tricks_won[winner_id].append(trick_cards)
        # Record the winning play — sets the bottom multiplier at round end (#57)
        state.last_winning_play = next(
            list(play) for pid, play in state.current_trick if pid == winner_id
        )

        # Clear trick state
        state.current_trick = []
        state._led_format = None
        state._led_suit = None
        state.current_leader_id = winner_id
        state.current_turn_id = winner_id
        state.trick_number += 1

        # Update live attacking_points (without bottom-deck multiplier — applied at end_round).
        # Teams are assigned during BOTTOM_EXCHANGE so is_defending is reliable here.
        attacker_ids_live = frozenset(p.id for p in state.players if not p.is_defending)
        state.attacking_points = sum(
            c.point_value
            for pid, tricks in state.tricks_won.items()
            if pid in attacker_ids_live
            for trick in tricks
            for c in trick
        )

        # Check if round is over (all hands empty)
        round_over = all(len(p.hand) == 0 for p in state.players)
        if round_over:
            state.transition_to(GamePhase.SCORING)

        result = {
            "trick_complete": True,
            "trick_winner": winner_id,
            "round_over": round_over,
        }
        if throw_failure:
            result.update(throw_failure)
        return result

    # ------------------------------------------------------------------
    # Round resolution
    # ------------------------------------------------------------------

    def end_round(self) -> dict:
        """Score the round and advance ranks.

        Must be called in the SCORING phase (after all tricks are played).

        Steps
        -----
        1. Determine attacking team from mode strategy.
        2. Count attacking points (with bottom-deck multiplier if applicable),
           then apply failed-throw penalties by FINAL team (defender thrower
           → attackers gain +P; attacker thrower → −P, clamped at ≥ 0).
        3. Determine rank advancement winner and step count.
        4. Advance the winning team's ranks (clamped at ACE).
        5. Check for game over (any player at ACE whose team just defended).
        6. Delegate next-leader selection to mode strategy.
        7. Transition to ROUND_OVER (caller decides GAME_OVER vs next DEALING).

        Returns
        -------
        dict with keys:
          "attacking_points": int
          "winner": "attacking" | "defending"
          "steps": int
          "game_over": bool
          "next_round_leader_id": str | None
        """
        state = self.state
        if state.phase != GamePhase.SCORING:
            raise ValueError(
                f"end_round() called in phase {state.phase.value!r}; "
                "expected SCORING."
            )
        if state.trump_context is None:
            raise ValueError("Cannot score a round with no trump context.")

        ctx = state.trump_context

        # Determine teams from mode strategy
        attacker_ids = self.mode.get_attacker_ids(state)
        defender_ids = {p.id for p in state.players} - attacker_ids

        # Identify last trick
        last_trick_winner_id = state.current_leader_id  # winner of last trick

        # Count attacking points.  The bottom multiplier is set by the WINNING
        # PLAY of the last trick, not the whole 4-player pile (issue #57).
        attacking_pts = count_attacking_points(
            tricks_won=state.tricks_won,
            attacker_ids=attacker_ids,
            bottom_deck=state.bottom_deck,
            last_trick_winner_id=last_trick_winner_id,
            last_trick_cards=state.last_winning_play,
            ctx=ctx,
        )

        # Apply failed-throw penalties using FINAL teams (a thrower may have
        # flipped teams via friend reveal after the throw).  A defender's
        # penalty is gained by the attackers (+P); an attacker's penalty is
        # deducted from attacking points (−P), with the total clamped at 0
        # (only attacker points exist numerically).
        throw_penalty_adjustment = 0
        for pid, penalty in state.throw_penalties.items():
            if pid in attacker_ids:
                throw_penalty_adjustment -= penalty
            else:
                throw_penalty_adjustment += penalty
        attacking_pts = max(0, attacking_pts + throw_penalty_adjustment)
        state.attacking_points = attacking_pts

        # Compute advancement
        winner, steps = compute_rank_advancement(attacking_pts)

        # Capture pre-advance ranks before modifying anything
        pre_advance_ranks = {p.id: p.rank.value for p in state.players}

        # Advance winning team's ranks
        winning_ids = attacker_ids if winner == "attacking" else defender_ids
        for pid in winning_ids:
            self._player(pid).advance_rank(steps)

        # Capture player info (post-rank-advance, pre-team-swap) for round_over message
        round_players = [
            {
                "id": p.id,
                "name": p.name,
                "old_rank": pre_advance_ranks[p.id],
                "rank": p.rank.value,
                "is_defending": p.is_defending,
            }
            for p in state.players
        ]

        # Check game over: defenders WIN the round while ALREADY at ACE going in.
        # Advancing INTO Ace only earns the right to defend it next round, so the
        # check uses pre-advance ranks (issue #52).  "attacking 0" (take over at
        # same rank) means defenders LOST — no game over.
        game_over = False
        if winner == "defending":
            for pid in defender_ids:
                if pre_advance_ranks[pid] == Rank.ACE.value:
                    game_over = True
                    break

        # Let mode strategy update team roles for next round (e.g. swap defenders).
        self.mode.on_round_end(state, winner)

        # Determine next round leader
        next_leader_id = self.mode.get_next_leader(state, winner)
        state.round_leader_id = next_leader_id
        state.round_number += 1

        state.transition_to(GamePhase.ROUND_OVER)
        if game_over:
            state.transition_to(GamePhase.GAME_OVER)

        return {
            "attacking_points": attacking_pts,
            "winner": winner,
            "steps": steps,
            "game_over": game_over,
            "next_round_leader_id": next_leader_id if not game_over else None,
            "round_players": round_players,  # team/rank snapshot for round_over display
            # Net failed-throw penalty applied to attacking points this round
            # (positive: defenders threw badly, attackers gained; negative:
            # attackers threw badly and were deducted, pre-clamp).
            "throw_penalty_adjustment": throw_penalty_adjustment,
        }

    async def deal_all_cards(
        self,
        on_card_dealt: Callable[[str, Card], Awaitable[None]] | None = None,
    ) -> None:
        """Async loop that deals all 100 cards one at a time.

        Parameters
        ----------
        on_card_dealt:
            Optional async callback invoked after each card is dealt.
            Receives (player_id, card).  Use this to push 'card_dealt' events
            over WebSocket.
        """
        while self.state.draw_pile:
            result = self.deal_next_card()
            if result is None:
                break
            player_id, card = result
            if on_card_dealt is not None:
                await on_card_dealt(player_id, card)
            if self.state.draw_pile:
                await asyncio.sleep(self.deal_delay)
