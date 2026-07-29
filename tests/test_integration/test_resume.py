"""Resuming a game at configured levels — engine-visible consequences.

The lobby half of this feature lives in ``tests/test_network/test_room_setup.py``.
What is pinned here is what the *engine* has to do differently once a game
starts from a resume configuration (2026-07-29 assessment §2.3, §2.4):

  R18 / R11   a configured leader keeps the lead through bidding — the winning
              bid fixes the trump suit only, exactly as in round 2+
  R12 / D01   the trump rank for the round is the configured leader's level
  R82 / D19   resuming *at* Ace is a legal, playable defend-at-Ace round, and
              it is one successful defense from ending the game
"""
from __future__ import annotations

import random

import pytest

from shengji.engine.engine import GameEngine
from shengji.models.card import Rank
from shengji.models.game_state import GamePhase, GameState
from shengji.modes.upgrade import UpgradeStrategy
from shengji.network.room import RoomSetup, apply_setup

from tests.test_integration.helpers import D, H, S, c, ctx, make_state

TR = ctx(trump_rank=Rank.TWO, trump_suit=H)


def _resumed_state(
    ranks: list[str],
    leader_seat: int = 0,
    round_number: int = 2,
    mode: str = "upgrade",
) -> tuple[GameState, RoomSetup]:
    """A 4-player WAITING state with a resume configuration applied by seat."""
    state = make_state(mode, round_leader_id="p0")
    setup = RoomSetup.from_json({
        "starting_ranks": ranks,
        "starting_leader_seat": leader_seat,
        "starting_round_number": round_number,
    })
    apply_setup(state, setup)
    return state, setup


def _to_bidding(state: GameState) -> None:
    state.transition_to(GamePhase.DEALING)
    state.transition_to(GamePhase.BIDDING_AFTER_DEAL)


# ---------------------------------------------------------------------------
# R18 — a configured leader is a predetermined leader
# ---------------------------------------------------------------------------

class TestResumedLeaderSurvivesBidding:
    def _bid_and_close(self, state: GameState, bidder: str) -> GameEngine:
        engine = GameEngine(state, UpgradeStrategy(), deal_delay=0)
        trump_rank = engine._player(state.round_leader_id).rank
        card = c(H, trump_rank)
        engine._player(bidder).hand.append(card)
        _to_bidding(state)
        engine.place_bid(bidder, [card])
        engine.close_bidding()
        return engine

    def test_bid_winner_does_not_take_the_lead(self):
        """Even with round_number pinned to 1 — the flag, not the number, is
        what makes a resumed leader predetermined."""
        state, _ = _resumed_state(
            ["5", "5", "K", "K"], leader_seat=2, round_number=1
        )
        assert state.round_leader_id == "p2"
        self._bid_and_close(state, bidder="p0")
        assert state.round_leader_id == "p2"

    def test_bid_still_fixes_the_trump_suit(self):
        state, _ = _resumed_state(["5", "5", "K", "K"], leader_seat=2)
        self._bid_and_close(state, bidder="p0")
        assert state.trump_context.trump_suit == H

    def test_teams_follow_the_configured_leaders_seat(self):
        """Upgrade partners are seats 0/2 vs 1/3; the leader's parity picks
        which pair defends.  Seat 2 leading means seats 0 and 2 defend."""
        state, _ = _resumed_state(["5", "5", "K", "K"], leader_seat=2)
        self._bid_and_close(state, bidder="p1")
        defending = {p.id for p in state.players if p.is_defending}
        assert defending == {"p0", "p2"}

    def test_leader_can_win_the_bid_themselves(self):
        state, _ = _resumed_state(["5", "5", "K", "K"], leader_seat=2)
        self._bid_and_close(state, bidder="p2")
        assert state.round_leader_id == "p2"

    def test_ordinary_round_one_still_hands_the_lead_to_the_bid_winner(self):
        """Regression guard: a game with no resume setup is untouched (R11)."""
        state = make_state("upgrade", round_leader_id="p0")
        assert state.leader_predetermined is False
        assert state.round_number == 1
        self._bid_and_close(state, bidder="p3")
        assert state.round_leader_id == "p3"


# ---------------------------------------------------------------------------
# R12 / D01 — the trump rank is the configured leader's level
# ---------------------------------------------------------------------------

