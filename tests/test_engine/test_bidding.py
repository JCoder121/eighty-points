"""Tests for GameEngine bidding logic (M4.2)."""
from __future__ import annotations

import pytest

from shengji.engine.engine import GameEngine
from shengji.models.card import Card, Rank, Suit
from shengji.models.deck import NUM_PLAYERS
from shengji.models.game_state import GamePhase, GameState
from shengji.models.player import Player
from shengji.models.trump import TrumpContext


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_player(idx: int, rank: Rank = Rank.TWO) -> Player:
    return Player(id=f"p{idx}", name=f"Player{idx}", rank=rank)


def _make_state(mode: str = "upgrade", leader_rank: Rank = Rank.TWO) -> GameState:
    players = [_make_player(i, rank=leader_rank) for i in range(NUM_PLAYERS)]
    return GameState(
        players=players,
        mode=mode,
        round_leader_id="p0",
    )


class _StubStrategy:
    def assign_teams(self, state) -> None:
        pass


def _make_engine(state: GameState | None = None) -> GameEngine:
    if state is None:
        state = _make_state()
    return GameEngine(state, _StubStrategy(), deal_delay=0)


def _deal_all(engine: GameEngine) -> None:
    """Synchronously deal all cards (no async needed in tests)."""
    engine.start_dealing()
    while engine.state.draw_pile:
        engine.deal_next_card()
    # state is now BIDDING_AFTER_DEAL


def _give_hand(engine: GameEngine, player_id: str, cards: list[Card]) -> None:
    """Replace a player's hand with the given cards (for controlled tests)."""
    engine._player(player_id).hand = list(cards)


# Convenience card constructors
def _card(suit: Suit, rank: Rank) -> Card:
    return Card(suit=suit, rank=rank)


SJ = Card(suit=Suit.JOKER, rank=Rank.SMALL_JOKER)
BJ = Card(suit=Suit.JOKER, rank=Rank.BIG_JOKER)


# ---------------------------------------------------------------------------
# _bid_strength helper
# ---------------------------------------------------------------------------

class TestBidStrength:
    def test_single_suited(self):
        assert GameEngine._bid_strength([_card(Suit.HEARTS, Rank.TWO)]) == 1

    def test_suited_pair(self):
        assert GameEngine._bid_strength([_card(Suit.HEARTS, Rank.TWO)] * 2) == 2

    def test_small_joker_pair(self):
        assert GameEngine._bid_strength([SJ, SJ]) == 3

    def test_big_joker_pair(self):
        assert GameEngine._bid_strength([BJ, BJ]) == 4

    def test_invalid_count_raises(self):
        with pytest.raises(ValueError):
            GameEngine._bid_strength([])
        with pytest.raises(ValueError):
            GameEngine._bid_strength([SJ, SJ, SJ])


# ---------------------------------------------------------------------------
# _validate_bid_cards helper
# ---------------------------------------------------------------------------

class TestValidateBidCards:
    def test_single_trump_rank_suited_ok(self):
        GameEngine._validate_bid_cards([_card(Suit.SPADES, Rank.TWO)], Rank.TWO)

    def test_single_joker_raises(self):
        with pytest.raises(ValueError, match="joker"):
            GameEngine._validate_bid_cards([SJ], Rank.TWO)

    def test_single_wrong_rank_raises(self):
        with pytest.raises(ValueError, match="trump rank"):
            GameEngine._validate_bid_cards([_card(Suit.SPADES, Rank.THREE)], Rank.TWO)

    def test_pair_not_identical_raises(self):
        with pytest.raises(ValueError, match="identical"):
            GameEngine._validate_bid_cards(
                [_card(Suit.SPADES, Rank.TWO), _card(Suit.HEARTS, Rank.TWO)], Rank.TWO
            )

    def test_pair_wrong_rank_raises(self):
        with pytest.raises(ValueError, match="trump rank"):
            GameEngine._validate_bid_cards(
                [_card(Suit.SPADES, Rank.THREE)] * 2, Rank.TWO
            )

    def test_pair_identical_trump_rank_ok(self):
        GameEngine._validate_bid_cards([_card(Suit.HEARTS, Rank.TWO)] * 2, Rank.TWO)

    def test_joker_pair_small_ok(self):
        GameEngine._validate_bid_cards([SJ, SJ], Rank.TWO)

    def test_joker_pair_big_ok(self):
        GameEngine._validate_bid_cards([BJ, BJ], Rank.TWO)

    def test_zero_cards_raises(self):
        with pytest.raises(ValueError):
            GameEngine._validate_bid_cards([], Rank.TWO)

    def test_three_cards_raises(self):
        with pytest.raises(ValueError):
            GameEngine._validate_bid_cards([_card(Suit.SPADES, Rank.TWO)] * 3, Rank.TWO)


