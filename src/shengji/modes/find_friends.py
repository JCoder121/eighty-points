"""FindFriendsStrategy — fluid-team (找朋友) mode strategy.

The round leader defends alone at the start of each round.  Before play
begins, the leader declares one (or more) "friend" cards — the first player
to play the n-th occurrence of that card joins the defending team.  Teams
are fully reassigned each round, so leadership and team composition can
change dramatically from round to round.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from shengji.models.card import Suit
from shengji.modes.base import ModeStrategy

if TYPE_CHECKING:
    from shengji.models.card import Card
    from shengji.models.game_state import GameState


class FindFriendsStrategy(ModeStrategy):
    """Find Friends (找朋友) mode: fluid teams re-assigned each round."""

    def __init__(self) -> None:
        # Tracks how many times each (suit, rank) card has been played this round.
        # Used to match against declaration ordinals.
        self._play_counts: dict[tuple, int] = {}

    # ------------------------------------------------------------------
    # Team assignment
    # ------------------------------------------------------------------

    def assign_teams(self, state: "GameState") -> None:
        """Leader defends alone; all other players start as attackers.

        Friends are revealed incrementally via resolve_friend() as play
        progresses.  Play-count tracking is also reset here at round start.
        """
        self._play_counts.clear()
        for p in state.players:
            p.is_defending = (p.id == state.round_leader_id)
            p.team = "defending" if p.is_defending else "attacking"

    # ------------------------------------------------------------------
    # Friend declarations
    # ------------------------------------------------------------------

    def needs_friend_declaration(self) -> bool:
        return True

    def validate_friend_declaration(
        self, state: "GameState", declarations: list
    ) -> None:
        """Raise ValueError if *declarations* violate Find Friends rules.

        Rules enforced:
          - Exactly (n_players // 2 - 1) declarations (→ 1 for 4-player game).
          - Each declared card must not be a trump-rank card.
          - Each declared card must not be a joker.

        Note: the leader is allowed to declare a card they hold themselves —
        this is legal, and the leader may end up as their own "friend" (1v3).
        """
        n_players = len(state.players)
        expected = n_players // 2 - 1  # 1 for 4-player game
        if len(declarations) != expected:
            raise ValueError(
                f"Must declare exactly {expected} friend(s) for {n_players} players; "
                f"got {len(declarations)}."
            )

        ctx = state.trump_context
        trump_rank = ctx.trump_rank if ctx is not None else None

        trump_suit = ctx.trump_suit if ctx is not None else None

        for decl in declarations:
            card = decl.card
            if card.suit == Suit.JOKER:
                raise ValueError(
                    f"Cannot declare a joker ({card}) as a friend card."
                )
            if trump_rank is not None and card.rank == trump_rank:
                raise ValueError(
                    f"Cannot declare the trump-rank card ({card}) as a friend card."
                )
            if trump_suit is not None and card.suit == trump_suit:
                raise ValueError(
                    f"Cannot declare a trump-suit card ({card}) as a friend card."
                )

    def resolve_friend(
        self, state: "GameState", player_id: str, card: "Card"
    ) -> None:
        """Check whether *card* triggers a pending friend declaration.

        Increments the per-card play-count and reveals the friend if the
        count matches the declaration's ordinal.  If the round leader plays
        their own declared card, they become their own friend (1v3).
        """
        # Quick exit if this card matches no declaration at all.
        has_matching_decl = any(
            d.card.suit == card.suit and d.card.rank == card.rank
            for d in state.friend_declarations
        )
        if not has_matching_decl:
            return

        key = (card.suit, card.rank)
        self._play_counts[key] = self._play_counts.get(key, 0) + 1
        count = self._play_counts[key]

        # Check whether this play triggers any unresolved declaration.
        for decl in state.friend_declarations:
            if decl.is_resolved:
                continue
            if decl.card.suit == card.suit and decl.card.rank == card.rank:
                if decl.ordinal == count:
                    decl.resolved_player_id = player_id
                    state.revealed_friends.add(player_id)
                    player_obj = next(
                        p for p in state.players if p.id == player_id
                    )
                    player_obj.is_defending = True
                    player_obj.team = "defending"
                    break  # one friend reveal per card play

    # ------------------------------------------------------------------
    # Round end / leadership rotation
    # ------------------------------------------------------------------

    def on_round_end(self, state: "GameState", winner_team: str) -> None:
        """No-op: Find Friends teams are fully reset by assign_teams() next round."""

    def get_next_leader(self, state: "GameState", winner_team: str) -> str:
        """Return the counter-clockwise next player on the winning team.

        Uses the *end-of-round* is_defending flags (which include any friends
        revealed during play) to identify the winning team.
        """
        players = state.players
        if winner_team == "defending":
            winning_ids = {p.id for p in players if p.is_defending}
        else:
            winning_ids = {p.id for p in players if not p.is_defending}

        leader_idx = next(
            i for i, p in enumerate(players) if p.id == state.round_leader_id
        )
        n = len(players)
        for step in range(1, n + 1):
            candidate_idx = (leader_idx + step) % n
            if players[candidate_idx].id in winning_ids:
                return players[candidate_idx].id

        return state.round_leader_id  # fallback
