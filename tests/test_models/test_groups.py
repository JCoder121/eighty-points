"""Tests for find_identical_groups, find_tractors, and classify_play."""
import pytest

from shengji.models.card import Card, Rank, Suit
from shengji.models.trump import TrumpContext
from shengji.models.groups import (
    Single,
    IdenticalGroup,
    Tractor,
    Throw,
    find_identical_groups,
    find_tractors,
    classify_play,
)

S, H, D, C = Suit.SPADES, Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS
J = Suit.JOKER
BJ = Card(J, Rank.BIG_JOKER)
SJ = Card(J, Rank.SMALL_JOKER)


def c(suit: Suit, rank: Rank) -> Card:
    return Card(suit=suit, rank=rank)


def ctx(trump_rank: Rank, trump_suit: Suit | None = None) -> TrumpContext:
    return TrumpContext(trump_rank=trump_rank, trump_suit=trump_suit)


# ---------------------------------------------------------------------------
# find_identical_groups
# ---------------------------------------------------------------------------

class TestFindIdenticalGroups:
    TC = ctx(Rank.TWO, H)

    def test_single_card_no_groups(self):
        assert find_identical_groups([c(S, Rank.ACE)], self.TC) == []

    def test_two_different_cards_no_groups(self):
        assert find_identical_groups([c(S, Rank.ACE), c(S, Rank.KING)], self.TC) == []

    def test_pair_returned(self):
        cards = [c(S, Rank.ACE), c(S, Rank.ACE)]
        groups = find_identical_groups(cards, self.TC)
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_triple_returned(self):
        cards = [c(S, Rank.ACE)] * 3
        groups = find_identical_groups(cards, self.TC)
        assert len(groups) == 1
        assert len(groups[0]) == 3

    def test_quad_returned(self):
        cards = [c(S, Rank.ACE)] * 4
        groups = find_identical_groups(cards, self.TC)
        assert len(groups) == 1
        assert len(groups[0]) == 4

    def test_two_pairs_two_groups(self):
        cards = [c(S, Rank.ACE), c(S, Rank.ACE), c(S, Rank.KING), c(S, Rank.KING)]
        groups = find_identical_groups(cards, self.TC)
        assert len(groups) == 2

    def test_mixed_single_and_pair(self):
        cards = [c(S, Rank.ACE), c(S, Rank.ACE), c(S, Rank.KING)]
        groups = find_identical_groups(cards, self.TC)
        assert len(groups) == 1  # only the pair
        assert len(groups[0]) == 2

    def test_off_suit_trump_rank_different_suits_are_different_groups(self):
        """2♠ and 2♦ are different cards even though same tractor tier."""
        cards = [c(S, Rank.TWO), c(S, Rank.TWO), c(D, Rank.TWO), c(D, Rank.TWO)]
        groups = find_identical_groups(cards, self.TC)
        assert len(groups) == 2  # 2♠2♠ and 2♦2♦ are separate groups


# ---------------------------------------------------------------------------
# find_tractors — dynamic adjacency test cases from the plan
# ---------------------------------------------------------------------------

