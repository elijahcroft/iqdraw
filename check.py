"""
Sanity checks on a finished build.

This is not a physics engine and does not try to be one.  Each check answers
one question that has a definite wrong answer - two beams occupying the same
space, a gear pair whose teeth cannot reach each other, a part sitting on its
own in mid-air - and stays silent about everything it cannot be sure of.

That restraint is the whole design.  A checker that cries wolf gets switched
off, and a switched-off checker catches nothing.  Every rule here is one a
build cannot legitimately break, so a report is worth reading every time.

    from iqdraw.check import check
    for problem in check(build):
        print(problem)
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .geom import Disc, Edge, Facet, mat_apply, vsub
from . import joints as J
from .drive import MESH_TOL, drive

# A face-to-face joint is contact, not interference, and floating-point noise
# puts it either side of zero.  Parts have to share more than this in all three
# axes before it counts as occupying the same space.
TOUCH = 0.12

# How far apart two parts can be and still be considered joined, when working
# out whether anything is stranded.  A pin bridges two beams across a gap of
# nothing, so this only has to absorb rounding.
REACH = 0.15

# Beyond this much of a gap, two gears are unrelated rather than badly spaced.
# Being a whole hole out is the classic slip, so this has to reach past 1.0;
# what keeps it precise is the "nothing in between" test, not this number.
MESH_NEAR = 1.60


@dataclass
class Problem:
    step: int          # 1-based step number, or 0 for whole-build findings
    kind: str
    message: str

    def __str__(self):
        where = f"step {self.step}" if self.step else "build"
        return f"{where}: {self.kind}: {self.message}"


# --------------------------------------------------------------- placements


@dataclass
class _Item:
    step: int
    name: str
    placement: object
    box: tuple         # world-space (x0, y0, z0, x1, y1, z1)

    @property
    def label(self):
        at = self.placement.tf.pos
        return f"{self.name} at ({at[0]:g}, {at[1]:g}, {at[2]:g})"


_local_boxes = {}


def _local_box(part):
    """
    The part's own bounding box, computed once per part and cached.

    Parts are interned by `parts.get`, and a CAD beam carries thousands of
    triangles, so measuring the mesh on every placement would cost more than
    every other check put together.
    """
    key = (part.name, part.color)
    hit = _local_boxes.get(key)
    if hit is not None:
        return hit
    pts = []
    for prim in part.prims:
        if isinstance(prim, Facet):
            pts.extend(prim.pts)
        elif isinstance(prim, Edge):
            pts.extend((prim.a, prim.b))
        elif isinstance(prim, Disc):
            reach = prim.r * 1.001
            cx, cy, cz = prim.center
            pts.extend(((cx - reach, cy - reach, cz - reach),
                        (cx + reach, cy + reach, cz + reach)))
    if not pts:
        box = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    else:
        box = (min(p[0] for p in pts), min(p[1] for p in pts),
               min(p[2] for p in pts), max(p[0] for p in pts),
               max(p[1] for p in pts), max(p[2] for p in pts))
    _local_boxes[key] = box
    return box


def _world_box(placement):
    """
    Transform the local box's eight corners and re-fit around them.

    For the axis-aligned quarter-turns most builds use this is exact; for an
    arbitrary angle it over-estimates.  That keeps the stranded rule quiet,
    but it would make the overlap rule invent problems, so that rule leaves
    turned parts alone - see `_square`.
    """
    x0, y0, z0, x1, y1, z1 = _local_box(placement.part)
    corners = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    pts = [placement.tf.point(c) for c in corners]
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            min(p[2] for p in pts), max(p[0] for p in pts),
            max(p[1] for p in pts), max(p[2] for p in pts))


def _items(build):
    """Every part, where it ends up - after any `turn` of the model."""
    from .spec import turned

    placed = []
    for i, step in enumerate(build.steps):
        if getattr(step, "turn", None) is not None:
            placed = [(n, name, turned(p, step.turn))
                      for n, name, p in placed]
        placed += [(i + 1, name, p) for p, name, _color, _qty in step.items]
    return [_Item(n, name, p, _world_box(p)) for n, name, p in placed]


def _overlap(a, b):
    """Per-axis overlap depths of two boxes; negative means a gap."""
    return tuple(min(a[i + 3], b[i + 3]) - max(a[i], b[i]) for i in range(3))


# ------------------------------------------------------------------- checks


STRUCTURAL = ("beam", "plate")


def _family(name):
    return name.split("_")[0]


def _check_duplicates(items):
    """
    The same part placed twice at the same coordinates.

    Always a copy-paste slip: the second one is invisible behind the first, so
    it never shows up in the drawing, but it does inflate the parts callout and
    send a student hunting for a part they do not need.
    """
    seen = {}
    for it in items:
        key = (it.name, tuple(round(v, 4) for v in it.placement.tf.pos),
               tuple(tuple(round(v, 4) for v in row)
                     for row in it.placement.tf.rot))
        if key in seen:
            first = seen[key]
            yield Problem(it.step, "duplicate",
                          f"{it.label} is already placed in step {first.step} - "
                          f"the parts list will ask for one more than the build "
                          f"uses")
        else:
            seen[key] = it


def _square(placement):
    """Is the part turned only by quarter turns, so its box is exact?"""
    return all(min(abs(v), abs(abs(v) - 1.0)) < 1e-6
               for row in placement.tf.rot for v in row)


def _check_structural_overlap(items):
    """
    Two beams or plates in the same space.

    Restricted to the flat structural parts on purpose.  Pins through beams,
    shafts through gears and collars on shafts are all meant to interpenetrate,
    so a general collision test would report the whole model.  Two beams never
    are.

    And restricted to parts turned by quarter turns.  A beam at 35 degrees has
    a bounding box far bigger than the beam, so two that only touch end to end
    - a claw finger's links - would be reported as one inside the other.
    """
    # Only parts on quarter turns: a beam at 45 degrees fills a fraction of
    # its bounding box, so two parallel diagonal beams well apart - the two
    # arms of a four-bar linkage - would read as one inside the other.
    flat = [it for it in items
            if _family(it.name) in STRUCTURAL and _square(it.placement)]
    for i, a in enumerate(flat):
        for b in flat[i + 1:]:
            # An exact duplicate overlaps itself perfectly; the duplicate rule
            # already says so, and more usefully.
            if a.name == b.name and a.placement.tf == b.placement.tf:
                continue
            dx, dy, dz = _overlap(a.box, b.box)
            if min(dx, dy, dz) > TOUCH:
                yield Problem(max(a.step, b.step), "overlap",
                              f"{a.label} and {b.label} occupy the same space "
                              f"({dx:.2f} x {dy:.2f} x {dz:.2f} holes of "
                              f"overlap) - one of them is on the wrong layer")


_GEAR = re.compile(r"^gear_(\d+)$")


def _gears(items):
    for it in items:
        m = _GEAR.match(it.name)
        if m:
            teeth = int(m[1])
            axis = mat_apply(it.placement.tf.rot, (0.0, 0.0, 1.0))
            yield it, teeth, teeth / 24.0, axis, it.placement.tf.pos


def _between(ca, cb, others):
    """
    Is there a third gear sitting on the line between these two?

    This is what lets the spacing rule be strict without being wrong.  Three
    gears in a row - a train, or an idler - leave the outer pair further apart
    than their own pitch radii, and that pair is not a mistake, it just is not
    a pair.  Only gears with nothing between them are meant to touch.
    """
    d = vsub(cb, ca)
    span = sum(v * v for v in d)
    if span < 1e-9:
        return False
    for c in others:
        w = vsub(c, ca)
        t = sum(x * y for x, y in zip(w, d)) / span
        if not 0.05 < t < 0.95:
            continue
        off = math.sqrt(max(0.0, sum(v * v for v in w) - t * t * span))
        if off < 0.6:
            return True
    return False


def _check_gear_mesh(items):
    """
    Gear pairs that are close to meshing but not actually meshing.

    VEX IQ gears share one module, so a pair meshes exactly when the distance
    between their shafts equals the sum of their pitch radii, and a pitch
    radius is teeth/24 holes.  That makes this arithmetic rather than a
    judgement call: 12T + 36T is 2 holes, 12T + 60T is 3, 36T + 60T is 4.

    A pair sitting far apart is two unrelated gears and draws no comment.  A
    pair sitting *almost* right is a spec that meant to mesh and missed, which
    is the mistake worth catching - it looks fine on the page and jams in the
    hand.
    """
    gears = list(_gears(items))
    centres = [g[4] for g in gears]
    for i, (a, ta, ra, axa, ca) in enumerate(gears):
        for j, (b, tb, rb, axb, cb) in enumerate(gears[i + 1:], i + 1):
            if abs(sum(x * y for x, y in zip(axa, axb))) < 0.999:
                continue                      # skew axes: a bevel pair, not this
            d = vsub(cb, ca)
            along = sum(x * y for x, y in zip(d, axa))
            if abs(along) > 0.45:
                continue                      # stacked on one shaft, not meshing
            perp = math.sqrt(max(0.0, sum(v * v for v in d) - along * along))
            want = ra + rb
            step = max(a.step, b.step)
            if perp < want - MESH_TOL:
                yield Problem(step, "gear mesh",
                              f"{ta}T and {tb}T are {perp:.2f} holes apart but "
                              f"need {want:g} - the teeth would grind through "
                              f"each other")
            elif (perp - want > MESH_TOL and perp - want < MESH_NEAR
                  and not _between(ca, cb,
                                   [c for k, c in enumerate(centres)
                                    if k not in (i, j)])):
                yield Problem(step, "gear mesh",
                              f"{ta}T and {tb}T are {perp:.2f} holes apart but "
                              f"need {want:g} - close enough to look meshed on "
                              f"the page, too far to drive each other")


def _check_stranded(items):
    """
    Parts with nothing joining them to the rest of the model.

    A single mistyped coordinate moves a part clean off the build, and the
    drawing shows it floating in space - which is easy to miss on a step that
    already has forty parts in it.  Anything touching anything else counts as
    joined, so this only fires on something genuinely adrift.
    """
    if len(items) < 2:
        return
    grown = [tuple(v - REACH if i < 3 else v + REACH
                   for i, v in enumerate(it.box)) for it in items]
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if min(_overlap(grown[i], grown[j])) > 0:
                parent[find(i)] = find(j)

    groups = {}
    for i in range(len(items)):
        groups.setdefault(find(i), []).append(i)
    if len(groups) < 2:
        return
    main = max(groups.values(), key=len)
    for group in groups.values():
        if group is main:
            continue
        for i in group:
            it = items[i]
            yield Problem(it.step, "stranded",
                          f"{it.label} touches nothing else in the build - "
                          f"check the coordinates")


# ---------------------------------------------------------- joint checks
#
# These read the joint model in `joints.py` - holes, rods and nominal
# envelopes - rather than the drawing's bounding boxes, which is what lets them
# say "through solid plastic, not a hole" instead of only "touching".

# Cylinders - spacers, collars, gears - are thin enough that the 0.12 slack
# beams get would hide a whole spacer's worth of mistake, so they get less.
CYL_TOL = 0.06
# Parts stacked on one shaft are placed by exact arithmetic; anything past
# rounding is two parts in one slot.
COAX_TOL = 0.04
# Parts a finished build has to hold on with a pin, shaft or standoff.  Leaves
# out the electronics, whose holes are not modelled, and rubber bands.
FASTENED = ("beam", "plate", "corner", "standoff", "lbeam", "anglebeam",
            "lockbeam", "crankarm", "connector", "tractionlink") + J.CYLINDERS


def _check_rods(model, collided):
    """
    A pin or shaft running through solid plastic rather than a hole.

    The half-hole slip: a shaft at x=2.5 instead of 2, a pin one layer too
    high.  The drawing hides it, because the rod is drawn inside the part it
    is passing through.
    """
    for r in model.parts:
        held = {j.part for j in model.joints if j.rod == r.index}
        for rod in ([r.rod] if r.rod else []) + r.pegs:
            yield from _rod_in_solid(model, collided, r, rod, held)


def _rod_in_solid(model, collided, r, rod, held):
    pts = J.rod_points(rod)
    reach = J._rod_box(rod)   # a centre line: zero wide, so only < 0 misses
    what = r.label if rod is r.rod else f"a peg of {r.label}"
    for p in model.parts:
        if (p is r or p.rod or p.index in held or p.family == "band"
                or p.opaque or min(J.overlap(reach, p.box)) < 0):
            continue
        if not any(J.inside(q, p) for q in pts):
            continue
        # Neither end of a rod in the wrong place is "loose" as well -
        # it is one mistake, already reported.
        collided.update((r.index, p.index))
        msg = (f"{what} runs through solid {p.label}, "
               f"not through one of its holes")
        near = J.nearest_hole(p, rod)
        if near:
            c = near[0].center
            msg += (f" - the nearest hole is at ({c[0]:g}, {c[1]:g}, "
                    f"{c[2]:g}), {near[1]:.2f} off")
        yield Problem(max(r.step, p.step), "rod in solid", msg)


def _check_loose(model, collided):
    """
    Parts nothing holds on.

    A pin has to reach into two parts to join them; a shaft has to pass
    through something; a beam, gear or spacer needs a pin, shaft or standoff
    through it.  Without one it is resting where the drawing put it, and the
    first student to pick the model up finds out.
    """
    if len(model.parts) < 2:
        return
    opaque = [u for u in model.parts if u.opaque]
    for p in model.parts:
        if p.index in collided:
            continue          # already reported, more usefully
        if any(u is not p and min(J.overlap(p.box, u.box)) > -0.1
               for u in opaque):
            continue          # held, perhaps, by a part not modelled here
        joined = model.joined(p.index)
        if p.family == "pin" and len(joined) < 2:
            what = (f"only goes into {model.parts[joined[0]].label}"
                    if joined else "is not in any hole")
            yield Problem(p.step, "loose",
                          f"{p.label} {what} - a pin has to reach into two "
                          f"parts to hold them together")
        elif p.rod and p.rod[2] == J.SQUARE and not joined:
            yield Problem(p.step, "loose",
                          f"{p.label} does not pass through any hole")
        elif p.family in FASTENED and not joined:
            yield Problem(p.step, "loose",
                          f"nothing pins or shafts {p.label} to the build - "
                          f"it would fall off when the model is picked up")


def _cylinder(p):
    x0, _, z0, x1, _, z1 = J.geometry_box(p.name)
    return x1, z1          # radius, half-height


def _cyl_vs_box(c, b):
    """(axial, radial) overlap of cylinder part `c` and box part `b`."""
    r, h = _cylinder(c)
    best = (0.0, 0.0)
    for box in b.boxes:
        x0, y0, z0, x1, y1, z1 = box
        pts = [J.to_local(c.tf, (x, y, z)) for x in (x0, x1)
               for y in (y0, y1) for z in (z0, z1)]
        lo = [min(q[i] for q in pts) for i in range(3)]
        hi = [max(q[i] for q in pts) for i in range(3)]
        axial = min(hi[2], h) - max(lo[2], -h)
        cx = min(max(0.0, lo[0]), hi[0])
        cy = min(max(0.0, lo[1]), hi[1])
        radial = r - math.hypot(cx, cy)
        if min(axial, radial) > min(best):
            best = (axial, radial)
    return best


def _check_collisions(model, _collided):
    """
    Solid parts in the same space: a spacer and a gear overlapping on one
    shaft, a wheel rubbing the rail, a beam through the brain.

    Beam against beam is the `overlap` rule's, gear against gear the mesh
    rule's; pins and shafts are meant to pass through things and have their
    own rule above.
    """
    solid = [p for p in model.parts
             if not p.rod and p.family != "band" and not p.opaque]
    for i, a in enumerate(solid):
        for b in solid[i + 1:]:
            if min(J.overlap(a.box, b.box)) <= 0:
                continue
            if a.family in STRUCTURAL and b.family in STRUCTURAL:
                continue
            if a.name == b.name and a.tf == b.tf:
                continue                      # the duplicate rule's
            ca, cb = a.family in J.CYLINDERS, b.family in J.CYLINDERS
            depth = None
            if ca and cb:
                ax, bx = a.axis, b.axis
                if abs(sum(x * y for x, y in zip(ax, bx))) < 0.999:
                    continue                  # skew: bevel gears and the like
                d = vsub(b.tf.pos, a.tf.pos)
                along = sum(x * y for x, y in zip(d, ax))
                perp = math.sqrt(max(0.0, sum(v * v for v in d) - along ** 2))
                (ra, ha), (rb, hb) = _cylinder(a), _cylinder(b)
                axial = ha + hb - abs(along)
                if perp < J.ON_AXIS:
                    if axial > COAX_TOL:
                        depth = axial
                elif not (a.family == "gear" and b.family == "gear"):
                    if min(axial, ra + rb - perp) > CYL_TOL:
                        depth = min(axial, ra + rb - perp)
            elif ca or cb:
                c, x = (a, b) if ca else (b, a)
                axial, radial = _cyl_vs_box(c, x)
                if min(axial, radial) > CYL_TOL:
                    depth = min(axial, radial)
            else:
                d = max(min(J.overlap(p, q)) for p in a.boxes for q in b.boxes)
                if d > TOUCH:
                    depth = d
            if depth is not None:
                yield Problem(max(a.step, b.step), "collision",
                              f"{a.label} and {b.label} overlap by "
                              f"{depth:.2f} holes - one of them is in the "
                              f"wrong place")


def _check_jammed(model, collided):
    """
    Gears meshing in a loop that cannot turn.

    Three gears all meshing with each other, or two shafts joined by two
    gear pairs of different ratios: each mesh is fine alone, but together
    they ask one shaft to turn at two speeds, so nothing turns.  It draws
    perfectly and locks solid in the hand.
    """
    for train in drive(model)["trains"]:
        if not train["jammed"]:
            continue
        a, b = (model.parts[i] for i in train["clash"])
        gears = [model.parts[i] for body in train["bodies"]
                 for i in body["parts"] if model.parts[i].family == "gear"]
        yield Problem(max(p.step for p in gears), "jammed",
                      f"{a.label} and {b.label} close a loop of meshing "
                      f"gears that would have to turn two speeds at once, "
                      f"so none of the {len(gears)} gears can turn - take "
                      f"one out of the loop")


CHECKS = (_check_duplicates, _check_structural_overlap,
          _check_gear_mesh, _check_stranded)

# Rules over the joint model.  They share a set of rods already reported as
# passing through solid, so one mistake is not also reported as a loose pin.
JOINT_CHECKS = (_check_rods, _check_loose, _check_collisions,
                _check_jammed)


def check(build, model=None):
    """Run every check over a build and return the problems, in step order."""
    items = _items(build)
    found = [p for rule in CHECKS for p in rule(items)]
    model = model or J.analyse(build)
    collided = set()
    for rule in JOINT_CHECKS:
        found.extend(rule(model, collided))
    found.sort(key=lambda p: (p.step, p.kind))
    return found
