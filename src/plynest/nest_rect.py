"""Rectangle nesting: maximal-rectangles placement under ruin-and-recreate search.

Sheet-goods parts are overwhelmingly rectangles, and rectangles have a much
better literature than general nesting.  Two ideas from it do the work here:

* **Maximal rectangles** (Jylanki, *A Thousand Ways to Pack the Bin*, 2010).
  Free space is kept as the set of maximal empty rectangles rather than a
  skyline, so a part can be dropped into any gap -- including one enclosed by
  parts placed earlier, which a bottom-left scan can never reach.  Several fit
  rules are tried; Best Short Side Fit is usually, but not always, the winner.

* **Ruin and recreate with late acceptance** (Schrimpf et al. 1999; the
  goal-driven variant of Guerriero & Saccomanno / Lodi et al. for 2D bin
  packing).  A greedy pass alone plateaus almost immediately: reordering the
  parts and re-running the same decoder explores one basin.  Instead the search
  repeatedly empties the least-used sheets, puts those parts back somewhere
  else, and keeps the result if it beats what the search held some iterations
  ago.  That is what actually removes a sheet from a job.

The objective is Falkenauer's: fewest sheets first, then the most lopsided fill
distribution, because concentrating material is what leaves a sheet empty enough
to delete.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

_EPS = 1e-7


@dataclass(frozen=True)
class RectItem:
    """One part reduced to a rectangle, already inflated by the kerf."""

    key: int
    w: float
    h: float

    @property
    def area(self) -> float:
        return self.w * self.h


@dataclass(frozen=True)
class RectPlacement:
    key: int
    x: float
    y: float
    rotated: bool


# --- fit rules --------------------------------------------------------------
# Each returns (primary, secondary); lower is better.

def _bssf(fx, fy, fw, fh, w, h):
    """Best Short Side Fit: smallest leftover on the tighter axis."""
    dw, dh = fw - w, fh - h
    return (min(dw, dh), max(dw, dh))


def _blsf(fx, fy, fw, fh, w, h):
    """Best Long Side Fit."""
    dw, dh = fw - w, fh - h
    return (max(dw, dh), min(dw, dh))


def _baf(fx, fy, fw, fh, w, h):
    """Best Area Fit, broken by short side."""
    dw, dh = fw - w, fh - h
    return (fw * fh - w * h, min(dw, dh))


def _bl(fx, fy, fw, fh, w, h):
    """Bottom Left: lowest top edge, then leftmost."""
    return (fy + h, fx)


RULES = {"bssf": _bssf, "blsf": _blsf, "baf": _baf, "bl": _bl}
RULE_NAMES = tuple(RULES)


class MaxRects:
    """Free space as a set of maximal empty rectangles."""

    __slots__ = ("width", "height", "free", "used_area", "max_w", "max_h")

    def __init__(self, width: float, height: float):
        self.width = width
        self.height = height
        self.free: list[tuple[float, float, float, float]] = [(0.0, 0.0, width, height)]
        self.used_area = 0.0
        # Largest free width and height anywhere on the sheet.  Scanning every
        # sheet for every part is the inner loop of the whole search, and these
        # two numbers reject most sheets without touching the free list.
        self.max_w = width
        self.max_h = height

    def copy(self) -> "MaxRects":
        clone = MaxRects.__new__(MaxRects)
        clone.width = self.width
        clone.height = self.height
        clone.free = list(self.free)
        clone.used_area = self.used_area
        clone.max_w = self.max_w
        clone.max_h = self.max_h
        return clone

    def cannot_hold(self, w: float, h: float, rotations) -> bool:
        """Cheap reject: True when no orientation can possibly fit."""
        for rotated in rotations:
            iw, ih = (h, w) if rotated else (w, h)
            if iw <= self.max_w + _EPS and ih <= self.max_h + _EPS:
                return False
        return True

    @property
    def capacity(self) -> float:
        return self.width * self.height

    def fill(self) -> float:
        cap = self.capacity
        return self.used_area / cap if cap > 0 else 0.0

    def find(self, w: float, h: float, rule, rotations: tuple[bool, ...]):
        """Best (score, x, y, rotated) for this item, or None."""
        best = None
        for rotated in rotations:
            iw, ih = (h, w) if rotated else (w, h)
            if iw > self.width + _EPS or ih > self.height + _EPS:
                continue
            for fx, fy, fw, fh in self.free:
                if fw + _EPS < iw or fh + _EPS < ih:
                    continue
                score = rule(fx, fy, fw, fh, iw, ih)
                if best is None or score < best[0]:
                    best = (score, fx, fy, rotated)
        return best

    def place(self, x: float, y: float, w: float, h: float) -> None:
        split: list[tuple[float, float, float, float]] = []
        for rect in self.free:
            split.extend(_split(rect, x, y, w, h))
        self.free = _prune(split)
        self.used_area += w * h
        self.max_w = max((r[2] for r in self.free), default=0.0)
        self.max_h = max((r[3] for r in self.free), default=0.0)


def _split(rect, x, y, w, h):
    """Break a free rectangle around a newly used one, keeping maximality."""
    fx, fy, fw, fh = rect
    if x >= fx + fw - _EPS or x + w <= fx + _EPS:
        return (rect,)
    if y >= fy + fh - _EPS or y + h <= fy + _EPS:
        return (rect,)

    out = []
    if y > fy + _EPS:                      # strip below
        out.append((fx, fy, fw, y - fy))
    if y + h < fy + fh - _EPS:             # strip above
        out.append((fx, y + h, fw, fy + fh - (y + h)))
    if x > fx + _EPS:                      # strip left
        out.append((fx, fy, x - fx, fh))
    if x + w < fx + fw - _EPS:             # strip right
        out.append((x + w, fy, fx + fw - (x + w), fh))
    return out


def _prune(rects):
    """Drop any free rectangle wholly inside another; that is what keeps the
    set maximal, and it is the only thing stopping it growing without bound."""
    rects = [r for r in rects if r[2] > _EPS and r[3] > _EPS]
    rects.sort(key=lambda r: -r[2] * r[3])
    kept: list[tuple[float, float, float, float]] = []
    for rect in rects:
        x, y, w, h = rect
        contained = False
        for kx, ky, kw, kh in kept:
            if (kx - _EPS <= x and ky - _EPS <= y
                    and kx + kw + _EPS >= x + w and ky + kh + _EPS >= y + h):
                contained = True
                break
        if not contained:
            kept.append(rect)
    return kept


@dataclass
class Bin:
    sheet: MaxRects
    placements: list[RectPlacement] = field(default_factory=list)

    def copy(self) -> "Bin":
        return Bin(self.sheet.copy(), list(self.placements))


@dataclass
class Solution:
    bins: list[Bin] = field(default_factory=list)

    def copy(self) -> "Solution":
        return Solution([b.copy() for b in self.bins])

    def score(self) -> tuple[int, float]:
        """Falkenauer: fewest sheets, then the most lopsided fill.

        Concentrating material is what leaves a sheet empty enough to delete,
        so at equal sheet count a lopsided solution is the more promising one.
        """
        return (len(self.bins), -sum(b.sheet.fill() ** 2 for b in self.bins))

    def item_count(self) -> int:
        return sum(len(b.placements) for b in self.bins)


def _insert(solution: Solution, item: RectItem, rule, rotations,
            width: float, height: float, open_new: bool = True) -> bool:
    """Put one item in the best place across all open sheets."""
    best = None
    for index, b in enumerate(solution.bins):
        if b.sheet.cannot_hold(item.w, item.h, rotations):
            continue
        found = b.sheet.find(item.w, item.h, rule, rotations)
        if found is None:
            continue
        if best is None or found[0] < best[0]:
            best = (found[0], index, found[1], found[2], found[3])
    if best is not None:
        _, index, x, y, rotated = best
        b = solution.bins[index]
        iw, ih = (item.h, item.w) if rotated else (item.w, item.h)
        b.sheet.place(x, y, iw, ih)
        b.placements.append(RectPlacement(item.key, x, y, rotated))
        return True

    if not open_new:
        return False
    fresh = Bin(MaxRects(width, height))
    found = fresh.sheet.find(item.w, item.h, rule, rotations)
    if found is None:
        return False
    _, x, y, rotated = found
    iw, ih = (item.h, item.w) if rotated else (item.w, item.h)
    fresh.sheet.place(x, y, iw, ih)
    fresh.placements.append(RectPlacement(item.key, x, y, rotated))
    solution.bins.append(fresh)
    return True


ORDERINGS = {
    "area": lambda i: (-i.area, -max(i.w, i.h)),
    "max_side": lambda i: (-max(i.w, i.h), -i.area),
    "height": lambda i: (-i.h, -i.w),
    "width": lambda i: (-i.w, -i.h),
    "perimeter": lambda i: (-(i.w + i.h), -i.area),
    "squareness": lambda i: (abs(i.w - i.h), -i.area),
}


def _construct(items: list[RectItem], width: float, height: float,
               rule, rotations, order) -> Solution | None:
    solution = Solution()
    for item in sorted(items, key=order):
        if not _insert(solution, item, rule, rotations, width, height):
            return None
    return solution


def _randomized_construct(items: list[RectItem], width: float, height: float,
                          rotations, rng: random.Random) -> Solution | None:
    """A greedy pass with a random rule and a jittered order.

    Restarting the goal-driven search from a genuinely different packing is what
    makes extra search effort worth spending: re-running the same descent from
    the same place only ever finds the same answer.
    """
    rule = RULES[rng.choice(RULE_NAMES)]
    noise = rng.uniform(0.05, 0.4)
    order = list(items)
    order.sort(key=lambda i: -i.area * (1.0 + rng.uniform(-noise, noise)))
    solution = Solution()
    for item in order:
        if not _insert(solution, item, rule, rotations, width, height):
            return None
    return solution


def lower_bound(items: list[RectItem], width: float, height: float) -> int:
    """Continuous area bound; the search stops the moment it reaches this."""
    capacity = width * height
    if capacity <= 0:
        return 0
    return max(1, math.ceil(sum(i.area for i in items) / capacity - 1e-9))


def _ruin(solution: Solution, rng: random.Random) -> tuple[Solution, list[int]]:
    """Empty a few sheets -- always the emptiest, plus some at random."""
    kept = solution.copy()
    if len(kept.bins) <= 1:
        return kept, []

    order = sorted(range(len(kept.bins)), key=lambda i: kept.bins[i].sheet.used_area)
    victims = {order[0]}
    extra = min(len(kept.bins) - 1, rng.randint(1, 2))
    while len(victims) < extra + 1:
        victims.add(rng.randrange(len(kept.bins)))

    pool: list[int] = []
    survivors: list[Bin] = []
    for index, b in enumerate(kept.bins):
        if index in victims:
            pool.extend(p.key for p in b.placements)
        else:
            survivors.append(b)
    kept.bins = survivors
    return kept, pool


def _recreate(solution: Solution, pool: list[int], by_key: dict[int, RectItem],
              rotations, width: float, height: float, rng: random.Random) -> bool:
    rule = RULES[rng.choice(RULE_NAMES)]
    items = [by_key[k] for k in pool]
    # Largest first, but jittered: a strictly greedy order is what the search
    # is trying to escape.
    noise = rng.uniform(0.0, 0.25)
    items.sort(key=lambda i: -i.area * (1.0 + rng.uniform(-noise, noise)))
    for item in items:
        if not _insert(solution, item, rule, rotations, width, height):
            return False
    return True


@dataclass
class Attempt:
    """A packing into a fixed number of sheets, with whatever did not fit."""

    bins: list[Bin]
    unplaced: list[int]

    def copy(self) -> "Attempt":
        return Attempt([b.copy() for b in self.bins], list(self.unplaced))

    def penalty(self, by_key: dict[int, RectItem]) -> float:
        """Area still homeless.  Zero means the target was met."""
        return sum(by_key[k].area for k in self.unplaced)


def _seed_attempt(solution: Solution, target: int,
                  by_key: dict[int, RectItem]) -> Attempt:
    """Keep the ``target`` fullest sheets; everything else goes back in the pool."""
    order = sorted(solution.bins, key=lambda b: -b.sheet.used_area)
    keep, drop = order[:target], order[target:]
    unplaced = [p.key for b in drop for p in b.placements]
    return Attempt([b.copy() for b in keep], unplaced)


def _shake(attempt: Attempt, by_key: dict[int, RectItem], rotations,
           width: float, height: float, rng: random.Random) -> Attempt | None:
    """One ruin-and-recreate step against a fixed sheet count.

    The ruin is proportional to the job.  Emptying one or two whole sheets is a
    huge move on a three-sheet job and a rounding error on a thirty-sheet one,
    so instead a fraction of all placed parts is lifted -- sometimes whole
    sheets, sometimes a patch around a random point, sometimes scattered.
    """
    trial = attempt.copy()
    if not trial.bins:
        return None

    pool = list(trial.unplaced)
    trial.unplaced = []
    fraction = rng.uniform(0.06, 0.30)
    mode = rng.random()

    if mode < 0.35:
        # Whole sheets, enough of them to matter at this job size.
        count = max(1, min(len(trial.bins), round(len(trial.bins) * fraction)))
        victims = rng.sample(range(len(trial.bins)), count)
        for index in victims:
            pool.extend(p.key for p in trial.bins[index].placements)
            trial.bins[index] = Bin(MaxRects(width, height))
    elif mode < 0.75:
        # A patch: everything within a radius of a random part, on a few sheets.
        count = max(1, min(len(trial.bins), round(len(trial.bins) * fraction) + 1))
        radius = rng.uniform(0.2, 0.6) * max(width, height)
        for index in rng.sample(range(len(trial.bins)), count):
            victim = trial.bins[index]
            if not victim.placements:
                continue
            anchor = rng.choice(victim.placements)
            keep, taken = [], []
            for p in victim.placements:
                near = math.hypot(p.x - anchor.x, p.y - anchor.y) <= radius
                (taken if near else keep).append(p)
            if not taken:
                continue
            pool.extend(p.key for p in taken)
            trial.bins[index] = _rebuild(keep, by_key, width, height)
    else:
        # Scattered: a random slice of everything placed.
        everything = [(i, p) for i, b in enumerate(trial.bins) for p in b.placements]
        if not everything:
            return None
        count = max(1, round(len(everything) * fraction))
        chosen = set(id(p) for _, p in rng.sample(everything, min(count, len(everything))))
        for index, b in enumerate(trial.bins):
            keep, taken = [], []
            for p in b.placements:
                (taken if id(p) in chosen else keep).append(p)
            if taken:
                pool.extend(p.key for p in taken)
                trial.bins[index] = _rebuild(keep, by_key, width, height)

    if not pool:
        return None

    # Recreate: biggest first, jittered, into the sheets we already have.
    rule = RULES[rng.choice(RULE_NAMES)]
    noise = rng.uniform(0.0, 0.3)
    items = [by_key[k] for k in pool]
    items.sort(key=lambda i: -i.area * (1.0 + rng.uniform(-noise, noise)))

    holder = Solution(trial.bins)
    for item in items:
        if not _insert(holder, item, rule, rotations, width, height, open_new=False):
            trial.unplaced.append(item.key)
    return trial


def _rebuild(placements: list[RectPlacement], by_key: dict[int, RectItem],
             width: float, height: float) -> Bin:
    """Recreate a sheet's free space from the placements that survived."""
    fresh = Bin(MaxRects(width, height))
    for p in placements:
        item = by_key[p.key]
        iw, ih = (item.h, item.w) if p.rotated else (item.w, item.h)
        fresh.sheet.place(p.x, p.y, iw, ih)
        fresh.placements.append(p)
    return fresh


