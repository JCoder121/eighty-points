"""WebSocket multi-player integration tests (M7.4).

Strategy
--------
- Use ``TestClient`` with ``client.websocket_connect()`` context managers.
- Multiple simultaneous connections are managed via ``contextlib.ExitStack``.
- All 4 players are created via REST before any WebSocket is opened.
- ``_drain_until_phase`` consumes messages until the desired game phase
  appears, handling the variable-length lobby/dealing message flood without
  hard-coding exact counts.
- ``deal_delay=0`` and ``mount_static=False`` keep tests fast and isolated.

Race-free dealing setup
-----------------------
In Starlette's TestClient each WebSocket connection runs in its own OS thread
with its own asyncio event loop.  If we connect all 4 players *then* send
``select_mode``, two ``start_and_deal`` tasks can race:

  1. LOOP 0 (ws[0]) processes ``select_mode`` → sets mode → 4 players → auto-start
  2. LOOP 3 (ws[3]) checks auto-start after its initial broadcasts, sees mode
     already set and 4 players → second auto-start

Two deals produce 4 ``bidding_after_deal`` messages per player, leaving stale
messages that cause assertions to fail for subsequent actions.

Fix: send ``select_mode`` when only 1 player is connected (check fails: 1≠4).
Then connect players 1, 2.  Connect player 3 last — ``handle_connection`` sees
4 players + mode already set → triggers *exactly one* auto-start.  In all
timing scenarios this yields exactly 2 ``bidding_after_deal`` messages per
player per deal.
"""
from __future__ import annotations

from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient

from shengji.models.game_state import GamePhase
from shengji.network.app import create_app
from shengji.network.room import NUM_PLAYERS, RoomManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client() -> tuple[TestClient, RoomManager]:
    manager = RoomManager()
    app = create_app(manager=manager, deal_delay=0, mount_static=False)
    return TestClient(app), manager


def _setup_room(client: TestClient, n: int = 1) -> tuple[str, list[str]]:
    """Create a room via REST and add ``n`` players total. Returns (room_id, player_ids)."""
    resp = client.post("/rooms", json={"name": "P0"})
    d = resp.json()
    room_id, pids = d["room_id"], [d["player_id"]]
    for i in range(1, n):
        pid = client.post(
            f"/rooms/{room_id}/join", json={"name": f"P{i}"}
        ).json()["player_id"]
        pids.append(pid)
    return room_id, pids


def _drain_until_phase(ws, phase_value: str, max_msgs: int = 500) -> dict:
    """Keep receiving until a game_state with ``phase_value`` appears; return that msg."""
    for _ in range(max_msgs):
        msg = ws.receive_json()
        if msg.get("type") == "game_state" and msg.get("phase") == phase_value:
            return msg
    raise AssertionError(
        f"Did not reach phase {phase_value!r} within {max_msgs} messages"
    )


def _next_of_type(ws, msg_type: str, max_msgs: int = 50) -> dict:
    """Skip messages until one with ``msg_type`` is found; return it."""
    for _ in range(max_msgs):
        msg = ws.receive_json()
        if msg.get("type") == msg_type:
            return msg
    raise AssertionError(f"No message of type {msg_type!r} within {max_msgs} messages")


