"""FastAPI back end: upload a STEP file, nest it, preview it, download DXF.

Runs are executed on a worker thread and polled, because nesting a full
assembly takes long enough that a synchronous request would time out.
"""
from __future__ import annotations

import shutil
import threading
import traceback
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..config import ExportSettings, RunSettings
from ..dxf_export import export
from ..geom2d import ARC_CHORD_TOL
from ..naming import sheet_name
from ..pipeline import Job, run as run_pipeline
from ..step_export import export_step
from ..units import from_mm

STATIC_DIR = Path(__file__).parent / "static"
WORK_DIR = Path.home() / ".plynest" / "runs"
WORK_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = 512 * 1024 * 1024


@dataclass
class RunState:
    run_id: str
    stage: str = "queued"
    progress: float = 0.0
    error: str | None = None
    job: Job | None = None
    settings: RunSettings | None = None
    source: Path | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    # Export runs on its own thread too: engraving labels into 100+ solids for a
    # STEP export takes long enough that a synchronous request would look hung.
    export_stage: str = "idle"
    export_progress: float = 0.0
    export_error: str | None = None
    export_files: list[str] = field(default_factory=list)
    export_zip: str | None = None


app = FastAPI(title="plynest", version="0.1.0")
_uploads: dict[str, Path] = {}
_runs: dict[str, RunState] = {}


class RunRequest(BaseModel):
    upload_id: str
    settings: dict[str, Any] = Field(default_factory=dict)


class ExportRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    name = Path(file.filename or "upload.step").name
    if not name.lower().endswith((".step", ".stp")):
        raise HTTPException(400, "Please upload a .step or .stp file")

    upload_id = uuid.uuid4().hex[:12]
    target_dir = WORK_DIR / upload_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / name

    size = 0
    with target.open("wb") as fh:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                fh.close()
                shutil.rmtree(target_dir, ignore_errors=True)
                raise HTTPException(413, "File is larger than 512 MB")
            fh.write(chunk)

    _uploads[upload_id] = target
    return {"upload_id": upload_id, "filename": name, "bytes": size}


def _worker(state: RunState) -> None:
    def progress(stage: str, frac: float) -> None:
        with state.lock:
            state.stage = stage
            state.progress = frac

    try:
        assert state.source is not None and state.settings is not None
        job = run_pipeline(state.source, state.settings, progress)
        with state.lock:
            state.job = job
            state.stage = "done"
            state.progress = 1.0
    except Exception as exc:  # surfaced to the browser rather than swallowed
        with state.lock:
            state.error = f"{type(exc).__name__}: {exc}"
            state.stage = "error"
            state.progress = 1.0
        traceback.print_exc()


@app.post("/api/run")
def start_run(req: RunRequest) -> dict[str, Any]:
    source = _uploads.get(req.upload_id)
    if source is None or not source.exists():
        raise HTTPException(404, "Upload not found; please upload the file again")

    run_id = uuid.uuid4().hex[:12]
    state = RunState(run_id=run_id, source=source, settings=RunSettings.from_dict(req.settings))
    _runs[run_id] = state
    threading.Thread(target=_worker, args=(state,), daemon=True).start()
    return {"run_id": run_id}


@app.get("/api/run/{run_id}")
def run_status(run_id: str) -> dict[str, Any]:
    state = _runs.get(run_id)
    if state is None:
        raise HTTPException(404, "Unknown run")
    with state.lock:
        payload: dict[str, Any] = {
            "run_id": run_id,
            "stage": state.stage,
            "progress": state.progress,
            "error": state.error,
        }
        if state.job is not None:
            payload["summary"] = state.job.summary()
            payload["warnings"] = state.job.warnings
            payload["skipped"] = state.job.skipped
    return payload


def _ring(points) -> list[list[float]]:
    return [[round(p.x, 3), round(p.y, 3)] for p in points]


