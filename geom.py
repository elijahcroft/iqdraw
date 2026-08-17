"""
Geometry core for VEX IQ build-instruction diagrams.

Units
-----
Everything is in PITCH units: 1 unit = one VEX IQ hole spacing = 12.7 mm.
VEX documents that every structural part is an integer multiple of this pitch,
which is what makes a pure integer-grid renderer possible.

Frame
-----
Right-handed, +z is up.  Parts are placed by HOLE CENTRE, not by corner, so a
connector pin and the hole it passes through share the same coordinates.  A
1x8 beam placed at (0, 0, 0) has holes at (0,0,0) through (7,0,0).

View
----
True isometric.  The camera sits on the (+1, +1, +1) diagonal, so the only
faces ever visible are +x, +y and +z.  Painter's algorithm sorts by x+y+z.

Outlines
--------
Instruction art needs a dark line on every hard edge and no line across a
smooth curve.  Solids therefore emit `Edge` primitives alongside their facets,
one per profile edge, tagged with the two faces that meet there.  At render
time an edge is drawn only if the crease is sharp enough AND at least one of
its two faces points at the camera.  That gives clean beam outlines, a rim
line around every cylinder, and no wireframe mess on tessellated curves.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

PITCH_MM = 12.7

# --------------------------------------------------------------- vector maths


def vadd(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vmul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def vdot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vcross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def vlen(a):
    return math.sqrt(vdot(a, a))


def vnorm(a):
    n = vlen(a)
    return (0.0, 0.0, 0.0) if n < 1e-12 else vmul(a, 1.0 / n)


def polygon_normal(pts):
    """Newell's method - robust for near-degenerate and non-planar polygons."""
    nx = ny = nz = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0, z0 = pts[i]
        x1, y1, z1 = pts[(i + 1) % n]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    return vnorm((nx, ny, nz))


def centroid(pts):
    n = float(len(pts))
    return (
        sum(p[0] for p in pts) / n,
        sum(p[1] for p in pts) / n,
        sum(p[2] for p in pts) / n,
    )


# ------------------------------------------------------------------ transform

IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def mat_apply(m, v):
    return (
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    )


def mat_mul(a, b):
    return tuple(
        tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
        for i in range(3)
    )


def rot_x(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c))


def rot_y(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c))