def _setup_deal(
    stack: ExitStack,
    client: TestClient,
    room_id: str,
    pids: list[str],
    mode: str = "upgrade",
) -> list:
    """Race-free helper: connect 4 players and drive to BIDDING_AFTER_DEAL.

    Pattern (see module docstring for rationale):
    1. Connect ws[0], immediately send select_mode (1 player → no auto-start).
    2. Connect ws[1], ws[2].
    3. Connect ws[3] → 4 players + mode set → exactly ONE auto-start fires.
    4. Drain all 4 WS queues to BIDDING_AFTER_DEAL, consuming both the
       on_card_dealt game_state and start_and_deal's final broadcast_game_states.

    Returns the list of WebSocket sessions [ws0, ws1, ws2, ws3].
    """
    ws0 = stack.enter_context(client.websocket_connect(f"/ws/{room_id}/{pids[0]}"))
    ws0.send_json({"action": "select_mode", "mode": mode})
    ws1 = stack.enter_context(client.websocket_connect(f"/ws/{room_id}/{pids[1]}"))
    ws2 = stack.enter_context(client.websocket_connect(f"/ws/{room_id}/{pids[2]}"))
    ws3 = stack.enter_context(client.websocket_connect(f"/ws/{room_id}/{pids[3]}"))
    wss = [ws0, ws1, ws2, ws3]
    # Drain all lobby + dealing messages for every player.
    # start_and_deal sends exactly 2 bidding_after_deal messages per deal:
    #   #1 from on_card_dealt after the final card (phase transitions there)
    #   #2 from start_and_deal's own broadcast_game_states after deal_all_cards
    for ws in wss:
        _drain_until_phase(ws, "bidding_after_deal")  # consumes #1
        ws.receive_json()                              # consumes #2 (trailing)
    return wss


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestWebSocketErrors:
    def test_unknown_room_gets_error(self):
        client, _ = _client()
        with client.websocket_connect("/ws/ZZZZZZ/fakeplayer") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "ZZZZZZ" in msg["message"]

    def test_unknown_player_gets_error(self):
        client, _ = _client()
        room_id, _ = _setup_room(client)
        with client.websocket_connect(f"/ws/{room_id}/notaplayer") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "not found" in msg["message"].lower()


# ---------------------------------------------------------------------------
# Connection / lobby broadcasts
# ---------------------------------------------------------------------------

class TestWebSocketConnection:
    def test_connect_receives_room_update_then_game_state(self):
        client, _ = _client()
        room_id, [pid] = _setup_room(client)
        with client.websocket_connect(f"/ws/{room_id}/{pid}") as ws:
            m1 = ws.receive_json()
            m2 = ws.receive_json()
            assert m1["type"] == "room_update"
            assert m2["type"] == "game_state"

    def test_room_update_contains_room_id(self):
        client, _ = _client()
        room_id, [pid] = _setup_room(client)
        with client.websocket_connect(f"/ws/{room_id}/{pid}") as ws:
            msg = ws.receive_json()
            assert msg["room_id"] == room_id

    def test_initial_game_state_phase_is_waiting(self):
        client, _ = _client()
        room_id, [pid] = _setup_room(client)
        with client.websocket_connect(f"/ws/{room_id}/{pid}") as ws:
            ws.receive_json()  # room_update
            msg = ws.receive_json()
            assert msg["phase"] == GamePhase.WAITING.value

    def test_second_player_connect_updates_first_player(self):
        """When player 2 connects, player 1 should receive a fresh room_update."""
        client, _ = _client()
        room_id, [pid1, pid2] = _setup_room(client, n=2)
        with ExitStack() as stack:
            ws1 = stack.enter_context(client.websocket_connect(f"/ws/{room_id}/{pid1}"))
            ws1.receive_json()  # own room_update
            ws1.receive_json()  # own game_state

            ws2 = stack.enter_context(client.websocket_connect(f"/ws/{room_id}/{pid2}"))
            # ws2 connecting triggers broadcast → ws1 receives updated room_update
            msg = ws1.receive_json()
            assert msg["type"] == "room_update"
            assert len(msg["players"]) == 2

    def test_room_update_includes_both_player_ids(self):
        client, _ = _client()
        room_id, [pid1, pid2] = _setup_room(client, n=2)
        with ExitStack() as stack:
            ws1 = stack.enter_context(client.websocket_connect(f"/ws/{room_id}/{pid1}"))
            ws1.receive_json()
            ws1.receive_json()
            ws2 = stack.enter_context(client.websocket_connect(f"/ws/{room_id}/{pid2}"))
            room_update = ws1.receive_json()  # room_update from ws2 joining
            ids = {p["id"] for p in room_update["players"]}
            assert pid1 in ids
            assert pid2 in ids


# ---------------------------------------------------------------------------
# Mode selection
# ---------------------------------------------------------------------------

