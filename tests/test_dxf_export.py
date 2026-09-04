"""Read the exported DXF back and check it says what the layout says."""
from __future__ import annotations

import math
from collections import Counter

import ezdxf
import pytest

from conftest import (
    as_loaded,
    plain_plate,
    plate_stepped_pocket,
    plate_with_rabbet,
    plate_with_through_hole,
)
from plynest.config import ExportSettings, NestSettings, SheetSpec
from plynest.dxf_export import export
from plynest.nest import nest
from plynest.orient import analyse
from plynest.units import MM_PER_INCH


def build(shapes, **nest_kw):
    parts = []
    for i, shape in enumerate(shapes):
        a = analyse(as_loaded(shape, index=i), f"PART{i}", part_id=f"p{i}")
        assert a.ok, a.messages
        parts.append(a.part)
    settings = NestSettings(kerf_mm=5.0, edge_keepout_mm=10.0,
                            sheet=SheetSpec(1000.0, 2000.0), attempts=2, **nest_kw)
    return parts, nest(parts, settings)


def read(path):
    doc = ezdxf.readfile(path)
    return doc, list(doc.modelspace())


def closed_polys(entities, layer_prefix):
    out = []
    for e in entities:
        if not e.dxf.layer.startswith(layer_prefix):
            continue
        if e.dxftype() == "LWPOLYLINE" and e.closed:
            pts = [(p[0], p[1]) for p in e.get_points("xy")]
            out.append(pts)
        elif e.dxftype() == "CIRCLE":
            c, r = e.dxf.center, e.dxf.radius
            out.append([(c.x - r, c.y - r), (c.x + r, c.y + r)])
    return out


