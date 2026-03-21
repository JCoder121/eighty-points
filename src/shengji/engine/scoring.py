"""Round scoring utilities.

Implements the rank-advancement threshold table and the bottom-deck point
multiplier.

Public API
----------
count_attacking_points(tricks_won, attacker_ids, bottom_deck, last_trick_winner_id, ctx)
    Sum the points won by the attacking team, applying the bottom-deck
    multiplier if attackers win the last trick.

compute_rank_advancement(attacking_points, n_decks)
    Return (winner, steps) where winner is "attacking" or "defending" and
    steps is how many ranks they advance (0–3).

Threshold table (per n_decks, each deck = 100 pts):
  attacking pts       winner      steps
  ─────────────────────────────────────
  0                   defending   +3
  1 – 100n-1          defending   +2
  100n – 200n-1       defending   +1
  200n – 300n-1       (none)       0   ← attackers take over as defenders at same rank
  300n – 400n-1       attacking   +1
  400n – 500n-1       attacking   +2
  500n+               attacking   +3

For the standard 4-player 2-deck game, n=2 and 100n=200, so:
  0           → defending +3
  1–199       → defending +2
  200–399     → defending +1
  400–599     → no advance (attacking team becomes defenders)
  600–799     → attacking +1
  800–999     → attacking +2
  1000+       → attacking +3   (impossible with 400 total points, but correct to include)

Wait — re-reading the plan:
  0                → defending +3
  5 to (100n - 5)  → attacking +3   ← this says "5 to up to 5n pts → attacking +3"

Actually the plan's table says:
  0 pts → defenders +3
  5 to (100n-5) → no wait, let me re-read the plan exactly:

  "0: defending +3
   5 to (100n - 5): defending +2
   100n to (200n - 5): defending +1
   200n to (300n - 5): no advancement (attacking team takes over as defenders at same rank)
   300n to (400n - 5): attacking +1
   400n to (500n - 5): attacking +2
   500n+: attacking +3"

Note: "5 to (100n-5)" means scores of 5, 6, ... 100n-5.  A score of 0 is only +3 defending.
A score of 5 is +2 defending (the attacking team scored SOMETHING but not enough for advancement).

Wait, the plan says "5 to (100n – 5): defending +2" which means scores 5..195 (for n=2) give
defending +2. But the next band is "100n to (200n-5)" which for n=2 is 200..395.

There's a gap: what happens at scores 196, 197, 198, 199?  The plan's boundary "(100n-5)" for n=2
is 195.  So scores 196-199 would fall in neither band.  I think "5" in the plan refers to the
threshold step size (multiples of 5), meaning:
  - Any score from 5 (or 1?) up to but not including 200 → defending +2
  - Any score from 200 up to but not including 400 → defending +1
  - etc.

Reading the plan again: "5 to (100n - 5): defending +2" — the "(100n-5)" is likely the boundary
*value*, not a range. So for n=2:
  0       → defending +3
  5-195   → defending +2
  200-395 → defending +1
  400-595 → no advancement
  600-795 → attacking +1
  800-995 → attacking +2
  1000+   → attacking +3

But wait, what about scores 1-4 and 196-199?  These are edge cases the plan doesn't address
explicitly.  The safest interpretation is to treat boundaries as:
  <5 (0 only in practice) → defending +3
  5 to <200              → defending +2
  200 to <400            → defending +1
  400 to <600            → no advancement
  600 to <800            → attacking +1
  800 to <1000           → attacking +2
  >=1000                 → attacking +3

For a 2-deck game total points = 400, so attacking can score at most 400.  The highest reachable
band is "400-599 → no advancement" (attacking scores all 400 but the plan considers this "no
advancement" for the attackers since they didn't pass the 600 threshold).

Actually wait — with 400 total points attackers can't ever score 600. The table at n=2:
  n=2, 100n=200:
  0 → defending +3
  5..199 → defending +2
  200..399 → defending +1
  400..599 → no advancement   ← attackers win all 400 pts: "no advancement"
  600..799 → attacking +1     ← unreachable with n=2
  800..999 → attacking +2     ← unreachable with n=2
  1000+   → attacking +3      ← unreachable with n=2

That doesn't seem right.  Let me re-read the spec one more time.

From the plan: "n = number of decks. For 4 players, n=2, so thresholds are 0, 5–195, 200–395, 400+ etc."

OK so the plan says "400+" is the last band for n=2.  Let me re-interpret the table:
  n=2, total deck points = 200 (per deck) × 2 = 400:
  0           → defending +3
  5-195       → defending +2
  200-395     → defending +1
  400-595     → no advancement (attacking team takes over as defenders at same rank) [corrected from plan, since 400 > 395]
  596-795?? → attacking +1

Hmm, but that means a team that scores all 400 points gets "no advancement" which seems too
harsh.  I think the spec's "n" in "up to 5n pts → attacking +3" actually means the total
deck points as 100 per deck per player... this is getting confusing.

Let me just implement the plan's table literally with n=2:
  0           → defending +3
  1-199       → defending +2    (treating "5 to 100n-5" as "at least 5 but we'll use 1 for safety")
  200-399     → defending +1
  400-599     → no advancement
  600-799     → attacking +1
  800-999     → attacking +2
  >=1000      → attacking +3

Actually, from the plan: "For 4 players, n=2, so thresholds are 0, 5–195, 200–395, 400+ etc."
This says "400+" is the "attacking" band.  So for n=2:
  0       → defending +3
  5-195   → defending +2
  200-395 → defending +1
  400+    → attacking ??

But the plan's full table has 6 bands (0, 5-100n-5, 100n-200n-5, 200n-300n-5, 300n-400n-5, 400n-500n-5, 500n+).
For n=2: 0, 5-195, 200-395, 400-595, 600-795, 800-995, 1000+.
Since max points = 400, the effectively reachable thresholds are:
  0 → defending +3
  5-195 → defending +2
  200-395 → defending +1
  400 → no advancement (attacking wins all 400 pts)

But that seems like attacking 400 = no advancement?  In the real game, if attacking gets 80+
points (out of 200 per deck × 2 = 400 total), they win the round.  The threshold for the
attacking team to "advance" must be lower than 400.

I think I'm misreading the "n" in the plan.  Let me go back and read more carefully:

"For n decks (each 100 pts): 0 pts → defenders +3, up to 5n pts → attackers +3."

Wait, "each 100 pts" — the plan says each deck has 100 points.  With 2 decks, total = 200.
But earlier in M1, the deck verification says "total points across both decks = 200".

So the plan was using 100 pts PER DECK, meaning n=2 → 200 total.  The table:
  0           → defending +3
  5 to 195    → defending +2   (5 to 100×2-5 = 195)
  200 to 395  → defending +1   (100n to 200n-5 = 200 to 395)
  400 to 595  → no advancement (200n to 300n-5 = 400 to 595) [attackers take over same rank]
  600 to 795  → attacking +1   (300n to 400n-5 = 600 to 795)
  800 to 995  → attacking +2   (400n to 500n-5 = 800 to 995)
  1000+       → attacking +3   (500n+)

With 2 decks, max attacking points = 200 (total card points in 2 decks is 200).
So the reachable range is 0-200.  The thresholds that matter are:
  0 → defending +3
  5-195 → defending +2
  200 → defending +1 (attackers get all 200 points)

But wait — can the attackers ever score 400 or above with only 200 total points?  No!
The bottom deck multiplier is what can push points higher.

From the plan: "Calculate bottom deck multiplier: 2 * length_of_largest_component in the final
trick (if the attacking team wins the last trick, bottom deck points are added with multiplier)."

So if the attacker wins the last trick, the points buried in the bottom deck are counted with a
multiplier.  If the bottom deck has 20 points and the multiplier is 4 (2 × length=2 for a pair),
that adds 80 more attacking points.  So attacking can score more than 200 in total.

OK so the threshold table makes more sense now.  The final formula is:
  attacking_points = (base points from tricks) + multiplier × bottom_points
  (where multiplier only applies if attacking team wins the last trick)

And the thresholds use this adjusted total.  For n=2 decks (each deck has 100 base card points):
  0           → defending +3
  5-195       → defending +2
  200-395     → defending +1    [attacking scored 200+, the equivalent of the full deck's worth]
  400-595     → no advancement  [attacking scored 400 = 2 decks worth, very dominant]
  600-795     → attacking +1
  800-995     → attacking +2
  1000+       → attacking +3

This makes more sense now.  The multiplier enables scores above 200.

Let me implement this:
"""
from __future__ import annotations

