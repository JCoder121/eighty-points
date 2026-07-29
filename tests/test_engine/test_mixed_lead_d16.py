"""D16 — a lead whose cards span more than one effective suit is rejected.

Decision D16 (docs/RULES.md, Q1) rules that a lead is a claim about *one*
suit.  A mixed-suit lead is **malformed**: it raises ValueError and leaves the
state untouched.  It is explicitly NOT a throw-penalty case — R71's forced
component and 10 pts/card only apply to *beatable single-suit* throws.

The check lives at the lead level rather than inside the Throw branch, so it
also covers the cross-suit plays that the classifier calls a Tractor (audit
F1: ``3♠3♠ + 4♦4♦``), which never reach the Throw branch at all.

Trump is one suit: jokers, trump-rank cards of any suit and trump-suit cards
all have effective suit ``"trump"``, so an all-trump lead stays legal.
"""
from __future__ import annotations

import pytest

from shengji.engine.engine import GameEngine
from shengji.models.card import Card, Rank, Suit
from shengji.models.game_state import GamePhase, GameState
from shengji.models.player import Player
from shengji.models.trump import TrumpContext
from shengji.modes.upgrade import UpgradeStrategy


def _c(suit: Suit, rank: Rank) -> Card:
    return Card(suit=suit, rank=rank)


A_S, K_S, Q_S, J_S = (_c(Suit.SPADES, r) for r in
                      (Rank.ACE, Rank.KING, Rank.QUEEN, Rank.JACK))
T_S, N_S, TH_S, FO_S = (_c(Suit.SPADES, r) for r in
                        (Rank.TEN, Rank.NINE, Rank.THREE, Rank.FOUR))
A_H, K_H, TH_H, FO_H = (_c(Suit.HEARTS, r) for r in
                        (Rank.ACE, Rank.KING, Rank.THREE, Rank.FOUR))
A_D, K_D, TH_D, FO_D, FI_D = (_c(Suit.DIAMONDS, r) for r in
                              (Rank.ACE, Rank.KING, Rank.THREE, Rank.FOUR, Rank.FIVE))
A_C, K_C, TH_C, FO_C = (_c(Suit.CLUBS, r) for r in
                        (Rank.ACE, Rank.KING, Rank.THREE, Rank.FOUR))
TWO_S = _c(Suit.SPADES, Rank.TWO)
TWO_H = _c(Suit.HEARTS, Rank.TWO)
TWO_D = _c(Suit.DIAMONDS, Rank.TWO)
SJ = _c(Suit.JOKER, Rank.SMALL_JOKER)
BJ = _c(Suit.JOKER, Rank.BIG_JOKER)


def _make_engine(hands: dict[str, list[Card]], *, trump_suit: Suit | None = Suit.HEARTS):
    players = [Player(id=f"p{i}", name=f"P{i}") for i in range(4)]
    state = GameState(players=players, mode="upgrade", round_leader_id="p0")
    state.phase = GamePhase.PLAYING
    state.trump_context = TrumpContext(trump_rank=Rank.TWO, trump_suit=trump_suit)
    state.tricks_won = {p.id: [] for p in players}
    state.current_turn_id = "p0"
    state.current_leader_id = "p0"
    for p in players:
        p.hand = list(hands[p.id])
    engine = GameEngine(state, UpgradeStrategy(), deal_delay=0)
    UpgradeStrategy().assign_teams(state)
    return engine


# ---------------------------------------------------------------------------
# Rejection
# ---------------------------------------------------------------------------

class TestMixedSuitLeadRejected:
    def test_two_singles_in_different_suits_is_rejected(self):
        # Q1's repro: A♥ + A♣ with ♠ trump classifies as Throw(Single, Single)
        # and passes validation when nobody holds a higher heart or club.
        engine = _make_engine({
            "p0": [A_H, A_C],
            "p1": [TH_H, TH_C],
            "p2": [FO_H, FO_C],
            "p3": [TH_S, FO_S],
        }, trump_suit=Suit.SPADES)

        with pytest.raises(ValueError, match="single suit"):
            engine.play_cards("p0", [A_H, A_C])

    def test_cross_suit_tractor_lead_is_rejected(self):
        # Audit F1: 3♠3♠ + 4♦4♦ currently classifies as Tractor(2, 2), skips
        # throw validation entirely and is accepted.
        engine = _make_engine({
            "p0": [TH_S, TH_S, FO_D, FO_D],
            "p1": [A_S, K_S, A_D, K_D],
            "p2": [Q_S, J_S, TH_C, FO_C],
            "p3": [T_S, N_S, TH_H, FO_H],
        })

        with pytest.raises(ValueError, match="single suit"):
            engine.play_cards("p0", [TH_S, TH_S, FO_D, FO_D])

    def test_rejection_is_order_independent(self):
        engine = _make_engine({
            "p0": [TH_S, TH_S, FO_D, FO_D],
            "p1": [A_S, K_S, A_D, K_D],
            "p2": [Q_S, J_S, TH_C, FO_C],
            "p3": [T_S, N_S, TH_H, FO_H],
        })

        with pytest.raises(ValueError, match="single suit"):
            engine.play_cards("p0", [FO_D, FO_D, TH_S, TH_S])

    def test_trump_plus_offsuit_lead_is_rejected(self):
        # ♥ trump: 3♥ is trump, 4♦ is not — two effective suits.
        engine = _make_engine({
            "p0": [TH_H, FO_D],
            "p1": [A_H, A_D],
            "p2": [K_H, K_D],
            "p3": [TH_S, FO_S],
        })

        with pytest.raises(ValueError, match="single suit"):
            engine.play_cards("p0", [TH_H, FO_D])


