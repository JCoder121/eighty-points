"""An independent lead/follow legality oracle, re-derived from ``docs/RULES.md``.

Nothing in this module reads the engine's decision logic.  Card strength (R6),
effective suit (R7), tractor adjacency (R8), play classification (R37), lead
legality (R38-R41) and follow legality (R42-R47) are re-implemented from the
spec text so that ``test_oracle.py`` can diff two genuinely separate opinions
about the same play.

Deliberate structural differences from ``models/groups.py`` + ``engine/tricks.py``:

* Adjacency is expressed as a **position ladder** for the trump hierarchy
  ("which strength positions exist in this trump context, in order") rather
  than as a ``tier + 1`` step.  That is exactly what **D18** asks for, and it
  makes the pre-D18 engine rule expressible as the same ladder with the
  trump-suit rank rung left in place even in no-trump — see ``legacy=True``.
* Tractors are found by taking **connected components of an adjacency graph**
  over the paired strength positions, not by a linear scan with a running
  buffer.
* A throw's components carry **their own cards** from the moment they are
  built, so there is no second "re-find the cards for this component" pass
  (the engine's ``_assign_throw_components``, the origin of suspected bug 7).
* Follow obligations are checked by **existence of a satisfying assignment**
  (backtracking over the proposal's identity groups) instead of a
  strongest-first greedy match, so a proposal is accepted whenever *some*
  legal reading of it works.

Post-ruling spec, not current engine
------------------------------------
The oracle implements the rules **as ruled** in the 2026-07-29 interview.  Two
of those rulings are not implemented in the engine yet, so the oracle is
expected to disagree with it in exactly two ways:

* **D16** — a throw lead whose components span more than one effective suit is
  an illegal lead.  The engine accepts it.
* **D18** — adjacency is "no *existing* strength position lies strictly between
  the two cards", so in no-trump a trump-rank pair and a Small-Joker pair form
  a tractor.  The engine steps one tier at a time over the (empty) trump-suit
  rank tier and calls them a throw.

``legacy=True`` on every entry point switches the oracle to the pre-D18
adjacency ladder.  ``test_oracle.py`` uses that to *classify* a disagreement:
if the legacy oracle agrees with the engine, the disagreement is the scheduled
D18 change; otherwise it is a finding.

Known limitation deliberately reproduced
----------------------------------------
``Known limitations`` item 1 in the spec: a circular-wrap run of 3+ positions
(K♥K♥ A♥A♥ 3♥3♥ at trump rank 2) is *not* one tractor.  The wrap edge is only
added when the two wrapped positions are the only paired tier-0 positions,
which is the documented "2-position wraps work" behaviour.  The engine is the
reference here per the campaign brief.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Iterable, Optional, Sequence, Union

from shengji.models.card import Card, Rank, Suit
from shengji.models.trump import TrumpContext

# R6: "2,3,4,5,6,7,8,9,10,J,Q,K,A", aces high.  Transcribed from the spec, not
# imported from models.card, so a change there cannot silently move the oracle.
SPEC_RANK_SEQUENCE: list[Rank] = [
    Rank.TWO, Rank.THREE, Rank.FOUR, Rank.FIVE, Rank.SIX, Rank.SEVEN,
    Rank.EIGHT, Rank.NINE, Rank.TEN, Rank.JACK, Rank.QUEEN, Rank.KING, Rank.ACE,
]

#: Number of non-trump-rank ranks — the size of every tier-0/tier-1 ladder.
LADDER_LEN = len(SPEC_RANK_SEQUENCE) - 1  # 12

TRUMP = "trump"


# ---------------------------------------------------------------------------
# R6 — card strength, R7 — effective suit
# ---------------------------------------------------------------------------

def strength(card: Card, ctx: TrumpContext) -> tuple[int, int]:
    """The ``(tier, position)`` key of R6.  Higher is stronger."""
    if card.rank == Rank.BIG_JOKER:
        return (5, 0)
    if card.rank == Rank.SMALL_JOKER:
        return (4, 0)
    if card.rank == ctx.trump_rank:
        if ctx.trump_suit is not None and card.suit == ctx.trump_suit:
            return (3, 0)
        return (2, 0)
    ladder = [r for r in SPEC_RANK_SEQUENCE if r != ctx.trump_rank]
    position = ladder.index(card.rank)
    if ctx.trump_suit is not None and card.suit == ctx.trump_suit:
        return (1, position)
    return (0, position)


def effective_suit(card: Card, ctx: TrumpContext) -> str:
    """R7.  Jokers, *every* trump-rank card, and trump-suit cards are "trump"."""
    if card.suit == Suit.JOKER:
        return TRUMP
    if card.rank == ctx.trump_rank:
        return TRUMP
    if ctx.trump_suit is not None and card.suit == ctx.trump_suit:
        return TRUMP
    return card.suit.value


# ---------------------------------------------------------------------------
# R8 — adjacency
# ---------------------------------------------------------------------------

def trump_ladder(ctx: TrumpContext, *, legacy: bool = False) -> list[tuple[int, int]]:
    """The strength positions of the trump hierarchy, weakest first.

    ``legacy=False`` (D18): only positions that can actually be occupied in this
    trump context are rungs, so in no-trump the off-suit trump-rank position sits
    directly below the Small Joker.

    ``legacy=True``: the trump-suit rank rung is kept even in no-trump, where no
    card can occupy it — the phantom rung is what keeps the pre-D18 engine from
    seeing 2♥2♥ + SJ SJ as a tractor.
    """
    if legacy or ctx.trump_suit is not None:
        return [(1, i) for i in range(LADDER_LEN)] + [(2, 0), (3, 0), (4, 0), (5, 0)]
    return [(2, 0), (4, 0), (5, 0)]


def positions_adjacent(
    pos_a: tuple[int, int],
    pos_b: tuple[int, int],
    ctx: TrumpContext,
    *,
    legacy: bool = False,
) -> bool:
    """R8, excluding the tier-0 circular wrap (handled in :func:`find_tractors`).

    Two positions are adjacent iff they are neighbouring rungs of the same
    ladder: the per-suit tier-0 ladder, or the trump ladder above.
    """
    lo, hi = sorted([pos_a, pos_b])
    if lo == hi:
        return False
    if lo[0] == hi[0]:
        # Same tier: consecutive positions.  (Tier 0 and tier 1 are separate
        # ladders — R8: "Tier 0 and tier 1 are never adjacent".)
        return hi[1] == lo[1] + 1
    ladder = trump_ladder(ctx, legacy=legacy)
    if lo in ladder and hi in ladder:
        return ladder.index(hi) == ladder.index(lo) + 1
    return False


# ---------------------------------------------------------------------------
# Identity grouping (R37: a group is copies of one identity, #50)
# ---------------------------------------------------------------------------

def identity_groups(cards: Iterable[Card]) -> dict[tuple[Suit, Rank], list[Card]]:
    groups: dict[tuple[Suit, Rank], list[Card]] = defaultdict(list)
    for card in cards:
        groups[(card.suit, card.rank)].append(card)
    return dict(groups)


def has_group(cards: Iterable[Card], k: int) -> bool:
    return any(len(g) >= k for g in identity_groups(cards).values())


# ---------------------------------------------------------------------------
# Tractors (R8 + R37)
# ---------------------------------------------------------------------------

def _paired_positions(
    cards: Sequence[Card], ctx: TrumpContext
) -> dict[tuple[int, int], list[Card]]:
    """Strength positions holding a real (identical) pair, with those cards.

    A position may hold several identities — all off-suit trump-rank cards share
    one position — but a pair must come from a single identity (#50), so each
    position is represented by its largest identity group.
    """
    by_position: dict[tuple[int, int], list[Card]] = defaultdict(list)
    for card in cards:
        by_position[strength(card, ctx)].append(card)

    paired: dict[tuple[int, int], list[Card]] = {}
    for position, at_position in by_position.items():
        largest = max(identity_groups(at_position).values(), key=len)
        if len(largest) >= 2:
            paired[position] = largest
    return paired


def find_tractors(
    cards: Sequence[Card],
    ctx: TrumpContext,
    *,
    legacy: bool = False,
    wrap_reference: Optional[Sequence[Card]] = None,
) -> list[list[Card]]:
    """Every maximal tractor in *cards* (R37: >= 2 pairs on consecutive positions).

    Built as connected components of the adjacency graph over paired positions.
    Since adjacency is a path relation, each component is a run.

    ``wrap_reference`` decides *availability of the circular wrap* from a card
    set other than *cards*.  R46/R47 claim cards from a hand in several greedy
    steps; without this, removing the cards claimed in step 1 can leave a set
    whose only tier-0 pairs are the two wrapped ends, conjuring a wrap tractor
    that the hand as a whole never had (``Known limitations`` 1 says the engine
    only ever sees the wrap when nothing else is paired in the suit).  Callers
    doing multi-step claims pass the original hand here so the wrap stays a
    property of the hand rather than of the leftovers.

    D22: a tractor lives inside ONE effective suit.  Tier-0 positions do not
    encode the suit, so without this partition two pairs in different suits at
    consecutive rank positions would chain (5♥5♥ + 6♦6♦ — the F1 bug).  All
    trump cards share the effective suit "trump" and stay one bucket.
    """
    buckets: dict[str, list[Card]] = defaultdict(list)
    for card in cards:
        buckets[effective_suit(card, ctx)].append(card)
    out: list[list[Card]] = []
    for suit_key, bucket in buckets.items():
        ref = (
            None
            if wrap_reference is None
            else [c for c in wrap_reference if effective_suit(c, ctx) == suit_key]
        )
        out.extend(
            _find_tractors_one_suit(bucket, ctx, legacy=legacy, wrap_reference=ref)
        )
    out.sort(key=lambda run: strength(run[0], ctx))
    return out


def _find_tractors_one_suit(
    cards: Sequence[Card],
    ctx: TrumpContext,
    *,
    legacy: bool = False,
    wrap_reference: Optional[Sequence[Card]] = None,
) -> list[list[Card]]:
    paired = _paired_positions(cards, ctx)
    positions = sorted(paired)
    if len(positions) < 2:
        return []

    neighbours: dict[tuple[int, int], set[tuple[int, int]]] = {p: set() for p in positions}
    for a, b in combinations(positions, 2):
        if positions_adjacent(a, b, ctx, legacy=legacy):
            neighbours[a].add(b)
            neighbours[b].add(a)

    # R8's tier-0 circular wrap, restricted to the case the engine actually
    # detects (Known limitations 1): the two wrapped positions must be the only
    # paired tier-0 positions, otherwise a 3+-position wrap run would form.
    reference = paired if wrap_reference is None else _paired_positions(wrap_reference, ctx)
    tier0 = sorted(p for p in reference if p[0] == 0)
    wrap = [(0, 0), (0, LADDER_LEN - 1)]
    if tier0 == wrap and all(p in paired for p in wrap):
        neighbours[wrap[0]].add(wrap[1])
        neighbours[wrap[1]].add(wrap[0])

    seen: set[tuple[int, int]] = set()
    tractors: list[list[Card]] = []
    for start in positions:
        if start in seen:
            continue
        stack = [start]
        component: list[tuple[int, int]] = []
        seen.add(start)
        while stack:
            node = stack.pop()
            component.append(node)
            for nxt in neighbours[node]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        if len(component) < 2:
            continue
        component.sort()
        multiplicity = min(len(paired[p]) for p in component)
        run: list[Card] = []
        for position in component:
            run.extend(paired[position][:multiplicity])
        tractors.append(run)

    tractors.sort(key=lambda run: strength(run[0], ctx))
    return tractors


# ---------------------------------------------------------------------------
# R37 — formats
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OSingle:
    pass


@dataclass(frozen=True)
class OGroup:
    count: int


@dataclass(frozen=True)
class OTractor:
    multiplicity: int
    length: int


@dataclass
class OThrow:
    #: ``(component_format, component_cards)`` — the cards are decided when the
    #: throw is decomposed, never re-derived later.
    components: list[tuple["OFormat", tuple[Card, ...]]] = field(default_factory=list)


OFormat = Union[OSingle, OGroup, OTractor, OThrow]


def card_count(fmt: OFormat) -> int:
    if isinstance(fmt, OSingle):
        return 1
    if isinstance(fmt, OGroup):
        return fmt.count
    if isinstance(fmt, OTractor):
        return fmt.multiplicity * fmt.length
    if isinstance(fmt, OThrow):
        return sum(card_count(c) for c, _ in fmt.components)
    raise TypeError(fmt)


def classify(cards: Sequence[Card], ctx: TrumpContext, *, legacy: bool = False) -> OFormat:
    """R37.  Single / IdenticalGroup / Tractor / Throw."""
    n = len(cards)
    if n == 0:
        raise ValueError("cannot classify an empty play")
    if n == 1:
        return OSingle()
    if len(identity_groups(cards)) == 1:
        return OGroup(count=n)

    tractors = find_tractors(cards, ctx, legacy=legacy)
    if len(tractors) == 1 and len(tractors[0]) == n:
        length = len({strength(c, ctx) for c in cards})
        return OTractor(multiplicity=n // length, length=length)

    # Throw: maximal tractors first, then identity groups, then singles.
    components: list[tuple[OFormat, tuple[Card, ...]]] = []
    remaining = list(cards)
    for run in tractors:
        length = len({strength(c, ctx) for c in run})
        components.append((OTractor(multiplicity=len(run) // length, length=length), tuple(run)))
        for card in run:
            remaining.remove(card)
    for group in identity_groups(remaining).values():
        fmt: OFormat = OSingle() if len(group) == 1 else OGroup(count=len(group))
        components.append((fmt, tuple(group)))
    return OThrow(components=components)


def signature(fmt: OFormat) -> tuple:
    """A comparable shape summary (used to diff against the engine's format)."""
    if isinstance(fmt, OSingle):
        return ("single",)
    if isinstance(fmt, OGroup):
        return ("group", fmt.count)
    if isinstance(fmt, OTractor):
        return ("tractor", fmt.multiplicity, fmt.length)
    if isinstance(fmt, OThrow):
        return ("throw", tuple(sorted(signature(c) for c, _ in fmt.components)))
    raise TypeError(fmt)


# ---------------------------------------------------------------------------
# R38-R41 — lead legality
# ---------------------------------------------------------------------------

@dataclass
class LeadVerdict:
    #: ``"legal"`` | ``"beatable_throw"`` (R40 fails → R71 penalty, not a
    #: rejection) | ``"illegal_mixed_suit"`` (D16)
    outcome: str
    rule: str
    fmt: OFormat
    beatable: list[tuple[OFormat, tuple[Card, ...]]] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        """Whether the engine should accept the cards as submitted (R50 sense)."""
        return self.outcome != "illegal_mixed_suit"


def _opponent_beats_component(
    fmt: OFormat,
    comp_cards: Sequence[Card],
    opponent_hand: Sequence[Card],
    ctx: TrumpContext,
    *,
    legacy: bool = False,
) -> bool:
    """R40: can this one opponent beat this one component, in its own suit?"""
    comp_suit = effective_suit(comp_cards[0], ctx)
    comp_strength = max(strength(c, ctx) for c in comp_cards)
    suited = [c for c in opponent_hand if effective_suit(c, ctx) == comp_suit]

    if isinstance(fmt, OSingle):
        return any(strength(c, ctx) > comp_strength for c in suited)
    if isinstance(fmt, OGroup):
        return any(
            len(g) >= fmt.count and strength(g[0], ctx) > comp_strength
            for g in identity_groups(suited).values()
        )
    if isinstance(fmt, OTractor):
        # D08: a longer opposing tractor beats it too.
        needed = card_count(fmt)
        return any(
            len(run) >= needed and max(strength(c, ctx) for c in run) > comp_strength
            for run in find_tractors(suited, ctx, legacy=legacy)
        )
    raise TypeError(fmt)


def lead_verdict(
    cards: Sequence[Card],
    leader_id: str,
    all_hands: dict[str, list[Card]],
    ctx: TrumpContext,
    *,
    legacy: bool = False,
) -> LeadVerdict:
    """R38-R41.  Singles/groups/tractors are unrestricted; throws are tested."""
    fmt = classify(cards, ctx, legacy=legacy)
    if not isinstance(fmt, OThrow):
        return LeadVerdict("legal", "R38", fmt)

    # D16 (changes R38/R39): a throw is a claim about one suit.
    if len({effective_suit(c, ctx) for c in cards}) > 1:
        return LeadVerdict("illegal_mixed_suit", "D16/R39", fmt)

    beatable = [
        (comp_fmt, comp_cards)
        for comp_fmt, comp_cards in fmt.components
        if any(
            _opponent_beats_component(comp_fmt, comp_cards, hand, ctx, legacy=legacy)
            for pid, hand in all_hands.items()
            if pid != leader_id  # R41: every other hand, partner included (D07)
        )
    ]
    if beatable:
        return LeadVerdict("beatable_throw", "R40", fmt, beatable)
    return LeadVerdict("legal", "R40", fmt)


# ---------------------------------------------------------------------------
# R42-R47 — follow legality
# ---------------------------------------------------------------------------

def _is_submultiset(part: Sequence[Card], whole: Sequence[Card]) -> bool:
    pool = list(whole)
    for card in part:
        if card not in pool:
            return False
        pool.remove(card)
    return True


def tractor_pair_capacity(
    cards: Sequence[Card], needed: int, ctx: TrumpContext, *, legacy: bool = False
) -> tuple[int, int]:
    """R46's ``(tractor_cards, extra_paired_cards)`` capacity of *cards*.

    "Repeatedly take the longest available tractor (whole pairs only) until
    ``needed`` cards are claimed, then count the remaining paired cards, capped
    at the open slots."  The tractors are recomputed after each claim, which is
    what "available" means once cards have been taken out.
    """
    remaining = list(cards)
    tractor_cards = 0
    while tractor_cards < needed:
        runs = find_tractors(remaining, ctx, legacy=legacy, wrap_reference=cards)
        if not runs:
            break
        longest = max(runs, key=len)
        take = min(len(longest), needed - tractor_cards)
        take -= take % 2  # whole pairs only
        if take == 0:
            break
        tractor_cards += take
        for card in longest[:take]:
            remaining.remove(card)

    paired = sum(len(g) - len(g) % 2 for g in identity_groups(remaining).values())
    paired = min(paired, needed - tractor_cards)
    paired -= paired % 2
    return tractor_cards, paired


def _greedy_tractor_claim(
    cards: Sequence[Card], needed: int, ctx: TrumpContext, *, legacy: bool = False
) -> tuple[list[Card], list[Card]]:
    """R47's card-specific claim for a Tractor component: tractors, then pairs.

    Returns ``(claimed, left_over)``.
    """
    remaining = list(cards)
    claimed: list[Card] = []
    while len(claimed) < needed:
        runs = find_tractors(remaining, ctx, legacy=legacy, wrap_reference=cards)
        if not runs:
            break
        longest = max(runs, key=len)
        take = min(len(longest), needed - len(claimed))
        take -= take % 2
        if take == 0:
            break
        claimed.extend(longest[:take])
        for card in longest[:take]:
            remaining.remove(card)

    if len(claimed) < needed:
        by_strength = sorted(
            (g for g in identity_groups(remaining).values() if len(g) >= 2),
            key=lambda g: strength(g[0], ctx),
            reverse=True,
        )
        for group in by_strength:
            if len(claimed) >= needed:
                break
            take = min(len(group), needed - len(claimed))
            claimed.extend(group[:take])
            for card in group[:take]:
                remaining.remove(card)
    return claimed, remaining


def _can_supply_groups(cards: Sequence[Card], obligations: Sequence[int]) -> bool:
    """Is there *any* way to carve the required groups out of *cards*?

    Exhaustive: obligations are satisfied by disjoint slices of identity groups,
    and every assignment is tried before giving up.
    """
    counts = sorted((len(g) for g in identity_groups(cards).values()), reverse=True)

    def search(pool: list[int], todo: list[int]) -> bool:
        if not todo:
            return True
        k, rest = todo[0], todo[1:]
        tried: set[int] = set()
        for i, available in enumerate(pool):
            if available < k or available in tried:
                continue
            tried.add(available)
            nxt = sorted(pool[:i] + [available - k] + pool[i + 1:], reverse=True)
            if search(nxt, rest):
                return True
        return False

    return search(counts, sorted(obligations, reverse=True))


def _throw_follow_obligations(
    hand_suited: Sequence[Card], led: OThrow, ctx: TrumpContext, *, legacy: bool = False
) -> tuple[list[tuple[int, int, int]], list[int]]:
    """R47 (as ruled by D23): per component, largest first — structural for
    tractors AND identity groups, nothing for singles.

    A Tractor component fixes how much tractor/pair structure the follower
    must supply — ``(tractor_cards, extra_paired_cards, component_size)`` —
    but *which* tractor or pairs supply it is the follower's choice.  (The
    pre-D23 rule demanded the exact cards of the greedy claim, which forced
    the weakest of two equal-length tractors; see audit F5 / matrix NEW-1.)
    """
    remaining = list(hand_suited)
    tractor_obligations: list[tuple[int, int, int]] = []
    group_obligations: list[int] = []

    for comp_fmt, _cards in sorted(led.components, key=lambda cc: -card_count(cc[0])):
        if isinstance(comp_fmt, OTractor):
            comp_n = card_count(comp_fmt)
            # Measure with the SAME capacity function the verdict applies to
            # the proposal (R46 semantics: a partial take from a longer
            # tractor counts as tractor structure).  Measuring the claimed
            # cards instead would under-demand: a 2-card fragment of a
            # 4-card tractor is only a pair once isolated.
            req_tr, req_pd = tractor_pair_capacity(remaining, comp_n, ctx, legacy=legacy)
            _claimed, remaining = _greedy_tractor_claim(
                remaining, comp_n, ctx, legacy=legacy
            )
            tractor_obligations.append((req_tr, req_pd, comp_n))
        elif isinstance(comp_fmt, OGroup):
            k = comp_fmt.count
            candidates = [g for g in identity_groups(remaining).values() if len(g) >= k]
            if candidates:
                chosen = max(candidates, key=lambda g: strength(g[0], ctx))
                group_obligations.append(k)
                for card in chosen[:k]:
                    remaining.remove(card)
        # Single component: no obligation.
    return tractor_obligations, group_obligations


@dataclass
class FollowVerdict:
    legal: bool
    rule: str
    detail: str = ""


def follow_verdict(
    proposed: Sequence[Card],
    hand: Sequence[Card],
    led_fmt: OFormat,
    led_suit: str,
    ctx: TrumpContext,
    *,
    legacy: bool = False,
) -> FollowVerdict:
    """R36 + R42-R47.  Is *proposed* a legal follow from *hand*?"""
    n = card_count(led_fmt)
    if len(proposed) != n:
        return FollowVerdict(False, "R36", f"played {len(proposed)} cards, lead had {n}")
    if not _is_submultiset(proposed, hand):
        return FollowVerdict(False, "R50", "cards are not in hand")

    suited_hand = [c for c in hand if effective_suit(c, ctx) == led_suit]
    suited_play = [c for c in proposed if effective_suit(c, ctx) == led_suit]
    s = len(suited_hand)

    # R42: exactly min(s, n) led-suit cards.
    if len(suited_play) != min(s, n):
        return FollowVerdict(
            False, "R42", f"{len(suited_play)} led-suit cards, must be {min(s, n)}"
        )
    # R43/R49: short or void — all led-suit cards played, the rest is free.
    if s < n:
        return FollowVerdict(True, "R43")

    if isinstance(led_fmt, OSingle):
        return FollowVerdict(True, "R44")  # any one led-suit card

    if isinstance(led_fmt, OGroup):
        k = led_fmt.count
        if not has_group(suited_hand, k):
            return FollowVerdict(True, "R45", f"hand holds no group of {k}")
        if not has_group(suited_play, k):
            return FollowVerdict(False, "R45", f"hand can supply a group of {k}")
        return FollowVerdict(True, "R45")

    if isinstance(led_fmt, OTractor):
        req_tractor, req_paired = tractor_pair_capacity(suited_hand, n, ctx, legacy=legacy)
        got_tractor, got_paired = tractor_pair_capacity(suited_play, n, ctx, legacy=legacy)
        if got_tractor < req_tractor:
            return FollowVerdict(
                False, "R46", f"{got_tractor} tractor cards, hand can supply {req_tractor}"
            )
        if got_tractor + got_paired < req_tractor + req_paired:
            return FollowVerdict(
                False,
                "R46",
                f"{got_tractor + got_paired} paired cards, hand can supply "
                f"{req_tractor + req_paired}",
            )
        return FollowVerdict(True, "R46")

    if isinstance(led_fmt, OThrow):
        tractor_obs, obligations = _throw_follow_obligations(
            suited_hand, led_fmt, ctx, legacy=legacy
        )
        left = list(suited_play)
        for req_tr, req_pd, comp_n in sorted(tractor_obs, key=lambda o: -o[2]):
            got_tr, got_pd = tractor_pair_capacity(left, comp_n, ctx, legacy=legacy)
            _claimed_p, left = _greedy_tractor_claim(left, comp_n, ctx, legacy=legacy)
            if got_tr < req_tr:
                return FollowVerdict(
                    False, "R47",
                    f"{got_tr} tractor cards for a {comp_n}-card component, "
                    f"hand can supply {req_tr} (D23 structural)",
                )
            if got_tr + got_pd < req_tr + req_pd:
                return FollowVerdict(
                    False, "R47",
                    f"{got_tr + got_pd} paired cards for a {comp_n}-card component, "
                    f"hand can supply {req_tr + req_pd} (D23 structural)",
                )
        if not _can_supply_groups(left, obligations):
            return FollowVerdict(False, "R47", f"must include groups {obligations}")
        return FollowVerdict(True, "R47")

    raise TypeError(led_fmt)


# ---------------------------------------------------------------------------
# Enumeration helper (used to build candidate sets)
# ---------------------------------------------------------------------------

def legal_follows(
    hand: Sequence[Card],
    led_fmt: OFormat,
    led_suit: str,
    ctx: TrumpContext,
    *,
    legacy: bool = False,
) -> list[tuple[Card, ...]]:
    """Every legal follow, by brute force.  Only for small hands / small n."""
    n = card_count(led_fmt)
    out: list[tuple[Card, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for combo in combinations(range(len(hand)), n):
        cards = tuple(hand[i] for i in combo)
        key = tuple(sorted(repr(c) for c in cards))
        if key in seen:
            continue
        seen.add(key)
        if follow_verdict(cards, hand, led_fmt, led_suit, ctx, legacy=legacy).legal:
            out.append(cards)
    return out
