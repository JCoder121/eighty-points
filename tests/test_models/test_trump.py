"""Tests for TrumpContext: card ordering, effective suit, and tractor adjacency."""
import pytest

from shengji.models.card import Card, Rank, Suit, RANK_ORDER
from shengji.models.trump import TrumpContext

# Convenience aliases
S, H, D, C = Suit.SPADES, Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS
J = Suit.JOKER

BJ = Card(J, Rank.BIG_JOKER)
SJ = Card(J, Rank.SMALL_JOKER)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ctx(trump_rank: Rank, trump_suit: Suit | None = None) -> TrumpContext:
    return TrumpContext(trump_rank=trump_rank, trump_suit=trump_suit)


def c(suit: Suit, rank: Rank) -> Card:
    return Card(suit=suit, rank=rank)


# ---------------------------------------------------------------------------
# card_order — basic tier assignment
# ---------------------------------------------------------------------------

class TestCardOrder:
    def test_big_joker_highest(self):
        tc = ctx(Rank.TWO, H)
        assert tc.card_order(BJ) == (5, 0)

    def test_small_joker_second_highest(self):
        tc = ctx(Rank.TWO, H)
        assert tc.card_order(SJ) == (4, 0)

    def test_trump_rank_on_suit_tier3(self):
        tc = ctx(Rank.TWO, H)
        assert tc.card_order(c(H, Rank.TWO)) == (3, 0)

    def test_trump_rank_off_suit_tier2(self):
        tc = ctx(Rank.TWO, H)
        assert tc.card_order(c(S, Rank.TWO)) == (2, 0)
        assert tc.card_order(c(D, Rank.TWO)) == (2, 0)
        assert tc.card_order(c(C, Rank.TWO)) == (2, 0)

    def test_trump_suit_non_rank_tier1(self):
        tc = ctx(Rank.TWO, H)
        order = tc.card_order(c(H, Rank.ACE))
        assert order[0] == 1

    def test_off_suit_non_rank_tier0(self):
        tc = ctx(Rank.TWO, H)
        order = tc.card_order(c(S, Rank.ACE))
        assert order[0] == 0

    def test_no_trump_trump_rank_tier2(self):
        """In no-trump mode all trump-rank cards go to tier 2."""
        tc = ctx(Rank.FOUR, None)
        assert tc.card_order(c(S, Rank.FOUR)) == (2, 0)
        assert tc.card_order(c(H, Rank.FOUR)) == (2, 0)
        assert tc.card_order(c(D, Rank.FOUR)) == (2, 0)
        assert tc.card_order(c(C, Rank.FOUR)) == (2, 0)

    def test_no_trump_suited_cards_tier0(self):
        tc = ctx(Rank.FOUR, None)
        assert tc.card_order(c(H, Rank.ACE))[0] == 0
        assert tc.card_order(c(S, Rank.THREE))[0] == 0


# ---------------------------------------------------------------------------
# Full ordering: trump rank 2, trump suit Hearts
# ---------------------------------------------------------------------------

