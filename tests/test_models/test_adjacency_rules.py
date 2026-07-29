"""Pin tests for the ruled adjacency semantics: D22 (suit-aware) and D18 (skip
empty strength positions).

D22 — `are_tractor_adjacent` additionally requires the two cards to share an
effective suit.  Closes audit finding F1 (docs/reports/2026-07-29-rules-audit.md
§3.1): two pairs in different non-trump suits at consecutive tier-0 positions
used to classify as a Tractor and so bypassed throw validation entirely.

D18 — two cards are adjacent iff no *occupied* strength position lies strictly
between their keys, where "occupied" means a position some card actually maps to
in the current trump context.  Replaces the old `tier2 == tier1 + 1` stepping.
"""
from __future__ import annotations


from shengji.models.card import Card, Rank, Suit
from shengji.models.groups import Throw, Tractor, classify_play, find_tractors
from shengji.models.trump import TrumpContext

S, H, D, C = Suit.SPADES, Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS
J = Suit.JOKER
BJ = Card(J, Rank.BIG_JOKER)
SJ = Card(J, Rank.SMALL_JOKER)


def c(suit: Suit, rank: Rank) -> Card:
    return Card(suit=suit, rank=rank)


def ctx(trump_rank: Rank, trump_suit: Suit | None = None) -> TrumpContext:
    return TrumpContext(trump_rank=trump_rank, trump_suit=trump_suit)


def pair(suit: Suit, rank: Rank) -> list[Card]:
    return [c(suit, rank), c(suit, rank)]


# ---------------------------------------------------------------------------
# D22 — adjacency requires a shared effective suit
# ---------------------------------------------------------------------------

class TestD22CrossSuitIsNotATractor:
    """The three audit F1 repros (♥ trump, rank 2)."""

    TC = ctx(Rank.TWO, H)

    def test_consecutive_positions_different_suits_not_adjacent(self):
        assert not self.TC.are_tractor_adjacent(c(S, Rank.THREE), c(D, Rank.FOUR))

    def test_wrap_across_different_suits_not_adjacent(self):
        assert not self.TC.are_tractor_adjacent(c(S, Rank.ACE), c(C, Rank.THREE))

    def test_3s3s_4d4d_is_a_throw(self):
        result = classify_play(pair(S, Rank.THREE) + pair(D, Rank.FOUR), self.TC)
        assert isinstance(result, Throw)

    def test_ks_ks_ac_ac_is_a_throw(self):
        result = classify_play(pair(S, Rank.KING) + pair(C, Rank.ACE), self.TC)
        assert isinstance(result, Throw)

    def test_as_as_3c_3c_wrap_is_a_throw(self):
        result = classify_play(pair(S, Rank.ACE) + pair(C, Rank.THREE), self.TC)
        assert isinstance(result, Throw)

    def test_three_suit_run_is_a_throw(self):
        cards = pair(S, Rank.THREE) + pair(D, Rank.FOUR) + pair(C, Rank.FIVE)
        assert isinstance(classify_play(cards, self.TC), Throw)

    def test_find_tractors_returns_no_cross_suit_runs(self):
        assert find_tractors(pair(S, Rank.THREE) + pair(D, Rank.FOUR), self.TC) == []
        assert find_tractors(pair(S, Rank.KING) + pair(C, Rank.ACE), self.TC) == []
        assert find_tractors(pair(S, Rank.ACE) + pair(C, Rank.THREE), self.TC) == []

    def test_no_trump_cross_suit_also_rejected(self):
        tc = ctx(Rank.TWO, None)
        assert find_tractors(pair(S, Rank.THREE) + pair(D, Rank.FOUR), tc) == []

    def test_suited_pair_plus_trump_rank_pair_not_adjacent(self):
        """A♠A♠ + 2♥2♥ in no-trump: spades vs trump, never a tractor.

        This is the case audit §3.1 warns D18 would create without D22.
        """
        tc = ctx(Rank.TWO, None)
        assert not tc.are_tractor_adjacent(c(S, Rank.ACE), c(H, Rank.TWO))
        assert isinstance(
            classify_play(pair(S, Rank.ACE) + pair(H, Rank.TWO), tc), Throw
        )


