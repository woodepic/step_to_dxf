"""Turn an arbitrary solid into a flat, cut-side-up Part.

The rule the CNC imposes: the sheet is never flipped, so every bit of material
that gets removed must be reachable from above.  Geometrically that means the
underside of the part is a single complete plane -- any downward-facing
horizontal face sitting above the bottom is an undercut, and undercuts are what
tell us the part is upside down.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
from OCP.TopoDS import TopoDS_Shape

from . import occ_utils as occ
from .part import Part, PartAnalysis, Pocket
from .profile import face_to_region, in_plane_alignment_angle
from .step_loader import LoadedSolid

# A face counts as horizontal when its normal is within ~0.6 deg of +/-Z.
NORMAL_TOL = 0.01
# Two Z levels closer than this are the same level (mm).
LEVEL_TOL = 1e-4
# Minimum plate aspect ratio (in-plane extent / thickness) to accept a solid.
MIN_PLATE_ASPECT = 1.5
# Faces below this area (mm^2) are ignored when picking the sheet axis.
MIN_FACE_AREA = 1e-6


@dataclass
class _Horiz:
    """A horizontal face: which way it looks and how high it sits."""

    z: float
    up: bool
    area: float
    face: object


def _axis_key(n: tuple[float, float, float]) -> tuple[float, float, float]:
    """Canonical direction ignoring sign, so +Z and -Z share a bucket."""
    x, y, z = n
    if z < -1e-9 or (abs(z) <= 1e-9 and (y < -1e-9 or (abs(y) <= 1e-9 and x < 0))):
        x, y, z = -x, -y, -z
    return (round(x, 6), round(y, 6), round(z, 6))


def _sheet_axis(shape: TopoDS_Shape) -> tuple[float, float, float] | None:
    """The plate's face normal: the planar direction carrying the most area."""
    totals: dict[tuple[float, float, float], float] = defaultdict(float)
    for face in occ.faces(shape):
        plane = occ.face_plane(face)
        if plane is None:
            continue
        area = occ.face_area(face)
        if area < MIN_FACE_AREA:
            continue
        totals[_axis_key(plane[0])] += area
    if not totals:
        return None
    return max(totals.items(), key=lambda kv: kv[1])[0]


def _horizontals(shape: TopoDS_Shape) -> list[_Horiz]:
    out: list[_Horiz] = []
    for face in occ.faces(shape):
        plane = occ.face_plane(face)
        if plane is None:
            continue
        n, pt = plane
        if abs(abs(n[2]) - 1.0) > NORMAL_TOL:
            continue
        out.append(_Horiz(z=pt[2], up=n[2] > 0, area=occ.face_area(face), face=face))
    return out


def _undercut_area(horizontals: list[_Horiz], z_bottom: float) -> float:
    """Total downward-facing area that does not sit on the bottom plane.

    Zero means the part can be cut without turning the sheet over.
    """
    return sum(h.area for h in horizontals if not h.up and abs(h.z - z_bottom) > LEVEL_TOL)


def _non_vertical_walls(shape: TopoDS_Shape) -> float:
    """Area of side geometry that is neither a vertical wall nor a vertical hole."""
    bad = 0.0
    for face in occ.faces(shape):
        surf = BRepAdaptor_Surface(face)
        kind = surf.GetType()
        if kind == GeomAbs_Plane:
            plane = occ.face_plane(face)
            if plane is None:
                continue
            nz = abs(plane[0][2])
            if nz > NORMAL_TOL and abs(nz - 1.0) > NORMAL_TOL:
                bad += occ.face_area(face)
        elif kind == GeomAbs_Cylinder:
            axis = surf.Cylinder().Axis().Direction()
            if abs(abs(axis.Z()) - 1.0) > NORMAL_TOL:
                bad += occ.face_area(face)
        else:
            bad += occ.face_area(face)
    return bad


