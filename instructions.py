"""
Turns a Build into a printable / projectable instruction booklet.

One self-contained HTML file: inline CSS, inline SVG, no fonts or scripts to
fetch.  It is laid out like the manual the build was redrawn from, page for
page - `Build(style=...)` picks which kind:

  letter     VEX's letter-size guides: four steps to a page, each with its
             parts box, the drawing pulled apart, and the step finished in a
             small box in the corner
  landscape  VEX's 2nd-gen guides: a parts strip across the top of each page,
             a step or two below it, each drawn pulled apart and then
             finished, "2X" where it is built twice
  slides     16:9 guides: one step a page under a strip of named parts
  magikid    Magikid's guides: one step a page, the step's parts in a small
             pale box at the top right

The pages carry no words beyond what the originals print - counts, part
numbers or names, the step number.  Each step's note and caption are still in
the page as text a screen reader reads out, and in the drawing's description.
"""

from __future__ import annotations

import html
import math
from collections import Counter
from functools import lru_cache

from . import parts
from .parts import get, part_number, size_label
from .render import render_module_icon, render_part_icon

CSS = """
*{box-sizing:border-box}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
:root{--desk:#e6e9ee;--paper:#fff;--ink:#171b21;--ink-3:#5a6270;--blue:#2274bc;
  --rule:#9a9a9a;--shadow:0 2px 10px rgba(20,26,36,.18)}
body{margin:0;background:var(--desk);color:var(--ink);
  font:14px/1.3 "Segoe UI",Roboto,-apple-system,"Helvetica Neue",Arial,sans-serif}
.sheet{padding:24px 0 40px}
/* Visually hidden, still read aloud: each step's words. */
.vh{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;
  clip:rect(0 0 0 0);clip-path:inset(50%);white-space:nowrap;border:0}
/* Pages off screen are not laid out until scrolled to: a long booklet's
   drawings are most of its weight. */
.page{position:relative;margin:0 auto 24px;background:var(--paper);
  box-shadow:var(--shadow);overflow:hidden;content-visibility:auto;
  contain-intrinsic-size:auto 800px}
.page svg{display:block}
.art{position:absolute;margin:0}
.art>svg{position:absolute;inset:0;width:100%;height:100%}
.badge{position:absolute;display:flex;align-items:center;justify-content:center;
  color:#fff;font-weight:700}
.badge svg{position:absolute;inset:0;width:100%;height:100%}
.badge b{position:relative}
.flag{position:absolute;width:24px;height:20px}
.times{position:absolute;color:var(--blue);font-weight:700;letter-spacing:-.02em}
.turn-icon{position:absolute;width:42px;height:42px}
footer{color:var(--ink-3);font-size:12px;text-align:center;padding:4px 0 0}
@media screen and (prefers-color-scheme:dark){:root{--desk:#15181d}
  footer{color:#a2acba}}
@media print{body{background:#fff}.sheet{padding:0}
  .page{margin:0;box-shadow:none;break-after:page;page-break-after:always;
    content-visibility:visible}
  .page:last-of-type{break-after:auto;page-break-after:auto}footer{display:none}}
"""

# ------------------------------------------------------------- per style

LETTER_CSS = """
.page{width:816px;height:1056px}
.foot{position:absolute;left:0;right:0;bottom:0;height:46px;background:var(--blue)}
.title{position:absolute;left:44px;top:34px;margin:0;color:var(--blue);
  font-size:21px;font-weight:400;line-height:1.1}
.cell{position:absolute}
.vrule{position:absolute;width:1px;background:var(--rule)}
.hrule{position:absolute;height:1px;background:var(--rule)}
.cell .badge{left:6px;top:0;width:40px;height:40px;font-size:19px}
.box{position:absolute;left:4px;right:4px;top:44px;display:flex;
  align-items:flex-end;justify-content:space-evenly;
  gap:4px 14px;padding:4px 10px 4px;flex-wrap:wrap}
.box>.scallop{position:absolute;inset:0;width:100%;height:100%;z-index:0}
.box>.it{position:relative;z-index:1}
.box .it{display:flex;flex-direction:column;align-items:center;min-width:0}
.box .q{font-size:15px;line-height:1.1}
.box .ic svg{max-width:150px;max-height:52px;width:auto;height:auto}
.box .pn{font-size:8px;color:#444;margin-top:1px}
.inset{position:absolute;right:4px;bottom:6px;width:31%;height:30%;z-index:1;
  border:1.5px solid var(--blue);border-radius:12px;background:#fff;padding:4px}
.inset svg{display:block;width:100%;height:100%}
.flag.l{left:-22px;top:-12px}.flag.r{left:38px;top:-12px}
"""

