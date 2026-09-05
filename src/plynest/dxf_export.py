"""Write nested sheets, or individual parts, out as DXF.

Closed profiles become single closed LWPOLYLINEs carrying bulge factors, so an
arc stays an arc all the way into CAM rather than arriving as a hundred tiny
chords.  Engraved labels come through the same way.

Geometry is nominal: kerf was handled as spacing during nesting, so the outlines
here are true part size and the CAM applies the tool offset.

Layers are named for the depth to cut, measured down from the part's top face.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import ezdxf
from ezdxf.document import Drawing

from .config import ExportSettings
from .geom2d import Arc, Contour, Region, Segment, split_wide_arcs
from .labels import LabelPlacement
from .naming import (
    engrave_layer,
    pocket_layer,
    safe_filename,
    sheet_name,
    through_layer,
    unique_filenames,
)
from .nest import NestResult, Sheet
from .part import Part
from .units import INSUNITS

# ACI colour indices, cycled per depth so layers are distinguishable on screen.
DEPTH_COLOURS = [3, 4, 6, 2, 5, 30, 40, 50, 211, 141]
COLOUR_THROUGH = 1
COLOUR_LABEL = 7
COLOUR_SHEET = 8
COLOUR_KEEPOUT = 9

LAYER_SHEET = "SHEET OUTLINE"
LAYER_KEEPOUT = "EDGE KEEP-OUT"

SUPPORTED_DXF_VERSIONS = ("R2000", "R2004", "R2007", "R2010", "R2013", "R2018")
"""R12 is excluded on purpose: it has no LWPOLYLINE, so every arc would have to
become a chord chain, which is exactly what this program avoids."""


def check_dxf_version(version: str) -> None:
    """Reject an unusable version before any file is written."""
    if version not in SUPPORTED_DXF_VERSIONS:
        raise ValueError(
            f"DXF version {version!r} is not supported; use one of "
            + ", ".join(SUPPORTED_DXF_VERSIONS)
            + (" (R12 has no LWPOLYLINE, so arcs could not be kept)"
               if version.upper() in ("R12", "AC1009") else "")
        )


@dataclass
class SheetGeometry:
    """Everything drawn for one sheet, bucketed by the depth it is cut to."""

    sheet: Sheet
    by_depth: dict[float, list[Region]]
    label_paths: list[tuple[Segment, ...]]
    label_depth: float


def collect_sheet_geometry(
    sheet: Sheet,
    labels: dict[str, LabelPlacement] | None = None,
    label_depth_mm: float = 1.0,
) -> SheetGeometry:
    """Transform every placed part's 2D features into sheet coordinates."""
    by_depth: dict[float, list[Region]] = {}
    paths: list[tuple[Segment, ...]] = []

    for placement in sheet.placements:
        ang, dx, dy = placement.transform()
        part = placement.part

        by_depth.setdefault(round(part.thickness, 4), []).append(
            part.profile.transformed(ang, dx, dy)
        )
        for pocket in part.pockets:
            by_depth.setdefault(round(pocket.depth, 4), []).append(
                pocket.region.transformed(ang, dx, dy)
            )

        placed = (labels or {}).get(part.id)
        if placed and placed.fitted:
            paths.extend(placed.transformed(ang, dx, dy).paths)

    return SheetGeometry(sheet, by_depth, paths, round(label_depth_mm, 4))


def _new_doc(settings: ExportSettings) -> Drawing:
    # setup=False: the standard setup adds Defpoints and a pile of text styles,
    # dimension styles and linetypes that only clutter a cut file.
    doc = ezdxf.new(settings.dxf_version, setup=False)
    # ezdxf creates Defpoints regardless of setup, and recreates it on every
    # write: it is an AutoCAD convention for non-plotting construction points
    # and only clutters a cut file.  Drop it and stop it coming back, so the
    # layer list is exactly what we drew.  Layer "0" is mandatory in every DXF
    # and has to stay, but nothing is ever drawn on it.
    if "Defpoints" in doc.layers:
        doc.layers.remove("Defpoints")
    if hasattr(doc, "_create_required_layers"):
        doc._create_required_layers = lambda: None
    doc.header["$INSUNITS"] = INSUNITS[settings.unit]
    doc.header["$MEASUREMENT"] = 0 if settings.unit == "in" else 1
    doc.header["$LUNITS"] = 2
    return doc


def _ensure_layer(doc: Drawing, name: str, colour: int) -> None:
    if name not in doc.layers:
        doc.layers.add(name, color=colour)


def _add_contour(msp, contour: Contour, layer: str, scale: float,
                 offset: tuple[float, float]) -> None:
    """Emit one closed contour, preferring CIRCLE / bulged LWPOLYLINE."""
    ox, oy = offset
    segs = contour.segments
    if len(segs) == 1 and isinstance(segs[0], Arc) and segs[0].full:
        arc = segs[0]
        msp.add_circle(((arc.center.x + ox) * scale, (arc.center.y + oy) * scale),
                       arc.radius * scale, dxfattribs={"layer": layer})
        return

    points = [
        ((seg.start.x + ox) * scale, (seg.start.y + oy) * scale, 0.0, 0.0,
         seg.bulge() if isinstance(seg, Arc) else 0.0)
        for seg in split_wide_arcs(segs)
    ]
    if points:
        msp.add_lwpolyline(points, format="xyseb", close=True, dxfattribs={"layer": layer})


