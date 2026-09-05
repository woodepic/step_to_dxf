"""Write the nested layout back out as STEP.

This is the "rearrange my assembly" mode: it takes the *original* solids from
the input file, applies the pose the orienter chose and the position the nester
chose, and optionally cuts the engraved label into the top face.  Nothing is
re-modelled from the 2D profile, so every fillet, chamfer and hole in the source
survives untouched.

One file per sheet, since one sheet is one physical panel.
"""
from __future__ import annotations

from pathlib import Path

from OCP.IFSelect import IFSelect_ReturnStatus
from OCP.Interface import Interface_Static
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_StepModelType
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDocStd import TDocStd_Document
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from shapely.geometry import LineString
from shapely.ops import unary_union

from . import occ_utils as occ
from .config import ExportSettings
from .labels import LabelPlacement
from .naming import safe_filename
from .nest import NestResult, Placement, Sheet
from .step_loader import LoadedSolid

ENGRAVE_OVERSHOOT = 0.01
"""How far the engraving tool breaks the top surface, so the cut is clean."""

ENGRAVE_QUAD_SEGS = 2
"""Segments per quarter turn on the groove's round ends and corners.

A 0.03 in groove has a 0.38 mm cap; nobody is inspecting its facets, and every
extra vertex is another face in the boolean."""

ENGRAVE_SIMPLIFY = 0.04
"""Vertex-thinning tolerance (mm) applied to the groove outline."""


def _engrave_tolerance(height_mm: float, width_mm: float) -> float:
    """Chord tolerance for flattening label curves into groove geometry.

    Solid text is expensive: every vertex of the groove outline becomes a face
    of the cut, and each face costs roughly a hundred STEP entities.  This is a
    representation of the engraving -- the cut itself comes from the DXF, which
    keeps exact arcs -- so a fraction of the cap height is plenty.  Narrow
    grooves get a proportionally finer tolerance so they do not look ragged.
    """
    return max(0.08, min(height_mm / 24.0, width_mm / 3.0))


class StepExportError(RuntimeError):
    pass


def _engraving_tools(placement: Placement, label: LabelPlacement | None,
                     settings: ExportSettings, depth_mm: float) -> list:
    """Prisms to subtract for the engraved label, in sheet coordinates."""
    if label is None or not label.fitted or not settings.engrave_labels_in_step:
        return []
    width = max(settings.engrave_tool_mm, 1e-3)
    tol = _engrave_tolerance(label.height, width)
    strokes = [
        LineString([(p.x, p.y) for p in chain])
        for chain in label.sampled(tol)
        if len(chain) >= 2
    ]
    if not strokes:
        return []
    # A router leaves a round-ended groove, so buffer with round caps and joins.
    grooves = unary_union([
        s.buffer(width / 2.0, cap_style=1, join_style=1, quad_segs=ENGRAVE_QUAD_SEGS)
        for s in strokes
    ])
    if ENGRAVE_SIMPLIFY > 0:
        grooves = grooves.simplify(ENGRAVE_SIMPLIFY)
    polys = list(getattr(grooves, "geoms", [grooves]))

    part = placement.part
    depth = min(depth_mm, part.thickness * 0.9)
    z0 = part.thickness - depth
    ang, dx, dy = placement.transform()

    tools = []
    for poly in polys:
        if poly.is_empty or poly.geom_type != "Polygon":
            continue
        face = occ.face_from_polygon(poly, z0)
        if face is None:
            continue
        solid = occ.prism(face, depth + ENGRAVE_OVERSHOOT)
        trsf = occ.rotation_z(ang)
        solid = occ.transform_shape(solid, trsf)
        solid = occ.transform_shape(solid, occ.translation(dx, dy, 0.0))
        tools.append(solid)
    return tools


def posed_solid(placement: Placement, source: LoadedSolid):
    """The original solid, moved into its place on the sheet."""
    part = placement.part
    if part.transform is None:
        raise StepExportError(
            f"{part.label}: no recorded orientation, cannot re-pose the original solid"
        )
    shape = occ.transform_shape(source.shape, part.transform)
    ang, dx, dy = placement.transform()
    if abs(ang) > 1e-12:
        shape = occ.transform_shape(shape, occ.rotation_z(ang))
    return occ.transform_shape(shape, occ.translation(dx, dy, 0.0))


def build_sheet(sheet: Sheet, sources: dict[int, LoadedSolid],
                labels: dict[str, LabelPlacement], settings: ExportSettings,
                label_depth_mm: float = 1.0):
    """Return ``[(name, shape), ...]`` for one sheet."""
    out = []
    for placement in sheet.placements:
        part = placement.part
        source = sources.get(part.source_index)
        if source is None:
            raise StepExportError(f"{part.label}: original solid is no longer available")
        shape = posed_solid(placement, source)
        try:
            tools = _engraving_tools(placement, labels.get(part.id), settings, label_depth_mm)
            if tools:
                engraved = occ.cut_many(shape, tools)
                # A boolean that collapses the part is worse than no engraving.
                if occ.volume(engraved) > 0:
                    shape = engraved
        except Exception:
            pass  # keep the part, lose only its engraving
        out.append((part.label, shape))
    return out


def _write(named_shapes, path: Path) -> None:
    """Write shapes to STEP, keeping each part's name."""
    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("plynest-out"))
    app.NewDocument(TCollection_ExtendedString("MDTV-XCAF"), doc)
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

    for name, shape in named_shapes:
        if shape is None or shape.IsNull():
            continue
        label = tool.AddShape(shape, False)
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))

    Interface_Static.SetCVal_s("write.step.unit", "MM")
    Interface_Static.SetIVal_s("write.step.schema", 5)  # AP242
    writer = STEPCAFControl_Writer()
    writer.SetNameMode(True)
    with occ.quiet():
        writer.Transfer(doc, STEPControl_StepModelType.STEPControl_AsIs)
        status = writer.Write(str(path))
    if status != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise StepExportError(f"OpenCASCADE refused to write {path.name} (status={status})")


def export_step(result: NestResult, settings: ExportSettings, out_dir: str | Path,
                sources: dict[int, LoadedSolid],
                labels: dict[str, LabelPlacement] | None = None,
                label_depth_mm: float = 1.0,
                sheet_namer=None, progress=None) -> list[Path]:
    """Write one STEP per sheet; returns the paths written."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    labels = labels or {}
    written: list[Path] = []

    total = len(result.sheets)
    for i, sheet in enumerate(result.sheets):
        named = build_sheet(sheet, sources, labels, settings, label_depth_mm)
        name = sheet_namer(sheet) if sheet_namer else f"Sheet {sheet.index + 1}"
        path = out_dir / f"{safe_filename(name)}.step"
        _write(named, path)
        written.append(path)
        if progress:
            progress(i + 1, total)
    return written
