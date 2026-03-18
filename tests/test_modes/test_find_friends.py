"""Tests for FindFriendsStrategy (M5.4)."""
from __future__ import annotations

import pytest

from shengji.models.card import Card, Rank, Suit
from shengji.models.friend_declaration import FriendDeclaration
from shengji.models.game_state import GameState
from shengji.models.player import Player
from shengji.models.trump import TrumpContext
from shengji.modes.find_friends import FindFriendsStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_players(n: int = 4) -> list[Player]:
    return [Player(id=f"p{i}", name=f"Player{i}") for i in range(n)]


def _make_state(
    leader_id: str = "p0",
    trump_rank: Rank = Rank.TWO,
    trump_suit: Suit | None = Suit.HEARTS,
) -> GameState:
    return GameState(
        players=_make_players(),
        mode="find_friends",
        round_leader_id=leader_id,
        trump_context=TrumpContext(trump_rank=trump_rank, trump_suit=trump_suit),
    )


def _decl(card: Card, ordinal: int = 1) -> FriendDeclaration:
    return FriendDeclaration(card=card, ordinal=ordinal)


A_S = Card(Suit.SPADES, Rank.ACE)
K_S = Card(Suit.SPADES, Rank.KING)
A_D = Card(Suit.DIAMONDS, Rank.ACE)
TWO_S = Card(Suit.SPADES, Rank.TWO)   # trump rank when trump_rank=2
SJ = Card(Suit.JOKER, Rank.SMALL_JOKER)
BJ = Card(Suit.JOKER, Rank.BIG_JOKER)


# ---------------------------------------------------------------------------
# assign_teams
# ---------------------------------------------------------------------------

class TestAssignTeams:
    def setup_method(self):
        self.strategy = FindFriendsStrategy()

    def test_leader_defends_alone(self):
        state = _make_state("p0")
        self.strategy.assign_teams(state)
        assert state.players[0].is_defending is True
        assert state.players[1].is_defending is False
        assert state.players[2].is_defending is False
        assert state.players[3].is_defending is False

    def test_non_leaders_attack(self):
        state = _make_state("p2")
        self.strategy.assign_teams(state)
        assert state.players[2].is_defending is True
        for i in [0, 1, 3]:
            assert state.players[i].is_defending is False

    def test_team_labels_set(self):
        state = _make_state("p0")
        self.strategy.assign_teams(state)
        assert state.players[0].team == "defending"
        for i in [1, 2, 3]:
            assert state.players[i].team == "attacking"

    def test_play_counts_reset_on_assign(self):
        """assign_teams() should reset internal play-count state."""
        state = _make_state("p0")
        # Simulate some leftover state from a previous round
        self.strategy._play_counts[(Suit.SPADES, Rank.ACE)] = 2
        self.strategy.assign_teams(state)
        assert self.strategy._play_counts == {}


# ---------------------------------------------------------------------------
# needs_friend_declaration
# ---------------------------------------------------------------------------

def test_needs_friend_declaration_true():
    assert FindFriendsStrategy().needs_friend_declaration() is True


# ---------------------------------------------------------------------------
# validate_friend_declaration
# ---------------------------------------------------------------------------

class TestValidateFriendDeclaration:
    def setup_method(self):
        self.strategy = FindFriendsStrategy()

    def test_valid_single_declaration_accepted(self):
        state = _make_state()
        self.strategy.validate_friend_declaration(state, [_decl(A_S)])

    def test_zero_declarations_raises(self):
        state = _make_state()
        with pytest.raises(ValueError, match="exactly 1"):
            self.strategy.validate_friend_declaration(state, [])

    def test_two_declarations_raises_for_4_players(self):
        state = _make_state()
        with pytest.raises(ValueError, match="exactly 1"):
            self.strategy.validate_friend_declaration(state, [_decl(A_S), _decl(K_S)])

    def test_joker_declaration_raises(self):
        state = _make_state()
        with pytest.raises(ValueError, match="joker"):
            self.strategy.validate_friend_declaration(state, [_decl(SJ)])

    def test_big_joker_declaration_raises(self):
        state = _make_state()
        with pytest.raises(ValueError, match="joker"):
            self.strategy.validate_friend_declaration(state, [_decl(BJ)])

    def test_trump_rank_card_raises(self):
        # trump_rank=2, so TWO♠ is a trump-rank card
        state = _make_state(trump_rank=Rank.TWO)
        with pytest.raises(ValueError, match="trump-rank"):
            self.strategy.validate_friend_declaration(state, [_decl(TWO_S)])

    def test_leader_can_declare_own_card(self):
        """Leader is allowed to declare a card they hold (becomes own friend)."""
        state = _make_state("p0")
        state.players[0].hand = [A_S]  # leader holds A♠
        # Should not raise — this is an intentional edge case
        self.strategy.validate_friend_declaration(state, [_decl(A_S)])

    def test_no_trump_context_skips_trump_rank_check(self):
        """If trump_context is None, the trump-rank restriction is skipped."""
        state = _make_state()
        state.trump_context = None
        # TWO_S would normally be banned — but no context so no restriction
        self.strategy.validate_friend_declaration(state, [_decl(TWO_S)])


