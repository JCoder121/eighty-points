"""Tests for superuser HTTP endpoints (M6.3)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shengji.models.card import Card, Rank, Suit
from shengji.models.deck import BOTTOM_SIZE, HAND_SIZE, NUM_PLAYERS
from shengji.models.game_state import GamePhase, GameState
from shengji.models.player import Player
from shengji.models.trump import TrumpContext
from shengji.superuser.api import SuperuserRoom, create_router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ROOM_ID = "TEST01"
GM_ID = "p0"
OTHER_ID = "p1"


def _make_players() -> list[Player]:
    return [Player(id=f"p{i}", name=f"Player{i}") for i in range(NUM_PLAYERS)]


def _make_game_state() -> GameState:
    from shengji.models.deck import Deck
    state = GameState(
        players=_make_players(),
        mode="upgrade",
        round_leader_id=GM_ID,
        phase=GamePhase.PLAYING,
        trump_context=TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS),
        current_turn_id=GM_ID,
    )
    deck = Deck()
    all_cards = list(deck._cards)
    state.bottom_deck = all_cards[:BOTTOM_SIZE]
    for i, p in enumerate(state.players):
        start = BOTTOM_SIZE + i * HAND_SIZE
        p.hand = all_cards[start : start + HAND_SIZE]
    state.tricks_won = {p.id: [] for p in state.players}
    return state


def _make_client(superuser_enabled: bool = True) -> tuple[TestClient, dict]:
    """Return a TestClient and the room store it uses."""
    rooms: dict[str, SuperuserRoom] = {}
    room = SuperuserRoom(
        room_id=ROOM_ID,
        game_master_id=GM_ID,
        game_state=_make_game_state(),
        superuser_enabled=superuser_enabled,
    )
    rooms[ROOM_ID] = room

    app = FastAPI()
    app.include_router(create_router(rooms))
    return TestClient(app), rooms


def _gm_headers() -> dict:
    return {"X-Player-Id": GM_ID}


def _other_headers() -> dict:
    return {"X-Player-Id": OTHER_ID}


# ---------------------------------------------------------------------------
# POST /superuser/enable/{room_id}
# ---------------------------------------------------------------------------

class TestEnableSuperuser:
    def test_enable_sets_flag(self):
        client, rooms = _make_client(superuser_enabled=False)
        resp = client.post(f"/superuser/enable/{ROOM_ID}", headers=_gm_headers())
        assert resp.status_code == 200
        assert rooms[ROOM_ID].superuser_enabled is True

    def test_enable_returns_ok(self):
        client, _ = _make_client(superuser_enabled=False)
        resp = client.post(f"/superuser/enable/{ROOM_ID}", headers=_gm_headers())
        assert resp.json()["ok"] is True

    def test_enable_idempotent(self):
        """Calling enable twice must not error."""
        client, _ = _make_client(superuser_enabled=True)
        resp = client.post(f"/superuser/enable/{ROOM_ID}", headers=_gm_headers())
        assert resp.status_code == 200

    def test_non_gm_cannot_enable(self):
        client, _ = _make_client(superuser_enabled=False)
        resp = client.post(f"/superuser/enable/{ROOM_ID}", headers=_other_headers())
        assert resp.status_code == 403

    def test_unknown_room_404(self):
        client, _ = _make_client()
        resp = client.post("/superuser/enable/NOPE", headers=_gm_headers())
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Access control — not enabled
# ---------------------------------------------------------------------------

class TestAccessControlNotEnabled:
    """Game master cannot use mutation endpoints before enabling."""

    def test_get_state_blocked_when_not_enabled(self):
        client, _ = _make_client(superuser_enabled=False)
        resp = client.get(f"/superuser/state/{ROOM_ID}", headers=_gm_headers())
        assert resp.status_code == 403

    def test_validate_blocked_when_not_enabled(self):
        client, _ = _make_client(superuser_enabled=False)
        resp = client.post(f"/superuser/validate/{ROOM_ID}", headers=_gm_headers())
        assert resp.status_code == 403

    def test_set_hand_blocked_when_not_enabled(self):
        client, _ = _make_client(superuser_enabled=False)
        body = {"player_id": "p0", "cards": [{"suit": "spades", "rank": "A"}]}
        resp = client.post(
            f"/superuser/set-hand/{ROOM_ID}", json=body, headers=_gm_headers()
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Access control — non-game-master
# ---------------------------------------------------------------------------

class TestAccessControlNonGM:
    def test_non_gm_cannot_get_state(self):
        client, _ = _make_client()
        resp = client.get(f"/superuser/state/{ROOM_ID}", headers=_other_headers())
        assert resp.status_code == 403

    def test_non_gm_cannot_set_hand(self):
        client, _ = _make_client()
        body = {"player_id": "p0", "cards": []}
        resp = client.post(
            f"/superuser/set-hand/{ROOM_ID}", json=body, headers=_other_headers()
        )
        assert resp.status_code == 403

    def test_non_gm_cannot_force_phase(self):
        client, _ = _make_client()
        body = {"phase": "scoring"}
        resp = client.post(
            f"/superuser/force-phase/{ROOM_ID}", json=body, headers=_other_headers()
        )
        assert resp.status_code == 403

    def test_non_gm_cannot_enable(self):
        client, _ = _make_client(superuser_enabled=False)
        resp = client.post(f"/superuser/enable/{ROOM_ID}", headers=_other_headers())
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /superuser/state/{room_id}
# ---------------------------------------------------------------------------

class TestGetState:
    def test_returns_full_state(self):
        client, _ = _make_client()
        resp = client.get(f"/superuser/state/{ROOM_ID}", headers=_gm_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "phase" in data
        assert "players" in data

    def test_all_hands_visible(self):
        client, _ = _make_client()
        resp = client.get(f"/superuser/state/{ROOM_ID}", headers=_gm_headers())
        for player_data in resp.json()["players"]:
            assert "hand" in player_data


# ---------------------------------------------------------------------------
# POST /superuser/validate/{room_id}
# ---------------------------------------------------------------------------

class TestValidate:
    def test_clean_state_returns_no_violations(self):
        client, _ = _make_client()
        resp = client.post(f"/superuser/validate/{ROOM_ID}", headers=_gm_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["violations"] == []

    def test_corrupted_state_returns_violations(self):
        client, rooms = _make_client()
        # Remove all cards from p0's hand without adjusting total
        rooms[ROOM_ID].game_state.players[0].hand = []
        resp = client.post(f"/superuser/validate/{ROOM_ID}", headers=_gm_headers())
        data = resp.json()
        assert data["valid"] is False
        assert len(data["violations"]) > 0


# ---------------------------------------------------------------------------
# POST /superuser/set-hand/{room_id}
# ---------------------------------------------------------------------------

class TestSetHand:
    def test_replaces_hand(self):
        client, rooms = _make_client()
        new_hand = [{"suit": "spades", "rank": "A"}, {"suit": "spades", "rank": "K"}]
        body = {"player_id": "p0", "cards": new_hand}
        resp = client.post(
            f"/superuser/set-hand/{ROOM_ID}", json=body, headers=_gm_headers()
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert len(rooms[ROOM_ID].game_state.players[0].hand) == 2

    def test_unknown_player_returns_400(self):
        client, _ = _make_client()
        body = {"player_id": "ghost", "cards": []}
        resp = client.post(
            f"/superuser/set-hand/{ROOM_ID}", json=body, headers=_gm_headers()
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /superuser/set-points/{room_id}
# ---------------------------------------------------------------------------

class TestSetPoints:
    def test_overrides_attacking_points(self):
        client, rooms = _make_client()
        body = {"attacking_points": 350}
        resp = client.post(
            f"/superuser/set-points/{ROOM_ID}", json=body, headers=_gm_headers()
        )
        assert resp.status_code == 200
        assert rooms[ROOM_ID].game_state.attacking_points == 350

    def test_negative_points_returns_warnings(self):
        client, _ = _make_client()
        body = {"attacking_points": -50}
        resp = client.post(
            f"/superuser/set-points/{ROOM_ID}", json=body, headers=_gm_headers()
        )
        data = resp.json()
        assert data["ok"] is True
        assert len(data["warnings"]) > 0


# ---------------------------------------------------------------------------
# POST /superuser/force-phase/{room_id}
# ---------------------------------------------------------------------------

class TestForcePhase:
    def test_changes_phase(self):
        client, rooms = _make_client()
        body = {"phase": "scoring"}
        resp = client.post(
            f"/superuser/force-phase/{ROOM_ID}", json=body, headers=_gm_headers()
        )
        assert resp.status_code == 200
        assert rooms[ROOM_ID].game_state.phase == GamePhase.SCORING

    def test_invalid_phase_returns_400(self):
        client, _ = _make_client()
        body = {"phase": "invalid_phase"}
        resp = client.post(
            f"/superuser/force-phase/{ROOM_ID}", json=body, headers=_gm_headers()
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /superuser/deal-specific/{room_id}
# ---------------------------------------------------------------------------

class TestDealSpecific:
    def _full_hands_and_bottom(self) -> tuple[dict, list]:
        from shengji.models.deck import Deck
        all_cards = list(Deck()._cards)
        bottom = [{"suit": c.suit.value, "rank": c.rank.value} for c in all_cards[:BOTTOM_SIZE]]
        hands = {}
        for i in range(NUM_PLAYERS):
            start = BOTTOM_SIZE + i * HAND_SIZE
            hands[f"p{i}"] = [
                {"suit": c.suit.value, "rank": c.rank.value}
                for c in all_cards[start : start + HAND_SIZE]
            ]
        return hands, bottom

    def test_deal_specific_sets_hands(self):
        client, rooms = _make_client()
        hands, bottom = self._full_hands_and_bottom()
        body = {"hands": hands, "bottom": bottom}
        resp = client.post(
            f"/superuser/deal-specific/{ROOM_ID}", json=body, headers=_gm_headers()
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # No warnings for a valid 108-card deal
        assert resp.json()["warnings"] == []

    def test_deal_specific_unknown_player_returns_400(self):
        client, _ = _make_client()
        body = {"hands": {"ghost": []}, "bottom": []}
        resp = client.post(
            f"/superuser/deal-specific/{ROOM_ID}", json=body, headers=_gm_headers()
        )
        assert resp.status_code == 400
