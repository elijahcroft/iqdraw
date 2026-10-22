"""
Isometric renderer.

Pipeline: transform every part's primitives into world space, then draw them
with a depth buffer (raster.py) into a PNG.  The SVG around it carries the
frame, the insertion arrows and the accessible name, so arrows stay crisp and
never take part in hiding.
"""

from __future__ import annotations

import base64
import hashlib
import math
from dataclasses import dataclass

from .geom import (
    VIEW, Edge, Facet, Transform, IDENTITY, fade, mat_apply, mix_color,
    hex_to_rgb, project, rot_z, vadd, vdot, vlen, vmul, vnorm, vsub,
)
from .parts import Part, get
from .raster import SHADOW_BLUR, SHADOW_DROP, rasterize

# A crease is only drawn when the two faces meeting there differ by more than
# this.  Keeps tessellated cylinders from turning into wireframe.
CREASE_LIMIT = 0.90


# Which way a part travels as it goes in.  Students lose the thread on steps
# like "a shaft through holes 0, 2 and 6" - twenty identical holes and nothing
# saying which. An arrow answers it without a word of text.
ARROW_DIRS = {
    "down": (0.0, 0.0, -1.0), "up": (0.0, 0.0, 1.0),
    "-z": (0.0, 0.0, -1.0), "+z": (0.0, 0.0, 1.0),
    "-x": (-1.0, 0.0, 0.0), "+x": (1.0, 0.0, 0.0),
    "-y": (0.0, -1.0, 0.0), "+y": (0.0, 1.0, 0.0),
}
ARROW_COLOR = "#e0452c"


def arrow_dir(spec):
    """True -> straight down, which is how most parts are pressed home."""
    if spec is None or spec is False:
        return None
    if spec is True:
        return ARROW_DIRS["down"]
    if isinstance(spec, str):
        try:
            return ARROW_DIRS[spec]
        except KeyError:
            raise KeyError(f"arrow must be True or one of "
                           f"{sorted(ARROW_DIRS)}, got {spec!r}") from None
    return tuple(float(v) for v in spec)


@dataclass
class Placement:
    part: Part
    tf: Transform
    new: bool = True
    arrow: tuple = None
    # Parts sharing a group are one finished module and explode as one rigid
    # piece, not spread apart.
    group: object = None
    # How far to draw it pulled back, in pitch, if not the usual.
    pull: float = None
    # Drawn only in its own step: a string lying loose before it is hung.
    temp: bool = False


@dataclass
class RenderOpts:
    scale: float = 34.0          # pixels per pitch
    pad: float = 14.0            # pixels of margin
    fade_old: float = 0.52       # how far to wash out already-built parts
    highlight: bool = True       # False renders every step in flat full colour
    line_scale: float = 0.040    # fine CAD edge, as a fraction of `scale`
    background: str = None       # e.g. "#ffffff"; None leaves it transparent
    explode: bool = False        # pull new parts back along their arrows
    ring: str = None             # colour of the line round a step's new parts
    ring_w: float = 1.0          # its width, against the usual
    ring_moving: bool = False    # ring only the new parts that move in
    pull: float = 1.0            # how far exploded parts are pulled, against
                                 # the usual
    guide: str = None            # colour of an exploded part's guide line


# ------------------------------------------------------------------ collection


def world_prims(placements, opts: RenderOpts, view_rot=IDENTITY):
    """Transform placements into a flat, view-rotated, colour-resolved list."""
    view = Transform(view_rot)
    out = []
    for n, pl in enumerate(placements, start=1):
        tf = pl.tf.then(view)
        washed = opts.highlight and not pl.new and opts.fade_old > 0
        lit = (opts.highlight and pl.new and not pl.part.plain
               and (pl.arrow is not None or not opts.ring_moving))
        for prim in pl.part.prims:
            p = prim.xform(tf)
            if washed:
                _wash(p, opts.fade_old)
            # Which part a primitive belongs to, and whether it is one of the
            # step's new parts: the raster draws a part's own folds lighter
            # than the line round it, and rings the new parts.
            p.pid, p.lit = n, lit
            out.append(p)
    return out


