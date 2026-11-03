"""
Grabber Arm - the drive base with a pivoting claw on the front.

This is the build that needs every piece of the composition machinery at once,
and it is worth reading for that:

  * the whole rolling chassis comes from `_modules.py`, shared with
    `drive-base.py`, so the two robots cannot drift apart below the deck

  * a claw finger is an `Assembly`; the claw is an `Assembly` that places two
    fingers, the second mirrored; the build places the claw.  Assemblies nest,
    so the claw is described once at its own origin and lands wherever the arm
    tips end up

  * the second finger is a mirror, not a rotation.  Nothing you can do by
    turning a left finger makes a right one

  * every pivot runs through real holes.  The arm swings about a shaft along
    y, so everything that shaft passes through - towers, spacers, arm beams -
    stands with its holes facing y

The layout across the robot, at the pivot (y, left to right):

    collar | tower | spacer | arm   ...claw...   arm | spacer | tower | collar
              0.5     0.875   1.25                4.75   5.125    5.5

Coordinates are 0-BASED.  The robot faces -x: the arm reaches out that way.
"""

from iqdraw import Assembly, Build

from _modules import add_chassis

PIVOT_Z = 5            # the tower's top hole, five up from the rail's bottom
ARM_REACH = (0, -4, -5)  # pivot hole, then the two holes the fingers pin to
TIE_X = -2             # the standoff that makes both arm beams one arm
STAND = (0, -90, 90)   # a beam stood upright, holes facing along y
INSIDE = ("+y", "-y")  # which way is inwards from each rail, y = 0 first
OUTSIDE = {"+y": "-y", "-y": "+y"}

# ------------------------------------------------------------------- a finger
# Built at its own origin: a beam on edge reaching out along -x, with a
# standoff at the tip pointing inward along +y.  That inward tip is what makes
# a finger handed - and so what makes the second one a mirror.

finger = Assembly("Claw Finger")

with finger.step("Stand a 1x4 beam on its edge. This is one finger.") as s:
    blade = s.add("beam_1x4", (0, 0, 0), rot=(90, 0, 180))

with finger.step("Pin a 1x standoff to the inside of the tip, pointing "
                 "inwards.",
                 caption="This is the part that actually grips. Both fingers "
                         "point in towards each other.") as s:
    tip = blade.hole(3, side="+y")
    s.add("pin_1x1", tip, arrow="-y")
    s.add("standoff_1", tip, arrow="-y")

# --------------------------------------------------------------------- a claw
# An assembly made of assemblies: two fingers, the second one mirrored, set
# far enough apart that their two standoff tips meet in the middle.

claw = Assembly("Claw")
claw.place(finger, at=(0, 0, 0))
claw.place(finger, at=(0, 2.5, 0), mirror="y",
           note="Build a second finger and mirror it, so the two tips face "
                "each other.",
           caption="Lay them next to each other first. If both tips point "
                   "the same way, one of them is built the wrong way round.")

# ---------------------------------------------------------------- the whole job

b = Build(
    "Grabber Arm",
    subtitle="VEX IQ (2nd gen) - drive base with a pivoting claw",
    intro="The rolling drive base, with two towers, an arm that swings on a "
          "shaft, and a claw that grips. The arm is moved by hand. Build "
          "time is about 45 minutes.",
    done="the arm swings up and down freely, and the two claw tips meet in "
         "the middle",
    scale=26,
    view_rz=-24,
    context_detail="simple",
)

chassis = add_chassis(b, first_section="One side frame")

# ------------------------------------------------------------------- the tower

b.section("The two towers",
          "These hold the arm up. They stand inside the front of each rail, "
          "clear of the wheels.")

with b.step("Push two pins into the inside of each rail at the front hole, "
            "one in each row.",
            caption="Push each one halfway in. The tower goes on the "
                    "other half.") as s:
    for rail, side in zip(chassis.rails, INSIDE):
        s.many("pin_1x1", [rail.hole(0, r, side=side) for r in (0, 1)],
               arrow=OUTSIDE[side])

with b.step("Press a 1x6 beam onto each pair of pins, standing straight up.",
            caption="Both towers stand upright and face each other "
                    "across the robot.") as s:
    towers = [s.add("beam_1x6", rail.hole(0), rot=STAND, on=rail, side=side,
                    arrow=OUTSIDE[side])
              for rail, side in zip(chassis.rails, INSIDE)]

# --------------------------------------------------------------------- the arm

b.section("The arm", "Both beams swing on one shaft, and a standoff ties them "
                     "together so they move as one arm.")

with b.step("Slide a spacer onto the inside of each tower's top hole, then "
            "hold a 1x6 beam on edge against it, reaching forwards.",
            caption="Nothing holds these yet. The shaft in the next step is "
                    "what catches them.") as s:
    arms = []
    for tower, side in zip(towers, INSIDE):
        sp = s.add("spacer", tower.hole(PIVOT_Z), on=tower, side=side)
        arms.append(s.add("beam_1x6", tower.hole(PIVOT_Z), rot=(90, 0, 180),
                          on=sp, side=side))

with b.step("Push one long shaft through the whole lot: tower, spacer, arm, "
            "arm, spacer, tower.",
            caption="Line up all six holes before you push. If it will not "
                    "go, one arm beam is a hole out.") as s:
    s.add("shaft_7", towers[0].hole(PIVOT_Z) + (0, -0.15, 0), arrow="+y")

with b.step("Lock a collar on each end of the shaft, outside the towers.",
            caption="Leave a little play - the arm has to swing, not "
                    "grip.") as s:
    for tower, side in zip(towers, INSIDE):
        s.add("collar", tower.hole(PIVOT_Z), on=tower, side=OUTSIDE[side],
              arrow=side)

with b.step("Tie the two arm beams together with a 3x standoff, two holes "
            "in from the pivot.",
            caption="A pin through each arm beam into each end of the "
                    "standoff.") as s:
    near = arms[0].hole(abs(TIE_X), side="+y")
    s.add("pin_1x1", near, arrow="+y")
    s.add("standoff_3", near)
    s.add("pin_1x1", arms[1].hole(abs(TIE_X), side="-y"), arrow="-y")

# -------------------------------------------------------------------- the claw

claw_at = arms[0].hole(abs(ARM_REACH[1]), side="+y") + (0, 0.25, 0)
b.place(claw, at=claw_at, section="The claw")

b.section("Fitting the claw")

with b.step("Pin each finger to the inside of the end of an arm beam - two "
            "pins each.",
            caption="Two pins, not one. One pin lets the finger flop.") as s:
    for arm, side in zip(arms, INSIDE):
        s.many("pin_1x1", [arm.hole(abs(x), side=side) for x in ARM_REACH[1:]],
               arrow=side)

with b.step("Check it. Push the base along the floor, then swing the arm up "
            "and down. Look down the claw: the two tips should meet.",
            caption="The arm should move with one finger and stay where you "
                    "leave it. If it drops, the collars are too tight or too "
                    "loose.") as s:
    pass
