"""Differential legality testing: the engine vs an independent oracle.

``oracle.py`` re-derives R6/R7/R8/R37 and the lead/follow legality rules
(R35-R50) from ``docs/RULES.md`` alone.  This module drives seeded full games
through the real engine and, at **every** turn, asks both implementations the
same question about a set of candidate plays:

* follower turns — for each candidate, ``oracle.follow_verdict`` vs the engine's
  ``engine.tricks.is_valid_follow`` (a pure predicate; ``play_cards`` is never
  called on a candidate, so no state is mutated);
* leader turns — for each candidate, the oracle's classification and R40 throw
  test vs the engine's ``classify_play`` / ``validate_throw``.

Candidates are the play the bot actually chose, the engine's own
``get_legal_plays`` suggestion, an exhaustive enumeration when the hand is small
enough, otherwise a sample biased toward led-suit combinations, plus targeted
near-misses (swap one card for an off-suit card, break a required pair, wrong
card count).

A second battery (``run_synthetic``) constructs the same question directly:
dealt games hardly ever produce a tractor lead and their throw leads are usually
beatable, so R46/R47 would stay nearly untested if the games were the only
source.  Both batteries feed the same comparison code, and both are seeded.

Two ``test_harness_detects_a_seeded_*`` tests monkeypatch the engine into
accepting everything and assert the harness notices, so "0 findings" cannot
quietly mean "0 comparisons".

Running
-------
    python -m pytest tests/test_fuzz/test_oracle.py -q          # light, ~1s
    FUZZ=1 python -m pytest tests/test_fuzz/test_oracle.py -q   # heavy, ~35s
    python -m pytest tests/test_fuzz/test_oracle.py -q -s       # + coverage counts

Tolerances (none)
-----------------
The 2026-07-29 rulings (D16-D18, D20-D23) are implemented in both the oracle
and the engine, and the scheduled-deviation tolerance this module carried while
the fix wave was in flight has been deleted: EVERY disagreement is now a
finding and fails the test.  The ``legacy=True`` oracle mode (the pre-D18
adjacency ladder) is retained only so pin tests can assert what the old
behavior was.

History: this harness found FINDING-ORACLE-1 (cross-suit pairs classifying as
a Tractor and escaping throw validation — the audit's F1), fixed by D22 and
pinned by ``test_finding_cross_suit_tractor_fixed_by_d22``.  Its differential
run also caught an asymmetric first draft of the D23 structural obligation in
the oracle itself (requirement measured on the claimed cards, verdict measured
by capacity), which is why both sides now use ``tractor_pair_capacity`` on the
same footing.
"""
from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations

import pytest

from shengji.engine.tricks import get_legal_plays, is_valid_follow, validate_throw
from shengji.models.card import Card, Rank, Suit
from shengji.models.game_state import GamePhase
from shengji.models.groups import (
    IdenticalGroup,
    Single,
    Throw,
    Tractor,
    classify_play,
)
from shengji.models.trump import TrumpContext

from tests.test_fuzz import oracle
from tests.test_fuzz.fuzz_helpers import HEAVY, MODES, FuzzDriver, RandomBot

# --- light / heavy dials ---------------------------------------------------
SEEDS = [0, 1, 2, 3, 5, 8] if HEAVY else [0, 1]
MAX_ROUNDS = 2 if HEAVY else 1
FOLLOW_BUDGET = 90 if HEAVY else 26
LEAD_BUDGET = 20 if HEAVY else 8
#: Enumerate every n-subset of the hand when there are at most this many.
ENUM_CAP = 600 if HEAVY else 120
#: Constructed (lead, hand) pairs — see ``synthetic_case``.
SYNTH_SEEDS = [0, 1, 2, 3, 4, 5] if HEAVY else [0, 1]
SYNTH_CASES = 2500 if HEAVY else 200

CASES = [(seed, mode) for seed in SEEDS for mode in MODES]


# ---------------------------------------------------------------------------
# Format signatures — the two implementations use different classes
# ---------------------------------------------------------------------------

def engine_signature(fmt) -> tuple:
    if isinstance(fmt, Single):
        return ("single",)
    if isinstance(fmt, IdenticalGroup):
        return ("group", fmt.count)
    if isinstance(fmt, Tractor):
        return ("tractor", fmt.multiplicity, fmt.length)
    if isinstance(fmt, Throw):
        return ("throw", tuple(sorted(engine_signature(c) for c in fmt.components)))
    raise TypeError(fmt)


def show(cards) -> str:
    return " ".join(repr(c) for c in cards)


# ---------------------------------------------------------------------------
# Disagreement bookkeeping
# ---------------------------------------------------------------------------

@dataclass
class Disagreement:
    seed: int
    mode: str
    trick: int
    kind: str          # "classify" | "follow" | "throw"
    label: str | None  # "D16" / "D18" / … when scheduled, None when a finding
    player: str
    hand: list[Card]
    lead: list[Card]
    candidate: list[Card]
    oracle: str
    engine: str
    ctx: TrumpContext | None = None

    def render(self) -> str:
        tag = f"[{self.label}] " if self.label else ""
        trump = "?"
        if self.ctx is not None:
            suit = self.ctx.trump_suit.value if self.ctx.trump_suit else "NO TRUMP"
            trump = f"rank {self.ctx.trump_rank.value}, {suit}"
        repro = (
            f"run_synthetic({self.seed}, cases={self.trick + 1})"
            if self.mode == "synthetic"
            else f"FuzzDriver({self.seed}, {self.mode!r}).run()"
        )
        return (
            f"\n{tag}{self.kind} disagreement — seed={self.seed} mode={self.mode} "
            f"trick={self.trick} player={self.player}"
            f"\n    trump     : {trump}"
            f"\n    hand      : {show(self.hand)}"
            f"\n    lead      : {show(self.lead) or '(this player is leading)'}"
            f"\n    candidate : {show(self.candidate)}"
            f"\n    oracle    : {self.oracle}"
            f"\n    engine    : {self.engine}"
            f"\n    repro     : {repro}"
        )


