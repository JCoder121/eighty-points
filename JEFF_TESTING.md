# Jeff's Testing Notes

Questions, observations, and answers collected during manual testing.

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
