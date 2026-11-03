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
