"""Tests for superuser mutator (M6.2)."""
from __future__ import annotations

import pytest

from shengji.models.card import Card, Rank, Suit
from shengji.models.deck import HAND_SIZE, NUM_PLAYERS, BOTTOM_SIZE
from shengji.models.game_state import GamePhase, GameState
from shengji.models.player import Player
from shengji.models.trump import TrumpContext
from shengji.superuser.mutator import (
    deal_specific_hands,
    force_phase,
    set_bottom,
    set_hand,
    set_points,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card(suit: Suit, rank: Rank) -> Card:
    return Card(suit=suit, rank=rank)


def _make_players() -> list[Player]:
    return [Player(id=f"p{i}", name=f"Player{i}") for i in range(NUM_PLAYERS)]


def _make_playing_state() -> GameState:
    """PLAYING-phase state with a full, consistent 108-card distribution."""
    from shengji.models.deck import Deck

    state = GameState(
        players=_make_players(),
        mode="upgrade",
        round_leader_id="p0",
        phase=GamePhase.PLAYING,
        trump_context=TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS),
        current_turn_id="p0",
    )
    deck = Deck()
    all_cards = list(deck._cards)
    state.bottom_deck = all_cards[:BOTTOM_SIZE]
    for i, p in enumerate(state.players):
        start = BOTTOM_SIZE + i * HAND_SIZE
        p.hand = all_cards[start : start + HAND_SIZE]
    state.tricks_won = {p.id: [] for p in state.players}
    return state


def _make_state() -> GameState:
    return GameState(
        players=_make_players(),
        mode="upgrade",
        round_leader_id="p0",
    )


# ---------------------------------------------------------------------------
# set_hand
# ---------------------------------------------------------------------------

class TestSetHand:
    def test_replaces_hand(self):
        state = _make_playing_state()
        new_cards = [_card(Suit.SPADES, Rank.ACE), _card(Suit.SPADES, Rank.KING)]
        set_hand(state, "p0", new_cards)
        assert state.players[0].hand == new_cards

    def test_unknown_player_raises(self):
        state = _make_state()
        with pytest.raises(ValueError, match="Unknown player_id"):
            set_hand(state, "ghost", [])

    def test_returns_warnings_when_card_count_wrong(self):
        state = _make_playing_state()
        # Remove cards from p0 without redistributing → card count drops
        warnings = set_hand(state, "p0", [])
        assert any("107" in w or "Total" in w for w in warnings)

    def test_no_warnings_when_count_remains_108(self):
        """Swap p0's hand with the bottom deck — total stays 108."""
        state = _make_playing_state()
        old_bottom = list(state.bottom_deck)
        old_hand = list(state.players[0].hand)
        # Swap: put old hand into bottom, put old bottom into p0
        state.bottom_deck = old_hand
        warnings = set_hand(state, "p0", old_bottom)
        assert warnings == []

    def test_mutation_is_isolated_to_one_player(self):
        state = _make_playing_state()
        hand_p1_before = list(state.players[1].hand)
        set_hand(state, "p0", [])
        assert state.players[1].hand == hand_p1_before


# ---------------------------------------------------------------------------
# set_bottom
# ---------------------------------------------------------------------------

class TestSetBottom:
    def test_replaces_bottom_deck(self):
        state = _make_playing_state()
        new_bottom = [_card(Suit.CLUBS, Rank.FIVE)] * BOTTOM_SIZE
        set_bottom(state, new_bottom)
        assert state.bottom_deck == new_bottom

    def test_returns_warnings_on_count_mismatch(self):
        state = _make_playing_state()
        old_bottom = list(state.bottom_deck)
        # Replace bottom with fewer cards (7) → card count drops by 1
        warnings = set_bottom(state, old_bottom[:7])
        assert len(warnings) > 0

    def test_no_warnings_after_card_neutral_swap(self):
        state = _make_playing_state()
        # Replace bottom with same cards (no-op in terms of count)
        same = list(state.bottom_deck)
        warnings = set_bottom(state, same)
        assert warnings == []


# ---------------------------------------------------------------------------
# set_points
# ---------------------------------------------------------------------------