class TestResumedTrumpRank:
    @pytest.mark.parametrize("leader_seat,expected", [
        (0, Rank.FIVE), (2, Rank.KING), (3, Rank.KING),
    ])
    def test_trump_rank_is_the_leading_seats_level(self, leader_seat, expected):
        state, _ = _resumed_state(["5", "5", "K", "K"], leader_seat=leader_seat)
        engine = GameEngine(state, UpgradeStrategy(), deal_delay=0)
        card = c(S, expected)
        engine._player("p1").hand.append(card)
        _to_bidding(state)
        bid = engine.place_bid("p1", [card])
        assert bid.resulting_trump.trump_rank == expected

    def test_a_card_of_the_wrong_rank_is_not_a_bid(self):
        state, _ = _resumed_state(["5", "5", "K", "K"], leader_seat=2)
        engine = GameEngine(state, UpgradeStrategy(), deal_delay=0)
        five = c(S, Rank.FIVE)
        engine._player("p1").hand.append(five)
        _to_bidding(state)
        with pytest.raises(ValueError):
            engine.place_bid("p1", [five])

    def test_the_real_deal_derives_the_same_rank(self):
        """Setup is applied before dealing, so nothing extra is needed to make
        the trump rank come out right — it falls out of round_leader_id."""
        state, _ = _resumed_state(["5", "5", "K", "K"], leader_seat=2)
        engine = GameEngine(
            state, UpgradeStrategy(), deal_delay=0, rng=random.Random(7)
        )
        engine.start_dealing()
        while engine.deal_next_card() is not None:
            pass
        assert state.phase == GamePhase.BIDDING_AFTER_DEAL
        # The deal starts from the seat after the leader (seat 3).
        assert len(state.players[3].hand) == 25
        bidder, card = next(
            (p.id, card)
            for p in state.players
            for card in p.hand
            if card.rank == Rank.KING
        )
        bid = engine.place_bid(bidder, [card])
        assert bid.resulting_trump.trump_rank == Rank.KING


# ---------------------------------------------------------------------------
# R82 / D19 — resuming at Ace
# ---------------------------------------------------------------------------

def _scoring_state_from_setup(
    ranks: list[str], leader_seat: int, attacker_pts: int
) -> tuple[GameEngine, GameState]:
    """Drive a resumed state to SCORING with *attacker_pts* captured.

    Teams come from the real strategy, so which pair defends follows from the
    configured leading seat.
    """
    state, _ = _resumed_state(ranks, leader_seat=leader_seat, round_number=9)
    engine = GameEngine(state, UpgradeStrategy(), deal_delay=0)
    state.trump_context = TR
    engine.mode.assign_teams(state)
    attacker = next(p for p in state.players if not p.is_defending)
    defender = next(p for p in state.players if p.is_defending)
    kings = [c(S, Rank.KING)] * (attacker_pts // 10)
    state.tricks_won = {p.id: [] for p in state.players}
    state.tricks_won[defender.id] = [[c(D, Rank.THREE)]]
    if kings:
        state.tricks_won[attacker.id] = [kings]
    state.bottom_deck = []
    state.current_leader_id = defender.id
    state.last_winning_play = [c(D, Rank.THREE)]
    state.phase = GamePhase.SCORING
    return engine, state


class TestResumeAtAce:
    def test_a_table_of_aces_starts_playable_not_over(self):
        state, _ = _resumed_state(["A", "A", "A", "A"], leader_seat=1)
        assert state.phase == GamePhase.WAITING
        assert [p.rank for p in state.players] == [Rank.ACE] * 4
        engine = GameEngine(
            state, UpgradeStrategy(), deal_delay=0, rng=random.Random(3)
        )
        engine.start_dealing()
        while engine.deal_next_card() is not None:
            pass
        assert state.phase == GamePhase.BIDDING_AFTER_DEAL
        assert all(len(p.hand) == 25 for p in state.players)

    def test_defending_at_ace_ends_the_game(self):
        """A resumed Ace defender is one successful defense from winning —
        game over uses PRE-advance ranks, so no round of advancement first."""
        engine, state = _scoring_state_from_setup(
            ["A", "5", "A", "5"], leader_seat=0, attacker_pts=70
        )
        result = engine.end_round()
        assert result["winner"] == "defending"
        assert result["game_over"] is True
        assert state.phase == GamePhase.GAME_OVER

    def test_attacking_at_ace_does_not_end_the_game(self):
        """The Ace pair is attacking here (seat 1 leads, so seats 1/3 defend).
        Winning as attackers takes over the defense; it does not win."""
        engine, state = _scoring_state_from_setup(
            ["A", "5", "A", "5"], leader_seat=1, attacker_pts=100
        )
        result = engine.end_round()
        assert result["winner"] == "attacking"
        assert result["game_over"] is False
        assert state.phase == GamePhase.ROUND_OVER

    def test_a_resumed_ace_defender_who_loses_keeps_playing(self):
        engine, state = _scoring_state_from_setup(
            ["A", "5", "A", "5"], leader_seat=0, attacker_pts=90
        )
        result = engine.end_round()
        assert result["winner"] == "attacking"
        assert result["game_over"] is False
        assert state.round_number == 10  # resumed at 9, incremented normally

    def test_ranks_still_clamp_at_ace(self):
        engine, state = _scoring_state_from_setup(
            ["A", "5", "A", "5"], leader_seat=0, attacker_pts=0  # defending +3
        )
        engine.end_round()
        assert {p.rank for p in state.players if p.id in ("p0", "p2")} == {Rank.ACE}
