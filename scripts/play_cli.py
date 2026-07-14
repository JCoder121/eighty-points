#!/usr/bin/env python
"""Terminal harness for the Shengji engine — no server, no frontend.

Drives GameEngine directly so hands can be reproduced with a seed and full
games can be fuzzed by random-legal-move bots.

Usage
-----
  python scripts/play_cli.py --seed 42                 # interactive, you play all 4 seats
  python scripts/play_cli.py --seed 42 --human 0       # you play seat 0, bots play the rest
  python scripts/play_cli.py --seed 42 --bots          # one full bot game, verbose
  python scripts/play_cli.py --bots --games 200        # fuzz seeds 0..199, report failures
  python scripts/play_cli.py --bots --mode find_friends --games 50

Every engine action is followed by a superuser validate_state() sweep;
violations are reported with the seed / round / trick needed to reproduce.
"""
from __future__ import annotations

import argparse
import random
import sys
import traceback
from collections import Counter

from shengji.engine.engine import GameEngine
from shengji.engine.tricks import get_legal_plays
from shengji.models.card import Card, Rank, Suit, RANK_ORDER, SUITED_SUITS
from shengji.models.deck import NUM_PLAYERS
from shengji.models.friend_declaration import FriendDeclaration
from shengji.models.game_state import GamePhase, GameState
from shengji.models.groups import Throw, classify_play, find_tractors
from shengji.models.player import Player
from shengji.modes.find_friends import FindFriendsStrategy
from shengji.modes.upgrade import UpgradeStrategy
from shengji.superuser.inspector import validate_state

MAX_REDEALS = 10


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def card_str(c: Card) -> str:
    return repr(c)


def hand_str(cards: list[Card], ctx=None) -> str:
    ordered = sorted(cards, key=ctx.card_order) if ctx else list(cards)
    return " ".join(f"{i}:{card_str(c)}" for i, c in enumerate(ordered))


def sorted_hand(cards: list[Card], ctx=None) -> list[Card]:
    return sorted(cards, key=ctx.card_order) if ctx else list(cards)


