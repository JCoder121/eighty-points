# Jeff's Testing Notes

---

## Important Notes

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

## Debugging

### After 4 players join, lobby shows "Game in progress..." and everything is stuck

**Observed behavior:** After simulating 4 players joining the lobby, all 4 browser windows show "Game in progress..." in the lobby status area and nothing else happens. The game never starts and no UI transitions occur.

**Root cause:** Phase string case mismatch between server and frontend.

The Python `GamePhase` enum stores **lowercase** string values (`"waiting"`, `"dealing"`, `"bidding_after_deal"`, etc.) and the server sends these lowercase values in every `game_state` message via `self.phase.value`. However, `app.js` compares phases against **uppercase** strings (`"WAITING"`, `"DEALING"`, etc.) everywhere.

This causes every phase check to fail silently:
- `phase !== "WAITING"` is always `true` (since `"waiting" !== "WAITING"`) → shows "Game in progress..." immediately, even in the lobby before the game starts
- `gamePhases.includes(msg.phase)` always returns `false` → frontend never transitions to the game screen
- `phase === "WAITING"` is always `false` → mode selector is always hidden, so the game master cannot select a mode and no game can ever start

**Fix:** Change all phase string literals in `app.js` from uppercase to lowercase to match what the server sends.

### Bidding bugs and UX issues discovered during first live dealing session

Four issues found after the phase-string fix allowed dealing to work for the first time.

**Issue 1 — Suit symbols too small; same-colour suits adjacent**

Suit symbols (♠♥♦♣) in the hand were 13 px — hard to distinguish quickly.
Also, the hand sort order was `[♠♥♦♣]`, placing hearts and diamonds (both red) adjacent,
and spades and clubs (both black) adjacent — very easy to misread.

*Fix:* `card-suit` font-size raised to 18 px. Hand sort order changed to `[♠♥♣♦]`
(alternating black–red–black–red). Bid buttons updated to the same order.

**Issue 2 — Single bid could overtake another single (wrong rule)**

A player holding a single trump-rank card of suit A could overtake a single bid of suit B
from a different player. The correct rule is: a single bid can only be beaten by a pair
or better — the bidder has the best single until someone shows two cards.

*Fix:* Removed the same-strength-single-overtake exception from `_can_overtake()` in the
engine. Also updated `place_bid` in the handler to auto-add the bidder to
`passed_in_bidding` so the 3 non-bidders' passes still trigger auto-close.

**Issue 3 — Pass button not disabled after a player bids**

A player who had placed a bid could still press "Pass", which made no logical sense
(a bid is a commitment, not a suggestion).

*Fix:* Pass button is now disabled when `gs.bids` contains the current player's ID.

**Issue 4 — No visual confirmation that Pass was pressed**

After clicking "Pass", the button looked identical. With 100 cards being slowly dealt,
it was impossible to tell if the press registered.

*Fix:* Added `S.hasPassed` tracking in frontend state. On press, the button immediately
changes to `"Passed ✓"` with a green border/text style, stays that way until the next bid
resets it (server clears pass tracking on each bid, so everyone must pass again).

**Issue 5 — Trump-rank cards not visually distinguished during bidding; suit order updated**

The hand during dealing showed all cards in a flat row with no indication of which cards
were relevant for bidding. Players had to mentally scan for their trump-rank cards.
Additionally, the suit display order was revised a second time to match the user's
preferred fixed ordering (♦ ♣ ♥ ♠), and all trump-rank cards are now grouped together
in a single block after bidding ends.

*Bidding/dealing phase (DEALING + BIDDING_AFTER_DEAL):*
- Hand is split into two sections separated by a gold dashed line:
  - **Main group** (left): non-trump-rank, non-joker cards, sorted ♦ ♣ ♥ ♠ by rank
  - **Highlighted group** (right, below separator): trump-rank cards of any suit + jokers,
    sorted ♦ ♣ ♥ ♠ then small joker then big joker; rendered with gold border + warm tint
- The trump rank label is shown in the separator text so the number is unmistakable
- If a player has no trump-rank cards or jokers, the separator and highlighted group
  are omitted entirely

