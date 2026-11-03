"""
The command line, driven the way a user drives it.

Runs the real entry point in a subprocess rather than calling main(), so
argument parsing, exit codes and the messages printed on failure are all
covered - those are the whole interface for anyone who never opens the source.
"""

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

import support


def run(*args, cwd=None):
    env = {"PYTHONPATH": support.IMPORT_ROOT, "PATH": "/usr/bin:/bin"}
    return subprocess.run([sys.executable, "-m", "iqdraw", *map(str, args)],
                          capture_output=True, text=True, env=env,
                          cwd=cwd or support.examples_dir().parent)


class _Temp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def spec(self, body, name="b.py"):
        path = self.tmp / name
        path.write_text("from iqdraw import Build\n" + body)
        return path


GOOD = """
b = Build("Good", done="it is rigid")
with b.step("Lay the beam down.") as s:
    s.add("beam_2x12", (0, 0, 0))
with b.step("Pin a second beam on top.") as s:
    s.add("pin_1x1", (0, 0, 0.25), axis="z", arrow=True)
    s.add("beam_1x4", (0, 0, 0.5))
"""


class TestRendering(_Temp):
    def test_it_creates_a_starter_without_overwriting(self):
        spec = self.tmp / "my-build.py"
        first = run("--new", spec)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("from iqdraw import Build", spec.read_text())
        original = spec.read_text()
        second = run("--new", spec)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(spec.read_text(), original)

    def test_it_writes_a_booklet(self):
        out = self.tmp / "out.html"
        r = run(self.spec(GOOD), "-o", out, "--detail", "simple")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(out.exists())
        self.assertIn("2 steps", r.stdout)

    def test_output_lands_beside_the_spec_by_default(self):
        spec = self.spec(GOOD)
        r = run(spec, "--detail", "simple")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(spec.with_suffix(".html").exists())

    def test_it_writes_one_svg_per_step(self):
        out = self.tmp / "out.html"
        steps = self.tmp / "steps"
        r = run(self.spec(GOOD), "-o", out, "--svg-dir", steps,
                "--detail", "simple")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(p.name for p in steps.glob("*.svg")),
                         ["step-01.svg", "step-02.svg"])
        self.assertIn("(2 files)", r.stdout)

    def test_png_output_reports_and_keeps_only_current_files(self):
        out = self.tmp / "out.html"
        steps = self.tmp / "steps"
        steps.mkdir()
        (steps / "step-03.png").write_bytes(b"stale")
        r = run(self.spec(GOOD), "-o", out, "--svg-dir", steps,
                "--detail", "simple", "--png")
        self.assertEqual(r.returncode, 0, r.stderr)
        if "rsvg-convert not found" in r.stderr:
            self.assertEqual(list(steps.glob("*.png")), [])
            self.assertIn("(2 files)", r.stdout)
            return
        self.assertEqual(sorted(p.name for p in steps.glob("*.png")),
                         ["step-01.png", "step-02.png"])
        self.assertIn("(4 files)", r.stdout)

    def test_a_shorter_rerender_removes_only_stale_step_files(self):
        out = self.tmp / "out.html"
        steps = self.tmp / "steps"
        steps.mkdir()
        (steps / "step-03.svg").write_text("stale")
        (steps / "notes.svg").write_text("keep me")
        r = run(self.spec(GOOD), "-o", out, "--svg-dir", steps,
                "--detail", "simple")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((steps / "step-03.svg").exists())
        self.assertEqual((steps / "notes.svg").read_text(), "keep me")

    def test_simple_detail_is_much_smaller_than_cad(self):
        if not support.parts.HAS_CAD_MESHES:
            self.skipTest("optional CAD meshes are not installed")
        a, b = self.tmp / "cad.html", self.tmp / "simple.html"
        run(self.spec(GOOD), "-o", a, "--detail", "cad")
        run(self.spec(GOOD), "-o", b, "--detail", "simple")
        self.assertLess(b.stat().st_size, a.stat().st_size)

    def test_the_hero_can_be_dropped(self):
        a, b = self.tmp / "a.html", self.tmp / "b.html"
        run(self.spec(GOOD), "-o", a, "--detail", "simple")
        run(self.spec(GOOD), "-o", b, "--detail", "simple", "--no-hero")
        self.assertLess(b.stat().st_size, a.stat().st_size)


