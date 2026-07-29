"""Shared machinery for the property-based fuzz suite.

Two things live here:

1. A **seeded game driver** (:class:`FuzzDriver`) that plays complete
   random-legal games through the real :class:`GameEngine`, invoking a hook
   after *every* engine action.  Everything is driven from a single
   ``random.Random(seed)`` so any failure is reproducible from its seed.

2. An **independent invariant battery** (:func:`check_invariants` and
   friends).  These deliberately do NOT call ``superuser.inspector.validate_state``
   — they re-derive card conservation, turn/phase coherence, points
   bookkeeping and round-end scoring from the raw GameState so that a bug in
   ``validate_state`` cannot mask a bug in the engine.  The driver runs
   ``validate_state`` too, as a second opinion, and reports its findings under
   a distinct prefix.
"""
from __future__ import annotations

import copy
import os
import random
from collections import Counter
from dataclasses import fields, is_dataclass
from typing import Callable, Iterable

from shengji.engine.engine import GameEngine
from shengji.engine.tricks import get_legal_plays
from shengji.models.card import (
    RANK_ORDER,
    SUITED_SUITS,
    Card,
    Rank,
    Suit,
)
from shengji.models.deck import BOTTOM_SIZE, HAND_SIZE, NUM_DECKS, NUM_PLAYERS, TOTAL_CARDS
from shengji.models.friend_declaration import FriendDeclaration
from shengji.models.game_state import GamePhase, GameState
from shengji.models.groups import Throw, classify_play, find_tractors
from shengji.models.player import Player
from shengji.modes.find_friends import FindFriendsStrategy
from shengji.modes.upgrade import UpgradeStrategy
from shengji.superuser.inspector import validate_state

MODES = ("upgrade", "find_friends")

#: Environment gate for the heavy battery.
HEAVY = os.environ.get("FUZZ") == "1"

MAX_REDEALS = 10


# ---------------------------------------------------------------------------
# The reference deck — built here from first principles, NOT from Deck().
# ---------------------------------------------------------------------------

def _reference_deck() -> Counter:
    """Multiset of every card that must exist in a game, built independently.

    Two copies each of 13 ranks x 4 suits plus two copies of each joker
    == 108 cards.  Written out longhand on purpose: if ``models.deck`` ever
    changes what it deals, this must not change with it.
    """
    counts: Counter = Counter()
    for _ in range(NUM_DECKS):
        for suit in (Suit.SPADES, Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS):
            for rank in RANK_ORDER:
                counts[(suit, rank)] += 1
        counts[(Suit.JOKER, Rank.SMALL_JOKER)] += 1
        counts[(Suit.JOKER, Rank.BIG_JOKER)] += 1
    return counts


REFERENCE_DECK: Counter = _reference_deck()

#: Point value per rank, re-stated independently of ``Card.point_value``.
POINT_VALUES: dict[Rank, int] = {Rank.FIVE: 5, Rank.TEN: 10, Rank.KING: 10}


def point_total(cards: Iterable[Card]) -> int:
    return sum(POINT_VALUES.get(c.rank, 0) for c in cards)


# ---------------------------------------------------------------------------
# Zone enumeration
# ---------------------------------------------------------------------------

def collect_zones(state: GameState) -> dict[str, list[Card]]:
    """Every card-holding zone the engine has, keyed by a readable name.

    Enumerated from the GameState field list:
      - ``hand:<pid>``      player hands
      - ``draw_pile``       undealt cards
      - ``bottom_deck``     the buried 8 (or the pre-exchange bottom)
      - ``trick:<pid>``     cards played into the trick in progress
      - ``won:<pid>``       captured/point piles

    That is the complete list.  Three GameState fields hold Cards but are not
    zones, and counting them would double-count:
      - ``last_winning_play`` — a reference to cards already inside ``tricks_won``
      - ``bids[].cards``      — cards *shown* from hand, never removed from it
      - ``friend_declarations[].card`` — a card *pattern*, not an instance

    There is also no "forced-throw remainder" zone: when a throw is beaten the
    engine leads only the forced component and the rest of the attempt stays in
    the leader's hand (asserted in :meth:`FuzzDriver.check_forced_throw`).
    """
    zones: dict[str, list[Card]] = {}
    for p in state.players:
        zones[f"hand:{p.id}"] = list(p.hand)
    zones["draw_pile"] = list(state.draw_pile)
    zones["bottom_deck"] = list(state.bottom_deck)
    for pid, play in state.current_trick:
        zones.setdefault(f"trick:{pid}", []).extend(play)
    for pid, tricks in state.tricks_won.items():
        pile: list[Card] = []
        for trick in tricks:
            pile.extend(trick)
        zones[f"won:{pid}"] = pile
    return zones


