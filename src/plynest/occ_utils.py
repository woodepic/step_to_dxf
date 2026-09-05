"""Thin helpers over OCP/OpenCASCADE so the rest of the code stays readable."""
from __future__ import annotations

import math
from contextlib import contextmanager

from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepGProp import BRepGProp
from OCP.BRepTools import BRepTools
from OCP.Bnd import Bnd_Box
from OCP.GeomAbs import GeomAbs_Plane
from OCP.GProp import GProp_GProps
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED, TopAbs_WIRE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Face, TopoDS_Shape, TopoDS_Wire
from OCP.gp import gp_Ax3, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec


def faces(shape: TopoDS_Shape) -> list[TopoDS_Face]:
    out = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        out.append(TopoDS.Face_s(ex.Current()))
        ex.Next()
    return out


def face_area(face: TopoDS_Face) -> float:
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    return props.Mass()


def volume(shape: TopoDS_Shape) -> float:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def bbox(shape: TopoDS_Shape, tol: float = 1e-7) -> tuple[float, ...]:
    box = Bnd_Box()
    box.SetGap(0.0)
    BRepBndLib.Add_s(shape, box, True)
    return box.Get()


def face_plane(face: TopoDS_Face):
    """Return ``(outward_normal, point_on_plane)`` for a planar face, else None.

    The normal accounts for the face's orientation flag, so it genuinely points
    out of the solid.
    """
    surf = BRepAdaptor_Surface(face)
    if surf.GetType() != GeomAbs_Plane:
        return None
    pln = surf.Plane()
    axis = pln.Axis().Direction()
    n = (axis.X(), axis.Y(), axis.Z())
    if face.Orientation() == TopAbs_REVERSED:
        n = (-n[0], -n[1], -n[2])
    loc = pln.Location()
    return n, (loc.X(), loc.Y(), loc.Z())


def unify(shape: TopoDS_Shape) -> TopoDS_Shape:
    """Merge coplanar/tangent faces so each planar level is a single face.

    Without this, a rabbet floor split into three coplanar faces by construction
    history would be read as three separate pockets.
    """
    try:
        unifier = ShapeUpgrade_UnifySameDomain(shape, True, True, True)
        unifier.Build()
        result = unifier.Shape()
        return result if not result.IsNull() else shape
    except Exception:
        return shape


def transform_shape(shape: TopoDS_Shape, trsf: gp_Trsf) -> TopoDS_Shape:
    builder = BRepBuilderAPI_Transform(shape, trsf, True)
    return builder.Shape()


def align_trsf(normal: tuple[float, float, float]) -> gp_Trsf:
    """Rotation mapping ``normal`` onto +Z (about the origin)."""
    trsf = gp_Trsf()
    src = gp_Ax3(gp_Pnt(0, 0, 0), gp_Dir(*normal))
    dst = gp_Ax3(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
    trsf.SetTransformation(dst, src)
    return trsf


def translation(dx: float, dy: float, dz: float) -> gp_Trsf:
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(dx, dy, dz))
    return t


def rotation_x180() -> gp_Trsf:
    t = gp_Trsf()
    from OCP.gp import gp_Ax1

    t.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)), math.pi)
    return t


def rotation_z(angle: float) -> gp_Trsf:
    t = gp_Trsf()
    from OCP.gp import gp_Ax1

    t.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), angle)
    return t


def face_wires(face: TopoDS_Face) -> tuple[TopoDS_Wire, list[TopoDS_Wire]]:
    """Return ``(outer_wire, inner_wires)`` for a face."""
    outer = BRepTools.OuterWire_s(face)
    inners = []
    ex = TopExp_Explorer(face, TopAbs_WIRE)
    while ex.More():
        w = TopoDS.Wire_s(ex.Current())
        if not w.IsSame(outer):
            inners.append(w)
        ex.Next()
    return outer, inners


def face_from_polygon(poly, z: float = 0.0, area_tol: float = 1e-3):
    """Build a planar face at height ``z`` from a shapely Polygon (holes kept).

    Returns None if the face does not come out with the polygon's area -- a
    face whose holes failed to subtract makes the subsequent boolean quietly do
    nothing, which is far worse than skipping it loudly.
    """
    from shapely.geometry.polygon import orient

    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeFace,
        BRepBuilderAPI_MakePolygon,
    )

    poly = orient(poly, 1.0)

    def wire(coords):
        builder = BRepBuilderAPI_MakePolygon()
        pts = list(coords)
        if len(pts) > 1 and abs(pts[0][0] - pts[-1][0]) < 1e-12 and abs(pts[0][1] - pts[-1][1]) < 1e-12:
            pts = pts[:-1]
        if len(pts) < 3:
            return None
        for x, y in pts:
            builder.Add(gp_Pnt(x, y, z))
        builder.Close()
        return builder.Wire() if builder.IsDone() else None

    outer = wire(poly.exterior.coords)
    if outer is None:
        return None
    maker = BRepBuilderAPI_MakeFace(outer, True)
    for ring in poly.interiors:
        inner = wire(ring.coords)
        if inner is not None:
            # Add() orients an inner wire as a hole itself; reversing it first
            # makes the "hole" add area instead of removing it.
            maker.Add(inner)
    if not maker.IsDone():
        return None
    face = maker.Face()
    if abs(face_area(face) - poly.area) > max(area_tol, poly.area * 1e-6):
        return None
    return face


def prism(face, dz: float):
    """Extrude a face by ``dz`` along +Z."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism

    return BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, dz), False, True).Shape()


def cut_many(base, tools: list):
    """Subtract every shape in ``tools`` from ``base`` in one boolean."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.TopTools import TopTools_ListOfShape

    if not tools:
        return base
    args = TopTools_ListOfShape()
    args.Append(base)
    cutters = TopTools_ListOfShape()
    for t in tools:
        cutters.Append(t)
    op = BRepAlgoAPI_Cut()
    op.SetArguments(args)
    op.SetTools(cutters)
    op.SetRunParallel(True)
    op.Build()
    if not op.IsDone():
        return base
    return op.Shape()


def compound(shapes: list):
    """Gather shapes into a single TopoDS_Compound."""
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    comp = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(comp)
    for s in shapes:
        if s is not None and not s.IsNull():
            builder.Add(comp, s)
    return comp


@contextmanager
def quiet():
    """Suppress OpenCASCADE's console banners.

    The STEP writer prints a transfer-statistics block for every shape, which
    buries anything useful in a 100-part export.
    """
    from OCP.Message import Message

    messenger = Message.DefaultMessenger_s()
    printers = messenger.Printers()
    saved = [printers.Value(i) for i in range(printers.Lower(), printers.Upper() + 1)]
    for printer in saved:
        messenger.RemovePrinter(printer)
    try:
        yield
    finally:
        for printer in saved:
            messenger.AddPrinter(printer)