def _wash(prim, amount):
    prim.color = fade(prim.color, amount)
    if isinstance(prim, Facet):
        for d in prim.decals:
            _wash(d, amount)
    elif isinstance(prim, Edge):
        prim.color = mix_color(prim.color, "#aeb4bd", amount)


MAX_EDGE = 0.85  # grid units; longer outlines are chopped before sorting


def _split_edge(e):
    """
    Cut a long outline into short pieces so each sorts where it actually
    lies.  A shaft's silhouette runs the full height of the shaft, so as one
    primitive it sorts by its midpoint and gets drawn over the beam that is
    supposed to be hiding its lower half.
    """
    length = vlen(vsub(e.b, e.a))
    n = int(math.ceil(length / MAX_EDGE - 1e-9))
    if n <= 1:
        return [e]
    out = []
    for i in range(n):
        t0, t1 = i / n, (i + 1) / n
        a = vadd(e.a, vmul(vsub(e.b, e.a), t0))
        b = vadd(e.a, vmul(vsub(e.b, e.a), t1))
        out.append(Edge(a, b, e.color, e.na, e.nb, e.width))
    return out


def visible(prims):
    """Back-face cull, split long outlines, then sort back-to-front."""
    keep = []
    for p in prims:
        if isinstance(p, Edge):
            # An edge survives if either adjoining face looks at the camera
            # and the crease between them is actually sharp.
            if (vdot(p.na, VIEW) > 0 or vdot(p.nb, VIEW) > 0) \
                    and vdot(p.na, p.nb) < CREASE_LIMIT:
                keep.extend(_split_edge(p))
        elif vdot(p.normal, VIEW) > 1e-6:
            keep.append(p)
    keep.sort(key=lambda p: p.key)
    return keep


# -------------------------------------------------------------------- bounds


def bounds(prims, opts: RenderOpts):
    xs, ys = [], []
    for p in prims:
        if isinstance(p, Facet):
            pts = [project(q) for q in p.pts]
        elif isinstance(p, Edge):
            pts = [project(p.a), project(p.b)]
        else:
            cx, cy = project(p.center)
            ux, uy = project(p.u)
            vx, vy = project(p.v)
            rx = p.r * (abs(ux) + abs(vx))
            ry = p.r * (abs(uy) + abs(vy))
            pts = [(cx - rx, cy - ry), (cx + rx, cy + ry)]
        for x, y in pts:
            xs.append(x)
            ys.append(y)
    if not xs:
        return (0.0, 0.0, 1.0, 1.0)
    return (min(xs), min(ys), max(xs), max(ys))


def union_bounds(*boxes):
    boxes = [b for b in boxes if b]
    return (
        min(b[0] for b in boxes), min(b[1] for b in boxes),
        max(b[2] for b in boxes), max(b[3] for b in boxes),
    )


# ---------------------------------------------------------------- SVG output


# Decimal places kept in emitted coordinates.  One tenth of a pixel is far
# past what any screen or printer resolves, and the drawing is scaled to the
# page anyway; every digit here is paid for once per vertex, and a robot-sized
# booklet has a few hundred thousand of them.
PRECISION = 1


def _n(v):
    """
    Compact number formatting, to `PRECISION` decimal places.

    Trailing zeros and a trailing point are dropped, and every spelling of
    zero collapses to `0` - including the bare `-` a negative value leaves
    behind once its digits are stripped.
    """
    s = f"{v:.{PRECISION}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("", "-", "-0") else s


_ALPHA = "abcdefghijklmnopqrstuvwxyz"


def _class_name(i):
    """Short, always-valid CSS identifiers: a, b, ... z, aa, ab, ..."""
    name = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        name = _ALPHA[r] + name
    return name


