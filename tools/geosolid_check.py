#!/usr/bin/env python3
"""Runs geosolid.v.pica, and the shader it replaced, on the same vertices.

TASKS 46 cut the solid shader from 31 instructions a vertex to 17: the
model-view and the projection became one matrix, and the fog's row and the
light's direction are carried into the model's space, once a model on the
CPU (`3DS Files/source/geosolidunif.c`). Neither Azahar nor a capture
shows a fault in that until it is on the screen, so this runs the shaders
here, through a PICA200 interpreter of its own, and compares what they
hand the rasteriser.

  - Both shaders are assembled with devkitPro's picasso: the game's
    (geosolid.v.pica linked with geolit.v.pica, as the Makefile links
    them) and the reference, `tools/src/geosolid_ref.v.pica`, which is
    geosolid.v.pica as it was at 846bcde.
  - The reference's uniforms are the old ones: the projection, the
    model-view, the light in view space and the fog's view-space row. The
    new shader's are what `geosolidunif.c` makes of the same, built for
    the host with `tools/src/geosolid_test.c`.
  - The scenes: the race's view (Mtx_PerspTilt), an envmap face
    (Mtx_Persp at 90 degrees), the mirror, and the screen quads' and the
    sprites' mappings; scenery drawn where it lies, thousands of units from
    the origin, and cars, small and turned; vertices inside the view and
    outside it, with random normals, colours and texture coordinates.

Every output is compared. In float32 the two must agree to within
rounding: the position to 1/100 of a pixel and 16 of the depth buffer's
2^24 steps, the colour to 1/100 of a step, the texture coordinates and
the fog exactly or to rounding. The PICA's own floats have 16 bits of
mantissa, so the run is made again with every value rounded to that, and
each shader's error against the exact (float64) result is reported: the
new one must be no worse than the old by more than a quarter.

The interpreter is checked first: the reference shader's float32 outputs
against the old shader's arithmetic done directly in numpy.

The lit shader, geolit.v.pica, takes the same `mvp` and `fogModel`: a
car's environment pass meets the solid pass's depth with GEQUAL, so the two
must give a vertex the same position to the bit. The check is that both
DVLEs give those names the same registers and that the lit shader's
position and fog, run as far as it can be here, equal the solid's.

    python tools/geosolid_check.py
    python tools/geosolid_check.py --mutate
"""
import argparse
import math
import os
import random
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "3DS Files" / "source"
PICASSO = Path("C:/devkitPro/tools/bin/picasso.exe")
SHADERS = [SRC / "geosolid.v.pica", SRC / "geolit.v.pica"]
REFERENCE = ROOT / "tools" / "src" / "geosolid_ref.v.pica"
UNIF_C = SRC / "geosolidunif.c"
HARNESS = ROOT / "tools" / "src" / "geosolid_test.c"
NL = chr(10)

GEO_FOG_STEPS = 128
GEO_FOG_TEX_W = 256

# The outputs' semantics in a DVLE's output table.
OUT_POSITION, OUT_COLOR, OUT_TEX0, OUT_TEX1 = 0, 2, 3, 5

# ================================================================ the shbin


