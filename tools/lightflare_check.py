#!/usr/bin/env python3
"""Cross-check 3DS Files/source/elightflare.c, the light flares' drawing,
against the retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own code: eLightUpdateTextures (0x00116488),
eRenderLightFlare (0x001164f0) with its part renderer (0x00116118) under
it, eRenderWorldLightFlares (0x00116778), and ePoly's constructor
(0x0010f968); the parts' table (0x002d6080), the types' (0x002d62d8) and
the textures' hashes (0x002d6070) as shipped. The harness
(tools/src/lightflare_test.c) runs elightflare.c, epoly.c and emath.c and
prints the same lines.

**The stubs**, logged and answered by the same rule on both sides:
GetTextureInfo, which hands back one of three textures of the checker's
own or NULL; ePoly::Render3D, which logs the poly from its vertices on;
and ePoly's destructor, which does nothing.

**The port's divergence**, which the model is made to share: retail
indexes the types' table with the flare's signed Type unchecked, and the
port draws nothing for one outside 0..9. A hook where retail forms the
index points it at a pair of NULLs for those.

**Compared** are the stubs' logs (every poly drawn, its texture, matrix
and flags), each call's result, the textures eLightUpdateTextures keeps,
and the two tables.

**The script** loads the textures in each combination; asks for flares
with no flare, matrix or camera, and not enabled; puts flares either side
of each clip plane by one ulp, with w either sign and with w from the
flare's depth; draws every type and some outside the table, facing the
camera, edge on and away, with each flag; at intensities from below zero
to far past one; at depths either side of every part's scale clamps; at
the camera itself; walks the world's packs with InGameFlag off and on,
empty packs and none; and then draws a few hundred flares from random
cars through random views.

    python tools/lightflare_check.py
    python tools/lightflare_check.py --mutate [--only a,b]
    python tools/lightflare_check.py --dump out/lightflare
"""
import argparse
import math
import os
import random
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, M64, s32       # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/lightflare_test.c"
FLARE = "3DS Files/source/elightflare.c"
SOURCES = [HARNESS, FLARE, "3DS Files/source/epoly.c",
           "3DS Files/source/emath.c", "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c", "3DS Files/source/bmatrix.c"]
HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = retail_model.RETAIL_GP
G_INGAME = GP - 21424                   # InGameFlag
G_PACKS = GP - 24272                    # eLightFlarePackList
IDENT = 0x002dc380                      # eMathIdentityMatrix
TEXTURES = 0x002d6328                   # the three TextureInfo pointers
PARAMS = 0x002d6080                     # the nine parts, 60 bytes each
TYPES = 0x002d62d8                      # each type's two parts

F_UPDATE = 0x00116488
F_RENDER = 0x001164f0
F_WORLD = 0x00116778
H_INDEX = 0x00116678                    # addu v0,s0,s1: the table's index

S_GETTEX = 0x001abf48
S_R3D = 0x0010ff88
S_PDTOR = 0x00114db8

HASHES = (0x8868656f, 0x88d8e8a2, 0x3394fe62)
NFLARES, NPACKS = 16, 3
REG_T0, REG_S0 = 8, 16


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def bitsf(u):
    return struct.unpack("<f", struct.pack("<I", u & M32))[0]


def fx(f):
    return "%08x" % fbits(f)


# ================================================================ the model