LANDSCAPE_CSS = """
.page{width:816px;height:552px}
.foot{position:absolute;left:0;right:0;bottom:0;height:22px;background:#1270c4;
  color:#fff;font-size:9px;display:flex;align-items:center;justify-content:flex-end;
  padding:0 14px}
.strip{position:absolute;left:14px;right:14px;top:6px;height:84px;display:flex;
  align-items:flex-end;justify-content:flex-start;gap:6px 26px;padding:0 8px 4px;
  border-bottom:1.5px solid #7d7d7d}
.strip .it{position:relative;display:flex;align-items:flex-end;gap:3px}
.strip .ic svg{max-width:150px;max-height:66px;width:auto;height:auto}
.strip .q{font-size:13px;font-weight:700;padding-bottom:2px}
.tag{position:absolute;left:-4px;top:-14px;background:#3a3a3a;color:#fff;
  font-size:8.5px;font-weight:700;border-radius:8px;padding:1px 6px}
.col{position:absolute}
.hrule{position:absolute;height:1.5px;background:#7d7d7d}
.vrule{position:absolute;top:96px;bottom:28px;width:1.5px;background:#7d7d7d}
.col .badge{left:2px;top:2px;width:30px;height:30px;font-size:13px;color:var(--blue)}
.col .times{left:38px;top:6px;font-size:40px;line-height:1}
.col .turn-icon{left:40px;top:4px}
.cover{background:#1270c4}
.cover .ctitle{position:absolute;left:0;right:0;top:40px;text-align:center;color:#fff;
  font-size:22px;font-weight:300;margin:0}
.cover .hero{position:absolute;left:60px;right:60px;top:90px;bottom:40px}
.cover .hero svg{position:absolute;inset:0;width:100%;height:100%}
.cover .band{position:absolute;right:0;top:0;bottom:0;width:26px;background:#3db44a}
.inv{position:absolute;left:24px;right:200px;top:24px;bottom:40px;display:flex;
  flex-direction:column;gap:14px}
.inv .it{position:relative;display:flex;align-items:center;gap:10px;height:44px;
  border-radius:0 26px 26px 0;padding:0 0 0 12px;width:62%}
.inv .q{font-size:14px;font-weight:700;min-width:34px}
.inv .pname{font-size:8px;color:#333;display:flex;flex-direction:column;
  align-items:flex-start;gap:2px}
.inv .ic{position:absolute;left:100%;margin-left:-40px;top:50%;
  transform:translateY(-50%)}
.inv .ic svg{display:block;max-width:220px;max-height:80px;width:auto;height:auto}
.tag.in{position:static}
"""

SLIDES_CSS = """
.page{width:960px;height:540px}
.strip{position:absolute;left:220px;right:150px;top:14px;height:128px;display:flex;
  flex-wrap:wrap;align-items:flex-end;align-content:flex-end;justify-content:center;
  gap:2px 34px;border-bottom:2px solid #8a8a8a;padding-bottom:8px}
.strip .it{display:flex;flex-direction:column;align-items:center}
.strip .ic svg{max-width:240px;max-height:40px;width:auto;height:auto}
.strip .nm{font-size:11px;color:#333;margin-top:3px;white-space:nowrap}
.strip .nm b{color:#111}
.page .badge{left:178px;top:24px;width:36px;height:36px;font-size:17px}
.page .times{left:224px;top:24px;font-size:30px}
.page .turn-icon{left:222px;top:66px}
.inset{position:absolute;right:136px;bottom:16px;width:186px;height:128px;
  border:1.5px solid #2c7cc0;border-radius:10px;background:#fff;padding:4px}
.inset svg{display:block;width:100%;height:100%}
.flag.l{left:-24px;top:-10px}.flag.r{left:34px;top:-10px}
.cover .ctitle{position:absolute;left:36px;top:12px;margin:0;background:#1f70c1;
  color:#fff;font-size:15px;font-weight:600;padding:6px 18px 6px 70px;
  border-radius:0 0 4px 4px;width:430px}
.cover .ctitle i{font-style:normal;font-weight:300;position:absolute;left:16px}
.cover .hero{position:absolute;left:60px;right:60px;top:60px;bottom:60px}
.cover .hero svg{position:absolute;inset:0;width:100%;height:100%}
"""

