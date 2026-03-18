"""Tests for UpgradeStrategy (M5.3)."""
from __future__ import annotations

import pytest

from shengji.models.card import Card, Rank, Suit
from shengji.models.game_state import GameState
from shengji.models.player import Player
from shengji.modes.upgrade import UpgradeStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_players(n: int = 4) -> list[Player]:
    return [Player(id=f"p{i}", name=f"Player{i}") for i in range(n)]


def _make_state(leader_id: str = "p0") -> GameState:
    return GameState(
        players=_make_players(),
        mode="upgrade",
        round_leader_id=leader_id,
    )


strategy = UpgradeStrategy()


# ---------------------------------------------------------------------------
# assign_teams
# ---------------------------------------------------------------------------

class TestAssignTeams:
    def test_leader_seat0_seats02_defend(self):
        state = _make_state("p0")
        strategy.assign_teams(state)
        assert state.players[0].is_defending is True   # p0
        assert state.players[1].is_defending is False  # p1
        assert state.players[2].is_defending is True   # p2
        assert state.players[3].is_defending is False  # p3

    def test_leader_seat1_seats13_defend(self):
        state = _make_state("p1")
        strategy.assign_teams(state)
        assert state.players[0].is_defending is False  # p0
        assert state.players[1].is_defending is True   # p1
        assert state.players[2].is_defending is False  # p2
        assert state.players[3].is_defending is True   # p3

    def test_leader_seat2_seats02_defend(self):
        """Same as seat 0 — same parity."""
        state = _make_state("p2")
        strategy.assign_teams(state)
        assert state.players[0].is_defending is True
        assert state.players[2].is_defending is True
        assert state.players[1].is_defending is False
        assert state.players[3].is_defending is False

    def test_leader_seat3_seats13_defend(self):
        """Same as seat 1 — same parity."""
        state = _make_state("p3")
        strategy.assign_teams(state)
        assert state.players[1].is_defending is True
        assert state.players[3].is_defending is True
        assert state.players[0].is_defending is False
        assert state.players[2].is_defending is False

    def test_team_labels_set(self):
        state = _make_state("p0")
        strategy.assign_teams(state)
        assert state.players[0].team == "defending"
        assert state.players[1].team == "attacking"
        assert state.players[2].team == "defending"
        assert state.players[3].team == "attacking"

    def test_get_attacker_ids_after_assign(self):
        state = _make_state("p0")
        strategy.assign_teams(state)
        attackers = strategy.get_attacker_ids(state)
        assert attackers == {"p1", "p3"}

    def test_get_attacker_ids_when_leader_at_seat1(self):
        state = _make_state("p1")
        strategy.assign_teams(state)
        attackers = strategy.get_attacker_ids(state)
        assert attackers == {"p0", "p2"}


# ---------------------------------------------------------------------------
# needs_friend_declaration / validate_friend_declaration
# ---------------------------------------------------------------------------

class TestFriendDeclaration:
    def test_needs_friend_declaration_false(self):
        assert strategy.needs_friend_declaration() is False

    def test_validate_friend_declaration_raises(self):
        state = _make_state()
        with pytest.raises(ValueError, match="not used"):
            strategy.validate_friend_declaration(state, [])

    def test_resolve_friend_noop(self):
        state = _make_state("p0")
        strategy.assign_teams(state)
        # resolve_friend should not raise or change state
        card = Card(suit=Suit.SPADES, rank=Rank.ACE)
        strategy.resolve_friend(state, "p1", card)
        # is_defending unchanged
        assert state.players[0].is_defending is True
        assert state.players[1].is_defending is False


# ---------------------------------------------------------------------------
# on_round_end
# ---------------------------------------------------------------------------

class TestOnRoundEnd:
    def _setup(self, leader_id: str = "p0") -> GameState:
        state = _make_state(leader_id)
        strategy.assign_teams(state)
        return state

    def test_defenders_win_roles_unchanged(self):
        state = self._setup("p0")
        # p0,p2 defending; p1,p3 attacking
        strategy.on_round_end(state, "defending")
        assert state.players[0].is_defending is True
        assert state.players[1].is_defending is False
        assert state.players[2].is_defending is True
        assert state.players[3].is_defending is False

    def test_attackers_win_roles_swapped(self):
        state = self._setup("p0")
        strategy.on_round_end(state, "attacking")
        # Former attackers (p1, p3) are now defenders
        assert state.players[0].is_defending is False
        assert state.players[1].is_defending is True
        assert state.players[2].is_defending is False
        assert state.players[3].is_defending is True

    def test_attackers_win_team_labels_updated(self):
        state = self._setup("p0")
        strategy.on_round_end(state, "attacking")
        assert state.players[1].team == "defending"
        assert state.players[0].team == "attacking"


# ---------------------------------------------------------------------------
# get_next_leader
# ---------------------------------------------------------------------------

class TestGetNextLeader:
    def _setup(self, leader_id: str = "p0") -> GameState:
        state = _make_state(leader_id)
        strategy.assign_teams(state)
        return state

    def test_defenders_win_next_defender_from_p0(self):
        """p0 leads, defenders win → next defender counter-clockwise is p2."""
        state = self._setup("p0")
        strategy.on_round_end(state, "defending")
        # Defenders are p0, p2. Counter-clockwise from p0 → next is p1 (skip, attacker)
        # → then p2 (defender). So next leader = p2.
        next_leader = strategy.get_next_leader(state, "defending")
        assert next_leader == "p2"

    def test_defenders_win_next_defender_from_p2(self):
        """p2 leads, defenders win → next defender counter-clockwise is p0."""
        state = _make_state("p2")
        strategy.assign_teams(state)
        strategy.on_round_end(state, "defending")
        # Defenders are p0, p2. From p2: next (p3 attacker), then p0 (defender).
        next_leader = strategy.get_next_leader(state, "defending")
        assert next_leader == "p0"

    def test_attackers_win_next_new_defender_from_p0(self):
        """p0 leads, attackers (p1,p3) win → after swap defenders are p1,p3.
        From p0, counter-clockwise: p1 is now a defender → next leader = p1."""
        state = self._setup("p0")
        strategy.on_round_end(state, "attacking")
        next_leader = strategy.get_next_leader(state, "attacking")
        assert next_leader == "p1"

    def test_attackers_win_next_new_defender_from_p1(self):
        """p1 leads (so p1,p3 originally defend), attackers (p0,p2) win.
        After swap, p0 and p2 become defenders.
        From p1: next is p2 (defender) → next leader = p2."""
        state = _make_state("p1")
        strategy.assign_teams(state)
        strategy.on_round_end(state, "attacking")
        next_leader = strategy.get_next_leader(state, "attacking")
        assert next_leader == "p2"

    def test_full_rotation_covers_all_seats(self):
        """After 4 rounds of defenders winning, leadership visits all 4 players."""
        # p0 leads initially, defenders are p0,p2
        # Round 1 (def wins): p0 → p2
        # Round 2 (def wins): p2 → p0
        # This is a 2-seat rotation; the other pair stays as attackers.
        state = _make_state("p0")
        strategy.assign_teams(state)

        visited = []
        for _ in range(4):
            visited.append(state.round_leader_id)
            strategy.on_round_end(state, "defending")
            next_id = strategy.get_next_leader(state, "defending")
            state.round_leader_id = next_id

        # Leaders should alternate p0 → p2 → p0 → p2
        assert visited == ["p0", "p2", "p0", "p2"]
