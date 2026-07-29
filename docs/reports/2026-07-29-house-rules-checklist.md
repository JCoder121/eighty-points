# House-rules checklist — what the engine actually does

**Date:** 2026-07-29 · **Status:** report only, no code or docs changed.

**Purpose.** Jeffrey asked to confirm his house rules still hold, flagging one he remembers as
"10 points for a level skip, instead of 20". This document lays out what is *implemented*,
what each source *says*, and where his memory could diverge from the record. It does not
decide who is right — Section C is the list of things only Jeffrey can settle.

**Method.** Every line below was checked against the engine source, and the scoring table was
probed empirically (`compute_rank_advancement` called directly at every band edge, results
inline in A1). File citations are `path:line` into `src/shengji/`.

**Baseline for "house rule".** `robertying.com/shengji/rules.html` — Jeffrey's original rules
source. A house rule is a deliberate deviation from it. `pagat.com` is used only as a
completeness checklist (per `docs/RULES.md` authority order).

---

## A. Confirmed house rules as implemented

**23 rules confirmed.** Each line: rule → exact current behavior → source decision → engine
citation.

### Scoring and level advancement

**A1 — Band width is 20 points, not 10.**
Threshold 80; every band is exactly 20 points wide. Probed empirically at and around every
edge (`compute_rank_advancement(p)`):

| points | 0 | 19 | 20 | 39 | 40 | 59 | 60 | 79 | 80 | 89 | 90 | 99 | 100 | 119 | 120 | 139 | 140 | 200 | 360 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| winner | def | def | def | def | def | def | def | def | att | att | att | att | att | att | att | att | att | att | att |
| levels | +4 | +4 | +3 | +3 | +2 | +2 | +1 | +1 | +0 | +0 | +0 | +0 | +1 | +1 | +2 | +2 | +3 | +3 | +3 |

Stated exactly: **from 80, each additional 20 attacking points buys the attackers one more
level** (100 → +1, 120 → +2, 140 → +3 and no further). Below 80, **each 20 points the
attackers fall short buys the defenders one more level** (79 → +1, 59 → +2, 39 → +3,
19 → +4). Note the probed values Jeffrey's memory would change: **89, 90, 95 and 99 are all
attacking +0 today** — the attackers take over at the same rank and gain nothing.
*Source:* Session 23 (PROGRESS.md: "Rank skip step reduced from 40 to 20 points (threshold
stays at 80)") + cap #51. *Engine:* `engine/scoring.py:142-152` — `step = 10 * n_decks` = 20
for the 2-deck game; `threshold = 40 * n_decks` = 80.

**A2 — 80 points is the win threshold for attackers.**
`< 80` → defenders win the round; `>= 80` → attackers win (possibly at +0).
*Source:* Session 23, unchanged from robertying. *Engine:* `engine/scoring.py:142, 145`.

**A3 — Attacking advancement is hard-capped at +3.**
Probed: 140, 200, 360 all return `("attacking", 3)`. Without the cap the bottom multiplier
(which can push a total past 300) used to jump a team from rank 2 to rank K in one round.
*Source:* on-record #51. *Engine:* `engine/scoring.py:151` — `min(3, ...)`.

**A4 — Defending shutout is +4, and there is no cap on the defending side.**
0-19 attacking points → defenders advance 4 levels. This **overrides robertying**, which
gives defenders +3 for a zero-point round. The defending side has no `min()` — +4 is simply
the top band, because the bands run out at 0 points.
*Source:* Session 23 bands (on record). *Engine:* `engine/scoring.py:145-147`.

**A5 — Only the winning team advances, all its members by the same number of levels.**
*Engine:* `engine/engine.py:825-827`.

**A6 — Advancement clamps at Ace; it never overflows past it.**
A +3 from King lands on Ace.
*Source:* D14 (engine position). *Engine:* `models/player.py:29-41`.

### Game over

