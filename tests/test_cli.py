"""
The command line, driven the way a user drives it.

Runs the real entry point in a subprocess rather than calling main(), so
argument parsing, exit codes and the messages printed on failure are all
covered - those are the whole interface for anyone who never opens the source.
"""

import pathlib
import subprocess
import sys
import tempfile
import unittest

import support

TOOLS = pathlib.Path(support.__file__).resolve().parents[2]


def run(*args, cwd=None):
    env = {"PYTHONPATH": str(TOOLS), "PATH": "/usr/bin:/bin"}
    return subprocess.run([sys.executable, "-m", "iqdraw", *map(str, args)],
                          capture_output=True, text=True, env=env,
                          cwd=cwd or TOOLS.parent)


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
with b.step("Pin it.") as s:
    s.add("pin_1x1", (0, 0, 0.25), axis="z", arrow=True)
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


class TestErrors(_Temp):
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
