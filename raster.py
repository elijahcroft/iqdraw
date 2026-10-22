"""
Depth-buffer rendering of the model to a PNG.

Painting facets back to front by their centres can't be made exact: on thin
parts (the brain's lid, a wheel hub, tyre tread) a facet underneath sorts in
front of the surface above it, and its edges poke through as stray ticks and
speckles.  Here every pixel keeps whichever surface is nearest, so nothing
shows through.

Outlines are found in the finished image rather than drawn per edge, the way
VEX's own build-guide renders look: a dark line wherever one surface sits in
front of another, and a lighter one where a surface folds sharply.

Needs numpy.  The PNG is written with the standard library.
"""

from __future__ import annotations

import math
import struct
import zlib

from .geom import Disc, Facet, VIEW, depth, hex_to_rgb, project, shade_factor, vdot

SUPERSAMPLE = 2   # raster pixels per output pixel, each way; averaged down
DPR = 2           # output pixels per SVG unit, so it stays sharp on HiDPI and paper
DECAL_BIAS = 0.01 # pitch toward the camera, so a hole drawn on a face wins over it
CREASE = 0.55     # neighbouring normals less alike than this draw a crease line
CREASE_DARKEN = 0.62
SILHOUETTE_DARKEN = 0.30
DESATURATE = 0.15 # pull lit colours this far toward grey, like a CAD viewport
AO_RADIUS = 0.35  # pitch around a pixel looked at for nearer surfaces
AO_DEPTH = 0.30   # how far nearer (in depth) counts as fully occluded
AO_STRENGTH = 0.35
SHADOW_DROP = 0.35   # pitch the soft shadow sits below the model on screen
SHADOW_BLUR = 0.45   # pitch it is softened over
SHADOW_ALPHA = 0.16
SHADOW_RGB = (26.0, 30.0, 38.0)


def _ring(d, segments):
    return [
        tuple(d.center[k] + d.r * (d.u[k] * math.cos(t) + d.v[k] * math.sin(t))
              for k in range(3))
        for t in (2 * math.pi * i / segments for i in range(segments))
    ]


def _fill(prim):
    normal = getattr(prim, "shade_normal", None) or prim.normal
    f = prim.shade if prim.shade is not None else shade_factor(normal)
    return tuple(min(255.0, c * f) for c in hex_to_rgb(prim.color))


def _triangles(prims):
    """
    (three points, rgb, depth bias, normal, ring id, part id, new) per
    visible triangle.  A decal belongs to the part of the face it is on.
    """
    out = []
    ring = 0

    def add(poly, prim, bias, ring_id, owner):
        rgb = _fill(prim)
        pid, lit = getattr(owner, "pid", 0), getattr(owner, "lit", False)
        for i in range(1, len(poly) - 1):
            out.append((poly[0], poly[i], poly[i + 1], rgb, bias, prim.normal,
                        ring_id, pid, lit))

    def add_disc(d, bias, owner):
        nonlocal ring
        if vdot(d.normal, VIEW) <= 1e-6:
            return
        ring += 1
        add(_ring(d, 32), d, bias, ring if d.stroke else 0, owner)

    for p in prims:
        if isinstance(p, Facet):
            if vdot(p.normal, VIEW) <= 1e-6:
                continue
            add(p.pts, p, 0.0, 0, p)
            for d in p.decals:
                if isinstance(d, Disc):
                    add_disc(d, DECAL_BIAS, p)
                elif vdot(d.normal, VIEW) > 1e-6:
                    add(d.pts, d, DECAL_BIAS, 0, p)
        elif isinstance(p, Disc):
            add_disc(p, DECAL_BIAS, p)
    return out


