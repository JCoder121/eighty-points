"""Gap pins for the bottom multiplier and the >200-point ceiling.

Behavior probed and found correct during the Phase-2 audit (edge-case matrix
cells 5.14, 5.21, 5.22 and R62).  Rule numbers refer to ``docs/RULES.md``.

Covered:
  R68        multiplier when the last trick's WINNING PLAY is a Throw
  D15 × FF   Find Friends: a revealed friend winning the last trick suppresses
             the bottom; an attacker winning after a reveal still multiplies
  R62        the attacking total may exceed 200 via the multiplier
"""
from __future__ import annotations

from shengji.engine.engine import GameEngine
from shengji.engine.scoring import compute_rank_advancement, count_attacking_points
from shengji.models.card import Card, Rank, Suit
from shengji.models.friend_declaration import FriendDeclaration
from shengji.models.game_state import GamePhase, GameState
from shengji.models.groups import Throw, classify_play
from shengji.models.player import Player
from shengji.models.trump import TrumpContext
from shengji.modes.find_friends import FindFriendsStrategy


def _c(suit: Suit, rank: Rank) -> Card:
    return Card(suit=suit, rank=rank)


def _s(rank: Rank) -> Card:
    return _c(Suit.SPADES, rank)


def _d(rank: Rank) -> Card:
    return _c(Suit.DIAMONDS, rank)


CTX = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.HEARTS)

KING_S = _s(Rank.KING)
THREE_S = _s(Rank.THREE)   # 0 pts
FIVE_S = _s(Rank.FIVE)


def _no_tricks() -> dict[str, list[list[Card]]]:
    return {"p0": [], "p1": [], "p2": [], "p3": []}


# ---------------------------------------------------------------------------
# R68 — the winning play is a THROW
# ---------------------------------------------------------------------------

class TestMultiplierFromThrowWinningPlay:
    """R68's last bullet: 2 × the largest component's card count, capped at 8.

    ``scoring._format_component_cards`` has a dedicated Throw branch that no
    committed test exercised.
    """

    BOTTOM = [KING_S, THREE_S]  # 10 pts buried

    def _points(self, winning_play: list[Card]) -> int:
        return count_attacking_points(
            tricks_won=_no_tricks(),
            attacker_ids={"p0"},
            bottom_deck=self.BOTTOM,
            last_trick_winner_id="p0",
            last_trick_cards=winning_play,
            ctx=CTX,
        )

    def test_largest_component_is_a_pair_gives_x4(self):
        play = [_s(Rank.ACE), _s(Rank.ACE), _s(Rank.NINE)]
        assert isinstance(classify_play(play, CTX), Throw)
        assert self._points(play) == 4 * 10

    def test_largest_component_is_a_four_card_tractor_gives_x8(self):
        play = [_s(Rank.ACE), _s(Rank.ACE), _s(Rank.KING), _s(Rank.KING), _s(Rank.NINE)]
        assert isinstance(classify_play(play, CTX), Throw)
        assert self._points(play) == 8 * 10

    def test_two_singles_give_x2(self):
        play = [_s(Rank.ACE), _s(Rank.JACK)]
        assert isinstance(classify_play(play, CTX), Throw)
        assert self._points(play) == 2 * 10


# ---------------------------------------------------------------------------
# D15 × Find Friends — the multiplier reads FINAL team membership
# ---------------------------------------------------------------------------

def _make_ff_engine(hands: dict[str, list[Card]], bottom: list[Card]) -> GameEngine:
    """Find Friends engine in PLAYING: p0 leads and defends alone."""
    players = [Player(id=f"p{i}", name=f"P{i}") for i in range(4)]
    state = GameState(players=players, mode="find_friends", round_leader_id="p0")
    state.phase = GamePhase.PLAYING
    state.trump_context = CTX
    state.tricks_won = {p.id: [] for p in players}
    state.bottom_deck = list(bottom)
    state.current_turn_id = "p0"
    state.current_leader_id = "p0"
    for p in players:
        p.hand = list(hands[p.id])
    strategy = FindFriendsStrategy()
    engine = GameEngine(state, strategy, deal_delay=0)
    strategy.assign_teams(state)
    # 8♦ (first copy) is the declared friend card.
    state.friend_declarations = [FriendDeclaration(card=_d(Rank.EIGHT), ordinal=1)]
    return engine


