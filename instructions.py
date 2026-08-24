"""
Turns a Build into a printable / projectable instruction booklet.

One self-contained HTML file: inline CSS, inline SVG, no fonts or scripts to
fetch.  It prints straight from a browser and projects legibly from the back
of a classroom.
"""

from __future__ import annotations

import html
from collections import Counter

from .parts import get
from .render import Styles, render_part_icon

CSS = """
*{box-sizing:border-box}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact}

/* One palette, named once. Dark mode and print both work by moving these
   handful of values rather than by restating the whole stylesheet. */
:root{
  --page:#eef0f3; --card:#fff; --ink:#171b21; --ink-2:#39414e; --ink-3:#4f5766;
  --chip:#f6f7f9; --line:#e5e8ec; --rule:#eceef1; --accent:#96421c;
  --plate:transparent; --shadow:0 1px 3px rgba(20,26,36,.14);
}

body{margin:0;background:var(--page);color:var(--ink);
  font:16px/1.6 "Segoe UI",Roboto,-apple-system,"Helvetica Neue",Arial,sans-serif;
  text-align:left}
.sheet{max-width:1080px;margin:0 auto;padding:28px 22px 60px}

/* Visually hidden, still read aloud. Used where the page shows something as
   position or colour and a screen reader needs it as a word. */
.vh{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;
  clip:rect(0 0 0 0);clip-path:inset(50%);white-space:nowrap;border:0}

a{color:#0b5fa5}
:focus-visible{outline:3px solid #0b5fa5;outline-offset:2px}

.cover{background:var(--card);border-radius:14px;padding:38px 40px 32px;
  box-shadow:var(--shadow);margin-bottom:26px}
.cover h1{margin:0;font-size:40px;line-height:1.15;letter-spacing:-.02em}
.cover .sub{margin:8px 0 0;font-size:19px;color:var(--ink-3);font-weight:500}
.cover .intro{margin:18px 0 0;max-width:60ch;color:var(--ink-2)}
.hero{margin:26px 0 8px;text-align:center}
.hero svg{max-width:100%;height:auto;background:var(--plate);border-radius:10px}

/* The shape of the build, before any of it: how many steps, how many parts,
   and how you know you have finished. */
.shape{margin:20px 0 0;padding:14px 18px;background:var(--chip);
  border:1px solid var(--line);border-left:4px solid var(--accent);
  border-radius:8px;max-width:60ch}
.shape p{margin:0;color:var(--ink-2)}
.shape p+p{margin-top:6px}
.shape b{color:var(--ink)}

.inv{margin-top:26px;border-top:2px solid #e3e6ea;padding-top:20px}
.inv h2{margin:0 0 14px;font-size:15px;text-transform:uppercase;
  letter-spacing:.09em;color:var(--ink-3)}
.inv ul{list-style:none;margin:0;padding:0;display:grid;gap:8px 18px;
  grid-template-columns:repeat(auto-fill,minmax(215px,1fr))}
.inv li{display:flex;align-items:center;gap:10px;background:var(--chip);
  border:1px solid var(--line);border-radius:8px;padding:7px 11px}

/* The build broken into named parts, on the cover. A job of unknown shape
   becomes a job with four things in it that finish. */
.contents{margin:26px 0 0;padding:18px 20px;background:var(--chip);
  border:1px solid var(--line);border-radius:10px}
.contents h2{margin:0 0 10px;font-size:13px;font-weight:700;
  text-transform:uppercase;letter-spacing:.09em;color:var(--ink-3)}
.contents ol{list-style:none;margin:0;padding:0}
.contents li{display:flex;gap:12px;align-items:baseline;padding:5px 0;
  border-top:1px solid var(--rule)}
.contents li:first-child{border-top:0}
.c-num{flex:none;width:22px;height:22px;border-radius:50%;background:var(--ink);
  color:var(--card);font-size:12px;font-weight:700;display:flex;
  align-items:center;justify-content:center;align-self:center}
.c-title{flex:1 1 auto;font-weight:600}
.c-steps{flex:none;font-size:14px;color:var(--ink-3)}

/* What a section needs, gathered before it starts, so following it is not
   interrupted by a trip to the tray on every step. */
.section-parts{margin:0 0 18px;padding:14px 18px;background:var(--card);
  border:1px solid var(--line);border-radius:10px;break-inside:avoid;
  box-shadow:var(--shadow)}
.section-parts h3{margin:0 0 9px;font-size:12px;font-weight:700;
  text-transform:uppercase;letter-spacing:.08em;color:var(--ink-3)}
.section-parts ul{list-style:none;margin:0;padding:0;display:flex;
  flex-wrap:wrap;gap:8px}
.section-parts li{flex:0 0 auto;display:flex;align-items:center;gap:10px;
  background:var(--chip);border:1px solid var(--line);border-radius:8px;
  padding:7px 11px}

/* A named chunk of the build. Carries its own length so the end of it is
   visible from the start, and starts a fresh page when printed - a section
   that straddles a page break is the one place a reader loses their spot. */
.section-head{margin:34px 0 18px;padding:0 0 0 16px;border-left:5px solid var(--accent);
  break-after:avoid;page-break-after:avoid}
.section-head:first-of-type{margin-top:6px}
.section-kicker{margin:0;font-size:12px;font-weight:700;text-transform:uppercase;
  letter-spacing:.09em;color:var(--ink-3)}
.section-head h2{margin:2px 0 0;font-size:26px;line-height:1.2}
.section-len{margin:3px 0 0;font-size:14px;font-weight:600;color:var(--ink-3)}
.section-note{margin:8px 0 0;font-size:16px;color:var(--ink-2);max-width:60ch}

.steps{list-style:none;margin:0;padding:0;counter-reset:none}
/* A robot-sized booklet is a few hundred thousand SVG elements, and laying
   out all of them before showing any is most of what makes a big one slow to
   open. `content-visibility` lets the browser skip the steps that are off
   screen until they are scrolled to; `contain-intrinsic-size` gives it a
   stand-in height meanwhile, so the scrollbar does not jump about. Printing
   turns it back off - every step has to be laid out to go on paper. */
.step{background:var(--card);border-radius:14px;margin-bottom:22px;overflow:hidden;
  box-shadow:var(--shadow);break-inside:avoid;page-break-inside:avoid;
  content-visibility:auto;contain-intrinsic-size:auto 880px}
.step-bar{display:flex;gap:16px;align-items:flex-start;padding:20px 26px 16px;
  border-bottom:1px solid var(--rule)}
.step-num{flex:none;width:44px;height:44px;border-radius:50%;background:var(--ink);
  color:var(--card);font-size:21px;font-weight:700;display:flex;align-items:center;
  justify-content:center}
.step-text{flex:1 1 auto;min-width:0}
/* Where you are, in words, on every step - not only as a badge you have to
   count against the pile of paper. */
.eyebrow{margin:0;font-size:12px;font-weight:700;text-transform:uppercase;
  letter-spacing:.09em;color:var(--ink-3)}
.eyebrow .of{font-weight:600}
.note{margin:5px 0 0;font-size:19px;font-weight:600;line-height:1.4}
.caption{margin:6px 0 0;color:var(--ink-3);font-size:15px}
.turn{margin:7px 0 0;font-size:13px;font-weight:700;color:var(--accent);
  text-transform:uppercase;letter-spacing:.05em}

/* A box to tick. Progress on a long build has to be visible without holding
   it in your head, and it has to survive being printed. */
.done{flex:none;display:flex;align-items:center;gap:7px;padding-top:4px;
  font-size:12px;color:var(--ink-3);cursor:pointer}
.done input{width:22px;height:22px;accent-color:#0b5fa5;margin:0;cursor:pointer}

.step-body{display:grid;grid-template-columns:236px 1fr;gap:4px;align-items:start}
.step-body.wide{grid-template-columns:1fr}
.step-body.wide .art{padding:10px 26px 26px}
.parts{padding:18px 12px 20px 26px}
.parts h3{margin:0 0 11px;font-size:12px;text-transform:uppercase;
  letter-spacing:.09em;color:var(--ink-3);font-weight:700}
.parts ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:7px}
.parts li{display:flex;align-items:center;gap:9px;background:var(--chip);
  border:1px solid var(--line);border-radius:8px;padding:6px 9px}
.icon{flex:none;width:46px;display:flex;align-items:center;justify-content:center}
.icon svg{max-width:46px;height:auto;background:var(--plate);border-radius:4px}
.qty{flex:none;font-weight:700;font-size:15px;min-width:26px}
.pname{font-size:13.5px;line-height:1.3;color:var(--ink-2)}
.art{margin:0;padding:10px 26px 26px 10px;text-align:center}
.art svg{max-width:100%;height:auto;background:var(--plate);border-radius:10px}

footer{color:var(--ink-3);font-size:13px;text-align:center;padding:8px 0 0}

@media (max-width:760px){.step-body{grid-template-columns:1fr}
  .parts{padding:18px 22px 4px}
  .parts ul{flex-direction:row;flex-wrap:wrap}
  .art{padding:10px 18px 22px}
  .cover{padding:26px 22px 24px}
  .cover h1{font-size:30px}}

/* Dark mode for screen reading. The drawings assume a pale background - a
   black beam on a black page is not a drawing - so they keep a white plate
   under them while the chrome around them goes dark. */
@media screen and (prefers-color-scheme:dark){
  :root{
    --page:#15181d; --card:#1e232a; --ink:#eef1f5; --ink-2:#c3cad4;
    --ink-3:#a2acba; --chip:#252b34; --line:#333b46; --rule:#2c333d;
    --accent:#f0996b; --plate:#fff; --shadow:0 1px 3px rgba(0,0,0,.5);
  }
  .inv{border-top-color:var(--line)}
  .step-num{background:#0b5fa5;color:#fff}
  a{color:#7cc0ff}
  :focus-visible{outline-color:#7cc0ff}
}

@media print{
  :root{
    --page:#fff; --card:#fff; --ink:#000; --ink-2:#222; --ink-3:#333;
    --chip:#fff; --line:#bbb; --rule:#bbb; --accent:#7a3416;
    --plate:transparent; --shadow:none;
  }
  body{background:#fff}
  .sheet{max-width:none;padding:0}
  .cover,.step{box-shadow:none;border:1px solid #bbb;margin-bottom:14px}
  .step{break-inside:avoid;content-visibility:visible}
  .section-head{break-before:page;page-break-before:always;margin:0 0 14px}
  .section-head:first-of-type{break-before:auto;page-break-before:auto}
  .done{color:#000}
  footer{display:none}
  @page{margin:12mm}
}
"""


