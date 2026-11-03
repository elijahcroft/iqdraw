"""
How parts join: the holes in them, the rods that go through those holes, and
the space each part fills.

The drawing geometry in `parts.py` is for looking at.  This is for reasoning
about - one small, exact model per part family, in the part's own coordinates:

    holes     a centre, an axis, how deep it runs, and whether it is round
              (spins on a shaft) or square (locks to one)
    rod       the centre line of a pin or shaft, end to end
    envelope  the box or cylinder the part fills, at its NOMINAL size - a
              beam is 0.5 thick here, not the 0.48 its molded rim draws at,
              because 0.5 is what two stacked beams actually measure

Placing parts relative to each other (`spec.Ref`), the joint checks
(`check.py`) and `iqdraw --inspect` all read this one model, so they can never
disagree about where a hole is.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .geom import Disc, Edge, Facet, mat_apply, vadd, vsub
from .parts import BEAM_T, PLATE_T, _gear_holes, get

ROUND, SQUARE = "round", "square"

# A rod is in a hole when its centre line runs within this of the hole's
# centre, parallel to it, and reaches at least ENGAGE into it.  Generous
# enough for 0.1-place arithmetic, far tighter than the half-hole slip it
# exists to catch.
ON_AXIS = 0.08
ENGAGE = 0.05
PARALLEL = 0.995

_SIZE = re.compile(r"^(beam|plate|corner)_(\d+)x(\d+)$")
_LEN = re.compile(r"^(shaft|standoff|pin|gear|wheel|band)_(\d+)(?:x(\d+))?$")

PIN_SPAN = {"pin_1x1": 1.0, "pin_1x2": 1.5, "pin_2x2": 2.0}
CYLINDERS = ("gear", "wheel", "collar", "spacer", "washer")
# Parts drawn for recognition only, with no hole positions to check against.
UNMODELLED = ("brain", "bumper", "distance", "battery")
# The parts this model knows the holes and solid of.  Anything else - an
# L-beam, a lock beam, an omni wheel, a plastic shaft - is left to the eye
# for now: a pin pushed into one counts as a joint, nothing is called solid,
# colliding or loose against it, and it is not a rod.
_MODELLED = re.compile(
    r"^(?:(?:beam|plate|corner)_\d+x\d+|pin_(?:1x1|1x2|2x2)|"
    r"(?:shaft|standoff|gear|wheel|band)_\d+|collar|spacer|washer|motor)$")


def modelled(name):
    """Does the joint model know this part's holes and shape?"""
    return bool(_MODELLED.match(name)) or family(name) in UNMODELLED


def opaque(name):
    """A part the joint model knows nothing about: see `_MODELLED`."""
    return not modelled(name)


def family(name):
    return name.split("_")[0]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _scale(v, k):
    return (v[0] * k, v[1] * k, v[2] * k)


def _norm(v):
    n = math.sqrt(_dot(v, v)) or 1.0
    return _scale(v, 1.0 / n)


# ------------------------------------------------------------- local model


@dataclass(frozen=True)
class Hole:
    center: tuple
    axis: tuple
    half: float          # half its depth along the axis
    shape: str = ROUND


_geom_boxes = {}


def geometry_box(name):
    """The drawn part's own bounding box, from the procedural geometry."""
    hit = _geom_boxes.get(name)
    if hit is not None:
        return hit
    pts = []
    for prim in get(name, detail="simple").prims:
        if isinstance(prim, Facet):
            pts.extend(prim.pts)
        elif isinstance(prim, Edge):
            pts.extend((prim.a, prim.b))
        elif isinstance(prim, Disc):
            cx, cy, cz = prim.center
            pts.extend(((cx - prim.r, cy - prim.r, cz - prim.r),
                        (cx + prim.r, cy + prim.r, cz + prim.r)))
    box = (min(p[0] for p in pts), min(p[1] for p in pts),
           min(p[2] for p in pts), max(p[0] for p in pts),
           max(p[1] for p in pts), max(p[2] for p in pts))
    _geom_boxes[name] = box
    return box