class TestModeSelection:
    def test_gm_select_mode_broadcasts_room_update_with_mode(self):
        client, _ = _client()
        room_id, [pid] = _setup_room(client)
        with client.websocket_connect(f"/ws/{room_id}/{pid}") as ws:
            ws.receive_json()  # room_update
            ws.receive_json()  # game_state
            ws.send_json({"action": "select_mode", "mode": "upgrade"})
            msg = ws.receive_json()
            assert msg["type"] == "room_update"
            assert msg["mode"] == "upgrade"

    def test_non_gm_select_mode_gets_error(self):
        client, _ = _client()
        room_id, [pid1, pid2] = _setup_room(client, n=2)
        with ExitStack() as stack:
            ws1 = stack.enter_context(client.websocket_connect(f"/ws/{room_id}/{pid1}"))
            ws1.receive_json(); ws1.receive_json()
            ws2 = stack.enter_context(client.websocket_connect(f"/ws/{room_id}/{pid2}"))
            # Drain messages from ws2 connecting
            ws1.receive_json(); ws1.receive_json()
            ws2.receive_json(); ws2.receive_json()

            ws2.send_json({"action": "select_mode", "mode": "upgrade"})
            msg = ws2.receive_json()
            assert msg["type"] == "error"
            assert "game master" in msg["message"].lower()

    def test_invalid_mode_gets_error(self):
        client, _ = _client()
        room_id, [pid] = _setup_room(client)
        with client.websocket_connect(f"/ws/{room_id}/{pid}") as ws:
            ws.receive_json(); ws.receive_json()
            ws.send_json({"action": "select_mode", "mode": "bogus_mode"})
            msg = ws.receive_json()
            assert msg["type"] == "error"

    def test_unknown_action_gets_error(self):
        client, _ = _client()
        room_id, [pid] = _setup_room(client)
        with client.websocket_connect(f"/ws/{room_id}/{pid}") as ws:
            ws.receive_json(); ws.receive_json()
            ws.send_json({"action": "fly_to_moon"})
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "unknown action" in msg["message"].lower()


# ---------------------------------------------------------------------------
# Dealing (requires all 4 players)
# ---------------------------------------------------------------------------

class TestDealing:
    def test_four_players_select_mode_triggers_dealing(self):
        """4 connected players + select_mode → game reaches BIDDING_AFTER_DEAL."""
        client, _ = _client()
        room_id, pids = _setup_room(client, n=NUM_PLAYERS)
        with ExitStack() as stack:
            _setup_deal(stack, client, room_id, pids)
            # _setup_deal drains to bidding — success implies dealing completed

    def test_player_hand_non_empty_after_deal(self):
        client, _ = _client()
        room_id, pids = _setup_room(client, n=NUM_PLAYERS)
        with ExitStack() as stack:
            ws0 = stack.enter_context(client.websocket_connect(f"/ws/{room_id}/{pids[0]}"))
            ws0.send_json({"action": "select_mode", "mode": "upgrade"})
            for pid in pids[1:]:
                stack.enter_context(client.websocket_connect(f"/ws/{room_id}/{pid}"))
            # _drain_until_phase returns the matching game_state, which has the player's hand.
            state = _drain_until_phase(ws0, "bidding_after_deal")
            # Player 0's own entry always has hand visible (include_hand=True for self).
            own = next(
                (p for p in state["players"] if p.get("hand") is not None), None
            )
            assert own is not None
            assert len(own["hand"]) > 0

    def test_card_dealt_messages_arrive_during_deal(self):
        """The server sends card_dealt before each game_state update per card."""
        client, _ = _client()
        room_id, pids = _setup_room(client, n=NUM_PLAYERS)
        with ExitStack() as stack:
            ws0 = stack.enter_context(client.websocket_connect(f"/ws/{room_id}/{pids[0]}"))
            ws0.send_json({"action": "select_mode", "mode": "upgrade"})
            for pid in pids[1:]:
                stack.enter_context(client.websocket_connect(f"/ws/{room_id}/{pid}"))
            card_dealt_count = 0
            for _ in range(600):
                msg = ws0.receive_json()
                if msg["type"] == "card_dealt":
                    card_dealt_count += 1
                if msg.get("type") == "game_state" and msg.get("phase") == "bidding_after_deal":
                    break
            assert card_dealt_count > 0

    def test_all_four_players_reach_bidding_phase(self):
        """Every player independently receives a BIDDING_AFTER_DEAL game_state."""
        client, _ = _client()
        room_id, pids = _setup_room(client, n=NUM_PLAYERS)
        with ExitStack() as stack:
            # _setup_deal returns after all 4 players reached bidding_after_deal.
            _setup_deal(stack, client, room_id, pids)

    def test_find_friends_mode_also_reaches_bidding(self):
        client, _ = _client()
        room_id, pids = _setup_room(client, n=NUM_PLAYERS)
        with ExitStack() as stack:
            _setup_deal(stack, client, room_id, pids, mode="find_friends")


