# Superuser mode — is it necessary?

**Date:** 2026-07-29 · **Status:** report only, no code changed, nothing committed.

**The question (Jeffrey).** *"Investigate if superuser mode is necessary. Maybe it could help to
artificially set people's levels (e.g. we continue from a previous session). But in terms of
rewinding rounds, I'm not sure how difficult it would be to implement. You should consider."*

**Method.** Read every file in `src/shengji/superuser/`, its mount in `network/app.py`, its
consumers across `src/` and `tests/`, the lobby UI in `frontend/`, and the engine paths the two
proposed features would touch (`engine/engine.py`, `modes/*.py`, `network/handler.py`). Effort
estimates are new-or-touched line counts by file, derived from reading the actual insertion
points, not from analogy.

**Headline.** Superuser mode is not currently load-bearing — the useful half of it
(`inspector.validate_state`) is already used directly by production code and the fuzz suite and
would survive the module's deletion; the mutating half has zero non-test callers and zero UI. And
neither of Jeffrey's two wishes is something superuser mode can serve today: setting levels is not
in the mutator at all, and rewinding needs infrastructure superuser mode does not have. Details in
§4.

---

## 1. What superuser mode is today

### 1.1 Capability catalogue

Three modules, 424 lines total, plus 74 tests.

**`superuser/inspector.py` (143 lines) — read-only, and genuinely used.**

| Function | What it does |
|---|---|
| `get_full_state(state)` | Returns `state.to_superuser_view()` — every hand, the bottom deck, draw-pile size, and all captured tricks, unredacted. |
| `validate_state(state)` | Returns a list of violation strings. Six checks: 108-card total (skipped in `WAITING`); no card identity appearing more than 2 times across every zone (R1); `trump_context` present in the phases that require it; no hand over `HAND_SIZE`; `round_leader_id` / `current_turn_id` name real players; `attacking_points >= 0`. |

**`superuser/mutator.py` (139 lines) — five writes, each returning `validate_state` output as
non-fatal warnings.**

| Function | Effect |
|---|---|
| `set_hand(state, player_id, cards)` | Replaces one hand wholesale. |
| `set_bottom(state, cards)` | Replaces the bottom deck. *(Not exposed over HTTP.)* |
| `set_points(state, attacking_points)` | Overwrites the live attacking-points total. |
| `force_phase(state, phase)` | Assigns `state.phase` directly, bypassing `transition_to()` and therefore the entire `_VALID_TRANSITIONS` graph. |
| `deal_specific_hands(state, hands, bottom)` | Sets all four hands and the bottom at once, empties the draw pile, resets `tricks_won` and `current_trick`. |

**`superuser/api.py` (252 lines) — six HTTP endpoints under `/superuser`.**

`POST /enable/{room_id}` · `GET /state/{room_id}` · `POST /validate/{room_id}` ·
`POST /set-hand/{room_id}` · `POST /set-points/{room_id}` · `POST /force-phase/{room_id}` ·
`POST /deal-specific/{room_id}`.

### 1.2 Auth model

Three-part, and thin. Every endpoint takes an `X-Player-Id` header; `_require_access`
(`api.py:100`) checks it equals `room.game_master_id` and — for everything except `/enable` —
that `room.superuser_enabled` is `True`. The flag defaults to `False` (`room.py:71`) and is
flipped by the game master calling `/enable`.

The header is **self-asserted**. Player IDs are 12 random lowercase-alphanumeric characters
(`room.py:161`), so they are not guessable, but anyone who learns the game master's ID — it is
sent to every client in the `room_update` broadcast (`handler.py:143`) — can call every superuser
endpoint on that room. **Every player in the room already knows the game master's player ID.**
There is no secret. The only thing standing between a curious player and every other player's hand
is that they have to open a terminal, and that the game master has clicked "Enable".

### 1.3 Wiring into the live server

`app.py:87-121` defines `_SuperuserRoomAdapter`, a `dict` subclass that proxies lookups to the
authoritative `RoomManager`, and `_LiveSuperuserRoom`, a per-room property proxy so
`room.superuser_enabled = True` writes through to the real `Room` instead of a discarded copy.
That is ~70 lines of adapter existing solely to reconcile M6's standalone room store with M7's
real one — pure integration debt with no game value.

### 1.4 Frontend

`index.html:781-788` renders a game-master-only "Enable Superuser Mode?" button in the lobby with
an "Are you sure?" confirm. `app.js:1497` posts to `/superuser/enable/{roomId}` and relabels the
button "Superuser Mode: ON".