class TestD22TrumpBehaviorUnchanged:
    """Inside trump every card shares effective suit "trump" — no change."""

    TC = ctx(Rank.TWO, H)

    def test_cross_suit_trump_rank_tractor_still_valid(self):
        """2♠2♠ + 2♥2♥ (tier 2 → tier 3) stays a Tractor."""
        assert self.TC.are_tractor_adjacent(c(S, Rank.TWO), c(H, Rank.TWO))
        result = classify_play(pair(S, Rank.TWO) + pair(H, Rank.TWO), self.TC)
        assert isinstance(result, Tractor)
        assert (result.multiplicity, result.length) == (2, 2)

    def test_trump_suit_top_to_off_suit_trump_rank_still_valid(self):
        """A♥A♥ + 2♠2♠ (tier 1 top → tier 2) stays a Tractor."""
        assert self.TC.are_tractor_adjacent(c(H, Rank.ACE), c(S, Rank.TWO))
        assert isinstance(
            classify_play(pair(H, Rank.ACE) + pair(S, Rank.TWO), self.TC), Tractor
        )

    def test_on_suit_trump_rank_to_small_joker_still_valid(self):
        assert self.TC.are_tractor_adjacent(c(H, Rank.TWO), SJ)
        assert isinstance(classify_play(pair(H, Rank.TWO) + [SJ, SJ], self.TC), Tractor)

    def test_joker_tractor_still_valid(self):
        assert self.TC.are_tractor_adjacent(SJ, BJ)
        assert isinstance(classify_play([SJ, SJ, BJ, BJ], self.TC), Tractor)

    def test_same_suit_tier0_tractor_still_valid(self):
        assert isinstance(
            classify_play(pair(S, Rank.KING) + pair(S, Rank.ACE), self.TC), Tractor
        )

    def test_same_suit_wrap_still_valid(self):
        assert isinstance(
            classify_play(pair(S, Rank.ACE) + pair(S, Rank.THREE), self.TC), Tractor
        )

    def test_tier0_and_tier1_never_adjacent(self):
        """A non-trump suit cannot chain into trump (falls out of D22)."""
        assert not self.TC.are_tractor_adjacent(c(S, Rank.ACE), c(H, Rank.THREE))
        assert not self.TC.are_tractor_adjacent(c(S, Rank.ACE), c(H, Rank.ACE))


class TestD22ClassificationIsOrderIndependent:
    """A cross-suit pair sharing a strength position must not silently displace
    the same-suit pair that actually forms the tractor."""

    TC = ctx(Rank.TWO, H)

    def _signature(self, cards: list[Card]):
        result = classify_play(cards, self.TC)
        assert isinstance(result, Throw)
        return sorted(
            (type(comp).__name__, getattr(comp, "count", None), getattr(comp, "length", None))
            for comp in result.components
        )

    def test_same_position_other_suit_does_not_hide_the_tractor(self):
        """3♦3♦ 4♦4♦ (a diamond tractor) + 3♠3♠, in both card orders."""
        a = pair(D, Rank.THREE) + pair(D, Rank.FOUR) + pair(S, Rank.THREE)
        b = pair(S, Rank.THREE) + pair(D, Rank.THREE) + pair(D, Rank.FOUR)
        assert self._signature(a) == self._signature(b)
        assert ("Tractor", None, 2) in self._signature(a)


# ---------------------------------------------------------------------------
# D18 — adjacency skips EMPTY strength positions, but not occupied ones
# ---------------------------------------------------------------------------

class TestD18SkipsEmptyPositions:
    def test_no_trump_trump_rank_pair_and_sj_pair_form_a_tractor(self):
        """In no-trump tier 3 (trump-rank-of-trump-suit) is empty, so tier 2
        and tier 4 are adjacent.  (D18; was a Throw before.)"""
        tc = ctx(Rank.TWO, None)
        assert tc.are_tractor_adjacent(c(H, Rank.TWO), SJ)
        result = classify_play(pair(H, Rank.TWO) + [SJ, SJ], tc)
        assert isinstance(result, Tractor)
        assert (result.multiplicity, result.length) == (2, 2)

    def test_no_trump_off_suit_trump_rank_pair_and_sj_pair_form_a_tractor(self):
        tc = ctx(Rank.TWO, None)
        assert tc.are_tractor_adjacent(c(S, Rank.TWO), SJ)

    def test_no_trump_sj_bj_still_adjacent(self):
        tc = ctx(Rank.TWO, None)
        assert tc.are_tractor_adjacent(SJ, BJ)

    def test_no_trump_trump_rank_not_adjacent_to_bj(self):
        """Tier 4 (SJ) is occupied and lies strictly between tier 2 and tier 5."""
        tc = ctx(Rank.TWO, None)
        assert not tc.are_tractor_adjacent(c(H, Rank.TWO), BJ)


