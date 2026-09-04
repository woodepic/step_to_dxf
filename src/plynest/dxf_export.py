"""Write nested sheets out as DXF.

Closed profiles become single closed LWPOLYLINEs carrying bulge factors, so an
arc stays an arc all the way into CAM rather than arriving as a hundred tiny
chords.  Geometry is nominal: kerf was handled as spacing during nesting, so the
outlines here are true part size and the CAM applies the tool offset.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import ezdxf
from ezdxf.document import Drawing

from .config import ExportSettings
from .geom2d import Arc, Contour, Line, Point, Region
from .labels import LabelPlacement
from .nest import NestResult, Placement, Sheet
from .units import INSUNITS, from_mm

# ACI colour indices, cycled per depth so layers are distinguishable on screen.
DEPTH_COLOURS = [3, 4, 6, 2, 5, 30, 40, 50, 211, 141]
COLOUR_THROUGH = 1
COLOUR_LABEL = 7
COLOUR_SHEET = 8
COLOUR_KEEPOUT = 9

LAYER_SHEET = "SHEET_OUTLINE"
LAYER_KEEPOUT = "EDGE_KEEPOUT"


def _fmt_depth(depth_mm: float, unit: str) -> str:
    v = from_mm(depth_mm, unit)
    text = f"{v:.4f}".rstrip("0").rstrip(".") if unit == "in" else f"{v:.2f}".rstrip("0").rstrip(".")
    return text.replace(".", "p").replace("-", "n")


def through_layer(depth_mm: float, unit: str) -> str:
    return f"CUT_THROUGH_{_fmt_depth(depth_mm, unit)}"


def pocket_layer(depth_mm: float, unit: str) -> str:
    return f"POCKET_{_fmt_depth(depth_mm, unit)}"


def engrave_layer(depth_mm: float, unit: str) -> str:
    return f"ENGRAVE_{_fmt_depth(depth_mm, unit)}"


@dataclass
class SheetGeometry:
    """Everything drawn for one sheet, bucketed by the depth it is cut to."""

    sheet: Sheet
    by_depth: dict[float, list[Region]]
    labels: list[tuple[float, list[list[Point]]]]

    def depths(self) -> list[float]:
        return sorted(self.by_depth)


def collect_sheet_geometry(
    sheet: Sheet,
    labels: dict[str, LabelPlacement] | None = None,
    label_depth_mm: float = 1.0,
) -> SheetGeometry:
    """Transform every placed part's 2D features into sheet coordinates."""
    by_depth: dict[float, list[Region]] = {}
    label_strokes: list[list[Point]] = []

    for placement in sheet.placements:
        ang, dx, dy = placement.transform()
        part = placement.part

        cut = round(part.thickness, 4)
        by_depth.setdefault(cut, []).append(part.profile.transformed(ang, dx, dy))

        for pocket in part.pockets:
            d = round(pocket.depth, 4)
            by_depth.setdefault(d, []).append(pocket.region.transformed(ang, dx, dy))

        placement_label = (labels or {}).get(part.id)
        if placement_label and placement_label.fitted:
            cos_a, sin_a = math.cos(ang), math.sin(ang)
            for stroke in placement_label.strokes:
                label_strokes.append([
                    Point(p.x * cos_a - p.y * sin_a + dx, p.x * sin_a + p.y * cos_a + dy)
                    for p in stroke
                ])

    labels_out = [(round(label_depth_mm, 4), label_strokes)] if label_strokes else []
    return SheetGeometry(sheet=sheet, by_depth=by_depth, labels=labels_out)


def _new_doc(settings: ExportSettings) -> Drawing:
    doc = ezdxf.new(settings.dxf_version, setup=True)
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
        msp.add_circle(
            ((arc.center.x + ox) * scale, (arc.center.y + oy) * scale),
            arc.radius * scale,
            dxfattribs={"layer": layer},
        )
        return

    points: list[tuple[float, float, float, float, float]] = []
    for seg in segs:
        bulge = seg.bulge() if isinstance(seg, Arc) else 0.0
        p = seg.start
        points.append(((p.x + ox) * scale, (p.y + oy) * scale, 0.0, 0.0, bulge))
    if not points:
        return
    msp.add_lwpolyline(points, format="xyseb", close=True, dxfattribs={"layer": layer})


def _add_region(msp, region: Region, layer: str, scale: float,
                offset: tuple[float, float]) -> None:
    _add_contour(msp, region.outer, layer, scale, offset)
    for hole in region.holes:
        _add_contour(msp, hole, layer, scale, offset)