# ---------------------------------------------------------------------------
# _can_overtake helper
# ---------------------------------------------------------------------------

class TestCanOvertake:
    from shengji.models.bid import Bid
    from shengji.models.trump import TrumpContext

    def _bid(self, player_id: str, cards: list[Card]) -> "Bid":
        from shengji.models.bid import Bid
        from shengji.models.trump import TrumpContext
        return Bid(
            player_id=player_id,
            cards=cards,
            resulting_trump=TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS),
        )

    def test_no_current_bid_always_valid(self):
        assert GameEngine._can_overtake([_card(Suit.HEARTS, Rank.TWO)], "p1", None)

    def test_single_cannot_overtake_single_different_player(self):
        # A single bid never beats another single — you need a pair or higher.
        current = self._bid("p0", [_card(Suit.HEARTS, Rank.TWO)])
        assert not GameEngine._can_overtake([_card(Suit.SPADES, Rank.TWO)], "p1", current)

    def test_single_cannot_overtake_own_single(self):
        current = self._bid("p0", [_card(Suit.HEARTS, Rank.TWO)])
        assert not GameEngine._can_overtake([_card(Suit.SPADES, Rank.TWO)], "p0", current)

    def test_pair_overtakes_single(self):
        current = self._bid("p0", [_card(Suit.HEARTS, Rank.TWO)])
        assert GameEngine._can_overtake([_card(Suit.SPADES, Rank.TWO)] * 2, "p1", current)

    def test_same_player_pair_overtakes_own_single(self):
        current = self._bid("p0", [_card(Suit.HEARTS, Rank.TWO)])
        assert GameEngine._can_overtake([_card(Suit.HEARTS, Rank.TWO)] * 2, "p0", current)

    def test_suited_pair_cannot_overtake_suited_pair(self):
        current = self._bid("p0", [_card(Suit.HEARTS, Rank.TWO)] * 2)
        assert not GameEngine._can_overtake([_card(Suit.SPADES, Rank.TWO)] * 2, "p1", current)

    def test_small_joker_pair_overtakes_suited_pair(self):
        current = self._bid("p0", [_card(Suit.HEARTS, Rank.TWO)] * 2)
        assert GameEngine._can_overtake([SJ, SJ], "p1", current)

    def test_big_joker_pair_overtakes_small_joker_pair(self):
        current = self._bid("p0", [SJ, SJ])
        assert GameEngine._can_overtake([BJ, BJ], "p1", current)

    def test_small_joker_pair_cannot_overtake_big_joker_pair(self):
        current = self._bid("p0", [BJ, BJ])
        assert not GameEngine._can_overtake([SJ, SJ], "p1", current)


# ---------------------------------------------------------------------------
# place_bid — integration
# ---------------------------------------------------------------------------

