"""
Assemblies, mirroring and sections - the three things a build too big to
write as one flat list of coordinates needs.
"""

import unittest

import support  # noqa: F401

from iqdraw import Assembly, Build
from iqdraw.geom import (
    Facet, MIRROR_ROT, Transform, box, det, polygon_normal, vlen, vsub,
)
from iqdraw.instructions import booklet
from iqdraw.spec import SpecError


def _side():
    """A two-step module: a rail, and a shaft pushed out along +y."""
    a = Assembly("Side")
    with a.step("lay the rail down") as s:
        s.add("beam_2x12", (0, 0, 0))
    with a.step("push the shaft through") as s:
        s.add("shaft_4", (1, 0, 0), axis="y", arrow="+y")
    return a


def _pos(step, i=0):
    return step.placements[i].tf.pos


class TestAssembly(unittest.TestCase):
    def test_placing_inserts_the_assembly_steps(self):
        b = Build("x")
        b.place(_side())
        self.assertEqual([s.note for s in b.steps],
                         ["lay the rail down", "push the shaft through"])

    def test_at_offsets_every_coordinate(self):
        b = Build("x")
        b.place(_side(), at=(0, 5, 0))
        self.assertEqual(_pos(b.steps[0]), (0.0, 5.0, 0.0))
        self.assertEqual(_pos(b.steps[1]), (1.0, 5.0, 0.0))

    def test_an_assembly_can_be_placed_more_than_once(self):
        side = _side()
        b = Build("x")
        b.place(side, at=(0, 0, 0))
        b.place(side, at=(0, 5, 0))
        # Placing must not consume the assembly - it stays reusable.
        self.assertEqual(len(side.steps), 2)
        self.assertEqual(len(b.steps), 4)
        self.assertEqual(b.inventory()[("beam_2x12", None)], 2)

    def test_note_collapses_the_module_to_one_step(self):
        b = Build("x")
        b.place(_side(), note="build a second one")
        self.assertEqual(len(b.steps), 1)
        self.assertEqual(b.steps[0].note, "build a second one")
        self.assertEqual(len(b.steps[0].items), 2)

    def test_a_collapsed_step_drops_the_insertion_arrows(self):
        # They answer "which way does this part go in", which is not what a
        # step placing an already-built module is asking.
        b = Build("x")
        b.place(_side(), note="build a second one")
        self.assertTrue(all(p.arrow is None for p in b.steps[0].placements))

    def test_an_uncollapsed_placement_keeps_its_arrows(self):
        b = Build("x")
        b.place(_side())
        self.assertEqual(b.steps[1].placements[0].arrow, (0.0, 1.0, 0.0))

    def test_assemblies_can_carry_their_own_camera_angle(self):
        a = Assembly("a")
        a.step("turned", view_rz=90).add("beam_1x4", (0, 0, 0))
        b = Build("x")
        b.place(a)
        self.assertEqual(b.steps[0].view_rz, 90)


class TestMirror(unittest.TestCase):
    def test_mirror_negates_the_axis(self):
        b = Build("x")
        b.place(_side(), at=(0, 0, 0), mirror="y")
        self.assertEqual(_pos(b.steps[1]), (1.0, 0.0, 0.0))
        # The shaft ran out along +y; mirrored it runs out along -y.
        self.assertEqual(b.steps[1].placements[0].arrow, (0.0, -1.0, 0.0))

    def test_mirror_then_offset(self):
        b = Build("x")
        b.place(_side(), at=(0, 8, 0), mirror="y")
        self.assertEqual(_pos(b.steps[1]), (1.0, 8.0, 0.0))

    def test_a_mirror_is_not_a_rotation(self):
        # The whole reason `mirror` exists: no rotation turns a left side
        # into a right side, so this has to be a reflection.
        self.assertLess(det(MIRROR_ROT["y"]), 0)

    def test_a_single_part_can_be_mirrored(self):
        b = Build("x")
        with b.step("handed twin") as s:
            s.add("corner_3x3", (0, 0, 0), mirror="x")
        self.assertLess(det(b.steps[0].placements[0].tf.rot), 0)

    def test_bad_mirror_axis_is_a_spec_error(self):
        b = Build("x")
        with self.assertRaises(SpecError):
            b.step("x").add("beam_1x4", (0, 0, 0), mirror="w")

    def test_mirrored_geometry_is_not_inside_out(self):
        # The load-bearing property. A reflection reverses polygon winding,
        # so a mirrored solid renders inside-out unless the primitives put
        # the winding back - which is what `Transform.flips` is for.
        tf = Transform(MIRROR_ROT["y"])
        facets = [f.xform(tf) for f in box(0, 0, 0, 1, 1, 1, "#888")
                  if isinstance(f, Facet)]
        for f in facets:
            self.assertLess(vlen(vsub(polygon_normal(f.pts), f.normal)), 1e-9)
        top = max(facets, key=lambda f: sum(q[2] for q in f.pts) / len(f.pts))
        self.assertAlmostEqual(top.normal[2], 1.0)

    def test_an_ordinary_placement_does_not_flip(self):
        self.assertFalse(Transform().flips)


