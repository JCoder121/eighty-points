"""UpgradeStrategy — fixed-team (升级) mode strategy.

Teams are determined by seating: seats 0,2 form one team; seats 1,3 form
the other.  The bid winner (round leader) is always on the defending team.

If the defending team wins a round, they continue defending and the leader
rotates counter-clockwise among defenders.  If the attacking team wins, they
swap to become the new defending team and the leader rotates among them.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from shengji.modes.base import ModeStrategy

if TYPE_CHECKING:
    from shengji.models.card import Card
    from shengji.models.game_state import GameState


class UpgradeStrategy(ModeStrategy):
    """Upgrade (升级) mode: fixed seat-based teams, no friend declarations."""

    # ------------------------------------------------------------------
    # Team assignment
    # ------------------------------------------------------------------

    def assign_teams(self, state: "GameState") -> None:
        """Set defending / attacking roles based on round leader's seat.

        Seats 0 and 2 are partners; seats 1 and 3 are partners.
        The round leader's seat parity determines which pair defends.
        """
        players = state.players
        leader_idx = next(
            i for i, p in enumerate(players) if p.id == state.round_leader_id
        )
        # leader parity: 0 → seats 0,2 defend; 1 → seats 1,3 defend
        leader_parity = leader_idx % 2
        for i, p in enumerate(players):
            p.is_defending = (i % 2 == leader_parity)
            p.team = "defending" if p.is_defending else "attacking"

    # ------------------------------------------------------------------
    # Friend declarations — not applicable in Upgrade mode
    # ------------------------------------------------------------------

    def needs_friend_declaration(self) -> bool:
        return False

    def validate_friend_declaration(
        self, state: "GameState", declarations: list
    ) -> None:
        raise ValueError("Friend declarations are not used in Upgrade mode.")

    def resolve_friend(
        self, state: "GameState", player_id: str, card: "Card"
    ) -> None:
        pass  # no-op

    # ------------------------------------------------------------------
    # Round end / leadership rotation
    # ------------------------------------------------------------------

    def on_round_end(self, state: "GameState", winner_team: str) -> None:
        """Swap defending / attacking roles if the attacking team won.

        Called *before* get_next_leader() so that is_defending reflects the
        *next* round's team assignments when get_next_leader() runs.
        """
        if winner_team == "attacking":
            # Attackers take over as defenders for the next round.
            for p in state.players:
                p.is_defending = not p.is_defending
                p.team = "defending" if p.is_defending else "attacking"
        # If defenders won, team roles stay unchanged.

    def get_next_leader(self, state: "GameState", winner_team: str) -> str:
        """Return the next counter-clockwise defender from the current leader.

        After on_round_end() has run, is_defending == True always marks the
        *next* round's defending team (i.e. the winning team).  We rotate the
        leader position to the next defending player counter-clockwise from the
        current round leader.
        """
        players = state.players
        winning_ids = {p.id for p in players if p.is_defending}

        leader_idx = next(
            i for i, p in enumerate(players) if p.id == state.round_leader_id
        )
        n = len(players)
        for step in range(1, n + 1):
            candidate_idx = (leader_idx + step) % n
            if players[candidate_idx].id in winning_ids:
                return players[candidate_idx].id

        # Should never be reached in a valid 4-player game.
        return state.round_leader_id
