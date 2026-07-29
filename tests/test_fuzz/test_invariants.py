"""Per-action invariant battery over complete random-legal games.

Every engine action in a full game is followed by an independent re-derivation
of card conservation, zone exclusivity, turn/phase coherence, points
bookkeeping and (at round end) the scoring/advancement table.  Nothing here
trusts ``superuser.inspector.validate_state``: it is run as a *second* opinion
alongside the checks, so a bug in the inspector cannot mask a bug in the
engine.

Running
-------
    python -m pytest tests/test_fuzz -q          # light: a few seconds
    FUZZ=1 python -m pytest tests/test_fuzz -q   # heavy: many more games

Reproducing a failure
---------------------
Failures print the seed, mode and the last 25 engine actions.  Any failure is
reproducible with::

    FuzzDriver(<seed>, "<mode>").run()

Findings
--------
FINDING-1 (FIXED by D21) — ``GameState.revealed_friends`` and
``friend_declarations`` were never reset by ``start_dealing``, so they
accumulated across rounds: old friends leaked into every player view, and a
repeat friend's reveal skipped the live-points recompute.  The tests at the
bottom of this file are now the pinned regressions.
"""
from __future__ import annotations

import copy

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from shengji.models.card import Card, Rank, Suit
from shengji.models.game_state import GamePhase

from tests.test_fuzz.fuzz_helpers import (
    HEAVY,
    MODES,
    REFERENCE_DECK,
    FuzzDriver,
    FuzzFailure,
    check_card_conservation,
    check_live_points,
    check_turn_and_phase,
    expected_advancement,
)

# --- light / heavy dials ---------------------------------------------------
# Light mode keeps the default suite to a few seconds; FUZZ=1 turns the same
# tests into a long soak.  Seeds are fixed either way — hypothesis runs with
# derandomize=True so the examples it picks are identical run to run.
GAME_EXAMPLES = 150 if HEAVY else 4
MAX_ROUNDS = 10 if HEAVY else 2
DEAL_CHECK_EVERY = 1 if HEAVY else 50
EXPLICIT_SEEDS = list(range(40)) if HEAVY else [0, 1, 7]

FUZZ_SETTINGS = settings(
    max_examples=GAME_EXAMPLES,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)


def _play(seed: int, mode: str, **kwargs) -> FuzzDriver:
    driver = FuzzDriver(
        seed,
        mode,
        max_rounds=kwargs.pop("max_rounds", MAX_ROUNDS),
        deal_check_every=kwargs.pop("deal_check_every", DEAL_CHECK_EVERY),
        **kwargs,
    )
    driver.run()
    return driver


# ---------------------------------------------------------------------------
# Full-game sweeps
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("seed", EXPLICIT_SEEDS)
def test_full_game_holds_every_invariant(seed: int, mode: str) -> None:
    """Fixed-seed regression games: every invariant after every action."""
    driver = _play(seed, mode)
    assert driver.rounds_played >= 1
    assert driver.checks > 50, "invariant battery barely ran — driver stalled?"


@pytest.mark.parametrize("mode", MODES)
@FUZZ_SETTINGS
@given(seed=st.integers(min_value=0, max_value=2**31 - 1))
@example(seed=0)
@example(seed=12345)
def test_generated_games_hold_every_invariant(mode: str, seed: int) -> None:
    """Hypothesis-chosen seeds, shrinking toward the smallest failing seed."""
    _play(seed, mode)


@pytest.mark.parametrize("mode", MODES)
def test_games_reach_scoring_and_exercise_throws(mode: str) -> None:
    """The driver must actually reach the interesting parts of the engine.

    A fuzz suite that silently stops exercising throws or round scoring would
    stay green while testing nothing, so assert the coverage it claims.
    """
    tricks = throws = rounds = 0
    for seed in range(8):
        driver = _play(seed, mode, max_rounds=2)
        tricks += driver.tricks_played
        throws += driver.throw_failures
        rounds += driver.rounds_played
    assert rounds == 16
    # 25 tricks per round is the ceiling; multi-card leads (pairs, tractors,
    # throws) consume several cards each and pull the real count down.
    assert tricks >= 16 * 12, f"only {tricks} tricks resolved"
    assert throws > 0, "no failed throws generated — penalty path never exercised"


