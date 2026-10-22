"""
Turn VEX's official STEP models into the compressed meshes in iqdraw/cadmesh.py.

iqdraw itself needs nothing but the standard library; this script is the one
place OpenCascade is needed, and only when a mesh is added or regenerated:

    uv run --no-project --python 3.12 --with cadquery-ocp \\
        --with fast-simplification python tools/iqdraw-cadmesh.py \\
        [--write] [--extra DIR] STEPS [KEY ...]

STEPS is VEX's "VEX IQ All Parts" pack
(https://link.vex.com/cad/STEP/VEX-IQ-All-Parts-STEP) - the zip itself, or a
folder it was unpacked into.  Its files are named as VEX names them, "2x8
Beam (228-2500-023).step", which is how a PARTS entry's part number finds
its file.  With no KEY every entry in PARTS is made.

The pack has no electronics.  VEX publishes those as separate downloads - a
STEP file per 2nd-gen part, and a zip of the first-gen control system - so a
PARTS entry for one names its `file` instead, and DIR (--extra) is the
folder those downloads were saved in.  A `file` is a name in DIR, or
("some.zip", "member.STEP") for a file inside a zip there, matched by its
base name.  Without --extra, a run with no KEY makes the pack's parts and
skips these, as it always has.

The `_DATA` entries are printed to stdout; with --write they are put
straight into iqdraw/cadmesh.py instead, replacing an entry of the same key
or adding one at the end.  A one-line size report per part goes to stderr -
check its box against the frame below before trusting the mesh.

Each part is moved into iqdraw's frame, in pitch units (12.7 mm):

  flat   beams: length along +x, width along +y, hole 0 at the origin,
         mid-plane at z = 0 - the frame `Part.holes` already assumes
  axial  pins, shafts, standoffs, collars, wheels: axis along +z, centred
         on the origin unless a `z` offset says otherwise
  fixed  anything whose holes are not one rectangular grid - an L beam, a
         corner connector.  The STEP file's own frame, already in pitch
         with a hole at its origin, is turned by `rot` (degrees, X then Y
         then Z) and moved by `at` (pitch) - both read off the part, not
         guessed from its bounding box

Molded parts tessellate into far more triangles than a page needs - the
ribs on a beam are hundreds of tiny flat faces - so each mesh is then
decimated to a triangle budget, and its shading normals rebuilt so that
flat faces stay flat.

The six meshes that predate this script (beam_1x4, beam_1x7, beam_2x12 and
the three gears) came from an earlier generator that was not kept.
`beam_2x12` is listed here as the check that this one lands in the same
frame: it reproduces that mesh's bounding box exactly.

The mesh format is the one `cadmesh.cad_mesh` reads: point and triangle
counts, int16 coordinates quantised to 0.001 pitch, uint16 indices, then an
int8 shading normal per triangle corner; zlib'd and base85'd.
"""

import base64
import tempfile
import zipfile

import fast_simplification
import numpy as np
import math
import re
import struct
import sys
import zlib
from pathlib import Path

from OCP.BRep import BRep_Tool
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepLib import BRepLib_ToolTriangulatedShape
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.BRep import BRep_Builder
from OCP.TopoDS import TopoDS, TopoDS_Compound, TopoDS_Iterator

PITCH_MM = 12.7
Q = 1000.0

# Shading is smoothed only between faces within ~14 degrees of each other.
# Any looser and a flat face picks up its fillets' shading after decimation,
# and comes out blotchy; curved surfaces tessellate finer than this anyway.
SMOOTH = 0.97

