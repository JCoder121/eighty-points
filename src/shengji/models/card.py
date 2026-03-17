from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Suit(str, Enum):
    SPADES = "spades"
    HEARTS = "hearts"
    DIAMONDS = "diamonds"
    CLUBS = "clubs"
    JOKER = "joker"  # Used only for SmallJoker / BigJoker


class Rank(str, Enum):
    TWO = "2"
    THREE = "3"
    FOUR = "4"
    FIVE = "5"
    SIX = "6"
    SEVEN = "7"
    EIGHT = "8"
    NINE = "9"
    TEN = "10"
    JACK = "J"
    QUEEN = "Q"
    KING = "K"
    ACE = "A"
    SMALL_JOKER = "SJ"
    BIG_JOKER = "BJ"


# Ordered rank sequence used for progression and adjacency (jokers excluded).
RANK_ORDER: list[Rank] = [
    Rank.TWO,
    Rank.THREE,
    Rank.FOUR,
    Rank.FIVE,
    Rank.SIX,
    Rank.SEVEN,
    Rank.EIGHT,
    Rank.NINE,
    Rank.TEN,
    Rank.JACK,
    Rank.QUEEN,
    Rank.KING,
    Rank.ACE,
]

# Suits that appear in a standard deck (joker suit is not a "suited" suit).
SUITED_SUITS: list[Suit] = [Suit.SPADES, Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS]

# Point values per card face.
_POINT_VALUES: dict[Rank, int] = {
    Rank.FIVE: 5,
    Rank.TEN: 10,
    Rank.KING: 10,
}


@dataclass(frozen=True)
class Card:
    suit: Suit
    rank: Rank

    def __post_init__(self) -> None:
        if self.suit == Suit.JOKER and self.rank not in (Rank.SMALL_JOKER, Rank.BIG_JOKER):
            raise ValueError(f"Joker suit requires a joker rank, got {self.rank}")
        if self.suit != Suit.JOKER and self.rank in (Rank.SMALL_JOKER, Rank.BIG_JOKER):
            raise ValueError(f"Joker rank requires joker suit, got {self.suit}")

    @property
    def point_value(self) -> int:
        return _POINT_VALUES.get(self.rank, 0)

    def __repr__(self) -> str:
        if self.suit == Suit.JOKER:
            return self.rank.value
        suit_symbol = {"spades": "♠", "hearts": "♥", "diamonds": "♦", "clubs": "♣"}[self.suit.value]
        return f"{self.rank.value}{suit_symbol}"

    def to_json(self) -> dict:
        return {"suit": self.suit.value, "rank": self.rank.value}

    @classmethod
    def from_json(cls, data: dict) -> Card:
        return cls(suit=Suit(data["suit"]), rank=Rank(data["rank"]))
