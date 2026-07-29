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

from shengji.models.card import RANK_ORDER, Rank
from shengji.models.game_state import GamePhase, GameState
from shengji.models.player import Player

if TYPE_CHECKING:
    from fastapi import WebSocket
    from shengji.engine.engine import GameEngine
    from shengji.engine.logger import GameLogger

# ── Constants ────────────────────────────────────────────────────────────────

NUM_PLAYERS = 4

_ROOM_ID_CHARS = string.ascii_uppercase + string.digits  # e.g. "AB3X7Q"
_PLAYER_ID_CHARS = string.ascii_lowercase + string.digits

# A resumed game is by definition not on its first round.  Only cosmetic —
# the predetermined-leader semantics come from GameState.leader_predetermined,
# not from this number.
_DEFAULT_RESUME_ROUND = 2


# ── RoomSetup ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RoomSetup:
    """Starting configuration that resumes a previous session.

    Everything is keyed by **seat index**, not player id, because the room is
    configured before anyone but the game master has joined.  Seat 0 is the
    game master (room creator); seats 1-3 are filled in join order and may
    afterwards be rearranged by the ``reorder_seats`` lobby action.  Whatever
    seat order is in place when the game starts is the one these ranks apply
    to.

    Attributes
    ----------
    starting_ranks:
        One rank per seat (exactly NUM_PLAYERS), each in RANK_ORDER (2..A).
    starting_leader_seat:
        Seat that leads the resumed round.  Unlike an ordinary round 1, this
        leader is *predetermined*: bidding only fixes the trump suit and
        cannot hand leadership to the winning bidder (R18).  The trump rank
        for the round is this seat's level (R12/D01).
    starting_round_number:
        Round number to display and score from.
    """

    starting_ranks: tuple[Rank, ...]
    starting_leader_seat: int = 0
    starting_round_number: int = _DEFAULT_RESUME_ROUND

    # ── Serialisation ─────────────────────────────────────────────────────

    def to_json(self) -> dict:
        return {
            "starting_ranks": [r.value for r in self.starting_ranks],
            "starting_leader_seat": self.starting_leader_seat,
            "starting_round_number": self.starting_round_number,
        }

    @classmethod
    def from_json(cls, data: dict) -> "RoomSetup":
        """Build a validated RoomSetup from an untrusted JSON object.

        Raises
        ------
        ValueError
            With a message suitable for showing to the game master.
        """
        if not isinstance(data, dict):
            raise ValueError("setup must be a JSON object.")

        raw_ranks = data.get("starting_ranks")
        if not isinstance(raw_ranks, list) or len(raw_ranks) != NUM_PLAYERS:
            raise ValueError(
                f"setup.starting_ranks must be a list of {NUM_PLAYERS} ranks."
            )
        ranks: list[Rank] = []
        for raw in raw_ranks:
            try:
                rank = Rank(raw)
            except ValueError:
                raise ValueError(f"Unknown rank {raw!r} in setup.starting_ranks.")
            if rank not in RANK_ORDER:
                # Jokers have ranks but are not levels a player can sit at.
                raise ValueError(
                    f"Rank {raw!r} is not a playable level (must be 2..A)."
                )
            ranks.append(rank)

        seat = data.get("starting_leader_seat", 0)
        if isinstance(seat, bool) or not isinstance(seat, int):
            raise ValueError("setup.starting_leader_seat must be an integer.")
        if not 0 <= seat < NUM_PLAYERS:
            raise ValueError(
                f"setup.starting_leader_seat must be 0..{NUM_PLAYERS - 1}, got {seat}."
            )

        round_number = data.get("starting_round_number", _DEFAULT_RESUME_ROUND)
        if isinstance(round_number, bool) or not isinstance(round_number, int):
            raise ValueError("setup.starting_round_number must be an integer.")
        if round_number < 1:
            raise ValueError(
                f"setup.starting_round_number must be >= 1, got {round_number}."
            )

        return cls(
            starting_ranks=tuple(ranks),
            starting_leader_seat=seat,
            starting_round_number=round_number,
        )


def apply_setup(state: GameState, setup: RoomSetup) -> None:
    """Write *setup* onto *state*, keyed by current seat order.

    Idempotent, and a no-op outside WAITING — the lobby re-applies on every
    roster or seat-order change, and must never rewrite a live game's ranks
    or round number.  The leader is only assigned once their seat is filled.

    Called before dealing, so ``place_bid`` derives the trump rank from the
    configured leader's level for free (R12/D01).
    """
    if state.phase != GamePhase.WAITING:
        return
    for seat, player in enumerate(state.players):
        if seat < len(setup.starting_ranks):
            player.rank = setup.starting_ranks[seat]
    state.round_number = setup.starting_round_number
    if setup.starting_leader_seat < len(state.players):
        state.round_leader_id = state.players[setup.starting_leader_seat].id
        # R18: the configured leader keeps the lead through bidding, exactly
        # like a round-2+ leader.  Without this a round-1 close_bidding would
        # hand leadership to the winning bidder.
        state.leader_predetermined = True


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
        select the game mode and reorder seats.
    game_state:
        The mutable GameState driven by the engine.
    engine:
        Created when dealing begins (None before the first deal starts).
    connections:
        Live WebSocket per player.  Not every player may be connected at all
        times (though in practice the room is destroyed on first disconnect).
    setup:
        Resume configuration supplied at room creation, or None for a fresh
        game.  Re-applied by seat on every lobby roster/order change.
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
    logger: "GameLogger | None" = None
    connections: dict[str, "WebSocket"] = field(default_factory=dict)
    setup: RoomSetup | None = None
    # Deterministic deals for the whole session when the room was created
    # with a seed: one Random instance shared by every round's engine, so a
    # given seed replays the same sequence of deals.
    rng: "random.Random | None" = None
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

    def create_room(
        self,
        player_name: str,
        setup: RoomSetup | None = None,
        seed: int | None = None,
    ) -> tuple[str, str]:
        """Create a new room with *player_name* as game master.

        Parameters
        ----------
        setup:
            Optional resume configuration (starting levels, leading seat,
            round number).  Applied by seat here and re-applied on every
            subsequent join / seat reorder.
        seed:
            Optional RNG seed for deterministic deals.  One Random instance
            is created here and reused by every round's engine, so the same
            seed replays the same session of deals.

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
        room = Room(
            room_id=room_id,
            game_master_id=player_id,
            game_state=state,
            setup=setup,
            rng=random.Random(seed) if seed is not None else None,
        )
        if setup is not None:
            apply_setup(state, setup)
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
            If the room does not exist, is full, the game has started, or the
            name is already taken.
        """
        room = self.get_room(room_id)
        if room is None:
            raise ValueError(f"Room {room_id!r} not found.")
        if len(room.game_state.players) >= NUM_PLAYERS:
            raise ValueError("Room is full (4 players maximum).")
        if room.game_state.phase != GamePhase.WAITING:
            raise ValueError("Game has already started — cannot join mid-game.")
        existing_names = {p.name for p in room.game_state.players}
        if player_name in existing_names:
            raise ValueError(f"Name {player_name!r} is already taken in this room.")

        player_id = self._gen_player_id()
        player = Player(id=player_id, name=player_name)
        room.game_state.players.append(player)
        if room.setup is not None:
            apply_setup(room.game_state, room.setup)
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
