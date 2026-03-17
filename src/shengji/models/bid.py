from __future__ import annotations

from dataclasses import dataclass, field

from shengji.models.card import Card
from shengji.models.trump import TrumpContext


@dataclass
class Bid:
    """Records a single bid placed during the dealing phase.

    player_id       — who placed the bid
    cards           — the card(s) shown to support the bid (1 or 2 cards)
    resulting_trump — the TrumpContext that would become active if this bid wins
    """

    player_id: str
    cards: list[Card]
    resulting_trump: TrumpContext

    def to_json(self) -> dict:
        return {
            "player_id": self.player_id,
            "cards": [c.to_json() for c in self.cards],
            "resulting_trump": {
                "trump_rank": self.resulting_trump.trump_rank.value,
                "trump_suit": (
                    self.resulting_trump.trump_suit.value
                    if self.resulting_trump.trump_suit
                    else None
                ),
            },
        }