def _esc(s):
    return html.escape(s or "")


def _part_row(name, color, qty, styles):
    part = get(name, color)
    # The icon sits beside the part's own name, so it is decorative - marking
    # it as an image would make a screen reader announce every row twice.
    icon = render_part_icon(name, color, styles=styles)
    return (
        f'<li><span class="icon">{icon}</span>'
        f'<span class="qty"><span class="vh">Quantity </span>{qty}&times;</span>'
        f'<span class="pname">{_esc(part.label)}</span></li>'
    )


def _contents(build):
    """
    The build broken into its named parts, on the cover.

    Six sections listed by name, each with the steps it covers, is the
    difference between a job of unknown shape and a job with four things in
    it that finish.  A build with no sections has nothing to list.
    """
    runs = [(sec, lo, hi) for sec, lo, hi in build.section_runs() if sec]
    if not runs:
        return ""
    rows = []
    for n, (section, lo, hi) in enumerate(runs, start=1):
        span = (f"step {lo + 1}" if hi - lo == 1
                else f"steps {lo + 1}&ndash;{hi}")
        rows.append(
            f'<li><span class="c-num" aria-hidden="true">{n}</span>'
            f'<span class="c-title">{_esc(section.title)}</span>'
            f'<span class="c-steps">{span}</span></li>'
        )
    return ('<div class="contents"><h2>What you will build</h2>'
            f'<ol>{"".join(rows)}</ol></div>')


