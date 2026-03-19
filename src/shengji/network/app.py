"""FastAPI application — creates the ASGI app used by uvicorn.

Routes
------
POST  /rooms                    — create a room
POST  /rooms/{room_id}/join     — join an existing room
WS    /ws/{room_id}/{player_id} — main game WebSocket
GET   /                         — health check
Mounted: /superuser/…           — superuser debug endpoints (M6)
Static:  /                      — frontend HTML/JS

Usage
-----
    uvicorn shengji.network.app:app --reload

For testing, call ``create_app()`` to get an isolated instance that uses
its own ``RoomManager`` instead of the module-level singleton.
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from shengji.network.handler import handle_connection
from shengji.network.room import RoomManager
from shengji.superuser.api import SuperuserRoom

# Seconds between dealt cards in production.  Override to 0 in tests.
DEAL_DELAY_SECONDS: float = 0.25


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CreateRoomBody(BaseModel):
    name: str


class JoinRoomBody(BaseModel):
    name: str


# ---------------------------------------------------------------------------
# Superuser room adapter
# ---------------------------------------------------------------------------

class _LiveSuperuserRoom:
    """Proxy that exposes the SuperuserRoom interface backed by a live Room.

    The M6 enable endpoint mutates ``room.superuser_enabled = True`` on
    whatever object ``rooms.get(room_id)`` returns.  Returning a plain copy
    (SuperuserRoom dataclass) would discard that write.  This proxy forwards
    attribute access — including the ``superuser_enabled`` setter — directly
    to the underlying Room so changes are immediately visible in the manager.
    """

    __slots__ = ("_room",)

    def __init__(self, real_room) -> None:  # real_room: Room
        object.__setattr__(self, "_room", real_room)

    @property
    def room_id(self) -> str:
        return self._room.room_id

    @property
    def game_master_id(self) -> str:
        return self._room.game_master_id

    @property
    def game_state(self):
        return self._room.game_state

    @property
    def superuser_enabled(self) -> bool:
        return self._room.superuser_enabled

    @superuser_enabled.setter
    def superuser_enabled(self, value: bool) -> None:
        self._room.superuser_enabled = value


class _SuperuserRoomAdapter(dict):
    """A dict-like store that proxies SuperuserRoom lookups to RoomManager.

    The M6 superuser router was designed to work with a plain dict
    ``{room_id: SuperuserRoom}``.  This adapter fulfills that interface while
    delegating actual room data to the authoritative RoomManager — so the
    superuser API always sees the live GameState without any synchronisation.
    """

    def __init__(self, manager: RoomManager) -> None:
        super().__init__()
        self._manager = manager

    def __contains__(self, room_id: object) -> bool:  # type: ignore[override]
        return self._manager.get_room(str(room_id)) is not None

    def get(self, room_id: object, default=None):  # type: ignore[override]
        room = self._manager.get_room(str(room_id))
        if room is None:
            return default
        # Return a live proxy so attribute mutations (e.g. superuser_enabled)
        # write through directly to the authoritative Room object.
        return _LiveSuperuserRoom(room)

    def __getitem__(self, room_id: str):
        result = self.get(room_id)
        if result is None:
            raise KeyError(room_id)
        return result

    def __setitem__(self, room_id: str, value) -> None:
        # Safety valve: if any code path does rooms[id] = room, propagate flag.
        room = self._manager.get_room(room_id)
        if room is not None:
            room.superuser_enabled = value.superuser_enabled


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(
    manager: RoomManager | None = None,
    deal_delay: float = DEAL_DELAY_SECONDS,
    mount_static: bool = True,
) -> FastAPI:
    """Return a fully configured FastAPI application.

    Parameters
    ----------
    manager:
        Room manager to use.  Defaults to a fresh instance (good for tests).
    deal_delay:
        Seconds between dealt cards.  Set to 0 in tests for instant dealing.
    mount_static:
        Whether to serve the frontend static files.  Disable in tests to
        avoid filesystem dependencies.
    """
    if manager is None:
        manager = RoomManager()

    app = FastAPI(title="Shengji (升级)")

    # ── Health check ─────────────────────────────────────────────────────────

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "game": "shengji"}

    # ── REST endpoints ───────────────────────────────────────────────────────

    @app.post("/rooms")
    async def create_room(body: CreateRoomBody) -> dict:
        """Create a new room.  The creator becomes the game master."""
        room_id, player_id = manager.create_room(body.name)
        return {"room_id": room_id, "player_id": player_id}

    @app.post("/rooms/{room_id}/join")
    async def join_room(room_id: str, body: JoinRoomBody) -> dict:
        """Join an existing room.  Fails if full or game has started."""
        try:
            player_id = manager.join_room(room_id, body.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"player_id": player_id}

    # ── WebSocket ────────────────────────────────────────────────────────────

    @app.websocket("/ws/{room_id}/{player_id}")
    async def ws_endpoint(ws: WebSocket, room_id: str, player_id: str) -> None:
        await handle_connection(ws, room_id, player_id, manager, deal_delay)

    # ── Superuser routes ─────────────────────────────────────────────────────
    # Use the adapter so M6's router always sees live GameState.
    from shengji.superuser.api import create_router as create_superuser_router
    su_rooms = _SuperuserRoomAdapter(manager)
    app.include_router(create_superuser_router(su_rooms))

    # ── Static files (frontend) ───────────────────────────────────────────────

    if mount_static:
        static_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend")
        )
        if os.path.isdir(static_dir):
            app.mount(
                "/", StaticFiles(directory=static_dir, html=True), name="static"
            )

    return app


# ---------------------------------------------------------------------------
# Module-level singleton (used by uvicorn in production)
# ---------------------------------------------------------------------------

app = create_app()