*After bidding (BOTTOM_EXCHANGE and beyond):*
- Highlighted section merges back into a single sorted hand automatically
- All trump-rank cards (any suit) are grouped together in one contiguous block,
  sub-sorted off-suit first (♦ ♣ ♥ ♠ order), on-suit trump rank last
- Trump-suit non-rank cards appear immediately left of the trump-rank block
- Jokers are rightmost

*Suit display order:* ♦ ♣ ♥ ♠ everywhere (alternating red/black). Bid buttons match.

### Follow-play validation rejects valid cards (two bugs found during play-testing)

**Bug 1 — Any suited single must be allowed to follow a single lead**

Observed: Player A leads A♥ (non-trump suit, clubs is trump). Player B tries to play 4♥ — the engine rejects it as illegal, even though 4♥ is a valid heart.

Root cause: `get_legal_plays` for a single lead returns `[suited[0]]` — only the first card in the suited list. The engine then checks `_cards_match_any(proposed, legal)`, which rejects any card other than that specific arbitrary first card.

**Bug 2 — Any 2 suited singles must be allowed to follow a pair lead when no pair is available**

Observed: Player A leads A♥A♥ (pair). Player B has no hearts pair. Playing 4♥+5♥ is rejected, but 10♥+J♥ is accepted — even though both are equally valid (no pair available, any two hearts suffice).

Root cause: `_match_group` for a degraded pair (no group of size k) iterates `sorted(groups.values(), ...)` and returns exactly one arbitrary combination of 2 suited cards. Any other combination fails `_cards_match_any`.

*Fix:* Added `is_valid_follow(proposed, hand, led_format, led_suit, ctx)` to `tricks.py`. Instead of comparing against one arbitrary option, it checks invariants directly:
- Must play as many suited cards as possible
- For Single: any one suited card is valid
- For IdenticalGroup(k): if hand has a group of k, proposed must include one; otherwise any k suited singles are valid
- For Tractor/Throw: falls back to `get_legal_plays` comparison (complex ordering rules still apply)

Both `engine.py` (play_cards) and `handler.py` (validate_play) now call `is_valid_follow` instead of the old `get_legal_plays + _cards_match_any` pattern.

---

## Q&A

Questions, observations, and answers collected during manual testing.

---

## 5. Capacity, scaling, and fault tolerance

### How many rooms can the server support right now?

There is no hardcoded room limit. In practice, the ceiling is set by three resources
on whatever machine uvicorn is running on:

| Resource | What it limits | Rough rule of thumb |
|---|---|---|
| **RAM** | Number of rooms in memory | Each room holds 4 player hands (~108 cards) + game state. A room is well under 1 MB of Python objects. A $6/mo VPS with 1 GB RAM could hold thousands of simultaneous rooms before RAM is the bottleneck. |
| **Open file descriptors** | Number of WebSocket connections | Each WebSocket is an open OS file descriptor. Default Linux limits are ~1,024 per process (tunable to 65,536+). At 4 connections per room that's ~16,000 rooms on a tuned system. |
| **asyncio event loop** | Message throughput | We use a single-process asyncio event loop. It can handle many concurrent WebSocket connections as long as no single handler blocks it. Our game logic is fast CPU-wise, so this is not a bottleneck in practice. |

**Short answer:** For a casual card game among friends, a single cheap VPS handles
hundreds to thousands of simultaneous rooms easily. You are unlikely to hit any limit.

### How do I scale out if I need more capacity?

This is where the current architecture has a known constraint: **all game state lives
in the `RoomManager` dict in one Python process**. You cannot simply spin up a second
server and load-balance across both, because a room on server A is invisible to server B.

The standard solution is to move shared state out of the process:

```
Before (current):
  Server A: RoomManager (in-memory dict)

After (scaled):
  Server A ──┐
  Server B ──┼──► Redis (shared room state + pub/sub for WebSocket messages)
  Server C ──┘
```

**Step-by-step path to horizontal scaling:**
1. Replace the in-memory `RoomManager` dict with **Redis** (a fast in-memory database
   that all server instances can share)
2. Use Redis pub/sub to forward WebSocket messages between servers (so a message from
   a player on Server A reaches players on Server B)