@dataclass
class Report:
    #: ``(rule, verdict) -> count`` for follow candidates — shows which
    #: obligations the run actually exercised, in both directions.
    rules: Counter = field(default_factory=Counter)
    states: int = 0
    lead_states: int = 0
    follow_states: int = 0
    candidates: int = 0
    lead_candidates: int = 0
    follow_candidates: int = 0
    agreements: int = 0
    findings: list[Disagreement] = field(default_factory=list)
    scheduled: list[Disagreement] = field(default_factory=list)

    def merge(self, other: "Report") -> None:
        self.rules.update(other.rules)
        self.states += other.states
        self.lead_states += other.lead_states
        self.follow_states += other.follow_states
        self.candidates += other.candidates
        self.lead_candidates += other.lead_candidates
        self.follow_candidates += other.follow_candidates
        self.agreements += other.agreements
        self.findings += other.findings
        self.scheduled += other.scheduled

    def summary(self) -> str:
        labels: dict[str, int] = {}
        for d in self.scheduled:
            labels[d.label] = labels.get(d.label, 0) + 1
        detail = ", ".join(f"{k}x{v}" for k, v in sorted(labels.items())) or "none"
        exercised = ", ".join(
            f"{rule}:{'ok' if legal else 'no'}x{n}"
            for (rule, legal), n in sorted(self.rules.items())
        )
        return (
            f"{self.states} states ({self.lead_states} lead / {self.follow_states} follow), "
            f"{self.candidates} candidates ({self.lead_candidates} lead / "
            f"{self.follow_candidates} follow), {self.agreements} agreements, "
            f"scheduled deviations: {detail}, findings: {len(self.findings)}"
            f"\n           follow rules exercised: {exercised}"
        )


#: Totals across every parametrised case in the session.
TOTALS = Report()


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------

def _adder(bucket: list[list[Card]], seen: set[tuple[str, ...]]):
    def add(cards) -> None:
        cards = list(cards)
        if not cards:
            return
        key = tuple(sorted(repr(c) for c in cards))
        if key in seen:
            return
        seen.add(key)
        bucket.append(cards)
    return add


def _remainder(hand: list[Card], used: list[Card]) -> list[Card]:
    rest = list(hand)
    for card in used:
        if card in rest:
            rest.remove(card)
    return rest