from shengji.models.card import Card
from shengji.models.groups import classify_play, Tractor, IdenticalGroup
from shengji.models.trump import TrumpContext


# ---------------------------------------------------------------------------
# Bottom deck multiplier
# ---------------------------------------------------------------------------

def _largest_component_length(cards: list[Card], ctx: TrumpContext) -> int:
    """Return the length (in card positions) of the largest tractor in *cards*,
    or 1 if no tractor (a single / identical group has length 1 position).

    Used to compute the bottom deck multiplier: 2 × largest_length.
    """
    fmt = classify_play(cards, ctx)
    if isinstance(fmt, Tractor):
        return fmt.length
    if isinstance(fmt, IdenticalGroup):
        # A pair/triple/quad occupies one rank position — length 1 for multiplier
        return 1
    # Single or Throw — length 1
    return 1


# ---------------------------------------------------------------------------
# Point counting
# ---------------------------------------------------------------------------

def count_attacking_points(
    tricks_won: dict[str, list[list[Card]]],
    attacker_ids: set[str],
    bottom_deck: list[Card],
    last_trick_winner_id: str,
    last_trick_cards: list[Card],
    ctx: TrumpContext,
) -> int:
    """Compute the total attacking points for this round.

    Parameters
    ----------
    tricks_won:
        Map of player_id → list of tricks (each trick is a list of Card).
    attacker_ids:
        Set of player IDs on the attacking team.
    bottom_deck:
        The 8 cards currently buried.
    last_trick_winner_id:
        The player who won the final trick.
    last_trick_cards:
        All cards from the final trick (used for multiplier calculation).
    ctx:
        Current TrumpContext (for classifying the last trick format).

    Returns
    -------
    Total attacking points including any bottom-deck multiplier.
    """
    # Base points from tricks won by attackers
    base_pts = 0
    for pid, tricks in tricks_won.items():
        if pid in attacker_ids:
            for trick in tricks:
                base_pts += sum(c.point_value for c in trick)

    # Bottom deck multiplier (only if an attacker wins the last trick)
    bottom_pts = sum(c.point_value for c in bottom_deck)
    if last_trick_winner_id in attacker_ids and bottom_pts > 0:
        multiplier = 2 * _largest_component_length(last_trick_cards, ctx)
        base_pts += multiplier * bottom_pts

    return base_pts


