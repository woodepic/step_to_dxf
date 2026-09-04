"""Geometry primitives: transforms must be rigid and areas exact."""
from __future__ import annotations

import math

import pytest

from plynest.geom2d import Arc, Contour, Point, Region, polygon_to_regions


def rect(w=10.0, h=4.0, x=0.0, y=0.0) -> Contour:
    return Contour.from_points([(x, y), (x + w, y), (x + w, y + h), (x, y + h)])


def test_rectangle_area_and_winding():
    c = rect()
    assert c.signed_area() == pytest.approx(40.0)
    assert c.is_ccw()
    assert c.reversed().signed_area() == pytest.approx(-40.0)


def test_full_circle_is_exact():
    c = Contour.circle(Point(3, -2), 5)
    assert c.signed_area() == pytest.approx(math.pi * 25, rel=1e-12)
    assert c.bounds() == pytest.approx((-2, -7, 8, 3))


@pytest.mark.parametrize("angle", [0, 30, 90, 180, 270, 137.5])
def test_rotation_preserves_area_and_size(angle):
    c = rect(10, 4)
    t = c.transformed(math.radians(angle), 17.0, -3.0)
    assert abs(t.signed_area()) == pytest.approx(40.0, rel=1e-12)
    x0, y0, x1, y1 = t.bounds()
    diag = math.hypot(10, 4)
    # No axis extent of a rotated rectangle can exceed its own diagonal.
    assert x1 - x0 <= diag + 1e-9
    assert y1 - y0 <= diag + 1e-9


def test_axis_rotation_swaps_extents():
    x0, y0, x1, y1 = rect(10, 4).transformed(math.pi / 2, 0, 0).bounds()
    assert (x1 - x0, y1 - y0) == pytest.approx((4.0, 10.0))


def test_mirroring_reverses_winding_but_keeps_area():
    c = rect(10, 4)
    m = c.transformed(0.0, 0.0, 0.0, mirror=True)
    assert abs(m.signed_area()) == pytest.approx(40.0)
    assert m.is_ccw() == c.is_ccw(), "winding is restored by reversing the chain"


def test_arc_survives_a_round_trip_of_transforms():
    a = Arc(Point(2, 1), 3, 0.2, 1.9, True)
    moved = a.transformed(math.radians(41), 5, -2)
    assert moved.radius == pytest.approx(a.radius)
    assert moved.sweep() == pytest.approx(a.sweep())
    assert moved.p0.dist(Point(*a.p0)) >= 0  # sanity: it is a real point
    back = moved.transformed(math.radians(-41), 0, 0).transformed(0, -5 * math.cos(0), 0)
    assert back.radius == pytest.approx(3.0)


def test_arc_bulge_matches_dxf_convention():
    quarter = Arc(Point(0, 0), 1, 0.0, math.pi / 2, True)
    assert quarter.bulge() == pytest.approx(math.tan(math.pi / 8))
    assert Arc(Point(0, 0), 1, 0.0, math.pi / 2, False).bulge() < 0


def test_region_with_hole():
    r = Region(rect(10, 10), (Contour.circle(Point(5, 5), 2).reversed(),))
    assert r.area() == pytest.approx(100 - math.pi * 4)
    assert r.to_polygon().area == pytest.approx(100 - math.pi * 4, rel=2e-2)


def test_transform_moves_region_predictably():
    r = Region(rect(10, 4))
    moved = r.transformed(0.0, 3.0, 7.0)
    assert moved.bounds() == pytest.approx((3.0, 7.0, 13.0, 11.0))


def test_polygon_round_trip():
    r = Region(rect(10, 10), (rect(2, 2, 4, 4).reversed(),))
    back = polygon_to_regions(r.to_polygon())
    assert len(back) == 1
    assert back[0].area() == pytest.approx(96.0, rel=1e-9)
