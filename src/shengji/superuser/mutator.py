"""Superuser mutator — controlled state mutations for debugging.

Every mutation function:
  1. Applies the change directly to the GameState.
  2. Calls validate_state() and returns any violation strings as warnings.

Violations are non-fatal — the superuser may intentionally create edge
cases for testing purposes.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from shengji.models.game_state import GamePhase
from shengji.superuser.inspector import validate_state

if TYPE_CHECKING:
    from shengji.models.card import Card
    from shengji.models.game_state import GameState


def set_hand(
    state: "GameState", player_id: str, cards: list["Card"]
) -> list[str]:
    """Replace *player_id*'s hand with *cards*.

    Parameters
    ----------
    state:
        The game state to mutate.
    player_id:
        Must be a known player.
    cards:
        The new hand contents.  May be any length; the caller is responsible
        for maintaining a sensible total card count.

    Returns
    -------
    list[str]
        Validation warnings (empty = state looks consistent after mutation).

    Raises
    ------
    ValueError
        If *player_id* is not a known player.
    """
    player = next((p for p in state.players if p.id == player_id), None)
    if player is None:
        raise ValueError(f"Unknown player_id: {player_id!r}")
    player.hand = list(cards)
    return validate_state(state)


def set_bottom(state: "GameState", cards: list["Card"]) -> list[str]:
    """Replace the bottom deck with *cards*.

    Returns
    -------
    list[str]
        Validation warnings after mutation.
    """
    state.bottom_deck = list(cards)
    return validate_state(state)


def set_points(state: "GameState", attacking_points: int) -> list[str]:
    """Override the attacking points total.

    Parameters
    ----------
    attacking_points:
        The new attacking_points value.  May be any integer (superuser may
        want to set a value outside normal range for edge-case testing).

    Returns
    -------
    list[str]
        Validation warnings after mutation.
    """
    state.attacking_points = attacking_points
    return validate_state(state)


def force_phase(state: "GameState", phase: GamePhase) -> list[str]:
    """Force the game into *phase*, bypassing the normal transition graph.

    This directly sets ``state.phase`` without calling ``transition_to()``,
    so it can jump to any phase regardless of the current one.

    Returns
    -------
    list[str]
        Validation warnings after mutation.
    """
    state.phase = phase
    return validate_state(state)


def deal_specific_hands(
    state: "GameState",
    hands: dict[str, list["Card"]],
    bottom: list["Card"],
) -> list[str]:
    """Set up a fully deterministic card distribution.

    Replaces every player's hand and the bottom deck simultaneously, then
    transitions the phase to PLAYING (or leaves it as-is if already past
    WAITING so the caller can sequence phases manually).

    Parameters
    ----------
    hands:
        Mapping of player_id → card list.  All player IDs must be known.
    bottom:
        Cards to place in the bottom deck.

    Returns
    -------
    list[str]
        Validation warnings after mutation.

    Raises
    ------
    ValueError
        If any player_id in *hands* is not a known player.
    """
    player_map = {p.id: p for p in state.players}
    for pid, cards in hands.items():
        if pid not in player_map:
            raise ValueError(f"Unknown player_id in hands: {pid!r}")
        player_map[pid].hand = list(cards)

    state.bottom_deck = list(bottom)
    state.draw_pile = []  # all cards explicitly distributed
    state.tricks_won = {p.id: [] for p in state.players}
    state.current_trick = []

    return validate_state(state)
