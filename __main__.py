"""
CLI:  python3 -m iqdraw builds/flapping-bird.py -o out/flapping-bird.html

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

from .instructions import booklet
from .spec import Build


def load_build(path: pathlib.Path) -> Build:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    for value in vars(module).values():
        if isinstance(value, Build):
            return value
    raise SystemExit(f"{path}: no Build instance found at module level")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="iqdraw", description=__doc__)
    ap.add_argument("spec", type=pathlib.Path, help="a build spec .py file")
    ap.add_argument("-o", "--out", type=pathlib.Path,
                    help="output .html (default: alongside the spec)")
    ap.add_argument("--svg-dir", type=pathlib.Path,
                    help="also write one .svg per step here")
    ap.add_argument("--png", action="store_true",
                    help="also rasterise each step to .png (needs rsvg-convert)")
    ap.add_argument("--no-hero", action="store_true",
                    help="skip the finished-model image on the cover")
    args = ap.parse_args(argv)

    build = load_build(args.spec)
    out = args.out or args.spec.with_suffix(".html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(booklet(build, hero=not args.no_hero), encoding="utf-8")
    print(f"{out}  ({len(build.steps)} steps, "
          f"{sum(build.inventory().values())} parts)")

    if args.svg_dir or args.png:
        d = args.svg_dir or out.parent / f"{out.stem}-steps"
        d.mkdir(parents=True, exist_ok=True)
        box = build.shared_box()
        for number, _step, svg in build.step_svgs(box):
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
