"""Orientation and flattening: the part must come out cut-side-up and correct."""
from __future__ import annotations

import math

import pytest

from conftest import (
    as_loaded,
    plain_plate,
    plate_stepped_pocket,
    plate_two_sided,
    plate_with_blind_hole,
    plate_with_dado,
    plate_with_rabbet,
    plate_with_through_hole,
    rotate,
    translate,
)
from plynest import occ_utils as occ
from plynest.orient import analyse


def flatten(shape, label="Part"):
    return analyse(as_loaded(shape), label, part_id="t0")


def test_plain_plate_flattens_to_its_footprint():
    a = flatten(plain_plate(400, 300, 18))
    assert a.ok
    p = a.part
    assert p.thickness == pytest.approx(18.0, abs=1e-6)
    assert p.width == pytest.approx(400.0, abs=1e-6)
    assert p.height == pytest.approx(300.0, abs=1e-6)
    assert p.pockets == ()
    assert p.profile.holes == ()
    assert p.area == pytest.approx(400 * 300, rel=1e-9)


def test_profile_starts_at_the_origin():
    a = flatten(translate(plain_plate(200, 100, 12), 517.0, -240.0, 88.0))
    assert a.ok
    x0, y0, x1, y1 = a.part.bounds()
    assert (x0, y0) == pytest.approx((0.0, 0.0), abs=1e-6)
    assert (x1, y1) == pytest.approx((200.0, 100.0), abs=1e-6)


@pytest.mark.parametrize("axis,angle", [
    ((1, 0, 0), 90), ((1, 0, 0), -90), ((0, 1, 0), 90),
    ((0, 1, 0), 180), ((0, 0, 1), 37), ((1, 1, 0), 90),
])
def test_sheet_axis_found_whatever_the_pose(axis, angle):
    """A panel lying on its side or edge must still flatten to 400x300x18."""
    a = flatten(rotate(plate_with_dado(400, 300, 18), axis, angle))
    assert a.ok, a.messages
    p = a.part
    assert p.thickness == pytest.approx(18.0, abs=1e-5)
    assert sorted((round(p.width, 4), round(p.height, 4))) == pytest.approx([300.0, 400.0], abs=1e-3)


def test_rabbet_face_ends_up_upward():
    """Cut features must be reachable from +Z, whichever way the part arrived."""
    upright = flatten(plate_with_rabbet())
    assert upright.ok and not upright.part.flipped
    assert len(upright.part.pockets) == 1

    upside_down = flatten(rotate(plate_with_rabbet(), (1, 0, 0), 180))
    assert upside_down.ok
    assert upside_down.part.flipped, "part arrived face-down and should be turned over"
    assert len(upside_down.part.pockets) == 1
    assert upside_down.part.pockets[0].depth == pytest.approx(6.0, abs=1e-6)
    # Same physical part, so same outline and same pocket size either way.
    assert upside_down.part.area == pytest.approx(upright.part.area, rel=1e-9)
    assert upside_down.part.pockets[0].region.area() == pytest.approx(
        upright.part.pockets[0].region.area(), rel=1e-6
    )


def test_pocket_depth_and_area():
    a = flatten(plate_with_rabbet(400, 300, 18, rabbet_w=20, rabbet_d=6))
    pocket = a.part.pockets[0]
    assert pocket.depth == pytest.approx(6.0, abs=1e-9)
    assert pocket.region.area() == pytest.approx(20 * 300, rel=1e-9)


def test_dado_is_one_pocket_not_three_faces():
    """UnifySameDomain must merge the split coplanar faces of a groove."""
    a = flatten(plate_with_dado())
    assert len(a.part.pockets) == 1
    assert a.part.pockets[0].region.area() == pytest.approx(18 * 300, rel=1e-9)


def test_through_hole_becomes_a_hole_in_the_profile():
    a = flatten(plate_with_through_hole(r=10.0))
    p = a.part
    assert len(p.profile.holes) == 1
    assert p.pockets == ()
    assert p.area == pytest.approx(400 * 300 - math.pi * 100, rel=1e-3)


def test_blind_hole_is_a_pocket_not_a_through_hole():
    a = flatten(plate_with_blind_hole(r=6.0, depth=8.0))
    p = a.part
    assert p.profile.holes == (), "a blind hole must not perforate the outline"
    assert len(p.pockets) == 1
    assert p.pockets[0].depth == pytest.approx(8.0, abs=1e-9)
    assert p.pockets[0].region.area() == pytest.approx(math.pi * 36, rel=1e-3)


def test_stepped_pocket_yields_two_depths():
    a = flatten(plate_stepped_pocket())
    depths = sorted(round(p.depth, 4) for p in a.part.pockets)
    assert depths == [4.0, 9.0]
    shallow = next(p for p in a.part.pockets if abs(p.depth - 4.0) < 1e-6)
    deep = next(p for p in a.part.pockets if abs(p.depth - 9.0) < 1e-6)
    # The shallow floor is the ring left around the deeper pocket.
    assert shallow.region.area() == pytest.approx(200 * 150 - 80 * 60, rel=1e-6)
    assert deep.region.area() == pytest.approx(80 * 60, rel=1e-6)


def test_two_sided_part_is_reported_not_silently_wrong():
    a = flatten(plate_two_sided())
    assert a.ok, "still nestable, but the operator must be told"
    assert any("flip" in m for m in a.part.warnings), a.part.warnings


def test_non_plate_solid_is_rejected():
    a = analyse(as_loaded(plain_plate(50, 50, 50)), "Cube", part_id="t0")
    assert not a.ok
    assert "not a sheet part" in " ".join(a.messages)


def test_volume_is_conserved_by_flattening():
    """The strongest single check: rebuild the solid's volume from the 2D data."""
    for shape in (
        plain_plate(), plate_with_rabbet(), plate_with_dado(),
        plate_with_through_hole(), plate_with_blind_hole(), plate_stepped_pocket(),
    ):
        a = flatten(shape)
        p = a.part
        rebuilt = p.thickness * p.profile.area() - sum(
            pk.region.area() * pk.depth for pk in p.pockets
        )
        assert rebuilt == pytest.approx(occ.volume(shape), rel=2e-3)