class TestSections(unittest.TestCase):
    def _sectioned(self):
        b = Build("x")
        b.section("Chassis")
        b.place(_side())
        b.section("Arm", "bolts to the front")
        with b.step("add the arm") as s:
            s.add("beam_1x8", (14, 0, 0.5))
        return b

    def test_steps_carry_their_section(self):
        b = self._sectioned()
        self.assertEqual([s.section.title for s in b.steps],
                         ["Chassis", "Chassis", "Arm"])

    def test_runs_group_consecutive_steps(self):
        self.assertEqual(self._sectioned().runs(), [(0, 2), (2, 3)])

    def test_place_can_open_a_section(self):
        b = Build("x")
        b.place(_side(), section="Left side")
        self.assertEqual(b.steps[0].section.title, "Left side")

    def test_a_build_with_no_sections_has_one_run(self):
        b = Build("x")
        b.place(_side())
        self.assertEqual(b.runs(), [(0, 2)])
        self.assertIsNone(b.steps[0].section)

    def test_without_sections_every_step_shares_one_frame(self):
        b = Build("x")
        b.place(_side())
        boxes = b.step_boxes()
        self.assertEqual(boxes, [b.shared_box()] * len(b.steps))

    def test_a_section_is_framed_on_the_build_so_far(self):
        # The reason sections exist at all: an early step should not be a
        # thumbnail adrift in a page sized for the finished model.
        b = self._sectioned()
        first, last = b.step_boxes()[0], b.step_boxes()[-1]
        self.assertLess(first[2] - first[0], last[2] - last[0])
        # ...and it still holds still within its own section.
        self.assertEqual(b.step_boxes()[0], b.step_boxes()[1])

    def test_the_booklet_announces_each_section(self):
        html = booklet(self._sectioned(), hero=False)
        self.assertIn("<h2>Chassis</h2>", html)
        self.assertIn("<h2>Arm</h2>", html)
        self.assertIn("Part 1 of 2", html)
        self.assertIn("bolts to the front", html)
        # Each section says how long it is, so its end is visible from its
        # start - the same job the cover's step count does for the build.
        self.assertIn(">2 steps<", html)
        self.assertIn(">1 step<", html)

    def test_step_numbering_stays_continuous_across_sections(self):
        html = booklet(self._sectioned(), hero=False)
        for n in (1, 2, 3):
            self.assertIn(f'id="step-{n}"', html)
        self.assertIn("of 3</span>", html)

    def test_an_unsectioned_booklet_gains_no_section_markup(self):
        b = Build("x")
        b.place(_side())
        self.assertNotIn('<div class="section-head">',
                         booklet(b, hero=False))


class TestContextDetail(unittest.TestCase):
    """
    Drawing the already-built parts from the cheaper procedural shapes.

    Every step redraws the whole model, so on a robot-sized build most of the
    file is parts that are washed out on purpose. The step's own parts keep
    optional local high-detail meshes either way.
    """

    def _build(self, context_detail=None):
        b = Build("x", context_detail=context_detail)
        with b.step("rail") as s:
            s.add("beam_2x12", (0, 0, 0))
        with b.step("gear on top") as s:
            s.add("gear_36", (2, 0, 0.75), axis="z")
        return b

    def test_default_draws_context_exactly_like_the_new_parts(self):
        b = self._build()
        built = b.step_svgs()[1][2]
        self.assertEqual(len(built), len(self._build().step_svgs()[1][2]))
        self.assertIsNone(b.context_detail)

    def test_simple_context_shrinks_the_later_steps(self):
        from iqdraw import parts
        if not parts.HAS_CAD_MESHES:
            self.skipTest("optional CAD meshes are not installed")
        full = self._build().step_svgs()
        lean = self._build("simple").step_svgs()
        # Step 1 has nothing built behind it, so it is untouched...
        self.assertEqual(len(full[0][2]), len(lean[0][2]))
        # ...and step 2, which carries the beam washed out behind it, shrinks.
        self.assertLess(len(lean[1][2]), len(full[1][2]))

    def test_a_check_your_work_step_keeps_full_detail(self):
        # It draws everything at full colour, so none of it is background.
        b = self._build("simple")
        b.step("check it holds together")
        plain = self._build()
        plain.step("check it holds together")
        self.assertEqual(len(b.step_svgs()[2][2]), len(plain.step_svgs()[2][2]))

    def test_get_resolves_one_part_at_a_chosen_detail(self):
        from iqdraw import parts
        self.assertIsNot(parts.get("beam_2x12", None, detail="simple"),
                         parts.get("beam_2x12", None, detail="cad"))
        # ...without disturbing the global level.
        self.assertEqual(parts.detail(), "cad")


