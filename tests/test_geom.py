"""Geometry core: the arithmetic every drawing is built on."""

import math
import unittest

import support  # noqa: F401  (puts iqdraw on the path)

from iqdraw.geom import (
    IDENTITY, PITCH_MM, Transform, box, centroid, euler, extrude, fade,
    hex_to_rgb, mat_apply, mix_color, polygon_normal, project, rgb_to_hex,
    rot_z, scale_color, vadd, vcross, vdot, vlen, vnorm, vsub,
)


class TestVectors(unittest.TestCase):
    def test_basic_algebra(self):
        self.assertEqual(vadd((1, 2, 3), (4, 5, 6)), (5, 7, 9))
        self.assertEqual(vsub((4, 5, 6), (1, 2, 3)), (3, 3, 3))
        self.assertEqual(vdot((1, 2, 3), (4, 5, 6)), 32)
        self.assertEqual(vcross((1, 0, 0), (0, 1, 0)), (0, 0, 1))
        self.assertAlmostEqual(vlen((3, 4, 0)), 5.0)

    def test_vnorm_survives_a_zero_vector(self):
        # Degenerate facets do occur in tessellated CAD meshes; normalising
        # one must not raise, or a single bad triangle takes down the render.
        self.assertEqual(vnorm((0, 0, 0)), (0.0, 0.0, 0.0))

    def test_polygon_normal_is_unit_and_right_handed(self):
        n = polygon_normal([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)])
        self.assertAlmostEqual(vlen(n), 1.0)
        self.assertAlmostEqual(n[2], 1.0)

    def test_centroid(self):
        self.assertEqual(centroid([(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)]),
                         (1.0, 1.0, 0.0))


class TestTransforms(unittest.TestCase):
    def test_identity_moves_nothing(self):
        tf = Transform(IDENTITY, (0, 0, 0))
        self.assertEqual(tf.point((1, 2, 3)), (1, 2, 3))

    def test_translation_then_rotation_composes_in_that_order(self):
        inner = Transform(IDENTITY, (1, 0, 0))
        outer = Transform(rot_z(90), (0, 0, 0))
        got = inner.then(outer).point((0, 0, 0))
        # the point rides the translation, then the whole thing spins
        self.assertAlmostEqual(got[0], 0.0)
        self.assertAlmostEqual(got[1], 1.0)

    def test_euler_applies_x_then_y_then_z(self):
        # +z tips onto -y under the X turn, then swings onto +x under the Z
        # turn.  Do those in the other order and you land somewhere else,
        # which is the whole reason the order is documented.
        got = mat_apply(euler(90, 0, 90), (0, 0, 1))
        for a, b in zip(got, (1.0, 0.0, 0.0)):
            self.assertAlmostEqual(a, b, places=9)
        stepwise = mat_apply(rot_z(90), mat_apply(euler(90, 0, 0), (0, 0, 1)))
        for a, b in zip(got, stepwise):
            self.assertAlmostEqual(a, b, places=9)

    def test_rotation_preserves_length(self):
        v = (0.3, -1.7, 2.2)
        self.assertAlmostEqual(vlen(mat_apply(euler(17, 43, -61), v)), vlen(v))


class TestProjection(unittest.TestCase):
    def test_up_is_up_on_screen(self):
        # +z must project to a smaller screen y, or the whole drawing is
        # upside down and every shadow lands on the wrong side.
        self.assertLess(project((0, 0, 1))[1], project((0, 0, 0))[1])

    def test_x_and_y_separate_horizontally(self):
        self.assertGreater(project((1, 0, 0))[0], 0)
        self.assertLess(project((0, 1, 0))[0], 0)

    def test_isometric_axes_are_equally_foreshortened(self):
        origin = project((0, 0, 0))
        lengths = [math.dist(origin, project(axis))
                   for axis in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]
        for length in lengths[1:]:
            self.assertAlmostEqual(length, lengths[0], places=9)


class TestColour(unittest.TestCase):
    def test_hex_roundtrip(self):
        self.assertEqual(rgb_to_hex(hex_to_rgb("#087fc7")), "#087fc7")

    def test_short_hex_expands(self):
        self.assertEqual(hex_to_rgb("#abc"), hex_to_rgb("#aabbcc"))

    def test_scale_clamps_instead_of_wrapping(self):
        # A shade factor above 1 is normal on a lit face; wrapping would turn
        # a highlight black.
        self.assertEqual(scale_color("#ffffff", 4.0), "#ffffff")
        self.assertEqual(scale_color("#ffffff", -1.0), "#000000")

    def test_mix_endpoints(self):
        self.assertEqual(mix_color("#000000", "#ffffff", 0.0), "#000000")
        self.assertEqual(mix_color("#000000", "#ffffff", 1.0), "#ffffff")

    def test_fade_moves_toward_grey(self):
        faded = fade("#000000", 1.0)
        self.assertEqual(faded, "#c9ccd2")


class TestSolids(unittest.TestCase):
    def test_box_is_subdivided_for_the_depth_sort(self):
        # One big facet sorts by its centre and paints over parts standing on
        # its far end, so a long box has to come back as many cells.
        small = box(0, 0, 0, 1, 1, 1, "#888888")
        large = box(0, 0, 0, 8, 8, 1, "#888888")
        self.assertGreater(len(large), len(small) * 4)

    def test_extrude_emits_facets_and_edges(self):
        prims = extrude([(0, 0), (1, 0), (1, 1), (0, 1)], 0.0, 1.0, "#888888")
        self.assertTrue(prims)
        kinds = {type(p).__name__ for p in prims}
        self.assertIn("Facet", kinds)
        self.assertIn("Edge", kinds)

    def test_pitch_is_the_documented_vex_hole_spacing(self):
        self.assertAlmostEqual(PITCH_MM, 12.7)


if __name__ == "__main__":
    unittest.main()
