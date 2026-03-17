"""Tests for the Player model."""
import pytest

from shengji.models.card import Card, Rank, Suit
from shengji.models.player import Player


def make_player(**kwargs) -> Player:
    defaults = {"id": "p1", "name": "Alice"}
    defaults.update(kwargs)
    return Player(**defaults)


# ---------------------------------------------------------------------------
# Rank progression
# ---------------------------------------------------------------------------

class TestRankAdvancement:
    def test_starts_at_two(self):
        p = make_player()
        assert p.rank == Rank.TWO

    def test_advance_one_step(self):
        p = make_player()
        p.advance_rank(1)
        assert p.rank == Rank.THREE

    def test_advance_multiple_steps(self):
        p = make_player()
        p.advance_rank(3)
        assert p.rank == Rank.FIVE

    def test_advance_zero_is_noop(self):
        p = make_player()
        p.advance_rank(0)
        assert p.rank == Rank.TWO

    def test_clamps_at_ace(self):
        p = make_player(rank=Rank.QUEEN)
        p.advance_rank(5)  # Q→K→A, would go past A
        assert p.rank == Rank.ACE

    def test_advance_from_ace_stays_at_ace(self):
        p = make_player(rank=Rank.ACE)
        p.advance_rank(3)
        assert p.rank == Rank.ACE

    def test_negative_steps_raises(self):
        p = make_player()
        with pytest.raises(ValueError):
            p.advance_rank(-1)

    def test_is_at_max_rank_false(self):
        p = make_player(rank=Rank.KING)
        assert not p.is_at_max_rank

    def test_is_at_max_rank_true(self):
        p = make_player(rank=Rank.ACE)
        assert p.is_at_max_rank

    def test_full_progression_two_to_ace(self):
        p = make_player()
        p.advance_rank(12)  # TWO is index 0, ACE is index 12
        assert p.rank == Rank.ACE


# ---------------------------------------------------------------------------
# to_json
# ---------------------------------------------------------------------------

class TestPlayerToJson:
    def test_includes_hand_when_requested(self):
        card = Card(Suit.SPADES, Rank.ACE)
        p = make_player(hand=[card])
        result = p.to_json(include_hand=True)
        assert "hand" in result
        assert result["hand"] == [card.to_json()]

    def test_excludes_hand_when_not_requested(self):
        card = Card(Suit.SPADES, Rank.ACE)
        p = make_player(hand=[card])
        result = p.to_json(include_hand=False)
        assert "hand" not in result
        assert result["hand_size"] == 1

    def test_hand_size_reflects_actual_hand(self):
        p = make_player(hand=[Card(Suit.SPADES, Rank.ACE)] * 5)
        assert p.to_json(include_hand=False)["hand_size"] == 5

    def test_fields_present(self):
        p = make_player(team="team_a", is_defending=True)
        result = p.to_json()
        assert result["id"] == "p1"
        assert result["name"] == "Alice"
        assert result["rank"] == "2"
        assert result["is_defending"] is True
        assert result["team"] == "team_a"

    def test_team_none_serialised(self):
        p = make_player()
        assert p.to_json()["team"] is None
