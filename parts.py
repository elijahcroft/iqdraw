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


CELL_PTS = 12  # boundary points per hole cell; also the hole's polygon count


def _resample(profile, target):
    """Split the longest edges until the outline has at least `target` points."""
    pts = list(profile)
    while len(pts) < target:
        k = max(range(len(pts)),
                key=lambda i: math.dist(pts[i], pts[(i + 1) % len(pts)]))
        a, b = pts[k], pts[(k + 1) % len(pts)]
        pts.insert(k + 1, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
    return pts


def _annulus(profile, cx, cy, r, z, up, color):
    """
    The face of one hole cell: the material between a circular void at
    (cx, cy) and the cell's outline, as a ring of quads.

    A hole has to be a real void, not a dark circle painted on a solid face.
    Under a depth sort, a solid face covering the hole would be one facet
    centred on the hole itself, and anything pushed through that hole - a pin,
    a shaft - sits nearer the camera than that centre and gets drawn on top of
    the beam it is buried in.  Ringing the void with quads puts real geometry
    on the near side of the hole, which is what hides the buried shaft.
    """
    out = []
    n = len(profile)
    for k in range(n):
        ax, ay = profile[k]
        bx, by = profile[(k + 1) % n]
        aa = math.atan2(ay - cy, ax - cx)
        ab = math.atan2(by - cy, bx - cx)
        ia = (cx + r * math.cos(aa), cy + r * math.sin(aa))
        ib = (cx + r * math.cos(ab), cy + r * math.sin(ab))
        pts = [(ia[0], ia[1], z), (ax, ay, z), (bx, by, z), (ib[0], ib[1], z)]
        if up < 0:
            pts.reverse()
        out.append(Facet(pts, color, (0.0, 0.0, float(up))))
    return out


def _loft_ring(lower, upper, z0, z1, color, inward=False):
    """Join two equal-length profiles with a band of shaded quadrilaterals."""
    out = []
    n = len(lower)
    for k in range(n):
        a0 = (*lower[k], z0)
        b0 = (*lower[(k + 1) % n], z0)
        b1 = (*upper[(k + 1) % n], z1)
        a1 = (*upper[k], z1)
        pts = [a0, b0, b1, a1]
        if inward:
            pts.reverse()
        out.append(Facet(pts, color))
    return out


def _hole_chamfer(cx, cy, outer_r, inner_r, z_face, z_bore, up, color):
    """The small conical lead-in molded around a VEX structural hole."""
    outer = circle_profile(outer_r, CELL_PTS, cx, cy)
    inner = circle_profile(inner_r, CELL_PTS, cx, cy)
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
    return rounded_rect(x0, y0, x1, y1, radii)


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

    outer = rounded_rect(x0, y0, x1, y1, (CORNER_R,) * 4)
    inset = rounded_rect(
        x0 + EDGE_BEVEL, y0 + EDGE_BEVEL,
        x1 - EDGE_BEVEL, y1 - EDGE_BEVEL,
        (CORNER_R - EDGE_BEVEL,) * 4,
    )
    face = t / 2
    shoulder = face - EDGE_BEVEL
    bevel_c = mix_color(color, "#ffffff", 0.09)

    # A VEX beam is injection molded, not a square-edged slab.  Keep the
    # vertical wall slightly inboard of each face and bridge it with a narrow
    # chamfer.  The highlight catches like a real CAD model without relying on
    # SVG gradients or a particular output resolution.
    prims = extrude(
        outer, -shoulder, shoulder, color,
        cap_top=False, cap_bottom=False, rim_top=True, rim_bottom=True,
    )
    prims += _loft_ring(outer, inset, shoulder, face, bevel_c)
    prims += _loft_ring(inset, outer, -face, -shoulder, color)

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
            cell = _cell_profile(i, j, w, length, EDGE_BEVEL)

            if (i, j) not in drilled:
                prims.append(Facet([(x, y, t / 2) for x, y in cell], color,
                                   (0.0, 0.0, 1.0)))
                prims.append(Facet([(x, y, -t / 2) for x, y in reversed(cell)],
                                   color, (0.0, 0.0, -1.0)))
                continue

            ring = _resample(cell, CELL_PTS)
            mouth_r = HOLE_R + HOLE_BEVEL
            prims += _annulus(ring, i, j, mouth_r, face, +1, color)
            prims += _annulus(ring, i, j, mouth_r, -face, -1, color)
            prims += _hole_chamfer(i, j, mouth_r, HOLE_R, face, shoulder,
                                   +1, bevel_c)
            prims += _hole_chamfer(i, j, mouth_r, HOLE_R, -face, -shoulder,
                                   -1, color)
            # Looking down a hole at this angle you see its far inner wall, so
            # the bore needs an inward-facing cylinder - a dark disc at the
            # bottom projects below the opening and never lines up with it.
            # Reversing the profile flips the wall normals to point inward.
            disc = circle_profile(HOLE_R, 12, i, j)
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


def _attach_face_details(prims, details, up=1):
    """Lift broad face markings clear of triangulated cap cells.

    A gear face is divided into narrow radial facets for depth sorting.  A
    round hole spans several of those facets, so attaching it to any one host
    lets the neighbouring facets paint over it.  A hair of physical relief is
    both true to the molded rim around the holes and keeps the complete detail
    ahead of every coplanar cap cell.
    """
    caps = [p for p in prims
            if isinstance(p, Facet) and p.normal[2] * up > 0.9]
    if not caps:
        return prims
    zmax = max(f.pts[0][2] * up for f in caps)
    dz = (zmax + 0.004) * up
    for detail in details:
        if isinstance(detail, Disc):
            detail.center = (detail.center[0], detail.center[1], dz)
        else:
            detail.pts = [(x, y, dz) for x, y, _ in detail.pts]
        prims.append(detail)
    return prims


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


def _gear_slot(angle, radius, length, width, z, color):
    """A tangential molded slot used on the classic VEX IQ 60T gear."""
    prof = rounded_rect(-length / 2, -width / 2,
                        length / 2, width / 2,
                        (width / 2,) * 4, segments=4)
    pts = [(x, y, z) for x, y in prof]
    tf = Transform(euler(rz=angle + 90),
                   (radius * math.cos(math.radians(angle)),
                    radius * math.sin(math.radians(angle)), 0.0))
    return Facet([tf.point(p) for p in pts], color, (0.0, 0.0, 1.0))


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
    t = 0.40
    hz = t / 2 + 0.20
    hub_r = min(0.38, r * 0.72)
    hub_c = mix_color(color, "#173d59", 0.11)
    p = extrude(gear_profile(teeth, r), -t / 2, t / 2, color)

    # VEX's spur gears are solid molded faces with round lightening holes.
    # Their layout is one of the quickest visual identifiers for the real
    # pieces: eight around a 36T, and two rings of eight on the classic 60T.
    hole_decals = []
    for x, y in _gear_holes(teeth):
        hole_decals += _painted_hole(x, y, t / 2, +1, color)
    if teeth >= 60:
        slot_c = mix_color(color, "#10151c", 0.82)
        hole_decals += [
            _gear_slot(a, 1.43, 0.72, 0.13, t / 2, slot_c)
            for a in (45, 135, 225, 315)
        ]
    _attach_face_details(p, hole_decals, +1)

    hub_up = attach(cylinder(hub_r, t / 2, hz, hub_c, segments=24),
                    _bore_decal(hz, +1, 0.0, hub_c, square=True), +1)
    hub_dn = attach(cylinder(hub_r, -hz, -t / 2, hub_c, segments=24),
                    _bore_decal(-hz, -1, 0.0, hub_c, square=True), -1)
    return Part(f"gear_{teeth}", f"{teeth}-Tooth Gear", color,
                p + hub_up + hub_dn, icon_rot=FACE_CAMERA)


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
    # 0.04 proud of the lid always sorts in front of the cell beneath it.
    p = body + box(0.6, 1.5, 0.9, 6.4, 5.0, 0.94, screen_c)
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
_detail = "simple"

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
