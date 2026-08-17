# iqdraw

VEX IQ (2nd gen) build instructions, drawn from a text spec.

You describe a build as a list of parts at hole coordinates. It renders
isometric step-by-step diagrams and wraps them in a printable booklet with a
parts callout on every step — the shape of a real VEX build guide.

No dependencies. Python 3 standard library only.

```bash
tools/iqdraw.sh builds/gear-train.py -o out/gear-train.html
```

Then open the HTML in a browser. Ctrl-P prints it.

Options: `--svg-dir DIR` writes one SVG per step, `--png` also rasterises them
(needs `rsvg-convert`), `--no-hero` drops the finished-model image from the
cover. Without `-o` the HTML lands next to the spec.

The wrapper just sets `PYTHONPATH` and calls the module, so this works too —
but only from the repo root:

```bash
PYTHONPATH=tools python3 -m iqdraw builds/gear-train.py -o out/gear-train.html
```

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
| gear | 0.40 body, hubs to ±0.40 | |
| `pin_1x1` | 1.00 long, centred | `z-0.5` … `z+0.5` |

So:

- a beam resting on another beam sits **0.5** higher
- the **top face** of a beam at `z` is at `z+0.25`
- a pin joining two stacked beams goes at their shared face — a beam at `z=0`
  and one at `z=0.5` meet at `z=0.25`, and a `pin_1x1` there reaches exactly
  0.25 into each

`builds/pinned-frame.py` is the worked example of this.

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
- **insertion arrows**, where you ask for them (see `arrow` below)
- a **"turn the model 90° to the left"** banner whenever the camera angle
  changes, so a reader never mistakes a new viewpoint for a changed build
- one frame shared by every step, sized to the finished model, so the build
  stays registered in place from page to page instead of jumping around

That last one is a deliberate trade: early steps sit in a lot of white space,
because the frame has to fit the finished model. Keeping the model registered
is worth more to someone following along than filling the page.

### `step(note, view_rz=None, caption="")`

`note` is the instruction, `caption` the smaller line under it — good for the
thing students get wrong. `view_rz` spins the camera about the vertical axis
for that step only, when a joint is hidden from the default angle; the turn
banner is generated from it automatically.

A step that adds no parts is a "check your work" step: it redraws the model at
full colour with no parts callout.

### `s.add(part, at, rot=None, axis=None, color=None, qty=1, arrow=None)`

- `at` — hole coordinates of the part's first hole. Floats are fine.
- `axis` — `'x' | 'y' | 'z'`. Reorients parts built along +z: pins, shafts,
  standoffs, gears, wheels, collars, spacers.
- `rot` — extra rotation `(rx, ry, rz)` in degrees, applied X then Y then Z,
  *after* `axis`.
- `color` — a `PALETTE` name or any hex string, overriding the part default.
- `qty` — affects the parts callout only, for when one drawn part stands in
  for several.
- `arrow` — draw an insertion arrow pointing the way the part goes in. `True`
  means straight down; otherwise `'+x'`, `'-x'`, `'+y'`, `'-y'`, `'+z'`,
  `'-z'`, `'up'`, `'down'`.

`s.many(part, positions, **kw)` places the same part at several coordinates.

**Use `arrow` whenever the step is "which hole?" rather than "which part?"**
"A shaft through holes 0, 2 and 6" asks a student to count along twenty
identical holes; three arrows answer it at a glance. Arrows are flat
annotations drawn over the top of the model — they are never occluded by it,
and they never appear on the cover image.

### `Build(...)` options

`scale` (pixels per hole, default 34), `view_rz` (default camera spin),
`highlight` (set `False` to draw every step in flat full colour instead of
washing out what is already built), `fade_old` (how far to wash it, 0–1).

Every step shares one frame sized to the finished model, so the build does not
jump size from page to page.

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
| `standoff_N` | N pitch long, runs `0`…`N` from `at` — sits **on** a face |
| `gear_N` | `gear_12` `gear_36` `gear_60` |
| `wheel_N` | N = diameter in mm: `wheel_200`, `wheel_160`, `wheel_100` |
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

**Measured**, from VEX's own documentation — 12.7 mm hole pitch, and the
3.18 mm square drive shaft, which is exactly ¼ pitch.

**Estimated** — beam and plate thickness, hole and pin radius, standoff width.
These were chosen to look right on the page, not measured with a caliper. They
are safe to change; nothing else depends on their values.

**The colour palette is a guess and you should check it against your kit.** A
wrong colour actively misleads a student. It is one table at the top of
`parts.py`, and any placement can override with `color:`.

The electronics — brain, motor, sensors — are proportioned to be recognisable
at a glance, not dimensionally accurate. Replace those functions if you need
real dimensions.

---

## Known limits

**Nothing checks that a build is physically possible.** There is no collision
detection and no notion of whether two parts are actually connected. If a spec
puts a beam where no beam can go, it draws it happily. The spec author is
responsible for that — which is why the demo builds keep their vertical
arithmetic explicit and commented.

**Hidden surfaces are resolved by sorting, not by a depth buffer.** SVG has no
z-buffer, so parts are drawn back to front. That is exact for parts sitting
next to each other and approximate where they interpenetrate. Most of the work
in `geom.py` is keeping facets small enough that the sort stays right: beam
faces are built per hole cell, holes are true voids ringed with quads rather
than dark circles painted on a solid face, extrusion walls are banded
vertically, and long outlines are chopped before sorting. A small artefact can
still appear where a pin meets the rounded end of a beam.

**Output is large** — roughly 1.5–2 MB for a six-step booklet, most of it gear
teeth and hole rings. It opens and prints fine; it is just not small. Lower
`CELL_PTS` in `parts.py` to trade hole roundness for size.

**One camera angle.** Everything is drawn from the same isometric viewpoint;
`view_rz` spins the model but cannot look from underneath.

---

## Check the render

The renderer is the only thing that knows whether a spec is right. After
writing or changing a build, rasterise it and *look*:

```bash
tools/iqdraw.sh builds/my-build.py -o out/x.html --svg-dir out/x-steps --png
```

Then open the PNGs. Coordinates that are one hole out, a part facing the wrong
way, a gear pair that does not mesh — all of it is obvious in the picture and
invisible in the spec.