# key -> (VEX part number, kind, extra).  `tris` is the triangle budget,
# sized against the meshes already bundled (beam_2x12 is ~7000).  A smooth
# curved part comes out cleaner tessellated coarsely than decimated - the
# hub decimated to shards - so it sets `deflect` (mm) and `angle` (radians)
# instead.  `z`
# shifts an axial part along its axis after centring, in pitch; `cap` says
# which end a capped shaft's cap belongs on.  `axes` names iqdraw's x, y and
# z as signed STEP axes, for a part whose box cannot say which way is which -
# an L-shaped beam is as wide as it is long - and then the STEP origin, which
# VEX puts on hole 0, stays the origin.  `file` takes the part from an
# --extra download instead of the pack (see the top of this file), and
# `shells` keeps only those top-level shapes of that file, by index (or by
# a tuple of indices for a shape nested further down): VEX
# models a motor's sleeve, core and socket as separate shells, so each can
# be its own key in its own colour, and the logo stickers are left out.
# `zcut` = (lo, hi) keeps the triangles whose lowest corner is in lo..hi,
# so one shell can be split between two keys in two colours.
MOTOR_STEP = "VEX-IQ-Smart-Motor-228-2560-.step"
MOTOR_AT = (22.15 / PITCH_MM, 0.5, 0.0)   # hole 0 is 22.15 mm off centre
BRAIN_STEP = "VEX-IQ-Robot-Brain-Gen-2-228-6480-.step"
BRAIN_AT = (3.5, 3.0, 6.2 / PITCH_MM)     # front strip's hole 0 to the origin
OMNI_STEP = "200mm-Travel-Omni-Directional-Wheel-228-2536-.step"
CONTROL_ZIP = ("VEX-IQ-All-Control-STEP.zip",)   # the first-gen control set
TOUCHLED_AT = (-6.2 / PITCH_MM, -6.2 / PITCH_MM, 0.48)

