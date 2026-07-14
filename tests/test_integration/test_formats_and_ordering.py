"""Format-classification and trump-ordering edge cases.

Covers oddities not exercised by the unit suites: the three-position
circular wrap, no-trump joker ordering, and equal-strength trump-rank ties
resolved inside a trick.
"""
from __future__ import annotations

from shengji.engine.tricks import resolve_trick_winner
from shengji.models.card import Rank, Suit
from shengji.models.groups import IdenticalGroup, Throw, Tractor, classify_play

from tests.test_integration.helpers import BJ, CL, D, H, S, SJ, c, ctx


class TestCircularWrapThreePositions:
    """Trump rank 2: in spades the filtered order is [3..K, A], so A wraps to 3.

    A two-position wrap (A-3) is detected as a tractor (covered in
    tests/test_models/test_groups.py).  A THREE-position wrap (K-A-3) would
    ideally be one 2x3 tractor, but the engine's documented limitation splits
    the wrap into a K-A tractor plus a 3-pair Throw.  Pin the current
    behavior so any change to wrap handling is deliberate.
    """

    def test_k_a_3_wrap_splits_into_throw(self):
        tr = ctx()
        cards = [
            c(S, Rank.KING), c(S, Rank.KING),
            c(S, Rank.ACE), c(S, Rank.ACE),
            c(S, Rank.THREE), c(S, Rank.THREE),
        ]
        fmt = classify_play(cards, tr)
        assert isinstance(fmt, Throw)
        kinds = sorted(type(comp).__name__ for comp in fmt.components)
        assert kinds == [IdenticalGroup.__name__, Tractor.__name__]


class TestNoTrumpOrdering:
    """No-trump rounds: jokers must still outrank the trump-rank (level) cards."""

    def test_jokers_outrank_trump_rank_cards(self):
        tr = ctx(trump_suit=None)
        two_s = c(S, Rank.TWO)
        assert tr.card_order(BJ) > tr.card_order(two_s)
        assert tr.card_order(SJ) > tr.card_order(two_s)

    def test_big_joker_wins_trick_over_trump_rank_lead(self):
        tr = ctx(trump_suit=None)
        two_s = c(S, Rank.TWO)
        trick = [("p0", [two_s]), ("p1", [BJ])]
        led_suit = tr.effective_suit(two_s)  # "trump" even with no trump suit
        assert resolve_trick_winner(trick, led_suit, tr) == "p1"


class TestOffSuitTrumpRankTies:
    """Off-suit trump-rank cards are equal in strength; first player wins ties."""

    TC = ctx(trump_suit=Suit.CLUBS)

    def test_equal_off_suit_trump_ranks_first_player_wins(self):
        two_h, two_d = c(H, Rank.TWO), c(D, Rank.TWO)
        assert self.TC.card_order(two_h) == self.TC.card_order(two_d)
        trick = [("p0", [two_h]), ("p1", [two_d])]
        assert resolve_trick_winner(trick, "trump", self.TC) == "p0"

    def test_on_suit_trump_rank_beats_off_suit(self):
        two_c, two_h = c(CL, Rank.TWO), c(H, Rank.TWO)
        assert self.TC.card_order(two_c) > self.TC.card_order(two_h)
        trick = [("p0", [two_h]), ("p1", [two_c])]
        assert resolve_trick_winner(trick, "trump", self.TC) == "p1"
