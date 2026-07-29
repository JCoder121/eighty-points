# Edge-case coverage matrix — Shengji engine

**Date:** 2026-07-29 · **Scope:** 4 players / 2 decks, Upgrade + Find Friends · **Status:** report only, no code or test changes.

Spec under audit: `docs/RULES.md` (R1-R84, D01-D21). Every cell below was mapped to tests by
**reading test bodies**, not names. Every GAP and PARTIAL in the prioritized list was
**empirically probed** against the real engine (throwaway scripts in the session scratchpad,
importing `shengji.*` directly) and the observed behavior is recorded.

## Verdict key

- **COVERED** — a test body asserts the cell's behavior.
- **PARTIAL** — behavior is exercised incidentally (e.g. as a setup step or via a helper that
  happens to hit it) but nothing asserts the rule the cell is about.
- **GAP** — nothing in `tests/` asserts it.

## Baseline notes

1. `tests/test_fuzz/` is **uncommitted work-in-progress** from the parallel fuzz-harness agent
   (`git status` shows it untracked). It is not part of the 621-test committed baseline. It
   already covers most of Dimension 8 (36 `@junk` adversarial cases). Dimension 8 below is
   scored against the committed baseline with the in-flight coverage noted per cell, so the
   two reports do not double-count.
2. D16-D18, D20, D21 are **ruled behavior changes not yet implemented**. Cells touching them
   pin the **ruled** target as correct and mark the current engine as *known-deviating*.
3. R17 (bidding close) is implemented in `network/handler.py`, not the engine — out of scope
   for an engine-only cell, flagged as a known limitation in the spec.

---

## Dimension 1 — Follow-suit legality: lead type × holding shape

Context abbreviations: TR = trump rank, `CTX_H` = TR 2 / hearts trump, `NT` = TR 2 / no-trump.

### 1a. Single lead (R42, R43, R44)

| # | Holding shape | Verdict | Evidence / observed |
|---|---|---|---|
| 1.1 | Rich suit (several led-suit cards) — any one is legal | COVERED | `test_tricks.py:582-588` asserts all four hearts individually validate |
| 1.2 | Exactly one led-suit card | COVERED | `test_tricks.py:590-593` off-suit rejected while the single heart is held |
| 1.3 | Void — any card legal | COVERED | `test_tricks.py:595-597`; `test_tricks.py:75-79` (`get_legal_plays`) |
| 1.4 | Wrong card count rejected | COVERED | `test_tricks.py:599-601` |
| 1.5 | Trump lead, holder has trump — must play trump | PARTIAL | Exercised inside tractor tests (`test_tricks.py:691-698`) but no single-lead trump assertion. Probed: legal ✓ |
| 1.6 | **No-trump: TR card cannot follow its natural suit (R7)** | **GAP** | Probed: `NT`, hearts led, hand `[2♥, A♦]` → **both** `[2♥]` and `[A♦]` legal, i.e. the player is treated as void in hearts. Matches R7 → **pin test** |
| 1.7 | No-trump: trump led, TR card must be played | **GAP** | Probed: hand `[2♥, A♦, K♠]`, trump led → `[2♥]` legal, `[A♦]` **rejected**. Matches R7 → **pin test** |

### 1b. IdenticalGroup(2) (pair) lead (R42, R45)

