"""
The build checks.

Two halves, and the quiet half matters more: a checker that reports a correct
build gets switched off, and then it catches nothing at all.
"""

import unittest

import support

from iqdraw import Build
from iqdraw.check import check


def _problems(build):
    """
    Everything but `loose`.  Most builds here are sketches of one mistake -
    gears with no shaft, beams with no pins - and a finished build would have
    those; `loose` has its own tests below.
    """
    return [p for p in check(build) if p.kind != "loose"]


def _kinds(build):
    return sorted(p.kind for p in _problems(build))


class TestQuietOnValidBuilds(unittest.TestCase):
    def test_the_shipped_examples_are_clean(self):
        for name in support.example_names():
            with self.subTest(build=name):
                self.assertEqual(check(support.load_example(name)), [])

    def test_an_empty_build_is_fine(self):
        self.assertEqual(check(Build("nothing")), [])

    def test_a_single_part_is_not_stranded(self):
        b = Build("one")
        b.step("s").add("beam_2x12", (0, 0, 0))
        self.assertEqual(check(b), [])

    def test_stacked_beams_touching_face_to_face_are_fine(self):
        b = Build("stack")
        with b.step("s") as s:
            s.add("beam_2x12", (0, 0, 0))
            s.add("beam_1x7", (1, 0, 0.5), rot=(0, 0, 90))
        self.assertEqual(_kinds(b), [])

    def test_a_compound_gear_pair_on_one_shaft_is_fine(self):
        b = Build("compound")
        with b.step("s") as s:
            s.add("beam_2x12", (0, 0, 0))
            s.add("shaft_4", (0, 0, 0), axis="z")
            s.add("gear_12", (0, 0, 0.6), axis="z")
            s.add("gear_36", (0, 0, 1.2), axis="z")
        self.assertEqual(_kinds(b), [])

    def test_an_idler_row_does_not_flag_the_outer_pair(self):
        # Three gears in a line: the ends are further apart than their own
        # pitch radii and that is exactly right, because they never touch.
        b = Build("idler")
        with b.step("s") as s:
            s.add("beam_2x12", (0, 0, 0))
            for x in (0, 1, 2):
                s.add("gear_12", (x, 0, 0.75), axis="z")
        self.assertEqual(_kinds(b), [])

    def test_gears_far_apart_are_two_gears_not_a_bad_pair(self):
        b = Build("separate")
        with b.step("s") as s:
            s.add("beam_2x12", (0, 0, 0))
            s.add("gear_12", (0, 0, 0.75), axis="z")
            s.add("gear_12", (8, 0, 0.75), axis="z")
        self.assertEqual(_kinds(b), [])


class TestCatchesRealMistakes(unittest.TestCase):
    def test_the_same_part_placed_twice(self):
        b = Build("dup")
        with b.step("s") as s:
            s.add("beam_2x12", (0, 0, 0))
            s.add("beam_2x12", (0, 0, 0))
        self.assertEqual(_kinds(b), ["duplicate"])

    def test_two_beams_in_the_same_space(self):
        b = Build("clash")
        with b.step("s") as s:
            s.add("beam_2x12", (0, 0, 0))
            s.add("beam_1x7", (2, 0, 0))
        self.assertEqual(_kinds(b), ["overlap"])

    def test_gears_a_hole_too_far_apart(self):
        b = Build("loose")
        with b.step("s") as s:
            s.add("beam_2x12", (0, 0, 0))
            s.add("gear_12", (0, 0, 0.75), axis="z")
            s.add("gear_36", (3, 0, 0.75), axis="z")
        self.assertEqual(_kinds(b), ["gear mesh"])

    def test_gears_jammed_into_each_other(self):
        b = Build("tight")
        with b.step("s") as s:
            s.add("beam_2x12", (0, 0, 0))
            s.add("gear_36", (0, 0, 0.75), axis="z")
            s.add("gear_36", (2, 0, 0.75), axis="z")
        self.assertIn("gear mesh", _kinds(b))

    def test_a_part_typed_off_the_edge_of_the_model(self):
        b = Build("adrift")
        with b.step("s") as s:
            s.add("beam_2x12", (0, 0, 0))
            s.add("beam_1x4", (30, 0, 0))
        self.assertEqual(_kinds(b), ["stranded"])

    def test_problems_name_the_step_they_are_in(self):
        b = Build("late")
        b.step("fine").add("beam_2x12", (0, 0, 0))
        b.step("wrong").add("beam_1x4", (40, 0, 0))
        self.assertEqual([p.step for p in _problems(b)], [2])

    def test_a_problem_reads_as_a_sentence(self):
        b = Build("adrift")
        with b.step("s") as s:
            s.add("beam_2x12", (0, 0, 0))
            s.add("beam_1x4", (30, 0, 0))
        text = str(_problems(b)[0])
        self.assertIn("step 1", text)
        self.assertIn("beam_1x4", text)



