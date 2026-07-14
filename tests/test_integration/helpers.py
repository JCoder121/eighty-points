"""Shared helpers for the integration edge-case suite (M9 backfill).

Unlike the unit suites (tests/test_engine, tests/test_models), these tests
drive the real GameEngine with the real mode strategies end to end.  The
superuser mutator is used only to force deterministic card layouts.
"""
from __future__ import annotations

from shengji.engine.engine import GameEngine
from shengji.models.card import Card, Rank, Suit
from shengji.models.deck import NUM_PLAYERS
from shengji.models.game_state import GamePhase, GameState
from shengji.models.player import Player
from shengji.models.trump import TrumpContext
from shengji.modes.find_friends import FindFriendsStrategy
from shengji.modes.upgrade import UpgradeStrategy
from shengji.superuser import mutator

S, H, D, CL = Suit.SPADES, Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS
SJ = Card(Suit.JOKER, Rank.SMALL_JOKER)
BJ = Card(Suit.JOKER, Rank.BIG_JOKER)


def c(suit: Suit, rank: Rank) -> Card:
    return Card(suit=suit, rank=rank)


def ctx(trump_rank: Rank = Rank.TWO, trump_suit: Suit | None = Suit.HEARTS) -> TrumpContext:
    return TrumpContext(trump_rank=trump_rank, trump_suit=trump_suit)


def make_players(ranks: dict[str, Rank] | None = None) -> list[Player]:
    players = [Player(id=f"p{i}", name=f"P{i}") for i in range(NUM_PLAYERS)]
    if ranks:
        for p in players:
            if p.id in ranks:
                p.rank = ranks[p.id]
    return players


def make_state(
    mode: str = "upgrade",
    round_leader_id: str = "p0",
    ranks: dict[str, Rank] | None = None,
) -> GameState:
    return GameState(players=make_players(ranks), mode=mode, round_leader_id=round_leader_id)


def make_engine(
    mode: str = "upgrade",
    round_leader_id: str = "p0",
    ranks: dict[str, Rank] | None = None,
) -> tuple[GameEngine, GameState]:
    """Build a real GameEngine over a fresh state; returns (engine, state)."""
    state = make_state(mode, round_leader_id, ranks)
    strategy = UpgradeStrategy() if mode == "upgrade" else FindFriendsStrategy()
    return GameEngine(state, strategy, deal_delay=0), state


def setup_playing(
    engine: GameEngine,
    hands: dict[str, list[Card]],
    bottom: list[Card],
    trump: TrumpContext,
) -> None:
    """Force a state straight into PLAYING with deterministic hands + trump.

    Skips WAITING -> DEALING -> BIDDING -> EXCHANGE for determinism, but
    assigns teams through the real strategy so is_defending is correct.
    """
    state = engine.state
    mutator.deal_specific_hands(state, hands, bottom)
    state.trump_context = trump
    engine.mode.assign_teams(state)  # leader's side defends
    state.phase = GamePhase.PLAYING
    state.current_leader_id = state.round_leader_id
    state.current_turn_id = state.round_leader_id