| # | Holding shape | Verdict | Evidence / observed |
|---|---|---|---|
| 1.8 | Hand holds a pair → must play some pair | COVERED | `test_tricks.py:643-648` |
| 1.9 | Two pairs → either is legal | COVERED | `test_tricks.py:893-898` (throw variant); probed pair lead: 2/3 subsets legal = the two pairs |
| 1.10 | No pair, ≥2 led-suit → any two singles | COVERED | `test_tricks.py:609-623` (four distinct combinations asserted) |
| 1.11 | **Hand holds a TRIPLE of the led suit** | **GAP** | Probed `[A♠,A♠,A♠,K♠]`: only `A♠A♠` legal (1/2). Matches R45 → pin |
| 1.12 | **Hand holds a QUAD** (not reachable in a 2-deck game) | **GAP** | Probed `[A♠]×4`: `A♠A♠` legal. Unreachable in real play; low value |
| 1.13 | Exactly 2 led-suit cards forming a pair | PARTIAL | Implied by 1.8; probed 1/2 legal (the pair). No dedicated assertion |
| 1.14 | Exactly 2 led-suit cards, not a pair | COVERED | `test_tricks.py:625-628` |
| 1.15 | Short (1 led-suit card) — must play it + free fill | COVERED | `test_tricks.py:630-635` |
| 1.16 | **Void — any 2 cards, including breaking own pair (R49)** | **GAP** | Probed `[K♦,K♦,Q♦]`: **both** `K♦K♦` and `K♦Q♦` legal (2/2). Matches R49 → pin |
| 1.17 | Off-suit substituted while led-suit available → rejected | COVERED | `test_tricks.py:625-628` |
| 1.18 | Mismatched off-suit TR cards are not a pair (#50) | COVERED | `test_tricks.py:723-729`, `test_trump_identity_flow.py:35-51` |

### 1c. Tractor lead (R46)

| # | Holding shape | Verdict | Evidence / observed |
|---|---|---|---|
| 1.19 | Exact tractor held → must play it | COVERED | `test_tricks.py:758-765` |
| 1.20 | **Longer tractor held (6-card) vs Tractor(2,2) lead** | **GAP** | Probed `A♠A♠K♠K♠Q♠Q♠`: 2/6 subsets legal — `AAKK` and `KKQQ`; `AAQQ` rejected. Correct → pin |
| 1.21 | Pairs but no tractor → must use pairs | COVERED | `test_tricks.py:706-721`, `:793-805` |
| 1.22 | Which pairs is the player's choice (#48) | COVERED | `test_tricks.py:793-800` |
| 1.23 | Real tractor beats two separate pairs as an obligation | COVERED | `test_tricks.py:813-824` |
| 1.24 | Singles only → any 4 | COVERED | `test_tricks.py:674-683` |
| 1.25 | **Short: 3 led-suit incl. a pair, 1 off-suit fill** | **GAP** | Probed `A♠A♠10♠ K♦K♦`: only `A♠A♠10♠+K♦` legal. Correct → pin |
| 1.26 | **Void → any 4, may break own trump tractor (R49)** | **GAP** | Probed `K♦K♦Q♦Q♦` vs spade tractor lead: legal. Correct → pin |
| 1.27 | **Tractor(2,3) lead (6 cards) — any shape** | **GAP** | All committed tractor-follow tests use `Tractor(2,2)`. Probed 3 hands (6-tractor+spare pair, 4-tractor+pair+singles, 3 pairs+2 singles) — each has exactly 1 legal follow, all correct → pin |
| 1.28 | Hand's tractor is a wrap tractor (A-3 at TR 2) | **GAP** | Not probed at follow level; classification is covered (2.1) |
| 1.29 | `get_legal_plays` output always validates | COVERED | `test_tricks.py:807-811`; re-verified across all 20 probe hands — hint was legal in every case |

### 1d. Throw lead (R47)

| # | Holding shape | Verdict | Evidence / observed |
|---|---|---|---|
| 1.30 | Pair component, hand has a pair → must include some pair | COVERED | `test_tricks.py:874-885` |
| 1.31 | Pair component, hand has no pair → any suited cards | COVERED | `test_tricks.py:853-860` |
| 1.32 | Two pair components, two pairs held → both required | COVERED | `test_tricks.py:931-941` |
| 1.33 | Two pair components, 3 pairs held → choose 2 | **GAP** | Probed: 3/13 legal = all three pair-choices. Correct → pin |
| 1.34 | Single component carries no obligation | PARTIAL | Implicit in 1.30's "+ any single"; no dedicated assertion |
| 1.35 | Short follow (fewer led-suit than throw size) | COVERED | `test_tricks.py:912-923` |
| 1.36 | **Tractor component — card-specific claim from hand** | **GAP** | Probed: hand `A♠A♠K♠K♠10♠10♠6♠` vs `Throw[Tractor(2,2),Single]` → 2/9 legal, both containing `AAKK`. Correct → pin |
| 1.37 | **Tractor component + hand holds TWO EQUAL-LENGTH tractors** | **GAP / BUG** | See **NEW-1** below. The engine forces the *lowest* tractor and rejects the higher one |
| 1.38 | Throw lead, follower void | **GAP** | Not probed exhaustively; falls through the `len(suited)<n` branch (same code path as 1.35) |

**Dimension 1 totals: 38 cells — 17 COVERED, 4 PARTIAL, 17 GAP** (1 of the GAPs is a bug).

---

## Dimension 2 — Tractor boundary shapes (R8, R37)

| # | Shape | Verdict | Evidence / observed |
|---|---|---|---|
| 2.1 | 2-position wrap A-3 at TR 2 (tier 0) | COVERED | `test_groups.py:108-114`, `test_trump.py:210-214`, `test_tricks.py:513-523` |
| 2.2 | Wrap A-2 at TR 3 | **GAP** | Probed: `A♠A♠2♠2♠` at TR 3 → `Tractor(2,2)` ✓ → pin |
| 2.3 | 3-position wrap K-A-3 splits (known limitation) | COVERED | `test_formats_and_ordering.py:26-36` pins `Throw[Tractor, IdenticalGroup]` |
| 2.4 | **3-position wrap A-3-4 splits** (same root cause, simpler shape) | **GAP** | Probed `3♠3♠ 4♠4♠ A♠A♠` → `Throw[Tractor(2,2), IdenticalGroup(2)]`. Same documented limitation, a *different* reachable shape → pin |
| 2.5 | TR-skip adjacency 3-5 at TR 4 | COVERED | `test_groups.py:84-91`, `test_trump.py:190-192`, `test_tricks.py:477-487` |
| 2.6 | TR-skip 8-10 at TR 9, 2-4 at TR 3 | COVERED | `test_groups.py:92-106`, `test_tricks.py:489-511` |
| 2.7 | TR-skip inside the **trump suit** (tier 1) | **GAP** | Probed TR 5 / hearts: `4♥4♥ 6♥6♥` → `Tractor(2,2)` ✓ (matches the tier-0 behavior) → pin |
| 2.8 | Tier 1 top ↔ tier 2 (A♥A♥ + 2♠2♠) | COVERED | `test_groups.py:186-191`, `test_trump.py:234-237` |
| 2.9 | Tier 2 ↔ tier 3 (2♠2♠ + 2♥2♥) | COVERED | `test_groups.py:135-140`, `test_trump.py:230-232` |
| 2.10 | Tier 3 ↔ tier 4 (2♥2♥ + SJ SJ) | COVERED | `test_groups.py:149-154`, `test_trump.py:226-228` |
| 2.11 | Tier 4 ↔ tier 5 (SJ SJ + BJ BJ) | COVERED | `test_groups.py:142-147`, `test_trump.py:222-224` |
| 2.12 | Tier 0 ↔ tier 1 NOT adjacent | COVERED | `test_trump.py:248-250` |
| 2.13 | Trump-suit wrap A♥-3♥ NOT adjacent | COVERED | `test_trump.py:239-242`. Probed classification: `A♥A♥3♥3♥` → `Throw` ✓ |
| 2.14 | Different non-trump suits not adjacent | COVERED | `test_trump.py:244-246`; probed `A♠A♠ + A♦A♦` → `Throw` ✓ |
| 2.15 | **No-trump gap: TR pair + SJ pair (D18 target)** | **GAP — engine known-deviating** | Probed: `NT`, `2♥2♥ + SJ SJ` → **`Throw`**; with hearts trump the same shape → `Tractor`. `SJ SJ + BJ BJ` is a tractor in both modes. D18 rules this should be a Tractor |
| 2.16 | No-trump: two off-suit TR pairs (`2♠2♠ + 2♥2♥`) | **GAP** | Probed: `Throw` ✓ — correct in *both* the current and the D18 world (same strength position, nothing between them is a *different* position) → pin |
| 2.17 | **3-rung trump-hierarchy tractor** `2♥2♥ SJ SJ BJ BJ` | **GAP** | Probed → `Tractor(2, 3)` ✓ → pin |
| 2.18 | **5-rung tractor** `A♥A♥ 2♠2♠ 2♥2♥ SJ SJ BJ BJ` | **GAP** | Probed → `Tractor(2, 5)` ✓ → pin |
| 2.19 | Quad of one identity → `IdenticalGroup(4)`, not a tractor | **GAP** | Probed ✓. Unreachable in a 2-deck game; low value |
| 2.20 | Two pairs at the SAME strength position (`2♠2♠+2♦2♦`) are not a quad and not a tractor (R37/#50) | COVERED | `test_groups.py:280-291` |
| 2.21 | **Three TR pairs at TR 2 / clubs: `2♠2♠ 2♦2♦ 2♣2♣`** | **GAP** | Probed → `Throw[Tractor(2,2), IdenticalGroup(2)]` — one off-suit pair pairs with the on-suit pair as a tractor, the other off-suit pair is left over. Correct per R8 → pin |
| 2.22 | Pair + adjacent TRIPLE (`A♠A♠ K♠K♠K♠`) | **GAP** | Probed → `Throw[Tractor(2,2), Single]` — the triple's 3rd card is orphaned as a Single. Consistent with R37's greedy decomposition; unreachable in 2 decks |
| 2.23 | Mixed-suit "tractor" attempts rejected | COVERED | `test_trump.py:244-250` |

**Dimension 2 totals: 23 cells — 12 COVERED, 0 PARTIAL, 11 GAP** (1 known-deviating vs D18).

---

## Dimension 3 — Throw resolution (R39-R41, R71-R75, D08, D13, D16)

### 3a. Throw legality (R40, R41)

| # | Case | Verdict | Evidence / observed |
|---|---|---|---|
| 3.1 | Valid throw, nobody beats any component | COVERED | `test_tricks.py:397-406`, `test_throw_penalty.py:128-142` |
| 3.2 | Single component beatable | COVERED | `test_tricks.py:408-417` |
| 3.3 | Pair component beatable by a higher pair | COVERED | `test_tricks.py:444-455` |
| 3.4 | Pair component NOT beatable when the thrower holds a blocking copy | COVERED | `test_tricks.py:430-442`, `:457-469` |
| 3.5 | Thrower's own higher cards don't beat the throw | COVERED | `test_tricks.py:419-428` |
| 3.6 | **Tractor component beaten by an EQUAL-length higher tractor** | **GAP** | Probed `7♠7♠6♠6♠+3♠` vs opp `Q♠Q♠J♠J♠` → tractor component reported beatable ✓ |
| 3.7 | **Tractor component beaten by a LONGER higher tractor (D08)** | **GAP** | Probed vs opp `Q♠Q♠J♠J♠10♠10♠` → beatable ✓. D08's "longer counts too" is the point of the rule and has **zero** coverage |
| 3.8 | **Tractor component NOT beaten by a longer but LOWER tractor** | **GAP** | Probed vs opp `5♠5♠4♠4♠` → tractor component **not** in the beatable list ✓ |
| 3.9 | Tractor component not beaten by a higher pair / higher single alone | **GAP** | Probed vs `A♠A♠` and vs `A♠` → tractor component not beatable ✓ |
| 3.10 | **Two opponents cannot combine to beat one component** | **GAP** | Probed `Q♠Q♠` with p1 and `J♠J♠` with p2 → tractor component not beatable ✓ (R40's per-opponent rule) |
| 3.11 | **D07: the thrower's PARTNER counts (Upgrade)** | **GAP** | Probed at engine level: p0 throws `K♠+Q♠`, partner p2 holds `A♠` → `throw_failed=True`. Matches D07 (now on-record) → pin |
| 3.12 | **R26: buried bottom cards are excluded from the check** | **GAP** | Probed: both `A♠` in the bottom, p0 throws `K♠+Q♠` → `throw_failed=False` ✓ → pin |
| 3.13 | Unrevealed friends count (D07, Find Friends) | **GAP** | Same code path as 3.11 (`all_hands` = every other seat); not separately probed |
| 3.14 | **Mixed-suit throw accepted (D16 target)** | **GAP — engine known-deviating** | Probed at engine level: `A♠ + A♦` accepted; `led_suit` is `'spades'` for `[A♠,A♦]` and `'diamonds'` for `[A♦,A♠]`. D16 rules this a hard reject |
| 3.15 | **Mixed-suit throw with one beatable component routes through the PENALTY path** | **GAP — engine known-deviating** | Probed: `K♠+A♦` with p1 holding `A♠` → `throw_failed=True`, forced `K♠`, penalty 20. D16 says malformed throws must be *rejected*, not penalized |
| 3.16 | All-trump throw in no-trump mode | **GAP** | Probed: `2♠+2♦` under `NT` → accepted, `led_suit='trump'`, `Throw[Single,Single]` ✓ (legitimately single-suited) → pin |
| 3.17 | `_assign_throw_components` silent-pass path (spec suspected-bug 7) | **GAP — not reproduced** | Probed several tractor+tractor and tractor+single throws; the component was always re-found. Confirms the spec's "no reachable case constructed" |

### 3b. Forced play + penalty (R71-R75)

| # | Case | Verdict | Evidence / observed |
|---|---|---|---|
| 3.18 | Tie-break: fewest cards first | COVERED | `test_throw_penalty.py:88-102` |
| 3.19 | Tie-break: weakest on an equal count | COVERED | `test_throw_penalty.py:68-86` |
| 3.20 | Unplayed attempt cards stay in hand; card conservation | COVERED | `test_throw_penalty.py:104-126` |
| 3.21 | Penalty = 10 × attempted cards (not withdrawn cards) | COVERED | `test_throw_penalty.py:79-83` (2 attempted → 20), `:99` (3 → 30) |
| 3.22 | **Forced component is a PAIR** (not a single) | **GAP** | Probed: throw `Q♠Q♠+A♠` vs p1 `K♠K♠` → forced `Q♠Q♠`, penalty 30 ✓. Every existing test forces a *single* → pin |
| 3.23 | **Multiple failed throws by the same player accumulate (R73)** | **GAP** | Probed: two failed throws by p0 → `throw_penalties == {'p0': 40}` ✓ → pin |
| 3.24 | Penalties reset at deal | COVERED | `test_throw_penalty.py:144-150` |
| 3.25 | Defender thrower → attackers gain | COVERED | `test_throw_penalty.py:164-184` |
| 3.26 | Attacker thrower → attackers lose, clamped at 0 (D13) | COVERED | `test_throw_penalty.py:186-205` |
| 3.27 | Find Friends: attribution uses FINAL team after a reveal | COVERED | `test_throw_penalty.py:207-237` |
| 3.28 | Find Friends: thrower flips the *other* way (defender → attacker) | **GAP** | Not reachable — a Find Friends reveal only ever moves a player *to* defending |
| 3.29 | **Forced throw as the LAST trick → bottom multiplier** | **GAP** | Probed: forced-single lead, defender wins last trick → bottom suppressed, `attacking_points == penalty` ✓. The forced-pair-as-last-trick × attacker-win path (→ ×4) is untested → pin |

**Dimension 3 totals: 29 cells — 12 COVERED, 0 PARTIAL, 17 GAP** (2 known-deviating vs D16, 1 unreachable).

---

## Dimension 4 — Trump declaration / bidding races (R12-R19, D02-D05)

| # | Case | Verdict | Evidence / observed |
|---|---|---|---|
| 4.1 | Suited single bid | COVERED | `test_bidding.py:205-210` |
| 4.2 | Suited identical pair bid | COVERED | `test_bidding.py:119-120`, `test_bidding_and_bottom.py:31-37` |
| 4.3 | Small-Joker pair → no-trump | COVERED | `test_bidding.py:268-271` |
| 4.4 | Big-Joker pair → no-trump | COVERED | `test_bidding.py:273-276` |
| 4.5 | Single joker illegal | COVERED | `test_bidding.py:99-101`, `:288-291` |
| 4.6 | Non-identical "pair" illegal (#50) | COVERED | `test_bidding.py:107-111` |
| 4.7 | Wrong-rank card illegal | COVERED | `test_bidding.py:103-105`, `:113-117` |
| 4.8 | 0 / 3 cards illegal | COVERED | `test_bidding.py:128-134`, `:84-88` |
| 4.9 | Bidder must hold the cards | COVERED | `test_bidding.py:221-225` |
| 4.10 | Single cannot override a single (other player) | COVERED | `test_bidding.py:234-242` |
| 4.11 | Single cannot override own single | COVERED | `test_bidding.py:244-250` |
| 4.12 | Suited pair cannot override a suited pair | COVERED | `test_bidding.py:259-266` |
| 4.13 | Pair overrides another player's single | COVERED | `test_bidding_and_bottom.py:31-37` |
| 4.14 | Self-override single → pair (D04) | COVERED | `test_bidding.py:252-257` |
| 4.15 | SJ pair > suited pair | COVERED | `test_bidding.py:178-180`, `test_bidding_and_bottom.py:39-45` |
| 4.16 | BJ pair > SJ pair; SJ pair cannot override BJ pair | COVERED | `test_bidding.py:182-188`, `:278-286` |
| 4.17 | Bid during DEALING | COVERED | `test_bidding.py:293-302` |
| 4.18 | Bid after deal (BIDDING_AFTER_DEAL) | COVERED | `test_bidding.py:205-210` (setup deals fully) |
| 4.19 | Bid rejected in a non-bidding phase | COVERED | `test_bidding.py:227-232` |
| 4.20 | Trump rank = round leader's level (R12) | COVERED | `test_bidding.py:304-312` |
| 4.21 | All-pass → redeal, leader + rank preserved (R19/D05) | COVERED | `test_bidding.py:343-350`, `test_bidding_and_bottom.py:55-65` |
| 4.22 | Second consecutive all-pass redeals again | COVERED | `test_bidding_and_bottom.py:67-76` |
| 4.23 | Bottom is NOT revealed on all-pass (D05) | PARTIAL | `test_bidding_and_bottom.py:62` asserts `len(draw_pile)==100`, implying a fresh deal, but nothing asserts the bottom stayed hidden / no fallback trump |
| 4.24 | Round 1: bid winner becomes round leader (R18) | COVERED | `test_bidding.py:336-341`, `:361-371` |
| 4.25 | Round 2+: leader unchanged, only trump set (R18) | COVERED | `test_bidding.py:387-411` (3 tests) |
| 4.26 | Teams assigned at bid close (R20) | PARTIAL | `close_bidding` calls `assign_teams`, exercised via stubs; the mode tests assert `assign_teams` directly (`test_upgrade.py:36-88`) but nothing asserts the *ordering* at close |
| 4.27 | **Bid cards stay in hand and may be buried (R13 + R25)** | **GAP** | Probed: after `place_bid`, the card is still in hand; after `close_bidding` + `exchange_bottom` burying it, `bid_card in state.bottom_deck` is True, hand back to 25 ✓ → pin |
| 4.28 | Bid card played normally later in the round | **GAP** | Same mechanism as 4.27; not separately probed |
| 4.29 | R17 all-passed trigger / passed-player-cannot-rebid | **OUT OF ENGINE SCOPE** | Implemented in `network/handler.py:302-303, 336-350`; see spec known-limitation 2 |

**Dimension 4 totals: 29 cells — 24 COVERED, 2 PARTIAL, 2 GAP, 1 out of scope.** This is the
best-covered dimension.

---

## Dimension 5 — Bottom / kitty (R23-R27, R61, R67-R70, D06, D15)

| # | Case | Verdict | Evidence / observed |
|---|---|---|---|
| 5.1 | Only the round leader may exchange | COVERED | `test_bottom_exchange.py:103-106` |
| 5.2 | Wrong phase rejected | COVERED | `test_bottom_exchange.py:97-101` |
| 5.3 | Wrong card count (7 / 0) rejected | COVERED | `test_bottom_exchange.py:108-111`, `test_bidding_and_bottom.py:116-119` |
| 5.4 | Card not in the post-pickup hand rejected | COVERED | `test_bottom_exchange.py:161-168` |
| 5.5 | Hand returns to 25; total cards conserved | COVERED | `test_bottom_exchange.py:125-154` |
| 5.6 | Burying points / trump / jokers allowed (D06) | COVERED | `test_bidding_and_bottom.py:103-114` |
| 5.7 | **Burying the winning bid's cards allowed (D06)** | **GAP** | See 4.27 — probed ✓ |
| 5.8 | Transitions to PLAYING (both modes) | COVERED | `test_bottom_exchange.py:156-159`, `:199-202` |
| 5.9 | Find Friends: declaration happens *before* the exchange (R23) | COVERED | `test_bottom_exchange.py:235-237`, `test_find_friends_flow.py:80-84` |
| 5.10 | Multiplier ×2 for a single winning play | COVERED | `test_scoring.py:156-176` |
| 5.11 | Multiplier ×4 for a pair | COVERED | `test_scoring.py:178-190` |
| 5.12 | Multiplier ×8 for a 4-card tractor | COVERED | `test_scoring.py:192-209`, `test_scoring_rounds.py:67-81` |
| 5.13 | Cap at 8 for a 6-card tractor | COVERED | `test_scoring.py:211-227` |
| 5.14 | **Multiplier when the winning play is a THROW (R68)** | **GAP** | Probed: `pair+single` → ×4; `tractor(4)+single` → ×8; `2 singles` → ×2. All match "2 × largest component, capped at 8" ✓ → pin |
| 5.15 | Multiplier for a triple (`IdenticalGroup(3)`) | **GAP** | Probed → ×6. Unreachable in a 2-deck game; R68's bullet list doesn't enumerate it |
| 5.16 | **Forced-throw component as the last trick's winning play (R68)** | **GAP** | Probed the defender-wins variant (bottom suppressed ✓). The attacker-wins-with-a-forced-pair path (→ ×4) is untested → pin |
| 5.17 | Defender wins last trick → bottom scores nothing (D15) | COVERED | `test_scoring.py:138-154` |
| 5.18 | Attacker wins last trick → bottom multiplied | COVERED | `test_scoring.py:156-176` |
| 5.19 | Bottom with 0 points → nothing added | COVERED | `test_scoring.py:229-240` |
| 5.20 | Total can exceed 200 via the multiplier (R62) | COVERED | `test_scoring_rounds.py:40-54` (300 pts) |
| 5.21 | **Find Friends: a revealed FRIEND wins the last trick → bottom suppressed** | **GAP** | Probed: friend p1 wins last trick as a defender → `attacking_points == 0`, bottom (20) suppressed ✓ (D15 uses final teams) → pin |
| 5.22 | **Find Friends: an attacker wins the last trick after a reveal → multiplier applies** | **GAP** | Probed: friend revealed mid-trick, attacker p3 wins with a single, bottom 20 → `attacking_points == 45` (5 trick + 2×20) ✓ → pin |
| 5.23 | Bottom hidden from all players during play, visible only to the leader during BOTTOM_EXCHANGE (R26) | COVERED | `test_game_state.py:146-168` — three tests: hidden during PLAYING even to the leader, visible to the leader in BOTTOM_EXCHANGE, hidden to non-leaders in BOTTOM_EXCHANGE |
| 5.24 | Bottom revealed at round end (R70) | **GAP** | Display-only rule, no engine effect |

**Dimension 5 totals: 24 cells — 16 COVERED, 0 PARTIAL, 8 GAP** (1 unreachable, 1 display-only).

---

## Dimension 6 — Point counting & Find Friends attribution (R28-R34, R59-R66)

| # | Case | Verdict | Evidence / observed |
|---|---|---|---|
| 6.1 | Exactly 1 declaration for 4 players | COVERED | `test_find_friends.py:106-114`, `test_find_friends_flow.py:72-78` |
| 6.2 | Joker banned as friend card | COVERED | `test_find_friends.py:116-124`, `test_find_friends_flow.py:57-60` |
| 6.3 | Trump-rank card banned | COVERED | `test_find_friends.py:126-130`, `test_find_friends_flow.py:62-65` |
| 6.4 | Trump-suit card banned, any rank (D11) | COVERED | `test_find_friends.py:139-151`, `test_find_friends_flow.py:67-70` |
| 6.5 | No-trump → any non-joker non-TR suit allowed | COVERED | `test_find_friends.py:160-165` |
| 6.6 | Only the round leader may declare | COVERED | `test_bottom_exchange.py:226-228`, `test_find_friends_flow.py:86-89` |
| 6.7 | Wrong phase rejected | COVERED | `test_bottom_exchange.py:221-224` |
| 6.8 | **Ordinal outside 1..2 (D20 target)** | **GAP — engine known-deviating** | Probed ordinals 0, 3, 5, −1 → **all accepted**, phase advances to BOTTOM_EXCHANGE, round silently becomes 1v3. D20 rules these must raise `ValueError` |
| 6.9 | Ordinal 1 reveals on the first copy | COVERED | `test_find_friends.py:188-194`, `test_find_friends_flow.py:93-105` |
| 6.10 | Ordinal 2 reveals only on the second copy | COVERED | `test_find_friends.py:196-205`, `test_find_friends_flow.py:131-144` |
| 6.11 | Both copies in one trick → only the first joins | COVERED | `test_find_friends_flow.py:146-158` |
| 6.12 | A resolved declaration cannot re-trigger | COVERED | `test_find_friends.py:227-236` |
| 6.13 | Non-matching card is a no-op | COVERED | `test_find_friends.py:181-186` |
| 6.14 | **The LEADER's copies count toward the ordinal (R32)** | **GAP** | Probed: ordinal 2, leader plays copy 1 (no reveal), p1 plays copy 2 → **p1 becomes the friend** ✓ → pin |
| 6.15 | Self-friend (leader declares + plays own card) → 1v3 | COVERED | `test_find_friends.py:218-225`, `test_find_friends_flow.py:160-172` |
| 6.16 | Friend card buried in the bottom → never reveals, 1v3 | COVERED | `test_find_friends_flow.py:174-189` |
| 6.17 | Retroactive re-attribution at the reveal moment, mid-trick (D12/#43) | COVERED | `test_find_friends_flow.py:107-129` |
| 6.18 | Reveal on the final trick still counts | COVERED | `test_find_friends_flow.py:191-214` |
| 6.19 | Reveal *before* any point tricks | PARTIAL | Implicitly covered by 6.9; nothing asserts the point total in that ordering |
| 6.20 | Points on the reveal trick itself go by the post-reveal team | PARTIAL | 6.17 asserts the *pre*-reveal total drops to 0; the trick then in progress is not separately asserted |
| 6.21 | `attacking_points` recomputed from scratch, no drift (R60) | COVERED | `test_find_friends_flow.py:107-129` asserts exact values at two points |
| 6.22 | Upgrade: attackers fixed all round (R63) | COVERED | `test_upgrade.py:78-88` |
| 6.23 | Final teams used at round end (R34) | COVERED | `test_throw_penalty.py:207-237` |
| 6.24 | Point values: 5→5, 10→10, K→10, rest 0, jokers 0 (R4) | COVERED | `test_card.py:10-34` |
| 6.25 | All 4 plays go to the winner's pile (R57) | COVERED | `test_game_loop.py:183-198` |
| 6.26 | **`revealed_friends` / `friend_declarations` survive into the next round (D21 target)** | **GAP — engine known-deviating** | Probed: after `start_dealing`, `revealed_friends == {'p2'}` and 1 stale declaration remain; `to_player_view('p1')` exposes both. D21 rules they must be cleared |

**Dimension 6 totals: 26 cells — 20 COVERED, 2 PARTIAL, 4 GAP** (2 known-deviating vs D20/D21).

---

## Dimension 7 — Level-up boundaries & game over (R76-R84, D14, D19)

| # | Case | Verdict | Evidence / observed |
|---|---|---|---|
| 7.1 | Bands 0/1/19 → defending +4 | COVERED | `test_scoring.py:44-52` |
| 7.2 | 20/39 → +3; 40/59 → +2; 60/79 → +1 | COVERED | `test_scoring.py:53-69` |
| 7.3 | 80/95/99 → attacking +0 | COVERED | `test_scoring.py:73-80` |
| 7.4 | 100/119 → +1; 120/139 → +2; 140 → +3 | COVERED | `test_scoring.py:82-95` |
| 7.5 | Cap at +3 for 200 / 500 (#51) | COVERED | `test_scoring.py:97-102`, `test_scoring_rounds.py:40-54` |
| 7.6 | `n_decks=1` band table | COVERED | `test_scoring.py:104-113` |
| 7.7 | Clamp at Ace: Q +3 → A (D14) | COVERED | `test_scoring.py:381-388` |
| 7.8 | Clamp: J +4 → A, K +4 → A, A +4 → A | **GAP** | Probed `advance_rank`: J+4→A, Q+3→A, K+4→A, A+4→A, 10+4→A ✓. Only the Q+3 case is pinned → pin the rest |
| 7.9 | Game over: defenders already at Ace defend successfully (R82/#52) | COVERED | `test_scoring.py:352-360` |
| 7.10 | Not game over: advancing *into* Ace (#52) | COVERED | `test_scoring.py:369-379` |
| 7.11 | Not game over when attackers win with steps ≥ 1 | COVERED | `test_scoring.py:362-367` (600 pts → +3) |
| 7.12 | **Not game over in the +0 takeover band (80-99) with a defender at Ace (R83)** | **GAP** | Probed: 90 pts, both defenders at Ace → `winner='attacking'`, `steps=0`, `game_over=False` ✓. R83 is the *specific* rule and only the +3 case is tested → pin |
| 7.13 | Only the winning team advances (R77) | COVERED | `test_scoring.py:323-336` |
| 7.14 | +0 steps advance nobody | COVERED | `test_scoring.py:338-345` |
| 7.15 | **Find Friends: game over fires on a revealed FRIEND at Ace (D19/Q4)** | **GAP** | Probed: leader p0 at rank 5, friend p1 at Ace, defenders win → `game_over=True`, phase GAME_OVER. Matches D19 (confirmed as intended) → pin |
| 7.16 | Find Friends: friend advances with the leader (R77) | **GAP** | Same probe as 7.15 — p0 and p1 both advance +4 (p0 5→9, p1 A→A clamped) → pin |
| 7.17 | Upgrade: defenders win → no role swap, leader → partner (R79/R80) | COVERED | `test_upgrade.py:125-132`, `:160-176` |
| 7.18 | Upgrade: attackers win → swap, leader → leader+1 (R79/R80) | COVERED | `test_upgrade.py:134-147`, `:178-194`, `test_scoring_rounds.py:56-63` |
| 7.19 | Upgrade: leader rotation from an odd seat | COVERED | `test_upgrade.py:186-194`. Probed at engine level (leader p1, 0 pts → next p3) ✓ |
| 7.20 | Find Friends: defenders (leader + friend) win → next leader from that set | COVERED | `test_find_friends.py:278-283`, `:293-298` |
| 7.21 | Find Friends: attackers win → next leader from attackers | COVERED | `test_find_friends.py:285-291` |
| 7.22 | **Find Friends: lone leader (no friend) defends and WINS → next leader** | **GAP** | Probed: leader p2 alone, defending wins → `next_round_leader_id == 'p2'` (the scan wraps to the leader). Matches R80 literally; **behavioral question**: the same player leads again and the trump rank jumps by their advancement → pin + flag |
| 7.23 | R81: next round's trump rank = new leader's level | PARTIAL | Falls out of R12; probed (new leader p3 at rank 6 after +4) but nothing asserts it across a round boundary |
| 7.24 | Round number increments | COVERED | `test_scoring.py:390-394` |
| 7.25 | Level never decreases (R5) | COVERED | `test_player.py:48` asserts `advance_rank(-1)` raises (`player.py:35-36`) |
| 7.26 | Multi-round leader rotation over 4 rounds | COVERED | `test_upgrade.py:196-213` |

**Dimension 7 totals: 26 cells — 19 COVERED, 1 PARTIAL, 6 GAP.**

---

## Dimension 8 — Adversarial / malformed actions

Scored against the **committed** baseline; the in-flight `tests/test_fuzz/test_adversarial.py`
(36 `@junk` cases, uncommitted) is noted per row. Rows marked *FUZZ* are covered there and
should **not** be duplicated in a fix wave.

| # | Case | Committed verdict | Notes |
|---|---|---|---|
| 8.1 | Play out of turn | COVERED | `test_game_loop.py:93-96`; also *FUZZ* |
| 8.2 | Play by a nonexistent player | **GAP** | *FUZZ* |
| 8.3 | Card not in hand | COVERED | `test_game_loop.py:98-102`; also *FUZZ* |
| 8.4 | Fabricated duplicate (2 copies of a singleton) | COVERED | `test_malformed_and_full_round.py:31-35`; also *FUZZ* |
| 8.5 | Empty play | COVERED | `test_malformed_and_full_round.py:43-46`; also *FUZZ* |
| 8.6 | Wrong follow count | COVERED | `test_malformed_and_full_round.py:37-41`; also *FUZZ* |
| 8.7 | Lead more cards than held | **GAP** | *FUZZ* |
| 8.8 | Play in the wrong phase | COVERED | `test_game_loop.py:87-91`; also *FUZZ* |
| 8.9 | Bid after bidding closed / wrong phase | COVERED | `test_bidding.py:227-232`; also *FUZZ* |
| 8.10 | Bid card not in hand | COVERED | `test_bidding.py:221-225`; also *FUZZ* |
| 8.11 | Bid wrong rank / single joker / 3 cards / mismatched pair | COVERED | `test_bidding.py:99-134`; also *FUZZ* |
| 8.12 | Equal-strength bid cannot overtake | COVERED | `test_bidding.py:234-266`; also *FUZZ* |
| 8.13 | Bid by a nonexistent player | **GAP** | *FUZZ* |
| 8.14 | `close_bidding` in the wrong phase | COVERED | `test_bidding.py:324-327`; also *FUZZ* |
| 8.15 | Exchange in the wrong phase / by the wrong player / wrong count | COVERED | `test_bottom_exchange.py:97-111`; also *FUZZ* |
| 8.16 | Exchange with cards not held | COVERED | `test_bottom_exchange.py:161-168`; also *FUZZ* |
| 8.17 | `declare_friends` in Upgrade mode | COVERED | `test_upgrade.py:99-102`; also *FUZZ* |
| 8.18 | `declare_friends` wrong phase / wrong player / 0 / 2 declarations | COVERED | `test_bottom_exchange.py:221-242`, `test_find_friends_flow.py:57-89`; also *FUZZ* |
| 8.19 | **Invalid friend ordinal (D20)** | **GAP** | Not in *FUZZ* either — see 6.8 |
| 8.20 | `end_round` outside SCORING | COVERED | `test_scoring.py:304-309`; also *FUZZ* |
| 8.21 | `start_dealing` mid-round / wrong phase | COVERED | `test_dealing.py:53-60`; also *FUZZ* |
| 8.22 | Non-Card payloads (string / None) | **GAP** | *FUZZ* |
| 8.23 | Illegal phase transitions rejected | **GAP** | *FUZZ*; `game_state.py:115-123` |
| 8.24 | Rejected action leaves state unmutated + game playable | **GAP** | *FUZZ* (this is the strongest property in the harness) |
| 8.25 | `deal_next_card` on an empty pile | COVERED | `test_dealing.py:164-169`; also *FUZZ* |

**Dimension 8 totals (committed baseline): 25 cells — 18 COVERED, 0 PARTIAL, 7 GAP** — 6 of the
7 are already closed by the in-flight fuzz harness; only 8.19 (D20 ordinals) is uncovered by
both.

---

## Totals

| Dimension | Cells | COVERED | PARTIAL | GAP |
|---|---|---|---|---|
| 1 — Follow legality | 38 | 17 | 4 | 17 |
| 2 — Tractor boundaries | 23 | 12 | 0 | 11 |
| 3 — Throw resolution | 29 | 12 | 0 | 17 |
| 4 — Bidding races | 29 | 24 | 2 | 2 (+1 out of scope) |
| 5 — Bottom / kitty | 24 | 16 | 0 | 8 |
| 6 — Points & FF attribution | 26 | 20 | 2 | 4 |
| 7 — Level-up & game over | 26 | 19 | 1 | 6 |
| 8 — Adversarial (committed) | 25 | 18 | 0 | 7 (6 closed by in-flight fuzz) |
| **Total** | **220** | **138** | **8** | **71** |

Coverage is strongly skewed: bidding and level bands are near-complete; **throw resolution
(41% covered) and follow legality (45%) carry the risk.**

---

## Prioritized gap list

Ranked by engine-correctness risk first, then rules with zero coverage, then nice-to-pin.
Each entry states the observed behavior and whether it matches spec.

### Tier A — suspected bugs (fix wave, then pin)

**A1. Throw-follow with two equal-length tractors forces the LOWER one — NEW BUG (cells 1.37, 1.36)**
`_is_valid_throw_follow` (`engine/tricks.py:398-427`) resolves a `Tractor` component by taking
`sorted(find_tractors(hand_rem), key=len, reverse=True)[0]`. When the follower holds two
tractors of the *same* length, `sorted` is stable, so the winner is whichever `find_tractors`
returned first — and `find_tractors` scans strength positions **ascending**, so it always
returns the **weakest** tractor first. The follower is then card-specifically required to play
that one and is forbidden from playing the higher one.
*Observed (engine level, `play_cards`):* trump-hearts round, p0 leads a valid throw
`A♥A♥ K♥K♥ + Q♥`; p1 holds `10♥10♥ 9♥9♥ 5♥5♥ 4♥4♥ 3♥`. `p1 → [10♥,10♥,9♥,9♥,3♥]` is
**REJECTED**; `p1 → [5♥,5♥,4♥,4♥,3♥]` is **ACCEPTED**.
*Why it's a bug, not just card-specificity:* the pure-`Tractor` lead path
(`_is_valid_tractor_follow`) is **structural** and accepts either tractor — verified: with a
`Tractor(2,2)` lead and the same shape of hand, both `Q♠Q♠J♠J♠` and `7♠7♠6♠6♠` validate. So
the two follow paths disagree, and R46's "which tractor to use is the follower's choice" is
silently reversed under R47. The choice is also an artifact of scan order, not any rule.
**Suggested fix:** make R47's tractor component structural like R46 (compare
`_tractor_pair_capacity`), or at minimum accept *any* tractor of ≥ the required length.

**A2. Mixed-suit throws are accepted and route through the PENALTY path (cells 3.14, 3.15) — D16 target**
Already in the spec's suspected-bug list, but the *penalty* half is new detail.
*Observed:* `A♠ + A♦` accepted; `led_suit` is `'spades'` for `[A♠,A♦]` and `'diamonds'` for
`[A♦,A♠]` — same two cards, different obligation for every follower. With `K♠ + A♦` and an
opponent holding `A♠`, the engine reports `throw_failed=True`, forces `K♠`, and charges a
20-point penalty. D16 rules a mixed-suit throw is a **malformed lead** to reject outright, so
today's behavior both accepts an illegal lead *and* mis-applies R71's penalty to it.

**A3. Trick-winner eligibility is order-dependent (spec suspected-bug 2) — D17 target**
Reproduced and **extended to 3-card throws**, which the spec did not record.
*Observed:* spade throw `A♠ + K♠K♠` led; a void follower playing `[4♥,4♥,6♦]` **wins**, while
`[6♦,4♥,4♥]` — the identical multiset — **loses**. The winning play is 2 trumps + 1 junk, which
pagat says can never take a throw. Root cause `_play_strength` reading `ctx.effective_suit(cards[0])`
(`engine/tricks.py:783`).

**A4. Friend-declaration ordinals are unvalidated (cells 6.8, 8.19) — D20 target**
*Observed:* ordinals `0`, `3`, `5`, and `-1` are all **accepted**; the phase advances normally
and the round silently becomes an unwinnable 1v3. Uncovered by both the committed suite and
the in-flight fuzz harness — the only Dimension-8 gap neither report closes.

**A5. No-trump tractor gap (cell 2.15) — D18 target**
*Observed:* `2♥2♥ + SJ SJ` under no-trump → `Throw`; the same shape with hearts trump →
`Tractor`. `SJ SJ + BJ BJ` is a tractor in both. Confirms the ladder's empty tier 3.

**A6. `revealed_friends` / `friend_declarations` leak across rounds (cell 6.26) — D21 target**
*Observed:* after `start_dealing`, `revealed_friends == {'p2'}` and the previous round's
declaration survive; `to_player_view('p1')` returns both, so during round N+1's deal every
player can read round N's friend identity and declared card.

### Tier B — zero-coverage rules whose behavior is correct (pin tests)

**B1. Tractor components in throw validation — R40 / D08 (cells 3.6-3.10).** The entire
tractor branch of `_single_opp_beats_component` has **no test**. Probed and all four sub-rules
behave correctly: equal-length higher tractor beats; **longer** higher tractor beats (D08, the
whole point of the decision); longer-but-lower does not; two opponents cannot combine. Highest
pin-value gap in the report — D08 is an on-record decision with zero regression protection.

**B2. D07 — the thrower's partner counts (cell 3.11).** Probed at engine level: p0 throws
`K♠+Q♠`, partner p2 holds `A♠` → `throw_failed=True`. Now an on-record decision (Q7) with no
test.

**B3. R26 — buried cards excluded from throw validation (cell 3.12).** Probed: both `A♠` in
the bottom, `K♠+Q♠` thrown → valid, no penalty. Guards against a plausible future refactor that
passes the bottom into `all_hands`.

**B4. Throw penalties accumulate; forced component may be a PAIR (cells 3.22, 3.23).** Probed:
two failed throws by p0 → `{'p0': 40}`; throw `Q♠Q♠+A♠` against `K♠K♠` forces the **pair**
`Q♠Q♠` with penalty 30. Every existing penalty test forces a single and throws once.

**B5. R83 — the +0 takeover band never ends the game (cell 7.12).** Probed: 90 points, both
defenders at Ace → `winner='attacking'`, `steps=0`, `game_over=False`. R83 exists specifically
for this case and only the +3 variant is tested.

**B6. D19 — Find Friends game over on a friend's level (cells 7.15, 7.16).** Probed: leader at
rank 5, revealed friend at Ace, defenders win → `game_over=True`. This was interviewed and
*confirmed as intended*, so it needs a pin before any Phase 5 refactor of `end_round`.

**B7. R68 — bottom multiplier from a THROW winning play (cell 5.14).** Probed:
`pair+single`→×4, `tractor(4)+single`→×8, `2 singles`→×2. The `Throw` branch of
`_format_component_cards` (`engine/scoring.py:53-54`) is untested.

**B8. Find Friends × bottom multiplier interaction (cells 5.21, 5.22).** Probed both
directions: friend wins the last trick as a defender → bottom suppressed, `attacking_points=0`;
attacker wins after a reveal → `5 + 2×20 = 45`. D15 correctly reads *final* teams.

**B9. R7 at engine level — no-trump TR cards can't follow their natural suit (cells 1.6, 1.7).**
Probed: holding `2♥` under no-trump, the player is treated as void in hearts (may play anything
to a hearts lead) and *must* play the `2♥` to a trump lead. This is the Session-24 fix with no
follow-level regression test.

**B10. R32 — the leader's own copies count toward the ordinal (cell 6.14).** Probed: ordinal 2,
leader plays copy 1 (no reveal), p1 plays copy 2 → p1 becomes the friend.

**B11. R13 + R25 — bid cards stay in hand and may be buried (cells 4.27, 5.7).** Probed
end-to-end through `place_bid` → `close_bidding` → `exchange_bottom`.

**B12. R80 — Find Friends lone leader wins, scan wraps to themself (cell 7.22).** Probed:
leader p2 defending alone wins → `next_round_leader_id == 'p2'`. Follows R80 literally, but it
means the same seat leads two rounds running and the trump rank jumps by their full
advancement. **Flag for the Phase 4 decisions interview** — this may be intended, but it is
undocumented and unasserted.

### Tier C — nice-to-pin (correct, lower risk)

**C1. Tractor(2,3) follows (cell 1.27)** — every committed tractor-follow test uses
`Tractor(2,2)`. Probed 3 hand shapes; obligations are correct in each.
**C2. Longer-tractor-held vs a shorter tractor lead (cell 1.20)** — probed `A♠A♠K♠K♠Q♠Q♠` vs
`Tractor(2,2)`: exactly the two adjacent sub-tractors validate, `AAQQ` does not.
**C3. Void / short follows may break the follower's own pairs (R49; cells 1.16, 1.25, 1.26)** —
probed; R49 is stated in the spec but nothing asserts it.
**C4. Trump-hierarchy tractors of length 3 and 5 (cells 2.17, 2.18)** — `2♥2♥ SJ SJ BJ BJ` →
`Tractor(2,3)`; `A♥A♥ 2♠2♠ 2♥2♥ SJ SJ BJ BJ` → `Tractor(2,5)`.
**C5. Trump-suit TR-skip adjacency (cell 2.7)** — TR 5 / hearts: `4♥4♥ 6♥6♥` → `Tractor`. Only
the tier-0 version of this rule is tested.
**C6. A-3-4 wrap splits (cell 2.4)** — a second, simpler instance of the documented 3-position
wrap limitation than the pinned K-A-3 case.
**C7. Wrap A-2 at TR 3 (cell 2.2)** — the circular wrap is only pinned at TR 2.
**C8. Three TR pairs at once (cell 2.21)** — `2♠2♠ 2♦2♦ 2♣2♣` → `Throw[Tractor, IdenticalGroup]`.
**C9. Level clamp from J / K / A (cell 7.8)** — only the Q+3 clamp is pinned.
**C10. Pair lead over a TRIPLE / choosing among 3 pairs in a throw (cells 1.11, 1.33)**.
**C11. All-pass keeps the bottom hidden with no fallback trump (cell 4.23, D05)** — currently
only inferred from the draw-pile size.

### Unreachable / no action

- Quads and triples of one identity (cells 1.12, 2.19, 2.22, 5.15) — impossible with 2 decks;
  reachable only through the superuser tools.
- `_assign_throw_components` silent-pass path (cell 3.17) — probed several tractor-heavy
  throws, never reproduced. Confirms the spec's suspected-bug 7 assessment.
- Find Friends thrower flipping defender → attacker (cell 3.28) — reveals only move players
  toward defending.
- R17 bidding close (cell 4.29) — lives in `network/handler.py`.

---

## New suspected bugs (not in `docs/RULES.md`'s suspected-bugs list)

1. **NEW-1 (Tier A1) — a throw-lead follow with two equal-length tractors forces the weakest
   one.** `engine/tricks.py:398-427`. Fully reproduced through `GameEngine.play_cards`. Makes
   R46 and R47 disagree and hands the follower's tactical choice to `find_tractors`' scan
   order.
2. **NEW-2 (detail on A2) — a mixed-suit throw with a beatable component is charged a throw
   penalty.** `engine/engine.py:611-640`. D16 classifies mixed-suit throws as malformed leads;
   R71's penalty is defined only for *beatable single-suit* throws, so the current path applies
   the wrong remedy to an illegal action.
3. **NEW-3 (detail on A3) — the trick-eligibility order dependence also lets a 2-trump + 1-junk
   play win a 3-card throw lead.** The spec recorded only the 2-card `[trump, junk]` case;
   `[4♥,4♥,6♦]` beating `A♠+K♠K♠` shows the same hole at throw sizes where the play genuinely
   matches the led component structure, so D17's fix has to consider suit purity, not just
   ordering.
4. **NEW-4 (behavioral question, not clearly a defect) — in Find Friends, a lone leader who
   defends successfully is re-selected as the next round leader.** `modes/find_friends.py:147-156`.
   R80's scan wraps back to the leader when nobody else is on the winning team. Worth putting to
   Jeffrey in Phase 4 alongside the other forks.
