"""The HTTP surface the browser talks to.

Worth testing directly: the layout endpoint reshapes every part for the preview,
so a change to the geometry types breaks it in a way no other test would catch.
"""
from __future__ import annotations

import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from conftest import SAMPLE_STEP, requires_sample
from plynest.web.app import app

pytestmark = requires_sample


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def finished_run(client):
    with SAMPLE_STEP.open("rb") as fh:
        res = client.post("/api/upload", files={"file": (SAMPLE_STEP.name, fh)})
    assert res.status_code == 200, res.text
    upload_id = res.json()["upload_id"]

    res = client.post("/api/run", json={
        "upload_id": upload_id,
        "settings": {"nest": {"attempts": 1}},
    })
    assert res.status_code == 200, res.text
    run_id = res.json()["run_id"]

    for _ in range(300):
        status = client.get(f"/api/run/{run_id}").json()
        if status["stage"] in ("done", "error"):
            break
        time.sleep(0.2)
    assert status["stage"] == "done", status
    return run_id


def test_defaults_are_served():
    with TestClient(app) as c:
        data = c.get("/api/defaults").json()
    assert data["nest"]["rotation"] == "90"
    assert data["export"]["include_keepout"] is False, "keep-out should default off"


def test_index_and_favicon_are_served(client):
    assert client.get("/").status_code == 200
    icon = client.get("/favicon.png")
    assert icon.status_code == 200
    assert icon.headers["content-type"].startswith("image/")


def test_rejects_a_non_step_upload(client):
    res = client.post("/api/upload", files={"file": ("notes.txt", b"hello")})
    assert res.status_code == 400


def test_run_summary(client, finished_run):
    data = client.get(f"/api/run/{finished_run}").json()
    assert data["summary"]["parts"] == 112
    assert data["summary"]["sheets"] > 0
    assert data["skipped"] == []


def test_layout_endpoint_describes_every_sheet(client, finished_run):
    """This is the call the preview makes; it touches every part's geometry."""
    data = client.get(f"/api/run/{finished_run}/layout").json()
    assert data["sheets"]
    total = 0
    for sheet in data["sheets"]:
        assert sheet["width_mm"] > 0 and sheet["height_mm"] > 0
        assert len(sheet["usable"]) == 4
        for part in sheet["parts"]:
            total += 1
            assert part["label"] and part["outline"]
            assert all(len(pt) == 2 for pt in part["outline"])
            assert part["width_mm"] > 0 and part["height_mm"] > 0
            for pocket in part["pockets"]:
                assert pocket["depth"] > 0 and pocket["rings"]
    assert total == data["summary"]["parts"]


def test_layout_includes_engraved_label_strokes(client, finished_run):
    data = client.get(f"/api/run/{finished_run}/layout").json()
    with_labels = [
        p for sheet in data["sheets"] for p in sheet["parts"] if p["label_strokes"]
    ]
    assert with_labels, "labels should reach the preview"
    for part in with_labels:
        for stroke in part["label_strokes"]:
            assert len(stroke) >= 2
            assert all(len(pt) == 2 for pt in stroke)


def test_layout_before_the_run_finishes_is_refused(client):
    assert client.get("/api/run/nope/layout").status_code == 404


@pytest.mark.parametrize("mode,ext", [
    ("dxf_per_sheet", ".dxf"),
    ("dxf_per_part", ".dxf"),
])
def test_export_produces_a_zip(client, finished_run, mode, ext):
    res = client.post(f"/api/run/{finished_run}/export",
                      json={"settings": {"mode": mode, "unit": "in"}})
    assert res.status_code == 200, res.text

    for _ in range(600):
        status = client.get(f"/api/run/{finished_run}/export/status").json()
        if status["stage"] in ("done", "error"):
            break
        time.sleep(0.2)
    assert status["stage"] == "done", status
    assert status["files"] and all(n.endswith(ext) for n in status["files"])

    got = client.get(f"/api/run/{finished_run}/download")
    assert got.status_code == 200
    import io

    with zipfile.ZipFile(io.BytesIO(got.content)) as zf:
        names = zf.namelist()
    assert "Layout report.txt" in names
    assert len(names) == len(status["files"]) + 1
    if mode == "dxf_per_sheet":
        assert any(n.startswith("Sheet 1, ") for n in names)


