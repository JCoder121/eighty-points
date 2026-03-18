"""Tests for play_cards and full trick lifecycle (M4.5).

These tests wire together dealing, bidding, exchange, and playing to verify
the full round loop works end-to-end.
"""
from __future__ import annotations

import pytest

from shengji.engine.engine import GameEngine
from shengji.models.card import Card, Rank, Suit
from shengji.models.deck import NUM_PLAYERS, HAND_SIZE
from shengji.models.game_state import GamePhase, GameState
from shengji.models.player import Player
from shengji.models.trump import TrumpContext


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _UpgradeStub:
    def needs_friend_declaration(self) -> bool:
        return False

    def validate_friend_declaration(self, state, declarations) -> None:
        raise RuntimeError("Not applicable")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_player(idx: int) -> Player:
    return Player(id=f"p{idx}", name=f"Player{idx}")


def _make_state() -> GameState:
    players = [_make_player(i) for i in range(NUM_PLAYERS)]
    return GameState(
        players=players,
        mode="upgrade",
        round_leader_id="p0",
    )


def _make_engine(state: GameState | None = None) -> GameEngine:
    if state is None:
        state = _make_state()
    return GameEngine(state, _UpgradeStub(), deal_delay=0)


def _setup_playing(engine: GameEngine) -> None:
    """Deal, bid, exchange, and transition to PLAYING with a known trump context."""
    engine.start_dealing()
    while engine.state.draw_pile:
        engine.deal_next_card()

    # Give p0 a trump card and bid
    trump = Card(Suit.HEARTS, Rank.TWO)
    p0 = engine._player("p0")
    p0.hand[0] = trump  # replace first card to keep count at 25
    engine.place_bid("p0", [trump])
    engine.close_bidding()

    # exchange_bottom: put back the existing bottom deck as-is
    put_back = list(engine.state.bottom_deck)
    engine.exchange_bottom("p0", put_back)
    # phase is now PLAYING, current_turn_id = round_leader_id = p0


# ---------------------------------------------------------------------------
# play_cards — preconditions
# ---------------------------------------------------------------------------

class TestPlayCardsPreconditions:
    def setup_method(self):
        self.engine = _make_engine()
        _setup_playing(self.engine)

    def test_wrong_phase_raises(self):
        self.engine.state.phase = GamePhase.BOTTOM_EXCHANGE
        card = self.engine._player("p0").hand[0]
        with pytest.raises(ValueError, match="PLAYING"):
            self.engine.play_cards("p0", [card])

    def test_out_of_turn_raises(self):
        card = self.engine._player("p1").hand[0]
        with pytest.raises(ValueError, match="turn"):
            self.engine.play_cards("p1", [card])

    def test_card_not_in_hand_raises(self):
        phantom = Card(Suit.CLUBS, Rank.ACE)
        self.engine._player("p0").hand = [c for c in self.engine._player("p0").hand if c != phantom]
        with pytest.raises(ValueError, match="not in"):
            self.engine.play_cards("p0", [phantom])


# ---------------------------------------------------------------------------
# play_cards — single trick
# ---------------------------------------------------------------------------

