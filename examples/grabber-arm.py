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

  * eighteen steps in seven named sections, each framed on the build so far

The heights, since a floating arm is the thing that is easy to get wrong:

    rails                   z = 0      (0.5 thick, so -0.25 .. +0.25)
    cross beams and the     z = 0.5    resting on the rails
      towers' feet
    tower top hole          z = 4.5    corner_2x4 feet at 0.5, four holes up
    arm beams               z = 4.5    on the pivot shaft, between the towers
    claw                    z = 5.0    resting on the arm beam tips

Coordinates are 0-BASED.  The robot faces -x: the arm reaches out that way.
"""

from iqdraw import Assembly, Build

from _modules import add_chassis

TOWER_X = 0            # the towers stand on the front holes of each rail
TOWER_Y = (-1, 6)      # the outer hole of each rail
FOOT_Z = 0.5           # a corner's foot rests on the rail, like a cross beam
PIVOT_Z = 4.5          # four holes up the tower: where the arm swings
ARM_Y = (0, 5)         # the arm beams, just inside the towers
ARM_TIP = -5           # a 1x6 beam reaching forward from the pivot
SHAFT_AT = -1.5        # the pivot shaft starts just outside the near tower
RETAIN_Y = (-1.7, 6.7) # collars, flush against the outer face of each tower
CLAW_Z = 5.0           # the claw rests on top of the arm beam tips

# ------------------------------------------------------------------- a finger
# Built at its own origin: the beam reaches out along -x and the tip turns
# inward along +y.  That inward turn is what makes a finger handed - and so
# what makes the second one a mirror.

finger = Assembly("Claw Finger")

with finger.step("Lay a 1x4 beam down. This is one finger.") as s:
    s.add("beam_1x4", (0, 0, 0), rot=(0, 0, 180))

with finger.step("Pin a 1x2 beam across the tip, turned a quarter turn so it "
                 "points inwards.",
                 caption="This is the part that actually grips. Both fingers "
                         "turn in towards each other.") as s:
    s.add("beam_1x2", (-3, 0, 0.5), rot=(0, 0, 90), arrow=True)
    s.add("pin_1x1", (-3, 0, 0.25), axis="z", arrow=True)

# --------------------------------------------------------------------- a claw
# An assembly made of assemblies: two fingers, the second one mirrored.

claw = Assembly("Claw")
claw.place(finger, at=(0, 0, 0))
claw.place(finger, at=(0, 5, 0), mirror="y",
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
    done="the arm swings up and down freely, and both claw tips meet in the "
         "middle when you close them",
    scale=26,
    view_rz=-24,
    context_detail="simple",
)

add_chassis(b, first_section="One side frame")

# ------------------------------------------------------------------- the tower

b.section("The two towers",
          "These hold the arm up. They go on the outer hole of each rail, "
          "clear of the wheels.")

with b.step("Stand a 2x4 corner connector on each rail at the front, foot "
            "pointing backwards.",
            caption="The tall leg goes up. Both towers lean the same way.") as s:
    s.many("corner_2x4", [(TOWER_X, y, FOOT_Z) for y in TOWER_Y], arrow=True)

with b.step("Pin each tower foot down into the rail underneath - two pins "
            "each.",
            caption="Two pins, not one. One pin lets the tower rock "
                    "forwards.") as s:
    s.many("pin_1x1",
           [(x, y, 0.25) for y in TOWER_Y for x in (TOWER_X, TOWER_X + 1)],
           axis="z", arrow=True)

# --------------------------------------------------------------------- the arm

b.section("The arm", "Both beams have to swing together, so they share one "
                     "shaft.")

with b.step("Hold a 1x6 beam against the inside of each tower, reaching "
            "forwards, with its end hole level with the top of the tower.",
            caption="Nothing holds these yet. The shaft in the next step is "
                    "what catches them.") as s:
    s.many("beam_1x6", [(0, y, PIVOT_Z) for y in ARM_Y], rot=(0, 0, 180))

with b.step("Push one long shaft through the whole lot: tower, arm, arm, "
            "tower.",
            caption="Line up all four holes before you push. If it will not "
                    "go, one arm beam is a hole out.") as s:
    s.add("shaft_9", (TOWER_X, SHAFT_AT, PIVOT_Z), axis="y", arrow="+y")

with b.step("Lock a collar on each end of the shaft, outside the towers.",
            caption="Leave a little play - the arm has to swing, not "
                    "grip.") as s:
    s.many("collar", [(TOWER_X, y, PIVOT_Z) for y in RETAIN_Y], axis="y",
           arrow=True)

# -------------------------------------------------------------------- the claw

b.place(claw, at=(ARM_TIP, ARM_Y[0], CLAW_Z), section="The claw")

b.section("Fitting the claw")

with b.step("Pin each finger down onto the end of an arm beam.",
            caption="The fingers sit on top of the arm, not inside it.") as s:
    s.many("pin_1x1", [(ARM_TIP, y, 4.75) for y in ARM_Y], axis="z",
           arrow=True)

with b.step("Check it. Push the base along the floor, then swing the arm up "
            "and down. Close the two tips together.",
            caption="The arm should move with one finger and stay where you "
                    "leave it. If it drops, the collars are too tight or too "
                    "loose.") as s:
    pass