@pytest.mark.parametrize("mode", MODES)
def test_determinism_same_seed_same_game(mode: str) -> None:
    """A seed reproduces a game exactly — the premise of every repro line."""
    first = _play(3, mode, max_rounds=2)
    second = _play(3, mode, max_rounds=2)
    assert first.log == second.log


# ---------------------------------------------------------------------------
# Round-end bookkeeping, isolated
# ---------------------------------------------------------------------------

def test_advancement_table_matches_documented_bands() -> None:
    """The band table transcribed in fuzz_helpers matches engine/scoring.py."""
    from shengji.engine.scoring import compute_rank_advancement

    for points in range(0, 400):
        assert expected_advancement(points) == compute_rank_advancement(points), points


@pytest.mark.parametrize("mode", MODES)
def test_round_end_bookkeeping_over_many_rounds(mode: str) -> None:
    """Scoring, ranks, game-over and leader rotation re-derived per round.

    ``FuzzDriver.finish_round`` runs :func:`check_round_end` after every
    ``end_round``; this test just makes sure enough rounds happen for that to
    mean something.
    """
    total_rounds = 0
    for seed in EXPLICIT_SEEDS:
        driver = _play(seed, mode, max_rounds=4)
        total_rounds += driver.rounds_played
    assert total_rounds >= 4 * len(EXPLICIT_SEEDS) - len(EXPLICIT_SEEDS)


# ---------------------------------------------------------------------------
# Meta-tests: prove the battery has teeth
# ---------------------------------------------------------------------------
# A silent invariant is worse than no invariant.  Each of these corrupts a
# reachable state by hand and asserts the corresponding checker notices.

def _mid_game_state(seed: int = 11, trick: int = 5):
    """A real reachable mid-play state, harvested from a seeded game."""
    driver = FuzzDriver(seed, "find_friends", max_rounds=1, deal_check_every=100)
    captured = {}

    def grab(label, engine):
        if label.startswith(f"playing_trick{trick}_") and "state" not in captured:
            captured["state"] = copy.deepcopy(engine.state)

    driver.on_snapshot = grab
    driver.run()
    return captured["state"]


def test_reference_deck_is_the_real_deck() -> None:
    from shengji.models.deck import Deck

    draw, bottom = Deck().prepare_deal()
    from collections import Counter

    actual = Counter((c.suit, c.rank) for c in draw + bottom)
    assert actual == REFERENCE_DECK
    assert sum(REFERENCE_DECK.values()) == 108


def test_conservation_catches_a_missing_card() -> None:
    state = _mid_game_state()
    assert check_card_conservation(state) == []
    state.players[0].hand.pop()
    assert any("conservation" in v for v in check_card_conservation(state))


def test_conservation_catches_a_cloned_card() -> None:
    state = _mid_game_state()
    # Same card in two zones at once — the classic double-spend.
    state.bottom_deck.append(state.players[1].hand[0])
    violations = check_card_conservation(state)
    assert any("extra" in v for v in violations), violations


def test_conservation_catches_a_card_from_outside_the_deck() -> None:
    state = _mid_game_state()
    state.players[2].hand.pop()
    state.players[2].hand.append(Card(suit=Suit.JOKER, rank=Rank.BIG_JOKER))
    violations = check_card_conservation(state)
    assert any("extra" in v and "missing" in v for v in violations), violations


def test_turn_check_catches_a_bogus_turn_pointer() -> None:
    state = _mid_game_state()
    assert check_turn_and_phase(state) == []
    state.current_turn_id = "nobody"
    assert any("not seated" in v for v in check_turn_and_phase(state))


def test_turn_check_catches_an_oversized_trick() -> None:
    state = _mid_game_state()
    state.current_trick = [(p.id, [p.hand[0]]) for p in state.players]
    state.current_trick.append(("p0", [state.players[0].hand[1]]))
    violations = check_turn_and_phase(state)
    assert any("exceeds" in v for v in violations), violations