class TestRejectionIsNotAPenalty:
    def test_no_penalty_recorded_and_state_unmutated(self):
        engine = _make_engine({
            "p0": [K_S, A_D],
            "p1": [A_S, K_D],
            "p2": [Q_S, TH_D],
            "p3": [J_S, FO_D],
        })
        state = engine.state
        hand_before = list(state.players[0].hand)

        with pytest.raises(ValueError, match="single suit"):
            engine.play_cards("p0", [K_S, A_D])

        # R71 must not fire: no forced component, no 10 pts/card.
        assert state.throw_penalties == {}
        # Nothing about the trick moved.
        assert state.players[0].hand == hand_before
        assert state.current_trick == []
        assert state.led_format is None
        assert state.led_suit is None
        assert state.current_turn_id == "p0"

    def test_leader_can_still_lead_legally_afterwards(self):
        engine = _make_engine({
            "p0": [K_S, A_D],
            "p1": [A_S, K_D],
            "p2": [Q_S, TH_D],
            "p3": [J_S, FO_D],
        })
        with pytest.raises(ValueError):
            engine.play_cards("p0", [K_S, A_D])

        engine.play_cards("p0", [K_S])
        assert engine.state.current_trick == [("p0", [K_S])]
        assert engine.state.led_suit == "spades"


# ---------------------------------------------------------------------------
# All-trump leads are ONE suit
# ---------------------------------------------------------------------------

class TestAllTrumpLeadsStayLegal:
    def test_joker_plus_trump_rank_trump_suit_throw_is_accepted(self):
        # ♠ trump, rank 2: SJ, 2♠ and 3♠ all have effective suit "trump".
        # Unbeatable here — nobody else holds a joker, so no penalty either.
        engine = _make_engine({
            "p0": [SJ, TWO_S, TH_S],
            "p1": [A_H, K_H, Q_S],
            "p2": [A_D, K_D, J_S],
            "p3": [A_C, K_C, T_S],
        }, trump_suit=Suit.SPADES)

        result = engine.play_cards("p0", [SJ, TWO_S])

        assert "throw_failed" not in result
        assert engine.state.led_suit == "trump"
        assert engine.state.current_trick == [("p0", [SJ, TWO_S])]

    def test_offsuit_trump_rank_counts_as_trump_in_a_lead(self):
        # 2♥ / 2♦ are trump-rank cards of non-trump suits: still "trump".
        engine = _make_engine({
            "p0": [BJ, TWO_H, TWO_D],
            "p1": [A_H, K_H, Q_S],
            "p2": [A_D, K_D, J_S],
            "p3": [A_C, K_C, T_S],
        }, trump_suit=Suit.SPADES)

        result = engine.play_cards("p0", [BJ, TWO_H, TWO_D])

        assert engine.state.led_suit == "trump"
        assert len(engine.state.current_trick[0][1]) == 3
        assert "throw_failed" not in result

    def test_beatable_all_trump_throw_still_takes_the_penalty_path(self):
        # D16 must not swallow R71: an all-trump (one suit) throw that IS
        # beatable is still validated normally and charged.
        engine = _make_engine({
            "p0": [K_S, Q_S],
            "p1": [A_S, TH_H],
            "p2": [K_D, TH_D],
            "p3": [K_C, TH_C],
        }, trump_suit=Suit.SPADES)

        result = engine.play_cards("p0", [K_S, Q_S])

        assert result["throw_failed"] is True
        assert result["forced_cards"] == [Q_S]
        assert engine.state.throw_penalties == {"p0": 20}


class TestSingleSuitLeadsUnaffected:
    def test_unbeatable_single_suit_throw_still_accepted(self):
        engine = _make_engine({
            "p0": [A_S, K_S],
            "p1": [TH_H, FO_H],
            "p2": [TH_D, FO_D],
            "p3": [TH_C, FO_C],
        })

        result = engine.play_cards("p0", [A_S, K_S])

        assert "throw_failed" not in result
        assert engine.state.led_suit == "spades"


# ---------------------------------------------------------------------------
# Followers are unaffected (R43 mixed follows stay legal)
# ---------------------------------------------------------------------------

class TestFollowersUnaffected:
    def test_void_follower_may_still_play_a_mixed_suit_fill(self):
        engine = _make_engine({
            "p0": [A_S, K_S],
            "p1": [TH_H, FO_D],   # void in spades
            "p2": [TH_D, FO_C],
            "p3": [TH_C, FO_H],
        })

        engine.play_cards("p0", [A_S, K_S])
        engine.play_cards("p1", [TH_H, FO_D])

        assert engine.state.current_trick[1] == ("p1", [TH_H, FO_D])
