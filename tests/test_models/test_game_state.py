"""Tests for GameState: phase transitions, player views, superuser view."""
import pytest

from shengji.models.bid import Bid
from shengji.models.card import Card, Rank, Suit
from shengji.models.friend_declaration import FriendDeclaration
from shengji.models.game_state import GamePhase, GameState
from shengji.models.player import Player
from shengji.models.trump import TrumpContext

S, H, D, C = Suit.SPADES, Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS


def make_card(suit: Suit, rank: Rank) -> Card:
    return Card(suit=suit, rank=rank)


def make_players(n: int = 4) -> list[Player]:
    names = ["Alice", "Bob", "Carol", "Dave"]
    return [Player(id=f"p{i}", name=names[i]) for i in range(n)]


def make_state(**kwargs) -> GameState:
    state = GameState(players=make_players(), mode="upgrade")
    for k, v in kwargs.items():
        setattr(state, k, v)
    return state


# ---------------------------------------------------------------------------
# Phase transitions
# ---------------------------------------------------------------------------

class TestPhaseTransitions:
    def test_waiting_to_dealing(self):
        state = GameState()
        state.transition_to(GamePhase.DEALING)
        assert state.phase == GamePhase.DEALING

    def test_dealing_to_bidding_after_deal(self):
        state = GameState(phase=GamePhase.DEALING)
        state.transition_to(GamePhase.BIDDING_AFTER_DEAL)
        assert state.phase == GamePhase.BIDDING_AFTER_DEAL

    def test_bidding_after_deal_to_bottom_exchange(self):
        state = GameState(phase=GamePhase.BIDDING_AFTER_DEAL)
        state.transition_to(GamePhase.BOTTOM_EXCHANGE)
        assert state.phase == GamePhase.BOTTOM_EXCHANGE

    def test_bidding_after_deal_to_dealing_redeal(self):
        """No bids → re-deal: BIDDING_AFTER_DEAL → DEALING is allowed."""
        state = GameState(phase=GamePhase.BIDDING_AFTER_DEAL)
        state.transition_to(GamePhase.DEALING)
        assert state.phase == GamePhase.DEALING

    def test_bidding_after_deal_to_friend_declaration(self):
        state = GameState(phase=GamePhase.BIDDING_AFTER_DEAL)
        state.transition_to(GamePhase.FRIEND_DECLARATION)
        assert state.phase == GamePhase.FRIEND_DECLARATION

    def test_friend_declaration_to_bottom_exchange(self):
        state = GameState(phase=GamePhase.FRIEND_DECLARATION)
        state.transition_to(GamePhase.BOTTOM_EXCHANGE)
        assert state.phase == GamePhase.BOTTOM_EXCHANGE

    def test_bottom_exchange_to_playing(self):
        state = GameState(phase=GamePhase.BOTTOM_EXCHANGE)
        state.transition_to(GamePhase.PLAYING)
        assert state.phase == GamePhase.PLAYING

    def test_playing_to_scoring(self):
        state = GameState(phase=GamePhase.PLAYING)
        state.transition_to(GamePhase.SCORING)
        assert state.phase == GamePhase.SCORING

    def test_scoring_to_round_over(self):
        state = GameState(phase=GamePhase.SCORING)
        state.transition_to(GamePhase.ROUND_OVER)
        assert state.phase == GamePhase.ROUND_OVER

    def test_round_over_to_dealing(self):
        state = GameState(phase=GamePhase.ROUND_OVER)
        state.transition_to(GamePhase.DEALING)
        assert state.phase == GamePhase.DEALING

    def test_round_over_to_game_over(self):
        state = GameState(phase=GamePhase.ROUND_OVER)
        state.transition_to(GamePhase.GAME_OVER)
        assert state.phase == GamePhase.GAME_OVER

    def test_game_over_has_no_transitions(self):
        state = GameState(phase=GamePhase.GAME_OVER)
        with pytest.raises(ValueError):
            state.transition_to(GamePhase.DEALING)

    def test_waiting_to_playing_invalid(self):
        state = GameState()
        with pytest.raises(ValueError):
            state.transition_to(GamePhase.PLAYING)

    def test_dealing_to_scoring_invalid(self):
        state = GameState(phase=GamePhase.DEALING)
        with pytest.raises(ValueError):
            state.transition_to(GamePhase.SCORING)

    def test_error_message_lists_allowed_phases(self):
        state = GameState(phase=GamePhase.WAITING)
        with pytest.raises(ValueError, match="dealing"):
            state.transition_to(GamePhase.SCORING)


