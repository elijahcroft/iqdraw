"""
Modules shared between builds.

A chassis described once, imported by every build that rolls on one. This is
the same argument `Assembly` makes inside a single file, one level up: the
drive base and the clawbot are the same robot from the wheels to the cross
beams, and they should not be two descriptions that can drift apart.

Files here starting with `_` are libraries, not builds - nothing renders them
directly.

Everything is in the chassis frame:

    +x  front to back, holes 0..11
    +y  left to right; the two rails stand on edge at y = 0 and y = 6
    +z  up; the rails' bottom row of holes is z = 0, the top row z = 1

The rails stand ON EDGE so their holes face sideways.  A beam's holes only
run through its face, so an axle can only cross a rail that is turned to face
it - a rail lying flat would need the axle to go through solid plastic.

Placement uses refs (what `s.add` returns): every spacer, wheel and collar is
stacked against the part before it with `on=`, so no height or offset in this
file is worked out by hand.

Coordinates are 0-BASED.
"""

from types import SimpleNamespace

from iqdraw import Assembly

AXLE_X = (1, 10)     # the two axles, near each end of the rail
BRACKET_X = (3, 8)   # the corner brackets the cross beams sit on
RAIL_Y = 6           # where the second side frame's rail stands

EDGE = (90, 0, 0)            # a beam turned up on edge: holes face along y
HANG = (180, 0, -90)         # a corner bracket hung foot-up, foot facing -y

# --------------------------------------------------------------- side frame
# Built at its own origin, as though it were the only thing on the table.
# Outboard is +y: the axles run out that way and the wheels go on the end.
# Inboard is -y, where the corner brackets go.

side_frame = Assembly("Side Frame")

with side_frame.step("Stand a 2x12 beam up on its long edge. This is one "
                     "side of the chassis.",
                     caption="The holes should face sideways, two rows "
                             "of twelve.") as s:
    rail = s.add("beam_2x12", (0, 0, 0), rot=EDGE)

with side_frame.step(
        "Push a short shaft through hole 1 and hole 10 of the bottom row.",
        caption="Count from the end: hole 1 is the second hole along. Leave "
                "a little sticking out on the inside.") as s:
    axles = s.many("shaft_3", [rail.hole(x) + (0, -0.2, 0) for x in AXLE_X],
                   arrow="+y")

with side_frame.step(
        "On the outside, slide a spacer and then a wheel onto each shaft.",
        caption="The spacer keeps the wheel from rubbing the rail. Turn the "
                "wheel until its square centre drops onto the shaft.") as s:
    spacers = [s.add("spacer", rail.hole(x), on=rail, side="+y", arrow="+y")
               for x in AXLE_X]
    wheels = [s.add("wheel_200", rail.hole(x), on=sp, side="+y", arrow="+y")
              for x, sp in zip(AXLE_X, spacers)]

with side_frame.step(
        "Lock a collar on each shaft, on both sides: one outside the wheel, "
        "one against the inside of the rail.",
        caption="The two collars trap the shaft. Without the inside one, the "
                "wheel pulls the shaft straight out.") as s:
    for x, w in zip(AXLE_X, wheels):
        s.add("collar", rail.hole(x), on=w, side="+y", arrow="+y")
        s.add("collar", rail.hole(x), on=rail, side="-y", arrow="-y")

with side_frame.step(
        "Push four pins into the inside of the rail: holes 3 and 8, both "
        "rows.",
        caption="Push each one halfway. The other half holds the bracket in "
                "the next step.") as s:
    s.many("pin_1x1", [rail.hole(x, r, side="-y") for x in BRACKET_X
                       for r in (0, 1)], arrow="+y")

with side_frame.step(
        "Press a 2x2 corner bracket onto each pair of pins, foot on top and "
        "pointing inwards.",
        caption="The foot sits just above the rail. The cross beams rest "
                "on it.") as s:
    brackets = [s.add("corner_2x2", rail.hole(x, 1) + (0, -0.5, 1),
                      rot=HANG, arrow="+y")
                for x in BRACKET_X]


def add_chassis(b, first_section="One side frame", brain=True):
    """
    Put a complete rolling chassis into build `b`, in its own sections.

    Two side frames, the second mirrored, joined by two cross beams on the
    corner brackets - and the brain on top unless the build wants that space
    for something else.  Returns what a build adds to next: `.rails`, the two
    rails as placed (y = 0 first), and `.cross`, the two cross beams.
    """
    b.section(
        first_section,
        "Build this once. You will build a second one just like it, the "
        "other way round.",
    )
    right = b.place(side_frame, at=(0, RAIL_Y, 0))

    b.section(
        "The other side frame",
        "The same steps again. The wheels still go on the outside - which is "
        "now the other way round.",
    )
    left = b.place(side_frame, at=(0, 0, 0), mirror="y",
                   note="Build a second side frame exactly like the first, "
                        "and set it down mirrored - wheels facing out.",
                   caption="Hold them side by side. They should look like a "
                           "pair of hands, not like two left hands.")

    b.section("Joining the two sides",
              "This is what turns two rails into a robot.")

    # Each pair of brackets facing each other across the chassis, front and
    # back, where the two copies of the side frame put them.  A cross beam
    # rests on a pair's feet and pins down through both holes of each foot.
    pairs = [(left(br), right(br)) for br in brackets]

    def feet(pair):
        return [br.hole(i, side="up") for br in pair for i in (0, 1)]

    cross = []
    with b.step("Lay a 1x6 beam across the two front brackets.",
                caption="Turn it a quarter turn so it runs across the "
                        "chassis, not along it.") as s:
        cross.append(s.add("beam_1x6", pairs[0][0].hole(0), rot=(0, 0, 90),
                           on=list(pairs[0]), arrow=True))

    with b.step("Push four connector pins down through the cross beam into "
                "the bracket feet underneath.",
                caption="Two pins into each foot. One pin per foot would let "
                        "the frame pivot - the second pin is what stops "
                        "it.") as s:
        s.many("pin_1x1", feet(pairs[0]), arrow=True)

    with b.step("Repeat at the back: one cross beam, four more pins.") as s:
        cross.append(s.add("beam_1x6", pairs[1][0].hole(0), rot=(0, 0, 90),
                           on=list(pairs[1])))
        s.many("pin_1x1", feet(pairs[1]), arrow=True)

    if brain:
        b.section("The brain")
        with b.step("Sit the brain on the two cross beams, screen up.",
                    caption="It should sit flat. If it rocks, a pin "
                            "underneath is not pushed all the way home.") as s:
            s.add("brain", (2, 0, 0), on=cross, arrow=True)
    return SimpleNamespace(rails=(left(rail), right(rail)), cross=cross)
