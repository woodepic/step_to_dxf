"""Place an engraved part name where the router can actually cut it.

The label has to land on solid top surface: inside the outline, clear of every
pocket and through hole, and clear of the edge by a margin.  Rabbets in
particular eat the corner you would naively pick, so the search walks inward
from the preferred corner until the whole text box fits.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from .config import LabelSettings
from .font import text_extents, text_strokes
from .geom2d import ARC_CHORD_TOL, Point
from .part import Part

Stroke = tuple[Point, ...]


@dataclass
class LabelPlacement:
    text: str
    strokes: tuple[Stroke, ...]
    """Open polylines in the part's local frame."""

    height: float
    angle: float
    origin: Point
    fitted: bool = True
    message: str | None = None

    def bounds(self) -> tuple[float, float, float, float]:
        xs = [p.x for s in self.strokes for p in s]
        ys = [p.y for s in self.strokes for p in s]
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return min(xs), min(ys), max(xs), max(ys)


def _corner_priority(corner: str, region: Polygon, w: float, h: float,
                     step: float) -> list[tuple[float, float]]:
    """Candidate lower-left text positions, best first for the chosen corner."""
    x0, y0, x1, y1 = region.bounds
    max_x = x1 - w
    max_y = y1 - h
    if max_x < x0 or max_y < y0:
        return []

    nx = max(1, int((max_x - x0) / step) + 1)
    ny = max(1, int((max_y - y0) / step) + 1)
    xs = [x0 + i * step for i in range(nx)] + [max_x]
    ys = [y0 + i * step for i in range(ny)] + [max_y]
    xs = sorted(set(min(v, max_x) for v in xs))
    ys = sorted(set(min(v, max_y) for v in ys))

    prefer_right = "right" in corner
    prefer_top = "top" in corner
    if corner == "center":
        cx, cy = (x0 + max_x) / 2, (y0 + max_y) / 2
        return sorted(((x, y) for x in xs for y in ys),
                      key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)

    anchor_x = max_x if prefer_right else x0
    anchor_y = max_y if prefer_top else y0
    # Walk away from the corner, preferring to slide along the long edge first.
    return sorted(
        ((x, y) for x in xs for y in ys),
        key=lambda p: (abs(p[1] - anchor_y), abs(p[0] - anchor_x)),
    )


def _allowed_region(part: Part, settings: LabelSettings) -> Polygon:
    """Solid top surface, inset from the edge and away from every cut feature."""
    base = part.profile.to_polygon(ARC_CHORD_TOL)
    if settings.margin_mm > 0:
        base = base.buffer(-settings.margin_mm, join_style=2)
    if base.is_empty:
        return Polygon()
    if part.pockets:
        cuts = unary_union([p.region.to_polygon(ARC_CHORD_TOL) for p in part.pockets])
        if settings.clearance_mm > 0:
            cuts = cuts.buffer(settings.clearance_mm, join_style=2)
        base = base.difference(cuts)
    if base.is_empty:
        return Polygon()
    if base.geom_type == "MultiPolygon":
        base = max(base.geoms, key=lambda g: g.area)
    return base


def place_label(part: Part, text: str, settings: LabelSettings) -> LabelPlacement | None:
    """Fit ``text`` onto ``part``, shrinking or turning it only if it must."""
    if not settings.enabled or not text:
        return None

    region = _allowed_region(part, settings)
    if region.is_empty or region.area <= 0:
        return LabelPlacement(text, (), settings.height_mm, 0.0, Point(0, 0), False,
                              "no clear top surface for a label")

    for scale in (1.0, 0.8, 0.65, 0.5):
        height = settings.height_mm * scale
        if height < 1.0:
            break
        w, ascent, descent = text_extents(text, height, uppercase=settings.uppercase)
        total_h = ascent + descent
        angles = (0.0, 90.0) if settings.allow_rotate else (0.0,)
        for angle in angles:
            bw, bh = (w, total_h) if angle == 0.0 else (total_h, w)
            step = max(1.0, height * 0.5)
            for x, y in _corner_priority(settings.corner, region, bw, bh, step):
                if region.contains(box(x, y, x + bw, y + bh)):
                    strokes, _, _ = text_strokes(text, height, uppercase=settings.uppercase)
                    if angle == 0.0:
                        origin = Point(x, y + descent)
                        placed = tuple(
                            tuple(Point(px + origin.x, py + origin.y) for px, py in s)
                            for s in strokes
                        )
                    else:
                        # Rotate 90 deg CCW: (px, py) -> (-py, px).
                        origin = Point(x + bw - descent, y)
                        placed = tuple(
                            tuple(Point(origin.x - py, origin.y + px) for px, py in s)
                            for s in strokes
                        )
                    note = None if scale == 1.0 else f"label shrunk to {height:.1f} mm to fit"
                    return LabelPlacement(text, placed, height, angle, origin, True, note)

    return LabelPlacement(
        text, (), settings.height_mm, 0.0, Point(0, 0), False,
        f"'{text}' does not fit on the clear surface of this part",
    )
