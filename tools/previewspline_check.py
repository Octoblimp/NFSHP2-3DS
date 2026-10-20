#!/usr/bin/env python3
"""Cross-check 3DS Files/source/previewspline.c, the Zone Preview camera's
course (PreviewRoute::MakeSplines and the free functions it calls), against
the retail image itself, run in mipsemu.

The model is the image. MakeSplines (0x00166570), LinearSeek (0x00164e58),
both EnforceHeightGaps (0x00164ea8, 0x00164f20), DownSampleXY
(0x00165150), EnforceMaximumSlope (0x001656b0), Spline::SetControlPoint
(0x00189460) and the Graph lookup the other way round (0x0018faf0) run as
shipped, with ConstrainToTopology (0x0015fd80), PreviewRoutePoint::
GetPosition (0x00164428) and TrackRoutePoint's under it, Spline's
constructors, destructor, AddControlPoint, GetPoint and what they call,
Graph's constructor and GetValue (0x0018f9f0) and Linear::GetValue
(0x00190070) under them. The harness (tools/src/previewspline_test.c) runs
the port's over the same script, and the two transcripts are diffed.

Stubs, printing what they are given on both sides: bMalloc hands out
blocks from a patterned arena, __builtin_delete and __builtin_vec_delete
print the block; SetInterestBBox (0x00136e00), GetElevation (0x00152070,
answers from a scripted list) and ConstrainToTopology's member
(0x001528b0, moves `to` and answers from a scripted list). The route, its
points and their TrackRoutePoints, the splines, the Linear, the stops and
the Graph's knees are laid out by the script.

The script:

    t k x y e dx dy bank fwd    TrackRoutePoint k: Position, Elevation,
                                Direction, BankSlope, ForwardSlope
    p k trp len off gap         PreviewRoutePoint k on TrackRoutePoint trp:
                                fLength, fOffset, fRouteGap
    r n dist off nul            the route: n points, fDistance, fOffset,
                                pPoints NULL when nul
    E n v...                    GetElevation's answers, in turn
    X n (r dx dy dz)...         the constrain member's answers and moves
    l m b                       the Linear
    a j type buf                spline j from the allocating constructor
    c j n (x y z w)...          spline j's points written straight in
    y j type                    spline j's Type
    M mask                      MakeSplines(route, tc, s0, s1, s2, Linear),
                                each when its bit (1, 2, 4, 8) is set
    H r s i gap, G r s i        EnforceHeightGap(s_r, s_s, i[, gap])
    D j frac nul n stops...     DownSampleXY(s_j, frac, stops or NULL, n)
    S j slope                   EnforceMaximumSlope(s_j, slope)
    W j i x y z w               SetControlPoint(s_j, i, v)
    K from to step              LinearSeek
    I n (x y)... m y...         the Graph lookup over n knees, m times
    d j                         spline j's dump

Floats are bits in hex. Every block, route point and spline starts as
0xa5 bytes, and the arena's first block 16 bytes in, so a read off either
end of a buffer reads the same bytes on both sides. A spline's points
print with the slot either side of them, so a write off either end shows.
After MakeSplines the control points print without the pad lanes: TrackRoutePoint::GetPosition
fills the walk's from its stack, and the eye points' are never written;
no lane reaches another anywhere after. The topology stubs print vectors
without the pad lanes too.

Not run on both sides: DownSampleXY with `stops` NULL and a count above
0 (retail's knees between are stack words; no caller does it), with more
than 4 stops (retail's fifth closing knee lands on its Graph), or with a
negative fraction (retail's alloca then wraps, and its constructor loop
does not end). With one coarse point (3 control points or fewer) retail's
GetPoint reads a slot either side of it, its knees and a callee's frame,
both with a weight of 0; the port reads zeros, and the script has such
splines.

    python tools/previewspline_check.py
    python tools/previewspline_check.py --mutate [--only a,b]
    python tools/previewspline_check.py --dump out/previewspline
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
import hostbuild
import mutpar
import physicscar_check as pcc
import retail_model
from mipsemu import M32, f_to_bits, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/previewspline_test.c"
PSC = "3DS Files/source/previewspline.c"
SOURCES = [HARNESS, PSC] + ["3DS Files/source/" + f for f in (
    "zonecam.c", "spline.c", "graph.c", "average.c", "previewroute.c",
    "trackroute.c", "trackpath.c", "quickspline.c", "banim.c", "cammover.c",
    "race.c", "camera.c", "eview.c", "emath.c", "bmatrix.c", "bmath.c",
    "replay.c", "p32.c", "bmathtab.c", "bvector.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
MAKE = 0x00166570                 # PreviewRoute::MakeSplines
SEEK = 0x00164e58                 # LinearSeek
GAP_AT = 0x00164ea8               # EnforceHeightGap(Spline *, Spline *, int, float)
GAP = 0x00164f20                  # EnforceHeightGap(Spline *, Spline *, int)
DOWN = 0x00165150                 # DownSampleXY
SLOPE = 0x001656b0                # EnforceMaximumSlope
SETCP = 0x00189460                # Spline::SetControlPoint
INVERSE = 0x0018faf0              # the Graph lookup the other way round
GETVALUE = 0x0018f9f0             # Graph::GetValue
STOPS_FN = 0x00165a70             # the stops, DownSampleXY's other caller
ZP_CTOR = 0x00161f98              # ZonePreviewCameraMover's constructor
VDL_CTOR = 0x00174ec0             # VisibleDrivingLine's constructor
SPL_ALLOC = 0x00189198
BMALLOC = 0x002577c0
DELETE = 0x00114e98
VEC_DELETE = 0x00114e90
SET_BBOX3 = 0x00136e00
GET_ELEV = 0x00152070
CONSTRAIN = 0x001528b0            # TopologyCoordinate::ConstrainToTopology
FUNK_EXISTS = 0x0025d220
EMATH_SINIT = 0x0011bf70          # writes eMulVector's (0, 0, 0, 1)
BMATRIX_SINIT = 0x0025afa8        # 0x00320a60 = (0, 0, 0, 1), bMulMatrix's

TRPS = 0x01000000
TRP_SIZE = 112
NTRP = 160
RPTS = 0x01008000
RPT_SIZE = 24
ROUTE = 0x0100a000
TC = 0x0100a100
SPLS = 0x0100b000
SPL_SIZE = 48
NSPL = 4
LIN = 0x0100b100
STOPS = 0x0100b200
NSTOP = 8
KNEES = 0x0100b300
NKNEE = 16
GRAPH = 0x0100b400
VEC = 0x0100b500
ARENA = 0x01040000
ARENA_SIZE = 0x80000
ARENA_GUARD = 16

PATTERN = 0xa5
LIMIT = 50000000


def fb(v):
    if isinstance(v, int):
        return v & M32
    return f_to_bits(v)


def h(v):
    return "%08x" % fb(v)


def fx(w):
    """A float's bits, with every NaN the one "nan"."""
    w &= M32
    if (w & 0x7f800000) == 0x7f800000 and (w & 0x7fffff):
        return "nan"
    return "%08x" % w


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def spl_at(j):
    return SPLS + SPL_SIZE * j


