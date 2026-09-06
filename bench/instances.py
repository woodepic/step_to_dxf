"""Benchmark instances for the nester.

The important ones are the *known-optimum* instances: take K whole sheets and
guillotine-cut each into pieces, allowing for the kerf that separates them.  Any
packing of those pieces needs at least K sheets, and K is achievable by
construction -- so the gap to K is a true measure of solution quality, not a
comparison against another heuristic.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

MM_PER_INCH = 25.4


@dataclass
class Instance:
    name: str
    rects: list[tuple[float, float]]
    sheet_w: float
    sheet_h: float
    kerf: float
    keepout: float
    optimum: int | None = None
    """Known-optimal sheet count, when the instance was built by cutting up sheets."""

    def total_area(self) -> float:
        return sum(w * h for w, h in self.rects)

    def usable(self) -> float:
        return (self.sheet_w - 2 * self.keepout) * (self.sheet_h - 2 * self.keepout)

    def area_bound(self) -> int:
        import math

        return math.ceil(self.total_area() / self.usable() - 1e-9)


def guillotine_cut(w: float, h: float, kerf: float, rng: random.Random,
                   min_side: float, depth: int = 0) -> list[tuple[float, float]]:
    """Recursively split a panel into pieces, consuming ``kerf`` at every cut."""
    can_split_w = w >= 2 * min_side + kerf
    can_split_h = h >= 2 * min_side + kerf
    if depth > 7 or not (can_split_w or can_split_h):
        return [(w, h)]
    if rng.random() < 0.22 and depth >= 2:
        return [(w, h)]

    if can_split_w and (not can_split_h or (w > h) == (rng.random() < 0.75)):
        lo, hi = min_side, w - min_side - kerf
        cut = rng.uniform(lo, hi)
        return (guillotine_cut(cut, h, kerf, rng, min_side, depth + 1)
                + guillotine_cut(w - cut - kerf, h, kerf, rng, min_side, depth + 1))
    lo, hi = min_side, h - min_side - kerf
    cut = rng.uniform(lo, hi)
    return (guillotine_cut(w, cut, kerf, rng, min_side, depth + 1)
            + guillotine_cut(w, h - cut - kerf, kerf, rng, min_side, depth + 1))


def perfect_instance(name: str, sheets: int, seed: int, *, min_side: float = 90.0,
                     sheet_w: float = 48 * MM_PER_INCH, sheet_h: float = 96 * MM_PER_INCH,
                     kerf: float = 6.35, keepout: float = 25.4,
                     slack: float = 0.0) -> Instance:
    """``sheets`` sheets cut up: ``sheets`` is achievable and so is the optimum.

    ``slack`` shrinks every piece afterwards.  With slack 0 the tiling is exact
    to the last micron, which is a pathological case -- no floating-point packer
    will rebuild it, and no real job looks like that.  A millimetre or two of
    slack keeps the instance tight while leaving the optimum reachable.
    """
    rng = random.Random(seed)
    rects: list[tuple[float, float]] = []
    for _ in range(sheets):
        rects += guillotine_cut(sheet_w - 2 * keepout, sheet_h - 2 * keepout,
                                kerf, rng, min_side)
    if slack:
        rects = [(max(10.0, w - slack), max(10.0, h - slack)) for w, h in rects]
    rng.shuffle(rects)
    return Instance(name, rects, sheet_w, sheet_h, kerf, keepout, optimum=sheets)


# Sizes that actually turn up in a kitchen, in millimetres.
_CARCASS = [
    (720.0, 560.0),   # tall side
    (720.0, 300.0),   # wall-unit side
    (560.0, 560.0),   # base shelf
    (860.0, 560.0),   # tall side
    (596.0, 560.0),   # bottom / top
    (140.0, 560.0),   # rail
    (716.0, 596.0),   # door
    (356.0, 596.0),   # drawer front
    (496.0, 460.0),   # drawer box side
    (496.0, 116.0),   # drawer box back
    (2300.0, 100.0),  # plinth
    (1200.0, 600.0),  # worktop template
]


def kitchen_instance(name: str, units: int, seed: int, *, kerf: float = 6.35,
                     keepout: float = 25.4) -> Instance:
    """A kitchen-sized job: many cabinets' worth of realistic panel sizes."""
    rng = random.Random(seed)
    rects: list[tuple[float, float]] = []
    for _ in range(units):
        for _ in range(rng.randint(4, 9)):
            w, h = rng.choice(_CARCASS)
            jitter = rng.choice([0.0, 0.0, 0.0, rng.uniform(-40, 40)])
            rects.append((max(60.0, w + jitter), max(60.0, h)))
    rng.shuffle(rects)
    return Instance(name, rects, 48 * MM_PER_INCH, 96 * MM_PER_INCH, kerf, keepout)


def all_instances() -> list[Instance]:
    """Three classes: exact tilings, tilings with a little slack, real jobs."""
    return [
        # Zero slack: the adversarial case, kept as a stress test.
        perfect_instance("exact-3", 3, seed=1),
        perfect_instance("exact-8", 8, seed=3),
        # A couple of millimetres of slack -- tight, but reachable.
        perfect_instance("cut-3", 3, seed=1, slack=2.0),
        perfect_instance("cut-5", 5, seed=2, slack=2.0),
        perfect_instance("cut-8", 8, seed=3, slack=2.0),
        perfect_instance("cut-12", 12, seed=4, slack=2.0),
        perfect_instance("cut-20", 20, seed=5, min_side=70.0, slack=2.0),
        perfect_instance("cut-fine-10", 10, seed=6, min_side=55.0, slack=2.0),
        # Realistic kitchen jobs; no known optimum, so the area bound is the ruler.
        kitchen_instance("kitchen-small", 6, seed=11),
        kitchen_instance("kitchen-medium", 16, seed=12),
        kitchen_instance("kitchen-large", 34, seed=13),
    ]


if __name__ == "__main__":
    for inst in all_instances():
        print(f"{inst.name:16s} {len(inst.rects):4d} rects  area={inst.total_area()/1e6:6.2f} m2 "
              f" area-bound={inst.area_bound():3d}  optimum={inst.optimum}")
