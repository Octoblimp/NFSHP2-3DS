#!/usr/bin/env python3
"""Cross-check 3DS Files/source/drivingchoice.c, the choices an AI car
makes about where to drive and the walk along the route that fills its
drive target (step 11b-2), and Race::GracePeriodIsActive in racecore.c,
against the retail image itself, run in mipsemu.

The model is the image. DrivingChoice's GetChoiceType (0x00241c00),
GetDrivingLine (0x00241c20), SetChoice with a type (0x00241cf8), with a
location (0x001cacc8) and with a choice (0x00245370), Clear (0x002453e0),
IsValid (0x00241d40), IsEqualTo (0x00241e30), IsEnoughRoom (0x00242b08),
FixupCarToExcludeFromCollisionPrediction (0x00243160),
GetPreferredSideOfCar (0x002432e8), FillUpDriveTarget (0x00243568),
AddToDriveTarget (0x002437e8), GetSpeedBackToLine (0x002438b0) and
ReduceCurrentL (0x00243988), the walk's AdvancePoint (0x00244588),
FuturePointList::Add (0x00244768), GetRoutePointsToUse (0x002447c0) and
the road-block list (0x00244c88), and Race::GracePeriodIsActive
(0x001492b0) run as shipped, over retail's own NearbyCarList::GetNearbyCar,
DrivingLocation's IsClear and AreWeInARelaxedSwitch,
GetCurrentCurvatureOfDrivingLine, TrackRoute::FindClosestPointAhead,
TrackRoutePoint's GetPosition and GetSignpost, Signpost's GetNewRoute and
GetNewRoutePoint, CalculateLookAheadDistance and DriveTarget's
AddPointToTarget and GetRouteAndRoutePoint. The harness
(tools/src/drivingchoice_test.c) runs the port over the same script, and
the two transcripts are diffed.

Three stubs, each of which prints a line, so the two sides must ask them
the same questions in the same order:
  AICarController::SignPostDecision (0x00191de0), which the port reaches
    through gAISignPostDecisionFn until step 11e, answers the script's
    take-or-not for the sign, and writes the script's line, if any, to the
    line it is handed;
  Car::GetRoutePoint (0x001332d8) answers the script's point for the car;
  Car::GetAmountOutOfBounds (0x00133308) answers the script's amount.
The port reaches the last two through the controller's vtable.

The cars are retail's at retail's offsets: the driver number, the car
class (CarTypeInfo 230), the driver's type (DriverInfo 8), the control
mode, the position, the body's x axis and the speed, and each car's
controller with its own location, its choice and its current action's
type (AIAction 588) or none. The routes are filed in TheTrackRouteManager
under their numbers, and the signs in SignpostArray.

A float prints as its bits, a NaN as "nan", and a pointer by what it is:
c3 a car, k3 its controller, L3 its location, ch3 its choice, e5 the
list's sixth entry, R1 a route, R1:17 a point, S4 the fifth sign, loc the
location, pat the 0xa5 fill.

    python tools/drivingchoice_check.py
    python tools/drivingchoice_check.py --mutate [--only a,b]
    python tools/drivingchoice_check.py --dump out/drivingchoice
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

HARNESS = "tools/src/drivingchoice_test.c"
DCC = "3DS Files/source/drivingchoice.c"
RCC = "3DS Files/source/racecore.c"
SOURCES = [HARNESS, DCC, RCC] + ["3DS Files/source/" + f for f in (
    "nearbycar.c", "drivinglocation.c", "drivetarget.c", "car.c",
    "carstate.c", "carinfo.c", "cartypeinfo.c", "langtab.c", "drivetrain.c",
    "engine.c", "wheel.c", "suspension.c", "steering.c", "rigidbody.c",
    "table.c", "trackroute.c", "trackpath.c", "quickspline.c", "bchunk.c",
    "world.c", "graph.c", "race.c", "copmanager.c", "replay.c", "p32.c",
    "bmem.c", "vtable.c", "emath.c", "bmatrix.c", "bvector.c", "bmath.c",
    "bmathtab.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
GET_CHOICE_TYPE = 0x00241c00
GET_DRIVING_LINE = 0x00241c20
SET_CHOICE = 0x00241cf8
SET_CHOICE_LOC = 0x001cacc8
SET_CHOICE_CHOICE = 0x00245370
CLEAR = 0x002453e0
IS_VALID = 0x00241d40
IS_EQUAL = 0x00241e30
ENOUGH_ROOM = 0x00242b08
FIXUP = 0x00243160
PREFERRED = 0x002432e8
FILL_UP = 0x00243568
ADD_TO_TARGET = 0x002437e8
SPEED_BACK = 0x002438b0
REDUCE = 0x00243988
ADVANCE = 0x00244588
FPL_ADD = 0x00244768
POINTS_TO_USE = 0x002447c0
UP_TO = 0x00244c88
GRACE = 0x001492b0

SIGN_DECISION = 0x00191de0
GET_ROUTE_POINT = 0x001332d8
GET_OOB = 0x00133308

ROUTE_TABLE = 0x00314438 + 16     # TheTrackRouteManager.pTrackRoutes
NUM_ROUTE_SLOTS = 100

GLOBALS = {
    "TIMER": GP - 19576,          # WorldTimer
    "RACE": GP - 22272,           # pCurrentRace
    "GRACE": GP - 22256,          # StartOfRaceGracePeriod
    "GAP": GP - 22252,            # TimeBetweenCarsForGracePeriodExit
    "WILLIAMS": GP - 15128,       # WilliamsAITuningMode
    "SECS": GP - 20328,           # AIDriverSecondsToLookAhead
    "DEF": GP - 20324,            # AIDriverDefaultLookAhead
    "SIGNS": GP - 18376,          # SignpostArray
    "NSIGNS": GP - 18372,         # NumSignposts
}

CARS = 0x01010000
CAR_STRIDE = 0x1000
NCARS = 16
CTRLS = 0x01020000
CTRL_STRIDE = 0x400
CHOICES = 0x01030000
ACTIONS = 0x01031000
ACTION_STRIDE = 608
LOCS = 0x01034000
CTIS = 0x01040000
CTI_STRIDE = 0x400
DRIVERS = 0x01048000
DRIVER_STRIDE = 32
LIST = 0x01090000
LOC = 0x01090c00
CHOICE = 0x01091000
OTHER = 0x01091010
FPL = 0x01091400
LPTR = 0x01091800
WALK = 0x01091900
TARGET = 0x01092000
RACE = 0x01093000
SIGNS = 0x01094000
NSIGNS = 32
SIGN_SIZE = 12
ROUTES = 0x01100000
ROUTE_STRIDE = 0x20000
NROUTES = 6

# The car, at retail's offsets.
C_DN = 10
C_CTI = 12
C_DRIVER = 20
C_CTL = 32
C_CTRL = 40
C_POS = 96
C_BM = 144
C_VMAG = 964
CTI_CLASS = 230
DRV_TYPE = 8
K_LOC = 504
K_CHOICE = 508
K_EXCLUDE = 516
K_ACTION = 532
A_TYPE = 588
RACE_START = 12

NC_SIZE = 28
LIST_ARRAY = 8
LIST_MAX = 16
LIST_HL = 456
LIST_HD = 460
FP_SIZE = 20
FPL_MAX = 20
FPL_BYTES = 4 + FP_SIZE * FPL_MAX
TARGET_BYTES = 528

RT_HEADER = 1064
RT_POINT = 112
LINES = 21

PATTERN = 0xa5
PAT32 = 0xa5a5a5a5

TRAFFIC_DRIVER = 3
RACER = 2
TRAFFIC_CONTROL = 3


def fb(v):
    if isinstance(v, int):
        return v & M32
    return f_to_bits(v)


def h(v):
    return "%08x" % fb(v)


def f32(v):
    return struct.unpack("<f", struct.pack("<f", v))[0]


def fx(w):
    """A float's bits, with every NaN the one "nan"."""
    w &= M32
    if (w & 0x7f800000) == 0x7f800000 and (w & 0x7fffff):
        return "nan"
    return "%08x" % w


def s8(v):
    v &= 0xff
    return v - 0x100 if v & 0x80 else v


def s16(v):
    v &= 0xffff
    return v - 0x10000 if v & 0x8000 else v


def car_at(k):
    return CARS + CAR_STRIDE * k


def route_at(k):
    return ROUTES + ROUTE_STRIDE * k


# ============================================================ the scenarios
#
# Set up, and not echoed:
# U k n rn type f0..f20  route k's header: n points, number rn, its Type and
#                        the 21 lines' flags; filed under rn if 0 <= rn < 100
# P w0 .. w27            the route's next point
# K i rn j               sign i: the route numbered rn, its point j
# C k w0 .. w16          car k (CAR_FIELDS), its controller, choice and
#                        action; the car it excludes is set to the fill
#
# Echoed:
# G name word            a global (GLOBALS)
# Q i take line          SignPostDecision for sign i: its answer, and the
#                        line it writes (-1 none)
# R t                    the race's StartTime
# N me n hl hd           the list's car (-1 none), count and half sizes
# E i px py vx vy L D k  the list's entry i
# D r j line t           the location set by hand (r, j -1 for NULL)
# T tt len               the target emptied: TType tt, Length len,
#                        LastPointToScore -1, the rest 0
# Y x y z rn j line sp   a point put on the target by hand
# X type k extra         the choice by hand (k -1 NULL)
# O type k extra         the other choice by hand
# W r j pn line off x    the walker: route r's point j, its number pn, the
#                        line, the offset and the crossed flag
# F                      the future point list filled with 0xa5, count 0
#
# The calls:
# a line                 GetChoiceType
# b type k               GetDrivingLine for car k
# c type k extra         SetChoice
# d                      SetChoice from the location
# e                      SetChoice from the other choice
# f                      Clear
# g                      IsValid, with the location and the list
# h                      IsEqualTo the other choice
# i e                    IsEnoughRoom beside entry e
# j k check              FixupCarToExcludeFromCollisionPrediction, car k
# k e                    GetPreferredSideOfCar of entry e
# m rn j line off x      FuturePointList::Add
# n                      AdvancePoint of the walker, for the list's car
# o                      GetRoutePointsToUse, *L filled with 0xa5 first
# p r j                  the road-block list, up to route r's point j
# q m                    GetSpeedBackToLine
# r l m r j line a hw in ReduceCurrentL
# s l e                  AddToDriveTarget of the list's point e
# t m in [z]             FillUpDriveTarget; z's bits make the location,
#                        the target and the list NULL (1, 2, 4)
# u k                    GracePeriodIsActive for car k
#
# What the image would read from wherever a NULL or a stray pointer lands
# is not scripted: a side-of-car choice always has a car, IsEnoughRoom's
# entry and a fix-up's car are on the list or out of bounds by no less than
# -0.001, a walk's routes are filed under their own numbers, the signs only
# lead on to a later route, so no walk goes round for ever, a road-block
# list ends on the location's route, and the walks start from a location
# that is set and a line from 0 to 20 (drivingchoice.c names each of the
# image's ways the other side of these).

CAR_FIELDS = (
    "px", "py", "pz", "bx", "by", "vmag", "dn", "cls", "dtype", "ctl",
    "oob", "rpr", "rpj", "ct", "cc", "cx", "act")
CAR_FLOATS = ("px", "py", "pz", "bx", "by", "vmag", "oob")


def car_op(k, v):
    out = []
    for f in CAR_FIELDS:
        if f in CAR_FLOATS:
            out.append(h(f32(v[f])))
        else:
            out.append("%d" % int(v[f]))
    return "C %d %s" % (k, " ".join(out))


