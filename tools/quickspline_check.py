#!/usr/bin/env python3
"""Cross-check 3DS Files/source/quickspline.c -- QuickSpline, the
Overhauser spline the track paths, the player's driving line and the belt
mover are built on -- against the image itself, run in mipsemu.

The model is the image: every QuickSpline method but DoSnapshot runs as
shipped, and so do bFMod, bMulMatrix's vector overload and bTransposeMatrix
beneath them. The harness runs the same op script on the port and prints
the same lines. Every float goes both ways as its bits.

**The heap.** bMalloc is stubbed in the model and hooked in the harness;
both log the request and label the block h0, h1, ... in order, and both log
a free by label. __builtin_vec_delete and __builtin_delete are both
`j bFree`, so both print as a free. The port allocates one vector more than
the image and clears the block (see quickspline.c); the harness logs its request
less that one vector, and the model's stub hands the image a block with
sixteen zeroed bytes past what it asked for, so that the one read past the
end the image can make -- a LOOP spline evaluated at exactly t = n -- lands
on the same zeros on both sides. The dump prints that slack vector for a
heap buffer, which is the port's promise checked against zeros.

**Labels, not pointers.** The two splines are s0 and s1, the two external
buffers e0 and e1, the basis matrices `basis`; a pointer inside one prints
as name+offset.

**Constants by address.** The EXTRAPOLATED range and the LINE epsilon come
out of the ELF at gp-27168, -27164 and -27160 and are printed against the
header's macros, so a typo there diffs.

Scenarios: the constants; the basis matrices before and after the first
spline, and the init flag's guard; both constructors, Init and
SetNumControlPoints over every end type, basis and count wrap; the endpoint
fixups for every type and count, with and without a Length; ClampParam over
a grid; the extrapolated control points around both ends; EvaluateSpline
over all three bases; GetPoint over every type and basis, the dirty flag,
the saturating floor and the one-past-the-end read; both closest-point
searches, ties included; FindClosestParam converging, stalling and running
out its 998 steps; CalibrateLength over every type and sample count; and
the destructor.

    python tools/quickspline_check.py
    python tools/quickspline_check.py --mutate [--only a,b]
    python tools/quickspline_check.py --dump out/quickspline
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import physicscar_check as pcc
from mipsemu import Emu, M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/quickspline_test.c"
QSC = "3DS Files/source/quickspline.c"
QSH = "3DS Files/source/quickspline.h"
SOURCES = [HARNESS, QSC,
           "3DS Files/source/bmem.c",
           "3DS Files/source/bmatrix.c",
           "3DS Files/source/bvector.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/replay.c", "3DS Files/source/p32.c",
           "3DS Files/source/bmathtab.c"]

HARNESS_TIMEOUT = 300

# ================================================================ the image

GP = 0x00328bf0
BASIS = 0x00314490
BASIS_DONE = GP - 16120
assert BASIS_DONE == 0x00324cf8

SPL = [0x01E00000, 0x01E00100]      # the two QuickSplines, 40 bytes each
EXT = [0x01E01000, 0x01E02000]      # two caller buffers, 256 vectors each
EXT_N = 256
OUT = 0x01E03000                    # results, up to four vectors
PT = 0x01E03100                     # the bVector3 a search is handed
SLACK = 16                          # the port's extra vector, in bytes
MAX_DUMP = 80                       # buffer entries a dump prints at most

SYM = dict(
    ctor="__11QuickSpline23QuickSplineEndPointType20QuickSplineBasisTypei",
    ctor_buf="__11QuickSpline23QuickSplineEndPointType20QuickSplineBasisType"
             "P8bVector4i",
    dtor="_$_11QuickSpline",
    init="Init__11QuickSpline23QuickSplineEndPointType20QuickSplineBasisType",
    setn="SetNumControlPoints__11QuickSplinei",
    fixup="FixupEndpoints__11QuickSpline",
    genex="GenerateExtrapolatedControlPoints__11QuickSplineP8bVector4i",
    eval="EvaluateSpline__11QuickSplineP8bVector4fiPC8bVector4",
    clamp="ClampParam__11QuickSplinef",
    getpoint="GetPoint__11QuickSplineP8bVector4fi",
    fccp="FindClosestControlPoint__11QuickSplineRC8bVector3i",
    fccp_all="FindClosestControlPoint__11QuickSplineRC8bVector3",
    fcp="FindClosestParam__11QuickSplineRC8bVector3ff",
    cal="CalibrateLength__11QuickSplinei",
    basis="InitBasisMatricies__Fv",
)

LOOP, LINE, EXTRAP = 0, 1, 2

# ---- the ops -----------------------------------------------------------------

(OP_TAG, OP_NEW, OP_NEWBUF, OP_DESTROY, OP_SETUP, OP_SETN, OP_POKE, OP_CP,
 OP_DUMP, OP_BASIS, OP_BASISFLAG, OP_BASISPOKE, OP_INITBASIS, OP_FIXUP,
 OP_CLAMP, OP_GENEX, OP_EVAL, OP_GETPOINT, OP_FCCP, OP_FCCPALL, OP_FCP,
 OP_CAL, OP_CONST) = range(23)

ARGS = {OP_TAG: 1, OP_NEW: 4, OP_NEWBUF: 4, OP_DESTROY: 2, OP_SETUP: 3,
        OP_SETN: 2, OP_POKE: 3, OP_CP: 6, OP_DUMP: 2, OP_BASIS: 0,
        OP_BASISFLAG: 1, OP_BASISPOKE: 4, OP_INITBASIS: 0, OP_FIXUP: 1,
        OP_CLAMP: 2, OP_GENEX: 2, OP_EVAL: 4, OP_GETPOINT: 3, OP_FCCP: 5,
        OP_FCCPALL: 4, OP_FCP: 6, OP_CAL: 2, OP_CONST: 0}

# The fields OP_POKE can set, at image offsets, with their widths. The last
# clears the buffer pointer; its value is ignored.
POKE = [("EndPointType", 0, 4), ("BasisType", 4, 4), ("MaxParam", 8, 4),
        ("MinParam", 12, 4), ("Length", 16, 4), ("ControlPointsDirty", 20, 1),
        ("BufferWasAllocated", 21, 1), ("MinControlPoints", 22, 1),
        ("MaxControlPoints", 24, 2), ("NumControlPoints", 26, 2),
        ("BufferNull", 28, 4)]
K = {n: i for i, (n, _, _) in enumerate(POKE)}


def fb(x):
    """A Python float's single-precision bits."""
    return struct.unpack("<I", struct.pack("<f", x))[0]


def bf(b):
    return struct.unpack("<f", struct.pack("<I", b & M32))[0]


def f32(x):
    return bf(fb(x))


class Script(object):
    def __init__(self):
        self.ops = []
        self.tags = []

    def op(self, code, *args):
        assert len(args) == ARGS[code], (code, args)
        self.ops.append((code,) + tuple(
            fb(a) if isinstance(a, float) else int(a) for a in args))

    def tag(self, s):
        self.tags.append(s)
        self.op(OP_TAG, len(self.tags) - 1)

    def encode(self):
        out = [len(self.tags)]
        for s in self.tags:
            b = s.encode("latin-1")
            out.append(len(b))
            out.extend(b)
        flat = []
        for o in self.ops:
            flat.extend(o)
        out.append(len(flat))
        out.extend(flat)
        return struct.pack("<%di" % len(out), *[s32(v & M32) for v in out])

    # ---- sugar -----------------------------------------------------------

    def poke(self, slot, name, v):
        self.op(OP_POKE, slot, K[name], v)

    def cp(self, slot, idx, v):
        self.op(OP_CP, slot, idx, *[float(c) for c in v])

    def fill(self, slot, lo, hi, vecs):
        """Every buffer entry from cp[lo] to cp[hi-1], from `vecs`."""
        for k, i in enumerate(range(lo, hi)):
            self.cp(slot, i, vecs[k % len(vecs)])

    def dump(self, slot, buf=1):
        self.op(OP_DUMP, slot, buf)


# ================================================================ the script


def rvec(rnd, r=100.0):
    return (rnd.uniform(-r, r), rnd.uniform(-r, r), rnd.uniform(-r, r),
            rnd.uniform(-r, r))


