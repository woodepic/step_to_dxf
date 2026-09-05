"""The STEP export must re-pose the *original* solids, not re-model them."""
from __future__ import annotations


import pytest

from conftest import (
    as_loaded,
    plain_plate,
    plate_stepped_pocket,
    plate_with_rabbet,
    plate_with_through_hole,
    rotate,
    translate,
)
from plynest import occ_utils as occ
from plynest.config import ExportSettings, LabelSettings, NestSettings, SheetSpec
from plynest.labels import place_label
from plynest.nest import nest
from plynest.orient import analyse
from plynest.step_export import StepExportError, build_sheet, export_step, posed_solid
from plynest.step_loader import load_step


def prepare(shapes, names=None):
    names = names or [f"PART {i}" for i in range(len(shapes))]
    parts, sources = [], {}
    for i, shape in enumerate(shapes):
        solid = as_loaded(shape, index=i)
        a = analyse(solid, names[i], part_id=f"p{i}")
        assert a.ok, a.messages
        parts.append(a.part)
        sources[i] = solid
    result = nest(parts, NestSettings(kerf_mm=5.0, edge_keepout_mm=10.0,
                                      sheet=SheetSpec(1000.0, 2000.0), attempts=2))
    return parts, sources, result


def no_engrave() -> ExportSettings:
    return ExportSettings(mode="step_per_sheet", engrave_labels_in_step=False)


# --- re-posing -------------------------------------------------------------

def test_reposing_preserves_volume_exactly():
    """A rigid move must not change the solid at all."""
    shapes = [plate_with_rabbet(), plate_stepped_pocket(), plate_with_through_hole()]
    parts, sources, result = prepare(shapes)
    for sheet in result.sheets:
        for placement in sheet.placements:
            source = sources[placement.part.source_index]
            moved = posed_solid(placement, source)
            assert occ.volume(moved) == pytest.approx(occ.volume(source.shape), rel=1e-12)


def test_reposed_solid_lands_where_the_layout_says():
    parts, sources, result = prepare([plain_plate(300, 200, 18) for _ in range(5)])
    for sheet in result.sheets:
        for placement in sheet.placements:
            moved = posed_solid(placement, sources[placement.part.source_index])
            xmin, ymin, zmin, xmax, ymax, zmax = occ.bbox(moved)
            px0, py0, px1, py1 = placement.bounds()
            assert (xmin, ymin) == pytest.approx((px0, py0), abs=1e-6)
            assert (xmax, ymax) == pytest.approx((px1, py1), abs=1e-6)
            assert zmin == pytest.approx(0.0, abs=1e-6)
            assert zmax == pytest.approx(placement.part.thickness, abs=1e-6)


@pytest.mark.parametrize("transform", [
    lambda s: s,
    lambda s: rotate(s, (1, 0, 0), 180),
    lambda s: translate(rotate(s, (0, 1, 0), 90), 250.0, -70.0, 33.0),
])
def test_reposing_works_from_any_starting_pose(transform):
    parts, sources, result = prepare([transform(plate_with_rabbet())])
    placement = result.sheets[0].placements[0]
    moved = posed_solid(placement, sources[0])
    _, _, zmin, _, _, zmax = occ.bbox(moved)
    assert zmin == pytest.approx(0.0, abs=1e-6)
    assert zmax == pytest.approx(18.0, abs=1e-4)


def test_reposed_parts_do_not_collide():
    parts, sources, result = prepare([plain_plate(400, 500, 18) for _ in range(6)])
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common

    for sheet in result.sheets:
        moved = [posed_solid(p, sources[p.part.source_index]) for p in sheet.placements]
        for i in range(len(moved)):
            for j in range(i + 1, len(moved)):
                op = BRepAlgoAPI_Common(moved[i], moved[j])
                op.Build()
                assert occ.volume(op.Shape()) == pytest.approx(0.0, abs=1e-6)


def test_missing_orientation_is_reported():
    parts, sources, result = prepare([plain_plate()])
    placement = result.sheets[0].placements[0]
    placement.part.transform = None
    with pytest.raises(StepExportError, match="re-pose"):
        posed_solid(placement, sources[0])


# --- engraving -------------------------------------------------------------

def test_engraving_removes_the_expected_volume():
    parts, sources, result = prepare([plain_plate(400, 300, 18)], ["AC4/DA2/FLOOR"])
    labels = {p.id: place_label(p, p.label, LabelSettings()) for p in parts}
    sheet = result.sheets[0]

    plain = build_sheet(sheet, sources, labels, no_engrave())
    engraved = build_sheet(sheet, sources, labels, ExportSettings(mode="step_per_sheet"), 1.0)
    removed = occ.volume(plain[0][1]) - occ.volume(engraved[0][1])

    from shapely.geometry import LineString
    from shapely.ops import unary_union
    from plynest.step_export import _engrave_tolerance

    label = labels[parts[0].id]
    area = unary_union([
        LineString([(p.x, p.y) for p in c]).buffer(ExportSettings().engrave_tool_mm / 2)
        for c in label.sampled(_engrave_tolerance(label.height)) if len(c) >= 2
    ]).area
    assert removed == pytest.approx(area * 1.0, rel=0.05)
    assert removed > 0