def lay(rnd, k, n, rn, rtype=0, signs=None, x=None, y=None, hd=None,
        turn=None, flags=None, smooth=False):
    """Route k: its header, its points and, for placing things beside it,
    each point's position, direction, widths and line offsets. A smooth
    route's points are 10 m apart, it turns by exactly `turn` at each and
    every line is on its centre, so its curvature is sin(6 turn)."""
    signs = signs or {}
    if x is None:
        x = rnd.uniform(-200.0, 200.0)
    if y is None:
        y = rnd.uniform(-200.0, 200.0)
    if hd is None:
        hd = rnd.uniform(-math.pi, math.pi)
    if turn is None:
        turn = rnd.choice((0.0, 0.03, -0.03, 0.15, -0.15,
                           rnd.uniform(-0.3, 0.3)))
    if flags is None:
        flags = [rnd.choice((0, 1, 2, 3, 0, 1, 4, 0x101))
                 for _ in range(LINES)]
    pos = []
    for i in range(n):
        pos.append((f32(x), f32(y)))
        if smooth:
            s = 10.0
            hd += turn
        else:
            s = rnd.uniform(6.0, 18.0)
            hd += turn + rnd.uniform(-0.04, 0.04)
        x += s * math.cos(hd)
        y += s * math.sin(hd)
    out = ["U %d %d %d %d %s" % (k, n, rn, rtype,
                                 " ".join("%x" % f for f in flags))]
    pts = []
    for i in range(n):
        px, py = pos[i]
        if i + 1 < n:
            nx, ny = pos[i + 1]
        else:
            nx = px + (px - pos[i - 1][0])
            ny = py + (py - pos[i - 1][1])
        dx, dy = nx - px, ny - py
        ln = math.hypot(dx, dy) or 1.0
        offs = [0] * LINES if smooth else [
            rnd.choice((0, rnd.randint(-1024, 1024), rnd.randint(-300, 300)))
            for _ in range(LINES)]
        if smooth:
            lw = rw = f32(25.0)
        else:
            lw = f32(rnd.uniform(4.0, 16.0))
            rw = f32(rnd.uniform(4.0, 16.0))
        bits = (rnd.getrandbits(32) & ~0xff) | signs.get(i, 0xff)
        raw = struct.pack("<12f", px, py, rnd.uniform(-5.0, 5.0),
                          f32(dx / ln), f32(dy / ln), f32(ln), lw, rw,
                          0.0, 0.0, rnd.uniform(0.0, 3000.0), 0.0)[:44]
        raw += struct.pack("<I", bits)
        raw += struct.pack("<21h", *offs)
        raw += bytes(rnd.randrange(256) for _ in range(LINES)) + bytes([k])
        assert len(raw) == RT_POINT
        out.append("P " + " ".join("%08x" % v for v in
                                   struct.unpack("<28I", raw)))
        pts.append(dict(x=px, y=py, dx=f32(dx / ln), dy=f32(dy / ln),
                        lw=lw, rw=rw, offs=offs, rn=rn))
    return out, pts


def off_of(p, line):
    return p["offs"][line] / 256.0


def beside(p, lat, along=0.0):
    """Where `lat` to the right of point p and `along` past it is."""
    return (p["x"] + lat * p["dy"] + along * p["dx"],
            p["y"] - lat * p["dx"] + along * p["dy"])


class World(object):
    """A scenario's routes, signs and cars, as ops."""

    def __init__(self, rnd):
        self.rnd = rnd
        self.ops = []
        self.pts = {}
        self.rn = {}
        self.cars = {}
        self.nsign = 0
        self.sign_points = []

    def route(self, k, n, rn, rtype=0, signs=None, **kw):
        ops, pts = lay(self.rnd, k, n, rn, rtype, signs, **kw)
        self.ops += ops
        self.pts[k] = pts
        self.rn[k] = rn
        return pts

    def sign(self, k2, j2):
        i = self.nsign
        self.nsign += 1
        self.ops.append("K %d %d %d" % (i, self.rn[k2], j2))
        return i

    def car(self, k, **kw):
        rnd = self.rnd
        a = rnd.uniform(-math.pi, math.pi)
        v = dict(px=rnd.uniform(-150.0, 150.0),
                 py=rnd.uniform(-150.0, 150.0),
                 pz=rnd.uniform(-3.0, 3.0), bx=math.cos(a), by=math.sin(a),
                 vmag=rnd.choice((0.0, 10.0, 26.8, rnd.uniform(0.0, 60.0),
                                  rnd.uniform(20.0, 40.0))),
                 dn=rnd.choice((0, 1, 5, 100, 101, 120, 149, 150, -3)),
                 cls=rnd.randint(0, 8),
                 dtype=rnd.choice((0, 1, 2, 2, 3, 3, 4)),
                 ctl=rnd.choice((0, 1, 2, 3, 3, 4)),
                 oob=rnd.choice((0.0, -0.001, -0.0011, -0.5, -4.0, 1.0)),
                 rpr=-1, rpj=-1, ct=0, cc=-1, cx=0,
                 act=rnd.choice((-1, 0, 5, 6, 6, 11)))
        v.update(kw)
        self.cars[k] = v
        self.ops.append(car_op(k, v))
        return v


def tgt_point(w, k, j, lat, line, sp=0.0, along=0.0):
    p = w.pts[k][j]
    x, y = beside(p, lat, along)
    return "Y %s %s %s %d %d %d %s" % (h(f32(x)), h(f32(y)),
                                        h(f32(w.rnd.uniform(-2.0, 2.0))),
                                        w.rn[k], j, line, h(f32(sp)))


def s_small(rnd):
    """The small methods, on every type and line worth trying."""
    w = World(rnd)
    ops = w.ops
    for k in range(4):
        w.car(k, cls=rnd.choice((0, 3, 8, -1, 127, -128)))
    for line in list(range(-5, 25)) + [0x7fffffff, -0x80000000, -7, 41]:
        ops.append("a %d" % line)
    for t in range(-2, 9):
        for k in range(4):
            ops.append("b %d %d" % (t, k))
    for t in list(range(-1, 9)) + [0x7fffffff]:
        for k in (-1, 0, 2):
            for x in (0, 1, 2):
                ops.append("X %d %d %d" % (rnd.choice((0, 1, 5, 6, 9)),
                                           rnd.choice((-1, 1, 3)),
                                           rnd.choice((0, 1, 7))))
                ops.append("c %d %d %d" % (t, k, x))
    for line in (0, 1, 2, 3, 19, 20, -1, -2, -3, 7, 0x7fffffff, -0x80000000):
        ops.append("X %d %d %d" % (rnd.choice((0, 1, 5, 6)), rnd.choice((-1,
                                                                         1)),
                                   rnd.choice((0, 1))))
        ops.append("D -1 -1 %d 00000000" % line)
        ops.append("d")
    for _ in range(40):
        ops.append("X %d %d %d" % (rnd.choice((0, 1, 2, 5, 6)),
                                   rnd.choice((-1, 0, 1)), rnd.choice((0, 1))))
        ops.append("O %d %d %d" % (rnd.randrange(-1, 9),
                                   rnd.choice((-1, 0, 1, 2)),
                                   rnd.choice((0, 1, 3))))
        ops.append(rnd.choice(("e", "f", "h", "h")))
    for t in range(-1, 9):
        for t2 in (t, t + 1, 5, 6):
            for k, k2 in ((0, 0), (0, 1), (-1, -1), (1, -1)):
                ops.append("X %d %d 0" % (t, k))
                ops.append("O %d %d 1" % (t2, k2))
                ops.append("h")
    return ops


def s_valid(rnd):
    """IsValid on a line, on a side and on neither, over routes of every
    kind of number."""
    w = World(rnd)
    ops = w.ops
    rns = (rnd.randrange(0, 50), rnd.choice((0, 49)),
           rnd.randrange(50, 70), rnd.choice((50, 69)),
           rnd.choice((70, rnd.randrange(70, 100))),
           rnd.choice((-3, 100, 120)))
    for k in range(NROUTES):
        w.route(k, 8, rns[k], rtype=rnd.choice((0, 1)))
    for k in range(8):
        w.car(k)
    ops.append("N 0 5 %s %s" % (h(f32(2.2)), h(f32(0.9))))
    for i in range(5):
        ops.append("E %d %s %s 0 0 %s %s %d" % (
            i, h(f32(rnd.uniform(-5.0, 5.0))), h(f32(rnd.uniform(-60, 60))),
            h(f32(2.0)), h(f32(1.0)), i + 1))
    for _ in range(120):
        r = rnd.choice((0, 1, 2, 3, 4, 5, -1))
        ops.append("D %d %d %d 00000000" % (r, 0 if r >= 0 else -1,
                                            rnd.randrange(LINES)))
        me = rnd.randrange(8)
        ops.append("N %d %d %s %s" % (me, rnd.choice((5, 3, 0)),
                                      h(f32(2.2)), h(f32(0.9))))
        t = rnd.choice((0, 1, 2, 3, 4, 5, 6, 7, -1, 1, 2))
        k = rnd.choice((-1, 0, 1, 3, 5, 6, 7))
        if t in (5, 6) and k < 0:
            k = 1
        ops.append("X %d %d 0" % (t, k))
        ops.append("g")
    return ops


def place_list(w, me, others, ys=None):
    """The list: car me, and an entry for each of `others`."""
    rnd = w.rnd
    ops = ["N %d %d %s %s" % (me, len(others),
                              h(f32(rnd.choice((2.2, 2.5, rnd.uniform(1.5,
                                                                     3.0))))),
                              h(f32(rnd.uniform(0.8, 1.2))))]
    for i, k in enumerate(others):
        y = ys[i] if ys else rnd.choice((rnd.uniform(-40.0, 40.0), 55.0,
                                         rnd.uniform(50.0, 90.0)))
        ops.append("E %d %s %s %s %s %s %s %d" % (
            i, h(f32(rnd.uniform(-6.0, 6.0))), h(f32(y)),
            h(f32(rnd.uniform(-5.0, 5.0))), h(f32(rnd.uniform(-5.0, 5.0))),
            h(f32(rnd.uniform(1.0, 3.0))), h(f32(rnd.uniform(0.8, 1.5))), k))
    return ops


def s_room(rnd):
    """IsEnoughRoom, the fix-up and the preferred side, beside cars on and
    off the road, facing either way, wanting either side."""
    w = World(rnd)
    ops = w.ops
    n0 = 40
    pts = w.route(0, n0, rnd.randrange(50),
                  turn=rnd.choice((0.0, 0.2, -0.2, 0.08, -0.25)))
    w.route(1, 20, rnd.randrange(50, 70), rtype=1)
    ncar = 8
    j0 = rnd.randrange(0, 10)
    line = rnd.randrange(LINES)
    me_lat = off_of(pts[j0], line) + rnd.choice((0.0, 0.5, -0.9, 3.0))
    hd = math.atan2(pts[j0]["dy"], pts[j0]["dx"])
    mx, my = beside(pts[j0], me_lat, 0.5)
    w.car(0, px=mx, py=my, bx=math.cos(hd), by=math.sin(hd),
          dtype=rnd.choice((2, 3, 0)), rpr=0, rpj=j0)
    for k in range(1, ncar):
        j = min(n0 - 2, j0 + rnd.randrange(0, 20))
        lat = rnd.choice((off_of(pts[j], line), off_of(pts[j], line) + 0.6,
                          rnd.uniform(-12.0, 12.0), pts[j]["rw"] - 2.0,
                          -pts[j]["lw"] + 2.0))
        x, y = beside(pts[j], lat, -0.5)
        back = rnd.random() < 0.4
        a = hd + (math.pi if back else 0.0) + rnd.uniform(-0.3, 0.3)
        w.car(k, px=x, py=y, bx=math.cos(a), by=math.sin(a),
              rpr=0, rpj=rnd.choice((j, j, max(0, j - 1))),
              dtype=rnd.choice((3, 3, 2, 0)),
              ct=rnd.choice((5, 6, 1, 0)), cc=rnd.choice((0, 0, 2, -1)),
              act=rnd.choice((6, 6, 5, -1, 11)))
        v = w.cars[k]
        if v["ct"] in (5, 6) and v["cc"] < 0:
            v["cc"] = 0
            ops[-1] = car_op(k, v)
    others = list(range(1, ncar))
    rnd.shuffle(others)
    ops += place_list(w, 0, others[:6])
    ops.append("D 0 %d %d 00000000" % (j0, line))
    for _ in range(50):
        e = rnd.randrange(6)
        k = others[e]
        t = rnd.choice((5, 6, 5, 6, 1, 2, 0, 7))
        ops.append("X %d %d %d" % (t, k, rnd.choice((0, 1))))
        ops.append("i %d" % e)
        ops.append("k %d" % e)
        ops.append("j 0 %d" % rnd.choice((1, 1, 0, 2)))
        if rnd.random() < 0.3:
            # Off the list: only where its amount out of bounds stops the
            # question before the entry is read.
            ok = others[6]
            v = w.cars[ok]
            v["oob"] = rnd.choice((0.0, -0.001, 1.0))
            ops.append(car_op(ok, v))
            ops.append("X %d %d 0" % (rnd.choice((5, 6)), ok))
            ops.append("j 0 1")
        if rnd.random() < 0.3:
            v = dict(w.cars[k])
            v["oob"] = rnd.choice((0.0, -0.001, -0.0011, -0.5, -4.0, 1.0))
            v["ct"] = rnd.choice((5, 6))
            v["cc"] = 0
            v["act"] = rnd.choice((6, 5, -1))
            v["dtype"] = rnd.choice((3, 2))
            w.cars[k] = v
            ops.append(car_op(k, v))
    # The bend: both on the line, the other well ahead.
    for _ in range(12):
        j = min(n0 - 2, j0 + rnd.randrange(3, 15))
        k = others[0]
        x, y = beside(pts[j], off_of(pts[j], line)
                      + rnd.choice((0.0, 0.9, -0.5, 1.1)), -0.5)
        v = dict(w.cars[k], px=x, py=y, oob=0.0)
        w.cars[k] = v
        ops.append(car_op(k, v))
        ops.append("E 0 %s %s 0 0 %s %s %d" % (
            h(f32(0.0)), h(f32(rnd.choice((49.0, 50.0, 51.0, 80.0)))),
            h(f32(2.0)), h(f32(1.0)), k))
        me = dict(w.cars[0], dtype=rnd.choice((2, 2, 3)))
        w.cars[0] = me
        ops.append(car_op(0, me))
        ops.append("X 5 %d 0" % k)
        ops.append("k 0")
    return ops


