"""
The SVG emitter.

Most of these guard the size optimisation: interning colours as CSS classes
and merging adjacent same-styled geometry are only safe while paint order and
every class reference survive intact.
"""

import re
import unittest
import xml.etree.ElementTree as ET

import support  # noqa: F401

from iqdraw import Build
from iqdraw.instructions import booklet

from iqdraw import Build
from iqdraw.render import (
    IDENTITY, PRECISION, Placement, RenderOpts, Styles, _class_name, _draw, _emit, _n, _path, bounds, render, render_part_icon, view_rotation, visible, world_prims,
)
from iqdraw.geom import Transform
from iqdraw.parts import get


def _scene():
    b = Build("x")
    with b.step("s") as s:
        s.add("beam_1x4", (0, 0, 0))
        s.add("pin_1x1", (1, 0, 0.25), axis="z")
    return b


def _classes_used(svg):
    return set(re.findall(r'class="([^"]+)"', svg))


def _classes_defined(svg):
    block = re.search(r"<style>(.*?)</style>", svg, re.S)
    return set(re.findall(r"\.([\w-]+)\{", block.group(1))) if block else set()


class TestWellFormed(unittest.TestCase):
    def test_output_parses_as_xml(self):
        ET.fromstring(_scene().hero_svg())

    def test_no_nan_or_infinity_reaches_the_page(self):
        svg = _scene().hero_svg()
        self.assertNotIn("nan", svg.lower())
        self.assertNotIn("inf", svg.lower())

    def test_viewbox_is_positive(self):
        svg = _scene().hero_svg()
        _, _, w, h = svg.split('viewBox="')[1].split('"')[0].split()
        self.assertGreater(float(w), 0)
        self.assertGreater(float(h), 0)


class TestStyleInterning(unittest.TestCase):
    def test_every_class_used_is_defined(self):
        svg = _scene().hero_svg()
        self.assertTrue(_classes_used(svg))
        self.assertLessEqual(_classes_used(svg), _classes_defined(svg))

    def test_class_names_are_short_and_sequential(self):
        self.assertEqual([_class_name(i) for i in range(3)], ["a", "b", "c"])
        self.assertEqual(_class_name(25), "z")
        self.assertEqual(_class_name(26), "aa")

    def test_identical_paint_gets_one_class(self):
        styles = Styles()
        self.assertEqual(styles.name("fill:#fff"), styles.name("fill:#fff"))
        self.assertNotEqual(styles.name("fill:#fff"), styles.name("fill:#000"))

    def test_a_standalone_drawing_namespaces_its_classes(self):
        # Two of these can end up pasted into one HTML page, where class names
        # are document-wide; without a namespace they would fight over `.a`.
        one = _scene().hero_svg()
        b = Build("y")
        b.step("s").add("gear_36", (0, 0, 0), axis="z")
        two = b.hero_svg()
        self.assertTrue(_classes_used(one).isdisjoint(_classes_used(two)))

    def test_the_namespace_is_stable_for_the_same_drawing(self):
        self.assertEqual(_classes_used(_scene().hero_svg()),
                         _classes_used(_scene().hero_svg()))

    def test_a_shared_stylesheet_emits_no_style_block(self):
        styles = Styles()
        svg = _scene().hero_svg(styles=styles)
        self.assertNotIn("<style>", svg)
        self.assertTrue(styles.css())

    def test_a_shared_stylesheet_covers_every_drawing_it_served(self):
        styles = Styles()
        b = _scene()
        svgs = [svg for _, _, svg in b.step_svgs(styles=styles)]
        svgs.append(b.hero_svg(styles=styles))
        svgs.append(render_part_icon("gear_36", styles=styles))
        defined = set(re.findall(r"\.([\w-]+)\{", styles.css()))
        for svg in svgs:
            self.assertLessEqual(_classes_used(svg), defined)


