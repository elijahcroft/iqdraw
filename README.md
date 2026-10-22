# iqdraw

[![Tests](https://github.com/elijahcroft/iqdraw/actions/workflows/tests.yml/badge.svg)](https://github.com/elijahcroft/iqdraw/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)

Create printable, step-by-step VEX IQ (2nd generation) build instructions from
a small, readable Python specification.

**[Read a finished booklet, and four worked builds &rarr;](https://elijahcroft.github.io/iqdraw/)**

You describe a build as a list of parts at hole coordinates. It renders
isometric step-by-step diagrams and wraps them in a printable booklet with a
parts callout on every step — the shape of a real VEX build guide.

A build too big for one flat list is described as **modules** placed into a
frame — written once, placed twice, mirrored for the far side — and its
booklet is divided into named **sections**. See
[Building something bigger](#building-something-bigger).

IQDraw works offline with Python 3.9 or newer. Its renderer needs numpy; the
desktop installation includes CustomTkinter.

## Desktop app

Prefer buttons to terminal commands? Launch **IQDraw Studio** after installing:

```bash
iqdraw-gui
```

You can also use `iqdraw --gui`, or open a build immediately with
`iqdraw-gui examples/gear-train.py`. The desktop app includes bundled examples,
recent projects, step and inventory review, validation results, remembered
drawing options, source auto-reload, keyboard shortcuts, and HTML/SVG/PNG
output. Rendering stays responsive in the background and uses the same tested
path as the CLI.

It uses CustomTkinter for a modern, system-aware desktop interface. The normal
IQDraw installation includes it automatically; some minimal Linux systems may
also need their OS's `python3-tk` package. Build specs are Python programs, so
only open files you trust. Studio inspects a spec in a short-lived helper
process to keep its state out of the GUI, but that is not a security sandbox.

Homebrew installs Tk separately from Python. If a Homebrew-based environment
reports `No module named '_tkinter'`, install the matching formula—for example,
`brew install python-tk@3.14` for Homebrew Python 3.14—then try `iqdraw-gui`
again.

## Quick start

```bash
git clone https://github.com/elijahcroft/iqdraw.git
cd iqdraw
python3 -m pip install -e .
iqdraw examples/gear-train.py -o out/gear-train.html
```

Open `out/gear-train.html` in a browser; use Print to make a paper booklet or
PDF. To start your own build without copying boilerplate:

```bash
iqdraw --new examples/my-build.py
iqdraw examples/my-build.py
```

The starter file is intentionally short. Edit its steps, refresh the generated
HTML, and use the [coordinate model](#the-coordinate-model) when adding parts.
The complete [pinned frame](examples/pinned-frame.py),
[gear train](examples/gear-train.py), [drive base](examples/drive-base.py), and
[grabber arm](examples/grabber-arm.py) show progressively larger builds.

| option | what it does |
|---|---|
| `-o FILE` | where the HTML goes. Without it, next to the spec |
| `--svg-dir DIR` | also write one SVG per step |
| `--png` | also rasterise each step (needs `rsvg-convert`) |
| `--no-hero` | drop the finished-model image from the cover |
| `--new FILE` | create a starter build without overwriting an existing file |
| `--detail simple` | plainer geometry, about a quarter the file size |
| `--context-detail simple` | plainer geometry for the parts *already built*; the step's own parts keep full detail |
| `--check-only` | run the checks and report, drawing nothing |
| `--strict` | treat anything the checks find as an error |
| `--no-check` | skip the checks |

You can also run `python3 -m iqdraw` anywhere you would use the `iqdraw`
command. Contributors should start with [CONTRIBUTING.md](CONTRIBUTING.md);
`./run-tests.sh` runs the test suite.

---

## The coordinate model

This is the part to get right; everything else follows from it.

**One grid unit = one VEX IQ hole = 12.7 mm.** VEX publishes that every
structural part is a whole number of pitches, which is the only reason a plain
integer grid can describe real builds.

**Parts are placed by hole centre, not by corner.** A `beam_1x8` at `(0,0,0)`
has holes at `(0,0,0)` through `(7,0,0)`. A pin at `(3,0,0)` goes through that
beam's fourth hole. The pin and the hole share an address — no offset
arithmetic.

**Coordinates are 0-based.** Hole `2` in a spec is the third hole a student
counts along the beam. Write step notes in whichever convention you teach, but
keep the numbers in the spec 0-based.

**+z is up.** The camera is fixed on the `(+1,+1,+1)` diagonal and always looks
down at the model, so the underside of a build is never drawn.

### The vertical stack

Thicknesses are what trip people up. These are the numbers:

| | thickness | a part at `z` occupies |
|---|---|---|
| beam | 0.50 | `z-0.25` … `z+0.25` |
| plate | 0.25 | `z-0.125` … `z+0.125` |
| gear | 0.50 | `z-0.25` … `z+0.25` |
| `pin_1x1` | 1.00 long, centred | `z-0.5` … `z+0.5` |

So:

- a beam resting on another beam sits **0.5** higher
- the **top face** of a beam at `z` is at `z+0.25`
- a pin joining two stacked beams goes at their shared face — a beam at `z=0`
  and one at `z=0.5` meet at `z=0.25`, and a `pin_1x1` there reaches exactly
  0.25 into each

`examples/pinned-frame.py` is the worked example of this.

---

## Writing a build

A build spec is a Python file, so loops and named constants are available —
which matters, because "a pin in every hole along this beam" is one line.

```python
from iqdraw import Build

b = Build("My Build", subtitle="Unit 5 - Lesson 19", scale=38)

with b.step("Lay the base beam down flat.") as s:
    s.add("beam_2x12", (0, 0, 0))

with b.step("Pin the cross beam on.") as s:
    s.add("beam_1x7", (1, 0, 0.5), rot=(0, 0, 90))
    s.many("pin_1x1", [(1, y, 0.25) for y in (0, 1, 5, 6)], axis="z")
```

The CLI renders the first `Build` it finds at module level.

### What each step shows

- everything built so far, **washed out**, with this step's parts at **full
  colour** — so the new work is unmistakable
- a **parts callout** listing only what this step needs, with counts
- the parts going in **pulled back** along their `arrow`, with a thin green
  line to where each one lands, and a small inset of the step finished (see
  `arrow` below)
- a **"turn the model 90° to the left"** banner whenever the camera angle
  changes, so a reader never mistakes a new viewpoint for a changed build
- one frame shared by every step, sized to the finished model, so the build
  stays registered in place from page to page instead of jumping around

That last one is a deliberate trade: early steps sit in a lot of white space,
because the frame has to fit the finished model. Keeping the model registered
is worth more to someone following along than filling the page. On a build
long enough to need [sections](#sections) the trade stops paying, and the
frame is recomputed at each section instead.

### `step(note, view_rz=None, caption="")`

`note` is the instruction, `caption` the smaller line under it — good for the
thing students get wrong. `view_rz` spins the camera about the vertical axis
for that step only, when a joint is hidden from the default angle; the turn
banner is generated from it automatically.

A step that adds no parts is a "check your work" step: it redraws the model at
full colour with no parts callout.

### `s.add(part, at, rot=None, axis=None, color=None, qty=1, arrow=None, mirror=None)`

- `at` — hole coordinates of the part's first hole. Floats are fine.
- `axis` — `'x' | 'y' | 'z'`. Reorients parts built along +z: pins, shafts,
  standoffs, gears, wheels, collars, spacers.
- `rot` — extra rotation `(rx, ry, rz)` in degrees, applied X then Y then Z,
  *after* `axis`.
- `mirror` — `'x' | 'y' | 'z'`. Reflects the part, for the handed twin of a
  chiral one like a corner bracket. Applied *before* `axis`.
- `color` — a `PALETTE` name or any hex string, overriding the part default.
- `qty` — affects the parts callout only, for when one drawn part stands in
  for several.
- `arrow` — the way the part goes in. `True` means straight down; otherwise
  `'+x'`, `'-x'`, `'+y'`, `'-y'`, `'+z'`, `'-z'`, `'up'`, `'down'`.

`s.many(part, positions, **kw)` places the same part at several coordinates.

**Give an `arrow` to every part that pushes in or slides on.** The booklet is
drawn the way a printed VEX build guide is: each such part is pulled back
along its arrow, a green guide line runs from it to the hole it goes in, and
a small inset in the corner shows the step finished. "A shaft through holes
0, 2 and 6" asks a student to count along twenty identical holes; the pulled
back shaft and its line answer it at a glance. A part with no arrow is drawn
where it ends up.

Parts going the same way are pulled back together, and the ones sitting
further out are pulled further, so a collar that goes on after a wheel is
drawn in front of it. A new part with no arrow that sits outside the parts
going in, like the beam that pins are pushed through, is pulled back further
still so it does not hide them.

Parts put together off the model and pushed on as one piece, like a wheel
already pinned to its lock beam, take the same `arrow` and a shared
`group="..."` label, and are pulled back together without coming apart.

`Build(..., explode=False)` turns this off and draws flat red insertion
arrows instead, with every part in place.

---

## Building something bigger

Everything above describes a build as one flat list of absolute coordinates.
That is fine for six steps and stops working somewhere around fifteen, for
two reasons that have nothing to do with each other:

- **the spec stops being writable.** An arm that sits three holes forward and
  two holes up carries that offset by hand on every line, so moving the arm
  means editing all of them — and the far side of a symmetric robot is the
  near side with every `y` negated, typed out twice.
- **the booklet stops being followable.** Thirty steps as one undivided list
  asks a reader to hold their own place in it, and every drawing is framed on
  the finished robot, so the first steps are a thumbnail in a mostly empty
  page.

`Assembly` fixes the first. `section()` fixes the second.

`examples/drive-base.py` is the worked example of both, and
`examples/grabber-arm.py` — nineteen steps in eight sections, a shared
chassis, and a claw made of two mirrored fingers — is the one that uses
every part of this at once.

### Assemblies

An assembly is a module written at its own origin, as though it were the only
thing on the table. `b.place()` drops it into the build:

```python
from iqdraw import Assembly, Build

side = Assembly("Side Frame")

with side.step("Lay a 2x12 beam down flat.") as s:
    s.add("beam_2x12", (0, 0, 0))

with side.step("Push a shaft through hole 1 and hole 10.") as s:
    s.many("shaft_4", [(x, 0, 0) for x in (1, 10)], axis="y", arrow="+y")

b = Build("Drive Base")
b.place(side, at=(0, 5, 0))
b.place(side, at=(0, 0, 0), mirror="y")
```

The assembly's steps become the build's steps, with their notes, captions and
camera angles intact and only their coordinates moved. Placing does not
consume it — place it as many times as the robot has of that module.

**Assemblies nest.** An assembly places another assembly exactly the way a
build places one, so a claw is two fingers and a build is a chassis, an arm
and a claw:

```python
finger = Assembly("Claw Finger")
...

claw = Assembly("Claw")
claw.place(finger, at=(0, 0, 0))
claw.place(finger, at=(0, 5, 0), mirror="y", note="and now a second, mirrored")

b.place(claw, at=(-5, 0, 5.0), section="The claw")
```

Transforms compose all the way down, mirrors included — and two reflections
make a rotation, so mirroring a claw that already contains a mirrored finger
gives you back a correctly handed pair rather than two of the same hand.

### Sharing modules between builds

A build spec is an ordinary Python module and its own directory is on the
import path, so builds sitting beside each other can share:

```python
# examples/grabber-arm.py
from _modules import add_chassis
```

`examples/_modules.py` holds the rolling chassis that `drive-base.py` and
`grabber-arm.py` both stand on. Once two builds share a chassis, describing it
once is the same argument `Assembly` makes inside one file — two descriptions
of one chassis can drift apart, and one cannot. **A file whose name starts
with `_` is a library, not a build**, and nothing tries to render it.

### `b.place(assembly, at, rot=None, mirror=None, note=None, caption="", section=None)`

- `at` — where the assembly's own origin lands.
- `rot` — `(rx, ry, rz)` in degrees.
- `mirror` — `'x' | 'y' | 'z'`, reflecting the whole module.
- `note` — collapse the module to a **single step** with this instruction,
  instead of repeating all of its steps.
- `section` — convenience for calling `section()` first.

**`mirror` is not a rotation, and that is the whole point of it.** No rotation
turns a left side into a right side; only a reflection does. Insertion arrows
are reflected with the module, so a shaft that pushed out along `+y` on one
side pushes out along `-y` on the other, which is correct and is what a
student is looking at.

**Use `note` the second time you place a module.** It is what a real build
guide does — "build a second one, mirrored" beats eight steps the reader has
already followed once. A collapsed step drops its parts' own arrows, because
those answer *which way does this part go in*, and a step placing a finished
module is not asking that. Give the `place` call its own `arrow=` instead,
the way the finished module goes on, and the module is drawn pulled back
in one piece. Its callout shows the parts, an arrow, and the module they
make.

### Sections

```python
b.section("One side frame", "You will build a second one just like it.")
b.place(side, at=(0, 5, 0))

b.section("Joining the two sides")
with b.step("Lay a 1x8 beam across both rails.") as s:
    ...
```

A section is a named run of steps. In the booklet each one gets a heading, the
count of steps in it, and its optional note — so the end of a chunk is visible
from the start of it, the same job the cover's step count does for the build
as a whole. The heading sits above the section's first step, and the pages
run on without a break, the way a printed build guide runs its chapters.

Declaring sections also puts **a contents list on the cover**, naming every
section and the steps it covers. A job of unknown shape becomes a job with
eight things in it that finish.

Sections also change how the drawings are framed. **The frame is recomputed at
each section, over everything built up to the end of it**, instead of being
sized to the finished model throughout. Inside a section the model still holds
still from step to step — which is the thing worth having — but the first
steps of `drive-base.py` are drawn about 1.6× larger than they would be
otherwise, and the boundary where the frame changes is the one place the
reader is already being told to look.

Step numbering stays continuous: **Step 7 of 22** all the way through, never
restarting per section. One numbering scheme, so "step 7" said out loud means
one thing.

**A build that declares no sections renders exactly as it did before any of
this existed** — byte for byte. Sections are opt-in.

### `Build(...)` options

`title`, `subtitle` and `intro` fill the cover. `done` is one line saying how a
builder knows they have finished — it prints as a **Finished when:** box on the
cover, next to the step and part counts:

```python
b = Build(
    "Gear Ratio Demonstrator",
    subtitle="VEX IQ (2nd gen) - 12T / 36T / 60T train",
    done="turning the crank turns all three gears, with no free play",
)
```

Worth filling in. A task whose finish condition is unstated is a task some
students cannot start, and "it looks like the picture" is not one.

The rest are drawing controls: `scale` (pixels per hole, default 34), `view_rz`
(default camera spin), `highlight` (set `False` to draw every step in flat full
colour instead of washing out what is already built), `fade_old` (how far to
wash it, 0–1), and `context_detail`.

### `context_detail`

Every step redraws the whole model, so on a robot-sized build most of every
drawing is parts that are washed out on purpose. `context_detail="simple"`
draws those from the cheaper procedural shapes while the step's **own** parts
keep the official CAD meshes:

```python
b = Build("Drive Base", context_detail="simple")
```

It takes the ten-step `drive-base` booklet from 8.6 MB to 5.5 MB — 1.9× on the
step drawings themselves, with the rest being the cover image and the last
step. `--context-detail simple` does the same from the command line without
editing the spec.

It is **off by default**, because it changes what a reader sees: an
already-built beam is drawn as a plain beam with round holes rather than a
molded one. In practice that sharpens the step rather than costing anything —
the part the step is about is now the only detailed thing on the page — but
it is a visible change, so it is opt-in. A "check your work" step, which draws
everything at full colour, keeps full detail throughout; nothing on it is
background.

Every step shares one frame sized to the finished model, so the build does not
jump size from page to page.

---

## What the booklet does for the reader

One self-contained HTML file — no fonts, scripts or images to fetch, so it
opens on a school laptop with no internet and prints straight from the browser.

- **The shape of the job on the cover**: how many steps, how many parts, the
  `done` line, and — for a build with sections — the list of what it is built
  out of, all before any of the build itself.
- **"Step 3 of 6" on every step**, in words rather than only as a badge, so
  progress never has to be held in your head.
- **A box to tick** per step, which works on screen and survives printing.
- **The layout of a printed build guide**: letter pages of four steps,
  each with a blue step badge, a rounded parts callout above the drawing
  ("1x" over each part, its name under it), and a small inset of the step
  finished. A step with more to say than a quarter page holds takes the whole
  row, and so does the last one.
- **A described drawing.** Every diagram carries an `aria-label` naming what
  the step added, because the picture holds the half of the instruction the
  words leave out — which hole, which way round. Part icons sit beside their
  own names and are marked decorative, so nothing gets read out twice.
- **White pages in every theme.** In dark mode only the desk around the
  pages goes dark; the drawings assume a pale background, and a black beam on
  a black page is not a drawing.
- **Text contrast at WCAG AA or better** in both themes.

Distinctions never rest on hue alone — already-built parts are separated from
new ones by lightness, which survives a black-and-white printer.

---

## Parts

Sizes are parsed from the name, so any length works without editing the
catalogue.

| name | notes |
|---|---|
| `beam_WxL` | `beam_1x8`, `beam_2x12` — W holes across, L along |
| `plate_WxL` | `plate_4x8` — thinner than a beam |
| `corner_AxB` | L bracket, A holes along +x and B up +z |
| `pin_1x1` `pin_1x2` `pin_2x2` | connector pins, centred on their `at` |
| `shaft_N` | N pitch long, square 3.18 mm section |
| `capped_shaft_N` | plastic shaft with a round cap on its `-z` end, so it cannot pull through |
| `standoff_N` | N pitch long, runs `0`…`N` from `at` — sits **on** a face |
| `gear_N` | `gear_12` `gear_36` `gear_60`; official round lightening-hole patterns and raised hubs |
| `wheel_N` | N = travel per revolution in mm: `wheel_100`, `wheel_160`, `wheel_200`, `wheel_250`. Uses the matching 20 mm pulley, 44 mm hub, or 64 mm hub; diameter is `N/pi` |
| `collar` `spacer` `washer` | |
| `motor` `brain` `bumper` `distance` `battery` | |
| `band_N` | rubber band, drawn stretched over N pitch |

**Gear spacing is not guesswork.** VEX IQ gears share a module, so two gears
mesh when their shaft spacing equals the sum of their pitch radii, and a pitch
radius is `teeth/24` holes:

| pair | shafts apart |
|---|---|
| 12T + 36T | 2 |
| 12T + 60T | 3 |
| 36T + 36T | 3 |
| 36T + 60T | 4 |
| 60T + 60T | 5 |

### Adding a part

Write a builder in `parts.py` returning a `Part`, and add one line to
`_RULES`. The solid constructors in `geom.py` — `box`, `cylinder`, `extrude`,
`rounded_rect`, `along` — cover most shapes. Build it along **+z** so `axis:`
works on it.

---

## What is measured and what is guessed

At the top of `parts.py`, in one block:

**Official CAD geometry** — the bundled meshes for `beam_1x4`, `beam_1x7`,
`beam_1x8`, `beam_2x8`, `beam_2x12`, `gear_12`, `gear_36`, `gear_60`,
`pin_1x1`, `shaft_6`, `capped_shaft_2`, `standoff_4`, `collar` (the rubber
shaft collar) and `wheel_200` (tyre and hub) are generated from VEX
Robotics' published STEP models. Their molded ribs, recessed faces, bosses,
lightening slots, tooth profiles, and real through-holes are therefore not
artist's approximations. The meshes are compressed into `cadmesh.py`; using
IQ Draw does not require a CAD package.

Adding one does. `tools/iqdraw-cadmesh.py` reads a STEP file from VEX's
"VEX IQ All Parts" pack, moves it into iqdraw's frame, decimates it to a
triangle budget and prints the `_DATA` entry for `cadmesh.py`. Its docstring
has the command. It needs OpenCascade, which `uv run --with cadquery-ocp`
fetches into a throwaway environment, so nothing is installed. A part with a
mesh still needs its procedural form in `parts.py`, because `--detail simple`
uses it.

**Measured**, from VEX's own documentation and STEP files — 12.7 mm hole
pitch, the 3.18 mm square drive shaft (exactly ¼ pitch), and the wheel sizes,
which VEX gives as travel per revolution.

**Estimated** — beam and plate thickness, molded edge and hole chamfers, hole
and pin radius, and standoff width. These were chosen to look right on the
page, not measured with a caliper. They are safe to change; nothing else
depends on their values.

**Structural plastic is drawn the grey VEX's own build guides use.** The
base-kit beams are black, but molded ribs, recesses and holes vanish on black,
and the manuals students already follow draw them grey. The grey was sampled
from those manuals: a lit face lands on their `#959498`. Everything else
follows the VEX IQ (2nd gen) base-kit plastic, the colour a part actually is
when a student pulls it out of the tray:

| part | colour |
|---|---|
| beams, plates, corner connectors | build-guide grey (the kit's are black) |
| standoffs | black |
| connector pins | blue |
| gears | blue |
| shafts | zinc-plated steel |
| plastic shafts | black |
| tyres | black, drawn a shade lighter so the tread reads, on a light grey hub |
| shaft collars | black rubber |
| brain, motors, sensors | dark charcoal |

Every plastic family is also sold in other colours, so **check the table
against your own kit** — VEX has changed plastic colours between production
runs, and a wrong colour actively misleads a student. It is one table at the
top of `parts.py`, and any placement can override with `color:`. `color="black"`
on a beam gives the base-pack colour back.

**Every molded edge is outlined**, the way the build guides draw them. Outline
segments are sorted a millimetre toward the camera (`EDGE_BIAS` in `geom.py`).
At their true depth they lie exactly on the faces they outline, and those
faces' seam strokes painted them out, so the CAD detail read only as shading.

The electronics — brain, motor, sensors — are proportioned to be recognisable
at a glance, not dimensionally accurate. Replace those functions if you need
real dimensions.

---

## Checks

Every render runs a set of sanity checks first and prints anything it finds to
stderr. They do not stop the drawing — `--strict` makes them fatal,
`--check-only` runs them without drawing, `--no-check` skips them.

| check | fires when |
|---|---|
| `duplicate` | the same part is placed twice at the same coordinates |
| `overlap` | two beams or plates occupy the same space |
| `gear mesh` | a gear pair is close to meshing but not actually meshing |
| `stranded` | a part touches nothing else in the build |

```
examples/my-build.py: step 3: gear mesh: 12T and 36T are 3.00 holes apart
    but need 2 - close enough to look meshed on the page, too far to
    drive each other
```

**Every rule only fires on something a correct build cannot do**, and that is
the whole design. A checker that reports a working build gets switched off, and
then it catches nothing. It is why the overlap rule looks at beams and plates
only: pins through beams and shafts through gears are *meant* to interpenetrate,
so a general collision test would report the entire model. Adding a rule means
adding both tests — one build that trips it, one plausible build that must not.

Mistakes in the spec itself are reported against the line that caused them:

```
examples/my-build.py:42: unknown part 'beem_1x8' - did you mean 'beam'?
    s.add("beem_1x8", (0, 0, 0))
```

---

## Known limits

**The checks are narrow.** They catch the four mistakes above and nothing else.
There is still no general collision detection and no notion of whether a joint
would actually hold, so a spec can describe a build that cannot be assembled and
be drawn happily. The spec author is responsible for that — which is why the
demo builds keep their vertical arithmetic explicit and commented.

**Sizes are not validated against the real VEX catalogue.** Lengths are parsed
from the name, so `beam_1x9` draws a nine-hole beam whether or not VEX sells
one. That flexibility is deliberate, but it means a booklet can call for a part
nobody can find in the tray. Check part names against your own kit.

**Hidden surfaces are resolved by sorting, not by a depth buffer.** SVG has no
z-buffer, so parts are drawn back to front. That is exact for parts sitting
next to each other and approximate where they interpenetrate. Most of the work
in `geom.py` is keeping facets small enough that the sort stays right: beam
faces are built per hole cell, holes are true voids ringed with quads rather
than dark circles painted on a solid face, extrusion walls are banded
vertically, and long outlines are chopped before sorting. A small artefact can
still appear where a pin meets the rounded end of a beam.

**Output is large** — the six-step gear-train booklet is about 5 MB at the
default detail level, most of it true gear teeth and molded beam geometry. It
opens and prints normally.

Colours are interned as CSS classes and adjacent same-styled geometry is merged
into single paths, which roughly halves the file without changing a pixel. If
that is still too big — a slow connection, an email attachment — `--detail
simple` swaps the bundled CAD meshes for the procedural shapes underneath and
brings the same booklet to about 1.3 MB, noticeably plainer but perfectly
usable.

**Every official mesh adds to it.** Giving the pins, collars, wheels and
1x8/2x8 beams their CAD meshes roughly doubled the booklets that use them:
`rubber-band-car` went from 11 MB to 23 MB, and `pendulum` from 5 MB to 14 MB.
`--context-detail simple` takes them back to 12 MB and 9 MB, with each step's
own parts still in full CAD. Halving the triangle budgets was tried and
rejected: the tyre loses its tread, the hub breaks into shards and the beam
ends go ragged.

**And it grows with the build**, because every step redraws the whole model:
the nineteen-step `grabber-arm` booklet is 11 MB and the ten-step `drive-base`
one is 8.2 MB, or 5.2 MB with `--context-detail simple`, or 3.2 MB with
`--detail simple`. Roughly, reckon on half a megabyte per step once a build is
robot-sized. Those files open and print, but a forty-step build is the point
where one of those flags stops being optional.

**Opening one is as much layout as it is bytes.** A robot-sized booklet is a
few hundred thousand SVG elements, and laying out every one of them before
showing anything is most of what makes a big one slow. Two things address it,
and neither changes a pixel:

- **the pages are `content-visibility: auto`**, so the browser skips laying
  out the ones off screen until they are scrolled to, with a stand-in height
  meanwhile so the scrollbar behaves. Printing turns it back off, because
  every page has to be laid out to reach paper.
- **coordinates are relative and tersely separated** (see below).

Together those took `grabber-arm` from 13 MB and 1.9 s to open, to 11 MB and
1.3 s — 15% smaller and about a third faster, with the rendered pages
byte-for-byte the same drawing.

**Sharing geometry between steps does not help, and this is measured.** The
obvious fix — define each shape once, `<use>` it from every step — was tried
and rejected: 19,815 of the 19,817 path strings in a `drive-base` step are
unique, because every primitive sits at its own absolute position, so there is
nothing to share *within* a step. Sharing across steps is real, but a
`<use href=… class=…>` reference costs about 38 bytes against a mean `d`
string of 32, so pointing at the geometry costs roughly what inlining it does.
End to end it came out at 6.6 MB against 5.7 MB — 14%, for a renderer rewrite
and a dependency on `<use>` surviving the print path. Don't spend the effort
again without re-measuring those two numbers first.

The two things that do work are **drawing less** — `--context-detail`, below —
and **spelling the same drawing more briefly**, which is what the path encoding
does.

### How coordinates are spelled

A facet is emitted as one absolute move followed by relative linetos, and a
minus sign is allowed to separate two numbers on its own:

```
M412,275l3.2,4.1-2.2,1.9-2-3.5z
```

Neighbouring vertices are a pixel or two apart, so the deltas between them are
one or two digits where the absolute coordinates are four or five, and roughly
half of them are negative and so cost no separator at all. It is worth about
15% of a booklet, losslessly.

Two details are load-bearing:

- **absolute positions are rounded before the deltas are taken**, so the
  points reconstruct to exactly the rounded coordinates instead of
  accumulating a rounding drift along a long outline.
- **each subpath starts with an absolute `M`**, which is what keeps
  `_emit`'s merging of adjacent same-styled paths safe.

`render.PRECISION` is how many decimal places survive, and it is `1` — a tenth
of a pixel. Dropping it to `0` takes another 20% off, and in the one build
checked it was hard to tell apart on screen and on paper, but it is no longer
lossless and moves every vertex by up to half a pixel. It is a constant rather
than a flag because it should be a considered decision, not a per-render one.

**One camera angle.** Everything is drawn from the same isometric viewpoint;
`view_rz` spins the model but cannot look from underneath.

---

## Check the render

The renderer is the only thing that knows whether a spec is right. After
writing or changing a build, rasterise it and *look*:

```bash
iqdraw examples/my-build.py -o out/x.html --svg-dir out/x-steps --png
```

Then open the PNGs. Coordinates that are one hole out, a part facing the wrong
way, a gear pair that does not mesh — all of it is obvious in the picture and
invisible in the spec.

---

## Converting a printed build manual

Printed Magikid and VEX manuals are pictures. The only text in
them is step numbers, part numbers and boilerplate, so nothing can be
extracted automatically. A conversion means reading the drawings and writing
the spec by hand.

1. **Render the manual large enough to count holes.** At 110 dpi the steps
   are readable, but counting holes on a beam takes a crop at 300 dpi:

   ```bash
   pdftoppm -r 300 -f 2 -l 2 -png "manual.pdf" /tmp/m
   magick /tmp/m-2.png -crop 1300x600+300+300 /tmp/callout.png
   ```

2. **Take part sizes from the callout icons, not the step drawings.** The
   icons are drawn flat, so the holes can be counted directly. The step
   drawings are foreshortened, so lengths read off them come out wrong.
3. **Fix the axes before writing any step.** Choose them so the finished
   model faces the camera on the `(+1,+1,+1)` diagonal. Anything that stands
   up is drawn standing up, even if students build it flat on the table.
   iqdraw cannot turn the model over halfway through a build.
4. **Map each manual section to `section()`, and a part built twice to
   an `Assembly`.** Place it the second time with `note=`. If the second copy
   differs (here the first stand gets standoffs and the second doesn't), the
   extra parts go in a build-level step, not in the assembly.
5. **Render, then compare every step's PNG with the matching page of the
   original.** Also compare the parts totals with the original's callouts.
   Fix things and re-render until both match.

Rotations that come up for upright parts, all checked in the pendulum:

| want | `rot=` |
|---|---|
| beam standing up, length along +z, width along +y | `(0, -90, 0)` |
| beam hanging down, length along -z | `(0, 90, 0)` |
| beam on its edge, length along +y, width along +z | `(90, 0, 90)` |

### VEX part numbers seen so far

The callouts print a part number and a count, but no name. The STEP pack
does name them (`2x8 Beam (228-2500-023).step`), so look a number up there
before guessing from the drawing.

| part number | iqdraw | |
|---|---|---|
| 228-2500-007 | `beam_1x8` | |
| 228-2500-023 | `beam_2x8` | |
| 228-2500-026 | `beam_2x12` | |
| 228-2500-060 | `pin_1x1` | |
| 228-2500-070 | `standoff_4` | |
| 228-2500-080 | `capped_shaft_2` | |
| 228-2500-122 | `shaft_6` | metal |
| 228-2500-143 | `collar` | rubber shaft collar, half a pitch thick |
| 228-2500-208 + 209 | `wheel_200` | 44 mm hub + 200 mm travel tyre, one part |

Every part in this table has an official mesh.

### Gaps found so far

- **Centre holes.** A 2-wide VEX IQ beam has a hole in the middle of each
  square of four, and the manuals use them. iqdraw only draws the regular
  grid. A part in a centre hole goes at a half-hole coordinate such as
  `y = 0.5`, and in the drawing it sits on plain plastic.
- **Real sizes move things.** With official meshes, parts are their true
  thickness: a rubber collar is 0.5 pitch, not the 0.36 the procedural one
  draws. Lay stacks out from those sizes, or parts that look fine plain
  will overlap once they are drawn in CAD.
- **No pulley, string, omni wheel, chain or track.** Draw the
  nearest part and say so in the step caption. Bigger builds will need these
  added to `parts.py` first.

---

## Licensing and the bundled CAD data

The source is MIT — see [LICENSE](LICENSE).

**The geometry in `cadmesh.py` is not.** Those meshes are derived from CAD
models published by VEX Robotics, and this project makes no claim over them.
Before publishing iqdraw anywhere with that file included, check what VEX's
terms actually permit — a permissive licence on the code does not extend to
data generated from someone else's models.

Two things make that a solvable problem rather than a blocker:

- every part has a procedural form, and `--detail simple` never touches the
  bundled meshes, so the tool is fully functional without them
- `cadmesh.py` is self-contained, so it can be dropped, replaced, or moved
  behind a separate download without touching anything else

"VEX" and "VEX IQ" are trademarks of Innovation First, Inc. This project is not
affiliated with, endorsed by, or sponsored by VEX Robotics or Innovation First.
