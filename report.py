"""
The finished build as data: `iqdraw build.py --inspect`.

Everything the checks know, as JSON - every part with its step, position,
axis, the space it fills and its holes in world coordinates; every joint
(which pin or shaft goes into which part, and whether it turns freely or is
locked to it); the problems; the parts list.  A drawing shows whether a
build looks right; this says what is actually joined to what, in numbers a
script or an agent can test.

`at=(x, y, z)` narrows it to one point: the parts filling it and the holes
running through it.

`drive` says what turns what: which parts turn as one body (a shaft and
everything square on it), which gears mesh, and how fast each body turns
for one turn of the train's driver.
"""

from __future__ import annotations

import math

from . import joints as J
from .check import MESH_TOL, check
from .geom import vsub
from .parts import _DEFAULT_COLOR, get


def _r(v):
    return round(float(v), 4) + 0.0


def _vec(v):
    return [_r(x) for x in v]


def _hole(h):
    return {"at": _vec(h.center), "axis": _vec(h.axis),
            "depth": _r(2 * h.half), "shape": h.shape}


def _through(h, p, tol=0.1):
    """Does hole `h` run through point `p`?"""
    w = [a - b for a, b in zip(p, h.center)]
    t = sum(a * b for a, b in zip(w, h.axis))
    off = sum((a - b * t) ** 2 for a, b in zip(w, h.axis)) ** 0.5
    return off < tol and abs(t) <= h.half + tol


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
    gears would have to turn two speeds at once is `jammed`.
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
              if any(parts[i].family in ("gear", "wheel", "motor")
                     for i in m)]
    bodies.sort()
    body_of = {i: n for n, m in enumerate(bodies) for i in m}
    meshes = [(a, b) for a, b in _meshes(parts)
              if body_of[a] != body_of[b]]

    links = {n: [] for n in range(len(bodies))}
    for a, b in meshes:
        # Speeds are all about the same +x, +y or +z, whichever way up each
        # gear went on, so a mesh always reverses.
        ratio = -_teeth(parts[a]) / _teeth(parts[b])
        links[body_of[a]].append((body_of[b], ratio))
        links[body_of[b]].append((body_of[a], 1 / ratio))

    trains, seen = [], set()
    for start in range(len(bodies)):
        if start in seen:
            continue
        group, todo = {start}, [start]
        while todo:
            for m, _ in links[todo.pop()]:
                if m not in group:
                    group.add(m)
                    todo.append(m)
        seen |= group
        motors = [n for n in sorted(group)
                  if any(parts[i].family == "motor" for i in bodies[n])]
        first = motors[0] if motors else min(group)
        speed, todo, jammed = {first: 1.0}, [first], False
        while todo:
            n = todo.pop()
            for m, ratio in links[n]:
                v = speed[n] * ratio
                if m not in speed:
                    speed[m] = v
                    todo.append(m)
                elif abs(speed[m] - v) > 1e-6:
                    jammed = True
        driver = next((i for i in bodies[first]
                       if parts[i].family == "motor"), bodies[first][0])
        trains.append({
            "driver": driver,
            "jammed": jammed,
            "bodies": [{"parts": bodies[n],
                        "speed": None if jammed else _r(speed[n])}
                       for n in sorted(group)],
        })
    return {
        "meshes": [{"gears": [a, b],
                    "teeth": [_teeth(parts[a]), _teeth(parts[b])]}
                   for a, b in meshes],
        "trains": trains,
    }


