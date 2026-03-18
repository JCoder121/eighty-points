"""ModeStrategy — abstract base class for Upgrade vs. Find Friends behaviour.

The engine delegates all mode-specific logic through this interface so that
the core game loop stays free of ``if mode == "find_friends"`` branches.

Concrete subclasses
-------------------
- UpgradeStrategy      (src/shengji/modes/upgrade.py)
- FindFriendsStrategy  (src/shengji/modes/find_friends.py)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shengji.models.card import Card
    from shengji.models.game_state import GameState


class ModeStrategy(ABC):
    """Abstract interface for game-mode-specific behaviour."""

    # ------------------------------------------------------------------
    # Team assignment
    # ------------------------------------------------------------------

    @abstractmethod
    def assign_teams(self, state: "GameState") -> None:
        """Set ``player.is_defending`` and ``player.team`` for every player.

        Called once per round, immediately after the bid winner is determined
        (i.e. after ``close_bidding()`` sets ``state.round_leader_id``).
        The round leader's identity tells the strategy which team defends.
        """

    def get_attacker_ids(self, state: "GameState") -> set[str]:
        """Return the set of player IDs on the attacking team.

        Default implementation reads the ``is_defending`` flags set by
        ``assign_teams()``.  Concrete subclasses may override if needed.
        """
        return {p.id for p in state.players if not p.is_defending}

    # ------------------------------------------------------------------
    # Friend declarations (Find Friends only)
    # ------------------------------------------------------------------

    @abstractmethod
    def needs_friend_declaration(self) -> bool:
        """Return True iff this mode requires a friend-declaration phase."""

    @abstractmethod
    def validate_friend_declaration(
        self, state: "GameState", declarations: list
    ) -> None:
        """Raise ValueError if *declarations* are illegal for this mode/state."""

    @abstractmethod
    def resolve_friend(
        self, state: "GameState", player_id: str, card: "Card"
    ) -> None:
        """Called for every card played; trigger friend reveal if applicable.

        For Find Friends: check whether *card* matches any pending declaration
        at the correct ordinal.  If so, mark *player_id* as a friend (set
        ``is_defending=True`` and update ``revealed_friends``).

        For Upgrade: this is a no-op.
        """

    # ------------------------------------------------------------------
    # Round end / leadership rotation
    # ------------------------------------------------------------------

    @abstractmethod
    def on_round_end(self, state: "GameState", winner_team: str) -> None:
        """Update team roles and defending status for the next round.

        Called by ``end_round()`` *before* ``get_next_leader()``.

        Parameters
        ----------
        winner_team:
            ``"attacking"`` or ``"defending"``.  When ``"attacking"`` and
            ``steps == 0`` the attackers take over as defenders at the same
            rank; when ``steps > 0`` they advance ranks and also take over.
        """

    @abstractmethod
    def get_next_leader(self, state: "GameState", winner_team: str) -> str:
        """Return the player_id who will be the round leader next round.

        Called *after* ``on_round_end()`` has updated team roles.
        """