class Styles:
    """
    Interns paint properties as CSS classes.

    A booklet carries tens of thousands of facets and outline segments, and
    between them only a few hundred distinct shades - every facet of one part
    at one angle resolves to the same colour.  Naming each shade once and
    pointing at it costs a two-character class attribute instead of a repeated
    pair of hex literals.  Nothing about what is drawn changes.

    Pass one instance to several `render` calls to share a single stylesheet
    across a whole document; leave it out and each drawing carries its own.
    """

    def __init__(self):
        self._names = {}

    def name(self, decl):
        n = self._names.get(decl)
        if n is None:
            n = _class_name(len(self._names))
            self._names[decl] = n
        return n

    def css(self, prefix=""):
        return "".join(f".{prefix}{n}{{{d}}}" for d, n in self._names.items())

    def prefix(self):
        """
        A short tag derived from the stylesheet itself.

        A standalone SVG pasted into an HTML page brings its <style> with it,
        and CSS class names are document-wide - two such drawings on one page
        would fight over `.a`.  Deriving the tag from the declarations keeps
        it stable for identical drawings and distinct for different ones,
        without any global counter.
        """
        digest = hashlib.sha1(self.css().encode("utf-8")).hexdigest()[:6]
        return f"q{digest}"


def _part_screen_points(placement, view_rot):
    tf = placement.tf.then(Transform(view_rot))
    return [project(p) for p in _part_points(placement, tf)]


def _part_points(placement, tf):
    pts = []
    for prim in placement.part.prims:
        p = prim.xform(tf)
        if isinstance(p, Facet):
            pts.extend(p.pts)
        elif isinstance(p, Edge):
            pts.extend((p.a, p.b))
        else:
            pts.append(p.center)
    return pts


ARROW_GAP, ARROW_LEN, ARROW_HEAD = 0.30, 1.25, 0.42


def _arrow_geometry(placement, view_rot):
    """(anchor, direction, back-reach) in unscaled screen units, or None."""
    dx, dy = project(mat_apply(view_rot, placement.arrow))
    n = math.hypot(dx, dy)
    if n < 1e-9:                       # travelling straight at the camera
        return None
    dx, dy = dx / n, dy / n
    pts = _part_screen_points(placement, view_rot)
    if not pts:
        return None
    ax = sum(p[0] for p in pts) / len(pts)
    ay = sum(p[1] for p in pts) / len(pts)
    # How far the part reaches back along its own approach, so the arrow
    # clears it instead of landing on top of it.
    back = max(-((p[0] - ax) * dx + (p[1] - ay) * dy) for p in pts)
    return (ax, ay, dx, dy, back)


def arrow_tail(placement, view_rot):
    """Where the arrow's tail lands, so the frame can be sized to include it."""
    g = _arrow_geometry(placement, view_rot)
    if g is None:
        return None
    ax, ay, dx, dy, back = g
    reach = back + ARROW_GAP + ARROW_LEN
    return (ax - dx * reach, ay - dy * reach)


def _arrow(placement, view_rot, scale, ox, oy, lw):
    """
    A flat annotation arrow pointing the way the part travels.

    Deliberately screen-space rather than a 3D object: it is a note to the
    reader, not part of the model, so it should never be occluded by the
    build and never take part in the depth sort.
    """
    g = _arrow_geometry(placement, view_rot)
    if g is None:
        return []
    ax, ay, dx, dy, back = g
    gap, length, head = ARROW_GAP, ARROW_LEN, ARROW_HEAD
    tipx = (ax - dx * (back + gap)) * scale + ox
    tipy = (ay - dy * (back + gap)) * scale + oy
    tailx, taily = tipx - dx * length * scale, tipy - dy * length * scale
    basex, basey = tipx - dx * head * scale, tipy - dy * head * scale
    wx, wy = -dy * head * 0.42 * scale, dx * head * 0.42 * scale

    shaft = (f'x1="{_n(tailx)}" y1="{_n(taily)}" '
             f'x2="{_n(basex)}" y2="{_n(basey)}"')
    headpts = (f"{_n(tipx)},{_n(tipy)} {_n(basex + wx)},{_n(basey + wy)} "
               f"{_n(basex - wx)},{_n(basey - wy)}")
    halo = _n(lw * 3.2)
    body = _n(lw * 1.9)
    # Drawn twice: a white halo first so the arrow stays readable where it
    # crosses a dark part.  There are only ever a handful of these, so they
    # keep their attributes inline rather than earning a class.
    return [
        (None, "raw", f'<line {shaft} stroke="#fff" stroke-width="{halo}"/>'),
        (None, "raw", f'<polygon points="{headpts}" fill="#fff" stroke="#fff" '
                      f'stroke-width="{halo}"/>'),
        (None, "raw",
         f'<line {shaft} stroke="{ARROW_COLOR}" stroke-width="{body}"/>'),
        (None, "raw", f'<polygon points="{headpts}" fill="{ARROW_COLOR}"/>'),
    ]


