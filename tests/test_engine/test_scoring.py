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

    For n=2: threshold=80, step=20.  Every band is 20 points wide.
    """

    # --- Defending side (< 80) ---

    def test_zero_pts_defending_plus4(self):
        assert compute_rank_advancement(0) == ("defending", 4)

    def test_one_pt_defending_plus4(self):
        assert compute_rank_advancement(1) == ("defending", 4)

    def test_19_pts_defending_plus4(self):
        assert compute_rank_advancement(19) == ("defending", 4)

    def test_20_pts_defending_plus3(self):
        assert compute_rank_advancement(20) == ("defending", 3)

    def test_39_pts_defending_plus3(self):
        assert compute_rank_advancement(39) == ("defending", 3)

    def test_40_pts_defending_plus2(self):
        assert compute_rank_advancement(40) == ("defending", 2)

    def test_59_pts_defending_plus2(self):
        assert compute_rank_advancement(59) == ("defending", 2)

    def test_60_pts_defending_plus1(self):
        assert compute_rank_advancement(60) == ("defending", 1)

    def test_79_pts_defending_plus1(self):
        assert compute_rank_advancement(79) == ("defending", 1)

    # --- Attacking side (>= 80) ---

    def test_80_pts_attacking_zero(self):
        assert compute_rank_advancement(80) == ("attacking", 0)

    def test_95_pts_attacking_zero(self):
        assert compute_rank_advancement(95) == ("attacking", 0)

    def test_99_pts_attacking_zero(self):
        assert compute_rank_advancement(99) == ("attacking", 0)

    def test_100_pts_attacking_plus1(self):
        assert compute_rank_advancement(100) == ("attacking", 1)

    def test_119_pts_attacking_plus1(self):
        assert compute_rank_advancement(119) == ("attacking", 1)

    def test_120_pts_attacking_plus2(self):
        assert compute_rank_advancement(120) == ("attacking", 2)

    def test_139_pts_attacking_plus2(self):
        assert compute_rank_advancement(139) == ("attacking", 2)

    def test_140_pts_attacking_plus3(self):
        assert compute_rank_advancement(140) == ("attacking", 3)

    def test_large_value_attacking_capped(self):
        # Issue #51: capped at +3 (140+ is the top band); bottom multiplier
        # can push totals far above 200 and must not over-promote.
        assert compute_rank_advancement(200) == ("attacking", 3)
        assert compute_rank_advancement(500) == ("attacking", 3)
        assert compute_rank_advancement(100, n_decks=1) == ("attacking", 3)

    def test_n_equals_1_thresholds(self):
        # n=1: threshold=40, step=10
        assert compute_rank_advancement(0, n_decks=1) == ("defending", 4)
        assert compute_rank_advancement(10, n_decks=1) == ("defending", 3)
        assert compute_rank_advancement(20, n_decks=1) == ("defending", 2)
        assert compute_rank_advancement(30, n_decks=1) == ("defending", 1)
        assert compute_rank_advancement(40, n_decks=1) == ("attacking", 0)
        assert compute_rank_advancement(50, n_decks=1) == ("attacking", 1)
        assert compute_rank_advancement(60, n_decks=1) == ("attacking", 2)
        assert compute_rank_advancement(70, n_decks=1) == ("attacking", 3)


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
        """Attacker wins last trick with a single → multiplier = 2×."""
        tricks_won = {
            "p0": [[FIVE_S, THREE_S, THREE_S, THREE_S]],
            "p1": [],
            "p2": [],
            "p3": [],
        }
        bottom = [FIVE_S, THREE_S]  # 5 pts in bottom
        # Winning play is a single card → multiplier 2×
        last_cards = [_c(Suit.SPADES, Rank.ACE)]
        pts = count_attacking_points(
            tricks_won=tricks_won,
            attacker_ids={"p0"},
            bottom_deck=bottom,
            last_trick_winner_id="p0",
            last_trick_cards=last_cards,
            ctx=ctx,
        )
        # base = 5 (from trick), multiplier = 2, bottom = 5 pts
        assert pts == 5 + 2 * 5  # = 15

    def test_attacker_wins_last_trick_pair_multiplier(self):
        """Winning with a pair → multiplier = 4× (issue #57)."""
        bottom = [TEN_S, THREE_S]  # 10 pts in bottom
        last_cards = [_c(Suit.SPADES, Rank.ACE), _c(Suit.SPADES, Rank.ACE)]
        pts = count_attacking_points(
            tricks_won={"p0": [], "p1": [], "p2": [], "p3": []},
            attacker_ids={"p0"},
            bottom_deck=bottom,
            last_trick_winner_id="p0",
            last_trick_cards=last_cards,
            ctx=ctx,
        )
        assert pts == 0 + 4 * 10  # = 40

    def test_attacker_wins_last_trick_tractor_multiplier(self):
        """Winning with a 4-card tractor → multiplier = 8× (issue #57)."""
        bottom = [TEN_S, THREE_S]  # 10 pts in bottom
        # Tractor: A♠A♠K♠K♠ with trump_rank=2 (A and K adjacent)
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
        # Tractor = 4 cards → multiplier capped formula min(8, 2*4) = 8
        assert pts == 0 + 8 * 10  # = 80

    def test_multiplier_capped_at_8(self):
        """A 6-card tractor still gives 8× (cap), not 12×."""
        bottom = [FIVE_S]  # 5 pts
        last_cards = [
            _c(Suit.SPADES, Rank.ACE), _c(Suit.SPADES, Rank.ACE),
            _c(Suit.SPADES, Rank.KING), _c(Suit.SPADES, Rank.KING),
            _c(Suit.SPADES, Rank.QUEEN), _c(Suit.SPADES, Rank.QUEEN),
        ]
        pts = count_attacking_points(
            tricks_won={"p0": [], "p1": [], "p2": [], "p3": []},
            attacker_ids={"p0"},
            bottom_deck=bottom,
            last_trick_winner_id="p0",
            last_trick_cards=last_cards,
            ctx=ctx,
        )
        assert pts == 8 * 5  # = 40

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

    def test_zero_pts_defending_wins_plus4(self):
        engine = _make_engine(_make_state_in_scoring(0))
        result = engine.end_round()
        assert result["winner"] == "defending"
        assert result["steps"] == 4

    def test_defender_rank_advances_on_win(self):
        engine = _make_engine(_make_state_in_scoring(0))  # defending +4
        engine.end_round()
        # Defenders are p0 and p2; both should be at rank SIX (TWO + 4 = SIX)
        assert engine._player("p0").rank == Rank.SIX
        assert engine._player("p2").rank == Rank.SIX

    def test_attacker_rank_advances_on_win(self):
        # 100 pts: threshold=80, step=20 → (100-80)//20 = 1 → attacking +1
        engine = _make_engine(_make_state_in_scoring(100))
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

    def test_not_game_over_when_defender_advances_into_ace(self):
        # Issue #52: defenders at KING who defend (+1) reach ACE but must
        # still successfully DEFEND at Ace next round to win the game.
        state = _make_state_in_scoring(60)  # defending +1
        state.players[0].rank = Rank.KING  # p0/p2 defenders
        state.players[2].rank = Rank.KING
        engine = _make_engine(state)
        result = engine.end_round()
        assert engine._player("p0").rank == Rank.ACE  # advanced into Ace
        assert result["game_over"] is False
        assert engine.state.phase == GamePhase.ROUND_OVER

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