def test_turn_check_catches_a_double_play_in_one_trick() -> None:
    state = _mid_game_state()
    state.current_trick = [
        ("p0", [state.players[0].hand[0]]),
        ("p0", [state.players[0].hand[1]]),
    ]
    violations = check_turn_and_phase(state)
    assert any("twice" in v for v in violations), violations


def test_points_check_catches_drifted_bookkeeping() -> None:
    state = _mid_game_state()
    assert check_live_points(state) == []
    state.attacking_points += 5
    assert check_live_points(state)


def test_points_check_catches_unattributed_team_flip() -> None:
    """Flipping a team without re-attributing points must be caught."""
    from tests.test_fuzz.fuzz_helpers import point_total

    for seed in (11, 12, 13, 14):
        state = _mid_game_state(seed, trick=13)
        for p in state.players:
            pile = [c for trick in state.tricks_won.get(p.id, []) for c in trick]
            if not p.is_defending and point_total(pile) > 0:
                p.is_defending = True  # flipped, points not recomputed
                assert check_live_points(state), "team flip went unnoticed"
                return
    raise AssertionError("no sampled state had an attacker holding scoring cards")


def test_forced_throw_check_catches_a_wrong_penalty() -> None:
    """The failed-throw contract check must notice a mispriced penalty."""
    driver = FuzzDriver(4, "upgrade", max_rounds=1, deal_check_every=100)
    driver.run()
    hand = [Card(suit=Suit.SPADES, rank=Rank.FIVE)]
    with pytest.raises(FuzzFailure, match="penalty"):
        driver.check_forced_throw(
            "p0",
            hand_before=hand,
            penalty_before=0,
            attempted=hand,
            result={
                "attempted_cards": hand,
                "forced_cards": hand,
                "penalty": 999,  # should be 10 x 1 card
            },
        )


def test_forced_throw_check_catches_a_swallowed_remainder() -> None:
    """Cards left over from a beaten throw must stay in the thrower's hand."""
    driver = FuzzDriver(4, "upgrade", max_rounds=1, deal_check_every=100)
    driver.run()
    five = Card(suit=Suit.SPADES, rank=Rank.FIVE)
    six = Card(suit=Suit.SPADES, rank=Rank.SIX)
    with pytest.raises(FuzzFailure, match="hand after forced throw"):
        driver.check_forced_throw(
            "p0",
            hand_before=[five, six],
            penalty_before=0,
            attempted=[five, six],
            result={
                "attempted_cards": [five, six],
                "forced_cards": [five],
                "penalty": 20,
            },
        )


# ---------------------------------------------------------------------------
# FINDING-1 / D21 regression (was a confirmed engine bug — now fixed)
# ---------------------------------------------------------------------------

def test_d21_friend_state_does_not_leak_across_rounds() -> None:
    """Every fresh deal starts with no revealed friends and no declarations.

    Was FINDING-1: ``start_dealing`` cleared bids, trump, tricks, points,
    penalties and the current trick, but not ``revealed_friends`` or
    ``friend_declarations``, so from round 2 onward a fresh deal already
    reported last round's friend — and ``to_player_view`` shipped that straight
    to every client.  D21 clears all three friend fields.
    """
    seen: list[tuple[int, set, list, dict]] = []

    driver = FuzzDriver(0, "find_friends", max_rounds=3, deal_check_every=100)
    real_start_dealing = driver.engine.start_dealing

    def spy() -> None:
        real_start_dealing()
        seen.append(
            (
                driver.state.round_number,
                set(driver.state.revealed_friends),
                list(driver.state.friend_declarations),
                dict(driver.state.friend_play_counts),
            )
        )

    driver.engine.start_dealing = spy
    driver.run()

    assert len(seen) >= 2, "expected more than one deal in a 3-round game"
    for round_no, revealed, decls, counts in seen:
        assert revealed == set(), (
            f"round {round_no} starts in DEALING with revealed_friends={revealed}"
        )
        assert decls == [], (
            f"round {round_no} starts in DEALING with stale declarations {decls}"
        )
        assert counts == {}, (
            f"round {round_no} starts in DEALING with stale play counts {counts}"
        )


