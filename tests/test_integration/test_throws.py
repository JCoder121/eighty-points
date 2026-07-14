"""Throw (甩牌) resolution edge cases.

Throw VALIDATION is unit-tested in tests/test_engine/test_tricks.py
(TestValidateThrow); these tests cover how a led throw is BEATEN (or not)
during trick resolution.
"""
from __future__ import annotations

from shengji.engine.tricks import resolve_trick_winner
from shengji.models.card import Rank
from shengji.models.groups import Throw, classify_play

from tests.test_integration.helpers import D, H, S, c, ctx

TR = ctx(trump_rank=Rank.TWO, trump_suit=H)


def _throw_a_kk() -> list:
    """A♠ + K♠K♠ — single + pair from the same suit."""
    return [c(S, Rank.ACE), c(S, Rank.KING), c(S, Rank.KING)]


class TestThrowResolution:
    def test_single_plus_pair_classifies_as_throw(self):
        fmt = classify_play(_throw_a_kk(), TR)
        assert isinstance(fmt, Throw)

    def test_matching_trump_throw_beats_led_throw(self):
        """A void follower covering BOTH components with trump wins."""
        led = _throw_a_kk()
        trump_throw = [c(H, Rank.THREE), c(H, Rank.FOUR), c(H, Rank.FOUR)]
        trick = [("p0", led), ("p1", trump_throw)]
        assert resolve_trick_winner(trick, "spades", TR) == "p1"

    def test_partial_trump_cannot_beat_throw(self):
        """Trumping only the single while the pair goes uncovered loses."""
        led = _throw_a_kk()
        partial = [c(H, Rank.THREE), c(D, Rank.SIX), c(D, Rank.SEVEN)]
        trick = [("p0", led), ("p1", partial)]
        assert resolve_trick_winner(trick, "spades", TR) == "p0"

    def test_higher_same_suit_throw_beats_led_throw(self):
        """A same-suit follower with a higher single AND higher pair wins."""
        led = [c(S, Rank.KING), c(S, Rank.NINE), c(S, Rank.NINE)]
        higher = [c(S, Rank.ACE), c(S, Rank.QUEEN), c(S, Rank.QUEEN)]
        trick = [("p0", led), ("p1", higher)]
        assert resolve_trick_winner(trick, "spades", TR) == "p1"

    def test_same_suit_singles_cannot_beat_pair_component(self):
        """Three higher singles (no pair) cannot match the pair component."""
        led = [c(S, Rank.KING), c(S, Rank.NINE), c(S, Rank.NINE)]
        three_singles = [c(S, Rank.ACE), c(S, Rank.JACK), c(S, Rank.TEN)]
        trick = [("p0", led), ("p1", three_singles)]
        assert resolve_trick_winner(trick, "spades", TR) == "p0"

    def test_all_trump_throw_lower_follower_loses(self):
        """A throw led IN trump: an in-trump follower with lower cards loses."""
        led = [c(H, Rank.ACE), c(H, Rank.KING), c(H, Rank.KING)]
        assert isinstance(classify_play(led, TR), Throw)
        lower = [c(H, Rank.QUEEN), c(H, Rank.JACK), c(H, Rank.JACK)]
        trick = [("p0", led), ("p1", lower)]
        assert resolve_trick_winner(trick, "trump", TR) == "p0"
