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
from typing import TYPE_CHECKING, Callable, Awaitable

from shengji.models.bid import Bid
from shengji.models.deck import Deck, NUM_PLAYERS, BOTTOM_SIZE, HAND_SIZE
from shengji.models.game_state import GamePhase, GameState
from shengji.models.card import Card, Rank, Suit
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
    ) -> None:
        self.state = state
        self.mode = mode_strategy
        self.deal_delay = deal_delay

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
        if state.phase not in (GamePhase.WAITING, GamePhase.ROUND_OVER):
            state.transition_to(GamePhase.DEALING)  # will raise if illegal

        deck = Deck()
        draw_pile, bottom_deck = deck.prepare_deal()

        state.draw_pile = list(draw_pile)
        state.bottom_deck = list(bottom_deck)
        state.cards_dealt_count = 0

        # Clear per-round fields
        state.bids = []
        state.trump_context = None
        state.current_trick = []
        state.tricks_won = {p.id: [] for p in state.players}
        state.attacking_points = 0
        state.trick_number = 1
        state.current_leader_id = state.round_leader_id
        state.current_turn_id = ""  # not used during dealing

        state.transition_to(GamePhase.DEALING)

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
          • No current bid       → always valid.
          • Strictly stronger    → valid.
          • Same strength (==1)  → valid only when a *different* player bids.
          • Suited pair (2) vs suited pair (2) → NEVER valid (equal strength, no suit rank).
        """
        if current_bid is None:
            return True
        new_str = GameEngine._bid_strength(new_cards)
        cur_str = GameEngine._bid_strength(current_bid.cards)
        if new_str > cur_str:
            return True
        if new_str == cur_str == 1 and new_player_id != current_bid.player_id:
            return True
        return False

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
            # Clear hands before re-dealing.
            for p in state.players:
                p.hand = []
            # Manually set phase back so start_dealing can transition ROUND_OVER→DEALING
            # The simplest approach: reset to WAITING temporarily then call start_dealing.
            # But WAITING→DEALING is valid. We need BIDDING_AFTER_DEAL→DEALING.
            # The transition table allows BIDDING_AFTER_DEAL→DEALING (re-deal case).
            state.transition_to(GamePhase.DEALING)
            # Now reset draw pile / bottom (start_dealing will re-shuffle)
            # To trigger start_dealing from DEALING we need to be in WAITING or ROUND_OVER.
            # Re-set phase to allow start_dealing's guard to pass:
            state.phase = GamePhase.ROUND_OVER  # transient — start_dealing accepts this
            self.start_dealing()
            return

        # Winning bid is the last entry in the bid history.
        winning_bid = state.bids[-1]
        state.round_leader_id = winning_bid.player_id
        state.current_leader_id = winning_bid.player_id
        state.trump_context = winning_bid.resulting_trump
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

        # Step 4: Phase transition
        if self.mode.needs_friend_declaration():
            state.transition_to(GamePhase.FRIEND_DECLARATION)
        else:
            state.transition_to(GamePhase.PLAYING)

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
        state.transition_to(GamePhase.PLAYING)

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
