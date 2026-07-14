# Shengji — Progress Log

Newest entries at the top.

---

## Session 26 — Cleanup sweep: seeded fuzzer, 5 engine bugs, M9 backfill, hardening

**Date:** 2026-07-14

Full-project cleanup driven by an interview with Jeffrey (rules decisions recorded below) plus a dedicated edge-case-hunting agent. 553 → 620 tests. Everything merged to `main`; the throw-penalty feature (next entry) shipped in the same session.

### Shipped (issue → PR)

- **#46 → PR 47 — Seedable RNG + terminal harness.** `Deck`/`GameEngine` accept `random.Random`; `scripts/play_cli.py` plays interactively in the terminal (all seats or `--human N`, `--seed` repeats hands) or fuzzes N full bot games with a `validate_state` sweep after every action. Fuzzing immediately paid off (below).
- **#48 → PR 49 — Tractor-follow validation.** Followers answering a tractor lead with pairs were forced to play the specific HIGHEST pairs; any pairs of the right count are legal. Found by the fuzzer (~6% of games crashed the room on a legal play). Validation is now structural.
- **#50 → PR 56 — Identity pairs.** Off-suit trump-rank cards of different suits formed phantom pairs/quads (could lead a fake "pair", win a real pair lead with a mismatched-trump ruff). Pairs/groups now require truly identical cards everywhere; strength ties unchanged. Decision: Jeffrey confirmed identical-cards-only.
- **#51 → PR 53 — Attacking advancement capped at +3** (formula was unbounded; 300-pt blowouts jumped ranks 2→K).
- **#52 → PR 55 — Game over one round early.** Defenders advancing INTO Ace no longer win instantly; they must defend AT Ace (pre-advance ranks gate the check).
- **#57 → PR 58 — Bottom multiplier.** Was stuck at 2× (classified the whole 16-card last trick). Now 2× the winning play's largest component, capped 8× (single 2×, pair 4×, tractor 8×). Also replaced scoring.py's contradictory 175-line docstring with the authoritative table.
- **PR 59 — M9 backfill:** 40 integration tests in `tests/test_integration/` (ported from the edge-hunt agent's 91-test suite, deduped against unit tests).
- **PR 62 — Hardening:** non-ValueError bugs in `handle_message` no longer nuke the room (contained + logged, error to acting player only); `validate_state` invariant sweep wired after every action (M9.3); `led_format`/`led_suit` promoted to declared GameState fields.
- **#44 closed:** trump-rank tractor adjacency verified already correct in all sub-cases (2-4 skip over rank 3, off↔on-suit rank tractor, joker tractor); the one real defect found nearby was #50.

### Interview decisions (authoritative)

- Pair = identical cards only. R2+ leader is rotation-determined (bid only fixes trump) — intended. Self-friend / friend-in-bottom → leader 1v3 — intended. Score bands final (0–19 def+4 … 140+ att+3). Failed throw = confirm dialog → forced smallest component + 10 pts × thrown cards, attributed by FINAL teams.

### E2E smoke pass (Playwright, 4 tabs)

All stages verified on the final build: landing/join errors, host-only mode select, dealing + trump highlight + bid banner/pass gating, 33-card exchange, legal trick play with point tracking, throw confirm dialog (cancel preserves selection; confirm → forced component + orange banner on all tabs), round-over overlay, FF declaration UI incl. 1st/2nd ordinal, friend status bar + reveal popup. Console clean. Found + fixed (#43 → PR 63): superuser-enable button missing `X-Player-Id` header (422 always), and the #43 defect confirmed as display timing — the friend's held points vanished silently at the next trick boundary; the engine now re-attributes the live total at the reveal moment. UX note for later: the throw-failed banner fades in 4s and is easy to miss.

### Known remaining

- 3+-position circular-wrap tractors (K-A-3 at rank 2) split into two runs (documented limitation, pinned by test).
- #29 Playwright full automated suite still open (this session's smoke pass was agent-driven, not committed tests).

---

## Session 26 — Failed-throw penalty: forced smallest component + 10 pts/card (#60)

**Date:** 2026-07-14

**Branch:** `feat/throw-penalty`. 580 tests passing. 100-game bot fuzz clean in both modes.

### What was changed

- **Engine (`tricks.py`):** `validate_throw` refactored into `find_beatable_components()` (returns the `(component, cards)` pairs a single opponent can beat); the bool API is kept as a thin wrapper.
- **Engine (`engine.py`):** `play_cards` no longer raises on a failed throw. The leader is forced to lead the SMALLEST beatable component (fewest cards; tie-break weakest by max card_order); the rest of the attempted cards stay in hand. Penalty = 10 × attempted cards, accumulated in new `GameState.throw_penalties` (reset in `start_dealing`). Result dict gains `throw_failed` / `attempted_cards` / `forced_cards` / `penalty`.
- **Scoring (`end_round`):** after `count_attacking_points`, penalties are attributed by FINAL teams — defender thrower → attackers gain +P; attacker thrower → −P, total clamped ≥ 0. Reported as `throw_penalty_adjustment`. Find Friends team flips (friend reveal after the throw) are therefore respected.
- **Network (`handler.py`):** new `check_play` WS action → per-player `{"type": "check_play_result", "is_throw": bool}` (true iff Throw AND leading). Failed throws broadcast `{"type": "throw_failed", ...}` to all players and log a `throw_penalty` event. `validate_play` no longer rejects beatable throws (they are playable with consequence). Logs/trick snapshots use the actually-played (forced) cards.
- **Logger (`logger.py`):** added `log_throw_penalty` (attempted/forced cards, penalty, trick number).
- **Frontend (`app.js`, `index.html`):** leading with >1 selected card first sends `check_play`; if it's a throw, an inline confirm bar warns about the forced-component + 10 pts/card consequence before playing. `throw_failed` broadcasts render as a centered banner (re-deal banner pattern). Pending play cards are captured at click time (also fixes a re-render race in the old validate flow).
- **CLI harness (`play_cli.py`):** leader ValueError fallback is now dead code for throws (comment updated, kept as safety net); verbose mode narrates forced throws and per-round penalty adjustments.
- **Tests:** `tests/test_engine/test_throw_penalty.py` (forced substitution, smallest-component tie-break, card conservation, penalty reset, end_round attribution both directions, FF retroactive team flip, valid throws unchanged) and `tests/test_network/test_check_play.py` (check_play classification + throw_failed broadcast).

---

## Session 25 — Re-deal notification on all-pass (#42)

**Date:** 2026-03-21

**Branch:** `fix/redeal-all-pass`. 553 tests passing.

### What was changed

- **Backend (`handler.py`):** after `close_bidding()` detects all-pass, server broadcasts `{"type": "redeal", "reason": "All players passed — re-dealing."}` to all players before triggering the re-deal task.
- **Frontend (`app.js`):** added `handleRedeal()` — creates a centered `.redeal-banner` div that auto-removes after 3s.
- **Frontend (`index.html`):** added `.redeal-banner` CSS (fixed center, gold border, 3s fade-out animation).

---

## Session 24 — Display fixes, trick delay, bidding pass, no-trump suit (#39, #40)

**Date:** 2026-03-21

**Branch:** `fix/display-fixes-trick-delay-bidding-notrump`. **PR:** #41. 553 tests passing.

### What was changed

- **Bottom cards at round-over (#40):** always revealed to all players, not just when defenders win. Label changed to "Bottom cards:".
- **Trick hold delay (#40):** every completed trick now holds for 3s (single/pair) or 5s (>2 cards) before clearing, so all players see the 4th player's cards. Backend restores `current_trick` from snapshot, broadcasts, sleeps, then clears.
- **Outbid player pass (#39):** frontend Pass button was disabled for any player in the bid history. Fixed to only disable for the current highest bidder. Outbid players can now pass.
- **No-trump effective_suit fix:** `effective_suit()` in `TrumpContext` returned natural suit for trump-rank cards in no-trump mode, but `card_order()` gave them trump-tier ordering. This caused:
  - Followers couldn't play single 2s when following a trump lead (2s not recognized as trump-suited)
  - AKK throws rejected because opponent 2s were counted as suited cards at trump ordering, appearing to beat any non-trump pair
  - Fixed: trump-rank cards always return `"trump"` from `effective_suit()` regardless of mode.
- **Throw trick-winning format matching:** `_format_can_beat_lead()` returned True unconditionally for Throw leads, so 3 random trump singles could beat a throw with a pair component. Fixed: follower's play must match the throw's component structure (pair for pair, single for single) to be eligible to win. Follower is still free to play any cards when out of led suit.

---

## Session 23 — Fix throw follow validation (#25) + scoring step change

**Date:** 2026-03-21

**Branch:** `fix/throw-follow-scoring-step`. 553 tests passing.

### What was changed

- **Throw follow validation (#25):** `is_valid_follow()` in `tricks.py` previously fell back to `get_legal_plays()` for throw follows, which returned only ONE valid combination. Players could only play that exact set of cards — other equally-valid selections were rejected.
- Added `_is_valid_throw_follow()` that validates **structural obligations** instead of exact card identity:
  - IdenticalGroup components: if hand has a pair, proposed must contain SOME pair (any pair, not a specific one)
  - Tractor components: card-specific required (reuses tractor follow logic)
  - Single components: no obligation — any suited card fills the slot
- 10 new tests covering: no-pair follows (any suited cards valid), pair-required follows, multiple-pair choice, partial follows with off-suit fill, and two-pair-component throws.
- **Scoring step change:** Rank skip step reduced from 40 to 20 points (threshold stays at 80). Clean 20-point bands everywhere, no caps, no special cases. Defending: 0-19 → +4, 20-39 → +3, 40-59 → +2, 60-79 → +1. Attacking: 80-99 → +0, 100-119 → +1, 120-139 → +2, 140+ → +3. Updated all scoring tests.

---

## Session 22 — Unique player names + leader display/logic (#31, #32)

**Date:** 2026-03-21

**Branch:** `fix/issues-31-32` → merged to main. 539 tests passing.

### What was changed

- **Unique names (#31):** `room.py` `join_room()` now rejects duplicate names within a room with a `ValueError` → HTTP 400. Frontend already surfaced `detail` errors via `setLandingError`.
- **Leader logic (#32):** `engine.py` `close_bidding()` only sets `round_leader_id` from the bid winner in round 1; subsequent rounds keep the predetermined leader. `current_leader_id` always mirrors `round_leader_id` after close.
- **Leader UI (#32):** `updateTrumpInfo()` in `app.js` appends ` · Leader: {name}` to the trump info bar after bidding completes in round 1 and immediately in all subsequent rounds.

### Design decisions

- `round_number` starts at 1 (not 0), so the guard is `round_number == 1`.
- Leader display is suppressed during WAITING/DEALING/BIDDING_AFTER_DEAL in round 1 (leader not yet known). Shown in all other phases including BOTTOM_EXCHANGE onwards.

---

## Session 21 — Joker Chinese labels + end screen rank progression (#35, #33)

**Date:** 2026-03-21

**Branch:** `feature/issues-33-35-joker-labels-rank-progression` → merged to main. 534 tests passing.

### What was changed

- **Joker display (#35):** `rankDisplay` in `app.js` now maps `"BJ"` → `"大"` and `"SJ"` → `"小"`. Affects hand, trick area, and bid buttons ("No Trump (大)" / "No Trump (小)"). Backend identifiers unchanged.
- **Rank progression (#33):** Backend (`engine.py`) captures each player's rank before advancing and adds `old_rank` to the `round_players` payload. End screen renders `old → new` (e.g. `4 → 5`) when rank changed; shows just the current rank when unchanged.

### Design decisions

- `old_rank` is captured before `advance_rank` is called, so it always reflects the rank at round start.
- Frontend only shows the arrow when `old_rank !== rank`; no `4 → 4` noise for non-advancing players.

---

## Session 20 — Find Friends phase ordering, UI, and friend reveal (#23)

**Date:** 2026-03-21

**Branch:** `feature/find-friends-phase-23` → merged to main. 534 tests passing.

### What was changed

- **Phase ordering fix:** `FRIEND_DECLARATION` now occurs *before* `BOTTOM_EXCHANGE` (correct rule: declare friend card before seeing the 8 global cards). New flow: `BIDDING_AFTER_DEAL → FRIEND_DECLARATION → BOTTOM_EXCHANGE → PLAYING` (Find Friends); Upgrade mode unchanged.
- **Trump-suit validation:** Backend rejects friend declarations for any card of the trump suit (jokers and trump-rank cards were already blocked). Frontend suit dropdown also hides the trump suit.
- **Declaration UI:** Controls reordered to `[1st/2nd ▾] [rank ▾] of [suit ▾] [Confirm]`; suit defaults to blank and is validated on confirm.
- **Friend status bar:** Permanent green bar visible to all players — shows `"{leader} is looking for {rank}{suit}"` after declaration, replaced by `"{friend} is the friend!"` once the card is played.
- **Friend reveal popup:** Temporary 4-second flash `"{name} is the friend!"` injected near the player's position in the trick area when the friend card is played.
- **Player view:** Added `revealed_friends`, `round_leader_id`, and `friend_declarations` to `to_player_view()`.
- **Tests:** Updated `test_game_state.py`, `test_bottom_exchange.py`, `test_bidding.py` for new phase ordering; added 3 new trump-suit validation tests (534 total).

### Design decisions

- Friend declaration comes before bottom exchange so the leader cannot use knowledge of the 8 buried cards to game their friend choice.
- Trump-suit filtering is frontend-only (UX); backend is the authoritative validator.
- Status bar uses green for both pre- and post-reveal states for accessibility.

---

## Session 19 — Mobile responsive layout (explore/mobile-responsive)

**Date:** 2026-03-21

**Branch:** `explore/mobile-responsive` → PR pending. 531 tests passing.

### What was changed

- Added `@media (max-width: 600px)` block to `frontend/index.html`:
  - Hand area switches from `flex-wrap: wrap` to `nowrap` + `overflow-x: auto` (horizontal scroll)
  - Trump-rank separator hidden on mobile (gold border/glow is sufficient)
  - Cards bumped from 38×56px → 54×76px with larger rank (17px) and suit (30px) text
  - Rank sticky note goes full-width instead of fixed `min-width: 150px` from right edge
- Added `scripts/dev_mobile.sh`: starts uvicorn + ngrok, fetches public URL via ngrok API, generates QR code PNG and opens in Preview
- Added shell aliases to `~/.bash_profile`: `eighty`, `eps`, `epm`, `c`
- Closed Playwright issues #12–17, consolidated into single issue #29 with checkbox checklist

### Design decisions

- Landscape mobile not targeted (phone width >600px in landscape falls through to desktop layout — acceptable)
- Trump separator removed on mobile only; desktop layout unchanged
- No JS changes — purely CSS media query

---

## Session 18 — Feature #21: per-game JSONL event logger

**Date:** 2026-03-20

**Branch:** `feature/game-logging-21` → PR #28. 531 tests passing.

### What was added

`GameLogger` class (`src/shengji/engine/logger.py`) writes one crash-safe JSONL file per game to `logs/games/{unix_timestamp}.jsonl`. The file is flushed after every write so a mid-game server kill leaves a readable log up to the last event. All writes are best-effort — a filesystem error never crashes the game.

### Events logged

| Event | When |
|-------|------|
| `round_start` | After dealing — full hands snapshot for all 4 players, bottom deck, teams |
| `bid` / `pass_bid` | Each bid or pass during bidding phase |
| `bidding_closed` | When bidding closes; includes trump context, team assignments, or redeal flag |
| `bottom_exchange` | 8 cards buried by round leader |
| `friend_declarations` | Find Friends only: declared card + ordinal |
| `play_cards` | Each card play: trick_number, trick_position (0=lead, 1–3=follow) |
| `friend_revealed` | Find Friends only: auto-detected via `revealed_friends` set diff — no-op in upgrade mode |
| `trick_complete` | All 4 plays in order, trick points, running attacking_points |
| `round_end` | attacking_points, winner, steps, post-advancement player ranks |
| `game_over` | Final winner and standings |
| `error` | Engine validation failures (player_id, action, message) |

### Hook points

`handler.py` was modified at 9 points. `Room` gained a `logger` field. Logger is created on first `start_and_deal` call and shared across all rounds of the same game. Closed on game over or room abort.

### Key implementation note

`engine.play_cards()` clears `state.current_trick` after resolving. The trick snapshot is taken *before* the call; the 4th player's cards are appended after to reconstruct the full trick for `trick_complete` logging.

---

## Session 17 — Fix #24: prevent passed players from re-bidding

**Date:** 2026-03-20

**Branch:** `fix/bidding-repassing-24` → merged as PR #27. 531 tests passing.

### Bug fixed

A player who passed during bidding could still send a `bid` action. When they did, `passed_in_bidding` was cleared and re-seeded with just the bidder — other players who had already clicked Pass had their buttons re-disabled with no way to pass again, stalling the game loop indefinitely.

### Fix

Added `players_who_passed: set[str]` to `Room` (never cleared on a new bid, only on new deal). The `bid` action in `handler.py` rejects with an error if `player_id` is in this set. The `pass_bid` action populates both `passed_in_bidding` (closure counter) and `players_who_passed` (permanent block). Frontend disables suit and joker bid buttons when `S.hasPassed` is true.

### Tests added (1 new)

- `TestBidding::test_passed_player_cannot_bid_again`: pass as p0, immediately attempt bid, assert error "already passed" returned.

### Worktree workflow

Used `git worktree add ../eighty_points_issue24 -b fix/bidding-repassing-24` for isolation. Rebased onto `main` after PR #26 merged mid-session.

---

## Session 16 — Fix #20: is_valid_follow free-choice singles in degraded tractor follows

**Date:** 2026-03-20

**Branch:** `fix/tricks-tractor-20` → merged as PR #26. 530 tests passing.

### Bug fixed

`is_valid_follow` for Tractor leads fell back to `get_legal_plays`, accepting only the one specific card combination it returned. This incorrectly rejected valid plays:
- Player with N suited singles (N > needed) was forced to play the exact subset `get_legal_plays` picked.
- Player with a pair + extra singles was forced to pair the pair with specific singles instead of any suited singles.

### Fix

Added `_is_valid_tractor_follow` in `engine/tricks.py`. It separates **required cards** (tractors + pairs, greedily claimed from the suited hand) from **free-choice singles**. The proposed play must include all required cards; remaining slots accept any suited singles.

### Tests added (6 new)

- `TestIsValidFollowTractorAllSingles`: any N-choose-k combo of suited singles valid when no pairs/tractors in hand
- `TestIsValidFollowTractorWithPairs`: pair required, singles free; omitting pair rejected
- Exact tractor in hand: must play the tractor

---

## Session 15 — Issue triage, branch rebase

**Date:** 2026-03-20

- Raised issue #24: player who passed can re-bid, stalling game loop
- Raised issue #25: AKK/AAK throw follow validation leaves follower with no legal moves
- Rebased `fix/trump-bugs-19-20` onto `main` (PR #11 had landed); resolved false conflict in `frontend/app.js` and `frontend/index.html` — `cc98d00` (remove defending pts) became a no-op and was dropped. Force-pushed.

---

## Session 14 — Features: Ready Button, Rank Sticky-Note, FF Compatibility

**Status:** Complete. 516 tests passing.

**Branch:** `fix/endgame-points-leader-rotation`

### Feature 2 — Rank sticky-note display (client-side toggle)

A "Ranks" button in the game top-bar (right side) toggles a small floating
sticky-note panel showing every player's current rank and team role. This is
entirely client-side — only the player who clicked the button sees it.

**Frontend-only changes:**
- `index.html`: Added `#btn-rank-display` button to the game top bar; added
  `#rank-display` sticky panel with `#rank-display-content` (initially hidden).
  Added CSS for the panel, rank entries, team-role tags (Def/Atk), and active
  button state.
- `app.js`:
  - `S.showRankDisplay: false` added to app state.
  - `renderRankDisplay(gs)`: renders one row per player with name, rank, and
    team tag (Def/Atk) when teams are known. Self is highlighted gold.
  - Called from `renderGame(gs)` so the panel refreshes on every state update.
  - Toggle button click handler: flips `S.showRankDisplay`, sets `.active` CSS,
    and re-renders the panel immediately.
  - Reset to hidden when OK returns player to landing.

---

### Feature 1 — Ready-for-next-round button (replaces auto-proceed)

**Problem:** The round-over overlay auto-dismissed after 8 s, often before
players had a chance to read the team breakdown or buried cards.

**Solution:** All 4 players must press "Ready for Next Round" (styled like the
Pass button) before the next deal starts. The button shows "Ready ✓" after
pressing, and a live "X/4 ready" counter updates for everyone.

**Backend changes:**
- `room.py`: Added `ready_for_next_round: set[str]` field to `Room`.
- `handler.py`:
  - `start_and_deal` now clears `ready_for_next_round` at the start of each round.
  - `handle_round_end` no longer calls `start_and_deal` automatically for non-game-over rounds.
  - New `ready_for_next_round` action: adds the player to the set, broadcasts `{"type": "ready_update", "ready_count": N, "total": 4}` to all; when all 4 are ready, fires `start_and_deal`.

**Frontend changes:**
- `showRoundOverlay` no longer sets an auto-dismiss timer.
- `handleGameState`: overlay is dismissed unconditionally on `phase === "dealing"` (not only when the timer is active), so the manual-ready path also triggers correctly.
- `handleRoundOver`: appends a "Ready for Next Round" button + "X/4 ready" counter below the team breakdown.
- New `handleReadyUpdate`: updates the counter element live as players press ready.
- `dispatchMessage`: registered `ready_update` message type.

---

### Feature 3 — Verified compatibility with both Find Friends and Upgrade modes

All changes made in Session 14 (and Session 13) were audited for game-mode
compatibility. No mode-specific conditional branching is present or needed.

**Audit results:**
- **Live attacking_points** (`engine.py`): uses `p.is_defending` flag, which is
  set correctly by both `FindFriendsStrategy` (on friend reveal + first trick)
  and `UpgradeStrategy` (at game start). Handles mid-round friend reveals
  correctly because the set is recomputed from scratch on every trick.
- **`round_players` snapshot** (`end_round()`): captured after rank advancement
  but before team swap — correct in both modes. Both strategies advance
  `round_leader_id` using `get_next_leader()` which already uses `is_defending`.
- **Bottom-deck reveal** (`handler.py`): triggered by `winner == "defending"`,
  which is computed from the universal `compute_rank_advancement()` call —
  identical logic for both modes.
- **`start_and_deal`** (`handler.py`): constructs the strategy via `_make_strategy(mode)`
  and passes it to `GameEngine`. No branching after that — fully mode-agnostic.
- **`ready_for_next_round`** and **rank sticky-note**: entirely in the network
  layer and frontend respectively; no engine calls, fully universal.

No code changes required — the implementation was already correct for both modes.

---

## Session 13 — Bug Fixes: Scoring Thresholds, Live Points, Round-Over Screen

**Status:** Complete. 516 tests passing.

**Branch:** `fix/endgame-points-leader-rotation`

### Fix 1 — Scoring thresholds wrong: 80-pt threshold, not 400-pt (backend)

The `compute_rank_advancement` function used `base = 100 * n_decks = 200` for
the threshold boundaries. This meant attackers needed 400+ points to take over
as defenders — never achievable without a large bottom-deck multiplier.

The correct Shengji rule for a 2-deck game uses `step = 20 * n_decks = 40`,
giving thresholds at 0, 40, 80, 120, 160, 200 (attacking). The key threshold
for attackers to win (take over at same rank) is **80 points**.

- Changed `base = 100 * n_decks` → `step = 20 * n_decks` in `scoring.py`
- New thresholds for n=2: 0→def+3, 1-39→def+2, 40-79→def+1, 80-119→atk+0,
  120-159→atk+1, 160-199→atk+2, 200+→atk+3
- All 15 `TestComputeRankAdvancement` tests updated to match new thresholds
- Added `test_user_example_95pts_attacking_zero` — the user's concrete example

### Fix 2 — game_over detection triggered incorrectly for "attacking 0" (backend)

The old check `if winner != "attacking" or steps == 0` triggered game_over
when attackers take over at the same rank (attacking, steps=0). This is wrong:
when attackers take over, the defenders *lost* the round — game should not end.

- Changed to `if winner == "defending"` — game only ends when defenders actually
  win a round AND one of them is already at ACE rank.

### Fix 3 — attacking_points not tracked live during game (backend)

`state.attacking_points` was only set in `end_round()`, so the frontend showed
0 throughout all 25 tricks. Added live update after each trick resolution in
`play_cards()`: sums attacker trick points without the bottom-deck multiplier
(which is only applied at round end).

### Fix 4 — Round-over screen too sparse; needs team/bottom-deck info (backend + frontend)

**Backend (`handler.py`):** `round_over` message now includes:
- `players`: snapshot of all players with their team assignment and rank
- `bottom_deck`: the 8 buried cards, revealed only when defenders win

**Backend (`engine.py`):** `end_round()` now returns `round_players` in its
result dict (captured post-rank-advance, pre-team-swap).

**Frontend (`app.js`):** `handleRoundOver` now renders a rich HTML overlay:
- Attacking points + whether ≥ 80 threshold was crossed
- Outcome (rank advancement or take-over)
- Two-column team breakdown with player name and rank
- Bottom-deck card display (defenders-win only)

`handleGameOver` updated to show a more descriptive message.

### Fix 5 — Points display shows confusing "200 pts needed" (frontend)

Replaced the "Defending: X pts needed" metric with a threshold-relative display:
- Shows "need X more (of 80)" when below threshold
- Shows "+X over 80 ✓" (green) when attackers have exceeded the threshold

### Fix 6 — Overlay body changed from `<p>` to `<div>` for rich HTML content

Overlay box widened to 520px (was 400px). Round-over auto-dismiss extended
from 4 s to 8 s to give players time to read the team/rank breakdown.

---

## Session 12 — Bug Fixes: Joker Highlighting, Throw Validation, Deal Delay

**Status:** Complete. 515 tests passing.

**Branch:** `fix/bidding-close-and-bugs`

### Fix 6 — Jokers always highlighted regardless of trump context (frontend)

- `isTrumpCard()` checked `!trumpContext` before `isJoker()`, so jokers
  were not highlighted when `trump_context` was null (e.g., during the
  dealing phase before a bid is placed).  Moved the joker check first
  so jokers are always treated as trump regardless of context.

### Fix 7 — Throw validation: pair components require a pair to beat (engine)

Two bugs in the old `validate_throw`:

1. **Wrong card assignment:** `_extract_component_cards` extracted cards
   in ascending card_order order, so for an A♦+K♦K♦ throw it assigned
   K♦ as the "single" and K♦K♦ as the pair — then checked whether any
   opponent could beat a single K♦ with any higher card, incorrectly
   invalidating the throw when an opponent held one A♦.

2. **Wrong beat check:** For IdenticalGroup components, the check compared
   individual card strengths.  A single A♦ was treated as able to "beat"
   a K♦K♦ pair, which violates the rule: you need a PAIR to beat a pair.

**Fix:** Rewrote `validate_throw` with two new helpers:
- `_assign_throw_components`: correctly maps throw cards to components
  (tractors first, then IdenticalGroups by highest group, then singles)
  so A♦+K♦K♦ is correctly seen as pair=K♦K♦, single=A♦.
- `_single_opp_beats_component`: checks per-opponent (not pooled) and
  format-aware: a Single is beaten by any higher card; an IdenticalGroup(k)
  requires the opponent to have k cards at the same position with higher
  rank; a Tractor requires a matching-size tractor.

Result: A♦+K♦K♦ and A♦A♦+K♦ throws are now correctly valid when the
thrower holds enough aces to prevent opponents from forming a beating pair.
3 new regression tests added.

### Fix 8 — Deal delay reduced from 0.5 s to 0.25 s (backend)

- `DEAL_DELAY_SECONDS` in `app.py` changed from 0.5 to 0.25.  100 cards
  now take ~25 s to deal rather than ~50 s.

---

## Session 11 — Bug Fixes: Bidding Design, Mode Selector, Trump Highlighting, Trick Resolution

**Status:** Complete. 512 tests passing.

**Branch:** `fix/bidding-close-and-bugs`

### Fix 1 — Remove manual close-bidding; all players must pass (backend + frontend)

- Removed `close_bidding` action branch from `handler.py`. Bidding now
  closes exclusively when all 4 players pass (`pass_bid` auto-close).
- Removed "Close Bidding" button from `renderBidArea` in `app.js`.
- Removed two now-invalid tests (`test_game_master_can_close_bidding`,
  `test_non_gm_cannot_close_bidding`) from `test_websocket.py`.

### Fix 2 — Mode selector shown only after all 4 players join (frontend)

- `renderLobby` now hides the Upgrade / Find Friends buttons until
  `n === 4`, preventing the game master from starting a game with
  fewer than 4 players.

### Fix 3 — Trump card highlighting throughout all play phases (frontend)

- Added `isTrumpCard(card, trumpContext)` helper: returns true for
  jokers, trump-rank cards (any suit), and trump-suit cards.
- Non-bidding `renderHand` now applies `.trump-highlight` (gold border
  + warm tint) to every trump card in hand for all post-bidding phases,
  giving players a persistent visual reminder of which cards are trump.

### Fix 4 — Own name larger on trick table (frontend)

- `renderTrickArea` adds `is-self` CSS class to the local player's name
  label (14 px, bold, white vs. 11 px grey for others). Makes it easy
  to identify your own position when testing multiple windows.

### Fix 5 — Degraded follows cannot win the trick (backend engine + tests)

- **Bug:** A follower with no pair in the led suit was allowed to "win"
  a pair-lead trick by playing two high singles (e.g., A♠ + K♠ beating
  a Q♠Q♠ lead), violating the rule that a degraded response can never win.
- **Fix:** Added `_format_can_beat_lead(play_fmt, led_fmt)` to `tricks.py`.
  Updated `_play_strength` to classify the follower's play and return
  `None` (ineligible) if the play's format cannot beat the led format.
  Updated `resolve_trick_winner` to accept an optional `led_format`
  parameter (auto-derived from the leader's cards if omitted, keeping
  existing tests backward-compatible). Engine passes `state._led_format`
  explicitly to `resolve_trick_winner`.
- **Coverage:** A trump pair (or tractor) following a non-trump pair lead
  is still eligible to win — the format check correctly allows it.
- 5 new regression tests added to `test_tricks.py`.

---

## Session 10 — Bug Fix: Bidding UX, Rules, and Follow-Play Validation

**Status:** Complete. 509 tests passing.

**Branch:** `fix/bidding-ux-and-rules`

Four bugs/UX issues discovered during manual testing after M8.

### Fix 1 — Larger suit symbols + non-adjacent suit colours (frontend)

- `.card .card-suit` font-size increased `13px → 18px` so ♠♥♣♦ symbols
  are clearly readable at a glance.
- Suit order in hand (and bid buttons) changed from `[♠♥♦♣]` to `[♠♥♣♦]`
  (black–red–black–red alternating). Previously hearts and diamonds (both
  red) were adjacent, making them hard to distinguish. Updated in both
  `cardSortKey` (hand sort) and `renderBidArea` (bid suit buttons).

### Fix 2 — Bidding overtake rule: single cannot beat single (engine + handler + tests)

- **Bug:** `_can_overtake` allowed a single trump-rank card from a different
  player to overtake another single. The correct rule is that a single can
  only be beaten by a strictly stronger bid (pair or joker pair).
- **Fix:** Removed the `new_str == cur_str == 1 and different player` exception
  from `_can_overtake`. Now only `new_str > cur_str` returns True.
- **Handler change:** When a bid is placed, the bidder is immediately added to
  `passed_in_bidding` (as if they auto-passed themselves). Without this,
  auto-close could never trigger after a bid since the bidder's Pass button
  is disabled (Fix 3). With it, only the remaining 3 players need to pass
  for auto-close.
- Updated 3 tests in `test_bidding.py` to match corrected semantics.

### Fix 3 — Pass button disabled after the player has bid (frontend)

- If `gs.bids.some(b => b.player_id === S.playerId)`, the Pass button is
  disabled. A player who has placed a bid cannot take it back by passing.
  Players who have only passed (no bid) can still pass again after another
  player raises the bid.

### Fix 5 — Highlighted trump-rank section during bidding; updated suit order (frontend)

Two sub-changes:

**5a — Suit order finalised as ♦♣♥♠ everywhere**
Changed from `[♠♥♣♦]` (previous fix) to `[♦♣♥♠]` in both `cardSortKey` and bid
buttons. Still alternates red/black. `cardSortKey` group numbering simplified:
non-trump 0–3, trump-suit 4, all-trump-rank 5, jokers 6 (previously 7/8/9/10).

**5b — All trump-rank cards now in one contiguous block during playing phase**
Previously split across group 8 (off-suit trump rank) and group 9 (on-suit trump rank).
Now both are group 5, sub-sorted: off-suit by suit order, on-suit last.

**5c — Bidding-phase hand split**
During `DEALING` and `BIDDING_AFTER_DEAL`, `renderHand` divides the hand into:
- Main group: non-trump-rank, non-joker cards (sorted ♦♣♥♠ by rank)
- Highlighted group: trump-rank (any suit) + jokers, sorted ♦♣♥♠ then SJ then BJ

Highlighted cards shown below a gold dashed separator with the trump rank label.
Cards rendered with `.trump-highlight` (gold border + warm tinted background + glow).
Once bidding closes (phase → `BOTTOM_EXCHANGE`), the split collapses automatically
back into a single merged hand.

New helpers: `isJoker()`, `getTrumpRank()`, `sortBiddingMain()`, `sortBiddingHighlight()`.
New CSS: `.hand-trump-sep`, `.card.trump-highlight`.

### Fix 4 — Pass button visual feedback (frontend)

- Added `S.hasPassed` and `S.lastBidsCount` to app state.
- On press: immediately changes button to `"Passed ✓"` with a green CSS
  class `btn-passed` (green border + text, opacity:1 so it stays visible).
- `S.hasPassed` resets in `handleGameState` when `bids.length` increases
  (server cleared passed_in_bidding after a new bid, so all must pass
  again) or when phase transitions to `"dealing"` (new round).

### Fix 5 — Hand display during bidding (frontend)

- Hand split during `dealing`/`bidding_after_deal` into a main group and
  a highlighted trump-rank section separated by a gold dashed divider.
- Trump-rank cards and jokers rendered with gold border and warm tint.
- After bidding, hand merges back into a single sorted block with trump-rank
  cards grouped contiguously (off-suit first, then on-suit, then jokers).
- Suit order fixed everywhere to ♦ ♣ ♥ ♠ (alternating red/black).

### Fix 6 — Follow-play validation rejects valid cards (engine + tricks + tests)

Two bugs discovered during play-testing where legal cards were rejected:

- **Bug 1 (Single lead):** Player leads A♥; follower's 4♥ is rejected even
  though it is a valid heart. Root cause: `get_legal_plays` returns only
  `[suited[0]]` — the first arbitrary card in the suited list.
- **Bug 2 (Pair lead, no pair available):** Follower has no heart pair; 4♥+5♥
  is rejected but 10♥+J♥ is accepted, even though both are equally valid.
  Root cause: `_match_group`'s degraded path returns one arbitrary combination
  of 2 suited cards; any other combination fails `_cards_match_any`.

**Fix:** Added `is_valid_follow(proposed, hand, led_format, led_suit, ctx)` to
`tricks.py`. Validates by invariants directly:
- Single: any one suited card is valid
- IdenticalGroup(k): must include a group if hand has one; otherwise any k suited singles
- Tractor/Throw: falls back to `get_legal_plays` comparison

Both `engine.py` (play_cards) and `handler.py` (validate_play) updated to call
`is_valid_follow` instead of the old `get_legal_plays + _cards_match_any` pattern.
11 new regression tests added to `test_tricks.py`.

---

## Session 9 — M8 Frontend

**Status:** M8 complete. 499 tests passing (no new backend tests for M8 per spec).

**Branch:** `feat/m8-frontend`

### M8.1 — `index.html` full structure + CSS (committed)
- Three screens: Landing, Lobby, Game
- Landing: create-room form + join-room form, centered layout
- Lobby: top bar (room code + trump info), player list with host badge,
  slot placeholders for empty seats, mode selector (GM only),
  superuser enable section with inline confirm (GM only)
- Game screen: persistent top bar, 3×3 CSS-grid trick area (top/left/mid/right/bottom
  positions), points display, hand area, context-sensitive action area, error bar,
  modal overlay for round-over/game-over/aborted events
- Card CSS: suit-color classes (red/black/purple), selectable + selected states
  (`translateY(-12px)` lift per spec), 38×56 px card elements

### M8.2 — `app.js` — WebSocket client core + Lobby (committed)
- `S` state object: roomId, playerId, isGameMaster, ws, gameState, roomUpdate,
  selectedIndices, awaitingValidation
- REST helpers: `apiPost`, `createRoom`, `joinRoom`
- WebSocket: `connectWS`, `sendWS`, `dispatchMessage`
- All message handlers: room_update, game_state, card_dealt, round_over,
  game_over, game_aborted, play_valid, play_invalid, error
- Lobby rendering: 4-slot player list with Host badge, status text,
  mode selector (GM only, active-button highlighting), superuser section
- Trump info bar: derives display text from trump_context or defending players' rank
- Overlay: showOverlay / hideOverlay; "OK" button returns to landing, resets all state
- Room code click-to-copy (clipboard API)

### Pitfalls & Learnings (M8)

**Pitfall 1 — innerHTML+= destroys dynamically appended children**
In `renderFriendDeclaration`, using `row.innerHTML += "<label>...</label>"` after
`row.appendChild(selectEl)` resets the DOM, destroying the appended `<select>` element.
Fix: use `document.createElement("label")` + `appendChild` exclusively; never mix
`innerHTML +=` with `appendChild` on the same element.

**Pitfall 2 — Bottom exchange UI: leader sees 25 cards, not 33**
The engine adds bottom deck cards to the hand INSIDE `exchange_bottom()` (atomically
on the server), so the leader's `game_state.players[i].hand` has only 25 cards during
BOTTOM_EXCHANGE phase. The 8 bottom cards are in `gs.bottom_deck` (visible only to
the leader). The UI must explicitly combine hand + bottom_deck to show 33 cards and
allow selection from both pools. Card keys use `"hand:N"` / `"bot:N"` to track source.

**Pitfall 3 — round_leader_id not in to_player_view**
`round_leader_id` is only in `to_superuser_view`, not `to_player_view`. During
FRIEND_DECLARATION phase the frontend must detect the leader via `current_leader_id`
(which equals `round_leader_id` from the start of dealing until PLAYING begins).

**Pitfall 4 — Selecting indices shift when hand changes**
If `S.selectedIndices` (now `selectedKeys`) is not cleared on every game_state update,
stale indices can point to wrong cards after the hand array changes (e.g., a card
is dealt or played). The spec mandates clearing selection on every `game_state` update.

### M8.3 — `app.js` — Game screen + Dealing + Bidding + Playing (committed)
- Game phase transitions: shows game screen once DEALING begins
- Trick area (renderTrickArea): maps player indices to top/left/right/bottom
  positions (counter-clockwise seating); highlights current turn (gold) and
  trick leader (blue); shows played cards per position
- Points display: attacking pts + remaining to defend
- Hand rendering (renderHand): sorts hand by suit groups then rank, with trump
  cards grouped on the right; creates selectable card elements
- Card sort key: non-trump suits → trump suit → off-suit trump rank → on-suit
  trump rank → jokers; rank ascending within group
- Card element: Unicode suit symbol + rank display, colored by suit
- Bid area (renderBidArea): per-player available_bids from server enable/disable
  suit buttons (♠♥♦♣) and joker buttons; current bid display; Pass + Close
  Bidding buttons; dealing progress indicator
- Play area (renderPlayArea): Play button (validate_play → play_cards two-step),
  Clear Selection; disabled when not player's turn or no cards selected;
  validation message inline
- Bottom exchange (renderBottomExchange): select-8 counter, Confirm Exchange button
- Friend declaration (renderFriendDeclaration): rank/suit/ordinal dropdowns,
  Declare Friend button (Find Friends mode only)
- Round-over/game-over/game-aborted overlay handling

### Pending Tests — to be executed in M9

These items were not verified during M8 (frontend has no automated tests per spec).
They should be exercised as part of M9 integration testing.

**Browser / manual flow tests:**
- Create room → copy room code → join from 3 additional tabs (4 players total)
- Host selects mode (Upgrade and Find Friends) — verify buttons highlight, status text updates
- 4th player joins with mode already selected → verify auto-start (no manual action needed)
- 4 players join, no mode selected → verify prompt shown to host only
- During dealing: verify cards appear in hand sorted correctly (trump grouped right)
- Bid buttons enable only when player holds valid trump-rank cards (per server available_bids)
- Place a suit bid → verify current bid banner updates for all players
- Reinforce a bid (same suit, 2nd card) → verify pair label appears
- All 4 players pass during BIDDING_AFTER_DEAL → verify re-deal triggers
- Host closes bidding manually → verify BOTTOM_EXCHANGE phase begins
- Bottom exchange: bid winner sees 33 cards (25 hand + 8 bottom); select 8 → Confirm Exchange
- Bottom exchange: non-leader sees waiting message, not the exchange UI
- Find Friends mode: leader sees rank/suit/ordinal dropdowns; non-leaders see waiting message
- Upgrade mode: FRIEND_DECLARATION phase never appears
- Playing: select cards (verify translateY lift); Play → validate → commit
- Playing: invalid play (e.g., not following suit) → inline error, selection preserved
- Trick area: cards clear after trick is resolved; next leader highlighted
- Points display updates after each trick
- Round completes → round-over overlay shows score + rank advancement; auto-dismisses after ~4s
- Game continues into next round automatically after round-over
- Defender at rank A defends → game-over overlay; OK returns to landing
- Disconnect one player mid-game → game_aborted overlay on all remaining players; OK returns to landing
- Superuser enable: Host clicks "Enable Superuser Mode?" → confirm dialog appears → "Yes, Enable" → button disables with "ON" label

**Backend integration tests (M9.1 / M9.2):**
- Full round simulation (Upgrade): deal_specific_hands → close_bidding → exchange → play all 25 tricks → end_round → verify rank advancement
- Full round simulation (Find Friends): same flow with friend declaration; verify friend revealed at correct ordinal
- Last trick won by attackers with high-value bottom deck → verify multiplier applied
- All 4 players pass → re-deal fires correctly
- Game-over condition: defending team at rank A defends successfully

---

## Session 8 — M7 Networking & Room Management

**Status:** M7 complete. 499 tests passing. PR open for review.

**Branch:** `feat/m7-networking`

### M7.1 — `room.py` + `test_room.py` (committed)
- `Room` dataclass: `room_id`, `game_master_id`, `game_state`, `engine`, `connections`, `superuser_enabled`, `passed_in_bidding`
- `RoomManager`: `create_room`, `join_room`, `get_room`, `remove_room`, `all_room_ids`
- 6-char alphanumeric room codes; 12-char lowercase+digits player IDs
- 25 tests covering create/join/lifecycle/defaults

### M7.2 — `handler.py` — WebSocket message dispatch (committed)
- `compute_available_bids(player, trump_rank, current_bid)` — bid options per player hand
- Broadcast helpers: `broadcast_all`, `send_to`, `send_error`, `broadcast_game_states`, `broadcast_room_update`
- `start_and_deal(room, manager, deal_delay)` — asyncio task; creates engine, runs deal loop with callbacks
- `handle_round_end(room, manager, deal_delay)` — score, next round or game_over
- `abort_room(room, manager, reason)` — send game_aborted to all, clean up
- `handle_message(room, player_id, data, manager, deal_delay)` — dispatches 8 action types: `select_mode`, `bid`, `pass_bid`, `close_bidding`, `exchange_bottom`, `declare_friends`, `play_cards`, `validate_play`
- `handle_connection(ws, room_id, player_id, manager, deal_delay)` — full WebSocket lifecycle
- Auto-close bidding: `passed_in_bidding` set resets on each new bid; when all NUM_PLAYERS pass, `close_bidding()` fires automatically

### M7.3 — `app.py` + `test_app.py` — REST endpoints + superuser adapter (committed)
- `create_app(manager, deal_delay, mount_static)` factory for test isolation
- Routes: `GET /health`, `POST /rooms`, `POST /rooms/{room_id}/join`, `WS /ws/{room_id}/{player_id}`
- `_LiveSuperuserRoom` proxy: forwards `superuser_enabled` setter to the live `Room` (the enable endpoint mutates the returned object; a plain copy would discard the write)
- `_SuperuserRoomAdapter(dict)`: wraps `RoomManager` as a dict for the M6 superuser router; `get()` returns `_LiveSuperuserRoom`
- 15 REST tests covering health, room creation, join validation, superuser adapter

### M7.4 — `test_websocket.py` — WebSocket integration tests (committed)
- 23 tests covering: error cases, connection/lobby broadcasts, mode selection, dealing, bidding, disconnect/abort
- `_setup_deal` helper: race-free 4-player setup (see Pitfall #2 below)
- `_drain_until_phase` / `_next_of_type` helpers for message queue draining

### Pitfalls & Learnings (M7)

**Pitfall 1 — `_SuperuserRoomAdapter.__setitem__` never called**
The M6 enable endpoint does `room.superuser_enabled = True` on the object returned by
`rooms.get(room_id)`. First attempt returned a plain `SuperuserRoom` copy — mutations
were discarded. Fix: `get()` now returns `_LiveSuperuserRoom`, a proxy with a
`superuser_enabled` property setter that writes through to the actual `Room`.

**Pitfall 2 — TestClient WebSocket race condition (double `start_and_deal`)**
In Starlette's TestClient each WebSocket runs in its own OS thread with its own
asyncio event loop. If all 4 players are connected *then* `select_mode` is sent:
- LOOP 0 processes `select_mode`, sets `state.mode`, sees 4 players → schedules Task A
- LOOP 3 (ws[3]'s `handle_connection`) runs its auto-start check concurrently and
  also sees mode set + 4 players → schedules Task B

Two deals run in parallel → 4 `bidding_after_deal` messages per player instead of 2.
Subsequent assertions read the wrong message.

Fix: send `select_mode` when only 1 player is connected (auto-start check fails: 1≠4).
Connect players 1, 2, then player 3 last — `handle_connection` for player 3 sees
4 players + mode set → fires exactly ONE auto-start. In all timing scenarios this
produces exactly 2 `bidding_after_deal` messages (one from `on_card_dealt` after the
last card, one from `start_and_deal`'s final `broadcast_game_states`).

**Pitfall 3 — Two `bidding_after_deal` messages per deal**
`start_and_deal` emits two `game_state(bidding_after_deal)` messages: (1) from the
`on_card_dealt` callback after the last card triggers the phase transition, and (2)
from the explicit `broadcast_game_states` at the end of the function. Tests must
consume BOTH before issuing further actions (e.g. `close_bidding`). The `_setup_deal`
helper does this: `_drain_until_phase(ws, "bidding_after_deal")` consumes #1;
`ws.receive_json()` consumes #2.

---

## Session 7 — M6 Superuser Mode

**Status:** M6 complete. 436 tests passing. PR open for review.

**Branch:** `feat/m6-superuser`

### M6.1 — `inspector.py` — read-only inspection (committed)
- `get_full_state(state)` — delegates to `state.to_superuser_view()`
- `validate_state(state) -> list[str]` — returns violation strings (empty = clean):
  - Total card count = 108 (skipped in WAITING)
  - No card appears more than 2 times (2-deck limit)
  - `trump_context` required in BOTTOM_EXCHANGE, FRIEND_DECLARATION, PLAYING, SCORING, ROUND_OVER
  - No player hand exceeds HAND_SIZE (25)
  - `round_leader_id` and `current_turn_id` (in PLAYING) must reference valid players
  - `attacking_points` must be ≥ 0
- 20 tests in `test_inspector.py`

### M6.2 — `mutator.py` — state mutations (committed)
- `set_hand(state, player_id, cards)` — replaces player's hand; returns validation warnings
- `set_bottom(state, cards)` — replaces bottom deck; returns warnings
- `set_points(state, attacking_points)` — overrides attacking_points; returns warnings
- `force_phase(state, phase)` — bypasses transition graph, sets phase directly; returns warnings
- `deal_specific_hands(state, hands, bottom)` — deterministic card distribution; clears draw_pile and tricks; returns warnings
- Each mutation is non-fatal: violations returned as warnings, not raised
- 22 tests in `test_mutator.py` including end-to-end "deal then play" integration

### M6.3 — `api.py` — FastAPI router (committed)
- `SuperuserRoom` dataclass: `room_id`, `game_master_id`, `game_state`, `superuser_enabled`
- Module-level `_rooms` dict; injectable via `create_router(rooms)` for test isolation
- `POST /superuser/enable/{room_id}` — sets `superuser_enabled=True`; game master only; idempotent
- `GET /superuser/state/{room_id}` — full state (all hands visible)
- `POST /superuser/validate/{room_id}` — returns `{valid, violations}`
- `POST /superuser/set-hand/{room_id}` — body: `{player_id, cards}`
- `POST /superuser/set-points/{room_id}` — body: `{attacking_points}`
- `POST /superuser/force-phase/{room_id}` — body: `{phase}`; 400 on unknown phase
- `POST /superuser/deal-specific/{room_id}` — body: `{hands, bottom}`
- Access control: all endpoints except enable require `superuser_enabled=True`; `X-Player-Id` header must match `game_master_id`; 403 otherwise
- 24 tests in `test_api.py` covering: enable flow, idempotency, non-GM rejection, not-enabled rejection, all mutation endpoints, unknown room 404

### Pitfalls & Learnings (M6)
- No pitfalls during M6. All 66 new tests passed first run.

---

## Session 6 — M5 Mode Strategies

**Status:** M5 complete. 370 tests passing. PR open for review.

**Branch:** `feat/m5-mode-strategies`

### M5.1 — `ModeStrategy` abstract base class (committed)
- `src/shengji/modes/base.py`:
  - `assign_teams(state)` — abstract; sets `is_defending` + `team` on every player
  - `get_attacker_ids(state)` — concrete default; reads `is_defending` flags
  - `needs_friend_declaration()` — abstract
  - `validate_friend_declaration(state, declarations)` — abstract
  - `resolve_friend(state, player_id, card)` — abstract; called per card played
  - `on_round_end(state, winner_team)` — abstract; updates team roles for next round
  - `get_next_leader(state, winner_team)` — abstract; returns next round_leader_id

### M5.2 — Engine integration (committed)
- `close_bidding()`: calls `self.mode.assign_teams(state)` after bid winner determined
- `play_cards()`: calls `self.mode.resolve_friend(state, player_id, card)` for each card played
- `end_round()`: calls `self.mode.on_round_end(state, winner)` before `get_next_leader()`
- Updated all 4 test stubs (`test_bidding`, `test_bottom_exchange`, `test_game_loop`, `test_scoring`) to include new no-op methods

### M5.3 — `UpgradeStrategy` (committed)
- `src/shengji/modes/upgrade.py`:
  - `assign_teams`: seats 0,2 vs seats 1,3; leader's parity determines which pair defends
  - `on_round_end`: flips all `is_defending` flags when attackers win; no-op when defenders win
  - `get_next_leader`: counter-clockwise next player on winning team (uses updated `is_defending` after `on_round_end`)
- 18 tests in `test_upgrade.py` covering all seat-parity assignments, role swaps, leader rotation

### M5.4 — `FindFriendsStrategy` (committed)
- `src/shengji/modes/find_friends.py`:
  - `assign_teams`: leader defends alone; resets `_play_counts` for fresh round
  - `validate_friend_declaration`: 1 friend for 4 players; rejects trump-rank and joker cards; leader declaring own card is allowed (1v3 edge case)
  - `resolve_friend`: increments per-card play counter; triggers declaration when count matches ordinal; marks friend as `is_defending=True`; supports sequential ordinals on same card
  - `on_round_end`: no-op (teams reset each round via `assign_teams`)
  - `get_next_leader`: counter-clockwise from current leader on winning team
- 24 tests in `test_find_friends.py` covering: leader-alone init, friend revelation at correct ordinal, sequential ordinals, leader-as-own-friend edge case, resolved declaration skipped, leader rotation

### Pitfalls & Learnings (M5)
- No pitfalls encountered during M5. The engine integration was clean because the stub design in M4 anticipated the ModeStrategy interface closely enough that only no-op method additions were needed in existing test stubs.

---

## Session 5 — M4 Game Engine

**Status:** M4 complete. PR open for review. Ready to implement M5 (Mode Strategies) once approved.

**Branch:** `feat/m4-game-engine`

### M4.1 — Engine skeleton + dealing (committed)
- `start_dealing()`: validates mode/phase, shuffles new deck, clears per-round state, transitions to `DEALING`
- `deal_next_card()`: routes cards counter-clockwise from player after round leader; transitions to `BIDDING_AFTER_DEAL` when draw pile empties
- `deal_all_cards()`: async loop with configurable delay and per-card callback
- 29 tests in `test_dealing.py`

### M4.6 — Scoring + `end_round()` (committed)
- `scoring.py`:
  - `count_attacking_points(tricks_won, attacker_ids, bottom_deck, last_trick_winner_id, last_trick_cards, ctx)`: sums attacker trick points; applies `2 × largest_component_length` multiplier to bottom-deck points when attackers win the last trick
  - `compute_rank_advancement(attacking_points, n_decks)`: full 7-band threshold table — 0 → defending+3; 1-99n → defending+2; 100n-199n → defending+1; 200n-299n → attacking+0; 300n-399n → attacking+1; 400n-499n → attacking+2; 500n+ → attacking+3
- `end_round()` in engine: validates SCORING phase; delegates team lookup to `mode.get_attacker_ids()`; counts points; calls `compute_rank_advancement`; advances winning team ranks; detects game-over (defender at ACE after successful defense); calls `mode.get_next_leader()`; increments round number; transitions to `ROUND_OVER` or `GAME_OVER`
- 30 tests in `test_scoring.py` covering all 7 threshold boundaries, bottom multiplier, tractor multiplier, rank clamping, and game-over detection — **328 total passing**

### M4.5 — `play_cards()` + full trick lifecycle (committed)
- `play_cards(player_id, cards)`: validates phase/turn/card-ownership; leader validates throw; follower validated against `get_legal_plays()`; resolves trick on 4th play; winner gets trick, leads next; round-over detected when all hands empty → transitions to `SCORING`
- Fixed: `current_turn_id` set to `round_leader_id` when entering PLAYING (from both `exchange_bottom` and `declare_friends`)
- `_cards_match_any()` module helper for multiset comparison of played vs legal plays
- Full-round simulation helper `_play_one_trick_auto()` uses `get_legal_plays()` for realistic follower responses
- 16 tests in `test_game_loop.py` (preconditions, single trick, full 25-trick round with card accounting) — 298 total passing

### M4.4 — Trick logic (`tricks.py`) (committed)
- `get_legal_plays(hand, led_format, led_suit, ctx)`: follower must match format to the best of their ability — exact match if enough suited cards, else all suited + fill with anything; degrades gracefully: tractor > pairs > singles
- `validate_throw(throw_cards, thrower_id, all_hands, ctx)`: throw invalid if any opponent holds a same-suit non-trump card that beats any component
- `resolve_trick_winner(trick, led_suit, ctx)`: off-suit plays ineligible to win; trump beats non-trump; highest card_order wins; first player wins ties
- All 4 dynamic adjacency cases from spec tested (trump rank 4/9/3/2)
- 28 tests in `test_tricks.py` — 282 total passing

### M4.3 — Bottom exchange + friend declaration (committed)
- `exchange_bottom(player_id, cards_to_put_back)`: validates phase/player/count; leader picks up 8 bottom cards (33 total), buries 8, hand returns to 25; delegates phase transition to mode strategy (`FRIEND_DECLARATION` for Find Friends, `PLAYING` for Upgrade)
- `declare_friends(player_id, declarations)`: validates phase/player, calls `mode.validate_friend_declaration()`, stores declarations, transitions to `PLAYING`
- 17 tests in `test_bottom_exchange.py` — 254 total passing

### M4.2 — Bidding (committed)
- `place_bid(player_id, cards)`: validates phase, card ownership, bid legality (trump rank, joker pair rules), and overtaking strength. Updates `state.bids` and live `trump_context`.
- `close_bidding()`: finalises bidding — re-deals on no bids (clears hands, calls `start_dealing`); otherwise promotes winning bidder to `round_leader_id`, locks trump context, transitions to `BOTTOM_EXCHANGE`.
- Static helpers: `_bid_strength()`, `_validate_bid_cards()`, `_can_overtake()`
- Bid strength tiers: suited single (1) < suited pair (2) < small joker pair (3) < big joker pair (4)
- Suited pairs cannot overtake other suited pairs; same player cannot re-bid a single with a different suit
- 44 tests in `test_bidding.py` — 237 total passing

---

## Session 4 — M2 + M3 Implementation

**Status:** M2 and M3 complete. Ready to implement M4 (Game Engine).

**Branch:** `feat/m3-game-state` → open PR for review.

**Completed:**

**M2 — Trump System & Card Ordering**
- `src/shengji/models/trump.py`:
  - `TrumpContext(trump_rank, trump_suit)` — frozen dataclass
  - `card_order(card) -> tuple[int, int]` — 6-tier sortable key (tier 0: off-suit, 1: trump suit, 2: off-suit trump rank, 3: on-suit trump rank, 4: small joker, 5: big joker)
  - `effective_suit(card) -> str` — "trump" for jokers/trump-rank/trump-suit cards; own suit in no-trump mode
  - `are_tractor_adjacent(card1, card2) -> bool` — dynamic adjacency including circular wrap for non-trump suits and cross-tier adjacency through the trump hierarchy
- `src/shengji/models/groups.py`:
  - `TrickFormat` union type: `Single`, `IdenticalGroup(count)`, `Tractor(multiplicity, length)`, `Throw(components)`
  - `find_identical_groups(cards, ctx)` — groups of size ≥ 2 by exact identity
  - `find_tractors(cards, ctx)` — maximal consecutive identical-group runs respecting dynamic adjacency
  - `classify_play(cards, ctx)` — classifies any card set into a TrickFormat
- **76 new tests — all passing** (`test_trump.py`, `test_groups.py`)

**M3 — Game State Model**
- `src/shengji/models/player.py`:
  - `Player(id, name, hand, rank, is_defending, team)`
  - `advance_rank(steps)` — clamps at ACE; raises on negative steps
  - `is_at_max_rank` property
  - `to_json(include_hand)` — hides hand when `include_hand=False`, always exposes `hand_size`
- `src/shengji/models/bid.py`:
  - `Bid(player_id, cards, resulting_trump)` — records a bid with the TrumpContext it would produce
- `src/shengji/models/friend_declaration.py`:
  - `FriendDeclaration(card, ordinal, resolved_player_id)` — Find Friends friend card declaration
  - `is_resolved` property
- `src/shengji/models/game_state.py`:
  - `GamePhase` enum: `WAITING → DEALING → BIDDING_AFTER_DEAL → BOTTOM_EXCHANGE → [FRIEND_DECLARATION →] PLAYING → SCORING → ROUND_OVER → [DEALING | GAME_OVER]`
  - `GameState` — authoritative state; all fields per spec
  - `transition_to(phase)` — enforces valid transitions, raises `ValueError` on illegal moves
  - `to_player_view(player_id)` — hides other players' hands; hides bottom deck except to round leader during `BOTTOM_EXCHANGE`
  - `to_superuser_view()` — full visibility: all hands, bottom deck, draw pile size, tricks won, friend declarations
- **53 new tests — all passing** (`test_player.py`, `test_game_state.py`)
- **164 total tests passing**

**Next steps (Session 5):**
- M4: `src/shengji/engine/engine.py` — `GameEngine` with dealing loop, bidding, bottom exchange, trick play, scoring
- M4: `src/shengji/engine/tricks.py` — trick resolution, `get_legal_plays`, throw validation
- M4: `src/shengji/engine/scoring.py` — point counting, bottom deck multiplier, rank advancement

---

## Session 2 — M0 + M1 Implementation

**Status:** M0 and M1 complete. PR #1 merged. Ready to implement M2 (TrumpContext + card ordering).

**Branch:** `feat/m0-m1-skeleton` → merged to `main` via PR #1 at https://github.com/JCoder121/eighty-points/pull/1

**Completed:**

**M0 — Project Skeleton**
- `pyproject.toml`: `setuptools` build backend, `requires-python = ">=3.10"`, deps (`fastapi`, `uvicorn[standard]`, `websockets`, `pydantic`), dev deps (`pytest`, `pytest-asyncio`, `httpx`, `ruff`), `asyncio_mode = "auto"`, `testpaths = ["tests"]`.
- Full directory layout: `src/shengji/{models,engine,modes,network,superuser}/__init__.py`, `tests/{test_models,test_engine,test_modes,test_network,test_superuser,test_integration}/__init__.py`, `tests/conftest.py`, `scripts/replay_log.py`, `frontend/{index.html,app.js}`, `logs/games/` (empty dir, `.jsonl` files gitignored).
- Minimal FastAPI app at `src/shengji/network/app.py`: `GET /` returns `{"status": "ok", "game": "shengji"}`.
- `README.md` with the four dev commands.
- `.gitignore` updated: `__pycache__/`, `*.pyc`, `*.egg-info/`, `.pytest_cache/`, `.ruff_cache/`, `logs/games/*.jsonl`.

**M1 — Card & Deck Models**
- `src/shengji/models/card.py`:
  - `Suit` enum: `SPADES`, `HEARTS`, `DIAMONDS`, `CLUBS`, `JOKER`
  - `Rank` enum: `TWO`–`ACE`, `SMALL_JOKER`, `BIG_JOKER`
  - `RANK_ORDER: list[Rank]` — 13 suited ranks in order (used for adjacency in M2)
  - `SUITED_SUITS: list[Suit]` — the 4 non-joker suits
  - `Card(suit, rank)` — frozen dataclass; `__post_init__` validates joker suit↔rank pairing
  - `point_value` property: 5→5, 10→10, K→10, all others→0
  - `to_json() -> dict` / `Card.from_json(dict)` — `{"suit": "spades", "rank": "K"}`
- `src/shengji/models/deck.py`:
  - Constants: `NUM_PLAYERS=4`, `NUM_DECKS=2`, `BOTTOM_SIZE=8`, `TOTAL_CARDS=108`, `HAND_SIZE=25`
  - `Deck` — internal `_cards: list[Card]` of 108 cards (2 × 54)
  - `shuffle()` — `random.shuffle` in place
  - `prepare_deal() -> tuple[list[Card], list[Card]]` — calls `shuffle()`, returns `(draw_pile[100], bottom_deck[8])`; index 0 of draw_pile is dealt first
- **35 tests — all passing** (`tests/test_models/test_card.py`, `tests/test_models/test_deck.py`)

**Environment note:** Python 3.10.9 via miniconda (`/Users/jeffrey/miniconda3/`). Install with `pip install -e ".[dev]"`.

**Next steps (Session 3):**
- M2: `src/shengji/models/trump.py` — `TrumpContext(trump_rank, trump_suit)` with `card_order()` and `effective_suit()`
- M2: `src/shengji/models/groups.py` — `find_identical_groups`, `find_tractors`, `classify_play`
- M2 tests: trump ordering, dynamic adjacency (trump rank 4 → 3&5 adjacent, trump rank 9 → 8&10 adjacent, trump rank 3 → 2&4 adjacent, trump rank 2 → A&3 adjacent edge case), tractor detection, `classify_play`

---

## Session 1 — Project Planning

**Status:** Implementation plan complete. Ready to begin coding.

**Completed:**
- Drafted full `IMPLEMENTATION_PLAN.md` covering all 9 milestones (M0–M9) plus appendices.
- Defined tech stack: Python + FastAPI + WebSockets backend, vanilla HTML/JS frontend.
- Clarified all game rules against the reference site (trump ordering, dynamic adjacency, bidding mechanics, scoring thresholds).
- Established architecture principles: shared `GameEngine` with `ModeStrategy` injection, superuser as first-class feature, card-by-card dealing with integrated bidding.
- Added full UX spec: lobby layout, bidding UI (suit buttons), card selection/play flow, no trick history (by design).
- Added game session logging (`.jsonl`), `replay_log.py` debugging script, and tech stack pros/cons.

**Decisions made:**
- Always 4 players, always 2 decks (108 cards). No variable player count.
- Cards dealt one at a time with `asyncio.sleep(DEAL_DELAY_SECONDS)`. No deal-all-at-once simplification.
- Bidding is suit-based (click a suit button), not card-selection. Server validates card availability.
- Disconnect behavior: all players kicked, room destroyed. No reconnect (see Future Todos).
- No trick history in UI — players must count cards from memory.
- Game master must explicitly select Upgrade or Find Friends before game can start.
- Superuser mode restricted to game master only; requires explicit confirmation button click.

**Next steps (first PR):**
- M0: Create project skeleton, `pyproject.toml`, directory layout.
- M1: Implement `Card`, `Deck` models with tests.
- M2: Implement `TrumpContext`, `classify_play`, `find_tractors` with tests.