def rvecs(rnd, n, r=100.0):
    return [rvec(rnd, r) for _ in range(n)]


def circle(n, radius=50.0, z=0.0, wobble=0.0):
    pts = []
    for i in range(n):
        a = 2.0 * math.pi * i / n
        pts.append((radius * math.cos(a), radius * math.sin(a),
                    z + wobble * math.sin(3.0 * a), 0.0))
    return pts


def wiggle(n, step=20.0):
    """An open road: forward in x, weaving in y, a gentle climb in z."""
    return [(step * i, 15.0 * math.sin(0.9 * i), 0.5 * i, 0.0)
            for i in range(n)]


def scenario_constants(sc):
    sc.tag("constants")
    sc.op(OP_CONST)
    sc.tag("basis before any spline")
    sc.op(OP_BASIS)


def scenario_ctor(sc, rnd):
    sc.tag("ctor loop 8")
    sc.op(OP_NEW, 0, LOOP, 0, 8)
    sc.dump(0, 0)
    sc.tag("basis after the first spline")
    sc.op(OP_BASIS)

    # The guard: a poked matrix survives a second init; a cleared flag
    # rebuilds it.
    sc.tag("basis guard")
    sc.op(OP_BASISPOKE, 1, 2, 3, fb(123.5))
    sc.op(OP_INITBASIS)
    sc.op(OP_BASIS)
    sc.op(OP_BASISFLAG, 0)
    sc.op(OP_INITBASIS)
    sc.op(OP_BASIS)
    sc.op(OP_BASISPOKE, 0, 0, 0, fb(-9.0))
    sc.op(OP_BASISFLAG, 0)
    sc.op(OP_NEW, 1, EXTRAP, 0, 4)       # the constructor's tail call
    sc.op(OP_BASIS)
    sc.dump(1, 0)
    sc.op(OP_DESTROY, 1, 0)
    sc.op(OP_DESTROY, 0, 0)

    sc.tag("ctor every type and basis")
    for ept in (LOOP, LINE, EXTRAP, 3, -1):
        for basis in (0, 1, -2):
            sc.op(OP_NEW, 0, ept, basis, 5)
            sc.dump(0, 0)
            sc.op(OP_DESTROY, 0, 0)

    # The count is cut to sixteen bits before the size is worked out.
    sc.tag("ctor count wraps")
    for n in (0, 1, 3, 20, 65539, 65536 + 17):
        sc.op(OP_NEW, 0, EXTRAP, 0, n)
        sc.dump(0, 0)
        sc.op(OP_DESTROY, 0, 0)

    sc.tag("ctor with buffer")
    for ept, n in ((LOOP, 11), (LINE, 3), (EXTRAP, 7), (LOOP, 40)):
        sc.op(OP_NEWBUF, 1, ept, 0, n)
        sc.dump(1, 0)
    sc.op(OP_NEWBUF, 1, EXTRAP, 0, 2)    # n - 3 wraps to 65535
    sc.dump(1, 0)
    sc.op(OP_DESTROY, 1, 0)

    sc.tag("init over a live spline")
    sc.op(OP_NEW, 0, LINE, 0, 6)
    sc.fill(0, -1, 8, rvecs(rnd, 9))
    sc.op(OP_SETN, 0, 6)
    sc.poke(0, "Length", 77.25)
    sc.poke(0, "ControlPointsDirty", 0)
    sc.dump(0)
    for ept, basis in ((LOOP, 0), (EXTRAP, 1), (LINE, 0), (7, 0)):
        sc.op(OP_SETUP, 0, ept, basis)
        sc.dump(0, 0)
    sc.op(OP_DESTROY, 0, 0)


def scenario_setn(sc):
    sc.tag("set num control points")
    sc.op(OP_NEW, 0, LOOP, 0, 10)
    for ept in (LOOP, LINE, EXTRAP, 3, -4):
        sc.poke(0, "EndPointType", ept)
        for n in (0, 1, 2, 7, 10, 65535, 65536, 65536 + 5, -1, -65535):
            sc.poke(0, "MaxParam", 3.5)
            sc.poke(0, "MinParam", -1.25)
            sc.poke(0, "ControlPointsDirty", 0)
            sc.op(OP_SETN, 0, n)
            sc.dump(0, 0)
    sc.op(OP_DESTROY, 0, 0)


def scenario_fixup(sc, rnd):
    sc.tag("fixup")
    for ept in (LOOP, LINE, EXTRAP, 3):
        for n in (0, 1, 2, 3, 5, 9):
            for length in (0.0, -0.0, 40.0, -12.5):
                sc.op(OP_NEW, 0, ept, 0, 9)
                sc.fill(0, -1, 11, rvecs(rnd, 11))
                sc.op(OP_SETN, 0, n)
                sc.poke(0, "Length", length)
                sc.op(OP_FIXUP, 0)
                sc.dump(0)
                sc.op(OP_DESTROY, 0, 0)

    # Points that make the w lane's rounding visible: a Length far larger
    # than the ws, and ws far larger than the Length.
    sc.tag("fixup rounding")
    for ept in (LOOP, LINE, EXTRAP):
        sc.op(OP_NEW, 0, ept, 0, 4)
        sc.fill(0, -1, 6, [(0.1, 0.2, 0.3, 1e-3), (1e7, -3.3, 7.7, 1e8),
                           (0.7, 1e-5, -1e6, 3.14159), (5.5, 6.5, 7.5, 1e-7)])
        sc.op(OP_SETN, 0, 4)
        sc.poke(0, "Length", 16777217.0)
        sc.op(OP_FIXUP, 0)
        sc.dump(0)
        sc.poke(0, "Length", 3.0e-3)
        sc.op(OP_FIXUP, 0)
        sc.dump(0)
        sc.op(OP_DESTROY, 0, 0)


CLAMP_TS = [0.0, -0.0, 1e-7, -1e-7, -1e-6, 0.5, 0.999999, 1.0, 2.5, 3.0,
            3.9999998, 4.0, 4.0000005, 7.0, 7.9999995, 8.0, 8.5, 15.999,
            16.0, 100.25, -0.5, -1.0, -3.75, -8.0, -8.0000005, -1000.0,
            1e7, -1e7, 3.0e9, -3.0e9]


def scenario_clamp(sc):
    sc.tag("clamp")
    sc.op(OP_NEW, 0, LOOP, 0, 16)
    for ept in (LOOP, LINE, EXTRAP, 3):
        sc.poke(0, "EndPointType", ept)
        for n in (1, 2, 4, 8, 16):
            sc.op(OP_SETN, 0, n)
            for t in CLAMP_TS:
                sc.op(OP_CLAMP, 0, float(t))
    # A LINE range the header does not produce: MinParam above zero, and
    # MaxParam at a size where the epsilon is lost.
    sc.poke(0, "EndPointType", LINE)
    # The last pair puts MaxParam at the epsilon itself, so the upper bound
    # is +0.0 and a t of -0.0 tells min.s's `<` from a `<=`.
    for lo, hi in ((0.5, 3.0), (2.0, 1.0), (0.0, 1e7), (-4.0, 0.0),
                   (0.0, 1.0), (0.0, 1.00000001e-07)):
        sc.poke(0, "MinParam", lo)
        sc.poke(0, "MaxParam", hi)
        for t in (-5.0, -0.0, 0.0, 0.25, 0.5, 0.99999994, 1.0, 2.0, 3.0,
                  1e7, 9999999.0):
            sc.op(OP_CLAMP, 0, float(t))
    sc.op(OP_DESTROY, 0, 0)


def scenario_genex(sc, rnd):
    sc.tag("extrapolated control points")
    for n in (1, 2, 3, 5):
        sc.op(OP_NEW, 0, EXTRAP, 0, 6)
        sc.fill(0, -1, 8, rvecs(rnd, 8, 50.0))
        sc.op(OP_SETN, 0, n)
        sc.op(OP_FIXUP, 0)
        for start in range(-7, n + 4):
            sc.op(OP_GENEX, 0, start)
        # The wraps a saturated floor produces.
        for start in (2147483646, 2147483645, -2147483647, -2147483648,
                      2147483647):
            sc.op(OP_GENEX, 0, start)
        sc.op(OP_DESTROY, 0, 0)