class TestFullOrdering:
    """BJ > SJ > 2♥ > 2♠=2♦=2♣ > A♥ > K♥ > ... > 3♥ > A♠ > K♠ > ..."""

    TC = ctx(Rank.TWO, H)

    def test_joker_hierarchy(self):
        assert self.TC.card_order(BJ) > self.TC.card_order(SJ)

    def test_joker_beats_trump_rank_on_suit(self):
        assert self.TC.card_order(SJ) > self.TC.card_order(c(H, Rank.TWO))

    def test_trump_rank_on_suit_beats_off_suit(self):
        assert self.TC.card_order(c(H, Rank.TWO)) > self.TC.card_order(c(S, Rank.TWO))

    def test_trump_rank_off_suits_equal(self):
        assert self.TC.card_order(c(S, Rank.TWO)) == self.TC.card_order(c(D, Rank.TWO))
        assert self.TC.card_order(c(D, Rank.TWO)) == self.TC.card_order(c(C, Rank.TWO))

    def test_trump_rank_off_suit_beats_trump_suit_cards(self):
        assert self.TC.card_order(c(S, Rank.TWO)) > self.TC.card_order(c(H, Rank.ACE))

    def test_trump_suit_ascending(self):
        """Hearts cards (trump suit) ascend 3♥ < 4♥ < ... < A♥ (2♥ excluded)."""
        filtered = [r for r in RANK_ORDER if r != Rank.TWO]  # 3..A
        prev_order = self.TC.card_order(c(H, filtered[0]))
        for rank in filtered[1:]:
            curr_order = self.TC.card_order(c(H, rank))
            assert curr_order > prev_order, f"{rank} should be > previous"
            prev_order = curr_order

    def test_off_suit_ascending(self):
        """Spades (non-trump) ascend with 2 removed: 3♠ < 4♠ < ... < A♠."""
        filtered = [r for r in RANK_ORDER if r != Rank.TWO]
        prev_order = self.TC.card_order(c(S, filtered[0]))
        for rank in filtered[1:]:
            curr_order = self.TC.card_order(c(S, rank))
            assert curr_order > prev_order
            prev_order = curr_order

    def test_trump_suit_beats_off_suit_same_rank(self):
        assert self.TC.card_order(c(H, Rank.ACE)) > self.TC.card_order(c(S, Rank.ACE))


# ---------------------------------------------------------------------------
# No-trump ordering
# ---------------------------------------------------------------------------

class TestNoTrumpOrdering:
    TC = ctx(Rank.TWO, None)

    def test_jokers_highest(self):
        assert self.TC.card_order(BJ) > self.TC.card_order(SJ)
        assert self.TC.card_order(SJ) > self.TC.card_order(c(S, Rank.TWO))

    def test_trump_rank_all_equal(self):
        assert self.TC.card_order(c(S, Rank.TWO)) == self.TC.card_order(c(H, Rank.TWO))
        assert self.TC.card_order(c(H, Rank.TWO)) == self.TC.card_order(c(D, Rank.TWO))

    def test_trump_rank_beats_suited(self):
        assert self.TC.card_order(c(S, Rank.TWO)) > self.TC.card_order(c(S, Rank.ACE))

    def test_suits_all_tier0(self):
        for suit in (S, H, D, C):
            assert self.TC.card_order(c(suit, Rank.ACE))[0] == 0


# ---------------------------------------------------------------------------
# effective_suit
# ---------------------------------------------------------------------------

class TestEffectiveSuit:
    TC = ctx(Rank.TWO, H)

    def test_jokers_are_trump(self):
        assert self.TC.effective_suit(BJ) == "trump"
        assert self.TC.effective_suit(SJ) == "trump"

    def test_trump_rank_on_suit_is_trump(self):
        assert self.TC.effective_suit(c(H, Rank.TWO)) == "trump"

    def test_trump_rank_off_suit_is_trump(self):
        assert self.TC.effective_suit(c(S, Rank.TWO)) == "trump"
        assert self.TC.effective_suit(c(D, Rank.TWO)) == "trump"

    def test_trump_suit_card_is_trump(self):
        assert self.TC.effective_suit(c(H, Rank.ACE)) == "trump"
        assert self.TC.effective_suit(c(H, Rank.THREE)) == "trump"

    def test_off_suit_card_keeps_suit(self):
        assert self.TC.effective_suit(c(S, Rank.ACE)) == "spades"
        assert self.TC.effective_suit(c(D, Rank.KING)) == "diamonds"
        assert self.TC.effective_suit(c(C, Rank.FIVE)) == "clubs"

    def test_no_trump_trump_rank_is_trump(self):
        tc_nt = ctx(Rank.TWO, None)
        # In no-trump, trump-rank cards are still trump for trick-following.
        assert tc_nt.effective_suit(c(S, Rank.TWO)) == "trump"
        assert tc_nt.effective_suit(c(H, Rank.TWO)) == "trump"

    def test_no_trump_jokers_still_trump(self):
        tc_nt = ctx(Rank.TWO, None)
        assert tc_nt.effective_suit(BJ) == "trump"
        assert tc_nt.effective_suit(SJ) == "trump"