**And that is the entire frontend.** No UI calls `/state`, `/validate`, `/set-hand`,
`/set-points`, `/force-phase`, or `/deal-specific`. Clicking the button changes a boolean and
nothing else. Every mutation is reachable only by hand-rolled `curl`.

### 1.5 Who actually calls this code

| Consumer | What it uses | Path |
|---|---|---|
| `network/handler.py:685` | `validate_state` — post-action invariant sweep, violations logged, never raised | in-process |
| `tests/test_fuzz/fuzz_helpers.py:43` | `validate_state` as a second opinion alongside the suite's own invariants | in-process |
| `scripts/play_cli.py` | `validate_state` per-action sweep in the bot fuzzer | in-process |
| `tests/test_integration/helpers.py:72` | `mutator.deal_specific_hands` for deterministic layouts | **in-process — not HTTP** |
| `tests/test_engine/test_tricks.py:955` | comments note the mutator as the only way to reach a state | in-process |
| `tests/test_network/test_app.py:135-165` | exercises `/superuser/enable` and `/superuser/state` | HTTP |
| `frontend/app.js:1500` | `/superuser/enable` only | HTTP |

The load-bearing consumer is `validate_state`, and it is load-bearing in *production*
(`handler.py`), not in debugging. The mutator's one real user imports the Python function
directly. **The HTTP mutation surface has no callers at all outside its own test file.**

### 1.6 Known rough edges

1. **Mutations can violate engine invariants by design.** Every mutator returns warnings rather
   than refusing. `set_hand` will happily give a player three copies of 5♥ — `validate_state`
   flags it (R1, `inspector.py:95-101`) and the write lands anyway. That is the documented
   contract ("the superuser may intentionally create edge cases"), and it is correct for a test
   fixture. It is wrong for a button in a live 4-player game: the state the other three players
   are looking at silently becomes illegal, and `handler.py:685` will then log an invariant
   violation on every subsequent action for the rest of the round.
2. **`force_phase` bypasses `transition_to`.** It can jump `WAITING → SCORING` and skip every
   setup step in between. Engine methods that assume phase preconditions (`end_round` requires
   `SCORING` and a non-`None` `trump_context`, `engine.py:776-782`) will then raise into the
   handler.
3. **No broadcast.** A mutation writes to `GameState` but sends nothing over the WebSocket.
   Clients keep rendering the pre-mutation view until some unrelated action triggers
   `broadcast_game_states`. In a live game that is a guaranteed desync window.
4. **Information asymmetry is permanent.** `/state` reveals all four hands. There is no
   round-scoped reset, no notification to the other players that it happened, and no audit entry
   in the game log. Enabling is announced only to the game master's own screen.
5. **The adapter layer (§1.3)** is maintenance surface that exists purely because M6 shipped its
   own room store before M7 existed.

---

## 2. Use case A — set players' levels to resume a previous session

### 2.1 Can the mutator do this today? No.

There is no `set_rank`. Levels live on `Player.rank` (`player.py:21`) and the only mutation path
is `Player.advance_rank(steps)` (`player.py:29`), called from exactly one place —
`engine.end_round():827`. Neither the mutator nor the HTTP API touches `Player.rank`, and
`to_superuser_view` exposes rank read-only. **Setting levels is not a superuser capability; it is
a feature that does not exist anywhere.**

### 2.2 Why this matters more than it looks

`handle_connection` tears the room down on the *first* disconnect: `WebSocketDisconnect` →
`abort_room` → `manager.remove_room` (`handler.py:695-697`). One player closing a laptop lid ends
the game for four people, and there is no way to get back. Today the only recovery is starting
over at level 2.

So this is not a convenience for artificially skipping ahead. **It is the only possible recovery
path from a dropped connection, and there currently isn't one.** That reframes the priority: this
is the single highest-value item in the whole report.

### 2.3 What "resume" actually requires

A resumable game state is fully described by three things:

1. **Each player's level** (`Player.rank`).
2. **Who leads the next round** (`state.round_leader_id`) — this is load-bearing beyond
   seating. R12/D01: the trump rank for a round *is* the round leader's level. It also determines
   the deal starting seat (`engine.py:218`) and, in Upgrade, which pair defends.
3. **`state.round_number`** — cosmetic, but players will notice "Round 1" on a resumed game.

Teams need no separate input, because both strategies derive them:

- **Upgrade** (`upgrade.py:29`): `assign_teams` sets `is_defending` by seat parity relative to the
  leader's index. Setting the leader fixes the teams.
