#!/usr/bin/env python3
"""Cross-check 3DS Files/source/fecar.c, the frontend's cars, and the
frontend half of elight.c against the retail image itself, run in
mipsemu.

The model is the image. FrontEndRenderingCar's constructor (0x0011e5c0),
ReInit (0x0011e758) and deleting destructor (0x0011e7d8),
RenderFrontEndCars (0x00123d28) with RenderFrontEndCar (0x00123c90),
SetSelectCarLighting (0x001157c0) and elSetupLightContext (0x00115978)
run as shipped, after eLight.obj's static initializer (0x00117098) has
filled its tables. The harness (tools/src/fecar_test.c) runs the port
over the same script, and the two transcripts are diffed.

Stubs print what they are given: bMalloc (0x002577c0) hands out blocks,
CarRenderInfo's constructor (0x0011e860), deleting destructor
(0x0011fac0) and Render (0x00120ef8), eModel::Render (0x0010dc80, which
the thunk 0x00123d18 reaches), eModel::GetBoundingBox (0x0010c9a8, which
answers the script's box), the eModel's deleting destructor (0x00114cf0),
eWaitUntilRenderingDone (0x00111dd8) and __builtin_delete (0x00114e98).
Render can change ForceCarLOD and ForceTireLOD as the script says.

The light context runs over an empty light database, or over one pack
the script links in: a root over two leaves and six lights, of every
type and attenuation. With the world's lights retail leaves the second
direction on its stack when no point light is near, and the third when
fewer than two are, so the dumps leave out what those reach: the
direction matrix's y or z column and that light's position. How many
are near comes from each side's own QueryLightDatabase (0x00115370),
called first with the same position, and is printed. SetSelectCarLighting fills its lit colours' w lanes from its
stack, so those print as "-" too; nothing reads them.

Every car starts from a byte pattern, so what a call leaves alone shows.
A float prints as its bits, a NaN as "nan", and a pointer by what it is.

    python tools/fecar_check.py
    python tools/fecar_check.py --mutate [--only a,b]
    python tools/fecar_check.py --dump out/fecar
"""

