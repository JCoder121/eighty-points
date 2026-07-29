"""D17 — suit-pure trick-winning eligibility (changes R51).

A play is "trump" for eligibility only if EVERY card in it is trump; otherwise
its effective suit is the common effective suit of all its cards if one exists.
A play whose cards span more than one effective suit is NEVER eligible to win,
so eligibility is order-independent.

Repros come from the audit (A3 / NEW-3) and the edge-case matrix.
"""
from __future__ import annotations

from shengji.engine.tricks import _play_strength, resolve_trick_winner
from shengji.models.card import Card, Rank, Suit
from shengji.models.groups import Single, classify_play
from shengji.models.trump import TrumpContext


def _c(suit: Suit, rank: Rank) -> Card:
    return Card(suit=suit, rank=rank)


def _ctx() -> TrumpContext:
    """Trump suit hearts, trump rank 2 — spades/diamonds are plain suits."""
    return TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS)


A_S = _c(Suit.SPADES, Rank.ACE)
K_S = _c(Suit.SPADES, Rank.KING)
THREE_H = _c(Suit.HEARTS, Rank.THREE)
FOUR_H = _c(Suit.HEARTS, Rank.FOUR)
A_H = _c(Suit.HEARTS, Rank.ACE)
FOUR_D = _c(Suit.DIAMONDS, Rank.FOUR)
SIX_D = _c(Suit.DIAMONDS, Rank.SIX)


class TestMixedSuitFollowCannotWin:
    """A follow spanning >1 effective suit is ineligible, in any card order."""

    def test_two_card_throw_trump_plus_junk_loses_both_orders(self):
        ctx = _ctx()
        lead = [A_S, K_S]
        led_fmt = classify_play(lead, ctx)

        for follow in ([THREE_H, FOUR_D], [FOUR_D, THREE_H]):
            trick = [("p0", lead), ("p1", list(follow))]
            assert resolve_trick_winner(trick, "spades", ctx, led_fmt) == "p0"

    def test_two_card_mixed_follow_has_no_strength(self):
        ctx = _ctx()
        led_fmt = classify_play([A_S, K_S], ctx)
        assert _play_strength([THREE_H, FOUR_D], "spades", led_fmt, ctx) is None
        assert _play_strength([FOUR_D, THREE_H], "spades", led_fmt, ctx) is None

    def test_three_card_throw_two_trumps_plus_junk_loses_both_orders(self):
        """Matrix NEW-3: [4H,4H,6D] structurally matches Throw(pair, single)
        but is not suit-pure, so it cannot take the trick."""
        ctx = _ctx()
        lead = [A_S, K_S, K_S]
        led_fmt = classify_play(lead, ctx)

        for follow in (
            [FOUR_H, FOUR_H, SIX_D],
            [SIX_D, FOUR_H, FOUR_H],
            [FOUR_H, SIX_D, FOUR_H],
        ):
            trick = [("p0", lead), ("p1", list(follow))]
            assert resolve_trick_winner(trick, "spades", ctx, led_fmt) == "p0"

    def test_eligibility_is_order_independent(self):
        ctx = _ctx()
        led_fmt = classify_play([A_S, K_S, K_S], ctx)
        verdicts = {
            _play_strength(list(order), "spades", led_fmt, ctx)
            for order in (
                (FOUR_H, FOUR_H, SIX_D),
                (SIX_D, FOUR_H, FOUR_H),
                (FOUR_H, SIX_D, FOUR_H),
            )
        }
        assert verdicts == {None}


class TestSuitPureTrumpFollowStillWins:
    """The pagat rule: an all-trump follow with matching structure ruffs."""

    def test_all_trump_pair_beats_pair_lead(self):
        ctx = _ctx()
        lead = [K_S, K_S]
        led_fmt = classify_play(lead, ctx)
        trick = [("p0", lead), ("p1", [FOUR_H, FOUR_H])]
        assert resolve_trick_winner(trick, "spades", ctx, led_fmt) == "p1"

    def test_all_trump_throw_beats_throw_lead(self):
        ctx = _ctx()
        lead = [A_S, K_S, K_S]
        led_fmt = classify_play(lead, ctx)
        trick = [("p0", lead), ("p1", [FOUR_H, FOUR_H, THREE_H])]
        assert resolve_trick_winner(trick, "spades", ctx, led_fmt) == "p1"

    def test_suited_follow_still_wins_when_higher(self):
        ctx = _ctx()
        lead = [_c(Suit.SPADES, Rank.NINE)]
        led_fmt = classify_play(lead, ctx)
        trick = [("p0", lead), ("p1", [A_S])]
        assert resolve_trick_winner(trick, "spades", ctx, led_fmt) == "p1"


class TestTrumpLeadOffSuitHole:
    """R51's short-circuit marked off-suit plays eligible on a trump lead."""

    def test_off_suit_play_on_trump_lead_is_ineligible(self):
        ctx = _ctx()
        assert _play_strength([SIX_D], "trump", Single(), ctx) is None

    def test_trump_lead_still_wins(self):
        ctx = _ctx()
        lead = [A_H]
        led_fmt = classify_play(lead, ctx)
        trick = [("p0", lead), ("p1", [SIX_D])]
        assert resolve_trick_winner(trick, "trump", ctx, led_fmt) == "p0"