def local_boxes(name):
    """The space a part fills, as one or more boxes in its own coordinates."""
    m = _SIZE.match(name)
    if m:
        fam, a, b = m[1], int(m[2]), int(m[3])
        if fam == "corner":
            # `a` holes along +x, `b` holes up +z from the shared corner.
            # The drawing runs the upright on down through the foot to
            # z=-0.5 so the elbow reads solid; the part itself stops at the
            # foot's underside.
            return [(-0.5, -0.5, -0.25, a - 0.5, 0.5, 0.25),
                    (-0.25, -0.5, -0.25, 0.25, 0.5, b + 0.5)]
        h = (BEAM_T if fam == "beam" else PLATE_T) / 2
        return [(-0.5, -0.5, -h, b - 0.5, a - 0.5, h)]
    m = _LEN.match(name)
    if m and m[1] == "standoff":
        x0, y0, _, x1, y1, _ = geometry_box(name)
        return [(x0, y0, 0.0, x1, y1, float(m[2]))]
    return [geometry_box(name)]


def local_holes(name):
    if opaque(name):
        return []
    fam = family(name)
    z = (0.0, 0.0, 1.0)
    m = _SIZE.match(name)
    if m:
        a, b = int(m[2]), int(m[3])
        if fam == "corner":
            return ([Hole((float(i), 0.0, 0.0), z, 0.25) for i in range(a)]
                    + [Hole((0.0, 0.0, float(i)), (1.0, 0.0, 0.0), 0.25)
                       for i in range(1, b + 1)])
        h = (BEAM_T if fam == "beam" else PLATE_T) / 2
        return [Hole((float(x), float(y), 0.0), z, h)
                for x in range(b) for y in range(a)]
    if fam == "gear":
        teeth = int(name.split("_")[1])
        return ([Hole((0.0, 0.0, 0.0), z, 0.25, SQUARE)]
                + [Hole((x, y, 0.0), z, 0.25) for x, y in _gear_holes(teeth)])
    if fam == "wheel":
        half = geometry_box(name)[5]
        return ([Hole((0.0, 0.0, 0.0), z, half, SQUARE)]
                + [Hole((h[0], h[1], 0.0), z, half)
                   for h in get(name, detail="simple").holes])
    if fam == "collar":
        return [Hole((0.0, 0.0, 0.0), z, geometry_box(name)[5], SQUARE)]
    if fam in ("spacer", "washer"):
        return [Hole((0.0, 0.0, 0.0), z, geometry_box(name)[5])]
    if fam == "standoff":
        n = float(name.split("_")[1])
        return [Hole((0.0, 0.0, 0.25), z, 0.25),
                Hole((0.0, 0.0, n - 0.25), z, 0.25)]
    if fam == "motor":
        # Mounting holes through the body, and the square drive socket.
        return ([Hole((float(i), float(j), 0.2), z, 0.7)
                 for i in range(3) for j in range(2)]
                + [Hole((2.5, 0.5, 0.2), (1.0, 0.0, 0.0), 0.25, SQUARE)])
    return []


def local_rod(name):
    """(start, end, shape) of a pin's or shaft's centre line, or None."""
    if opaque(name):
        return None
    if name in PIN_SPAN:
        h = PIN_SPAN[name] / 2
        return (0.0, 0.0, -h), (0.0, 0.0, h), ROUND
    m = _LEN.match(name)
    if m and m[1] == "shaft":
        return (0.0, 0.0, -0.5), (0.0, 0.0, int(m[2]) - 0.5), SQUARE
    return None


def is_axial(name):
    """Built along +z, so `axis=` reorients it: pins, shafts, gears, ..."""
    return (local_rod(name) is not None
            or family(name) in CYLINDERS + ("standoff",))


# ------------------------------------------------------------- world model


