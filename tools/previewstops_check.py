#!/usr/bin/env python3
"""Cross-check 3DS Files/source/previewstops.c, the Zone Preview's stops,
against the retail image itself, run in mipsemu.

The model is the image. The stops (0x00165a70) run as shipped, and under
them the stop list's helpers (0x001657a0 to 0x00165a38), the jump table
at 0x002b1ff0, tCopManager's GetActiveRoadBlock and GetNumActiveRoadBlocks,
Race::GetRacingCar, Spline's GetPoint, GetDerivative and AddControlPoint,
Linear::GetValue, HeapSort and the list's destructors (0x00167748). Called
directly too: the approach parameter (0x0018a238) and its cosine
(0x0018a160), Linear::GetInverse (0x00190088), the topology's blocked
segment (0x00152690) and tSpikeStrip's centre (0x00241960). The harness
(tools/src/previewstops_test.c) runs the port over the same script, and
the two transcripts are diffed.

Stubs, printing what they are given on both sides: bMalloc hands out
blocks from a patterned arena and __builtin_delete prints the block;
Collision::IsTwoCarCollision (0x0021eb20) answers from the script;
TopologyCoordinate's SetInterestBBox (0x00136e00) and SegmentIntersects
(0x001525a0, answering from a scripted list); and DownSampleXY
(0x00165150), checked on its own (tools/previewspline_check.py). bMemSet
and bMemCpy are native, and HeapSort's holding slot is bMalloc'd and
freed unprinted, as the port's heap_sort mallocs its own. Everything else the stops read is laid out by the
script at retail's offsets: pCopManager at gp-15620 (its cops, the
pursuits' roadblocks and the spike strips), pCurrentWorld at gp-22120
(the helicopter, the race's cars and the collisions), the cars' racing
cars, and the splines and Linears.

Every structure starts from a byte pattern, so what a call leaves alone
shows. A float prints as its bits, a NaN as "nan", and a pointer by what
it is. Vectors print without their fourth lane: retail's stop centres
and spike centres start it from a stack word.

    python tools/previewstops_check.py
    python tools/previewstops_check.py --mutate [--only a,b]
    python tools/previewstops_check.py --dump out/previewstops
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

HARNESS = "tools/src/previewstops_test.c"
PSC = "3DS Files/source/previewstops.c"
SOURCES = [HARNESS, PSC] + ["3DS Files/source/" + f for f in (
    "spline.c", "average.c", "copmanager.c", "race.c", "trackroute.c",
    "replay.c", "trackpath.c", "bvector.c", "bmath.c", "quickspline.c",
    "p32.c", "bmathtab.c", "bmatrix.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
STOPS = 0x00165a70
APPROACH = 0x0018a238
COSINE = 0x0018a160
INVERSE = 0x00190088
BLOCKED = 0x00152690
CENTRE = 0x00241960
BMALLOC = 0x002577c0
DELETE = 0x00114e98
VEC_DELETE = 0x00114e90
BMEMSET = 0x00250340
BMEMCPY = 0x00250288
BFREE = 0x00257850
HSORT_FILE = 0x002b73c8           # HeapSort's bMalloc, its holding slot
TWO_CAR = 0x0021eb20
SET_BBOX3 = 0x00136e00
SEG_HITS = 0x001525a0
DOWNSAMPLE = 0x00165150
FUNK_EXISTS = 0x0025d220
EMATH_SINIT = 0x0011bf70
BMATRIX_SINIT = 0x0025afa8

G_MGR = GP - 15620                # pCopManager
G_WORLD = GP - 22120              # pCurrentWorld
G_RACE = GP - 22272               # pCurrentRace

# The layouts, retail's offsets.
MGR_NCOPS, MGR_COPS, MGR_PURSUITS, MGR_SPIKES = 8, 16, 44, 80
NSLOT = 7
COP_CAR, COP_STATE = 4, 16
CAR_RACING, CAR_GEOM, CAR_POS, CAR_WHEELS = 28, 80, 96, 956
RC_PLACE = 10
RB_COPS, RB_INDEX = 0, 104
PUR_RB = 20
SPK_ID, SPK_N, SPK_POS, SPK_STRIDE = 24, 40, 128, 112
HELI_PLAN, HELI_POS = 728, 832
W_COLL, W_HELI, W_AI, W_COP, W_CARS = 16, 24, 32, 36, 44
COLL_POINT = 32

# Where the script's world lives.
MGR = 0x01000000
COPS = 0x01001000
COP_SIZE = 0x40
NCOP = 12
CARS = 0x01002000
CAR_SIZE = 0x400
NCAR = 14
RCARS = 0x01006000
RC_SIZE = 0x20
RBS = 0x01007000
RB_SIZE = 0x80
NRB = 8
PURS = 0x01008000
PUR_SIZE = 0x20
NPUR = 8
SPIKES = 0x01009000
SPK_SIZE = 0x900
NSPIKE = 6
MAXELEM = 20
HELI = 0x0100d000
HELI_SIZE = 0x400
WORLD = 0x0100e000
WORLD_SIZE = 0x100
COLLS = 0x0100e400
COLL_SIZE = 0x40
NCOLL = 8
RACE = 0x0100e800
TC = 0x0100f000
ROUTE = 0x0100f100
EYE = 0x0100f200
LOOK = 0x0100f240
AHEAD = 0x0100f280
SPL_SIZE = 48
LIN_E = 0x0100f300
LIN_L = 0x0100f310
LIN_X = 0x0100f320
VA = 0x0100f340
VB = 0x0100f360
VOUT = 0x0100f380
STOPSA = 0x0100f400
NSTOPS = 8
EYEPTS = 0x01010000
LOOKPTS = 0x01010400
AHEADPTS = 0x01010800
NPTS = 64
ARENA = 0x01020000
ARENA_SIZE = 0x40000

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


def cop_at(i):
    return COPS + COP_SIZE * i


def car_at(i):
    return CARS + CAR_SIZE * i


def rc_at(i):
    return RCARS + RC_SIZE * i


def rb_at(i):
    return RBS + RB_SIZE * i


def pur_at(i):
    return PURS + PUR_SIZE * i


def spike_at(i):
    return SPIKES + SPK_SIZE * i


def coll_at(i):
    return COLLS + COLL_SIZE * i


# ============================================================ the scenarios


def vec(*xs):
    return " ".join(h(x) for x in xs)


def road(rnd, n, start, head, step, lift):
    """`n` points about `step` apart along a road that bends and climbs a
    little, `lift` above it."""
    x, y, z = start
    bend = rnd.uniform(-0.1, 0.1)
    climb = rnd.uniform(-0.06, 0.06)
    pts = []
    for i in range(n):
        pts.append((x, y, z + lift, rnd.choice((0.0, 1.0))))
        s = step * rnd.uniform(0.9, 1.1)
        x += math.cos(head) * s
        y += math.sin(head) * s
        z += climb * s + rnd.uniform(-0.2, 0.2)
        head += bend + rnd.uniform(-0.04, 0.04)
    return pts


def spline_line(op, typ, pts):
    return "%s %d %d %s" % (op, typ, len(pts),
                            " ".join(vec(*p) for p in pts))


def beside(rnd, pts, side, along=None):
    """A point `side` off the road (left or right) at a fraction `along`
    of it, a little above or below."""
    n = len(pts)
    u = rnd.uniform(0.0, 1.0) if along is None else along
    i = min(int(u * (n - 1)), n - 2)
    a, b = pts[i], pts[i + 1]
    k = u * (n - 1) - i
    x = a[0] + (b[0] - a[0]) * k
    y = a[1] + (b[1] - a[1]) * k
    z = a[2] + (b[2] - a[2]) * k
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = math.hypot(dx, dy) or 1.0
    return (x - dy / d * side, y + dx / d * side,
            z + rnd.uniform(-3.0, 1.0), rnd.uniform(-2.0, 2.0))


def near(rnd, p, r):
    return (p[0] + rnd.uniform(-r, r), p[1] + rnd.uniform(-r, r),
            p[2] + rnd.uniform(-r / 4, r / 4), rnd.uniform(-2.0, 2.0))


def preview_lins(rnd):
    """The mover's Linears, as its constructor makes them."""
    dist = rnd.uniform(150.0, 600.0)
    out = f32(dist * 0.009)
    infrac = f32(1.5 / (out + 1.5))
    lead = f32(20.0 / dist)
    em = f32(f32(1.0 - lead) - infrac)
    lb = f32(infrac + lead)
    lm = f32(1.0 - lb)
    return ("lin E %s" % vec(em, infrac), "lin L %s" % vec(lm, lb))


