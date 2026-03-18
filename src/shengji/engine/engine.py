"""GameEngine — shared game loop for both Upgrade and Find Friends modes.

The engine is the single source of mutation for GameState.  It validates
every incoming action, applies the change, and returns a list of events
that the network layer can broadcast.

Usage
-----
    engine = GameEngine(state, mode_strategy)
    await engine.start_dealing(broadcast_fn)

Each action method is *synchronous* except start_dealing, which drives the
async deal loop.  Callers supply a broadcast callback so the engine stays
decoupled from WebSocket details.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Callable, Awaitable

from shengji.models.deck import Deck, NUM_PLAYERS, BOTTOM_SIZE, HAND_SIZE
from shengji.models.game_state import GamePhase, GameState
from shengji.models.card import Card

if TYPE_CHECKING:
    from shengji.modes.base import ModeStrategy

# Seconds to wait between dealing individual cards.  0 in tests; ~0.5 in prod.
DEAL_DELAY_SECONDS: float = 0.5

# ---------------------------------------------------------------------------
# Event helpers
# ---------------------------------------------------------------------------

def _event(kind: str, **data) -> dict:
    return {"event": kind, **data}


# ---------------------------------------------------------------------------
# GameEngine
# ---------------------------------------------------------------------------

class GameEngine:
    """Drives a single game session.

    Parameters
    ----------
    state:
        The mutable GameState shared by all players.
    mode_strategy:
        Injected strategy for Upgrade vs. Find Friends differences.
    deal_delay:
        Seconds between each dealt card.  Override to 0 in tests.
    """

    def __init__(
        self,
        state: GameState,
        mode_strategy: "ModeStrategy",
        deal_delay: float = DEAL_DELAY_SECONDS,
    ) -> None:
        self.state = state
        self.mode = mode_strategy
        self.deal_delay = deal_delay

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _player(self, player_id: str):
        """Return the Player with this id, or raise ValueError."""
        for p in self.state.players:
            if p.id == player_id:
                return p
        raise ValueError(f"Unknown player_id: {player_id!r}")

    def _next_player_id(self, after_id: str) -> str:
        """Return the player_id seated counter-clockwise from *after_id*.

        Players are stored in counter-clockwise order, so the next player
        is simply index + 1 (mod NUM_PLAYERS).
        """
        ids = [p.id for p in self.state.players]
        idx = ids.index(after_id)
        return ids[(idx + 1) % NUM_PLAYERS]

    # ------------------------------------------------------------------
    # Dealing
    # ------------------------------------------------------------------

    def start_dealing(self) -> None:
        """Synchronous portion of deal setup.

        Validates preconditions, shuffles a new deck, stores the draw pile
        and bottom on the GameState, and transitions to DEALING.

        The actual card-by-card loop is driven by deal_all_cards(), which is
        async so it can sleep between cards.  Separating the two lets unit
        tests exercise start_dealing without needing an event loop.

        Raises
        ------
        ValueError
            If the game mode is not set or the phase is wrong.
        """
        state = self.state
        if state.mode is None:
            raise ValueError("Game mode must be set before dealing starts.")
        if state.phase not in (GamePhase.WAITING, GamePhase.ROUND_OVER):
            state.transition_to(GamePhase.DEALING)  # will raise if illegal

        deck = Deck()
        draw_pile, bottom_deck = deck.prepare_deal()

        state.draw_pile = list(draw_pile)
        state.bottom_deck = list(bottom_deck)
        state.cards_dealt_count = 0

        # Clear per-round fields
        state.bids = []
        state.trump_context = None
        state.current_trick = []
        state.tricks_won = {p.id: [] for p in state.players}
        state.attacking_points = 0
        state.trick_number = 1
        state.current_leader_id = state.round_leader_id
        state.current_turn_id = ""  # not used during dealing

        state.transition_to(GamePhase.DEALING)

    def deal_next_card(self) -> tuple[str, Card] | None:
        """Pop one card from the draw pile and add it to the next player's hand.

        Cards are dealt counter-clockwise starting from the player *after* the
        round leader.

        Returns
        -------
        (player_id, card)
            The recipient and the card they received.
        None
            When the draw pile is exhausted (all 100 cards have been dealt).

        Side effects
        ------------
        Increments state.cards_dealt_count.  When the draw pile empties,
        transitions phase to BIDDING_AFTER_DEAL.
        """
        state = self.state
        if not state.draw_pile:
            return None

        # Determine which player receives this card.
        # Deal order: start from the player after the round leader,
        # cycling counter-clockwise.  cards_dealt_count tells us whose turn it is.
        ids = [p.id for p in state.players]
        round_leader_idx = ids.index(state.round_leader_id)
        recipient_idx = (round_leader_idx + 1 + state.cards_dealt_count) % NUM_PLAYERS
        recipient_id = ids[recipient_idx]

        card = state.draw_pile.pop(0)
        self._player(recipient_id).hand.append(card)
        state.cards_dealt_count += 1

        if not state.draw_pile:
            state.transition_to(GamePhase.BIDDING_AFTER_DEAL)

        return recipient_id, card

    async def deal_all_cards(
        self,
        on_card_dealt: Callable[[str, Card], Awaitable[None]] | None = None,
    ) -> None:
        """Async loop that deals all 100 cards one at a time.

        Parameters
        ----------
        on_card_dealt:
            Optional async callback invoked after each card is dealt.
            Receives (player_id, card).  Use this to push 'card_dealt' events
            over WebSocket.
        """
        while self.state.draw_pile:
            result = self.deal_next_card()
            if result is None:
                break
            player_id, card = result
            if on_card_dealt is not None:
                await on_card_dealt(player_id, card)
            if self.state.draw_pile:
                await asyncio.sleep(self.deal_delay)
