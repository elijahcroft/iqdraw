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

from .cadmesh import cad_mesh, gear_mesh
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
PLATE_T = 0.50           # plate thickness - a 2nd-gen plate is as thick as
                         # a beam (0.48 in the 3x3, 4x4 and 4x8 STEP files)
HOLE_R = 0.25            # hole radius
PIN_R = 0.19             # connector-pin radius
STANDOFF_W = 0.46        # standoff across the flats
CORNER_R = 0.50          # the rounded end of a beam == half a pitch
EDGE_BEVEL = 0.055       # molded chamfer around structural-part faces
HOLE_BEVEL = 0.055       # countersink around each structural hole
# ============================================================================

# Colours.  Structural plastic is drawn the light grey VEX's own build guides
# use, not the black of the kit's base packs: molded detail - ribs, recesses,
# the holes themselves - disappears on black, and the guides students already
# follow draw it grey.  Everything else follows the VEX IQ (2nd gen) *base*
# colours that ship in the Starter and Super Kits, so a rendered step matches
# what a student pulls out of the tray.  Every plastic family is also sold in
# alternate colours - a placement can override any of them with `color:`, and
# `color="black"` gives the base-pack colour back.
#
#   beams, plates       guide grey      (base packs are black: 1x/2x Beam Base
#                                        Pack, 4x Plate Base Pack)
#   corner connectors   guide grey      (base pack 228-3513 is black)
#   connector pins      blue            (Connector Pin Pack 228-3058)
#   standoffs           black           (Standoff Base Pack 228-3514)
#   metal shafts        zinc-plated steel (Shaft Base Pack 228-3506)
#   plastic shafts      black           (Plastic Shaft Base Pack 228-3620)
#   gears               blue            (Gear Base Pack 228-3502)
#   sprockets + chain   orange          (the colour most kits carry)
#   tyres               black rubber (drawn a shade lighter), on a light grey hub
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
    "guide": "#8b8a90",      # beams, plates, corners - sampled from the
                             # #8d8c92 VEX's build guides use
    "grey": "#cfd0d4",       # wheel hubs
    "vexgrey": "#6b7079",    # optional grey structural variant
    "dgrey": "#4d535c",      # electronics housings
    "black": "#2b2f35",      # standoffs, collars, plastic shafts
    "rubber": "#47484d",     # tyres - a shade off black, so the tread reads
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


# VEX part numbers, printed under each part in the letter-size guides'
# callouts.  Read off the STEP pack's file names; a part not listed here is
# named instead.
PART_NUMBERS = {
    "beam_1x2": "228-2500-001", "beam_1x4": "228-2500-003",
    "beam_1x6": "228-2500-005", "beam_1x8": "228-2500-007",
    "beam_1x10": "228-2500-009", "beam_2x2": "228-2500-017",
    "beam_2x6": "228-2500-021", "beam_2x8": "228-2500-023",
    "beam_2x12": "228-2500-026", "beam_2x16": "228-2500-028",
    "beam_offset_4x4": "228-2500-151", "plate_4x4": "228-2500-040",
    "plate_4x12": "228-2500-045", "lbeam_2x3": "228-2500-145",
    "lbeam_3x5": "228-2500-150", "anglebeam_3x3_60": "228-2500-149",
    "anglebeam_3x3_45": "228-2500-148", "lockbeam_1x3": "228-2500-141",
    "lockbeam_round_2x2": "228-2500-1925", "lockbeam_2x2": "228-2500-140",
    "connector_2w_1x2": "228-2500-128", "connector_2w_1x2_offset": "228-2500-135",
    "connector_2w_2x1": "228-2500-132",
    "connector_2w_2x2_offset": "228-2500-136",
    "connector_triple_2x2": "228-2500-1253",
    "connector_chassis_large": "228-2500-126",
    "pin_0x2": "228-2500-086", "pin_1x1": "228-2500-060",
    "pin_1x2": "228-2500-061", "pin_2x2": "228-2500-062",
    "standoff_half": "228-2500-064", "standoff_1": "228-2500-065",
    "standoff_2": "228-2500-067", "standoff_4": "228-2500-070",
    "standoffconn_mini": "228-2500-170",
    "shaft_2": "228-2500-117", "shaft_3": "228-2500-119",
    "shaft_4": "228-2500-120", "shaft_6": "228-2500-122",
    "shaft_8": "228-2500-124", "plastic_shaft_2": "228-2500-074",
    "capped_shaft_2": "228-2500-080", "capped_shaft_3": "228-2500-081",
    "capped_shaft_5": "228-2500-2225", "plastic_motor_shaft_3": "228-2500-094",
    "motorshaft_2": "228-2500-2234", "motorshaft_3": "228-2500-2236",
    "collar": "228-2500-143", "washer": "228-2500-112",
    "spacer": "228-2500-114", "gear_12": "228-2500-213",
    "crankarm_1x4": "228-2500-246", "tractionlink": "228-2500-239",
    "gear_36": "228-2500-214", "gear_60": "228-2500-215",
    "hub_200": "228-2500-208", "tyre_200": "228-2500-209",
    "pulley_20": "228-2500-164", "omni_200": "228-2536",
    "motor": "228-2560", "brain": "228-6480", "cable_200": "228-2780-001",
}


def part_number(name):
    """The VEX number for `name`, or None.  A stand-in has none of its own."""
    return None if "@" in name else PART_NUMBERS.get(name)


def size_label(name):
    """
    The size the 2nd-gen guides print in a dark tag on a part - "2x12" on a
    beam, "1x1" on a pin, "3x" on a shaft, "200mm" on a wheel - or "".
    """
    base = name.partition("@")[0]
    m = re.match(r"^(?:beam|plate|pin|lockbeam_round|lockbeam|crankarm)_(\d+x\d+)$",
                 base)
    if m:
        return m[1]
    m = re.match(r"^(?:shaft|plastic_shaft|capped_shaft|motorshaft|"
                 r"plastic_motor_shaft|standoff)_(\d+)$", base)
    if m:
        return f"{m[1]}x"
    m = re.match(r"^(?:wheel|omni|tyre|hub|cable)_(\d+)$", base)
    if m:
        return f"{m[1]}mm"
    return ""


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
    # Never ringed as a step's new part - a cable's run, which the guides
    # draw plain and mark only where it plugs in.
    plain: bool = False


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


# The 4x4 offset right-angle beam: two 3-hole arms at right angles, joined
# by a hole set diagonally across the corner, so the arms' end holes are 4
# apart along each axis.  Hole 0 is at the origin and its arms run along +x
# and then +y, which is the STEP model's frame turned a quarter.
_OFFSET_4X4_HOLES = ((0, 0), (1, 0), (2, 0), (2.5, 0.5), (3, 1), (3, 2), (3, 3))


