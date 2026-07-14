# Shengji (升级) — Python Implementation Plan

## Project Overview

Build a web-based multiplayer card game supporting two modes:

- **Upgrade (升级)**: Fixed teams, leader rotates among winning team.
- **Find Friends (找朋友)**: Fluid teams that change each round, leader rotates among previous round's winners.

Rules reference: <https://robertying.com/shengji/rules.html>

Tech stack: **Python backend** (FastAPI + WebSockets), **browser frontend** (lightweight HTML/JS), **pytest** for testing.

---

## Architecture Principles

> **Read this before writing any code.**

1. **Shared game engine.** Both Upgrade and Find Friends share ~90% of their logic (deck, trumps, tricks, scoring, rank advancement). You must implement a single `GameEngine` class that handles the shared game loop. Mode-specific behavior (team assignment, friend declaration) is injected via strategy objects or subclasses — never via `if mode == "find_friends"` scattered throughout the engine.

   **Game master must select a mode.** The game cannot start without the game master explicitly choosing either "Upgrade (升级)" or "Find Friends (找朋友)". The server must enforce this: `start_dealing()` raises an error if `game_state.mode` is not set. The 4th-player auto-start logic must check that a mode is selected before calling `start_dealing()` — if not, it prompts the game master to choose first.

2. **Robust unit tests.** Every module you create must have a corresponding test file. Write tests *as you implement*, not after. Tests are not optional — they are a deliverable equal in importance to the feature code. Aim for >90% line coverage on all game-logic modules.

3. **Superuser mode.** The game must support a superuser interface that can: inspect and modify any player's hand simultaneously, set point totals, inject cards into the bottom deck, validate board-state legality, and force-advance the game phase. This is a first-class feature, not a bolt-on — design your state model to support it from day one.

---

## Milestone 0 — Project Skeleton

**Goal:** Repository structure, dependency management, dev tooling.

### Steps

0.1. Create the directory layout:

```
shengji/
├── pyproject.toml
├── README.md
├── src/
│   └── shengji/
│       ├── __init__.py
│       ├── models/          # Data classes: Card, Deck, Player, GameState, etc.
│       ├── engine/          # Game loop, trick resolution, scoring
│       ├── modes/           # Upgrade-specific and FindFriends-specific logic
│       ├── network/         # FastAPI app, WebSocket handlers, room management
│       └── superuser/       # Superuser inspection & mutation API
├── tests/
│   ├── conftest.py
│   ├── test_models/
│   ├── test_engine/
│   ├── test_modes/
│   ├── test_network/
│   ├── test_superuser/
│   └── test_integration/
├── scripts/
│   └── replay_log.py        # Pretty-print a game log file for debugging
├── logs/
│   └── games/               # Auto-created at runtime; one .jsonl file per game session
└── frontend/
    ├── index.html
    └── app.js
```

0.2. Set up `pyproject.toml` with dependencies: `fastapi`, `uvicorn[standard]`, `websockets`, `pydantic`, `pytest`, `pytest-asyncio`, `httpx` (for async test client). Also add `ruff` as a dev dependency for linting.

0.3. **There is no Makefile and no build step.** Python does not compile. The three commands you need are:

- **Install dependencies:** `pip install -e ".[dev]"` (installs the package in editable mode plus dev dependencies defined in `pyproject.toml`)
- **Run tests:** `pytest` (run from the project root; pytest discovers all `tests/` files automatically)
- **Run the server:** `uvicorn shengji.network.app:app --reload` (the `--reload` flag auto-restarts on file changes during development)
- **Lint:** `ruff check src/ tests/`

Document these four commands in the `README.md`. There is no need for a `Makefile` or any build/compile tooling.

0.4. Confirm the skeleton runs: `uvicorn shengji.network.app:app --reload` serves a "hello world" and `pytest` discovers zero tests with no errors.

---

## Milestone 1 — Card & Deck Models

**Goal:** Represent cards, decks, and point values. This is the foundation everything else depends on.

### Steps

1.1. **`src/shengji/models/card.py`** — Define the `Card` dataclass.

- Fields: `suit` (enum: Spades, Hearts, Diamonds, Clubs, Joker), `rank` (enum: 2–A, SmallJoker, BigJoker).
- Property `point_value`: returns 5 for 5s, 10 for 10s and Kings, 0 otherwise.
- Cards must be hashable and comparable (you will need custom ordering later when trump context is known — for now just implement `__eq__` and `__hash__`).

1.2. **`src/shengji/models/deck.py`** — Define `Deck`.

- **This game always has exactly 4 players and always uses exactly 2 decks (108 cards total).** Do not build for variable player counts — hardcode these constants and document them clearly.
- Each deck = 52 suited cards + 1 SmallJoker + 1 BigJoker = 54 cards. Two decks = 108 cards.
- Method `shuffle()` → randomizes card order.
- Method `prepare_deal() -> tuple[list[Card], list[Card]]` → returns `(draw_pile, bottom_deck)`. The bottom deck is the last **8 cards** from the shuffled deck. The draw pile is the remaining **100 cards**, in the order they will be dealt (first card dealt = index 0). The actual dealing of cards to players happens in the engine one card at a time (see M4.1) — the Deck class only prepares the shuffled piles.
- Verify: total points across both decks = 200.

1.3. **Tests: `tests/test_models/test_card.py` and `test_deck.py`**

- Card point values are correct for every rank.
- Deck has correct total card count and point total.
- `prepare_deal` produces a draw pile of 100 cards and bottom of 8 cards, with no duplicates and no missing cards.
- Shuffled deck differs from unshuffled deck (statistical — just assert not equal).

---

## Milestone 2 — Trump System & Card Ordering

**Goal:** Given a trump rank and optional trump suit, produce a total ordering of all cards. This ordering is used everywhere: trick resolution, tractor detection, throw validation.

### Steps

2.1. **`src/shengji/models/trump.py`** — Define `TrumpContext`.

- Fields: `trump_rank: Rank`, `trump_suit: Optional[Suit]` (None = no-trump).
- Method `card_order(card: Card) -> tuple[int, int]` — returns a sortable key. The tuple's first element is the *tier* (non-trump suit < trump suit non-rank < trump rank off-suit < trump rank on-suit < small joker < big joker). The second element is the rank order *within* that tier.
- **Critical adjacency rule:** When a trump rank is set, that rank is removed from every suit's normal ordering and promoted to the trump tier. This leaves a gap, and the two ranks on either side of the gap become adjacent for purposes of tractor formation. This is **dynamic** — it depends entirely on whatever the current trump rank is, not on a hardcoded pair of values. For example: if trump rank is 4, the non-trump suit ordering becomes `...3, 5, 6...` (3 and 5 are now adjacent). If trump rank is 9, the ordering becomes `...8, 10, J...` (8 and 10 are now adjacent). If trump rank is 3, the ordering becomes `...2, 4, 5...` (2 and 4 are now adjacent). Do **not** hardcode "3 and 5" — implement this by computing the ordered rank list for each suit and removing the trump rank from it, then treating consecutive entries in that filtered list as adjacent.
- Method `effective_suit(card: Card) -> str` — returns the card's suit for trick-following purposes. Trump-rank cards and jokers return `"trump"`. In no-trump mode, trump-rank cards each retain their own suit (4 distinct suits and 4 total jokers).