**A7 — The game ends only when the defending team wins a round while **already** at Ace going
in.** The check reads pre-advancement ranks, so a team that advances *into* Ace does not win —
they earn the right to defend at Ace next round.
*Source:* on-record #52. *Engine:* `engine/engine.py:844-850` (`pre_advance_ranks[pid] ==
Rank.ACE.value`).

**A8 — The `80-99` attacking band (+0) can never end the game.** `winner == "attacking"`
means the defenders lost, so the game-over branch is not entered at all.
*Source:* follows from #52. *Engine:* `engine/engine.py:845` (`if winner == "defending"`).

**A9 — Game over fires if **any** member of the winning defending team was at Ace.**
In Upgrade this is unambiguous (partners share a level). In Find Friends it can fire on a
*revealed friend's* level rather than the round leader's — a leader at level 5 who
successfully defends alongside a friend sitting at Ace ends the game, even though nobody
defended Ace.
*Source:* D19, ruled by Jeffrey 2026-07-29 as intended. *Engine:* `engine/engine.py:846-850`.

### Bottom (底牌) multiplier

**A10 — The bottom scores only when an attacker wins the final trick.**
If a defender wins the last trick the bottom contributes nothing to anybody.
*Source:* D15 (engine position — see Section B; robertying's text is garbled here and the
engine follows pagat). *Engine:* `engine/scoring.py:101`.

**A11 — The multiplier is 2 × the card count of the largest component of the **winning play**,
capped at 8.** Probed: single → 2×, pair → 4×, 4-card tractor → 8×, 6-card tractor → 8×
(cap). Set by the winning play alone — not the whole 16-card pile, and not the lead if the
lead lost.
*Source:* on-record #57. *Engine:* `engine/scoring.py:36-55, 102-106`.

**A12 — Multiplied amount = multiplier × the point value of the 8 buried cards.**
A bottom with no point cards adds nothing regardless of the multiplier.
*Engine:* `engine/scoring.py:100-106`.

### Failed throws (甩牌)

**A13 — A failed throw is not rejected.** The engine forces the leader to lead a reduced play;
the rest of the attempted cards stay in hand and may be played later.
*Source:* on-record #60. *Engine:* `engine/engine.py:629-650`.

**A14 — The forced play is the smallest beatable component: fewest cards first, tie broken by
weakest (lowest maximum card strength).**
*Source:* #60. *Engine:* `engine/engine.py:638-644`.

**A15 — Penalty = 10 points × the number of cards in the ATTEMPTED throw.**
Not the withdrawn cards, not the beatable components. Multiple failed throws by the same
player in a round accumulate.
*Source:* #60. *Engine:* `engine/engine.py:635, 645-647`.

**A16 — Penalties are attributed at round end by FINAL team membership.**
Defender thrower → `attacking_points += penalty`; attacker thrower → `attacking_points -=
penalty`; the total is then clamped at 0. A Find Friends reveal after the throw is therefore
respected.
*Source:* #60 + D13 (clamp). *Engine:* `engine/engine.py:806-815`.

**A17 — Deliberately failing a throw to withhold a declared friend card is a legal gambit.**
The forced component substitutes, the friend card returns to hand unrevealed, and the
10 pts/card penalty is the price.
*Source:* D25, confirmed by Jeffrey 2026-07-29. *Engine:* emergent from
`engine/engine.py:629-650` × `modes/find_friends.py:96-130`.

**A18 — Throw legality is judged against all three other hands, including the thrower's own
partner (Upgrade) and any unrevealed friend (Find Friends).**
So in Upgrade a throw fails when your *partner* holds the beating card.
*Source:* D07, confirmed on record by Jeffrey 2026-07-29 (Q7). *Engine:* `engine/engine.py:632`.

### Formats and play

**A19 — A pair means two identical cards (same rank AND same suit).**
Two equal-strength off-suit trump-rank cards (2♦ + 2♣ at rank 2) are *not* a pair anywhere:
not for leading, not for bidding, not for tractors, not for throw checks. Strength ties are
unchanged — those two cards still tie for trick-winning.
*Source:* on-record #50. *Engine:* `models/groups.py:72-95, 127-131, 193-194`;
`engine/engine.py:247-273` (bids).

**A20 — Tractor adjacency requires the two cards to share an effective suit, and adjacency
means "no occupied strength position lies strictly between them" (not "one tier up").**
Consequence: in no-trump, a trump-rank pair and a Small-Joker pair *do* form a tractor, same
as in a suited round; and `3♠3♠ + 4♦4♦` is a Throw, never a Tractor.
*Source:* D22 + D18, ruled 2026-07-29. *Engine:* `models/trump.py:109-139`.

**A21 — A lead must be a single effective suit; a cross-suit lead is rejected outright with an
error, and is NOT a throw-penalty case.** The check runs before classification, so cross-suit
card sets can never be led in any format.
*Source:* D16, ruled 2026-07-29. *Engine:* `engine/engine.py:613-623`.

### Round structure

**A22 — In rounds 2+ the round leader is rotation-determined; bidding fixes only the trump
suit.** Only in round 1 does the winning bidder become the round leader. In rounds 2+ the bid
winner may be an *attacker*, and the predetermined defender still exchanges the bottom and
leads trick 1. The next leader is the first player counter-clockwise from the current leader
who is on the winning team.
*Source:* on-record Session 26 ("R2+ leader is rotation-determined (bid only fixes trump) —
intended") + D24 (a lone Find Friends leader who defends successfully is re-selected).
*Engine:* `engine/engine.py:414-418`; `modes/upgrade.py:78-99`; `modes/find_friends.py:139-160`.

**A23 — Find Friends: the leader declares 1 friend card + ordinal (1st or 2nd copy) before
seeing the bottom; the round is 1-versus-3 when the declaration is unreachable.**
The leader may legally declare a card they hold themselves, and the declared card may turn out
to be buried. 1v3 arises only when no other player can ever play the k-th copy. Ordinals
outside 1..2 are rejected with `ValueError` (D20). Jokers, trump-rank cards, and trump-suit
cards may not be declared. Friend state (`revealed_friends`, `friend_declarations`, play
counters) is cleared at every deal (D21). Points a player captured *before* being revealed
move retroactively to the defending side (D12).
*Source:* on-record Session 26 ("Self-friend / friend-in-bottom → leader 1v3 — intended") +
D11, D12, D20, D21. *Engine:* `modes/find_friends.py:51-130`; `engine/engine.py:183-188`
(clear); `engine/engine.py:98-115` (retroactive recount).

---

## B. Deviations never explicitly ruled by Jeffrey

These are the rules whose `docs/RULES.md` source annotation is an **engine position** (D01-D06,
D08-D15, D22) rather than an interview decision or robertying. Most are gap-fills where
robertying is silent. Four are worth Jeffrey's eyes because they change play or override a
source; the rest are listed for completeness.

### B1 — Genuine deviations with gameplay impact (recommend ruling)

**B1a — The bottom scores nothing when a DEFENDER wins the last trick (D15).**
`docs/RULES.md` R67 records that robertying's summary "is garbled here and is overridden by
the engine's position, which matches pagat" (kitty bonus only when the opponents take the last
trick). This is the single largest un-ruled scoring behavior: in a round where the defenders
close out the last trick, a bottom stuffed with kings is simply dead. Nobody has confirmed
this is how Jeffrey's group plays. *Engine:* `engine/scoring.py:101`.

**B1b — Find Friends bans trump-SUIT cards as friend cards (D11).**
robertying bans jokers and trump-rank cards only. The trump-suit ban is an engine addition
that shrinks the declarable space by a full suit. *Engine:* `modes/find_friends.py:88-90`.

**B1c — All-pass causes a full re-deal; the bottom is never turned face-up (D05).**
pagat's fallback (reveal a bottom card to derive a trump) is not implemented. Same leader,
same trump rank, fresh shuffle. *Engine:* `engine/engine.py:404-411`.

**B1d — The tier-0 circular wrap (A and 3 adjacent) has no cited source at all, and it is
fragile.** `docs/RULES.md` R8 states that with trump rank 2, Ace and 3 of the same non-trump
suit are adjacent for tractor purposes — with no source annotation. It is also only detected
when the two wrapped positions are the *only* pair positions in tier 0: `A♠A♠ 3♠3♠` is a
tractor, but `A♠A♠ 3♠3♠ 8♠8♠` is three loose pairs (Known limitation 1, pinned by test). This
affects throw beatability, follow obligations, and the bottom multiplier for such plays.
*Engine:* `models/trump.py:133-136`; `models/groups.py:108-114, 131-152`.

### B2 — Un-ruled positions where robertying is silent (low risk, listed for completeness)

- **D01** trump rank = the round leader's individual level (governs even in Find Friends,
  where team levels diverge). `engine/engine.py:338`.
- **D02** bidding runs during and after the deal; bid cards are shown, not spent.
- **D03** bid ladder: suited single < suited identical pair < Small-Joker pair < Big-Joker
  pair, with no suit precedence at equal strength.
- **D04** a player may override their **own** bid if strictly stronger — pagat forbids this;
  robertying is silent. `engine/engine.py:275-297`.
- **D06** burying is unrestricted: point cards, trump, and the shown bid cards may all go into
  the bottom. `engine/engine.py:473-484`.
- **D08** a throw's tractor component is beaten by a *longer* opposing tractor as well as an
  equal-length one.
- **D09** degraded follows (right card count, wrong shape) can never win a trick, even when
  strictly stronger.
- **D10** to win a throw lead, a play must match the throw's component structure
  component-for-component.
- **D12** point attribution is retroactive on friend reveal.
- **D13** the final attacking total is clamped at 0 after penalties.
- **D14** level advancement clamps at Ace.
- **D22** suit-aware tractor adjacency — recorded without an interview because robertying,
  pagat, and the on-record decisions all require single-suit plays; it is a deviation from
  *previous engine behavior*, not from a source.

Also un-ruled and documented as a limitation: **throw components are decomposed greedily**
(maximal tractors, then identity groups, then singles), so a play with more than one valid
decomposition is judged against the greedy one only.

---

## C. Questions for Jeffrey

### C1 — 10-point bands or 20-point bands? (the one you flagged)

**The conflict.** You remember 10 points per level skip. The on-record Session 23 decision
says the step was changed **from 40 to 20**, threshold unchanged at 80. `docs/RULES.md` R76
and `engine/scoring.py` both implement 20, and the band edges are pinned by ~20 assertions in
`tests/test_engine/test_scoring.py` plus a redundant implementation in the fuzz harness.

**Worked comparison.** Same round outcomes, two rules. "10-pt" here means step = 10 with the
80 threshold kept and the +3 attacking cap kept:

| attacking points | current (20-pt bands) | under 10-pt bands |
|---|---|---|
| 0 (shutout) | defending **+4** | defending **+8** |
| 35 | defending +3 | defending **+5** |
| 75 | defending +1 | defending +1 |
| 80 | attacking +0 | attacking +0 |
| 85 | attacking +0 | attacking +0 |
| **95** | attacking **+0** | attacking **+1** |
| 105 | attacking +1 | attacking **+2** |
| 115 | attacking +1 | attacking **+3** (cap) |
| 125 | attacking +2 | attacking +3 |
| 145 | attacking +3 | attacking +3 |

The recognizable difference at the table: **does a round where the attackers scrape 95 points
advance them a level, or do they just take over at the same rank?** Today it is take-over at
the same rank. Second tell: **how many levels does a shutout give the defenders?** Today it is
+4; a straight 10-point step makes it +8.

**A possible explanation for the memory.** The engine parametrizes the table as
`threshold = 40 × n_decks`, `step = 10 × n_decks` (`engine/scoring.py:142-143`). For a
**single-deck** game those are exactly threshold 40 and **step 10**, and the same four bands
come out (probed: `compute_rank_advancement(10, n_decks=1)` → defending +3,
`(20, n_decks=1)` → defending +2). So "10 points per skip" is the correct number for a
one-deck game and for the formula's shape — it may be that memory rather than a different
house rule for the 4-player, 2-deck game. **Please confirm which of these three you actually
play:** (i) 20-pt bands as implemented, (ii) 10-pt bands with the 80 threshold — noting that
this makes a shutout +8 unless the defending side also gets a cap, (iii) something else, e.g.
10-pt steps on the attacking side only.

**What a change would touch** (nothing has been changed):
- `src/shengji/engine/scoring.py:142-152` — the `step` constant and the docstring table
  (the docstring is duplicated at lines 13-16 and 126-140).
- `docs/RULES.md` R76 (band table + the formal `ceil`/`//` statement) and the scoring line in
  `CURRENT_STATE.md`.