def follow_candidates(
    rng: random.Random,
    hand: list[Card],
    n: int,
    led_suit: str,
    ctx: TrumpContext,
    chosen: list[Card],
    hint: list[Card],
    budget: int,
) -> list[list[Card]]:
    """Legal plays plus near-misses, for a follower holding *hand*."""
    out: list[list[Card]] = []
    add = _adder(out, set())
    add(chosen)
    add(hint)

    suited = [c for c in hand if oracle.effective_suit(c, ctx) == led_suit]
    off_suit = [c for c in hand if oracle.effective_suit(c, ctx) != led_suit]

    if n <= len(hand) and math.comb(len(hand), n) <= ENUM_CAP:
        for combo in combinations(range(len(hand)), n):
            add([hand[i] for i in combo])
    else:
        # Bias toward led-suit combinations: those are where the interesting
        # obligations (R45/R46/R47) live — a random draw from the whole hand is
        # almost always rejected by R42 alone.
        for _ in range(budget // 2):
            if len(suited) >= n:
                add(rng.sample(suited, n))
            elif off_suit:
                add(suited + rng.sample(off_suit, min(n - len(suited), len(off_suit))))
        while len(out) < budget:
            before = len(out)
            add(rng.sample(hand, n))
            if len(out) == before and len(out) >= budget // 2:
                break

    # Targeted near-misses around plays the engine itself considers legal:
    # swap one card (off-suit substitution / pair break) and wrong card counts.
    for base in (chosen, hint):
        if not base:
            continue
        rest = _remainder(hand, base)
        for _ in range(3):
            if not rest:
                break
            mutant = list(base)
            mutant[rng.randrange(len(mutant))] = rng.choice(rest)
            add(mutant)
        if len(base) > 1:
            add(base[:-1])          # R36: one card short
        if rest:
            add(base + [rest[0]])   # R36: one card long
    return out


def lead_candidates(
    rng: random.Random, hand: list[Card], ctx: TrumpContext, chosen: list[Card], budget: int
) -> list[list[Card]]:
    """Singles, pairs, tractors, single-suit multi-component plays, mixed junk."""
    out: list[list[Card]] = []
    add = _adder(out, set())
    add(chosen)

    for card in rng.sample(hand, min(2, len(hand))):
        add([card])
    pairs = [g for g in oracle.identity_groups(hand).values() if len(g) >= 2]
    for group in pairs[:2]:
        add(group[:2])
    for run in oracle.find_tractors(hand, ctx)[:2]:
        add(run)

    by_suit: dict[str, list[Card]] = {}
    for card in hand:
        by_suit.setdefault(oracle.effective_suit(card, ctx), []).append(card)
    # Same-suit multi-card plays — these are the ones R40 actually judges.
    for suit_cards in sorted(by_suit.values(), key=len, reverse=True)[:2]:
        for _ in range(2):
            if len(suit_cards) >= 2:
                k = rng.randint(2, min(5, len(suit_cards)))
                add(rng.sample(suit_cards, k))
    # Mixed-suit plays — the D16 surface.
    while len(out) < budget and len(hand) >= 2:
        before = len(out)
        add(rng.sample(hand, rng.randint(2, min(5, len(hand)))))
        if len(out) == before:
            break
    return out[:budget]


# ---------------------------------------------------------------------------
# The cross-check itself
# ---------------------------------------------------------------------------

class CrossChecker:
    def __init__(self, seed: int, mode: str) -> None:
        self.seed = seed
        self.mode = mode
        self.rng = random.Random(seed * 7919 + 13)  # separate from the game rng
        self.report = Report()

    # -- helpers ---------------------------------------------------------

    def _record(self, dis: Disagreement) -> None:
        if dis.label:
            self.report.scheduled.append(dis)
        else:
            self.report.findings.append(dis)

    def _diff(self, ctx: TrumpContext, **kwargs) -> Disagreement:
        return Disagreement(seed=self.seed, mode=self.mode, ctx=ctx, **kwargs)

    # -- entry point -----------------------------------------------------

    def on_turn(self, engine, player, chosen: list[Card]) -> None:
        state = engine.state
        self.report.states += 1
        if state.current_trick:
            self.check_follow(engine, player, chosen)
        else:
            self.check_lead(engine, player, chosen)

    # -- leader ----------------------------------------------------------

    def check_lead(self, engine, player, chosen: list[Card]) -> None:
        state = engine.state
        ctx = state.trump_context
        self.report.lead_states += 1
        all_hands = {p.id: list(p.hand) for p in state.players}
        hand = list(player.hand)

        for cand in lead_candidates(self.rng, hand, ctx, chosen, LEAD_BUDGET):
            self.report.candidates += 1
            self.report.lead_candidates += 1

            spec = oracle.lead_verdict(cand, player.id, all_hands, ctx)
            engine_fmt = classify_play(cand, ctx)
            engine_sig = engine_signature(engine_fmt)

            # (a) mixed-suit leads (D16) — the engine's gate lives in
            # ``play_cards`` (not ``classify_play``/``validate_throw``), and is
            # exactly "the cards span >1 effective suit".  Both sides implement
            # the same predicate, so compare it directly; the engine-level
            # rejection itself is pinned in tests/test_engine/test_mixed_lead_d16.py.
            if spec.outcome == "illegal_mixed_suit":
                engine_rejects = len({ctx.effective_suit(c) for c in cand}) > 1
                if engine_rejects:
                    self.report.agreements += 1
                else:
                    self._record(self._diff(
                        ctx, trick=state.trick_number, kind="throw", label=None,
                        player=player.id, hand=hand, lead=[], candidate=cand,
                        oracle="D16/R39 → illegal lead (spans several suits)",
                        engine="play_cards gate would accept it",
                    ))
                continue

            # (b) format classification (R37)
            if oracle.signature(spec.fmt) != engine_sig:
                self._record(self._diff(
                    ctx, trick=state.trick_number, kind="classify", label=None,
                    player=player.id, hand=hand, lead=[], candidate=cand,
                    oracle=f"R37/R8 → {oracle.signature(spec.fmt)}",
                    engine=f"{engine_sig}",
                ))
                continue

            # (c) lead legality (R38-R41)
            engine_valid = validate_throw(cand, player.id, all_hands, ctx)
            oracle_valid = spec.outcome != "beatable_throw"
            if oracle_valid != engine_valid:
                beaten = ", ".join(show(c) for _, c in spec.beatable)
                self._record(self._diff(
                    ctx, trick=state.trick_number, kind="throw", label=None,
                    player=player.id, hand=hand, lead=[], candidate=cand,
                    oracle=f"{spec.rule} → {'valid' if oracle_valid else 'beatable'}"
                           + (f" (beatable components: {beaten})" if beaten else ""),
                    engine=f"validate_throw → {engine_valid}",
                ))
                continue

            self.report.agreements += 1

    # -- follower --------------------------------------------------------

    def check_follow(self, engine, player, chosen: list[Card]) -> None:
        state = engine.state
        ctx = state.trump_context
        self.report.follow_states += 1
        hand = list(player.hand)
        lead_cards = list(state.current_trick[0][1])

        engine_fmt = state.led_format
        engine_suit = state.led_suit
        spec_fmt = oracle.classify(lead_cards, ctx)
        # R42's preamble: the led suit is the effective suit of the first led card.
        spec_suit = oracle.effective_suit(lead_cards[0], ctx)

        if spec_suit != engine_suit:
            self._record(self._diff(
                ctx, trick=state.trick_number, kind="classify", label=None,
                player=player.id, hand=hand, lead=lead_cards, candidate=[],
                oracle=f"R7/R42 led suit {spec_suit}", engine=f"led suit {engine_suit}",
            ))
            return

        if oracle.signature(spec_fmt) != engine_signature(engine_fmt):
            self._record(self._diff(
                ctx, trick=state.trick_number, kind="classify", label=None,
                player=player.id, hand=hand, lead=lead_cards, candidate=[],
                oracle=f"R37 led format {oracle.signature(spec_fmt)}",
                engine=f"led format {engine_signature(engine_fmt)}",
            ))

        n = oracle.card_count(spec_fmt)
        hint = get_legal_plays(hand, engine_fmt, engine_suit, ctx)
        hint = list(hint[0]) if hint else []
        candidates = follow_candidates(
            self.rng, hand, n, spec_suit, ctx, chosen, hint, FOLLOW_BUDGET
        )
        self.compare_follows(
            ctx, hand, lead_cards, candidates,
            spec_fmt, spec_suit, engine_fmt, engine_suit,
            trick=state.trick_number, player=player.id,
        )

    def compare_follows(
        self,
        ctx: TrumpContext,
        hand: list[Card],
        lead_cards: list[Card],
        candidates: list[list[Card]],
        spec_fmt,
        spec_suit: str,
        engine_fmt,
        engine_suit: str,
        *,
        trick: int,
        player: str,
    ) -> None:
        """Diff both implementations over *candidates*; record every mismatch.

        Shared by the game-driven cross-check and the synthetic battery.
        """
        for cand in candidates:
            self.report.candidates += 1
            self.report.follow_candidates += 1

            spec = oracle.follow_verdict(cand, hand, spec_fmt, spec_suit, ctx)
            self.report.rules[(spec.rule, spec.legal)] += 1
            engine_ok = is_valid_follow(cand, hand, engine_fmt, engine_suit, ctx)
            if spec.legal == engine_ok:
                self.report.agreements += 1
                continue

            self._record(self._diff(
                ctx, trick=trick, kind="follow", label=None,
                player=player, hand=hand, lead=lead_cards, candidate=cand,
                oracle=f"{spec.rule} → {'legal' if spec.legal else 'ILLEGAL'}"
                       + (f" ({spec.detail})" if spec.detail else ""),
                engine=f"is_valid_follow → {engine_ok}",
            ))


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

class CrossCheckBot(RandomBot):
    """The random-legal bot, hooked on every play and biased toward big leads.

    ``RandomBot`` leads a single most of the time, which leaves R46 (tractor
    follows) and R47 (throw follows) almost unexercised — a legality oracle that
    never sees a tractor lead is not worth much.  Follows are still the stock
    random-legal choice; only the *lead* distribution changes, and every lead it
    picks is one ``RandomBot`` could also have picked.
    """

    def __init__(self, rng: random.Random, checker: CrossChecker) -> None:
        super().__init__(rng)
        self.checker = checker

    def choose_play(self, engine, player):
        state = engine.state
        if state.current_trick:
            cards = super().choose_play(engine, player)
        else:
            cards = self.choose_lead(state.trump_context, list(player.hand))
        self.checker.on_turn(engine, player, list(cards))
        return cards

    def choose_lead(self, ctx, hand: list[Card]) -> list[Card]:
        roll = self.rng.random()

        tractors = oracle.find_tractors(hand, ctx)
        if roll < 0.30 and tractors:
            return list(self.rng.choice(tractors))

        pairs = [g[:2] for g in oracle.identity_groups(hand).values() if len(g) >= 2]
        if roll < 0.55 and pairs:
            return list(self.rng.choice(pairs))

        if roll < 0.85:
            by_suit: dict[str, list[Card]] = {}
            for card in hand:
                by_suit.setdefault(oracle.effective_suit(card, ctx), []).append(card)
            wide = [cards for cards in by_suit.values() if len(cards) >= 3]
            if wide:
                suit_cards = self.rng.choice(wide)
                # The top cards of a suit — a throw built this way is usually
                # unbeatable, so it survives R40 and followers actually face a
                # Throw lead rather than the reduced play of a failed throw.
                suit_cards.sort(key=lambda c: oracle.strength(c, ctx), reverse=True)
                k = self.rng.randint(2, min(5, len(suit_cards)))
                return suit_cards[:k]

        return [self.rng.choice(hand)]


class OracleDriver(FuzzDriver):
    """FuzzDriver with the cross-checker wired in.

    ``verify`` is a no-op here: the per-action invariant battery is
    ``test_invariants.py``'s job, and running it again would triple this
    suite's runtime for no extra coverage.  Round-end checks still run
    (``finish_round`` calls them directly).
    """

    def __init__(self, seed: int, mode: str, **kwargs) -> None:
        super().__init__(seed, mode, **kwargs)
        self.checker = CrossChecker(seed, mode)
        self.bot = CrossCheckBot(self.rng, self.checker)

    def verify(self, label: str, *, live_points: str | None = None) -> None:
        self.checks += 1


def run_case(seed: int, mode: str) -> Report:
    driver = OracleDriver(seed, mode, max_rounds=MAX_ROUNDS, deal_check_every=1000)
    driver.run()
    return driver.checker.report


# ---------------------------------------------------------------------------
# Synthetic follow battery
# ---------------------------------------------------------------------------
#
# Dealt games almost never produce a tractor lead (two adjacent identical pairs
# in one hand) and their throw leads are usually beatable, so R46/R47 barely
# fire in a game-driven run.  ``is_valid_follow`` is a pure function of
# (proposal, hand, led format, led suit, trump context), so the battery below
# constructs those four directly: a lead built from consecutive rungs of one
# suit's strength ladder, and a follower hand stocked with that suit.  Card
# multiplicities respect the two-deck limit, so every (hand, lead) pair is one
# a real deal could produce.

SUITED = [Suit.SPADES, Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS]
IDENTITIES = [Card(s, r) for s in SUITED for r in oracle.SPEC_RANK_SEQUENCE] + [
    Card(Suit.JOKER, Rank.SMALL_JOKER), Card(Suit.JOKER, Rank.BIG_JOKER)
]


def synthetic_case(
    rng: random.Random,
) -> tuple[TrumpContext, list[Card], list[Card], dict[str, list[Card]]]:
    """A random (trump context, single-suit lead, follower hand, all hands).

    ``all_hands`` deals what is left of the two decks to the three non-leaders,
    which is what R40/R41 judge a throw against.
    """
    ctx = TrumpContext(
        trump_rank=rng.choice(oracle.SPEC_RANK_SEQUENCE),
        trump_suit=rng.choice([*SUITED, None]),
    )

    by_effective: dict[str, list[Card]] = {}
    for card in IDENTITIES:
        by_effective.setdefault(oracle.effective_suit(card, ctx), []).append(card)
    led_suit = rng.choice(sorted(by_effective))
    ladder = sorted(by_effective[led_suit], key=lambda c: oracle.strength(c, ctx))
    elsewhere = [c for suit, cs in by_effective.items() if suit != led_suit for c in cs]

    left = {(c.suit, c.rank): 2 for c in IDENTITIES}

    def draw(card: Card, copies: int) -> list[Card]:
        key = (card.suit, card.rank)
        copies = min(copies, left[key])
        left[key] -= copies
        return [card] * copies

    # --- the lead: consecutive ladder rungs, so tractors actually occur ------
    style = rng.choice(["single", "pair", "run", "run", "mixed", "mixed", "scatter"])
    lead: list[Card] = []
    if style == "single":
        lead = draw(rng.choice(ladder), 1)
    elif style == "pair":
        lead = draw(rng.choice(ladder), 2)
    elif style in ("run", "mixed"):
        length = rng.randint(2, 3)
        start = rng.randrange(max(1, len(ladder) - length))
        for card in ladder[start:start + length]:
            lead += draw(card, 2)
        if style == "mixed":
            for card in rng.sample(ladder, min(2, len(ladder))):
                lead += draw(card, 1)
    else:  # scatter — loose singles, i.e. a throw of singles
        for card in rng.sample(ladder, min(rng.randint(2, 4), len(ladder))):
            lead += draw(card, 1)
    if not lead:
        lead = draw(ladder[0], 1) or [ladder[0]]

    # --- the follower's hand ------------------------------------------------
    n = len(lead)
    hand: list[Card] = []
    suited_target = rng.choice([0, 1, n - 1, n, n, n + 2, n + 4])
    for _ in range(4 * len(ladder)):  # the ladder can run out of copies
        if len(hand) >= suited_target:
            break
        hand += draw(rng.choice(ladder), rng.choice([1, 2, 2]))
    if rng.random() < 0.35:  # plant a tractor in the follower's suit
        start = rng.randrange(max(1, len(ladder) - 2))
        for card in ladder[start:start + 2]:
            hand += draw(card, 2)
    total = max(n, len(hand)) + rng.randint(0, 5)
    for _ in range(4 * len(elsewhere)):
        if len(hand) >= total:
            break
        hand += draw(rng.choice(elsewhere), rng.choice([1, 2]))

    # The rest of the two decks, split between the leader's three opponents.
    # R41/D07: every one of them counts when judging the throw.
    pool = [Card(suit, rank) for (suit, rank), n_left in left.items() for _ in range(n_left)]
    rng.shuffle(pool)
    size = rng.randint(2, 10)
    all_hands = {"p0": list(lead)}
    all_hands["p1"] = hand
    for i, pid in enumerate(("p2", "p3")):
        all_hands[pid] = pool[i * size:(i + 1) * size]
    return ctx, lead, hand, all_hands


def run_synthetic(seed: int, cases: int) -> Report:
    checker = CrossChecker(seed, "synthetic")
    rng = random.Random(seed)
    for case in range(cases):
        ctx, lead, hand, all_hands = synthetic_case(rng)
        # D16: a mixed-suit lead is illegal and imposes no follow obligations;
        # play_cards rejects it before classification (pinned in
        # tests/test_engine/test_mixed_lead_d16.py).  Skip such cases.
        if len({ctx.effective_suit(c) for c in lead}) > 1:
            continue
        spec_fmt = oracle.classify(lead, ctx)
        engine_fmt = classify_play(lead, ctx)
        spec_suit = oracle.effective_suit(lead[0], ctx)
        engine_suit = ctx.effective_suit(lead[0])
        checker.report.states += 1
        checker.report.follow_states += 1

        if oracle.signature(spec_fmt) != engine_signature(engine_fmt):
            checker._record(checker._diff(
                ctx, trick=case, kind="classify", label=None, player="synthetic",
                hand=hand, lead=lead, candidate=[],
                oracle=f"R37 {oracle.signature(spec_fmt)}",
                engine=f"{engine_signature(engine_fmt)}",
            ))

        # --- lead legality (R38-R41) ---------------------------------------
        checker.report.lead_states += 1
        checker.report.candidates += 1
        checker.report.lead_candidates += 1
        spec_lead = oracle.lead_verdict(lead, "p0", all_hands, ctx)
        engine_valid = validate_throw(lead, "p0", all_hands, ctx)
        oracle_valid = spec_lead.outcome != "beatable_throw"
        if oracle_valid != engine_valid:
            beaten = ", ".join(show(c) for _, c in spec_lead.beatable)
            checker._record(checker._diff(
                ctx, trick=case, kind="throw", label=None, player="p0",
                hand=list(all_hands["p2"]) + list(all_hands["p3"]), lead=lead,
                candidate=lead,
                oracle=f"{spec_lead.rule} → {'valid' if oracle_valid else 'beatable'}"
                       + (f" (beatable: {beaten})" if beaten else ""),
                engine=f"validate_throw → {engine_valid}",
            ))
        else:
            checker.report.agreements += 1

        n = len(lead)
        if len(hand) < n:
            continue
        hint = get_legal_plays(hand, engine_fmt, engine_suit, ctx)
        hint = list(hint[0]) if hint else []
        candidates = follow_candidates(
            rng, hand, n, spec_suit, ctx, [], hint, FOLLOW_BUDGET
        )
        checker.compare_follows(
            ctx, hand, lead, candidates, spec_fmt, spec_suit, engine_fmt, engine_suit,
            trick=case, player="synthetic",
        )
    return checker.report


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed,mode", CASES)
def test_oracle_agrees_with_engine(seed: int, mode: str) -> None:
    """Every candidate play gets the same verdict from both implementations."""
    report = run_case(seed, mode)
    TOTALS.merge(report)
    print(f"\n[oracle] seed={seed} mode={mode}: {report.summary()}")
    assert report.candidates > 0, "no candidates were cross-checked"
    if report.findings:
        pytest.fail(
            f"{len(report.findings)} unscheduled legality disagreement(s):"
            + "".join(d.render() for d in report.findings[:5])
        )


@pytest.mark.parametrize("seed", SYNTH_SEEDS)
def test_oracle_agrees_on_constructed_leads(seed: int) -> None:
    """Same diff, over constructed tractor/throw leads a real deal rarely gives."""
    report = run_synthetic(seed, SYNTH_CASES)
    TOTALS.merge(report)
    print(f"\n[oracle] synthetic seed={seed}: {report.summary()}")
    exercised = {rule for rule, _ in report.rules}
    assert {"R45", "R46", "R47"} <= exercised, (
        f"battery never reached the group/tractor/throw obligations: {sorted(exercised)}"
    )
    if report.findings:
        pytest.fail(
            f"{len(report.findings)} unscheduled legality disagreement(s):"
            + "".join(d.render() for d in report.findings[:5])
        )


def test_harness_detects_a_seeded_bug(monkeypatch) -> None:
    """Teeth check: an engine that accepts everything must be caught.

    Without this, "0 findings" could just mean the comparison never ran.
    """
    monkeypatch.setattr(
        "tests.test_fuzz.test_oracle.is_valid_follow",
        lambda proposed, hand, led_format, led_suit, ctx: True,
    )
    report = run_synthetic(seed=99, cases=20)
    assert report.findings, "the harness failed to notice an always-accept engine"
    assert all(d.kind == "follow" for d in report.findings)


def test_harness_detects_a_seeded_throw_bug(monkeypatch) -> None:
    """Teeth check for the lead side: an engine that passes every throw."""
    monkeypatch.setattr(
        "tests.test_fuzz.test_oracle.validate_throw",
        lambda cards, thrower_id, all_hands, ctx: True,
    )
    report = run_synthetic(seed=99, cases=20)
    assert any(d.kind == "throw" for d in report.findings), (
        "the harness failed to notice an engine that validates every throw"
    )


def test_totals_reported() -> None:
    """Print the session totals (visible with -s); also a floor on coverage."""
    print(f"\n[oracle] TOTAL: {TOTALS.summary()}")
    assert TOTALS.states > 0


# ---------------------------------------------------------------------------
# Scheduled deviations — these pin the *current* engine behaviour.
# When the D16/D18 fix wave lands, they fail; delete them and the tolerance
# labels in CrossChecker at the same time.
# ---------------------------------------------------------------------------

def _hands(**kwargs) -> dict[str, list[Card]]:
    return {pid: list(cards) for pid, cards in kwargs.items()}


def test_scheduled_deviation_d16_mixed_suit_throw_lead() -> None:
    """D16: the oracle rejects a multi-suit throw lead; the engine accepts it."""
    ctx = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.SPADES)
    lead = [Card(Suit.HEARTS, Rank.ACE), Card(Suit.CLUBS, Rank.ACE)]
    hands = _hands(
        p0=lead + [Card(Suit.HEARTS, Rank.THREE)],
        p1=[Card(Suit.HEARTS, Rank.KING), Card(Suit.CLUBS, Rank.KING)],
        p2=[Card(Suit.DIAMONDS, Rank.ACE)],
        p3=[Card(Suit.DIAMONDS, Rank.KING)],
    )

    verdict = oracle.lead_verdict(lead, "p0", hands, ctx)
    assert verdict.outcome == "illegal_mixed_suit", "oracle must reject per D16/R39"
    assert isinstance(classify_play(lead, ctx), Throw)
    # D16 implemented: the engine's play_cards gate rejects any lead spanning
    # more than one effective suit (pinned end-to-end in
    # tests/test_engine/test_mixed_lead_d16.py — here we pin the predicate).
    assert len({ctx.effective_suit(c) for c in lead}) > 1


