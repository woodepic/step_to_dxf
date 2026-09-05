"""The engraving font must cover real part names and scale predictably."""
from __future__ import annotations

import math
import string

import pytest

from plynest.font import GLYPHS, TOFU, glyph_for, text_extents, text_paths, text_strokes
from plynest.geom2d import Arc, Point

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
    assert text_paths("", 6.0) == []


# --- the properties that stop letters looking wrong -------------------------

def test_every_stroke_is_a_continuous_chain():
    """A gap inside a stroke draws as a chord straight through the letter."""
    broken = []
    for ch, glyph in list(GLYPHS.items()) + [("TOFU", TOFU)]:
        for i, stroke in enumerate(glyph.strokes):
            for a, b in zip(stroke, stroke[1:]):
                gap = math.dist(a.end(), b.start())
                if gap > 1e-9:
                    broken.append((ch, i, round(gap, 6)))
    assert broken == []


def test_curves_are_emitted_as_arcs_not_sampled_points():
    for ch in "COQSGB038e":
        paths = text_paths(ch, 6.0)
        arcs = [s for path in paths for s in path if isinstance(s, Arc)]
        assert arcs, f"{ch!r} should carry real arcs"


def test_arc_radii_scale_with_the_text():
    small = [s.radius for p in text_paths("O", 4.0) for s in p if isinstance(s, Arc)]
    big = [s.radius for p in text_paths("O", 8.0) for s in p if isinstance(s, Arc)]
    assert small and len(small) == len(big)
    for a, b in zip(small, big):
        assert b == pytest.approx(a * 2.0, rel=1e-12)


def test_rendered_paths_are_continuous_too():
    for path in text_paths("AC1/DA1/LEFT SIDE", 6.0, uppercase=True):
        for a, b in zip(path, path[1:]):
            assert a.end.dist(b.start) < 1e-9


def test_curves_are_sampled_finely_enough_to_look_smooth():
    """Faceting on a curve is the thing that made the old font look wobbly.

    Only arcs are checked: a straight segment is legitimately one long chord
    (N's diagonal is longer than the cap height).
    """
    tol = 0.05
    worst = 0.0
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
        for path in text_paths(ch, 10.0):
            for seg in path:
                if not isinstance(seg, Arc):
                    continue
                pts = seg.sample(tol)
                for a, b in zip(pts, pts[1:]):
                    mid = Point((a.x + b.x) / 2, (a.y + b.y) / 2)
                    # How far the chord's midpoint falls inside the true arc.
                    worst = max(worst, seg.radius - seg.center.dist(mid))
    assert worst <= tol * 1.05, f"curves deviate by {worst:.3f}, above the {tol} tolerance"


def test_glyphs_stay_inside_their_advance_width():
    for ch, glyph in GLYPHS.items():
        if ch == " ":
            continue
        xs = [v for stroke in glyph.strokes for seg in stroke
              for v in (seg.start()[0], seg.end()[0])]
        if not xs:
            continue
        assert min(xs) >= -0.75, f"{ch!r} starts left of its origin"
        assert max(xs) <= glyph.advance + 1.2, f"{ch!r} overruns its advance"
