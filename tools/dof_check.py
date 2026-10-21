#!/usr/bin/env python3
"""Cross-check 3DS Files/source/efocus.c (EcstasyE.obj's depth of field)
against retail's image, SLES_507.31, run in mipsemu
(retail_model.RetailEmu).

The model is the image: GetFocusPalette, the three Map helpers,
CreateFocusPalette (with the image's RemapLinearIntoClut8) and
eAttachDepthOfField run as shipped. Stubbed:

    eGetView                the scenario's views, 128 apart
    bMemSet                 a memset
    AttachImageDataPacket   silent: the palettes' upload
    eDmaChain::Add          for each view's packet, the line the port's
                            gEDofAttachFn prints: the view, its palette
                            and the band; for the blur's, gEDofBlurFn's

The band is the image's t0 and t1, read from registers t0 and t1 at
0x00119d9c, once the edge loop is done; a CreateFocusPalette that clears
the palette leaves none. The frame's memory, where the image builds the
packets, is the model's, and never runs out: the port's cannot.

The harness links efocus.c (and efog.c, for RemapLinearIntoClut8), gives
it eGetView and ZRanges, and prints the same lines. The palettes are
dumped after each eAttachDepthOfField and each CreateFocusPalette.

The PICA's side, efocus_plan and efocus_pica_alpha, has nothing in the
image to run. For it the model is the spec written out here, over the
image's palette and band: the plan's steps and the alpha they leave at
each depth of D24S. And where a scenario asks (P, not Q), the spec is held
to the image's palette: at every 24-bit depth up to 0x20400, the alpha the
passes leave is within TOL of what the palette has for the PS2's index
there (efog_depth_alpha of the GS's Z, as trackview.c's gs_z makes it),
or for the index either side of it. That is the write-up's half a step,
the A byte's offset of 32 and the combiners' bytes.

Scenarios: each of the cameras' focus over the race's near and far; two
views; DrawDepthOfField off; no focus anywhere, and on one view only; a
depth of field alone and a focal distance alone; the overrides; a
negative depth of field; bands past either end and exactly on an entry's
depth; FocusRampLength from -5 to 300; the alpha's minimum and maximum
apart, reversed, past 128 and equal; FocusFirstPrevious at 0, past
everything, -inf and NaN; FocusPrintPalette; other depth ranges; a near
plane at and past the far; Active bytes past 1; CreateFocusPalette with
a NULL view and palette; GetFocusPalette by ID; the helpers and the
PICA's bytes.

    python tools/dof_check.py
    python tools/dof_check.py --mutate [--only a,b]
    python tools/dof_check.py --dump out/dof
"""
import argparse
import math
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import physicscar_check as pcc
import retail_model
from mipsemu import M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/dof_test.c"
EFC = "3DS Files/source/efocus.c"
SOURCES = [HARNESS, EFC, "3DS Files/source/efog.c",
           "3DS Files/source/weatherman.c", "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c"]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = retail_model.RETAIL_GP         # 0x003358f0
DRAW = GP - 24136
PRINT = GP - 24132
AMIN = GP - 24128
AMAX = GP - 24124
FOCAL = GP - 24120
DOF = GP - 24116
BLEND = GP - 24112
SAMPLES = GP - 24068
LEN = GP - 24056
FIRST = GP - 24052
JITTER = 0x002da750
FOCUS_PAL = 0x002db380
ZR1_MIN = 0x002c9e38                # ZRanges[1].ZMin, then ZMax
ZR1_MAX = 0x002c9e3c
FMEM_PTR = GP - 19388               # the frame's memory
FMEM_END = GP - 19384
FMEM_FAIL = GP - 19372
FMEM_WANT = GP - 19368

GET_PALETTE = 0x00119b28
S2P = 0x00119b58
P2S = 0x00119b70
S2V = 0x00119b90
CREATE = 0x00119c20
ATTACH = 0x00119f70
BAND_PC = 0x00119d9c                # t0 and t1 in registers 8 and 9

E_GET_VIEW = 0x00107c90
ATTACH_IMAGE = 0x00108a50
DMA_ADD1 = 0x00104808               # eDmaChain::Add(void *)
BMEMSET = 0x00250340
VIEW_ADD_RA = 0x0011a37c
BLUR_ADD_RA = 0x0011a958

ATTACH_ARGS = (0x344000, 0x342c00)  # eDisplayFrame's

# Where the model keeps the scenario's objects.
VIEWS = 0x01010000                  # 128 apart
RTS = 0x01011000                    # 256 apart
CAMS = 0x01012000                   # 512 apart
PAL = 0x01014100
TMP_VIEW = 0x01014600
CHAIN = 0x01016000
FMEM = 0x01020000
FMEM_SIZE = 0x10000
NUM_VIEWS = 5

# The helpers' operands, as the harness lists them.
S2P_ZS = (0x00000000, 0x40000000, 0x40000010, 0x400ff010, 0x40000fff,
          0x40001000, 0x4007f000, 0x40080000, 0x400ff000, 0x40100000,
          0x3f800000, 0xbf800000, 0x7f800000, 0xffffffff, 0x12345678)
P2S_IS = (0, 1, 2, 15, 16, 127, 128, 200, 254, 255, 256, 0x1ff,
          0xffffffff, 0x80000000)
S2V_ARGS = ((0x3f000000, 0x44fa0000, 0x40000010),
            (0x3f000000, 0x44fa0000, 0x40400000),
            (0x3f000000, 0x44fa0000, 0x407ff000),
            (0x3f000000, 0x44fa0000, 0x40800000),
            (0x3f800000, 0x44bb8000, 0x40200000),
            (0x3e800000, 0x457a0000, 0x40100000),
            (0x41200000, 0x41200000, 0x40400000),
            (0x447a0000, 0x3f800000, 0x40400000),
            (0x3f000000, 0x44fa0000, 0x00000000),
            (0x3f000000, 0x44fa0000, 0xc0000000))
PICA_GS = (0, 1, 2, 63, 64, 65, 100, 127, 128, 129, 200, 255, 256, 1000,
           0xffffffff)