def test_scheduled_deviation_d18_no_trump_joker_tractor() -> None:
    """D18: in no-trump a trump-rank pair + Small-Joker pair is a tractor."""
    ctx = TrumpContext(trump_rank=Rank.TWO, trump_suit=None)
    cards = [
        Card(Suit.HEARTS, Rank.TWO), Card(Suit.HEARTS, Rank.TWO),
        Card(Suit.JOKER, Rank.SMALL_JOKER), Card(Suit.JOKER, Rank.SMALL_JOKER),
    ]

    assert oracle.signature(oracle.classify(cards, ctx)) == ("tractor", 2, 2)
    assert oracle.signature(oracle.classify(cards, ctx, legacy=True)) == (
        "throw", (("group", 2), ("group", 2))
    )
    # D18 implemented: the engine now skips the empty trump-suit-rank tier in
    # no-trump, agreeing with the oracle's non-legacy ladder.
    assert engine_signature(classify_play(cards, ctx)) == ("tractor", 2, 2)

    # With a trump suit the ladder is unbroken and both agree it is a tractor.
    suited = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.SPADES)
    spade_pair = [
        Card(Suit.SPADES, Rank.TWO), Card(Suit.SPADES, Rank.TWO),
        Card(Suit.JOKER, Rank.SMALL_JOKER), Card(Suit.JOKER, Rank.SMALL_JOKER),
    ]
    assert oracle.signature(oracle.classify(spade_pair, suited)) == ("tractor", 2, 2)
    assert engine_signature(classify_play(spade_pair, suited)) == ("tractor", 2, 2)


