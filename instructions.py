"""
Turns a Build into a printable / projectable instruction booklet.

One self-contained HTML file: inline CSS, inline SVG, no fonts or scripts to
fetch.  It prints straight from a browser and projects legibly from the back
of a classroom.
"""

from __future__ import annotations

import html

from .parts import get
from .render import render_part_icon

CSS = """
*{box-sizing:border-box}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{margin:0;background:#eef0f3;color:#171b21;
  font:16px/1.5 "Segoe UI",Roboto,-apple-system,"Helvetica Neue",Arial,sans-serif}
.sheet{max-width:1080px;margin:0 auto;padding:28px 22px 60px}

.cover{background:#fff;border-radius:14px;padding:38px 40px 32px;
  box-shadow:0 1px 3px rgba(20,26,36,.14);margin-bottom:26px}
.cover h1{margin:0;font-size:40px;line-height:1.1;letter-spacing:-.02em}
.cover .sub{margin:8px 0 0;font-size:19px;color:#5b6473;font-weight:500}
.cover .intro{margin:18px 0 0;max-width:60ch;color:#39414e}
.hero{margin:26px 0 8px;text-align:center}
.hero svg{max-width:100%;height:auto}

.inv{margin-top:26px;border-top:2px solid #e3e6ea;padding-top:20px}
.inv h2{margin:0 0 14px;font-size:15px;text-transform:uppercase;
  letter-spacing:.09em;color:#5b6473}
.inv ul{list-style:none;margin:0;padding:0;display:grid;gap:8px 18px;
  grid-template-columns:repeat(auto-fill,minmax(215px,1fr))}
.inv li{display:flex;align-items:center;gap:10px;background:#f6f7f9;
  border:1px solid #e5e8ec;border-radius:8px;padding:7px 11px}

.step{background:#fff;border-radius:14px;margin-bottom:22px;overflow:hidden;
  box-shadow:0 1px 3px rgba(20,26,36,.14);break-inside:avoid;page-break-inside:avoid}
.step-bar{display:flex;gap:16px;align-items:flex-start;padding:20px 26px 16px;
  border-bottom:1px solid #eceef1}
.step-num{flex:none;width:44px;height:44px;border-radius:50%;background:#171b21;
  color:#fff;font-size:21px;font-weight:700;display:flex;align-items:center;
  justify-content:center}
.note{margin:9px 0 0;font-size:19px;font-weight:600;line-height:1.35}
.caption{margin:6px 0 0;color:#5b6473;font-size:15px}
.turn{margin:9px 0 0;font-size:13px;font-weight:700;color:#b0491f;
  text-transform:uppercase;letter-spacing:.05em}
.turn+.note{margin-top:3px}
.step-body{display:grid;grid-template-columns:236px 1fr;gap:4px;align-items:start}
.step-body.wide{grid-template-columns:1fr}
.step-body.wide .art{padding:10px 26px 26px}
.parts{padding:18px 12px 20px 26px}
.parts h4{margin:0 0 11px;font-size:12px;text-transform:uppercase;
  letter-spacing:.09em;color:#5b6473;font-weight:700}
.parts ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:7px}
.parts li{display:flex;align-items:center;gap:9px;background:#f6f7f9;
  border:1px solid #e5e8ec;border-radius:8px;padding:6px 9px}
.icon{flex:none;width:46px;display:flex;align-items:center;justify-content:center}
.icon svg{max-width:46px;height:auto}
.qty{flex:none;font-weight:700;font-size:15px;min-width:26px}
.pname{font-size:13.5px;line-height:1.25;color:#39414e}
.art{margin:0;padding:10px 26px 26px 10px;text-align:center}
.art svg{max-width:100%;height:auto}

footer{color:#79828f;font-size:13px;text-align:center;padding:8px 0 0}

@media (max-width:760px){.step-body{grid-template-columns:1fr}
  .parts{padding:18px 22px 4px}
  .parts ul{flex-direction:row;flex-wrap:wrap}
  .art{padding:10px 18px 22px}}

@media print{
  body{background:#fff}
  .sheet{max-width:none;padding:0}
  .cover,.step{box-shadow:none;border:1px solid #dfe3e8;margin-bottom:14px}
  .step{break-inside:avoid}
  footer{display:none}
  @page{margin:12mm}
}
"""


