"""
The joint model for the part families beyond beams, pins and shafts: L and
angle beams, lock beams, the crank arm, plastic and motor shafts, the capped
pin, omni wheels, hubs and the mini standoff connector.
"""

import unittest

import support  # noqa: F401  (makes the checkout importable)

from iqdraw import Build
from iqdraw import joints as J
from iqdraw.check import check
from iqdraw.report import catalogue, report


def _kinds(b):
    return sorted(p.kind for p in check(b))


def _fits(b, rod, part):
    """The fit of every joint between parts named `rod` and `part`."""
    model = J.analyse(b)
    return [j.fit for j in model.joints
            if model.parts[j.rod].name == rod
            and model.parts[j.part].name == part]


class TestFlatParts(unittest.TestCase):
    def test_an_l_beam_pinned_through_its_leg_holds(self):
        b = Build("x")
        with b.step() as s:
            beam = s.add("beam_1x4", (0, 0, 0))
            el = s.add("lbeam_2x3", (0, 0, 0.5))
            s.add("pin_1x1", beam.hole(0, side="up"))
            s.add("pin_1x1", beam.hole(1, side="up"))
        self.assertEqual(_kinds(b), [])
        self.assertEqual(el.hole(0, 2), (0, 2, 0.5))

    def test_a_pin_in_the_l_beams_empty_crook_goes_into_nothing(self):
        b = Build("x")
        with b.step() as s:
            s.add("plate_4x8", (0, 0, 0))
            s.add("lbeam_2x3", (0, 0, 0.375))
            s.add("pin_1x1", (1, 1, 0.25), axis="z")
        self.assertIn("loose", _kinds(b))

    def test_a_shaft_locks_in_the_centre_of_a_lock_beam_only(self):
        b = Build("x")
        with b.step() as s:
            lock = s.add("lockbeam_1x3", (0, 0, 0))
            s.add("shaft_2", lock.hole(1))
            s.add("shaft_2", lock.hole(0))
        self.assertEqual(sorted(_fits(b, "shaft_2", "lockbeam_1x3")),
                         ["free", "locked"])

    def test_the_crank_arm_locks_on_hole_0(self):
        b = Build("x")
        with b.step() as s:
            arm = s.add("crankarm_1x4", (0, 0, 0))
            s.add("shaft_2", arm.hole(0))
        self.assertEqual(_fits(b, "shaft_2", "crankarm_1x4"), ["locked"])

    def test_a_pin_through_an_angle_beams_slanted_leg_is_in_a_hole(self):
        b = Build("x")
        with b.step() as s:
            ang = s.add("anglebeam_3x3_60", (0, 0, 0))
            far = ang.holes[-1]
            s.add("pin_1x1", far + (0, 0, 0.25))
        self.assertNotIn("rod in solid", _kinds(b))

    def test_between_two_holes_of_the_slanted_leg_is_solid(self):
        b = Build("x")
        with b.step() as s:
            ang = s.add("anglebeam_3x3_60", (0, 0, 0))
            a, c = ang.holes[-2], ang.holes[-1]
            s.add("shaft_2", tuple((p + q) / 2 for p, q in zip(a, c)),
                  axis="z")
        self.assertIn("rod in solid", _kinds(b))


class TestRods(unittest.TestCase):
    def test_a_plastic_shaft_drives_a_gear(self):
        b = Build("x")
        with b.step() as s:
            beam = s.add("beam_1x4", (0, 0, 0))
            s.add("plastic_shaft_3", beam.hole(0))
            s.add("gear_12", beam.hole(0) + (0, 0, 0.5))
        self.assertEqual(_fits(b, "plastic_shaft_3", "gear_12"), ["locked"])
        self.assertEqual(_fits(b, "plastic_shaft_3", "beam_1x4"), ["free"])

    def test_a_capped_pin_joins_two_beams_from_underneath(self):
        b = Build("x")
        with b.step() as s:
            low = s.add("beam_1x4", (0, 0, 0))
            s.add("beam_1x4", (0, 0, 0.5))
            s.add("pin_0x2", low.hole(2, side="down"))
        self.assertEqual(_kinds(b), [])

    def test_a_shaft_through_solid_plastic_is_still_caught(self):
        b = Build("x")
        with b.step() as s:
            s.add("lockbeam_1x3", (0, 0, 0))
            s.add("capped_shaft_2", (0.5, 0, 0), axis="z")
        self.assertIn("rod in solid", _kinds(b))


class TestWheels(unittest.TestCase):
    def test_an_omni_wheel_turns_with_its_shaft(self):
        b = Build("x")
        with b.step() as s:
            s.add("beam_2x12", (0, 0, 0), rot=(90, 0, 0))
            s.add("shaft_4", (1, -1.2, 0), axis="y")
            s.add("omni_200", (1, 1.5, 0), axis="y")
        drive = report(b)["drive"]
        names = {p["id"]: p["name"] for p in report(b)["parts"]}
        bodies = [sorted(names[i] for i in body["parts"])
                  for t in drive["trains"] for body in t["bodies"]]
        self.assertIn(["omni_200", "shaft_4"], bodies)


class TestPegs(unittest.TestCase):
    """Corner connectors and the traction link: built-in pegs, each half a
    pin, that push into the next part's holes."""

    def _connector(self, beam_at):
        b = Build("x")
        with b.step() as s:
            c = s.add("connector_2w_1x2", (0, 0, 0))
            s.add("beam_1x4", beam_at)                  # pressed on the pegs
            s.add("beam_1x4", (0, 0.25, 0), rot=(90, 0, 0))
            s.add("pin_1x1", c.hole(0, side="+y"))
            s.add("pin_1x1", c.hole(1, side="+y"))
        return b

    def test_a_beam_pressed_onto_the_pegs_is_joined(self):
        b = self._connector((0, 0, 0.75))
        self.assertEqual(_kinds(b), [])
        model = J.analyse(b)
        self.assertIn("peg", {j.kind for j in model.joints})

    def test_a_peg_into_solid_plastic_is_caught(self):
        b = self._connector((0.5, 0, 0.75))
        problems = [p for p in check(b) if p.kind == "rod in solid"]
        self.assertEqual(len(problems), 1)
        self.assertIn("a peg of connector_2w_1x2", problems[0].message)

    def test_hole_takes_the_parts_own_hole_names(self):
        b = Build("x")
        with b.step() as s:
            c = s.add("connector_2w_1x2_offset", (0, 0, 0))
        # Named (0.5, 0, 0.5) by the part; its centre is mid-plate.
        self.assertEqual(c.hole(0.5, 0, 0.5), (0.5, -0.25, 0.5))

    def test_a_traction_link_pegs_into_a_beam(self):
        b = Build("x")
        with b.step() as s:
            beam = s.add("beam_1x4", (0, 0, 0))
            s.add("tractionlink", beam.hole(1, side="up"))
        self.assertEqual(_kinds(b), [])

    def test_part_info_lists_the_pegs(self):
        from iqdraw.report import part_info
        info = part_info("connector_triple_2x2")
        self.assertEqual(len(info["pegs"]), 6)


class TestEveryFamily(unittest.TestCase):
    def test_every_catalogued_part_can_be_checked_and_inspected(self):
        for fam in catalogue():
            with self.subTest(part=fam["example"]):
                b = Build("x")
                with b.step() as s:
                    s.add("beam_1x4", (0, 0, 0))
                    s.add(fam["example"], (0, 4, 0))
                check(b)
                report(b)


if __name__ == "__main__":
    unittest.main()