# ------------------------------------------------------------------ explode
# How printed build guides answer "which hole": the new part is drawn pulled
# back along the way it goes in, with a thin line from where it is to where
# it lands.  The finished position is left to the small inset beside it.

EXPLODE_MIN, EXPLODE_MAX = 1.5, 3.0   # grid units of pull-back
EXPLODE_SPREAD = 2.5                  # most extra pull for an outer part
GUIDE_COLOR = "#3fb34f"
# The families whose parts go into holes, and so carry a guide line when the
# piece they are part of moves as one.
GUIDED = {"pin", "shaft", "standoff", "capped", "motorshaft", "plastic"}


def exploded(placements, k=1.0):
    """
    (placements, guides): every new part that has an arrow moved back along
    it, and a (home, pulled) pair of world points for each one's guide line.
    `k` scales every pull: the 2nd-gen guides pull parts a long way out.

    Parts travelling the same way are pulled by the same amount, plus how far
    further out they sit, so a collar that goes on after a wheel is drawn in
    front of the wheel rather than through it.
    """
    groups = {}
    for i, pl in enumerate(placements):
        if pl.new and pl.arrow:
            d = vnorm(pl.arrow)
            key = (tuple(round(v, 3) for v in d), pl.group)
            groups.setdefault(key, []).append(i)
    out = list(placements)
    guides = []
    for (d, rigid), idx in groups.items():
        if rigid is not None:
            for i in idx:
                pl = placements[i]
                off = vmul(d, -(pl.pull if pl.pull is not None
                                else EXPLODE_MAX) * k)
                out[i] = Placement(pl.part, pl.tf.then(Transform(IDENTITY, off)),
                                   new=True, arrow=pl.arrow, group=pl.group)
                # A piece moving as one is guided in by the parts that go
                # into holes - its pins, shafts and standoffs - as the
                # guides draw it, not by every part it is made of.
                if pl.pull is not None or \
                        pl.part.name.split("_")[0] in GUIDED:
                    pts = _part_points(pl, pl.tf)
                    lo, hi = _bbox(pts)
                    c = tuple((a + b) / 2 for a, b in zip(lo, hi))
                    guides.append((c, vadd(c, off)))
            continue
        info = []
        for i in idx:
            pts = _part_points(placements[i], placements[i].tf)
            lo = [min(p[k] for p in pts) for k in range(3)]
            hi = [max(p[k] for p in pts) for k in range(3)]
            centre = tuple((a + b) / 2 for a, b in zip(lo, hi))
            along = [vdot(p, d) for p in pts]
            # How far out the part's leading end sits: what goes on first
            # has its leading end deepest, whatever its length.
            info.append((i, centre, max(along) - min(along), -max(along)))
        pull = k * min(EXPLODE_MAX,
                       max(EXPLODE_MIN, 0.6 * max(e for _, _, e, _ in info) + 0.8))
        base = min(o for _, _, _, o in info)
        for i, centre, _, o in info:
            off = vmul(d, -(pull + min(EXPLODE_SPREAD * k, o - base)))
            pl = placements[i]
            if pl.pull is not None:
                off = vmul(d, -pl.pull * k)
            out[i] = Placement(pl.part, pl.tf.then(Transform(IDENTITY, off)),
                               new=True, arrow=pl.arrow)
            guides.append((centre, vadd(centre, off)))
        # A new part with no arrow of its own that sits further out than the
        # parts going in - the beam the pins come through - goes on after
        # them, so it is pulled back further still or it hides them.
        reach = max(abs(o - base) for _, _, _, o in info) + pull
        ends = _span(placements, idx)
        for j, pl in enumerate(placements):
            if not pl.new or pl.arrow or out[j] is not pl:
                continue
            pts = _part_points(pl, pl.tf)
            lo, hi = _bbox(pts)
            o = -vdot(tuple((a + b) / 2 for a, b in zip(lo, hi)), d)
            # A part the others go into - the drum of a wheel round its
            # lock beam - is not in their way, however its centre sits.
            along = [vdot(q, d) for q in pts]
            holds = any(min(along) + 0.05 < vdot(c, d) < max(along) - 0.05
                        for _, c, _, _ in info)
            if not holds and o > max(-vdot(c, d) for _, c, _, _ in info) + 1e-6 \
                    and _overlaps(lo, hi, *ends, d):
                off = vmul(d, -(reach + pull))
                out[j] = Placement(pl.part, pl.tf.then(Transform(IDENTITY, off)),
                                   new=True)
    return out, guides


