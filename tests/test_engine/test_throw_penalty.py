"""Failed-throw penalty tests.

A leader's throw (甩牌) whose components can be beaten is no longer rejected:
the leader is forced to lead only the smallest beatable component and
concedes 10 pts per attempted card.  Penalties are recorded per player in
GameState.throw_penalties and attributed to teams at round end using FINAL
team membership (Find Friends reveals can flip the thrower's team).
"""
from __future__ import annotations

from shengji.engine.engine import GameEngine
from shengji.models.card import Card, Rank, Suit
from shengji.models.friend_declaration import FriendDeclaration
from shengji.models.game_state import GamePhase, GameState
from shengji.models.player import Player
from shengji.models.trump import TrumpContext
from shengji.modes.find_friends import FindFriendsStrategy
from shengji.modes.upgrade import UpgradeStrategy


def _c(suit: Suit, rank: Rank) -> Card:
    return Card(suit=suit, rank=rank)


A_S = _c(Suit.SPADES, Rank.ACE)
K_S = _c(Suit.SPADES, Rank.KING)
Q_S = _c(Suit.SPADES, Rank.QUEEN)
T_S = _c(Suit.SPADES, Rank.TEN)
N_S = _c(Suit.SPADES, Rank.NINE)
E_S = _c(Suit.SPADES, Rank.EIGHT)
S_S = _c(Suit.SPADES, Rank.SEVEN)
X_S = _c(Suit.SPADES, Rank.SIX)
F_S = _c(Suit.SPADES, Rank.FIVE)
FO_S = _c(Suit.SPADES, Rank.FOUR)
TH_S = _c(Suit.SPADES, Rank.THREE)

TH_D = _c(Suit.DIAMONDS, Rank.THREE)
FO_D = _c(Suit.DIAMONDS, Rank.FOUR)
FI_D = _c(Suit.DIAMONDS, Rank.FIVE)
EI_D = _c(Suit.DIAMONDS, Rank.EIGHT)


def _make_engine(strategy, hands: dict[str, list[Card]], trick_leader: str = "p0"):
    """Build an engine directly in PLAYING with controlled hands.

    ``round_leader_id`` is always p0 (drives team assignment); the leader of
    the first trick may be someone else via ``trick_leader``.
    """
    players = [Player(id=f"p{i}", name=f"P{i}") for i in range(4)]
    state = GameState(players=players, mode="upgrade", round_leader_id="p0")
    state.phase = GamePhase.PLAYING
    state.trump_context = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS)
    state.tricks_won = {p.id: [] for p in players}
    state.current_turn_id = trick_leader
    state.current_leader_id = trick_leader
    for p in players:
        p.hand = list(hands[p.id])
    engine = GameEngine(state, strategy, deal_delay=0)
    strategy.assign_teams(state)
    return engine


# ---------------------------------------------------------------------------
# Forced component substitution
# ---------------------------------------------------------------------------

class TestForcedComponent:
    def test_failed_throw_forces_weakest_component_and_records_penalty(self):
        # p1 holds A♠ → both K♠ and Q♠ singles are beatable; the weaker Q♠
        # is forced.  Penalty = 10 × 2 attempted cards.
        engine = _make_engine(UpgradeStrategy(), {
            "p0": [K_S, Q_S],
            "p1": [A_S, TH_S],
            "p2": [FO_S, F_S],
            "p3": [X_S, S_S],
        })
        result = engine.play_cards("p0", [K_S, Q_S])

        assert result["throw_failed"] is True
        assert result["forced_cards"] == [Q_S]
        assert result["attempted_cards"] == [K_S, Q_S]
        assert result["penalty"] == 20
        assert engine.state.throw_penalties == {"p0": 20}
        # The unplayed card stays in hand; only the forced card was led.
        assert engine.state.players[0].hand == [K_S]
        assert engine.state.current_trick == [("p0", [Q_S])]

    def test_smallest_beatable_component_prefers_fewest_cards(self):
        # Throw K♠K♠ + 10♠: p1's A♠A♠ beats the pair AND a lone A♠ beats the
        # single — the SMALLEST (fewest cards) component, 10♠, is forced.
        engine = _make_engine(UpgradeStrategy(), {
            "p0": [K_S, K_S, T_S],
            "p1": [A_S, A_S, TH_S],
            "p2": [FO_S, F_S, X_S],
            "p3": [S_S, E_S, N_S],
        })
        result = engine.play_cards("p0", [K_S, K_S, T_S])

        assert result["throw_failed"] is True
        assert result["forced_cards"] == [T_S]
        assert result["penalty"] == 30
        assert sorted(c.rank.value for c in engine.state.players[0].hand) == ["K", "K"]

    def test_trick_proceeds_with_forced_component_and_conserves_cards(self):
        engine = _make_engine(UpgradeStrategy(), {
            "p0": [K_S, Q_S],
            "p1": [A_S, TH_S],
            "p2": [FO_S, F_S],
            "p3": [X_S, S_S],
        })
        state = engine.state
        total_before = sum(len(p.hand) for p in state.players)

        engine.play_cards("p0", [K_S, Q_S])          # forced to Q♠
        engine.play_cards("p1", [TH_S])
        engine.play_cards("p2", [FO_S])
        result = engine.play_cards("p3", [X_S])

        assert result["trick_complete"] is True
        assert result["trick_winner"] == "p0"        # Q♠ is the highest played
        # Card conservation: 4 cards in the trick pile, the rest in hands.
        trick_cards = sum(len(t) for ts in state.tricks_won.values() for t in ts)
        in_hands = sum(len(p.hand) for p in state.players)
        assert trick_cards == 4
        assert trick_cards + in_hands == total_before
        assert state.players[0].hand == [K_S]

    def test_valid_throw_is_unchanged(self):
        # No opponent can beat A♠ or K♠ (thrower holds the visible A♠ and no
        # opponent holds one) — throw goes through with no penalty.
        engine = _make_engine(UpgradeStrategy(), {
            "p0": [A_S, K_S],
            "p1": [TH_S, FO_S],
            "p2": [F_S, X_S],
            "p3": [S_S, E_S],
        })
        result = engine.play_cards("p0", [A_S, K_S])

        assert "throw_failed" not in result
        assert engine.state.throw_penalties == {}
        assert engine.state.players[0].hand == []
        assert engine.state.current_trick == [("p0", [A_S, K_S])]

    def test_start_dealing_resets_penalties(self):
        players = [Player(id=f"p{i}", name=f"P{i}") for i in range(4)]
        state = GameState(players=players, mode="upgrade", round_leader_id="p0")
        state.throw_penalties = {"p0": 40}
        engine = GameEngine(state, UpgradeStrategy(), deal_delay=0)
        engine.start_dealing()
        assert state.throw_penalties == {}