def _add_open_path(msp, path: tuple[Segment, ...], layer: str, scale: float,
                   offset: tuple[float, float]) -> None:
    """Emit one open chain (a label stroke) keeping its arcs."""
    ox, oy = offset
    segs = list(path)
    if len(segs) == 1 and isinstance(segs[0], Arc) and segs[0].full:
        arc = segs[0]
        msp.add_circle(((arc.center.x + ox) * scale, (arc.center.y + oy) * scale),
                       arc.radius * scale, dxfattribs={"layer": layer})
        return

    segs = split_wide_arcs(segs)
    points = [
        ((seg.start.x + ox) * scale, (seg.start.y + oy) * scale, 0.0, 0.0,
         seg.bulge() if isinstance(seg, Arc) else 0.0)
        for seg in segs
    ]
    if not points:
        return
    end = segs[-1].end
    points.append(((end.x + ox) * scale, (end.y + oy) * scale, 0.0, 0.0, 0.0))
    msp.add_lwpolyline(points, format="xyseb", close=False, dxfattribs={"layer": layer})


def _add_region(msp, region: Region, layer: str, scale: float,
                offset: tuple[float, float]) -> None:
    _add_contour(msp, region.outer, layer, scale, offset)
    for hole in region.holes:
        _add_contour(msp, hole, layer, scale, offset)


def _add_rect(msp, x0, y0, x1, y1, layer: str, scale: float,
              offset: tuple[float, float]) -> None:
    ox, oy = offset
    msp.add_lwpolyline(
        [((x0 + ox) * scale, (y0 + oy) * scale), ((x1 + ox) * scale, (y0 + oy) * scale),
         ((x1 + ox) * scale, (y1 + oy) * scale), ((x0 + ox) * scale, (y1 + oy) * scale)],
        close=True, dxfattribs={"layer": layer},
    )


def _scale_for(settings: ExportSettings) -> float:
    return 1.0 / 25.4 if settings.unit == "in" else 1.0


def _draw_depths(doc: Drawing, by_depth: dict[float, list[Region]], through: float,
                 settings: ExportSettings, scale: float,
                 offset: tuple[float, float]) -> None:
    msp = doc.modelspace()
    for i, depth in enumerate(sorted(by_depth)):
        is_through = abs(depth - through) < 1e-6
        layer = (through_layer if is_through else pocket_layer)(depth, settings.unit)
        _ensure_layer(doc, layer, COLOUR_THROUGH if is_through
                      else DEPTH_COLOURS[i % len(DEPTH_COLOURS)])
        for region in by_depth[depth]:
            _add_region(msp, region, layer, scale, offset)


def _draw_sheet(doc: Drawing, geom: SheetGeometry, settings: ExportSettings) -> None:
    msp = doc.modelspace()
    scale = _scale_for(settings)
    sheet = geom.sheet
    offset = (0.0, 0.0)

    if settings.include_sheet_outline:
        _ensure_layer(doc, LAYER_SHEET, COLOUR_SHEET)
        _add_rect(msp, 0, 0, sheet.spec.width_mm, sheet.spec.height_mm,
                  LAYER_SHEET, scale, offset)
    if settings.include_keepout:
        _ensure_layer(doc, LAYER_KEEPOUT, COLOUR_KEEPOUT)
        _add_rect(msp, *sheet.usable, LAYER_KEEPOUT, scale, offset)

    _draw_depths(doc, geom.by_depth, round(sheet.thickness, 4), settings, scale, offset)

    if settings.include_labels and geom.label_paths:
        layer = engrave_layer(geom.label_depth, settings.unit)
        _ensure_layer(doc, layer, COLOUR_LABEL)
        for path in geom.label_paths:
            _add_open_path(msp, path, layer, scale, offset)


def _draw_part(doc: Drawing, part: Part, label: LabelPlacement | None,
               settings: ExportSettings, label_depth_mm: float) -> None:
    """One part on its own, bounding box at the origin."""
    scale = _scale_for(settings)
    by_depth: dict[float, list[Region]] = {round(part.thickness, 4): [part.profile]}
    for pocket in part.pockets:
        by_depth.setdefault(round(pocket.depth, 4), []).append(pocket.region)
    _draw_depths(doc, by_depth, round(part.thickness, 4), settings, scale, (0.0, 0.0))

    if settings.include_labels and label and label.fitted:
        layer = engrave_layer(round(label_depth_mm, 4), settings.unit)
        _ensure_layer(doc, layer, COLOUR_LABEL)
        for path in label.paths:
            _add_open_path(doc.modelspace(), path, layer, scale, (0.0, 0.0))


def export(
    result: NestResult,
    settings: ExportSettings,
    out_dir: str | Path,
    labels: dict[str, LabelPlacement] | None = None,
    label_depth_mm: float = 1.0,
    parts: list[Part] | None = None,
) -> list[Path]:
    """Write DXF files for ``result`` and return the paths written."""
    check_dxf_version(settings.dxf_version)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if settings.mode == "dxf_per_part":
        source = parts if parts is not None else [
            p.part for s in result.sheets for p in s.placements
        ]
        names = unique_filenames([p.label for p in source])
        for part, name in zip(source, names):
            doc = _new_doc(settings)
            _draw_part(doc, part, (labels or {}).get(part.id), settings, label_depth_mm)
            path = out_dir / f"{name}.dxf"
            doc.saveas(path)
            written.append(path)
        return written

    for sheet in result.sheets:
        geom = collect_sheet_geometry(sheet, labels, label_depth_mm)
        doc = _new_doc(settings)
        _draw_sheet(doc, geom, settings)
        name = safe_filename(sheet_name(sheet.index, sheet.thickness, settings.unit))
        path = out_dir / f"{name}.dxf"
        doc.saveas(path)
        written.append(path)
    return written
