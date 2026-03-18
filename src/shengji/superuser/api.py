"""Superuser HTTP endpoints (mounted under /superuser/).

Room management
---------------
This module maintains a simple in-memory room store:

    _rooms: dict[str, SuperuserRoom]

Each ``SuperuserRoom`` holds a ``GameState``, the game master's player ID,
and a ``superuser_enabled`` flag.  M7 (Networking) will integrate this store
with the full Room management system; for now the store is standalone.

Access control
--------------
All endpoints except ``POST /superuser/enable/{room_id}`` require:
  1. The ``X-Player-Id`` header matches the room's ``game_master_id``.
  2. ``room.superuser_enabled == True``.

The enable endpoint only requires the header to match ``game_master_id``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from shengji.models.card import Card, Rank, Suit
from shengji.models.game_state import GamePhase, GameState
from shengji.models.player import Player
from shengji.models.trump import TrumpContext
from shengji.superuser import inspector, mutator

# ---------------------------------------------------------------------------
# Room model
# ---------------------------------------------------------------------------

@dataclass
class SuperuserRoom:
    """Minimal room record used by the superuser API."""

    room_id: str
    game_master_id: str
    game_state: GameState
    superuser_enabled: bool = False


# Module-level in-memory store.  Tests may populate this directly.
_rooms: dict[str, SuperuserRoom] = {}


def get_rooms() -> dict[str, SuperuserRoom]:
    """Return the live room store (injectable in tests)."""
    return _rooms


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class _CardJson(BaseModel):
    suit: str
    rank: str


class SetHandBody(BaseModel):
    player_id: str
    cards: list[_CardJson]


class SetPointsBody(BaseModel):
    attacking_points: int


class ForcePhaseBody(BaseModel):
    phase: str


class DealSpecificBody(BaseModel):
    hands: dict[str, list[_CardJson]]
    bottom: list[_CardJson]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_from_json(c: _CardJson) -> Card:
    return Card.from_json({"suit": c.suit, "rank": c.rank})


def _get_room(room_id: str, rooms: dict[str, SuperuserRoom]) -> SuperuserRoom:
    room = rooms.get(room_id)
    if room is None:
        raise HTTPException(status_code=404, detail=f"Room {room_id!r} not found.")
    return room


def _require_access(
    room: SuperuserRoom, player_id: str, require_enabled: bool = True
) -> None:
    """Raise 403 if access control fails."""
    if player_id != room.game_master_id:
        raise HTTPException(
            status_code=403,
            detail="Only the game master can access superuser endpoints.",
        )
    if require_enabled and not room.superuser_enabled:
        raise HTTPException(
            status_code=403,
            detail=(
                "Superuser mode is not enabled for this room. "
                "Call POST /superuser/enable/{room_id} first."
            ),
        )


# ---------------------------------------------------------------------------
# Router factory (accepts an injectable room store for testing)
# ---------------------------------------------------------------------------

def create_router(rooms: dict[str, SuperuserRoom] | None = None) -> APIRouter:
    """Return a FastAPI APIRouter wired to *rooms*.

    If *rooms* is None the module-level ``_rooms`` dict is used (production).
    Tests pass their own dict to get full isolation.
    """
    if rooms is None:
        rooms = _rooms

    router = APIRouter(prefix="/superuser", tags=["superuser"])

    # ------------------------------------------------------------------
    # Enable superuser mode
    # ------------------------------------------------------------------

    @router.post("/enable/{room_id}")
    def enable_superuser(
        room_id: str,
        x_player_id: str = Header(..., alias="X-Player-Id"),
    ) -> dict[str, Any]:
        """Activate superuser mode for this room (game master only).

        Idempotent — calling twice is harmless.
        """
        room = _get_room(room_id, rooms)
        _require_access(room, x_player_id, require_enabled=False)
        room.superuser_enabled = True
        return {"ok": True, "superuser_enabled": True}

    # ------------------------------------------------------------------
    # Read-only
    # ------------------------------------------------------------------

    @router.get("/state/{room_id}")
    def get_state(
        room_id: str,
        x_player_id: str = Header(..., alias="X-Player-Id"),
    ) -> dict[str, Any]:
        """Return the full game state (all hands visible)."""
        room = _get_room(room_id, rooms)
        _require_access(room, x_player_id)
        return inspector.get_full_state(room.game_state)

    @router.post("/validate/{room_id}")
    def validate(
        room_id: str,
        x_player_id: str = Header(..., alias="X-Player-Id"),
    ) -> dict[str, Any]:
        """Run state validation and return any violations."""
        room = _get_room(room_id, rooms)
        _require_access(room, x_player_id)
        violations = inspector.validate_state(room.game_state)
        return {"violations": violations, "valid": len(violations) == 0}

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    @router.post("/set-hand/{room_id}")
    def set_hand(
        room_id: str,
        body: SetHandBody,
        x_player_id: str = Header(..., alias="X-Player-Id"),
    ) -> dict[str, Any]:
        """Replace a player's hand."""
        room = _get_room(room_id, rooms)
        _require_access(room, x_player_id)
        cards = [_card_from_json(c) for c in body.cards]
        try:
            warnings = mutator.set_hand(room.game_state, body.player_id, cards)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "warnings": warnings}

    @router.post("/set-points/{room_id}")
    def set_points(
        room_id: str,
        body: SetPointsBody,
        x_player_id: str = Header(..., alias="X-Player-Id"),
    ) -> dict[str, Any]:
        """Override attacking points."""
        room = _get_room(room_id, rooms)
        _require_access(room, x_player_id)
        warnings = mutator.set_points(room.game_state, body.attacking_points)
        return {"ok": True, "warnings": warnings}

    @router.post("/force-phase/{room_id}")
    def force_phase(
        room_id: str,
        body: ForcePhaseBody,
        x_player_id: str = Header(..., alias="X-Player-Id"),
    ) -> dict[str, Any]:
        """Jump to a specific phase, bypassing the normal transition graph."""
        room = _get_room(room_id, rooms)
        _require_access(room, x_player_id)
        try:
            phase = GamePhase(body.phase)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Unknown phase: {body.phase!r}"
            )
        warnings = mutator.force_phase(room.game_state, phase)
        return {"ok": True, "warnings": warnings}

    @router.post("/deal-specific/{room_id}")
    def deal_specific(
        room_id: str,
        body: DealSpecificBody,
        x_player_id: str = Header(..., alias="X-Player-Id"),
    ) -> dict[str, Any]:
        """Set up a deterministic card distribution."""
        room = _get_room(room_id, rooms)
        _require_access(room, x_player_id)
        hands = {
            pid: [_card_from_json(c) for c in cards]
            for pid, cards in body.hands.items()
        }
        bottom = [_card_from_json(c) for c in body.bottom]
        try:
            warnings = mutator.deal_specific_hands(room.game_state, hands, bottom)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "warnings": warnings}

    return router


# Default router (used by the main app in M7).
router = create_router()