def assemble(sources, tmp, name):
    out = Path(tmp) / (name + ".shbin")
    r = subprocess.run([str(PICASSO), "-o", str(out)] + [str(s) for s in sources],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, (r.stdout + r.stderr).strip()
    return out.read_bytes(), ""


def f24(u):
    """A float24 constant's bits as a float."""
    u &= 0xffffff
    s, e, m = u >> 23, (u >> 16) & 0x7f, u & 0xffff
    if e == 0:
        return -0.0 if s else 0.0
    if e == 0x7f:
        return float("-inf") if s else float("inf")
    v = math.ldexp(1.0 + m / 65536.0, e - 63)
    return -v if s else v


class Dvle:
    pass


def parse(data):
    assert data[:4] == b"DVLB", "not a DVLB"
    n, = struct.unpack_from("<I", data, 4)
    offs = struct.unpack_from("<%dI" % n, data, 8)
    dvlp = 8 + 4 * n
    w = struct.unpack_from("<7I", data, dvlp)
    code = struct.unpack_from("<%dI" % w[3], data, dvlp + w[2])
    ops = [x & 0xffffffff for x in
           struct.unpack_from("<%dQ" % w[5], data, dvlp + w[4])]
    dvles = []
    for o in offs:
        e = struct.unpack_from("<16I", data, o)
        d = Dvle()
        d.main = e[2]
        d.consts = []
        for j in range(e[7]):
            typ, reg = struct.unpack_from("<HH", data, o + e[6] + 20 * j)
            vals = struct.unpack_from("<4I", data, o + e[6] + 20 * j + 4)
            d.consts.append((typ & 0xff, reg, vals))
        d.outs = []
        for j in range(e[11]):
            typ, reg, mask = struct.unpack_from("<HHH", data, o + e[10] + 8 * j)
            d.outs.append((typ, reg, mask))
        d.unifs = {}
        sym = o + e[14]
        for j in range(e[13]):
            so, start, end = struct.unpack_from("<IHH", data, o + e[12] + 8 * j)
            name = data[sym + so:data.index(b"\0", sym + so)].decode()
            d.unifs[name] = (start, end)
        dvles.append(d)
    return code, ops, dvles


def straight_length(code, main):
    pc = main
    while code[pc] >> 26 != 0x22:
        pc += 1
    return pc - main


# =========================================================== the interpreter

def round24(x):
    """Each float32 rounded to the PICA's 16 bits of mantissa (nearest)."""
    x = np.ascontiguousarray(x, dtype=np.float32)
    b = x.view(np.uint32).astype(np.uint64)
    b = (b + 0x3f + ((b >> 7) & 1)) & ~np.uint64(0x7f)
    return (b & 0xffffffff).astype(np.uint32).view(np.float32)


class Unsupported(Exception):
    pass


def run(code, ops, dvle, inputs, unif, fp24=False, partial=False):
    """The DVLE's main on every vertex at once. `inputs` maps v0.. to (N,
    4) float32 arrays, `unif` is (96, 4) float32. Returns the output
    registers and how often each component was written. `partial` stops
    at the first instruction this does not know rather than failing."""
    n = next(iter(inputs.values())).shape[0]
    unif = unif.astype(np.float32).copy()
    for typ, reg, vals in dvle.consts:
        if typ == 2:
            unif[reg] = [f24(v) for v in vals]
    if fp24:
        unif = round24(unif)
        inputs = {k: round24(v) for k, v in inputs.items()}
    r = np.zeros((16, n, 4), np.float32)
    o = np.zeros((16, n, 4), np.float32)
    count = np.zeros((16, 4), int)

    def src(reg, neg, swz):
        if reg < 0x10:
            v = inputs.get(reg)
            if v is None:
                v = np.tile(np.array([0, 0, 0, 1], np.float32), (n, 1))
        elif reg < 0x20:
            v = r[reg - 0x10]
        else:
            v = np.broadcast_to(unif[reg - 0x20], (n, 4))
        sel = [(swz >> 6) & 3, (swz >> 4) & 3, (swz >> 2) & 3, swz & 3]
        v = v[:, sel]
        return -v if neg else v

    pc = dvle.main
    for _ in range(4096):
        ins = code[pc]
        op = ins >> 26
        if op == 0x22:                                  # END
            return o, count
        if op == 0x21:                                  # NOP
            pc += 1
            continue
        if op >= 0x30:                                  # MADI, MAD
            desc = ops[ins & 0x1f]
            dst = (ins >> 24) & 0x1f
            if op >= 0x38:
                s1, s2, s3 = (ins >> 17) & 0x1f, (ins >> 10) & 0x7f, (ins >> 5) & 0x1f
            else:
                s1, s2, s3 = (ins >> 17) & 0x1f, (ins >> 12) & 0x1f, (ins >> 5) & 0x7f
            if (ins >> 22) & 3:
                raise Unsupported("pc %d: an address register" % pc)
            a = src(s1, desc >> 4 & 1, desc >> 5 & 0xff)
            b = src(s2, desc >> 13 & 1, desc >> 14 & 0xff)
            c = src(s3, desc >> 22 & 1, desc >> 23 & 0xff)
            res = (a * b).astype(np.float32) + c
        elif op <= 0x1b:
            desc = ops[ins & 0x7f]
            dst = (ins >> 21) & 0x1f
            if (ins >> 19) & 3:
                raise Unsupported("pc %d: an address register" % pc)
            if op in (0x18, 0x1a, 0x1b):
                s1, s2 = (ins >> 14) & 0x1f, (ins >> 7) & 0x7f
            else:
                s1, s2 = (ins >> 12) & 0x7f, (ins >> 7) & 0x1f
            a = src(s1, desc >> 4 & 1, desc >> 5 & 0xff)
            b = src(s2, desc >> 13 & 1, desc >> 14 & 0xff)
            if op == 0x00:                              # ADD
                res = a + b
            elif op == 0x01:                            # DP3
                d = (a[:, 0] * b[:, 0] + a[:, 1] * b[:, 1]) + a[:, 2] * b[:, 2]
                res = np.repeat(d[:, None], 4, 1)
            elif op == 0x02:                            # DP4
                d = ((a[:, 0] * b[:, 0] + a[:, 1] * b[:, 1])
                     + a[:, 2] * b[:, 2]) + a[:, 3] * b[:, 3]
                res = np.repeat(d[:, None], 4, 1)
            elif op == 0x08:                            # MUL
                res = a * b
            elif op == 0x0b:                            # FLR
                res = np.floor(a)
            elif op == 0x0c:                            # MAX
                res = np.where(a > b, a, b)
            elif op == 0x0d:                            # MIN
                res = np.where(a < b, a, b)
            elif op == 0x0e:                            # RCP
                res = np.repeat((1.0 / a[:, 0:1]).astype(np.float32), 4, 1)
            elif op == 0x0f:                            # RSQ
                res = np.repeat((1.0 / np.sqrt(a[:, 0:1])).astype(np.float32), 4, 1)
            elif op == 0x05:                            # EX2
                res = np.repeat(np.exp2(a[:, 0:1]), 4, 1)
            elif op == 0x06:                            # LG2
                res = np.repeat(np.log2(a[:, 0:1]), 4, 1)
            elif op == 0x13:                            # MOV
                res = a
            else:
                if partial:
                    return o, count
                raise Unsupported("pc %d: opcode 0x%02x" % (pc, op))
        else:
            if partial:
                return o, count
            raise Unsupported("pc %d: opcode 0x%02x" % (pc, op))
        res = res.astype(np.float32)
        if fp24:
            res = round24(res)
        mask = desc & 0xf
        comps = [i for i in range(4) if mask >> (3 - i) & 1]
        if dst < 0x10:
            o[dst][:, comps] = res[:, comps]
            for i in comps:
                count[dst, i] += 1
        else:
            r[dst - 0x10][:, comps] = res[:, comps]
        pc += 1
    raise Unsupported("no END in 4096 instructions")


def outputs(dvle, o, count):
    """The DVLE's outputs by semantic: (N, 4) arrays of the components the
    table maps, the rest NaN."""
    res = {}
    for typ, reg, mask in dvle.outs:
        a = res.setdefault(typ, np.full((o.shape[1], 4), np.nan, np.float32))
        for i in range(4):
            if mask >> i & 1:
                a[:, i] = o[reg][:, i]
    return res


# =============================================================== the scenes

def fog_s(u):
    return (u * GEO_FOG_STEPS + 0.5) / GEO_FOG_TEX_W


def persp(fovy, aspect, near, far):
    """citro3d's Mtx_Persp (right-handed): depth -1..0."""
    t = math.tan(fovy / 2)
    m = np.zeros((4, 4))
    m[0, 0] = 1 / (aspect * t)
    m[1, 1] = 1 / t
    m[2, 3] = far * near / (near - far)
    m[3, 2] = -1.0
    m[2, 2] = -m[3, 2] * near / (near - far)
    return m


def persp_tilt(fovy, aspect, near, far):
    """citro3d's Mtx_PerspTilt: x and y swapped for the screen's turn."""
    t = math.tan(fovy / 2)
    m = np.zeros((4, 4))
    m[0, 1] = 1 / t
    m[1, 0] = -1 / (t * aspect)
    m[2, 3] = far * near / (near - far)
    m[3, 2] = -1.0
    m[2, 2] = -m[3, 2] * near / (near - far)
    return m


def ortho_tilt(l, r, b, t, n, f):
    """citro3d's Mtx_OrthoTilt, right-handed."""
    m = np.zeros((4, 4))
    m[0, 1] = 2 / (t - b)
    m[0, 3] = (b + t) / (b - t)
    m[1, 0] = 2 / (l - r)
    m[1, 3] = (l + r) / (r - l)
    m[2, 2] = 1 / (n - f)
    m[2, 3] = 0.5 * (n + f) / (n - f) - 0.5
    m[3, 3] = 1.0
    return m


def rot(rng):
    a, b, c = (rng.uniform(-math.pi, math.pi) for _ in range(3))
    rx = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)],
                   [0, math.sin(a), math.cos(a)]])
    ry = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0],
                   [-math.sin(b), 0, math.cos(b)]])
    rz = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0],
                   [0, 0, 1]])
    return rz @ ry @ rx


