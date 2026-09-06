# plynest

Turn a STEP assembly of plywood parts into nested 4×8 sheets and CNC-ready DXF.

Point it at an assembly, and it works out which face of each part has to be
uppermost, flattens the part to a 2D profile with a layer per cut depth, nests
everything onto sheets of the right stock thickness, engraves each part's name
somewhere the router can actually reach, and writes the DXF.

It can also hand the layout back as STEP: the original solids, re-posed into the
nest with the labels cut into them.

```
STEP assembly ──▶ orient & flatten ──▶ label ──▶ nest ──▶ DXF
                                                       └─▶ STEP
```

---

## Quick start

```bash
python3.11 -m venv venv
./venv/bin/pip install -r requirements.txt

# Web UI
./run_web.sh                          # then open http://127.0.0.1:8000

# Or the command line
./venv/bin/python -m plynest.cli "Full Layout.step" -o out/
```

The sample assembly in this repo (112 parts, four cabinets with drawers) nests
onto **10 sheets at 70.9% material utilisation** in about 3 seconds.

---

## How it decides which way up a part goes

The sheet never gets flipped on the router, so every bit of material removed has
to be reachable from above. Geometrically that means the underside of the part
is one complete plane — **any downward-facing horizontal face sitting above the
bottom is an undercut**, and an undercut is what tells you the part arrived
upside down.

So for each solid, plynest:

1. **Finds the sheet axis.** The planar direction carrying the most face area.
   For a panel that is the pair of big faces, whatever pose the assembly left
   the part in.
2. **Picks the pose.** It measures undercut area with the part as-is and turned
   over, and takes the pose with none. If *both* poses have undercuts, the part
   genuinely cannot be finished from one side and you get a warning naming it
   rather than a quietly wrong DXF.
3. **Squares it to the axes** using the dominant straight edge of the outline.
4. **Reads the geometry off the faces**, not off slices:
   - the **underside** gives the through-cut profile — outer boundary and any
     through holes;
   - each **upward-facing face below the top surface** is a pocket floor, and
     its height gives the depth. A rabbet, a dado, a blind shelf-pin hole and a
     stepped pocket all fall out of the same rule.

Circles and arcs stay symbolic the whole way through, so a hole arrives in the
DXF as a `CIRCLE`, not as a hundred tiny chords.

### Why you can trust the flattening

Every part's volume is reconstructed from the extracted 2D data:

```
volume  =  thickness × profile area  −  Σ (pocket area × pocket depth)
```

and compared against what OpenCASCADE measures for the original solid. Across
all 112 parts of the sample assembly the worst error is **0.0006%**, which is
arc tessellation and nothing else. This runs as a test.

---

## Nesting

Sheet-goods parts are overwhelmingly rectangles, and rectangles have a much
better literature than general nesting, so there are two engines. `auto` picks
the rectangle one whenever every part in a stock group is rectangular, and falls
back to the polygon nester otherwise.

### The rectangle engine

Two ideas from the literature do the work:

**Maximal rectangles** — free space is kept as the set of maximal empty
rectangles rather than a skyline, so a part can drop into any gap, including one
enclosed by parts placed earlier, which a bottom-left scan can never reach. Four
fit rules are tried (Best Short Side Fit, Best Long Side Fit, Best Area Fit,
Bottom-Left) across six orderings; BSSF usually but not always wins. This is
Jylänki's MaxRects family.

**Goal-driven ruin and recreate, with late acceptance** — a greedy pass alone
plateaus almost immediately, which is the trap the first version of this program
fell into: reordering the parts and re-running the same decoder just explores one
basin. Instead the search fixes a target of one fewer sheet and repeatedly ruins
part of the layout — a few whole sheets, a patch around a random part, or a
scattered slice — then rebuilds it, driving the *homeless area* to zero. That is
a far sharper signal than nudging a general objective and hoping a sheet empties.
Late-acceptance hill climbing compares against what the search held some
iterations ago, so it can walk through worse layouts to reach better ones.

Three details matter in practice:

- **The kerf is handled by inflation.** Every part and the sheet grow by one
  kerf, and the gap between neighbours falls out of the arithmetic with no
  special cases at the sheet edge.
- **The search stops when it is provably done.** It computes the continuous area
  lower bound and returns the moment it reaches it — which is why a high effort
  setting costs nothing on an easy job.
- **Hopeless targets are abandoned.** Most targets clear the area bound but are
  geometrically impossible; after a spell without progress the search writes that
  target off rather than grinding to the end of the budget.

`Search effort` is roughly the number of seconds spent trying to beat the first
packing. Unlike the old nester, spending more genuinely buys more: when the
direct attempt stalls, the search restarts the same target from a completely
different randomised packing.

