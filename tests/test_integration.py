"""End-to-end checks against the real sample assembly.

These are the guarantees an operator needs before sending a job to the router:
every part in the STEP file reaches a sheet, at its true size, without
overlapping a neighbour, and the DXF says the same thing the preview did.
"""
from __future__ import annotations

from collections import Counter

import ezdxf
import pytest

from conftest import SAMPLE_STEP, requires_sample
from plynest import occ_utils as occ
from plynest.config import ExportSettings, NestSettings, RunSettings
from plynest.dxf_export import export
from plynest.pipeline import run
from plynest.step_loader import load_step
from plynest.units import MM_PER_INCH

pytestmark = requires_sample


@pytest.fixture(scope="module")
def job():
    settings = RunSettings()
    settings.nest.attempts = 2  # keep the suite quick; quality is tested elsewhere
    return run(SAMPLE_STEP, settings)


def test_every_solid_in_the_file_becomes_a_part(job):
    solids = load_step(SAMPLE_STEP)
    assert len(job.parts) + len(job.skipped) == len(solids)
    assert job.skipped == [], f"solids were dropped: {job.skipped}"


def test_every_part_reaches_a_sheet_exactly_once(job):
    placed = [p.part.id for sheet in job.result.sheets for p in sheet.placements]
    assert sorted(placed) == sorted(p.id for p in job.parts)
    assert len(placed) == len(set(placed))
    assert job.result.unplaced == []


def test_placed_parts_keep_their_true_dimensions(job):
    by_id = {p.id: p for p in job.parts}
    for sheet in job.result.sheets:
        for placement in sheet.placements:
            part = by_id[placement.part.id]
            x0, y0, x1, y1 = placement.bounds()
            got = sorted((round(x1 - x0, 4), round(y1 - y0, 4)))
            want = sorted((round(part.width, 4), round(part.height, 4)))
            assert got == pytest.approx(want, abs=1e-4), part.label
            assert placement.profile().area() == pytest.approx(part.area, rel=1e-9)


def test_flattening_conserves_every_solid_volume(job):
    """The 2D data must describe the same object the STEP file did."""
    solids = {s.index: s for s in load_step(SAMPLE_STEP)}
    for part in job.parts:
        solid = solids[part.source_index]
        rebuilt = part.thickness * part.profile.area() - sum(
            pk.region.area() * pk.depth for pk in part.pockets
        )
        assert rebuilt == pytest.approx(occ.volume(solid.shape), rel=1e-4), part.label


def test_no_overlaps_and_kerf_is_honoured(job):
    kerf = NestSettings().kerf_mm
    for sheet in job.result.sheets:
        polys = [p.polygon() for p in sheet.placements]
        for i in range(len(polys)):
            for j in range(i + 1, len(polys)):
                assert not polys[i].overlaps(polys[j])
                gap = polys[i].distance(polys[j])
                assert gap >= kerf - 0.11, (
                    f"sheet {sheet.index}: {sheet.placements[i].part.label} and "
                    f"{sheet.placements[j].part.label} are {gap:.3f} mm apart"
                )


def test_everything_is_inside_the_edge_keepout(job):
    for sheet in job.result.sheets:
        kx0, ky0, kx1, ky1 = sheet.usable
        for placement in sheet.placements:
            x0, y0, x1, y1 = placement.bounds()
            assert x0 >= kx0 - 1e-6 and y0 >= ky0 - 1e-6, placement.part.label
            assert x1 <= kx1 + 1e-6 and y1 <= ky1 + 1e-6, placement.part.label


def test_sheets_never_mix_stock_thickness(job):
    for sheet in job.result.sheets:
        assert len({round(p.part.thickness, 3) for p in sheet.placements}) == 1


def test_the_sample_uses_half_and_three_quarter_inch_stock(job):
    thicknesses = sorted({round(p.thickness / MM_PER_INCH, 4) for p in job.parts})
    assert thicknesses == pytest.approx([0.5, 0.75], abs=1e-3)


