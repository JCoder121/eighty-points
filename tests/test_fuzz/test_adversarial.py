"""Adversarial action fuzz: junk actions fired at reachable mid-game states.

Every state used here was produced by the real engine through a legal sequence
of actions (see :func:`fuzz_helpers.harvest_snapshots`).  Against each one we
fire malformed, out-of-phase and impossible actions and require two things:

1. the engine **rejects cleanly** — a ``ValueError`` (or, for type-junk, a
   ``TypeError``/``AttributeError``), never a hang, an assertion, or silent
   acceptance; and
2. the engine **does not mutate** — a total fingerprint of the GameState *and*
   the mode strategy's private bookkeeping is identical before and after.

Rejection-without-rollback is the failure mode this suite exists to catch: an
action that half-applies before noticing it is illegal leaves a game that
nothing downstream can trust.

Findings
--------
FINDING-2 (fixed) — ``exchange_bottom`` used to move the bottom deck into the
leader's hand *before* validating the cards to bury, so a rejected exchange
left a 33-card hand and an empty bottom.  All validation now precedes any
mutation; the two ``exchange_*`` junk items below guard that.

Running
-------
    python -m pytest tests/test_fuzz/test_adversarial.py -q
    FUZZ=1 python -m pytest tests/test_fuzz/test_adversarial.py -q   # more seeds
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Callable

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from shengji.engine.engine import GameEngine
from shengji.models.card import RANK_ORDER, SUITED_SUITS, Card, Rank, Suit
from shengji.models.friend_declaration import FriendDeclaration
from shengji.models.game_state import GamePhase, GameState
from shengji.models.player import Player

from tests.test_fuzz.fuzz_helpers import (
    HEAVY,
    MODES,
    check_invariants,
    fingerprint,
    harvest_snapshots,
)

SEEDS = [0, 1, 2, 3, 4] if HEAVY else [0]

GHOST = "no-such-player"


# ---------------------------------------------------------------------------
# Small state probes
# ---------------------------------------------------------------------------

def _leader(state: GameState) -> Player:
    return next(p for p in state.players if p.id == state.round_leader_id)


def _turn_player(state: GameState) -> Player | None:
    return next((p for p in state.players if p.id == state.current_turn_id), None)


def _someone_else(state: GameState, pid: str) -> Player:
    return next(p for p in state.players if p.id != pid)


def _card_not_held(hand: list[Card]) -> Card | None:
    """Any real deck card absent from *hand*."""
    for suit in SUITED_SUITS:
        for rank in RANK_ORDER:
            card = Card(suit=suit, rank=rank)
            if card not in hand:
                return card
    for rank in (Rank.SMALL_JOKER, Rank.BIG_JOKER):
        card = Card(suit=Suit.JOKER, rank=rank)
        if card not in hand:
            return card
    return None


def _singleton_in_hand(hand: list[Card]) -> Card | None:
    """A card held exactly once — playing two of it is a fabricated duplicate."""
    for card in hand:
        if hand.count(card) == 1:
            return card
    return None


def _trump_rank(state: GameState) -> Rank:
    return _leader(state).rank


# ---------------------------------------------------------------------------
# Junk action registry
# ---------------------------------------------------------------------------

@dataclass
class Junk:
    """One malformed action, plus how to build it from a live engine.

    ``build`` returns a zero-argument callable to invoke, or ``None`` when this
    particular state cannot express the attack (wrong phase, or the state
    happens not to contain the ingredients).
    """

    name: str
    build: Callable[[GameEngine], Callable[[], object] | None]
    expect: tuple[type, ...] = (ValueError,)
    modes: tuple[str, ...] = MODES
    note: str = ""


JUNK: list[Junk] = []


def junk(name: str, *, expect=(ValueError,), modes=MODES, note: str = ""):
    def register(fn):
        JUNK.append(Junk(name=name, build=fn, expect=tuple(expect), modes=tuple(modes), note=note))
        return fn

    return register


# --- PLAYING: who and what ------------------------------------------------

@junk("play_out_of_turn", note="a seated player who is not on turn plays")
def _(engine):
    state = engine.state
    if state.phase != GamePhase.PLAYING:
        return None
    other = _someone_else(state, state.current_turn_id)
    if not other.hand:
        return None
    return lambda: engine.play_cards(other.id, [other.hand[0]])


@junk("play_by_nonexistent_player")
def _(engine):
    state = engine.state
    if state.phase != GamePhase.PLAYING:
        return None
    turn = _turn_player(state)
    if turn is None or not turn.hand:
        return None
    return lambda: engine.play_cards(GHOST, [turn.hand[0]])


@junk("play_card_not_in_hand")
def _(engine):
    state = engine.state
    if state.phase != GamePhase.PLAYING:
        return None
    turn = _turn_player(state)
    if turn is None:
        return None
    card = _card_not_held(turn.hand)
    if card is None:
        return None
    return lambda: engine.play_cards(turn.id, [card])


@junk("play_fabricated_duplicate", note="two copies of a card held only once")
def _(engine):
    state = engine.state
    if state.phase != GamePhase.PLAYING:
        return None
    turn = _turn_player(state)
    if turn is None:
        return None
    card = _singleton_in_hand(turn.hand)
    if card is None:
        return None
    return lambda: engine.play_cards(turn.id, [card, card])


@junk("play_empty_hand_of_cards")
def _(engine):
    state = engine.state
    if state.phase != GamePhase.PLAYING:
        return None
    turn = _turn_player(state)
    if turn is None:
        return None
    return lambda: engine.play_cards(turn.id, [])


@junk("follow_with_wrong_card_count", note="follower plays one card too many")
def _(engine):
    state = engine.state
    if state.phase != GamePhase.PLAYING or not state.current_trick:
        return None
    turn = _turn_player(state)
    if turn is None:
        return None
    wanted = len(state.current_trick[0][1]) + 1
    if len(turn.hand) < wanted:
        return None
    cards = turn.hand[:wanted]
    return lambda: engine.play_cards(turn.id, cards)


@junk("lead_more_cards_than_held")
def _(engine):
    state = engine.state
    if state.phase != GamePhase.PLAYING or state.current_trick:
        return None
    turn = _turn_player(state)
    if turn is None:
        return None
    extra = _card_not_held(turn.hand)
    if extra is None or not turn.hand:
        return None
    cards = list(turn.hand) + [extra]
    return lambda: engine.play_cards(turn.id, cards)


@junk("play_in_wrong_phase")
def _(engine):
    state = engine.state
    if state.phase == GamePhase.PLAYING:
        return None
    holder = next((p for p in state.players if p.hand), None)
    if holder is None:
        return None
    return lambda: engine.play_cards(holder.id, [holder.hand[0]])


# --- Bidding --------------------------------------------------------------

@junk("bid_after_bidding_closed")
def _(engine):
    state = engine.state
    if state.phase in (GamePhase.DEALING, GamePhase.BIDDING_AFTER_DEAL):
        return None
    leader = _leader(state)
    trump_rank = _trump_rank(state)
    card = next((c for c in leader.hand if c.rank == trump_rank), None)
    if card is None:
        card = Card(suit=Suit.SPADES, rank=trump_rank)
    return lambda: engine.place_bid(leader.id, [card])


@junk("bid_card_not_in_hand")
def _(engine):
    state = engine.state
    if state.phase not in (GamePhase.DEALING, GamePhase.BIDDING_AFTER_DEAL):
        return None
    trump_rank = _trump_rank(state)
    for p in state.players:
        for suit in SUITED_SUITS:
            card = Card(suit=suit, rank=trump_rank)
            if card not in p.hand:
                return lambda p=p, card=card: engine.place_bid(p.id, [card])
    return None


@junk("bid_wrong_rank", note="a suited card that is not the trump rank")
def _(engine):
    state = engine.state
    if state.phase not in (GamePhase.DEALING, GamePhase.BIDDING_AFTER_DEAL):
        return None
    trump_rank = _trump_rank(state)
    leader = _leader(state)
    card = next(
        (c for c in leader.hand if c.rank != trump_rank and c.suit != Suit.JOKER),
        None,
    )
    if card is None:
        return None
    return lambda: engine.place_bid(leader.id, [card])


@junk("bid_single_joker")
def _(engine):
    state = engine.state
    if state.phase not in (GamePhase.DEALING, GamePhase.BIDDING_AFTER_DEAL):
        return None
    for p in state.players:
        card = next((c for c in p.hand if c.suit == Suit.JOKER), None)
        if card is not None:
            return lambda p=p, card=card: engine.place_bid(p.id, [card])
    return None


@junk("bid_three_cards")
def _(engine):
    state = engine.state
    if state.phase not in (GamePhase.DEALING, GamePhase.BIDDING_AFTER_DEAL):
        return None
    leader = _leader(state)
    if len(leader.hand) < 3:
        return None
    cards = leader.hand[:3]
    return lambda: engine.place_bid(leader.id, cards)


@junk("bid_mismatched_pair", note="two different cards offered as a pair")
def _(engine):
    state = engine.state
    if state.phase not in (GamePhase.DEALING, GamePhase.BIDDING_AFTER_DEAL):
        return None
    trump_rank = _trump_rank(state)
    for p in state.players:
        held = [c for c in p.hand if c.rank == trump_rank]
        distinct = {c.suit for c in held}
        if len(distinct) >= 2:
            a, b = (Card(suit=s, rank=trump_rank) for s in sorted(distinct, key=str)[:2])
            return lambda p=p, a=a, b=b: engine.place_bid(p.id, [a, b])
    return None


@junk("bid_equal_strength_cannot_overtake")
def _(engine):
    state = engine.state
    if state.phase not in (GamePhase.DEALING, GamePhase.BIDDING_AFTER_DEAL):
        return None
    if not state.bids:
        return None
    last = state.bids[-1]
    cards = list(last.cards)
    return lambda: engine.place_bid(last.player_id, cards)


@junk("bid_by_nonexistent_player")
def _(engine):
    state = engine.state
    if state.phase not in (GamePhase.DEALING, GamePhase.BIDDING_AFTER_DEAL):
        return None
    card = Card(suit=Suit.SPADES, rank=_trump_rank(state))
    return lambda: engine.place_bid(GHOST, [card])


@junk("close_bidding_in_wrong_phase")
def _(engine):
    if engine.state.phase == GamePhase.BIDDING_AFTER_DEAL:
        return None
    return lambda: engine.close_bidding()


# --- Bottom exchange -------------------------------------------------------

@junk("exchange_in_wrong_phase")
def _(engine):
    state = engine.state
    if state.phase == GamePhase.BOTTOM_EXCHANGE:
        return None
    leader = _leader(state)
    if len(leader.hand) < 8:
        return None
    cards = leader.hand[:8]
    return lambda: engine.exchange_bottom(leader.id, cards)


@junk("exchange_by_wrong_player")
def _(engine):
    state = engine.state
    if state.phase != GamePhase.BOTTOM_EXCHANGE:
        return None
    other = _someone_else(state, state.round_leader_id)
    if len(other.hand) < 8:
        return None
    cards = other.hand[:8]
    return lambda: engine.exchange_bottom(other.id, cards)


@junk("exchange_too_few_cards")
def _(engine):
    state = engine.state
    if state.phase != GamePhase.BOTTOM_EXCHANGE:
        return None
    leader = _leader(state)
    cards = leader.hand[:7]
    return lambda: engine.exchange_bottom(leader.id, cards)


@junk("exchange_too_many_cards")
def _(engine):
    state = engine.state
    if state.phase != GamePhase.BOTTOM_EXCHANGE:
        return None
    leader = _leader(state)
    if len(leader.hand) < 9:
        return None
    cards = leader.hand[:9]
    return lambda: engine.exchange_bottom(leader.id, cards)


@junk(
    "exchange_card_not_held",
    note="FINDING-2 regression: the bottom must not be picked up before this is validated",
)
def _(engine):
    state = engine.state
    if state.phase != GamePhase.BOTTOM_EXCHANGE:
        return None
    leader = _leader(state)
    combined = list(leader.hand) + list(state.bottom_deck)
    stranger = _card_not_held(combined)
    if stranger is None or len(combined) < 8:
        return None
    cards = combined[:7] + [stranger]
    return lambda: engine.exchange_bottom(leader.id, cards)


@junk(
    "exchange_fabricated_duplicate",
    note="FINDING-2 regression: same rollback path reached via a duplicated card",
)
def _(engine):
    state = engine.state
    if state.phase != GamePhase.BOTTOM_EXCHANGE:
        return None
    leader = _leader(state)
    combined = list(leader.hand) + list(state.bottom_deck)
    single = _singleton_in_hand(combined)
    if single is None or len(combined) < 8:
        return None
    rest = [c for c in combined if c != single][:6]
    cards = [single, single] + rest
    if len(cards) != 8:
        return None
    return lambda: engine.exchange_bottom(leader.id, cards)


# --- Friend declaration ----------------------------------------------------

def _legal_friend_card(state: GameState) -> Card:
    ctx = state.trump_context
    for suit in SUITED_SUITS:
        for rank in RANK_ORDER:
            if rank == ctx.trump_rank:
                continue
            if ctx.trump_suit is not None and suit == ctx.trump_suit:
                continue
            return Card(suit=suit, rank=rank)
    raise AssertionError("no legal friend card exists")


@junk("declare_friends_in_upgrade_mode", modes=("upgrade",))
def _(engine):
    state = engine.state
    if state.trump_context is None:
        return None
    decl = FriendDeclaration(card=_legal_friend_card(state), ordinal=1)
    return lambda: engine.declare_friends(state.round_leader_id, [decl])


@junk("declare_friends_in_wrong_phase", modes=("find_friends",))
def _(engine):
    state = engine.state
    if state.phase == GamePhase.FRIEND_DECLARATION or state.trump_context is None:
        return None
    decl = FriendDeclaration(card=_legal_friend_card(state), ordinal=1)
    return lambda: engine.declare_friends(state.round_leader_id, [decl])


@junk("declare_friends_by_wrong_player", modes=("find_friends",))
def _(engine):
    state = engine.state
    if state.phase != GamePhase.FRIEND_DECLARATION:
        return None
    other = _someone_else(state, state.round_leader_id)
    decl = FriendDeclaration(card=_legal_friend_card(state), ordinal=1)
    return lambda: engine.declare_friends(other.id, [decl])


@junk("declare_zero_friends", modes=("find_friends",))
def _(engine):
    state = engine.state
    if state.phase != GamePhase.FRIEND_DECLARATION:
        return None
    return lambda: engine.declare_friends(state.round_leader_id, [])


@junk("declare_two_friends", modes=("find_friends",))
def _(engine):
    state = engine.state
    if state.phase != GamePhase.FRIEND_DECLARATION:
        return None
    card = _legal_friend_card(state)
    decls = [
        FriendDeclaration(card=card, ordinal=1),
        FriendDeclaration(card=card, ordinal=2),
    ]
    return lambda: engine.declare_friends(state.round_leader_id, decls)


@junk("declare_joker_as_friend", modes=("find_friends",))
def _(engine):
    state = engine.state
    if state.phase != GamePhase.FRIEND_DECLARATION:
        return None
    decl = FriendDeclaration(
        card=Card(suit=Suit.JOKER, rank=Rank.BIG_JOKER), ordinal=1
    )
    return lambda: engine.declare_friends(state.round_leader_id, [decl])


@junk("declare_trump_rank_as_friend", modes=("find_friends",))
def _(engine):
    state = engine.state
    if state.phase != GamePhase.FRIEND_DECLARATION:
        return None
    ctx = state.trump_context
    suit = next(s for s in SUITED_SUITS if s != ctx.trump_suit)
    decl = FriendDeclaration(card=Card(suit=suit, rank=ctx.trump_rank), ordinal=1)
    return lambda: engine.declare_friends(state.round_leader_id, [decl])


@junk("declare_trump_suit_as_friend", modes=("find_friends",))
def _(engine):
    state = engine.state
    if state.phase != GamePhase.FRIEND_DECLARATION:
        return None
    ctx = state.trump_context
    if ctx.trump_suit is None:
        return None
    rank = next(r for r in RANK_ORDER if r != ctx.trump_rank)
    decl = FriendDeclaration(card=Card(suit=ctx.trump_suit, rank=rank), ordinal=1)
    return lambda: engine.declare_friends(state.round_leader_id, [decl])


# --- Round / phase machinery ----------------------------------------------

@junk("end_round_outside_scoring")
def _(engine):
    if engine.state.phase == GamePhase.SCORING:
        return None
    return lambda: engine.end_round()


@junk("start_dealing_mid_round")
def _(engine):
    state = engine.state
    if state.phase in (GamePhase.WAITING, GamePhase.ROUND_OVER, GamePhase.DEALING):
        return None
    return lambda: engine.start_dealing()


# --- Type junk (looser expectations, same no-mutation requirement) ---------

@junk("play_a_string_instead_of_cards", expect=(ValueError, TypeError, AttributeError))
def _(engine):
    state = engine.state
    if state.phase != GamePhase.PLAYING:
        return None
    turn = _turn_player(state)
    if turn is None:
        return None
    return lambda: engine.play_cards(turn.id, "not cards")


@junk("play_none_instead_of_cards", expect=(ValueError, TypeError, AttributeError))
def _(engine):
    state = engine.state
    if state.phase != GamePhase.PLAYING:
        return None
    turn = _turn_player(state)
    if turn is None:
        return None
    return lambda: engine.play_cards(turn.id, None)


@junk("bid_none_instead_of_cards", expect=(ValueError, TypeError, AttributeError))
def _(engine):
    state = engine.state
    if state.phase not in (GamePhase.DEALING, GamePhase.BIDDING_AFTER_DEAL):
        return None
    return lambda: engine.place_bid(_leader(state).id, None)


@junk(
    "declare_junk_objects_as_friends",
    expect=(ValueError, TypeError, AttributeError),
    modes=("find_friends",),
)
def _(engine):
    state = engine.state
    if state.phase != GamePhase.FRIEND_DECLARATION:
        return None
    return lambda: engine.declare_friends(state.round_leader_id, [object()])


# ---------------------------------------------------------------------------
# The battery
# ---------------------------------------------------------------------------

# FINDING-2 (exchange_bottom picked the bottom up before validating the cards
# to bury, so a rejection left a 33-card hand and an empty bottom) is fixed:
# all validation now runs before any mutation. The two exchange_* junk items
# below are therefore ordinary passing cases, not xfails.


def _params():
    for item in JUNK:
        for mode in item.modes:
            yield pytest.param(item, mode, id=f"{item.name}-{mode}")


@pytest.mark.parametrize("item,mode", list(_params()))
def test_junk_action_rejected_without_mutation(item: Junk, mode: str) -> None:
    """Fire one junk action at every reachable state; demand clean rejection."""
    fired = 0
    for seed in SEEDS:
        for label, pristine in harvest_snapshots(seed, mode):
            engine = copy.deepcopy(pristine)
            action = item.build(engine)
            if action is None:
                continue
            fired += 1
            before = fingerprint(engine)
            with pytest.raises(item.expect):
                action()
            after = fingerprint(engine)
            assert before == after, (
                f"{item.name} mutated state at [{label}] (seed={seed}, mode={mode}, "
                f"phase={engine.state.phase.value}) despite being rejected. "
                f"{item.note}"
            )
            violations = check_invariants(engine.state, live_points="off")
            assert not violations, (
                f"{item.name} left invalid state at [{label}] "
                f"(seed={seed}, mode={mode}): {violations}"
            )
    assert fired, (
        f"{item.name} never applied to any harvested {mode} state — the attack "
        "has stopped being expressible and is no longer testing anything"
    )


@pytest.mark.parametrize("mode", MODES)
def test_every_snapshot_starts_valid(mode: str) -> None:
    """The harvested states are themselves legal — the battery's baseline."""
    for seed in SEEDS:
        snaps = harvest_snapshots(seed, mode)
        assert len(snaps) >= 8, f"only {len(snaps)} snapshots harvested"
        for label, engine in snaps:
            live = "off" if engine.state.phase in (
                GamePhase.ROUND_OVER, GamePhase.GAME_OVER
            ) else "boundary"
            violations = check_invariants(engine.state, live_points=live)
            assert not violations, f"[{label}] seed={seed} mode={mode}: {violations}"


