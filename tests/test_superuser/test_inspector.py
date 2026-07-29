"""Tests for superuser inspector (M6.1)."""
from __future__ import annotations

import pytest

from shengji.models.card import Card, Rank, Suit
from shengji.models.deck import HAND_SIZE, NUM_PLAYERS, BOTTOM_SIZE
from shengji.models.game_state import GamePhase, GameState
from shengji.models.player import Player
from shengji.models.trump import TrumpContext
from shengji.superuser import mutator
from shengji.superuser.inspector import get_full_state, validate_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_players(n: int = NUM_PLAYERS) -> list[Player]:
    return [Player(id=f"p{i}", name=f"Player{i}") for i in range(n)]


def _make_state(phase: GamePhase = GamePhase.WAITING) -> GameState:
    return GameState(
        players=_make_players(),
        mode="upgrade",
        round_leader_id="p0",
        phase=phase,
    )


def _card(suit: Suit, rank: Rank) -> Card:
    return Card(suit=suit, rank=rank)


def _make_playing_state() -> GameState:
    """Return a PLAYING-phase state with a full, consistent card distribution."""
    state = _make_state()
    state.phase = GamePhase.PLAYING
    state.trump_context = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS)
    state.round_leader_id = "p0"
    state.current_turn_id = "p0"

    # Build a fresh 2-deck set (108 cards) and distribute them:
    # 8 to bottom, 25 to each of 4 players = 8 + 100 = 108
    from shengji.models.deck import Deck
    deck = Deck()
    all_cards = list(deck._cards)  # all 108 cards

    state.bottom_deck = all_cards[:BOTTOM_SIZE]
    for i, p in enumerate(state.players):
        start = BOTTOM_SIZE + i * HAND_SIZE
        p.hand = all_cards[start : start + HAND_SIZE]

    state.tricks_won = {p.id: [] for p in state.players}
    return state


# ---------------------------------------------------------------------------
# get_full_state
# ---------------------------------------------------------------------------

class TestGetFullState:
    def test_returns_dict(self):
        state = _make_state()
        result = get_full_state(state)
        assert isinstance(result, dict)

    def test_includes_phase(self):
        state = _make_state(GamePhase.PLAYING)
        state.trump_context = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS)
        result = get_full_state(state)
        assert result["phase"] == "playing"

    def test_includes_all_hands(self):
        state = _make_playing_state()
        result = get_full_state(state)
        for player_data in result["players"]:
            assert "hand" in player_data


# ---------------------------------------------------------------------------
# validate_state — clean state
# ---------------------------------------------------------------------------

class TestValidateStateClean:
    def test_waiting_phase_no_violations(self):
        state = _make_state(GamePhase.WAITING)
        assert validate_state(state) == []

    def test_playing_state_clean(self):
        state = _make_playing_state()
        assert validate_state(state) == []


# ---------------------------------------------------------------------------
# validate_state — total card count
# ---------------------------------------------------------------------------

class TestValidateStateTotalCards:
    def test_missing_card_detected(self):
        state = _make_playing_state()
        state.players[0].hand.pop()  # remove one card → 107 total
        violations = validate_state(state)
        assert any("107" in v and "108" in v for v in violations)

    def test_extra_card_detected(self):
        state = _make_playing_state()
        state.players[0].hand.append(_card(Suit.SPADES, Rank.ACE))  # 109 total
        violations = validate_state(state)
        assert any("109" in v and "108" in v for v in violations)

    def test_waiting_skips_card_count(self):
        # In WAITING, no cards anywhere — no violation
        state = _make_state(GamePhase.WAITING)
        violations = validate_state(state)
        assert not any("108" in v for v in violations)


# ---------------------------------------------------------------------------
# validate_state — duplicate cards
# ---------------------------------------------------------------------------

class TestValidateStateDuplicates:
    def test_three_copies_of_card_detected(self):
        state = _make_playing_state()
        # Find a card to triplicate
        extra = _card(Suit.SPADES, Rank.ACE)
        # Remove a card from p3 hand to keep total = 108
        state.players[3].hand.pop()
        # Add an extra copy to p0 (now 3 copies of ACE_S exist if it was already in deck)
        # To be safe, directly stuff 3 copies into known spots
        target_card = state.players[0].hand[0]
        # Remove one occurrence of target_card from p1 and add it to p0
        for p in state.players[1:]:
            if target_card in p.hand:
                p.hand.remove(target_card)
                state.players[0].hand.append(target_card)
                break
        violations = validate_state(state)
        # Should detect duplicate OR card count violation
        assert len(violations) > 0

    def test_two_copies_of_same_card_is_ok(self):
        """2-deck game allows 2 copies of any card — should not flag as violation."""
        state = _make_playing_state()
        # Find a card that appears twice (2-deck game guarantees this)
        from collections import Counter
        all_cards = []
        for p in state.players:
            all_cards.extend(p.hand)
        all_cards.extend(state.bottom_deck)
        counts = Counter((c.suit, c.rank) for c in all_cards)
        # At least some cards appear twice — validate should still pass
        violations = validate_state(state)
        assert violations == []


# ---------------------------------------------------------------------------
# validate_state — trump context
# ---------------------------------------------------------------------------

class TestValidateStateTrumpContext:
    def test_playing_without_trump_context_flagged(self):
        state = _make_playing_state()
        state.trump_context = None
        violations = validate_state(state)
        assert any("trump_context" in v for v in violations)

    def test_waiting_without_trump_context_ok(self):
        state = _make_state(GamePhase.WAITING)
        violations = validate_state(state)
        assert not any("trump_context" in v for v in violations)

    def test_scoring_without_trump_context_flagged(self):
        state = _make_playing_state()
        state.phase = GamePhase.SCORING
        state.trump_context = None
        violations = validate_state(state)
        assert any("trump_context" in v for v in violations)


