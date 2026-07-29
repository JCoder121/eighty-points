"""Gap pins for throw validation and the failed-throw penalty.

Every test here pins behavior the Phase-2 audit probed and found CORRECT but
untested (edge-case matrix Tier B, cells 3.6-3.12, 3.22, 3.23).  Rule numbers
refer to ``docs/RULES.md``.

Covered:
  R40 / D08  the Tractor branch of throw validation (all four sub-rules)
  R41 / D07  the thrower's own PARTNER counts as an opponent
  R26        buried bottom cards are excluded from the check
  R73        penalties accumulate; the forced component may be a PAIR
"""
from __future__ import annotations

from shengji.engine.engine import GameEngine
from shengji.engine.tricks import find_beatable_components, validate_throw
from shengji.models.card import Card, Rank, Suit
from shengji.models.game_state import GamePhase, GameState
from shengji.models.groups import IdenticalGroup, Single, Tractor, Throw, classify_play
from shengji.models.player import Player
from shengji.models.trump import TrumpContext
from shengji.modes.upgrade import UpgradeStrategy


def _c(suit: Suit, rank: Rank) -> Card:
    return Card(suit=suit, rank=rank)


def _s(rank: Rank) -> Card:
    return _c(Suit.SPADES, rank)


CTX = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS)

A_S = _s(Rank.ACE)
K_S = _s(Rank.KING)
Q_S = _s(Rank.QUEEN)
J_S = _s(Rank.JACK)
T_S = _s(Rank.TEN)
N_S = _s(Rank.NINE)
E_S = _s(Rank.EIGHT)
SV_S = _s(Rank.SEVEN)
SX_S = _s(Rank.SIX)
F_S = _s(Rank.FIVE)
FO_S = _s(Rank.FOUR)
TH_S = _s(Rank.THREE)


def _make_engine(
    hands: dict[str, list[Card]],
    bottom: list[Card] | None = None,
    trick_leader: str = "p0",
) -> GameEngine:
    """Build an Upgrade engine sitting in PLAYING with controlled hands."""
    players = [Player(id=f"p{i}", name=f"P{i}") for i in range(4)]
    state = GameState(players=players, mode="upgrade", round_leader_id="p0")
    state.phase = GamePhase.PLAYING
    state.trump_context = CTX
    state.tricks_won = {p.id: [] for p in players}
    state.bottom_deck = list(bottom or [])
    state.current_turn_id = trick_leader
    state.current_leader_id = trick_leader
    for p in players:
        p.hand = list(hands[p.id])
    strategy = UpgradeStrategy()
    engine = GameEngine(state, strategy, deal_delay=0)
    strategy.assign_teams(state)
    return engine


# ---------------------------------------------------------------------------
# R40 / D08 — the Tractor branch of throw validation
# ---------------------------------------------------------------------------

