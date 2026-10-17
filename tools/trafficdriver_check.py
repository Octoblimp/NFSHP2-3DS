"""Cross-check 3DS Files/source/trafficdriver.c against the retail image's
own code.

TrafficDriver is the controller of a traffic car: retail's
TrafficDriver.obj, 0x0018c380 to 0x0018d070. The oracle is SLES_507.31
itself, run in tools/mipsemu.py:

- the constructor (0x0018c380), and through _vt$13TrafficDriver
  (0x002b4730) the destructor (0x0018c418), Think (0x0018c4d8),
  JustReset (0x0018cb10) and GetRouteNumbersToUse (0x0018cae8);
  ExecuteCurrentAction (0x0018cb98), CalculateDesiredSpeed (0x0018cc78)
  and SetDirection (0x0018d030) called directly;
- run as shipped under them: Car::PrintAbove (0x0018d078, empty),
  DrivingChoiceTypeIsDrivingLine (0x0018d038), DrivingChoice::Clear
  (0x00130920) and ~DrivingChoice (0x00130930), DrivingLocation's IsClear
  (0x00239c80), SetRoute (0x00239bb0), SetDrivingLine (0x00239bd0) and
  SetRelaxedSwitch (0x00239be0), TrackRoutePoint::GetSignpost
  (0x001c14f8), Signpost's GetNewRoute (0x001c0ff8) and GetNewRoutePoint
  (0x001c1020), AICarController::GetMyDriverNumber (0x001908f0) and
  bNormalize(bVector2 *, const bVector2 *) (0x002588a0).

Stood in on both sides, each call printing a line, so both must ask the
same questions in the same order:
  AICarController's constructor (0x00190140), which sets the car and
    AICarController's vptr and nothing else, and its destructor
    (0x001903a0); DoStickyDecisions (0x00191b30), ClearStickyDecisions
    (0x00191d10), GetCurrentTrackRoutePoint (0x001921f8, which leaves the
    current location alone, clears its route or puts it on a route, as
    the script says) and MaybeHonkAndOrBlinkHeadlights (0x00192fa8);
  PsychoDriver's constructor (0x00139760), which gives the driver a test
    table (FDVT) whose destructor (8), SetDesiredSpeed (56) and SetTarget
    (64) print;
  NearbyCarList::BuildArray (0x00193898), Car::SetMovementMode
    (0x00131618, which also stores the mode), DrivingChoice::
    GetDrivingLine (0x00241c20, answering the script's line),
    HighlightDrivingLine (0x001cb450), DriveTargetRenderer::
    SetTargetToRender (0x001cb600), AIAction::UpdateStatus (0x001c6a98,
    setting the script's Status and CanExpire) and ClearPointsToDrive
    (0x001caa60);
  bMalloc (0x002577c0) and the frees (bFree 0x00257850, __builtin_delete
    0x00114e98): a block filled with 0xcd, named h0, h1, ... (the port's
    PsychoDriver prints as the console's 624);
  bOMalloc (0x00257c80), the port's aiaction_new: answering a0, a1, ...;
  the six CalculateScores the cascade asks (GetUnstuck 0x001c8c30,
    AccidentRecovery 0x001ca2a8, IJustGotHit 0x001c9d20, AvoidCars
    0x001c6cf8, PullOver 0x001c8400, JustDrive 0x001c7458): each prints
    what its out parameters hold on the way in, writes the script's
    answers into those the script's mask names, and answers the script's
    score;
  the six actions' constructors (JustDrive 0x001c73c0, PullOver
    0x001c8298, GetUnstuck 0x001c8b30, AccidentRecovery 0x001ca1f0,
    IJustGotHit 0x001c9c68, AvoidCars 0x001c6ba0): each prints its
    arguments and gives the action a test table (FAVT) whose destructor
    (8) and CalculatePointsToDrive (24) print, the latter filling the
    action's points and speeds from the script, and a Score of its
    argument plus the script's bias.

aiplan_time_to_change, DrivingChoice::Clear and GetMyDriverNumber are the
harness's copies of aiaction.c's, drivingchoice.c's and
aicarcontroller.c's (which their checkers check), as those need most of
the AI to link.

The record is dumped by field; the table slot by slot as retail's
addresses; and the globals the image keeps by value.

    python tools/trafficdriver_check.py
    python tools/trafficdriver_check.py --mutate [--only a,b] [--jobs N]
    python tools/trafficdriver_check.py --dump PREFIX
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
from mipsemu import M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/trafficdriver_test.c"
TDC = "3DS Files/source/trafficdriver.c"
SOURCES = [HARNESS, TDC,
           "3DS Files/source/drivinglocation.c",
           "3DS Files/source/race.c",
           "3DS Files/source/trackroute.c",
           "3DS Files/source/trackpath.c",
           "3DS Files/source/replay.c", "3DS Files/source/p32.c",
           "3DS Files/source/quickspline.c",
           "3DS Files/source/bmem.c",
           "3DS Files/source/bmatrix.c",
           "3DS Files/source/bvector.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c",
           "3DS Files/source/bchunk.c",
           "3DS Files/source/vtable.c"]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = retail_model.RETAIL_GP

CTOR = 0x0018c380
DTOR = 0x0018c418
EXEC = 0x0018cb98
SPEED = 0x0018cc78
SET_DIRECTION = 0x0018d030
TRAFFICDRIVER_VT = 0x002b4730

AICC_CTOR = 0x00190140
AICC_DTOR = 0x001903a0
AICC_VT = 0x002b4d90
STICKY = 0x00191b30
CLEAR_STICKY = 0x00191d10
GCTRP = 0x001921f8
MAYBE_HONK = 0x00192fa8
PSYCHO_CTOR = 0x00139760
BUILD_ARRAY = 0x00193898
SET_MOVEMENT_MODE = 0x00131618
GET_DRIVING_LINE = 0x00241c20
HIGHLIGHT = 0x001cb450
SET_TARGET_TO_RENDER = 0x001cb600
UPDATE_STATUS = 0x001c6a98
CLEAR_POINTS = 0x001caa60
BMALLOC = 0x002577c0
BOMALLOC = 0x00257c80
BFREE = 0x00257850
BDELETE = 0x00114e98

RENDERER = 0x00314630               # TheDriveTargetRenderer
ROUTE_MANAGER = 0x00314438          # TheTrackRouteManager; pTrackRoutes at 16

# The CalculateScores, in the cascade's order, and the constructors.
SCORES = (("unstuck", 0x001c8c30), ("recovery", 0x001ca2a8),
          ("hit", 0x001c9d20), ("avoid", 0x001c6cf8),
          ("pullover", 0x001c8400), ("drive", 0x001c7458))
NEWS = (("drive", 0x001c73c0), ("pullover", 0x001c8298),
        ("unstuck", 0x001c8b30), ("recovery", 0x001ca1f0),
        ("hit", 0x001c9c68), ("avoid", 0x001c6ba0))
S_UNSTUCK, S_RECOVERY, S_HIT, S_AVOID, S_PULLOVER, S_DRIVE = range(6)

WORLD_TIMER_GP = -19576
LOOP_COUNTER_GP = -19552
CURRENT_WORLD_GP = -22120
SLOT_POOL_GP = -18288
SIGNPOSTS_GP = -18376
LOOK_AHEAD_GP = -20328
CAM_DEFAULT_GP = -21532
CAM_CAR_GP = -21528
# OP_GLOBAL's: JustDrive, AvoidCars, IJustGotHit, GetUnstuck and
# AccidentRecovery's scores, PullOver's; GetUnstuck's, AvoidCars' and
# IJustGotHit's lifetimes; PullOverTrafficCarTimeout.
GLOBAL_GPS = (-18272, -18252, -18248, -18244, -18240, -18236,
              -18208, -18200, -18196, -18160)
(G_JD, G_AVOID, G_HIT, G_UNSTUCK, G_RECOVERY, G_PULLOVER, G_L_UNSTUCK,
 G_L_AVOID, G_L_HIT, G_T_TRAFFIC) = range(10)
FLOAT_GLOBALS = (G_L_UNSTUCK, G_L_AVOID, G_L_HIT, G_T_TRAFFIC)

# The world: retail's offsets.
D = 0x01E00000                      # the TrafficDriver, 736 bytes
D_SIZE = 736
CAR = 0x01E01000                    # CarIndex 8, DriverNumber 10,
                                    # MyDriver 20, TheMovementMode 36
DRV = 0x01E02000                    # TheDriverType 8
WORLD = 0x01E02200                  # TotalNumCars 28, TrafficCarPos 40,
                                    # CarTable 44
LIST = 0x01E02300
LOC = 0x01E02400
CHOICE = 0x01E02480
CUR = 0x01E02500                    # an action, 608 bytes
CARS = 0x01E03000                   # c0..c7, 0x100 apart
NCARS = 8
POOL = 0x01E04000
SCR = 0x01E09000
FDVT = 0x01E0A000                   # the test driver table
FDVT_DTOR, FDVT_SPEED, FDVT_TARGET = FDVT + 0x800, FDVT + 0x810, FDVT + 0x820
FAVT = 0x01E0B000                   # the test action table
FAVT_DTOR, FAVT_POINTS = FAVT + 0x800, FAVT + 0x810
SIGNS = 0x01E0C000                  # 256 Signposts, 12 bytes each
NSIGNS = 256
SLOTS = 0x01E10000                  # a0, a1, ..., 0x300 apart
SLOT_SPAN = 0x300
NSLOTS = 64
ROUTES = 0x01E20000                 # r0..r3, 0x20000 apart
ROUTE_SPAN = 0x20000
NROUTES = 4
SLACK = 16

ACTION_SIZE = 608
ROUTE_SIZE = 115752
POINT_SIZE = 112
POINT_TABLE = 1064
NPTS = 20

INFO = D + 12
MYLOC = D + 476
OFF_CAR, OFF_DRIVER, OFF_VT = 0, 4, 8
OFF_CHOICE = 492
OFF_LOC, OFF_CURCHOICE, OFF_LIST = 504, 508, 512
OFF_SECS, OFF_FORCE, OFF_ACTION, OFF_LAST = 524, 528, 532, 544
OFF_PICK = 720
DRIVER_VT_OFF = 556

(OP_TAG, OP_JUNK, OP_NEW, OP_DEL, OP_NULL, OP_RAWDEL, OP_THINK, OP_ROUTES,
 OP_RESET, OP_EXEC, OP_SPEED, OP_DIR, OP_SET, OP_CUR, OP_POKE, OP_GLOBAL,
 OP_PT, OP_FILL, OP_ROUTE, OP_RPOINT, OP_SIGN, OP_LOC, OP_WORLD, OP_TABLE,
 OP_DUMP, OP_STATIC) = range(26)

ARGS = {OP_TAG: 1, OP_JUNK: 1, OP_NEW: 0, OP_DEL: 1, OP_NULL: 0,
        OP_RAWDEL: 1, OP_THINK: 1, OP_ROUTES: 0, OP_RESET: 0, OP_EXEC: 0,
        OP_SPEED: 0, OP_DIR: 1, OP_SET: 2, OP_CUR: 1, OP_POKE: 2,
        OP_GLOBAL: 2, OP_PT: 3, OP_FILL: 0, OP_ROUTE: 3, OP_RPOINT: 4,
        OP_SIGN: 3, OP_LOC: 5, OP_WORLD: 2, OP_TABLE: 2, OP_DUMP: 0,
        OP_STATIC: 0}

# OP_SET's keys: what the stand-ins answer. K_SCORE + i is the i'th
# CalculateScore's score.
(K_MASK, K_HIT, K_AVOIDCAR, K_SECS, K_OKAY, K_USED, K_ACH_TYPE, K_ACH_CAR,
 K_ACH_EXTRA, K_STATUS, K_CANEXPIRE, K_BIAS, K_GCTRP, K_LINE, K_NPTS,
 K_DSPEED, K_DTIME, K_DTOL, K_USEDLS, K_ALLOWED) = range(20)
K_SCORE = 20
K_COUNT = K_SCORE + 6
FLOAT_KEYS = (K_SECS, K_DSPEED, K_DTIME, K_DTOL)

# K_MASK's bits: which outs the CalculateScores write.
W_HIT, W_AVOIDCAR, W_SECS, W_OKAY, W_USED, W_ACH = (1 << k for k in range(6))
W_ALL = (1 << 6) - 1

# OP_POKE's fields.
(P_TIMER, P_LOOP, P_LAST, P_SECS, P_PICK, P_DTYPE, P_CARIDX, P_DRVNUM,
 P_MODE, P_LOCSEL, P_LIST, P_CHOICE_TYPE, P_CAMCAR, P_CAMDEF, P_LOOKAHEAD,
 P_FORCE, P_CUR_TYPE, P_CUR_SCORE, P_CUR_STATUS, P_CUR_CANEXP) = range(20)
FLOAT_POKES = (P_SECS, P_LOOKAHEAD)

# A car argument: -1 none, 0..7 cN, 8 my own car.
NO_CAR, MY_CAR = -1, NCARS

# K_GCTRP: -2 leaves the location alone, -1 clears its route.
GC_LEAVE, GC_CLEAR = -2, -1

TRAFFIC_CAR = 3                     # DRIVER_TYPE_TRAFFIC_CAR
TRAFFIC_MOVEMENT = 2

TICK = 0.000250000012


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


def first_ticks_over(limit, inclusive):
    """The fewest ticks whose seconds reach `limit` (`<=`) or pass it."""
    n = int(limit / TICK) - 4
    while not (limit <= secs_of(n) if inclusive else limit < secs_of(n)):
        n += 1
    return n


UNSTUCK_TICKS = first_ticks_over(2.0, False)        # 8001


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

    def set(self, key, v):
        if key in FLOAT_KEYS and not isinstance(v, Fb):
            v = float(v)
        self.op(OP_SET, key, v)

    def poke(self, f, v):
        if f in FLOAT_POKES and not isinstance(v, Fb):
            v = float(v)
        self.op(OP_POKE, f, v)

    def glob(self, i, v):
        if i in FLOAT_GLOBALS and not isinstance(v, Fb):
            v = float(v)
        self.op(OP_GLOBAL, i, v)

    def scores(self, *vals):
        assert len(vals) == 6
        for i, v in enumerate(vals):
            self.set(K_SCORE + i, v)

    def fresh(self, junk=0xa5):
        self.op(OP_JUNK, junk)
        self.op(OP_NEW)


# ============================================================== the script

# The image's globals, as the cascade's gates read them.
GATES = ((S_UNSTUCK, G_UNSTUCK, 500), (S_RECOVERY, G_RECOVERY, 500),
         (S_HIT, G_HIT, 400), (S_AVOID, G_AVOID, 400),
         (S_PULLOVER, G_PULLOVER, 600), (S_DRIVE, G_JD, 150))

ROUTE_NUMBERS = (50, 57, 60, 59)
ROUTE_POINTS = 64

# The signs the hairpin scenarios use: (flags, new route, new point). 10's
# route is not loaded; 255 is a hairpin no point names, as 255 is no sign.
SIGN_DEFS = {1: (0x20, 2, 7), 2: (0x28, 2, 7), 3: (0x01, 2, 7),
             4: (0x27, 3, 12), 5: (0x60, 3, 0), 6: (0x20, 0, 63),
             7: (0x2f, 1, 5), 8: (0x22, 3, 40), 9: (0xdf, 2, 1),
             10: (0x20, 5, 3), 200: (0x20, 1, 2), 255: (0x20, 1, 2)}


class Routes(object):
    """The routes' points as the script has left them: each op only
    writes what changes."""

    def __init__(self, sc):
        self.sc = sc
        self.pts = {}
        for k in range(NROUTES):
            sc.op(OP_ROUTE, k, ROUTE_POINTS, ROUTE_NUMBERS[k])
            for i in range(ROUTE_POINTS):
                self.point(k, i, 5.0, 0xff)

    def point(self, k, i, length, sign):
        v = (fb(f32(length)), sign & 0xff)
        if self.pts.get((k, i)) != v:
            self.pts[(k, i)] = v
            self.sc.op(OP_RPOINT, k, i, Fb(v[0]), v[1])

    def reset(self, k):
        for i in range(ROUTE_POINTS):
            self.point(k, i, 5.0, 0xff)


def ready(sc, junk=0xa5, dtype=0, locsel=0):
    """A driver that thinks on the next THINK of a positive dt, on route
    0's point 3 (line 5)."""
    sc.fresh(junk)
    sc.poke(P_DTYPE, dtype)
    sc.poke(P_LOCSEL, locsel)
    sc.poke(P_LIST, 1)
    sc.op(OP_LOC, 0, 0, 3, 5, 0)
    sc.op(OP_LOC, 1, 1, 9, 5, 0)
    sc.poke(P_SECS, 0.0)
    sc.poke(P_LAST, 0)
    sc.poke(P_CHOICE_TYPE, 0)


