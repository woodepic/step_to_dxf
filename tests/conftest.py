"""Synthetic solids for tests, so the suite does not depend on the sample file."""
from __future__ import annotations

import math
from pathlib import Path

import pytest
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

from plynest import occ_utils as occ
from plynest.step_loader import LoadedSolid

SAMPLE_STEP = Path(__file__).resolve().parents[1] / "Full Layout.step"

requires_sample = pytest.mark.skipif(
    not SAMPLE_STEP.exists(), reason="sample STEP file not present"
)


def box(x: float, y: float, z: float, at: tuple[float, float, float] = (0, 0, 0)):
    return BRepPrimAPI_MakeBox(gp_Pnt(*at), x, y, z).Shape()


def cylinder(radius: float, height: float, at: tuple[float, float, float] = (0, 0, 0)):
    axis = gp_Ax2(gp_Pnt(*at), gp_Dir(0, 0, 1))
    return BRepPrimAPI_MakeCylinder(axis, radius, height).Shape()


def cut(a, b):
    op = BRepAlgoAPI_Cut(a, b)
    op.Build()
    return op.Shape()


def first_solid(shape):
    ex = TopExp_Explorer(shape, TopAbs_SOLID)
    assert ex.More(), "shape has no solid"
    return TopoDS.Solid_s(ex.Current())


def as_loaded(shape, path=("Test", "Part"), index: int = 0) -> LoadedSolid:
    return LoadedSolid(path=tuple(path), shape=first_solid(shape), index=index)


def moved(shape, trsf: gp_Trsf):
    return occ.transform_shape(shape, trsf)


def rotate(shape, axis_dir: tuple[float, float, float], angle_deg: float):
    t = gp_Trsf()
    t.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(*axis_dir)), math.radians(angle_deg))
    return occ.transform_shape(shape, t)


def translate(shape, dx: float, dy: float, dz: float):
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(dx, dy, dz))
    return occ.transform_shape(shape, t)


# --- named fixtures --------------------------------------------------------

def plain_plate(w=400.0, h=300.0, t=18.0):
    """A featureless rectangular panel."""
    return box(w, h, t)


def plate_with_rabbet(w=400.0, h=300.0, t=18.0, rabbet_w=20.0, rabbet_d=6.0):
    """Panel with a rabbet along the x=0 edge, cut from the +Z face."""
    return cut(box(w, h, t), box(rabbet_w, h, rabbet_d, at=(0, 0, t - rabbet_d)))


def plate_with_dado(w=400.0, h=300.0, t=18.0, dado_w=18.0, dado_d=6.0, at_x=150.0):
    """Panel with a through-width groove in the +Z face."""
    return cut(box(w, h, t), box(dado_w, h, dado_d, at=(at_x, 0, t - dado_d)))


def plate_with_through_hole(w=400.0, h=300.0, t=18.0, r=10.0, at=(100.0, 100.0)):
    return cut(box(w, h, t), cylinder(r, t * 3, at=(at[0], at[1], -t)))


def plate_with_blind_hole(w=400.0, h=300.0, t=18.0, r=6.0, depth=8.0, at=(100.0, 100.0)):
    return cut(box(w, h, t), cylinder(r, depth + 1, at=(at[0], at[1], t - depth)))


def plate_two_sided(w=400.0, h=300.0, t=18.0):
    """Pockets in both faces -- cannot be finished without flipping the sheet."""
    s = cut(box(w, h, t), box(50, 50, 5, at=(20, 20, t - 5)))
    return cut(s, box(50, 50, 5, at=(300, 200, 0)))


def plate_stepped_pocket(w=400.0, h=300.0, t=18.0):
    """Two pockets at different depths, one inside the other."""
    s = cut(box(w, h, t), box(200, 150, 4, at=(50, 50, t - 4)))
    return cut(s, box(80, 60, 9, at=(100, 90, t - 9)))


# --- degenerate and awkward solids -----------------------------------------

def sphere(r=50.0, at=(0.0, 0.0, 0.0)):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeSphere

    return BRepPrimAPI_MakeSphere(gp_Pnt(*at), r).Shape()


def upright_cylinder(r=100.0, h=18.0):
    return cylinder(r, h)


def wedge(dx=200.0, dy=100.0, dz=18.0, ltx=80.0):
    """A box with one face sloped: non-vertical walls."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeWedge

    return BRepPrimAPI_MakeWedge(dx, dz, dy, ltx).Shape()


def plate_with_chamfered_top(w=300.0, h=200.0, t=18.0, c=4.0):
    """Plate whose top edge is chamfered all round."""
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    from plynest import occ_utils as occ

    solid = box(w, h, t)
    maker = BRepFilletAPI_MakeChamfer(solid)
    top = None
    for face in occ.faces(solid):
        plane = occ.face_plane(face)
        if plane and abs(plane[0][2] - 1.0) < 1e-6:
            top = face
            break
    ex = TopExp_Explorer(top, TopAbs_EDGE)
    while ex.More():
        maker.Add(c, c, TopoDS.Edge_s(ex.Current()), top)
        ex.Next()
    maker.Build()
    return maker.Shape()


def two_separate_bodies(w=400.0, h=300.0, t=18.0):
    """Two disjoint plates in one shape: a valid solid is connected, so this
    stays a compound and should load as two parts, not one broken one."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse

    op = BRepAlgoAPI_Fuse(box(w, h, t), box(w, h, t, at=(w * 2, 0, 0)))
    op.Build()
    return op.Shape()


def bar(a=20.0, b=20.0, length=400.0):
    """Two small dimensions and one long one: not a sheet part."""
    return box(a, b, length)


def round_plate(r=150.0, t=18.0):
    return cylinder(r, t)


def plate_with_slot_to_edge(w=400.0, h=300.0, t=18.0):
    """A through slot that breaks out of the outline -- a C shape."""
    return cut(box(w, h, t), box(100, 120, t * 3, at=(150, -10, -t)))


def tiny_plate(w=6.0, h=4.0, t=1.0):
    return box(w, h, t)


def write_step(named_shapes, path):
    """Write shapes to a STEP file with names, for building test fixtures."""
    from plynest.step_export import _write

    _write(list(named_shapes), path)
    return path


def messy_assembly(path):
    """A STEP file with the mix a real export throws at you.

    Good parts, a part that arrives face-down, a hole, something that is not a
    sheet part at all, and something too big for any sheet.
    """
    return write_step([
        ("Good Panel", plain_plate(400, 300, 18)),
        ("Face Down", rotate(plate_with_rabbet(400, 300, 18), (1, 0, 0), 180)),
        ("Holed", plate_with_through_hole(350, 250, 18, r=15)),
        ("Ball Bearing", sphere(40.0)),
        ("Steel Bar", bar(20, 20, 400)),
        ("Oversize Panel", plain_plate(3000, 2000, 18)),
        ("Thin Ply", plain_plate(300, 200, 6)),
    ], path)
