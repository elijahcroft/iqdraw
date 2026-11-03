"""Six-Wheel Survey Rover - a flagship example for the IQDraw gallery.

The rover is intentionally broader than the other worked builds.  It shows
how one readable specification can describe repeated suspension modules,
mirrored geometry, a layered deck, electronics, a bumper and a raised sensor
mast without turning into a wall of absolute coordinates.

The design is a classroom model rather than a competition drivetrain: all six
wheels roll freely, the brain sits on a rigid deck, and the distance sensor is
high enough to see over the front bumper.  It is meant to be pushed by hand
while students collect or discuss sensor readings.

Every joint is a real one, and `iqdraw --check-only --strict` holds it to
that: axles cross the rails through holes because the rails stand on edge,
the deck rests on corner brackets pinned to the rails, and the mast feet sit
on a bumper beam wide enough to take both of their pins.

Placement uses refs - what `s.add()` returns - so stacked parts are placed
with `on=` against the part below, and pins at a hole's face with
`hole(..., side=)`.  No height in this file is worked out by hand.

Coordinates are 0-BASED.  The rover faces -x; +z is up.
"""

from iqdraw import Assembly, Build


AXLE_X = (1, 5, 10)
BRACKET_X = (0, 3, 8)   # the front bracket carries the bumper, the others the deck
FAR_SIDE_Y = 8
DECK_Y = (2.5, 5.5)     # deck pin rows, clear of the bracket pins beneath

EDGE = (90, 0, 0)       # a beam turned up on edge: holes face along y
HANG = (180, 0, -90)    # a corner bracket hung foot-up, foot facing -y
ACROSS = (0, 0, 90)     # a flat beam turned to run across the rover


# ---------------------------------------------------------- one wheel module
# Build one complete side at its own origin, then place it twice.  Mirroring
# the second copy keeps both sets of wheels on the outside of the chassis.
# Outboard is +y; inboard, where the brackets go, is -y.

side_module = Assembly("Six-Wheel Side Module")

with side_module.step(
        "Stand a grey 2x12 rail up on its long edge. This is one side of the "
        "rover.",
        caption="The holes face sideways, two rows of twelve.") as s:
    rail = s.add("beam_2x12", (0, 0, 0), rot=EDGE, color="vexgrey")

with side_module.step(
        "Push a short shaft through holes 1, 5 and 10 of the bottom row.",
        caption="Leave a little sticking out on the inside for a "
                "collar.") as s:
    s.many("shaft_3", [rail.hole(x) + (0, -0.2, 0) for x in AXLE_X],
           arrow="+y")

with side_module.step(
        "On the outside, slide a spacer and then a 160 mm wheel onto each "
        "shaft.",
        caption="Turn each wheel until its square centre drops onto the "
                "shaft.") as s:
    wheels = []
    for x in AXLE_X:
        sp = s.add("spacer", rail.hole(x), on=rail, side="+y", arrow="+y")
        wheels.append(s.add("wheel_160", rail.hole(x), on=sp, side="+y",
                            arrow="+y"))

with side_module.step(
        "Lock a collar on both ends of every shaft: outside the wheel and "
        "against the inside of the rail.",
        caption="The wheels should spin without sliding along their "
                "shafts.") as s:
    for x, w in zip(AXLE_X, wheels):
        s.add("collar", rail.hole(x), on=w, side="+y", arrow="+y")
        s.add("collar", rail.hole(x), on=rail, side="-y", arrow="-y")

with side_module.step(
        "Push pins into the inside of the rail at holes 0, 3 and 8, both "
        "rows.",
        caption="Halfway in. The brackets go on the other half.") as s:
    s.many("pin_1x1", [rail.hole(x, r, side="-y") for x in BRACKET_X
                       for r in (0, 1)], arrow="+y")

with side_module.step(
        "Press a 2x2 corner bracket onto each pair of pins, foot on top and "
        "pointing inwards.",
        caption="All three feet sit level, just above the rail.") as s:
    brackets = [s.add("corner_2x2", rail.hole(x, 1) + (0, -0.5, 1),
                      rot=HANG, arrow="+y")
                for x in BRACKET_X]


# --------------------------------------------------------------- whole rover

b = Build(
    "Six-Wheel Survey Rover",
    subtitle="VEX IQ (2nd gen) - modular exploration platform",
    intro="A hand-pushed classroom rover with six independently spinning "
          "wheels, a rigid equipment deck, front bumper and elevated distance "
          "sensor. It demonstrates mirrored modules, sections, coloured "
          "structure and a deliberate camera change. Build time is about "
          "50 minutes.",
    done="all six wheels spin freely, the chassis does not rack, and the "
         "distance sensor looks straight ahead over the bumper",
    scale=25,
    # Look towards the rover's front so the bumper and sensor lenses are
    # visible on the cover instead of hidden behind their housings.
    view_rz=156,
    context_detail="simple",
)

b.section(
    "First wheel module",
    "Build one complete side. The second side is the same module mirrored.",
)
far = b.place(side_module, at=(0, FAR_SIDE_Y, 0))