def _offset_beam(color):
    official = _official(cad_mesh, "beam_offset_4x4", color)
    if official is None:
        # Plain arms, plus the corner hole as a one-hole beam turned 45
        # degrees; the overlapping round ends read as the molded bend.
        arm, _ = _flat(1, 3, BEAM_T, color)
        corner, _ = _flat(1, 1, BEAM_T, color)
        official = (arm
                    + [p.xform(Transform(euler(rz=90.0), (3.0, 1.0, 0.0)))
                       for p in arm]
                    + [p.xform(Transform(euler(rz=45.0), (2.5, 0.5, 0.0)))
                       for p in corner])
    return Part("beam_offset_4x4", "4x4 Offset Right Angle Beam", color,
                official, _OFFSET_4X4_HOLES)


def _plate(w, length, color):
    official = _official(cad_mesh, f"plate_{w}x{length}", color)
    if official is not None:
        # The official plates are as thick as a beam, not the PLATE_T
        # estimate the procedural form uses.
        holes = tuple((x, y) for x in range(length) for y in range(w))
        return Part(f"plate_{w}x{length}", f"{w}x{length} Plate", color,
                    official, holes)
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
    official = _official(cad_mesh, name, color)
    if official is not None:
        return Part(name, label, color, official, ((0.0, 0.0, 0.0),),
                    icon_rot=(90.0, 0.0, 0.0))
    r = PIN_R
    # The ridge is the joint face.  A 1x2 pin has one pitch of its length on
    # one side of it and half a pitch on the other, so it is not centred.
    lo, hi = (-1.0, 0.5) if span == 1.50 else (-span / 2, span / 2)
    p = cylinder(r, lo, hi, color, segments=20)
    p += cylinder(r * 1.22, -0.06, 0.06, color, segments=20)
    p += cylinder(r * 1.12, hi - 0.24, hi - 0.07, color, segments=20)
    p += cylinder(r * 1.12, lo + 0.07, lo + 0.24, color, segments=20)
    return Part(name, label, color, p, ((0.0, 0.0, 0.0),), icon_rot=(90.0, 0.0, 0.0))


def _pin_capped(color):
    """
    The 0x2 connector pin: a head, then a pitch of pin - enough for two
    beams.  The origin is the underside of the head, the face it is pushed
    against, and the pin runs up +z from there.
    """
    p = _official(cad_mesh, "pin_0x2", color)
    if p is None:
        p = cylinder(0.25, -0.05, 0.0, color, segments=20)
        p += cylinder(PIN_R, 0.0, 0.92, color, segments=20)
    return Part("pin_0x2", "0x2 Connector Pin", color, p,
                ((0.0, 0.0, 0.0),), icon_rot=(90.0, 0.0, 0.0))


def _shaft(length, color, kind=""):
    name = f"{kind}shaft_{length}"
    p = (_official(cad_mesh, name, color)
         or _square_bar(SHAFT_W, -0.5, length - 0.5, color))
    label = f"{length}x Plastic Shaft" if kind else f"{length}x Shaft"
    return Part(name, label, color, p, icon_rot=(90.0, 0.0, 0.0))


def _capped_shaft(length, color):
    """A plastic shaft with a round cap on its -z end, so it cannot pull through."""
    p = _official(cad_mesh, f"capped_shaft_{length}", color)
    if p is None:
        p = _square_bar(SHAFT_W, -0.5, length - 0.5, color)
        p += cylinder(0.19, -0.5, -0.38, color, segments=20)
    return Part(f"capped_shaft_{length}", f"{length}x Capped Shaft", color, p,
                icon_rot=(90.0, 0.0, 0.0))


def _standoff(length, color, name=None):
    name = name or f"standoff_{length}"
    official = _official(cad_mesh, name, color)
    if official is not None:
        return Part(name, f"{length}x Standoff", color, official,
                    icon_rot=(90.0, 0.0, 0.0))
    p = _square_bar(STANDOFF_W, 0.0, float(length), color, corner=0.10)
    # the threaded ends read as a slightly narrower collar
    p += _square_bar(STANDOFF_W * 0.72, -0.14, 0.0, color, corner=0.08)
    p += _square_bar(STANDOFF_W * 0.72, float(length), length + 0.14, color,
                     corner=0.08)
    return Part(name, f"{length}x Standoff", color, p,
                icon_rot=(90.0, 0.0, 0.0))


def _standoff_connector(color):
    """
    The mini standoff connector: a short round sleeve along +z, centred on
    the origin.  Its bore is round, so on a shaft it spins - a spacer.
    """
    name = "standoffconn_mini"
    p = _official(cad_mesh, name, color)
    if p is None:
        p = attach(cylinder(0.30, -0.43, 0.43, color, segments=22),
                   _bore_decal(0.43, +1, HOLE_R * 0.75, color), +1)
        attach(p, _bore_decal(-0.43, -1, HOLE_R * 0.75, color), -1)
    return Part(name, "Mini Standoff Connector", color, p,
                icon_rot=(90.0, 0.0, 0.0))


def _motor_shaft(length, color):
    """
    A plastic motor shaft: a plain shaft that runs -0.5 .. length-0.5 like
    any other, with a thin ridge at its -z end and a short tip beyond it,
    the part that would go into a motor.
    """
    name = f"plastic_motor_shaft_{length}"
    p = _official(cad_mesh, name, color)
    if p is None:
        p = _square_bar(SHAFT_W, -0.46, length - 0.54, color)
        p += cylinder(0.19, -0.50, -0.46, color, segments=20)
        p += _square_bar(SHAFT_W, -0.90, -0.50, color)
    return Part(name, f"{length}x Plastic Motor Shaft", color, p,
                icon_rot=(90.0, 0.0, 0.0))


def _metal_motor_shaft(length, color):
    """
    A metal motor shaft: a short tip that goes into the motor, a ridge, then
    the shaft.  The origin is the ridge, which stops against the motor's
    face; the shaft runs up +z from it, about `length` pitch.
    """
    name = f"motorshaft_{length}"
    p = _official(cad_mesh, name, color)
    if p is None:
        p = _square_bar(SHAFT_W, 0.04, length - 0.1, color)
        p += cylinder(0.19, -0.04, 0.04, color, segments=20)
        p += _square_bar(SHAFT_W, -0.46, -0.04, color)
    return Part(name, f"{length}x Motor Shaft", color, p,
                icon_rot=(90.0, 0.0, 0.0))


def _lockbeam_round(color):
    """
    The 2x2 center offset round lock beam: a disc two pitch across on
    z = 0..0.5, drilled with four holes on the diagonals (+-0.5, +-0.5) and a
    square centre hole, with a boss below it down to z = -0.43.  Pinned to a
    wheel hub it is what makes the wheel turn with its shaft.
    """
    name = "lockbeam_round_2x2"
    holes = tuple((x, y, 0.0) for x in (-0.5, 0.5) for y in (-0.5, 0.5))
    p = _official(cad_mesh, name, color)
    if p is None:
        p = attach(cylinder(1.0, 0.0, 0.5, color, segments=32),
                   [d for x, y, _ in holes
                    for d in _painted_hole(x, y, 0.5, +1, color)]
                   + _bore_decal(0.5, +1, 0.0, color, square=True), +1)
        p += cylinder(0.45, -0.43, 0.0, color, segments=20)
    return Part(name, "2x2 Center Offset Round Lock Beam", color, p, holes,
                icon_rot=FACE_CAMERA)


