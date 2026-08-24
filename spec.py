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

from .geom import (
    AXIS_ROT, IDENTITY, MIRROR_ROT, Transform, euler, mat_mul,
)
from .parts import UnknownPart, get
from .render import (
    Placement, RenderOpts, arrow_dir, arrow_tail, render, view_rotation,
)


class SpecError(Exception):
    """A mistake in a build file, reported against the line that made it."""


def _orient(rot=None, axis=None, mirror=None):
    """
    The rotation part of a placement: mirror, then axis, then rot.

    That order is the one that stays predictable when they combine - `mirror`
    picks the handed version of the part, `axis` says which way it runs, and
    `rot` is the extra spin on top.
    """
    if axis is not None and axis not in AXIS_ROT:
        raise SpecError(f"axis must be 'x', 'y' or 'z', got {axis!r}")
    if mirror is not None and mirror not in MIRROR_ROT:
        raise SpecError(f"mirror must be 'x', 'y' or 'z', got {mirror!r}")
    m = MIRROR_ROT[mirror] if mirror else IDENTITY
    if axis:
        m = mat_mul(AXIS_ROT[axis], m)
    if rot:
        m = mat_mul(euler(*rot), m)
    return m


@dataclass
class Section:
    """
    A named run of steps - "Chassis", "Arm", "Joining the two sides".

    A thirty-step booklet as one undivided list asks a reader to hold their
    own place in it.  Sections give the build named parts that finish, and
    the frame is recomputed at each one so early steps are not a small model
    stranded in a page sized for the finished robot.
    """

    title: str
    note: str = ""


