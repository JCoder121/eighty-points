"""Gap-pin tests: Find Friends declarations, reveals, game over, and D-decisions.

Pins behavior the 2026-07-29 audit found CORRECT but untested
(docs/reports/2026-07-29-rules-audit.md §6, edge-case matrix Tier B):

  R84 / D19  game over may fire on a revealed FRIEND's pre-advance Ace
  R31 / F2   self-friend stays 1v3; a buried copy does NOT block the live copy
  R32 / B10  the leader's own copies count toward the ordinal
  R80 / D24  a lone leader who defends successfully leads again
  D25        withholding a declared friend card via a failed throw is legal
  D21        no player view carries a previous round's friend information
  R7  / B9   no-trump: a trump-rank card cannot follow its natural suit
"""
from __future__ import annotations

from shengji.engine.engine import GameEngine
from shengji.engine.tricks import is_valid_follow
from shengji.models.card import Card, Rank, Suit
from shengji.models.friend_declaration import FriendDeclaration
from shengji.models.game_state import GamePhase, GameState
from shengji.models.groups import Single
from shengji.models.trump import TrumpContext
from shengji.modes.find_friends import FindFriendsStrategy

from tests.test_integration.helpers import CL, D, H, S, c

TR = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS)
A_S = Card(Suit.SPADES, Rank.ACE)


def _ff_engine(ranks: dict[str, Rank] | None = None) -> tuple[GameEngine, GameState]:
    from tests.test_integration.helpers import make_state

    state = make_state("find_friends", "p0", ranks=ranks)
    engine = GameEngine(state, FindFriendsStrategy(), deal_delay=0)
    state.trump_context = TR
    engine.mode.assign_teams(state)  # p0 defends alone (R22)
    return engine, state