def affine(r3, t):
    m = np.eye(4)
    m[:3, :3] = r3
    m[:3, 3] = t
    return m


class Scene:
    pass


def make_scenes(seed):
    rng = random.Random(seed)
    scenes = []
    kinds = [("view", "scenery"), ("view", "car"), ("envmap", "scenery"),
             ("envmap", "car"), ("mirror", "scenery"), ("view", "far"),
             ("screen", "quad"), ("sprite", "quad")]
    for k in range(48):
        proj_kind, model_kind = kinds[k % len(kinds)]
        s = Scene()
        s.name = "%s/%s #%d" % (proj_kind, model_kind, k)
        near, far = rng.choice([(0.5, 10000.0), (1.0, 10000.0), (2.0, 5000.0),
                                (0.25, 32.0)])
        if proj_kind == "view":
            s.proj = persp_tilt(math.radians(rng.uniform(40, 80)), 400 / 240,
                                near, far)
        elif proj_kind == "envmap":
            s.proj = persp(math.radians(90), 1.0, near, far)
        elif proj_kind == "mirror":
            s.proj = persp(math.radians(rng.uniform(30, 60)), 2.5, near, far)
        else:
            s.proj = ortho_tilt(0, 400, 240, 0, 1, -1)
            if proj_kind == "sprite":
                s.proj[2] = [0, 0, -1, 0]
        s.near, s.far = near, far
        if model_kind == "quad":
            s.mv = np.eye(4)
        else:
            cam = np.array([rng.uniform(-6000, 6000) for _ in range(3)])
            view = affine(rot(rng), np.zeros(3)) @ affine(np.eye(3), -cam)
            if model_kind in ("scenery", "far"):
                model = np.eye(4)          # drawn where it lies
            else:
                scale = rng.choice([1.0, 1.0, 0.999, 1.02])
                pos = cam + np.array([rng.uniform(-40, 40) for _ in range(3)])
                model = affine(rot(rng) * scale, pos)
            s.mv = view @ model
        s.light = np.array([rng.gauss(0, 1) for _ in range(3)])
        s.light /= np.linalg.norm(s.light)
        s.lightClr = [rng.uniform(0, 1.2) for _ in range(3)]
        s.ambient = rng.uniform(0, 1)
        s.uv = (rng.choice([1.0, 0.625, 0.5, 0.25]),
                rng.choice([1.0, 0.75, 0.5]))
        if proj_kind in ("screen", "sprite"):
            s.fog = np.array([0, 0, 0, fog_s(rng.uniform(0, 1))])
        else:
            # georender.c's fog_row: the projection's w row by a, plus b.
            a = (fog_s(0.0) - fog_s(1.0)) / (far - near)
            b = fog_s(0.0) - a * far
            s.fog = a * s.proj[3] + np.array([0, 0, 0, b])
        s.model_kind, s.proj_kind = model_kind, proj_kind
        scenes.append(s)
    return scenes