def course(rnd, ne=None, nl=None, types=(2, 2)):
    """An eye-forward and a look spline along one road, and the Linears."""
    start = (rnd.uniform(-500, 500), rnd.uniform(-500, 500),
             rnd.uniform(-5, 20))
    head = rnd.uniform(-math.pi, math.pi)
    ne = ne or rnd.randint(12, 30)
    nl = nl or rnd.randint(12, 40)
    span = rnd.uniform(150.0, 400.0)
    eye = road(rnd, ne, start, head, span / (ne - 1), 4.0)
    look = road(rnd, nl, start, head, span / (nl - 1), 1.0)
    lines = [spline_line("eye", types[0], eye),
             spline_line("look", types[1], look)]
    lines += preview_lins(rnd)
    return eye, look, lines


def car_line(k, geom, pos, wheels, place):
    return "car %d %s %s %d %d" % (k, vec(*geom), vec(*pos), wheels, place)


def s_inverse(rnd):
    sc = []
    for m in (0.0, 0.001, -0.001, f32(0.001) * 1.0000001, 0.00099999,
              -0.0010001, 1e-30, -0.0, 2.0, -0.5):
        sc.append("inv %s" % vec(m, rnd.uniform(-2, 2), rnd.uniform(-3, 3)))
    for _ in range(20):
        sc.append("inv %s" % vec(rnd.uniform(-2, 2), rnd.uniform(-2, 2),
                                 rnd.uniform(-3, 3)))
    return sc


def s_centre(rnd):
    sc = []
    for i, m in enumerate((0, 1, 2, 3, 7, MAXELEM)):
        els = [near(rnd, (rnd.uniform(-200, 200), rnd.uniform(-200, 200),
                          0.0), 6.0) for _ in range(m)]
        sc.append("spike %d %d %s" % (rnd.randint(-1, 9), m,
                                      " ".join(vec(*p) for p in els)))
    for i in range(6):
        sc.append("centre %d" % i)
    return sc


def s_block(rnd):
    sc = []
    answers = [rnd.choice((0, 0, 0, 1)) for _ in range(60)]
    sc.append("topo " + " ".join(str(a) for a in answers))
    for length in (0.0, 5.0, 29.99, 30.0, 30.0001, 59.99, 60.0, 90.0,
                   121.0, 300.0):
        a = (rnd.uniform(-300, 300), rnd.uniform(-300, 300),
             rnd.uniform(-10, 10), rnd.uniform(-2, 2))
        th = rnd.uniform(-math.pi, math.pi)
        b = (a[0] + math.cos(th) * length, a[1] + math.sin(th) * length,
             a[2], rnd.uniform(-2, 2))
        sc.append("block %s %s" % (vec(*a), vec(*b)))
    sc.append("topo " + " ".join(str(rnd.choice((0, 1))) for _ in range(40)))
    for _ in range(14):
        a = (rnd.uniform(-300, 300), rnd.uniform(-300, 300),
             rnd.uniform(-10, 10), rnd.uniform(-2, 2))
        b = near(rnd, a, rnd.choice((20.0, 60.0, 150.0)))
        sc.append("block %s %s" % (vec(*a), vec(*b)))
    # Whole-number ends an exact 30, 60 or 90 apart along an axis.
    sc.append("topo " + " ".join("0" for _ in range(40)))
    for length in (30.0, 60.0, 90.0, 29.0, 31.0):
        for axis in range(3):
            a = [float(rnd.randint(-200, 200)) for _ in range(3)]
            b = list(a)
            b[axis] += length * rnd.choice((1, -1))
            sc.append("block %s %s" % (vec(*(a + [0.0])),
                                       vec(*(b + [1.0]))))
    return sc


def s_approach(rnd, typ):
    sc = []
    eye, look, lines = course(rnd, types=(typ, 2))
    sc += lines
    for _ in range(10):
        p = beside(rnd, eye, rnd.uniform(-50, 50))
        sc.append("cosine %s %s" % (h(rnd.uniform(-1.0, len(eye))),
                                    vec(*p)))
    for _ in range(14):
        p = beside(rnd, eye, rnd.uniform(-60, 60),
                   along=rnd.uniform(-0.2, 1.2))
        tgt = rnd.choice((-0.6, -0.6, rnd.uniform(-1.0, 1.0)))
        tol = rnd.choice((0.01, 0.01, 0.0, 0.5, 1e-6))
        sc.append("appr %s %s" % (vec(tgt, tol), vec(*p)))
    return sc


def s_approach_short(rnd):
    """Eye splines of one, two and three points."""
    sc = []
    for n in (1, 2, 3):
        eye = road(rnd, n, (0.0, 0.0, 0.0), rnd.uniform(-3, 3), 30.0, 4.0)
        sc.append(spline_line("eye", 2, eye))
        for _ in range(4):
            p = beside(rnd, eye if n > 1 else eye * 2, rnd.uniform(-30, 30),
                       along=rnd.uniform(-0.5, 1.5))
            sc.append("appr %s %s" % (vec(-0.6, 0.01), vec(*p)))
    return sc


def cops_world(rnd, eye):
    """A cop manager with cops along the road, its roadblocks, their
    pursuits, spike strips and a helicopter."""
    sc = ["mgr 1"]
    ncop = rnd.randint(0, NSLOT)
    sc.append("ncops %d" % ncop)
    order = list(range(NCOP))
    rnd.shuffle(order)
    for i in range(NSLOT):
        o = order[i] if rnd.random() < 0.85 else -1
        sc.append("slot %d %d" % (i, o))
    spots = [beside(rnd, eye, rnd.uniform(-45, 45)) for _ in range(4)]
    for c in range(NCOP):
        state = rnd.choice((0, 1, 2, 3, 4, 4, 4, 5, 6, 7, 8, 9, -1))
        sc.append("cop %d %d %d" % (c, c, state))
        base = rnd.choice(spots)
        g = near(rnd, base, rnd.choice((4.0, 12.0, 30.0)))
        sc.append(car_line(c, g, near(rnd, g, 1.0), rnd.randint(0, 4),
                           rnd.randint(0, 8)))
    nrb = rnd.randint(0, NRB)
    for r in range(nrb):
        a = rnd.choice(range(-1, NCOP))
        b = rnd.choice(range(-1, NCOP))
        sc.append("rb %d %d %d %d" % (r, a, b, rnd.randint(0, 3)))
    for _ in range(rnd.randint(0, NPUR)):
        sc.append("pur %d" % (rnd.randint(-1, nrb - 1) if nrb else -1))
    for _ in range(rnd.randint(0, 3)):
        base = beside(rnd, eye, rnd.uniform(-30, 30))
        m = rnd.randint(0, 6)
        els = [near(rnd, base, 5.0) for _ in range(m)]
        sc.append("spike %d %d %s" % (rnd.randint(0, 3), m,
                                      " ".join(vec(*p) for p in els)))
    if rnd.random() < 0.7:
        sc.append("heli 1 %d %s" % (rnd.choice((0, 1, 2, 3, 4, 5, 6, -1)),
                                    vec(*beside(rnd, eye,
                                                rnd.uniform(-40, 40)))))
    return sc


def race_world(rnd, eye):
    """No cop manager: the race's cars and the collisions."""
    sc = ["mgr 0"]
    ai = rnd.randint(0, 4)
    cop = rnd.randint(ai, NCAR)
    table = list(range(NCAR))
    rnd.shuffle(table)
    sc.append("world %d %d %s" % (ai, cop, " ".join(str(t) for t in table)))
    places = list(range(1, NCAR + 1))
    rnd.shuffle(places)
    for k in range(NCAR):
        place = places[k] if rnd.random() < 0.8 else rnd.choice((1, 2))
        g = beside(rnd, eye, rnd.uniform(-40, 40))
        sc.append(car_line(k, near(rnd, g, 1.0), g,
                           rnd.choice((0, 2, 4, 4, 4)), place))
    for _ in range(rnd.randint(0, 4)):
        sc.append("coll %s %d" % (vec(*beside(rnd, eye,
                                              rnd.uniform(-40, 40))),
                                  rnd.choice((0, 1, 1))))
    sc.append("topo " + " ".join(str(rnd.choice((0, 0, 0, 1)))
                                 for _ in range(60)))
    return sc


