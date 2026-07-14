from __future__ import annotations

import random

from shengji.models.card import Card, Rank, Suit, RANK_ORDER, SUITED_SUITS

# Fixed game constants — this game always has exactly 4 players and 2 decks.
NUM_PLAYERS: int = 4
NUM_DECKS: int = 2
BOTTOM_SIZE: int = 8  # cards set aside before dealing; leader exchanges these
TOTAL_CARDS: int = 108  # 54 cards per deck × 2 decks
HAND_SIZE: int = (TOTAL_CARDS - BOTTOM_SIZE) // NUM_PLAYERS  # 25 cards per hand


def _make_single_deck() -> list[Card]:
    """Return the 54 cards in one standard Shengji deck."""
    cards: list[Card] = []
    for suit in SUITED_SUITS:
        for rank in RANK_ORDER:
            cards.append(Card(suit=suit, rank=rank))
    cards.append(Card(suit=Suit.JOKER, rank=Rank.SMALL_JOKER))
    cards.append(Card(suit=Suit.JOKER, rank=Rank.BIG_JOKER))
    return cards


class Deck:
    """Two standard Shengji decks shuffled together (108 cards).

    rng: optional random.Random for deterministic shuffles (seeded replays,
    tests).  When None, the module-level random is used (production default).
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self._cards: list[Card] = _make_single_deck() + _make_single_deck()
        self._rng = rng

    def shuffle(self) -> None:
        """Randomise card order in place."""
        (self._rng or random).shuffle(self._cards)

    def prepare_deal(self) -> tuple[list[Card], list[Card]]:
        """Return (draw_pile, bottom_deck) after shuffling.

        draw_pile: 100 cards ordered for one-at-a-time dealing (index 0 dealt first).
        bottom_deck: the last 8 cards, set aside for the round leader to exchange.

        The Deck is consumed by this call — do not call prepare_deal twice on the
        same instance.  Create a new Deck for each round.
        """
        self.shuffle()
        bottom_deck = self._cards[-BOTTOM_SIZE:]
        draw_pile = self._cards[: TOTAL_CARDS - BOTTOM_SIZE]
        return draw_pile, bottom_deck