GET_IDS = (-1, 0, 1, 2, 3, 4, 5, 9, 0x7fffffff, -0x80000000)


def make_d24s():
    edges = (1, 0x7f, 0x80, 0x1ff, 0x200, 0x3ff, 0x400, 0x1e0, 0x1df,
             0xffff, 0x10000, 0x10001, 0x101ff, 0x1fdff, 0x1fe00, 0x1feff,
             0x1ff00, 0x1ffff, 0x20000, 0x20001, 0x2ffff, 0x30000, 0x7fffff,
             0x800000, 0xfffffe, 0xffffff)
    out = []
    for d in list(range(0, 0x20401, 0x100)) + list(edges):
        if d not in out:
            out.append(d)
    return out


D24S = make_d24s()

# The bound's slack, in the PICA's bytes: the combiners' products, each
# taken down, and the INTERPOLATE's. One ramp step is about 10.6.
TOL = 2
BOUND_TOP = 0x20400


def fb(x):
    if isinstance(x, int):
        return x & M32
    return struct.unpack("<I", struct.pack("<f", x))[0]


def bf(u):
    return struct.unpack("<f", struct.pack("<I", u & M32))[0]


def f32(x):
    """x rounded to a float, as the host's and the PICA's floats hold it."""
    if math.isnan(x) or math.isinf(x):
        return x
    try:
        return struct.unpack("<f", struct.pack("<f", x))[0]
    except OverflowError:
        return math.copysign(math.inf, x)


def trunc_w(x):
    """ee_trunc_w: toward zero, saturated, NaN as 0."""
    if x != x:
        return 0
    if x >= 2147483648.0:
        return 0x7fffffff
    if x < -2147483648.0:
        return -0x80000000
    return int(x)


FLT_MAX = 0xff7fffff                # -FLT_MAX's bits


class Scenario(object):
    def __init__(self, name, ops, views=None, draw=1, prnt=0, amin=0.0,
                 amax=128.0, focal=0.0, dof=0.0, length=24, first=FLT_MAX,
                 zr=(0x40000010, 0x40800000)):
        self.name = name
        self.ops = ops
        # (active, near, far, focal, dof) for views 0 .. 4.
        v = [(0, 0.5, 10000.0, 0.0, 0.0)] * NUM_VIEWS
        for i, t in (views or {}).items():
            v[i] = t
        self.views = v
        self.draw = draw
        self.prnt = prnt
        self.amin = fb(amin)
        self.amax = fb(amax)
        self.focal = fb(focal)
        self.dof = fb(dof)
        self.length = length
        self.first = fb(first)
        self.zr = zr

    def lines(self):
        out = ["S %s" % self.name,
               "g %d %d %x %x %x %x %d %x" % (
                   self.draw & M32, self.prnt & M32, self.amin, self.amax,
                   self.focal, self.dof, self.length, self.first),
               "z %x %x" % self.zr]
        for i, (a, n, f, fo, d) in enumerate(self.views):
            out.append("v %d %x %x %x %x %x" % (i, a, fb(n), fb(f), fb(fo),
                                                 fb(d)))
        out.append("o " + self.ops)
        return out


def view_depths(near, far, zr=(0x40000010, 0x40800000)):
    """CreateFocusPalette's d[], nearest first, in floats as the image
    rounds them: for picking a focus exactly on an entry's depth."""
    zmin, zmax = bf(zr[0]), bf(zr[1])
    near, far = f32(near), f32(far)
    span = f32(far - near)
    a = f32(f32(f32(far * near) * f32(zmax - zmin)) / span)
    b = f32(f32(f32(-zmax * near) + f32(zmin * far)) / span)
    d = [0.0] * 256
    for i in range(256):
        sz = bf(zr[0] | (i & 0xff) << 12)
        d[255 - i] = f32(a / f32(sz - b))
    return d


CHASE = (1, 0.5, 10000.0, 15.0, 65.0)
BUMPER = (1, 0.5, 10000.0, 10.0, 7.5)
FLY = (1, 0.5, 10000.0, 2.0, 30.0)
ORBIT = (1, 0.5, 10000.0, 6.0, 8.0)
TRACKCAR = (1, 0.5, 10000.0, 40.0, 7.5)
OFF = (1, 0.5, 10000.0, 0.0, 0.0)


