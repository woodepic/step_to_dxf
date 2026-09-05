"""The command line is a supported entry point; drive it the way a user would."""
from __future__ import annotations

import ezdxf
import pytest

from conftest import SAMPLE_STEP, requires_sample
from plynest.cli import EXIT_BAD_INPUT, EXIT_OK, EXIT_UNPLACED, main

pytestmark = requires_sample


def run_cli(tmp_path, *args) -> int:
    return main([str(SAMPLE_STEP), "-o", str(tmp_path), "--quiet", *args])


def test_default_run_writes_a_dxf_per_sheet(tmp_path, capsys):
    assert run_cli(tmp_path) == EXIT_OK
    files = sorted(tmp_path.glob("*.dxf"))
    assert files
    assert all(f.name.startswith("Sheet ") and f.name.endswith(" in.dxf") for f in files)
    out = capsys.readouterr().out
    assert "112 parts" in out and "utilisation" in out


def test_millimetre_units(tmp_path):
    assert run_cli(tmp_path, "--unit", "mm", "--sheet-width", "1219.2",
                   "--sheet-height", "2438.4", "--kerf", "6.35",
                   "--edge-keepout", "25.4", "--label-height", "6",
                   "--label-depth", "1") == EXIT_OK
    doc = ezdxf.readfile(str(sorted(tmp_path.glob("*.dxf"))[0]))
    assert doc.header["$INSUNITS"] == 4
    assert any(l.dxf.name.endswith("mm deep") for l in doc.layers)


def test_per_part_mode(tmp_path):
    assert run_cli(tmp_path, "--mode", "dxf_per_part") == EXIT_OK
    assert len(list(tmp_path.glob("*.dxf"))) == 112


def test_no_labels(tmp_path):
    assert run_cli(tmp_path, "--no-labels") == EXIT_OK
    doc = ezdxf.readfile(str(sorted(tmp_path.glob("*.dxf"))[0]))
    assert not any(l.dxf.name.startswith("ENGRAVE") for l in doc.layers)


def test_keepout_layer_is_opt_in(tmp_path):
    assert run_cli(tmp_path, "--keepout-layer") == EXIT_OK
    doc = ezdxf.readfile(str(sorted(tmp_path.glob("*.dxf"))[0]))
    assert any(l.dxf.name.startswith("EDGE KEEP") for l in doc.layers)


def test_rotation_modes(tmp_path):
    for mode in ("none", "180", "90", "free"):
        out = tmp_path / mode
        assert main([str(SAMPLE_STEP), "-o", str(out), "--quiet",
                     "--rotation", mode, "--attempts", "1"]) == EXIT_OK
        assert list(out.glob("*.dxf"))


def test_step_mode_without_engraving_is_quick(tmp_path):
    assert run_cli(tmp_path, "--mode", "step_per_sheet",
                   "--no-engrave-in-step", "--attempts", "1") == EXIT_OK
    files = sorted(tmp_path.glob("*.step"))
    assert files and all(f.name.startswith("Sheet ") for f in files)


def test_a_sheet_too_small_reports_unplaced_parts(tmp_path, capsys):
    code = run_cli(tmp_path, "--sheet-width", "4", "--sheet-height", "4",
                   "--attempts", "1")
    assert code == EXIT_UNPLACED, "unplaced parts must be a non-zero exit"
    assert "NOT PLACED" in capsys.readouterr().out


def test_a_bad_input_file_is_a_clean_error(tmp_path, capsys):
    bad = tmp_path / "bad.step"
    bad.write_text("definitely not a STEP file")
    assert main([str(bad), "-o", str(tmp_path / "out"), "--quiet"]) == EXIT_BAD_INPUT
    assert "Could not read" in capsys.readouterr().err


def test_a_missing_input_file_is_a_clean_error(tmp_path, capsys):
    assert main([str(tmp_path / "nope.step"), "-o", str(tmp_path)]) == EXIT_BAD_INPUT
    assert "Could not read" in capsys.readouterr().err


@pytest.mark.parametrize("args", [
    ("--kerf", "-1"),
    ("--edge-keepout", "-3"),
    ("--sheet-width", "0"),
    ("--sheet-height", "-96"),
])
def test_impossible_settings_are_refused_before_any_work(tmp_path, args, capsys):
    assert run_cli(tmp_path, *args) == EXIT_BAD_INPUT
    assert capsys.readouterr().err.strip()
    assert not list(tmp_path.glob("*"))


def test_help_does_not_need_a_file(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "plynest" in capsys.readouterr().out