BAD_GEARS = """
b = Build("Bad")
with b.step("gears one hole out") as s:
    s.add("beam_2x12", (0, 0, 0))
    s.add("gear_12", (0, 0, 0.75), axis="z")
    s.add("gear_36", (3, 0, 0.75), axis="z")
"""


class TestChecks(_Temp):
    def test_problems_are_reported_but_still_drawn(self):
        out = self.tmp / "out.html"
        r = run(self.spec(BAD_GEARS), "-o", out, "--detail", "simple")
        self.assertEqual(r.returncode, 0)
        self.assertIn("gear mesh", r.stderr)
        self.assertTrue(out.exists())

    def test_strict_turns_a_problem_into_a_failure(self):
        r = run(self.spec(BAD_GEARS), "-o", self.tmp / "o.html",
                "--detail", "simple", "--strict")
        self.assertNotEqual(r.returncode, 0)

    def test_check_only_draws_nothing(self):
        out = self.tmp / "out.html"
        r = run(self.spec(GOOD), "-o", out, "--check-only")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(out.exists())
        self.assertIn("no problems", r.stdout)

    def test_checks_can_be_switched_off(self):
        r = run(self.spec(BAD_GEARS), "-o", self.tmp / "o.html",
                "--detail", "simple", "--no-check")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("gear mesh", r.stderr)

    def test_a_clean_build_says_nothing(self):
        r = run(self.spec(GOOD), "-o", self.tmp / "o.html", "--detail", "simple")
        self.assertEqual(r.stderr.strip(), "")


class TestInspect(_Temp):
    def test_it_prints_the_build_as_json(self):
        r = run(self.spec(GOOD), "--inspect")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual([p["name"] for p in data["parts"]],
                         ["beam_2x12", "pin_1x1", "beam_1x4"])
        self.assertEqual(data["parts"][1]["joined"], [0, 2])
        self.assertEqual(data["problems"], [])

    def test_at_reports_what_is_at_a_point(self):
        r = run(self.spec(GOOD), "--inspect", "--at", "0,0,0.25")
        query = json.loads(r.stdout)["query"]
        self.assertEqual(query["parts"], [0, 1, 2])
        self.assertEqual(sorted(h["part"] for h in query["holes"]), [0, 2])

    def test_at_needs_inspect_and_three_numbers(self):
        spec = self.spec(GOOD)
        self.assertIn("needs --inspect", run(spec, "--at", "0,0,0").stderr)
        self.assertIn("three numbers",
                      run(spec, "--inspect", "--at", "0,0").stderr)


class TestErrors(_Temp):
    def test_check_modes_cannot_contradict_each_other(self):
        spec = self.spec(GOOD)
        for option in ("--strict", "--check-only"):
            with self.subTest(option=option):
                r = run(spec, "--no-check", option)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("cannot be used with --no-check", r.stderr)

    def test_an_unknown_part_names_the_line(self):
        spec = self.spec('b = Build("x")\n'
                         'with b.step("s") as s:\n'
                         '    s.add("beem_1x8", (0, 0, 0))\n')
        r = run(spec, "-o", self.tmp / "o.html")
        self.assertNotEqual(r.returncode, 0)
        # line 1 is the import `spec()` prepends, so the bad call is line 4
        self.assertIn("b.py:4", r.stderr)
        self.assertIn('s.add("beem_1x8"', r.stderr)
        self.assertIn("beam", r.stderr)

    def test_a_spec_with_no_build_says_so(self):
        spec = self.spec("x = 1\n")
        r = run(spec, "-o", self.tmp / "o.html")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no Build", r.stderr)

    def test_a_missing_file_fails_cleanly(self):
        r = run(self.tmp / "nope.py", "-o", self.tmp / "o.html")
        self.assertNotEqual(r.returncode, 0)

    def test_a_bad_detail_level_is_rejected(self):
        r = run(self.spec(GOOD), "--detail", "photoreal")
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