3. Put a load balancer (nginx, Caddy, or a cloud LB) in front with **sticky sessions**
   disabled — any server can handle any request once Redis holds the state

This is well-understood but non-trivial work. For a game played among friends it is
almost certainly unnecessary — start with one server and only add this complexity if
you actually hit capacity limits.

### What is fault tolerance like?

**Currently: none.** This is an intentional tradeoff documented in the implementation
plan's "Future Todos." Specifically:

- **Server restart = all rooms lost.** Game state is only in RAM. If uvicorn crashes or
  the machine reboots, every active game disappears. Players would see a "Disconnected"
  overlay and have to start over.
- **Player disconnect = room destroyed.** If any one of the 4 players loses their
  connection (closes the tab, WiFi drops), the server immediately sends `game_aborted`
  to the other 3 and tears down the room. There is no reconnect grace period.
- **No persistence.** There is no database. Completed game history is not stored
  anywhere (the `.jsonl` logging described in M9 would give you a file-based audit
  trail, but not full game restoration).

**How you would improve this (in order of effort):**

1. **Reconnect grace period** (medium effort) — instead of immediately aborting on
   disconnect, pause the game for 60 seconds and let the player rejoin with the same
   `player_id`. The game log snapshots are already designed to support this.

2. **Persist game state to Redis or SQLite** (medium effort) — serialize `GameState`
   to JSON after every action and write it to a store. On server restart, reload active
   rooms from the store. This makes the server restart-safe.

3. **Multi-server redundancy** (high effort) — run 2+ server instances behind a load
   balancer. If one crashes, the load balancer routes new connections to the others.
   Existing connections on the crashed server are still lost (WebSockets are stateful),
   but the system recovers quickly and rooms persisted in Redis survive.

**Bottom line:** For playing with friends, the current setup is perfectly fine. The
worst case is a dropped connection forces everyone to start a new game — annoying but
not catastrophic.

---

## 4. Why localhost:8000 works now, and what it takes to go live

### Why it works on your machine right now

When you run `uvicorn shengji.network.app:app --reload`, uvicorn starts an HTTP server
**on your own computer**. `localhost` is just a name that means "this machine", and
`8000` is the port it listens on. So `http://localhost:8000` is purely local — only
your machine can reach it. No one on the internet can visit it.

The request flow right now:
```
Your browser  →  localhost:8000  →  uvicorn  →  FastAPI  →  your Python code
```
Everything happens on one machine. There is no network involved.

### What "going live" actually means

To make `https://jeff_eighty_points.com` work, you need three things:

**1. A server on the internet (a VPS or cloud instance)**
Instead of running uvicorn on your laptop, you run it on a machine with a public IP
address that anyone on the internet can reach. Common cheap options:
- **DigitalOcean Droplet** (~$6/month, simplest to get started)
- **AWS EC2 / Google Cloud / Azure** (more powerful, more complex)
- **Railway / Render / Fly.io** (platform-as-a-service — they manage the machine for
  you, you just deploy the code; easiest option for a small project like this)

**2. A domain name**
You buy a domain (e.g. `jeff-eighty-points.com`) from a registrar like Namecheap or
Cloudflare (~$10–15/year). Then you create a **DNS record** that points your domain
to the public IP address of your server. DNS is just a global lookup table:
"when someone asks for jeff-eighty-points.com, send them to IP 1.2.3.4".

**3. HTTPS / TLS certificate**
Browsers require HTTPS for WebSockets (`wss://`) to work on a real domain (our
`app.js` already switches between `ws://` and `wss://` automatically based on the
page protocol). You get a free TLS certificate from **Let's Encrypt**, typically
automated via a tool called **Certbot** or handled automatically by platforms like
Render/Railway.

You also put a **reverse proxy** (nginx or Caddy) in front of uvicorn. The proxy
handles HTTPS termination and forwards plain HTTP to uvicorn internally:

```
User's browser
      │  HTTPS (port 443)
      ▼
  nginx / Caddy          ← handles TLS cert, domain routing
      │  HTTP (port 8000, internal only)
      ▼
  uvicorn / FastAPI      ← your Python code, unchanged
```

### Simplest path to go live (recommended for a side project)