def scenario_eval(sc, rnd):
    sc.tag("evaluate")
    sc.op(OP_NEW, 0, LOOP, 0, 8)
    sc.fill(0, -1, 10, rvecs(rnd, 10))
    sc.op(OP_SETN, 0, 8)
    for basis in (0, 1, 2):
        for t in (0.0, 1.0, 0.5, 0.25, 0.75, 0.1, 0.999, -0.5, 1.5, 2.0,
                  rnd.random(), rnd.random(), 1e-4, 3.3):
            for idx in (-1, 0, 3, 6):
                sc.op(OP_EVAL, 0, float(t), basis, idx)
    sc.op(OP_DESTROY, 0, 0)


GP_TS = [0.0, -0.0, 0.5, 1.0, 1.25, 2.999, 3.0, 3.5, 4.0, 4.75, 5.0, 6.5,
         7.0, 7.999, 8.0, 8.25, 9.0, -0.25, -1.0, -1.5, -3.0, -7.75, 12.5,
         -1e-6, -1e-7, 1e-7, 1e4, -1e4]


def scenario_getpoint(sc, rnd):
    sc.tag("getpoint empty")
    for ept in (LOOP, LINE, EXTRAP):
        sc.op(OP_NEW, 0, ept, 0, 4)
        sc.fill(0, -1, 6, rvecs(rnd, 6))
        sc.op(OP_SETN, 0, 0)
        sc.op(OP_GETPOINT, 0, 1.5, 0)
        sc.dump(0)
        sc.op(OP_DESTROY, 0, 0)

    sc.tag("getpoint")
    for ept in (LOOP, LINE, EXTRAP):
        for n, maxc in ((1, 3), (2, 4), (3, 3), (4, 8), (8, 9)):
            # A one-point LINE clamps t to -1e-7, floors it to segment -1
            # and reads cp[-2], before the block: nothing to agree on.
            if ept == LINE and n == 1:
                continue
            sc.op(OP_NEW, 0, ept, 0, maxc)
            sc.fill(0, -1, maxc + 2, rvecs(rnd, maxc + 3, 60.0))
            sc.op(OP_SETN, 0, n)
            sc.poke(0, "Length", float(n) * 17.0 if n > 2 else 0.0)
            for basis in (0, 1, 2):
                for t in GP_TS:
                    sc.op(OP_GETPOINT, 0, float(t), basis)
                for _ in range(6):
                    sc.op(OP_GETPOINT, 0, rnd.uniform(-2.0, n + 2.0), basis)
            sc.dump(0)
            sc.op(OP_DESTROY, 0, 0)

    # The dirty flag: a moved point is seen only once GetPoint has run the
    # fixups again, and a clean spline keeps its stale endpoints.
    sc.tag("getpoint dirty")
    sc.op(OP_NEW, 0, LOOP, 0, 6)
    sc.fill(0, -1, 8, circle(9))
    sc.op(OP_SETN, 0, 6)
    sc.op(OP_GETPOINT, 0, 5.5, 0)
    sc.dump(0)
    sc.cp(0, 0, (99.0, -99.0, 9.0, 0.5))
    sc.op(OP_GETPOINT, 0, 5.5, 0)
    sc.dump(0)
    sc.poke(0, "ControlPointsDirty", 1)
    sc.op(OP_GETPOINT, 0, 5.5, 0)
    sc.dump(0)
    sc.op(OP_DESTROY, 0, 0)

    # The one read past the end: t a hair below zero on a LOOP wraps to
    # exactly n, the segment starts at cp[n-1], and cp[n+2] is past the
    # image's block. At full capacity that is the slack vector.
    sc.tag("getpoint past the end")
    for maxc in (5, 6):
        sc.op(OP_NEW, 0, LOOP, 0, maxc)
        sc.fill(0, -1, maxc + 2, rvecs(rnd, maxc + 3, 30.0))
        sc.op(OP_SETN, 0, 5)
        for basis in (0, 1, 2):
            for t in (-1e-6, -3e-7, -1e-5, 5.0, 10.0 - 1e-6, -5.0000005):
                sc.op(OP_CLAMP, 0, float(t))
                sc.op(OP_GETPOINT, 0, float(t), basis)
        sc.dump(0)
        sc.op(OP_DESTROY, 0, 0)

    # A floor that saturates: EXTRAPOLATED passes t through, cvt.w.s pins
    # it at INT_MAX or INT_MIN, and the extrapolation's index sums wrap.
    sc.tag("getpoint saturated")
    sc.op(OP_NEW, 0, EXTRAP, 0, 4)
    sc.fill(0, -1, 6, [(0.0, 0.0, 0.0, 0.0), (1.0, 2.0, 0.5, 1.0),
                       (2.0, 3.0, 1.0, 2.0), (4.0, 3.5, 1.0, 3.0),
                       (5.0, 5.0, 0.0, 4.0), (1.0, 1.0, 1.0, 1.0)])
    sc.op(OP_SETN, 0, 4)
    for t in (3.0e9, -3.0e9, 2147483648.0, -2147483648.0, -2147483904.0,
              1e10, -1e10, 2147483520.0, -2147483520.0, 9999999.0,
              -9999999.0):
        for basis in (0, 1, 2):
            sc.op(OP_GETPOINT, 0, float(t), basis)
    sc.op(OP_DESTROY, 0, 0)

    sc.tag("getpoint on a caller's buffer")
    sc.op(OP_NEWBUF, 1, LOOP, 0, 9)
    sc.fill(1, -1, 8, circle(9, 30.0, 2.0, 1.5))
    sc.op(OP_SETN, 1, 6)
    for t in (0.0, 0.5, 2.25, 5.9, -0.1):
        sc.op(OP_GETPOINT, 1, float(t), 0)
    sc.dump(1)


def scenario_closest_point(sc, rnd):
    sc.tag("closest control point")
    pts = rvecs(rnd, 12, 80.0)
    sc.op(OP_NEW, 0, EXTRAP, 0, 12)
    sc.fill(0, -1, 14, [pts[0]] + pts + [pts[1]])
    for n in (1, 2, 5, 12):
        sc.op(OP_SETN, 0, n)
        for _ in range(12):
            p = rvec(rnd, 90.0)
            sc.op(OP_FCCPALL, 0, p[0], p[1], p[2])
            for start in range(n):
                sc.op(OP_FCCP, 0, p[0], p[1], p[2], start)
    sc.op(OP_SETN, 0, 0)
    sc.op(OP_FCCPALL, 0, 1.0, 2.0, 3.0)

    # A road of points, so the walks go somewhere: from each start, to a
    # point near each control point.
    sc.tag("closest control point walks")
    road = wiggle(12)
    sc.fill(0, 0, 12, road)
    sc.op(OP_SETN, 0, 12)
    for k in range(12):
        p = (road[k][0] + 3.0, road[k][1] - 2.0, road[k][2] + 1.0)
        sc.op(OP_FCCPALL, 0, *p)
        for start in (0, 3, 6, 11):
            sc.op(OP_FCCP, 0, p[0], p[1], p[2], start)
    # A dip and a rise either side of the start: the backward walk runs
    # against the distance the forward walk left behind.
    for p in ((40.0, 0.0, 0.0), (150.0, 30.0, 0.0), (-50.0, 0.0, 0.0),
              (400.0, 0.0, 0.0)):
        for start in range(12):
            sc.op(OP_FCCP, 0, p[0], p[1], p[2], start)

    # Ties. Forward and backward both stop on an equal distance; the
    # exhaustive search keeps the first of equals.
    sc.tag("closest control point ties")
    ring = [(10.0, 0.0, 0.0, 0.0), (0.0, 10.0, 0.0, 0.0),
            (-10.0, 0.0, 0.0, 0.0), (0.0, -10.0, 0.0, 0.0),
            (10.0, 0.0, 0.0, 0.0), (0.0, 0.0, 10.0, 0.0),
            (0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0)]
    sc.fill(0, 0, 8, ring)
    sc.op(OP_SETN, 0, 8)
    for p in ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (5.0, 5.0, 0.0),
              (-5.0, 5.0, 0.0), (0.0, 0.0, 5.0), (3.0, -3.0, 3.0)):
        sc.op(OP_FCCPALL, 0, *p)
        for start in range(8):
            sc.op(OP_FCCP, 0, p[0], p[1], p[2], start)

    # The order the squares are summed in. (a, b, c) and (c, b, a) are the
    # same distance in real arithmetic; summed x + y then + z, the first
    # rounds one ulp nearer, and summed the other way round, the second.
    sc.tag("closest control point summation order")
    a, b, c = 13.927599906921387, 9.12425422668457, 6.968796253204346
    sc.fill(0, 0, 3, [(a, b, c, 0.0), (c, b, a, 0.0), (a, b, c, 0.0)])
    sc.op(OP_SETN, 0, 2)
    sc.op(OP_FCCPALL, 0, 0.0, 0.0, 0.0)
    sc.op(OP_FCCP, 0, 0.0, 0.0, 0.0, 0)
    sc.op(OP_FCCP, 0, 0.0, 0.0, 0.0, 1)
    sc.op(OP_DESTROY, 0, 0)


