"""
Isometric SVG renderer.

Pipeline: transform every part's primitives into world space, drop the ones
facing away from the camera, sort what's left back-to-front, and emit.  Circles
survive as real SVG ellipses (via a transform matrix) rather than being
tessellated, so holes stay crisp at any zoom and print size.
"""

from __future__ import annotations

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
    line_scale: float = 0.052    # outline weight, as a fraction of `scale`
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


def _n(v):
    """
    Compact number formatting.  Values are already in pixels, so one decimal
    is a tenth of a pixel - far past what any screen or printer resolves - and
    it takes a big drawing down by a third.
    """
    s = f"{v:.1f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def _fill(prim):
    f = prim.shade if prim.shade is not None else shade_factor(prim.normal)
    return scale_color(prim.color, f)


def _draw(prim, scale, ox, oy, lw, out):
    if isinstance(prim, Facet):
        pts = " ".join(
            f"{_n(project(p)[0] * scale + ox)},{_n(project(p)[1] * scale + oy)}"
            for p in prim.pts
        )
        # Stroke each facet in its own fill colour.  Neighbouring coplanar
        # cells otherwise antialias against the background along their shared
        # border and leave a faint grid of seams across every large face.
        fill = _fill(prim)
        out.append(f'<polygon points="{pts}" fill="{fill}" stroke="{fill}"/>')
        for d in prim.decals:
            _draw(d, scale, ox, oy, lw, out)

    elif isinstance(prim, Disc):
        cx, cy = project(prim.center)
        ux, uy = project(prim.u)
        vx, vy = project(prim.v)
        r = prim.r * scale
        m = (f"matrix({_n(ux * r)},{_n(uy * r)},{_n(vx * r)},{_n(vy * r)},"
             f"{_n(cx * scale + ox)},{_n(cy * scale + oy)})")
        stroke = ""
        if prim.stroke:
            stroke = (f' stroke="{scale_color(prim.color, 0.62)}"'
                      f' stroke-width="{_n(lw * 0.8)}"'
                      f' vector-effect="non-scaling-stroke"')
        out.append(f'<ellipse rx="1" ry="1" transform="{m}" '
                   f'fill="{_fill(prim)}"{stroke}/>')

    else:  # Edge
        ax, ay = project(prim.a)
        bx, by = project(prim.b)
        out.append(
            f'<line x1="{_n(ax * scale + ox)}" y1="{_n(ay * scale + oy)}" '
            f'x2="{_n(bx * scale + ox)}" y2="{_n(by * scale + oy)}" '
            f'stroke="{prim.color}" stroke-width="{_n(lw * prim.width)}"/>'
        )


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
    # crosses a dark part.
    return [
        f'<line {shaft} stroke="#fff" stroke-width="{halo}"/>',
        f'<polygon points="{headpts}" fill="#fff" stroke="#fff" '
        f'stroke-width="{halo}"/>',
        f'<line {shaft} stroke="{ARROW_COLOR}" stroke-width="{body}"/>',
        f'<polygon points="{headpts}" fill="{ARROW_COLOR}"/>',
    ]


def render(placements, opts: RenderOpts, view_rot=IDENTITY, box=None,
           class_name=None, arrows=True):
    """
    Render placements to an SVG string.  Pass `box` (an unscaled bounds tuple)
    to force a shared frame across every step so the model does not jump size
    from page to page.
    """
    prims = visible(world_prims(placements, opts, view_rot))
    b = box or bounds(prims, opts)
    x0, y0, x1, y1 = b
    w = (x1 - x0) * opts.scale + 2 * opts.pad
    h = (y1 - y0) * opts.scale + 2 * opts.pad
    ox = -x0 * opts.scale + opts.pad
    oy = -y0 * opts.scale + opts.pad
    lw = max(0.85, opts.scale * opts.line_scale)

    body = []
    if opts.background:
        body.append(f'<rect width="{_n(w)}" height="{_n(h)}" '
                    f'fill="{opts.background}"/>')
    for p in prims:
        _draw(p, opts.scale, ox, oy, lw, body)

    if arrows:
        for pl in placements:
            if pl.new and pl.arrow:
                body += _arrow(pl, view_rot, opts.scale, ox, oy, lw)

    cls = f' class="{class_name}"' if class_name else ""
    # The seam-covering stroke width is the same on every polygon, so it lives
    # on the root and only edges and holes override it.
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_n(w)} {_n(h)}"'
        f' width="{_n(w)}" height="{_n(h)}"{cls}'
        f' stroke-width="{_n(lw * 0.55)}"'
        f' stroke-linecap="round" stroke-linejoin="round">'
        + "".join(body)
        + "</svg>"
    )


def render_part_icon(name, color=None, rot=None, box_px=54.0, min_px=27.0):
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
    return render(placement, opts)


def view_rotation(degrees):
    """Spin the whole model about the vertical axis before projecting."""
    return rot_z(degrees)