class Model:
    def __init__(self):
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True,
                                            eesqrt=True)
        self.lines = []
        self.view = self.block(256)
        self.cam = self.block(256)
        self.wv = self.block(64)
        self.wc = self.block(64)
        self.lw = self.block(64)
        self.flares = [self.block(80) for _ in range(NFLARES)]
        self.packs = [self.block(64) for _ in range(NPACKS)]
        self.texes = [self.block(64) for _ in range(3)]
        self.tex_on = [0, 0, 0]
        self.nulls = self.block(16)
        e.put32(self.view + 56, self.cam)
        e.put32(self.view + 68, self.wv)
        e.put32(self.view + 72, self.wc)
        for k in range(16):
            e.put32(IDENT + 4 * k, fbits(1.0 if k % 5 == 0 else 0.0))
        for k in range(3):
            e.put32(TEXTURES + 4 * k, 0)
        e.put32(G_INGAME, 0)
        e.put32(G_PACKS, G_PACKS)
        e.put32(G_PACKS + 4, G_PACKS)
        self.install()

    def block(self, size):
        a = self.e.alloc(size, 16)
        self.e.write(a, bytes(size))
        return a

    def log(self, s):
        self.lines.append("  " + s)

    def tname(self, a):
        a &= M32
        if a == 0:
            return "NULL"
        if a in self.texes:
            return "T%d" % self.texes.index(a)
        return "?"

    def mname(self, a):
        a &= M32
        return {IDENT: "I", self.lw: "LW"}.get(a, "?")

    # ---- the stubs --------------------------------------------------------

    def install(self):
        e = self.e
        r = e.reg

        def gettex(e):
            h = r[4] & M32
            self.log("gettex %08x %d %d" % (h, s32(r[5]), s32(r[6])))
            for i, hh in enumerate(HASHES):
                if h == hh:
                    return self.texes[i] if self.tex_on[i] else 0
            return 0

        def render3d(e):
            p = r[4] & M32
            words = " ".join("%08x" % e.u32(p + o) for o in range(16, 144, 4))
            bts = " ".join("%02x" % b for b in e.read(p + 144, 9))
            self.log("r3d %s %s %d %s %s %s" % (
                self.tname(r[5]), self.mname(r[6]), s32(r[7]), words, bts,
                "NULL" if e.u32(p + 156) == 0 else "?"))

        def pdtor(e):
            return None

        # The port's guard: a Type outside 0..9 finds two NULLs.
        def index(e):
            t = s32(r[REG_T0])
            if not 0 <= t < 10:
                r[REG_S0] = (self.nulls - TYPES) & M64

        e.stub(S_GETTEX, gettex)
        e.stub(S_R3D, render3d)
        e.stub(S_PDTOR, pdtor)
        e.hook(H_INDEX, index)

    # ---- the ops ----------------------------------------------------------

    def run(self, t):
        e = self.e
        op = t[0]
        self.lines.append(op)
        if op == "mat":
            m = {"lw": self.lw, "wv": self.wv, "wc": self.wc,
                 "cam": self.cam}[t[1]]
            for k in range(16):
                e.put32(m + 4 * k, int(t[2 + k], 16))
        elif op == "campos":
            for k in range(3):
                e.put32(self.cam + 64 + 4 * k, int(t[1 + k], 16))
        elif op == "h":
            e.put32(self.view + 8, int(t[1], 16))
        elif op == "cam":
            e.put32(self.view + 56, self.cam if int(t[1]) else 0)
        elif op == "flare":
            f = self.flares[int(t[1])]
            e.mem[f + 12] = int(t[2]) & 0xff
            e.mem[f + 13] = int(t[3]) & 0xff
            struct.pack_into("<H", e.mem, f + 14, int(t[4]) & 0xffff)
            for k in range(3):
                e.put32(f + 48 + 4 * k, int(t[5 + k], 16))
                e.put32(f + 64 + 4 * k, int(t[8 + k], 16))
        elif op == "tex":
            self.tex_on[int(t[1])] = int(t[2])
        elif op == "update":
            e.call(F_UPDATE)
            self.log("tex %s %s %s" % tuple(
                self.tname(e.u32(TEXTURES + 4 * k)) for k in range(3)))
        elif op == "render":
            k = int(t[1])
            e.set_f(12, bitsf(int(t[3], 16)))
            ret = e.call(F_RENDER, self.view,
                         0 if k < 0 else self.flares[k],
                         self.lw if int(t[2]) else 0)
            self.log("ret %d" % ret)
        elif op == "ingame":
            e.put32(G_INGAME, int(t[1]))
        elif op == "packs":
            self.link(t[1:])
        elif op == "world":
            e.call(F_WORLD, self.view)
        elif op == "table":
            self.table()
        else:
            raise SystemExit("no op %s" % op)

    def link(self, counts):
        e = self.e
        head = G_PACKS
        e.put32(head, head)
        e.put32(head + 4, head)
        nxt = 0
        for k, c in enumerate(counts):
            h = self.packs[k]
            lst = h + 56
            e.put32(lst, lst)
            e.put32(lst + 4, lst)
            for _ in range(int(c)):
                f = self.flares[nxt]
                nxt += 1
                last = e.u32(lst + 4)
                e.put32(f + 4, last)
                e.put32(f, lst)
                e.put32(last, f)
                e.put32(lst + 4, f)
            last = e.u32(head + 4)
            e.put32(h + 4, last)
            e.put32(h, head)
            e.put32(last, h)
            e.put32(head + 4, h)

    def table(self):
        e = self.e
        for i in range(9):
            p = PARAMS + 60 * i
            self.log("part %d %s %d" % (
                i, " ".join("%08x" % e.u32(p + 4 * k) for k in range(14)),
                s32(e.u32(p + 56))))
        for i in range(10):
            idx = []
            for k in range(2):
                a = e.u32(TYPES + 8 * i + 4 * k)
                idx.append(-1 if a == 0 else (a - PARAMS) // 60)
            self.log("type %d %d %d" % (i, idx[0], idx[1]))


def model(lines):
    m = Model()
    for ln in lines:
        m.run(ln.split("|"))
    return m.lines


# ================================================================ the script

def F(v):
    return fx(v)


def nextup(v):
    """The float after `v`, away from zero."""
    return bitsf(fbits(v) + 1)


def nextdown(v):
    """The float before `v`, toward zero."""
    return bitsf(fbits(v) - 1)


IDENT_M = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
           0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def mat(name, m):
    return "mat|%s|%s" % (name, "|".join(F(x) for x in m))


def vec3(op, v):
    return "%s|%s" % (op, "|".join(F(x) for x in v))


def flare(i, en, typ, flags, pos, d):
    return "flare|%d|%d|%d|%d|%s|%s" % (
        i, en, typ, flags, "|".join(F(x) for x in pos),
        "|".join(F(x) for x in d))


def render(i, lw=1, inten=1.0):
    return "render|%d|%d|%s" % (i, lw, F(inten))


def texes(a, b, c):
    return ["tex|0|%d" % a, "tex|1|%d" % b, "tex|2|%d" % c, "update"]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def norm(a):
    n = math.sqrt(dot(a, a))
    return [x / n for x in a]


def rotation(rng):
    """Three orthonormal rows, from a random unit quaternion."""
    q = norm([rng.gauss(0, 1) for _ in range(4)])
    w, x, y, z = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y + w * z),
             2 * (x * z - w * y)],
            [2 * (x * y - w * z), 1 - 2 * (x * x + z * z),
             2 * (y * z + w * x)],
            [2 * (x * z + w * y), 2 * (y * z - w * x),
             1 - 2 * (x * x + y * y)]]