def scenario_closest_param(sc, rnd):
    sc.tag("closest param loop")
    sc.op(OP_NEW, 0, LOOP, 0, 8)
    sc.fill(0, -1, 10, circle(8, 50.0, 1.0, 4.0))
    sc.op(OP_SETN, 0, 8)
    for _ in range(14):
        a = rnd.uniform(0.0, 2.0 * math.pi)
        r = rnd.uniform(30.0, 70.0)
        p = (r * math.cos(a), r * math.sin(a), rnd.uniform(-3.0, 3.0))
        guess = rnd.choice((0.0, a / (2.0 * math.pi) * 8.0,
                            rnd.uniform(-2.0, 10.0)))
        tol = rnd.choice((0.01, 0.001, 1e-4, 0.5))
        sc.op(OP_FCP, 0, p[0], p[1], p[2], float(guess), float(tol))
    sc.dump(0, 0)

    # A tolerance nothing meets: the search runs its 998 steps, or stops on
    # a secant slope of exactly zero.
    sc.tag("closest param exhausts")
    for p, guess in (((49.0, 3.0, 0.5), 0.2), ((0.0, 55.0, 1.0), 1.7),
                     ((0.0, 0.0, 0.0), 3.0)):
        sc.op(OP_FCP, 0, p[0], p[1], p[2], float(guess), 0.0)
    sc.op(OP_DESTROY, 0, 0)

    sc.tag("closest param extrapolated")
    road = wiggle(6)
    sc.op(OP_NEW, 0, EXTRAP, 0, 6)
    sc.fill(0, -1, 8, [road[0]] + road + [road[-1]])
    sc.op(OP_SETN, 0, 6)
    for _ in range(12):
        x = rnd.uniform(-60.0, 160.0)
        p = (x, rnd.uniform(-25.0, 25.0), rnd.uniform(-2.0, 4.0))
        guess = rnd.choice((0.0, x / 20.0, 2.5, -1.0, 7.0))
        tol = rnd.choice((0.01, 1e-3, 1e-5))
        sc.op(OP_FCP, 0, p[0], p[1], p[2], float(guess), float(tol))

    sc.tag("closest param line")
    sc.poke(0, "EndPointType", LINE)
    sc.op(OP_SETN, 0, 6)
    for p, guess in (((-30.0, 0.0, 0.0), 0.5), ((130.0, 5.0, 2.0), 4.0),
                     ((55.0, -9.0, 1.0), 2.0), ((200.0, 0.0, 0.0), 4.9)):
        sc.op(OP_FCP, 0, p[0], p[1], p[2], float(guess), 1e-3)

    # A tangent of zero: every point the same, so the first step returns
    # the guess untouched. And no points at all.
    sc.tag("closest param degenerate")
    sc.poke(0, "EndPointType", EXTRAP)
    sc.fill(0, -1, 8, [(4.0, 4.0, 4.0, 0.0)])
    sc.op(OP_SETN, 0, 6)
    sc.op(OP_FCP, 0, 1.0, 2.0, 3.0, 2.5, 1e-3)
    sc.op(OP_FCP, 0, 1.0, 2.0, 3.0, -7.25, 1e-3)
    sc.op(OP_SETN, 0, 0)
    sc.op(OP_FCP, 0, 1.0, 2.0, 3.0, 2.5, 1e-3)
    sc.dump(0, 0)
    sc.op(OP_DESTROY, 0, 0)

    # A straight road of unit steps, where position and tangent at a whole
    # t are exact. Far down the extrapolated end, every step is clamped to
    # 1 and never changes sign, so t is the number of steps taken when the
    # 998 run out. Half a unit off with a tolerance of exactly 0.5 tells
    # the `<` from a `<=`.
    sc.tag("closest param counted")
    sc.op(OP_NEW, 0, EXTRAP, 0, 6)
    sc.fill(0, -1, 7, [(float(i), 0.0, 0.0, 0.0) for i in range(-1, 6)])
    sc.op(OP_SETN, 0, 6)
    sc.op(OP_FCP, 0, 5000.0, 0.0, 0.0, 0.0, 1e-3)
    sc.op(OP_FCP, 0, -5000.0, 0.0, 0.0, 3.0, 1e-3)
    sc.op(OP_FCP, 0, 2.5, 0.0, 0.0, 2.0, 0.5)
    sc.op(OP_FCP, 0, 2.5, 0.0, 0.0, 2.0, 0.25)
    sc.op(OP_DESTROY, 0, 0)


def scenario_calibrate(sc, rnd):
    sc.tag("calibrate")
    for ept in (LOOP, LINE, EXTRAP):
        for n in (0, 1, 2, 3, 6):
            for samples in (0, 1, 4, 16):
                shape = circle(max(n, 1), 40.0, 0.0, 3.0) if ept == LOOP \
                    else wiggle(max(n, 1))
                sc.op(OP_NEW, 0, ept, 0, 7)
                sc.fill(0, -1, 9, [shape[0]] + shape + rvecs(rnd, 4))
                sc.op(OP_SETN, 0, n)
                sc.op(OP_CAL, 0, samples)
                sc.dump(0)
                sc.op(OP_DESTROY, 0, 0)

    # A Length already there: the fixups each segment reruns use it, not
    # the one being measured -- visible in the extra points' w.
    sc.tag("calibrate over a length")
    for ept in (LOOP, LINE, EXTRAP):
        sc.op(OP_NEW, 0, ept, 0, 5)
        sc.fill(0, -1, 7, rvecs(rnd, 7, 40.0))
        sc.op(OP_SETN, 0, 5)
        sc.poke(0, "Length", 1000.0)
        sc.op(OP_CAL, 0, 3)
        sc.dump(0)
        sc.op(OP_CAL, 0, 3)
        sc.dump(0)
        sc.op(OP_DESTROY, 0, 0)

    # A LOOP whose MaxParam was poked short: segments at or past it are
    # skipped, but their w is still written.
    sc.tag("calibrate short range")
    sc.op(OP_NEW, 0, LOOP, 0, 6)
    sc.fill(0, -1, 8, circle(8))
    sc.op(OP_SETN, 0, 6)
    sc.poke(0, "MaxParam", 3.5)
    sc.op(OP_CAL, 0, 5)
    sc.dump(0)
    sc.op(OP_DESTROY, 0, 0)

    # Sample counts whose j / samples is not j * (1 / samples) in float --
    # 7 at j = 3 and 6, 12 at 5, 7 and 10 -- and then FindClosestParam on
    # the calibrated spline, whose tangent now has a w: the speed is
    # xyz only.
    sc.tag("calibrate odd samples")
    for samples in (7, 12):
        sc.op(OP_NEW, 0, LOOP, 0, 6)
        sc.fill(0, -1, 8, circle(8, 45.0, 0.0, 5.0))
        sc.op(OP_SETN, 0, 6)
        sc.op(OP_CAL, 0, samples)
        sc.dump(0)
        for p, guess in (((40.0, 10.0, 1.0), 0.5), ((-20.0, 38.0, 0.0), 2.2),
                         ((5.0, -44.0, -2.0), 4.6)):
            sc.op(OP_FCP, 0, p[0], p[1], p[2], float(guess), 1e-4)
        sc.op(OP_DESTROY, 0, 0)