def _zone_summary(zones: dict[str, list[Card]]) -> str:
    return ", ".join(f"{k}={len(v)}" for k, v in zones.items() if v)


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

def check_card_conservation(state: GameState) -> list[str]:
    """The union of all zones is exactly the 108-card double deck.

    Because the comparison is a multiset equality against the reference deck,
    this simultaneously proves *zone exclusivity*: a card duplicated into two
    zones raises its count above 2 (or displaces another card), and a card
    lost from every zone drops its count below 2.  Both show up as a diff.
    """
    if state.phase == GamePhase.WAITING:
        return []  # no cards exist before the first deal

    zones = collect_zones(state)
    seen: Counter = Counter()
    for cards in zones.values():
        for c in cards:
            seen[(c.suit, c.rank)] += 1

    violations: list[str] = []
    total = sum(seen.values())
    if total != TOTAL_CARDS:
        violations.append(
            f"card conservation: {total} cards across zones, expected {TOTAL_CARDS} "
            f"({_zone_summary(zones)})"
        )
    if seen != REFERENCE_DECK:
        missing = REFERENCE_DECK - seen
        extra = seen - REFERENCE_DECK
        parts = []
        if missing:
            parts.append("missing " + ", ".join(
                f"{r.value}{s.value}x{n}" for (s, r), n in sorted(
                    missing.items(), key=lambda kv: str(kv[0]))))
        if extra:
            parts.append("extra " + ", ".join(
                f"{r.value}{s.value}x{n}" for (s, r), n in sorted(
                    extra.items(), key=lambda kv: str(kv[0]))))
        violations.append("card conservation: deck multiset differs — " + "; ".join(parts))
    return violations


def check_turn_and_phase(state: GameState) -> list[str]:
    """Turn pointers, trick shape and hand sizes are coherent for the phase."""
    violations: list[str] = []
    ids = [p.id for p in state.players]
    id_set = set(ids)

    if len(id_set) != NUM_PLAYERS:
        violations.append(f"seating: expected {NUM_PLAYERS} distinct players, got {ids}")

    if state.round_leader_id and state.round_leader_id not in id_set:
        violations.append(f"round_leader_id {state.round_leader_id!r} is not seated")
    if state.current_leader_id and state.current_leader_id not in id_set:
        violations.append(f"current_leader_id {state.current_leader_id!r} is not seated")

    # --- trick shape ---------------------------------------------------
    if len(state.current_trick) > NUM_PLAYERS:
        violations.append(
            f"trick size {len(state.current_trick)} exceeds {NUM_PLAYERS} players"
        )
    trick_players = [pid for pid, _ in state.current_trick]
    if len(set(trick_players)) != len(trick_players):
        violations.append(f"a player played twice in one trick: {trick_players}")
    for pid in trick_players:
        if pid not in id_set:
            violations.append(f"trick contains play by unseated player {pid!r}")
    # Every play in a trick has the same card count as the lead.
    if state.current_trick:
        lead_n = len(state.current_trick[0][1])
        for pid, play in state.current_trick[1:]:
            if len(play) != lead_n:
                violations.append(
                    f"follow by {pid!r} has {len(play)} cards, lead had {lead_n}"
                )
        if lead_n == 0:
            violations.append("lead play is empty")
    # Seating order: after the leader, plays proceed counter-clockwise.
    if len(state.current_trick) > 1:
        start = ids.index(trick_players[0])
        expected = [ids[(start + i) % NUM_PLAYERS] for i in range(len(trick_players))]
        if trick_players != expected:
            violations.append(
                f"trick play order {trick_players} is not counter-clockwise from "
                f"{trick_players[0]!r} (expected {expected})"
            )

    # led_format/led_suit exist exactly while a trick is in progress.
    if state.current_trick and (state.led_format is None or state.led_suit is None):
        violations.append("trick in progress but led_format/led_suit is unset")
    if not state.current_trick and (
        state.led_format is not None or state.led_suit is not None
    ):
        violations.append("no trick in progress but led_format/led_suit is still set")

    # --- phase-specific --------------------------------------------------
    if state.phase == GamePhase.PLAYING:
        if state.current_turn_id not in id_set:
            violations.append(f"current_turn_id {state.current_turn_id!r} is not seated")
        elif state.current_trick:
            expected_turn = ids[(ids.index(trick_players[-1]) + 1) % NUM_PLAYERS]
            if state.current_turn_id != expected_turn:
                violations.append(
                    f"current_turn_id is {state.current_turn_id!r}; after "
                    f"{trick_players[-1]!r} played it should be {expected_turn!r}"
                )
        if not 1 <= state.trick_number <= HAND_SIZE + 1:
            violations.append(
                f"trick_number {state.trick_number} outside 1..{HAND_SIZE + 1}"
            )
        # Hand sizes: everyone holds the same count, less what they have already
        # committed to the trick in progress.
        played = {pid: len(play) for pid, play in state.current_trick}
        restored = {p.id: len(p.hand) + played.get(p.id, 0) for p in state.players}
        if len(set(restored.values())) != 1:
            violations.append(
                f"uneven hands: hand+committed sizes {restored} should all be equal"
            )

    for p in state.players:
        if len(p.hand) > HAND_SIZE:
            violations.append(f"{p.id!r} holds {len(p.hand)} cards (max {HAND_SIZE})")
        if len(p.hand) < 0:
            violations.append(f"{p.id!r} has a negative hand size")

    if state.phase in (
        GamePhase.BOTTOM_EXCHANGE,
        GamePhase.FRIEND_DECLARATION,
        GamePhase.PLAYING,
        GamePhase.SCORING,
    ) and state.trump_context is None:
        violations.append(f"phase {state.phase.value!r} requires a trump context")

    if state.phase == GamePhase.PLAYING and len(state.bottom_deck) != BOTTOM_SIZE:
        violations.append(
            f"bottom deck holds {len(state.bottom_deck)} cards during play "
            f"(expected {BOTTOM_SIZE})"
        )

    if state.attacking_points < 0:
        violations.append(f"attacking_points is negative ({state.attacking_points})")

    for pid, penalty in state.throw_penalties.items():
        if pid not in id_set:
            violations.append(f"throw penalty recorded for unseated player {pid!r}")
        if penalty < 0 or penalty % 10 != 0:
            violations.append(f"throw penalty {penalty} for {pid!r} is not a positive 10x")

    return violations


