"""Tests for GameEngine dealing logic (M4.1)."""
from __future__ import annotations

import pytest

from shengji.engine.engine import GameEngine
from shengji.models.card import Card, Rank, Suit
from shengji.models.deck import NUM_PLAYERS, HAND_SIZE, BOTTOM_SIZE
from shengji.models.game_state import GamePhase, GameState
from shengji.models.player import Player


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


class _StubStrategy:
    """Minimal ModeStrategy stub — only the fields the engine touches."""
    pass


def _make_engine(state: GameState | None = None, deal_delay: float = 0) -> GameEngine:
    if state is None:
        state = _make_state()
    return GameEngine(state, _StubStrategy(), deal_delay=deal_delay)


# ---------------------------------------------------------------------------
# start_dealing — precondition checks
# ---------------------------------------------------------------------------

class TestStartDealingPreconditions:
    def test_raises_if_no_mode(self):
        state = _make_state()
        state.mode = None
        engine = _make_engine(state)
        with pytest.raises(ValueError, match="mode"):
            engine.start_dealing()

    def test_raises_if_wrong_phase(self):
        state = _make_state()
        # Force into DEALING phase (not a valid start phase for start_dealing
        # except for round transitions — WAITING is fine, PLAYING is not)
        state.phase = GamePhase.PLAYING
        engine = _make_engine(state)
        with pytest.raises(ValueError):
            engine.start_dealing()

    def test_ok_from_waiting(self):
        engine = _make_engine()
        engine.start_dealing()
        assert engine.state.phase == GamePhase.DEALING

    def test_ok_from_round_over(self):
        state = _make_state()
        state.phase = GamePhase.ROUND_OVER
        engine = _make_engine(state)
        engine.start_dealing()
        assert engine.state.phase == GamePhase.DEALING


# ---------------------------------------------------------------------------
# start_dealing — state initialisation
# ---------------------------------------------------------------------------

class TestStartDealingInit:
    def setup_method(self):
        self.engine = _make_engine()
        self.engine.start_dealing()
        self.state = self.engine.state

    def test_draw_pile_size(self):
        assert len(self.state.draw_pile) == 100

    def test_bottom_deck_size(self):
        assert len(self.state.bottom_deck) == BOTTOM_SIZE

    def test_total_cards_correct(self):
        all_cards = (
            self.state.draw_pile
            + self.state.bottom_deck
            + [c for p in self.state.players for c in p.hand]
        )
        assert len(all_cards) == 108

    def test_cards_dealt_count_reset(self):
        assert self.state.cards_dealt_count == 0

    def test_bids_cleared(self):
        assert self.state.bids == []

    def test_trump_context_cleared(self):
        assert self.state.trump_context is None

    def test_current_trick_cleared(self):
        assert self.state.current_trick == []

    def test_tricks_won_initialised(self):
        assert set(self.state.tricks_won.keys()) == {"p0", "p1", "p2", "p3"}
        for tricks in self.state.tricks_won.values():
            assert tricks == []

    def test_attacking_points_reset(self):
        assert self.state.attacking_points == 0

    def test_trick_number_reset(self):
        assert self.state.trick_number == 1

    def test_current_leader_set_from_round_leader(self):
        assert self.state.current_leader_id == self.state.round_leader_id


# ---------------------------------------------------------------------------
# deal_next_card
# ---------------------------------------------------------------------------

class TestDealNextCard:
    def setup_method(self):
        self.engine = _make_engine()
        self.engine.start_dealing()
        self.state = self.engine.state

    def test_returns_player_and_card(self):
        result = self.engine.deal_next_card()
        assert result is not None
        player_id, card = result
        assert isinstance(player_id, str)
        assert isinstance(card, Card)

    def test_first_card_goes_to_player_after_leader(self):
        # round_leader_id = "p0", so first card goes to "p1" (counter-clockwise)
        player_id, _ = self.engine.deal_next_card()
        assert player_id == "p1"

    def test_cards_dealt_count_increments(self):
        self.engine.deal_next_card()
        assert self.state.cards_dealt_count == 1
        self.engine.deal_next_card()
        assert self.state.cards_dealt_count == 2

    def test_card_added_to_recipient_hand(self):
        player_id, card = self.engine.deal_next_card()
        player = self.engine._player(player_id)
        assert card in player.hand

    def test_card_removed_from_draw_pile(self):
        before = len(self.state.draw_pile)
        self.engine.deal_next_card()
        assert len(self.state.draw_pile) == before - 1

    def test_returns_none_when_exhausted(self):
        # Deal all 100 cards
        while self.state.draw_pile:
            self.engine.deal_next_card()
        result = self.engine.deal_next_card()
        assert result is None

    def test_phase_transitions_to_bidding_after_deal_when_exhausted(self):
        while self.state.draw_pile:
            self.engine.deal_next_card()
        assert self.state.phase == GamePhase.BIDDING_AFTER_DEAL

    def test_each_player_gets_equal_cards(self):
        while self.state.draw_pile:
            self.engine.deal_next_card()
        for p in self.state.players:
            assert len(p.hand) == HAND_SIZE


# ---------------------------------------------------------------------------
# Deal order — counter-clockwise from player after leader
# ---------------------------------------------------------------------------

class TestDealOrder:
    def test_deal_order_cycles_counter_clockwise(self):
        """Cards should go to p1, p2, p3, p0, p1, p2, p3, p0, ..."""
        engine = _make_engine()
        engine.start_dealing()

        expected_order = ["p1", "p2", "p3", "p0"] * 25  # 100 cards total
        actual_order = []
        while engine.state.draw_pile:
            player_id, _ = engine.deal_next_card()
            actual_order.append(player_id)

        assert actual_order == expected_order

    def test_deal_order_with_different_leader(self):
        """When leader is p2, deal starts from p3."""
        state = _make_state()
        state.round_leader_id = "p2"
        engine = _make_engine(state)
        engine.start_dealing()

        expected_first_four = ["p3", "p0", "p1", "p2"]
        actual_first_four = []
        for _ in range(4):
            player_id, _ = engine.deal_next_card()
            actual_first_four.append(player_id)

        assert actual_first_four == expected_first_four


# ---------------------------------------------------------------------------
# Async deal_all_cards
# ---------------------------------------------------------------------------

class TestDealAllCards:
    @pytest.mark.asyncio
    async def test_deal_all_cards_deals_100_cards(self):
        engine = _make_engine(deal_delay=0)
        engine.start_dealing()
        await engine.deal_all_cards()
        total_in_hands = sum(len(p.hand) for p in engine.state.players)
        assert total_in_hands == 100

    @pytest.mark.asyncio
    async def test_deal_all_cards_fires_callback_for_each_card(self):
        engine = _make_engine(deal_delay=0)
        engine.start_dealing()
        calls = []

        async def on_card(pid, card):
            calls.append((pid, card))

        await engine.deal_all_cards(on_card_dealt=on_card)
        assert len(calls) == 100

    @pytest.mark.asyncio
    async def test_deal_all_cards_phase_after(self):
        engine = _make_engine(deal_delay=0)
        engine.start_dealing()
        await engine.deal_all_cards()
        assert engine.state.phase == GamePhase.BIDDING_AFTER_DEAL

    @pytest.mark.asyncio
    async def test_deal_all_cards_no_callback(self):
        """Passing no callback should work fine (no error)."""
        engine = _make_engine(deal_delay=0)
        engine.start_dealing()
        await engine.deal_all_cards()  # no on_card_dealt
        assert engine.state.phase == GamePhase.BIDDING_AFTER_DEAL
