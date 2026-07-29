# Phase 4 — Consolidated findings (2026-07-29)

Merges: rules-audit (`2026-07-29-rules-audit.md`), edge-case matrix
(`2026-07-29-edge-case-matrix.md`), fuzz harness (`tests/test_fuzz/`, FINDING-1/2),
legality oracle (`tests/test_fuzz/test_oracle.py`, 11,530 candidates, 0 non-scheduled
disagreements).

Baseline at consolidation: 740 passed + 5 xfailed; heavy `FUZZ=1` battery 174 passed in 69s;
oracle heavy 31 passed in 35s.

## (a) Clear bugs → fix waves

### Wave 1 — behavior-preserving (parallel, disjoint files)
| id | bug | fix | files |
|---|---|---|---|
| W1-1 | FINDING-2: `exchange_bottom` mutates before validating; rejected exchange leaves 33-card hand + empty bottom | validate bury list first, then mutate | `engine/engine.py` |
| W1-2 | F6: `FindFriendsStrategy._play_counts` is engine state outside `GameState`; snapshot/restore loses reveal progress | move counter onto `GameState`; clear in `start_dealing` | `modes/find_friends.py`, `models/game_state.py` |
| W1-3 | Audit §3.7 follow-ups: silent `continue` in `find_beatable_components`; `validate_state` misses >2-copy identities | raise instead of continue; add R1 multiplicity check | `engine/tricks.py`, `superuser/inspector.py` |
| W1-4 | Spec edits: F2 (R31 wording — 1v3 only when playable copies < ordinal), F3 (limitation #1 broadened: wrap detected only when wrapped positions are the only tier-0 pair positions), D20 scope (reject ordinal ≤0 too) | RULES.md text only | `docs/RULES.md` |

### Wave 2 — behavior-changing (after harness; SEQUENCED: F1 → D16/D17 → D18)
| id | change | decision | lockstep list |
|---|---|---|---|
| W2-1 | F1 (D22): tractor adjacency requires shared effective suit; `led_suit` derived from whole play, not `cards[0]` | D22 (new — consistent with D16 ruling; both sources demand single-suit plays) | `models/trump.py` + `models/groups.py`, oracle `tests/test_fuzz/oracle.py` (has suit-aware adjacency already — remove tolerance), pin tests |
| W2-2 | D16: reject mixed-suit throw leads (malformed lead, no penalty) | D16 | `engine/engine.py` or `tricks.py`, oracle tolerance removal, frontend `check_play` unaffected (server rejects), pin tests |
| W2-3 | D17: suit-pure eligibility to win; order-independent | D17 | `engine/tricks.py:_play_strength`, pin tests (2-card and 3-card NEW-3 cases) |
| W2-4 | D18: adjacency = no occupied position strictly between (AFTER W2-1) | D18 | `models/trump.py`, oracle legacy-ladder tolerance removal, pin tests (incl. audit §4's A♥A♥+2♥2♥ cases) |
| W2-5 | D20: reject friend ordinals outside 1..2 (incl. 0, negative) | D20 | `modes/find_friends.py`, pin tests |
| W2-6 | D21 + FINDING-1: clear `revealed_friends`/`friend_declarations` in `start_dealing`; fixes skipped mid-trick re-attribution for repeat friends; un-xfail FINDING-1 test | D21 | `engine/engine.py`, `tests/test_fuzz/test_invariants.py` (flip xfail), redaction invariant |
| W2-7 | F5/NEW-1: R47 tractor component becomes structural like R46 (pending interview) | Q8 | `engine/tricks.py:_is_valid_throw_follow`, oracle already structural — remove any tolerance, pin NEW-1 repro |

### Wave 3 — gap-pin tests (matrix Tier B/C + audit §6 zero-coverage)
Priority: B1 (R40/D08 tractor-beat branch), B2 (D07), B6 (D19), R31 self-friend, B4 penalty
accumulation + forced-pair, B5 (R83), B7 (R68 throw multiplier), B8 (FF × multiplier), B9 (R7
no-trump follow), then B3/B10/B11/B12, audit's 14 zero-coverage list, Tier C as time allows.
Skip cells fixed+pinned by wave 2.

## (b) Rule decisions → interview (Q8-Q11)
- **Q8 (F5/NEW-1):** R47 tractor-in-throw obligation: card-specific (current; forces the
  *weakest* on equal length — scan-order artifact) vs structural like R46. Recommend structural.
- **Q9 (NEW-4):** lone FF leader who defends successfully re-leads next round (R80 wraps to
  self; same trump rank family two rounds running). Keep literal R80 vs rotate. Recommend keep + document.
- **Q10 (audit §5):** leader can deliberately fail a throw to withhold their declared friend
  card (it returns to hand, no reveal). Intended (penalty = cost) vs forbid. Recommend intended + document.
- **Q11 (F4):** network layer silently upgrades a single bid to a pair when holding two.
  Document as network rule vs allow explicit single bids. Recommend document as intended.

## (c) Non-decisions recorded
- F1 fix (W2-1) is recorded as **D22** without interview: it is the classifier-level face of
  the already-ruled D16, and authority sources 1-3 agree (robertying "all winning plays must be
  one suit"; pagat "consecutive pairs within a suit").
- Refactor: **NOT NEEDED** per audit §7 (atomic rejections verified; rules logic already pure;
  seeding deterministic). Only F6 (W1-2) moves state.
