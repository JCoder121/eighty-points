"""Gap-pin tests: level bands, game over, leader rotation, bidding round 1.

Pins behavior that the 2026-07-29 audit found CORRECT but untested
(docs/reports/2026-07-29-rules-audit.md §6, edge-case matrix Tier B):

  R83        the 80-99 "+0 takeover" band can never end the game
  R84 / #52  game over needs defenders ALREADY at Ace, not advancing into it
  D14 / C9   rank advancement clamps at Ace from every starting rank
  R80 / R81  defenders win → partner leads next round at their own level
  R11        the round-1 placeholder leader is replaced by the bid winner
  R13 / R25  bid cards are shown, not spent — and may then be buried
"""
from __future__ import annotations

from shengji.engine.engine import GameEngine
from shengji.models.card import Rank
from shengji.models.game_state import GamePhase, GameState
from shengji.modes.upgrade import UpgradeStrategy

from tests.test_integration.helpers import D, H, S, c, ctx, make_state

TR = ctx(trump_rank=Rank.TWO, trump_suit=H)


def _scoring_state(
    defender_ranks: dict[str, Rank], attacker_pts: int
) -> tuple[GameEngine, GameState]:
    """SCORING-phase Upgrade state: p0/p2 defend, p1/p3 attack with
    *attacker_pts* captured (as Kings). A defender won the last trick."""
    state = make_state("upgrade", "p0", ranks=defender_ranks)
    engine = GameEngine(state, UpgradeStrategy(), deal_delay=0)
    state.trump_context = TR
    for p in state.players:
        p.is_defending = p.id in ("p0", "p2")
        p.team = "defending" if p.is_defending else "attacking"
    kings = [c(S, Rank.KING)] * (attacker_pts // 10)
    state.tricks_won = {
        "p0": [[c(D, Rank.THREE)]],
        "p1": [kings] if kings else [],
        "p2": [],
        "p3": [],
    }
    state.bottom_deck = []
    state.current_leader_id = "p0"
    state.last_winning_play = [c(D, Rank.THREE)]
    state.phase = GamePhase.SCORING
    return engine, state


class TestTakeoverBandNeverEndsGame:
    def test_r83_90_points_with_defenders_at_ace(self):
        """R83: 80-99 means winner="attacking" with steps=0 — the defenders
        LOST, so even a full-Ace defending pair cannot trigger game over."""
        engine, state = _scoring_state(
            {"p0": Rank.ACE, "p2": Rank.ACE}, attacker_pts=90
        )
        result = engine.end_round()
        assert result["winner"] == "attacking"
        assert result["steps"] == 0
        assert result["game_over"] is False
        assert state.phase == GamePhase.ROUND_OVER


class TestGameOverAtAce:
    def test_r84_defenders_already_at_ace_win_ends_game(self):
        engine, state = _scoring_state(
            {"p0": Rank.ACE, "p2": Rank.ACE}, attacker_pts=70  # defending +1
        )
        result = engine.end_round()
        assert result["winner"] == "defending"
        assert result["game_over"] is True
        assert result["next_round_leader_id"] is None
        assert state.phase == GamePhase.GAME_OVER

    def test_r84_advancing_into_ace_does_not_end_game(self):
        """#52: King + 1 lands ON Ace but the check uses pre-advance ranks."""
        engine, state = _scoring_state(
            {"p0": Rank.KING, "p2": Rank.KING}, attacker_pts=70  # defending +1
        )
        result = engine.end_round()
        assert result["winner"] == "defending"
        assert engine._player("p0").rank == Rank.ACE
        assert result["game_over"] is False
        assert state.phase == GamePhase.ROUND_OVER


class TestAdvancementClampsAtAce:
    """D14 / matrix C9: only the Q+3 clamp was previously pinned."""

    def test_jack_plus_four_clamps_to_ace(self):
        # 0-19 attacker points → defending +4; J +4 would pass Ace.
        engine, _ = _scoring_state({"p0": Rank.JACK, "p2": Rank.JACK}, 10)
        result = engine.end_round()
        assert result["steps"] == 4
        assert engine._player("p0").rank == Rank.ACE
        assert engine._player("p2").rank == Rank.ACE
        assert result["game_over"] is False  # pre-advance rank was J

    def test_king_plus_three_clamps_to_ace(self):
        # 20-39 attacker points → defending +3.
        engine, _ = _scoring_state({"p0": Rank.KING, "p2": Rank.KING}, 30)
        result = engine.end_round()
        assert result["steps"] == 3
        assert engine._player("p0").rank == Rank.ACE
        assert result["game_over"] is False


class TestLeaderRotationAndTrumpRank:
    def test_r80_r81_defenders_win_partner_leads_at_own_level(self):
        """R80: defending win → the leader's partner (seat +2) leads next.
        R81/R12: the next trump rank is the NEW leader's level."""
        engine, state = _scoring_state(
            {"p0": Rank.FIVE, "p2": Rank.FIVE}, attacker_pts=70  # defending +1
        )
        result = engine.end_round()
        assert result["next_round_leader_id"] == "p2"
        assert state.round_leader_id == "p2"
        # R12 derives the trump rank from the leader's level at deal time;
        # p2 advanced FIVE -> SIX with the win.
        assert engine._player("p2").rank == Rank.SIX


class TestRound1BiddingPins:
    def _dealt_engine(self) -> tuple[GameEngine, GameState]:
        """A round-1 state mid-BIDDING: p0 is the placeholder leader (room
        creator); p1 holds a pair of trump-rank spades plus filler."""
        state = make_state("upgrade", "p0")
        engine = GameEngine(state, UpgradeStrategy(), deal_delay=0)
        state.phase = GamePhase.DEALING
        state.transition_to(GamePhase.BIDDING_AFTER_DEAL)
        # A legal 25-card hand for the bidder: the trump-rank pair plus 23
        # filler cards, never more than 2 copies of one identity (R1).
        filler_ranks = [
            Rank.THREE, Rank.FOUR, Rank.FIVE, Rank.SIX, Rank.SEVEN, Rank.EIGHT,
            Rank.NINE, Rank.TEN, Rank.JACK, Rank.QUEEN, Rank.KING, Rank.ACE,
        ]
        filler = [c(H, r) for r in filler_ranks] + [c(D, r) for r in filler_ranks]
        engine._player("p1").hand = [c(S, Rank.TWO), c(S, Rank.TWO)] + filler[:23]
        for pid in ("p0", "p2", "p3"):
            engine._player(pid).hand = [c(D, Rank.THREE), c(D, Rank.FOUR)]
        state.round_number = 1
        return engine, state

    def test_r11_bid_winner_replaces_placeholder_leader(self):
        engine, state = self._dealt_engine()
        engine.place_bid("p1", [c(S, Rank.TWO), c(S, Rank.TWO)])
        engine.close_bidding()
        assert state.round_leader_id == "p1"
        assert state.trump_context is not None
        assert state.trump_context.trump_suit == S
        assert state.trump_context.trump_rank == Rank.TWO

    def test_r13_r25_bid_cards_stay_in_hand_and_may_be_buried(self):
        engine, state = self._dealt_engine()
        pair = [c(S, Rank.TWO), c(S, Rank.TWO)]
        engine.place_bid("p1", pair)
        assert engine._player("p1").hand.count(c(S, Rank.TWO)) == 2, (
            "R13: bid cards are shown, not spent"
        )
        engine.close_bidding()
        assert state.phase == GamePhase.BOTTOM_EXCHANGE
        # The new leader picks up the 8-card bottom and may bury the very
        # cards they showed as the winning bid (D06).
        state.bottom_deck = [c(S, r) for r in (
            Rank.THREE, Rank.FOUR, Rank.FIVE, Rank.SIX,
            Rank.SEVEN, Rank.EIGHT, Rank.NINE, Rank.TEN,
        )]
        leader_hand = engine._player("p1").hand
        bury = pair + [card for card in leader_hand if card.suit != S][:6]
        engine.exchange_bottom("p1", bury)
        assert engine._player("p1").hand.count(c(S, Rank.TWO)) == 0
        assert state.bottom_deck.count(c(S, Rank.TWO)) == 2