def rot_z(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


def euler(rx=0.0, ry=0.0, rz=0.0):
    """Rotation applied X, then Y, then Z.  Degrees."""
    return mat_mul(rot_z(rz), mat_mul(rot_y(ry), rot_x(rx)))


@dataclass(frozen=True)
class Transform:
    rot: tuple = IDENTITY
    pos: tuple = (0.0, 0.0, 0.0)

    def point(self, p):
        return vadd(mat_apply(self.rot, p), self.pos)

    def direction(self, d):
        return mat_apply(self.rot, d)

    def then(self, outer: "Transform") -> "Transform":
        """Self applied first, then `outer`."""
        return Transform(
            mat_mul(outer.rot, self.rot),
            vadd(mat_apply(outer.rot, self.pos), outer.pos),
        )


# ----------------------------------------------------------------- projection

_C30 = math.cos(math.radians(30.0))
_S30 = 0.5


def project(p):
    """(x, y, z) in grid units -> (sx, sy) in screen units (y already flipped)."""
    x, y, z = p
    return ((x - y) * _C30, (x + y) * _S30 - z)


def depth(p):
    """Distance toward the camera.  Larger = nearer = drawn later."""
    return p[0] + p[1] + p[2]


VIEW = vnorm((1.0, 1.0, 1.0))

# -------------------------------------------------------------------- shading
# Calibrated so a +z face reads 1.00, +x reads 0.82, +y reads 0.68, and any
# face turned away sits on the ambient floor.  Raise GAIN for more contrast.

LIGHT = vnorm((0.67, 0.42, 1.00))
AMBIENT = 0.45
GAIN = 0.70


def shade_factor(normal):
    return AMBIENT + GAIN * max(0.0, vdot(normal, LIGHT))


# --------------------------------------------------------------------- colour


def hex_to_rgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def luma(h):
    r, g, b = hex_to_rgb(h)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def scale_color(h, f):
    r, g, b = hex_to_rgb(h)
    return rgb_to_hex((r * f, g * f, b * f))


def mix_color(h, other, t):
    """Blend `h` toward `other` by t in [0, 1]."""
    a, b = hex_to_rgb(h), hex_to_rgb(other)
    return rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def fade(h, amount):
    """Wash a colour out toward pale grey - used for already-built steps."""
    return mix_color(h, "#c9ccd2", amount)


def outline_color(base):
    """
    A line colour that stays visible on both pale and dark parts: push light
    parts toward near-black, and dark parts toward a mid grey instead.
    """
    return mix_color(base, "#585f6b", 0.55) if luma(base) < 80 else mix_color(
        base, "#141820", 0.76
    )


# ------------------------------------------------------------------ primitives


@dataclass
class Facet:
    """A flat polygon, shaded by its normal."""

    pts: list
    color: str
    normal: tuple = None
    decals: list = field(default_factory=list)
    shade: float = None  # override the computed lambert term

    def __post_init__(self):
        if self.normal is None:
            self.normal = polygon_normal(self.pts)

    def xform(self, tf: Transform) -> "Facet":
        return Facet(
            [tf.point(p) for p in self.pts],
            self.color,
            tf.direction(self.normal),
            [d.xform(tf) for d in self.decals],
            self.shade,
        )

    @property
    def key(self):
        return depth(centroid(self.pts))


@dataclass
class Disc:
    """A circle lying in a plane.  Renders as a true SVG ellipse, no polygons."""

    center: tuple
    u: tuple  # in-plane unit vector
    v: tuple  # in-plane unit vector, perpendicular to u
    r: float
    color: str
    normal: tuple = None
    stroke: bool = True
    shade: float = None

    def __post_init__(self):
        if self.normal is None:
            self.normal = vnorm(vcross(self.u, self.v))

    def xform(self, tf: Transform) -> "Disc":
        return Disc(
            tf.point(self.center),
            tf.direction(self.u),
            tf.direction(self.v),
            self.r,
            self.color,
            tf.direction(self.normal),
            self.stroke,
            self.shade,
        )

    @property
    def key(self):
        return depth(self.center)


@dataclass
class Edge:
    """
    A candidate outline segment.  `na`/`nb` are the normals of the two faces
    meeting here; the renderer drops the edge when the crease is soft or when
    both faces point away from the camera.
    """

    a: tuple
    b: tuple
    color: str
    na: tuple
    nb: tuple
    width: float = 1.0

    def xform(self, tf: Transform) -> "Edge":
        return Edge(
            tf.point(self.a),
            tf.point(self.b),
            self.color,
            tf.direction(self.na),
            tf.direction(self.nb),
            self.width,
        )

    @property
    def key(self):
        return depth(centroid((self.a, self.b)))


# ---------------------------------------------------- 2D profile constructors


def _arc(cx, cy, r, start, sweep, segments):
    return [
        (cx + r * math.cos(start + sweep * i / segments),
         cy + r * math.sin(start + sweep * i / segments))
        for i in range(segments + 1)
    ]


def rounded_rect(x0, y0, x1, y1, radii, segments=4):
    """
    CCW 2D profile.  `radii` is (bottom-left, bottom-right, top-right,
    top-left); 0 gives a sharp corner.
    """
    rbl, rbr, rtr, rtl = radii
    pts = []
    pts += _arc(x1 - rbr, y0 + rbr, rbr, -math.pi / 2, math.pi / 2, segments) if rbr \
        else [(x1, y0)]
    pts += _arc(x1 - rtr, y1 - rtr, rtr, 0.0, math.pi / 2, segments) if rtr \
        else [(x1, y1)]
    pts += _arc(x0 + rtl, y1 - rtl, rtl, math.pi / 2, math.pi / 2, segments) if rtl \
        else [(x0, y1)]
    pts += _arc(x0 + rbl, y0 + rbl, rbl, math.pi, math.pi / 2, segments) if rbl \
        else [(x0, y0)]
    return pts


def circle_profile(r, segments=24, cx=0.0, cy=0.0):
    return [
        (cx + r * math.cos(2 * math.pi * i / segments),
         cy + r * math.sin(2 * math.pi * i / segments))
        for i in range(segments)
    ]


def gear_profile(teeth, pitch_r, tooth_depth=0.19):
    """
    Trapezoidal spur-gear outline.  VEX IQ gears mesh on whole-pitch centre
    distances, which falls out of pitch_r = teeth / 24 (see parts.py).

    Tooth depth is ABSOLUTE, not a fraction of the radius: gears in a meshing
    family all share one module, so a 60-tooth gear has the same size teeth as
    a 12-tooth one, just more of them.
    """
    tip = pitch_r + tooth_depth
    root = pitch_r - tooth_depth
    step = 2 * math.pi / teeth
    pts = []
    for i in range(teeth):
        b = i * step
        for frac, r in ((0.00, root), (0.30, tip), (0.70, tip), (0.84, root)):
            a = b + step * frac
            pts.append((r * math.cos(a), r * math.sin(a)))
    return pts


# ------------------------------------------------------- solid constructors

CREASE_COS = math.cos(math.radians(26.0))  # sharper than this gets an outline


def _cap(profile, z, up, color, cap_cell):
    """
    A cap surface, fanned into cells from the profile centre once it grows
    past `cap_cell` across.  One big polygon carries a single depth value, so
    a 60-tooth gear's face would sort by its hub alone and let the beam
    underneath paint straight through it.
    """
    cx = sum(p[0] for p in profile) / len(profile)
    cy = sum(p[1] for p in profile) / len(profile)
    reach = max(math.hypot(x - cx, y - cy) for x, y in profile)
    if reach * 2 <= cap_cell:
        pts = [(x, y, z) for x, y in profile]
        if up < 0:
            pts.reverse()
        return [Facet(pts, color, (0.0, 0.0, float(up)))]

    # A dense profile (a gear) already gives fine depth granularity around the
    # rim, so extra rings would only multiply facet count for no benefit.
    rings = 1 if len(profile) > 60 else max(1, int(round(reach / cap_cell)))
    out = []
    n = len(profile)
    for i in range(n):
        ax, ay = profile[i]
        bx, by = profile[(i + 1) % n]
        for k in range(rings):
            t0, t1 = k / rings, (k + 1) / rings
            pa1 = (cx + (ax - cx) * t1, cy + (ay - cy) * t1)
            pb1 = (cx + (bx - cx) * t1, cy + (by - cy) * t1)
            if k == 0:
                pts = [(cx, cy, z), (pa1[0], pa1[1], z), (pb1[0], pb1[1], z)]
            else:
                pa0 = (cx + (ax - cx) * t0, cy + (ay - cy) * t0)
                pb0 = (cx + (bx - cx) * t0, cy + (by - cy) * t0)
                pts = [(pa0[0], pa0[1], z), (pa1[0], pa1[1], z),
                       (pb1[0], pb1[1], z), (pb0[0], pb0[1], z)]
            if up < 0:
                pts.reverse()
            out.append(Facet(pts, color, (0.0, 0.0, float(up))))
    return out


def extrude(profile, z0, z1, color, cap_top=True, cap_bottom=True,
            edges=True, edge_width=1.0, rim_top=None, rim_bottom=None,
            cap_cell=1.2, zcell=0.4):
    """
    Extrude a CCW 2D profile along +z into facets plus crease edges.
    Returns a flat list of primitives.

    `rim_top` / `rim_bottom` default to the matching cap flag.  Set them True
    with the cap off when something else supplies the cap surface - beams draw
    their faces as per-hole cells but still want one clean outline.
    """
    rim_top = cap_top if rim_top is None else rim_top
    rim_bottom = cap_bottom if rim_bottom is None else rim_bottom
    out = []
    n = len(profile)
    wall_normals = []
    # Bands of wall, not one full-height quad.  A pin or shaft pushed through
    # a beam is interpenetrating geometry, which no back-to-front ordering can
    # resolve exactly; short bands at least sort at the height they occupy, so
    # the buried part of a shaft loses to the beam instead of painting over it.
    zs = _split_span(z0, z1, zcell)
    for i in range(n):
        ax, ay = profile[i]
        bx, by = profile[(i + 1) % n]
        nrm = vnorm((by - ay, -(bx - ax), 0.0))
        for k in range(len(zs) - 1):
            za, zb = zs[k], zs[k + 1]
            out.append(
                Facet([(ax, ay, za), (bx, by, za), (bx, by, zb), (ax, ay, zb)],
                      color, nrm)
            )
        wall_normals.append(nrm)

    if cap_top:
        out += _cap(profile, z1, +1, color, cap_cell)
    if cap_bottom:
        out += _cap(profile, z0, -1, color, cap_cell)

    if edges:
        ec = outline_color(color)
        for i in range(n):
            ax, ay = profile[i]
            bx, by = profile[(i + 1) % n]
            nw = wall_normals[i]
            # top and bottom rim: wall against cap, always a hard crease
            if rim_top:
                out.append(Edge((ax, ay, z1), (bx, by, z1), ec, nw,
                                (0.0, 0.0, 1.0), edge_width))
            if rim_bottom:
                out.append(Edge((ax, ay, z0), (bx, by, z0), ec, nw,
                                (0.0, 0.0, -1.0), edge_width))
            # vertical seam: only where the profile actually turns a corner
            nxt = wall_normals[(i + 1) % n]
            if vdot(nw, nxt) < CREASE_COS:
                out.append(Edge((bx, by, z0), (bx, by, z1), ec, nw, nxt, edge_width))
    return out


def _split_span(a, b, cell):
    n = max(1, int(math.ceil(abs(b - a) / cell - 1e-9)))
    return [a + (b - a) * i / n for i in range(n + 1)]


def box(x0, y0, z0, x1, y1, z1, color, cell=1.0, edges=True, edge_width=1.0):
    """
    Axis-aligned box, subdivided into cells no larger than `cell` so the
    painter's-algorithm depth sort stays accurate.  Without this a single wide
    facet - a brain lid, a motor body - can sort ahead of a small part sitting
    on its far end and paint straight over it.
    """
    xs = _split_span(x0, x1, cell)
    ys = _split_span(y0, y1, cell)
    profile = (
        [(x, y0) for x in xs[:-1]]
        + [(x1, y) for y in ys[:-1]]
        + [(x, y1) for x in reversed(xs[1:])]
        + [(x0, y) for y in reversed(ys[1:])]
    )
    out = extrude(profile, z0, z1, color, cap_top=False, cap_bottom=False,
                  rim_top=True, rim_bottom=True, edges=edges,
                  edge_width=edge_width)
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            a, b, c, d = xs[i], xs[i + 1], ys[j], ys[j + 1]
            out.append(Facet([(a, c, z1), (b, c, z1), (b, d, z1), (a, d, z1)],
                             color, (0.0, 0.0, 1.0)))
            out.append(Facet([(a, d, z0), (b, d, z0), (b, c, z0), (a, c, z0)],
                             color, (0.0, 0.0, -1.0)))
    return out


def _contains_xy(poly, x, y):
    inside = False
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i][0], poly[i][1]
        x1, y1 = poly[(i + 1) % n][0], poly[(i + 1) % n][1]
        if (y0 > y) != (y1 > y):
            xi = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < xi:
                inside = not inside
    return inside