def world_box(tf, box):
    """
    A local box moved by `tf`, re-fitted.  Exact for the quarter-turns real
    builds use; an over-estimate otherwise, which only ever makes a check
    quieter.
    """
    x0, y0, z0, x1, y1, z1 = box
    pts = [tf.point((x, y, z)) for x in (x0, x1) for y in (y0, y1)
           for z in (z0, z1)]
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            min(p[2] for p in pts), max(p[0] for p in pts),
            max(p[1] for p in pts), max(p[2] for p in pts))


def union(boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            min(b[2] for b in boxes), max(b[3] for b in boxes),
            max(b[4] for b in boxes), max(b[5] for b in boxes))


def overlap(a, b):
    """Per-axis overlap depths of two boxes; negative means a gap."""
    return tuple(min(a[i + 3], b[i + 3]) - max(a[i], b[i]) for i in range(3))


def to_local(tf, p):
    """World point -> the part's own coordinates.  Rotations are orthonormal
    (mirrors included), so the inverse is the transpose."""
    d = vsub(p, tf.pos)
    r = tf.rot
    return (r[0][0] * d[0] + r[1][0] * d[1] + r[2][0] * d[2],
            r[0][1] * d[0] + r[1][1] * d[1] + r[2][1] * d[2],
            r[0][2] * d[0] + r[1][2] * d[1] + r[2][2] * d[2])


@dataclass
class Placed:
    """One part in the finished model, measured in world coordinates."""

    index: int
    step: int
    name: str
    color: object
    tf: object
    boxes: list = field(default_factory=list)
    holes: list = field(default_factory=list)   # [Hole] in world coordinates
    rod: tuple = None                            # (a, b, shape) in world

    @property
    def box(self):
        return union(self.boxes)

    @property
    def family(self):
        return family(self.name)

    @property
    def axis(self):
        """Where the part's own +z points - the axis of anything axial."""
        return mat_apply(self.tf.rot, (0.0, 0.0, 1.0))

    @property
    def opaque(self):
        return opaque(self.name)

    @property
    def label(self):
        p = self.tf.pos
        return f"{self.name} at ({p[0]:g}, {p[1]:g}, {p[2]:g})"


def place(index, step, name, color, tf):
    holes = [Hole(tf.point(h.center), _norm(tf.direction(h.axis)), h.half,
                  h.shape) for h in local_holes(name)]
    rod = local_rod(name)
    if rod:
        rod = (tf.point(rod[0]), tf.point(rod[1]), rod[2])
    return Placed(index, step, name, color, tf,
                  [world_box(tf, b) for b in local_boxes(name)], holes, rod)


def engagement(rod, hole):
    """How far a rod reaches into a hole along its axis; 0 if it misses."""
    a, b, _shape = rod
    span = vsub(b, a)
    length = math.sqrt(_dot(span, span))
    d = _scale(span, 1.0 / length)
    if abs(_dot(d, hole.axis)) < PARALLEL:
        return 0.0
    w = vsub(hole.center, a)
    t = _dot(w, d)
    off = vsub(w, _scale(d, t))
    if _dot(off, off) > ON_AXIS ** 2:
        return 0.0
    reach = min(length, t + hole.half) - max(0.0, t - hole.half)
    return reach if reach > ENGAGE else 0.0


def _seated(socket, hole):
    """A standoff end sitting square on a hole, coaxial and face to face."""
    if abs(_dot(socket.axis, hole.axis)) < PARALLEL:
        return False
    w = vsub(hole.center, socket.center)
    t = _dot(w, socket.axis)
    off = vsub(w, _scale(socket.axis, t))
    if _dot(off, off) > ON_AXIS ** 2:
        return False
    gap = abs(t) - socket.half - hole.half
    return -ENGAGE < gap < ENGAGE