class TestFindFriendsBottomMultiplier:
    BOTTOM = [KING_S, KING_S]  # 20 pts buried

    def test_revealed_friend_wins_last_trick_suppresses_the_bottom(self):
        # p1 plays the declared 8♦ and flips to defending, then wins the final
        # trick — D15 uses FINAL teams, so the bottom scores for nobody.
        engine = _make_ff_engine(
            {
                "p0": [_d(Rank.THREE), _d(Rank.SIX)],
                "p1": [_d(Rank.EIGHT), _d(Rank.ACE)],
                "p2": [_d(Rank.FOUR), _d(Rank.SEVEN)],
                "p3": [_d(Rank.FIVE), _d(Rank.NINE)],
            },
            bottom=self.BOTTOM,
        )
        state = engine.state
        assert not state.players[1].is_defending

        engine.play_cards("p0", [_d(Rank.THREE)])
        engine.play_cards("p1", [_d(Rank.EIGHT)])      # reveal
        engine.play_cards("p2", [_d(Rank.FOUR)])
        first = engine.play_cards("p3", [_d(Rank.FIVE)])
        assert state.players[1].is_defending
        assert first["trick_winner"] == "p1"           # 8♦ is high

        engine.play_cards("p1", [_d(Rank.ACE)])
        engine.play_cards("p2", [_d(Rank.SEVEN)])
        engine.play_cards("p3", [_d(Rank.NINE)])
        last = engine.play_cards("p0", [_d(Rank.SIX)])
        assert last["trick_winner"] == "p1"            # a DEFENDER takes the last trick
        assert last["round_over"] is True

        result = engine.end_round()
        # The friend captured the 5♦; attackers p2/p3 captured nothing and the
        # 20-point bottom is suppressed entirely.
        assert result["attacking_points"] == 0

    def test_attacker_wins_last_trick_after_a_reveal_still_multiplies(self):
        # Same reveal, but attacker p3 takes the final trick with a single →
        # ×2 on the 20-point bottom, on top of the 5 pts in that trick.
        engine = _make_ff_engine(
            {
                "p0": [_d(Rank.THREE), _d(Rank.FIVE)],
                "p1": [_d(Rank.EIGHT), _d(Rank.SIX)],
                "p2": [_d(Rank.FOUR), _d(Rank.SEVEN)],
                "p3": [_d(Rank.NINE), _d(Rank.ACE)],
            },
            bottom=self.BOTTOM,
        )
        state = engine.state

        engine.play_cards("p0", [_d(Rank.THREE)])
        engine.play_cards("p1", [_d(Rank.EIGHT)])      # reveal
        engine.play_cards("p2", [_d(Rank.FOUR)])
        first = engine.play_cards("p3", [_d(Rank.NINE)])
        assert state.players[1].is_defending
        assert first["trick_winner"] == "p3"

        engine.play_cards("p3", [_d(Rank.ACE)])
        engine.play_cards("p0", [_d(Rank.FIVE)])       # 5 pts into the last trick
        engine.play_cards("p1", [_d(Rank.SIX)])
        last = engine.play_cards("p2", [_d(Rank.SEVEN)])
        assert last["trick_winner"] == "p3"            # an ATTACKER takes it

        result = engine.end_round()
        assert engine.mode.get_attacker_ids(state) == {"p2", "p3"}
        assert result["attacking_points"] == 5 + 2 * 20


# ---------------------------------------------------------------------------
# R62 — the attacking total may exceed 200
# ---------------------------------------------------------------------------

class TestTotalCanExceed200:
    def test_multiplier_pushes_the_total_past_200_and_bands_still_apply(self):
        # Attackers capture 100 pts in tricks; the bottom holds 40 pts and an
        # attacker wins the last trick with a 4-card tractor → ×8.
        attacker_tricks = [[KING_S] * 8, [FIVE_S] * 4]           # 80 + 20 = 100
        bottom = [KING_S] * 4 + [THREE_S] * 4                    # 40 pts
        tractor = [
            _s(Rank.ACE), _s(Rank.ACE), _s(Rank.KING), _s(Rank.KING),
        ]

        pts = count_attacking_points(
            tricks_won={"p0": attacker_tricks, "p1": [], "p2": [], "p3": []},
            attacker_ids={"p0"},
            bottom_deck=bottom,
            last_trick_winner_id="p0",
            last_trick_cards=tractor,
            ctx=CTX,
        )

        assert pts == 100 + 8 * 40    # 420
        assert pts > 200
        # R76's top band is 140+, capped at +3 — a huge total must not
        # over-promote (issue #51).
        assert compute_rank_advancement(pts) == ("attacking", 3)