def make_vertices(s, rng, n=600):
    """Model-space positions, most of them inside the view, and the rest
    of each vertex's attributes."""
    pts = np.zeros((n, 3))
    if s.model_kind == "quad":
        pts[:, 0] = rng.uniform(-40, 440, n)
        pts[:, 1] = rng.uniform(-40, 280, n)
        pts[:, 2] = rng.uniform(-0.5, 1.5, n)
    else:
        inv = np.linalg.inv(s.mv)
        lim = min(s.far, 3000.0 if s.model_kind != "far" else s.far)
        d = s.near + (lim - s.near) * rng.uniform(0, 1, n) ** 2
        x = rng.uniform(-1.3, 1.3, n) * d
        y = rng.uniform(-1.3, 1.3, n) * d
        view = np.stack([x, y, -d, np.ones(n)], 1)
        model = (inv @ view.T).T
        pts = model[:, :3]
    v0 = np.zeros((n, 4), np.float32)
    v0[:, :3] = pts.astype(np.float32)
    v0[:, 3] = 1
    v1 = np.zeros((n, 4), np.float32)
    v1[:, :2] = rng.uniform(-2, 3, (n, 2)).astype(np.float32)
    v1[:, 3] = 1
    v2 = rng.integers(0, 256, (n, 4)).astype(np.float32)
    v3 = rng.integers(-127, 128, (n, 4)).astype(np.float32)
    return {0: v0, 1: v1, 2: v2, 3: v3}


# ============================================================ the uniforms

def bits(x):
    return "%08x" % struct.unpack("<I", struct.pack("<f", float(x)))[0]


def unbits(h):
    return struct.unpack("<f", struct.pack("<I", int(h, 16)))[0]


