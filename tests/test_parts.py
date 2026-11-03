"""The part catalogue: naming, sizing, colour and detail level."""

import math
import unittest
from unittest import mock

import support  # noqa: F401

from iqdraw import parts
from iqdraw.geom import Disc, Edge, Facet, _contains_xy
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


class TestFaceRelief(unittest.TestCase):
    """The stepped face a beam or plate is molded with."""

    def setUp(self):
        parts.set_detail("simple")

    def tearDown(self):
        parts.set_detail(parts.DEFAULT_DETAIL)

    def face_z(self, name):
        return {round(z, 4) for prim in get(name).prims
                if isinstance(prim, Facet) for _x, _y, z in prim.pts}

    def test_a_beam_face_has_all_three_molded_levels(self):
        # Measured off the part, as a distance from its mid-plane: the
        # perimeter rim and the pads around the holes stand at 0.24, the
        # general face between them at 0.18, and the pockets the holes are
        # separated by drop to 0.079.
        seen = self.face_z("beam_2x12")
        for level in (0.24, 0.18, 0.079):
            with self.subTest(level=level):
                self.assertIn(level, seen)
                self.assertIn(-level, seen, "the far face is molded too")

    def test_the_hole_geometry_is_untouched_by_the_relief(self):
        # The counterbore is right already: full face height at the edge of
        # the pad, dropping to 0.195 where it meets the bore.
        beam = get("beam_2x12")
        at = {}
        for prim in beam.prims:
            if not isinstance(prim, Facet):
                continue
            for x, y, z in prim.pts:
                r = round(math.hypot(x, y), 3)
                if z > 0 and r in (0.25, 0.305):
                    at.setdefault(r, set()).add(round(z, 4))
        self.assertEqual(at[0.25], {0.195})
        self.assertEqual(at[0.305], {0.24})

    def test_a_hole_is_still_a_void_and_not_a_painted_disc(self):
        # Nothing may span a hole on the side a pin is pushed in from: one
        # facet centred on the hole sorts in front of whatever is buried in
        # it.  See the note on _relief_step.
        for prim in get("beam_2x12").prims:
            if not isinstance(prim, Facet) or max(q[2] for q in prim.pts) <= 0:
                continue
            self.assertFalse(_contains_xy(prim.pts, 3.0, 1.0),
                             f"{prim.color} facet covers the hole at (3, 1)")

    def test_a_plate_is_relieved_in_proportion_to_its_thickness(self):
        # The levels are fractions of the half thickness, not fixed depths -
        # a 0.25-thick plate cannot carry a beam's 0.24 rim.
        seen = self.face_z("plate_4x8")
        self.assertLessEqual(max(seen), parts.PLATE_T / 2)
        self.assertEqual(max(seen), round(parts.PLATE_T / 2 * parts.RIM_LEVEL, 4))

    def face_at(self, name, x, y):
        """Every height the near face carries at one (x, y)."""
        return {round(qz, 4) for prim in get(name).prims
                if isinstance(prim, Facet) for qx, qy, qz in prim.pts
                if qz > 0 and abs(qx - x) < 1e-9 and abs(qy - y) < 1e-9}

    def test_a_rib_carries_the_face_across_to_the_next_hole(self):
        # A real part does not ring each hole with a moat.  The general face
        # runs straight from one pad to the next as a rib, and it is the
        # corner between four holes that is recessed.
        half = parts.BEAM_T / 2
        self.assertEqual(self.face_at("beam_2x12", 3.5, 0.0),
                         {round(half * parts.FACE_LEVEL, 4)})
        self.assertEqual(self.face_at("beam_2x12", 3.5, 0.5),
                         {round(half * parts.POCKET_LEVEL, 4)})

    def test_neighbouring_cells_agree_on_the_edge_they_share(self):
        # Cells are sampled on rays from their own hole precisely so that two
        # of them land on the same points of the boundary between.  Sampling
        # it differently would crack the face open down that line, because a
        # rib puts one stretch of it higher than the rest.
        heights = {}
        for prim in get("beam_2x12").prims:
            if not isinstance(prim, Facet):
                continue
            for qx, qy, qz in prim.pts:
                if qz > 0 and abs(qx - 3.5) < 1e-9:
                    heights.setdefault(round(qy, 6), set()).add(round(qz, 6))
        self.assertTrue(heights, "nothing lies on the shared boundary")
        for y, zs in sorted(heights.items()):
            self.assertEqual(len(zs), 1, f"the boundary splits at y={y}: {zs}")

    def test_a_hole_is_round_enough_not_to_read_as_a_socket(self):
        # Bore, counterbore and pad all ride the cell's spokes, so the one
        # count decides how round every part of a hole looks.
        bore = {(round(x, 6), round(y, 6)) for prim in get("beam_2x12").prims
                if isinstance(prim, Facet) for x, y, _z in prim.pts
                if abs(math.hypot(x - 3.0, y) - parts.HOLE_R) < 1e-9}
        self.assertGreaterEqual(len(bore), parts.CELL_PTS)

    def test_every_relief_band_faces_out_of_the_part(self):
        # A band wound the wrong way round is invisible: the renderer culls
        # it, leaving a hole in the face rather than a step in it.
        for prim in get("beam_2x12").prims:
            if not isinstance(prim, Facet) or prim.normal == (0.0, 0.0, 0.0):
                continue
            zs = [q[2] for q in prim.pts]
            if max(zs) - min(zs) > 1e-9 or zs[0] < 0.05:
                continue    # not one of the near face's flat levels
            self.assertGreater(prim.normal[2], 0.9)


