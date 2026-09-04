"""The engraving font must cover real part names and scale predictably."""
from __future__ import annotations

import math
import string

import pytest

from plynest.font import TOFU, glyph_for, text_extents, text_strokes

PRINTABLE = string.ascii_letters + string.digits + " /\\-_.,:;()[]<>#+=*'\"!?&@%"


def test_every_printable_character_has_a_glyph():
    missing = [c for c in PRINTABLE if glyph_for(c) is TOFU]
    assert missing == []


def test_unknown_character_falls_back_visibly():
    assert glyph_for("☃") is TOFU, "an unmapped glyph must be obvious, not absent"


def test_strokes_are_open_polylines_with_at_least_two_points():
    strokes, _, _ = text_strokes("AC4/DA2/Floor", 6.0)
    assert strokes
    assert all(len(s) >= 2 for s in strokes)
    assert all(math.isfinite(v) for s in strokes for p in s for v in p)


def test_width_scales_linearly_with_height():
    w1, _, _ = text_extents("PEDESTAL LEFT", 4.0)
    w2, _, _ = text_extents("PEDESTAL LEFT", 8.0)
    assert w2 == pytest.approx(w1 * 2.0, rel=1e-12)


def test_cap_height_is_honoured():
    _, ascent, _ = text_extents("ABC", 6.0)
    assert ascent == pytest.approx(6.0, rel=1e-9)


def test_strokes_stay_within_the_reported_extents():
    text = "Right Wall #12"
    height = 5.0
    w, ascent, descent = text_extents(text, height)
    strokes, _, _ = text_strokes(text, height)
    xs = [p[0] for s in strokes for p in s]
    ys = [p[1] for s in strokes for p in s]
    assert min(xs) >= -1e-9 and max(xs) <= w + 1e-9
    assert max(ys) <= ascent + 1e-9 and min(ys) >= -descent - 1e-9


def test_uppercase_option_changes_the_layout():
    lower = text_extents("Floor", 6.0)[0]
    upper = text_extents("Floor", 6.0, uppercase=True)[0]
    assert upper != lower
    assert upper == text_extents("FLOOR", 6.0)[0]


def test_empty_text_is_harmless():
    strokes, width, _ = text_strokes("", 6.0)
    assert strokes == [] and width == 0.0
