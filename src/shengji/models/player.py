from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from shengji.models.card import Card, Rank, RANK_ORDER


@dataclass
class Player:
    """Represents one player at the table.

    Rank progression sequence is the 13-rank list TWO..ACE.  A player can never
    advance past ACE.  The game ends when a player successfully defends while
    at rank ACE (handled by the engine / mode strategy).
    """

    id: str
    name: str
    hand: list[Card] = field(default_factory=list)
    rank: Rank = Rank.TWO
    is_defending: bool = False
    team: Optional[str] = None

    # ------------------------------------------------------------------
    # Rank progression
    # ------------------------------------------------------------------

    def advance_rank(self, steps: int) -> None:
        """Move this player forward *steps* positions in RANK_ORDER.

        Clamps at ACE — a +3 that would overshoot ACE just lands on ACE.
        steps must be >= 0.
        """
        if steps < 0:
            raise ValueError(f"steps must be non-negative, got {steps}")
        if steps == 0:
            return
        current_index = RANK_ORDER.index(self.rank)
        new_index = min(current_index + steps, len(RANK_ORDER) - 1)
        self.rank = RANK_ORDER[new_index]

    @property
    def is_at_max_rank(self) -> bool:
        """True when the player is at ACE (the highest rank)."""
        return self.rank == Rank.ACE

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_json(self, include_hand: bool = True) -> dict:
        result: dict = {
            "id": self.id,
            "name": self.name,
            "rank": self.rank.value,
            "is_defending": self.is_defending,
            "team": self.team,
            "hand_size": len(self.hand),
        }
        if include_hand:
            result["hand"] = [c.to_json() for c in self.hand]
        return result