@pytest.mark.parametrize("mode", MODES)
def test_rejected_action_leaves_the_game_playable(mode: str) -> None:
    """After a storm of junk, the legal continuation still works.

    Rejection with a clean state is only half the promise; the other half is
    that the game can carry on.  This fires every applicable junk action at a
    mid-trick state and then plays the round out to scoring.
    """
    from tests.test_fuzz.fuzz_helpers import RandomBot
    import random

    snaps = dict(harvest_snapshots(SEEDS[0], mode))
    engine = copy.deepcopy(snaps["playing_trick5_seat2"])
    for item in JUNK:
        if mode not in item.modes or item.name.startswith("exchange_"):
            continue  # exchange_* need BOTTOM_EXCHANGE; covered by the battery above
        action = item.build(engine)
        if action is None:
            continue
        with pytest.raises(item.expect):
            action()

    state = engine.state
    bot = RandomBot(random.Random(99))
    while state.phase == GamePhase.PLAYING:
        turn = _turn_player(state)
        engine.play_cards(turn.id, bot.choose_play(engine, turn))
        assert not check_invariants(state, live_points="off")
    assert state.phase == GamePhase.SCORING
    summary = engine.end_round()
    assert summary["attacking_points"] >= 0


# ---------------------------------------------------------------------------
# Hypothesis: random sequences of junk against one state
# ---------------------------------------------------------------------------

