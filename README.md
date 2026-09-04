# plynest

Turn a STEP assembly of plywood parts into nested 4×8 sheets and CNC-ready DXF.

Point it at an assembly, and it works out which face of each part has to be
uppermost, flattens the part to a 2D profile with a layer per cut depth, nests
everything onto sheets of the right stock thickness, engraves each part's name
somewhere the router can actually reach, and writes the DXF.

```
STEP assembly ──▶ orient & flatten ──▶ label ──▶ nest ──▶ DXF
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

Bottom-left fill over true outlines, not bounding boxes — an L-shaped part lets
a neighbour tuck into its notch. Candidate positions come from the edges of
already-placed parts, which is where the contacts in an optimal packing always
are.

Three things lift it from "works" to "near optimal":

- several part orderings, each tried in two scan directions;
- a **consolidation pass** that tries to empty the least-used sheet into the
  others — this is what removes the half-empty sheet first-fit always leaves;
- exact clearance as a distance test, so parts can genuinely butt up at one kerf.

Parts of different thickness never share a sheet; they are different stock.

**Kerf is spacing, not an offset.** Exported outlines are true part size and the
gap between neighbours is guaranteed to be at least the kerf, so your CAM
applies the tool offset as usual. Edge keep-out is the border left free for
hold-down bolts and clamps.

On the sample assembly the ½″ group packs to 5 sheets averaging 83%. The ¾″
group also takes 5: its panels are 693 mm wide on a 1168 mm usable width, so
they can only sit one per row, and 5 is essentially the floor.

---

## Labels

Part names are engraved with a **built-in single-stroke font**. An outline font
would force the router to V-carve or pocket the counter of every letter; a
single-stroke font is one pass of the bit down the centre of each stroke, which
is what a ¼″ part label wants.

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

One layer per cut depth, so each depth can be a separate toolpath:

| Layer | Contents |
|---|---|
| `CUT_THROUGH_0p75` | outlines and through holes, cut to full thickness |
| `POCKET_0p25` | pocket floors at 0.25″ deep |
| `ENGRAVE_0p04` | label strokes |
| `SHEET_OUTLINE`, `EDGE_KEEPOUT` | reference only |

Three file layouts:

- **One DXF per sheet** — every depth on its own layer (default)
- **One DXF per sheet, per depth** — one file per toolpath
- **One DXF for everything** — all sheets side by side in a single file

Closed profiles are written as single closed `LWPOLYLINE`s carrying bulge
factors, so arcs survive into CAM. Units are inches or millimetres, with
`$INSUNITS` set to match. The export zip also contains a plain-text layout
report listing every part, its size, its rotation and whether it was flipped.

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
             [--rotation {none,180,90,free}] [--attempts N]
             [--mode {per_sheet,per_depth,single_file}]
             [--no-labels] [--label-height H] [--label-depth D]
             [--label-corner ...] [--label-style ...]
```

All lengths are in whatever `--unit` says. Exit status is non-zero if any part
could not be placed.

---

## Tests

```bash
./venv/bin/python -m pytest        # 119 tests, ~8 s
```

The suite covers geometry transforms and exact arc maths, font coverage,
orientation and flattening against synthetic solids of known size, label
placement, DXF round-trips, and nesting invariants. The checks that matter most
for trusting a cut file:

- every solid in the STEP file becomes a part, and every part reaches a sheet
  **exactly once**;
- each placed part still has its **true dimensions and area**;
- **volume is conserved** from the STEP solid all the way to the 2D data;
- no two parts overlap, and every gap is at least the kerf;
- everything is inside the edge keep-out, and no sheet mixes stock thickness;
- no label crosses a pocket or leaves its part;
- exporting and **re-reading the DXF** reproduces every part at the right size
  and position.

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
  font.py          built-in single-stroke engraving font
  labels.py        where a label can legally go
  nest.py          the packer
  dxf_export.py    DXF writing
  pipeline.py      end to end
  cli.py           command line
  web/             FastAPI back end + browser UI
```

## Requirements

Python 3.10+, and `cadquery-ocp` (OpenCASCADE), `ezdxf`, `shapely`, `numpy`,
`fastapi`. Everything installs from PyPI; no conda needed.