def rasterize(prims, scale, ox, oy, width, height, line_px, background=None,
              lines=(), line_rgb=(0, 0, 0), ring_rgb=None, ring_w=1.0,
              margin=0.0):
    """
    Draw `prims` into a `width` x `height` (SVG units) image and return PNG
    bytes.  `scale`, `ox` and `oy` map projected pitch to SVG units, exactly
    as the frame around it was sized.

    `lines` are (a, b) pairs of points in the same space as `prims`, drawn
    thin in `line_rgb` and hidden wherever a part is in front of them - an
    exploded part's guide line disappears into the hole it leads to.

    `ring_rgb` draws a line that colour round the step's new parts, the way
    the printed guides pick them out, instead of washing the rest out.

    `margin` is the empty border (SVG units) round the model; the soft shadow
    is kept inside it so it is never cut off at the image's edge.
    """
    import numpy as np

    k = DPR * SUPERSAMPLE
    W = max(1, int(math.ceil(width * DPR))) * SUPERSAMPLE
    H = max(1, int(math.ceil(height * DPR))) * SUPERSAMPLE
    zbuf = np.full((H, W), -np.inf)
    col = np.zeros((H, W, 3), np.float32)
    nrm = np.zeros((H, W, 3), np.float32)
    rid = np.zeros((H, W), np.int32)
    pid = np.zeros((H, W), np.int32)
    lit = np.zeros((H, W), bool)

    for a, b, c, rgb, bias, normal, ring_id, part, new in _triangles(prims):
        (ax, ay), (bx, by), (cx, cy) = (
            ((x * scale + ox) * k, (y * scale + oy) * k)
            for x, y in (project(a), project(b), project(c)))
        area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if abs(area) < 1e-9:
            continue
        x0 = max(0, int(math.floor(min(ax, bx, cx))))
        x1 = min(W - 1, int(math.ceil(max(ax, bx, cx))))
        y0 = max(0, int(math.floor(min(ay, by, cy))))
        y1 = min(H - 1, int(math.ceil(max(ay, by, cy))))
        if x0 > x1 or y0 > y1:
            continue
        xs = np.arange(x0, x1 + 1) + 0.5
        ys = np.arange(y0, y1 + 1)[:, None] + 0.5
        w0 = ((bx - xs) * (cy - ys) - (by - ys) * (cx - xs)) / area
        w1 = ((cx - xs) * (ay - ys) - (cy - ys) * (ax - xs)) / area
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not inside.any():
            continue
        z = w0 * depth(a) + w1 * depth(b) + w2 * depth(c) + bias
        zs = zbuf[y0:y1 + 1, x0:x1 + 1]
        win = inside & (z > zs)
        zs[win] = z[win]
        col[y0:y1 + 1, x0:x1 + 1][win] = rgb
        nrm[y0:y1 + 1, x0:x1 + 1][win] = normal
        rid[y0:y1 + 1, x0:x1 + 1][win] = ring_id
        pid[y0:y1 + 1, x0:x1 + 1][win] = part
        lit[y0:y1 + 1, x0:x1 + 1][win] = new

    covered = np.isfinite(zbuf)
    floor = zbuf[covered].min() - 100.0 if covered.any() else 0.0
    z = np.where(covered, zbuf, floor)

    # A step in depth bigger than a slanted surface can make across a few
    # pixels is one part in front of another.  The line goes on the far side,
    # coloured from the near one, so a pale part gets a paler outline.  Inside
    # one part - a beam's ribs over its own floor - it is only a fold, and
    # drawn as one: a beam's lattice is hundreds of such steps, and outlined
    # in black each one it turns the whole beam into a dark speckled texture.
    jump = 0.08 + 3.0 / (scale * k)
    line = np.zeros((H, W), bool)
    line_col = np.zeros((H, W, 3), np.float32)
    crease = np.zeros((H, W), bool)
    for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        here = (slice(max(0, -dy), H - max(0, dy)), slice(max(0, -dx), W - max(0, dx)))
        there = (slice(max(0, dy), H - max(0, -dy)), slice(max(0, dx), W - max(0, -dx)))
        step = (z[there] - z[here]) > jump
        own = step & covered[here] & (pid[here] == pid[there])
        nearer = step & ~own
        line[here] |= nearer
        line_col[here][nearer] = col[there][nearer] * SILHOUETTE_DARKEN
        crease[here] |= own
        both = covered[here] & covered[there]
        fold = both & (np.sum(nrm[here] * nrm[there], axis=-1) < CREASE)
        rim = both & (rid[here] != rid[there]) & ((rid[here] > 0) | (rid[there] > 0))
        crease[here] |= fold | rim

    reach = max(0, int(round((line_px * k - 1) / 2)))
    for _ in range(reach):
        grown = line.copy()
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            here = (slice(max(0, -dy), H - max(0, dy)), slice(max(0, -dx), W - max(0, dx)))
            there = (slice(max(0, dy), H - max(0, -dy)), slice(max(0, dx), W - max(0, -dx)))
            add = line[there] & ~grown[here]
            grown[here] |= add
            line_col[here][add] = line_col[there][add]
        line = grown

    alpha = covered | line
    grey = col @ np.array([0.299, 0.587, 0.114], np.float32)
    out = col + (grey[..., None] - col) * DESATURATE
    out *= _occlusion(z, nrm, covered, scale * k)[..., None]
    out[crease & ~line] *= CREASE_DARKEN
    out[line] = line_col[line]
    if ring_rgb is not None and lit.any():
        _ring_new(lit & covered, np.where(covered, pid, -1), out, alpha, ring_rgb,
                  line_px * k * RING_WIDTH * ring_w)
    _guides(lines, line_rgb, z, out, alpha, scale, ox, oy, k, line_px * k * 1.7)
    shadow = _shadow(covered, scale * k, margin * k) * ~alpha
    out[~alpha] = SHADOW_RGB
    if background:
        bg = np.array(hex_to_rgb(background), np.float32)
        out[~alpha] = bg + (np.array(SHADOW_RGB, np.float32) - bg) * shadow[~alpha, None]
        shadow[:] = 1.0
    cover = np.where(alpha, 1.0, shadow).astype(np.float32)
    rgba = np.concatenate([out, cover[..., None] * 255.0], axis=-1)
    # Average each supersample block; colour is premultiplied by coverage first
    # so an edge pixel blends toward transparent rather than toward black.
    rgba[..., :3] *= rgba[..., 3:] / 255.0
    h, w = H // SUPERSAMPLE, W // SUPERSAMPLE
    rgba = rgba.reshape(h, SUPERSAMPLE, w, SUPERSAMPLE, 4).mean(axis=(1, 3))
    a = rgba[..., 3:]
    rgba[..., :3] = np.where(a > 0, rgba[..., :3] * 255.0 / np.maximum(a, 1e-6), 0)
    return _png(np.clip(np.rint(rgba), 0, 255).astype(np.uint8))