def test_every_part_is_machinable_from_the_top(job):
    """No part may need the sheet turned over."""
    offenders = [p.label for p in job.parts if any("flip" in w for w in p.warnings)]
    assert offenders == [], f"parts needing a flip: {offenders}"


def test_labels_are_unique_and_placed(job):
    labels = [p.label for p in job.parts]
    assert len(set(labels)) == len(labels), "two parts would be engraved the same"
    unplaced = [p.label for p in job.parts
                if p.id in job.labels and not job.labels[p.id].fitted]
    assert unplaced == [], f"labels that would not fit: {unplaced}"


def test_labels_never_cross_a_cut_feature(job):
    from shapely.geometry import LineString

    by_id = {p.id: p for p in job.parts}
    for part_id, placement in job.labels.items():
        if not placement.fitted:
            continue
        part = by_id[part_id]
        outline = part.profile.to_polygon()
        for stroke in placement.sampled():
            if len(stroke) < 2:
                continue
            geom = LineString([(p.x, p.y) for p in stroke])
            assert outline.contains(geom), f"{part.label}: label leaves the part"
            for pocket in part.pockets:
                assert not geom.intersects(pocket.region.to_polygon()), (
                    f"{part.label}: label crosses a {pocket.depth:.1f} mm pocket"
                )


def test_through_holes_survive_into_the_dxf(job, tmp_path):
    holes_in_parts = sum(len(p.profile.holes) for p in job.parts)
    assert holes_in_parts > 0, "the sample assembly does have through holes"

    paths = export(job.result, ExportSettings(unit="in"), tmp_path, labels=job.labels)
    circles = 0
    for path in paths:
        doc = ezdxf.readfile(path)
        circles += sum(
            1 for e in doc.modelspace()
            if e.dxftype() == "CIRCLE" and e.dxf.layer.startswith("CUT THROUGH")
        )
    assert circles == holes_in_parts


def test_dxf_round_trip_reproduces_every_part(job, tmp_path):
    """Export, re-read, and match each outline back to the part it came from."""
    paths = export(job.result, ExportSettings(unit="in"), tmp_path, labels=job.labels)
    assert len(paths) == job.result.sheet_count()

    exported: Counter[tuple[float, float]] = Counter()
    for path in paths:
        doc = ezdxf.readfile(path)
        assert doc.header["$INSUNITS"] == 1
        for e in doc.modelspace():
            if e.dxftype() != "LWPOLYLINE" or not e.dxf.layer.startswith("CUT THROUGH"):
                continue
            pts = [(p[0], p[1]) for p in e.get_points("xy")]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            exported[(round(max(xs) - min(xs), 3), round(max(ys) - min(ys), 3))] += 1

    planned: Counter[tuple[float, float]] = Counter()
    for sheet in job.result.sheets:
        for placement in sheet.placements:
            x0, y0, x1, y1 = placement.bounds()
            planned[(round((x1 - x0) / MM_PER_INCH, 3),
                     round((y1 - y0) / MM_PER_INCH, 3))] += 1

    assert exported == planned


def test_dxf_per_sheet_files_are_named_readably(job, tmp_path):
    paths = export(job.result, ExportSettings(unit="in"), tmp_path, labels=job.labels)
    assert len(paths) == job.result.sheet_count()
    for i, path in enumerate(paths):
        assert path.name.startswith(f"Sheet {i + 1}, ")
        assert path.name.endswith(" in.dxf")


def test_dxf_per_part_writes_one_readable_file_per_part(job, tmp_path):
    paths = export(job.result, ExportSettings(unit="in", mode="dxf_per_part"),
                   tmp_path, labels=job.labels, parts=job.parts)
    assert len(paths) == len(job.parts)
    assert len(set(p.name for p in paths)) == len(paths), "filenames collided"
    for path in paths:
        assert "/" not in path.stem
        doc = ezdxf.readfile(path)
        assert len(doc.modelspace()) > 0, f"{path.name} is empty"