def with_cur(sc, score, status=0, canexp=0, typ=6):
    sc.op(OP_CUR, 1)
    sc.poke(P_CUR_SCORE, score)
    sc.poke(P_CUR_TYPE, typ)
    sc.set(K_STATUS, status)
    sc.set(K_CANEXPIRE, canexp)


def defaults(sc):
    sc.set(K_MASK, 0)
    sc.set(K_BIAS, 0)
    sc.set(K_GCTRP, GC_LEAVE)
    sc.set(K_LINE, 5)
    sc.set(K_STATUS, 0)
    sc.set(K_CANEXPIRE, 0)
    sc.scores(-1, -1, -1, -1, -1, -1)
    sc.poke(P_TIMER, 100000)
    sc.poke(P_MODE, 0)


def bend_points(n, theta, d1=10.0, d2=10.0, ox=0.0, oy=0.0, rot=0.0):
    """n points: the first half along `rot`, the rest turned by theta."""
    m = n // 2
    pts = []
    for i in range(NPTS):
        if i <= m:
            t = d1 * i / max(m, 1)
            x, y = t * math.cos(rot), t * math.sin(rot)
        else:
            px, py = d1 * math.cos(rot), d1 * math.sin(rot)
            t = d2 * (i - m) / max(n - 1 - m, 1)
            x = px + t * math.cos(rot + theta)
            y = py + t * math.sin(rot + theta)
        pts.append((f32(ox + x), f32(oy + y)))
    return pts


def put_points(sc, pts):
    for i, (x, y) in enumerate(pts):
        sc.op(OP_PT, i, x, y)