def view_matrix(R, E):
    """World to view, the camera's axes R's rows and its eye E."""
    r0, r1, r2 = R
    return [r0[0], r1[0], r2[0], 0.0,
            r0[1], r1[1], r2[1], 0.0,
            r0[2], r1[2], r2[2], 0.0,
            -dot(E, r0), -dot(E, r1), -dot(E, r2), 1.0]


def projection(sx, sy, n, f):
    a = f / (f - n)
    return [sx, 0.0, 0.0, 0.0, 0.0, sy, 0.0, 0.0,
            0.0, 0.0, a, 1.0, 0.0, 0.0, -n * a, 0.0]


def mul(A, B):
    """Row vectors: p * A * B."""
    return [sum(A[4 * i + k] * B[4 * k + j] for k in range(4))
            for i in range(4) for j in range(4)]


def model_matrix(R, T, s=1.0):
    return [s * R[0][0], s * R[0][1], s * R[0][2], 0.0,
            s * R[1][0], s * R[1][1], s * R[1][2], 0.0,
            s * R[2][0], s * R[2][1], s * R[2][2], 0.0,
            T[0], T[1], T[2], 1.0]


def plain():
    """Identity views: clip coordinates are the flare's own, w 1, and the
    depth its z."""
    return [mat("lw", IDENT_M), mat("wv", IDENT_M), mat("wc", IDENT_M),
            mat("cam", IDENT_M), vec3("campos", (0.0, 0.0, -5.0)),
            "h|%s" % F(100.0), "cam|1"]


def tables():
    out = ["table"]
    for combo in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0),
                  (0, 1, 1), (1, 1, 1)):
        out += texes(*combo)
    return out


def basics():
    out = plain()
    on = flare(0, 1, 0, 0, (0.0, 0.0, 0.5), (0.0, 0.0, -1.0))
    out += [on, render(0), render(-1), render(0, lw=0), "cam|0", render(0),
            "cam|1"]
    for en in (0, -1, 2, 127, -128):
        out += [flare(0, en, 0, 0, (0.0, 0.0, 0.5), (0.0, 0.0, -1.0)),
                render(0)]
    # Before the textures are looked up: nothing to draw with.
    return out


def clips():
    out = plain()
    walls = [("w1", IDENT_M, 1.0), ("w-1", IDENT_M[:15] + [-1.0], 1.0),
             ("w.5", IDENT_M[:15] + [0.5], 0.5)]
    for _, wc, lim in walls:
        out.append(mat("wc", wc))
        for axis in range(3):
            for sign in (1.0, -1.0):
                for v in (nextdown(lim), lim, nextup(lim)):
                    p = [0.0, 0.0, 0.25]
                    p[axis] = sign * v
                    out += [flare(1, 1, 4, 0, p, (0.0, 0.0, -1.0)),
                            render(1)]
    # w from the flare's z: behind the eye, |w| still bounds it.
    wz = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
          0.0, 0.0, 0.5, 1.0, 0.0, 0.0, 0.0, 0.0]
    out.append(mat("wc", wz))
    for p in ((0.5, 0.5, 2.0), (2.5, 0.0, 2.0), (1.0, -1.0, -1.0),
              (0.0, 0.0, -3.0), (0.0, 1.5, -1.0), (0.0, 0.0, 0.0),
              (1e-3, 0.0, 0.0), (-0.0, 0.0, -0.0)):
        out += [flare(1, 1, 4, 1, p, (0.3, 0.2, -1.0)), render(1)]
    # No w at all, and a full row: only what lands on zero is seen.
    out.append(mat("wc", IDENT_M[:15] + [0.0]))
    for p in ((0.0, 0.0, 0.0), (1e-30, 0.0, 0.0), (0.0, 0.0, -1e-30)):
        out += [flare(1, 1, 4, 0, p, (0.0, 0.0, -1.0)), render(1)]
    out.append(mat("wc", IDENT_M))
    return out


