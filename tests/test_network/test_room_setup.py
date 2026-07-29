"""Resume-at-levels lobby setup (Design A1, 2026-07-29 assessment §2.5).

A room may be created with a ``setup`` block that fixes each *seat*'s
starting level, which seat leads, and the round number — enough to resume a
session that ended between rounds (§6 ruling 2).  Seats are used rather than
player ids because only the game master exists when the room is created.
"""
from __future__ import annotations

import json
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient

from shengji.models.card import Rank
from shengji.models.game_state import GamePhase
from shengji.network.app import create_app
from shengji.network.room import NUM_PLAYERS, RoomManager, RoomSetup, apply_setup


def _client() -> tuple[TestClient, RoomManager]:
    manager = RoomManager()
    app = create_app(manager=manager, deal_delay=0, mount_static=False)
    return TestClient(app), manager


SETUP_BODY = {
    "starting_ranks": ["5", "5", "K", "K"],
    "starting_leader_seat": 2,
    "starting_round_number": 7,
}


def _fill(client: TestClient, room_id: str) -> list[str]:
    """Add the remaining 3 players; return all 4 player ids in seat order."""
    return [
        client.post(f"/rooms/{room_id}/join", json={"name": f"P{i}"}).json()["player_id"]
        for i in range(1, NUM_PLAYERS)
    ]


# ---------------------------------------------------------------------------
# RoomSetup.from_json — validation
# ---------------------------------------------------------------------------

class TestRoomSetupValidation:
    def test_full_payload_parses(self):
        setup = RoomSetup.from_json(SETUP_BODY)
        assert setup.starting_ranks == (Rank.FIVE, Rank.FIVE, Rank.KING, Rank.KING)
        assert setup.starting_leader_seat == 2
        assert setup.starting_round_number == 7

    def test_leader_seat_and_round_number_default(self):
        setup = RoomSetup.from_json({"starting_ranks": ["2", "3", "4", "5"]})
        assert setup.starting_leader_seat == 0
        # A resumed game is not on its first round.
        assert setup.starting_round_number == 2

    def test_round_trips_through_json(self):
        setup = RoomSetup.from_json(SETUP_BODY)
        assert RoomSetup.from_json(setup.to_json()) == setup

    @pytest.mark.parametrize("ranks", [
        ["5", "5", "K"],                 # too few
        ["5", "5", "K", "K", "K"],       # too many
        "5555",                          # not a list
        None,                            # missing
    ])
    def test_rank_list_must_have_one_entry_per_seat(self, ranks):
        with pytest.raises(ValueError, match="starting_ranks"):
            RoomSetup.from_json({"starting_ranks": ranks})

    def test_unknown_rank_rejected(self):
        with pytest.raises(ValueError, match="Unknown rank"):
            RoomSetup.from_json({"starting_ranks": ["5", "5", "K", "Z"]})

    def test_joker_is_not_a_playable_level(self):
        with pytest.raises(ValueError, match="not a playable level"):
            RoomSetup.from_json({"starting_ranks": ["5", "5", "K", "BJ"]})

    def test_ace_is_a_playable_level(self):
        setup = RoomSetup.from_json({"starting_ranks": ["A", "A", "A", "A"]})
        assert setup.starting_ranks == (Rank.ACE,) * NUM_PLAYERS

    @pytest.mark.parametrize("seat", [-1, 4, 99, "2", True, 1.5])
    def test_bad_leader_seat_rejected(self, seat):
        with pytest.raises(ValueError, match="starting_leader_seat"):
            RoomSetup.from_json({
                "starting_ranks": ["2", "2", "2", "2"],
                "starting_leader_seat": seat,
            })

    @pytest.mark.parametrize("n", [0, -3, "7", True])
    def test_bad_round_number_rejected(self, n):
        with pytest.raises(ValueError, match="starting_round_number"):
            RoomSetup.from_json({
                "starting_ranks": ["2", "2", "2", "2"],
                "starting_round_number": n,
            })

    def test_non_object_rejected(self):
        with pytest.raises(ValueError):
            RoomSetup.from_json(["5", "5", "K", "K"])


# ---------------------------------------------------------------------------
# POST /rooms — the setup block is optional
# ---------------------------------------------------------------------------

class TestCreateRoomWithSetup:
    def test_no_setup_leaves_room_unconfigured(self):
        client, manager = _client()
        data = client.post("/rooms", json={"name": "Alice"}).json()
        room = manager.get_room(data["room_id"])
        assert data["setup"] is None
        assert room.setup is None
        assert room.game_state.players[0].rank == Rank.TWO
        assert room.game_state.round_number == 1
        assert room.game_state.leader_predetermined is False

    def test_setup_is_stored_and_echoed(self):
        client, manager = _client()
        resp = client.post("/rooms", json={"name": "Alice", "setup": SETUP_BODY})
        assert resp.status_code == 200
        assert resp.json()["setup"] == SETUP_BODY
        assert manager.get_room(resp.json()["room_id"]).setup == RoomSetup.from_json(
            SETUP_BODY
        )

    def test_game_master_gets_seat_zero_rank_immediately(self):
        client, manager = _client()
        room_id = client.post(
            "/rooms", json={"name": "Alice", "setup": SETUP_BODY}
        ).json()["room_id"]
        assert manager.get_room(room_id).game_state.players[0].rank == Rank.FIVE

    def test_invalid_setup_returns_400_with_reason(self):
        client, manager = _client()
        resp = client.post("/rooms", json={
            "name": "Alice",
            "setup": {"starting_ranks": ["5", "5", "K", "BJ"]},
        })
        assert resp.status_code == 400
        assert "not a playable level" in resp.json()["detail"]
        assert manager.all_room_ids() == []  # no half-configured room left behind