def script():
    sc = Script()
    rnd = random.Random(0x7d)

    sc.tag("static")
    sc.op(OP_STATIC)

    sc.tag("routes and signs")
    routes = Routes(sc)
    for i, (flags, nr, np_) in sorted(SIGN_DEFS.items()):
        sc.op(OP_SIGN, i, flags, nr | (np_ << 8))
    sc.glob(G_JD, 150)
    defaults(sc)

    # -- the constructor and the destructor -----------------------------------
    for flags in (0, 1, 2, 3):
        sc.tag("new, del %d" % flags)
        sc.fresh(0xa5 if flags != 2 else 0x00)
        sc.op(OP_DUMP)
        sc.op(OP_DEL, flags)
        sc.op(OP_DUMP)

    sc.tag("new, car indices")
    for idx in (0, 1, 2, 7, 13, 14, 69, 100, -1, -7, 255, 32767, -32768):
        sc.op(OP_JUNK, 0x3c)
        sc.poke(P_CARIDX, idx)
        sc.op(OP_NEW)
        sc.op(OP_DUMP)
    sc.poke(P_CARIDX, 0)

    sc.tag("del with no driver")
    sc.fresh(0x5c)
    sc.op(OP_NULL)
    sc.op(OP_DEL, 1)
    sc.op(OP_DUMP)

    # Called directly, with AICarController's vptr: the destructor's own.
    sc.tag("del with another vptr")
    for flags in (1, 0):
        sc.fresh()
        sc.op(OP_RAWDEL, flags)
        sc.op(OP_DUMP)

    sc.tag("routes")
    for pick in (1, 0, 2, -1, 0x80000000, 0x100):
        sc.fresh()
        sc.poke(P_PICK, pick)
        sc.op(OP_ROUTES)
    sc.tag("set direction")
    for v in (0, 1, 5, -1, 0x80000000, 0):
        sc.op(OP_DIR, v)
        sc.op(OP_ROUTES)
        sc.op(OP_DUMP)

    # -- Think: whose turn ------------------------------------------------------
    # The route cleared after the stand-in's GetCurrentTrackRoutePoint, so
    # a think stops there.
    sc.set(K_GCTRP, GC_CLEAR)
    sc.tag("think, another driver's clock")
    for dtype in (0, 1, 2, 4, -1, 0x103):
        for secs, dt in ((0.0, 0.1), (0.2, 0.2), (0.2, nextup(0.2, -1)),
                         (0.2, nextup(0.2)), (-0.0, 0.0), (0.0, 0.0),
                         (0.0, -0.0), (1e-30, 1e-30), (nextup(0.0), 0.0),
                         (-5.0, -1.0), (5.0, 4.0), (5.0, 6.0),
                         (nextup(-0.0), -0.0), (0.3, 0.1)):
            ready(sc, dtype=dtype)
            sc.poke(P_SECS, secs)
            sc.op(OP_THINK, f32(dt))
            sc.op(OP_DUMP)

    sc.tag("think, the clock run down")
    ready(sc)
    sc.poke(P_SECS, 0.7)
    for _ in range(12):
        sc.op(OP_THINK, f32(1.0 / 30.0))
        sc.op(OP_DUMP)

    sc.tag("think, the stagger")
    for idx in (0, 1, 2, 5, 13):
        sc.op(OP_JUNK, 0xa5)
        sc.poke(P_CARIDX, idx)
        sc.op(OP_NEW)
        sc.poke(P_DTYPE, 0)
        sc.poke(P_LOCSEL, 0)
        sc.poke(P_LIST, 1)
        for _ in range(4):
            sc.op(OP_THINK, f32(-0.01))
            sc.op(OP_DUMP)
    sc.poke(P_CARIDX, 0)

    # A traffic car: the odd frames of twelve, the half its place among
    # the traffic in the world's table. A negative counter's remainder is
    # negative, so the table's traffic starts at 6 for those.
    sc.tag("think, traffic turns")
    configs = ((14, 6, 6), (14, 6, 7), (14, 6, 8), (14, 6, 11), (14, 6, 0),
               (14, 6, 3), (14, 6, 5), (10, 6, 9), (10, 6, 10), (8, 6, 7),
               (6, 6, 6), (13, 13, 13), (13, 8, 12), (13, 8, 13),
               (12, 7, 11), (12, 7, 12), (9, 9, 9), (14, 13, 13))
    counters = list(range(-30, 31)) + [0x7fffffff, 0x80000000, 0x80000001,
                                       0x7ffffff3, 0xfffffff3, 12 * 1000 + 7,
                                       -12 * 1000 - 7, 0x40000001]
    for total, pos, slot in configs:
        sc.op(OP_WORLD, total, pos)
        for i in range(14):
            sc.op(OP_TABLE, i, MY_CAR if i == slot else i % NCARS)
        ready(sc, dtype=TRAFFIC_CAR)
        for cnt in counters:
            sc.poke(P_LOOP, cnt)
            sc.op(OP_THINK, f32(0.05))
        sc.op(OP_DUMP)
    sc.tag("think, traffic, the clock unread")
    sc.op(OP_WORLD, 14, 6)
    for i in range(14):
        sc.op(OP_TABLE, i, MY_CAR if i == 8 else NO_CAR)
    for secs in (5.0, -5.0, 0.0):
        ready(sc, dtype=TRAFFIC_CAR)
        sc.poke(P_SECS, secs)
        for cnt in (5, 4, 6, 3):
            sc.poke(P_LOOP, cnt)
            sc.op(OP_THINK, f32(0.25))
            sc.op(OP_DUMP)
    sc.poke(P_LOOP, 0)
    sc.op(OP_WORLD, 0, 0)

    # -- Think: the location ----------------------------------------------------
    sc.tag("think, the look-ahead and the location")
    for look in (2.0, 3.5, -1.0, 0.0):
        for locsel in (0, 1):
            ready(sc, locsel=locsel)
            sc.poke(P_LOOKAHEAD, look)
            sc.op(OP_THINK, f32(0.1))
            sc.op(OP_DUMP)
    sc.poke(P_LOOKAHEAD, 2.0)

    sc.tag("think, PrintAbove's test")
    sc.set(K_GCTRP, GC_CLEAR)
    for camdef in (1, 0, -1):
        for drvnum, camcar in ((3, 3), (3, -1), (-1, -1), (0, 7)):
            ready(sc)
            sc.poke(P_CAMDEF, camdef)
            sc.poke(P_DRVNUM, drvnum)
            sc.poke(P_CAMCAR, camcar)
            sc.op(OP_THINK, f32(0.1))
            sc.op(OP_DUMP)
    sc.poke(P_CAMDEF, 1)
    sc.poke(P_CAMCAR, -1)
    sc.poke(P_DRVNUM, 0)

    sc.tag("think, a route found")
    for gc, locsel in ((0, 0), (2, 1), (3, 0), (GC_LEAVE, 0)):
        ready(sc, locsel=locsel)
        if gc != GC_LEAVE:
            sc.op(OP_LOC, locsel, -1, 0, 5, 0)
        sc.set(K_GCTRP, gc)
        sc.op(OP_THINK, f32(0.1))
        sc.op(OP_DUMP)
    sc.set(K_GCTRP, GC_LEAVE)

    # -- Think: no action -------------------------------------------------------
    sc.tag("think, no action")
    for jd in (150, 0, -5, 700):
        ready(sc)
        sc.glob(G_JD, jd)
        sc.op(OP_THINK, f32(0.1))
        sc.op(OP_DUMP)
    sc.glob(G_JD, 150)

    # -- Think: the cascade -----------------------------------------------------
    sc.tag("cascade, statuses")
    for status in (-1, 0, 1, 2, 3, 4, 5):
        for canexp in (0, 1, 7, -1):
            ready(sc)
            with_cur(sc, 450, status, canexp)
            sc.scores(0, 0, 0, 0, 0, 0)
            sc.op(OP_THINK, f32(0.1))
            sc.op(OP_DUMP)

    # Each gate with the current score a point either side of its global,
    # and its own score a point either side of that.
    sc.tag("cascade, the gates")
    for i, g, gv in GATES:
        for cur in (gv - 1, gv, gv + 1):
            for d in (-1, 0, 1):
                ready(sc)
                with_cur(sc, cur)
                sc.scores(*[cur + d if k == i else -1 for k in range(6)])
                sc.op(OP_THINK, f32(0.1))
                sc.op(OP_DUMP)

    sc.tag("cascade, the gates moved")
    for i, g, gv in GATES:
        for nv in (gv - 100, gv + 100, 0, -1):
            sc.glob(g, nv)
            ready(sc)
            with_cur(sc, gv - 50)
            sc.scores(*[gv if k == i else -1 for k in range(6)])
            sc.op(OP_THINK, f32(0.1))
            sc.op(OP_DUMP)
        sc.glob(g, gv)

    sc.tag("cascade, the order")
    for bias in (-2000, -600, -101, -100, -1, 0, 1, 100, 450):
        for cur in (None, 0, 399, 650):
            ready(sc)
            if cur is None:
                with_cur(sc, 0, 3, 1)
            else:
                with_cur(sc, cur)
            sc.set(K_BIAS, bias)
            sc.scores(450, 450, 450, 450, 450, 450)
            sc.op(OP_THINK, f32(0.1))
            sc.op(OP_DUMP)
    sc.set(K_BIAS, 0)
    # Each step's score is the best the gates after it see.
    for sv in ((501, 502, 503, 504, 605, 606), (10, 20, 30, 40, 50, 60),
               (-1, 499, -1, 399, 599, 149), (499, -1, 399, -1, -1, 149),
               (0, -1, -1, -1, -1, -1), (-1, -1, -1, -1, -1, 0),
               (300, -1, -1, -1, -1, 400), (-1, 300, -1, -1, -1, 400),
               (-1, -1, 300, -1, -1, 400), (-1, -1, -1, 300, -1, 400),
               (-1, -1, -1, -1, 300, 400), (450, -1, 420, 430, -1, -1),
               (-1, 450, -1, 430, 550, -1)):
        for cur in (None, 0, 100):
            ready(sc)
            with_cur(sc, 0 if cur is None else cur, 1 if cur is None else 0)
            sc.scores(*sv)
            sc.op(OP_THINK, f32(0.1))
            sc.op(OP_DUMP)

    # GetUnstuck waits two seconds since the last.
    sc.tag("cascade, GetUnstuck's two seconds")
    for timer, last in ((UNSTUCK_TICKS - 1, 0), (UNSTUCK_TICKS, 0),
                        (UNSTUCK_TICKS + 1, 0), (UNSTUCK_TICKS - 2, 0),
                        (0, 0), (-1, 0), (0, UNSTUCK_TICKS),
                        (0x80000000 + UNSTUCK_TICKS, 0x80000000),
                        (0x80000000 + UNSTUCK_TICKS - 1, 0x80000000),
                        (UNSTUCK_TICKS - 2, 0xffffffff),
                        (UNSTUCK_TICKS - 1, 0xffffffff),
                        (0x7fffffff, 0), (0x7fffffff, 0xffffffff),
                        (0x80000000, 0), (0, 0x80000001),
                        (100000, 100000 - UNSTUCK_TICKS)):
        ready(sc)
        with_cur(sc, 0)
        sc.poke(P_TIMER, timer)
        sc.poke(P_LAST, last)
        sc.scores(10, -1, -1, -1, -1, -1)
        sc.op(OP_THINK, f32(0.1))
        sc.op(OP_DUMP)
    sc.poke(P_TIMER, 100000)
    sc.tag("cascade, GetUnstuck's stamp")
    ready(sc)
    with_cur(sc, 0)
    sc.scores(10, -1, -1, -1, -1, -1)
    for t in (100000, 100001, 104000, 108000, 108001, 108002, 116003):
        sc.poke(P_TIMER, t)
        sc.poke(P_SECS, 0.0)
        sc.op(OP_THINK, f32(0.1))
        sc.op(OP_DUMP)
    sc.poke(P_TIMER, 100000)

    sc.tag("cascade, the lifetimes and timeout")
    for li in (0.0, 5.0, -3.0, 0.25):
        sc.glob(G_L_UNSTUCK, li)
        sc.glob(G_L_AVOID, f32(li + 1.0))
        sc.glob(G_L_HIT, f32(li - 1.0))
        sc.glob(G_T_TRAFFIC, f32(li * 7.0))
        for i in (S_UNSTUCK, S_HIT, S_AVOID, S_PULLOVER):
            ready(sc)
            with_cur(sc, 0)
            sc.scores(*[10 if k == i else -1 for k in range(6)])
            sc.op(OP_THINK, f32(0.1))
            sc.op(OP_DUMP)
    sc.glob(G_L_UNSTUCK, 5.0)
    sc.glob(G_L_AVOID, 0.0)
    sc.glob(G_L_HIT, 0.0)
    sc.glob(G_T_TRAFFIC, -999.0)

    # IJustGotHit's car.
    sc.tag("cascade, IJustGotHit")
    for mask in (0, W_HIT, W_ALL):
        for car in (NO_CAR, 0, 3, MY_CAR):
            ready(sc)
            with_cur(sc, 0)
            sc.set(K_MASK, mask)
            sc.set(K_HIT, car)
            sc.set(K_AVOIDCAR, 5)
            sc.scores(-1, -1, 10, 20, -1, -1)
            sc.op(OP_THINK, f32(0.1))
            sc.op(OP_DUMP)

    # AvoidCars' outs, and `okay` through the unsigned conversion.
    sc.tag("cascade, AvoidCars")
    for okay in (0, 1, -1, 2, 3, 0x7fffffff, 0x80000000, 0x80000001,
                 0xffffffff, 0x00ffffff, 0x01000001, 0x01000003, 0x40000041,
                 0xc0000041, 0xfffffffe, 0x8000007f, 0x80000080, 0x80000081,
                 0x800000c1):
        ready(sc)
        with_cur(sc, 0)
        sc.set(K_MASK, W_OKAY)
        sc.set(K_OKAY, okay)
        sc.scores(-1, -1, -1, 10, -1, -1)
        sc.op(OP_THINK, f32(0.1))
        sc.op(OP_DUMP)
    for mask in (0, W_AVOIDCAR, W_SECS, W_USED, W_ACH, W_ALL,
                 W_AVOIDCAR | W_ACH, W_HIT | W_SECS):
        for used in (0, 1, -3):
            ready(sc)
            with_cur(sc, 0)
            sc.set(K_MASK, mask)
            sc.set(K_AVOIDCAR, 2)
            sc.set(K_HIT, 6)
            sc.set(K_SECS, 1.75)
            sc.set(K_OKAY, 0)
            sc.set(K_USED, used)
            sc.set(K_ACH_TYPE, 3)
            sc.set(K_ACH_CAR, 4)
            sc.set(K_ACH_EXTRA, 1)
            sc.scores(-1, -1, 7, 10, -1, -1)
            sc.op(OP_THINK, f32(0.1))
            sc.op(OP_DUMP)
    sc.set(K_MASK, 0)

    # Off the belt: AvoidCars and PullOver put a car on its traffic belt
    # onto the mellow mover.
    sc.tag("cascade, off the belt")
    for mode in (0, 1, 2, 3, 4, -1, 0x102):
        for sv in ((-1, -1, -1, 10, -1, -1), (-1, -1, -1, -1, 10, -1),
                   (-1, -1, -1, 10, 20, -1), (-1, -1, -1, -1, -1, 10)):
            ready(sc)
            with_cur(sc, 0)
            sc.poke(P_MODE, mode)
            sc.scores(*sv)
            sc.op(OP_THINK, f32(0.1))
            sc.op(OP_DUMP)
    sc.poke(P_MODE, 0)

    sc.tag("cascade, PullOver's list and location")
    for locsel in (0, 1):
        for lst in (0, 1):
            ready(sc, locsel=locsel)
            sc.poke(P_LIST, lst)
            with_cur(sc, 0)
            sc.scores(-1, -1, -1, -1, 10, -1)
            sc.op(OP_THINK, f32(0.1))
            sc.op(OP_DUMP)

    # -- Think: the driving line ------------------------------------------------
    sc.tag("think, the driving line")
    sc.poke(P_TIMER, 77777)
    for typ in (-1, 0, 1, 2, 3, 4, 5, 6, 0x80000001):
        for line in (5, 6, -1):
            for locsel in (0, 1):
                ready(sc, locsel=locsel)
                sc.op(OP_LOC, locsel, locsel, 3, 5, 0x1234)
                sc.op(OP_LOC, 1 - locsel, 2, 4, 9, 0x4321)
                sc.poke(P_DRVNUM, 3)
                sc.poke(P_CHOICE_TYPE, typ)
                sc.set(K_LINE, line)
                if typ == 2:
                    with_cur(sc, 0)
                sc.op(OP_THINK, f32(0.1))
                sc.op(OP_DUMP)
    sc.set(K_LINE, 5)
    sc.poke(P_DRVNUM, 0)
    sc.poke(P_CHOICE_TYPE, 0)
    sc.poke(P_TIMER, 100000)

    # -- ExecuteCurrentAction ---------------------------------------------------
    sc.tag("execute, the camera")
    for drvnum, camcar in ((3, 3), (3, -1), (-1, -1), (0, 0), (-32768, -32768),
                           (7, 6)):
        ready(sc)
        with_cur(sc, 0)
        sc.poke(P_DRVNUM, drvnum)
        sc.poke(P_CAMCAR, camcar)
        sc.op(OP_EXEC)
        sc.op(OP_DUMP)
    sc.poke(P_CAMCAR, -1)
    sc.poke(P_DRVNUM, 0)

    sc.tag("execute, the speeds")
    for allowed, dls, ds, dt_, dtol in ((0, 0, 12.5, 1.5, 0.75),
                                        (1, 0, 30.0, 0.0, 2.0),
                                        (-1, 1, 5.0, 3.0, 1.0),
                                        (7, 1, 50.0, -1.0, -2.0),
                                        (1, 2, 9.0, 0.5, 0.5),
                                        (0, 0, -4.0, 1.0, 0.0)):
        ready(sc)
        with_cur(sc, 0)
        sc.set(K_ALLOWED, allowed)
        sc.set(K_USEDLS, dls)
        sc.set(K_DSPEED, ds)
        sc.set(K_DTIME, dt_)
        sc.set(K_DTOL, dtol)
        sc.set(K_NPTS, 5)
        sc.op(OP_EXEC)
        sc.op(OP_DUMP)
    for k in (K_ALLOWED, K_USEDLS, K_NPTS):
        sc.set(k, 0)
    for k in (K_DSPEED, K_DTIME, K_DTOL):
        sc.set(k, 0.0)

    # -- CalculateDesiredSpeed: the hairpins ------------------------------------
    sc.set(K_USEDLS, 1)
    sc.set(K_DSPEED, 40.0)

    def speed(locsel, pt, numpoints, lengths=None, signs=None, route=1,
              timer=None, rn=None):
        """CalculateDesiredSpeed from point `pt` of `route`."""
        sc.op(OP_ROUTE, route, numpoints,
              ROUTE_NUMBERS[route] if rn is None else rn)
        for i in range(ROUTE_POINTS):
            ln = lengths(i) if callable(lengths) else (
                lengths if lengths is not None else 5.0)
            routes.point(route, i, ln, (signs or {}).get(i, 0xff))
        sc.fresh()
        sc.poke(P_LOCSEL, locsel)
        sc.poke(P_LIST, 1)
        sc.op(OP_LOC, 0, 0, 3, 5, 0)
        sc.op(OP_LOC, 1, 0, 3, 5, 0)
        sc.op(OP_LOC, locsel, route, pt, 5, 0x55)
        if timer is not None:
            sc.poke(P_TIMER, timer)
        with_cur(sc, 0)
        sc.op(OP_FILL)
        sc.op(OP_SPEED)
        sc.op(OP_DUMP)

    sc.tag("speed, a clear location")
    sc.fresh()
    sc.poke(P_LOCSEL, 0)
    sc.op(OP_LOC, 0, -1, 0, 5, 0)
    with_cur(sc, 0)
    for dls in (0, 1):
        sc.set(K_USEDLS, dls)
        sc.op(OP_FILL)
        sc.op(OP_SPEED)
    sc.set(K_USEDLS, 1)

    sc.tag("speed, a sign at each place")
    for sign in (1, 2, 3, 4, 5, 6, 7, 8, 9, 0, 200, 0xfe):
        for off in (0, 1, 2, 3, 14, 15, 16, 18, 19, 20):
            speed(0, 10, ROUTE_POINTS, 5.0, {10 + off: sign})
    sc.tag("speed, near and far")
    for ln in (5.0, nextup(5.0, -1), nextup(5.0), 4.0, 1.0, 0.0, -1.0,
               3.3333333, 2.5, 9.99, 10.0, 10.5, 75.0, 74.99, 80.0,
               nextup(10.0, -1)):
        for off in (0, 1, 2, 7, 14, 15, 18, 19):
            speed(0, 20, ROUTE_POINTS, ln, {20 + off: 1})
    # The sum's edges: exactly 10 m and 75 m, and a hair short.
    sc.tag("speed, the edges")
    for lens, off in (((10.0,), 1), ((nextup(10.0, -1),), 1),
                      ((4.0, 6.0), 2), ((4.0, nextup(6.0, -1)), 2),
                      ((70.0, 5.0), 2), ((70.0, nextup(5.0, -1)), 2),
                      ((70.0, nextup(5.0, -16)), 2),
                      ((70.0, 5.0, 1.0), 3), ((74.0, 1.0), 2),
                      ((74.0, nextup(1.0, -1)), 2), ((37.5, 37.5), 2),
                      ((80.0,), 1), ((75.0,), 1), ((nextup(75.0, -1),), 1),
                      ((30.0, 0.5), 2), ((30.5,), 1), ((nextup(30.5, -1),), 1),
                      ((nextup(30.5),), 1)):
        speed(0, 5, ROUTE_POINTS,
              lambda i, lens=lens: lens[i - 5] if 5 <= i < 5 + len(lens)
              else 0.5, {5 + off: 1})
    # The route's end: the scan stops at the last point.
    sc.tag("speed, the route's end")
    for numpoints in (10, 11, 12, 13, 1, 0, 9):
        for pt in (8, 9, 10, 11, 12, 0):
            speed(0, pt, numpoints, 1.0, {9: 1, 10: 1, 11: 1, 12: 1})
    # Taken within 10 m: the location goes to the sign's route, and the
    # routes it may pick follow the new route's number.
    sc.tag("speed, the take")
    for rn in (49, 50, 58, 59, 60, 61, 69, 70, -1, -32768, 32767):
        for locsel in (0, 1):
            speed(locsel, 4, ROUTE_POINTS, 3.0, {6: 1}, timer=4321)
            sc.op(OP_ROUTE, 2, ROUTE_POINTS, rn)
            speed(locsel, 4, ROUTE_POINTS, 3.0, {6: 1})
    sc.op(OP_ROUTE, 2, ROUTE_POINTS, ROUTE_NUMBERS[2])
    for sign in (4, 6, 8, 9, 10, 200):
        speed(0, 30, ROUTE_POINTS, 2.0, {31: sign})
    for locsel in (0, 1):
        speed(locsel, 4, ROUTE_POINTS, 3.0, {6: 10})
        sc.op(OP_SPEED)
        sc.op(OP_DUMP)
    # The other routes, and both locations.
    sc.tag("speed, other routes")
    for route in (0, 2, 3):
        for locsel in (0, 1):
            speed(locsel, 7, ROUTE_POINTS, 2.0, {9: 1}, route=route)
            routes.reset(route)
    routes.reset(1)
    sc.op(OP_ROUTE, 1, ROUTE_POINTS, ROUTE_NUMBERS[1])

    # -- CalculateDesiredSpeed: the bends ---------------------------------------
    def bend(pts, n, dls=1, ds=40.0, dt_=0.0, dtol=0.0):
        put_points(sc, pts)
        sc.set(K_NPTS, n)
        sc.set(K_USEDLS, dls)
        sc.set(K_DSPEED, ds)
        sc.set(K_DTIME, dt_)
        sc.set(K_DTOL, dtol)
        sc.op(OP_FILL)
        sc.op(OP_SPEED)

    sc.fresh()
    sc.poke(P_LOCSEL, 0)
    sc.op(OP_LOC, 0, -1, 0, 5, 0)
    with_cur(sc, 0)
    sc.tag("speed, bends by count")
    for n in list(range(0, 21)) + [128, 200, 255]:
        for theta in (0.0, 0.5, 1.2, math.pi / 2, math.pi):
            bend(bend_points(n if n <= 20 else 20, theta), n)
    sc.tag("speed, the cosine's edge")
    base = math.acos(0.64)
    for k in range(-40, 41):
        for rot in (0.0, 1.1, -2.5):
            bend(bend_points(9, base + k * 3e-8, 10.0, 13.0, 3.0, -2.0, rot),
                 9)
    # 16/25 is 0.64 to the float: the dot is TD_BEND_COS exactly.
    y = f32(math.sqrt(369.0))
    exact = [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (26.0, y)] + \
        [(26.0, y)] * (NPTS - 4)
    bend(exact, 4)
    bend(exact, 5)
    sc.tag("speed, zero halves")
    for pts in ([(1.0, 1.0)] * NPTS,
                [(1.0, 1.0), (1.0, 1.0), (1.0, 1.0), (1.0, 5.0)] +
                [(1.0, 5.0)] * (NPTS - 4),
                [(0.0, 0.0), (3.0, 0.0), (6.0, 0.0), (6.0, 0.0)] +
                [(6.0, 0.0)] * (NPTS - 4),
                [(2.0, 0.0), (0.0, 0.0), (2.0, 0.0), (0.0, 0.0)] +
                [(0.0, 0.0)] * (NPTS - 4)):
        for n in (3, 4, 5):
            bend(pts, n)
    sc.tag("speed, the speeds")
    for dls in (0, 1, 5):
        for ds in (0.0, 5.0, 9.0, 10.0, 13.0, 24.5865, 30.0, -3.0, 1e6):
            for n in (0, 5):
                bend(bend_points(5, 2.0), n, dls, ds, 1.25, 0.5)
    # Both: a hairpin and a bend, and a hairpin short of 10 m/s.
    sc.tag("speed, a hairpin and a bend")
    for n, theta in ((0, 0.0), (5, 0.0), (5, 2.0), (9, 0.7)):
        put_points(sc, bend_points(n, theta))
        sc.set(K_NPTS, n)
        for ln, dls in ((1.0, 1), (9.0, 1), (20.0, 1), (1.0, 0), (20.0, 0)):
            sc.set(K_USEDLS, dls)
            sc.set(K_DSPEED, 25.0)
            speed(0, 10, ROUTE_POINTS, ln, {13: 1})
    routes.reset(1)
    for k in (K_NPTS, K_USEDLS):
        sc.set(k, 0)
    for k in (K_DSPEED, K_DTIME, K_DTOL):
        sc.set(k, 0.0)

    # -- JustReset --------------------------------------------------------------
    sc.tag("reset")
    for rn in (48, 49, 50, 51, 55, 58, 59, 60, 61, 69, -1, -32768, 32767,
               None):
        for locsel in (0, 1):
            for cur in (0, 1):
                sc.fresh()
                sc.poke(P_LOCSEL, locsel)
                sc.poke(P_LIST, 1)
                sc.poke(P_PICK, 7)
                if rn is None:
                    sc.op(OP_LOC, 0, -1, 0, 5, 0)
                else:
                    sc.op(OP_ROUTE, 0, ROUTE_POINTS, rn)
                    sc.op(OP_LOC, 0, 0, 3, 5, 0)
                sc.op(OP_LOC, 1, 3, 3, 5, 0)
                if cur:
                    with_cur(sc, 0)
                else:
                    sc.op(OP_CUR, 0)
                sc.op(OP_RESET)
                sc.op(OP_ROUTES)
                sc.op(OP_DUMP)
    sc.op(OP_ROUTE, 0, ROUTE_POINTS, ROUTE_NUMBERS[0])

    # -- random rounds ----------------------------------------------------------
    sc.tag("random")
    for _ in range(400):
        defaults(sc)
        locsel = rnd.randrange(2)
        ready(sc, junk=rnd.choice((0xa5, 0, 0x5c)),
              dtype=rnd.choice((0, 0, 0, TRAFFIC_CAR, 1)), locsel=locsel)
        if rnd.random() < 0.3:
            sc.op(OP_WORLD, 14, 6)
            for i in range(14):
                sc.op(OP_TABLE, i, rnd.choice((MY_CAR, NO_CAR, 2)))
            sc.poke(P_LOOP, rnd.randrange(-50, 50))
        sc.poke(P_TIMER, rnd.choice((rnd.randrange(0, 1 << 32),
                                     rnd.randrange(0, 30000))))
        sc.poke(P_LAST, rnd.choice((0, rnd.randrange(0, 1 << 32))))
        sc.poke(P_MODE, rnd.choice((0, 2, 2, 4)))
        sc.poke(P_DRVNUM, rnd.randrange(-1, 5))
        sc.poke(P_CAMCAR, rnd.randrange(-1, 5))
        sc.poke(P_CHOICE_TYPE, rnd.randrange(-1, 7))
        sc.set(K_LINE, rnd.randrange(3, 7))
        sc.set(K_GCTRP, rnd.choice((GC_LEAVE, GC_LEAVE, GC_LEAVE, GC_CLEAR,
                                    rnd.randrange(NROUTES))))
        sc.set(K_MASK, rnd.randrange(W_ALL + 1))
        sc.set(K_HIT, rnd.randrange(-1, 9))
        sc.set(K_AVOIDCAR, rnd.randrange(-1, 9))
        sc.set(K_SECS, f32(rnd.uniform(-3, 3)))
        sc.set(K_OKAY, rnd.choice((0, 1, rnd.randrange(0, 1 << 32))))
        sc.set(K_USED, rnd.randrange(-1, 3))
        sc.set(K_ACH_TYPE, rnd.randrange(-1, 6))
        sc.set(K_ACH_CAR, rnd.randrange(-1, 9))
        sc.set(K_ACH_EXTRA, rnd.randrange(3))
        sc.set(K_BIAS, rnd.choice((0, 0, rnd.randrange(-300, 300))))
        sc.set(K_STATUS, rnd.randrange(-1, 5))
        sc.set(K_CANEXPIRE, rnd.randrange(2))
        sc.set(K_NPTS, rnd.randrange(0, 21))
        put_points(sc, [(f32(rnd.uniform(-50, 50)), f32(rnd.uniform(-50, 50)))
                        for _ in range(NPTS)])
        sc.set(K_USEDLS, rnd.randrange(2))
        sc.set(K_DSPEED, f32(rnd.uniform(0, 40)))
        sc.set(K_DTIME, f32(rnd.uniform(0, 3)))
        sc.set(K_DTOL, f32(rnd.uniform(0, 3)))
        sc.set(K_ALLOWED, rnd.randrange(2))
        sc.scores(*[rnd.choice((-1, -1, 0, rnd.randrange(-3, 800)))
                    for _ in range(6)])
        if rnd.random() < 0.3:
            sc.op(OP_CUR, 0)
        else:
            with_cur(sc, rnd.choice((0, 149, 150, 399, 400, 499, 500, 599,
                                     600, rnd.randrange(-5, 900))),
                     rnd.randrange(-1, 5), rnd.randrange(2))
        for _ in range(rnd.randrange(1, 4)):
            sc.op(OP_THINK, f32(rnd.choice((0.1, 0.25, 1.0 / 30.0))))
        if rnd.random() < 0.2:
            sc.op(OP_RESET)
        sc.op(OP_DUMP)
        sc.op(OP_WORLD, 0, 0)
        sc.poke(P_LOOP, 0)

    sc.tag("globals")
    sc.op(OP_STATIC)
    return sc