class Reporter:
    """Collects invariant violations and prints game narration."""

    def __init__(self, verbose: bool):
        self.verbose = verbose
        self.violations: list[str] = []

    def say(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    def check(self, state: GameState, where: str) -> None:
        for v in validate_state(state):
            self.violations.append(f"[{where}] {v}")


# ---------------------------------------------------------------------------
# Bot policy — random legal moves
# ---------------------------------------------------------------------------

class Bot:
    def __init__(self, rng: random.Random):
        self.rng = rng

    # -- bidding -----------------------------------------------------------
    def bid_options(self, hand: list[Card], trump_rank: Rank) -> list[list[Card]]:
        opts: list[list[Card]] = []
        by_suit = Counter(c.suit for c in hand if c.rank == trump_rank)
        for suit, n in by_suit.items():
            card = Card(suit=suit, rank=trump_rank)
            opts.append([card])
            if n >= 2:
                opts.append([card, card])
        for jr in (Rank.SMALL_JOKER, Rank.BIG_JOKER):
            if sum(1 for c in hand if c.rank == jr) >= 2:
                j = Card(suit=Suit.JOKER, rank=jr)
                opts.append([j, j])
        return opts

    def maybe_bid(self, engine: GameEngine, player: Player, force: bool) -> bool:
        state = engine.state
        trump_rank = next(
            p.rank for p in state.players if p.id == state.round_leader_id
        )
        current = state.bids[-1] if state.bids else None
        opts = [
            o
            for o in self.bid_options(player.hand, trump_rank)
            if GameEngine._can_overtake(o, player.id, current)
        ]
        if not opts:
            return False
        if not force and self.rng.random() > 0.8:
            return False
        engine.place_bid(player.id, self.rng.choice(opts))
        return True

    # -- friend declaration --------------------------------------------------
    def declare(self, engine: GameEngine) -> None:
        state = engine.state
        ctx = state.trump_context
        candidates = [
            Card(suit=s, rank=r)
            for s in SUITED_SUITS
            for r in RANK_ORDER
            if r != ctx.trump_rank and (ctx.trump_suit is None or s != ctx.trump_suit)
        ]
        decl = FriendDeclaration(
            card=self.rng.choice(candidates),
            ordinal=self.rng.choice([1, 1, 1, 2]),
        )
        engine.declare_friends(state.round_leader_id, [decl])

    # -- bottom exchange -----------------------------------------------------
    def exchange(self, engine: GameEngine) -> None:
        state = engine.state
        leader = next(p for p in state.players if p.id == state.round_leader_id)
        combined = list(leader.hand) + list(state.bottom_deck)
        engine.exchange_bottom(state.round_leader_id, self.rng.sample(combined, 8))

    # -- playing -------------------------------------------------------------
    def lead_options(self, hand: list[Card], ctx) -> list[list[Card]]:
        opts: list[list[Card]] = [[c] for c in hand]
        counts = Counter(hand)
        opts += [[c, c] for c, n in counts.items() if n >= 2]
        opts += find_tractors(hand, ctx)
        return opts

    def choose_play(self, engine: GameEngine, player: Player) -> list[Card]:
        state = engine.state
        ctx = state.trump_context
        if not state.current_trick:  # leading
            # Occasionally attempt a throw (may be rejected — caller handles).
            if self.rng.random() < 0.08:
                suits = {ctx.effective_suit(c) for c in player.hand}
                suit = self.rng.choice(sorted(suits))
                suited = [c for c in player.hand if ctx.effective_suit(c) == suit]
                if len(suited) >= 2:
                    k = self.rng.randint(2, min(6, len(suited)))
                    cand = self.rng.sample(suited, k)
                    if isinstance(classify_play(cand, ctx), Throw):
                        return cand
            opts = self.lead_options(player.hand, ctx)
            weights = [3 if len(o) > 1 else 1 for o in opts]  # prefer pairs/tractors a bit
            return self.rng.choices(opts, weights=weights, k=1)[0]
        led_fmt = getattr(state, "_led_format", None)
        led_suit = getattr(state, "_led_suit", None)
        legal = get_legal_plays(player.hand, led_fmt, led_suit, ctx)
        if not legal:
            raise RuntimeError(
                f"get_legal_plays returned no options for {player.id} "
                f"(hand={player.hand}, led={led_fmt}, suit={led_suit})"
            )
        return self.rng.choice(legal)


# ---------------------------------------------------------------------------
# Interactive input
# ---------------------------------------------------------------------------

def prompt_cards(player: Player, ctx, prompt: str) -> list[Card] | None:
    """Ask for space-separated indices into the sorted hand. None = auto."""
    hand = sorted_hand(player.hand, ctx)
    print(f"\n  {player.name} hand: {hand_str(player.hand, ctx)}")
    while True:
        raw = input(f"  {prompt} (indices / 'a' auto / 'q' quit): ").strip().lower()
        if raw == "q":
            raise KeyboardInterrupt
        if raw in ("a", ""):
            return None
        try:
            idxs = [int(t) for t in raw.split()]
            if len(set(idxs)) != len(idxs):
                raise ValueError
            return [hand[i] for i in idxs]
        except (ValueError, IndexError):
            print("  Invalid input — space-separated card indices, e.g. '0 1'.")


# ---------------------------------------------------------------------------
# Game driver
# ---------------------------------------------------------------------------

class GameRunner:
    def __init__(self, seed: int, mode: str, human_seats: set[int], verbose: bool,
                 max_rounds: int):
        self.seed = seed
        self.rng = random.Random(seed)
        self.bot = Bot(self.rng)
        self.human_seats = human_seats
        self.max_rounds = max_rounds
        self.rep = Reporter(verbose)

        players = [Player(id=f"p{i}", name=f"P{i}") for i in range(NUM_PLAYERS)]
        strategy = FindFriendsStrategy() if mode == "find_friends" else UpgradeStrategy()
        self.state = GameState(players=players, mode=mode, round_leader_id="p0")
        self.engine = GameEngine(self.state, strategy, deal_delay=0, rng=self.rng)

    def is_human(self, player_id: str) -> bool:
        return int(player_id[1:]) in self.human_seats

    def player(self, pid: str) -> Player:
        return next(p for p in self.state.players if p.id == pid)

    # -- phases ------------------------------------------------------------
    def run_dealing_and_bidding(self) -> None:
        state, engine = self.state, self.engine
        for redeal in range(MAX_REDEALS):
            engine.start_dealing()
            while engine.deal_next_card() is not None:
                pass
            self.rep.check(state, f"r{state.round_number} after deal")
            trump_rank = self.player(state.round_leader_id).rank
            self.rep.say(f"\n=== Round {state.round_number} — trump rank {trump_rank.value} "
                         f"(leader {state.round_leader_id}) ===")

            order = list(state.players)
            self.rng.shuffle(order)
            for i, p in enumerate(order):
                if self.is_human(p.id):
                    self._human_bid(p, trump_rank)
                else:
                    # Force the last eligible bot to bid on the final redeal attempt
                    force = redeal == MAX_REDEALS - 1 and i == len(order) - 1 and not state.bids
                    if self.bot.maybe_bid(engine, p, force):
                        self.rep.say(f"  {p.name} bids {[card_str(c) for c in state.bids[-1].cards]}")
            engine.close_bidding()
            if state.phase != GamePhase.DEALING:  # bid placed — done
                ctx = state.trump_context
                suit = ctx.trump_suit.value if ctx.trump_suit else "NO-TRUMP"
                self.rep.say(f"  Trump: {suit} rank {ctx.trump_rank.value}; "
                             f"round leader {state.round_leader_id}")
                return
            self.rep.say("  All passed — re-dealing.")
        raise RuntimeError(f"No bid after {MAX_REDEALS} re-deals (seed {self.seed})")

    def _human_bid(self, p: Player, trump_rank: Rank) -> None:
        print(f"\n[BIDDING] trump rank is {trump_rank.value}; current bid: "
              f"{[card_str(c) for c in self.state.bids[-1].cards] if self.state.bids else 'none'}")
        cards = prompt_cards(p, self.state.trump_context, f"{p.name} bid (or 'a' to pass)")
        if cards:
            try:
                self.engine.place_bid(p.id, cards)
                print(f"  {p.name} bids {[card_str(c) for c in cards]}")
            except ValueError as e:
                print(f"  Rejected: {e}")
                self._human_bid(p, trump_rank)

    def run_friend_declaration(self) -> None:
        if self.state.phase != GamePhase.FRIEND_DECLARATION:
            return
        leader = self.player(self.state.round_leader_id)
        if self.is_human(leader.id):
            while True:
                raw = input(f"  {leader.name} declare friend card as RANK SUIT ORDINAL "
                            "(e.g. 'A spades 1', 'a' auto): ").strip().lower()
                if raw in ("a", ""):
                    self.bot.declare(self.engine)
                    break
                try:
                    rank_s, suit_s, ord_s = raw.split()
                    decl = FriendDeclaration(
                        card=Card(suit=Suit(suit_s), rank=Rank(rank_s.upper())),
                        ordinal=int(ord_s),
                    )
                    self.engine.declare_friends(leader.id, [decl])
                    break
                except (ValueError, KeyError) as e:
                    print(f"  Rejected: {e}")
        else:
            self.bot.declare(self.engine)
        decls = self.state.friend_declarations
        self.rep.say("  Friend declared: " + ", ".join(
            f"{card_str(d.card)} (#{d.ordinal})" for d in decls))

    def run_exchange(self) -> None:
        state = self.state
        leader = self.player(state.round_leader_id)
        if self.is_human(leader.id):
            combined = leader.hand + state.bottom_deck
            print(f"\n[EXCHANGE] bottom picked up: "
                  f"{' '.join(card_str(c) for c in state.bottom_deck)}")
            tmp = Player(id=leader.id, name=leader.name)
            tmp.hand = combined
            while True:
                cards = prompt_cards(tmp, state.trump_context, "bury exactly 8")
                if cards is None:
                    self.bot.exchange(self.engine)
                    break
                try:
                    self.engine.exchange_bottom(leader.id, cards)
                    break
                except ValueError as e:
                    print(f"  Rejected: {e}")
        else:
            self.bot.exchange(self.engine)
        self.rep.check(state, f"r{state.round_number} after exchange")

    def run_tricks(self) -> None:
        state, engine = self.state, self.engine
        while state.phase == GamePhase.PLAYING:
            pid = state.current_turn_id
            player = self.player(pid)
            leading = not state.current_trick
            if self.is_human(pid):
                role = "LEAD" if leading else "follow"
                trick = "  ".join(f"{q}:{' '.join(card_str(c) for c in cs)}"
                                  for q, cs in state.current_trick)
                if trick:
                    print(f"\n[TRICK {state.trick_number}] so far: {trick}")
                cards = prompt_cards(player, state.trump_context, f"{player.name} {role}")
                if cards is None:
                    cards = self.bot.choose_play(engine, player)
                try:
                    result = engine.play_cards(pid, cards)
                except ValueError as e:
                    print(f"  Rejected: {e}")
                    continue
            else:
                cards = self.bot.choose_play(engine, player)
                try:
                    result = engine.play_cards(pid, cards)
                except ValueError as e:
                    if leading:
                        # Bot throw attempt rejected — legitimate; lead a single instead.
                        cards = [self.rng.choice(player.hand)]
                        result = engine.play_cards(pid, cards)
                    else:
                        # get_legal_plays produced a play is_valid_follow rejects —
                        # by definition an engine inconsistency. Record and try the
                        # remaining legal options so the fuzz run can continue.
                        led_fmt = getattr(state, "_led_format", None)
                        led_suit = getattr(state, "_led_suit", None)
                        self.rep.violations.append(
                            f"[r{state.round_number} t{state.trick_number}] "
                            f"get_legal_plays/is_valid_follow disagree: {pid} "
                            f"play={[card_str(c) for c in cards]} led={led_fmt} "
                            f"led_suit={led_suit} hand={[card_str(c) for c in sorted_hand(player.hand, state.trump_context)]} "
                            f"err={e}"
                        )
                        result = None
                        for alt in get_legal_plays(player.hand, led_fmt, led_suit,
                                                   state.trump_context):
                            try:
                                cards = alt
                                result = engine.play_cards(pid, alt)
                                break
                            except ValueError:
                                continue
                        if result is None:
                            raise
            self.rep.say(f"  {player.name}: {' '.join(card_str(c) for c in cards)}")
            self.rep.check(state, f"r{state.round_number} t{state.trick_number} after {pid}")
            if result["trick_complete"]:
                self.rep.say(f"  -> trick to {result['trick_winner']} "
                             f"(attacking pts {state.attacking_points})")

    def run_game(self) -> dict:
        state, engine = self.state, self.engine
        for _ in range(self.max_rounds):
            self.run_dealing_and_bidding()
            self.run_friend_declaration()
            self.run_exchange()
            self.run_tricks()
            summary = engine.end_round()
            self.rep.check(state, f"r{state.round_number - 1} after end_round")
            self.rep.say(f"\n  ROUND RESULT: {summary['winner']} wins, "
                         f"attacking pts {summary['attacking_points']}, "
                         f"steps {summary['steps']}")
            for rp in summary["round_players"]:
                self.rep.say(f"    {rp['name']}: {rp['old_rank']} -> {rp['rank']}"
                             f"{'  (defending)' if rp['is_defending'] else ''}")
            if summary["game_over"]:
                self.rep.say("\n  GAME OVER")
                return {"game_over": True, "rounds": state.round_number - 1}
        return {"game_over": False, "rounds": self.max_rounds}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=None,
                    help="RNG seed (deals + bot choices); random if omitted")
    ap.add_argument("--mode", choices=["upgrade", "find_friends"], default="upgrade")
    ap.add_argument("--bots", action="store_true", help="all seats bot-played")
    ap.add_argument("--human", type=int, default=None, metavar="SEAT",
                    help="play only this seat (0-3); other seats are bots")
    ap.add_argument("--games", type=int, default=1,
                    help="with --bots: run N games on seeds seed..seed+N-1")
    ap.add_argument("--max-rounds", type=int, default=30)
    ap.add_argument("--quiet", action="store_true", help="only print failures/summary")
    args = ap.parse_args()

    base_seed = args.seed if args.seed is not None else random.randrange(10**6)
    if args.bots:
        human_seats: set[int] = set()
    elif args.human is not None:
        human_seats = {args.human}
    else:
        human_seats = {0, 1, 2, 3}

    if not args.bots and args.games > 1:
        ap.error("--games requires --bots")

    failures = []
    for i in range(args.games):
        seed = base_seed + i
        verbose = not args.quiet and (args.games == 1 or not args.bots)
        runner = GameRunner(seed, args.mode, human_seats, verbose, args.max_rounds)
        if verbose or args.games == 1:
            print(f"seed={seed} mode={args.mode}")
        try:
            result = runner.run_game()
            status = "game_over" if result["game_over"] else f"{result['rounds']} rounds"
            if runner.rep.violations:
                failures.append((seed, "invariant", runner.rep.violations))
                print(f"FAIL seed={seed}: {len(runner.rep.violations)} invariant violations")
                for v in runner.rep.violations[:5]:
                    print(f"    {v}")
            elif not args.quiet:
                print(f"OK   seed={seed}: {status}")
        except KeyboardInterrupt:
            print("\nQuit.")
            return 130
        except Exception:
            failures.append((seed, "crash", traceback.format_exc()))
            print(f"FAIL seed={seed}: CRASH")
            print("    " + traceback.format_exc().replace("\n", "\n    "))
            for v in runner.rep.violations:
                print(f"    recorded: {v}")

    if args.games > 1:
        print(f"\n{args.games - len(failures)}/{args.games} games clean")
        if failures:
            print("Failing seeds: " + ", ".join(str(s) for s, _, _ in failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
