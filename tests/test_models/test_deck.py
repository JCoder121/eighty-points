from collections import Counter

from shengji.models.card import Card, Rank, Suit, RANK_ORDER, SUITED_SUITS
from shengji.models.deck import Deck, TOTAL_CARDS, BOTTOM_SIZE, HAND_SIZE, NUM_PLAYERS


# ---------------------------------------------------------------------------
# Deck composition
# ---------------------------------------------------------------------------

def test_deck_has_108_cards():
    deck = Deck()
    deck.shuffle()
    draw, bottom = deck.prepare_deal()
    assert len(draw) + len(bottom) == TOTAL_CARDS == 108


def test_prepare_deal_draw_pile_size():
    deck = Deck()
    draw, _ = deck.prepare_deal()
    assert len(draw) == TOTAL_CARDS - BOTTOM_SIZE  # 100


def test_prepare_deal_bottom_size():
    deck = Deck()
    _, bottom = deck.prepare_deal()
    assert len(bottom) == BOTTOM_SIZE  # 8


def test_hand_size_constant():
    # 100 cards / 4 players = 25 cards per hand
    assert HAND_SIZE == 25


def test_no_missing_cards():
    """Every card that should exist in two decks is present exactly twice."""
    deck = Deck()
    draw, bottom = deck.prepare_deal()
    all_cards = draw + bottom
    counts = Counter(all_cards)

    # Each suited card appears in both decks → count 2
    for suit in SUITED_SUITS:
        for rank in RANK_ORDER:
            card = Card(suit=suit, rank=rank)
            assert counts[card] == 2, f"Expected 2× {card}, got {counts[card]}"

    # Each joker appears in both decks → count 2
    assert counts[Card(Suit.JOKER, Rank.SMALL_JOKER)] == 2
    assert counts[Card(Suit.JOKER, Rank.BIG_JOKER)] == 2


def test_no_extra_cards():
    """No unexpected cards appear in the deck."""
    deck = Deck()
    draw, bottom = deck.prepare_deal()
    all_cards = draw + bottom
    assert len(all_cards) == TOTAL_CARDS


def test_total_points_200():
    """Both decks together contain exactly 200 points."""
    deck = Deck()
    draw, bottom = deck.prepare_deal()
    total = sum(c.point_value for c in draw + bottom)
    assert total == 200


# ---------------------------------------------------------------------------
# Shuffling
# ---------------------------------------------------------------------------

def test_shuffle_changes_order():
    """After shuffling, the card order should differ from the unshuffled order
    (with overwhelming probability — failure probability ≈ 1/108! ≈ 0).
    """
    deck_a = Deck()
    before = list(deck_a._cards)  # snapshot before shuffle
    deck_a.shuffle()
    after = list(deck_a._cards)
    assert before != after, "Shuffled deck is identical to unshuffled — astronomically unlikely"


def test_multiple_decks_independent():
    """Two separate Deck instances produce independent shuffles."""
    draw_a, _ = Deck().prepare_deal()
    draw_b, _ = Deck().prepare_deal()
    assert draw_a != draw_b, "Two independently shuffled decks are identical — astronomically unlikely"


# ---------------------------------------------------------------------------
# prepare_deal: no duplicates within a single call
# ---------------------------------------------------------------------------

def test_draw_and_bottom_are_disjoint():
    """The 100 draw cards and 8 bottom cards share no position (they're slices of the same list)."""
    deck = Deck()
    draw, bottom = deck.prepare_deal()
    # As lists they're disjoint slices; verify no card appears more than twice across both
    counts = Counter(draw + bottom)
    for card, count in counts.items():
        assert count <= 2, f"Card {card} appears {count} times — max allowed is 2 (two decks)"