def helper_outputs(exe, scenes):
    """geosolidunif.c's products for each scene, through the harness."""
    lines = []
    for s in scenes:
        p32 = s.proj.astype(np.float32)
        mv32 = s.mv.astype(np.float32)
        lines.append("M " + " ".join(bits(x) for x in
                                     list(p32.ravel()) + list(mv32.ravel())
                                     + list(s.fog.astype(np.float32))
                                     + list(s.light.astype(np.float32))))
        lines.append("C " + " ".join(bits(x) for x in
                                     s.lightClr + [s.ambient]))
    r = subprocess.run([str(exe)], input=NL.join(lines) + NL,
                       capture_output=True, text=True, timeout=60)
    out = r.stdout.split(NL)
    res = []
    for i, s in enumerate(scenes):
        m = out[2 * i].split()
        c = out[2 * i + 1].split()
        assert m[0] == "M" and c[0] == "C", (m[:1], c[:1])
        vals = [unbits(h) for h in m[1:]]
        cols = [unbits(h) for h in c[1:]]
        res.append({"mvp": np.array(vals[:16], np.float32).reshape(4, 4),
                    "fogModel": np.array(vals[16:20], np.float32),
                    "lightModel": np.array(vals[20:24], np.float32),
                    "lightClr": np.array(cols[:4], np.float32),
                    "ambientClr": np.array(cols[4:], np.float32)})
    return res


def put_unif(unif, dvle, name, rows):
    start, end = dvle.unifs[name]
    rows = np.atleast_2d(np.asarray(rows, np.float32))
    assert 0x10 <= start <= end < 0x70, (name, start, end)
    assert end - start + 1 == rows.shape[0], (name, start, end, rows.shape)
    unif[start - 0x10:end - 0x10 + 1] = rows


def old_uniforms(dvle, s):
    u = np.zeros((96, 4), np.float32)
    put_unif(u, dvle, "projection", s.proj)
    put_unif(u, dvle, "modelView", s.mv)
    put_unif(u, dvle, "lightVec", list(s.light) + [0])
    put_unif(u, dvle, "lightClr", s.lightClr + [1])
    put_unif(u, dvle, "ambientClr", [s.ambient] * 3 + [1])
    put_unif(u, dvle, "uvScale", [s.uv[0], s.uv[1], 0, 1])
    put_unif(u, dvle, "fogRow", s.fog)
    return u


def new_uniforms(dvle, s, h):
    u = np.zeros((96, 4), np.float32)
    put_unif(u, dvle, "mvp", h["mvp"])
    put_unif(u, dvle, "fogModel", h["fogModel"])
    if "lightModel" in dvle.unifs:
        put_unif(u, dvle, "lightModel", h["lightModel"])
        put_unif(u, dvle, "lightClr", h["lightClr"])
        put_unif(u, dvle, "ambientClr", h["ambientClr"])
    put_unif(u, dvle, "uvScale", [s.uv[0], s.uv[1], 0, 1])
    return u


def exact(s, v):
    """The old shader's arithmetic in float64."""
    p = v[0].astype(np.float64)
    p[:, 3] = 1
    view = (s.mv @ p.T).T
    view[:, 3] = 1
    pos = (s.proj @ view.T).T
    fog = view @ s.fog
    n = v[3][:, :3].astype(np.float64) / 127
    nv = (s.mv[:3, :3] @ n.T).T
    d = np.maximum(nv @ s.light, 0)
    col = np.empty((len(p), 4))
    for i in range(3):
        col[:, i] = (s.ambient + s.lightClr[i] * d) * v[2][:, i] / 255
    col[:, 3] = v[2][:, 3] / 255
    tex = np.stack([v[1][:, 0] * s.uv[0], 1 - v[1][:, 1] * s.uv[1]], 1)
    return pos, fog, col, tex


def with_consts(dvle, unif):
    """`unif` with the DVLE's float constants in their registers."""
    unif = unif.astype(np.float32).copy()
    for typ, reg, vals in dvle.consts:
        if typ == 2:
            unif[reg] = [f24(x) for x in vals]
    return unif