def types():
    out = plain()
    pos, d = (0.1, -0.05, 0.4), (0.05, 0.1, -1.0)
    for typ in list(range(10)) + [10, 11, 100, 127, -1, -2, -128]:
        for flags in (0, 1):
            out += [flare(2, 1, typ, flags, pos, d), render(2),
                    render(2, inten=0.6)]
    # Textures missing: the headlights' inner, outer, and the glow.
    for combo in ((0, 1, 1), (1, 0, 1), (1, 1, 0), (0, 0, 0)):
        out += texes(*combo)
        for typ in (0, 1, 5, 7, 9):
            out += [flare(2, 1, typ, 0, pos, d), render(2)]
    out += texes(1, 1, 1)
    return out


def facings():
    out = plain()
    # From (0, 0, 0.4) the eye is straight down -z.
    dirs = [(0.0, 0.0, -1.0), (0.0, 0.8660254, -0.5), (1.0, 0.0, -0.01),
            (1.0, 0.0, -0.005), (0.0, 1.0, 0.0), (0.3, 0.0, 0.954),
            (0.0, 0.0, 1.0), (0.0, 0.0, -1.5), (0.0, 0.0, 2.5),
            (0.0, 0.0, -1e-3), (0.6, 0.0, -0.8)]
    for d in dirs:
        for flags in (0, 1, 2, 3, 0xffff, 0x8000):
            for typ in (0, 4, 1):
                out += [flare(3, 1, typ, flags, (0.0, 0.0, 0.4), d),
                        render(3)]
    return out


def intensities():
    out = plain()
    for inten in (0.0, -0.0, 1.0, 0.5, 2.0, -0.5, 1e-3, 100.0, -3.0,
                  0.999, 1.0001):
        for typ in (0, 1, 2, 3, 5, 6, 7, 9):
            out += [flare(4, 1, typ, typ & 1, (0.02, 0.03, 0.3),
                          (0.1, -0.2, -1.0)), render(4, inten=inten)]
    return out


def depths():
    out = plain()
    # Clip on x and y only; the depth is the flare's z over H.
    out.append(mat("wc", [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                          0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]))
    for h in (100.0, 256.0, 1000.0, -200.0):
        out.append("h|%s" % F(h))
        for z in (0.01, 0.1, 0.25, 0.5, 1.0, 1.5, 2.0, 2.56, 3.0, 4.0,
                  10.0, 30.0, 100.0, 1e4, -5.0, 0.0):
            for typ in (0, 2, 3, 5, 9):
                out += [flare(5, 1, typ, 1, (0.01, -0.01, z),
                              (0.0, 0.0, -1.0)), render(5)]
    # The camera's matrix apart from the view's: the depth is its z.
    out += ["h|%s" % F(256.0),
            mat("cam", [0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                        1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 3.0, 1.0])]
    for x in (0.5, -0.5, 2.0):
        for z in (0.2, 5.0):
            out += [flare(5, 1, 0, 0, (x * 0.1, 0.0, z), (0.0, 0.0, -1.0)),
                    render(5)]
    out += [mat("cam", IDENT_M), mat("wc", IDENT_M)]
    return out


def at_eye():
    """A flare at the camera: no direction to it, and a quotient of
    FLT_MAX that zero times takes back to zero."""
    out = plain()
    eye = (1.5, -2.0, 3.0)
    out += [vec3("campos", eye),
            mat("wc", [0.0] * 15 + [1.0])]
    for typ in (0, 4):
        for flags in (0, 1):
            out += [flare(6, 1, typ, flags, eye, (0.0, 0.0, -1.0)),
                    render(6)]
    out += [vec3("campos", (0.0, 0.0, -5.0)), mat("wc", IDENT_M)]
    return out


