"""Nesting invariants: nothing lost, nothing overlapping, nothing off the sheet."""
from __future__ import annotations

import math

import pytest
from shapely import affinity

from plynest.config import NestSettings, SheetSpec
from plynest.geom2d import Contour, Point, Region
from plynest.nest import Placement, nest
from plynest.part import Part, Pocket


def make_part(pid: str, w: float, h: float, thickness: float = 18.0) -> Part:
    profile = Region(Contour.from_points([(0, 0), (w, 0), (w, h), (0, h)]))
    return Part(id=pid, label=pid, path=("T", pid), thickness=thickness, profile=profile)


def small_settings(**kw) -> NestSettings:
    base = dict(
        kerf_mm=5.0,
        edge_keepout_mm=10.0,
        sheet=SheetSpec(1000.0, 2000.0),
        attempts=2,
    )
    base.update(kw)
    return NestSettings(**base)


def placed_parts(result):
    return [p for sheet in result.sheets for p in sheet.placements]


# --- the core guarantee ----------------------------------------------------

def test_every_part_is_placed_exactly_once():
    parts = [make_part(f"p{i}", 200 + i * 7, 300 + i * 5) for i in range(20)]
    result = nest(parts, small_settings())
    assert result.unplaced == []
    ids = [p.part.id for p in placed_parts(result)]
    assert sorted(ids) == sorted(p.id for p in parts)
    assert len(ids) == len(set(ids)), "a part was placed twice"


def test_placed_parts_keep_their_dimensions():
    parts = [make_part(f"p{i}", 137.5 + i, 421.25 - i) for i in range(12)]
    result = nest(parts, small_settings())
    by_id = {p.id: p for p in parts}
    for placement in placed_parts(result):
        original = by_id[placement.part.id]
        x0, y0, x1, y1 = placement.bounds()
        got = sorted((round(x1 - x0, 6), round(y1 - y0, 6)))
        want = sorted((round(original.width, 6), round(original.height, 6)))
        assert got == pytest.approx(want, abs=1e-6), (
            f"{placement.part.id} changed size when placed at {placement.angle} deg"
        )
        assert placement.profile().area() == pytest.approx(original.area, rel=1e-9)


def test_no_two_parts_overlap_and_kerf_is_respected():
    parts = [make_part(f"p{i}", 150 + (i % 5) * 40, 220 + (i % 3) * 60) for i in range(24)]
    settings = small_settings(kerf_mm=8.0)
    result = nest(parts, settings)
    for sheet in result.sheets:
        polys = [p.polygon() for p in sheet.placements]
        for i in range(len(polys)):
            for j in range(i + 1, len(polys)):
                assert not polys[i].intersects(polys[j]), "parts overlap"
                gap = polys[i].distance(polys[j])
                assert gap >= settings.kerf_mm - 1e-6, (
                    f"gap {gap:.4f} mm is under the {settings.kerf_mm} mm kerf"
                )


def test_parts_stay_inside_the_edge_keepout():
    parts = [make_part(f"p{i}", 180, 260) for i in range(15)]
    settings = small_settings(edge_keepout_mm=25.0)
    result = nest(parts, settings)
    for sheet in result.sheets:
        kx0, ky0, kx1, ky1 = sheet.usable
        assert (kx0, ky0) == pytest.approx((25.0, 25.0))
        for placement in sheet.placements:
            x0, y0, x1, y1 = placement.bounds()
            assert x0 >= kx0 - 1e-6 and y0 >= ky0 - 1e-6
            assert x1 <= kx1 + 1e-6 and y1 <= ky1 + 1e-6


def test_different_thicknesses_never_share_a_sheet():
    parts = (
        [make_part(f"a{i}", 200, 300, thickness=18.0) for i in range(6)]
        + [make_part(f"b{i}", 200, 300, thickness=12.0) for i in range(6)]
        + [make_part(f"c{i}", 200, 300, thickness=6.0) for i in range(6)]
    )
    result = nest(parts, small_settings())
    for sheet in result.sheets:
        thicknesses = {p.part.thickness for p in sheet.placements}
        assert len(thicknesses) == 1
        assert sheet.thickness == pytest.approx(next(iter(thicknesses)))
    assert {round(s.thickness, 2) for s in result.sheets} == {18.0, 12.0, 6.0}


# --- rotation modes --------------------------------------------------------