# ================================================================ the model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        e.stub_bware()
        self.heap = []                  # (addr, span, label)
        self.nslots = 0
        self.vals = dict.fromkeys(range(K_COUNT), 0)
        self.pts = [(0, 0)] * NPTS
        for base, n in ((D, 0x1000), (CAR, 0x1000), (DRV, 0x2000),
                        (POOL, 0x1000), (SCR, 0x1000), (FDVT, 0x1000),
                        (FAVT, 0x1000), (SIGNS, 0x1000),
                        (SLOTS, NSLOTS * SLOT_SPAN),
                        (ROUTES, NROUTES * ROUTE_SPAN)):
            e.mem[base:base + n] = bytes(n)
        e.put32(CAR + 20, DRV)
        e.put32(GP + CURRENT_WORLD_GP, WORLD)
        e.put32(GP + SLOT_POOL_GP, POOL)
        e.put32(GP + SIGNPOSTS_GP, SIGNS)
        for k in range(100):
            e.put32(ROUTE_MANAGER + 16 + 4 * k,
                    self.route_addr(k) if k < NROUTES else 0)
        e.put32(FDVT + 12, FDVT_DTOR)
        e.put32(FDVT + 60, FDVT_SPEED)
        e.put32(FDVT + 68, FDVT_TARGET)
        e.put32(FAVT + 12, FAVT_DTOR)
        e.put32(FAVT + 28, FAVT_POINTS)
        e.put32(CUR + 16, FAVT)
        self.stubs()

    def emit(self, s):
        self.out.append(s)

    def w(self, a):
        return self.e.u32(a)

    def car_addr(self, i):
        if i == NO_CAR:
            return 0
        if i == MY_CAR:
            return CAR
        assert 0 <= i < NCARS, i
        return CARS + 0x100 * i

    def route_addr(self, k):
        if k < 0:
            return 0
        assert k < NROUTES, k
        return ROUTES + ROUTE_SPAN * k

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        names = {D: "d", INFO: "info", MYLOC: "myloc", CAR: "car",
                 WORLD: "world", LIST: "list", LOC: "loc", CHOICE: "choice",
                 RENDERER: "renderer"}
        if a in names:
            return names[a]
        if CARS <= a < CARS + 0x100 * NCARS and (a - CARS) % 0x100 == 0:
            return "c%d" % ((a - CARS) // 0x100)
        if CUR <= a < CUR + ACTION_SIZE:
            return "cur" if a == CUR else "cur+%d" % (a - CUR)
        if SLOTS <= a < SLOTS + SLOT_SPAN * NSLOTS:
            i, off = divmod(a - SLOTS, SLOT_SPAN)
            if off < ACTION_SIZE:
                return "a%d" % i if off == 0 else "a%d+%d" % (i, off)
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

        def omalloc(em):
            assert self.nslots < NSLOTS
            p = SLOTS + SLOT_SPAN * self.nslots
            self.nslots += 1
            self.emit("  oalloc %s -> %s" % ("pool" if arg(0) == POOL
                                             else self.label(arg(0)),
                                             self.label(p)))
            return p

        def aicc_ctor(em):
            t = arg(0)
            self.emit("  aicc init %s %s" % (self.label(t),
                                             self.label(arg(1))))
            e.put32(t + OFF_CAR, arg(1))
            e.put32(t + OFF_VT, AICC_VT)
            return t

        def aicc_dtor(em):
            self.emit("  aicc dtor %s %d" % (self.label(arg(0)),
                                             s32(arg(1))))

        def sticky(em):
            self.emit("  sticky %s" % self.label(arg(0)))

        def clear_sticky(em):
            self.emit("  clearsticky %s" % self.label(arg(0)))

        def gctrp(em):
            c = arg(0)
            self.emit("  gctrp %s %s" % (self.label(c), self.label(arg(1))))
            k = s32(self.vals[K_GCTRP])
            if k == GC_LEAVE:
                return
            loc = self.w(c + OFF_LOC)
            e.put32(loc, self.route_addr(k))
            if k >= 0:
                e.put32(loc + 4, self.route_addr(k) + POINT_TABLE)

        def honk(em):
            self.emit("  honk %s %s %s" % (self.label(arg(0)),
                                           self.label(arg(1)),
                                           self.label(arg(2))))

        def psycho(em):
            t = arg(0)
            self.emit("  psycho init %s %s" % (self.label(t),
                                               self.label(arg(1))))
            e.put32(t + DRIVER_VT_OFF, FDVT)
            return t

        def driver_dtor(em):
            self.emit("  driver dtor %s %d" % (self.label(arg(0)),
                                               s32(arg(1))))

        def driver_speed(em):
            self.emit("  driver speed %s %s %s %s %d" % (
                self.label(arg(0)), fx(e.fpr[12]), fx(e.fpr[13]),
                fx(e.fpr[14]), s32(arg(1))))

        def driver_target(em):
            t = arg(1)
            self.emit("  driver target %s %s %d" % (
                self.label(arg(0)), self.label(t), s8(e.u8(t))))

        def act_dtor(em):
            self.emit("  act dtor %s %d" % (self.label(arg(0)),
                                            s32(arg(1))))

        def act_points(em):
            a = arg(0)
            self.emit("  act points %s %s" % (self.label(a),
                                              self.label(arg(1))))
            self.fill(a)

        def build(em):
            self.emit("  build %s %s %s" % (self.label(arg(0)),
                                            self.label(arg(1)),
                                            fx(e.fpr[12])))

        def highlight(em):
            self.emit("  highlight %s %d" % (self.label(arg(0)),
                                             s32(arg(1))))

        def set_mode(em):
            self.emit("  mode %s %d" % (self.label(arg(0)), s32(arg(1))))
            e.put32(arg(0) + 36, arg(1))

        def get_line(em):
            r = s32(self.vals[K_LINE])
            self.emit("  getline %d %s -> %d" % (s32(arg(0)),
                                                 self.label(arg(1)), r))
            return r

        def render(em):
            self.emit("  render %s %s" % (self.label(arg(0)),
                                          self.label(arg(1))))

        def status(em):
            a = arg(0)
            self.emit("  status %s %s" % (self.label(a), self.label(arg(1))))
            e.put32(a + 12, self.vals[K_STATUS])
            e.put32(a + 0, self.vals[K_CANEXPIRE])

        def clear_points(em):
            self.emit("  clearpoints %s" % self.label(arg(0)))

        e.stub(BMALLOC, malloc)
        e.stub(BFREE, free)
        e.stub(BDELETE, free)
        e.stub(BOMALLOC, omalloc)
        e.stub(AICC_CTOR, aicc_ctor)
        e.stub(AICC_DTOR, aicc_dtor)
        e.stub(STICKY, sticky)
        e.stub(CLEAR_STICKY, clear_sticky)
        e.stub(GCTRP, gctrp)
        e.stub(MAYBE_HONK, honk)
        e.stub(PSYCHO_CTOR, psycho)
        e.stub(FDVT_DTOR, driver_dtor)
        e.stub(FDVT_SPEED, driver_speed)
        e.stub(FDVT_TARGET, driver_target)
        e.stub(FAVT_DTOR, act_dtor)
        e.stub(FAVT_POINTS, act_points)
        e.stub(BUILD_ARRAY, build)
        e.stub(HIGHLIGHT, highlight)
        e.stub(SET_MOVEMENT_MODE, set_mode)
        e.stub(GET_DRIVING_LINE, get_line)
        e.stub(SET_TARGET_TO_RENDER, render)
        e.stub(UPDATE_STATUS, status)
        e.stub(CLEAR_POINTS, clear_points)
        for i, (name, addr) in enumerate(SCORES):
            e.stub(addr, self.score_stub(i, name))
        for name, addr in NEWS:
            e.stub(addr, self.new_stub(name))

    def fill(self, a):
        e, v = self.e, self.vals
        e.write(a + 32, bytes([v[K_NPTS] & 0xff]))
        for k, (x, y) in enumerate(self.pts):
            e.put32(a + 48 + 16 * k, x)
            e.put32(a + 52 + 16 * k, y)
        e.put32(a + 564, v[K_DSPEED])
        e.put32(a + 568, v[K_DTIME])
        e.put32(a + 572, v[K_DTOL])
        e.put32(a + 576, v[K_USEDLS])
        e.put32(a + 580, v[K_ALLOWED])

    def choice_str(self, p):
        return "%d %s %d" % (s32(self.w(p)), self.label(self.w(p + 4)),
                             s32(self.w(p + 8)))

    def score_stub(self, i, name):
        e, v = self.e, self.vals

        def put_car(p, key):
            e.put32(p, self.car_addr(s32(v[key])))

        def stub(em):
            a = [e.reg[4 + k] & M32 for k in range(6)]
            mask = v[K_MASK]
            s = "  score %s %s" % (name, self.label(a[0]))
            if i == S_HIT:
                s += " car %s" % self.label(self.w(a[1]))
            elif i == S_AVOID:
                s += " car %s choice %s secs %s okay %d used %d" % (
                    self.label(self.w(a[1])), self.choice_str(a[2]),
                    fx(self.w(a[3])), s32(self.w(a[4])), s32(self.w(a[5])))
            r = s32(v[K_SCORE + i])
            self.emit(s + " -> %d" % r)
            if i == S_HIT and mask & W_HIT:
                put_car(a[1], K_HIT)
            elif i == S_AVOID:
                if mask & W_AVOIDCAR:
                    put_car(a[1], K_AVOIDCAR)
                if mask & W_ACH:
                    e.put32(a[2], v[K_ACH_TYPE])
                    e.put32(a[2] + 4, self.car_addr(s32(v[K_ACH_CAR])))
                    e.put32(a[2] + 8, v[K_ACH_EXTRA])
                if mask & W_SECS:
                    e.put32(a[3], v[K_SECS])
                if mask & W_OKAY:
                    e.put32(a[4], v[K_OKAY])
                if mask & W_USED:
                    e.put32(a[5], v[K_USED])
            return r
        return stub

    def new_stub(self, name):
        e = self.e

        def stub(em):
            a = [e.reg[4 + k] & M32 for k in range(5)]
            s = "  new %s %s %d %s" % (name, self.label(a[0]), s32(a[1]),
                                       fx(e.fpr[12]))
            if name == "unstuck":
                s += " %s" % fx(e.fpr[13])
            elif name == "hit":
                s += " %s" % self.label(a[2])
            elif name == "avoid":
                s += " %s %s %d %d" % (self.label(a[2]), fx(e.fpr[13]),
                                       s32(a[3]), s32(a[4]))
            elif name == "pullover":
                s += " %s %s %s" % (fx(e.fpr[13]), self.label(a[2]),
                                    self.label(a[3]))
            self.emit(s)
            e.put32(a[0] + 16, FAVT)
            e.put32(a[0] + 592, s32(a[1]) + s32(self.vals[K_BIAS]))
            return a[0]
        return stub

    # ---- the dump --------------------------------------------------------

    def vtname(self, v):
        return {TRAFFICDRIVER_VT: "trafficdriver", AICC_VT: "aicc",
                FAVT: "fav"}.get(v, "%08x" % v)

    def dump_loc(self, name, p):
        w = self.w
        self.emit("  %s %s %s %d %08x" % (
            name, self.label(w(p)),
            self.label(w(p + 4)) if w(p) else "-", s32(w(p + 8)),
            w(p + 12)))

    def dump(self):
        w = self.w
        a = w(D + OFF_ACTION)
        al = self.label(a)
        self.emit("d vt %s car %s drv %s act %s force %d pick %d secs %08x "
                  "last %08x"
                  % (self.vtname(w(D + OFF_VT)), self.label(w(D + OFF_CAR)),
                     self.label(w(D + OFF_DRIVER)), al,
                     s32(w(D + OFF_FORCE)), s32(w(D + OFF_PICK)),
                     w(D + OFF_SECS), w(D + OFF_LAST)))
        self.emit("d choice %s mode %d" % (self.choice_str(D + OFF_CHOICE),
                                           s32(w(CAR + 36))))
        self.dump_loc("loc", LOC)
        self.dump_loc("myloc", MYLOC)
        if al[0] == "a" or al == "cur":
            self.emit("  act vt %s type %d score %d status %d exp %d" % (
                self.vtname(w(a + 16)), s32(w(a + 588)), s32(w(a + 592)),
                s32(w(a + 12)), s32(w(a + 0))))

    def static(self):
        w = self.w
        self.emit("g scores %s" % " ".join(
            "%d" % s32(w(GP + GLOBAL_GPS[g])) for g in range(6)))
        self.emit("g lifetimes %s %s %s timeout %s look %s cam %d %d" % (
            fx(w(GP + GLOBAL_GPS[G_L_UNSTUCK])),
            fx(w(GP + GLOBAL_GPS[G_L_AVOID])),
            fx(w(GP + GLOBAL_GPS[G_L_HIT])),
            fx(w(GP + GLOBAL_GPS[G_T_TRAFFIC])),
            fx(w(GP + LOOK_AHEAD_GP)), s32(w(GP + CAM_DEFAULT_GP)),
            s32(w(GP + CAM_CAR_GP))))
        for k in range(17):
            fn = w(TRAFFICDRIVER_VT + 8 * k + 4)
            self.emit("vt %d %d %08x" % (
                k, s16(self.e.u16(TRAFFICDRIVER_VT + 8 * k)), fn))

    # ---- the run ---------------------------------------------------------

    def vcall(self, slot, *args):
        e = self.e
        vt = self.w(D + OFF_VT)
        delta = s16(e.u16(vt + slot))
        fn = self.w(vt + slot + 4)
        return e.call(fn, (D + delta) & M32, *args)

    def cur(self):
        a = self.w(D + OFF_ACTION)
        assert a != 0, "no current action"
        return a

    def run(self, sc):
        e, w = self.e, self.w
        tags = sc.tags
        for o in sc.ops:
            code, a = o[0], o[1:]
            if code == OP_TAG:
                self.emit("[%s]" % tags[a[0]])
            elif code == OP_JUNK:
                e.mem[D:D + D_SIZE] = bytes([a[0] & 0xff]) * D_SIZE
            elif code == OP_NEW:
                self.nslots = 0             # each driver's actions from a0
                self.emit("new")
                r = e.call(CTOR, D, CAR)
                self.emit("new -> %s" % self.label(r))
            elif code == OP_DEL:
                self.emit("del %d" % s32(a[0]))
                self.vcall(8, a[0])
            elif code == OP_NULL:
                e.put32(D + OFF_DRIVER, 0)
            elif code == OP_RAWDEL:
                e.put32(D + OFF_VT, AICC_VT)
                self.emit("rawdel %d" % s32(a[0]))
                e.call(DTOR, D, a[0])
            elif code == OP_THINK:
                self.emit("think %s" % fx(a[0]))
                e.fpr[12] = a[0] & M32
                self.vcall(32)
            elif code == OP_ROUTES:
                e.put32(SCR, 0x5a5a5a5a)
                e.put32(SCR + 4, 0x5a5a5a5a)
                self.vcall(112, SCR, SCR + 4)
                self.emit("routes -> %d %d" % (s32(w(SCR)), s32(w(SCR + 4))))
            elif code == OP_RESET:
                self.emit("reset")
                self.vcall(80)
            elif code == OP_EXEC:
                self.emit("exec")
                e.call(EXEC, D)
            elif code == OP_SPEED:
                for k in range(3):
                    e.put32(SCR + 4 * k, 0x5a5a5a5a)
                e.call(SPEED, D, SCR, SCR + 4, SCR + 8)
                self.emit("speed -> %s %s %s" % (fx(w(SCR)), fx(w(SCR + 4)),
                                                 fx(w(SCR + 8))))
            elif code == OP_DIR:
                e.call(SET_DIRECTION, D, a[0])
            elif code == OP_SET:
                self.vals[a[0]] = a[1] & M32
            elif code == OP_CUR:
                e.put32(D + OFF_ACTION, CUR if a[0] else 0)
            elif code == OP_POKE:
                self.poke(a[0], a[1])
            elif code == OP_GLOBAL:
                e.put32(GP + GLOBAL_GPS[a[0]], a[1])
            elif code == OP_PT:
                self.pts[a[0]] = (a[1] & M32, a[2] & M32)
            elif code == OP_FILL:
                self.fill(self.cur())
            elif code == OP_ROUTE:
                r = self.route_addr(a[0])
                e.put32(r + 16, a[1])
                e.write(r + 10, struct.pack("<h", s16(a[2])))
            elif code == OP_RPOINT:
                p = self.route_addr(a[0]) + POINT_TABLE + POINT_SIZE * a[1]
                e.put32(p + 20, a[2])
                e.write(p + 44, bytes([a[3] & 0xff]))
            elif code == OP_SIGN:
                p = SIGNS + 12 * a[0]
                e.write(p, bytes([a[2] & 0xff, a[1] & 0xff]))
                e.write(p + 2, struct.pack("<H", (a[2] >> 8) & 0xffff))
            elif code == OP_LOC:
                p = LOC if a[0] == 1 else MYLOC
                rk = s32(a[1])
                r = self.route_addr(rk)
                e.put32(p, r)
                e.put32(p + 4, r + POINT_TABLE + POINT_SIZE * a[2]
                        if rk >= 0 else 0)
                e.put32(p + 8, a[3])
                e.put32(p + 12, a[4])
            elif code == OP_WORLD:
                e.put32(WORLD + 28, a[0])
                e.put32(WORLD + 40, a[1])
            elif code == OP_TABLE:
                e.put32(WORLD + 44 + 4 * a[0], self.car_addr(s32(a[1])))
            elif code == OP_DUMP:
                self.dump()
            elif code == OP_STATIC:
                self.static()
            else:
                raise ValueError("op %d" % code)
        return self.out

    def poke(self, f, v):
        e, w = self.e, self.w
        if f == P_TIMER:
            e.put32(GP + WORLD_TIMER_GP, v)
        elif f == P_LOOP:
            e.put32(GP + LOOP_COUNTER_GP, v)
        elif f == P_LAST:
            e.put32(D + OFF_LAST, v)
        elif f == P_SECS:
            e.put32(D + OFF_SECS, v)
        elif f == P_PICK:
            e.put32(D + OFF_PICK, v)
        elif f == P_DTYPE:
            e.put32(DRV + 8, v)
        elif f == P_CARIDX:
            e.write(CAR + 8, struct.pack("<h", s16(v)))
        elif f == P_DRVNUM:
            e.write(CAR + 10, struct.pack("<h", s16(v)))
        elif f == P_MODE:
            e.put32(CAR + 36, v)
        elif f == P_LOCSEL:
            e.put32(D + OFF_LOC, LOC if s32(v) == 1 else MYLOC)
            e.put32(D + OFF_CURCHOICE, CHOICE)
        elif f == P_LIST:
            e.put32(D + OFF_LIST, LIST if v else 0)
        elif f == P_CHOICE_TYPE:
            e.put32(CHOICE, v)
        elif f == P_CAMCAR:
            e.put32(GP + CAM_CAR_GP, v)
        elif f == P_CAMDEF:
            e.put32(GP + CAM_DEFAULT_GP, v)
        elif f == P_LOOKAHEAD:
            e.put32(GP + LOOK_AHEAD_GP, v)
        elif f == P_FORCE:
            e.put32(D + OFF_FORCE, v)
        elif f == P_CUR_TYPE:
            e.put32(self.cur() + 588, v)
        elif f == P_CUR_SCORE:
            e.put32(self.cur() + 592, v)
        elif f == P_CUR_STATUS:
            e.put32(self.cur() + 12, v)
        elif f == P_CUR_CANEXP:
            e.put32(self.cur() + 0, v)
        else:
            raise ValueError("poke %d" % f)


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc.encode().hex().splitlines()
                               + sc.tags, lambda s: Model().run(sc),
                               cut=MUTATIONS_HEADER)


