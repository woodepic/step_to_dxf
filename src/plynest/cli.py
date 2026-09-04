"""Command line front end: ``python -m plynest.cli layout.step -o out/``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import (
    ExportSettings,
    LabelSettings,
    NestSettings,
    RunSettings,
    SheetSpec,
)
from .dxf_export import export
from .pipeline import run
from .units import from_mm, to_mm


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="plynest",
        description="Nest a STEP plywood assembly onto sheets and write CNC-ready DXF.",
    )
    p.add_argument("step", help="input STEP file")
    p.add_argument("-o", "--out", default="out", help="output directory (default: out)")
    p.add_argument("--unit", choices=["in", "mm"], default="in",
                   help="units for the DXF and for the options below (default: in)")
    p.add_argument("--sheet-width", type=float, default=48.0)
    p.add_argument("--sheet-height", type=float, default=96.0)
    p.add_argument("--kerf", type=float, default=0.25,
                   help="clearance between neighbouring parts (default: 0.25 in)")
    p.add_argument("--edge-keepout", type=float, default=1.0,
                   help="uncuttable border for hold-downs (default: 1.0 in)")
    p.add_argument("--rotation", choices=["none", "180", "90", "free"], default="90")
    p.add_argument("--attempts", type=int, default=6)
    p.add_argument("--mode", choices=["per_sheet", "per_depth", "single_file"],
                   default="per_sheet", help="one DXF per sheet, per sheet+depth, or one file")
    p.add_argument("--no-labels", action="store_true", help="do not engrave part names")
    p.add_argument("--label-height", type=float, default=0.25,
                   help="engraved cap height (default: 0.25 in)")
    p.add_argument("--label-depth", type=float, default=0.04,
                   help="engraving depth (default: 0.04 in)")
    p.add_argument("--label-corner",
                   choices=["bottom_right", "bottom_left", "top_right", "top_left", "center"],
                   default="bottom_right")
    p.add_argument("--label-style",
                   choices=["abbrev_path", "full_path", "parent_name", "name", "name_index"],
                   default="abbrev_path")
    p.add_argument("--quiet", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    unit = args.unit

    settings = RunSettings(
        nest=NestSettings(
            kerf_mm=to_mm(args.kerf, unit),
            edge_keepout_mm=to_mm(args.edge_keepout, unit),
            rotation=args.rotation,
            sheet=SheetSpec.from_units(args.sheet_width, args.sheet_height, unit),
            attempts=args.attempts,
        ),
        labels=LabelSettings(
            enabled=not args.no_labels,
            style=args.label_style,
            height_mm=to_mm(args.label_height, unit),
            depth_mm=to_mm(args.label_depth, unit),
            corner=args.label_corner,
        ),
        export=ExportSettings(unit=unit, mode=args.mode, include_labels=not args.no_labels),
    )

    def progress(stage: str, frac: float) -> None:
        if not args.quiet:
            print(f"  [{frac * 100:5.1f}%] {stage}", file=sys.stderr)

    job = run(args.step, settings, progress)
    paths = export(
        job.result,
        settings.export,
        args.out,
        labels=job.labels,
        label_depth_mm=settings.labels.depth_mm,
        job_name=Path(args.step).stem,
    )

    s = job.summary()
    print(f"\n{s['source']}: {s['parts']} parts on {s['sheets']} sheets "
          f"({s['utilisation'] * 100:.1f}% material utilisation)")
    for thickness, count in s["thicknesses"].items():
        print(f"  {from_mm(thickness, unit):.4g} {unit} stock: {count} parts")
    if job.skipped:
        print(f"\n{len(job.skipped)} solid(s) skipped:")
        for path, why in job.skipped:
            print(f"  {path}: {why}")
    if job.warnings:
        print(f"\n{len(job.warnings)} warning(s):")
        for w in job.warnings[:20]:
            print(f"  {w}")
        if len(job.warnings) > 20:
            print(f"  ... and {len(job.warnings) - 20} more")
    print(f"\nWrote {len(paths)} DXF file(s) to {Path(args.out).resolve()}")
    return 1 if job.result.unplaced else 0


if __name__ == "__main__":
    raise SystemExit(main())
