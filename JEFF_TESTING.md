# Jeff's Testing Notes

Questions, observations, and answers collected during manual testing.

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