def scenario_teardown(sc):
    sc.tag("destroy")
    for flags in (0, 1, 2, 3):
        sc.op(OP_NEW, 0, LOOP, 0, 3)
        sc.op(OP_DESTROY, 0, flags)
    sc.op(OP_NEWBUF, 1, LINE, 0, 6)
    sc.op(OP_DESTROY, 1, 1)
    sc.op(OP_NEWBUF, 1, LINE, 0, 6)
    sc.poke(1, "BufferWasAllocated", 1)
    sc.op(OP_DESTROY, 1, 0)
    sc.op(OP_NEW, 0, LOOP, 0, 3)
    sc.poke(0, "BufferNull", 0)
    sc.op(OP_DESTROY, 0, 1)
    sc.op(OP_NEW, 0, LOOP, 0, 3)
    sc.poke(0, "BufferWasAllocated", 0)
    sc.op(OP_DESTROY, 0, 1)


def script():
    rnd = random.Random(0x5B11E)
    sc = Script()
    scenario_constants(sc)
    scenario_ctor(sc, rnd)
    scenario_setn(sc)
    scenario_fixup(sc, rnd)
    scenario_clamp(sc)
    scenario_genex(sc, rnd)
    scenario_eval(sc, rnd)
    scenario_getpoint(sc, rnd)
    scenario_closest_point(sc, rnd)
    scenario_closest_param(sc, rnd)
    scenario_calibrate(sc, rnd)
    scenario_teardown(sc)
    return sc


# ================================================================ the model


class Model(object):
    def __init__(self, sc):
        self.sc = sc
        self.out = []
        e = self.e = Emu(ieee=True)
        e.stub_bware()
        self.fn = {k: e.addr_of(v) for k, v in SYM.items()}
        self.heap = []                  # (addr, size, label)
        e.mem[SPL[0]:SPL[0] + 0x200] = bytes([0x55]) * 0x200
        self.stubs()

    def emit(self, s):
        self.out.append(s)

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        regions = [(SPL[0], 40, "s0"), (SPL[1], 40, "s1"),
                   (EXT[0], EXT_N * 16, "e0"), (EXT[1], EXT_N * 16, "e1"),
                   (BASIS, 192, "basis")]
        regions += [(p, n + SLACK, name) for p, n, name in self.heap]
        for base, size, name in regions:
            if base <= a < base + size:
                return name if a == base else "%s+%d" % (name, a - base)
        return "?"

    def stubs(self):
        e = self.e

        def arg(i):
            return e.reg[4 + i] & M32

        def cstr(p):
            end = e.mem.index(b"\0", p)
            return e.mem[p:end].decode("latin-1")

        def malloc(em):
            size = s32(arg(0))
            p = e.alloc(size + SLACK, align=16)
            e.mem[p:p + size + SLACK] = bytes(size + SLACK)
            name = "h%d" % len(self.heap)
            self.heap.append((p, size, name))
            self.emit("  alloc %s size %d name %s flags %d pool %d"
                      % (name, size, cstr(arg(1)), s32(arg(2)),
                         s32(arg(3))))
            return p

        def free(em):
            self.emit("  free %s" % self.label(arg(0)))

        e.stub("bMalloc__FiPCcii", malloc)
        e.stub("__builtin_vec_delete", free)
        e.stub("__builtin_delete", free)

    # ---- the prints ------------------------------------------------------

    def vec(self, a):
        e = self.e
        return "%08x %08x %08x %08x" % (e.u32(a), e.u32(a + 4),
                                        e.u32(a + 8), e.u32(a + 12))

    def dump(self, slot, buf):
        e = self.e
        s = SPL[slot]
        sb = lambda a: (e.u8(a) ^ 0x80) - 0x80
        maxc = e.u16(s + 24)
        self.emit("s%d ept %d bt %d max %08x min %08x len %08x dirty %d "
                  "alloc %d minc %d maxc %d n %d buf %s cp %s basis %s"
                  % (slot, s32(e.u32(s)), s32(e.u32(s + 4)), e.u32(s + 8),
                     e.u32(s + 12), e.u32(s + 16), sb(s + 20), sb(s + 21),
                     sb(s + 22), maxc, e.u16(s + 26),
                     self.label(e.u32(s + 28)), self.label(e.u32(s + 32)),
                     self.label(e.u32(s + 36))))
        if not buf:
            return
        b = e.u32(s + 28)
        for i in range(min(maxc + 3, MAX_DUMP)):
            self.emit("  b%d %s" % (i, self.vec(b + 16 * i)))
        if self.label(b).startswith("h"):
            self.emit("  slack %s" % self.vec(b + 16 * (maxc + 3)))

    def basis(self):
        e = self.e
        self.emit("basis done %d" % s32(e.u32(BASIS_DONE)))
        for k in range(3):
            for r in range(4):
                self.emit("  m%d r%d %s" % (k, r,
                                            self.vec(BASIS + 64 * k + 16 * r)))

    def put_pt(self, x, y, z):
        e = self.e
        e.put32(PT, x)
        e.put32(PT + 4, y)
        e.put32(PT + 8, z)
        e.put32(PT + 12, 0)

    # ---- the run ---------------------------------------------------------

    def run(self):
        sc, e, emit, fn = self.sc, self.e, self.emit, self.fn
        for o in sc.ops:
            code, a = o[0], o[1:]
            if code == OP_TAG:
                emit("[%s]" % sc.tags[a[0]])
            elif code == OP_NEW:
                slot, ept, basis, n = a
                emit("new s%d ept %d bt %d n %d" % (slot, ept, basis, n))
                e.call(fn["ctor"], SPL[slot], ept, basis, n)
            elif code == OP_NEWBUF:
                slot, ept, basis, n = a
                emit("newbuf s%d ept %d bt %d n %d" % (slot, ept, basis, n))
                e.call(fn["ctor_buf"], SPL[slot], ept, basis, EXT[slot], n)
            elif code == OP_DESTROY:
                emit("destroy s%d flags %d" % (a[0], a[1]))
                e.call(fn["dtor"], SPL[a[0]], a[1])
            elif code == OP_SETUP:
                slot, ept, basis = a
                emit("setup s%d ept %d bt %d" % (slot, ept, basis))
                e.call(fn["init"], SPL[slot], ept, basis)
            elif code == OP_SETN:
                e.call(fn["setn"], SPL[a[0]], a[1])
            elif code == OP_POKE:
                slot, k, v = a
                _, off, w = POKE[k]
                addr = SPL[slot] + off
                if POKE[k][0] == "BufferNull":
                    e.put32(addr, 0)
                elif w == 4:
                    e.put32(addr, v)
                elif w == 2:
                    struct.pack_into("<H", e.mem, addr, v & 0xFFFF)
                else:
                    e.mem[addr] = v & 0xFF
            elif code == OP_CP:
                slot, idx = a[0], a[1]
                p = (e.u32(SPL[slot] + 32) + 16 * idx) & M32
                for j in range(4):
                    e.put32(p + 4 * j, a[2 + j])
            elif code == OP_DUMP:
                self.dump(a[0], a[1])
            elif code == OP_BASIS:
                self.basis()
            elif code == OP_BASISFLAG:
                e.put32(BASIS_DONE, a[0])
            elif code == OP_BASISPOKE:
                k, r, lane, v = a
                e.put32(BASIS + 64 * k + 16 * r + 4 * lane, v)
            elif code == OP_INITBASIS:
                e.call(fn["basis"])
            elif code == OP_FIXUP:
                e.call(fn["fixup"], SPL[a[0]])
            elif code == OP_CLAMP:
                e.fpr[12] = a[1] & M32
                e.call(fn["clamp"], SPL[a[0]])
                emit("clamp %08x -> %08x" % (a[1] & M32, e.fpr[0]))
            elif code == OP_GENEX:
                e.call(fn["genex"], SPL[a[0]], OUT, a[1])
                emit("genex %d" % a[1])
                for i in range(4):
                    emit("  %s" % self.vec(OUT + 16 * i))
            elif code == OP_EVAL:
                slot, t, basis, idx = a
                cp = (e.u32(SPL[slot] + 32) + 16 * idx) & M32
                e.fpr[12] = t & M32
                e.call(fn["eval"], SPL[slot], OUT, basis, cp)
                emit("eval %08x b%d cp%d -> %s"
                     % (t & M32, basis, idx, self.vec(OUT)))
            elif code == OP_GETPOINT:
                slot, t, basis = a
                e.fpr[12] = t & M32
                r = e.call(fn["getpoint"], SPL[slot], OUT, basis)
                emit("point %08x b%d -> %s ret %s"
                     % (t & M32, basis, self.vec(OUT), self.label(r)))
            elif code == OP_FCCP:
                slot, x, y, z, start = a
                self.put_pt(x, y, z)
                r = e.call(fn["fccp"], SPL[slot], PT, start)
                emit("fccp %08x %08x %08x from %d -> %d"
                     % (x & M32, y & M32, z & M32, start, r))
            elif code == OP_FCCPALL:
                slot, x, y, z = a
                self.put_pt(x, y, z)
                r = e.call(fn["fccp_all"], SPL[slot], PT)
                emit("fccp %08x %08x %08x -> %d"
                     % (x & M32, y & M32, z & M32, r))
            elif code == OP_FCP:
                slot, x, y, z, guess, tol = a
                self.put_pt(x, y, z)
                e.fpr[12] = guess & M32
                e.fpr[13] = tol & M32
                e.call(fn["fcp"], SPL[slot], PT)
                emit("fcp %08x %08x %08x g %08x tol %08x -> %08x"
                     % (x & M32, y & M32, z & M32, guess & M32, tol & M32,
                        e.fpr[0]))
            elif code == OP_CAL:
                emit("calibrate s%d samples %d" % (a[0], a[1]))
                e.call(fn["cal"], SPL[a[0]], a[1])
            elif code == OP_CONST:
                for off in (-27168, -27164, -27160):
                    emit("const gp%d %08x" % (off, e.u32(GP + off)))
            else:
                raise ValueError("op %d" % code)
        return self.out


