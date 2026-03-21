"""Tests for Room management (M7.1)."""
from __future__ import annotations

import pytest

from shengji.models.game_state import GamePhase
from shengji.network.room import NUM_PLAYERS, Room, RoomManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _manager() -> RoomManager:
    return RoomManager()


# ---------------------------------------------------------------------------
# create_room
# ---------------------------------------------------------------------------

class TestCreateRoom:
    def test_returns_room_id_and_player_id(self):
        m = _manager()
        room_id, player_id = m.create_room("Alice")
        assert room_id
        assert player_id

    def test_room_id_is_6_chars(self):
        m = _manager()
        room_id, _ = m.create_room("Alice")
        assert len(room_id) == 6

    def test_room_id_is_alphanumeric(self):
        m = _manager()
        room_id, _ = m.create_room("Alice")
        assert room_id.isalnum()

    def test_room_stored_in_manager(self):
        m = _manager()
        room_id, _ = m.create_room("Alice")
        assert m.get_room(room_id) is not None

    def test_creator_is_game_master(self):
        m = _manager()
        room_id, player_id = m.create_room("Alice")
        room = m.get_room(room_id)
        assert room.game_master_id == player_id

    def test_creator_is_first_player(self):
        m = _manager()
        room_id, player_id = m.create_room("Alice")
        room = m.get_room(room_id)
        assert room.game_state.players[0].id == player_id

    def test_creator_name_stored(self):
        m = _manager()
        room_id, _ = m.create_room("Alice")
        room = m.get_room(room_id)
        assert room.game_state.players[0].name == "Alice"

    def test_phase_is_waiting(self):
        m = _manager()
        room_id, _ = m.create_room("Alice")
        room = m.get_room(room_id)
        assert room.game_state.phase == GamePhase.WAITING

    def test_unique_room_ids(self):
        m = _manager()
        ids = {m.create_room(f"P{i}")[0] for i in range(50)}
        assert len(ids) == 50

    def test_unique_player_ids_across_rooms(self):
        m = _manager()
        pids = {m.create_room(f"P{i}")[1] for i in range(50)}
        assert len(pids) == 50


# ---------------------------------------------------------------------------
# join_room
# ---------------------------------------------------------------------------

class TestJoinRoom:
    def _create(self, m: RoomManager) -> str:
        room_id, _ = m.create_room("Alice")
        return room_id

    def test_join_returns_player_id(self):
        m = _manager()
        room_id = self._create(m)
        pid = m.join_room(room_id, "Bob")
        assert pid

    def test_join_adds_player_to_state(self):
        m = _manager()
        room_id = self._create(m)
        m.join_room(room_id, "Bob")
        room = m.get_room(room_id)
        assert len(room.game_state.players) == 2

    def test_join_stores_player_name(self):
        m = _manager()
        room_id = self._create(m)
        m.join_room(room_id, "Bob")
        room = m.get_room(room_id)
        assert any(p.name == "Bob" for p in room.game_state.players)

    def test_join_unknown_room_raises(self):
        m = _manager()
        with pytest.raises(ValueError, match="not found"):
            m.join_room("NOPE99", "Bob")

    def test_full_room_raises(self):
        m = _manager()
        room_id = self._create(m)
        for i in range(NUM_PLAYERS - 1):
            m.join_room(room_id, f"Player{i}")
        with pytest.raises(ValueError, match="full"):
            m.join_room(room_id, "Extra")

    def test_join_started_game_raises(self):
        m = _manager()
        room_id = self._create(m)
        room = m.get_room(room_id)
        room.game_state.mode = "upgrade"
        # Force phase to DEALING to simulate started game
        room.game_state.phase = GamePhase.DEALING
        with pytest.raises(ValueError, match="already started"):
            m.join_room(room_id, "Latecomer")

    def test_four_players_can_join(self):
        m = _manager()
        room_id = self._create(m)
        for i in range(NUM_PLAYERS - 1):
            m.join_room(room_id, f"Player{i}")
        room = m.get_room(room_id)
        assert len(room.game_state.players) == NUM_PLAYERS

    def test_duplicate_name_raises(self):
        m = _manager()
        room_id = self._create(m)  # Alice already in room
        with pytest.raises(ValueError, match="already taken"):
            m.join_room(room_id, "Alice")

    def test_different_name_allowed_after_duplicate_attempt(self):
        m = _manager()
        room_id = self._create(m)
        with pytest.raises(ValueError):
            m.join_room(room_id, "Alice")
        pid = m.join_room(room_id, "Bob")  # should succeed
        assert pid


# ---------------------------------------------------------------------------
# get_room / remove_room
# ---------------------------------------------------------------------------

class TestRoomLifecycle:
    def test_get_nonexistent_returns_none(self):
        m = _manager()
        assert m.get_room("ZZZZZZ") is None

    def test_remove_room(self):
        m = _manager()
        room_id, _ = m.create_room("Alice")
        m.remove_room(room_id)
        assert m.get_room(room_id) is None

    def test_remove_nonexistent_is_noop(self):
        m = _manager()
        m.remove_room("NOPE99")  # should not raise

    def test_all_room_ids(self):
        m = _manager()
        ids = [m.create_room(f"P{i}")[0] for i in range(3)]
        assert set(m.all_room_ids()) == set(ids)


# ---------------------------------------------------------------------------
# Room dataclass defaults
# ---------------------------------------------------------------------------

class TestRoomDefaults:
    def test_engine_starts_none(self):
        m = _manager()
        room_id, _ = m.create_room("Alice")
        room = m.get_room(room_id)
        assert room.engine is None

    def test_connections_start_empty(self):
        m = _manager()
        room_id, _ = m.create_room("Alice")
        room = m.get_room(room_id)
        assert room.connections == {}

    def test_superuser_disabled_by_default(self):
        m = _manager()
        room_id, _ = m.create_room("Alice")
        room = m.get_room(room_id)
        assert room.superuser_enabled is False

    def test_passed_in_bidding_empty(self):
        m = _manager()
        room_id, _ = m.create_room("Alice")
        room = m.get_room(room_id)
        assert room.passed_in_bidding == set()