class TestPlaceBid:
    def setup_method(self):
        self.engine = _make_engine()
        _deal_all(self.engine)

    def _give_cards(self, player_id: str, cards: list[Card]) -> None:
        """Put specific cards in a player's hand for test control."""
        p = self.engine._player(player_id)
        p.hand = list(cards)

    def test_single_bid_accepted(self):
        card = _card(Suit.HEARTS, Rank.TWO)
        self._give_cards("p1", [card])
        bid = self.engine.place_bid("p1", [card])
        assert bid.player_id == "p1"
        assert len(self.engine.state.bids) == 1

    def test_trump_context_updated_on_bid(self):
        card = _card(Suit.HEARTS, Rank.TWO)
        self._give_cards("p1", [card])
        self.engine.place_bid("p1", [card])
        ctx = self.engine.state.trump_context
        assert ctx is not None
        assert ctx.trump_suit == Suit.HEARTS
        assert ctx.trump_rank == Rank.TWO

    def test_bid_rejected_if_player_lacks_card(self):
        card = _card(Suit.HEARTS, Rank.TWO)
        self.engine._player("p1").hand = []  # empty hand
        with pytest.raises(ValueError, match="does not hold"):
            self.engine.place_bid("p1", [card])

    def test_bid_rejected_in_wrong_phase(self):
        self.engine.state.phase = GamePhase.PLAYING
        card = _card(Suit.HEARTS, Rank.TWO)
        self._give_cards("p1", [card])
        with pytest.raises(ValueError, match="phase"):
            self.engine.place_bid("p1", [card])

    def test_single_cannot_overtake_single_different_player(self):
        # Rule: a single never beats another single; you need a pair or better.
        c_hearts = _card(Suit.HEARTS, Rank.TWO)
        c_spades = _card(Suit.SPADES, Rank.TWO)
        self._give_cards("p1", [c_hearts])
        self._give_cards("p2", [c_spades])
        self.engine.place_bid("p1", [c_hearts])
        with pytest.raises(ValueError, match="not strong enough"):
            self.engine.place_bid("p2", [c_spades])

    def test_same_player_cannot_rebid_single(self):
        c1 = _card(Suit.HEARTS, Rank.TWO)
        c2 = _card(Suit.SPADES, Rank.TWO)
        self._give_cards("p1", [c1, c2])
        self.engine.place_bid("p1", [c1])
        with pytest.raises(ValueError, match="not strong enough"):
            self.engine.place_bid("p1", [c2])

    def test_reinforcement_single_to_pair_same_player(self):
        c = _card(Suit.HEARTS, Rank.TWO)
        self._give_cards("p1", [c, c])
        self.engine.place_bid("p1", [c])
        self.engine.place_bid("p1", [c, c])
        assert GameEngine._bid_strength(self.engine.state.bids[-1].cards) == 2

    def test_suited_pair_cannot_overtake_suited_pair(self):
        c_hearts = _card(Suit.HEARTS, Rank.TWO)
        c_spades = _card(Suit.SPADES, Rank.TWO)
        self._give_cards("p1", [c_hearts, c_hearts])
        self._give_cards("p2", [c_spades, c_spades])
        self.engine.place_bid("p1", [c_hearts, c_hearts])
        with pytest.raises(ValueError, match="not strong enough"):
            self.engine.place_bid("p2", [c_spades, c_spades])

    def test_small_joker_pair_bid(self):
        self._give_cards("p2", [SJ, SJ])
        bid = self.engine.place_bid("p2", [SJ, SJ])
        assert bid.resulting_trump.trump_suit is None  # no-trump

    def test_big_joker_pair_bid(self):
        self._give_cards("p3", [BJ, BJ])
        bid = self.engine.place_bid("p3", [BJ, BJ])
        assert bid.resulting_trump.trump_suit is None

    def test_big_joker_overtakes_small_joker(self):
        c_hearts = _card(Suit.HEARTS, Rank.TWO)
        self._give_cards("p0", [c_hearts, c_hearts])
        self._give_cards("p1", [SJ, SJ])
        self._give_cards("p2", [BJ, BJ])
        self.engine.place_bid("p0", [c_hearts, c_hearts])
        self.engine.place_bid("p1", [SJ, SJ])
        self.engine.place_bid("p2", [BJ, BJ])
        assert self.engine.state.bids[-1].player_id == "p2"

    def test_single_joker_bid_raises(self):
        self._give_cards("p1", [SJ])
        with pytest.raises(ValueError, match="joker"):
            self.engine.place_bid("p1", [SJ])

    def test_bid_accepted_during_dealing_phase(self):
        """Bids are valid even while cards are still being dealt."""
        engine = _make_engine()
        engine.start_dealing()
        # Give p1 a trump-rank card manually to simulate mid-deal
        card = _card(Suit.HEARTS, Rank.TWO)
        engine._player("p1").hand = [card]
        assert engine.state.phase == GamePhase.DEALING
        bid = engine.place_bid("p1", [card])
        assert bid.player_id == "p1"

    def test_trump_rank_comes_from_round_leader_rank(self):
        """If the round leader is at rank 5, trump rank should be FIVE."""
        state = _make_state(leader_rank=Rank.FIVE)
        engine = _make_engine(state)
        _deal_all(engine)
        card = _card(Suit.DIAMONDS, Rank.FIVE)
        engine._player("p1").hand = [card]
        bid = engine.place_bid("p1", [card])
        assert bid.resulting_trump.trump_rank == Rank.FIVE


