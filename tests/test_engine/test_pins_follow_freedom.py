"""Gap pins for follower freedom and Tractor(2,3) follow obligations.

Behavior probed and found correct during the Phase-2 audit (edge-case matrix
cells 1.16, 1.25, 1.26, 1.27 — Tier C1/C3).  Rule numbers refer to
``docs/RULES.md``.

Covered:
  R48   there is no "must beat if able" rule — a follower holding a winning
        card may play a losing one, and a void follower need not trump
  R49   off-suit fill has no shape obligation: a void or short follower may
        break their own pairs and their own trump tractor
  R46   Tractor(2,3) leads (every committed tractor-follow test uses length 2)
"""
from __future__ import annotations

from shengji.engine.engine import GameEngine
from shengji.engine.tricks import is_valid_follow
from shengji.models.card import Card, Rank, Suit
from shengji.models.game_state import GamePhase, GameState
from shengji.models.groups import Tractor, classify_play
from shengji.models.player import Player
from shengji.models.trump import TrumpContext
from shengji.modes.upgrade import UpgradeStrategy


def _c(suit: Suit, rank: Rank) -> Card:
    return Card(suit=suit, rank=rank)


def _s(rank: Rank) -> Card:
    return _c(Suit.SPADES, rank)


def _d(rank: Rank) -> Card:
    return _c(Suit.DIAMONDS, rank)


def _h(rank: Rank) -> Card:
    return _c(Suit.HEARTS, rank)


CTX = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS)


def _make_engine(hands: dict[str, list[Card]]) -> GameEngine:
    """Upgrade engine in PLAYING with controlled hands; p0 leads."""
    players = [Player(id=f"p{i}", name=f"P{i}") for i in range(4)]
    state = GameState(players=players, mode="upgrade", round_leader_id="p0")
    state.phase = GamePhase.PLAYING
    state.trump_context = CTX
    state.tricks_won = {p.id: [] for p in players}
    state.current_turn_id = "p0"
    state.current_leader_id = "p0"
    for p in players:
        p.hand = list(hands[p.id])
    strategy = UpgradeStrategy()
    engine = GameEngine(state, strategy, deal_delay=0)
    strategy.assign_teams(state)
    return engine


def _fmt(cards: list[Card]):
    return classify_play(cards, CTX)


# ---------------------------------------------------------------------------
# R48 — no obligation to play high
# ---------------------------------------------------------------------------

class TestNoMustBeatRule:
    def test_follower_holding_the_ace_may_play_a_losing_spade(self):
        # p1 could take the trick with A♠ and instead ducks with 3♠.  The
        # engine accepts it and p0 wins — R48 has no "must beat" check.
        engine = _make_engine({
            "p0": [_s(Rank.KING), _s(Rank.TWO)],
            "p1": [_s(Rank.ACE), _s(Rank.THREE)],
            "p2": [_s(Rank.FOUR), _s(Rank.FIVE)],
            "p3": [_s(Rank.SIX), _s(Rank.SEVEN)],
        })
        engine.play_cards("p0", [_s(Rank.KING)])
        engine.play_cards("p1", [_s(Rank.THREE)])
        engine.play_cards("p2", [_s(Rank.FOUR)])
        result = engine.play_cards("p3", [_s(Rank.SIX)])

        assert result["trick_winner"] == "p0"
        assert engine.state.players[1].hand == [_s(Rank.ACE)]

    def test_void_follower_need_not_trump(self):
        # p1 is void in spades and holds trump A♥; discarding a diamond is
        # legal, so the non-trump lead survives.
        engine = _make_engine({
            "p0": [_s(Rank.KING), _s(Rank.TWO)],
            "p1": [_h(Rank.ACE), _d(Rank.THREE)],
            "p2": [_s(Rank.FOUR), _s(Rank.FIVE)],
            "p3": [_s(Rank.SIX), _s(Rank.SEVEN)],
        })
        engine.play_cards("p0", [_s(Rank.KING)])
        engine.play_cards("p1", [_d(Rank.THREE)])
        engine.play_cards("p2", [_s(Rank.FOUR)])
        result = engine.play_cards("p3", [_s(Rank.SIX)])

        assert result["trick_winner"] == "p0"
        assert engine.state.players[1].hand == [_h(Rank.ACE)]

    def test_lower_pair_is_legal_over_a_higher_one(self):
        # Pair lead, follower holds two pairs — R45 requires *some* pair, R48
        # never requires the winning one.
        hand = [_s(Rank.ACE), _s(Rank.ACE), _s(Rank.FOUR), _s(Rank.FOUR)]
        led = _fmt([_s(Rank.KING), _s(Rank.KING)])
        assert is_valid_follow([_s(Rank.FOUR), _s(Rank.FOUR)], hand, led, "spades", CTX)


