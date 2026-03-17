from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Union

from shengji.models.card import Card
from shengji.models.trump import TrumpContext


# ---------------------------------------------------------------------------
# TrickFormat types
# ---------------------------------------------------------------------------

@dataclass
class Single:
    """One card."""


@dataclass
class IdenticalGroup:
    """N copies of the same card (pair, triple, quad, …)."""
    count: int


@dataclass
class Tractor:
    """A sequence of consecutive identical groups.

    multiplicity — number of cards at each rank position (usually 2 for pairs)
    length        — number of consecutive rank positions
    Total cards   = multiplicity × length  (minimum 4: a pair of pairs)
    """
    multiplicity: int
    length: int


@dataclass
class Throw:
    """A multi-component lead (甩牌): more than one distinct format component."""
    components: list[TrickFormat] = field(default_factory=list)


TrickFormat = Union[Single, IdenticalGroup, Tractor, Throw]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _position_groups(
    cards: list[Card], ctx: TrumpContext
) -> dict[tuple[int, int], list[Card]]:
    """Group cards by their (tier, rank_pos) key from card_order."""
    groups: dict[tuple[int, int], list[Card]] = defaultdict(list)
    for card in cards:
        groups[ctx.card_order(card)].append(card)
    return dict(groups)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_identical_groups(cards: list[Card], ctx: TrumpContext) -> list[list[Card]]:
    """Group cards by exact identity (same suit AND rank).

    Returns only groups of size >= 2 (pairs, triples, quads).
    ctx is accepted for API consistency but exact-identity grouping does not
    depend on trump context.
    """
    groups: dict[tuple, list[Card]] = defaultdict(list)
    for card in cards:
        groups[(card.suit, card.rank)].append(card)
    return [g for g in groups.values() if len(g) >= 2]


def find_tractors(cards: list[Card], ctx: TrumpContext) -> list[list[Card]]:
    """Find all maximal tractors in *cards*.

    A tractor is a run of >= 2 consecutive rank-positions (per card_order)
    where every position holds >= 2 cards.  Consecutive positions are
    determined by TrumpContext.are_tractor_adjacent — including the circular
    wrap for non-trump suits and cross-tier adjacency in the trump hierarchy.

    Returns a list of card-lists; each sub-list is one tractor (the cards
    that make it up, taking *multiplicity* cards from each position).

    Note: when the run has more cards at some positions than others, only
    *min* cards per position are included so the result is a valid tractor.
    Leftover cards at those positions remain in the caller's hands.

    Limitation: the algorithm performs a linear scan over sorted positions and
    therefore detects the circular wrap only when the wrapped positions happen
    to be the sole members of tier 0 being examined.  Runs of 3+ positions
    that wrap (e.g. K♠♠ A♠♠ 3♠♠ when trump rank=2) are not guaranteed to be
    detected as a single tractor; they are detected as two separate runs.
    """
    pos_groups = _position_groups(cards, ctx)

    # Only positions with >= 2 cards can be part of a tractor
    pair_positions = {pos: grp for pos, grp in pos_groups.items() if len(grp) >= 2}

    if len(pair_positions) < 2:
        return []

    sorted_positions = sorted(pair_positions.keys())

    tractors: list[list[Card]] = []
    current_run: list[tuple[int, int]] = [sorted_positions[0]]

    for i in range(1, len(sorted_positions)):
        prev_pos = current_run[-1]
        curr_pos = sorted_positions[i]
        # Use a representative card from each position for adjacency check
        prev_card = pair_positions[prev_pos][0]
        curr_card = pair_positions[curr_pos][0]
        if ctx.are_tractor_adjacent(prev_card, curr_card):
            current_run.append(curr_pos)
        else:
            if len(current_run) >= 2:
                tractors.append(_build_tractor(current_run, pair_positions))
            current_run = [curr_pos]

    if len(current_run) >= 2:
        tractors.append(_build_tractor(current_run, pair_positions))

    return tractors


def _build_tractor(
    run: list[tuple[int, int]],
    pair_positions: dict[tuple[int, int], list[Card]],
) -> list[Card]:
    """Build the card list for a tractor run, using min multiplicity."""
    mult = min(len(pair_positions[pos]) for pos in run)
    result: list[Card] = []
    for pos in run:
        result.extend(pair_positions[pos][:mult])
    return result


def classify_play(cards: list[Card], ctx: TrumpContext) -> TrickFormat:
    """Classify a set of played cards into a TrickFormat.

    Recognised formats (in priority order):
      Single          — exactly 1 card
      IdenticalGroup  — all cards at the same card_order position
      Tractor         — all cards form one tractor
      Throw           — everything else (mixed components)
    """
    n = len(cards)
    if n == 0:
        raise ValueError("Cannot classify an empty play")

    if n == 1:
        return Single()

    pos_groups = _position_groups(cards, ctx)

    # All cards at the same position → identical group (pair, triple, …)
    if len(pos_groups) == 1:
        return IdenticalGroup(count=n)

    # Check for a single tractor covering all cards
    tractors = find_tractors(cards, ctx)
    if len(tractors) == 1 and len(tractors[0]) == n:
        mult = min(len(g) for g in pos_groups.values())
        length = len(pos_groups)
        return Tractor(multiplicity=mult, length=length)

    # Otherwise it's a throw — decompose greedily into tractors then groups/singles
    components: list[TrickFormat] = []
    remaining = list(cards)

    for tractor_cards in tractors:
        sub = classify_play(tractor_cards, ctx)
        components.append(sub)
        for c in tractor_cards:
            remaining.remove(c)

    # Classify what's left position-by-position
    for grp in _position_groups(remaining, ctx).values():
        if len(grp) == 1:
            components.append(Single())
        else:
            components.append(IdenticalGroup(count=len(grp)))

    return Throw(components=components)
