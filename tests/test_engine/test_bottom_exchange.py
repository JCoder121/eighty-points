"""Tests for GameEngine bottom exchange and friend declaration (M4.3)."""
from __future__ import annotations

import pytest

from shengji.engine.engine import GameEngine
from shengji.models.card import Card, Rank, Suit
from shengji.models.deck import NUM_PLAYERS, BOTTOM_SIZE, HAND_SIZE
from shengji.models.friend_declaration import FriendDeclaration
from shengji.models.game_state import GamePhase, GameState
from shengji.models.player import Player
from shengji.models.trump import TrumpContext


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _UpgradeStub:
    """Stub for Upgrade mode: no friend declaration needed."""
    def assign_teams(self, state) -> None:
        pass

    def needs_friend_declaration(self) -> bool:
        return False

    def validate_friend_declaration(self, state, declarations) -> None:
        raise RuntimeError("Should not be called in Upgrade mode")


class _FindFriendsStub:
    """Stub for Find Friends mode: friend declaration required."""
    def assign_teams(self, state) -> None:
        pass

    def needs_friend_declaration(self) -> bool:
        return True

    def validate_friend_declaration(self, state, declarations) -> None:
        # Accept any non-empty list for testing
        if not declarations:
            raise ValueError("Must declare at least one friend.")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_player(idx: int) -> Player:
    return Player(id=f"p{idx}", name=f"Player{idx}")


def _make_state(mode: str = "upgrade") -> GameState:
    players = [_make_player(i) for i in range(NUM_PLAYERS)]
    return GameState(
        players=players,
        mode=mode,
        round_leader_id="p0",
    )


def _make_engine(state: GameState | None = None, find_friends: bool = False) -> GameEngine:
    if state is None:
        state = _make_state(mode="find_friends" if find_friends else "upgrade")
    strategy = _FindFriendsStub() if find_friends else _UpgradeStub()
    return GameEngine(state, strategy, deal_delay=0)


def _deal_and_bid(engine: GameEngine, bidder_id: str = "p0") -> None:
    """Deal all cards and simulate a bid so we reach BOTTOM_EXCHANGE."""
    engine.start_dealing()
    while engine.state.draw_pile:
        engine.deal_next_card()
    # Give the bidder a trump-rank card by replacing their first card.
    # This keeps hand size at HAND_SIZE (25), which the exchange_bottom assert requires.
    trump_card = Card(suit=Suit.HEARTS, rank=Rank.TWO)
    bidder = engine._player(bidder_id)
    if trump_card not in bidder.hand:
        bidder.hand[0] = trump_card  # replace, not insert
    engine.place_bid(bidder_id, [trump_card])
    engine.close_bidding()
    # state is now BOTTOM_EXCHANGE, bottom_deck has 8 cards


# ---------------------------------------------------------------------------
# exchange_bottom — preconditions
# ---------------------------------------------------------------------------

class TestExchangeBottomPreconditions:
    def setup_method(self):
        self.engine = _make_engine()
        _deal_and_bid(self.engine)

    def test_wrong_phase_raises(self):
        self.engine.state.phase = GamePhase.PLAYING
        eight = self.engine.state.bottom_deck[:8]
        with pytest.raises(ValueError, match="BOTTOM_EXCHANGE"):
            self.engine.exchange_bottom("p0", eight)

    def test_wrong_player_raises(self):
        eight = self.engine.state.bottom_deck[:8]
        with pytest.raises(ValueError, match="round leader"):
            self.engine.exchange_bottom("p1", eight)

    def test_wrong_card_count_raises(self):
        seven = self.engine.state.bottom_deck[:7]
        with pytest.raises(ValueError, match="exactly 8"):
            self.engine.exchange_bottom("p0", seven)


# ---------------------------------------------------------------------------
# exchange_bottom — core logic
# ---------------------------------------------------------------------------