def test_known_limitation_three_position_wrap_is_split() -> None:
    """``Known limitations`` 1: a 3-position circular wrap is not one tractor.

    The oracle deliberately reproduces the engine here (the campaign brief
    treats the engine as correct), so this pins both at once.
    """
    ctx = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.SPADES)
    cards = [
        Card(Suit.HEARTS, Rank.KING), Card(Suit.HEARTS, Rank.KING),
        Card(Suit.HEARTS, Rank.ACE), Card(Suit.HEARTS, Rank.ACE),
        Card(Suit.HEARTS, Rank.THREE), Card(Suit.HEARTS, Rank.THREE),
    ]
    expected = ("throw", (("group", 2), ("tractor", 2, 2)))
    assert oracle.signature(oracle.classify(cards, ctx)) == expected
    assert engine_signature(classify_play(cards, ctx)) == expected

    # The 2-position wrap does work, in both implementations.
    wrap = cards[2:]  # A♥A♥ 3♥3♥
    assert oracle.signature(oracle.classify(wrap, ctx)) == ("tractor", 2, 2)
    assert engine_signature(classify_play(wrap, ctx)) == ("tractor", 2, 2)


def test_finding_cross_suit_tractor_fixed_by_d22() -> None:
    """FINDING-ORACLE-1, fixed by D22 — cross-suit pairs no longer chain.

    Pre-D22, R8's tier-0 clause never mentioned suit, so 5♥5♥ + 6♦6♦ was a
    Tractor in both implementations, skipped the R40 throw test, and escaped
    D16.  D22 makes adjacency require a shared effective suit; the play is now
    a Throw of two pairs, and as a mixed-suit lead it is rejected outright by
    the engine's D16 gate.
    """
    ctx = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.SPADES)
    cards = [
        Card(Suit.HEARTS, Rank.FIVE), Card(Suit.HEARTS, Rank.FIVE),
        Card(Suit.DIAMONDS, Rank.SIX), Card(Suit.DIAMONDS, Rank.SIX),
    ]
    expected = ("throw", (("group", 2), ("group", 2)))
    assert oracle.signature(oracle.classify(cards, ctx)) == expected
    assert engine_signature(classify_play(cards, ctx)) == expected
    hands = _hands(
        p0=cards,
        p1=[Card(Suit.HEARTS, Rank.KING), Card(Suit.HEARTS, Rank.KING),
            Card(Suit.DIAMONDS, Rank.KING), Card(Suit.DIAMONDS, Rank.KING)],
        p2=[], p3=[],
    )
    assert oracle.lead_verdict(cards, "p0", hands, ctx).outcome == "illegal_mixed_suit"
    assert len({ctx.effective_suit(c) for c in cards}) > 1  # engine D16 gate fires