def worlds():
    out = plain()
    spec = [(1, 9, 0, (0.0, 0.0, 0.5), (0.0, 0.0, -1.0)),
            (1, 9, 0, (0.3, 0.2, 0.8), (0.0, 0.0, -1.0)),
            (0, 9, 0, (0.1, 0.1, 0.1), (0.0, 0.0, -1.0)),
            (1, 4, 1, (0.0, -0.5, 0.2), (0.0, 0.0, 1.0)),
            (1, 9, 0, (5.0, 0.0, 0.5), (0.0, 0.0, -1.0)),   # off the screen
            (1, 12, 0, (0.0, 0.0, 0.5), (0.0, 0.0, -1.0)),
            (1, 0, 0, (-0.2, 0.1, 0.6), (0.2, 0.0, -1.0)),
            (1, -3, 0, (0.0, 0.0, 0.5), (0.0, 0.0, -1.0)),
            (1, 9, 0, (0.4, -0.4, 0.9), (0.1, 0.1, -1.0))]
    for i, (en, typ, fl, p, d) in enumerate(spec):
        out.append(flare(i, en, typ, fl, p, d))
    out += ["ingame|0", "packs|2|3", "world", "ingame|1", "world",
            "packs", "world", "packs|0", "world", "packs|0|2", "world",
            "packs|1|1|1", "world", "packs|9", "world", "packs|4|0|5",
            "world", "ingame|7", "world", "cam|0", "world", "cam|1",
            "ingame|-1", "world", "ingame|0", "world", "packs"]
    return out


def randoms(rng, n=400):
    out = []
    view = None
    for case in range(n):
        if case % 12 == 0:
            R = rotation(rng)
            E = [rng.uniform(-500, 500), rng.uniform(-500, 500),
                 rng.uniform(-20, 60)]
            h = rng.uniform(150.0, 400.0)
            sx, sy = h / 200.0, h / 120.0
            wv = view_matrix(R, E)
            wc = mul(wv, projection(sx, sy, 0.5, 3000.0))
            camm = wv
            if rng.random() < 0.2:
                camm = view_matrix(rotation(rng), E)
            out += [mat("wv", wv), mat("wc", wc), mat("cam", camm),
                    vec3("campos", E), "h|%s" % F(h)]
            view = (R, E, sx, sy)
        R, E, sx, sy = view
        # A car near the eye, and a flare on it.
        R2 = rotation(rng)
        s = rng.choice((1.0, 1.0, 1.0, 0.5, 2.0))
        T = [E[k] + rng.uniform(-40, 40) for k in range(3)]
        out.append(mat("lw", model_matrix(R2, T, s)))
        z = rng.choice((rng.uniform(0.2, 3.0), rng.uniform(3.0, 30.0),
                        rng.uniform(30.0, 300.0), rng.uniform(-20.0, 0.0)))
        x = rng.uniform(-1.2, 1.2) * abs(z) / sx
        y = rng.uniform(-1.2, 1.2) * abs(z) / sy
        wp = [E[k] + x * R[0][k] + y * R[1][k] + z * R[2][k]
              for k in range(3)]
        p = [dot([wp[k] - T[k] for k in range(3)], R2[i]) / s
             for i in range(3)]
        to_eye = norm([E[k] - wp[k] for k in range(3)])
        a = rng.uniform(-1.0, 2.0)
        u = norm([a * to_eye[k] + rng.gauss(0, 1) for k in range(3)])
        u = [c * rng.choice((1.0, 1.0, 1.0, 0.7, 1.3)) for c in u]
        d = [dot(u, R2[i]) / s for i in range(3)]
        i = case % NFLARES
        en = 0 if rng.random() < 0.08 else 1
        typ = rng.randrange(10)
        flags = rng.choice((0, 0, 1, 2, 3))
        inten = rng.choice((1.0, 1.0, rng.uniform(0.0, 1.2), 0.0))
        out += [flare(i, en, typ, flags, p, d), render(i, inten=inten)]
        if rng.random() < 0.04:
            out += texes(*(rng.randrange(2) for _ in range(3)))
    out += texes(1, 1, 1)
    return out


def script():
    rng = random.Random(0xf1a2e)
    return (tables() + basics() + texes(1, 1, 1) + basics() + clips()
            + types() + facings() + intensities() + depths() + at_eye()
            + worlds() + randoms(rng))


# ================================================================= running