def s_cops(rnd):
    eye, look, lines = course(rnd)
    sc = lines + cops_world(rnd, eye)
    for _ in range(rnd.randint(1, 3)):
        sc.append("find %d" % rnd.choice((0, 1, 2, 3, 4, 4, 4, 6)))
    return sc


def s_race(rnd):
    eye, look, lines = course(rnd)
    sc = lines + race_world(rnd, eye)
    for _ in range(rnd.randint(1, 2)):
        sc.append("find %d" % rnd.choice((1, 2, 4, 4, 6)))
    return sc


def s_seen(rnd):
    """More roadblock cops behind one spike strip than the six seen."""
    eye, look, lines = course(rnd)
    sc = lines + ["mgr 1", "ncops 7"]
    for i in range(NSLOT):
        sc.append("slot %d %d" % (i, i + 4))
    for c in range(NCOP):
        sc.append("cop %d %d %d" % (c, c, 4))
        g = beside(rnd, eye, rnd.uniform(-30, 30))
        sc.append(car_line(c, g, g, 4, 3))
    for r in range(5):
        sc.append("rb %d %d %d 2" % (r, 2 * r, 2 * r + 1))
        sc.append("pur %d" % r)
    sc.append("rb 5 1 11 1")
    sc.append("pur 5")
    base = beside(rnd, eye, 10.0)
    sc.append("spike 2 2 %s %s" % (vec(*near(rnd, base, 2.0)),
                                   vec(*near(rnd, base, 2.0))))
    sc.append("find 4")
    return sc


def one_road(rnd, n=24, typ=2, nl=None, bend=True):
    """An eye spline of `n` points 12 apart along a road and a look spline
    of `nl` 3 below it, and Linears that map the preview's time straight
    through: a stop between the ends lands."""
    start = (rnd.uniform(-500, 500), rnd.uniform(-500, 500),
             rnd.uniform(-5, 20))
    head = rnd.uniform(-math.pi, math.pi)
    if bend:
        eye = road(rnd, n, start, head, 12.0, 4.0)
    else:
        eye = [(start[0] + math.cos(head) * 12.0 * i,
                start[1] + math.sin(head) * 12.0 * i, start[2] + 4.0, 0.0)
               for i in range(n)]
    nl = nl or n
    look = []
    for j in range(nl):
        u = j * (n - 1) / (nl - 1)
        i = min(int(u), n - 2)
        k = u - i
        a, b = eye[i], eye[i + 1]
        look.append((a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k,
                     a[2] + (b[2] - a[2]) * k - 3.0, 0.0))
    return eye, [spline_line("eye", typ, eye), spline_line("look", typ, look),
                 "lin E %s" % vec(1.0, 0.0), "lin L %s" % vec(1.0, 0.0)]


def s_pairs(rnd):
    """Roadblock cops' cars just under and over 10 apart."""
    eye, lines = one_road(rnd)
    sc = lines + ["mgr 1", "ncops 7"]
    for i in range(7):
        sc.append("slot %d %d" % (i, i))
    gaps = (9.99, 10.0, 3.0, 25.0)
    for r in range(4):
        a = beside(rnd, eye, (-8.0, 8.0)[r % 2], along=0.2 + 0.2 * r)
        a = (float(round(a[0])), float(round(a[1])), float(round(a[2])),
             0.0)
        b = (a[0] + gaps[r], a[1], a[2], 1.0)
        c = beside(rnd, eye, rnd.uniform(-20, 20), along=0.5)
        for k, g in ((2 * r, a), (2 * r + 1, b)):
            sc.append("cop %d %d 4" % (k, k))
            sc.append(car_line(k, g, c, 4, 3))
        sc.append("rb %d %d %d %d" % (r, 2 * r, 2 * r + 1, r))
        sc.append("pur %d" % r)
    sc.append("find 6")
    sc.append("ncops 2")
    sc.append("slot 0 1")
    sc.append("slot 1 3")
    sc.append("rb 0 -1 1 0")
    sc.append("find 4")
    return sc


def s_rb_twice(rnd):
    """A cop in two active roadblocks: the first, its partner far, takes
    it; the second's cop, its partner the first cop and near, makes a
    point of its own between them."""
    eye, lines = one_road(rnd)
    sc = lines + ["mgr 1", "ncops 3"]
    x = beside(rnd, eye, 6.0, along=0.3)
    x = (float(round(x[0])), float(round(x[1])), float(round(x[2])), 0.0)
    spots = (x, (x[0] + 25.0, x[1], x[2], 0.0), (x[0] + 3.0, x[1], x[2], 0.0))
    for i, g in enumerate(spots):
        sc.append("slot %d %d" % (i, i))
        sc.append("cop %d %d 4" % (i, i))
        sc.append(car_line(i, g, g, 4, 0))
    sc += ["rb 0 0 1 0", "rb 1 2 0 1", "pur 0", "pur 1", "find 4"]
    # And roadblock 1's cops seen through its spike strip.
    sc += ["spike 1 1 %s" % vec(*beside(rnd, eye, 4.0, along=0.7)),
           "find 4"]
    return sc


def s_far(rnd):
    """Stops about 45 to 65 from the camera's point, either side of 60,
    off a straight road."""
    eye, lines = one_road(rnd, n=30, bend=False)
    sc = lines + ["mgr 1", "ncops 7"]
    for i, side in enumerate((36.0, -40.0, 43.0, -45.5, 47.0, -48.5, 52.0)):
        g = beside(rnd, eye, side, along=0.25 + 0.1 * i)
        sc.append("slot %d %d" % (i, i))
        sc.append("cop %d %d 5" % (i, i))
        sc.append(car_line(i, g, g, 4, 0))
    sc += ["find 6", "find 3"]
    return sc


def s_loop(rnd):
    """Looped and clamped eye and look splines of 10 and 30 points, with
    stops that land."""
    sc = []
    for typ in (1, 0):
        eye, lines = one_road(rnd, n=10, typ=typ, nl=30)
        sc += lines + ["mgr 1", "ncops 5"]
        for i in range(5):
            g = beside(rnd, eye, (-10.0, 10.0)[i % 2], along=0.15 + 0.17 * i)
            sc.append("slot %d %d" % (i, i))
            sc.append("cop %d %d 7" % (i, i))
            sc.append(car_line(i, g, g, 4, 0))
        sc.append("find 6")
    return sc


def s_hairpin(rnd):
    """Crossings up one arm of a hairpin, round its turn and back down the
    other: the nearer pair's midpoint picks the arm."""
    arm1 = [(10.0 * i, 20.0, 0.0, 0.0) for i in range(11)]
    arm2 = [(100.0 - 20.0 * i, -20.0, 0.0, 0.0) for i in range(6)]
    sc = [spline_line("eye", 2, arm1 + [(115.0, 0.0, 0.0, 0.0)] + arm2)]
    for px in (49.0, 50.5, 51.0, 51.5, 52.0, 52.4, 53.0):
        sc.append("appr %s %s" % (vec(-0.6, 0.01), vec(px, 0.0, 0.0, 0.0)))
    # A straight spline 16 apart, the target met exactly at a halving
    # (3, 4, 5 from the point) and a tolerance below zero: the halving
    # goes on past a g of exactly 0.
    sc.append(spline_line("eye", 2, [(16.0 * i, 0.0, 0.0, 0.0)
                                     for i in range(5)]))
    for x, y in ((43.0, 4.0), (39.0, 4.0), (47.0, -4.0), (43.0, 0.0)):
        for tol in (-1.0, 0.01):
            sc.append("appr %s %s" % (vec(-0.6, tol), vec(x, y, 0.0, 0.0)))
    return sc


