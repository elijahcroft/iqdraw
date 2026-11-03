"""Render compact, redistributable gallery previews for GitHub Pages.

The public site deliberately uses IQDraw's included procedural geometry.  A
local install may provide optional CAD meshes, but those source files are not
redistributed and the gallery must be reproducible from the repository alone.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

from iqdraw import parts
from iqdraw.__main__ import load_build


EXAMPLES = (
    "survey-rover",
    "pinned-frame",
    "gear-train",
    "drive-base",
    "grabber-arm",
)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: render-previews.py OUTPUT_DIRECTORY")
    rasterizer = shutil.which("rsvg-convert")
    if not rasterizer:
        raise SystemExit(
            "rsvg-convert is required to build the Pages gallery previews"
        )

    root = pathlib.Path(__file__).resolve().parent.parent
    output = pathlib.Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    parts.set_detail("simple")

    for name in EXAMPLES:
        build = load_build(root / "examples" / f"{name}.py")
        svg = build.hero_svg()
        destination = output / f"{name}.png"
        subprocess.run(
            [rasterizer, "-b", "white", "-w", "720", "-o", str(destination)],
            input=svg,
            text=True,
            check=True,
        )
        print(f"preview: {destination.name}")


if __name__ == "__main__":
    main()
