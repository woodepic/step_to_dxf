"""The sheet-part model: a flat profile, a stack of pockets, and a thickness."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .geom2d import ARC_CHORD_TOL, Line, Region


@dataclass(frozen=True)
class Pocket:
    """Material removed from the top face down to ``depth`` (mm)."""

    depth: float
    region: Region

    @property
    def through(self) -> bool:
        return False


@dataclass
class Part:
    """One plywood component, flattened and oriented cut-side-up.

    Local frame: profile lies in XY with its bounding box starting at the
    origin; +Z (out of the page) is the face that meets the router bit.
    """

    id: str
    label: str
    path: tuple[str, ...]
    thickness: float
    profile: Region
    """Through-cut geometry: outer boundary plus any through holes."""

    pockets: tuple[Pocket, ...] = ()
    warnings: tuple[str, ...] = ()
    flipped: bool = False
    """True if the part was turned over relative to its pose in the assembly."""

    source_index: int = 0

    transform: Any = None
    """gp_Trsf taking the original STEP solid into this part's local frame.

    Applying it to the source solid reproduces the flattened pose exactly, which
    is what lets a STEP export re-pose the real geometry instead of re-modelling
    it from the 2D profile."""

    def bounds(self) -> tuple[float, float, float, float]:
        return self.profile.bounds()

    @property
    def width(self) -> float:
        x0, _, x1, _ = self.bounds()
        return x1 - x0

    @property
    def height(self) -> float:
        _, y0, _, y1 = self.bounds()
        return y1 - y0

    @property
    def area(self) -> float:
        return self.profile.area()

    def is_rectangle(self, tol: float = 1e-6) -> bool:
        """True when the outline is an axis-aligned rectangle.

        Holes do not matter: nesting collides on the solid outline, so a panel
        full of drilling is still a rectangle as far as packing is concerned.
        """
        segments = self.profile.outer.segments
        if len(segments) != 4 or not all(isinstance(s, Line) for s in segments):
            return False
        for seg in segments:
            if abs(seg.start.x - seg.end.x) > tol and abs(seg.start.y - seg.end.y) > tol:
                return False
        x0, y0, x1, y1 = self.profile.outer.bounds()
        return abs(abs(self.profile.outer.signed_area()) - (x1 - x0) * (y1 - y0)) <= max(
            tol, (x1 - x0) * (y1 - y0) * 1e-9
        )

    def depths(self) -> list[float]:
        """Distinct machining depths, shallowest first, through-cut last."""
        ds = sorted({round(p.depth, 4) for p in self.pockets})
        return ds + [round(self.thickness, 4)]

    def top_solid_region(self, tol: float = ARC_CHORD_TOL):
        """Top-face area untouched by any pocket -- where a label may live."""
        from shapely.ops import unary_union

        base = self.profile.to_polygon(tol)
        if not self.pockets:
            return base
        cut = unary_union([p.region.to_polygon(tol) for p in self.pockets])
        return base.difference(cut)


@dataclass
class PartAnalysis:
    """Everything learned about one solid, including why it may be unusable."""

    part: Part | None
    ok: bool
    messages: tuple[str, ...] = ()
    source_path: tuple[str, ...] = ()
    source_index: int = 0
