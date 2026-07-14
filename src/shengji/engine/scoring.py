"""Round scoring utilities.

Implements the rank-advancement threshold table and the bottom-deck point
multiplier.

Public API
----------
count_attacking_points(...)
    Sum the points won by the attacking team; if an attacker won the last
    trick, bottom-deck points are added at a multiplier set by the winning
    play's largest component (2x single, 4x pair, 8x tractor — capped at 8).

compute_rank_advancement(attacking_points, n_decks)
    Return (winner, steps).  For n_decks=2: threshold 80, 20-point bands.
    0-19 defending +4 | 20-39 +3 | 40-59 +2 | 60-79 +1 |
    80-99 attacking +0 (take over) | 100-119 +1 | 120-139 +2 | 140+ +3 (cap).

The authoritative table is the one implemented below (settled Session 23,
cap added in issue #51); older planning docs describing 200n/300n thresholds
are obsolete.
"""
from __future__ import annotations

from shengji.models.card import Card
from shengji.models.groups import classify_play, Tractor, IdenticalGroup, Throw
from shengji.models.trump import TrumpContext


# ---------------------------------------------------------------------------
# Bottom deck multiplier
# ---------------------------------------------------------------------------

_MAX_BOTTOM_MULTIPLIER = 8


def _largest_component_cards(cards: list[Card], ctx: TrumpContext) -> int:
    """Return the CARD COUNT of the largest component of a play.

    Used for the bottom-deck multiplier (issue #57): 2 × this count, capped
    at 8 — single 2×, pair 4×, tractor (4+ cards) 8×.
    """
    if not cards:
        return 1
    fmt = classify_play(cards, ctx)
    return _format_component_cards(fmt)


def _format_component_cards(fmt) -> int:
    if isinstance(fmt, Tractor):
        return fmt.multiplicity * fmt.length
    if isinstance(fmt, IdenticalGroup):
        return fmt.count
    if isinstance(fmt, Throw):
        return max(_format_component_cards(c) for c in fmt.components)
    return 1  # Single


# ---------------------------------------------------------------------------
# Point counting
# ---------------------------------------------------------------------------

def count_attacking_points(
    tricks_won: dict[str, list[list[Card]]],
    attacker_ids: set[str],
    bottom_deck: list[Card],
    last_trick_winner_id: str,
    last_trick_cards: list[Card],
    ctx: TrumpContext,
) -> int:
    """Compute the total attacking points for this round.

    Parameters
    ----------
    tricks_won:
        Map of player_id → list of tricks (each trick is a list of Card).
    attacker_ids:
        Set of player IDs on the attacking team.
    bottom_deck:
        The 8 cards currently buried.
    last_trick_winner_id:
        The player who won the final trick.
    last_trick_cards:
        The WINNING PLAY of the final trick (not the whole 4-player pile);
        its largest component sets the bottom multiplier (issue #57).
    ctx:
        Current TrumpContext (for classifying the winning play's format).

    Returns
    -------
    Total attacking points including any bottom-deck multiplier.
    """
    # Base points from tricks won by attackers
    base_pts = 0
    for pid, tricks in tricks_won.items():
        if pid in attacker_ids:
            for trick in tricks:
                base_pts += sum(c.point_value for c in trick)

    # Bottom deck multiplier (only if an attacker wins the last trick)
    bottom_pts = sum(c.point_value for c in bottom_deck)
    if last_trick_winner_id in attacker_ids and bottom_pts > 0:
        multiplier = min(
            _MAX_BOTTOM_MULTIPLIER,
            2 * _largest_component_cards(last_trick_cards, ctx),
        )
        base_pts += multiplier * bottom_pts

    return base_pts


# ---------------------------------------------------------------------------
# Rank advancement threshold table
# ---------------------------------------------------------------------------

def compute_rank_advancement(
    attacking_points: int,
    n_decks: int = 2,
) -> tuple[str, int]:
    """Return (winner, steps) for rank advancement.

    winner — "attacking" or "defending"
    steps  — number of ranks to advance (0 means the attacking team takes
              over as defenders at the same rank; the "winner" field is still
              "attacking" in this case to indicate they take over).

    Threshold table (threshold = 40 * n_decks = 80; step = 10 * n_decks = 20):
      attacking_points      winner       steps
      ──────────────────────────────────────────
      0  to 19              defending    4
      20 to 39              defending    3
      40 to 59              defending    2
      60 to 79              defending    1
      80 to 99              attacking    0   (take over at same rank)
      100 to 119            attacking    1
      120 to 139            attacking    2
      140+                  attacking    3

    Every band is 20 points wide (step = 10 * n_decks).  The key threshold
    is 80 points (40 * n_decks): attackers scoring ≥ 80 take over as
    defenders.  The bottom-deck multiplier can push totals above 200.
    """
    threshold = 40 * n_decks  # = 80 for n=2; attackers need this many to win
    step = 10 * n_decks       # = 20 for n=2; each skip requires this many extra

    if attacking_points < threshold:
        steps = (threshold - attacking_points + step - 1) // step
        return ("defending", steps)
    else:
        # Cap at 3 per the table above (140+ is the top band); the bottom
        # multiplier can push totals far higher and must not over-promote.
        steps = min(3, (attacking_points - threshold) // step)
        return ("attacking", steps)