# ---------------------------------------------------------------------------
# are_tractor_adjacent — dynamic adjacency
# ---------------------------------------------------------------------------

class TestTractorAdjacency:
    """The gap left by removing the trump rank creates new adjacent pairs."""

    def test_rank4_gap_makes_3_and_5_adjacent(self):
        tc = ctx(Rank.FOUR, H)
        assert tc.are_tractor_adjacent(c(S, Rank.THREE), c(S, Rank.FIVE))

    def test_rank4_normal_pairs_also_adjacent(self):
        tc = ctx(Rank.FOUR, H)
        assert tc.are_tractor_adjacent(c(S, Rank.FIVE), c(S, Rank.SIX))

    def test_rank4_three_not_adjacent_to_six(self):
        tc = ctx(Rank.FOUR, H)
        assert not tc.are_tractor_adjacent(c(S, Rank.THREE), c(S, Rank.SIX))

    def test_rank9_gap_makes_8_and_10_adjacent(self):
        tc = ctx(Rank.NINE, H)
        assert tc.are_tractor_adjacent(c(S, Rank.EIGHT), c(S, Rank.TEN))

    def test_rank3_gap_makes_2_and_4_adjacent(self):
        tc = ctx(Rank.THREE, H)
        assert tc.are_tractor_adjacent(c(S, Rank.TWO), c(S, Rank.FOUR))

    def test_rank2_circular_makes_ace_and_3_adjacent(self):
        """When trump rank is 2, Ace and 3 wrap around and become adjacent
        in non-trump suits."""
        tc = ctx(Rank.TWO, H)
        assert tc.are_tractor_adjacent(c(S, Rank.ACE), c(S, Rank.THREE))

    def test_trump_rank_card_not_adjacent_to_regular_card(self):
        """4♠ is now trump (off-suit trump rank), not part of the spades suit."""
        tc = ctx(Rank.FOUR, H)
        # 3♠ is tier 0; 4♠ is tier 2 — not adjacent (tier gap > 1)
        assert not tc.are_tractor_adjacent(c(S, Rank.THREE), c(S, Rank.FOUR))

    def test_joker_pair_adjacent(self):
        tc = ctx(Rank.TWO, H)
        assert tc.are_tractor_adjacent(SJ, BJ)

    def test_on_suit_trump_rank_adjacent_to_joker(self):
        tc = ctx(Rank.TWO, H)
        assert tc.are_tractor_adjacent(c(H, Rank.TWO), SJ)

    def test_off_suit_trump_rank_adjacent_to_on_suit(self):
        tc = ctx(Rank.TWO, H)
        assert tc.are_tractor_adjacent(c(S, Rank.TWO), c(H, Rank.TWO))

    def test_trump_suit_top_adjacent_to_off_suit_trump_rank(self):
        """A♥ (highest trump-suit non-rank card) is adjacent to off-suit trump ranks."""
        tc = ctx(Rank.TWO, H)
        assert tc.are_tractor_adjacent(c(H, Rank.ACE), c(S, Rank.TWO))

    def test_trump_suit_top_not_circularly_adjacent_to_trump_suit_bottom(self):
        """A♥ is NOT circularly adjacent to 3♥ within the trump suit (tier 1)."""
        tc = ctx(Rank.TWO, H)
        assert not tc.are_tractor_adjacent(c(H, Rank.ACE), c(H, Rank.THREE))

    def test_different_non_trump_suits_not_adjacent(self):
        tc = ctx(Rank.TWO, H)
        assert not tc.are_tractor_adjacent(c(S, Rank.ACE), c(D, Rank.ACE))

    def test_non_trump_suit_and_trump_suit_not_adjacent(self):
        tc = ctx(Rank.TWO, H)
        assert not tc.are_tractor_adjacent(c(S, Rank.ACE), c(H, Rank.ACE))
