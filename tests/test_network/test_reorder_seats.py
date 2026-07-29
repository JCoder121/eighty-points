"""Lobby seat ordering — the ``reorder_seats`` WebSocket action (§6 ruling 3).

Seat order is load-bearing: in Upgrade, seats 0/2 partner against seats 1/3
(``UpgradeStrategy.assign_teams``), and the deal starts from the seat after
the round leader.  Join order is therefore not good enough to rebuild a
table, so the game master gets to rearrange seats before the game starts.

The UI for this lands separately; these tests pin the backend contract.
"""
from __future__ import annotations

from contextlib import ExitStack

from fastapi.testclient import TestClient

from shengji.models.card import Rank
from shengji.models.game_state import GamePhase
from shengji.network.app import create_app
from shengji.network.room import NUM_PLAYERS, Room, RoomManager


def _client() -> tuple[TestClient, RoomManager]:
    manager = RoomManager()
    app = create_app(manager=manager, deal_delay=0, mount_static=False)
    return TestClient(app), manager


def _setup_room(
    client: TestClient, manager: RoomManager, setup: dict | None = None
) -> tuple[str, list[str], Room]:
    """Create a full 4-player lobby.

    The Room object is returned alongside the ids because closing a WebSocket
    disconnects a player, which tears the room out of the manager — the tests
    still need to inspect the state it was left in.
    """
    body: dict = {"name": "P0"}
    if setup is not None:
        body["setup"] = setup
    d = client.post("/rooms", json=body).json()
    room_id, pids = d["room_id"], [d["player_id"]]
    for i in range(1, NUM_PLAYERS):
        pids.append(
            client.post(
                f"/rooms/{room_id}/join", json={"name": f"P{i}"}
            ).json()["player_id"]
        )
    return room_id, pids, manager.get_room(room_id)


def _next_of_type(ws, msg_type: str, max_msgs: int = 50) -> dict:
    for _ in range(max_msgs):
        msg = ws.receive_json()
        if msg.get("type") == msg_type:
            return msg
    raise AssertionError(f"No {msg_type!r} message within {max_msgs} messages")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestReorderSeats:
    def test_game_master_can_reorder(self):
        client, manager = _client()
        room_id, pids, room = _setup_room(client, manager)
        new_order = [pids[3], pids[0], pids[2], pids[1]]
        with client.websocket_connect(f"/ws/{room_id}/{pids[0]}") as ws:
            ws.send_json({"action": "reorder_seats", "order": new_order})
            _next_of_type(ws, "room_update")  # initial connect broadcast
            msg = _next_of_type(ws, "room_update")
        assert [p.id for p in room.game_state.players] == new_order
        assert [p["id"] for p in msg["players"]] == new_order

    def test_reorder_rehomes_configured_ranks_and_leader(self):
        """Ranks are configured per seat, so moving a player to a new seat
        gives them that seat's level — and seat 2 always leads."""
        client, manager = _client()
        setup = {
            "starting_ranks": ["5", "5", "K", "K"],
            "starting_leader_seat": 2,
            "starting_round_number": 4,
        }
        room_id, pids, room = _setup_room(client, manager, setup)
        state = room.game_state
        assert state.round_leader_id == pids[2]

        new_order = [pids[3], pids[2], pids[1], pids[0]]
        with client.websocket_connect(f"/ws/{room_id}/{pids[0]}") as ws:
            ws.send_json({"action": "reorder_seats", "order": new_order})
            _next_of_type(ws, "room_update")
            msg = _next_of_type(ws, "room_update")

        assert [p.rank for p in state.players] == [
            Rank.FIVE, Rank.FIVE, Rank.KING, Rank.KING
        ]
        # pids[1] now sits in seat 2 and therefore leads.
        assert state.round_leader_id == pids[1]
        assert msg["round_leader_id"] == pids[1]
        assert [p["rank"] for p in msg["players"]] == ["5", "5", "K", "K"]

    def test_identity_reorder_is_accepted(self):
        client, manager = _client()
        room_id, pids, room = _setup_room(client, manager)
        with client.websocket_connect(f"/ws/{room_id}/{pids[0]}") as ws:
            ws.send_json({"action": "reorder_seats", "order": list(pids)})
            _next_of_type(ws, "room_update")
            msg = _next_of_type(ws, "room_update")
        assert [p["id"] for p in msg["players"]] == pids

    def test_reorder_does_not_start_the_game(self):
        client, manager = _client()
        room_id, pids, room = _setup_room(client, manager)
        with client.websocket_connect(f"/ws/{room_id}/{pids[0]}") as ws:
            ws.send_json({"action": "reorder_seats", "order": list(reversed(pids))})
            _next_of_type(ws, "room_update")
            _next_of_type(ws, "room_update")
        assert room.game_state.phase == GamePhase.WAITING
        assert room.engine is None