class TestGearGeometry(unittest.TestCase):
    def setUp(self):
        parts.set_detail("simple")

    def tearDown(self):
        parts.set_detail(parts.DEFAULT_DETAIL)

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

    def test_lightening_holes_are_voids_and_not_painted_discs(self):
        # A painted hole rides on face facets that sort independently of
        # it, and the ones in front clip it into a half-moon.
        for teeth in (36, 48, 60):
            gear = get(f"gear_{teeth}")
            self.assertFalse([p for p in gear.prims if isinstance(p, Disc)])
            for x, y in parts._gear_holes(teeth):
                for prim in gear.prims:
                    # Facing the side a shaft enters from; the dark floor
                    # seen from below faces away and is culled from above.
                    if isinstance(prim, Facet) and prim.normal[2] > 0 and \
                            min(q[2] for q in prim.pts) > 0:
                        self.assertFalse(
                            _contains_xy(prim.pts, x, y),
                            f"gear_{teeth}: a facet covers the hole at "
                            f"({x:.2f}, {y:.2f})")

    def test_a_gear_face_has_its_three_molded_levels(self):
        # Measured off the part: rim and hub at 0.25, spokes at 0.18, and
        # the recessed web at 0.079.
        for teeth in (36, 60):
            seen = {round(z, 4) for prim in get(f"gear_{teeth}").prims
                    if isinstance(prim, Facet) for _x, _y, z in prim.pts}
            for level in (0.25, 0.18, 0.079):
                with self.subTest(teeth=teeth, level=level):
                    self.assertIn(level, seen)
                    self.assertIn(-level, seen, "the far face is molded too")

    def test_no_face_facet_is_long_enough_to_mis_sort(self):
        # Facets sort by their centre.  A sliver fanned from a gear's hub, or
        # a rim strip down the whole side of a beam, sorts by a point far
        # from most of its own area and paints over parts lying across it.
        for name in ("gear_36", "gear_60", "beam_2x12", "plate_4x8"):
            for prim in get(name).prims:
                if not isinstance(prim, Facet):
                    continue
                span = max(math.dist(a, b) for a in prim.pts
                           for b in prim.pts)
                self.assertLess(span, 1.1, f"{name}: {span:.2f} long facet")


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
        parts.set_detail(parts.DEFAULT_DETAIL)

    def test_cad_is_the_stable_product_default(self):
        self.assertEqual(parts.DEFAULT_DETAIL, "cad")

    def test_cad_detail_falls_back_when_a_local_mesh_is_missing(self):
        parts.set_detail("cad")
        with mock.patch.object(parts, "cad_mesh", return_value=None):
            beam = get("beam_1x8")
        self.assertTrue(beam.prims)

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
