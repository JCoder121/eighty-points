"""Friend-reveal progress must live on GameState, not on the strategy instance.

The per-card play counter used to match friend-declaration ordinals is engine
state: a snapshot/restore of GameState taken mid-round has to round-trip it, and
a freshly constructed FindFriendsStrategy driving a restored state must resume
exactly where the previous one left off.
"""
from __future__ import annotations

import copy

from shengji.models.card import Card, Rank, Suit
from shengji.models.friend_declaration import FriendDeclaration
from shengji.models.game_state import GameState
from shengji.models.player import Player
from shengji.models.trump import TrumpContext
from shengji.modes.find_friends import FindFriendsStrategy

A_S = Card(Suit.SPADES, Rank.ACE)


def _make_state(leader_id: str = "p0") -> GameState:
    return GameState(
        players=[Player(id=f"p{i}", name=f"Player{i}") for i in range(4)],
        mode="find_friends",
        round_leader_id=leader_id,
        trump_context=TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS),
    )


def test_reveal_progress_survives_snapshot_into_fresh_strategy():
    """Ordinal-2 reveal fires on the second copy even across a state round-trip."""
    state = _make_state()
    FindFriendsStrategy().assign_teams(state)
    state.friend_declarations = [FriendDeclaration(card=A_S, ordinal=2)]

    # First copy of the declared card: no reveal yet.
    FindFriendsStrategy().resolve_friend(state, "p1", A_S)
    assert state.revealed_friends == set()

    restored = copy.deepcopy(state)

    # A brand-new strategy drives the restored state; the second copy must fire.
    FindFriendsStrategy().resolve_friend(restored, "p2", A_S)

    assert "p2" in restored.revealed_friends
    assert restored.friend_declarations[0].resolved_player_id == "p2"
    assert next(p for p in restored.players if p.id == "p2").is_defending is True


def test_play_counts_are_snapshotted_independently():
    """A deep copy owns its own counter — further plays don't leak back."""
    state = _make_state()
    FindFriendsStrategy().assign_teams(state)
    state.friend_declarations = [FriendDeclaration(card=A_S, ordinal=2)]

    strategy = FindFriendsStrategy()
    strategy.resolve_friend(state, "p1", A_S)

    restored = copy.deepcopy(state)
    strategy.resolve_friend(restored, "p2", A_S)

    assert "p2" in restored.revealed_friends
    assert state.revealed_friends == set()
    assert state.friend_declarations[0].resolved_player_id is None