- `tests/test_engine/test_scoring.py:33-108` — ~20 band-edge assertions, including the
  `n_decks=1` cases which would need re-deriving.
- `tests/test_fuzz/fuzz_helpers.py:338-343` — `expected_advancement`, the independent
  re-implementation the fuzz invariant battery cross-checks against
  (`tests/test_fuzz/test_invariants.py:139-142`).
- `tests/test_engine/test_pins_bottom_multiplier.py:207` — the "big multiplier still caps at
  +3" pin.
- If the defending side would exceed +4, `models/player.py:29-41` (Ace clamp) and the
  game-over interaction in `engine/engine.py:844-850` need a fresh look — a +8 can carry a
  team from 2 to 10 in one round.

### C2 — Should a defender winning the last trick really kill the bottom entirely? (B1a)

Today, if a defender takes trick 25, the bottom's points score for nobody — not the attackers,
not the defenders. This is the engine following pagat over a garbled robertying passage, and
it was never put to you. The alternative many groups play is that the bottom points go to the
**defenders** in that case (or that the bonus simply does not exist). Which is it at your
table?

### C3 — Does a shutout really give the defenders +4, or +3? (A4)

robertying says a zero-point round gives the defenders +3. The Session 23 bands you signed off
give +4 (0-19 → +4). This one *is* on record, so it is likely deliberate — but it is a direct
override of your original source, and it is exactly the kind of thing worth re-confirming
while you are checking the table. Note this question is entangled with C1: if the bands change
width, the shutout number changes with them.

