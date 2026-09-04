"""Nest parts onto stock sheets.

Bottom-left-fill over true part outlines (not bounding boxes), so an L-shaped
part lets a neighbour tuck into its notch.  Candidate positions come from the
edges of already-placed parts, which is where an optimal packing's contacts
always are.

Three things lift it from "works" to "near optimal": several part orderings are
tried, each in two scan directions, and a consolidation pass afterwards tries to
empty the least-used sheet into the others.  That last step is what removes the
half-empty sheet a first-fit heuristic always leaves behind.

Parts of different thickness never share a sheet -- they are different stock.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import numpy as np
from shapely import affinity
from shapely.geometry import Polygon
from shapely.strtree import STRtree

from .config import ROTATION_ANGLES, NestSettings, SheetSpec
from .geom2d import ARC_CHORD_TOL, Region
from .part import Part

THICKNESS_TOL = 0.05
"""Parts within this many mm of each other are treated as the same stock."""


@dataclass
class Placement:
    """A part positioned on a sheet: rotate about the origin, then translate."""

    part: Part
    angle: float
    dx: float
    dy: float

    def transform(self) -> tuple[float, float, float]:
        return (math.radians(self.angle), self.dx, self.dy)

    def profile(self) -> Region:
        return self.part.profile.transformed(*self.transform())

    def polygon(self, tol: float = ARC_CHORD_TOL) -> Polygon:
        return self.profile().to_polygon(tol)

    def bounds(self) -> tuple[float, float, float, float]:
        return self.profile().bounds()


@dataclass
class Sheet:
    index: int
    thickness: float
    spec: SheetSpec
    placements: list[Placement] = field(default_factory=list)
    usable: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    def used_area(self) -> float:
        return sum(p.part.area for p in self.placements)

    def utilisation(self) -> float:
        total = self.spec.width_mm * self.spec.height_mm
        return self.used_area() / total if total else 0.0


@dataclass
class NestResult:
    sheets: list[Sheet]
    unplaced: list[tuple[Part, str]] = field(default_factory=list)

    def sheet_count(self) -> int:
        return len(self.sheets)

    def total_utilisation(self) -> float:
        if not self.sheets:
            return 0.0
        used = sum(s.used_area() for s in self.sheets)
        total = sum(s.spec.width_mm * s.spec.height_mm for s in self.sheets)
        return used / total if total else 0.0


@dataclass(frozen=True)
class _Variant:
    """One part pre-rotated, with its outline moved so its bbox starts at (0,0)."""

    angle: float
    poly: Polygon
    w: float
    h: float
    ox: float
    oy: float


class _SheetPacker:
    """Incremental bottom-left packer for one sheet."""

    def __init__(self, rect: tuple[float, float, float, float], gap: float, scan: str = "bl"):
        self.x0, self.y0, self.x1, self.y1 = rect
        self.gap = gap
        self.scan = scan
        self.capacity = (self.x1 - self.x0) * (self.y1 - self.y0)
        self.polys: list[Polygon] = []
        self.boxes = np.zeros((0, 4), dtype=float)
        self.area_used = 0.0
        self._tree: STRtree | None = None

    def snapshot(self):
        return (list(self.polys), self.boxes.copy(), self.area_used, self._tree)

    def restore(self, snap) -> None:
        self.polys, self.boxes, self.area_used, self._tree = list(snap[0]), snap[1].copy(), snap[2], snap[3]

    def _fits(self, poly: Polygon, cx: float, cy: float, w: float, h: float) -> bool:
        if len(self.boxes):
            bx0, by0 = cx - self.gap, cy - self.gap
            bx1, by1 = cx + w + self.gap, cy + h + self.gap
            # Inflated bounding boxes reject the vast majority of candidates cheaply.
            overlap = (
                (self.boxes[:, 0] < bx1)
                & (self.boxes[:, 2] > bx0)
                & (self.boxes[:, 1] < by1)
                & (self.boxes[:, 3] > by0)
            )
            if overlap.any():
                # Boxes touch, so compare the real outlines.
                probe = affinity.translate(poly, cx, cy).buffer(
                    self.gap / 2.0, join_style=2, mitre_limit=4.0
                )
                assert self._tree is not None
                for idx in self._tree.query(probe):
                    other = self.polys[int(idx)].buffer(
                        self.gap / 2.0, join_style=2, mitre_limit=4.0
                    )
                    if other.intersects(probe):
                        return False
        return True

    def _candidates(self, w: float, h: float) -> list[tuple[float, float]]:
        max_x, max_y = self.x1 - w, self.y1 - h
        if max_x < self.x0 - 1e-9 or max_y < self.y0 - 1e-9:
            return []
        xs = {self.x0}
        ys = {self.y0}
        for bx0, by0, bx1, by1 in self.boxes:
            xs.add(bx1 + self.gap)
            xs.add(bx0)
            ys.add(by1 + self.gap)
            ys.add(by0)
        xs_l = sorted(v for v in xs if self.x0 - 1e-9 <= v <= max_x + 1e-9)
        ys_l = sorted(v for v in ys if self.y0 - 1e-9 <= v <= max_y + 1e-9)
        if self.scan == "lb":
            return [(x, y) for x in xs_l for y in ys_l]
        return [(x, y) for y in ys_l for x in xs_l]

    def try_place(self, v: _Variant) -> tuple[float, float] | None:
        """First feasible position in scan order, or None."""
        if self.area_used + v.poly.area > self.capacity + 1e-9:
            return None  # cannot possibly fit; skip the scan entirely
        for x, y in self._candidates(v.w, v.h):
            if self._fits(v.poly, x, y, v.w, v.h):
                return (x, y)
        return None

    def commit(self, v: _Variant, x: float, y: float) -> None:
        moved = affinity.translate(v.poly, x, y)
        self.polys.append(moved)
        b = moved.bounds
        self.boxes = np.vstack([self.boxes, np.array([[b[0], b[1], b[2], b[3]]])])
        self.area_used += moved.area
        self._tree = STRtree(self.polys)


def _variants(part: Part, angles: tuple[float, ...]) -> list[_Variant]:
    out: list[_Variant] = []
    seen: set[tuple[int, int]] = set()
    for angle in angles:
        region = part.profile.transformed(math.radians(angle), 0.0, 0.0)
        x0, y0, x1, y1 = region.bounds()
        w, h = x1 - x0, y1 - y0
        key = (int(round(w * 100)), int(round(h * 100)))
        if key in seen:
            continue  # a square part gains nothing from a 90 deg turn
        seen.add(key)
        poly = affinity.translate(region.to_polygon(ARC_CHORD_TOL), -x0, -y0)
        out.append(_Variant(angle, poly, w, h, -x0, -y0))
    return out


_ORDER_KEYS = {
    "area": lambda p: -p.area,
    "max_dim": lambda p: -max(p.width, p.height),
    "height": lambda p: -p.height,
    "width": lambda p: -p.width,
    "perimeter": lambda p: -(p.width + p.height),
    "bbox": lambda p: -(p.width * p.height),
}


def _orderings(parts: list[Part], attempts: int, seed: int) -> list[list[Part]]:
    """Deterministic orderings first, then seeded shuffles of the largest-first list."""
    out: list[list[Part]] = []
    for name, key in _ORDER_KEYS.items():
        out.append(sorted(parts, key=lambda p, k=key: (k(p), p.id)))
        if len(out) >= attempts:
            return out
    rng = random.Random(seed)
    base = sorted(parts, key=lambda p: (-p.area, p.id))
    while len(out) < attempts:
        shuffled = list(base)
        # Perturb locally: swapping neighbours in a size-ordered list explores
        # useful alternatives without destroying the largest-first structure.
        for _ in range(max(1, len(shuffled) // 6)):
            i = rng.randrange(len(shuffled))
            j = min(len(shuffled) - 1, max(0, i + rng.randint(-3, 3)))
            shuffled[i], shuffled[j] = shuffled[j], shuffled[i]
        out.append(shuffled)
    return out


def _place_all(ordered: list[Part], rect, settings: NestSettings, scan: str,
               variant_cache: dict[str, list[_Variant]]):
    """First-fit-decreasing over sheets, opening a new sheet only when forced."""
    packers: list[_SheetPacker] = []
    assignments: list[list[Placement]] = []
    unplaced: list[tuple[Part, str]] = []
    usable_w, usable_h = rect[2] - rect[0], rect[3] - rect[1]

    for part in ordered:
        variants = variant_cache[part.id]
        feasible = [v for v in variants if v.w <= usable_w + 1e-6 and v.h <= usable_h + 1e-6]
        if not feasible:
            unplaced.append((
                part,
                f"{part.width:.1f} x {part.height:.1f} mm exceeds the usable "
                f"{usable_w:.1f} x {usable_h:.1f} mm sheet area",
            ))
            continue

        placed = False
        for si in range(len(packers) + 1):
            if si == len(packers):
                packers.append(_SheetPacker(rect, settings.kerf_mm, scan))
                assignments.append([])
            packer = packers[si]
            best = None
            for v in feasible:
                pos = packer.try_place(v)
                if pos is None:
                    continue
                key = (round(pos[1], 3), round(pos[0], 3)) if scan == "bl" else (
                    round(pos[0], 3), round(pos[1], 3)
                )
                score = key + (v.w * v.h,)
                if best is None or score < best[0]:
                    best = (score, v, pos)
            if best is not None:
                _, v, (x, y) = best
                packer.commit(v, x, y)
                assignments[si].append(Placement(part, v.angle, x + v.ox, y + v.oy))
                placed = True
                break
        if not placed:
            unplaced.append((part, "no position found on any sheet"))

    return packers, assignments, unplaced


def _consolidate(packers, assignments, rect, settings, variant_cache, scan) -> None:
    """Try to empty the emptiest sheet into the others, repeatedly.

    First-fit leaves a sparse tail sheet; redistributing it often removes a whole
    sheet from the job.  Mutates ``packers``/``assignments`` in place.
    """
    changed = True
    while changed and len(packers) > 1:
        changed = False
        order = sorted(range(len(packers)), key=lambda i: packers[i].area_used)
        for victim in order:
            targets = [i for i in range(len(packers)) if i != victim]
            snaps = {i: packers[i].snapshot() for i in targets}
            moves: list[tuple[int, Placement]] = []
            parts_to_move = sorted(assignments[victim], key=lambda p: -p.part.area)
            ok = True
            for placement in parts_to_move:
                part = placement.part
                landed = False
                for ti in targets:
                    best = None
                    for v in variant_cache[part.id]:
                        pos = packers[ti].try_place(v)
                        if pos is None:
                            continue
                        key = (round(pos[1], 3), round(pos[0], 3)) if scan == "bl" else (
                            round(pos[0], 3), round(pos[1], 3)
                        )
                        if best is None or key < best[0]:
                            best = (key, v, pos)
                    if best is not None:
                        _, v, (x, y) = best
                        packers[ti].commit(v, x, y)
                        moves.append((ti, Placement(part, v.angle, x + v.ox, y + v.oy)))
                        landed = True
                        break
                if not landed:
                    ok = False
                    break
            if ok:
                for ti, placement in moves:
                    assignments[ti].append(placement)
                packers.pop(victim)
                assignments.pop(victim)
                changed = True
                break
            for i in targets:
                packers[i].restore(snaps[i])
    return


def _pack_group(parts: list[Part], thickness: float, settings: NestSettings,
                start_index: int) -> tuple[list[Sheet], list[tuple[Part, str]]]:
    spec = settings.sheet
    k = settings.edge_keepout_mm
    rect = (k, k, spec.width_mm - k, spec.height_mm - k)
    if rect[2] <= rect[0] or rect[3] <= rect[1]:
        return [], [(p, "edge keep-out leaves no usable sheet area") for p in parts]

    angles = ROTATION_ANGLES.get(settings.rotation, ROTATION_ANGLES["90"])
    variant_cache = {p.id: _variants(p, angles) for p in parts}

    best: tuple[tuple, list[list[Placement]], list] | None = None
    for ordered in _orderings(parts, max(1, settings.attempts), settings.seed):
        for scan in ("bl", "lb"):
            packers, assignments, unplaced = _place_all(
                ordered, rect, settings, scan, variant_cache
            )
            _consolidate(packers, assignments, rect, settings, variant_cache, scan)
            # Fewer sheets first; then push the leftover onto as few sheets as
            # possible so the offcut is one usable piece rather than a comb.
            spread = sorted((p.area_used for p in packers))
            score = (len(unplaced), len(packers), spread[0] if spread else 0.0)
            if best is None or score < best[0]:
                best = (score, assignments, unplaced)

    assert best is not None
    _, assignments, unplaced = best
    sheets = []
    for i, placements in enumerate(assignments):
        if not placements:
            continue
        sheets.append(
            Sheet(index=start_index + len(sheets), thickness=thickness, spec=spec,
                  placements=placements, usable=rect)
        )
    return sheets, unplaced


def nest(parts: list[Part], settings: NestSettings) -> NestResult:
    """Group parts by stock thickness and pack each group onto sheets."""
    groups: dict[float, list[Part]] = {}
    for part in parts:
        key = next((k for k in groups if abs(k - part.thickness) <= THICKNESS_TOL), None)
        groups.setdefault(key if key is not None else round(part.thickness, 3), []).append(part)

    all_sheets: list[Sheet] = []
    all_unplaced: list[tuple[Part, str]] = []
    for thickness in sorted(groups, reverse=True):
        sheets, unplaced = _pack_group(groups[thickness], thickness, settings, len(all_sheets))
        for s in sheets:
            s.index = len(all_sheets)
            all_sheets.append(s)
        all_unplaced.extend(unplaced)

    return NestResult(sheets=all_sheets, unplaced=all_unplaced)