def _crank_arm(color):
    """
    The 1x4 crank arm with a 23-tooth gear (228-2500-246): a 1-wide arm of
    four holes along +x, hole 0 square and ringed by the gear, lying in the
    xy plane with its mid-plane at z = 0, like a beam.
    """
    name = "crankarm_1x4"
    holes = tuple((i, 0) for i in range(4))
    p = _official(cad_mesh, name, color)
    if p is None:
        p, _ = _flat(1, 4, BEAM_T, color)
        p += cylinder(1.08, -0.25, 0.25, color, segments=23)
    return Part(name, "1x4 Crank Arm with 23 Tooth Gear", color, p, holes)


def _traction_link(color):
    """
    The traction link (228-2500-239): a rubbery pad on two pegs one pitch
    apart, at x = 0 and 1, pointing down -z with their tips at z = -0.5.
    The pad's underside, which sits on whatever the pegs go into, is z = 0.
    """
    name = "tractionlink"
    p = _official(cad_mesh, name, color)
    if p is None:
        p = box(-0.22, -0.25, 0.0, 1.28, 0.25, 0.33, color)
        for x in (0, 1):
            p += moved(cylinder(0.15, -0.5, 0.0, color, segments=12), (x, 0, 0))
    return Part(name, "Traction Link", color, p)


def _lockbeam(length, color):
    """A 1-wide beam whose centre hole is square, so it turns with a shaft."""
    name = f"lockbeam_1x{length}"
    holes = tuple((i, 0) for i in range(length))
    p = _official(cad_mesh, name, color)
    if p is None:
        p, _ = _flat(1, length, BEAM_T, color)
    return Part(name, f"1x{length} Center Lock Beam", color, p, holes)


def _connector_double_1x2_offset(color):
    """
    The double 2x wide 1x2 offset corner connector: a block two pitch long,
    one deep and 1.5 tall, with holes through it along y at (0, 0, 0) and
    (1, 0, 0) and a centre hole half a pitch above them, and two pegs on its
    top face (z = 1) pointing up, two on its bottom face (z = -0.5) pointing
    down, over x = 0 and 1.  It joins a beam to one 1.5 pitch above it.
    """
    name = "connector_2w_1x2_offset_double"
    holes = ((0, 0, 0), (1, 0, 0), (0.5, 0, 0.5))
    prims = _official(cad_mesh, name, color)
    if prims is None:
        prims = box(-0.5, -0.5, -0.5, 1.5, 0.5, 1.0, color)
        for x in (0.0, 1.0):
            for z0, z1 in ((1.0, 1.48), (-0.98, -0.5)):
                prims += moved(cylinder(PIN_R, z0, z1, color, segments=20),
                               (x, 0.0, 0.0))
    return Part(name, "Double 2x Wide 1x2 Offset Corner Connector", color, prims,
                holes)


def _lockbeam_square(color):
    """
    The 2x2 center lock beam: a 2x2 square beam lying flat, its origin on
    the square centre hole, so it sits on a shaft at the shaft's own
    coordinates, with a pin hole at each corner (+-0.5, +-0.5).
    """
    name = "lockbeam_2x2"
    holes = tuple((x, y, 0.0) for x in (-0.5, 0.5) for y in (-0.5, 0.5))
    p = _official(cad_mesh, name, color)
    if p is None:
        p = moved(_flat(2, 2, BEAM_T, color)[0], (-0.5, -0.5, 0.0))
    return Part(name, "2x2 Center Lock Beam", color, p, holes,
                icon_rot=FACE_CAMERA)


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


# The hub each tyre is sold on, for the wheels with official meshes.
_WHEEL_HUB = {200: "wheel_hub_44"}


def _wheel(travel_mm, color):
    # VEX names its IQ wheels by TRAVEL PER REVOLUTION, not by diameter - a
    # "200mm wheel" rolls 200 mm per turn, so it is 200/pi = 63.7 mm across.
    # Taking the name as a diameter draws every wheel pi times too big.
    r = travel_mm / math.pi / PITCH_MM / 2.0
    hub_c = PALETTE["grey"]  # light-grey hub, so it reads against a black tyre
    tyre = _official(cad_mesh, f"tyre_{travel_mm}", color)
    hub = _official(cad_mesh, _WHEEL_HUB.get(travel_mm), hub_c)
    if tyre is not None and hub is not None:
        return Part(f"wheel_{travel_mm}", f"{travel_mm}mm Travel Wheel", color,
                    tyre + hub, icon_rot=(90.0, 0.0, 0.0))

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


def _wheel_half(travel_mm, color, which):
    """
    The hub or the tyre of a travel wheel on its own, in the wheel's frame,
    for the guides that hand them out apart and have the tyre pushed on.
    """
    r = travel_mm / math.pi / PITCH_MM / 2.0
    width = 0.95
    if which == "tyre":
        mesh = _official(cad_mesh, f"tyre_{travel_mm}", color)
        label = f"{travel_mm}mm Travel Tire"
        if mesh is None:
            mesh = cylinder(r, -width / 2, width / 2, color, segments=36)
            mesh += cylinder(r * 0.93, -width / 2 - 0.04, width / 2 + 0.04,
                             color, segments=36)
        return Part(f"tyre_{travel_mm}", label, color, mesh,
                    icon_rot=(90.0, 0.0, 0.0))
    mesh = _official(cad_mesh, _WHEEL_HUB.get(travel_mm), color)
    if mesh is None:
        zc = width / 2 + 0.16
        mesh = cylinder(r * 0.69, -width / 2 - 0.14, width / 2 + 0.14, color,
                        segments=30)
        boss = attach(cylinder(0.42, -zc, zc, color, segments=22),
                      _bore_decal(zc, +1, 0.0, color, square=True), +1)
        attach(boss, _bore_decal(-zc, -1, 0.0, color, square=True), -1)
        mesh += boss
    return Part(f"hub_{travel_mm}", f"{travel_mm}mm Travel Wheel Hub", color,
                mesh, icon_rot=(90.0, 0.0, 0.0))


def _ring(r_out, r_in, z0, z1, color, segments=32):
    """A flat ring along +z: a disc with a round hole through the middle."""
    outer = circle_profile(r_out, segments)
    inner = circle_profile(r_in, segments)
    p = extrude(outer, z0, z1, color, cap_top=False, cap_bottom=False)
    p += extrude(list(reversed(inner)), z0, z1, color, cap_top=False,
                 cap_bottom=False)
    p += _loft_ring(outer, inner, z1, z1, color)
    p += _loft_ring(outer, inner, z0, z0, color, inward=True)
    return p