PARTS = {
    "beam_1x8":     ("228-2500-007", "flat",  {"w": 1, "l": 8, "tris": 2200}),
    "beam_2x8":     ("228-2500-023", "flat",  {"w": 2, "l": 8, "tris": 4700}),
    "beam_2x12":    ("228-2500-026", "flat",  {"w": 2, "l": 12, "tris": 7000}),
    "pin_1x1":      ("228-2500-060", "axial", {"tris": 800}),
    "standoff_4":   ("228-2500-070", "axial", {"z": 2.0, "tris": 1000}),
    "shaft_6":      ("228-2500-122", "axial", {"z": 2.5}),
    "capped_shaft_2": ("228-2500-080", "axial", {"z": 0.5, "cap": "-z"}),
    "collar":       ("228-2500-143", "axial", {}),
    "wheel_hub_44": ("228-2500-208", "axial", {"deflect": 0.3, "angle": 0.7}),
    "tyre_200":     ("228-2500-209", "axial", {"tris": 6000}),
    "beam_1x6":     ("228-2500-005", "flat",  {"w": 1, "l": 6, "tris": 1700}),
    "plate_4x4":    ("228-2500-040", "flat",  {"w": 4, "l": 4, "tris": 4700}),
    "lbeam_2x3":    ("228-2500-145", "fixed", {"rot": (180, 0, 0), "tris": 1300}),
    "lbeam_3x5":    ("228-2500-150", "fixed", {"rot": (0, 0, 180), "tris": 2200}),
    "connector_2w_1x2": ("228-2500-128", "fixed",
                         {"at": (0, 0, 0.5), "tris": 1500}),
    "connector_2w_2x1": ("228-2500-132", "fixed", {"tris": 1600}),
    "connector_2w_1x2_offset": ("228-2500-135", "fixed",
                                {"at": (0, 0, 1.0), "tris": 1800}),
    # the 1x2 pin keeps its STEP origin, which is the ridge: the joint face
    "pin_1x2":      ("228-2500-061", "axial", {"z": -0.25, "tris": 1000}),
    "pin_2x2":      ("228-2500-062", "axial", {"tris": 1200}),
    "standoff_1":   ("228-2500-065", "axial", {"z": 0.5, "tris": 600}),
    "shaft_4":      ("228-2500-120", "axial", {"z": 1.5}),
    "plastic_shaft_2": ("228-2500-074", "axial", {"z": 0.5}),
    "beam_1x10":    ("228-2500-009", "flat",  {"w": 1, "l": 10, "tris": 2700}),
    "lockbeam_1x3": ("228-2500-141", "flat",  {"w": 1, "l": 3, "tris": 900}),
    "standoff_half": ("228-2500-064", "axial", {"z": 0.25, "tris": 500}),
    "standoffconn_mini": ("228-2500-170", "axial", {"tris": 600}),
    "capped_shaft_3": ("228-2500-081", "axial", {"z": 1.0, "cap": "-z"}),
    # ridge at the -z end, its motor tip beyond it - the STEP file has both
    # at +z, and the ridge is too slight for `cap` to find by girth
    "plastic_motor_shaft_3": ("228-2500-094", "fixed",
                              {"rot": (180, 0, 0), "at": (0, 0, 0.78)}),
    # centred on its centre hole, so it reads the same either way up
    "connector_triple_2x2": ("228-2500-1253", "fixed",
                             {"at": (-0.5, 0, 1.0), "tris": 2400}),
    "connector_2w_2x2_offset": ("228-2500-136", "fixed",
                                {"at": (0, 0, 1.0), "tris": 2000}),
    "beam_2x2":     ("228-2500-017", "flat",  {"w": 2, "l": 2, "tris": 1200}),
    # origin on the underside of the head, the face it is pushed against
    "pin_0x2":      ("228-2500-086", "fixed", {"at": (0, 0, 0.44), "tris": 900}),
    # metal motor shaft: origin on the ridge, the long side up +z, its
    # short motor tip below
    "motorshaft_3": ("228-2500-2236", "fixed",
                     {"rot": (180, 0, 0), "at": (0, 0, -0.28)}),
    "capped_shaft_5": ("228-2500-2225", "axial", {"z": 2.0, "cap": "-z"}),
    "washer":       ("228-2500-112", "axial", {}),
    # boss down -z, the drilled disc on z = 0..0.5
    "lockbeam_round_2x2": ("228-2500-1925", "fixed",
                           {"rot": (90, 0, 0), "at": (0, 0, 0.25),
                            "tris": 1600}),
    "beam_1x2":     ("228-2500-001", "flat",  {"w": 1, "l": 2, "tris": 700}),
    "beam_2x6":     ("228-2500-021", "flat",  {"w": 2, "l": 6, "tris": 3600}),
    "spacer":       ("228-2500-114", "axial", {}),
    "motorshaft_2": ("228-2500-2234", "fixed",
                     {"rot": (180, 0, 0), "at": (0, 0, -0.28)}),
    # straight leg's end hole at the origin, corner at (2, 0), the bent leg
    # turning 60 degrees anticlockwise from there
    "anglebeam_3x3_60": ("228-2500-149", "fixed",
                         {"rot": (0, 180, 0), "at": (2, 0, 0), "tris": 1700}),
    # the same layout, its bent leg turning 45 degrees instead
    "anglebeam_3x3_45": ("228-2500-148", "fixed",
                         {"rot": (0, 180, 0), "at": (2, 0, 0), "tris": 1700}),
    "connector_chassis_large": ("228-2500-126", "fixed",
                                {"at": (0, -0.5, 0.5), "tris": 2000}),
    "beam_2x16":    ("228-2500-028", "flat",  {"w": 2, "l": 16, "tris": 9300}),
    "standoff_2":   ("228-2500-067", "axial", {"z": 1.0, "tris": 700}),
    "beam_offset_4x4": ("228-2500-151", "flat", {"axes": ("+y", "-x", "+z"),
                                                 "tris": 3000}),
    "shaft_8":      ("228-2500-124", "axial", {"z": 3.5}),
    "pulley_20":    ("228-2500-164", "axial", {"tris": 1500}),
    "plate_4x12":   ("228-2500-045", "flat",  {"w": 4, "l": 12, "tris": 12000}),
    # gear round hole 0 at the origin, the arm along +x to hole 3
    "crankarm_1x4": ("228-2500-246", "fixed", {"rot": (0, 0, -90), "tris": 2600}),
    # its two pegs down -z at x = 0 and 1, tips at z = -0.5, the pad on top
    "tractionlink": ("228-2500-239", "fixed",
                     {"rot": (90, 0, 0), "at": (0, 1.43, -0.45), "tris": 1200}),
    # ---- electronics, from VEX's separate downloads (--extra) ----
    # Smart Motor face up: the face is z = 0 and the housing hangs to
    # z = -3.97, hole 0 at the origin, rows y = 0 and 1, the socket at
    # (2.5, 0.5).  Shell 1 is the face and core, 3 the sleeve, 0 the socket;
    # the face is drawn darker than the rest, as the build guides draw it.
    "motor_face":   ("228-2560", "fixed", {"file": MOTOR_STEP, "shells": (1,),
                                           "rot": (-90, 0, 0), "at": MOTOR_AT,
                                           "zcut": (-0.85, 1)}),
    # the core under the sleeve, in the sleeve's colour: it shows through
    # the sleeve's cut-outs, and where the two overlap the depth sort has
    # no second colour to stripe through
    "motor_core":   ("228-2560", "fixed", {"file": MOTOR_STEP, "shells": (1,),
                                           "rot": (-90, 0, 0), "at": MOTOR_AT,
                                           "zcut": (-9, -0.85)}),
    "motor":        ("228-2560", "fixed", {"file": MOTOR_STEP, "shells": (3,),
                                           "rot": (-90, 0, 0), "at": MOTOR_AT}),
    "motor_socket": ("228-2560", "fixed", {"file": MOTOR_STEP, "shells": (0,),
                                           "rot": (-90, 0, 0), "at": MOTOR_AT}),
    # Robot Brain (2nd gen) screen up: front strip's hole 0 at the origin,
    # back strip at y = 6, the front face y = 0.  Shell 0 is the case, split
    # at z = 1.9 so its lid can be drawn dark as the builds draw it; 9 is the
    # band of ports, 8 the screen, 1-7 the buttons and logo.
    "brain":        ("228-6480", "fixed", {"file": BRAIN_STEP, "shells": (0,),
                                           "at": BRAIN_AT, "zcut": (-9, 1.9),
                                           "tris": 8000}),
    "brain_lid":    ("228-6480", "fixed", {"file": BRAIN_STEP, "shells": (0,),
                                           "at": BRAIN_AT, "zcut": (1.9, 9),
                                           "tris": 4000}),
    "brain_ports":  ("228-6480", "fixed", {"file": BRAIN_STEP, "shells": (9,),
                                           "at": BRAIN_AT}),
    "brain_screen": ("228-6480", "fixed", {"file": BRAIN_STEP, "shells": (8,),
                                           # a hair above the lid's recess, or
                                           # the depth sort hides it
                                           "at": BRAIN_AT[:2]
                                           + (BRAIN_AT[2] + 0.02,)}),
    "brain_buttons": ("228-6480", "fixed", {"file": BRAIN_STEP,
                                            "shells": (1, 2, 3, 4, 5, 6, 7),
                                            "at": BRAIN_AT}),
    # 200 mm omni wheel along +z, centred on its axle midway across the
    # rollers; the hub's pin face, drilled for a lock beam, is the +z side
    "omni_hub_200": ("228-2536", "fixed", {"file": OMNI_STEP, "shells": (0,),
                                           "rot": (90, 0, 0), "tris": 6000}),
    "omni_rollers_200": ("228-2536", "fixed", {"file": OMNI_STEP,
                                               # each roller's outside only
                                               "shells": tuple((k, 2) for k in
                                                               range(1, 15)),
                                               "rot": (90, 0, 0), "deflect": 0.3,
                                               "angle": 0.7, "tris": 6000}),
    # pair at x = 0, 1 on z = 0, centre hole at (0.5, 0.5), pegs up and down
    "connector_2w_1x2_offset_double": ("228-2500-274", "fixed",
                                       {"at": (1, 0, -0.5), "tris": 1800}),
    # the 2x2 center lock beam, centred on its square hole
    "lockbeam_2x2": ("228-2500-140", "fixed", {"tris": 1200}),
    # Touch LED (the same part with either brain), button up: underside on
    # z = 0, its 2x2 square of holes at (0..1, 0..1).  Shell 0 is the body
    # and 3 the base, 1 and 2 the button; 4, the light pipe, is hidden.
    "touchled":     ("228-3010", "fixed", {"file": CONTROL_ZIP + ("228-3010.STEP",),
                                           "shells": (0, 3), "rot": (90, 0, 180),
                                           "at": TOUCHLED_AT}),
    "touchled_button": ("228-3010", "fixed", {"file": CONTROL_ZIP + ("228-3010.STEP",),
                                              "shells": (1, 2), "rot": (90, 0, 180),
                                              "at": TOUCHLED_AT}),
}