def _bbox(pts):
    return ([min(p[k] for p in pts) for k in range(3)],
            [max(p[k] for p in pts) for k in range(3)])


def _span(placements, idx):
    """The box around the parts at `idx`."""
    boxes = [_bbox(_part_points(placements[i], placements[i].tf)) for i in idx]
    return ([min(b[0][k] for b in boxes) for k in range(3)],
            [max(b[1][k] for b in boxes) for k in range(3)])


def _overlaps(lo, hi, lo2, hi2, d):
    """Do two boxes overlap, looking along `d`?"""
    for k in range(3):
        if abs(d[k]) > 0.9:
            continue
        if hi[k] < lo2[k] - 1e-6 or hi2[k] < lo[k] - 1e-6:
            return False
    return True


def render(placements, opts: RenderOpts, view_rot=IDENTITY, box=None,
           class_name=None, arrows=True, styles=None, title=None):
    """
    Render placements to an SVG string.  Pass `box` (an unscaled bounds tuple)
    to force a shared frame across every step so the model does not jump size
    from page to page.

    `styles` is accepted for callers that share one stylesheet across a
    document; the raster drawing needs none.  `title` is the accessible name
    read out to a screen reader.
    """
    guides = []
    if opts.explode:
        # The guide lines do the arrows' job, the way a printed guide does.
        placements, guides = exploded(placements, opts.pull)
        arrows = False
    world = world_prims(placements, opts, view_rot)
    b = box or bounds(visible(world), opts)
    x0, y0, x1, y1 = b
    # Room below and to the sides for the soft shadow, where the margin is
    # too narrow to hold it.
    room = max(0.0, (SHADOW_DROP + SHADOW_BLUR) * opts.scale - opts.pad)
    w = (x1 - x0) * opts.scale + 2 * (opts.pad + room)
    h = (y1 - y0) * opts.scale + 2 * opts.pad + room
    ox = -x0 * opts.scale + opts.pad + room
    oy = -y0 * opts.scale + opts.pad
    lw = max(0.85, opts.scale * opts.line_scale)

    lines = [(mat_apply(view_rot, a), mat_apply(view_rot, c))
             for a, c in guides]
    # The arrows' job falls to the guides, so a part pulled back has its
    # `arrow` still set: that is how the ring finds the parts that move.
    png = rasterize(world, opts.scale, ox, oy, w, h, lw * 0.9, opts.background,
                    lines=lines,
                    line_rgb=hex_to_rgb(opts.guide or GUIDE_COLOR),
                    ring_rgb=hex_to_rgb(opts.ring) if opts.ring else None,
                    ring_w=opts.ring_w, margin=opts.pad + room)
    body = [f'<image width="{_n(w)}" height="{_n(h)}" href="data:image/png;'
            f'base64,{base64.b64encode(png).decode("ascii")}"/>']

    if arrows:
        for pl in placements:
            if pl.new and pl.arrow:
                body += [op[2] for op in _arrow(pl, view_rot, opts.scale, ox, oy, lw)]

    head = ""

    cls = f' class="{class_name}"' if class_name else ""
    if title:
        # A drawing carries the half of the instruction the words leave out -
        # which hole, which way round - so it has to announce itself rather
        # than be skipped as decoration.  aria-label is what assistive tech
        # actually reads; the <title> is for anyone opening the .svg directly.
        head = f"<title>{_xml_escape(title)}</title>" + head
        a11y = f' role="img" aria-label="{_xml_escape(title)}"'
    else:
        a11y = ' role="presentation" aria-hidden="true"'
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_n(w)} {_n(h)}"'
        f' width="{_n(w)}" height="{_n(h)}"{cls}{a11y}'
        f' stroke-linecap="round" stroke-linejoin="round">'
        + head + "".join(body)
        + "</svg>"
    )


