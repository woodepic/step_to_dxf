"""User-facing settings for a nesting run."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Literal

from .units import MM_PER_INCH, to_mm

RotationMode = Literal["none", "180", "90", "free"]
DxfMode = Literal["per_sheet", "per_depth", "single_file"]
LabelStyle = Literal["abbrev_path", "full_path", "parent_name", "name", "name_index"]

ROTATION_ANGLES: dict[str, tuple[float, ...]] = {
    "none": (0.0,),
    "180": (0.0, 180.0),
    "90": (0.0, 90.0, 180.0, 270.0),
    "free": (0.0, 90.0, 180.0, 270.0, 45.0, 135.0, 225.0, 315.0),
}


@dataclass
class SheetSpec:
    """A stock sheet.  Defaults to a 4x8 ft panel."""

    width_mm: float = 48.0 * MM_PER_INCH   # 1219.2
    height_mm: float = 96.0 * MM_PER_INCH  # 2438.4

    @staticmethod
    def from_units(width: float, height: float, unit: str) -> "SheetSpec":
        return SheetSpec(to_mm(width, unit), to_mm(height, unit))


@dataclass
class LabelSettings:
    enabled: bool = True
    style: LabelStyle = "abbrev_path"
    height_mm: float = 6.0
    """Cap height of the engraved text."""

    depth_mm: float = 1.0
    """How deep to engrave; emitted as its own depth layer."""

    corner: Literal["bottom_right", "bottom_left", "top_right", "top_left", "center"] = (
        "bottom_right"
    )
    margin_mm: float = 6.0
    """Inset from the part edge before text is placed."""

    clearance_mm: float = 1.5
    """Keep-clear band between text and any pocket or hole."""

    uppercase: bool = True
    allow_rotate: bool = True
    """Let the label turn 90 deg if it will not fit horizontally."""

    stroke_font: str = "single_stroke"


@dataclass
class NestSettings:
    kerf_mm: float = 6.35
    """Clearance guaranteed between neighbouring part outlines (tool diameter)."""

    edge_keepout_mm: float = 25.4
    """Unusable border of the sheet, for hold-down bolts and clamps."""

    rotation: RotationMode = "90"
    sheet: SheetSpec = field(default_factory=SheetSpec)
    attempts: int = 6
    """Distinct part orderings tried; the best result wins."""

    seed: int = 12345


@dataclass
class ExportSettings:
    unit: Literal["mm", "in"] = "in"
    mode: DxfMode = "per_sheet"
    include_labels: bool = True
    include_sheet_outline: bool = True
    include_keepout: bool = True
    dxf_version: str = "R2010"


@dataclass
class RunSettings:
    nest: NestSettings = field(default_factory=NestSettings)
    labels: LabelSettings = field(default_factory=LabelSettings)
    export: ExportSettings = field(default_factory=ExportSettings)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "RunSettings":
        def build(cls, payload):
            if not isinstance(payload, dict):
                return cls()
            names = {f.name: f for f in fields(cls)}
            kwargs = {}
            for key, value in payload.items():
                if key not in names:
                    continue
                if key == "sheet":
                    kwargs[key] = build(SheetSpec, value)
                else:
                    kwargs[key] = value
            return cls(**kwargs)

        return RunSettings(
            nest=build(NestSettings, data.get("nest", {})),
            labels=build(LabelSettings, data.get("labels", {})),
            export=build(ExportSettings, data.get("export", {})),
        )
