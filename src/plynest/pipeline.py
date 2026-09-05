"""End-to-end: STEP file in, nested sheets and DXF out."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import RunSettings
from .labels import LabelPlacement, place_label
from .nest import NestResult, nest
from .orient import analyse
from .part import Part
from .step_loader import LoadedSolid, label_for, load_step

Progress = Callable[[str, float], None]


@dataclass
class Job:
    """The result of analysing and nesting one STEP file."""

    parts: list[Part]
    result: NestResult
    labels: dict[str, LabelPlacement]
    skipped: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_name: str = ""

    sources: dict[int, LoadedSolid] = field(default_factory=dict)
    """The original solids, kept so a STEP export can re-pose the real geometry."""

    def summary(self) -> dict:
        thick = Counter(round(p.thickness, 2) for p in self.parts)
        return {
            "source": self.source_name,
            "parts": len(self.parts),
            "skipped": len(self.skipped),
            "sheets": self.result.sheet_count(),
            "utilisation": self.result.total_utilisation(),
            "thicknesses": dict(sorted(thick.items(), reverse=True)),
            "unplaced": len(self.result.unplaced),
            "warnings": len(self.warnings),
        }


def unique_labels(solids: list[LoadedSolid], style: str) -> dict[int, str]:
    """Label every solid, appending an index only where names actually collide."""
    base = {s.index: label_for(s, style=style) for s in solids}
    counts = Counter(base.values())
    seen: Counter[str] = Counter()
    out: dict[int, str] = {}
    for s in solids:
        text = base[s.index]
        if counts[text] > 1:
            seen[text] += 1
            text = f"{text} {seen[text]}"
        out[s.index] = text
    return out


def analyse_parts(solids: list[LoadedSolid], settings: RunSettings,
                  progress: Progress | None = None) -> tuple[list[Part], list[tuple[str, str]], list[str]]:
    names = unique_labels(solids, settings.labels.style)
    parts: list[Part] = []
    skipped: list[tuple[str, str]] = []
    warnings: list[str] = []
    total = max(1, len(solids))
    for i, solid in enumerate(solids):
        analysis = analyse(solid, names[solid.index], part_id=f"p{solid.index:04d}")
        if analysis.ok and analysis.part is not None:
            parts.append(analysis.part)
            for message in analysis.part.warnings:
                warnings.append(f"{analysis.part.label}: {message}")
        else:
            skipped.append((solid.path_str, "; ".join(analysis.messages)))
        if progress and i % 10 == 0:
            progress("Analysing parts", 0.05 + 0.35 * (i / total))
    return parts, skipped, warnings


def run(step_path: str | Path, settings: RunSettings,
        progress: Progress | None = None) -> Job:
    """Load, orient, label and nest a STEP assembly."""
    step_path = Path(step_path)
    if progress:
        progress("Reading STEP file", 0.02)
    solids = load_step(step_path)

    parts, skipped, warnings = analyse_parts(solids, settings, progress)

    if progress:
        progress("Placing labels", 0.42)
    labels: dict[str, LabelPlacement] = {}
    if settings.labels.enabled:
        for part in parts:
            placement = place_label(part, part.label, settings.labels)
            if placement is None:
                continue
            labels[part.id] = placement
            if placement.message:
                warnings.append(f"{part.label}: {placement.message}")

    if progress:
        progress("Nesting sheets", 0.5)
    result = nest(parts, settings.nest)
    if progress:
        progress("Done", 1.0)

    for part, reason in result.unplaced:
        warnings.append(f"{part.label}: NOT PLACED - {reason}")

    return Job(
        parts=parts,
        result=result,
        labels=labels,
        skipped=skipped,
        warnings=warnings,
        source_name=step_path.name,
        sources={s.index: s for s in solids},
    )