def load(path, shells=None):
    reader = STEPControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        sys.exit(f"{path}: not a readable STEP file")
    reader.TransferRoots()
    shape = reader.OneShape()
    if shells is None:
        return shape

    def child(shape, i):
        kids, it = [], TopoDS_Iterator(shape)
        while it.More():
            kids.append(it.Value())
            it.Next()
        if i >= len(kids):
            sys.exit(f"{path}: a shape has {len(kids)} children, not {i + 1}")
        return kids[i]

    out, builder = TopoDS_Compound(), BRep_Builder()
    builder.MakeCompound(out)
    for index in shells:
        part = shape
        for i in index if isinstance(index, tuple) else (index,):
            part = child(part, i)
        builder.Add(out, part)
    return out


def triangulate(shape, deflect, angle):
    """Outward-wound triangles in mm, with a shading normal per corner."""
    BRepMesh_IncrementalMesh(shape, deflect, False, angle, True)
    tris = []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face(exp.Current())
        loc = TopLoc_Location()
        poly = BRep_Tool.Triangulation_s(face, loc)
        exp.Next()
        if poly is None:
            continue
        if not poly.HasNormals():
            BRepLib_ToolTriangulatedShape.ComputeNormals_s(face, poly)
        trsf = loc.Transformation()
        flip = face.Orientation() == TopAbs_REVERSED
        pts, nrm = [], []
        for i in range(1, poly.NbNodes() + 1):
            p = poly.Node(i).Transformed(trsf)
            n = poly.Normal(i).Transformed(trsf)
            s = -1.0 if flip else 1.0
            pts.append((p.X(), p.Y(), p.Z()))
            nrm.append((s * n.X(), s * n.Y(), s * n.Z()))
        for i in range(1, poly.NbTriangles() + 1):
            a, b, c = poly.Triangle(i).Get()
            if flip:
                b, c = c, b
            tris.append([(pts[k - 1], nrm[k - 1]) for k in (a, b, c)])
    return tris