@dataclass
class Joint:
    """`rod` goes into hole `hole` of `part`.  `kind` is pin, shaft or
    seated (a standoff end sitting on a hole); `fit` is locked when a square
    shaft sits in a square bore and turns with it, free otherwise."""

    rod: int
    part: int
    hole: int
    kind: str
    fit: str
    at: tuple


@dataclass
class Model:
    parts: list
    joints: list

    def joined(self, i):
        """Indices of every part joined directly to part `i`."""
        out = set()
        for j in self.joints:
            if j.rod == i:
                out.add(j.part)
            elif j.part == i:
                out.add(j.rod)
        return sorted(out)


def _near(a, b, pad=0.1):
    return min(overlap(a, b)) > -pad


def analyse(build):
    """Every part in the finished build, and every joint between them."""
    from .spec import turned

    # Where each part ends up: moved by every `turn` after its step, and
    # without the parts drawn for one step only.
    placed = []
    for n, step in enumerate(build.steps, 1):
        if getattr(step, "turn", None) is not None:
            placed = [(m, name, color, turned(p, step.turn))
                      for m, name, color, p in placed]
        placed += [(n, name, color, p) for p, name, color, _qty in step.items
                   if not getattr(p, "temp", False)]
    items = [place(k, n, name, color, p.tf)
             for k, (n, name, color, p) in enumerate(placed)]
    joints = []
    for r in items:
        sockets = r.holes if r.family == "standoff" else []
        if not (r.rod or sockets):
            continue
        for p in items:
            if p is r or not _near(r.box, p.box):
                continue
            if not p.holes:
                # Electronics: their holes are not modelled, so a pin pushed
                # into one is taken at its word rather than called solid.
                hit = (r.rod and (p.family in UNMODELLED or p.opaque) and next(
                    (q for q in rod_points(r.rod) if inside(q, p)), None))
                if hit:
                    joints.append(Joint(r.index, p.index, -1, r.family,
                                        "free", hit))
                continue
            for h_i, h in enumerate(p.holes):
                if r.rod and engagement(r.rod, h):
                    kind = "pin" if r.family == "pin" else "shaft"
                    fit = ("locked" if r.rod[2] == SQUARE and h.shape == SQUARE
                           else "free")
                    joints.append(Joint(r.index, p.index, h_i, kind, fit,
                                        h.center))
                    break
                # Two standoff ends touching are not fastened; one sitting on
                # a beam's hole is how standoffs are stood up.
                if p.family != "standoff" and any(
                        _seated(s, h) for s in sockets):
                    joints.append(Joint(r.index, p.index, h_i, "seated",
                                        "free", h.center))
                    break
    return Model(items, joints)


def inside(p, item, margin=0.03):
    """Is world point `p` inside the solid of `item` (shrunk by `margin`)?"""
    q = to_local(item.tf, p)
    if item.family in CYLINDERS:
        x0, _, z0, x1, _, z1 = geometry_box(item.name)
        return (math.hypot(q[0], q[1]) < x1 - margin
                and z0 + margin < q[2] < z1 - margin)
    return any(b[0] + margin < q[0] < b[3] - margin
               and b[1] + margin < q[1] < b[4] - margin
               and b[2] + margin < q[2] < b[5] - margin
               for b in local_boxes(item.name))


def rod_points(rod, spacing=0.05):
    a, b, _ = rod
    span = vsub(b, a)
    n = max(1, int(math.sqrt(_dot(span, span)) / spacing))
    return [vadd(a, _scale(span, i / n)) for i in range(n + 1)]


def nearest_hole(item, rod):
    """The hole of `item` closest to `rod`'s centre line, among those it
    could go through, and how far off it is."""
    a, b, _ = rod
    d = _norm(vsub(b, a))
    best = None
    for h in item.holes:
        if abs(_dot(d, h.axis)) < PARALLEL:
            continue
        w = vsub(h.center, a)
        off = vsub(w, _scale(d, _dot(w, d)))
        dist = math.sqrt(_dot(off, off))
        if best is None or dist < best[1]:
            best = (h, dist)
    return best
