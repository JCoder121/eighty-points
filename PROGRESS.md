# Shengji — Progress Log

Newest entries at the top.

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
