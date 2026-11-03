"""
What turns what, from the joint model.

A body is the parts that turn as one; a train is the bodies joined by
meshing gears.  `iqdraw --inspect` prints this as its `drive` section, and
the `jammed` check reads it to catch a train that cannot turn at all.
"""

from __future__ import annotations

import math

from . import joints as J
from .geom import vsub

# Gear centre distance is exact arithmetic - pitch radius is teeth/24 - so the
# tolerance only has to cover a spec author writing 1.5 for 1.5.
MESH_TOL = 0.06

# A body is worth reporting when it holds one of these.
TURNING = ("gear", "wheel", "omni", "hub", "motor")


def _teeth(p):
    m = J._LEN.match(p.name)
    return int(m[2]) if m and m[1] == "gear" else None


def _meshes(parts):
    """Pairs of gears whose teeth engage: parallel shafts, the same height
    along them, and centres exactly their two pitch radii apart."""
    gears = [(p, _teeth(p)) for p in parts if _teeth(p)]
    for i, (a, ta) in enumerate(gears):
        for b, tb in gears[i + 1:]:
            if abs(J._dot(a.axis, b.axis)) < J.PARALLEL:
                continue
            d = vsub(b.tf.pos, a.tf.pos)
            along = J._dot(d, a.axis)
            perp = math.sqrt(max(0.0, J._dot(d, d) - along * along))
            if abs(along) < 0.45 and abs(perp - (ta + tb) / 24.0) <= MESH_TOL:
                yield a.index, b.index


def drive(model):
    """
    What turns what.  A body is the parts that turn as one: a shaft and every
    gear, wheel and collar locked square on it, with the motor if the shaft
    is in its socket.  A train is the bodies joined by meshing gears; its
    driver is its motor, or failing that its first-built body.  `speed` is
    turns per turn of the driver, signed about the +x, +y or +z the shaft
    runs along - so -0.333 is a third as fast, the other way.  A train whose
    gears would have to turn two speeds at once is `jammed`, and `clash` is
    the meshing pair that closes the loop.
    """
    parts = model.parts
    root = list(range(len(parts)))

    def find(i):
        while root[i] != i:
            root[i] = root[root[i]]
            i = root[i]
        return i

    for j in model.joints:
        if j.fit == "locked":
            root[find(j.rod)] = find(j.part)
    members = {}
    for p in parts:
        members.setdefault(find(p.index), []).append(p.index)
    bodies = [sorted(m) for m in members.values()
              if any(parts[i].family in TURNING for i in m)]
    bodies.sort()
    body_of = {i: n for n, m in enumerate(bodies) for i in m}
    meshes = [(a, b) for a, b in _meshes(parts)
              if body_of[a] != body_of[b]]

    links = {n: [] for n in range(len(bodies))}
    for a, b in meshes:
        # Speeds are all about the same +x, +y or +z, whichever way up each
        # gear went on, so a mesh always reverses.
        ratio = -_teeth(parts[a]) / _teeth(parts[b])
        links[body_of[a]].append((body_of[b], ratio, (a, b)))
        links[body_of[b]].append((body_of[a], 1 / ratio, (a, b)))

    trains, seen = [], set()
    for start in range(len(bodies)):
        if start in seen:
            continue
        group, todo = {start}, [start]
        while todo:
            for m, _, _ in links[todo.pop()]:
                if m not in group:
                    group.add(m)
                    todo.append(m)
        seen |= group
        motors = [n for n in sorted(group)
                  if any(parts[i].family == "motor" for i in bodies[n])]
        first = motors[0] if motors else min(group)
        speed, todo, clash = {first: 1.0}, [first], None
        while todo:
            n = todo.pop()
            for m, ratio, pair in links[n]:
                v = speed[n] * ratio
                if m not in speed:
                    speed[m] = v
                    todo.append(m)
                elif abs(speed[m] - v) > 1e-6 and clash is None:
                    clash = list(pair)
        jammed = clash is not None
        driver = next((i for i in bodies[first]
                       if parts[i].family == "motor"), bodies[first][0])
        trains.append({
            "driver": driver,
            "jammed": jammed,
            "clash": clash,
            "bodies": [{"parts": bodies[n],
                        "speed": None if jammed else round(speed[n], 4) + 0.0}
                       for n in sorted(group)],
        })
    return {
        "meshes": [{"gears": [a, b],
                    "teeth": [_teeth(parts[a]), _teeth(parts[b])]}
                   for a, b in meshes],
        "trains": trains,
    }
