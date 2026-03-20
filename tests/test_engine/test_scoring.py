"""Tests for scoring utilities and end_round (M4.6)."""
from __future__ import annotations

import pytest

from shengji.engine.engine import GameEngine
from shengji.engine.scoring import compute_rank_advancement, count_attacking_points
from shengji.models.card import Card, Rank, Suit
from shengji.models.deck import NUM_PLAYERS
from shengji.models.game_state import GamePhase, GameState
from shengji.models.player import Player
from shengji.models.trump import TrumpContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _c(suit: Suit, rank: Rank) -> Card:
    return Card(suit=suit, rank=rank)


ctx = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS)

# Point cards
FIVE_S = _c(Suit.SPADES, Rank.FIVE)
TEN_S = _c(Suit.SPADES, Rank.TEN)
KING_S = _c(Suit.SPADES, Rank.KING)
THREE_S = _c(Suit.SPADES, Rank.THREE)  # 0 pts


# ---------------------------------------------------------------------------
# compute_rank_advancement — threshold boundary tests
# ---------------------------------------------------------------------------

class TestComputeRankAdvancement:
    """Test every boundary of the threshold table.

    For n=2: step=40, thresholds at 0,40,80,120,160,200.
    The key threshold for attackers to take over is 80 (= 2*step = 2*40).
    """

    def test_zero_pts_defending_plus3(self):
        assert compute_rank_advancement(0) == ("defending", 3)

    def test_one_pt_defending_plus2(self):
        assert compute_rank_advancement(1) == ("defending", 2)

    def test_just_below_first_threshold_defending_plus2(self):
        # step-1 = 39
        assert compute_rank_advancement(39) == ("defending", 2)

    def test_at_first_threshold_defending_plus1(self):
        # step = 40
        assert compute_rank_advancement(40) == ("defending", 1)

    def test_just_below_second_threshold_defending_plus1(self):
        # 2*step-1 = 79
        assert compute_rank_advancement(79) == ("defending", 1)

    def test_at_second_threshold_attacking_zero(self):
        # 2*step = 80 — attackers take over same rank (the key "win" threshold)
        assert compute_rank_advancement(80) == ("attacking", 0)

    def test_user_example_95pts_attacking_zero(self):
        # User example: 95 pts → "attackers succeeded but do not skip a level"
        assert compute_rank_advancement(95) == ("attacking", 0)

    def test_just_below_third_threshold_attacking_zero(self):
        # 3*step-1 = 119
        assert compute_rank_advancement(119) == ("attacking", 0)

    def test_at_third_threshold_attacking_plus1(self):
        # 3*step = 120
        assert compute_rank_advancement(120) == ("attacking", 1)

    def test_just_below_fourth_threshold_attacking_plus1(self):
        # 4*step-1 = 159
        assert compute_rank_advancement(159) == ("attacking", 1)

    def test_at_fourth_threshold_attacking_plus2(self):
        # 4*step = 160
        assert compute_rank_advancement(160) == ("attacking", 2)

    def test_just_below_fifth_threshold_attacking_plus2(self):
        # 5*step-1 = 199
        assert compute_rank_advancement(199) == ("attacking", 2)

    def test_at_fifth_threshold_attacking_plus3(self):
        # 5*step = 200 (achievable via bottom-deck multiplier)
        assert compute_rank_advancement(200) == ("attacking", 3)

    def test_large_value_attacking_plus3(self):
        assert compute_rank_advancement(9999) == ("attacking", 3)

    def test_n_equals_1_thresholds(self):
        # n=1: step=20, thresholds at 0,20,40,60,80,100
        assert compute_rank_advancement(0, n_decks=1) == ("defending", 3)
        assert compute_rank_advancement(10, n_decks=1) == ("defending", 2)
        assert compute_rank_advancement(20, n_decks=1) == ("defending", 1)
        assert compute_rank_advancement(40, n_decks=1) == ("attacking", 0)
        assert compute_rank_advancement(60, n_decks=1) == ("attacking", 1)
        assert compute_rank_advancement(80, n_decks=1) == ("attacking", 2)
        assert compute_rank_advancement(100, n_decks=1) == ("attacking", 3)


# ---------------------------------------------------------------------------
# count_attacking_points — base points
# ---------------------------------------------------------------------------

