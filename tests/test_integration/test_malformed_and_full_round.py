"""Malformed-input rejection plus full deterministic rounds with state
invariants (card conservation, superuser validation) checked after every play.
"""
from __future__ import annotations

import pytest

from shengji.engine.tricks import get_legal_plays
from shengji.models.card import RANK_ORDER, SUITED_SUITS, Card, Rank
from shengji.models.deck import TOTAL_CARDS
from shengji.models.friend_declaration import FriendDeclaration
from shengji.models.game_state import GamePhase, GameState
from shengji.superuser import inspector

from tests.test_integration.helpers import BJ, D, S, SJ, c, ctx, make_engine, setup_playing


def _simple_playing():
    engine, state = make_engine()
    hands = {
        "p0": [c(S, Rank.THREE), c(S, Rank.FOUR)],
        "p1": [c(S, Rank.FIVE), c(S, Rank.SIX)],
        "p2": [c(S, Rank.SEVEN), c(S, Rank.EIGHT)],
        "p3": [c(S, Rank.NINE), c(S, Rank.TEN)],
    }
    setup_playing(engine, hands, [], ctx())
    return engine, state


class TestMalformedPlays:
    def test_duplicate_card_objects_in_one_play_rejected(self):
        """p0 holds ONE 3♠; playing it twice in a single play must fail."""
        engine, _ = _simple_playing()
        with pytest.raises(ValueError, match="not in"):
            engine.play_cards("p0", [c(S, Rank.THREE), c(S, Rank.THREE)])

    def test_wrong_size_follow_rejected(self):
        engine, _ = _simple_playing()
        engine.play_cards("p0", [c(S, Rank.THREE)])  # single lead
        with pytest.raises(ValueError, match="follow"):
            engine.play_cards("p1", [c(S, Rank.FIVE), c(S, Rank.SIX)])

    def test_empty_lead_rejected(self):
        engine, _ = _simple_playing()
        with pytest.raises(ValueError):
            engine.play_cards("p0", [])


# ---------------------------------------------------------------------------
# Full deterministic rounds: conservation + validate_state after every play
# ---------------------------------------------------------------------------

def _full_deck() -> list[Card]:
    cards: list[Card] = []
    for _ in range(2):  # two decks
        for suit in SUITED_SUITS:
            for rank in RANK_ORDER:
                cards.append(Card(suit=suit, rank=rank))
        cards.append(SJ)
        cards.append(BJ)
    return cards


def _count_all(state: GameState) -> int:
    total = sum(len(p.hand) for p in state.players)
    total += len(state.bottom_deck)
    total += len(state.draw_pile)
    for tricks in state.tricks_won.values():
        for trick in tricks:
            total += len(trick)
    for _, play in state.current_trick:
        total += len(play)
    return total


def _check_conservation(state: GameState) -> None:
    assert _count_all(state) == TOTAL_CARDS, f"card count drifted to {_count_all(state)}"
    violations = [
        v for v in inspector.validate_state(state)
        if "Total card" in v or "appears" in v or "maximum hand" in v
    ]
    assert violations == [], violations


def _play_out_round(engine, state) -> None:
    """Drive a full round: leader plays their first card, followers play the
    first legal response, checking invariants after every single play."""
    while state.phase == GamePhase.PLAYING:
        leader = state.current_turn_id
        engine.play_cards(leader, [engine._player(leader).hand[0]])
        _check_conservation(state)
        for _ in range(3):
            pid = state.current_turn_id
            options = get_legal_plays(
                engine._player(pid).hand, state.led_format, state.led_suit,
                state.trump_context,
            )
            engine.play_cards(pid, options[0])
            _check_conservation(state)


class TestFullRoundInvariants:
    def _deal(self, mode: str):
        deck = _full_deck()
        assert len(deck) == TOTAL_CARDS
        hands = {
            "p0": deck[0:25],
            "p1": deck[25:50],
            "p2": deck[50:75],
            "p3": deck[75:100],
        }
        engine, state = make_engine(mode)
        setup_playing(engine, hands, deck[100:108], ctx())
        return engine, state

    def test_full_round_upgrade_invariants(self):
        engine, state = self._deal("upgrade")
        _check_conservation(state)
        _play_out_round(engine, state)

        assert state.phase == GamePhase.SCORING
        assert all(len(p.hand) == 0 for p in state.players)
        assert _count_all(state) == TOTAL_CARDS

        result = engine.end_round()
        assert result["attacking_points"] >= 0
        assert result["winner"] in ("attacking", "defending")

    def test_full_round_find_friends_invariants(self):
        engine, state = self._deal("find_friends")
        state.friend_declarations = [
            FriendDeclaration(card=c(D, Rank.ACE), ordinal=1)  # non-trump card
        ]
        _play_out_round(engine, state)

        assert state.phase == GamePhase.SCORING
        assert _count_all(state) == TOTAL_CARDS
        result = engine.end_round()
        assert result["winner"] in ("attacking", "defending")
