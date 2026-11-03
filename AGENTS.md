# Writing IQDraw builds — a guide for agents

A build spec is a Python file that places VEX IQ parts at hole coordinates.
This page is the short version of the README for writing one: the loop to
work in, the orientations that come up again and again, and the mistakes the
checks catch.

## The loop

```bash
iqdraw build.py --check-only --strict     # 1. is it physically buildable?
iqdraw build.py --inspect | jq …          # 2. what is joined to what?
iqdraw build.py --sheet out/sheet.png     # 3. does it look like the idea?
iqdraw build.py -o out/build.html         # 4. the booklet, once it is right
```

- `--check-only --strict` must pass. The joint checks mean a pin through
  solid plastic, a part nothing holds on, or two parts in one space are all
  errors, not warnings.
- `--inspect` prints every part's world box and holes and every joint as JSON.
  `--at X,Y,Z` names what is at one point. A shaft's joints say `locked`
  (square in square: it drives) or `free` (spins).
- `--sheet` is every step plus top, side, front and corner views on one PNG.
  The flat views have hole-number rulers. `--views DIR` writes all seven
  views separately.
- `--parts` lists the part families; `--part NAME` gives one part's envelope
  and hole table in its own coordinates.

Steps 1–3 skip the booklet and take seconds; the booklet can take tens of
seconds on a robot-sized build.

## Coordinates

- One unit is one hole (12.7 mm). Parts are placed by their **first hole's
  centre**. `+z` is up. Coordinates are 0-based.
- **Holes only run through a part's face.** A flat beam's holes run along
  `z`. A shaft along `y` needs a beam turned on edge. This is the most common
  mistake, and `rod in solid` reports it.
- Nominal thicknesses: beam 0.5, plate 0.25, gear 0.5, spacer 0.25,
  washer 0.12, collar 0.36. Two stacked beams are 0.5 apart; the pin joining
  them is centred on their shared face.

## Place against parts, not at numbers

`s.add()` returns a `Ref`. Use it instead of working out coordinates:

```python
rail = s.add("beam_2x12", (0, 0, 0), rot=(90, 0, 0))       # on edge
s.add("shaft_3", rail.hole(1) + (0, -0.2, 0))              # axis from the hole
sp = s.add("spacer", rail.hole(1), on=rail, side="+y")     # pressed on +y face
s.add("wheel_200", rail.hole(1), on=sp, side="+y")
s.add("pin_1x1", rail.hole(5, 1, side="-y"))               # half in, half out
g = s.add("gear_12", (0, 0, 0.75), axis="z")
s.add("gear_36", g.meshing("gear_36", "+x"))               # meshes, on the grid
```

- `hole(x, y=0, z=0)` takes the part's **own** hole coordinates. A bad index
  raises an error listing the real ones.
- `on=` takes a `Ref`, a list of them, or a coordinate. `side=` is the
  direction to stack in.
- A `Ref` is in the coordinates of the `Build` or `Assembly` it was made in.
  `b.place(assembly, ...)` returns the copy: `left = b.place(side, at=…)`,
  then `left(rail)` is that rail where the copy put it, ready for `hole()`,
  `face()` and `on=`. Never re-derive a placed assembly's faces by hand.

## Orientations that come up

`tests/test_refs.py` pins every row, so this table stays true.

| want | `rot=` |
|---|---|
| flat beam running along `y` | `(0, 0, 90)` |
| beam on edge along `x`, holes facing `y` (a rail) | `(90, 0, 0)` |
| beam on edge reaching `-x`, holes facing `y` (an arm) | `(90, 0, 180)` |
| beam on edge along `y`, holes facing `x` (a crossbar) | `(90, 0, 90)` |
| beam standing up, holes facing `y` (a tower) | `(0, -90, 90)` |
| corner bracket hung foot-up, foot pointing `-y` | `(180, 0, -90)` |
| corner bracket hung foot-up, foot pointing `+y` | `(180, 0, 90)` |

An unrotated `corner_AxB` has its foot along `+x` with vertical holes, and its
upright along `+z` with holes facing `x`. To check an orientation, place the
part in a scratch build and print `ref.box` and `ref.hole(…).axis`, or run
`--part NAME`.

## Patterns that pass the checks

- **Axle through a rail:** stand the rail on edge. Put the shaft through a
  hole, with a spacer and the wheel outside and a collar on each end.
- **Joining two on-edge rails:** pin a hung corner bracket inside each rail
  through both rows, then pin flat cross beams onto the brackets' feet. A
  standoff with a pin in each end also spans between two facing holes.
- **A pivot:** everything the pivot shaft passes through must have holes along
  that shaft. Two arm beams on one shaft swing separately unless something
  ties them together, such as a standoff.
- **Driving something:** a shaft spins freely in a beam's round hole. Use a
  square bore (gear, wheel, collar) to make it turn with the shaft.
- **Electronics** (brain, sensors, battery) are drawn for recognition only,
  with no hole positions. Rest them on the structure with `on=`.

## The checks

| kind | means |
|---|---|
| `rod in solid` | a pin or shaft passes through a part's plastic, not one of its holes; the message names the nearest hole |
| `loose` | a pin reaches fewer than two parts, a shaft none, or nothing pins or shafts a structural part on |
| `collision` | two solid parts overlap |
| `overlap` | two beams or plates overlap |
| `gear mesh` | two gears are almost, but not exactly, at mesh distance |
| `stranded` | a part touches nothing |
| `duplicate` | the same part twice in one place |

## Known quirks

- The drawings are mirror images: `+x` is drawn to the lower right and `+y` to
  the lower left. Views and booklets agree with each other, but don't write
  "left" or "right" in a step note from the coordinates alone.
- Size names parse any number, so `beam_1x9` draws fine. Check sizes against a
  real kit.