def analyse(solid: LoadedSolid, label: str, *, part_id: str) -> PartAnalysis:
    """Flatten one solid into a Part, or explain why it cannot be nested."""
    messages: list[str] = []
    shape = occ.unify(solid.shape)

    axis = _sheet_axis(shape)
    if axis is None:
        return PartAnalysis(None, False, ("no planar faces; not a sheet part",),
                            solid.path, solid.index)

    aligned = occ.transform_shape(shape, occ.align_trsf(axis))
    xmin, ymin, zmin, xmax, ymax, zmax = occ.bbox(aligned)
    thickness = zmax - zmin
    in_plane = max(xmax - xmin, ymax - ymin)
    if thickness <= 0 or in_plane / thickness < MIN_PLATE_ASPECT:
        return PartAnalysis(
            None, False,
            (f"not plate-like (thickness {thickness:.2f} mm vs extent {in_plane:.2f} mm)",),
            solid.path, solid.index,
        )

    # Drop to z=0 and decide which way up.  Compare undercut area for the part
    # as-is against the part turned over; the machinable pose has none.
    aligned = occ.transform_shape(aligned, occ.translation(0, 0, -zmin))
    horiz = _horizontals(aligned)
    as_is = _undercut_area(horiz, 0.0)
    flipped_shape = occ.transform_shape(aligned, occ.rotation_x180())
    fz = occ.bbox(flipped_shape)[2]
    flipped_shape = occ.transform_shape(flipped_shape, occ.translation(0, 0, -fz))
    flipped_horiz = _horizontals(flipped_shape)
    as_flipped = _undercut_area(flipped_horiz, 0.0)

    flipped = False
    if as_is > LEVEL_TOL and as_flipped <= LEVEL_TOL:
        flipped = True
    elif as_is > LEVEL_TOL and as_flipped > LEVEL_TOL:
        # Cut from both sides: pick the pose needing less rework and say so.
        flipped = as_flipped < as_is
        worst = min(as_is, as_flipped)
        messages.append(
            f"has features on both faces ({worst:.0f} mm^2 unreachable from the top); "
            "this part cannot be finished without flipping the sheet"
        )

    if flipped:
        aligned = flipped_shape
        horiz = flipped_horiz

    bad_walls = _non_vertical_walls(aligned)
    if bad_walls > 1.0:
        messages.append(
            f"{bad_walls:.0f} mm^2 of non-vertical wall (chamfer/draft); "
            "the flat profile is the silhouette at the base"
        )

    # Take the thickness from the face planes, not the bounding box: OCC pads a
    # bbox by the shape tolerance, and this number becomes the through-cut depth.
    def _levels(hs: list[_Horiz]) -> tuple[float, float] | None:
        downs = [h.z for h in hs if not h.up]
        ups = [h.z for h in hs if h.up]
        if not downs or not ups:
            return None
        return min(downs), max(ups)

    levels = _levels(horiz)
    if levels is None:
        return PartAnalysis(None, False, ("no flat underside found",), solid.path, solid.index)
    z_bottom, z_top = levels
    thickness = z_top - z_bottom
    level_tol = max(LEVEL_TOL, thickness * 1e-3)

    # Rotate about Z so the part's minimum bounding rectangle is axis aligned;
    # parts arrive at whatever yaw the assembly gave them.
    bottoms = [h for h in horiz if not h.up and abs(h.z - z_bottom) <= level_tol]
    if not bottoms:
        return PartAnalysis(None, False, ("no flat underside found",), solid.path, solid.index)

    yaw = in_plane_alignment_angle([b.face for b in bottoms])
    if abs(yaw) > 1e-9:
        aligned = occ.transform_shape(aligned, occ.rotation_z(yaw))
        horiz = _horizontals(aligned)
        levels = _levels(horiz)
        if levels is None:
            return PartAnalysis(None, False, ("no flat underside found",), solid.path, solid.index)
        z_bottom, z_top = levels
        thickness = z_top - z_bottom
        level_tol = max(LEVEL_TOL, thickness * 1e-3)
        bottoms = [h for h in horiz if not h.up and abs(h.z - z_bottom) <= level_tol]

    dx = dy = 0.0
    bottom_regions = [face_to_region(b.face, dx, dy) for b in bottoms]
    bottom_regions = [r for r in bottom_regions if r is not None]
    if not bottom_regions:
        return PartAnalysis(None, False, ("underside could not be converted to 2D",),
                            solid.path, solid.index)

    if len(bottom_regions) == 1:
        profile = bottom_regions[0]
    else:
        from .geom2d import polygon_to_regions, regions_to_multipolygon

        merged = polygon_to_regions(regions_to_multipolygon(bottom_regions))
        if len(merged) != 1:
            messages.append(
                f"underside is {len(merged)} disconnected islands; nesting the largest only"
            )
        profile = max(merged, key=lambda r: r.area())

    # Every upward face below the top surface is a pocket floor.
    pockets: list[Pocket] = []
    for h in horiz:
        if not h.up:
            continue
        depth = z_top - h.z
        if depth <= level_tol:
            continue  # this is the top surface itself
        if depth >= thickness - level_tol:
            continue  # coincident with the underside; already a through cut
        region = face_to_region(h.face, dx, dy)
        if region is None:
            continue
        pockets.append(Pocket(depth=depth, region=region))

    pockets.sort(key=lambda p: p.depth)

    # Finally slide everything so the outline's bounding box starts at (0, 0).
    ox, oy, _, _ = profile.bounds()
    if abs(ox) > 1e-12 or abs(oy) > 1e-12:
        profile = profile.transformed(0.0, -ox, -oy)
        pockets = [Pocket(pk.depth, pk.region.transformed(0.0, -ox, -oy)) for pk in pockets]

    part = Part(
        id=part_id,
        label=label,
        path=solid.path,
        thickness=thickness,
        profile=profile,
        pockets=tuple(pockets),
        warnings=tuple(messages),
        flipped=flipped,
        source_index=solid.index,
    )
    return PartAnalysis(part, True, tuple(messages), solid.path, solid.index)