MAGIKID_CSS = """
.page{width:1123px;height:794px}
.num{position:absolute;left:52px;top:34px;margin:0;font-size:46px;font-weight:700;
  font-family:Arial,Helvetica,sans-serif;color:#000}
.box{position:absolute;right:56px;top:42px;min-width:150px;min-height:150px;
  max-width:420px;background:#d9edfb;border:1.2px solid #000;display:flex;
  flex-wrap:wrap;align-items:center;justify-content:center;gap:6px 14px;
  padding:14px 14px 22px}
.box .it{position:relative;display:flex;flex-direction:column;align-items:center}
.box .ic svg{max-width:240px;max-height:150px;width:auto;height:auto}
.box .q{font-size:10px;align-self:flex-start;margin-top:2px}
.inv{position:absolute;left:40px;right:40px;top:40px;bottom:40px;display:flex;
  flex-direction:column;flex-wrap:wrap;align-content:flex-start;gap:18px 40px}
.inv .it{display:flex;flex-direction:column;align-items:flex-start}
.inv .ic svg{max-width:300px;max-height:150px;width:auto;height:auto}
.inv .q{font-size:10px}
.turn-icon.mk{left:470px;top:250px;width:30px;height:30px;border:1px solid #2b6fc2;
  padding:3px;background:#fff}
"""

STYLE_CSS = {"letter": LETTER_CSS, "landscape": LANDSCAPE_CSS,
             "slides": SLIDES_CSS, "magikid": MAGIKID_CSS}

PRINT_SIZE = {"letter": "8.5in 11in", "landscape": "8.5in 5.75in",
              "slides": "10in 5.625in", "magikid": "297mm 210mm"}


def _esc(s):
    return html.escape(s or "")


@lru_cache(maxsize=None)
def _icon(name, color, box_px, detail, flat=False):
    # Decorative: the count and the part's name or number sit beside it.
    return render_part_icon(name, color, box_px=box_px, min_px=30.0,
                            flat=flat)


def _scallop(w, h, r=14.0, step=16.0, dip=1.6, color="#2274bc"):
    """
    The letter guides' parts box: a rounded rectangle whose sides are a row
    of shallow scallops.  An SVG `w` x `h` px, to lay behind the box.
    """
    def edge(x0, y0, x1, y1, nx, ny):
        n = max(1, round(math.hypot(x1 - x0, y1 - y0) / step))
        out = []
        for k in range(n):
            ax = x0 + (x1 - x0) * (k + 0.5) / n + nx * dip
            ay = y0 + (y1 - y0) * (k + 0.5) / n + ny * dip
            bx = x0 + (x1 - x0) * (k + 1) / n
            by = y0 + (y1 - y0) * (k + 1) / n
            out.append(f"Q{ax:.1f} {ay:.1f} {bx:.1f} {by:.1f}")
        return " ".join(out)
    i = 1.0
    d = (f"M{r:.1f} {i} " + edge(r, i, w - r, i, 0, 1)
         + f" A{r - i} {r - i} 0 0 1 {w - i} {r:.1f} "
         + edge(w - i, r, w - i, h - r, -1, 0)
         + f" A{r - i} {r - i} 0 0 1 {w - r:.1f} {h - i} "
         + edge(w - r, h - i, r, h - i, 0, -1)
         + f" A{r - i} {r - i} 0 0 1 {i} {h - r:.1f} "
         + edge(i, h - r, i, r, 1, 0)
         + f" A{r - i} {r - i} 0 0 1 {r:.1f} {i} Z")
    return (f'<svg class="scallop" viewBox="0 0 {w:.0f} {h:.0f}" '
            f'aria-hidden="true"><path d="{d}" fill="#fff" stroke="{color}" '
            'stroke-width="1.5"/></svg>')


