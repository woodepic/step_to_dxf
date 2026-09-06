"""Compare nesting engines on the benchmark instances."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from instances import Instance, all_instances  # noqa: E402

from plynest.config import NestSettings, SheetSpec  # noqa: E402
from plynest.geom2d import Contour, Region  # noqa: E402
from plynest.nest import nest as polygon_nest  # noqa: E402
from plynest.nest_rect import solve as rect_solve  # noqa: E402
from plynest.part import Part  # noqa: E402


def as_parts(inst: Instance) -> list[Part]:
    parts = []
    for i, (w, h) in enumerate(inst.rects):
        profile = Region(Contour.from_points([(0, 0), (w, 0), (w, h), (0, h)]))
        parts.append(Part(id=f"p{i}", label=f"p{i}", path=("b", f"p{i}"),
                          thickness=18.0, profile=profile))
    return parts


def run_old(inst: Instance, effort: int):
    settings = NestSettings(kerf_mm=inst.kerf, edge_keepout_mm=inst.keepout,
                            sheet=SheetSpec(inst.sheet_w, inst.sheet_h),
                            attempts=effort, engine="polygon")
    start = time.perf_counter()
    result = polygon_nest(as_parts(inst), settings)
    elapsed = time.perf_counter() - start
    if result.unplaced:
        return None, elapsed
    return result.sheet_count(), elapsed


def run_new(inst: Instance, effort: float):
    start = time.perf_counter()
    bins, report = rect_solve(
        inst.rects,
        inst.sheet_w - 2 * inst.keepout,
        inst.sheet_h - 2 * inst.keepout,
        kerf=inst.kerf, effort=effort,
    )
    elapsed = time.perf_counter() - start
    if bins is None:
        return None, elapsed
    placed = sum(len(b) for b in bins)
    assert placed == len(inst.rects), f"lost parts: {placed} of {len(inst.rects)}"
    return len(bins), elapsed


def density(inst: Instance, sheets: int) -> float:
    return inst.total_area() / (sheets * inst.usable()) if sheets else 0.0


def main(effort_old: int = 6, effort_new: float = 6.0, only: str | None = None,
         skip_old: str = "") -> None:
    print(f"{'instance':16s} {'n':>5s} {'bnd':>4s} | {'old':>4s} {'dens':>6s} {'time':>7s}"
          f" | {'new':>4s} {'dens':>6s} {'time':>7s} | gain")
    print("-" * 84)
    tot_old = tot_new = tot_bound = 0
    for inst in all_instances():
        if only and only not in inst.name:
            continue
        target = inst.optimum if inst.optimum is not None else inst.area_bound()
        if skip_old and skip_old in inst.name:
            old, t_old = None, 0.0
        else:
            old, t_old = run_old(inst, effort_old)
        new, t_new = run_new(inst, effort_new)
        tot_old += old or 0
        tot_new += new or 0
        tot_bound += target
        gain = "" if old is None or new is None else f"{old - new:+d}"
        print(f"{inst.name:16s} {len(inst.rects):5d} {target:4d} | "
              f"{old if old else '-':>4} {density(inst, old or 0) * 100:5.1f}% {t_old:6.2f}s | "
              f"{new if new else '-':>4} {density(inst, new or 0) * 100:5.1f}% {t_new:6.2f}s | {gain}")
    print("-" * 84)
    print(f"{'TOTAL':16s} {'':5s} {tot_bound:4d} | {tot_old:4d} {'':14s} | "
          f"{tot_new:4d} {'':14s} | {tot_old - tot_new:+d} sheets")


if __name__ == "__main__":
    args = sys.argv[1:]
    main(effort_old=int(args[0]) if args else 6,
         effort_new=float(args[1]) if len(args) > 1 else 6.0,
         only=args[2] if len(args) > 2 else None,
         skip_old=args[3] if len(args) > 3 else "")
