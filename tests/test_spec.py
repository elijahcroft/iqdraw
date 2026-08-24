"""The build-spec API and the bookkeeping the booklet depends on."""

import unittest

import support  # noqa: F401

from iqdraw import Build
from iqdraw.spec import SpecError


def _tiny():
    b = Build("Tiny", subtitle="sub", intro="intro", done="it holds together")
    with b.step("first") as s:
        s.add("beam_2x12", (0, 0, 0))
    with b.step("second", caption="mind the gap") as s:
        s.many("pin_1x1", [(0, 0, 0.25), (3, 0, 0.25)], axis="z")
    return b


class TestBuilding(unittest.TestCase):
    def test_steps_collect_in_order(self):
        b = _tiny()
        self.assertEqual([s.note for s in b.steps], ["first", "second"])

    def test_many_places_one_part_per_coordinate(self):
        self.assertEqual(len(_tiny().steps[1].items), 2)

    def test_step_works_without_the_with_statement(self):
        b = Build("x")
        b.step("plain").add("beam_1x4", (0, 0, 0))
        self.assertEqual(len(b.steps[0].items), 1)

    def test_inventory_totals_across_steps(self):
        inv = _tiny().inventory()
        self.assertEqual(inv[("beam_2x12", None)], 1)
        self.assertEqual(inv[("pin_1x1", None)], 2)

    def test_qty_inflates_the_callout_but_not_the_drawing(self):
        b = Build("x")
        with b.step("one drawn, four asked for") as s:
            s.add("pin_1x1", (0, 0, 0), qty=4)
        self.assertEqual(sum(b.inventory().values()), 4)
        self.assertEqual(len(b.all_placements()), 1)

    def test_done_condition_is_carried(self):
        self.assertEqual(_tiny().done, "it holds together")

    def test_done_defaults_to_empty_rather_than_none(self):
        self.assertEqual(Build("x").done, "")


class TestErrors(unittest.TestCase):
    def test_unknown_part_is_a_spec_error(self):
        b = Build("x")
        with self.assertRaises(SpecError):
            b.step("s").add("beem_1x8", (0, 0, 0))

    def test_bad_axis_is_a_spec_error(self):
        b = Build("x")
        with self.assertRaises(SpecError) as cm:
            b.step("s").add("shaft_3", (0, 0, 0), axis="Z")
        self.assertIn("'x', 'y' or 'z'", str(cm.exception))

    def test_bad_arrow_direction_is_rejected(self):
        b = Build("x")
        with self.assertRaises(KeyError):
            b.step("s").add("pin_1x1", (0, 0, 0), arrow="sideways")


class TestFraming(unittest.TestCase):
    def test_one_frame_fits_every_step(self):
        # The whole point of the shared box: the model must not change size
        # from page to page, because size reads as progress.
        b = _tiny()
        box = b.shared_box()
        self.assertLess(box[0], box[2])
        self.assertLess(box[1], box[3])
        svgs = [svg for _, _, svg in b.step_svgs(box)]
        widths = {svg.split('viewBox="')[1].split('"')[0] for svg in svgs}
        self.assertEqual(len(widths), 1)

    def test_the_frame_leaves_room_for_insertion_arrows(self):
        plain = Build("x")
        plain.step("s").add("pin_1x1", (0, 0, 0), axis="z")
        arrowed = Build("x")
        arrowed.step("s").add("pin_1x1", (0, 0, 0), axis="z", arrow=True)
        self.assertGreater(_area(arrowed.shared_box()), _area(plain.shared_box()))

    def test_view_angle_falls_back_to_the_build_default(self):
        b = Build("x", view_rz=25)
        b.step("inherits")
        b.step("overrides", view_rz=-10)
        self.assertEqual(b.step_angle(b.steps[0]), 25)
        self.assertEqual(b.step_angle(b.steps[1]), -10)


def _area(box):
    return (box[2] - box[0]) * (box[3] - box[1])


class TestStepRendering(unittest.TestCase):
    def test_every_step_renders_once(self):
        b = _tiny()
        out = b.step_svgs()
        self.assertEqual([n for n, _, _ in out], [1, 2])
        for _, _, svg in out:
            self.assertTrue(svg.startswith("<svg"))

    def test_later_steps_carry_the_earlier_parts(self):
        b = _tiny()
        self.assertEqual(len(b.all_placements()), 3)

    def test_alt_text_names_what_the_step_adds(self):
        b = _tiny()
        alt = b.step_alt(2, b.steps[1])
        self.assertIn("Step 2", alt)
        self.assertIn("Connector Pin", alt)

    def test_a_check_your_work_step_says_nothing_was_added(self):
        b = Build("x")
        b.step("look at it")
        self.assertIn("nothing added", b.step_alt(1, b.steps[0]))

    def test_hero_draws_the_whole_model(self):
        self.assertIn("<svg", _tiny().hero_svg())


if __name__ == "__main__":
    unittest.main()