def extents(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return round(max(xs) - min(xs), 4), round(max(ys) - min(ys), 4)


# --- the guarantee the operator cares about --------------------------------

def test_every_part_appears_in_the_dxf_at_the_right_size(tmp_path):
    shapes = [plain_plate(300 + i * 20, 200 + i * 15, 18) for i in range(8)]
    parts, result = build(shapes)
    paths = export(result, ExportSettings(unit="mm", mode="per_sheet"), tmp_path)

    found: Counter[tuple[float, float]] = Counter()
    for path in paths:
        _, entities = read(path)
        for pts in closed_polys(entities, "CUT_THROUGH"):
            w, h = extents(pts)
            found[tuple(sorted((w, h)))] += 1

    expected: Counter[tuple[float, float]] = Counter()
    for part in parts:
        expected[tuple(sorted((round(part.width, 4), round(part.height, 4))))] += 1

    assert found == expected, "a part is missing, duplicated, or the wrong size"


def test_units_conversion_to_inches(tmp_path):
    parts, result = build([plain_plate(254.0, 508.0, 18)])
    paths = export(result, ExportSettings(unit="in", mode="per_sheet"), tmp_path)
    doc, entities = read(paths[0])
    assert doc.header["$INSUNITS"] == 1
    w, h = extents(closed_polys(entities, "CUT_THROUGH")[0])
    assert (w, h) == pytest.approx((10.0, 20.0), abs=1e-6)


def test_units_stay_millimetres_when_asked(tmp_path):
    parts, result = build([plain_plate(254.0, 508.0, 18)])
    paths = export(result, ExportSettings(unit="mm", mode="per_sheet"), tmp_path)
    doc, entities = read(paths[0])
    assert doc.header["$INSUNITS"] == 4
    w, h = extents(closed_polys(entities, "CUT_THROUGH")[0])
    assert (w, h) == pytest.approx((254.0, 508.0), abs=1e-6)


def test_layer_per_depth(tmp_path):
    parts, result = build([plate_stepped_pocket(400, 300, 18)])
    paths = export(result, ExportSettings(unit="mm", mode="per_sheet"), tmp_path)
    doc, _ = read(paths[0])
    names = {l.dxf.name for l in doc.layers}
    assert "CUT_THROUGH_18" in names
    assert "POCKET_4" in names
    assert "POCKET_9" in names


def test_through_hole_becomes_a_circle_entity(tmp_path):
    parts, result = build([plate_with_through_hole(300, 300, 18, r=12.5, at=(150, 150))])
    paths = export(result, ExportSettings(unit="mm", mode="per_sheet"), tmp_path)
    _, entities = read(paths[0])
    circles = [e for e in entities if e.dxftype() == "CIRCLE"]
    assert len(circles) == 1, "an arc must survive as an arc, not a chord chain"
    assert circles[0].dxf.radius == pytest.approx(12.5, rel=1e-9)
    assert circles[0].dxf.layer.startswith("CUT_THROUGH")


def test_per_depth_mode_splits_the_files(tmp_path):
    parts, result = build([plate_stepped_pocket(400, 300, 18)])
    paths = export(result, ExportSettings(unit="mm", mode="per_depth", include_labels=False),
                   tmp_path)
    assert len(paths) == 3, "one file each for 4 mm, 9 mm and the through cut"
    depth_layers = []
    for path in paths:
        doc, entities = read(path)
        cut = {e.dxf.layer for e in entities
               if e.dxf.layer.startswith(("CUT_", "POCKET_"))}
        assert len(cut) == 1, f"{path.name} mixes depths"
        depth_layers.append(cut.pop())
    assert sorted(depth_layers) == ["CUT_THROUGH_18", "POCKET_4", "POCKET_9"]


def test_single_file_mode_holds_every_sheet_side_by_side(tmp_path):
    shapes = [plain_plate(900, 1900, 18) for _ in range(3)]
    parts, result = build(shapes)
    assert result.sheet_count() == 3
    paths = export(result, ExportSettings(unit="mm", mode="single_file"), tmp_path)
    assert len(paths) == 1
    _, entities = read(paths[0])
    outlines = closed_polys(entities, "CUT_THROUGH")
    assert len(outlines) == 3
    lefts = sorted(min(p[0] for p in pts) for pts in outlines)
    assert lefts[1] - lefts[0] > 900, "sheets must not be drawn on top of each other"


def test_labels_can_be_left_out(tmp_path):
    from plynest.config import LabelSettings
    from plynest.labels import place_label

    parts, result = build([plain_plate(400, 300, 18)])
    labels = {p.id: place_label(p, p.label, LabelSettings()) for p in parts}

    with_labels = export(result, ExportSettings(unit="mm", include_labels=True),
                         tmp_path / "a", labels=labels)
    without = export(result, ExportSettings(unit="mm", include_labels=False),
                     tmp_path / "b", labels=labels)
    _, ents_a = read(with_labels[0])
    _, ents_b = read(without[0])
    assert any(e.dxf.layer.startswith("ENGRAVE") for e in ents_a)
    assert not any(e.dxf.layer.startswith("ENGRAVE") for e in ents_b)


def test_sheet_and_keepout_can_be_left_out(tmp_path):
    parts, result = build([plain_plate(400, 300, 18)])
    paths = export(
        result,
        ExportSettings(unit="mm", include_sheet_outline=False, include_keepout=False),
        tmp_path,
    )
    doc, _ = read(paths[0])
    names = {l.dxf.name for l in doc.layers}
    assert "SHEET_OUTLINE" not in names and "EDGE_KEEPOUT" not in names


def test_pocket_geometry_matches_the_part(tmp_path):
    parts, result = build([plate_with_rabbet(400, 300, 18, rabbet_w=60, rabbet_d=6)])
    paths = export(result, ExportSettings(unit="mm", include_labels=False), tmp_path)
    _, entities = read(paths[0])
    pockets = closed_polys(entities, "POCKET_")
    assert len(pockets) == 1
    w, h = extents(pockets[0])
    assert sorted((w, h)) == pytest.approx([60.0, 300.0], abs=1e-6)


def test_exported_positions_match_the_nest(tmp_path):
    shapes = [plain_plate(300, 400, 18) for _ in range(6)]
    parts, result = build(shapes)
    paths = export(result, ExportSettings(unit="mm", include_labels=False), tmp_path)
    for sheet, path in zip(result.sheets, paths):
        _, entities = read(path)
        exported = sorted(
            (round(min(p[0] for p in pts), 3), round(min(p[1] for p in pts), 3))
            for pts in closed_polys(entities, "CUT_THROUGH")
        )
        planned = sorted(
            (round(pl.bounds()[0], 3), round(pl.bounds()[1], 3)) for pl in sheet.placements
        )
        assert exported == pytest.approx(planned, abs=1e-6)
