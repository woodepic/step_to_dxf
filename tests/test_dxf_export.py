"""Read the exported DXF back and check it says what the layout says."""
from __future__ import annotations

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
from plynest.config import ExportSettings, LabelSettings, NestSettings, SheetSpec
from plynest.dxf_export import export
from plynest.labels import place_label
from plynest.nest import nest
from plynest.orient import analyse


def build(shapes, labels=("PART0", "PART1", "PART2", "PART3", "PART4", "PART5",
                          "PART6", "PART7", "PART8", "PART9"), **nest_kw):
    parts = []
    for i, shape in enumerate(shapes):
        a = analyse(as_loaded(shape, index=i), labels[i % len(labels)], part_id=f"p{i}")
        assert a.ok, a.messages
        parts.append(a.part)
    settings = NestSettings(kerf_mm=5.0, edge_keepout_mm=10.0,
                            sheet=SheetSpec(1000.0, 2000.0), attempts=2, **nest_kw)
    return parts, nest(parts, settings)


def read(path):
    doc = ezdxf.readfile(path)
    return doc, list(doc.modelspace())


def layers_used(entities) -> set[str]:
    return {e.dxf.layer for e in entities}


def closed_polys(entities, layer_prefix):
    out = []
    for e in entities:
        if not e.dxf.layer.startswith(layer_prefix):
            continue
        if e.dxftype() == "LWPOLYLINE" and e.closed:
            out.append([(p[0], p[1]) for p in e.get_points("xy")])
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
    paths = export(result, ExportSettings(unit="mm"), tmp_path)

    found: Counter[tuple[float, float]] = Counter()
    for path in paths:
        _, entities = read(path)
        for pts in closed_polys(entities, "CUT THROUGH"):
            found[tuple(sorted(extents(pts)))] += 1

    expected = Counter(
        tuple(sorted((round(p.width, 4), round(p.height, 4)))) for p in parts
    )
    assert found == expected, "a part is missing, duplicated, or the wrong size"


def test_units_conversion_to_inches(tmp_path):
    _, result = build([plain_plate(254.0, 508.0, 18)])
    paths = export(result, ExportSettings(unit="in"), tmp_path)
    doc, entities = read(paths[0])
    assert doc.header["$INSUNITS"] == 1
    assert extents(closed_polys(entities, "CUT THROUGH")[0]) == pytest.approx((10.0, 20.0), abs=1e-6)


def test_units_stay_millimetres_when_asked(tmp_path):
    _, result = build([plain_plate(254.0, 508.0, 18)])
    paths = export(result, ExportSettings(unit="mm"), tmp_path)
    doc, entities = read(paths[0])
    assert doc.header["$INSUNITS"] == 4
    assert extents(closed_polys(entities, "CUT THROUGH")[0]) == pytest.approx((254.0, 508.0), abs=1e-6)


# --- naming ----------------------------------------------------------------

def test_sheet_files_are_named_readably(tmp_path):
    shapes = [plain_plate(900, 1900, 18), plain_plate(900, 1900, 18),
              plain_plate(900, 1900, 12)]
    _, result = build(shapes)
    paths = export(result, ExportSettings(unit="in"), tmp_path)
    names = sorted(p.name for p in paths)
    assert names == ["Sheet 1, 0.7087 in.dxf", "Sheet 2, 0.7087 in.dxf",
                     "Sheet 3, 0.4724 in.dxf"]


def test_sheet_names_read_naturally_in_inches(tmp_path):
    """Imperial stock should come out as the size you would ask for."""
    _, result = build([plain_plate(400, 400, 19.05), plain_plate(400, 400, 12.7)])
    paths = export(result, ExportSettings(unit="in"), tmp_path)
    assert sorted(p.name for p in paths) == ["Sheet 1, 0.75 in.dxf", "Sheet 2, 0.5 in.dxf"]


def test_layer_names_state_the_depth_from_the_top_face(tmp_path):
    _, result = build([plate_stepped_pocket(400, 300, 18)])
    paths = export(result, ExportSettings(unit="mm"), tmp_path)
    doc, entities = read(paths[0])
    used = layers_used(entities)
    assert "CUT THROUGH 18 mm deep" in used
    assert "POCKET 4 mm deep" in used
    assert "POCKET 9 mm deep" in used


