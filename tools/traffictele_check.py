"""Cross-check 3DS Files/source/traffictele.c and airouteplan.c against the
retail image's own code.

TrafficTeleporter places the traffic cars and moves the ones out of sight:
retail's TrafficTeleporter.obj, 0x002226f8 to 0x002232c0. TryToTeleportCar
asks GuessTargetDestinations (0x001cbb70) where to put a car, which is
airouteplan.c. The oracle is SLES_507.31 itself, run in tools/mipsemu.py:

- every TrafficTeleporter function but DoSnapshot, called directly: the
  constructor (0x002226f8), the destructor (0x00222760), DoTimestep
  (0x002227e0), PlaceNewCar (0x002228e0), TryToTeleportCar (0x00222a90),
  IsGoodPlace (0x00222c40), both CheckIsVisible (0x00222d88, 0x00222dc8),
  SetThinkTime (0x00222e10), ForwardsOrBackwards (0x00222e40),
  FillInTotals (0x00222e88), both TooCloseToAnotherCar (0x00222ee8,
  0x00222fc0), PickRoutePoint (0x002230d0), RandomPlayerCar (0x002231f0),
  PickRandomSkin (0x00223228) and SwitchSkin (0x00223278);
- GuessTargetDestinations (0x001cbb70), both through TryToTeleportCar and
  called directly over route networks with signposts;
- run as shipped under them: TrackPathManager::CompareDistances
  (0x00208598), bATan (0x0025a890), TrackRoutePoint::GetSignpost
  (0x001c14f8) and Signpost's GetNewRoute (0x001c0ff8) and
  GetNewRoutePoint (0x001c1020).

Stood in on both sides, each call printing a line, so both must ask the
same questions in the same order:
  World::Random(int) (0x0014e520) and Random(float) (0x0014e548), which
    answer from the script's queue, then from a shared generator;
  World::GetDATToClosestPlayer (0x0014e4a0: the DAT less the script's
    player DAT) and GetDistanceToClosestPlayer (0x0014e3e8: the script's
    distance);
  GetNearestRoutePoint (0x001cb7a0, answering the script's point);
  Car::IsPoofed (0x00133260), CarTypeInfo's skin count (0x001884b8) and
    skin number (0x001884d8, the index plus the script's base);
  Car's constructor (0x00130a48, which gives the car the test controller
    whose SetCurrentRoute slot, 40, prints), SetMovementMode (0x00131618),
    SetControlMode (0x00131410), ResetToRoutePoint (0x00132f20) and
    SwitchSkin (0x0011e588);
  TrackPathCoordinate's constructor (0x002086b8) and destructor
    (0x00208748), silent, and ResetPosition (0x00208838), which prints
    the position (the port's through trackpath.c's gTrackPathDistanceFn);
  bMalloc (0x002577c0) and __builtin_delete (0x00114e98): a block filled
    with 0xcd, named h0, h1, ... (the port's Car prints as the console's
    2208).

With no race IsGoodPlace's start line is read through address 0 on the
console; the port leaves it out. Address 0 of the model reads 0, a start
line at 0, so the no-race cases keep their points 2000 and more from 0,
where the two agree.

    python tools/traffictele_check.py
    python tools/traffictele_check.py --mutate [--only a,b] [--jobs N]
    python tools/traffictele_check.py --dump PREFIX
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
from collections import deque
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import mutpar
import physicscar_check as pcc
import retail_model
from mipsemu import M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/traffictele_test.c"
TTC = "3DS Files/source/traffictele.c"
APC = "3DS Files/source/airouteplan.c"
TTH = "3DS Files/source/traffictele.h"
APH = "3DS Files/source/airouteplan.h"
SOURCES = [HARNESS, TTC, APC,
           "3DS Files/source/race.c",
           "3DS Files/source/trackroute.c",
           "3DS Files/source/trackpath.c",
           "3DS Files/source/quickspline.c",
           "3DS Files/source/bmem.c",
           "3DS Files/source/bmatrix.c",
           "3DS Files/source/bvector.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c",
           "3DS Files/source/bchunk.c",
           "3DS Files/source/vtable.c"]

HARNESS_TIMEOUT = 300

# ================================================================ the image

GP = retail_model.RETAIL_GP

CTOR = 0x002226f8
DTOR = 0x00222760
STEP = 0x002227e0
PLACE = 0x002228e0
TRY = 0x00222a90
GOOD = 0x00222c40
VISAT = 0x00222d88
VIS = 0x00222dc8
THINKT = 0x00222e10
FOB = 0x00222e40
FILL = 0x00222e88
CLOSEAT = 0x00222ee8
CLOSE = 0x00222fc0
PICK = 0x002230d0
RPC = 0x002231f0
SKIN = 0x00223228
SWITCH = 0x00223278
GTD = 0x001cbb70

RAND_I = 0x0014e520
RAND_F = 0x0014e548
DAT_CLOSE = 0x0014e4a0
DIST_CLOSE = 0x0014e3e8
NEAREST = 0x001cb7a0
POOFED = 0x00133260
NSKINS = 0x001884b8
SKINNUM = 0x001884d8
CAR_CTOR = 0x00130a48
SET_MOVE = 0x00131618
SET_CTRL = 0x00131410
RESET_TO = 0x00132f20
CAR_SWITCH = 0x0011e588
BMALLOC = 0x002577c0
BDELETE = 0x00114e98
BFREE = 0x00257850
TPC_CTOR = 0x002086b8
TPC_DTOR = 0x00208748
TPC_RESET = 0x00208838

RACE_PARAMS = 0x0031a898            # TrafficDensity 16, TrafficOncoming 20
DENSITY = RACE_PARAMS + 16
ONCOMING = RACE_PARAMS + 20
TRACK_PATH = 0x0031bc38             # TheTrackPathManager; TrackLength at 0
ROUTE_MANAGER = 0x00314438          # TheTrackRouteManager; pTrackRoutes at 16

WORLD_GP = -22120
RACE_GP = -22272
NPLAYERS_GP = -20920
PLAYERS_GP = -20928                 # PlayerPlayersByIndex[2]
TIMER_GP = -19576
CTI_GP = -20616                     # the CarTypeInfo array
SIGNPOSTS_GP = -18376
MIN_DENSITY_GP = -27148
SPEED_GP = -27144

# The world: retail's offsets.
T = 0x01E00000                      # the TrafficTeleporter, 88 bytes
T_SIZE = 88
WORLD = 0x01E00200                  # CarList 0, TotalNumCars 28,
                                    # TrafficCarPos 40, CarTable 44
RACE = 0x01E00800                   # RaceStage 0, StartTime 12,
                                    # StartLineBoundaryNumber 1618,
                                    # BoundaryDistances 1620
INFO = 0x01E01000                   # DriverInfo: CurrentRideInfo 12
PLAYERS = 0x01E01100                # p0, p1 0x40 apart; MyCar 4
CTL = 0x01E01200                    # the test controller, vptr at 8
FCVT = 0x01E01400                   # its table
FCVT_SETROUTE = FCVT + 0x100
SCR = 0x01E01800
OUT = 0x01E01A00                    # GuessTargetDestinations' out[32]
NOUT = 32
RIDES = 0x01E01C00                  # each car's RideInfo, 0x10 apart
DRVS = 0x01E01E00                   # each car's DriverInfo, 0x20 apart
CTS = 0x01E02000                    # ct0..ct3, 1376 bytes each
CT_SIZE = 1376
NCT = 4
CARS = 0x01E04000                   # c0..c7, 0x1000 apart
NCARS = 8
SIGNS = 0x01E0C000                  # 256 Signposts, 12 bytes each
NSIGNS = 256
ROUTES = 0x01E20000                 # r0..r5, 0x20000 apart
ROUTE_SPAN = 0x20000
NROUTES = 6
SLACK = 16

ROUTE_SIZE = 115752
POINT_SIZE = 112
POINT_TABLE = 1064
MAX_POINTS = 1024

# Car's fields.
CAR_NEXT, CAR_PREV, CAR_CT, CAR_RIDE, CAR_DRIVER, CAR_CTL = 0, 4, 12, 16, 20, 40
CAR_X, CAR_Y, CAR_RENDER, CAR_DAT = 96, 100, 1192, 2036

(OP_TAG, OP_JUNK, OP_NEW, OP_DEL, OP_STEP, OP_PLACE, OP_TRY, OP_GOOD,
 OP_VIS, OP_VISAT, OP_THINKT, OP_FOB, OP_FILL, OP_CLOSEAT, OP_CLOSE,
 OP_PICK, OP_RPC, OP_SKIN, OP_SWITCH, OP_GTD, OP_DUMP, OP_STATIC,
 OP_TPOKE, OP_SET, OP_RI, OP_RF, OP_SEED, OP_RCLEAR, OP_GLOBAL, OP_SLOT,
 OP_ROUTE, OP_RPOINT, OP_SIGN, OP_CAR, OP_LCLEAR, OP_LADD, OP_WORLD,
 OP_TABLE, OP_PLAYER, OP_INFO) = range(40)

ARGS = {OP_TAG: 1, OP_JUNK: 1, OP_NEW: 0, OP_DEL: 1, OP_STEP: 1,
        OP_PLACE: 0, OP_TRY: 1, OP_GOOD: 4, OP_VIS: 1, OP_VISAT: 2,
        OP_THINKT: 0, OP_FOB: 0, OP_FILL: 1, OP_CLOSEAT: 4, OP_CLOSE: 3,
        OP_PICK: 1, OP_RPC: 0, OP_SKIN: 1, OP_SWITCH: 1, OP_GTD: 5,
        OP_DUMP: 0, OP_STATIC: 0, OP_TPOKE: 2, OP_SET: 2, OP_RI: 1,
        OP_RF: 1, OP_SEED: 1, OP_RCLEAR: 0, OP_GLOBAL: 2, OP_SLOT: 2,
        OP_ROUTE: 3, OP_RPOINT: 4, OP_SIGN: 4, OP_CAR: 3, OP_LCLEAR: 0,
        OP_LADD: 1, OP_WORLD: 2, OP_TABLE: 2, OP_PLAYER: 2, OP_INFO: 2}

# OP_SET's keys: what the stand-ins answer.
(K_PDAT, K_DIST, K_NEAR_RET, K_NEAR_ROUTE, K_NEAR_POINT, K_NSKINS,
 K_SKINBASE, K_CTLDELTA, K_POOF_MASK) = range(9)
K_COUNT = 9
FLOAT_KEYS = (K_PDAT, K_DIST)

# OP_GLOBAL's.
(G_DENSITY, G_ONCOMING, G_TRACKLEN, G_TIMER, G_NPLAYERS, G_RACE, G_STAGE,
 G_START, G_BOUNDARY, G_BDIST) = range(10)
NBDIST = 5
FLOAT_GLOBALS = (G_DENSITY, G_ONCOMING, G_TRACKLEN) + tuple(
    G_BDIST + i for i in range(NBDIST))

# OP_RPOINT's fields.
PF_X, PF_Y, PF_Z, PF_DX, PF_DY, PF_LEN, PF_DAT, PF_BITS = range(8)
FLOAT_PFS = (PF_X, PF_Y, PF_Z, PF_DX, PF_DY, PF_LEN, PF_DAT)
PF_OFF = (0, 4, 8, 12, 16, 20, 40, 44)

# OP_CAR's fields.
C_DAT, C_X, C_Y, C_RENDER, C_DTYPE, C_CT, C_SKIN = range(7)
FLOAT_CS = (C_DAT, C_X, C_Y)

NO_CAR = -1
TRAFFIC = 3                         # DRIVER_TYPE_TRAFFIC_CAR
POSTED = 0x8000
NO_SIGN = 0xff

TICK = 0.000250000012
LCG_A, LCG_C = 1103515245, 12345
CANON_NAN = 0x7fc00000


def fb(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def bf(b):
    return struct.unpack("<f", struct.pack("<I", b & M32))[0]


def f32(x):
    return bf(fb(x))


def fx(b):
    return "%08x" % (b & M32)


def s16(v):
    v &= 0xffff
    return v - 0x10000 if v & 0x8000 else v


def s8(v):
    v &= 0xff
    return v - 0x100 if v & 0x80 else v


class Fb(object):
    """A float argument given as its bits."""
    def __init__(self, bits):
        self.bits = bits & M32


def nextup(x, n=1):
    """x moved n ulps towards +inf (a float32)."""
    b = fb(f32(x))
    for _ in range(abs(n)):
        if n > 0:
            if b & 0x80000000:
                b = 0 if b == 0x80000000 else b - 1
            else:
                b += 1
        else:
            if b & 0x80000000:
                b += 1
            elif b == 0:
                b = 0x80000001
            else:
                b -= 1
    return bf(b)


def secs_of(ticks):
    """Seconds as the image reckons a tick count."""
    return f32(f32(float(s32(ticks & M32))) * f32(TICK))


def first_ticks_reaching(limit):
    """The fewest ticks whose seconds are not under `limit`."""
    n = int(limit / TICK) - 4
    while secs_of(n) < limit:
        n += 1
    return n


START_TICKS = first_ticks_reaching(20.0)        # the start line let go


def think_time(d):
    return f32(f32(f32(f32(1.0) - f32(d)) * 15.0) + 1.0)


class Script(object):
    def __init__(self):
        self.ops = []
        self.tags = []

    def op(self, code, *args):
        assert len(args) == ARGS[code], (code, args)
        out = []
        for a in args:
            if isinstance(a, Fb):
                out.append(a.bits)
            elif isinstance(a, float):
                out.append(fb(a))
            else:
                out.append(int(a))
        self.ops.append((code,) + tuple(out))

    def tag(self, s):
        """A scenario's name, with the random queues emptied: what one
        left over is never another's."""
        self.tags.append(s)
        self.op(OP_TAG, len(self.tags) - 1)
        self.op(OP_RCLEAR)

    def rand(self, f=(), i=()):
        """The answers for the next call alone: the queues emptied, then
        the floats and the ints, the generator after them."""
        self.op(OP_RCLEAR)
        self.rf(*f)
        self.ri(*i)

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

    def set(self, key, v):
        if key in FLOAT_KEYS and not isinstance(v, Fb):
            v = float(v)
        self.op(OP_SET, key, v)

    def glob(self, g, v):
        if g in FLOAT_GLOBALS and not isinstance(v, Fb):
            v = float(v)
        self.op(OP_GLOBAL, g, v)

    def car(self, i, f, v):
        if f in FLOAT_CS and not isinstance(v, Fb):
            v = float(v)
        self.op(OP_CAR, i, f, v)

    def ri(self, *vals):
        for v in vals:
            self.op(OP_RI, v)

    def rf(self, *vals):
        for v in vals:
            self.op(OP_RF, v if isinstance(v, Fb) else float(v))

    def tpoke(self, idx, v):
        self.op(OP_TPOKE, idx, v)

    def time(self, v):
        self.tpoke(0, v if isinstance(v, Fb) else Fb(fb(f32(v))))


