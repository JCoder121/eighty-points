"""Find Friends end-to-end flows: declarations through the engine with the
REAL FindFriendsStrategy (the unit suite uses a stub), and reveal-by-play
scenarios including ordinals, self-friend, buried friend cards, and reveals
on the final trick.
"""
from __future__ import annotations

import pytest

from shengji.engine.engine import GameEngine
from shengji.models.card import Card, Rank
from shengji.models.friend_declaration import FriendDeclaration
from shengji.models.game_state import GamePhase
from shengji.modes.find_friends import FindFriendsStrategy

from tests.test_integration.helpers import BJ, D, H, S, c, ctx, make_state

TR = ctx(trump_rank=Rank.TWO, trump_suit=H)


def _decl_engine() -> tuple[GameEngine, object]:
    """Engine in FRIEND_DECLARATION with the real strategy validating."""
    state = make_state("find_friends", "p0", ranks={"p0": Rank.TWO})
    strategy = FindFriendsStrategy()
    engine = GameEngine(state, strategy, deal_delay=0)
    state.trump_context = TR
    strategy.assign_teams(state)
    state.phase = GamePhase.FRIEND_DECLARATION
    return engine, state


def _ff_playing(
    hands: dict[str, list[Card]],
    declarations: list[tuple[Card, int]],
    bottom: list[Card] | None = None,
) -> tuple[GameEngine, object, FindFriendsStrategy]:
    """FF engine forced into PLAYING with declarations set and teams assigned."""
    state = make_state("find_friends", "p0", ranks={"p0": Rank.TWO})
    strategy = FindFriendsStrategy()
    engine = GameEngine(state, strategy, deal_delay=0)
    state.trump_context = TR
    for p in state.players:
        p.hand = list(hands.get(p.id, []))
    state.bottom_deck = list(bottom or [])
    strategy.assign_teams(state)  # leader p0 defends alone; resets play counts
    state.friend_declarations = [
        FriendDeclaration(card=card, ordinal=ordinal) for card, ordinal in declarations
    ]
    state.tricks_won = {p.id: [] for p in state.players}
    state.phase = GamePhase.PLAYING
    state.current_leader_id = "p0"
    state.current_turn_id = "p0"
    return engine, state, strategy


class TestFriendDeclarationFlow:
    def test_joker_rejected(self):
        engine, _ = _decl_engine()
        with pytest.raises(ValueError, match="joker"):
            engine.declare_friends("p0", [FriendDeclaration(card=BJ, ordinal=1)])

    def test_trump_rank_card_rejected(self):
        engine, _ = _decl_engine()
        with pytest.raises(ValueError, match="trump-rank"):
            engine.declare_friends("p0", [FriendDeclaration(card=c(S, Rank.TWO), ordinal=1)])

    def test_trump_suit_card_rejected(self):
        engine, _ = _decl_engine()
        with pytest.raises(ValueError, match="trump-suit"):
            engine.declare_friends("p0", [FriendDeclaration(card=c(H, Rank.ACE), ordinal=1)])

    def test_wrong_declaration_count_rejected(self):
        engine, _ = _decl_engine()
        with pytest.raises(ValueError, match="exactly"):
            engine.declare_friends("p0", [
                FriendDeclaration(card=c(S, Rank.ACE), ordinal=1),
                FriendDeclaration(card=c(D, Rank.KING), ordinal=1),
            ])

    def test_valid_declaration_stored_and_advances_phase(self):
        engine, state = _decl_engine()
        engine.declare_friends("p0", [FriendDeclaration(card=c(S, Rank.ACE), ordinal=1)])
        assert state.phase == GamePhase.BOTTOM_EXCHANGE
        assert len(state.friend_declarations) == 1

    def test_non_leader_cannot_declare(self):
        engine, _ = _decl_engine()
        with pytest.raises(ValueError, match="round leader"):
            engine.declare_friends("p1", [FriendDeclaration(card=c(S, Rank.ACE), ordinal=1)])


