"""Non-visual GUI behavior, testable without a display server."""

import pathlib
import tempfile
import unittest

import support  # noqa: F401 - adds the checkout's parent to sys.path

from iqdraw.gui import (
    RenderSettings, create_starter, inspect_build, inspection_command,
    render_command,
)
from iqdraw.gui_state import (
    StudioState, bundled_examples, config_path, load_state, save_state,
)


class TestRenderCommand(unittest.TestCase):
    def test_it_translates_all_form_options(self):
        settings = RenderSettings(
            pathlib.Path("build.py"), pathlib.Path("guide.html"),
            detail="cad", context_detail="simple", hero=False,
            checks=True, strict=True, svg_dir=pathlib.Path("steps"), png=True,
        )
        command = render_command(settings)
        self.assertIn("--context-detail", command)
        self.assertIn("--no-hero", command)
        self.assertIn("--strict", command)
        self.assertIn("--svg-dir", command)
        self.assertIn("--png", command)
        self.assertNotIn("--no-check", command)

    def test_checks_can_be_disabled(self):
        command = render_command(RenderSettings(
            pathlib.Path("b.py"), pathlib.Path("b.html"), checks=False,
        ))
        self.assertIn("--no-check", command)
        self.assertNotIn("--strict", command)

    def test_defaults_make_the_shortest_useful_command(self):
        command = render_command(RenderSettings(
            pathlib.Path("b.py"), pathlib.Path("b.html"),
        ))
        self.assertEqual(command[1:], ["-m", "iqdraw", "b.py", "-o", "b.html",
                                       "--detail", "simple"])

    def test_inspection_is_a_separate_helper_process(self):
        command = inspection_command(pathlib.Path("b.py"))
        self.assertEqual(command[1:], ["-m", "iqdraw.gui_inspect", "b.py"])


class TestStarterAndSummary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_new_build_uses_the_title_and_never_overwrites(self):
        path = self.root / "little-crane.py"
        create_starter(path, "Little Crane")
        self.assertIn("Little Crane", path.read_text())
        with self.assertRaises(FileExistsError):
            create_starter(path, "Replacement")

    def test_summary_drives_steps_parts_and_checks_tabs(self):
        path = self.root / "clean.py"
        path.write_text(
            "from iqdraw import Build\n"
            "b = Build('Clean', subtitle='Demo')\n"
            "with b.step('Add a beam') as s:\n"
            "    s.add('beam_1x8', (0, 0, 0))\n"
        )
        summary = inspect_build(path)
        self.assertEqual(summary["title"], "Clean")
        self.assertEqual(summary["steps"], 1)
        self.assertEqual(summary["parts"], 1)
        self.assertEqual(summary["step_rows"][0][2], "Add a beam")


class TestStudioState(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_preferences_round_trip(self):
        path = self.root / "studio.json"
        state = StudioState(detail="cad", hero=False, export_svg=True)
        state.remember(self.root / "robot.py")
        save_state(path, state)
        loaded = load_state(path)
        self.assertEqual(loaded.detail, "cad")
        self.assertFalse(loaded.hero)
        self.assertTrue(loaded.export_svg)
        self.assertEqual(loaded.recent_files, state.recent_files)

    def test_corrupt_preferences_fall_back_to_defaults(self):
        path = self.root / "studio.json"
        path.write_text("not json")
        self.assertEqual(load_state(path), StudioState())

    def test_recent_files_are_unique_and_newest_first(self):
        state = StudioState()
        a, b = self.root / "a.py", self.root / "b.py"
        state.remember(a)
        state.remember(b)
        state.remember(a)
        self.assertEqual(state.recent_files, [str(a.resolve()), str(b.resolve())])

    def test_config_path_respects_xdg(self):
        path = config_path({"XDG_CONFIG_HOME": "/tmp/config"}, platform="linux")
        self.assertEqual(path, pathlib.Path("/tmp/config/iqdraw/studio.json"))

    def test_bundled_examples_hide_support_modules(self):
        examples = self.root / "examples"
        examples.mkdir()
        (examples / "gear-train.py").touch()
        (examples / "_modules.py").touch()
        self.assertEqual([path.name for path in bundled_examples(self.root)],
                         ["gear-train.py"])


if __name__ == "__main__":
    unittest.main()
