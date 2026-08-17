"""
The build-spec API.

A build file is a plain Python module - no YAML, no dependencies - which means
loops and variables are available where they help most:

    from iqdraw import Build

    b = Build("Flapping Bird", subtitle="Unit 5 - Lesson 19")

    with b.step("Lay the base beam down flat.") as s:
        s.add("beam_2x12", (0, 0, 0))
        for x in (0, 5, 11):
            s.add("pin_1x1", (x, 0, 0))

Every step shows the whole model so far, with the parts added in that step at
full colour and everything already built washed out behind them.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .geom import AXIS_ROT, IDENTITY, Transform, euler, mat_mul
from .parts import get
from .render import (
    Placement, RenderOpts, arrow_dir, arrow_tail, render, view_rotation,
)


@dataclass
class Step:
    note: str = ""
    items: list = field(default_factory=list)
    view_rz: float = None
    caption: str = ""

    def add(self, part, at=(0.0, 0.0, 0.0), rot=None, axis=None, color=None,
            qty=1, arrow=None):
        """
        Place a part.

        at     hole coordinates of the part's first hole
        axis   'x' | 'y' | 'z' - reorients parts that are built along +z
               (pins, shafts, standoffs, gears, wheels, collars)
        rot    extra rotation in degrees, applied X then Y then Z, after `axis`
        qty    only affects the parts callout; use it when one drawn part
               stands in for several identical ones
        arrow  draw an insertion arrow pointing the way the part goes in.
               True means straight down; otherwise '+x','-x','+y','-y',
               '+z','-z','up','down'.  Worth it whenever the step is "which
               hole?" rather than "which part?"
        """
        m = AXIS_ROT[axis] if axis else IDENTITY
        if rot:
            m = mat_mul(euler(*rot), m)
        self.items.append(
            (Placement(get(part, color), Transform(m, tuple(float(v) for v in at)),
                       arrow=arrow_dir(arrow)),
             part, color, qty)
        )
        return self

    def many(self, part, positions, **kw):
        """Place the same part at several coordinates."""
        for at in positions:
            self.add(part, at, **kw)
        return self

    # `with b.step(...) as s:` is just sugar; the object is usable either way.
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def placements(self):
        return [p for p, _, _, _ in self.items]

    def part_counts(self):
        c = Counter()
        for _, name, color, qty in self.items:
            c[(name, color)] += qty
        return c


class Build:
    def __init__(self, title, subtitle="", intro="", scale=34.0,
                 highlight=True, view_rz=0.0, fade_old=0.52):
        self.title = title
        self.subtitle = subtitle
        self.intro = intro
        self.view_rz = view_rz
        self.steps: list[Step] = []
        self.opts = RenderOpts(scale=scale, highlight=highlight,
                               fade_old=fade_old)

    def step(self, note="", view_rz=None, caption=""):
        s = Step(note=note, view_rz=view_rz, caption=caption)
        self.steps.append(s)
        return s

    # ------------------------------------------------------------- rendering

    def step_angle(self, step):
        """The effective camera angle for a step, in degrees."""
        return self.view_rz if step.view_rz is None else step.view_rz

    def _rot_for(self, step):
        return view_rotation(self.step_angle(step))

    def all_placements(self):
        return [p for s in self.steps for p in s.placements]

    def shared_box(self):
        """
        One frame for every step, computed from the finished model under each
        view angle in use.  Without this the model visibly grows page to page,
        which is exactly the cue a student uses to judge progress.
        """
        from .render import bounds, union_bounds, visible, world_prims

        angles = {self.view_rz} | {
            s.view_rz for s in self.steps if s.view_rz is not None
        }
        boxes = []
        for a in angles:
            rot = view_rotation(a)
            prims = visible(world_prims(self.all_placements(), self.opts, rot))
            x0, y0, x1, y1 = bounds(prims, self.opts)
            # Insertion arrows stand off the model, so the frame has to leave
            # room for them or they get cropped at the edge of the drawing.
            for p in self.all_placements():
                tail = arrow_tail(p, rot) if p.arrow else None
                if tail:
                    x0, y0 = min(x0, tail[0]), min(y0, tail[1])
                    x1, y1 = max(x1, tail[0]), max(y1, tail[1])
            boxes.append((x0, y0, x1, y1))
        return union_bounds(*boxes)

    def step_svgs(self, box=None):
        """[(step_index, Step, svg)] with each step's new parts highlighted."""
        box = box or self.shared_box()
        out = []
        built = []
        for i, step in enumerate(self.steps):
            # A step that adds nothing is a "check your work" step: show the
            # model at full colour rather than washing all of it out.
            carry_new = not step.placements
            placements = (
                [Placement(p.part, p.tf, new=carry_new) for p in built]
                + [Placement(p.part, p.tf, new=True, arrow=p.arrow)
                   for p in step.placements]
            )
            out.append((i + 1, step,
                        render(placements, self.opts, self._rot_for(step), box)))
            built.extend(step.placements)
        return out

    def hero_svg(self, scale=None, view_rz=None):
        """The finished model, everything at full colour."""
        opts = RenderOpts(
            scale=scale or self.opts.scale * 1.25,
            highlight=False,
            line_scale=self.opts.line_scale,
        )
        rot = view_rotation(self.view_rz if view_rz is None else view_rz)
        # No insertion arrows here - the cover shows the finished thing, not
        # an instruction.
        return render(self.all_placements(), opts, rot, arrows=False)

    def inventory(self):
        total = Counter()
        for s in self.steps:
            total.update(s.part_counts())
        return total