class TestCountAttackingPoints:
    def test_attackers_win_point_cards(self):
        tricks_won = {
            "p0": [[FIVE_S, THREE_S]],   # p0 is attacker: 5 pts
            "p1": [[TEN_S, THREE_S]],    # p1 is defender: 10 pts (not counted)
            "p2": [],
            "p3": [],
        }
        pts = count_attacking_points(
            tricks_won=tricks_won,
            attacker_ids={"p0", "p2"},
            bottom_deck=[THREE_S],
            last_trick_winner_id="p1",  # defender wins last trick → no multiplier
            last_trick_cards=[THREE_S, THREE_S, THREE_S, THREE_S],
            ctx=ctx,
        )
        assert pts == 5

    def test_defender_wins_last_trick_no_multiplier(self):
        tricks_won = {
            "p0": [[FIVE_S]],
            "p1": [[TEN_S]],
            "p2": [],
            "p3": [],
        }
        bottom = [KING_S, KING_S]  # 20 pts in bottom
        pts = count_attacking_points(
            tricks_won=tricks_won,
            attacker_ids={"p0"},
            bottom_deck=bottom,
            last_trick_winner_id="p1",  # defender wins → no multiplier
            last_trick_cards=[THREE_S],
            ctx=ctx,
        )
        assert pts == 5  # only p0's 5 pts; bottom not added

    def test_attacker_wins_last_trick_single_multiplier(self):
        """Attacker wins last trick with singles → multiplier = 2*1 = 2."""
        tricks_won = {
            "p0": [[FIVE_S, THREE_S, THREE_S, THREE_S]],
            "p1": [],
            "p2": [],
            "p3": [],
        }
        bottom = [FIVE_S, THREE_S]  # 5 pts in bottom
        # 4 different singles → Throw → length=1 → multiplier 2*1=2
        last_cards = [
            _c(Suit.SPADES, Rank.ACE),
            _c(Suit.CLUBS, Rank.SEVEN),
            _c(Suit.DIAMONDS, Rank.EIGHT),
            _c(Suit.CLUBS, Rank.NINE),
        ]
        pts = count_attacking_points(
            tricks_won=tricks_won,
            attacker_ids={"p0"},
            bottom_deck=bottom,
            last_trick_winner_id="p0",
            last_trick_cards=last_cards,
            ctx=ctx,
        )
        # base = 5 (from trick), multiplier = 2 (single/throw → length 1), bottom = 5 pts
        assert pts == 5 + 2 * 5  # = 15

    def test_attacker_wins_last_trick_tractor_multiplier(self):
        """Tractor (length=2) gives multiplier 2*2=4."""
        tricks_won = {"p0": [], "p1": [], "p2": [], "p3": []}
        bottom = [TEN_S, THREE_S]  # 10 pts in bottom
        # Tractor: A♠A♠K♠K♠ with trump_rank=2 (A and K adjacent)
        # Wait, with trump_rank=2, filtered ranks are [3..A]; K=pos10, A=pos11 → adjacent
        last_cards = [
            _c(Suit.SPADES, Rank.ACE), _c(Suit.SPADES, Rank.ACE),
            _c(Suit.SPADES, Rank.KING), _c(Suit.SPADES, Rank.KING),
        ]
        pts = count_attacking_points(
            tricks_won={"p0": [], "p1": [], "p2": [], "p3": []},
            attacker_ids={"p0"},
            bottom_deck=bottom,
            last_trick_winner_id="p0",
            last_trick_cards=last_cards,
            ctx=ctx,
        )
        # Tractor length=2 → multiplier = 2*2 = 4; bottom = 10 pts
        assert pts == 0 + 4 * 10  # = 40

    def test_no_points_in_bottom_no_multiplier_effect(self):
        tricks_won = {"p0": [[FIVE_S]], "p1": [], "p2": [], "p3": []}
        bottom = [THREE_S, THREE_S]  # 0 pts in bottom
        pts = count_attacking_points(
            tricks_won=tricks_won,
            attacker_ids={"p0"},
            bottom_deck=bottom,
            last_trick_winner_id="p0",
            last_trick_cards=[_c(Suit.SPADES, Rank.ACE)],
            ctx=ctx,
        )
        assert pts == 5


# ---------------------------------------------------------------------------
# end_round integration
# ---------------------------------------------------------------------------

def _make_player(idx: int) -> Player:
    return Player(id=f"p{idx}", name=f"Player{idx}")


class _UpgradeStub:
    """Minimal upgrade stub: p0+p2 defend, p1+p3 attack."""

    def assign_teams(self, state) -> None:
        pass

    def needs_friend_declaration(self) -> bool:
        return False

    def validate_friend_declaration(self, state, declarations) -> None:
        raise RuntimeError("Not applicable")

    def resolve_friend(self, state, player_id, card) -> None:
        pass

    def on_round_end(self, state, winner_team: str) -> None:
        pass

    def get_attacker_ids(self, state: GameState) -> set[str]:
        return {"p1", "p3"}

    def get_next_leader(self, state: GameState, winner: str) -> str:
        return "p0"  # always p0 for simplicity


