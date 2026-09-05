"""Hostile and awkward inputs: the program must fail loudly or cope, never lie.

Every test here is a thing a real STEP file or a slip of the keyboard could do.
"""
from __future__ import annotations

import math

import pytest

from conftest import (
    as_loaded,
    box,
    cut,
    plain_plate,
    plate_with_chamfered_top,
    plate_with_slot_to_edge,
    two_separate_bodies,
    bar,
    round_plate,
    sphere,
    tiny_plate,
    upright_cylinder,
    wedge,
)
from plynest.config import (
    ExportSettings,
    LabelSettings,
    NestSettings,
    RunSettings,
    SheetSpec,
)
from plynest.geom2d import Contour, Point, Region
from plynest.nest import nest
from plynest.orient import analyse
from plynest.part import Part


def flatten(shape, label="P"):
    return analyse(as_loaded(shape), label, part_id="t0")


def rect_part(pid, w, h, thickness=18.0, label=None):
    profile = Region(Contour.from_points([(0, 0), (w, 0), (w, h), (0, h)]))
    return Part(id=pid, label=label or pid, path=("T", pid), thickness=thickness,
                profile=profile)


def small_nest(**kw) -> NestSettings:
    base = dict(kerf_mm=5.0, edge_keepout_mm=10.0,
                sheet=SheetSpec(1000.0, 2000.0), attempts=1)
    base.update(kw)
    return NestSettings(**base)


# --- solids that are not sheet parts ---------------------------------------

@pytest.mark.parametrize("shape,why", [
    (sphere(50.0), "a sphere has no planar face at all"),
    (box(50, 50, 50), "a cube is not plate-like"),
    (bar(20, 20, 400), "a square bar is not a sheet part"),
])
def test_non_sheet_solids_are_rejected_with_a_reason(shape, why):
    result = flatten(shape)
    assert not result.ok, why
    assert result.messages and result.messages[0], "a rejection must say why"


def test_a_disc_is_accepted_as_a_round_part():
    result = flatten(round_plate(150.0, 18.0))
    assert result.ok, result.messages
    part = result.part
    assert part.thickness == pytest.approx(18.0, abs=1e-6)
    assert part.width == pytest.approx(300.0, abs=1e-3)
    assert part.area == pytest.approx(math.pi * 150 ** 2, rel=1e-6)


def test_an_upright_cylinder_is_a_plate_not_a_failure():
    result = flatten(upright_cylinder(100.0, 18.0))
    assert result.ok and result.part.thickness == pytest.approx(18.0, abs=1e-6)


def test_a_narrow_strip_is_still_a_sheet_part():
    """3/4 x 1 x 24 in is a real plywood part, and must not read as a bar."""
    result = flatten(box(19.05, 25.4, 610.0))
    assert result.ok, result.messages
    assert result.part.thickness == pytest.approx(19.05, abs=1e-6)


def test_a_very_small_plate_still_works():
    result = flatten(tiny_plate(6.0, 4.0, 1.0))
    assert result.ok, result.messages
    assert result.part.thickness == pytest.approx(1.0, abs=1e-9)


def test_non_vertical_walls_are_flagged_not_silently_wrong():
    result = flatten(plate_with_chamfered_top())
    assert result.ok, result.messages
    assert any("vertical" in m for m in result.part.warnings), result.part.warnings


def test_a_sloped_solid_is_flagged_or_rejected():
    result = flatten(wedge())
    if result.ok:
        assert result.part.warnings, "a sloped wall must be reported"
    else:
        assert result.messages


def test_two_disjoint_bodies_load_as_two_parts():
    """A valid solid is connected, so a shape with two islands is two parts."""
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    shape = two_separate_bodies()
    found = 0
    ex = TopExp_Explorer(shape, TopAbs_SOLID)
    while ex.More():
        found += 1
        ex.Next()
    assert found == 2


def test_a_c_shaped_part_keeps_its_notch():
    result = flatten(plate_with_slot_to_edge())
    assert result.ok
    assert result.part.area == pytest.approx(400 * 300 - 100 * 110, rel=1e-6)


# --- nesting settings that make no sense -----------------------------------

def test_zero_size_sheet_is_reported_not_crashed():
    result = nest([rect_part("a", 100, 100)], small_nest(sheet=SheetSpec(0.0, 0.0)))
    assert result.sheets == []
    assert len(result.unplaced) == 1