# ---------------------------------------------------------------------------
# End-of-round attribution
# ---------------------------------------------------------------------------

def _play_out(engine: GameEngine, tricks: list[list[tuple[str, list[Card]]]]):
    for trick in tricks:
        for pid, cards in trick:
            engine.play_cards(pid, cards)


class TestEndRoundAttribution:
    def test_defender_thrower_adds_penalty_to_attacking_points(self):
        # Upgrade: p0 leads → p0/p2 defend, p1/p3 attack.  p0's throw fails.
        engine = _make_engine(UpgradeStrategy(), {
            "p0": [K_S, Q_S],
            "p1": [A_S, TH_S],
            "p2": [FO_S, F_S],
            "p3": [X_S, S_S],
        })
        engine.play_cards("p0", [K_S, Q_S])          # forced Q♠, penalty 20
        _play_out(engine, [
            [("p1", [TH_S]), ("p2", [FO_S]), ("p3", [X_S])],   # p0 wins (Q♠)
            # Trick 2: p0 leads K♠; p1's A♠ wins K(10) + 5♠(5) = 15 pts.
            [("p0", [K_S]), ("p1", [A_S]), ("p2", [F_S]), ("p3", [S_S])],
        ])
        assert engine.state.phase == GamePhase.SCORING

        result = engine.end_round()
        # 15 trick pts + 20 penalty (defender p0 threw → attackers gain).
        assert result["throw_penalty_adjustment"] == 20
        assert result["attacking_points"] == 35
        assert result["winner"] == "defending"

    def test_attacker_thrower_deducts_penalty_clamped_at_zero(self):
        # p1 (attacker) leads the first trick and fails a throw; attackers
        # win no points, so 0 − 20 clamps to 0.
        engine = _make_engine(UpgradeStrategy(), {
            "p0": [X_S, S_S],
            "p1": [K_S, Q_S],
            "p2": [A_S, TH_S],
            "p3": [FO_S, F_S],
        }, trick_leader="p1")
        engine.play_cards("p1", [K_S, Q_S])          # forced Q♠, penalty 20
        _play_out(engine, [
            [("p2", [TH_S]), ("p3", [FO_S]), ("p0", [X_S])],   # p1 wins (Q♠)
            # Trick 2: p2 (defender) takes K(10) + 5(5) — attackers get 0.
            [("p1", [K_S]), ("p2", [A_S]), ("p3", [F_S]), ("p0", [S_S])],
        ])

        result = engine.end_round()
        assert result["throw_penalty_adjustment"] == -20
        assert result["attacking_points"] == 0
        assert result["winner"] == "defending"

    def test_find_friends_penalty_uses_final_team_after_reveal(self):
        # p1 fails a throw while still an ATTACKER, then reveals as the
        # friend (plays the declared 8♦) — the penalty must be attributed by
        # the FINAL team: p1 defends, so attackers GAIN the 20 pts.
        strategy = FindFriendsStrategy()
        engine = _make_engine(strategy, {
            "p1": [K_S, Q_S, EI_D],
            "p2": [A_S, F_S, TH_D],
            "p3": [TH_S, FO_S, FO_D],
            "p0": [X_S, S_S, FI_D],
        }, trick_leader="p1")
        state = engine.state
        state.friend_declarations = [
            FriendDeclaration(card=_c(Suit.DIAMONDS, Rank.EIGHT), ordinal=1)
        ]
        assert not state.players[1].is_defending  # p1 starts as attacker

        engine.play_cards("p1", [K_S, Q_S])          # forced Q♠, penalty 20
        _play_out(engine, [
            [("p2", [F_S]), ("p3", [TH_S]), ("p0", [X_S])],    # p1 wins (Q♠)
            # p1 plays the declared friend card → flips to defending.
            [("p1", [EI_D]), ("p2", [TH_D]), ("p3", [FO_D]), ("p0", [FI_D])],
            # p2 (attacker) wins the last trick: K(10) pts.
            [("p1", [K_S]), ("p2", [A_S]), ("p3", [FO_S]), ("p0", [S_S])],
        ])
        assert state.players[1].is_defending        # friend revealed

        result = engine.end_round()
        # Attackers (p2, p3): 10 trick pts + 20 penalty from defender p1.
        assert result["throw_penalty_adjustment"] == 20
        assert result["attacking_points"] == 30