class TestJoints(unittest.TestCase):
    """The joint rules, which read holes and rods rather than boxes."""

    def _base(self):
        b = Build("j")
        return b, b.step("s")

    def test_a_pin_joining_two_beams_is_fine(self):
        b, s = self._base()
        s.add("beam_2x12", (0, 0, 0))
        s.add("beam_1x4", (0, 0, 0.5))
        s.add("pin_1x1", (0, 0, 0.25), axis="z")
        self.assertEqual(check(b), [])

    def test_a_shaft_through_holes_carrying_a_stack_is_fine(self):
        b, s = self._base()
        s.add("beam_2x12", (0, 0, 0))
        s.add("shaft_3", (0, 0, 0), axis="z")
        s.add("spacer", (0, 0, 0.375), axis="z")
        s.add("gear_12", (0, 0, 0.75), axis="z")
        s.add("collar", (0, 0, 1.18), axis="z")
        self.assertEqual(check(b), [])

    def test_a_shaft_half_a_hole_out_runs_through_solid(self):
        b, s = self._base()
        s.add("beam_2x12", (0, 0, 0))
        s.add("shaft_3", (2.5, 0, 0), axis="z")
        problems = check(b)
        self.assertEqual([p.kind for p in problems], ["rod in solid"])
        self.assertIn("nearest hole", problems[0].message)

    def test_a_shaft_through_the_edge_of_a_flat_beam(self):
        b, s = self._base()
        s.add("beam_2x12", (0, 0, 0))
        s.add("shaft_4", (1, 0, 0), axis="y")
        self.assertEqual([p.kind for p in check(b)], ["rod in solid"])

    def test_a_pin_in_only_one_part_holds_nothing(self):
        b, s = self._base()
        s.add("beam_2x12", (0, 0, 0))
        s.add("beam_1x4", (0, 0, 0.5))
        s.add("pin_1x1", (0, 0, 0.25), axis="z")
        s.add("pin_1x1", (5, 0, 0.25), axis="z")
        problems = check(b)
        self.assertEqual([p.kind for p in problems], ["loose"])
        self.assertIn("pin_1x1 at (5, 0, 0.25)", problems[0].message)

    def test_a_beam_nothing_pins_on(self):
        b, s = self._base()
        s.add("beam_2x12", (0, 0, 0))
        s.add("beam_1x4", (0, 0, 0.5))
        self.assertEqual([p.kind for p in check(b)], ["loose", "loose"])

    def test_a_gear_overlapping_its_spacer(self):
        b, s = self._base()
        s.add("beam_2x12", (0, 0, 0))
        s.add("shaft_3", (0, 0, 0), axis="z")
        s.add("spacer", (0, 0, 0.375), axis="z")
        s.add("gear_12", (0, 0, 0.6), axis="z")
        self.assertEqual([p.kind for p in check(b)], ["collision"])

    def test_a_wheel_rubbing_the_rail(self):
        b, s = self._base()
        s.add("beam_1x8", (0, 0, 0), rot=(90, 0, 0))   # on edge: holes face y
        s.add("shaft_4", (1, 0, 0), axis="y")
        s.add("wheel_200", (1, 0.5, 0), axis="y")
        s.add("collar", (1, 1.6, 0), axis="y")
        self.assertIn("collision", [p.kind for p in check(b)])

    def test_a_wheel_clear_of_the_rail_is_fine(self):
        b, s = self._base()
        s.add("beam_1x8", (0, 0, 0), rot=(90, 0, 0))
        s.add("shaft_4", (1, 0, 0), axis="y")
        s.add("wheel_200", (1, 0.95, 0), axis="y")
        s.add("collar", (1, 1.81, 0), axis="y")
        self.assertEqual(check(b), [])


if __name__ == "__main__":
    unittest.main()
