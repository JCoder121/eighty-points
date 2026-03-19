"""Tests for trick resolution utilities (M4.4)."""
from __future__ import annotations

import pytest

from shengji.engine.tricks import (
    get_legal_plays,
    is_valid_follow,
    resolve_trick_winner,
    validate_throw,
)
from shengji.models.card import Card, Rank, Suit
from shengji.models.groups import (
    IdenticalGroup,
    Single,
    Tractor,
    Throw,
    classify_play,
)
from shengji.models.trump import TrumpContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _c(suit: Suit, rank: Rank) -> Card:
    return Card(suit=suit, rank=rank)


def _ctx(trump_rank: Rank = Rank.TWO, trump_suit: Suit | None = Suit.HEARTS) -> TrumpContext:
    return TrumpContext(trump_rank=trump_rank, trump_suit=trump_suit)


SJ = Card(Suit.JOKER, Rank.SMALL_JOKER)
BJ = Card(Suit.JOKER, Rank.BIG_JOKER)

# Convenience shortcuts for common cards under trump_rank=2, trump_suit=HEARTS
# Tier 0: off-suit non-trump-rank
A_S = _c(Suit.SPADES, Rank.ACE)
K_S = _c(Suit.SPADES, Rank.KING)
Q_S = _c(Suit.SPADES, Rank.QUEEN)
J_S = _c(Suit.SPADES, Rank.JACK)
T_S = _c(Suit.SPADES, Rank.TEN)
N_S = _c(Suit.SPADES, Rank.NINE)
A_D = _c(Suit.DIAMONDS, Rank.ACE)
K_D = _c(Suit.DIAMONDS, Rank.KING)
# Tier 1: trump-suit (HEARTS) non-trump-rank
A_H = _c(Suit.HEARTS, Rank.ACE)
K_H = _c(Suit.HEARTS, Rank.KING)
Q_H = _c(Suit.HEARTS, Rank.QUEEN)
T_H = _c(Suit.HEARTS, Rank.TEN)
# Tier 2: off-suit trump-rank
TWO_S = _c(Suit.SPADES, Rank.TWO)
TWO_D = _c(Suit.DIAMONDS, Rank.TWO)
TWO_C = _c(Suit.CLUBS, Rank.TWO)
# Tier 3: on-suit trump-rank
TWO_H = _c(Suit.HEARTS, Rank.TWO)


# ---------------------------------------------------------------------------
# get_legal_plays — single lead
# ---------------------------------------------------------------------------

class TestGetLegalPlaysSingle:
    ctx = _ctx()

    def test_has_suited_plays_one(self):
        hand = [A_S, K_S, A_H]
        plays = get_legal_plays(hand, Single(), "spades", self.ctx)
        assert len(plays) == 1
        assert len(plays[0]) == 1
        assert plays[0][0] in [A_S, K_S]

    def test_no_suited_plays_anything(self):
        hand = [A_H, K_H]  # only trump-suit cards
        plays = get_legal_plays(hand, Single(), "spades", self.ctx)
        assert len(plays) == 1
        assert plays[0][0] in hand


# ---------------------------------------------------------------------------
# get_legal_plays — identical group (pair)
# ---------------------------------------------------------------------------

class TestGetLegalPlaysGroup:
    ctx = _ctx()

    def test_has_pair_plays_pair(self):
        hand = [A_S, A_S, K_S]
        plays = get_legal_plays(hand, IdenticalGroup(2), "spades", self.ctx)
        assert len(plays[0]) == 2
        # Should play the pair
        assert plays[0].count(A_S) == 2

    def test_only_singles_of_suit_fills_pair(self):
        hand = [A_S, K_S, A_H]  # no spade pair
        plays = get_legal_plays(hand, IdenticalGroup(2), "spades", self.ctx)
        assert len(plays[0]) == 2
        # Both spades
        assert all(self.ctx.effective_suit(c) == "spades" for c in plays[0])

    def test_no_suit_plays_any_two(self):
        hand = [A_H, K_H, Q_H]  # no spades
        plays = get_legal_plays(hand, IdenticalGroup(2), "spades", self.ctx)
        assert len(plays[0]) == 2