# ---------------------------------------------------------------------------
# Oracle self-checks — the obligations the fuzz run may not reach often
# ---------------------------------------------------------------------------

def test_r42_r43_suit_obligation() -> None:
    ctx = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.SPADES)
    hand = [
        Card(Suit.HEARTS, Rank.FIVE), Card(Suit.HEARTS, Rank.NINE),
        Card(Suit.CLUBS, Rank.SEVEN), Card(Suit.SPADES, Rank.FOUR),
    ]
    lead = [Card(Suit.HEARTS, Rank.KING)]
    led, eng_led = oracle.classify(lead, ctx), classify_play(lead, ctx)

    # R44: any one heart is legal; a club while holding hearts is not (R42).
    for card in (Card(Suit.HEARTS, Rank.FIVE), Card(Suit.HEARTS, Rank.NINE)):
        assert oracle.follow_verdict([card], hand, led, "hearts", ctx).legal
        assert is_valid_follow([card], hand, eng_led, "hearts", ctx)
    bad = oracle.follow_verdict([Card(Suit.CLUBS, Rank.SEVEN)], hand, led, "hearts", ctx)
    assert (bad.legal, bad.rule) == (False, "R42")
    assert not is_valid_follow([Card(Suit.CLUBS, Rank.SEVEN)], hand, eng_led, "hearts", ctx)

    # R43: void in diamonds — anything goes.
    led_d = oracle.classify([Card(Suit.DIAMONDS, Rank.KING)], ctx)
    ok = oracle.follow_verdict([Card(Suit.SPADES, Rank.FOUR)], hand, led_d, "diamonds", ctx)
    assert (ok.legal, ok.rule) == (True, "R43")


