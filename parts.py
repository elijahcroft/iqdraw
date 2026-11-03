"""
The VEX IQ (2nd generation) part catalogue.

Parts are named, not enumerated: `get("beam_1x8")`, `get("gear_36")`,
`get("plate_4x8")`.  Sizes are parsed out of the name, so any beam or plate
length works without touching this file.

Local frames
------------
Every part's origin is its FIRST HOLE, and its holes sit on integer
coordinates from there.  That is what lets a build spec put a pin and the hole
it goes through at the same address.

  beam_1x8   at (0,0,0) -> holes (0,0,0) .. (7,0,0), lying in the xy plane
  beam_2x12  at (0,0,0) -> holes (0..11, 0..1, 0)
  shaft_6    at (0,0,0) -> runs from -0.5 to 5.5 along its axis
  standoff_2 at (0,0,0) -> runs from 0 to 2 along its axis (sits ON a face)

Rotate at placement time with `rot: [rx, ry, rz]` (degrees, applied X then Y
then Z), or use `axis:` on the parts that take one.
"""

from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass

try:
    # High-detail meshes are deliberately optional.  The open-source package
    # ships its own procedural geometry; a local cadmesh.py can add meshes
    # only when its user has the right to use and redistribute that data.
    from .cadmesh import cad_mesh, gear_mesh
    HAS_CAD_MESHES = True
except ImportError:
    HAS_CAD_MESHES = False

    def cad_mesh(_key, _color):
        return None

    def gear_mesh(_key, _color):
        return None
from .geom import (
    Disc, Facet, Transform, along, attach, box, circle_profile, cylinder,
    euler, extrude, gear_profile, mix_color, moved, rounded_rect, scale_color,
)

# ============================================================================
# CONSTANTS
#
# MEASURED - these come from VEX's published documentation:
PITCH_MM = 12.7          # hole pitch, 0.5"; every part is an integer multiple
SHAFT_W = 3.18 / PITCH_MM  # 3.18 mm square drive shaft == exactly 1/4 pitch
#
# ESTIMATED - these are visual approximations chosen to look right on the page,
# not verified against a caliper.  They are safe to tune; nothing else in the
# renderer depends on their exact values.
BEAM_T = 0.50            # beam thickness, in pitch
PLATE_T = 0.25           # plate thickness
HOLE_R = 0.25            # hole radius
PIN_R = 0.19             # connector-pin radius
STANDOFF_W = 0.46        # standoff across the flats
CORNER_R = 0.50          # the rounded end of a beam == half a pitch
EDGE_BEVEL = 0.055       # molded chamfer around structural-part faces
HOLE_BEVEL = 0.055       # countersink around each structural hole
#
# Molded face relief.  An injection-molded VEX face is not one plane: a
# perimeter rim and a raised pad around every hole stand proud of a general
# face, and the material between the holes is recessed below it.  Measured
# from the mid-plane of a 0.50-pitch beam those three levels sit at 0.24,
# 0.18 and 0.079, which is what these fractions of the half-thickness come
# to.  Fractions rather than absolute depths so a 0.25-thick plate gets the
# same relief in proportion instead of one deeper than the plate itself.
RIM_LEVEL = 0.96         # perimeter rim, and the pad around each hole
FACE_LEVEL = 0.72        # the general face between those features
POCKET_LEVEL = 0.316     # the pockets recessed between the holes
RIM_W = 0.06             # width of the flat perimeter rim
RIM_DRAFT = 0.025        # horizontal run of the wall under the rim
# Where each face level starts, as a fraction of the distance from the pad
# around a hole out to the edge of that hole's cell.  Fractions again, so a
# cell squeezed narrow by the rim keeps every level rather than losing the
# ones that no longer fit.
PAD_S = 0.14             # pad wall gives way to the general face
FACE_S = 0.58            # general face gives way to the pocket
#
# Gear face relief, measured from the gear's mid-plane: the toothed rim and
# the hub stand at the full half-thickness, the spokes between neighbouring
# lightening holes at 0.18, and the web the holes are cut through at 0.079.
GEAR_T = 0.50            # gear thickness
GEAR_SPOKE_Z = 0.18      # top of the spokes between lightening holes
GEAR_WEB_Z = 0.079       # the recessed web between rim and hub
GEAR_RIM_W = 0.16        # flat of the toothed rim inside the tooth roots
GEAR_RAYS = 12           # spokes each hole's web cell is sampled on
# ============================================================================

# Colours.  These follow the VEX IQ (2nd gen) *base* colours that ship in the
# Starter and Super Kits, so a rendered step matches what a student pulls out
# of the tray.  Every plastic family is also sold in alternate colours - a
# placement can override any of them with `color:`.
#
#   beams, plates       black           (1x/2x Beam Base Pack, 4x Plate Base Pack)
#   corner connectors   black           (Corner Connector Base Pack 228-3513)
#   connector pins      blue            (Connector Pin Pack 228-3058)
#   standoffs           black           (Standoff Base Pack 228-3514)
#   metal shafts        zinc-plated steel (Shaft Base Pack 228-3506)
#   plastic shafts      black           (Plastic Shaft Base Pack 228-3620)
#   gears               blue            (Gear Base Pack 228-3502)
#   sprockets + chain   orange          (the colour most kits carry)
#   tyres               black rubber, on a light grey hub
#   shaft collars       black rubber
#   brain, motors, sensors   dark charcoal
#
# The hex values themselves are eyeballed from product photography, not
# sampled from plastic; the *assignment* above is what matters, and it is
# sourced.  Check them against your own kit - VEX has changed plastic colours
# between production runs, and a wrong colour actively misleads a student.
PALETTE = {
    "white": "#eef0f3",      # white-variant packs
    "steel": "#b9bfc7",      # zinc-plated steel shafts
    "grey": "#9ba2ac",       # wheel hubs
    "vexgrey": "#6b7079",    # optional grey structural variant
    "dgrey": "#4d535c",      # electronics housings
    "black": "#2b2f35",      # corner connectors, standoffs, tyres, collars
    "green": "#46a63f",
    "blue": "#087fc7",       # gears, connector pins
    "orange": "#f07d18",     # sprockets and chain
    "red": "#d43f37",
    "yellow": "#f2c318",
    "purple": "#7c5ac0",
    "screen": "#2b5f86",
}


def color_of(name):
    return PALETTE.get(name, name)


# Turns a part built flat in the xy plane to face the camera square-on.  Lying
# flat, a gear projects to a squashed ellipse and you cannot count its teeth;
# face-on it is unmistakable, which is the whole job of a parts callout.
FACE_CAMERA = (-54.74, 0.0, -45.0)


@dataclass
class Part:
    name: str
    label: str
    color: str
    prims: list
    holes: tuple = ()
    # Rotation used when the part is drawn alone in a step's parts callout.
    icon_rot: tuple = (0.0, 0.0, 0.0)


# ------------------------------------------------------------------ internals


