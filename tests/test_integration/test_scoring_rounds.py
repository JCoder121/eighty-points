"""Round scoring driven through end_round() with the REAL UpgradeStrategy.

The unit suite (tests/test_engine/test_scoring.py) covers threshold bands,
the +3 attacking cap (issue #51), and game-over rules (issue #52) with a
stub strategy; these tests exercise rank advancement, team swaps, and
leader rotation end to end.
"""
from __future__ import annotations

from shengji.engine.engine import GameEngine
from shengji.engine.scoring import count_attacking_points
from shengji.models.card import Rank
from shengji.models.game_state import GamePhase, GameState
from shengji.modes.upgrade import UpgradeStrategy

from tests.test_integration.helpers import CL, D, H, S, c, ctx, make_state

TR = ctx(trump_rank=Rank.TWO, trump_suit=H)


def _scoring_state(defender_rank: Rank, attacker_pts: int) -> tuple[GameEngine, GameState]:
    """SCORING-phase state: p0/p2 defend at *defender_rank*; p1/p3 attack and
    have won *attacker_pts* points (in Kings).  A defender won the last trick."""
    state = make_state("upgrade", "p0", ranks={"p0": defender_rank, "p2": defender_rank})
    engine = GameEngine(state, UpgradeStrategy(), deal_delay=0)
    state.trump_context = TR
    for p in state.players:
        p.is_defending = p.id in ("p0", "p2")
        p.team = "defending" if p.is_defending else "attacking"
    kings = [c(S, Rank.KING)] * (attacker_pts // 10)
    state.tricks_won = {"p0": [[c(D, Rank.THREE)]], "p1": [kings] if kings else [],
                        "p2": [], "p3": []}
    state.bottom_deck = []
    state.current_leader_id = "p0"  # defender won the last trick
    state.phase = GamePhase.SCORING
    return engine, state


class TestEndRoundIntegration:
    def test_huge_attacker_score_caps_at_three_steps(self):
        """Issue #51 (fixed): a blowout with a big bottom multiplier must not
        advance the attackers more than +3 ranks."""
        engine, state = _scoring_state(Rank.THREE, 0)
        # Attackers p1/p3 start at TWO; p1 wins the last trick with a single,
        # doubling a 100-point bottom: 100 (tricks) + 2*100 = 300 points.
        state.bottom_deck = [c(S, Rank.KING)] * 10
        state.current_leader_id = "p1"
        state.tricks_won["p1"] = [[c(S, Rank.KING)] * 10, [c(S, Rank.THREE)]]
        result = engine.end_round()
        assert result["attacking_points"] == 300
        assert result["winner"] == "attacking"
        assert result["steps"] == 3, "attacking advancement capped at +3"
        assert engine._player("p1").rank == Rank.FIVE  # TWO + 3
        assert engine._player("p3").rank == Rank.FIVE

    def test_attacker_win_swaps_teams_and_rotates_leader(self):
        engine, state = _scoring_state(Rank.FIVE, 120)  # attacking +2
        result = engine.end_round()
        assert result["winner"] == "attacking"
        # Former attackers p1/p3 defend next round; the new leader is one of them.
        assert result["next_round_leader_id"] in ("p1", "p3")
        defenders = {p.id for p in state.players if p.is_defending}
        assert defenders == {"p1", "p3"}


class TestBottomMultiplierClassification:
    def test_multiplier_classifies_whole_last_trick(self):
        """KNOWN LIMITATION (pinned): the bottom multiplier classifies the
        concatenated 4-player last trick, which is a Throw -> length 1 ->
        multiplier 2, even when the winning play itself was a 2x2 tractor
        (which alone would give 2*2 = 4x)."""
        bottom = [c(S, Rank.KING), c(S, Rank.KING)]  # 20 pts
        last_trick = [
            c(H, Rank.FOUR), c(H, Rank.FOUR), c(H, Rank.FIVE), c(H, Rank.FIVE),  # winner
            c(S, Rank.THREE), c(S, Rank.SIX), c(S, Rank.NINE), c(S, Rank.TEN),
            c(D, Rank.THREE), c(D, Rank.SIX), c(D, Rank.NINE), c(D, Rank.TEN),
            c(CL, Rank.THREE), c(CL, Rank.SIX), c(CL, Rank.NINE), c(CL, Rank.TEN),
        ]
        pts = count_attacking_points(
            tricks_won={"p0": [], "p1": [], "p2": [], "p3": []},
            attacker_ids={"p1"},
            bottom_deck=bottom,
            last_trick_winner_id="p1",
            last_trick_cards=last_trick,
            ctx=TR,
        )
        assert pts == 40  # 20 * 2x, not 20 * 4x
