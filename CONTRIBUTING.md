# Contributing to iqdraw

The library has no dependencies and the tests have none either, so there is no
install step and no virtualenv to set up.

```bash
./run-tests.sh            # all of it, about 30 seconds
./run-tests.sh test_check # one module
```

Everything runs on a stock Python 3.9+. `rsvg-convert` is optional and only
used by `--png`.

---

## Where things live

| file | what it owns |
|---|---|
| `geom.py` | vectors, transforms, the isometric projection, shading, and the solid constructors (`box`, `cylinder`, `extrude`) |
| `parts.py` | the part catalogue — one builder per family, plus the colour table and the measured-vs-estimated constants |
| `cadmesh.py` | optional, untracked local high-detail mesh provider |
| `spec.py` | the `Build` / `Assembly` / `Step` API a build file writes against, and how modules and sections compose |
| `render.py` | culling, depth sorting, and SVG emission |
| `check.py` | the sanity checks that run before every draw |
| `instructions.py` | the printable HTML booklet |
| `__main__.py` | the command line |

The dependency order is strictly one way: `geom` → `parts` → `spec`/`render` →
`instructions`. Nothing lower imports anything higher.

---

## The one thing to understand first

**One grid unit is one VEX IQ hole, 12.7 mm, and parts are placed by hole
centre.** A `beam_1x8` at `(0,0,0)` has holes at `(0,0,0)`…`(7,0,0)`, so a pin
at `(3,0,0)` goes through its fourth hole — the pin and the hole share an
address, and no offset arithmetic is ever needed.

If that is not clear, read the "coordinate model" section of `README.md`
before changing anything; almost every bug in this codebase has been a
misunderstanding of it.

---

## Adding a part

1. Write a builder in `parts.py` returning a `Part`. Build it **along +z** so
   `axis:` works on it.
2. Add one line to `_RULES`, and a default colour to `_DEFAULT_COLOR`.
3. Add the family to the sample table in `tests/test_parts.py` — that test
   asserts every known family actually builds, so a new family with no sample
   fails the suite.
4. **Look at it.** The renderer is the only thing that knows whether geometry
   is right:

   ```bash
   iqdraw examples/my-build.py -o out/x.html --svg-dir out/x --png
   ```

`geom.py`'s `box`, `cylinder`, `extrude`, `rounded_rect` and `along` cover most
shapes. Two rules that are not obvious:

- **Keep facets small.** SVG has no depth buffer, so parts are painted back to
  front and every facet sorts by a single depth value. One large facet sorts by
  its centre and paints over anything standing on its far end. `box` and
  `extrude` subdivide for this reason; do not defeat it.
- **Holes are voids, not dark circles.** A solid face with a circle painted on
  it sorts as one facet centred on the hole, and anything pushed through that
  hole draws on top of the part it is buried in. Ring the void with quads —
  `_annulus` does this.

---

## Adding a check

`check.py` holds one function per rule. The bar for a new rule is high and
deliberately so:

> A rule must only fire on something a correct build **cannot** do.

A checker that reports a working build gets switched off, and a switched-off
checker catches nothing. This is why the collision rule looks at beams and
plates only — pins through beams and shafts through gears are meant to
interpenetrate, so a general collision test would report the entire model.

Every rule needs tests on both sides: one build that trips it, and one
plausible build that must **not**. `tests/test_check.py` puts the quiet cases
first for that reason.

---

## Changing the renderer

`tests/test_render.py` guards the invariants that make the output small:
colours are interned as CSS classes, adjacent same-styled geometry merges into
one `<path>`, and merging never reorders anything. If you touch emission, the
paint-order test is the one to watch.

For a change that should not alter what is drawn at all, prove it. Render the
examples before and after and compare the rasterised steps:

```bash
iqdraw examples/gear-train.py -o /tmp/a.html --svg-dir /tmp/a --png
# ... make the change ...
iqdraw examples/gear-train.py -o /tmp/b.html --svg-dir /tmp/b --png
compare -metric AE /tmp/a/step-01.png /tmp/b/step-01.png null:
```

---

## Style

Match what is there. The house style in this codebase is that **comments
explain why, not what** — the reason a facet is subdivided, the reason an
arrow is screen-space, the reason a tolerance is the number it is. A comment
restating the code is worse than no comment.

Line length is 79. There is no formatter or linter configured, on purpose.

---

## Geometry and licensing

All committed part geometry must be original and MIT-licensable. Do not commit
VEX CAD files or meshes derived from them without explicit redistribution
permission. A local, ignored `cadmesh.py` may provide `cad_mesh` and
`gear_mesh` for private use; the public package must remain fully functional
without it.
