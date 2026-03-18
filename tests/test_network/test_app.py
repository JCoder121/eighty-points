"""Tests for REST endpoints (M7.2/M7.3)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from shengji.models.game_state import GamePhase
from shengji.network.app import create_app
from shengji.network.room import NUM_PLAYERS, RoomManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _client() -> tuple[TestClient, RoomManager]:
    manager = RoomManager()
    app = create_app(manager=manager, deal_delay=0, mount_static=False)
    return TestClient(app), manager


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def test_health_check():
    client, _ = _client()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# POST /rooms
# ---------------------------------------------------------------------------

class TestCreateRoom:
    def test_returns_room_id_and_player_id(self):
        client, _ = _client()
        resp = client.post("/rooms", json={"name": "Alice"})
        assert resp.status_code == 200
        data = resp.json()
        assert "room_id" in data
        assert "player_id" in data

    def test_room_id_is_6_chars(self):
        client, _ = _client()
        resp = client.post("/rooms", json={"name": "Alice"})
        assert len(resp.json()["room_id"]) == 6

    def test_room_exists_in_manager(self):
        client, manager = _client()
        resp = client.post("/rooms", json={"name": "Alice"})
        room_id = resp.json()["room_id"]
        assert manager.get_room(room_id) is not None

    def test_creator_is_game_master(self):
        client, manager = _client()
        resp = client.post("/rooms", json={"name": "Alice"})
        data = resp.json()
        room = manager.get_room(data["room_id"])
        assert room.game_master_id == data["player_id"]

    def test_multiple_rooms_have_different_ids(self):
        client, _ = _client()
        r1 = client.post("/rooms", json={"name": "A"}).json()["room_id"]
        r2 = client.post("/rooms", json={"name": "B"}).json()["room_id"]
        assert r1 != r2


# ---------------------------------------------------------------------------
# POST /rooms/{room_id}/join
# ---------------------------------------------------------------------------

class TestJoinRoom:
    def _create(self, client: TestClient) -> tuple[str, str]:
        resp = client.post("/rooms", json={"name": "Alice"})
        d = resp.json()
        return d["room_id"], d["player_id"]

    def test_join_returns_player_id(self):
        client, _ = _client()
        room_id, _ = self._create(client)
        resp = client.post(f"/rooms/{room_id}/join", json={"name": "Bob"})
        assert resp.status_code == 200
        assert "player_id" in resp.json()

    def test_join_different_player_id_from_creator(self):
        client, _ = _client()
        room_id, alice_id = self._create(client)
        bob_id = client.post(f"/rooms/{room_id}/join", json={"name": "Bob"}).json()["player_id"]
        assert alice_id != bob_id

    def test_join_unknown_room_returns_400(self):
        client, _ = _client()
        resp = client.post("/rooms/ZZZZZZ/join", json={"name": "Bob"})
        assert resp.status_code == 400

    def test_full_room_returns_400(self):
        client, _ = _client()
        room_id, _ = self._create(client)
        for i in range(NUM_PLAYERS - 1):
            client.post(f"/rooms/{room_id}/join", json={"name": f"Player{i}"})
        resp = client.post(f"/rooms/{room_id}/join", json={"name": "Extra"})
        assert resp.status_code == 400
        assert "full" in resp.json()["detail"].lower()

    def test_join_started_game_returns_400(self):
        client, manager = _client()
        room_id, _ = self._create(client)
        room = manager.get_room(room_id)
        room.game_state.phase = GamePhase.DEALING
        resp = client.post(f"/rooms/{room_id}/join", json={"name": "Late"})
        assert resp.status_code == 400

    def test_four_players_can_join_sequentially(self):
        client, manager = _client()
        room_id, _ = self._create(client)
        for i in range(NUM_PLAYERS - 1):
            resp = client.post(f"/rooms/{room_id}/join", json={"name": f"P{i}"})
            assert resp.status_code == 200
        assert len(manager.get_room(room_id).game_state.players) == NUM_PLAYERS


# ---------------------------------------------------------------------------
# Superuser endpoints accessible via the app (adapter integration)
# ---------------------------------------------------------------------------

class TestSuperuserAdapter:
    def _setup(self, client: TestClient, manager: RoomManager) -> tuple[str, str]:
        resp = client.post("/rooms", json={"name": "GM"})
        d = resp.json()
        return d["room_id"], d["player_id"]

    def test_enable_superuser_via_app(self):
        client, manager = _client()
        room_id, gm_id = self._setup(client, manager)
        resp = client.post(
            f"/superuser/enable/{room_id}",
            headers={"X-Player-Id": gm_id},
        )
        assert resp.status_code == 200
        # Flag propagated to main Room
        room = manager.get_room(room_id)
        assert room.superuser_enabled is True

    def test_superuser_state_reflects_live_game_state(self):
        client, manager = _client()
        room_id, gm_id = self._setup(client, manager)
        # Enable superuser
        client.post(f"/superuser/enable/{room_id}", headers={"X-Player-Id": gm_id})
        # Mutate game state directly
        manager.get_room(room_id).game_state.attacking_points = 42
        resp = client.get(
            f"/superuser/state/{room_id}",
            headers={"X-Player-Id": gm_id},
        )
        assert resp.status_code == 200
        assert resp.json()["attacking_points"] == 42

    def test_non_gm_cannot_enable_via_app(self):
        client, manager = _client()
        room_id, _ = self._setup(client, manager)
        resp = client.post(
            f"/superuser/enable/{room_id}",
            headers={"X-Player-Id": "hacker"},
        )
        assert resp.status_code == 403