# ---------------------------------------------------------------------------
# R49 — off-suit fill has no shape obligation
# ---------------------------------------------------------------------------

class TestFillCardsHaveNoShapeObligation:
    def test_void_follower_may_break_their_own_pair(self):
        # Pair lead in spades, follower void: K♦K♦ and K♦Q♦ are BOTH legal.
        hand = [_d(Rank.KING), _d(Rank.KING), _d(Rank.QUEEN)]
        led = _fmt([_s(Rank.KING), _s(Rank.KING)])
        assert is_valid_follow([_d(Rank.KING), _d(Rank.KING)], hand, led, "spades", CTX)
        assert is_valid_follow([_d(Rank.KING), _d(Rank.QUEEN)], hand, led, "spades", CTX)

    def test_void_follower_may_break_their_own_trump_tractor(self):
        # Tractor(2,2) lead in spades; the follower is void and holds the trump
        # tractor A♥A♥K♥K♥.  Keeping it together and tearing it apart are both
        # legal — R43 lets a void follower play any n cards.
        hand = [
            _h(Rank.ACE), _h(Rank.ACE), _h(Rank.KING), _h(Rank.KING),
            _d(Rank.THREE), _d(Rank.FOUR),
        ]
        lead = [_s(Rank.ACE), _s(Rank.ACE), _s(Rank.KING), _s(Rank.KING)]
        led = _fmt(lead)
        assert isinstance(led, Tractor)
        assert is_valid_follow(
            [_h(Rank.ACE), _h(Rank.ACE), _h(Rank.KING), _h(Rank.KING)],
            hand, led, "spades", CTX,
        )
        assert is_valid_follow(
            [_h(Rank.ACE), _h(Rank.KING), _d(Rank.THREE), _d(Rank.FOUR)],
            hand, led, "spades", CTX,
        )

    def test_short_follower_breaks_an_off_suit_pair_for_the_fill(self):
        # Three spades against a 4-card tractor lead: all three spades are
        # compulsory (R43) and the single fill slot splits the K♦ pair.
        hand = [
            _s(Rank.ACE), _s(Rank.ACE), _s(Rank.TEN),
            _d(Rank.KING), _d(Rank.KING),
        ]
        led = _fmt([_s(Rank.ACE), _s(Rank.ACE), _s(Rank.KING), _s(Rank.KING)])
        assert is_valid_follow(
            [_s(Rank.ACE), _s(Rank.ACE), _s(Rank.TEN), _d(Rank.KING)],
            hand, led, "spades", CTX,
        )
        # Keeping the diamond pair intact means abandoning a compulsory spade.
        assert not is_valid_follow(
            [_s(Rank.ACE), _s(Rank.ACE), _d(Rank.KING), _d(Rank.KING)],
            hand, led, "spades", CTX,
        )


# ---------------------------------------------------------------------------
# R46 — Tractor(2,3) leads (6 cards)
# ---------------------------------------------------------------------------

