"""
`--inspect`'s drive section: what turns as one body, which gears mesh, and
how fast each body turns for one turn of the driver.
"""

import unittest

import support  # noqa: F401  (makes the checkout importable)

from iqdraw import Build
from iqdraw.report import report


def _drive(b):
    out = report(b)
    names = {p["id"]: p["name"] for p in out["parts"]}
    return out["drive"], names


def _speeds(train, names, family):
    return [body["speed"] for body in train["bodies"]
            for i in body["parts"] if names[i].startswith(family)]


class TestDrive(unittest.TestCase):
    def test_a_shaft_and_its_square_parts_turn_as_one(self):
        b = Build("x")
        with b.step() as s:
            beam = s.add("beam_1x4", (0, 0, 0))
            s.add("shaft_3", beam.hole(0))
            s.add("spacer", beam.hole(0), on=beam)
            s.add("gear_12", beam.hole(0) + (0, 0, 0.625))
        drive, names = _drive(b)
        self.assertEqual(len(drive["trains"]), 1)
        body = drive["trains"][0]["bodies"][0]
        # The spacer's round bore spins on the shaft; the gear's does not.
        self.assertEqual(sorted(names[i] for i in body["parts"]),
                         ["gear_12", "shaft_3"])

    def test_a_train_gives_each_gear_its_speed(self):
        b = Build("x")
        with b.step() as s:
            g12 = s.add("gear_12", (0, 0, 0), axis="z")
            g36 = s.add("gear_36", g12.meshing("gear_36", "+x"))
            s.add("gear_60", g36.meshing("gear_60", "+x"))
        drive, names = _drive(b)
        self.assertEqual([m["teeth"] for m in drive["meshes"]],
                         [[12, 36], [36, 60]])
        (train,) = drive["trains"]
        self.assertFalse(train["jammed"])
        self.assertEqual(names[train["driver"]], "gear_12")
        self.assertEqual([body["speed"] for body in train["bodies"]],
                         [1.0, -0.3333, 0.2])

    def test_a_motor_drives_its_train(self):
        b = Build("x")
        with b.step() as s:
            s.add("motor", (0, 0, 0))
            # Into the square drive socket on the motor's +x side.
            shaft = s.add("shaft_3", (3, 0.5, 0.2), axis="x")
            g = s.add("gear_12", shaft.pos + (1, 0, 0), axis="x")
            s.add("gear_36", g.meshing("gear_36", "+y"))
        drive, names = _drive(b)
        trains = [t for t in drive["trains"] if len(t["bodies"]) > 1]
        self.assertEqual(len(trains), 1, drive)
        self.assertEqual(names[trains[0]["driver"]], "motor")
        self.assertEqual(_speeds(trains[0], names, "gear_36"), [-0.3333])

    def test_gears_meshing_in_a_ring_of_three_jam(self):
        b = Build("x")
        with b.step() as s:
            for at in ((0, 0, 0), (1, 0, 0), (0.5, 0.8660254, 0)):
                s.add("gear_12", at, axis="z")
        (train,) = _drive(b)[0]["trains"]
        self.assertTrue(train["jammed"])
        self.assertEqual({body["speed"] for body in train["bodies"]}, {None})

    def test_a_gear_put_on_upside_down_still_counts_the_same_way(self):
        b = Build("x")
        with b.step() as s:
            s.add("gear_12", (0, 0, 0), axis="z")
            s.add("gear_12", (1, 0, 0), rot=(180, 0, 0))
        (train,) = _drive(b)[0]["trains"]
        self.assertEqual([body["speed"] for body in train["bodies"]],
                         [1.0, -1.0])


if __name__ == "__main__":
    unittest.main()