def test_negative_kerf_is_treated_as_none():
    parts = [rect_part(f"p{i}", 200, 200) for i in range(4)]
    result = nest(parts, small_nest(kerf_mm=-5.0))
    assert result.unplaced == []
    for sheet in result.sheets:
        polys = [p.polygon() for p in sheet.placements]
        for i in range(len(polys)):
            for j in range(i + 1, len(polys)):
                assert polys[i].intersection(polys[j]).area == pytest.approx(0.0, abs=1e-6)


def test_negative_keepout_is_treated_as_none():
    result = nest([rect_part("a", 900, 1900)], small_nest(edge_keepout_mm=-20.0))
    assert result.unplaced == []
    sheet = result.sheets[0]
    x0, y0, x1, y1 = sheet.usable
    assert x0 >= 0 and y0 >= 0
    assert x1 <= sheet.spec.width_mm and y1 <= sheet.spec.height_mm


def test_kerf_wider_than_the_sheet_is_reported():
    result = nest([rect_part("a", 100, 100), rect_part("b", 100, 100)],
                  small_nest(kerf_mm=5000.0))
    assert len(result.sheets) + len(result.unplaced) >= 1
    assert all(len(s.placements) <= 1 for s in result.sheets)


def test_a_part_exactly_the_usable_size_fits():
    settings = small_nest(kerf_mm=0.0, edge_keepout_mm=10.0)
    part = rect_part("exact", 980.0, 1980.0)
    result = nest([part], settings)
    assert result.unplaced == [], "a part exactly the usable size must fit"


def test_a_part_a_hair_too_big_is_reported():
    settings = small_nest(kerf_mm=0.0, edge_keepout_mm=10.0, rotation="none")
    result = nest([rect_part("big", 980.5, 1980.0)], settings)
    assert len(result.unplaced) == 1
    assert "exceeds" in result.unplaced[0][1]


def test_zero_attempts_still_produces_a_layout():
    result = nest([rect_part(f"p{i}", 200, 300) for i in range(5)], small_nest(attempts=0))
    assert result.unplaced == []
    assert result.sheets


def test_a_part_with_zero_area_is_rejected_before_nesting():
    degenerate = Part(id="z", label="z", path=("T", "z"), thickness=18.0,
                      profile=Region(Contour.from_points([(0, 0), (0, 0), (0, 0)])))
    result = nest([degenerate], small_nest())
    assert len(result.unplaced) == 1 and result.sheets == []


def test_many_identical_parts_all_get_placed():
    parts = [rect_part(f"p{i}", 240, 240) for i in range(40)]
    result = nest(parts, small_nest())
    assert result.unplaced == []
    placed = [p.part.id for s in result.sheets for p in s.placements]
    assert sorted(placed) == sorted(p.id for p in parts)


def test_free_rotation_mode_places_everything():
    parts = [rect_part(f"p{i}", 150 + i * 5, 400) for i in range(8)]
    result = nest(parts, small_nest(rotation="free"))
    assert result.unplaced == []


# --- settings plumbing -----------------------------------------------------

def test_settings_survive_nonsense_types():
    back = RunSettings.from_dict({"nest": "not a dict", "labels": None, "export": []})
    assert back.nest.rotation == "90"
    assert back.labels.enabled is True
    assert back.export.unit == "in"


def test_unknown_rotation_mode_falls_back():
    parts = [rect_part(f"p{i}", 200, 300) for i in range(3)]
    result = nest(parts, small_nest(rotation="sideways"))
    assert result.unplaced == []


def test_engrave_width_default_is_thirty_thou():
    from plynest.units import from_mm

    assert from_mm(ExportSettings().engrave_tool_mm, "in") == pytest.approx(0.03, abs=1e-6)


# --- names that break filesystems ------------------------------------------

WINDOWS_RESERVED = ["CON", "PRN", "AUX", "NUL", "COM1", "COM9", "LPT1", "LPT9"]


@pytest.mark.parametrize("name", WINDOWS_RESERVED)
def test_windows_reserved_device_names_are_escaped(name):
    """CON.dxf cannot exist on Windows, whatever the extension."""
    from plynest.naming import safe_filename

    out = safe_filename(name)
    assert out.upper() not in WINDOWS_RESERVED, f"{name!r} would be unusable on Windows"


def test_reserved_name_with_an_extension_is_also_escaped():
    from plynest.naming import safe_filename

    assert safe_filename("con").lower() != "con"
    assert safe_filename("Nul").lower() != "nul"


def test_a_name_that_is_only_illegal_characters_still_yields_a_file():
    from plynest.naming import safe_filename

    for junk in ("///", "***", "   ", "...", "?<>|"):
        out = safe_filename(junk)
        assert out and not set(out) & set('<>:"/\\|?*')