def _xml_escape(s):
    """Escape for both element text and attribute values - aria-label is an
    attribute, so an unescaped quote in a part label would end it early and
    break the whole drawing."""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# Screen directions as world vectors, for drawing a part face-on: across,
# up, and toward the camera.
_ACROSS = (2 ** -0.5, -(2 ** -0.5), 0.0)
_UP = (-(6 ** -0.5), -(6 ** -0.5), 2 * 6 ** -0.5)
_TOWARD = (3 ** -0.5, 3 ** -0.5, 3 ** -0.5)
# Parts drawn side-on in a flat callout: pins, shafts and standoffs lie
# across it, as the letter-size guides draw them.  Connectors show their
# holes.  Everything else is drawn face-on.
_SIDE_ON = {"pin", "shaft", "standoff", "capped", "plastic", "motorshaft",
            "standoffconn"}
_HOLES_ON_Y = {"connector"}


def flat_rotation(name):
    """The rotation that shows part `name` flat to the page."""
    family = name.partition("@")[0].split("_")[0]
    if family in _SIDE_ON:
        cols = (_UP, _TOWARD, _ACROSS)          # x up, y at you, z across
    elif family in _HOLES_ON_Y:
        cols = (tuple(-v for v in _ACROSS), _TOWARD, _UP)
    else:
        cols = (_ACROSS, _UP, _TOWARD)
    return tuple(tuple(cols[j][i] for j in range(3)) for i in range(3))


def render_part_icon(name, color=None, rot=None, box_px=54.0, min_px=27.0,
                     styles=None, title=None, flat=False):
    """
    A single part on its own, for the parts callout.

    Sized to fit the slot rather than drawn at a fixed scale.  At one shared
    scale a 2x12 beam fills the box and a shaft collar is a four-pixel speck,
    which defeats the point - the callout exists to let a student recognise
    the part, not to compare part sizes.  Bigger parts still get a bigger
    icon, just sub-linearly.
    """
    part = get(name, color)
    from .geom import euler
    # A cable is drawn the way it is held up, not flat.
    flat = flat and name.split("_")[0] not in ("cable",)
    rotation = (flat_rotation(name) if flat else
                euler(*(rot if rot is not None else part.icon_rot)))
    placement = [Placement(part, Transform(rotation, (0.0, 0.0, 0.0)))]

    probe = RenderOpts(scale=1.0, pad=0.0, highlight=False)
    x0, y0, x1, y1 = bounds(visible(world_prims(placement, probe)), probe)
    extent = max(x1 - x0, y1 - y0, 1e-6)
    target = min_px + (box_px - min_px) * min(1.0, (extent / 12.0) ** 0.5)

    opts = RenderOpts(scale=target / extent, pad=2.0, highlight=False)
    return render(placement, opts, styles=styles, title=title)


def render_module_icon(placements, view_rot=IDENTITY, box_px=96.0,
                       title=None):
    """A finished module on its own, for the callout of the step that fits it."""
    probe = RenderOpts(scale=1.0, pad=0.0, highlight=False)
    x0, y0, x1, y1 = bounds(visible(world_prims(placements, probe, view_rot)),
                            probe)
    opts = RenderOpts(scale=box_px / max(x1 - x0, y1 - y0, 1e-6), pad=2.0,
                      highlight=False)
    return render(placements, opts, view_rot, arrows=False, title=title)


def view_rotation(degrees):
    """Spin the whole model about the vertical axis before projecting."""
    return rot_z(degrees)