def bbox(tris):
    vs = [p for t in tris for p, _ in t]
    return [(min(v[i] for v in vs), max(v[i] for v in vs)) for i in range(3)]


def frame(tris, kind, extra):
    """
    Rotate and move the part into iqdraw's frame and convert to pitch.

    Axes are assigned by bounding-box size, which is unambiguous for every
    part here: a beam is longest along its length and thinnest through its
    thickness; an axial part's axis is the one dimension that differs from
    the other two.
    """
    if kind == "fixed":
        return fixed_frame(tris, extra.get("rot", (0, 0, 0)),
                           extra.get("at", (0, 0, 0)))
    if "axes" in extra:
        axes = ["xyz".index(a[1]) for a in extra["axes"]]
        sign = [1.0 if a[0] == "+" else -1.0 for a in extra["axes"]]
        rot = [[sign[k] if axes[k] == i else 0.0 for i in range(3)]
               for k in range(3)]
        assert np.linalg.det(rot) > 0, "axes must keep the frame right-handed"
        return [[(tuple(sign[k] * p[axes[k]] / PITCH_MM for k in range(3)),
                  tuple(sign[k] * n[axes[k]] for k in range(3)))
                 for p, n in t] for t in tris]

    box = bbox(tris)
    size = [hi - lo for lo, hi in box]
    order = sorted(range(3), key=lambda i: size[i])  # thinnest first
    if kind == "flat":
        x, y, z = order[2], order[1], order[0]
    else:
        # the odd one out: a shaft's long axis, a collar's short one
        lo_gap = size[order[1]] - size[order[0]]
        hi_gap = size[order[2]] - size[order[1]]
        z = order[2] if hi_gap > lo_gap else order[0]
        x, y = [i for i in range(3) if i != z]
    axes = [x, y, z]
    # keep the frame right-handed, so windings stay outward
    sign = [1.0, 1.0, 1.0]
    perm_even = sum(1 for i in range(3) for j in range(i + 1, 3)
                    if axes[i] > axes[j]) % 2 == 0
    if not perm_even:
        sign[1] = -1.0

    centre = [(lo + hi) / 2 for lo, hi in box]
    if kind == "flat":
        offset = ((extra["l"] - 1) / 2, (extra["w"] - 1) / 2, 0.0)
    else:
        offset = (0.0, 0.0, extra.get("z", 0.0))

    def move(p, n):
        q = tuple(sign[k] * (p[axes[k]] - centre[axes[k]]) / PITCH_MM + offset[k]
                  for k in range(3))
        m = tuple(sign[k] * n[axes[k]] for k in range(3))
        return q, m

    out = [[move(p, n) for p, n in t] for t in tris]

    cap = extra.get("cap")
    if cap:
        # The capped end is the fatter one.  Flip end for end if it came out
        # on the wrong side - a half turn about x keeps the frame right-handed.
        lo_z = min(p[2] for t in out for p, _ in t)
        hi_z = max(p[2] for t in out for p, _ in t)

        def girth(zz):
            return max((math.hypot(p[0], p[1]) for t in out for p, _ in t
                        if abs(p[2] - zz) < 0.1), default=0.0)

        cap_low = girth(lo_z) > girth(hi_z)
        if cap_low != (cap == "-z"):
            mid = (lo_z + hi_z) / 2
            out = [[((p[0], -p[1], 2 * mid - p[2]), (n[0], -n[1], -n[2]))
                    for p, n in t] for t in out]
    return out


