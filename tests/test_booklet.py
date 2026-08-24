"""
The printable booklet: structure, accessibility, and the shipped examples.

Parsed as real HTML rather than pattern-matched where it matters, so a broken
document fails here instead of in a classroom.
"""

import re
import unittest
from html.parser import HTMLParser

import support

from iqdraw import Build, booklet, parts


def _sample(done="both gears turn together"):
    b = Build("Sample Build", subtitle="unit 1", intro="a short intro",
              done=done)
    with b.step("Lay the beam down.") as s:
        s.add("beam_2x12", (0, 0, 0))
    with b.step("Pin it.", caption="press until it clicks") as s:
        s.many("pin_1x1", [(0, 0, 0.25), (3, 0, 0.25)], axis="z")
    with b.step("Check it holds."):
        pass
    return b


class _Structure(HTMLParser):
    """Collects the tag structure and flags anything left unclosed."""

    VOID = {"meta", "br", "hr", "img", "input", "link"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.tags = []
        self.headings = []
        self.mismatched = []
        self._heading = None

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag not in self.VOID:
            self.stack.append(tag)
        if re.fullmatch(r"h[1-6]", tag):
            self._heading = (tag, "")

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.mismatched.append((tag, list(self.stack[-3:])))
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
            return
        self.stack.pop()
        if self._heading and self._heading[0] == tag:
            self.headings.append(self._heading)
            self._heading = None

    def handle_data(self, data):
        if self._heading:
            self._heading = (self._heading[0], self._heading[1] + data)


def _parse(html):
    p = _Structure()
    p.feed(html)
    return p


class TestStructure(unittest.TestCase):
    def setUp(self):
        self.html = booklet(_sample())
        self.doc = _parse(self.html)

    def test_every_tag_is_closed(self):
        self.assertEqual(self.doc.mismatched, [])
        self.assertEqual(self.doc.stack, [])

    def test_it_is_a_standalone_document(self):
        self.assertTrue(self.html.startswith("<!doctype html>"))
        self.assertIn('<html lang="en">', self.html)
        self.assertIn("<title>Sample Build</title>", self.html)

    def test_nothing_is_fetched_from_the_network(self):
        # A booklet gets opened on a school laptop with no internet and
        # printed; anything external is a blank page waiting to happen.
        for tag, attrs in self.doc.tags:
            for key in ("src", "href"):
                if key in attrs:
                    self.assertNotRegex(attrs[key], r"^(https?:)?//")

    def test_steps_are_an_ordered_list(self):
        self.assertIn('<ol class="steps">', self.html)
        self.assertEqual(self.html.count('<li class="step"'), 3)

    def test_heading_levels_never_skip(self):
        levels = [int(t[1]) for t, _ in self.doc.headings]
        self.assertEqual(levels[0], 1)
        for prev, cur in zip(levels, levels[1:]):
            self.assertLessEqual(cur - prev, 1)

    def test_each_step_is_anchored(self):
        for n in (1, 2, 3):
            self.assertIn(f'id="step-{n}"', self.html)


class TestOrientation(unittest.TestCase):
    def setUp(self):
        self.html = booklet(_sample())

    def test_the_cover_states_the_shape_of_the_job(self):
        self.assertIn("3 steps", self.html)
        self.assertIn("3 parts", self.html)

    def test_the_done_condition_is_on_the_cover(self):
        self.assertIn("both gears turn together", self.html)

    def test_no_done_line_when_none_was_given(self):
        self.assertNotIn("Finished when", booklet(_sample(done="")))

    def test_every_step_says_where_it_is_in_the_run(self):
        for n in (1, 2, 3):
            self.assertIn(f"Step {n} <span class=\"of\">of 3</span>", self.html)

    def test_every_step_has_something_to_tick(self):
        self.assertEqual(self.html.count('type="checkbox"'), 3)


class TestAccessibility(unittest.TestCase):
    def setUp(self):
        self.html = booklet(_sample())
        self.doc = _parse(self.html)

    def test_every_drawing_is_labelled_or_marked_decorative(self):
        for tag, attrs in self.doc.tags:
            if tag == "svg":
                self.assertTrue(
                    attrs.get("aria-label") or attrs.get("aria-hidden"),
                    "an svg is neither labelled nor hidden")

    def test_step_drawings_describe_what_was_added(self):
        labels = [a["aria-label"] for t, a in self.doc.tags
                  if t == "svg" and "aria-label" in a]
        step_labels = [l for l in labels if l.startswith("Step")]
        self.assertEqual(len(step_labels), 3)
        self.assertIn("Connector Pin", step_labels[1])

    def test_a_step_that_adds_nothing_says_so(self):
        labels = [a["aria-label"] for t, a in self.doc.tags
                  if t == "svg" and a.get("aria-label", "").startswith("Step 3")]
        self.assertIn("nothing added", labels[0])

    def test_part_icons_are_decorative_beside_their_own_names(self):
        # The row already says "2x Connector Pin"; an icon announced as an
        # image would make a screen reader read every row twice.
        icons = re.findall(r'<span class="icon">(<svg[^>]*)', self.html)
        self.assertTrue(icons)
        for icon in icons:
            self.assertIn('aria-hidden="true"', icon)

    def test_quantities_are_readable_without_the_visual_column(self):
        self.assertIn('<span class="vh">Quantity </span>', self.html)

    def test_the_checkbox_has_a_label(self):
        self.assertIn("Mark step 1 done", self.html)

    def test_it_offers_a_dark_theme_and_a_print_theme(self):
        self.assertIn("prefers-color-scheme:dark", self.html)
        self.assertIn("@media print", self.html)

    def test_the_visually_hidden_helper_is_defined(self):
        self.assertIn(".vh{", self.html)


class TestSharedStylesheet(unittest.TestCase):
    def test_one_stylesheet_serves_the_whole_document(self):
        html = booklet(_sample())
        used = set(re.findall(r'class="([a-z]+)"', html))
        defined = set(re.findall(r"\.([a-z]+)\{", html))
        self.assertTrue(used)
        self.assertLessEqual(used - {"steps", "step"}, defined | {"steps"})

    def test_sharing_beats_repeating(self):
        # Each drawing carrying its own <style> is the thing this replaced.
        self.assertEqual(booklet(_sample()).count("<style>"), 2)


class TestExamples(unittest.TestCase):
    """
    The shipped builds, end to end.

    Drawn at the lighter detail level: this is checking that a real spec
    survives the whole pipeline, and the CAD meshes are exercised directly in
    test_parts without costing several seconds a render.
    """

    @classmethod
    def setUpClass(cls):
        parts.set_detail("simple")

    @classmethod
    def tearDownClass(cls):
        parts.set_detail("cad")

    def test_every_shipped_example_renders_and_parses(self):
        for name in support.example_names():
            with self.subTest(build=name):
                build = support.load_example(name)
                doc = _parse(booklet(build))
                self.assertEqual(doc.mismatched, [])
                self.assertEqual(doc.stack, [])

    def test_hero_can_be_dropped(self):
        build = support.load_example(support.example_names()[0])
        self.assertLess(len(booklet(build, hero=False)), len(booklet(build)))


if __name__ == "__main__":
    unittest.main()