def _sorted(counts):
    return sorted(counts.items(), key=_inv_sort)


def _burst(points=14, fill="#2274bc"):
    """The letter and 16:9 guides' step badge: a blue starburst."""
    pts = []
    for i in range(points * 2):
        r = 1.0 if i % 2 == 0 else 0.80
        t = math.pi * i / points - math.pi / 2
        pts.append(f"{r * math.cos(t):.3f},{r * math.sin(t):.3f}")
    return (f'<svg viewBox="-1 -1 2 2" aria-hidden="true">'
            f'<polygon points="{" ".join(pts)}" fill="{fill}"/></svg>')


def _cog():
    """The 2nd-gen guides' step badge: a blue outlined gear, open inside."""
    pts = []
    n = 12
    for i in range(n * 4):
        t = 2 * math.pi * i / (n * 4) - math.pi / 2
        r = 0.94 if (i % 4) in (0, 1) else 0.78
        pts.append(f"{r * math.cos(t):.3f},{r * math.sin(t):.3f}")
    return (f'<svg viewBox="-1 -1 2 2" aria-hidden="true">'
            f'<polygon points="{" ".join(pts)}" fill="#fff" stroke="#1270c4" '
            f'stroke-width=".09" stroke-linejoin="round"/></svg>')


def _turn_icon():
    """Two orange arrows chasing round: turn the model."""
    return ('<svg class="turn-icon" viewBox="-12 -12 24 24" aria-hidden="true">'
            '<g fill="none" stroke="#f26b21" stroke-width="2.6" '
            'stroke-linecap="round">'
            '<path d="M-8.5 -2.5 A9 9 0 0 1 7 -5.5"/>'
            '<path d="M8.5 2.5 A9 9 0 0 1 -7 5.5"/></g>'
            '<g fill="#f26b21"><path d="M9.6 -8.6 L8.6 -1.8 L3.2 -5.8 Z"/>'
            '<path d="M-9.6 8.6 L-8.6 1.8 L-3.2 5.8 Z"/></g></svg>')


def _flag(side):
    """A small chequered flag either side of the last step's badge."""
    cells = "".join(
        f'<rect x="{3 + 4 * c}" y="{1 + 4 * r}" width="4" height="4"/>'
        for r in range(3) for c in range(4) if (r + c) % 2 == 0)
    flip = ' transform="translate(22 0) scale(-1 1)"' if side == "l" else ""
    return (f'<svg class="flag {side}" viewBox="0 0 22 18" aria-hidden="true">'
            f'<g{flip}><rect x="3" y="1" width="16" height="12" fill="#fff" '
            f'stroke="#171b21" stroke-width=".8"/><g fill="#171b21">{cells}</g>'
            f'<line x1="2.5" y1="1" x2="2.5" y2="17.5" stroke="#171b21" '
            f'stroke-width="1.4"/></g></svg>')


def _words(number, step, n_steps):
    """What the page shows as pictures, as text for a screen reader."""
    bits = [f"Step {number} of {n_steps}."]
    if step.times > 1:
        bits.append(f"Do this {step.times} times.")
    if step.turn is not None:
        bits.append(step.turn_note)
    if step.note:
        bits.append(step.note)
    if step.caption:
        bits.append(step.caption)
    return f'<p class="vh">{_esc(" ".join(bits))}</p>'


def _turns(build, camera=True):
    """
    [bool] per step: does the reader turn the model before it?  With
    `camera` False, only where the build says so - the 2nd-gen guides draw
    the arrows only where you turn a piece over, not for a new view.
    """
    out, prev = [], None
    for step in build.steps:
        angle = build.step_angle(step)
        moved = camera and prev is not None and abs(angle - prev) > 1e-6
        # The 2nd-gen guides mark only what the build marks with `spin`;
        # the letter and 16:9 guides also mark a turn of the model.
        out.append(step.spin or moved or (camera and step.turn is not None))
        prev = angle
    return out