@app.get("/api/run/{run_id}/layout")
def layout(run_id: str) -> dict[str, Any]:
    """Flattened geometry for the browser preview, in millimetres."""
    state = _runs.get(run_id)
    if state is None:
        raise HTTPException(404, "Unknown run")
    with state.lock:
        job = state.job
        settings = state.settings
    if job is None:
        raise HTTPException(409, "Run is not finished")
    assert settings is not None

    sheets = []
    for sheet in job.result.sheets:
        parts = []
        for placement in sheet.placements:
            ang, dx, dy = placement.transform()
            part = placement.part
            profile = part.profile.transformed(ang, dx, dy)
            entry: dict[str, Any] = {
                "id": part.id,
                "label": part.label,
                "path": "/".join(part.path),
                "angle": placement.angle,
                "flipped": part.flipped,
                "outline": _ring(profile.outer.sample(ARC_CHORD_TOL)),
                "holes": [_ring(h.sample(ARC_CHORD_TOL)) for h in profile.holes],
                "pockets": [],
                "label_strokes": [],
                "width_mm": round(part.width, 3),
                "height_mm": round(part.height, 3),
                "thickness_mm": round(part.thickness, 3),
                "warnings": list(part.warnings),
            }
            for pocket in part.pockets:
                region = pocket.region.transformed(ang, dx, dy)
                entry["pockets"].append({
                    "depth": round(pocket.depth, 3),
                    "rings": [_ring(c.sample(ARC_CHORD_TOL)) for c in region.contours()],
                })
            placed_label = job.labels.get(part.id)
            if placed_label and placed_label.fitted:
                entry["label_strokes"] = [
                    _ring(chain)
                    for chain in placed_label.transformed(ang, dx, dy).sampled(ARC_CHORD_TOL)
                ]
            parts.append(entry)

        depths = sorted({round(pk.depth, 3) for p in sheet.placements for pk in p.part.pockets})
        sheets.append({
            "index": sheet.index,
            "thickness_mm": round(sheet.thickness, 3),
            "width_mm": sheet.spec.width_mm,
            "height_mm": sheet.spec.height_mm,
            "usable": [round(v, 3) for v in sheet.usable],
            "utilisation": round(sheet.utilisation(), 4),
            "pocket_depths": depths,
            "parts": parts,
        })

    return {
        "run_id": run_id,
        "sheets": sheets,
        "summary": job.summary(),
        "warnings": job.warnings,
        "unplaced": [{"label": p.label, "reason": r} for p, r in job.result.unplaced],
    }


@app.post("/api/run/{run_id}/export")
def export_run(run_id: str, req: ExportRequest) -> dict[str, Any]:
    state = _runs.get(run_id)
    if state is None:
        raise HTTPException(404, "Unknown run")
    with state.lock:
        if state.job is None:
            raise HTTPException(409, "Run is not finished")
        if state.export_stage == "working":
            raise HTTPException(409, "An export is already running")
        state.export_stage = "working"
        state.export_progress = 0.0
        state.export_error = None
        state.export_files = []
        state.export_zip = None

    defaults = ExportSettings()
    export_settings = ExportSettings(**{
        **defaults.__dict__,
        **{k: v for k, v in req.settings.items() if k in defaults.__dict__},
    })
    threading.Thread(target=_export_worker, args=(state, export_settings), daemon=True).start()
    return {"started": True}