def test_layer_names_in_inches(tmp_path):
    _, result = build([plate_with_rabbet(400, 300, 19.05, rabbet_d=6.35)])
    paths = export(result, ExportSettings(unit="in"), tmp_path)
    _, entities = read(paths[0])
    used = layers_used(entities)
    assert "CUT THROUGH 0.75 in deep" in used
    assert "POCKET 0.25 in deep" in used


# --- layer hygiene ---------------------------------------------------------

def test_nothing_is_drawn_on_layer_zero(tmp_path):
    _, result = build([plate_stepped_pocket()])
    paths = export(result, ExportSettings(unit="mm"), tmp_path)
    _, entities = read(paths[0])
    assert "0" not in layers_used(entities)


def test_defpoints_layer_is_not_written(tmp_path):
    """ezdxf adds Defpoints on read, so check the file text, not the document."""
    _, result = build([plain_plate()])
    paths = export(result, ExportSettings(unit="mm"), tmp_path)
    assert "Defpoints" not in paths[0].read_text(errors="ignore")


def test_keepout_is_off_by_default(tmp_path):
    _, result = build([plain_plate()])
    paths = export(result, ExportSettings(unit="mm"), tmp_path)
    _, entities = read(paths[0])
    assert not any(e.dxf.layer.startswith("EDGE KEEP") for e in entities)


def test_keepout_can_be_switched_on(tmp_path):
    _, result = build([plain_plate()])
    paths = export(result, ExportSettings(unit="mm", include_keepout=True), tmp_path)
    _, entities = read(paths[0])
    assert any(e.dxf.layer.startswith("EDGE KEEP") for e in entities)


# --- geometry fidelity -----------------------------------------------------

def test_through_hole_becomes_a_circle_entity(tmp_path):
    _, result = build([plate_with_through_hole(300, 300, 18, r=12.5, at=(150, 150))])
    paths = export(result, ExportSettings(unit="mm"), tmp_path)
    _, entities = read(paths[0])
    circles = [e for e in entities if e.dxftype() == "CIRCLE"]
    assert len(circles) == 1, "an arc must survive as an arc, not a chord chain"
    assert circles[0].dxf.radius == pytest.approx(12.5, rel=1e-9)
    assert circles[0].dxf.layer.startswith("CUT THROUGH")


def test_no_polyline_bulge_exceeds_a_half_turn(tmp_path):
    """A bulge over 1 means an arc past 180 deg, which some CAM mishandles."""
    parts, result = build([plate_with_through_hole(300, 300, 18, r=12.5)])
    labels = {p.id: place_label(p, p.label, LabelSettings()) for p in parts}
    paths = export(result, ExportSettings(unit="mm"), tmp_path, labels=labels)
    _, entities = read(paths[0])
    for e in entities:
        if e.dxftype() != "LWPOLYLINE":
            continue
        for point in e.get_points("xyseb"):
            assert abs(point[4]) <= 1.0 + 1e-9


def test_labels_are_written_with_arcs(tmp_path):
    parts, result = build([plain_plate(400, 300, 18)])
    labels = {p.id: place_label(p, "AC4/DA2/FLOOR", LabelSettings()) for p in parts}
    paths = export(result, ExportSettings(unit="mm"), tmp_path, labels=labels)
    _, entities = read(paths[0])
    engrave = [e for e in entities if e.dxf.layer.startswith("ENGRAVE")]
    assert engrave
    bulges = sum(1 for e in engrave if e.dxftype() == "LWPOLYLINE"
                 for p in e.get_points("xyseb") if abs(p[4]) > 1e-9)
    assert bulges > 0, "curved letters should carry bulges, not be flattened"


def test_pocket_geometry_matches_the_part(tmp_path):
    _, result = build([plate_with_rabbet(400, 300, 18, rabbet_w=60, rabbet_d=6)])
    paths = export(result, ExportSettings(unit="mm", include_labels=False), tmp_path)
    _, entities = read(paths[0])
    pockets = closed_polys(entities, "POCKET")
    assert len(pockets) == 1
    assert sorted(extents(pockets[0])) == pytest.approx([60.0, 300.0], abs=1e-6)