def model(sc):
    return Model(sc).run()


# ================================================================ the build


def build_harness(tmp, name="quickspline_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, ops_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(ops_path)], stdout=fh,
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

MUTATIONS = [
    # -- the basis ---------------------------------------------------------
    ("basis-guard", QSC, "if (QuickSplineBasisMatrixInitDone != 0)",
     "if (0)"),
    ("basis-flag", QSC, "QuickSplineBasisMatrixInitDone = 1;",
     "QuickSplineBasisMatrixInitDone = 0;"),
    ("basis-m0", QSC,
     "set_row(&m[0].v1,   2.0f,   0.0f,  -5.0f,  3.0f);",
     "set_row(&m[0].v1,   2.0f,   0.0f,  -4.0f,  3.0f);"),
    ("basis-m1", QSC,
     "set_row(&m[1].v2,   1.0f,   8.0f,  -9.0f,  0.0f);",
     "set_row(&m[1].v2,   1.0f,   8.0f,  -8.0f,  0.0f);"),
    ("basis-m2", QSC,
     "set_row(&m[2].v3,  -2.0f,   6.0f,   0.0f,  0.0f);",
     "set_row(&m[2].v3,  -2.0f,   5.0f,   0.0f,  0.0f);"),
    ("basis-halve", QSC, "    halve(&m[1]);\n", ""),
    ("basis-halve-lane", QSC, "r->w = r->w * 0.5f;", "r->w = r->w * 1.0f;"),
    ("basis-transpose", QSC, "    bTransposeMatrix(&m[2], &m[2]);\n", ""),
    # -- construction ------------------------------------------------------
    ("init-max", QSC, "max = s->MaxControlPoints;", "max = n;"),
    ("init-alloc", QSC, "s->BufferWasAllocated = 1;",
     "s->BufferWasAllocated = 0;"),
    ("init-size", QSC, "(max + 3 + QUICKSPLINE_SLACK_POINTS)",
     "(max + 2 + QUICKSPLINE_SLACK_POINTS)"),
    ("init-clear", QSC, "memset(buf, 0,", "memset(buf, 1,"),
    ("init-flags", QSC, "quickspline.cpp\", 77, 16);",
     "quickspline.cpp\", 78, 16);"),
    ("init-pool", QSC, "quickspline.cpp\", 77, 16);",
     "quickspline.cpp\", 77, 0);"),
    ("initbuf-alloc", QSC, "s->BufferWasAllocated = 0;",
     "s->BufferWasAllocated = 1;"),
    ("initbuf-count", QSC, "(uint16_t)sub32(n, 3);", "(uint16_t)sub32(n, 2);"),
    ("initbuf-buf", QSC,
     "s->pControlPointBuffer = buf;\n    quickspline_setup(s, ept, basis);\n"
     "    return s;\n}\n\nvoid quickspline_destroy",
     "s->pControlPointBuffer = buf + 1;\n    quickspline_setup(s, ept, basis);\n"
     "    return s;\n}\n\nvoid quickspline_destroy"),
    ("destroy-alloc", QSC,
     "if (s->BufferWasAllocated != 0 && s->pControlPointBuffer != NULL)",
     "if (s->pControlPointBuffer != NULL)"),
    ("destroy-null", QSC,
     "if (s->BufferWasAllocated != 0 && s->pControlPointBuffer != NULL)",
     "if (s->BufferWasAllocated != 0)"),
    ("destroy-flag", QSC, "if (flags & 1)", "if (flags & 2)"),
    ("setup-ept", QSC, "s->EndPointType = ept;", "s->EndPointType = basis;"),
    ("setup-bt", QSC, "s->BasisType = basis;", "s->BasisType = ept;"),
    ("setup-basis", QSC, "if (basis == QUICKSPLINE_OVERHAUSER)",
     "if (basis != 1)"),
    ("setup-cp", QSC, "s->pControlPoints = s->pControlPointBuffer + 1;",
     "s->pControlPoints = s->pControlPointBuffer + 2;"),
    ("setup-minc", QSC, "s->MinControlPoints = 3;", "s->MinControlPoints = 2;"),
    ("setup-length", QSC, "s->Length = 0.0f;\n    quickspline_set_num",
     "s->Length = 1.0f;\n    quickspline_set_num"),
    ("setup-setn", QSC, "quickspline_set_num_control_points(s, 0);",
     "quickspline_set_num_control_points(s, 1);"),
    # -- the count ---------------------------------------------------------
    ("setn-dirty", QSC,
     "s->ControlPointsDirty = 1;\n    s->NumControlPoints",
     "s->ControlPointsDirty = 0;\n    s->NumControlPoints"),
    ("setn-trunc", QSC, "if (s->NumControlPoints == 0) {\n        s->MinParam",
     "if (n == 0) {\n        s->MinParam"),
    ("setn-zero-max", QSC, "s->MaxParam = 0.0f;\n        return;",
     "s->MaxParam = 1.0f;\n        return;"),
    ("setn-zero-return", QSC, "s->MaxParam = 0.0f;\n        return;",
     "s->MaxParam = 0.0f;"),
    ("setn-loop", QSC, "s->MaxParam = (float)s->NumControlPoints;",
     "s->MaxParam = (float)(s->NumControlPoints - 1);"),
    ("setn-line", QSC, "s->MaxParam = (float)(s->NumControlPoints - 1);",
     "s->MaxParam = (float)s->NumControlPoints;"),
    ("setn-ex-min", QSC, "s->MinParam = QUICKSPLINE_EXTRAPOLATED_MIN;",
     "s->MinParam = 0.0f;"),
    ("setn-ex-max", QSC, "s->MaxParam = QUICKSPLINE_EXTRAPOLATED_MAX;",
     "s->MaxParam = 9999998.0f;"),
    ("setn-default", QSC,
     "        // Any other type leaves the range as it was.\n        break;",
     "        s->MinParam = 0.0f;\n        break;"),
    ("hdr-ex-max", QSH, "#define QUICKSPLINE_EXTRAPOLATED_MAX 9999999.0f",
     "#define QUICKSPLINE_EXTRAPOLATED_MAX 9999998.0f"),
    ("hdr-eps", QSH, "#define QUICKSPLINE_LINE_EPSILON 1.00000001e-07f",
     "#define QUICKSPLINE_LINE_EPSILON 1.1e-07f"),
    # -- the endpoints -----------------------------------------------------
    ("ex-sub", QSC, "r.y = a->y - b->y;", "r.y = b->y - a->y;"),
    ("ex-mul", QSC, "r.w = r.w * k;", "r.w = r.w;"),
    ("ex-fused", QSC, "r.z = r.z + base->z;",
     "r.z = fmaf(a->z - b->z, k, base->z);"),
    ("fix-empty", QSC, "if (n == 0)\n        return;\n\n    // Every copy",
     "\n    // Every copy"),
    ("fix-loop-prev", QSC, "cp[-1] = cp[n - 1];", "cp[-1] = cp[n - 2];"),
    ("fix-loop-n", QSC, "cp[n] = cp[0];", "cp[n] = cp[1];"),
    ("fix-loop-n1", QSC, "cp[n + 1] = cp[1];", "cp[n + 1] = cp[0];"),
    ("fix-loop-order", QSC,
     "cp[n] = cp[0];\n        cp[n + 1] = cp[1];",
     "cp[n + 1] = cp[1];\n        cp[n] = cp[0];"),
    ("fix-loop-len", QSC,
     "if (s->Length == 0.0f)\n            return;\n        // Around",
     "if (s->Length != 0.0f)\n            return;\n        // Around"),
    ("fix-loop-w-prev", QSC, "cp[-1].w = cp[n - 1].w - s->Length;",
     "cp[-1].w = s->Length - cp[n - 1].w;"),
    ("fix-loop-w-n", QSC, "cp[n].w = s->Length + cp[0].w;",
     "cp[n].w = s->Length + cp[1].w;"),
    ("fix-loop-w-n1", QSC, "cp[n + 1].w = s->Length + cp[1].w;",
     "cp[n + 1].w = cp[1].w;"),
    ("fix-line-front", QSC, "cp[-1] = cp[0];\n        cp[n] = cp[n - 1];",
     "cp[-1] = cp[1];\n        cp[n] = cp[n - 1];"),
    ("fix-line-back", QSC, "cp[n] = cp[n - 1];", "cp[n] = cp[n - 2];"),
    ("fix-line-len", QSC,
     "if (s->Length == 0.0f)\n            return;\n        // Mirrored",
     "if (s->Length != 0.0f)\n            return;\n        // Mirrored"),
    ("fix-line-w-front", QSC, "cp[-1].w = -cp[1].w;", "cp[-1].w = -cp[0].w;"),
    ("fix-line-w-back", QSC, "cp[n].w = (s->Length + s->Length) - cp[n - 1].w;",
     "cp[n].w = s->Length - cp[n - 1].w;"),
    ("fix-ex-len", QSC,
     "if (s->Length == 0.0f)\n            return;\n        cp[-1].w",
     "cp[-1].w"),
    ("fix-ex-w-front", QSC,
     "return;\n        cp[-1].w = -cp[1].w;",
     "return;\n        cp[-1].w = -cp[0].w;"),
    ("fix-ex-w-back", QSC,
     "cp[n].w = (s->Length + s->Length) - cp[n - 1].w;\n        return;\n\n"
     "    default:",
     "cp[n].w = s->Length - cp[n - 1].w;\n        return;\n\n    default:"),
    ("fix-ex-front-k", QSC, "&cp[1], &cp[0], -1.0f, &cp[0]);",
     "&cp[1], &cp[0], 1.0f, &cp[0]);"),
    ("fix-ex-front-base", QSC, "&cp[1], &cp[0], -1.0f, &cp[0]);",
     "&cp[1], &cp[0], -1.0f, &cp[1]);"),
    ("fix-ex-back-k", QSC, "&cp[n - 2], 1.0f, &cp[n - 1]);",
     "&cp[n - 2], -1.0f, &cp[n - 1]);"),
    ("fix-ex-back-base", QSC, "&cp[n - 2], 1.0f, &cp[n - 1]);",
     "&cp[n - 2], 1.0f, &cp[n - 2]);"),
    ("genex-count", QSC, "for (i = 0; i < 4; i++) {",
     "for (i = 0; i < 3; i++) {"),
    ("genex-low", QSC, "if (k < -1)", "if (k < 0)"),
    ("genex-high", QSC, "else if (n < k)", "else if (n <= k)"),
    ("genex-low-k", QSC, "(float)sub32(0, k)", "(float)sub32(-1, k)"),
    ("genex-high-k", QSC, "(float)add32(sub32(k, n), 1)",
     "(float)sub32(k, n)"),
    ("genex-low-pair", QSC, "extrapolate(&out[i], &cp[0], &cp[1],",
     "extrapolate(&out[i], &cp[1], &cp[0],"),
    ("genex-high-pair", QSC, "extrapolate(&out[i], &cp[n - 1], &cp[n - 2],",
     "extrapolate(&out[i], &cp[n - 2], &cp[n - 1],"),
    ("genex-copy", QSC, "out[i] = cp[k];", "out[i] = cp[k - 1];"),
    # -- evaluation --------------------------------------------------------
    ("eval-one", QSC, "v.x = 1.0f;", "v.x = 0.0f;"),
    ("eval-t2", QSC, "float    t2 = t * t;", "float    t2 = t;"),
    ("eval-basis", QSC, "&s->pBasisMatricies[basis]",
     "&s->pBasisMatricies[0]"),
    ("clamp-loop", QSC, "return bFMod(t, s->MaxParam);",
     "return fmodf(t, s->MaxParam);"),
    ("clamp-eps", QSC, "float hi = s->MaxParam - QUICKSPLINE_LINE_EPSILON;",
     "float hi = s->MaxParam;"),
    ("clamp-min-le", QSC, "t = (t < s->MinParam) ? s->MinParam : t;",
     "t = (t <= s->MinParam) ? s->MinParam : t;"),
    ("clamp-min-src", QSC, "t = (t < s->MinParam) ? s->MinParam : t;",
     "t = (t < s->MinParam) ? 0.0f : t;"),
    ("clamp-max-le", QSC, "return (t < hi) ? t : hi;",
     "return (t <= hi) ? t : hi;"),
    ("clamp-type", QSC, "if (s->EndPointType == QUICKSPLINE_LINE) {",
     "if (s->EndPointType != QUICKSPLINE_EXTRAPOLATED) {"),
    ("gp-dirty-skip", QSC,
     "if (s->ControlPointsDirty != 0) {\n        quickspline_fixup_endpoints(s);"
     "\n        s->ControlPointsDirty = 0;\n    }\n\n    if (s->NumControlPoints"
     " == 0) {\n        out->x",
     "if (0) {\n        quickspline_fixup_endpoints(s);"
     "\n        s->ControlPointsDirty = 0;\n    }\n\n    if (s->NumControlPoints"
     " == 0) {\n        out->x"),
    ("gp-dirty-keep", QSC,
     "        s->ControlPointsDirty = 0;\n    }\n\n    if (s->NumControlPoints"
     " == 0) {\n        out->x",
     "    }\n\n    if (s->NumControlPoints == 0) {\n        out->x"),
    ("gp-empty", QSC, "out->w = 0.0f;", "out->w = 1.0f;"),
    ("gp-trunc", QSC, "whole = (float)ee_trunc_w(t);", "whole = floorf(t);"),
    ("gp-floor-le", QSC, "if (t < whole)\n        whole = whole - 1.0f;",
     "if (t <= whole)\n        whole = whole - 1.0f;"),
    ("gp-floor-off", QSC, "if (t < whole)\n        whole = whole - 1.0f;", ""),
    ("gp-frac", QSC, "    t = t - whole;\n", ""),
    ("gp-ex-last", QSC, "seg >= s->NumControlPoints - 1)",
     "seg >= s->NumControlPoints)"),
    ("gp-ex-low", QSC, "(seg < 0 ||", "(seg < -1 ||"),
    ("gp-ex-type", QSC,
     "if (s->EndPointType == QUICKSPLINE_EXTRAPOLATED\n",
     "if (s->EndPointType != QUICKSPLINE_LOOP\n"),
    ("gp-ex-start", QSC, "sub32(seg, 1));", "seg);"),
    ("gp-ex-basis", QSC,
     "quickspline_evaluate_spline(s, out, t, basis, pts);",
     "quickspline_evaluate_spline(s, out, t, 0, pts);"),
    ("gp-cp", QSC, "&s->pControlPoints[seg - 1]);",
     "&s->pControlPoints[seg]);"),
    # -- the searches ------------------------------------------------------
    ("dist-y", QSC, "float dy = p->y - q->y;", "float dy = p->y - q->x;"),
    ("dist-order", QSC, "return sqrtf(dx * dx + dy * dy + dz * dz);",
     "return sqrtf(dx * dx + (dy * dy + dz * dz));"),
    ("from-start-d", QSC, "float     bestd = dist3(p, &cp[start]);",
     "float     bestd = dist3(p, &cp[0]);"),
    ("from-fwd-tie", QSC, "if (bestd <= d)", "if (bestd < d)"),
    ("from-bwd-tie", QSC,
     "for (i = start - 1; i >= 0; i--) {\n        float d = dist3(p, &cp[i]);"
     "\n\n        if (bestd <= d)",
     "for (i = start - 1; i >= 0; i--) {\n        float d = dist3(p, &cp[i]);"
     "\n\n        if (bestd < d)"),
    ("from-fwd-end", QSC, "for (i = start + 1; i < n; i++) {",
     "for (i = start + 1; i < n - 1; i++) {"),
    ("from-bwd-end", QSC, "for (i = start - 1; i >= 0; i--) {",
     "for (i = start - 1; i > 0; i--) {"),
    ("from-bwd-start", QSC, "for (i = start - 1; i >= 0; i--) {",
     "for (i = best - 1; i >= 0; i--) {"),
    ("from-fwd-bestd", QSC,
     "        bestd = d;\n    }\n\n    // ...then",
     "    }\n\n    // ...then"),
    ("all-tie", QSC, "if (best < 0 || d < bestd) {",
     "if (best < 0 || d <= bestd) {"),
    ("all-init", QSC, "int32_t best = -1;", "int32_t best = 0;"),
    ("all-end", QSC,
     "for (i = 0; i < n; i++) {\n"
     "        float d = dist3(p, &s->pControlPoints[i]);",
     "for (i = 0; i < n - 1; i++) {\n"
     "        float d = dist3(p, &s->pControlPoints[i]);"),
    ("fcp-left", QSC, "int32_t  left = 998;", "int32_t  left = 999;"),
    ("fcp-limit", QSC, "float    limit = 1.0f;", "float    limit = 2.0f;"),
    ("fcp-fixup", QSC,
     "        quickspline_fixup_endpoints(s);\n        s->ControlPointsDirty = 0;"
     "\n    }\n\n    if (s->NumControlPoints == 0)\n        return 0.0f;",
     "        s->ControlPointsDirty = 0;"
     "\n    }\n\n    if (s->NumControlPoints == 0)\n        return 0.0f;"),
    ("fcp-clear", QSC,
     "        s->ControlPointsDirty = 0;"
     "\n    }\n\n    if (s->NumControlPoints == 0)\n        return 0.0f;",
     "    }\n\n    if (s->NumControlPoints == 0)\n        return 0.0f;"),
    ("fcp-empty", QSC, "        return 0.0f;\n\n    do {",
     "        return guess;\n\n    do {"),
    ("fcp-tangent", QSC, "quickspline_get_point(s, &tan, t, 1);",
     "quickspline_get_point(s, &tan, t, 2);"),
    ("fcp-speed", QSC, "tan.y * tan.y + tan.z * tan.z);",
     "tan.y * tan.y + tan.z * tan.z + tan.w * tan.w);"),
    ("fcp-speed0", QSC, "if (speed == 0.0f)\n            return t;\n", ""),
    ("fcp-err-y", QSC, "(p->y - pos.y) * tan.y", "(p->y - pos.y) * tan.x"),
    ("fcp-err-div", QSC, "+ (p->z - pos.z) * tan.z) / speed;",
     "+ (p->z - pos.z) * tan.z);"),
    ("fcp-tol", QSC, "if (fabsf(err) < tolerance)",
     "if (fabsf(err) <= tolerance)"),
    ("fcp-first", QSC, "slope = speed;", "slope = 1.0f;"),
    ("fcp-secant", QSC, "slope = (prevErr - err) / prevStep;",
     "slope = (err - prevErr) / prevStep;"),
    ("fcp-slope0", QSC, "if (slope == 0.0f)\n                return t;\n", ""),
    ("fcp-clamp-neg", QSC,
     "        step = (step < -limit) ? -limit : step;\n", ""),
    ("fcp-clamp-pos", QSC,
     "        step = (step < limit) ? step : limit;\n", ""),
    ("fcp-wrap", QSC, "next = quickspline_clamp_param(s, t + step);",
     "next = t + step;"),
    ("fcp-halve-sign", QSC, "if (step * prevStep < 0.0f)",
     "if (step * prevStep <= 0.0f)"),
    ("fcp-halve-amt", QSC, "limit = limit * 0.5f;", "limit = limit * 0.25f;"),
    ("fcp-prev-err", QSC, "        prevErr = err;\n", ""),
    ("cal-w", QSC, "        s->pControlPoints[i].w = total;\n", ""),
    ("cal-dirty", QSC,
     "        s->ControlPointsDirty = 1;\n\n        // A LINE",
     "\n        // A LINE"),
    ("cal-max", QSC, "if (!(fi < s->MaxParam))", "if (!(fi <= s->MaxParam))"),
    ("cal-start", QSC, "        quickspline_get_point(s, &cur, fi, 0);\n", ""),
    ("cal-param", QSC, "fi + (float)j / (float)samples",
     "fi + (float)j * (1.0f / (float)samples)"),
    ("cal-sum", QSC, "total = total + sqrtf(dx * dx + dy * dy + dz * dz);",
     "total = total + sqrtf(dx * dx + (dy * dy + dz * dz));"),
    ("cal-prev", QSC, "            prev = cur;\n        }\n    }",
     "        }\n    }"),
    ("cal-length", QSC, "    s->Length = total;\n", ""),
    ("cal-final-dirty", QSC,
     "s->Length = total;\n    s->ControlPointsDirty = 1;",
     "s->Length = total;\n    s->ControlPointsDirty = 0;"),
]

EQUIVALENT = {}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name


def mutate_pass(only=None):
    sc = script()
    base = model(sc)
    caught = 0
    survived = []
    missing = []
    equivalent = []
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only is not None:
        unknown = sorted(set(only) - {m[0] for m in MUTATIONS})
        if unknown:
            sys.exit("no such mutation: " + " ".join(unknown))

    opsdir = tempfile.TemporaryDirectory()
    ops = Path(opsdir.name) / "ops.bin"
    ops.write_bytes(sc.encode())
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, ops, out)
        if diff(base, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for m in todo:
        name, rel = m[0], m[1]
        edits = m[2] if len(m) == 3 else [(m[2], m[3], 1)]
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        new = text
        ok = True
        for before, after, count in edits:
            probe = before.replace(NL, "\r\n") if crlf else before
            repl = after.replace(NL, "\r\n") if crlf else after
            if new.count(probe) < count:
                ok = False
                break
            new = new.replace(probe, repl, count)
        if not ok:
            missing.append(name)
            print("  %-44s PATTERN NOT FOUND" % name)
            continue
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
                rc = run_harness(exe, ops, out)
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
    opsdir.cleanup()

    real = [m for m in todo if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    # An entry whose mutant was caught is a wrong reason, not a spare one.
    # --only leaves the others unrun, so only the ones that ran are judged.
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
        ops = Path(tmp) / "ops.bin"
        ops.write_bytes(sc.encode())
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, ops, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(lines, harness)
    print("%d ops, %d lines, %d differ" % (len(sc.ops), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
