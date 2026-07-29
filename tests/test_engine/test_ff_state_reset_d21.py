"""D21 — Find Friends per-round state is cleared by start_dealing.

``revealed_friends``, ``friend_declarations`` and ``friend_play_counts`` are
round-scoped.  Before D21 only ``friend_play_counts`` was reset (in
``assign_teams``); the other two survived into the next deal and were shipped
to every client by ``to_player_view``, so during the deal and bidding of round
N+1 everyone could still see round N's declared card and revealed friend —
exactly the hidden information R32 exists to protect.

The stale reveal set also broke live scoring: ``play_cards`` re-attributes
points only when ``revealed_friends`` *changes*, so a player who was a friend
in an earlier round was already in the set and their new reveal skipped the
recompute (fuzz FINDING-1).
"""
from __future__ import annotations

import pytest

from shengji.engine.engine import GameEngine
from shengji.models.card import Card, Rank, Suit
from shengji.models.friend_declaration import FriendDeclaration
from shengji.models.game_state import GamePhase, GameState
from shengji.models.player import Player
from shengji.models.trump import TrumpContext
from shengji.modes.find_friends import FindFriendsStrategy

A_S = Card(suit=Suit.SPADES, rank=Rank.ACE)


def _engine_at_round_over() -> GameEngine:
    players = [Player(id=f"p{i}", name=f"P{i}") for i in range(4)]
    state = GameState(players=players, mode="find_friends", round_leader_id="p0")
    state.phase = GamePhase.ROUND_OVER
    state.trump_context = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS)
    # Round N left a resolved friend behind.
    decl = FriendDeclaration(card=A_S, ordinal=1)
    decl.resolved_player_id = "p2"
    state.friend_declarations = [decl]
    state.revealed_friends = {"p2"}
    state.friend_play_counts = {(A_S.suit, A_S.rank): 1}
    return GameEngine(state, FindFriendsStrategy(), deal_delay=0)


class TestStartDealingClearsFriendState:
    def test_revealed_friends_cleared(self):
        engine = _engine_at_round_over()
        engine.start_dealing()
        assert engine.state.revealed_friends == set()

    def test_friend_declarations_cleared(self):
        engine = _engine_at_round_over()
        engine.start_dealing()
        assert engine.state.friend_declarations == []

    def test_friend_play_counts_cleared(self):
        engine = _engine_at_round_over()
        engine.start_dealing()
        assert engine.state.friend_play_counts == {}

    @pytest.mark.parametrize("viewer", ["p0", "p1", "p2", "p3"])
    def test_no_player_view_leaks_last_rounds_friend(self, viewer):
        engine = _engine_at_round_over()
        engine.start_dealing()

        view = engine.state.to_player_view(viewer)

        assert view["revealed_friends"] == []
        assert view["friend_declarations"] == []
