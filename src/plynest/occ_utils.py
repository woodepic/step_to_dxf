"""Thin helpers over OCP/OpenCASCADE so the rest of the code stays readable."""
from __future__ import annotations

import math

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
