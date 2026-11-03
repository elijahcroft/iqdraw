"""
Views and contact sheets - the pictures for checking a spec, not for the
reader.
"""

import unittest

import support  # noqa: F401  (makes the checkout importable)

from iqdraw import Build
from iqdraw.geom import det, mat_apply, project
from iqdraw.views import VIEWS, look, sheet_svg, view_svg


def _build():
    b = Build("Views")
    with b.step("Lay the beam down.") as s:
        beam = s.add("beam_1x4", (0, 0, 0))
    with b.step("Pin a second beam on top.") as s:
        s.add("pin_1x1", beam.hole(1, side="up"))
        s.add("beam_1x4", (0, 0, 0), on=beam)
    return b


class TestLook(unittest.TestCase):
    def test_it_is_a_rotation_with_the_camera_on_the_named_side(self):
        for name, (toward, up, _) in VIEWS.items():
            if toward is None:
                continue
            with self.subTest(view=name):
                r = look(toward, up)
                self.assertAlmostEqual(det(r), 1.0)
                # The camera sits on (1, 1, 1); `toward` has to land there.
                for v in mat_apply(r, toward):
                    self.assertAlmostEqual(v, 3 ** -0.5)

    def _screen(self, name, axis):
        toward, up, _ = VIEWS[name]
        return project(mat_apply(look(toward, up), axis))

    def test_the_top_view_reads_like_a_map(self):
        # +x to the right, +y up the page - as seen from above, not a mirror.
        x, y = self._screen("top", (1, 0, 0)), self._screen("top", (0, 1, 0))
        self.assertGreater(x[0], 0.5)
        self.assertLess(y[1], -0.5)

    def test_side_views_see_what_a_camera_on_that_side_sees(self):
        # From -y with +z up, +x is on the right; from -x, +y is on the left.
        self.assertGreater(self._screen("yminus", (1, 0, 0))[0], 0.5)
        self.assertLess(self._screen("xminus", (0, 1, 0))[0], -0.5)


class TestViews(unittest.TestCase):
    def test_every_view_draws_with_a_key(self):
        b = _build()
        for name in VIEWS:
            with self.subTest(view=name):
                svg = view_svg(b, name)
                self.assertTrue(svg.startswith("<svg"))
                self.assertIn("+z", svg)

    def test_flat_views_number_the_holes(self):
        svg = view_svg(_build(), "top")
        self.assertIn("x (holes)", svg)
        self.assertIn(">3</text>", svg)          # the beam's last hole

    def test_the_corner_view_has_no_rulers(self):
        self.assertNotIn("(holes)", view_svg(_build(), "iso"))

    def test_an_unknown_view_names_the_real_ones(self):
        with self.assertRaises(ValueError) as e:
            view_svg(_build(), "side")
        self.assertIn("xminus", str(e.exception))


class TestSheet(unittest.TestCase):
    def test_it_holds_every_step_and_four_views(self):
        svg = sheet_svg(_build())
        self.assertIn("Step 1 of 2", svg)
        self.assertIn("Step 2 of 2", svg)
        for name in ("top", "xminus", "yminus", "iso"):
            self.assertIn(f"View: {name}", svg)


if __name__ == "__main__":
    unittest.main()