class TestTractorLengthThreeFollow:
    """Every committed tractor-follow test uses Tractor(2,2); the obligation is
    structural and must scale to a 6-card lead."""

    LEAD = [
        _s(Rank.ACE), _s(Rank.ACE), _s(Rank.KING), _s(Rank.KING),
        _s(Rank.QUEEN), _s(Rank.QUEEN),
    ]

    def _led(self):
        fmt = _fmt(self.LEAD)
        assert isinstance(fmt, Tractor) and fmt.length == 3
        return fmt

    def test_six_card_tractor_in_hand_must_be_played_whole(self):
        hand = [
            _s(Rank.TEN), _s(Rank.TEN), _s(Rank.NINE), _s(Rank.NINE),
            _s(Rank.EIGHT), _s(Rank.EIGHT), _s(Rank.FIVE), _s(Rank.FIVE),
        ]
        led = self._led()
        assert is_valid_follow(
            [_s(Rank.TEN), _s(Rank.TEN), _s(Rank.NINE), _s(Rank.NINE),
             _s(Rank.EIGHT), _s(Rank.EIGHT)],
            hand, led, "spades", CTX,
        )
        # Substituting the spare pair for two tractor pairs drops the play from
        # 6 tractor cards to 4.
        assert not is_valid_follow(
            [_s(Rank.TEN), _s(Rank.TEN), _s(Rank.NINE), _s(Rank.NINE),
             _s(Rank.FIVE), _s(Rank.FIVE)],
            hand, led, "spades", CTX,
        )

    def test_four_card_tractor_plus_a_pair_satisfies_the_lead(self):
        hand = [
            _s(Rank.TEN), _s(Rank.TEN), _s(Rank.NINE), _s(Rank.NINE),
            _s(Rank.SIX), _s(Rank.SIX), _s(Rank.FOUR), _s(Rank.THREE),
        ]
        led = self._led()
        assert is_valid_follow(
            [_s(Rank.TEN), _s(Rank.TEN), _s(Rank.NINE), _s(Rank.NINE),
             _s(Rank.SIX), _s(Rank.SIX)],
            hand, led, "spades", CTX,
        )
        # The spare pair is compulsory: singles cannot take its slots.
        assert not is_valid_follow(
            [_s(Rank.TEN), _s(Rank.TEN), _s(Rank.NINE), _s(Rank.NINE),
             _s(Rank.SIX), _s(Rank.FOUR)],
            hand, led, "spades", CTX,
        )
        # Nor may the tractor itself be broken up.
        assert not is_valid_follow(
            [_s(Rank.TEN), _s(Rank.TEN), _s(Rank.SIX), _s(Rank.SIX),
             _s(Rank.FOUR), _s(Rank.THREE)],
            hand, led, "spades", CTX,
        )

    def test_three_disjoint_pairs_must_all_be_played(self):
        hand = [
            _s(Rank.TEN), _s(Rank.TEN), _s(Rank.EIGHT), _s(Rank.EIGHT),
            _s(Rank.SIX), _s(Rank.SIX), _s(Rank.FOUR), _s(Rank.THREE),
        ]
        led = self._led()
        assert is_valid_follow(
            [_s(Rank.TEN), _s(Rank.TEN), _s(Rank.EIGHT), _s(Rank.EIGHT),
             _s(Rank.SIX), _s(Rank.SIX)],
            hand, led, "spades", CTX,
        )
        assert not is_valid_follow(
            [_s(Rank.TEN), _s(Rank.TEN), _s(Rank.EIGHT), _s(Rank.EIGHT),
             _s(Rank.SIX), _s(Rank.FOUR)],
            hand, led, "spades", CTX,
        )

    def test_short_follower_plays_every_led_suit_card_then_fills_freely(self):
        hand = [
            _s(Rank.ACE), _s(Rank.ACE), _s(Rank.KING),
            _d(Rank.THREE), _d(Rank.FOUR), _d(Rank.FIVE), _d(Rank.SIX),
        ]
        led = self._led()
        assert is_valid_follow(
            [_s(Rank.ACE), _s(Rank.ACE), _s(Rank.KING),
             _d(Rank.THREE), _d(Rank.FOUR), _d(Rank.FIVE)],
            hand, led, "spades", CTX,
        )
        # Holding back the K♠ violates R42/R43.
        assert not is_valid_follow(
            [_s(Rank.ACE), _s(Rank.ACE),
             _d(Rank.THREE), _d(Rank.FOUR), _d(Rank.FIVE), _d(Rank.SIX)],
            hand, led, "spades", CTX,
        )