_JUNK_BY_NAME = {j.name: j for j in JUNK}
_SAFE_NAMES = sorted(n for n in _JUNK_BY_NAME if not n.startswith("exchange_"))

ADVERSARIAL_SETTINGS = settings(
    max_examples=200 if HEAVY else 15,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)


@pytest.mark.parametrize("mode", MODES)
@ADVERSARIAL_SETTINGS
@given(
    names=st.lists(st.sampled_from(_SAFE_NAMES), min_size=1, max_size=8),
    snapshot_index=st.integers(min_value=0, max_value=40),
)
def test_junk_sequences_never_corrupt_state(
    mode: str, names: list[str], snapshot_index: int
) -> None:
    """A *sequence* of rejected actions must be as harmless as a single one.

    Hypothesis picks both the state and the attack order, and shrinks to the
    shortest corrupting sequence when one exists.
    """
    snaps = harvest_snapshots(SEEDS[0], mode)
    label, pristine = snaps[snapshot_index % len(snaps)]
    engine = copy.deepcopy(pristine)
    before = fingerprint(engine)

    for name in names:
        item = _JUNK_BY_NAME[name]
        if mode not in item.modes:
            continue
        action = item.build(engine)
        if action is None:
            continue
        with pytest.raises(item.expect):
            action()

    assert fingerprint(engine) == before, (
        f"junk sequence {names} mutated state at [{label}] (mode={mode})"
    )
    live = "off" if engine.state.phase in (
        GamePhase.ROUND_OVER, GamePhase.GAME_OVER
    ) else "boundary"
    assert not check_invariants(engine.state, live_points=live)


