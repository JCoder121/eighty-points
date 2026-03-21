"""Room management for the Shengji multiplayer server.

A ``Room`` holds all live state for one game session: the GameState, the
engine (created when dealing begins), and the active WebSocket connections.

``RoomManager`` is the in-memory registry of active rooms.  A single
process-level instance is created in ``app.py``; tests may create their own
isolated instances.
"""
from __future__ import annotations

import random
import string
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from shengji.models.game_state import GamePhase, GameState
from shengji.models.player import Player

if TYPE_CHECKING:
    from fastapi import WebSocket
    from shengji.engine.engine import GameEngine

# ── Constants ────────────────────────────────────────────────────────────────

NUM_PLAYERS = 4

_ROOM_ID_CHARS = string.ascii_uppercase + string.digits  # e.g. "AB3X7Q"
_PLAYER_ID_CHARS = string.ascii_lowercase + string.digits


# ── Room dataclass ───────────────────────────────────────────────────────────

@dataclass
class Room:
    """All live state for one game session.

    Attributes
    ----------
    room_id:
        6-character alphanumeric code shared with players.
    game_master_id:
        player_id of the first player to create the room.  Only they can
        select the game mode and enable superuser features.
    game_state:
        The mutable GameState driven by the engine.
    engine:
        Created when dealing begins (None before the first deal starts).
    connections:
        Live WebSocket per player.  Not every player may be connected at all
        times (though in practice the room is destroyed on first disconnect).
    superuser_enabled:
        True once the game master has called POST /superuser/enable/{room_id}.
    passed_in_bidding:
        Set of player_ids that have passed during the current BIDDING_AFTER_DEAL
        window.  Cleared whenever a successful bid is placed (so all must pass
        again to close bidding after the last raise).
    players_who_passed:
        Set of player_ids that have passed at any point this bidding round.
        Never cleared on a new bid — only on a new deal.  Used to permanently
        block re-bids from players who already passed.
    """

    room_id: str
    game_master_id: str
    game_state: GameState
    engine: "GameEngine | None" = None
    connections: dict[str, "WebSocket"] = field(default_factory=dict)
    superuser_enabled: bool = False
    passed_in_bidding: set[str] = field(default_factory=set)
    players_who_passed: set[str] = field(default_factory=set)
    ready_for_next_round: set[str] = field(default_factory=set)


# ── RoomManager ──────────────────────────────────────────────────────────────

class RoomManager:
    """In-memory registry of active rooms.

    Create one shared instance per process (done in ``app.py``).
    Tests should create their own isolated instances.
    """

    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}

    # ── Public API ────────────────────────────────────────────────────────

    def create_room(self, player_name: str) -> tuple[str, str]:
        """Create a new room with *player_name* as game master.

        Returns
        -------
        (room_id, player_id)
        """
        room_id = self._gen_room_id()
        player_id = self._gen_player_id()

        player = Player(id=player_id, name=player_name)
        state = GameState(
            players=[player],
            round_leader_id=player_id,
        )
        room = Room(room_id=room_id, game_master_id=player_id, game_state=state)
        self._rooms[room_id] = room
        return room_id, player_id

    def join_room(self, room_id: str, player_name: str) -> str:
        """Add *player_name* to an existing room.

        Returns
        -------
        player_id
            The newly created player's ID.

        Raises
        ------
        ValueError
            If the room does not exist, is full, or the game has started.
        """
        room = self.get_room(room_id)
        if room is None:
            raise ValueError(f"Room {room_id!r} not found.")
        if len(room.game_state.players) >= NUM_PLAYERS:
            raise ValueError("Room is full (4 players maximum).")
        if room.game_state.phase != GamePhase.WAITING:
            raise ValueError("Game has already started — cannot join mid-game.")

        player_id = self._gen_player_id()
        player = Player(id=player_id, name=player_name)
        room.game_state.players.append(player)
        return player_id

    def get_room(self, room_id: str) -> Room | None:
        """Return the Room with *room_id*, or None if it does not exist."""
        return self._rooms.get(room_id)

    def remove_room(self, room_id: str) -> None:
        """Delete a room from the registry (called on game-over or abort)."""
        self._rooms.pop(room_id, None)

    def all_room_ids(self) -> list[str]:
        """Return all active room IDs."""
        return list(self._rooms.keys())

    # ── Internal helpers ──────────────────────────────────────────────────

    def _gen_room_id(self) -> str:
        """Generate a unique 6-character room code."""
        while True:
            code = "".join(random.choices(_ROOM_ID_CHARS, k=6))
            if code not in self._rooms:
                return code

    @staticmethod
    def _gen_player_id() -> str:
        """Generate a random 12-character player ID."""
        return "".join(random.choices(_PLAYER_ID_CHARS, k=12))
