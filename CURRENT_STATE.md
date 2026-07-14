# Shengji — Current State

> **First read through this document.** If gaps arise in your understanding, look at
> `IMPLEMENTATION_PLAN.md` and `PROGRESS.md`.

---

## Where we are

- **All milestones (M0–M9) are complete** — M9's integration suite was backfilled in Session 26 (`tests/test_integration/`, 40 tests).
- **621 tests passing** (pytest).
- **Scoring:** 80 pts to win, 20-pt bands; attacking advancement capped at +3 (#51); defending shutout +4. Game over only when defending while ALREADY at Ace (#52). Bottom multiplier = 2× winning play's largest component, capped 8× — single 2×, pair 4×, tractor 8× (#57).
- **Pairs require identical cards (#50):** equal-strength off-suit trump-rank cards (e.g. 2♦+2♣) no longer form phantom pairs/quads — grouping is by identity everywhere (classify, follow validation, tractors, throw checks); strength/tie rules unchanged.
- **Seeded terminal harness:** `python scripts/play_cli.py` — interactive play (all seats or `--human N`) and `--bots --games N` fuzzer with per-action `validate_state` sweep. Deck/GameEngine accept an injectable `random.Random`. Run the fuzzer after any engine change.
- **Handler hardening:** a non-ValueError bug in message handling no longer destroys the room (contained + logged + per-player error); `validate_state` runs after every action with violations logged; `led_format`/`led_suit` are declared GameState fields.
- **Current branch:** `main`
- **No automated frontend tests yet.** All frontend testing is manual (a Playwright smoke pass was run in Session 26; full suite is issue #29).
- **Mobile layout:** Basic responsive support added — horizontal scroll hand on portrait mobile (≤600px), larger tap targets.
- **Active work:** Bug fixes and polish discovered through manual play-testing.
- **Find Friends mode** is fully implemented: correct phase ordering (declare before exchange), trump-suit/rank/joker restrictions, permanent friend status bar, friend reveal popups.
- **Jokers display as 大/小** (Big Joker = 大, Small Joker = 小) in all UI locations; backend identifiers unchanged.
- **End screen shows rank progression** (`old → new`) so players can see what changed each round.
- **Unique player names enforced:** server rejects duplicate names in a room (HTTP 400).
- **Leader displayed in UI:** trump info bar shows `· Leader: {name}` after leader is determined; round 2+ leader is predetermined (not overridden by bidding).
- **Bottom cards shown at round-over recap** for all players regardless of outcome.
- **Trick hold delay:** every completed trick holds 3s (single/pair) or 5s (>2 cards) before clearing so all players can review.
- **Bidding pass fix:** outbid players can now pass (frontend checked current highest bidder only).
- **No-trump mode fix:** trump-rank cards (2s) correctly treated as trump for trick-following and throw validation.
- **Throw trick-winning:** format-matching trump required to beat a throw lead (pair for pair, single for single).
- **Re-deal notification:** all-pass triggers a visible banner to all players before re-dealing.
- **Failed-throw penalty (#60):** a leader's failed 甩牌 is no longer rejected — the engine forces the smallest beatable component (rest stays in hand) and the thrower concedes 10 pts/attempted card, attributed to teams at round end by FINAL teams (Find Friends reveals respected). Frontend shows a confirm dialog before any throw lead (`check_play` WS action) and a banner to all players when a throw fails.

## What's built

| Layer | Module(s) | Status |
|---|---|---|
| Card & Deck models | `models/card.py`, `models/deck.py` | Complete |
| Trump system & ordering | `models/trump.py`, `models/groups.py` | Complete |
| Game state model | `models/game_state.py`, `models/player.py`, `models/bid.py`, `models/friend_declaration.py` | Complete |
| Game engine | `engine/engine.py`, `engine/tricks.py`, `engine/scoring.py` | Complete |
| Mode strategies | `modes/upgrade.py`, `modes/find_friends.py` | Complete |
| Superuser tools | `superuser/inspector.py`, `superuser/mutator.py`, `superuser/api.py` | Complete |
| Networking & rooms | `network/app.py`, `network/handler.py`, `network/room.py` | Complete |
| Game logger | `engine/logger.py` | Complete |
| Frontend | `frontend/index.html`, `frontend/app.js` | Complete (no mobile support) |

## How to run

```bash
pip install -e ".[dev]"           # install
pytest                             # run tests
uvicorn shengji.network.app:app --reload   # start server at localhost:8000
```

## Debugging with game logs

**Every game session writes a JSONL log to `logs/games/{unix_timestamp}.jsonl`.**
When investigating a bug, start here before reading code.

Each line is one JSON event. Key events:

- `round_start` — full snapshot of all 4 hands, bottom deck, teams, and player ranks at the start of each round. **Start here** to reconstruct the game state.
- `play_cards` + `trick_complete` — every card played and every trick resolved, with running attacking_points.
- `friend_revealed` — when a friend is identified in Find Friends mode.
- `round_end` — full scoring breakdown: attacking_points, winner, steps, post-advancement ranks.
- `error` — any engine validation failure, with the action and player that triggered it.

**Workflow for debugging an issue:**
1. Reproduce the bug while the server is running to capture a log file.
2. Find the relevant log in `logs/games/` (latest timestamp).
3. Read the `round_start` event to get initial hands and trump context.
4. Trace `play_cards` / `trick_complete` events to find where behavior diverged.
5. Cross-reference `engine/tricks.py`, `engine/scoring.py`, or `modes/` as needed.

Log files are gitignored (`logs/games/*.jsonl`).

## Tracking work

Bug reports, pending tests, and enhancements are tracked as **GitHub Issues**.
Run `gh issue list --state open` to see what needs doing.

---

## Notes & Reference

### How to leverage Claude CLI for testing in future projects

This is the first project using Claude CLI for end-to-end planning and implementation. Here is a practical guide for how to use Claude and its ecosystem more effectively for both backend and frontend testing on a web-based card game like this one.

#### Backend testing (pytest)

The current setup is already well-structured — pytest with a real in-process FastAPI test client. Claude CLI can help you go further:

**What to ask Claude to do directly:**
- Write new pytest tests for edge cases you find during manual play. Just describe the bug ("Player A leads a single, follower's card is rejected") and Claude can write the regression test and the fix together in one pass — as it did for the follow-play validation bugs.
- After any engine change, ask Claude to audit the test suite for gaps: "Are there cases in `tricks.py` that the current tests don't cover?" This works well because Claude can read the source and the tests side-by-side.
- Use Claude to write `conftest.py` fixtures and shared helpers (e.g., `_setup_deal`) so that new tests stay short and focused.

**Structured workflow that works well:**
1. Write a failing test first (describe the expected behavior to Claude).
2. Ask Claude to make it pass without breaking existing tests.
3. Run `pytest` in the terminal and paste failures back if any arise.
4. Repeat. Claude remembers the context within a session, so iteration is fast.

**WebSocket integration tests** are the hardest to write by hand — they require careful message ordering and async coordination. Claude CLI is particularly useful here because it can reason about the full message sequence (as it did with the `_drain_until_phase` / `_next_of_type` helpers in M7). Be explicit: paste the sequence of messages you expect and let Claude scaffold the test around them.

#### Frontend testing (Playwright)

[Playwright](https://playwright.dev/) is a browser automation library made by Microsoft. It lets you write Python (or JS/TypeScript) scripts that control a real browser — clicking buttons, reading the DOM, checking what appears on screen. For a WebSocket-based game like this, it is the right tool for end-to-end frontend tests.

**How it fits this project:**

```
Playwright script
  │
  │  Opens 4 browser tabs (one per player)
  │  Each tab connects to localhost:8000 over a real WebSocket
  │  Script clicks buttons, reads displayed state, asserts expected outcomes
  ▼
uvicorn (running locally) ← your actual FastAPI + game engine
```

This tests the complete stack — Python engine, WebSocket handler, JavaScript rendering — all at once. It can catch bugs that unit tests miss (like the phase-string case mismatch that broke the lobby, or the Pass button not updating visually).

**How to use Claude CLI with Playwright:**
- Ask Claude to write Playwright tests given a description of a user flow. Example: "Write a Playwright test that opens 4 tabs, creates a room in the first, joins from the other three, and asserts that all four see the dealing phase begin."
- Claude can read your `app.js` and generate selectors that match your actual DOM structure (`data-testid` attributes, class names, button text).
- Add `data-testid="..."` attributes to key elements in `index.html` before writing tests — ask Claude to add them. This makes selectors stable even when CSS classes change.
- Playwright has a codegen tool (`playwright codegen http://localhost:8000`) that records your manual clicks and generates a test script. You can paste that generated script to Claude and ask it to clean it up, add assertions, and parametrize it.

**Recommended setup:**
```bash
pip install pytest-playwright
playwright install chromium
```
Then Playwright tests live alongside your pytest suite and run with the same `pytest` command.

#### Claude Chrome Extension

The [Claude chrome extension](https://chromewebstore.google.com/detail/claude-ai/ghbhpddlgkpamgnohekoghlicdopgmdb) is a different tool from Claude CLI — it lets you use Claude from within the browser, including highlighting elements on a webpage and asking questions about them. It is useful for:

- **Visual debugging:** Open your game, highlight a broken UI element, and ask Claude "why is this card overlapping the trick area?" — Claude sees the page visually and can reason about CSS layout.
- **One-off questions about the live page:** You can ask it to explain what a WebSocket message contains, or to look at the currently rendered DOM and identify a bug.
- **Not a replacement for Playwright:** The Chrome extension is interactive and manual. Playwright is automated and repeatable. Use the extension for exploratory debugging; use Playwright for regression tests.

#### Summary: recommended testing workflow going forward

| Layer | Tool | When to use |
|---|---|---|
| Game engine (pure Python) | pytest | After every engine change; Claude writes tests + fixes together |
| WebSocket integration | pytest + TestClient | For message-sequence correctness; Claude scaffolds helpers |
| Full browser E2E | Playwright | Before sharing with players; covers JS rendering + UX flows |
| Visual/CSS debugging | Claude Chrome extension | Exploratory debugging of layout issues on a live local page |

**The highest-leverage habit:** before starting any new milestone, ask Claude to draft a test plan alongside the implementation plan. The M8 "Pending Tests" section in PROGRESS.md was written after the fact; writing it first forces you to think about what "done" looks like and gives Claude a checklist to work from rather than discovering gaps during manual play.

---

### Mobile / cross-device experience is not designed for yet

This game is intended to be played with friends across a mix of devices — phones, tablets,
and laptops. The current frontend makes **no concessions for small screens or touch input**.
This is a design decision that needs to be resolved before the game is shared with anyone.

**What the current UI assumes:**
- A reasonably wide screen (700 px+ for the hand area to spread out without wrapping awkwardly)
- A mouse or trackpad for clicking small card elements (38 × 56 px each — tight on a phone touchscreen)
- A keyboard is not required, but the card elements and buttons are sized for pointer devices

**What happens on a phone today:**
- The hand area wraps into multiple rows and may overflow or look cramped
- Cards (38 × 56 px) are hard to tap accurately on a small touchscreen
- The 3 × 3 trick grid shrinks but does not reflow — text may overlap
- Bid buttons and the Pass button are usable but tightly spaced
- There is no viewport scaling other than the `<meta name="viewport">` tag already present

**Design options to consider:**

| Option | Tradeoff |
|---|---|
| **Require laptop/desktop** | Simplest. Just tell your friends "use a computer." Eliminates the problem entirely for this version. |
| **Responsive layout (CSS media queries)** | Moderate effort. Increase card sizes for touch, reflow the trick grid to vertical on narrow screens, make buttons finger-friendly (min 44 px tap targets per Apple/Google HIG). |
| **Progressive Web App (PWA)** | Larger effort. Add a manifest + service worker so players can install the game to their phone home screen, giving a more native feel. Does not solve the layout problem on its own. |
| **Separate mobile UI** | Most effort. A second simplified view tuned for small screens (e.g., scrollable hand, larger tap zones, collapsed trick area). |

**Recommended path:** Make a deliberate choice before inviting players. If everyone can use
a laptop for now, document that as the expectation and revisit responsiveness in a later
milestone. If mobile support is required from day one, plan a CSS media-query pass before
testing with real players.

---

### Debugging notes (resolved)

These bugs were found and fixed during manual testing. Kept here as reference for understanding past design decisions.

#### Phase-string case mismatch (Session 10)
The Python `GamePhase` enum stores lowercase values (`"waiting"`, `"dealing"`, etc.) but `app.js` originally compared against uppercase (`"WAITING"`, `"DEALING"`). Every phase check failed silently. **Fixed:** Changed all JS phase literals to lowercase.

#### Follow-play validation rejects valid cards (Session 10)
Two bugs where legal cards were rejected. A single lead returned only one arbitrary legal card instead of all suited cards. A degraded pair returned one arbitrary combination instead of allowing any. **Fixed:** Added `is_valid_follow()` to `tricks.py` that checks invariants directly.

#### Throw validation: pair components require a pair to beat (Session 12)
`validate_throw` had wrong card assignment and wrong beat checks. A single A could "beat" a K-K pair. **Fixed:** Rewrote with `_assign_throw_components` and `_single_opp_beats_component`.

#### Degraded follows cannot win the trick (Session 11)
A follower with no pair could "win" a pair-lead trick with two high singles. **Fixed:** Added `_format_can_beat_lead()` — degraded responses are ineligible to win.

---

### Q&A Reference

#### How does the JS frontend connect to the game engine?

```
Browser (index.html + app.js)
        │
        │  Step 1: HTTP REST (create/join room)
        │  POST /rooms          → { room_id, player_id }
        │  POST /rooms/XYZ/join → { player_id }
        ▼
FastAPI server (app.py)
        │
        │  Step 2: WebSocket upgrade
        │  GET /ws/{room_id}/{player_id}  (browser opens persistent connection)
        │
        │  ◄── server pushes JSON messages whenever game state changes
        │  ──► browser sends JSON messages when player takes an action
        ▼
handler.py  →  GameEngine  →  GameState
```

1. **User clicks "Create Room"** — `app.js` makes a POST to `/rooms`. Server creates a room and returns `room_id` + `player_id`.
2. **`app.js` opens a WebSocket** to `/ws/{room_id}/{player_id}`. Unlike HTTP, this is a persistent two-way channel.
3. **Server pushes state** via `broadcast_game_states()` on every change. Browser re-renders from scratch.
4. **Client sends actions** like `{"action": "play_cards", "cards": [...]}`. Handler calls engine, engine mutates state, broadcast goes out.

**Key insight:** The browser never computes game logic. It only renders what the server tells it.

#### Joining a lobby that does not exist

Handled and tested. `POST /rooms/{room_id}/join` returns HTTP 400 with `"Room ... not found"`. Frontend catches and displays the error. Also tested: joining full rooms and games in progress.

#### Capacity, scaling, and fault tolerance

**Capacity:** No hardcoded limit. A cheap VPS handles hundreds to thousands of rooms. Each room is well under 1 MB of Python objects.

**Scaling:** Currently single-process, in-memory state. Horizontal scaling would require moving state to Redis + pub/sub for WebSocket forwarding. Not needed for playing with friends.

**Fault tolerance:** Currently none. Server restart = all rooms lost. Player disconnect = room destroyed (no reconnect grace period). No persistence. This is an intentional tradeoff for simplicity.

#### Going from localhost to production

Simplest path: push to GitHub → deploy on Render (free tier) → get `*.onrender.com` URL with HTTPS. The code needs zero changes. Optionally buy a domain and point DNS at it.

#### Favicon 404

Harmless — browsers auto-request `/favicon.ico`. Fix with `<link rel="icon" href="data:,">` in `<head>` when desired.
