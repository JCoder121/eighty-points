"""Handler tests for the check_play action and the throw_failed broadcast.

These drive handle_message() directly with a fake WebSocket, avoiding the
full TestClient dance — check_play is a per-player, read-only classification
so no multi-connection choreography is needed.
"""
from __future__ import annotations

from shengji.engine.engine import GameEngine
from shengji.models.card import Card, Rank, Suit
from shengji.models.game_state import GamePhase, GameState
from shengji.models.player import Player
from shengji.models.trump import TrumpContext
from shengji.modes.upgrade import UpgradeStrategy
from shengji.network.handler import handle_message
from shengji.network.room import Room, RoomManager


class _FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, msg: dict) -> None:
        self.sent.append(msg)


A_S = Card(Suit.SPADES, Rank.ACE)
K_S = Card(Suit.SPADES, Rank.KING)
Q_S = Card(Suit.SPADES, Rank.QUEEN)
T_S = Card(Suit.SPADES, Rank.TEN)
N_S = Card(Suit.SPADES, Rank.NINE)
E_S = Card(Suit.SPADES, Rank.EIGHT)
S_S = Card(Suit.SPADES, Rank.SEVEN)
X_S = Card(Suit.SPADES, Rank.SIX)
F_S = Card(Suit.SPADES, Rank.FIVE)
FO_S = Card(Suit.SPADES, Rank.FOUR)
TH_S = Card(Suit.SPADES, Rank.THREE)


def _make_room() -> tuple[Room, dict[str, _FakeWS]]:
    players = [Player(id=f"p{i}", name=f"P{i}") for i in range(4)]
    state = GameState(players=players, mode="upgrade", round_leader_id="p0")
    state.phase = GamePhase.PLAYING
    state.trump_context = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS)
    state.tricks_won = {p.id: [] for p in players}
    state.current_turn_id = "p0"
    state.current_leader_id = "p0"
    hands = {
        "p0": [K_S, Q_S],
        "p1": [A_S, TH_S],
        "p2": [FO_S, F_S],
        "p3": [X_S, S_S],
    }
    for p in players:
        p.hand = list(hands[p.id])
    strategy = UpgradeStrategy()
    engine = GameEngine(state, strategy, deal_delay=0)
    strategy.assign_teams(state)

    room = Room(room_id="TESTRM", game_master_id="p0", game_state=state, engine=engine)
    conns = {p.id: _FakeWS() for p in players}
    room.connections.update(conns)
    return room, conns


async def _send(room: Room, player_id: str, data: dict) -> None:
    await handle_message(room, player_id, data, manager=RoomManager(), deal_delay=0)


def _of_type(ws: _FakeWS, msg_type: str) -> list[dict]:
    return [m for m in ws.sent if m.get("type") == msg_type]


class TestCheckPlay:
    async def test_leading_multi_card_throw_reports_is_throw(self):
        room, conns = _make_room()
        await _send(room, "p0", {
            "action": "check_play",
            "cards": [K_S.to_json(), Q_S.to_json()],
        })
        results = _of_type(conns["p0"], "check_play_result")
        assert results == [{"type": "check_play_result", "is_throw": True}]
        # Response goes to the asking player only.
        assert not _of_type(conns["p1"], "check_play_result")

    async def test_leading_pair_is_not_a_throw(self):
        room, conns = _make_room()
        await _send(room, "p0", {
            "action": "check_play",
            "cards": [K_S.to_json(), K_S.to_json()],
        })
        assert _of_type(conns["p0"], "check_play_result")[0]["is_throw"] is False

    async def test_single_card_is_not_a_throw(self):
        room, conns = _make_room()
        await _send(room, "p0", {
            "action": "check_play",
            "cards": [K_S.to_json()],
        })
        assert _of_type(conns["p0"], "check_play_result")[0]["is_throw"] is False

    async def test_follower_is_never_a_throw(self):
        room, conns = _make_room()
        room.game_state.current_trick = [("p3", [X_S])]
        await _send(room, "p0", {
            "action": "check_play",
            "cards": [K_S.to_json(), Q_S.to_json()],
        })
        assert _of_type(conns["p0"], "check_play_result")[0]["is_throw"] is False

    async def test_no_engine_reports_error(self):
        room, conns = _make_room()
        room.engine = None
        await _send(room, "p0", {"action": "check_play", "cards": []})
        assert _of_type(conns["p0"], "error")


class TestThrowFailedBroadcast:
    async def test_failed_throw_broadcasts_to_all_players(self):
        room, conns = _make_room()
        await _send(room, "p0", {
            "action": "play_cards",
            "cards": [K_S.to_json(), Q_S.to_json()],
        })
        for pid, ws in conns.items():
            msgs = _of_type(ws, "throw_failed")
            assert len(msgs) == 1, f"{pid} missing throw_failed"
            msg = msgs[0]
            assert msg["player_id"] == "p0"
            assert msg["player_name"] == "P0"
            assert msg["penalty"] == 20
            assert msg["forced_cards"] == [Q_S.to_json()]
            assert msg["attempted_cards"] == [K_S.to_json(), Q_S.to_json()]
        # The engine recorded the penalty and led only the forced card.
        assert room.game_state.throw_penalties == {"p0": 20}
        assert room.game_state.current_trick == [("p0", [Q_S])]

    async def test_valid_lead_does_not_broadcast_throw_failed(self):
        room, conns = _make_room()
        await _send(room, "p0", {"action": "play_cards", "cards": [K_S.to_json()]})
        for ws in conns.values():
            assert not _of_type(ws, "throw_failed")