def script():
    d = view_depths(0.5, 10000.0)
    S = Scenario
    return [
        S("chase", "A P1 g", {1: CHASE}),
        S("chase and bumper", "A P1 P2", {1: CHASE, 2: BUMPER}),
        S("fly", "A P1", {1: FLY}),
        S("orbit", "A P1", {1: ORBIT}),
        S("trackcar", "A P1", {1: TRACKCAR}),
        S("bumper, view 2 alone", "A P2", {2: BUMPER}),
        S("far focus", "A P1", {1: (1, 0.5, 10000.0, 800.0, 400.0)}),
        S("draw off", "A P1", {1: CHASE}, draw=0),
        S("draw 2", "A", {1: CHASE}, draw=2),
        S("no focus", "A P1 P2", {1: OFF, 2: OFF}),
        S("one cleared", "A P1 P2", {1: OFF, 2: CHASE}),
        S("second cleared", "A P1 P2", {1: CHASE, 2: OFF}),
        S("inactive with focus", "A P1 P2",
          {1: CHASE, 2: (0, 0.5, 10000.0, 10.0, 7.5)}),
        S("views 3 and 4 skipped", "A",
          {3: CHASE, 4: BUMPER, 0: CHASE}),
        S("dof only", "A P1", {1: (1, 0.5, 10000.0, 0.0, 50.0)}),
        S("focal only", "A P1", {1: (1, 0.5, 10000.0, 20.0, 0.0)}),
        S("override focal", "A P1", {1: CHASE}, focal=30.0),
        S("override dof", "A P1", {1: CHASE}, dof=100.0),
        S("override both", "A P1", {1: OFF}, focal=12.0, dof=4.0),
        S("override negative focal", "A Q1", {1: CHASE}, focal=-5.0),
        S("negative dof", "A Q1", {1: (1, 0.5, 10000.0, 15.0, -40.0)}),
        S("huge focus", "A P1", {1: (1, 0.5, 10000.0, 1.0e6, 10.0)}),
        S("tiny focus", "A P1", {1: (1, 0.5, 10000.0, 0.001, 0.001)}),
        S("focus on entry 100", "A P1", {1: (1, 0.5, 10000.0, d[100], 0.0)}),
        S("focus on entry 105", "A P1", {1: (1, 0.5, 10000.0, d[105], 0.0)}),
        S("focus on entry 0", "A P1", {1: (1, 0.5, 10000.0, d[0], 0.0)}),
        S("focus on entry 255", "A P1", {1: (1, 0.5, 10000.0, d[255], 0.0)}),
        S("focus on entry 1", "A P1", {1: (1, 0.5, 10000.0, d[1], 0.0)}),
        S("band on entries 40 .. 90", "A P1",
          {1: (1, 0.5, 10000.0, f32((d[40] + d[90]) * 0.5),
               f32(d[90] - d[40]))}),
        S("band 40 .. 90, len 1, min 10 max 100", "A P1",
          {1: (1, 0.5, 10000.0, f32((d[40] + d[90]) * 0.5),
               f32(d[90] - d[40]))}, length=1, amin=10.0, amax=100.0),
        S("band 40 .. 90, len 0, min 10 max 100", "A P1",
          {1: (1, 0.5, 10000.0, f32((d[40] + d[90]) * 0.5),
               f32(d[90] - d[40]))}, length=0, amin=10.0, amax=100.0),
        S("band 40 .. 90, min -0.7 max 64", "A P1",
          {1: (1, 0.5, 10000.0, f32((d[40] + d[90]) * 0.5),
               f32(d[90] - d[40]))}, amin=-0.7, amax=64.0),
        S("far edge past all", "A P1",
          {1: (1, 0.5, 10000.0, 5.0e5, f32(2.0 * (5.0e5 - d[60])))}),
        S("first on the far edge", "A Q1",
          {1: (1, 0.5, 10000.0, 2.0, 2.0)}, first=3.0),
        S("first 0", "A Q1", {1: CHASE}, first=0.0),
        S("first past all", "A Q1", {1: CHASE}, first=1.0e30),
        S("first -inf", "A Q1", {1: CHASE}, first=0xff800000),
        S("first NaN", "A Q1", {1: CHASE}, first=0x7fc00000),
        S("len 0", "A P1 P2", {1: CHASE, 2: BUMPER}, length=0),
        S("len 1", "A P1 P2", {1: CHASE, 2: BUMPER}, length=1),
        S("len 2", "A P1 P2", {1: CHASE, 2: BUMPER}, length=2),
        S("len 7", "A P1 P2", {1: CHASE, 2: BUMPER}, length=7),
        S("len 255", "A P1 P2", {1: CHASE, 2: BUMPER}, length=255),
        S("len 300", "A P1", {1: FLY}, length=300),
        S("len -5", "A P1", {1: CHASE}, length=-5),
        S("len 0 with a min", "A P1 P2", {1: CHASE, 2: BUMPER}, length=0,
          amin=10.0, amax=100.0),
        S("min 10 max 100", "A P1 P2", {1: CHASE, 2: BUMPER}, amin=10.0,
          amax=100.0),
        S("min 128 max 0", "A P1 P2", {1: CHASE, 2: BUMPER}, amin=128.0,
          amax=0.0),
        S("min 0 max 255", "A Q1 Q2", {1: CHASE, 2: BUMPER}, amax=255.0),
        S("min -10 max 300", "A Q1", {1: BUMPER}, amin=-10.0, amax=300.0),
        S("min 0.5 max 127.9", "A P1", {1: BUMPER}, amin=0.5, amax=127.9),
        S("min and max 0", "A P1", {1: CHASE}, amax=0.0),
        S("min and max 64", "A P1", {1: CHASE}, amin=64.0, amax=64.0),
        S("print", "g A g A g", {1: CHASE}, prnt=1),
        S("z 2 .. 4", "A Q1", {1: CHASE}, zr=(0x40000000, 0x40800000)),
        S("z to 3", "A Q1 H", {1: CHASE}, zr=(0x40000010, 0x40400000)),
        S("z from 1", "A Q1", {1: CHASE}, zr=(0x3f800000, 0x40800000)),
        S("near at far", "A Q1", {1: (1, 10.0, 10.0, 15.0, 65.0)}),
        S("near past far", "A Q1", {1: (1, 1000.0, 1.0, 15.0, 65.0)}),
        S("near 1 far 1500", "A P1", {1: (1, 1.0, 1500.0, 15.0, 65.0)}),
        S("active bytes", "A P1 P2",
          {1: (2, 0.5, 10000.0, 15.0, 65.0),
           2: (0x80, 0.5, 10000.0, 10.0, 7.5)}),
        S("create", "C1 Cn Cp1 C2 C0 C3",
          {1: CHASE, 2: (0, 0.5, 10000.0, 0.0, 0.0),
           0: BUMPER, 3: FLY}),
        S("twice", "A A P1", {1: CHASE}),
        S("plan before any", "Q1 Q2", {1: CHASE}),
        S("helpers", "G H B", {1: CHASE}),
    ]


# =========================================================== the PICA's spec


def clut_index(k):
    return (k & ~0x18) | ((k & 8) << 1) | ((k & 0x10) >> 1)


def pica_byte(g):
    return 255 if g >= 128 else (g * 255 + 64) // 128


def sat8(v):
    return 0 if v < 0 else 255 if v > 255 else v


class Step(object):
    def __init__(self, alpha=0):
        self.ramp = 0
        self.alpha = alpha
        self.farb = 0
        self.nearb = 0
        self.quads = 0
        self.times = 0
        self.k = 0
        self.min = 0
        self.max = 0

    def text(self, at):
        return ("[at %08x ramp %d alpha %d far %d near %d q %d t %d k %d "
                "min %d max %d]" % (fb(at), self.ramp, self.alpha, self.farb,
                                    self.nearb, self.quads, self.times,
                                    self.k, self.min, self.max))