def test_engraving_only_touches_the_top():
    parts, sources, result = prepare([plain_plate(400, 300, 18)], ["FLOOR"])
    labels = {p.id: place_label(p, p.label, LabelSettings()) for p in parts}
    named = build_sheet(result.sheets[0], sources, labels,
                        ExportSettings(mode="step_per_sheet"), 1.0)
    _, _, zmin, _, _, zmax = occ.bbox(named[0][1])
    assert zmin == pytest.approx(0.0, abs=1e-6), "engraving must not break through"
    assert zmax == pytest.approx(18.0, abs=1e-6)


def test_engraving_can_be_turned_off():
    parts, sources, result = prepare([plain_plate(400, 300, 18)], ["FLOOR"])
    labels = {p.id: place_label(p, p.label, LabelSettings()) for p in parts}
    plain = build_sheet(result.sheets[0], sources, labels, no_engrave())
    assert occ.volume(plain[0][1]) == pytest.approx(400 * 300 * 18, rel=1e-9)


def test_engraving_never_cuts_deeper_than_the_stock():
    """A silly engrave depth must be clamped, not perforate the part."""
    parts, sources, result = prepare([plain_plate(400, 300, 6.0)], ["FLOOR"])
    labels = {p.id: place_label(p, p.label, LabelSettings()) for p in parts}
    named = build_sheet(result.sheets[0], sources, labels,
                        ExportSettings(mode="step_per_sheet"), label_depth_mm=50.0)
    _, _, zmin, _, _, zmax = occ.bbox(named[0][1])
    assert zmin == pytest.approx(0.0, abs=1e-6)
    assert occ.volume(named[0][1]) > 0


# --- file round trip -------------------------------------------------------

def test_written_step_reloads_with_the_right_parts(tmp_path):
    names = ["AC1/Floor", "AC1/Left Side", "AC1/Right Side"]
    shapes = [plain_plate(300, 200, 18), plain_plate(310, 210, 18), plain_plate(320, 220, 18)]
    parts, sources, result = prepare(shapes, names)
    paths = export_step(result, no_engrave(), tmp_path, sources)
    assert len(paths) == result.sheet_count()

    reloaded = load_step(paths[0])
    assert len(reloaded) == len(result.sheets[0].placements)
    assert sorted(s.name for s in reloaded) == sorted(
        p.part.label for p in result.sheets[0].placements
    )


def test_written_step_keeps_positions_and_sizes(tmp_path):
    parts, sources, result = prepare([plain_plate(300, 200, 18), plain_plate(400, 250, 18)])
    paths = export_step(result, no_engrave(), tmp_path, sources)
    reloaded = {s.name: s for s in load_step(paths[0])}
    for placement in result.sheets[0].placements:
        solid = reloaded[placement.part.label]
        xmin, ymin, zmin, xmax, ymax, zmax = occ.bbox(solid.shape)
        px0, py0, px1, py1 = placement.bounds()
        assert (xmin, ymin, xmax, ymax) == pytest.approx((px0, py0, px1, py1), abs=1e-4)
        assert zmax - zmin == pytest.approx(placement.part.thickness, abs=1e-4)


def test_written_step_files_are_named_readably(tmp_path):
    from plynest.naming import sheet_name

    shapes = [plain_plate(900, 1900, 19.05), plain_plate(900, 1900, 19.05)]
    parts, sources, result = prepare(shapes)
    paths = export_step(result, no_engrave(), tmp_path, sources,
                        sheet_namer=lambda sh: sheet_name(sh.index, sh.thickness, "in"))
    assert sorted(p.name for p in paths) == ["Sheet 1, 0.75 in.step", "Sheet 2, 0.75 in.step"]


def test_engraved_step_reloads_and_is_still_solid(tmp_path):
    parts, sources, result = prepare([plain_plate(400, 300, 18)], ["AC4/FLOOR"])
    labels = {p.id: place_label(p, p.label, LabelSettings()) for p in parts}
    paths = export_step(result, ExportSettings(mode="step_per_sheet"), tmp_path,
                        sources, labels=labels, label_depth_mm=1.0)
    reloaded = load_step(paths[0])
    assert len(reloaded) == 1
    volume = occ.volume(reloaded[0].shape)
    full = 400 * 300 * 18
    assert 0 < volume < full, "the label should have been cut into the solid"
    assert volume == pytest.approx(full, rel=0.01), "but only a groove's worth"
