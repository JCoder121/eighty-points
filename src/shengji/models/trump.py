from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from shengji.models.card import Card, Rank, Suit, RANK_ORDER


@dataclass(frozen=True)
class TrumpContext:
    """Captures the trump rank and suit for a single round.

    trump_suit=None means no-trump: trump-rank cards are always trump for
    trick-following (effective_suit returns "trump") and are ranked above all
    suited cards in card_order.

    Card ordering tiers (higher tier = stronger card):
      0 — non-trump-suit, non-trump-rank suited cards
      1 — trump-suit non-trump-rank cards  (only when trump_suit is set)
      2 — trump-rank cards of off-suit     (all equal to each other)
      3 — trump-rank card of trump suit    (only when trump_suit is set)
      4 — Small Joker
      5 — Big Joker

    Adjacency for tractor formation:
      • The two cards must share an effective suit (D22).  Every trump card —
        trump suit, trump rank of any suit, jokers — shares the suit "trump",
        so the trump hierarchy still chains across tiers; two non-trump suits
        never do.
      • Otherwise two cards are adjacent iff no OCCUPIED strength position lies
        strictly between their keys (D18), where a position counts as occupied
        when some card actually maps to it in this context.  Empty rungs are
        skipped: in no-trump, tiers 1 and 3 do not exist, so a trump-rank pair
        and a Small-Joker pair are adjacent.  Occupied rungs still block: with
        a trump suit, tier 2 (the off-suit trump-rank cards) sits between the
        top trump-suit card and the on-suit trump-rank card, so A♥ and 2♥ are
        NOT adjacent when ♥ is trump.
      • Tier 0 keeps its circular wrap (position 0 and position n-1 are
        adjacent within one suit) — so when trump rank=2, Ace and 3 are
        adjacent in a non-trump suit.  There is no wrap inside tier 1.
      • Tier 0 ↔ tier 1 is therefore never adjacent (non-trump suits cannot
        form tractors with trump) — it falls out of the shared-suit rule.
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

    def occupied_positions(self) -> list[tuple[int, int]]:
        """Every (tier, rank_pos) key some card maps to in this context, ascending.

        Tiers 1 and 3 exist only when a trump suit is declared; in no-trump they
        are empty rungs that adjacency skips over (D18).
        """
        n = len(self._filtered_ranks())
        positions: list[tuple[int, int]] = [(0, p) for p in range(n)]
        if self.trump_suit is not None:
            positions.extend((1, p) for p in range(n))
        positions.append((2, 0))
        if self.trump_suit is not None:
            positions.append((3, 0))
        positions.extend([(4, 0), (5, 0)])
        return sorted(positions)

    def effective_suit(self, card: Card) -> str:
        """Return the suit string used for trick-following.

        Returns "trump" for jokers, trump-rank cards (regardless of mode),
        and trump-suit cards.  Trump-rank cards are always trump — even in
        no-trump mode — because they must follow trump leads and are ranked
        in the trump hierarchy by card_order.
        """
        if card.suit == Suit.JOKER:
            return "trump"
        if card.rank == self.trump_rank:
            return "trump"
        if self.trump_suit is not None and card.suit == self.trump_suit:
            return "trump"
        return card.suit.value

    def are_tractor_adjacent(self, card1: Card, card2: Card) -> bool:
        """Return True if card1 and card2 are at adjacent positions for tractor formation.

        See class docstring for the adjacency rules.
        """
        # D22: adjacency is suit-aware.  Two pairs in different non-trump suits
        # at consecutive tier-0 positions are a Throw, not a Tractor.
        if self.effective_suit(card1) != self.effective_suit(card2):
            return False

        o1 = self.card_order(card1)
        o2 = self.card_order(card2)
        # Normalise so o1 <= o2
        if o1 > o2:
            o1, o2 = o2, o1
        # Cards at the same strength position are one rung, not two.
        if o1 == o2:
            return False

        t1, p1 = o1
        t2, p2 = o2

        n = len(self._filtered_ranks())  # 12

        # The circular wrap survives D18 as an explicit tier-0 rule: the
        # positions between A and 3 the long way round are all occupied.
        if t1 == 0 and t2 == 0 and p1 == 0 and p2 == n - 1:
            return True

        # D18: adjacent iff no occupied strength position lies strictly between.
        return not any(o1 < pos < o2 for pos in self.occupied_positions())