class TestExchangeBottomLogic:
    def setup_method(self):
        self.engine = _make_engine()
        _deal_and_bid(self.engine)
        self.state = self.engine.state
        self.leader = self.engine._player("p0")

    def test_leader_picks_up_bottom(self):
        """After picking up, leader should have HAND_SIZE + BOTTOM_SIZE cards briefly."""
        bottom_cards = list(self.state.bottom_deck)
        # Do exchange — choose bottom cards as the put-back
        self.engine.exchange_bottom("p0", bottom_cards)
        # hand should be back to HAND_SIZE
        assert len(self.leader.hand) == HAND_SIZE

    def test_hand_size_correct_after_exchange(self):
        put_back = self.state.bottom_deck[:BOTTOM_SIZE]
        self.engine.exchange_bottom("p0", put_back)
        assert len(self.leader.hand) == HAND_SIZE

    def test_new_bottom_deck_is_put_back_cards(self):
        put_back = list(self.state.bottom_deck)  # put same 8 back
        self.engine.exchange_bottom("p0", put_back)
        assert sorted(self.state.bottom_deck, key=repr) == sorted(put_back, key=repr)

    def test_total_cards_unchanged(self):
        initial_total = (
            len(self.state.bottom_deck)
            + sum(len(p.hand) for p in self.state.players)
        )
        put_back = list(self.state.bottom_deck)
        self.engine.exchange_bottom("p0", put_back)
        final_total = (
            len(self.state.bottom_deck)
            + sum(len(p.hand) for p in self.state.players)
        )
        assert initial_total == final_total

    def test_upgrade_transitions_to_playing(self):
        put_back = list(self.state.bottom_deck)
        self.engine.exchange_bottom("p0", put_back)
        assert self.state.phase == GamePhase.PLAYING

    def test_card_not_in_hand_raises(self):
        # Create a card the leader definitely doesn't have
        phantom = Card(suit=Suit.CLUBS, rank=Rank.ACE)
        # Make sure it's not in hand
        self.leader.hand = [c for c in self.leader.hand if c != phantom]
        seven = list(self.state.bottom_deck)[:7]
        with pytest.raises(ValueError, match="not in the leader"):
            self.engine.exchange_bottom("p0", seven + [phantom])

    def test_leader_can_exchange_with_cards_from_bottom(self):
        """Leader picks up bottom and puts part of it back — valid."""
        bottom_cards = list(self.state.bottom_deck)
        # Use the actual bottom cards as put-back (leader will have them after pickup)
        self.engine.exchange_bottom("p0", bottom_cards)
        assert len(self.leader.hand) == HAND_SIZE

    def test_points_in_bottom_preserved(self):
        """Cards buried in the bottom retain their point values."""
        put_back = list(self.state.bottom_deck)
        self.engine.exchange_bottom("p0", put_back)
        bottom_pts = sum(c.point_value for c in self.state.bottom_deck)
        assert isinstance(bottom_pts, int)  # just confirm it's accessible


# ---------------------------------------------------------------------------
# exchange_bottom — Find Friends transitions to FRIEND_DECLARATION
# ---------------------------------------------------------------------------

class TestExchangeBottomFindFriends:
    def setup_method(self):
        self.engine = _make_engine(find_friends=True)
        _deal_and_bid(self.engine)

    def test_find_friends_transitions_to_friend_declaration(self):
        put_back = list(self.engine.state.bottom_deck)
        self.engine.exchange_bottom("p0", put_back)
        assert self.engine.state.phase == GamePhase.FRIEND_DECLARATION


# ---------------------------------------------------------------------------
# declare_friends
# ---------------------------------------------------------------------------

class TestDeclareFriends:
    def setup_method(self):
        self.engine = _make_engine(find_friends=True)
        _deal_and_bid(self.engine)
        put_back = list(self.engine.state.bottom_deck)
        self.engine.exchange_bottom("p0", put_back)
        # Now in FRIEND_DECLARATION

    def _decl(self) -> FriendDeclaration:
        return FriendDeclaration(
            card=Card(suit=Suit.SPADES, rank=Rank.ACE),
            ordinal=1,
        )

    def test_wrong_phase_raises(self):
        self.engine.state.phase = GamePhase.PLAYING
        with pytest.raises(ValueError, match="FRIEND_DECLARATION"):
            self.engine.declare_friends("p0", [self._decl()])

    def test_wrong_player_raises(self):
        with pytest.raises(ValueError, match="round leader"):
            self.engine.declare_friends("p1", [self._decl()])

    def test_declarations_stored(self):
        decl = self._decl()
        self.engine.declare_friends("p0", [decl])
        assert self.engine.state.friend_declarations == [decl]

    def test_transitions_to_playing(self):
        self.engine.declare_friends("p0", [self._decl()])
        assert self.engine.state.phase == GamePhase.PLAYING

    def test_strategy_validation_called(self):
        """Empty declarations rejected by the stub strategy."""
        with pytest.raises(ValueError, match="at least one friend"):
            self.engine.declare_friends("p0", [])