def vec(*xs):
    return " ".join(h(x) for x in xs)


# ============================================================ the scenarios


def s_seek(rnd):
    """LinearSeek: each way, the step past, short of and exactly on the
    gap, no gap, a step of 0 and below it."""
    out = []
    fixed = [(0.0, 10.0, 4.0), (10.0, 0.0, 4.0), (3.0, 3.0, 4.0),
             (1.0, 5.0, 4.0), (5.0, 1.0, 4.0), (1.0, 4.0, 4.0),
             (-2.0, 2.0, 4.0), (2.0, -2.0, 4.0), (0.0, 0.0, 0.0),
             (1.0, 2.0, 0.0), (2.0, 1.0, -1.0), (1.0, 2.0, -1.0),
             (0.0, -0.0, 4.0), (-0.0, 0.0, 4.0), (6.0, 6.5, 0.5),
             (6.5, 6.0, 0.5)]
    for a, b, s in fixed:
        out.append("K %s" % vec(a, b, s))
    for _ in range(40):
        a = rnd.uniform(-8, 8)
        b = rnd.choice((a, a + rnd.uniform(-8, 8), rnd.uniform(-8, 8)))
        out.append("K %s" % vec(a, b, rnd.choice((4.0, 4.0, 0.5,
                                                 rnd.uniform(0, 6)))))
    return out


def s_inverse(rnd):
    """The Graph lookup: no knee, one, two and more, climbing, flat and
    out of order; below the first, on each knee, between, at and past the
    last, and a NaN."""
    out = []

    def one(knees, ys):
        ks = " ".join(vec(x, y) for x, y in knees)
        out.append("I %d %s %d %s" % (len(knees), ks, len(ys),
                                      " ".join(h(y) for y in ys)))

    def probes(knees):
        ys = [k[1] for k in knees]
        lo, hi = min(ys + [0.0]), max(ys + [1.0])
        t = [lo - 1.0, hi + 1.0, 0.0, 0x7fc00000]
        t += ys
        for a, b in zip(ys, ys[1:]):
            t.append(f32((a + b) / 2))
        t += [rnd.uniform(lo - 0.5, hi + 0.5) for _ in range(4)]
        return t

    one([], [0.0, 1.0])
    one([(3.0, 2.0)], [0.0, 2.0, 5.0])
    one([(0.0, 0.0), (4.0, 10.0)], probes([(0.0, 0.0), (4.0, 10.0)]))
    one([(0.0, 0.0), (1.0, 1.5), (3.0, 7.0), (3.0, 9.0)],
        probes([(0.0, 0.0), (1.0, 1.5), (3.0, 7.0), (3.0, 9.0)]))
    # A pair closer than the epsilon in y: the midpoint in x.
    k = [(0.0, 0.0), (2.0, 4.0), (5.0, f32(4.0 + 4e-7)), (6.0, 20.0)]
    one(k, probes(k) + [4.0, f32(4.0 + 2e-7)])
    k = [(0.0, 0.0), (2.0, 4.0), (5.0, f32(4.0 + 2e-6)), (6.0, 20.0)]
    one(k, probes(k) + [4.0, f32(4.0 + 1e-6)])
    for _ in range(6):
        n = rnd.randrange(2, 7)
        y, k = rnd.uniform(-5, 5), []
        for i in range(n):
            k.append((float(i) + rnd.uniform(-0.3, 0.3), y))
            y += rnd.choice((rnd.uniform(0.1, 6), rnd.uniform(0.1, 6), 0.0))
        one(k, probes(k))
    k = [(0.0, 5.0), (1.0, 2.0), (2.0, 8.0), (3.0, 1.0)]
    one(k, probes(k))
    # A flat first pair, and a first pair closer than the epsilon.
    k = [(0.0, 1.0), (2.0, 1.0), (5.0, 4.0)]
    one(k, probes(k))
    k = [(0.5, 0.0), (2.0, f32(4e-7)), (5.0, 4.0)]
    one(k, probes(k))
    return out


def curve(rnd, n, zspread=3.0):
    """n control points along a winding road, each lane its own."""
    x, y, z = rnd.uniform(-500, 500), rnd.uniform(-500, 500), \
        rnd.uniform(-10, 60)
    head = rnd.uniform(-math.pi, math.pi)
    pts = []
    for _ in range(n):
        pts.append((x, y, z + rnd.uniform(-zspread, zspread),
                    rnd.choice((0.0, 1.0, rnd.uniform(-2, 2)))))
        step = rnd.uniform(4, 14)
        x += math.cos(head) * step
        y += math.sin(head) * step
        z += rnd.uniform(-1.5, 1.5)
        head += rnd.uniform(-0.4, 0.4)
    return pts


def put(j, pts):
    return "c %d %d %s" % (j, len(pts),
                           " ".join(vec(*p) for p in pts))


