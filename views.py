"""
The finished model from any side, and the whole build on one sheet.

A booklet answers "what does the reader see?"; these answer "is the spec
right?".  The flat views - top, bottom and the four sides - look straight
along an axis and carry a ruler of hole numbers along two edges, so a part
one hole out is a number that is wrong rather than a picture that looks a
bit off.  Every view has a key saying which way +x, +y and +z point.

The sheet is every step plus four views of the finished model on one page:
one image to look at after each change, instead of thirty.

Views use the same camera convention as the booklet - `geom.project` - so a
part on the left of a view is on the left of the booklet's drawing too.
"""

from __future__ import annotations

import base64
import math
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

from . import joints
from .geom import mat_apply, project, rot_z, vcross, vdot, vnorm
from .render import RenderOpts, _xml_escape, bounds, render, visible, \
    world_prims

# The renderer's own camera frame: screen right, screen up, and toward the
# camera, as `geom.project` and `geom.depth` define them.
_RIGHT = vnorm((1.0, -1.0, 0.0))
_UP = vnorm((-1.0, -1.0, 2.0))
_TOWARD = vnorm((1.0, 1.0, 1.0))


def look(toward, up):
    """
    The model rotation that puts the camera on the `toward` side of it, with
    `up` pointing up the page.
    """
    d = vnorm(toward)
    u = vnorm(tuple(a - b * vdot(up, d) for a, b in zip(up, d)))
    r = vcross(d, u)
    return tuple(tuple(_RIGHT[i] * r[j] + _UP[i] * u[j] + _TOWARD[i] * d[j]
                       for j in range(3)) for i in range(3))


# name: (camera side, page up, description).  Side views keep +z up the page.
VIEWS = {
    "top": ((0, 0, 1), (0, -1, 0), "from above, looking down"),
    "bottom": ((0, 0, -1), (0, 1, 0), "from below, looking up"),
    "xminus": ((-1, 0, 0), (0, 0, 1), "from the -x side"),
    "xplus": ((1, 0, 0), (0, 0, 1), "from the +x side"),
    "yminus": ((0, -1, 0), (0, 0, 1), "from the -y side"),
    "yplus": ((0, 1, 0), (0, 0, 1), "from the +y side"),
    "iso": (None, None, "the booklet's own corner view"),
}

# The views on a contact sheet, after the steps.
SHEET_VIEWS = ("top", "xminus", "yminus", "iso")

HEAD = 40          # px of header above a view: its name and the axis key
PAD = 34           # px of margin round the drawing, for the rulers
FONT = "font-family:sans-serif"


def _rotation(build, name):
    toward, up, _ = VIEWS[name]
    return rot_z(build.view_rz) if toward is None else look(toward, up)


def _model_box(build):
    """The finished model's nominal extent, in hole coordinates."""
    model = joints.analyse(build)
    if not model.parts:
        return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    return joints.union([p.box for p in model.parts])


def _axis_key(rot, x, y):
    """+x/+y/+z as they point on this view, drawn from (x, y)."""
    out = []
    for name, axis in (("x", (1, 0, 0)), ("y", (0, 1, 0)), ("z", (0, 0, 1))):
        sx, sy = project(mat_apply(rot, axis))
        n = math.hypot(sx, sy)
        if n < 0.2:
            # Pointing straight at or away from the camera.
            toward = vdot(mat_apply(rot, axis), _TOWARD) > 0
            out.append(f'<text x="{x - 14}" y="{y + 4}" font-size="10" '
                       f'text-anchor="end" style="{FONT}" fill="#555">'
                       f'+{name} {"toward you" if toward else "away"}</text>')
            continue
        ex, ey = x + sx / n * 16, y + sy / n * 16
        out.append(f'<line x1="{x}" y1="{y}" x2="{ex:.1f}" y2="{ey:.1f}" '
                   f'stroke="#555" stroke-width="1.4"/>')
        out.append(f'<text x="{ex + sx / n * 7 - 3:.1f}" '
                   f'y="{ey + sy / n * 7 + 3:.1f}" font-size="10" '
                   f'style="{FONT}" fill="#555">+{name}</text>')
    return "".join(out)


