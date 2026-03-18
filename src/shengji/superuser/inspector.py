"""Superuser inspector — read-only game state inspection and validation.

All functions here are pure (no side effects) and operate directly on a
GameState.  They are safe to call at any time during a game session.
"""
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from shengji.models.card import Rank, Suit
from shengji.models.deck import HAND_SIZE, NUM_DECKS
from shengji.models.game_state import GamePhase

if TYPE_CHECKING:
    from shengji.models.card import Card
    from shengji.models.game_state import GameState

# Maximum times any single card may appear across the entire 2-deck set.
_MAX_CARD_COPIES = NUM_DECKS  # 2

# Total cards in the game (2 decks × 54 cards).
_TOTAL_CARDS = 108

# Phases where trump context must be set.
_TRUMP_REQUIRED_PHASES = {
    GamePhase.BOTTOM_EXCHANGE,
    GamePhase.FRIEND_DECLARATION,
    GamePhase.PLAYING,
    GamePhase.SCORING,
    GamePhase.ROUND_OVER,
}

# Phases where we skip the total-card-count check (no cards in play yet).
_SKIP_CARD_COUNT_PHASES = {GamePhase.WAITING}


def get_full_state(state: "GameState") -> dict:
    """Return a complete view of the game state with all hands visible."""
    return state.to_superuser_view()


def _all_cards_in_play(state: "GameState") -> list["Card"]:
    """Collect every card that the state currently tracks."""
    cards: list["Card"] = []
    for p in state.players:
        cards.extend(p.hand)
    cards.extend(state.bottom_deck)
    cards.extend(state.draw_pile)
    for tricks in state.tricks_won.values():
        for trick in tricks:
            cards.extend(trick)
    # Also count cards in the current (incomplete) trick
    for _, play in state.current_trick:
        cards.extend(play)
    return cards


def validate_state(state: "GameState") -> list[str]:
    """Inspect *state* and return a list of violation strings.

    An empty list means the state looks consistent.  Violations are
    informational — the superuser may intentionally create edge cases.

    Checks performed
    ----------------
    1. Total card count (skipped in WAITING phase).
    2. No card appears more than NUM_DECKS (2) times.
    3. trump_context is set in phases that require it.
    4. No player's hand exceeds HAND_SIZE.
    5. round_leader_id and current_turn_id (in PLAYING) refer to real players.
    6. attacking_points is non-negative.
    """
    violations: list[str] = []
    player_ids = {p.id for p in state.players}

    # ------------------------------------------------------------------ #
    # 1. Total card count
    # ------------------------------------------------------------------ #
    if state.phase not in _SKIP_CARD_COUNT_PHASES:
        all_cards = _all_cards_in_play(state)
        total = len(all_cards)
        if total != _TOTAL_CARDS:
            violations.append(
                f"Total card count is {total}, expected {_TOTAL_CARDS}."
            )

    # ------------------------------------------------------------------ #
    # 2. Duplicate card check
    # ------------------------------------------------------------------ #
    if state.phase not in _SKIP_CARD_COUNT_PHASES:
        all_cards = _all_cards_in_play(state)
        counts = Counter((c.suit, c.rank) for c in all_cards)
        for (suit, rank), n in counts.items():
            if n > _MAX_CARD_COPIES:
                violations.append(
                    f"Card {rank.value} of {suit.value} appears {n} times "
                    f"(maximum is {_MAX_CARD_COPIES})."
                )

    # ------------------------------------------------------------------ #
    # 3. Trump context required in certain phases
    # ------------------------------------------------------------------ #
    if state.phase in _TRUMP_REQUIRED_PHASES and state.trump_context is None:
        violations.append(
            f"Phase {state.phase.value!r} requires trump_context to be set."
        )

    # ------------------------------------------------------------------ #
    # 4. Hand size limits
    # ------------------------------------------------------------------ #
    for p in state.players:
        if len(p.hand) > HAND_SIZE:
            violations.append(
                f"Player {p.id!r} has {len(p.hand)} cards "
                f"(maximum hand size is {HAND_SIZE})."
            )

    # ------------------------------------------------------------------ #
    # 5. Leader / turn id validity
    # ------------------------------------------------------------------ #
    if state.round_leader_id and state.round_leader_id not in player_ids:
        violations.append(
            f"round_leader_id {state.round_leader_id!r} is not a known player."
        )

    if state.phase == GamePhase.PLAYING:
        if state.current_turn_id not in player_ids:
            violations.append(
                f"current_turn_id {state.current_turn_id!r} is not a known player."
            )

    # ------------------------------------------------------------------ #
    # 6. Points non-negative
    # ------------------------------------------------------------------ #
    if state.attacking_points < 0:
        violations.append(
            f"attacking_points is {state.attacking_points} (must be ≥ 0)."
        )

    return violations