class TestSingleTrick:
    def setup_method(self):
        self.engine = _make_engine()
        _setup_playing(self.engine)
        self.state = self.engine.state
        # Give each player a controlled hand (all singles, known order)
        # p0 leads
        ctx = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS)
        self.engine.state.trump_context = ctx

    def test_leader_plays_reduces_hand(self):
        p0_hand = self.engine._player("p0").hand
        card = p0_hand[0]
        count_before = p0_hand.count(card)
        self.engine.play_cards("p0", [card])
        count_after = self.engine._player("p0").hand.count(card)
        # Exactly one copy removed (duplicates possible in 2-deck game)
        assert count_after == count_before - 1
        assert len(self.engine._player("p0").hand) == HAND_SIZE - 1

    def test_trick_appended(self):
        card = self.engine._player("p0").hand[0]
        self.engine.play_cards("p0", [card])
        assert len(self.state.current_trick) == 1

    def test_turn_advances_after_play(self):
        card = self.engine._player("p0").hand[0]
        self.engine.play_cards("p0", [card])
        assert self.state.current_turn_id == "p1"

    def test_trick_not_complete_after_one_play(self):
        card = self.engine._player("p0").hand[0]
        result = self.engine.play_cards("p0", [card])
        assert result["trick_complete"] is False

    def test_full_trick_resolves_winner(self):
        """Play one full trick with 4 players and verify a winner is determined."""
        # Give each player one distinct spade so we can predict the winner
        ctx = self.state.trump_context
        cards = [
            Card(Suit.SPADES, Rank.ACE),
            Card(Suit.SPADES, Rank.KING),
            Card(Suit.SPADES, Rank.QUEEN),
            Card(Suit.SPADES, Rank.JACK),
        ]
        for i, pid in enumerate(["p0", "p1", "p2", "p3"]):
            self.engine._player(pid).hand = [cards[i]] + [Card(Suit.CLUBS, Rank.THREE)] * (HAND_SIZE - 1)

        r0 = self.engine.play_cards("p0", [cards[0]])
        assert r0["trick_complete"] is False
        r1 = self.engine.play_cards("p1", [cards[1]])
        assert r1["trick_complete"] is False
        r2 = self.engine.play_cards("p2", [cards[2]])
        assert r2["trick_complete"] is False
        r3 = self.engine.play_cards("p3", [cards[3]])

        assert r3["trick_complete"] is True
        assert r3["trick_winner"] == "p0"  # A♠ wins

    def test_winner_leads_next_trick(self):
        cards = [
            Card(Suit.SPADES, Rank.ACE),
            Card(Suit.SPADES, Rank.KING),
            Card(Suit.SPADES, Rank.QUEEN),
            Card(Suit.SPADES, Rank.JACK),
        ]
        for i, pid in enumerate(["p0", "p1", "p2", "p3"]):
            self.engine._player(pid).hand = [cards[i]] + [Card(Suit.CLUBS, Rank.THREE)] * (HAND_SIZE - 1)

        for pid, card in zip(["p0", "p1", "p2", "p3"], cards):
            self.engine.play_cards(pid, [card])

        assert self.state.current_turn_id == "p0"  # A♠ winner leads again

    def test_trick_winner_gets_cards_in_tricks_won(self):
        cards = [
            Card(Suit.SPADES, Rank.ACE),
            Card(Suit.SPADES, Rank.KING),
            Card(Suit.SPADES, Rank.QUEEN),
            Card(Suit.SPADES, Rank.JACK),
        ]
        for i, pid in enumerate(["p0", "p1", "p2", "p3"]):
            self.engine._player(pid).hand = [cards[i]] + [Card(Suit.CLUBS, Rank.THREE)] * (HAND_SIZE - 1)

        for pid, card in zip(["p0", "p1", "p2", "p3"], cards):
            self.engine.play_cards(pid, [card])

        won = self.state.tricks_won["p0"]
        assert len(won) == 1
        assert len(won[0]) == 4

    def test_trick_number_increments(self):
        cards = [
            Card(Suit.SPADES, Rank.ACE),
            Card(Suit.SPADES, Rank.KING),
            Card(Suit.SPADES, Rank.QUEEN),
            Card(Suit.SPADES, Rank.JACK),
        ]
        for i, pid in enumerate(["p0", "p1", "p2", "p3"]):
            self.engine._player(pid).hand = [cards[i]] + [Card(Suit.CLUBS, Rank.THREE)] * (HAND_SIZE - 1)

        assert self.state.trick_number == 1
        for pid, card in zip(["p0", "p1", "p2", "p3"], cards):
            self.engine.play_cards(pid, [card])
        assert self.state.trick_number == 2

    def test_trump_beats_led_suit(self):
        """A trump card beats the led non-trump card."""
        ctx = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS)
        self.state.trump_context = ctx
        # p0 leads A♠, p1 plays 2♠ (trump rank off-suit = tier 2), p2 & p3 play low spades
        cards_by_player = {
            "p0": [Card(Suit.SPADES, Rank.ACE)],
            "p1": [Card(Suit.SPADES, Rank.TWO)],  # trump rank card
            "p2": [Card(Suit.SPADES, Rank.KING)],
            "p3": [Card(Suit.SPADES, Rank.QUEEN)],
        }
        for pid, cards in cards_by_player.items():
            self.engine._player(pid).hand = cards + [Card(Suit.CLUBS, Rank.THREE)] * (HAND_SIZE - 1)

        for pid in ["p0", "p1", "p2", "p3"]:
            self.engine.play_cards(pid, cards_by_player[pid])

        # 2♠ is trump (tier 2) > A♠ (tier 0)
        assert self.state.tricks_won["p1"] != []


# ---------------------------------------------------------------------------
# Full round (25 tricks → SCORING)
# ---------------------------------------------------------------------------

def _play_one_trick_auto(engine: GameEngine) -> None:
    """Play one full trick using get_legal_plays to determine follower responses."""
    from shengji.engine.tricks import get_legal_plays
    from shengji.models.groups import classify_play

    state = engine.state
    ctx = state.trump_context

    # Leader plays their first card
    leader_id = state.current_turn_id
    lead_card = engine._player(leader_id).hand[0]
    engine.play_cards(leader_id, [lead_card])
    led_fmt = classify_play([lead_card], ctx)
    led_suit = ctx.effective_suit(lead_card)

    # Followers play legal cards
    for _ in range(NUM_PLAYERS - 1):
        follower_id = state.current_turn_id
        follower_hand = engine._player(follower_id).hand
        legal = get_legal_plays(follower_hand, led_fmt, led_suit, ctx)
        engine.play_cards(follower_id, legal[0])


class TestFullRound:
    def setup_method(self):
        self.engine = _make_engine()
        _setup_playing(self.engine)
        self.state = self.engine.state

    def test_full_round_reaches_scoring(self):
        """Playing all 25 tricks transitions to SCORING."""
        while self.state.phase == GamePhase.PLAYING:
            _play_one_trick_auto(self.engine)
        assert self.state.phase == GamePhase.SCORING

    def test_all_cards_accounted_for_after_round(self):
        """After all tricks, every card should be in tricks_won or bottom_deck."""
        while self.state.phase == GamePhase.PLAYING:
            _play_one_trick_auto(self.engine)

        tricks_cards = [
            c
            for pid in self.state.tricks_won
            for trick in self.state.tricks_won[pid]
            for c in trick
        ]
        total = len(tricks_cards) + len(self.state.bottom_deck)
        assert total == 108

    def test_all_hands_empty_after_round(self):
        """All players should have empty hands once SCORING is reached."""
        while self.state.phase == GamePhase.PLAYING:
            _play_one_trick_auto(self.engine)

        for p in self.state.players:
            assert len(p.hand) == 0

    def test_exactly_25_tricks_played(self):
        """Each round is exactly 25 tricks."""
        while self.state.phase == GamePhase.PLAYING:
            _play_one_trick_auto(self.engine)

        total_tricks = sum(
            len(tricks) for tricks in self.state.tricks_won.values()
        )
        assert total_tricks == 25
