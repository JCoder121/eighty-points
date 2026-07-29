"""Handler tests for D26 — explicit single bids over the ``bid`` WS action.

Audit finding F4: the ``bid`` action auto-selected the strongest bid available in
the named suit, so a player holding two trump-rank cards of a suit could never
place a *single* bid even though R14 allows it.  D26 adds an optional ``count``
field (1 or 2); omitting it preserves the old auto-strongest behavior.

These drive handle_message() directly with a fake WebSocket (same approach as
test_check_play.py) so the hands are deterministic — the TestClient path deals
randomly and cannot guarantee a player holds a trump-rank pair.
"""
from __future__ import annotations

from shengji.engine.engine import GameEngine
from shengji.models.card import Card, Rank, Suit
from shengji.models.game_state import GamePhase, GameState
from shengji.models.player import Player
from shengji.modes.upgrade import UpgradeStrategy
from shengji.network.handler import handle_message
from shengji.network.room import Room, RoomManager


class _FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, msg: dict) -> None:
        self.sent.append(msg)


TRUMP_RANK = Rank.TWO          # every Player starts at rank TWO, so this is the round's trump rank
TWO_S = Card(Suit.SPADES, Rank.TWO)
TWO_H = Card(Suit.HEARTS, Rank.TWO)
SJ = Card(Suit.JOKER, Rank.SMALL_JOKER)
BJ = Card(Suit.JOKER, Rank.BIG_JOKER)

# p0 holds a spade pair (single or pair bid available) and a lone heart
# (single only); the small-joker pair covers the no-trump branch.
DEFAULT_HANDS = {
    "p0": [TWO_S, TWO_S, TWO_H, SJ, SJ],
    "p1": [],
    "p2": [],
    "p3": [],
}


def _make_bidding_room(hands: dict[str, list[Card]] | None = None):
    players = [Player(id=f"p{i}", name=f"P{i}") for i in range(4)]
    state = GameState(players=players, mode="upgrade", round_leader_id="p0")
    state.phase = GamePhase.BIDDING_AFTER_DEAL
    state.tricks_won = {p.id: [] for p in players}
    for p in players:
        p.hand = list((hands or DEFAULT_HANDS)[p.id])
    engine = GameEngine(state, UpgradeStrategy(), deal_delay=0)

    room = Room(room_id="TESTRM", game_master_id="p0", game_state=state, engine=engine)
    conns = {p.id: _FakeWS() for p in players}
    room.connections.update(conns)
    return room, conns


async def _send(room: Room, player_id: str, data: dict) -> None:
    await handle_message(room, player_id, data, manager=RoomManager(), deal_delay=0)


def _of_type(ws: _FakeWS, msg_type: str) -> list[dict]:
    return [m for m in ws.sent if m.get("type") == msg_type]


class TestExplicitBidCount:
    async def test_count_1_bids_a_single_while_holding_a_pair(self):
        """D26: the whole point — a pair-holder may show only one card."""
        room, conns = _make_bidding_room()
        await _send(room, "p0", {"action": "bid", "suit": "spades", "count": 1})

        assert not _of_type(conns["p0"], "error")
        assert len(room.game_state.bids) == 1
        bid = room.game_state.bids[-1]
        assert bid.cards == [TWO_S]
        assert bid.resulting_trump.trump_suit is Suit.SPADES
        # And the table was told about it.
        assert _of_type(conns["p1"], "game_state")[-1]["bids"][-1]["cards"] == [
            TWO_S.to_json()
        ]

    async def test_count_2_bids_the_pair(self):
        room, conns = _make_bidding_room()
        await _send(room, "p0", {"action": "bid", "suit": "spades", "count": 2})

        assert not _of_type(conns["p0"], "error")
        assert room.game_state.bids[-1].cards == [TWO_S, TWO_S]

    async def test_count_absent_still_auto_selects_the_pair(self):
        """Backward compatibility: older clients send no count and keep pairs."""
        room, conns = _make_bidding_room()
        await _send(room, "p0", {"action": "bid", "suit": "spades"})

        assert not _of_type(conns["p0"], "error")
        assert room.game_state.bids[-1].cards == [TWO_S, TWO_S]

    async def test_count_absent_falls_back_to_a_single(self):
        """Auto-strongest with only one card held is unchanged: a single."""
        room, conns = _make_bidding_room()
        await _send(room, "p0", {"action": "bid", "suit": "hearts"})

        assert not _of_type(conns["p0"], "error")
        assert room.game_state.bids[-1].cards == [TWO_H]

    async def test_count_1_with_a_single_card_held_is_accepted(self):
        room, conns = _make_bidding_room()
        await _send(room, "p0", {"action": "bid", "suit": "hearts", "count": 1})

        assert not _of_type(conns["p0"], "error")
        assert room.game_state.bids[-1].cards == [TWO_H]


class TestBidCountRejections:
    async def test_count_3_is_rejected_and_changes_no_state(self):
        room, conns = _make_bidding_room()
        await _send(room, "p0", {"action": "bid", "suit": "spades", "count": 3})

        assert _of_type(conns["p0"], "error")
        assert room.game_state.bids == []
        assert room.passed_in_bidding == set()

    async def test_count_0_is_rejected(self):
        room, conns = _make_bidding_room()
        await _send(room, "p0", {"action": "bid", "suit": "spades", "count": 0})

        assert _of_type(conns["p0"], "error")
        assert room.game_state.bids == []

    async def test_non_integer_count_is_rejected(self):
        room, conns = _make_bidding_room()
        await _send(room, "p0", {"action": "bid", "suit": "spades", "count": "1"})

        assert _of_type(conns["p0"], "error")
        assert room.game_state.bids == []

    async def test_count_2_without_holding_the_pair_is_rejected(self):
        room, conns = _make_bidding_room()
        await _send(room, "p0", {"action": "bid", "suit": "hearts", "count": 2})

        assert _of_type(conns["p0"], "error")
        assert room.game_state.bids == []

    async def test_count_1_without_holding_the_card_is_rejected(self):
        room, conns = _make_bidding_room()
        await _send(room, "p0", {"action": "bid", "suit": "clubs", "count": 1})

        assert _of_type(conns["p0"], "error")
        assert room.game_state.bids == []


class TestJokerBidCount:
    async def test_joker_bid_with_count_1_is_rejected(self):
        """R14: a single joker is never a legal bid."""
        room, conns = _make_bidding_room()
        await _send(room, "p0", {"action": "bid", "joker": "small", "count": 1})

        assert _of_type(conns["p0"], "error")
        assert room.game_state.bids == []

    async def test_joker_bid_with_count_2_is_accepted(self):
        room, conns = _make_bidding_room()
        await _send(room, "p0", {"action": "bid", "joker": "small", "count": 2})

        assert not _of_type(conns["p0"], "error")
        assert room.game_state.bids[-1].cards == [SJ, SJ]
        assert room.game_state.bids[-1].resulting_trump.trump_suit is None

    async def test_joker_bid_without_count_is_unchanged(self):
        room, conns = _make_bidding_room()
        await _send(room, "p0", {"action": "bid", "joker": "small"})

        assert not _of_type(conns["p0"], "error")
        assert room.game_state.bids[-1].cards == [SJ, SJ]