@pytest.mark.parametrize("mode,allowed", [
    ("none", {0.0}),
    ("180", {0.0, 180.0}),
    ("90", {0.0, 90.0, 180.0, 270.0}),
])
def test_rotation_mode_is_obeyed(mode, allowed):
    parts = [make_part(f"p{i}", 150 + i * 3, 400) for i in range(10)]
    result = nest(parts, small_settings(rotation=mode))
    used = {p.angle for p in placed_parts(result)}
    assert used <= allowed


def test_no_rotation_keeps_every_part_upright():
    parts = [make_part(f"p{i}", 120, 700) for i in range(8)]
    result = nest(parts, small_settings(rotation="none"))
    for placement in placed_parts(result):
        x0, y0, x1, y1 = placement.bounds()
        assert (x1 - x0, y1 - y0) == pytest.approx((120.0, 700.0))


def test_rotation_lets_a_long_part_fit_across_the_sheet():
    """A 1500 mm part fits a 1000x2000 sheet only along its length."""
    part = make_part("long", 1500.0, 100.0)
    blocked = nest([part], small_settings(rotation="none"))
    assert blocked.unplaced and "exceeds" in blocked.unplaced[0][1]
    allowed = nest([part], small_settings(rotation="90"))
    assert allowed.unplaced == []
    assert placed_parts(allowed)[0].angle in (90.0, 270.0)


# --- robustness ------------------------------------------------------------

def test_oversized_part_is_reported_not_crashed():
    parts = [make_part("ok", 200, 200), make_part("huge", 5000, 5000)]
    result = nest(parts, small_settings())
    assert [p.id for p, _ in result.unplaced] == ["huge"]
    assert "exceeds" in result.unplaced[0][1]
    assert [p.part.id for p in placed_parts(result)] == ["ok"]


def test_keepout_larger_than_the_sheet_is_reported():
    result = nest([make_part("p", 100, 100)], small_settings(edge_keepout_mm=600.0))
    assert result.sheets == []
    assert len(result.unplaced) == 1
    assert "usable" in result.unplaced[0][1]


def test_zero_kerf_still_produces_a_valid_layout():
    parts = [make_part(f"p{i}", 200, 200) for i in range(9)]
    result = nest(parts, small_settings(kerf_mm=0.0))
    assert result.unplaced == []
    for sheet in result.sheets:
        polys = [p.polygon() for p in sheet.placements]
        for i in range(len(polys)):
            for j in range(i + 1, len(polys)):
                assert polys[i].intersection(polys[j]).area == pytest.approx(0.0, abs=1e-6)


def test_empty_input():
    result = nest([], small_settings())
    assert result.sheets == [] and result.unplaced == []
    assert result.total_utilisation() == 0.0


def test_nesting_is_deterministic():
    parts = [make_part(f"p{i}", 170 + i * 11, 240 + i * 3) for i in range(16)]
    a = nest(parts, small_settings())
    b = nest(parts, small_settings())
    key = lambda r: [
        (s.index, p.part.id, round(p.angle, 6), round(p.dx, 6), round(p.dy, 6))
        for s in r.sheets for p in sorted(s.placements, key=lambda q: q.part.id)
    ]
    assert key(a) == key(b)


def test_part_with_a_notch_lets_a_neighbour_tuck_in():
    """Nesting works on real outlines, so an L-shape is not treated as its bbox."""
    l_shape = Region(Contour.from_points(
        [(0, 0), (900, 0), (900, 400), (400, 400), (400, 1800), (0, 1800)]
    ))
    big = Part(id="L", label="L", path=("T", "L"), thickness=18.0, profile=l_shape)
    # Two fillers fit the 500 x 1400 notch but not the scraps around the L's
    # bounding box, so packing them on one sheet is only possible on outlines.
    filler = [make_part(f"f{i}", 460, 640) for i in range(2)]
    result = nest([big] + filler, small_settings(kerf_mm=4.0, rotation="none"))
    assert result.unplaced == []
    assert result.sheet_count() == 1, "the notch should have swallowed the fillers"
    notch = [p for p in result.sheets[0].placements if p.part.id != "L"]
    for placement in notch:
        x0, y0, _, _ = placement.bounds()
        assert x0 >= 400.0 and y0 >= 400.0, "filler did not land in the notch"


def test_utilisation_is_a_sane_fraction():
    parts = [make_part(f"p{i}", 300, 400) for i in range(10)]
    result = nest(parts, small_settings())
    assert 0.0 < result.total_utilisation() <= 1.0
    for sheet in result.sheets:
        assert 0.0 < sheet.utilisation() <= 1.0