def _add_rect(msp, x0: float, y0: float, x1: float, y1: float, layer: str,
              scale: float, offset: tuple[float, float]) -> None:
    ox, oy = offset
    pts = [
        ((x0 + ox) * scale, (y0 + oy) * scale),
        ((x1 + ox) * scale, (y0 + oy) * scale),
        ((x1 + ox) * scale, (y1 + oy) * scale),
        ((x0 + ox) * scale, (y1 + oy) * scale),
    ]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})


def _draw_sheet(doc: Drawing, geom: SheetGeometry, settings: ExportSettings,
                offset: tuple[float, float] = (0.0, 0.0),
                only_depth: float | None = None) -> None:
    msp = doc.modelspace()
    scale = 1.0 / 25.4 if settings.unit == "in" else 1.0
    sheet = geom.sheet
    unit = settings.unit

    if only_depth is None:
        if settings.include_sheet_outline:
            _ensure_layer(doc, LAYER_SHEET, COLOUR_SHEET)
            _add_rect(msp, 0, 0, sheet.spec.width_mm, sheet.spec.height_mm,
                      LAYER_SHEET, scale, offset)
        if settings.include_keepout:
            _ensure_layer(doc, LAYER_KEEPOUT, COLOUR_KEEPOUT)
            x0, y0, x1, y1 = sheet.usable
            _add_rect(msp, x0, y0, x1, y1, LAYER_KEEPOUT, scale, offset)

    cut_depth = round(sheet.thickness, 4)
    for i, depth in enumerate(geom.depths()):
        if only_depth is not None and abs(depth - only_depth) > 1e-6:
            continue
        is_through = abs(depth - cut_depth) < 1e-6
        layer = through_layer(depth, unit) if is_through else pocket_layer(depth, unit)
        colour = COLOUR_THROUGH if is_through else DEPTH_COLOURS[i % len(DEPTH_COLOURS)]
        _ensure_layer(doc, layer, colour)
        for region in geom.by_depth[depth]:
            _add_region(msp, region, layer, scale, offset)

    if settings.include_labels:
        for depth, strokes in geom.labels:
            if only_depth is not None and abs(depth - only_depth) > 1e-6:
                continue
            layer = engrave_layer(depth, unit)
            _ensure_layer(doc, layer, COLOUR_LABEL)
            ox, oy = offset
            for stroke in strokes:
                if len(stroke) < 2:
                    continue
                msp.add_lwpolyline(
                    [((p.x + ox) * scale, (p.y + oy) * scale) for p in stroke],
                    close=False,
                    dxfattribs={"layer": layer},
                )


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "sheet"


def export(
    result: NestResult,
    settings: ExportSettings,
    out_dir: str | Path,
    labels: dict[str, LabelPlacement] | None = None,
    label_depth_mm: float = 1.0,
    job_name: str = "layout",
) -> list[Path]:
    """Write DXF files for ``result`` and return the paths written."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    geoms = [collect_sheet_geometry(s, labels, label_depth_mm) for s in result.sheets]
    stem = safe_name(job_name)

    if settings.mode == "single_file":
        doc = _new_doc(settings)
        gap = 100.0
        x = 0.0
        for geom in geoms:
            _draw_sheet(doc, geom, settings, offset=(x, 0.0))
            x += geom.sheet.spec.width_mm + gap
        path = out_dir / f"{stem}_all_sheets.dxf"
        doc.saveas(path)
        written.append(path)
        return written

    for geom in geoms:
        sheet = geom.sheet
        thick = _fmt_depth(sheet.thickness, settings.unit)
        base = f"{stem}_sheet{sheet.index + 1:02d}_t{thick}"
        if settings.mode == "per_depth":
            depths = list(geom.depths())
            if settings.include_labels and geom.labels:
                depths += [d for d, _ in geom.labels if d not in depths]
            for depth in sorted(set(depths)):
                doc = _new_doc(settings)
                _draw_sheet(doc, geom, settings, only_depth=depth)
                if not len(doc.modelspace()):
                    continue
                path = out_dir / f"{base}_d{_fmt_depth(depth, settings.unit)}.dxf"
                doc.saveas(path)
                written.append(path)
        else:
            doc = _new_doc(settings)
            _draw_sheet(doc, geom, settings)
            path = out_dir / f"{base}.dxf"
            doc.saveas(path)
            written.append(path)

    return written