def step_scale(s, length, quads_left):
    if length >= 1:
        f = f32(255.0 / f32(2.0 * f32(float(length))))
    else:
        f = 255.0
    s.quads = 0
    while f > 8.0 and s.quads < quads_left:
        f = f32(f * 0.25)
        s.quads += 1
    if f > 8.0:
        s.quads += 1
        s.times = 4
        s.k = 0
        return
    if f >= 1.0:
        s.times = 4 if f > 4.0 else 2 if f > 2.0 else 1
        k = f32(f32(f / s.times) - 1.0)
    else:
        s.times = 0
        k = f
    s.k = trunc_w(f32(f32(k * 255.0) + 0.5)) & 0xff


def region_step(alpha, band, lo, hi, base, amin, amax, length):
    first = alpha(lo)
    j = lo + 1
    while j <= hi and alpha(j) == first:
        j += 1
    if j > hi or band is None:
        return Step(pica_byte(first))
    s = Step()
    s.ramp = 1
    s.min = pica_byte(trunc_w(amin) & 0xff)
    s.max = pica_byte(trunc_w(amax) & 0xff)
    far = 255 - band[1]
    near = 255 - band[0]
    s.farb = 2 * (far - base)
    s.nearb = 2 * (near - base) + 1
    both = 1 if (s.farb > 0 and s.nearb < 255) else 0
    stages = (3 if both else 1) + 1 + (1 if (s.min != 0 or s.max != 255)
                                       else 0)
    step_scale(s, length, 6 - stages + both)
    return s


def plan(palette, band, amin, amax, length):
    """efocus_plan: [(at, step)], empty for a palette with no alpha."""
    if all(p >> 24 == 0 for p in palette):
        return []

    def alpha(j):
        return palette[clut_index(j)] >> 24

    steps = [(0.0, region_step(alpha, band, 0, 127, 0, amin, amax, length)),
             (f32(1.0 / 256.0),
              region_step(alpha, band, 128, 255, 128, amin, amax, length)),
             (f32(2.0 / 256.0), Step(pica_byte(alpha(255))))]
    out = []
    for at, s in steps:
        if out and not out[-1][1].ramp and not s.ramp \
                and out[-1][1].alpha == s.alpha:
            continue
        out.append((at, s))
    return out