# ================================================================ the build


def build_harness(tmp, name="trafficdriver_test"):
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
    return (name, TDC, before, after)


def step(score_call, init):
    """The text from a cascade step's CalculateScore to its constructor."""
    return score_call + NL + "            if (best < s) {" + NL + \
        "                delete_current(d);" + NL + init


UN_INIT = "                c->CurrentAction = &aigetunstuck_init("
RC_INIT = "                c->CurrentAction = &aiaccidentrecovery_init("
HIT_HONK = ("                aicarcontroller_maybe_honk_and_or_blink_headlights("
            + NL + "                    c, hitCar, &info->MyNearbyCarList);")
AV_HONK = ("                aicarcontroller_maybe_honk_and_or_blink_headlights("
           + NL + "                    c, avoidCar, &info->MyNearbyCarList);")
AV_NEW = ("                c->CurrentAction = &aiavoidcars_init(" + NL +
          "                    (AIActionAvoidCars *)aiaction_new(), s," + NL +
          "                    AIActionAvoidCarsLifetime, avoidCar," + NL +
          "                    (float)(uint32_t)okay, used, 0)->Base;")
BEST = "                best = c->CurrentAction->Score;" + NL + \
    "            }" + NL + "        }" + NL + NL + "        if (best < "
DT_DRIVER = ("    if (drv != NULL) {" + NL +
             "        const VtEntry *e = vt_slot(drv->_vtable, CARDRIVER_VT_DTOR);"
             + NL + "        ((DriverDtorFn)e->fn)(vt_this(drv, e), 3);" + NL +
             "    }" + NL)