def test_r45_any_pair_not_a_specific_one() -> None:
    """R45: holding two pairs, either one satisfies a pair lead."""
    ctx = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.SPADES)
    hand = [
        Card(Suit.HEARTS, Rank.FIVE), Card(Suit.HEARTS, Rank.FIVE),
        Card(Suit.HEARTS, Rank.KING), Card(Suit.HEARTS, Rank.KING),
        Card(Suit.HEARTS, Rank.NINE),
    ]
    lead = [Card(Suit.HEARTS, Rank.SEVEN), Card(Suit.HEARTS, Rank.SEVEN)]
    led, eng_led = oracle.classify(lead, ctx), classify_play(lead, ctx)
    for pair in (hand[0:2], hand[2:4]):
        assert oracle.follow_verdict(pair, hand, led, "hearts", ctx).legal
        assert is_valid_follow(pair, hand, eng_led, "hearts", ctx)
    split = [Card(Suit.HEARTS, Rank.FIVE), Card(Suit.HEARTS, Rank.NINE)]
    verdict = oracle.follow_verdict(split, hand, led, "hearts", ctx)
    assert (verdict.legal, verdict.rule) == (False, "R45")
    assert not is_valid_follow(split, hand, eng_led, "hearts", ctx)


def test_r46_tractor_capacity() -> None:
    """R46: a hand that can supply two pairs must supply two pairs."""
    ctx = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.SPADES)
    hand = [
        Card(Suit.HEARTS, Rank.FIVE), Card(Suit.HEARTS, Rank.FIVE),
        Card(Suit.HEARTS, Rank.NINE), Card(Suit.HEARTS, Rank.NINE),
        Card(Suit.HEARTS, Rank.SEVEN), Card(Suit.HEARTS, Rank.JACK),
    ]
    lead = [
        Card(Suit.HEARTS, Rank.KING), Card(Suit.HEARTS, Rank.KING),
        Card(Suit.HEARTS, Rank.QUEEN), Card(Suit.HEARTS, Rank.QUEEN),
    ]
    led, eng_led = oracle.classify(lead, ctx), classify_play(lead, ctx)
    assert oracle.signature(led) == ("tractor", 2, 2)
    good = hand[0:4]  # two pairs, no tractor available in hand
    assert oracle.follow_verdict(good, hand, led, "hearts", ctx).legal
    assert is_valid_follow(good, hand, eng_led, "hearts", ctx)
    bad = [hand[0], hand[2], hand[4], hand[5]]  # only one pair's worth
    verdict = oracle.follow_verdict(bad, hand, led, "hearts", ctx)
    assert (verdict.legal, verdict.rule) == (False, "R46")
    assert not is_valid_follow(bad, hand, eng_led, "hearts", ctx)