STALL_LIMIT = 2500
"""Iterations without progress before a sheet target is written off.

Most targets are geometrically impossible even though they clear the area
bound, and grinding on one to the end of the budget just makes the program
feel slow for no gain."""


def _pack_into(target: int, solution: Solution, by_key: dict[int, RectItem],
               rotations, width: float, height: float, rng: random.Random,
               deadline: float) -> tuple[Solution | None, int]:
    """Try to fit everything into exactly ``target`` sheets.

    Goal-driven ruin and recreate: the sheet count is fixed and the search
    drives the homeless area to zero, which is a far sharper signal than
    nudging a free-form objective and hoping a sheet falls empty.
    """
    current = _seed_attempt(solution, target, by_key)
    if not current.unplaced:
        return Solution(current.bins), 0

    history_len = 30
    best_penalty = current.penalty(by_key)
    history = [best_penalty] * history_len
    iterations = 0
    stalled = 0

    while time.perf_counter() < deadline and stalled < STALL_LIMIT:
        iterations += 1
        trial = _shake(current, by_key, rotations, width, height, rng)
        if trial is None:
            stalled += 1
            continue
        if not trial.unplaced:
            return Solution(trial.bins), iterations

        penalty = trial.penalty(by_key)
        slot = iterations % history_len
        if penalty <= current.penalty(by_key) or penalty <= history[slot]:
            current = trial
        if penalty < best_penalty - _EPS:
            best_penalty = penalty
            stalled = 0
        else:
            stalled += 1
        history[slot] = current.penalty(by_key)

    return None, iterations