# ============================================================== the script

TRACK_LEN = 10000.0
SLOTS = {50: 0, 51: 1, 53: 2, 60: 3, 62: 4, 69: 5}
ROUTE_POINTS = 40


class Routes(object):
    """The routes' points as the script has left them: each op only
    writes what changes."""

    def __init__(self, sc):
        self.sc = sc
        self.pts = {}
        self.n = {}

    def route(self, k, n, number):
        if self.n.get(k) != (n, number):
            self.n[k] = (n, number)
            self.sc.op(OP_ROUTE, k, n, number)

    def field(self, k, i, f, v):
        if f in FLOAT_PFS:
            v = fb(f32(v)) if not isinstance(v, Fb) else v.bits
        v &= M32
        if self.pts.get((k, i, f)) != v:
            self.pts[(k, i, f)] = v
            self.sc.op(OP_RPOINT, k, i, f, Fb(v) if f in FLOAT_PFS else s32(v))

    def point(self, k, i, x, y, z, dx, dy, length, dat, bits):
        for f, v in ((PF_X, x), (PF_Y, y), (PF_Z, z), (PF_DX, dx),
                     (PF_DY, dy), (PF_LEN, length), (PF_DAT, dat),
                     (PF_BITS, bits)):
            self.field(k, i, f, v)

    def line(self, k, n, ox, oy, theta, step=25.0, dat0=0.0, ddat=None,
             bits=POSTED | NO_SIGN, z=0.0, length=None):
        """n points from (ox, oy) along theta, `step` apart, DATs from
        dat0 on by ddat (step by default), wrapped at the track's end."""
        c, s = f32(math.cos(theta)), f32(math.sin(theta))
        ddat = step if ddat is None else ddat
        length = step if length is None else length
        for i in range(n):
            d = (dat0 + i * ddat) % TRACK_LEN
            self.point(k, i, ox + i * step * c, oy + i * step * s,
                       z + 0.5 * i, c, s, length, d, bits)

    def bits(self, k, i, bits):
        self.field(k, i, PF_BITS, bits)

    def sign(self, k, i, sign, posted=True):
        self.bits(k, i, (POSTED if posted else 0) | (sign & 0xff))


def route_geom(k):
    """Route k's line: near the origin, each its own way."""
    return dict(ox=5.0 * k, oy=10.0 * k, theta=0.3 * k + 0.1)


def standard_routes(rt, n=ROUTE_POINTS):
    for k in range(NROUTES):
        rt.route(k, n, [50, 51, 53, 60, 62, 69][k])
        rt.line(k, n, dat0=300.0 + 1500.0 * k, **route_geom(k))


def standard_world(sc):
    """Eight cars: c0 and c1 the players' (racers), c2..c7 traffic, all
    drawn, far from each other round the track."""
    sc.op(OP_LCLEAR)
    for i in range(NCARS):
        sc.car(i, C_DAT, 1000.0 * i + 50.0)
        sc.car(i, C_X, 300.0 * i)
        sc.car(i, C_Y, -200.0 * i)
        sc.car(i, C_RENDER, 1)
        sc.car(i, C_DTYPE, 0 if i < 2 else TRAFFIC)
        sc.car(i, C_CT, i % NCT)
        sc.car(i, C_SKIN, i)
        sc.op(OP_LADD, i)
    sc.op(OP_WORLD, NCARS, 2)
    for i in range(14):
        sc.op(OP_TABLE, i, i if i < NCARS else NO_CAR)
    sc.op(OP_PLAYER, 0, 0)
    sc.op(OP_PLAYER, 1, 1)
    sc.glob(G_NPLAYERS, 1)
    sc.set(K_POOF_MASK, 0)


def standard_race(sc):
    sc.glob(G_RACE, 1)
    sc.glob(G_STAGE, 4)
    sc.glob(G_START, 0)
    sc.glob(G_TIMER, 200000)
    sc.glob(G_BOUNDARY, 1)
    for i, v in enumerate((0.0, 10.0, 20.0, 50.0, 90.0)):
        sc.glob(G_BDIST + i, v)


def defaults(sc):
    sc.glob(G_DENSITY, 0.5)
    sc.glob(G_ONCOMING, 0.5)
    sc.glob(G_TRACKLEN, TRACK_LEN)
    sc.set(K_PDAT, 5000.0)
    sc.set(K_DIST, 1000.0)
    sc.set(K_NEAR_RET, 1)
    sc.set(K_NEAR_ROUTE, 0)
    sc.set(K_NEAR_POINT, 0)
    sc.set(K_NSKINS, 4)
    sc.set(K_SKINBASE, 10)
    sc.set(K_CTLDELTA, 0)
    sc.op(OP_RCLEAR)
    sc.op(OP_SEED, 0x1234)


def slots(sc, mapping):
    for idx in range(100):
        sc.op(OP_SLOT, idx, mapping.get(idx, -1))


def think_boundary():
    """A density whose think time is exactly 20, if there is one near
    -4/15, and the ulps either side."""
    d = f32(-4.0 / 15.0)
    for n in range(-64, 65):
        x = nextup(d, n)
        if think_time(x) == 20.0:
            return x
    return None


def script():
    sc = Script()
    rnd = random.Random(0x7e1e)
    rt = Routes(sc)

    sc.tag("static")
    sc.op(OP_STATIC)

    defaults(sc)
    slots(sc, SLOTS)
    for i in range(NSIGNS):
        sc.op(OP_SIGN, i, 0, 50, 0)
    standard_routes(rt)
    standard_world(sc)
    standard_race(sc)
    sc.op(OP_INFO, 2, 0x5a)

    # ---- FillInTotals ------------------------------------------------------
    sc.tag("fill")
    for k, n in enumerate((40, 7, 0, 13, 40, 3)):
        rt.route(k, n, [50, 51, 53, 60, 62, 69][k])
    for first in (50, 60, 45, 55, 64, -5, -10, 0, 41):
        sc.op(OP_FILL, first)
    rt.route(1, -3, 51)
    sc.op(OP_FILL, 50)
    rt.route(4, 0x7fffffff, 62)
    rt.route(5, 0x7fffffff, 69)
    sc.op(OP_FILL, 60)
    slots(sc, {50: 0, 59: 1, 60: 3, 61: 4})
    sc.op(OP_FILL, 50)
    sc.op(OP_FILL, 60)
    slots(sc, SLOTS)
    standard_routes(rt)

    # ---- the constructor, SetThinkTime, the destructor ----------------------
    sc.tag("new")
    db = think_boundary()
    dens = [0.5, 1.0, 0.0, 0.33, 0.4, -1.0, -0.4, -0.2, 2.0, 1e30, -1e30,
            Fb(0x7fc00000), Fb(0xffc00000), Fb(0x7f800000), Fb(0xff800000)]
    if db is not None:
        dens += [nextup(db, -1), db, nextup(db, 1)]
    for junk, d in zip([0xa5, 0x00, 0xff, 0x3c] * 8, dens):
        sc.op(OP_JUNK, junk)
        sc.glob(G_DENSITY, d)
        sc.op(OP_NEW)
        sc.op(OP_DUMP)
    sc.glob(G_DENSITY, 0.5)
    for d in (0.25, 0.75, -3.0, Fb(0x7fc00000)):
        sc.glob(G_DENSITY, d)
        sc.op(OP_THINKT)
        sc.op(OP_DUMP)
    sc.glob(G_DENSITY, 0.5)
    for flags in (0, 2, 1, 3, -1):
        sc.op(OP_DEL, flags)
    sc.op(OP_JUNK, 0xa5)
    sc.op(OP_NEW)
    sc.op(OP_DUMP)

    # ---- ForwardsOrBackwards -----------------------------------------------
    sc.tag("fob")
    for onc, answers in ((0.5, (0.25, 0.5, nextup(0.5, -1), 0.75, 0.0)),
                         (0.0, (0.0, -0.0, 0.5)),
                         (1.0, (0.999999, 1.0, 0.0)),
                         (Fb(0x7fc00000), (0.5,)),
                         (-1.0, (-2.0, -1.0))):
        sc.glob(G_ONCOMING, onc)
        for a in answers:
            sc.rf(a)
            sc.op(OP_FOB)
    sc.glob(G_ONCOMING, 0.5)
    for _ in range(4):
        sc.op(OP_FOB)                   # from the generator

    # ---- PickRoutePoint ----------------------------------------------------
    sc.tag("pick")
    for k, n in enumerate((40, 7, 0, 13, 40, 3)):
        rt.route(k, n, [50, 51, 53, 60, 62, 69][k])
    sc.op(OP_NEW)
    sc.op(OP_DUMP)
    for v in (0, 1, 39, 40, 41, 46):
        sc.ri(v)
        sc.op(OP_PICK, 1)
    for v in (0, 12, 13, 14, 52, 53, 55):
        sc.ri(v)
        sc.op(OP_PICK, 0)
    sc.ri(3)
    sc.op(OP_PICK, 7)                   # any non-zero is forwards
    sc.ri(3)
    sc.op(OP_PICK, -1)
    # Unposted points are drawn again.
    rt.bits(0, 5, NO_SIGN)
    rt.bits(1, 2, NO_SIGN)
    sc.ri(5, 5, 42, 6)
    sc.op(OP_PICK, 1)
    sc.ri(5, 41)
    sc.op(OP_PICK, 1)
    # All of them unposted: 101 draws and the last one taken.
    for k, n in ((0, 40), (1, 7)):
        for i in range(n):
            rt.bits(k, i, NO_SIGN)
    sc.op(OP_PICK, 1)
    sc.ri(*[rnd.randrange(47) for _ in range(100)])
    sc.ri(17)
    sc.op(OP_PICK, 1)
    # Posted on a later bit pattern: only bit 15 counts.
    for k, n in ((0, 40), (1, 7)):
        for i in range(n):
            rt.bits(k, i, 0xffff7fff if i % 2 else 0x00008000 | NO_SIGN)
    for v in (2, 3, 4, 3, 41, 42):
        sc.ri(v)
    sc.op(OP_PICK, 1)
    sc.op(OP_PICK, 1)
    sc.op(OP_PICK, 1)
    standard_routes(rt)

    # ---- RandomPlayerCar, PickRandomSkin, SwitchSkin -------------------------
    sc.tag("players")
    sc.ri(0)
    sc.op(OP_RPC)
    sc.glob(G_NPLAYERS, 2)
    sc.ri(1, 0)
    sc.op(OP_RPC)
    sc.op(OP_RPC)
    sc.op(OP_PLAYER, 1, 5)
    sc.ri(1)
    sc.op(OP_RPC)
    sc.op(OP_PLAYER, 1, 1)
    sc.glob(G_NPLAYERS, 1)

    sc.tag("skins")
    for ns, base, ct, ans in ((0, 10, 0, None), (4, 10, 1, 2), (1, 0, 2, 0),
                              (3, -5, 3, 1), (4, 10, -1, 3), (-1, 7, 0, None),
                              (300, 200, 1, 299)):
        sc.set(K_NSKINS, ns)
        sc.set(K_SKINBASE, base)
        if ans is not None:
            sc.ri(ans)
        sc.op(OP_SKIN, ct)
    sc.set(K_NSKINS, 4)
    for skin, base, ans in ((12, 10, 2), (12, 10, 3), (-1, 253, 2),
                            (12, 266, 2), (0, 0, 0), (5, 3, 2)):
        sc.car(3, C_SKIN, skin)
        sc.set(K_SKINBASE, base)
        sc.ri(ans)
        sc.op(OP_SWITCH, 3)
    sc.set(K_NSKINS, 0)
    sc.car(4, C_SKIN, 0)
    sc.op(OP_SWITCH, 4)
    sc.car(4, C_SKIN, 3)
    sc.op(OP_SWITCH, 4)
    sc.car(4, C_CT, -1)
    sc.op(OP_SWITCH, 4)
    sc.car(4, C_CT, 0)
    sc.set(K_NSKINS, 4)
    sc.set(K_SKINBASE, 10)

    # ---- CheckIsVisible ----------------------------------------------------
    sc.tag("visible")
    pd = 5000.0
    for dat in (pd, pd + 249.99, nextup(pd + 250.0, -1), pd + 250.0,
                pd - 250.0, nextup(pd - 250.0, 1), pd - 1000.0, 0.0,
                Fb(0x7fc00000), Fb(0x7f800000), Fb(0xff800000)):
        sc.op(OP_VIS, dat if isinstance(dat, Fb) else float(dat))
    for d in (0.0, 249.99, nextup(250.0, -1), 250.0, 1000.0, -5.0,
              Fb(0x7fc00000), Fb(0xff800000)):
        sc.set(K_DIST, d)
        sc.op(OP_VISAT, 12.5, -3.25)
    sc.set(K_DIST, 1000.0)

    # ---- TooCloseToAnotherCar ----------------------------------------------
    sc.tag("close")
    base = 3000.0
    for i in range(NCARS):
        sc.car(i, C_DAT, 6000.0 + 300.0 * i)
    # A traffic car: within 100 either way.
    for d in (0.0, 50.0, -50.0, 99.99, -99.99, nextup(100.0, -1), 100.0,
              -100.0, 150.0, -150.0):
        sc.car(4, C_DAT, base)
        sc.op(OP_CLOSE, f32(base + d), NO_CAR, 0)
    # A racer: only up to 100 behind it.
    for d in (0.0, 50.0, -50.0, 99.99, -99.99, 100.0, nextup(0.0, 1),
              -0.0):
        sc.car(1, C_DAT, base)
        sc.op(OP_CLOSE, f32(base + d) if d != 0.0 else Fb(fb(base)),
              NO_CAR, 0)
    sc.car(1, C_DAT, 6300.0)
    # Round the end of the track.
    sc.car(4, C_DAT, 9990.0)
    sc.op(OP_CLOSE, 40.0, NO_CAR, 0)
    sc.car(1, C_DAT, 9990.0)
    sc.car(4, C_DAT, 7200.0)
    sc.op(OP_CLOSE, 40.0, NO_CAR, 0)
    sc.op(OP_CLOSE, 9940.0, NO_CAR, 0)
    sc.car(1, C_DAT, 6300.0)
    # The ones passed over.
    sc.car(4, C_DAT, base)
    sc.op(OP_CLOSE, base + 10.0, 4, 0)
    sc.op(OP_CLOSE, base + 10.0, 3, 0)
    sc.set(K_POOF_MASK, 1 << 4)
    sc.op(OP_CLOSE, base + 10.0, NO_CAR, 0)
    sc.set(K_POOF_MASK, (1 << 3) | (1 << 5))
    sc.op(OP_CLOSE, base + 10.0, NO_CAR, 1)
    sc.set(K_POOF_MASK, 0)
    sc.car(4, C_RENDER, 0)
    sc.op(OP_CLOSE, base + 10.0, NO_CAR, 0)
    sc.op(OP_CLOSE, base + 10.0, NO_CAR, 1)
    sc.op(OP_CLOSE, base + 10.0, NO_CAR, 2)
    sc.car(4, C_RENDER, -1)
    sc.op(OP_CLOSE, base + 10.0, NO_CAR, 0)
    sc.car(4, C_RENDER, 1)
    sc.car(4, C_DTYPE, 2)
    sc.op(OP_CLOSE, base + 10.0, NO_CAR, 0)
    sc.op(OP_CLOSE, base - 10.0, NO_CAR, 0)
    sc.car(4, C_DTYPE, TRAFFIC)
    # Two near: the first in the list answers.
    sc.car(6, C_DAT, base + 30.0)
    sc.op(OP_CLOSE, base + 10.0, NO_CAR, 0)
    sc.op(OP_CLOSE, base + 10.0, 4, 0)
    sc.op(OP_LCLEAR)
    sc.op(OP_CLOSE, base + 10.0, NO_CAR, 0)
    for i in (6, 4, 0):
        sc.op(OP_LADD, i)
    sc.op(OP_CLOSE, base + 10.0, NO_CAR, 0)

    # TooCloseToAnotherCar(bVector2 *): in the plane.
    sc.tag("closeat")
    standard_world(sc)
    for i in range(NCARS):
        sc.car(i, C_DAT, 6000.0 + 300.0 * i)
    sc.car(5, C_X, 100.0)
    sc.car(5, C_Y, 200.0)
    for dx, dy in ((0.0, 0.0), (60.0, 79.99), (60.0, 80.0), (-99.99, 0.0),
                   (0.0, -100.0), (0.0, nextup(100.0, -1)), (70.0, 70.0),
                   (71.0, 71.0)):
        sc.op(OP_CLOSEAT, f32(100.0 + dx), f32(200.0 + dy), NO_CAR, 0)
    sc.op(OP_CLOSEAT, 100.0, 200.0, 5, 0)
    sc.set(K_POOF_MASK, 1 << 5)
    sc.op(OP_CLOSEAT, 100.0, 200.0, NO_CAR, 0)
    sc.set(K_POOF_MASK, 0)
    sc.car(5, C_RENDER, 0)
    sc.op(OP_CLOSEAT, 100.0, 200.0, NO_CAR, 0)
    sc.op(OP_CLOSEAT, 100.0, 200.0, NO_CAR, 1)
    sc.car(5, C_RENDER, 1)
    sc.car(5, C_DTYPE, 0)
    sc.op(OP_CLOSEAT, 150.0, 200.0, NO_CAR, 0)
    sc.car(5, C_DTYPE, TRAFFIC)
    sc.op(OP_CLOSEAT, Fb(0x7fc00000), 200.0, NO_CAR, 0)
    standard_world(sc)

    # ---- IsGoodPlace -------------------------------------------------------
    sc.tag("good")
    for i in range(NCARS):
        sc.car(i, C_DAT, 6000.0 + 300.0 * i)
    sc.set(K_PDAT, 9000.0)
    # The race well under way: neither visible nor close.
    sc.op(OP_GOOD, 0, 5, NO_CAR, 0)      # DAT 425
    sc.set(K_PDAT, 500.0)
    sc.op(OP_GOOD, 0, 5, NO_CAR, 0)      # visible
    sc.set(K_PDAT, 9000.0)
    sc.car(3, C_DAT, 450.0)
    sc.op(OP_GOOD, 0, 5, NO_CAR, 0)      # c3 too close
    sc.op(OP_GOOD, 0, 5, 3, 0)
    sc.car(3, C_RENDER, 0)
    sc.op(OP_GOOD, 0, 5, NO_CAR, 0)
    sc.op(OP_GOOD, 0, 5, NO_CAR, 1)
    sc.car(3, C_RENDER, 1)
    sc.car(3, C_DAT, 6900.0)
    # The start line: StartLineBoundaryNumber 1, 10% round, 1000.
    start = f32(f32(f32(TRACK_LEN) * f32(0.01)) * 10.0)
    for ticks in (START_TICKS - 1, START_TICKS, 0, 4000, -100000,
                  0x7fffffff, -0x80000000):
        sc.glob(G_TIMER, ticks)
        sc.op(OP_GOOD, 1, 0, NO_CAR, 0)          # DAT 1800, near it
        sc.op(OP_GOOD, 2, 0, NO_CAR, 0)          # DAT 3300, not
    sc.glob(G_START, 1000)
    sc.glob(G_TIMER, 1000 + START_TICKS - 1)
    sc.op(OP_GOOD, 1, 0, NO_CAR, 0)
    sc.glob(G_TIMER, 1000 + START_TICKS)
    sc.op(OP_GOOD, 1, 0, NO_CAR, 0)
    sc.glob(G_TIMER, 999)
    sc.op(OP_GOOD, 1, 0, NO_CAR, 0)
    sc.glob(G_START, 0)
    sc.glob(G_TIMER, 0)
    # Either side of 2000 from it.
    for d in (1999.99, nextup(2000.0, -1), 2000.0, -1999.99, -2000.0,
              2500.0, 0.0):
        rt.field(2, 3, PF_DAT, f32(start + d) % TRACK_LEN)
        sc.op(OP_GOOD, 2, 3, NO_CAR, 0)
    # Visible and near the start: the start line answers first.
    sc.set(K_PDAT, f32(start))
    rt.field(2, 3, PF_DAT, start)
    sc.op(OP_GOOD, 2, 3, NO_CAR, 0)
    sc.set(K_PDAT, 9000.0)
    # The other boundaries, and one round the end of the track.
    for b, v in ((0, 0.0), (2, 20.0), (3, 50.0), (4, 99.5), (4, 0.25)):
        sc.glob(G_BOUNDARY, b)
        sc.glob(G_BDIST + b, v)
        for dat in (100.0, 1900.0, 2100.0, 4900.0, 5100.0, 9500.0):
            rt.field(2, 3, PF_DAT, dat)
            sc.op(OP_GOOD, 2, 3, NO_CAR, 0)
    sc.glob(G_BDIST + 4, 90.0)
    sc.glob(G_BOUNDARY, 1)
    sc.glob(G_TRACKLEN, 8000.0)
    rt.field(2, 3, PF_DAT, 2700.0)
    sc.op(OP_GOOD, 2, 3, NO_CAR, 0)
    rt.field(2, 3, PF_DAT, 2850.0)
    sc.op(OP_GOOD, 2, 3, NO_CAR, 0)
    sc.glob(G_TRACKLEN, TRACK_LEN)
    # No race: the console's start line is at 0, so keep 2000 off it.
    sc.glob(G_RACE, 0)
    for dat in (2100.0, 5000.0, 7900.0):
        rt.field(2, 3, PF_DAT, dat)
        sc.op(OP_GOOD, 2, 3, NO_CAR, 0)
    sc.car(3, C_DAT, 5050.0)
    rt.field(2, 3, PF_DAT, 5000.0)
    sc.op(OP_GOOD, 2, 3, NO_CAR, 0)
    sc.set(K_PDAT, 5100.0)
    sc.op(OP_GOOD, 2, 3, NO_CAR, 0)
    sc.set(K_PDAT, 9000.0)
    sc.car(3, C_DAT, 6900.0)
    standard_race(sc)
    sc.glob(G_TIMER, 200000)
    standard_routes(rt)

    # ---- GuessTargetDestinations -------------------------------------------
    gtd_script(sc, rt, rnd)

    # ---- PlaceNewCar -------------------------------------------------------
    place_script(sc, rt, rnd)

    # ---- TryToTeleportCar --------------------------------------------------
    try_script(sc, rt, rnd)

    # ---- DoTimestep --------------------------------------------------------
    step_script(sc, rt, rnd)

    sc.tag("static")
    sc.op(OP_STATIC)
    return sc


