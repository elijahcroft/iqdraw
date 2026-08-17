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

import math
import re
from dataclasses import dataclass

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
# ============================================================================

# Colours.  CHECK THESE AGAINST YOUR OWN KIT - VEX has changed plastic colours
# between runs, and a wrong colour actively misleads a student.  Any placement
# can override with `color:`.
PALETTE = {
    "white": "#eef0f3",
    "steel": "#c6cbd2",
    "grey": "#9ba2ac",
    "dgrey": "#565d67",
    "black": "#31353c",
    "green": "#5cb646",
    "blue": "#2f8fd6",
    "orange": "#ef8b26",
    "red": "#d9483c",
    "yellow": "#f0c22e",
    "purple": "#8b62c8",
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

    prims = extrude(
        rounded_rect(x0, y0, x1, y1, (CORNER_R,) * 4),
        -t / 2, t / 2, color,
        cap_top=False, cap_bottom=False, rim_top=True, rim_bottom=True,
    )

    eps = 1e-9
    for i in range(length):
        for j in range(w):
            cx0, cy0, cx1, cy1 = i - 0.5, j - 0.5, i + 0.5, j + 0.5
            at_x0, at_x1 = abs(cx0 - x0) < eps, abs(cx1 - x1) < eps
            at_y0, at_y1 = abs(cy0 - y0) < eps, abs(cy1 - y1) < eps
            radii = (
                CORNER_R if (at_x0 and at_y0) else 0.0,
                CORNER_R if (at_x1 and at_y0) else 0.0,
                CORNER_R if (at_x1 and at_y1) else 0.0,
                CORNER_R if (at_x0 and at_y1) else 0.0,
            )
            cell = rounded_rect(cx0, cy0, cx1, cy1, radii)

            if (i, j) not in drilled:
                prims.append(Facet([(x, y, t / 2) for x, y in cell], color,
                                   (0.0, 0.0, 1.0)))
                prims.append(Facet([(x, y, -t / 2) for x, y in reversed(cell)],
                                   color, (0.0, 0.0, -1.0)))
                continue

            ring = _resample(cell, CELL_PTS)
            prims += _annulus(ring, i, j, HOLE_R, t / 2, +1, color)
            prims += _annulus(ring, i, j, HOLE_R, -t / 2, -1, color)
            # Looking down a hole at this angle you see its far inner wall, so
            # the bore needs an inward-facing cylinder - a dark disc at the
            # bottom projects below the opening and never lines up with it.
            # Reversing the profile flips the wall normals to point inward.
            disc = circle_profile(HOLE_R, 12, i, j)
            prims += extrude(list(reversed(disc)), -t / 2, t / 2, bore,
                             cap_top=False, cap_bottom=False, edges=False,
                             zcell=t)  # too short to need banding
            prims.append(Facet([(x, y, -t / 2) for x, y in disc], bore,
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


def _square_bar(across, z0, z1, color, corner=0.06):
    prof = rounded_rect(-across / 2, -across / 2, across / 2, across / 2,
                        (corner,) * 4)
    return extrude(prof, z0, z1, color)


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
    r = teeth / 24.0
    t = 0.40
    hz = t / 2 + 0.20
    hub_r = min(0.40, r * 0.72)
    hub_c = mix_color(color, "#3c424b", 0.55)
    p = extrude(gear_profile(teeth, r), -t / 2, t / 2, color)
    hub_up = attach(cylinder(hub_r, t / 2, hz, hub_c, segments=22),
                    _bore_decal(hz, +1, 0.0, hub_c, square=True), +1)
    hub_dn = attach(cylinder(hub_r, -hz, -t / 2, hub_c, segments=22),
                    _bore_decal(-hz, -1, 0.0, hub_c, square=True), -1)
    return Part(f"gear_{teeth}", f"{teeth}-Tooth Gear", color,
                p + hub_up + hub_dn, icon_rot=FACE_CAMERA)


def _wheel(dia_mm, color):
    r = dia_mm / PITCH_MM / 2.0
    width = 0.95
    hub_c = PALETTE["steel"]
    zc = width / 2 + 0.16
    p = cylinder(r, -width / 2, width / 2, color, segments=36)          # tread
    p += cylinder(r * 0.93, -width / 2 - 0.04, width / 2 + 0.04, color, segments=36)
    p += cylinder(r * 0.58, -width / 2 - 0.06, width / 2 + 0.06, hub_c, segments=30)
    boss = attach(cylinder(0.42, -zc, zc, hub_c, segments=22),
                  _bore_decal(zc, +1, 0.0, hub_c, square=True), +1)
    attach(boss, _bore_decal(-zc, -1, 0.0, hub_c, square=True), -1)
    return Part(f"wheel_{dia_mm}", f"{dia_mm}mm Wheel", color, p + boss,
                icon_rot=(90.0, 0.0, 0.0))


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
    trim = PALETTE["dgrey"]
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
    p += along("x", _square_bar(SHAFT_W, 0.0, 0.75, PALETTE["black"]),
               (2.5, 0.5, 0.2))                                      # output shaft
    return Part("motor", "Smart Motor", color, p,
                tuple((i, j, 0.0) for i in range(3) for j in range(2)))


def _brain(color):
    """VEX IQ (2nd gen) Robot Brain - recognisable proportions, not exact."""
    screen_c = PALETTE["screen"]
    trim = PALETTE["dgrey"]
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
    lens = PALETTE["dgrey"]
    p = box(-0.5, -0.5, -0.4, 1.5, 0.9, 0.6, color)
    for x in (0.05, 0.95):
        p += along("y", cylinder(0.24, 0.0, 0.12, lens, segments=20),
                   (x, 0.9, 0.1))
    return Part("distance", "Distance Sensor", color, p)


def _battery(color):
    p = box(-0.5, -0.5, -0.5, 3.5, 2.5, 0.6, color)
    p += box(3.5, 0.4, -0.2, 3.7, 1.6, 0.3, PALETTE["dgrey"])
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
    "beam": "white", "plate": "white", "corner": "white",
    "pin": "green", "shaft": "dgrey", "standoff": "steel",
    "gear": "grey", "wheel": "black", "collar": "dgrey",
    "spacer": "steel", "washer": "steel", "motor": "white",
    "brain": "black", "bumper": "white", "distance": "white",
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
    (re.compile(r"^spacer$"), lambda m, c: _spacer(0.35, c)),
    (re.compile(r"^washer$"), lambda m, c: _spacer(0.12, c)),
    (re.compile(r"^motor$"), lambda m, c: _motor(c)),
    (re.compile(r"^brain$"), lambda m, c: _brain(c)),
    (re.compile(r"^bumper$"), lambda m, c: _bumper(c)),
    (re.compile(r"^distance$"), lambda m, c: _distance(c)),
    (re.compile(r"^battery$"), lambda m, c: _battery(c)),
]

_cache = {}


def get(name, color=None):
    """Build (and cache) a part by name.  `color` overrides the default."""
    key = (name, color)
    if key in _cache:
        return _cache[key]
    family = name.split("_")[0]
    resolved = color_of(color or _DEFAULT_COLOR.get(family, "white"))
    for pattern, make in _RULES:
        m = pattern.match(name)
        if m:
            part = make(m, resolved)
            _cache[key] = part
            return part
    raise KeyError(
        f"unknown part {name!r}. Known families: "
        + ", ".join(sorted(_DEFAULT_COLOR))
    )


def known_families():
    return sorted(_DEFAULT_COLOR)