class TestThrowTractorComponent:
    """R40's tractor sub-rule and D08 ("a LONGER higher tractor beats too").

    The throw is always ``7♠7♠ 6♠6♠ + A♠``: a Tractor(2,2) component plus a
    Single that no opponent can ever beat (A♠ is the top spade and the thrower
    holds it), so anything reported beatable is the tractor component.
    """

    THROW = [SV_S, SV_S, SX_S, SX_S, A_S]

    def _hands(self, opponents: dict[str, list[Card]]) -> dict[str, list[Card]]:
        hands = {"p0": list(self.THROW), "p1": [], "p2": [], "p3": []}
        hands.update(opponents)
        return hands

    def _beatable(self, opponents: dict[str, list[Card]]):
        return find_beatable_components(self.THROW, "p0", self._hands(opponents), CTX)

    def test_throw_decomposes_into_tractor_plus_single(self):
        fmt = classify_play(self.THROW, CTX)
        assert isinstance(fmt, Throw)
        assert sorted(type(comp).__name__ for comp in fmt.components) == [
            "Single",
            "Tractor",
        ]

    def test_equal_length_higher_tractor_beats_the_component(self):
        # Q♠Q♠ J♠J♠ is a 4-card tractor above 7♠7♠6♠6♠ (R40, tractor bullet).
        beatable = self._beatable({"p1": [Q_S, Q_S, J_S, J_S]})
        assert [type(fmt).__name__ for fmt, _ in beatable] == ["Tractor"]
        assert not validate_throw(self.THROW, "p0", self._hands({"p1": [Q_S, Q_S, J_S, J_S]}), CTX)

    def test_longer_higher_tractor_also_beats_the_component(self):
        # D08: length need not match — a 6-card higher tractor beats a 4-card
        # component.  This is the entire point of the decision and had zero
        # regression coverage before this pin.
        opp = [Q_S, Q_S, J_S, J_S, T_S, T_S]
        beatable = self._beatable({"p1": opp})
        assert [type(fmt).__name__ for fmt, _ in beatable] == ["Tractor"]
        beaten_fmt, beaten_cards = beatable[0]
        assert isinstance(beaten_fmt, Tractor)
        assert sorted(c.rank.value for c in beaten_cards) == ["6", "6", "7", "7"]

    def test_longer_but_lower_tractor_does_not_beat_the_component(self):
        # 5♠5♠4♠4♠3♠3♠ is longer (6 cards) but its top card is below 7♠.
        assert self._beatable({"p1": [F_S, F_S, FO_S, FO_S, TH_S, TH_S]}) == []

    def test_higher_pair_or_single_alone_does_not_beat_a_tractor_component(self):
        # A tractor component needs a TRACTOR to beat it (matrix cell 3.9).
        assert self._beatable({"p1": [A_S, A_S]}) == []
        assert self._beatable({"p1": [K_S]}) == []

    def test_two_opponents_cannot_combine_to_beat_one_component(self):
        # R40 is per-opponent: Q♠Q♠ with p1 and J♠J♠ with p2 would form a
        # beating tractor only if the two hands were pooled.
        assert self._beatable({"p1": [Q_S, Q_S], "p2": [J_S, J_S]}) == []
        # ...and the same four cards in ONE hand do beat it.
        assert len(self._beatable({"p1": [Q_S, Q_S, J_S, J_S]})) == 1


# ---------------------------------------------------------------------------
# R41 / D07 — the thrower's partner counts
# ---------------------------------------------------------------------------

class TestPartnerCountsForThrowValidation:
    """D07 (confirmed by interview Q7): all three other hands are inspected,
    including the thrower's own partner in Upgrade."""

    def test_partners_beating_card_fails_the_throw(self):
        # Upgrade with round leader p0 → p0/p2 defend, p1/p3 attack.  The A♠
        # sits in PARTNER p2's hand and still invalidates p0's throw.
        engine = _make_engine({
            "p0": [K_S, Q_S],
            "p1": [TH_S, FO_S],
            "p2": [A_S, F_S],
            "p3": [SX_S, SV_S],
        })
        state = engine.state
        assert state.players[0].is_defending and state.players[2].is_defending

        result = engine.play_cards("p0", [K_S, Q_S])

        assert result["throw_failed"] is True
        assert result["forced_cards"] == [Q_S]        # weakest beatable component
        assert result["penalty"] == 20                # R73: 10 × 2 attempted
        assert state.throw_penalties == {"p0": 20}

    def test_same_throw_is_valid_when_nobody_holds_the_ace(self):
        # Control for the test above: move both A♠ out of every hand and the
        # identical throw goes through untouched.
        engine = _make_engine({
            "p0": [K_S, Q_S],
            "p1": [TH_S, FO_S],
            "p2": [F_S, SX_S],
            "p3": [SV_S, E_S],
        })
        result = engine.play_cards("p0", [K_S, Q_S])

        assert "throw_failed" not in result
        assert engine.state.throw_penalties == {}
        assert engine.state.current_trick == [("p0", [K_S, Q_S])]


# ---------------------------------------------------------------------------
# R26 — buried bottom cards are out of play
# ---------------------------------------------------------------------------