def gtd(sc, count, k, i, dist, fwd):
    sc.op(OP_GTD, count, k, i, float(dist) if not isinstance(dist, Fb)
          else dist, fwd)


def gtd_script(sc, rt, rnd):
    sc.tag("gtd plain")
    for k, n in enumerate((40, 20, 20, 20, 40, 10)):
        rt.route(k, n, [50, 51, 53, 60, 62, 69][k])
    gtd(sc, 1, -1, 0, 100.0, 1)
    gtd(sc, 1, 0, -1, 100.0, 1)
    gtd(sc, 1, -1, -1, 100.0, 0)
    # A point but no route: still nothing.
    gtd(sc, 1, -2, 3, 0.0, 1)
    gtd(sc, 1, -2, 3, 100.0, 0)
    for dist in (0.0, -1.0, 24.99, 25.0, nextup(25.0, 1), 75.0, 100.0,
                 975.0, 999.0, 1000.0, 5000.0):
        gtd(sc, 1, 0, 0, dist, 1)
    for dist in (0.0, -30.0, 24.99, 25.0, 100.0, 250.0, 260.0, 274.0,
                 275.0):
        gtd(sc, 1, 0, 10, dist, 0)
    gtd(sc, 1, 1, 3, 1000.0, 1)          # off the end
    gtd(sc, 1, 1, 3, 1000.0, 0)          # off the start
    gtd(sc, 1, 1, 19, 0.0, 1)
    gtd(sc, 1, 1, 19, 30.0, 1)
    gtd(sc, 1, 1, 0, 30.0, 0)
    gtd(sc, 3, 0, 0, 100.0, 1)
    gtd(sc, 2, 0, 0, Fb(0x7fc00000), 1)
    gtd(sc, 1, 0, 0, Fb(0x7f800000), 1)
    gtd(sc, 1, 0, 0, Fb(0xff800000), 1)
    gtd(sc, 1, 0, 0, 100.0, 5)           # any non-zero is forwards
    # An unposted point ends the walk; the first is never asked.
    rt.bits(0, 6, NO_SIGN)
    gtd(sc, 1, 0, 0, 500.0, 1)
    gtd(sc, 1, 0, 6, 10.0, 1)
    gtd(sc, 1, 0, 6, 50.0, 1)
    gtd(sc, 1, 0, 9, 200.0, 0)
    gtd(sc, 1, 0, 9, 60.0, 0)
    rt.bits(0, 6, POSTED | NO_SIGN)
    # Lengths that differ.
    for i in range(40):
        rt.field(0, i, PF_LEN, [10.0, 0.0, 37.5, 2.25][i % 4])
    for dist in (0.0, 9.0, 10.0, 10.5, 47.0, 47.5, 49.0, 200.0):
        gtd(sc, 1, 0, 0, dist, 1)
        gtd(sc, 1, 0, 20, dist, 0)
    standard_routes(rt)

    # Signs. Signpost i: (flags, new route slot, new point).
    sc.tag("gtd signs")
    for k, n in enumerate((40, 20, 20, 20, 40, 10)):
        rt.route(k, n, [50, 51, 53, 60, 62, 69][k])
    signs = {1: (0x03, 51, 5),           # stop
             2: (0x02, 53, 4),           # always take
             3: (0x00, 51, 2),           # faster: the branch first
             4: (0x01, 53, 7),           # slower: the branch last
             5: (0x0b, 51, 5),           # stop, walking back
             6: (0x0a, 53, 15),          # always take, walking back
             7: (0x08, 51, 12),          # faster, walking back
             8: (0x04, 62, 3),           # equivalent
             9: (0x05, 69, 1),           # don't take
             10: (0x06, 60, 0),
             11: (0x07, 60, 19),
             12: (0xf3, 51, 5),          # the high bits do not count
             13: (0xfb, 51, 5),
             14: (0x02, 51, 19),         # to a route's last point
             15: (0x00, 62, 0)}
    for i, (flags, route, point) in signs.items():
        sc.op(OP_SIGN, i, flags, route, point)
    for s in sorted(signs):
        rt.sign(0, 3, s)
        for dist, fwd, start in ((100.0, 1, 0), (60.0, 1, 0), (400.0, 1, 0),
                                 (800.0, 1, 0), (10.0, 0, 6), (90.0, 0, 6),
                                 (300.0, 0, 6), (0.0, 1, 3), (10.0, 0, 3)):
            gtd(sc, 3, 0, start, dist, fwd)
    rt.sign(0, 3, NO_SIGN)
    # A stop on a point of no length: it still counts, next time round.
    rt.field(0, 3, PF_LEN, 0.0)
    rt.sign(0, 3, 1)
    gtd(sc, 1, 0, 0, 100.0, 1)
    gtd(sc, 1, 0, 3, 0.0, 1)
    gtd(sc, 1, 0, 3, 10.0, 0)
    rt.sign(0, 3, 5)
    gtd(sc, 1, 0, 6, 100.0, 0)
    rt.field(0, 3, PF_LEN, 25.0)
    rt.sign(0, 3, NO_SIGN)
    # Branches on the branch routes too.
    rt.sign(1, 8, 4)
    rt.sign(2, 9, 3)
    rt.sign(2, 12, 1)
    rt.sign(0, 3, 3)
    rt.sign(0, 7, 4)
    rt.sign(0, 11, 8)
    for count in (1, 2, 3, 4, 6):
        for dist in (100.0, 150.0, 300.0, 600.0):
            gtd(sc, count, 0, 0, dist, 1)
    # count 0 never matches: every point found, out as far as it goes.
    gtd(sc, 0, 0, 0, 150.0, 1)
    rt.sign(1, 8, NO_SIGN)
    rt.sign(2, 9, NO_SIGN)
    rt.sign(2, 12, NO_SIGN)
    rt.sign(0, 7, NO_SIGN)
    rt.sign(0, 11, NO_SIGN)
    rt.sign(0, 3, NO_SIGN)
    # A sign onto an unposted point: walked once, as the branch is popped.
    rt.bits(1, 2, NO_SIGN)
    rt.sign(0, 3, 3)
    gtd(sc, 2, 0, 0, 80.0, 1)
    gtd(sc, 2, 0, 0, 100.0, 1)
    rt.sign(0, 3, 2)
    gtd(sc, 2, 0, 0, 100.0, 1)
    rt.sign(0, 3, NO_SIGN)
    rt.bits(1, 2, POSTED | NO_SIGN)

    # The ring: a sign on every point, branches at both ends.
    sc.tag("gtd ring")
    for i in range(40):
        rt.sign(0, i, 3 if i % 3 == 0 else 4)
    for count in (1, 3, 8):
        for dist in (60.0, 2000.0):
            gtd(sc, count, 0, 0, dist, 1)
    # Paths that end at once: the 71st path ends the walk, with 0.
    for k in (1, 2):
        rt.bits(k, 2, NO_SIGN)
        rt.bits(k, 7, NO_SIGN)
    for i in range(40):
        rt.sign(0, i, 4)
        rt.sign(4, i, 4)
    sc.op(OP_SIGN, 20, 0x02, 62, 0)
    rt.sign(0, 39, 20)
    for count, dist in ((1, 5000.0), (1, 30000.0), (2, 1990.0),
                        (1, 1990.0), (3, 2300.0)):
        gtd(sc, count, 0, 0, dist, 1)
    for i in range(40):
        rt.sign(0, i, 3)
        rt.sign(4, i, NO_SIGN)
    gtd(sc, 1, 0, 0, 30000.0, 1)
    gtd(sc, 4, 0, 0, 30000.0, 1)
    gtd(sc, 1, 0, 39, 30000.0, 0)
    standard_routes(rt)
    for k, n in enumerate((40, 20, 20, 20, 40, 10)):
        rt.route(k, n, [50, 51, 53, 60, 62, 69][k])
    for i in range(40):
        rt.sign(0, i, rnd.choice((NO_SIGN, NO_SIGN, 3, 4, 8, 9, 10, 2, 1)))
        rt.sign(4, i, rnd.choice((NO_SIGN, NO_SIGN, NO_SIGN, 3, 4, 11)))
    for _ in range(12):
        gtd(sc, rnd.choice((1, 2, 3, 5)), rnd.choice((0, 4)),
            rnd.randrange(40), f32(rnd.uniform(0.0, 1500.0)),
            rnd.choice((0, 1)))

    # A loop of zero-length points: the step guard.
    sc.tag("gtd steps")
    standard_routes(rt)
    rt.route(5, 10, 69)
    for i in range(10):
        rt.field(5, i, PF_LEN, 0.0)
    sc.op(OP_SIGN, 21, 0x02, 69, 0)
    rt.sign(5, 9, 21)
    gtd(sc, 1, 5, 0, 10.0, 1)
    sc.op(OP_SIGN, 21, 0x02, 69, 9)
    rt.sign(5, 9, NO_SIGN)
    rt.sign(5, 0, 21)
    rt.sign(5, 9, 21)
    sc.op(OP_SIGN, 22, 0x0a, 69, 9)
    rt.sign(5, 0, 22)
    gtd(sc, 1, 5, 5, 10.0, 0)
    # One found, then the loop: still 0.
    rt.sign(5, 0, NO_SIGN)
    sc.op(OP_SIGN, 21, 0x02, 69, 0)
    sc.op(OP_SIGN, 23, 0x01, 69, 0)
    rt.sign(0, 0, 23)
    gtd(sc, 2, 0, 0, 30.0, 1)
    gtd(sc, 1, 0, 0, 30.0, 1)
    rt.sign(0, 0, NO_SIGN)
    # The guard's edge: found on the 0x11800th step, and a step later.
    # r5p1 always takes r5p0, a metre back along its direction: each pair
    # of steps 1 less to go, found on r5p1.
    rt.route(5, 2, 69)
    rt.point(5, 0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 5000.0, POSTED | NO_SIGN)
    rt.point(5, 1, 0.0, 0.0, 0.0, 1.0, 0.0, 1.0, 5001.0, POSTED | NO_SIGN)
    sc.op(OP_SIGN, 72, 0x02, 69, 0)
    rt.sign(5, 1, 72)
    for start, dist in ((0, 35838.0), (0, 35839.0), (1, 35839.0),
                        (1, 35840.0)):
        gtd(sc, 1, 5, start, dist, 1)

    # A full ring: a slower sign on each point of r0, to its own point of
    # r1, each found. The way on fills it at the 19th; branches after
    # that are dropped.
    sc.tag("gtd full")
    rt.route(0, 30, 50)
    rt.line(0, 30, 0.0, 0.0, 0.0, step=10.0, dat0=100.0)
    rt.route(1, 30, 51)
    for i in range(30):
        rt.point(1, i, 0.0, 0.0, 0.0, 1.0, 0.0, 1.0e6, 2000.0 + i,
                 POSTED | NO_SIGN)
        sc.op(OP_SIGN, 40 + i, 0x01, 51, i)
        rt.sign(0, i, 40 + i)
    for count, dist in ((1, 255.0), (25, 255.0), (31, 400.0)):
        gtd(sc, count, 0, 0, dist, 1)
    # The 71st path: two a sign, the branch to a dead end (r3p0) and the
    # way on, but r2p0's and r2p35's branches to r4p0, found.
    rt.route(2, 40, 53)
    rt.line(2, 40, 0.0, 0.0, 0.0, step=10.0, dat0=100.0)
    rt.route(3, 1, 60)
    rt.point(3, 0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 3000.0, POSTED | NO_SIGN)
    rt.route(4, 1, 62)
    rt.point(4, 0, 0.0, 0.0, 0.0, 1.0, 0.0, 1.0e6, 4000.0,
             POSTED | NO_SIGN)
    sc.op(OP_SIGN, 70, 0x00, 60, 0)
    sc.op(OP_SIGN, 71, 0x00, 62, 0)
    for i in range(40):
        rt.sign(2, i, 71 if i in (0, 35) else 70)
    for count, dist in ((2, 345.0), (2, 355.0), (2, 365.0), (3, 355.0),
                        (3, 365.0)):
        gtd(sc, count, 2, 0, dist, 1)
    standard_routes(rt)