def replica(dvle, unif, v):
    """The reference shader's arithmetic in float32, step for step in the
    shader's order: what the interpreter must give, to the bit."""
    u = with_consts(dvle, unif)
    n = len(v[0])

    def row(name, i=0):
        return u[dvle.unifs[name][0] - 0x10 + i]

    def const(x):
        # normScale and colScale, known by their values.
        for typ, reg, vals in dvle.consts:
            if typ == 2 and abs(f24(vals[0]) - x) < 1e-6:
                return u[reg][0]
        raise KeyError(x)

    def dp3(a, b):
        return (a[0] * b[:, 0] + a[1] * b[:, 1]) + a[2] * b[:, 2]

    def dp4(a, b):
        return dp3(a, b) + a[3] * b[:, 3]

    mv = [row("modelView", i) for i in range(4)]
    proj = [row("projection", i) for i in range(4)]
    p = v[0].copy()
    p[:, 3] = 1
    r1 = np.ones((n, 4), np.float32)
    for i in range(3):
        r1[:, i] = dp4(mv[i], p)
    pos = np.stack([dp4(proj[i], r1) for i in range(4)], 1)
    fog = dp4(row("fogRow"), r1)
    uv = row("uvScale")
    tex = np.stack([uv[0] * v[1][:, 0],
                    np.float32(1) + -(uv[1] * v[1][:, 1])], 1)
    r0 = np.zeros((n, 4), np.float32)
    r0[:, :3] = const(1 / 127) * v[3][:, :3]
    r2 = np.zeros((n, 4), np.float32)
    for i in range(3):
        r2[:, i] = dp3(mv[i], r0)
    d = dp3(row("lightVec"), r2)
    d = np.where(np.float32(0) > d, np.float32(0), d)
    lc, am = row("lightClr"), row("ambientClr")
    r6 = const(1 / 255) * v[2]
    col = np.empty((n, 4), np.float32)
    for i in range(3):
        col[:, i] = (am[i] + lc[i] * d) * r6[:, i]
    col[:, 3] = r6[:, 3]
    return pos, fog, col, tex


# ============================================================= the compare

def errors(out, ex_pos, ex_fog, keep):
    """Each kept vertex's error against the exact result: on the screen in
    pixels (an NDC unit is 200 at most), in the depth buffer's 2^24 steps,
    and in the fog texture's texels."""
    a = out[OUT_POSITION][keep].astype(np.float64)
    b = ex_pos[keep]
    xy = np.abs(a[:, :2] / a[:, 3:4] - b[:, :2] / b[:, 3:4]).max(1) * 200
    z = np.abs(a[:, 2] / a[:, 3] - b[:, 2] / b[:, 3]) * (1 << 24)
    f = np.abs(out[OUT_TEX1][keep, 0].astype(np.float64) - ex_fog[keep]) * 256
    return [xy, z, f]


def inside(pos):
    w = pos[:, 3]
    return (w > 1e-3) & (np.abs(pos[:, 0]) <= w) & (np.abs(pos[:, 1]) <= w)


# The position's error is rounding: world coordinates in the thousands,
# with the camera's translation taken off them, leave the near vertices a
# few of the last bits. The new shader rounds the projection's products with
# the model-view once more than the old, so in float32 its error is some
# 1.2 times the old's (the square root of 2 at worst); on the PICA, whose
# uniforms take 16 bits of mantissa, both round the model-view's entries
# the same, and the two are alike: better at one vertex, worse at the next.
# So the judgement is of the spread over every scene, its median, its 99th
# percentile and its mean, which may each be the old's by SLACK and TOL
# more; one scene's worst vertex is held only to FAULT_X times the old's,
# against a fault that moves whole models.
SLACK = {"32": 1.5, "24": 1.25}
TOL = (0.01, 16.0, 0.01)
TOL_SCALE = {"32": 1, "24": 16}
FAULT_X = 4
UNITS = ("px", "depth steps", "fog texels")