# ---------------------------------------------------------------------------
# resolve_friend
# ---------------------------------------------------------------------------

class TestResolveFriend:
    def setup_method(self):
        self.strategy = FindFriendsStrategy()

    def _setup(self, leader_id: str = "p0") -> GameState:
        state = _make_state(leader_id)
        self.strategy.assign_teams(state)
        return state

    def test_non_matching_card_noop(self):
        state = self._setup()
        state.friend_declarations = [_decl(A_S)]
        self.strategy.resolve_friend(state, "p1", K_S)  # K♠ ≠ A♠
        assert state.players[1].is_defending is False
        assert state.revealed_friends == set()

    def test_first_occurrence_triggers_ordinal_1(self):
        state = self._setup()
        state.friend_declarations = [_decl(A_S, ordinal=1)]
        self.strategy.resolve_friend(state, "p1", A_S)
        assert state.players[1].is_defending is True
        assert "p1" in state.revealed_friends
        assert state.friend_declarations[0].resolved_player_id == "p1"

    def test_second_occurrence_triggers_ordinal_2(self):
        state = self._setup()
        state.friend_declarations = [_decl(A_S, ordinal=2)]
        # First play does NOT trigger
        self.strategy.resolve_friend(state, "p1", A_S)
        assert state.players[1].is_defending is False
        # Second play triggers
        self.strategy.resolve_friend(state, "p2", A_S)
        assert state.players[2].is_defending is True
        assert "p2" in state.revealed_friends

    def test_ordinal_1_and_2_sequential(self):
        """Two declarations for the same card with ordinals 1 and 2."""
        state = self._setup()
        state.friend_declarations = [_decl(A_S, ordinal=1), _decl(A_S, ordinal=2)]
        # First A♠: triggers ordinal=1
        self.strategy.resolve_friend(state, "p1", A_S)
        assert state.players[1].is_defending is True
        # Second A♠: triggers ordinal=2
        self.strategy.resolve_friend(state, "p2", A_S)
        assert state.players[2].is_defending is True

    def test_leader_plays_declared_card_becomes_own_friend(self):
        """Edge case: leader plays their own declared card → 1v3."""
        state = self._setup("p0")
        state.friend_declarations = [_decl(A_S, ordinal=1)]
        self.strategy.resolve_friend(state, "p0", A_S)
        assert state.players[0].is_defending is True  # still defending (was already)
        assert "p0" in state.revealed_friends
        assert state.friend_declarations[0].resolved_player_id == "p0"

    def test_already_resolved_declaration_skipped(self):
        """A resolved declaration cannot be triggered again."""
        state = self._setup()
        decl = _decl(A_S, ordinal=1)
        decl.resolved_player_id = "p1"  # already resolved
        state.friend_declarations = [decl]
        state.revealed_friends.add("p1")
        # Playing A♠ again should not re-trigger
        self.strategy.resolve_friend(state, "p2", A_S)
        assert "p2" not in state.revealed_friends

    def test_friend_team_label_updated(self):
        state = self._setup()
        state.friend_declarations = [_decl(A_S)]
        self.strategy.resolve_friend(state, "p1", A_S)
        assert state.players[1].team == "defending"


# ---------------------------------------------------------------------------
# on_round_end
# ---------------------------------------------------------------------------

def test_on_round_end_noop():
    strategy = FindFriendsStrategy()
    state = _make_state("p0")
    strategy.assign_teams(state)
    # on_round_end should not raise or change is_defending
    strategy.on_round_end(state, "defending")
    assert state.players[0].is_defending is True
    assert state.players[1].is_defending is False


# ---------------------------------------------------------------------------
# get_next_leader
# ---------------------------------------------------------------------------

class TestGetNextLeader:
    def setup_method(self):
        self.strategy = FindFriendsStrategy()

    def _setup_with_friend(self, leader: str, friend: str) -> GameState:
        """Leader and friend defend; other two attack."""
        state = _make_state(leader)
        self.strategy.assign_teams(state)
        # Manually reveal a friend
        friend_player = next(p for p in state.players if p.id == friend)
        friend_player.is_defending = True
        friend_player.team = "defending"
        state.revealed_friends.add(friend)
        return state

    def test_defenders_win_next_leader_from_defenders(self):
        """p0 + p2 defend, defenders win → next leader from {p0,p2}."""
        state = self._setup_with_friend("p0", "p2")
        next_id = self.strategy.get_next_leader(state, "defending")
        # From p0, counter-clockwise: p1 (not defender), p2 (defender)
        assert next_id == "p2"

    def test_attackers_win_next_leader_from_attackers(self):
        """p0 defends alone (no friend revealed), attackers win → from p1,p2,p3."""
        state = _make_state("p0")
        self.strategy.assign_teams(state)
        next_id = self.strategy.get_next_leader(state, "attacking")
        # From p0, counter-clockwise: p1 (attacker) → first attacker
        assert next_id == "p1"

    def test_next_leader_wraps_around(self):
        """From the last seat, wraps counter-clockwise to seat 0."""
        state = self._setup_with_friend("p3", "p1")
        # Defenders: p3, p1. From p3 (idx 3): next is p0 (attacker), p1 (defender).
        next_id = self.strategy.get_next_leader(state, "defending")
        assert next_id == "p1"