def s_exact(rnd):
    """Float edges: segments exactly 30.0 long whose one step does not land
    back on `a`; points 20 apart by retail's order of the squares' sum and
    not by the other, either way; and points stacked 25 apart in z."""
    sc = ["topo " + " ".join("0" for _ in range(20))]
    for a, b in (("4341ea81 c006dd72 43523f16", "43449f02 c1fb5def 4358067a"),
                 ("c288d6d4 41228a45 c33c9d5c", "c2966b51 421ab9d6 c3364335"),
                 ("c07323e0 c1674add 42af5c40",
                  "c189a5fc c22523c0 42ae04b2")):
        sc.append("block %s 00000000 %s 3f800000" % (a, b))
    eye, lines = one_road(rnd)
    sc += lines + ["mgr 1", "ncops 6"]
    neg = " ".join("%08x" % (int(x, 16) ^ 0x80000000)
                   for x in ("41187deb", "412ccab2", "415e0306"))
    pts = (vec(0.0, 0.0, 0.0, 0.0), "415a6351 41197c9c 41307d4d 00000000",
           vec(100.0, 0.0, 0.0, 0.0), neg + " 00000000",
           vec(-100.0, 50.0, 0.0, 0.0), vec(-100.0, 50.0, 25.0, 0.0))
    for i, g in enumerate(pts):
        sc.append("slot %d %d" % (i, i))
        sc.append("cop %d %d 3" % (i, i))
        sc.append("car %d %s %s 4 0" % (i, g, g))
    sc.append("find 4")
    return sc


def s_floor(rnd):
    """Linears that put every stop on one parameter: the floor's edges,
    the taken control point and the one before, and the bounds."""
    sc = []
    eye, look, lines = course(rnd, ne=16, nl=11)
    sc += lines[:2]
    stops = [beside(rnd, eye, rnd.uniform(-25, 25),
                    along=0.2 + 0.15 * i) for i in range(4)]
    sc += ["mgr 1", "ncops 4"]
    for i, p in enumerate(stops):
        sc.append("slot %d %d" % (i, i))
        sc.append("cop %d %d 3" % (i, i))
        sc.append(car_line(i, p, p, 4, 0))
    # The eye's inverse is its b when |m| <= 0.001; look's value of that,
    # times 10, is where the stop lands.
    for b in (0.5, 0.95, 0.999, 1.0, 1.05, 0.0, 0.04, -0.05, 0.1, 0.45):
        sc.append("lin E %s" % vec(0.0005, b))
        sc.append("lin L %s" % vec(1.0, 0.0))
        sc.append("find 4")
    sc.append("lin E %s" % vec(0.0, 0.5))
    sc.append("lin L %s" % vec(0.0, 0.5))
    sc.append("find 4")
    sc.append("lin L %s" % vec(0.2, 0.4))
    sc.append("find 3")
    sc.append("lin L %s" % vec(-1.0, 1.0))
    sc.append("find 4")
    sc.append("lin E %s" % vec(0.0005, 0.05))
    sc.append("lin L %s" % vec(1.0, -0.1))
    sc.append("find 4")
    sc.append("lin E %s" % vec(0.0005, 1.0))
    sc.append("lin L %s" % vec(0.5, 0.0))
    sc.append("find 4")
    sc.append("lin E %s" % vec(0.0005, 0.6))
    sc.append("find 4")
    sc.append("lin E %s" % vec(0.0005, 0.15))
    sc.append("lin L %s" % vec(1.0, -0.1))
    sc.append("find 4")
    return sc


def s_many(rnd, cops):
    """Stops spread along the road, more than maxStops of them."""
    eye, look, lines = course(rnd, ne=rnd.randint(20, 40),
                              nl=rnd.randint(30, 60))
    sc = list(lines)
    spots = [beside(rnd, eye, rnd.uniform(-20, 20),
                    along=0.08 + 0.12 * i + rnd.uniform(-0.03, 0.03))
             for i in range(7)]
    rnd.shuffle(spots)
    if cops:
        sc += ["mgr 1", "ncops 7"]
        for i, p in enumerate(spots):
            sc.append("slot %d %d" % (i, i))
            sc.append("cop %d %d %d" % (i, i, rnd.choice((3, 5, 7, 8))))
            sc.append(car_line(i, p, p, 4, 0))
    else:
        sc.append("mgr 0")
        sc.append("world 0 0 %s" % " ".join(str(k) for k in range(NCAR)))
        for i, p in enumerate(spots):
            sc.append("coll %s 1" % vec(*p))
        sc.append("topo " + " ".join(str(rnd.choice((0, 0, 0, 0, 1)))
                                     for _ in range(60)))
    for m in (6, 4, 2, 1):
        sc.append("find %d" % m)
    return sc


def s_types(rnd):
    """Clamped and looped splines, a scenario each."""
    out = []
    for te, tl in ((0, 0), (1, 1), (0, 2), (2, 1)):
        eye, look, lines = course(rnd, types=(te, tl))
        out.append(lines + cops_world(rnd, eye) + ["find 4"])
    return out