def _paginate(build, per_page, cells=None):
    """
    [[step index]] per page: `per_page` cells to a page, a wide step taking
    two, and a new page wherever a step asks for one.  `cells` is the list
    of (index, wide, new page) to lay out, if not just the steps.
    """
    if cells is None:
        cells = [(i, s.wide, s.page) for i, s in enumerate(build.steps)]
    pages, cur, used = [], [], 0
    for i, wide, page in cells:
        need = 2 if wide and per_page == 4 else 1
        if cur and (page or used + need > per_page):
            pages.append(cur)
            cur, used = [], 0
        cur.append(i)
        used += need
    if cur:
        pages.append(cur)
    return pages


def _doc(build, pages):
    size = PRINT_SIZE[build.style]
    css = (CSS + STYLE_CSS[build.style]
           + f"@media print{{@page{{size:{size};margin:0}}}}")
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_esc(build.title)}</title>"
        f"<style>{css}</style></head>"
        f'<body><main class="sheet">{"".join(pages)}'
        "<footer>Drawn with iqdraw &middot; VEX IQ (2nd gen)</footer>"
        "</main></body></html>"
    )


def booklet(build, hero=True):
    """Render a complete Build to a standalone HTML document."""
    return _doc(build, _LAYOUTS[build.style](build, hero))


# ----------------------------------------------------------------- letter


def _letter(build, hero):
    n = len(build.steps)
    svgs = [svg for _, _, svg in build.step_svgs()]
    insets = build.step_insets(px=170.0)
    pages = []
    W, H, top, bottom, gut = 816, 1056, 34, 60, 22
    # The finished model, as a cell of its own after the last step: -1.
    cells = [(i, st.wide, st.page) for i, st in enumerate(build.steps)]
    wide = {i for i, w, _ in cells if w}
    if build.finale and hero:
        cells.append((-1, build.finale == "row", False))
        if build.finale == "row":
            wide.add(-1)
    for p, idx in enumerate(_paginate(build, 4, cells)):
        # Lay the page's cells out two by two, a wide one taking a row.
        rows, row = [], []
        for i in idx:
            if i in wide:
                if row:
                    rows.append(row)
                rows.append([i])
                row = []
                continue
            row.append(i)
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        nrows = max(2, len(rows))
        rh = (H - top - bottom) / nrows
        body = []
        if p == 0:
            body.append(f'<h1 class="title">{_esc(build.title)}</h1>')
        for r, row in enumerate(rows):
            y = top + r * rh
            if r:
                body.append(f'<div class="hrule" style="left:{gut}px;'
                            f'right:{gut}px;top:{y:.0f}px"></div>')
            full = len(row) == 1 and row[0] in wide
            cw = (W - 2 * gut) / (1 if full else 2)
            if not full:
                body.append(f'<div class="vrule" style="left:{W / 2:.0f}px;'
                            f'top:{y + 4:.0f}px;height:{rh - 8:.0f}px"></div>')
            for c, i in enumerate(row):
                x = gut + c * cw
                # The title sits over the first step, as the original's does.
                dy = 52 if (p == 0 and r == 0 and c == 0) else 0
                if i == -1:
                    body.append(f'<figure class="art" style="left:{x + 8:.0f}px;'
                                f'top:{y + 12:.0f}px;width:{cw - 16:.0f}px;'
                                f'height:{rh - 22:.0f}px">{build.hero_svg()}'
                                '</figure>')
                    continue
                body.append(_letter_cell(build, i, n, svgs[i], insets[i],
                                         x + 8, y + 12 + dy, cw - 16,
                                         rh - 22 - dy))
        body.append('<div class="foot" aria-hidden="true"></div>')
        pages.append(f'<section class="page">{"".join(body)}</section>')
    return pages


