# Shengji — Progress Log

Newest entries at the top.

---

## Session 9 — M8 Frontend

**Status:** In progress. 499 tests passing (no new backend tests for M8).

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