def s_gaps(rnd):
    """Both EnforceHeightGaps over two splines of each type: points
    before, at, inside and past each end, a gap above and below each
    point's, and the halves of odd and even counts."""
    out = []
    for typ in (2, 0, 1, 3, 2):
        for n in (1, 2, 5, 8, 13):
            ref = curve(rnd, n + rnd.randrange(0, 3))
            s = [(x, y, z + rnd.choice((0.5, 2.0, 10.0, -1.0,
                                        rnd.uniform(-3, 12))), w)
                 for x, y, z, w in ref[:n]]
            out += ["a 0 %d 32" % typ, "a 1 %d 32" % typ, put(0, ref),
                    put(1, s)]
            for i in (-2, -1, 0, n // 2, n - 1, n, n + 2):
                out.append("H 0 1 %d %s" % (i, h(rnd.choice(
                    (0.5, 2.0, 0.0, -0.5, rnd.uniform(-1, 11))))))
            out.append(put(1, s))
            for i in sorted({-3, -2, -1, 0, 1, n // 2 - 1, n // 2,
                             n // 2 + 1, n - 2, n - 1, n, n + 1, n + 3}):
                out.append("G 0 1 %d" % i)
                if rnd.random() < 0.5:
                    out.append(put(1, [(x, y, z + rnd.uniform(-2, 12), w)
                                       for x, y, z, w in ref[:n]]))
    # The exact gap: held where it already is.
    ref = curve(rnd, 6, 0.0)
    s = [(x, y, f32(z + 2.0), w) for x, y, z, w in ref]
    out += ["a 0 2 16", "a 1 2 16", put(0, ref), put(1, s)]
    for i in range(6):
        out.append("H 0 1 %d %s" % (i, h(f32(s[i][2] - ref[i][2]))))
    return out


def s_slope(rnd):
    """EnforceMaximumSlope: no point, one, two, and runs with drops both
    ways, at 0.4, 0 and a negative slope."""
    out = []
    for n in (0, 1, 2, 3, 6, 20):
        for slope in (0.4, 0.4, 0.0, -0.2, rnd.uniform(0.05, 2)):
            pts = curve(rnd, n, rnd.choice((0.5, 3.0, 15.0)))
            if n > 3 and rnd.random() < 0.5:
                k = rnd.randrange(n)
                x, y, z, w = pts[k]
                pts[k] = (x, y, z + rnd.choice((-30.0, 30.0)), w)
            out += ["a 2 2 32", put(2, pts), "S 2 %s" % h(slope)]
    return out


def down_case(rnd, n, typ, frac, stops, buf=None):
    pts = curve(rnd, n)
    out = ["a 3 %d %d" % (typ, buf or max(n, 1)), put(3, pts)]
    if stops is None:
        out.append("D 3 %s 1 0" % h(frac))
    else:
        out.append("D 3 %s 0 %d %s" % (h(frac), len(stops),
                                       " ".join(h(s) for s in stops)))
    return out


def s_down(rnd):
    """DownSampleXY: every count from 0 to 12 and a few long ones, each
    type, the fractions that come out whole and not, and 0 to 4 stops: in
    order, out of order, at the ends, past them, below 0, and the ones
    whose knee falls on a half."""
    out = []
    for n in range(0, 13):
        for typ in (2, 0, 1, 3):
            if typ == 1 and n < 2:
                continue
            out += down_case(rnd, n, typ, 0.3333, None)
    for n in (4, 6, 8, 9, 12, 30, 33, 47, 100):
        for frac in (0.3333, 0.5, 0.25, 1.0, 0.1, rnd.uniform(0.05, 1)):
            out += down_case(rnd, n, rnd.choice((2, 2, 0, 1)), frac, None)
    # Past the stack's 64 coarse points, on the heap.
    out += down_case(rnd, 200, 2, 0.3333, None)
    out += down_case(rnd, 260, 2, 0.5, None)
    out += down_case(rnd, 150, 2, 0.5, [20.0, 75.5])
    # The stops.
    for n in (4, 7, 8, 10, 16, 33, 40):
        for typ in (2, 2, 0, 1, 3):
            last = {0: n - 1, 1: n, 2: n - 1, 3: 0}[typ]
            if last == 0:
                continue
            for k in range(0, 5):
                st = sorted(rnd.uniform(0, last) for _ in range(k))
                if rnd.random() < 0.3:
                    rnd.shuffle(st)
                if k and rnd.random() < 0.3:
                    st[rnd.randrange(k)] = rnd.choice(
                        (0.0, float(last), -1.5, last + 2.0,
                         rnd.uniform(-3, 0)))
                out += down_case(rnd, n, typ, rnd.choice((0.3333, 0.3333,
                                                          0.5)), st)
            out += down_case(rnd, n, typ, 0.3333, [])
    # A knee on a half: n 8, fraction 0.5 (top 3), last 7: 3.5 -> 1.5,
    # -3.5 -> -1.5, and their neighbours.
    for st in ([3.5], [-3.5], [f32(3.5 + 1e-5)], [f32(3.5 - 1e-5)],
               [-2.8], [-4.0], [7.0, 3.5], [0.0, 7.0]):
        out += down_case(rnd, 8, 2, 0.5, st)
    # A negative count of stops: the closing knee over the first.
    out += down_case(rnd, 9, 2, 0.3333, [2.0], None)
    out.append("D 3 %s 0 -1 %s" % (h(0.3333), h(2.0)))
    return out


def s_set(rnd):
    pts = curve(rnd, 5)
    out = ["a 1 2 8", put(1, pts)]
    for i in (0, 4, 2, 5):
        out.append("W 1 %d %s" % (i, vec(*(rnd.uniform(-50, 50)
                                           for _ in range(4)))))
    return out


def route_lines(rnd, npts, spacing=(3.0, 25.0), gaps=0.2):
    """npts route points along a winding road, each on a TrackRoutePoint
    of its own: the lines, and the sum of their lengths."""
    x, y, z = rnd.uniform(-900, 900), rnd.uniform(-900, 900), \
        rnd.uniform(-20, 80)
    head = rnd.uniform(-math.pi, math.pi)
    out, total = [], 0.0
    for k in range(npts):
        d = (math.cos(head), math.sin(head))
        fwd = rnd.uniform(-0.15, 0.15)
        out.append("t %d %s" % (k, vec(x, y, z, d[0], d[1],
                                       rnd.uniform(-0.1, 0.1), fwd)))
        ln = rnd.uniform(*spacing)
        off = rnd.choice((0.0, rnd.uniform(-6, 6), rnd.uniform(-6, 6)))
        gap = 0.0 if rnd.random() > gaps else rnd.uniform(-5, 5)
        out.append("p %d %d %s" % (k, k, vec(ln, off, gap)))
        x += d[0] * ln
        y += d[1] * ln
        z += fwd * ln
        head += rnd.uniform(-0.35, 0.35)
        total += ln
    return out, total


def elev_line(rnd, z):
    n = rnd.randrange(3, 9)
    return "E %d %s" % (n, vec(*(z + rnd.uniform(-4, 4) for _ in range(n))))


def constrain_line(rnd):
    n = rnd.randrange(2, 7)
    parts = []
    for _ in range(n):
        r = rnd.choice((0, 0, 0, 1, 2))
        d = ((0.0, 0.0, 0.0) if r == 0 and rnd.random() < 0.7 else
             tuple(rnd.uniform(-1.5, 1.5) for _ in range(3)))
        parts.append("%d %s" % (r, vec(*d)))
    return "X %d %s" % (n, " ".join(parts))


def s_make(rnd, mask=15, npts=None, types=(2, 2, 2), buf=100, dist=None,
           param=None, nul=False):
    """One MakeSplines: a route, the three splines, the Linear, the
    topology's answers, then the call and the dumps."""
    npts = rnd.randrange(8, 40) if npts is None else npts
    lines, total = route_lines(rnd, npts)
    out = list(lines)
    if dist is None:
        dist = rnd.choice((total, total, total * rnd.uniform(0.3, 0.95),
                           total + rnd.uniform(5, 40), 320.0))
    elif callable(dist):
        dist = dist(total)
    out.append("r %d %s %s %d" % (npts, h(dist),
                                  h(rnd.choice((0.0, rnd.uniform(-7, 7)))),
                                  1 if nul else 0))
    if param is None:
        param = (rnd.uniform(0.4, 0.95), rnd.uniform(0.0, 0.25))
    out.append("l %s" % vec(*param))
    out += ["a %d %d %d" % (j, types[j], buf) for j in range(3)]
    out += [elev_line(rnd, rnd.uniform(-20, 80)), constrain_line(rnd)]
    out.append("M %d" % mask)
    return out


def script():
    rnd = random.Random(0x5b1e9e01)
    sc = [s_seek(rnd), s_inverse(rnd), s_set(rnd), s_slope(rnd),
          s_gaps(rnd), s_down(rnd)]
    # The whole course, as the mover asks for it.
    for _ in range(6):
        sc.append(s_make(rnd))
    # Short routes and short walks: 1, 2 and 3 control points, and none.
    for d in (4.0, 10.0, 15.0, 25.0, 30.0, 0.0, -3.0):
        sc.append(s_make(rnd, npts=rnd.randrange(4, 8), dist=d))
    sc.append(s_make(rnd, npts=1))
    sc.append(s_make(rnd, npts=0))
    sc.append(s_make(rnd, nul=True))
    # Each spline or the Linear missing; VisibleDrivingLine's look alone.
    for mask in (1, 3, 5, 6, 7, 11, 13, 14, 9, 0, 2, 4, 8, 10, 12):
        sc.append(s_make(rnd, mask=mask, npts=rnd.randrange(6, 20)))
    # The spline types; a small buffer that AddControlPoint grows.
    for types in ((0, 0, 0), (1, 1, 1), (3, 2, 2), (2, 0, 1), (-1, 2, 3)):
        sc.append(s_make(rnd, types=types, npts=rnd.randrange(6, 20)))
    sc.append(s_make(rnd, buf=4, npts=12))
    # The ends of the flight off the spline's ends, and on them.
    for param in ((0.0, 0.0), (1.0, 0.0), (0.5, -0.4), (0.3, 0.9),
                  (2.0, 0.1), (-1.0, 0.5), (0.0, 0.5), (1.0, -0.2)):
        sc.append(s_make(rnd, param=param, npts=rnd.randrange(6, 20)))
    # Long gaps between route points, and short ones.
    lines = s_make(rnd, npts=30)
    sc.append(lines)
    return sc


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
        self.e = retail_model.emu(retail=True, ieee=True)
        e = self.e
        e.stub(FUNK_EXISTS, lambda em: 0)
        e.stub(VEC_DELETE, self.s_free)
        e.stub(DELETE, self.s_free)
        e.stub(BMALLOC, self.s_malloc)
        e.stub(SET_BBOX3, self.s_bbox)
        e.stub(GET_ELEV, self.s_elev)
        e.stub(CONSTRAIN, self.s_constrain)
        e.call(EMATH_SINIT)
        e.call(BMATRIX_SINIT)
        self.names = {0: "null", TC: "tc"}
        for j in range(NSPL):
            self.names[spl_at(j)] = "s%d" % j
        self.blocks = {}

    def emit(self, s):
        self.out.append(s)

    def name(self, a):
        a &= M32
        if a in self.blocks:
            return self.blocks[a]
        return self.names.get(a, "?%08x" % a)

    def fill(self, a, n):
        self.e.write(a, bytes([PATTERN]) * n)

    def w(self, a):
        return self.e.u32(a)

    def cstr(self, a):
        s = bytearray()
        while self.e.mem[a] and len(s) < 200:
            s.append(self.e.mem[a])
            a += 1
        return s.decode("latin-1")

    def reset(self):
        self.fill(TRPS, TRP_SIZE * NTRP)
        self.fill(RPTS, RPT_SIZE * NTRP)
        self.fill(ROUTE, 24)
        self.fill(SPLS, SPL_SIZE * NSPL)
        self.fill(LIN, 8)
        self.fill(STOPS, 4 * NSTOP)
        self.fill(KNEES, 8 * NKNEE)
        self.fill(GRAPH, 8)
        self.fill(ARENA, ARENA_SIZE)
        self.heap = ARENA + ARENA_GUARD
        self.blocks = {}
        self.elevs, self.ne = [0], 0
        self.cons, self.nc = [(0, 0, 0, 0)], 0

    # ---- the stubs -------------------------------------------------------

    def s_malloc(self, em):
        size, line, align = s32(em.reg[4]), s32(em.reg[6]), s32(em.reg[7])
        p = (self.heap + 15) & ~15
        self.heap = p + size
        if self.heap > ARENA + ARENA_SIZE:
            raise SystemExit("model arena full")
        tag = "m%d" % len(self.blocks)
        self.blocks[p] = tag
        self.emit("  malloc %d %s %d %d -> %s"
                  % (size, self.cstr(em.reg[5] & M32), line, align, tag))
        return p

    def s_free(self, em):
        self.emit("  free %s" % self.name(em.reg[4]))

    def s_bbox(self, em):
        vel = em.reg[6] & M32
        self.emit("  bbox %s pos %s r %s vel %s"
                  % (self.name(em.reg[4]), self.vec3(em.reg[5] & M32),
                     fx(em.fpr[12]), self.vec3(vel) if vel else "null"))

    def s_elev(self, em):
        args = "".join("1" if em.reg[r] & M32 else "0" for r in (6, 7, 8))
        v = self.elevs[self.ne % len(self.elevs)]
        self.ne += 1
        self.emit("  elev %s pt %s args %s -> %s"
                  % (self.name(em.reg[4]), self.vec3(em.reg[5] & M32), args,
                     fx(v)))
        em.fpr[0] = v

    def s_constrain(self, em):
        to = em.reg[8] & M32
        r, dx, dy, dz = self.cons[self.nc % len(self.cons)]
        self.nc += 1
        self.emit("  constrain %s type %d two %d from %s to %s dist %s"
                  " lift %s -> %d"
                  % (self.name(em.reg[4]), s32(em.reg[5]), s32(em.reg[6]),
                     self.vec3(em.reg[7] & M32), self.vec3(to),
                     fx(em.fpr[12]), fx(em.fpr[13]), r))
        for i, d in enumerate((dx, dy, dz)):
            a = to + 4 * i
            self.e.put32(a, f_to_bits(f32(bits_f(self.w(a)) + bits_f(d))))
        return r

    # ---- the dumps -------------------------------------------------------

    def vec3(self, a):
        return " ".join(fx(self.w(a + 4 * i)) for i in range(3))

    def dump_spline(self, j, lanes):
        a = spl_at(j)
        w = self.w
        self.emit("  s%d buf %d n %d type %d pts %s arr %s dirty %d tab %d"
                  " len %s cal %s"
                  % (j, s32(w(a)), s32(w(a + 4)), s32(w(a + 8)),
                     self.name(w(a + 12)), self.name(w(a + 16)),
                     s32(w(a + 20)), s32(w(a + 24)), fx(w(a + 32)),
                     self.name(w(a + 44))))
        p, n = w(a + 12), s32(w(a + 4))
        if p not in self.blocks or n < 0 or n > 1024:
            return
        for i in range(-1, n + 1):
            q = p + 16 * i
            if lanes == 4:
                self.emit("    s%d %d %s %s" % (j, i, self.vec3(q),
                                               fx(w(q + 12))))
            else:
                self.emit("    s%d %d %s" % (j, i, self.vec3(q)))

    # ---- the ops ---------------------------------------------------------

    def call(self, fn, *args, **f):
        e = self.e
        for i, v in f.items():
            e.fpr[int(i[1:])] = v & M32
        return e.call(fn, *args, limit=LIMIT)

    def op(self, t):
        e = self.e
        c = t[0]
        x = lambda i: int(t[i], 16)
        if c == "t":
            a = TRPS + TRP_SIZE * int(t[1])
            for k, off in enumerate((0, 4, 8, 12, 16, 32, 36)):
                e.put32(a + off, x(2 + k))
        elif c == "p":
            a = RPTS + RPT_SIZE * int(t[1])
            e.put32(a + 4, TRPS + TRP_SIZE * int(t[2]))
            e.put32(a + 8, x(3))
            e.put32(a + 12, x(4))
            e.put32(a + 20, x(5))
        elif c == "r":
            e.put32(ROUTE, 0 if int(t[4]) else RPTS)
            e.put32(ROUTE + 4, int(t[1]))
            e.put32(ROUTE + 16, x(2))
            e.put32(ROUTE + 20, x(3))
        elif c == "E":
            n = int(t[1])
            self.elevs = [int(v, 16) for v in t[2:2 + n]]
            self.ne = 0
        elif c == "X":
            n = int(t[1])
            self.cons = []
            for i in range(n):
                q = t[2 + 4 * i:6 + 4 * i]
                self.cons.append((int(q[0]), int(q[1], 16), int(q[2], 16),
                                  int(q[3], 16)))
            self.nc = 0
        elif c == "l":
            e.put32(LIN, x(1))
            e.put32(LIN + 4, x(2))
        elif c == "a":
            j, typ, buf = int(t[1]), int(t[2]), int(t[3])
            self.fill(spl_at(j), SPL_SIZE)
            self.call(SPL_ALLOC, spl_at(j), typ, buf, 16384)
            self.dump_spline(j, 4)
        elif c == "c":
            j, n = int(t[1]), int(t[2])
            p = self.w(spl_at(j) + 12)
            for i in range(4 * n):
                e.put32(p + 4 * i, x(3 + i))
            e.put32(spl_at(j) + 4, n)
        elif c == "y":
            e.put32(spl_at(int(t[1])) + 8, int(t[2]))
        elif c == "M":
            m = int(t[1])
            self.call(MAKE, ROUTE, TC,
                      spl_at(0) if m & 1 else 0, spl_at(1) if m & 2 else 0,
                      spl_at(2) if m & 4 else 0, LIN if m & 8 else 0)
            self.emit("  route n %d dist %s off %s"
                      % (s32(self.w(ROUTE + 4)), fx(self.w(ROUTE + 16)),
                         fx(self.w(ROUTE + 20))))
            for j in range(3):
                self.dump_spline(j, 3)
        elif c == "H":
            r, s, i = int(t[1]), int(t[2]), int(t[3])
            self.call(GAP_AT, spl_at(r), spl_at(s), i, f12=x(4))
            self.dump_spline(s, 4)
        elif c == "G":
            r, s, i = int(t[1]), int(t[2]), int(t[3])
            self.call(GAP, spl_at(r), spl_at(s), i)
            self.dump_spline(s, 4)
        elif c == "D":
            j, nul, n = int(t[1]), int(t[3]), int(t[4])
            for i in range(min(max(n, 0), NSTOP)):
                e.put32(STOPS + 4 * i, x(5 + i))
            self.call(DOWN, spl_at(j), 0 if nul else STOPS, n, f12=x(2))
            self.dump_spline(j, 4)
        elif c == "S":
            self.call(SLOPE, spl_at(int(t[1])), f12=x(2))
            self.dump_spline(int(t[1]), 4)
        elif c == "W":
            j, i = int(t[1]), int(t[2])
            for k in range(4):
                e.put32(VEC + 4 * k, x(3 + k))
            self.call(SETCP, spl_at(j), i, VEC)
            self.dump_spline(j, 4)
        elif c == "K":
            self.call(SEEK, f12=x(1), f13=x(2), f14=x(3))
            self.emit("  seek %s" % fx(e.fpr[0]))
        elif c == "I":
            n = int(t[1])
            for i in range(2 * n):
                e.put32(KNEES + 4 * i, x(2 + i))
            e.put32(GRAPH, KNEES)
            e.put32(GRAPH + 4, n)
            m = int(t[2 + 2 * n])
            for i in range(m):
                y = x(3 + 2 * n + i)
                self.call(INVERSE, GRAPH, f12=y)
                self.emit("  inv %s -> %s" % (fx(y), fx(e.fpr[0])))
        elif c == "d":
            self.dump_spline(int(t[1]), 4)
        else:
            raise SystemExit("bad op %r" % (t,))

    def run(self, scenarios):
        for i, sc in enumerate(scenarios):
            self.emit("B %d" % i)
            self.reset()
            for ln in sc:
                op = ln.split()[0]
                if not (len(op) == 1 and op in "tpEXcl"):
                    self.emit("> " + ln[:40])
                self.op(ln.split())
        return self.out


def bits_f(w):
    return struct.unpack("<f", struct.pack("<I", w & M32))[0]


def image_facts():
    """What the port takes from the image without running it."""
    e = retail_model.emu(retail=True, ieee=True)
    u = e.u32
    jal = lambda t: 0x0c000000 | (t >> 2)
    out = []

    def callers(t):
        got = []
        for a in range(0x00100000, 0x002a0000, 4):
            if u(a) == jal(t):
                got.append(a)
        return got

    ms = callers(MAKE)
    out.append((ms == [0x00162190, 0x00174fe8],
                "MakeSplines called from %s (the mover's constructor and "
                "VisibleDrivingLine's)" % ", ".join("%08x" % a for a in ms)))
    # VisibleDrivingLine's: a3, t0 and t1 zero, the look spline alone.
    vdl = [u(0x00174fd4), u(0x00174fd8), u(0x00174fec)]
    out.append((vdl == [0x0000402d, 0x0000482d, 0x0000382d],
                "VisibleDrivingLine passes NULL eye splines and Linear: %s"
                % " ".join("%08x" % w for w in vdl)))
    ds = callers(DOWN)
    out.append((ds == [0x00166514, 0x00166cd0, 0x00166ce8, 0x00166d00],
                "DownSampleXY called from %s (0x00165a70's, then "
                "MakeSplines's three)" % ", ".join("%08x" % a for a in ds)))
    # MakeSplines's three pass a1 = a2 = 0 (move a1,zero before the jal,
    # move a2,zero in its slot), no stops.
    nost = all(u(a - 4) == 0x0000282d and u(a + 4) == 0x0000302d
               for a in ds[1:])
    out.append((nost, "MakeSplines's DownSampleXYs pass no stops"))
    inv = callers(INVERSE)
    out.append((inv == [0x00165528],
                "the Graph lookup the other way round called only from "
                "DownSampleXY: %s" % ", ".join("%08x" % a for a in inv)))
    # DownSampleXY's knees: five bVector2 constructed (the loop from 4),
    # the Graph at +48 and the coarse spline at +64.
    knees = (u(0x00165250), u(0x001651f8), u(0x00165200))
    out.append((knees == (0x24020004, 0x27d60030, 0x27d70040),
                "DownSampleXY: 5 knees, Graph at +48, coarse spline at +64: "
                "%08x %08x %08x" % knees))
    eps = (u(GP - 29948), u(GP - 29952))
    out.append((eps[0] == eps[1] == 0x358637bd,
                "the lookup's epsilon is GetValue's: %08x %08x" % eps))
    consts = [u(GP + o) for o in (-30692, -30684, -30680)]
    out.append((consts == [0x3c257eb5] * 3,
                "the three 1/99 steps: %s" % " ".join("%08x" % c
                                                     for c in consts)))
    return out


# ================================================================ the build


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


def build_harness(tmp, name="previewspline_test"):
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


def M(name, before, after, rel=PSC):
    return (name, rel, before, after)


MUTATIONS = [
    # The constants.
    M("c-step", "#define PS_STEP          10.0f",
      "#define PS_STEP          10.5f"),
    M("c-box", "#define PS_WALK_BOX      12.0f",
      "#define PS_WALK_BOX      12.5f"),
    M("c-look", "#define PS_LOOK_HEIGHT   1.5f",
      "#define PS_LOOK_HEIGHT   1.25f"),
    M("c-fwd", "#define PS_FORWARD_RISE  0.5f",
      "#define PS_FORWARD_RISE  0.75f"),
    M("c-back", "#define PS_BACKWARD_RISE 10.0f",
      "#define PS_BACKWARD_RISE 9.0f"),
    M("c-seek", "#define PS_SEEK_STEP     4.0f",
      "#define PS_SEEK_STEP     3.0f"),
    M("c-samples", "#define PS_SAMPLES       100",
      "#define PS_SAMPLES       99"),
    M("c-sstep", "#define PS_SAMPLE_STEP   0.01010101f",
      "#define PS_SAMPLE_STEP   0.0101f"),
    M("c-sbox", "#define PS_SAMPLE_BOX    10.7f",
      "#define PS_SAMPLE_BOX    10.5f"),
    M("c-slope", "#define PS_MAX_SLOPE     0.4f",
      "#define PS_MAX_SLOPE     0.45f"),
    M("c-down", "#define PS_DOWN_SAMPLE   0.3333f",
      "#define PS_DOWN_SAMPLE   0.3f"),
    M("c-gap", "#define PS_GAP_START     1000.0f",
      "#define PS_GAP_START     5.0f"),
    M("c-eps", "#define GRAPH_INVERSE_EPSILON 9.99999997e-07f",
      "#define GRAPH_INVERSE_EPSILON 1e-5f"),
    # The spline's last parameter.
    M("last-loop", "return (float)s->NumControlPoints;",
      "return (float)(s->NumControlPoints - 1);"),
    M("last-clamp",
      "if (s->Type == SPLINE_CLAMP || s->Type == SPLINE_EXTRAPOLATE)",
      "if (s->Type == SPLINE_EXTRAPOLATE)"),
    M("last-ext",
      "if (s->Type == SPLINE_CLAMP || s->Type == SPLINE_EXTRAPOLATE)",
      "if (s->Type == SPLINE_CLAMP)"),
    M("last-else", "    return 0.0f;" + NL + "}", "    return 1.0f;" + NL + "}"),
    # MakeSplines's walk.
    M("w-null", "if (pr->pPoints == NULL)" + NL + "        return;",
      "if (pr->nPoints == 0)" + NL + "        return;"),
    M("w-n", "while (i < pr->nPoints - 1 && next < pr->fDistance) {",
      "while (i < pr->nPoints && next < pr->fDistance) {"),
    M("w-end", "while (i < pr->nPoints - 1 && next < pr->fDistance) {",
      "while (i < pr->nPoints - 1 && next <= pr->fDistance) {"),
    M("w-along", "&pos, along," + NL, "&pos, next," + NL),
    M("w-off", NL + "                                            pr->fOffset);",
      NL + "                                            0.0f);"),
    M("w-box", "topology_set_interest_bbox3(tc, &pos, PS_WALK_BOX, NULL);",
      "topology_set_interest_bbox3(tc, &pos, PS_SAMPLE_BOX, NULL);"),
    M("w-look", "+ PS_LOOK_HEIGHT;" + NL + "        if (look != NULL)",
      "+ PS_FORWARD_RISE;" + NL + "        if (look != NULL)"),
    M("w-fwd", "eye.z = pos.z + PS_FORWARD_RISE;" + NL + "            eye.pad",
      "eye.z = pos.z + PS_BACKWARD_RISE;" + NL + "            eye.pad"),
    M("w-back", "eye.z = pos.z + PS_BACKWARD_RISE;" + NL + "            eye.pad",
      "eye.z = pos.z + PS_FORWARD_RISE;" + NL + "            eye.pad"),
    M("w-fwd-y", "eye.y = pos.y;" + NL + "            eye.z = pos.z + "
      "PS_FORWARD_RISE;",
      "eye.y = pos.x;" + NL + "            eye.z = pos.z + PS_FORWARD_RISE;"),
    M("w-dist", "dist = next;", "dist = along;"),
    M("w-in-end", "while (next < pr->fDistance && i < pr->nPoints - 1",
      "while (i < pr->nPoints - 1"),
    M("w-in-n", "i < pr->nPoints - 1" + NL + "               &&",
      "i < pr->nPoints - 2" + NL + "               &&"),
    M("w-in-len", "&& pr->pPoints[i].fLength < along) {",
      "&& pr->pPoints[i + 1].fLength < along) {"),
    M("w-in-sub", "along -= pr->pPoints[i].fLength;",
      "along -= PS_STEP;"),
    M("w-gap", "pr->fOffset += pr->pPoints[i].fRouteGap;",
      "pr->fOffset -= pr->pPoints[i].fRouteGap;"),
    M("w-gap-i", "i++;" + NL + "            pr->fOffset += pr->pPoints[i]"
      ".fRouteGap;",
      "pr->fOffset += pr->pPoints[i].fRouteGap;" + NL + "            i++;"),
    M("w-seek", "preview_linear_seek(pr->fOffset, pr->pPoints[i].fOffset,",
      "preview_linear_seek(pr->pPoints[i].fOffset, pr->fOffset,"),
    M("w-fdist", "pr->fDistance = dist;", "pr->fDistance = next;"),
    # The walls.
    M("p-cond",
      "if (look != NULL && eyeForward != NULL && eyeBackward != NULL) {",
      "if (look != NULL && eyeForward != NULL) {"),
    M("p-order", "float t = spline_last(look) * (float)k * PS_SAMPLE_STEP;",
      "float t = spline_last(look) * ((float)k * PS_SAMPLE_STEP);"),
    M("p-box", "topology_set_interest_bbox3(tc, &pos, PS_SAMPLE_BOX, NULL);",
      "topology_set_interest_bbox3(tc, &pos, PS_WALK_BOX, NULL);"),
    M("p-look", "+ PS_LOOK_HEIGHT;" + NL + "            spline_get_point",
      "+ PS_FORWARD_RISE;" + NL + "            spline_get_point"),
    M("p-fwd", "eye.z = pos.z + PS_FORWARD_RISE;" + NL
      + "            zone_constrain",
      "eye.z = pos.z + PS_BACKWARD_RISE;" + NL + "            zone_constrain"),
    M("p-back", "eye.z = pos.z + PS_BACKWARD_RISE;" + NL
      + "            zone_constrain",
      "eye.z = pos.z + PS_FORWARD_RISE;" + NL + "            zone_constrain"),
    M("p-ways", "&eye, 1, 0);" + NL + "            gapForward",
      "&eye, 0, 0);" + NL + "            gapForward"),
    M("p-sides", "&eye, 1, 0);" + NL + "            gapBackward",
      "&eye, 1, 1);" + NL + "            gapBackward"),
    M("p-gapf", "gapForward[k] = eye.z - pos.z;", "gapForward[k] = eye.z;"),
    M("p-gapb", "gapBackward[k] = eye.z - pos.z;",
      "gapBackward[k] = pos.z - eye.z;"),
    M("p-spline", "spline_get_point(eyeBackward, &eye, t);",
      "spline_get_point(eyeForward, &eye, t);"),
    M("p-lo", "for (j = at - 1; j < at + 3; j++)" + NL
      + "                preview_enforce_height_gap_at(look, eyeForward,",
      "for (j = at; j < at + 3; j++)" + NL
      + "                preview_enforce_height_gap_at(look, eyeForward,"),
    M("p-hi", "for (j = at - 1; j < at + 3; j++)" + NL
      + "                preview_enforce_height_gap_at(look, eyeBackward,",
      "for (j = at - 1; j < at + 2; j++)" + NL
      + "                preview_enforce_height_gap_at(look, eyeBackward,"),
    M("p-which", "gapBackward[k]);", "gapForward[k]);"),
    # The ends of the flight.
    M("e-cond", "if (eyeParam != NULL && look != NULL && eyeForward != NULL)",
      "if (eyeParam != NULL && eyeForward != NULL)"),
    M("e-first", "linear_get_value(eyeParam, 0.0f)",
      "linear_get_value(eyeParam, 0.5f)"),
    M("e-last", "linear_get_value(eyeParam, 1.0f)",
      "linear_get_value(eyeParam, 0.9f)"),
    M("e-spline", "int32_t first = ee_trunc_w(spline_last(eyeForward)",
      "int32_t first = ee_trunc_w(spline_last(look)"),
    M("e-fwd", "preview_enforce_height_gap(look, eyeForward, last);",
      "preview_enforce_height_gap(look, eyeForward, first);"),
    M("e-back", "preview_enforce_height_gap(look, eyeBackward, first);",
      "preview_enforce_height_gap(look, eyeBackward, last);"),
    # The slopes and the smoothing.
    M("s-fwd", "preview_enforce_maximum_slope(eyeForward, PS_MAX_SLOPE);",
      ";"),
    M("s-back", "preview_enforce_maximum_slope(eyeBackward, PS_MAX_SLOPE);",
      ";"),
    M("d-look", "preview_down_sample_xy(look, PS_DOWN_SAMPLE, NULL, 0);",
      ";"),
    M("d-fwd", "preview_down_sample_xy(eyeForward, PS_DOWN_SAMPLE, NULL, 0);",
      ";"),
    M("d-back",
      "preview_down_sample_xy(eyeBackward, PS_DOWN_SAMPLE, NULL, 0);",
      ";"),
    # LinearSeek.
    M("k-abs", "step = fabsf(d);", "step = d;"),
    M("k-down", "return from - step;", "return from + step;"),
    M("k-up", "return from + step;", "return to;"),
    M("k-same", "    return from;" + NL + "}", "    return to;" + NL + "}"),
    # EnforceHeightGap with a gap.
    M("g-lo", "if (i < 0 || !(i < s->NumControlPoints))",
      "if (i < -1 || !(i < s->NumControlPoints))"),
    M("g-hi", "if (i < 0 || !(i < s->NumControlPoints))",
      "if (i < 0 || !(i <= s->NumControlPoints))"),
    M("g-cmp", "if (gap < p.z - below) {", "if (gap > p.z - below) {"),
    M("g-ref", "below = ref->pControlPoints[i].z;",
      "below = ref->pControlPoints[i].y;"),
    M("g-set", "p.z = below + gap;", "p.z = below - gap;"),
    # EnforceHeightGap over a span.
    M("h-half", "if (i < s->NumControlPoints / 2) {",
      "if (i <= s->NumControlPoints / 2) {"),
    M("h-lo0", "        lo = 0;", "        lo = 1;"),
    M("h-hi0", "hi = i + 2;", "hi = i + 1;"),
    M("h-lo1", "lo = i - 2;", "lo = i - 1;"),
    M("h-hi1", "hi = s->NumControlPoints - 1;", "hi = s->NumControlPoints;"),
    M("h-cmp", "if (b.z - a.z < gap)", "if (a.z - b.z < gap)"),
    M("h-ref", "spline_get_point(ref, &a, (float)j);",
      "spline_get_point(s, &a, (float)j);"),
    M("h-hold", "for (j = lo; j <= hi; j++)" + NL
      + "        preview_enforce_height_gap_at",
      "for (j = lo; j < hi; j++)" + NL
      + "        preview_enforce_height_gap_at"),
    # bRound.
    M("r-down", "float down = x < t ? t - 1.0f : t;", "float down = t;"),
    M("r-half", "if (x - down < 0.5f)", "if (x - down <= 0.5f)"),
    M("r-up", "return t < x ? t + 1.0f : t;", "return t + 1.0f;"),
    M("r-ret", "        return down;", "        return t;"),
    # DownSampleXY.
    M("d-ceil", "if (whole < want)" + NL + "        whole += 1.0f;",
      "if (whole < want)" + NL + "        whole += 0.0f;"),
    M("d-top", "top = (float)(count - 1);", "top = (float)count;"),
    M("d-knee", "round_half_up(top * stops[i]",
      "(float)ee_trunc_w(top * stops[i]"),
    M("d-knee-last", NL + "                                               "
      "/ spline_last(s));",
      NL + "                                               / (float)n);"),
    M("d-knee-y", "knees[i + 1].y = stops[i];",
      "knees[i + 1].y = stops[0];"),
    M("d-close", "knees[numStops + 1].x = top;",
      "knees[numStops + 1].x = top + 1.0f;"),
    M("d-close-y", "knees[numStops + 1].y = spline_last(s);",
      "knees[numStops + 1].y = (float)n;"),
    M("d-knees", "graph_init(&g, knees, numStops + 2);",
      "graph_init(&g, knees, numStops + 1);"),
    M("d-sample", "graph_get_value(&g, (float)i));", "(float)i);"),
    M("d-type", "spline_init(&coarse, SPLINE_EXTRAPOLATE, count, pts, 0);",
      "spline_init(&coarse, SPLINE_CLAMP, count, pts, 0);"),
    M("d-t", "float t = (float)i * spline_last(s) / (float)(n - 1);",
      "float t = (float)i * (spline_last(s) / (float)(n - 1));"),
    M("d-inv", "spline_get_point(&coarse, &p, graph_get_inverse(&g, t));",
      "spline_get_point(&coarse, &p, graph_get_value(&g, t));"),
    M("d-z", "p.z = q.z;", "q.z = p.z;"),
    M("d-zt", "spline_get_point(s, &q, t);",
      "spline_get_point(s, &q, (float)i);"),
    M("d-loop", "for (i = 0; i < n; i++) {" + NL + "            float t",
      "for (i = 0; i < n - 1; i++) {" + NL + "            float t"),
    M("d-spare", "memset(&buf[0], 0, sizeof buf[0]);",
      "memset(&buf[0], 0x40, sizeof buf[0]);"),
    # EnforceMaximumSlope.
    M("m-from", "for (i = 1; i < n; i++) {" + NL + "        float dx",
      "for (i = 2; i < n; i++) {" + NL + "        float dx"),
    M("m-fcmp", "if (z < p[i].z)", "if (z > p[i].z)"),
    M("m-dist", "float z = p[i - 1].z + sqrtf(dx * dx + dy * dy) * slope;",
      "float z = p[i - 1].z + sqrtf(dx * dx + dx * dx) * slope;"),
    M("m-back-from", "for (i = n - 1; i > 0; i--) {",
      "for (i = n - 2; i > 0; i--) {"),
    M("m-back-cmp", "if (z < p[i - 1].z)", "if (z > p[i - 1].z)"),
    M("m-back-slope",
      "float z = p[i].z + sqrtf(dx * dx + dy * dy) * slope;",
      "float z = p[i].z + sqrtf(dx * dx + dy * dy) * 0.4f;"),
    # SetControlPoint.
    M("cp-lanes", "s->pControlPoints[i] = *v;",
      "s->pControlPoints[i].x = v->x;" + NL
      + "    s->pControlPoints[i].y = v->y;" + NL
      + "    s->pControlPoints[i].z = v->z;"),
    # The Graph lookup the other way round.
    M("i-n", "if (n < 2)", "if (n < 1)"),
    M("i-lo", "if (y <= p[0].y)", "if (y < p[0].y)"),
    M("i-hi", "if (p[n - 1].y <= y)", "if (p[n - 1].y < y)"),
    M("i-seg-lo", "if (p[i].y <= y && y < p[i + 1].y) {",
      "if (p[i].y < y && y < p[i + 1].y) {"),
    M("i-seg-hi", "if (p[i].y <= y && y < p[i + 1].y) {",
      "if (p[i].y <= y && y <= p[i + 1].y) {"),
    M("i-eps", "if (GRAPH_INVERSE_EPSILON < fabsf(dy))",
      "if (0.0f < fabsf(dy))"),
    M("i-lerp", "return p[i].x + (y - p[i].y) / dy * dx;",
      "return p[i].x + (y - p[i].y) * dx / dy;"),
    M("i-mid", "return p[i].x + dx * 0.5f;", "return p[i].x;"),
    M("i-fall", "fall-through." + NL + "    return p[0].y;",
      "fall-through." + NL + "    return p[0].x;"),
]

EQUIVALENT = {
    "d-spare": "the spare before the coarse points is read only by GetPoint "
               "on a one-point spline, through the extrapolation, with a "
               "weight of 0: any finite value there gives the same curve",
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    base = model_cached(sc)
    scdir = tempfile.TemporaryDirectory()
    scp = Path(scdir.name) / "scenarios.txt"
    scp.write_text(encode(sc))
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text().splitlines()
        if diff(base, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "previewspline_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs)
    scdir.cleanup()
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

    sc = script()
    lines = model_cached(sc)
    facts = image_facts()
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
        d.with_suffix(".image").write_text(
            NL.join(("   " if ok else "BAD") + " " + l for ok, l in facts)
            + NL)

    bad = [l for ok, l in facts if not ok]
    for l in bad:
        print("image: " + l)
    n = diff(lines, harness)
    ops = sum(len(s) for s in sc)
    print("image: %d facts, %d wrong" % (len(facts), len(bad)))
    print("%d scenarios, %d ops, %d lines, %d differ"
          % (len(sc), ops, len(harness), n))
    sys.exit(1 if (n or rc or bad) else 0)


if __name__ == "__main__":
    main()