# ---------------------------------------------------------------------------
# get_legal_plays — tractor
# ---------------------------------------------------------------------------

class TestGetLegalPlaysTractor:
    ctx = _ctx(trump_rank=Rank.FOUR, trump_suit=Suit.HEARTS)

    def test_has_tractor_plays_tractor(self):
        # trump rank=4; A♠A♠K♠K♠ is a tractor (A and K adjacent in spades)
        hand = [A_S, A_S, K_S, K_S, Q_S]
        led = Tractor(multiplicity=2, length=2)
        plays = get_legal_plays(hand, led, "spades", self.ctx)
        assert len(plays[0]) == 4

    def test_no_tractor_uses_pairs_then_singles(self):
        # Has pair A♠A♠ but no tractor
        hand = [A_S, A_S, Q_S, J_S]
        led = Tractor(multiplicity=2, length=2)
        plays = get_legal_plays(hand, led, "spades", self.ctx)
        assert len(plays[0]) == 4
        # Must include the pair
        assert plays[0].count(A_S) == 2

    def test_insufficient_suited_fills_with_any(self):
        hand = [A_S, K_S, A_H, K_H]  # only 2 spades
        led = Tractor(multiplicity=2, length=2)
        plays = get_legal_plays(hand, led, "spades", self.ctx)
        assert len(plays[0]) == 4


# ---------------------------------------------------------------------------
# resolve_trick_winner — singles
# ---------------------------------------------------------------------------

class TestResolveTrickWinnerSingles:
    ctx = _ctx()

    def test_highest_of_led_suit_wins(self):
        trick = [
            ("p0", [A_S]),
            ("p1", [K_S]),
            ("p2", [Q_S]),
            ("p3", [J_S]),
        ]
        assert resolve_trick_winner(trick, "spades", self.ctx) == "p0"

    def test_trump_beats_non_trump(self):
        trick = [
            ("p0", [A_S]),
            ("p1", [TWO_S]),  # tier-2 trump (off-suit trump rank)
            ("p2", [Q_S]),
            ("p3", [J_S]),
        ]
        assert resolve_trick_winner(trick, "spades", self.ctx) == "p1"

    def test_higher_trump_beats_lower(self):
        trick = [
            ("p0", [TWO_S]),  # tier-2
            ("p1", [TWO_H]),  # tier-3 (on-suit trump rank)
            ("p2", [A_H]),    # tier-1
            ("p3", [SJ]),
        ]
        # SJ is tier 4 > TWO_H tier 3
        assert resolve_trick_winner(trick, "trump", self.ctx) == "p3"

    def test_big_joker_beats_small_joker(self):
        trick = [
            ("p0", [SJ]),
            ("p1", [BJ]),
        ]
        assert resolve_trick_winner(trick, "trump", self.ctx) == "p1"

    def test_first_player_wins_tie(self):
        trick = [
            ("p0", [A_S]),
            ("p1", [A_S]),  # same card (2-deck game)
        ]
        assert resolve_trick_winner(trick, "spades", self.ctx) == "p0"

    def test_off_suit_cannot_win(self):
        trick = [
            ("p0", [A_S]),  # leader
            ("p1", [A_D]),  # off-suit, cannot win
        ]
        assert resolve_trick_winner(trick, "spades", self.ctx) == "p0"

    def test_empty_trick_raises(self):
        with pytest.raises(ValueError, match="empty"):
            resolve_trick_winner([], "spades", self.ctx)


# ---------------------------------------------------------------------------
# resolve_trick_winner — multi-card plays
# ---------------------------------------------------------------------------

