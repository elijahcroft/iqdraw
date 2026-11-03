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

from . import joints as J
from .check import check
from .drive import drive
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
    "pin": ("pin_1x1 | pin_1x2 | pin_2x2 | pin_0x2", "pin_1x1",
            "centred on `at`, along its axis; joins the two parts it "
            "reaches into. pin_0x2 has a head: `at` is the head's underside "
            "and the pin runs a pitch up +z"),
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
# Drawn, but not yet in the joint model: no holes are checked, and a pin
# pushed into one is taken at its word.  See `joints.modelled`.
_DRAWN_ONLY = "drawn only - the joint checks do not model its holes yet"
FAMILIES.update({
    "lbeam": ("lbeam_AxB", "lbeam_2x3",
              "right-angle beam: A holes along +x and B along +y, sharing "
              "hole 0; holes along z"),
    "anglebeam": ("anglebeam_3x3_60 | anglebeam_3x3_45", "anglebeam_3x3_60",
                  "three holes along +x, the third the corner, then two more "
                  "along a leg turned 60 or 45 degrees; holes along z"),
    "lockbeam": ("lockbeam_1xN | lockbeam_2x2 | lockbeam_round_2x2",
                 "lockbeam_1x3",
                 "a beam whose centre hole is square, so it turns with its "
                 "shaft (lockbeam_1xN: odd N only); the 2x2s are centred on "
                 "that hole with a pin hole at each corner"),
    "connector": ("connector_2w_1x2 | connector_2w_2x2 | connector_2w_2x1 | "
                  "connector_triple_2x2 | connector_chassis_large | ...",
                  "connector_2w_1x2", _DRAWN_ONLY),
    "standoffconn": ("standoffconn_mini", "standoffconn_mini",
                     "a short sleeve centred on `at`: round bore, so it "
                     "spins on a shaft like a spacer"),
    "plastic": ("plastic_shaft_N | plastic_motor_shaft_N", "plastic_shaft_2",
                "square, like shaft_N; the motor shaft's tip reaches past "
                "-0.5 into the motor"),
    "capped": ("capped_shaft_N", "capped_shaft_2",
               "a square plastic shaft with a round cap on its -z end"),
    "motorshaft": ("motorshaft_N", "motorshaft_3",
                   "metal, square; `at` is the ridge that stops against the "
                   "motor, the tip below it and the shaft up +z"),
    "crankarm": ("crankarm_1x4", "crankarm_1x4",
                 "four holes along +x like a beam, hole 0 square and ringed "
                 "by a 23-tooth gear (not meshed by the checks)"),
    "tractionlink": ("tractionlink", "tractionlink", _DRAWN_ONLY),
    "omni": ("omni_N", "omni_200",
             "omni-directional wheel along +z, centred on its axle; square "
             "bore at `at`"),
    "tyre": ("tyre_N", "tyre_200", _DRAWN_ONLY),
    "hub": ("hub_N", "hub_200", "a travel wheel's hub alone: square bore at "
                                "`at`"),
    "pulley": ("pulley_20", "pulley_20", _DRAWN_ONLY),
    "string": ("string_AxB", "string_6x3.5", _DRAWN_ONLY),
    "touchled": ("touchled", "touchled", _DRAWN_ONLY),
    "cable": ("cable_N", "cable_200", _DRAWN_ONLY),
})


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
        "modelled": J.modelled(name),
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
                    "modelled": info["modelled"],
                    "example_envelope": info["envelope"],
                    "example_holes": len(info["holes"])})
    return out