def _blur(a, r):
    """Two passes of a (2r+1)-wide box mean, zero outside the image."""
    import numpy as np

    n = 2 * r + 1
    for _ in range(2):
        s = np.zeros((a.shape[0] + n, a.shape[1] + n))
        s[1:, 1:] = np.pad(a, r).cumsum(0).cumsum(1)
        a = (s[n:, n:] - s[:-n, n:] - s[n:, :-n] + s[:-n, :-n]) / (n * n)
    return a


# (x, y, z) -> (screen x, screen y, depth), all in pitch; see geom.project
_TO_SCREEN = ((math.sqrt(3) / 2, -math.sqrt(3) / 2, 0.0),
              (0.5, 0.5, -1.0),
              (1.0, 1.0, 1.0))


def _occlusion(z, nrm, covered, px):
    """
    How much light each pixel keeps, 1 - AO_STRENGTH at most: darker where
    the surfaces round it stand nearer than its own face would - inside a
    hole, under a ledge, in the corner where two parts meet.  Each pixel's
    neighbourhood is compared against the plane of its own face, so a flat
    face, however slanted, is left alone, and so are its edges.
    `px` is raster pixels per pitch.
    """
    import numpy as np

    r = max(1, int(round(AO_RADIUS * px / 2)))   # two passes reach 2r
    m = covered.astype(np.float64)
    seen = np.maximum(_blur(m, r), 1e-6)
    ys, xs = np.indices(z.shape, dtype=np.float64)
    mean_z = _blur(np.where(covered, z, 0.0), r) / seen
    dx = _blur(m * xs, r) / seen - xs
    dy = _blur(m * ys, r) / seen - ys
    # The face's plane as depth over screen position: its normal through the
    # inverse of the projection.
    g = nrm.astype(np.float64) @ np.linalg.inv(np.array(_TO_SCREEN))
    facing = covered & (np.abs(g[..., 2]) > 0.05)
    gz = np.where(facing, g[..., 2], 1.0)
    plane = -(g[..., 0] * dx + g[..., 1] * dy) / gz / px
    occ = np.clip((mean_z - z - plane) / AO_DEPTH, 0.0, 1.0) * facing
    return (1.0 - AO_STRENGTH * occ).astype(np.float32)


def _shadow(covered, px, margin_px):
    """
    A soft shadow under the model, 0..SHADOW_ALPHA: its silhouette dropped a
    little and blurred, scaled down to fit the `margin_px` border.
    """
    import numpy as np

    drop, soft = SHADOW_DROP * px, SHADOW_BLUR * px
    reach = drop + soft           # two passes of soft / 2
    if reach > 0.8 * margin_px:
        drop, soft = (v * 0.8 * margin_px / reach for v in (drop, soft))
    drop, r = int(round(drop)), int(round(soft / 2))
    if r < 1:
        return np.zeros(covered.shape, np.float32)
    dropped = np.zeros(covered.shape)
    dropped[drop:] = covered[:covered.shape[0] - drop]
    return (_blur(dropped, r) * SHADOW_ALPHA).astype(np.float32)


