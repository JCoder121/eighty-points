from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional

from shengji.models.bid import Bid
from shengji.models.card import Card
from shengji.models.friend_declaration import FriendDeclaration
from shengji.models.player import Player
from shengji.models.trump import TrumpContext


class GamePhase(str, Enum):
    """Ordered phases of a game round.

    Allowed transitions (enforced by transition_to()):
      WAITING → DEALING
      DEALING → BIDDING_AFTER_DEAL
      BIDDING_AFTER_DEAL → FRIEND_DECLARATION  (Find Friends mode)
      BIDDING_AFTER_DEAL → BOTTOM_EXCHANGE     (Upgrade mode)
      FRIEND_DECLARATION → BOTTOM_EXCHANGE
      BOTTOM_EXCHANGE → PLAYING
      PLAYING → SCORING
      SCORING → ROUND_OVER
      ROUND_OVER → DEALING                     (next round)
      ROUND_OVER → GAME_OVER
    """

    WAITING = "waiting"
    DEALING = "dealing"
    BIDDING_AFTER_DEAL = "bidding_after_deal"
    BOTTOM_EXCHANGE = "bottom_exchange"
    FRIEND_DECLARATION = "friend_declaration"
    PLAYING = "playing"
    SCORING = "scoring"
    ROUND_OVER = "round_over"
    GAME_OVER = "game_over"


_VALID_TRANSITIONS: dict[GamePhase, set[GamePhase]] = {
    GamePhase.WAITING: {GamePhase.DEALING},
    GamePhase.DEALING: {GamePhase.BIDDING_AFTER_DEAL},
    GamePhase.BIDDING_AFTER_DEAL: {GamePhase.FRIEND_DECLARATION, GamePhase.BOTTOM_EXCHANGE, GamePhase.DEALING},  # re-deal on no bid
    GamePhase.FRIEND_DECLARATION: {GamePhase.BOTTOM_EXCHANGE},
    GamePhase.BOTTOM_EXCHANGE: {GamePhase.PLAYING},
    GamePhase.PLAYING: {GamePhase.SCORING},
    GamePhase.SCORING: {GamePhase.ROUND_OVER},
    GamePhase.ROUND_OVER: {GamePhase.DEALING, GamePhase.GAME_OVER},
    GamePhase.GAME_OVER: set(),
}


@dataclass
class GameState:
    """Full, authoritative state of one game session.

    The engine mutates this object; the network layer serialises it.
    Never send the raw GameState over the wire — use to_player_view() or
    to_superuser_view() instead.
    """

    # Core setup
    players: list[Player] = field(default_factory=list)
    mode: Optional[Literal["upgrade", "find_friends"]] = None
    phase: GamePhase = GamePhase.WAITING

    # Trump
    trump_context: Optional[TrumpContext] = None

    # Cards
    bottom_deck: list[Card] = field(default_factory=list)
    draw_pile: list[Card] = field(default_factory=list)
    cards_dealt_count: int = 0

    # Trick tracking
    current_trick: list[tuple[str, list[Card]]] = field(default_factory=list)
    tricks_won: dict[str, list[list[Card]]] = field(default_factory=dict)

    # Turn / leader tracking
    current_leader_id: str = ""
    round_leader_id: str = ""
    current_turn_id: str = ""

    # Scoring
    attacking_points: int = 0
    round_number: int = 1
    trick_number: int = 1

    # Bidding history
    bids: list[Bid] = field(default_factory=list)

    # Find Friends only
    friend_declarations: list[FriendDeclaration] = field(default_factory=list)
    revealed_friends: set[str] = field(default_factory=set)

    # ------------------------------------------------------------------
    # Phase management
    # ------------------------------------------------------------------

    def transition_to(self, new_phase: GamePhase) -> None:
        """Transition to *new_phase*, raising ValueError on illegal moves."""
        allowed = _VALID_TRANSITIONS.get(self.phase, set())
        if new_phase not in allowed:
            raise ValueError(
                f"Cannot transition from {self.phase.value!r} to {new_phase.value!r}. "
                f"Allowed: {[p.value for p in allowed]}"
            )
        self.phase = new_phase

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------

    def to_player_view(self, player_id: str) -> dict:
        """Serialise state for a specific player.

        The player sees their own hand in full; other players' hands are
        hidden (only hand_size is exposed).  The bottom deck is hidden
        unless the player is the round leader during BOTTOM_EXCHANGE.
        """
        show_bottom = (
            self.phase == GamePhase.BOTTOM_EXCHANGE
            and player_id == self.round_leader_id
        )

        players_view = []
        for p in self.players:
            is_self = p.id == player_id
            players_view.append(p.to_json(include_hand=is_self))

        return {
            "phase": self.phase.value,
            "mode": self.mode,
            "round_number": self.round_number,
            "trick_number": self.trick_number,
            "trump_context": _trump_context_json(self.trump_context),
            "players": players_view,
            "current_trick": _trick_json(self.current_trick),
            "current_leader_id": self.current_leader_id,
            "current_turn_id": self.current_turn_id,
            "attacking_points": self.attacking_points,
            "bids": [b.to_json() for b in self.bids],
            "bottom_deck": (
                [c.to_json() for c in self.bottom_deck] if show_bottom else None
            ),
            "cards_dealt_count": self.cards_dealt_count,
            "revealed_friends": list(self.revealed_friends),
            "round_leader_id": self.round_leader_id,
            "friend_declarations": [fd.to_json() for fd in self.friend_declarations],
        }

    def to_superuser_view(self) -> dict:
        """Serialise full state — all hands, bottom deck, draw pile visible."""
        return {
            "phase": self.phase.value,
            "mode": self.mode,
            "round_number": self.round_number,
            "trick_number": self.trick_number,
            "trump_context": _trump_context_json(self.trump_context),
            "players": [p.to_json(include_hand=True) for p in self.players],
            "current_trick": _trick_json(self.current_trick),
            "current_leader_id": self.current_leader_id,
            "round_leader_id": self.round_leader_id,
            "current_turn_id": self.current_turn_id,
            "attacking_points": self.attacking_points,
            "bids": [b.to_json() for b in self.bids],
            "bottom_deck": [c.to_json() for c in self.bottom_deck],
            "draw_pile_size": len(self.draw_pile),
            "cards_dealt_count": self.cards_dealt_count,
            "tricks_won": {
                pid: [[c.to_json() for c in trick] for trick in tricks]
                for pid, tricks in self.tricks_won.items()
            },
            "friend_declarations": [fd.to_json() for fd in self.friend_declarations],
            "revealed_friends": list(self.revealed_friends),
        }


# ------------------------------------------------------------------
# Private serialisation helpers
# ------------------------------------------------------------------

def _trump_context_json(ctx: Optional[TrumpContext]) -> Optional[dict]:
    if ctx is None:
        return None
    return {
        "trump_rank": ctx.trump_rank.value,
        "trump_suit": ctx.trump_suit.value if ctx.trump_suit else None,
    }


def _trick_json(trick: list[tuple[str, list[Card]]]) -> list[dict]:
    return [
        {"player_id": pid, "cards": [c.to_json() for c in cards]}
        for pid, cards in trick
    ]