def walk_world(rnd, w, nsigns=4):
    """Five routes, three racing and two traffic, each starting near the
    others, and the signs leading only on to a route later in `order`."""
    rns = rnd.sample(range(0, 50), 3) + rnd.sample(range(50, 70), 2)
    sizes = (40, 30, 30, 25, 20)
    order = [0, 3, 1, 4, 2]
    plan = {}
    for _ in range(nsigns):
        a = rnd.randrange(4)
        k = order[a]
        plan[(k, rnd.randrange(1, sizes[k] - 2))] = order[
            rnd.randrange(a + 1, 5)]
    plan = sorted(plan.items())
    signs = {}
    for i, ((k, j), b) in enumerate(plan):
        signs.setdefault(k, {})[j] = i
    x = rnd.uniform(-100.0, 100.0)
    y = rnd.uniform(-100.0, 100.0)
    for k in range(5):
        w.route(k, sizes[k], rns[k], rtype=0 if k < 3 else 1,
                signs=signs.get(k), x=x + rnd.uniform(-30.0, 30.0),
                y=y + rnd.uniform(-30.0, 30.0))
    w.sign_points = [kj for kj, b in plan]
    for i, ((k, j), b) in enumerate(plan):
        got = w.sign(b, rnd.randrange(0, sizes[b] - 5))
        if got != i:
            raise SystemExit("sign %d filed as %d" % (i, got))
    return sizes


def near_sign(rnd, w, sizes):
    """A route and a point on it: half the time a few points short of a
    sign, so the walk from there crosses it."""
    if w.sign_points and rnd.random() < 0.6:
        k, j = rnd.choice(w.sign_points)
        return k, max(0, j - rnd.randrange(0, 4))
    k = rnd.randrange(5)
    return k, rnd.randrange(sizes[k] - 1)


def decide(rnd, w):
    ops = []
    for i in range(w.nsign):
        ops.append("Q %d %d %d" % (i, rnd.choice((0, 1, 1)),
                                   rnd.choice((-1, -1, rnd.randrange(LINES)))))
    return ops


def target_on(rnd, w, sizes, k, j, n, line):
    """A target of n points along route k up to its point j."""
    ops = ["T %d %s" % (rnd.randrange(64), h(f32(rnd.uniform(0.0, 80.0))))]
    for i in range(n):
        jj = max(0, j - (n - 1 - i))
        ops.append(tgt_point(w, k, jj, rnd.uniform(-4.0, 4.0), line,
                             sp=rnd.uniform(0.0, 40.0),
                             along=rnd.uniform(-2.0, 2.0)))
    return ops


def s_walk(rnd):
    """AdvancePoint, GetRoutePointsToUse and the road-block list, across
    signs taken and not, for racers and the rest."""
    w = World(rnd)
    ops = w.ops
    sizes = walk_world(rnd, w, nsigns=rnd.randint(4, 10))
    j0 = rnd.randrange(0, 12)
    line = rnd.randrange(LINES)
    p = w.pts[0][j0]
    mx, my = beside(p, off_of(p, line) + rnd.uniform(-3.0, 3.0), 1.0)
    w.car(0, px=mx, py=my, dtype=rnd.choice((2, 2, 3, 0)),
          vmag=rnd.choice((0.0, 15.0, 30.0, 45.0)))
    for k in range(1, 4):
        w.car(k)
    ops += place_list(w, 0, [1, 2, 3])
    ops += decide(rnd, w)
    ops.append("D 0 %d %d 00000000" % (j0, line))
    # The walker, step by step.
    for _ in range(16):
        k, j = near_sign(rnd, w, sizes)
        ops.append("W %d %d %d %d %s %d" % (
            k, j, rnd.choice((j, j, j - 1, sizes[k] - 1)),
            rnd.randrange(LINES), h(f32(rnd.uniform(-2.0, 2.0))),
            rnd.choice((0, 1))))
        for _ in range(rnd.randint(1, 8)):
            ops.append("n")
        if rnd.random() < 0.3:
            ops += decide(rnd, w)
    # The walk to use, from an empty target and from targets ending on
    # every route.
    for _ in range(14):
        if rnd.random() < 0.3:
            ops.append("T 0 00000000")
        else:
            k, j = near_sign(rnd, w, sizes)
            ops += target_on(rnd, w, sizes, k, j, rnd.randint(1, 6),
                             rnd.randrange(LINES))
        dtype = rnd.choice((2, 2, 3, 0))
        if ops[-1].startswith("Y") and rnd.random() < 0.25:
            # A racer's target ending on a traffic route, its last point
            # with no number: the walk is from the location, and where the
            # target ends is measured across the location's point.
            kt = rnd.choice((3, 4))
            f = tgt_point(w, kt, rnd.randrange(sizes[kt]),
                          rnd.uniform(-4.0, 4.0), rnd.randrange(LINES),
                          sp=rnd.uniform(0.0, 40.0)).split()
            f[5] = "-1"
            ops.append(" ".join(f))
            dtype = 2
        v = dict(w.cars[0], dtype=dtype,
                 vmag=rnd.choice((0.0, 5.0, 15.0, 30.0, 60.0)))
        w.cars[0] = v
        ops.append(car_op(0, v))
        ops.append("G SECS %s" % h(f32(rnd.choice((2.0, 0.5, 4.0, 10.0)))))
        ops.append("G DEF %s" % h(f32(rnd.choice((20.0, 5.0, 60.0,
                                                   400.0)))))
        kl, jl = near_sign(rnd, w, sizes)
        ops.append("D %d %d %d 00000000" % (kl, jl, rnd.randrange(LINES)))
        ops.append("o")
        if rnd.random() < 0.4:
            ops += decide(rnd, w)
    # From a location on another route.
    for _ in range(6):
        k = rnd.randrange(5)
        jl = rnd.randrange(sizes[k] - 1)
        ops.append("D %d %d %d 00000000" % (k, jl, rnd.randrange(LINES)))
        ops.append("T 0 00000000")
        ops.append("o")
        for jj in (jl, jl + 1, jl - 1, sizes[k] - 1, min(sizes[k] - 1,
                                                         jl + 25)):
            if 0 <= jj < sizes[k]:
                ops.append("p %d %d" % (k, jj))
    # No location: no point, nothing walked, *L as it was.
    ops.append("D -1 -1 3 00000000")
    ops.append("T 0 00000000")
    ops.append("o")
    # The list by hand.
    ops.append("F")
    for _ in range(rnd.randint(1, 6)):
        ops.append("m %d %d %d %s %d" % (
            rnd.randrange(100), rnd.randrange(30), rnd.randrange(LINES),
            h(f32(rnd.uniform(-3.0, 3.0))), rnd.choice((0, 1, 2))))
    return ops


def s_fill(rnd):
    """FillUpDriveTarget, for each way of moving with respect to the line,
    inside the edges or not, the tuning mode on and off."""
    w = World(rnd)
    ops = w.ops
    sizes = walk_world(rnd, w, nsigns=rnd.randint(3, 8))
    j0 = rnd.randrange(0, 15)
    line = rnd.randrange(LINES)
    p = w.pts[0][j0]
    mx, my = beside(p, off_of(p, line) + rnd.uniform(-4.0, 4.0), 1.0)
    w.car(0, px=mx, py=my, dtype=rnd.choice((2, 3, 0)),
          vmag=rnd.choice((10.0, 28.0, 35.0)), dn=rnd.choice((0, 101, 120)),
          ctl=rnd.choice((0, 3, 1)))
    for k in range(1, 4):
        w.car(k)
    ops += place_list(w, 0, [1, 2, 3])
    ops += decide(rnd, w)
    ops.append("R %08x" % rnd.choice((0, 40000, 100000)))
    for _ in range(16):
        ops.append("G TIMER %08x" % rnd.choice((0, 30000, 48000, 60000,
                                                 200000)))
        ops.append("G WILLIAMS %08x" % rnd.choice((0, 0, 0, 1)))
        jl = rnd.randrange(sizes[0] - 2)
        ops.append("D 0 %d %d %08x" % (jl, rnd.randrange(LINES),
                                       rnd.choice((0, 30000, 50000))))
        if rnd.random() < 0.3:
            ops.append("T %d 00000000" % rnd.randrange(64))
        else:
            k, j = near_sign(rnd, w, sizes)
            if rnd.random() < 0.4:
                k, j = 0, min(sizes[0] - 2, jl + rnd.randrange(0, 4))
            ops += target_on(rnd, w, sizes, k, j,
                             rnd.choice((1, 2, 4, 8, 19, 20)),
                             rnd.randrange(LINES))
        v = dict(w.cars[0], dtype=rnd.choice((2, 3, 0)),
                 vmag=rnd.choice((10.0, 28.0, 35.0, 60.0)),
                 ctl=rnd.choice((0, 0, 3)))
        w.cars[0] = v
        ops.append(car_op(0, v))
        ops.append("t %d %d" % (rnd.choice((0, 0, 1, 2, 3, 4)),
                                rnd.choice((0, 1))))
        if rnd.random() < 0.3:
            ops += decide(rnd, w)
    # Towards the line at no speed, the tuning mode off and every sign
    # taken: past a sign the speed is 0.25 at the most, and no less.
    ops.append("G WILLIAMS 00000000")
    ops.append("G TIMER %08x" % 200000)
    for i in range(w.nsign):
        ops.append("Q %d 1 -1" % i)
    for _ in range(10):
        ops.append("D 0 %d %d 00000000" % (rnd.randrange(sizes[0] - 2),
                                           rnd.randrange(LINES)))
        k, j = near_sign(rnd, w, sizes)
        ops += target_on(rnd, w, sizes, k, j, rnd.choice((1, 2, 4)),
                         rnd.randrange(LINES))
        v = dict(w.cars[0], dtype=rnd.choice((2, 0)), vmag=10.0, ctl=0)
        w.cars[0] = v
        ops.append(car_op(0, v))
        ops.append("t 0 %d" % rnd.randrange(2))
    # No location, no target, no list: nothing done.
    ops.append("D -1 -1 3 00000000")
    ops.append("T 7 00000000")
    ops.append("t 0 0")
    # A NULL location, target or list: nothing done either.
    ops.append("D 0 2 %d 00000000" % line)
    ops.append(car_op(0, w.cars[0]))
    for z in (1, 2, 4, 3, 6, 5, 7):
        ops.append("t 0 %d %d" % (rnd.randrange(2), z))
    # AddToDriveTarget on its own, of what the walk found.
    ops.append("D 0 2 %d 00000000" % line)
    ops.append("T 0 00000000")
    ops.append("o")
    for _ in range(6):
        ops.append("s %s %d" % (h(f32(rnd.uniform(-5.0, 5.0))),
                                rnd.randrange(2)))
    return ops