DT_BASE = "    aicarcontroller_destroy(&d->Base, flags);" + NL
EX_POINTS = ("    ((ActionInfoFn)e->fn)(vt_this(a, e), "
             "&c->MyCurrentDrivingInformation);" + NL)
EX_RENDER = ("    if (aicarcontroller_get_my_driver_number(c) == "
             "CameraFollowThisCarInstead)" + NL +
             "        drivetargetrenderer_set_target_to_render(" + NL +
             "            &TheDriveTargetRenderer, "
             "&c->CurrentAction->PointsToDrive);" + NL)
EX_TARGET = ("    drv = c->Base.Driver;" + NL +
             "    e = vt_slot(drv->_vtable, CARDRIVER_VT_SET_TARGET);" + NL +
             "    ((DriverTargetFn)e->fn)(vt_this(drv, e)," + NL +
             "                            &c->CurrentAction->PointsToDrive);"
             + NL)
EX_SPEED = ("    drv = c->Base.Driver;" + NL +
            "    e = vt_slot(drv->_vtable, CARDRIVER_VT_SET_DESIRED_SPEED);" + NL +
            "    ((DriverDesiredSpeedFn)e->fn)(vt_this(drv, e), speed, time, tol,"
            + NL + "                                  "
            "c->CurrentAction->AllowedToUseThrottleAndBrake);" + NL)
JR_DEL = "    delete_current(d);" + NL
JR_STICKY = "    aicarcontroller_clear_sticky_decisions(c);" + NL

