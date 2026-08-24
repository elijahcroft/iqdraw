"""
The build checks.

Two halves, and the quiet half matters more: a checker that reports a correct
build gets switched off, and then it catches nothing at all.
"""

import unittest

import support

from iqdraw import Build
from iqdraw.check import check


def _kinds(build):
    return sorted(p.kind for p in check(build))


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
        self.assertEqual(check(b), [])

    def test_a_compound_gear_pair_on_one_shaft_is_fine(self):
        b = Build("compound")
        with b.step("s") as s:
            s.add("beam_2x12", (0, 0, 0))
            s.add("shaft_4", (0, 0, 0), axis="z")
            s.add("gear_12", (0, 0, 0.6), axis="z")
            s.add("gear_36", (0, 0, 1.2), axis="z")
        self.assertEqual(check(b), [])

    def test_an_idler_row_does_not_flag_the_outer_pair(self):
        # Three gears in a line: the ends are further apart than their own
        # pitch radii and that is exactly right, because they never touch.
        b = Build("idler")
        with b.step("s") as s:
            s.add("beam_2x12", (0, 0, 0))
            for x in (0, 1, 2):
                s.add("gear_12", (x, 0, 0.75), axis="z")
        self.assertEqual(check(b), [])

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
        self.assertEqual([p.step for p in check(b)], [2])

    def test_a_problem_reads_as_a_sentence(self):
        b = Build("adrift")
        with b.step("s") as s:
            s.add("beam_2x12", (0, 0, 0))
            s.add("beam_1x4", (30, 0, 0))
        text = str(check(b)[0])
        self.assertIn("step 1", text)
        self.assertIn("beam_1x4", text)


if __name__ == "__main__":
    unittest.main()