def _letter_cell(build, i, n, svg, inset, x, y, w, h):
    step = build.steps[i]
    number = i + 1
    items = []
    # A step that puts pieces together shows each piece, as it stands,
    # with no count or name - as the letter guides do.
    for pls in step.pieces or ():
        icon = render_module_icon(pls, view_rot=build._rot_for(step),
                                  box_px=66.0)
        items.append(f'<div class="it piece"><span class="ic">{icon}</span>'
                     '</div>')
    for (name, color), qty in _sorted(step.part_counts(times=True)):
        num = part_number(name) or get(name, color).label
        items.append(f'<div class="it"><span class="q">{qty}x</span>'
                     f'<span class="ic">'
                     f'{_icon(name, color, 84.0, parts._detail, True)}'
                     f'</span><span class="pn">{_esc(num)}</span></div>')
    if step.module and not step.pieces:
        name, placements = step.module
        icon = render_module_icon(placements, view_rot=build._rot_for(step),
                                  box_px=60.0)
        items.append(f'<div class="it"><span class="q">1x</span>'
                     f'<span class="ic">{icon}</span>'
                     f'<span class="pn">{_esc(name)}</span></div>')
    last = number == n
    badge = (f'<span class="badge">{_burst()}'
             + (_flag("l") + _flag("r") if last else "")
             + f"<b>{number}</b></span>")
    box_h = 92 if items else 0
    box = (f'<div class="box" style="height:{box_h}px">'
           f'{_scallop(w - 8, box_h)}{"".join(items)}</div>'
           if items else "")
    art_top = 44 + box_h + 4
    # As big as the cell allows, held to its top left, so the small
    # finished view fits in the corner the drawing leaves.
    svg = svg.replace("<svg ", '<svg preserveAspectRatio="xMinYMin meet" ', 1)
    art = (f'<figure class="art" style="left:0;top:{art_top}px;'
           f'right:0;bottom:0">{svg}</figure>')
    ins = f'<div class="inset">{inset}</div>' if inset else ""
    return (f'<div class="cell" id="step-{number}" style="left:{x:.0f}px;'
            f'top:{y:.0f}px;width:{w:.0f}px;height:{h:.0f}px">'
            f"{_words(number, step, n)}{badge}{box}{art}{ins}</div>")


# -------------------------------------------------------------- landscape


def _landscape(build, hero):
    n = len(build.steps)
    svgs = [svg for _, _, svg in build.step_svgs()]
    done = build.step_insets(full=True)
    turns = _turns(build, camera=False)
    pages = [_landscape_cover(build, hero)] + _landscape_inventory(build)
    W = 816
    for idx in _paginate(build, 3):
        counts = Counter()
        modules = []
        for i in idx:
            counts.update(build.steps[i].part_counts(times=True))
            if build.steps[i].module:
                modules.append(build.steps[i])
        strip = []
        for (name, color), qty in _sorted(counts):
            tag = size_label(name)
            strip.append(
                '<div class="it"><span class="ic">'
                f'{_icon(name, color, 84.0, parts._detail)}</span>'
                + (f'<span class="tag">{_esc(tag)}</span>' if tag else "")
                + f'<span class="q">x{qty}</span></div>')
        for step in modules:
            name, placements = step.module
            icon = render_module_icon(placements, view_rot=build._rot_for(step),
                                      box_px=70.0)
            strip.append(f'<div class="it"><span class="ic">{icon}</span>'
                         f'<span class="q">x1</span></div>')
        body = [f'<div class="strip">{"".join(strip)}</div>'] if strip else []
        # Columns across the page; a step marked `under` shares the column
        # of the one before it, the two stacked.
        cols = []
        for i in idx:
            if cols and build.steps[i].under:
                cols[-1].append(i)
            else:
                cols.append([i])
        cw = (W - 28) / len(cols)
        top, bottom = 96, 552 - 26
        for c, col in enumerate(cols):
            x = 14 + c * cw
            if c:
                body.append(f'<div class="vrule" style="left:{x:.0f}px"></div>')
            rh = (bottom - top) / len(col)
            for r, i in enumerate(col):
                y = top + r * rh
                if r:
                    body.append(f'<div class="hrule" style="left:{x + 6:.0f}px;'
                                f'width:{cw - 12:.0f}px;top:{y:.0f}px"></div>')
                body.append(_landscape_col(build, i, n, svgs[i], done[i],
                                           turns[i], x + 6, cw - 12, y + 2,
                                           rh - 4))
        body.append(f'<div class="foot" aria-hidden="true">{len(pages) + 1}'
                    '</div>')
        pages.append(f'<section class="page">{"".join(body)}</section>')
    return pages


