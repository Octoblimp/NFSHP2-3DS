#!/usr/bin/env python3
"""Cross-check 3DS Files/source/racecore.c, Race's construction, against
the retail image itself, run in mipsemu.

The model is the image. Race's constructor (0x001475e8) and destructor
(0x001476e0), FigureOutBoundaries (0x00147b20), AddBoundaryPosition
(0x001479f8), GetLapNumberExact (0x00147d58), SetupGhostCars
(0x001485e0), RacingCar's constructor (0x001493b8) and UnInit, and
TimeAroundTrackTable's constructor (0x001467a0), GetTimeTableEntry,
GetTimeAroundTrack and destructor run as shipped, and so do
TrackPathCoordinate's two constructors and destructor,
TrackPathManager::ComparePercentDistances, TrackRoutePoint::GetPosition
and bScaleAdd under them. The harness (tools/src/racecore_test.c) runs the
port over the same script, and the two transcripts are diffed.

Everything else is a stub that prints its arguments: TrackPathCoordinate::
UpdatePosition, GetTrackPositionMarker, __builtin_delete and WorldObject's
destructor; bMemSet is native. UpdatePosition answers from mix(), a hash
of the position that the harness computes the same way, as the distance
round a track one unit long -- either anywhere in 2^-7 .. 2^9 of either
sign, or (S umode 1) in [0, 1), as a real track's would be.

The script lays out the rest at retail's offsets: the Race, the table,
TheRaceParameters' TrackDirection (+12), Point2Point (+40) and
NumLapsInRace (+44), pCurrentRace (gp-22272), eight position markers, and
four TrackRoutes on TheTrackRouteManager's racing list (0x00314438). The
Race and the table are filled with 0xa5 before they are built, so a field
a constructor leaves alone shows.

Before the run, Race and TimeAroundTrackTable are asserted in an ARM
compile of racecore.h, when devkitARM is there.

    python tools/racecore_check.py
    python tools/racecore_check.py --mutate [--only a,b]
    python tools/racecore_check.py --dump out/racecore
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
import retail_model
from mipsemu import M32, f_to_bits, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/racecore_test.c"
RCC = "3DS Files/source/racecore.c"
RCH = "3DS Files/source/racecore.h"
RCE = "3DS Files/source/race.c"
SOURCES = [HARNESS, RCC, RCE,
           "3DS Files/source/trackroute.c",
           "3DS Files/source/trackpath.c",
           "3DS Files/source/quickspline.c",
           "3DS Files/source/bmem.c",
           "3DS Files/source/bmatrix.c",
           "3DS Files/source/bvector.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c",
           "3DS Files/source/bchunk.c"]

HARNESS_TIMEOUT = 120

ARM_GCC = Path("C:/devkitPro/devkitARM/bin/arm-none-eabi-gcc.exe")
CTRU_INCLUDE = Path("C:/devkitPro/libctru/include")

# ================================================================ the image

GP = 0x003358f0
TATT_CTOR = 0x001467a0
TATT_ENTRY = 0x00146ae8
TATT_TIME = 0x00146b90
TATT_DTOR = 0x001494c8
RACE_CTOR = 0x001475e8
RACE_DTOR = 0x001476e0
ADD_BOUNDARY = 0x001479f8
FIGURE = 0x00147b20
LAP_EXACT = 0x00147d58
SETUP_GHOST = 0x001485e0
RC_CTOR = 0x001493b8
UNINIT = 0x00146c88

UPDATE_POS = 0x002087f8
TPC_DTOR = 0x00208748
GET_MARKER = 0x00151478
DELETE = 0x00114e98
WO_DTOR = 0x001cd828
B_MEMSET = 0x00250340

G_RACE = GP - 22272

RP = 0x0031a898
RP_DIR = RP + 12
RP_P2P = RP + 40
RP_LAPS = RP + 44

ROUTE_MGR = 0x00314438      # the racing list's head; the traffic one's at +8

RACE_BYTES = 1716
RC_BYTES = 192
TATT_BYTES = 2052
ROUTE_POINTS = 1064
POINT_BYTES = 112
NLINE = 21

MISC = 0x01000000
RACE = MISC
TATT = MISC + 0x1000
GHOSTS = MISC + 0x2000
NGHOST = 4
WOBJS = MISC + 0x2200
NWOBJ = 2
MARKERS = MISC + 0x2400
NMARK = 8
POSBUF = MISC + 0x2600
OUTBUF = MISC + 0x2610
NAMES = MISC + 0x2800
ROUTES = 0x01200000
ROUTE_STRIDE = 0x20000
NROUTE = 4
MAX_POINTS = 40

PATTERN = 0xa5

MARKER_NAMES = ("ForwardStartLine", "BackwardStartLine", "ForwardFinishLine",
                "BackwardFinishLine", "SplitTimeBoundary1",
                "SplitTimeBoundary2", "SplitTimeBoundary3", "Nowhere")


def arm_layout_check():
    """Race and TimeAroundTrackTable in an ARM compile of racecore.h.
    Returns 0 when they hold or devkitARM is not there."""
    if not ARM_GCC.exists():
        print("devkitARM not found; the ARM layout check is skipped")
        return 0
    lines = [
        "#include <stddef.h>",
        "#include \"racecore.h\"",
        "_Static_assert(sizeof(struct RacingCar) == 192, \"rc\");",
        "_Static_assert(sizeof(Race) == 1716, \"race\");",
        "_Static_assert(offsetof(Race, BoundaryDistances) == 1620, \"bd\");",
        "_Static_assert(offsetof(Race, pTimeAroundTrackTable) == 1712, \"t\");",
        "_Static_assert(sizeof(TimeTableEntry) == 8, \"entry\");",
        "_Static_assert(offsetof(TimeAroundTrackTable, EntryTable) == 4, \"et\");",
        "_Static_assert(sizeof(TimeAroundTrackTable) == 2052, \"tatt\");",
    ]
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "racecore_layout.c"
        src.write_text(NL.join(lines) + NL)
        r = subprocess.run(
            [str(ARM_GCC), "-fsyntax-only", "-march=armv6k", "-mtune=mpcore",
             "-mfloat-abi=hard", "-std=c11", "-I",
             str(ROOT / "3DS Files/source"), "-I", str(CTRU_INCLUDE),
             str(src)],
            capture_output=True, text=True)
    if r.returncode != 0:
        print("the ARM layout check failed:")
        print((r.stderr or r.stdout)[:3000])
        return 1
    print("ARM layout: Race is 1716 bytes with BoundaryDistances at 1620, "
          "TimeAroundTrackTable 2052")
    return 0


def fx(w):
    """A float's bits, with every NaN the one "nan"."""
    w &= M32
    if (w & 0x7f800000) == 0x7f800000 and (w & 0x7fffff):
        return "nan"
    return "%08x" % w


def mixw(a, b, salt, seed):
    h = (a * 0x9e3779b1 + b * 0x85ebca77 + salt * 0xc2b2ae3d
         + seed * 0x27d4eb2f) & M32
    return h ^ (h >> 15)


def mixf(a, b, salt, seed):
    h = mixw(a, b, salt, seed)
    return (h & 0x807fffff) | ((120 + ((h >> 23) & 15)) << 23)


def unitf(a, b, salt, seed):
    """[0, 1) in steps of 2^-24, exactly as the harness rounds it."""
    h = mixw(a, b, salt, seed) & 0xffffff
    return f_to_bits(h / 16777216.0)