# ---------------------------------------------------------------------------
# Documented non-exception rejections
# ---------------------------------------------------------------------------

def test_deal_next_card_on_empty_pile_returns_none_without_mutating() -> None:
    """``deal_next_card`` documents ``None`` (not a raise) as its stop signal."""
    for mode in MODES:
        snaps = dict(harvest_snapshots(SEEDS[0], mode))
        engine = copy.deepcopy(snaps["bidding"])  # draw pile exhausted
        assert engine.state.draw_pile == []
        before = fingerprint(engine)
        assert engine.deal_next_card() is None
        assert fingerprint(engine) == before


def test_upgrade_strategy_rejects_friend_declarations_directly() -> None:
    """Belt and braces: the strategy refuses even if the phase gate is bypassed."""
    from shengji.modes.upgrade import UpgradeStrategy

    snaps = dict(harvest_snapshots(SEEDS[0], "upgrade"))
    engine = copy.deepcopy(snaps["bottom_exchange"])
    decl = FriendDeclaration(card=_legal_friend_card(engine.state), ordinal=1)
    with pytest.raises(ValueError):
        UpgradeStrategy().validate_friend_declaration(engine.state, [decl])


def test_phase_machine_rejects_illegal_transitions() -> None:
    """``GameState.transition_to`` is the last line of defence on phase order."""
    snaps = dict(harvest_snapshots(SEEDS[0], "upgrade"))
    engine = copy.deepcopy(snaps["playing_trick2_seat1"])
    state = engine.state
    for target in (
        GamePhase.WAITING,
        GamePhase.DEALING,
        GamePhase.BIDDING_AFTER_DEAL,
        GamePhase.BOTTOM_EXCHANGE,
        GamePhase.FRIEND_DECLARATION,
        GamePhase.ROUND_OVER,
        GamePhase.GAME_OVER,
    ):
        before = fingerprint(engine)
        with pytest.raises(ValueError):
            state.transition_to(target)
        assert fingerprint(engine) == before