import argparse
import math
import random
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hostbuild
import physicscar_check as pcc
import retail_model
from mipsemu import M32, f_to_bits, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/fecar_test.c"
FEC = "3DS Files/source/fecar.c"
ELC = "3DS Files/source/elight.c"
SOURCES = [HARNESS, FEC, ELC] + ["3DS Files/source/" + f for f in (
    "bmem.c", "emath.c", "bmatrix.c", "bmath.c", "bmathtab.c",
    "bvector.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
FE_CTOR = 0x0011e5c0
FE_REINIT = 0x0011e758
FE_DTOR = 0x0011e7d8
FE_RENDER_ALL = 0x00123d28
SET_LIGHTING = 0x001157c0
ELSETUP = 0x00115978
QUERY = 0x00115370               # QueryLightDatabase, for the mask
ELIGHT_SINIT = 0x00117098         # eLight.obj's static initializer
EMATH_SINIT = 0x0011bf70          # writes eMulVector's (0, 0, 0, 1)

S_MALLOC = 0x002577c0             # bMalloc(int, const char *, int, int)
S_CRI_CTOR = 0x0011e860
S_CRI_DTOR = 0x0011fac0
S_CRI_RENDER = 0x00120ef8
S_MODEL_RENDER = 0x0010dc80
S_BBOX = 0x0010c9a8
S_MODEL_DEL = 0x00114cf0
S_WAIT = 0x00111dd8
S_DELETE = 0x00114e98             # __builtin_delete

G_LIST = GP - 23656               # FrontEndRenderingCarList
G_CAR_LOD = GP - 23696            # ForceCarLOD
G_TIRE_LOD = GP - 23692           # ForceTireLOD
G_F8 = GP - 23596
G_F16 = GP - 23600
G_VIEW_MODE = GP - 24888          # eGetCurrentViewMode's
G_FLOW = GP - 21420               # CurrentGameFlowState
G_CARSEL = GP - 19968             # IsCarSelectScreenActive's
G_PACKS = GP - 24264              # eLightPackList

SEL_LIGHTS = (0x002d5f70, 0x002d5ff0)

FERCS = 0x01000000
FERC_STRIDE = 0x400
NF = 4
CRIS = 0x01010000
CRI_STRIDE = 0x1000
NC = 64
MODELS = 0x01060000
MODEL_STRIDE = 64
NM = 3
VIEWS = 0x01070000
VIEW_STRIDE = 128
VMATS = 0x01071000
NV = 3
LW = 0x01072000
HACK = 0x01072100
EYE = 0x01072200
LC = 0x01072300
LC_SIZE = 288
QBUF = 0x01072500                 # QueryLightDatabase's eLightQuery

# The light pack the script can link into the database, the same as the
# harness's kLights and kNodes: a root over two leaves that overlap at
# x = 0, and six lights. A light is (Type, AttenuationType, Colour, x, y,
# z, Size, FarStart, Intensity); a node is (x, the x extent,
# NumChildren, the children), y and z centred at 0 with extent 101.
PACK = 0x01074000
TREE = 0x01074100
NODES = 0x01074200
LIGHTS = 0x01074400
PACK_LIGHTS = [
    (0, 0, 0x00305070, -60.0, 10.0, -20.0, 150.0, 60.0, 0.4375),
    (2, 0, 0x00c08040, -10.0, 20.0, 5.0, 120.0, 40.0, 0.75),
    (0, 2, 0x00204060, 60.0, -10.0, 10.0, 130.0, 30.0, 0.625),
    (2, 1, 0x0010e0a0, 40.0, -40.0, 30.0, 140.0, 140.0, 1.25),
    (0, 2, 0x00ff00ff, -70.0, -30.0, 40.0, 100.0, 0.0, 1.75),
    (1, 0, 0x00ffffff, 0.0, 0.0, 0.0, 500.0, 0.0, 1.0),
]
PACK_NODES = [
    (0.0, 101.0, 2, (1, 2)),
    (-50.0, 51.0, -3, (0, 1, 4)),
    (50.0, 51.0, -4, (1, 2, 3, 5)),
]

PATTERN = 0xa5


def fb(v):
    if isinstance(v, int):
        return v & M32
    return f_to_bits(v)


def fx(w):
    """A float's bits, with every NaN the one "nan"."""
    w &= M32
    if (w & 0x7f800000) == 0x7f800000 and (w & 0x7fffff):
        return "nan"
    return "%08x" % w


def h(v):
    return "%08x" % fb(v)


def fer_at(k):
    return FERCS + FERC_STRIDE * k


def view_at(i):
    return VIEWS + VIEW_STRIDE * i


# ============================================================ the scenarios


def f32(v):
    return struct.unpack("<f", struct.pack("<f", v))[0]


def rot(ax, ay, az):
    """A rotation matrix, row by row, as 16 floats with a zero last row."""
    cx, sx = math.cos(ax), math.sin(ax)
    cy, sy = math.cos(ay), math.sin(ay)
    cz, sz = math.cos(az), math.sin(az)
    r = [[cy * cz, cy * sz, -sy],
         [sx * sy * cz - cx * sz, sx * sy * sz + cx * cz, sx * cy],
         [cx * sy * cz + sx * sz, cx * sy * sz - sx * cz, cx * cy]]
    out = []
    for row in r:
        out += row + [0.0]
    return out + [0.0, 0.0, 0.0, 1.0]


def rnd_rot(rnd, pos=None):
    m = rot(rnd.uniform(-3.2, 3.2), rnd.uniform(-1.6, 1.6),
            rnd.uniform(-3.2, 3.2))
    if pos is not None:
        m[12:15] = pos
    return m


def rnd_mat(rnd):
    k = rnd.random()
    if k < 0.15:
        return [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
    if k < 0.8:
        return rnd_rot(rnd, [rnd.uniform(-3, 3) for _ in range(3)])
    return [rnd.uniform(-5, 5) for _ in range(16)]


def hs(vals):
    return " ".join(h(v) for v in vals)


def ride(rnd):
    if rnd.random() < 0.2:
        return "-"
    return "%x %x %x %x %x" % (rnd.choice((0, 1, 5, 17, 37, 63, -1)) & M32,
                               rnd.randrange(256), rnd.randrange(256),
                               rnd.randrange(256), rnd.randrange(256))


def s_ctor(rnd):
    out = ["I 0 0 -", "I 1 1 25 0 3 1 0", "W", "I 2 2 3f ff 9 0 1", "W",
           "R 0 5 1 2 3 4", "R 0 -", "R 1 11 0 0 0 0", "R 2 -",
           "D 1 0", "Q 0", "Q 2", "I 1 0 7 7 7 7 7", "W", "D 0 1",
           "S 2 md 1", "D 2 3", "W", "S 1 md 2", "R 1 -", "D 1 1", "W",
           "I 3 1 -", "I 0 2 1 2 3 4 5", "W", "D 0 0", "D 3 1", "W"]
    # Only a car off the list is built, and only one on it deleted: a car
    # built twice would leave the list a loop.
    linked = {1, 2}
    for _ in range(80):
        k = rnd.randrange(NF)
        c = rnd.random()
        if c < 0.3:
            if k in linked:
                out.append("D %d %d" % (k, rnd.choice((0, 1, 3))))
                linked.discard(k)
            else:
                out.append("I %d %d %s" % (k, rnd.randrange(NV), ride(rnd)))
                linked.add(k)
        elif c < 0.6:
            out.append("R %d %s" % (k, ride(rnd)))
        elif c < 0.7:
            out.append("W")
        else:
            out.append("Q %d" % k)
    return out


def setf(rnd, k):
    c = rnd.random()
    if c < 0.12:
        return "S %d en %d" % (k, rnd.choice((0, 1, 1, 2, -1)))
    if c < 0.2:
        return "S %d u %d" % (k, rnd.choice((0, 1, 5)))
    if c < 0.35:
        return "S %d rf %d" % (k, rnd.choice((0, 1)))
    if c < 0.45:
        return "S %d hd %d" % (k, rnd.choice((0, 1, 7)))
    if c < 0.55:
        return "S %d cp %d" % (k, rnd.choice((0, 1, 3)))
    if c < 0.62:
        return "S %d vw %d" % (k, rnd.randrange(NV + 1))
    if c < 0.7:
        return "S %d md %d" % (k, rnd.choice((-1, -1, 0, 1, 2)))
    if c < 0.8:
        return "S %d p %s" % (k, hs(rnd.uniform(-3, 3) for _ in range(3)))
    if c < 0.86:
        return "S %d b %s" % (k, hs(rnd_mat(rnd)))
    if c < 0.93:
        return "S %d t %d %s" % (k, rnd.randrange(4), hs(rnd_mat(rnd)))
    return "S %d k %d %s" % (k, rnd.randrange(4), hs(rnd_mat(rnd)))


def box(rnd):
    mn = [rnd.uniform(-3, 0) for _ in range(3)]
    mx = [rnd.uniform(0, 3) for _ in range(3)]
    return "X %s" % hs(mn + mx)


def s_render(rnd):
    out = ["I 0 0 25 0 3 1 0", "I 1 0 25 0 3 1 0", "S 1 rf 1",
           "I 2 1 17 0 0 0 0", "I 3 2 -", box(rnd)]
    # Every argument against both kinds of car.
    for mode in (0, 1, 2):
        out.append("G %d" % mode)
        for v in range(NV):
            for bits in range(16):
                out.append("P %d %d %d %d %d" % (
                    v, bits & 1, (bits >> 1) & 1, (bits >> 2) & 1,
                    (bits >> 3) & 1))
    out.append("G 1")
    for f8, f16 in ((1, 0), (0, 1), (1, 1), (0, 0)):
        out.append("F %d %d" % (f8, f16))
        out.append("P 0 1 1 1 1")
    # The lights, the model and the box.
    out += ["S 0 hd 1", "P 0 1 1 1 1", "S 0 cp 1", "P 0 1 1 1 1",
            "S 0 hd 0", "P 0 1 1 1 1", "S 1 hd 1", "S 1 cp 1",
            "P 0 1 1 1 1", "S 0 md 0", "P 0 1 1 0 0", "S 1 md 1",
            "P 0 0 1 1 1", "S 0 md -1", "S 1 md -1", "S 0 en 0",
            "P 0 1 1 1 1", "S 0 en 1", "S 0 u 0", "P 0 1 1 1 1",
            box(rnd), "P 0 1 1 1 1", "X %s" % hs([1, 2, 3, 1, 2, 3]),
            "P 0 1 1 1 1"]
    # Render changing the levels of detail, or not.
    out += ["L -1 -1", "K 2 -", "P 0 1 1 1 1", "K - 3", "P 0 1 1 1 1",
            "K 0 -", "P 0 1 0 1 1", "K - 1", "P 0 0 1 1 1", "K 1 1",
            "P 0 0 1 1 1", "K - -", "L 4 5", "P 0 1 1 1 1"]
    # A car without a CarRenderInfo is skipped, model or no.
    out += ["R 2 -", "S 2 md 0", "P 1 1 1 1 1", "D 0 3", "W",
            "P 0 1 1 1 1"]
    for _ in range(200):
        c = rnd.random()
        k = rnd.randrange(NF)
        if c < 0.45:
            out.append(setf(rnd, k))
        elif c < 0.75:
            out.append("P %d %d %d %d %d" % (
                rnd.randrange(NV), rnd.random() < 0.8, rnd.random() < 0.6,
                rnd.random() < 0.5, rnd.random() < 0.5))
        elif c < 0.8:
            out.append(box(rnd))
        elif c < 0.84:
            out.append("G %d" % rnd.choice((0, 1, 1, 2, 3)))
        elif c < 0.88:
            out.append("K %s %s" % (rnd.choice(("-", "-", "0", "1", "2")),
                                    rnd.choice(("-", "-", "0", "1"))))
        elif c < 0.92:
            out.append("L %d %d" % (rnd.choice((-1, 0, 1, 2)),
                                    rnd.choice((-1, 0, 1))))
        elif c < 0.95:
            out.append("R %d %s" % (k, ride(rnd)))
        else:
            out.append("Q %d" % k)
    return out


def bright(rnd):
    return rnd.choice((0.0, 1.0, 0.5, -0.0, -1.0, 2.0, 5.0, 5.8, 6.0, 7.0,
                       100.0, -100.0, float("inf"), float("-inf"),
                       0x7fc00000, rnd.uniform(-1, 8), rnd.uniform(0, 1)))


def s_lights(rnd):
    out = []
    for v in (0, 1, 2, 3, -1, 2):
        for locked in (0, 1, 2, -1, 0):
            out.append("C %d %d %s" % (v, locked, h(bright(rnd))))
    for _ in range(60):
        out.append("C %d %d %s" % (rnd.choice((0, 1, 2, 2)),
                                   rnd.choice((0, 0, 1)), h(bright(rnd))))
    return out


def z_op(rnd, v):
    lw = rnd_rot(rnd, [rnd.uniform(-100, 100) for _ in range(3)])
    if rnd.random() < 0.1:
        lw = [rnd.uniform(-2, 2) for _ in range(16)]
    hack = "-" if rnd.random() < 0.3 else hs(rnd_mat(rnd))
    eye = "-" if rnd.random() < 0.3 else hs(
        [rnd.uniform(-100, 100) for _ in range(3)] + [rnd.uniform(0, 2)])
    return "Z %d %s %s %s" % (v, hs(lw), hack, eye)


def s_lc(rnd, pack=0):
    out = ["Y %d" % pack, "C 0 0 %s" % h(0.5), "C 2 0 %s" % h(1.5)]
    for v in range(NV):
        out.append("M %d %s" % (v, hs(rnd_rot(rnd, [rnd.uniform(-9, 9)
                                                    for _ in range(3)]))))
    for fe, cs in ((0, 0), (0, 1), (1, 0), (1, 1)):
        out.append("U %d %d" % (fe, cs))
        for v in range(NV):
            for _ in range(4):
                out.append(z_op(rnd, v))
    out += ["U 1 1", "C 0 1 0", "Z 0 %s - -" % hs(rnd_rot(rnd, [0, 0, 0])),
            "Z 1 %s - -" % hs(rnd_rot(rnd, [1, 2, 3])),
            "Z 2 %s - -" % hs(rnd_rot(rnd, [1, 2, 3]))]
    for _ in range(80):
        c = rnd.random()
        if c < 0.1:
            out.append("U %d %d" % (rnd.random() < 0.8, rnd.random() < 0.7))
        elif c < 0.2:
            out.append("M %d %s" % (rnd.randrange(NV), hs(rnd_mat(rnd))))
        elif c < 0.3:
            out.append("C %d %d %s" % (rnd.randrange(NV),
                                       rnd.random() < 0.2,
                                       h(rnd.uniform(0, 3))))
        elif c < 0.35:
            out.append("Y %d" % (rnd.random() < 0.7))
        else:
            out.append(z_op(rnd, rnd.randrange(NV)))
    return out


def script():
    rnd = random.Random(0xfeca5)
    return [s_ctor(rnd), s_render(rnd), s_lights(rnd), s_lc(rnd),
            s_render(rnd), s_lc(rnd, 1), s_lc(rnd, 1)]


def encode(scenarios):
    lines = []
    for i, s in enumerate(scenarios):
        lines.append("B %d" % i)
        lines += s
    return NL.join(lines) + NL


# ================================================================ the model


class Model(object):
    def __init__(self):
        self.out = []
        self.e = retail_model.RetailEmu(ieee=True)
        e = self.e
        e.call(EMATH_SINIT)
        e.call(ELIGHT_SINIT, limit=200000)
        e.stub(S_MALLOC, self.s_malloc)
        e.stub(S_CRI_CTOR, self.s_cri_ctor)
        e.stub(S_CRI_DTOR, self.s_cri_dtor)
        e.stub(S_CRI_RENDER, self.s_render)
        e.stub(S_MODEL_RENDER, self.s_model_render)
        e.stub(S_BBOX, self.s_bbox)
        e.stub(S_MODEL_DEL, self.s_model_del)
        e.stub(S_WAIT, lambda em: self.emit("  wait"))
        e.stub(S_DELETE, lambda em: self.emit("  free %s"
                                              % self.name(self.arg(0))))
        self.lod_to = [None, None]
        self.box = [0] * 6

    def emit(self, s):
        self.out.append(s)

    def arg(self, i):
        return self.e.reg[(4, 5, 6, 7, 8, 9, 10, 11)[i]] & M32

    def w(self, a):
        return self.e.u32(a)

    def name(self, a):
        a &= M32
        if a == 0:
            return "null"
        if a == G_LIST:
            return "head"
        for k in range(NF):
            f = fer_at(k)
            if a == f:
                return "f%d" % k
            if a == f + 12:
                return "f%d.ride" % k
            if a == f + 48:
                return "f%d.body" % k
        for i, c in enumerate(self.cris):
            if a == c:
                return "c%d" % i
            if a == c + 64:
                return "c%d.body" % i
        for j in range(NM):
            if a == MODELS + MODEL_STRIDE * j:
                return "m%d" % j
        for i in range(NV):
            if a == view_at(i):
                return "v%d" % i
        return "?"

    # ---- the stubs -------------------------------------------------------

    def s_malloc(self, em):
        self.emit("  alloc pool %d" % s32(self.arg(3)))
        a = CRIS + CRI_STRIDE * self.npool
        self.npool += 1
        return a

    def s_cri_ctor(self, em):
        ri, rd, car = self.arg(0), self.arg(1), self.arg(2)
        self.cris.append(ri)
        b = self.e.mem
        self.emit("  cri new %s ride %s %08x %02x%02x%02x%02x car %s" % (
            self.name(ri), self.name(rd), self.w(rd), b[rd + 4], b[rd + 5],
            b[rd + 6], b[rd + 7], self.name(car)))
        return ri

    def s_cri_dtor(self, em):
        self.emit("  cri del %s %d" % (self.name(self.arg(0)),
                                       s32(self.arg(1))))

    def mat(self, tag, a):
        self.emit("    %s %s" % (tag, " ".join(fx(self.w(a + 4 * i))
                                                for i in range(16))))

    def s_render(self, em):
        w = self.w
        pos = self.arg(2)
        self.emit("  render %s view %s pos %s body %s flags %d forced %d "
                  "lod %d %d" % (
                      self.name(self.arg(0)), self.name(self.arg(1)),
                      " ".join(fx(w(pos + 4 * i)) for i in range(4)),
                      self.name(self.arg(3)), self.arg(6), self.arg(7),
                      s32(w(G_CAR_LOD)), s32(w(G_TIRE_LOD))))
        for i in range(4):
            self.mat("t%d" % i, self.arg(4) + 64 * i)
            self.mat("k%d" % i, self.arg(5) + 64 * i)
        if self.lod_to[0] is not None:
            self.e.put32(G_CAR_LOD, self.lod_to[0] & M32)
        if self.lod_to[1] is not None:
            self.e.put32(G_TIRE_LOD, self.lod_to[1] & M32)

    def s_model_render(self, em):
        self.emit("  model render %s mat %s light %s flags %d" % (
            self.name(self.arg(0)), self.name(self.arg(1)),
            self.name(self.arg(2)), self.arg(3)))

    def s_bbox(self, em):
        self.emit("  bbox %s" % self.name(self.arg(0)))
        mn, mx = self.arg(1), self.arg(2)
        for i in range(3):
            self.e.put32(mn + 4 * i, self.box[i])
            self.e.put32(mx + 4 * i, self.box[3 + i])

    def s_model_del(self, em):
        self.emit("  model del %s %d" % (self.name(self.arg(0)),
                                         s32(self.arg(1))))

    # ---- the dumps -------------------------------------------------------

    def pfer(self, k):
        f = fer_at(k)
        w = self.w
        b = self.e.mem
        self.emit("  f%d next %s prev %s ri %s ride %08x %02x%02x%02x%02x "
                  "view %d" % (k, self.name(w(f)), self.name(w(f + 4)),
                               self.name(w(f + 8)), w(f + 12), b[f + 16],
                               b[f + 17], b[f + 18], b[f + 19],
                               s32(w(f + 20))))
        self.emit("    pos %s model %s en %d u %d rf %d hd %d cp %d" % (
            " ".join(fx(w(f + 32 + 4 * i)) for i in range(4)),
            self.name(w(f + 624)), s32(w(f + 628)), s32(w(f + 632)),
            s32(w(f + 636)), s32(w(f + 640)), s32(w(f + 644))))
        self.mat("body", f + 48)
        for i in range(4):
            self.mat("t%d" % i, f + 112 + 64 * i)
            self.mat("k%d" % i, f + 368 + 64 * i)

    def plist(self):
        w = self.w
        fwd, back = [], []
        n = w(G_LIST)
        while n != G_LIST and len(fwd) < 16:
            fwd.append(self.name(n))
            n = w(n)
        n = w(G_LIST + 4)
        while n != G_LIST and len(back) < 16:
            back.append(self.name(n))
            n = w(n + 4)
        self.emit("  list%s /%s" % ("".join(" " + s for s in fwd),
                                    "".join(" " + s for s in back)))

    def vec(self, tag, a, wl):
        w = self.w
        self.emit("    %s %s %s %s %s" % (tag, fx(w(a)), fx(w(a + 4)),
                                         fx(w(a + 8)),
                                         fx(w(a + 12)) if wl else "-"))

    def plights(self):
        for s, a in enumerate(SEL_LIGHTS):
            self.emit("  lights %d" % s)
            for i in range(3):
                self.vec("c%d" % i, a + 32 * i, False)
                self.vec("d%d" % i, a + 16 + 32 * i, True)
            self.vec("amb", a + 96, False)

    def plc(self, world, near):
        for row in range(18):
            ws = []
            for i in range(4):
                n = row * 4 + i
                masked = world and (
                    (16 <= n < 28 and ((i == 1 and near < 1)
                                       or (i == 2 and near < 2)))
                    or (36 <= n < 40 and near < 1)
                    or (40 <= n < 44 and near < 2))
                ws.append("-" if masked else fx(self.w(LC + 4 * n)))
            self.emit("    lc%02d %s" % (row, " ".join(ws)))

    # ---- the ops ---------------------------------------------------------

    def fill(self, a, n):
        self.e.write(a, bytes([PATTERN]) * n)

    def put_words(self, a, toks):
        for i, t in enumerate(toks):
            self.e.put32(a + 4 * i, int(t, 16))

    def put_ride(self, a, t):
        """Writes the ride at `a`, or returns 0 for "-"."""
        if t[0] == "-":
            return 0
        self.e.put32(a, int(t[0], 16))
        for i in range(4):
            self.e.mem[a + 4 + i] = int(t[1 + i], 16)
        return a

    def build_pack(self):
        e = self.e
        e.write(LIGHTS, bytes(96 * len(PACK_LIGHTS)))
        for i, (ty, att, col, x, y, z, size, far, inten) in enumerate(
                PACK_LIGHTS):
            a = LIGHTS + 96 * i
            e.mem[a + 36] = ty
            e.mem[a + 37] = att
            e.put32(a + 44, col)
            for off, v in ((48, x), (52, y), (56, z), (60, size),
                           (76, inten), (80, far)):
                e.put32(a + off, f_to_bits(v))
        e.write(NODES, bytes(48 * len(PACK_NODES)))
        for i, (x, ext, count, kids) in enumerate(PACK_NODES):
            a = NODES + 48 * i
            e.put32(a, f_to_bits(x))
            e.write(a + 12, struct.pack("<hh", 0 if i else -1, count))
            for off, v in ((16, ext), (20, 101.0), (24, 101.0)):
                e.put32(a + off, f_to_bits(v))
            for j, k in enumerate(kids):
                e.write(a + 28 + 2 * j, struct.pack("<h", k))
        e.write(TREE, bytes(16))
        e.put32(TREE, NODES)
        e.write(TREE + 4, struct.pack("<hhhh", 2, 1, 3, 2))
        e.write(PACK, bytes(28))
        e.put32(PACK + 8, 1)
        e.put32(PACK + 12, TREE)
        e.put32(PACK + 16, len(PACK_NODES))
        e.put32(PACK + 20, LIGHTS)
        e.put32(PACK + 24, len(PACK_LIGHTS))

    def link_pack(self, on):
        e = self.e
        if on:
            for a in (G_PACKS, G_PACKS + 4):
                e.put32(a, PACK)
            for a in (PACK, PACK + 4):
                e.put32(a, G_PACKS)
        else:
            e.put32(G_PACKS, G_PACKS)
            e.put32(G_PACKS + 4, G_PACKS)

    def reset(self):
        e = self.e
        self.fill(FERCS, FERC_STRIDE * NF)
        self.fill(MODELS, MODEL_STRIDE * NM)
        for a in SEL_LIGHTS:
            e.write(a, bytes(128))
        self.npool = 0
        self.cris = []
        e.put32(G_LIST, G_LIST)
        e.put32(G_LIST + 4, G_LIST)
        self.build_pack()
        self.link_pack(0)
        e.put32(G_CAR_LOD, M32)
        e.put32(G_TIRE_LOD, M32)
        e.put32(G_F8, 0)
        e.put32(G_F16, 0)
        e.put32(G_VIEW_MODE, 1)
        e.put32(G_FLOW, 0)
        e.put32(G_CARSEL, 0)
        self.lod_to = [None, None]
        self.box = [0] * 6
        self.fe = 0
        for i in range(NV):
            v = view_at(i)
            e.write(v, bytes(VIEW_STRIDE))
            e.put32(v, i)
            e.put32(v + 68, VMATS + 64 * i)
            e.write(VMATS + 64 * i, bytes(64))

    RIDE = 0x01073000             # the script's ride, before it is copied

    def op(self, t):
        e = self.e
        c = t[0]
        if c == "I":
            k, v = int(t[1]), int(t[2])
            rd = self.put_ride(self.RIDE, t[3:])
            e.call(FE_CTOR, fer_at(k), rd, v, limit=100000)
            self.pfer(k)
        elif c == "R":
            k = int(t[1])
            rd = self.put_ride(self.RIDE, t[2:])
            e.call(FE_REINIT, fer_at(k), rd, limit=100000)
            self.pfer(k)
        elif c == "D":
            e.call(FE_DTOR, fer_at(int(t[1])), int(t[2]), limit=100000)
            self.plist()
        elif c == "S":
            f = fer_at(int(t[1]))
            fld = t[2]
            ints = {"en": 628, "u": 632, "rf": 636, "hd": 640, "cp": 644,
                    "vw": 20}
            if fld in ints:
                e.put32(f + ints[fld], int(t[3]) & M32)
            elif fld == "md":
                j = int(t[3])
                e.put32(f + 624, 0 if j < 0 else MODELS + MODEL_STRIDE * j)
            elif fld == "p":
                self.put_words(f + 32, t[3:6])
            elif fld == "b":
                self.put_words(f + 48, t[3:19])
            elif fld == "t":
                self.put_words(f + 112 + 64 * int(t[3]), t[4:20])
            elif fld == "k":
                self.put_words(f + 368 + 64 * int(t[3]), t[4:20])
            else:
                raise SystemExit("bad field %r" % (t,))
        elif c == "Q":
            self.pfer(int(t[1]))
        elif c == "W":
            self.plist()
        elif c == "G":
            e.put32(G_VIEW_MODE, int(t[1]) & M32)
        elif c == "F":
            e.put32(G_F8, int(t[1]) & M32)
            e.put32(G_F16, int(t[2]) & M32)
        elif c == "L":
            e.put32(G_CAR_LOD, int(t[1]) & M32)
            e.put32(G_TIRE_LOD, int(t[2]) & M32)
        elif c == "K":
            self.lod_to = [None if x == "-" else int(x) for x in t[1:3]]
        elif c == "X":
            self.box = [int(x, 16) for x in t[1:7]]
        elif c == "P":
            v, cars, refl, p8, p16 = (int(x) for x in t[1:6])
            e.call(FE_RENDER_ALL, view_at(v), cars, refl, p8, p16,
                   limit=400000)
            self.emit("  lod %d %d" % (s32(self.w(G_CAR_LOD)),
                                       s32(self.w(G_TIRE_LOD))))
        elif c == "C":
            e.fpr[12] = int(t[3], 16)
            e.call(SET_LIGHTING, int(t[1]) & M32, int(t[2]) & M32,
                   limit=10000)
            self.plights()
        elif c == "U":
            self.fe = int(t[1])
            e.put32(G_FLOW, 3 if self.fe else 5)
            e.put32(G_CARSEL, int(t[2]) & M32)
        elif c == "M":
            self.put_words(VMATS + 64 * int(t[1]), t[2:18])
        elif c == "Z":
            v = int(t[1])
            self.put_words(LW, t[2:18])
            rest = t[18:]
            hack = 0
            if rest[0] != "-":
                self.put_words(HACK, rest[:16])
                hack = HACK
                rest = rest[16:]
            else:
                rest = rest[1:]
            eye = 0
            if rest[0] != "-":
                self.put_words(EYE, rest[:4])
                eye = EYE
            near = s32(e.call(QUERY, QBUF, LW + 48, limit=200000))
            self.fill(LC, LC_SIZE)
            r = e.call(ELSETUP, LC, LW, hack, eye, view_at(v),
                       limit=200000)
            self.emit("  lc -> %d near %d" % (s32(r), near))
            self.plc(not self.fe, near)
        elif c == "Y":
            self.link_pack(int(t[1]))
        else:
            raise SystemExit("bad op %r" % (t,))

    def run(self, scenarios):
        for i, sc in enumerate(scenarios):
            self.emit("B %d" % i)
            self.reset()
            for ln in sc:
                self.emit("> " + ln[:40])
                self.op(ln.split())
        return self.out


# ================================================================ the build


def build_harness(tmp, name="fecar_test"):
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


# ============================================================ the mutations


def M(name, before, after, rel=FEC):
    return (name, rel, before, after)


MUTATIONS = [
    # the constructor
    M("init-type", "f->Ride.Type = -1;", "f->Ride.Type = 0;"),
    M("init-cbvd", "f->Ride.CanBeVertexDamaged = 0;",
      "f->Ride.CanBeVertexDamaged = 1;"),
    M("init-inst", "f->Ride.InstanceIndex = 0;", "f->Ride.InstanceIndex = 2;"),
    M("init-skin", "f->Ride.SkinNumber = 0;", "f->Ride.SkinNumber = 3;"),
    M("init-dash", "f->Ride.HasDash = 0;", "f->Ride.HasDash = 1;"),
    M("init-ri-null", "    f->pRenderInfo = NULL;\n    fecar_reinit",
      "    fecar_reinit"),
    M("init-no-reinit", "    fecar_reinit(f, ride);\n", ""),
    M("init-pos-x", "    f->Position.x = 0.0f;\n", "    f->Position.x = 1.0f;\n"),
    M("init-pos-y", "    f->Position.y = 0.0f;\n", "    f->Position.y = 1.0f;\n"),
    M("init-pos-z", "    f->Position.z = 0.0f;\n", "    f->Position.z = 1.0f;\n"),
    M("init-view", "f->ViewID = view_id;", "f->ViewID = 0;"),
    M("init-body", "    eIdentity(&f->BodyMatrix);\n", ""),
    M("init-tires", "for (i = 0; i < 4; i++)\n        eIdentity(&f->TireMatrices",
      "for (i = 0; i < 3; i++)\n        eIdentity(&f->TireMatrices"),
    M("init-brakes", "for (i = 0; i < 4; i++)\n        eIdentity(&f->Brake",
      "for (i = 1; i < 4; i++)\n        eIdentity(&f->Brake"),
    M("init-u632", "f->Unused632 = 1;", "f->Unused632 = 0;"),
    M("init-tail-next", "    tail->next = &f->Node;\n", ""),
    M("init-list-prev", "    FrontEndRenderingCarList.prev = &f->Node;\n", ""),
    M("init-node-prev", "f->Node.prev = tail;",
      "f->Node.prev = &FrontEndRenderingCarList;"),
    M("init-node-next", "f->Node.next = &FrontEndRenderingCarList;",
      "f->Node.next = tail;"),
    M("init-head", "tail = FrontEndRenderingCarList.prev;",
      "tail = &FrontEndRenderingCarList;"),
    M("init-model", "    f->pModel = NULL;\n    f->Enabled", "    f->Enabled"),
    M("init-en", "f->Enabled = 1;", "f->Enabled = 0;"),
    M("init-rf", "f->Reflection = 0;", "f->Reflection = 1;"),
    M("init-hd", "f->Headlights = 0;", "f->Headlights = 1;"),
    M("init-cp", "f->CopLights = 0;", "f->CopLights = 1;"),
    # ReInit
    M("reinit-no-del", "        carrenderinfo_delete(f->pRenderInfo, 3);\n"
      "        f->pRenderInfo = NULL;\n    }\n    if (ride",
      "        f->pRenderInfo = NULL;\n    }\n    if (ride"),
    M("reinit-del-flags", "        carrenderinfo_delete(f->pRenderInfo, 3);\n"
      "        f->pRenderInfo = NULL;\n    }\n    if (ride",
      "        carrenderinfo_delete(f->pRenderInfo, 1);\n"
      "        f->pRenderInfo = NULL;\n    }\n    if (ride"),
    M("reinit-keep", "        f->pRenderInfo = NULL;\n    }\n    if (ride",
      "    }\n    if (ride"),
    M("reinit-no-copy", "        f->Ride = *ride;\n", ""),
    M("reinit-ride-src", "&f->Ride, NULL);", "ride, NULL);"),
    M("reinit-car", "&f->Ride, NULL);", "&f->Ride, (Car *)f);"),
    M("reinit-pool", "\"CarRenderInfo\", 0, 16)", "\"CarRenderInfo\", 0, 32)"),
    M("reinit-guard", "    if (ride != NULL) {", "    if (1) {"),
    # the destructor
    M("del-wait", "        gEWaitUntilRenderingDoneFn();\n", ""),
    M("del-cri-flags", "        carrenderinfo_delete(f->pRenderInfo, 3);\n"
      "        f->pRenderInfo = NULL;\n    }\n    if (f->pModel",
      "        carrenderinfo_delete(f->pRenderInfo, 1);\n"
      "        f->pRenderInfo = NULL;\n    }\n    if (f->pModel"),
    M("del-no-cri", "        carrenderinfo_delete(f->pRenderInfo, 3);\n"
      "        f->pRenderInfo = NULL;\n    }\n    if (f->pModel",
      "        f->pRenderInfo = NULL;\n    }\n    if (f->pModel"),
    M("del-cri-null", "        f->pRenderInfo = NULL;\n    }\n    if (f->pModel",
      "    }\n    if (f->pModel"),
    M("del-model-flags", "emodel_delete(f->pModel, 3);",
      "emodel_delete(f->pModel, 1);"),
    M("del-no-model", "        emodel_delete(f->pModel, 3);\n", ""),
    M("del-model-null", "        f->pModel = NULL;\n    }\n    f->Node",
      "    }\n    f->Node"),
    M("del-unlink-next", "    f->Node.prev->next = f->Node.next;\n", ""),
    M("del-unlink-prev", "    f->Node.next->prev = f->Node.prev;\n", ""),
    M("del-free-bit", "    if (flags & 1)\n        bFree(f);",
      "    if (flags & 2)\n        bFree(f);"),
    M("del-free-always", "    if (flags & 1)\n        bFree(f);",
      "    bFree(f);"),
    # RenderFrontEndCar
    M("rfc-car-lod", "s_car_lod[2] = { 0, 1 };", "s_car_lod[2] = { 0, 2 };"),
    M("rfc-tire-lod", "s_tire_lod[2] = { 0, 1 };",
      "s_tire_lod[2] = { 1, 1 };"),
    M("rfc-car-index", "= s_car_lod[reflection];", "= s_car_lod[0];"),
    M("rfc-tire-index", "= s_tire_lod[reflection];", "= s_tire_lod[1];"),
    M("rfc-restore-car-cond", "    if (ForceCarLOD == car_lod)\n", ""),
    M("rfc-restore-tire-cond", "    if (ForceTireLOD == tire_lod)\n", ""),
    M("rfc-no-restore-car", "        ForceCarLOD = old_car;\n", "        ;\n"),
    M("rfc-no-restore-tire", "        ForceTireLOD = old_tire;\n",
      "        ;\n"),
    M("rfc-swap", "    ForceTireLOD = tire_lod;\n    carrenderinfo_render",
      "    ForceTireLOD = car_lod + 1;\n    carrenderinfo_render"),
    M("rfc-flags", "brake_matrices, flags, forced_lights);",
      "brake_matrices, flags | 2, forced_lights);"),
    # RenderFrontEndCars
    M("rfcs-ri-null", "if (ri == NULL || f->Enabled", "if (f->Enabled"),
    M("rfcs-enabled", "f->Enabled == 0 || ", ""),
    M("rfcs-view", " || f->ViewID != view->ID)", ")"),
    M("rfcs-mode", "if (mode != 1 || !reflections)", "if (!reflections)"),
    M("rfcs-mode-lt", "if (mode != 1 || !reflections)",
      "if (mode < 1 || !reflections)"),
    M("rfcs-refl-arg", "if (mode != 1 || !reflections)", "if (mode != 1)"),
    M("rfcs-refl-flags", "flags = 17;", "flags = 16;"),
    M("rfcs-cars", "            if (!cars)\n                continue;\n", ""),
    M("rfcs-cars-flags", "            flags = 0;\n", "            flags = 1;\n"),
    M("rfcs-p8", "if (!pass8)", "if (pass8)"),
    M("rfcs-p16", "if (!pass16)", "if (pass16)"),
    M("rfcs-p8-bit", "            flags |= 8;\n        if (!pass16)",
      "            flags |= 4;\n        if (!pass16)"),
    M("rfcs-force8", "        if (FrontEndCarForceFlag8)\n"
      "            flags |= 8;\n", ""),
    M("rfcs-force16", "        if (FrontEndCarForceFlag16)\n"
      "            flags |= 16;\n", ""),
    M("rfcs-force-swap", "if (FrontEndCarForceFlag8)", "if (FrontEndCarForceFlag16)"),
    M("rfcs-model-matrix", "gEModelRenderFn(f->pModel, &f->BodyMatrix,",
      "gEModelRenderFn(f->pModel, &f->TireMatrices[0],"),
    M("rfcs-model-flags", "&f->BodyMatrix, NULL, flags);",
      "&f->BodyMatrix, NULL, 0);"),
    M("rfcs-model-continue", "NULL, flags);\n            continue;",
      "NULL, flags);"),
    M("rfcs-bbox-model", "&ri->Body[0]", "&ri->Body[1]"),
    M("rfcs-centre-half", "(mx.x - mn.x) * 0.5f", "(mx.x - mn.x) * 0.25f"),
    M("rfcs-centre-sign", "pos.x = f->Position.x - (", "pos.x = f->Position.x + ("),
    M("rfcs-centre-min", "(mn.x + (mx.x - mn.x)", "(mx.x + (mx.x - mn.x)"),
    M("rfcs-centre-y", "(mn.x + (mx.x - mn.x) * 0.5f)",
      "(mn.y + (mx.y - mn.y) * 0.5f)"),
    M("rfcs-pos-copy", "        pos = f->Position;\n",
      "        pos.y = f->Position.y;\n        pos.z = f->Position.z;\n"
      "        pos.pad = 0.0f;\n"),
    M("rfcs-tire-copy", "tires[i] = f->TireMatrices[i];",
      "tires[i] = f->BrakeMatrices[i];"),
    M("rfcs-brake-copy", "brakes[i] = f->BrakeMatrices[i];",
      "brakes[i] = f->TireMatrices[i];"),
    M("rfcs-forced-head", "forced = f->Headlights ? 3 : 0;",
      "forced = f->Headlights ? 1 : 0;"),
    M("rfcs-forced-cop", "            forced |= 8;\n", "            forced |= 4;\n"),
    M("rfcs-forced-refl", "        if (!f->Reflection) {\n            forced",
      "        {\n            forced"),
    M("rfcs-unused-arg", "f->Unused632, f->Reflection, flags",
      "0, f->Reflection, flags"),
    M("rfcs-refl-arg2", "f->Unused632, f->Reflection, flags",
      "f->Unused632, 0, flags"),
    M("rfcs-body-arg", "&pos, &f->BodyMatrix, tires",
      "&pos, &f->TireMatrices[0], tires"),
    M("rfcs-ff", "flags, forced);\n    }", "forced, flags);\n    }"),
    # SetSelectCarLighting
    M("ssl-view", "view_id == 2 ? 1 : 0", "view_id == 1 ? 1 : 0", rel=ELC),
    M("ssl-locked", "    if (locked) {", "    if (locked == 1) {", rel=ELC),
    M("ssl-dark-colour", "s->Light[i].Colour = s_dark_colour[i];",
      "s->Light[i].Colour = s_car_colour[i];", rel=ELC),
    M("ssl-dark-dir", "s->Light[i].Direction = s_dark_dir[i];",
      "s->Light[i].Direction = s_car_dir[i];", rel=ELC),
    M("ssl-dark-amb", "s->Ambient = s_dark_ambient;",
      "s->Ambient = s_car_ambient;", rel=ELC),
    M("ssl-dark-return", "        s->Ambient = s_dark_ambient;\n        return;\n",
      "        s->Ambient = s_dark_ambient;\n", rel=ELC),
    M("ssl-add", "add = bright * 30.0f;", "add = bright * 32.0f;", rel=ELC),
    M("ssl-min-nan", "    return 255.0f < v ? 255.0f : v;",
      "    return v < 255.0f ? v : 255.0f;", rel=ELC),
    M("ssl-min-bound", "    return 255.0f < v ? 255.0f : v;",
      "    return 250.0f < v ? 250.0f : v;", rel=ELC),
    M("ssl-lane-y", "min255(s_car_colour[i].y + add)",
      "min255(s_car_colour[i].z + add)", rel=ELC),
    M("ssl-lane-z", "min255(s_car_colour[i].z + add)",
      "min255(s_car_colour[i].x + add)", rel=ELC),
    M("ssl-amb-add", "min255(s_car_ambient.x)", "min255(s_car_ambient.x + add)",
      rel=ELC),
    M("ssl-amb-lane", "min255(s_car_ambient.z)", "min255(s_car_ambient.z + 1)",
      rel=ELC),
    M("ssl-lit-dir", "s->Light[i].Direction = s_car_dir[i];",
      "s->Light[i].Direction = s_dark_dir[i];", rel=ELC),
    M("ssl-tab-colour", "{ 128.0f, 128.0f, 180.0f, 0.0f },",
      "{ 128.0f, 128.0f, 181.0f, 0.0f },", rel=ELC),
    M("ssl-tab-amb", "s_car_ambient = { 32.0f, 32.0f, 32.0f, 0.0f };",
      "s_car_ambient = { 32.0f, 33.0f, 32.0f, 0.0f };", rel=ELC),
    M("ssl-tab-dir", "{ 6.82f, -6.1f, -8.56f, 0.0f },",
      "{ 6.82f, -6.1f, -8.5f, 0.0f },", rel=ELC),
    M("ssl-tab-dark-dir", "{ 0.307f, 10.0f, 2.82f, 0.0f },",
      "{ 0.31f, 10.0f, 2.82f, 0.0f },", rel=ELC),
    M("ssl-tab-dark-colour", "static const bVector4 s_dark_colour[3];",
      "static const bVector4 s_dark_colour[3] = { { 1.0f } };", rel=ELC),
    M("ssl-tab-dark-amb", "static const bVector4 s_dark_ambient;",
      "static const bVector4 s_dark_ambient = { 0.0f, 0.0f, 1.0f };",
      rel=ELC),
    # elSetupLightContext's frontend
    M("lc-fe-flag", "frontend = gElInFrontendFn != NULL && gElInFrontendFn();",
      "frontend = 0;", rel=ELC),
    M("lc-fe-dirs", "    if (frontend) {\n        if (gElCarSelectActiveFn",
      "    if (0) {\n        if (gElCarSelectActiveFn", rel=ELC),
    M("lc-cs-dirs", "gElCarSelectActiveFn()) {\n            const eSelectCarLights"
      " *s =\n                &elSelectCarLights[view->ID == 2 ? 1 : 0];\n"
      "            bMatrix4 vinv;",
      "gElCarSelectActiveFn() && 0) {\n            const eSelectCarLights"
      " *s =\n                &elSelectCarLights[view->ID == 2 ? 1 : 0];\n"
      "            bMatrix4 vinv;", rel=ELC),
    M("lc-dir-view", "&elSelectCarLights[view->ID == 2 ? 1 : 0];\n"
      "            bMatrix4 vinv;", "&elSelectCarLights[0];\n"
      "            bMatrix4 vinv;", rel=ELC),
    M("lc-dir-inv", "eInvertRotationMatrix(&vinv, view->WorldViewMatrix);",
      "vinv = *view->WorldViewMatrix;", rel=ELC),
    M("lc-dir-src", "(const bVector3 *)&s->Light[i].Direction);",
      "(const bVector3 *)&s->Light[i].Colour);", rel=ELC),
    M("lc-fe-dir-table", "dir[i] = elFrontEndLightDir[i];",
      "dir[i] = elFrontEndLightDir[2 - i];", rel=ELC),
    M("lc-fe-tab-dir", "{ 4.3f, 2.5f, 2.5f, 0.0f },",
      "{ 4.2f, 2.5f, 2.5f, 0.0f },", rel=ELC),
    M("lc-fe-tab-colour", "    { 128.0f, 128.0f, 128.0f, 0.0f },\n"
      "    { 64.0f, 64.0f, 64.0f, 0.0f },\n    { 64.0f",
      "    { 127.0f, 128.0f, 128.0f, 0.0f },\n"
      "    { 64.0f, 64.0f, 64.0f, 0.0f },\n    { 64.0f", rel=ELC),
    M("lc-fe-tab-amb", "    { 64.0f, 64.0f, 64.0f, 0.0f },\n"
      "    { 0.0f, 0.0f, 0.0f, 0.0f },\n};",
      "    { 64.0f, 64.0f, 64.0f, 0.0f },\n"
      "    { 0.0f, 1.0f, 0.0f, 0.0f },\n};", rel=ELC),
    M("lc-cs-colours", "gElCarSelectActiveFn()) {\n            const eSelectCarLights"
      " *s =\n                &elSelectCarLights[view->ID == 2 ? 1 : 0];\n\n",
      "gElCarSelectActiveFn() && 0) {\n            const eSelectCarLights"
      " *s =\n                &elSelectCarLights[view->ID == 2 ? 1 : 0];\n\n",
      rel=ELC),
    M("lc-col-view", "&elSelectCarLights[view->ID == 2 ? 1 : 0];\n\n",
      "&elSelectCarLights[1];\n\n", rel=ELC),
    M("lc-col-amb", "            c[3] = &s->Ambient;\n", "", rel=ELC),
    M("lc-col-w", "row->w = i == 3 ? 128.0f : 0.0f;", "row->w = 128.0f;",
      rel=ELC),
    M("lc-col-w3", "row->w = i == 3 ? 128.0f : 0.0f;",
      "row->w = i == 3 ? 127.0f : 0.0f;", rel=ELC),
    M("lc-col-z", "            row->z = c[i]->z;\n            row->w",
      "            row->z = c[i]->y;\n            row->w", rel=ELC),
    M("lc-si", "        lc->SunlightIntensity = 1.0f;\n", "", rel=ELC),
    M("lc-fe-sun", "    } else {\n        // The sun's colour",
      "    }\n    {\n        // The sun's colour", rel=ELC),
]

EQUIVALENT = {
    "rfcs-unused-arg": "RenderFrontEndCar never reads its seventh argument",
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    hostbuild.recover()
    m = Model()
    sc = script()
    base = m.run(sc)
    caught, survived, missing, equivalent = 0, [], [], []
    scdir = tempfile.TemporaryDirectory()
    scp = Path(scdir.name) / "scenarios.txt"
    scp.write_text(encode(sc))
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, scp, out)
        if diff(base, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for mut in todo:
        name, rel, before, after = mut
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if text.count(probe) != 1:
            missing.append(name)
            print("  %-44s PATTERN %s" % (
                name, "NOT FOUND" if not text.count(probe) else "NOT UNIQUE"))
            continue
        new = text.replace(probe, repl, 1)
        try:
            hostbuild.write_source(path, new)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = build_harness(tmp)
                except SystemExit:
                    print("  %-44s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, scp, out)
                if rc == pcc.HARNESS_HUNG:
                    print("  %-44s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-44s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-44s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-44s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-44s SURVIVED" % name)
                    survived.append(name)
        finally:
            try:
                hostbuild.write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))
    scdir.cleanup()

    real = [m for m in todo if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    ran = {m[0] for m in todo}
    stale = [n for n in EQUIVALENT
             if n not in equivalent and n not in missing
             and (n in ran or only is None)]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally above is over %d of %d"
              % (len(missing), len(real), len(todo)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
    for name in holes:
        print("  unexplained: %s" % name)
    for name in stale:
        print("  listed as equivalent but %s: %s"
              % ("caught" if name in ran else "names no mutation", name))
    return 1 if (holes or missing or stale) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--dump", metavar="PREFIX")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None))

    m = Model()
    sc = script()
    lines = m.run(sc)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = Path(tmp) / "scenarios.txt"
        scp.write_text(encode(sc))
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(lines, harness)
    ops = sum(len(s) for s in sc)
    print("%d scenarios, %d ops, %d lines, %d differ"
          % (len(sc), ops, len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
