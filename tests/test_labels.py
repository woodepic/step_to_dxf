"""Engraved labels must land on solid top surface, never over a cut feature."""
from __future__ import annotations

import math

import pytest
from shapely.geometry import LineString, Point as ShPoint

from conftest import (
    as_loaded,
    plain_plate,
    plate_stepped_pocket,
    plate_with_rabbet,
    plate_with_through_hole,
)
from plynest.config import LabelSettings
from plynest.labels import _allowed_region, place_label
from plynest.orient import analyse


def flatten(shape):
    a = analyse(as_loaded(shape), "Part", part_id="t0")
    assert a.ok, a.messages
    return a.part


def stroke_geoms(placement):
    return [LineString([(p.x, p.y) for p in s]) for s in placement.sampled() if len(s) >= 2]


def test_label_sits_inside_the_part():
    part = flatten(plain_plate(400, 300, 18))
    placement = place_label(part, "AC4/FLOOR", LabelSettings())
    assert placement.fitted
    outline = part.profile.to_polygon()
    for geom in stroke_geoms(placement):
        assert outline.contains(geom)


def test_label_defaults_to_the_bottom_right():
    part = flatten(plain_plate(400, 300, 18))
    placement = place_label(part, "FLOOR", LabelSettings(corner="bottom_right"))
    x0, y0, x1, y1 = placement.bounds()
    assert x1 > 200, "should hug the right half"
    assert y0 < 150, "should hug the bottom half"


@pytest.mark.parametrize("corner,check", [
    ("bottom_left", lambda b: b[0] < 200 and b[1] < 150),
    ("top_right", lambda b: b[2] > 200 and b[3] > 150),
    ("top_left", lambda b: b[0] < 200 and b[3] > 150),
])
def test_other_corners(corner, check):
    part = flatten(plain_plate(400, 300, 18))
    placement = place_label(part, "FLOOR", LabelSettings(corner=corner))
    assert placement.fitted and check(placement.bounds())


def test_label_avoids_a_rabbet():
    """The default corner is inside the rabbet, so the text must move off it."""
    part = flatten(plate_with_rabbet(400, 300, 18, rabbet_w=120, rabbet_d=6))
    settings = LabelSettings(corner="bottom_left", clearance_mm=2.0)
    placement = place_label(part, "LEFT SIDE", settings)
    assert placement.fitted
    rabbet = part.pockets[0].region.to_polygon()
    for geom in stroke_geoms(placement):
        assert not geom.intersects(rabbet), "label was engraved into the rabbet"
        assert geom.distance(rabbet) >= settings.clearance_mm - 0.5


def test_label_avoids_through_holes():
    part = flatten(plate_with_through_hole(200, 200, 18, r=40, at=(150, 50)))
    placement = place_label(part, "PANEL", LabelSettings(corner="bottom_right"))
    assert placement.fitted
    assert len(part.profile.holes) == 1
    outline = part.profile.to_polygon()  # the hole is already cut out of this
    for geom in stroke_geoms(placement):
        assert outline.contains(geom)


def test_label_avoids_every_pocket_level():
    part = flatten(plate_stepped_pocket())
    placement = place_label(part, "STEPPED", LabelSettings(corner="bottom_right"))
    assert placement.fitted
    for pocket in part.pockets:
        poly = pocket.region.to_polygon()
        for geom in stroke_geoms(placement):
            assert not geom.intersects(poly)


def test_label_rotates_when_the_part_is_narrow():
    part = flatten(plain_plate(40, 600, 18))
    placement = place_label(part, "PEDESTAL LEFT", LabelSettings(height_mm=6.0))
    assert placement.fitted
    assert placement.angle == 90.0
    assert part.profile.to_polygon().contains(
        LineString([(p.x, p.y) for p in placement.sampled()[0]])
    )


def test_label_shrinks_before_giving_up():
    part = flatten(plain_plate(70, 40, 18))
    settings = LabelSettings(height_mm=10.0, allow_rotate=False, margin_mm=2.0)
    # At the requested height this name is ~88 mm wide on a 66 mm usable width.
    placement = place_label(part, "DRAWER SIDE", settings)
    assert placement.fitted
    assert placement.height < settings.height_mm
    assert "shrunk" in (placement.message or "")


def test_impossible_label_is_reported_not_silently_dropped():
    part = flatten(plain_plate(30, 20, 18))
    placement = place_label(part, "THIS NAME IS FAR TOO LONG TO ENGRAVE HERE", LabelSettings())
    assert not placement.fitted
    assert placement.paths == ()
    assert "does not fit" in placement.message


def test_labels_disabled_returns_nothing():
    part = flatten(plain_plate())
    assert place_label(part, "X", LabelSettings(enabled=False)) is None


def test_margin_keeps_the_text_off_the_edge():
    part = flatten(plain_plate(400, 300, 18))
    settings = LabelSettings(margin_mm=25.0)
    placement = place_label(part, "FLOOR", settings)
    x0, y0, x1, y1 = placement.bounds()
    assert x0 >= 25.0 - 1e-6 and y0 >= 25.0 - 1e-6
    assert x1 <= 400 - 25.0 + 1e-6 and y1 <= 300 - 25.0 + 1e-6


def test_placed_label_keeps_its_arcs():
    """Curves must survive placement, or the DXF gets a faceted chord chain."""
    from plynest.geom2d import Arc

    part = flatten(plain_plate(400, 300, 18))
    placement = place_label(part, "AC4/DA2/FLOOR", LabelSettings())
    arcs = [s for path in placement.paths for s in path if isinstance(s, Arc)]
    assert arcs, "letters with bowls should place real arcs"
    for arc in arcs:
        assert arc.radius > 0 and math.isfinite(arc.sweep())


def test_placed_label_paths_are_continuous():
    part = flatten(plain_plate(400, 300, 18))
    placement = place_label(part, "AC4/DA2/FLOOR", LabelSettings())
    for path in placement.paths:
        for a, b in zip(path, path[1:]):
            assert a.end.dist(b.start) < 1e-6, "a stroke is broken by a gap"


def test_allowed_region_excludes_pockets():
    part = flatten(plate_with_rabbet(400, 300, 18, rabbet_w=120, rabbet_d=6))
    region = _allowed_region(part, LabelSettings(margin_mm=0.0, clearance_mm=0.0))
    assert not region.contains(ShPoint(60, 150)), "rabbet area must be excluded"
    assert region.contains(ShPoint(300, 150))
