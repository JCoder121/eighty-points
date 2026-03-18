"""WebSocket message dispatch and broadcast helpers.

This module contains all the game logic that glues incoming WebSocket
messages to the engine, and outgoing messages back to players.

Key entry points
----------------
- ``handle_connection``  — full lifecycle for one WebSocket connection.
- ``handle_message``     — dispatch one parsed JSON action.
- ``broadcast_game_states`` — send each player their personalised view.
- ``abort_room``         — send game_aborted to everyone, clean up.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket, WebSocketDisconnect

from shengji.engine.engine import GameEngine
from shengji.engine.tricks import get_legal_plays, validate_throw
from shengji.models.card import Card, Rank, Suit, SUITED_SUITS
from shengji.models.friend_declaration import FriendDeclaration
from shengji.models.game_state import GamePhase
from shengji.models.groups import Throw, classify_play
from shengji.modes.find_friends import FindFriendsStrategy
from shengji.modes.upgrade import UpgradeStrategy
from shengji.network.room import NUM_PLAYERS, Room, RoomManager

if TYPE_CHECKING:
    from shengji.models.bid import Bid
    from shengji.models.player import Player

# ---------------------------------------------------------------------------
# Available-bids computation
# ---------------------------------------------------------------------------

def compute_available_bids(
    player: "Player",
    trump_rank: Rank,
    current_bid: "Bid | None",
) -> list[dict]:
    """Return bid options the player can currently make.

    Each entry is one of:
      ``{"type": "single",     "suit": "hearts"}``
      ``{"type": "pair",       "suit": "hearts"}``
      ``{"type": "joker_pair", "joker": "small" | "big"}``

    Only bids that would legally overtake *current_bid* are included.
    """
    available: list[dict] = []

    bj = Card(Suit.JOKER, Rank.BIG_JOKER)
    sj = Card(Suit.JOKER, Rank.SMALL_JOKER)

    if player.hand.count(bj) >= 2:
        if GameEngine._can_overtake([bj, bj], player.id, current_bid):
            available.append({"type": "joker_pair", "joker": "big"})

    if player.hand.count(sj) >= 2:
        if GameEngine._can_overtake([sj, sj], player.id, current_bid):
            available.append({"type": "joker_pair", "joker": "small"})

    for suit in SUITED_SUITS:
        tc = Card(suit=suit, rank=trump_rank)
        count = player.hand.count(tc)
        if count >= 2 and GameEngine._can_overtake([tc, tc], player.id, current_bid):
            available.append({"type": "pair", "suit": suit.value})
        if count >= 1 and GameEngine._can_overtake([tc], player.id, current_bid):
            available.append({"type": "single", "suit": suit.value})

    return available


# ---------------------------------------------------------------------------
# Broadcast helpers
# ---------------------------------------------------------------------------

async def broadcast_all(room: Room, msg: dict) -> None:
    """Send the same JSON message to every connected player."""
    for ws in list(room.connections.values()):
        try:
            await ws.send_json(msg)
        except Exception:
            pass  # stale connection; ignore here, cleaned up on disconnect


async def send_to(room: Room, player_id: str, msg: dict) -> None:
    """Send a JSON message to one specific player."""
    ws = room.connections.get(player_id)
    if ws is not None:
        try:
            await ws.send_json(msg)
        except Exception:
            pass


async def send_error(room: Room, player_id: str, message: str) -> None:
    await send_to(room, player_id, {"type": "error", "message": message})


async def broadcast_game_states(room: Room) -> None:
    """Send each player their personalised game state view.

    The view includes ``available_bids`` so clients can enable/disable
    bid buttons without inspecting other players' hands.
    """
    state = room.game_state

    # Determine trump_rank for available_bids computation.
    if state.trump_context is not None:
        trump_rank = state.trump_context.trump_rank
    else:
        leader = next(
            (p for p in state.players if p.id == state.round_leader_id), None
        )
        trump_rank = leader.rank if leader else Rank.TWO

    current_bid = state.bids[-1] if state.bids else None

    for pid, ws in list(room.connections.items()):
        player = next((p for p in state.players if p.id == pid), None)
        if player is None:
            continue
        view: dict[str, Any] = state.to_player_view(pid)
        view["available_bids"] = compute_available_bids(player, trump_rank, current_bid)
        try:
            await ws.send_json({"type": "game_state", **view})
        except Exception:
            pass


async def broadcast_room_update(room: Room) -> None:
    """Broadcast lobby state (players list, mode) to all connected players."""
    msg = {
        "type": "room_update",
        "room_id": room.room_id,
        "game_master_id": room.game_master_id,
        "mode": room.game_state.mode,
        "players": [
            {"id": p.id, "name": p.name}
            for p in room.game_state.players
        ],
    }
    await broadcast_all(room, msg)


# ---------------------------------------------------------------------------
# Game lifecycle helpers
# ---------------------------------------------------------------------------

def _make_strategy(mode: str):
    """Instantiate the correct ModeStrategy for *mode*."""
    if mode == "upgrade":
        return UpgradeStrategy()
    return FindFriendsStrategy()


async def start_and_deal(
    room: Room, manager: RoomManager, deal_delay: float
) -> None:
    """Set up the engine and deal all cards for a new round.

    This coroutine is launched as an asyncio background task from the
    WebSocket handler so it runs concurrently with message processing.
    """
    strategy = _make_strategy(room.game_state.mode)
    room.engine = GameEngine(
        room.game_state, strategy, deal_delay=deal_delay
    )
    room.engine.start_dealing()
    room.passed_in_bidding.clear()
    await broadcast_game_states(room)

    async def on_card_dealt(player_id: str, card: Card) -> None:
        # Send the card to the recipient only.
        await send_to(room, player_id, {
            "type": "card_dealt",
            "card": card.to_json(),
        })
        # Broadcast updated state/available_bids to all.
        await broadcast_game_states(room)

    await room.engine.deal_all_cards(on_card_dealt=on_card_dealt)
    # Phase is now BIDDING_AFTER_DEAL.
    await broadcast_game_states(room)


async def handle_round_end(
    room: Room, manager: RoomManager, deal_delay: float
) -> None:
    """Score the round and start the next one (or end the game)."""
    try:
        result = room.engine.end_round()
    except ValueError as exc:
        await broadcast_all(room, {"type": "error", "message": str(exc)})
        return

    await broadcast_all(room, {
        "type": "round_over",
        "attacking_points": result["attacking_points"],
        "winner": result["winner"],
        "steps": result["steps"],
        "game_over": result["game_over"],
    })
    await broadcast_game_states(room)

    if result["game_over"]:
        await broadcast_all(room, {
            "type": "game_over",
            "winner": result["winner"],
        })
        manager.remove_room(room.room_id)
        return

    # Start the next round automatically.
    asyncio.create_task(start_and_deal(room, manager, deal_delay))


async def abort_room(room: Room, manager: RoomManager, reason: str) -> None:
    """Send game_aborted to all players, close connections, destroy room."""
    msg = {"type": "game_aborted", "reason": reason}
    for ws in list(room.connections.values()):
        try:
            await ws.send_json(msg)
            await ws.close()
        except Exception:
            pass
    room.connections.clear()
    manager.remove_room(room.room_id)


# ---------------------------------------------------------------------------
# Incoming action dispatch
# ---------------------------------------------------------------------------

def _cards_from_json(card_list: list[dict]) -> list[Card]:
    return [Card.from_json(c) for c in card_list]


async def handle_message(
    room: Room,
    player_id: str,
    data: dict,
    manager: RoomManager,
    deal_delay: float,
) -> None:
    """Dispatch one incoming WebSocket action to the correct engine method."""
    action = data.get("action")
    state = room.game_state
    engine = room.engine

    try:
        # ── Lobby actions (no engine needed) ────────────────────────────

        if action == "select_mode":
            if player_id != room.game_master_id:
                await send_error(room, player_id, "Only the game master can select the mode.")
                return
            mode = data.get("mode")
            if mode not in ("upgrade", "find_friends"):
                await send_error(room, player_id, f"Unknown mode: {mode!r}")
                return
            state.mode = mode
            await broadcast_room_update(room)
            # Auto-start if all 4 players are already connected.
            if (
                len(state.players) == NUM_PLAYERS
                and state.phase == GamePhase.WAITING
            ):
                asyncio.create_task(start_and_deal(room, manager, deal_delay))

        # ── Bidding ──────────────────────────────────────────────────────

        elif action == "bid":
            if engine is None:
                await send_error(room, player_id, "Game has not started yet.")
                return
            trump_rank = engine._player(state.round_leader_id).rank

            if "suit" in data:
                suit = Suit(data["suit"])
                tc = Card(suit=suit, rank=trump_rank)
                count = engine._player(player_id).hand.count(tc)
                if count >= 2:
                    bid_cards = [tc, tc]
                elif count >= 1:
                    bid_cards = [tc]
                else:
                    await send_error(
                        room, player_id,
                        f"You do not hold a trump-rank {suit.value} card."
                    )
                    return
            elif "joker" in data:
                joker_type = data["joker"]
                jc = Card(
                    Suit.JOKER,
                    Rank.BIG_JOKER if joker_type == "big" else Rank.SMALL_JOKER,
                )
                bid_cards = [jc, jc]
            else:
                await send_error(room, player_id, "Bid must specify 'suit' or 'joker'.")
                return

            engine.place_bid(player_id, bid_cards)
            # Reset pass tracking so all must pass again to close bidding.
            room.passed_in_bidding.clear()
            await broadcast_game_states(room)

        elif action == "pass_bid":
            if state.phase != GamePhase.BIDDING_AFTER_DEAL:
                await send_error(room, player_id, "You can only pass during BIDDING_AFTER_DEAL.")
                return
            room.passed_in_bidding.add(player_id)
            if len(room.passed_in_bidding) >= NUM_PLAYERS:
                engine.close_bidding()
                room.passed_in_bidding.clear()
                await broadcast_game_states(room)
                # If close_bidding triggered a re-deal, engine has already
                # called start_dealing() internally; re-run the deal loop.
                if state.phase == GamePhase.DEALING:
                    asyncio.create_task(start_and_deal(room, manager, deal_delay))

        elif action == "close_bidding":
            # Game master manually closes bidding.
            if player_id != room.game_master_id:
                await send_error(room, player_id, "Only the game master can close bidding.")
                return
            if engine is None or state.phase not in (
                GamePhase.BIDDING_AFTER_DEAL, GamePhase.DEALING
            ):
                await send_error(room, player_id, "Cannot close bidding now.")
                return
            engine.close_bidding()
            room.passed_in_bidding.clear()
            await broadcast_game_states(room)
            if state.phase == GamePhase.DEALING:
                asyncio.create_task(start_and_deal(room, manager, deal_delay))

        # ── Bottom exchange ───────────────────────────────────────────────

        elif action == "exchange_bottom":
            if engine is None:
                await send_error(room, player_id, "Game has not started yet.")
                return
            cards = _cards_from_json(data.get("cards_to_put_back", []))
            engine.exchange_bottom(player_id, cards)
            await broadcast_game_states(room)

        # ── Friend declaration ────────────────────────────────────────────

        elif action == "declare_friends":
            if engine is None:
                await send_error(room, player_id, "Game has not started yet.")
                return
            raw_decls = data.get("declarations", [])
            declarations = [
                FriendDeclaration(
                    card=Card.from_json(d["card"]),
                    ordinal=d["ordinal"],
                )
                for d in raw_decls
            ]
            engine.declare_friends(player_id, declarations)
            await broadcast_game_states(room)

        # ── Playing a trick ───────────────────────────────────────────────

        elif action == "play_cards":
            if engine is None:
                await send_error(room, player_id, "Game has not started yet.")
                return
            cards = _cards_from_json(data.get("cards", []))
            result = engine.play_cards(player_id, cards)
            await broadcast_game_states(room)
            if result.get("round_over"):
                await handle_round_end(room, manager, deal_delay)

        # ── Read-only play validation ──────────────────────────────────────

        elif action == "validate_play":
            if engine is None:
                await send_error(room, player_id, "Game has not started yet.")
                return
            cards = _cards_from_json(data.get("cards", []))
            ctx = state.trump_context
            player_obj = engine._player(player_id)
            is_leader = len(state.current_trick) == 0
            try:
                if is_leader:
                    led_fmt = classify_play(cards, ctx)
                    if isinstance(led_fmt, Throw):
                        all_hands = {p.id: p.hand for p in state.players}
                        if not validate_throw(cards, player_id, all_hands, ctx):
                            raise ValueError("Invalid throw: a component can be beaten by an opponent.")
                else:
                    led_fmt = getattr(state, "_led_format", None)
                    led_suit = getattr(state, "_led_suit", None)
                    legal = get_legal_plays(player_obj.hand, led_fmt, led_suit, ctx)
                    # Check if the proposed play matches any legal option
                    from shengji.engine.engine import _cards_match_any
                    if not _cards_match_any(cards, legal):
                        raise ValueError("That play is not legal given the led format.")
                await send_to(room, player_id, {"type": "play_valid"})
            except ValueError as exc:
                await send_to(room, player_id, {
                    "type": "play_invalid",
                    "reason": str(exc),
                })

        # ── Unknown action ────────────────────────────────────────────────

        else:
            await send_error(room, player_id, f"Unknown action: {action!r}")

    except ValueError as exc:
        # Engine validation failures are non-fatal; report to the player.
        await send_error(room, player_id, str(exc))


# ---------------------------------------------------------------------------
# Full connection lifecycle
# ---------------------------------------------------------------------------

async def handle_connection(
    ws: WebSocket,
    room_id: str,
    player_id: str,
    manager: RoomManager,
    deal_delay: float,
) -> None:
    """Drive the full lifecycle of one WebSocket connection.

    Called from the FastAPI route handler.
    """
    await ws.accept()

    room = manager.get_room(room_id)
    if room is None:
        await ws.send_json({"type": "error", "message": f"Room {room_id!r} not found."})
        await ws.close()
        return

    player = next(
        (p for p in room.game_state.players if p.id == player_id), None
    )
    if player is None:
        await ws.send_json({"type": "error", "message": "Player not found in room."})
        await ws.close()
        return

    # Register connection.
    room.connections[player_id] = ws

    # Bring the newly connected player up to speed.
    await broadcast_room_update(room)
    await broadcast_game_states(room)

    # Auto-start: 4 players + mode already selected.
    state = room.game_state
    if (
        len(state.players) == NUM_PLAYERS
        and state.mode is not None
        and state.phase == GamePhase.WAITING
        and room.engine is None
    ):
        asyncio.create_task(start_and_deal(room, manager, deal_delay))

    try:
        while True:
            data = await ws.receive_json()
            await handle_message(room, player_id, data, manager, deal_delay)
    except WebSocketDisconnect:
        room.connections.pop(player_id, None)
        await abort_room(room, manager, "A player disconnected.")
    except Exception:
        room.connections.pop(player_id, None)
        await abort_room(room, manager, "An unexpected error occurred.")