# ---------------------------------------------------------------------------
# Application by seat as players join
# ---------------------------------------------------------------------------

class TestSetupAppliedBySeat:
    def _room(self):
        client, manager = _client()
        d = client.post("/rooms", json={"name": "Alice", "setup": SETUP_BODY}).json()
        ids = [d["player_id"]] + _fill(client, d["room_id"])
        return manager.get_room(d["room_id"]), ids

    def test_every_seat_gets_its_configured_rank(self):
        room, _ = self._room()
        assert [p.rank for p in room.game_state.players] == [
            Rank.FIVE, Rank.FIVE, Rank.KING, Rank.KING
        ]

    def test_configured_seat_leads(self):
        room, ids = self._room()
        assert room.game_state.round_leader_id == ids[2]
        assert room.game_state.leader_predetermined is True

    def test_round_number_is_restored(self):
        room, _ = self._room()
        assert room.game_state.round_number == 7

    def test_leader_not_assigned_until_that_seat_is_filled(self):
        client, manager = _client()
        d = client.post("/rooms", json={"name": "Alice", "setup": SETUP_BODY}).json()
        room = manager.get_room(d["room_id"])
        # Seat 2 is still empty — nothing to point round_leader_id at yet.
        assert room.game_state.round_leader_id == d["player_id"]
        assert room.game_state.leader_predetermined is False
        client.post(f"/rooms/{d['room_id']}/join", json={"name": "B"})
        assert room.game_state.leader_predetermined is False
        p2 = client.post(
            f"/rooms/{d['room_id']}/join", json={"name": "C"}
        ).json()["player_id"]
        assert room.game_state.round_leader_id == p2
        assert room.game_state.leader_predetermined is True

    def test_apply_setup_is_a_no_op_once_the_game_has_started(self):
        """The lobby re-applies on every roster change; a started game must
        never have its ranks or round number rewritten underneath it."""
        room, _ = self._room()
        room.game_state.phase = GamePhase.PLAYING
        room.game_state.round_number = 9
        room.game_state.players[0].rank = Rank.ACE
        apply_setup(room.game_state, room.setup)
        assert room.game_state.round_number == 9
        assert room.game_state.players[0].rank == Rank.ACE


# ---------------------------------------------------------------------------
# End to end: a resumed room deals its first round as the configured round
# ---------------------------------------------------------------------------

class TestResumedGameStarts:
    def _play_to_deal(self, client, manager, room_id, pids):
        """Connect all 4 and let the auto-start deal run (see test_websocket
        for why select_mode goes out before the other three connect)."""
        room = manager.get_room(room_id)
        with ExitStack() as stack:
            ws0 = stack.enter_context(
                client.websocket_connect(f"/ws/{room_id}/{pids[0]}")
            )
            ws0.send_json({"action": "select_mode", "mode": "upgrade"})
            for pid in pids[1:]:
                stack.enter_context(client.websocket_connect(f"/ws/{room_id}/{pid}"))
            for _ in range(500):
                msg = ws0.receive_json()
                if msg.get("phase") == GamePhase.BIDDING_AFTER_DEAL.value:
                    return room, msg
            raise AssertionError("never reached BIDDING_AFTER_DEAL")

    def _resumed_room(self, client, manager):
        d = client.post("/rooms", json={"name": "Alice", "setup": SETUP_BODY}).json()
        return d["room_id"], [d["player_id"]] + _fill(client, d["room_id"])

    def test_configured_leader_and_round_survive_the_deal(self):
        client, manager = _client()
        room_id, pids = self._resumed_room(client, manager)
        room, view = self._play_to_deal(client, manager, room_id, pids)
        assert view["round_leader_id"] == pids[2]
        assert view["round_number"] == 7
        assert [p["rank"] for p in view["players"]] == ["5", "5", "K", "K"]

    def test_deal_starts_from_the_seat_after_the_configured_leader(self):
        """The leader is dealt last (D-order starts at leader+1), so a wrong
        leader shows up as a rotated hand-size sequence mid-deal."""
        client, manager = _client()
        room_id, pids = self._resumed_room(client, manager)
        room, _ = self._play_to_deal(client, manager, room_id, pids)
        assert room.game_state.round_leader_id == pids[2]
        assert all(len(p.hand) == 25 for p in room.game_state.players)

    def test_resume_is_recorded_in_the_game_log(self, tmp_path, monkeypatch):
        """A log that opens at round 7 with players at K has to explain
        itself — GameLogger writes relative to the cwd, so redirect it."""
        monkeypatch.chdir(tmp_path)
        client, manager = _client()
        room_id, pids = self._resumed_room(client, manager)
        room, _ = self._play_to_deal(client, manager, room_id, pids)
        room.logger.close()

        log_file = next((tmp_path / "logs" / "games").iterdir())
        entries = [json.loads(line) for line in log_file.read_text().splitlines()]
        resume = next(e for e in entries if e["event"] == "resume_setup")
        assert resume["setup"] == SETUP_BODY
        assert resume["round_leader_id"] == pids[2]
        assert [p["rank"] for p in resume["players"]] == ["5", "5", "K", "K"]
        assert resume["seq"] == 0  # first line in the file

    def test_an_ordinary_game_logs_no_resume_entry(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        client, manager = _client()
        d = client.post("/rooms", json={"name": "Alice"}).json()
        pids = [d["player_id"]] + _fill(client, d["room_id"])
        room, _ = self._play_to_deal(client, manager, d["room_id"], pids)
        room.logger.close()

        log_file = next((tmp_path / "logs" / "games").iterdir())
        entries = [json.loads(line) for line in log_file.read_text().splitlines()]
        assert not [e for e in entries if e["event"] == "resume_setup"]
