"""D23 — a throw's Tractor component imposes a STRUCTURAL obligation (changes R47).

Any tractor drawn from the follower's led-suit cards whose (multiplicity, length)
is at least the component's satisfies the obligation — matching R46's rule for a
pure tractor lead.  Repros come from audit F5 and matrix NEW-1 / Tier A1.
"""
from __future__ import annotations

from shengji.engine.tricks import is_valid_follow
from shengji.models.card import Card, Rank, Suit
from shengji.models.groups import (
    IdenticalGroup,
    Single,
    Throw,
    Tractor,
    classify_play,
)
from shengji.models.trump import TrumpContext


def _c(suit: Suit, rank: Rank) -> Card:
    return Card(suit=suit, rank=rank)


def _ctx() -> TrumpContext:
    """Trump suit hearts, trump rank 2."""
    return TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS)


def _h(rank: Rank) -> Card:
    return _c(Suit.HEARTS, rank)


def _s(rank: Rank) -> Card:
    return _c(Suit.SPADES, rank)


class TestTwoEqualLengthTractorsInTrump:
    """Matrix NEW-1 / audit A1, reproduced at the is_valid_follow level.

    Lead AH AH KH KH + QH (trump hearts).  The follower holds two 4-card
    tractors; either must satisfy the Tractor(2,2) component.
    """

    LEAD = [_h(Rank.ACE), _h(Rank.ACE), _h(Rank.KING), _h(Rank.KING), _h(Rank.QUEEN)]
    HAND = [
        _h(Rank.TEN), _h(Rank.TEN), _h(Rank.NINE), _h(Rank.NINE),
        _h(Rank.FIVE), _h(Rank.FIVE), _h(Rank.FOUR), _h(Rank.FOUR),
        _h(Rank.THREE),
    ]

    def _led_format(self, ctx):
        fmt = classify_play(self.LEAD, ctx)
        assert isinstance(fmt, Throw)
        return fmt

    def test_higher_tractor_validates(self):
        ctx = _ctx()
        play = [_h(Rank.TEN), _h(Rank.TEN), _h(Rank.NINE), _h(Rank.NINE), _h(Rank.THREE)]
        assert is_valid_follow(play, self.HAND, self._led_format(ctx), "trump", ctx)

    def test_lower_tractor_validates(self):
        ctx = _ctx()
        play = [_h(Rank.FIVE), _h(Rank.FIVE), _h(Rank.FOUR), _h(Rank.FOUR), _h(Rank.THREE)]
        assert is_valid_follow(play, self.HAND, self._led_format(ctx), "trump", ctx)


class TestAuditF5Table:
    """Audit §3.5: hand 9S9S 10S10S QSQS KSKS 7S against Throw(Tractor(2,2), Single).

    R46 (pure tractor lead) accepts either tractor; R47 must now agree.
    """

    HAND = [
        _s(Rank.NINE), _s(Rank.NINE), _s(Rank.TEN), _s(Rank.TEN),
        _s(Rank.QUEEN), _s(Rank.QUEEN), _s(Rank.KING), _s(Rank.KING),
        _s(Rank.SEVEN),
    ]
    LOW_TRACTOR_PLAY = [
        _s(Rank.NINE), _s(Rank.NINE), _s(Rank.TEN), _s(Rank.TEN), _s(Rank.SEVEN)
    ]
    HIGH_TRACTOR_PLAY = [
        _s(Rank.QUEEN), _s(Rank.QUEEN), _s(Rank.KING), _s(Rank.KING), _s(Rank.SEVEN)
    ]

    def _throw_format(self, ctx):
        lead = [_s(Rank.FIVE), _s(Rank.FIVE), _s(Rank.FOUR), _s(Rank.FOUR), _s(Rank.THREE)]
        fmt = classify_play(lead, ctx)
        assert isinstance(fmt, Throw)
        return fmt

    def test_low_tractor_validates(self):
        ctx = _ctx()
        assert is_valid_follow(
            self.LOW_TRACTOR_PLAY, self.HAND, self._throw_format(ctx), "spades", ctx
        )

    def test_high_tractor_validates(self):
        ctx = _ctx()
        assert is_valid_follow(
            self.HIGH_TRACTOR_PLAY, self.HAND, self._throw_format(ctx), "spades", ctx
        )

    def test_pure_tractor_lead_accepts_both(self):
        """R46 anchor — the two follow paths must agree."""
        ctx = _ctx()
        led = Tractor(multiplicity=2, length=2)
        assert is_valid_follow(self.LOW_TRACTOR_PLAY[:4], self.HAND, led, "spades", ctx)
        assert is_valid_follow(self.HIGH_TRACTOR_PLAY[:4], self.HAND, led, "spades", ctx)


class TestTractorObligationStillEnforced:
    """Structural does not mean optional."""

    def test_loose_pairs_cannot_dodge_a_held_tractor(self):
        ctx = _ctx()
        hand = [
            _s(Rank.NINE), _s(Rank.NINE), _s(Rank.TEN), _s(Rank.TEN),
            _s(Rank.QUEEN), _s(Rank.QUEEN), _s(Rank.SEVEN),
        ]
        led = Throw(components=[Tractor(multiplicity=2, length=2), Single()])
        play = [_s(Rank.QUEEN), _s(Rank.QUEEN), _s(Rank.NINE), _s(Rank.NINE), _s(Rank.SEVEN)]
        assert not is_valid_follow(play, hand, led, "spades", ctx)

    def test_sole_tractor_is_still_required(self):
        ctx = _ctx()
        hand = [
            _s(Rank.NINE), _s(Rank.NINE), _s(Rank.TEN), _s(Rank.TEN),
            _s(Rank.SEVEN), _s(Rank.FIVE), _s(Rank.THREE),
        ]
        led = Throw(components=[Tractor(multiplicity=2, length=2), Single()])
        play = [_s(Rank.NINE), _s(Rank.NINE), _s(Rank.SEVEN), _s(Rank.FIVE), _s(Rank.THREE)]
        assert not is_valid_follow(play, hand, led, "spades", ctx)

    def test_pair_obligation_alongside_tractor_still_enforced(self):
        """Tractor + IdenticalGroup(2) throw: both obligations survive."""
        ctx = _ctx()
        hand = [
            _s(Rank.NINE), _s(Rank.NINE), _s(Rank.TEN), _s(Rank.TEN),
            _s(Rank.QUEEN), _s(Rank.QUEEN), _s(Rank.SEVEN), _s(Rank.FIVE),
        ]
        led = Throw(
            components=[Tractor(multiplicity=2, length=2), IdenticalGroup(count=2)]
        )
        good = [
            _s(Rank.NINE), _s(Rank.NINE), _s(Rank.TEN), _s(Rank.TEN),
            _s(Rank.QUEEN), _s(Rank.QUEEN),
        ]
        bad = [
            _s(Rank.NINE), _s(Rank.NINE), _s(Rank.TEN), _s(Rank.TEN),
            _s(Rank.SEVEN), _s(Rank.FIVE),
        ]
        assert is_valid_follow(good, hand, led, "spades", ctx)
        assert not is_valid_follow(bad, hand, led, "spades", ctx)