def _export_worker(state: RunState, export_settings: ExportSettings) -> None:
    try:
        with state.lock:
            job = state.job
            settings = state.settings
        assert job is not None and settings is not None

        out_dir = WORK_DIR / state.run_id / "export"
        if out_dir.exists():
            shutil.rmtree(out_dir)

        def note(stage: str, frac: float) -> None:
            with state.lock:
                state.export_stage = stage
                state.export_progress = frac

        if export_settings.mode == "step_per_sheet":
            note("Rebuilding solids and engraving labels", 0.05)
            paths = export_step(
                job.result, export_settings, out_dir, job.sources,
                labels=job.labels if export_settings.include_labels else None,
                label_depth_mm=settings.labels.depth_mm,
                sheet_namer=lambda sh: sheet_name(sh.index, sh.thickness, export_settings.unit),
                progress=lambda done, total: note(
                    f"Writing sheet {done} of {total}", 0.05 + 0.85 * done / max(total, 1)
                ),
            )
        else:
            note("Writing DXF", 0.2)
            paths = export(
                job.result, export_settings, out_dir,
                labels=job.labels if export_settings.include_labels else None,
                label_depth_mm=settings.labels.depth_mm,
                parts=job.parts,
            )

        note("Packing zip", 0.93)
        archive = WORK_DIR / state.run_id / f"{_zip_stem(job, export_settings)}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in paths:
                zf.write(path, path.name)
            zf.writestr("Layout report.txt", _report(job, export_settings))

        with state.lock:
            state.export_files = [p.name for p in paths]
            state.export_zip = archive.name
            state.export_stage = "done"
            state.export_progress = 1.0
    except Exception as exc:
        with state.lock:
            state.export_error = f"{type(exc).__name__}: {exc}"
            state.export_stage = "error"
            state.export_progress = 1.0
        traceback.print_exc()


def _zip_stem(job: Job, settings: ExportSettings) -> str:
    kind = {
        "dxf_per_sheet": "DXF by sheet",
        "dxf_per_part": "DXF by part",
        "step_per_sheet": "STEP by sheet",
    }.get(settings.mode, "export")
    return f"{Path(job.source_name).stem} - {kind}"


@app.get("/api/run/{run_id}/export/status")
def export_status(run_id: str) -> dict[str, Any]:
    state = _runs.get(run_id)
    if state is None:
        raise HTTPException(404, "Unknown run")
    with state.lock:
        return {
            "stage": state.export_stage,
            "progress": state.export_progress,
            "error": state.export_error,
            "files": state.export_files,
            "zip": state.export_zip,
            "download": f"/api/run/{run_id}/download",
        }


def _report(job: Job, settings: ExportSettings) -> str:
    unit = settings.unit
    lines = [
        f"plynest layout report for {job.source_name}",
        "=" * 60,
        f"Parts nested : {len(job.parts)}",
        f"Sheets       : {job.result.sheet_count()}",
        f"Utilisation  : {job.result.total_utilisation() * 100:.1f}%",
        f"Units        : {unit}",
        f"Export       : {settings.mode}",
        "",
    ]
    for sheet in job.result.sheets:
        lines.append(
            f"{sheet_name(sheet.index, sheet.thickness, unit)}  "
            f"-  {len(sheet.placements)} parts, {sheet.utilisation() * 100:.1f}% used"
        )
        for placement in sorted(sheet.placements, key=lambda p: p.part.label):
            part = placement.part
            lines.append(
                f"    {part.label:<34s} "
                f"{from_mm(part.width, unit):8.3f} x {from_mm(part.height, unit):8.3f} {unit}"
                f"  rot {placement.angle:>5.1f}deg"
                + ("  [FLIPPED]" if part.flipped else "")
            )
        lines.append("")
    if job.warnings:
        lines.append("Warnings:")
        lines += [f"  - {w}" for w in job.warnings]
    if job.skipped:
        lines.append("")
        lines.append("Skipped solids:")
        lines += [f"  - {p}: {why}" for p, why in job.skipped]
    return "\n".join(lines)


@app.get("/api/run/{run_id}/download")
def download(run_id: str):
    state = _runs.get(run_id)
    if state is None or state.job is None:
        raise HTTPException(404, "Unknown run")
    with state.lock:
        name = state.export_zip
    if not name:
        raise HTTPException(404, "Nothing exported yet")
    archive = WORK_DIR / run_id / name
    if not archive.exists():
        raise HTTPException(404, "Nothing exported yet")
    return FileResponse(archive, filename=archive.name, media_type="application/zip")


@app.get("/api/defaults")
def defaults() -> dict[str, Any]:
    return RunSettings().to_dict()


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