b.section(
    "Mirrored wheel module",
    "Repeat the same steps, but keep every wheel on the outside.",
)
near = b.place(
    side_module,
    at=(0, 0, 0),
    mirror="y",
)


# ---------------------------------------------------------- bridge and deck

# Each pair of brackets facing each other across the rover, front to back,
# where the two copies of the side module put them.
pairs = [(near(br), far(br)) for br in brackets]


def feet(pair, holes=(0, 1)):
    """The tops of a pair's foot holes, where pins go down into them."""
    return [br.hole(i, side="up") for br in pair for i in holes]


b.section(
    "Bridge the chassis",
    "Two cross beams make a ladder frame; the plate on top becomes the "
    "equipment deck.",
)

with b.step(
        "Lay a 1x8 beam across the brackets at the middle and at the back.",
        caption="Each beam reaches from one bracket foot to the other.") as s:
    cross = [s.add("beam_1x8", pair[0].hole(0), rot=ACROSS, on=list(pair),
                   arrow=True)
             for pair in pairs[1:]]

with b.step(
        "Pin both cross beams down into the bracket feet - four pins per "
        "beam.",
        caption="Use both holes of every foot. This is what stops the long "
                "chassis from racking.") as s:
    s.many("pin_1x1", [p for pair in pairs[1:] for p in feet(pair)],
           arrow=True)

with b.step(
        "Set a 4x8 plate on the two cross beams to make the equipment deck.",
        caption="The long edges run front to back, centred between the "
                "side rails.") as s:
    deck = s.add("plate_4x8", (2, DECK_Y[0], 0), color="vexgrey", on=cross,
                 arrow=True)

with b.step(
        "Lock the deck down with four connector pins.",
        caption="Two pins into each cross beam spread the load across the "
                "whole frame.") as s:
    s.many("pin_1x1", [c.hole(int(y - 0.5), side="up") for c in cross
                       for y in DECK_Y], arrow=True)


# --------------------------------------------------------------- controller

b.section("The controller", "The brain sits low and centred over the deck.")

with b.step(
        "Place the Robot Brain flat on the deck, screen facing up.",
        caption="Keep it centred so the rover carries the same weight on both "
                "sides.") as s:
    s.add("brain", (2.5, 1, 0), on=deck, arrow=True)


# ------------------------------------------------------------ front bumper

b.section(
    "Front bumper",
    "A bright cross beam protects the sensor mast and makes the rover's front "
    "edge obvious in every view.",
)

with b.step(
        "Lay a red 2x8 beam across the front brackets.",
        caption="Pin it down through the inner hole of each front foot.") as s:
    # Two holes wide: its second row lies over the feet, its first in
    # front of them, one hole further forward.
    bumper_beam = s.add("beam_2x8", pairs[0][0].hole(0) + (1, 0, 0),
                        rot=ACROSS, color="red", on=list(pairs[0]),
                        arrow=True)
    s.many("pin_1x1", feet(pairs[0], holes=(1,)), arrow=True)

with b.step(
        "Mount the bumper switch in the middle of the red beam.",
        caption="The red button faces up, clear of the wheels.") as s:
    s.add("bumper", (1, 3, 0), rot=(0, 0, 90), on=bumper_beam, arrow=True)


# ------------------------------------------------------------- sensor mast

b.section(
    "Sensor mast",
    "Two uprights and a crossbar lift the distance sensor above the bumper and "
    "the Robot Brain.",
)

with b.step(
        "Stand a yellow 2x4 corner connector on each end of the red beam.",
        caption="The tall legs point up; both feet point towards the back.") as s:
    masts = s.many("corner_2x4", [(0, y, 0) for y in (0.5, FAR_SIDE_Y - 0.5)],
                   color="yellow", on=bumper_beam, arrow=True)

with b.step(
        "Pin both mast feet down into the red beam.",
        caption="Two pins per foot keep the mast square.") as s:
    s.many("pin_1x1", [m.hole(x, side="-z") for m in masts for x in (0, 1)],
           arrow=True)

with b.step(
        "Pin a yellow 1x8 beam across the front of the two uprights, at the "
        "top hole.",
        caption="The crossbar should be level when viewed from the front.") as s:
    top = [m.hole(0, 0, 4, side="-x") for m in masts]
    s.many("pin_1x1", top, arrow="+x")
    # Against the uprights' front face, where the pins are - not the masts'
    # whole front, which the feet reach past.
    crossbar = s.add("beam_1x8", top[0], rot=(90, 0, 90), color="yellow",
                     on=top[0][0], side="-x", arrow="+x")

with b.step(
        "Fit the distance sensor at the centre of the yellow crossbar, lenses "
        "pointing forwards.",
        caption="The two black lenses should look over the bumper, not down "
                "at the deck.") as s:
    s.add("distance", crossbar.hole(3) + (0, 0, -0.1), rot=(0, 0, 90),
          on=crossbar, side="-x", arrow="+x")


# --------------------------------------------------------------- final check

b.section("Inspection")

with b.step(
        "Turn the rover around and inspect the far side. Spin every wheel, "
        "press the bumper and check that the mast is square.",
        caption="The view changes here on purpose so hidden collars and the "
                "sensor direction are easy to verify.",
        view_rz=-24) as s:
    pass