OMNI_WEB = (0.61, 0.97)   # the omni hub's drilled web, along its +z


def _omni(travel_mm, color):
    """
    An omni-directional wheel, along +z and centred on its axle midway
    across the rollers: a grey hub, and two rows of seven black rollers round
    the rim, staggered so one is always on the floor.

    Taken from VEX's STEP file (228-2536): 200/pi mm across the rollers and
    2.1 pitch wide over them.  The hub is not symmetric.  Its web, drilled
    with a 2x2 square of pin holes for a round lock beam and four more
    outside them, is the +z face, 0.61 .. 0.97 up, with the centre boss
    standing to 1.04; the -z side is an open drum the lock beam sits in.
    """
    r = travel_mm / math.pi / PITCH_MM / 2.0
    hub_c = PALETTE["grey"]
    roller_c = color
    hub = _official(cad_mesh, f"omni_hub_{travel_mm}", hub_c)
    if hub is not None:
        return Part(f"omni_{travel_mm}", f"{travel_mm}mm Travel Omni Wheel",
                    color, hub + cad_mesh(f"omni_rollers_{travel_mm}", roller_c),
                    icon_rot=(90.0, 0.0, 0.0))
    p = _ring(r - 0.15, 1.45, -0.07, 0.07, hub_c)                 # mid flange
    for z0, z1 in ((-0.75, -0.6), (0.6, 0.75)):                   # side plates
        p += _ring(r - 0.35, 1.45, z0, z1, hub_c)
    p += _ring(1.55, 1.4, -0.75, 0.61, hub_c)                     # the drum
    web = cylinder(1.55, OMNI_WEB[0], OMNI_WEB[1], hub_c, segments=32)
    attach(web, [d for x, y in ((-0.5, -0.5), (-0.5, 0.5), (0.5, -0.5),
                                (0.5, 0.5), (0, 1), (0, -1), (1, 0), (-1, 0))
                 for d in _painted_hole(x, y, OMNI_WEB[1], +1, hub_c)], +1)
    p += web
    boss = cylinder(0.31, OMNI_WEB[1], 1.04, hub_c, segments=16)
    p += attach(boss, _bore_decal(1.04, +1, 0.0, hub_c, square=True), +1)
    n, rr, length = 7, 0.47, 1.2
    for row, z in enumerate((-0.555, 0.555)):
        for k in range(n):
            a = 360.0 / n * (k + 0.5 * row)
            roller = along("x", cylinder(rr, -length / 2, length / 2,
                                         roller_c, segments=14))
            tf = Transform(euler(rz=a + 90.0),
                           ((r - rr) * math.cos(math.radians(a)),
                            (r - rr) * math.sin(math.radians(a)), z))
            p += [prim.xform(tf) for prim in roller]
    return Part(f"omni_{travel_mm}", f"{travel_mm}mm Travel Omni Wheel",
                color, p, icon_rot=(90.0, 0.0, 0.0))


def _collar(color):
    official = _official(cad_mesh, "collar", color)
    if official is not None:
        return Part("collar", "Shaft Collar", color, official,
                    icon_rot=(90.0, 0.0, 0.0))
    p = attach(cylinder(0.34, -0.18, 0.18, color, segments=22),
               _bore_decal(0.18, +1, 0.0, color, square=True), +1)
    attach(p, _bore_decal(-0.18, -1, 0.0, color, square=True), -1)
    return Part("collar", "Shaft Collar", color, p, icon_rot=(90.0, 0.0, 0.0))


def _spacer(thickness, color):
    h = thickness / 2
    thin = thickness < 0.2
    official = _official(cad_mesh, "washer" if thin else "spacer", color)
    if official is not None:
        return Part("washer", "Washer", color, official,
                    icon_rot=(90.0, 0.0, 0.0))
    p = attach(cylinder(0.30, -h, h, color, segments=22),
               _bore_decal(h, +1, HOLE_R * 0.8, color), +1)
    attach(p, _bore_decal(-h, -1, HOLE_R * 0.8, color), -1)
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


def _lbeam(a, b, color):
    """
    A right-angle beam: `a` holes along +x and `b` along +y, sharing hole 0
    at the corner.  Drawn plain, it is two straight beams overlapping on that
    corner hole, the way `_corner` builds its elbow.
    """
    name = f"lbeam_{a}x{b}"
    holes = tuple([(i, 0) for i in range(a)] + [(0, j) for j in range(1, b)])
    prims = _official(cad_mesh, name, color)
    if prims is None:
        leg_a, _ = _flat(1, a, BEAM_T, color)
        leg_b, _ = _flat(1, b, BEAM_T, color)
        tf = Transform(euler(rz=90.0), (0.0, 0.0, 0.0))
        prims = leg_a + [s.xform(tf) for s in leg_b]
    return Part(name, f"{a}x{b} Right Angle Beam", color, prims, holes)


def _connector_2x1(color):
    """
    The 2x wide 2x1 corner connector (228-2500-132): two pegs one pitch
    apart along +x, at x = 0 and 1, standing up +z from its top face at
    z = 0, and below peg 0 a tab one pitch thick with two holes through it
    along y, at z = -0.5 and -1.5.  Taken from VEX's STEP file.
    """
    name = "connector_2w_2x1"
    holes = ((0.0, 0.0, -0.5), (0.0, 0.0, -1.5))
    prims = _official(cad_mesh, name, color)
    if prims is None:
        prims = box(-0.35, -0.49, -0.45, 1.35, 0.49, 0.0, color)
        prims += box(-0.35, -0.49, -1.98, 0.35, 0.49, -0.45, color)
        for x in (0, 1):
            prims += moved(cylinder(PIN_R, 0.0, 0.48, color, segments=12),
                           (x, 0, 0))
    return Part(name, "2x Wide 2x1 Corner Connector", color, prims, holes)


def _connector(size, offset, color):
    """
    A 2x wide corner connector: a plate standing in the xz plane with holes
    through it along y, two pegs on its top edge pointing up +z.  The plate
    fills y = -0.5..0 and the pegs sit on its +y face, so a beam pressed
    onto the pegs ends up against whatever is pinned to that face.

    The 1x2 has one row of two holes at z = 0, its pegs half a pitch above.
    Each other shape keeps that bottom-up reading: the offset 1x2 is half a
    pitch taller with a centre hole above the pair, putting the pegs a whole
    pitch above the holes; the offset 2x2 adds a second row below, at
    z = -1, with centre holes between the rows and above the top one.
    """
    name = f"connector_2w_{size}" + ("_offset" if offset else "")
    label = f"2x Wide {size} " + ("Offset " if offset else "") + \
        "Corner Connector"
    top = 1.0 if offset else 0.5          # where the pegs start
    rows = (0, -1) if size == "2x2" else (0,)
    holes = tuple((x, 0, z) for z in rows for x in (0, 1))
    if offset:
        holes += tuple((0.5, 0, z + 0.5) for z in rows)
    prims = _official(cad_mesh, name, color)
    if prims is None:
        slab, _ = _flat(len(rows), 2, BEAM_T, color)
        tf = Transform(euler(rx=90.0), (0.0, -0.25, rows[-1]))
        prims = [s.xform(tf) for s in slab]
        if offset:
            prims += box(-0.5, -0.5, 0.5, 1.5, 0.0, top, color)
        prims += box(-0.5, -0.5, top - 0.15, 1.5, 0.5, top, color)  # flange
        for x in (0.0, 1.0):
            prims += moved(cylinder(PIN_R, top, top + 0.48, color,
                                    segments=20), (x, 0.0, 0.0))
    return Part(name, label, color, prims, holes)