def attach(prims, decals, up=1):
    """
    Ride decals on the outermost +z (or -z) facet *directly underneath each
    one*.  Riding a decal on its host is the only way to guarantee it draws
    immediately after; and it has to be the right host, because a subdivided
    lid is many facets and the later cells would otherwise paint over decals
    parked on the first one.
    """
    caps = [p for p in prims
            if isinstance(p, Facet) and p.normal[2] * up > 0.9]
    if not caps:
        return prims
    outermost = max(caps, key=lambda f: f.pts[0][2] * up)
    zmax = outermost.pts[0][2] * up
    caps = [f for f in caps if abs(f.pts[0][2] * up - zmax) < 1e-9]

    for d in decals:
        c = d.center if isinstance(d, Disc) else centroid(d.pts)
        host = next((f for f in caps if _contains_xy(f.pts, c[0], c[1])),
                    outermost)
        host.decals = list(host.decals) + [d]
    return prims


def cylinder(r, z0, z1, color, segments=24, **kw):
    return extrude(circle_profile(r, segments), z0, z1, color, **kw)


# Rotations carrying a locally +z-aligned solid onto a world axis.
AXIS_ROT = {"z": IDENTITY, "x": rot_y(90), "y": rot_x(-90)}


def along(axis, solids, offset=(0.0, 0.0, 0.0)):
    """Reorient solids built along +z so they run along `axis` instead."""
    tf = Transform(AXIS_ROT[axis], offset)
    return [s.xform(tf) for s in solids]


def moved(solids, offset):
    tf = Transform(IDENTITY, offset)
    return [s.xform(tf) for s in solids]