def test_dxf_per_part_holds_the_same_parts_as_the_layout(job, tmp_path):
    """Per-part output ignores the nest, but must still cover every part once."""
    paths = export(job.result, ExportSettings(unit="in", mode="dxf_per_part"),
                   tmp_path, labels=job.labels, parts=job.parts)
    sizes: Counter[tuple[float, float]] = Counter()
    for path in paths:
        doc = ezdxf.readfile(path)
        outlines = [
            e for e in doc.modelspace()
            if e.dxftype() == "LWPOLYLINE" and e.dxf.layer.startswith("CUT THROUGH")
        ]
        assert outlines, f"{path.name} has no through cut"
        biggest = max(outlines, key=lambda e: len(e))
        pts = [(p[0], p[1]) for p in biggest.get_points("xy")]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        assert min(xs) == pytest.approx(0.0, abs=1e-6), "part should sit at the origin"
        assert min(ys) == pytest.approx(0.0, abs=1e-6)
        sizes[(round(max(xs) - min(xs), 3), round(max(ys) - min(ys), 3))] += 1

    expected = Counter(
        (round(p.width / MM_PER_INCH, 3), round(p.height / MM_PER_INCH, 3))
        for p in job.parts
    )
    assert sizes == expected


def test_no_dxf_draws_on_layer_zero(job, tmp_path):
    paths = export(job.result, ExportSettings(unit="in"), tmp_path, labels=job.labels)
    for path in paths:
        doc = ezdxf.readfile(path)
        assert "0" not in {e.dxf.layer for e in doc.modelspace()}
        assert "Defpoints" not in path.read_text(errors="ignore")


def test_step_export_reproduces_the_layout(job, tmp_path):
    """The rearrange-my-assembly mode: same parts, same places, real geometry."""
    from plynest.naming import sheet_name
    from plynest.step_export import export_step
    from plynest.step_loader import load_step as reload_step

    settings = ExportSettings(mode="step_per_sheet", engrave_labels_in_step=False)
    paths = export_step(
        job.result, settings, tmp_path, job.sources,
        sheet_namer=lambda sh: sheet_name(sh.index, sh.thickness, "in"),
    )
    assert len(paths) == job.result.sheet_count()

    sheet = job.result.sheets[0]
    reloaded = reload_step(paths[0])
    assert len(reloaded) == len(sheet.placements)
    assert sorted(s.name for s in reloaded) == sorted(p.part.label for p in sheet.placements)

    by_name = {s.name: s for s in reloaded}
    for placement in sheet.placements:
        b = occ.bbox(by_name[placement.part.label].shape)
        px0, py0, px1, py1 = placement.bounds()
        assert (b[0], b[1], b[3], b[4]) == pytest.approx((px0, py0, px1, py1), abs=1e-3)
        assert b[2] == pytest.approx(0.0, abs=1e-3)
        assert b[5] == pytest.approx(placement.part.thickness, abs=1e-3)


def test_step_export_preserves_every_solid_volume(job, tmp_path):
    """Re-posing is rigid, so nothing may gain or lose material."""
    from plynest.step_export import posed_solid

    for sheet in job.result.sheets[:2]:
        for placement in sheet.placements:
            source = job.sources[placement.part.source_index]
            moved = posed_solid(placement, source)
            assert occ.volume(moved) == pytest.approx(occ.volume(source.shape), rel=1e-9)


def test_material_utilisation_is_reasonable(job):
    assert 0.5 < job.result.total_utilisation() < 1.0
    assert job.result.sheet_count() <= 14, "the layout has gone badly wrong"


def test_rerunning_gives_the_same_layout():
    settings = RunSettings()
    settings.nest.attempts = 1
    a = run(SAMPLE_STEP, settings)
    b = run(SAMPLE_STEP, settings)
    key = lambda j: [
        (s.index, p.part.label, round(p.angle, 6), round(p.dx, 6), round(p.dy, 6))
        for s in j.result.sheets
        for p in sorted(s.placements, key=lambda q: q.part.label)
    ]
    assert key(a) == key(b)
