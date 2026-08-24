"""
Pinned Rectangular Frame - the base every other build starts from.

Worth reading as a worked example of how the vertical stack lines up, because
that is the part students (and spec authors) get wrong:

    a beam is 0.5 units thick and centred on its own z, so a beam at z=0
    occupies -0.25 .. +0.25 and a beam resting on top of it sits at z=0.5

    a 1x1 connector pin is 1.0 long and centred on its z, so a pin at the
    z=0.25 interface reaches 0.25 into each of the two beams it joins

Coordinates are 0-BASED: hole 0 is the first hole a student counts.
"""

from iqdraw import Build

RAIL_Y = (0, 5)          # the two long rails, 5 holes apart
CROSS_X = (1, 10)        # where the cross beams land
JOINT_Z = 0.25           # the face where the rails and cross beams meet

b = Build(
    "Pinned Rectangular Frame",
    subtitle="VEX IQ (2nd gen) - starter chassis",
    intro="Two long rails and two cross beams, held together with eight "
          "connector pins. Rigid in every direction, and it is the base most "
          "other builds are bolted onto.",
    done="holding two opposite corners and twisting moves nothing at all",
    scale=38,
    view_rz=-20,
)

with b.step("Put the two 2x12 rails down flat, five holes apart.") as s:
    s.many("beam_2x12", [(0, y, 0) for y in RAIL_Y])

with b.step("Lay a 1x7 beam across both rails, near one end. Turn it a "
            "quarter turn so it runs across the rails, not along them.") as s:
    s.add("beam_1x7", (CROSS_X[0], 0, 0.5), rot=(0, 0, 90), arrow=True)

with b.step("Push four connector pins down through the cross beam into the "
            "rails underneath.",
            caption="Two pins into each rail. One pin per rail would let the "
                    "frame pivot - the second pin is what makes it rigid.") as s:
    s.many("pin_1x1",
           [(CROSS_X[0], y, JOINT_Z) for y in (0, 1, 5, 6)], axis="z",
           arrow=True)

with b.step("Repeat at the other end: one cross beam, four more pins.") as s:
    s.add("beam_1x7", (CROSS_X[1], 0, 0.5), rot=(0, 0, 90))
    s.many("pin_1x1",
           [(CROSS_X[1], y, JOINT_Z) for y in (0, 1, 5, 6)], axis="z",
           arrow=True)

with b.step("Check it. Hold two opposite corners and try to twist the frame - "
            "it should not move at all.",
            caption="If it racks, a pin is not seated. Press each one home "
                    "until it clicks.") as s:
    pass