# ---------------------------------------------------------------------------
# close_bidding
# ---------------------------------------------------------------------------

class TestCloseBidding:
    def setup_method(self):
        self.engine = _make_engine()
        _deal_all(self.engine)

    def test_close_bidding_wrong_phase_raises(self):
        self.engine.state.phase = GamePhase.PLAYING
        with pytest.raises(ValueError, match="BIDDING_AFTER_DEAL"):
            self.engine.close_bidding()

    def test_close_bidding_with_bid_transitions_to_bottom_exchange(self):
        card = _card(Suit.HEARTS, Rank.TWO)
        self.engine._player("p1").hand = [card]
        self.engine.place_bid("p1", [card])
        self.engine.close_bidding()
        assert self.engine.state.phase == GamePhase.BOTTOM_EXCHANGE

    def test_close_bidding_sets_round_leader_to_winner(self):
        card = _card(Suit.HEARTS, Rank.TWO)
        self.engine._player("p2").hand = [card]
        self.engine.place_bid("p2", [card])
        self.engine.close_bidding()
        assert self.engine.state.round_leader_id == "p2"

    def test_close_bidding_no_bid_triggers_redeal(self):
        # No bids placed — should re-deal
        self.engine.close_bidding()
        assert self.engine.state.phase == GamePhase.DEALING
        # All hands cleared and draw pile refilled
        for p in self.engine.state.players:
            assert p.hand == []
        assert len(self.engine.state.draw_pile) == 100

    def test_close_bidding_locks_trump_context(self):
        card = _card(Suit.SPADES, Rank.TWO)
        self.engine._player("p3").hand = [card]
        self.engine.place_bid("p3", [card])
        self.engine.close_bidding()
        ctx = self.engine.state.trump_context
        assert ctx is not None
        assert ctx.trump_suit == Suit.SPADES

    def test_last_bid_wins_when_multiple_bids(self):
        # p1 bids a single; p2 overtakes with a pair (the minimum required
        # to beat a single since same-strength bids cannot overtake).
        c1 = _card(Suit.HEARTS, Rank.TWO)
        c2 = _card(Suit.SPADES, Rank.TWO)
        self.engine._player("p1").hand = [c1]
        self.engine._player("p2").hand = [c2, c2]
        self.engine.place_bid("p1", [c1])
        self.engine.place_bid("p2", [c2, c2])
        self.engine.close_bidding()
        assert self.engine.state.round_leader_id == "p2"