2.2. **`src/shengji/models/groups.py`** — Trick-format detection utilities.

- `find_identical_groups(cards: list[Card], ctx: TrumpContext) -> list[list[Card]]` — groups by identical card (same suit+rank). Returns groups of size >= 2.
- `find_tractors(cards: list[Card], ctx: TrumpContext) -> list[list[Card]]` — finds consecutive identical-card sequences. A tractor requires multiplicity >= 2 (pairs, triples) and length >= 2 consecutive ranks. The smallest tractor is 4 cards (2 consecutive pairs). Must respect the trump-adjusted adjacency.
- `classify_play(cards: list[Card], ctx: TrumpContext) -> TrickFormat` — returns a structured description: `Single`, `IdenticalGroup(n)`, `Tractor(multiplicity, length)`, or `Throw(components: list[TrickFormat])`.

2.3. **Tests: `tests/test_models/test_trump.py` and `test_groups.py`**

- Ordering is correct for a concrete example: trump rank 2, trump suit Hearts. Verify Big Joker > Small Joker > 2♥ > 2♠ = 2♦ = 2♣ > A♥ > K♥ > ... > 3♥ > A♠ > K♠ > ...
- No-trump ordering: jokers > all trump-rank cards (equal) > suited cards in normal order.
- Adjacency is dynamic: test multiple trump ranks to confirm the correct pair of ranks collapse together each time.
  - Trump rank 4 → 3 and 5 become adjacent; verify `3♠3♠5♠5♠` is a valid tractor.
  - Trump rank 9 → 8 and 10 become adjacent; verify `8♠8♠10♠10♠` is a valid tractor.
  - Trump rank 3 → 2 and 4 become adjacent; verify `2♠2♠4♠4♠` is a valid tractor.
  - Trump rank 2 → A and 3 become adjacent (2 removed from bottom, A wraps); clarify and document the edge case for rank 2 (lowest) and rank A (highest) in the implementation.
- Classify_play correctly identifies singles, pairs, triples, tractors, and throws.

---

## Milestone 3 — Game State Model

**Goal:** A single `GameState` object that fully describes the game at any point in time. This is the source of truth that the engine mutates and the network layer serializes.

### Steps

3.1. **`src/shengji/models/player.py`** — Define `Player`.

- Fields: `id: str`, `name: str`, `hand: list[Card]`, `rank: Rank` (starts at 2), `is_defending: bool`, `team: Optional[str]`.