class TestFindTractors:
    def test_rank4_gap_3_and_5_adjacent(self):
        """Trump rank 4 → 3♠3♠5♠5♠ is a valid tractor."""
        tc = ctx(Rank.FOUR, H)
        cards = [c(S, Rank.THREE), c(S, Rank.THREE), c(S, Rank.FIVE), c(S, Rank.FIVE)]
        tractors = find_tractors(cards, tc)
        assert len(tractors) == 1
        assert len(tractors[0]) == 4

    def test_rank9_gap_8_and_10_adjacent(self):
        """Trump rank 9 → 8♠8♠10♠10♠ is a valid tractor."""
        tc = ctx(Rank.NINE, H)
        cards = [c(S, Rank.EIGHT), c(S, Rank.EIGHT), c(S, Rank.TEN), c(S, Rank.TEN)]
        tractors = find_tractors(cards, tc)
        assert len(tractors) == 1
        assert len(tractors[0]) == 4

    def test_rank3_gap_2_and_4_adjacent(self):
        """Trump rank 3 → 2♠2♠4♠4♠ is a valid tractor."""
        tc = ctx(Rank.THREE, H)
        cards = [c(S, Rank.TWO), c(S, Rank.TWO), c(S, Rank.FOUR), c(S, Rank.FOUR)]
        tractors = find_tractors(cards, tc)
        assert len(tractors) == 1
        assert len(tractors[0]) == 4

    def test_rank2_circular_ace_and_3_adjacent(self):
        """Trump rank 2 → A♠A♠3♠3♠ is a valid tractor (circular wrap)."""
        tc = ctx(Rank.TWO, H)
        cards = [c(S, Rank.ACE), c(S, Rank.ACE), c(S, Rank.THREE), c(S, Rank.THREE)]
        tractors = find_tractors(cards, tc)
        assert len(tractors) == 1
        assert len(tractors[0]) == 4

    def test_normal_consecutive_pair(self):
        tc = ctx(Rank.TWO, H)
        cards = [c(S, Rank.KING), c(S, Rank.KING), c(S, Rank.ACE), c(S, Rank.ACE)]
        tractors = find_tractors(cards, tc)
        assert len(tractors) == 1

    def test_non_consecutive_pairs_no_tractor(self):
        """Two pairs separated by a gap are NOT a tractor."""
        tc = ctx(Rank.TWO, H)
        # Queen and Ace are not adjacent (King is in between)
        cards = [c(S, Rank.QUEEN), c(S, Rank.QUEEN), c(S, Rank.ACE), c(S, Rank.ACE)]
        tractors = find_tractors(cards, tc)
        assert len(tractors) == 0

    def test_single_pair_no_tractor(self):
        tc = ctx(Rank.TWO, H)
        cards = [c(S, Rank.ACE), c(S, Rank.ACE)]
        assert find_tractors(cards, tc) == []

    def test_trump_tractor_off_suit_and_on_suit(self):
        """2♠2♠ + 2♥2♥ (off-suit + on-suit trump rank) form a tractor."""
        tc = ctx(Rank.TWO, H)
        cards = [c(S, Rank.TWO), c(S, Rank.TWO), c(H, Rank.TWO), c(H, Rank.TWO)]
        tractors = find_tractors(cards, tc)
        assert len(tractors) == 1

    def test_joker_pair_tractor(self):
        """SJ SJ + BJ BJ form a tractor."""
        tc = ctx(Rank.TWO, H)
        cards = [SJ, SJ, BJ, BJ]
        tractors = find_tractors(cards, tc)
        assert len(tractors) == 1

    def test_on_suit_trump_rank_and_sj_tractor(self):
        """2♥2♥ + SJ SJ form a tractor."""
        tc = ctx(Rank.TWO, H)
        cards = [c(H, Rank.TWO), c(H, Rank.TWO), SJ, SJ]
        tractors = find_tractors(cards, tc)
        assert len(tractors) == 1

    def test_trump_suit_normal_tractor(self):
        """K♥K♥ A♥A♥ (trump suit non-rank) form a tractor."""
        tc = ctx(Rank.TWO, H)
        cards = [c(H, Rank.KING), c(H, Rank.KING), c(H, Rank.ACE), c(H, Rank.ACE)]
        tractors = find_tractors(cards, tc)
        assert len(tractors) == 1

    def test_three_length_tractor(self):
        tc = ctx(Rank.TWO, H)
        cards = [
            c(S, Rank.JACK), c(S, Rank.JACK),
            c(S, Rank.QUEEN), c(S, Rank.QUEEN),
            c(S, Rank.KING), c(S, Rank.KING),
        ]
        tractors = find_tractors(cards, tc)
        assert len(tractors) == 1
        assert len(tractors[0]) == 6

    def test_two_separate_tractors(self):
        tc = ctx(Rank.TWO, H)
        # 3♠3♠4♠4♠ and 9♠9♠10♠10♠ — two separate tractors
        cards = [
            c(S, Rank.THREE), c(S, Rank.THREE),
            c(S, Rank.FOUR), c(S, Rank.FOUR),
            c(S, Rank.NINE), c(S, Rank.NINE),
            c(S, Rank.TEN), c(S, Rank.TEN),
        ]
        tractors = find_tractors(cards, tc)
        assert len(tractors) == 2

    def test_trump_suit_top_adjacent_to_off_suit_trump_rank(self):
        """A♥A♥ + 2♠2♠ form a tractor (tier 1 top → tier 2)."""
        tc = ctx(Rank.TWO, H)
        cards = [c(H, Rank.ACE), c(H, Rank.ACE), c(S, Rank.TWO), c(S, Rank.TWO)]
        tractors = find_tractors(cards, tc)
        assert len(tractors) == 1