def check_live_points(state: GameState) -> list[str]:
    """``attacking_points`` equals the points in attackers' captured piles.

    This is the *live* bookkeeping invariant, valid from the start of a round
    up to (but not including) ``end_round``, which folds in the bottom-deck
    multiplier and throw penalties.  "Attackers" means the current
    ``is_defending`` flags, so a Find Friends reveal that flips a player must
    be re-attributed immediately for this to hold.
    """
    attackers = {p.id for p in state.players if not p.is_defending}
    expected = 0
    for pid, tricks in state.tricks_won.items():
        if pid in attackers:
            for trick in tricks:
                expected += point_total(trick)
    if state.attacking_points != expected:
        return [
            f"attacking_points is {state.attacking_points} but attackers "
            f"{sorted(attackers)} hold {expected} points in captured piles "
            f"(piles: { {pid: point_total(c for t in ts for c in t) for pid, ts in state.tricks_won.items()} })"
        ]
    return []


def check_invariants(
    state: GameState,
    *,
    live_points: str = "boundary",
) -> list[str]:
    """Run the full independent battery, then validate_state as a cross-check.

    ``live_points`` selects when :func:`check_live_points` applies:

    ``"boundary"``
        Only between tricks.  The engine recomputes unconditionally at every
        trick resolution, so this is the invariant that genuinely holds today.
    ``"always"``
        Also mid-trick.  Issue #43 promises immediate re-attribution the moment
        a Find Friends reveal flips a player, so this *should* hold too — it
        does not (see FINDING-1 in test_invariants.py).
    ``"off"``
        Skip; used after ``end_round`` folds in the bottom multiplier and
        throw penalties.
    """
    violations = check_card_conservation(state)
    violations += check_turn_and_phase(state)
    if live_points == "always" or (live_points == "boundary" and not state.current_trick):
        violations += check_live_points(state)
    violations += [f"validate_state: {v}" for v in validate_state(state)]
    return violations


# ---------------------------------------------------------------------------
# Round-end (scoring) verification
# ---------------------------------------------------------------------------

