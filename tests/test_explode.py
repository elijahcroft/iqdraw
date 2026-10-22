"""
The exploded view: parts going in drawn pulled back along their arrows, with
a guide line, an inset of the step finished, and the page layout around it.
"""

import unittest

import support  # noqa: F401

from iqdraw import Assembly, Build, parts
from iqdraw.instructions import booklet
from iqdraw.render import exploded
from iqdraw.spec import Step


def _x(placement):
    return placement.tf.pos[0]


class TestExploded(unittest.TestCase):
    def setUp(self):
        parts.set_detail("simple")

    def tearDown(self):
        parts.set_detail("cad")

    def test_an_arrowed_part_is_pulled_back_along_its_arrow(self):
        s = Step().add("pin_1x1", (0, 0, 0), axis="x", arrow="-x")
        out, guides = exploded(s.placements)
        self.assertGreater(_x(out[0]), 1.0)
        self.assertEqual(len(guides), 1)

    def test_a_part_with_no_arrow_stays_put(self):
        s = Step().add("beam_1x4", (0, 0, 0)).add("pin_1x1", (0, 5, 0),
                                                   axis="x", arrow="-x")
        out, _ = exploded(s.placements)
        self.assertEqual(out[0].tf.pos, s.placements[0].tf.pos)

    def test_the_part_further_out_is_pulled_further(self):
        s = Step()
        s.add("collar", (0, 0, 0), axis="x", arrow="-x")
        s.add("collar", (1, 0, 0), axis="x", arrow="-x")
        out, _ = exploded(s.placements)
        pulled = [_x(o) - _x(p) for o, p in zip(out, s.placements)]
        self.assertGreater(pulled[1], pulled[0])

    def test_a_beam_the_pins_come_through_is_pulled_clear_of_them(self):
        s = Step()
        s.add("beam_2x8", (0.5, 0, 0), rot=(0, 90, 0))
        s.add("pin_1x1", (0.25, 0, 0), axis="x", arrow="-x")
        out, _ = exploded(s.placements)
        self.assertGreater(_x(out[0]), _x(out[1]))

    def test_a_module_moves_in_one_piece(self):
        side = Assembly("Side")
        side.step("rail").add("beam_1x4", (0, 0, 0))
        side.step("pin").add("pin_1x1", (0, 0, 0.25), axis="z")
        b = Build("x")
        b.place(side, at=(0, 0, 0), note="fit it", arrow="-z")
        step = b.steps[0]
        out, _ = exploded(step.placements)
        moves = {round(o.tf.pos[2] - p.tf.pos[2], 6)
                 for o, p in zip(out, step.placements)}
        self.assertEqual(len(moves), 1)
        self.assertEqual(step.module[0], "Side")

    def test_only_steps_with_arrows_get_an_inset(self):
        b = Build("x")
        b.step("lay").add("beam_1x4", (0, 0, 0))
        b.step("pin").add("pin_1x1", (0, 0, 0.25), axis="z", arrow=True)
        insets = b.step_insets()
        self.assertIsNone(insets[0])
        self.assertIn("<svg", insets[1])

    def test_explode_off_draws_flat_arrows_instead(self):
        b = Build("x", explode=False)
        b.step("pin").add("pin_1x1", (0, 0, 0.25), axis="z", arrow=True)
        self.assertEqual(b.step_insets(), [None])
        self.assertIn("<polygon", b.step_svgs()[0][2])


class TestPages(unittest.TestCase):
    def setUp(self):
        parts.set_detail("simple")

    def tearDown(self):
        parts.set_detail("cad")

    def test_four_short_steps_share_a_page(self):
        b = Build("x")
        for n in range(4):
            b.step(f"beam {n}").add("beam_1x4", (0, n, 0))
        self.assertEqual(booklet(b, hero=False).count('<section class="page'), 1)

    def test_a_wide_step_takes_a_whole_row(self):
        b = Build("x")
        for n in range(4):
            b.step("beam", wide=n == 1).add("beam_1x4", (0, n, 0))
        # 1, then 2 across the row; 3 and 4 share the next page.
        self.assertEqual(booklet(b, hero=False).count('<section class="page'), 2)

    def test_a_step_can_start_a_page(self):
        b = Build("x")
        b.step("one").add("beam_1x4", (0, 0, 0))
        b.step("two", page=True).add("beam_1x4", (0, 1, 0))
        self.assertEqual(booklet(b, hero=False).count('<section class="page'), 2)

    def test_one_step_a_page_in_the_16_9_style(self):
        b = Build("x", style="slides")
        for n in range(3):
            b.step("beam").add("beam_1x4", (0, n, 0))
        self.assertEqual(booklet(b, hero=False).count('<section class="page"'), 3)


if __name__ == "__main__":
    unittest.main()