class TestD18OccupiedPositionsStillBlock:
    TC = ctx(Rank.TWO, H)

    def test_trump_suit_top_not_adjacent_to_on_suit_trump_rank(self):
        """A♥A♥ + 2♥2♥ with ♥ trump: tier 2 (off-suit trump ranks 2♠/2♦/2♣) is
        OCCUPIED and lies strictly between tier 1 top and tier 3, so under D18's
        wording the two are NOT adjacent.

        Diverges from the audit's "presumably intended" aside in §4; the ruled
        wording in docs/RULES.md D18 is authoritative.
        """
        assert not self.TC.are_tractor_adjacent(c(H, Rank.ACE), c(H, Rank.TWO))
        assert isinstance(
            classify_play(pair(H, Rank.ACE) + pair(H, Rank.TWO), self.TC), Throw
        )

    def test_tier0_gap_still_blocks(self):
        """Q♠ and A♠ are not adjacent — K♠ sits between them."""
        assert not self.TC.are_tractor_adjacent(c(S, Rank.QUEEN), c(S, Rank.ACE))

    def test_trump_suit_gap_still_blocks(self):
        assert not self.TC.are_tractor_adjacent(c(H, Rank.QUEEN), c(H, Rank.ACE))

    def test_trump_rank_pair_not_adjacent_to_bj(self):
        """Tier 4 (SJ) lies between tier 3 and tier 5 and is occupied."""
        assert not self.TC.are_tractor_adjacent(c(H, Rank.TWO), BJ)

    def test_trump_suit_top_not_wrapping_to_trump_suit_bottom(self):
        """The circular wrap exists only in tier 0."""
        assert not self.TC.are_tractor_adjacent(c(H, Rank.ACE), c(H, Rank.THREE))

    def test_same_strength_position_is_one_rung_not_two(self):
        """2♠ and 2♦ tie in strength (both tier 2); one rung cannot chain to
        itself, so 2♠2♠ + 2♦2♦ stays a Throw of two pairs (issue #50)."""
        assert not self.TC.are_tractor_adjacent(c(S, Rank.TWO), c(D, Rank.TWO))
        result = classify_play(pair(S, Rank.TWO) + pair(D, Rank.TWO), self.TC)
        assert isinstance(result, Throw)

    def test_same_strength_position_in_no_trump(self):
        tc = ctx(Rank.TWO, None)
        assert not tc.are_tractor_adjacent(c(S, Rank.TWO), c(H, Rank.TWO))


class TestD22SuitScopedPositions:
    """Positions are keyed per effective suit, so an unrelated pair in another
    suit can no longer sit "between" two positions of the tractor's own suit.

    Narrows ``Known limitations`` 1 (audit F3): the same-suit half of the
    limitation is unchanged, the cross-suit half is gone.
    """

    TC = ctx(Rank.TWO, H)

    def test_wrap_survives_an_unrelated_pair_in_another_suit(self):
        cards = pair(S, Rank.ACE) + pair(S, Rank.THREE) + pair(D, Rank.EIGHT)
        result = classify_play(cards, self.TC)
        assert isinstance(result, Throw)
        assert any(isinstance(comp, Tractor) for comp in result.components)

    def test_wrap_still_destroyed_by_a_same_suit_pair(self):
        """Unchanged known limitation: 8♠8♠ really does break the scan."""
        cards = pair(S, Rank.ACE) + pair(S, Rank.THREE) + pair(S, Rank.EIGHT)
        result = classify_play(cards, self.TC)
        assert isinstance(result, Throw)
        assert not any(isinstance(comp, Tractor) for comp in result.components)


class TestOccupiedPositions:
    def test_no_trump_has_no_tier1_or_tier3(self):
        tiers = {t for t, _ in ctx(Rank.TWO, None).occupied_positions()}
        assert tiers == {0, 2, 4, 5}

    def test_suited_trump_has_every_tier(self):
        tiers = {t for t, _ in ctx(Rank.TWO, H).occupied_positions()}
        assert tiers == {0, 1, 2, 3, 4, 5}

    def test_tier0_spans_the_filtered_ranks(self):
        positions = ctx(Rank.TWO, H).occupied_positions()
        assert [p for t, p in positions if t == 0] == list(range(12))