def script():
    rnd = random.Random(0x5709e5)
    sc = [s_inverse(rnd), s_centre(rnd), s_block(rnd), s_block(rnd),
          s_approach_short(rnd)]
    for typ in (2, 2, 0, 1):
        sc.append(s_approach(rnd, typ))
    sc += [s_seen(rnd), s_pairs(rnd), s_floor(rnd), s_floor(rnd),
           s_rb_twice(rnd), s_far(rnd), s_loop(rnd), s_hairpin(rnd),
           s_exact(rnd)]
    for i in range(8):
        sc.append(s_many(rnd, i % 2 == 0))
    for _ in range(14):
        sc.append(s_cops(rnd))
    for _ in range(14):
        sc.append(s_race(rnd))
    sc += s_types(rnd)
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
        self.e = retail_model.RetailEmu(ieee=True)
        e = self.e
        e.stub(FUNK_EXISTS, lambda em: 0)
        e.stub(VEC_DELETE, self.s_free)
        e.stub(DELETE, self.s_free)
        e.stub(BMALLOC, self.s_malloc)
        e.stub(BMEMSET, self.s_memset)
        e.stub(BMEMCPY, self.s_memcpy)
        e.stub(BFREE, lambda em: None)
        e.stub(TWO_CAR, self.s_two)
        e.stub(SET_BBOX3, self.s_bbox)
        e.stub(SEG_HITS, self.s_seg)
        e.stub(DOWNSAMPLE, self.s_down)
        e.call(EMATH_SINIT)
        e.call(BMATRIX_SINIT)
        self.names = {0: "null", TC: "tc", ROUTE: "route", EYE: "eye",
                      LOOK: "look", AHEAD: "ahead", STOPSA: "stops",
                      EYEPTS: "eyepts", LOOKPTS: "lookpts",
                      AHEADPTS: "aheadpts"}
        for i in range(NCOLL):
            self.names[coll_at(i)] = "c%d" % i
        self.blocks = {}

    def emit(self, s):
        self.out.append(s)

    def name(self, a):
        a &= M32
        if a in self.names:
            return self.names[a]
        if a in self.blocks:
            return self.blocks[a]
        return "?"

    def fill(self, a, n):
        self.e.write(a, bytes([PATTERN]) * n)

    def w(self, a):
        return self.e.u32(a)

    def put(self, a, x):
        self.e.put32(a, int(x, 16) if isinstance(x, str) else x)

    def put_vec(self, a, t):
        for i in range(4):
            self.put(a + 4 * i, t[i])

    def cstr(self, a):
        s = bytearray()
        while self.e.mem[a] and len(s) < 200:
            s.append(self.e.mem[a])
            a += 1
        return s.decode("latin-1")

    def reset(self):
        e = self.e
        self.fill(MGR, 0x100)
        self.fill(COPS, COP_SIZE * NCOP)
        self.fill(CARS, CAR_SIZE * NCAR)
        self.fill(RCARS, RC_SIZE * NCAR)
        self.fill(RBS, RB_SIZE * NRB)
        self.fill(PURS, PUR_SIZE * NPUR)
        self.fill(SPIKES, SPK_SIZE * NSPIKE)
        self.fill(HELI, HELI_SIZE)
        self.fill(WORLD, WORLD_SIZE)
        self.fill(COLLS, COLL_SIZE * NCOLL)
        for a in (EYE, LOOK, AHEAD):
            self.fill(a, SPL_SIZE)
        for a in (EYEPTS, LOOKPTS, AHEADPTS):
            self.fill(a, 16 * NPTS)
        self.fill(LIN_E, 8)
        self.fill(LIN_L, 8)
        self.fill(ARENA, ARENA_SIZE)
        e.put32(MGR + MGR_NCOPS, 0)
        for i in range(NSLOT):
            e.put32(MGR + MGR_COPS + 4 * i, 0)
        for off in (MGR_PURSUITS, MGR_SPIKES):
            e.put32(MGR + off, MGR + off)
            e.put32(MGR + off + 4, MGR + off)
        e.put32(WORLD + W_COLL, WORLD + W_COLL)
        e.put32(WORLD + W_COLL + 4, WORLD + W_COLL)
        e.put32(WORLD + W_HELI, 0)
        e.put32(WORLD + W_AI, 0)
        e.put32(WORLD + W_COP, 0)
        for i in range(NCAR):
            e.put32(WORLD + W_CARS + 4 * i, 0)
        e.put32(G_MGR, 0)
        e.put32(G_WORLD, WORLD)
        e.put32(G_RACE, RACE)
        self.npur = self.nspike = self.ncoll = 0
        self.two = [0] * NCOLL
        self.topo, self.itopo = [], 0
        self.heap = ARENA
        self.blocks = {}

    def append(self, head, node):
        """bTList::AddTail, next at +0 and prev at +4."""
        e = self.e
        last = self.w(head + 4)
        e.put32(node, head)
        e.put32(node + 4, last)
        e.put32(last, node)
        e.put32(head + 4, node)

    # ---- the stubs -------------------------------------------------------

    def s_malloc(self, em):
        size = s32(em.reg[4])
        p = (self.heap + 15) & ~15
        self.heap = p + max(size, 0)
        assert self.heap <= ARENA + ARENA_SIZE, "arena full"
        if em.reg[5] & M32 == HSORT_FILE:
            # The port's heap_sort holds its element in a malloc'd slot of
            # its own, unprinted.
            return p
        tag = "m%d" % len(self.blocks)
        self.blocks[p] = tag
        self.emit("  malloc %s %d %d %d -> %s"
                  % (self.cstr(em.reg[5] & M32), s32(em.reg[6]),
                     s32(em.reg[7]), size, tag))
        return p

    def s_free(self, em):
        self.emit("  free %s" % self.name(em.reg[4]))

    def s_memset(self, em):
        a, v, n = em.reg[4] & M32, em.reg[5] & 0xff, s32(em.reg[6])
        assert 0 <= n < 0x10000, "bMemSet %d" % n
        em.mem[a:a + n] = bytes([v]) * n
        return a

    def s_memcpy(self, em):
        d, a, n = em.reg[4] & M32, em.reg[5] & M32, s32(em.reg[6])
        assert 0 <= n < 0x10000, "bMemCpy %d" % n
        em.mem[d:d + n] = em.mem[a:a + n]
        return d

    def s_two(self, em):
        a = em.reg[4] & M32
        i = (a - COLLS) // COLL_SIZE
        r = self.two[i] if 0 <= i < NCOLL and a == coll_at(i) else 0
        self.emit("  two %s -> %d" % (self.name(a), r))
        return r

    def s_bbox(self, em):
        p = em.reg[5] & M32
        self.emit("  bbox %s %s %s %s"
                  % (self.name(em.reg[4]), self.vec3(p), fx(em.fpr[12]),
                     self.name(em.reg[6])))

    def s_seg(self, em):
        ans = self.topo[self.itopo] if self.itopo < len(self.topo) else 0
        self.itopo += 1
        self.emit("  seg %s %s %s %s -> %d"
                  % (self.name(em.reg[4]), self.vec3(em.reg[5] & M32),
                     self.vec3(em.reg[6] & M32), fx(em.fpr[12]), ans))
        return ans

    def s_down(self, em):
        st, n = em.reg[5] & M32, s32(em.reg[6])
        vals = "".join(" %s" % fx(self.w(st + 4 * i))
                       for i in range(min(max(n, 0), NSTOPS)))
        self.emit("  down %s %s %s %d%s"
                  % (self.name(em.reg[4]), fx(em.fpr[12]), self.name(st), n,
                     vals))

    # ---- what the transcript shows --------------------------------------

    def vec3(self, a):
        return " ".join(fx(self.w(a + 4 * i)) for i in range(3))

    def dump_spline(self, tag, a):
        w = self.w
        self.emit("  %s n %d buf %d type %d dirty %d pts %s arr %s"
                  % (tag, s32(w(a + 4)), s32(w(a)), s32(w(a + 8)),
                     s32(w(a + 20)), self.name(w(a + 12)),
                     self.name(w(a + 16))))

    def set_spline(self, a, pts, t):
        e = self.e
        typ, n = int(t[0]), int(t[1])
        e.put32(a, n)
        e.put32(a + 4, n)
        e.put32(a + 8, typ)
        e.put32(a + 12, pts)
        e.put32(a + 16, 0)
        e.put32(a + 20, 1)
        e.put32(a + 24, 16384)
        e.put32(a + 28, 0)
        e.put32(a + 32, 0)
        e.put32(a + 36, 0)
        e.put32(a + 40, 0)
        e.put32(a + 44, 0)
        for i in range(n):
            self.put_vec(pts + 16 * i, t[2 + 4 * i:6 + 4 * i])

    def call(self, fn, *args, **f):
        e = self.e
        for i, v in f.items():
            e.fpr[int(i[1:])] = v & M32
        return e.call(fn, *args, limit=LIMIT)

    def find(self, maxs):
        e = self.e
        self.fill(STOPSA, 4 * NSTOPS)
        a = AHEAD
        e.put32(a, NPTS)
        e.put32(a + 4, 0)
        e.put32(a + 8, 2)
        e.put32(a + 12, AHEADPTS)
        e.put32(a + 16, 0)
        e.put32(a + 20, 0)
        e.put32(a + 24, 16384)
        e.put32(a + 44, 0)
        e.put32(e.reg[29] & M32, maxs)
        n = self.call(STOPS, ROUTE, TC, EYE, LOOK, AHEAD, LIN_E, LIN_L,
                      STOPSA)
        self.emit("  count %d" % n)
        self.emit("  stops" + "".join(" %s" % fx(self.w(STOPSA + 4 * i))
                                      for i in range(NSTOPS)))
        self.dump_spline("eye", EYE)
        self.dump_spline("look", LOOK)
        self.dump_spline("ahead", AHEAD)
        pts, n = self.w(AHEAD + 12), s32(self.w(AHEAD + 4))
        for i in range(min(n, NPTS)):
            self.emit("  ahead %d %s" % (i, self.vec3(pts + 16 * i)))

    # ---- the script ------------------------------------------------------

    def op(self, t, line):
        e = self.e
        c = t[0]
        if c == "mgr":
            e.put32(G_MGR, MGR if int(t[1]) else 0)
        elif c == "ncops":
            e.put32(MGR + MGR_NCOPS, int(t[1]))
        elif c == "slot":
            o = int(t[2])
            e.put32(MGR + MGR_COPS + 4 * int(t[1]), 0 if o < 0 else cop_at(o))
        elif c == "cop":
            cp = cop_at(int(t[1]))
            e.put32(cp + COP_CAR, car_at(int(t[2])))
            e.put32(cp + COP_STATE, int(t[3]))
        elif c == "car":
            k = int(t[1])
            car = car_at(k)
            e.put32(car + CAR_RACING, rc_at(k))
            self.put_vec(car + CAR_GEOM, t[2:6])
            self.put_vec(car + CAR_POS, t[6:10])
            e.put32(car + CAR_WHEELS, int(t[10]))
            e.mem[rc_at(k) + RC_PLACE] = int(t[11]) & 0xff
        elif c == "rb":
            rb = rb_at(int(t[1]))
            for k in range(2):
                o = int(t[2 + k])
                e.put32(rb + RB_COPS + 4 * k, 0 if o < 0 else cop_at(o))
            e.put32(rb + RB_INDEX, int(t[4]))
        elif c == "pur":
            p = pur_at(self.npur)
            self.npur += 1
            r = int(t[1])
            e.put32(p + PUR_RB, 0 if r < 0 else rb_at(r))
            self.append(MGR + MGR_PURSUITS, p)
        elif c == "spike":
            s = spike_at(self.nspike)
            self.nspike += 1
            m = int(t[2])
            e.put32(s + SPK_ID, int(t[1]))
            e.put32(s + SPK_N, m)
            for k in range(m):
                self.put_vec(s + SPK_POS + SPK_STRIDE * k,
                             t[3 + 4 * k:7 + 4 * k])
            self.append(MGR + MGR_SPIKES, s)
        elif c == "heli":
            if int(t[1]):
                e.put32(WORLD + W_HELI, HELI)
                e.put32(HELI + HELI_PLAN, int(t[2]))
                self.put_vec(HELI + HELI_POS, t[3:7])
            else:
                e.put32(WORLD + W_HELI, 0)
        elif c == "world":
            e.put32(WORLD + W_AI, int(t[1]))
            e.put32(WORLD + W_COP, int(t[2]))
            for k in range(NCAR):
                o = int(t[3 + k])
                e.put32(WORLD + W_CARS + 4 * k, 0 if o < 0 else car_at(o))
        elif c == "coll":
            cl = coll_at(self.ncoll)
            self.put_vec(cl + COLL_POINT, t[1:5])
            self.two[self.ncoll] = int(t[5])
            self.ncoll += 1
            self.append(WORLD + W_COLL, cl)
        elif c == "topo":
            self.topo = [int(x) for x in t[1:]]
            self.itopo = 0
        elif c == "eye":
            self.set_spline(EYE, EYEPTS, t[1:])
        elif c == "look":
            self.set_spline(LOOK, LOOKPTS, t[1:])
        elif c == "lin":
            a = LIN_E if t[1][0] == "E" else LIN_L
            self.put(a, t[2])
            self.put(a + 4, t[3])
        elif c == "find":
            self.emit("> " + line)
            self.find(int(t[1]))
        elif c == "appr":
            self.emit("> " + line)
            self.put_vec(VA, t[3:7])
            self.call(APPROACH, EYE, VA, f12=int(t[1], 16),
                      f13=int(t[2], 16))
            self.emit("  appr %s" % fx(e.fpr[0]))
        elif c == "cosine":
            self.emit("> " + line)
            self.put_vec(VA, t[2:6])
            self.call(COSINE, EYE, VA, f12=int(t[1], 16))
            self.emit("  cos %s" % fx(e.fpr[0]))
        elif c == "inv":
            self.emit("> " + line)
            self.put(LIN_X, t[1])
            self.put(LIN_X + 4, t[2])
            self.call(INVERSE, LIN_X, f12=int(t[3], 16))
            self.emit("  inv %s" % fx(e.fpr[0]))
        elif c == "block":
            self.emit("> " + line)
            self.put_vec(VA, t[1:5])
            self.put_vec(VB, t[5:9])
            r = self.call(BLOCKED, TC, VA, VB)
            self.emit("  block %d" % r)
        elif c == "centre":
            self.emit("> " + line)
            self.call(CENTRE, spike_at(int(t[1])), VOUT)
            self.emit("  centre %s" % self.vec3(VOUT))
        else:
            raise SystemExit("bad op %r" % (t,))

    def run(self, scenarios):
        for i, sc in enumerate(scenarios):
            self.emit("B %d" % i)
            self.reset()
            for ln in sc:
                self.op(ln.split(), ln)
        return self.out