class TestFriendRevealFlow:
    def test_ordinal_1_reveals_on_first_play(self):
        hands = {
            "p0": [c(S, Rank.THREE)],
            "p1": [c(S, Rank.ACE)],  # friend card
            "p2": [c(S, Rank.FOUR)],
            "p3": [c(S, Rank.FIVE)],
        }
        engine, state, _ = _ff_playing(hands, [(c(S, Rank.ACE), 1)])
        engine.play_cards("p0", [c(S, Rank.THREE)])
        assert engine._player("p1").is_defending is False
        engine.play_cards("p1", [c(S, Rank.ACE)])
        assert engine._player("p1").is_defending is True
        assert "p1" in state.revealed_friends

    def test_attacking_points_reattributed_at_reveal_moment(self):
        """Issue #43: when the friend reveals, their previously-held points
        leave the live attacking total IMMEDIATELY (mid-trick), together
        with the reveal — not silently at the next trick boundary."""
        hands = {
            "p0": [c(S, Rank.THREE), c(S, Rank.SIX)],
            "p1": [c(S, Rank.TEN), c(S, Rank.ACE)],  # A♠ = friend card
            "p2": [c(S, Rank.FOUR), c(S, Rank.SEVEN)],
            "p3": [c(S, Rank.FIVE), c(S, Rank.EIGHT)],
        }
        engine, state, _ = _ff_playing(hands, [(c(S, Rank.ACE), 1)])
        # Trick 1: p1 (still an attacker) wins 15 points (10♠ + 5♠).
        engine.play_cards("p0", [c(S, Rank.THREE)])
        engine.play_cards("p1", [c(S, Rank.TEN)])
        engine.play_cards("p2", [c(S, Rank.FOUR)])
        result = engine.play_cards("p3", [c(S, Rank.FIVE)])
        assert result["trick_winner"] == "p1"
        assert state.attacking_points == 15
        # Trick 2: p1 leads the friend card — reveal flips them to defender,
        # and the live total drops at that exact play, mid-trick.
        engine.play_cards("p1", [c(S, Rank.ACE)])
        assert engine._player("p1").is_defending is True
        assert state.attacking_points == 0

    def test_ordinal_2_only_second_copy_reveals(self):
        hands = {
            "p0": [c(S, Rank.THREE)],
            "p1": [c(S, Rank.ACE)],  # first copy — should NOT reveal
            "p2": [c(S, Rank.ACE)],  # second copy — should reveal
            "p3": [c(S, Rank.FOUR)],
        }
        engine, _, _ = _ff_playing(hands, [(c(S, Rank.ACE), 2)])
        engine.play_cards("p0", [c(S, Rank.THREE)])
        engine.play_cards("p1", [c(S, Rank.ACE)])
        assert engine._player("p1").is_defending is False
        engine.play_cards("p2", [c(S, Rank.ACE)])
        assert engine._player("p2").is_defending is True
        assert engine._player("p1").is_defending is False

    def test_both_copies_in_same_trick_only_first_joins(self):
        hands = {
            "p0": [c(S, Rank.THREE)],
            "p1": [c(S, Rank.ACE)],
            "p2": [c(S, Rank.ACE)],
            "p3": [c(S, Rank.FOUR)],
        }
        engine, _, _ = _ff_playing(hands, [(c(S, Rank.ACE), 1)])
        engine.play_cards("p0", [c(S, Rank.THREE)])
        engine.play_cards("p1", [c(S, Rank.ACE)])
        engine.play_cards("p2", [c(S, Rank.ACE)])
        assert engine._player("p1").is_defending is True
        assert engine._player("p2").is_defending is False

    def test_self_friend_leader_stays_alone(self):
        """Leader declares a card they hold and plays it — still 1v3."""
        hands = {
            "p0": [c(S, Rank.ACE)],
            "p1": [c(S, Rank.THREE)],
            "p2": [c(S, Rank.FOUR)],
            "p3": [c(S, Rank.FIVE)],
        }
        engine, state, _ = _ff_playing(hands, [(c(S, Rank.ACE), 1)])
        engine.play_cards("p0", [c(S, Rank.ACE)])
        assert engine._player("p0").is_defending is True
        defenders = {p.id for p in state.players if p.is_defending}
        assert defenders == {"p0"}

    def test_friend_card_buried_in_bottom_never_reveals(self):
        hands = {
            "p0": [c(S, Rank.THREE)],
            "p1": [c(S, Rank.FOUR)],
            "p2": [c(S, Rank.FIVE)],
            "p3": [c(S, Rank.SIX)],
        }
        bottom = [c(S, Rank.ACE), c(S, Rank.ACE)]  # both copies buried
        engine, state, strategy = _ff_playing(hands, [(c(S, Rank.ACE), 1)], bottom=bottom)
        engine.play_cards("p0", [c(S, Rank.THREE)])
        engine.play_cards("p1", [c(S, Rank.FOUR)])
        engine.play_cards("p2", [c(S, Rank.FIVE)])
        engine.play_cards("p3", [c(S, Rank.SIX)])
        defenders = {p.id for p in state.players if p.is_defending}
        assert defenders == {"p0"}, "buried friend never reveals -> leader stays alone"
        assert strategy.get_attacker_ids(state) == {"p1", "p2", "p3"}

    def test_friend_revealed_on_last_trick_still_counts(self):
        hands = {
            "p0": [c(S, Rank.THREE), c(D, Rank.THREE)],
            "p1": [c(S, Rank.FOUR), c(D, Rank.ACE)],  # friend card in trick 2
            "p2": [c(S, Rank.FIVE), c(D, Rank.FOUR)],
            "p3": [c(S, Rank.SIX), c(D, Rank.FIVE)],
        }
        engine, state, _ = _ff_playing(hands, [(c(D, Rank.ACE), 1)])
        # Trick 1 (spades) — no friend card played.
        engine.play_cards("p0", [c(S, Rank.THREE)])
        engine.play_cards("p1", [c(S, Rank.FOUR)])
        engine.play_cards("p2", [c(S, Rank.FIVE)])
        engine.play_cards("p3", [c(S, Rank.SIX)])
        # Trick 2 (diamonds, the last trick) led by the trick-1 winner.
        order = ["p0", "p1", "p2", "p3"]
        idx = order.index(state.current_turn_id)
        cardmap = {
            "p0": c(D, Rank.THREE), "p1": c(D, Rank.ACE),
            "p2": c(D, Rank.FOUR), "p3": c(D, Rank.FIVE),
        }
        for pid in order[idx:] + order[:idx]:
            engine.play_cards(pid, [cardmap[pid]])
        assert engine._player("p1").is_defending is True
        assert state.phase == GamePhase.SCORING