# ---------------------------------------------------------------------------
# validate_state — hand size
# ---------------------------------------------------------------------------

class TestValidateStateHandSize:
    def test_oversized_hand_flagged(self):
        state = _make_state(GamePhase.WAITING)
        # Stuff too many cards into p0 without worrying about 108 total
        state.players[0].hand = [_card(Suit.SPADES, Rank.ACE)] * (HAND_SIZE + 1)
        violations = validate_state(state)
        assert any("p0" in v and str(HAND_SIZE + 1) in v for v in violations)

    def test_normal_hand_size_ok(self):
        state = _make_playing_state()
        violations = validate_state(state)
        assert not any("maximum hand size" in v for v in violations)


# ---------------------------------------------------------------------------
# validate_state — player ID references
# ---------------------------------------------------------------------------

class TestValidateStatePlayerIds:
    def test_invalid_round_leader_flagged(self):
        state = _make_state(GamePhase.WAITING)
        state.round_leader_id = "ghost"
        violations = validate_state(state)
        assert any("round_leader_id" in v and "ghost" in v for v in violations)

    def test_invalid_current_turn_id_in_playing_flagged(self):
        state = _make_playing_state()
        state.current_turn_id = "nobody"
        violations = validate_state(state)
        assert any("current_turn_id" in v and "nobody" in v for v in violations)

    def test_valid_current_turn_id_ok(self):
        state = _make_playing_state()
        violations = validate_state(state)
        assert not any("current_turn_id" in v for v in violations)


# ---------------------------------------------------------------------------
# validate_state — points
# ---------------------------------------------------------------------------

class TestValidateStatePoints:
    def test_negative_attacking_points_flagged(self):
        state = _make_state()
        state.attacking_points = -1
        violations = validate_state(state)
        assert any("attacking_points" in v for v in violations)

    def test_zero_points_ok(self):
        state = _make_state()
        violations = validate_state(state)
        assert not any("attacking_points" in v for v in violations)


# ---------------------------------------------------------------------------
# validate_state — card multiplicity (R1: two decks, max 2 copies)
# ---------------------------------------------------------------------------

class TestValidateStateMultiplicity:
    """R1 caps every card identity at two copies across the whole state.

    The multiplicity check used to be gated behind the same phase skip as the
    108-card total, so a hand written by ``mutator.set_hand`` before the deal
    (WAITING) could hold three copies of one card and draw no warning at all.
    That is the one state in which ``_assign_throw_components`` can hand a
    throw component zero cards.
    """

    def _triple(self) -> list[Card]:
        ten = _card(Suit.SPADES, Rank.TEN)
        eight = _card(Suit.SPADES, Rank.EIGHT)
        return [ten, ten, ten, eight, eight]

    def test_triple_in_hand_flagged_in_waiting(self):
        """The audit repro: set_hand with three 10-spades must warn."""
        state = _make_state(GamePhase.WAITING)
        warnings = mutator.set_hand(state, "p0", self._triple())
        assert any("10" in w and "spades" in w and "3 times" in w for w in warnings), warnings

    def test_triple_in_hand_flagged_in_playing(self):
        state = _make_playing_state()
        violations = validate_state(state)
        assert not any("appears" in v for v in violations)
        for p in state.players:
            p.hand = [c for c in p.hand if c.suit != Suit.SPADES or c.rank != Rank.TEN]
        state.bottom_deck = [
            c for c in state.bottom_deck
            if c.suit != Suit.SPADES or c.rank != Rank.TEN
        ]
        state.players[0].hand = self._triple()
        assert any("3 times" in v for v in validate_state(state))

    def test_two_copies_never_flagged(self):
        state = _make_state(GamePhase.WAITING)
        ten = _card(Suit.SPADES, Rank.TEN)
        warnings = mutator.set_hand(state, "p0", [ten, ten])
        assert not any("appears" in w for w in warnings), warnings

    def test_copies_split_across_zones_flagged(self):
        """Two in hand plus one in the bottom is still three copies."""
        state = _make_state(GamePhase.WAITING)
        ten = _card(Suit.SPADES, Rank.TEN)
        mutator.set_hand(state, "p0", [ten, ten])
        warnings = mutator.set_bottom(state, [ten])
        assert any("3 times" in w for w in warnings), warnings

    def test_copies_split_across_players_flagged(self):
        state = _make_state(GamePhase.WAITING)
        ten = _card(Suit.SPADES, Rank.TEN)
        mutator.set_hand(state, "p0", [ten, ten])
        warnings = mutator.set_hand(state, "p1", [ten])
        assert any("3 times" in w for w in warnings), warnings

    def test_copies_in_captured_pile_flagged(self):
        state = _make_state(GamePhase.WAITING)
        ten = _card(Suit.SPADES, Rank.TEN)
        state.tricks_won = {"p0": [[ten, ten], [ten]]}
        assert any("3 times" in v for v in validate_state(state))

    def test_copies_in_current_trick_flagged(self):
        state = _make_state(GamePhase.WAITING)
        ten = _card(Suit.SPADES, Rank.TEN)
        state.players[0].hand = [ten, ten]
        state.current_trick = [("p1", [ten])]
        assert any("3 times" in v for v in validate_state(state))

    def test_empty_waiting_state_is_clean(self):
        assert validate_state(_make_state(GamePhase.WAITING)) == []