class TestMerging(unittest.TestCase):
    def _ops(self, placements):
        opts = RenderOpts()
        prims = visible(world_prims(placements, opts))
        styles = Styles()
        ops = []
        for p in prims:
            _draw(p, opts.scale, 0.0, 0.0, 1.0, styles, ops)
        return ops

    def test_merging_preserves_paint_order(self):
        # The depth sort is the only thing standing between this and parts
        # painting over each other, so a merge must never reorder anything.
        placements = [Placement(get("beam_1x4"), Transform(IDENTITY, (0, 0, 0))),
                      Placement(get("pin_1x1"), Transform(IDENTITY, (1, 0, 0.25)))]
        ops = self._ops(placements)
        merged = _emit(ops, "")
        flat = []
        for element in merged:
            cls = re.search(r'class="([^"]*)"', element)
            for sub in re.findall(r"M[^MZ]*Z?", 
                                  re.search(r'd="([^"]*)"', element).group(1)
                                  if 'd="' in element else ""):
                flat.append((cls.group(1), sub))
        self.assertEqual([c for c, _ in flat],
                         [c for c, kind, _ in ops if kind == "path"])

    def test_merging_loses_no_geometry(self):
        placements = [Placement(get("beam_1x4"), Transform(IDENTITY, (0, 0, 0)))]
        ops = self._ops(placements)
        merged = "".join(_emit(ops, ""))
        self.assertEqual(merged.count("M"),
                         sum(op[2].count("M") for op in ops))

    def test_a_merged_run_shares_one_element(self):
        ops = [("a", "path", "M0,0 1,1Z"), ("a", "path", "M2,2 3,3Z"),
               ("b", "path", "M4,4 5,5Z")]
        self.assertEqual(len(_emit(ops, "")), 2)

    def test_raw_ops_pass_through_untouched(self):
        ops = [("a", "path", "M0,0Z"), (None, "raw", "<rect/>"),
               ("a", "path", "M1,1Z")]
        out = _emit(ops, "")
        self.assertEqual(len(out), 3)
        self.assertIn("<rect/>", out)

    def test_edges_never_pick_up_a_fill(self):
        # A <line> has no fill; the <path> that replaced it defaults to black
        # and would flood the drawing without this.
        svg = _scene().hero_svg()
        block = re.search(r"<style>(.*?)</style>", svg, re.S).group(1)
        for decl in re.findall(r"\.[\w-]+\{([^}]*)\}", block):
            if "stroke-width" in decl and "fill:" in decl:
                self.assertIn("fill:none", decl)


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


class TestPathEncoding(unittest.TestCase):
    """
    Coordinates are most of a booklet, so how they are spelled is most of its
    size.  All three of these are lossless - the geometry has to come back out
    exactly, or the saving is not a saving.
    """

    def _points(self, d):
        """Walk `M x,y l dx,dy...` back to the absolute points it describes."""
        nums = [float(n) for n in re.findall(r"-?\d*\.?\d+", d)]
        pts = [(nums[0], nums[1])]
        for i in range(2, len(nums), 2):
            pts.append((round(pts[-1][0] + nums[i], 6),
                        round(pts[-1][1] + nums[i + 1], 6)))
        return pts

    def test_a_polygon_round_trips(self):
        pts = [(10.0, 20.0), (13.2, 24.1), (11.0, 26.0), (9.0, 22.5)]
        self.assertEqual(self._points(_path(pts, True)), pts)

    def test_a_segment_round_trips(self):
        pts = [(10.0, -20.0), (13.2, -24.1)]
        self.assertEqual(self._points(_path(pts, False)), pts)

    def test_a_closed_path_says_so(self):
        self.assertTrue(_path([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)], True)
                        .endswith("z"))
        self.assertFalse(_path([(0.0, 0.0), (1.0, 0.0)], False).endswith("z"))

    def test_deltas_do_not_accumulate_drift(self):
        # Rounding each absolute point before subtracting is what keeps a long
        # outline from walking away from where it belongs.
        pts = [(0.0, 0.0)] + [(i * 0.04, i * 0.04) for i in range(1, 60)]
        rounded = [(round(x, PRECISION), round(y, PRECISION)) for x, y in pts]
        self.assertEqual(self._points(_path(rounded, False)), rounded)

    def test_a_minus_sign_separates_without_a_space(self):
        d = _path([(0.0, 0.0), (-5.0, -5.0)], False)
        self.assertNotIn(" -", d)
        self.assertNotIn(",-", d)

    def test_positive_deltas_keep_their_separators(self):
        d = _path([(0.0, 0.0), (5.0, 5.0), (9.0, 9.0)], False)
        self.assertEqual(self._points(d),
                         [(0.0, 0.0), (5.0, 5.0), (9.0, 9.0)])

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
