"""Bidding state-machine and bottom-exchange edge flows.

Most single-step place_bid/exchange_bottom validation is unit-tested in
tests/test_engine/test_bidding.py and test_bottom_exchange.py; these tests
cover multi-step flows not exercised there (cross-player overtakes with
cards actually in hand, repeated all-pass redeals, burying jokers/trump/
points picked up from the bottom).
"""
from __future__ import annotations

import pytest

from shengji.engine.engine import GameEngine
from shengji.models.card import Rank, Suit
from shengji.models.deck import BOTTOM_SIZE, HAND_SIZE
from shengji.models.game_state import GamePhase
from shengji.modes.upgrade import UpgradeStrategy

from tests.test_integration.helpers import BJ, CL, D, H, S, SJ, c, ctx, make_state


def _bidding_engine() -> tuple[GameEngine, object]:
    """Engine in BIDDING_AFTER_DEAL with trump rank TWO for everyone."""
    state = make_state("upgrade", "p0", ranks={p: Rank.TWO for p in ("p0", "p1", "p2", "p3")})
    engine = GameEngine(state, UpgradeStrategy(), deal_delay=0)
    state.phase = GamePhase.BIDDING_AFTER_DEAL
    return engine, state


class TestBiddingEdges:
    def test_pair_overtakes_another_players_single(self):
        engine, _ = _bidding_engine()
        engine._player("p0").hand = [c(S, Rank.TWO)]
        engine._player("p1").hand = [c(D, Rank.TWO), c(D, Rank.TWO)]
        engine.place_bid("p0", [c(S, Rank.TWO)])
        bid = engine.place_bid("p1", [c(D, Rank.TWO), c(D, Rank.TWO)])
        assert bid.resulting_trump.trump_suit == Suit.DIAMONDS

    def test_small_joker_pair_overtakes_suited_pair(self):
        engine, _ = _bidding_engine()
        engine._player("p0").hand = [c(S, Rank.TWO), c(S, Rank.TWO)]
        engine._player("p1").hand = [SJ, SJ]
        engine.place_bid("p0", [c(S, Rank.TWO), c(S, Rank.TWO)])
        bid = engine.place_bid("p1", [SJ, SJ])
        assert bid.resulting_trump.trump_suit is None  # no-trump round

    def test_bid_with_wrong_rank_card_rejected(self):
        engine, _ = _bidding_engine()
        engine._player("p0").hand = [c(S, Rank.THREE)]
        with pytest.raises(ValueError):
            engine.place_bid("p0", [c(S, Rank.THREE)])


class TestAllPassRedeal:
    def test_all_pass_redeals_and_preserves_leader(self):
        engine, state = _bidding_engine()
        assert state.bids == []
        engine.close_bidding()  # nobody bid
        assert state.phase == GamePhase.DEALING
        assert state.round_leader_id == "p0", "leader preserved across redeal"
        assert state.bids == [], "bids cleared on redeal"
        # start_dealing() rebuilt a full shuffled draw pile (108 - 8 bottom).
        assert len(state.draw_pile) == 100
        for p in state.players:
            assert p.hand == []

    def test_second_all_pass_redeals_again(self):
        engine, state = _bidding_engine()
        engine.close_bidding()  # redeal 1
        assert state.phase == GamePhase.DEALING
        # Simulate dealing finishing again with still no bids.
        state.draw_pile = []
        state.phase = GamePhase.BIDDING_AFTER_DEAL
        engine.close_bidding()  # redeal 2
        assert state.phase == GamePhase.DEALING
        assert state.round_leader_id == "p0"


def _exchange_engine() -> tuple[GameEngine, object]:
    """Engine in BOTTOM_EXCHANGE: p0 holds 25 cards, bottom holds 8 spicy ones."""
    state = make_state("upgrade", "p0", ranks={"p0": Rank.TWO})
    engine = GameEngine(state, UpgradeStrategy(), deal_delay=0)
    state.trump_context = ctx(Rank.TWO, Suit.HEARTS)
    non_trump_ranks = [
        Rank.THREE, Rank.FOUR, Rank.FIVE, Rank.SIX, Rank.SEVEN, Rank.EIGHT,
        Rank.NINE, Rank.TEN, Rank.JACK, Rank.QUEEN, Rank.KING, Rank.ACE,
    ]
    leader_hand = (
        [c(S, r) for r in non_trump_ranks]
        + [c(D, r) for r in non_trump_ranks]
        + [c(D, Rank.THREE)]
    )  # 25 cards
    engine._player("p0").hand = leader_hand
    state.bottom_deck = [
        c(CL, Rank.FIVE), c(CL, Rank.TEN), c(CL, Rank.KING),  # point cards
        SJ, BJ, c(H, Rank.TWO), c(H, Rank.ACE), c(CL, Rank.THREE),
    ]
    state.phase = GamePhase.BOTTOM_EXCHANGE
    return engine, state


class TestBottomExchangeFlow:
    def test_leader_can_bury_points_trumps_and_jokers(self):
        """Burying point cards, trump cards, and jokers is all allowed."""
        engine, state = _exchange_engine()
        put_back = [
            c(CL, Rank.FIVE), c(CL, Rank.TEN), c(CL, Rank.KING),
            SJ, BJ, c(H, Rank.TWO), c(H, Rank.ACE), c(CL, Rank.THREE),
        ]
        engine.exchange_bottom("p0", put_back)
        assert state.phase == GamePhase.PLAYING
        assert len(engine._player("p0").hand) == HAND_SIZE
        assert len(state.bottom_deck) == BOTTOM_SIZE
        assert any(card.point_value > 0 for card in state.bottom_deck)

    def test_zero_cards_rejected(self):
        engine, _ = _exchange_engine()
        with pytest.raises(ValueError, match="exactly"):
            engine.exchange_bottom("p0", [])
