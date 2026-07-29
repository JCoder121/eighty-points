"""A room created with a seed deals deterministically.

The optional ``seed`` on POST /rooms creates one ``random.Random`` shared by
every round's engine, so the same seed replays the same session of deals —
the web-game counterpart of ``play_cli.py --seed``.
"""
from __future__ import annotations

from contextlib import ExitStack

from tests.test_network.test_websocket import _client, _setup_deal


def _room_with_seed(client, seed):
    resp = client.post("/rooms", json={"name": "P0", "seed": seed})
    d = resp.json()
    room_id, pids = d["room_id"], [d["player_id"]]
    for i in range(1, 4):
        pids.append(
            client.post(f"/rooms/{room_id}/join", json={"name": f"P{i}"}).json()[
                "player_id"
            ]
        )
    return room_id, pids


def _dealt_hand_sizes_and_first_state(client, manager, seed):
    room_id, pids = _room_with_seed(client, seed)
    with ExitStack() as stack:
        _setup_deal(stack, client, room_id, pids)
        state = manager.get_room(room_id).game_state
        return [tuple(sorted(repr(c) for c in p.hand)) for p in state.players]


class TestSeededRooms:
    def test_same_seed_same_deal(self):
        client_a, mgr_a = _client()
        client_b, mgr_b = _client()
        hands_a = _dealt_hand_sizes_and_first_state(client_a, mgr_a, seed=42)
        hands_b = _dealt_hand_sizes_and_first_state(client_b, mgr_b, seed=42)
        assert hands_a == hands_b

    def test_different_seed_different_deal(self):
        client_a, mgr_a = _client()
        client_b, mgr_b = _client()
        hands_a = _dealt_hand_sizes_and_first_state(client_a, mgr_a, seed=1)
        hands_b = _dealt_hand_sizes_and_first_state(client_b, mgr_b, seed=2)
        assert hands_a != hands_b

    def test_no_seed_still_works(self):
        client, mgr = _client()
        resp = client.post("/rooms", json={"name": "P0"})
        assert resp.status_code == 200
        room = mgr.get_room(resp.json()["room_id"])
        assert room.rng is None