@dataclass
class Step:
    note: str = ""
    items: list = field(default_factory=list)
    view_rz: float = None
    caption: str = ""
    section: Section = None

    def add(self, part, at=(0.0, 0.0, 0.0), rot=None, axis=None, color=None,
            qty=1, arrow=None, mirror=None):
        """
        Place a part.

        at     hole coordinates of the part's first hole
        axis   'x' | 'y' | 'z' - reorients parts that are built along +z
               (pins, shafts, standoffs, gears, wheels, collars)
        rot    extra rotation in degrees, applied X then Y then Z, after `axis`
        mirror 'x' | 'y' | 'z' - reflect the part, for the handed twin of a
               chiral part like a corner bracket.  Applied before `axis`
        qty    only affects the parts callout; use it when one drawn part
               stands in for several identical ones
        arrow  draw an insertion arrow pointing the way the part goes in.
               True means straight down; otherwise '+x','-x','+y','-y',
               '+z','-z','up','down'.  Worth it whenever the step is "which
               hole?" rather than "which part?"
        """
        m = _orient(rot, axis, mirror)
        try:
            resolved = get(part, color)
        except UnknownPart as e:
            raise SpecError(str(e)) from None
        self.items.append(
            (Placement(resolved, Transform(m, tuple(float(v) for v in at)),
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


class _Steps:
    """Whatever holds an ordered list of steps - a `Build` or an `Assembly`."""

    def __init__(self):
        self.steps: list[Step] = []
        self._section = None

    def step(self, note="", view_rz=None, caption=""):
        s = Step(note=note, view_rz=view_rz, caption=caption,
                 section=self._section)
        self.steps.append(s)
        return s

    def all_placements(self):
        return [p for s in self.steps for p in s.placements]

    def place(self, assembly, at=(0.0, 0.0, 0.0), rot=None, mirror=None,
              note=None, caption=""):
        """
        Build `assembly` into this one, moved to `at`.

        at       where the assembly's own origin lands, in hole coordinates
        rot      rotation in degrees, applied X then Y then Z
        mirror   'x' | 'y' | 'z' - reflect the whole module, for the far side
                 of a symmetric robot
        note     collapse the assembly to a single step with this instruction,
                 instead of repeating all of its steps.  This is what a real
                 build guide does the second time round - "build a second one,
                 mirrored" beats eight steps the reader has already followed
        caption  the smaller line under `note`, when collapsing

        The assembly's steps keep their own notes, captions and camera angles;
        only their coordinates move.  Assemblies nest: an arm made of two
        link modules places them the same way a build places the arm.
        """
        outer = Transform(_orient(rot, mirror=mirror),
                          tuple(float(v) for v in at))

        def moved(items, arrows=True):
            out = []
            for placement, name, color, qty in items:
                arrow = (outer.direction(placement.arrow)
                         if arrows and placement.arrow else None)
                out.append((Placement(placement.part,
                                      placement.tf.then(outer), arrow=arrow),
                            name, color, qty))
            return out

        if note is not None:
            # No insertion arrows on a collapsed step.  They answer "which
            # way does this part go in", and a step that places a module the
            # reader has already built is not asking that - it would arrive
            # as a dozen arrows at once, which is the question it isn't.
            s = self.step(note=note, caption=caption)
            for src in assembly.steps:
                s.items.extend(moved(src.items, arrows=False))
            return self

        for src in assembly.steps:
            s = self.step(note=src.note, view_rz=src.view_rz,
                          caption=src.caption)
            s.items.extend(moved(src.items))
        return self

    def inventory(self):
        total = Counter()
        for s in self.steps:
            total.update(s.part_counts())
        return total


class Assembly(_Steps):
    """
    A module built in its own coordinates, to be dropped into a `Build`.

    This is what makes a big build writable.  Without it every coordinate in
    a robot is absolute, so an arm that sits three holes forward and two up
    carries that offset by hand on every line, and moving the arm means
    editing all of them.  An assembly is written as though it were the only
    thing on the table, at its own origin:

        arm = Assembly("Arm")
        with arm.step("Pin the two links together.") as s:
            s.add("beam_1x8", (0, 0, 0))

        b.place(arm, at=(3, 0, 2))

    Place it more than once for the parts a robot has two of - and `mirror`
    for the ones it has a left and a right of.
    """

    def __init__(self, name=""):
        super().__init__()
        self.name = name


class Build(_Steps):
    def __init__(self, title, subtitle="", intro="", done="", scale=34.0,
                 highlight=True, view_rz=0.0, fade_old=0.52,
                 context_detail=None):
        super().__init__()
        # How much geometry the already-built parts carry.  None draws them
        # exactly like the new ones; "simple" swaps them for the procedural
        # shapes, which is most of a booklet's size once a build is
        # robot-sized and costs nothing the reader is looking at - those
        # parts are washed out on purpose, and the step's own parts keep the
        # official CAD meshes either way.
        self.context_detail = context_detail
        self.title = title
        self.subtitle = subtitle
        self.intro = intro
        # How a builder knows they have finished, in one line.  A task with an
        # unstated finish condition is a task some students cannot start.
        self.done = done
        self.view_rz = view_rz
        self.opts = RenderOpts(scale=scale, highlight=highlight,
                               fade_old=fade_old)

    # ----------------------------------------------------------- composition

    def section(self, title, note=""):
        """
        Start a named run of steps.  Every step after this belongs to it,
        until the next `section()`.
        """
        self._section = Section(title, note)
        return self._section

    def place(self, assembly, at=(0.0, 0.0, 0.0), rot=None, mirror=None,
              note=None, caption="", section=None):
        """As `_Steps.place`, plus `section` as a shorthand for opening one."""
        if section is not None:
            self.section(section)
        return super().place(assembly, at, rot, mirror, note, caption)

    # ------------------------------------------------------------- rendering

    def step_angle(self, step):
        """The effective camera angle for a step, in degrees."""
        return self.view_rz if step.view_rz is None else step.view_rz

    def _rot_for(self, step):
        return view_rotation(self.step_angle(step))

    def _box(self, placements, angles):
        """The frame `placements` need, under every one of `angles`."""
        from .render import bounds, union_bounds, visible, world_prims

        boxes = []
        for a in angles:
            rot = view_rotation(a)
            prims = visible(world_prims(placements, self.opts, rot))
            x0, y0, x1, y1 = bounds(prims, self.opts)
            # Insertion arrows stand off the model, so the frame has to leave
            # room for them or they get cropped at the edge of the drawing.
            for p in placements:
                tail = arrow_tail(p, rot) if p.arrow else None
                if tail:
                    x0, y0 = min(x0, tail[0]), min(y0, tail[1])
                    x1, y1 = max(x1, tail[0]), max(y1, tail[1])
            boxes.append((x0, y0, x1, y1))
        return union_bounds(*boxes)

    def _angles(self, steps):
        return {self.view_rz} | {
            s.view_rz for s in steps if s.view_rz is not None
        }

    def shared_box(self):
        """
        One frame for every step, computed from the finished model under each
        view angle in use.  Without this the model visibly grows page to page,
        which is exactly the cue a student uses to judge progress.
        """
        return self._box(self.all_placements(), self._angles(self.steps))

    def step_boxes(self):
        """
        One frame per step - shared across a section, regrown at each one.

        Registering every step against the finished model is right for a
        six-step build and wrong for a forty-step one, where it leaves the
        first steps as a thumbnail adrift in a page sized for a whole robot.
        A section is the unit that keeps registration worth having: inside it
        the model holds still, and the boundary where the frame changes is
        the one place the reader is already being told to look.

        With no sections declared this is the shared box for every step, so
        an existing build renders exactly as it did.
        """
        if not any(s.section for s in self.steps):
            return [self.shared_box()] * len(self.steps)

        boxes = [None] * len(self.steps)
        for lo, hi in self.runs():
            through = self.steps[:hi]
            boxes[lo:hi] = [
                self._box([p for s in through for p in s.placements],
                          self._angles(through))
            ] * (hi - lo)
        return boxes

    def section_runs(self):
        """
        [(section, lo, hi)] - each run of steps and the section it belongs to.

        `section` is None for a build that never declared one, which is the
        single run covering everything.
        """
        return [(self.steps[lo].section, lo, hi) for lo, hi in self.runs()]

    def runs(self):
        """[(start, stop)] index ranges of consecutive same-section steps."""
        runs, lo = [], 0
        for i in range(1, len(self.steps) + 1):
            if i == len(self.steps) or \
                    self.steps[i].section is not self.steps[lo].section:
                runs.append((lo, i))
                lo = i
        return runs

    def step_svgs(self, box=None, styles=None):
        """
        [(step_index, Step, svg)] with each step's new parts highlighted.

        `box` forces one frame across every step; left out, each step gets
        its section's frame.
        """
        boxes = [box] * len(self.steps) if box else self.step_boxes()
        out = []
        built = []   # (placement, part name, colour) of everything so far
        for i, step in enumerate(self.steps):
            # A step that adds nothing is a "check your work" step: show the
            # model at full colour rather than washing all of it out - and at
            # full detail with it, since nothing there is background.
            carry_new = not step.placements
            placements = (
                [Placement(self._context_part(p, name, color, carry_new),
                           p.tf, new=carry_new)
                 for p, name, color in built]
                + [Placement(p.part, p.tf, new=True, arrow=p.arrow)
                   for p in step.placements]
            )
            out.append((i + 1, step,
                        render(placements, self.opts, self._rot_for(step),
                               boxes[i], styles=styles,
                               title=self.step_alt(i + 1, step))))
            built.extend((p, name, color)
                         for p, name, color, _qty in step.items)
        return out

    def _context_part(self, placement, name, color, at_full_colour):
        """The geometry an already-built part is drawn with."""
        if self.context_detail is None or at_full_colour:
            return placement.part
        return get(name, color, detail=self.context_detail)

    def step_alt(self, number, step):
        """
        What a screen reader says instead of the drawing.

        The picture carries the part of the instruction the words leave out -
        which hole, which way round - so a reader who cannot see it is left
        with an incomplete step unless the drawing names what it added.
        """
        counts = step.part_counts()
        if not counts:
            return f"Step {number}: the model so far, with nothing added."
        added = ", ".join(
            f"{qty} {get(name, color).label}" + ("s" if qty > 1 else "")
            for (name, color), qty in counts.items()
        )
        return (f"Step {number}: the model so far, with {added} "
                f"drawn in full colour and everything already built "
                f"faded behind it.")

    def hero_svg(self, scale=None, view_rz=None, styles=None):
        """The finished model, everything at full colour."""
        opts = RenderOpts(
            scale=scale or self.opts.scale * 1.25,
            highlight=False,
            line_scale=self.opts.line_scale,
        )
        rot = view_rotation(self.view_rz if view_rz is None else view_rz)
        # No insertion arrows here - the cover shows the finished thing, not
        # an instruction.
        return render(self.all_placements(), opts, rot, arrows=False,
                      styles=styles,
                      title=f"The finished {self.title}, seen from one corner.")
