"""
Isometric SVG renderer.

Pipeline: transform every part's primitives into world space, drop the ones
facing away from the camera, sort what's left back-to-front, and emit.  Circles
survive as real SVG ellipses (via a transform matrix) rather than being
tessellated, so holes stay crisp at any zoom and print size.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from .geom import (
    VIEW, Disc, Edge, Facet, Transform, IDENTITY, fade, mat_apply, mix_color,
    project, rot_z, scale_color, shade_factor, vadd, vdot, vlen, vmul, vsub,
)
from .parts import Part, get

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


@dataclass
class RenderOpts:
    scale: float = 34.0          # pixels per pitch
    pad: float = 14.0            # pixels of margin
    fade_old: float = 0.52       # how far to wash out already-built parts
    highlight: bool = True       # False renders every step in flat full colour
    line_scale: float = 0.040    # fine CAD edge, as a fraction of `scale`
    background: str = None       # e.g. "#ffffff"; None leaves it transparent


# ------------------------------------------------------------------ collection


def world_prims(placements, opts: RenderOpts, view_rot=IDENTITY):
    """Transform placements into a flat, view-rotated, colour-resolved list."""
    view = Transform(view_rot)
    out = []
    for pl in placements:
        tf = pl.tf.then(view)
        washed = opts.highlight and not pl.new
        for prim in pl.part.prims:
            p = prim.xform(tf)
            if washed:
                _wash(p, opts.fade_old)
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


def _fill(prim):
    normal = getattr(prim, "shade_normal", None) or prim.normal
    f = prim.shade if prim.shade is not None else shade_factor(normal)
    return scale_color(prim.color, f)


def _screen(p, scale, ox, oy):
    x, y = project(p)
    return (round(x * scale + ox, PRECISION), round(y * scale + oy, PRECISION))


def _path(points, close):
    """
    A polyline as one absolute move followed by relative linetos.

    Neighbouring vertices of a facet are a pixel or two apart, so the deltas
    between them are one or two digits where the absolute coordinates are
    four or five.  A booklet is mostly these, and the geometry is identical -
    only the spelling is shorter.

    The absolute positions are rounded *before* the deltas are taken, so the
    points reconstruct to exactly the rounded coordinates instead of
    accumulating a rounding drift along the outline.
    """
    x0, y0 = points[0]
    out = ["M", _pair(x0, y0), "l"]
    px, py = x0, y0
    for x, y in points[1:]:
        pair = _pair(x - px, y - py)
        # A leading minus separates two numbers on its own, so the space in
        # front of it is dead weight - and about half of these deltas are
        # negative.
        if len(out) > 3 and not pair.startswith("-"):
            out.append(" ")
        out.append(pair)
        px, py = x, y
    if close:
        out.append("z")
    return "".join(out)


def _pair(x, y):
    """`x,y` - but the comma goes too when a minus sign already separates."""
    nx, ny = _n(x), _n(y)
    return nx + ny if ny.startswith("-") else f"{nx},{ny}"


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


def _draw(prim, scale, ox, oy, lw, styles, out):
    """
    Append (class, kind, payload) ops.  Emission batches them afterwards, so
    geometry is collected here and never formatted into an element directly.
    """
    if isinstance(prim, Facet):
        # Stroke each facet in its own fill colour.  Neighbouring coplanar
        # cells otherwise antialias against the background along their shared
        # border and leave a faint grid of seams across every large face.
        fill = _fill(prim)
        cls = styles.name(f"fill:{fill};stroke:{fill}")
        out.append((cls, "path",
                    _path([_screen(p, scale, ox, oy) for p in prim.pts], True)))
        for d in prim.decals:
            _draw(d, scale, ox, oy, lw, styles, out)

    elif isinstance(prim, Disc):
        cx, cy = project(prim.center)
        ux, uy = project(prim.u)
        vx, vy = project(prim.v)
        r = prim.r * scale
        m = (f"matrix({_n(ux * r)},{_n(uy * r)},{_n(vx * r)},{_n(vy * r)},"
             f"{_n(cx * scale + ox)},{_n(cy * scale + oy)})")
        decl = f"fill:{_fill(prim)}"
        if prim.stroke:
            decl += (f";stroke:{scale_color(prim.color, 0.62)}"
                     f";stroke-width:{_n(lw * 0.8)}"
                     f";vector-effect:non-scaling-stroke")
        cls = styles.name(decl)
        out.append((cls, "ellipse", f'rx="1" ry="1" transform="{m}"'))

    else:  # Edge
        cls = styles.name(f"fill:none;stroke:{prim.color};"
                          f"stroke-width:{_n(lw * prim.width)}")
        out.append((cls, "path",
                    _path([_screen(prim.a, scale, ox, oy),
                           _screen(prim.b, scale, ox, oy)], False)))


def _emit(ops, prefix):
    """
    Turn ops into elements, merging runs that share a class.

    Only ever merges ops that were already adjacent in the depth sort, so
    paint order is exactly what it was one-element-per-primitive.  Within a
    single <path> SVG fills the whole geometry and then strokes it, rather
    than alternating - which is invisible here because a facet's stroke is its
    own fill colour, the seam-covering trick above.
    """
    out = []
    i = 0
    while i < len(ops):
        cls, kind, payload = ops[i]
        if kind == "raw":
            out.append(payload)
            i += 1
        elif kind == "ellipse":
            out.append(f'<ellipse class="{prefix}{cls}" {payload}/>')
            i += 1
        else:
            j = i + 1
            while j < len(ops) and ops[j][1] == "path" and ops[j][0] == cls:
                j += 1
            d = "".join(op[2] for op in ops[i:j])
            out.append(f'<path class="{prefix}{cls}" d="{d}"/>')
            i = j
    return out


def _part_screen_points(placement, view_rot):
    tf = placement.tf.then(Transform(view_rot))
    pts = []
    for prim in placement.part.prims:
        p = prim.xform(tf)
        if isinstance(p, Facet):
            pts.extend(p.pts)
        elif isinstance(p, Edge):
            pts.extend((p.a, p.b))
        else:
            pts.append(p.center)
    return [project(p) for p in pts]


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


def render(placements, opts: RenderOpts, view_rot=IDENTITY, box=None,
           class_name=None, arrows=True, styles=None, title=None):
    """
    Render placements to an SVG string.  Pass `box` (an unscaled bounds tuple)
    to force a shared frame across every step so the model does not jump size
    from page to page.

    `styles` shares one stylesheet across several drawings in the same
    document; left out, the drawing carries its own, name-spaced so it can be
    pasted anywhere without colliding.  `title` is the accessible name read
    out to a screen reader.
    """
    prims = visible(world_prims(placements, opts, view_rot))
    b = box or bounds(prims, opts)
    x0, y0, x1, y1 = b
    w = (x1 - x0) * opts.scale + 2 * opts.pad
    h = (y1 - y0) * opts.scale + 2 * opts.pad
    ox = -x0 * opts.scale + opts.pad
    oy = -y0 * opts.scale + opts.pad
    lw = max(0.85, opts.scale * opts.line_scale)

    shared = styles is not None
    styles = styles if shared else Styles()

    ops = []
    if opts.background:
        ops.append((None, "raw", f'<rect width="{_n(w)}" height="{_n(h)}" '
                                 f'fill="{opts.background}"/>'))
    for p in prims:
        _draw(p, opts.scale, ox, oy, lw, styles, ops)

    if arrows:
        for pl in placements:
            if pl.new and pl.arrow:
                ops += _arrow(pl, view_rot, opts.scale, ox, oy, lw)

    # A shared stylesheet is emitted once by the caller, and its names are
    # already unique within that document.  A standalone drawing carries its
    # own, name-spaced against whatever page it might be pasted into.
    prefix = "" if shared else styles.prefix()
    head = "" if shared else f"<style>{styles.css(prefix)}</style>"
    body = _emit(ops, prefix)

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
    # The seam-covering stroke width is the same on every polygon, so it lives
    # on the root and only edges and holes override it.
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_n(w)} {_n(h)}"'
        f' width="{_n(w)}" height="{_n(h)}"{cls}{a11y}'
        f' stroke-width="{_n(lw * 0.55)}"'
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


def render_part_icon(name, color=None, rot=None, box_px=54.0, min_px=27.0,
                     styles=None, title=None):
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
    rotation = euler(*(rot if rot is not None else part.icon_rot))
    placement = [Placement(part, Transform(rotation, (0.0, 0.0, 0.0)))]

    probe = RenderOpts(scale=1.0, pad=0.0, highlight=False)
    x0, y0, x1, y1 = bounds(visible(world_prims(placement, probe)), probe)
    extent = max(x1 - x0, y1 - y0, 1e-6)
    target = min_px + (box_px - min_px) * min(1.0, (extent / 12.0) ** 0.5)

    opts = RenderOpts(scale=target / extent, pad=2.0, highlight=False)
    return render(placement, opts, styles=styles, title=title)


def view_rotation(degrees):
    """Spin the whole model about the vertical axis before projecting."""
    return rot_z(degrees)