def test_r40_throw_beat_test_is_per_component_and_per_opponent() -> None:
    """R40/R41: one opponent must beat one component alone; D07 counts partners."""
    ctx = TrumpContext(trump_rank=Rank.TWO, trump_suit=Suit.SPADES)
    throw = [
        Card(Suit.HEARTS, Rank.ACE),
        Card(Suit.HEARTS, Rank.KING), Card(Suit.HEARTS, Rank.KING),
    ]
    # Nobody holds a higher heart single or a higher heart pair → valid.
    safe = _hands(
        p0=throw,
        p1=[Card(Suit.HEARTS, Rank.QUEEN)],
        p2=[Card(Suit.HEARTS, Rank.ACE)],          # single ace: beats no component
        p3=[Card(Suit.HEARTS, Rank.THREE)],
    )
    assert oracle.lead_verdict(throw, "p0", safe, ctx).outcome == "legal"
    assert validate_throw(throw, "p0", safe, ctx) is True

    # Split across two opponents — still valid (they may not combine).
    split = _hands(
        p0=throw,
        p1=[Card(Suit.HEARTS, Rank.ACE)],
        p2=[Card(Suit.HEARTS, Rank.ACE)],
        p3=[],
    )
    assert oracle.lead_verdict(throw, "p0", split, ctx).outcome == "legal"
    assert validate_throw(throw, "p0", split, ctx) is True

    # One partner holding the ace pair beats the K♥K♥ component (D07).
    beaten = _hands(
        p0=throw,
        p1=[],
        p2=[Card(Suit.HEARTS, Rank.ACE), Card(Suit.HEARTS, Rank.ACE)],
        p3=[],
    )
    verdict = oracle.lead_verdict(throw, "p0", beaten, ctx)
    assert verdict.outcome == "beatable_throw"
    assert [show(c) for _, c in verdict.beatable] == ["K♥ K♥"]
    assert validate_throw(throw, "p0", beaten, ctx) is False


def test_r7_no_trump_rank_card_cannot_follow_its_natural_suit() -> None:
    """R7's stated consequence, checked against the engine."""
    ctx = TrumpContext(trump_rank=Rank.TWO, trump_suit=None)
    hand = [Card(Suit.HEARTS, Rank.TWO), Card(Suit.CLUBS, Rank.NINE)]
    lead = [Card(Suit.HEARTS, Rank.KING)]
    led, eng_led = oracle.classify(lead, ctx), classify_play(lead, ctx)
    assert oracle.effective_suit(hand[0], ctx) == "trump"
    for card in hand:
        assert oracle.follow_verdict([card], hand, led, "hearts", ctx).legal
        assert is_valid_follow([card], hand, eng_led, "hearts", ctx)


def test_engine_reaches_playing_phase() -> None:
    """Guard: the cross-check is worthless if the driver never plays a trick."""
    driver = OracleDriver(0, "upgrade", max_rounds=1, deal_check_every=1000)
    driver.run()
    # Multi-card leads consume several cards per trick, so a round is 25 tricks
    # only when everything is led as singles.
    assert 10 <= driver.tricks_played <= 25
    assert all(not p.hand for p in driver.state.players)
    assert driver.state.phase in (GamePhase.ROUND_OVER, GamePhase.GAME_OVER)
    assert driver.checker.report.follow_states > 0
