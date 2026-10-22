"""
The renderer: a depth-buffered PNG inside an SVG frame that carries the
arrows and the accessible name.
"""

import base64
import re
import struct
import unittest
import xml.etree.ElementTree as ET

import support  # noqa: F401

from iqdraw import Build
from iqdraw.instructions import booklet

from iqdraw import Build
from iqdraw.render import (
    IDENTITY, Placement, RenderOpts, Styles, _class_name, _n, bounds, render, render_part_icon, view_rotation, visible, world_prims,
)
from iqdraw.geom import Transform
from iqdraw.parts import get


def _scene():
    b = Build("x")
    with b.step("s") as s:
        s.add("beam_1x4", (0, 0, 0))
        s.add("pin_1x1", (1, 0, 0.25), axis="z")
    return b


def _png(svg):
    return base64.b64decode(svg.split("base64,")[1].split('"')[0])


class TestWellFormed(unittest.TestCase):
    def test_output_parses_as_xml(self):
        ET.fromstring(_scene().hero_svg())

    def test_no_nan_or_infinity_reaches_the_page(self):
        # The image's base64 can spell anything, so only the markup is checked.
        svg = re.sub(r"base64,[^\"]*", "", _scene().hero_svg())
        self.assertNotIn("nan", svg.lower())
        self.assertNotIn("inf", svg.lower())

    def test_viewbox_is_positive(self):
        svg = _scene().hero_svg()
        _, _, w, h = svg.split('viewBox="')[1].split('"')[0].split()
        self.assertGreater(float(w), 0)
        self.assertGreater(float(h), 0)


class TestStyleInterning(unittest.TestCase):
    def test_class_names_are_short_and_sequential(self):
        self.assertEqual([_class_name(i) for i in range(3)], ["a", "b", "c"])
        self.assertEqual(_class_name(25), "z")
        self.assertEqual(_class_name(26), "aa")

    def test_identical_paint_gets_one_class(self):
        styles = Styles()
        self.assertEqual(styles.name("fill:#fff"), styles.name("fill:#fff"))
        self.assertNotEqual(styles.name("fill:#fff"), styles.name("fill:#000"))

class TestAccessibility(unittest.TestCase):
    def test_a_titled_drawing_announces_itself(self):
        svg = render([Placement(get("beam_1x4"), Transform())],
                     RenderOpts(), title="A 1x4 beam")
        self.assertIn('role="img"', svg)
        self.assertIn('aria-label="A 1x4 beam"', svg)
        self.assertIn("<title>A 1x4 beam</title>", svg)

    def test_an_untitled_drawing_is_decorative(self):
        svg = render([Placement(get("beam_1x4"), Transform())], RenderOpts())
        self.assertIn('aria-hidden="true"', svg)
        self.assertNotIn("<title>", svg)

    def test_the_label_is_xml_escaped(self):
        svg = render([Placement(get("beam_1x4"), Transform())],
                     RenderOpts(), title='a <b> & "c"')
        ET.fromstring(svg)
        self.assertIn("&lt;b&gt;", svg)


class TestIcons(unittest.TestCase):
    def test_a_small_part_is_not_a_speck_beside_a_large_one(self):
        # The callout exists so a student recognises the part, not so they can
        # compare part sizes, so icons are fitted to the slot.
        beam = render_part_icon("beam_2x12")
        collar = render_part_icon("collar")
        self.assertGreater(_svg_width(collar), _svg_width(beam) * 0.3)

    def test_a_bigger_part_still_gets_a_bigger_icon(self):
        self.assertGreater(_svg_width(render_part_icon("beam_2x12")),
                           _svg_width(render_part_icon("beam_1x4")))


def _svg_width(svg):
    return float(svg.split('width="')[1].split('"')[0])


class TestCamera(unittest.TestCase):
    def test_spinning_the_view_changes_the_drawing(self):
        placements = [Placement(get("beam_2x12"), Transform())]
        opts = RenderOpts()
        a = bounds(visible(world_prims(placements, opts, view_rotation(0))), opts)
        b = bounds(visible(world_prims(placements, opts, view_rotation(90))), opts)
        self.assertNotEqual(a, b)

    def test_back_faces_are_culled(self):
        placements = [Placement(get("beam_2x12"), Transform())]
        opts = RenderOpts()
        raw = world_prims(placements, opts)
        self.assertLess(len(visible(raw)), len(raw) * 1.5)


class TestRaster(unittest.TestCase):
    def test_the_drawing_is_an_embedded_png(self):
        png = _png(_scene().hero_svg())
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")

    def test_the_png_is_sharp_enough_for_print(self):
        # Two image pixels per SVG unit, so it holds up on HiDPI screens and paper.
        svg = _scene().hero_svg()
        w = float(svg.split('width="')[1].split('"')[0])
        png_w, = struct.unpack(">I", _png(svg)[16:20])
        self.assertGreaterEqual(png_w, 2 * int(w))

    def test_zero_has_one_spelling(self):
        for v in (0.0, -0.0, -0.001, 0.001):
            self.assertEqual(_n(v), "0")


class TestOpeningSpeed(unittest.TestCase):
    def test_steps_are_skipped_until_scrolled_to(self):
        b = Build("x")
        b.step("one").add("beam_1x4", (0, 0, 0))
        html = booklet(b, hero=False)
        self.assertIn("content-visibility:auto", html)
        self.assertIn("contain-intrinsic-size", html)

    def test_printing_turns_that_back_off(self):
        # Every step has to be laid out to reach paper.
        b = Build("x")
        b.step("one").add("beam_1x4", (0, 0, 0))
        html = booklet(b, hero=False)
        after_print = html[html.index("@media print"):]
        self.assertIn("content-visibility:visible", after_print)


if __name__ == "__main__":
    unittest.main()