1. Push the code to GitHub (already done)
2. Sign up for **Render** (render.com) — free tier available
3. Create a new "Web Service", point it at the GitHub repo
4. Set the start command to: `uvicorn shengji.network.app:app --host 0.0.0.0 --port $PORT`
5. Render gives you a free `*.onrender.com` URL automatically with HTTPS
6. (Optional) Buy a domain and point it at Render via their custom domain settings

The code itself needs **zero changes** to go from localhost to production — FastAPI and
uvicorn are production-ready as-is for a small multiplayer game. The only caveat is
that our game state is in-memory, so a server restart clears all active rooms (noted
in the implementation plan's "Future Todos").

---

## 1. Favicon 404 error in server logs

**Observation:** When opening `http://localhost:8000` in the browser, the server logs show:
```
127.0.0.1:57854 - "GET /favicon.ico HTTP/1.1" 404 Not Found
```

**What it is:** Every browser automatically requests `/favicon.ico` — the tiny icon shown
in the browser tab. This is the browser doing it on its own, not anything in our code.
Since we don't have a favicon file, FastAPI returns a 404. This is harmless and does not
affect game functionality at all.

**How to fix (when we care):** Two options:
- **Quick:** Add a `<link rel="icon" href="data:,">` line inside the `<head>` of
  `frontend/index.html`. This tells the browser "no icon" and suppresses the request.
- **Proper:** Create a `frontend/favicon.ico` file (any 16×16 or 32×32 `.ico` image)
  and add `<link rel="icon" href="/favicon.ico">` to the `<head>`. The FastAPI static
  file server already serves everything in `frontend/`, so no backend change needed.

---

## 2. How does the JS frontend connect to the game engine?

High-level overview for someone new to frontend ↔ backend communication:

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
        │  ◄─── server pushes JSON messages whenever game state changes
        │  ───► browser sends JSON messages when player takes an action
        ▼
handler.py  →  GameEngine  →  GameState
```

**Step by step:**

1. **User clicks "Create Room"** — `app.js` makes a regular HTTP POST to `/rooms`.
   The server creates a room in memory and returns a `room_id` (e.g. `"ABC123"`) and
   a `player_id` (a random string identifying this player).

2. **`app.js` opens a WebSocket** to `/ws/ABC123/<player_id>`. Unlike HTTP (which is
   one request → one response), a WebSocket is a persistent two-way channel that stays
   open for the entire game.

3. **Server pushes state to the client.** Whenever anything changes (a card is dealt,
   someone bids, a trick is played), `handler.py` calls `broadcast_game_states()`,
   which sends each player a personalized JSON snapshot of the game (`game_state`
   message). The browser receives this and `app.js` re-renders the whole UI from scratch.

4. **Client sends actions to the server.** When a player clicks "Play" or a bid button,
   `app.js` sends a small JSON message like `{"action": "play_cards", "cards": [...]}`.
   `handler.py` receives it, calls the appropriate `GameEngine` method (e.g.
   `engine.play_cards()`), which mutates the `GameState` object. Then a new
   `game_state` broadcast goes out to all players.

**The key insight:** The browser never computes game logic. It only renders what the
server tells it, and sends player intentions (actions) back. All rules, validation, and
state live in the Python `GameEngine` on the server.

---

## 3. Edge case: joining a lobby that does not exist

**Question:** What happens if a player enters a bogus room code on the landing page?

**Answer: Yes, this is already handled and tested.**

- The REST endpoint `POST /rooms/{room_id}/join` returns **HTTP 400** with
  `{"detail": "Room ... not found"}` if the room code doesn't exist.
- `app.js` catches this error and displays it on the landing page (the red error text
  below the join form) — the player stays on the landing page and can try again.
- The test lives in `tests/test_network/test_app.py`:
  ```python
  def test_join_unknown_room_returns_400(self):
      resp = client.post("/rooms/ZZZZZZ/join", json={"name": "Bob"})
      assert resp.status_code == 400
  ```

**Other join-related edge cases that are also tested:**
- Joining a full room (4 players already) → 400 "full"
- Joining a game already in progress → 400
- Two players get different player IDs → verified