@dataclass
class NestReport:
    sheets: int
    lower_bound: int
    iterations: int
    seconds: float
    improved_from: int
    optimal: bool
    restarts: int = 0


def solve(rects: list[tuple[float, float]], width: float, height: float, *,
          kerf: float = 0.0, rotations: tuple[bool, ...] = (False, True),
          effort: float = 6.0, seed: int = 12345,
          time_limit: float | None = None):
    """Nest ``rects`` onto ``width`` x ``height`` sheets.

    ``effort`` is roughly the number of seconds spent trying to beat the greedy
    result.  Returns ``(bins, report)`` where each bin is a list of
    ``RectPlacement`` whose coordinates are kerf-inclusive lower-left corners.
    """
    start = time.perf_counter()
    # Kerf as inflation: grow every part and the sheet by one kerf, and the gap
    # between neighbours falls out of the arithmetic with no special cases.
    bin_w, bin_h = width + kerf, height + kerf
    items = [RectItem(i, w + kerf, h + kerf) for i, (w, h) in enumerate(rects)]
    by_key = {i.key: i for i in items}

    if not items:
        return [], NestReport(0, 0, 0, 0.0, 0, True)

    bound = lower_bound(items, bin_w, bin_h)
    rng = random.Random(seed)

    best: Solution | None = None
    for rule_name in RULE_NAMES:
        for order in ORDERINGS.values():
            candidate = _construct(items, bin_w, bin_h, RULES[rule_name], rotations, order)
            if candidate is None:
                continue
            if best is None or candidate.score() < best.score():
                best = candidate
        if best is not None and len(best.bins) <= bound:
            break

    if best is None:
        return None, NestReport(0, bound, 0, time.perf_counter() - start, 0, False)

    greedy_sheets = len(best.bins)
    budget = max(0.0, effort)
    if time_limit is not None:
        budget = min(budget, max(0.0, time_limit - (time.perf_counter() - start)))
    deadline = start + (time.perf_counter() - start) + budget

    iterations = 0
    restarts = 0
    while len(best.bins) > bound and time.perf_counter() < deadline:
        target = len(best.bins) - 1
        packed, used = _pack_into(target, best, by_key, rotations,
                                  bin_w, bin_h, rng, deadline)
        iterations += used
        if packed is not None:
            best = packed
            continue

        # The direct attempt stalled.  Try the same target from somewhere else
        # entirely; this is where a bigger effort setting earns its keep.
        progressed = False
        while time.perf_counter() < deadline:
            restarts += 1
            seedling = _randomized_construct(items, bin_w, bin_h, rotations, rng)
            if seedling is None or len(seedling.bins) < target:
                continue
            packed, used = _pack_into(target, seedling, by_key, rotations,
                                      bin_w, bin_h, rng, deadline)
            iterations += used
            if packed is not None:
                best = packed
                progressed = True
                break
        if not progressed:
            break

    elapsed = time.perf_counter() - start
    report = NestReport(
        sheets=len(best.bins),
        lower_bound=bound,
        iterations=iterations,
        seconds=elapsed,
        improved_from=greedy_sheets,
        optimal=len(best.bins) <= bound,
        restarts=restarts,
    )
    return [b.placements for b in best.bins], report