def check(new_shbin, ref_shbin, exe, quiet=False):
    """Every comparison; returns the faults found."""
    code_n, ops_n, dvles_n = parse(new_shbin)
    code_r, ops_r, dvles_r = parse(ref_shbin)
    solid, lit, ref = dvles_n[0], dvles_n[1], dvles_r[0]
    faults = []
    say = (lambda *a: None) if quiet else print

    # The two passes share the products' registers.
    for name in ("mvp", "fogModel"):
        a, b = solid.unifs.get(name), lit.unifs.get(name)
        if a is None or a != b:
            faults.append("%s: solid %s, lit %s" % (name, a, b))

    scenes = make_scenes(46)
    helpers = helper_outputs(exe, scenes)
    rng = np.random.default_rng(46)
    interp_bad = 0
    worst_ct = [0.0, 0.0]
    errs = {k: [[], [], []] for k in ("old32", "new32", "old24", "new24")}
    for s, h in zip(scenes, helpers):
        v = make_vertices(s, rng)
        ex_pos, ex_fog, ex_col, ex_tex = exact(s, v)
        uo = old_uniforms(ref, s)
        un = new_uniforms(solid, s, h)
        try:
            oo, co = run(code_r, ops_r, ref, v, uo)
            on, cn = run(code_n, ops_n, solid, v, un)
            oo24, _ = run(code_r, ops_r, ref, v, uo, fp24=True)
            on24, _ = run(code_n, ops_n, solid, v, un, fp24=True)
        except Unsupported as e:
            faults.append("%s: %s" % (s.name, e))
            continue
        old, new = outputs(ref, oo, co), outputs(solid, on, cn)
        for _, reg, mask in solid.outs:
            for i in range(4):
                if mask >> i & 1 and cn[reg, i] != 1:
                    faults.append("%s: o%d.%s written %d times"
                                  % (s.name, reg, "xyzw"[i], cn[reg, i]))

        # The interpreter against the reference's arithmetic.
        rp, rf, rc, rt = replica(ref, uo, v)
        if not (np.array_equal(old[OUT_POSITION], rp)
                and np.array_equal(old[OUT_TEX1][:, 0], rf)
                and np.array_equal(old[OUT_COLOR], rc)
                and np.array_equal(old[OUT_TEX0][:, :2], rt)):
            interp_bad += 1

        # The colour and the texture coordinates against the old, which has
        # no large numbers in them to lose.
        c = float(np.abs(new[OUT_COLOR] - old[OUT_COLOR]).max() * 255)
        # The texture coordinates, and the fog's t and the rest after its s.
        # A component one shader maps and the other does not is a fault.
        tex = [new[OUT_TEX0], old[OUT_TEX0], new[OUT_TEX1][:, 1:],
               old[OUT_TEX1][:, 1:]]
        if not (np.array_equal(np.isnan(tex[0]), np.isnan(tex[1]))
                and np.array_equal(np.isnan(tex[2]), np.isnan(tex[3]))):
            faults.append("%s: the shaders map different texture "
                          "coordinates" % s.name)
        t = float(max(np.nan_to_num(np.abs(tex[0] - tex[1])).max(),
                      np.nan_to_num(np.abs(tex[2] - tex[3])).max()))
        worst_ct = [max(worst_ct[0], c), max(worst_ct[1], t)]
        if c > 0.01 or t > 1e-6:
            faults.append("%s: colour %.4f steps, texcoord %.2g from the old"
                          % (s.name, c, t))

        # The position and the fog against the exact, each shader's.
        keep = inside(ex_pos) & (ex_pos[:, 3] > s.near * 0.5)
        if not keep.any():
            continue
        e = {"old32": errors(old, ex_pos, ex_fog, keep),
             "new32": errors(new, ex_pos, ex_fog, keep),
             "old24": errors(outputs(ref, oo24, co), ex_pos, ex_fog, keep),
             "new24": errors(outputs(solid, on24, cn), ex_pos, ex_fog, keep)}
        for k in e:
            for i in range(3):
                errs[k][i].append(e[k][i])
        for prec in ("32", "24"):
            for i in range(3):
                mo, mn = e["old" + prec][i].max(), e["new" + prec][i].max()
                if mn > FAULT_X * mo + TOL[i] * TOL_SCALE[prec]:
                    faults.append("%s: float%s %s %.4f, the old's %.4f"
                                  % (s.name, prec, UNITS[i], mn, mo))

    say("geosolid_check: %d instructions a vertex (the reference %d); %d "
        "scenes, %d vertices each"
        % (straight_length(code_n, solid.main),
           straight_length(code_r, ref.main), len(scenes), 600))
    if interp_bad:
        faults.append("the interpreter is not the reference's arithmetic in "
                      "%d scenes" % interp_bad)
    else:
        say("  the interpreter gives the reference's float32 arithmetic to "
            "the bit")
    say("  colour %.5f steps and texcoord %.2g from the old at most"
        % tuple(worst_ct))
    for prec, name in (("32", "float32"), ("24", "the PICA's 16-bit "
                                                  "mantissas")):
        say("  %s, error against the exact, old -> new:" % name)
        say("    %-11s %21s %21s %21s %21s" % ("", "median", "99th", "mean",
                                               "max"))
        for i in range(3):
            if not errs["old" + prec][i]:
                continue
            eo = np.concatenate(errs["old" + prec][i])
            en = np.concatenate(errs["new" + prec][i])
            stats = [(np.median(eo), np.median(en)),
                     (np.percentile(eo, 99), np.percentile(en, 99)),
                     (eo.mean(), en.mean()), (eo.max(), en.max())]
            say("    %-11s" % UNITS[i] + "".join(
                " %9.4g -> %-9.4g" % st for st in stats))
            tol = TOL[i] * TOL_SCALE[prec]
            for (so, sn), what in zip(stats[:3], ("median", "99th percentile",
                                                  "mean")):
                if sn > so * SLACK[prec] + tol:
                    faults.append("float%s: the new shader's %s %s error is "
                                  "%.4g, the old's %.4g"
                                  % (prec, what, UNITS[i], sn, so))

    # The lit pass's position and fog, as far as it runs here: the solid's
    # to the bit, or its GEQUAL fails.
    for s, h in zip(scenes[:8], helpers[:8]):
        v = make_vertices(s, np.random.default_rng(7))
        on, cn = run(code_n, ops_n, solid, v, new_uniforms(solid, s, h))
        ol, cl = run(code_n, ops_n, lit, v, new_uniforms(lit, s, h),
                     partial=True)
        a, b = outputs(solid, on, cn), outputs(lit, ol, cl)
        if not (np.array_equal(a[OUT_POSITION], b[OUT_POSITION])
                and np.array_equal(a[OUT_TEX1][:, 0], b[OUT_TEX1][:, 0])):
            faults.append("%s: the lit pass's position or fog differs from "
                          "the solid's" % s.name)
    return faults


