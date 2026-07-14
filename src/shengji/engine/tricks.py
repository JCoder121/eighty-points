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

from shengji.models.card import Card
from shengji.models.groups import (
    Single,
    IdenticalGroup,
    Tractor,
    Throw,
    TrickFormat,
    classify_play,
    find_tractors,
    identity_groups,
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
    """Match an IdenticalGroup of *count* cards from *suited*.

    Groups are formed by exact card identity — same-strength cards of
    different suits (off-suit trump ranks) are NOT interchangeable (#50).
    """
    groups = identity_groups(suited)

    # Find the strongest group >= count
    best = sorted(
        [(ctx.card_order(v[0]), v) for v in groups.values() if len(v) >= count],
        key=lambda kv: kv[0],
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
# is_valid_follow
# ---------------------------------------------------------------------------

def _multiset_eq(a: list[Card], b: list[Card]) -> bool:
    """Return True if two card lists are equal as multisets."""
    return sorted(repr(c) for c in a) == sorted(repr(c) for c in b)


def is_valid_follow(
    proposed: list[Card],
    hand: list[Card],
    led_format: TrickFormat,
    led_suit: str,
    ctx: TrumpContext,
) -> bool:
    """Return True if *proposed* is a legal follow.

    Validates by checking invariants directly rather than comparing to a single
    'best' option from get_legal_plays.  This allows any valid follow
    (e.g., any suited single, any 2 suited singles when no pair is available).

    Rules
    -----
    1. Must play exactly as many cards as the led format requires.
    2. Must play as many suited cards as possible (up to the required count).
    3. If not enough suited cards, must play ALL suited cards (fill freely).
    4. If enough suited cards, all proposed cards must be suited, and:
       - Single: any one suited card is valid.
       - IdenticalGroup(k): if hand has a group of k, proposed must too;
         otherwise any k suited cards are valid.
       - Tractor / Throw: fall back to get_legal_plays comparison (complex
         ordering rules still apply).
    """
    n = _format_card_count(led_format)
    if len(proposed) != n:
        return False

    # Verify all proposed cards are in hand
    hand_copy = list(hand)
    for c in proposed:
        if c not in hand_copy:
            return False
        hand_copy.remove(c)

    suited_in_hand = [c for c in hand if ctx.effective_suit(c) == led_suit]
    suited_in_proposed = [c for c in proposed if ctx.effective_suit(c) == led_suit]

    must_suited = min(len(suited_in_hand), n)

    # Must play as many suited cards as possible
    if len(suited_in_proposed) < must_suited:
        return False

    # Not enough suited cards — must play ALL suited, fill rest freely
    if len(suited_in_hand) < n:
        return _multiset_eq(suited_in_proposed, suited_in_hand)

    # Enough suited cards — all proposed must be suited
    if len(suited_in_proposed) != n:
        return False

    # Format-specific checks
    if isinstance(led_format, Single):
        return True  # any one suited card is valid

    if isinstance(led_format, IdenticalGroup):
        k = led_format.count
        # Check if hand has a group of k truly identical cards (#50)
        hand_has_group = any(
            len(v) >= k for v in identity_groups(suited_in_hand).values()
        )

        if not hand_has_group:
            # No group of k available — any k suited cards are valid
            return True

        # Hand has a qualifying group — proposed must include one too
        return any(
            len(v) >= k for v in identity_groups(suited_in_proposed).values()
        )

    if isinstance(led_format, Tractor):
        return _is_valid_tractor_follow(suited_in_proposed, suited_in_hand, led_format, ctx)

    # Throw — validate structural obligations directly
    if isinstance(led_format, Throw):
        return _is_valid_throw_follow(suited_in_proposed, suited_in_hand, led_format, ctx)

    return False


def _is_valid_tractor_follow(
    proposed_suited: list[Card],
    hand_suited: list[Card],
    led: Tractor,
    ctx: TrumpContext,
) -> bool:
    """Validate a tractor follow.

    The player must include all required (tractor + pair) cards from their
    suited hand; any remaining slots may be filled with any suited singles.

    Steps:
      1. Greedily claim tractor cards from the hand (largest tractor first).
      2. Greedily claim pairs from what remains.
      3. Verify the proposed play contains all claimed required cards.
      4. Any leftover proposed cards (the singles) are accepted freely.
    """
    needed = led.multiplicity * led.length

    # The obligation is STRUCTURAL, not card-specific: the hand determines how
    # many tractor cards and how many additional pair cards must appear in the
    # play, but WHICH tractor/pairs to use is the player's choice.
    req_tractor, req_paired = _tractor_pair_capacity(hand_suited, needed, ctx)
    got_tractor, got_paired = _tractor_pair_capacity(proposed_suited, needed, ctx)

    if got_tractor < req_tractor:
        return False
    # Tractor cards are themselves paired, so compare total paired structure.
    return got_tractor + got_paired >= req_tractor + req_paired


def _tractor_pair_capacity(
    cards: list[Card], needed: int, ctx: TrumpContext
) -> tuple[int, int]:
    """Return (tractor_cards, additional_pair_cards) *cards* can contribute
    toward a tractor follow of *needed* total cards.

    Greedy, largest tractor first (mirrors get_legal_plays/_match_tractor):
    claim up to *needed* cards from tractors, then count remaining paired
    cards (capped by the slots still open).
    """
    remaining = list(cards)
    tractor_cards = 0
    for t in sorted(find_tractors(remaining, ctx), key=len, reverse=True):
        if tractor_cards >= needed:
            break
        take = min(len(t), needed - tractor_cards)
        # Only whole pairs count as tractor structure
        take -= take % 2
        tractor_cards += take
        for c in t[:take]:
            remaining.remove(c)

    paired = sum(len(g) - len(g) % 2 for g in identity_groups(remaining).values())
    paired = min(paired, needed - tractor_cards)
    paired -= paired % 2
    return tractor_cards, paired


def _is_valid_throw_follow(
    proposed_suited: list[Card],
    hand_suited: list[Card],
    led: Throw,
    ctx: TrumpContext,
) -> bool:
    """Validate a throw follow using structural obligations.

    For each component of the throw (processed largest-first), determine what
    structure the hand obliges the follower to play, then verify the proposed
    play contains matching structures.  Any remaining slots are free-choice
    suited cards.

    Structural obligations (not card-specific) are used for IdenticalGroup
    components so that the player can choose *which* pair/group to play.
    Tractor components use card-specific obligations (same as tractor follow)
    since multiple tractors in one suit is extremely rare.
    """
    hand_rem = list(hand_suited)

    # Card-specific required cards (for tractor components)
    required_cards: list[Card] = []
    # Structural obligations: list of group sizes the proposed must contain
    group_obligations: list[int] = []

    for comp in sorted(led.components, key=lambda f: -_format_card_count(f)):
        comp_n = _format_card_count(comp)

        if isinstance(comp, Tractor):
            # Use tractor follow logic: greedily claim tractors then pairs
            remaining = list(hand_rem)
            comp_required: list[Card] = []

            for t in sorted(find_tractors(remaining, ctx), key=len, reverse=True):
                if len(comp_required) >= comp_n:
                    break
                take = min(len(t), comp_n - len(comp_required))
                comp_required.extend(t[:take])
                for c in t[:take]:
                    remaining.remove(c)

            if len(comp_required) < comp_n:
                id_groups = sorted(
                    identity_groups(remaining).values(),
                    key=lambda g: ctx.card_order(g[0]),
                    reverse=True,
                )
                for group in id_groups:
                    if len(comp_required) >= comp_n:
                        break
                    if len(group) >= 2:
                        take = min(len(group), comp_n - len(comp_required))
                        comp_required.extend(group[:take])
                        for c in group[:take]:
                            remaining.remove(c)

            required_cards.extend(comp_required)
            hand_rem = remaining

        elif isinstance(comp, IdenticalGroup):
            k = comp.count
            id_groups = sorted(
                identity_groups(hand_rem).values(),
                key=lambda g: ctx.card_order(g[0]),
                reverse=True,
            )
            for group in id_groups:
                if len(group) >= k:
                    group_obligations.append(k)
                    for c in group[:k]:
                        hand_rem.remove(c)
                    break

        # Single: no structural obligation

    # --- Validate proposed ---

    prop_rem = list(proposed_suited)

    # Check card-specific requirements (tractor components)
    for req in required_cards:
        if req not in prop_rem:
            return False
        prop_rem.remove(req)

    # Check structural requirements (group components) — largest first
    for k in sorted(group_obligations, reverse=True):
        found = False
        for group in sorted(
            identity_groups(prop_rem).values(),
            key=lambda g: ctx.card_order(g[0]),
            reverse=True,
        ):
            if len(group) >= k:
                for c in group[:k]:
                    prop_rem.remove(c)
                found = True
                break
        if not found:
            return False

    # Remaining proposed cards are free-choice suited cards — always valid
    return True


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

    A throw is valid iff, for every component of the throw, no single
    opponent can beat that component using cards of the same suit in a
    matching format:

    - Single component:            no opponent has a higher single in the
                                   same suit.
    - IdenticalGroup(k) component: no single opponent has k or more cards
                                   at the same position with higher rank.
    - Tractor component:           no single opponent has a tractor of the
                                   required size with higher rank.

    Key rule for pairs: the thrower holding A♦ alongside K♦K♦ guarantees
    no opponent can have two Aces (only one remains), so K♦K♦ cannot be
    beaten by a pair — making the throw valid even though opponents might
    hold one A♦.

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
        return True

    # Assign each component its actual cards from the throw (format-aware).
    assigned = _assign_throw_components(throw_cards, throw_fmt.components, ctx)

    # For each component, check if any SINGLE opponent can beat it.
    for component, comp_cards in assigned:
        if not comp_cards:
            continue
        comp_suit = ctx.effective_suit(comp_cards[0])
        comp_strength = max(ctx.card_order(c) for c in comp_cards)

        for pid, hand in all_hands.items():
            if pid == thrower_id:
                continue
            opp_suited = [c for c in hand if ctx.effective_suit(c) == comp_suit]
            if _single_opp_beats_component(component, comp_strength, opp_suited, ctx):
                return False

    return True


def _assign_throw_components(
    throw_cards: list[Card],
    components: list[TrickFormat],
    ctx: TrumpContext,
) -> list[tuple[TrickFormat, list[Card]]]:
    """Map each throw component to its actual cards.

    Processes in format-priority order (Tractors → IdenticalGroups → Singles)
    so that larger groups get their cards before singles claim them.
    """
    remaining = list(throw_cards)
    result: list[tuple[TrickFormat, list[Card]]] = []

    # Pass 1: Tractors
    for comp in components:
        if isinstance(comp, Tractor):
            needed = comp.multiplicity * comp.length
            tractors = find_tractors(remaining, ctx)
            matched: list[Card] = []
            for t in tractors:
                if len(t) == needed:
                    matched = t
                    break
            result.append((comp, matched))
            for c in matched:
                remaining.remove(c)

    # Pass 2: IdenticalGroups — assign strongest identical group of sufficient size
    for comp in components:
        if isinstance(comp, IdenticalGroup):
            k = comp.count
            matched = []
            for group in sorted(
                identity_groups(remaining).values(),
                key=lambda g: ctx.card_order(g[0]),
                reverse=True,
            ):
                if len(group) >= k:
                    matched = group[:k]
                    break
            result.append((comp, matched))
            for c in matched:
                remaining.remove(c)

    # Pass 3: Singles — take one card each from whatever remains
    for comp in components:
        if isinstance(comp, Single):
            if remaining:
                result.append((comp, [remaining[0]]))
                remaining = remaining[1:]
            else:
                result.append((comp, []))

    return result


def _single_opp_beats_component(
    component: TrickFormat,
    comp_strength: tuple,
    opp_suited: list[Card],
    ctx: TrumpContext,
) -> bool:
    """Return True if a single opponent (opp_suited = their same-suit cards)
    can beat this throw component.

    - Single:         any card with higher card_order suffices.
    - IdenticalGroup: needs k cards at the same card_order, all higher.
    - Tractor:        needs a matching-size tractor with higher card_order.
    """
    if isinstance(component, Single):
        return any(ctx.card_order(c) > comp_strength for c in opp_suited)

    if isinstance(component, IdenticalGroup):
        # Opponent needs k truly IDENTICAL higher cards (#50): equal-strength
        # off-suit trump ranks of different suits do not form a beating group.
        k = component.count
        return any(
            len(v) >= k and ctx.card_order(v[0]) > comp_strength
            for v in identity_groups(opp_suited).values()
        )

    if isinstance(component, Tractor):
        needed = component.multiplicity * component.length
        for t in find_tractors(opp_suited, ctx):
            if len(t) >= needed and max(ctx.card_order(c) for c in t) > comp_strength:
                return True
        return False

    return False


# ---------------------------------------------------------------------------
# resolve_trick_winner
# ---------------------------------------------------------------------------

def _format_can_beat_lead(play_fmt: TrickFormat, led_fmt: TrickFormat) -> bool:
    """Return True if a play of play_fmt is eligible to beat a lead of led_fmt.

    A degraded follow (e.g., two singles played to follow a pair lead because
    the player had no pair) cannot win the trick regardless of card strength.
    Only a play that matches the led format — or a stronger format in trump —
    can win.

    Rules
    -----
    - Single lead:            any Single is eligible.
    - IdenticalGroup(k) lead: IdenticalGroup(>=k) or any Tractor is eligible.
    - Tractor(m, L) lead:     Tractor with multiplicity >= m and length >= L
                              is eligible; pairs and singles are not.
    - Throw lead:             play must match every component (pair for pair,
                              tractor for tractor, single for single).
    """
    if isinstance(led_fmt, Single):
        return isinstance(play_fmt, Single)
    if isinstance(led_fmt, IdenticalGroup):
        k = led_fmt.count
        if isinstance(play_fmt, IdenticalGroup):
            return play_fmt.count >= k
        if isinstance(play_fmt, Tractor):
            return True  # tractor contains pairs — can beat a pair lead
        return False  # Single or Throw cannot beat a pair/triple lead
    if isinstance(led_fmt, Tractor):
        if isinstance(play_fmt, Tractor):
            return (
                play_fmt.multiplicity >= led_fmt.multiplicity
                and play_fmt.length >= led_fmt.length
            )
        return False  # pairs and singles cannot beat a tractor lead
    # Throw lead — each led component must be matchable by a play component.
    if isinstance(led_fmt, Throw):
        if not isinstance(play_fmt, Throw):
            # Non-throw play: treat as a single component and check against
            # all led components.  Only works if throw has exactly 1 component.
            return (
                len(led_fmt.components) == 1
                and _format_can_beat_lead(play_fmt, led_fmt.components[0])
            )
        # Sort components largest-first so we match greedily.
        led_comps = sorted(
            led_fmt.components,
            key=lambda f: _format_card_count(f),
            reverse=True,
        )
        play_comps = sorted(
            play_fmt.components,
            key=lambda f: _format_card_count(f),
            reverse=True,
        )
        # Each led component must be matched by a play component.
        remaining = list(play_comps)
        for lc in led_comps:
            matched = False
            for i, pc in enumerate(remaining):
                if _format_can_beat_lead(pc, lc):
                    remaining.pop(i)
                    matched = True
                    break
            if not matched:
                return False
        return True
    return True


def resolve_trick_winner(
    trick: list[tuple[str, list[Card]]],
    led_suit: str,
    ctx: TrumpContext,
    led_format: TrickFormat | None = None,
) -> str:
    """Return the player_id that wins the trick.

    Rules
    -----
    1. Only plays in the led suit or trump are eligible to win.
       Off-suit plays can never win.
    2. A follower's play must match the led format (or a stronger format in
       the same suit / trump) to be eligible to win.  A degraded response
       (e.g., two singles played to follow a pair lead because the player
       had no pair) is ineligible to win even if the cards outrank the lead.
    3. Among eligible plays, trump beats non-trump.
    4. Among plays of the same effective suit, the highest card_order wins.
       For multi-card plays the winning value is the single strongest card.
    5. On a tie, the first player to play wins (leader wins ties).

    Parameters
    ----------
    trick:
        Ordered list of (player_id, cards_played) — index 0 is the leader.
    led_suit:
        Effective suit of the lead.
    ctx:
        Current TrumpContext.
    led_format:
        TrickFormat of the lead.  If omitted it is derived from the leader's
        cards via classify_play (backward-compatible with existing tests).
    """
    if not trick:
        raise ValueError("Cannot resolve an empty trick.")

    if led_format is None:
        led_format = classify_play(trick[0][1], ctx)

    best_player_id = trick[0][0]
    best_strength = _play_strength(trick[0][1], led_suit, led_format, ctx)

    for player_id, cards in trick[1:]:
        strength = _play_strength(cards, led_suit, led_format, ctx)
        if strength is None:
            continue  # ineligible (off-suit or degraded follow)
        if best_strength is None or strength > best_strength:
            best_player_id = player_id
            best_strength = strength

    return best_player_id


def _play_strength(
    cards: list[Card],
    led_suit: str,
    led_format: TrickFormat,
    ctx: TrumpContext,
) -> tuple[int, int] | None:
    """Return the strength key of a play, or None if ineligible to win.

    A play is ineligible if:
    - Its effective suit is neither the led suit nor trump, OR
    - Its classified format cannot beat the led format (degraded response).
    """
    play_suit = ctx.effective_suit(cards[0])
    if play_suit != led_suit and play_suit != "trump" and led_suit != "trump":
        return None  # off-suit, ineligible

    # Degraded responses (e.g., two singles following a pair lead) cannot win.
    play_fmt = classify_play(cards, ctx)
    if not _format_can_beat_lead(play_fmt, led_format):
        return None

    return max(ctx.card_order(c) for c in cards)
