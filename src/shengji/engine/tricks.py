"""Trick resolution utilities.

This module is intentionally decoupled from GameEngine so it can be tested
in isolation.  The engine calls into these helpers when validating and
resolving plays.

Public API
----------
get_legal_plays(hand, led_format, led_suit, ctx)
    What a follower is allowed (and required) to play given their hand and
    the led trick format.

validate_throw(throw_cards, thrower_hand, all_hands, ctx)
    Check whether a throw lead is legal (every component must be the highest
    remaining card of its suit in the hands of non-throwing players).

resolve_trick_winner(trick, led_suit, ctx)
    Given a list of (player_id, cards) plays, return the player_id that
    wins the trick.
"""
from __future__ import annotations

from collections import defaultdict

from shengji.models.card import Card
from shengji.models.groups import (
    Single,
    IdenticalGroup,
    Tractor,
    Throw,
    TrickFormat,
    classify_play,
    find_tractors,
)
from shengji.models.trump import TrumpContext


# ---------------------------------------------------------------------------
# get_legal_plays
# ---------------------------------------------------------------------------

def get_legal_plays(
    hand: list[Card],
    led_format: TrickFormat,
    led_suit: str,
    ctx: TrumpContext,
) -> list[list[Card]]:
    """Return all legal responses for a follower.

    A follower MUST match the led format to the best of their ability:
      1. Play an exact match (same format, same suit) if possible.
      2. Otherwise contribute as many suited cards as possible and fill the
         rest with any cards.

    The function returns a list of valid plays (each play is a list of
    Card objects).  In practice most hands have only one legal response
    (the best available match), but the list structure supports future UI
    hint expansion.

    Parameters
    ----------
    hand:       The follower's current hand.
    led_format: The TrickFormat of the lead (from classify_play).
    led_suit:   The effective suit of the lead (from ctx.effective_suit on the
                led cards).
    ctx:        The current TrumpContext.
    """
    n_cards = _format_card_count(led_format)
    suited = [c for c in hand if ctx.effective_suit(c) == led_suit]
    non_suited = [c for c in hand if ctx.effective_suit(c) != led_suit]

    if not suited:
        # No suited cards — can play anything
        return [_pick_any(hand, n_cards)]

    if len(suited) >= n_cards:
        # Enough suited cards to potentially match the format exactly
        best = _best_suited_response(suited, led_format, ctx)
        return [best]
    else:
        # Not enough suited cards — use all suited, fill remainder with anything
        remainder = n_cards - len(suited)
        fill = _pick_any(non_suited, remainder)
        return [suited + fill]


def _format_card_count(fmt: TrickFormat) -> int:
    """Total number of cards in a format."""
    if isinstance(fmt, Single):
        return 1
    if isinstance(fmt, IdenticalGroup):
        return fmt.count
    if isinstance(fmt, Tractor):
        return fmt.multiplicity * fmt.length
    if isinstance(fmt, Throw):
        return sum(_format_card_count(c) for c in fmt.components)
    raise TypeError(f"Unknown format type: {type(fmt)}")


def _pick_any(cards: list[Card], n: int) -> list[Card]:
    """Pick exactly *n* cards from *cards* (arbitrary order)."""
    return list(cards[:n])


def _best_suited_response(
    suited: list[Card],
    led_format: TrickFormat,
    ctx: TrumpContext,
) -> list[Card]:
    """Try to match the led format using only *suited* cards.

    Priority:
      Tractor > IdenticalGroup (pair/triple) > single cards

    If the exact format cannot be matched, degrade gracefully:
      - For a Tractor lead: match as many tractor pairs as possible, then
        pairs, then singles.
      - For an IdenticalGroup lead: match a group of equal or lesser size,
        then singles.
      - For a Single lead: play any one suited card.

    Returns exactly as many cards as the format requires.
    """
    n = _format_card_count(led_format)

    if isinstance(led_format, Single):
        return [suited[0]]

    if isinstance(led_format, IdenticalGroup):
        return _match_group(suited, led_format.count, ctx)

    if isinstance(led_format, Tractor):
        return _match_tractor(suited, led_format, ctx)

    if isinstance(led_format, Throw):
        # For a throw, try to match each component in priority order
        result: list[Card] = []
        remaining = list(suited)
        for component in sorted(
            led_format.components,
            key=lambda f: -_format_card_count(f),  # largest first
        ):
            needed = _format_card_count(component)
            if len(remaining) >= needed:
                matched = _best_suited_response(remaining, component, ctx)
                result.extend(matched)
                for c in matched:
                    remaining.remove(c)
            else:
                result.extend(remaining)
                remaining = []
                break
        # Fill remaining slots from suited (shouldn't happen but guard)
        result.extend(remaining[: n - len(result)])
        return result[:n]

    return suited[:n]


def _match_group(suited: list[Card], count: int, ctx: TrumpContext) -> list[Card]:
    """Match an IdenticalGroup of *count* cards from *suited*."""
    # Group by card_order position (same position = same tier/rank)
    groups: dict[tuple, list[Card]] = defaultdict(list)
    for c in suited:
        groups[ctx.card_order(c)].append(c)

    # Find the largest group >= count
    best = sorted(
        [(k, v) for k, v in groups.items() if len(v) >= count],
        key=lambda kv: kv[0],  # highest key = strongest
        reverse=True,
    )
    if best:
        return best[0][1][:count]

    # No single group of sufficient size — find largest group then fill
    all_groups = sorted(groups.values(), key=len, reverse=True)
    result: list[Card] = []
    for g in all_groups:
        if len(result) >= count:
            break
        take = min(len(g), count - len(result))
        result.extend(g[:take])
    return result[:count]