### C4 — Can a Find Friends friend's level end the game? (A9 / D19)

You ruled this "yes, keep current behavior" on 2026-07-29. Restating it because it is
surprising in play: a round leader sitting at level 5 who successfully defends, with a
mid-round-revealed friend who happens to be at Ace, **ends the game** — and the friend never
defended their own level. Confirm this is what you want, or gate it on the round leader's
level only (the level actually being defended).

### C5 — In Find Friends, may the leader declare a trump-suit card as the friend card? (B1b)

The engine bans it; robertying bans only jokers and trump-rank cards. Was the trump-suit ban
your intent, or an engine addition to remove?

### C6 — Two smaller un-ruled ones

- **All-pass → full re-deal, bottom never revealed** (B1c). Confirm you do not use the
  variant where a bottom card is turned face-up to set trump.
- **A throw fails when your own partner holds the beating card** (A18 / D07). You confirmed
  this on 2026-07-29, so it is on record — flagged only because it is the rule most likely to
  feel wrong at the table (your partner would never actually challenge you).

### C7 — Is there a house rule you play that is not in this document at all?

`docs/RULES.md` covers R1-R84 and D01-D26 and nothing in the engine sits outside it. But the
audit can only verify rules that exist in code — a rule your group plays that was never
implemented would be invisible to this exercise. The likeliest places for such a gap, based on
what the sources cover and the engine does not: bidding by "grabbing" or re-bidding after the
bottom, restrictions on burying point cards (D06 allows anything), a defender's obligation to
play high in the last trick, and any bonus for winning every trick.