def _section_parts(build, lo, hi, styles):
    """Everything a section needs, so it can be fetched once at the start."""
    total = Counter()
    for step in build.steps[lo:hi]:
        total.update(step.part_counts())
    if not total:
        return ""
    chips = "".join(_part_row(name, color, qty, styles)
                    for (name, color), qty in sorted(total.items(),
                                                     key=_inv_sort))
    return ('<div class="section-parts"><h3>Fetch these before you start</h3>'
            f"<ul>{chips}</ul></div>")


def booklet(build, hero=True):
    """Render a complete Build to a standalone HTML document."""
    parts_out = []
    # One stylesheet for every drawing in the document.  The same few hundred
    # shades recur in every step, the hero and every parts icon; naming them
    # once here rather than per-SVG is most of why the file is the size it is.
    styles = Styles()

    inv = build.inventory()
    n_steps = len(build.steps)
    n_parts = sum(inv.values())
    inv_rows = "".join(
        _part_row(name, color, qty, styles)
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
    # The shape of the job before any of it: how long, and how you know you
    # have finished.  A reader who cannot see the end of a task from the start
    # of it spends capacity predicting instead of building.
    shape = [
        '<div class="shape">',
        f"<p><b>{n_steps} steps</b>, <b>{n_parts} parts</b>. "
        "Each step shows only what to add, in full colour, "
        "with what you have already built faded behind it.</p>",
    ]
    if build.done:
        shape.append(f"<p><b>Finished when:</b> {_esc(build.done)}</p>")
    shape.append("</div>")
    cover.append("".join(shape))
    if hero:
        cover.append(f'<div class="hero">{build.hero_svg(styles=styles)}</div>')
    cover.append(_contents(build))
    cover += [
        '<div class="inv"><h2>Parts you will need</h2>',
        f"<ul>{inv_rows}</ul></div>",
        "</header>",
    ]
    parts_out.append("".join(cover))

    svgs = build.step_svgs(styles=styles)
    runs = build.runs()
    n_sections = sum(1 for lo, _ in runs if build.steps[lo].section)

    prev_angle = None
    for part_no, (lo, hi) in enumerate(runs, start=1):
        section = build.steps[lo].section
        if section:
            # The section says how long it is, so the reader can see the end
            # of this chunk from the start of it.  That is the same job the
            # cover's step count does for the build as a whole.
            n = hi - lo
            head = [
                '<div class="section-head">',
                f'<p class="section-kicker">Part {part_no} of {n_sections}</p>',
                f"<h2>{_esc(section.title)}</h2>",
                f'<p class="section-len">{n} step{"s" if n != 1 else ""}</p>',
            ]
            if section.note:
                head.append(f'<p class="section-note">{_esc(section.note)}</p>')
            head.append("</div>")
            head.append(_section_parts(build, lo, hi, styles))
            parts_out.append("".join(head))
        prev_angle, chunk = _steps_html(build, svgs[lo:hi], n_steps,
                                        styles, prev_angle)
        start = f' start="{lo + 1}"' if lo else ""
        parts_out.append(f'<ol class="steps"{start}>{chunk}</ol>')

    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_esc(build.title)}</title>"
        f"<style>{CSS}</style><style>{styles.css()}</style></head>"
        f'<body><main class="sheet">{"".join(parts_out)}'
        "<footer>Drawn with iqdraw &middot; VEX IQ (2nd gen) &middot; "
        "1 grid unit = 12.7&nbsp;mm</footer></main></body></html>"
    )