- **Find Friends** (`find_friends.py:29`): the leader defends alone and friends are re-derived by
  declaration each round. Setting the leader is again sufficient.

**One genuine wrinkle, Upgrade only.** Partnerships are seat parity — seats 0/2 vs 1/3 — and
seating is join order (`room.py:137` appends). To resume an Upgrade game the four players must
rejoin in an order that reproduces the old partnerships, or the feature needs a seat-reorder
control. Two options: document "join in this order" (free, error-prone), or add drag/swap
reordering of `state.players` in the lobby (+~60 lines, and it is independently useful for
ordinary games where people want to pick partners). I'd ship the levels feature first and treat
reordering as a fast follow.

**Second wrinkle, Upgrade only.** In Upgrade, teammates advance together
(`engine.py:826` advances the whole winning set), so their levels are always equal. The UI should
therefore offer *two* level inputs in Upgrade mode and *four* in Find Friends, or validate that
Upgrade partners match. Four independent inputs with no validation invites resuming into a state
the engine can never produce.

### 2.4 Interaction with the Ace / game-over rule

R82/D19 (`engine.py:841-850`): game over fires when the winner is `defending` and any defender's
**pre-advance** rank was already Ace. Resuming a game with a player at Ace is therefore legitimate
and one successful defense from ending — which is exactly right, and exactly what a resumed
session should do. No special handling needed. The one thing to guard is the *combination*: if
you set someone to Ace **and** make them the round leader, the very next round can end the game
immediately. That is correct behavior, but a one-line UI hint ("A defending Ace can end the game
this round") prevents a confused bug report.

### 2.5 Design A1 — first-class lobby setup *(recommended)*

Game-master-only panel in the existing lobby, next to the mode selector. No superuser involvement.

**Backend.** One new WS action in `handle_message`:

```
action: "set_starting_levels"
  { levels: {player_id: rank}, leader_id: str, round_number: int }
```

Validation: sender is game master; `phase == WAITING`; every key is a known player; every value is
in `RANK_ORDER`; `leader_id` is a known player; in Upgrade, seat-parity partners have equal levels.
Then assign `Player.rank`, `state.round_leader_id`, `state.round_number`, and broadcast.
`broadcast_room_update` (`handler.py:138`) currently sends only `{id, name}` per player — it needs
`rank` and the leader id so the lobby can render what is configured. `GameLogger` should get a
`log_starting_levels` entry so a resumed game's log records that it was resumed.

**Frontend.** The pieces already exist: `RANK_ORDER` and `rankDisplay()` are defined in `app.js`
(`:31`, and used at `:1384`), so the per-player rank `<select>` is nearly free. The lobby panel is
GM-only and `WAITING`-only, mirroring `mode-selector` (`app.js:643`). Unknown WS message types are
silently ignored by the dispatch (`app.js:190-204`, no `default` case), so nothing breaks for a
stale client.

**Estimate.**

| File | Lines |
|---|---|
| `src/shengji/network/handler.py` — action branch + validation, extend `broadcast_room_update` | +65 |
| `src/shengji/engine/logger.py` — one log method | +10 |
| `frontend/index.html` — panel markup + CSS | +30 |
| `frontend/app.js` — render selects, send action, reflect broadcast | +70 |
| `tests/test_network/` — ~9 tests (happy path, non-GM rejected, post-`WAITING` rejected, bad rank, unknown player, Upgrade parity, leader sets trump rank, round_number, log entry) | +140 |
| **Total** | **~315 lines, 5 files** |

**Roughly half a session.** No engine changes. The optional seat-reordering follow-up adds ~60
lines in `app.js` + `handler.py`.

### 2.6 Design A2 — superuser `set-rank` endpoint *(not recommended)*

`mutator.set_rank(state, player_id, rank)` (+25 lines) and `POST /superuser/set-rank/{room_id}`
(+30) and tests (+50). **~105 lines** — genuinely cheaper.

But it is worse on every axis that matters. Jeffrey and three friends would have to `curl` four
times before every resumed game; the mutation does not broadcast, so all four clients render stale
levels until something else triggers a state push (§1.6.3); enabling superuser to use it hands the
game master permanent visibility into every hand for the rest of the session; and it cannot enforce
the Upgrade parity rule without duplicating team logic that the handler already has in scope.

A2 is the right shape for a *test fixture*. A1 is the right shape for a *feature people use*. The
210-line difference buys a thing friends can actually operate.

---

## 3. Use case B — rewinding rounds

### 3.1 Design (a) — snapshot at round start, rewind to round N

**Feasibility: good.** The prerequisites are already in place.

- `GameState` is a plain mutable dataclass of plain fields (`game_state.py:55`) — `deepcopy`
  handles it whole.
- The rules audit (`docs/reports/2026-07-29-rules-audit.md` §7) verified deepcopy snapshot/restore
  round-trips engine state, and `tests/test_fuzz/` already deepcopies whole `GameEngine` objects
  across ~8 harvest points per seed (`fuzz_helpers.py:548`) — this is exercised code, not theory.
- **F6 is fixed**, and it was the blocker. `FindFriendsStrategy` now holds no instance state; the
  reveal counters live on `GameState.friend_play_counts` (`game_state.py:113`, cleared in
  `assign_teams`, `find_friends.py:38`). Both strategy objects are therefore pure behavior, so a
  `GameState` snapshot is *complete* — the strategy needs no restore at all.
- Round-start state is already captured on disk: `log_round_start` writes every hand and the
  bottom deck to `logs/games/*.jsonl` (`logger.py:64-73`). That is a useful cross-check, but I'd
  snapshot in memory rather than rehydrate from JSONL — the log records `round_leader_id`,
  `players`, and `bottom_deck` but not `throw_penalties`, `friend_play_counts`, or
  `last_winning_play`, so it is a lossy restore source.

**Where to snapshot.** In `start_and_deal` (`handler.py:164`), immediately after
`deal_all_cards` returns and next to the existing `log_round_start` call at `:196-197`. At that
point the deal is complete, the phase is `BIDDING_AFTER_DEAL`, and the round is at its natural
resume point. Append `(round_number, deepcopy(room.game_state))` to a new
`Room.round_snapshots: list` field.

**The two real hazards, and how to handle them.**

*Hazard 1 — reference rewiring.* `room.engine.state` and `room.game_state` are two names for one
object. Replacing `room.game_state` alone leaves the engine driving the old one. The clean fix is
to **restore in place** rather than rebind:

```python
snap = copy.deepcopy(snapshot)
for f in dataclasses.fields(GameState):
    setattr(room.game_state, f.name, getattr(snap, f.name))
```

~10 lines, and every existing reference — `room.engine.state`, `room.game_state`, and any local
captured by a running coroutine — sees the restored data with no rebinding at all. This is
strictly better than constructing a fresh `GameEngine`.

*Hazard 2 — in-flight coroutines, and this is the one that will bite.* Two background tasks can be
mid-flight when a rewind lands:

- The **trick hold**: `handler.py:505` does `await asyncio.sleep(3 or 5)` and then, after waking,
  writes `state.current_trick = []` and may call `handle_round_end` → `engine.end_round()`. A
  rewind during that sleep resumes into a state that no longer matches, clears a trick that
  belongs to a different round, and can score a round that has been rewound out of existence.
- The **deal loop**: `deal_all_cards` sleeps `deal_delay` between cards (`engine.py:898`) and
  appends to hands as it goes. A rewind mid-deal races it directly.

Restoring in place does **not** fix this — the stale coroutine holds a reference to the same
object it always did and will keep writing to it. The fix is a generation counter: a
`Room.generation: int` incremented on every rewind; each background task captures the value it
started with and returns early if it no longer matches. That is ~6 lines total (one field, one
increment, two guards) but it must not be forgotten, and it is the thing to write a test for
first. Simplest policy: **reject a rewind while a deal or trick hold is in flight** (a `Room.busy`
flag) rather than trying to interrupt one — one line of validation instead of a concurrency
argument, at the cost of the game master occasionally having to click twice.

**Client invalidation.** Broadcast a new `round_rewound` message, then `broadcast_game_states`.
The client keeps derived state that a rewind makes wrong: `selectedKeys`, `pendingPlayCards`,
`awaitingValidation`, `hasPassed`, `lastBidsCount`, `knownFriends`, `lastRoundNumber` (all in the
`S` object, `app.js`). The handler resets those, closes any open confirm dialog or overlay, and
shows a banner. The existing `handleRedeal` is the right template — same shape of "throw away
what you were doing, here's fresh state".

**Logging.** Append a `round_rewound` event. Do not rewrite history: the log is append-only and
flushed per line (`logger.py:46-52`), and a rewind that silently erased its own trace would be the
worst possible property for a debugging artifact.

**Memory.** A 13-round game holds 13 deepcopies of ~108 `Card` objects plus scalars. Hundreds of
kilobytes. Not a consideration.

**Estimate.**

| File | Lines |
|---|---|
| `src/shengji/network/room.py` — `round_snapshots`, `generation`, `busy` fields | +8 |
| `src/shengji/network/handler.py` — snapshot capture, `rewind_to_round` action, in-place restore, generation guards, broadcast | +90 |
| `src/shengji/engine/logger.py` — `log_round_rewound` | +10 |
| `frontend/index.html` + `app.js` — GM control with confirm, `round_rewound` handler, client-state reset, banner | +100 |
| `tests/` — ~11 tests (snapshot fidelity round-trip, rewind restores hands/ranks/points/friends, GM-only, unknown round rejected, rewind-during-hold is safe, log entry, post-rewind play still legal) | +180 |
| **Total** | **~390 lines, 5 files** |

**One focused session.** No engine changes; everything lives in the network layer.

### 3.2 Design (b) — action-level undo

Two sub-designs, both materially worse.

**(b1) Action log + replay from the round-start snapshot.** Record every mutating action on the
`Room` since the last snapshot; to undo, deepcopy the snapshot and replay all but the last action.

Determinism is fine *within* a round: I checked, and no engine path after the deal consumes
randomness — `random` appears only in `Deck.shuffle` (`deck.py:39`) and the `rng` plumbing on
`GameEngine.__init__` (`engine.py:80`). `place_bid`, `exchange_bottom`, `close_bidding`,
`play_cards`, and `end_round` are all deterministic given state and arguments. Replay across a
re-deal boundary is *not* deterministic (`close_bidding` on all-pass calls `start_dealing`, which
shuffles a fresh deck with `self.rng`, `None` in production), but since snapshots are taken
post-deal, replay never has to cross that boundary.

The cost is not determinism. It is that **replay must not broadcast and must not sleep**, and
today the only implementation of action-dispatch is `handle_message` — 320 lines that interleave
engine calls with `broadcast_game_states`, `send_error`, `asyncio.sleep`, logger writes, and
`asyncio.create_task`. Replay needs a pure "apply" path, which means either splitting
`handle_message` into apply/notify halves (a real refactor of the largest function in the network
layer) or writing a second dispatcher that will drift out of sync with the first.

It also has to reproduce state that lives *outside* `GameState`: `room.passed_in_bidding` and
`room.players_who_passed` implement R17 in the handler, and D26's bid-`count` handling is handler
logic too. Both must be part of the replayed action semantics.

And it is a permanent tax. Every future handler change would have to preserve replayability, with
no test that naturally catches a violation unless you build one (a fuzz property asserting
`replay(log) == live` over the existing driver — worth building if you go this route, ~60 lines on
top of `fuzz_helpers.py`).

**Estimate: ~450 lines touched in `handler.py` for the apply/notify split, ~180 new lines of
replay driver and log plumbing, ~200 lines of tests including the replay-equivalence property —
2 to 3 focused sessions**, plus ongoing maintenance drag on every subsequent handler change.

**(b2) Inverse actions.** Recommend against, categorically. `play_cards` alone mutates `hand`,
`current_trick`, `led_format`, `led_suit`, `tricks_won`, `current_leader_id`, `current_turn_id`,
`trick_number`, `attacking_points`, `last_winning_play`, `throw_penalties`, `revealed_friends`,
and `friend_play_counts`, and can cascade into trick resolution and round end. Writing its inverse
is writing a second engine, with no oracle to check it against — the existing legality oracle
validates *forward* rules, and there is nothing analogous for undo. It would silently rot on every
engine change. The mutate-in-place structure makes this the worst option available, and the audit
already declined to refactor away from mutate-in-place for good reasons (§7).

### 3.3 The multiplayer objection that applies to both

Rewinding un-shows information four humans have already seen. Nobody can unsee the trick they just
watched, so any rewind is a social act, not just a state operation.

This is survivable at round granularity — "we're replaying this round" is a coherent thing to say
at a table, and everyone has seen roughly the same cards anyway. It is *not* coherent at play
granularity: undoing one card mid-trick means three players have information the fifth play was
supposed to depend on, and the person undoing gains a free look at how the table reacted. Design
(a) is defensible around a real table. Design (b) mostly is not.

That is an argument on top of the 4-to-6× cost difference, and it points the same direction.

---

## 4. Is superuser mode necessary?

Assembling the evidence:

**Value delivered today: near zero.** No UI beyond a boolean toggle (§1.4). Zero non-test callers
of the mutation API (§1.5). The one mutator function anything uses (`deal_specific_hands`) is
imported as a Python function by `tests/test_integration/helpers.py` and would keep working if the
entire HTTP layer were deleted tonight.

**The genuinely valuable piece is not superuser-gated.** `validate_state` runs in production on
every action (`handler.py:685`), in the fuzz suite, and in the CLI bot fuzzer. It is not a
superuser feature; it is a core invariant checker that happens to live in a directory called
`superuser/`.

**Risk surface is real and mispriced.** Once enabled, the game master can read all four hands at
will, with no notification, no round-scoped expiry, and no log entry. For a friends game the trust
model is "we trust Jeffrey", which is fine — but the button offers nothing in return for that
trust, because there is no UI to do anything with the access. It is pure downside as shipped. The
mutations are worse: they can produce states the engine cannot reach, and they don't broadcast, so
using one mid-game desyncs all four clients until the next unrelated state push (§1.6).

**Maintenance cost is quiet but ongoing.** ~70 lines of adapter in `app.py` reconciling M6's
standalone room store with M7's real one, 74 tests, and a mutation surface whose contract
("violations are non-fatal") conflicts with the invariant sweep that production now runs on every
action.

**Neither of Jeffrey's two wishes is served by it.** Setting levels is not in the mutator at all
(§2.1). Rewinding needs snapshot infrastructure superuser mode does not have, and the natural
design (a) is a network-layer feature that never touches `superuser/` (§3.1).

### Recommendation

**Replace it with first-class features.** Ship levels-at-lobby (A1, ~315 lines) and
round-start-snapshot rewind (B-a, ~390 lines) as ordinary game-master controls; keep
`superuser/inspector.py` exactly as it is, renamed out of the `superuser` package to reflect what
it actually is (a core invariant checker used in production); keep `superuser/mutator.py` as an
in-process test fixture, since `tests/test_integration/helpers.py` legitimately depends on
`deal_specific_hands` for deterministic layouts; and delete the HTTP layer — `superuser/api.py`,
the `_SuperuserRoomAdapter` and `_LiveSuperuserRoom` proxies in `app.py`, the
`Room.superuser_enabled` flag, and the lobby toggle in `frontend/`. That removes the only
mechanism by which the game master can read other players' hands, removes ~70 lines of pure
integration debt, removes a mutation path that can desync four clients and produce states the
engine cannot reach — and costs nothing real, because nothing calls it. The order matters:
levels-at-lobby first, because it is the higher-value feature by a wide margin. A dropped
connection currently destroys the room outright (`handler.py:695`), which means today there is no
way to resume an interrupted game at all; rewind is a nice-to-have, but resume is the only
recovery path that exists for the failure mode Jeffrey's friends will actually hit.

**Effort: ~315 lines / 5 files (half a session) for levels-at-lobby; ~390 lines / 5 files (one
focused session) for round-snapshot rewind.** Action-level undo, for comparison, is ~830 lines
across a refactor of the largest function in the network layer, 2-3 sessions, plus permanent
maintenance drag — 4 to 6× the cost of round-level rewind for a feature that is socially
incoherent at a real table (§3.3). Not worth it.

### If you'd rather not delete anything yet

A smaller step that captures most of the safety win: keep the module, but drop the four mutation
endpoints and keep `/enable`, `/state`, `/validate` as a read-only debug view. That kills the
desync and illegal-state risks (§1.6.1-1.6.3) while preserving "let me look at what the server
thinks is going on", which is the one thing the HTTP layer might plausibly be wanted for during a
live playtest. It leaves the all-hands visibility question unresolved, which is a judgment call
only Jeffrey can make about his own table.

---

## 5. Open questions for Jeffrey

1. **Resume scope.** Levels + leader + round number is enough to resume *between* rounds. Is
   mid-round resume (restoring hands and a partial trick) ever wanted, or is "finish the round or
   lose it" acceptable? Mid-round resume is a much bigger feature — it needs persistence across
   process restarts, not just a lobby form.
2. **Upgrade seating.** Reproduce partnerships by asking people to rejoin in order, or build a
   seat-reorder control in the lobby? (§2.3)
3. **Rewind authority.** Game master alone, or all four players must confirm? The current
   `ready_for_next_round` mechanism (`handler.py:564`) is already a working "wait for all four"
   pattern to copy if you want consensus.
4. **All-hands visibility.** Is the game master seeing every hand something you want available at
   all, given there is no UI for it today and enabling it is invisible to the other three players?
