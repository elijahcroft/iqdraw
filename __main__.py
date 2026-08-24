"""
CLI:  iqdraw examples/gear-train.py -o out/gear-train.html

The build file is an ordinary Python module; the first module-level `Build`
instance it defines is the one that gets rendered.
"""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import shutil
import subprocess
import sys
import traceback

from . import parts
from .check import check
from .instructions import booklet
from .spec import Build, SpecError


STARTER = '''"""My first IQDraw build."""

from iqdraw import Build

b = Build(
    "My Build",
    subtitle="VEX IQ (2nd gen)",
    intro="What students will build and why.",
    done="the model is rigid and every moving part turns freely",
)

with b.step("Lay a 2x12 beam down flat.") as s:
    s.add("beam_2x12", (0, 0, 0))

with b.step("Pin a cross beam on top.") as s:
    s.add("beam_1x7", (1, 0, 0.5), rot=(0, 0, 90), arrow=True)
    s.many("pin_1x1", [(1, y, 0.25) for y in (0, 1)], axis="z", arrow=True)
'''


def load_build(path: pathlib.Path) -> Build:
    # The spec's own directory goes on the path first, so a build can import
    # shared modules from beside it - `from _modules import chassis`. Once
    # several builds share a chassis, describing it once is the same argument
    # `Assembly` makes inside one file.
    here = str(path.resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    try:
        spec.loader.exec_module(module)
    except SpecError as e:
        raise SystemExit(_where(e, path)) from None
    for value in vars(module).values():
        if isinstance(value, Build):
            return value
    raise SystemExit(f"{path}: no Build instance found at module level")


def _where(exc, path):
    """
    Point a spec error at the line of the build file that caused it.

    A build file is executed, not parsed, so the default traceback is a wall
    of iqdraw internals with the one line the author actually wrote buried in
    the middle of it.
    """
    frame = None
    for f in traceback.extract_tb(exc.__traceback__):
        if pathlib.Path(f.filename) == path:
            frame = f
    if frame is None:
        return f"{path}: {exc}"
    return f"{path}:{frame.lineno}: {exc}\n    {frame.line}"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="iqdraw", description=__doc__)
    ap.add_argument("spec", type=pathlib.Path, nargs="?",
                    help="a build spec .py file")
    ap.add_argument("--new", metavar="FILE", type=pathlib.Path,
                    help="write a commented starter build and exit")
    ap.add_argument("-o", "--out", type=pathlib.Path,
                    help="output .html (default: alongside the spec)")
    ap.add_argument("--svg-dir", type=pathlib.Path,
                    help="also write one .svg per step here")
    ap.add_argument("--png", action="store_true",
                    help="also rasterise each step to .png (needs rsvg-convert)")
    ap.add_argument("--no-hero", action="store_true",
                    help="skip the finished-model image on the cover")
    ap.add_argument("--detail", choices=parts.DETAIL_LEVELS, default="simple",
                    help="geometry detail: 'simple' uses the included "
                         "procedural shapes (default); 'cad' uses optional "
                         "local meshes when available")
    ap.add_argument("--context-detail", choices=parts.DETAIL_LEVELS,
                    help="geometry detail for the parts already built, drawn "
                         "washed out behind the step's own. 'simple' is about "
                         "half the file on a robot-sized build; the step's "
                         "new parts keep full detail either way")
    ap.add_argument("--no-check", action="store_true",
                    help="skip the build sanity checks")
    ap.add_argument("--strict", action="store_true",
                    help="treat any problem the checks find as an error")
    ap.add_argument("--check-only", action="store_true",
                    help="run the checks and report, without drawing anything")
    ap.add_argument("--gui", action="store_true",
                    help="open the desktop interface")
    args = ap.parse_args(argv)

    if args.gui:
        if args.new:
            ap.error("--gui and --new cannot be used together")
        from .gui import main as gui_main
        gui_main([str(args.spec)] if args.spec else [])
        return

    if args.new:
        if args.spec:
            ap.error("SPEC and --new cannot be used together")
        try:
            args.new.parent.mkdir(parents=True, exist_ok=True)
            with args.new.open("x", encoding="utf-8") as f:
                f.write(STARTER)
        except FileExistsError:
            raise SystemExit(f"{args.new}: already exists; nothing changed")
        print(f"Created {args.new}\nNext: iqdraw {args.new}")
        return
    if args.spec is None:
        ap.error("a build spec is required (or use --new FILE)")

    parts.set_detail(args.detail)
    build = load_build(args.spec)
    if args.context_detail:
        build.context_detail = args.context_detail

    if not args.no_check:
        problems = check(build)
        for p in problems:
            print(f"{args.spec}: {p}", file=sys.stderr)
        if problems and (args.strict or args.check_only):
            raise SystemExit(f"{len(problems)} problem(s) found")
        if args.check_only:
            print(f"{args.spec}: no problems found")
    if args.check_only:
        return

    out = args.out or args.spec.with_suffix(".html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(booklet(build, hero=not args.no_hero), encoding="utf-8")
    print(f"{out}  ({len(build.steps)} steps, "
          f"{sum(build.inventory().values())} parts)")

    if args.svg_dir or args.png:
        d = args.svg_dir or out.parent / f"{out.stem}-steps"
        d.mkdir(parents=True, exist_ok=True)
        for number, _step, svg in build.step_svgs():
            f = d / f"step-{number:02d}.svg"
            f.write_text(svg, encoding="utf-8")
            if args.png:
                _rasterise(f)
        print(f"{d}/  ({len(build.steps)} files)")


def _rasterise(svg_path: pathlib.Path):
    tool = shutil.which("rsvg-convert")
    if not tool:
        print("rsvg-convert not found; skipping PNG", file=sys.stderr)
        return
    png = svg_path.with_suffix(".png")
    subprocess.run([tool, "-b", "white", "-o", str(png), str(svg_path)],
                   check=True)


if __name__ == "__main__":
    main()