# ============================================================== mutations

MUTATIONS = [
    ("mvp-no-w-column", UNIF_C,
     "out->mvp[i][j] = j == 3 ? s + projection[i][3] : s;",
     "out->mvp[i][j] = s;"),
    ("mvp-transposed", UNIF_C,
     "float s = projection[i][0] * modelView[0][j]",
     "float s = projection[i][0] * modelView[j][0]"),
    ("fog-no-w", UNIF_C,
     "out->fog[j] = j == 3 ? s + fogRow[3] : s;", "out->fog[j] = s;"),
    ("light-no-127", UNIF_C, " * (1.0f / 127.0f);", ";"),
    ("light-transposed", UNIF_C,
     "(lightVec[0] * modelView[0][j]", "(lightVec[0] * modelView[j][0]"),
    ("ambient-alpha-1", UNIF_C, "ambientClr[3] = k;", "ambientClr[3] = 1.0f;"),
    ("colour-w-1", UNIF_C, "lightClr[3]   = 0.0f;", "lightClr[3]   = 1.0f;"),
    ("colour-no-255", UNIF_C, "lightClr[0]   = r * k;", "lightClr[0]   = r;"),
    ("shader-no-clamp", SHADERS[0], "max r3, zeros, r3", "mov r3, r3"),
    ("shader-t-unflipped", SHADERS[0], "add outtex.y, ones, -r7.y",
     "add outtex.y, ones, r7.y"),
    ("shader-w-row", SHADERS[0], "dp4 outpos.w, mvp[3], r0",
     "dp4 outpos.w, mvp[2], r0"),
    ("shader-no-vertex-colour", SHADERS[0], "mul outclr, r4, inclr",
     "mov outclr, r4"),
    ("shader-fog-t", SHADERS[0], "mov outfog.yzw, fogTail",
     "mov outfog.yzw, zeros"),
    ("lit-own-matrix", SHADERS[1], "dp4 outpos.x, mvp[0], r0",
     "dp4 outpos.x, mvp[1], r0"),
]


def build_all(tmp, unif_src=None, shader_srcs=None):
    exe = hostbuild.build(tmp, [str(HARNESS), str(unif_src or UNIF_C)],
                          name="geosolid_test", quiet=True)
    new, err = assemble(shader_srcs or SHADERS, tmp, "geosolid")
    if new is None:
        sys.exit("picasso: " + err)
    return exe, new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    args = ap.parse_args()
    np.seterr(all="ignore")      # the lit shader's LG2 of 0, by design
    with tempfile.TemporaryDirectory() as tmp:
        ref, err = assemble([REFERENCE], tmp, "reference")
        if ref is None:
            sys.exit("picasso: " + err)
        exe, new = build_all(tmp)
        faults = check(new, ref, exe)
        for f in faults:
            print("  FAULT " + f)
        if faults:
            print("geosolid_check: %d faults" % len(faults))
            return 1
        print("geosolid_check: 0 faults")
        if not args.mutate:
            return 0
        caught = 0
        for name, path, old, new_text in MUTATIONS:
            text = path.read_bytes().decode("utf-8")
            if text.count(old) != 1:
                print("  %s: PATTERN NOT FOUND" % name)
                continue
            mdir = Path(tmp) / name
            mdir.mkdir()
            copy = mdir / path.name
            copy.write_bytes(text.replace(old, new_text).encode("utf-8"))
            if path == UNIF_C:
                exe_m, new_m = build_all(mdir, unif_src=copy)
            else:
                srcs = [copy if s == path else s for s in SHADERS]
                exe_m, new_m = build_all(mdir, shader_srcs=srcs)
            f = check(new_m, ref, exe_m, quiet=True)
            caught += bool(f)
            print("  %s: %s" % (name, "caught (%s)" % f[0] if f
                                else "NOT CAUGHT"))
        print("geosolid_check: %d of %d mutations caught"
              % (caught, len(MUTATIONS)))
        return 0 if caught == len(MUTATIONS) else 1


if __name__ == "__main__":
    sys.exit(main())