def _rulers(rot, box, scale, frame):
    """Hole numbers along the bottom and left edges of a flat view."""
    x0, y0, x1, y1 = frame
    width = (x1 - x0) * scale + 2 * PAD
    height = (y1 - y0) * scale + 2 * PAD
    centre = tuple((box[i] + box[i + 3]) / 2 for i in range(3))
    out = []
    for k, name in enumerate("xyz"):
        e = [0.0, 0.0, 0.0]
        e[k] = 1.0
        sx, sy = project(mat_apply(rot, e))
        horizontal = abs(sx) > 0.5 and abs(sy) < 1e-6
        vertical = abs(sy) > 0.5 and abs(sx) < 1e-6
        if not (horizontal or vertical):
            continue
        lo, hi = math.ceil(box[k] - 1e-6), math.floor(box[k + 3] + 1e-6)
        every = 1 if scale >= 18 else 2 if scale >= 9 else 5
        for t in range(lo, hi + 1):
            if t % every:
                continue
            p = list(centre)
            p[k] = float(t)
            qx, qy = project(mat_apply(rot, p))
            px = (qx - x0) * scale + PAD
            py = (qy - y0) * scale + PAD
            if horizontal:
                out.append(f'<line x1="{px:.1f}" y1="{height - PAD + 4}" '
                           f'x2="{px:.1f}" y2="{height - PAD + 10}" '
                           f'stroke="#999"/>')
                out.append(f'<text x="{px:.1f}" y="{height - PAD + 22}" '
                           f'font-size="10" text-anchor="middle" '
                           f'style="{FONT}" fill="#555">{t:g}</text>')
            else:
                out.append(f'<line x1="{PAD - 10}" y1="{py:.1f}" '
                           f'x2="{PAD - 4}" y2="{py:.1f}" stroke="#999"/>')
                out.append(f'<text x="{PAD - 13}" y="{py + 3.5:.1f}" '
                           f'font-size="10" text-anchor="end" '
                           f'style="{FONT}" fill="#555">{t:g}</text>')
        label = f"{name} (holes)"
        if horizontal:
            out.append(f'<text x="{width - 4}" y="{height - 4}" font-size="10" '
                       f'text-anchor="end" style="{FONT}" fill="#555">'
                       f'{label}</text>')
        else:
            out.append(f'<text x="4" y="12" font-size="10" '
                       f'style="{FONT}" fill="#555">{label}</text>')
    return "".join(out)


def view_svg(build, name, titled=True):
    """
    The finished model, everything at full colour, from view `name` - one of
    `VIEWS`.  Flat views carry hole-number rulers; every view has a key.
    `titled=False` leaves out the view's name, for a sheet that captions it.
    """
    if name not in VIEWS:
        raise ValueError(f"unknown view {name!r} - pick one of "
                         f"{', '.join(VIEWS)}")
    rot = _rotation(build, name)
    opts = RenderOpts(scale=build.opts.scale, pad=PAD, highlight=False,
                      background="#ffffff")
    placements = build.all_placements()
    frame = bounds(visible(world_prims(placements, opts, rot)), opts)
    drawing = render(placements, opts, rot, box=frame, arrows=False,
                     title=f"The finished {build.title}, "
                           f"{VIEWS[name][2]}.")
    if VIEWS[name][0] is not None:
        drawing = drawing[:-len("</svg>")] + _rulers(
            rot, _model_box(build), opts.scale, frame) + "</svg>"
    w, h = _size(drawing)
    w = max(w, 260.0)
    title = (f'<text x="8" y="16" font-size="13" font-weight="bold" '
             f'style="{FONT}">{_xml_escape(name)}</text>'
             f'<text x="8" y="31" font-size="10" style="{FONT}" fill="#555">'
             f'{_xml_escape(VIEWS[name][2])}</text>') if titled else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" '
            f'height="{h + HEAD:.0f}" viewBox="0 0 {w:.0f} {h + HEAD:.0f}">'
            f'<rect width="100%" height="100%" fill="#fff"/>'
            + title + _axis_key(rot, w - 70, 20)
            + _place(drawing, 0, HEAD, *_size(drawing))
            + "</svg>")


_ROOT = re.compile(r'<svg\b[^>]*>')