### What it is worth

On the sample assembly: **10 sheets to 9**, and 9 is the proven lower bound
(4 + 5), so that job is now optimal. Utilisation 70.9% → 78.8%.

Across 16 randomly generated kitchen jobs (33–156 parts each):

| | sheets | time |
|---|---|---|
| polygon engine | 166 | 8.3 s |
| rectangle engine | **160** | 21.5 s |

**3.6% less plywood**, better on 6 jobs and worse on none. It is also far faster
at scale on hard instances — a 600-part instance went from 288 s to 10 s.

`bench/` holds the harness: instances with known optima built by guillotine-
cutting whole sheets, realistic kitchen jobs, and a population comparison.

### The polygon engine

Bottom-left fill over true outlines, with candidate positions taken from the
edges of already-placed parts, plus a consolidation pass that empties the
least-used sheet into the others. It handles genuinely irregular parts — an
L-shaped part lets a neighbour tuck into its notch — and free-angle rotation.

### Both engines

Parts of different thickness never share a sheet; they are different stock.

**Kerf is spacing, not an offset.** Exported outlines are true part size and the
gap between neighbours is guaranteed to be at least the kerf, so your CAM applies
the tool offset as usual. Edge keep-out is the border left free for hold-down
bolts and clamps.

## Labels

Part names are engraved with a **built-in single-stroke font**. An outline font
would force the router to V-carve or pocket the counter of every letter; a
single-stroke font is one pass of the bit down the centre of each stroke, which
is what a ¼″ part label wants.

Every curve in it is a real circular arc, and every stroke is one continuous
chain — the tests assert both. That matters: an arc reaches the DXF as an arc,
so letters stay smooth at any zoom instead of showing facets, and a stroke with
a gap in it would draw as a chord straight through the middle of the letter.

Placement walks inward from the chosen corner (bottom-right by default) until
the whole text box sits on solid top surface — inside the outline, clear of
every pocket, rabbet and through hole, and inset from the edge by a margin. If
it will not fit the label turns 90°, then shrinks; if it still will not fit you
are told which part, rather than getting a label cut through a rabbet.

Names come from the assembly path, abbreviated: `Assembled Cabinet <4>` +
`Drawer Assembly <2>` + `Floor` becomes **`AC4/DA2/Floor`**. Where two parts
would end up with the same label they get numbered — and only then.

Labels are toggleable in the viewer and at export.

---

## Output

Three things you can export, all as a zip with a plain-text layout report:

| Mode | What you get |
|---|---|
| **DXF, one per sheet** | `Sheet 1, 0.75 in.dxf` — the nested layout, a layer per cut depth |
| **DXF, one per part** | `AC4-DA2-Front Side.dxf` — each part at the origin; ignores the layout |
| **STEP, one per sheet** | `Sheet 1, 0.75 in.step` — the real solids re-posed into the nest |

Layer names say how deep to cut, measured down from the part's top face:

| Layer | Contents |
|---|---|
| `CUT THROUGH 0.75 in deep` | outlines and through holes, cut to full thickness |
| `POCKET 0.25 in deep` | pocket floors a quarter inch down |
| `ENGRAVE 0.04 in deep` | label strokes |
| `SHEET OUTLINE`, `EDGE KEEP-OUT` | reference only; keep-out is off by default |

Nothing is ever drawn on layer `0`, and `Defpoints` is not written. (Layer `0`
still exists — the DXF spec requires it.)

Closed profiles are written as single closed `LWPOLYLINE`s carrying bulge
factors, so arcs survive into CAM as arcs; no polyline arc exceeds a half turn,
which keeps fussy post-processors happy. Units are inches or millimetres, with
`$INSUNITS` set to match.

### The STEP mode

This is the "rearrange my assembly" mode. It takes the **original solids** from
your input file, applies the pose the orienter chose and the position the nester
chose, and cuts the engraved label into the top face. Nothing is re-modelled
from the 2D profile, so every fillet, chamfer and hole in the source survives
exactly — the tests assert the volume is unchanged to 1 part in 10⁹.

Solid text is expensive: every vertex of a groove becomes a face, and each face
costs about a hundred STEP entities. The sample assembly comes to ~150 MB across
ten sheets, or ~24 MB zipped, in about 20 seconds. Turn off "cut the labels into
the solids" and the same export is a few hundred KB and near-instant.

The groove defaults to 0.03″ wide. Because the STEP is a *representation* — the
cut itself comes from the DXF, which keeps exact arcs — the groove outline is
tessellated to a fraction of the cap height rather than to full precision.

---

## Web UI

