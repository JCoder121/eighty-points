from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from shengji.models.card import Card


@dataclass
class FriendDeclaration:
    """Declares a "friend" card in Find Friends mode.

    card                — the specific card being declared (e.g. A♠)
    ordinal             — which occurrence triggers the friendship (1st, 2nd, …
                          person to play that card joins the declaring team)
    resolved_player_id  — set once the friend has actually played the card;
                          None until then (friend identity is hidden)
    """

    card: Card
    ordinal: int
    resolved_player_id: Optional[str] = None

    @property
    def is_resolved(self) -> bool:
        return self.resolved_player_id is not None

    def to_json(self) -> dict:
        return {
            "card": self.card.to_json(),
            "ordinal": self.ordinal,
            "resolved_player_id": self.resolved_player_id,
        }
