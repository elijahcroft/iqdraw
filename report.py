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
"""

from __future__ import annotations

from . import joints as J
from .check import check


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