# Boundary points per hole cell, which is also the hole's own polygon count.
# Must be a multiple of 8: cells are sampled on evenly spaced rays from their
# hole, and a cell corner has to fall on one of those rays or the four cells
# meeting there each chord it off and leave a gap.  16 is what stops a hole
# reading as a socket rather than a hole; 24 rounds it further and widens the
# pockets, at roughly another 40% on a booklet for a difference that does not
# survive being printed at a booklet's 38px per hole.
CELL_PTS = 16


def _cell_ring(cell, cx, cy, n):
    """`cell`'s outline sampled on `n` evenly spaced rays from (cx, cy).

    Sampling by angle rather than along the outline is what lets two
    neighbouring cells agree, point for point, on the boundary they share:
    the angle set is symmetric, so the ray from one hole and the ray from the
    next land on the same spot of the edge between them.  Cells that
    disagreed there would crack open as soon as the two sides of that edge
    sat at different heights, which is exactly what a rib does to it.

    It also puts the ring on the same angles as `circle_profile`, so the pad
    around a hole meets its counterbore with no seam.

    Corners the rays happen to miss are kept as well: a chord across one
    would cut the cell short of its neighbour and open a gap in the face.
    """
    found = []
    m = len(cell)
    for k in range(n):
        a = 2 * math.pi * k / n
        dx, dy = math.cos(a), math.sin(a)
        for e in range(m):
            x0, y0 = cell[e]
            ex = cell[(e + 1) % m][0] - x0
            ey = cell[(e + 1) % m][1] - y0
            den = dx * ey - dy * ex
            if abs(den) < 1e-12:
                continue
            t = ((x0 - cx) * ey - (y0 - cy) * ex) / den
            u = ((x0 - cx) * dy - (y0 - cy) * dx) / den
            if t > 0.0 and -1e-9 <= u <= 1.0 + 1e-9:
                found.append((a, (cx + dx * t, cy + dy * t)))
                break
    for x, y in cell:
        found.append((math.atan2(y - cy, x - cx) % (2 * math.pi), (x, y)))
    found.sort(key=lambda p: p[0])
    out = []
    for a, pt in found:
        if not out or a - out[-1][0] > 1e-9:
            out.append((a, pt))
    return [pt for _a, pt in out]


def _rib_spokes(ring, i, j, drilled):
    """Which points of cell (i, j)'s ring carry a rib to a neighbouring hole.

    A real part does not ring each hole with a moat: the pads are joined to
    their neighbours by ribs at the level of the general face, and it is the
    gaps left between those ribs that are recessed.  A rib runs one spoke
    either side of the line between the two holes it joins - the narrowest
    that still gives it a flat top rather than a single ridge line.
    """
    span = 2 * math.pi / CELL_PTS + 1e-9
    axes = [(1, 0, 0.0), (0, 1, math.pi / 2),
            (-1, 0, math.pi), (0, -1, 3 * math.pi / 2)]
    out = []
    for x, y in ring:
        a = math.atan2(y - j, x - i)
        out.append(any(
            (i + di, j + dj) in drilled
            and abs((a - axis + math.pi) % (2 * math.pi) - math.pi) <= span
            for di, dj, axis in axes))
    return out


def _loft_ring(lower, upper, z0, z1, color, inward=False):
    """Join two equal-length profiles with a band of shaded quadrilaterals.

    Each height is either one value for the whole ring or one value per
    point, for a band that has to rise and fall as it goes round.
    """
    out = []
    n = len(lower)
    za = z0 if isinstance(z0, list) else [z0] * n
    zb = z1 if isinstance(z1, list) else [z1] * n
    for k in range(n):
        m = (k + 1) % n
        a0 = (*lower[k], za[k])
        b0 = (*lower[m], za[m])
        b1 = (*upper[m], zb[m])
        a1 = (*upper[k], zb[k])
        pts = [a0, b0, b1, a1]
        if inward:
            pts.reverse()
        out.append(Facet(pts, color))
    return out


def _hole_chamfer(ring, cx, cy, outer_r, inner_r, z_face, z_bore, up, color):
    """The small conical lead-in molded around a VEX structural hole.

    Cut on `ring`'s spokes, so it lands on the pad around the hole point for
    point instead of leaving a seam the width of one chord.
    """
    outer = _pad_ring(ring, cx, cy, outer_r)
    inner = _pad_ring(ring, cx, cy, inner_r)
    if up > 0:
        return _loft_ring(outer, inner, z_face, z_bore, color, inward=True)
    return _loft_ring(inner, outer, z_bore, z_face, color, inward=True)


