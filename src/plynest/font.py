"""A built-in single-stroke (engraving) vector font.

Outline fonts force a router to either V-carve or pocket the counters of every
letter; a single-stroke font is one pass of the bit down the centre of each
line, which is what you want for a 6 mm part label.  Nothing suitable ships
with ezdxf, so the glyphs live here.

Design grid: baseline y=0, cap height y=CAP, descenders to -3.  Glyph
coordinates are scaled by (height / CAP) at render time.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

CAP = 10.0
X_HEIGHT = 6.6
DESCENDER = -3.0
LETTER_SPACING = 1.9
WORD_SPACING = 4.2
LINE_SPACING = 1.55  # multiples of cap height

Stroke = tuple[tuple[float, float], ...]


def _ell(cx: float, cy: float, rx: float, ry: float, a0: float, a1: float,
         steps: int | None = None) -> list[tuple[float, float]]:
    """Sample an ellipse arc from a0 to a1 (degrees, CCW when a1 > a0)."""
    if steps is None:
        steps = max(3, int(abs(a1 - a0) / 18.0) + 2)
    out = []
    for i in range(steps + 1):
        a = math.radians(a0 + (a1 - a0) * i / steps)
        out.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
    return out


def _cat(*chunks) -> Stroke:
    """Concatenate point lists, dropping duplicated joins."""
    pts: list[tuple[float, float]] = []
    for chunk in chunks:
        for p in chunk:
            if pts and abs(pts[-1][0] - p[0]) < 1e-9 and abs(pts[-1][1] - p[1]) < 1e-9:
                continue
            pts.append(p)
    return tuple(pts)


@dataclass(frozen=True)
class Glyph:
    advance: float
    strokes: tuple[Stroke, ...]


def _g(advance: float, *strokes) -> Glyph:
    return Glyph(advance, tuple(tuple(s) for s in strokes))


# --- uppercase -------------------------------------------------------------
_UPPER: dict[str, Glyph] = {
    "A": _g(6.4, [(0, 0), (3.2, CAP), (6.4, 0)], [(1.15, 3.6), (5.25, 3.6)]),
    "B": _g(6.2,
            [(0, 0), (0, CAP)],
            _cat([(0, CAP), (3.2, CAP)], _ell(3.2, 7.5, 2.7, 2.5, 90, -90), [(3.2, 5), (0, 5)]),
            _cat([(0, 5), (3.4, 5)], _ell(3.4, 2.5, 2.8, 2.5, 90, -90), [(3.4, 0), (0, 0)])),
    "C": _g(6.2, _ell(3.1, 5, 3.1, 5, 48, 312)),
    "D": _g(6.4,
            _cat([(0, 0), (0, CAP), (2.4, CAP)], _ell(2.4, 5, 4.0, 5, 90, -90),
                 [(2.4, 0), (0, 0)])),
    "E": _g(5.6, [(5.6, CAP), (0, CAP), (0, 0), (5.6, 0)], [(0, 5), (4.4, 5)]),
    "F": _g(5.4, [(5.4, CAP), (0, CAP), (0, 0)], [(0, 5), (4.3, 5)]),
    "G": _g(6.6,
            _cat(_ell(3.2, 5, 3.2, 5, 40, 330), [(5.65, 2.5), (6.6, 2.5), (6.6, 4.6)]),
            [(6.6, 4.6), (3.9, 4.6)]),
    "H": _g(6.4, [(0, 0), (0, CAP)], [(6.4, 0), (6.4, CAP)], [(0, 5), (6.4, 5)]),
    "I": _g(1.0, [(0.5, 0), (0.5, CAP)]),
    "J": _g(5.4, _cat([(5.0, CAP), (5.0, 2.6)], _ell(2.6, 2.6, 2.4, 2.6, 0, -180))),
    "K": _g(6.2, [(0, 0), (0, CAP)], [(6.0, CAP), (0.2, 4.1)], [(2.2, 5.6), (6.2, 0)]),
    "L": _g(5.2, [(0, CAP), (0, 0), (5.2, 0)]),
    "M": _g(7.6, [(0, 0), (0, CAP), (3.8, 3.4), (7.6, CAP), (7.6, 0)]),
    "N": _g(6.6, [(0, 0), (0, CAP), (6.6, 0), (6.6, CAP)]),
    "O": _g(6.8, _cat(_ell(3.4, 5, 3.4, 5, 0, 360))),
    "P": _g(6.0,
            [(0, 0), (0, CAP)],
            _cat([(0, CAP), (3.2, CAP)], _ell(3.2, 7.3, 2.8, 2.7, 90, -90), [(3.2, 4.6), (0, 4.6)])),
    "Q": _g(6.8, _cat(_ell(3.4, 5, 3.4, 5, 0, 360)), [(4.3, 2.6), (6.9, -0.6)]),
    "R": _g(6.2,
            [(0, 0), (0, CAP)],
            _cat([(0, CAP), (3.2, CAP)], _ell(3.2, 7.3, 2.8, 2.7, 90, -90), [(3.2, 4.6), (0, 4.6)]),
            [(3.0, 4.6), (6.2, 0)]),
    "S": _g(6.0,
            _cat(_ell(3.0, 7.4, 3.0, 2.6, 20, 200),
                 _ell(3.0, 2.7, 3.0, 2.7, 100, -70))),
    "T": _g(6.0, [(0, CAP), (6.0, CAP)], [(3.0, CAP), (3.0, 0)]),
    "U": _g(6.4, _cat([(0, CAP), (0, 3.0)], _ell(3.2, 3.0, 3.2, 3.0, 180, 360), [(6.4, CAP)])),
    "V": _g(6.4, [(0, CAP), (3.2, 0), (6.4, CAP)]),
    "W": _g(9.2, [(0, CAP), (2.3, 0), (4.6, 6.6), (6.9, 0), (9.2, CAP)]),
    "X": _g(6.2, [(0, 0), (6.2, CAP)], [(0, CAP), (6.2, 0)]),
    "Y": _g(6.2, [(0, CAP), (3.1, 4.8), (6.2, CAP)], [(3.1, 4.8), (3.1, 0)]),
    "Z": _g(6.0, [(0, CAP), (6.0, CAP), (0, 0), (6.0, 0)]),
}

# --- lowercase -------------------------------------------------------------
_XH = X_HEIGHT
_LOWER: dict[str, Glyph] = {
    "a": _g(5.6,
            _cat(_ell(2.8, 3.3, 2.8, 3.3, 60, 300)),
            [(5.6, _XH - 0.6), (5.6, 0)]),
    "b": _g(5.6, [(0, CAP), (0, 0)], _cat(_ell(2.8, 3.3, 2.8, 3.3, 180, -120))),
    "c": _g(5.4, _cat(_ell(2.7, 3.3, 2.7, 3.3, 55, 305))),
    "d": _g(5.6, [(5.6, CAP), (5.6, 0)], _cat(_ell(2.8, 3.3, 2.8, 3.3, 0, 360))[:0]
            or _cat(_ell(2.8, 3.3, 2.8, 3.3, 0, 300))),
    "e": _g(5.4, _cat([(0.0, 3.3), (5.4, 3.3)], _ell(2.7, 3.3, 2.7, 3.3, 0, 290))),
    "f": _g(3.6, _cat([(3.6, CAP - 0.6)], _ell(2.0, CAP - 2.2, 1.6, 1.6, 90, 180), [(0.4, 0)]),
            [(0.0, _XH), (3.4, _XH)]),
    "g": _g(5.6, _cat(_ell(2.8, 3.3, 2.8, 3.3, 0, 360)),
            _cat([(5.6, _XH)], [(5.6, -0.6)], _ell(2.8, -0.6, 2.8, 2.4, 0, -180))),
    "h": _g(5.4, [(0, CAP), (0, 0)],
            _cat([(0, 4.0)], _ell(2.7, 3.9, 2.7, 2.7, 180, 0), [(5.4, 0)])),
    "i": _g(1.0, [(0.5, _XH), (0.5, 0)], [(0.5, CAP - 0.6), (0.5, CAP)]),
    "j": _g(2.6, _cat([(2.2, _XH)], [(2.2, -0.4)], _ell(1.0, -0.4, 1.2, 2.2, 0, -180)),
            [(2.2, CAP - 0.6), (2.2, CAP)]),
    "k": _g(5.2, [(0, CAP), (0, 0)], [(4.8, _XH), (0.2, 2.4)], [(1.8, 3.6), (5.2, 0)]),
    "l": _g(1.0, [(0.5, CAP), (0.5, 0)]),
    "m": _g(8.6, [(0, _XH), (0, 0)],
            _cat([(0, 4.4)], _ell(2.15, 4.3, 2.15, 2.3, 180, 0), [(4.3, 0)]),
            _cat([(4.3, 4.4)], _ell(6.45, 4.3, 2.15, 2.3, 180, 0), [(8.6, 0)])),
    "n": _g(5.4, [(0, _XH), (0, 0)],
            _cat([(0, 4.0)], _ell(2.7, 3.9, 2.7, 2.7, 180, 0), [(5.4, 0)])),
    "o": _g(5.6, _cat(_ell(2.8, 3.3, 2.8, 3.3, 0, 360))),
    "p": _g(5.6, [(0, DESCENDER), (0, _XH)], _cat(_ell(2.8, 3.3, 2.8, 3.3, 180, -120))),
    "q": _g(5.6, [(5.6, DESCENDER), (5.6, _XH)], _cat(_ell(2.8, 3.3, 2.8, 3.3, 0, 300))),
    "r": _g(4.0, [(0, _XH), (0, 0)], _cat([(0, 3.9)], _ell(2.4, 3.8, 2.4, 2.6, 180, 60))),
    "s": _g(4.8,
            _cat(_ell(2.4, 5.0, 2.4, 1.7, 20, 200), _ell(2.4, 1.7, 2.4, 1.7, 100, -70))),
    "t": _g(3.4, [(1.2, CAP), (1.2, 1.4), (2.6, 0.1)], [(0, _XH), (3.4, _XH)]),
    "u": _g(5.4, _cat([(0, _XH), (0, 2.6)], _ell(2.7, 2.6, 2.7, 2.6, 180, 360), [(5.4, _XH)]),
            [(5.4, 2.6), (5.4, 0)]),
    "v": _g(5.2, [(0, _XH), (2.6, 0), (5.2, _XH)]),
    "w": _g(7.8, [(0, _XH), (1.95, 0), (3.9, 4.6), (5.85, 0), (7.8, _XH)]),
    "x": _g(5.0, [(0, 0), (5.0, _XH)], [(0, _XH), (5.0, 0)]),
    "y": _g(5.2, [(0, _XH), (2.6, 0)],
            [(5.2, _XH), (1.2, DESCENDER)]),
    "z": _g(4.8, [(0, _XH), (4.8, _XH), (0, 0), (4.8, 0)]),
}

# --- digits ----------------------------------------------------------------
_DIGITS: dict[str, Glyph] = {
    "0": _g(6.0, _cat(_ell(3.0, 5, 3.0, 5, 0, 360)), [(1.1, 1.9), (4.9, 8.1)]),
    "1": _g(4.0, [(0.6, 8.0), (2.4, CAP), (2.4, 0)], [(0.4, 0), (4.0, 0)]),
    "2": _g(6.0, _cat(_ell(3.0, 7.2, 3.0, 2.8, 170, -20), [(5.6, 5.2), (0, 0), (6.0, 0)])),
    "3": _g(6.0,
            _cat([(0.4, CAP), (5.4, CAP), (2.4, 6.0)], _ell(2.6, 3.2, 2.9, 2.9, 62, -140))),
    "4": _g(6.2, [(4.6, 0), (4.6, CAP), (0, 2.8), (6.2, 2.8)]),
    "5": _g(6.0, [(5.6, CAP), (0.9, CAP), (0.5, 5.6)],
            _cat([(0.5, 5.6)], _ell(3.0, 3.0, 3.0, 3.0, 105, -110))),
    "6": _g(6.0, _cat(_ell(3.0, 3.1, 3.0, 3.1, 0, 360)),
            _cat(_ell(3.0, 6.0, 3.0, 4.0, 180, 80))),
    "7": _g(5.8, [(0, CAP), (5.8, CAP), (2.0, 0)]),
    "8": _g(6.0, _cat(_ell(3.0, 7.4, 2.6, 2.6, 0, 360)), _cat(_ell(3.0, 2.9, 3.0, 2.9, 0, 360))),
    "9": _g(6.0, _cat(_ell(3.0, 6.9, 3.0, 3.1, 0, 360)),
            _cat(_ell(3.0, 4.0, 3.0, 4.0, 0, -100))),
}

# --- punctuation -----------------------------------------------------------
_PUNCT: dict[str, Glyph] = {
    " ": _g(WORD_SPACING),
    "/": _g(4.6, [(0, -1.0), (4.6, CAP + 0.4)]),
    "\\": _g(4.6, [(0, CAP + 0.4), (4.6, -1.0)]),
    "-": _g(5.0, [(0.4, 4.6), (4.6, 4.6)]),
    "_": _g(5.6, [(0, -1.6), (5.6, -1.6)]),
    ".": _g(1.4, [(0.2, 0), (0.7, 0), (0.7, 0.5), (0.2, 0.5), (0.2, 0)]),
    ",": _g(1.8, [(1.0, 0.6), (0.9, 0), (0.1, -1.6)]),
    ":": _g(1.4, [(0.2, 0), (0.7, 0)], [(0.2, 4.6), (0.7, 4.6)]),
    ";": _g(1.8, [(0.9, 4.6), (0.4, 4.6)], [(1.0, 0.6), (0.9, 0), (0.1, -1.6)]),
    "(": _g(2.8, _cat(_ell(2.8, 4.6, 2.8, 5.8, 140, 220))),
    ")": _g(2.8, _cat(_ell(0.0, 4.6, 2.8, 5.8, 40, -40))),
    "[": _g(2.6, [(2.6, -0.8), (0, -0.8), (0, CAP + 0.6), (2.6, CAP + 0.6)]),
    "]": _g(2.6, [(0, -0.8), (2.6, -0.8), (2.6, CAP + 0.6), (0, CAP + 0.6)]),
    "<": _g(5.2, [(5.0, 8.2), (0.2, 4.6), (5.0, 1.0)]),
    ">": _g(5.2, [(0.2, 8.2), (5.0, 4.6), (0.2, 1.0)]),
    "#": _g(6.6, [(1.9, 0), (2.9, CAP)], [(4.1, 0), (5.1, CAP)],
            [(0.4, 3.2), (6.2, 3.2)], [(0.8, 6.8), (6.6, 6.8)]),
    "+": _g(5.6, [(2.8, 1.6), (2.8, 7.6)], [(0, 4.6), (5.6, 4.6)]),
    "=": _g(5.6, [(0, 3.2), (5.6, 3.2)], [(0, 6.2), (5.6, 6.2)]),
    "*": _g(5.0, [(2.5, 5.0), (2.5, CAP)], [(0.2, 6.3), (4.8, 8.7)], [(0.2, 8.7), (4.8, 6.3)]),
    "'": _g(1.4, [(0.5, CAP), (0.5, 7.6)]),
    '"': _g(3.0, [(0.5, CAP), (0.5, 7.6)], [(2.5, CAP), (2.5, 7.6)]),
    "!": _g(1.4, [(0.5, CAP), (0.5, 2.6)], [(0.2, 0), (0.7, 0)]),
    "?": _g(5.2, _cat(_ell(2.6, 7.2, 2.6, 2.8, 175, -60), [(2.6, 2.8)]), [(2.3, 0), (2.8, 0)]),
    "&": _g(6.8, _cat(_ell(2.4, 8.0, 2.0, 2.0, -60, 200),
                      [(0.6, 6.6), (5.4, 0.0)],
                      _ell(2.6, 2.6, 2.6, 2.6, -60, 150),
                      [(6.8, 3.2)])),
    "@": _g(7.2, _cat(_ell(3.4, 4.4, 1.8, 1.8, 0, 360)),
            _cat([(5.2, 4.4), (5.2, 2.8)], _ell(3.4, 4.6, 3.4, 4.6, -15, 300))),
    "%": _g(7.0, [(0.6, 0), (6.4, CAP)],
            _cat(_ell(1.7, 8.0, 1.7, 2.0, 0, 360)), _cat(_ell(5.3, 2.0, 1.7, 2.0, 0, 360))),
}

GLYPHS: dict[str, Glyph] = {**_UPPER, **_LOWER, **_DIGITS, **_PUNCT}

# Anything unmapped engraves as a filled-ish box so a bad label is obvious
# rather than silently missing.
TOFU = _g(5.0, [(0.4, 0.4), (4.6, 0.4), (4.6, 9.6), (0.4, 9.6), (0.4, 0.4)], [(0.4, 0.4), (4.6, 9.6)])


def glyph_for(ch: str, *, uppercase_fallback: bool = True) -> Glyph:
    g = GLYPHS.get(ch)
    if g is not None:
        return g
    if uppercase_fallback:
        g = GLYPHS.get(ch.upper()) or GLYPHS.get(ch.lower())
        if g is not None:
            return g
    return TOFU


def text_strokes(
    text: str, height: float, *, uppercase: bool = False, tracking: float = 0.0
) -> tuple[list[list[tuple[float, float]]], float, float]:
    """Lay ``text`` out on the baseline at the origin.

    Returns ``(strokes, width, ascent)`` in the same units as ``height``, where
    ``height`` is the cap height.
    """
    if uppercase:
        text = text.upper()
    scale = height / CAP
    strokes: list[list[tuple[float, float]]] = []
    pen = 0.0
    top = CAP
    bottom = 0.0
    for ch in text:
        g = glyph_for(ch)
        for s in g.strokes:
            strokes.append([((pen + x) * scale, y * scale) for x, y in s])
            for _, y in s:
                top = max(top, y)
                bottom = min(bottom, y)
        pen += g.advance + LETTER_SPACING + tracking / max(scale, 1e-9)
    width = max(0.0, pen - LETTER_SPACING - tracking / max(scale, 1e-9)) * scale
    return strokes, width, top * scale


def text_extents(text: str, height: float, *, uppercase: bool = False) -> tuple[float, float, float]:
    """``(width, ascent_above_baseline, descent_below_baseline)`` for ``text``."""
    if uppercase:
        text = text.upper()
    scale = height / CAP
    pen = 0.0
    top, bottom = CAP, 0.0
    for ch in text:
        g = glyph_for(ch)
        for s in g.strokes:
            for _, y in s:
                top = max(top, y)
                bottom = min(bottom, y)
        pen += g.advance + LETTER_SPACING
    width = max(0.0, pen - LETTER_SPACING) * scale
    return width, top * scale, -bottom * scale