class TestResolveTrickWinnerMulti:
    ctx = _ctx()

    def test_higher_pair_wins(self):
        trick = [
            ("p0", [A_S, A_S]),
            ("p1", [K_S, K_S]),
        ]
        assert resolve_trick_winner(trick, "spades", self.ctx) == "p0"

    def test_trump_pair_beats_non_trump_pair(self):
        trick = [
            ("p0", [A_S, A_S]),
            ("p1", [A_H, A_H]),  # trump suit hearts
        ]
        assert resolve_trick_winner(trick, "spades", self.ctx) == "p1"


# ---------------------------------------------------------------------------
# validate_throw
# ---------------------------------------------------------------------------

class TestValidateThrow:
    ctx = _ctx(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS)

    def _throw(self, cards: list[Card], all_hands: dict[str, list[Card]]) -> bool:
        return validate_throw(cards, "p0", all_hands, self.ctx)

    def test_non_throw_always_valid(self):
        # A single is not a throw — always valid
        assert self._throw([A_S], {"p0": [A_S], "p1": [], "p2": [], "p3": []})

    def test_throw_valid_when_no_opponent_beats_component(self):
        # p0 throws A♠ + A♦ (singles); opponents have no spades/diamonds stronger
        throw_cards = [A_S, A_D]
        all_hands = {
            "p0": throw_cards,
            "p1": [K_S],   # K♠ < A♠ → cannot beat A♠
            "p2": [K_D],   # K♦ < A♦ → cannot beat A♦
            "p3": [],
        }
        assert self._throw(throw_cards, all_hands)

    def test_throw_invalid_when_opponent_beats_component(self):
        # p0 throws K♠ + A♦; p1 has A♠ which beats K♠
        throw_cards = [K_S, A_D]
        all_hands = {
            "p0": throw_cards,
            "p1": [A_S],  # A♠ > K♠ → beats a component
            "p2": [],
            "p3": [],
        }
        assert not self._throw(throw_cards, all_hands)

    def test_throw_valid_when_only_thrower_has_higher(self):
        # p0 throws K♠; only p0 has A♠ (not opponents)
        throw_cards = [K_S, A_D]
        all_hands = {
            "p0": throw_cards + [A_S],
            "p1": [],
            "p2": [],
            "p3": [],
        }
        assert self._throw(throw_cards, all_hands)


# ---------------------------------------------------------------------------
# Dynamic adjacency (from plan: trump rank 4, 9, 3, 2)
# ---------------------------------------------------------------------------

class TestDynamicAdjacency:
    def test_trump_rank_4_adjacent_3_and_5(self):
        """3♠3♠5♠5♠ is a valid tractor when trump rank=4."""
        ctx = TrumpContext(trump_rank=Rank.FOUR, trump_suit=Suit.HEARTS)
        cards = [
            _c(Suit.SPADES, Rank.THREE),
            _c(Suit.SPADES, Rank.THREE),
            _c(Suit.SPADES, Rank.FIVE),
            _c(Suit.SPADES, Rank.FIVE),
        ]
        fmt = classify_play(cards, ctx)
        assert isinstance(fmt, Tractor)

    def test_trump_rank_9_adjacent_8_and_10(self):
        """8♠8♠10♠10♠ is a valid tractor when trump rank=9."""
        ctx = TrumpContext(trump_rank=Rank.NINE, trump_suit=Suit.HEARTS)
        cards = [
            _c(Suit.SPADES, Rank.EIGHT),
            _c(Suit.SPADES, Rank.EIGHT),
            _c(Suit.SPADES, Rank.TEN),
            _c(Suit.SPADES, Rank.TEN),
        ]
        fmt = classify_play(cards, ctx)
        assert isinstance(fmt, Tractor)

    def test_trump_rank_3_adjacent_2_and_4(self):
        """2♠2♠4♠4♠ is a valid tractor when trump rank=3."""
        ctx = TrumpContext(trump_rank=Rank.THREE, trump_suit=Suit.HEARTS)
        cards = [
            _c(Suit.SPADES, Rank.TWO),
            _c(Suit.SPADES, Rank.TWO),
            _c(Suit.SPADES, Rank.FOUR),
            _c(Suit.SPADES, Rank.FOUR),
        ]
        fmt = classify_play(cards, ctx)
        assert isinstance(fmt, Tractor)

    def test_trump_rank_2_ace_and_3_adjacent(self):
        """A♠A♠3♠3♠ is a valid tractor when trump rank=2 (circular wrap: A wraps to 3)."""
        ctx = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS)
        cards = [
            _c(Suit.SPADES, Rank.ACE),
            _c(Suit.SPADES, Rank.ACE),
            _c(Suit.SPADES, Rank.THREE),
            _c(Suit.SPADES, Rank.THREE),
        ]
        fmt = classify_play(cards, ctx)
        assert isinstance(fmt, Tractor)