def _cell_profile(i, j, w, length, inset):
    """A hole cell with only the part's exposed perimeter inset for beveling."""
    x0 = i - 0.5 + (inset if i == 0 else 0.0)
    x1 = i + 0.5 - (inset if i == length - 1 else 0.0)
    y0 = j - 0.5 + (inset if j == 0 else 0.0)
    y1 = j + 0.5 - (inset if j == w - 1 else 0.0)
    r = max(0.0, CORNER_R - inset)
    radii = (
        r if i == 0 and j == 0 else 0.0,
        r if i == length - 1 and j == 0 else 0.0,
        r if i == length - 1 and j == w - 1 else 0.0,
        r if i == 0 and j == w - 1 else 0.0,
    )
    return rounded_rect(x0, y0, x1, y1, radii, CELL_PTS // 4)


def _split_runs(outlines, cell=1.0):
    """Cut every side longer than `cell` into equal pieces, the same way in
    each of several concentric outlines so they still loft point for point.

    A beam's rim is otherwise one strip down each long side, sorting by the
    middle of the beam - so it paints across a gear sitting over one end.
    """
    first = outlines[0]
    n = len(first)
    counts = [max(1, math.ceil(math.dist(first[k], first[(k + 1) % n])
                               / cell - 1e-9)) for k in range(n)]
    out = []
    for prof in outlines:
        pts = []
        for k in range(n):
            (ax, ay), (bx, by) = prof[k], prof[(k + 1) % n]
            m = counts[k]
            pts += [(ax + (bx - ax) * s / m, ay + (by - ay) * s / m)
                    for s in range(m)]
        out.append(pts)
    return out


def _blend(inner, outer, s):
    """A profile `s` of the way out from `inner` to `outer`, point for point."""
    return [(a[0] + (b[0] - a[0]) * s, a[1] + (b[1] - a[1]) * s)
            for a, b in zip(inner, outer)]


def _pad_ring(profile, cx, cy, r):
    """A circle of radius `r`, sampled along `profile`'s radial directions.

    Every ring of a hole cell is cut on the same spokes, so the pad around
    the hole meets the counterbore that lands on it point for point.
    """
    out = []
    for x, y in profile:
        a = math.atan2(y - cy, x - cx)
        out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return out


def _relief_step(inner, outer, z_in, z_out, up, color):
    """One step of face relief: the band between two concentric rings.

    A hole has to be a real void, not a dark circle painted on a solid face.
    Under a depth sort, a solid face covering the hole would be one facet
    centred on the hole itself, and anything pushed through that hole - a
    pin, a shaft - sits nearer the camera than that centre and gets drawn on
    top of the beam it is buried in.  Ringing the void with bands puts real
    geometry on the near side of the hole, which is what hides the buried
    shaft, and it is why a face is built out of these rather than out of two
    big polygons.

    Wound so the band faces away from the mid-plane on whichever side `up`
    names, which is what carries it through the back-face cull.
    """
    def flip(z):
        return [-v for v in z] if isinstance(z, list) else -z

    if up > 0:
        return _loft_ring(outer, inner, z_out, z_in, color)
    return _loft_ring(inner, outer, flip(z_in), flip(z_out), color)


def _sink_color(band, deep, color):
    """Recolour the quads of `band` that lie wholly on the pocket floor.

    The sunk walls shade themselves off their own normals, but a pocket floor
    is parallel to the face above it and would otherwise be the same grey -
    and a booklet has to survive black-and-white printing.
    """
    for quad in band:
        if all(abs(abs(q[2]) - deep) < 1e-9 for q in quad.pts):
            quad.color = color
    return band


def _flat(w, length, t, color, holes=None):
    """
    A beam/plate slab: `length` holes along +x, `w` holes along +y, lying in
    the xy plane with its mid-plane at z=0 and hole (0,0) at the origin.

    Faces are emitted per hole cell rather than as two big polygons, which
    keeps the depth sort fine-grained: a standoff at the far end of a long
    beam never gets painted over by the beam it stands on.
    """
    x0, y0 = -0.5, -0.5
    x1, y1 = length - 0.5, w - 0.5
    drilled = set(holes) if holes is not None else {
        (i, j) for i in range(length) for j in range(w)
    }
    bore = mix_color(color, "#1b1f27", 0.66)

    # Every outline here is cut on the same angular grid the hole cells are
    # sampled on, so a cell's rounded end lands exactly on the rim that runs
    # past it.
    arc = CELL_PTS // 4
    outer = rounded_rect(x0, y0, x1, y1, (CORNER_R,) * 4, arc)
    inset = rounded_rect(
        x0 + EDGE_BEVEL, y0 + EDGE_BEVEL,
        x1 - EDGE_BEVEL, y1 - EDGE_BEVEL,
        (CORNER_R - EDGE_BEVEL,) * 4, arc,
    )
    brink = rounded_rect(
        x0 + EDGE_BEVEL + RIM_W, y0 + EDGE_BEVEL + RIM_W,
        x1 - EDGE_BEVEL - RIM_W, y1 - EDGE_BEVEL - RIM_W,
        (CORNER_R - EDGE_BEVEL - RIM_W,) * 4, arc,
    )
    sill_in = EDGE_BEVEL + RIM_W + RIM_DRAFT
    sill = rounded_rect(
        x0 + sill_in, y0 + sill_in, x1 - sill_in, y1 - sill_in,
        (CORNER_R - sill_in,) * 4, arc,
    )
    outer, inset, brink, sill = _split_runs([outer, inset, brink, sill])
    face = t / 2
    shoulder = face - EDGE_BEVEL
    rim_z = face * RIM_LEVEL
    gen_z = face * FACE_LEVEL
    pocket_z = face * POCKET_LEVEL
    bevel_c = mix_color(color, "#ffffff", 0.09)
    # Recessed surfaces are darkened as well as sunk.  The sunk walls shade
    # themselves off their own normals, but a pocket floor is parallel to the
    # face above it and would otherwise be the same grey - and a booklet has
    # to survive black-and-white printing, where colour carries nothing.
    recess_c = mix_color(color, "#11151b", 0.24)

    # A VEX beam is injection molded, not a square-edged slab.  Keep the
    # vertical wall slightly inboard of each face and bridge it with a narrow
    # chamfer.  The highlight catches like a real CAD model without relying on
    # SVG gradients or a particular output resolution.
    prims = extrude(
        outer, -shoulder, shoulder, color,
        cap_top=False, cap_bottom=False, rim_top=True, rim_bottom=True,
    )
    prims += _loft_ring(outer, inset, shoulder, rim_z, bevel_c)
    prims += _loft_ring(inset, outer, -rim_z, -shoulder, color)

    # The rim runs right round the part at the highest level of the face, and
    # drops from there to the pocket floor the hole cells are bounded by.
    # Drawing it once around the whole outline, rather than as the outer edge
    # of every cell, keeps the level along a shared cell boundary constant -
    # cells resample their outlines independently, and a boundary whose height
    # varied would crack open wherever two cells disagreed about where to
    # sample it.
    for up in (1, -1):
        prims += _relief_step(brink, inset, rim_z, rim_z, up, color)
        prims += _relief_step(sill, brink, pocket_z, rim_z, up, recess_c)

    # The pitch marks/notches along a genuine IQ beam's side are visible even
    # in VEX's simplified parts poster.  Subtle recessed rectangles make a
    # long black beam readable as molded IQ structure instead of a plain bar.
    groove_c = mix_color(color, "#11151b", 0.58)
    notch_w = 0.13
    notch_z = min(t * 0.27, 0.12)
    for i in range(length - 1):
        x = i + 0.5
        prims.append(Facet(
            [(x - notch_w, y1 + 0.002, -notch_z),
             (x + notch_w, y1 + 0.002, -notch_z),
             (x + notch_w, y1 + 0.002, notch_z),
             (x - notch_w, y1 + 0.002, notch_z)],
            groove_c, (0.0, 1.0, 0.0)))
        prims.append(Facet(
            [(x + notch_w, y0 - 0.002, -notch_z),
             (x - notch_w, y0 - 0.002, -notch_z),
             (x - notch_w, y0 - 0.002, notch_z),
             (x + notch_w, y0 - 0.002, notch_z)],
            groove_c, (0.0, -1.0, 0.0)))
    for j in range(w - 1):
        y = j + 0.5
        prims.append(Facet(
            [(x1 + 0.002, y + notch_w, -notch_z),
             (x1 + 0.002, y - notch_w, -notch_z),
             (x1 + 0.002, y - notch_w, notch_z),
             (x1 + 0.002, y + notch_w, notch_z)],
            groove_c, (1.0, 0.0, 0.0)))
        prims.append(Facet(
            [(x0 - 0.002, y - notch_w, -notch_z),
             (x0 - 0.002, y + notch_w, -notch_z),
             (x0 - 0.002, y + notch_w, notch_z),
             (x0 - 0.002, y - notch_w, notch_z)],
            groove_c, (-1.0, 0.0, 0.0)))

    for i in range(length):
        for j in range(w):
            cell = _cell_profile(i, j, w, length, sill_in)

            if (i, j) not in drilled:
                # A blank cell has no pad to build the relief around, so it
                # stays flat - at the pocket floor, which is the level every
                # cell meets its neighbours and the rim at.
                prims.append(Facet([(x, y, pocket_z) for x, y in cell],
                                   recess_c, (0.0, 0.0, 1.0)))
                prims.append(Facet([(x, y, -pocket_z) for x, y in
                                    reversed(cell)],
                                   recess_c, (0.0, 0.0, -1.0)))
                continue

            ring = _cell_ring(cell, i, j, CELL_PTS)
            mouth_r = HOLE_R + HOLE_BEVEL
            # Three steps out from the hole: the wall of the pad the
            # counterbore lands on, then the general face, then the cell's
            # own edge.  How high that last step lands depends on the spoke -
            # a rib carries the general face straight over to the next hole,
            # and what is left between the ribs drops to the pocket floor.
            # Every ring is cut on the cell's own spokes, so a cell the rim
            # has squeezed narrow keeps all three levels rather than losing
            # the ones that no longer fit.
            pad = _pad_ring(ring, i, j, mouth_r)
            shelf = _blend(pad, ring, PAD_S)
            lip = _blend(pad, ring, FACE_S)
            step_z = [gen_z if rib else pocket_z
                      for rib in _rib_spokes(ring, i, j, drilled)]
            for up in (1, -1):
                prims += _relief_step(pad, shelf, rim_z, gen_z, up, color)
                prims += _relief_step(shelf, lip, gen_z, step_z, up, color)
                prims += _sink_color(
                    _relief_step(lip, ring, step_z, step_z, up, color),
                    pocket_z, recess_c)
            prims += _hole_chamfer(ring, i, j, mouth_r, HOLE_R, rim_z,
                                   shoulder, +1, bevel_c)
            prims += _hole_chamfer(ring, i, j, mouth_r, HOLE_R, -rim_z,
                                   -shoulder, -1, color)
            # Looking down a hole at this angle you see its far inner wall, so
            # the bore needs an inward-facing cylinder - a dark disc at the
            # bottom projects below the opening and never lines up with it.
            # Reversing the profile flips the wall normals to point inward.
            disc = _pad_ring(ring, i, j, HOLE_R)
            prims += extrude(list(reversed(disc)), -shoulder, shoulder, bore,
                             cap_top=False, cap_bottom=False, edges=False,
                             zcell=t)  # too short to need banding
            prims.append(Facet([(x, y, -shoulder) for x, y in disc], bore,
                               (0.0, 0.0, 1.0)))
    return prims, tuple(sorted(drilled))


def _painted_hole(x, y, z, up, base):
    """
    A hole drawn ON a solid face, rather than cut through it as a void.

    Only for faces nothing is ever pushed through - a motor's mounting holes.
    Structural parts must use the void in `_flat`, or shafts pushed through
    them will sort in front of the face that should be hiding them.
    """
    n = (0.0, 0.0, float(up))
    u = (1.0, 0.0, 0.0)
    v = (0.0, float(up), 0.0)
    return [
        Disc((x, y, z), u, v, HOLE_R * 1.34, scale_color(base, 0.93), n,
             stroke=False),
        Disc((x, y, z), u, v, HOLE_R, mix_color(base, "#1b1f27", 0.66), n,
             stroke=True),
    ]


def _annular_cylinder(outer_r, inner_r, z0, z1, color, segments=36):
    """A hollow cylinder with real front and rear annular faces."""
    outer = circle_profile(outer_r, segments)
    inner = circle_profile(inner_r, segments)
    p = extrude(outer, z0, z1, color, cap_top=False, cap_bottom=False,
                rim_top=True, rim_bottom=True)
    # Reversing the inner profile points its wall normals into the opening.
    p += extrude(list(reversed(inner)), z0, z1, color,
                 cap_top=False, cap_bottom=False,
                 rim_top=True, rim_bottom=True)
    for i in range(segments):
        j = (i + 1) % segments
        top = [(*outer[i], z1), (*outer[j], z1),
               (*inner[j], z1), (*inner[i], z1)]
        bottom = [(*inner[i], z0), (*inner[j], z0),
                  (*outer[j], z0), (*outer[i], z0)]
        p.append(Facet(top, color, (0.0, 0.0, 1.0)))
        p.append(Facet(bottom, color, (0.0, 0.0, -1.0)))
    return p


def _wheel_tread(r, width, color, count=24):
    """Staggered diagonal rubber lugs on a travel tire's circumference."""
    tread_c = mix_color(color, "#080a0d", 0.34)
    p = []
    da = math.pi / count * 0.48
    gap = width * 0.08
    for i in range(count):
        a = 2 * math.pi * i / count
        # Opposing slants form the shallow chevron pattern on the real tire.
        for z0, z1, slant in ((-width / 2 + gap, -gap, +1),
                              (gap, width / 2 - gap, -1)):
            angles = (a - da, a + da, a + da + slant * da,
                      a - da + slant * da)
            pts = [
                (r * math.cos(angles[0]), r * math.sin(angles[0]), z0),
                (r * math.cos(angles[1]), r * math.sin(angles[1]), z0),
                (r * math.cos(angles[2]), r * math.sin(angles[2]), z1),
                (r * math.cos(angles[3]), r * math.sin(angles[3]), z1),
            ]
            p.append(Facet(pts, tread_c,
                           (math.cos(a), math.sin(a), 0.0), shade=0.72))
    return p


def _square_bar(across, z0, z1, color, corner=0.06):
    prof = rounded_rect(-across / 2, -across / 2, across / 2, across / 2,
                        (corner,) * 4)
    return extrude(prof, z0, z1, color)


def _gear_holes(teeth):
    """Official VEX spur-gear lightening-hole layouts, in pitch units."""
    if teeth == 36:
        return [
            (0.80 * math.cos(math.radians(a)),
             0.80 * math.sin(math.radians(a)))
            for a in range(0, 360, 45)
        ]
    if teeth == 48:
        # The 48T face uses a staggered 3-2-2-2-3 arrangement.
        return [
            (-1.0, -1.0), (0.0, -1.0), (1.0, -1.0),
            (-0.5, -0.5), (0.5, -0.5),
            (-1.0, 0.0), (1.0, 0.0),
            (-0.5, 0.5), (0.5, 0.5),
            (-1.0, 1.0), (0.0, 1.0), (1.0, 1.0),
        ]
    if teeth >= 60:
        holes = []
        for radius, offset in ((0.88, 0.0), (1.78, 0.0)):
            holes += [
                (radius * math.cos(math.radians(a + offset)),
                 radius * math.sin(math.radians(a + offset)))
                for a in range(0, 360, 45)
            ]
        return holes
    return []


def _gear_slots(teeth):
    """The tangential molded slots of the classic VEX IQ 60T gear.

    Each sits midway between an inner and an outer lightening hole, so the
    web keeps an even margin round all three.
    """
    if teeth < 60:
        return []
    length, width, radius = 0.72, 0.13, 1.33
    prof = rounded_rect(-length / 2, -width / 2, length / 2, width / 2,
                        (width / 2,) * 4, segments=4)
    out = []
    for angle in (45, 135, 225, 315):
        tf = Transform(euler(rz=angle + 90),
                       (radius * math.cos(math.radians(angle)),
                        radius * math.sin(math.radians(angle)), 0.0))
        pts = [tf.point((x, y, 0.0)) for x, y in prof]
        out.append((tf.pos[0], tf.pos[1], [(x, y) for x, y, _ in pts]))
    return out


def _clip(poly, a, b, c, label):
    """The part of convex polygon `poly` where a*x + b*y <= c.

    `poly` is a list of (point, label) pairs, the label naming what the side
    leaving that point was cut by, so a cell remembers which neighbour each
    of its sides is shared with.
    """
    out = []
    n = len(poly)
    for k in range(n):
        p, lab = poly[k]
        q = poly[(k + 1) % n][0]
        dp = a * p[0] + b * p[1] - c
        dq = a * q[0] + b * q[1] - c
        if abs(dp) < 1e-12:
            dp = 0.0
        if abs(dq) < 1e-12:
            dq = 0.0
        x = None
        if (dp < 0 < dq) or (dq < 0 < dp):
            t = dp / (dp - dq)
            x = (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)
        if dp <= 0:
            if dq > 0:
                out.append((p, lab) if x else (p, label))
                if x:
                    out.append((x, label))
            else:
                out.append((p, lab))
        elif dq < 0:
            out.append((x, lab))
    # A cut through a corner leaves a zero-length side behind.
    return [(p, lab) for k, (p, lab) in enumerate(out)
            if math.dist(p, out[(k + 1) % len(out)][0]) > 1e-9]


def _power_cells(sites, boundary):
    """Split convex `boundary` into one cell per (x, y, r) site.

    A power diagram rather than plain nearest-centre cells: weighting by
    radius moves each shared side out of the bigger feature's way, so a hub
    and the lightening hole beside it both keep a margin of web.  Sides on
    `boundary` itself are labelled None, the rest by the neighbouring site.
    """
    cells = []
    for i, (x, y, r) in enumerate(sites):
        poly = [(p, None) for p in boundary]
        for j, (u, v, s) in enumerate(sites):
            if j != i:
                poly = _clip(poly, 2 * (u - x), 2 * (v - y),
                             (u * u + v * v - s * s) - (x * x + y * y - r * r),
                             j)
        cells.append(poly)
    return cells


def _ray_hit(poly, cx, cy, a):
    """(distance, side index) where the ray from (cx, cy) at `a` leaves
    convex `poly`."""
    dx, dy = math.cos(a), math.sin(a)
    best = None
    m = len(poly)
    for e in range(m):
        x0, y0 = poly[e]
        ex = poly[(e + 1) % m][0] - x0
        ey = poly[(e + 1) % m][1] - y0
        den = dx * ey - dy * ex
        if abs(den) < 1e-12:
            continue
        t = ((x0 - cx) * ey - (y0 - cy) * ex) / den
        u = ((x0 - cx) * dy - (y0 - cy) * dx) / den
        if t > 0.0 and -1e-9 <= u <= 1.0 + 1e-9 and (best is None
                                                     or t < best[0]):
            best = (t, e)
    return best


def _cell_rays(cell, cx, cy, n):
    """Spoke angles for a cell: `n` even rays from its site plus one to each
    corner, each with the cell point it lands on and the neighbours that
    point is shared with.

    A ray to every corner is what lets two cells agree on the side between
    them - both contain its two ends, so neither cuts across the other.
    """
    pts = [p for p, _lab in cell]
    out = []
    for k, (p, lab) in enumerate(cell):
        out.append((math.atan2(p[1] - cy, p[0] - cx) % (2 * math.pi), p,
                    {cell[k - 1][1], lab}))
    corners = [a for a, _p, _l in out]
    for k in range(n):
        a = 2 * math.pi * k / n
        if any(abs((a - c + math.pi) % (2 * math.pi) - math.pi) < 1e-6
               for c in corners):
            continue
        t, e = _ray_hit(pts, cx, cy, a)
        out.append((a, (cx + t * math.cos(a), cy + t * math.sin(a)),
                    {cell[e][1]}))
    out.sort(key=lambda o: o[0])
    return out


def _bore_decal(z, up, r, color, square=False):
    """The dark shaft hole on the face of a gear, wheel or collar."""
    n = (0.0, 0.0, float(up))
    dark = mix_color(color, "#14181f", 0.72)
    if square:
        s = SHAFT_W / 2 * 1.12
        pts = [(-s, -s, z), (s, -s, z), (s, s, z), (-s, s, z)]
        if up < 0:
            pts.reverse()
        return [Facet(pts, dark, n)]
    return [Disc((0.0, 0.0, z), (1.0, 0.0, 0.0), (0.0, float(up), 0.0), r,
                 dark, n, stroke=True)]


# -------------------------------------------------------------- part builders


def _beam(w, length, color):
    official = _official(cad_mesh, f"beam_{w}x{length}", color)
    if official is not None:
        holes = tuple((x, y) for x in range(length) for y in range(w))
        return Part(f"beam_{w}x{length}", f"{w}x{length} Beam", color,
                    official, holes)
    prims, holes = _flat(w, length, BEAM_T, color)
    return Part(f"beam_{w}x{length}", f"{w}x{length} Beam", color, prims, holes)


def _plate(w, length, color):
    prims, holes = _flat(w, length, PLATE_T, color)
    return Part(f"plate_{w}x{length}", f"{w}x{length} Plate", color, prims, holes)


def _pin(span, label, name, color):
    """
    A connector pin lying along +z, centred on the origin.  Reads as a VEX pin
    from the centre ridge and the two retaining barbs.
    """
    # The ridge and barbs are kept only slightly proud of the shaft: anything
    # wider sticks out past the bore it sits in and shows through the part it
    # is buried in (see "Known limits" in the README).
    r = PIN_R
    p = cylinder(r, -span / 2, span / 2, color, segments=20)
    p += cylinder(r * 1.22, -0.06, 0.06, color, segments=20)
    p += cylinder(r * 1.12, span / 2 - 0.24, span / 2 - 0.07, color, segments=20)
    p += cylinder(r * 1.12, -span / 2 + 0.07, -span / 2 + 0.24, color, segments=20)
    return Part(name, label, color, p, ((0.0, 0.0, 0.0),), icon_rot=(90.0, 0.0, 0.0))


def _shaft(length, color):
    p = _square_bar(SHAFT_W, -0.5, length - 0.5, color)
    return Part(f"shaft_{length}", f"{length}x Shaft", color, p,
                icon_rot=(90.0, 0.0, 0.0))


def _standoff(length, color):
    p = _square_bar(STANDOFF_W, 0.0, float(length), color, corner=0.10)
    # the threaded ends read as a slightly narrower collar
    p += _square_bar(STANDOFF_W * 0.72, -0.14, 0.0, color, corner=0.08)
    p += _square_bar(STANDOFF_W * 0.72, float(length), length + 0.14, color,
                     corner=0.08)
    return Part(f"standoff_{length}", f"{length}x Standoff", color, p,
                icon_rot=(90.0, 0.0, 0.0))


def _gear(teeth, color):
    """
    VEX IQ gears mesh on whole-pitch centre distances.  That works out to a
    pitch radius of teeth/24, so 12T (r=0.5) and 36T (r=1.5) mesh exactly 2
    holes apart, 12T and 60T exactly 3 apart, and so on.
    """
    official = _official(gear_mesh, teeth, color)
    if official is not None:
        return Part(f"gear_{teeth}", f"{teeth}-Tooth Gear", color,
                    official, icon_rot=FACE_CAMERA)

    r = teeth / 24.0
    h = GEAR_T / 2
    web_z, spoke_z = GEAR_WEB_Z, GEAR_SPOKE_Z
    hub_r = 0.38
    hub_c = mix_color(color, "#173d59", 0.11)
    recess_c = mix_color(color, "#11151b", 0.24)
    bore_c = mix_color(color, "#1b1f27", 0.66)
    profile = gear_profile(teeth, r)
    root = min(math.hypot(x, y) for x, y in profile)

    # VEX's spur gears have round lightening holes through a recessed web.
    # Their layout is one of the quickest visual identifiers for the real
    # pieces: eight around a 36T, and two rings of eight on the classic 60T.
    holes = _gear_holes(teeth)
    slots = _gear_slots(teeth)
    reach = max((math.hypot(x, y) + HOLE_R for x, y in holes), default=0.0)
    rim_in = max(root - GEAR_RIM_W, reach + 0.06)
    solid = rim_in - hub_r < 0.2
    if solid:
        # Too small for a web: the face runs flat from the teeth to a centre
        # cap just wide enough to carry the square bore.
        rim_in = min(0.24, root * 0.75)

    p = extrude(profile, -h, h, color, cap_top=False, cap_bottom=False,
                rim_top=True, rim_bottom=True)
    # The toothed rim, one facet per tooth.  A face fanned from the centre
    # would be long slivers each sorting by a point near the hub, and the
    # beam behind the gear would paint straight across them.
    inner = circle_profile(rim_in, teeth)
    for i in range(teeth):
        j = (i + 1) % teeth
        outline = [inner[i]] + profile[4 * i:4 * i + 4] + [profile[4 * j],
                                                          inner[j]]
        p.append(Facet([(x, y, h) for x, y in outline], color,
                       (0.0, 0.0, 1.0)))
        p.append(Facet([(x, y, -h) for x, y in reversed(outline)], color,
                       (0.0, 0.0, -1.0)))

    if solid:
        for up in (1, -1):
            cap = [Facet([(x, y, h * up) for x, y in inner[::up]], color,
                         (0.0, 0.0, float(up)))]
            p += attach(cap, _bore_decal(h * up, up, 0.0, color,
                                         square=True), up)
        return Part(f"gear_{teeth}", f"{teeth}-Tooth Gear", color, p,
                    icon_rot=FACE_CAMERA)

    # The rim's inner wall, stepping down to the web.
    wall = list(reversed(inner))
    p += extrude(wall, web_z, h, color, cap_top=False, cap_bottom=False,
                 rim_top=True, rim_bottom=False)
    p += extrude(wall, -h, -web_z, color, cap_top=False, cap_bottom=False,
                 rim_top=False, rim_bottom=True)

    # The web is split into one cell per feature - the hub, each hole, each
    # slot - and each cell is built as rings out from its feature, the same
    # way a beam's face is built round its holes.  That keeps every facet
    # small and puts real geometry on the near side of every void.
    sites = [(0.0, 0.0, hub_r)] + [(x, y, HOLE_R) for x, y in holes]
    sites += [(x, y, 0.0) for x, y, _prof in slots]
    is_hole = set(range(1, len(holes) + 1))
    for k, cell in enumerate(_power_cells(sites, inner)):
        cx, cy, rad = sites[k]
        # The hub is the one feature big enough to show its facets.
        rays = _cell_rays(cell, cx, cy,
                          GEAR_RAYS * 2 if k == 0 else GEAR_RAYS)
        edge = [pt for _a, pt, _l in rays]
        if k > len(holes):
            prof = slots[k - len(holes) - 1][2]
            hole = []
            for a, _pt, _l in rays:
                t, _e = _ray_hit(prof, cx, cy, a)
                hole.append((cx + t * math.cos(a), cy + t * math.sin(a)))
        else:
            hole = [(cx + rad * math.cos(a), cy + rad * math.sin(a))
                    for a, _pt, _l in rays]

        # A spoke runs along every side two holes share, at its own level
        # between the web and the rim; everywhere else drops to the web.
        rib = [k in is_hole and labels <= is_hole for _a, _p, labels in rays]
        for up in (1, -1):
            if any(rib):
                step_z = [spoke_z if s else web_z for s in rib]
                foot = _blend(hole, edge, 0.45)
                brow = _blend(hole, edge, 0.7)
                p += _sink_color(_relief_step(hole, foot, web_z, web_z, up,
                                              color), web_z, recess_c)
                p += _relief_step(foot, brow, web_z, step_z, up, color)
                p += _sink_color(_relief_step(brow, edge, step_z, step_z, up,
                                              color), web_z, recess_c)
            else:
                p += _sink_color(_relief_step(hole, edge, web_z, web_z, up,
                                              color), web_z, recess_c)

        if k == 0:
            hub_up = extrude(hole, web_z, h, hub_c, cap_bottom=False,
                             rim_bottom=False)
            hub_dn = extrude(hole, -h, -web_z, hub_c, cap_top=False,
                             rim_top=False)
            p += attach(hub_up, _bore_decal(h, +1, 0.0, hub_c, square=True),
                        +1)
            p += attach(hub_dn, _bore_decal(-h, -1, 0.0, hub_c, square=True),
                        -1)
            continue
        # A real void, dark inside, as on a beam (see _relief_step).
        p += extrude(list(reversed(hole)), -web_z, web_z, bore_c,
                     cap_top=False, cap_bottom=False,
                     rim_top=True, rim_bottom=True)
        p.append(Facet([(x, y, -web_z) for x, y in hole], bore_c,
                       (0.0, 0.0, 1.0)))
        p.append(Facet([(x, y, web_z) for x, y in reversed(hole)], bore_c,
                       (0.0, 0.0, -1.0)))
    return Part(f"gear_{teeth}", f"{teeth}-Tooth Gear", color, p,
                icon_rot=FACE_CAMERA)


def _wheel(travel_mm, color):
    # VEX names its IQ wheels by TRAVEL PER REVOLUTION, not by diameter - a
    # "200mm wheel" rolls 200 mm per turn, so it is 200/pi = 63.7 mm across.
    # Taking the name as a diameter draws every wheel pi times too big.
    r = travel_mm / math.pi / PITCH_MM / 2.0

    # These are assemblies, not one proportional wheel scaled four ways.
    # VEX pairs the 100 mm tire with a blue 20 mm pulley, the 160/200 mm tires
    # with its 44 mm hub, and the 250 mm tire with its 64 mm hub.
    if travel_mm <= 100:
        hub_r, hub_c, hole_r = 10.0 / PITCH_MM, PALETTE["blue"], None
        width = 0.72
    elif travel_mm <= 200:
        hub_r, hub_c, hole_r = 22.0 / PITCH_MM, PALETTE["grey"], 0.78
        width = 0.88 if travel_mm == 200 else 1.02
    else:
        hub_r, hub_c, hole_r = 32.0 / PITCH_MM, PALETTE["grey"], 1.02
        width = 1.20

    hub_width = width + 0.22
    zc = hub_width / 2 + 0.12
    # A real annulus stops the tire's cap triangles from showing through the
    # hub, which was the source of the white spikes in wheel callout icons.
    p = _annular_cylinder(r, hub_r * 0.97, -width / 2, width / 2,
                          color, segments=40)
    p += _wheel_tread(r + 0.006, width, color)
    # A shallow sidewall molding ring keeps the tire from reading as a plain
    # black washer when the parts callout shows it nearly face-on.
    sidewall_c = mix_color(color, "#707780", 0.12)
    mid_r = (r + hub_r) / 2
    band = min(0.055, (r - hub_r) * 0.16)
    for z0, z1 in ((width / 2, width / 2 + 0.012),
                   (-width / 2 - 0.012, -width / 2)):
        p += _annular_cylinder(mid_r + band, mid_r - band, z0, z1,
                               sidewall_c, segments=40)

    holes = ()
    if hole_r is None:
        # The 100 mm tire presses over a six-spoke 20 mm pulley, not a scaled
        # down version of the solid wheel hub.
        p += _annular_cylinder(hub_r, hub_r * 0.68,
                               -hub_width / 2, hub_width / 2,
                               hub_c, segments=30)
        spoke = box(0.28, -0.055, -hub_width / 2,
                    hub_r * 0.80, 0.055, hub_width / 2,
                    hub_c, cell=1.0)
        for a in range(0, 360, 60):
            tf = Transform(euler(rz=a))
            p += [prim.xform(tf) for prim in spoke]
    else:
        # The 44/64 mm hubs are open, ribbed cups.  Modeling the holes as
        # actual annuli (instead of dark spots on a solid disc) keeps pins and
        # shafts visible through them and avoids painter-order crescents.
        face0, face1 = -hub_width / 2 - 0.025, hub_width / 2 + 0.025
        p += _annular_cylinder(hub_r, hub_r * 0.76, face0, face1,
                               hub_c, segments=36)
        holes = tuple(
            (hole_r * math.cos(math.radians(a)),
             hole_r * math.sin(math.radians(a)), 0.0)
            for a in range(0, 360, 45)
        )
        collar = _annular_cylinder(HOLE_R * 1.34, HOLE_R,
                                   face0, face1, hub_c, segments=20)
        for x, y, _ in holes:
            p += moved(collar, (x, y, 0.0))
        rib = box(0.34, -0.055, face0, hub_r * 0.82, 0.055, face1,
                  hub_c, cell=1.0)
        for a in range(0, 360, 45):
            tf = Transform(euler(rz=a + 22.5))
            p += [prim.xform(tf) for prim in rib]

    boss = attach(cylinder(0.39, -zc, zc, hub_c, segments=22),
                  _bore_decal(zc, +1, 0.0, hub_c, square=True), +1)
    attach(boss, _bore_decal(-zc, -1, 0.0, hub_c, square=True), -1)
    return Part(f"wheel_{travel_mm}", f"{travel_mm}mm Travel Wheel",
                color, p + boss, holes, icon_rot=(-51.0, 0.0, -45.0))


def _collar(color):
    p = attach(cylinder(0.34, -0.18, 0.18, color, segments=22),
               _bore_decal(0.18, +1, 0.0, color, square=True), +1)
    attach(p, _bore_decal(-0.18, -1, 0.0, color, square=True), -1)
    return Part("collar", "Shaft Collar", color, p, icon_rot=(90.0, 0.0, 0.0))


def _spacer(thickness, color):
    h = thickness / 2
    p = attach(cylinder(0.30, -h, h, color, segments=22),
               _bore_decal(h, +1, HOLE_R * 0.8, color), +1)
    attach(p, _bore_decal(-h, -1, HOLE_R * 0.8, color), -1)
    thin = thickness < 0.2
    return Part("washer" if thin else "spacer", "Washer" if thin else "Spacer",
                color, p, icon_rot=(90.0, 0.0, 0.0))


def _corner(a, b, color):
    """
    An L bracket: `a` holes running along +x, `b` holes running up +z, sharing
    the corner.  The two slabs interpenetrate at the corner, which reads as a
    solid elbow once shaded.
    """
    leg_a, _ = _flat(1, a, BEAM_T, color)
    leg_b, _ = _flat(1, b + 1, BEAM_T, color,
                     holes=[(i, 0) for i in range(1, b + 1)])
    tf = Transform(euler(ry=-90.0), (0.0, 0.0, 0.0))
    prims = leg_a + [s.xform(tf) for s in leg_b]
    holes = tuple([(i, 0, 0) for i in range(a)] + [(0, 0, i) for i in range(1, b + 1)])
    return Part(f"corner_{a}x{b}", f"{a}x{b} Corner Connector", color, prims, holes)


def _motor(color):
    """
    VEX IQ Smart Motor.  Proportions are eyeballed to be recognisable at a
    glance, not dimensionally exact - swap this function if you need accuracy.
    """
    trim = PALETTE["black"]
    body = box(-0.5, -0.5, -0.5, 2.5, 1.5, 0.9, color)
    # Mounting holes ride on the body lid as decals so they can never be
    # painted over by the very facet they belong to.
    lid_holes = []
    for i in range(3):
        for j in range(2):
            lid_holes += _painted_hole(i, j, 0.9, +1, color)
    attach(body, lid_holes, +1)

    p = body
    p += box(-0.62, -0.36, -0.36, -0.5, 1.36, 0.76, trim)           # cable end
    p += along("x", cylinder(0.42, 0.0, 0.32, trim, segments=22),
               (2.5, 0.5, 0.2))                                      # shaft boss
    p += along("x", _square_bar(SHAFT_W, 0.0, 0.75, PALETTE["steel"]),
               (2.5, 0.5, 0.2))                                      # output shaft
    return Part("motor", "Smart Motor", color, p,
                tuple((i, j, 0.0) for i in range(3) for j in range(2)))


def _brain(color):
    """VEX IQ (2nd gen) Robot Brain - recognisable proportions, not exact."""
    screen_c = PALETTE["screen"]
    trim = PALETTE["black"]
    # Roughly 110 x 85 mm, which is about 8 x 6 holes.
    body = box(-0.5, -0.5, -0.5, 7.5, 5.5, 0.9, color)
    # The screen is a raised solid, not a decal.  A decal rides on one lid
    # facet and gets clipped by the neighbouring cells it overhangs; a solid
    # 0.04 proud of the lid always sorts in front of the cell beneath it -
    # but only if its cells sit squarely on the lid's, so its edges follow
    # the lid's one-pitch grid.  Off the grid, a lid cell's centre can land
    # nearer the camera than the screen cell above it and paint a stripe
    # across the display.
    p = body + box(0.5, 1.5, 0.9, 6.5, 4.5, 0.94, screen_c)
    attach(body, [Disc((x, 0.55, 0.9), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
                       0.26, trim, (0.0, 0.0, 1.0))
                  for x in (2.2, 3.5, 4.8)], +1)
    for i in range(6):                                               # port row
        p += box(i + 0.7 - 0.26, -0.6, -0.28, i + 0.7 + 0.26, -0.5, 0.34, trim)
    return Part("brain", "Robot Brain", color, p)


def _bumper(color):
    p = box(-0.5, -0.5, -0.35, 1.5, 1.5, 0.35, color)
    p += moved(cylinder(0.42, 0.35, 0.55, PALETTE["red"], segments=22),
               (0.5, 0.5, 0.0))
    return Part("bumper", "Bumper Switch", color, p)


def _distance(color):
    lens = PALETTE["black"]
    p = box(-0.5, -0.5, -0.4, 1.5, 0.9, 0.6, color)
    for x in (0.05, 0.95):
        p += along("y", cylinder(0.24, 0.0, 0.12, lens, segments=20),
                   (x, 0.9, 0.1))
    return Part("distance", "Distance Sensor", color, p)


def _battery(color):
    p = box(-0.5, -0.5, -0.5, 3.5, 2.5, 0.6, color)
    p += box(3.5, 0.4, -0.2, 3.7, 1.6, 0.3, PALETTE["black"])
    return Part("battery", "Robot Battery", color, p)


def _rubber_band(length, color):
    """A stretched band, drawn as a thin loop lying along +x."""
    r = 0.10
    seg = []
    for side in (-1, 1):
        seg += moved(along("x", cylinder(r, 0.0, float(length), color, segments=14)),
                     (0.0, side * 0.18, 0.0))
    for x in (0.0, float(length)):
        seg += moved(along("y", cylinder(r, -0.18, 0.18, color, segments=14)),
                     (x, 0.0, 0.0))
    return Part(f"band_{length}", "Rubber Band", color, seg,
                icon_rot=(0.0, 0.0, 0.0))


# ------------------------------------------------------------------- registry

_DEFAULT_COLOR = {
    "beam": "black", "plate": "black", "corner": "black",
    "pin": "blue", "shaft": "steel", "standoff": "black",
    "gear": "blue", "wheel": "black", "collar": "black",
    "spacer": "white", "washer": "white", "motor": "dgrey",
    "brain": "dgrey", "bumper": "dgrey", "distance": "dgrey",
    "battery": "dgrey", "band": "green",
}

_RULES = [
    (re.compile(r"^beam_(\d+)x(\d+)$"), lambda m, c: _beam(int(m[1]), int(m[2]), c)),
    (re.compile(r"^plate_(\d+)x(\d+)$"), lambda m, c: _plate(int(m[1]), int(m[2]), c)),
    (re.compile(r"^corner_(\d+)x(\d+)$"), lambda m, c: _corner(int(m[1]), int(m[2]), c)),
    (re.compile(r"^pin_1x1$"), lambda m, c: _pin(1.00, "1x1 Connector Pin", "pin_1x1", c)),
    (re.compile(r"^pin_1x2$"), lambda m, c: _pin(1.50, "1x2 Connector Pin", "pin_1x2", c)),
    (re.compile(r"^pin_2x2$"), lambda m, c: _pin(2.00, "2x2 Connector Pin", "pin_2x2", c)),
    (re.compile(r"^shaft_(\d+)$"), lambda m, c: _shaft(int(m[1]), c)),
    (re.compile(r"^standoff_(\d+)$"), lambda m, c: _standoff(int(m[1]), c)),
    (re.compile(r"^gear_(\d+)$"), lambda m, c: _gear(int(m[1]), c)),
    (re.compile(r"^wheel_(\d+)$"), lambda m, c: _wheel(int(m[1]), c)),
    (re.compile(r"^band_(\d+)$"), lambda m, c: _rubber_band(int(m[1]), c)),
    (re.compile(r"^collar$"), lambda m, c: _collar(c)),
    (re.compile(r"^spacer$"), lambda m, c: _spacer(0.25, c)),
    (re.compile(r"^washer$"), lambda m, c: _spacer(0.12, c)),
    (re.compile(r"^motor$"), lambda m, c: _motor(c)),
    (re.compile(r"^brain$"), lambda m, c: _brain(c)),
    (re.compile(r"^bumper$"), lambda m, c: _bumper(c)),
    (re.compile(r"^distance$"), lambda m, c: _distance(c)),
    (re.compile(r"^battery$"), lambda m, c: _battery(c)),
]

# How much geometry a part carries.
#
#   "cad"     optional local meshes, where one exists: molded ribs, real
#             tooth profiles, recessed faces. Falls back to simple geometry.
#   "simple"  the procedural approximations underneath.  Roughly a quarter of
#             the file size and noticeably plainer - worth it for a build that
#             has to load over a slow connection or go out by email.
#
# Every part has a procedural form; "cad" only overrides parts supplied by an
# optional local mesh module, so no proprietary data is required.
DETAIL_LEVELS = ("cad", "simple")
# CAD is the product default, rather than a capability-dependent preference.
# That keeps the CLI, Studio, and saved defaults stable when a local mesh
# library is added or removed. `cad` is safe everywhere: each lookup falls
# back to IQDraw's included procedural model when no matching local mesh is
# available.
DEFAULT_DETAIL = "cad"

_detail = DEFAULT_DETAIL

_cache = {}


def set_detail(level):
    """Choose the geometry detail level.  Clears the part cache."""
    global _detail
    if level not in DETAIL_LEVELS:
        raise ValueError(f"detail must be one of {DETAIL_LEVELS}, got {level!r}")
    _detail = level
    _cache.clear()


def detail():
    return _detail


def _official(fetch, key, color):
    """An optional local CAD mesh for `key`, or None if off or absent."""
    return None if _detail == "simple" else fetch(key, color)


def get(name, color=None, detail=None):
    """
    Build (and cache) a part by name.  `color` overrides the default.

    `detail` overrides the global detail level for this one part, which is
    how a booklet can draw the step's new parts from optional local meshes and
    everything already built from the included procedural shapes.
    """
    global _detail
    level = detail or _detail
    key = (name, color, level)
    if key in _cache:
        return _cache[key]
    family = name.split("_")[0]
    resolved = color_of(color or _DEFAULT_COLOR.get(family, "white"))
    for pattern, make in _RULES:
        m = pattern.match(name)
        if m:
            # The builders read the module-level detail rather than taking it
            # as an argument, so swap it for the duration of this one build.
            was, _detail = _detail, level
            try:
                part = make(m, resolved)
            finally:
                _detail = was
            _cache[key] = part
            return part
    raise UnknownPart(name)


class UnknownPart(Exception):
    """
    A part name no rule matches.

    Carries a suggestion, because the overwhelmingly common cause is a size
    that does not exist rather than a family that does not - `beam_1x9` when
    the kit has a 1x8, `gear_35` for a 36.  Guessing blindly at the catalogue
    is exactly the dead end this is meant to save.
    """

    def __init__(self, name):
        self.name = name
        family = name.split("_")[0]
        if family in _DEFAULT_COLOR:
            hint = (f"{family!r} is a known family, so the size is the "
                    f"problem - check {name.split('_', 1)[-1]!r} against a "
                    f"real part")
        else:
            near = difflib.get_close_matches(family, _DEFAULT_COLOR, 1, 0.6)
            hint = (f"did you mean {near[0]!r}?" if near else
                    "known families: " + ", ".join(sorted(_DEFAULT_COLOR)))
        super().__init__(f"unknown part {name!r} - {hint}")


def known_families():
    return sorted(_DEFAULT_COLOR)
