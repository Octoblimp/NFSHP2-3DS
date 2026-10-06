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
CCP = "3DS Files/source/carcollisionpredict.c"
SOURCES = [HARNESS, DCC, RCC, CCP] + ["3DS Files/source/" + f for f in (
    "nearbycar.c", "drivinglocation.c", "drivetarget.c", "obb.c", "car.c",
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
BUILD = 0x00241ea0
AROUND = 0x00243aa8
PARALLEL = 0x00243f70
CLEARANCE = 0x002442c0
SEARCH = 0x00244d80
SMOOTH = 0x00244ea0
# DoSmoothOffsetChange's slope, the one divide the script takes by zero:
# the model runs with the EE's divide, and no other site may take it.
SMOOTH_DIV = 0x00245050

# CarCollisionPredict (step 11b-4a).
WHO = 0x001e5e60
WILL = 0x001e60a0
STOPPED = 0x001e6010
MAKE_OBBS = 0x001e6860
WHEN_2D = 0x001e72f8
TISA = 0x001e7238
OVERLAP = 0x001e6ac0
# WillIHitThisCar's steps along each car's leg, which divide by a leg of 0
# when a car is at its next point.
WILL_DIVS = {0x001e65ec, 0x001e65f4}

# DriveTarget's MinDistanceToPoint and its square, which the image's
# start-up code (0x0020ab48) works out and the emulator does not run.
MIN_DIST = 0x00331a48
MIN_DIST_SQ = 0x003324d4

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
    "TRAFFIC": GP - 15152,        # AITrafficTuningMode
    "SLOWCAR": GP - 15120,        # AISlowCarSpeed
    "SLOWTRAFFIC": GP - 15116,    # AISlowTrafficSpeed
    "WORLD": GP - 22120,          # pCurrentWorld
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
CDRIVERS = 0x01060000             # each car's CarDriver, its target first
CDRIVER_STRIDE = 0x400
PLAYERS = 0x01070000              # a player, never read
PLAYER_STRIDE = 16
VEC = 0x01091a00
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
OBBS = 0x01095000                 # MakeOBBsForDriveTarget's twenty boxes
OBB_A = 0x01096000
OBB_B = 0x01096100
VEC_D = 0x01096200
VEC_V = 0x01096210
OUT = 0x01096300                  # the out floats
WORLD = 0x01098000
BODIES = 0x010a0000               # each car's collision body
BODY_STRIDE = 0x200
ROUTES = 0x01100000
ROUTE_STRIDE = 0x20000
NROUTES = 6

# The car, at retail's offsets.
C_DN = 10
C_CTI = 12
C_DRIVER = 20
C_PLAYER = 24
C_CTL = 32
C_CTRL = 40
C_CDRIVER = 44
C_POS = 96
C_VEL = 112
C_BM = 144
C_NW = 956
C_FS = 960
C_VMAG = 964
C_BODY = 52
C_ACC = 128
C_ANGLE = 932
B_MIN = 224
B_MAX = 240
W_ID = 408
OBB_SIZE = 80
NOBBS = 20
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
# H k tt len pk ct pt    car k's own target emptied: TType tt, Length len,
#                        LastPointToScore -1, the picked point pk and its
#                        two times, the rest 0
# I k x y z rn j line sp a point put on car k's target by hand
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
# v m                    BuildDriveTarget
# w                      BuildDriveTargetAroundCar
# x px py start          the future point list's closest point ahead
# y e idx                the clearance beside entry e (-1 NULL)
# z idx from to in       DoSmoothOffsetChange
# M side                 MakeDriveTargetParallelToCar
#
# CarCollisionPredict's (step 11b-4a). Set up, and echoed:
# A k ax ay vz ang mn mx car k's acceleration, its velocity's z, its angle
#                        and its collision body's box (three words each)
# Z k c                  car k's controller leaves out car c (-1 NULL)
# S n                    the target's NumPoints by hand
# The calls:
# 1 a0 a1 b0 b1          IntervalOverlap
# 2 v d r                TimeIntervalForSeparatingAxis
# 3 a b dx dy vx vy      WhenWillOverlapOccur2D; each box is six words:
#                        A0's and A1's x and y, a0 and a1
# 4 t c scale z          MakeOBBsForDriveTarget of the target (t -1) or car
#                        t's own, for car c (-1 NULL); z's bits make the
#                        target and the boxes NULL (1, 2)
# 5 e                    IsThisCarStoppedDirectlyInFrontOfMe, entry e
# 6 k max                WillIHitThisCar: the list's car on the target,
#                        and car k
# 7 max z                WhoWillThisDriveTargetHit; z's 1 makes the
#                        location NULL
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
    "oob", "rpr", "rpj", "ct", "cc", "cx", "act", "pl", "nw", "vx", "vy",
    "fs")
CAR_FLOATS = ("px", "py", "pz", "bx", "by", "vmag", "oob", "vx", "vy",
              "fs")


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
        self.sign_to = []

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
        self.sign_to.append((k2, j2))
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
        # Drawn from nothing, so the scenarios before these were added
        # draw what they drew.
        v.update(pl=0, nw=4, vx=math.cos(a), vy=math.sin(a), fs=0.0)
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


def heading_of(p):
    return math.atan2(p["dy"], p["dx"])


def lateral_of(p, x, y):
    return (x - p["x"]) * p["dy"] - (y - p["y"]) * p["dx"]


def its_target(rnd, w, sizes, k, kr, j, reverse=False):
    """Car k's own target: up to eight points along route kr from about
    its point j, forwards or back, now and then jumping to another route,
    and sometimes with a point that has no route or no number."""
    ops = ["H %d %d %s %d %d %d" % (
        k, rnd.randrange(64), h(f32(rnd.uniform(0.0, 80.0))),
        rnd.choice((0, 0, 1, 2, 7, -1)), rnd.choice((0, 1000, 5000)),
        rnd.choice((0, 1000)))]
    jj = max(0, min(sizes[kr] - 1, j))
    for i in range(rnd.choice((0, 1, 2, 4, 6, 8, 8))):
        if i and rnd.random() < 0.12:
            kr = rnd.randrange(5)
            jj = rnd.randrange(sizes[kr])
        f = tgt_point(w, kr, jj, rnd.uniform(-5.0, 5.0),
                      rnd.randrange(LINES), sp=rnd.uniform(0.0, 40.0),
                      along=rnd.uniform(-2.0, 2.0)).split()
        if rnd.random() < 0.06:
            f[4 if rnd.random() < 0.5 else 5] = "-1"
        ops.append("I %d %s" % (k, " ".join(f[1:])))
        jj = max(0, min(sizes[kr] - 1, jj + (-1 if reverse else 1)))
    return ops


def car_at_point(rnd, w, k, kr, j, lat, near, its=None, **kw):
    """Car k at route kr's point j, lat across it, heading along it or
    across or back and sliding a little, at speeds either side of the
    ones that matter."""
    p = w.pts[kr][j]
    x, y = beside(p, lat, rnd.uniform(-3.0, 3.0))
    if near:
        turn = rnd.choice((0.0, 0.2, -0.2, 0.7, -0.7))
        speed = rnd.choice((4.9, 5.0, 5.01, 12.0, 20.0, 30.0, 30.0))
        nw = rnd.choice((2, 3, 4, 4, 4))
    else:
        turn = rnd.choice((0.0, 0.0, 0.3, -0.3, 0.78, -0.78, 0.8, -0.8,
                           math.pi, 1.6))
        speed = rnd.choice((4.9, 5.0, 5.01, 9.99, 10.0, 10.01, 10.5, 19.99,
                            20.0, 20.01, 20.5, 30.0, -15.0, -25.0, 0.0))
        nw = rnd.choice((2, 3, 4, 4))
    a = heading_of(p) + turn
    slip = a + rnd.choice((0.0, 0.0, 0.3, -0.5, 0.9))
    vel = max(abs(speed), 1.0)
    args = dict(px=x, py=y, bx=math.cos(a), by=math.sin(a), vmag=speed,
                vx=vel * math.cos(slip), vy=vel * math.sin(slip), nw=nw,
                pl=rnd.choice((0, 1)), dtype=rnd.choice((1, 2, 3, 3, 4, 4)),
                fs=rnd.choice((0.0, 25.0, 35.0)), oob=0.0)
    args.update(kw)
    return w.car(k, **args)


def place_other(rnd, w, sizes, k, kr, j0, near=False, reverse=None,
                span=18):
    """Car k up to `span` points ahead of j0 on route kr: on its line,
    near an edge or off the road; and its own target."""
    j = min(sizes[kr] - 2, j0 + rnd.randrange(1, span))
    p = w.pts[kr][j]
    lat = rnd.choice((off_of(p, 0), rnd.uniform(-3.0, 3.0),
                      rnd.uniform(-p["lw"], p["rw"]), p["rw"] - 1.0,
                      -p["lw"] + 1.0, p["rw"] + 4.9, p["rw"] + 5.1,
                      -p["lw"] - 4.9, -p["lw"] - 5.1, p["rw"] + 9.0))
    v = car_at_point(rnd, w, k, kr, j, lat, near)
    if reverse is None:
        reverse = rnd.random() < 0.2
    kt = rnd.choice((kr, kr, kr, 3, 4, 1))
    jt = j if kt == kr else rnd.randrange(sizes[kt])
    w.ops += its_target(rnd, w, sizes, k, kt, jt, reverse)
    return v


def place_me(rnd, w, k, kr, j0, line, **kw):
    p = w.pts[kr][j0]
    hd = heading_of(p) + rnd.choice((0.0, 0.0, 0.1, -0.1))
    slip = hd + rnd.choice((0.0, 0.0, 0.2, -0.3))
    x, y = beside(p, off_of(p, line) + rnd.uniform(-2.0, 2.0), 1.0)
    sp = rnd.choice((4.9, 5.0, 5.01, 20.0, 35.0))
    args = dict(px=x, py=y, bx=math.cos(hd), by=math.sin(hd), vmag=sp,
                vx=sp * math.cos(slip), vy=sp * math.sin(slip),
                dtype=rnd.choice((2, 2, 3, 3, 4, 0)), oob=0.0)
    args.update(kw)
    return w.car(k, **args)


def s_around(rnd):
    """BuildDriveTarget, and BuildDriveTargetAroundCar under it, for a
    line, a side and neither, beside cars of every kind, on the road and
    off it and past a sign, the traffic tuning mode on and off."""
    w = World(rnd)
    ops = w.ops
    sizes = walk_world(rnd, w, nsigns=rnd.randint(0, 6))
    # The walk starts on route 0, or a few points short of a sign so that
    # it crosses it.
    if w.sign_points and rnd.random() < 0.6:
        si = rnd.randrange(len(w.sign_points))
        kl, js = w.sign_points[si]
        jl = max(0, js - rnd.randrange(1, 6))
    else:
        si = None
        kl, jl = 0, rnd.randrange(0, 8)
    line = rnd.randrange(LINES)
    place_me(rnd, w, 0, kl, jl, line)
    others = [1, 2, 3, 4]

    def place(k, near):
        if si is not None and rnd.random() < 0.5:
            # Past the sign, where the walk's points carry an offset.
            b, j2 = w.sign_to[si]
            place_other(rnd, w, sizes, k, b, max(0, j2 - 1), near, span=4)
        else:
            # Mostly within the walk's look-ahead, about five points.
            place_other(rnd, w, sizes, k, kl, jl, near,
                        span=rnd.choice((7, 7, 18)))

    for k in others:
        place(k, rnd.random() < 0.6)
    # Not on the list.
    place_other(rnd, w, sizes, 5, kl, jl)
    ops += place_list(w, 0, others)
    for i in range(w.nsign):
        ops.append("Q %d %d %d" % (i, rnd.choice((0, 1, 1, 1)),
                                   rnd.choice((-1, -1, rnd.randrange(LINES)))))
    for _ in range(40):
        if rnd.random() < 0.5:
            place(rnd.choice(others), rnd.random() < 0.6)
        if rnd.random() < 0.25:
            place_me(rnd, w, 0, kl, jl, line)
        if rnd.random() < 0.2:
            ops += place_list(w, 0, others)
        ops.append("G TIMER %08x" % rnd.choice((0, 1000, 5000, 77777)))
        if rnd.random() < 0.3:
            ops.append("G TRAFFIC %08x" % rnd.choice((0, 1)))
        if rnd.random() < 0.1:
            ops.append("G SLOWCAR %s" % h(f32(rnd.choice((20.0, 9.0,
                                                            30.0)))))
            ops.append("G SLOWTRAFFIC %s" % h(f32(rnd.choice((10.0, 4.0,
                                                               25.0)))))
        if rnd.random() < 0.15:
            ops.append("G SECS %s" % h(f32(rnd.choice((2.0, 0.5, 6.0)))))
            ops.append("G DEF %s" % h(f32(rnd.choice((20.0, 60.0, 150.0)))))
        if rnd.random() < 0.05:
            ops.append("D -1 -1 %d 00000000" % line)
        else:
            ops.append("D %d %d %d 00000000" % (
                kl, max(0, jl + rnd.choice((0, 0, 1, -1))),
                line if rnd.random() < 0.8 else rnd.randrange(LINES)))
        t = rnd.choice((5, 6, 5, 6, 5, 6, 1, 2, 3, 4, 0, 7))
        k = rnd.choice(others)
        if rnd.random() < 0.5:
            if rnd.random() < 0.1:
                k = rnd.choice((5, -1))
            ops.append("X %d %d %d" % (t, k, rnd.choice((0, 1))))
            ops += its_target(rnd, w, sizes, 0, kl, jl)
            ops.append("v %d" % rnd.choice((0, 1, 2)))
        else:
            ops.append("X %d %d %d" % (rnd.choice((5, 6)), k,
                                       rnd.choice((0, 1))))
            if rnd.random() < 0.4:
                ops.append("T %d 00000000" % rnd.randrange(64))
            else:
                kk, jj = near_sign(rnd, w, sizes)
                if rnd.random() < 0.5:
                    kk, jj = kl, min(sizes[kl] - 2, jl + rnd.randrange(0, 3))
                ops += target_on(rnd, w, sizes, kk, jj,
                                 rnd.choice((1, 2, 4, 8)),
                                 rnd.randrange(LINES))
            ops.append("w")
        if rnd.random() < 0.3:
            ops += decide(rnd, w)
    return ops


def s_sign_pass(rnd):
    """Round a car just past a sign onto a route that carries straight on
    a metre or two to one side, so the walk's points there carry a small
    offset that the passing point keeps."""
    w = World(rnd)
    ops = w.ops
    sizes = [40, 30, 30, 25, 20]
    js = rnd.randrange(8, 20)
    rns = rnd.sample(range(0, 50), 3)
    pts0 = w.route(0, sizes[0], rns[0], signs={js: 0})
    p = pts0[js + 1]
    x, y = beside(p, rnd.uniform(-3.0, 3.0))
    w.route(1, sizes[1], rns[1], x=x, y=y, hd=heading_of(p), turn=0.0)
    w.route(2, sizes[2], rns[2])
    w.route(3, sizes[3], rnd.randrange(50, 60), rtype=1)
    w.route(4, sizes[4], rnd.randrange(60, 70), rtype=1)
    w.sign(1, 0)
    w.sign_points = [(0, js)]
    line = rnd.randrange(LINES)
    jl = js - rnd.randrange(1, 4)
    place_me(rnd, w, 0, 0, jl, line, dtype=rnd.choice((2, 2, 0, 3)))
    others = [1, 2, 3, 4]
    for k in others:
        place_other(rnd, w, sizes, k, 1, -1, rnd.random() < 0.6, span=5)
    ops += place_list(w, 0, others)
    for _ in range(30):
        ops.append("Q 0 %d -1" % rnd.choice((1, 1, 1, 0)))
        # A look-ahead long enough to reach well past the sign.
        ops.append("G SECS %s" % h(f32(rnd.choice((2.0, 6.0, 10.0)))))
        ops.append("G DEF %s" % h(f32(rnd.choice((20.0, 150.0)))))
        if rnd.random() < 0.5:
            place_other(rnd, w, sizes, rnd.choice(others), 1, -1,
                        rnd.random() < 0.6, span=5)
        if rnd.random() < 0.3:
            place_me(rnd, w, 0, 0, jl, line, dtype=rnd.choice((2, 2, 0, 3)))
        ops.append("G TIMER %08x" % rnd.choice((0, 1000, 77777)))
        ops.append("D 0 %d %d 00000000" % (jl, line))
        k = rnd.choice(others)
        ops.append("X %d %d %d" % (rnd.choice((5, 6)), k, rnd.choice((0, 1))))
        if rnd.random() < 0.5:
            ops += its_target(rnd, w, sizes, 0, 0, jl)
            ops.append("v %d" % rnd.choice((0, 1, 2)))
        else:
            ops.append("T %d 00000000" % rnd.randrange(64))
            ops.append("w")
    return ops


def s_pieces(rnd):
    """The pieces on their own, over lists made by hand on racing and
    traffic routes: the closest point ahead from anywhere, the clearance
    beside cars either side of each speed that matters, the smooth way out
    to every index either way, and the target alongside a car level with
    this one, its own target running either way."""
    w = World(rnd)
    ops = w.ops
    sizes = walk_world(rnd, w, nsigns=0)
    j0 = rnd.randrange(0, 6)
    line = rnd.randrange(LINES)
    me = place_me(rnd, w, 0, 0, j0, line)
    others = [1, 2, 3, 4]
    for k in others:
        place_other(rnd, w, sizes, k, 0, j0, near=True)
    ops += place_list(w, 0, others)
    for _ in range(12):
        kf = rnd.choice((0, 0, 0, 3, 4))
        pts = w.pts[kf]
        ops.append("F")
        n = rnd.choice((0, 1, 2, 3, 4, 5, 8, 12, 20))
        js = rnd.randrange(0, sizes[kf] - max(n, 1))
        fl = []
        for i in range(n):
            ln = line if rnd.random() < 0.8 else rnd.randrange(LINES)
            # Now and then the same point twice, for a tie.
            jj = js + i - 1 if i and rnd.random() < 0.15 else js + i
            fo = rnd.choice((0.0, 0.0, rnd.uniform(-2.0, 2.0)))
            fl.append((jj, ln, f32(fo)))
            ops.append("m %d %d %d %s 0" % (w.rn[kf], jj, ln, h(f32(fo))))
        for _ in range(6):
            p = pts[max(0, min(sizes[kf] - 1, js + rnd.randrange(-2, n + 3)))]
            if rnd.random() < 0.15:
                x, y = p["x"], p["y"]       # on the point: not ahead
            else:
                x, y = beside(p, rnd.uniform(-8.0, 8.0),
                              rnd.choice((0.0, -0.01, 0.01,
                                          rnd.uniform(-20.0, 20.0))))
            ops.append("x %s %s %d" % (h(f32(x)), h(f32(y)),
                                       rnd.choice((-3, -1, 0, 0, 1, 2, n - 1,
                                                   n, n + 2))))
        # The clearance: the car close beside where this one would be,
        # at each speed either side of the slow ones.
        for _ in range(8 if n else 2):
            e = rnd.randrange(4)
            k = others[e]
            if n:
                i = rnd.randrange(n)
                jj, ln, fo = fl[i]
                p0 = pts[fl[0][0]]
                mine = (lateral_of(p0, me["px"], me["py"])
                        - off_of(p0, fl[0][1]) + fl[0][2])
                lat = (mine + off_of(pts[jj], ln) - fo
                       + rnd.choice((0.0, 2.0, -3.5, 5.0, -7.0,
                                     rnd.uniform(-9.0, 9.0))))
                car_at_point(rnd, w, k, kf, jj, lat, False,
                             vmag=rnd.choice((
                                 9.99, 10.0, 10.01, 10.5, 19.99, 20.0, 20.01,
                                 20.5, 25.0, -10.0, -10.5, -15.0, -20.0,
                                 -20.5, -25.0, 0.0)),
                             dtype=rnd.choice((3, 3, 2, 1, 4)))
            me = dict(me, dtype=rnd.choice((3, 2, 2, 0)))
            w.cars[0] = me
            ops.append(car_op(0, me))
            ops.append("y %d %d" % (rnd.choice((e, e, e, -1)),
                                    rnd.choice((-1,) + tuple(range(n)))))
        for _ in range(4):
            if rnd.random() < 0.5:
                ops.append("T %d 00000000" % rnd.randrange(64))
            else:
                ops += target_on(rnd, w, sizes, kf, max(0, js - 1),
                                 rnd.choice((1, 2, 5, 18, 19, 20)), line)
            fr = rnd.choice((0.0, 1.5, -2.0, rnd.uniform(-6.0, 6.0)))
            to = rnd.choice((fr, 0.0, 3.0, -3.0, rnd.uniform(-8.0, 8.0)))
            ops.append("z %d %s %s %d" % (rnd.randrange(0, n + 2),
                                          h(f32(fr)), h(f32(to)),
                                          rnd.choice((0, 1))))
        # Alongside: the car level with this one, its target along the
        # list's route either way, cached or not.
        for _ in range(4):
            k = rnd.choice(others)
            if rnd.random() < 0.6:
                jo = js + rnd.randrange(0, max(1, n))
                car_at_point(rnd, w, k, kf, min(sizes[kf] - 1, jo),
                             rnd.uniform(-4.0, 4.0), True)
                rev = rnd.random() < 0.5
                ops.extend(its_target(rnd, w, sizes, k,
                                      rnd.choice((kf, kf, 3, 4)),
                                      jo + (rnd.randrange(2, 8) if rev
                                            else 0), rev))
            if rnd.random() < 0.3:
                me = place_me(rnd, w, 0, 0, j0, line)
            ops.append("G TIMER %08x" % rnd.choice((0, 1000, 5000, 77777)))
            ops.append("X %d %d 0" % (rnd.choice((5, 6)), k))
            if rnd.random() < 0.5:
                ops.append("T %d 00000000" % rnd.randrange(64))
            else:
                ops += target_on(rnd, w, sizes, kf, max(0, js - 1),
                                 rnd.choice((1, 2, 5, 18, 19, 20)), line)
            ops.append("M %s" % h(f32(rnd.choice((0.0, 3.5, -3.5,
                                                  rnd.uniform(-9.0, 9.0))))))
    return ops


def s_back(rnd):
    """Lists and targets that run back on themselves: the smooth way out
    over a list that doubles back, so a point before the last is further
    from the first than the last is, and the target alongside a car on a
    traffic route whose own target runs back down the list, so that each
    point's search for the road starts where the last one's ended."""
    w = World(rnd)
    ops = w.ops
    sizes = walk_world(rnd, w, nsigns=0)
    kf = rnd.choice((3, 4, 3, 4, 0))
    pts = w.pts[kf]
    line = rnd.randrange(LINES)

    def along(k, j, lat, sp, **kw):
        p = pts[j]
        hd = heading_of(p) + rnd.choice((0.0, 0.0, 0.1, -0.2))
        x, y = beside(p, lat, rnd.uniform(-2.0, 2.0))
        args = dict(px=x, py=y, bx=math.cos(hd), by=math.sin(hd), vmag=sp,
                    vx=sp * math.cos(hd), vy=sp * math.sin(hd), nw=4,
                    fs=rnd.choice((0.0, 25.0, 35.0)), oob=0.0)
        args.update(kw)
        return w.car(k, **args)

    js = rnd.randrange(0, 4)
    along(0, js, off_of(pts[js], line), rnd.choice((20.0, 35.0)),
          dtype=rnd.choice((2, 3, 0)))
    others = [1, 2, 3, 4]
    for k in others:
        along(k, js + rnd.randrange(0, 8), rnd.uniform(-4.0, 4.0),
              rnd.choice((12.0, 30.0)), pl=rnd.choice((0, 1)),
              dtype=rnd.choice((1, 2, 3, 4)))
    ops += place_list(w, 0, others)
    for _ in range(30):
        n = rnd.randrange(8, 14)
        back = rnd.random() < 0.5
        ops.append("F")
        jj = js
        for i in range(n):
            if back and i and rnd.random() < 0.3:
                # Two or three points on, then back to where it was.
                jx = min(sizes[kf] - 1, jj + rnd.randrange(2, 4))
            else:
                jx = jj
                jj = min(sizes[kf] - 1, jj + 1)
            ln = line if rnd.random() < 0.8 else rnd.randrange(LINES)
            fo = rnd.choice((0.0, 0.0, rnd.uniform(-1.0, 1.0)))
            ops.append("m %d %d %d %s 0" % (w.rn[kf], jx, ln, h(f32(fo))))
        ops.append("T %d 00000000" % rnd.randrange(64))
        if back or rnd.random() < 0.3:
            # Out by a little, on a road wide enough not to stop it.
            fr = rnd.choice((0.0, -1.5, 1.0))
            to = fr + rnd.choice((1.0, 2.5, 4.0, -1.0, -2.5))
            for _ in range(3):
                ops.append("z %d %s %s %d" % (rnd.randrange(3, n + 2),
                                              h(f32(fr)), h(f32(to)),
                                              rnd.choice((0, 0, 1))))
            continue
        k = rnd.choice(others)
        jo = js + rnd.randrange(0, n - 2)
        along(k, jo, rnd.uniform(-4.0, 4.0), rnd.choice((12.0, 30.0)),
              pl=rnd.choice((0, 1)), dtype=rnd.choice((1, 2, 3, 4)))
        kt = kf if kf != 0 else rnd.choice((3, 4))
        rev = rnd.random() < 0.7
        jt = jo + rnd.randrange(2, 9) if rev else jo
        ops += its_target(rnd, w, sizes, k, kt, jt, rev)
        ops.append("G TIMER %08x" % rnd.choice((0, 1000, 77777)))
        ops.append("X %d %d 0" % (rnd.choice((5, 6)), k))
        ops.append("M %s" % h(f32(rnd.choice((3.5, -3.5, 6.0, -6.0, 9.0,
                                               -9.0,
                                               rnd.uniform(-12.0, 12.0))))))
    return ops


# ------------------------------------------- CarCollisionPredict (11b-4a)


def bam_of(a):
    return int(round(a / (2.0 * math.pi) * 65536.0)) & 0xffff


def extras(rnd, k, hd, flip=None):
    """Car k's acceleration, velocity z, angle (about its heading, now and
    then anything) and box: mostly a car's, now and then lopsided, inside
    out on an axis or flat; inside out on axis `flip` when it is given."""
    if rnd.random() < 0.1:
        ang = rnd.randrange(65536)
    else:
        ang = bam_of(hd + rnd.choice((0.0, 0.0, 0.0, 0.05, -0.3)))
    acc = rnd.choice(((0.0, 0.0), (0.0, 0.0),
                      (rnd.uniform(-3.0, 3.0), rnd.uniform(-3.0, 3.0)),
                      (rnd.uniform(-15.0, 15.0), rnd.uniform(-15.0, 15.0))))
    hl = rnd.choice((2.3, 2.5, rnd.uniform(1.6, 3.2)))
    hw = rnd.choice((0.9, 1.0, rnd.uniform(0.6, 1.4)))
    hz = rnd.choice((0.7, rnd.uniform(0.4, 1.0)))
    off = rnd.choice((0.0, 0.0, rnd.uniform(-0.5, 0.5)))
    mn = [-hl + off, -hw, -hz]
    mx = [hl + off, hw, hz]
    r = rnd.random()
    if flip is not None:
        mn[flip], mx[flip] = mx[flip], mn[flip]
    elif r < 0.06:
        i = rnd.randrange(3)
        mn[i], mx[i] = mx[i], mn[i]
    elif r < 0.09:
        mx[2] = mn[2]
    vz = rnd.choice((0.0, 0.0, rnd.uniform(-2.0, 2.0)))
    return "A %d %s %s %s %d %s" % (
        k, h(f32(acc[0])), h(f32(acc[1])), h(f32(vz)), ang,
        " ".join(h(f32(x)) for x in mn + mx))


def mover(rnd, w, k, x, y, hd, speed, back=False, flip=None, **kw):
    """Car k at (x, y) heading hd at `speed`, sliding a little; backing up
    when `back`. A car at 1 m/s or more has a velocity to go by."""
    slip = hd + rnd.choice((0.0, 0.0, 0.0, 0.1, -0.15))
    vel = abs(speed)
    if vel < 1.0 and rnd.random() < 0.5:
        vel = 0.0
    vd = slip + (math.pi if back else 0.0)
    fs = -vel if back else vel * rnd.choice((1.0, 1.0, 0.98))
    args = dict(px=x, py=y, bx=math.cos(hd), by=math.sin(hd), vmag=speed,
                vx=max(vel, 1e-3) * math.cos(vd),
                vy=max(vel, 1e-3) * math.sin(vd), fs=fs,
                nw=rnd.choice((4, 4, 3)),
                pl=rnd.choice((0, 0, 0, 1)),
                dtype=rnd.choice((1, 2, 2, 3, 3, 4, 5)),
                ctl=rnd.choice((1, 2, 2, 3, 3, 4)),
                act=rnd.choice((-1, 5, 5, 7, 10, 11, 0, 6)),
                oob=rnd.choice((0.0, -0.25, -0.2499, -0.2501, -1.0, 0.5,
                                -0.3)))
    args.update(kw)
    v = w.car(k, **args)
    w.ops.append(extras(rnd, k, hd, flip))
    return v


def lane_target(rnd, w, k, kr, j0, n, lat, rev=False):
    """Car k's own target (k -1: the target): n points along route kr from
    j0, forwards or back, lat across, now and then changing lane or
    doubling a point."""
    if k < 0:
        ops = ["T %d %s" % (rnd.randrange(64), h(f32(rnd.uniform(0, 80))))]
    else:
        ops = ["H %d %d %s %d %d %d" % (
            k, rnd.randrange(64), h(f32(rnd.uniform(0.0, 80.0))),
            rnd.choice((0, 0, 1, 2, 7)), rnd.choice((0, 1000, 5000)),
            rnd.choice((0, 1000)))]
    pts = w.pts[kr]
    j = j0
    last = None
    for i in range(n):
        if rnd.random() < 0.1:
            lat += rnd.choice((-3.5, 3.5, -1.0, 1.0))
        if last is not None and rnd.random() < 0.06:
            x, y = last
        else:
            j = max(0, min(len(pts) - 1, j))
            x, y = beside(pts[j], lat * (-1.0 if rev else 1.0),
                          rnd.uniform(-1.0, 1.0))
        last = (x, y)
        f = "%s %s %s %d %d %d %s" % (
            h(f32(x)), h(f32(y)), h(f32(rnd.uniform(-2.0, 2.0))), w.rn[kr],
            j, rnd.randrange(LINES), h(f32(rnd.uniform(0.0, 40.0))))
        ops.append(("Y " if k < 0 else "I %d " % k) + f)
        j += -1 if rev else 1
    return ops


def frame(me, x, y):
    """Where (x, y) is from car `me`: across (right) and ahead."""
    dx, dy = x - me["px"], y - me["py"]
    return (dx * me["by"] - dy * me["bx"], dx * me["bx"] + dy * me["by"])


SPEEDS_ME = (0.0, 0.0005, 0.001, 0.0011, 1.5, 1.999, 2.0, 2.001, 10.0, 20.0,
             30.0, 45.0, -3.0)


def s_predict(rnd):
    """WillIHitThisCar and WhoWillThisDriveTargetHit: my car along a route
    on a target of its points, and cars ahead going my way more slowly,
    coming the other way, crossing on a second route, alongside, stopped,
    behind and backing up, in every mode and action either side of each
    test, the traffic tuning mode on and off."""
    w = World(rnd)
    ops = w.ops
    turn = rnd.choice((0.0, 0.0, 0.02, -0.02, 0.05))
    pts = w.route(0, 40, rnd.randrange(50), smooth=True, turn=turn)
    jc = rnd.randrange(14, 26)
    pc = pts[jc]
    hd1 = heading_of(pc) + rnd.choice((math.pi / 2, -math.pi / 2, 0.7,
                                       2.4))
    w.route(1, 30, rnd.randrange(50, 70), smooth=True, turn=0.0,
            x=pc["x"] - 150.0 * math.cos(hd1),
            y=pc["y"] - 150.0 * math.sin(hd1), hd=hd1 - 0.0)
    lanes = (-3.5, 0.0, 3.5)
    others = [1, 2, 3, 4, 5, 6]

    def place_me():
        j0 = rnd.randrange(2, 8)
        lat = rnd.choice(lanes) + rnd.uniform(-0.5, 0.5)
        p = pts[j0]
        x, y = beside(p, lat, rnd.uniform(-3.0, 3.0))
        hd = heading_of(p) + rnd.choice((0.0, 0.0, 0.05, -0.08))
        sp = rnd.choice(SPEEDS_ME)
        back = rnd.random() < 0.12
        me = mover(rnd, w, 0, x, y, hd, sp, back=back,
                   ctl=rnd.choice((2, 2, 3, 3, 1)),
                   dtype=rnd.choice((2, 2, 3, 3, 4)))
        n = rnd.choice((0, 1, 2, 4, 8, 12, 20, 20))
        ops.extend(lane_target(rnd, w, -1, 0, j0 + rnd.choice((0, 1, 1, 2)),
                               n, lat))
        if n and rnd.random() < 0.08:
            # The first point on the car: a first leg of 0.
            ops.append("T 0 00000000")
            ops.append("Y %s %s 00000000 %d %d 0 00000000" % (
                h(f32(x)), h(f32(y)), w.rn[0], j0))
            ops.extend(lane_target(rnd, w, -1, 0, j0 + 1, n, lat)[1:])
        return me, j0, lat

    def place(k, me, j0):
        kind = rnd.choice(("follow", "follow", "oncoming", "oncoming",
                           "cross", "beside", "stopped", "behind", "back"))
        sp = rnd.choice((0.0, 0.5, 4.9, 5.0, 5.01, 8.0, 15.0, 25.0, 35.0,
                         -4.0))
        lat = rnd.choice(lanes) + rnd.uniform(-0.6, 0.6)
        rev = False
        back = False
        kr = 0
        if kind == "follow":
            j = j0 + rnd.randrange(1, 8)
        elif kind == "oncoming":
            j = j0 + rnd.randrange(3, 16)
            rev = True
        elif kind == "cross":
            kr = 1
            j = rnd.randrange(6, 14)
        elif kind == "beside":
            j = j0
            lat = rnd.choice((lat + 3.5, lat - 3.5, lat + 2.0))
        elif kind == "stopped":
            j = j0 + rnd.randrange(1, 4)
            sp = rnd.choice((0.0, 0.0, 2.0, 4.99, 5.0, 5.001, -2.0))
        elif kind == "behind":
            j = max(0, j0 - rnd.randrange(1, 3))
        else:
            j = j0 + rnd.randrange(1, 6)
            back = True
        p = w.pts[kr][min(j, len(w.pts[kr]) - 1)]
        x, y = beside(p, lat * (-1.0 if rev else 1.0),
                      rnd.uniform(-4.0, 4.0))
        hd = heading_of(p) + (math.pi if rev else 0.0) + rnd.choice(
            (0.0, 0.0, 0.1, -0.1))
        mover(rnd, w, k, x, y, hd, sp, back=back)
        ops.extend(lane_target(rnd, w, k, kr, j + (-1 if rev else 1),
                               rnd.choice((0, 1, 3, 6, 10, 20)), lat,
                               rev=rev))

    def put_list(me):
        cars = list(others)
        rnd.shuffle(cars)
        cars = cars[:rnd.choice((0, 1, 3, 6, 6))]
        ops.append("N 0 %d %s %s" % (len(cars),
                                     h(f32(rnd.uniform(0.8, 1.2))),
                                     h(f32(rnd.uniform(2.0, 2.6)))))
        for i, k in enumerate(cars):
            v = w.cars[k]
            lx, ly = frame(me, v["px"], v["py"])
            if rnd.random() < 0.1:
                lx, ly = rnd.uniform(-3.0, 3.0), rnd.uniform(-5.0, 30.0)
            ops.append("E %d %s %s %s %s %s %s %d" % (
                i, h(f32(lx)), h(f32(ly)), h(f32(rnd.uniform(-5.0, 5.0))),
                h(f32(rnd.uniform(-5.0, 5.0))),
                h(f32(rnd.uniform(0.8, 1.3))),
                h(f32(rnd.uniform(2.0, 2.8))), k))
        return len(cars)

    me, j0, lat0 = place_me()
    for k in others:
        place(k, me, j0)
    nl = put_list(me)
    ops.append("D 0 %d 0 00000000" % j0)
    for _ in range(30):
        r = rnd.random()
        if r < 0.15:
            me, j0, lat0 = place_me()
            nl = put_list(me)
        elif r < 0.45:
            place(rnd.choice(others), me, j0)
            if rnd.random() < 0.5:
                nl = put_list(me)
        if rnd.random() < 0.3:
            ops.append("G TIMER %08x" % rnd.choice((0, 1000, 5000)))
        if rnd.random() < 0.15:
            ops.append("G TRAFFIC %08x" % rnd.choice((0, 1)))
        if rnd.random() < 0.15:
            ops.append("G SECS %s" % h(f32(rnd.choice((2.0, 0.5, 4.0)))))
            ops.append("G DEF %s" % h(f32(rnd.choice((20.0, 8.0, 60.0)))))
        if rnd.random() < 0.2:
            ops.append("Z 0 %d" % rnd.choice([-1] + others))
        for e in range(nl):
            if rnd.random() < 0.3:
                ops.append("5 %d" % e)
        for _ in range(rnd.choice((1, 2, 3))):
            ops.append("6 %d %s" % (rnd.choice(others), h(f32(rnd.choice((
                0.0, 0.5, 1.0, 2.0, 3.0, 5.0, 5.0, 10.0, -1.0))))))
        if rnd.random() < 0.08:
            # Who's bounds on the count. Past 20 the target overflows, so
            # only Who sees it, and then my car is placed again.
            ops.append("S %d" % rnd.choice((0, -1, 21, 20, 100)))
            ops.append("7 %s 0" % h(f32(5.0)))
            me, j0, lat0 = place_me()
            nl = put_list(me)
        if rnd.random() < 0.06:
            ops.append("D -1 -1 0 00000000")
        elif rnd.random() < 0.1:
            ops.append("D 0 %d 0 00000000" % j0)
        ops.append("7 %s %d" % (h(f32(rnd.choice((0.5, 2.0, 3.0, 5.0,
                                                   10.0)))),
                                1 if rnd.random() < 0.05 else 0))
    return ops


def s_parts(rnd):
    """IntervalOverlap, TimeIntervalForSeparatingAxis and
    WhenWillOverlapOccur2D on their own, at every edge, and
    MakeOBBsForDriveTarget over targets of every length and none."""
    w = World(rnd)
    ops = w.ops

    def fv(*c):
        return h(f32(rnd.choice(c)))

    ends = (-9999.0, -5.0, -1.0, -0.5, 0.0, 0.0, 0.5, 1.0, 2.0, 5.0, 9999.0,
            99999.0)
    for _ in range(150):
        e = [rnd.choice(ends + (rnd.uniform(-10.0, 10.0),)) for _ in range(4)]
        if rnd.random() < 0.6:
            e[0], e[1] = min(e[0], e[1]), max(e[0], e[1])
            e[2], e[3] = min(e[2], e[3]), max(e[2], e[3])
        ops.append("1 " + " ".join(h(f32(x)) for x in e))
    still = 9.99999975e-05
    for _ in range(150):
        v = rnd.choice((0.0, still, -still, f32(still * 1.0000001),
                        f32(still * 0.9999999), -f32(still * 1.0000001),
                        rnd.uniform(-30.0, 30.0), rnd.uniform(-0.01, 0.01)))
        d = rnd.choice((0.0, 2.0, -2.0, rnd.uniform(-50.0, 50.0)))
        r = rnd.choice((abs(d), 2.0, rnd.uniform(0.0, 8.0), 0.0))
        ops.append("2 %s %s %s" % (h(f32(v)), h(f32(d)), h(f32(r))))
    for _ in range(250):
        boxes = []
        for _b in range(2):
            a = rnd.uniform(-math.pi, math.pi)
            ax = [math.cos(a), math.sin(a), -math.sin(a), math.cos(a)]
            if rnd.random() < 0.25:
                # Axes no turn makes. A box from MakeOBBs is turned, and
                # then each cosine across is the other's size.
                b = rnd.uniform(-math.pi, math.pi)
                ax[2:] = [math.cos(b), math.sin(b)]
            boxes += ax + [
                      rnd.choice((2.3, rnd.uniform(0.5, 4.0), -2.0)),
                      rnd.choice((1.0, rnd.uniform(0.3, 2.0)))]
        dx, dy = rnd.uniform(-30.0, 30.0), rnd.uniform(-30.0, 30.0)
        if rnd.random() < 0.2:
            dx, dy = rnd.uniform(-2.0, 2.0), rnd.uniform(-2.0, 2.0)
        sp = rnd.choice((0.0, 1e-5, rnd.uniform(0.0, 40.0)))
        if rnd.random() < 0.7:
            # Mostly closing on each other.
            ln = math.hypot(dx, dy) or 1.0
            vx, vy = -dx / ln * sp, -dy / ln * sp
            vx += rnd.uniform(-3.0, 3.0)
            vy += rnd.uniform(-3.0, 3.0)
        else:
            vx, vy = rnd.uniform(-30.0, 30.0), rnd.uniform(-30.0, 30.0)
        if rnd.random() < 0.1:
            vx = 0.0
        ops.append("3 " + " ".join(h(f32(x)) for x in
                                   boxes + [dx, dy, vx, vy]))
    # The edges no draw lands on: ends that touch, -0 against 0, and two
    # square boxes 2 m apart on x, closing or parting at 1 m/s, which touch
    # at -0 and at 0.
    ops += ["1 00000000 3f800000 80000000 40000000",
            "1 00000000 3f800000 3f800000 40000000",
            "1 3f800000 40000000 00000000 3f800000",
            "1 80000000 00000000 00000000 3f800000",
            "1 00000000 3f800000 80000000 80000000",
            "1 bf800000 3f800000 80000000 00000000"]
    sq = "3f800000 00000000 00000000 3f800000 3f800000 3f800000"
    for v in ("bf800000", "3f800000"):
        ops.append("3 %s %s 40000000 00000000 %s 00000000" % (sq, sq, v))
    pts = w.route(0, 30, rnd.randrange(50), turn=rnd.choice((0.0, 0.1)))
    for k in range(3):
        p = pts[rnd.randrange(5)]
        mover(rnd, w, k, p["x"], p["y"], heading_of(p), 10.0)
    for _ in range(40):
        if rnd.random() < 0.3:
            k = rnd.randrange(3)
            p = pts[rnd.randrange(5)]
            mover(rnd, w, k, p["x"], p["y"], rnd.uniform(-3.2, 3.2), 10.0)
        t = rnd.choice((-1, -1, 0, 1, 2))
        n = rnd.choice((0, 1, 2, 5, 12, 20))
        ops.extend(lane_target(rnd, w, t, 0, rnd.randrange(8), n,
                               rnd.uniform(-4.0, 4.0),
                               rev=rnd.random() < 0.2))
        z = rnd.choice((0, 0, 0, 0, 1, 2))
        ops.append("4 %d %d %s %d" % (t, rnd.choice((0, 1, 2, 2, -1)),
                                      fv(1.0, 1.3, 1000.0, 0.0, -1.0),
                                      z))
    # A box inside out on each axis in turn, so the half sizes' fabsf
    # shows.
    for ax in (0, 1, 2):
        p = pts[rnd.randrange(5)]
        mover(rnd, w, 0, p["x"], p["y"], heading_of(p), 10.0, flip=ax)
        ops.extend(lane_target(rnd, w, -1, 0, rnd.randrange(8), 3, 0.0))
        for sc_ in ("3f800000", "bf800000"):
            ops.append("4 -1 0 %s 0" % sc_)
    return ops


def exact_target(w, k, kr, j, n, lat, rev=False, picked=True):
    """Car k's own target (k -1: the target): n points on route kr's own
    points from j, `lat` across in the route's frame, nothing jittered.
    With `picked`, the first point is cached as the one picked at time 0
    and the blend's time is 0, so at WorldTimer 0 neither GetFirstPoint
    nor the blend touches it."""
    pts = w.pts[kr]
    if k < 0:
        ops = ["T 0 00000000"]
    else:
        ops = ["H %d 0 00000000 0 0 0" % k if picked
               else "H %d 0 00000000 0 1000 1000" % k]
    for i in range(n):
        jj = j - i if rev else j + i
        if not 0 <= jj < len(pts):
            break
        x, y = beside(pts[jj], lat)
        f = "%s %s 00000000 %d %d 0 00000000" % (h(f32(x)), h(f32(y)),
                                                 w.rn[kr], jj)
        ops.append(("Y " if k < 0 else "I %d " % k) + f)
    return ops


# A backing car's actions, accident recovery twice.
BACK_ACTS = (-1, 5, 7, 10, 10, 11, 0, 6)


def s_meet(rnd):
    """WillIHitThisCar where the two cars do meet, a second or more on:
    head on, catching one up, at a crossing, one backing into the other,
    both at one speed on the route's own points (so their legs end
    together), and both crawling apart, where a step runs past 99999.
    Who over the same two, either side of the hit."""
    w = World(rnd)
    ops = w.ops
    pts = w.route(0, 40, rnd.randrange(50), smooth=True,
                  turn=rnd.choice((0.0, 0.0, 0.02, -0.02)))
    jc = rnd.randrange(18, 26)
    pc = pts[jc]
    hd1 = heading_of(pc) + rnd.choice((math.pi / 2, -math.pi / 2, 0.8,
                                       2.3))
    # Straight, so the crossing is its point 15.
    w.route(1, 30, rnd.randrange(50, 70), smooth=True, turn=0.0,
            x=pc["x"] - 150.0 * math.cos(hd1),
            y=pc["y"] - 150.0 * math.sin(hd1), hd=hd1)

    def flip():
        return rnd.choice((None,) * 8 + (0, 1, 2))

    def place(k, kr, j, lat, along, rev, sp, back=False, **kw):
        p = w.pts[kr][max(0, min(len(w.pts[kr]) - 1, j))]
        x, y = beside(p, lat, along)
        hd = heading_of(p) + (math.pi if rev else 0.0)
        return mover(rnd, w, k, x, y, hd, sp, back=back, flip=flip(), **kw)

    for _ in range(18):
        kind = rnd.choice(("headon", "catch", "cross", "cross", "back_me",
                           "back_me", "back_it", "back_it", "even", "slow"))
        timer = rnd.choice((7000, 7000, 7000, 0))
        lat = rnd.choice((-3.5, 0.0, 3.5))
        vm = rnd.choice((5.0, 10.0, 15.0, 20.0, 30.0))
        vi = rnd.choice((0.0, 4.0, 8.0, 12.0, 20.0, 28.0))
        when = rnd.uniform(0.6, 4.0)
        j0 = rnd.randrange(3, 8)
        kr, rev, back_me, back_it = 0, False, False, False
        lat_i = lat + rnd.uniform(-0.8, 0.8)
        along_i = rnd.uniform(-3.0, 3.0)
        mine = its = None
        kw_me, kw_it = {}, {}
        if kind == "cross":
            j0 = max(1, jc - max(1, int(round(vm * when / 10.0))))
            arrive = (jc - j0) * 10.0 / vm
            vi = rnd.choice((8.0, 12.0, 20.0, 28.0))
            dist = vi * arrive + rnd.uniform(-4.0, 4.0)
            n10 = int(dist // 10.0)
            kr, ji = 1, max(0, 15 - n10)
            along_i = -(dist - 10.0 * n10)
            lat_i = rnd.uniform(-2.0, 2.0)
        elif kind == "headon":
            ji = j0 + max(2, int(round((vm + vi) * when / 10.0)))
            rev = True
        elif kind == "catch":
            vi = min(vi, vm * 0.6)
            ji = j0 + 1 + max(1, int(round((vm - vi) * when / 10.0)))
        elif kind == "back_me":
            ji = j0 - rnd.choice((1, 2, 3))
            vm = rnd.choice((3.0, 6.0, 10.0, 15.0))
            vi = rnd.choice((0.0, 0.0, 4.0, 10.0))
            rev = rnd.random() < 0.3
            back_me = True
            kw_me["act"] = rnd.choice(BACK_ACTS)
            if rnd.random() < 0.3:
                # Under 1 m/s, so predicted along my body, away from it:
                # it catches mine up sooner or later by my speed.
                kw_me["vmag"] = -vm
                vi = rnd.choice((4.0, 10.0))
                rev = False
        elif kind == "back_it":
            ji = j0 + rnd.choice((1, 2, 3))
            vm = rnd.choice((0.0, 0.0005, 5.0, 10.0))
            vi = rnd.choice((3.0, 6.0, 10.0, 15.0))
            back_it = True
            kw_it["ctl"] = rnd.choice((1, 2, 2, 3, 3, 4))
            kw_it["act"] = rnd.choice(BACK_ACTS)
            if rnd.random() < 0.4:
                # Under 1 m/s, so predicted along its body, away from me:
                # mine catches it up, or not, by its speed.
                kw_it["vmag"] = -vi
                vm = rnd.choice((5.0, 10.0))
        elif kind == "even":
            vm = vi = rnd.choice((10.0, 20.0))
            ji = j0 + rnd.choice((2, 3, 4, 6))
            rev = rnd.random() < 0.6
            lat_i, along_i = lat, 0.0
            timer = 0
            kw_me.update(dtype=2, pl=0)
            kw_it.update(dtype=2, pl=0)
            mine = exact_target(w, -1, 0, j0 + 1, rnd.choice((4, 8, 12)),
                                lat)
            its = exact_target(w, 1, 0, ji - 1 if rev else ji + 1,
                               rnd.choice((4, 8, 12)), lat, rev=rev)
        else:
            # Both crawl, 0.001 m/s, apart: my first leg is 3 mm, so 3 s,
            # and the next two legs are 150 m, so the second step is past
            # 99999, never overlapping.
            ji = j0 - 2
            vm, vi = 0.0005, 0.0
            rev = True
            lat_i, along_i = lat, 0.0
            timer = 0
            kw_me.update(dtype=2, ctl=2, pl=0)
            kw_it.update(dtype=2, ctl=2, pl=0)
            p = pts[j0]
            a = beside(p, lat, 0.003)
            b = beside(p, lat, 150.003)
            mine = ["T 0 00000000"] + [
                "Y %s %s 00000000 %d %d 0 00000000" % (
                    h(f32(q[0])), h(f32(q[1])), w.rn[0], j0) for q in (a, b)]
            c = beside(pts[ji], lat, -150.0)
            its = ["H 1 0 00000000 0 0 0",
                   "I 1 %s %s 00000000 %d %d 0 00000000" % (
                       h(f32(c[0])), h(f32(c[1])), w.rn[0], ji)]
        if kind in ("headon", "catch", "cross") and rnd.random() < 0.4:
            # Traffic off the road, its target blended unless it is just
            # driving.
            kw_it.update(dtype=3, pl=0,
                         oob=rnd.choice((-0.25, -0.2501, -0.3, -1.0, 0.0)),
                         act=rnd.choice((5, 5, 5, 7, 10, -1, 0, 6)))
        ops.append("G TIMER %08x" % timer)
        ops.append("G TRAFFIC %08x" % (1 if rnd.random() < 0.1 else 0))
        me = place(0, 0, j0, lat, rnd.uniform(-1.0, 1.0)
                   if kind not in ("even", "slow") else 0.0, False, vm,
                   back=back_me, **kw_me)
        place(1, kr, ji, lat_i, along_i, rev, vi, back=back_it, **kw_it)
        if mine is None:
            n = rnd.choice((0, 3, 6, 10, 20))
            mine = lane_target(rnd, w, -1, 0, j0 + 1, n, lat)
        if its is None:
            n = rnd.choice((0, 3, 6, 10, 20))
            step = -1 if rev else 1
            its = lane_target(rnd, w, 1, kr, ji + step, n,
                              -lat_i if rev else lat_i, rev=rev)
        ops.extend(mine)
        ops.extend(its)
        lx, ly = frame(me, w.cars[1]["px"], w.cars[1]["py"])
        ops.append("N 0 1 %s %s" % (h(f32(rnd.uniform(0.8, 1.2))),
                                    h(f32(rnd.uniform(2.0, 2.6)))))
        ops.append("E 0 %s %s 00000000 00000000 %s %s 1" % (
            h(f32(lx)), h(f32(ly)), h(f32(rnd.uniform(0.8, 1.3))),
            h(f32(rnd.uniform(2.0, 2.8)))))
        ops.append("D 0 %d 0 00000000" % j0)
        for _w in range(2):
            ops.append("6 1 %s" % h(f32(rnd.choice((0.5, 1.0, 2.0, 3.0, 5.0,
                                                    10.0)))))
        ops.append("7 %s 0" % h(f32(rnd.choice((0.5, 1.0, 1.5, 2.0, 3.0,
                                                5.0)))))
    return ops


def s_stopped(rnd):
    """IsThisCarStoppedDirectlyInFrontOfMe either side of each bound:
    speeds either side of 5 m/s both ways, entries either side of the box
    across and of the 23 m ahead, and far behind."""
    w = World(rnd)
    ops = w.ops
    speeds = (0.0, 4.99, 5.0, 5.01, 8.0, -2.0, -4.99, -5.0, -5.01, -8.0)
    for k in range(7):
        w.car(k, vmag=rnd.choice(speeds))
    for _ in range(10):
        hl, hd = rnd.uniform(0.8, 1.2), rnd.uniform(2.0, 2.6)
        ops.append("N 0 6 %s %s" % (h(f32(hl)), h(f32(hd))))
        for i in range(6):
            L, D = rnd.uniform(0.8, 1.3), rnd.uniform(2.0, 2.8)
            lx = rnd.uniform(-1.3, 1.3) * (hl + L)
            r = rnd.random()
            if r < 0.45:
                ly = (hd + D) + 23.0 + rnd.uniform(-4.0, 1.0)
            elif r < 0.65:
                ly = -rnd.uniform(25.0, 60.0)
            else:
                ly = rnd.uniform(-10.0, 35.0)
            ops.append("E %d %s %s 00000000 00000000 %s %s %d" % (
                i, h(f32(lx)), h(f32(ly)), h(f32(L)), h(f32(D)),
                rnd.randrange(1, 7)))
        for i in range(6):
            ops.append("5 %d" % i)
        if rnd.random() < 0.5:
            w.car(rnd.randrange(1, 7), vmag=rnd.choice(speeds))
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
    # Step 11b-3's, after the rest so that theirs draw what they drew.
    for _ in range(8):
        sc.append(s_around(rnd))
        sc.append(s_pieces(rnd))
    for _ in range(4):
        sc.append(s_sign_pass(rnd))
    for _ in range(6):
        sc.append(s_back(rnd))
    # Step 11b-4a's.
    for _ in range(10):
        sc.append(s_predict(rnd))
    for _ in range(3):
        sc.append(s_parts(rnd))
    for _ in range(12):
        sc.append(s_meet(rnd))
    for _ in range(2):
        sc.append(s_stopped(rnd))
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
        self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        self.e.stub(SIGN_DECISION, self.s_sign)
        self.e.stub(GET_ROUTE_POINT, self.s_rp)
        self.e.stub(GET_OOB, self.s_oob)
        self.w = self.e.u32
        self.grace0 = self.w(GLOBALS["GRACE"])
        self.gap0 = self.w(GLOBALS["GAP"])
        self.traffic0 = self.w(GLOBALS["TRAFFIC"])
        self.slowcar0 = self.w(GLOBALS["SLOWCAR"])
        self.slowtraffic0 = self.w(GLOBALS["SLOWTRAFFIC"])
        d = struct.unpack("<f", struct.pack("<I", self.w(MIN_DIST)))[0]
        self.e.put32(MIN_DIST_SQ, fb(f32(d * d)))
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

    def dump_its(self):
        """What the choice's car's own target picked, if it has a car."""
        car = self.w(CHOICE + 4)
        if CARS <= car < CARS + CAR_STRIDE * NCARS:
            t = self.w(car + C_CDRIVER)
            self.emit("  its pk %d %d %d" % (s8(self.e.mem[t + 500]),
                                             s32(self.w(t + 504)),
                                             s32(self.w(t + 508))))

    def dump_target(self, t=TARGET):
        w, m = self.w, self.e.mem
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

    def dump_obbs(self):
        """The boxes written: up to the first whose a0 is still the fill.
        A position's w is the target point's, which a STACK-W point leaves
        to the stack, so only its x, y and z."""
        w = self.w
        n = 0
        while n < NOBBS and w(OBBS + OBB_SIZE * n + 64) != PAT32:
            n += 1
        self.emit("  obbs %d" % n)
        for i in range(n):
            o = OBBS + OBB_SIZE * i
            self.emit("    %d %s | %s | %s | %s | %s" % (
                i, " ".join(fx(w(o + 4 * j)) for j in range(3)),
                " ".join(fx(w(o + 16 + 4 * j)) for j in range(4)),
                " ".join(fx(w(o + 32 + 4 * j)) for j in range(4)),
                " ".join(fx(w(o + 48 + 4 * j)) for j in range(4)),
                " ".join(fx(w(o + 64 + 4 * j)) for j in range(3))))

    def put_obb(self, a, v):
        """A0's and A1's x and y, a0 and a1; the rest 0."""
        e = self.e
        e.mem[a:a + OBB_SIZE] = bytes(OBB_SIZE)
        for off, x in zip((16, 20, 32, 36, 64, 68), v):
            e.put32(a + off, int(x, 16))

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
        e.mem[CDRIVERS:CDRIVERS + CDRIVER_STRIDE * NCARS] = bytes(
            CDRIVER_STRIDE * NCARS)
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
        e.mem[BODIES:BODIES + BODY_STRIDE * NCARS] = bytes(
            BODY_STRIDE * NCARS)
        e.put32(WORLD + W_ID, 0)
        for name, v in (("TIMER", 0), ("RACE", RACE), ("WORLD", WORLD),
                        ("GRACE", self.grace0), ("GAP", self.gap0),
                        ("WILLIAMS", 0),
                        ("SECS", 0x40000000), ("DEF", 0x41a00000),
                        ("SIGNS", SIGNS), ("NSIGNS", NSIGNS),
                        ("TRAFFIC", self.traffic0),
                        ("SLOWCAR", self.slowcar0),
                        ("SLOWTRAFFIC", self.slowtraffic0)):
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
        e.put32(a + C_PLAYER, PLAYERS + PLAYER_STRIDE * k if v["pl"] else 0)
        e.put32(a + C_CDRIVER, CDRIVERS + CDRIVER_STRIDE * k)
        e.put32(a + C_VEL, v["vx"])
        e.put32(a + C_VEL + 4, v["vy"])
        e.put32(a + C_NW, v["nw"])
        e.put32(a + C_FS, v["fs"])
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

    def car_target(self, s):
        return CDRIVERS + CDRIVER_STRIDE * int(s)

    def put_point(self, t, v):
        """x y z rn j line sp, at the end of the target at t."""
        e = self.e
        n = e.mem[t]
        p = t + 16 + 16 * n
        for i in range(3):
            e.put32(p + 4 * i, int(v[i], 16))
        e.put32(p + 12, 0)
        e.mem[t + 416 + n] = int(v[3]) & 0xff
        struct.pack_into("<h", e.mem, t + 436 + 2 * n, int(v[4]))
        e.mem[t + 476 + n] = int(v[5]) & 0xff
        e.put32(t + 336 + 4 * n, int(v[6], 16))
        e.mem[t] = n + 1

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
            self.put_point(TARGET, t[1:])
        elif c == "H":
            a = self.car_target(t[1])
            e.mem[a:a + TARGET_BYTES] = bytes(TARGET_BYTES)
            e.put32(a + 496, int(t[2]))
            e.put32(a + 512, int(t[3], 16))
            e.mem[a + 516] = 0xff
            e.mem[a + 500] = int(t[4]) & 0xff
            e.put32(a + 504, int(t[5]))
            e.put32(a + 508, int(t[6]))
        elif c == "I":
            self.put_point(self.car_target(t[1]), t[2:])
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
        elif c in "vw":
            if c == "v":
                got = self.call(BUILD, CHOICE, TARGET, LOC, LIST, int(t[1]),
                                f12=0x3f800000, f13=0x40000000)
            else:
                got = self.call(AROUND, CHOICE, TARGET, LIST, LOC,
                                f12=0x3f800000)
            self.emit("  built %d" % got)
            self.dump_target()
            self.emit("  exclude %s" % self.name(
                w(w(w(LIST) + C_CTRL) + K_EXCLUDE)))
            self.dump_its()
        elif c == "x":
            e.put32(VEC, int(t[1], 16))
            e.put32(VEC + 4, int(t[2], 16))
            self.emit("  ahead %d" % s32(self.call(SEARCH, FPL, VEC,
                                                    int(t[3]))))
        elif c == "y":
            nc = self.entry(t[1]) if int(t[1]) >= 0 else 0
            self.call(CLEARANCE, CHOICE, LIST, nc, FPL, int(t[2]))
            self.emit("  clear %s" % fx(e.fpr[0]))
        elif c == "z":
            self.call(SMOOTH, FPL, TARGET, LIST, int(t[1]), int(t[4]),
                      f12=int(t[2], 16), f13=int(t[3], 16))
            self.dump_target()
        elif c == "M":
            self.call(PARALLEL, CHOICE, TARGET, LIST, FPL, f12=int(t[1], 16))
            self.dump_target()
            self.dump_its()
        elif c == "A":
            k = int(t[1])
            a = car_at(k)
            b = BODIES + BODY_STRIDE * k
            e.put32(a + C_ACC, int(t[2], 16))
            e.put32(a + C_ACC + 4, int(t[3], 16))
            e.put32(a + C_VEL + 8, int(t[4], 16))
            struct.pack_into("<H", e.mem, a + C_ANGLE, int(t[5]) & 0xffff)
            e.put32(a + C_BODY, b)
            for i in range(3):
                e.put32(b + B_MIN + 4 * i, int(t[6 + i], 16))
                e.put32(b + B_MAX + 4 * i, int(t[9 + i], 16))
        elif c == "Z":
            e.put32(w(self.car_ptr(t[1]) + C_CTRL) + K_EXCLUDE,
                    self.car_ptr(t[2]))
        elif c == "S":
            e.mem[TARGET] = int(t[1]) & 0xff
        elif c == "1":
            e.put32(OUT, PAT32)
            e.put32(OUT + 4, PAT32)
            got = self.call(OVERLAP, OUT, OUT + 4, f12=int(t[1], 16),
                            f13=int(t[2], 16), f14=int(t[3], 16),
                            f15=int(t[4], 16))
            self.emit("  ovl %d %s %s" % (got, fx(w(OUT)), fx(w(OUT + 4))))
        elif c == "2":
            e.put32(OUT, PAT32)
            e.put32(OUT + 4, PAT32)
            self.call(TISA, OUT, OUT + 4, f12=int(t[1], 16),
                      f13=int(t[2], 16), f14=int(t[3], 16))
            self.emit("  tisa %s %s" % (fx(w(OUT)), fx(w(OUT + 4))))
        elif c == "3":
            self.put_obb(OBB_A, t[1:7])
            self.put_obb(OBB_B, t[7:13])
            for i in range(4):
                e.put32(VEC_D + 4 * i, int(t[13 + i], 16) if i < 2 else 0)
                e.put32(VEC_V + 4 * i, int(t[15 + i], 16) if i < 2 else 0)
            self.call(WHEN_2D, OBB_A, OBB_B, VEC_D, VEC_V)
            self.emit("  when %s" % fx(e.fpr[0]))
        elif c == "4":
            z = int(t[4])
            tgt = TARGET if int(t[1]) < 0 else self.car_target(t[1])
            self.fill(OBBS, OBB_SIZE * NOBBS)
            self.call(MAKE_OBBS, 0, 0 if z & 1 else tgt,
                      0 if z & 2 else OBBS, self.car_ptr(t[2]),
                      f12=int(t[3], 16))
            self.dump_obbs()
        elif c == "5":
            got = self.call(STOPPED, 0, self.entry(t[1]), LIST)
            self.emit("  stopped %d" % got)
        elif c == "6":
            e.put32(OUT, PAT32)
            got = self.call(WILL, 0, TARGET, LOC, w(LIST), self.car_ptr(t[1]),
                            OUT, f12=int(t[2], 16))
            self.emit("  will %d %s" % (got, fx(w(OUT))))
        elif c == "7":
            e.put32(OUT, PAT32)
            got = self.call(WHO, 0, TARGET, LIST, 0 if int(t[2]) & 1 else LOC,
                            OUT, f12=int(t[1], 16))
            self.emit("  who %s %s id %d" % (self.name(got), fx(w(OUT)),
                                             w(WORLD + W_ID)))
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
        stray = self.e.eediv_pcs - {SMOOTH_DIV} - WILL_DIVS
        if stray:
            raise SystemExit("the EE's divide by zero at %s, which the port "
                             "divides as IEEE does"
                             % ", ".join("0x%08x" % pc for pc in sorted(stray)))
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
      "    if (other->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR\n"
      "        && other->State",
      "    if (other->MyDriver->TheDriverType != DRIVER_TYPE_TRAFFIC_CAR\n"
      "        && other->State"),
    M("fx-traffic-me",
      "    if (other->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR\n"
      "        && other->State",
      "    if (car->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR\n"
      "        && other->State"),
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
    M("rl-inside", "    if (inside) {\n        hi = (point->",
      "    if (!inside) {\n        hi = (point->"),
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
    M("fu-full", "loc->pRoutePoint);\n    if (!(t->NumPoints < DRIVETARGET_MAX_POINTS))",
      "loc->pRoutePoint);\n    if (!(t->NumPoints < DRIVETARGET_MAX_POINTS - 1))"),
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
    # -- 11b-3's literals and globals ----------------------------------
    M("k-extra-lateral", "#define DC_EXTRA_LATERAL     4.0f",
      "#define DC_EXTRA_LATERAL     3.0f"),
    M("k-far-off-road", "#define DC_FAR_OFF_ROAD      5.0f",
      "#define DC_FAR_OFF_ROAD      4.0f"),
    M("k-parallel-speed", "#define DC_PARALLEL_SPEED    5.0f",
      "#define DC_PARALLEL_SPEED    6.0f"),
    M("k-parallel-wheels", "#define DC_PARALLEL_WHEELS   3",
      "#define DC_PARALLEL_WHEELS   4"),
    M("k-parallel-wheels-lo", "#define DC_PARALLEL_WHEELS   3",
      "#define DC_PARALLEL_WHEELS   2"),
    M("k-same-heading", "#define DC_SAME_HEADING      0.707099974f",
      "#define DC_SAME_HEADING      0.75f"),
    M("k-no-edge", "#define DC_NO_EDGE           999999.0f",
      "#define DC_NO_EDGE           5.0f"),
    M("k-far-away", "#define DC_FAR_AWAY          1.0e14f",
      "#define DC_FAR_AWAY          10.0f"),
    M("k-search-step", "#define DC_SEARCH_STEP       0.0416666679f",
      "#define DC_SEARCH_STEP       0.0833333358f"),
    M("k-gap", "#define DC_GAP               2.0f",
      "#define DC_GAP               2.5f"),
    M("k-gap-player", "#define DC_GAP_PLAYER        1.5f",
      "#define DC_GAP_PLAYER        1.0f"),
    M("k-gap-slow", "#define DC_GAP_SLOW          6.0f",
      "#define DC_GAP_SLOW          5.0f"),
    M("g-traffic", "int32_t AITrafficTuningMode;",
      "int32_t AITrafficTuningMode = 1;"),
    M("g-slow-car", "float   AISlowCarSpeed = 20.0f;",
      "float   AISlowCarSpeed = 21.0f;"),
    M("g-slow-traffic", "float   AISlowTrafficSpeed = 10.0f;",
      "float   AISlowTrafficSpeed = 11.0f;"),
    M("oob-right", "        return l - p->RightWidth;",
      "        return l - p->LeftWidth;"),
    M("oob-left", "    return -(l + p->LeftWidth);",
      "    return -(l + p->RightWidth);"),
    # -- the closest point ahead ---------------------------------------
    M("se-start", "    int32_t i = start < 0 ? 0 : start;",
      "    int32_t i = start < 0 ? 1 : start;"),
    M("se-best", "    int32_t best = -1;\n    float bestDist",
      "    int32_t best = 0;\n    float bestDist"),
    M("se-dy", "        float dy = p->Position.y - pos->y;",
      "        float dy = p->Position.y - pos->x;"),
    M("se-ahead-sign", "        float ahead = -((pos->x - p->Position.x)",
      "        float ahead = ((pos->x - p->Position.x)"),
    M("se-ahead-dir", "                        + (pos->y - p->Position.y) * p->Direction.y);",
      "                        + (pos->y - p->Position.y) * p->Direction.x);"),
    M("se-ahead-strict", "        if (0.0f < ahead && d < bestDist) {",
      "        if (0.0f <= ahead && d < bestDist) {"),
    M("se-ahead-off", "        if (0.0f < ahead && d < bestDist) {",
      "        if (d < bestDist) {"),
    M("se-tie", "        if (0.0f < ahead && d < bestDist) {",
      "        if (0.0f < ahead && d <= bestDist) {"),
    M("se-skip-two", "        skip = ee_trunc_w(d * DC_SEARCH_STEP) - 2;",
      "        skip = ee_trunc_w(d * DC_SEARCH_STEP) - 1;"),
    M("se-skip-off", "        skip = ee_trunc_w(d * DC_SEARCH_STEP) - 2;",
      "        skip = 0;"),
    M("se-skip-floor", "(uint32_t)(0 < skip ? skip : 0) + 1u);",
      "(uint32_t)(0 < skip ? skip : 1) + 1u);"),
    # -- the smooth way out --------------------------------------------
    M("sm-last", "    int32_t last = index - 2, i;",
      "    int32_t last = index - 1, i;"),
    M("sm-guard", "    if (last + 1 < 2)\n        return;",
      "    if (last + 1 < 3)\n        return;"),
    M("sm-a-line", "                                                          l->Points[0].nLine));",
      "                                                          0));"),
    M("sm-b-point", "    pe = fp_point(&l->Points[last]);",
      "    pe = fp_point(&l->Points[last - 1]);"),
    M("sm-slope", "    slope = ee_div(toL - fromL,", "    slope = ee_div(fromL - toL,"),
    M("sm-ieee-div", "    slope = ee_div(toL - fromL,\n                   sqrtf(",
      "    slope = (toL - fromL) / (\n                   sqrtf("),
    M("sm-full", "    if (!(t->NumPoints < DRIVETARGET_MAX_POINTS))\n        return;\n\n    i = 0;",
      "    i = 0;"),
    M("sm-from", "        cur = fromL + sqrtf((a.x - c.x) * (a.x - c.x)",
      "        cur = sqrtf((a.x - c.x) * (a.x - c.x)"),
    M("sm-cap-up", "            if (toL < cur)\n                cur = toL;",
      "            if (0)\n                cur = toL;"),
    M("sm-cap-down", "            if (cur < toL)\n                cur = toL;",
      "            if (0)\n                cur = toL;"),
    M("sm-line-off", "        cur = (cur + trpoint_get_driving_line_offset(p, fp->nLine))",
      "        cur = (cur)"),
    M("sm-offset", "              + fp->fOffset;\n        if (inside) {",
      "              - fp->fOffset;\n        if (inside) {"),
    M("sm-inside", "        if (inside) {", "        if (!inside) {"),
    M("sm-inside-lo", "            lo = (DC_EDGE - p->LeftWidth) + list->MyHalfSizeL;",
      "            lo = (DC_EDGE - p->LeftWidth);"),
    M("sm-inside-hi", "            hi = (p->RightWidth - DC_EDGE) - list->MyHalfSizeL;",
      "            hi = p->RightWidth - list->MyHalfSizeL;"),
    M("sm-outside-lo",
      "            lo = -p->LeftWidth;\n            hi = p->RightWidth;\n        }\n        // STACK-W, as",
      "            lo = -p->RightWidth;\n            hi = p->RightWidth;\n        }\n        // STACK-W, as"),
    M("sm-outside-hi",
      "            lo = -p->LeftWidth;\n            hi = p->RightWidth;\n        }\n        // STACK-W, as",
      "            lo = -p->LeftWidth;\n            hi = p->LeftWidth;\n        }\n        // STACK-W, as"),
    M("sm-clamp", "min_s(hi, max_s(cur, lo))", "cur"),
    M("sm-rn", "drivetarget_add_point3(t, &pos, (int8_t)fp->nRouteNumber,",
      "drivetarget_add_point3(t, &pos, (int8_t)(fp->nRouteNumber + 1),"),
    M("sm-pn", "(int16_t)fp->nPointNumber, (int8_t)fp->nLine,",
      "(int16_t)(fp->nPointNumber + 1), (int8_t)fp->nLine,"),
    M("sm-dl", "(int16_t)fp->nPointNumber, (int8_t)fp->nLine,",
      "(int16_t)fp->nPointNumber, (int8_t)(fp->nLine + 1),"),
    M("sm-check", "                               1, NULL);\n        i++;",
      "                               0, NULL);\n        i++;"),
    M("sm-end", "    } while (!(last < i) && t->NumPoints",
      "    } while (!(last <= i) && t->NumPoints"),
    # -- the clearance -------------------------------------------------
    M("cl-null", "    if (nc == NULL)\n        return 0.0f;",
      "    if (nc == NULL)\n        return 1.0f;"),
    M("cl-search", "        if (index == -1)\n            index = futurepointlist",
      "        if (index == -2)\n            index = futurepointlist"),
    M("cl-search-car", "                l, (const bVector2 *)&other->State.Position, 0);",
      "                l, (const bVector2 *)&me->State.Position, 0);"),
    M("cl-mine-line", "                    - trpoint_get_driving_line_offset(p0, f0->nLine))",
      "                    + trpoint_get_driving_line_offset(p0, f0->nLine))"),
    M("cl-mine-off", "                   + f0->fOffset;", "                   - f0->fOffset;"),
    M("cl-its-line", "                   - trpoint_get_driving_line_offset(pi, fi->nLine))",
      "                   - trpoint_get_driving_line_offset(pi, f0->nLine))"),
    M("cl-its-off", "                  + fi->fOffset;", "                  - fi->fOffset;"),
    M("cl-abs", "            gap = (fabsf(mine - its) - list->MyHalfSizeL)",
      "            gap = ((mine - its) - list->MyHalfSizeL)"),
    M("cl-my-half", "            gap = (fabsf(mine - its) - list->MyHalfSizeL)",
      "            gap = (fabsf(mine - its))"),
    M("cl-its-half", "                  - nc->ApparentHalfSizeL;\n        }",
      "                  - nc->ApparentHalfSizeD;\n        }"),
    M("cl-v-abs", "    v = fabsf(other->State.VelocityMagnitude);",
      "    v = other->State.VelocityMagnitude;"),
    M("cl-v-mine", "    v = fabsf(other->State.VelocityMagnitude);",
      "    v = fabsf(me->State.VelocityMagnitude);"),
    M("cl-me-traffic", "    if (me->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR)\n        least = DC_GAP;",
      "    if (0)\n        least = DC_GAP;"),
    M("cl-other-traffic", "    else if (other->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR",
      "    else if (other->MyDriver->TheDriverType != DRIVER_TYPE_TRAFFIC_CAR"),
    M("cl-le-traffic", "? v <= AISlowTrafficSpeed : v <= AISlowCarSpeed)",
      "? v < AISlowTrafficSpeed : v <= AISlowCarSpeed)"),
    M("cl-le-car", "? v <= AISlowTrafficSpeed : v <= AISlowCarSpeed)",
      "? v <= AISlowTrafficSpeed : v < AISlowCarSpeed)"),
    M("cl-player", "        least = other->pPlayer != NULL ? DC_GAP_PLAYER : DC_GAP;",
      "        least = DC_GAP;"),
    M("cl-max-gap", "    return max_s(gap, least);", "    return gap;"),
    M("cl-max-least", "    return max_s(gap, least);", "    return least;"),
    # -- alongside another car's target --------------------------------
    M("mp-other-speed", "    if (!(DC_PARALLEL_SPEED < other->State.VelocityMagnitude))",
      "    if (!(DC_PARALLEL_SPEED <= other->State.VelocityMagnitude))"),
    M("mp-other-speed-off", "    if (!(DC_PARALLEL_SPEED < other->State.VelocityMagnitude))\n        return;",
      "    if (0)\n        return;"),
    M("mp-me-speed", "    if (!(DC_PARALLEL_SPEED < me->State.VelocityMagnitude))",
      "    if (!(DC_PARALLEL_SPEED <= me->State.VelocityMagnitude))"),
    M("mp-me-speed-off", "    if (!(DC_PARALLEL_SPEED < me->State.VelocityMagnitude))\n        return;",
      "    if (0)\n        return;"),
    M("mp-wheels", "    if (other->State.nWheelsTouchingGround < DC_PARALLEL_WHEELS)",
      "    if (other->State.nWheelsTouchingGround <= DC_PARALLEL_WHEELS)"),
    M("mp-heading", "    if (!(DC_SAME_HEADING < mine.x * theirs.x + mine.y * theirs.y))",
      "    if (!(0.0f < mine.x * theirs.x + mine.y * theirs.y))"),
    M("mp-heading-y", "    if (!(DC_SAME_HEADING < mine.x * theirs.x + mine.y * theirs.y))",
      "    if (!(DC_SAME_HEADING < mine.x * theirs.x + mine.x * theirs.y))"),
    M("mp-theirs", "    bNormalize2(&theirs, (const bVector2 *)&other->State.Velocity);",
      "    bNormalize2(&theirs, (const bVector2 *)&other->State.BodyMatrix.v0);"),
    M("mp-first", "    j = drivetarget_get_first_point(its, &other->State);",
      "    j = 0;"),
    M("mp-first-mine", "    j = drivetarget_get_first_point(its, &other->State);",
      "    j = drivetarget_get_first_point(its, &me->State);"),
    M("mp-want-side", "        float want = lateral(p, q->x, q->y) + side;",
      "        float want = lateral(p, q->x, q->y) - side;"),
    M("mp-want-q", "        float want = lateral(p, q->x, q->y) + side;",
      "        float want = side;"),
    M("mp-type", "        if (r->Type != TRACK_ROUTE_TRAFFIC) {",
      "        if (r->Type == TRACK_ROUTE_TRAFFIC) {"),
    M("mp-racing-lo",
      "            lo = -p->LeftWidth;\n            hi = p->RightWidth;\n        } else {",
      "            lo = -p->RightWidth;\n            hi = p->RightWidth;\n        } else {"),
    M("mp-racing-hi",
      "            lo = -p->LeftWidth;\n            hi = p->RightWidth;\n        } else {",
      "            lo = -p->LeftWidth;\n            hi = p->LeftWidth;\n        } else {"),
    M("mp-from", "                l, (const bVector2 *)&p->Position, from);",
      "                l, (const bVector2 *)&p->Position, 0);"),
    M("mp-from-none", "            if (from != -1) {", "            if (0) {"),
    M("mp-edge-l", "trpoint_get_position2(e, &le, 0.0f, -e->LeftWidth);",
      "trpoint_get_position2(e, &le, 0.0f, e->LeftWidth);"),
    M("mp-edge-r", "trpoint_get_position2(e, &re, 0.0f, e->RightWidth);",
      "trpoint_get_position2(e, &re, 0.0f, -e->RightWidth);"),
    M("mp-order", "                if (ll < rl) {", "                if (rl < ll) {"),
    M("mp-margin", "        m = list->MyHalfSizeL + DC_EDGE;", "        m = DC_EDGE;"),
    M("mp-lo", "        lo = lo + m;", "        lo = lo - m;"),
    M("mp-hi", "        hi = hi - m;", "        hi = hi + m;"),
    M("mp-clamp", "min_s(hi, max_s(want, lo))", "want"),
    M("mp-rn", "        drivetarget_add_point3(t, &pos, its->Route[j],",
      "        drivetarget_add_point3(t, &pos, its->Route[0],"),
    M("mp-pn", "                               its->RoutePointNumber[j], its->DrivingLine[j],",
      "                               its->RoutePointNumber[0], its->DrivingLine[j],"),
    M("mp-dl", "                               its->RoutePointNumber[j], its->DrivingLine[j],",
      "                               its->RoutePointNumber[j], its->DrivingLine[0],"),
    M("mp-car", "                               1, me);", "                               1, NULL);"),
    M("mp-check", "                               1, me);", "                               0, me);"),
    # -- round a car ---------------------------------------------------
    M("ar-search-car", "                &fl, (const bVector2 *)&nc->TheCar->State.Position, 0))",
      "                &fl, (const bVector2 *)&list->MyCar->State.Position, 0))"),
    M("ar-extra", "        if (d->UseExtraLateralDistance)", "        if (!d->UseExtraLateralDistance)"),
    M("ar-oob", "        if (amount_out_of_bounds(p, lat) < DC_FAR_OFF_ROAD) {",
      "        if (amount_out_of_bounds(p, lat) < 1000.0f) {"),
    M("ar-lat", "        lat = lateral(p, other->State.Position.x, other->State.Position.y);",
      "        lat = lateral(p, other->State.Position.y, other->State.Position.x);"),
    M("ar-side", "            side = d->Type == CHOICE_LEFT_SIDE_OF_CAR ? -1.0f : 1.0f;",
      "            side = d->Type == CHOICE_LEFT_SIDE_OF_CAR ? 1.0f : -1.0f;"),
    M("ar-traffic-me", "            if (list->MyCar->MyDriver->TheDriverType\n                    == DRIVER_TYPE_TRAFFIC_CAR\n                && AITrafficTuningMode != 0)",
      "            if (AITrafficTuningMode != 0)"),
    M("ar-traffic-mode", "            if (list->MyCar->MyDriver->TheDriverType\n                    == DRIVER_TYPE_TRAFFIC_CAR\n                && AITrafficTuningMode != 0)",
      "            if (list->MyCar->MyDriver->TheDriverType\n                    == DRIVER_TYPE_TRAFFIC_CAR)"),
    M("ar-room-half", "            room = side * ((list->MyHalfSizeL + nc->ApparentHalfSizeL)",
      "            room = side * ((list->MyHalfSizeL)"),
    M("ar-room-clear", "                           + clearance);", "                           );"),
    M("ar-along", "            along = (other->State.Position.x - p->Position.x)",
      "            along = (list->MyCar->State.Position.x - p->Position.x)"),
    M("ar-pass-hi", "            passL = min_s((p->RightWidth - DC_EDGE) - list->MyHalfSizeL,",
      "            passL = min_s(p->RightWidth,"),
    M("ar-pass-lo", "                                list->MyHalfSizeL\n                                    - (p->LeftWidth - DC_EDGE)));",
      "                                -p->LeftWidth));"),
    M("ar-pass-offset", "                          max_s((lat + room) + fp->fOffset,",
      "                          max_s((lat + room),"),
    M("ar-pass-room", "                          max_s((lat + room) + fp->fOffset,",
      "                          max_s((lat - room) + fp->fOffset,"),
    M("ar-pos-along", "            trpoint_get_position3(p, &pos, along, passL);",
      "            trpoint_get_position3(p, &pos, 0.0f, passL);"),
    M("ar-from", "                &fl, t, list, idx, currentL,",
      "                &fl, t, list, idx, 0.0f,"),
    M("ar-to", "                passL - trpoint_get_driving_line_offset(p, line), 1);",
      "                passL, 1);"),
    M("ar-inside", "                passL - trpoint_get_driving_line_offset(p, line), 1);",
      "                passL - trpoint_get_driving_line_offset(p, line), 0);"),
    M("ar-no-smooth", "            drivingchoice_do_smooth_offset_change(\n"
      "                &fl, t, list, idx, currentL,\n"
      "                passL - trpoint_get_driving_line_offset(p, line), 1);\n", ""),
    M("ar-add-rn", "            drivetarget_add_point3(t, &pos, (int8_t)r->RouteNumber,",
      "            drivetarget_add_point3(t, &pos, (int8_t)(r->RouteNumber + 1),"),
    M("ar-add-pn", "                                   (int16_t)troute_get_point_number(r, p),",
      "                                   (int16_t)(troute_get_point_number(r, p) + 1),"),
    M("ar-add-line", "                                   (int8_t)line, 1, NULL);",
      "                                   (int8_t)(line + 1), 1, NULL);"),
    M("ar-add-check", "                                   (int8_t)line, 1, NULL);",
      "                                   (int8_t)line, 0, NULL);"),
    M("ar-last", "            t->LastPointToScore = (int8_t)(t->NumPoints - 1);",
      "            t->LastPointToScore = (int8_t)t->NumPoints;"),
    M("ar-player", "            if (it->pPlayer != NULL", "            if (it->pPlayer == NULL"),
    M("ar-cop", "                    ? its != DRIVER_TYPE_COP", "                    ? 1"),
    M("ar-its-traffic", "                    : its == DRIVER_TYPE_TRAFFIC_CAR\n                          && list",
      "                    : 1\n                          && list"),
    M("ar-me-traffic", "                          && list->MyCar->MyDriver->TheDriverType\n                                 != DRIVER_TYPE_TRAFFIC_CAR)",
      "                          && 1)"),
    M("ar-parallel-room", "                                                                &fl, room);",
      "                                                                &fl, -room);"),
    M("ar-fill-m", "                                               MOVEMENT_PARALLEL_TO_LINE, 1);\n            done = 1;",
      "                                               MOVEMENT_TOWARDS_LINE, 1);\n            done = 1;"),
    M("ar-fill-inside", "                                               MOVEMENT_PARALLEL_TO_LINE, 1);\n            done = 1;",
      "                                               MOVEMENT_PARALLEL_TO_LINE, 0);\n            done = 1;"),
    M("ar-done", "            done = 1;", "            done = 0;"),
    M("ar-fail-m", "    if (!done)\n        drivingchoice_fill_up_drive_target(t, loc, list,\n"
      "                                           MOVEMENT_PARALLEL_TO_LINE, 1);",
      "    if (!done)\n        drivingchoice_fill_up_drive_target(t, loc, list,\n"
      "                                           MOVEMENT_TOWARDS_LINE, 1);"),
    M("ar-fail-inside", "    if (!done)\n        drivingchoice_fill_up_drive_target(t, loc, list,\n"
      "                                           MOVEMENT_PARALLEL_TO_LINE, 1);",
      "    if (!done)\n        drivingchoice_fill_up_drive_target(t, loc, list,\n"
      "                                           MOVEMENT_PARALLEL_TO_LINE, 0);"),
    # -- BuildDriveTarget ----------------------------------------------
    M("bd-assign", "    drivetarget_assign(t, &list->MyCar->pCarDriver->MyDriveTarget);\n", ""),
    M("bd-clear", "    drivetarget_clear(t, list->MyCar, 0.0f);\n", ""),
    M("bd-valid", "    if (!drivingchoice_is_valid(d, loc, list)) {", "    if (0) {"),
    M("bd-invalid-m", "        drivingchoice_fill_up_drive_target(t, loc, list, m, 1);",
      "        drivingchoice_fill_up_drive_target(t, loc, list,\n"
      "                                           MOVEMENT_PARALLEL_TO_LINE, 1);"),
    M("bd-invalid-inside", "        drivingchoice_fill_up_drive_target(t, loc, list, m, 1);",
      "        drivingchoice_fill_up_drive_target(t, loc, list, m, 0);"),
    M("bd-line-loc", "        drivingchoice_fill_up_drive_target(t, &onLine, list, m, 1);",
      "        drivingchoice_fill_up_drive_target(t, loc, list, m, 1);"),
    M("bd-line-inside", "        drivingchoice_fill_up_drive_target(t, &onLine, list, m, 1);",
      "        drivingchoice_fill_up_drive_target(t, &onLine, list, m, 0);"),
    M("bd-line-which", "            &onLine, drivingchoice_get_driving_line(d->Type, list->MyCar), 0);",
      "            &onLine, loc->DrivingLine, 0);"),
    M("bd-line-built", "        built = 1;\n    } else {", "        built = 0;\n    } else {"),
    M("bd-around-built", "        built = drivingchoice_build_drive_target_around_car(d, t, list, 0.0f,",
      "        drivingchoice_build_drive_target_around_car(d, t, list, 0.0f,"),
    M("bd-fixup", "    drivingchoice_fixup_car_to_exclude_from_collision_prediction(\n"
      "        d, list->MyCar, 0, list);\n    return built;", "    return built;"),
    M("bd-fixup-check", "        d, list->MyCar, 0, list);\n    return built;",
      "        d, list->MyCar, 1, list);\n    return built;"),
    # -- CarCollisionPredict (11b-4a): the constants -------------------
    M("ck-no-hit", "#define CCP_NO_HIT          99999.0f",
      "#define CCP_NO_HIT          9999.0f", rel=CCP),
    M("ck-still", "#define CCP_STILL           0.00100000005f",
      "#define CCP_STILL           0.5f", rel=CCP),
    M("ck-traffic-scale", "#define CCP_TRAFFIC_SCALE   1.29999995f",
      "#define CCP_TRAFFIC_SCALE   1.5f", rel=CCP),
    M("ck-backing-scale", "#define CCP_BACKING_SCALE   1.29999995f",
      "#define CCP_BACKING_SCALE   1.5f", rel=CCP),
    M("ck-leg-done", "#define CCP_LEG_DONE        0.00100000005f",
      "#define CCP_LEG_DONE        0.100000001f", rel=CCP),
    M("ck-same", "#define CCP_SAME            0.00100000005f",
      "#define CCP_SAME            99990.0f", rel=CCP),
    M("ck-axis-still", "#define CCP_AXIS_STILL      9.99999975e-05f",
      "#define CCP_AXIS_STILL      0.100000001f", rel=CCP),
    M("ck-never", "#define CCP_NEVER           9999.0f",
      "#define CCP_NEVER           999.0f", rel=CCP),
    M("ck-always", "#define CCP_ALWAYS         -9999.0f",
      "#define CCP_ALWAYS         -999.0f", rel=CCP),
    M("ck-no-overlap", "#define CCP_NO_OVERLAP      99999.0f",
      "#define CCP_NO_OVERLAP      9999.0f", rel=CCP),
    M("ck-stopped-speed", "#define CCP_STOPPED_SPEED   5.0f",
      "#define CCP_STOPPED_SPEED   4.0f", rel=CCP),
    M("ck-stopped-ahead", "#define CCP_STOPPED_AHEAD   23.0f",
      "#define CCP_STOPPED_AHEAD   20.0f", rel=CCP),
    M("ck-on-road", "#define CCP_ON_ROAD        -0.25f",
      "#define CCP_ON_ROAD        0.0f", rel=CCP),
    M("ck-slow", "#define CCP_SLOW            2.0f",
      "#define CCP_SLOW            3.0f", rel=CCP),
    M("ck-tuning", "#define CCP_TUNING_SCALE    1000.0f",
      "#define CCP_TUNING_SCALE    100.0f", rel=CCP),
    M("ck-max-s", "return fs < ft ? ft : fs;", "return fs < ft ? fs : ft;",
      rel=CCP),
    M("ck-no-action", "return a == NULL ? AIACTION_NONE : a->Type;",
      "return a == NULL ? AIACTION_JUST_DRIVE : a->Type;", rel=CCP),
    M("ck-blind-unstuck",
      "return type == AIACTION_GET_UNSTUCK || type == AIACTION_NONE",
      "return type == AIACTION_NONE", rel=CCP),
    M("ck-blind-none",
      "return type == AIACTION_GET_UNSTUCK || type == AIACTION_NONE",
      "return type == AIACTION_GET_UNSTUCK", rel=CCP),
    M("ck-blind-accident",
      "|| type == AIACTION_ACCIDENT_RECOVERY || t->NumPoints == 0;",
      "|| t->NumPoints == 0;", rel=CCP),
    M("ck-blind-empty",
      "|| type == AIACTION_ACCIDENT_RECOVERY || t->NumPoints == 0;",
      "|| type == AIACTION_ACCIDENT_RECOVERY;", rel=CCP),
    # -- WhoWillThisDriveTargetHit ---------------------------------------
    M("cw-clear", "if (loc == NULL || drivinglocation_is_clear(loc))",
      "if (loc == NULL)", rel=CCP),
    M("cw-np-lo", "if (t->NumPoints <= 0 ||", "if (t->NumPoints < 0 ||",
      rel=CCP),
    M("cw-np-hi", "!(t->NumPoints < CCP_MAX_POINTS + 1))",
      "!(t->NumPoints < CCP_MAX_POINTS))", rel=CCP),
    M("cw-care", "if (!ai_do_we_care_about_this_car(nc, list))\n"
      "            continue;", "", rel=CCP),
    M("cw-stopped-its", "its = 0.0f;\n            r = 1;",
      "its = 1.0f;\n            r = 1;", rel=CCP),
    M("cw-stopped-r", "its = 0.0f;\n            r = 1;",
      "its = 0.0f;\n            r = 0;", rel=CCP),
    M("cw-still-fabs",
      "fabsf(list->MyCar->State.VelocityMagnitude) <= CCP_STILL",
      "list->MyCar->State.VelocityMagnitude <= CCP_STILL", rel=CCP),
    M("cw-still", "fabsf(list->MyCar->State.VelocityMagnitude) <= CCP_STILL",
      "fabsf(list->MyCar->State.VelocityMagnitude) <= CCP_SLOW", rel=CCP),
    M("cw-exclude", "                   || nc->TheCar == exclude) {",
      "                   ) {", rel=CCP),
    M("cw-cars", "r = ccp_will_i_hit_this_car(t, loc, list->MyCar, nc->TheCar,",
      "r = ccp_will_i_hit_this_car(t, loc, nc->TheCar, list->MyCar,",
      rel=CCP),
    M("cw-max-time", "maxTime, &its);", "maxTime + 1.0f, &its);", rel=CCP),
    M("cw-best", "if (r && its < best) {", "if (r && its <= best) {", rel=CCP),
    M("cw-r", "if (r && its < best) {", "if (its < best) {", rel=CCP),
    M("cw-best-init", "float best = CCP_NO_HIT;", "float best = 50.0f;",
      rel=CCP),
    M("cw-keep", "            best = its;\n", "", rel=CCP),
    M("cw-id", "        pCurrentWorld->CollisionPredictionID++;\n", "",
      rel=CCP),
    M("cw-when", "    *when = best;\n    return hit;", "    return hit;",
      rel=CCP),
    # -- IsThisCarStoppedDirectlyInFrontOfMe -----------------------------
    M("cs-fabs",
      "if (!(fabsf(nc->TheCar->State.VelocityMagnitude) <= CCP_STOPPED_SPEED))",
      "if (!(nc->TheCar->State.VelocityMagnitude <= CCP_STOPPED_SPEED))",
      rel=CCP),
    M("cs-speed", "<= CCP_STOPPED_SPEED))", "< CCP_STOPPED_SPEED))", rel=CCP),
    M("cs-x-fabs", "return fabsf(nc->Position.x) <", "return nc->Position.x <",
      rel=CCP),
    M("cs-x-its", "< list->MyHalfSizeL + nc->ApparentHalfSizeL",
      "< list->MyHalfSizeL", rel=CCP),
    M("cs-x-mine", "< list->MyHalfSizeL + nc->ApparentHalfSizeL",
      "< nc->ApparentHalfSizeL", rel=CCP),
    M("cs-y-its", "(list->MyHalfSizeD + nc->ApparentHalfSizeD)",
      "(list->MyHalfSizeD)", rel=CCP),
    M("cs-y-mine", "(list->MyHalfSizeD + nc->ApparentHalfSizeD)",
      "(nc->ApparentHalfSizeD)", rel=CCP),
    M("cs-y-abs", "&& nc->Position.y <", "&& fabsf(nc->Position.y) <",
      rel=CCP),
    # -- WillIHitThisCar -------------------------------------------------
    M("cl-its-target",
      "drivetarget_copy(&s_its, &other->pCarDriver->MyDriveTarget);",
      "drivetarget_copy(&s_its, t);", rel=CCP),
    M("cl-my-traffic",
      "if (me->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR\n"
      "        && CCP_ON_ROAD < car_get_amount_out_of_bounds(me))",
      "if (CCP_ON_ROAD < car_get_amount_out_of_bounds(me))", rel=CCP),
    M("cl-my-oob", "&& CCP_ON_ROAD < car_get_amount_out_of_bounds(me))",
      "&& CCP_ON_ROAD <= car_get_amount_out_of_bounds(me))", rel=CCP),
    M("cl-my-fill", "drivetarget_fill_with_current_acceleration(&s_mine, me);",
      "drivetarget_blend_with_current_acceleration(&s_mine, me);", rel=CCP),
    M("cl-my-blend",
      "    else\n        drivetarget_blend_with_current_acceleration(&s_mine, me);",
      "    else\n        ;", rel=CCP),
    M("cl-its-traffic",
      "if (other->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR) {",
      "if (other->MyDriver->TheDriverType != DRIVER_TYPE_TRAFFIC_CAR) {",
      rel=CCP),
    M("cl-its-oob", "if (CCP_ON_ROAD < car_get_amount_out_of_bounds(other))",
      "if (CCP_ON_ROAD <= car_get_amount_out_of_bounds(other))", rel=CCP),
    M("cl-its-fill",
      "drivetarget_fill_with_current_acceleration(&s_its, other);",
      "drivetarget_blend_with_current_acceleration(&s_its, other);",
      rel=CCP),
    M("cl-its-just", "else if (action_type(other) != AIACTION_JUST_DRIVE)",
      "else", rel=CCP),
    M("cl-its-blend",
      "            drivetarget_blend_with_current_acceleration(&s_its, other);",
      "            ;", rel=CCP),
    M("cl-my-scale", "if (me->TheControlMode == TRAFFIC_CONTROL)",
      "if (me->TheControlMode == AI_CONTROL)", rel=CCP),
    M("cl-its-scale", "if (other->TheControlMode == TRAFFIC_CONTROL)\n",
      "if (other->TheControlMode == AI_CONTROL)\n", rel=CCP),
    M("cl-my-speed", "myV0 = mySpeed = me->State.VelocityMagnitude;",
      "myV0 = mySpeed = me->State.ForwardSpeed;", rel=CCP),
    M("cl-its-speed", "itsV0 = itsSpeed = other->State.VelocityMagnitude;",
      "itsV0 = itsSpeed = other->State.ForwardSpeed;", rel=CCP),
    M("cl-my-back",
      "if (me->State.ForwardSpeed < 0.0f && backing_blind(me, &s_mine)) {",
      "if (backing_blind(me, &s_mine)) {", rel=CCP),
    M("cl-my-blind",
      "if (me->State.ForwardSpeed < 0.0f && backing_blind(me, &s_mine)) {",
      "if (me->State.ForwardSpeed < 0.0f) {", rel=CCP),
    M("cl-my-predict", "        ai_straight_line_predict(me, &s_mine);\n", "",
      rel=CCP),
    M("cl-my-fabs", "mySpeed = fabsf(myV0);", "mySpeed = myV0;", rel=CCP),
    M("cl-my-bscale", "myScale = CCP_BACKING_SCALE;", "myScale = 1.0f;",
      rel=CCP),
    M("cl-its-back", "if (other->State.ForwardSpeed < 0.0f\n",
      "if (other->State.ForwardSpeed <= 0.0f\n", rel=CCP),
    M("cl-its-ai", "&& (other->TheControlMode == AI_CONTROL\n",
      "&& (other->TheControlMode == COP_CONTROL\n", rel=CCP),
    M("cl-its-mode",
      "            || other->TheControlMode == TRAFFIC_CONTROL)\n",
      "            || other->TheControlMode == REAL_CONTROL)\n", rel=CCP),
    M("cl-its-blind", "\n        && backing_blind(other, &s_its)) {", ") {",
      rel=CCP),
    M("cl-its-predict", "        ai_straight_line_predict(other, &s_its);\n",
      "", rel=CCP),
    M("cl-its-fabs", "itsSpeed = fabsf(itsV0);", "itsSpeed = itsV0;",
      rel=CCP),
    M("cl-its-bscale", "itsScale = CCP_BACKING_SCALE;", "itsScale = 1.0f;",
      rel=CCP),
    M("cl-my-floor", "    mySpeed = max_s(mySpeed, CCP_STILL);\n", "",
      rel=CCP),
    M("cl-its-floor", "    itsSpeed = max_s(itsSpeed, CCP_STILL);\n", "",
      rel=CCP),
    M("cl-my-slow", "if (mySpeed < CCP_SLOW)\n        myScale = 1.0f;", "",
      rel=CCP),
    M("cl-its-slow", "if (itsSpeed < CCP_SLOW)\n        itsScale = 1.0f;", "",
      rel=CCP),
    M("cl-tuning-type",
      "if (me->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR\n"
      "        && AITrafficTuningMode != 0)",
      "if (AITrafficTuningMode != 0)", rel=CCP),
    M("cl-tuning-on", "&& AITrafficTuningMode != 0)",
      "&& AITrafficTuningMode == 0)", rel=CCP),
    M("cl-my-first", "i = drivetarget_get_first_point(&s_mine, &me->State);",
      "i = 0;", rel=CCP),
    M("cl-its-first",
      "j = drivetarget_get_first_point(&s_its, &other->State);", "j = 0;",
      rel=CCP),
    M("cl-my-start", "myPos.y = me->State.Position.y;",
      "myPos.y = me->State.Position.x;", rel=CCP),
    M("cl-its-start", "itsPos.x = other->State.Position.x;",
      "itsPos.x = me->State.Position.x;", rel=CCP),
    M("cl-loop-i", "while (i < s_mine.NumPoints && j < s_its.NumPoints",
      "while (i < s_mine.NumPoints - 1 && j < s_its.NumPoints", rel=CCP),
    M("cl-loop-j", "&& j < s_its.NumPoints\n",
      "&& j < s_its.NumPoints - 1\n", rel=CCP),
    M("cl-loop-time", "&& elapsed <= maxTime) {", "&& elapsed < maxTime) {",
      rel=CCP),
    M("cl-loop-no-time", "\n           && elapsed <= maxTime) {", ") {",
      rel=CCP),
    M("cl-my-leg", "myLeg.y = myTo->y - myPos.y;",
      "myLeg.y = myTo->y - itsPos.y;", rel=CCP),
    M("cl-its-leg", "itsLeg.x = itsTo->x - itsPos.x;",
      "itsLeg.x = itsTo->x - myPos.x;", rel=CCP),
    M("cl-its-len", "itsLen = sqrtf(itsLeg.x * itsLeg.x + itsLeg.y * itsLeg.y);",
      "itsLen = sqrtf(itsLeg.x * itsLeg.x + itsLeg.x * itsLeg.y);", rel=CCP),
    M("cl-its-time", "itsTime = itsLen / itsSpeed;",
      "itsTime = itsLen / mySpeed;", rel=CCP),
    M("cl-my-time", "myTime = myLen / mySpeed;", "myTime = myLen / itsSpeed;",
      rel=CCP),
    M("cl-step", "step = myTime < itsTime ? myTime : itsTime;",
      "step = myTime < itsTime ? itsTime : myTime;", rel=CCP),
    M("cl-dx", "d.x = itsPos.x - myPos.x;", "d.x = myPos.x - itsPos.x;",
      rel=CCP),
    M("cl-dy", "d.y = itsPos.y - myPos.y;", "d.y = itsPos.y + myPos.y;",
      rel=CCP),
    M("cl-vx", "v.x = itsVel.x - myVel.x;", "v.x = myVel.x - itsVel.x;",
      rel=CCP),
    M("cl-vy", "v.y = itsVel.y - myVel.y;", "v.y = itsVel.y + myVel.y;",
      rel=CCP),
    M("cl-my-vel", "bNormalize2To(&myVel, &myVel, mySpeed);",
      "bNormalize2To(&myVel, &myVel, itsSpeed);", rel=CCP),
    M("cl-its-vel", "bNormalize2To(&itsVel, &itsVel, itsSpeed);",
      "bNormalize2(&itsVel, &itsVel);", rel=CCP),
    M("cl-boxes",
      "at = ccp_when_will_overlap_occur_2d(&s_my_obbs[i], &s_its_obbs[j],",
      "at = ccp_when_will_overlap_occur_2d(&s_my_obbs[i], &s_its_obbs[i],",
      rel=CCP),
    M("cl-at", "if (at <= step) {", "if (at < step) {", rel=CCP),
    M("cl-hit", "hit = elapsed + at;", "hit = at;", rel=CCP),
    M("cl-fm", "fm = ee_div(step * mySpeed, myLen);",
      "fm = ee_div(step * itsSpeed, myLen);", rel=CCP),
    M("cl-fi", "fi = ee_div(step * itsSpeed, itsLen);",
      "fi = ee_div(step * itsSpeed, myLen);", rel=CCP),
    M("cl-fm-ieee", "fm = ee_div(step * mySpeed, myLen);",
      "fm = step * mySpeed / myLen;", rel=CCP),
    M("cl-fi-ieee", "fi = ee_div(step * itsSpeed, itsLen);",
      "fi = step * itsSpeed / itsLen;", rel=CCP),
    M("cl-my-x", "myPos.x = myPos.x + (myTo->x - myPos.x) * fm;",
      "myPos.x = myTo->x;", rel=CCP),
    M("cl-its-y", "itsPos.y = itsPos.y + (itsTo->y - itsPos.y) * fi;",
      "itsPos.y = itsPos.y + (itsTo->y - itsPos.y) * fm;", rel=CCP),
    M("cl-its-x", "itsPos.x = itsPos.x + (itsTo->x - itsPos.x) * fi;",
      "itsPos.x = itsTo->x;", rel=CCP),
    M("cl-my-y", "myPos.y = myPos.y + (myTo->y - myPos.y) * fm;",
      "myPos.y = myPos.y + (myTo->y - myPos.y) * fi;", rel=CCP),
    M("cl-leg-done",
      "if (fabsf(myTime - step) <= CCP_LEG_DONE)\n            i++;\n"
      "        else\n            j++;",
      "if (fabsf(itsTime - step) <= CCP_LEG_DONE)\n            j++;\n"
      "        else\n            i++;", rel=CCP),
    M("cl-both", "            i++;\n        else\n            j++;",
      "            i++;\n        j++;", rel=CCP),
    M("cl-elapsed", "elapsed = elapsed + step;", "elapsed = step;", rel=CCP),
    M("cl-when", "    *when = hit;\n", "", rel=CCP),
    M("cl-r-lt", "r = hit < CCP_NO_HIT && !(", "r = !(", rel=CCP),
    # -- MakeOBBsForDriveTarget ------------------------------------------
    M("co-np", "if (t == NULL || t->NumPoints <= 0 ||",
      "if (t == NULL || t->NumPoints < 0 ||", rel=CCP),
    M("co-obbs", "|| obbs == NULL || car == NULL)", "|| car == NULL)",
      rel=CCP),
    M("co-car", "|| obbs == NULL || car == NULL)", "|| obbs == NULL)",
      rel=CCP),
    M("co-h0", "h0 = fabsf((hi.x - lo.x) * 0.5f) * scale;",
      "h0 = fabsf((hi.x - lo.x) * 0.5f);", rel=CCP),
    M("co-h0-fabs", "h0 = fabsf((hi.x - lo.x) * 0.5f) * scale;",
      "h0 = (hi.x - lo.x) * 0.5f * scale;", rel=CCP),
    M("co-h1", "h1 = fabsf((hi.y - lo.y) * 0.5f) * scale;",
      "h1 = fabsf((hi.x - lo.x) * 0.5f) * scale;", rel=CCP),
    M("co-h2", "h2 = fabsf((hi.z - lo.z) * 0.5f) * scale;",
      "h2 = fabsf((hi.z - lo.z) * 0.25f) * scale;", rel=CCP),
    M("co-sincos", "bSinCos(&s, &c, car->State.Angle);",
      "bSinCos(&c, &s, car->State.Angle);", rel=CCP),
    M("co-0-a0x", "obbs[0].A0.x = c;", "obbs[0].A0.x = s;", rel=CCP),
    M("co-0-a0y", "obbs[0].A0.y = s;", "obbs[0].A0.y = -s;", rel=CCP),
    M("co-0-a1x", "obbs[0].A1.x = -s;", "obbs[0].A1.x = s;", rel=CCP),
    M("co-0-a1y", "obbs[0].A1.y = c;", "obbs[0].A1.y = -c;", rel=CCP),
    M("co-0-a0pad", "    obbs[0].A0.pad = 0.0f;\n", "", rel=CCP),
    M("co-0-a2z", "obbs[0].A2.z = 1.0f;", "obbs[0].A2.z = 0.0f;", rel=CCP),
    M("co-0-a2y", "    obbs[0].A2.y = 0.0f;\n", "", rel=CCP),
    M("co-0-h0", "obbs[0].a0 = h0;", "obbs[0].a0 = h1;", rel=CCP),
    M("co-0-h1", "obbs[0].a1 = h1;", "obbs[0].a1 = h0;", rel=CCP),
    M("co-0-h2", "obbs[0].a2 = h2;", "obbs[0].a2 = h1;", rel=CCP),
    M("co-0-pos", "obbs[0].Position = t->Points[0];",
      "obbs[0].Position = t->Points[1];", rel=CCP),
    M("co-loop", "for (i = 1; i < t->NumPoints; i++) {",
      "for (i = 1; i < t->NumPoints - 1; i++) {", rel=CCP),
    M("co-dir-y", "dir.y = t->Points[i - 1].y - t->Points[i].y;",
      "dir.y = t->Points[i].y - t->Points[i - 1].y;", rel=CCP),
    M("co-dir-x", "dir.x = t->Points[i - 1].x - t->Points[i].x;",
      "dir.x = t->Points[i].x - t->Points[i - 1].x;", rel=CCP),
    M("co-norm", "        bNormalize2(&dir, &dir);\n", "", rel=CCP),
    M("co-a0y", "o->A0.y = dir.y;", "o->A0.y = dir.x;", rel=CCP),
    M("co-a0x", "o->A0.x = dir.x;", "o->A0.x = -dir.x;", rel=CCP),
    M("co-a1y", "o->A1.y = dir.x;", "o->A1.y = -dir.x;", rel=CCP),
    M("co-a1x", "o->A1.x = -dir.y;", "o->A1.x = dir.y;", rel=CCP),
    M("co-a1pad", "        o->A1.pad = 0.0f;\n", "", rel=CCP),
    M("co-a2z", "o->A2.z = 1.0f;", "o->A2.z = -1.0f;", rel=CCP),
    M("co-a2x", "        o->A2.x = 0.0f;\n", "", rel=CCP),
    M("co-h0s", "o->a0 = h0;", "o->a0 = h1;", rel=CCP),
    M("co-h1s", "o->a1 = h1;", "o->a1 = h2;", rel=CCP),
    M("co-h2s", "o->a2 = h2;", "o->a2 = h0;", rel=CCP),
    M("co-pos", "o->Position = t->Points[i];",
      "o->Position = t->Points[i - 1];", rel=CCP),
    # -- WhenWillOverlapOccur2D ------------------------------------------
    M("cv-c10", "float c10 = a->A1.x * b->A0.x + a->A1.y * b->A0.y;",
      "float c10 = a->A1.x * b->A0.x + a->A1.y * b->A1.y;", rel=CCP),
    M("cv-c00", "float c00 = a->A0.x * b->A0.x + a->A0.y * b->A0.y;",
      "float c00 = a->A0.x * b->A0.x - a->A0.y * b->A0.y;", rel=CCP),
    M("cv-c11", "float c11 = a->A1.x * b->A1.x + a->A1.y * b->A1.y;",
      "float c11 = a->A1.x * b->A1.x;", rel=CCP),
    M("cv-c01", "float c01 = a->A0.x * b->A1.x + a->A0.y * b->A1.y;",
      "float c01 = a->A0.x * b->A1.y + a->A0.y * b->A1.x;", rel=CCP),
    M("cv-ra1-own", "float rA1 = (fabsf(a->a1) +", "float rA1 = (fabsf(a->a0) +",
      rel=CCP),
    M("cv-ra1-c", "fabsf(b->a0 * c10)) + fabsf(b->a1 * c11);",
      "fabsf(b->a0 * c11)) + fabsf(b->a1 * c10);", rel=CCP),
    M("cv-ra0-c", "fabsf(b->a0 * c00)) + fabsf(b->a1 * c01);",
      "fabsf(b->a0 * c00));", rel=CCP),
    M("cv-ra0-fabs", "fabsf(b->a0 * c00)) + fabsf(b->a1 * c01);",
      "b->a0 * c00) + fabsf(b->a1 * c01);", rel=CCP),
    M("cv-ra0-own", "float rA0 = (fabsf(a->a0) +", "float rA0 = (a->a0 +",
      rel=CCP),
    M("cv-rb1-c", "fabsf(a->a0 * c01)) + fabsf(a->a1 * c11);",
      "fabsf(a->a0 * c10)) + fabsf(a->a1 * c11);", rel=CCP),
    M("cv-rb1-own", "float rB1 = (fabsf(b->a1) +", "float rB1 = (fabsf(b->a0) +",
      rel=CCP),
    M("cv-rb0-c", "fabsf(a->a0 * c00)) + fabsf(a->a1 * c10);",
      "fabsf(a->a0 * c00)) + fabsf(a->a1 * c01);", rel=CCP),
    M("cv-rb0-own", "float rB0 = (fabsf(b->a0) +", "float rB0 = (fabsf(b->a1) +",
      rel=CCP),
    M("cv-a1-d", "v->x * a->A1.x + v->y * a->A1.y, d->x * a->A1.x + d->y * a->A1.y,",
      "v->x * a->A1.x + v->y * a->A1.y, d->x * a->A1.x - d->y * a->A1.y,",
      rel=CCP),
    M("cv-a1-v", "v->x * a->A1.x + v->y * a->A1.y, d->x * a->A1.x + d->y * a->A1.y,",
      "v->x * a->A0.x + v->y * a->A0.y, d->x * a->A1.x + d->y * a->A1.y,",
      rel=CCP),
    M("cv-a0-v", "v->x * a->A0.x + v->y * a->A0.y, d->x * a->A0.x + d->y * a->A0.y,",
      "-(v->x * a->A0.x + v->y * a->A0.y), d->x * a->A0.x + d->y * a->A0.y,",
      rel=CCP),
    M("cv-a0-d", "v->x * a->A0.x + v->y * a->A0.y, d->x * a->A0.x + d->y * a->A0.y,",
      "v->x * a->A0.x + v->y * a->A0.y, d->y * a->A0.x + d->x * a->A0.y,",
      rel=CCP),
    M("cv-b1-d", "v->x * b->A1.x + v->y * b->A1.y, d->x * b->A1.x + d->y * b->A1.y,",
      "v->x * b->A1.x + v->y * b->A1.y, d->x * b->A1.x,", rel=CCP),
    M("cv-b1-v", "v->x * b->A1.x + v->y * b->A1.y, d->x * b->A1.x + d->y * b->A1.y,",
      "v->x * b->A1.x - v->y * b->A1.y, d->x * b->A1.x + d->y * b->A1.y,",
      rel=CCP),
    M("cv-b0-v", "v->x * b->A0.x + v->y * b->A0.y, d->x * b->A0.x + d->y * b->A0.y,",
      "v->y * b->A0.x + v->x * b->A0.y, d->x * b->A0.x + d->y * b->A0.y,",
      rel=CCP),
    M("cv-b0-d", "v->x * b->A0.x + v->y * b->A0.y, d->x * b->A0.x + d->y * b->A0.y,",
      "v->x * b->A0.x + v->y * b->A0.y, -(d->x * b->A0.x + d->y * b->A0.y),",
      rel=CCP),
    M("cv-r-a1", "rA1, &in[0], &in[1]);", "rA0, &in[0], &in[1]);", rel=CCP),
    M("cv-r-a0", "rA0, &in[2], &in[3]);", "rA1, &in[2], &in[3]);", rel=CCP),
    M("cv-r-b1", "rB1, &in[4], &in[5]);", "rB0, &in[4], &in[5]);", rel=CCP),
    M("cv-r-b0", "rB0, &in[6], &in[7]);", "rB1, &in[6], &in[7]);", rel=CCP),
    M("cv-ov1", "if (!ccp_interval_overlap(in[0], in[1], in[2], in[3], &lo, &hi)",
      "if (!ccp_interval_overlap(in[0], in[1], in[0], in[1], &lo, &hi)",
      rel=CCP),
    M("cv-ov2", "        || !ccp_interval_overlap(lo, hi, in[4], in[5], &lo, &hi)\n",
      "", rel=CCP),
    M("cv-ov3",
      "        || !ccp_interval_overlap(lo, hi, in[6], in[7], &lo, &hi)) {",
      "        ) {", rel=CCP),
    M("cv-fail", "        lo = CCP_NO_OVERLAP;\n        hi",
      "        lo = -1.0f;\n        hi", rel=CCP),
    M("cv-ret-lo", "if (0.0f < lo)\n        return lo;",
      "if (0.0f <= lo)\n        return lo;", rel=CCP),
    M("cv-ret-0", "if (lo < 0.0f && 0.0f < hi)", "if (lo < 0.0f)", rel=CCP),
    M("cv-ret-0-hi", "if (lo < 0.0f && 0.0f < hi)",
      "if (lo < 0.0f && 0.0f <= hi)", rel=CCP),
    M("cv-ret-0-lo", "if (lo < 0.0f && 0.0f < hi)",
      "if (lo <= 0.0f && 0.0f < hi)", rel=CCP),
    M("cv-ret-none", "        return 0.0f;\n    return CCP_NO_OVERLAP;",
      "        return 0.0f;\n    return hi;", rel=CCP),
    # -- TimeIntervalForSeparatingAxis ------------------------------------
    M("ct-still-fabs", "if (fabsf(v) < CCP_AXIS_STILL) {",
      "if (v < CCP_AXIS_STILL) {", rel=CCP),
    M("ct-still-le", "if (fabsf(v) < CCP_AXIS_STILL) {",
      "if (fabsf(v) <= CCP_AXIS_STILL) {", rel=CCP),
    M("ct-r", "if (r < fabsf(d)) {", "if (r <= fabsf(d)) {", rel=CCP),
    M("ct-r-fabs", "if (r < fabsf(d)) {", "if (r < d) {", rel=CCP),
    M("ct-never-min", "*tmin = CCP_NEVER;", "*tmin = CCP_ALWAYS;", rel=CCP),
    M("ct-never-max", "*tmin = CCP_NEVER;\n            *tmax = CCP_NEVER;",
      "*tmin = CCP_NEVER;\n            *tmax = CCP_ALWAYS;", rel=CCP),
    M("ct-always-min", "*tmin = CCP_ALWAYS;", "*tmin = CCP_NEVER;", rel=CCP),
    M("ct-always-max", "*tmin = CCP_ALWAYS;\n            *tmax = CCP_NEVER;",
      "*tmin = CCP_ALWAYS;\n            *tmax = CCP_ALWAYS;", rel=CCP),
    M("ct-return", "        return;\n    }\n    *tmax = (r - d) / v;",
      "    }\n    *tmax = (r - d) / v;", rel=CCP),
    M("ct-tmax", "*tmax = (r - d) / v;", "*tmax = (r + d) / v;", rel=CCP),
    M("ct-tmin", "*tmin = -(r + d) / v;", "*tmin = (r + d) / v;", rel=CCP),
    M("ct-tmin-d", "*tmin = -(r + d) / v;", "*tmin = -(r - d) / v;", rel=CCP),
    M("ct-swap", "if (v < 0.0f) {", "if (v > 0.0f) {", rel=CCP),
    M("ct-swap-half", "        *tmin = *tmax;\n        *tmax = lo;",
      "        *tmin = *tmax;", rel=CCP),
    # -- IntervalOverlap ------------------------------------------------
    M("cn-passes", "for (n = 3; n > 0; n--) {", "for (n = 2; n > 0; n--) {",
      rel=CCP),
    M("cn-inner", "for (k = 0; k < n; k++) {", "for (k = 1; k < n; k++) {",
      rel=CCP),
    M("cn-cmp", "if (e[k + 1] < e[k]) {", "if (e[k + 1] <= e[k]) {",
      rel=CCP),
    M("cn-swap", "                e[k] = e[k + 1];\n                e[k + 1] = x;",
      "                e[k] = e[k + 1];", rel=CCP),
    M("cn-a0", "if (a0 <= e[1] && e[1] <= a1", "if (a0 < e[1] && e[1] <= a1",
      rel=CCP),
    M("cn-a1", "&& e[1] <= a1 &&", "&& e[1] < a1 &&", rel=CCP),
    M("cn-b0", "&& b0 <= e[1] &&", "&& b0 < e[1] &&", rel=CCP),
    M("cn-b1", "&& e[1] <= b1)", "&& e[1] < b1)", rel=CCP),
    M("cn-lo", "*lo = e[1];", "*lo = e[0];", rel=CCP),
    M("cn-hi", "*hi = e[2];", "*hi = e[3];", rel=CCP),
    M("cn-ret", "        return 1;\n    }\n    return 0;",
      "        return 0;\n    }\n    return 0;", rel=CCP),
]

EQUIVALENT = {
    "fx-its-side":
        "The side test on the oncoming car's own choice guards two tests "
        "that its type is CHOICE_LEFT_SIDE_OF_CAR or CHOICE_RIGHT_SIDE_OF_"
        "CAR, the only two types IsSideOfCar accepts. Without it, a choice "
        "of any other type with pCar equal to this car reaches those tests "
        "and fails both, leaving ok as it was: the same result for every "
        "type.",
    "sm-full":
        "Without the test before the loop, a full target goes once round "
        "it: the point is worked out and handed to AddPointToTarget, which "
        "refuses it at its own NumPoints < 20 before touching anything, "
        "and the loop's own test then stops. Nothing in the pass writes "
        "anywhere else.",
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