RING_WIDTH = 2.2   # the line round new parts, against an outline


def _ring_new(lit, pid, out, alpha, rgb, width):
    """
    Paint a line `width` raster pixels wide round each of the step's new
    parts, as they show on screen: wherever one meets anything that is not
    itself.
    """
    import numpy as np

    H, W = lit.shape
    edge = np.zeros((H, W), bool)
    for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        here = (slice(max(0, -dy), H - max(0, dy)), slice(max(0, -dx), W - max(0, dx)))
        there = (slice(max(0, dy), H - max(0, -dy)), slice(max(0, dx), W - max(0, -dx)))
        edge[here] |= lit[here] & (pid[here] != pid[there])
    r = max(1, int(round(width / 2)))
    yy, xx = np.nonzero(edge)
    band = np.zeros((H, W), bool)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy > r * r + 0.5:
                continue
            y, x = yy + dy, xx + dx
            ok = (y >= 0) & (y < H) & (x >= 0) & (x < W)
            band[y[ok], x[ok]] = True
    out[band] = np.array(rgb, np.float32)
    alpha[band] = True


GUIDE_SLACK = 0.03  # pitch; a guide this close behind a surface still shows


def _guides(lines, rgb, z, out, alpha, scale, ox, oy, k, width):
    """
    Each guide line, hidden wherever a part is in front of it, with a dot
    where it goes into a hole: at both ends of every stretch of it that
    shows, as the printed guides mark the holes.
    """
    import numpy as np

    H, W = z.shape
    r = max(0.5, width / 2)
    reach = int(math.ceil(r))
    disc = [(dy, dx) for dy in range(-reach, reach + 1)
            for dx in range(-reach, reach + 1) if dx * dx + dy * dy <= r * r + 0.25]
    R = max(r * 1.5, HOLE_DOT * scale * k)   # fills the hole it marks
    big = int(math.ceil(R))
    dot = [(dy, dx) for dy in range(-big, big + 1)
           for dx in range(-big, big + 1) if dx * dx + dy * dy <= R * R + 0.25]
    for a, b in lines:
        (ax, ay), (bx, by) = (((x * scale + ox) * k, (y * scale + oy) * k)
                              for x, y in (project(a), project(b)))
        n = 2 * int(math.hypot(bx - ax, by - ay)) + 2
        t = np.linspace(0.0, 1.0, n)
        xs, ys = ax + (bx - ax) * t, ay + (by - ay) * t
        zs = depth(a) + (depth(b) - depth(a)) * t
        xc = np.clip(np.rint(xs).astype(int), 0, W - 1)
        yc = np.clip(np.rint(ys).astype(int), 0, H - 1)
        on = zs >= z[yc, xc] - GUIDE_SLACK
        for dy, dx in disc:
            xi = np.rint(xs + dx).astype(int)
            yi = np.rint(ys + dy).astype(int)
            ok = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
            xi, yi, zz = xi[ok], yi[ok], zs[ok]
            seen = zz >= z[yi, xi] - GUIDE_SLACK
            out[yi[seen], xi[seen]] = rgb
            alpha[yi[seen], xi[seen]] = True
        # Ends of each visible stretch long enough to be a line, not a
        # speck - where the line goes in behind a surface.
        edges = np.flatnonzero(np.diff(on.astype(np.int8)))
        ends = [i + 1 if on[i + 1] else i for i in edges]
        for i in ends:
            if 0 < i < n - 1:
                cx, cy = xs[i], ys[i]
                for dy, dx in dot:
                    xi, yi = int(round(cx + dx)), int(round(cy + dy))
                    if 0 <= xi < W and 0 <= yi < H:
                        out[yi, xi] = rgb
                        alpha[yi, xi] = True


HOLE_DOT = 0.16   # a hole's dot's radius, in pitch


def _png(rgba):
    """Encode an (h, w, 4) uint8 array, every row "Up"-filtered."""
    import numpy as np

    h, w, _ = rgba.shape
    up = rgba.astype(np.int16)
    up[1:] -= rgba[:-1]
    rows = np.empty((h, w * 4 + 1), np.uint8)
    rows[:, 0] = 2
    rows[:, 1:] = (up % 256).astype(np.uint8).reshape(h, w * 4)

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows.tobytes(), 9))
            + chunk(b"IEND", b""))