def step_alpha(s, d24):
    b = d24 >> 8 & 0xff
    if not s.ramp:
        return s.alpha
    w = 0
    if s.farb > 0:
        w += sat8(s.farb - b)
    if s.nearb < 255:
        w += sat8(b - s.nearb)
    w = sat8(w * (s.times or 1))
    for _ in range(s.quads):
        w = sat8(w * 4)
    if s.times:
        x = sat8(w + w * s.k // 255)
    else:
        x = w * s.k // 255
    return (s.max * x + s.min * (255 - x)) // 255


def pica_alpha(p, d24):
    if not p:
        return 0
    depth = f32(float(d24) / 16777215.0)
    at = 0
    for n in range(1, len(p)):
        if p[n][0] <= depth:
            at = n
    return step_alpha(p[at][1], d24)


def gs_z(d24, zr):
    """trackview.c's gs_z: the GS's Z for a PICA depth."""
    if d24 == 0:
        return 0
    zmin = f32(f32(bf(zr[0]) - 2.0) * 4194304.0)
    zmax = f32(f32(bf(zr[1]) - 2.0) * 4194304.0)
    t = f32(float(d24) / 16777215.0)
    z = f32(zmin + f32(f32(zmax - zmin) * t))
    return 0xffffff if z >= 16777215.0 else int(z)


def depth_alpha(z):
    return 255 if z > 0xffff else z >> 8 & 0xff


def bound(p, palette, zr):
    """The first depth whose alpha is off the palette's by more than TOL,
    as a line, or None."""
    ideal = [pica_byte(palette[clut_index(j)] >> 24) for j in range(256)]
    lo = [min(ideal[max(j - 1, 0):j + 2]) - TOL for j in range(256)]
    hi = [max(ideal[max(j - 1, 0):j + 2]) + TOL for j in range(256)]
    for d24 in list(range(BOUND_TOP)) + [0x7fffff, 0xffffff]:
        j = depth_alpha(gs_z(d24, zr))
        a = pica_alpha(p, d24)
        if not lo[j] <= a <= hi[j]:
            return ("  bound FAIL d24 %x index %d alpha %d palette %d .. %d"
                    % (d24, j, a, lo[j] + TOL, hi[j] - TOL))
    return None


# ================================================================ the model


class Model(object):
    def __init__(self):
        self.out = []
        self.e = retail_model.RetailEmu(ieee=True)
        self.sc = None
        self.cur = 0
        self.band_of = {}
        self.attached = {}
        e = self.e
        e.stub(E_GET_VIEW, self.get_view)
        e.stub(BMEMSET, self.memset)
        e.stub(ATTACH_IMAGE, lambda em: None)
        e.stub(DMA_ADD1, self.dma_add1)
        e.hook(CREATE, self.create_entry)
        e.hook(BAND_PC, self.band_hook)

    def emit(self, s):
        self.out.append(s)

    def arg(self, i):
        return self.e.reg[4 + i] & M32

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        for i in range(4):
            if a == FOCUS_PAL + 1024 * i:
                return "focus%d" % i
        if a == PAL:
            return "pal"
        return "x"

    # ---- the stubs and hooks -----------------------------------------------

    def get_view(self, em):
        return (VIEWS + 128 * s32(self.arg(0))) & M32

    def memset(self, em):
        a, v, n = self.arg(0), self.arg(1), self.arg(2)
        em.write(a, bytes([v & 0xff]) * n)

    def create_entry(self, em):
        self.cur = self.arg(0)
        self.band_of[self.cur] = None

    def band_hook(self, em):
        self.band_of[self.cur] = (s32(em.reg[8]), s32(em.reg[9]))

    def dma_add1(self, em):
        ra = em.reg[31] & M32
        if ra == BLUR_ADD_RA:
            self.emit("  blur")
            return
        if ra != VIEW_ADD_RA:
            return
        vid = s32(em.reg[30])
        band = self.band_of.get(VIEWS + 128 * vid)
        pal = self.label(FOCUS_PAL + 1024 * (vid - 1))
        if band is None:
            self.emit("  attach view %d %s noband" % (vid, pal))
        else:
            self.emit("  attach view %d %s band %d %d"
                      % (vid, pal, band[0], band[1]))
        self.attached[vid] = band

    # ---- the dumps ---------------------------------------------------------

    def palette(self, a):
        return [self.e.u32(a + 4 * k) for k in range(256)]

    def dump_palette(self, name, a):
        self.emit("  %s %s" % (name, " ".join(
            "%x" % w for w in self.palette(a))))

    def plan_op(self, vid, check):
        sc = self.sc
        pal = self.palette(FOCUS_PAL + 1024 * (vid - 1))
        p = plan(pal, self.attached.get(vid), bf(sc.amin), bf(sc.amax),
                 sc.length)
        self.emit("  plan %d%s" % (len(p), "".join(
            " " + s.text(at) for at, s in p)))
        self.emit("  alphas " + " ".join(
            "%x" % pica_alpha(p, d) for d in D24S))
        if check:
            self.emit(bound(p, pal, sc.zr) or "  bound ok")

    # ---- the scenario ------------------------------------------------------

    def reset(self, sc):
        e = self.e
        e.put32(DRAW, sc.draw & M32)
        e.put32(PRINT, sc.prnt & M32)
        e.put32(AMIN, sc.amin)
        e.put32(AMAX, sc.amax)
        e.put32(FOCAL, sc.focal)
        e.put32(DOF, sc.dof)
        e.put32(LEN, sc.length & M32)
        e.put32(FIRST, sc.first)
        e.put32(ZR1_MIN, sc.zr[0])
        e.put32(ZR1_MAX, sc.zr[1])
        e.write(FMEM, bytes(FMEM_SIZE))
        e.put32(FMEM_PTR, FMEM)
        e.put32(FMEM_END, FMEM + FMEM_SIZE)
        e.put32(FMEM_FAIL, 0)
        e.put32(FMEM_WANT, 0)
        e.write(VIEWS, bytes(128 * 10))
        e.write(RTS, bytes(256 * 10))
        e.write(CAMS, bytes(512 * 10))
        for i, (a, n, f, fo, d) in enumerate(sc.views):
            v = VIEWS + 128 * i
            e.put32(v, i)
            e.mem[v + 4] = a & 0xff
            e.put32(v + 12, fb(n))
            e.put32(v + 16, fb(f))
            e.put32(v + 48, RTS + 256 * i)
            e.put32(v + 56, CAMS + 512 * i)
            e.put32(CAMS + 512 * i + 116, fb(fo))
            e.put32(CAMS + 512 * i + 120, fb(d))
        for n in range(4):
            for k in range(256):
                e.put32(FOCUS_PAL + 1024 * n + 4 * k,
                        0xde000000 | n << 16 | k)
        for k in range(256):
            e.put32(PAL + 4 * k, 0xdead0000 + k)
        self.band_of = {}
        self.attached = {}

    def op(self, o):
        e = self.e
        self.emit(" %s" % o)
        if o == "A":
            self.emit("  -> %d" % e.call(ATTACH, CHAIN, *ATTACH_ARGS,
                                         limit=2000000))
            for n in range(4):
                self.dump_palette("focus%d" % n, FOCUS_PAL + 1024 * n)
        elif o == "Cn":
            self.emit("  -> %d" % e.call(CREATE, 0, PAL, limit=1000000))
            self.dump_palette("pal", PAL)
        elif o.startswith("Cp"):
            self.emit("  -> %d" % e.call(CREATE, VIEWS + 128 * int(o[2:]), 0,
                                         limit=1000000))
        elif o.startswith("C"):
            self.emit("  -> %d" % e.call(CREATE, VIEWS + 128 * int(o[1:]),
                                         PAL, limit=1000000))
            self.dump_palette("pal", PAL)
        elif o[0] in "PQ":
            self.plan_op(int(o[1:]), o[0] == "P")
        elif o == "G":
            parts = []
            for i in GET_IDS:
                e.put32(TMP_VIEW, i & M32)
                parts.append(self.label(e.call(GET_PALETTE, TMP_VIEW,
                                               limit=100)))
            self.emit("  get " + " ".join(parts))
        elif o == "H":
            self.emit("  s2p " + " ".join(self.s2p(z) for z in S2P_ZS))
            self.emit("  p2s " + " ".join(self.p2s(i) for i in P2S_IS))
            self.emit("  s2v " + " ".join(self.s2v(a) for a in S2V_ARGS))
        elif o == "B":
            self.emit("  byte " + " ".join(
                "%d" % pica_byte(g) for g in PICA_GS))
        elif o == "g":
            self.emit("  globals print %d" % s32(e.u32(PRINT)))
        else:
            self.emit("  ?")

    def s2p(self, z):
        self.e.fpr[12] = z
        return "%x" % (self.e.call(S2P, limit=100) & M32)

    def p2s(self, i):
        self.e.call(P2S, i, limit=100)
        return "%08x" % self.e.fpr[0]

    def s2v(self, a):
        for r, v in zip((12, 13, 14), a):
            self.e.fpr[r] = v
        self.e.call(S2V, limit=100)
        return "%08x" % self.e.fpr[0]

    def run(self, scenarios):
        e = self.e
        self.emit("start draw %d print %d min %08x max %08x focal %08x "
                  "dof %08x blend %d samples %d len %d first %08x" % (
                      s32(e.u32(DRAW)), s32(e.u32(PRINT)), e.u32(AMIN),
                      e.u32(AMAX), e.u32(FOCAL), e.u32(DOF),
                      s32(e.u32(BLEND)), s32(e.u32(SAMPLES)),
                      s32(e.u32(LEN)), e.u32(FIRST)))
        self.emit("jitter " + " ".join(
            "%d,%d" % (s32(e.u32(JITTER + 8 * k)),
                       s32(e.u32(JITTER + 8 * k + 4))) for k in range(6)))
        for k, sc in enumerate(scenarios):
            self.sc = sc
            self.reset(sc)
            self.emit("scenario %d %s" % (k, sc.name))
            for o in sc.ops.split():
                self.op(o)
        return self.out


def model(scenarios):
    return Model().run(scenarios)


# ================================================================ the build


def build_harness(tmp, name="dof_test"):
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


def encode(scenarios):
    return NL.join(l for s in scenarios for l in s.lines()) + NL


diff = pcc.diff

# ============================================================ the mutations

E = EFC

MUTATIONS = [
    # GetFocusPalette and the helpers.
    ("fc-get-base", E, "(uint32_t)(view->ID - 1);",
     "(uint32_t)(view->ID - 2);"),
    ("fc-get-bound", E, "return n < 4 ? FocusPalettes[n] : NULL;",
     "return n < 3 ? FocusPalettes[n] : NULL;"),
    ("fc-s2p-shift", E, "bits_of(z) >> 12 & 0xffu", "bits_of(z) >> 11 & 0xffu"),
    ("fc-s2p-mask", E, "bits_of(z) >> 12 & 0xffu",
     "bits_of(z) >> 12 & 0x1ffu"),
    ("fc-p2s-mask", E, "(i & 0xffu) << 12", "(i & 0x1ffu) << 12"),
    ("fc-p2s-base", E, "bits_of(ZRanges[1].ZMin) |",
     "bits_of(ZRanges[1].ZMax) |"),
    ("fc-s2v-span", E, "float span = far - near;", "float span = near - far;"),
    ("fc-s2v-a", E, "(ZRanges[1].ZMax - ZRanges[1].ZMin) / span",
     "(ZRanges[1].ZMax + ZRanges[1].ZMin) / span"),
    ("fc-s2v-b", E, "(-ZRanges[1].ZMax * near + ZRanges[1].ZMin * far)",
     "(-ZRanges[1].ZMax * far + ZRanges[1].ZMin * near)"),
    ("fc-s2v-ret", E, "return a / (sz - b);", "return a / (sz + b);"),
    # CreateFocusPalette.
    ("fc-null-view", E, "if (view == NULL || palette == NULL) {",
     "if (palette == NULL) {"),
    ("fc-null-pal", E, "if (view == NULL || palette == NULL) {",
     "if (view == NULL) {"),
    ("fc-near-plane", E, "near  = view->NearZ;", "near  = view->FarZ;"),
    ("fc-cam-focal", E, "focal = cam->CurrentKey.FocalDistance;",
     "focal = cam->CurrentKey.DepthOfField;"),
    ("fc-d-order", E, "d[255 - k] = MapScreenZToViewZ",
     "d[k] = MapScreenZToViewZ"),
    ("fc-focal-override", E, "if (FocalDistance != 0.0f) {",
     "if (FocalDistance > 0.0f) {"),
    ("fc-dof-override", E, "if (DepthOfField != 0.0f) {",
     "if (DepthOfField == 0.0f) {"),
    ("fc-clear-and", E, "if (dof == 0.0f && focal == 0.0f) {",
     "if (dof == 0.0f || focal == 0.0f) {"),
    ("fc-clear-size", E, "memset(palette, 0, 256 * sizeof *palette);",
     "memset(palette, 0, 255 * sizeof *palette);"),
    ("fc-clear-ret", E,
     "memset(palette, 0, 256 * sizeof *palette);" + NL + "        return 0;",
     "memset(palette, 0, 256 * sizeof *palette);" + NL + "        return 1;"),
    ("fc-half", E, "half     = dof * 0.5f;", "half     = dof * 0.25f;"),
    ("fc-far-edge", E, "farEdge  = focal + half;", "farEdge  = focal + dof;"),
    ("fc-near-edge", E, "nearEdge = focal - half;", "nearEdge = focal;"),
    ("fc-first", E, "prev     = FocusFirstPrevious;", "prev     = 0.0f;"),
    ("fc-t0-init", E, "t0       = 0;", "t0       = 1;"),
    ("fc-t1-init", E, "t1       = 255;", "t1       = 254;"),
    ("fc-near-lt", E, "if (prev < nearEdge && nearEdge <= d[k]) {",
     "if (prev <= nearEdge && nearEdge <= d[k]) {"),
    ("fc-near-le", E, "if (prev < nearEdge && nearEdge <= d[k]) {",
     "if (prev < nearEdge && nearEdge < d[k]) {"),
    ("fc-far-lt", E, "if (prev < farEdge && farEdge <= d[k]) {",
     "if (prev <= farEdge && farEdge <= d[k]) {"),
    ("fc-far-le", E, "if (prev < farEdge && farEdge <= d[k]) {",
     "if (prev < farEdge && farEdge < d[k]) {"),
    ("fc-prev", E, "        prev = d[k];" + NL, ""),
    ("fc-maxc", E,
     "maxC = (uint32_t)ee_trunc_w(FocusAlphaMax) << 24 | 0x808080u;",
     "maxC = (uint32_t)ee_trunc_w(FocusAlphaMax) << 24 | 0x808000u;"),
    ("fc-minc", E,
     "minC = (uint32_t)ee_trunc_w(FocusAlphaMin) << 24 | 0x808080u;",
     "minC = (uint32_t)ee_trunc_w(FocusAlphaMin) << 23 | 0x808080u;"),
    ("fc-fill-t0", E, "k < t0 || t1 < k ? maxC : minC",
     "k <= t0 || t1 < k ? maxC : minC"),
    ("fc-fill-t1", E, "k < t0 || t1 < k ? maxC : minC",
     "k < t0 || t1 <= k ? maxC : minC"),
    ("fc-near-ramp-start", E,
     "for (a = 1; a < len; a++) {" + NL
     + "        if ((uint32_t)(t0 - a) < 256u) {",
     "for (a = 0; a < len; a++) {" + NL
     + "        if ((uint32_t)(t0 - a) < 256u) {"),
    ("fc-near-ramp-end", E,
     "for (a = 1; a < len; a++) {" + NL
     + "        if ((uint32_t)(t0 - a) < 256u) {",
     "for (a = 1; a <= len; a++) {" + NL
     + "        if ((uint32_t)(t0 - a) < 256u) {"),
    ("fc-near-ramp-bound", E, "if ((uint32_t)(t0 - a) < 256u) {",
     "if ((uint32_t)(t0 - a) < 128u) {"),
    ("fc-near-ramp-index", E, "lin[255 - (t0 - a)]", "lin[254 - (t0 - a)]"),
    ("fc-far-ramp-end", E,
     "for (a = 1; a < len; a++) {" + NL
     + "        if ((uint32_t)(t1 + a) < 256u) {",
     "for (a = 1; a < len - 1; a++) {" + NL
     + "        if ((uint32_t)(t1 + a) < 256u) {"),
    ("fc-far-ramp-bound", E, "if ((uint32_t)(t1 + a) < 256u) {",
     "if ((uint32_t)(t1 + a) < 255u) {"),
    ("fc-far-ramp-index", E, "lin[255 - (t1 + a)]", "lin[256 - (t1 + a)]"),
    ("fc-ramp-step", E, "(float)a / (float)len * range",
     "(float)(a + 1) / (float)len * range"),
    ("fc-ramp-min", E, "float v = FocusAlphaMin + ", "float v = FocusAlphaMax - "),
    ("fc-ramp-bits", E, "return (uint32_t)ee_trunc_w(v) << 24 | 0x808080u;",
     "return (uint32_t)ee_trunc_w(v + 0.5f) << 24 | 0x808080u;"),
    ("fc-range", E, "range = FocusAlphaMax - FocusAlphaMin;",
     "range = FocusAlphaMax;"),
    ("fc-print-test", E, "if (FocusPrintPalette) {", "if (!FocusPrintPalette) {"),
    ("fc-print-reset", E, "FocusPrintPalette = 0;", "(void)0;"),
    ("fc-remap", E, "RemapLinearIntoClut8(palette, lin);",
     "memcpy(palette, lin, sizeof lin);"),
    ("fc-band-near", E, "band->Near = t0;", "band->Near = t1;"),
    ("fc-band-far", E, "band->Far  = t1;", "band->Far  = 255 - t1;"),
    ("fc-create-ret", E,
     "    }" + NL + "    return 1;" + NL + "}" + NL + NL
     + "int CreateFocusPalette",
     "    }" + NL + "    return 2;" + NL + "}" + NL + NL
     + "int CreateFocusPalette"),
    # eAttachDepthOfField.
    ("fa-draw", E, "if (!DrawDepthOfField) {", "if (DrawDepthOfField != 1) {"),
    ("fa-first-ids", E,
     "came back." + NL + "    for (id = 1; id < 3; id++) {",
     "came back." + NL + "    for (id = 1; id < 2; id++) {"),
    ("fa-first-active", E,
     "        if (!view->Active) {" + NL + "            continue;" + NL
     + "        }" + NL + "        pal = GetFocusPalette(view);" + NL
     + "        if (pal == NULL) {" + NL + "            continue;" + NL
     + "        }" + NL + "        made",
     "        pal = GetFocusPalette(view);" + NL
     + "        if (pal == NULL) {" + NL + "            continue;" + NL
     + "        }" + NL + "        made"),
    ("fa-first-pal", E,
     "        if (pal == NULL) {" + NL + "            continue;" + NL
     + "        }" + NL + "        made",
     "        made"),
    ("fa-any", E, "    if (!any) {" + NL, "    if (0) {" + NL),
    ("fa-any-or", E, "any |= made[id - 1];", "any = made[id - 1];"),
    ("fa-second-ids", E,
     "the blur's." + NL + "    for (id = 1; id < 3; id++) {",
     "the blur's." + NL + "    for (id = 2; id < 3; id++) {"),
    ("fa-second-active", E,
     "        if (!view->Active) {" + NL + "            continue;" + NL
     + "        }" + NL + "        pal = GetFocusPalette(view);" + NL
     + "        if (pal == NULL) {" + NL + "            continue;" + NL
     + "        }" + NL + "        if (gEDofAttachFn",
     "        pal = GetFocusPalette(view);" + NL
     + "        if (pal == NULL) {" + NL + "            continue;" + NL
     + "        }" + NL + "        if (gEDofAttachFn"),
    ("fa-band", E, "made[id - 1] ? &band[id - 1] : NULL", "&band[id - 1]"),
    ("fa-blur", E, "        gEDofBlurFn();" + NL, ""),
    ("fa-ret", E, "        gEDofBlurFn();" + NL + "    }" + NL + "    return 1;",
     "        gEDofBlurFn();" + NL + "    }" + NL + "    return any + 1;"),
    # The PICA's side.
    ("pb-round", E, "(gsAlpha * 255u + 64u) / 128u", "(gsAlpha * 255u) / 128u"),
    ("pb-clamp", E, "gsAlpha >= 128u ? 255u", "gsAlpha > 128u ? 255u"),
    ("pl-entry", E, "return palette[efog_clut_index(j)] >> 24;",
     "return palette[j] >> 24;"),
    ("pl-allzero", E, "if (palette[j] >> 24 != 0) {",
     "if (palette[j] != 0) {"),
    ("pl-region0", E, "region_step(palette, band, 0, 127, 0, &step[0]);",
     "region_step(palette, band, 0, 127, 1, &step[0]);"),
    ("pl-region1", E, "region_step(palette, band, 128, 255, 128, &step[1]);",
     "region_step(palette, band, 128, 255, 127, &step[1]);"),
    ("pl-last", E, "constant_step(&step[2], entry_alpha(palette, 255));",
     "constant_step(&step[2], entry_alpha(palette, 254));"),
    ("pl-constancy", E, "if (j > hi || band == NULL) {",
     "if (j > hi - 1 || band == NULL) {"),
    ("pl-farb", E, "s->FarB  = (int16_t)(2 * (far - base));",
     "s->FarB  = (int16_t)(2 * (far - base) + 1);"),
    ("pl-nearb", E, "s->NearB = (int16_t)(2 * (near - base) + 1);",
     "s->NearB = (int16_t)(2 * (near - base));"),
    ("pl-far-index", E, "far      = 255 - band->Far;",
     "far      = 254 - band->Far;"),
    ("pl-near-index", E, "near     = 255 - band->Near;",
     "near     = 255 - band->Far;"),
    ("pl-both", E, "both   = s->FarB > 0 && s->NearB < 255;",
     "both   = s->FarB > 0 || s->NearB < 255;"),
    ("pl-stages", E, "stages = (both ? 3 : 1) + 1",
     "stages = (both ? 2 : 1) + 1"),
    ("pl-stages-interp", E,
     "stages = (both ? 3 : 1) + 1 + (s->Min != 0 || s->Max != 255);",
     "stages = (both ? 3 : 1) + 1;"),
    ("pl-quads-left", E,
     "step_scale(s, FocusRampLength, 6 - stages + both);",
     "step_scale(s, FocusRampLength, 6 - stages);"),
    ("pl-min", E,
     "efocus_pica_byte((uint32_t)ee_trunc_w(FocusAlphaMin) & 0xffu);",
     "efocus_pica_byte((uint32_t)ee_trunc_w(FocusAlphaMin + 0.5f) & 0xffu);"),
    ("pl-max", E,
     "efocus_pica_byte((uint32_t)ee_trunc_w(FocusAlphaMax) & 0xffu);",
     "efocus_pica_byte((uint32_t)ee_trunc_w(FocusAlphaMax) & 0x7fu);"),
    ("pl-merge", E,
     "&& same_step(&plan->Step[plan->Count - 1], &step[n])) {",
     "&& 0) {"),
    ("pl-same", E, "return !a->Ramp && !b->Ramp && a->Alpha == b->Alpha;",
     "return !a->Ramp && a->Alpha == b->Alpha;"),
    ("pl-at", E, "{ 0.0f, 1.0f / 256.0f, 2.0f / 256.0f }",
     "{ 0.0f, 1.0f / 255.0f, 2.0f / 256.0f }"),
    ("ps-f", E, "float f = len >= 1 ? 255.0f / (2.0f * (float)len) : 255.0f;",
     "float f = len >= 1 ? 255.0f / (float)len : 255.0f;"),
    ("ps-f-zero", E,
     "float f = len >= 1 ? 255.0f / (2.0f * (float)len) : 255.0f;",
     "float f = len >= 1 ? 255.0f / (2.0f * (float)len) : 127.5f;"),
    ("ps-quad-limit", E, "while (f > 8.0f && s->Quads < quadsLeft) {",
     "while (f > 8.0f && s->Quads <= quadsLeft) {"),
    ("ps-quad-factor", E, "f *= 0.25f;", "f *= 0.5f;"),
    ("ps-step", E, "    if (f > 8.0f) {" + NL + "        s->Quads++;" + NL
     + "        s->Times = 4;" + NL + "        s->K     = 0;" + NL
     + "        return;" + NL + "    }" + NL, ""),
    ("ps-step-quad", E, "        s->Quads++;" + NL + "        s->Times = 4;",
     "        s->Times = 4;"),
    ("ps-step-times", E, "        s->Times = 4;" + NL + "        s->K     = 0;",
     "        s->Times = 2;" + NL + "        s->K     = 0;"),
    ("ps-step-k", E, "s->K     = 0;", "s->K     = 255;"),
    ("ps-step-ret", E, "        s->K     = 0;" + NL + "        return;",
     "        s->K     = 0;"),
    ("ps-times", E, "s->Times = f > 4.0f ? 4 : f > 2.0f ? 2 : 1;",
     "s->Times = f > 4.0f ? 4 : 1;"),
    ("ps-k", E, "k        = f / (float)s->Times - 1.0f;",
     "k        = f / (float)s->Times;"),
    ("ps-small", E, "        s->Times = 0;", "        s->Times = 1;"),
    ("ps-k-round", E, "s->K = (uint8_t)ee_trunc_w(k * 255.0f + 0.5f);",
     "s->K = (uint8_t)ee_trunc_w(k * 255.0f);"),
    ("pa-b", E, "int32_t  b = (int32_t)(d24 >> 8 & 0xffu);",
     "int32_t  b = (int32_t)(d24 >> 9 & 0xffu);"),
    ("pa-far-term", E, "w += sat8(s->FarB - b);", "w += sat8(s->FarB - b - 1);"),
    ("pa-near-term", E, "if (s->NearB < 255) {", "if (s->NearB < 253) {"),
    ("pa-near-sum", E, "w += sat8(b - s->NearB);", "w += sat8(b - s->NearB + 1);"),
    ("pa-times", E, "s->Times ? s->Times : 1u", "s->Times ? s->Times : 2u"),
    ("pa-quads", E, "w = sat8((int32_t)w * 4);", "w = sat8((int32_t)w * 3);"),
    ("pa-madd", E, "x = sat8((int32_t)(w + w * s->K / 255u));",
     "x = sat8((int32_t)(w + w * s->K / 256u));"),
    ("pa-mul", E, "x = w * s->K / 255u;", "x = w * s->K / 256u;"),
    ("pa-lerp", E, "(s->Max * x + s->Min * (255u - x)) / 255u",
     "(s->Max * x + s->Min * (256u - x)) / 255u"),
    ("pa-region", E, "for (n = 1; n < plan->Count; n++) {",
     "for (n = 1; n < plan->Count - 1; n++) {"),
]

EQUIVALENT = {
    # The CSM1 swap keeps each 32 entries in place, so a region's values,
    # entry 0's, 128's and 255's are the same either way; those are all the
    # plan reads.
    "pl-entry",
    # At 128, (128 * 255 + 64) / 128 is 255 as well.
    "pb-clamp",
    # CreateFocusPalette returns 0 for a NULL palette before it reads or
    # writes anything, so calling it gives the same 0 as skipping it.
    "fa-first-pal",
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    base = model(sc)
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

    for m in todo:
        name, rel, before, after = m
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

    sc = script()
    lines = model(sc)
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
    print("%d scenarios, %d lines, %d differ" % (len(sc), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