def report(build, at=None):
    model = J.analyse(build)
    sections = [s.section.title if s.section else None for s in build.steps]
    parts = [{
        "id": p.index,
        "step": p.step,
        "section": sections[p.step - 1],
        "name": p.name,
        "color": p.color,
        "at": _vec(p.tf.pos),
        "axis": _vec(p.axis),
        "box": _vec(p.box),
        "holes": [_hole(h) for h in p.holes],
        "joined": model.joined(p.index),
    } for p in model.parts]
    joints = [{
        "rod": j.rod, "part": j.part, "kind": j.kind, "fit": j.fit,
        "at": _vec(j.at),
    } for j in model.joints]
    out = {
        "title": build.title,
        "steps": [{"step": i, "note": s.note, "section": sections[i - 1],
                   "parts": [p["id"] for p in parts if p["step"] == i]}
                  for i, s in enumerate(build.steps, 1)],
        "parts": parts,
        "joints": joints,
        "drive": drive(model),
        "problems": [{"step": p.step, "kind": p.kind, "message": p.message}
                     for p in check(build, model)],
        "inventory": [{"name": name, "color": color, "qty": qty}
                      for (name, color), qty in
                      sorted(build.inventory().items(),
                             key=lambda kv: (kv[0][0], str(kv[0][1])))],
    }
    if at is not None:
        pt = tuple(float(v) for v in at)
        out["query"] = {
            "at": _vec(pt),
            # Parts whose space holds the point, by their envelope box.
            "parts": [p.index for p in model.parts
                      if all(p.box[i] - 0.05 <= pt[i] <= p.box[i + 3] + 0.05
                             for i in range(3))],
            "holes": [dict(_hole(h), part=p.index)
                      for p in model.parts for h in p.holes
                      if _through(h, pt)],
        }
    return out


# --------------------------------------------------------------- catalogue

# family: (name pattern, example, how it is placed).  Sizes come from the
# name, so any number parses - check the size against a real kit.
FAMILIES = {
    "beam": ("beam_WxL", "beam_2x12",
             "W holes across (+y), L along (+x), lying flat with its holes "
             "along z; first hole at `at`. rot=(90, 0, 0) stands it on edge"),
    "plate": ("plate_WxL", "plate_4x8", "a thinner beam: 0.25 thick"),
    "corner": ("corner_AxB", "corner_2x4",
               "L bracket: A holes along +x (holes along z), B holes up +z "
               "(holes along x)"),
    "pin": ("pin_1x1 | pin_1x2 | pin_2x2", "pin_1x1",
            "centred on `at`, along its axis; joins the two parts it "
            "reaches into"),
    "shaft": ("shaft_N", "shaft_4",
              "square, runs from 0.5 behind `at` to N-0.5 ahead along its "
              "axis; spins in round holes, locks in square bores"),
    "standoff": ("standoff_N", "standoff_2",
                 "runs 0..N from `at` along its axis; a pin socket in each "
                 "end"),
    "gear": ("gear_N", "gear_36",
             "N teeth, square bore at `at`; pitch radius N/24, so two "
             "gears mesh (Na+Nb)/24 holes apart"),
    "wheel": ("wheel_N", "wheel_200",
              "N = travel per revolution in mm (100, 160, 200, 250); "
              "square bore at `at`"),
    "collar": ("collar", "collar", "locks to a shaft: square bore"),
    "spacer": ("spacer", "spacer", "0.25 thick, round bore"),
    "washer": ("washer", "washer", "0.12 thick, round bore"),
    "motor": ("motor", "motor",
              "mounting holes along z, square drive socket on +x"),
    "brain": ("brain", "brain", "no hole positions modelled"),
    "bumper": ("bumper", "bumper", "no hole positions modelled"),
    "distance": ("distance", "distance", "no hole positions modelled"),
    "battery": ("battery", "battery", "no hole positions modelled"),
    "band": ("band_N", "band_4", "rubber band stretched over N holes"),
}


def part_info(name):
    """One part, in its own coordinates: what `iqdraw --part NAME` prints."""
    part = get(name)
    rod = J.local_rod(name)
    return {
        "name": name,
        "label": part.label,
        "family": J.family(name),
        "default_color": _DEFAULT_COLOR.get(J.family(name)),
        "axial": J.is_axial(name),
        "rod": ({"from": _vec(rod[0]), "to": _vec(rod[1]), "shape": rod[2]}
                if rod else None),
        "envelope": [_vec(b) for b in J.local_boxes(name)],
        "holes": [_hole(h) for h in J.local_holes(name)],
    }


def catalogue():
    """Every part family: what `iqdraw --parts` prints."""
    out = []
    for family in sorted(_DEFAULT_COLOR):
        pattern, example, notes = FAMILIES[family]
        info = part_info(example)
        out.append({"family": family, "pattern": pattern, "example": example,
                    "notes": notes, "axial": info["axial"],
                    "example_envelope": info["envelope"],
                    "example_holes": len(info["holes"])})
    return out
