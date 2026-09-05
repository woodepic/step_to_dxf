"""Human-readable, filesystem-safe names for exported files and DXF layers.

Sheets are named the way you would say them out loud -- "Sheet 3, 0.5 in" --
and layers say how deep to cut, measured down from the part's top face.
"""
from __future__ import annotations

import re

from .units import from_mm

# Characters AutoCAD rejects in a layer name, plus path separators.
_LAYER_BAD = re.compile(r'[<>/\\":;?*|=\']')
_FILE_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Windows refuses these as filenames whatever the extension, so "CON.dxf"
# simply cannot be written on a machine the operator may well be using.
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{stem}{i}" for stem in ("COM", "LPT") for i in range(0, 10)
}

MAX_STEM_BYTES = 180
"""Filename budget, leaving room for an extension and a collision suffix."""


def _truncate(text: str, limit: int) -> str:
    """Cut to ``limit`` UTF-8 bytes without splitting a character."""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore")


def format_thickness(value_mm: float, unit: str) -> str:
    """``19.05`` mm -> ``"0.75 in"`` or ``"19.05 mm"``."""
    v = from_mm(value_mm, unit)
    text = f"{v:.4f}" if unit == "in" else f"{v:.2f}"
    text = text.rstrip("0").rstrip(".") or "0"
    return f"{text} {unit}"


def sheet_name(index: int, thickness_mm: float, unit: str) -> str:
    """``"Sheet 3, 0.5 in"`` -- 1-based, matching how you would count them."""
    return f"Sheet {index + 1}, {format_thickness(thickness_mm, unit)}"


def safe_filename(text: str, fallback: str = "part") -> str:
    """Make ``text`` usable as a filename while staying readable.

    Path separators become hyphens rather than underscores, so ``AC4/DA2/Floor``
    reads as ``AC4-DA2-Floor``.
    """
    text = text.replace("/", "-").replace("\\", "-")
    text = _FILE_BAD.sub("-", text)
    text = re.sub(r"\s+", " ", text).strip(" .-")
    text = _truncate(text, MAX_STEM_BYTES)
    # Windows silently drops a trailing dot or space, which would quietly merge
    # two different parts into one file.
    text = text.rstrip(" .")
    if not text:
        return fallback
    if text.split(".")[0].upper() in _RESERVED:
        text = f"{text}_"
    return text


def unique_filenames(names: list[str]) -> list[str]:
    """Disambiguate names that collide once made filesystem-safe."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for name in names:
        safe = safe_filename(name)
        key = safe.lower()
        if key in seen:
            seen[key] += 1
            safe = f"{safe} ({seen[key]})"
        else:
            seen[key] = 1
        out.append(safe)
    return out


def _layer(text: str) -> str:
    return _LAYER_BAD.sub("-", text)[:250]


def through_layer(depth_mm: float, unit: str) -> str:
    """Layer for the full-depth cut, e.g. ``CUT THROUGH 0.75 in deep``."""
    return _layer(f"CUT THROUGH {format_thickness(depth_mm, unit)} deep")


def pocket_layer(depth_mm: float, unit: str) -> str:
    """Layer for a pocket floor, depth measured down from the top face."""
    return _layer(f"POCKET {format_thickness(depth_mm, unit)} deep")


def engrave_layer(depth_mm: float, unit: str) -> str:
    return _layer(f"ENGRAVE {format_thickness(depth_mm, unit)} deep")
