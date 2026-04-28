# Shengji (升级)

A real-time multiplayer web implementation of the Chinese trick-taking card game Shengji (升级, "Upgrade"), playable in the browser with 4 players over WebSockets.

There are some remaining unresolved issues. One day, I might return to this project and fully complete it, with superuser mode (game state modifications), code refactoring, and an embedded demo link

## Demo
[Game start state demo](https://youtu.be/js4RYXfHU3E)

[Game end state demo](https://youtu.be/XYI9y-lNWTo)


> **[Screen recording placeholder]** — A walkthrough of gameplay will be added here.

## Features

- **Two game modes**
  - **Upgrade (升级):** Fixed 2v2 teams, leader rotates among the winning team
  - **Find Friends (找朋友):** Dynamic teams — the leader secretly declares a "friend" card; whoever plays it becomes their partner, revealed mid-round
- **Full trick engine** — singles, pairs, tractors (consecutive pairs), and throws with server-side validation
- **Trump system** — suit trump, no-trump (joker pair), trump rank ordering, and rank adjacency across the full 2-deck hierarchy
- **Rank progression** — both sides advance ranks based on attacking points (80 to win, 20 pts per rank skip)
- **Real-time multiplayer** — WebSocket-based, all game logic server-authoritative
- **Superuser tools** — inspect/modify any player's hand, set points, inject cards, force phase transitions (for debugging and testing)
- **Game session logging** — every action logged as JSONL for replay and debugging
- **Responsive layout** — basic mobile support with horizontal-scroll hand and larger tap targets

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.10+, FastAPI, WebSockets |
| Frontend | Vanilla HTML/JS (single-page, no framework) |
| Testing | pytest (553 tests), pytest-asyncio |
| Linting | Ruff |

No build step. No bundler. No frontend framework.

## Architecture

```
src/shengji/
├── models/       # Card, Deck, Player, GameState, TrumpContext, Bid, FriendDeclaration
├── engine/       # GameEngine (game loop), tricks (resolution), scoring, logger
├── modes/        # Upgrade and FindFriends strategy implementations
├── network/      # FastAPI app, WebSocket handler, room management
└── superuser/    # Inspector, mutator, and API for debugging

frontend/
├── index.html    # Single-page app (landing → lobby → game)
└── app.js        # WebSocket client, rendering, UI state
```

The browser never computes game logic — it renders state pushed by the server. Every player action is validated server-side before being applied.

**Communication flow:**
1. HTTP REST to create/join rooms
2. WebSocket upgrade for real-time gameplay
3. Server broadcasts full game state to all players on every action

## Getting Started

```bash
# Install
pip install -e ".[dev]"

# Run tests
pytest

# Start the server
uvicorn shengji.network.app:app --reload
# Open http://localhost:8000 in 4 browser tabs
```

## Rules Reference

https://robertying.com/shengji/rules.html

## Built With

This project was built end-to-end using [Claude Code](https://claude.ai/claude-code) (Anthropic's CLI for Claude) — from architecture planning through implementation, testing, and debugging.