def _landscape_col(build, i, n, svg, done, turn, x, w, y, h):
    step = build.steps[i]
    number = i + 1
    badge = f'<span class="badge">{_cog()}<b>{number}</b></span>'
    extra = ""
    if step.times > 1:
        extra = f'<span class="times">{step.times}X</span>'
    elif turn:
        extra = _turn_icon()
    if done:
        # Pulled apart above and to the left, finished below and to the
        # right, the two overlapping a little as the guides draw them.
        art = (f'<figure class="art" style="left:0;top:34px;width:78%;'
               f'height:58%">{svg}</figure>'
               f'<figure class="art" style="right:0;bottom:0;width:70%;'
               f'height:50%">{done}</figure>')
    else:
        art = (f'<figure class="art" style="left:0;top:34px;right:0;'
               f'bottom:0">{svg}</figure>')
    return (f'<div class="col" id="step-{number}" style="left:{x:.0f}px;'
            f'width:{w:.0f}px;top:{y:.0f}px;height:{h:.0f}px">'
            f'{_words(number, step, n)}{badge}{extra}{art}</div>')


def _landscape_cover(build, hero):
    pic = build.hero_svg() if hero else ""
    return ('<section class="page cover">'
            f'<h1 class="ctitle">{_esc(build.title)}</h1>'
            f'<div class="hero">{pic}</div><div class="band"></div>'
            '</section>')


# The 2nd-gen guides list the parts over several pages, one kind of part to
# a page, each on a band of its own colour: motion, connectors, electronics,
# structure.
INV_GROUPS = (
    ("#d9e8c4", ("washer", "spacer", "collar", "lockbeam", "shaft", "capped",
                 "plastic", "motorshaft", "gear", "pulley", "hub", "tyre",
                 "wheel", "omni", "crankarm", "tractionlink", "string")),
    ("#bbe8d8", ("pin", "connector", "standoff", "standoffconn", "corner")),
    ("#f08a8a", ("motor", "brain", "battery", "cable", "touchled", "bumper",
                 "distance")),
    ("#fbd2b2", ("beam", "plate", "lbeam", "anglebeam")),
)
INV_ROWS = 7


def _landscape_inventory(build):
    inv = _sorted(build.inventory())
    groups = [[] for _ in INV_GROUPS]
    for item in inv:
        fam = item[0][0].partition("@")[0].split("_")[0]
        k = next((i for i, (_c, fams) in enumerate(INV_GROUPS) if fam in fams),
                 len(INV_GROUPS) - 1)
        if item[0][0] == "lockbeam_1x3":
            k = len(INV_GROUPS) - 1
        groups[k].append(item)
    pages = []
    for (band, _fams), items in zip(INV_GROUPS, groups):
        for j in range(0, len(items), INV_ROWS):
            rows = []
            for (name, color), qty in items[j:j + INV_ROWS]:
                part = get(name, color)
                tag = size_label(name)
                rows.append(
                    f'<div class="it" style="background:{band}">'
                    f'<span class="q">{qty}x</span><span class="pname">'
                    + (f'<span class="tag in">{_esc(tag)}</span>' if tag else "")
                    + f'{_esc(part.label)}</span><span class="ic">'
                    f'{_icon(name, color, 150.0, parts._detail)}</span></div>')
            pages.append(f'<section class="page"><div class="inv">'
                         f'{"".join(rows)}</div><div class="foot" '
                         f'aria-hidden="true">{len(pages) + 2}</div></section>')
    return pages


# ----------------------------------------------------------------- slides


