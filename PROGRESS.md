# Shengji — Progress Log

Newest entries at the top.

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
