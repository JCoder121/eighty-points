"""Per-game JSONL event logger.

Writes one log file per game to ``logs/games/{unix_timestamp}.jsonl``.
Each line is a JSON object (JSONL format).  The file is flushed after every
write so that a mid-game server crash leaves a readable log up to the last
event.

All logging is best-effort: write errors are silently swallowed so that a
filesystem problem never crashes a running game.

Usage
-----
Create one ``GameLogger`` when the first round starts and keep it on the
``Room`` object.  Call ``close()`` when the game ends or is aborted.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shengji.models.bid import Bid
    from shengji.models.card import Card
    from shengji.models.friend_declaration import FriendDeclaration
    from shengji.models.game_state import GameState


class GameLogger:
    """Append-only, crash-safe JSONL logger for one game session."""

    def __init__(self, log_dir: str = "logs/games/") -> None:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        self._path = Path(log_dir) / f"{ts}.jsonl"
        self._file = open(self._path, "a")  # noqa: SIM115
        self._seq = 0

    # ------------------------------------------------------------------
    # Internal write helper
    # ------------------------------------------------------------------

    def _write(self, event: dict) -> None:
        event["seq"] = self._seq
        event["ts"] = time.time()
        self._seq += 1
        try:
            self._file.write(json.dumps(event, default=str) + "\n")
            self._file.flush()
        except Exception:
            pass  # best-effort — never crash the game

    def close(self) -> None:
        try:
            self._file.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Event methods
    # ------------------------------------------------------------------

    def log_round_start(self, state: "GameState") -> None:
        """Full state snapshot after dealing completes (all hands dealt, before bidding)."""
        self._write({
            "event": "round_start",
            "round_number": state.round_number,
            "mode": state.mode,
            "round_leader_id": state.round_leader_id,
            "players": [p.to_json(include_hand=True) for p in state.players],
            "bottom_deck": [c.to_json() for c in state.bottom_deck],
        })

    def log_bid(self, player_id: str, cards: "list[Card]", bid: "Bid") -> None:
        self._write({
            "event": "bid",
            "player_id": player_id,
            "cards": [c.to_json() for c in cards],
            "resulting_trump": {
                "trump_rank": bid.resulting_trump.trump_rank.value,
                "trump_suit": (
                    bid.resulting_trump.trump_suit.value
                    if bid.resulting_trump.trump_suit else None
                ),
            },
        })

    def log_pass_bid(self, player_id: str) -> None:
        self._write({
            "event": "pass_bid",
            "player_id": player_id,
        })

    def log_bidding_closed(self, state: "GameState", redeal: bool) -> None:
        if redeal:
            self._write({
                "event": "bidding_closed",
                "redeal": True,
                "winning_bid": None,
                "trump_context": None,
                "teams": None,
            })
        else:
            winning_bid = state.bids[-1] if state.bids else None
            self._write({
                "event": "bidding_closed",
                "redeal": False,
                "winning_bid": winning_bid.to_json() if winning_bid else None,
                "trump_context": (
                    {
                        "trump_rank": state.trump_context.trump_rank.value,
                        "trump_suit": state.trump_context.trump_suit.value
                        if state.trump_context.trump_suit else None,
                    }
                    if state.trump_context else None
                ),
                "teams": [
                    {"id": p.id, "team": p.team}
                    for p in state.players
                ],
            })

    def log_bottom_exchange(self, player_id: str, cards_buried: "list[Card]") -> None:
        self._write({
            "event": "bottom_exchange",
            "player_id": player_id,
            "cards_buried": [c.to_json() for c in cards_buried],
        })

    def log_friend_declarations(
        self, player_id: str, declarations: "list[FriendDeclaration]"
    ) -> None:
        self._write({
            "event": "friend_declarations",
            "player_id": player_id,
            "declarations": [
                {"card": d.card.to_json(), "ordinal": d.ordinal}
                for d in declarations
            ],
        })

    def log_play_cards(
        self,
        player_id: str,
        cards: "list[Card]",
        trick_number: int,
        trick_position: int,
    ) -> None:
        self._write({
            "event": "play_cards",
            "player_id": player_id,
            "cards": [c.to_json() for c in cards],
            "trick_number": trick_number,
            "trick_position": trick_position,  # 0=lead, 1-3=follow
        })

    def log_friend_revealed(
        self, player_id: str, card: "Card", ordinal: int
    ) -> None:
        self._write({
            "event": "friend_revealed",
            "player_id": player_id,
            "card": card.to_json(),
            "ordinal": ordinal,
        })

    def log_throw_penalty(
        self,
        player_id: str,
        attempted_cards: "list[Card]",
        forced_cards: "list[Card]",
        penalty: int,
        trick_number: int,
    ) -> None:
        self._write({
            "event": "throw_penalty",
            "player_id": player_id,
            "attempted_cards": [c.to_json() for c in attempted_cards],
            "forced_cards": [c.to_json() for c in forced_cards],
            "penalty": penalty,
            "trick_number": trick_number,
        })

    def log_trick_complete(
        self,
        trick_number: int,
        winner_id: str,
        plays: list[dict],
        trick_points: int,
        attacking_points: int,
    ) -> None:
        self._write({
            "event": "trick_complete",
            "trick_number": trick_number,
            "winner_id": winner_id,
            "plays": plays,
            "trick_points": trick_points,
            "attacking_points": attacking_points,
        })

    def log_round_end(self, result: dict, state: "GameState") -> None:
        self._write({
            "event": "round_end",
            "round_number": result.get("round_number", state.round_number - 1),
            "attacking_points": result["attacking_points"],
            "winner": result["winner"],
            "steps": result["steps"],
            "game_over": result["game_over"],
            "players": result.get("round_players", []),
            "bottom_deck": [c.to_json() for c in state.bottom_deck],
        })

    def log_game_over(self, winner: str, players: list[dict]) -> None:
        self._write({
            "event": "game_over",
            "winner": winner,
            "players": players,
        })

    def log_error(self, player_id: str, action: str, message: str) -> None:
        self._write({
            "event": "error",
            "player_id": player_id,
            "action": action,
            "message": message,
        })