# ---------------------------------------------------------------------------
# classify_play
# ---------------------------------------------------------------------------

class TestClassifyPlay:
    TC = ctx(Rank.TWO, H)

    def test_single(self):
        result = classify_play([c(S, Rank.ACE)], self.TC)
        assert isinstance(result, Single)

    def test_pair(self):
        result = classify_play([c(S, Rank.ACE), c(S, Rank.ACE)], self.TC)
        assert isinstance(result, IdenticalGroup)
        assert result.count == 2

    def test_triple(self):
        cards = [c(S, Rank.ACE)] * 3
        result = classify_play(cards, self.TC)
        assert isinstance(result, IdenticalGroup)
        assert result.count == 3

    def test_tractor_two_pairs(self):
        cards = [c(S, Rank.KING), c(S, Rank.KING), c(S, Rank.ACE), c(S, Rank.ACE)]
        result = classify_play(cards, self.TC)
        assert isinstance(result, Tractor)
        assert result.multiplicity == 2
        assert result.length == 2

    def test_tractor_three_pairs(self):
        tc = ctx(Rank.TWO, H)
        cards = [
            c(S, Rank.JACK), c(S, Rank.JACK),
            c(S, Rank.QUEEN), c(S, Rank.QUEEN),
            c(S, Rank.KING), c(S, Rank.KING),
        ]
        result = classify_play(cards, tc)
        assert isinstance(result, Tractor)
        assert result.multiplicity == 2
        assert result.length == 3

    def test_tractor_dynamic_rank4(self):
        tc = ctx(Rank.FOUR, H)
        cards = [c(S, Rank.THREE), c(S, Rank.THREE), c(S, Rank.FIVE), c(S, Rank.FIVE)]
        result = classify_play(cards, tc)
        assert isinstance(result, Tractor)

    def test_throw_pair_and_single(self):
        """A pair + a single from the same suit = Throw."""
        cards = [c(S, Rank.ACE), c(S, Rank.ACE), c(S, Rank.KING)]
        result = classify_play(cards, self.TC)
        assert isinstance(result, Throw)

    def test_throw_two_non_consecutive_pairs(self):
        """Q♠Q♠ + A♠A♠ (non-consecutive) = Throw."""
        cards = [c(S, Rank.QUEEN), c(S, Rank.QUEEN), c(S, Rank.ACE), c(S, Rank.ACE)]
        result = classify_play(cards, self.TC)
        assert isinstance(result, Throw)

    def test_throw_two_singles(self):
        cards = [c(S, Rank.ACE), c(S, Rank.KING)]
        result = classify_play(cards, self.TC)
        assert isinstance(result, Throw)

    def test_empty_play_raises(self):
        with pytest.raises(ValueError):
            classify_play([], self.TC)

    def test_all_off_suit_trump_ranks_identical_group(self):
        """2♠2♦2♣ off-suit trump ranks are all at the same card_order position."""
        tc = ctx(Rank.TWO, H)
        cards = [c(S, Rank.TWO), c(D, Rank.TWO)]
        result = classify_play(cards, tc)
        assert isinstance(result, IdenticalGroup)
        assert result.count == 2

    def test_joker_pair(self):
        result = classify_play([SJ, SJ], self.TC)
        assert isinstance(result, IdenticalGroup)
        assert result.count == 2

    def test_joker_tractor(self):
        result = classify_play([SJ, SJ, BJ, BJ], self.TC)
        assert isinstance(result, Tractor)
        assert result.multiplicity == 2
        assert result.length == 2