# ---------------------------------------------------------------------------
# Rejections — the order must be a permutation, from the GM, before the deal
# ---------------------------------------------------------------------------

class TestReorderSeatsRejected:
    def _expect_error(self, payload: dict, sender_seat: int = 0) -> tuple[str, list]:
        client, manager = _client()
        room_id, pids, room = _setup_room(client, manager)
        payload = {**payload}
        if payload.get("order") == "__reversed__":
            payload["order"] = list(reversed(pids))
        with client.websocket_connect(f"/ws/{room_id}/{pids[sender_seat]}") as ws:
            ws.send_json({"action": "reorder_seats", **payload})
            msg = _next_of_type(ws, "error")
        order_after = [p.id for p in room.game_state.players]
        assert order_after == pids, "a rejected reorder must not move anyone"
        return msg["message"], pids

    def test_non_game_master_rejected(self):
        message, _ = self._expect_error({"order": "__reversed__"}, sender_seat=1)
        assert "game master" in message

    def test_duplicate_player_rejected(self):
        client, manager = _client()
        room_id, pids, room = _setup_room(client, manager)
        with client.websocket_connect(f"/ws/{room_id}/{pids[0]}") as ws:
            ws.send_json({
                "action": "reorder_seats",
                "order": [pids[0], pids[0], pids[1], pids[2]],
            })
            msg = _next_of_type(ws, "error")
        assert "exactly once" in msg["message"]
        assert [p.id for p in room.game_state.players] == pids

    def test_missing_player_rejected(self):
        message, pids = self._expect_error({"order": None})
        assert "list of player ids" in message

    def test_short_order_rejected(self):
        client, manager = _client()
        room_id, pids, room = _setup_room(client, manager)
        with client.websocket_connect(f"/ws/{room_id}/{pids[0]}") as ws:
            ws.send_json({"action": "reorder_seats", "order": pids[:3]})
            msg = _next_of_type(ws, "error")
        assert "exactly once" in msg["message"]

    def test_unknown_player_id_rejected(self):
        client, manager = _client()
        room_id, pids, room = _setup_room(client, manager)
        with client.websocket_connect(f"/ws/{room_id}/{pids[0]}") as ws:
            ws.send_json({
                "action": "reorder_seats",
                "order": [pids[0], pids[1], pids[2], "ghost1234567"],
            })
            msg = _next_of_type(ws, "error")
        assert "exactly once" in msg["message"]

    def test_non_string_entries_rejected(self):
        client, manager = _client()
        room_id, pids, room = _setup_room(client, manager)
        with client.websocket_connect(f"/ws/{room_id}/{pids[0]}") as ws:
            ws.send_json({"action": "reorder_seats", "order": [0, 1, 2, 3]})
            msg = _next_of_type(ws, "error")
        assert "list of player ids" in msg["message"]

    def test_rejected_after_the_game_has_started(self):
        client, manager = _client()
        room_id, pids, room = _setup_room(client, manager)
        with ExitStack() as stack:
            ws0 = stack.enter_context(
                client.websocket_connect(f"/ws/{room_id}/{pids[0]}")
            )
            ws0.send_json({"action": "select_mode", "mode": "upgrade"})
            for pid in pids[1:]:
                stack.enter_context(client.websocket_connect(f"/ws/{room_id}/{pid}"))
            # Wait for the deal to finish before trying to move a seat.
            for _ in range(500):
                msg = ws0.receive_json()
                if msg.get("phase") == GamePhase.BIDDING_AFTER_DEAL.value:
                    break
            else:
                raise AssertionError("never reached BIDDING_AFTER_DEAL")
            ws0.send_json({"action": "reorder_seats", "order": list(reversed(pids))})
            err = _next_of_type(ws0, "error", max_msgs=200)
        assert "before the game starts" in err["message"]
        assert [p.id for p in room.game_state.players] == pids