def _slides(build, hero):
    n = len(build.steps)
    svgs = [svg for _, _, svg in build.step_svgs()]
    insets = build.step_insets(px=180.0)
    turns = _turns(build)
    pages = []
    if hero:
        pages.append('<section class="page cover">'
                     f'<h1 class="ctitle">{_esc(build.title)}</h1>'
                     f'<div class="hero">{build.hero_svg()}</div></section>')
    for i, step in enumerate(build.steps):
        number = i + 1
        items = []
        for (name, color), qty in _sorted(step.part_counts(times=True)):
            label = get(name, color).label
            items.append(f'<div class="it"><span class="ic">'
                         f'{_icon(name, color, 120.0, parts._detail)}</span>'
                         f'<span class="nm"><b>{qty}x</b> - {_esc(label)}'
                         '</span></div>')
        if step.module:
            name, placements = step.module
            icon = render_module_icon(placements, view_rot=build._rot_for(step),
                                      box_px=60.0)
            items.append(f'<div class="it"><span class="ic">{icon}</span>'
                         f'<span class="nm"><b>1x</b> - {_esc(name)}</span>'
                         '</div>')
        last = number == n
        badge = (f'<span class="badge">{_burst(12)}'
                 + (_flag("l") + _flag("r") if last else "")
                 + f"<b>{number}</b></span>")
        extra = (f'<span class="times">{step.times}X</span>'
                 if step.times > 1 else (_turn_icon() if turns[i] else ""))
        strip = f'<div class="strip">{"".join(items)}</div>' if items else ""
        top = 150 if items else 40
        art = (f'<figure class="art" style="left:150px;right:150px;top:{top}px;'
               f'bottom:14px">{svgs[i]}</figure>')
        ins = f'<div class="inset">{insets[i]}</div>' if insets[i] else ""
        pages.append(f'<section class="page" id="step-{number}">'
                     f"{_words(number, step, n)}{badge}{extra}{strip}{art}{ins}"
                     "</section>")
    return pages


# ---------------------------------------------------------------- magikid


def _magikid(build, hero):
    n = len(build.steps)
    svgs = [svg for _, _, svg in build.step_svgs()]
    turns = [st.spin or st.turn is not None for st in build.steps]
    pages = []
    inv = []
    for (name, color), qty in _sorted(build.inventory()):
        inv.append(f'<div class="it"><span class="ic">'
                   f'{_icon(name, color, 230.0, parts._detail)}</span>'
                   f'<span class="q">{qty}x</span></div>')
    pages.append(f'<section class="page"><div class="inv">{"".join(inv)}</div>'
                 "</section>")
    for i, step in enumerate(build.steps):
        number = i + 1
        items = []
        for (name, color), qty in _sorted(step.part_counts(times=True)):
            items.append(f'<div class="it"><span class="ic">'
                         f'{_icon(name, color, 150.0, parts._detail)}</span>'
                         f'<span class="q">{qty}x</span></div>')
        # Magikid lists a module's parts, not a picture of the module.
        box = f'<div class="box">{"".join(items)}</div>' if items else ""
        # Held to the bottom of the page, clear of the parts box at the top
        # right, as Magikid's pages place it.
        svg = svgs[i].replace("<svg ", '<svg preserveAspectRatio="xMidYMax '
                              'meet" ', 1)
        art = ('<figure class="art" style="left:30px;right:30px;top:150px;'
               f'bottom:20px">{svg}</figure>')
        # Magikid marks a turn with a small blue box of two arrows.
        spin = (_turn_icon().replace('class="turn-icon"',
                                     'class="turn-icon mk"')
                .replace("#f26b21", "#2b6fc2") if turns[i] else "")
        pages.append(f'<section class="page" id="step-{number}">'
                     f'{_words(number, step, n)}'
                     f'<p class="num" aria-hidden="true">{number}</p>'
                     f"{box}{art}{spin}</section>")
    return pages


_LAYOUTS = {"letter": _letter, "landscape": _landscape, "slides": _slides,
            "magikid": _magikid}


def _inv_sort(item):
    """Group the parts list the way a kit tray is laid out."""
    order = ["beam", "plate", "lbeam", "anglebeam", "lockbeam", "corner",
             "connector", "pin", "standoff", "standoffconn", "shaft",
             "plastic", "capped", "motorshaft", "collar", "spacer", "washer",
             "gear", "pulley", "hub", "tyre", "wheel", "omni", "motor",
             "brain", "battery", "cable", "bumper", "distance", "band"]
    name = item[0][0]
    family = name.split("_")[0]
    idx = order.index(family) if family in order else len(order)
    return (idx, name)