class TestNesting(unittest.TestCase):
    """An assembly made of assemblies - a claw of two fingers, an arm of two
    links.  Without this, composition stops one level down."""

    def _finger(self):
        a = Assembly("Finger")
        with a.step("lay the beam") as s:
            s.add("beam_1x4", (0, 0, 0))
        with a.step("turn the tip in") as s:
            s.add("beam_1x2", (3, 0, 0.5), rot=(0, 0, 90))
        return a

    def _claw(self):
        c = Assembly("Claw")
        c.place(self._finger(), at=(0, 0, 0))
        c.place(self._finger(), at=(0, 5, 0), mirror="y", note="and a second")
        return c

    def test_an_assembly_can_place_an_assembly(self):
        self.assertEqual(len(self._claw().steps), 3)

    def test_nested_transforms_compose(self):
        b = Build("x")
        b.place(self._claw(), at=(2, 1, 4))
        # finger one lands at the claw's origin, moved by the build's `at`
        self.assertEqual(_pos(b.steps[0]), (2.0, 1.0, 4.0))
        # the mirrored finger was at y=5 inside the claw
        self.assertEqual(_pos(b.steps[2]), (2.0, 6.0, 4.0))

    def test_a_mirror_inside_survives_the_outer_placement(self):
        b = Build("x")
        b.place(self._claw(), at=(0, 0, 0))
        from iqdraw.geom import det
        self.assertLess(det(b.steps[2].placements[0].tf.rot), 0)

    def test_mirroring_the_whole_nest_cancels_the_inner_mirror(self):
        # Two reflections make a rotation - the far claw's far finger is
        # handed the same way as the near claw's near finger.
        from iqdraw.geom import det
        b = Build("x")
        b.place(self._claw(), at=(0, 0, 0), mirror="y")
        self.assertGreater(det(b.steps[2].placements[0].tf.rot), 0)

    def test_inventory_counts_through_the_nest(self):
        b = Build("x")
        b.place(self._claw())
        self.assertEqual(b.inventory()[("beam_1x4", None)], 2)
        self.assertEqual(b.inventory()[("beam_1x2", None)], 2)


class TestCoverContents(unittest.TestCase):
    def _sectioned(self):
        b = Build("x")
        b.section("Chassis")
        b.step("one").add("beam_2x12", (0, 0, 0))
        b.step("two").add("pin_1x1", (0, 0, 0.25), axis="z")
        b.section("Arm")
        b.step("three").add("beam_1x8", (0, 0, 0.5))
        return b

    def test_the_cover_lists_the_sections_and_their_steps(self):
        html = booklet(self._sectioned(), hero=False)
        self.assertIn("What you will build", html)
        self.assertIn(">Chassis</span>", html)
        self.assertIn("steps 1&ndash;2", html)
        self.assertIn(">step 3<", html)

    def test_a_build_with_no_sections_has_no_contents_block(self):
        b = Build("x")
        b.step("only").add("beam_1x4", (0, 0, 0))
        self.assertNotIn("What you will build", booklet(b, hero=False))

    def test_each_section_lists_what_to_fetch(self):
        html = booklet(self._sectioned(), hero=False)
        self.assertIn("Fetch these before you start", html)

    def test_section_runs_pairs_sections_with_their_ranges(self):
        runs = self._sectioned().section_runs()
        self.assertEqual([(s.title, lo, hi) for s, lo, hi in runs],
                         [("Chassis", 0, 2), ("Arm", 2, 3)])


if __name__ == "__main__":
    unittest.main()
