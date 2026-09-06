"""How often does a better packer actually save a sheet?

A single instance says little: most jobs sit far from the boundary where one
extra point of density removes a sheet.  What matters is the distribution over
many jobs, which is what a shop actually experiences.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from instances import kitchen_instance  # noqa: E402

from plynest.config import NestSettings, SheetSpec  # noqa: E402
from plynest.geom2d import Contour, Region  # noqa: E402
from plynest.nest import nest as polygon_nest  # noqa: E402
from plynest.nest_rect import solve as rect_solve  # noqa: E402
from plynest.part import Part  # noqa: E402


def as_parts(inst):
    parts = []
    for i, (w, h) in enumerate(inst.rects):
        profile = Region(Contour.from_points([(0, 0), (w, 0), (w, h), (0, h)]))
        parts.append(Part(id=f"p{i}", label=f"p{i}", path=("b", f"p{i}"),
                          thickness=18.0, profile=profile))
    return parts


def main(jobs: int = 30, units_lo: int = 4, units_hi: int = 24,
         effort_old: int = 6, effort_new: float = 4.0) -> None:
    import random

    rng = random.Random(7)
    old_total = new_total = 0
    old_time = new_time = 0.0
    wins = losses = ties = 0
    rows = []

    for j in range(jobs):
        units = rng.randint(units_lo, units_hi)
        inst = kitchen_instance(f"job{j}", units, seed=1000 + j)

        start = time.perf_counter()
        settings = NestSettings(kerf_mm=inst.kerf, edge_keepout_mm=inst.keepout,
                                sheet=SheetSpec(inst.sheet_w, inst.sheet_h),
                                attempts=effort_old, engine="polygon")
        old_res = polygon_nest(as_parts(inst), settings)
        t_old = time.perf_counter() - start
        old = old_res.sheet_count() if not old_res.unplaced else None

        start = time.perf_counter()
        bins, _ = rect_solve(inst.rects, inst.sheet_w - 2 * inst.keepout,
                             inst.sheet_h - 2 * inst.keepout,
                             kerf=inst.kerf, effort=effort_new)
        t_new = time.perf_counter() - start
        new = len(bins) if bins is not None else None

        if old is None or new is None:
            continue
        old_total += old
        new_total += new
        old_time += t_old
        new_time += t_new
        if new < old:
            wins += 1
        elif new > old:
            losses += 1
        else:
            ties += 1
        rows.append((inst.name, len(inst.rects), inst.area_bound(), old, new,
                     t_old, t_new))

    print(f"{'job':8s} {'n':>4s} {'bnd':>4s} | {'old':>4s} {'new':>4s} | "
          f"{'t_old':>7s} {'t_new':>7s}")
    print("-" * 52)
    for name, n, bound, old, new, t_old, t_new in rows:
        flag = "  <-- saved" if new < old else ("  <-- worse" if new > old else "")
        print(f"{name:8s} {n:4d} {bound:4d} | {old:4d} {new:4d} | "
              f"{t_old:6.2f}s {t_new:6.2f}s{flag}")
    print("-" * 52)
    print(f"jobs: {len(rows)}   sheets  old {old_total}  new {new_total}  "
          f"({new_total - old_total:+d}, {(old_total - new_total) / max(old_total, 1) * 100:.2f}%)")
    print(f"better on {wins} jobs, worse on {losses}, tied on {ties}")
    print(f"time    old {old_time:.1f}s   new {new_time:.1f}s "
          f"({old_time / max(new_time, 1e-9):.1f}x)")


def effort_sweep(jobs: int = 24, efforts=(0.0, 1.0, 4.0, 12.0, 30.0)) -> None:
    """Does spending more time actually buy fewer sheets?"""
    import random

    from instances import kitchen_instance

    rng = random.Random(7)
    specs = [(f"job{j}", rng.randint(4, 24), 1000 + j) for j in range(jobs)]
    made = [kitchen_instance(n, u, seed=s) for n, u, s in specs]
    bounds = sum(i.area_bound() for i in made)

    print(f"{jobs} kitchen jobs, area bound {bounds} sheets")
    print(f"{'effort':>8s} | {'sheets':>7s} {'excess':>7s} | {'time':>8s}")
    print("-" * 40)
    for effort in efforts:
        total = 0.0
        start = time.perf_counter()
        for inst in made:
            bins, _ = rect_solve(inst.rects, inst.sheet_w - 2 * inst.keepout,
                                 inst.sheet_h - 2 * inst.keepout,
                                 kerf=inst.kerf, effort=effort)
            total += len(bins)
        elapsed = time.perf_counter() - start
        print(f"{effort:8.0f} | {int(total):7d} {int(total) - bounds:+7d} | {elapsed:7.1f}s")


if __name__ == "__main__":
    if sys.argv[1:2] == ["sweep"]:
        effort_sweep(jobs=int(sys.argv[2]) if len(sys.argv) > 2 else 24)
    else:
        args = [int(a) for a in sys.argv[1:3]] or [30]
        main(jobs=args[0])