def place_script(sc, rt, rnd):
    sc.tag("place")
    standard_routes(rt)
    standard_world(sc)
    standard_race(sc)
    for i in range(NCARS):
        sc.car(i, C_DAT, 6000.0 + 300.0 * i)
    sc.set(K_PDAT, 9000.0)
    sc.op(OP_JUNK, 0xa5)
    sc.op(OP_NEW)
    sc.op(OP_DUMP)
    # The first draw good, forwards, then backwards; the third is too close
    # to c4 and the generator draws on.
    for fwd, pick in ((0.25, 7), (0.75, 21), (0.75, 79), (0.25, 52)):
        sc.rand(f=(fwd,), i=(pick, 2))
        sc.op(OP_INFO, 2, 0x5a)
        sc.op(OP_PLACE)
    # Each type's car, its own skins.
    for ty in range(NCT):
        sc.rand(f=(0.25,), i=(30 + ty, 1))
        sc.op(OP_INFO, ty, -1)
        sc.op(OP_PLACE)
    sc.set(K_NSKINS, 0)
    sc.rand(f=(0.25,), i=(9,))
    sc.op(OP_INFO, 1, 0x33)
    sc.op(OP_PLACE)
    sc.set(K_NSKINS, 4)
    # The controller's this-adjustment.
    sc.set(K_CTLDELTA, 16)
    sc.rand(f=(0.25,), i=(11, 0))
    sc.op(OP_PLACE)
    sc.set(K_CTLDELTA, -8)
    sc.rand(f=(0.25,), i=(12, 3))
    sc.op(OP_PLACE)
    sc.set(K_CTLDELTA, 0)
    # Unposted (r0p8), then visible (r0p9, DAT 525), then too close (r0p28
    # on c5), then good (r0p33).
    rt.bits(0, 8, NO_SIGN)
    sc.set(K_PDAT, 525.0)
    sc.car(5, C_DAT, 1000.0)
    sc.rand(f=(0.25,), i=(8, 9, 28, 33, 0))
    sc.op(OP_PLACE)
    rt.bits(0, 8, POSTED | NO_SIGN)
    sc.car(5, C_DAT, 7500.0)
    sc.set(K_PDAT, 9000.0)
    # An undrawn car counts: r0p28 is too close to c4.
    sc.car(4, C_RENDER, 0)
    sc.car(4, C_DAT, 1000.0)
    sc.rand(f=(0.25,), i=(28, 33, 0))
    sc.op(OP_PLACE)
    sc.car(4, C_RENDER, 1)
    sc.car(4, C_DAT, 7200.0)
    # The start line (1000) keeps the cars off while the race is 10 s old:
    # r0p5 and r0p20 are near it, r2p5 is not.
    sc.glob(G_TIMER, 40000)
    sc.rand(f=(0.25,), i=(5, 20, 85, 1))
    sc.op(OP_PLACE)
    sc.glob(G_TIMER, 200000)
    # A hundred tries, all of them visible; then good on the hundredth.
    sc.set(K_PDAT, 400.0)
    sc.rand(f=(0.25,), i=[rnd.randrange(8) for _ in range(100)])
    sc.op(OP_PLACE)
    sc.rand(f=(0.25,), i=[rnd.randrange(8) for _ in range(99)] + [39, 2])
    sc.op(OP_PLACE)
    sc.set(K_PDAT, 9000.0)
    # Either way with no points: no draw, no car.
    for k in range(3):
        rt.route(k, 0, [50, 51, 53][k])
    sc.op(OP_NEW)
    sc.op(OP_DUMP)
    sc.rand(f=(0.25,))
    sc.op(OP_PLACE)
    sc.rand(f=(0.75,))
    sc.op(OP_PLACE)
    standard_routes(rt)
    for k in range(3, 6):
        rt.route(k, 0, [60, 62, 69][k - 3])
    sc.op(OP_NEW)
    sc.op(OP_DUMP)
    sc.rand(f=(0.25,))
    sc.op(OP_PLACE)
    sc.rand(f=(0.75,))
    sc.op(OP_PLACE)
    standard_routes(rt)
    # The first forward slot empty, the rest not: only the last total
    # says whether there are any.
    rt.route(0, 0, 50)
    sc.op(OP_NEW)
    sc.op(OP_DUMP)
    sc.rand(f=(0.25,), i=(5, 2))
    sc.op(OP_PLACE)
    standard_routes(rt)
    sc.op(OP_NEW)
    # Elevations, headings and DATs of every kind; some too close, where the
    # generator draws on.
    for k in range(NROUTES):
        for i in (0, 13, 39):
            rt.field(k, i, PF_Z, f32(rnd.uniform(-50.0, 50.0)))
            a = rnd.uniform(-math.pi, math.pi)
            rt.field(k, i, PF_DX, f32(math.cos(a)))
            rt.field(k, i, PF_DY, f32(math.sin(a)))
    for k in range(NROUTES):
        for p in (0, 13, 39):
            sc.rand(f=(0.25 if k < 3 else 0.75,),
                    i=((k % 3) * ROUTE_POINTS + p, k % 4))
            sc.op(OP_PLACE)
    standard_routes(rt)


def try_script(sc, rt, rnd):
    sc.tag("try")
    standard_routes(rt)
    standard_world(sc)
    standard_race(sc)
    sc.op(OP_NEW)
    for i in range(NCARS):
        sc.car(i, C_DAT, 9000.0 + 100.0 * i)
    # The player (c0) at r0p4, DAT 400.
    sc.car(0, C_DAT, 400.0)
    sc.car(0, C_X, 12.5)
    sc.car(0, C_Y, -7.0)
    sc.set(K_PDAT, 400.0)
    sc.set(K_NEAR_ROUTE, 0)
    sc.set(K_NEAR_POINT, 4)
    sc.car(5, C_DAT, 100.0)
    # Off the routes: nothing.
    sc.set(K_NEAR_RET, 0)
    sc.rand(f=(0.25,), i=(0,))
    sc.op(OP_TRY, 5)
    sc.rand(f=(0.75,), i=(0,))
    sc.op(OP_TRY, 5)
    sc.set(K_NEAR_RET, 1)
    # 250 on is r0p14, DAT 650. The car is moved there unless it was
    # already ahead of the player and not as far as that.
    for carDat in (100.0, 900.0, 500.0, 649.0, 650.0, 651.0, 380.0, 400.0):
        sc.car(5, C_DAT, carDat)
        sc.rand(f=(0.25,), i=(0, 2))
        sc.op(OP_TRY, 5)
    # Walking back from r0p16 with the player there: r0p5, behind it.
    sc.car(0, C_DAT, 700.0)
    sc.set(K_PDAT, 700.0)
    sc.set(K_NEAR_POINT, 16)
    sc.car(5, C_DAT, 100.0)
    sc.rand(f=(0.75,), i=(0,))
    sc.op(OP_TRY, 5)
    sc.car(0, C_DAT, 400.0)
    sc.set(K_PDAT, 400.0)
    # Walking back from r0p4: off the start of the route.
    sc.set(K_NEAR_POINT, 4)
    sc.rand(f=(0.75,), i=(0,))
    sc.op(OP_TRY, 5)
    # Nowhere 250 on: the route's end.
    sc.set(K_NEAR_POINT, 35)
    sc.rand(f=(0.25,), i=(0,))
    sc.op(OP_TRY, 5)
    sc.set(K_NEAR_POINT, 4)
    # Too close to c6 at 650, 700 and 750; 800 is good.
    sc.car(6, C_DAT, 700.0)
    sc.car(5, C_DAT, 100.0)
    sc.rand(f=(0.25,), i=(0, 1))
    sc.op(OP_TRY, 5)
    # The other player, round the end of the track: r3 from 9800 on, the
    # player at r3p6 (9950), 250 on is r3p16 (200).
    rt.line(3, ROUTE_POINTS, dat0=9800.0, **route_geom(3))
    sc.glob(G_NPLAYERS, 2)
    sc.car(1, C_DAT, 9950.0)
    sc.car(1, C_X, -40.0)
    sc.set(K_PDAT, 9950.0)
    sc.set(K_NEAR_ROUTE, 3)
    sc.set(K_NEAR_POINT, 6)
    for carDat in (9900.0, 100.0, 200.0, 4000.0):
        sc.car(5, C_DAT, carDat)
        sc.rand(f=(0.25,), i=(1, 3))
        sc.op(OP_TRY, 5)
    sc.glob(G_NPLAYERS, 1)
    sc.car(1, C_DAT, 9100.0)
    sc.set(K_PDAT, 400.0)
    sc.set(K_NEAR_ROUTE, 0)
    sc.set(K_NEAR_POINT, 4)
    standard_routes(rt)
    # An undrawn car at r0p14 does not count (all = 0).
    sc.car(6, C_DAT, 9600.0)
    sc.car(3, C_DAT, 650.0)
    sc.car(3, C_RENDER, 0)
    sc.car(5, C_DAT, 100.0)
    sc.rand(f=(0.25,), i=(0, 2))
    sc.op(OP_TRY, 5)
    sc.car(3, C_RENDER, 1)
    sc.car(3, C_DAT, 9300.0)
    # The place level with the player (c0 at 650, the stand-in's player
    # DAT still 400): neither ahead nor behind.
    sc.car(0, C_DAT, 650.0)
    sc.rand(f=(0.25,), i=(0, 2))
    sc.op(OP_TRY, 5)
    sc.car(0, C_DAT, 400.0)
    sc.car(6, C_DAT, 700.0)
    # The skin left as it is.
    sc.car(5, C_DAT, 100.0)
    sc.car(5, C_SKIN, 12)
    sc.rand(f=(0.25,), i=(0, 2))
    sc.op(OP_TRY, 5)
    # A sign along the way: r0p9 always takes r4p30.
    sc.op(OP_SIGN, 30, 0x02, 62, 30)
    rt.sign(0, 9, 30)
    sc.rand(f=(0.25,), i=(0, 2))
    sc.op(OP_TRY, 5)
    rt.sign(0, 9, NO_SIGN)
    # A ulp past 250 on: r0p13 a ulp longer, so it is found there.
    rt.field(0, 13, PF_LEN, nextup(25.0, 1))
    sc.rand(f=(0.25,), i=(0, 2))
    sc.op(OP_TRY, 5)
    rt.field(0, 13, PF_LEN, 25.0)
    # And past 50 on from r0p14.
    rt.field(0, 15, PF_LEN, nextup(25.0, 1))
    sc.rand(f=(0.25,), i=(0, 2))
    sc.op(OP_TRY, 5)
    rt.field(0, 15, PF_LEN, 25.0)
    # Walking back on a route whose DATs fall: from r0p20 (800) 250 back
    # is r0p9 (1075), too close to c6 at 1100, then r0p6 (1150), and
    # r0p3 (1225) is good.
    rt.line(0, ROUTE_POINTS, dat0=1300.0, ddat=-25.0, **route_geom(0))
    sc.car(0, C_DAT, 800.0)
    sc.set(K_PDAT, 800.0)
    sc.set(K_NEAR_POINT, 20)
    sc.car(6, C_DAT, 1100.0)
    sc.rand(f=(0.75,), i=(0, 2))
    sc.op(OP_TRY, 5)
    standard_routes(rt)
    sc.car(0, C_DAT, 400.0)
    sc.set(K_PDAT, 400.0)
    sc.set(K_NEAR_POINT, 4)
    sc.car(6, C_DAT, 700.0)
    # The generator's directions and players.
    sc.glob(G_NPLAYERS, 2)
    sc.car(6, C_DAT, 9600.0)
    for carDat in (100.0, 3000.0, 9000.0):
        sc.car(5, C_DAT, carDat)
        sc.rand()
        sc.op(OP_TRY, 5)
    sc.glob(G_NPLAYERS, 1)
    standard_world(sc)
    sc.set(K_NEAR_ROUTE, 0)
    sc.set(K_NEAR_POINT, 0)


