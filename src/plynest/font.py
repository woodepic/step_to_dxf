"""A built-in single-stroke (engraving) vector font.

Outline fonts force a router to either V-carve or pocket the counters of every
letter; a single-stroke font is one pass of the bit down the centre of each
line, which is what you want for a 6 mm part label.  Nothing suitable ships
with ezdxf, so the glyphs live here.

Curves are **circular arcs**, not sampled points, so they reach the DXF as real
ARC geometry and stay smooth at any zoom.  Every stroke is a continuous chain:
each segment starts exactly where the previous one ended (``test_font`` asserts
it), which is what stops a letter from being crossed by a stray chord.

Design grid: baseline y=0, cap height y=CAP, x-height y=XH, descenders to
DESCENDER.  Coordinates are scaled by (height / CAP) at render time.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .geom2d import TAU, Arc, Line, Point, Segment, bounds_union

CAP = 10.0
XH = 6.0
DESCENDER = -3.0
LETTER_SPACING = 1.9
WORD_SPACING = 4.2
LINE_SPACING = 1.55  # multiples of cap height


@dataclass(frozen=True)
class _L:
    """A straight run, in glyph units."""

    x0: float
    y0: float
    x1: float
    y1: float

    def start(self) -> tuple[float, float]:
        return (self.x0, self.y0)

    def end(self) -> tuple[float, float]:
        return (self.x1, self.y1)

    def to_segment(self, scale: float, pen: float) -> Segment:
        return Line(
            Point((self.x0 + pen) * scale, self.y0 * scale),
            Point((self.x1 + pen) * scale, self.y1 * scale),
        )


@dataclass(frozen=True)
class _A:
    """A circular arc, angles in degrees; anticlockwise when a1 > a0."""

    cx: float
    cy: float
    r: float
    a0: float
    a1: float

    def _at(self, deg: float) -> tuple[float, float]:
        a = math.radians(deg)
        return (self.cx + self.r * math.cos(a), self.cy + self.r * math.sin(a))

    def start(self) -> tuple[float, float]:
        return self._at(self.a0)

    def end(self) -> tuple[float, float]:
        return self._at(self.a1)

    @property
    def full(self) -> bool:
        return abs(self.a1 - self.a0) >= 359.999

    def to_segment(self, scale: float, pen: float) -> Segment:
        return Arc(
            Point((self.cx + pen) * scale, self.cy * scale),
            self.r * scale,
            math.radians(self.a0) % TAU,
            math.radians(self.a1) % TAU,
            ccw=self.a1 > self.a0,
            full=self.full,
        )


GlyphSeg = _L | _A
Stroke = tuple[GlyphSeg, ...]


@dataclass(frozen=True)
class Glyph:
    advance: float
    strokes: tuple[Stroke, ...]


def _chain(segs: list[GlyphSeg] | tuple[GlyphSeg, ...]) -> tuple[GlyphSeg, ...]:
    """Snap straight runs onto their neighbours' endpoints.

    Arcs define the true geometry; a line's endpoints are hand-written, so they
    are rewritten to match whatever they join. That keeps every chain exactly
    continuous without having to type arc endpoints to full precision.
    """
    out = list(segs)
    for i in range(1, len(out)):
        cur = out[i]
        if isinstance(cur, _L):
            px, py = out[i - 1].end()
            out[i] = _L(px, py, cur.x1, cur.y1)
    for i in range(len(out) - 1):
        cur, nxt = out[i], out[i + 1]
        if isinstance(cur, _L) and isinstance(nxt, _A):
            nx, ny = nxt.start()
            out[i] = _L(cur.x0, cur.y0, nx, ny)
    return tuple(out)


def _g(advance: float, *strokes: list[GlyphSeg] | tuple[GlyphSeg, ...]) -> Glyph:
    return Glyph(advance, tuple(_chain(s) for s in strokes))


# --- uppercase -------------------------------------------------------------
# Bowls are built from circular arcs joined by straight sides (a "stadium"),
# which keeps every curve exactly circular without making the caps look round.
_UPPER: dict[str, Glyph] = {
    "A": _g(6.4,
            [_L(0, 0, 3.2, CAP), _L(3.2, CAP, 6.4, 0)],
            [_L(1.2, 3.75, 5.2, 3.75)]),
    "B": _g(5.2,
            [_L(0, 0, 0, CAP)],
            [_L(0, CAP, 2.4, CAP), _A(2.4, 7.5, 2.5, 90, -90), _L(2.4, 5, 0, 5)],
            [_L(0, 5, 2.4, 5), _A(2.4, 2.5, 2.5, 90, -90), _L(2.4, 0, 0, 0)]),
    "C": _g(6.0,
            [_A(3, 7, 3, 20, 180), _L(0, 7, 0, 3), _A(3, 3, 3, 180, 340)]),
    "D": _g(6.2,
            [_L(0, 0, 0, CAP)],
            [_L(0, CAP, 3, CAP), _A(3, 7, 3, 90, 0), _L(6, 7, 6, 3),
             _A(3, 3, 3, 0, -90), _L(3, 0, 0, 0)]),
    "E": _g(5.6,
            [_L(5.6, CAP, 0, CAP), _L(0, CAP, 0, 0), _L(0, 0, 5.6, 0)],
            [_L(0, 5, 4.4, 5)]),
    "F": _g(5.4,
            [_L(5.4, CAP, 0, CAP), _L(0, CAP, 0, 0)],
            [_L(0, 5, 4.3, 5)]),
    "G": _g(6.0,
            [_A(3, 7, 3, 20, 180), _L(0, 7, 0, 3), _A(3, 3, 3, 180, 360),
             _L(6, 3, 6, 4.8), _L(6, 4.8, 3.6, 4.8)]),
    "H": _g(6.4,
            [_L(0, 0, 0, CAP)], [_L(6.4, 0, 6.4, CAP)], [_L(0, 5, 6.4, 5)]),
    "I": _g(1.0, [_L(0.5, 0, 0.5, CAP)]),
    "J": _g(4.6, [_L(4.6, CAP, 4.6, 2.4), _A(2.3, 2.4, 2.3, 0, -180)]),
    "K": _g(6.2,
            [_L(0, 0, 0, CAP)], [_L(6.0, CAP, 0.2, 4.1)], [_L(2.2, 5.6, 6.2, 0)]),
    "L": _g(5.2, [_L(0, CAP, 0, 0), _L(0, 0, 5.2, 0)]),
    "M": _g(7.6,
            [_L(0, 0, 0, CAP), _L(0, CAP, 3.8, 3.4), _L(3.8, 3.4, 7.6, CAP),
             _L(7.6, CAP, 7.6, 0)]),
    "N": _g(6.6, [_L(0, 0, 0, CAP), _L(0, CAP, 6.6, 0), _L(6.6, 0, 6.6, CAP)]),
    "O": _g(6.0,
            [_A(3, 7, 3, 0, 180), _L(0, 7, 0, 3), _A(3, 3, 3, 180, 360),
             _L(6, 3, 6, 7)]),
    "P": _g(5.2,
            [_L(0, 0, 0, CAP)],
            [_L(0, CAP, 2.6, CAP), _A(2.6, 7.4, 2.6, 90, -90), _L(2.6, 4.8, 0, 4.8)]),
    "Q": _g(6.4,
            [_A(3, 7, 3, 0, 180), _L(0, 7, 0, 3), _A(3, 3, 3, 180, 360),
             _L(6, 3, 6, 7)],
            [_L(3.8, 2.4, 6.4, -0.4)]),
    "R": _g(5.6,
            [_L(0, 0, 0, CAP)],
            [_L(0, CAP, 2.6, CAP), _A(2.6, 7.4, 2.6, 90, -90), _L(2.6, 4.8, 0, 4.8)],
            [_L(2.8, 4.8, 5.6, 0)]),
    # Two tangent circles: they meet exactly at (2.8, 5) and turn opposite ways,
    # which is what makes the spine of the S continuous.
    "S": _g(5.6,
            [_A(2.8, 7.5, 2.5, -35, 270), _A(2.8, 2.5, 2.5, 90, -145)]),
    "T": _g(6.0, [_L(0, CAP, 6, CAP)], [_L(3, CAP, 3, 0)]),
    "U": _g(6.0, [_L(0, CAP, 0, 3), _A(3, 3, 3, 180, 360), _L(6, 3, 6, CAP)]),
    "V": _g(6.4, [_L(0, CAP, 3.2, 0), _L(3.2, 0, 6.4, CAP)]),
    "W": _g(9.2,
            [_L(0, CAP, 2.3, 0), _L(2.3, 0, 4.6, 6.6), _L(4.6, 6.6, 6.9, 0),
             _L(6.9, 0, 9.2, CAP)]),
    "X": _g(6.2, [_L(0, 0, 6.2, CAP)], [_L(0, CAP, 6.2, 0)]),
    "Y": _g(6.2,
            [_L(0, CAP, 3.1, 4.8), _L(3.1, 4.8, 6.2, CAP)], [_L(3.1, 4.8, 3.1, 0)]),
    "Z": _g(6.0, [_L(0, CAP, 6, CAP), _L(6, CAP, 0, 0), _L(0, 0, 6, 0)]),
}

# --- digits ----------------------------------------------------------------
_DIGITS: dict[str, Glyph] = {
    "0": _g(5.6,
            [_A(2.8, 7.2, 2.8, 0, 180), _L(0, 7.2, 0, 2.8),
             _A(2.8, 2.8, 2.8, 180, 360), _L(5.6, 2.8, 5.6, 7.2)],
            [_L(1.0, 1.9, 4.6, 8.1)]),
    "1": _g(4.0, [_L(0.6, 8.0, 2.4, CAP), _L(2.4, CAP, 2.4, 0)], [_L(0.4, 0, 4.0, 0)]),
    "2": _g(5.6,
            [_A(2.8, 7.2, 2.8, 160, -25), _L(5.34, 6.02, 0.2, 0), _L(0.2, 0, 5.6, 0)]),
    "3": _g(5.2,
            [_A(2.6, 7.5, 2.5, 150, -90), _A(2.6, 2.5, 2.5, 90, -150)]),
    "4": _g(6.2, [_L(4.6, 0, 4.6, CAP), _L(4.6, CAP, 0, 2.8), _L(0, 2.8, 6.2, 2.8)]),
    "5": _g(5.5,
            [_L(5.2, CAP, 0.7, CAP), _L(0.7, CAP, 0.7, 4.6),
             _A(2.8, 2.9, 2.7, 141, -140)]),
    "6": _g(5.6,
            [_A(2.8, 3.0, 2.8, 0, 360)],
            [_A(7.0, 3.0, 7.0, 180, 122)]),
    "7": _g(5.6, [_L(0, CAP, 5.6, CAP), _L(5.6, CAP, 1.9, 0)]),
    "8": _g(5.5,
            [_A(2.8, 7.7, 2.3, 0, 360)],
            [_A(2.8, 2.7, 2.7, 0, 360)]),
    "9": _g(5.6,
            [_A(2.8, 7.0, 2.8, 0, 360)],
            [_A(-1.4, 7.0, 7.0, 0, -58)]),
}

# --- lowercase -------------------------------------------------------------
_LOWER: dict[str, Glyph] = {
    "a": _g(6.0, [_A(3, 3, 3, 0, 360)], [_L(6, XH, 6, 0)]),
    "b": _g(6.0, [_L(0, CAP, 0, 0)], [_A(3, 3, 3, 0, 360)]),
    "c": _g(6.0, [_A(3, 3, 3, 50, 310)]),
    "d": _g(6.0, [_L(6, CAP, 6, 0)], [_A(3, 3, 3, 0, 360)]),
    "e": _g(6.0, [_L(0, 3, 6, 3), _A(3, 3, 3, 0, 300)]),
    "f": _g(4.3,
            [_L(1.6, 0, 1.6, 8.2), _A(3.4, 8.2, 1.8, 180, 60)],
            [_L(0, XH, 3.6, XH)]),
    "g": _g(6.0,
            [_A(3, 3, 3, 0, 360)],
            [_L(6, XH, 6, -1), _A(3, -1, 3, 0, -180)]),
    "h": _g(6.0, [_L(0, CAP, 0, 0)], [_A(3, 3, 3, 180, 0), _L(6, 3, 6, 0)]),
    "i": _g(1.0, [_L(0.5, XH, 0.5, 0)], [_L(0.5, 8.6, 0.5, 9.4)]),
    "j": _g(2.4,
            [_L(2.4, XH, 2.4, -1), _A(1.2, -1, 1.2, 0, -180)],
            [_L(2.4, 8.6, 2.4, 9.4)]),
    "k": _g(5.0,
            [_L(0, CAP, 0, 0)], [_L(4.6, XH, 0.2, 2.2)], [_L(1.7, 3.5, 5.0, 0)]),
    "l": _g(1.0, [_L(0.5, CAP, 0.5, 0)]),
    "m": _g(8.8,
            [_L(0, XH, 0, 0)],
            [_A(2.2, 3.8, 2.2, 180, 0), _L(4.4, 3.8, 4.4, 0)],
            [_A(6.6, 3.8, 2.2, 180, 0), _L(8.8, 3.8, 8.8, 0)]),
    "n": _g(6.0, [_L(0, XH, 0, 0)], [_A(3, 3, 3, 180, 0), _L(6, 3, 6, 0)]),
    "o": _g(6.0, [_A(3, 3, 3, 0, 360)]),
    "p": _g(6.0, [_L(0, DESCENDER, 0, XH)], [_A(3, 3, 3, 0, 360)]),
    "q": _g(6.0, [_L(6, DESCENDER, 6, XH)], [_A(3, 3, 3, 0, 360)]),
    "r": _g(3.6, [_L(0, XH, 0, 0)], [_A(2.6, 3.4, 2.6, 180, 70)]),
    "s": _g(4.0, [_A(2.0, 4.5, 1.5, -35, 270), _A(2.0, 1.5, 1.5, 90, -145)]),
    "t": _g(3.8,
            [_L(1.4, CAP, 1.4, 1.4), _A(2.6, 1.4, 1.2, 180, 270)],
            [_L(0, XH, 3.6, XH)]),
    "u": _g(6.0, [_L(0, XH, 0, 3), _A(3, 3, 3, 180, 360), _L(6, 3, 6, XH)]),
    "v": _g(6.0, [_L(0, XH, 3, 0), _L(3, 0, 6, XH)]),
    "w": _g(8.4,
            [_L(0, XH, 2.1, 0), _L(2.1, 0, 4.2, 4.2), _L(4.2, 4.2, 6.3, 0),
             _L(6.3, 0, 8.4, XH)]),
    "x": _g(5.0, [_L(0, 0, 5, XH)], [_L(0, XH, 5, 0)]),
    "y": _g(6.0, [_L(0, XH, 3.2, 0.4)], [_L(6, XH, 1.4, DESCENDER)]),
    "z": _g(4.8, [_L(0, XH, 4.8, XH), _L(4.8, XH, 0, 0), _L(0, 0, 4.8, 0)]),
}

# --- punctuation -----------------------------------------------------------
_PUNCT: dict[str, Glyph] = {
    " ": _g(WORD_SPACING),
    "/": _g(4.6, [_L(0, -1, 4.6, 11)]),
    "\\": _g(4.6, [_L(0, 11, 4.6, -1)]),
    "-": _g(5.0, [_L(0.4, 4.6, 4.6, 4.6)]),
    "_": _g(5.6, [_L(0, -1.6, 5.6, -1.6)]),
    ".": _g(1.4, [_L(0.55, 0, 0.55, 0.5)]),
    ",": _g(1.8, [_L(0.9, 0.6, 0.75, 0), _L(0.75, 0, 0.1, -1.5)]),
    ":": _g(1.4, [_L(0.55, 0, 0.55, 0.5)], [_L(0.55, 4.3, 0.55, 4.8)]),
    ";": _g(1.8, [_L(0.75, 4.3, 0.75, 4.8)], [_L(0.9, 0.6, 0.75, 0), _L(0.75, 0, 0.1, -1.5)]),
    "(": _g(2.4, [_A(6.0, 5.0, 6.0, 145, 215)]),
    ")": _g(2.4, [_A(-3.6, 5.0, 6.0, -35, 35)]),
    "[": _g(2.6, [_L(2.6, -0.8, 0, -0.8), _L(0, -0.8, 0, 10.6), _L(0, 10.6, 2.6, 10.6)]),
    "]": _g(2.6, [_L(0, -0.8, 2.6, -0.8), _L(2.6, -0.8, 2.6, 10.6), _L(2.6, 10.6, 0, 10.6)]),
    "<": _g(5.2, [_L(5.0, 8.2, 0.2, 4.6), _L(0.2, 4.6, 5.0, 1.0)]),
    ">": _g(5.2, [_L(0.2, 8.2, 5.0, 4.6), _L(5.0, 4.6, 0.2, 1.0)]),
    "#": _g(6.6,
            [_L(1.9, 0, 2.9, CAP)], [_L(4.1, 0, 5.1, CAP)],
            [_L(0.4, 3.2, 6.2, 3.2)], [_L(0.8, 6.8, 6.6, 6.8)]),
    "+": _g(5.6, [_L(2.8, 1.6, 2.8, 7.6)], [_L(0, 4.6, 5.6, 4.6)]),
    "=": _g(5.6, [_L(0, 3.2, 5.6, 3.2)], [_L(0, 6.2, 5.6, 6.2)]),
    "*": _g(5.0,
            [_L(2.5, 5.0, 2.5, CAP)], [_L(0.2, 6.3, 4.8, 8.7)], [_L(0.2, 8.7, 4.8, 6.3)]),
    "'": _g(1.4, [_L(0.5, CAP, 0.5, 7.6)]),
    '"': _g(3.0, [_L(0.5, CAP, 0.5, 7.6)], [_L(2.5, CAP, 2.5, 7.6)]),
    "!": _g(1.4, [_L(0.5, CAP, 0.5, 2.6)], [_L(0.5, 0, 0.5, 0.5)]),
    "?": _g(4.8,
            [_A(2.4, 7.6, 2.4, 170, -40), _L(4.24, 6.06, 2.4, 3.6), _L(2.4, 3.6, 2.4, 2.6)],
            [_L(2.4, 0, 2.4, 0.5)]),
    # Loop, diagonal down-left, bowl round the bottom, then a long terminal
    # that sweeps back up past the loop -- without it this reads as a reversed S.
    "&": _g(6.6,
            [_A(2.2, 7.9, 1.7, 210, -70), _L(0, 0, 0.66, 4.05),
             _A(3.0, 2.7, 2.7, 150, 390), _L(0, 0, 6.6, 6.0)]),
    "@": _g(7.0,
            [_A(3.2, 4.4, 1.6, 0, 360)],
            [_A(3.2, 4.4, 3.4, -20, 300)]),
    "%": _g(7.0,
            [_L(0.6, 0, 6.4, CAP)],
            [_A(1.7, 8.0, 1.5, 0, 360)],
            [_A(5.3, 2.0, 1.5, 0, 360)]),
}

GLYPHS: dict[str, Glyph] = {**_UPPER, **_LOWER, **_DIGITS, **_PUNCT}

# Anything unmapped engraves as a crossed box, so a bad label is obvious rather
# than silently missing.
TOFU = _g(5.0,
          [_L(0.4, 0.4, 4.6, 0.4), _L(4.6, 0.4, 4.6, 9.6),
           _L(4.6, 9.6, 0.4, 9.6), _L(0.4, 9.6, 0.4, 0.4)],
          [_L(0.4, 0.4, 4.6, 9.6)])


def glyph_for(ch: str, *, uppercase_fallback: bool = True) -> Glyph:
    g = GLYPHS.get(ch)
    if g is not None:
        return g
    if uppercase_fallback:
        g = GLYPHS.get(ch.upper()) or GLYPHS.get(ch.lower())
        if g is not None:
            return g
    return TOFU


def text_paths(
    text: str, height: float, *, uppercase: bool = False, tracking: float = 0.0
) -> list[list[Segment]]:
    """Lay ``text`` out on the baseline at the origin, as open segment chains.

    ``height`` is the cap height.  Curves come back as real arcs.
    """
    if uppercase:
        text = text.upper()
    scale = height / CAP
    extra = tracking / scale if scale else 0.0
    out: list[list[Segment]] = []
    pen = 0.0
    for ch in text:
        g = glyph_for(ch)
        for stroke in g.strokes:
            out.append([seg.to_segment(scale, pen) for seg in stroke])
        pen += g.advance + LETTER_SPACING + extra
    return out


def text_strokes(
    text: str, height: float, *, uppercase: bool = False, tracking: float = 0.0,
    tol: float | None = None,
) -> tuple[list[list[tuple[float, float]]], float, float]:
    """Sampled form of :func:`text_paths`, for previews and solid modelling.

    Returns ``(strokes, width, ascent)``.
    """
    from .geom2d import ARC_CHORD_TOL

    chord = tol if tol is not None else min(ARC_CHORD_TOL, height / 120.0)
    strokes: list[list[tuple[float, float]]] = []
    for path in text_paths(text, height, uppercase=uppercase, tracking=tracking):
        pts: list[tuple[float, float]] = []
        for seg in path:
            sampled = [(p.x, p.y) for p in seg.sample(chord)]
            if pts and math.dist(pts[-1], sampled[0]) < 1e-9:
                sampled = sampled[1:]
            pts.extend(sampled)
        if len(pts) >= 2:
            strokes.append(pts)
    width, ascent, _ = text_extents(text, height, uppercase=uppercase, tracking=tracking)
    return strokes, width, ascent


def text_extents(
    text: str, height: float, *, uppercase: bool = False, tracking: float = 0.0
) -> tuple[float, float, float]:
    """``(width, ascent_above_baseline, descent_below_baseline)`` for ``text``.

    Exact: arc extents come from the arc, not from sampled points.
    """
    if uppercase:
        text = text.upper()
    scale = height / CAP
    paths = text_paths(text, height, uppercase=False, tracking=tracking)
    top, bottom = CAP * scale, 0.0
    if paths:
        _, y0, _, y1 = bounds_union(seg.bounds() for path in paths for seg in path)
        top, bottom = max(top, y1), min(bottom, y0)

    pen = 0.0
    for ch in text:
        pen += glyph_for(ch).advance + LETTER_SPACING + (tracking / scale if scale else 0)
    width = max(0.0, pen - LETTER_SPACING - (tracking / scale if scale else 0)) * scale
    return width, top, -bottom
