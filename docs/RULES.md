# Shengji (升级 / 80 Points) — Authoritative Rules Specification

This document is the **audit target** for the engine-verification campaign described in
`VERIFICATION_PLAYBOOK.md`. It is written to be precise enough that an independent test
oracle can be built from this file alone, without reading the engine.

## Authority order

When sources disagree, the higher-numbered source loses:

1. **Jeffrey's on-record interview decisions** — GitHub issue numbers (#50, #51, #52, #57, #60)
   and the "Interview decisions (authoritative)" block in `PROGRESS.md` (Session 26).
2. **The primary reference** — `robertying.com/shengji/rules.html`, Jeffrey's original rules
   source.
3. **pagat.com** (Tractor/80 Points and Zhao Pengyou pages) — used **only as a completeness
   checklist** to enumerate rule surface the primary source does not address. Pagat never
   overrides 1 or 2 and its player-count/deck-count tables do not apply here.

## Scope

- **4 players, 2 decks (108 cards), 25-card hands, 8-card bottom**, in both modes:
  **Upgrade** (升级, fixed seat partnerships) and **Find Friends** (找朋友, fluid teams).
  Variable player counts and deck counts are out of scope.
- **Engine rules only**: dealing, bidding/trump declaration, bottom exchange, friend
  declaration, lead/follow legality, trick winning, point capture, bottom multiplier, throw
  penalty, level advancement, game over. UI and network behavior are out of scope except
  where a rule is *implemented* in the network layer — those cases are called out explicitly
  as known limitations.

## Terminology

- **Defending team** — the team of the round leader (the player who exchanges the bottom).
  They are defending their current level. Also called "declarers" in pagat.
- **Attacking team** — everyone else. They are the ones who capture points; the single
  round score `attacking_points` is *their* total.
- **Round leader** (`round_leader_id`) — the player who exchanges the bottom, declares
  friends in Find Friends, and leads trick 1.