def s_bend(rnd, c, sgn):
    """GetPreferredSideOfCar on a smooth bend of curvature c (0.12 is the
    bend's), turning sgn's way and wide
    enough that no side is ever blocked: each car either side of 1 m off
    the line, a traffic car either side of 5 m, and the other car past the
    route's last point, where no point is ahead of it."""
    w = World(rnd)
    ops = w.ops
    n0 = 40
    pts = w.route(0, n0, rnd.randrange(50), turn=sgn * math.asin(c) / 6.0,
                  smooth=True)
    j0 = rnd.randrange(0, 8)
    line = rnd.randrange(LINES)
    w.car(0, oob=0.0)
    w.car(1, oob=0.0)
    ops += place_list(w, 0, [1])
    for _ in range(60):
        case = rnd.choice(("bend", "bend", "traffic", "end"))
        if case == "end":
            # The location two or three short of the end: what is measured
            # across its point and across the next differ.
            jl = n0 - rnd.choice((2, 3))
            my_lat = rnd.choice((0.0, 0.5, -0.5, 2.0, -2.0))
            ox, oy = beside(pts[n0 - 1], rnd.uniform(-6.0, 6.0),
                            rnd.uniform(1.0, 6.0))
            dtype = rnd.choice((2, 3))
        else:
            jl = j0
            j = min(n0 - 2, j0 + rnd.randrange(2, 15))
            if case == "bend":
                my_lat = rnd.choice((0.0, 0.5, -0.5, 0.9, -0.9, 1.5, -1.5))
                o_lat = rnd.choice((0.0, 0.6, -0.6, 0.95, -0.95, 1.2, -1.2))
                dtype = rnd.choice((2, 0))
            else:
                my_lat = rnd.choice((0.0, 2.0, -3.0, -7.0))
                o_lat = rnd.choice((0.0, 4.5, 5.5, 5.9, 6.5, -5.5, -6.5))
                dtype = 3
            ox, oy = beside(pts[j], o_lat, -0.5)
        ops.append("D 0 %d %d 00000000" % (jl, line))
        mx, my = beside(pts[jl], my_lat, 0.5)
        me = dict(w.cars[0], px=mx, py=my, dtype=dtype)
        other = dict(w.cars[1], px=ox, py=oy)
        w.cars[0], w.cars[1] = me, other
        ops.append(car_op(0, me))
        ops.append(car_op(1, other))
        ops.append("E 0 %s %s 0 0 %s %s 1" % (
            h(f32(rnd.uniform(-2.0, 2.0))),
            h(f32(rnd.choice((45.0, 49.9, 50.5, 80.0)))),
            h(f32(rnd.choice((1.0, 2.0)))), h(f32(1.0))))
        ops.append("k 0")
    return ops


def s_speed(rnd):
    """GetSpeedBackToLine either side of 60 and 66 mph, in the grace period
    and out, relaxed or not; and the grace period on its own."""
    w = World(rnd)
    ops = w.ops
    w.route(0, 20, 3)
    for k in range(4):
        w.car(k)
    ops.append("R %08x" % 1000)
    for _ in range(60):
        v = dict(w.cars[0],
                 vmag=rnd.choice((26.8216362, f32(26.8216362) + 1e-5, 27.0,
                                  29.5038013, 29.51, 40.0, 0.0, 10.0)),
                 ctl=rnd.choice((0, 1, 3, 4)),
                 dn=rnd.choice((0, 100, 101, 102, 125, 149, 150, -5)))
        w.cars[0] = v
        ops.append(car_op(0, v))
        ops.append("N 0 0 00000000 00000000")
        ops.append("G TIMER %08x" % rnd.choice((
            1000, 49000, 49001, 49004, 61000, 1000 + 4 * 12000 - 4,
            rnd.randrange(0, 300000), 0x7fffffff, 0x80000000, 0)))
        ops.append("D 0 %d %d %08x" % (rnd.randrange(20), rnd.randrange(LINES),
                                       rnd.choice((0, 30000, 45000, 48000))))
        for m in (0, 1, 2, 3, 4, -1, 7):
            ops.append("q %d" % m)
        ops.append("u 0")
    for g, gap in ((12.0, 0.5), (0.0, 0.0), (5.0, -1.0)):
        ops.append("G GRACE %s" % h(f32(g)))
        ops.append("G GAP %s" % h(f32(gap)))
        for dn in (100, 101, 149, 150, 0, 99, 102):
            v = dict(w.cars[1], dn=dn)
            ops.append(car_op(1, v))
            for t in (1000, 1000 + 4 * 12000, 1000 + 4 * 12000 + 1,
                      1000 + 4 * 11500, 1000 + 4 * 12500, 0):
                ops.append("G TIMER %08x" % t)
                ops.append("u 1")
    return ops


def s_reduce(rnd):
    """ReduceCurrentL, each way and to each edge."""
    w = World(rnd)
    ops = w.ops
    w.route(0, 10, 7)
    for _ in range(150):
        ops.append("r %s %d 0 %d %d %s %s %d" % (
            h(f32(rnd.choice((0.0, -0.0, rnd.uniform(-15.0, 15.0), 0.25,
                              -0.25, 0.1, 30.0, -30.0)))),
            rnd.choice((0, 1, 2, 3, 4, 7)), rnd.randrange(10),
            rnd.randrange(LINES),
            h(f32(rnd.choice((0.25, 0.5, 0.0, rnd.uniform(0.0, 3.0))))),
            h(f32(rnd.choice((1.0, 2.2, 0.0, 9.0)))),
            rnd.choice((0, 1, 1, 0x100))))
    return ops


