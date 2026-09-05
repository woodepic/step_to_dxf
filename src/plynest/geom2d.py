"""Planar geometry primitives that survive rigid transforms with arcs intact.

Everything downstream of the STEP reader works in this representation:
millimetres, Y-up, angles in radians CCW from +X.  Keeping arcs symbolic (rather
than tessellating at read time) means the exported DXF contains real ARC/bulge
geometry, which is what a router's CAM wants.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

from shapely.geometry import LinearRing, Polygon
from shapely.geometry.base import BaseGeometry

TAU = 2.0 * math.pi

# Chordal tolerance used whenever an arc must be flattened (collision tests,
# area maths, SVG preview).  0.05 mm is well under router positioning accuracy.
ARC_CHORD_TOL = 0.05


def _norm_angle(a: float) -> float:
    """Wrap to [0, 2pi)."""
    a = math.fmod(a, TAU)
    return a + TAU if a < 0 else a


@dataclass(frozen=True)
class Point:
    x: float
    y: float

    def __iter__(self):
        yield self.x
        yield self.y

    def rotated(self, ang: float) -> "Point":
        c, s = math.cos(ang), math.sin(ang)
        return Point(self.x * c - self.y * s, self.x * s + self.y * c)

    def mirrored_x(self) -> "Point":
        """Reflect across the Y axis (x -> -x)."""
        return Point(-self.x, self.y)

    def translated(self, dx: float, dy: float) -> "Point":
        return Point(self.x + dx, self.y + dy)

    def dist(self, other: "Point") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


@dataclass(frozen=True)
class Line:
    start: Point
    end: Point

    @property
    def p0(self) -> Point:
        return self.start

    @property
    def p1(self) -> Point:
        return self.end

    def reversed(self) -> "Line":
        return Line(self.end, self.start)

    def transformed(self, ang: float, dx: float, dy: float, mirror: bool = False) -> "Line":
        def t(p: Point) -> Point:
            if mirror:
                p = p.mirrored_x()
            return p.rotated(ang).translated(dx, dy)

        return Line(t(self.start), t(self.end))

    def sample(self, tol: float = ARC_CHORD_TOL) -> list[Point]:
        return [self.start, self.end]

    def bounds(self) -> tuple[float, float, float, float]:
        return (
            min(self.start.x, self.end.x),
            min(self.start.y, self.end.y),
            max(self.start.x, self.end.x),
            max(self.start.y, self.end.y),
        )

    def area_correction(self) -> float:
        return 0.0

    def length(self) -> float:
        return self.start.dist(self.end)


@dataclass(frozen=True)
class Arc:
    """Circular arc travelling from ``start_angle`` to ``end_angle``.

    ``ccw`` records the sweep direction; the swept angle is always taken as the
    positive difference in that direction, so a full circle is represented with
    ``start_angle == end_angle`` and ``full=True``.
    """

    center: Point
    radius: float
    start_angle: float
    end_angle: float
    ccw: bool = True
    full: bool = False

    @property
    def p0(self) -> Point:
        return self._at(self.start_angle)

    @property
    def p1(self) -> Point:
        return self._at(self.end_angle)

    @property
    def start(self) -> Point:
        return self.p0

    @property
    def end(self) -> Point:
        return self.p1

    def _at(self, ang: float) -> Point:
        return Point(
            self.center.x + self.radius * math.cos(ang),
            self.center.y + self.radius * math.sin(ang),
        )

    def sweep(self) -> float:
        """Signed swept angle: positive CCW, negative CW."""
        if self.full:
            return TAU if self.ccw else -TAU
        if self.ccw:
            d = _norm_angle(self.end_angle - self.start_angle)
        else:
            d = -_norm_angle(self.start_angle - self.end_angle)
        if abs(d) < 1e-12:
            d = TAU if self.ccw else -TAU
        return d

    def reversed(self) -> "Arc":
        return Arc(
            self.center,
            self.radius,
            self.end_angle,
            self.start_angle,
            not self.ccw,
            self.full,
        )

    def transformed(self, ang: float, dx: float, dy: float, mirror: bool = False) -> "Arc":
        c = self.center
        sa, ea, ccw = self.start_angle, self.end_angle, self.ccw
        if mirror:
            # x -> -x maps angle t to pi - t and reverses the sense of rotation.
            c = c.mirrored_x()
            sa, ea = math.pi - sa, math.pi - ea
            ccw = not ccw
        c = c.rotated(ang).translated(dx, dy)
        return Arc(c, self.radius, _norm_angle(sa + ang), _norm_angle(ea + ang), ccw, self.full)

    def sample(self, tol: float = ARC_CHORD_TOL) -> list[Point]:
        sweep = self.sweep()
        # Segments needed to hold the chordal deviation under ``tol``.
        if self.radius <= tol:
            steps = 8
        else:
            max_step = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - tol / self.radius)))
            steps = max(2, int(math.ceil(abs(sweep) / max(max_step, 1e-6))))
        steps = min(steps, 720)
        return [self._at(self.start_angle + sweep * i / steps) for i in range(steps + 1)]

    def bulge(self) -> float:
        """DXF LWPOLYLINE bulge factor for this arc: tan(sweep / 4)."""
        return math.tan(self.sweep() / 4.0)

    def contains_angle(self, ang: float) -> bool:
        """Does ``ang`` fall inside the swept range?"""
        if self.full:
            return True
        sweep = self.sweep()
        if sweep >= 0:
            return _norm_angle(ang - self.start_angle) <= sweep + 1e-12
        return _norm_angle(self.start_angle - ang) <= -sweep + 1e-12

    def bounds(self) -> tuple[float, float, float, float]:
        """Exact bounds: the endpoints plus whichever cardinal points are swept."""
        pts = [self.p0, self.p1]
        for i in range(4):
            ang = i * math.pi / 2.0
            if self.contains_angle(ang):
                pts.append(self._at(ang))
        xs = [p.x for p in pts]
        ys = [p.y for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def area_correction(self) -> float:
        """Signed area of the circular segment between this arc and its chord.

        Adding this to the shoelace area of the chord polygon gives the region's
        exact area, so a circle measures pi*r^2 rather than an inscribed n-gon.
        """
        theta = self.sweep()
        return 0.5 * self.radius * self.radius * (theta - math.sin(theta))

    def length(self) -> float:
        return abs(self.sweep()) * self.radius

    def split(self, pieces: int = 2) -> list["Arc"]:
        """Divide the sweep into ``pieces`` arcs that chain end to start."""
        if pieces < 2:
            return [self]
        sweep = self.sweep()
        step = sweep / pieces
        out = []
        for i in range(pieces):
            a0 = self.start_angle + step * i
            a1 = a0 + step
            out.append(Arc(self.center, self.radius, a0 % TAU, a1 % TAU,
                           ccw=step > 0, full=False))
        return out


def split_wide_arcs(segments: Iterable["Segment"]) -> list["Segment"]:
    """Break arcs sweeping more than 180 degrees into halves.

    A polyline bulge is tan(sweep/4), which blows up towards a full turn and
    exceeds 1 for any arc over a half turn.  Some CAM post-processors mishandle
    those, so keep every emitted arc at a half turn or less.
    """
    out: list[Segment] = []
    for seg in segments:
        if isinstance(seg, Arc):
            sweep = abs(seg.sweep())
            if sweep > math.pi + 1e-9:
                out.extend(seg.split(int(math.ceil(sweep / math.pi))))
                continue
        out.append(seg)
    return out


Segment = Line | Arc


@dataclass(frozen=True)
class Contour:
    """A closed chain of segments. Vertices are shared end-to-start."""

    segments: tuple[Segment, ...]

    @staticmethod
    def from_points(points: Sequence[Point | tuple[float, float]]) -> "Contour":
        pts = [p if isinstance(p, Point) else Point(*p) for p in points]
        if len(pts) >= 2 and pts[0].dist(pts[-1]) < 1e-9:
            pts = pts[:-1]
        segs = [Line(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]
        return Contour(tuple(segs))

    @staticmethod
    def circle(center: Point, radius: float, ccw: bool = True) -> "Contour":
        return Contour((Arc(center, radius, 0.0, 0.0, ccw, full=True),))

    def transformed(self, ang: float, dx: float, dy: float, mirror: bool = False) -> "Contour":
        segs = tuple(s.transformed(ang, dx, dy, mirror) for s in self.segments)
        if mirror:
            # Mirroring reverses winding; flip the chain so it stays consistent.
            segs = tuple(s.reversed() for s in reversed(segs))
        return Contour(segs)

    def sample(self, tol: float = ARC_CHORD_TOL) -> list[Point]:
        pts: list[Point] = []
        for seg in self.segments:
            spts = seg.sample(tol)
            if pts and pts[-1].dist(spts[0]) < 1e-9:
                spts = spts[1:]
            pts.extend(spts)
        if len(pts) > 1 and pts[0].dist(pts[-1]) < 1e-9:
            pts.pop()
        return pts

    def is_degenerate(self, tol: float = ARC_CHORD_TOL) -> bool:
        """True when this contour encloses nothing shapely could work with."""
        pts = self.sample(tol)
        if len(pts) < 3:
            return True
        return abs(self.signed_area(tol)) < 1e-12

    def to_ring(self, tol: float = ARC_CHORD_TOL) -> LinearRing | None:
        if self.is_degenerate(tol):
            return None
        return LinearRing([(p.x, p.y) for p in self.sample(tol)])

    def signed_area(self, tol: float = ARC_CHORD_TOL) -> float:
        """Exact signed area: shoelace over the chord polygon plus arc segments."""
        verts = [seg.start for seg in self.segments]
        n = len(verts)
        a = 0.0
        for i in range(n):
            p, q = verts[i], verts[(i + 1) % n]
            a += p.x * q.y - q.x * p.y
        a /= 2.0
        return a + sum(seg.area_correction() for seg in self.segments)

    def is_ccw(self, tol: float = ARC_CHORD_TOL) -> bool:
        return self.signed_area(tol) > 0

    def reversed(self) -> "Contour":
        return Contour(tuple(s.reversed() for s in reversed(self.segments)))

    def oriented(self, ccw: bool) -> "Contour":
        return self if self.is_ccw() == ccw else self.reversed()

    def bounds(self, tol: float = ARC_CHORD_TOL) -> tuple[float, float, float, float]:
        """Exact bounds, including the bulge of any arc."""
        return bounds_union(seg.bounds() for seg in self.segments)

    def length(self) -> float:
        return sum(s.length() for s in self.segments)


@dataclass(frozen=True)
class Region:
    """An outer boundary with zero or more holes."""

    outer: Contour
    holes: tuple[Contour, ...] = ()

    def transformed(self, ang: float, dx: float, dy: float, mirror: bool = False) -> "Region":
        return Region(
            self.outer.transformed(ang, dx, dy, mirror),
            tuple(h.transformed(ang, dx, dy, mirror) for h in self.holes),
        )

    def to_polygon(self, tol: float = ARC_CHORD_TOL) -> Polygon:
        """Shapely form of this region, or an empty polygon if it is degenerate.

        A collapsed outline (a repeated point, a zero-area sliver) would
        otherwise raise out of shapely deep inside the nester.
        """
        if self.outer.is_degenerate(tol):
            return Polygon()
        holes = [
            [(p.x, p.y) for p in h.sample(tol)]
            for h in self.holes
            if not h.is_degenerate(tol)
        ]
        poly = Polygon([(p.x, p.y) for p in self.outer.sample(tol)], holes)
        if not poly.is_valid:
            poly = poly.buffer(0)
        return poly if isinstance(poly, Polygon) else Polygon()

    def bounds(self, tol: float = ARC_CHORD_TOL) -> tuple[float, float, float, float]:
        return self.outer.bounds(tol)

    def area(self, tol: float = ARC_CHORD_TOL) -> float:
        return abs(self.outer.signed_area(tol)) - sum(abs(h.signed_area(tol)) for h in self.holes)

    def contours(self) -> tuple[Contour, ...]:
        return (self.outer,) + self.holes

    def has_arcs(self) -> bool:
        return any(isinstance(seg, Arc) for c in self.contours() for seg in c.segments)


def regions_to_multipolygon(regions: Iterable[Region], tol: float = ARC_CHORD_TOL) -> BaseGeometry:
    from shapely.ops import unary_union

    polys = [r.to_polygon(tol) for r in regions]
    return unary_union(polys) if polys else Polygon()


def polygon_to_regions(geom: BaseGeometry) -> list[Region]:
    """Convert a shapely (Multi)Polygon back into line-only Regions."""
    from shapely.geometry import MultiPolygon

    out: list[Region] = []
    polys = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    for p in polys:
        if p.is_empty or not isinstance(p, Polygon):
            continue
        outer = Contour.from_points([Point(x, y) for x, y in p.exterior.coords])
        holes = tuple(
            Contour.from_points([Point(x, y) for x, y in i.coords]) for i in p.interiors
        )
        out.append(Region(outer.oriented(True), tuple(h.oriented(False) for h in holes)))
    return out


def bounds_union(
    all_bounds: Iterable[tuple[float, float, float, float]]
) -> tuple[float, float, float, float]:
    bs = list(all_bounds)
    if not bs:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        min(b[0] for b in bs),
        min(b[1] for b in bs),
        max(b[2] for b in bs),
        max(b[3] for b in bs),
    )
