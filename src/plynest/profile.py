"""Convert planar OCC faces into 2D Regions, keeping circles and arcs symbolic."""
from __future__ import annotations

import math

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepTools import BRepTools_WireExplorer
from OCP.GCPnts import GCPnts_QuasiUniformDeflection
from OCP.GeomAbs import GeomAbs_BSplineCurve, GeomAbs_Circle, GeomAbs_Line
from OCP.TopAbs import TopAbs_REVERSED
from OCP.TopoDS import TopoDS_Face, TopoDS_Wire

from . import occ_utils as occ
from .geom2d import ARC_CHORD_TOL, TAU, Arc, Contour, Line, Point, Region

WELD_TOL = 1e-6


def _wire_to_contour(wire: TopoDS_Wire, dx: float, dy: float) -> Contour | None:
    """Walk a wire in order, emitting Lines and Arcs in the XY plane."""
    segments: list[Line | Arc] = []
    explorer = BRepTools_WireExplorer(wire)
    while explorer.More():
        edge = explorer.Current()
        reversed_edge = explorer.Orientation() == TopAbs_REVERSED
        curve = BRepAdaptor_Curve(edge)
        kind = curve.GetType()
        u0, u1 = curve.FirstParameter(), curve.LastParameter()

        if kind == GeomAbs_Line:
            a, b = curve.Value(u0), curve.Value(u1)
            p0 = Point(a.X() + dx, a.Y() + dy)
            p1 = Point(b.X() + dx, b.Y() + dy)
            seg: Line | Arc = Line(p0, p1)
            if reversed_edge:
                seg = seg.reversed()
            if seg.start.dist(seg.end) > WELD_TOL:
                segments.append(seg)

        elif kind == GeomAbs_Circle:
            circ = curve.Circle()
            axis = circ.Axis().Direction()
            if abs(abs(axis.Z()) - 1.0) > 1e-6:
                return None  # circle out of plane; caller falls back
            center = circ.Location()
            c = Point(center.X() + dx, center.Y() + dy)
            r = circ.Radius()
            a = curve.Value(u0)
            b = curve.Value(u1)
            sa = math.atan2(a.Y() + dy - c.y, a.X() + dx - c.x)
            ea = math.atan2(b.Y() + dy - c.y, b.X() + dx - c.x)
            # The circle's own axis sets the parameter's sense of rotation.
            ccw = axis.Z() > 0
            full = abs((u1 - u0) - TAU) < 1e-7
            seg = Arc(c, r, sa % TAU, ea % TAU, ccw, full)
            if reversed_edge:
                seg = seg.reversed()
            segments.append(seg)

        else:
            # Splines and conics: flatten to a chord chain within tolerance.
            deflection = GCPnts_QuasiUniformDeflection(curve, ARC_CHORD_TOL, u0, u1)
            if not deflection.IsDone() or deflection.NbPoints() < 2:
                return None
            pts = [deflection.Value(i) for i in range(1, deflection.NbPoints() + 1)]
            chain = [Point(p.X() + dx, p.Y() + dy) for p in pts]
            if reversed_edge:
                chain.reverse()
            for i in range(len(chain) - 1):
                if chain[i].dist(chain[i + 1]) > WELD_TOL:
                    segments.append(Line(chain[i], chain[i + 1]))

        explorer.Next()

    if not segments:
        return None

    # Weld consecutive endpoints so downstream code can assume a closed chain.
    cleaned: list[Line | Arc] = []
    for seg in segments:
        if cleaned and cleaned[-1].end.dist(seg.start) > 1e-4:
            cleaned.append(Line(cleaned[-1].end, seg.start))
        cleaned.append(seg)
    if len(cleaned) > 1 and cleaned[-1].end.dist(cleaned[0].start) > 1e-4:
        cleaned.append(Line(cleaned[-1].end, cleaned[0].start))
    return Contour(tuple(cleaned))


def face_to_region(face: TopoDS_Face, dx: float = 0.0, dy: float = 0.0) -> Region | None:
    """Project a Z-normal planar face into XY, translated by (dx, dy)."""
    outer_wire, inner_wires = occ.face_wires(face)
    outer = _wire_to_contour(outer_wire, dx, dy)
    if outer is None:
        return None
    holes = []
    for w in inner_wires:
        c = _wire_to_contour(w, dx, dy)
        if c is not None:
            holes.append(c.oriented(False))
    return Region(outer.oriented(True), tuple(holes))


def in_plane_alignment_angle(faces: list[TopoDS_Face]) -> float:
    """Yaw (radians) that lands the parts's minimum bounding rectangle on the axes.

    Only straight edges are considered: for sheet goods the outline's dominant
    straight run is the edge you want square to the sheet.
    """
    from collections import defaultdict

    weights: dict[int, float] = defaultdict(float)
    for face in faces:
        outer, _ = occ.face_wires(face)
        explorer = BRepTools_WireExplorer(outer)
        while explorer.More():
            curve = BRepAdaptor_Curve(explorer.Current())
            if curve.GetType() == GeomAbs_Line:
                a = curve.Value(curve.FirstParameter())
                b = curve.Value(curve.LastParameter())
                vx, vy = b.X() - a.X(), b.Y() - a.Y()
                length = math.hypot(vx, vy)
                if length > 1e-6:
                    # Edge directions are mod 90 deg: a rectangle has two families.
                    ang = math.degrees(math.atan2(vy, vx)) % 90.0
                    weights[int(round(ang * 100))] += length
            explorer.Next()
    if not weights:
        return 0.0
    best = max(weights.items(), key=lambda kv: kv[1])[0] / 100.0
    if best > 45.0:
        best -= 90.0
    return math.radians(-best)