def route_at(r):
    return ROUTES + ROUTE_STRIDE * r


def point_at(r, k):
    return route_at(r) + ROUTE_POINTS + POINT_BYTES * k


def marker_at(k):
    return MARKERS + 24 * k


def sb(v):
    return v - 256 if v > 127 else v


def sh(v):
    return v - 65536 if v > 32767 else v


# ============================================================ the scenarios


def h(w):
    return "0x%08x" % (w & M32)


def rbits(rnd, lo=-900.0, hi=900.0):
    return f_to_bits(rnd.uniform(lo, hi))


DISTS = (0.0, -0.0, 5.0, 33.0, 66.0, 95.0, 100.0, 100.5, 150.0, 199.0,
         200.0, 250.0, -1.0, -0.5, 1e-30, 99.99999)


def rdist(rnd):
    if rnd.random() < 0.5:
        return f_to_bits(rnd.choice(DISTS))
    return f_to_bits(rnd.uniform(-150.0, 260.0))


def s_markers(rnd, p_on=0.5):
    out = []
    for k in range(NMARK):
        if rnd.random() < p_on:
            out.append("M %d %s %s" % (k, h(rbits(rnd)), h(rbits(rnd))))
        else:
            out.append("X %d" % k)
    return out


def s_params(rnd):
    out = []
    if rnd.random() < 0.6:
        out.append("S dir %d" % rnd.choice((0, 0, 1, 1, 2, -1)))
    if rnd.random() < 0.6:
        out.append("S p2p %d" % rnd.choice((0, 0, 1, 1, 2, -1)))
    if rnd.random() < 0.5:
        out.append("S laps %d" % rnd.choice((0, 1, 2, 2, 3, 5, -1, 10)))
    if rnd.random() < 0.4:
        out.append("S seed %d" % rnd.randrange(1 << 16))
    if rnd.random() < 0.4:
        out.append("S umode %d" % rnd.choice((0, 1)))
    return out


def s_construct(rnd):
    """The constructor over every marker set, direction, Point2Point and
    lap count, and FigureOutBoundaries again after a change."""
    out = []
    for case in range(90):
        out += s_params(rnd)
        if rnd.random() < 0.7:
            out += s_markers(rnd, rnd.choice((0.0, 0.3, 0.6, 0.9, 1.0)))
        out.append("N")
        if rnd.random() < 0.3:
            out += s_params(rnd)
            out += s_markers(rnd)
            out.append("F")
    return out


def s_add(rnd):
    """AddBoundaryPosition on its own, at every count up to eight."""
    out = []
    out.append("N")
    for case in range(80):
        if rnd.random() < 0.3:
            out += s_markers(rnd)
        if rnd.random() < 0.2:
            out.append("S seed %d" % rnd.randrange(1 << 16))
        if rnd.random() < 0.2:
            out.append("S umode %d" % rnd.choice((0, 1)))
        out.append("SN %d" % rnd.randrange(9))
        out.append("A %d %s" % (rnd.randrange(NMARK), h(rdist(rnd))))
    return out


PCTS = (0.0, -0.0, 5.0, 50.0, 49.999, 50.001, -50.0, -50.001, 100.0, 99.0,
        150.0, -150.0, 1000.0, 0.01)


def rpct(rnd):
    if rnd.random() < 0.4:
        return f_to_bits(rnd.choice(PCTS))
    return f_to_bits(rnd.uniform(-160.0, 260.0))


def s_lap(rnd):
    """GetLapNumberExact from every finish line, -1 among them."""
    out = []
    for case in range(30):
        out += s_params(rnd)
        out += s_markers(rnd)
        out.append("N")
        for _ in range(rnd.randrange(1, 4)):
            if rnd.random() < 0.4:
                out.append("SF %d" % rnd.choice((-1, 0, 1, 2, 3, 4)))
            if rnd.random() < 0.4:
                out.append("SB %d %s" % (rnd.randrange(5), h(rpct(rnd))))
            for _ in range(rnd.randrange(1, 5)):
                out.append("L %s" % h(rpct(rnd)))
    return out


def s_destroy(rnd):
    """The destructor over every set of ghost pointers and flags."""
    out = []
    for case in range(40):
        if rnd.random() < 0.5:
            out.append("N")
        out.append("G %d %d %d %d %d" % tuple(
            rnd.choice((-1, -1, k, k, 6, 7)) for k in range(5)))
        out.append("D %d" % rnd.choice((0, 1, 2, 3, 1)))
        if rnd.random() < 0.5:
            out.append("C")
    return out


FLAGS = (0, 0, 0, 1, 2, 3, 1, 4, 5, 8, 0xfffffffc, 0x80000001)


def s_routes(rnd):
    out = []
    for r in range(NROUTE):
        n = rnd.choice((0, 1, 2, 5, 12, 25, 25, MAX_POINTS, MAX_POINTS, -1))
        out.append("P %d %d" % (r, n))
        valid = rnd.choice((0.0, 0.5, 0.8, 1.0))
        for line in range(NLINE):
            if rnd.random() < valid:
                f = rnd.choice((1, 2, 3, 5, 0x80000002))
            else:
                f = rnd.choice(FLAGS)
            out.append("PL %d %d %d" % (r, line, f))
        x, y = rnd.uniform(-500, 500), rnd.uniform(-500, 500)
        for k in range(max(n, 0)):
            a = rnd.uniform(-math.pi, math.pi)
            step = rnd.choice((0.0, 1.0, 10.0, 40.0, 40.0))
            x += step * math.cos(a)
            y += step * math.sin(a)
            if rnd.random() < 0.1:
                dx, dy = rnd.uniform(-2, 2), rnd.uniform(-2, 2)
            else:
                dx, dy = math.cos(a), math.sin(a)
            out.append("PT %d %d %s %s %s %s %d %d"
                       % (r, k, h(f_to_bits(x)), h(f_to_bits(y)),
                          h(f_to_bits(dx)), h(f_to_bits(dy)),
                          rnd.randrange(-32768, 32768), rnd.randrange(256)))
    order = list(range(NROUTE))
    rnd.shuffle(order)
    order = order[:rnd.choice((0, 1, 2, 3, 4, 4, 4))]
    out.append("Q" + "".join(" %d" % r for r in order))
    return out


LAPS = (0.0, -0.0, 1.0, 0.5, 0.99999994, 1.0 / 256, 255.5 / 256, -1.0,
        2.25, 100.25, 1e6, -1e6, 16777217.0, 3.0 + 1.0 / 512)


def rlap(rnd):
    if rnd.random() < 0.4:
        return f_to_bits(rnd.choice(LAPS))
    return f_to_bits(rnd.uniform(-3.0, 40.0))


def s_tatt(rnd, n):
    """The table over random racing routes, car classes and boundaries,
    then looked up. Point2Point stays 0 and no boundary is poked, so every
    lap the table sees is a number, below 2^31."""
    out = []
    for case in range(n):
        if rnd.random() < 0.3:
            out.append("S seed %d" % rnd.randrange(1 << 16))
        out.append("S umode %d" % rnd.choice((0, 1, 1)))
        out.append("S dir %d" % rnd.choice((0, 1)))
        out.append("S p2p 0")
        if rnd.random() < 0.7:
            out += s_routes(rnd)
        out += s_markers(rnd, rnd.choice((0.0, 0.5, 1.0)))
        out.append("N")
        out.append("T %d" % rnd.randrange(11))
        for _ in range(rnd.randrange(2, 8)):
            out.append("%s %s" % (rnd.choice(("E", "E0", "TA")),
                                  h(rlap(rnd))))
        if rnd.random() < 0.3:
            out.append("TD %d" % rnd.choice((0, 2, 1, 3)))
    return out