#: Advancement bands, transcribed from the table in engine/scoring.py's
#: docstring rather than from its code.
def expected_advancement(points: int) -> tuple[str, int]:
    if points < 80:
        # exactly 0 -> 5 (true shutout, D28); 1-19 -> 4, 20-39 -> 3,
        # 40-59 -> 2, 60-79 -> 1
        steps = (80 - points + 19) // 20
        return ("defending", steps + 1 if points == 0 else steps)
    # 80-99 -> 0, 100-119 -> 1, 120-139 -> 2, 140+ -> 3 (capped)
    return ("attacking", min(3, (points - 80) // 20))


def advance(rank: Rank, steps: int) -> Rank:
    idx = min(RANK_ORDER.index(rank) + steps, len(RANK_ORDER) - 1)
    return RANK_ORDER[idx]


def _largest_identity_run(cards: list[Card]) -> int | None:
    """Card count of the play's largest component, when we can be sure of it.

    Returns None when the play's shape is ambiguous without re-implementing
    the engine's tractor detection, in which case callers fall back to a
    bounds check on the multiplier.
    """
    if len(cards) == 1:
        return 1
    identities = Counter((c.suit, c.rank) for c in cards)
    if len(identities) == 1:
        return len(cards)  # pure pair / triple / quad
    return None


class RoundSnapshot:
    """Everything needed to re-derive a round's score, captured pre-``end_round``."""

    def __init__(self, state: GameState) -> None:
        self.attackers = {p.id for p in state.players if not p.is_defending}
        self.defenders = {p.id for p in state.players if p.is_defending}
        self.tricks_won = copy.deepcopy(state.tricks_won)
        self.bottom_deck = list(state.bottom_deck)
        self.last_winning_play = list(state.last_winning_play)
        self.last_trick_winner = state.current_leader_id
        self.throw_penalties = dict(state.throw_penalties)
        self.ranks = {p.id: p.rank for p in state.players}
        self.round_number = state.round_number


def check_round_end(
    snap: RoundSnapshot, summary: dict, state: GameState
) -> list[str]:
    """Verify the scoring the engine reported against an independent re-derivation."""
    violations: list[str] = []

    base = 0
    for pid, tricks in snap.tricks_won.items():
        if pid in snap.attackers:
            for trick in tricks:
                base += point_total(trick)

    bottom_pts = point_total(snap.bottom_deck)
    adjustment = 0
    for pid, penalty in snap.throw_penalties.items():
        adjustment += -penalty if pid in snap.attackers else penalty

    reported = summary["attacking_points"]
    if reported != state.attacking_points:
        violations.append(
            f"end_round returned {reported} points but state.attacking_points "
            f"is {state.attacking_points}"
        )
    if summary.get("throw_penalty_adjustment", 0) != adjustment:
        violations.append(
            f"throw_penalty_adjustment is {summary.get('throw_penalty_adjustment')}, "
            f"expected {adjustment} from penalties {snap.throw_penalties} "
            f"(attackers {sorted(snap.attackers)})"
        )

    attacker_took_last = snap.last_trick_winner in snap.attackers
    if not attacker_took_last or bottom_pts == 0:
        expected = max(0, base + adjustment)
        if reported != expected:
            violations.append(
                f"points: reported {reported}, expected {expected} "
                f"(base {base} + penalty adj {adjustment}, no bottom bonus: "
                f"last trick to {snap.last_trick_winner!r}, bottom worth {bottom_pts})"
            )
    else:
        known = _largest_identity_run(snap.last_winning_play)
        if known is not None:
            multiplier = min(8, 2 * known)
            expected = max(0, base + multiplier * bottom_pts + adjustment)
            if reported != expected:
                violations.append(
                    f"points: reported {reported}, expected {expected} "
                    f"(base {base} + {multiplier}x bottom {bottom_pts} + adj "
                    f"{adjustment}; winning play {snap.last_winning_play})"
                )
        else:
            candidates = {
                max(0, base + m * bottom_pts + adjustment) for m in (2, 4, 6, 8)
            }
            if reported not in candidates:
                violations.append(
                    f"points: reported {reported} is not base {base} + adj "
                    f"{adjustment} + any legal bottom multiplier x {bottom_pts} "
                    f"(candidates {sorted(candidates)}; winning play "
                    f"{snap.last_winning_play})"
                )

    # --- advancement -----------------------------------------------------
    winner, steps = expected_advancement(reported)
    if summary["winner"] != winner or summary["steps"] != steps:
        violations.append(
            f"advancement: engine says {summary['winner']}/+{summary['steps']} for "
            f"{reported} points; band table says {winner}/+{steps}"
        )

    winning_ids = snap.attackers if summary["winner"] == "attacking" else snap.defenders
    for p in state.players:
        old = snap.ranks[p.id]
        want = advance(old, summary["steps"]) if p.id in winning_ids else old
        if p.rank != want:
            side = "winning" if p.id in winning_ids else "losing"
            violations.append(
                f"rank: {p.id!r} ({side} team) went {old.value} -> {p.rank.value}, "
                f"expected {want.value} after +{summary['steps']}"
            )

    expected_game_over = summary["winner"] == "defending" and any(
        snap.ranks[pid] == Rank.ACE for pid in snap.defenders
    )
    if bool(summary["game_over"]) != expected_game_over:
        violations.append(
            f"game_over is {summary['game_over']}, expected {expected_game_over} "
            f"(winner {summary['winner']}, defender ranks "
            f"{ {pid: snap.ranks[pid].value for pid in snap.defenders} })"
        )

    if summary["game_over"]:
        if state.phase != GamePhase.GAME_OVER:
            violations.append(f"game over but phase is {state.phase.value!r}")
    else:
        if state.phase != GamePhase.ROUND_OVER:
            violations.append(f"round ended but phase is {state.phase.value!r}")
        if state.round_leader_id != summary["next_round_leader_id"]:
            violations.append(
                f"next leader mismatch: state {state.round_leader_id!r} vs summary "
                f"{summary['next_round_leader_id']!r}"
            )
    if state.round_number != snap.round_number + 1:
        violations.append(
            f"round_number went {snap.round_number} -> {state.round_number}"
        )
    return violations


# ---------------------------------------------------------------------------
# State fingerprinting (for "rejection must not mutate" checks)
# ---------------------------------------------------------------------------

def _freeze(value):
    if isinstance(value, Card):
        return ("Card", value.suit.value, value.rank.value)
    if is_dataclass(value) and not isinstance(value, type):
        return (type(value).__name__,) + tuple(
            (f.name, _freeze(getattr(value, f.name))) for f in fields(value)
        )
    if isinstance(value, dict):
        return ("dict",) + tuple(
            sorted((repr(k), _freeze(v)) for k, v in value.items())
        )
    if isinstance(value, set) or isinstance(value, frozenset):
        return ("set",) + tuple(sorted(repr(v) for v in value))
    if isinstance(value, (list, tuple)):
        return (type(value).__name__,) + tuple(_freeze(v) for v in value)
    return repr(value)


def fingerprint(engine: GameEngine):
    """A total, order-sensitive fingerprint of engine + state + strategy.

    Covers every GameState field (hands in order, draw pile, bottom, tricks,
    bids, penalties, phase, turn pointers) *and* the mode strategy's private
    bookkeeping (Find Friends' per-card play counts), which is mutable state
    a rejected action could corrupt just as easily.
    """
    return (
        _freeze(engine.state),
        _freeze(engine.mode.__dict__),
    )


_SNAPSHOT_CACHE: dict[tuple[int, str], list[tuple[str, GameEngine]]] = {}


def harvest_snapshots(seed: int, mode: str) -> list[tuple[str, GameEngine]]:
    """Deep copies of reachable engine states, one per checkpoint of a game.

    Every state here was produced by the real engine through a legal sequence
    of actions, so an adversarial action fired at one is being fired at a state
    the engine genuinely reaches in play.  Results are cached per (seed, mode);
    callers must not mutate the returned engines — copy first.
    """
    key = (seed, mode)
    if key in _SNAPSHOT_CACHE:
        return _SNAPSHOT_CACHE[key]

    collected: list[tuple[str, GameEngine]] = []
    seen: set[str] = set()

    def grab(label: str, engine: GameEngine) -> None:
        if label in seen:
            return
        seen.add(label)
        collected.append((label, copy.deepcopy(engine)))

    FuzzDriver(
        seed, mode, max_rounds=1, deal_check_every=100, on_snapshot=grab
    ).run()
    _SNAPSHOT_CACHE[key] = collected
    return collected


# ---------------------------------------------------------------------------
# Random-legal bot
# ---------------------------------------------------------------------------

class RandomBot:
    """Picks uniformly among legal options; occasionally attempts a throw."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng

    def bid_options(self, hand: list[Card], trump_rank: Rank) -> list[list[Card]]:
        opts: list[list[Card]] = []
        by_suit = Counter(c.suit for c in hand if c.rank == trump_rank)
        for suit, n in by_suit.items():
            card = Card(suit=suit, rank=trump_rank)
            opts.append([card])
            if n >= 2:
                opts.append([card, card])
        for jr in (Rank.SMALL_JOKER, Rank.BIG_JOKER):
            if sum(1 for c in hand if c.rank == jr) >= 2:
                j = Card(suit=Suit.JOKER, rank=jr)
                opts.append([j, j])
        return opts

    def maybe_bid(self, engine: GameEngine, player: Player, force: bool) -> list[Card] | None:
        state = engine.state
        trump_rank = next(
            p.rank for p in state.players if p.id == state.round_leader_id
        )
        current = state.bids[-1] if state.bids else None
        opts = [
            o
            for o in self.bid_options(player.hand, trump_rank)
            if GameEngine._can_overtake(o, player.id, current)
        ]
        if not opts:
            return None
        if not force and self.rng.random() > 0.8:
            return None
        return self.rng.choice(opts)

    def friend_declaration(self, engine: GameEngine) -> list[FriendDeclaration]:
        ctx = engine.state.trump_context
        candidates = [
            Card(suit=s, rank=r)
            for s in SUITED_SUITS
            for r in RANK_ORDER
            if r != ctx.trump_rank and (ctx.trump_suit is None or s != ctx.trump_suit)
        ]
        return [
            FriendDeclaration(
                card=self.rng.choice(candidates),
                ordinal=self.rng.choice([1, 1, 1, 2]),
            )
        ]

    def bury(self, engine: GameEngine) -> list[Card]:
        state = engine.state
        leader = next(p for p in state.players if p.id == state.round_leader_id)
        combined = list(leader.hand) + list(state.bottom_deck)
        return self.rng.sample(combined, BOTTOM_SIZE)

    def lead_options(self, hand: list[Card], ctx) -> list[list[Card]]:
        opts: list[list[Card]] = [[c] for c in hand]
        counts = Counter(hand)
        opts += [[c, c] for c, n in counts.items() if n >= 2]
        opts += find_tractors(hand, ctx)
        # D16: a lead must be a single effective suit, so a cross-suit
        # candidate would just be rejected by the engine.  Singles and pairs
        # are single-suit by construction; this only bites if find_tractors
        # ever hands back a cross-suit tractor (audit F1).
        return [o for o in opts if len({ctx.effective_suit(c) for c in o}) == 1]

    def choose_play(self, engine: GameEngine, player: Player) -> list[Card]:
        state = engine.state
        ctx = state.trump_context
        if not state.current_trick:
            if self.rng.random() < 0.10:  # try a throw now and then
                suits = {ctx.effective_suit(c) for c in player.hand}
                suit = self.rng.choice(sorted(suits))
                suited = [c for c in player.hand if ctx.effective_suit(c) == suit]
                if len(suited) >= 2:
                    k = self.rng.randint(2, min(6, len(suited)))
                    cand = self.rng.sample(suited, k)
                    if isinstance(classify_play(cand, ctx), Throw):
                        return cand
            opts = self.lead_options(player.hand, ctx)
            weights = [3 if len(o) > 1 else 1 for o in opts]
            return self.rng.choices(opts, weights=weights, k=1)[0]
        legal = get_legal_plays(player.hand, state.led_format, state.led_suit, ctx)
        if not legal:
            raise AssertionError(
                f"get_legal_plays returned nothing for {player.id} "
                f"(hand={player.hand}, led={state.led_format}, suit={state.led_suit})"
            )
        return self.rng.choice(legal)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

class FuzzFailure(AssertionError):
    """Carries the seed, mode and action log needed to reproduce a failure."""


class FuzzDriver:
    """Plays complete bot games, checking invariants after every engine action.

    Parameters
    ----------
    seed, mode:
        Everything (deal, bidding, plays) derives from ``random.Random(seed)``,
        so ``FuzzDriver(seed, mode).run()`` is a complete repro recipe.
    max_rounds:
        Stop after this many rounds even if nobody has reached Ace.
    deal_check_every:
        Run the invariant battery after every N-th dealt card.  Dealing is 100
        near-identical actions per round; checking each one is pure cost in the
        light suite.  Heavy mode passes 1.
    on_snapshot:
        Optional callback ``(label, engine) -> None`` invoked at interesting
        checkpoints; used by the adversarial suite to harvest reachable states.
    """

    def __init__(
        self,
        seed: int,
        mode: str,
        *,
        max_rounds: int = 4,
        deal_check_every: int = 25,
        strict_live_points: bool = False,
        on_snapshot: Callable[[str, GameEngine], None] | None = None,
    ) -> None:
        self.seed = seed
        self.mode = mode
        self.max_rounds = max_rounds
        self.deal_check_every = deal_check_every
        self.strict_live_points = strict_live_points
        self.on_snapshot = on_snapshot

        self.rng = random.Random(seed)
        self.bot = RandomBot(self.rng)
        self.log: list[str] = []
        self.rounds_played = 0
        self.tricks_played = 0
        self.throw_failures = 0
        self.checks = 0

        players = [Player(id=f"p{i}", name=f"P{i}") for i in range(NUM_PLAYERS)]
        strategy = FindFriendsStrategy() if mode == "find_friends" else UpgradeStrategy()
        self.state = GameState(players=players, mode=mode, round_leader_id="p0")
        self.engine = GameEngine(self.state, strategy, deal_delay=0, rng=self.rng)

    # -- plumbing ---------------------------------------------------------

    def _player(self, pid: str) -> Player:
        return next(p for p in self.state.players if p.id == pid)

    def _record(self, action: str) -> None:
        self.log.append(f"r{self.state.round_number} t{self.state.trick_number} {action}")

    def fail(self, label: str, violations: list[str]) -> None:
        tail = "\n    ".join(self.log[-25:])
        raise FuzzFailure(
            f"\nseed={self.seed} mode={self.mode} at [{label}] "
            f"(phase={self.state.phase.value})\n"
            + "\n".join(f"  VIOLATION: {v}" for v in violations)
            + f"\n  repro: FuzzDriver({self.seed}, {self.mode!r}).run()"
            + f"\n  last actions:\n    {tail}"
        )

    def verify(self, label: str, *, live_points: str | None = None) -> None:
        self.checks += 1
        if live_points is None:
            live_points = "always" if self.strict_live_points else "boundary"
        violations = check_invariants(self.state, live_points=live_points)
        if violations:
            self.fail(label, violations)

    def snapshot(self, label: str) -> None:
        if self.on_snapshot is not None:
            self.on_snapshot(label, self.engine)

    # -- phases -----------------------------------------------------------

    def deal_and_bid(self) -> None:
        state, engine = self.state, self.engine
        for redeal in range(MAX_REDEALS):
            engine.start_dealing()
            self._record("start_dealing")
            self.verify("after start_dealing")
            dealt = 0
            while engine.deal_next_card() is not None:
                dealt += 1
                if dealt % self.deal_check_every == 0:
                    self.verify(f"after dealing card {dealt}")
            self._record(f"dealt {dealt} cards")
            self.verify("after deal")
            self.snapshot("bidding")

            order = list(state.players)
            self.rng.shuffle(order)
            for i, p in enumerate(order):
                force = (
                    redeal == MAX_REDEALS - 1
                    and i == len(order) - 1
                    and not state.bids
                )
                cards = self.bot.maybe_bid(engine, p, force)
                if cards is None:
                    continue
                engine.place_bid(p.id, cards)
                self._record(f"{p.id} bids {cards}")
                self.verify(f"after bid by {p.id}")
                self.snapshot("bidding_with_bid_on_record")

            engine.close_bidding()
            self._record("close_bidding")
            self.verify("after close_bidding")
            if state.phase != GamePhase.DEALING:
                return
            self._record("no bids — re-dealing")
        raise FuzzFailure(
            f"seed={self.seed} mode={self.mode}: no bid after {MAX_REDEALS} re-deals"
        )

    def declare_friends(self) -> None:
        if self.state.phase != GamePhase.FRIEND_DECLARATION:
            return
        self.snapshot("friend_declaration")
        decls = self.bot.friend_declaration(self.engine)
        self.engine.declare_friends(self.state.round_leader_id, decls)
        self._record(
            "declare_friends "
            + ", ".join(f"{d.card!r}#{d.ordinal}" for d in decls)
        )
        self.verify("after declare_friends")

    def exchange(self) -> None:
        self.snapshot("bottom_exchange")
        buried = self.bot.bury(self.engine)
        self.engine.exchange_bottom(self.state.round_leader_id, buried)
        self._record(f"exchange_bottom buries {buried}")
        self.verify("after exchange_bottom")

    def play_tricks(self) -> None:
        state, engine = self.state, self.engine
        snapshot_targets = {1, 2, 5, 13, HAND_SIZE}
        while state.phase == GamePhase.PLAYING:
            pid = state.current_turn_id
            player = self._player(pid)
            if state.trick_number in snapshot_targets:
                self.snapshot(
                    f"playing_trick{state.trick_number}_seat{len(state.current_trick)}"
                )
            hand_before = list(player.hand)
            penalty_before = state.throw_penalties.get(pid, 0)
            cards = self.bot.choose_play(engine, player)
            result = engine.play_cards(pid, cards)
            if result.get("throw_failed"):
                self.throw_failures += 1
                self._record(
                    f"{pid} THROW FAILED {result['attempted_cards']} -> forced "
                    f"{result['forced_cards']} (penalty {result['penalty']})"
                )
                self.check_forced_throw(
                    pid, hand_before, penalty_before, cards, result
                )
            else:
                self._record(f"{pid} plays {cards}")
            self.verify(f"after play by {pid}")
            if result["trick_complete"]:
                self.tricks_played += 1
                self._record(f"trick to {result['trick_winner']}")

    def check_forced_throw(
        self,
        pid: str,
        hand_before: list[Card],
        penalty_before: int,
        attempted: list[Card],
        result: dict,
    ) -> None:
        """Verify the documented failed-throw contract (engine.py docstring).

        A beatable throw is not rejected: the leader is forced to lead the
        smallest beatable component, concedes 10 points per card in the
        *attempted* throw, and keeps the rest of the attempt in hand.  That
        last clause is why there is no separate "forced-throw remainder" zone
        to conserve — the remainder never leaves the leader's hand.
        """
        violations: list[str] = []
        forced = result["forced_cards"]
        attempted_by_engine = result["attempted_cards"]
        penalty = result["penalty"]

        if Counter(map(repr, attempted_by_engine)) != Counter(map(repr, attempted)):
            violations.append(
                f"attempted_cards {attempted_by_engine} != what was played {attempted}"
            )
        forced_counts = Counter(map(repr, forced))
        attempted_counts = Counter(map(repr, attempted))
        if forced_counts - attempted_counts:
            violations.append(
                f"forced cards {forced} are not a subset of the attempt {attempted}"
            )
        if not 1 <= len(forced) <= len(attempted):
            violations.append(
                f"forced {len(forced)} cards from a {len(attempted)}-card attempt"
            )
        if penalty != 10 * len(attempted):
            violations.append(
                f"penalty {penalty} != 10 x {len(attempted)} attempted cards"
            )
        delta = self.state.throw_penalties.get(pid, 0) - penalty_before
        if delta != penalty:
            violations.append(
                f"throw_penalties[{pid!r}] moved by {delta}, expected {penalty}"
            )
        # The unplayed part of the attempt must still be in hand.
        player = self._player(pid)
        expected_hand = Counter(map(repr, hand_before)) - forced_counts
        if Counter(map(repr, player.hand)) != expected_hand:
            violations.append(
                f"hand after forced throw is {sorted(map(repr, player.hand))}, "
                f"expected the pre-play hand minus only {forced}"
            )
        if violations:
            self.fail(f"forced throw by {pid}", violations)

    def finish_round(self) -> dict:
        self.snapshot("scoring")
        snap = RoundSnapshot(self.state)
        summary = self.engine.end_round()
        self._record(
            f"end_round: {summary['winner']} +{summary['steps']} "
            f"({summary['attacking_points']} pts)"
        )
        violations = check_round_end(snap, summary, self.state)
        # After scoring, attacking_points includes the bottom multiplier and
        # penalties, so the live-pile equality no longer applies.
        violations += check_invariants(self.state, live_points="off")
        if violations:
            self.fail("after end_round", violations)
        self.snapshot("round_over")
        return summary

    # -- entry point -------------------------------------------------------

    def run(self) -> dict:
        for _ in range(self.max_rounds):
            self.deal_and_bid()
            self.declare_friends()
            self.exchange()
            self.play_tricks()
            summary = self.finish_round()
            self.rounds_played += 1
            if summary["game_over"]:
                return {
                    "game_over": True,
                    "rounds": self.rounds_played,
                    "checks": self.checks,
                }
        return {
            "game_over": False,
            "rounds": self.rounds_played,
            "checks": self.checks,
        }