def fixed_frame(tris, rot, at):
    """Turn the STEP frame by `rot` (degrees, X then Y then Z), move by `at`."""
    rx, ry, rz = (math.radians(a) for a in rot)
    cx, sx, cy, sy, cz, sz = (math.cos(rx), math.sin(rx), math.cos(ry),
                              math.sin(ry), math.cos(rz), math.sin(rz))
    m = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]) @ \
        np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]) @ \
        np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    m = np.round(m, 9)

    def move(p, n):
        q = m @ (np.array(p) / PITCH_MM) + np.array(at, dtype=float)
        return tuple(float(c) for c in q), tuple(float(c) for c in m @ n)

    return [[move(p, n) for p, n in t] for t in tris]


def decimate(tris, budget):
    """Quadric-decimate to `budget` triangles and rebuild shading normals."""
    if len(tris) <= budget:
        return tris
    index, pts, faces = {}, [], []
    for t in tris:
        ids = []
        for p, _ in t:
            k = tuple(round(c * 1e4) for c in p)
            if k not in index:
                index[k] = len(pts)
                pts.append(p)
            ids.append(index[k])
        if len(set(ids)) == 3:
            faces.append(ids)
    pts, faces = fast_simplification.simplify(
        np.array(pts, dtype=np.float64), np.array(faces, dtype=np.int64),
        target_count=budget)

    tri_pts = pts[faces]
    normals = np.cross(tri_pts[:, 1] - tri_pts[:, 0], tri_pts[:, 2] - tri_pts[:, 0])
    area = np.linalg.norm(normals, axis=1)
    keep = area > 1e-12
    faces, tri_pts, normals, area = faces[keep], tri_pts[keep], normals[keep], area[keep]
    unit = normals / area[:, None]

    touching = [[] for _ in range(len(pts))]
    for fi, f in enumerate(faces):
        for v in f:
            touching[v].append(fi)

    out = []
    for fi, f in enumerate(faces):
        corners = []
        for v in f:
            # smooth across neighbours that are nearly coplanar with this
            # face, and nothing else, so a hard edge stays hard
            near = [g for g in touching[v] if unit[g] @ unit[fi] >= SMOOTH]
            n = (normals[near]).sum(axis=0)
            n = n / (np.linalg.norm(n) or 1.0)
            corners.append((tuple(pts[v]), tuple(n)))
        out.append(corners)
    return out


def encode(tris):
    index, points, triangles, smooth = {}, [], [], []
    for t in tris:
        ids = []
        for p, n in t:
            k = tuple(round(c * Q) for c in p)
            if k not in index:
                index[k] = len(points)
                points.append(k)
            ids.append(index[k])
            length = math.sqrt(sum(c * c for c in n)) or 1.0
            smooth.append(tuple(max(-127, min(127, round(127 * c / length)))
                                for c in n))
        if len(set(ids)) < 3:
            smooth[-3:] = []  # collapsed by quantisation
            continue
        triangles.append(ids)
    if len(points) > 0xFFFF:
        sys.exit(f"{len(points)} points will not fit uint16 indices - "
                 "raise `deflect` for this part")
    raw = struct.pack("<II", len(points), len(triangles))
    raw += struct.pack(f"<{len(points) * 3}h", *[c for p in points for c in p])
    raw += struct.pack(f"<{len(triangles) * 3}H", *[i for t in triangles for i in t])
    raw += struct.pack(f"<{len(smooth) * 3}b", *[c for n in smooth for c in n])
    return base64.b85encode(zlib.compress(raw, 9)).decode(), len(points), len(triangles)