def s_walk(rnd, n):
    out = []
    for _ in range(n):
        k = rnd.random()
        if k < 0.15:
            out += s_params(rnd)
        elif k < 0.3:
            out += s_markers(rnd)
        elif k < 0.45:
            out.append("N")
        elif k < 0.55:
            out.append("F")
        elif k < 0.65:
            out.append("L %s" % h(rpct(rnd)))
        elif k < 0.72:
            out.append("SG")
        elif k < 0.8:
            out.append("SN %d" % rnd.randrange(9))
            out.append("A %d %s" % (rnd.randrange(NMARK), h(rdist(rnd))))
        elif k < 0.9:
            out.append("G %d %d %d %d %d" % tuple(
                rnd.choice((-1, k2, 7)) for k2 in range(5)))
            out.append("D %d" % rnd.choice((0, 1, 2, 3)))
            out.append("C")
        else:
            out.append("S p2p 0")
            out.append("N")
            out.append("T %d" % rnd.randrange(11))
            out.append("TA %s" % h(rlap(rnd)))
    return out


def script():
    rnd = random.Random(0x8c3a51d9)
    sc = [s_construct(rnd), s_add(rnd), s_lap(rnd), s_destroy(rnd)]
    for n in (6, 12, 12):
        sc.append(s_tatt(rnd, n))
    for n in (40, 80):
        sc.append(s_walk(rnd, n))
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
        for a, fn in ((UPDATE_POS, self.s_update),
                      (GET_MARKER, self.s_marker),
                      (DELETE, self.s_delete),
                      (WO_DTOR, self.s_wodel),
                      (B_MEMSET, self.s_memset)):
            e.stub(a, fn)
        # TrackPathCoordinate's destructor runs: with flag 2 it returns.
        assert e.u32(TPC_DTOR) == 0x30a50001
        # RacingCar::UnInit is `jr ra`.
        assert e.u32(UNINIT) == 0x03e00008
        for k, nm in enumerate(MARKER_NAMES):
            e.write(NAMES + 32 * k, nm.encode("latin-1") + b"\0")

        self.names = {0: "null", RACE: "R", TATT: "T"}
        for i in range(NGHOST):
            self.names[GHOSTS + 64 * i] = "g%d" % i
        for i in range(NWOBJ):
            self.names[WOBJS + 96 * i] = "o%d" % i
        for i in range(8):
            self.names[RACE + 36 + RC_BYTES * i] = "rc%d" % i
        for k in range(NMARK):
            self.names[marker_at(k)] = "m%d" % k

    def emit(self, s):
        self.out.append(s)

    def name(self, a):
        return self.names.get(a & M32, "?")

    def named(self, k):
        if k < 0:
            return 0
        if k < NGHOST:
            return GHOSTS + 64 * k
        if k < NGHOST + NWOBJ:
            return WOBJS + 96 * (k - NGHOST)
        if k == NGHOST + NWOBJ:
            return RACE + 36
        return TATT

    def arg(self, i):
        return self.e.reg[(4, 5, 6, 7, 8, 9, 10, 11)[i]] & M32

    def w(self, a):
        return self.e.u32(a)

    def fill(self, a, n, byte=PATTERN):
        self.e.write(a, bytes([byte]) * n)

    def cstr(self, a):
        b = bytearray()
        while self.e.mem[a]:
            b.append(self.e.mem[a])
            a += 1
        return b.decode("latin-1")

    # ---- the stubs -------------------------------------------------------

    def s_update(self, e):
        c, pos = self.arg(0), self.arg(1)
        x, y = self.w(pos), self.w(pos + 4)
        if self.umode:
            r = unitf(x, y, 3, self.seed)
        else:
            r = mixf(x, y, 3, self.seed)
        self.emit("  upd %s %s -> %s" % (fx(x), fx(y), fx(r)))
        e.put32(c, x)
        e.put32(c + 4, y)
        e.put32(c + 16, r)
        e.put32(c + 20, r)

    def s_marker(self, e):
        name, i = self.cstr(self.arg(0)), s32(self.arg(1))
        m = 0
        for k in range(NMARK):
            if self.marker_on[k] and i == 0 and name == MARKER_NAMES[k]:
                m = marker_at(k)
        self.emit("  marker %s %d -> %s" % (name, i, self.name(m)))
        return m

    def s_delete(self, e):
        self.emit("  delete %s" % self.name(self.arg(0)))

    def s_wodel(self, e):
        self.emit("  wodel %s %d" % (self.name(self.arg(0)),
                                     s32(self.arg(1))))

    def s_memset(self, e):
        a, v, n = self.arg(0), self.arg(1), s32(self.arg(2))
        e.mem[a:a + n] = bytes([v & 0xff]) * n
        return a

    # ---- the state -------------------------------------------------------

    def reset(self):
        e = self.e
        self.fill(RACE, RACE_BYTES)
        self.fill(TATT, TATT_BYTES)
        for r in range(NROUTE):
            e.write(route_at(r), bytes(ROUTE_POINTS))
        e.put32(ROUTE_MGR, ROUTE_MGR)
        e.put32(ROUTE_MGR + 4, ROUTE_MGR)
        e.put32(ROUTE_MGR + 8, ROUTE_MGR + 8)
        e.put32(ROUTE_MGR + 12, ROUTE_MGR + 8)
        e.write(MARKERS, bytes(24 * NMARK))
        self.marker_on = [0] * NMARK
        self.fill(POSBUF, 8)
        e.put32(RP_DIR, 0)
        e.put32(RP_P2P, 0)
        e.put32(RP_LAPS, 2)
        e.put32(G_RACE, 0)
        self.seed = 0
        self.umode = 0

    def set_global(self, f, v):
        regs = {"dir": RP_DIR, "p2p": RP_P2P, "laps": RP_LAPS}
        if f in regs:
            self.e.put32(regs[f], v & M32)
        elif f == "seed":
            self.seed = v & M32
        elif f == "umode":
            self.umode = v
        else:
            raise SystemExit("bad global %s" % f)

    # ---- the dumps -------------------------------------------------------

    def dump_race(self):
        e, w = self.e, self.w
        r = RACE
        self.emit("  race st %d go %d cd %d t %08x %08x %08x n %d fin %d "
                  "one %d laps %d force %d %d"
                  % (s32(w(r)), s32(w(r + 4)), s32(w(r + 8)), w(r + 12),
                     w(r + 16), w(r + 20), s32(w(r + 24)), s32(w(r + 28)),
                     s32(w(r + 32)), s32(w(r + 1604)), s32(w(r + 1608)),
                     s32(w(r + 1612))))
        nb = sh(e.mem[r + 1616] | (e.mem[r + 1617] << 8))
        self.emit("  bound n %d s %d f %d d %s"
                  % (nb, sb(e.mem[r + 1618]), sb(e.mem[r + 1619]),
                     " ".join(fx(w(r + 1620 + 4 * i)) for i in range(5))))
        self.emit("  lines %s %s %s %s"
                  % tuple(fx(w(r + 1640 + 4 * i)) for i in range(4)))
        self.emit("  ghost %s %s %s %s tatt %s cur %s"
                  % (self.name(w(r + 1656)), self.name(w(r + 1660)),
                     self.name(w(r + 1664)), self.name(w(r + 1668)),
                     self.name(w(r + 1712)), self.name(w(G_RACE))))
        self.emit("  name" + bytes(e.mem[r + 1672:r + 1712]).hex())
        self.emit("  cars" + "".join(" " + self.name(w(r + 1572 + 4 * i))
                                     for i in range(8)))
        for i in range(8):
            c = r + 36 + RC_BYTES * i
            m = e.mem

            def h16(o):
                return sh(m[c + o] | (m[c + o + 1] << 8))
            self.emit("  rc%d %s %d %d %s %d %d %s %s %s %s"
                      % (i, self.name(w(c)), h16(4), h16(6),
                         " ".join("%d" % sb(m[c + o]) for o in range(8, 16)),
                         h16(16), h16(18), fx(w(c + 20)), fx(w(c + 24)),
                         fx(w(c + 28)), fx(w(c + 32))))
            self.emit("  rc%d t %s | %s | %x %s %s"
                      % (i, " ".join("%x" % w(c + 36 + 4 * k)
                                     for k in range(25)),
                         " ".join("%x" % w(c + 136 + 4 * k)
                                  for k in range(11)),
                         w(c + 180), fx(w(c + 184)), fx(w(c + 188))))

    def dump_tatt(self):
        w = self.w
        self.emit("  tatt total %s" % fx(w(TATT)))
        for i in range(0, 256, 8):
            self.emit("  t%03d" % i + "".join(
                " %s:%s" % (fx(w(TATT + 4 + 8 * k)), fx(w(TATT + 8 + 8 * k)))
                for k in range(i, i + 8)))

    # ---- the ops ---------------------------------------------------------

    def call(self, fn, *args, **kw):
        e = self.e
        sp = e.reg[29] & M32
        e.write(sp - 0x4000, bytes(0x4000))
        for i, v in kw.get("f", {}).items():
            e.fpr[i] = v & M32
        return e.call(fn, *args, limit=4000000)

    def link_routes(self, order):
        e = self.e
        nodes = [route_at(r) for r in order]
        ring = [ROUTE_MGR] + nodes
        for i, a in enumerate(ring):
            e.put32(a, ring[(i + 1) % len(ring)])
            e.put32(a + 4, ring[i - 1])

    def point(self, r, k, n):
        e = self.e
        p = point_at(r, k)
        for i in range(4):
            e.put32(p + (0, 4, 12, 16)[i], n[i] & M32)
        for line in range(NLINE):
            e.write(p + 48 + 2 * line,
                    struct.pack("<H", (n[4] + 37 * line) & 0xffff))
            e.mem[p + 90 + line] = (n[5] + 13 * line) & 0xff

    def op(self, t):
        e = self.e
        c = t[0]
        if c == "S":
            self.set_global(t[1], int(t[2], 0))
            return
        n = [int(x, 0) for x in t[1:]]
        if c == "M":
            self.marker_on[n[0]] = 1
            e.put32(marker_at(n[0]) + 16, n[1])
            e.put32(marker_at(n[0]) + 20, n[2])
        elif c == "X":
            self.marker_on[n[0]] = 0
        elif c == "N":
            self.fill(RACE, RACE_BYTES)
            v = self.call(RACE_CTOR, RACE)
            self.emit("  -> %s" % self.name(v))
            self.dump_race()
        elif c == "F":
            self.call(FIGURE, RACE)
            self.dump_race()
        elif c == "SN":
            e.write(RACE + 1616, struct.pack("<h", n[0]))
        elif c == "SB":
            e.put32(RACE + 1620 + 4 * n[0], n[1])
        elif c == "SF":
            e.mem[RACE + 1619] = n[0] & 0xff
        elif c == "A":
            v = self.call(ADD_BOUNDARY, RACE, NAMES + 32 * n[0], POSBUF,
                          f={12: n[1]})
            self.emit("  -> %d %s %s" % (v, fx(self.w(POSBUF)),
                                         fx(self.w(POSBUF + 4))))
            self.dump_race()
        elif c == "L":
            self.call(LAP_EXACT, RACE, f={12: n[0]})
            self.emit("  -> %s" % fx(e.fpr[0]))
        elif c == "G":
            for i, off in enumerate((1656, 1660, 1664, 1668, 1712)):
                e.put32(RACE + off, self.named(n[i]))
        elif c == "D":
            self.call(RACE_DTOR, RACE, n[0] & M32)
            self.emit("  cur %s" % self.name(self.w(G_RACE)))
        elif c == "C":
            e.put32(G_RACE, RACE)
        elif c == "SG":
            self.call(SETUP_GHOST, RACE)
            self.dump_race()
        elif c == "P":
            e.put32(route_at(n[0]) + 16, n[1] & M32)
        elif c == "PL":
            e.put32(route_at(n[0]) + 40 + 48 * n[1], n[2] & M32)
        elif c == "PT":
            self.point(n[0], n[1], n[2:])
        elif c == "Q":
            self.link_routes(n)
        elif c == "T":
            self.fill(TATT, TATT_BYTES)
            v = self.call(TATT_CTOR, TATT, n[0] & M32)
            self.emit("  -> %s" % self.name(v))
            self.dump_tatt()
        elif c in ("E", "E0"):
            e.put32(OUTBUF, 0xa5a5a5a5)
            v = self.call(TATT_ENTRY, TATT, 0 if c == "E0" else OUTBUF,
                          f={12: n[0]})
            self.emit("  -> %d %s" % ((s32(v) - (TATT + 4)) // 8,
                                      fx(self.w(OUTBUF))))
        elif c == "TA":
            self.call(TATT_TIME, TATT, f={12: n[0]})
            self.emit("  -> %s" % fx(e.fpr[0]))
        elif c == "TD":
            self.call(TATT_DTOR, TATT, n[0] & M32)
            self.emit("  done")
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