def test_d21_no_player_view_leaks_a_previous_rounds_friend() -> None:
    """Redaction invariant: during DEALING/BIDDING no view carries old friends.

    Sampled at every deal of a multi-round Find Friends game, for all four
    viewers — the round-over screen may show a friend, the next round's deal
    and bidding may not.
    """
    driver = FuzzDriver(1, "find_friends", max_rounds=3, deal_check_every=100)
    real_start_dealing = driver.engine.start_dealing
    real_close_bidding = driver.engine.close_bidding
    checked = 0

    def check_views(where: str) -> None:
        nonlocal checked
        state = driver.state
        assert state.phase in (GamePhase.DEALING, GamePhase.BIDDING_AFTER_DEAL), (
            f"{where}: unexpected phase {state.phase}"
        )
        for player in state.players:
            view = state.to_player_view(player.id)
            assert view["revealed_friends"] == [], (
                f"round {state.round_number} {where}: {player.id}'s view exposes "
                f"revealed_friends={view['revealed_friends']}"
            )
            assert view["friend_declarations"] == [], (
                f"round {state.round_number} {where}: {player.id}'s view exposes "
                f"declarations {view['friend_declarations']}"
            )
            checked += 1

    def dealing_spy() -> None:
        real_start_dealing()
        check_views("after start_dealing")

    def bidding_spy() -> None:
        check_views("during bidding")
        real_close_bidding()

    driver.engine.start_dealing = dealing_spy
    driver.engine.close_bidding = bidding_spy
    driver.run()
    assert checked >= 16, "expected at least two rounds x two samples x four viewers"


def test_finding_1_mid_trick_points_reattribution_is_immediate() -> None:
    """attacking_points matches the captured piles after *every* play.

    Pinned regression for the second half of FINDING-1: ``play_cards``
    re-attributes points only when ``revealed_friends`` *changes*, so while the
    set survived across rounds a repeat friend's reveal was invisible to it and
    ``attacking_points`` stayed wrong until the trick resolved — the mid-trick
    drift issue #43 set out to fix.  Used to fail on 42 of 60 find_friends
    seeds (repro: ``FuzzDriver(0, 'find_friends', strict_live_points=True)``);
    D21's clear in ``start_dealing`` fixes it.
    """
    for seed in range(6):
        FuzzDriver(
            seed,
            "find_friends",
            max_rounds=4,
            deal_check_every=100,
            strict_live_points=True,
        ).run()


def test_finding_1_does_not_affect_upgrade_mode() -> None:
    """Scoping check: the strict mid-trick invariant holds in Upgrade mode."""
    for seed in range(4):
        FuzzDriver(
            seed,
            "upgrade",
            max_rounds=2,
            deal_check_every=100,
            strict_live_points=True,
        ).run()


def test_finding_1_points_are_correct_again_by_trick_end() -> None:
    """Bounding the blast radius: the drift is transient, not persistent.

    ``_recompute_attacking_points`` runs unconditionally when a trick resolves,
    so the wrong total self-heals within one trick and round scoring is
    unaffected.  If this ever fails, FINDING-1 has become a scoring bug rather
    than a display bug.
    """
    for seed in range(6):
        driver = FuzzDriver(seed, "find_friends", max_rounds=4, deal_check_every=100)
        driver.run()  # boundary-only live-points checks
        assert driver.state.phase in (GamePhase.ROUND_OVER, GamePhase.GAME_OVER)


def test_finding_1_repro_no_longer_reproduces() -> None:
    """The published FINDING-1 repro now runs clean under strict live points."""
    driver = FuzzDriver(
        0, "find_friends", max_rounds=4, deal_check_every=100,
        strict_live_points=True,
    )
    driver.run()
    assert driver.state.phase in (GamePhase.ROUND_OVER, GamePhase.GAME_OVER)
