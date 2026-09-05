"""File and layer names must be readable and safe on every filesystem."""
from __future__ import annotations

import pytest

from plynest.naming import (
    engrave_layer,
    format_thickness,
    pocket_layer,
    safe_filename,
    sheet_name,
    through_layer,
    unique_filenames,
)


@pytest.mark.parametrize("mm,unit,want", [
    (19.05, "in", "0.75 in"),
    (12.7, "in", "0.5 in"),
    (6.35, "in", "0.25 in"),
    (19.05, "mm", "19.05 mm"),
    (12.7, "mm", "12.7 mm"),
    (18.0, "mm", "18 mm"),
])
def test_format_thickness(mm, unit, want):
    assert format_thickness(mm, unit) == want


def test_sheet_names_are_one_based_and_readable():
    assert sheet_name(0, 19.05, "in") == "Sheet 1, 0.75 in"
    assert sheet_name(5, 12.7, "in") == "Sheet 6, 0.5 in"
    assert sheet_name(2, 18.0, "mm") == "Sheet 3, 18 mm"


def test_layer_names_state_depth_from_the_top_face():
    assert through_layer(19.05, "in") == "CUT THROUGH 0.75 in deep"
    assert pocket_layer(6.35, "in") == "POCKET 0.25 in deep"
    assert engrave_layer(1.0, "mm") == "ENGRAVE 1 mm deep"


@pytest.mark.parametrize("bad", ["<", ">", "/", "\\", '"', ":", ";", "?", "*", "|", "=", "'"])
def test_layer_names_never_contain_characters_autocad_rejects(bad):
    assert bad not in through_layer(19.05, "in")
    assert bad not in pocket_layer(3.0, "mm")


def test_slashes_in_a_part_name_become_hyphens():
    assert safe_filename("AC4/DA2/Front Side") == "AC4-DA2-Front Side"


@pytest.mark.parametrize("bad", ['a<b', 'a>b', 'a:b', 'a"b', 'a|b', 'a?b', 'a*b', 'a\\b'])
def test_filenames_drop_characters_windows_rejects(bad):
    out = safe_filename(bad)
    assert not set(out) & set('<>:"/\\|?*')


def test_filename_never_comes_back_empty():
    assert safe_filename("///") == "part"
    assert safe_filename("") == "part"


def test_colliding_filenames_are_numbered():
    assert unique_filenames(["A/B", "A-B", "Other"]) == ["A-B", "A-B (2)", "Other"]


def test_unique_filenames_is_case_insensitive():
    """Windows and macOS would otherwise overwrite one with the other."""
    assert unique_filenames(["Floor", "floor"]) == ["Floor", "floor (2)"]


def test_sheet_name_survives_being_made_a_filename():
    name = safe_filename(sheet_name(0, 19.05, "in"))
    assert name == "Sheet 1, 0.75 in"
