"""FastAPI application — creates the ASGI app used by uvicorn.

Routes
------
POST  /rooms                    — create a room (optionally with resume setup)
POST  /rooms/{room_id}/join     — join an existing room
WS    /ws/{room_id}/{player_id} — main game WebSocket
GET   /                         — health check
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
from shengji.network.room import RoomManager, RoomSetup

# Seconds between dealt cards in production.  Override to 0 in tests.
DEAL_DELAY_SECONDS: float = 0.25


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CreateRoomBody(BaseModel):
    name: str
    # Optional resume configuration; validated by RoomSetup.from_json.
    # Left untyped here so a malformed payload produces our own 400 with a
    # readable message rather than pydantic's field-path error dump.
    setup: dict | None = None
    # Optional RNG seed: deterministic deals for the whole session (the same
    # seed replays the same sequence of hands round after round).
    seed: int | None = None


class JoinRoomBody(BaseModel):
    name: str


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
        """Create a new room.  The creator becomes the game master.

        An optional ``setup`` block resumes a previous session: it fixes each
        seat's starting level, which seat leads the first round, and the round
        number to display.  See ``RoomSetup``.
        """
        setup = None
        if body.setup is not None:
            try:
                setup = RoomSetup.from_json(body.setup)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
        room_id, player_id = manager.create_room(
            body.name, setup=setup, seed=body.seed
        )
        return {
            "room_id": room_id,
            "player_id": player_id,
            "setup": setup.to_json() if setup else None,
        }

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
