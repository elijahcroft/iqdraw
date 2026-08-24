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
    +y  left to right; the two rails sit at y = {-1, 0} and y = {5, 6}
    +z  up; the rails' mid-plane is z = 0

Coordinates are 0-BASED.
"""

from iqdraw import Assembly

AXLE_X = (1, 10)     # the two axles, near each end of the rail
WHEEL_Y = 2.2        # outboard of the rail's outer face at y = 1.5
COLLAR_Y = 3.1       # outboard of the wheel hub, still on the shaft
RAIL_Y = 5           # where the second side frame's rail lands
CROSS_X = (2, 9)     # the two cross beams, clear of both wheels
JOINT_Z = 0.25       # the face where a cross beam meets a rail
DECK_Z = 0.5         # the cross beams' mid-plane: one beam above the rails

# --------------------------------------------------------------- side frame
# Built at its own origin, as though it were the only thing on the table.
# Outboard is +y: the shaft runs out that way and the wheel goes on the end.

side_frame = Assembly("Side Frame")

with side_frame.step("Lay a 2x12 beam down flat. This is one side of the "
                     "chassis.") as s:
    s.add("beam_2x12", (0, 0, 0))

with side_frame.step(
        "Push a shaft through hole 1 and hole 10 of the front row.",
        caption="Count from the end: hole 1 is the second hole along.") as s:
    s.many("shaft_4", [(x, 0, 0) for x in AXLE_X], axis="y", arrow="+y")

with side_frame.step(
        "Push a wheel onto the end of each shaft.",
        caption="The flat of the shaft has to line up with the square hole "
                "in the wheel - turn the wheel until it drops on.") as s:
    s.many("wheel_200", [(x, WHEEL_Y, 0) for x in AXLE_X], axis="y",
           arrow="+y")

with side_frame.step(
        "Lock a collar on the outside of each wheel.",
        caption="Press it right up to the wheel. A gap here is what makes a "
                "wheel fall off later.") as s:
    s.many("collar", [(x, COLLAR_Y, 0) for x in AXLE_X], axis="y", arrow="+y")


def add_chassis(b, first_section="One side frame", brain=True):
    """
    Put a complete rolling chassis into build `b`, in its own sections.

    Two side frames, the second mirrored, joined by two cross beams - and the
    brain on top unless the build wants that space for something else.
    """
    b.section(
        first_section,
        "Build this once. You will build a second one just like it, the "
        "other way round.",
    )
    b.place(side_frame, at=(0, RAIL_Y, 0))

    b.section(
        "The other side frame",
        "The same four steps again. The wheels still go on the outside - "
        "which is now the other way round.",
    )
    b.place(side_frame, at=(0, 0, 0), mirror="y",
            note="Build a second side frame exactly like the first, and set "
                 "it down mirrored - wheels facing out.",
            caption="Hold them side by side. They should look like a pair "
                    "of hands, not like two left hands.")

    b.section("Joining the two sides",
              "This is what turns two rails into a robot.")

    with b.step("Lay a 1x8 beam across both rails, near the front.",
                caption="Turn it a quarter turn so it runs across the rails, "
                        "not along them.") as s:
        s.add("beam_1x8", (CROSS_X[0], -1, DECK_Z), rot=(0, 0, 90), arrow=True)

    with b.step("Push four connector pins down through the cross beam into "
                "the rails underneath.",
                caption="Two pins into each rail. One pin per rail would let "
                        "the frame pivot - the second pin is what stops "
                        "it.") as s:
        s.many("pin_1x1", [(CROSS_X[0], y, JOINT_Z) for y in (-1, 0, 5, 6)],
               axis="z", arrow=True)

    with b.step("Repeat at the back: one cross beam, four more pins.") as s:
        s.add("beam_1x8", (CROSS_X[1], -1, DECK_Z), rot=(0, 0, 90))
        s.many("pin_1x1", [(CROSS_X[1], y, JOINT_Z) for y in (-1, 0, 5, 6)],
               axis="z", arrow=True)

    if brain:
        b.section("The brain")
        with b.step("Sit the brain on the two cross beams, ports facing the "
                    "back.",
                    caption="It should sit flat. If it rocks, a pin "
                            "underneath is not pushed all the way home.") as s:
            s.add("brain", (2, 0, 1.25), arrow=True)
    return b