class TestSetPoints:
    def test_overrides_attacking_points(self):
        state = _make_state()
        set_points(state, 250)
        assert state.attacking_points == 250

    def test_negative_points_returns_warning(self):
        state = _make_state()
        warnings = set_points(state, -10)
        assert any("attacking_points" in w for w in warnings)

    def test_zero_points_no_warning(self):
        state = _make_state()
        warnings = set_points(state, 0)
        assert not any("attacking_points" in w for w in warnings)

    def test_large_value_accepted_without_error(self):
        state = _make_state()
        # Superuser may intentionally set extreme values
        warnings = set_points(state, 9999)
        # No exception; just returns whatever warnings exist
        assert isinstance(warnings, list)


# ---------------------------------------------------------------------------
# force_phase
# ---------------------------------------------------------------------------

class TestForcePhase:
    def test_sets_phase_directly(self):
        state = _make_state()
        assert state.phase == GamePhase.WAITING
        force_phase(state, GamePhase.PLAYING)
        assert state.phase == GamePhase.PLAYING

    def test_bypasses_transition_graph(self):
        """Can jump to GAME_OVER from WAITING (impossible via transition_to)."""
        state = _make_state()
        force_phase(state, GamePhase.GAME_OVER)
        assert state.phase == GamePhase.GAME_OVER

    def test_returns_warnings_when_state_inconsistent(self):
        """Forcing PLAYING without trump_context should produce a warning."""
        state = _make_state()
        warnings = force_phase(state, GamePhase.PLAYING)
        assert any("trump_context" in w for w in warnings)

    def test_no_warnings_when_consistent(self):
        state = _make_playing_state()
        # Already in PLAYING; force to SCORING — state is still consistent
        warnings = force_phase(state, GamePhase.SCORING)
        assert warnings == []


# ---------------------------------------------------------------------------
# deal_specific_hands
# ---------------------------------------------------------------------------

class TestDealSpecificHands:
    def _hands_and_bottom(self):
        """Build a deterministic 108-card distribution."""
        from shengji.models.deck import Deck

        all_cards = list(Deck()._cards)
        bottom = all_cards[:BOTTOM_SIZE]
        hands = {}
        for i in range(NUM_PLAYERS):
            start = BOTTOM_SIZE + i * HAND_SIZE
            hands[f"p{i}"] = all_cards[start : start + HAND_SIZE]
        return hands, bottom

    def test_sets_all_hands(self):
        state = _make_state()
        hands, bottom = self._hands_and_bottom()
        deal_specific_hands(state, hands, bottom)
        for i, p in enumerate(state.players):
            assert p.hand == hands[f"p{i}"]

    def test_sets_bottom(self):
        state = _make_state()
        hands, bottom = self._hands_and_bottom()
        deal_specific_hands(state, hands, bottom)
        assert state.bottom_deck == bottom

    def test_draw_pile_cleared(self):
        state = _make_state()
        state.draw_pile = [_card(Suit.SPADES, Rank.ACE)]  # stale
        hands, bottom = self._hands_and_bottom()
        deal_specific_hands(state, hands, bottom)
        assert state.draw_pile == []

    def test_no_warnings_when_108_cards(self):
        state = _make_state()
        hands, bottom = self._hands_and_bottom()
        warnings = deal_specific_hands(state, hands, bottom)
        assert warnings == []

    def test_unknown_player_raises(self):
        state = _make_state()
        with pytest.raises(ValueError, match="Unknown player_id"):
            deal_specific_hands(state, {"ghost": []}, [])

    def test_can_be_played_through_engine(self):
        """After deal_specific_hands, the engine can play tricks normally."""
        from shengji.engine.engine import GameEngine
        from shengji.engine.tricks import get_legal_plays
        from shengji.models.groups import classify_play

        state = _make_state()
        state.trump_context = TrumpContext(
            trump_rank=Rank.TWO, trump_suit=Suit.HEARTS
        )
        state.current_turn_id = "p0"
        state.round_leader_id = "p0"
        state.phase = GamePhase.PLAYING
        hands, bottom = self._hands_and_bottom()
        deal_specific_hands(state, hands, bottom)

        class _Stub:
            def assign_teams(self, s): pass
            def needs_friend_declaration(self): return False
            def validate_friend_declaration(self, s, d): pass
            def resolve_friend(self, s, pid, c): pass
            def on_round_end(self, s, w): pass
            def get_attacker_ids(self, s): return {"p1", "p3"}
            def get_next_leader(self, s, w): return "p0"

        engine = GameEngine(state, _Stub(), deal_delay=0)
        lead_card = state.players[0].hand[0]
        result = engine.play_cards("p0", [lead_card])
        assert result["trick_complete"] is False