def _make_state_in_scoring(attacker_pts: int = 0) -> GameState:
    """Build a GameState already in SCORING phase with specified attacker points."""
    players = [_make_player(i) for i in range(NUM_PLAYERS)]
    state = GameState(
        players=players,
        mode="upgrade",
        round_leader_id="p0",
        phase=GamePhase.SCORING,
        trump_context=TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS),
        current_leader_id="p0",
        tricks_won={"p0": [], "p1": [], "p2": [], "p3": []},
        bottom_deck=[THREE_S] * 8,  # no points
    )
    # Manually inject attacking points into p1's tricks
    if attacker_pts > 0:
        # Give p1 (attacker) tricks worth attacker_pts points (use 5s)
        fives_needed = attacker_pts // 5
        state.tricks_won["p1"] = [[_c(Suit.SPADES, Rank.FIVE)] * fives_needed]
    return state


def _make_engine(state: GameState | None = None) -> GameEngine:
    if state is None:
        state = _make_state_in_scoring()
    return GameEngine(state, _UpgradeStub(), deal_delay=0)


class TestEndRound:
    def test_wrong_phase_raises(self):
        state = _make_state_in_scoring()
        state.phase = GamePhase.PLAYING
        engine = _make_engine(state)
        with pytest.raises(ValueError, match="SCORING"):
            engine.end_round()

    def test_returns_attacking_points(self):
        state = _make_state_in_scoring(attacker_pts=10)
        engine = _make_engine(state)
        result = engine.end_round()
        assert result["attacking_points"] == 10

    def test_zero_pts_defending_wins_plus3(self):
        engine = _make_engine(_make_state_in_scoring(0))
        result = engine.end_round()
        assert result["winner"] == "defending"
        assert result["steps"] == 3

    def test_defender_rank_advances_on_win(self):
        engine = _make_engine(_make_state_in_scoring(0))  # defending +3
        engine.end_round()
        # Defenders are p0 and p2; both should be at rank FIVE (TWO + 3 = FIVE)
        assert engine._player("p0").rank == Rank.FIVE
        assert engine._player("p2").rank == Rank.FIVE

    def test_attacker_rank_advances_on_win(self):
        # 120 pts: 3*step=120 → attacking +1 (step=40 for n=2)
        engine = _make_engine(_make_state_in_scoring(120))
        engine.end_round()
        # Attackers are p1 and p3; advance 1 rank from TWO → THREE
        assert engine._player("p1").rank == Rank.THREE
        assert engine._player("p3").rank == Rank.THREE

    def test_no_advancement_zero_steps(self):
        # 90 pts: 2*step=80 ≤ 90 < 3*step=120 → attacking +0 (take over same rank)
        engine = _make_engine(_make_state_in_scoring(90))
        result = engine.end_round()
        assert result["steps"] == 0
        # Attackers take over but don't advance ranks
        assert engine._player("p1").rank == Rank.TWO
        assert engine._player("p3").rank == Rank.TWO

    def test_round_over_phase_after_end_round(self):
        engine = _make_engine(_make_state_in_scoring(100))
        engine.end_round()
        assert engine.state.phase == GamePhase.ROUND_OVER

    def test_game_over_when_defender_at_ace_and_defends(self):
        state = _make_state_in_scoring(0)  # defending +3 → but clamps at ACE
        # Put defenders at ACE already
        state.players[0].rank = Rank.ACE  # p0 is defender
        state.players[2].rank = Rank.ACE  # p2 is defender
        engine = _make_engine(state)
        result = engine.end_round()
        assert result["game_over"] is True
        assert engine.state.phase == GamePhase.GAME_OVER

    def test_not_game_over_when_attacking_wins(self):
        state = _make_state_in_scoring(600)  # attacking +1
        state.players[0].rank = Rank.ACE  # defender at ACE but attackers won
        engine = _make_engine(state)
        result = engine.end_round()
        assert result["game_over"] is False

    def test_rank_clamped_at_ace(self):
        state = _make_state_in_scoring(0)  # defending +3
        state.players[0].rank = Rank.QUEEN  # QUEEN + 3 = ACE (not beyond)
        state.players[2].rank = Rank.QUEEN
        engine = _make_engine(state)
        engine.end_round()
        assert engine._player("p0").rank == Rank.ACE
        assert engine._player("p2").rank == Rank.ACE

    def test_round_number_increments(self):
        engine = _make_engine()
        assert engine.state.round_number == 1
        engine.end_round()
        assert engine.state.round_number == 2
