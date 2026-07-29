"""A malformed WebSocket frame must not destroy the room.

Found by live-server WS fuzz (Session 27): ``receive_json()`` sat outside the
containment try in ``handle_connection``, so one non-JSON text frame from any
client raised into the outer exception handler and aborted the whole 4-player
room.  Variant: valid JSON that is not an object (a list or string) survived
parsing, then ``data.get`` raised AttributeError inside the containment
LOGGING path and escaped to the same room-killing handler.

The connection loop now parses frames itself: unparseable or non-object frames
get a per-player error message and the connection lives on.

These pins use a single-connection room: with 4 concurrent TestClient portal
sessions the same scenario deadlocks inside pytest's collection context (it
passes standalone and against a live uvicorn — verified during Session 27's
fuzz run), and one connection is sufficient to pin the regression: pre-fix,
the malformed frame kills THIS connection's loop and aborts the room, so the
follow-up valid action would never get a reply.
"""
from __future__ import annotations

from tests.test_network.test_websocket import _client, _next_of_type, _setup_room


def _connected(client):
    resp = client.post("/rooms", json={"name": "P0"})
    d = resp.json()
    return d["room_id"], d["player_id"]


class TestMalformedFramesDoNotKillTheRoom:
    def test_non_json_frame_gets_error_and_connection_survives(self):
        client, manager = _client()
        room_id, pid = _connected(client)
        with client.websocket_connect(f"/ws/{room_id}/{pid}") as ws:
            ws.receive_json()  # room_update
            ws.receive_json()  # game_state
            ws.send_text("this is not json {{{")
            err = _next_of_type(ws, "error")
            assert "not valid JSON" in err["message"]
            # The connection loop is still alive: a valid action gets a reply
            # (pre-fix, the room was aborted and nothing would ever arrive).
            ws.send_json({"action": "select_mode", "mode": "upgrade"})
            msg = _next_of_type(ws, "room_update")
            assert msg["type"] == "room_update"
            # The room was not torn down.
            assert manager.get_room(room_id) is not None

    def test_json_non_object_frames_get_error_and_connection_survives(self):
        client, manager = _client()
        room_id, pid = _connected(client)
        with client.websocket_connect(f"/ws/{room_id}/{pid}") as ws:
            ws.receive_json()  # room_update
            ws.receive_json()  # game_state
            ws.send_text('["valid", "json", "wrong", "shape"]')
            err = _next_of_type(ws, "error")
            assert "JSON object" in err["message"]
            ws.send_text('"just a string"')
            err = _next_of_type(ws, "error")
            assert "JSON object" in err["message"]
            ws.send_json({"action": "select_mode", "mode": "find_friends"})
            msg = _next_of_type(ws, "room_update")
            assert msg["type"] == "room_update"
            assert manager.get_room(room_id) is not None