def build_harness(tmp, name="lightflare_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, sc_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(sc_path)], stdout=fh,
                               stderr=subprocess.PIPE, text=True,
                               timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("harness hung, killed after %d s" % HARNESS_TIMEOUT)
        return pcc.HARNESS_HUNG
    if r.returncode != 0:
        print("harness exited %d" % r.returncode)
        if r.stderr:
            print(r.stderr[:2000])
    return r.returncode


diff = pcc.diff


def write_inputs(d):
    lines = script()
    sc = Path(d) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    return lines, sc


# ============================================================= mutations

L = FLARE
MUTATIONS = [
    # ---- the tables
    ("p0_max", L, "{ 0.0f, 64.0f,", "{ 0.0f, 63.0f,"),
    ("p0_colour", L, "{ 100.0f, 120.0f, 170.0f, 80.0f }",
     "{ 100.0f, 120.0f, 171.0f, 80.0f }"),
    ("p0_power", L, "1.45f, 0.8f, 0.01f, 0.015f, 0 }",
     "1.5f, 0.8f, 0.01f, 0.015f, 0 }"),
    ("p1_tex", L, "3.0f, 0.8f, 0.01f, 0.015f, 1 }",
     "3.0f, 0.8f, 0.01f, 0.015f, 0 }"),
    ("p1_size", L, "{ 28.0f, 28.0f,", "{ 28.0f, 29.0f,"),
    ("p2_alpha", L, "{ 128.0f, 0.0f, 0.0f, 80.0f }",
     "{ 128.0f, 0.0f, 0.0f, 81.0f }"),
    ("p2_maxscale", L, "1.0f, 0.2f, 0.01f, 0.02f, 2 }",
     "1.0f, 0.2f, 0.01f, 0.03f, 2 }"),
    ("p3_power", L, "1.2f, 0.2f, 0.005f, 0.01f, 2 }",
     "1.0f, 0.2f, 0.005f, 0.01f, 2 }"),
    ("p4_toward", L, "1.0f, 0.2f, 0.005f, 0.01f, 2 }",
     "1.0f, 0.3f, 0.005f, 0.01f, 2 }"),
    ("p5_min", L, "{ 128.0f, 64.0f, 64.0f, 48.0f }",
     "{ 128.0f, 64.0f, 64.0f, 47.0f }"),
    ("p6_min", L, "{ 64.0f, 64.0f, 128.0f, 48.0f }",
     "{ 64.0f, 64.0f, 127.0f, 48.0f }"),
    ("p7_min", L, "{ 128.0f, 128.0f, 128.0f, 32.0f }",
     "{ 128.0f, 128.0f, 128.0f, 33.0f }"),
    ("p8_size", L, "{ 30.0f, 50.0f,", "{ 30.0f, 51.0f,"),
    ("p8_scale", L, "1.0f, 4.0f, 0.001f, 0.1f, 2 }",
     "1.0f, 4.0f, 0.002f, 0.1f, 2 }"),
    ("p8_toward", L, "1.0f, 4.0f, 0.001f", "1.0f, 3.0f, 0.001f"),
    ("type0", L, "{ P(0), P(1) }, { P(2), NULL }",
     "{ P(0), NULL }, { P(2), NULL }"),
    ("type3", L, "{ P(3), NULL }, { P(4), NULL },",
     "{ P(3), NULL }, { NULL, NULL },"),
    ("type6", L, "{ P(7), NULL }, { P(0), P(1) },",
     "{ P(6), NULL }, { P(0), P(1) },"),
    ("type8", L, "{ P(0), P(1) }, { P(8), NULL },",
     "{ P(0), NULL }, { P(8), NULL },"),
    ("type9", L, "{ P(8), NULL },\n};", "{ P(7), NULL },\n};"),
    ("hash_inner", L, "0x8868656fu,", "0x8868656eu,"),
    ("hash_glow", L, "0x3394fe62u,", "0x3394fe63u,"),
    ("upd_args", L, "GetTextureInfo(kTextureHashes[i], 0, 0);",
     "GetTextureInfo(kTextureHashes[i], 1, 0);"),
    ("upd_count", L, "for (i = 0; i < NUM_LIGHT_FLARE_TEXTURES; i++)\n"
     "        eLight", "for (i = 0; i < 2; i++)\n        eLight"),
    # ---- a part
    ("rp_tex", L, "    if (tex == NULL)\n        return;\n", ""),
    ("rp_clamp", L, "d = facing < 0.01f ? 0.01f : facing;",
     "d = facing < 0.02f ? 0.02f : facing;"),
    ("rp_clamp_off", L, "d = facing < 0.01f ? 0.01f : facing;",
     "d = facing;"),
    ("rp_bias", L, "+ (ONE_BITS - p->Power * ONE_BITS));",
     "+ (ONE_BITS - p->Power));"),
    ("rp_power", L, "bits = ee_trunc_w((float)bits * p->Power",
     "bits = ee_trunc_w((float)bits"),
    ("rp_intensity", L, "k = k * intensity;", "k = k * 1.0f;"),
    ("rp_size", L, "size = p->MinSize + (p->MaxSize - p->MinSize) * k;",
     "size = p->MinSize + p->MaxSize * k;"),
    ("rp_size_le", L, "if (size <= 0.0f)", "if (size < 0.0f)"),
    ("rp_toward", L, "cx = to_cam->x * p->TowardCamera + pos->x;",
     "cx = pos->x;"),
    ("rp_toward_z", L, "cz = to_cam->z * p->TowardCamera + pos->z;",
     "cz = to_cam->z * p->TowardCamera - pos->z;"),
    ("rp_minscale", L, "    if (scale < p->MinScale)\n"
     "        scale = p->MinScale;\n", ""),
    ("rp_maxscale", L, "    if (p->MaxScale < scale)\n"
     "        scale = p->MaxScale;\n", ""),
    ("rp_ext", L, "ext = size * scale;", "ext = size;"),
    ("rp_r", L, "r = (uint8_t)ee_trunc_w(p->MinColour[0]\n",
     "r = (uint8_t)ee_trunc_w(p->MinColour[1]\n"),
    ("rp_g", L, "+ (p->MaxColour[1] - p->MinColour[1]) * k);",
     "+ (p->MaxColour[1] - p->MinColour[1]));"),
    ("rp_a", L, "a = (uint8_t)ee_trunc_w(p->MinColour[3]",
     "a = (uint8_t)ee_trunc_w(p->MaxColour[3]"),
    ("rp_uv", L, "poly.UVs[2][1] = 1.0f;", "poly.UVs[2][1] = 0.0f;"),
    ("rp_uv3", L, "poly.UVs[3][0] = 0.0f;", "poly.UVs[3][0] = 1.0f;"),
    ("rp_col_b", L, "poly.Colours[i][2] = b;", "poly.Colours[i][2] = g;"),
    ("rp_v0x", L, "poly.Vertices[0].x = (cx - rx) + ux;",
     "poly.Vertices[0].x = (cx + rx) + ux;"),
    ("rp_v1y", L, "poly.Vertices[1].y = (cy + ry) + uy;",
     "poly.Vertices[1].y = (cy + ry) - uy;"),
    ("rp_v2z", L, "poly.Vertices[2].z = (cz + rz) - uz;",
     "poly.Vertices[2].z = (cz - rz) - uz;"),
    ("rp_v3x", L, "poly.Vertices[3].x = (cx - rx) - ux;",
     "poly.Vertices[3].x = (cx - rx) + ux;"),
    ("rp_ry", L, "ry = right->y * ext;", "ry = up->y * ext;"),
    ("rp_uz", L, "uz = up->z * ext;", "uz = up->z * size;"),
    ("rp_matrix", L, "gEPolyRender3DFn(&poly, tex, &eMathIdentityMatrix, 0);",
     "gEPolyRender3DFn(&poly, tex, NULL, 0);"),
    ("rp_flags", L, "gEPolyRender3DFn(&poly, tex, &eMathIdentityMatrix, 0);",
     "gEPolyRender3DFn(&poly, tex, &eMathIdentityMatrix, 1);"),
    ("rp_init", L, "    epoly_init(&poly);\n",
     "    memset(&poly, 0, sizeof poly);\n"),
    # ---- eRenderLightFlare
    ("r_null_flare", L,
     "if (flare == NULL || local_world == NULL || cam == NULL)",
     "if (local_world == NULL || cam == NULL)"),
    ("r_null_lw", L,
     "if (flare == NULL || local_world == NULL || cam == NULL)",
     "if (flare == NULL || cam == NULL)"),
    ("r_null_cam", L,
     "if (flare == NULL || local_world == NULL || cam == NULL)",
     "if (flare == NULL || local_world == NULL)"),
    ("r_enabled", L, "if (flare->Enabled == 0)\n        return 0;",
     "if (flare->Enabled <= 0)\n        return 0;"),
    ("r_wpx", L,
     "wp.x = m->v0.x * px + m->v1.x * py + m->v2.x * pz + m->v3.x;",
     "wp.x = m->v0.x * px + m->v1.x * py + m->v2.x * pz;"),
    ("r_wpy_order", L,
     "wp.y = m->v0.y * px + m->v1.y * py + m->v2.y * pz + m->v3.y;",
     "wp.y = m->v3.y + m->v0.y * px + m->v1.y * py + m->v2.y * pz;"),
    ("r_wpz", L, "wp.z = m->v0.z * px", "wp.z = m->v0.y * px"),
    ("r_cly_row", L, "cly = c->v0.y * wp.x", "cly = c->v0.x * wp.x"),
    ("r_clw", L,
     "clw = c->v0.w * wp.x + c->v1.w * wp.y + c->v2.w * wp.z + c->v3.w;",
     "clw = c->v0.w * wp.x + c->v1.w * wp.y + c->v2.w * wp.z + 1.0f;"),
    ("r_lim_abs", L, "lim = fabsf(clw);", "lim = clw;"),
    ("r_clip_eq", L, "if (lim < clx", "if (lim <= clx"),
    ("r_clip_px", L, "if (lim < clx || ", "if ("),
    ("r_clip_nx", L, "clx < -lim || lim < cly", "lim < cly"),
    ("r_clip_py", L, "|| lim < cly || cly", "|| cly"),
    ("r_clip_ny", L, "|| cly < -lim\n", "\n"),
    ("r_clip_pz", L, "        || lim < clz || clz < -lim)",
     "        || clz < -lim)"),
    ("r_clip_nz", L, "|| clz < -lim)", ")"),
    ("r_wd", L, "wdy = m->v0.y * dx + m->v1.y * dy + m->v2.y * dz;",
     "wdy = m->v0.y * dx + m->v1.y * dy + m->v2.z * dz;"),
    ("r_wd_t", L, "wdz = m->v0.z * dx + m->v1.z * dy + m->v2.z * dz;",
     "wdz = m->v0.z * dx + m->v1.z * dy + m->v2.z * dz + m->v3.z;"),
    ("r_tocam", L, "to_cam.x = cam->CurrentKey.Position.x - wp.x;",
     "to_cam.x = wp.x - cam->CurrentKey.Position.x;"),
    ("r_len", L, "len2 = to_cam.x * to_cam.x + to_cam.y * to_cam.y"
     " + to_cam.z * to_cam.z;",
     "len2 = to_cam.x * to_cam.x + to_cam.y * to_cam.y;"),
    ("r_q", L, "q = ee_div(1.0f, sqrtf(len2));", "q = 1.0f / sqrtf(len2);"),
    ("r_q_root", L, "q = ee_div(1.0f, sqrtf(len2));",
     "q = ee_div(1.0f, len2);"),
    ("r_norm_z", L, "    to_cam.z = to_cam.z * q;\n", ""),
    ("r_facing", L,
     "facing = to_cam.x * wdx + to_cam.y * wdy + to_cam.z * wdz;",
     "facing = to_cam.x * wdx + to_cam.y * wdy;"),
    ("r_flags", L, "if (flare->Flags & 1)", "if (flare->Flags & 2)"),
    ("r_flags_any", L, "if (flare->Flags & 1)", "if (flare->Flags)"),
    ("r_fabs", L, "facing = fabsf(facing);", "facing = -facing;"),
    ("r_right", L, "right.y = v->v1.x;", "right.y = v->v0.y;"),
    ("r_up", L, "up.z = v->v2.y;", "up.z = v->v2.x;"),
    ("r_depth_row", L, "depth = m->v0.z * wp.x", "depth = m->v0.y * wp.x"),
    ("r_depth_t", L, "m->v2.z * wp.z + m->v3.z;", "m->v2.z * wp.z;"),
    ("r_depth_h", L, "depth = depth / view->H;", "depth = depth * view->H;"),
    ("r_depth_cam", L, "    m = &cam->CurrentKey.Matrix;\n",
     "    m = view->WorldViewMatrix;\n"),
    ("r_type_ret", L, "if ((uint8_t)flare->Type >= NUM_LIGHT_FLARE_TYPES)\n"
     "        return 1;", "if ((uint8_t)flare->Type >= NUM_LIGHT_FLARE_TYPES)\n"
     "        return 0;"),
    ("r_part0", L, "    if (parts[0] != NULL)\n        render_part(parts[0]",
     "    if (parts[1] != NULL)\n        render_part(parts[1]"),
    ("r_part1", L, "    if (parts[1] != NULL)\n        render_part(parts[1],"
     " &wp, &to_cam, &right, &up, intensity, facing,\n"
     "                    depth);\n", ""),
    ("r_intensity", L,
     "render_part(parts[0], &wp, &to_cam, &right, &up, intensity, facing,",
     "render_part(parts[0], &wp, &to_cam, &right, &up, 1.0f, facing,"),
    ("r_ret", L, "                    depth);\n    return 1;\n}",
     "                    depth);\n    return 2;\n}"),
    # ---- eRenderWorldLightFlares
    ("w_ingame", L, "if (InGameFlag == 0)\n        return;",
     "if (InGameFlag != 0)\n        return;"),
    ("w_inten", L, "&eMathIdentityMatrix, 1.0f);",
     "&eMathIdentityMatrix, 0.5f);"),
    ("w_lw", L, "el_render_light_flare(view, (eLightFlare *)n,\n"
     "                                  &eMathIdentityMatrix",
     "el_render_light_flare(view, (eLightFlare *)n,\n"
     "                                  NULL"),
    ("w_first_pack", L, "for (h = eLightFlarePackList.next;",
     "for (h = eLightFlarePackList.next->next;"),
    ("w_first_flare", L, "for (n = list->next; n != list; n = n->next)",
     "for (n = list->next->next; n != list; n = n->next)"),
]

EQUIVALENT = {}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    indir = tempfile.TemporaryDirectory()
    lines, scp = write_inputs(indir.name)
    base = model(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text(encoding="latin-1").splitlines()
        if diff(base, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "lightflare_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs)
    indir.cleanup()
    return mutpar.summarize(todo, only, EQUIVALENT, tally)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--jobs", type=int, metavar="N",
                    help="with --mutate, mutants at once (default %d)"
                    % mutpar.JOBS)
    ap.add_argument("--dump", metavar="PREFIX")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None,
                             args.jobs))

    with tempfile.TemporaryDirectory() as tmp:
        lines, scp = write_inputs(tmp)
        got = model(lines)
        exe = build_harness(tmp)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text(encoding="latin-1").splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(got) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(got, harness)
    print("%d ops, %d lines, %d differ" % (len(lines), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
