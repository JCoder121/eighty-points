"""Gap pins for tractors that live inside the trump hierarchy.

Behavior probed and found correct during the Phase-2 audit (edge-case matrix
cells 2.7, 2.17, 2.18 — Tier C4/C5).  Rule numbers refer to ``docs/RULES.md``.

Covered:
  R8 / R37   trump-ladder tractors of length 3 and 5 (tiers 3→4→5 and 1→5)
  R8 / D18   TR-skip adjacency INSIDE the trump suit (tier 1), the trump-side
             twin of the tier-0 skip that is already tested
"""
from __future__ import annotations

from shengji.models.card import Card, Rank, Suit
from shengji.models.groups import Tractor, classify_play
from shengji.models.trump import TrumpContext


def _c(suit: Suit, rank: Rank) -> Card:
    return Card(suit=suit, rank=rank)


SJ = Card(Suit.JOKER, Rank.SMALL_JOKER)
BJ = Card(Suit.JOKER, Rank.BIG_JOKER)


class TestTrumpHierarchyTractors:
    """R8's trump-ladder rungs are consecutive strength positions, so pairs on
    neighbouring rungs chain into a tractor exactly as suited pairs do."""

    ctx = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS)

    def test_three_rung_tractor_trump_rank_suit_to_both_jokers(self):
        # tier 3 (2♥, trump-rank of the trump suit) → tier 4 (SJ) → tier 5 (BJ)
        cards = [_c(Suit.HEARTS, Rank.TWO), _c(Suit.HEARTS, Rank.TWO), SJ, SJ, BJ, BJ]
        fmt = classify_play(cards, self.ctx)
        assert isinstance(fmt, Tractor)
        assert (fmt.multiplicity, fmt.length) == (2, 3)

    def test_five_rung_tractor_spans_the_whole_top_of_the_ladder(self):
        # tier 1 top (A♥) → tier 2 (off-suit trump rank 2♠) → tier 3 (2♥)
        # → tier 4 (SJ) → tier 5 (BJ)
        cards = [
            _c(Suit.HEARTS, Rank.ACE), _c(Suit.HEARTS, Rank.ACE),
            _c(Suit.SPADES, Rank.TWO), _c(Suit.SPADES, Rank.TWO),
            _c(Suit.HEARTS, Rank.TWO), _c(Suit.HEARTS, Rank.TWO),
            SJ, SJ,
            BJ, BJ,
        ]
        fmt = classify_play(cards, self.ctx)
        assert isinstance(fmt, Tractor)
        assert (fmt.multiplicity, fmt.length) == (2, 5)


class TestTrumpSuitRankSkipAdjacency:
    """R8: the trump-rank card is removed from its suit's ladder, so the ranks
    either side of it become adjacent.  Only the tier-0 (non-trump suit) form
    of this rule was tested; this pins the tier-1 (trump suit) form."""

    ctx = TrumpContext(trump_rank=Rank.FIVE, trump_suit=Suit.HEARTS)

    def test_four_and_six_of_the_trump_suit_are_adjacent_at_trump_rank_five(self):
        cards = [
            _c(Suit.HEARTS, Rank.FOUR), _c(Suit.HEARTS, Rank.FOUR),
            _c(Suit.HEARTS, Rank.SIX), _c(Suit.HEARTS, Rank.SIX),
        ]
        fmt = classify_play(cards, self.ctx)
        assert isinstance(fmt, Tractor)
        assert (fmt.multiplicity, fmt.length) == (2, 2)

    def test_same_shape_in_a_non_trump_suit_is_also_a_tractor(self):
        # Control: the tier-0 twin of the rule, so a regression that breaks one
        # side of the ladder is visibly asymmetric.
        cards = [
            _c(Suit.SPADES, Rank.FOUR), _c(Suit.SPADES, Rank.FOUR),
            _c(Suit.SPADES, Rank.SIX), _c(Suit.SPADES, Rank.SIX),
        ]
        assert isinstance(classify_play(cards, self.ctx), Tractor)