MUTATIONS = [
    # -- the constants ----------------------------------------------------------
    M("k-stagger", "#define TD_THINK_STAGGER  (-0.0142857153f)",
      "#define TD_THINK_STAGGER  (-0.0142857162f)"),
    M("k-interval", "#define TD_THINK_INTERVAL 0.200000003f",
      "#define TD_THINK_INTERVAL 0.200000018f"),
    M("k-turns", "#define TD_TURNS 12", "#define TD_TURNS 10"),
    M("k-tick", "#define TD_TICKS_TO_SECONDS 0.000250000012f",
      "#define TD_TICKS_TO_SECONDS 0.000250000041f"),
    M("k-wait", "#define TD_UNSTUCK_WAIT     2.0f",
      "#define TD_UNSTUCK_WAIT     1.99999988f"),
    M("k-nolife", "#define TD_NO_LIFETIME (-1.0f)",
      "#define TD_NO_LIFETIME (-2.0f)"),
    M("k-top", "#define TD_TOP_SPEED         24.5865002f",
      "#define TD_TOP_SPEED         24.5865021f"),
    M("k-look-lo", "#define TD_HAIRPIN_LOOK      75.0f",
      "#define TD_HAIRPIN_LOOK      74.9999924f"),
    M("k-look-hi", "#define TD_HAIRPIN_LOOK      75.0f",
      "#define TD_HAIRPIN_LOOK      75.0000076f"),
    M("k-points", "#define TD_HAIRPIN_POINTS    18.75f",
      "#define TD_HAIRPIN_POINTS    19.0f"),
    M("k-points-lo", "#define TD_HAIRPIN_POINTS    18.75f",
      "#define TD_HAIRPIN_POINTS    17.99f"),
    M("k-hspeed", "#define TD_HAIRPIN_SPEED     0.327820003f",
      "#define TD_HAIRPIN_SPEED     0.327820033f"),
    M("k-take-lo", "#define TD_HAIRPIN_TAKE      10.0f",
      "#define TD_HAIRPIN_TAKE      9.99999905f"),
    M("k-take-hi", "#define TD_HAIRPIN_TAKE      10.0f",
      "#define TD_HAIRPIN_TAKE      10.000001f"),
    M("k-cos", "#define TD_BEND_COS          0.639999986f",
      "#define TD_BEND_COS          0.640000045f"),
    M("k-cos-lo", "#define TD_BEND_COS          0.639999986f",
      "#define TD_BEND_COS          0.639999926f"),
    M("k-bspeed", "#define TD_BEND_SPEED        10.0f",
      "#define TD_BEND_SPEED        10.000001f"),
    M("k-tol", "#define TD_SLOW_TOLERANCE    2.0f",
      "#define TD_SLOW_TOLERANCE    2.00000024f"),
    M("k-least", "#define TD_LEAST_SPEED       10.0f",
      "#define TD_LEAST_SPEED       10.000001f"),
    M("k-low-first", "#define TD_LOW_FIRST  50", "#define TD_LOW_FIRST  51"),
    M("k-low-last", "#define TD_LOW_LAST   59", "#define TD_LOW_LAST   58"),
    M("k-high-first", "#define TD_HIGH_FIRST 60",
      "#define TD_HIGH_FIRST 61"),
    M("k-high-last", "#define TD_HIGH_LAST  69", "#define TD_HIGH_LAST  68"),
    M("k-pool", "#define TD_POOL CAR_MEMORY_POOL", "#define TD_POOL 15"),

    # -- the helpers ------------------------------------------------------------
    M("max-swap", "return fs < ft ? ft : fs;", "return fs < ft ? fs : ft;"),
    M("min-swap", "return fs < ft ? fs : ft;", "return fs < ft ? ft : fs;"),
    M("ss-unsigned", "(float)(int32_t)((uint32_t)WorldTimer - t->PackedTime)",
      "(float)((uint32_t)WorldTimer - t->PackedTime)"),
    M("ss-order", "((uint32_t)WorldTimer - t->PackedTime)",
      "(t->PackedTime - (uint32_t)WorldTimer)"),
    M("del-flags", "((ActionDtorFn)e->fn)(vt_this(a, e), 3);",
      "((ActionDtorFn)e->fn)(vt_this(a, e), 1);"),
    M("del-null", "    if (d->Base.CurrentAction != NULL)" + NL,
      "    if (1)" + NL),
    M("jd-life", "score," + NL + "                             TD_NO_LIFETIME)",
      "score," + NL + "                             0.0f)"),
    M("jd-score", "aiaction_new(), score,", "aiaction_new(), score + 1,"),
    M("belt-mode", "if (car->TheMovementMode == TRAFFIC_MOVEMENT)",
      "if (car->TheMovementMode != TRAFFIC_MOVEMENT)"),
    M("belt-target", "car_set_movement_mode(car, MELLOW_MOVEMENT);",
      "car_set_movement_mode(car, MELLOW_MOVEMENT + 1);"),

    # -- the constructor and the destructor -------------------------------------
    M("ct-vt", "    d->Base.Base._vtable = TRAFFICDRIVER_VTABLE;" + NL +
      "    pd = ", "    pd = "),
    M("ct-size", "bMalloc((int)sizeof(PsychoDriver), ",
      "bMalloc((int)sizeof(PsychoDriver) + 16, "),
    M("ct-name", "\"PsychoDriver\",", "\"Psycho\","),
    M("ct-flags", "0, TD_POOL);", "1, TD_POOL);"),
    M("ct-pdcar", "pd = psychodriver_init(pd, car);",
      "pd = psychodriver_init(pd, NULL);"),
    M("ct-driver", "d->Base.Base.Driver = &pd->Base;",
      "d->Base.Base.Driver = NULL;"),
    M("ct-force", "d->Base.ForceCurrentAction = AIACTION_NONE;",
      "d->Base.ForceCurrentAction = AIACTION_NONE - 1;"),
    M("ct-pick", "d->PickLowNumberedRoutes = 1;",
      "d->PickLowNumberedRoutes = 2;"),
    M("ct-action", "    d->Base.CurrentAction = NULL;" + NL, ""),
    M("ct-secs", "(float)car->CarIndex * TD_THINK_STAGGER;",
      "(float)(car->CarIndex + 1) * TD_THINK_STAGGER;"),
    M("ct-secs-u", "(float)car->CarIndex * TD_THINK_STAGGER;",
      "(float)(uint16_t)car->CarIndex * TD_THINK_STAGGER;"),
    M("ct-ret", "    return d;" + NL, "    return NULL;" + NL),
    M("dt-vt", "    d->Base.Base._vtable = TRAFFICDRIVER_VTABLE;" + NL +
      "    drv = ", "    drv = "),
    M("dt-null", "    if (drv != NULL) {", "    if (1) {"),
    M("dt-flags", "((DriverDtorFn)e->fn)(vt_this(drv, e), 3);",
      "((DriverDtorFn)e->fn)(vt_this(drv, e), 1);"),
    M("dt-base-flags", "aicarcontroller_destroy(&d->Base, flags);",
      "aicarcontroller_destroy(&d->Base, 1);"),
    M("dt-order", DT_DRIVER + DT_BASE, DT_BASE + DT_DRIVER),

    # -- whose turn -------------------------------------------------------------
    M("mt-type", "if (car->MyDriver->TheDriverType != DRIVER_TYPE_TRAFFIC_CAR)",
      "if (car->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR)"),
    M("mt-le", "return d->Base.SecondsBeforeNextActionEvaluation <= 0.0f;",
      "return d->Base.SecondsBeforeNextActionEvaluation < 0.0f;"),
    M("mt-mod", "m = WorldLoopCounter % TD_TURNS;",
      "m = (int32_t)((uint32_t)WorldLoopCounter % TD_TURNS);"),
    M("mt-odd", "if ((m & 1) == 0)", "if ((m & 1) != 0)"),
    M("mt-half", "    m >>= 1;", "    m /= 2;"),
    M("mt-lt", "return m < w->TotalNumCars - w->TrafficCarPos",
      "return m <= w->TotalNumCars - w->TrafficCarPos"),
    M("mt-sub", "return m < w->TotalNumCars - w->TrafficCarPos",
      "return m < w->TotalNumCars"),
    M("mt-pos", "&& w->CarTable[w->TrafficCarPos + m] == car;",
      "&& w->CarTable[m] == car;"),

    # -- Think ------------------------------------------------------------------
    M("th-dt", "c->SecondsBeforeNextActionEvaluation -= dt;",
      "c->SecondsBeforeNextActionEvaluation += dt;"),
    M("th-sticky", "    aicarcontroller_do_sticky_decisions(c);" + NL, ""),
    M("th-interval",
      "c->SecondsBeforeNextActionEvaluation += TD_THINK_INTERVAL;",
      "c->SecondsBeforeNextActionEvaluation = TD_THINK_INTERVAL;"),
    M("th-build-loc", "c->CurrentDrivingLocation," + NL +
      "                              AIDriverSecondsToLookAhead);",
      "&info->MyDrivingLocation," + NL +
      "                              AIDriverSecondsToLookAhead);"),
    M("th-build-list", "nearbycarlist_build_array(&info->MyNearbyCarList,",
      "nearbycarlist_build_array(c->CurrentNearbyCarList,"),
    M("th-build-secs", "AIDriverSecondsToLookAhead);",
      "AIDriverSecondsToLookAhead + 1.0f);"),
    M("th-gctrp", "aicarcontroller_get_current_track_route_point(c, NULL);",
      "aicarcontroller_get_current_track_route_point(c, car);"),
    M("th-clear", "if (drivinglocation_is_clear(c->CurrentDrivingLocation))" +
      NL + "        return;", "if (0)" + NL + "        return;"),
    M("th-clear-loc",
      "if (drivinglocation_is_clear(c->CurrentDrivingLocation))" + NL +
      "        return;",
      "if (drivinglocation_is_clear(&info->MyDrivingLocation))" + NL +
      "        return;"),
    M("th-null", "    if (c->CurrentAction == NULL) {", "    if (0) {"),
    M("th-null-score", "new_just_drive(AIActionJustDriveScore);" + NL +
      "    } else {",
      "new_just_drive(AIActionJustDriveScore + 1);" + NL + "    } else {"),
    M("th-status", "        aiaction_update_status(c->CurrentAction, info);"
      + NL, ""),
    M("th-ttc", "best = aiplan_time_to_change(&c->CurrentAction->Base)" + NL +
      "                   ? -1 : c->CurrentAction->Score;",
      "best = c->CurrentAction->Score;"),
    M("th-ttc-neg", "? -1 : c->CurrentAction->Score;",
      "? 0 : c->CurrentAction->Score;"),
    M("in-hit", "hitCar = NULL;", "hitCar = car;"),
    M("in-avoid", "avoidCar = NULL;", "avoidCar = car;"),
    M("in-okay", "okay = 1;", "okay = 0;"),
    M("in-used", "used = 0;", "used = 1;"),
    M("in-secs", "secs = 0.0f;", "secs = 1.0f;"),
    M("in-clear", "        drivingchoice_clear(&choice);" + NL,
      "        drivingchoice_clear(&choice);" + NL +
      "        choice.UseExtraLateralDistance = 1;" + NL),

    # -- the cascade: GetUnstuck ------------------------------------------------
    M("un-gate", "if (best < AIActionGetUnstuckScore",
      "if (best <= AIActionGetUnstuckScore"),
    M("un-gate-g", "if (best < AIActionGetUnstuckScore",
      "if (best < AIActionAccidentRecoveryScore"),
    M("un-wait-lt", "TD_UNSTUCK_WAIT" + NL + "                   < seconds_since(",
      "TD_UNSTUCK_WAIT" + NL + "                   <= seconds_since("),
    M("un-lt", "s = aigetunstuck_calculate_score(info);" + NL +
      "            if (best < s) {",
      "s = aigetunstuck_calculate_score(info);" + NL +
      "            if (best <= s) {"),
    M("un-del", step("            s = aigetunstuck_calculate_score(info);",
                     UN_INIT),
      "            s = aigetunstuck_calculate_score(info);" + NL +
      "            if (best < s) {" + NL + UN_INIT),
    M("un-score", "(AIActionGetUnstuck *)aiaction_new(), s,",
      "(AIActionGetUnstuck *)aiaction_new(), s + 1,"),
    M("un-life", "AIActionGetUnstuckLifetime, TD_NO_LIFETIME)->Base;",
      "TD_NO_LIFETIME, AIActionGetUnstuckLifetime)->Base;"),
    M("un-stamp", "c->LastTimeNonGetUnstuckActionWasCalled.PackedTime =" + NL +
      "                    (uint32_t)WorldTimer;",
      "c->LastTimeNonGetUnstuckActionWasCalled.PackedTime =" + NL +
      "                    (uint32_t)WorldTimer + 1;"),
    M("un-stamp-drop", "                c->LastTimeNonGetUnstuckActionWasCalled"
      ".PackedTime =" + NL + "                    (uint32_t)WorldTimer;" + NL,
      ""),
    M("un-best", BEST + "AIActionAccidentRecoveryScore",
      "            }" + NL + "        }" + NL + NL +
      "        if (best < AIActionAccidentRecoveryScore"),

    # -- AccidentRecovery -------------------------------------------------------
    M("rc-gate", "if (best < AIActionAccidentRecoveryScore) {",
      "if (best <= AIActionAccidentRecoveryScore) {"),
    M("rc-gate-g", "if (best < AIActionAccidentRecoveryScore) {",
      "if (best < AIActionGetUnstuckScore) {"),
    M("rc-lt", "s = aiaccidentrecovery_calculate_score(info);" + NL +
      "            if (best < s) {",
      "s = aiaccidentrecovery_calculate_score(info);" + NL +
      "            if (best <= s) {"),
    M("rc-del", step("            s = aiaccidentrecovery_calculate_score(info);",
                     RC_INIT),
      "            s = aiaccidentrecovery_calculate_score(info);" + NL +
      "            if (best < s) {" + NL + RC_INIT),
    M("rc-score", "(AIActionAccidentRecovery *)aiaction_new(), s,",
      "(AIActionAccidentRecovery *)aiaction_new(), s + 1,"),
    M("rc-life", "(AIActionAccidentRecovery *)aiaction_new(), s," + NL +
      "                    TD_NO_LIFETIME)->Base;",
      "(AIActionAccidentRecovery *)aiaction_new(), s," + NL +
      "                    0.0f)->Base;"),
    M("rc-best", BEST + "AIActionIJustGotHitScore",
      "            }" + NL + "        }" + NL + NL +
      "        if (best < AIActionIJustGotHitScore"),

    # -- IJustGotHit ------------------------------------------------------------
    M("hit-gate", "if (best < AIActionIJustGotHitScore) {",
      "if (best <= AIActionIJustGotHitScore) {"),
    M("hit-gate-g", "if (best < AIActionIJustGotHitScore) {",
      "if (best < AIActionAvoidCarsScore) {"),
    M("hit-lt", "s = aijustgothit_calculate_score(info, &hitCar);" + NL +
      "            if (best < s) {",
      "s = aijustgothit_calculate_score(info, &hitCar);" + NL +
      "            if (best <= s) {"),
    M("hit-car", "s = aijustgothit_calculate_score(info, &hitCar);",
      "s = aijustgothit_calculate_score(info, &avoidCar);"),
    M("hit-del", "                delete_current(d);" + NL + HIT_HONK,
      HIT_HONK),
    M("hit-honk", HIT_HONK + NL, ""),
    M("hit-honk-car", "c, hitCar, &info->MyNearbyCarList);",
      "c, NULL, &info->MyNearbyCarList);"),
    M("hit-honk-list", "c, hitCar, &info->MyNearbyCarList);",
      "c, hitCar, c->CurrentNearbyCarList);"),
    M("hit-honk-order", "                delete_current(d);" + NL + HIT_HONK,
      HIT_HONK + NL + "                delete_current(d);"),
    M("hit-score", "(AIActionIJustGotHit *)aiaction_new(), s,",
      "(AIActionIJustGotHit *)aiaction_new(), s + 1,"),
    M("hit-life", "AIActionIJustGotHitLifetime, hitCar)->Base;",
      "AIActionIJustGotHitLifetime + 1.0f, hitCar)->Base;"),
    M("hit-newcar", "AIActionIJustGotHitLifetime, hitCar)->Base;",
      "AIActionIJustGotHitLifetime, NULL)->Base;"),
    M("hit-best", BEST + "AIActionAvoidCarsScore",
      "            }" + NL + "        }" + NL + NL +
      "        if (best < AIActionAvoidCarsScore"),

    # -- AvoidCars --------------------------------------------------------------
    M("av-gate", "if (best < AIActionAvoidCarsScore) {",
      "if (best <= AIActionAvoidCarsScore) {"),
    M("av-gate-g", "if (best < AIActionAvoidCarsScore) {",
      "if (best < AIActionIJustGotHitScore) {"),
    M("av-lt", "                                            &okay, &used);" +
      NL + "            if (best < s) {",
      "                                            &okay, &used);" + NL +
      "            if (best <= s) {"),
    M("av-args", "&okay, &used);", "&used, &okay);"),
    M("av-del", "                delete_current(d);" + NL +
      "                // AIDriver's arguments", "                // AIDriver's"
      " arguments"),
    M("av-score", "(AIActionAvoidCars *)aiaction_new(), s,",
      "(AIActionAvoidCars *)aiaction_new(), s + 1,"),
    M("av-life", "AIActionAvoidCarsLifetime, avoidCar,",
      "AIActionAvoidCarsLifetime + 1.0f, avoidCar,"),
    M("av-car", "AIActionAvoidCarsLifetime, avoidCar,",
      "AIActionAvoidCarsLifetime, hitCar,"),
    M("av-okay-signed", "(float)(uint32_t)okay, used, 0)->Base;",
      "(float)okay, used, 0)->Base;"),
    M("av-secs", "(float)(uint32_t)okay, used, 0)->Base;",
      "secs, used, 0)->Base;"),
    M("av-used", "(float)(uint32_t)okay, used, 0)->Base;",
      "(float)(uint32_t)okay, okay, 0)->Base;"),
    M("av-zero", "(float)(uint32_t)okay, used, 0)->Base;",
      "(float)(uint32_t)okay, used, 1)->Base;"),
    M("av-choice", "                info->MyDrivingChoice = choice;" + NL, ""),
    M("av-honk", AV_HONK + NL, ""),
    M("av-honk-car", "c, avoidCar, &info->MyNearbyCarList);",
      "c, hitCar, &info->MyNearbyCarList);"),
    M("av-honk-list", "c, avoidCar, &info->MyNearbyCarList);",
      "c, avoidCar, c->CurrentNearbyCarList);"),
    M("av-honk-order", AV_NEW + NL +
      "                info->MyDrivingChoice = choice;" + NL + AV_HONK,
      AV_HONK + NL + AV_NEW + NL +
      "                info->MyDrivingChoice = choice;"),
    M("av-belt", "                off_the_belt(car);" + NL +
      BEST + "AIActionPullOverScore",
      BEST + "AIActionPullOverScore"),
    M("av-belt-order", AV_HONK + NL + "                off_the_belt(car);",
      "                off_the_belt(car);" + NL + AV_HONK),
    M("av-best", BEST + "AIActionPullOverScore",
      "            }" + NL + "        }" + NL + NL +
      "        if (best < AIActionPullOverScore"),

    # -- PullOver ---------------------------------------------------------------
    M("po-gate", "if (best < AIActionPullOverScore) {",
      "if (best <= AIActionPullOverScore) {"),
    M("po-gate-g", "if (best < AIActionPullOverScore) {",
      "if (best < AIActionGetUnstuckScore) {"),
    M("po-lt", "s = aipullover_calculate_score(info);" + NL +
      "            if (best < s) {",
      "s = aipullover_calculate_score(info);" + NL +
      "            if (best <= s) {"),
    M("po-del", "                delete_current(d);" + NL +
      "                c->CurrentAction = &aipullover_init(",
      "                c->CurrentAction = &aipullover_init("),
    M("po-score", "(AIActionPullOver *)aiaction_new(), s, TD_NO_LIFETIME,",
      "(AIActionPullOver *)aiaction_new(), s + 1, TD_NO_LIFETIME,"),
    M("po-life", "(AIActionPullOver *)aiaction_new(), s, TD_NO_LIFETIME,",
      "(AIActionPullOver *)aiaction_new(), s, 0.0f,"),
    M("po-timeout", "AIActionPullOverTrafficCarTimeout,",
      "AIActionPullOverTrafficCarTimeout + 1.0f,"),
    M("po-list", "c->CurrentNearbyCarList, c->CurrentDrivingLocation)->Base;",
      "&info->MyNearbyCarList, c->CurrentDrivingLocation)->Base;"),
    M("po-loc", "c->CurrentNearbyCarList, c->CurrentDrivingLocation)->Base;",
      "c->CurrentNearbyCarList, &info->MyDrivingLocation)->Base;"),
    M("po-belt", "                off_the_belt(car);" + NL +
      BEST + "AIActionJustDriveScore",
      BEST + "AIActionJustDriveScore"),
    M("po-best", BEST + "AIActionJustDriveScore",
      "            }" + NL + "        }" + NL + NL +
      "        if (best < AIActionJustDriveScore"),

    # -- JustDrive --------------------------------------------------------------
    M("jd-gate", "if (best < AIActionJustDriveScore) {",
      "if (best <= AIActionJustDriveScore) {"),
    M("jd-lt", "s = aijustdrive_calculate_score(info);" + NL +
      "            if (best < s) {",
      "s = aijustdrive_calculate_score(info);" + NL +
      "            if (best <= s) {"),
    M("jd-new-score", "c->CurrentAction = new_just_drive(s);",
      "c->CurrentAction = new_just_drive(s + 1);"),
    M("jd-del", "                delete_current(d);" + NL +
      "                c->CurrentAction = new_just_drive(s);",
      "                c->CurrentAction = new_just_drive(s);"),
    M("fallback", "        if (c->CurrentAction == NULL)" + NL +
      "            c->CurrentAction = new_just_drive(AIActionJustDriveScore);",
      "        if (0)" + NL +
      "            c->CurrentAction = new_just_drive(AIActionJustDriveScore);"),

    # -- the driving line -------------------------------------------------------
    M("dl-type", "type = c->CurrentDrivingChoice->Type;",
      "type = info->MyDrivingChoice.Type;"),
    M("dl-is", "if (drivingchoice_type_is_driving_line(type)) {",
      "if (!drivingchoice_type_is_driving_line(type)) {"),
    M("dl-car", "drivingchoice_get_driving_line(type, car);",
      "drivingchoice_get_driving_line(type, NULL);"),
    M("dl-type-arg", "drivingchoice_get_driving_line(type, car);",
      "drivingchoice_get_driving_line(CHOICE_NONE, car);"),
    M("dl-ne", "if (line != c->CurrentDrivingLocation->DrivingLine) {",
      "if (line == c->CurrentDrivingLocation->DrivingLine) {"),
    M("dl-loc", "if (line != c->CurrentDrivingLocation->DrivingLine) {",
      "if (line != info->MyDrivingLocation.DrivingLine) {"),
    M("dl-set-loc",
      "drivinglocation_set_driving_line(c->CurrentDrivingLocation, line,",
      "drivinglocation_set_driving_line(&info->MyDrivingLocation, line,"),
    M("dl-set-relaxed", "line," + NL +
      "                                             0);",
      "line," + NL + "                                             1);"),
    M("dl-set", "            drivinglocation_set_driving_line("
      "c->CurrentDrivingLocation, line," + NL +
      "                                             0);" + NL, ""),
    M("dl-hl", "            ai_highlight_driving_line(c->CurrentDrivingLocation,"
      + NL + "                                      "
      "aicarcontroller_get_my_driver_number(c));" + NL, ""),
    M("dl-hl-loc", "ai_highlight_driving_line(c->CurrentDrivingLocation,",
      "ai_highlight_driving_line(&info->MyDrivingLocation,"),
    M("dl-hl-num", "aicarcontroller_get_my_driver_number(c));",
      "aicarcontroller_get_my_driver_number(c) + 1);"),
    M("dl-exec", "    trafficdriver_execute_current_action(d);" + NL + "}" +
      NL + NL + "void trafficdriver_get_route_numbers_to_use",
      "}" + NL + NL + "void trafficdriver_get_route_numbers_to_use"),

    # -- the routes and JustReset -----------------------------------------------
    M("rt-pick", "if (d->PickLowNumberedRoutes) {",
      "if (!d->PickLowNumberedRoutes) {"),
    M("jr-myloc", "TrackRoute *r = c->MyCurrentDrivingInformation."
      "MyDrivingLocation.pRoute;",
      "TrackRoute *r = c->CurrentDrivingLocation->pRoute;"),
    M("jr-null", "    if (r != NULL)" + NL, "    if (1)" + NL),
    M("jr-le", "            < (uint32_t)(TD_LOW_LAST - TD_LOW_FIRST + 1);",
      "            <= (uint32_t)(TD_LOW_LAST - TD_LOW_FIRST + 1);"),
    M("jr-signed", "(uint32_t)(r->RouteNumber - TD_LOW_FIRST)" + NL +
      "            < (uint32_t)(TD_LOW_LAST - TD_LOW_FIRST + 1);",
      "(r->RouteNumber - TD_LOW_FIRST)" + NL +
      "            < (TD_LOW_LAST - TD_LOW_FIRST + 1);"),
    M("jr-del", JR_DEL + JR_STICKY, JR_STICKY),
    M("jr-sticky", JR_DEL + JR_STICKY, JR_DEL),
    M("jr-order", JR_DEL + JR_STICKY, JR_STICKY + JR_DEL),
    M("jr-score", "    c->CurrentAction = new_just_drive(AIActionJustDriveScore);"
      + NL + "    trafficdriver_execute_current_action(d);",
      "    c->CurrentAction = new_just_drive(AIActionJustDriveScore + 1);"
      + NL + "    trafficdriver_execute_current_action(d);"),
    M("jr-exec", "    c->CurrentAction = new_just_drive(AIActionJustDriveScore);"
      + NL + "    trafficdriver_execute_current_action(d);" + NL,
      "    c->CurrentAction = new_just_drive(AIActionJustDriveScore);" + NL),

    # -- ExecuteCurrentAction ---------------------------------------------------
    M("ex-info", "(vt_this(a, e), &c->MyCurrentDrivingInformation);",
      "(vt_this(a, e), NULL);"),
    M("ex-cam", "(c) == CameraFollowThisCarInstead)",
      "(c) != CameraFollowThisCarInstead)"),
    M("ex-cam-def", "(c) == CameraFollowThisCarInstead)",
      "(c) == CameraFollowDefaultCar)"),
    M("ex-render", "&TheDriveTargetRenderer, &c->CurrentAction->PointsToDrive);",
      "&TheDriveTargetRenderer, (DriveTarget *)c->CurrentAction);"),
    M("ex-order", EX_POINTS + EX_RENDER, EX_RENDER + EX_POINTS),
    M("ex-swap", "(vt_this(drv, e), speed, time, tol,",
      "(vt_this(drv, e), speed, tol, time,"),
    M("ex-allowed", "c->CurrentAction->AllowedToUseThrottleAndBrake);",
      "1);"),
    M("ex-target", "((DriverTargetFn)e->fn)(vt_this(drv, e)," + NL +
      "                            &c->CurrentAction->PointsToDrive);",
      "((DriverTargetFn)e->fn)(vt_this(drv, e)," + NL +
      "                            (DriveTarget *)c->CurrentAction);"),
    M("ex-call-order", EX_TARGET + EX_SPEED, EX_SPEED + EX_TARGET),
    M("ex-clear", "    aiaction_clear_points_to_drive(c->CurrentAction);" + NL,
      ""),

    # -- the hairpins -----------------------------------------------------------
    M("fh-sum", "float sum = 0.0f;", "float sum = 1.0f;"),
    M("fh-k", "int32_t i, k = 0;", "int32_t i, k = 1;"),
    M("fh-n", "int32_t n = (int32_t)TD_HAIRPIN_POINTS;",
      "int32_t n = (int32_t)TD_HAIRPIN_POINTS + 1;"),
    M("fh-start", "if (n < 0 || !(i < r->NumPoints)) {",
      "if (n < 0 || !(i <= r->NumPoints)) {"),
    M("fh-start-n", "if (n < 0 || !(i < r->NumPoints)) {",
      "if (n < 19 || !(i < r->NumPoints)) {"),
    M("fh-has", "if (trpoint_has_signpost(p)) {", "if (1) {"),
    M("fh-hair", "if ((s->Flags & SIGNPOST_HAIRPIN)",
      "if (!(s->Flags & SIGNPOST_HAIRPIN)"),
    M("fh-back", "&& !(s->Flags & SIGNPOST_BACKWARDS)) {", ") {"),
    M("fh-dist", "*dist = sum;" + NL + "                return p;",
      "*dist = sum + 1.0f;" + NL + "                return p;"),
    M("fh-len", "        sum += p->Length;" + NL + "        p++;",
      "        p++;" + NL + "        sum += p->Length;"),
    M("fh-look", "if (!(sum < TD_HAIRPIN_LOOK))",
      "if (!(sum <= TD_HAIRPIN_LOOK))"),
    M("fh-kle", "if (n < k || !(i < r->NumPoints))",
      "if (n <= k || !(i < r->NumPoints))"),
    M("fh-end", "if (n < k || !(i < r->NumPoints))",
      "if (n < k || !(i <= r->NumPoints))"),

    # -- CalculateDesiredSpeed --------------------------------------------------
    M("cs-give0", "    give = *tol;", "    give = 1.0f;"),
    M("cs-clear", "if (!drivinglocation_is_clear(c->CurrentDrivingLocation)) {",
      "if (1) {"),
    M("cs-give", "            give = TD_SLOW_TOLERANCE;" + NL +
      "            s = trpoint_get_signpost(p);",
      "            s = trpoint_get_signpost(p);"),
    M("cs-most", "most = dist * TD_HAIRPIN_SPEED;", "most = dist;"),
    M("cs-take", "if (dist < TD_HAIRPIN_TAKE) {", "if (dist <= TD_HAIRPIN_TAKE) {"),
    M("cs-route", "signpost_get_new_route_point(s)," + NL +
      "                                          0, 0);",
      "signpost_get_new_route_point(s)," + NL +
      "                                          1, 0);"),
    M("cs-relaxed", "signpost_get_new_route_point(s)," + NL +
      "                                          0, 0);",
      "signpost_get_new_route_point(s)," + NL +
      "                                          0, 1);"),
    M("cs-pick", "                    < TD_HIGH_FIRST;",
      "                    <= TD_HIGH_FIRST;"),
    M("cs-pick-clear", "(drivinglocation_is_clear(l) ? -1",
      "(drivinglocation_is_clear(l) ? 100"),
    M("cs-n3", "if (a->PointsToDrive.NumPoints >= 3) {",
      "if (a->PointsToDrive.NumPoints > 3) {"),
    M("cs-n-unsigned", "if (a->PointsToDrive.NumPoints >= 3) {",
      "if ((uint8_t)a->PointsToDrive.NumPoints >= 3) {"),
    M("cs-first", "&a->PointsToDrive.Points[0];", "&a->PointsToDrive.Points[1];"),
    M("cs-mid", "&a->PointsToDrive.Points[n / 2];",
      "&a->PointsToDrive.Points[(n - 1) / 2];"),
    M("cs-last", "&a->PointsToDrive.Points[n - 1];",
      "&a->PointsToDrive.Points[n - 2];"),
    M("cs-in", "in.x = pm->x - p0->x;", "in.x = p0->x - pm->x;"),
    M("cs-in-y", "in.y = pm->y - p0->y;", "in.y = pm->y - p0->x;"),
    M("cs-out", "out.y = pn->y - pm->y;", "out.y = pm->y - pn->y;"),
    M("cs-out-x", "out.x = pn->x - pm->x;", "out.x = pn->x - p0->x;"),
    M("cs-norm-in", "        bNormalize2(&in, &in);" + NL, ""),
    M("cs-norm-out", "        bNormalize2(&out, &out);" + NL, ""),
    M("cs-bend", "if (in.x * out.x + in.y * out.y < TD_BEND_COS) {",
      "if (in.x * out.x + in.y * out.y <= TD_BEND_COS) {"),
    M("cs-bend-most", "            most = TD_BEND_SPEED;",
      "            most = min_s(most, TD_BEND_SPEED);"),
    M("cs-bend-give", "            most = TD_BEND_SPEED;" + NL +
      "            give = TD_SLOW_TOLERANCE;",
      "            most = TD_BEND_SPEED;"),
    M("cs-max", "    most = max_s(most, TD_LEAST_SPEED);" + NL, ""),
    M("cs-dls", "if (a->UseDrivingLineSpeed) {",
      "if (!a->UseDrivingLineSpeed) {"),
    M("cs-dls-speed", "        *speed = most;" + NL,
      "        *speed = TD_TOP_SPEED;" + NL),
    M("cs-dls-time", "        *time = 0.0f;" + NL + "        *tol = give;",
      "        *time = 1.0f;" + NL + "        *tol = give;"),
    M("cs-dls-tol", "        *tol = give;", "        *tol = 0.0f;"),
    M("cs-ds", "*speed = a->DesiredSpeed;", "*speed = most;"),
    M("cs-swap", "*time = a->TimeToGetToDesiredSpeed;" + NL +
      "        *tol = a->DesiredSpeedTolerance;",
      "*time = a->DesiredSpeedTolerance;" + NL +
      "        *tol = a->TimeToGetToDesiredSpeed;"),
    M("cs-min", "    *speed = min_s(*speed, most);" + NL, ""),
    M("sd", "d->PickLowNumberedRoutes = low;",
      "d->PickLowNumberedRoutes = low != 0;"),

    # -- the table --------------------------------------------------------------
    M("vt-dtor", "E(trafficdriver_destroy),", "E(aicarcontroller_destroy),"),
    M("vt-debug", "E(aicarcontroller_debug_display),",
      "E(aicarcontroller_find_where_i_am),"),
    M("vt-snap", "E(trafficdriver_do_snapshot),",
      "E(aicarcontroller_do_snapshot),"),
    M("vt-think", "E(trafficdriver_think),", "E(aicarcontroller_debug_display),"),
    M("vt-reset", "E(trafficdriver_just_reset),",
      "E(aicarcontroller_set_to_physics_mode),"),
    M("vt-routes", "E(trafficdriver_get_route_numbers_to_use),",
      "E(aicarcontroller_choose_new_action),"),
    M("vt-last", "E(aicarcontroller_generate_points_to_fulfill_action),",
      "E(aicarcontroller_choose_new_action),"),
]

EQUIVALENT = {
    "fallback": "every step replaces the action it deletes, so the action "
                "is never NULL after the cascade",
    "cs-bend-most": "max_s(most, 10) follows, so min_s(most, 10) and 10 "
                    "both come out at 10",
    "cs-dls-speed": "the most is never over 24.5865: the hairpin scan stops "
                    "short of 75 m, and 74.9999924 x 0.32782 is 24.586498",
    "cs-n-unsigned": "a DriveTarget has at most 20 points; past 127 the "
                     "mutant reads before the points, memory the two sides "
                     "do not share, and neither finds a bend there",
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
        todo, SOURCES, "trafficdriver_test",
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
