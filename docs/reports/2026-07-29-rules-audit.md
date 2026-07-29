# Adversarial rules audit — engine vs `docs/RULES.md`

**Date:** 2026-07-29 · **Scope:** R1–R84, D01–D21 · **Method:** code trace + empirical probes
against the real engine · **Status:** report only, no code or test changes.

Baseline at time of audit: `pytest tests/` → **721 passed, 5 xfailed**.

## How to read this

Every rule was traced to the code path the spec cites, and every cited `file:line` was checked
for truthfulness *and completeness* (i.e. whether another path can reach the same behavior and
bypass the citation). Anything not decidable by reading was settled with a throwaway probe run
against the real engine outside the repo. Probe transcripts are reproduced inline; the probe
scripts themselves were scratch files and are not checked in.

Verdicts:

| verdict | meaning |
|---|---|
| **CONFORMS** | engine matches the rule as written, verified at the cited path |
| **DEVIATION** | engine and spec disagree, or the spec contradicts its own authority order |
| **DEVIATION-SCHEDULED** | D16–D18 / D20 / D21 — known, ruled, pending Phase 5 |
| **AMBIGUOUS** | the spec does not determine the answer |
| **UNVERIFIABLE** | not decidable against the engine alone (network/display layer) |

---

## 1. Summary

| | count |
|---|---|
| CONFORMS | 71 |
| DEVIATION (not scheduled) | 4 |
| DEVIATION-SCHEDULED | 5 |
| AMBIGUOUS | 2 |
| UNVERIFIABLE | 2 |
| **total rules** | **84** |

D01–D15 all hold as described (each is verified via its owning rule). D16–D18, D20, D21 were
checked only for *ground-truth accuracy* as instructed; **all five descriptions of current
behavior in the "Resolved forks" section are accurate**, with two corrections to their scope
noted in §4. D19 was audited normally and conforms.

The headline result: **follow-legality (R42–R47), trick-winning (R51–R56), scoring (R59–R66),
throw penalty (R71–R75) and round transitions (R76–R84) are all clean.** A 170k-play
differential test against an independently written oracle found zero disagreements in the
follow logic, and a 25-trick full-round replay showed zero point-attribution drift. The real
finding is upstream of all of that, in play *classification* (§3.1).

## 2. Verdict table

### Setup (R1–R8)

| rule | verdict | evidence |
|---|---|---|
| R1 | CONFORMS | `models/deck.py:15-23` builds 2 × (4×13 + SJ + BJ) = 108; `models/card.py:66-70` enforces joker suit↔rank pairing |
| R2 | CONFORMS | `models/deck.py:8` (`NUM_PLAYERS = 4`); `engine/engine.py:117-125` advances `(idx+1) % 4` |
| R3 | CONFORMS | `models/deck.py:10-12` — `HAND_SIZE = (108-8)//4 = 25` |
| R4 | CONFORMS | `models/card.py:54-58, 72-74`; deck total verified = 200 |
| R5 | CONFORMS | `models/player.py:29-41`, 13-entry `RANK_ORDER` |
| R6 | CONFORMS | `models/trump.py:48-67` — all six tiers probed |
| R7 | CONFORMS | `models/trump.py:69-83`; the no-trump consequence (trump-rank card cannot follow its natural suit) verified |
| R8 | DEVIATION-SCHEDULED (D18) **+ see F1** | `models/trump.py:85-118`. The cited predicate is truthful, but tier 0 is shared by all three non-trump suits, so `are_tractor_adjacent(3♠, 4♦)` is `True` |

### Dealing & bidding (R9–R22)