- **Trump rank** — the rank that is trump this round (the round leader's current level).
- **Trump suit** — the declared suit, or `None` in no-trump.
- **Component** — one maximal format unit (single / pair / tractor) inside a throw.

Rules are numbered **R##**. Documented engine positions are numbered **D##** and collected in
`## Documented decisions`. The forks originally listed as open questions were all ruled on by
Jeffrey in the 2026-07-29 interview — see `## Resolved forks` (D16-D21; Q7 confirmed D07).

---

## Setup

**R1** — The deck is exactly two standard 54-card decks combined: 4 suits × 13 ranks
(2,3,4,5,6,7,8,9,10,J,Q,K,A) plus a Small Joker and a Big Joker, each appearing twice.
Total 108 cards. No card identity (suit+rank) may ever appear more than twice in the game.
*Source:* robertying (one 54-card deck per two players); pagat. *Engine:*
`models/deck.py:8-23`, `models/card.py:34-51`.

**R2** — There are exactly 4 players, seated so that index order in `state.players` is
counter-clockwise. Play, dealing, and turn order all advance by `index + 1 (mod 4)`.
*Engine:* `models/deck.py:8`, `engine/engine.py:117-125`.

**R3** — Each player receives 25 cards; 8 cards form the bottom (底牌). 4 × 25 + 8 = 108.
*Engine:* `models/deck.py:10-12`.

**R4** — Point cards: every 5 is worth 5 points, every 10 is worth 10 points, every King is
worth 10 points. All other cards are worth 0. Total points in the deck = 200
(8 fives = 40, 8 tens = 80, 8 kings = 80). *Source:* robertying; pagat. *Engine:*
`models/card.py:54-58, 72-74`.

**R5** — Every player has an individual **level** (rank) from the sequence
2,3,4,5,6,7,8,9,10,J,Q,K,A. All players start at 2. A level never decreases and never
advances past Ace (advancement is clamped). *Engine:* `models/player.py:29-41`,
`models/card.py:34-48`.

**R6 (card strength)** — Given trump rank `TR` and trump suit `TS` (possibly `None`), each
card has a strength key `(tier, position)`, compared lexicographically, higher is stronger:

| tier | cards | position |
|---|---|---|
| 5 | Big Joker | 0 |
| 4 | Small Joker | 0 |
| 3 | the trump-rank card **of the trump suit** (only when `TS` is set) | 0 |
| 2 | trump-rank cards of the other three suits — **all mutually equal** | 0 |
| 1 | non-trump-rank cards of the trump suit (only when `TS` is set) | index in `RANK_ORDER` with `TR` removed (0 = lowest) |
| 0 | all other suited cards | index in `RANK_ORDER` with `TR` removed |

Aces are high (position 11 of 12 after removing `TR`). Two cards with the same key are
interchangeable for trick-winning; ties are broken by play order (R56).
*Source:* robertying (trump = rank cards + jokers + declared suit); pagat hierarchy.
*Engine:* `models/trump.py:48-67`.

**R7 (effective suit)** — For following purposes each card belongs to exactly one *effective
suit*: `"trump"` for jokers, for **all** trump-rank cards (including off-suit ones, and
including no-trump mode), and for trump-suit cards; otherwise the card's natural suit.
Consequence: in no-trump mode a trump-rank card can **never** be used to follow its natural
suit — a player holding only 2♥ (rank 2 trump) is void in hearts.
*Engine:* `models/trump.py:69-83` (Session 24 fix).

**R8 (adjacency, for tractors)** — Two cards occupy *adjacent* strength positions iff they
share an **effective suit** (D22 — cross-suit pairs never chain) and, with their keys
normalised so `k1 ≤ k2`:
  - same tier and `pos2 == pos1 + 1`; **or**
  - tier 0 only: the circular wrap `pos1 == 0` and `pos2 == 11` (so with `TR = 2`, Ace and 3
    of the same non-trump suit are adjacent); **or**
  - inside trump (tiers 1-5): the two positions are neighbouring rungs of the trump ladder
    with **no occupied position strictly between them** (D18) — in particular, in no-trump
    the empty trump-suit-rank rung (tier 3) is skipped, so a trump-rank pair and a
    Small-Joker pair are adjacent.

Tier 0 and tier 1 are **never** adjacent (a non-trump suit cannot form a tractor with trump;
with D22 this also follows from the suit requirement). The circular wrap exists **only** in
tier 0 — inside the trump suit, A and 3 are not adjacent. *Engine:* `models/trump.py` (D22/D18
implemented 2026-07-29). See `## Known limitations` for the wrap fragility.

---

## Dealing & Bidding

**R9** — Before dealing, the 108-card deck is shuffled; the **last 8 cards** are set aside
as the bottom and the remaining 100 form the draw pile. The bottom is therefore fixed before
any card is dealt and is never seen by anyone until the bottom exchange.
*Engine:* `models/deck.py:41-53`.

**R10** — Cards are dealt one at a time, starting with the player **immediately
counter-clockwise from the round leader**, cycling until the draw pile is exhausted (25 each).
*Engine:* `engine/engine.py:208-216`.

**R11** — In round 1 the round leader is a placeholder (the room creator) whose only effect
is to fix the trump rank (all players are at level 2, so the trump rank is 2) and the deal
start position; the actual round leader is replaced by the bid winner in R18.
*Engine:* `network/room.py:104`, `engine/engine.py:409-411`.

**R12 (trump rank)** — The trump rank for a round is the **round leader's current level**
(D01). It is fixed for the whole round and cannot be changed by bidding.
*Engine:* `engine/engine.py:338`.

**R13 (bidding window)** — Bids may be placed while cards are still being dealt (`DEALING`)
and after the deal completes (`BIDDING_AFTER_DEAL`). Bid cards are **shown, not spent** —
they stay in the bidder's hand and are played normally later (D02).
*Engine:* `engine/engine.py:327-331`, and `place_bid` never removes cards.

**R14 (legal bid shapes)** — A bid is exactly one of:
  - **1 card**: a single suited card of the trump rank → declares that card's suit as trump.
  - **2 cards**: two **identical** trump-rank cards (same rank *and* suit) → declares that suit.
  - **2 cards**: two Small Jokers, or two Big Jokers → declares **no-trump** (`trump_suit = None`).

A single joker is never a legal bid. A "pair" of two different trump-rank cards
(e.g. 2♦ + 2♣) is not a legal pair bid (#50 identity rule). The bidder must actually hold the
cards. *Source:* robertying (identical cards, single joker invalid); pagat.
*Engine:* `engine/engine.py:247-273, 343-350`.

**R15 (bid strength)** — Strength ladder: suited single = 1 < suited identical pair = 2 <
Small-Joker pair = 3 < Big-Joker pair = 4 (D03). *Engine:* `engine/engine.py:228-245`.

**R16 (overriding)** — A new bid is legal iff it is **strictly stronger** than the current
highest bid. Equal strength never overrides (a single cannot override another single; a
suited pair cannot override a suited pair, in any suit). A player may override **their own**
bid, including raising their own single to a pair (D04). *Engine:* `engine/engine.py:275-297`.

**R17 (bidding closes)** — Bidding closes when all four players have passed. The bidder of
the current highest bid is automatically counted as having passed, so a bid followed by three
passes closes bidding. A player who explicitly passes may not bid again this round.
*Note:* this trigger is implemented in the **network layer**, not the engine — see
`## Known limitations`. *Engine/handler:* `network/handler.py:302-303, 336-350`.

**R18 (bid winner)** — The last (highest) bid wins. Its `TrumpContext` (trump rank from R12
plus the declared suit, or no-trump) becomes the round's trump context. **In round 1 only**,
the winning bidder becomes the round leader. In rounds 2+ the round leader is
rotation-determined (R80) and bidding fixes **only the trump suit** — the bid winner may be
an attacker, in which case the predetermined leader (a defender) still exchanges the bottom
and leads trick 1. *Source:* on-record interview decision (Session 26): "R2+ leader is
rotation-determined (bid only fixes trump) — intended". *Engine:* `engine/engine.py:407-412`.

**R19 (no bids)** — If nobody bids, all hands are discarded and the round is **re-dealt** from
a fresh shuffle, with the same round leader and the same trump rank. The bottom is *not*
revealed and no fallback trump is derived from it (D05 — pagat's bottom-reveal fallback is
explicitly not implemented). *Engine:* `engine/engine.py:397-405`.

**R20 (teams are assigned at bid close)** — Immediately after the bid winner is determined,
teams are assigned (R21/R22) and only then does the round proceed to friend declaration
(Find Friends) or bottom exchange (Upgrade). *Engine:* `engine/engine.py:414-422`.

**R21 (Upgrade teams)** — Seats 0 and 2 are partners; seats 1 and 3 are partners. The pair
containing the round leader defends; the other pair attacks. Teams are re-derived from the
leader's seat parity every round. *Engine:* `modes/upgrade.py:28-42`.

**R22 (Find Friends teams at start)** — The round leader defends **alone**; the other three
players all start as attackers. Team membership then changes only through friend reveals
(R32). *Engine:* `modes/find_friends.py:33-42`.

---

## Bottom (底牌)

**R23** — Only the round leader may exchange the bottom, and only in the `BOTTOM_EXCHANGE`
phase. In Find Friends this phase comes **after** friend declaration, so the leader declares
friends without having seen the bottom. *Engine:* `engine/engine.py:451-460`,
`models/game_state.py:42-52`.

**R24** — The exchange is: take all 8 bottom cards into hand (33 cards), then bury exactly 8
cards from the resulting 33. The buried 8 become the new bottom; the hand returns to 25.
*Engine:* `engine/engine.py:461-490`.

**R25** — Any 8 cards may be buried, including point cards and trump (D06). There is no
restriction on burying 5s/10s/Ks and no restriction on burying the cards that were shown as
the winning bid. *Engine:* `engine/engine.py:473-484` (no filtering).

**R26** — The bottom is hidden from every player during play, including the leader, and is
revealed only at round end. Buried cards are out of play: they never count toward following
obligations, never count as "cards an opponent could hold" for throw validation (R41), and
their points reach the score only via the bottom multiplier (R67-R70).
*Engine:* `models/game_state.py:136-139` (only the leader sees it, only during
`BOTTOM_EXCHANGE`), `engine/engine.py:612` (throw check reads hands only).

**R27** — After the exchange the phase becomes `PLAYING` and the round leader is on turn to
lead trick 1. *Engine:* `engine/engine.py:492-494`.

---

## Find Friends declarations

**R28** — In Find Friends the round leader declares exactly `n_players // 2 - 1` = **1**
friend card per round, in the `FRIEND_DECLARATION` phase, before the bottom exchange. Only
the round leader may declare. *Engine:* `engine/engine.py:521-532`,
`modes/find_friends.py:64-70`.

**R29 (declaration shape)** — A declaration is a specific card identity (suit + rank) plus an
**ordinal** *k* with `1 ≤ k ≤ 2` (D20 — ordinals outside 1..number-of-decks are rejected with
`ValueError`): the player who plays the *k*-th copy of that exact card in this round becomes
a friend. *Source:* robertying ("specific card + ordinal"); pagat ("first/second copy").
*Engine:* `models/friend_declaration.py:9-26`, `modes/find_friends.py:109-119`.

**R30 (illegal friend cards)** — A declared card may not be a joker, may not be of the trump
rank, and may not be of the trump suit. In no-trump mode there is no trump suit, so only the
joker and trump-rank bans apply. *Source:* robertying bans jokers and trump-rank cards; the
trump-suit ban is an engine addition (D11). *Engine:* `modes/find_friends.py:77-90`.

**R31** — The leader may declare a card they hold themselves, and the declared card may turn
out to be in the bottom. The round is 1-versus-3 only when the declaration is **unreachable**:
the number of playable copies of the declared card outside the leader's control is smaller
than needed for the ordinal to fire on another player (both copies buried; one copy buried
with ordinal 2; or the leader holds/buries copies such that the ordinal can only fire on
themselves). With one copy buried and the other in an opponent's hand, that opponent still
becomes the friend when their copy's play matches the ordinal (audit F2 — engine verified
correct; earlier wording here overstated the 1v3 outcome). *Source:* on-record interview
decision (Session 26): "Self-friend / friend-in-bottom → leader 1v3 — intended", scoped to
the unreachable cases. *Engine:* `modes/find_friends.py:60-62, 96-99`.

**R32 (reveal)** — Friend identity is hidden until the triggering card is actually played.
When any player plays a card matching a declaration, a per-identity play counter increments;
if the counter equals the declaration's ordinal, that player immediately becomes a defender
(`is_defending = True`) and the declaration is marked resolved. At most one friend is revealed
per card played. Counters count **every** copy played by **anyone**, including the leader.
Reveal bookkeeping (`revealed_friends`, `friend_declarations`, and the per-identity play
counters, which live on `GameState` as `friend_play_counts`) is cleared at the start of every
deal (D21), so no view carries a previous round's friend information.
*Engine:* `modes/find_friends.py`, `engine/engine.py` (`start_dealing` clears; D21 2026-07-29).

**R33 (retroactive point attribution)** — Point attribution is by **current** team membership,
recomputed over all tricks won so far at every reveal and at every trick completion.
Therefore points a player captured *before* being revealed as a friend move from the attacking
total to the defending side at the moment of the reveal (D12).
*Engine:* `engine/engine.py:98-115, 664-672, 707`.

**R34 (final teams)** — All round-end computations — point total, level advancement, throw
penalty attribution, next-leader selection, game-over check — use **final** team membership,
i.e. including every friend revealed during the round.
*Engine:* `engine/engine.py:765-766, 788-792, 803, 831-834`.

---

## Play — lead legality

**R35 (turn order)** — The trick leader plays first; the other three follow in
counter-clockwise seat order. A trick is complete when all four players have played. A player
may only play on their own turn. *Engine:* `engine/engine.py:579-583, 678-679`.

**R36 (card count)** — Every follower plays exactly as many cards as the leader played.
*Engine:* `engine/tricks.py:253-255`.

**R37 (formats)** — A play is classified into exactly one format:
  - **Single** — 1 card.
  - **IdenticalGroup(k)** — *k* copies of the **same identity** (same rank *and* suit).
    With 2 decks, `k = 2` in practice: a pair. Two equal-strength but different cards
    (e.g. 2♦ + 2♣ when 2s are trump) are **not** a pair (#50).
  - **Tractor(multiplicity=2, length=L)** — `L ≥ 2` identical pairs occupying consecutive
    strength positions per R8. With 2 decks the multiplicity is always 2.
  - **Throw** — anything else: a multi-component play, decomposed greedily into maximal
    tractors first, then identity groups, then singles.

*Source:* robertying (identical cards only, tractors are consecutive multiples); on-record
decision #50. *Engine:* `models/groups.py:167-214`, `models/groups.py:95-152`.

**R38 (what may be led)** — A lead must consist of cards of **one effective suit** (D16 —
a lead spanning more than one effective suit is rejected as malformed, with no penalty; the
check runs before classification so cross-suit card sets can never be led in any format).
Within one suit, the leader may lead a Single, an IdenticalGroup, or a Tractor from their
hand with no further restriction. A **Throw** lead is additionally subject to R39-R41.
*Engine:* `engine/engine.py` play_cards lead branch (D16 implemented 2026-07-29).

**R39 (throw definition)** — A Throw lead (甩牌) is a claim that every component of the play
is unbeatable. All components share one effective suit (enforced by R38/D16).
*Source:* robertying ("highest possible plays in suit claimed simultaneously");
pagat ("set of top cards").

**R40 (throw legality test)** — A throw is **valid** iff, for every component, no **single**
other player holds, in that component's effective suit, a play that beats it:
  - Single component: some other player holds a strictly stronger card of that effective suit.
  - IdenticalGroup(k) component: some other player holds *k* copies of one identity in that
    effective suit whose strength is strictly greater.
  - Tractor component of *n* cards: some other player holds a tractor of **≥ n** cards in that
    effective suit whose maximum card strength is strictly greater (D08).

The check is per-component and per-opponent: one opponent must beat one component by
themselves; two opponents cannot combine. *Engine:* `engine/tricks.py:517-643`.

**R41 (whose cards count)** — The throw legality test inspects the hands of **all three other
players** — including, in Upgrade, the thrower's partner, and in Find Friends, any unrevealed
friend (D07). Buried bottom cards and already-played cards are excluded (they are not in any
hand). *Engine:* `engine/engine.py:612`, `engine/tricks.py:544-551`.

An invalid throw is **not rejected** — see the throw penalty (R71-R75).

---

## Play — follow legality

A follower's obligations are computed against `led_suit` (the effective suit of the lead,
taken from the leader's first card) and `led_format`.

**R42 (suit obligation)** — A follower must play as many cards of the led effective suit as
possible, up to the number of cards required. Formally, with `n` = required card count and
`s` = the number of led-suit cards in hand, the play must contain exactly `min(s, n)` led-suit
cards. *Source:* robertying ("match suit if possible"); pagat.
*Engine:* `engine/tricks.py:264-279`.

**R43 (void / short)** — If `s < n` the follower must play **all** their led-suit cards and
may fill the remaining `n - s` slots with **any** cards from their hand (trump or otherwise),
in any shape. If `s == 0` the follower may play any `n` cards.
*Engine:* `engine/tricks.py:273-275`.

**R44 (Single lead)** — If the follower holds any led-suit card, they must play exactly one
led-suit card; **any** one of them is legal. *Engine:* `engine/tricks.py:282-283`.

**R45 (IdenticalGroup(k) lead)** — If `s ≥ k`, all played cards must be led-suit, and:
  - if the follower holds at least one identity with `≥ k` copies in the led suit, the play
    must contain some group of `k` identical cards — **any** such group, not a specific one;
  - otherwise any `k` led-suit cards are legal.

*Source:* robertying ("match format if possible"); pagat. *Engine:* `engine/tricks.py:285-299`.

**R46 (Tractor lead)** — The obligation is **structural, not card-specific**. Compute, for the
follower's led-suit cards, a greedy capacity `(tractor_cards, extra_paired_cards)`: repeatedly
take the longest available tractor (whole pairs only) until `n` cards are claimed, then count
the remaining paired cards, capped at the open slots. The proposed play must supply at least
as many tractor cards and at least as many total paired cards as the hand's capacity requires.
Which tractor and which pairs to use is the follower's choice; leftover slots may be filled
with any led-suit cards. *Source:* #48/PR 49 (structural validation).
*Engine:* `engine/tricks.py:311-367`.

**R47 (Throw lead)** — Obligations are computed per component, largest component first,
against the follower's led-suit cards, and are **structural throughout** (D23):
  - **Tractor** component of *n* cards: the play must supply at least as many tractor cards
    and at least as many total paired cards as the hand's greedy capacity toward *n*
    (R46's `(tractor_cards, extra_paired_cards)` measure, applied per component with the
    claimed cards consumed before the next component). Which tractor/pairs supply it is the
    follower's choice — with two equal-length tractors, either satisfies (pre-D23 the greedy
    claim was card-specific and forced the weakest; audit F5 / matrix NEW-1).
  - **IdenticalGroup(k)** component: structural — if the hand can still supply a group of `k`,
    the play must contain some group of `k`.
  - **Single** component: no obligation.

Any remaining slots are free-choice led-suit cards. *Source:* #25 (Session 23); D23
(2026-07-29). *Engine:* `engine/tricks.py` `_is_valid_throw_follow` (structural).

**R48** — There is no obligation to play *high*: a follower is never required to try to win a
trick, and no "must beat if able" rule exists anywhere.
*Engine:* absence of any such check in `engine/tricks.py:228-308`.

**R49** — There is no obligation on the *shape* of off-suit fill cards (R43): a short follower
may break up their own pairs or trump tractors freely.
*Engine:* `engine/tricks.py:273-275`.

**R50** — A play that violates any of R36/R42-R47 is rejected with an error and the game state
is unchanged. *Engine:* `engine/engine.py:655-659`.

---

## Play — trick winning

**R51 (eligibility — suit)** — A play is eligible to win only if **all** its cards share one
effective suit AND that suit equals the led suit or is `"trump"` (D17). A play spanning more
than one effective suit is never eligible, regardless of card order; a play counts as trump
only when every card in it is trump. Off-suit plays cannot win, including on trump leads
(the pre-D17 first-card shortcut and its trump-lead hole are removed).
*Engine:* `engine/tricks.py` `_play_effective_suit`/`_play_strength` (D17, 2026-07-29).

**R52 (eligibility — format)** — A play must also match the led format to be eligible to win
(D09 — a "degraded" follow can never win, regardless of card strength):
  - Single lead: any Single is eligible.
  - IdenticalGroup(k) lead: an IdenticalGroup of count ≥ k is eligible; a Tractor is eligible;
    two unpaired singles are **not**.
  - Tractor(m, L) lead: only a Tractor with multiplicity ≥ m **and** length ≥ L is eligible;
    loose pairs and singles are not.
  - Throw lead: the play must be decomposable so that every led component is matched by a
    play component that would be eligible against it — pair for pair, tractor for tractor,
    single for single (D10). A non-throw play is eligible only if the throw had exactly one
    component.

*Source:* pagat ("unpaired trumps cannot win a pair lead"); Sessions 11 and 24.
*Engine:* `engine/tricks.py:650-715`.

**R53 (trump beats non-trump)** — Among eligible plays, any trump play beats any non-trump
play. This falls out of R6: trump tiers (1-5) are all above tier 0.
*Engine:* `engine/tricks.py:792` combined with `models/trump.py:48-67`.

**R54 (strength of a multi-card play)** — An eligible play's strength is the strength key
(R6) of its **single strongest card**. *Engine:* `engine/tricks.py:792`.

**R55 (winner)** — The trick is won by the eligible play with the highest strength.
*Engine:* `engine/tricks.py:757-768`.

**R56 (ties)** — Strictly-greater comparison: on an exact strength tie the **earlier** play
wins. Since the leader plays first, the leader wins all ties. This is how two equal off-suit
trump-rank cards (tier 2) are resolved. *Source:* pagat ("ties → first played").
*Engine:* `engine/tricks.py:762-766`.

**R57 (capture)** — All 4 plays (all cards in the trick, regardless of who played them) go to
the trick winner's captured pile. Points are counted from those piles.
*Engine:* `engine/engine.py:690-691`.

**R58 (next leader)** — The winner of a trick leads the next one. Trick 1 is led by the round
leader (R27). The round ends when all hands are empty (25 tricks).
*Engine:* `engine/engine.py:701-712`.

---

## Scoring & points

**R59 (single running total)** — The round score is a single number, `attacking_points`: the
sum of the point values (R4) of all cards in tricks captured by players **currently** on the
attacking team. The defending team has no separate total.
*Engine:* `engine/engine.py:98-115`, `engine/scoring.py:92-97`.

**R60** — `attacking_points` is recomputed from scratch (not incrementally accumulated) at
every trick completion and at every friend reveal, so R33's retroactive attribution is exact
and there is no drift. *Engine:* `engine/engine.py:98-115, 668-672, 707`.

**R61** — Points from the bottom enter the total only through R67-R70. Points in cards buried
by the leader are otherwise not counted for anyone.

**R62** — The maximum points available from tricks is 200. With the bottom multiplier the
attacking total can exceed 200 (up to 200 + 8 × bottom points).

**R63** — In Upgrade mode the attacking team is the fixed pair not containing the round
leader, for the whole round. *Engine:* `modes/upgrade.py:28-42`.

**R64** — In Find Friends the attacking team shrinks the moment a friend is revealed (R32),
and the final split is used for round-end scoring (R34).

**R65** — Failed-throw penalties are applied to `attacking_points` after trick points are
counted — see R74.

**R66** — The final `attacking_points` is clamped to be non-negative (D13).
*Engine:* `engine/engine.py:793`.

---

## Bottom multiplier

**R67 (trigger)** — The bottom's points are added to `attacking_points` **only if a member of
the attacking team wins the final trick** (D15). If a defender wins the last trick the bottom
contributes nothing to anyone. *Source:* pagat (kitty bonus only when opponents take the last
trick); robertying's summary is garbled here and is overridden by the engine's position, which
matches pagat. *Engine:* `engine/scoring.py:99-106`.

**R68 (multiplier)** — The multiplier is `2 × (card count of the largest component of the
winning play of the final trick)`, capped at 8:
  - winning play is a single → ×2
  - winning play is a pair → ×4
  - winning play is a tractor (4+ cards) → ×8 (cap)
  - winning play is a throw → 2 × its largest component's card count, capped at 8

The multiplier is set by the **winning play only** — not by the whole 4-player pile, and not
by the lead if the lead lost. *Source:* on-record decision #57; robertying's format table
(1 card 2×, pair 4×, tractor 8×). *Engine:* `engine/scoring.py:36-55, 102-106`.

**R69** — The multiplied amount is `multiplier × (sum of point values of the 8 buried cards)`.
If the bottom holds no point cards, nothing is added regardless of the multiplier.
*Engine:* `engine/scoring.py:100-106`.

**R70** — The bottom is revealed to all players at round end.
*(Display rule, Session 24; no engine effect.)*

---

## Throw penalty

**R71 (no rejection)** — A leader's throw that fails the R40 test is **not** rejected. The
engine forces the leader to lead a reduced play and applies a penalty. All other cards from
the attempt stay in the leader's hand and may be played later.
*Source:* on-record decision #60. *Engine:* `engine/engine.py:611-640`.

**R72 (forced play)** — The forced lead is the **smallest beatable component**: fewest cards
first, and on a tie the **weakest** (lowest maximum card strength). The trick then proceeds
normally with that play as the lead; `led_format` and `led_suit` are derived from it.
*Source:* #60. *Engine:* `engine/engine.py:617-643`.

**R73 (penalty size)** — The penalty is `10 × (number of cards in the ATTEMPTED throw)`, not
the number of withdrawn cards and not the number of beatable components. Multiple failed
throws by the same player in a round accumulate.
*Source:* #60. *Engine:* `engine/engine.py:615, 625-627`.

**R74 (attribution)** — Penalties are attributed at **round end** using **final** team
membership (so a Find Friends reveal after the throw is respected):
  - thrower ends on the defending team → `attacking_points += penalty`
  - thrower ends on the attacking team → `attacking_points -= penalty`

The sum of all adjustments is applied at once and the result is clamped at 0 (R66).
*Source:* #60. *Engine:* `engine/engine.py:787-793`.

**R75** — Penalties reset to empty at the start of each round's deal.
*Engine:* `engine/engine.py:180`.

---

## Level advancement & game over

**R76 (band table)** — From the final `attacking_points`, with threshold 80 and 20-point bands:

| attacking_points | winner | levels gained |
|---|---|---|
| 0-19 | defending | +4 |
| 20-39 | defending | +3 |
| 40-59 | defending | +2 |
| 60-79 | defending | +1 |
| 80-99 | attacking | +0 (take over, no level change) |
| 100-119 | attacking | +1 |
| 120-139 | attacking | +2 |
| 140 and above | attacking | +3 (hard cap) |

Formally: if `points < 80`, defending wins with `steps = ceil((80 - points) / 20)`; else
attacking wins with `steps = min(3, (points - 80) // 20)`.
*Source:* on-record Session 23 bands + cap #51 (which override robertying's "0 points →
defending +3"). *Engine:* `engine/scoring.py:115-152`.

**R77** — Only the winning team advances, and every member of the winning team advances by the
same number of levels. In Find Friends, a revealed friend advances with the leader; an
unrevealed-friend round means the lone leader advances alone (R31).
*Engine:* `engine/engine.py:802-805`.

**R78** — Advancement is clamped at Ace: a +3 from King lands on Ace, not past it (D14).
*Engine:* `models/player.py:29-41`.

**R79 (role swap)** — In Upgrade, if the attacking team wins (including the +0 take-over band)
the two pairs swap roles for the next round; if the defending team wins, roles are unchanged.
In Find Friends, roles are meaningless between rounds — teams are rebuilt from scratch each
round by R22. *Engine:* `modes/upgrade.py:65-76`, `modes/find_friends.py:132-133`.

**R80 (next round leader)** — The next round leader is the first player, scanning
counter-clockwise from the **current** round leader, who belongs to the **winning** team.
  - Upgrade: defending team won → the leader's partner (leader + 2); attacking team won → the
    player to the leader's counter-clockwise side (leader + 1).
  - Find Friends: the same scan, over the final winning team.

*Source:* pagat (declarers won → starter's partner; opponents won → next player).
*Engine:* `modes/upgrade.py:78-99`, `modes/find_friends.py:135-156`.

**R81** — The next round's trump rank follows automatically from R12: it is the new round
leader's level.

**R82 (game over)** — The game ends **only** when the defending team wins a round while
**already** at Ace going into that round. The check uses **pre-advancement** levels, so a team
that advances *into* Ace does not win — they earn the right to defend at Ace next round.
*Source:* on-record decision #52; robertying ("reach rank A and successfully defend once").
*Engine:* `engine/engine.py:819-828`.

**R83** — The attacking band `80-99` (`winner = "attacking"`, `steps = 0`) means the defenders
**lost**; it can never end the game. *Engine:* `engine/engine.py:823-828`.

**R84** — The game-over check fires if **any** player on the winning defending team was at Ace
before advancement. In Upgrade this is unambiguous (partners always share a level). In Find
Friends this can fire on a revealed friend's level rather than the round leader's — see **Q4**.
*Engine:* `engine/engine.py:824-828`.

---

## Documented decisions

Engine positions that are defensible and not covered by an on-record ruling. Each is recorded
here as the project's choice; later fixes should cite the number.

- **D01** — The trump rank is the round leader's individual level. In Find Friends, where
  levels diverge across a shifting team, the leader's level alone governs. (R12)
- **D02** — Bidding runs concurrently with the deal and continues after it; shown bid cards
  stay in hand. (R13)
- **D03** — Bid strength ladder is single < suited pair < Small-Joker pair < Big-Joker pair,
  with no suit precedence at equal strength. (R15)
- **D04** — A player may override their own bid if strictly stronger (pagat forbids this;
  robertying is silent). (R16)
- **D05** — All-pass is resolved by a full re-deal with the same leader and trump rank; the
  pagat fallback of turning the bottom face-up to derive a trump is not implemented. (R19)
- **D06** — Burying is unrestricted: point cards, trump, and the shown bid cards may all be
  buried. (R25)
- **D07** — Throw legality is judged against all three other hands, including the thrower's
  own partner (Upgrade) and unrevealed friends (Find Friends). (R41)
- **D08** — A throw's tractor component is beaten by a *longer* opposing tractor as well as an
  equal-length one; equal length is not required. (R40)
- **D09** — Degraded follows (right card count, wrong shape) are ineligible to win the trick
  even when strictly stronger. (R52)
- **D10** — To win a throw lead, a play must match the throw's component structure
  component-for-component. (R52)
- **D11** — Find Friends bans trump-**suit** cards as friend cards, in addition to jokers and
  trump-rank cards. (R30)
- **D12** — Point attribution is retroactive on friend reveal: points captured before the
  reveal follow the player to the defending side. (R33)
- **D13** — The final attacking total is clamped at 0 after penalties. (R66)
- **D14** — Level advancement clamps at Ace rather than overflowing. (R78)
- **D15** — The bottom multiplier applies only when an attacker wins the final trick; a
  defending last-trick win means the bottom scores nothing for anybody. (R67)

Decisions D16-D21 were ruled by Jeffrey in the 2026-07-29 interview (see `## Resolved forks`
for full analysis). D16-D18, D20, D21 are **behavior changes** pending implementation
(Phase 5, after the fuzz harness lands); D19 confirms current behavior.

- **D16** — A throw lead whose components do not all share one effective suit is **rejected**
  as an illegal lead (clear error; NOT a throw-penalty case — R71 applies only to beatable
  single-suit throws). Removes the `cards[0]` order dependence for `led_suit`. (Q1; changes R38/R39)
- **D17** — A play is "trump" for eligibility only if **every** card in it is trump; a play
  whose cards span more than one effective suit is **never eligible to win** a trick.
  Eligibility becomes order-independent. (Q2; changes R51)
- **D18** — Tractor adjacency is "no occupied strength position lies strictly between the two
  cards" rather than "tier + 1": in no-trump, a trump-rank pair and a Small-Joker pair form a
  tractor, consistent with suited mode. (Q3; changes R8)
- **D19** — Game over fires if **any** member of the winning defending team was at Ace before
  advancement — including a Find Friends friend revealed mid-round. Current engine behavior
  confirmed as intended. (Q4; confirms R84)
- **D20** — Friend-declaration ordinals outside 1..2 (generally 1..number of decks) are
  rejected with `ValueError`. Audit scope note: today NO validation exists at all — 0,
  negative, and arbitrary ordinals are accepted — so the rejection set is every integer
  outside 1..2. (Q5; changes R29)
- **D21** — `revealed_friends` and `friend_declarations` are cleared in `start_dealing`; "no
  player view exposes another round's or player's hidden information" becomes a fuzz-harness
  invariant. (Q6; changes R32 bookkeeping)
- **D07 (confirmed)** — Q7 ruled to keep judging throws against all three other hands,
  partner included; D07 is now an on-record decision, not an engine accident.

Decisions D22-D26 were ruled in the Phase 4 interview (2026-07-29), consolidating the audit /
matrix / fuzz findings (see `docs/reports/2026-07-29-consolidated-findings.md`):

- **D22** — Tractor adjacency additionally requires the two cards to share an **effective
  suit**, and a play's `led_suit` is derived from the whole play, not `cards[0]`. Closes audit
  finding F1 (cross-suit plays classifying as Tractors and bypassing throw validation — e.g.
  `3♠3♠+4♦4♦`). Classifier-level face of D16; recorded without a separate interview because
  authority sources 1-3 all require single-suit plays. **Must land before D18.** (changes R8/R37)
- **D23** — A throw's tractor component imposes a **structural** obligation like R46: any
  qualifying tractor of the required length satisfies it. Fixes the scan-order artifact that
  forced the *weakest* of two equal-length tractors (audit F5 / matrix NEW-1). (changes R47)
- **D24** — In Find Friends, a lone leader who successfully defends is re-selected as the next
  round leader (R80's scan wraps back to them). Confirmed intended. (confirms R80)
- **D25** — Deliberately failing a throw to withhold a declared friend card (forced component
  substitutes; the friend card returns to hand unrevealed) is a **legal gambit**; the 10
  pts/card penalty is its cost. Confirmed intended. (confirms R71/R72 × R32 interaction)
- **D26** — The network layer must support **explicit single bids**: a player holding two
  trump-rank cards of a suit may bid either the single or the pair. The current silent
  single→pair upgrade (audit F4) is a bug to fix in `network/handler.py` (protocol gains an
  optional count; default preserves current auto-strongest behavior for older clients).
  (network-layer rule; R14/R15 reachable space)

---

## Known limitations

1. **Circular-wrap tractors are fragile (broader than first documented).** With trump rank 2,
   K♥K♥ A♥A♥ 3♥3♥ splits into a 4-card tractor (K-A) plus a pair (3-3). Audit finding F3
   showed the failure is wider: the 0↔11 wrap is detected **only** when the two wrapped
   positions are the sole pair-positions in tier 0 — any unrelated tier-0 pair in the same
   play sits between them in sort order and destroys the wrap entirely
   (A♠A♠ 3♠3♠ → tractor; A♠A♠ 3♠3♠ 8♠8♠ → three loose pairs). This changes the R40
   beatability test, R47 obligations, and the R68 multiplier for such plays. Cause:
   `find_tractors` scans positions in sorted order and can only observe the wrap at the ends
   of the scan. Documented and pinned by test. *Engine:* `models/groups.py:108-114, 131-152`.
   Verified empirically 2026-07-28/29.
2. **Bidding close lives in the network layer.** The engine exposes `close_bidding()` but the
   "all four passed" trigger, the auto-pass of the current bidder, and the "a player who
   passed may not bid again" rule are all implemented in `network/handler.py:302-303,
   336-350`. An engine-only test oracle cannot exercise R17; it must either drive the handler
   or treat R17 as out of engine scope.
3. **Throw components are decomposed greedily.** `classify_play` builds a throw's components
   from maximal tractors first, then identity groups, then singles. A play with more than one
   valid decomposition is judged against the greedy one only.
4. **`exchange_bottom`'s docstring is stale** (it claims a transition to `FRIEND_DECLARATION`
   in Find Friends). The code always transitions to `PLAYING`; friend declaration happens
   before the exchange (R23). Behavior is correct; the comment is not.

---

## Resolved forks (interviewed 2026-07-29)

All seven forks below were put to Jeffrey and ruled. Rulings: Q1 → D16 (reject), Q2 → D17
(suit-pure wins), Q3 → D18 (close the gap), Q4 → D19 (keep any-defender check), Q5 → D20
(reject bad ordinals), Q6 → D21 (clear stale state), Q7 → D07 confirmed (keep all-hands
judging). The original analyses are retained below for auditors.

### Q1 — May a throw lead mix suits? → **D16: no, reject**

**The fork.** A throw is supposed to be a claim about one suit. Nothing in the engine requires
a throw's components to share an effective suit.

**What the engine currently does.** It accepts a mixed-suit throw. `classify_play` splits the
play into components by strength position with no suit check, and `find_beatable_components`
validates each component *against its own suit* independently. Verified empirically: with
trump ♠ / rank 2, leading A♥ + A♣ classifies as `Throw(Single, Single)` and passes validation
when no opponent holds a higher heart or a higher club. The trick's `led_suit` is then taken
from `cards[0]` only (`engine/engine.py:643`), so followers are held to the first card's suit
and the other component's suit is unconstrained — and the same two cards submitted in the
opposite order produce a different led suit.

**What the sources say.** robertying: "All winning plays must be one suit (original or
trump)". pagat: a throw is "mixed singles/pairs **from one suit** (or trumps)". Both sources
require single-suit throws; the engine has no such rule.

**Recommended default.** Reject a lead whose components do not all share one effective suit,
with a clear error (this is a lead-legality rule, not a throw-penalty case — R71's penalty is
for *beatable* throws, not malformed ones). This also removes the `cards[0]` ordering
dependence for `led_suit`.

### Q2 — Can a mixed trump + junk follow win a throw lead? → **D17: no, suit-pure only**

**The fork.** When a follower is void in the led suit (R43) they may play any cards. Whether
such a play can *win* depends on two order-sensitive checks.

**What the engine currently does.** `_play_strength` (`engine/tricks.py:783-785`) determines
the play's suit from `cards[0]` only, and `_format_can_beat_lead` checks structure, not suit
purity. Verified empirically: hearts throw A♥+K♥ led; a void follower playing [3♠(trump), 4♦]
**wins the trick**, but the identical two cards submitted as [4♦, 3♠] are ineligible and the
leader wins. Same cards, different array order, different winner. Related: when the lead is
trump, the suit test `play_suit != led_suit and play_suit != "trump" and led_suit != "trump"`
short-circuits, so off-suit plays are marked *eligible* on trump leads (harmless today, since
the trump lead always outranks them, but it is not a rule anyone wrote down).

**What the sources say.** pagat, for throws: the lead is won by a non-leader only if that
player plays **only trumps**. Neither source contemplates a mixed play winning anything.

**Recommended default.** Compute a play's effective suit as "trump" only if **every** card in
it is trump, and otherwise as the common suit if there is one; a play whose cards span more
than one effective suit is never eligible to win. That makes eligibility order-independent and
matches pagat. (Deliberately a separate fix from Q1 — this one is about following, not
leading.)

### Q3 — In no-trump, should the trump-rank pair and the joker pair form a tractor? → **D18: yes**

**The fork.** The trump hierarchy is continuous — trump-rank cards, then Small Joker, then Big
Joker — so consecutive pairs in it should form a tractor. In no-trump mode the tier-3 rung
(trump-rank card of the trump suit) does not exist, and the adjacency ladder has a gap.

**What the engine currently does.** `are_tractor_adjacent` requires `tier2 == tier1 + 1`, so
tier 2 (trump-rank) is adjacent to tier 3 only. In no-trump, tier 3 is empty, so tier 2 and
tier 4 (Small Joker) are not adjacent. Verified empirically at trump rank 2, no-trump:
2♥2♥ + SJ SJ classifies as a **Throw** of two pairs; the same shape with a trump suit
(2♠2♠ + SJ SJ, spades trump) classifies as a **Tractor**. SJ SJ + BJ BJ is a tractor in both
modes.

**What the sources say.** Neither source addresses tractors across the joker boundary in
no-trump specifically. pagat says jokers "rank above trump rank + suit card" and that a
tractor is consecutive pairs in the ordering, which implies the pair should be adjacent when
nothing sits between them.

**Recommended default.** Treat adjacency as "no occupied strength position lies strictly
between them" rather than "tier + 1", so no-trump 2♥2♥ + SJ SJ becomes a tractor. This is a
behavior change with real play impact, so it needs your call rather than a silent fix.

### Q4 — In Find Friends, should a revealed friend's level trigger game over? → **D19: yes, keep current behavior**

**The fork.** Decision #52 says the game ends when a team defends successfully while already
at Ace. In Find Friends, levels are individual and the defending "team" is assembled mid-round,
so it can contain a player at Ace who is not the one whose level is being defended (the trump
rank comes from the leader, D01).

**What the engine currently does.** `end_round` (`engine/engine.py:824-828`) scans **every**
final defender's pre-advance level and declares game over if any of them was at Ace. So a
leader at level 5 who successfully defends with a friend who happens to be at Ace ends the
game — and the friend never defended their own level.

**What the sources say.** robertying: "Winner: reach rank A and successfully defend once."
pagat: "game ends above Ace". Neither contemplates fluid teams with divergent levels.

**Recommended default.** In Find Friends, gate game over on the **round leader's**
pre-advance level only (the level actually being defended); keep the current any-defender
check in Upgrade, where partners always share a level and the two rules coincide.

### Q5 — Should a friend declaration's ordinal be validated? → **D20: yes, reject outside 1..2**

**The fork.** With 2 decks there are exactly 2 copies of any non-joker card, so the only
meaningful ordinals are 1 and 2.

**What the engine currently does.** `validate_friend_declaration`
(`modes/find_friends.py:51-90`) checks the count of declarations and the card's suit/rank, but
never checks the ordinal. A declaration of "the 5th A♠" is accepted, can never resolve, and
silently produces a 1-versus-3 round. The frontend only offers 1st/2nd, so today this is
reachable only through a hand-built client or the superuser tools — but the engine is the
authority, not the UI.

**What the sources say.** Both sources describe calling the "first"/"second" copy; neither
contemplates an out-of-range ordinal.

**Recommended default.** Reject ordinals outside 1..2 (generally: 1..number of decks) with a
`ValueError`. R31's intended 1v3 outcomes (self-friend, friend-in-bottom) are unaffected —
they arise from legal declarations.

### Q6 — Should `revealed_friends` be cleared between rounds? → **D21: yes, clear + redaction invariant**

**The fork.** Friend identity is supposed to be hidden until the card is played (R32).

**What the engine currently does.** `start_dealing` (`engine/engine.py:173-183`) clears bids,
trump, tricks, points, and penalties, but **not** `state.revealed_friends` (a set that only
ever grows) and not `state.friend_declarations` (replaced only when the new leader declares).
Both are serialized into every player's view (`models/game_state.py:162, 164`). So during the
deal and bidding of round N+1, every player can still see round N's revealed friend and round
N's declared card. Team logic is unaffected (`assign_teams` resets `is_defending` each round),
so this is stale display state rather than a scoring bug — but it is the kind of leak the
per-player redaction property in the playbook is meant to rule out.

**What the sources say.** Not addressed; this is an implementation artifact rather than a
rules fork.

**Recommended default.** Clear `revealed_friends` and `friend_declarations` in
`start_dealing`, and treat "no player view exposes another player's hidden information" as an
invariant the fuzz harness asserts. Flagging it here rather than fixing it silently because it
touches what the round-over screen can display.

### Q7 — Should the thrower's own partner count when judging a throw? → **D07 confirmed: yes, all other hands**

**The fork.** R40 asks "can any single other player beat this component". Whether "other
player" includes your partner changes how often throws succeed.

**What the engine currently does.** It includes all three other players, partner included
(`engine/engine.py:612`, D07). In Upgrade this means a throw fails when your partner holds the
higher card, even though your partner would never play it to beat you.

**What the sources say.** robertying: a throw is "highest possible plays in suit claimed" —
silent on whose cards count. pagat frames it as a challenge: "any player holding a beating
card must immediately expose it", which in practice means opponents, since a partner has no
reason to challenge.

**Recommended default.** Keep the current behavior (all other players). It is the stricter,
simpler rule, it is symmetric between the two modes, and it avoids the Find Friends problem of
"partner" being undefined before the friend is revealed. Confirming this makes D07 an
on-record decision rather than an engine accident.

---

## Suspected bugs (no fixes applied)

Confirmed by direct probes against the engine while writing this spec. Listed here so the
Phase 2 audit can start from verified behavior rather than re-deriving it.

1. **Mixed-suit throw leads are accepted** (Q1) — and `led_suit` then depends on the order of
   the submitted card array. `engine/engine.py:603-643`, `models/groups.py:167-214`.
2. **Trick-winner eligibility is order-dependent** (Q2) — `_play_strength` reads the play's
   suit from `cards[0]`, so [trump, junk] wins a throw lead that [junk, trump] loses.
   `engine/tricks.py:783-785`.
3. **No-trump tractor gap** (Q3) — a trump-rank pair and a Small-Joker pair are adjacent with a
   trump suit but not in no-trump, because the ladder steps one tier at a time over an empty
   tier 3. `models/trump.py:109-117`.
4. **Friend-declaration ordinals are unvalidated** (Q5) — an out-of-range ordinal is accepted
   and silently yields an unresolvable friend. `modes/find_friends.py:51-90`.
5. **`revealed_friends` and `friend_declarations` survive into the next round** (Q6) —
   `start_dealing` clears everything else. `engine/engine.py:173-183`.
6. **Find Friends game over can fire on a friend's level** (Q4) — the check scans every final
   defender, not the leader whose level is being defended. `engine/engine.py:824-828`.
7. **Minor / low risk:** `_assign_throw_components` assigns a Tractor component no cards if it
   cannot re-find a tractor of exactly the right length in the remaining cards, and
   `find_beatable_components` then skips that component's beat check entirely
   (`engine/tricks.py:568-578, 538-540`). No reachable case was constructed — the same
   `find_tractors` call produced the components in the first place — but it is a silent-pass
   path rather than an error.