# ---------------------------------------------------------------------------
# to_player_view — information hiding
# ---------------------------------------------------------------------------

class TestPlayerView:
    def _state_with_hands(self) -> GameState:
        players = make_players()
        players[0].hand = [make_card(S, Rank.ACE), make_card(S, Rank.KING)]
        players[1].hand = [make_card(H, Rank.ACE)]
        players[2].hand = [make_card(D, Rank.ACE)]
        players[3].hand = [make_card(C, Rank.ACE)]
        return GameState(players=players, mode="upgrade", phase=GamePhase.PLAYING)

    def test_own_hand_visible(self):
        state = self._state_with_hands()
        view = state.to_player_view("p0")
        own = next(p for p in view["players"] if p["id"] == "p0")
        assert "hand" in own
        assert len(own["hand"]) == 2

    def test_other_hands_hidden(self):
        state = self._state_with_hands()
        view = state.to_player_view("p0")
        for p in view["players"]:
            if p["id"] != "p0":
                assert "hand" not in p
                assert "hand_size" in p

    def test_opponent_hand_size_correct(self):
        state = self._state_with_hands()
        view = state.to_player_view("p0")
        p1_view = next(p for p in view["players"] if p["id"] == "p1")
        assert p1_view["hand_size"] == 1

    def test_bottom_deck_hidden_during_playing(self):
        state = self._state_with_hands()
        state.bottom_deck = [make_card(S, Rank.FIVE)] * 8
        state.round_leader_id = "p0"
        view = state.to_player_view("p0")
        assert view["bottom_deck"] is None

    def test_bottom_deck_visible_to_leader_during_exchange(self):
        state = self._state_with_hands()
        state.phase = GamePhase.BOTTOM_EXCHANGE
        state.round_leader_id = "p0"
        state.bottom_deck = [make_card(S, Rank.FIVE)] * 8
        view = state.to_player_view("p0")
        assert view["bottom_deck"] is not None
        assert len(view["bottom_deck"]) == 8

    def test_bottom_deck_hidden_to_non_leader_during_exchange(self):
        state = self._state_with_hands()
        state.phase = GamePhase.BOTTOM_EXCHANGE
        state.round_leader_id = "p0"
        state.bottom_deck = [make_card(S, Rank.FIVE)] * 8
        view = state.to_player_view("p1")
        assert view["bottom_deck"] is None

    def test_phase_and_mode_present(self):
        state = self._state_with_hands()
        view = state.to_player_view("p0")
        assert view["phase"] == "playing"
        assert view["mode"] == "upgrade"

    def test_trump_context_none_serialised(self):
        state = self._state_with_hands()
        view = state.to_player_view("p0")
        assert view["trump_context"] is None

    def test_trump_context_serialised(self):
        state = self._state_with_hands()
        state.trump_context = TrumpContext(trump_rank=Rank.TWO, trump_suit=H)
        view = state.to_player_view("p0")
        assert view["trump_context"] == {"trump_rank": "2", "trump_suit": "hearts"}

    def test_current_trick_serialised(self):
        state = self._state_with_hands()
        state.current_trick = [("p0", [make_card(S, Rank.ACE)])]
        view = state.to_player_view("p0")
        assert view["current_trick"] == [
            {"player_id": "p0", "cards": [{"suit": "spades", "rank": "A"}]}
        ]

    def test_bids_serialised(self):
        state = self._state_with_hands()
        tc = TrumpContext(trump_rank=Rank.TWO, trump_suit=H)
        state.bids = [Bid(player_id="p0", cards=[make_card(H, Rank.TWO)], resulting_trump=tc)]
        view = state.to_player_view("p0")
        assert len(view["bids"]) == 1
        assert view["bids"][0]["player_id"] == "p0"