def test_exported_positions_match_the_nest(tmp_path):
    shapes = [plain_plate(300, 400, 18) for _ in range(6)]
    _, result = build(shapes)
    paths = export(result, ExportSettings(unit="mm", include_labels=False), tmp_path)
    for sheet, path in zip(result.sheets, paths):
        _, entities = read(path)
        exported = sorted(
            (round(min(p[0] for p in pts), 3), round(min(p[1] for p in pts), 3))
            for pts in closed_polys(entities, "CUT THROUGH")
        )
        planned = sorted(
            (round(pl.bounds()[0], 3), round(pl.bounds()[1], 3)) for pl in sheet.placements
        )
        assert exported == pytest.approx(planned, abs=1e-6)


# --- per-part mode ---------------------------------------------------------

def test_per_part_mode_writes_one_file_per_part(tmp_path):
    shapes = [plain_plate(300, 200, 18), plate_with_rabbet(), plate_stepped_pocket()]
    parts, result = build(shapes, )
    paths = export(result, ExportSettings(unit="mm", mode="dxf_per_part"), tmp_path,
                   parts=parts)
    assert len(paths) == len(parts)
    assert sorted(p.stem for p in paths) == sorted(p.label for p in parts)


def test_per_part_files_are_named_for_the_part(tmp_path):
    parts, result = build([plain_plate(300, 200, 18)], labels=("AC4/DA2/Front Side",))
    paths = export(result, ExportSettings(unit="mm", mode="dxf_per_part"), tmp_path,
                   parts=parts)
    assert paths[0].name == "AC4-DA2-Front Side.dxf"


def test_per_part_colliding_names_are_disambiguated(tmp_path):
    parts, result = build([plain_plate(300, 200, 18), plain_plate(310, 200, 18)],
                          labels=("A/B",))
    paths = export(result, ExportSettings(unit="mm", mode="dxf_per_part"), tmp_path,
                   parts=parts)
    assert sorted(p.name for p in paths) == ["A-B (2).dxf", "A-B.dxf"]


def test_per_part_ignores_the_layout(tmp_path):
    """Each part sits at the origin, not at its nested position."""
    parts, result = build([plain_plate(300, 200, 18) for _ in range(4)])
    paths = export(result, ExportSettings(unit="mm", mode="dxf_per_part"), tmp_path,
                   parts=parts)
    for path in paths:
        _, entities = read(path)
        pts = closed_polys(entities, "CUT THROUGH")[0]
        assert (min(p[0] for p in pts), min(p[1] for p in pts)) == pytest.approx((0.0, 0.0))


def test_per_part_has_no_sheet_furniture(tmp_path):
    parts, result = build([plate_with_rabbet()])
    paths = export(result, ExportSettings(unit="mm", mode="dxf_per_part",
                                          include_sheet_outline=True,
                                          include_keepout=True), tmp_path, parts=parts)
    _, entities = read(paths[0])
    used = layers_used(entities)
    assert "SHEET OUTLINE" not in used and "EDGE KEEP-OUT" not in used


def test_per_part_keeps_pockets_and_labels(tmp_path):
    parts, result = build([plate_stepped_pocket()])
    labels = {p.id: place_label(p, p.label, LabelSettings()) for p in parts}
    paths = export(result, ExportSettings(unit="mm", mode="dxf_per_part"), tmp_path,
                   parts=parts, labels=labels)
    _, entities = read(paths[0])
    used = layers_used(entities)
    assert any(l.startswith("POCKET") for l in used)
    assert any(l.startswith("ENGRAVE") for l in used)
    assert any(l.startswith("CUT THROUGH") for l in used)


def test_labels_can_be_left_out(tmp_path):
    parts, result = build([plain_plate(400, 300, 18)])
    labels = {p.id: place_label(p, p.label, LabelSettings()) for p in parts}
    with_labels = export(result, ExportSettings(unit="mm", include_labels=True),
                         tmp_path / "a", labels=labels)
    without = export(result, ExportSettings(unit="mm", include_labels=False),
                     tmp_path / "b", labels=labels)
    assert any(e.dxf.layer.startswith("ENGRAVE") for e in read(with_labels[0])[1])
    assert not any(e.dxf.layer.startswith("ENGRAVE") for e in read(without[0])[1])
