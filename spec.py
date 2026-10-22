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
from .parts import Part, UnknownPart, get
from .render import (
    Placement, RenderOpts, arrow_dir, arrow_tail, bounds, exploded, render,
    view_rotation, visible, world_prims,
)


def turned(placement, tf):
    """`placement` moved by `tf`, its insertion arrow turned with it."""
    arrow = tf.direction(placement.arrow) if placement.arrow else None
    return Placement(placement.part, placement.tf.then(tf), new=placement.new,
                     arrow=arrow, group=placement.group, pull=placement.pull,
                     temp=placement.temp)


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
    # Set by `Build.turn`: everything built before this step is moved by it,
    # and `turn_note` says so on the page.
    turn: Transform = None
    turn_note: str = ""
    # Set on a step that places a finished module in one go: (name, the
    # module's parts in its own coordinates), drawn as one callout item.
    module: tuple = None
    # How many times the reader does this step - "2X" on the page, for the
    # side of a robot that is built twice.  Counts in the parts lists follow.
    times: int = 1
    # Start a new page here, where the original manual turns the page.
    page: bool = False
    # Take the whole width of the page, where the original gives a step a
    # full row of a four-to-a-page layout.
    wide: bool = False
    # Set by `Build.aside`: the module this step builds on its own, beside
    # the model rather than on it.  Drawn with nothing else.
    alone: object = None
    # Set by `Build.join`: (aside token, "built" | "aside", arrow, label) -
    # the step that puts the two together, moving one whole onto the other.
    join: tuple = None
    # With `alone`: where the module is drawn on the table, if not where it
    # ends up - a Transform from where it ends up.
    shown: Transform = None
    # Show the "turn it round" arrows: the reader turns a piece over or round
    # before this step, though the camera has not moved.
    spin: bool = False
    # With `join`: how far the moving piece is drawn pulled back, if not the
    # usual.
    join_pull: float = None
    # With `join`: [placements] per piece put together - the model so far,
    # then each piece built aside - for a callout that shows them.
    pieces: list = None
    # Drawn under the step before it, in the same column of the page.
    under: bool = False

    def add(self, part, at=(0.0, 0.0, 0.0), rot=None, axis=None, color=None,
            qty=1, arrow=None, mirror=None, group=None, pull=None,
            temp=False):
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
        group  any label: parts with the same label and arrow go on as one
               piece already put together, and are drawn pulled back as one
        pull   how far, in pitch, to draw it pulled back along its arrow,
               where the usual distance leaves it hidden
        temp   drawn in this step only - a string lying loose, which a
               later step draws hung - and left out of the finished model
        """
        m = _orient(rot, axis, mirror)
        if isinstance(part, Part):
            # A part made on the spot, like a cable's run: drawn, and
            # listed only if given a quantity.
            resolved, part = part, part.name
        else:
            try:
                resolved = get(part, color)
            except UnknownPart as e:
                raise SpecError(str(e)) from None
        self.items.append(
            (Placement(resolved, Transform(m, tuple(float(v) for v in at)),
                       arrow=arrow_dir(arrow), group=group, pull=pull,
                       temp=temp),
             part, color, qty)
        )
        return self

    def include(self, assembly, at=(0.0, 0.0, 0.0), rot=None, mirror=None,
                arrow=None):
        """
        Add every part of `assembly` to this step, moved as `place` would
        move it - for parts written in a module's own frame that go on in
        a step of the build, like a pad fitted as a finger goes on.  With
        `arrow`, they go on together as one piece that way.
        """
        outer = Transform(_orient(rot, mirror=mirror),
                          tuple(float(v) for v in at))
        way = arrow_dir(arrow)
        for placement, name, color, qty in assembly.all_items():
            own = (outer.direction(placement.arrow)
                   if placement.arrow else None)
            self.items.append((Placement(placement.part,
                                         placement.tf.then(outer),
                                         arrow=way or own,
                                         group=id(assembly) if way else None,
                                         pull=placement.pull),
                               name, color, qty))
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

    def part_counts(self, times=False):
        """What the step takes; with `times`, for every time it is done."""
        c = Counter()
        k = self.times if times else 1
        for _, name, color, qty in self.items:
            c[(name, color)] += qty * k
        # a part placed with qty=0 is drawn but not listed
        return Counter({k: v for k, v in c.items() if v})


class _Steps:
    """Whatever holds an ordered list of steps - a `Build` or an `Assembly`."""

    def __init__(self):
        self.steps: list[Step] = []
        self._section = None
        self._turn = None

    def step(self, note="", view_rz=None, caption="", times=1, page=False,
             wide=False, spin=False, under=False):
        """
        Add a step.  `times=2` marks one the reader does twice ("2X"),
        `page=True` starts a new page with it, `wide=True` gives it a whole
        row and `under=True` stacks it below the step before, wherever the
        original manual does.
        """
        s = Step(note=note, view_rz=view_rz, caption=caption,
                 section=self._section, times=times, page=page, wide=wide,
                 spin=spin, under=under)
        if self._turn is not None:
            s.turn, s.turn_note = self._turn
            self._turn = None
        self.steps.append(s)
        return s

    def all_placements(self):
        return self.placements_through(len(self.steps))

    def all_items(self):
        """(placement, name, colour, qty) for every part, where it ends up."""
        out = []
        for st in self.steps:
            if st.turn is not None:
                out = [(turned(p, st.turn), n, c, q) for p, n, c, q in out]
            out.extend(st.items)
        return out

    def placements_through(self, hi):
        """
        Every placement in the first `hi` steps, where it is at step `hi` -
        moved by any `turn` on the way, so they all share one frame.
        """
        out = []
        for s in self.steps[:hi]:
            if s.turn is not None:
                out = [turned(p, s.turn) for p in out]
            # A part drawn for its own step only is gone by the next.
            out = [p for p in out if not p.temp]
            out.extend(s.placements)
        return out

    def place(self, assembly, at=(0.0, 0.0, 0.0), rot=None, mirror=None,
              note=None, caption="", counted=True, arrow=None, page=False,
              spin=False):
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
        counted  False draws the assembly but lists none of its parts - for
                 a module the reader brings finished, like the robot an
                 upgrade is built onto, which its own booklet already counted
        arrow    when collapsing, the way the finished module goes on, as for
                 `Step.add`: it is drawn pulled back that way, in one piece

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
                                      placement.tf.then(outer), arrow=arrow,
                                      group=placement.group if arrow else None,
                                      pull=placement.pull if arrow else None,
                                      temp=placement.temp),
                            name, color, qty if counted else 0))
            return out

        if note is not None:
            # No insertion arrows on a collapsed step.  They answer "which
            # way does this part go in", and a step that places a module the
            # reader has already built is not asking that - it would arrive
            # as a dozen arrows at once, which is the question it isn't.
            s = self.step(note=note, caption=caption, page=page, spin=spin)
            for src in assembly.steps:
                s.items.extend(moved(src.items, arrows=False))
            if arrow is not None:
                way = arrow_dir(arrow)
                for placement, *_ in s.items:
                    placement.arrow, placement.group = way, id(s)
            s.module = (assembly.name or "The module",
                        [Placement(p.part, p.tf.then(Transform(outer.rot)))
                         for p in assembly.all_placements()])
            return self

        for k, src in enumerate(assembly.steps):
            s = self.step(note=src.note, view_rz=src.view_rz,
                          caption=src.caption, times=src.times,
                          page=src.page or (page and k == 0), wide=src.wide,
                          spin=src.spin, under=src.under)
            s.items.extend(moved(src.items))
            if src.module:
                s.module = (src.module[0],
                            [Placement(p.part, p.tf.then(Transform(outer.rot)))
                             for p in src.module[1]])
        return self

    def inventory(self):
        total = Counter()
        for s in self.steps:
            total.update(s.part_counts(times=True))
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


# How each kind of original manual is laid out and drawn, so a redrawn
# booklet looks like the one it copies.  None of them washes out the parts
# already built; they mark the new ones instead, or let the guide lines do it.
#
#   letter     VEX's letter-size guides (Lever, Pulley, Standard Drive Base):
#              four steps to a page, a parts box per step, green guide lines,
#              the step finished in a small box in the corner
#   landscape  VEX's 2nd-gen guides (BaseBot, Clawbot): one parts strip
#              across the top of each page, magenta guide lines and a magenta
#              line round each new part, the step finished drawn full size
#   slides     16:9 guides (M.A.D. Box): one step a page, a named parts strip
#              along the top, green guide lines, the step finished in a box
#   magikid    Magikid's guides (Wiper): one step a page, nothing pulled
#              apart, a red line round the new parts, the parts in a small
#              pale box at the top right
STYLES = {
    "letter":    dict(ring=None, guide="#86c440", explode=True, ring_w=1.0,
                      pull=1.0),
    "landscape": dict(ring="#da0a8c", guide="#da0a8c", explode=True,
                      ring_w=1.0, pull=1.7, ring_moving=True),
    "slides":    dict(ring="#7cc242", guide="#7cc242", explode=True,
                      ring_w=0.7, pull=1.0, ring_moving=True),
    "magikid":   dict(ring="#e2373f", guide=None, explode=False, ring_w=0.45,
                      pull=1.0, arrows=False),
}


class Build(_Steps):
    def __init__(self, title, subtitle="", intro="", done="", scale=34.0,
                 highlight=True, view_rz=0.0, fade_old=0.0,
                 context_detail=None, explode=None, style="letter",
                 finale=None):
        super().__init__()
        if style not in STYLES:
            raise SpecError(f"style must be one of {sorted(STYLES)}, "
                            f"got {style!r}")
        self.style = style
        # A big picture of the finished model after the last step, where
        # the original ends on one: "cell" for a quarter of the page, "row"
        # for half of it.  Letter style only.
        if finale not in (None, "cell", "row"):
            raise SpecError(f"finale must be None, 'cell' or 'row', "
                            f"got {finale!r}")
        self.finale = finale
        self.frame_each = True
        look = STYLES[style]
        if explode is None:
            explode = look["explode"]
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
                               fade_old=fade_old, explode=explode,
                               ring=look["ring"], guide=look["guide"],
                               ring_w=look["ring_w"], pull=look["pull"],
                               ring_moving=look.get("ring_moving", False))

    # ----------------------------------------------------------- composition

    def turn(self, rot=None, at=(0.0, 0.0, 0.0), note="Turn the model over."):
        """
        Turn over everything built so far before the next step: rotate it by
        `rot` (degrees, X then Y then Z) and move it to `at`.

        For a module built one way up and fitted the other - a claw built
        standing on its motor and hung on the robot motor-up.  Steps before
        the turn are drawn the way up they are built; the next step and
        everything after it in the turned frame, with `note` on the page.
        """
        self._turn = (Transform(_orient(rot), tuple(float(v) for v in at)),
                      note)
        return self

    def aside(self, assembly, at=(0.0, 0.0, 0.0), rot=None, mirror=None,
              page=False, show_at=None, show_rot=None):
        """
        Build `assembly` to one side, where the original manual builds a
        piece on the table before it goes on: its steps are drawn showing
        that piece alone - where it will end up (`at`, `rot`), or, with
        `show_at` / `show_rot`, placed that way instead, as the manual draws
        it on the table.  Then `join` puts the two together.  Returns the
        token `join` takes.
        """
        start = len(self.steps)
        self.place(assembly, at=at, rot=rot, mirror=mirror, page=page)
        token = object()
        shown = None
        if show_at is not None or show_rot is not None:
            outer = Transform(_orient(rot, None, mirror),
                              tuple(float(v) for v in at))
            back = tuple(tuple(outer.rot[j][i] for j in range(3))
                         for i in range(3))
            undo = Transform(back, tuple(-sum(back[i][j] * outer.pos[j]
                                              for j in range(3))
                                         for i in range(3)))
            shown = undo.then(Transform(_orient(show_rot),
                                        tuple(float(v) for v in
                                              (show_at or (0, 0, 0)))))
        for s in self.steps[start:]:
            s.alone = token
            s.shown = shown
        return token

    def join(self, token, moving="aside", arrow="down", label=None, note="",
             caption="", page=False, wide=False, view_rz=None, times=1,
             spin=False, under=False, pull=None):
        """
        The step that puts a piece built `aside` together with the rest.
        It is returned, so parts that go on with it can be added to it.
        `moving` says which one is drawn pulled back along `arrow` (by
        `pull` pitch, if not the usual): "aside"
        for the piece going onto the model, "built" for the model so far
        going onto the piece - "Step 3 Assembly" in the parts strip, as a
        guide that has you lift the model onto a beam on the table names it.
        With `token` None the piece is the parts this step adds: the model
        so far is lowered onto them.  A tuple of tokens moves several pieces
        built aside at once, each pulled back the same way.  Parts added with no arrow of their own
        to a step that moves its piece go on with the piece.
        """
        if moving not in ("aside", "built"):
            raise SpecError(f"moving must be 'aside' or 'built', got {moving!r}")
        s = self.step(note=note, caption=caption, page=page, wide=wide,
                      view_rz=view_rz, times=times, spin=spin, under=under)
        k = len(self.steps) - 1
        s.join = (token, moving, arrow, label)
        s.join_pull = pull
        before = self._items_through(k)
        tokens = [self.steps[j].alone for *_x, j in before]
        joined = set()
        for st in self.steps[:k]:
            if st.join:
                t = st.join[0]
                joined.update(t if isinstance(t, tuple) else (t,))
        several = (token if isinstance(token, tuple) else
                   (token,) if token not in (None, "self") else ())
        rest = [p for (p, *_x), t in zip(before, tokens)
                if t is None or t in joined]
        s.pieces = [pl for pl in
                    [rest] + [[p for (p, *_x), t in zip(before, tokens)
                               if t == one] for one in several] if pl] or None
        if label:
            # The parts strip shows the piece that moves, as one item.
            drawn, _ = self._scene(k)
            s.module = (label, [Placement(p.part, p.tf)
                                for p, _n, _c in drawn if p.new])
        return s

    def bring(self, assembly, at=(0.0, 0.0, 0.0), rot=None, mirror=None,
              moving="built", arrow="down", counted=False, label=None,
              note="", caption="", page=False, wide=False, view_rz=None,
              times=1, spin=False):
        """
        A finished module the reader brings to the build in one step - the
        BaseBot a claw goes onto, a side frame built a second time - and
        either the model so far goes onto it (`moving="built"`, the module
        drawn as it stands) or it goes onto the model (`"aside"`).
        `counted=False` lists none of its parts: its own booklet, or the
        steps marked "2X", already did.
        """
        s = self.join("self", moving=moving, arrow=arrow, label=None,
                      note=note, caption=caption, page=page, wide=wide,
                      view_rz=view_rz, times=times, spin=spin)
        outer = Transform(_orient(rot, mirror=mirror),
                          tuple(float(v) for v in at))
        for src in assembly.all_items():
            placement, name, color, qty = src
            s.items.append((Placement(placement.part, placement.tf.then(outer)),
                            name, color, qty if counted else 0))
        if label:
            s.module = (label, [Placement(p.part, p.tf.then(Transform(outer.rot)))
                                for p in assembly.all_placements()])
        return s

    def section(self, title, note=""):
        """
        Start a named run of steps.  Every step after this belongs to it,
        until the next `section()`.
        """
        self._section = Section(title, note)
        return self._section

    def place(self, assembly, at=(0.0, 0.0, 0.0), rot=None, mirror=None,
              note=None, caption="", section=None, counted=True, arrow=None,
              page=False, spin=False):
        """As `_Steps.place`, plus `section` as a shorthand for opening one."""
        if section is not None:
            self.section(section)
        return super().place(assembly, at, rot, mirror, note, caption,
                             counted, arrow, page, spin)

    # ------------------------------------------------------------- rendering

    def step_angle(self, step):
        """The effective camera angle for a step, in degrees."""
        return self.view_rz if step.view_rz is None else step.view_rz

    def _rot_for(self, step):
        return view_rotation(self.step_angle(step))

    def _box(self, placements, angles, pulled=()):
        """
        The frame `placements` need, under every one of `angles` - and room
        for `pulled`, the parts where an exploded step draws them.
        """
        from .render import bounds, union_bounds, visible, world_prims

        boxes = []
        if self.opts.explode:
            placements = placements + list(pulled)
        for a in angles:
            rot = view_rotation(a)
            prims = visible(world_prims(placements, self.opts, rot))
            x0, y0, x1, y1 = bounds(prims, self.opts)
            # Insertion arrows stand off the model, so the frame has to leave
            # room for them or they get cropped at the edge of the drawing.
            for p in placements:
                tail = (arrow_tail(p, rot)
                        if p.arrow and not self.opts.explode
                        and STYLES[self.style].get("arrows", True) else None)
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
        return self._frame(range(len(self.steps)))

    def _items_through(self, hi):
        """
        [(placement, name, colour, step index)] for the first `hi` steps,
        where each part is at step `hi` - moved by any `turn` on the way.
        """
        out = []
        for i, s in enumerate(self.steps[:hi]):
            if s.turn is not None:
                out = [(turned(p, s.turn), n, c, k) for p, n, c, k in out]
            out = [x for x in out if not x[0].temp]
            out.extend((p, n, c, i) for p, n, c, _q in s.items)
        return out

    def _scene(self, i):
        """
        What step `i` draws: ([(placement, name, colour)] with each
        placement's `new`, `arrow` and `group` set for the drawing, and the
        same for the step finished).

        A step of a module built to one side (`aside`) shows that module
        alone.  A `join` step moves one whole piece onto the other: the
        module onto the model, or the model so far onto the module.  Until
        it is joined, a module built aside is left out of other steps.
        """
        step = self.steps[i]
        before = self._items_through(i)
        if step.turn is not None:     # this step starts with the model turned
            before = [(turned(p, step.turn), n, c, k) for p, n, c, k in before]
        joined = set()
        for k in range(i):
            if self.steps[k].join:
                t = self.steps[k].join[0]
                joined.update(t if isinstance(t, tuple) else (t,))
        mine = [(p, n, c) for p, n, c, _k in before]
        tokens = [self.steps[k].alone for _p, _n, _c, k in before]
        new = [(p, n, c) for p, n, c, _q in step.items]

        def old(group):
            return [(Placement(p.part, p.tf, new=False), n, c)
                    for p, n, c in group]

        if step.alone is not None:
            ctx = [x for x, t in zip(mine, tokens) if t == step.alone]
            if step.shown is not None:
                ctx = [(turned(p, step.shown), n, c) for p, n, c in ctx]
                new = [(turned(p, step.shown), n, c) for p, n, c in new]
        elif step.join:
            token, which, way, _label = step.join
            rest = [x for x, t in zip(mine, tokens)
                    if t is None or t in joined]
            own = new
            if token == "self":         # `bring`: the step's own module
                piece, own = new, []
            elif token is None:         # the step's own parts are the piece
                piece = []
            else:
                several = token if isinstance(token, tuple) else (token,)
                piece = [x for x, t in zip(mine, tokens) if t in several]
            if which == "aside" and token is not None:
                # Parts the step adds with no arrow of their own go on to
                # the piece first, and travel with it.
                piece = piece + [x for x in own if x[0].arrow is None]
                own = [x for x in own if x[0].arrow is not None]
            moving, still = (rest, piece) if which == "built" else (piece, rest)
            d = arrow_dir(way)
            drawn = old(still) + [
                (Placement(p.part, p.tf, new=True, arrow=d, group=("join", i),
                           pull=step.join_pull), n, c) for p, n, c in moving]
            done = old(still) + [(Placement(p.part, p.tf, new=True), n, c)
                                 for p, n, c in moving]
            drawn += [(Placement(p.part, p.tf, new=True, arrow=p.arrow,
                                 group=p.group, pull=p.pull), n, c)
                      for p, n, c in own]
            done += [(Placement(p.part, p.tf, new=True), n, c)
                     for p, n, c in own]
            return drawn, done
        else:
            ctx = [x for x, t in zip(mine, tokens) if t is None or t in joined]
        drawn = old(ctx) + [(Placement(p.part, p.tf, new=True, arrow=p.arrow,
                                       group=p.group, pull=p.pull), n, c)
                            for p, n, c in new]
        done = old(ctx) + [(Placement(p.part, p.tf, new=True), n, c)
                           for p, n, c in new]
        return drawn, done

    def _frame(self, idx):
        """The one frame that holds every step in `idx`, pulled apart and
        finished, from each step's own camera angle."""
        boxes = []
        for i in idx:
            drawn, done = self._scene(i)
            pls = [p for p, _n, _c in drawn]
            if self.opts.explode:
                pls = (exploded(pls, self.opts.pull)[0]
                       + [p for p, _n, _c in done])
            boxes.append(self._box(pls, {self.step_angle(self.steps[i])}))
        from .render import union_bounds
        return union_bounds(*boxes)

    def step_boxes(self):
        """
        One frame per step - shared across a section, regrown at each one.

        Registering every step against the finished model is right for a
        six-step build and wrong for a forty-step one, where it leaves the
        first steps as a thumbnail adrift in a page sized for a whole robot.
        A section is the unit that keeps registration worth having: inside it
        the model holds still, and the boundary where the frame changes is
        the one place the reader is already being told to look.  A turn of
        the model, a module built aside and the step that joins it each
        start a frame of their own too.
        """
        groups, cur, key = [], [], None
        for i, s in enumerate(self.steps):
            # The printed guides each frame every step on its own, as big as
            # the page allows.
            k = i if self.frame_each else (id(s.section), s.alone, bool(s.join))
            if cur and (k != key or s.turn is not None or s.join):
                groups.append(cur)
                cur = []
            cur.append(i)
            key = k
        if cur:
            groups.append(cur)
        boxes = [None] * len(self.steps)
        for g in groups:
            box = self._frame(g)
            for i in g:
                boxes[i] = box
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
        for i, step in enumerate(self.steps):
            drawn, _done = self._scene(i)
            # A step that adds nothing is a "check your work" step: drawn at
            # full detail, since nothing there is background.
            check = not any(p.new for p, _n, _c in drawn)
            placements = [
                p if p.new else Placement(self._context_part(p, n, c, check),
                                          p.tf, new=False)
                for p, n, c in drawn]
            out.append((i + 1, step,
                        render(placements, self.opts, self._rot_for(step),
                               boxes[i], styles=styles,
                               arrows=STYLES[self.style].get("arrows", True),
                               title=self.step_alt(i + 1, step))))
        return out

    def step_insets(self, px=150.0, full=False):
        """
        [svg or None] per step: the model as it stands once the step is done,
        for a step whose parts are drawn pulled back.  Small, for the corner
        of the step - or with `full`, at the step drawing's own scale and
        frame, with the new parts still marked, as the 2nd-gen guides draw
        it beside the pulled-apart view.
        """
        out = []
        boxes = self.step_boxes() if full else None
        for i, step in enumerate(self.steps):
            drawn, done = self._scene(i)
            if not (self.opts.explode and any(p.arrow for p, _n, _c in drawn)):
                out.append(None)
                continue
            placements = [p for p, _n, _c in done]
            rot = self._rot_for(step)
            title = f"Step {i + 1} finished."
            if full:
                opts = RenderOpts(scale=self.opts.scale, pad=self.opts.pad,
                                  highlight=self.opts.highlight,
                                  fade_old=self.opts.fade_old,
                                  line_scale=self.opts.line_scale,
                                  ring=self.opts.ring,
                                  ring_w=self.opts.ring_w)
                out.append(render(placements, opts, rot, boxes[i],
                                  arrows=False, title=title))
                continue
            probe = RenderOpts(scale=1.0, pad=0.0, highlight=False)
            x0, y0, x1, y1 = bounds(visible(world_prims(placements, probe, rot)),
                                    probe)
            # The 16:9 guides keep the new parts ringed in the small view too.
            ring = self.opts.ring if self.style == "slides" else None
            opts = RenderOpts(scale=px / max(x1 - x0, y1 - y0, 1e-6), pad=4.0,
                              highlight=ring is not None, fade_old=0.0,
                              line_scale=self.opts.line_scale, ring=ring,
                              ring_w=0.6)
            out.append(render(placements, opts, rot, arrows=False, title=title))
        return out

    def _context_part(self, placement, name, color, at_full_colour):
        """The geometry an already-built part is drawn with."""
        if self.context_detail is None or at_full_colour:
            return placement.part
        try:
            return get(name, color, detail=self.context_detail)
        except UnknownPart:     # a part made on the spot has one form only
            return placement.part

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