# ---------------------------------------------------------------------------
# Bidding phase
# ---------------------------------------------------------------------------

class TestBidding:
    """Tests that assume we reach BIDDING_AFTER_DEAL first via _setup_deal."""

    def test_all_pass_bid_auto_closes_bidding(self):
        """When all NUM_PLAYERS players pass, bidding closes automatically."""
        client, _ = _client()
        room_id, pids = _setup_room(client, n=NUM_PLAYERS)
        with ExitStack() as stack:
            wss = _setup_deal(stack, client, room_id, pids)
            for ws in wss:
                ws.send_json({"action": "pass_bid"})
            # After 4 passes the server closes bidding and broadcasts a new game_state
            msg = wss[0].receive_json()
            assert msg["type"] == "game_state"
            assert msg["phase"] != "bidding_after_deal"

    def test_pass_bid_in_wrong_phase_gets_error(self):
        """pass_bid outside BIDDING_AFTER_DEAL returns an error."""
        client, _ = _client()
        room_id, [pid] = _setup_room(client)
        with client.websocket_connect(f"/ws/{room_id}/{pid}") as ws:
            ws.receive_json(); ws.receive_json()  # lobby messages
            ws.send_json({"action": "pass_bid"})
            msg = ws.receive_json()
            assert msg["type"] == "error"

    def test_bid_without_engine_gets_error(self):
        """Bidding before the game engine is set up returns an error."""
        client, _ = _client()
        room_id, [pid] = _setup_room(client)
        with client.websocket_connect(f"/ws/{room_id}/{pid}") as ws:
            ws.receive_json(); ws.receive_json()
            ws.send_json({"action": "bid", "suit": "hearts"})
            msg = ws.receive_json()
            assert msg["type"] == "error"

    def test_passed_player_cannot_bid_again(self):
        """A player who has passed cannot place a bid — regression for issue #24."""
        client, _ = _client()
        room_id, pids = _setup_room(client, n=NUM_PLAYERS)
        with ExitStack() as stack:
            wss = _setup_deal(stack, client, room_id, pids)
            # Player 0 passes
            wss[0].send_json({"action": "pass_bid"})
            # Player 0 attempts to bid — should be rejected immediately
            wss[0].send_json({"action": "bid", "suit": "hearts"})
            msg = wss[0].receive_json()
            assert msg["type"] == "error"
            assert "passed" in msg["message"].lower()


# ---------------------------------------------------------------------------
# Disconnect / abort
# ---------------------------------------------------------------------------

class TestDisconnect:
    def test_disconnect_sends_game_aborted_to_remaining_player(self):
        """When one player disconnects, the other receives game_aborted."""
        client, _ = _client()
        room_id, [pid1, pid2] = _setup_room(client, n=2)

        with client.websocket_connect(f"/ws/{room_id}/{pid2}") as ws2:
            ws2.receive_json()  # room_update (pid2 alone)
            ws2.receive_json()  # game_state

            with client.websocket_connect(f"/ws/{room_id}/{pid1}") as ws1:
                ws1.receive_json()  # room_update (both players)
                ws1.receive_json()  # game_state
                # ws2 also receives updated room_update and game_state from ws1 joining
                ws2.receive_json()
                ws2.receive_json()
            # ws1 __exit__ closes connection → WebSocketDisconnect → abort_room
            msg = ws2.receive_json()
            assert msg["type"] == "game_aborted"

    def test_room_removed_after_abort(self):
        """After a disconnect, the room is removed from the manager."""
        client, manager = _client()
        room_id, [pid1, pid2] = _setup_room(client, n=2)

        with client.websocket_connect(f"/ws/{room_id}/{pid2}") as ws2:
            ws2.receive_json(); ws2.receive_json()
            with client.websocket_connect(f"/ws/{room_id}/{pid1}") as ws1:
                ws1.receive_json(); ws1.receive_json()
                ws2.receive_json(); ws2.receive_json()
            # ws1 disconnected → abort_room → room deleted
            ws2.receive_json()  # game_aborted
        assert manager.get_room(room_id) is None