def _esc(s):
    return html.escape(s or "")


def _part_row(name, color, qty):
    part = get(name, color)
    icon = render_part_icon(name, color)
    return (
        f'<li><span class="icon">{icon}</span>'
        f'<span class="qty">{qty}&times;</span>'
        f'<span class="pname">{_esc(part.label)}</span></li>'
    )


def booklet(build, hero=True):
    """Render a complete Build to a standalone HTML document."""
    box = build.shared_box()
    parts_out = []

    inv = build.inventory()
    inv_rows = "".join(
        _part_row(name, color, qty)
        for (name, color), qty in sorted(inv.items(), key=_inv_sort)
    )

    cover = [
        '<header class="cover">',
        f"<h1>{_esc(build.title)}</h1>",
    ]
    if build.subtitle:
        cover.append(f'<p class="sub">{_esc(build.subtitle)}</p>')
    if build.intro:
        cover.append(f'<p class="intro">{_esc(build.intro)}</p>')
    if hero:
        cover.append(f'<div class="hero">{build.hero_svg()}</div>')
    cover += [
        '<div class="inv"><h2>Parts you will need</h2>',
        f"<ul>{inv_rows}</ul></div>",
        "</header>",
    ]
    parts_out.append("".join(cover))

    prev_angle = None
    for number, step, svg in build.step_svgs(box):
        rows = "".join(
            _part_row(name, color, qty)
            for (name, color), qty in sorted(step.part_counts().items(),
                                             key=_inv_sort)
        )
        # If the camera moved, say so. Otherwise the reader assumes the build
        # changed shape between steps rather than that they are looking at it
        # from a new side.
        angle = build.step_angle(step)
        turn = ""
        if prev_angle is not None and abs(angle - prev_angle) > 1e-6:
            delta = (angle - prev_angle + 180) % 360 - 180
            way = "left" if delta > 0 else "right"
            turn = (f'<p class="turn">&#8635; Turn the model '
                    f"{abs(delta):g}&deg; to the {way}</p>")
        prev_angle = angle
        note = f'<p class="note">{_esc(step.note)}</p>' if step.note else ""
        cap = f'<p class="caption">{_esc(step.caption)}</p>' if step.caption else ""
        # A step with no new parts gets no callout, and its drawing takes the
        # full width instead of leaving an empty column.
        if rows:
            body = (f'<div class="parts"><h4>Parts for this step</h4>'
                    f"<ul>{rows}</ul></div>"
                    f'<figure class="art">{svg}</figure>')
            body_cls = "step-body"
        else:
            body = f'<figure class="art">{svg}</figure>'
            body_cls = "step-body wide"
        parts_out.append(
            '<section class="step">'
            f'<div class="step-bar"><span class="step-num">{number}</span>'
            f'<div class="step-text">{turn}{note}{cap}</div></div>'
            f'<div class="{body_cls}">{body}</div></section>'
        )

    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_esc(build.title)}</title><style>{CSS}</style></head>"
        f'<body><div class="sheet">{"".join(parts_out)}'
        "<footer>Drawn with iqdraw &middot; VEX IQ (2nd gen) &middot; "
        "1 grid unit = 12.7&nbsp;mm</footer></div></body></html>"
    )


def _inv_sort(item):
    """Group the parts list the way a kit tray is laid out."""
    order = ["beam", "plate", "corner", "pin", "standoff", "shaft", "collar",
             "spacer", "washer", "gear", "wheel", "motor", "brain", "bumper",
             "distance", "battery", "band"]
    name = item[0][0]
    family = name.split("_")[0]
    idx = order.index(family) if family in order else len(order)
    return (idx, name)