def build_harness(tmp, name="racecore_test"):
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


def M(name, rel, before, after=None):
    return (name, rel, before, after)


MUTATIONS = [
    # ---- the boundary helpers
    M("boundary_at_next", RCC,
      "               + 4 * i, sizeof f);",
      "               + 4 * (i + 1), sizeof f);"),
    M("boundary_at_array", RCC,
      """    memcpy(&f, (const unsigned char *)r + offsetof(Race, BoundaryDistances)
                   + 4 * i, sizeof f);
    return f;""",
      """    (void)f;
    return r->BoundaryDistances[i < 0 ? 0 : i];"""),
    M("boundary_set_next", RCC,
      "+ 4 * i, &f,", "+ 4 * (i + 1), &f,"),

    # ---- the driving line
    M("line_offset_shift", RCC,
      "DrivingLineOffsets[line] * 256)", "DrivingLineOffsets[line] * 128)"),
    M("line_offset_unsigned", RCC,
      "(int32_t)p->DrivingLineOffsets[line]",
      "(int32_t)(uint16_t)p->DrivingLineOffsets[line]"),
    M("line_offset_scale", RCC,
      """    return (float)((int32_t)p->DrivingLineOffsets[line] * 256)
           * (1.0f / 65536.0f);""",
      """    return (float)((int32_t)p->DrivingLineOffsets[line] * 256)
           * (1.0f / 32768.0f);"""),
    M("line_speed_shift", RCC,
      "DrivingLineSpeeds[line] << 16)", "DrivingLineSpeeds[line] << 15)"),
    M("line_speed_signed", RCC,
      "(int32_t)p->DrivingLineSpeeds[line]",
      "(int32_t)(int8_t)p->DrivingLineSpeeds[line]"),

    # ---- TimeAroundTrackTable's constructor
    M("tatt_line_class", RCC,
      "int   line = car_class * 2;", "int   line = car_class;"),
    M("tatt_line_odd", RCC,
      "int   line = car_class * 2;", "int   line = car_class * 2 + 1;"),
    M("tatt_no_memset", RCC,
      "    memset(t->EntryTable, 0, sizeof t->EntryTable);", ""),
    M("tatt_memset_short", RCC,
      "    memset(t->EntryTable, 0, sizeof t->EntryTable);",
      "    memset(t->EntryTable, 0, sizeof t->EntryTable - 8);"),
    M("tatt_total_zero", RCC,
      "    t->TotalTimeAroundTrack = 0.0f;", ""),
    M("tatt_valid_only", RCC,
      "if (!(flags & DLI_IS_VALID) && !(flags & DLI_IS_FAKE))",
      "if (!(flags & DLI_IS_VALID))"),
    M("tatt_fake_only", RCC,
      "if (!(flags & DLI_IS_VALID) && !(flags & DLI_IS_FAKE))",
      "if (!(flags & DLI_IS_FAKE))"),
    M("tatt_flags_or", RCC,
      "if (!(flags & DLI_IS_VALID) && !(flags & DLI_IS_FAKE))",
      "if (!(flags & DLI_IS_VALID) || !(flags & DLI_IS_FAKE))"),
    M("tatt_flags_any", RCC,
      "if (!(flags & DLI_IS_VALID) && !(flags & DLI_IS_FAKE))",
      "if (!flags)"),
    M("tatt_one_route", RCC,
      "    for (i = 0; i < m->NumRacing; i++) {",
      "    for (i = 0; i < m->NumRacing && i < 1; i++) {"),
    M("tatt_last_segment", RCC,
      "for (k = 0; k < r->NumPoints - 1; k++) {",
      "for (k = 0; k < r->NumPoints - 2; k++) {"),
    M("tatt_first_segment", RCC,
      "for (k = 0; k < r->NumPoints - 1; k++) {",
      "for (k = 1; k < r->NumPoints - 1; k++) {"),
    M("tatt_p1_offset_p0", RCC,
      "trpoint_get_position2(p1, &b, 0.0f, line_offset(p1, line));",
      "trpoint_get_position2(p1, &b, 0.0f, line_offset(p0, line));"),
    M("tatt_p0_offset_line", RCC,
      "trpoint_get_position2(p0, &a, 0.0f, line_offset(p0, line));",
      "trpoint_get_position2(p0, &a, 0.0f, line_offset(p0, line + 1));"),
    M("tatt_p0_distance", RCC,
      "trpoint_get_position2(p0, &a, 0.0f, line_offset(p0, line));",
      "trpoint_get_position2(p0, &a, 1.0f, line_offset(p0, line));"),
    M("tatt_p0_no_offset", RCC,
      "trpoint_get_position2(p0, &a, 0.0f, line_offset(p0, line));",
      "trpoint_get_position2(p0, &a, 0.0f, 0.0f);"),
    M("tatt_lap0_scale", RCC,
      """                                             c.RatioAroundTrack * 100.0f);
            trackpath_coord_update_position(&c, &b);""",
      """                                             c.RatioAroundTrack * 10.0f);
            trackpath_coord_update_position(&c, &b);"""),
    M("tatt_lap1_scale", RCC,
      """                                             c.RatioAroundTrack * 100.0f);

            // Across""",
      """                                             c.RatioAroundTrack * 10.0f);

            // Across"""),
    M("tatt_lap1_at_a", RCC,
      "trackpath_coord_update_position(&c, &b);",
      "trackpath_coord_update_position(&c, &a);"),
    M("tatt_wrap_threshold", RCC,
      "if (0.5f < dlap) {", "if (0.4f < dlap) {"),
    M("tatt_wrap_lap0_down", RCC,
      "                lap0 += 1.0f;", "                lap0 -= 1.0f;"),
    M("tatt_wrap_stale", RCC,
      """                lap0 += 1.0f;
                dlap = lap1 - lap0;""",
      """                lap0 += 1.0f;"""),
    M("tatt_wrap2_threshold", RCC,
      "} else if (0.5f < lap0 - lap1) {", "} else if (0.6f < lap0 - lap1) {"),
    M("tatt_wrap2_lap0", RCC,
      "                lap1 += 1.0f;", "                lap0 -= 1.0f;"),
    M("tatt_wrap2_stale", RCC,
      """                lap1 += 1.0f;
                dlap = lap1 - lap0;""",
      """                lap1 += 1.0f;"""),
    M("tatt_no_wrap", RCC,
      "if (0.5f < dlap) {", "if (0) {"),
    M("tatt_dy_from_x", RCC,
      "dy = a.y - b.y;", "dy = a.x - b.y;"),
    M("tatt_no_sqrt", RCC,
      "dist = sqrtf(dx * dx + dy * dy);", "dist = dx * dx + dy * dy;"),
    M("tatt_dist_x_only", RCC,
      "dist = sqrtf(dx * dx + dy * dy);", "dist = sqrtf(dx * dx);"),
    M("tatt_rate_flat", RCC,
      "rate = dlap / (dist / line_speed(p0, line));",
      "rate = dlap * dist / line_speed(p0, line);"),
    M("tatt_rate_reassoc", RCC,
      "rate = dlap / (dist / line_speed(p0, line));",
      "rate = dlap * line_speed(p0, line) / dist;"),
    M("tatt_rate_p1_speed", RCC,
      "rate = dlap / (dist / line_speed(p0, line));",
      "rate = dlap / (dist / line_speed(p1, line));"),
    M("tatt_entry_lap1", RCC,
      "e = tatt_get_time_table_entry(t, lap0, NULL);",
      "e = tatt_get_time_table_entry(t, lap1, NULL);"),
    M("tatt_rate_any", RCC,
      "if (0.0f < rate && e->Rate == 0.0f)",
      "if (rate != 0.0f && e->Rate == 0.0f)"),
    M("tatt_rate_last", RCC,
      "if (0.0f < rate && e->Rate == 0.0f)", "if (0.0f < rate)"),
    M("tatt_prev_init", RCC,
      "prev = 1.0f / 180.0f;", "prev = 1.0f / 160.0f;"),
    M("tatt_time_after", RCC,
      """        e->Time = time;
        if (rate == 0.0f) {
            e->Rate = prev;
            rate = prev;
        }
        time += (1.0f / 256.0f) / rate;""",
      """        if (rate == 0.0f) {
            e->Rate = prev;
            rate = prev;
        }
        time += (1.0f / 256.0f) / rate;
        e->Time = time;"""),
    M("tatt_fill_rate_kept", RCC,
      """            e->Rate = prev;
            rate = prev;""",
      """            rate = prev;"""),
    M("tatt_fill_rate_default", RCC,
      """            e->Rate = prev;
            rate = prev;""",
      """            e->Rate = 1.0f / 180.0f;
            rate = 1.0f / 180.0f;"""),
    M("tatt_prev_kept", RCC,
      "        prev = rate;", ""),
    M("tatt_step", RCC,
      "time += (1.0f / 256.0f) / rate;", "time += (1.0f / 255.0f) / rate;"),
    M("tatt_step_mul", RCC,
      "time += (1.0f / 256.0f) / rate;", "time += (1.0f / 256.0f) * rate;"),
    M("tatt_total", RCC,
      "t->TotalTimeAroundTrack = time;",
      "t->TotalTimeAroundTrack = time - prev;"),
    M("tatt_return", RCC,
      """    t->TotalTimeAroundTrack = time;
    return t;""",
      """    t->TotalTimeAroundTrack = time;
    return NULL;"""),
    M("tatt_destroy_flag", RCC,
      """    if (flags & 1)
        bFree(t);""",
      """    if (flags & 2)
        bFree(t);"""),

    # ---- GetTimeTableEntry
    M("entry_no_clamp", RCC,
      """    if (lap < 0.0f)
        lap = 0.0f;""", ""),
    M("entry_clamp_abs", RCC,
      """    if (lap < 0.0f)
        lap = 0.0f;""",
      """    if (lap < 0.0f)
        lap = -lap;"""),
    M("entry_slot_255", RCC,
      "slot = ee_trunc_w(frac * 256.0f);", "slot = ee_trunc_w(frac * 255.0f);"),
    M("entry_slot_round", RCC,
      "slot = ee_trunc_w(frac * 256.0f);",
      "slot = ee_trunc_w(frac * 256.0f + 0.5f) & 255;"),
    M("entry_index_before", RCC,
      "e = &t->EntryTable[slot];",
      "e = &t->EntryTable[slot ? slot - 1 : 0];"),
    M("entry_no_total", RCC,
      "float before = whole * t->TotalTimeAroundTrack + e->Time;",
      "float before = whole + e->Time;"),
    M("entry_no_time", RCC,
      "float before = whole * t->TotalTimeAroundTrack + e->Time;",
      "float before = whole * t->TotalTimeAroundTrack;"),
    M("entry_into_slot", RCC,
      "(frac - (float)slot * (1.0f / 256.0f)) / e->Rate;",
      "(frac - (float)slot * (1.0f / 255.0f)) / e->Rate;"),
    M("entry_into_whole", RCC,
      "(frac - (float)slot * (1.0f / 256.0f)) / e->Rate;",
      "frac / e->Rate;"),
    M("entry_into_mul", RCC,
      "(frac - (float)slot * (1.0f / 256.0f)) / e->Rate;",
      "(frac - (float)slot * (1.0f / 256.0f)) * e->Rate;"),
    M("entry_no_into", RCC,
      "*time = before + into;", "*time = before; (void)into;"),
    M("entry_time_skipped", RCC,
      "    if (time) {", "    if (time && 0) {"),
    M("time_around_next_lap", RCC,
      "tatt_get_time_table_entry(t, lap, &time);",
      "tatt_get_time_table_entry(t, lap + 1.0f, &time);"),

    # ---- RacingCar's constructor
    M("rc_bct", RCC,
      "        rc->BoundaryCrossingTimes[i].PackedTime = 0;", ""),
    M("rc_bct_four", RCC,
      """    for (i = 0; i < 5; i++)
        rc->BoundaryCrossingTimes[i]""",
      """    for (i = 0; i < 4; i++)
        rc->BoundaryCrossingTimes[i]"""),
    M("rc_running", RCC,
      "        rc->RunningTimes[i].PackedTime = 0;", ""),
    M("rc_prev_running", RCC,
      "        rc->PreviousRunningTimes[i].PackedTime = 0;", ""),
    M("rc_best", RCC,
      "        rc->BestRunningTimes[i].PackedTime = 0;", ""),
    M("rc_prev_best", RCC,
      """    for (i = 0; i < 5; i++)
        rc->PreviousBestRunningTimes[i]""",
      """    for (i = 1; i < 5; i++)
        rc->PreviousBestRunningTimes[i]"""),
    M("rc_laps_ten", RCC,
      "for (i = 0; i < 11; i++)", "for (i = 0; i < 10; i++)"),
    M("rc_race_time", RCC,
      "    rc->RaceTime.PackedTime = 0;", ""),
    M("rc_laps_value", RCC,
      "rc->LapTimes[i].PackedTime = 0;", "rc->LapTimes[i].PackedTime = 1;"),

    # ---- Race's constructor
    M("ctor_seven_cars", RCC,
      """    for (i = 0; i < RACE_MAX_RACING_CARS; i++)
        racingcar_construct""",
      """    for (i = 0; i < RACE_MAX_RACING_CARS - 1; i++)
        racingcar_construct"""),
    M("ctor_not_current", RCC,
      "    pCurrentRace = r;", "    pCurrentRace = NULL;"),
    M("ctor_stage", RCC,
      "r->RaceStage = RACE_STAGE_NONE;",
      "r->RaceStage = (eRaceStage)(RACE_STAGE_NONE + 1);"),
    M("ctor_laps_or", RCC,
      "if (RaceParametersNumLapsInRace && RaceParametersPoint2Point)",
      "if (RaceParametersNumLapsInRace || RaceParametersPoint2Point)"),
    M("ctor_laps_p2p_only", RCC,
      "if (RaceParametersNumLapsInRace && RaceParametersPoint2Point)",
      "if (RaceParametersPoint2Point)"),
    M("ctor_laps_p2p_one", RCC,
      "if (RaceParametersNumLapsInRace && RaceParametersPoint2Point)",
      "if (RaceParametersNumLapsInRace && RaceParametersPoint2Point == 1)"),
    M("ctor_laps_two", RCC,
      "        r->NumLapsInRace = 1;", "        r->NumLapsInRace = 2;"),
    M("ctor_force_pos", RCC,
      "    r->ForceRaceFinishPosition = 0;", ""),
    M("ctor_force_player", RCC,
      "    r->ForceRaceFinishPlayerNum = 0;", ""),
    M("ctor_start_time", RCC,
      [("""    r->StartTime.PackedTime = 0;
    r->RaceTime.PackedTime = 0;
    r->BestLapTime""", """    r->RaceTime.PackedTime = 0;
    r->BestLapTime"""),
       ("""    r->StartTime.PackedTime = 0;
    r->RaceTime.PackedTime = 0;
    r->NumRacingCars""", """    r->RaceTime.PackedTime = 0;
    r->NumRacingCars""")]),
    M("ctor_race_time", RCC,
      [("""    r->RaceTime.PackedTime = 0;
    r->BestLapTime""", """    r->BestLapTime"""),
       ("""    r->RaceTime.PackedTime = 0;
    r->NumRacingCars""", """    r->NumRacingCars""")]),
    M("ctor_best_first", RCC,
      "    r->BestLapTime.PackedTime = 0;", ""),
    M("ctor_num_cars", RCC,
      "    r->NumRacingCars = 0;", ""),
    M("ctor_num_finished", RCC,
      "    r->NumRacingCarsFinished = 0;", ""),
    M("ctor_one_remaining", RCC,
      "    r->DetectedOneCarRemaining = 0;", ""),
    M("ctor_wobj", RCC,
      "    r->pReplayingGhostCarWorldObject = NULL;", ""),
    M("ctor_replaying", RCC,
      "    r->pReplayingGhostCarData = NULL;", ""),
    M("ctor_capturing_car", RCC,
      "    r->pCapturingGhostCar = NULL;", ""),
    M("ctor_capturing_data", RCC,
      "    r->pCapturingGhostCarData = NULL;", ""),
    M("ctor_countdown", RCC,
      "    r->StartCountdownTimeFrames = 0;", ""),
    M("ctor_go", RCC,
      "    r->StartGoTimeFrames = 0;", ""),
    M("ctor_start_line_x", RCC,
      "    r->StartLinePosition.x = 0.0f;", ""),
    M("ctor_best_lap", RCC,
      "r->BestLapTime.PackedTime = 0x7fffffffu;",
      "r->BestLapTime.PackedTime = 0x7ffffffeu;"),
    M("ctor_no_boundaries", RCC,
      """    race_figure_out_boundaries(r);
    r->pTimeAroundTrackTable = NULL;""",
      """    r->pTimeAroundTrackTable = NULL;"""),
    M("ctor_tatt", RCC,
      "    r->pTimeAroundTrackTable = NULL;", ""),
    M("ctor_return", RCC,
      """    r->pTimeAroundTrackTable = NULL;
    return r;""",
      """    r->pTimeAroundTrackTable = NULL;
    return NULL;"""),

    # ---- Race's destructor
    M("dtor_replaying_kept", RCC,
      "        bFree(r->pReplayingGhostCarData);", ""),
    M("dtor_wobj_unnested", RCC,
      """        bFree(r->pReplayingGhostCarData);
        if (r->pReplayingGhostCarWorldObject && gWorldObjectDeleteFn)
            gWorldObjectDeleteFn(r->pReplayingGhostCarWorldObject);
    }""",
      """        bFree(r->pReplayingGhostCarData);
    }
    if (r->pReplayingGhostCarWorldObject && gWorldObjectDeleteFn)
        gWorldObjectDeleteFn(r->pReplayingGhostCarWorldObject);"""),
    M("dtor_wobj_kept", RCC,
      "            gWorldObjectDeleteFn(r->pReplayingGhostCarWorldObject);",
      "            (void)0;"),
    M("dtor_wobj_untested", RCC,
      "if (r->pReplayingGhostCarWorldObject && gWorldObjectDeleteFn)",
      "if (gWorldObjectDeleteFn)"),
    M("dtor_wobj_first", RCC,
      """        bFree(r->pReplayingGhostCarData);
        if (r->pReplayingGhostCarWorldObject && gWorldObjectDeleteFn)
            gWorldObjectDeleteFn(r->pReplayingGhostCarWorldObject);""",
      """        if (r->pReplayingGhostCarWorldObject && gWorldObjectDeleteFn)
            gWorldObjectDeleteFn(r->pReplayingGhostCarWorldObject);
        bFree(r->pReplayingGhostCarData);"""),
    M("dtor_wobj_data", RCC,
      "            gWorldObjectDeleteFn(r->pReplayingGhostCarWorldObject);",
      "            gWorldObjectDeleteFn("
      "(WorldObject *)r->pReplayingGhostCarData);"),
    M("dtor_capturing_kept", RCC,
      "        bFree(r->pCapturingGhostCarData);", ""),
    M("dtor_capturing_car", RCC,
      "        bFree(r->pCapturingGhostCarData);",
      "        bFree(r->pCapturingGhostCar);"),
    M("dtor_capturing_untested", RCC,
      """    if (r->pCapturingGhostCarData)
        bFree""",
      """    if (1)
        bFree"""),
    M("dtor_tatt_kept", RCC,
      "tatt_destroy(r->pTimeAroundTrackTable, 3);",
      "tatt_destroy(r->pTimeAroundTrackTable, 2);"),
    M("dtor_tatt_untested", RCC,
      """    if (r->pTimeAroundTrackTable)
        tatt_destroy""",
      """    if (r->pTimeAroundTrackTable || 1)
        tatt_destroy"""),
    M("dtor_current_kept", RCC,
      "    pCurrentRace = NULL;", ""),
    M("dtor_flag", RCC,
      """    if (flags & 1)
        bFree(r);""",
      """    if (flags & 2)
        bFree(r);"""),
    M("dtor_free_always", RCC,
      """    if (flags & 1)
        bFree(r);""",
      """    bFree(r);"""),

    # ---- AddBoundaryPosition
    M("add_wrap_at_100", RCC,
      "if (100.0f < dist)", "if (100.0f <= dist)"),
    M("add_wrap_99", RCC,
      "dist -= 100.0f;", "dist -= 99.0f;"),
    M("add_no_wrap", RCC,
      """    if (100.0f < dist)
        dist -= 100.0f;""", ""),
    M("add_pos_x_kept", RCC,
      "    pos->x = 0.0f;", ""),
    M("add_pos_y_kept", RCC,
      "    pos->y = 0.0f;", ""),
    M("add_marker_index", RCC,
      "track_get_position_marker_named(name, 0);",
      "track_get_position_marker_named(name, 1);"),
    M("add_marker_scale", RCC,
      "boundary_set(r, n, c.RatioAroundTrack * 100.0f);",
      "boundary_set(r, n, c.RatioAroundTrack * 10.0f);"),
    M("add_marker_slot", RCC,
      "boundary_set(r, n, c.RatioAroundTrack * 100.0f);",
      "boundary_set(r, n + 1, c.RatioAroundTrack * 100.0f);"),
    M("add_marker_swapped", RCC,
      """        pos->y = m->Position.y;
        pos->x = m->Position.x;""",
      """        pos->y = m->Position.x;
        pos->x = m->Position.y;"""),
    M("add_marker_pos_kept", RCC,
      """        pos->y = m->Position.y;
        pos->x = m->Position.x;""", ""),
    M("add_marker_count", RCC,
      """        r->NumBoundaries = (int16_t)(n + 1);
        return (int16_t)(n + 1) - 1;
    }
    if""",
      """        return (int16_t)(n + 1) - 1;
    }
    if"""),
    M("add_marker_return", RCC,
      """        return (int16_t)(n + 1) - 1;
    }
    if""",
      """        return n + 1;
    }
    if"""),
    M("add_dist_strict", RCC,
      "if (0.0f <= dist) {", "if (0.0f < dist) {"),
    M("add_dist_any", RCC,
      "if (0.0f <= dist) {", "if (1) {"),
    M("add_dist_slot", RCC,
      "boundary_set(r, n, dist);", "boundary_set(r, n + 1, dist);"),
    M("add_dist_count", RCC,
      """        r->NumBoundaries = (int16_t)(n + 1);
        return (int16_t)(n + 1) - 1;
    }
    return -1;""",
      """        return (int16_t)(n + 1) - 1;
    }
    return -1;"""),
    M("add_fail", RCC,
      """    return -1;
}""",
      """    return -2;
}"""),

    # ---- FigureOutBoundaries
    M("fig_count_kept", RCC,
      "    r->NumBoundaries = 0;", ""),
    M("fig_backward_test", RCC,
      "if (RaceParametersTrackDirection == TRACK_DIRECTION_FORWARD) {",
      "if (RaceParametersTrackDirection != TRACK_DIRECTION_BACKWARD) {"),
    M("fig_fwd_start_dist", RCC,
      """            (int8_t)race_add_boundary_position(r, FORWARD_START_LINE, &pos,
                                               5.0f);""",
      """            (int8_t)race_add_boundary_position(r, FORWARD_START_LINE, &pos,
                                               6.0f);"""),
    M("fig_fwd_start_pos", RCC,
      """        r->StartLinePosition = pos;
        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_1""",
      """        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_1"""),
    M("fig_fwd_split1", RCC,
      """+ 33.0f);
        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_2""",
      """+ 34.0f);
        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_2"""),
    M("fig_fwd_split2", RCC,
      """+ 66.0f);
        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_3""",
      """+ 67.0f);
        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_3"""),
    M("fig_fwd_split3", RCC,
      """SPLIT_TIME_BOUNDARY_3, &pos, -1.0f);
        if""",
      """SPLIT_TIME_BOUNDARY_3, &pos, 99.0f);
        if"""),
    M("fig_fwd_finish", RCC,
      """FORWARD_FINISH_LINE, &pos,
                boundary_at(r, r->StartLineBoundaryNumber) + 95.0f);""",
      """FORWARD_FINISH_LINE, &pos,
                boundary_at(r, r->StartLineBoundaryNumber) + 96.0f);"""),
    M("fig_fwd_finish_always", RCC,
      """        if (RaceParametersPoint2Point)
            finish = race_add_boundary_position(r, FORWARD_FINISH_LINE""",
      """        if (1)
            finish = race_add_boundary_position(r, FORWARD_FINISH_LINE"""),
    M("fig_fwd_split_order", RCC,
      """        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_1, &pos,
            boundary_at(r, r->StartLineBoundaryNumber) + 33.0f);
        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_2, &pos,
            boundary_at(r, r->StartLineBoundaryNumber) + 66.0f);""",
      """        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_2, &pos,
            boundary_at(r, r->StartLineBoundaryNumber) + 66.0f);
        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_1, &pos,
            boundary_at(r, r->StartLineBoundaryNumber) + 33.0f);"""),
    M("fig_bwd_start_name", RCC,
      "race_add_boundary_position(r, BACKWARD_START_LINE, &pos,",
      "race_add_boundary_position(r, FORWARD_START_LINE, &pos,"),
    M("fig_bwd_start_dist", RCC,
      """            (int8_t)race_add_boundary_position(r, BACKWARD_START_LINE, &pos,
                                               5.0f);""",
      """            (int8_t)race_add_boundary_position(r, BACKWARD_START_LINE, &pos,
                                               4.0f);"""),
    M("fig_bwd_start_pos", RCC,
      """        r->StartLinePosition = pos;
        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_3""",
      """        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_3"""),
    M("fig_bwd_split3_last", RCC,
      """        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_3, &pos, -1.0f);
        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_2, &pos,
            boundary_at(r, r->StartLineBoundaryNumber) + 33.0f);
        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_1, &pos,
            boundary_at(r, r->StartLineBoundaryNumber) + 66.0f);""",
      """        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_2, &pos,
            boundary_at(r, r->StartLineBoundaryNumber) + 33.0f);
        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_1, &pos,
            boundary_at(r, r->StartLineBoundaryNumber) + 66.0f);
        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_3, &pos, -1.0f);"""),
    M("fig_bwd_split2", RCC,
      """+ 33.0f);
        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_1""",
      """+ 32.0f);
        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_1"""),
    M("fig_bwd_split1", RCC,
      """+ 66.0f);
        if (RaceParametersPoint2Point)
            finish = race_add_boundary_position(r, BACKWARD_FINISH_LINE""",
      """+ 65.0f);
        if (RaceParametersPoint2Point)
            finish = race_add_boundary_position(r, BACKWARD_FINISH_LINE"""),
    M("fig_bwd_finish_name", RCC,
      "finish = race_add_boundary_position(r, BACKWARD_FINISH_LINE, &pos,",
      "finish = race_add_boundary_position(r, FORWARD_FINISH_LINE, &pos,"),
    M("fig_bwd_finish", RCC,
      """BACKWARD_FINISH_LINE, &pos,
                boundary_at(r, r->StartLineBoundaryNumber) + 95.0f);""",
      """BACKWARD_FINISH_LINE, &pos,
                boundary_at(r, r->StartLineBoundaryNumber) + 94.0f);"""),
    M("fig_finish_number", RCC,
      "r->FinishLineBoundaryNumber = (int8_t)finish;",
      "r->FinishLineBoundaryNumber = (int8_t)(finish + 1);"),
    M("fig_finish_pos", RCC,
      "        r->FinishLinePosition = pos;",
      "        r->FinishLinePosition = r->StartLinePosition;"),
    M("fig_p2p_one", RCC,
      """    if (RaceParametersPoint2Point) {
        r->FinishLineBoundaryNumber""",
      """    if (RaceParametersPoint2Point == 1) {
        r->FinishLineBoundaryNumber"""),
    M("fig_loop_finish_number", RCC,
      "r->FinishLineBoundaryNumber = r->StartLineBoundaryNumber;",
      "r->FinishLineBoundaryNumber = -1;"),
    M("fig_loop_finish_pos", RCC,
      "r->FinishLinePosition = r->StartLinePosition;",
      "r->FinishLinePosition = pos;"),

    # ---- GetLapNumberExact
    M("lap_from_start", RCC,
      "boundary_at(r, r->FinishLineBoundaryNumber));",
      "boundary_at(r, r->StartLineBoundaryNumber));"),
    M("lap_args_swapped", RCC,
      """        &TheTrackPathManager, pct,
        boundary_at(r, r->FinishLineBoundaryNumber));""",
      """        &TheTrackPathManager, boundary_at(r, r->FinishLineBoundaryNumber),
        pct);"""),
    M("lap_wrap_le", RCC,
      """    if (d < 0.0f)
        d += 100.0f;""",
      """    if (d <= 0.0f)
        d += 100.0f;"""),
    M("lap_wrap_99", RCC,
      "        d += 100.0f;", "        d += 99.0f;"),
    M("lap_no_wrap", RCC,
      """    if (d < 0.0f)
        d += 100.0f;""", ""),
    M("lap_divide", RCC,
      "return d * 0.01f;", "return d / 100.0f;"),
]

# Mutants that cannot change what either side computes, each with why.
EQUIVALENT = {
    # Zeroed for the table's own lookups, which ask for no time and so
    # never read it, and set again at the end.
    "tatt_total_zero",
    # Zeroed here and set to 0x7fffffff a few lines on.
    "ctor_best_first",
    # FigureOutBoundaries sets StartLinePosition from the start line's
    # AddBoundaryPosition, which zeroes its pos first.
    "ctor_start_line_x",
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
        edits = before if isinstance(before, list) else [(before, after)]
        new, bad = text, None
        for b, a in edits:
            probe = b.replace(NL, "\r\n") if crlf else b
            repl = a.replace(NL, "\r\n") if crlf else a
            if new.count(probe) != 1:
                bad = "NOT FOUND" if not new.count(probe) else "NOT UNIQUE"
                break
            new = new.replace(probe, repl, 1)
        if bad:
            missing.append(name)
            print("  %-44s PATTERN %s" % (name, bad))
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

    layout = arm_layout_check()
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
    sys.exit(1 if (n or rc or layout) else 0)


if __name__ == "__main__":
    main()
