# Engine Verification Playbook

Process for rigorously verifying this game engine against its rules — hash out every rule
difference, enumerate edge cases, fuzz for rare-state bugs, and only then touch UI/polish.
Distilled from the Stratego engine verification campaign (2026-07-28, stratego repo,
`docs/reports/2026-07-28-*.md` there are the reference artifacts). A fresh session should be able
to execute this top to bottom.

## Operating rules (learned the hard way)

- **Main session orchestrates, reviews every diff, and runs the consolidated gate. Subagents do
  scoped work.** One fresh subagent per task, file-partitioned so parallel agents never share files.
- **Auditors are report-only.** Discovery agents (rules audit, coverage matrix) write reports under
  `docs/reports/`, never code. Prevents them "fixing" things mid-discovery and colliding with fixers.
- **Sequence behavior-changing fixes AFTER the fuzz harness lands.** The fuzzer pins current
  behavior; changing semantics under it mid-flight means it chases a moving target.
- **Every duplicated rule implementation updates in lockstep.** If a rule lives in the engine AND a
  bot/client mirror AND a test oracle, one change order covers all three, explicitly listed.
- **Review agent pairs for integration bugs.** Two individually-correct fixes can compose into a
  bug (Stratego: server kicks stale socket + client auto-reconnects = infinite kick loop). After
  parallel fixes land, reason about their interaction before committing.
- **Mid-flight red tests are expected.** With TDD agents working in parallel, the tree has
  red-phase tests. Before diagnosing a "regression", check which agent owns the file and verify
  against clean HEAD (`git stash` trick).
- **Fixtures must not hard-code derived geometry.** Tests that assume "piece X is at square Y
  because the default setup puts it there" break when the setup is fixed. Clear/build by square,
  not by assumed identity. Audit for overloaded sentinels (Stratego: `pos === null` meant both
  "unplaced" and "captured" — a new feature silently conflated them).
- Agents report: exact commands run, exact results, red-then-green confirmation, anything needing
  an off-sandbox run (port binding, subprocess spawning). No commits by agents — main session
  reviews, gates, commits.

## Phase 0 — Ground

Read CLAUDE.md, CURRENT_STATE.md, the engine source layout, and run the full existing test suite
to a known-green (or known-red) baseline. Record the gate command set (here: pytest; note which
suites need network/timeouts). Map where rules logic lives vs. UI/network — engine verification
scopes to the engine; frontend/network are out of scope until the engine is trusted.

## Phase 1 — Authoritative rules spec FIRST (Shengji-specific)

Stratego had an official Hasbro PDF to audit against. Shengji does not — it's a variant family, so
**the spec must be written before it can be audited against**:

1. Collect what's already decided: Jeffrey's on-record interview decisions (identity pairs, 8×
   kitty cap, throw penalty — see auto-memory + repo docs), plus whatever rules docs exist in-repo.
2. Use a reference source (e.g. pagat.com Shengji/80-points page) to enumerate the FULL rule
   surface: dealing, trump declaration/overriding, kitty, lead/follow legality (singles, pairs,
   tractors, throws), trick winning, point capture, kitty multiplier at endgame, level
   advancement, and every regional-variant fork.
3. For every fork the current engine takes a position on: record it as a numbered **documented
   decision**. For every fork that's ambiguous or Jeffrey hasn't ruled on: **interview via
   AskUserQuestion** (batch the questions, recommend a default). Decisions get recorded in the
   spec BEFORE any code changes — every later fix cites its decision number.

Output: `docs/RULES.md` (or extend an existing spec) — numbered normative rules + numbered
documented decisions. This is the audit target.

## Phase 2 — Parallel report-only audits

Launch together (both read-only):

