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

# A face-to-face joint is contact, not interference, and floating-point noise
# puts it either side of zero.  Parts have to share more than this in all three
# axes before it counts as occupying the same space.
TOUCH = 0.12

# How far apart two parts can be and still be considered joined, when working
# out whether anything is stranded.  A pin bridges two beams across a gap of
# nothing, so this only has to absorb rounding.
REACH = 0.15

# Gear centre distance is exact arithmetic - pitch radius is teeth/24 - so the
# tolerance only has to cover a spec author writing 1.5 for 1.5.
MESH_TOL = 0.06
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

    For the axis-aligned quarter-turns real builds use this is exact; for an
    arbitrary angle it over-estimates, which is the safe direction - it can
    only ever make a check quieter, never make it invent a problem.
    """
    x0, y0, z0, x1, y1, z1 = _local_box(placement.part)
    corners = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    pts = [placement.tf.point(c) for c in corners]
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            min(p[2] for p in pts), max(p[0] for p in pts),
            max(p[1] for p in pts), max(p[2] for p in pts))


def _items(build):
    out = []
    for i, step in enumerate(build.steps):
        for placement, name, _color, _qty in step.items:
            out.append(_Item(i + 1, name, placement, _world_box(placement)))
    return out


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


def _check_structural_overlap(items):
    """
    Two beams or plates in the same space.

    Restricted to the flat structural parts on purpose.  Pins through beams,
    shafts through gears and collars on shafts are all meant to interpenetrate,
    so a general collision test would report the whole model.  Two beams never
    are.
    """
    flat = [it for it in items if _family(it.name) in STRUCTURAL]
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


CHECKS = (_check_duplicates, _check_structural_overlap,
          _check_gear_mesh, _check_stranded)


def check(build):
    """Run every check over a build and return the problems, in step order."""
    items = _items(build)
    found = [p for rule in CHECKS for p in rule(items)]
    found.sort(key=lambda p: (p.step, p.kind))
    return found
