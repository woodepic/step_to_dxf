"""Unit handling.  Internally everything is millimetres; only export converts."""
from __future__ import annotations

MM_PER_INCH = 25.4

# DXF $INSUNITS codes.
INSUNITS = {"mm": 4, "in": 1}


def to_mm(value: float, unit: str) -> float:
    return value * MM_PER_INCH if unit == "in" else value


def from_mm(value_mm: float, unit: str) -> float:
    return value_mm / MM_PER_INCH if unit == "in" else value_mm


def format_length(value_mm: float, unit: str) -> str:
    """Human-readable length used in layer names and the UI."""
    v = from_mm(value_mm, unit)
    if unit == "in":
        return f"{v:.4f}".rstrip("0").rstrip(".") + "in"
    return f"{v:.2f}".rstrip("0").rstrip(".") + "mm"