def find(steps, number, scratch):
    """The STEP file for a VEX part number, from the pack's zip or folder."""
    pattern = re.compile(rf"\({re.escape(number)}\)\.ste?p$", re.I)
    if zipfile.is_zipfile(steps):
        with zipfile.ZipFile(steps) as z:
            hits = [n for n in z.namelist() if pattern.search(n)]
            if hits:
                out = Path(scratch) / f"{number}.step"
                out.write_bytes(z.read(hits[0]))
                return out
    else:
        hits = [p for p in Path(steps).rglob("*") if pattern.search(p.name)]
        if hits:
            return hits[0]
    sys.exit(f"no STEP file for {number} in {steps}")


def find_extra(extra, file, scratch):
    """An --extra download: a file in folder `extra`, or (zip, member) in it."""
    if extra is None:
        sys.exit(f"{file} is not in the parts pack - pass --extra DIR")
    if isinstance(file, str):
        path = Path(extra) / file
        if not path.is_file():
            sys.exit(f"no {file} in {extra}")
        return path
    archive, member = file
    with zipfile.ZipFile(Path(extra) / archive) as z:
        hits = [n for n in z.namelist() if Path(n).name == member]
        if len(hits) != 1:
            sys.exit(f"{len(hits)} files named {member} in {archive}")
        out = Path(scratch) / member
        out.write_bytes(z.read(hits[0]))
        return out


CADMESH = Path(__file__).resolve().parents[1] / "cadmesh.py"


def write_entry(key_src, entry):
    """Replace the entry spelled `key_src` in cadmesh.py, or add it to _DATA."""
    s = CADMESH.read_text()
    pat = re.compile(rf"    {re.escape(key_src)}: \(\n.*?\n    \),\n", re.S)
    if pat.search(s):
        s = pat.sub(lambda m: entry, s, count=1)
    else:
        end = "}\n\n\ndef cad_mesh"
        assert s.count(end) == 1, "cannot find the end of _DATA in cadmesh.py"
        s = s.replace(end, entry + end)
    CADMESH.write_text(s)


def main(argv):
    write = "--write" in argv
    argv = [a for a in argv if a != "--write"]
    extra = None
    if "--extra" in argv:
        i = argv.index("--extra")
        extra = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if not argv:
        sys.exit(__doc__)
    steps, keys = argv[0], argv[1:]
    if not keys:
        keys = [k for k in PARTS if extra or "file" not in PARTS[k][2]]
    unknown = [k for k in keys if k not in PARTS]
    if unknown:
        sys.exit(f"not in PARTS: {', '.join(unknown)} - add an entry first")
    scratch = tempfile.mkdtemp(prefix="iqdraw-cadmesh-")
    for key in keys:
        number, kind, opts = PARTS[key]
        path = (find_extra(extra, opts["file"], scratch) if "file" in opts
                else find(steps, number, scratch))
        shape = load(path, opts.get("shells"))
        tris = frame(triangulate(shape, opts.get("deflect", 0.1),
                                 opts.get("angle", 0.5)), kind, opts)
        if "zcut" in opts:
            lo, hi = opts["zcut"]
            tris = [t for t in tris if lo <= min(p[2] for p, _ in t) < hi]
        tris = decimate(tris, opts.get("tris", len(tris)))
        data, n_pts, n_tri = encode(tris)
        box = bbox(tris)
        print(f"{key}: {n_pts} points, {n_tri} triangles, {len(data)} bytes, "
              "box " + " ".join(f"{lo:.3f}..{hi:.3f}" for lo, hi in box),
              file=sys.stderr)
        lines = "".join(f'        "{data[i:i + 100]}"\n'
                        for i in range(0, len(data), 100))
        # cadmesh.py spells keys with double quotes; repr() would not
        key_src = f'"{key}"' if isinstance(key, str) else repr(key)
        entry = f"    {key_src}: (\n{lines}    ),\n"
        if write:
            write_entry(key_src, entry)
        else:
            print(entry, end="")


if __name__ == "__main__":
    main(sys.argv[1:])