def script():
    rnd = random.Random(0x11b2dc)
    sc = [s_small(rnd), s_valid(rnd), s_room(rnd), s_walk(rnd), s_fill(rnd),
          s_speed(rnd), s_reduce(rnd)]
    for _ in range(6):
        sc.append(s_room(rnd))
        sc.append(s_walk(rnd))
        sc.append(s_fill(rnd))
    for _ in range(2):
        sc.append(s_valid(rnd))
        sc.append(s_speed(rnd))
        sc.append(s_reduce(rnd))
    for c in (0.09, 0.105, 0.11, 0.115, 0.125, 0.13, 0.3):
        for sgn in (1, -1):
            sc.append(s_bend(rnd, c, sgn))
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
        self.e.stub(SIGN_DECISION, self.s_sign)
        self.e.stub(GET_ROUTE_POINT, self.s_rp)
        self.e.stub(GET_OOB, self.s_oob)
        self.w = self.e.u32
        self.grace0 = self.w(GLOBALS["GRACE"])
        self.gap0 = self.w(GLOBALS["GAP"])
        self.dec = {}
        self.rp = {}
        self.oob = {}

    def emit(self, s):
        self.out.append(s)

    def fill(self, a, n):
        self.e.mem[a:a + n] = bytes([PATTERN]) * n

    # ---- names -----------------------------------------------------------

    def name(self, a):
        a &= M32
        if a == 0:
            return "null"
        if a == PAT32:
            return "pat"
        for base, stride, n, tag in (
                (CARS, CAR_STRIDE, NCARS, "c"),
                (CTRLS, CTRL_STRIDE, NCARS, "k"),
                (LOCS, 16, NCARS, "L"),
                (CHOICES, 16, NCARS, "ch"),
                (ACTIONS, ACTION_STRIDE, NCARS, "a"),
                (SIGNS, SIGN_SIZE, NSIGNS, "S"),
                (LIST + LIST_ARRAY, NC_SIZE, LIST_MAX, "e")):
            if base <= a < base + stride * n and (a - base) % stride == 0:
                return "%s%d" % (tag, (a - base) // stride)
        if a == LOC:
            return "loc"
        if a == CHOICE:
            return "CH"
        if a == OTHER:
            return "OT"
        if ROUTES <= a < ROUTES + ROUTE_STRIDE * NROUTES:
            k, off = divmod(a - ROUTES, ROUTE_STRIDE)
            if off == 0:
                return "R%d" % k
            if off >= RT_HEADER and (off - RT_HEADER) % RT_POINT == 0:
                return "R%d:%d" % (k, (off - RT_HEADER) // RT_POINT)
        return "?%08x" % a

    def car_index(self, a):
        return (a - CARS) // CAR_STRIDE

    # ---- the stubs -------------------------------------------------------

    def s_sign(self, em):
        ctrl, sign, linep, loc = (em.reg[r] & M32 for r in (4, 5, 6, 7))
        i = (sign - SIGNS) // SIGN_SIZE
        take, nl = self.dec.get(i, (0, -1))
        self.emit("  sign %s %s %d %s" % (self.name(ctrl), self.name(sign),
                                          s32(self.w(linep)),
                                          self.name(loc)))
        if nl >= 0:
            self.e.put32(linep, nl)
        return take

    def s_rp(self, em):
        car = em.reg[4] & M32
        self.emit("  rp %s" % self.name(car))
        return self.rp[self.car_index(car)]

    def s_oob(self, em):
        car = em.reg[4] & M32
        self.emit("  oob %s" % self.name(car))
        em.fpr[0] = self.oob[self.car_index(car)]

    # ---- the dumps -------------------------------------------------------

    def dump_choice(self, a, tag):
        w = self.w
        self.emit("  %s %d %s %d" % (tag, s32(w(a)), self.name(w(a + 4)),
                                     s32(w(a + 8))))

    def dump_target(self):
        w, m = self.w, self.e.mem
        t = TARGET
        n = s8(m[t])
        self.emit("  target n %d tt %d len %s last %d pk %d %d %d" % (
            n, s32(w(t + 496)), fx(w(t + 512)), s8(m[t + 516]),
            s8(m[t + 500]), s32(w(t + 504)), s32(w(t + 508))))
        for i in range(max(0, min(n, 20))):
            p = t + 16 + 16 * i
            self.emit("    %d %s %s %s r %d p %d l %d sp %s" % (
                i, fx(w(p)), fx(w(p + 4)), fx(w(p + 8)), s8(m[t + 416 + i]),
                s16(self.e.u16(t + 436 + 2 * i)), s8(m[t + 476 + i]),
                fx(w(t + 336 + 4 * i))))

    def dump_fpl(self):
        w = self.w
        n = s32(w(FPL))
        self.emit("  fpl %d" % n)
        for i in range(max(0, min(n, FPL_MAX))):
            p = FPL + 4 + FP_SIZE * i
            self.emit("    %d r %d p %d l %d o %s x %d" % (
                i, s32(w(p)), s32(w(p + 4)), s32(w(p + 8)), fx(w(p + 12)),
                s32(w(p + 16))))

    def dump_walk(self, got):
        w = self.w
        self.emit("  adv %d %s %s n %d o %s x %d l %d" % (
            got, self.name(w(WALK)), self.name(w(WALK + 4)),
            s32(w(WALK + 8)), fx(w(WALK + 12)), s32(w(WALK + 16)),
            s32(w(WALK + 20))))

    # ---- the world -------------------------------------------------------

    def reset(self):
        e = self.e
        e.mem[CARS:CARS + CAR_STRIDE * NCARS] = bytes(CAR_STRIDE * NCARS)
        e.mem[CTRLS:CTRLS + CTRL_STRIDE * NCARS] = bytes(CTRL_STRIDE * NCARS)
        e.mem[CHOICES:LOCS + 16 * NCARS] = bytes(LOCS + 16 * NCARS - CHOICES)
        e.mem[CTIS:DRIVERS + DRIVER_STRIDE * NCARS] = bytes(
            DRIVERS + DRIVER_STRIDE * NCARS - CTIS)
        e.mem[ROUTE_TABLE:ROUTE_TABLE + 4 * NUM_ROUTE_SLOTS] = bytes(
            4 * NUM_ROUTE_SLOTS)
        e.mem[SIGNS:SIGNS + SIGN_SIZE * NSIGNS] = bytes(SIGN_SIZE * NSIGNS)
        e.mem[RACE:RACE + 64] = bytes(64)
        self.fill(LIST, 464)
        self.fill(LOC, 16)
        self.fill(CHOICE, 12)
        self.fill(OTHER, 12)
        self.fill(FPL, FPL_BYTES)
        self.fill(LPTR, 4)
        self.fill(WALK, 24)
        self.fill(TARGET, TARGET_BYTES)
        for name, v in (("TIMER", 0), ("RACE", RACE),
                        ("GRACE", self.grace0), ("GAP", self.gap0),
                        ("WILLIAMS", 0),
                        ("SECS", 0x40000000), ("DEF", 0x41a00000),
                        ("SIGNS", SIGNS), ("NSIGNS", NSIGNS)):
            e.put32(GLOBALS[name], v)
        self.dec = {}
        self.rp = {}
        self.oob = {}

    def set_car(self, t):
        e = self.e
        k = int(t[1])
        v = {}
        for f, x in zip(CAR_FIELDS, t[2:]):
            v[f] = int(x, 16) if f in CAR_FLOATS else int(x)
        a = car_at(k)
        ctrl = CTRLS + CTRL_STRIDE * k
        cti = CTIS + CTI_STRIDE * k
        drv = DRIVERS + DRIVER_STRIDE * k
        ch = CHOICES + 16 * k
        act = ACTIONS + ACTION_STRIDE * k
        struct.pack_into("<h", e.mem, a + C_DN, v["dn"])
        e.put32(a + C_CTI, cti)
        e.mem[cti + CTI_CLASS] = v["cls"] & 0xff
        e.put32(a + C_DRIVER, drv)
        e.put32(drv + DRV_TYPE, v["dtype"])
        e.put32(a + C_CTL, v["ctl"])
        e.put32(a + C_CTRL, ctrl)
        for i, f in enumerate(("px", "py", "pz")):
            e.put32(a + C_POS + 4 * i, v[f])
        e.put32(a + C_BM, v["bx"])
        e.put32(a + C_BM + 4, v["by"])
        e.put32(a + C_VMAG, v["vmag"])
        e.put32(ctrl + K_LOC, LOCS + 16 * k)
        e.put32(ctrl + K_CHOICE, ch)
        e.put32(ctrl + K_EXCLUDE, PAT32)
        e.put32(ctrl + K_ACTION, act if v["act"] >= 0 else 0)
        e.put32(act + A_TYPE, v["act"])
        e.put32(ch, v["ct"])
        e.put32(ch + 4, self.car_ptr(v["cc"]))
        e.put32(ch + 8, v["cx"])
        self.oob[k] = v["oob"]
        self.rp[k] = self.point_of(v["rpr"], v["rpj"])

    def set_route(self, t):
        e = self.e
        k, n, rn, ty = int(t[1]), int(t[2]), int(t[3]), int(t[4])
        a = route_at(k)
        e.mem[a:a + RT_HEADER] = bytes(RT_HEADER)
        struct.pack_into("<hh", e.mem, a + 8, 1, rn)
        e.put32(a + 12, ty)
        e.put32(a + 16, n)
        e.put32(a + 20, n)
        for i in range(LINES):
            e.put32(a + 40 + 48 * i, int(t[5 + i], 16))
        if 0 <= rn < NUM_ROUTE_SLOTS:
            e.put32(ROUTE_TABLE + 4 * rn, a)
        self.cur_route = a
        self.cur_n = 0

    def route_of(self, k):
        k = int(k)
        return route_at(k) if k >= 0 else 0

    def point_of(self, k, j):
        k, j = int(k), int(j)
        if k < 0 or j < 0:
            return 0
        return route_at(k) + RT_HEADER + RT_POINT * j

    def car_ptr(self, s):
        k = int(s)
        return car_at(k) if k >= 0 else 0

    def entry(self, s):
        return LIST + LIST_ARRAY + NC_SIZE * int(s)

    def set_choice(self, a, t):
        e = self.e
        e.put32(a, int(t[1]))
        e.put32(a + 4, self.car_ptr(t[2]))
        e.put32(a + 8, int(t[3]))

    # ---- the ops ---------------------------------------------------------

    def call(self, fn, *args, **f):
        e = self.e
        for i, v in f.items():
            e.fpr[int(i[1:])] = v & M32
        return e.call(fn, *args, limit=4000000)

    def op(self, t):
        e, w = self.e, self.w
        c = t[0]
        if c == "U":
            self.set_route(t)
        elif c == "P":
            a = self.cur_route + RT_HEADER + RT_POINT * self.cur_n
            for i in range(28):
                e.put32(a + 4 * i, int(t[1 + i], 16))
            self.cur_n += 1
        elif c == "K":
            a = SIGNS + SIGN_SIZE * int(t[1])
            e.mem[a] = int(t[2]) & 0xff
            struct.pack_into("<H", e.mem, a + 2, int(t[3]) & 0xffff)
        elif c == "C":
            self.set_car(t)
        elif c == "G":
            e.put32(GLOBALS[t[1]], int(t[2], 16))
        elif c == "Q":
            self.dec[int(t[1])] = (int(t[2]), int(t[3]))
        elif c == "R":
            e.put32(RACE + RACE_START, int(t[1], 16))
        elif c == "N":
            e.put32(LIST, self.car_ptr(t[1]))
            e.put32(LIST + 4, int(t[2]))
            e.put32(LIST + LIST_HL, int(t[3], 16))
            e.put32(LIST + LIST_HD, int(t[4], 16))
        elif c == "E":
            a = self.entry(t[1])
            for i in range(6):
                e.put32(a + 4 * i, int(t[2 + i], 16))
            e.put32(a + 24, self.car_ptr(t[8]))
        elif c == "D":
            e.put32(LOC, self.route_of(t[1]))
            e.put32(LOC + 4, self.point_of(t[1], t[2]))
            e.put32(LOC + 8, int(t[3]))
            e.put32(LOC + 12, int(t[4], 16))
        elif c == "T":
            e.mem[TARGET:TARGET + TARGET_BYTES] = bytes(TARGET_BYTES)
            e.put32(TARGET + 496, int(t[1]))
            e.put32(TARGET + 512, int(t[2], 16))
            e.mem[TARGET + 516] = 0xff
        elif c == "Y":
            n = e.mem[TARGET]
            p = TARGET + 16 + 16 * n
            for i in range(3):
                e.put32(p + 4 * i, int(t[1 + i], 16))
            e.put32(p + 12, 0)
            e.mem[TARGET + 416 + n] = int(t[4]) & 0xff
            struct.pack_into("<h", e.mem, TARGET + 436 + 2 * n, int(t[5]))
            e.mem[TARGET + 476 + n] = int(t[6]) & 0xff
            e.put32(TARGET + 336 + 4 * n, int(t[7], 16))
            e.mem[TARGET] = n + 1
        elif c == "X":
            self.set_choice(CHOICE, t)
        elif c == "O":
            self.set_choice(OTHER, t)
        elif c == "W":
            e.put32(WALK, self.route_of(t[1]))
            e.put32(WALK + 4, self.point_of(t[1], t[2]))
            e.put32(WALK + 8, int(t[3]))
            e.put32(WALK + 20, int(t[4]))
            e.put32(WALK + 12, int(t[5], 16))
            e.put32(WALK + 16, int(t[6]))
        elif c == "F":
            self.fill(FPL, FPL_BYTES)
            e.put32(FPL, 0)
        elif c == "a":
            self.emit("  ctype %d" % self.call(GET_CHOICE_TYPE, int(t[1])))
        elif c == "b":
            self.emit("  dline %d" % self.call(GET_DRIVING_LINE, int(t[1]),
                                               self.car_ptr(t[2])))
        elif c == "c":
            self.call(SET_CHOICE, CHOICE, int(t[1]), self.car_ptr(t[2]),
                      int(t[3]))
            self.dump_choice(CHOICE, "choice")
        elif c == "d":
            self.call(SET_CHOICE_LOC, CHOICE, LOC)
            self.dump_choice(CHOICE, "choice")
        elif c == "e":
            self.call(SET_CHOICE_CHOICE, CHOICE, OTHER)
            self.dump_choice(CHOICE, "choice")
        elif c == "f":
            self.call(CLEAR, CHOICE)
            self.dump_choice(CHOICE, "choice")
        elif c == "g":
            self.emit("  valid %d" % self.call(IS_VALID, CHOICE, LOC, LIST))
        elif c == "h":
            self.emit("  equal %d" % self.call(IS_EQUAL, CHOICE, OTHER))
        elif c == "i":
            got = self.call(ENOUGH_ROOM, CHOICE, self.entry(t[1]), LIST)
            self.emit("  room %d" % got)
        elif c == "j":
            car = self.car_ptr(t[1])
            self.call(FIXUP, CHOICE, car, int(t[2]), LIST)
            self.emit("  exclude %s" % self.name(
                w(w(car + C_CTRL) + K_EXCLUDE)))
        elif c == "k":
            got = self.call(PREFERRED, CHOICE, self.entry(t[1]), LIST, LOC)
            self.emit("  side %d" % got)
        elif c == "m":
            self.call(FPL_ADD, FPL, int(t[1]), int(t[2]), int(t[3]),
                      int(t[5]), f12=int(t[4], 16))
            self.dump_fpl()
        elif c == "n":
            me = w(LIST)
            got = self.call(ADVANCE, FPL, WALK, WALK + 4, WALK + 8,
                            WALK + 12, WALK + 16, WALK + 20, w(me + C_CTRL))
            self.dump_walk(got)
        elif c == "o":
            self.fill(LPTR, 4)
            self.call(POINTS_TO_USE, FPL, TARGET, LOC, LIST, LPTR)
            self.dump_fpl()
            self.emit("  L %s" % fx(w(LPTR)))
        elif c == "p":
            self.call(UP_TO, FPL, LOC, self.point_of(t[1], t[2]))
            self.dump_fpl()
        elif c == "q":
            self.call(SPEED_BACK, LIST, LOC, int(t[1]))
            self.emit("  speed %s" % fx(e.fpr[0]))
        elif c == "r":
            e.put32(LPTR, int(t[1], 16))
            self.call(REDUCE, LPTR, int(t[2]), self.point_of(t[3], t[4]),
                      int(t[5]), int(t[8]), f12=int(t[6], 16),
                      f13=int(t[7], 16))
            self.emit("  l %s" % fx(w(LPTR)))
        elif c == "s":
            self.call(ADD_TO_TARGET, LOC, FPL + 4 + FP_SIZE * int(t[2]),
                      TARGET, f12=int(t[1], 16))
            self.dump_target()
        elif c == "t":
            z = int(t[3]) if len(t) > 3 else 0
            self.call(FILL_UP, 0 if z & 2 else TARGET, 0 if z & 1 else LOC,
                      0 if z & 4 else LIST, int(t[1]), int(t[2]))
            self.dump_target()
            me = w(LIST)
            self.emit("  exclude %s" % self.name(
                w(w(me + C_CTRL) + K_EXCLUDE)))
        elif c == "u":
            got = self.call(GRACE, w(GLOBALS["RACE"]), self.car_ptr(t[1]))
            self.emit("  grace %d" % got)
        else:
            raise SystemExit("bad op %r" % (t,))

    def run(self, scenarios):
        for i, sc in enumerate(scenarios):
            self.emit("B %d" % i)
            self.reset()
            for ln in sc:
                if ln[0] not in "CKPU":
                    self.emit("> " + ln[:48])
                self.op(ln.split())
        return self.out


# ================================================================ the build


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


def build_harness(tmp, name="drivingchoice_test"):
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


def M(name, before, after, rel=DCC):
    return (name, rel, before, after)


MUTATIONS = [
    # -- the literal pool ----------------------------------------------
    M("k-on-road", "#define DC_ON_ROAD          -0.00100000005f",
      "#define DC_ON_ROAD          0.0f"),
    M("k-room-margin", "#define DC_ROOM_MARGIN       5.0f",
      "#define DC_ROOM_MARGIN       4.0f"),
    M("k-traffic-near", "#define DC_TRAFFIC_NEAR      5.0f",
      "#define DC_TRAFFIC_NEAR      6.0f"),
    M("k-near-line", "#define DC_NEAR_LINE         1.0f",
      "#define DC_NEAR_LINE         1.5f"),
    M("k-far-ahead", "#define DC_FAR_AHEAD         50.0f",
      "#define DC_FAR_AHEAD         40.0f"),
    M("k-bending", "#define DC_BENDING           0.119999997f",
      "#define DC_BENDING           0.100000001f"),
    M("k-slow", "#define DC_SLOW              26.8216362f",
      "#define DC_SLOW              25.0f"),
    M("k-fast", "#define DC_FAST              29.5038013f",
      "#define DC_FAST              31.0f"),
    M("k-slow-back", "#define DC_SPEED_SLOW_BACK   0.25f",
      "#define DC_SPEED_SLOW_BACK   0.3f"),
    M("k-fast-back", "#define DC_SPEED_FAST_BACK   0.5f",
      "#define DC_SPEED_FAST_BACK   0.6f"),
    M("k-past-target", "#define DC_PAST_TARGET      -10.0f",
      "#define DC_PAST_TARGET      -5.0f"),
    M("k-min-points", "#define DC_MIN_POINTS        5",
      "#define DC_MIN_POINTS        4"),
    M("k-edge", "#define DC_EDGE              1.0f",
      "#define DC_EDGE              0.5f"),
    # -- the helpers ---------------------------------------------------
    M("min-s-max", "    return ft < fs ? ft : fs;",
      "    return ft < fs ? fs : ft;"),
    M("max-s-min", "    return fs < ft ? ft : fs;",
      "    return fs < ft ? fs : ft;"),
    M("lat-sign", "           - (y - p->Position.y) * p->Direction.x;",
      "           + (y - p->Position.y) * p->Direction.x;"),
    M("lat-dir", "    return (x - p->Position.x) * p->Direction.y",
      "    return (x - p->Position.x) * p->Direction.x"),
    # -- GetChoiceType, GetDrivingLine ---------------------------------
    M("ct-plus", "return line % 2 + 1;", "return line % 2;"),
    M("ct-and", "return line % 2 + 1;", "return (line & 1) + 1;"),
    M("dl-type",
      "return (int32_t)car->pCarTypeInfo->CarClass * 2 + (type - 1);",
      "return (int32_t)car->pCarTypeInfo->CarClass * 2 + type;"),
    M("dl-class",
      "return (int32_t)car->pCarTypeInfo->CarClass * 2 + (type - 1);",
      "return (int32_t)car->pCarTypeInfo->CarClass * 3 + (type - 1);"),
    # -- SetChoice and its two callers, Clear --------------------------
    M("sc-line-car", "        ok = car == NULL;", "        ok = 1;"),
    M("sc-side-car",
      "ok = drivingchoice_type_is_side_of_car(type) && car != NULL;",
      "ok = drivingchoice_type_is_side_of_car(type);"),
    M("sc-side-type",
      "ok = drivingchoice_type_is_side_of_car(type) && car != NULL;",
      "ok = car != NULL;"),
    M("sc-ok", "    if (ok) {", "    if (!ok) {"),
    M("sc-extra", "d->UseExtraLateralDistance = extra;",
      "d->UseExtraLateralDistance = 0;"),
    M("sc-type", "        d->Type = type;\n", ""),
    M("sc-car", "d->pCar = car;", "d->pCar = NULL;"),
    M("scl-line", "drivingchoice_get_choice_type(loc->DrivingLine),",
      "drivingchoice_get_choice_type(loc->DrivingLine + 1),"),
    M("scc-car", "drivingchoice_set_choice(d, other->Type, other->pCar,",
      "drivingchoice_set_choice(d, other->Type, NULL,"),
    M("scc-extra", "                             other->UseExtraLateralDistance);",
      "                             0);"),
    M("cl-extra", "    d->UseExtraLateralDistance = 0;",
      "    d->UseExtraLateralDistance = 1;"),
    M("cl-type", "    d->Type = CHOICE_NONE;",
      "    d->Type = CHOICE_DRIVING_LINE_0;"),
    M("cl-car", "    d->pCar = NULL;\n}", "}"),
    # -- IsValid, IsEqualTo --------------------------------------------
    M("iv-clear-rn", "? -1 : (int32_t)loc->pRoute->RouteNumber;",
      "? 0 : (int32_t)loc->pRoute->RouteNumber;"),
    M("iv-racing-signed", "if ((uint32_t)rn < 50u) {", "if (rn < 50) {"),
    M("iv-racing-bound", "if ((uint32_t)rn < 50u) {",
      "if ((uint32_t)rn < 49u) {"),
    M("iv-line-index",
      "drivingchoice_get_driving_line(d->Type, list->MyCar)].Flags;",
      "drivingchoice_get_driving_line(d->Type, list->MyCar) + 1].Flags;"),
    M("iv-flag-valid",
      "return (flags & DLI_IS_VALID) != 0 || ((flags >> 1) & 1u) != 0;",
      "return ((flags >> 1) & 1u) != 0;"),
    M("iv-flag-two",
      "return (flags & DLI_IS_VALID) != 0 || ((flags >> 1) & 1u) != 0;",
      "return (flags & DLI_IS_VALID) != 0;"),
    M("iv-flag-and",
      "return (flags & DLI_IS_VALID) != 0 || ((flags >> 1) & 1u) != 0;",
      "return (flags & DLI_IS_VALID) != 0 && ((flags >> 1) & 1u) != 0;"),
    M("iv-traffic-lo", "if ((uint32_t)(rn - 50) < 20u)",
      "if ((uint32_t)(rn - 51) < 19u)"),
    M("iv-traffic-hi", "if ((uint32_t)(rn - 50) < 20u)",
      "if ((uint32_t)(rn - 50) < 21u)"),
    M("iv-traffic-line", "return d->Type == CHOICE_DRIVING_LINE_0;",
      "return 1;"),
    M("iv-other-route",
      "            return d->Type == CHOICE_DRIVING_LINE_0;\n        return 0;",
      "            return d->Type == CHOICE_DRIVING_LINE_0;\n        return 1;"),
    M("iv-side", "return nearbycarlist_get_nearby_car(list, d->pCar) != NULL;",
      "return 1;"),
    M("iv-none", "    return 0;\n}\n\nint drivingchoice_is_equal_to",
      "    return 1;\n}\n\nint drivingchoice_is_equal_to"),
    M("eq-side-car",
      "return d->pCar == other->pCar && d->Type == other->Type;",
      "return d->Type == other->Type;"),
    M("eq-side-type",
      "return d->pCar == other->pCar && d->Type == other->Type;",
      "return d->pCar == other->pCar;"),
    M("eq-line-car", "    return d->Type == other->Type;\n}",
      "    return d->Type == other->Type && d->pCar == other->pCar;\n}"),
    # -- IsEnoughRoom --------------------------------------------------
    M("er-line",
      "        return 1;\n    if (!drivingchoice_type_is_side_of_car(d->Type))\n"
      "        return 0;\n    if (!(car_get",
      "        return 0;\n    if (!drivingchoice_type_is_side_of_car(d->Type))\n"
      "        return 0;\n    if (!(car_get"),
    M("er-none",
      "        return 0;\n    if (!(car_get_amount_out_of_bounds",
      "        return 1;\n    if (!(car_get_amount_out_of_bounds"),
    M("er-on-road",
      "if (!(car_get_amount_out_of_bounds(d->pCar) < DC_ON_ROAD))\n"
      "        return 1;",
      "if (!(car_get_amount_out_of_bounds(d->pCar) < DC_ON_ROAD))\n"
      "        return 0;"),
    M("er-on-road-me",
      "if (!(car_get_amount_out_of_bounds(d->pCar) < DC_ON_ROAD))",
      "if (!(car_get_amount_out_of_bounds(list->MyCar) < DC_ON_ROAD))"),
    M("er-rp-me", "    rp = car_get_route_point(d->pCar);",
      "    rp = car_get_route_point(list->MyCar);"),
    M("er-room-mine",
      "    rp = car_get_route_point(d->pCar);\n"
      "    room = (nc->ApparentHalfSizeL + list->MyHalfSizeL) + DC_ROOM_MARGIN;",
      "    rp = car_get_route_point(d->pCar);\n"
      "    room = nc->ApparentHalfSizeL + DC_ROOM_MARGIN;"),
    M("er-room-its",
      "    rp = car_get_route_point(d->pCar);\n"
      "    room = (nc->ApparentHalfSizeL + list->MyHalfSizeL) + DC_ROOM_MARGIN;",
      "    rp = car_get_route_point(d->pCar);\n"
      "    room = list->MyHalfSizeL + DC_ROOM_MARGIN;"),
    M("er-lat-xy",
      "lat = lateral(rp, d->pCar->State.Position.x, d->pCar->State.Position.y);",
      "lat = lateral(rp, d->pCar->State.Position.y, d->pCar->State.Position.x);"),
    M("er-left-type",
      "if (d->Type == CHOICE_LEFT_SIDE_OF_CAR)\n        return -rp",
      "if (d->Type == CHOICE_RIGHT_SIDE_OF_CAR)\n        return -rp"),
    M("er-left-room", "return -rp->LeftWidth < lat - room;",
      "return -rp->LeftWidth < lat + room;"),
    M("er-left-width", "return -rp->LeftWidth < lat - room;",
      "return -rp->RightWidth < lat - room;"),
    M("er-right-room", "return lat + room < rp->RightWidth;",
      "return lat - room < rp->RightWidth;"),
    M("er-right-width", "return lat + room < rp->RightWidth;",
      "return lat + room < rp->LeftWidth;"),
    # -- FixupCarToExcludeFromCollisionPrediction ----------------------
    M("fx-line-null",
      "    if (drivingchoice_type_is_driving_line(d->Type)) {\n"
      "        car_ai_controller(car)->CarToExcludeFromCollisionPrediction = NULL;\n",
      "    if (drivingchoice_type_is_driving_line(d->Type)) {\n"),
    M("fx-unchecked-null",
      "    if (!check) {\n"
      "        car_ai_controller(car)->CarToExcludeFromCollisionPrediction = NULL;\n",
      "    if (!check) {\n"),
    M("fx-check", "    if (!check) {", "    if (check) {"),
    M("fx-traffic",
      "if (other->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR",
      "if (other->MyDriver->TheDriverType != DRIVER_TYPE_TRAFFIC_CAR"),
    M("fx-traffic-me",
      "if (other->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR",
      "if (car->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR"),
    M("fx-dot-sign", "           < 0.0f) {", "           > 0.0f) {"),
    M("fx-dot-x",
      "&& other->State.BodyMatrix.v0.x * car->State.BodyMatrix.v0.x",
      "&& other->State.BodyMatrix.v0.y * car->State.BodyMatrix.v0.x"),
    M("fx-dot-y",
      "+ other->State.BodyMatrix.v0.y * car->State.BodyMatrix.v0.y",
      "- other->State.BodyMatrix.v0.y * car->State.BodyMatrix.v0.y"),
    M("fx-its-car", "            && its->pCar == car) {",
      "            && its->pCar != car) {"),
    M("fx-its-side",
      "        if (drivingchoice_type_is_side_of_car(its->Type)\n"
      "            && its->pCar == car) {",
      "        if (its->pCar == car) {"),
    M("fx-its-left",
      "                if (d->Type == CHOICE_RIGHT_SIDE_OF_CAR)\n"
      "                    ok = 0;",
      "                if (d->Type == CHOICE_LEFT_SIDE_OF_CAR)\n"
      "                    ok = 0;"),
    M("fx-its-right", "} else if (its->Type == CHOICE_RIGHT_SIDE_OF_CAR",
      "} else if (its->Type == CHOICE_LEFT_SIDE_OF_CAR"),
    M("fx-its-right-mine",
      "                       && d->Type == CHOICE_LEFT_SIDE_OF_CAR) {",
      "                       && d->Type == CHOICE_RIGHT_SIDE_OF_CAR) {"),
    M("fx-pull-over",
      "if (act == AIACTION_PULL_OVER && d->Type == CHOICE_LEFT_SIDE_OF_CAR)",
      "if (act != AIACTION_PULL_OVER && d->Type == CHOICE_LEFT_SIDE_OF_CAR)"),
    M("fx-pull-over-side",
      "if (act == AIACTION_PULL_OVER && d->Type == CHOICE_LEFT_SIDE_OF_CAR)",
      "if (act == AIACTION_PULL_OVER && d->Type == CHOICE_RIGHT_SIDE_OF_CAR)"),
    M("fx-no-action", "? oc->CurrentAction->Type : AIACTION_NONE;",
      "? oc->CurrentAction->Type : AIACTION_PULL_OVER;"),
    M("fx-ok", "    if (!ok)\n        return;", "    if (0)\n        return;"),
    M("fx-room", "    if (!drivingchoice_is_enough_room(",
      "    if (0 && !drivingchoice_is_enough_room("),
    M("fx-room-entry",
      "            d, nearbycarlist_get_nearby_car(list, d->pCar), list))",
      "            d, nearbycarlist_get_nearby_car(list, list->MyCar), list))"),
    M("fx-store",
      "car_ai_controller(car)->CarToExcludeFromCollisionPrediction = d->pCar;",
      "car_ai_controller(car)->CarToExcludeFromCollisionPrediction = NULL;"),
    # -- GetPreferredSideOfCar -----------------------------------------
    M("ps-closest-null", "    if (cp == NULL)\n        cp = p;\n", ""),
    M("ps-closest-loc", "    if (cp == NULL)\n        cp = p;",
      "    if (cp == NULL)\n        cp = p + 1;"),
    M("ps-closest-from",
      "loc->pRoute, (const bVector2 *)&other->State.Position, p);",
      "loc->pRoute, (const bVector2 *)&me->State.Position, p);"),
    M("ps-other-lat",
      "otherLat = lateral(cp, other->State.Position.x, other->State.Position.y);",
      "otherLat = lateral(p, other->State.Position.x, other->State.Position.y);"),
    M("ps-other-off",
      "otherOff = otherLat - trpoint_get_driving_line_offset(cp, line);",
      "otherOff = otherLat;"),
    M("ps-other-off-p",
      "otherOff = otherLat - trpoint_get_driving_line_offset(cp, line);",
      "otherOff = otherLat - trpoint_get_driving_line_offset(p, line);"),
    M("ps-my-off",
      "    myOff = lateral(p, me->State.Position.x, me->State.Position.y)\n"
      "            - trpoint_get_driving_line_offset(p, line);",
      "    myOff = lateral(p, me->State.Position.x, me->State.Position.y);"),
    M("ps-traffic",
      "if (me->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR\n"
      "        && otherOff",
      "if (me->MyDriver->TheDriverType != DRIVER_TYPE_TRAFFIC_CAR\n"
      "        && otherOff"),
    M("ps-traffic-near", "        && otherOff < DC_TRAFFIC_NEAR) {",
      "        && fabsf(otherOff) < DC_TRAFFIC_NEAR) {"),
    M("ps-traffic-side", "        decided = 1;\n        left = 0;",
      "        decided = 1;\n        left = 1;"),
    M("ps-traffic-open", "        decided = 1;\n        left = 0;",
      "        left = 0;"),
    M("ps-my-abs", "if (!decided && fabsf(myOff) <= DC_NEAR_LINE",
      "if (!decided && myOff <= DC_NEAR_LINE"),
    M("ps-other-abs", "        && fabsf(otherOff) <= DC_NEAR_LINE",
      "        && otherOff <= DC_NEAR_LINE"),
    M("ps-far-y", "DC_FAR_AHEAD < nc->Position.y",
      "DC_FAR_AHEAD < nc->Position.x"),
    M("ps-bend-abs", "        && DC_BENDING <= fabsf(curv)) {",
      "        && DC_BENDING <= curv) {"),
    M("ps-bend-side", "left = 0.0f < curv ? 0 : 1;",
      "left = 0.0f < curv ? 1 : 0;"),
    M("ps-bend-open", "        left = 0.0f < curv ? 0 : 1;\n        decided = 1;",
      "        left = 0.0f < curv ? 0 : 1;"),
    M("ps-away", "left = otherOff < myOff ? 0 : 1;",
      "left = otherOff < myOff ? 1 : 0;"),
    M("ps-room-mine",
      "\n    room = (nc->ApparentHalfSizeL + list->MyHalfSizeL) + DC_ROOM_MARGIN;\n"
      "    if (left)",
      "\n    room = nc->ApparentHalfSizeL + DC_ROOM_MARGIN;\n    if (left)"),
    M("ps-room-its",
      "\n    room = (nc->ApparentHalfSizeL + list->MyHalfSizeL) + DC_ROOM_MARGIN;\n"
      "    if (left)",
      "\n    room = list->MyHalfSizeL + DC_ROOM_MARGIN;\n    if (left)"),
    M("ps-left-room", "blocked = otherLat - room < -cp->LeftWidth;",
      "blocked = otherLat + room < -cp->LeftWidth;"),
    M("ps-left-width", "blocked = otherLat - room < -cp->LeftWidth;",
      "blocked = otherLat - room < -cp->RightWidth;"),
    M("ps-right-room", "blocked = cp->RightWidth < otherLat + room;",
      "blocked = cp->RightWidth < otherLat - room;"),
    M("ps-right-width", "blocked = cp->RightWidth < otherLat + room;",
      "blocked = cp->LeftWidth < otherLat + room;"),
    M("ps-blocked", "return blocked ? !left : left;", "return left;"),
    # -- FuturePointList::Add ------------------------------------------
    M("fa-route", "p->nRouteNumber = route;", "p->nRouteNumber = route + 1;"),
    M("fa-point", "p->nPointNumber = point;", "p->nPointNumber = point + 1;"),
    M("fa-line", "p->nLine = line;", "p->nLine = 0;"),
    M("fa-count", "    l->NumPoints++;\n", ""),
    M("fa-crossed", "p->bCrossedSignpost = crossed;",
      "p->bCrossedSignpost = 0;"),
    M("fa-offset", "p->fOffset = offset;", "p->fOffset = 0.0f;"),
    # -- AdvancePoint --------------------------------------------------
    M("ap-no-sign", "    if (trpoint_has_signpost(*point)) {", "    if (0) {"),
    M("ap-off-zero",
      "float off = trpoint_get_driving_line_offset(*point, *line);",
      "float off = 0.0f;"),
    M("ap-off-after", "trpoint_get_position3(*point, &pos, 0.0f, off);",
      "trpoint_get_position3(*point, &pos, 0.0f,\n"
      "                                  trpoint_get_driving_line_offset("
      "*point, *line));"),
    M("ap-decision", "            && gAISignPostDecisionFn(ctrl, s, line,",
      "            && !gAISignPostDecisionFn(ctrl, s, line,"),
    M("ap-decision-ctrl", "            && gAISignPostDecisionFn(ctrl, s, line,",
      "            && gAISignPostDecisionFn(NULL, s, line,"),
    M("ap-decision-loc", "                                     ctrl->CurrentDrivingLocation)) {",
      "                                     NULL)) {"),
    M("ap-pos-ahead", "trpoint_get_position3(*point, &pos, 0.0f, off);",
      "trpoint_get_position3(*point, &pos, 1.0f, off);"),
    M("ap-route", "            *route = signpost_get_new_route(s);\n", ""),
    M("ap-point", "            *point = np;\n", ""),
    M("ap-pn", "*pointNumber = troute_get_point_number(*route, np);",
      "*pointNumber = troute_get_point_number(*route, np) + 1;"),
    M("ap-crossed", "*crossed = 1;", "*crossed = 0;"),
    M("ap-offset-line",
      "            *offset = lateral(np, pos.x, pos.y)\n"
      "                      - trpoint_get_driving_line_offset(np, *line);",
      "            *offset = lateral(np, pos.x, pos.y);"),
    M("ap-offset-np", "            *offset = lateral(np, pos.x, pos.y)",
      "            *offset = lateral(np, pos.y, pos.x)"),
    M("ap-sign-result",
      "            return 1;\n        }\n    }\n\n    n = ++*pointNumber;",
      "            return 0;\n        }\n    }\n\n    n = ++*pointNumber;"),
    M("ap-store-pn", "    n = ++*pointNumber;", "    n = *pointNumber + 1;"),
    M("ap-end", "    if (!(n < (*route)->NumPoints))",
      "    if (!(n < (*route)->NumPoints - 1))"),
    M("ap-end-result",
      "    if (!(n < (*route)->NumPoints))\n        return 0;",
      "    if (!(n < (*route)->NumPoints))\n        return 1;"),
    M("ap-offset-kept", "    *offset = 0.0f;\n    *crossed = 0;\n",
      "    *crossed = 0;\n"),
    M("ap-crossed-kept", "    *crossed = 0;\n    *point = troute_get_point(*route, n);",
      "    *point = troute_get_point(*route, n);"),
    M("ap-next", "    *point = troute_get_point(*route, n);",
      "    *point = troute_get_point(*route, n - 1);"),
    # -- GetRoutePointsToUse -------------------------------------------
    M("rp-count",
      "    l->NumPoints = 0;\n    ptnum = drivinglocation_is_clear(loc)",
      "    ptnum = drivinglocation_is_clear(loc)"),
    M("rp-ptnum-loc",
      "? -1 : troute_get_point_number(loc->pRoute, loc->pRoutePoint);",
      "? -1 : troute_get_point_number(loc->pRoute, loc->pRoutePoint) + 1;"),
    M("rp-last", "    i = t->NumPoints - 1;\n    if (i >= 0) {",
      "    i = t->NumPoints - 2;\n    if (i >= 0) {"),
    M("rp-racer", "if (me->MyDriver->TheDriverType == DRIVER_TYPE_AI_RACER",
      "if (me->MyDriver->TheDriverType != DRIVER_TYPE_AI_RACER"),
    M("rp-racer-traffic", "            && route->Type == TRACK_ROUTE_TRAFFIC) {",
      "            && route->Type != TRACK_ROUTE_TRAFFIC) {"),
    M("rp-own-route", "            route = loc->pRoute;\n", ""),
    M("rp-ptnum-t", "ptnum = t->RoutePointNumber[i];",
      "ptnum = t->RoutePointNumber[i] + 1;"),
    M("rp-line-t", "line = t->DrivingLine[i];", "line = loc->DrivingLine;"),
    M("rp-point-t", "point = troute_get_point(route, ptnum);",
      "point = troute_get_point(route, ptnum + 1);"),
    M("rp-past", "} while (DC_PAST_TARGET < (last->x - point->Position.x)",
      "} while (DC_PAST_TARGET > (last->x - point->Position.x)"),
    M("rp-past-dx",
      "                                      * point->Direction.x\n"
      "                                  + (last->y",
      "                                      * point->Direction.y\n"
      "                                  + (last->y"),
    M("rp-past-dy", "                                  + (last->y - point->Position.y)",
      "                                  - (last->y - point->Position.y)"),
    M("rp-empty-xy",
      "*currentL = lateral(point, me->State.Position.x, me->State.Position.y);",
      "*currentL = lateral(point, me->State.Position.y, me->State.Position.x);"),
    M("rp-empty-test", "    if (t->NumPoints == 0) {",
      "    if (t->NumPoints <= 1) {"),
    M("rp-p2", "            *currentL = lateral(p2, t->Points",
      "            *currentL = lateral(point, t->Points"),
    M("rp-p2-test",
      "        if (drivetarget_get_route_and_route_point(t, t->NumPoints - 1, &r2,",
      "        if (0 && drivetarget_get_route_and_route_point(t, t->NumPoints - 1, &r2,"),
    M("rp-else-last",
      "            *currentL = lateral(point, t->Points[t->NumPoints - 1].x,\n"
      "                                t->Points[t->NumPoints - 1].y);",
      "            *currentL = lateral(point, t->Points[0].x,\n"
      "                                t->Points[0].y);"),
    M("rp-l-line", "    *currentL = *currentL - trpoint_get_driving_line_offset(point,\n"
      "                                                            loc->DrivingLine);",
      "    *currentL = *currentL - trpoint_get_driving_line_offset(point,\n"
      "                                                            line);"),
    M("rp-l-no-line", "    *currentL = *currentL - trpoint_get_driving_line_offset(point,\n"
      "                                                            loc->DrivingLine);",
      ""),
    M("rp-first-crossed",
      "                        troute_get_point_number(route, point), line, offset, 0);",
      "                        troute_get_point_number(route, point), line, offset, crossed);"),
    M("rp-first-offset",
      "                        troute_get_point_number(route, point), line, offset, 0);",
      "                        troute_get_point_number(route, point), line, 0.0f, 0);"),
    M("rp-second", "    if (l->NumPoints == 1) {", "    if (l->NumPoints == 2) {"),
    M("rp-second-crossed",
      "                            offset, 0);\n    }",
      "                            offset, crossed);\n    }"),
    M("rp-dist-sqrt", "    dist = sqrtf((me->State.Position.x - point->Position.x)",
      "    dist = ((me->State.Position.x - point->Position.x)"),
    M("rp-dist-y",
      "                 + (me->State.Position.y - point->Position.y)\n",
      "                 - (me->State.Position.y - point->Position.y)\n"),
    M("rp-look-or",
      "if (!(dist <= lookAhead) && !(l->NumPoints < DC_MIN_POINTS))",
      "if (!(dist <= lookAhead) || !(l->NumPoints < DC_MIN_POINTS))"),
    M("rp-look-min",
      "if (!(dist <= lookAhead) && !(l->NumPoints < DC_MIN_POINTS))",
      "if (!(dist <= lookAhead))"),
    M("rp-look-dist",
      "if (!(dist <= lookAhead) && !(l->NumPoints < DC_MIN_POINTS))",
      "if (!(l->NumPoints < DC_MIN_POINTS))"),
    M("rp-max", "more = l->NumPoints < FUTUREPOINTLIST_MAX;",
      "more = l->NumPoints < FUTUREPOINTLIST_MAX - 1;"),
    M("rp-dist-len", "dist = dist + point->Length;",
      "dist = dist + point->Length * 0.5f;"),
    M("rp-loop-crossed",
      "                            offset, crossed);\n    }\n}",
      "                            offset, 0);\n    }\n}"),
    # -- the road-block list -------------------------------------------
    M("ut-count",
      "    l->NumPoints = 0;\n    if (drivinglocation_is_clear(loc))\n"
      "        return;\n    rn",
      "    if (drivinglocation_is_clear(loc))\n        return;\n    rn"),
    M("ut-line", "    line = loc->DrivingLine;\n    i = troute",
      "    line = 0;\n    i = troute"),
    M("ut-start",
      "    i = troute_get_point_number(loc->pRoute, loc->pRoutePoint);",
      "    i = troute_get_point_number(loc->pRoute, loc->pRoutePoint) + 1;"),
    M("ut-end", "last = troute_get_point_number(loc->pRoute, end);",
      "last = troute_get_point_number(loc->pRoute, end) - 1;"),
    M("ut-le", "for (; !(last < i) && l->NumPoints < FUTUREPOINTLIST_MAX; i++)",
      "for (; !(last <= i) && l->NumPoints < FUTUREPOINTLIST_MAX; i++)"),
    M("ut-max", "for (; !(last < i) && l->NumPoints < FUTUREPOINTLIST_MAX; i++)",
      "for (; !(last < i) && l->NumPoints < FUTUREPOINTLIST_MAX - 1; i++)"),
    M("ut-offset", "futurepointlist_add(l, rn, i, line, 0.0f, 0);",
      "futurepointlist_add(l, rn, i, line, 1.0f, 0);"),
    # -- GetSpeedBackToLine, the grace period --------------------------
    M("sb-parallel",
      "    if (m == MOVEMENT_PARALLEL_TO_LINE)\n        return 0.0f;",
      "    if (m == MOVEMENT_PARALLEL_TO_LINE)\n        return DC_SPEED_FAST_BACK;"),
    M("sb-sides", "if ((uint32_t)(m - MOVEMENT_TOWARDS_LEFT_SIDE_OF_TRACK) < 2u",
      "if ((uint32_t)(m - MOVEMENT_TOWARDS_LEFT_SIDE_OF_TRACK) < 1u"),
    M("sb-sides-none",
      "if ((uint32_t)(m - MOVEMENT_TOWARDS_LEFT_SIDE_OF_TRACK) < 2u",
      "if ((uint32_t)(m - MOVEMENT_TOWARDS_LEFT_SIDE_OF_TRACK) < 3u"),
    M("sb-traffic",
      "        || list->MyCar->TheControlMode == TRAFFIC_CONTROL)",
      "        || list->MyCar->TheControlMode != TRAFFIC_CONTROL)"),
    M("sb-grace",
      "    if (race_grace_period_is_active(pCurrentRace, list->MyCar))\n"
      "        return 0.0f;",
      "    if (race_grace_period_is_active(pCurrentRace, list->MyCar))\n"
      "        return DC_SPEED_SLOW_BACK;"),
    M("sb-vmag", "v = list->MyCar->State.VelocityMagnitude;",
      "v = list->MyCar->State.VelocityMagnitude * 0.5f;"),
    M("sb-slow", "    if (v <= DC_SLOW)\n        return 0.0f;",
      "    if (v <= DC_SLOW)\n        return DC_SPEED_SLOW_BACK;"),
    M("sb-fast", "    if (v <= DC_FAST)\n        return DC_SPEED_SLOW_BACK;",
      "    if (v <= DC_FAST)\n        return DC_SPEED_FAST_BACK;"),
    M("sb-relaxed", "? DC_SPEED_SLOW_BACK : DC_SPEED_FAST_BACK;",
      "? DC_SPEED_FAST_BACK : DC_SPEED_SLOW_BACK;"),
    M("gr-start", "float StartOfRaceGracePeriod = 12.0f;",
      "float StartOfRaceGracePeriod = 10.0f;", rel=RCC),
    M("gr-between", "float TimeBetweenCarsForGracePeriodExit = 0.5f;",
      "float TimeBetweenCarsForGracePeriodExit = 0.25f;", rel=RCC),
    M("gr-lo", "if ((uint32_t)(car->DriverNumber - 101) < 49u)",
      "if ((uint32_t)(car->DriverNumber - 102) < 48u)", rel=RCC),
    M("gr-hi", "if ((uint32_t)(car->DriverNumber - 101) < 49u)",
      "if ((uint32_t)(car->DriverNumber - 101) < 50u)", rel=RCC),
    M("gr-signed", "if ((uint32_t)(car->DriverNumber - 101) < 49u)",
      "if (car->DriverNumber - 101 < 49)", rel=RCC),
    M("gr-order", "grace = grace + (float)(100 - car->DriverNumber)",
      "grace = grace + (float)(car->DriverNumber - 100)", rel=RCC),
    M("gr-ticks", "               * 0.000250000012f",
      "               * 0.000500000024f", rel=RCC),
    M("gr-started",
      "((uint32_t)WorldTimer - r->StartTime.PackedTime)",
      "((uint32_t)WorldTimer)", rel=RCC),
    M("gr-test", "           <= grace;", "           >= grace;", rel=RCC),
    # -- ReduceCurrentL ------------------------------------------------
    M("rl-right", "        *l = *l + amount;", "        *l = *l - amount;"),
    M("rl-left", "        *l = *l - amount;", "        *l = *l + amount;"),
    M("rl-right-type",
      "    if (m == MOVEMENT_TOWARDS_RIGHT_SIDE_OF_TRACK) {",
      "    if (m == MOVEMENT_TOWARDS_LINE) {"),
    M("rl-left-type",
      "} else if (m == MOVEMENT_TOWARDS_LEFT_SIDE_OF_TRACK) {",
      "} else if (m == MOVEMENT_PARALLEL_TO_LINE) {"),
    M("rl-neg-add", "*l = amount < -cur ? cur + amount : 0.0f;",
      "*l = amount < -cur ? cur - amount : 0.0f;"),
    M("rl-neg-test", "*l = amount < -cur ? cur + amount : 0.0f;",
      "*l = amount < cur ? cur + amount : 0.0f;"),
    M("rl-neg-zero", "*l = amount < -cur ? cur + amount : 0.0f;",
      "*l = amount < -cur ? cur + amount : cur;"),
    M("rl-pos-sub", "*l = amount < cur ? cur - amount : 0.0f;",
      "*l = amount < cur ? cur + amount : 0.0f;"),
    M("rl-pos-zero", "*l = amount < cur ? cur - amount : 0.0f;",
      "*l = amount < cur ? cur - amount : cur;"),
    M("rl-sign", "        if (cur < 0.0f)", "        if (cur > 0.0f)"),
    M("rl-off", "    off = trpoint_get_driving_line_offset(point, line);",
      "    off = 0.0f;"),
    M("rl-inside", "    if (inside) {", "    if (!inside) {"),
    M("rl-hi-half", "hi = (point->RightWidth - DC_EDGE) - halfWidth;",
      "hi = (point->RightWidth - DC_EDGE) + halfWidth;"),
    M("rl-lo-half", "lo = (DC_EDGE - point->LeftWidth) + halfWidth;",
      "lo = (DC_EDGE - point->LeftWidth) - halfWidth;"),
    M("rl-hi-edge", "hi = (point->RightWidth - DC_EDGE) - halfWidth;",
      "hi = point->RightWidth - halfWidth;"),
    M("rl-lo-edge", "lo = (DC_EDGE - point->LeftWidth) + halfWidth;",
      "lo = -point->LeftWidth + halfWidth;"),
    M("rl-hi", "        hi = point->RightWidth;", "        hi = point->LeftWidth;"),
    M("rl-lo", "        lo = -point->LeftWidth;", "        lo = -point->RightWidth;"),
    M("rl-clamp-hi", "*l = min_s(hi - off, max_s(*l, lo - off));",
      "*l = max_s(*l, lo - off);"),
    M("rl-clamp-lo", "*l = min_s(hi - off, max_s(*l, lo - off));",
      "*l = min_s(hi - off, *l);"),
    M("rl-clamp-off", "*l = min_s(hi - off, max_s(*l, lo - off));",
      "*l = min_s(hi, max_s(*l, lo));"),
    M("rl-clamp-order", "*l = min_s(hi - off, max_s(*l, lo - off));",
      "*l = max_s(lo - off, min_s(*l, hi - off));"),
    # -- AddToDriveTarget ----------------------------------------------
    M("at-point", "                                           p->nPointNumber);\n"
      "    bVector3 pos;",
      "                                           p->nPointNumber + 1);\n"
      "    bVector3 pos;"),
    M("at-ahead", "    trpoint_get_position3(pt, &pos, 0.0f,",
      "    trpoint_get_position3(pt, &pos, 1.0f,"),
    M("at-l", "l + trpoint_get_driving_line_offset(pt, p->nLine));",
      "trpoint_get_driving_line_offset(pt, p->nLine));"),
    M("at-line", "l + trpoint_get_driving_line_offset(pt, p->nLine));",
      "l + trpoint_get_driving_line_offset(pt, 0));"),
    M("at-rn", "drivetarget_add_point3(t, &pos, (int8_t)p->nRouteNumber,",
      "drivetarget_add_point3(t, &pos, (int8_t)(p->nRouteNumber + 1),"),
    M("at-pn", "(int16_t)p->nPointNumber, (int8_t)p->nLine, 1,",
      "(int16_t)(p->nPointNumber + 1), (int8_t)p->nLine, 1,"),
    M("at-dl", "(int16_t)p->nPointNumber, (int8_t)p->nLine, 1,",
      "(int16_t)p->nPointNumber, (int8_t)(p->nLine + 1), 1,"),
    M("at-check", "(int16_t)p->nPointNumber, (int8_t)p->nLine, 1,",
      "(int16_t)p->nPointNumber, (int8_t)p->nLine, 0,"),
    # -- FillUpDriveTarget ---------------------------------------------
    M("fu-null-loc", "    if (loc == NULL || t == NULL || list == NULL)",
      "    if (t == NULL || list == NULL)"),
    M("fu-null-target", "    if (loc == NULL || t == NULL || list == NULL)",
      "    if (loc == NULL || list == NULL)"),
    M("fu-null-list", "    if (loc == NULL || t == NULL || list == NULL)",
      "    if (loc == NULL || t == NULL)"),
    M("fu-clear",
      "    if (drivinglocation_is_clear(loc))\n        return;\n    // The terrain",
      "    if (0)\n        return;\n    // The terrain"),
    M("fu-ttype", "t->TType = (int32_t)trpoint_terrain_type(loc->pRoutePoint);",
      "t->TType = 0;"),
    M("fu-ttype-late",
      "    t->TType = (int32_t)trpoint_terrain_type(loc->pRoutePoint);\n"
      "    if (!(t->NumPoints < DRIVETARGET_MAX_POINTS))\n        return;",
      "    if (!(t->NumPoints < DRIVETARGET_MAX_POINTS))\n        return;\n"
      "    t->TType = (int32_t)trpoint_terrain_type(loc->pRoutePoint);"),
    M("fu-full", "    if (!(t->NumPoints < DRIVETARGET_MAX_POINTS))",
      "    if (!(t->NumPoints < DRIVETARGET_MAX_POINTS - 1))"),
    M("fu-speed-m", "speed = drivingchoice_get_speed_back_to_line(list, loc, m);",
      "speed = drivingchoice_get_speed_back_to_line(list, loc,\n"
      "                                                 MOVEMENT_TOWARDS_LINE);"),
    M("fu-crossed-m",
      "if (m == MOVEMENT_TOWARDS_LINE && fp->bCrossedSignpost)",
      "if (fp->bCrossedSignpost)"),
    M("fu-crossed-only",
      "if (m == MOVEMENT_TOWARDS_LINE && fp->bCrossedSignpost)",
      "if (m == MOVEMENT_TOWARDS_LINE)"),
    M("fu-crossed-min", "speed = min_s(speed, DC_SPEED_SLOW_BACK);",
      "speed = DC_SPEED_SLOW_BACK;"),
    M("fu-reduce-line",
      "drivingchoice_reduce_current_l(&l, m, pt, loc->DrivingLine, speed,",
      "drivingchoice_reduce_current_l(&l, m, pt, fp->nLine, speed,"),
    M("fu-reduce-half", "                                       list->MyHalfSizeL, inside);",
      "                                       0.0f, inside);"),
    M("fu-reduce-inside", "                                       list->MyHalfSizeL, inside);",
      "                                       list->MyHalfSizeL, !inside);"),
    M("fu-offset", "        l = l + fp->fOffset;", "        l = l - fp->fOffset;"),
    M("fu-tuning-m",
      "if (WilliamsAITuningMode != 0 && m == MOVEMENT_TOWARDS_LINE)",
      "if (WilliamsAITuningMode != 0)"),
    M("fu-tuning-off",
      "if (WilliamsAITuningMode != 0 && m == MOVEMENT_TOWARDS_LINE)",
      "if (m == MOVEMENT_TOWARDS_LINE)"),
    M("fu-add-l",
      "drivingchoice_add_to_drive_target(ls[i], loc, &fl.Points[i], t);",
      "drivingchoice_add_to_drive_target(ls[0], loc, &fl.Points[i], t);"),
    M("fu-no-fixup",
      "    drivingchoice_fixup_car_to_exclude_from_collision_prediction(\n"
      "        &dc, list->MyCar, 0, list);",
      ""),
    M("fu-no-choice", "    drivingchoice_set_choice_location(&dc, loc);\n", ""),
]

EQUIVALENT = {
    "fx-its-side":
        "The side test on the oncoming car's own choice guards two tests "
        "that its type is CHOICE_LEFT_SIDE_OF_CAR or CHOICE_RIGHT_SIDE_OF_"
        "CAR, the only two types IsSideOfCar accepts. Without it, a choice "
        "of any other type with pCar equal to this car reaches those tests "
        "and fails both, leaving ok as it was: the same result for every "
        "type.",
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
        todo, SOURCES, "drivingchoice_test",
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
