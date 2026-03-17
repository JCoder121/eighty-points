import pytest
from shengji.models.card import Card, Rank, Suit


# ---------------------------------------------------------------------------
# point_value
# ---------------------------------------------------------------------------

def test_five_worth_5():
    assert Card(Suit.SPADES, Rank.FIVE).point_value == 5


def test_ten_worth_10():
    assert Card(Suit.HEARTS, Rank.TEN).point_value == 10


def test_king_worth_10():
    assert Card(Suit.CLUBS, Rank.KING).point_value == 10


@pytest.mark.parametrize("rank", [
    Rank.TWO, Rank.THREE, Rank.FOUR, Rank.SIX, Rank.SEVEN,
    Rank.EIGHT, Rank.NINE, Rank.JACK, Rank.QUEEN, Rank.ACE,
])
def test_non_scoring_ranks_worth_0(rank):
    assert Card(Suit.SPADES, rank).point_value == 0


def test_small_joker_worth_0():
    assert Card(Suit.JOKER, Rank.SMALL_JOKER).point_value == 0


def test_big_joker_worth_0():
    assert Card(Suit.JOKER, Rank.BIG_JOKER).point_value == 0


# ---------------------------------------------------------------------------
# Hashability and equality (frozen dataclass)
# ---------------------------------------------------------------------------

def test_cards_equal_same_suit_rank():
    assert Card(Suit.SPADES, Rank.ACE) == Card(Suit.SPADES, Rank.ACE)


def test_cards_not_equal_different_suit():
    assert Card(Suit.SPADES, Rank.ACE) != Card(Suit.HEARTS, Rank.ACE)


def test_cards_hashable_in_set():
    s = {Card(Suit.SPADES, Rank.ACE), Card(Suit.SPADES, Rank.ACE), Card(Suit.HEARTS, Rank.TWO)}
    assert len(s) == 2


def test_cards_usable_as_dict_keys():
    d = {Card(Suit.SPADES, Rank.KING): "king of spades"}
    assert d[Card(Suit.SPADES, Rank.KING)] == "king of spades"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_joker_rank_requires_joker_suit():
    with pytest.raises(ValueError):
        Card(Suit.SPADES, Rank.SMALL_JOKER)


def test_joker_suit_requires_joker_rank():
    with pytest.raises(ValueError):
        Card(Suit.JOKER, Rank.ACE)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def test_to_json_suited():
    c = Card(Suit.DIAMONDS, Rank.QUEEN)
    assert c.to_json() == {"suit": "diamonds", "rank": "Q"}


def test_to_json_joker():
    c = Card(Suit.JOKER, Rank.BIG_JOKER)
    assert c.to_json() == {"suit": "joker", "rank": "BJ"}


def test_from_json_round_trip():
    original = Card(Suit.HEARTS, Rank.SEVEN)
    assert Card.from_json(original.to_json()) == original


def test_from_json_joker_round_trip():
    original = Card(Suit.JOKER, Rank.SMALL_JOKER)
    assert Card.from_json(original.to_json()) == original