def _steps_html(build, svgs, n_steps, styles, prev_angle):
    """One run of steps as <li> elements, and the camera angle they end on."""
    steps_out = []
    for number, step, svg in svgs:
        rows = "".join(
            _part_row(name, color, qty, styles)
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
            body = (f'<div class="parts"><h3>Parts for this step</h3>'
                    f"<ul>{rows}</ul></div>"
                    f'<figure class="art">{svg}</figure>')
            body_cls = "step-body"
        else:
            body = f'<figure class="art">{svg}</figure>'
            body_cls = "step-body wide"
        steps_out.append(
            f'<li class="step" id="step-{number}">'
            f'<div class="step-bar">'
            f'<span class="step-num" aria-hidden="true">{number}</span>'
            f'<div class="step-text">'
            f'<h2 class="eyebrow">Step {number} '
            f'<span class="of">of {n_steps}</span></h2>'
            f"{turn}{note}{cap}</div>"
            f'<label class="done"><input type="checkbox">'
            f'<span class="vh">Mark step {number} done</span>'
            f'<span aria-hidden="true">done</span></label>'
            f"</div>"
            f'<div class="{body_cls}">{body}</div></li>'
        )
    return prev_angle, "".join(steps_out)


def _inv_sort(item):
    """Group the parts list the way a kit tray is laid out."""
    order = ["beam", "plate", "corner", "pin", "standoff", "shaft", "collar",
             "spacer", "washer", "gear", "wheel", "motor", "brain", "bumper",
             "distance", "battery", "band"]
    name = item[0][0]
    family = name.split("_")[0]
    idx = order.index(family) if family in order else len(order)
    return (idx, name)