def step_script(sc, rt, rnd):
    sc.tag("step")
    standard_routes(rt)
    standard_world(sc)
    standard_race(sc)
    for i in range(NCARS):
        sc.car(i, C_DAT, 9000.0 + 100.0 * i)
    sc.car(0, C_DAT, 400.0)
    sc.set(K_PDAT, 400.0)
    sc.set(K_NEAR_ROUTE, 0)
    sc.set(K_NEAR_POINT, 4)
    sc.op(OP_NEW)
    sc.op(OP_DUMP)
    # Not now: thin traffic, no race, not racing, no players.
    sc.time(0.5)
    for g, v, back in ((G_DENSITY, nextup(0.4, -1), 0.5),
                       (G_DENSITY, Fb(0xff800000), 0.5),
                       (G_STAGE, 3, 4), (G_STAGE, 0, 4), (G_STAGE, 5, 4),
                       (G_RACE, 0, 1), (G_NPLAYERS, 0, 1)):
        sc.glob(g, v)
        sc.op(OP_STEP, 1.0)
        sc.op(OP_DUMP)
        sc.glob(g, back)
    # No traffic.
    sc.op(OP_WORLD, 2, 2)
    sc.op(OP_STEP, 1.0)
    sc.op(OP_DUMP)
    sc.op(OP_WORLD, NCARS, 2)
    sc.glob(G_DENSITY, 0.4)
    sc.op(OP_STEP, 0.25)
    sc.op(OP_DUMP)
    sc.glob(G_DENSITY, Fb(0x7fc00000))
    sc.rand()
    sc.op(OP_STEP, 0.25)
    sc.op(OP_DUMP)
    sc.glob(G_DENSITY, 0.5)
    # The clock running down.
    sc.time(5.0)
    for dt in (1.0, 2.5, 1.5, -1.0, 0.0, 1.0, Fb(0x7fc00000)):
        sc.rand(f=(0.25,), i=(0, 2))
        sc.op(OP_STEP, dt)
        sc.op(OP_DUMP)
    # Time up: the cars after LastCar in turn, the first out of sight moved.
    # `vis` are table indexes from TrafficCarPos.
    for last, vis in ((0, ()), (0, (1,)), (2, (3, 4)), (5, ()), (3, (4, 5)),
                      (1, (2, 3, 4, 5, 0)), (4, (5, 0, 1))):
        for i in range(NCARS - 2):
            sc.car(2 + i, C_DAT, 600.0 if i in vis else 9200.0 + 100.0 * i)
        sc.tpoke(1, last)
        sc.time(0.25)
        sc.rand(f=(0.25,), i=(0, 2))
        sc.op(OP_STEP, 0.25)
        sc.op(OP_DUMP)
    # All in sight: round to LastCar and stop.
    for i in range(2, NCARS):
        sc.car(i, C_DAT, 550.0)
    for last in (0, 3, 5):
        sc.tpoke(1, last)
        sc.time(0.0)
        sc.op(OP_STEP, 0.0)
        sc.op(OP_DUMP)
    # A smaller table, and LastCar past it.
    for i in range(2, NCARS):
        sc.car(i, C_DAT, 9000.0 + 100.0 * i)
    sc.op(OP_WORLD, 5, 2)
    for last in (0, 2, 4, 7, -1, -5):
        sc.tpoke(1, last)
        sc.time(0.0)
        sc.rand(f=(0.25,), i=(0, 2))
        sc.op(OP_STEP, 0.5)
        sc.op(OP_DUMP)
    sc.op(OP_WORLD, 3, 2)
    sc.tpoke(1, 0)
    sc.time(0.0)
    sc.car(2, C_DAT, 550.0)
    sc.op(OP_STEP, 0.5)
    sc.op(OP_DUMP)
    sc.op(OP_WORLD, NCARS, 2)
    # Densities' think times.
    for d in (1.0, 0.4, 0.9):
        sc.glob(G_DENSITY, d)
        sc.time(0.0)
        sc.rand(f=(0.25,), i=(0, 2))
        sc.op(OP_STEP, 0.5)
        sc.op(OP_DUMP)
    sc.glob(G_DENSITY, 0.5)
    # A run of steps on the generator alone.
    sc.glob(G_NPLAYERS, 2)
    sc.car(1, C_DAT, 5000.0)
    sc.time(0.0)
    sc.rand()
    for k in range(40):
        sc.op(OP_STEP, 0.75 if k % 3 else 2.5)
        sc.op(OP_DUMP)
    sc.glob(G_NPLAYERS, 1)