# ---------------------------------------------------------------------------
# Trump ordering correctness
# ---------------------------------------------------------------------------

class TestTrumpOrdering:
    ctx = _ctx(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS)

    def test_full_trump_order(self):
        """BJ > SJ > 2♥ > 2♠=2♦=2♣ > A♥ > K♥ > ... > 3♥ > A♠ > K♠ > ..."""
        def rank(c):
            return self.ctx.card_order(c)

        assert rank(BJ) > rank(SJ)
        assert rank(SJ) > rank(TWO_H)
        assert rank(TWO_H) > rank(TWO_S)
        assert rank(TWO_S) == rank(TWO_D) == rank(TWO_C)  # all tier-2
        assert rank(TWO_S) > rank(A_H)
        assert rank(A_H) > rank(K_H)
        assert rank(A_H) > rank(A_S)  # trump-suit > off-suit
        assert rank(A_S) > rank(K_S)  # A > K within off-suit

    def test_effective_suit_trump_rank(self):
        assert self.ctx.effective_suit(TWO_H) == "trump"
        assert self.ctx.effective_suit(TWO_S) == "trump"
        assert self.ctx.effective_suit(A_H) == "trump"
        assert self.ctx.effective_suit(A_S) == "spades"

    def test_effective_suit_no_trump(self):
        ctx_no_trump = TrumpContext(trump_rank=Rank.TWO, trump_suit=None)
        # In no-trump mode, trump-rank cards keep their own suit
        assert ctx_no_trump.effective_suit(TWO_S) == "spades"
        assert ctx_no_trump.effective_suit(TWO_H) == "hearts"
        # Jokers are always trump
        assert ctx_no_trump.effective_suit(SJ) == "trump"


# ---------------------------------------------------------------------------
# is_valid_follow — bug regression tests (bugs reported during play-testing)
# ---------------------------------------------------------------------------
# Context: trump_rank=2, trump_suit=clubs.  Hearts is a plain (non-trump) suit.

_FOUR_H  = _c(Suit.HEARTS, Rank.FOUR)
_FIVE_H  = _c(Suit.HEARTS, Rank.FIVE)
_TEN_H   = _c(Suit.HEARTS, Rank.TEN)
_JACK_H  = _c(Suit.HEARTS, Rank.JACK)
_ACE_H   = _c(Suit.HEARTS, Rank.ACE)
_THREE_S = _c(Suit.SPADES, Rank.THREE)

_CTX_CLUBS_TRUMP = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.CLUBS)


