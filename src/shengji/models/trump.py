from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from shengji.models.card import Card, Rank, Suit, RANK_ORDER


@dataclass(frozen=True)
class TrumpContext:
    """Captures the trump rank and suit for a single round.

    trump_suit=None means no-trump: trump-rank cards keep their own suit for
    trick-following purposes, but are still ranked above all suited cards in
    card_order.

    Card ordering tiers (higher tier = stronger card):
      0 — non-trump-suit, non-trump-rank suited cards
      1 — trump-suit non-trump-rank cards  (only when trump_suit is set)
      2 — trump-rank cards of off-suit     (all equal to each other)
      3 — trump-rank card of trump suit    (only when trump_suit is set)
      4 — Small Joker
      5 — Big Joker

    Adjacency for tractor formation:
      • Within tier 0: consecutive rank positions in the filtered list, PLUS
        circular wrap (position 0 and position n-1 are adjacent).  This means
        e.g. when trump rank=2, Ace and 3 are adjacent in non-trump suits.
      • Within tier 1: consecutive rank positions only (no circular wrap).
      • Tier 1 top ↔ tier 2: adjacent (highest trump-suit card is adjacent to
        off-suit trump-rank cards in the trump hierarchy).
      • Tier 2 ↔ tier 3, tier 3 ↔ tier 4, tier 4 ↔ tier 5: adjacent.
      • Tier 0 ↔ tier 1: NOT adjacent (non-trump suits cannot form tractors
        with trump-suit cards).
    """

    trump_rank: Rank
    trump_suit: Optional[Suit] = None

    def _filtered_ranks(self) -> list[Rank]:
        """RANK_ORDER with trump_rank removed (12 ranks)."""
        return [r for r in RANK_ORDER if r != self.trump_rank]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def card_order(self, card: Card) -> tuple[int, int]:
        """Return a sortable (tier, rank_pos) key.

        Higher tuple → stronger card.  Cards at the same tuple value are
        interchangeable for trick-winning purposes.
        """
        if card.rank == Rank.BIG_JOKER:
            return (5, 0)
        if card.rank == Rank.SMALL_JOKER:
            return (4, 0)
        if card.rank == self.trump_rank:
            if self.trump_suit is not None and card.suit == self.trump_suit:
                return (3, 0)
            return (2, 0)
        # Ordinary suited card (not joker, not trump rank)
        filtered = self._filtered_ranks()
        rank_pos = filtered.index(card.rank)
        if self.trump_suit is not None and card.suit == self.trump_suit:
            return (1, rank_pos)
        return (0, rank_pos)

    def effective_suit(self, card: Card) -> str:
        """Return the suit string used for trick-following.

        Returns "trump" for jokers, trump-rank cards (when trump_suit is set),
        and trump-suit cards.  In no-trump mode (trump_suit=None), trump-rank
        cards retain their own suit value; only jokers return "trump".
        """
        if card.suit == Suit.JOKER:
            return "trump"
        if card.rank == self.trump_rank:
            if self.trump_suit is None:
                return card.suit.value  # no-trump: keep own suit
            return "trump"
        if self.trump_suit is not None and card.suit == self.trump_suit:
            return "trump"
        return card.suit.value

    def are_tractor_adjacent(self, card1: Card, card2: Card) -> bool:
        """Return True if card1 and card2 are at adjacent positions for tractor formation.

        See class docstring for the adjacency rules.
        """
        o1 = self.card_order(card1)
        o2 = self.card_order(card2)
        # Normalise so o1 <= o2
        if o1 > o2:
            o1, o2 = o2, o1
        t1, p1 = o1
        t2, p2 = o2

        n = len(self._filtered_ranks())  # 12

        if t1 == t2:
            # Consecutive positions within the same tier
            if p2 == p1 + 1:
                return True
            # Circular wrap only for tier 0 (non-trump suits)
            if t1 == 0 and p1 == 0 and p2 == n - 1:
                return True
            return False

        if t2 == t1 + 1:
            # Tier 1 (trump suit, highest rank) → tier 2 (off-suit trump rank)
            if t1 == 1 and p1 == n - 1 and p2 == 0:
                return True
            # Tier 2/3/4 each have only one rank position (pos=0); they are
            # adjacent to the next tier.
            if t1 >= 2 and p1 == 0 and p2 == 0:
                return True

        return False