# ================================================================ the model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        e.stub_bware()
        self.heap = []                  # (addr, span, label)
        self.vals = dict.fromkeys(range(K_COUNT), 0)
        self.qi = deque()
        self.qf = deque()
        self.seed = 0
        self.order = []
        for base, n in ((T, 0x200), (WORLD, 0x600), (RACE, 0x800),
                        (INFO, 0x100), (PLAYERS, 0x100), (CTL, 0x200),
                        (FCVT, 0x200), (SCR, 0x200), (OUT, 0x200),
                        (RIDES, 0x200), (DRVS, 0x200),
                        (CTS, CT_SIZE * NCT), (CARS, 0x1000 * NCARS),
                        (SIGNS, 12 * NSIGNS),
                        (ROUTES, NROUTES * ROUTE_SPAN)):
            e.mem[base:base + n] = bytes(n)
        assert bytes(e.mem[0:0x700]) == bytes(0x700), "address 0 not 0"
        e.put32(GP + WORLD_GP, WORLD)
        e.put32(GP + RACE_GP, RACE)
        e.put32(GP + PLAYERS_GP, PLAYERS)
        e.put32(GP + PLAYERS_GP + 4, PLAYERS + 0x40)
        e.put32(GP + CTI_GP, CTS)
        e.put32(GP + SIGNPOSTS_GP, SIGNS)
        e.put32(WORLD, WORLD)
        e.put32(WORLD + 4, WORLD)
        for i in range(NCARS):
            c = self.car_addr(i)
            e.put32(c + CAR_RIDE, RIDES + 0x10 * i)
            e.put32(c + CAR_DRIVER, DRVS + 0x20 * i)
        e.put32(CTL + 8, FCVT)
        e.put32(FCVT + 44, FCVT_SETROUTE)
        self.stubs()

    def emit(self, s):
        self.out.append(s)

    def w(self, a):
        return self.e.u32(a)

    def car_addr(self, i):
        if i == NO_CAR:
            return 0
        assert 0 <= i < NCARS, i
        return CARS + 0x1000 * i

    def route_addr(self, k):
        if k < 0:
            return 0
        assert k < NROUTES, k
        return ROUTES + ROUTE_SPAN * k

    def point_addr(self, k, i):
        if k <= -2:
            return self.point_addr(-k - 2, i)
        if k < 0 or i < 0:
            return 0
        return self.route_addr(k) + POINT_TABLE + POINT_SIZE * i

    def ct_addr(self, k):
        return 0 if k < 0 else CTS + CT_SIZE * k

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        names = {T: "t", WORLD: "world", RACE: "race", INFO: "info",
                 CTL: "ctl", SCR: "scr", PLAYERS: "p0", PLAYERS + 0x40: "p1"}
        if a in names:
            return names[a]
        if CTL < a < CTL + 0x100:
            return "ctl+%d" % (a - CTL)
        if CTL - 0x100 < a < CTL:
            return "ctl-%d" % (CTL - a)
        if CARS <= a < CARS + 0x1000 * NCARS and (a - CARS) % 0x1000 == 0:
            return "c%d" % ((a - CARS) // 0x1000)
        if RIDES <= a < RIDES + 0x10 * NCARS and (a - RIDES) % 0x10 == 0:
            return "ride%d" % ((a - RIDES) // 0x10)
        if DRVS <= a < DRVS + 0x20 * NCARS and (a - DRVS) % 0x20 == 0:
            return "drv%d" % ((a - DRVS) // 0x20)
        if CTS <= a < CTS + CT_SIZE * NCT and (a - CTS) % CT_SIZE == 0:
            return "ct%d" % ((a - CTS) // CT_SIZE)
        if ROUTES <= a < ROUTES + ROUTE_SPAN * NROUTES:
            k, off = divmod(a - ROUTES, ROUTE_SPAN)
            if off < ROUTE_SIZE:
                if off == 0:
                    return "r%d" % k
                if off >= POINT_TABLE and (off - POINT_TABLE) % POINT_SIZE == 0:
                    return "r%dp%d" % (k, (off - POINT_TABLE) // POINT_SIZE)
                return "r%d+%d" % (k, off)
        if SIGNS <= a < SIGNS + 12 * NSIGNS and (a - SIGNS) % 12 == 0:
            return "s%d" % ((a - SIGNS) // 12)
        for base, span, name in self.heap:
            if base <= a < base + span:
                return name if a == base else "%s+%d" % (name, a - base)
        return "?"

    # ---- the random numbers ------------------------------------------------

    def lcg(self):
        self.seed = (self.seed * LCG_A + LCG_C) & M32
        return self.seed >> 8

    def rand_i(self, n):
        if self.qi:
            return s32(self.qi.popleft())
        r = self.lcg()
        return r % n if n > 0 else 0

    def rand_f(self, x):
        if self.qf:
            return self.qf.popleft()
        r = self.lcg()
        return fb(f32(f32(r * (1.0 / 16777216.0)) * bf(x)))

    # ---- the stand-ins ---------------------------------------------------

    def stubs(self):
        e = self.e

        def arg(i):
            return e.reg[4 + i] & M32

        def cstr(p):
            end = e.mem.index(b"\0", p)
            return e.mem[p:end].decode("latin-1")

        def malloc(em):
            size = s32(arg(0))
            name = cstr(arg(1))
            span = max(size, 0) + SLACK
            p = e.alloc(span, align=16)
            e.mem[p:p + span] = bytes([0xcd]) * span
            lab = "h%d" % len(self.heap)
            self.heap.append((p, span, lab))
            self.emit("  alloc %s size %d name %s flags %d pool %d"
                      % (lab, size, name, s32(arg(2)), s32(arg(3))))
            return p

        def free(em):
            self.emit("  free %s" % self.label(arg(0)))

        def rand_i(em):
            n = s32(arg(1))
            r = self.rand_i(n)
            self.emit("  rand %s %d -> %d" % (self.label(arg(0)), n, r))
            return r

        def rand_f(em):
            x = e.fpr[12] & M32
            r = self.rand_f(x)
            self.emit("  randf %s %s -> %s" % (self.label(arg(0)), fx(x),
                                               fx(r)))
            e.fpr[0] = r

        def dat_close(em):
            dat = e.fpr[12] & M32
            r = f32(bf(dat) - bf(self.vals[K_PDAT]))
            rb = CANON_NAN if r != r else fb(r)
            self.emit("  datclose %s %s -> %s" % (self.label(arg(0)), fx(dat),
                                                  fx(rb)))
            e.fpr[0] = rb

        def dist_close(em):
            p = arg(1)
            r = self.vals[K_DIST] & M32
            self.emit("  distclose %s %s %s -> %s" % (
                self.label(arg(0)), fx(self.w(p)), fx(self.w(p + 4)), fx(r)))
            e.fpr[0] = r

        def nearest(em):
            out, p = arg(0), arg(1)
            r = s32(self.vals[K_NEAR_RET])
            self.emit("  nearest %s %s %s routes %d %d %s -> %d" % (
                "scr" if out == e.reg[29] & M32 else "?",
                fx(self.w(p)), fx(self.w(p + 4)), s32(arg(2)), s32(arg(3)),
                fx(e.fpr[12]), r))
            if r:
                k = s32(self.vals[K_NEAR_ROUTE])
                e.put32(out, self.route_addr(k))
                e.put32(out + 4, self.point_addr(k,
                                                 s32(self.vals[K_NEAR_POINT])))
            return r

        def poofed(em):
            c = arg(0)
            i = (c - CARS) // 0x1000
            r = (self.vals[K_POOF_MASK] >> i) & 1
            self.emit("  poofed %s -> %d" % (self.label(c), r))
            return r

        def nskins(em):
            r = s32(self.vals[K_NSKINS])
            self.emit("  numskins %s -> %d" % (self.label(arg(0)), r))
            return r

        def skinnum(em):
            i = s32(arg(1))
            r = s32(i + s32(self.vals[K_SKINBASE]))
            self.emit("  skinnumber %s %d -> %d" % (self.label(arg(0)), i, r))
            return r

        def car_ctor(em):
            c, info, pos = arg(0), arg(1), arg(2)
            self.emit("  car init %s %s pos %s %s %s angle %d dat %s" % (
                self.label(c), self.label(info), fx(self.w(pos)),
                fx(self.w(pos + 4)), fx(self.w(pos + 8)), s32(arg(3)),
                fx(e.fpr[12])))
            e.put32(c + CAR_CTL, CTL)
            return c

        def set_move(em):
            self.emit("  mode %s %d" % (self.label(arg(0)), s32(arg(1))))

        def set_ctrl(em):
            self.emit("  control %s %d" % (self.label(arg(0)), s32(arg(1))))

        def reset_to(em):
            self.emit("  resetto %s %s %s speed %s blink %d dir %s" % (
                self.label(arg(0)), self.label(arg(1)), self.label(arg(2)),
                fx(e.fpr[12]), s32(arg(3)), fx(e.fpr[13])))

        def car_switch(em):
            self.emit("  switchskin %s %d" % (self.label(arg(0)),
                                              s32(arg(1))))

        def setroute(em):
            self.emit("  setroute %s %s %s" % (self.label(arg(0)),
                                               self.label(arg(1)),
                                               self.label(arg(2))))

        def tpc_ctor(em):
            return arg(0)

        def tpc_dtor(em):
            return None

        def tpc_reset(em):
            p = arg(1)
            self.emit("  reset %s %s" % (fx(self.w(p)), fx(self.w(p + 4))))

        e.stub(BMALLOC, malloc)
        e.stub(BFREE, free)
        e.stub(BDELETE, free)
        e.stub(RAND_I, rand_i)
        e.stub(RAND_F, rand_f)
        e.stub(DAT_CLOSE, dat_close)
        e.stub(DIST_CLOSE, dist_close)
        e.stub(NEAREST, nearest)
        e.stub(POOFED, poofed)
        e.stub(NSKINS, nskins)
        e.stub(SKINNUM, skinnum)
        e.stub(CAR_CTOR, car_ctor)
        e.stub(SET_MOVE, set_move)
        e.stub(SET_CTRL, set_ctrl)
        e.stub(RESET_TO, reset_to)
        e.stub(CAR_SWITCH, car_switch)
        e.stub(FCVT_SETROUTE, setroute)
        e.stub(TPC_CTOR, tpc_ctor)
        e.stub(TPC_DTOR, tpc_dtor)
        e.stub(TPC_RESET, tpc_reset)

    # ---- the dump --------------------------------------------------------

    def dump(self):
        w = self.w
        self.emit("t time %s last %d fwd %s back %s" % (
            fx(w(T)), s32(w(T + 4)),
            " ".join("%d" % w(T + 8 + 4 * i) for i in range(10)),
            " ".join("%d" % w(T + 48 + 4 * i) for i in range(10))))

    def static(self):
        self.emit("k min %s speed %s" % (fx(self.w(GP + MIN_DENSITY_GP)),
                                         fx(self.w(GP + SPEED_GP))))

    def links(self):
        e = self.e
        cars = [self.car_addr(i) for i in self.order]
        chain = [WORLD] + cars + [WORLD]
        for k in range(1, len(chain) - 1):
            e.put32(chain[k] + CAR_NEXT, chain[k + 1])
            e.put32(chain[k] + CAR_PREV, chain[k - 1])
        e.put32(WORLD, chain[1])
        e.put32(WORLD + 4, chain[-2])

    # ---- the run ---------------------------------------------------------

    def run(self, sc):
        e, w = self.e, self.w
        tags = sc.tags
        for o in sc.ops:
            code, a = o[0], o[1:]
            if code == OP_TAG:
                self.emit("[%s]" % tags[a[0]])
            elif code == OP_JUNK:
                e.mem[T:T + T_SIZE] = bytes([a[0] & 0xff]) * T_SIZE
            elif code == OP_NEW:
                r = e.call(CTOR, T)
                self.emit("new -> %s" % self.label(r))
            elif code == OP_DEL:
                self.emit("del %d" % s32(a[0]))
                e.call(DTOR, T, a[0])
            elif code == OP_STEP:
                self.emit("step %s" % fx(a[0]))
                e.fpr[12] = a[0] & M32
                e.call(STEP, T)
            elif code == OP_PLACE:
                self.emit("place")
                r = e.call(PLACE, T, INFO) & M32
                self.emit("place -> %s" % self.label(r))
                if r:
                    self.emit("  render %d" % s8(e.u8(r + CAR_RENDER)))
                self.emit("  info skin %d" % s8(e.u8(INFO + 17)))
            elif code == OP_TRY:
                self.emit("try %s" % self.label(self.car_addr(s32(a[0]))))
                e.call(TRY, T, self.car_addr(s32(a[0])))
            elif code == OP_GOOD:
                k, i, ex, al = (s32(x) for x in a)
                e.put32(SCR, self.route_addr(k))
                e.put32(SCR + 4, self.point_addr(k, i))
                r = e.call(GOOD, T, SCR, self.car_addr(ex), al)
                self.emit("good r%dp%d %s %d -> %d" % (
                    k, i, self.label(self.car_addr(ex)), al, r))
            elif code == OP_VIS:
                e.fpr[12] = a[0] & M32
                r = e.call(VIS, T)
                self.emit("vis %s -> %d" % (fx(a[0]), r))
            elif code == OP_VISAT:
                e.put32(SCR, a[0])
                e.put32(SCR + 4, a[1])
                r = e.call(VISAT, T, SCR)
                self.emit("visat -> %d" % r)
            elif code == OP_THINKT:
                e.call(THINKT, T)
            elif code == OP_FOB:
                r = e.call(FOB, T)
                self.emit("fob -> %d" % r)
            elif code == OP_FILL:
                for k in range(11):
                    e.put32(SCR + 4 * k, 0x5a5a5a5a)
                e.call(FILL, T, SCR, a[0])
                self.emit("fill %d -> %s" % (s32(a[0]), " ".join(
                    "%d" % s32(w(SCR + 4 * k)) for k in range(11))))
            elif code == OP_CLOSEAT:
                e.put32(SCR, a[0])
                e.put32(SCR + 4, a[1])
                r = e.call(CLOSEAT, T, SCR, self.car_addr(s32(a[2])), a[3])
                self.emit("closeat %s %s %s %d -> %d" % (
                    fx(a[0]), fx(a[1]), self.label(self.car_addr(s32(a[2]))),
                    s32(a[3]), r))
            elif code == OP_CLOSE:
                e.fpr[12] = a[0] & M32
                r = e.call(CLOSE, T, self.car_addr(s32(a[1])), a[2])
                self.emit("close %s %s %d -> %d" % (
                    fx(a[0]), self.label(self.car_addr(s32(a[1]))),
                    s32(a[2]), r))
            elif code == OP_PICK:
                e.put32(SCR, 0x5a5a5a5a)
                e.put32(SCR + 4, 0x5a5a5a5a)
                e.call(PICK, T, SCR, a[0])
                self.emit("pick %d -> %s %s" % (s32(a[0]), self.label(w(SCR)),
                                                self.label(w(SCR + 4))))
            elif code == OP_RPC:
                r = e.call(RPC, T)
                self.emit("rpc -> %s" % self.label(r))
            elif code == OP_SKIN:
                r = e.call(SKIN, T, self.ct_addr(s32(a[0])))
                self.emit("skin -> %d" % r)
            elif code == OP_SWITCH:
                self.emit("switch %s" % self.label(self.car_addr(s32(a[0]))))
                e.call(SWITCH, T, self.car_addr(s32(a[0])))
            elif code == OP_GTD:
                count, k, i, dist, fwd = a
                for j in range(2 * NOUT):
                    e.put32(OUT + 4 * j, 0x5a5a5a5a)
                e.fpr[12] = dist & M32
                r = e.call(GTD, OUT, count, self.route_addr(s32(k)),
                           self.point_addr(s32(k), s32(i)), fwd)
                assert r <= NOUT, "gtd wrote %d" % r
                n = min(NOUT, max(r, count & M32, 0) + 1)
                self.emit("gtd %d r%dp%d %s %d -> %d %s" % (
                    count & M32, s32(k), s32(i), fx(dist), s32(fwd), r,
                    " ".join("%s/%s" % (self.label(w(OUT + 8 * j)),
                                        self.label(w(OUT + 8 * j + 4)))
                             for j in range(n))))
            elif code == OP_DUMP:
                self.dump()
            elif code == OP_STATIC:
                self.static()
            elif code == OP_TPOKE:
                e.put32(T + 4 * a[0], a[1])
            elif code == OP_SET:
                self.vals[a[0]] = a[1] & M32
                if a[0] == K_CTLDELTA:
                    e.write(FCVT + 40, struct.pack("<h", s16(a[1])))
            elif code == OP_RI:
                self.qi.append(a[0] & M32)
            elif code == OP_RF:
                self.qf.append(a[0] & M32)
            elif code == OP_SEED:
                self.seed = a[0] & M32
            elif code == OP_RCLEAR:
                self.qi.clear()
                self.qf.clear()
            elif code == OP_GLOBAL:
                self.glob(a[0], a[1])
            elif code == OP_SLOT:
                e.put32(ROUTE_MANAGER + 16 + 4 * a[0], self.route_addr(s32(a[1])))
            elif code == OP_ROUTE:
                r = self.route_addr(a[0])
                e.put32(r + 16, a[1])
                e.write(r + 10, struct.pack("<h", s16(a[2])))
            elif code == OP_RPOINT:
                k, i, f, v = a
                e.put32(self.point_addr(k, i) + PF_OFF[f], v)
            elif code == OP_SIGN:
                p = SIGNS + 12 * a[0]
                e.write(p, bytes([a[2] & 0xff, a[1] & 0xff]))
                e.write(p + 2, struct.pack("<H", a[3] & 0xffff))
            elif code == OP_CAR:
                self.car_field(s32(a[0]), a[1], a[2])
            elif code == OP_LCLEAR:
                self.order = []
                self.links()
            elif code == OP_LADD:
                self.order.append(s32(a[0]))
                self.links()
            elif code == OP_WORLD:
                e.put32(WORLD + 28, a[0])
                e.put32(WORLD + 40, a[1])
            elif code == OP_TABLE:
                e.put32(WORLD + 44 + 4 * a[0], self.car_addr(s32(a[1])))
            elif code == OP_PLAYER:
                e.put32(PLAYERS + 0x40 * a[0] + 4, self.car_addr(s32(a[1])))
            elif code == OP_INFO:
                e.put32(INFO + 12, a[0])
                e.write(INFO + 17, bytes([a[1] & 0xff]))
            else:
                raise ValueError("op %d" % code)
        return self.out

    def glob(self, g, v):
        e = self.e
        if g == G_DENSITY:
            e.put32(DENSITY, v)
        elif g == G_ONCOMING:
            e.put32(ONCOMING, v)
        elif g == G_TRACKLEN:
            e.put32(TRACK_PATH, v)
        elif g == G_TIMER:
            e.put32(GP + TIMER_GP, v)
        elif g == G_NPLAYERS:
            e.put32(GP + NPLAYERS_GP, v)
        elif g == G_RACE:
            e.put32(GP + RACE_GP, RACE if v else 0)
        elif g == G_STAGE:
            e.put32(RACE, v)
        elif g == G_START:
            e.put32(RACE + 12, v)
        elif g == G_BOUNDARY:
            e.write(RACE + 1618, bytes([v & 0xff]))
        elif G_BDIST <= g < G_BDIST + NBDIST:
            e.put32(RACE + 1620 + 4 * (g - G_BDIST), v)
        else:
            raise ValueError("global %d" % g)

    def car_field(self, i, f, v):
        e = self.e
        c = self.car_addr(i)
        if f == C_DAT:
            e.put32(c + CAR_DAT, v)
        elif f == C_X:
            e.put32(c + CAR_X, v)
        elif f == C_Y:
            e.put32(c + CAR_Y, v)
        elif f == C_RENDER:
            e.write(c + CAR_RENDER, bytes([v & 0xff]))
        elif f == C_DTYPE:
            e.put32(DRVS + 0x20 * i + 8, v)
        elif f == C_CT:
            e.put32(c + CAR_CT, self.ct_addr(s32(v)))
        elif f == C_SKIN:
            e.write(RIDES + 0x10 * i + 5, bytes([v & 0xff]))
        else:
            raise ValueError("car field %d" % f)


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc.encode().hex().splitlines()
                               + sc.tags, lambda s: Model().run(sc),
                               cut=MUTATIONS_HEADER)


# ================================================================ the build


def build_harness(tmp, name="traffictele_test"):
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

def M(name, before, after):
    return (name, TTC, before, after)


def P(name, before, after):
    return (name, APC, before, after)


def H(name, before, after):
    return (name, TTH, before, after)


def A(name, before, after):
    return (name, APH, before, after)


MUTATIONS = [
    # The constructor.
    M("ctor_nan_held",
      "    if (t->TimeUntilTeleport < TELEPORT_FIRST_THINK)\n",
      "    if (!(t->TimeUntilTeleport >= TELEPORT_FIRST_THINK))\n"),
    M("ctor_last_car", "    t->LastCar = 0;\n", "    t->LastCar = 1;\n"),
    M("ctor_no_think",
      "    traffic_teleporter_set_think_time(t);\n    // `c.lt.s`",
      "    // `c.lt.s`"),
    M("ctor_backward_first",
      "TRAFFIC_BACKWARD_ROUTES);\n    traffic_teleporter_set_think_time",
      "TRAFFIC_FORWARD_ROUTES);\n    traffic_teleporter_set_think_time"),
    M("first_think", "#define TELEPORT_FIRST_THINK 20.0f",
      "#define TELEPORT_FIRST_THINK 19.5f"),
    M("dtor_flags", "    if (flags & 1)\n", "    if (flags & 3)\n"),

    # DoTimestep.
    M("step_density_le", "TrafficDensity < TELEPORT_MIN_DENSITY)",
      "TrafficDensity <= TELEPORT_MIN_DENSITY)"),
    M("step_density_nan",
      "    if (TheRaceParameters.TrafficDensity < TELEPORT_MIN_DENSITY)\n",
      "    if (!(TheRaceParameters.TrafficDensity >= TELEPORT_MIN_DENSITY))\n"),
    M("step_no_traffic",
      "    if (w->TotalNumCars == w->TrafficCarPos)\n        return;\n", ""),
    M("step_stage", "!= RACE_STAGE_RACING)", "< RACE_STAGE_RACING)"),
    M("step_players", "    if (PlayerNumPlayers == 0)\n",
      "    if (PlayerNumPlayers < 0)\n"),
    M("step_dt", "t->TimeUntilTeleport - dt;", "t->TimeUntilTeleport + dt;"),
    M("step_time_le", "    if (0.0f < t->TimeUntilTeleport)\n",
      "    if (0.0f <= t->TimeUntilTeleport)\n"),
    M("step_time_nan", "    if (0.0f < t->TimeUntilTeleport)\n",
      "    if (!(0.0f >= t->TimeUntilTeleport))\n"),
    M("step_no_rethink",
      "        return;\n    traffic_teleporter_set_think_time(t);\n",
      "        return;\n"),
    M("step_from_zero", "    i = (uint32_t)t->LastCar;\n", "    i = 0;\n"),
    M("step_wrap_le",
      "    if (!(i < (uint32_t)(w->TotalNumCars - w->TrafficCarPos)))",
      "    if (!(i <= (uint32_t)(w->TotalNumCars - w->TrafficCarPos)))"),
    M("step_wrap_signed",
      "if (!(i < (uint32_t)(w->TotalNumCars - w->TrafficCarPos)))",
      "if (!((int32_t)i < (w->TotalNumCars - w->TrafficCarPos)))"),
    M("step_table", "w->CarTable[w->TrafficCarPos + (int32_t)i]",
      "w->CarTable[(int32_t)i]"),
    M("step_vis_dat",
      "                t, c->TheTrackPathCoordinate.DistanceAroundTrack)) {",
      "                t, 0.0f)) {"),
    M("step_last_car_kept", "            t->LastCar = (int32_t)i;\n", ""),
    M("step_round", "        if (i == (uint32_t)t->LastCar)\n            return;\n",
      ""),

    # PlaceNewCar.
    M("place_and",
      "    if (t->ForwardTotals[TRAFFIC_ROUTES_EACH - 1] == 0\n        ||",
      "    if (t->ForwardTotals[TRAFFIC_ROUTES_EACH - 1] == 0\n        &&"),
    M("place_first_total",
      "    if (t->ForwardTotals[TRAFFIC_ROUTES_EACH - 1] == 0\n",
      "    if (t->ForwardTotals[0] == 0\n"),
    M("place_fwd_after",
      "    fwd = traffic_teleporter_forwards_or_backwards(t);\n"
      "    if (t->ForwardTotals[TRAFFIC_ROUTES_EACH - 1] == 0\n"
      "        || t->BackwardTotals[TRAFFIC_ROUTES_EACH - 1] == 0)\n"
      "        return NULL;\n",
      "    if (t->ForwardTotals[TRAFFIC_ROUTES_EACH - 1] == 0\n"
      "        || t->BackwardTotals[TRAFFIC_ROUTES_EACH - 1] == 0)\n"
      "        return NULL;\n"
      "    fwd = traffic_teleporter_forwards_or_backwards(t);\n"),
    M("place_tries_le", "    if (!(++tries < TELEPORT_PLACE_TRIES))",
      "    if (!(++tries <= TELEPORT_PLACE_TRIES))"),
    M("place_all", "traffic_teleporter_is_good_place(t, &rp, NULL, 1)",
      "traffic_teleporter_is_good_place(t, &rp, NULL, 0)"),
    M("place_no_reset",
      "    trackpath_coord_reset_position(&coord, &p->Position);\n", ""),
    M("place_atan",
      "bATan(rp.Point->Direction.x, rp.Point->Direction.y)",
      "bATan(rp.Point->Direction.y, rp.Point->Direction.x)"),
    M("place_x", "    pos.x = p->Position.x;\n", "    pos.x = p->Position.y;\n"),
    M("place_z", "    pos.z = rp.Point->Elevation;\n", "    pos.z = 0.0f;\n"),
    M("place_skin_type", "cartypeinfo_get(info->CurrentRideInfo.Type)",
      "cartypeinfo_get(0)"),
    M("place_skin_kept",
      "    info->CurrentRideInfo.SkinNumber = (int8_t)\n",
      "    (void)\n"),
    M("place_pool", "\"Car\", 0, CAR_MEMORY_POOL)", "\"Car\", 0, 0)"),
    M("place_dat", "                      rp.Point->DistanceAroundTrack);",
      "                      0.0f);"),
    M("place_movement", "    car_set_movement_mode(c, eNO_MOVEMENT);",
      "    car_set_movement_mode(c, TRAFFIC_MOVEMENT);"),
    M("place_control", "    car_set_control_mode(c, TRAFFIC_CONTROL);",
      "    car_set_control_mode(c, 0);"),
    M("place_vt_this", "(vt_this(ctl, e), rp.Route, rp.Point);",
      "(ctl, rp.Route, rp.Point);"),
    M("place_route_point", "(vt_this(ctl, e), rp.Route, rp.Point);",
      "(vt_this(ctl, e), rp.Route, NULL);"),
    M("place_render", "    c->RenderingEnabled = 0;\n",
      "    c->RenderingEnabled = 1;\n"),

    # TryToTeleportCar.
    M("try_order",
      "    fwd = traffic_teleporter_forwards_or_backwards(t);\n"
      "    pc = traffic_teleporter_random_player_car(t);\n",
      "    pc = traffic_teleporter_random_player_car(t);\n"
      "    fwd = traffic_teleporter_forwards_or_backwards(t);\n"),
    M("try_car_ahead_swap",
      "&TheTrackPathManager, c->TheTrackPathCoordinate.DistanceAroundTrack,\n"
      "        pc->TheTrackPathCoordinate.DistanceAroundTrack);",
      "&TheTrackPathManager, pc->TheTrackPathCoordinate.DistanceAroundTrack,\n"
      "        c->TheTrackPathCoordinate.DistanceAroundTrack);"),
    M("try_routes", "fwd ? FORWARD_TRAFFIC_ROUTES : ONCOMING_TRAFFIC_ROUTES",
      "fwd ? ONCOMING_TRAFFIC_ROUTES : FORWARD_TRAFFIC_ROUTES"),
    M("try_first_ahead", "TELEPORT_FIRST_AHEAD, fwd)",
      "TELEPORT_STEP_AHEAD, fwd)"),
    M("try_first_fwd", "TELEPORT_FIRST_AHEAD, fwd)",
      "TELEPORT_FIRST_AHEAD, !fwd)"),
    M("try_first_fails",
      "TELEPORT_FIRST_AHEAD, fwd) != 1)\n        return;\n",
      "TELEPORT_FIRST_AHEAD, fwd) < 0)\n        return;\n"),
    M("try_step_ahead", "TELEPORT_STEP_AHEAD, fwd)",
      "TELEPORT_FIRST_AHEAD, fwd)"),
    M("try_step_fwd", "TELEPORT_STEP_AHEAD, fwd)", "TELEPORT_STEP_AHEAD, 1)"),
    M("try_ahead_from", "info.Point->DistanceAroundTrack,\n"
      "            pc->TheTrackPathCoordinate.DistanceAroundTrack);",
      "info.Point->DistanceAroundTrack,\n"
      "            c->TheTrackPathCoordinate.DistanceAroundTrack);"),
    M("try_except", "traffic_teleporter_is_good_place(t, &info, c, 0)",
      "traffic_teleporter_is_good_place(t, &info, NULL, 0)"),
    M("try_all", "traffic_teleporter_is_good_place(t, &info, c, 0)",
      "traffic_teleporter_is_good_place(t, &info, c, 1)"),
    M("try_car_zero_le", "            if (0.0f < carAhead && carAhead < ahead)",
      "            if (0.0f <= carAhead && carAhead < ahead)"),
    M("try_car_ahead_le", "if (0.0f < carAhead && carAhead < ahead)",
      "if (0.0f < carAhead && carAhead <= ahead)"),
    M("try_car_or", "if (0.0f < carAhead && carAhead < ahead)",
      "if (0.0f < carAhead || carAhead < ahead)"),
    M("try_ahead_le", "            if (ahead < 0.0f)\n",
      "            if (ahead <= 0.0f)\n"),
    M("try_blink", "TELEPORT_SPEED, 0, 1.0f);", "TELEPORT_SPEED, 1, 1.0f);"),
    M("try_dir", "TELEPORT_SPEED, 0, 1.0f);", "TELEPORT_SPEED, 0, -1.0f);"),
    M("try_movement", "    car_set_movement_mode(c, TRAFFIC_MOVEMENT);",
      "    car_set_movement_mode(c, eNO_MOVEMENT);"),
    M("try_no_skin", "            traffic_teleporter_switch_skin(t, c);\n", ""),

    # IsGoodPlace.
    M("good_unsigned",
      "(float)(int32_t)((uint32_t)WorldTimer - r->StartTime.PackedTime)",
      "(float)((uint32_t)WorldTimer - r->StartTime.PackedTime)"),
    M("good_time_le", "               * TELEPORT_TICK < TELEPORT_START_TIME) {",
      "               * TELEPORT_TICK <= TELEPORT_START_TIME) {"),
    M("tick", "#define TELEPORT_TICK        0.00025f",
      "#define TELEPORT_TICK        0.000251f"),
    M("good_tracklen",
      "float start = TheTrackPathManager.TrackLength * TELEPORT_PERCENT",
      "float start = 100000.0f * TELEPORT_PERCENT"),
    M("percent", "#define TELEPORT_PERCENT     0.01f",
      "#define TELEPORT_PERCENT     0.0101f"),
    M("good_boundary", "r->BoundaryDistances[r->StartLineBoundaryNumber]",
      "r->BoundaryDistances[1]"),
    M("good_fabs",
      "        if (fabsf(trackpath_compare_distances(\n"
      "                &TheTrackPathManager, info->Point->DistanceAroundTrack,\n"
      "                start)) < TELEPORT_START_CLEAR)",
      "        if ((trackpath_compare_distances(\n"
      "                &TheTrackPathManager, info->Point->DistanceAroundTrack,\n"
      "                start)) < TELEPORT_START_CLEAR)"),
    M("good_swap",
      "                &TheTrackPathManager, info->Point->DistanceAroundTrack,\n"
      "                start)) < TELEPORT_START_CLEAR)",
      "                &TheTrackPathManager, start,\n"
      "                info->Point->DistanceAroundTrack)) < TELEPORT_START_CLEAR)"),
    M("good_clear_le", "start)) < TELEPORT_START_CLEAR)",
      "start)) <= TELEPORT_START_CLEAR)"),
    M("good_vis_anyway",
      "    if (!nearStart) {\n        if (traffic_teleporter_check_is_visible(",
      "    if (1) {\n        if (traffic_teleporter_check_is_visible("),
    M("good_vis_ignored",
      "                t, info->Point->DistanceAroundTrack))\n            return 0;\n",
      "                t, info->Point->DistanceAroundTrack))\n            ;\n"),
    M("good_except", "            t, info->Point->DistanceAroundTrack, except, all);",
      "            t, info->Point->DistanceAroundTrack, NULL, all);"),
    M("good_all", "            t, info->Point->DistanceAroundTrack, except, all);",
      "            t, info->Point->DistanceAroundTrack, except, 1);"),
    M("good_too_close", "    return !nearStart && !tooClose;",
      "    return !nearStart;"),
    M("good_near_start", "    return !nearStart && !tooClose;",
      "    return !tooClose;"),

    # CheckIsVisible, CheckIsVisibleAt, SetThinkTime and
    # ForwardsOrBackwards.
    M("visat_le", "           < TELEPORT_SIGHT;\n}\n\nint32_t "
      "traffic_teleporter_check_is_visible(",
      "           <= TELEPORT_SIGHT;\n}\n\nint32_t "
      "traffic_teleporter_check_is_visible("),
    M("vis_le", "pCurrentWorld, dat))\n           < TELEPORT_SIGHT;",
      "pCurrentWorld, dat))\n           <= TELEPORT_SIGHT;"),
    M("vis_nan",
      "    return fabsf(world_get_dat_to_closest_player(pCurrentWorld, dat))\n"
      "           < TELEPORT_SIGHT;",
      "    return !(fabsf(world_get_dat_to_closest_player(pCurrentWorld, dat))\n"
      "           >= TELEPORT_SIGHT);"),
    M("vis_fabs",
      "    return fabsf(world_get_dat_to_closest_player(pCurrentWorld, dat))",
      "    return (world_get_dat_to_closest_player(pCurrentWorld, dat))"),
    M("think_scale", "* 15.0f + 1.0f", "* 16.0f + 1.0f"),
    M("think_add", "* 15.0f + 1.0f", "* 15.0f + 2.0f"),
    M("think_one", "(1.0f - TheRaceParameters.TrafficDensity)",
      "(1.5f - TheRaceParameters.TrafficDensity)"),
    M("fob_le", "           < TheRaceParameters.TrafficOncoming;",
      "           <= TheRaceParameters.TrafficOncoming;"),
    M("fob_range", "world_random_f(pCurrentWorld, 1.0f)",
      "world_random_f(pCurrentWorld, 2.0f)"),

    # FillInTotals.
    M("fill_missing",
      "        if (r != NULL)\n            total += (uint32_t)r->NumPoints;\n"
      "        out[i] = total;",
      "        total += r != NULL ? (uint32_t)r->NumPoints : 1u;\n"
      "        out[i] = total;"),
    M("fill_out_first",
      "        if (r != NULL)\n            total += (uint32_t)r->NumPoints;\n"
      "        out[i] = total;",
      "        out[i] = total;\n        if (r != NULL)\n"
      "            total += (uint32_t)r->NumPoints;"),
    M("fill_nine", "    for (i = 0; i < TRAFFIC_ROUTES_EACH; i++) {",
      "    for (i = 0; i < TRAFFIC_ROUTES_EACH - 1; i++) {"),
    M("fill_first", "first + i);\n\n        if (r != NULL)",
      "first + i + 1);\n\n        if (r != NULL)"),

    # TooCloseToAnotherCar and TooCloseAt.
    M("skip_except", "    if (c == except)\n        return 1;\n", ""),
    M("skip_poof", "    if (car_is_poofed(c))\n        return 1;\n",
      "    (void)car_is_poofed(c);\n"),
    M("skip_order",
      "    if (c == except)\n        return 1;\n"
      "    if (car_is_poofed(c))\n        return 1;\n",
      "    if (car_is_poofed(c))\n        return 1;\n"
      "    if (c == except)\n        return 1;\n"),
    M("skip_all", "    return !all && c->RenderingEnabled == 0;",
      "    return c->RenderingEnabled == 0;"),
    M("skip_render", "    return !all && c->RenderingEnabled == 0;",
      "    return !all && c->RenderingEnabled != 0;"),
    M("closeat_le", "        if (sqrtf(dx * dx + dy * dy) < TELEPORT_TOO_CLOSE)",
      "        if (sqrtf(dx * dx + dy * dy) <= TELEPORT_TOO_CLOSE)"),
    M("closeat_dx", "        dx = pos->x - c->State.Position.x;",
      "        dx = pos->x + c->State.Position.x;"),
    M("closeat_dy", "        dy = pos->y - c->State.Position.y;",
      "        dy = pos->y - c->State.Position.x;"),
    M("closeat_skip",
      "        if (skip_car(c, except, all))\n            continue;\n        dx",
      "        if (skip_car(c, except, 0))\n            continue;\n        dx"),
    M("close_skip",
      "        if (skip_car(c, except, all))\n            continue;\n        d =",
      "        if (skip_car(c, except, 1))\n            continue;\n        d ="),
    M("close_swap",
      "            &TheTrackPathManager, dat,\n"
      "            c->TheTrackPathCoordinate.DistanceAroundTrack);",
      "            &TheTrackPathManager,\n"
      "            c->TheTrackPathCoordinate.DistanceAroundTrack, dat);"),
    M("close_type", "== DRIVER_TYPE_TRAFFIC_CAR)", "!= DRIVER_TYPE_TRAFFIC_CAR)"),
    M("close_traffic_le", "            if (fabsf(d) < TELEPORT_TOO_CLOSE)",
      "            if (fabsf(d) <= TELEPORT_TOO_CLOSE)"),
    M("close_traffic_fabs", "            if (fabsf(d) < TELEPORT_TOO_CLOSE)",
      "            if (d < TELEPORT_TOO_CLOSE)"),
    M("close_racer_le", "        } else if (d < TELEPORT_TOO_CLOSE && 0.0f < d) {",
      "        } else if (d <= TELEPORT_TOO_CLOSE && 0.0f < d) {"),
    M("close_racer_zero", "        } else if (d < TELEPORT_TOO_CLOSE && 0.0f < d) {",
      "        } else if (d < TELEPORT_TOO_CLOSE && 0.0f <= d) {"),
    M("close_racer_fabs", "        } else if (d < TELEPORT_TOO_CLOSE && 0.0f < d) {",
      "        } else if (fabsf(d) < TELEPORT_TOO_CLOSE) {"),

    # PickRoutePoint, RandomPlayerCar, PickRandomSkin and SwitchSkin.
    M("pick_totals",
      "    const uint32_t *totals = fwd ? t->ForwardTotals : t->BackwardTotals;",
      "    const uint32_t *totals = t->ForwardTotals;"),
    M("pick_first",
      "fwd ? TRAFFIC_FORWARD_ROUTES\n                                : TRAFFIC_BACKWARD_ROUTES;",
      "fwd ? TRAFFIC_BACKWARD_ROUTES\n                                : TRAFFIC_FORWARD_ROUTES;"),
    M("pick_range", "(int32_t)totals[TRAFFIC_ROUTES_EACH - 1]);",
      "(int32_t)totals[TRAFFIC_ROUTES_EACH - 2]);"),
    M("pick_le", "        while (!(n < totals[i]))",
      "        while (!(n <= totals[i]))"),
    M("pick_no_sub", "        if (i != 0)\n            n -= totals[i - 1];\n", ""),
    M("pick_sub_same", "            n -= totals[i - 1];\n",
      "            n -= totals[i];\n"),
    M("pick_tries",
      "    } while (tries < TELEPORT_PICK_TRIES && !trpoint_is_posted(p));",
      "    } while (tries < TELEPORT_PICK_TRIES - 1 && !trpoint_is_posted(p));"),
    M("pick_no_posted",
      "    } while (tries < TELEPORT_PICK_TRIES && !trpoint_is_posted(p));",
      "    } while (0);"),
    M("rpc_range", "PlayerNumPlayers)]->MyCar", "1)]->MyCar"),
    M("skin_none_le", "    if (n == 0)\n        return 0;\n",
      "    if (n <= 0)\n        return 0;\n"),
    M("skin_none", "    if (n == 0)\n        return 0;\n",
      "    if (n == 0)\n        return -1;\n"),
    M("skin_range", "world_random_i(pCurrentWorld, n));",
      "world_random_i(pCurrentWorld, n - 1));"),
    M("switch_unsigned", "    if (skin != c->pRideInfo->SkinNumber)",
      "    if (skin != (uint8_t)c->pRideInfo->SkinNumber)"),
    M("switch_always", "    if (skin != c->pRideInfo->SkinNumber)\n", "    if (1)\n"),

    # The header's numbers.
    H("min_density", "#define TELEPORT_MIN_DENSITY  0.4f",
      "#define TELEPORT_MIN_DENSITY  0.40001f"),
    H("sight", "#define TELEPORT_SIGHT        250.0f",
      "#define TELEPORT_SIGHT        250.01f"),
    H("first_ahead", "#define TELEPORT_FIRST_AHEAD  250.0f",
      "#define TELEPORT_FIRST_AHEAD  250.01f"),
    H("step_ahead", "#define TELEPORT_STEP_AHEAD   50.0f",
      "#define TELEPORT_STEP_AHEAD   50.01f"),
    H("speed", "#define TELEPORT_SPEED        24.5865f",
      "#define TELEPORT_SPEED        24.5866f"),
    H("too_close", "#define TELEPORT_TOO_CLOSE    100.0f",
      "#define TELEPORT_TOO_CLOSE    100.01f"),
    H("start_time", "#define TELEPORT_START_TIME   20.0f",
      "#define TELEPORT_START_TIME   20.01f"),
    H("start_clear", "#define TELEPORT_START_CLEAR  2000.0f",
      "#define TELEPORT_START_CLEAR  2000.1f"),
    H("place_tries_100", "#define TELEPORT_PLACE_TRIES  100",
      "#define TELEPORT_PLACE_TRIES  99"),
    H("pick_tries_101", "#define TELEPORT_PICK_TRIES   101",
      "#define TELEPORT_PICK_TRIES   100"),
    H("forward_routes", "#define TRAFFIC_FORWARD_ROUTES  50",
      "#define TRAFFIC_FORWARD_ROUTES  51"),
    H("backward_routes", "#define TRAFFIC_BACKWARD_ROUTES 60",
      "#define TRAFFIC_BACKWARD_ROUTES 61"),

    # GuessTargetDestinations.
    P("gtd_null_route", "    if (route == NULL || point == NULL)\n",
      "    if (point == NULL)\n"),
    P("gtd_null_point", "    if (route == NULL || point == NULL)\n",
      "    if (route == NULL)\n"),
    P("gtd_back_length", "        cur.Dist = dist + point->Length;\n",
      "        cur.Dist = dist;\n"),
    P("gtd_back_fwd", "    if (!fwd)\n        cur.Dist", "    if (fwd)\n        cur.Dist"),
    P("gtd_sub", "        cur.Dist = cur.Dist - p->Length;\n",
      "        cur.Dist = cur.Dist - p->Length * 0.5f;\n"),
    P("gtd_found_le", "        if (cur.Dist < 0.0f) {\n",
      "        if (cur.Dist <= 0.0f) {\n"),
    P("gtd_found_nan", "        if (cur.Dist < 0.0f) {\n",
      "        if (!(cur.Dist >= 0.0f)) {\n"),
    P("gtd_count", "            if ((uint32_t)found == count)\n",
      "            if ((uint32_t)found > count)\n"),
    P("gtd_out", "            out++;\n", ""),
    P("gtd_found_keeps", "            out++;\n            cur.Point = NULL;\n",
      "            out++;\n            cur.Point = step(cur.Route, p, fwd);\n"),
    P("gtd_has_signpost", "            if (trpoint_has_signpost(p)) {",
      "            if (trpoint_has_signpost(p) && fwd) {"),
    P("gtd_backwards_ignored", "                if (fwd ? !back : back) {\n",
      "                if (1) {\n"),
    P("gtd_backwards_fwd", "                if (fwd ? !back : back) {\n",
      "                if (!back) {\n"),
    P("gtd_sign_mask", "    uint32_t sign = s->Flags & SIGNPOST_SIGN_MASK;",
      "    uint32_t sign = s->Flags & 0x0fu;"),
    P("gtd_stop", "                        cur.Dist = -1.0f;\n",
      "                        cur.Dist = cur.Dist;\n"),
    P("gtd_stop_advance", "                    advance = 0;\n", ""),
    P("gtd_always_minus",
      "                        cur.Dist = across(cur.Dist, p, to);\n",
      "                        cur.Dist = cur.Dist - p->Length;\n"),
    P("gtd_always_route",
      "                        cur.Route = signpost_get_new_route(s);\n"
      "                        cur.Point = to;",
      "                        cur.Point = to;"),
    P("across_length", "    return (dist + p->Length)\n", "    return (dist)\n"),
    P("across_sign",
      "           - ((to->Position.x - p->Position.x) * p->Direction.x",
      "           + ((to->Position.x - p->Position.x) * p->Direction.x"),
    P("across_x", "((to->Position.x - p->Position.x) * p->Direction.x",
      "((to->Position.x - p->Position.y) * p->Direction.x"),
    P("across_y",
      "              + (to->Position.y - p->Position.y) * p->Direction.y);",
      "              + 0.0f * p->Direction.y);"),
    P("branch_dist",
      "                        branch.Dist = across(cur.Dist, p, branch.Point);\n",
      "                        branch.Dist = cur.Dist;\n"),
    P("branch_way_fwd",
      "                        cur.Point = step(cur.Route, p, fwd);\n"
      "                        if (cur.Point != NULL && !q.Full)",
      "                        cur.Point = step(cur.Route, p, 1);\n"
      "                        if (cur.Point != NULL && !q.Full)"),
    P("branch_way_dropped",
      "                        if (cur.Point != NULL && !q.Full)\n"
      "                            push_front(&q, &cur);\n", ""),
    P("branch_way_back",
      "                        if (cur.Point != NULL && !q.Full)\n"
      "                            push_front(&q, &cur);\n",
      "                        if (cur.Point != NULL && !q.Full)\n"
      "                            push_back(&q, &cur);\n"),
    P("branch_way_full", "                        if (cur.Point != NULL && !q.Full)\n",
      "                        if (cur.Point != NULL)\n"),
    P("branch_way_null", "                        if (cur.Point != NULL && !q.Full)\n",
      "                        if (!q.Full)\n"),
    P("branch_full", "                        if (!q.Full) {\n                            if (sign",
      "                        {\n                            if (sign"),
    P("branch_faster_back",
      "                            if (sign == SIGN_FASTER)\n"
      "                                push_front(&q, &branch);",
      "                            if (sign == SIGN_FASTER)\n"
      "                                push_back(&q, &branch);"),
    P("branch_slower_front",
      "                            else\n                                push_back(&q, &branch);",
      "                            else\n                                push_front(&q, &branch);"),
    P("push_front_wrap",
      "    q->Front = q->Front == 0 ? ROUTEPLAN_RING - 1 : q->Front - 1;",
      "    q->Front = q->Front == 0 ? ROUTEPLAN_RING - 2 : q->Front - 1;"),
    P("push_front_full",
      "    q->Full = q->Back == q->Front;\n    q->Path[q->Front] = *p;",
      "    q->Full = 0;\n    q->Path[q->Front] = *p;"),
    P("push_back_wrap", "    if (q->Back == ROUTEPLAN_RING)\n",
      "    if (q->Back == ROUTEPLAN_RING - 1)\n"),
    P("push_back_full", "        q->Back = 0;\n    q->Full = q->Back == q->Front;",
      "        q->Back = 0;\n    q->Full = 0;"),
    P("advance_back", "            if (advance)\n                cur.Point = step(cur.Route, p, fwd);",
      "            if (advance)\n                cur.Point = step(cur.Route, p, 1);"),
    P("posted", "        if (cur.Point != NULL && !trpoint_is_posted(cur.Point))\n"
      "            cur.Point = NULL;\n", ""),
    P("pop_empty_full", "            if (!q.Full && q.Front == q.Back)\n",
      "            if (q.Front == q.Back)\n"),
    P("pop_wrap", "            if (q.Front == ROUTEPLAN_RING)\n",
      "            if (q.Front == ROUTEPLAN_RING - 1)\n"),
    P("pop_full", "            q.Full = 0;\n            if (++paths", "            if (++paths"),
    P("paths_gt", "            if (++paths >= ROUTEPLAN_MAX_PATHS)\n",
      "            if (++paths > ROUTEPLAN_MAX_PATHS)\n"),
    P("paths_found", "            if (++paths >= ROUTEPLAN_MAX_PATHS)\n                return 0;",
      "            if (++paths >= ROUTEPLAN_MAX_PATHS)\n                return found;"),
    P("steps_ge", "        if (++steps > ROUTEPLAN_MAX_STEPS)\n",
      "        if (++steps >= ROUTEPLAN_MAX_STEPS)\n"),
    P("steps_from", "    int32_t  steps = 1;\n", "    int32_t  steps = 0;\n"),
    P("steps_found", "        if (++steps > ROUTEPLAN_MAX_STEPS)\n            return 0;",
      "        if (++steps > ROUTEPLAN_MAX_STEPS)\n            return found;"),
    P("step_back_zero", "        if (i == 0)\n            return NULL;\n        i--;",
      "        i--;\n        if (i == 0)\n            return NULL;"),
    P("step_fwd_le", "        if (!(i < r->NumPoints))\n",
      "        if (!(i <= r->NumPoints))\n"),
    A("ring", "#define ROUTEPLAN_RING           20",
      "#define ROUTEPLAN_RING           19"),
    A("max_paths", "#define ROUTEPLAN_MAX_PATHS      71",
      "#define ROUTEPLAN_MAX_PATHS      72"),
    A("max_steps", "#define ROUTEPLAN_MAX_STEPS      0x11800",
      "#define ROUTEPLAN_MAX_STEPS      0x117ff"),
]

EQUIVALENT = {
    "good_swap":
        "CompareDistances(b, a) is -CompareDistances(a, b) exactly, the "
        "wrap at half the track included, and the start line test takes "
        "its fabs",
    "branch_way_full":
        "Full is only ever set by a push, and a pop always comes between "
        "a branch's pushes and the next branch: it is 0 when the way on "
        "is pushed",
}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    base = model_cached(sc)
    opsdir = tempfile.TemporaryDirectory()
    ops = Path(opsdir.name) / "ops.bin"
    ops.write_bytes(sc.encode())
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, ops, out)
        took = time.monotonic() - t0
        got = out.read_text().splitlines()
        if diff(base, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "traffictele_test",
        lambda exe, out: mutpar.run_exe([exe, ops], out, limit),
        base, diff, EQUIVALENT, jobs)
    opsdir.cleanup()
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
        ops = Path(tmp) / "ops.bin"
        ops.write_bytes(sc.encode())
        exe = build_harness(tmp)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, ops, out)
        harness = out.read_text().splitlines()

    if args.dump:
        Path(args.dump + ".model.txt").write_text(NL.join(lines) + NL)
        Path(args.dump + ".harness.txt").write_text(NL.join(harness) + NL)

    bad = diff(lines, harness)
    print("%d ops, %d lines, %d differ"
          % (len(sc.ops), len(harness), bad))
    sys.exit(1 if (bad or rc) else 0)


if __name__ == "__main__":
    main()