def _anglebeam(angle, color):
    """
    A 3x3 angle beam: three holes along +x from the origin, the third one
    the corner, then two more along a leg turned `angle` degrees (60 or 45)
    anticlockwise from there.
    """
    name = f"anglebeam_3x3_{angle}"
    c, s_ = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    holes = ((0, 0), (1, 0), (2, 0), (2 + c, s_), (2 + 2 * c, 2 * s_))
    prims = _official(cad_mesh, name, color)
    if prims is None:
        leg_a, _ = _flat(1, 3, BEAM_T, color)
        leg_b, _ = _flat(1, 3, BEAM_T, color)
        tf = Transform(euler(rz=float(angle)), (2.0, 0.0, 0.0))
        prims = leg_a + [p.xform(tf) for p in leg_b]
    return Part(name, f"3x3 {angle} Degree Angle Beam", color, prims, holes)


def _connector_chassis_large(color):
    """
    The large chassis corner connector: an L-shaped block one pitch thick
    (x = -0.5..0.5), its three holes through along x at (0, 0, 0),
    (0, 1, 0) and (0, 0, -1).  Two pegs point up +z from its top face over
    the first two holes, and two point out of its -y face beside the first
    and third - so it joins a beam lying flat to one standing across it.
    """
    name = "connector_chassis_large"
    holes = ((0, 0, 0), (0, 1, 0), (0, 0, -1))
    prims = _official(cad_mesh, name, color)
    if prims is None:
        prims = box(-0.5, -0.5, -0.5, 0.5, 1.5, 0.5, color)
        prims += box(-0.5, -0.5, -1.5, 0.5, 0.5, -0.5, color)
        for y in (0.0, 1.0):
            prims += moved(cylinder(PIN_R, 0.5, 0.98, color, segments=20),
                           (0.0, y, 0.0))
        for z in (0.0, -1.0):
            prims += along("y", cylinder(PIN_R, -0.98, -0.5, color,
                                         segments=20), (0.0, 0.0, z))
    return Part(name, "Large Chassis Corner Connector", color, prims, holes)


def _connector_triple(color):
    """
    The triple 2x wide 2x2 corner connector: a 2 x 1 x 2 pitch block with a
    square of four holes and a centre hole through it along y, and two pegs
    on each of three faces - top, bottom and +x.  The origin is the centre
    hole, so the holes are at x, z = +-0.5, and a block turned upside down
    puts every hole and peg back where it was.
    """
    name = "connector_triple_2x2"
    holes = tuple((x, 0, z) for x in (-0.5, 0.5) for z in (-0.5, 0.5)) + \
        ((0, 0, 0),)
    prims = _official(cad_mesh, name, color)
    if prims is None:
        prims = box(-1.0, -0.5, -1.0, 1.0, 0.5, 1.0, color)
        for x in (-0.5, 0.5):
            for z0, z1 in ((1.0, 1.48), (-1.48, -1.0)):
                prims += moved(cylinder(PIN_R, z0, z1, color, segments=20),
                               (x, 0.0, 0.0))
        for z in (-0.5, 0.5):
            prims += along("x", cylinder(PIN_R, 1.0, 1.48, color,
                                         segments=20), (0.0, 0.0, z))
    return Part(name, "Triple 2x Wide 2x2 Corner Connector", color, prims,
                holes)


def _face(x0, y0, x1, y1, holes, color, rot, offset):
    """
    A skin a fiftieth of a pitch thick whose +z face carries painted holes,
    turned by `rot` (degrees, X then Y then Z) and moved by `offset` onto
    whichever face of a housing they belong on.  `attach` only hangs decals
    on +z faces, so the holes are put on first and the face turned after.
    """
    skin = box(x0, y0, -0.02, x1, y1, 0.0, color)
    attach(skin, [d for x, y in holes for d in _painted_hole(x, y, 0.0, +1,
                                                              color)], +1)
    tf = Transform(euler(*rot), offset)
    return [s.xform(tf) for s in skin]


def _lid(x0, y0, x1, y1, z, color, panels):
    """
    A flat +z cap whose facet grid follows every panel's edges, so a screen
    or a button is a cell of the lid in its own colour rather than a solid
    sitting on it.  A raised panel loses the depth sort to the lid cells
    beside it, which paint across it in stripes; a flush one has nothing to
    lose to.  `panels` is a list of (x0, y0, x1, y1, color).
    """
    def lines(lo, hi, cuts):
        edges = sorted({lo, hi} | {c for c in cuts if lo < c < hi})
        out = [lo]
        for a, b in zip(edges, edges[1:]):
            n = max(1, math.ceil((b - a) - 1e-9))
            out += [a + (b - a) * k / n for k in range(1, n + 1)]
        return out

    xs = lines(x0, x1, [v for q in panels for v in (q[0], q[2])])
    ys = lines(y0, y1, [v for q in panels for v in (q[1], q[3])])
    out = []
    for a, b in zip(xs, xs[1:]):
        for c, d in zip(ys, ys[1:]):
            mx, my = (a + b) / 2, (c + d) / 2
            fill = next((q[4] for q in panels
                         if q[0] < mx < q[2] and q[1] < my < q[3]), color)
            out.append(Facet([(a, c, z), (b, c, z), (b, d, z), (a, d, z)],
                             fill, (0.0, 0.0, 1.0)))
    return out


