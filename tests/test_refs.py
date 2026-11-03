"""
Placing parts against each other: what `s.add()` hands back.

The point of a Ref is that nobody does stack arithmetic by hand.  The gear
train is the proof - its heights were worked out and written down as
constants, and the same build written with refs has to land on every one.
"""

import unittest

import support  # noqa: F401  (makes the checkout importable)

from iqdraw import Build, Point
from iqdraw.check import check
from iqdraw.spec import SpecError


def _positions(b):
    return [(n, p.tf.pos) for st in b.steps for p, n, *_ in st.items]


class TestHoles(unittest.TestCase):
    def setUp(self):
        self.s = Build("h").step("s")
        self.rail = self.s.add("beam_2x12", (0, 0, 0))

    def test_a_hole_is_its_centre_with_its_axis(self):
        h = self.rail.hole(3, 1)
        self.assertEqual(h, (3.0, 1.0, 0.0))
        self.assertEqual(h.axis, (0.0, 0.0, 1.0))

    def test_side_moves_to_the_face_it_opens_onto(self):
        self.assertEqual(self.rail.hole(3, side="up"), (3.0, 0.0, 0.25))
        self.assertEqual(self.rail.hole(3, side="-z"), (3.0, 0.0, -0.25))

    def test_holes_follow_the_part_round(self):
        cross = self.s.add("beam_1x4", (2, 0, 0.5), rot=(0, 0, 90))
        self.assertEqual(cross.hole(3), (2.0, 3.0, 0.5))
        upright = self.s.add("corner_2x4", (0, 0, 0))
        self.assertEqual([abs(v) for v in upright.hole(0, 0, 2).axis],
                         [1.0, 0.0, 0.0])

    def test_a_missing_hole_lists_the_real_ones(self):
        with self.assertRaises(SpecError) as e:
            self.rail.hole(12)
        self.assertIn("(11, 1, 0)", str(e.exception))

    def test_side_has_to_run_along_the_hole(self):
        with self.assertRaises(SpecError):
            self.rail.hole(0, side="+x")

    def test_points_add_as_vectors(self):
        p = self.rail.hole(1) + (0, 2.2, 0)
        self.assertEqual(p, (1.0, 2.2, 0.0))
        self.assertEqual(p.axis, (0.0, 0.0, 1.0))

    def test_faces(self):
        self.assertEqual((self.rail.top, self.rail.bottom), (0.25, -0.25))
        self.assertEqual(self.rail.face("+y"), 1.5)


class TestPlacing(unittest.TestCase):
    def test_a_rod_at_a_hole_lines_up_with_it(self):
        s = Build("p").step("s")
        upright = s.add("corner_2x4", (0, 0, 0))
        shaft = s.add("shaft_4", upright.hole(0, 0, 3))
        self.assertEqual(shaft.axis, (1.0, 0.0, 0.0))
        self.assertEqual(shaft.pos, (0.0, 0.0, 3.0))

    def test_an_explicit_axis_still_wins(self):
        s = Build("p").step("s")
        rail = s.add("beam_2x12", (0, 0, 0))
        self.assertEqual(s.add("shaft_4", rail.hole(1), axis="y").axis,
                         (0.0, 1.0, 0.0))

    def test_on_sits_on_the_highest_of_several(self):
        s = Build("p").step("s")
        low = s.add("beam_1x4", (0, 0, 0))
        high = s.add("beam_1x4", (0, 2, 0.5))
        deck = s.add("plate_4x8", (0, 0, 0), on=[low, high])
        self.assertEqual(deck.bottom, 0.75)

    def test_on_can_press_sideways(self):
        s = Build("p").step("s")
        rail = s.add("beam_1x8", (0, 0, 0), rot=(90, 0, 0))
        wheel = s.add("wheel_200", rail.hole(1), axis="y",
                      on=rail, side="+y")
        self.assertAlmostEqual(wheel.face("-y"), rail.face("+y"))

    def test_many_returns_a_ref_per_part(self):
        s = Build("p").step("s")
        refs = s.many("pin_1x1", [(0, 0, 0), (1, 0, 0)], axis="z")
        self.assertEqual([r.pos for r in refs], [(0, 0, 0), (1, 0, 0)])

    def test_on_rejects_what_is_not_a_part(self):
        s = Build("p").step("s")
        with self.assertRaises(SpecError):
            s.add("spacer", (0, 0, 0), on="beam")


class TestMeshing(unittest.TestCase):
    def test_spacing_is_teeth_over_24_per_gear(self):
        s = Build("m").step("s")
        g = s.add("gear_12", (0, 0, 0.75), axis="z")
        self.assertEqual(g.meshing("gear_36", "+x"), (2.0, 0.0, 0.75))
        self.assertEqual(g.meshing("gear_60", "-y"), (0.0, -3.0, 0.75))

    def test_only_across_the_face(self):
        s = Build("m").step("s")
        g = s.add("gear_12", (0, 0, 0.75), axis="z")
        with self.assertRaises(SpecError):
            g.meshing("gear_36", "up")


class TestGearTrainWithoutArithmetic(unittest.TestCase):
    def test_refs_land_on_every_hand_worked_height(self):
        b = Build("gt")
        with b.step("beam") as s:
            beam = s.add("beam_2x12", (0, 0, 0))
        with b.step("shafts") as s:
            s.many("shaft_3", [beam.hole(x) for x in (0, 2, 6)])
        with b.step("spacers") as s:
            sp = [s.add("spacer", beam.hole(x), on=beam) for x in (0, 2, 6)]
        with b.step("gears") as s:
            g12 = s.add("gear_12", beam.hole(0), on=sp[0])
            g36 = s.add("gear_36", g12.meshing("gear_36", "+x"), on=sp[1])
            g60 = s.add("gear_60", g36.meshing("gear_60", "+x"), on=sp[2])
        with b.step("collars") as s:
            collar = [s.add("collar", g.pos, on=g) for g in (g12, g36, g60)]
        with b.step("knob") as s:
            s.add("wheel_100", collar[0].pos, on=collar[0])
        self.assertEqual(_positions(b),
                         _positions(support.load_example("gear-train")))
        self.assertEqual(check(b), [])


if __name__ == "__main__":
    unittest.main()
