"""
iqdraw - VEX IQ (2nd gen) build-instruction diagrams from a text spec.

    from iqdraw import Build

    b = Build("My Build")
    with b.step("Lay the base beam down.") as s:
        s.add("beam_2x12", (0, 0, 0))

Render it with:  iqdraw examples/my-build.py -o out/my-build.html
"""

from .geom import PITCH_MM
from .instructions import booklet
from .parts import PALETTE, get, known_families, set_detail
from .render import RenderOpts, render, render_part_icon
from .spec import Assembly, Build, Section, Step

__all__ = [
    "Assembly", "Build", "Section", "Step", "RenderOpts",
    "PALETTE", "PITCH_MM",
    "booklet", "get", "known_families", "render", "render_part_icon",
    "set_detail",
]