def _motor(color):
    """
    VEX IQ (2nd gen) Smart Motor, lying face up: the face the shaft comes out
    of is the z = 0 plane, and the housing hangs down to z = -4.

    Drawn from VEX's STEP file (228-2560) when CAD detail is on.  This
    procedural form was measured off the build manuals before that, and the
    STEP file agrees with it to 0.03 pitch: a 4.5 x 2 pitch face with
    two rows of four mounting holes, a centre hole in each square of four,
    and the output in the centre hole between the third and fourth columns -
    off centre, toward the end the cable plugs into.  The housing is 4 pitch
    deep, so two motors back to back fill the 8 pitch between a drive base's
    rails.  Two pitch is also exactly the gap between two beams held apart
    by a 2x2 corner connector, which the BaseBot fits it into.
    """
    trim = PALETTE["vexgrey"]                 # the darker face and its rim
    dark = PALETTE["black"]
    holes = tuple((i, j, 0.0) for i in range(4) for j in range(2))
    face = _official(cad_mesh, "motor_face", trim)
    if face is not None:
        # VEX's STEP file lands on this frame exactly: 4.51 x 2.0 face,
        # 3.97 deep, the same holes and socket as drawn below
        p = (face + cad_mesh("motor_core", color) + cad_mesh("motor", color)
             + cad_mesh("motor_socket", dark))
        return Part("motor", "Smart Motor", color, p, holes)
    p = box(-0.5, -0.5, -0.45, 4.0, 1.5, -0.02, trim)
    p += _face(-0.5, -0.5, 4.0, 1.5,
               [(i, j) for i in range(4) for j in range(2)]
               + [(x, 0.5) for x in (0.5, 1.5, 3.5)],
               trim, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    socket = cylinder(0.36, 0.0, 0.03, dark, segments=22)
    p += moved(attach(socket, _bore_decal(0.03, +1, 0.0, dark, square=True),
                      +1), (2.5, 0.5, 0.0))
    p += box(-0.42, -0.42, -4.0, 3.92, 1.42, -0.45, color, top=False)
    p += box(3.92, 0.12, -3.3, 3.98, 0.88, -2.3, dark)            # cable port
    return Part("motor", "Smart Motor", color, p, holes)


SCREEN = "#e3ebc4"   # the brain's screen, pale as the manuals draw it


def _brain(color):
    """
    VEX IQ (2nd gen) Robot Brain, screen up.  Drawn from VEX's STEP file
    (228-6480) when CAD detail is on; this procedural form was measured off
    the build manuals, and the STEP file confirms its frame - the hole
    strips, the 6 pitch between them - though the real case is 8 pitch wide,
    not 8.5, and 2.7 tall.  A dark bumper band runs round the
    bottom, and its front and back faces each carry a strip of eight
    mounting holes, six ports above it in the grey body.  Hole 0 of the
    front strip is the origin, the front face is the y = 0 plane, and the
    back strip is the same eight holes at y = 6: the BaseBot pegs its brain
    to holes six apart, and the manuals draw the band six pitch deep against
    a strip seven pitch long.  The battery clips in underneath - see
    `_battery`.
    """
    trim = PALETTE["vexgrey"]
    dark = PALETTE["black"]
    holes = tuple((i, y, 0.0) for y in (0.0, 6.0) for i in range(8))
    body = _official(cad_mesh, "brain", color)
    if body is not None:
        # VEX's STEP file lands on this frame: 8 x 6 pitch, the two strips
        # of eight holes 6 apart, half a pitch above the bottom.  The port
        # band is its own shell lying on the case's: in two colours the
        # depth sort stripes one through the other, so it is drawn the
        # case's colour.  The lid is dark, as drawn below.
        p = (body + cad_mesh("brain_ports", color)
             + cad_mesh("brain_lid", dark)
             + cad_mesh("brain_screen", SCREEN)
             + cad_mesh("brain_buttons", trim))
        return Part("brain", "Robot Brain", color, p, holes)
    x0, x1, y1 = -0.75, 7.75, 6.0
    z0, z1, z2, z3 = -0.55, 0.55, 1.95, 2.3   # bumper, body, bezel, top
    # Every face is a flat panel grid, with the bands, ports and screen as
    # cells of it - not a box with skins laid over it.  A skin over a face
    # loses the depth sort to that face's own cells and comes out in
    # stripes; a face that IS its markings has nothing to lose to.
    bands = [(-99, z0, 99, z1, dark), (-99, z2, 99, z3, dark)]
    ports = [(0.25 + 1.3 * i - 0.36, 0.8, 0.25 + 1.3 * i + 0.36, 1.7, dark)
             for i in range(6)]
    # one cell per mounting hole, so no neighbouring cell paints over it
    cells = [(i - 0.5, z0, i + 0.5, z1, dark) for i in range(8)]
    holes = [d for i in range(8)
             for d in _painted_hole(i, 0.0, 0.0, +1, PALETTE["dgrey"])]

    def flip(panels):                      # v -> -v, for faces built upside down
        return [(a, -d, c, -b, k) for a, b, c, d, k in panels]

    def face(skin, rot, at):
        tf = Transform(euler(*rot), at)
        return [f.xform(tf) for f in skin]

    front = attach(_lid(x0, z0, x1, z3, 0.0, color, bands + cells + ports),
                   holes, +1)
    back = attach(_lid(x0, -z3, x1, -z0, 0.0, color,
                       flip(bands + cells + ports)),
                  [d for i in range(8)
                   for d in _painted_hole(i, 0.0, 0.0, +1, PALETTE["dgrey"])],
                  +1)
    p = face(front, (90.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    p += face(back, (-90.0, 0.0, 0.0), (0.0, y1, 0.0))
    # the ends: u runs along -z on the +x end and +z on the -x end
    p += face(_lid(-z3, 0.0, -z0, y1, 0.0, color,
                   [(-z1, -99, -z0, 99, dark), (-z3, -99, -z2, 99, dark)]),
              (0.0, 90.0, 0.0), (x1, 0.0, 0.0))
    p += face(_lid(z0, 0.0, z3, y1, 0.0, color,
                   [(z0, -99, z1, 99, dark), (z2, -99, z3, 99, dark)]),
              (0.0, -90.0, 0.0), (x0, 0.0, 0.0))
    p += _lid(x0, 0.0, x1, y1, z3, dark,
              [(2.3, 1.5, 4.7, 4.5, SCREEN)]                     # screen
              + [(x - 0.4, y - 0.3, x + 0.4, y + 0.3, trim)      # buttons
                 for x in (1.1, 5.9) for y in (1.9, 4.1)])
    return Part("brain", "Robot Brain", color, p,
                tuple((i, y, 0.0) for y in (0.0, y1) for i in range(8)))


CABLE_TAIL = 0.9   # how far the cable runs straight out of a plug


def _cable(mm, color):
    """
    One plugged-in end of a Smart Cable: the plug with its tip at the origin
    and a short tail running up +z, out of the port.  A whole cable's route
    depends on the robot, so a build draws the two ends where they plug in
    and gives the second end `qty=0`, which keeps the callout counting
    cables rather than ends.
    """
    p = box(-0.21, -0.17, 0.0, 0.21, 0.17, 0.55, "#e6e8ec", cell=0.3)
    p += box(-0.11, -0.11, 0.55, 0.11, 0.11, CABLE_TAIL, color, cell=0.3)
    return Part(f"cable_{mm}", f"{mm} mm Smart Cable", color, p,
                icon_rot=(90.0, 0.0, 0.0))


def cable_route(points, color=None, r=0.11, name=None, label="Smart Cable"):
    """
    A Smart Cable's run, as a round tube through `points` (world pitch) -
    a smooth curve through each in turn.  It is drawn, not counted: the
    cable's plugs, placed as `cable_N`, carry the count.  Pass the Part
    straight to `Step.add`.
    """
    from .geom import vadd, vcross, vmul, vnorm, vsub
    color = color_of(color or "black")
    pts = [tuple(float(v) for v in q) for q in points]
    # Named for where it starts, so two runs in a step are two parts.
    name = name or "cable route from " + ",".join(f"{v:g}" for v in pts[0])
    # Catmull-Rom through the points, the ends held straight.
    ext = [vsub(vmul(pts[0], 2), pts[1])] + pts + [vsub(vmul(pts[-1], 2), pts[-2])]
    path = []
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        for k in range(10):
            t = k / 10
            path.append(tuple(
                0.5 * (2 * p1[j] + (-p0[j] + p2[j]) * t
                       + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t * t
                       + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t ** 3)
                for j in range(3)))
    path.append(pts[-1])
    sides = 8
    rings = []
    up = (0.0, 0.0, 1.0)
    for i, c in enumerate(path):
        a = path[max(0, i - 1)]
        b = path[min(len(path) - 1, i + 1)]
        t = vnorm(vsub(b, a))
        ref = up if abs(t[2]) < 0.9 else (1.0, 0.0, 0.0)
        u = vnorm(vcross(t, ref))
        v = vcross(t, u)
        rings.append([vadd(c, vadd(vmul(u, r * math.cos(2 * math.pi * k / sides)),
                                   vmul(v, r * math.sin(2 * math.pi * k / sides))))
                      for k in range(sides)])
    prims = []
    for r0, r1 in zip(rings, rings[1:]):
        for k in range(sides):
            quad = [r0[k], r0[(k + 1) % sides], r1[(k + 1) % sides], r1[k]]
            prims.append(Facet(quad, color))
    part = Part(name, label, color, prims, plain=True)
    _MADE[name] = part
    return part


# Parts made on the spot, like a cable's run, by name: a parts callout or
# the drawing's description looks them up like any other.
_MADE = {}


def _touchled(color):
    """
    Touch LED (228-3010), button up: its underside, which pins to a beam, is
    the z = 0 plane, with the 2x2 square of pin holes at (0..1, 0..1) and a
    fifth in the middle; the body rises 2 pitch to the white button, whose
    top is z = 2.48.  Taken from VEX's STEP file.
    """
    holes = tuple((i, j, 0.0) for i in range(2) for j in range(2))
    white = PALETTE["white"]
    body = _official(cad_mesh, "touchled", color)
    if body is not None:
        return Part("touchled", "Touch LED", color,
                    body + cad_mesh("touchled_button", white), holes)
    p = box(-0.5, -0.5, 0.0, 1.5, 1.5, 0.82, PALETTE["vexgrey"])
    p += box(-0.48, -0.48, 0.82, 1.48, 1.48, 1.98, color)
    p += box(-0.46, -0.46, 1.98, 1.46, 1.46, 2.48, white)
    return Part("touchled", "Touch LED", color, p, holes)


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
    """
    The Robot Battery, drawn in the brain's own frame: placed at the brain's
    `at` and `rot`, it is the flat pack clipped in under the brain, set in
    from every edge.
    """
    # A closed box: drawn on its own in a parts callout, an open top shows
    # straight through to its floor.  Its top half sits up in the brain's
    # recess, out of sight once it is clipped in.
    p = box(0.6, 1.0, -1.05, 6.4, 5.0, -0.25, color)
    p += box(6.4, 2.2, -0.95, 6.75, 3.8, -0.4, PALETTE["dgrey"])
    return Part("battery", "Robot Battery", color, p)


# The 20 mm pulley's groove, which a string or belt rides in, in pitch.
PULLEY_GROOVE_R = {20: 10 / PITCH_MM}


def _pulley(size, color):
    """
    A VEX IQ pulley lying along +z, centred on the origin: two flanges with
    the string groove between them.  `size` is VEX's name for it, the groove
    diameter in mm; the flanges stand about 2.3 mm proud of the groove.
    """
    name = f"pulley_{size}"
    official = _official(cad_mesh, name, color)
    if official is not None:
        return Part(name, f"{size}mm Pulley", color, official,
                    icon_rot=FACE_CAMERA)
    groove = size / 2 / PITCH_MM
    rim = groove + 0.18
    p = cylinder(groove, -0.13, 0.13, color, segments=30)
    for z0, z1 in ((-0.25, -0.13), (0.13, 0.25)):
        p += cylinder(rim, z0, z1, color, segments=30)
    attach(p, _bore_decal(0.25, +1, 0.0, color, square=True), +1)
    attach(p, _bore_decal(-0.25, -1, 0.0, color, square=True), -1)
    return Part(name, f"{size}mm Pulley", color, p, icon_rot=FACE_CAMERA)


def _string_over_pulleys(span, drop, color):
    """
    A string laid over two 20 mm pulleys `span` apart along +x, hanging
    `drop` below their centres on the outside of each.  The origin is the
    first pulley's centre and everything lies in the xz plane, the plane the
    pulleys turn in.  A string is not a rigid part; this is one shape it
    takes, drawn as a thin cord.
    """
    r = PULLEY_GROOVE_R[20]
    cord = 0.07
    pts = [(-r, -drop)]
    for k in range(7):  # over the top of the first pulley, outside in
        a = math.radians(180 - 15 * k)
        pts.append((r * math.cos(a), r * math.sin(a)))
    for k in range(7):  # and over the second, inside out
        a = math.radians(90 - 15 * k)
        pts.append((span + r * math.cos(a), r * math.sin(a)))
    pts.append((span + r, -drop))
    prims = []
    for (x0, z0), (x1, z1) in zip(pts, pts[1:]):
        length = math.hypot(x1 - x0, z1 - z0)
        tf = Transform(euler(ry=math.degrees(math.atan2(x1 - x0, z1 - z0))),
                       (x0, 0.0, z0))
        prims += [q.xform(tf)
                  for q in cylinder(cord, 0.0, length, color, segments=8)]
    return Part(f"string_{span:g}x{drop:g}", "String", color, prims)


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
    "beam": "guide", "plate": "guide", "corner": "guide",
    "pin": "blue", "shaft": "steel", "capped": "black", "standoff": "black",
    "gear": "blue", "wheel": "rubber", "collar": "black",
    "spacer": "white", "washer": "white", "motor": "grey",
    "brain": "grey", "bumper": "dgrey", "distance": "dgrey",
    "battery": "black", "band": "green", "lbeam": "guide",
    "connector": "black", "plastic": "black", "cable": "black",
    "lockbeam": "black", "standoffconn": "guide", "motorshaft": "steel",
    "omni": "rubber", "anglebeam": "guide", "touchled": "grey",
    "pulley": "blue",
    "tyre": "rubber", "hub": "grey",
    "crankarm": "blue", "tractionlink": "black",
    "string": "#a7d3e6",  # the pale blue the build guides draw it
}

_RULES = [
    (re.compile(r"^beam_(\d+)x(\d+)$"), lambda m, c: _beam(int(m[1]), int(m[2]), c)),
    (re.compile(r"^beam_offset_4x4$"), lambda m, c: _offset_beam(c)),
    (re.compile(r"^plate_(\d+)x(\d+)$"), lambda m, c: _plate(int(m[1]), int(m[2]), c)),
    (re.compile(r"^corner_(\d+)x(\d+)$"), lambda m, c: _corner(int(m[1]), int(m[2]), c)),
    (re.compile(r"^lbeam_(\d+)x(\d+)$"), lambda m, c: _lbeam(int(m[1]), int(m[2]), c)),
    (re.compile(r"^connector_2w_(1x2|2x2)(_offset)?$"),
     lambda m, c: _connector(m[1], bool(m[2]), c)),
    (re.compile(r"^connector_2w_2x1$"), lambda m, c: _connector_2x1(c)),
    (re.compile(r"^connector_triple_2x2$"), lambda m, c: _connector_triple(c)),
    (re.compile(r"^connector_chassis_large$"), lambda m, c: _connector_chassis_large(c)),
    (re.compile(r"^anglebeam_3x3_(60|45)$"), lambda m, c: _anglebeam(int(m[1]), c)),
    (re.compile(r"^pin_0x2$"), lambda m, c: _pin_capped(c)),
    (re.compile(r"^pin_1x1$"), lambda m, c: _pin(1.00, "1x1 Connector Pin", "pin_1x1", c)),
    (re.compile(r"^pin_1x2$"), lambda m, c: _pin(1.50, "1x2 Connector Pin", "pin_1x2", c)),
    (re.compile(r"^pin_2x2$"), lambda m, c: _pin(2.00, "2x2 Connector Pin", "pin_2x2", c)),
    (re.compile(r"^shaft_(\d+)$"), lambda m, c: _shaft(int(m[1]), c)),
    (re.compile(r"^plastic_shaft_(\d+)$"), lambda m, c: _shaft(int(m[1]), c, "plastic_")),
    (re.compile(r"^capped_shaft_(\d+)$"), lambda m, c: _capped_shaft(int(m[1]), c)),
    (re.compile(r"^standoff_(\d+)$"), lambda m, c: _standoff(int(m[1]), c)),
    (re.compile(r"^standoff_half$"), lambda m, c: _standoff(0.5, c, "standoff_half")),
    (re.compile(r"^standoffconn_mini$"), lambda m, c: _standoff_connector(c)),
    (re.compile(r"^lockbeam_1x(\d+)$"), lambda m, c: _lockbeam(int(m[1]), c)),
    (re.compile(r"^crankarm_1x4$"), lambda m, c: _crank_arm(c)),
    (re.compile(r"^tractionlink$"), lambda m, c: _traction_link(c)),
    (re.compile(r"^plastic_motor_shaft_(\d+)$"), lambda m, c: _motor_shaft(int(m[1]), c)),
    (re.compile(r"^motorshaft_(\d+)$"), lambda m, c: _metal_motor_shaft(int(m[1]), c)),
    (re.compile(r"^lockbeam_round_2x2$"), lambda m, c: _lockbeam_round(c)),
    (re.compile(r"^lockbeam_2x2$"), lambda m, c: _lockbeam_square(c)),
    (re.compile(r"^connector_2w_1x2_offset_double$"),
     lambda m, c: _connector_double_1x2_offset(c)),
    (re.compile(r"^omni_(\d+)$"), lambda m, c: _omni(int(m[1]), c)),
    (re.compile(r"^gear_(\d+)$"), lambda m, c: _gear(int(m[1]), c)),
    (re.compile(r"^wheel_(\d+)$"), lambda m, c: _wheel(int(m[1]), c)),
    (re.compile(r"^tyre_(\d+)$"), lambda m, c: _wheel_half(int(m[1]), c, "tyre")),
    (re.compile(r"^hub_(\d+)$"), lambda m, c: _wheel_half(int(m[1]), c, "hub")),
    (re.compile(r"^band_(\d+)$"), lambda m, c: _rubber_band(int(m[1]), c)),
    (re.compile(r"^pulley_(20)$"), lambda m, c: _pulley(int(m[1]), c)),
    (re.compile(r"^string_(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)$"),
     lambda m, c: _string_over_pulleys(float(m[1]), float(m[2]), c)),
    (re.compile(r"^collar$"), lambda m, c: _collar(c)),
    (re.compile(r"^spacer$"), lambda m, c: _spacer(0.25, c)),
    (re.compile(r"^washer$"), lambda m, c: _spacer(0.12, c)),
    (re.compile(r"^motor$"), lambda m, c: _motor(c)),
    (re.compile(r"^brain$"), lambda m, c: _brain(c)),
    (re.compile(r"^bumper$"), lambda m, c: _bumper(c)),
    (re.compile(r"^touchled$"), lambda m, c: _touchled(c)),
    (re.compile(r"^distance$"), lambda m, c: _distance(c)),
    (re.compile(r"^battery$"), lambda m, c: _battery(c)),
    (re.compile(r"^cable_(\d+)$"), lambda m, c: _cable(int(m[1]), c)),
]

# How much geometry a part carries.
#
#   "cad"     the bundled official VEX meshes, where one exists: molded ribs,
#             real tooth profiles, recessed faces.  What you want on paper.
#   "simple"  the procedural approximations underneath.  Roughly a quarter of
#             the file size and noticeably plainer - worth it for a build that
#             has to load over a slow connection or go out by email.
#
# Every part has a procedural form; "cad" only overrides the handful that ship
# with real geometry, so nothing is unavailable at the lower level.
DETAIL_LEVELS = ("cad", "simple")
_detail = "cad"

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
    """The bundled CAD mesh for `key`, or None if it is off or absent."""
    return None if _detail == "simple" else fetch(key, color)


def get(name, color=None, detail=None):
    """
    Build (and cache) a part by name.  `color` overrides the default.

    `detail` overrides the global detail level for this one part, which is
    how a booklet draws the step's new parts from the official CAD meshes and
    everything already built from the cheaper procedural shapes.

    A name with an `@` in it is a stand-in: "beam_1x4@1x4 Crank Arm" draws a
    1x4 beam but calls it a crank arm wherever the part is named - the parts
    callouts and the drawing's description.  It is for a part iqdraw cannot
    draw yet, so the callout still sends a student to the right tray; say in
    the step's caption what the real part looks like.
    """
    global _detail
    if name in _MADE:
        return _MADE[name]
    level = detail or _detail
    key = (name, color, level)
    if key in _cache:
        return _cache[key]
    base, at, stand_in = name.partition("@")
    if at:
        part = get(base, color, detail)
        part = Part(name, stand_in, part.color, part.prims, part.holes,
                    part.icon_rot)
        _cache[key] = part
        return part
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
