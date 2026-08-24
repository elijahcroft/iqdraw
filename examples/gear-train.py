"""
Gear Ratio Demonstrator - three meshing gears on one beam.

The spacing is not decorative.  VEX IQ gears share a module, so two gears mesh
when the gap between their shafts equals the sum of their pitch radii, and a
pitch radius is teeth/24 holes:

    12T + 36T  ->  0.5 + 1.5 = 2 holes apart
    36T + 60T  ->  1.5 + 2.5 = 4 holes apart

which is why the shafts sit at holes 0, 2 and 6.  Turn the crank once and the
60-tooth gear turns a fifth of a revolution: a 5:1 reduction the students can
count tooth by tooth.

Coordinates here are 0-BASED.  "Hole 2" in this file is the third hole a
student counts along the beam.
"""

from iqdraw import Build

# Height of each layer above the beam's mid-plane.  Named rather than inlined
# so the stack stays obvious and adjustable.
SPACER_Z = 0.375  # 0.25x spacer sits on the beam's top face
GEAR_Z = 0.75     # 0.5x-thick gear lands on the spacer
COLLAR_Z = 1.18   # locks down on the gear's top face
CRANK_Z = 1.61    # underside lands on top of the collar

SHAFTS = [(0, "gear_12"), (2, "gear_36"), (6, "gear_60")]

b = Build(
    "Gear Ratio Demonstrator",
    subtitle="VEX IQ (2nd gen) - 12T / 36T / 60T train",
    intro="A hand-cranked three-gear train. Count the teeth, turn the crank, "
          "and work out how far the big gear moves for one turn of the small "
          "one. Build time is about 15 minutes.",
    done="turning the crank turns all three gears, with no free play",
    scale=40,
)

with b.step("Lay the 2x12 beam down flat. This is the whole chassis.") as s:
    s.add("beam_2x12", (0, 0, 0))

with b.step("Push a shaft down through holes 0, 2 and 6 of the front row.",
            caption="Leave about half a hole of shaft sticking out underneath.") as s:
    s.many("shaft_3", [(x, 0, 0) for x, _ in SHAFTS], axis="z", arrow=True)

with b.step("Drop one spacer over each shaft. These hold the gears clear of "
            "the beam so they can spin freely.") as s:
    s.many("spacer", [(x, 0, SPACER_Z) for x, _ in SHAFTS], axis="z",
           arrow=True)

with b.step("Slide the gears on: 12-tooth, then 36-tooth, then 60-tooth.",
            caption="Check that each pair actually meshes before you go on - "
                    "the teeth should turn each other with no free play.") as s:
    for x, gear in SHAFTS:
        s.add(gear, (x, 0, GEAR_Z), axis="z", arrow=True)

with b.step("Lock a collar onto each shaft above the gear.") as s:
    s.many("collar", [(x, 0, COLLAR_Z) for x, _ in SHAFTS], axis="z",
           arrow=True)

with b.step("Finish with a crank arm on the 12-tooth shaft, and a standoff "
            "through its far end for a handle.",
            caption="The arm points out to the side so it swings clear of the "
                    "other two gears.") as s:
    s.add("beam_1x4", (0, 0, CRANK_Z), rot=(0, 0, 90))
    s.add("standoff_2", (0, 3, CRANK_Z + 0.25), axis="z")