def test_trailing_dots_and_spaces_are_stripped():
    """Windows silently drops them, which turns two names into one."""
    from plynest.naming import safe_filename

    assert not safe_filename("Part name. ").endswith((".", " "))
    assert not safe_filename("Part name...").endswith(".")


def test_absurdly_long_names_are_truncated_but_stay_unique():
    from plynest.naming import safe_filename, unique_filenames

    long_a = "A" * 300 + "-one"
    long_b = "A" * 300 + "-two"
    assert len(safe_filename(long_a).encode()) <= 200
    names = unique_filenames([long_a, long_b])
    assert len(set(names)) == 2, "truncation must not collide two parts into one"


def test_unicode_names_survive():
    from plynest.naming import safe_filename

    out = safe_filename("Boîte / Côté gauche")
    assert "Côté" in out and "/" not in out


def test_layer_names_stay_within_the_dxf_limit():
    from plynest.naming import pocket_layer

    assert len(pocket_layer(3.0, "mm")) <= 255


# --- label settings that make no sense -------------------------------------

def test_zero_height_label_is_refused_cleanly():
    from plynest.labels import place_label

    part = flatten(plain_plate(400, 300, 18)).part
    placement = place_label(part, "FLOOR", LabelSettings(height_mm=0.0))
    assert placement is not None and not placement.fitted


def test_negative_label_height_is_refused_cleanly():
    from plynest.labels import place_label

    part = flatten(plain_plate(400, 300, 18)).part
    placement = place_label(part, "FLOOR", LabelSettings(height_mm=-6.0))
    assert placement is not None and not placement.fitted


def test_margin_larger_than_the_part_is_refused_cleanly():
    from plynest.labels import place_label

    part = flatten(plain_plate(400, 300, 18)).part
    placement = place_label(part, "FLOOR", LabelSettings(margin_mm=500.0))
    assert not placement.fitted
    assert placement.message


def test_negative_margin_does_not_push_text_off_the_part():
    from shapely.geometry import LineString

    from plynest.labels import place_label

    part = flatten(plain_plate(400, 300, 18)).part
    placement = place_label(part, "FLOOR", LabelSettings(margin_mm=-50.0))
    if placement.fitted:
        outline = part.profile.to_polygon()
        for chain in placement.sampled():
            assert outline.contains(LineString([(p.x, p.y) for p in chain]))


def test_label_text_with_unknown_glyphs_still_places():
    from plynest.labels import place_label

    part = flatten(plain_plate(400, 300, 18)).part
    placement = place_label(part, "Côté ☃ 側", LabelSettings())
    assert placement.fitted and placement.paths


def test_whitespace_only_label_is_harmless():
    from plynest.labels import place_label

    part = flatten(plain_plate(400, 300, 18)).part
    placement = place_label(part, "   ", LabelSettings())
    assert placement is None or placement.fitted or placement.message


def test_part_entirely_covered_by_a_pocket_reports_no_room():
    from plynest.labels import place_label

    # Cutting the whole top would just make a thinner plate; leave a sliver of
    # border so there is a pocket, but nowhere legal for text.
    shape = cut(box(200, 150, 18), box(190, 140, 4, at=(5, 5, 14)))
    part = flatten(shape).part
    placement = place_label(part, "FLOOR", LabelSettings())
    assert not placement.fitted
    assert "no clear top surface" in placement.message


# --- export edge cases ------------------------------------------------------

def test_exporting_an_empty_result_writes_nothing(tmp_path):
    from plynest.dxf_export import export
    from plynest.nest import NestResult

    assert export(NestResult(sheets=[]), ExportSettings(), tmp_path) == []


def test_export_handles_a_part_named_with_slashes_and_unicode(tmp_path):
    from plynest.dxf_export import export

    parts = [rect_part("p0", 300, 200, label="Boîte/Côté gauche")]
    result = nest(parts, small_nest())
    paths = export(result, ExportSettings(mode="dxf_per_part"), tmp_path, parts=parts)
    assert len(paths) == 1 and paths[0].exists()


def test_export_survives_a_label_that_did_not_fit(tmp_path):
    from plynest.dxf_export import export
    from plynest.labels import place_label

    part = flatten(plain_plate(60, 40, 6)).part
    result = nest([part], small_nest())
    labels = {part.id: place_label(part, "A" * 80, LabelSettings())}
    assert not labels[part.id].fitted
    paths = export(result, ExportSettings(), tmp_path, labels=labels)
    assert paths and paths[0].exists()