- **Adversarial spec-vs-engine audit**: fresh-eyes agent traces actual code paths (never trusts
  comments/test names) for every numbered rule; empirical probes against the real engine for
  anything uncertain; verdict per rule: CONFORMS (file:line) / DEVIATION (concrete repro
  scenario) / AMBIGUOUS-DOCUMENTED / UNVERIFIABLE. Also flags rules with zero test coverage.
  → `docs/reports/YYYY-MM-DD-rules-audit.md`
- **Edge-case coverage matrix**: enumerate the edge-case space per rule dimension from first
  principles (for Shengji: follow-suit legality per combination type, tractor boundary shapes,
  throw beat/penalty resolution, trump-declaration races, kitty scoring corners, point counting,
  level-up boundaries), then map every cell to an existing test **by reading the test body, not
  the name**. Verdict per cell: COVERED / PARTIAL / GAP; end with a prioritized gap list where
  each gap was empirically probed against the engine (so proposed tests pin verified behavior,
  clearly separated from suspected bugs).
  → `docs/reports/YYYY-MM-DD-edge-case-matrix.md`

## Phase 3 — Fuzz harness (parallel with Phase 2; own test dir only)

Python analog of the Stratego fast-check harness, using **hypothesis** + seeded random playouts:

1. **Per-action invariant battery**: play full seeded random-legal games; after EVERY action
   assert: card conservation (multiset of all zones == full deck(s)), zone exclusivity (a card in
   exactly one hand/trick/kitty/captured pile), turn/phase coherence, points monotone and
   consistent with captured tricks, no action accepted out of phase, score/level bookkeeping
   consistent at round end.
2. **Independent legality oracle**: re-derive follow-suit/combination legality from RULES.md in
   the test file, structurally different from the engine's implementation; cross-check the
   engine's accept/reject decision on every candidate play across random reachable states.
   Disagreement = the bug class everything else misses. (In Stratego this found nothing because
   the engine was clean; the flag-capture asymmetry was found by the invariant battery instead —
   run both.)
3. **Adversarial action fuzz**: malformed/out-of-phase/junk actions against reachable mid-game
   states — engine must reject cleanly without mutation or crash.
4. Light mode runs in the default suite (seconds); heavy mode behind an env gate
   (e.g. `FUZZ=1`, high example counts, long games). Deterministic seeds, reproducible failures.

## Phase 4 — Consolidate findings → decisions interview

Merge audit + matrix + fuzz findings. Separate into: (a) clear bugs — just fix; (b) genuine rule
decisions — AskUserQuestion batch with recommendations; (c) coverage gaps — pin tests. Record new
decisions in RULES.md before implementing.

## Phase 5 — Fix waves

- Wave 1 (parallel, disjoint files): behavior-preserving bugfixes and additive features.
- Wave 2 (after fuzz harness merged): behavior-changing rule fixes, one agent per coherent change,
  with the lockstep list (engine + mirrors + oracle + flipped pin tests) in the brief.
- Wave 3: gap-pin tests from the matrix (skip cells already covered by wave-2 work).

## Phase 6 — Gate and commit

Full suite incl. heavy fuzz once, plus any E2E. Commit in logical units citing decision numbers.
Update CURRENT_STATE.md.

## Refactor assessment (do NOT refactor first)

The engine was written under an older Claude Code — assess during Phase 2, refactor only if the
audit shows structural cost. The properties that made Stratego cheap to verify, in priority order:

1. **Pure reducer core**: `(state, action) → (state', events) | rejection`, total (never throws),
   no I/O. If Shengji's engine mutates in place or tangles network/UI into rules code, THIS is
   the refactor worth doing — it's what makes the oracle + invariant harness possible.
2. **Redacted per-player views** derived from canonical state (no player sees hidden info;
   redaction is testable as a property).
3. **Deterministic seeding** end-to-end (deal, shuffle) so any fuzz failure replays exactly.

If the engine already has these, refactor is unnecessary regardless of code age. If refactoring,
do it AFTER Phase 3 exists — the fuzz harness is the safety net that makes refactoring safe.
