"""Pipeline plumbing and failure handling."""
from __future__ import annotations

import pytest

from plynest.config import RunSettings, SheetSpec
from plynest.step_loader import LoadedSolid, StepLoadError, abbreviate, label_for, load_step
from plynest.pipeline import unique_labels
from plynest.units import MM_PER_INCH, format_length, from_mm, to_mm


def fake(path, index):
    return LoadedSolid(path=tuple(path), shape=None, index=index)


# --- naming ----------------------------------------------------------------

@pytest.mark.parametrize("raw,want", [
    ("Assembled Cabinet <4>", "AC4"),
    ("Drawer Assembly <2>", "DA2"),
    ("Floor", "Floor"),
    ("Right Wall", "RW"),
    ("Back Side <11>", "BS11"),
])
def test_abbreviate(raw, want):
    assert abbreviate(raw) == want


def test_abbrev_path_label():
    solid = fake(("Doc", "Assembled Cabinet <4>", "Drawer Assembly <2>", "Floor"), 0)
    assert label_for(solid, style="abbrev_path") == "AC4/DA2/Floor"


@pytest.mark.parametrize("style,want", [
    ("name", "Floor"),
    ("name_index", "Floor #1"),
    ("parent_name", "Drawer Assembly <2> / Floor"),
    ("full_path", "Assembled Cabinet <4>/Drawer Assembly <2>/Floor"),
])
def test_label_styles(style, want):
    solid = fake(("Doc", "Assembled Cabinet <4>", "Drawer Assembly <2>", "Floor"), 0)
    assert label_for(solid, style=style) == want


def test_colliding_labels_are_numbered_only_where_they_collide():
    solids = [
        fake(("Doc", "Panel"), 0),
        fake(("Doc", "Panel"), 1),
        fake(("Doc", "Unique"), 2),
    ]
    names = unique_labels(solids, "name")
    assert names[0] == "Panel 1"
    assert names[1] == "Panel 2"
    assert names[2] == "Unique", "a name that is already unique must be left alone"
    assert len(set(names.values())) == 3


# --- units -----------------------------------------------------------------

def test_unit_round_trip():
    for unit in ("mm", "in"):
        assert from_mm(to_mm(3.75, unit), unit) == pytest.approx(3.75)
    assert to_mm(1.0, "in") == pytest.approx(MM_PER_INCH)
    assert to_mm(1.0, "mm") == 1.0


def test_format_length():
    assert format_length(MM_PER_INCH * 0.75, "in") == "0.75in"
    assert format_length(12.7, "mm") == "12.7mm"


def test_sheet_spec_from_units():
    spec = SheetSpec.from_units(48, 96, "in")
    assert (spec.width_mm, spec.height_mm) == pytest.approx((1219.2, 2438.4))


# --- settings --------------------------------------------------------------

def test_settings_round_trip():
    settings = RunSettings()
    settings.nest.kerf_mm = 3.0
    settings.labels.height_mm = 8.0
    settings.export.mode = "per_depth"
    back = RunSettings.from_dict(settings.to_dict())
    assert back.nest.kerf_mm == 3.0
    assert back.labels.height_mm == 8.0
    assert back.export.mode == "per_depth"
    assert back.nest.sheet.width_mm == pytest.approx(settings.nest.sheet.width_mm)


def test_settings_ignore_unknown_keys():
    back = RunSettings.from_dict({"nest": {"kerf_mm": 2.0, "bogus": 1}, "nope": {}})
    assert back.nest.kerf_mm == 2.0


def test_settings_from_empty_dict_uses_defaults():
    assert RunSettings.from_dict({}).nest.rotation == "90"


# --- failure handling ------------------------------------------------------

def test_missing_file():
    with pytest.raises(StepLoadError, match="not found"):
        load_step("/no/such/file.step")


def test_garbage_file(tmp_path):
    bad = tmp_path / "bad.step"
    bad.write_text("this is not a STEP file at all\n")
    with pytest.raises(StepLoadError):
        load_step(bad)


def test_empty_file(tmp_path):
    bad = tmp_path / "empty.step"
    bad.write_bytes(b"")
    with pytest.raises(StepLoadError):
        load_step(bad)


def test_truncated_step_file(tmp_path):
    bad = tmp_path / "truncated.step"
    bad.write_text("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION((''),'2;1');\n")
    with pytest.raises(StepLoadError):
        load_step(bad)