def _score_setup(state: GameState, attacker_pts: int, last_winner: str) -> None:
    kings = [c(S, Rank.KING)] * (attacker_pts // 10)
    state.tricks_won = {
        "p0": [[c(D, Rank.THREE)]],
        "p1": [kings] if kings else [],
        "p2": [],
        "p3": [],
    }
    state.bottom_deck = []
    state.current_leader_id = last_winner
    state.last_winning_play = [c(D, Rank.THREE)]
    state.phase = GamePhase.SCORING


class TestGameOverOnFriendsLevel:
    def test_d19_revealed_friend_at_ace_ends_game(self):
        """D19 (ruled 2026-07-29): the leader defends at rank 5, but the
        revealed friend was already at Ace — a successful defense ends the game."""
        engine, state = _ff_engine(ranks={"p0": Rank.FIVE, "p1": Rank.ACE})
        engine._player("p1").is_defending = True  # friend revealed during play
        state.revealed_friends = {"p1"}
        _score_setup(state, attacker_pts=70, last_winner="p0")  # defending +1
        result = engine.end_round()
        assert result["winner"] == "defending"
        assert result["game_over"] is True

    def test_no_defender_at_ace_game_continues(self):
        engine, state = _ff_engine(ranks={"p0": Rank.FIVE, "p1": Rank.KING})
        engine._player("p1").is_defending = True
        state.revealed_friends = {"p1"}
        _score_setup(state, attacker_pts=70, last_winner="p0")
        result = engine.end_round()
        assert result["winner"] == "defending"
        assert result["game_over"] is False


class TestSelfFriendAndBuriedCopy:
    def test_r31_self_friend_leader_stays_1v3(self):
        """R31: the leader declares a card they hold and plays the ordinal
        copy themselves — no other player ever becomes a friend."""
        engine, state = _ff_engine()
        state.friend_declarations = [FriendDeclaration(card=A_S, ordinal=1)]
        engine.mode.resolve_friend(state, "p0", A_S)
        assert all(
            not p.is_defending for p in state.players if p.id != "p0"
        ), "R31: leader remains alone on the defending side"
        assert state.friend_declarations[0].resolved_player_id == "p0"

    def test_f2_buried_copy_does_not_block_the_live_copy(self):
        """Audit F2: with one copy of the declared card in the bottom, the
        OTHER copy is live — the opponent who plays it becomes the friend."""
        engine, state = _ff_engine()
        state.friend_declarations = [FriendDeclaration(card=A_S, ordinal=1)]
        state.bottom_deck = [A_S] + [c(D, Rank.SIX)] * 7  # copy 1 buried
        engine.mode.resolve_friend(state, "p2", A_S)  # copy 2 played by p2
        assert engine._player("p2").is_defending is True
        assert "p2" in state.revealed_friends


class TestOrdinalCounting:
    def test_b10_leaders_own_copy_counts_toward_ordinal_two(self):
        """R32: counters count EVERY copy played by ANYONE, leader included."""
        engine, state = _ff_engine()
        state.friend_declarations = [FriendDeclaration(card=A_S, ordinal=2)]
        engine.mode.resolve_friend(state, "p0", A_S)  # copy 1: the leader's own
        assert state.revealed_friends == set()
        engine.mode.resolve_friend(state, "p1", A_S)  # copy 2 → reveal fires
        assert "p1" in state.revealed_friends
        assert engine._player("p1").is_defending is True


class TestLoneLeaderReLeads:
    def test_d24_lone_winning_leader_is_next_leader_at_new_level(self):
        """R80/D24: the winning-team scan wraps back to a lone leader; R81 —
        the next trump rank is the (advanced) leader's level."""
        engine, state = _ff_engine(ranks={"p0": Rank.FIVE})
        _score_setup(state, attacker_pts=70, last_winner="p0")  # defending +1
        result = engine.end_round()
        assert result["winner"] == "defending"
        assert result["next_round_leader_id"] == "p0"
        assert state.round_leader_id == "p0"
        assert engine._player("p0").rank == Rank.SIX  # R81: next trump rank


class TestWithholdFriendCardViaFailedThrow:
    def test_d25_forced_component_returns_friend_card_unrevealed(self):
        """D25 (ruled 2026-07-29): a beatable throw containing the declared
        friend card is forced down to the smallest beatable component; the
        friend card returns to hand, no reveal fires, and the 10 pts/card
        penalty is recorded."""
        engine, state = _ff_engine()
        # Leader declares the first K♠ as friend, then leads 3♠ + K♠ as a
        # "throw" while an opponent still holds A♠ (beats the K♠? no — the
        # SMALLEST beatable component is the 3♠, beaten by any higher spade).
        k_s = c(S, Rank.KING)
        state.friend_declarations = [FriendDeclaration(card=k_s, ordinal=1)]
        hands = {
            "p0": [c(S, Rank.THREE), k_s] + [c(D, r) for r in (
                Rank.FOUR, Rank.FIVE, Rank.SIX)],
            "p1": [c(S, Rank.ACE), c(S, Rank.FOUR), c(CL, Rank.FOUR),
                   c(CL, Rank.FIVE), c(CL, Rank.SIX)],
            "p2": [c(D, Rank.SEVEN), c(D, Rank.EIGHT), c(D, Rank.NINE),
                   c(D, Rank.TEN), c(D, Rank.JACK)],
            "p3": [c(CL, Rank.SEVEN), c(CL, Rank.EIGHT), c(CL, Rank.NINE),
                   c(CL, Rank.TEN), c(CL, Rank.JACK)],
        }
        for pid, hand in hands.items():
            engine._player(pid).hand = list(hand)
        state.phase = GamePhase.PLAYING
        state.current_leader_id = "p0"
        state.current_turn_id = "p0"

        result = engine.play_cards("p0", [c(S, Rank.THREE), k_s])
        assert result.get("throw_failed") is True
        assert result["forced_cards"] == [c(S, Rank.THREE)]
        assert result["penalty"] == 20  # 10 x 2 attempted cards
        assert k_s in engine._player("p0").hand, (
            "D25: the declared friend card returns to hand"
        )
        assert state.revealed_friends == set(), "no reveal fires"
        assert state.throw_penalties == {"p0": 20}


class TestRedactionAcrossRounds:
    def test_d21_views_carry_no_previous_round_friend_info(self):
        engine, state = _ff_engine()
        state.friend_declarations = [
            FriendDeclaration(card=A_S, ordinal=1, resolved_player_id="p2")
        ]
        state.revealed_friends = {"p2"}
        state.phase = GamePhase.ROUND_OVER
        engine.start_dealing()
        assert state.revealed_friends == set()
        assert state.friend_declarations == []
        assert state.friend_play_counts == {}
        for pid in ("p0", "p1", "p2", "p3"):
            view = state.to_player_view(pid)
            assert view.get("revealed_friends") in (None, [], set()), (
                f"D21: {pid}'s view leaks last round's friend"
            )
            assert view.get("friend_declarations") in (None, []), (
                f"D21: {pid}'s view leaks last round's declaration"
            )


class TestNoTrumpTrumpRankFollow:
    """B9 / R7 at follow level: in no-trump, a trump-rank card belongs to the
    effective suit "trump" and can never follow its natural suit."""

    NT = TrumpContext(trump_rank=Rank.TWO, trump_suit=None)

    def test_holder_of_only_2h_is_void_in_hearts(self):
        hand = [c(H, Rank.TWO), c(CL, Rank.NINE), c(D, Rank.FOUR)]
        led = Single()
        # Void in hearts (the 2♥ is trump): any card is a legal follow.
        assert is_valid_follow([c(CL, Rank.NINE)], hand, led, "hearts", self.NT)
        assert is_valid_follow([c(D, Rank.FOUR)], hand, led, "hearts", self.NT)

    def test_2h_must_follow_a_trump_lead(self):
        hand = [c(H, Rank.TWO), c(CL, Rank.NINE), c(D, Rank.FOUR)]
        led = Single()  # a trump-rank single was led (effective suit "trump")
        assert is_valid_follow([c(H, Rank.TWO)], hand, led, "trump", self.NT)
        assert not is_valid_follow([c(CL, Rank.NINE)], hand, led, "trump", self.NT), (
            "R7: the 2♥ is the player's only trump and must be played"
        )