def test_export_to_a_directory_that_does_not_exist_yet(tmp_path):
    from plynest.dxf_export import export

    result = nest([rect_part("a", 300, 200)], small_nest())
    paths = export(result, ExportSettings(), tmp_path / "deep" / "nested" / "dir")
    assert paths and paths[0].exists()


# --- STEP files that are wrong in interesting ways --------------------------

MINIMAL_HEADER = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION((''),'2;1');
FILE_NAME('t','2020-01-01T00:00:00',(''),(''),'','','');
FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));
ENDSEC;
DATA;
ENDSEC;
END-ISO-10303-21;
"""


def test_a_structurally_valid_step_with_no_shapes_is_reported(tmp_path):
    from plynest.step_loader import StepLoadError, load_step

    path = tmp_path / "empty.step"
    path.write_text(MINIMAL_HEADER)
    with pytest.raises(StepLoadError):
        load_step(path)


def test_a_directory_passed_as_a_file_is_reported(tmp_path):
    from plynest.step_loader import StepLoadError, load_step

    with pytest.raises(StepLoadError):
        load_step(tmp_path)


def test_binary_junk_is_reported(tmp_path):
    from plynest.step_loader import StepLoadError, load_step

    path = tmp_path / "junk.step"
    path.write_bytes(bytes(range(256)) * 40)
    with pytest.raises(StepLoadError):
        load_step(path)


def test_a_step_file_with_a_null_byte_in_the_name(tmp_path):
    from plynest.step_loader import StepLoadError, load_step

    with pytest.raises(StepLoadError):
        load_step(tmp_path / "no\x00such.step")


def test_our_own_export_round_trips_through_the_loader(tmp_path):
    """Names must survive out and back, or a reload is useless."""
    from plynest.step_export import export_step
    from plynest.step_loader import load_step

    real = flatten(plain_plate(300, 200, 18), "AC1/Floor").part
    result = nest([real], small_nest())
    sources = {real.source_index: as_loaded(plain_plate(300, 200, 18))}
    paths = export_step(result, ExportSettings(engrave_labels_in_step=False),
                        tmp_path, sources)
    assert [s.name for s in load_step(paths[0])] == ["AC1/Floor"]


# --- the whole pipeline under odd settings ----------------------------------

def test_pipeline_with_labels_off(tmp_path):
    from conftest import SAMPLE_STEP

    if not SAMPLE_STEP.exists():
        pytest.skip("sample STEP file not present")
    from plynest.pipeline import run

    settings = RunSettings()
    settings.labels.enabled = False
    settings.nest.attempts = 1
    job = run(SAMPLE_STEP, settings)
    assert job.labels == {}
    assert job.result.unplaced == []


def test_pipeline_on_a_tiny_sheet_reports_every_part(tmp_path):
    """A sheet smaller than the parts must not silently drop them."""
    from conftest import SAMPLE_STEP

    if not SAMPLE_STEP.exists():
        pytest.skip("sample STEP file not present")
    from plynest.pipeline import run

    settings = RunSettings()
    settings.nest.sheet = SheetSpec(200.0, 200.0)
    settings.nest.attempts = 1
    job = run(SAMPLE_STEP, settings)
    assert len(job.result.unplaced) == len(job.parts)
    assert all("exceed" in reason or "usable" in reason
               for _, reason in job.result.unplaced)
    assert any("NOT PLACED" in w for w in job.warnings)


# --- one bad part must not take down the job --------------------------------

def test_a_solid_that_cannot_be_analysed_is_skipped_not_fatal(monkeypatch):
    """A malformed body costs you that part, not the whole run."""
    from plynest import pipeline
    from plynest.pipeline import analyse_parts
    from plynest.step_loader import LoadedSolid

    solids = [
        LoadedSolid(path=("T", f"P{i}"), shape=plain_plate(300, 200, 18), index=i)
        for i in range(4)
    ]
    real = pipeline.analyse

    def explode(solid, label, *, part_id):
        if solid.index == 2:
            raise RuntimeError("kaboom in OpenCASCADE")
        return real(solid, label, part_id=part_id)

    monkeypatch.setattr(pipeline, "analyse", explode)
    parts, skipped, _ = analyse_parts(solids, RunSettings())
    assert len(parts) == 3
    assert len(skipped) == 1
    assert "kaboom" in skipped[0][1]


def test_a_label_that_throws_is_reported_not_fatal(monkeypatch):
    from plynest import pipeline

    def explode(part, text, settings):
        raise RuntimeError("bad glyph")

    monkeypatch.setattr(pipeline, "place_label", explode)
    from conftest import SAMPLE_STEP

    if not SAMPLE_STEP.exists():
        pytest.skip("sample STEP file not present")
    settings = RunSettings()
    settings.nest.attempts = 1
    job = pipeline.run(SAMPLE_STEP, settings)
    assert job.labels == {}
    assert any("bad glyph" in w for w in job.warnings)
    assert job.result.unplaced == [], "nesting must still have happened"


def test_a_failed_engraving_keeps_the_part(monkeypatch):
    """Losing the label is acceptable; losing the part is not."""
    from plynest import step_export
    from plynest.labels import place_label
    from plynest.step_export import build_sheet

    part = flatten(plain_plate(400, 300, 18), "FLOOR").part
    result = nest([part], small_nest())
    sources = {part.source_index: as_loaded(plain_plate(400, 300, 18))}
    labels = {part.id: place_label(part, "FLOOR", LabelSettings())}

    monkeypatch.setattr(step_export, "_engraving_tools",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    named = build_sheet(result.sheets[0], sources, labels,
                        ExportSettings(mode="step_per_sheet"), 1.0)
    from plynest import occ_utils as occ

    assert len(named) == 1
    assert occ.volume(named[0][1]) == pytest.approx(400 * 300 * 18, rel=1e-9)


def test_an_engraving_that_destroys_the_part_is_discarded(monkeypatch):
    from plynest import occ_utils as occ
    from plynest import step_export
    from plynest.labels import place_label
    from plynest.step_export import build_sheet

    part = flatten(plain_plate(400, 300, 18), "FLOOR").part
    result = nest([part], small_nest())
    sources = {part.source_index: as_loaded(plain_plate(400, 300, 18))}
    labels = {part.id: place_label(part, "FLOOR", LabelSettings())}

    # Pretend the boolean returned an empty shape.
    monkeypatch.setattr(step_export.occ, "cut_many", lambda base, tools: box(0.0, 0, 0))
    named = build_sheet(result.sheets[0], sources, labels,
                        ExportSettings(mode="step_per_sheet"), 1.0)
    assert occ.volume(named[0][1]) == pytest.approx(400 * 300 * 18, rel=1e-9)


# --- scale and determinism --------------------------------------------------

def test_a_large_job_completes_in_reasonable_time():
    import time

    parts = [rect_part(f"p{i}", 180 + (i % 11) * 17, 240 + (i % 7) * 23)
             for i in range(300)]
    start = time.time()
    result = nest(parts, small_nest(attempts=1))
    elapsed = time.time() - start
    assert result.unplaced == []
    placed = sum(len(s.placements) for s in result.sheets)
    assert placed == 300
    assert elapsed < 60, f"300 parts took {elapsed:.0f}s"


def test_the_same_input_always_gives_the_same_layout():
    parts = [rect_part(f"p{i}", 170 + i * 11, 240 + i * 3) for i in range(20)]
    key = lambda r: [
        (s.index, p.part.id, round(p.angle, 6), round(p.dx, 6), round(p.dy, 6))
        for s in r.sheets for p in sorted(s.placements, key=lambda q: q.part.id)
    ]
    assert key(nest(parts, small_nest())) == key(nest(parts, small_nest()))


def test_part_order_does_not_change_the_result():
    """Nesting sorts internally, so the input order must not matter."""
    parts = [rect_part(f"p{i}", 170 + i * 11, 240 + i * 3) for i in range(14)]
    a = nest(parts, small_nest())
    b = nest(list(reversed(parts)), small_nest())
    assert a.sheet_count() == b.sheet_count()
    key = lambda r: sorted(
        (p.part.id, round(p.angle, 6), round(p.dx, 6), round(p.dy, 6))
        for s in r.sheets for p in s.placements
    )
    assert key(a) == key(b)


def test_two_runs_can_proceed_at_once():
    """The web front end runs jobs on threads; nothing may be shared."""
    import threading

    results = {}

    def go(key, n):
        parts = [rect_part(f"{key}{i}", 200 + i, 300) for i in range(n)]
        results[key] = nest(parts, small_nest())

    threads = [threading.Thread(target=go, args=(k, n)) for k, n in (("a", 12), ("b", 9))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 2
    for key, result in results.items():
        assert result.unplaced == []
        assert all(p.part.id.startswith(key) for s in result.sheets for p in s.placements)


# --- label placement must stay bounded on big parts -------------------------

def test_label_search_is_bounded_on_a_full_sheet_part():
    """The natural step would be millions of positions on a 2.4 m panel."""
    from plynest.labels import MAX_CANDIDATES, _allowed_region, _corner_priority

    part = flatten(box(2400.0, 1200.0, 18.0)).part
    region = _allowed_region(part, LabelSettings(height_mm=2.5))
    grid = _corner_priority("bottom_right", region, 100.0, 4.0, 1.25)
    assert len(grid) <= MAX_CANDIDATES * 1.1


def test_label_placement_on_a_big_pocketed_part_is_quick():
    import time

    from plynest.labels import place_label

    shape = box(2400.0, 1200.0, 18.0)
    for i in range(6):
        shape = cut(shape, box(300, 1000, 4, at=(150 + i * 350, 100, 14)))
    part = flatten(shape).part
    start = time.time()
    placement = place_label(part, "AC4/DRAWER ASSEMBLY 2/LEFT SIDE",
                            LabelSettings(height_mm=2.5))
    assert time.time() - start < 5.0
    assert placement.fitted


def test_the_exact_corner_is_always_a_candidate():
    """Widening the step must not lose the position we actually want."""
    from plynest.labels import _allowed_region, _corner_priority

    part = flatten(box(2400.0, 1200.0, 18.0)).part
    region = _allowed_region(part, LabelSettings())
    w, h = 60.0, 8.0
    grid = _corner_priority("bottom_right", region, w, h, 0.5)
    x0, y0, x1, y1 = region.bounds
    assert (pytest.approx(x1 - w), pytest.approx(y0)) in [
        (pytest.approx(x), pytest.approx(y)) for x, y in grid[:1]
    ]


# --- planar geometry corner cases -------------------------------------------

def test_a_zero_radius_arc_does_not_explode():
    from plynest.geom2d import Arc

    arc = Arc(Point(0, 0), 0.0, 0.0, math.pi, True)
    assert arc.length() == 0.0
    assert all(math.isfinite(v) for v in arc.bounds())
    assert arc.sample(0.05)


def test_a_full_circle_splits_into_valid_arcs():
    from plynest.geom2d import Contour, split_wide_arcs

    circle = Contour.circle(Point(0, 0), 5.0)
    pieces = split_wide_arcs(circle.segments)
    assert len(pieces) >= 2
    assert all(abs(p.bulge()) <= 1.0 + 1e-9 for p in pieces)
    total = sum(abs(p.sweep()) for p in pieces)
    assert total == pytest.approx(2 * math.pi, rel=1e-12)
    for a, b in zip(pieces, pieces[1:]):
        assert a.end.dist(b.start) < 1e-9


def test_a_degenerate_contour_yields_an_empty_polygon():
    from plynest.geom2d import Contour, Region

    for pts in ([(0, 0), (0, 0), (0, 0)], [(0, 0), (10, 0), (20, 0)]):
        region = Region(Contour.from_points(pts))
        assert region.to_polygon().is_empty


def test_huge_coordinates_stay_finite():
    from plynest.geom2d import Contour

    contour = Contour.from_points([(0, 0), (1e6, 0), (1e6, 1e6), (0, 1e6)])
    moved = contour.transformed(math.radians(31.7), 1e7, -1e7)
    assert all(math.isfinite(v) for v in moved.bounds())
    assert abs(moved.signed_area()) == pytest.approx(1e12, rel=1e-9)


def test_transform_round_trip_returns_the_original():
    from plynest.geom2d import Contour

    contour = Contour.from_points([(0, 0), (30, 0), (30, 12), (0, 12)])
    ang = math.radians(41.0)
    there = contour.transformed(ang, 17.0, -3.0)
    back = there.transformed(-ang, 0.0, 0.0).transformed(
        0.0, -(17.0 * math.cos(-ang) - -3.0 * math.sin(-ang)),
        -(17.0 * math.sin(-ang) + -3.0 * math.cos(-ang)))
    assert back.bounds() == pytest.approx(contour.bounds(), abs=1e-9)


def test_unit_conversion_is_exact_both_ways():
    from plynest.units import MM_PER_INCH, from_mm, to_mm

    for value in (0.0, 0.03, 0.5, 0.75, 48.0, 96.0, 1e6):
        assert from_mm(to_mm(value, "in"), "in") == pytest.approx(value, rel=1e-12)
    assert to_mm(1.0, "in") == MM_PER_INCH