class TestIsValidFollowSingle:
    """Bug: any suited single must legally follow a single lead."""

    ctx = _CTX_CLUBS_TRUMP

    def test_any_suited_single_is_valid(self):
        # Hand has several hearts; any one should be valid to follow a heart lead
        hand = [_FOUR_H, _FIVE_H, _TEN_H, _JACK_H]
        assert is_valid_follow([_FOUR_H],  hand, Single(), "hearts", self.ctx)
        assert is_valid_follow([_FIVE_H],  hand, Single(), "hearts", self.ctx)
        assert is_valid_follow([_TEN_H],   hand, Single(), "hearts", self.ctx)
        assert is_valid_follow([_JACK_H],  hand, Single(), "hearts", self.ctx)

    def test_off_suit_invalid_when_suited_available(self):
        hand = [_FOUR_H, _THREE_S]
        # Must play a heart; spade is invalid when a heart is available
        assert not is_valid_follow([_THREE_S], hand, Single(), "hearts", self.ctx)

    def test_off_suit_valid_when_no_suited_available(self):
        hand = [_THREE_S]
        assert is_valid_follow([_THREE_S], hand, Single(), "hearts", self.ctx)

    def test_wrong_number_of_cards_invalid(self):
        hand = [_FOUR_H, _FIVE_H]
        assert not is_valid_follow([_FOUR_H, _FIVE_H], hand, Single(), "hearts", self.ctx)


class TestIsValidFollowPairNoGroup:
    """Bug: when no pair available, any 2 suited singles must be valid follow for pair lead."""

    ctx = _CTX_CLUBS_TRUMP

    def test_lowest_two_singles_valid(self):
        # Bug case: 4♥+5♥ was rejected; should be valid when no pair exists
        hand = [_FOUR_H, _FIVE_H, _TEN_H, _JACK_H]
        assert is_valid_follow([_FOUR_H, _FIVE_H], hand, IdenticalGroup(2), "hearts", self.ctx)

    def test_non_lowest_two_singles_also_valid(self):
        # 10♥+J♥ was already accepted; must still be valid
        hand = [_FOUR_H, _FIVE_H, _TEN_H, _JACK_H]
        assert is_valid_follow([_TEN_H, _JACK_H], hand, IdenticalGroup(2), "hearts", self.ctx)

    def test_any_combination_of_two_suited_singles_valid(self):
        hand = [_FOUR_H, _FIVE_H, _TEN_H, _JACK_H]
        assert is_valid_follow([_FOUR_H, _TEN_H],  hand, IdenticalGroup(2), "hearts", self.ctx)
        assert is_valid_follow([_FOUR_H, _JACK_H], hand, IdenticalGroup(2), "hearts", self.ctx)
        assert is_valid_follow([_FIVE_H, _TEN_H],  hand, IdenticalGroup(2), "hearts", self.ctx)

    def test_off_suit_invalid_when_two_suited_available(self):
        hand = [_FOUR_H, _FIVE_H, _THREE_S]
        # Must use both hearts; cannot substitute spade
        assert not is_valid_follow([_FOUR_H, _THREE_S], hand, IdenticalGroup(2), "hearts", self.ctx)

    def test_must_use_all_suited_when_only_one_heart(self):
        # Only 1 heart; must play it plus any other card
        hand = [_FOUR_H, _THREE_S]
        assert is_valid_follow([_FOUR_H, _THREE_S], hand, IdenticalGroup(2), "hearts", self.ctx)
        # Cannot skip the heart
        assert not is_valid_follow([_THREE_S, _THREE_S], hand, IdenticalGroup(2), "hearts", self.ctx)


class TestIsValidFollowPairHasGroup:
    """When hand has a pair, proposed play must include that pair."""

    ctx = _CTX_CLUBS_TRUMP

    def test_must_play_pair_when_available(self):
        hand = [_ACE_H, _ACE_H, _FOUR_H, _FIVE_H]
        # A♥A♥ is a valid pair play
        assert is_valid_follow([_ACE_H, _ACE_H], hand, IdenticalGroup(2), "hearts", self.ctx)
        # 4♥5♥ is NOT valid — hand has a pair so must use it
        assert not is_valid_follow([_FOUR_H, _FIVE_H], hand, IdenticalGroup(2), "hearts", self.ctx)