def _size(svg):
    tag = _ROOT.match(svg)[0]
    return (float(re.search(r'\bwidth="([\d.]+)"', tag)[1]),
            float(re.search(r'\bheight="([\d.]+)"', tag)[1]))


def _place(svg, x, y, w, h):
    """`svg` nested at (x, y), scaled to fit w x h with its aspect kept."""
    tag = _ROOT.match(svg)[0]
    new = re.sub(r'\bwidth="[\d.]+"', f'width="{w:.1f}"', tag, count=1)
    new = re.sub(r'\bheight="[\d.]+"', f'height="{h:.1f}"', new, count=1)
    new = new.replace("<svg", f'<svg x="{x:.1f}" y="{y:.1f}"', 1)
    return new + svg[len(tag):]


def _wrap(text, width):
    words, lines, line = text.split(), [], ""
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return lines


def _png_image(svg, x, y, w, h, tool):
    """`svg` rasterised on its own and embedded as an <image>."""
    sw, sh = _size(svg)
    k = min(w / sw, h / sh) * 2          # twice the cell, for a sharp zoom
    png = subprocess.run([tool, "-b", "white", "-w", str(max(1, round(sw * k))),
                          "-h", str(max(1, round(sh * k)))],
                         input=svg.encode(), capture_output=True,
                         check=True).stdout
    data = base64.b64encode(png).decode()
    return (f'<image x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'href="data:image/png;base64,{data}"/>')


def sheet_svg(build, columns=4, cell_w=420, cell_h=330, rasterizer=None):
    """
    Every step and four views of the finished model, captioned, on one page.

    The steps are the booklet's own drawings - new parts at full colour,
    insertion arrows and all - so what is checked here is what gets printed.

    `rasterizer` (a path to rsvg-convert) embeds each drawing as a PNG
    instead of nesting its SVG.  Thirty nested drawings with thirty
    stylesheets take rsvg minutes to rasterise as one document, and seconds
    one at a time.
    """
    cells = []
    total = len(build.steps)
    for number, step, svg in build.step_svgs():
        title = f"Step {number} of {total}"
        if step.section:
            title += f" - {step.section.title}"
        cells.append((title, step.note, svg))
    for name in SHEET_VIEWS:
        cells.append((f"View: {name}", VIEWS[name][2],
                      view_svg(build, name, titled=False)))

    text_h = 46
    rows = math.ceil(len(cells) / columns) or 1
    width = columns * cell_w
    height = rows * cell_h + 50
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
           f'height="{height}" viewBox="0 0 {width} {height}">'
           f'<rect width="100%" height="100%" fill="#fff"/>'
           f'<text x="12" y="30" font-size="20" font-weight="bold" '
           f'style="{FONT}">{_xml_escape(build.title)}</text>']
    slots = [((i % columns) * cell_w, 50 + (i // columns) * cell_h)
             for i in range(len(cells))]
    if rasterizer:
        with ThreadPoolExecutor() as pool:
            drawings = list(pool.map(
                lambda c: _png_image(c[0][2], c[1][0] + 8, c[1][1] + text_h,
                                     cell_w - 16, cell_h - text_h - 10,
                                     rasterizer), zip(cells, slots)))
    else:
        drawings = [_place(svg, x + 8, y + text_h, cell_w - 16,
                           cell_h - text_h - 10)
                    for (_, _, svg), (x, y) in zip(cells, slots)]
    for (title, note, _svg), (x, y), drawing in zip(cells, slots, drawings):
        out.append(f'<rect x="{x + 4}" y="{y + 4}" width="{cell_w - 8}" '
                   f'height="{cell_h - 8}" fill="none" stroke="#ddd"/>')
        out.append(f'<text x="{x + 12}" y="{y + 20}" font-size="12" '
                   f'font-weight="bold" style="{FONT}">'
                   f'{_xml_escape(title)}</text>')
        for j, line in enumerate(_wrap(note, 66)[:2]):
            out.append(f'<text x="{x + 12}" y="{y + 34 + j * 12}" '
                       f'font-size="10" style="{FONT}" fill="#444">'
                       f'{_xml_escape(line)}</text>')
        out.append(drawing)
    out.append("</svg>")
    return "".join(out)
