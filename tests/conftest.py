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