| rule | verdict | evidence |
|---|---|---|
| R9 | CONFORMS | `models/deck.py:41-53` — bottom is the last 8 post-shuffle, fixed before any deal |
| R10 | CONFORMS | probed: leader `p2` → recipients `p3, p0, p1, p2, p3` (`engine/engine.py:208-216`) |
| R11 | CONFORMS | `network/room.py:104` seeds the creator as leader; `engine/engine.py:409-411` replaces in round 1 |
| R12 | CONFORMS | `engine/engine.py:338` |
| R13 | CONFORMS | probed: after a 2♠2♠ bid the hand still holds both 2♠ |
| R14 | CONFORMS | probed all shapes — single joker rejected, non-trump-rank single rejected, 2♠+2♦ rejected as a pair (#50), suited single/pair and SJ/BJ pairs accepted |
| R15 | CONFORMS | `engine/engine.py:228-245`; ladder confirmed by the override probe |
| R16 | CONFORMS | probed: equal strength never overrides (single vs single, pair vs pair, own pair vs own pair); own single → own pair accepted |
| R17 | UNVERIFIABLE (network) | `network/handler.py:302-303, 336-350` implement it as documented. **See F4** for a network-layer restriction not in the spec |
| R18 | CONFORMS | probed: round 2, `p1` wins the bid, `round_leader_id` stays `p2`, trump becomes ♠ with rank from `p2` |
| R19 | CONFORMS | probed: all-pass → hands emptied, phase `dealing`, same leader `p2`, fresh 100-card draw pile, `round_number` unchanged |
| R20 | CONFORMS | `engine/engine.py:414-422` |
| R21 | CONFORMS | `modes/upgrade.py:28-42`; parity re-derived every round |
| R22 | CONFORMS | `modes/find_friends.py:33-42` — probed, leader alone defends |

### Bottom (R23–R27)

| rule | verdict | evidence |
|---|---|---|
| R23 | CONFORMS | `engine/engine.py:451-460`; FF ordering (declare → exchange) verified |
| R24 | CONFORMS | `engine/engine.py:461-490`, hand returns to 25 (assert at :487) |
| R25 | CONFORMS | probed: the two shown bid cards were buried successfully |
| R26 | CONFORMS | `models/game_state.py:136-139`; `engine/engine.py:612` passes hands only, so buried cards never enter the throw check |
| R27 | CONFORMS | `engine/engine.py:492-494` |

### Find Friends (R28–R34)

| rule | verdict | evidence |
|---|---|---|
| R28 | CONFORMS | `engine/engine.py:521-532`, `modes/find_friends.py:64-70` |
| R29 | DEVIATION-SCHEDULED (D20) | ordinal is unvalidated — see §4 |
| R30 | CONFORMS | `modes/find_friends.py:77-90` — joker, trump-rank and trump-suit bans all fire |
| R31 | **DEVIATION — F2** | see §3.2 |
| R32 | DEVIATION-SCHEDULED (D21) | reveal logic itself is correct; the cross-round bookkeeping leak is the scheduled part |
| R33 | CONFORMS | probed: attacker captured K♥ (10 pts), `attacking_points` = 10; on revealing as a friend mid-trick it dropped to 0 **immediately**, not at the trick boundary |
| R34 | CONFORMS | `engine/engine.py:765-766` reads `is_defending` before `on_round_end` flips it |

### Lead legality (R35–R41)

| rule | verdict | evidence |
|---|---|---|
| R35 | CONFORMS | probed: out-of-turn play raises with state unchanged |
| R36 | CONFORMS | `engine/tricks.py:253-255` |
| R37 | **AMBIGUOUS — F1** | the spec's Tractor definition inherits R8's silence on suit; see §3.1 |
| R38 | **DEVIATION — F1** | a multi-suit multi-component lead can classify as `Tractor` and never reach R39–R41; see §3.1 |
| R39 | DEVIATION-SCHEDULED (D16) | mixed-suit throws accepted; `led_suit` from `cards[0]` |
| R40 | CONFORMS | probed per-component and per-opponent: two different opponents beating two different components yields 2 beatable entries (no combining); pair components require *k identical* higher cards (#50); D08 longer-tractor beat confirmed |
| R41 | CONFORMS | probed both D07 halves: with the beating A♠ in the **partner's** hand (Upgrade seats 0/2) the component is still marked beatable, and likewise when held by a not-yet-revealed Find Friends friend |

### Follow legality (R42–R50)

All verified twice: by code trace, and by a differential test against an oracle written from
`docs/RULES.md` alone. **169,861 candidate plays** across 3 trump contexts (♥-trump, no-trump,
♠-trump rank 10), exhaustively enumerating every distinct play a random hand could make against
a random lead. **Zero disagreements.** The same run also checked four standalone properties and
found no violations: every accepted play contained exactly `min(s, n)` led-suit cards (R42);
every short follow dumped its entire led-suit holding (R43); no led-suit single was ever
rejected on a single lead (R44); and no unpaired play was accepted when the hand held a
qualifying pair (R45). A **liveness** check confirmed at least one legal follow always exists,
and every `get_legal_plays` output was accepted by `is_valid_follow`.

| rule | verdict | evidence |
|---|---|---|
| R42 | CONFORMS | `engine/tricks.py:264-279`; property-checked |
| R43 | CONFORMS | `engine/tricks.py:273-275`; property-checked |
| R44 | CONFORMS | `engine/tricks.py:282-283`; property-checked |
| R45 | CONFORMS | `engine/tricks.py:285-299`; property-checked |
| R46 | CONFORMS | `engine/tricks.py:311-367`; probed that a hand with two 4-card tractors may play *either* one, but not two non-adjacent pairs |
| R47 | CONFORMS (**see F5**) | `engine/tricks.py:370-472`; probed that the tractor component obligation is card-specific as the rule states — only the greedily-claimed tractor is accepted |
| R48 | CONFORMS | no must-beat check exists anywhere in `engine/tricks.py:228-308`; the oracle run accepted low cards throughout |
| R49 | CONFORMS | off-suit fill shape is unconstrained (`engine/tricks.py:273-275`) |
| R50 | CONFORMS | probed: an illegal follow raises and leaves hand, trick and turn pointer byte-identical |

### Trick winning (R51–R58)

| rule | verdict | evidence |
|---|---|---|
| R51 | DEVIATION-SCHEDULED (D17) | `engine/tricks.py:783-785`; order dependence and the trump-lead hole both reproduced — see §4 |
| R52 | CONFORMS | every branch probed — degraded 2-singles lose to a pair lead even holding the higher ace; 2♠+2♦ is not a pair; a trump pair wins; loose pairs lose to a tractor lead; a trump tractor wins; D10 component matching works (pair+single beats a pair+single throw, 3 singles do not) |
| R53 | CONFORMS | `engine/tricks.py:792` + `models/trump.py:48-67` |
| R54 | CONFORMS | `engine/tricks.py:792` (`max` over the play) |
| R55 | CONFORMS | `engine/tricks.py:757-768` |
| R56 | CONFORMS | probed: leader wins a 2♠/2♦ tier-2 tie; between two equal K♠ plays the earlier seat wins |
| R57 | CONFORMS | `engine/engine.py:690-691` — all 4 plays go to the winner's pile |
| R58 | CONFORMS | `engine/engine.py:701-712` |

### Scoring (R59–R66)

| rule | verdict | evidence |
|---|---|---|
| R59 | CONFORMS | `engine/engine.py:98-115` |
| R60 | CONFORMS | probed a full seeded 25-trick round: the live total matched a from-scratch recount at **every** trick boundary (0 drift events); round total reconciled to 190 trick points + 10 bottom points = 200 |
| R61 | CONFORMS | buried points enter only via `engine/scoring.py:99-106` |
| R62 | CONFORMS | probed: base 10 + 8 × 15 = 130 |
| R63 | CONFORMS | `modes/upgrade.py:28-42` |
| R64 | CONFORMS | follows from R32/R34, both verified |
| R65 | CONFORMS | `engine/engine.py:787-793` — penalties applied after `count_attacking_points` |
| R66 | CONFORMS | probed: base 5 with a 200 attacker penalty → final 0, `throw_penalty_adjustment` −200 (clamp is applied *after* summing all adjustments, as the rule requires) |

### Bottom multiplier (R67–R70)

| rule | verdict | evidence |
|---|---|---|
| R67 | CONFORMS | probed: defender winning the last trick → bottom contributes 0 |
| R68 | CONFORMS | probed the full ladder on a 15-point bottom: single → 40, pair → 70, 4-tractor → 130, 6-tractor → 130 (cap holds), throw(pair+single) → 70 (largest component wins) |
| R69 | CONFORMS | `engine/scoring.py:100-106` — guarded on `bottom_pts > 0` |
| R70 | UNVERIFIABLE (network) | implemented at `network/handler.py:216-222`, **not** in `to_player_view` (which gates `show_bottom` on `BOTTOM_EXCHANGE`). An engine-only oracle cannot exercise this rule — same category as R17 |

### Throw penalty (R71–R75)

| rule | verdict | evidence |
|---|---|---|
| R71 | CONFORMS | probed: 4-card throw not rejected; remainder `[K♠, K♠, 4♠]` stayed in hand |
| R72 | CONFORMS | probed the tie-break directly — with beatable components `{4♠4♠, 3♠, K♠}` the engine forced `[3♠]`: fewest cards first, then weakest |
| R73 | CONFORMS | probed: 4-card attempt → penalty 40; 2-card attempt → 20. Accumulation is `+=` at `engine/engine.py:625-627` |
| R74 | CONFORMS | `engine/engine.py:787-792` reads `attacker_ids` derived from end-of-round `is_defending` |
| R75 | CONFORMS | `engine/engine.py:180` |

### Rounds & game over (R76–R84)

| rule | verdict | evidence |
|---|---|---|
| R76 | CONFORMS | every band boundary probed: 0/19→D+4, 20/39→D+3, 40/59→D+2, 60/79→D+1, 80/99→A+0, 100/119→A+1, 120/139→A+2, 140/200/320→A+3 |
| R77 | CONFORMS | probed FF: only the leader and the revealed friend advanced (2→6), the two attackers stayed at 2 |
| R78 | CONFORMS | probed: K defenders winning +4 land on A, not past it |
| R79 | CONFORMS | probed: defenders win → teams unchanged; attackers win → roles swapped |
| R80 | CONFORMS | probed both modes: Upgrade defenders win → `p2` (leader+2); attackers win → `p1` (leader+1); FF with leader `p0` and friend `p3` defending → next leader `p3` |
| R81 | CONFORMS | follows from R12 + R80 |
| R82 | CONFORMS | probed: K defenders winning advance to A with `game_over=False` (advancing *into* Ace does not end it); Ace defenders winning → `game_over=True` |
| R83 | CONFORMS | probed: the 80-point band returns `("attacking", 0)` with `game_over=False` |
| R84 | CONFORMS (D19) | probed: leader at level 5 defending successfully alongside an Ace-level revealed friend → `game_over=True`, on the friend's level |

---

## 3. Findings

### 3.1 F1 — CRITICAL: cross-suit plays classify as a Tractor, bypassing throw validation

**Rules:** R8, R37, R38 (and it defeats the planned D16 fix)
**Code:** `models/trump.py:100-107`, `models/groups.py:116-152, 189-195`

Tier 0 in `card_order` is *(0, rank_pos)* for every non-trump suit — the suit is not part of the
key. `are_tractor_adjacent` compares only `(tier, pos)`, so two pairs in **different suits** at
consecutive rank positions are adjacent, and `find_tractors` builds a tractor from them.

Repro (♥ trump, rank 2):

```
classify_play([3♠, 3♠, 4♦, 4♦])            -> Tractor(multiplicity=2, length=2)
classify_play([3♠, 3♠, 4♦, 4♦, 5♣, 5♣])    -> Tractor(multiplicity=2, length=3)
classify_play([K♠, K♠, A♣, A♣])            -> Tractor(multiplicity=2, length=2)
classify_play([A♠, A♠, 3♣, 3♣])            -> Tractor(multiplicity=2, length=2)   # via the wrap
```

This is not merely a classifier curiosity — it reaches the engine and changes play:

```
p0 leads [3♠, 3♠, 4♦, 4♦]
  -> accepted, throw_failed = False
  -> led_format = Tractor(2,2), led_suit = "spades"
p0 leads [4♦, 4♦, 3♠, 3♠]      (same four cards)
  -> led_suit = "diamonds"
```

Three consequences, in order of severity:

1. **Throw validation is skipped entirely.** `play_cards` only runs `find_beatable_components`
   when `isinstance(led_fmt, Throw)` (`engine/engine.py:611`). A mixed-suit play that classifies
   as `Tractor` never faces the R40 unbeatability test and can never incur the R71–R75 penalty —
   even though a leader holding two junk pairs in two suits is exactly the case R39 exists to
   police. In the probe above, `p1` held `A♠ K♠ Q♠ J♠` and `p2` held `A♦ K♦ Q♦ J♦`; both
   components were trivially beatable and nothing happened.
2. **It defeats D16.** D16 is specified as "a **throw** lead whose components do not all share
   one effective suit is rejected". Because this play is a `Tractor`, not a `Throw`, a D16 fix
   written to that wording will not catch it. The suit-purity check has to live in
   `classify_play` / `are_tractor_adjacent`, not in the throw branch.
3. **`led_suit` is order-dependent** for these plays, the same `cards[0]` problem D16 was meant
   to remove — so the D16 fix will not fully remove it either.

Both authority sources rule against the current behavior: robertying, "All winning plays must be
one suit (original or trump)"; pagat describes a tractor as consecutive pairs *within a suit*.
R8 and R37 are silent on suit, which is why the verdicts above are AMBIGUOUS — the spec does not
currently forbid this, and it should.

**Suggested fix direction (for Phase 4/5, not applied):** make suit part of tractor adjacency —
two cards are adjacent only if they share an effective suit — and derive `led_suit` from the
whole play rather than `cards[0]`. Note this interacts with D18: implementing "no occupied
position strictly between" *without* a suit constraint would make it worse, because in no-trump
`A♠A♠ + 2♥2♥` would become adjacent (tier 0 pos 11 → tier 2) and produce a tractor spanning a
non-trump suit and trump. **D18 must not be implemented before F1 is fixed.**

### 3.2 F2 — R31 overstates the "friend in the bottom" outcome

**Rule:** R31 · **Code:** `modes/find_friends.py:92-126` (engine is correct; the spec is not)

R31 says the declared card "may turn out to be in the bottom … In either case no other player can
ever become a friend, and the leader plays 1-versus-3 for the whole round." With two decks there
are two copies of every non-joker card, so burying one copy leaves the other live.

Repro (FF, leader `p0`, declaration `A♠` ordinal 1, one `A♠` in the bottom, the other in `p1`'s
hand): `p1` plays their `A♠` on trick 2 → `revealed_friends = {'p1'}`, `p1` flips to defending.
Not a 1v3 round.

The engine is doing the right thing. R31 needs restating: the round is 1v3 only when the number
of *playable* copies of the declared card is smaller than the ordinal — i.e. both copies buried,
or one copy buried with ordinal 2, or the leader holding/burying copies such that the ordinal is
unreachable. This matters because R31 is cited as an on-record interview decision, so the fix is
to the wording, not the behavior.

### 3.3 F3 — a 2-position wrap tractor is destroyed by an unrelated pair

**Rules:** R8, R37 · **Code:** `models/groups.py:131-152` · extends known limitation #1

Known limitation #1 documents that 3+-position wraps split into a tractor plus a pair. The
failure is broader than that: adding a **non-adjacent** pair between the wrap endpoints in sort
order destroys the wrap tractor completely.

```
♥ trump, rank 2:
find_tractors([A♠, A♠, 3♠, 3♠])             -> [[3♠, 3♠, A♠, A♠]]      # wrap detected
find_tractors([A♠, A♠, 3♠, 3♠, 8♠, 8♠])     -> []                       # wrap gone
classify_play([A♠, A♠, 3♠, 3♠, 8♠, 8♠])     -> Throw(IG(2), IG(2), IG(2))
```

`find_tractors` scans sorted positions linearly, so it can only observe the 0↔11 wrap when
position 0 is the immediate predecessor of position 11 in the sorted list. `8♠8♠` at position 5
sits between them and breaks the run.

Consequence: whether a component is a tractor or two loose pairs depends on **unrelated cards in
the same play**, which changes the R40 unbeatability test (a tractor component is beaten by a
different card set than two independent pairs), the R47 follow obligations imposed on the other
three players, and the R68 bottom multiplier (largest component 2 → ×4 instead of 4 → ×8).

Currently the spec's limitation #1 understates this; it should say the wrap is detected **only**
when the two wrapped positions are the sole pair-positions in tier 0.

### 3.4 F4 — the network layer silently upgrades a single bid to a pair

**Rule:** R17 (and R14/R15 by consequence) · **Code:** `network/handler.py:307-320`

The `bid` action does not accept a card list — it accepts a suit, then chooses the cards:

```python
count = engine._player(player_id).hand.count(tc)
if count >= 2:   bid_cards = [tc, tc]
elif count >= 1: bid_cards = [tc]
```

So a player holding two trump-rank cards of a suit **cannot place a single bid** through the
network layer; it is always upgraded to a pair. The engine permits the single (R14 allows it and
`place_bid` would accept it). This is a real rule the spec does not record, and it is invisible
to any engine-only oracle. It is arguably benign — a pair is strictly better for the bidder —
but it means the reachable bid space in a real game is smaller than R14/R15 describe. It should
either be documented as a network-layer rule or removed.

Same section, a non-issue worth recording so it is not re-derived: the joker branch builds
`[jc, jc]` without checking the hand, but `place_bid`'s possession check (`engine/engine.py:344-350`)
removes both copies from a hand copy and rejects if the player holds only one. Correct.

### 3.5 F5 — R46 and R47 impose contradictory obligations for the same structure

**Rules:** R46 vs R47 · **Code:** `engine/tricks.py:311-339` vs `engine/tricks.py:398-427`

Both rules are implemented as written, so this is not a deviation — but the spec encodes an
inconsistency worth a decision. For a **tractor lead** the obligation is structural: the follower
may satisfy it with any qualifying tractor. For a **tractor component inside a throw lead** the
obligation is card-specific: only the tractor the greedy algorithm happens to claim is accepted.

Probed with `hand = 9♠9♠ 10♠10♠ Q♠Q♠ K♠K♠ 7♠` (two 4-card tractors):

| lead | play `9-10 tractor` | play `Q-K tractor` |
|---|---|---|
| `Tractor(2,2)` (R46) | accepted | accepted |
| `Throw(Tractor(2,2), Single)` (R47) | accepted | **rejected** |

The same hand, the same two tractors, and the follower's freedom depends on whether the leader
appended a single. R47's own source note calls this deliberate ("multiple tractors in one suit is
extremely rare"), but the probe shows it is constructible, and the asymmetry is the kind of thing
a player would report as a bug.

### 3.6 F6 — `_play_counts` is engine state living outside `GameState`

**Rule:** R32 · **Code:** `modes/find_friends.py:27, 39, 109-111`

The per-identity play counter that drives friend reveals is an attribute of the
`FindFriendsStrategy` **object**, not a field of `GameState`. It is cleared in `assign_teams`,
not in `start_dealing`, and it is not serialized by `to_superuser_view`.

Consequences for verification specifically: a `GameState` snapshot/restore does not round-trip
the reveal state, so any replay, save/load, or state-diffing property in the fuzz harness will
silently diverge on Find Friends rounds mid-way through a declared card's two copies. It also
means the same strategy instance must be reused for the whole game — `network/handler.py:171`
constructs a fresh `GameEngine` **and a fresh strategy** in `start_and_deal` each round, which is
fine today only because the counter is meant to reset per round anyway. This is the one place
where "the engine's state is `GameState`" is not true, and it should move onto `GameState` before
the harness starts asserting state-round-trip properties.

### 3.7 Spot-check of suspected bug #7 — `_assign_throw_components` silent pass

**Result: not reachable through legal play. Reachable through the superuser mutator.**

I searched for it rather than reasoning about it. Restricted to legal card multisets (≤ 2 copies
of any identity, since the game has exactly 2 decks), across four trump contexts, using a
pair-biased generator plus exhaustive enumeration of all 2-pair, 3-pair and 4-pair combinations:

```
legal throws examined: 1,265,387  (277,241 with >= 1 Tractor component)
  component assigned ZERO cards ......... 0
  component assigned WRONG card count ... 0
  assignment does not partition the play  0
```

An earlier unconstrained run (600k random plays) also found nothing; a deliberately *illegal*
generator that allowed 3 copies of an identity produced 9,362 hits immediately. So the guard
holding the bug closed is the two-deck multiplicity limit, not anything in the algorithm.

That limit is not enforced everywhere. `superuser/mutator.set_hand` writes any hand and
`validate_state` returns **no warning** for three copies of one card:

```
mutator.set_hand(state, "p0", [10♠, 10♠, 10♠, 8♠, 8♠])   -> warnings: []
classify_play([8♠,8♠,10♠,10♠,10♠])  -> Throw(IdenticalGroup(2), IdenticalGroup(3))
_assign_throw_components(...)       -> [(IG(2), [10♠,10♠]), (IG(3), [])]
find_beatable_components(... opponent holds A♠A♠A♠ ...)
                                    -> only the IG(2) reported; the IG(3) beat check was skipped
```

So the accurate statement for the spec is: the silent-pass path is unreachable in play, and the
invariant that closes it — "no identity appears more than twice" (R1) — is not checked by
`superuser/inspector.validate_state`. Two cheap follow-ups, both out of scope here: turn the
`continue` at `engine/tricks.py:538-540` into a raise, and add the multiplicity check to
`validate_state`.

## 4. Ground-truth check on the scheduled items (D16–D18, D20, D21)

All five descriptions in "Resolved forks" are accurate. Reproductions, plus two scope corrections.

**D16 / Q1 (R38, R39)** — confirmed. Mixed-suit throws are accepted and `led_suit` comes from
`cards[0]`; leading `[A♠, K♠]` classifies as `Throw(Single, Single)` and both components are
validated against their own suits independently.
*Scope correction:* the fix as worded will not cover the mixed-suit plays that classify as
`Tractor` — see **F1**.

**D17 / Q2 (R51)** — confirmed exactly as written:

```
♥ trump; p0 leads [A♠, K♠] (Throw of two singles); p1 is void in spades
  p1 plays [3♥, 4♦]  -> p1 WINS
  p1 plays [4♦, 3♥]  -> p0 wins       (same two cards)
```

The trump-lead hole is also confirmed: `_play_strength([3♦], led_suit="trump", …)` returns
`(0, 0)` rather than `None`, i.e. an off-suit play is marked *eligible* on a trump lead. Harmless
today — the probe confirms the trump lead still wins — because the trump play always outranks it.

**D18 / Q3 (R8)** — confirmed: at rank 2, `2♥2♥ + SJ SJ` is a `Throw` in no-trump but a `Tractor`
with ♥ trump; `SJ SJ + BJ BJ` is a `Tractor` in both.
*Scope note:* two further gaps in the same ladder that the D18 wording will also change, and
which are not currently listed — with ♥ trump, `A♥A♥ + 2♥2♥` is a `Throw` (tier 1 → tier 3 skips
the tier-2 rung), and in no-trump `A♥A♥ + 2♥2♥` is likewise a `Throw` (tier 0 → tier 2). Both
become tractors under "no occupied position strictly between", which is presumably intended. But
see **F1** — without a suit constraint the same change also makes `A♠A♠ + 2♥2♥` a tractor in
no-trump, which is not intended. **Sequence F1 before D18.**

**D20 / Q5 (R29)** — confirmed, and slightly broader than described. The spec says ordinals
outside 1..2 are accepted; in fact **no** validation exists at all:

```
ordinal = 5   -> ACCEPTED
ordinal = 0   -> ACCEPTED
ordinal = -1  -> ACCEPTED
ordinal = 99  -> ACCEPTED
```

Zero and negative ordinals should be in the rejection set too.

**D21 / Q6 (R32)** — confirmed. After `start_dealing`, `revealed_friends` still holds `{'p2'}`
and `friend_declarations` still holds the previous round's resolved declaration; both appear in
`to_player_view("p1")`, including `resolved_player_id`. (The existing fuzz suite already pins
this as "finding 1" — `tests/test_fuzz/test_invariants.py:302`.)

**D19 / Q4 (R84)** — audited normally, CONFORMS. Probed: leader at level 5 defends successfully
with a revealed friend at Ace → `game_over = True`, decided by the friend's level.

**D07 (Q7)** — confirmed at both halves; see R41.

## 5. Cross-rule interactions checked

The interactions named in the audit brief, each probed end to end:

| interaction | result |
|---|---|
| Forced throw component (R72) as the **last trick** → which play sets the bottom multiplier (R68)? | No interaction bug. The forced component is an ordinary lead; `last_winning_play` tracks the actual winner of the actual final trick. Probed a 3-card attempt forced to `[3♠]`, played out to round end: multiplier came from the real final trick's winning play (`[Q♠]`, single → ×2), and the 30-point penalty was applied on top → 80. Card counts stayed in sync because every player still plays the reduced count. |
| Bid cards shown then buried (R13 + R25) | Legal and works. Bid `2♠2♠`, both stayed in hand, both were buried in the exchange, hand returned to 25. |
| Friend card in a forced-throw **remainder** | Works, and is strategically load-bearing. FF leader `p1` declared `K♠` and attempted `[3♠, K♠]`; forced down to `[3♠]`, `K♠` stayed in hand, no reveal fired. A leader can therefore use a failed throw to withhold their own declared friend card — worth recording as intended or not. |
| Trump-rank tractor adjacency (R8) vs #50 identity pairs | Correct. `2♠2♠ + 2♦2♦` (both tier 2, one position) → `Throw` of two pairs, not a tractor. `2♠2♠ + 2♥2♥` (tier 2 → tier 3) → `Tractor`. `2♠ + 2♦` → `Throw` of two singles. |
| Throw penalty × Find Friends team flip (R74) | Attribution reads `is_defending` at round end (`engine/engine.py:765, 788-792`), after every reveal. Already pinned by `tests/test_engine/test_throw_penalty.py:207`. |
| Penalty clamp ordering (R65/R66/R74) | Correct: all adjustments summed first, clamp applied once to the total (`engine/engine.py:793`), not per-thrower. |

## 6. Rules with zero test coverage

"Zero coverage" means no test asserts the rule's distinguishing outcome. Tests that merely
traverse the code path do not count; test bodies were read.

**Zero coverage (14):**

- **R11** — round-1 placeholder leader. `network/room.py:104` seeds it; no test asserts that the
  placeholder only fixes the trump rank and deal start and is then replaced.
- **R31** — self-friend / friend-in-bottom → 1v3. `tests/test_integration/test_find_friends_flow.py:174`
  covers the *both copies buried* case only; nothing covers the leader declaring a card they hold
  and becoming their own friend. (This gap is why F2 went unnoticed.)
- **R41 / D07** — no test places the beating card in the **thrower's partner's** hand with teams
  assigned. `tests/test_engine/test_tricks.py:390-470` are pure `validate_throw` unit tests with
  no team notion, so the on-record D07 ruling is unpinned.
- **R48** — no test asserts a follower may decline to win a trick they could win.
- **R49** — no test asserts a short follower may break their own pair or trump tractor for fill.
- **R61** — no test asserts that points in buried cards reach no one except via R67–R70.
- **R62** — no test asserts the >200 ceiling (`200 + 8 × bottom`).
- **R70** — bottom revealed at round end; only reachable through the handler, untested there.
- **R81** — no test asserts the next round's trump rank equals the new leader's level.
- **R84** — no test covers the Find Friends game-over firing on a **revealed friend's** level
  rather than the leader's. This is D19, a decision made *this* interview; it is currently
  unpinned in either direction.
- **R2** — seat order is counter-clockwise. Turn advance is tested; the seating semantics are not.
- **R26** (second half) — no test asserts that buried cards are excluded from the R41 throw check.
- **R29** — declaration shape (card identity + ordinal *k*) is tested for `k=1` only; nothing
  exercises `k=2`, the other legal ordinal.
- **R39** — the definition rule itself has no test (D16 will supply one).

**Weak coverage (asserts something adjacent, not the rule):**

- **R8** — `tests/test_models/test_trump.py` pins the tier ladder and
  `tests/test_integration/test_formats_and_ordering.py:26` pins the K-A-3 split, but nothing
  pins cross-suit non-adjacency (because the engine does not have it — F1) or the wrap-destroyed
  case (F3).
- **R73** — accumulation across *multiple* throws by one player in one round is asserted nowhere;
  single-throw penalty size is covered at `tests/test_engine/test_throw_penalty.py:68`.
- **R47** — throw-follow tests exist (`tests/test_engine/test_tricks.py:900-930`) but none covers
  a tractor component with two candidate tractors in hand, which is where F5 lives.

Everything else in R1–R84 has at least one test that asserts its distinguishing behavior; the
strongest areas are R42–R47 (`tests/test_engine/test_tricks.py`, ~30 assertions),
R52 (`tests/test_engine/test_tricks.py:236-330`), R67–R69 (`tests/test_engine/test_scoring.py:138-215`)
and R76–R83 (`tests/test_engine/test_scoring.py:352-375`, `tests/test_modes/test_upgrade.py:125-200`).

## 7. Refactor assessment

**Verdict: no. The mutate-in-place structure did not impede this audit, and it is not what is
costing verification effort.**

Measured against the playbook's three criteria:

1. **Pure reducer core** — not satisfied *literally*: `play_cards` mutates `GameState` in place
   and raises `ValueError` on rejection instead of returning it. But the two properties that
   actually matter for verification are both present. Rejection is **atomic**: every validation
   in `play_cards` (turn check :579, possession check :588-594, `is_valid_follow` :655) runs
   before the first mutation at :662, and I confirmed empirically that an illegal follow and an
   out-of-turn play both leave hand, trick and turn pointer byte-identical. And the rules logic
   is **already pure and already extracted**: `engine/tricks.py`, `models/groups.py`,
   `models/trump.py` and `engine/scoring.py` are 1,150 lines of side-effect-free functions over
   plain arguments. That is why the 170k-play differential oracle in §R42–R50 and the 1.27M-throw
   search in §3.7 were both possible to write directly against the real code with no test
   scaffolding at all. A reducer refactor would move the mutation, not the rules — the oracle
   would not get easier to write.

2. **Redacted per-player views** — satisfied structurally (`to_player_view` derives from
   canonical state and gates the bottom correctly) with one known leak, D21, already ruled and
   scheduled. That is a two-line fix in `start_dealing`, not a refactor.

3. **Deterministic seeding** — satisfied. `GameEngine(rng=…)` threads through to `Deck`
   (`models/deck.py:33-39`); I ran a full seeded 25-trick round in §R60 and the existing suite
   already asserts replay determinism (`tests/test_fuzz/test_invariants.py:124`).

The one genuine structural defect found is **F6**: `FindFriendsStrategy._play_counts` is engine
state that does not live on `GameState`. That breaks criterion 1 in the way that actually bites —
state snapshot/restore does not round-trip — and it will produce false failures the moment the
fuzz harness asserts state-diffing properties. Moving that counter onto `GameState` is a
contained change and is worth doing **before** Phase 3 hardens; a broader reducer refactor is not.

Also worth noting against criterion 1: two rules (R17, R70) are implemented in
`network/handler.py` and are therefore genuinely outside any engine-level oracle, and F4 shows
the network layer imposes at least one rule of its own that the spec does not record. That is a
real boundary problem — but it is a *bidding and display* boundary problem, not one the
mutate-in-place core causes, and pulling R17 into the engine (`close_bidding` owning the pass
set) is a much smaller change than restructuring the engine.

## 8. Recommended sequencing for Phase 5

1. **F1 before D18.** D18 as worded, applied to the current suit-blind adjacency, makes the
   cross-suit problem worse rather than better.
2. **F1 alongside D16.** They are the same bug seen from two sides; fixing only the `Throw`
   branch leaves the `Tractor` branch open.
3. **F6 before Phase 3 hardens** — cheap, and it removes a class of false fuzz failures.
4. **F2, F3, F4 are spec edits**, not code changes: R31's wording, limitation #1's wording, and
   recording (or removing) the network layer's single→pair bid upgrade.
5. **F5 needs a decision**, not a fix — R46 and R47 are both implemented as written; the question
   is whether the asymmetry is intended.
6. **The 14 zero-coverage rules** should be pinned in the same wave, with R41/D07, R84/D19 and
   R31 first — those three are on-record decisions with no test defending them.