# ================================================================ the build


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


def build_flags():
    return list(hostbuild.FLAGS)


def build_harness(tmp, name="previewstops_test"):
    return hostbuild.build(tmp, SOURCES, name=name, flags=build_flags())


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
    M("radius", "#define STOP_RADIUS          20.0f",
      "#define STOP_RADIUS          25.0f"),
    M("pair", "#define STOP_ROADBLOCK_PAIR  10.0f",
      "#define STOP_ROADBLOCK_PAIR  9.0f"),
    M("max-dist", "#define STOP_MAX_DISTANCE    60.0f",
      "#define STOP_MAX_DISTANCE    50.0f"),
    M("cos", "#define STOP_APPROACH_COS    -0.6f",
      "#define STOP_APPROACH_COS    -0.5f"),
    M("tol", "#define STOP_APPROACH_TOL    0.01f",
      "#define STOP_APPROACH_TOL    0.02f"),
    M("downsample", "#define STOP_DOWNSAMPLE      0.3333f",
      "#define STOP_DOWNSAMPLE      0.3f"),
    M("max-seen", "#define STOP_MAX_SEEN        6",
      "#define STOP_MAX_SEEN        7"),
    M("flat", "#define LINEAR_FLAT          0.001f",
      "#define LINEAR_FLAT          0.002f"),
    M("topo-short", "#define TOPO_SHORT           30.0f",
      "#define TOPO_SHORT           31.0f"),
    M("topo-step", "#define TOPO_STEP_INV        0.033333335f",
      "#define TOPO_STEP_INV        0.034f"),
    M("topo-radius", "#define TOPO_RADIUS          0.5f",
      "#define TOPO_RADIUS          1.0f"),

    # The helpers.
    M("last-loop", "    if (s->Type == SPLINE_LOOP)" + NL
      + "        return (float)s->NumControlPoints;",
      "    if (s->Type == SPLINE_LOOP)" + NL
      + "        return (float)(s->NumControlPoints - 1);"),
    M("last-clamp",
      "if (s->Type == SPLINE_CLAMP || s->Type == SPLINE_EXTRAPOLATE)",
      "if (s->Type == SPLINE_EXTRAPOLATE)"),
    M("dist3", "    return sqrtf((dx * dx + dy * dy) + dz * dz);",
      "    return sqrtf(dx * dx + dy * dy);"),
    M("dist3-order", "    return sqrtf((dx * dx + dy * dy) + dz * dz);",
      "    return sqrtf(dx * dx + (dy * dy + dz * dz));"),
    M("halfway", "    o->y = (a->y + b->y) * 0.5f;", "    o->y = a->y;"),

    # The stop list.
    M("pc-sum", "        sum.y += v->y;" + NL + "        sum.z += v->z;"
      + NL + "        sum.pad += v->pad;" + NL + "        count++;",
      "        sum.y += v->x;" + NL + "        sum.z += v->z;"
      + NL + "        sum.pad += v->pad;" + NL + "        count++;"),
    M("pc-count", "        sum.pad += v->pad;" + NL + "        count++;",
      "        sum.pad += v->pad;" + NL + "        count += 2;"),
    M("pc-k", "    out->z = sum.z * k;" + NL + "    out->pad = sum.pad * k;"
      + NL + "}" + NL + NL + "// 0x00165828",
      "    out->z = sum.z;" + NL + "    out->pad = sum.pad * k;"
      + NL + "}" + NL + NL + "// 0x00165828"),
    M("try-lt", "        if (STOP_RADIUS < dist3(pt,",
      "        if (STOP_RADIUS > dist3(pt,"),
    M("try-keep", "    if (!addPoint)" + NL + "        return 1;",
      "    if (!addPoint)" + NL + "        return 0;"),
    M("try-pos", "    q->Position = *pt;" + NL, ""),
    M("try-size", "\"PreviewPausePoint\", 0, 16);",
      "\"PreviewPausePoint\", 0, 0);"),
    M("add-taken", "        if (pause_try_add((PreviewPause *)(void *)n, pt,"
      " addPoint))" + NL + "            return;",
      "        if (pause_try_add((PreviewPause *)(void *)n, pt,"
      " addPoint))" + NL + "            ;"),
    M("add-own", "    pause_try_add(p, pt, 1);",
      "    pause_try_add(p, pt, addPoint);"),
    M("add-size", "\"PreviewPause\"," + NL + "                                0, 16);",
      "\"PreviewPause\"," + NL + "                                0, 0);"),
    M("seen-dup", "        if (seen[i] == cop)" + NL + "            return;"
      + NL, ""),
    M("seen-has", "        if (seen[i] == cop)" + NL + "            return 1;",
      "        if (seen[i] == cop)" + NL + "            return 0;"),

    # The roadblock's stop.
    M("rb-pos", "    bVector3 pos = cop->pMyCar->State.GeometryPosition;",
      "    bVector3 pos = cop->pMyCar->State.Position;"),
    M("rb-found", "            if (c == (const void *)cop)",
      "            if (c != (const void *)cop)"),
    M("rb-none", "        if (!found)" + NL + "            continue;" + NL,
      ""),
    M("rb-cnt", "        if (cnt == 2) {", "        if (cnt >= 1) {"),
    M("rb-lt", "            if (dist3(a, b) < STOP_ROADBLOCK_PAIR)",
      "            if (dist3(a, b) <= STOP_ROADBLOCK_PAIR)"),
    M("rb-seen", "                seen_add(rb->cops[k], seen, numSeen);"
      + NL, "                ;" + NL),
    M("rb-break", "                seen_add(rb->cops[k], seen, numSeen);"
      + NL + "        break;", "                seen_add(rb->cops[k], seen,"
      " numSeen);" + NL + "        ;"),

    # The cops' stops.
    M("spike-add", "        add_stop_point(pauses, &c, 1);",
      "        add_stop_point(pauses, &c, 0);"),
    M("spike-id", "rb->nIndexIntoLoadedData != s->nRoadBlockID",
      "rb->nIndexIntoLoadedData == s->nRoadBlockID"),
    M("spike-seen", "                    seen_add(rb->cops[k], seen,"
      " &numSeen);", "                    ;"),
    M("ncops", "    for (i = 0; i < pCopManager->nNumCops; i++) {",
      "    for (i = 0; i < pCopManager->nNumCops - 1; i++) {"),
    M("state-trap", "        case LS_SPEED_TRAP:" + NL,
      "        case (eLogicState)2:" + NL),
    M("state-patrol", "        case LS_DRIVING_ON_PATROL:" + NL, ""),
    M("state-caught", "        case LS_CAUGHT_SPEEDER:" + NL, ""),
    M("state-guard", "        case LS_GUARD_LOCATION:" + NL,
      "        case (eLogicState)6:" + NL),
    M("state-rb", "        case LS_ROAD_BLOCK:" + NL,
      "        case (eLogicState)1:" + NL),
    M("simple-seen", "            if (!seen_has(cop, seen, &numSeen))" + NL
      + "                add_stop_point(", "            if (1)" + NL
      + "                add_stop_point("),
    M("simple-pos", "                add_stop_point(pauses, &cop->pMyCar->"
      "State.GeometryPosition,", "                add_stop_point(pauses, "
      "&cop->pMyCar->State.Position,"),
    M("rb-seen-has", "            if (!seen_has(cop, seen, &numSeen))" + NL
      + "                road_block_stop(", "            if (1)" + NL
      + "                road_block_stop("),
    M("heli-plan", "(uint32_t)h->Plan < (uint32_t)CHOPPLAN_START_CHASE",
      "(uint32_t)h->Plan <= (uint32_t)CHOPPLAN_START_CHASE"),
    M("heli-signed", "(uint32_t)h->Plan < (uint32_t)CHOPPLAN_START_CHASE",
      "(int32_t)h->Plan < (int32_t)CHOPPLAN_START_CHASE"),
    M("heli-bomb", "h->Plan == CHOPPLAN_BOMBING_RUN",
      "h->Plan == CHOPPLAN_START_CHASE"),
    M("heli-pos", "add_stop_point(pauses, &h->CurrentPos, 1);",
      "add_stop_point(pauses, &h->CurrentPos, 0);"),

    # The race's stops.
    M("racers", "    return pCurrentWorld->CopCarPos - pCurrentWorld->AICarPos;",
      "    return pCurrentWorld->CopCarPos - pCurrentWorld->AICarPos - 1;"),
    M("racer-base", "CarTable[pCurrentWorld->AICarPos + i]",
      "CarTable[i]"),
    M("first", "->RacePosition == 1) {", "->RacePosition == 2) {"),
    M("first-pos", "            add_stop_point(pauses, &car->State.Position,"
      " 0);" + NL + "            break;", "            add_stop_point(pauses,"
      " &car->State.GeometryPosition, 0);" + NL + "            break;"),
    M("first-break", "            add_stop_point(pauses, &car->State.Position,"
      " 0);" + NL + "            break;", "            add_stop_point(pauses,"
      " &car->State.Position, 0);" + NL + "            ;"),
    M("second", "->RacePosition == 2" + NL, "->RacePosition == 3" + NL),
    M("airborne", "|| car->State.nWheelsTouchingGround == 0)",
      "|| car->State.nWheelsTouchingGround <= 2)"),
    M("or-and", "|| car->State.nWheelsTouchingGround == 0)",
      "&& car->State.nWheelsTouchingGround == 0)"),
    M("two-car", "        if (collision_is_two_car_collision(c))",
      "        if (!collision_is_two_car_collision(c))"),
    M("coll-add", "add_stop_point(pauses, &c->CurrentContactPoint, 0);",
      "add_stop_point(pauses, &c->CurrentContactPoint, 1);"),
    M("cop-or-race", "    if (pCopManager != NULL)" + NL
      + "        cop_stops(&pauses);",
      "    if (pCopManager == NULL)" + NL + "        cop_stops(&pauses);"),

    # The stops onto the look spline.
    M("nused", "    int32_t nUsed = look->NumControlPoints - 1;",
      "    int32_t nUsed = look->NumControlPoints;"),
    M("count-max", "n != &pauses && count < maxStops;",
      "n != &pauses && count <= maxStops;"),
    M("approach-spline", "            t = spline_find_approach_param("
      "eyeForward, &centre,", "            t = spline_find_approach_param("
      "look, &centre,"),
    M("inverse-by", "t / spline_last(eyeForward)));",
      "t / spline_last(look)));"),
    M("inverse-lin", "                                       eyeParam," + NL,
      "                                       lookParam," + NL),
    M("x-last", "            x = spline_last(look)" + NL,
      "            x = spline_last(eyeForward)" + NL),
    M("floor", "            if (x < fl)" + NL + "                fl -= 1.0f;",
      "            if (x <= fl)" + NL + "                fl -= 1.0f;"),
    M("floor-none", "            if (x < fl)" + NL + "                fl -= "
      "1.0f;" + NL, ""),
    M("taken-prev", "                k--;" + NL + "                if (k < 0 "
      "|| k >= nUsed || used[k])" + NL + "                    continue;",
      "                continue;"),
    M("taken-fl", "                fl = (float)k;" + NL, ""),
    M("taken-lo", "            if (k < 0 || k >= nUsed || used[k]) {",
      "            if (k < 1 || k >= nUsed || used[k]) {"),
    M("bound-lo", "            if (fl <= spline_last(look) * linear_get_value"
      "(lookParam, 0.0f))", "            if (fl < spline_last(look) * "
      "linear_get_value(lookParam, 0.0f))"),
    M("bound-hi", "            if (spline_last(look) * linear_get_value("
      "lookParam, 1.0f) <= fl)", "            if (spline_last(look) * "
      "linear_get_value(lookParam, 1.0f) < fl)"),
    M("eye-at", "            spline_get_point(eyeForward, &eye, t);",
      "            spline_get_point(look, &eye, t);"),
    M("blocked-cops", "            if (pCopManager == NULL" + NL,
      "            if (1" + NL),
    M("blocked-args", "topology_segment_blocked(tc, &eye, &centre))",
      "topology_segment_blocked(tc, &centre, &eye))"),
    M("dist-lt", "            if (dist3(&centre, &eye) < STOP_MAX_DISTANCE)",
      "            if (dist3(&centre, &eye) > STOP_MAX_DISTANCE)"),
    M("used-set", "                used[k] = 1;" + NL, ""),
    M("entry-param", "                entries[count].Param = fl;",
      "                entries[count].Param = x;"),
    M("entry-pos", "                entries[count].Position = centre;",
      "                entries[count].Position = eye;"),
    M("compare", "    return ((const PreviewStopEntry *)a)->Param" + NL
      + "           - ((const PreviewStopEntry *)b)->Param;",
      "    return ((const PreviewStopEntry *)b)->Param" + NL
      + "           - ((const PreviewStopEntry *)a)->Param;"),
    M("stops-copy", "        stops[i] = entries[i].Param;",
      "        stops[i] = (float)i;"),
    M("ahead-last", "        if (s < count && stops[s] == (float)i) {",
      "        if (s + 1 < count && stops[s] == (float)i) {"),
    M("ahead-pos", "            spline_add_control_point(lookAhead, "
      "&entries[s].Position);", "            spline_add_control_point("
      "lookAhead, src);"),
    M("ahead-src", "            spline_add_control_point(lookAhead, src);",
      "            spline_add_control_point(lookAhead, "
      "look->pControlPoints);"),
    M("down-count", "preview_down_sample_xy(lookAhead, STOP_DOWNSAMPLE, "
      "stops, count);", "preview_down_sample_xy(lookAhead, STOP_DOWNSAMPLE,"
      " stops, maxStops);"),
    M("free-points", "            bFree(q);" + NL, ""),
    M("free-order", "            list_remove(q);" + NL + "            bFree(q);"
      + NL + "        }" + NL + "        bFree(p);",
      "            list_remove(q);" + NL + "        }" + NL + "        bFree(p);"
      + NL + "        while ((q = p->Points.next) != &p->Points)" + NL
      + "            bFree(q);"),
    M("ret-count", "    return count;" + NL + "}", "    return maxStops;" + NL
      + "}"),

    # The approach's cosine.
    M("cos-sign", "    vx = p.x - pt->x;", "    vx = pt->x - p.x;"),
    M("cos-norm", "    q = 1.0f / sqrtf((d.x * d.x + d.y * d.y) + d.z * d.z);",
      "    q = 1.0f;"),
    M("cos-vnorm", "    q = 1.0f / sqrtf((vx * vx + vy * vy) + vz * vz);",
      "    q = 1.0f / ((vx * vx + vy * vy) + vz * vz);"),
    M("cos-order", "    return (vx * d.x + vy * d.y) + vz * d.z;",
      "    return vx * d.x + (vy * d.y + vz * d.z);"),
    M("cos-deriv", "    spline_get_derivative(s, &d, t);",
      "    spline_get_point(s, &d, t + 1.0f);"),

    # The approach's parameter.
    M("appr-start", "    prev = spline_approach_cosine(s, pt, 0.0f) - target;",
      "    prev = spline_approach_cosine(s, pt, 1.0f) - target;"),
    M("appr-cross", "        if (prev * g < 0.0f) {",
      "        if (prev * g > 0.0f) {"),
    M("appr-mid", "            mid.x = b->x * 0.5f + a->x * 0.5f;",
      "            mid.x = b->x;"),
    M("appr-best", "            if (best == 0 || d < bestD) {",
      "            if (best == 0 || d > bestD) {"),
    M("appr-prev", "        prev = g;" + NL + "    }", "    }"),
    M("appr-none", "        return prev < 0.0f ? spline_last(s) + 1.0f : -1.0f;",
      "        return prev < 0.0f ? spline_last(s) : -1.0f;"),
    M("appr-none-sign",
      "        return prev < 0.0f ? spline_last(s) + 1.0f : -1.0f;",
      "        return prev > 0.0f ? spline_last(s) + 1.0f : -1.0f;"),
    M("appr-ref", "    ref = g;" + NL + "    r = lo;",
      "    ref = -g;" + NL + "    r = lo;"),
    M("appr-r", "    ref = g;" + NL + "    r = lo;",
      "    ref = g;" + NL + "    r = hi;"),
    M("appr-tol", "tol < fabsf(g) && iter < 10;", "tol < g && iter < 10;"),
    M("appr-iter", "tol < fabsf(g) && iter < 10;",
      "tol < fabsf(g) && iter < 9;"),
    M("appr-move", "        if (g * ref < 0.0f) {" + NL + "            lo = r;",
      "        if (g * ref > 0.0f) {" + NL + "            lo = r;"),
    M("appr-hi-ref", "            ref = g;" + NL + "            hi = r;",
      "            hi = r;"),
    M("appr-hi", "            ref = g;" + NL + "            hi = r;",
      "            ref = g;" + NL + "            lo = r;"),

    # Linear::GetInverse.
    M("inv-flat", "    if (fabsf(l->m) <= LINEAR_FLAT)",
      "    if (fabsf(l->m) < LINEAR_FLAT)"),
    M("inv-abs", "    if (fabsf(l->m) <= LINEAR_FLAT)",
      "    if (l->m <= LINEAR_FLAT)"),
    M("inv-b", "    if (fabsf(l->m) <= LINEAR_FLAT)" + NL
      + "        return l->b;", "    if (fabsf(l->m) <= LINEAR_FLAT)" + NL
      + "        return y;"),
    M("inv-formula", "    return (y - l->b) / l->m;",
      "    return (y + l->b) / l->m;"),

    # The topology's blocked segment.
    M("blk-dir", "    d.x = a->x - b->x;", "    d.x = b->x - a->x;"),
    M("blk-dir-pad", "    d.pad = a->pad - b->pad;", "    d.pad = 0.0f;"),
    M("blk-short", "    if (len < TOPO_SHORT) {", "    if (len <= TOPO_SHORT) {"),
    M("blk-short-r", "topology_set_interest_bbox3(tc, &mid, len * 0.5f, NULL);",
      "topology_set_interest_bbox3(tc, &mid, len, NULL);"),
    M("blk-short-args",
      "        return topology_segment_intersects(tc, a, b, TOPO_RADIUS);",
      "        return topology_segment_intersects(tc, b, a, TOPO_RADIUS);"),
    M("blk-ceil", "    if (steps < raw)" + NL + "        steps += 1.0f;" + NL,
      ""),
    M("blk-ceil-le", "    if (steps < raw)", "    if (steps <= raw)"),
    M("blk-n0", "    if (n <= 0)" + NL + "        return 0;",
      "    if (n <= 1)" + NL + "        return 0;"),
    M("blk-step", "    step = len / (float)n;",
      "    step = len / (float)(n + 1);"),
    M("blk-frac", "        frac = (float)k / (float)n;",
      "        frac = (float)(k - 1) / (float)n;"),
    M("blk-cur-pad", "        cur.pad = b->pad + d.pad * frac;",
      "        cur.pad = b->pad;"),
    M("blk-mid", "        halfway(&mid, &prev, &cur);",
      "        halfway(&mid, b, &cur);"),
    M("blk-step-r",
      "topology_set_interest_bbox3(tc, &mid, step * 0.5f, NULL);",
      "topology_set_interest_bbox3(tc, &mid, step, NULL);"),
    M("blk-order", "        if (topology_segment_intersects(tc, &cur, &prev,",
      "        if (topology_segment_intersects(tc, &prev, &cur,"),
    M("blk-hit", "TOPO_RADIUS))" + NL + "            return 1;",
      "TOPO_RADIUS))" + NL + "            return 0;"),
    M("blk-prev", "        prev = cur;" + NL + "    }" + NL + "    return 0;",
      "    }" + NL + "    return 0;"),
    M("blk-last", "    for (k = 1; k <= n; k++) {",
      "    for (k = 1; k < n; k++) {"),

    # tSpikeStrip's centre.
    M("ctr-loop", "    for (i = 0; i < n; i++) {" + NL
      + "        const bVector4 *v = &s->Elements[i]",
      "    for (i = 0; i < n - 1; i++) {" + NL
      + "        const bVector4 *v = &s->Elements[i]"),
    M("ctr-sum", "        sum.z += v->z;" + NL + "        sum.pad += v->w;",
      "        sum.z += v->y;" + NL + "        sum.pad += v->w;"),
    M("ctr-n", "    if (n >= 2) {", "    if (n >= 3) {"),
    M("ctr-k", "        float k = 1.0f / (float)n;",
      "        float k = 1.0f / (float)(n + 1);"),
    M("ctr-y", "        out->y = sum.y * k;" + NL + "        out->z = sum.z * k;"
      + NL + "        out->pad = sum.pad * k;" + NL + "    } else",
      "        out->y = sum.y;" + NL + "        out->z = sum.z * k;"
      + NL + "        out->pad = sum.pad * k;" + NL + "    } else"),
]

EQUIVALENT = {
    # The pad lanes reach only SetInterestBBox, which takes x and y, and
    # SegmentIntersects, which takes x, y and z.
    "blk-dir-pad": "the segment's pad lane: nothing reads it",
    "blk-cur-pad": "the step's pad lane: nothing reads it",
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
        todo, SOURCES, "previewstops_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs, flags=build_flags())
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