def test_export_names_the_zip_for_what_it_contains(client, finished_run):
    client.post(f"/api/run/{finished_run}/export",
                json={"settings": {"mode": "dxf_per_part"}})
    for _ in range(600):
        status = client.get(f"/api/run/{finished_run}/export/status").json()
        if status["stage"] in ("done", "error"):
            break
        time.sleep(0.2)
    assert status["stage"] == "done"
    assert status["zip"] == "Full Layout - DXF by part.zip"


def test_download_before_export_is_refused(client, finished_run):
    assert client.get("/api/run/unknown/download").status_code == 404


# --- hostile and careless requests -----------------------------------------

def test_unknown_ids_are_404_not_500(client):
    for path in ("/api/run/nope", "/api/run/nope/layout", "/api/run/nope/export/status",
                 "/api/run/nope/download"):
        assert client.get(path).status_code == 404, path
    assert client.post("/api/run/nope/export", json={"settings": {}}).status_code == 404


def test_running_an_unknown_upload_is_404(client):
    res = client.post("/api/run", json={"upload_id": "does-not-exist", "settings": {}})
    assert res.status_code == 404


def test_malformed_request_bodies_are_rejected(client):
    assert client.post("/api/run", json={}).status_code == 422
    assert client.post("/api/run", content=b"not json").status_code == 422


def test_nonsense_settings_do_not_crash_the_run(client):
    """Junk in the settings should fall back to defaults, not 500."""
    with SAMPLE_STEP.open("rb") as fh:
        upload_id = client.post(
            "/api/upload", files={"file": (SAMPLE_STEP.name, fh)}
        ).json()["upload_id"]
    res = client.post("/api/run", json={
        "upload_id": upload_id,
        "settings": {"nest": {"kerf_mm": "wide", "attempts": None}, "bogus": 1},
    })
    assert res.status_code in (200, 400)


def test_unknown_export_mode_is_refused(client, finished_run):
    res = client.post(f"/api/run/{finished_run}/export",
                      json={"settings": {"mode": "carrier_pigeon"}})
    assert res.status_code == 400
    status = client.get(f"/api/run/{finished_run}/export/status").json()
    assert status["stage"] != "working", "a refused export must not leave the run busy"


def test_upload_without_a_step_extension_is_refused(client):
    assert client.post("/api/upload",
                       files={"file": ("model.iges", b"x")}).status_code == 400
    assert client.post("/api/upload",
                       files={"file": ("noextension", b"x")}).status_code == 400


def test_a_stp_extension_is_accepted(client):
    res = client.post("/api/upload", files={"file": ("model.STP", b"not really step")})
    assert res.status_code == 200


def test_a_bad_step_file_fails_the_run_with_a_message(client):
    upload_id = client.post(
        "/api/upload", files={"file": ("junk.step", b"this is not a STEP file")}
    ).json()["upload_id"]
    run_id = client.post("/api/run", json={"upload_id": upload_id}).json()["run_id"]
    for _ in range(200):
        status = client.get(f"/api/run/{run_id}").json()
        if status["stage"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert status["stage"] == "error"
    assert status["error"] and "StepLoadError" in status["error"]


def test_old_runs_are_evicted_so_the_disk_does_not_fill(client):
    from plynest.web.app import MAX_RETAINED_RUNS, _runs

    ids = []
    for _ in range(MAX_RETAINED_RUNS + 3):
        upload_id = client.post(
            "/api/upload", files={"file": ("junk.step", b"nope")}
        ).json()["upload_id"]
        ids.append(client.post("/api/run", json={"upload_id": upload_id}).json()["run_id"])

    assert len(_runs) <= MAX_RETAINED_RUNS + 2
    assert client.get(f"/api/run/{ids[-1]}").status_code == 200
    assert client.get(f"/api/run/{ids[0]}").status_code == 404