Drag in a `.step`, adjust settings, nest, and inspect the result before
exporting. The viewer pans and zooms, has a tab per sheet, and lets you toggle
labels, pockets, holes and the keep-out rectangle independently. Switching
between inches and millimetres rewrites every field.

Settings: sheet size, kerf, edge keep-out, rotation mode (90° steps / 180° only
to keep the grain / none / any angle), search effort, and for labels: height,
engrave depth, corner, naming style, edge margin, feature clearance and case.

---

## Command line

```
plynest STEP [-o OUT] [--unit {in,mm}]
             [--sheet-width W] [--sheet-height H]
             [--kerf K] [--edge-keepout E]
             [--rotation {none,180,90,free}] [--attempts EFFORT]
             [--engine {auto,rect,polygon}]
             [--mode {dxf_per_sheet,dxf_per_part,step_per_sheet}]
             [--no-labels] [--label-height H] [--label-depth D]
             [--label-corner ...] [--label-style ...]
             [--keepout-layer] [--engrave-tool W] [--no-engrave-in-step]
```

The CLI writes loose files into `-o`; the web UI zips them.

All lengths are in whatever `--unit` says. Exit status is non-zero if any part
could not be placed.

---

## Tests

```bash
./venv/bin/python -m pytest        # 343 tests, ~40 s
```

The suite covers geometry transforms and exact arc maths, font coverage,
orientation and flattening against synthetic solids of known size, label
placement, DXF and STEP round-trips, nesting invariants, the command line, the
HTTP endpoints, and a pile of hostile inputs — spheres, bars, discs, zero-area
outlines, negative kerfs, Windows reserved filenames, junk STEP files and
settings full of nonsense. The checks that matter most for trusting a cut file:

- every solid in the STEP file becomes a part, and every part reaches a sheet
  **exactly once**;
- each placed part still has its **true dimensions and area**;
- **volume is conserved** from the STEP solid all the way to the 2D data;
- no two parts overlap, and every gap is at least the kerf;
- everything is inside the edge keep-out, and no sheet mixes stock thickness;
- no label crosses a pocket or leaves its part;
- exporting and **re-reading the DXF** reproduces every part at the right size
  and position;
- exporting and **re-reading the STEP** puts every solid where the nest said,
  with its volume unchanged;
- the HTTP endpoints the browser calls, including the one that reshapes every
  part for the preview.

Tests needing the sample assembly skip cleanly if it is absent.

---

## Layout

```
src/plynest/
  step_loader.py   STEP → named, world-positioned solids (XCAF, keeps the tree)
  orient.py        pose selection and flattening
  profile.py       planar faces → 2D contours, arcs kept symbolic
  geom2d.py        points, lines, arcs, contours, regions; exact area and bounds
  part.py          the sheet-part model
  font.py          built-in single-stroke engraving font, arcs and all
  labels.py        where a label can legally go
  nest.py          the packer, and the choice between engines
  nest_rect.py     maximal rectangles + ruin-and-recreate search
  naming.py        readable file and layer names
  dxf_export.py    DXF writing
  step_export.py   re-posing the original solids, engraving included
  pipeline.py      end to end
  cli.py           command line
  web/             FastAPI back end + browser UI
```

## Requirements

Python 3.10+, and `cadquery-ocp` (OpenCASCADE), `ezdxf`, `shapely`, `numpy`,
`fastapi`. Everything installs from PyPI; no conda needed.

---

## References

The rectangle engine follows:

- Jukka Jylänki, *A Thousand Ways to Pack the Bin — A Practical Approach to
  Two-Dimensional Rectangle Bin Packing* (2010) — the MaxRects family and the
  fit rules, with Best Short Side Fit as the usual winner.
- E. K. Burke, G. Kendall, G. Whitwell, *A New Placement Heuristic for the
  Orthogonal Stock-Cutting Problem*, Operations Research 52(4), 2004 — the idea
  that dynamic selection (fit the item to the gap, rather than following a fixed
  order) beats a fixed-order decoder.
- G. Schrimpf et al., *Record Breaking Optimization Results Using the Ruin and
  Recreate Principle*, J. Computational Physics 159, 1999 — ruin and recreate.
- E. K. Burke, Y. Bykov, *The Late Acceptance Hill-Climbing Heuristic* (2017) —
  the acceptance criterion, which is what lets the search cross worse solutions.
- Goal-driven ruin-and-recreate for 2D bin packing, as in the GDRR line of work
  — fixing a target bin count and minimising unplaced area, rather than
  optimising a general objective and hoping a bin empties.

The polygon engine is a bottom-left-fill in the style of Burke et al., *A New
Bottom-Left-Fill Heuristic Algorithm for the Two-Dimensional Irregular Packing
Problem*, Operations Research 54(3), 2006.