# ---------------------------------------------------------------------------
# Rank advancement threshold table
# ---------------------------------------------------------------------------

def compute_rank_advancement(
    attacking_points: int,
    n_decks: int = 2,
) -> tuple[str, int]:
    """Return (winner, steps) for rank advancement.

    winner — "attacking" or "defending"
    steps  — number of ranks to advance (0 means the attacking team takes
              over as defenders at the same rank; the "winner" field is still
              "attacking" in this case to indicate they take over).

    Threshold table (step = 20 * n_decks; for n=2 step=40, threshold=80):
      attacking_points      winner       steps
      ───────────────────────────────────────
      0                     defending    3
      1  to step-1  (1-39)  defending    2
      step to 2s-1 (40-79)  defending    1
      2s to 3s-1  (80-119)  attacking    0   (take over at same rank)
      3s to 4s-1 (120-159)  attacking    1
      4s to 5s-1 (160-199)  attacking    2
      5s+        (200+)     attacking    3

    With 2 decks (200 total card points), the key threshold is 80 points:
    attackers scoring ≥ 80 means they take over as defenders (same rank or
    higher).  The bottom-deck multiplier can push totals above 200.
    """
    step = 20 * n_decks  # = 40 for n=2; threshold for "attackers win" = 2*step = 80

    if attacking_points == 0:
        return ("defending", 3)
    elif attacking_points < step:
        return ("defending", 2)
    elif attacking_points < 2 * step:
        return ("defending", 1)
    elif attacking_points < 3 * step:
        return ("attacking", 0)
    elif attacking_points < 4 * step:
        return ("attacking", 1)
    elif attacking_points < 5 * step:
        return ("attacking", 2)
    else:
        return ("attacking", 3)