**Rank progression:** Define the rank sequence explicitly as an ordered list: `[2, 3, 4, 5, 6, 7, 8, 9, 10, J, Q, K, A]` — 13 ranks total. When a team advances by N ranks, move N positions forward in this list. A player **cannot advance past A**. If a +3 advancement would go past A, they simply land on A. The game ends when a player successfully defends (their team doesn't lose) while their rank is A.

3.2. **`src/shengji/models/game_state.py`** — Define `GameState`.

- Fields:
  - `players: list[Player]` (ordered by seating in counter-clockwise order; index 0 = game master)
  - `mode: Literal["upgrade", "find_friends"]`
  - `phase: GamePhase` (enum: `WAITING`, `DEALING`, `BIDDING_AFTER_DEAL`, `BOTTOM_EXCHANGE`, `FRIEND_DECLARATION`, `PLAYING`, `SCORING`, `ROUND_OVER`, `GAME_OVER`). Note: bidding happens *during* the `DEALING` phase (players can bid as cards arrive). `BIDDING_AFTER_DEAL` is a brief phase after all cards are dealt where players get a final chance to bid/pass before bidding closes. If no one has bid by the end of `BIDDING_AFTER_DEAL`, re-deal.
  - `trump_context: Optional[TrumpContext]`
  - `bottom_deck: list[Card]`
  - `current_trick: list[tuple[str, list[Card]]]` (player_id → cards played, in the order they were played)
  - `tricks_won: dict[str, list[list[Card]]]` (player_id → list of tricks won)
  - `current_leader_id: str` (who leads this trick)
  - `draw_pile: list[Card]` (remaining cards to deal during DEALING phase; empty once dealing is complete)
  - `cards_dealt_count: int` (number of cards dealt so far, for progress tracking and logging)
  - `current_turn_id: str` (which player is expected to act next — during PLAYING this cycles counter-clockwise from the leader; not used during DEALING since bidding is open to all players simultaneously)
  - `round_leader_id: str` (defender/dealer for this round — the player who won the bid)
  - `attacking_points: int`
  - `round_number: int`
  - `trick_number: int` (current trick within the round, 1-indexed, for logging)
  - `bids: list[Bid]` (history of bids this round)
  - `friend_declarations: list[FriendDeclaration]` (Find Friends only)
  - `revealed_friends: set[str]` (player_ids whose friend status is known)
- Method `to_player_view(player_id: str) -> dict` — returns a sanitized view: the player sees their own hand, the current trick, point totals, but NOT other players' hands or the bottom deck (unless they are the leader during exchange). This is what gets sent over WebSocket.
- Method `to_superuser_view() -> dict` — returns the full state with all hands visible.

3.3. **`src/shengji/models/bid.py`** — `Bid` dataclass: `player_id`, `cards: list[Card]`, `resulting_trump: TrumpContext`.

3.4. **`src/shengji/models/friend_declaration.py`** — `FriendDeclaration` dataclass: `card: Card`, `ordinal: int` (1st, 2nd, etc. person to play it), `resolved_player_id: Optional[str]`.

3.5. **Tests: `tests/test_models/test_game_state.py`**

- `to_player_view` does not leak other players' hands.
- `to_superuser_view` includes all hands.
- Phase transitions: verify that invalid phase sequences raise errors (e.g., cannot go from WAITING to PLAYING directly).

---

## Milestone 4 — Game Engine (Shared Logic)

**Goal:** The core game loop that both modes share. This is the most important and complex module.

### Steps

4.1. **`src/shengji/engine/engine.py`** — Define `GameEngine`.

- Constructor takes `GameState` and a `ModeStrategy` (see Milestone 5).

**First round leader:** The game master (player index 0) is the round leader for round 1. In all subsequent rounds, the leader is determined by the `ModeStrategy.get_next_leader()` method based on who won the previous round.

**Card-by-card dealing with integrated bidding:** Cards are dealt one at a time to players in counter-clockwise order, with a configurable delay between each card (define `DEAL_DELAY_SECONDS` as a constant, e.g. `0.5`). Use `await asyncio.sleep(DEAL_DELAY_SECONDS)` between each card — this is intentional to simulate the real-world experience of drawing cards and allows natural bidding to occur mid-deal. Bidding can happen **at any point during dealing** — a player may bid as soon as they receive a trump-rank card, without waiting for dealing to finish. This means the game phase is `DEALING` while cards are being distributed, and bidding actions are accepted during this phase.

- The engine exposes action methods that validate input, mutate state, and return events:
  - `start_dealing()` → shuffles deck, calls `prepare_deal()` to get the draw pile (100 cards) and bottom (8 cards). Stores the draw pile on the GameState. Begins the dealing loop: deal one card at a time to each player in counter-clockwise order starting from the player after the round leader. After each card, push a `card_dealt` event to that player only. Bidding is open throughout this process.
  - `deal_next_card()` → pops the next card from the draw pile, adds it to the next player's hand, emits a `card_dealt` event to that player. Returns `True` if more cards remain, `False` when the draw pile is empty. The dealing loop calls this method repeatedly with `asyncio.sleep(DEAL_DELAY_SECONDS)` between calls.
  - `place_bid(player_id, suit_or_joker)` → validates bid is legal. **This is not card-selection from hand — the player chooses a suit to declare (or no-trump via jokers), and the server checks they have the required cards.** Bid rules:
    - The trump rank for this round is the defending team's current rank (e.g., rank 4 means trump-rank cards are all 4s).
    - **Single bid:** A player shows one trump-rank card of a specific suit (e.g., one 4♥) to declare that suit as trump. The server validates the player's hand contains at least one 4♥. This overtakes any previous single bid by a different player.
    - **Reinforcement ("nailing it down"):** The current highest bidder can reinforce their single bid by showing a second identical card (e.g., a second 4♥), making it a pair bid. The server validates the player has two of that card. A pair bid is strictly stronger than any single bid.
    - **Overtaking a pair bid:** A nailed-down pair of suited trump-rank cards (e.g., 4♥4♥) can **only** be overtaken by a pair of jokers. Two small jokers or two big jokers declare no-trump. Two big jokers are stronger than two small jokers. No suited pair can overtake another suited pair (they are considered equal strength since suits have no inherent rank).
    - **A single joker cannot be used as a bid.** Only joker pairs are valid joker bids.
    - Bidding is **not turn-based** — any player may bid at any time during dealing (it's a race). The `current_turn_id` field is not used during the DEALING phase. Multiple bids can come in rapid succession.
    - Bidding concludes when dealing finishes AND no new bids have been placed for a brief window (or all players have explicitly passed after dealing completes). If **nobody bids at all** after dealing finishes, re-deal the entire round. The re-deal case must be handled — do not let the game get stuck.
  - `exchange_bottom(player_id, cards_to_put_back)` → the bid winner picks up all 8 bottom cards (adding them to their hand, giving them 33 cards temporarily), then selects 8 cards from their hand to put back as the new bottom. Validates: only the round leader can do this, they must put back exactly 8 cards, hand size returns to 25. Transitions to FRIEND_DECLARATION (Find Friends) or PLAYING (Upgrade).
  - `declare_friends(player_id, declarations)` → delegates to ModeStrategy. Validates constraints (cannot declare trump-rank or jokers). Transitions to PLAYING.
  - `play_cards(player_id, cards)` → the big one. See step 4.2.
  - `end_round()` → calculates point thresholds, rank advancement, team rotation. See step 4.3.

4.2. **Trick resolution logic** (within `play_cards` or a dedicated `src/shengji/engine/tricks.py`):

**Play order within a trick:** The trick leader plays first. Then the remaining 3 players play in **counter-clockwise** order from the leader (based on seating position in the `players` list). The engine must enforce this: `play_cards(player_id, cards)` must reject any play where `player_id != current_turn_id`. After each play, advance `current_turn_id` to the next player counter-clockwise. After all 4 players have played, resolve the trick winner. The trick winner becomes the `current_leader_id` and `current_turn_id` for the next trick.

- **Leading a trick:** Leader can play any valid format (single, identical group, tractor, or throw). Validate format using `classify_play`.
- **Following a trick:** The follower must match the format to the best of their ability given their hand.
  - First: play cards of the led suit (determined by `effective_suit` of the led cards).
  - If they have enough suited cards to match the format, they must. If not, they play as many suited cards as they can and fill the remainder with any other cards.
  - Only exact-format matches of the same suit or trump are eligible to *win* the trick. Off-suit plays that don't match the format can never win.
  - Implement `get_legal_plays(hand, led_format, led_suit, trump_context) -> list[list[Card]]` — returns all legal responses. This is critical for both UI hints and validation.
- **Throw validation:** When a player leads a throw, check that every component is the highest remaining in that suit. If any other player can beat a component with a non-trump card of the same suit, the throw is invalid — the leader must instead lead the weakest defeatable component as a single/pair.
- **Determining trick winner:** Compare all plays. Only plays matching the led format are eligible. Among eligible plays: trump plays beat non-trump plays; among plays of the same type, the highest card (by trump ordering) wins. On ties (equal-value cards), the first player to play wins.
- **Round ends** when all players have 0 cards in hand (after 25 tricks). Transition to SCORING.

4.3. **Scoring and round resolution** (within `end_round` or `src/shengji/engine/scoring.py`):

- Sum points from all tricks won by the attacking team.
- Bottom deck multiplier: if an attacker wins the last trick, bottom points × `min(8, 2 × cards in the winning play's largest component)` — single 2×, pair 4×, tractor 8× (issue #57).
- Rank advancement — **authoritative table** (settled Session 23; the original 200n/300n draft was never shipped). Threshold `40 × n_decks = 80`, band `10 × n_decks = 20`:
    - `0–19`: defending +4
    - `20–39`: defending +3
    - `40–59`: defending +2
    - `60–79`: defending +1
    - `80–99`: attacking +0 (take over as defenders at same rank)
    - `100–119`: attacking +1
    - `120–139`: attacking +2
    - `140+`: attacking +3 (capped, issue #51)
- Advance the winning team's ranks. Game over only when a team defends successfully while ALREADY at rank A (issue #52) — advancing into A earns the right to defend it next round.

4.4. **Tests: `tests/test_engine/`**

- **`test_bidding.py`**: Valid bid accepted, invalid bid rejected (wrong cards, weaker than current bid). Bidding ends correctly.
- **`test_bottom_exchange.py`**: Only leader can exchange, card count stays correct, bottom points are preserved.
- **`test_tricks.py`**: This file will be large. Test:
  - Single card beats single card by trump ordering.
  - Pair must be followed by pair of same suit if available.
  - Tractor must be followed by tractor if available, else pairs, else singles of suit.
  - Throw validation: valid throw accepted, invalid throw forces smallest component.
  - Trick winner determined correctly including tie-breaking.
  - `get_legal_plays` returns correct options for various hand/trick combinations.
- **`test_scoring.py`**: Point counting correct. Bottom deck multiplier applied correctly. Rank advancement thresholds tested at every boundary (0, 5, 195, 200, 395, 400, 500).
- **`test_game_loop.py`**: Full round simulation — deal, bid, exchange, play all tricks, score. Verify all cards accounted for, points sum correctly, next round state is valid.

---

## Milestone 5 — Mode Strategies (Upgrade vs. Find Friends)

**Goal:** Encapsulate the differences between the two game modes behind a common interface so the engine doesn't branch on mode.

### Steps

5.1. **`src/shengji/modes/base.py`** — Define `ModeStrategy` (abstract base class).

```python
class ModeStrategy(ABC):
    @abstractmethod
    def assign_teams(self, state: GameState) -> None: ...

    @abstractmethod
    def on_round_end(self, state: GameState, winning_team: str) -> None: ...

    @abstractmethod
    def get_next_leader(self, state: GameState) -> str: ...

    @abstractmethod
    def needs_friend_declaration(self) -> bool: ...

    @abstractmethod
    def validate_friend_declaration(self, state: GameState, declarations: list) -> None: ...

    @abstractmethod
    def resolve_friend(self, state: GameState, player_id: str, card: Card) -> None: ...
```

5.2. **`src/shengji/modes/upgrade.py`** — `UpgradeStrategy(ModeStrategy)`.

- `assign_teams`: Fixed teams. Players 0,2 vs players 1,3 (or however teams were set in the previous round). Leader's team defends.
- `on_round_end`: Leader rotates to the next player on the winning team (counter-clockwise).
- `get_next_leader`: Next counter-clockwise teammate of current leader on the winning team.
- `needs_friend_declaration`: returns `False`.
- `validate_friend_declaration`: raises error (not applicable).
- `resolve_friend`: no-op.

5.3. **`src/shengji/modes/find_friends.py`** — `FindFriendsStrategy(ModeStrategy)`.

- `assign_teams`: Leader defends alone initially. Friends are revealed during play.
- `validate_friend_declaration`: Declared cards cannot be trump-rank or jokers. Number of friends must be correct (for 4 players, leader declares 1 friend → 2v2). **Edge case: the leader is allowed to declare a card they hold themselves, intentionally or unintentionally becoming their own "friend."** If this happens, the defending team is just the leader alone (1v3). This is a legal play — do not reject it.
- `resolve_friend`: When a player plays a declared card (matching the ordinal), mark them as a friend. Transfer their accumulated points to the defending team's pool. If the leader plays the declared card themselves, they are revealed as their own friend.
- `on_round_end`: Leader for next round comes from the winning team.
- `get_next_leader`: Counter-clockwise rotation among winning team members.

5.4. **Tests: `tests/test_modes/`**

- **`test_upgrade.py`**: Teams assigned correctly. Leader rotates to correct player. Rank advancement applies to correct team.
- **`test_find_friends.py`**: Friend declaration validates legal cards. Friend revealed at correct ordinal. Points transfer correctly when friend is revealed. Edge case: leader declares "2nd person to play A♠" — the first A♠ does not trigger, the second does.

---

## Milestone 6 — Superuser Mode

**Goal:** A debugging interface that can inspect and mutate any game state. Treat this as a first-class feature — it will save enormous time during development and QA.

**Access control:** Superuser privilege is granted exclusively to the **game master** — the first player to create the room. No other player can access superuser features, even if they know the token. The game master activates superuser mode through the UI by clicking a dedicated **"Enable Superuser Mode?"** confirmation button in the lobby. This is intentionally a two-step action (navigate to the option, then confirm) to prevent accidental activation. Once confirmed, the game master's client is flagged as `superuser: true` in their session and superuser controls become visible to them throughout the game.

### Steps

6.1. **`src/shengji/superuser/inspector.py`** — Read-only inspection.

- `get_full_state(game_state) -> dict` — all hands, all points, bottom deck, trick history.
- `validate_state(game_state) -> list[str]` — returns a list of violations (empty = valid). Checks:
  - Total cards across all hands + bottom + played tricks = original deck count.
  - No duplicate cards beyond what the deck allows (2 decks means max 2 of any suited card, max 2 of each joker).
  - Point totals are consistent (attacking_points + defending_points + unplayed_points = 200).
  - Current phase is reachable (no impossible state like PLAYING with no trump context).
  - All players have the correct number of cards for the current point in the round.

6.2. **`src/shengji/superuser/mutator.py`** — State mutation.

- `set_hand(game_state, player_id, cards) -> None` — replaces a player's hand. Automatically moves displaced cards to a "limbo" pool or redistributes. Logs the mutation.
- `set_bottom(game_state, cards) -> None` — replaces the bottom deck.
- `set_points(game_state, attacking_points: int) -> None` — overrides point total.
- `force_phase(game_state, phase: GamePhase) -> None` — jump to a phase (use with caution).
- `deal_specific_hands(game_state, hands: dict[str, list[Card]], bottom: list[Card]) -> None` — set up a fully deterministic deal for testing.
- Every mutation must be followed by `validate_state` — if the mutation creates an illegal state, raise a warning (not an error — superuser may intentionally create edge cases).

6.3. **`src/shengji/superuser/api.py`** — HTTP endpoints (mounted under `/superuser/`).

- All superuser endpoints require **both**:
  1. The request's `player_id` must match the room's game master player ID (checked server-side).
  2. The game master must have previously confirmed superuser activation (a `superuser_enabled: bool` flag stored on the `Room` object, set via the confirmation flow below).
- `POST /superuser/enable/{room_id}` — game master calls this after clicking "Enable Superuser Mode?" and confirming. Sets `room.superuser_enabled = True`. This is the only endpoint that does not require `superuser_enabled` to already be true.
- `GET /superuser/state/{room_id}` — full game state.
- `POST /superuser/validate/{room_id}` — run validation, return violations.
- `POST /superuser/set-hand/{room_id}` — body: `{player_id, cards}`.
- `POST /superuser/set-points/{room_id}` — body: `{attacking_points}`.
- `POST /superuser/force-phase/{room_id}` — body: `{phase}`.
- `POST /superuser/deal-specific/{room_id}` — body: `{hands, bottom}`.

6.4. **Tests: `tests/test_superuser/`**

- `validate_state` catches: missing cards, duplicate cards, point mismatch, impossible phase.
- `set_hand` correctly moves cards and validation passes after mutation.
- `deal_specific_hands` sets up an exact scenario that can then be played through the engine.
- Non-game-master player cannot call any superuser endpoint even with correct player_id format.
- Game master cannot call mutation endpoints before calling `/superuser/enable` first.
- Superuser enable is idempotent (calling it twice is harmless).

---

## Milestone 7 — Networking & Room Management

**Goal:** Players can create/join rooms and play via WebSocket. No login or auth required.

### Steps

7.1. **`src/shengji/network/room.py`** — Room management.

- `Room` class: `room_id: str` (6-character alphanumeric code), `players: list[WebSocketConnection]`, `game_state: GameState`, `engine: GameEngine`.
- `RoomManager`: in-memory dict of active rooms.
  - `create_room(player_name) -> (room_id, player_id)` — creates room, adds creator as game master (player index 0).
  - `join_room(room_id, player_name) -> player_id` — adds player. Rejects if room is full (4 players) or game already started.
  - `remove_player(room_id, player_id)` — handles disconnects.

7.2. **`src/shengji/network/app.py`** — FastAPI application.

- `POST /rooms` — create a room. Returns `{room_id, player_id}`.
- `POST /rooms/{room_id}/join` — join a room. Body: `{name}`. Returns `{player_id}`.
- `WebSocket /ws/{room_id}/{player_id}` — main game connection.
- Mount superuser routes from Milestone 6.
- Serve static files from `frontend/`.

7.3. **`src/shengji/network/handler.py`** — WebSocket message protocol.

**Card serialization format:** All card references in WebSocket messages use JSON objects with two fields: `{"suit": "spades", "rank": "K"}`. Suit values: `"spades"`, `"hearts"`, `"diamonds"`, `"clubs"`, `"joker"`. Rank values: `"2"` through `"10"`, `"J"`, `"Q"`, `"K"`, `"A"`, `"small_joker"`, `"big_joker"`. This format must be consistent across all messages (incoming and outgoing) and match the enum string values used by the Card model's serialization. Define a `card_to_json` / `card_from_json` utility pair in the models and use them everywhere — do not hand-write serialization in multiple places.

- Incoming messages (client → server): JSON with `action` field.
  - `{"action": "select_mode", "mode": "upgrade" | "find_friends"}` — game master only, during WAITING phase.
  - `{"action": "bid", "suit": "hearts"}` — during DEALING or BIDDING_AFTER_DEAL. Declares a suit as trump. Server validates player has the trump-rank card(s).
  - `{"action": "bid", "joker": "small" | "big"}` — during DEALING or BIDDING_AFTER_DEAL. Declares no-trump via joker pair. Server validates player has a pair of the specified joker.
  - `{"action": "pass_bid"}` — pass on bidding (only during BIDDING_AFTER_DEAL).
  - `{"action": "exchange_bottom", "cards_to_put_back": [...]}` — during BOTTOM_EXCHANGE.
  - `{"action": "declare_friends", "declarations": [...]}` — during FRIEND_DECLARATION.
  - `{"action": "play_cards", "cards": [...]}` — during PLAYING.
  - `{"action": "validate_play", "cards": [...]}` — during PLAYING (read-only validation, see M8.7).
- Outgoing messages (server → client): JSON with `type` field.
  - `{"type": "room_update", "players": [...], "mode": ...}` — lobby state.
  - `{"type": "card_dealt", "card": {...}}` — sent to one player only during DEALING. Contains the newly dealt card.
  - `{"type": "bid_update", "current_bid": {...}, "bidder": "...", "available_bids": [...]}` — broadcast to all after a bid. `available_bids` is per-player (each player's view includes only their own available bids).
  - `{"type": "game_state", ...}` — the player's view of the game (from `to_player_view`).
  - `{"type": "play_valid"}` / `{"type": "play_invalid", "reason": "..."}` — response to `validate_play`.
  - `{"type": "error", "message": ...}` — validation errors.
  - `{"type": "game_aborted", "reason": "..."}` — broadcast to all players when any player disconnects. Client must return to landing page on receipt.
  - `{"type": "game_over", "winner": ...}` — final result.
- On every state change, broadcast `game_state` to all players (each gets their own view).
- **Auto-start:** When the 4th player joins, if a mode has been selected, automatically call `start_dealing()` and begin dealing cards. If no mode selected yet, prompt the game master to choose.

7.4. **Tests: `tests/test_network/`**

- Room creation returns valid room code.
- Joining a full room is rejected.
- Game auto-starts when 4th player joins and mode is selected.
- WebSocket messages are routed to correct engine methods.
- Each player receives only their own view (not other hands).
- **Disconnect handling:** If any player disconnects (WebSocket closes unexpectedly), the server immediately sends a `{"type": "game_aborted", "reason": "A player disconnected"}` message to all remaining connected players, then closes all WebSocket connections in that room and destroys the room. There is no pause-and-wait, no bot replacement. All players are kicked. The client, upon receiving `game_aborted`, displays a clear message ("The game ended because a player disconnected") and returns the user to the landing page. This is intentionally simple — see the Future Todos section for potential reconnection support.

---

## Milestone 8 — Frontend

**Goal:** Functional browser UI. The game must be playable and clear. Keep the visual design simple (no graphics/animations beyond card interactions), but the UX flows must be complete and polished.

### Steps

8.1. **`frontend/index.html`** — Single-page app with three screens.

**Screen 1: Landing page.**
- Two options: **"Create Room"** button (with a name input), or **"Join Room"** (with a room code input and a name input).
- Clean and minimal — just these inputs and buttons, centered on the page.

**Screen 2: Lobby.**
- **Upper-left corner:** `ROOM CODE: XXXXXX` in large, easily-copyable text. Players share this code to invite friends.
- **Upper-right corner:** `CURRENTLY PLAYING: [trump rank] [trump suit or "no trump"]` — e.g., "4 of Hearts" or "8 No Trump". Before the first round starts, this shows the initial rank (e.g., "Currently at Rank 2"). This header persists into the game screen.
- **Center:** Player list showing who has joined (names). The game master is marked with a "(Host)" label.
- **Below player list:** If fewer than 4 players, display **"Waiting for players..."** text. The game master also sees:
  - A mode selector: two buttons, **"Upgrade (升级)"** and **"Find Friends (找朋友)"**.
  - A clearly separated **"Enable Superuser Mode?"** button with an inline "Are you sure?" confirmation. Only visible to the game master.
- **Auto-start:** When the 4th player joins AND a mode has been selected, the game begins automatically — transition to the game screen. If 4 players have joined but no mode is selected, prompt the game master: "4 players ready — select a game mode to begin."

**Screen 3: Game screen** — the main play area, described in sections below.

8.2. **Game screen layout.**

- **Top bar (persistent):**
  - Left: `ROOM CODE: XXXXXX`
  - Right: `CURRENTLY PLAYING: [rank] [suit]` (updates each round when the trump context changes)
- **Center: trick area.** Shows the 4 positions (top, left, right, bottom — corresponding to the 4 players). Each position shows the player's name and, during the **current active trick only**, the card(s) they have played so far. **Once a trick is complete and the winner is determined, the trick area is immediately cleared.** There is no trick history visible — players cannot scroll back or see previous tricks. This intentionally replicates the real-world experience: players must count cards from memory. The current player (you) is always at the bottom.
- **Below trick area: point display.** Shows `Attacking team: X pts` and `Defending team: X pts` (or equivalent).
- **Bottom: player's hand.** Cards rendered in a horizontal row using Unicode suit symbols (♠♥♦♣) and text ranks. Cards should be sorted by suit, then by rank within suit, with trump cards grouped together on the right side of the hand.
- **Below hand: action area.** Context-sensitive buttons that change based on game phase (see 8.3–8.5).

8.3. **Dealing phase UX.**

- As cards are dealt one at a time (server pushes `card_dealt` messages), each new card appears instantly in the player's hand in its correct sorted position. **No animations.** The frontend should be lightweight and fast — a card appearing is sufficient to communicate that it arrived. Do not add CSS transitions, slides, or any visual effects.
- **Bidding buttons** appear in the action area as soon as dealing begins:
  - **4 suit buttons:** ♠, ♥, ♦, ♣ — each labeled with the suit symbol. Clicking declares that suit as trump.
  - **2 joker buttons:** "No Trump (Small Joker)" and "No Trump (Big Joker)".
  - **Button enable/disable logic (server-validated):** A suit button is only clickable if the player currently holds at least one trump-rank card of that suit that they haven't already bid. The joker buttons are only clickable if the player holds a pair of the relevant joker (2 small jokers or 2 big jokers). The server sends an updated `available_bids` list with each `card_dealt` and `game_state` message so the client knows which buttons to enable. **Do not rely on client-side hand inspection for this — the server is the authority.**
  - When a player clicks a suit button: if they have one trump-rank card of that suit, it's a single bid. If they already hold the current highest bid for that suit (single) and now have two, clicking again reinforces to a pair ("nails it down"). The server determines which case applies.
  - A **"Pass"** button is available during the `BIDDING_AFTER_DEAL` phase (after dealing completes). During dealing itself, players simply don't click anything if they don't want to bid.
- **Current bid display:** Show the current highest bid above the bidding buttons — e.g., "Current bid: Player 2 — 4♥ (single)" or "Current bid: Player 2 — 4♥4♥ (nailed down)". If no bid yet, show "No bid yet."

8.4. **Card selection and play flow** — during the PLAYING phase.

- Each card in the player's hand is rendered as a clickable element.
- Clicking a card **toggles its selection**. Selected cards are visually distinguished — raise them upward (CSS `transform: translateY(-12px)`) and apply a highlighted border or background tint. Deselecting returns the card to its normal position.
- Multiple cards can be selected simultaneously (required for pairs, tractors, throws).
- A **"Play" button** is shown when it is the player's turn. Clicking Play sends a `{"action": "validate_play", "cards": [...selected cards...]}` message to the server *before* committing the play. The server responds with either:
  - `{"type": "play_valid"}` — the client then sends the real `play_cards` action and clears the selection.
  - `{"type": "play_invalid", "reason": "..."}` — the client displays the reason inline (e.g., "You must follow suit — you have ♠ cards remaining") without clearing the selection so the player can adjust.
- The Play button is disabled (greyed out) when: it is not the player's turn, or no cards are selected.
- A **"Clear Selection"** button deselects all cards without submitting anything.

8.5. **Bottom exchange and friend declaration UX.**

- **Bottom exchange (bid winner only):** The 8 bottom cards are added to the player's hand (temporarily showing 33 cards). The action area shows: "Select 8 cards to put back in the bottom deck" and a **"Confirm Exchange"** button. The button is disabled until exactly 8 cards are selected. After confirming, the hand returns to 25 cards.
- **Friend declaration (Find Friends mode only):** A separate UI panel appears — **not** card selection from hand. The panel has:
  - A dropdown for card rank (2 through A, excluding the current trump rank).
  - A dropdown for suit (♠♥♦♣).
  - A dropdown for ordinal ("1st person to play this card", "2nd person to play this card").
  - A **"Declare Friend"** button to confirm.

8.6. **`frontend/app.js`** — WebSocket client.

- Connect to `/ws/{room_id}/{player_id}`.
- Render game state on every `game_state` message.
- Handle `card_dealt` messages during dealing: append the new card to the player's hand and re-render the hand immediately (no animation).
- Send action messages on user interaction.
- Display errors from `error` messages inline near the action area (not as browser alerts).
- Maintain client-side selection state (`selectedCards: Set`) that resets on each new game state update (i.e., after a play is accepted, the hand re-renders from server state and selection starts fresh).

8.7. **WebSocket protocol additions** — add to the message list in M7.3:

- `{"action": "validate_play", "cards": [...]}` — incoming, during PLAYING. Server runs `get_legal_plays` to check if the proposed play is legal. Returns `play_valid` or `play_invalid` without advancing game state. This is a read-only check — it never mutates `GameState`.
- `{"action": "bid", "suit": "hearts"}` or `{"action": "bid", "joker": "small"}` — incoming, during DEALING or BIDDING_AFTER_DEAL. Player declares a suit or joker pair. Server validates they have the cards.
- `{"type": "card_dealt", "card": {...}}` — outgoing, sent to one player only, during DEALING. Contains the newly dealt card.
- `{"type": "bid_update", "current_bid": {...}, "available_bids": [...]}` — outgoing, broadcast to all after a bid is placed. Also included in each player's `game_state` view.

8.8. **No frontend tests required** — but the `validate_play` and `bid` endpoints are tested via the backend tests in M7.

---

## Milestone 9 — Integration Testing & Polish

**Goal:** End-to-end tests that simulate full games, plus edge case hardening.

### Steps

9.1. **`tests/test_integration/test_full_game.py`** — Simulate a complete game.

- Use `deal_specific_hands` (superuser) to set up deterministic hands.
- Play through an entire round with scripted moves.
- Verify final scores and rank changes.
- Do this for both Upgrade and Find Friends modes.

9.2. **`tests/test_integration/test_edge_cases.py`** — Known tricky scenarios.

- Last trick won by attackers with bottom deck multiplier.
- Throw invalidation (component beaten by non-trump suited card).
- No-trump round: verify 5 distinct suits work correctly.
- Friend declared on a card that never gets played (friend stays hidden).
- Player wins the game by defending at rank A.
- All 4 players pass on bidding (re-deal).

9.3. **State validation sweep.** Add a hook in the engine: after every action, run `validate_state`. During development and testing, this should be ON by default. Add a flag to disable it in production for performance.

9.4. **Game session logging.**

Each game session must produce a persistent log file that is complete enough to replay or diagnose any crash or buggy state purely by reading it — without needing to reproduce the problem live.

**Format:** Use **newline-delimited JSON** (one JSON object per line, `.jsonl` extension). This format is easy to stream-write, trivially parseable line-by-line, grep-friendly, and readable without any special tooling. Do not use a human-readable prose format — structured fields are critical so that future tooling can parse, filter, and replay logs programmatically.

**File location:** `logs/games/{room_id}_{timestamp}.jsonl`. Create the `logs/games/` directory on startup if it doesn't exist.

**What to log** — every entry must include at minimum `ts` (ISO 8601 timestamp), `room_id`, `round`, `phase`, and `seq` (monotonically increasing sequence number per game). Beyond that:

- **Game lifecycle events:** room created, player joined (with player_id and name), game mode selected, game started, round started, round ended (with full scoring breakdown), game over (with winner).
- **Every player action:** player_id, action type, cards involved (as serialized card objects, not display strings), and the resulting phase transition.
- **Full game state snapshot** at the start of each round (after dealing) and at the end of each round (before resetting). This snapshot includes all hands, bottom deck, trump context, and team assignments. These snapshots are the "save points" — if you know which round had the bug, you can load the pre-round snapshot and replay from there.
- **Superuser mutations:** any superuser action must be logged with `"event": "superuser_mutation"`, the mutation type, the before/after values, and a note that the state was manually altered. This is critical — a log is useless for debugging if it doesn't distinguish natural game flow from superuser intervention.
- **Validation failures:** any call to `validate_state` that returns violations must be logged immediately with the full list of violations and the full game state at that moment.
- **Errors and exceptions:** any unhandled exception in the engine or network handler must be logged with the full traceback and the last known game state.

**Example log line:**
```json
{"seq": 42, "ts": "2025-01-15T14:23:01.004Z", "room_id": "ABC123", "round": 2, "phase": "PLAYING", "event": "play_cards", "player_id": "p1", "cards": [{"suit": "spades", "rank": "K"}, {"suit": "spades", "rank": "K"}], "trick_number": 7, "resulting_phase": "PLAYING"}
```

**Implementation notes:**
- Write log entries synchronously (or use an async queue that flushes promptly) — a crash must not lose the last few events.
- Log file is append-only. Never truncate or overwrite mid-game.
- Implement `scripts/replay_log.py` as a standalone script that pretty-prints a log file into a human-readable transcript. Run it with `python scripts/replay_log.py logs/games/ABC123_....jsonl`. It should output: round headers, each player action with card names, trick winners, and the final score/rank changes per round. This is the primary debugging workflow — when investigating a bug, run the replay script on the relevant log file to get a readable game transcript without touching the game code.

---

## Appendix A: Card & Trick Reference

Kept here so you don't have to keep re-reading the rules website.

### Point values
| Card | Points |
|------|--------|
| 5    | 5      |
| 10   | 10     |
| K    | 10     |
| All others | 0 |

Each deck = 100 points. 2 decks (4 players) = 200 points total.

### Trump hierarchy (suit specified, e.g. Hearts, trump rank 7)
1. Big Joker (highest)
2. Small Joker
3. 7♥ (trump rank in trump suit)
4. 7♠ = 7♦ = 7♣ (trump rank in other suits, equal)
5. A♥, K♥, Q♥, ... 8♥, 6♥, 5♥, ... 3♥ (non-trump-rank hearts, normal order, skip 7)
6. Non-trump suits in normal order (A high, 2 low, trump rank removed — the two ranks on either side of the removed rank become adjacent)

### Trick formats
| Format | Example | Min size |
|--------|---------|----------|
| Single | 5♠ | 1 card |
| Identical group | 5♠5♠ (pair) | 2 cards |
| Tractor | 5♠5♠6♠6♠ (pair tractor, 2 consecutive pairs) | 4 cards |
| Throw | K♠ + Q♠Q♠ + 8♠8♠9♠9♠ (if all are highest remaining) | 1+ cards |

### Rank advancement thresholds (n = number of decks)
| Attacking team points | Outcome |
|-----------------------|---------|
| 0                     | Defending team advances 3 ranks |
| 5 to 100n - 5        | Defending team advances 2 ranks |
| 100n to 200n - 5     | Defending team advances 1 rank |
| 200n to 300n - 5     | Attacking team takes over, no rank change |
| 300n to 400n - 5     | Attacking team advances 1 rank |
| 400n to 500n - 5     | Attacking team advances 2 ranks |
| 500n or more         | Attacking team advances 3 ranks |

### Bottom deck point multiplier
If the attacking team wins the last trick, points in the bottom deck are added to the attacking team's total, multiplied by `2 * L` where `L` is the number of cards in the largest component of the last trick.

| Largest component | Multiplier |
|-------------------|------------|
| Single (1)        | 2x         |
| Pair (2)          | 4x         |
| Triple (3)        | 6x         |
| Tractor of 4      | 8x         |

---

## Appendix B: Testing Expectations

Every pull request must:

1. Include unit tests for all new logic.
2. Pass all existing tests (`pytest`).
3. Maintain >90% line coverage on `src/shengji/engine/` and `src/shengji/models/`.
4. Include at least one integration test for any new user-facing feature.
5. Use `deal_specific_hands` in tests wherever deterministic card deals are needed — never rely on random shuffles in tests.

---

## Appendix C: Implementation Order Summary

| Order | Milestone | Depends On | Estimated Complexity |
|-------|-----------|------------|---------------------|
| 1     | M0: Skeleton | Nothing | Low |
| 2     | M1: Card & Deck | M0 | Low |
| 3     | M2: Trump & Ordering | M1 | Medium |
| 4     | M3: Game State | M1, M2 | Medium |
| 5     | M4: Game Engine | M2, M3 | High |
| 6     | M5: Mode Strategies | M4 | Medium |
| 7     | M6: Superuser | M3, M4 | Medium |
| 8     | M7: Networking | M4, M5, M6 | Medium |
| 9     | M8: Frontend | M7 | Low |
| 10    | M9: Integration | All | Medium |

Milestones 6 (Superuser) and 5 (Modes) can be developed in parallel once M4 is complete.

---

## Appendix D: Tech Stack Analysis

### Backend: Python + FastAPI + WebSockets

**Why this choice:**
- FastAPI is the most popular modern Python web framework for async applications. It has first-class WebSocket support, automatic OpenAPI docs (useful for the superuser API), and Pydantic integration for request/response validation — which we already need for the card serialization models.
- Python is the right language for this project because the game logic is complex but not performance-critical (4 players, 25 tricks per round). Python's readability makes the engine code easier to review and debug, which matters more here than raw speed.
- `asyncio` is essential for the dealing mechanic (dealing cards one at a time with `asyncio.sleep`). FastAPI runs natively on `asyncio`, so there's no impedance mismatch.

**Pros:**
- Mature ecosystem: FastAPI, Pydantic, pytest, uvicorn are all battle-tested and well-documented.
- WebSocket handling is built into FastAPI — no separate library needed for the core protocol.
- Pydantic models give us automatic validation on API inputs, which reduces boilerplate in the superuser endpoints.
- Rapid development: Python's expressiveness means less code for the game logic, which is the bulk of this project.
- Easy deployment: a single `uvicorn` process serves both the API and WebSocket connections.

**Cons:**
- **No persistent state.** All game state lives in-memory. If the server process dies, all active games are lost. For a casual card game this is acceptable, but if durability matters later, you'd need to add Redis or a database. This is a known tradeoff — adding persistence now would significantly increase scope for minimal benefit.
- **Single-process scaling.** WebSocket connections are pinned to the process that accepted them. You cannot load-balance across multiple server instances without sticky sessions or a pub/sub layer (e.g., Redis). For 4-player games this is irrelevant — a single process can handle thousands of concurrent rooms.
- **Python is slow** relative to Go, Rust, or Node.js. This does not matter for a turn-based card game with 4 players, but would matter if this were a real-time action game.
- **GIL limitations.** Python's Global Interpreter Lock means CPU-bound work blocks the event loop. The game engine logic is lightweight enough that this won't be an issue, but it's worth noting. Do not put expensive computations (e.g., exhaustive `get_legal_plays` searches) in the async hot path without profiling.

**Alternatives considered:**
- **Node.js + Express/Socket.io:** Would also work well. Socket.io has slightly better reconnection handling out of the box. Rejected because the game logic (card ordering, tractor detection, throw validation) benefits from Python's readability and the team's familiarity.
- **Go + Gorilla WebSocket:** Better performance and concurrency, but significantly more verbose for the complex game logic. Not worth it for 4-player games.
- **Django Channels:** Heavier than FastAPI, adds ORM complexity we don't need (no database), and async support is less mature.

### Frontend: Vanilla HTML + CSS + JavaScript

**Why this choice:**
- This is a card game with text-based card rendering (Unicode symbols), a handful of buttons, and a WebSocket connection. There is no complex component tree, no routing, no shared state across pages. A React/Vue/Svelte framework would add build tooling, a `node_modules` directory, and a compilation step — all for a single-page app that is essentially one screen with conditional rendering.
- Vanilla JS keeps the frontend zero-dependency: open `index.html`, connect to the WebSocket, done. No `npm install`, no bundler, no transpiler.

**Pros:**
- Zero build step. The server serves static files directly. No webpack, no Vite, no build pipeline to maintain.
- Minimal surface area for bugs. The frontend is a thin rendering layer over server state — it receives JSON, renders HTML, sends JSON. Frameworks add indirection that isn't needed here.
- Easy to debug: open browser DevTools, inspect the WebSocket messages, done.
- No frontend dependency management or version conflicts.

**Cons:**
- **No component abstraction.** As the UI grows, vanilla JS DOM manipulation can become messy. Mitigate this by organizing rendering into clear functions (`renderHand()`, `renderTrick()`, `renderBidButtons()`) that each own a section of the DOM.
- **No reactive data binding.** When game state updates, you must manually re-render the relevant DOM sections. This is manageable because the server pushes complete state on every update — just re-render everything on each `game_state` message.
- **No TypeScript.** No compile-time type checking on the client. Mitigate by keeping the frontend simple and testing the WebSocket protocol thoroughly on the backend.
- **Harder to maintain long-term** if the UI requirements grow significantly (e.g., animations, mobile responsiveness, spectator mode). If the frontend ever needs a rewrite, migrating to a framework later is straightforward because the WebSocket protocol is the contract — the backend doesn't change.

**Alternatives considered:**
- **React/Vue + Vite:** Standard choice for web apps. Rejected because it adds a build step, `node_modules`, and framework concepts (state management, component lifecycle) that are unnecessary for this scope. If the frontend grows past ~500 lines of JS, reconsider.
- **Svelte:** Lightest framework option with the smallest bundle. Would be a reasonable upgrade path if the vanilla JS approach becomes unwieldy.
- **HTMX:** Interesting for server-rendered HTML, but WebSocket-driven real-time updates don't map cleanly to HTMX's request/response model.

---

## Future Todos

These are intentionally **out of scope** for the current implementation. Do not implement them now. They are recorded here so future contributors understand the known gaps and can pick them up as follow-on work.

- **Game state restoration after disconnect.** Currently, if any player disconnects, the room is destroyed and all players are kicked. A natural extension would be to persist the game log (already being written as `.jsonl`) and allow players to rejoin a room by presenting the same room code within a grace period. The `replay_log.py` script and the round-start snapshots in the log are designed to support this, but the reconnect flow itself is not implemented.

- **Spectator mode.** Allow additional users to join a room as observers (read-only view). They would see the current trick area and point totals but not any player's hand. The `to_player_view` → `to_superuser_view` pattern already provides the infrastructure for different views; a `to_spectator_view` method would be a straightforward addition.

- **Persistent leaderboard / game history.** Store completed game results (winners, rank levels reached, number of rounds) in a simple SQLite database or flat file. Currently all game data is ephemeral.

- **Mobile-responsive layout.** The current UI targets desktop browsers. Adapting the hand display and trick area for small screens (card scrolling, touch-friendly hit targets) is non-trivial but desirable.

- **Bot/AI player.** Allow a room to start with fewer than 4 human players by filling empty seats with a simple rule-based bot. The minimum viable bot is a random-legal-play bot (picks a random legal play from `get_legal_plays`). A stronger bot requires game-tree search or a heuristic model.

- **Configurable deal delay.** Currently `DEAL_DELAY_SECONDS` is a hardcoded constant. Exposing this as a room setting (the game master can set "fast deal" vs. "normal deal") would improve the experience for experienced players who want to move quickly.

- **Round replay from log.** Extend `scripts/replay_log.py` to not just pretty-print a log, but to actually feed a recorded round back through the engine for debugging. This would allow reproducing a specific bug deterministically without needing the original players.

- **Session resumption after accidental disconnect.** Currently any disconnect immediately aborts the room for all players, which is a poor user experience if someone simply loses WiFi for a moment. The desired end state is that a player can close and reopen their browser (or refresh the page) and land back in their seat mid-game with full hand and game state restored — ideally within a grace period (e.g. 60–90 seconds) before the room is torn down. Full design is TBD, but the solution will likely involve some combination of: (1) a durable session token (cookie or URL parameter) issued at room-join time so the server can re-authenticate the returning player without a login flow, (2) persisting game state beyond the in-memory `RoomManager` (Redis or SQLite) so it survives a brief server hiccup, and (3) a reconnect WebSocket handshake that replays any missed messages since the disconnect. The existing `.jsonl` game log and round-start snapshots are already structured to support replaying state, which gives this a natural starting point.