class TestBuriedCardsExcludedFromThrowValidation:
    def test_both_beating_copies_in_the_bottom_leave_the_throw_valid(self):
        # Both A♠ are buried, so no HAND holds a spade above K♠ — R26 says the
        # bottom never counts as "cards an opponent could hold".
        engine = _make_engine(
            {
                "p0": [K_S, Q_S],
                "p1": [TH_S, FO_S],
                "p2": [F_S, SX_S],
                "p3": [SV_S, E_S],
            },
            bottom=[A_S, A_S, T_S, N_S, J_S, _c(Suit.HEARTS, Rank.THREE),
                    _c(Suit.CLUBS, Rank.THREE), _c(Suit.DIAMONDS, Rank.THREE)],
        )
        result = engine.play_cards("p0", [K_S, Q_S])

        assert "throw_failed" not in result
        assert engine.state.throw_penalties == {}
        assert engine.state.players[0].hand == []
        assert engine.state.current_trick == [("p0", [K_S, Q_S])]

    def test_one_copy_buried_and_one_in_a_hand_still_fails_the_throw(self):
        # Contrast: the bottom is ignored, but the live copy still counts.
        engine = _make_engine(
            {
                "p0": [K_S, Q_S],
                "p1": [A_S, FO_S],
                "p2": [F_S, SX_S],
                "p3": [SV_S, E_S],
            },
            bottom=[A_S] + [_c(Suit.CLUBS, Rank.THREE)] * 7,
        )
        result = engine.play_cards("p0", [K_S, Q_S])

        assert result["throw_failed"] is True
        assert result["penalty"] == 20


# ---------------------------------------------------------------------------
# R73 — penalty accumulation and pair-sized forced components
# ---------------------------------------------------------------------------

class TestThrowPenaltyAccumulation:
    def test_two_failed_throws_by_one_player_accumulate(self):
        # p1 holds A♠ for the whole round, so both of p0's throws fail.
        engine = _make_engine({
            "p0": [K_S, Q_S, J_S],
            "p1": [A_S, TH_S, FO_S],
            "p2": [F_S, SX_S, SV_S],
            "p3": [E_S, N_S, T_S],
        })
        state = engine.state

        first = engine.play_cards("p0", [K_S, Q_S])   # forced Q♠, 10 × 2 = 20
        assert first["forced_cards"] == [Q_S]
        assert state.throw_penalties == {"p0": 20}

        # p0 wins the trick with Q♠ and therefore leads again.
        engine.play_cards("p1", [TH_S])
        engine.play_cards("p2", [F_S])
        assert engine.play_cards("p3", [E_S])["trick_winner"] == "p0"

        second = engine.play_cards("p0", [K_S, J_S])  # forced J♠, another 20
        assert second["throw_failed"] is True
        assert second["forced_cards"] == [J_S]
        assert second["penalty"] == 20
        # R73: penalties from the same player in one round sum.
        assert state.throw_penalties == {"p0": 40}

    def test_forced_component_may_be_a_pair_and_penalty_counts_all_attempted(self):
        # Throw Q♠Q♠ + A♠.  Only the PAIR is beatable (p1's K♠K♠); the single
        # A♠ is the top spade and the thrower holds it.  R72 forces the pair,
        # R73 charges 10 × 3 attempted cards even though only 2 were played.
        engine = _make_engine({
            "p0": [Q_S, Q_S, A_S],
            "p1": [K_S, K_S, TH_S],
            "p2": [FO_S, F_S, SX_S],
            "p3": [SV_S, E_S, N_S],
        })
        state = engine.state

        fmt = classify_play([Q_S, Q_S, A_S], CTX)
        assert isinstance(fmt, Throw)
        assert any(isinstance(comp, IdenticalGroup) for comp in fmt.components)
        assert any(isinstance(comp, Single) for comp in fmt.components)

        result = engine.play_cards("p0", [Q_S, Q_S, A_S])

        assert result["throw_failed"] is True
        assert result["forced_cards"] == [Q_S, Q_S]
        assert result["penalty"] == 30
        assert state.throw_penalties == {"p0": 30}
        assert state.players[0].hand == [A_S]         # unplayed card stays
        assert state.current_trick == [("p0", [Q_S, Q_S])]
        assert isinstance(state.led_format, IdenticalGroup)
