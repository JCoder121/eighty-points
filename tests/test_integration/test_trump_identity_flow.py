"""Engine-level regression flows for trump-rank identity (issue #50, fixed).

Two different off-suit trump-rank cards (e.g. 2♦ + 2♣) tie in strength but
are NOT identical, so they never form a pair.  Unit coverage lives in
tests/test_models/test_groups.py and tests/test_engine/test_tricks.py
(TestMismatchedTrumpRuff); these tests run the same rule through
GameEngine.play_cards on real state.
"""
from __future__ import annotations

from shengji.models.card import Rank
from shengji.models.groups import IdenticalGroup, Throw

from tests.test_integration.helpers import CL, D, H, S, c, ctx, make_engine, setup_playing

TR = ctx(trump_rank=Rank.TWO, trump_suit=H)


class TestMismatchedTrumpRuffFlow:
    def test_lead_of_two_different_trump_rank_cards_is_a_throw(self):
        """Leading 2♦+2♣ is a Throw of two singles, not a phantom pair lead."""
        engine, state = make_engine()
        hands = {
            "p0": [c(D, Rank.TWO), c(CL, Rank.TWO)],
            "p1": [c(H, Rank.THREE), c(H, Rank.FOUR)],
            "p2": [c(H, Rank.FIVE), c(H, Rank.SIX)],
            "p3": [c(H, Rank.SEVEN), c(H, Rank.EIGHT)],
        }
        setup_playing(engine, hands, [], TR)
        engine.play_cards("p0", [c(D, Rank.TWO), c(CL, Rank.TWO)])
        led = state._led_format
        assert isinstance(led, Throw)
        assert not isinstance(led, IdenticalGroup)

    def test_mismatched_trump_ruff_does_not_steal_pair_trick(self):
        """A void follower ruffing K♠K♠ with 2♦+2♣ is a degraded follow: the
        engine accepts the play but the trick stays with the leader."""
        engine, state = make_engine()
        hands = {
            "p0": [c(S, Rank.KING), c(S, Rank.KING)],
            "p1": [c(D, Rank.TWO), c(CL, Rank.TWO)],  # void in spades
            "p2": [c(S, Rank.THREE), c(S, Rank.FOUR)],
            "p3": [c(S, Rank.FIVE), c(S, Rank.SIX)],
        }
        setup_playing(engine, hands, [], TR)
        result = engine.play_cards("p0", [c(S, Rank.KING), c(S, Rank.KING)])
        assert result["trick_complete"] is False
        engine.play_cards("p1", [c(D, Rank.TWO), c(CL, Rank.TWO)])
        engine.play_cards("p2", [c(S, Rank.THREE), c(S, Rank.FOUR)])
        result = engine.play_cards("p3", [c(S, Rank.FIVE), c(S, Rank.SIX)])
        assert result["trick_complete"] is True
        assert result["trick_winner"] == "p0"