def _match_tractor(suited: list[Card], led: Tractor, ctx: TrumpContext) -> list[Card]:
    """Match a Tractor from *suited* cards, degrading gracefully."""
    needed = led.multiplicity * led.length
    tractors = find_tractors(suited, ctx)

    # Prefer a tractor of the required multiplicity and length
    exact = [t for t in tractors if len(t) == needed]
    if exact:
        return exact[0]

    # Degrade: use any available tractor pairs
    result: list[Card] = []
    remaining = list(suited)
    for t in sorted(tractors, key=len, reverse=True):
        if len(result) >= needed:
            break
        take = min(len(t), needed - len(result))
        result.extend(t[:take])
        for c in t[:take]:
            remaining.remove(c)

    # Fill remaining with suited pairs, then singles
    if len(result) < needed:
        result.extend(_match_group(remaining, needed - len(result), ctx))

    return result[:needed]


# ---------------------------------------------------------------------------
# validate_throw
# ---------------------------------------------------------------------------

def validate_throw(
    throw_cards: list[Card],
    thrower_id: str,
    all_hands: dict[str, list[Card]],
    ctx: TrumpContext,
) -> bool:
    """Return True if the throw is valid.

    A throw is valid iff every component of the throw is the highest
    remaining card of its suit among the other players' hands.  If any
    other player holds a non-trump card of the same suit that beats a
    throw component, the throw is invalid.

    Parameters
    ----------
    throw_cards:
        The cards the leader is throwing.
    thrower_id:
        The leading player's id.
    all_hands:
        Dict of player_id → hand (includes all players).
    ctx:
        Current TrumpContext.
    """
    throw_fmt = classify_play(throw_cards, ctx)
    if not isinstance(throw_fmt, Throw):
        # Not actually a throw — single/pair/tractor leads are always legal
        return True

    # Build opponent hands
    opponent_cards: list[Card] = []
    for pid, hand in all_hands.items():
        if pid != thrower_id:
            opponent_cards.extend(hand)

    # Check each component of the throw
    for component in throw_fmt.components:
        component_cards = _extract_component_cards(throw_cards, component, ctx)
        if not component_cards:
            continue
        component_suit = ctx.effective_suit(component_cards[0])
        component_strength = ctx.card_order(component_cards[0])

        # Find opponent cards of the same suit
        opp_suited = [
            c for c in opponent_cards
            if ctx.effective_suit(c) == component_suit
        ]

        for opp_card in opp_suited:
            if ctx.card_order(opp_card) > component_strength:
                # An opponent can beat this component with a non-trump suited card
                return False

    return True


def _extract_component_cards(
    all_throw_cards: list[Card],
    component: TrickFormat,
    ctx: TrumpContext,
) -> list[Card]:
    """Extract the cards belonging to one component of a throw.

    Returns up to _format_card_count(component) cards from *all_throw_cards*
    that match the component's tier, sorted weakest first.
    """
    n = _format_card_count(component)
    # Group by card_order, sorted ascending
    by_pos: dict[tuple, list[Card]] = defaultdict(list)
    for c in all_throw_cards:
        by_pos[ctx.card_order(c)].append(c)

    sorted_pos = sorted(by_pos.keys())
    result: list[Card] = []
    for pos in sorted_pos:
        result.extend(by_pos[pos])
        if len(result) >= n:
            break
    return result[:n]


# ---------------------------------------------------------------------------
# resolve_trick_winner
# ---------------------------------------------------------------------------

def resolve_trick_winner(
    trick: list[tuple[str, list[Card]]],
    led_suit: str,
    ctx: TrumpContext,
) -> str:
    """Return the player_id that wins the trick.

    Rules
    -----
    1. Only plays that match the led suit (or trump) are eligible to win.
       Off-suit plays that don't follow suit can never win.
    2. Among eligible plays, trump beats non-trump.
    3. Among plays of the same effective suit, the highest card (by
       card_order) wins.
    4. The strongest card is the highest card_order value in the play.
       For multi-card plays (pairs, tractors) the winning "value" is the
       single strongest card in that play.
    5. On a tie (equal-value cards), the first player to play wins.

    Parameters
    ----------
    trick:
        Ordered list of (player_id, cards_played) — index 0 is the leader.
    led_suit:
        The effective suit of the lead (from ctx.effective_suit on the leader's cards).
    ctx:
        Current TrumpContext.
    """
    if not trick:
        raise ValueError("Cannot resolve an empty trick.")

    best_player_id = trick[0][0]
    best_strength = _play_strength(trick[0][1], led_suit, ctx)

    for player_id, cards in trick[1:]:
        strength = _play_strength(cards, led_suit, ctx)
        if strength is None:
            continue  # off-suit, ineligible
        if best_strength is None or strength > best_strength:
            best_player_id = player_id
            best_strength = strength

    return best_player_id


def _play_strength(
    cards: list[Card],
    led_suit: str,
    ctx: TrumpContext,
) -> tuple[int, int] | None:
    """Return the strength key of a play, or None if ineligible.

    A play is eligible if any card in it matches the led_suit or is trump.
    Strength is the highest card_order in the play.
    """
    play_suit = ctx.effective_suit(cards[0])  # all cards in a play share the led suit if following correctly
    if play_suit != led_suit and play_suit != "trump" and led_suit != "trump":
        # Off-suit and not trump — ineligible
        return None

    # Strength = highest card_order in the play
    return max(ctx.card_order(c) for c in cards)
