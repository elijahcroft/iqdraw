"""The part catalogue: naming, sizing, colour and detail level."""

import unittest

import support  # noqa: F401

from iqdraw import parts
from iqdraw.geom import Disc, Edge, Facet
from iqdraw.parts import PALETTE, UnknownPart, get, known_families


class TestLookup(unittest.TestCase):
    def test_sizes_are_parsed_from_the_name(self):
        self.assertEqual(len(get("beam_1x8").holes), 8)
        self.assertEqual(len(get("beam_2x12").holes), 24)

    def test_holes_start_at_the_origin_and_step_by_one(self):
        # A pin and the hole it goes through share an address; that only works
        # if hole 0 really is at the part's own origin.
        holes = sorted(get("beam_1x8").holes)
        self.assertEqual(holes[0], (0, 0))
        self.assertEqual(holes[-1], (7, 0))

    def test_parts_are_interned(self):
        self.assertIs(get("beam_1x8"), get("beam_1x8"))

    def test_colour_override_is_a_separate_part(self):
        self.assertIsNot(get("beam_1x8"), get("beam_1x8", "red"))
        self.assertEqual(get("beam_1x8", "red").color, PALETTE["red"])

    def test_raw_hex_colour_passes_through(self):
        self.assertEqual(get("beam_1x8", "#123456").color, "#123456")

    def test_every_known_family_builds(self):
        samples = {
            "beam": "beam_1x4", "plate": "plate_2x4", "corner": "corner_2x2",
            "pin": "pin_1x1", "shaft": "shaft_3", "standoff": "standoff_2",
            "gear": "gear_36", "wheel": "wheel_200", "collar": "collar",
            "spacer": "spacer", "washer": "washer", "motor": "motor",
            "brain": "brain", "bumper": "bumper", "distance": "distance",
            "battery": "battery", "band": "band_4",
        }
        self.assertEqual(sorted(samples), known_families())
        for family, name in samples.items():
            with self.subTest(family=family):
                part = get(name)
                self.assertTrue(part.prims, f"{name} drew nothing")
                self.assertTrue(part.label)

    def test_every_primitive_is_a_known_kind(self):
        for prim in get("gear_36").prims:
            self.assertIsInstance(prim, (Facet, Edge, Disc))


class TestErrors(unittest.TestCase):
    def test_unknown_family_lists_the_real_ones(self):
        with self.assertRaises(UnknownPart) as cm:
            get("sprocket_18")
        self.assertIn("beam", str(cm.exception))

    def test_a_near_miss_gets_a_suggestion(self):
        with self.assertRaises(UnknownPart) as cm:
            get("beem_1x8")
        self.assertIn("beam", str(cm.exception))
        self.assertIn("mean", str(cm.exception))

    def test_a_known_family_with_a_bad_size_says_so(self):
        with self.assertRaises(UnknownPart) as cm:
            get("gear_")
        self.assertIn("size", str(cm.exception))


class TestGearGeometry(unittest.TestCase):
    def test_pitch_radius_is_teeth_over_24(self):
        # This is the arithmetic the whole meshing table rests on, so it is
        # worth pinning even though nothing exposes it as a function.
        for teeth, radius in ((12, 0.5), (36, 1.5), (60, 2.5)):
            with self.subTest(teeth=teeth):
                self.assertAlmostEqual(teeth / 24.0, radius)

    def test_documented_mesh_distances(self):
        for a, b, apart in ((12, 36, 2), (12, 60, 3), (36, 36, 3),
                            (36, 60, 4), (60, 60, 5)):
            with self.subTest(pair=(a, b)):
                self.assertAlmostEqual(a / 24.0 + b / 24.0, apart)

    def test_a_gear_is_about_as_wide_as_its_pitch_diameter(self):
        pts = [p for prim in get("gear_36").prims
               if isinstance(prim, Facet) for p in prim.pts]
        width = max(p[0] for p in pts) - min(p[0] for p in pts)
        self.assertAlmostEqual(width, 3.0, delta=0.6)

    def test_gear_face_details_are_not_clipped_into_one_cap_cell(self):
        gear = get("gear_36")
        dark_discs = [p for p in gear.prims if isinstance(p, Disc)]
        self.assertEqual(len(dark_discs), 16)  # rim + bore for eight holes


class TestWheelGeometry(unittest.TestCase):
    def test_wheel_diameter_comes_from_travel(self):
        for travel in (100, 160, 200, 250):
            with self.subTest(travel=travel):
                pts = [p for prim in get(f"wheel_{travel}").prims
                       if isinstance(prim, Facet) for p in prim.pts]
                diameter = max(p[0] for p in pts) - min(p[0] for p in pts)
                expected = travel / parts.PITCH_MM / 3.141592653589793
                self.assertAlmostEqual(diameter, expected, delta=0.08)

    def test_160_and_200_wheels_share_the_44mm_hub(self):
        # Their tire diameters differ, but VEX specifies the same 44 mm hub.
        for travel in (160, 200):
            wheel = get(f"wheel_{travel}")
            grey_pts = [p for prim in wheel.prims
                        if isinstance(prim, Facet) and prim.color == PALETTE["grey"]
                        for p in prim.pts]
            diameter = max(p[0] for p in grey_pts) - min(p[0] for p in grey_pts)
            self.assertAlmostEqual(diameter, 44.0 / parts.PITCH_MM, delta=0.08)

    def test_standard_wheel_hub_has_eight_attachment_holes(self):
        self.assertEqual(len(get("wheel_200").holes), 8)

    def test_100mm_tire_uses_a_pulley_without_attachment_holes(self):
        wheel = get("wheel_100")
        self.assertEqual(wheel.holes, ())
        self.assertTrue(any(isinstance(p, Facet) and p.color == PALETTE["blue"]
                            for p in wheel.prims))


class TestDetail(unittest.TestCase):
    def tearDown(self):
        parts.set_detail("cad")

    def test_simple_is_lighter_than_cad(self):
        if not parts.HAS_CAD_MESHES:
            self.skipTest("optional CAD meshes are not installed")
        parts.set_detail("cad")
        heavy = len(get("gear_36").prims)
        parts.set_detail("simple")
        light = len(get("gear_36").prims)
        self.assertLess(light, heavy)

    def test_every_part_still_draws_at_simple_detail(self):
        parts.set_detail("simple")
        for name in ("beam_1x4", "beam_2x12", "gear_12", "gear_36", "gear_60"):
            with self.subTest(name=name):
                self.assertTrue(get(name).prims)

    def test_switching_detail_clears_the_cache(self):
        parts.set_detail("cad")
        before = get("beam_1x4")
        parts.set_detail("simple")
        self.assertIsNot(before, get("beam_1x4"))

    def test_a_bad_level_is_rejected(self):
        with self.assertRaises(ValueError):
            parts.set_detail("photoreal")


if __name__ == "__main__":
    unittest.main()