# ---------------------------------------------------------------------------
# to_superuser_view — full visibility
# ---------------------------------------------------------------------------

class TestSuperuserView:
    def test_all_hands_visible(self):
        players = make_players()
        for i, p in enumerate(players):
            p.hand = [make_card(S, Rank.ACE)] * (i + 1)
        state = GameState(players=players, mode="upgrade", phase=GamePhase.PLAYING)
        view = state.to_superuser_view()
        for i, p in enumerate(view["players"]):
            assert "hand" in p
            assert len(p["hand"]) == i + 1

    def test_bottom_deck_always_visible(self):
        state = make_state(
            phase=GamePhase.BOTTOM_EXCHANGE,
            bottom_deck=[make_card(S, Rank.FIVE)] * 8,
        )
        view = state.to_superuser_view()
        assert len(view["bottom_deck"]) == 8

    def test_draw_pile_size_present(self):
        state = make_state(draw_pile=[make_card(S, Rank.ACE)] * 10)
        view = state.to_superuser_view()
        assert view["draw_pile_size"] == 10

    def test_tricks_won_serialised(self):
        state = make_state()
        state.tricks_won = {"p0": [[make_card(S, Rank.ACE)]]}
        view = state.to_superuser_view()
        assert view["tricks_won"]["p0"] == [[{"suit": "spades", "rank": "A"}]]

    def test_friend_declarations_serialised(self):
        state = make_state(mode="find_friends")
        fd = FriendDeclaration(card=make_card(S, Rank.ACE), ordinal=1)
        state.friend_declarations = [fd]
        view = state.to_superuser_view()
        assert len(view["friend_declarations"]) == 1
        assert view["friend_declarations"][0]["ordinal"] == 1

    def test_revealed_friends_present(self):
        state = make_state()
        state.revealed_friends = {"p1", "p2"}
        view = state.to_superuser_view()
        assert set(view["revealed_friends"]) == {"p1", "p2"}

    def test_round_leader_id_present(self):
        state = make_state(round_leader_id="p2")
        view = state.to_superuser_view()
        assert view["round_leader_id"] == "p2"


# ---------------------------------------------------------------------------
# FriendDeclaration
# ---------------------------------------------------------------------------

class TestFriendDeclaration:
    def test_unresolved_by_default(self):
        fd = FriendDeclaration(card=make_card(S, Rank.ACE), ordinal=1)
        assert not fd.is_resolved
        assert fd.resolved_player_id is None

    def test_resolved_after_set(self):
        fd = FriendDeclaration(card=make_card(S, Rank.ACE), ordinal=1, resolved_player_id="p3")
        assert fd.is_resolved

    def test_to_json(self):
        fd = FriendDeclaration(card=make_card(S, Rank.ACE), ordinal=2, resolved_player_id="p1")
        result = fd.to_json()
        assert result["card"] == {"suit": "spades", "rank": "A"}
        assert result["ordinal"] == 2
        assert result["resolved_player_id"] == "p1"


# ---------------------------------------------------------------------------
# Bid
# ---------------------------------------------------------------------------

class TestBid:
    def test_to_json(self):
        tc = TrumpContext(trump_rank=Rank.TWO, trump_suit=H)
        bid = Bid(player_id="p0", cards=[make_card(H, Rank.TWO)], resulting_trump=tc)
        result = bid.to_json()
        assert result["player_id"] == "p0"
        assert result["cards"] == [{"suit": "hearts", "rank": "2"}]
        assert result["resulting_trump"] == {"trump_rank": "2", "trump_suit": "hearts"}

    def test_no_trump_bid_to_json(self):
        tc = TrumpContext(trump_rank=Rank.TWO, trump_suit=None)
        bid = Bid(player_id="p1", cards=[make_card(S, Rank.TWO), make_card(H, Rank.TWO)], resulting_trump=tc)
        result = bid.to_json()
        assert result["resulting_trump"]["trump_suit"] is None
