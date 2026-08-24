"""
Two-Wheel Drive Base - the rolling chassis most other builds bolt onto.

The chassis itself lives in `_modules.py`, because the clawbot is the same
robot from the wheels to the cross beams and the two should not be able to
drift apart. This file is the cover, the finish condition, and the call that
puts the chassis in.

What `_modules.add_chassis` demonstrates, and the reason it is written as
modules rather than one flat list of coordinates: the side frame is described
once and placed twice, the second time through `mirror="y"`. There is no
rotation that turns a left side into a right side - a reflection is the only
thing that does it.
"""

from iqdraw import Build

from _modules import add_chassis

b = Build(
    "Two-Wheel Drive Base",
    subtitle="VEX IQ (2nd gen) - rolling chassis",
    intro="Two side frames, joined by two cross beams, with the brain on "
          "top. It rolls when you push it, and it is the base most other "
          "builds start from. Build time is about 25 minutes.",
    done="both sides roll freely, and twisting two opposite corners moves "
         "nothing",
    scale=30,
    view_rz=-20,
)

add_chassis(b)

with b.step("Check it. Push the base along the floor - both wheels should "
            "turn freely. Then hold two opposite corners and twist.",
            caption="Nothing should move. If it racks, press each pin home "
                    "until it clicks.") as s:
    pass
