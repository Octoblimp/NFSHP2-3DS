#!/usr/bin/env python3
"""Cross-check 3DS Files/source/nearbycar.c and drivinglocation.c, what an
AI car knows of the cars around it and where it drives, against the retail
image itself, run in mipsemu.

The model is the image. NearbyCarList's BuildArray (0x00193898),
ClearArray (0x001940c8), GetCarsIndexInArray (0x00193d90), GetNearbyCar
(0x00193dd8) and GetCarAhead (0x00193e20), DrivingInformation::Clear
(0x00193e68), the free CalculateMaxAcceleration (0x001cce50),
CanICatchThisCar (0x001ccfd8), DoWeCareAboutThisCar (0x001ccde8),
GetCurrentCurvatureOfDrivingLine (0x001ccbc0) and HighlightDrivingLine
(0x001cb450), and DrivingLocation's Clear (0x001941e0), SetRoute
(0x00239bb0), SetRoutePoint, SetDrivingLine, SetRelaxedSwitch,
GetNumSecondsLeftInRelaxedSwitch and AreWeInARelaxedSwitch (0x00239bc8 ..
0x00239c48) run as shipped, over retail's own Car::IsPoofed, WorldToCar,
GetForwardAcceleration and GetCarSpaceBoundingBox, CalculateLookAhead
Distance, CompareDistances, GetAccelerationTable, Table::GetValue, the
TrackRoutePoint's GetPosition, bATan, bCos, bNormalize, the e-matrix
calls, bMemSet and bMemCpy. The harness (tools/src/nearbycar_test.c) runs
the port over the same script, and the two transcripts are diffed.

One stub: BeltMover::GetAccelerationDueToGravity (0x00204668), which the
port reaches through gBeltMoverGravityFn while BeltMover is unported,
answers the script's value for whichever car's mover it is handed. It
prints nothing, because the image calls CalculateMaxAcceleration twice
where its answer is dead and the port does not.

The cars are retail's at retail's offsets (docs/retail_layout.txt) and the
port's by name: each car's position, velocity with its fourth lane,
acceleration, body x axis, angle, forward speed, speed, boost and draft
factors, the rendering byte, the poofed word, DistanceAroundTrack, the
control and movement modes, its type, CarTypeInfo's drag, speed limiter
and mass, a player or none, its collision body's bounding box and its belt
gravity. MatrixValid is cleared whenever a car is set, so both sides build
the cached RelCoordMatrix afresh. The world's car list is linked in the
script's order. The acceleration tables are the script's, by type.

A float prints as its bits, a NaN as "nan", and a pointer by what it is:
c3 a car, e5 the list's sixth entry, s the scratch NearbyCar, R1 a route,
R1:17 a point, pat the 0xa5 fill.

    python tools/nearbycar_check.py
    python tools/nearbycar_check.py --mutate [--only a,b]
    python tools/nearbycar_check.py --dump out/nearbycar
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

HARNESS = "tools/src/nearbycar_test.c"
NBC = "3DS Files/source/nearbycar.c"
DLC = "3DS Files/source/drivinglocation.c"
SOURCES = [HARNESS, NBC, DLC] + ["3DS Files/source/" + f for f in (
    "drivetarget.c", "car.c", "carstate.c", "carinfo.c", "cartypeinfo.c",
    "langtab.c", "drivetrain.c", "engine.c", "wheel.c", "suspension.c",
    "steering.c", "rigidbody.c", "table.c", "trackroute.c", "trackpath.c",
    "quickspline.c", "bchunk.c", "world.c", "graph.c", "race.c",
    "copmanager.c", "replay.c", "p32.c", "bmem.c", "vtable.c", "emath.c",
    "bmatrix.c", "bvector.c", "bmath.c", "bmathtab.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
BUILD = 0x00193898
CLEAR_ARRAY = 0x001940c8
INDEX = 0x00193d90
NEARBY = 0x00193dd8
AHEAD = 0x00193e20
DI_CLEAR = 0x00193e68
MAX_ACCEL = 0x001cce50
CAN_CATCH = 0x001ccfd8
DO_WE_CARE = 0x001ccde8
CURVATURE = 0x001ccbc0
HIGHLIGHT = 0x001cb450
DL_CLEAR = 0x001941e0
DL_SET_ROUTE = 0x00239bb0
DL_SET_POINT = 0x00239bc8
DL_SET_LINE = 0x00239bd0
DL_SET_RELAXED = 0x00239be0
DL_SECONDS = 0x00239bf8
DL_ARE_WE = 0x00239c48
BELT_GRAVITY = 0x00204668

TPM = 0x0031bc38                  # TheTrackPathManager, TrackLength at 0
ACCEL = 0x0030daf0                # TheCarTypeAccelerationTable
ACCEL_STRIDE = 148
ACCEL_TABLE = 128

GLOBALS = {
    "WORLD": GP - 22120,          # pCurrentWorld
    "TDLF": GP - 20496,           # TrafficDriverLookaheadFactor
    "PASS": GP - 18164,           # AIActionPassMaxTimeAheadToMakeAttempt
    "SECS": GP - 20328,           # AIDriverSecondsToLookAhead
    "DEF": GP - 20324,            # AIDriverDefaultLookAhead
    "CAM": GP - 21528,            # CameraFollowThisCarInstead
    "HROUTE": GP - 18316,         # HighlightDrivingLineInRouteNumber
    "HLINE": GP - 18312,          # HighlightDrivingLineNumber
    "TIMER": GP - 19576,          # WorldTimer
    "LEN": TPM,                   # TheTrackPathManager.TrackLength
}

WORLD = 0x01000000
CARS = 0x01010000
CAR_STRIDE = 0x1000
NCARS = 32
CTIS = 0x01040000
CTI_STRIDE = 0x800
RIDES = 0x01050000
BODIES = 0x01060000
BODY_STRIDE = 0x200
MOVERS = 0x01070000
MOVER_STRIDE = 0x40
PLAYER = 0x01080000
LIST = 0x01090000
SCRATCH = 0x01090400
DI = 0x01090800
LOC = 0x01090c00
ROUTES = 0x01100000
ROUTE_STRIDE = 0x20000
NROUTES = 4

# The car, at retail's offsets.
C_NEXT = 0
C_PREV = 4
C_CTI = 12
C_RIDE = 16
C_PLAYER = 24
C_CTL = 32
C_MOV = 36
C_MOVER = 48
C_BODY = 52
C_POS = 96
C_VEL = 112
C_ACC = 128
C_BM = 144
C_ANGLE = 932
C_FWD = 960
C_VMAG = 964
C_BOOST = 992
C_MVALID = 1088
C_DRAFT = 1112
C_REND = 1192
C_DAT = 2036
C_POOF = 2160
CTI_MASS = 480
CTI_DRAG = 752
CTI_LIMITER = 800
B_MIN = 224
B_MAX = 240

NC_SIZE = 28
LIST_ARRAY = 8
LIST_MAX = 16
LIST_HL = 456
LIST_HD = 460
DI_LOC = 464
DI_CHOICE = 480

RT_HEADER = 1064
RT_POINT = 112
LINES = 21

PATTERN = 0xa5
PAT32 = 0xa5a5a5a5

TRAFFIC = 3
BELT = 6
NTYPES = 6


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


def car_at(k):
    return CARS + CAR_STRIDE * k


def route_at(k):
    return ROUTES + ROUTE_STRIDE * k


# ============================================================ the scenarios
#
# B n                   a scenario: everything cleared, the list, the
#                       scratch entry and DrivingInformation filled
# A t n min max mul d.. type t's acceleration table: n entries over
#                       min..max, IndexMultiplier mul
# G name word           a global (GLOBALS)
# C k w0 .. w34         car k (CAR_FIELDS), MatrixValid cleared
# L k ..                the world's car list, in this order
# R                     the list filled with 0xa5
# N me loc              the list's MyCar is car me (-1 none), then
#                       BuildArray with the location (1) or NULL (0)
# M                     the list dumped
# I k                   GetCarsIndexInArray, GetNearbyCar and GetCarAhead of
#                       car k (-1 NULL)
# Q px py vx vy L D k   the scratch NearbyCar
# Y e                   DoWeCareAboutThisCar of entry e (0..15, s, n)
# K e me acc flag       CanICatchThisCar of entry e for car me
#
# An entry at or past the list's count is skipped, by Y and K both: the
# game asks only of the cars it kept, and an empty entry's car is NULL.
# X k speed             CalculateMaxAcceleration
# U k n rn              route k's header: n points, route number rn
# P w0 .. w27           the route's next point
# D r j line t          the location set by hand (r, j -1 for NULL)
# V                     GetCurrentCurvatureOfDrivingLine of the location
# H i                   HighlightDrivingLine of the location for car index i
# S r j line rel        SetRoute
# T r j                 SetRoutePoint, route r's point j
# J line rel            SetDrivingLine
# Z rel                 SetRelaxedSwitch
# E                     GetNumSecondsLeftInRelaxedSwitch and AreWe...
# O                     DrivingLocation::Clear
# F                     DrivingInformation::Clear
# W                     NearbyCarList::ClearArray

CAR_FIELDS = (
    "px", "py", "pz", "vx", "vy", "vz", "vw", "ax", "ay", "az",
    "bx", "by", "bz", "angle", "fwd", "vmag", "boost", "draft", "rend",
    "poof", "dat", "ctl", "mov", "type", "drag", "limiter", "mass",
    "player", "minx", "miny", "minz", "maxx", "maxy", "maxz", "belt")


class World(object):
    def __init__(self, rnd, tracklen=None):
        self.rnd = rnd
        self.len = tracklen if tracklen is not None else f32(
            rnd.choice((2000.0, 4800.0, 9000.0, 650.0)))
        self.ops = ["G LEN %s" % h(self.len)]
        for t in range(NTYPES):
            self.ops.append(table_op(rnd, t))

    def car(self, k, **kw):
        rnd = self.rnd
        a = rnd.uniform(-math.pi, math.pi)
        sp = rnd.choice((0.0, 0.5, rnd.uniform(1.0, 60.0),
                         rnd.uniform(1.0, 60.0), rnd.uniform(10.0, 45.0)))
        va = a + rnd.choice((0.0, rnd.uniform(-0.6, 0.6), math.pi))
        v = dict(
            px=rnd.uniform(-150.0, 150.0), py=rnd.uniform(-150.0, 150.0),
            pz=rnd.uniform(-5.0, 5.0),
            vx=sp * math.cos(va), vy=sp * math.sin(va),
            vz=rnd.uniform(-1.0, 1.0),
            vw=rnd.choice((0.0, 0.0, rnd.uniform(-5.0, 5.0))),
            ax=rnd.uniform(-10.0, 10.0), ay=rnd.uniform(-10.0, 10.0),
            az=rnd.uniform(-3.0, 3.0))
        sc = rnd.choice((1.0, 1.0, rnd.uniform(0.5, 1.5)))
        tilt = rnd.choice((0.0, rnd.uniform(-0.3, 0.3), rnd.uniform(-1, 1)))
        v.update(bx=sc * math.cos(a), by=sc * math.sin(a), bz=sc * tilt)
        v["angle"] = (int(round(a / (2 * math.pi) * 65536))
                      + rnd.choice((0, 0, rnd.randint(-3000, 3000)))) & 0xffff
        v["fwd"] = sp * rnd.choice((1.0, 1.0, -1.0))
        v["vmag"] = rnd.choice((sp, sp, 0.05, sp * 1.1))
        v["boost"] = rnd.choice((1.0, 1.0, 1.25, 0.8))
        v["draft"] = rnd.choice((0.0, rnd.uniform(0.0, 0.3)))
        v["rend"] = rnd.choice((1, 1, 1, 1, 0, -1, 2))
        v["poof"] = rnd.choice((0, 0, 0, 0, 1, 2, 3))
        v["dat"] = rnd.uniform(0.0, self.len)
        v["ctl"] = rnd.choice((0, 1, 2, 3, 3, 4))
        v["mov"] = rnd.choice((0, 1, 2, 3, 4, 5, 6, 6, 7))
        v["type"] = rnd.randrange(NTYPES)
        v["drag"] = rnd.choice((rnd.uniform(0.2, 0.6), rnd.uniform(0.2, 0.6),
                                0.0005, 0.002))
        v["limiter"] = rnd.choice((0.0, 100.0, 120.0, 150.0, 200.0))
        v["mass"] = rnd.uniform(900.0, 2200.0)
        v["player"] = rnd.choice((0, 0, 1))
        hw, hl = rnd.uniform(0.8, 1.2), rnd.uniform(2.0, 2.8)
        v.update(minx=-hw * rnd.uniform(0.9, 1.1), miny=-hl * rnd.uniform(
            0.9, 1.1), minz=-0.5, maxx=hw, maxy=hl, maxz=1.2)
        v["belt"] = rnd.uniform(-3.0, 3.0)
        v.update(kw)
        return car_op(k, v), v


def car_op(k, v):
    out = []
    for f in CAR_FIELDS:
        x = v[f]
        if f in ("angle", "rend", "poof", "ctl", "mov", "type", "player"):
            out.append("%x" % (int(x) & M32))
        else:
            out.append(h(f32(x)))
    return "C %d %s" % (k, " ".join(out))


def table_op(rnd, t):
    n = rnd.choice((32, 32, 16, 8, 2))
    mx = f32(rnd.choice((55.555557, 70.0, 40.0)))
    data = []
    a = rnd.uniform(6.0, 12.0)
    for i in range(n):
        data.append(f32(max(0.0, a * (1.0 - (i / float(n)) ** 1.5))))
    if rnd.random() < 0.5:
        data[-1] = 0.0
    mul = f32(f32(float(n - 1)) / mx)
    return "A %d %d %s %s %s %s" % (t, n, h(0.0), h(mx), h(mul),
                                    " ".join(h(d) for d in data))


def link(ks):
    return "L " + " ".join("%d" % k for k in ks) if ks else "L"


def lookups(rnd, ks, extra=()):
    ops = []
    for k in list(ks) + list(extra) + [-1]:
        ops.append("I %d" % k)
    for e in range(LIST_MAX):
        if rnd.random() < 0.5:
            ops.append("Y %d" % e)
    ops.append("Y n")
    return ops


def s_basic(rnd):
    """A pack of cars along the track, most near, a few anywhere."""
    w = World(rnd)
    ops = list(w.ops)
    n = rnd.randint(4, 14)
    ks = list(range(n))
    base = rnd.uniform(0.0, w.len)
    spread = rnd.choice((20.0, 40.0, 70.0))
    for k in ks:
        if rnd.random() < 0.8:
            x = rnd.uniform(-spread * 0.4, spread * 0.4)
            y = rnd.uniform(-spread, spread)
            dat = (base + y + rnd.uniform(-10.0, 10.0)) % w.len
            ops.append(w.car(k, px=x, py=y, dat=f32(dat))[0])
        else:
            ops.append(w.car(k)[0])
    ops.append(link(ks))
    for me in ks:
        ops.append("N %d 1" % me)
        ops += lookups(rnd, ks)
    return ops


def s_crowd(rnd):
    """More than sixteen to choose from, all near, the full list walking
    on."""
    w = World(rnd)
    ops = list(w.ops)
    n = rnd.randint(17, NCARS)
    ks = list(range(n))
    me = rnd.randrange(n)
    for k in ks:
        ops.append(w.car(k, px=rnd.uniform(-15.0, 15.0),
                         py=rnd.uniform(-15.0, 15.0), poof=0, rend=1,
                         dat=f32(100.0 + rnd.uniform(-5.0, 5.0)))[0])
    rnd.shuffle(ks)
    ops.append(link(ks))
    for m in (me, ks[0], ks[-1]):
        ops.append("N %d 1" % m)
        ops += lookups(rnd, ks[:4] + ks[-3:])
    return ops


def s_catch(rnd):
    """Cars past the look-ahead that a closing speed or a difference in
    acceleration brings within reach, and ones it does not."""
    w = World(rnd)
    ops = list(w.ops)
    me_line, me = w.car(0, px=0.0, py=0.0, vx=0.0, vy=rnd.uniform(5.0, 20.0),
                        vmag=10.0, ctl=0, dat=f32(1000.0))
    ops.append(me_line)
    ks = [0]
    for k in range(1, rnd.randint(6, 14)):
        d = rnd.uniform(25.0, 140.0)
        ang = rnd.uniform(-math.pi, math.pi)
        rv = rnd.uniform(-40.0, 40.0)
        ops.append(w.car(k, px=d * math.cos(ang), py=d * math.sin(ang),
                         vx=rv * math.cos(ang + math.pi),
                         vy=rv * math.sin(ang + math.pi),
                         dat=f32(1000.0 + d * math.sin(ang)
                                 + rnd.uniform(-20.0, 20.0)))[0])
        ks.append(k)
    ops.append(link(ks))
    for secs, pas in (("40000000", "40400000"), ("40000000", "3f800000"),
                      ("3f000000", "40a00000")):
        ops.append("G SECS %s" % secs)
        ops.append("G PASS %s" % pas)
        ops.append("N 0 1")
        ops += lookups(rnd, ks[:5])
    ops.append("G SECS 40000000")
    ops.append("G PASS 40400000")
    return ops


def s_round(rnd):
    """Near in space and far round the track, across the track's join, for
    a car of each control mode: only a traffic car's look-ahead takes the
    factor. Car 12 is car 0 in traffic, and not on the list."""
    w = World(rnd, tracklen=f32(3000.0))
    ops = list(w.ops)
    line, me = w.car(0, px=0.0, py=0.0, vmag=12.0, ctl=0,
                     dat=f32(rnd.choice((10.0, 2990.0, 1500.0))))
    ops.append(line)
    ops.append(car_op(12, dict(me, ctl=TRAFFIC)))
    ks = [0]
    for k in range(1, 12):
        ops.append(w.car(k, px=rnd.uniform(-20.0, 20.0),
                         py=rnd.uniform(-20.0, 20.0), rend=1, poof=0,
                         dat=f32(rnd.uniform(0.0, 3000.0)))[0])
        ks.append(k)
    ops.append(link(ks))
    for tdlf in ("40400000", "3f800000", "41200000"):
        ops.append("G TDLF %s" % tdlf)
        for dflt in ("41a00000", "42c80000", "40000000"):
            ops.append("G DEF %s" % dflt)
            ops.append("N 0 1")
            ops.append("N 12 1")
    ops.append("G TDLF 40400000")
    ops.append("G DEF 41a00000")
    return ops


def s_edges(rnd):
    """No car, no location, an empty world, a car not on the list, ties in
    y, a car standing still and one reversing."""
    w = World(rnd)
    ops = list(w.ops)
    ops.append("N -1 1")
    ops.append("N -1 0")
    # Two cars on one spot and three on another, and the car's own: ties.
    for k, (x, y) in enumerate(((0.0, 0.0), (5.0, 10.0), (5.0, 10.0),
                                (-5.0, -10.0), (-5.0, -10.0),
                                (-5.0, -10.0))):
        ops.append(w.car(k, px=x, py=y, rend=1, poof=0, dat=f32(100.0))[0])
    ops.append("N 0 0")
    ops.append("L")
    ops.append("N 0 1")
    ops.append(link([1, 2, 3, 4, 5]))
    ops.append("N 0 1")
    ops += lookups(rnd, [0, 1, 2, 3, 4, 5])
    ops.append(w.car(0, vx=0.0, vy=0.0, vz=0.0, vmag=0.0, fwd=0.0)[0])
    ops.append(link([0, 1, 2, 3, 4, 5]))
    ops.append("N 0 1")
    ops.append(w.car(0, vx=-3.0, vy=-4.0, fwd=-5.0, vmag=5.0)[0])
    ops.append("N 0 1")
    ops.append(w.car(0, vx=0.3, vy=0.4, fwd=0.5, vmag=0.5)[0])
    ops.append("N 0 1")
    # Every rendering byte with every poofed word.
    k = 0
    for rend in (0, 1, 2, -1):
        for poof in (0, 1, 2, 3, -1, 0x101):
            ops.append(w.car(k, px=1.0 + k, py=2.0, rend=rend, poof=poof,
                             dat=f32(100.0))[0])
            k += 1
    ops.append(link(range(k)))
    ops.append("N 0 1")
    ops.append("N 7 1")
    ops.append("R")
    ops.append("M")
    ops.append("W")
    ops.append("M")
    return ops


def s_scratch(rnd):
    """DoWeCare and CanICatch on entries made by hand."""
    w = World(rnd)
    ops = list(w.ops)
    for k in range(4):
        ops.append(w.car(k, px=rnd.uniform(-10.0, 10.0),
                         py=rnd.uniform(-10.0, 10.0), rend=1, poof=0,
                         dat=f32(500.0 + rnd.uniform(-5.0, 5.0)),
                         maxx=1.0)[0])
    ops.append(link([0, 1, 2, 3]))
    ops.append("N 0 1")
    for _ in range(40):
        k = rnd.randrange(4)
        ops.append("Q %s %s %s %s %s %s %d" % (
            h(f32(rnd.uniform(-30.0, 30.0))),
            h(f32(rnd.choice((rnd.uniform(-10.0, 10.0), -4.5, -5.0, -4.0,
                              rnd.uniform(-60.0, 60.0))))),
            h(f32(rnd.uniform(-30.0, 30.0))), h(f32(rnd.uniform(-30.0, 30.0))),
            h(f32(rnd.uniform(0.8, 2.8))),
            h(f32(rnd.choice((rnd.uniform(0.8, 2.8), 2.0, 2.5)))), k))
        ops.append("Y s")
        me = rnd.randrange(4)
        acc = rnd.choice((0.0, -1.0, 3.0))
        ops.append("K s %d %s %d" % (me, h(f32(acc)), rnd.choice((0, 1))))
        for e in range(2):
            ops.append("K %d %d %s 0" % (e, me, h(f32(acc))))
    # The bias on its edge: a player's car at exactly the sum.
    ops.append(w.car(1, player=1)[0])
    ops.append(w.car(2, player=0)[0])
    for y in (-4.0, -4.5, -5.0, -3.5, -3.0, -2.5, -2.0):
        for k in (1, 2):
            ops.append("Q %s %s %s %s %s %s %d" % (
                h(0.0), h(f32(y)), h(0.0), h(0.0), h(f32(2.0)), h(f32(2.0)),
                k))
            ops.append("Y s")
    return ops


def s_maxacc(rnd):
    w = World(rnd)
    ops = list(w.ops)
    for k in range(8):
        ops.append(w.car(k)[0])
    for _ in range(60):
        k = rnd.randrange(8)
        sp = rnd.choice((0.0, rnd.uniform(0.0, 80.0), 44.704, 53.6448,
                         rnd.uniform(40.0, 70.0)))
        ops.append("X %d %s" % (k, h(f32(sp))))
    # A belt car and one not, at the speed limiter and either side of it,
    # with so little drag that the cap can take.
    lim = f32(f32(100.0) * f32(0.447027266))
    ops.append(w.car(0, mov=BELT, limiter=100.0, boost=1.0, drag=0.0005,
                     draft=0.0)[0])
    ops.append(w.car(1, mov=0, limiter=100.0, boost=1.0, bz=0.4,
                     drag=0.0005, draft=0.0)[0])
    for k in (0, 1):
        for sp in (44.0, lim, 44.71, 60.0, 0.0, 10.0):
            ops.append("X %d %s" % (k, h(f32(sp))))
    return ops


def lay_route(rnd, k, n, rn, x=0.0, y=0.0, turn=None, straight=False):
    """Route k's lines: its header and points. A straight one runs along x
    in steps of ten with every line on the centre, so its bend is exactly
    0."""
    if straight:
        out = ["U %d %d %d" % (k, n, rn)]
        for i in range(n):
            raw = struct.pack("<12f", 10.0 * i, 0.0, 0.0, 1.0, 0.0, 10.0,
                              8.0, 8.0, 0.0, 0.0, 10.0 * i, 0.0)[:44]
            raw += struct.pack("<I", 0) + bytes(2 * LINES)
            raw += bytes(LINES) + bytes([k])
            out.append("P " + " ".join("%08x" % v for v in
                                       struct.unpack("<28I", raw)))
        return out
    if turn is None:
        turn = rnd.choice((0.0, 0.05, -0.05, 0.2, rnd.uniform(-0.3, 0.3)))
    hd = rnd.uniform(-math.pi, math.pi)
    pos = []
    for i in range(n):
        pos.append((f32(x), f32(y)))
        s = rnd.uniform(6.0, 18.0)
        hd += turn + rnd.uniform(-0.05, 0.05)
        x += s * math.cos(hd)
        y += s * math.sin(hd)
    out = ["U %d %d %d" % (k, n, rn)]
    for i in range(n):
        px, py = pos[i]
        if i + 1 < n:
            nx, ny = pos[i + 1]
        else:
            nx = px + (px - pos[i - 1][0])
            ny = py + (py - pos[i - 1][1])
        dx, dy = nx - px, ny - py
        ln = math.hypot(dx, dy) or 1.0
        offs = [rnd.choice((0, rnd.randint(-2560, 2560), rnd.randint(-300, 300),
                            rnd.choice((32767, -32768))))
                for _ in range(LINES)]
        raw = struct.pack("<12f", px, py, rnd.uniform(-5.0, 5.0),
                          f32(dx / ln), f32(dy / ln), f32(ln),
                          rnd.uniform(4.0, 16.0), rnd.uniform(4.0, 16.0),
                          0.0, 0.0, rnd.uniform(0.0, 3000.0), 0.0)[:44]
        raw += struct.pack("<I", rnd.getrandbits(32))
        raw += struct.pack("<21h", *offs)
        raw += bytes(rnd.randrange(256) for _ in range(LINES)) + bytes([k])
        assert len(raw) == RT_POINT
        out.append("P " + " ".join("%08x" % v for v in
                                   struct.unpack("<28I", raw)))
    return out


def s_curve(rnd):
    ops = []
    sizes = (60, 13, 45, 30)
    for k in range(NROUTES):
        ops += lay_route(rnd, k, sizes[k], rnd.choice((k, 300 + k, -2)),
                         straight=(k == 3))
    for _ in range(60):
        k = rnd.choice((0, 0, 2, 2, 1, 3))
        n = sizes[k]
        j = rnd.choice((0, n - 13, n - 12, n - 1, rnd.randrange(n),
                        rnd.randrange(n), rnd.randrange(max(1, n - 12))))
        j = max(0, min(n - 1, j))
        ops.append("D %d %d %d %08x" % (k, j, rnd.randrange(LINES),
                                        rnd.getrandbits(32)))
        ops.append("V")
        cam = rnd.choice((0, 1, 2, -1))
        ops.append("G CAM %08x" % (cam & M32))
        ops.append("H %d" % rnd.choice((cam, cam, 0, 3)))
    ops.append("D -1 -1 3 00000000")
    ops.append("V")
    ops.append("G CAM 00000002")
    ops.append("H 2")
    ops.append("H 1")
    return ops


def s_location(rnd):
    ops = []
    for k in range(2):
        ops += lay_route(rnd, k, 20, k)
    ops.append("G TIMER 00000000")
    ops.append("O")
    ops.append("E")
    for _ in range(50):
        c = rnd.randrange(7)
        if c == 0:
            ops.append("G TIMER %08x" % rnd.choice((
                rnd.getrandbits(32), rnd.randrange(100000),
                0x7fffffff, 0x80000000, 0xffffffff)))
        elif c == 1:
            ops.append("S %d %d %d %d" % (rnd.choice((0, 1, -1)),
                                          rnd.choice((0, 5, 19, -1)),
                                          rnd.choice((0, 3, 20, -1)),
                                          rnd.choice((0, 1, 2, -1))))
        elif c == 2:
            ops.append("T %d %d" % (rnd.choice((0, 1)),
                                    rnd.choice((0, 7, -1))))
        elif c == 3:
            ops.append("J %d %d" % (rnd.choice((1, 7, -1, 300)),
                                    rnd.choice((0, 1, 0x100))))
        elif c == 4:
            ops.append("Z %d" % rnd.choice((0, 1, -2)))
        elif c == 5:
            ops.append("O")
        else:
            ops.append("G TIMER %08x" % rnd.randrange(30000))
        ops.append("E")
    # Exactly three seconds, and either side, from a switch at 1000.
    ops.append("G TIMER 000003e8")
    ops.append("Z 1")
    for t in (1000, 12999, 13000, 13001, 13004, 999, 0x800003e8):
        ops.append("G TIMER %08x" % t)
        ops.append("E")
    return ops


def s_clear(rnd):
    w = World(rnd)
    ops = list(w.ops)
    ops.append("F")
    ops.append("W")
    ops.append("M")
    for k in range(3):
        ops.append(w.car(k)[0])
    ops.append(link([0, 1, 2]))
    ops.append("N 1 1")
    ops.append("W")
    ops.append("M")
    ops.append("I 1")
    return ops


def script():
    rnd = random.Random(0x4ea6b9)
    sc = [s_basic(rnd), s_crowd(rnd), s_catch(rnd), s_round(rnd),
          s_edges(rnd), s_scratch(rnd), s_maxacc(rnd), s_curve(rnd),
          s_location(rnd), s_clear(rnd)]
    for _ in range(6):
        sc.append(s_basic(rnd))
        sc.append(s_catch(rnd))
        sc.append(s_crowd(rnd))
    for _ in range(2):
        sc.append(s_scratch(rnd))
        sc.append(s_maxacc(rnd))
        sc.append(s_curve(rnd))
        sc.append(s_location(rnd))
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
        self.e.stub(BELT_GRAVITY, self.s_belt)
        self.w = self.e.u32
        self.belt = {}

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
        if CARS <= a < CARS + CAR_STRIDE * NCARS:
            k, off = divmod(a - CARS, CAR_STRIDE)
            if off == 0:
                return "c%d" % k
        if a == SCRATCH:
            return "s"
        if LIST + LIST_ARRAY <= a < LIST + LIST_ARRAY + NC_SIZE * LIST_MAX:
            i, off = divmod(a - LIST - LIST_ARRAY, NC_SIZE)
            if off == 0:
                return "e%d" % i
        if ROUTES <= a < ROUTES + ROUTE_STRIDE * NROUTES:
            k, off = divmod(a - ROUTES, ROUTE_STRIDE)
            if off == 0:
                return "R%d" % k
            if off >= RT_HEADER and (off - RT_HEADER) % RT_POINT == 0:
                return "R%d:%d" % (k, (off - RT_HEADER) // RT_POINT)
        return "?%08x" % a

    # ---- the stub --------------------------------------------------------

    def s_belt(self, em):
        m = em.reg[4] & M32
        em.fpr[0] = self.belt[m]

    # ---- the dumps -------------------------------------------------------

    def dump_list(self, a):
        w = self.w
        self.emit("  list me %s n %d hl %s hd %s" % (
            self.name(w(a)), s32(w(a + 4)), fx(w(a + LIST_HL)),
            fx(w(a + LIST_HD))))
        for i in range(LIST_MAX):
            b = a + LIST_ARRAY + NC_SIZE * i
            self.emit("    %d %s %s %s %s %s %s %s" % (
                i, fx(w(b)), fx(w(b + 4)), fx(w(b + 8)), fx(w(b + 12)),
                fx(w(b + 16)), fx(w(b + 20)), self.name(w(b + 24))))

    def dump_loc(self, a, tag="loc"):
        w = self.w
        self.emit("  %s %s %s line %d t %08x" % (
            tag, self.name(w(a)), self.name(w(a + 4)), s32(w(a + 8)),
            w(a + 12)))

    # ---- the world -------------------------------------------------------

    def reset(self):
        e = self.e
        e.mem[WORLD:WORLD + 0x10000] = bytes(0x10000)
        e.mem[CARS:CARS + CAR_STRIDE * NCARS] = bytes(CAR_STRIDE * NCARS)
        e.put32(GLOBALS["WORLD"], WORLD)
        self.link([])
        self.fill(LIST, 464)
        self.fill(SCRATCH, NC_SIZE)
        self.fill(DI, 492)
        self.fill(LOC, 16)
        for name, v in (("TDLF", 0x40400000), ("PASS", 0x40400000),
                        ("SECS", 0x40000000), ("DEF", 0x41a00000),
                        ("CAM", M32), ("HROUTE", M32), ("HLINE", M32),
                        ("TIMER", 0), ("LEN", 0x44fa0000)):
            e.put32(GLOBALS[name], v)
        self.belt = {}

    def link(self, ks):
        e = self.e
        nodes = [WORLD] + [car_at(k) for k in ks]
        for i, n in enumerate(nodes):
            e.put32(n + C_NEXT, nodes[(i + 1) % len(nodes)])
            e.put32(n + C_PREV, nodes[i - 1])

    def set_car(self, t):
        e = self.e
        k = int(t[1])
        v = dict(zip(CAR_FIELDS, (int(x, 16) for x in t[2:])))
        a = car_at(k)
        cti = CTIS + CTI_STRIDE * k
        ride = RIDES + 16 * k
        body = BODIES + BODY_STRIDE * k
        mover = MOVERS + MOVER_STRIDE * k
        e.put32(a + C_CTI, cti)
        e.put32(a + C_RIDE, ride)
        e.put32(a + C_PLAYER, PLAYER if v["player"] else 0)
        e.put32(a + C_CTL, v["ctl"])
        e.put32(a + C_MOV, v["mov"])
        e.put32(a + C_MOVER, mover)
        e.put32(a + C_BODY, body)
        for i, f in enumerate(("px", "py", "pz")):
            e.put32(a + C_POS + 4 * i, v[f])
        for i, f in enumerate(("vx", "vy", "vz", "vw")):
            e.put32(a + C_VEL + 4 * i, v[f])
        for i, f in enumerate(("ax", "ay", "az")):
            e.put32(a + C_ACC + 4 * i, v[f])
        for i, f in enumerate(("bx", "by", "bz")):
            e.put32(a + C_BM + 4 * i, v[f])
        struct.pack_into("<H", e.mem, a + C_ANGLE, v["angle"] & 0xffff)
        e.put32(a + C_FWD, v["fwd"])
        e.put32(a + C_VMAG, v["vmag"])
        e.put32(a + C_BOOST, v["boost"])
        e.put32(a + C_MVALID, 0)
        e.put32(a + C_DRAFT, v["draft"])
        e.mem[a + C_REND] = v["rend"] & 0xff
        e.put32(a + C_DAT, v["dat"])
        e.put32(a + C_POOF, v["poof"])
        e.put32(ride, v["type"])
        e.put32(cti + CTI_DRAG, v["drag"])
        e.put32(cti + CTI_LIMITER, v["limiter"])
        e.put32(cti + CTI_MASS, v["mass"])
        for i, f in enumerate(("minx", "miny", "minz")):
            e.put32(body + B_MIN + 4 * i, v[f])
        e.put32(body + B_MIN + 12, 0)
        for i, f in enumerate(("maxx", "maxy", "maxz")):
            e.put32(body + B_MAX + 4 * i, v[f])
        e.put32(body + B_MAX + 12, 0)
        self.belt[mover] = v["belt"]

    def set_table(self, t):
        e = self.e
        k, n = int(t[1]), int(t[2])
        a = ACCEL + ACCEL_STRIDE * k
        e.mem[a:a + ACCEL_STRIDE] = bytes(ACCEL_STRIDE)
        for i in range(n):
            e.put32(a + 4 * i, int(t[6 + i], 16))
        tb = a + ACCEL_TABLE
        e.put32(tb, a)
        e.put32(tb + 4, n)
        e.put32(tb + 8, int(t[3], 16))
        e.put32(tb + 12, int(t[4], 16))
        e.put32(tb + 16, int(t[5], 16))

    def set_route(self, t):
        e = self.e
        k, n, rn = int(t[1]), int(t[2]), int(t[3])
        a = route_at(k)
        e.mem[a:a + RT_HEADER] = bytes(RT_HEADER)
        struct.pack_into("<hh", e.mem, a + 8, 1, rn)
        e.put32(a + 16, n)
        e.put32(a + 20, n)
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

    def entry(self, s):
        if s == "s":
            return SCRATCH
        if s == "n":
            return 0
        return LIST + LIST_ARRAY + NC_SIZE * int(s)

    def past(self, s):
        return s not in ("s", "n") and int(s) >= s32(self.w(LIST + 4))

    def car_ptr(self, s):
        k = int(s)
        return car_at(k) if k >= 0 else 0

    # ---- the ops ---------------------------------------------------------

    def call(self, fn, *args, **f):
        e = self.e
        for i, v in f.items():
            e.fpr[int(i[1:])] = v & M32
        return e.call(fn, *args, limit=2000000)

    def op(self, t):
        e = self.e
        c = t[0]
        if c == "A":
            self.set_table(t)
        elif c == "G":
            e.put32(GLOBALS[t[1]], int(t[2], 16))
        elif c == "C":
            self.set_car(t)
        elif c == "L":
            self.link([int(k) for k in t[1:]])
        elif c == "R":
            self.fill(LIST, 464)
        elif c == "N":
            e.put32(LIST, self.car_ptr(t[1]))
            self.call(BUILD, LIST, LOC if int(t[2]) else 0, f12=0x3f800000)
            self.dump_list(LIST)
        elif c == "M":
            self.dump_list(LIST)
        elif c == "I":
            car = self.car_ptr(t[1])
            i = self.call(INDEX, LIST, car)
            nb = self.call(NEARBY, LIST, car)
            ah = self.call(AHEAD, LIST, car)
            self.emit("  index %d nearby %s ahead %s" % (
                i, self.name(nb), self.name(ah)))
        elif c == "Q":
            for i in range(6):
                e.put32(SCRATCH + 4 * i, int(t[1 + i], 16))
            e.put32(SCRATCH + 24, self.car_ptr(t[7]))
        elif c == "Y":
            if self.past(t[1]):
                self.emit("  skip")
                return
            got = self.call(DO_WE_CARE, self.entry(t[1]), LIST)
            self.emit("  care %d" % got)
        elif c == "K":
            if self.past(t[1]):
                self.emit("  skip")
                return
            got = self.call(CAN_CATCH, self.entry(t[1]), self.car_ptr(t[2]),
                            int(t[4]), f12=int(t[3], 16))
            self.emit("  catch %d" % got)
        elif c == "X":
            self.call(MAX_ACCEL, self.car_ptr(t[1]), f12=int(t[2], 16))
            self.emit("  max %s" % fx(e.fpr[0]))
        elif c == "U":
            self.set_route(t)
        elif c == "P":
            a = self.cur_route + RT_HEADER + RT_POINT * self.cur_n
            for i in range(28):
                e.put32(a + 4 * i, int(t[1 + i], 16))
            self.cur_n += 1
        elif c == "D":
            e.put32(LOC, self.route_of(t[1]))
            e.put32(LOC + 4, self.point_of(t[1], t[2]))
            e.put32(LOC + 8, int(t[3]))
            e.put32(LOC + 12, int(t[4], 16))
        elif c == "V":
            self.call(CURVATURE, LOC)
            self.emit("  curve %s" % fx(e.fpr[0]))
        elif c == "H":
            self.call(HIGHLIGHT, LOC, int(t[1]))
            self.emit("  highlight %d %d" % (s32(self.w(GLOBALS["HROUTE"])),
                                             s32(self.w(GLOBALS["HLINE"]))))
        elif c == "S":
            self.call(DL_SET_ROUTE, LOC, self.route_of(t[1]),
                      self.point_of(t[1], t[2]), int(t[3]), int(t[4]))
            self.dump_loc(LOC)
        elif c == "T":
            self.call(DL_SET_POINT, LOC, self.point_of(t[1], t[2]))
            self.dump_loc(LOC)
        elif c == "J":
            self.call(DL_SET_LINE, LOC, int(t[1]), int(t[2]))
            self.dump_loc(LOC)
        elif c == "Z":
            self.call(DL_SET_RELAXED, LOC, int(t[1]))
            self.dump_loc(LOC)
        elif c == "E":
            self.call(DL_SECONDS, LOC)
            left = e.fpr[0]
            got = self.call(DL_ARE_WE, LOC)
            self.emit("  left %s relaxed %d" % (fx(left), got))
        elif c == "O":
            self.call(DL_CLEAR, LOC)
            self.dump_loc(LOC)
        elif c == "F":
            self.call(DI_CLEAR, DI)
            w = self.w
            self.emit("  di me %s n %d hl %s hd %s" % (
                self.name(w(DI)), s32(w(DI + 4)), fx(w(DI + LIST_HL)),
                fx(w(DI + LIST_HD))))
            self.dump_loc(DI + DI_LOC, "diloc")
            self.emit("  choice %d %s %d" % (
                s32(w(DI + DI_CHOICE)), self.name(w(DI + DI_CHOICE + 4)),
                s32(w(DI + DI_CHOICE + 8))))
        elif c == "W":
            self.call(CLEAR_ARRAY, LIST)
        else:
            raise SystemExit("bad op %r" % (t,))

    def run(self, scenarios):
        for i, sc in enumerate(scenarios):
            self.emit("B %d" % i)
            self.reset()
            for ln in sc:
                if ln[0] not in "ACPU":
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


def build_harness(tmp, name="nearbycar_test"):
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


def M(name, before, after, rel=NBC):
    return (name, rel, before, after)


def D(name, before, after):
    return (name, DLC, before, after)


MUTATIONS = [
    # BuildArray.
    M("build-null-loc", "if (me == NULL || loc == NULL)", "if (me == NULL)"),
    M("build-memset", "memset(l->Array, 0, sizeof l->Array);",
      "memset(l->Array, 0, sizeof l->Array / 2);"),
    M("build-traffic", "if (me->TheControlMode == TRAFFIC_CONTROL)",
      "if (me->TheControlMode != TRAFFIC_CONTROL)"),
    M("build-traffic-factor", "look *= TrafficDriverLookaheadFactor;",
      "look *= 3.0f;"),
    M("build-max", "if (n >= NEARBYCARLIST_MAX)",
      "if (n >= NEARBYCARLIST_MAX - 1)"),
    M("build-poof-bool",
      "if (((car_is_poofed(c) ^ 1) & (int32_t)c->RenderingEnabled) == 0)",
      "if (car_is_poofed(c) || c->RenderingEnabled == 0)"),
    M("build-rend-byte", "& (int32_t)c->RenderingEnabled) == 0)",
      "& (int32_t)(uint8_t)c->RenderingEnabled) == 0)"),
    M("build-local", "car_world_to_car(me, &local,",
      "car_world_to_car(c, &local,"),
    M("build-rel", "rel.x = c->State.Velocity.x - me->State.Velocity.x;",
      "rel.x = c->State.Velocity.x + me->State.Velocity.x;"),
    M("build-dist", "dist = sqrtf(local.x * local.x + local.y * local.y);",
      "dist = sqrtf(local.y * local.y);"),
    M("build-round-abs", "round = fabsf(trackpath_compare_distances(",
      "round = (trackpath_compare_distances("),
    M("build-store-velocity", "nc->Velocity.y = rel.y;" + NL
      + "        nc->TheCar = c;", "nc->TheCar = c;"),
    M("build-look-le", "if (!(dist <= look) &&", "if (!(dist < look * 0.9f) &&"),
    M("build-catch", "if (!(dist <= look) && !ai_can_i_catch_this_car(nc, me,"
      " 0.0f, 0))", "if (!(dist <= look))"),
    M("build-round-3", "if (!(round <= look * 3.0f))",
      "if (!(round <= look * 2.0f))"),
    M("build-ang", "int32_t ang = bATan(me->State.Velocity.x,"
      " me->State.Velocity.y);", "int32_t ang = bATan(me->State.Velocity.y,"
      " me->State.Velocity.x);"),
    M("build-rotate", "(uint16_t)(16384 - ang)", "(uint16_t)(ang - 16384)"),
    M("build-rotated-store", "eMulVector3(&rel, &m, &rel);" + NL
      + "            nc->Velocity.x = rel.x;" + NL
      + "            nc->Velocity.y = rel.y;",
      "eMulVector3(&rel, &m, &rel);"),
    M("build-hl", "hl = (mx.y - mn.y) * 0.5f;", "hl = mx.y;"),
    M("build-hd", "hd = (mx.x - mn.x) * 0.5f;", "hd = (mx.x + mn.x) * 0.5f;"),
    M("build-cos", "bCosBam((uint16_t)(c->State.Angle - me->State.Angle))",
      "bCosBam((uint16_t)(c->State.Angle + me->State.Angle))"),
    M("build-L", "nc->ApparentHalfSizeL = c2 * hl + s2 * hd;",
      "nc->ApparentHalfSizeL = c2 * hd + s2 * hl;"),
    M("build-D", "nc->ApparentHalfSizeD = c2 * hd + s2 * hl;",
      "nc->ApparentHalfSizeD = c2 * hd + s2 * hd;"),
    M("build-num", "l->NumCarsInArray = n;",
      "l->NumCarsInArray = n < 16 ? n : 15;"),
    M("sort-dir", "if (order[j]->Position.y < order[j + 1]->Position.y)",
      "if (order[j]->Position.y > order[j + 1]->Position.y)"),
    M("sort-ties", "if (order[j]->Position.y < order[j + 1]->Position.y)",
      "if (order[j]->Position.y <= order[j + 1]->Position.y)"),
    M("sort-inner", "for (j = 0; j < n - 1; j++)",
      "for (j = 0; j < n - 2; j++)"),
    M("sort-back", "for (k = 0; k < n; k++)", "for (k = 0; k < n - 1; k++)"),
    M("my-hl", "l->MyHalfSizeL = mx.y;", "l->MyHalfSizeL = mx.x;"),
    M("my-hd", "l->MyHalfSizeD = mx.x;", "l->MyHalfSizeD = -mn.x;"),

    # ClearArray and the lookups.
    M("clear-num", "    l->NumCarsInArray = 0;" + NL
      + "    l->MyHalfSizeL = 0.0f;", "    l->MyHalfSizeL = 0.0f;"),
    M("clear-hl", "    l->NumCarsInArray = 0;" + NL
      + "    l->MyHalfSizeL = 0.0f;", "    l->NumCarsInArray = 0;"),
    M("clear-hd", "l->MyHalfSizeD = 0.0f;" + NL + "    l->NumCarsInArray",
      "l->NumCarsInArray"),
    M("index-bound", "for (i = 0; i < l->NumCarsInArray; i++)",
      "for (i = 0; i < NEARBYCARLIST_MAX; i++)"),
    M("index-none", "            return i;" + NL + "    return -1;",
      "            return i;" + NL + "    return 0;"),
    M("nearby-none", "return i == -1 ? NULL : &l->Array[i];",
      "return i == 0 ? NULL : &l->Array[i];"),
    M("ahead-first", "return i <= 0 ? NULL : &l->Array[i - 1];",
      "return i < 0 ? NULL : &l->Array[i];"),
    M("ahead-which", "return i <= 0 ? NULL : &l->Array[i - 1];",
      "return i <= 0 ? NULL : &l->Array[i];"),

    # DrivingInformation::Clear.
    M("di-list", "    nearbycarlist_clear_array(&d->MyNearbyCarList);" + NL,
      ""),
    M("di-loc", "    drivinglocation_clear(&d->MyDrivingLocation);" + NL, ""),
    M("di-type", "d->MyDrivingChoice.Type = CHOICE_NONE;",
      "d->MyDrivingChoice.Type = CHOICE_DRIVING_LINE_0;"),
    M("di-car", "d->MyDrivingChoice.pCar = NULL;", ""),
    M("di-extra", "d->MyDrivingChoice.UseExtraLateralDistance = 0;",
      "d->MyDrivingChoice.UseExtraLateralDistance = 1;"),

    # CalculateMaxAcceleration.
    M("max-boost", "float v = speed / car->State.BoostFactor;",
      "float v = speed;"),
    M("max-table-arg", "get_acceleration_table(car->pRideInfo->Type)," + NL
      + "                                  v);",
      "get_acceleration_table(car->pRideInfo->Type)," + NL
      + "                                  speed);"),
    M("max-draft", "((1.0f - car->DraftFactor) * ti->Aero.Drag)",
      "((1.0f + car->DraftFactor) * ti->Aero.Drag)"),
    M("max-v2", "* ti->Aero.Drag) * (v * v);", "* ti->Aero.Drag) * v;"),
    M("max-limiter-le", "* NEARBYCAR_MPH_TO_MS <= v &&",
      "* NEARBYCAR_MPH_TO_MS < v &&"),
    M("max-mph", "#define NEARBYCAR_MPH_TO_MS 0.447027266f",
      "#define NEARBYCAR_MPH_TO_MS 0.44704f"),
    M("max-cap-cmp", "&& drag < accel)", "&& drag > accel)"),
    M("max-cap", "        accel = drag;" + NL, "        accel = drag * 0.5f;"
      + NL),
    M("max-drag-mass", "dragAccel = drag / ti->Body.Mass;",
      "dragAccel = drag;"),
    M("max-belt-mode", "if (car->TheMovementMode == BELT_MOVEMENT)",
      "if (car->TheMovementMode != BELT_MOVEMENT)"),
    M("max-belt", "grade = gBeltMoverGravityFn(car->pCarMover);",
      "grade = 0.0f;"),
    M("max-normalise", "grade = -RIGIDBODY_GRAVITY * (x->z * q);",
      "grade = -RIGIDBODY_GRAVITY * x->z;"),
    M("max-norm-z", "(x->x * x->x + x->y * x->y) + x->z * x->z)",
      "(x->x * x->x + x->y * x->y))"),
    M("max-sum", "return (accel - dragAccel) + grade;",
      "return (accel - dragAccel) - grade;"),

    # CanICatchThisCar.
    M("catch-mine", "float mine = car_get_forward_acceleration(car);",
      "float mine = 0.0f;"),
    M("catch-dist", "dist = sqrtf(nc->Position.x * nc->Position.x" + NL
      + "                 + nc->Position.y * nc->Position.y);",
      "dist = sqrtf(nc->Position.y * nc->Position.y);"),
    M("catch-closing", "closing = sqrtf(nc->Velocity.x * nc->Velocity.x" + NL
      + "                    + nc->Velocity.y * nc->Velocity.y);",
      "closing = sqrtf(nc->Velocity.y * nc->Velocity.y);"),
    M("catch-facing", "if (0.0f < car->State.BodyMatrix.v0.x",
      "if (0.0f > car->State.BodyMatrix.v0.x"),
    M("catch-facing-y", "+ car->State.BodyMatrix.v0.y"
      " * o->State.BodyMatrix.v0.y)", "- car->State.BodyMatrix.v0.y"
      " * o->State.BodyMatrix.v0.y)"),
    M("catch-same", "diff = mine - car_get_forward_acceleration(o);",
      "diff = mine;"),
    M("catch-apart", "diff = mine + car_get_forward_acceleration(o);",
      "diff = mine - car_get_forward_acceleration(o);"),
    M("catch-time", "t = AIActionPassMaxTimeAheadToMakeAttempt;",
      "t = 3.0f;"),
    M("catch-half", "(diff * t) * (t * 0.5f);", "(diff * t) * (t * 0.25f);"),
    M("catch-closing-sign", "return dist < closing * t +",
      "return dist < closing * t * 0.5f +"),

    # DoWeCareAboutThisCar.
    M("care-self", "if (nc == NULL || nc->TheCar == l->MyCar)",
      "if (nc == NULL)"),
    M("care-player", "if (nc->TheCar->pPlayer != NULL)",
      "if (nc->TheCar->pPlayer == NULL)"),
    M("care-bias", "bias = -0.5f;", "bias = 0.5f;"),
    M("care-L", "return -((nc->ApparentHalfSizeD + l->MyHalfSizeD) + bias)",
      "return -((nc->ApparentHalfSizeL + l->MyHalfSizeD) + bias)"),
    M("care-my", "return -((nc->ApparentHalfSizeD + l->MyHalfSizeD) + bias)",
      "return -((nc->ApparentHalfSizeD + l->MyHalfSizeL) + bias)"),
    M("care-lt", "           < nc->Position.y;", "           <= nc->Position.y;"),

    # GetCurrentCurvatureOfDrivingLine.
    M("curve-13", "if (r->NumPoints - idx < 13)",
      "if (r->NumPoints - idx < 12)"),
    M("curve-line", "(float)(r->TrackRoutePointTable[idx].DrivingLineOffsets"
      "[line] * 256)", "(float)(r->TrackRoutePointTable[idx]."
      "DrivingLineOffsets[line + 1] * 256)"),
    M("curve-q8", "                  * 256) * (1.0f / 65536.0f);" + NL
      + "    trpoint_get_position2(&r->TrackRoutePointTable[idx + 6]",
      "                  * 128) * (1.0f / 65536.0f);" + NL
      + "    trpoint_get_position2(&r->TrackRoutePointTable[idx + 6]"),
    M("curve-mid", "trpoint_get_position2(&r->TrackRoutePointTable[idx + 6],"
      " &b, 0.0f, lat);", "trpoint_get_position2(&r->TrackRoutePointTable"
      "[idx + 5], &b, 0.0f, lat);"),
    M("curve-chord", "d1.x = a.x - b.x;", "d1.x = b.x - a.x;"),
    M("curve-norm", "    bNormalize2(&d2, &d2);" + NL, ""),
    M("curve-cross", "cz = d1.x * d2.y - d2.x * d1.y;",
      "cz = d1.x * d2.y + d2.x * d1.y;"),
    M("curve-zero", "return 0.0f <= cz ? -len : len;",
      "return 0.0f < cz ? -len : len;"),
    M("curve-sign", "return 0.0f <= cz ? -len : len;",
      "return 0.0f <= cz ? len : -len;"),

    # HighlightDrivingLine.
    M("hl-camera", "if (CameraFollowThisCarInstead != carIndex)",
      "if (CameraFollowThisCarInstead == carIndex)"),
    M("hl-clear", "drivinglocation_is_clear(loc) ? -1 : loc->pRoute->"
      "RouteNumber;", "drivinglocation_is_clear(loc) ? 0 : loc->pRoute->"
      "RouteNumber;"),
    M("hl-line", "HighlightDrivingLineNumber = loc->DrivingLine;",
      "HighlightDrivingLineNumber = -1;"),

    # DrivingLocation.
    D("dl-clear-time", "d->LastRelaxedDrivingLineSwitchTime.PackedTime = 0;",
      "d->LastRelaxedDrivingLineSwitchTime.PackedTime = 1;"),
    D("dl-clear-line", "d->DrivingLine = -1;", "d->DrivingLine = 0;"),
    D("dl-clear-route", "    d->pRoute = NULL;" + NL, ""),
    D("dl-clear-point", "    d->pRoutePoint = NULL;" + NL, ""),
    D("dl-route-relaxed", "drivinglocation_set_driving_line(d, line,"
      " relaxed);", "drivinglocation_set_driving_line(d, line, 0);"),
    D("dl-route-point", "    d->pRoutePoint = p;" + NL
      + "    drivinglocation_set_driving_line",
      "    drivinglocation_set_driving_line"),
    D("dl-point", "    // 0x00239bc8." + NL + "    d->pRoutePoint = p;",
      "    // 0x00239bc8."),
    D("dl-line-byte", "d->DrivingLine = line;",
      "d->DrivingLine = (int8_t)line;"),
    D("dl-line-relaxed", "drivinglocation_set_relaxed_switch(d, relaxed);",
      "drivinglocation_set_relaxed_switch(d, 1);"),
    D("dl-relaxed-one", "relaxed ? (uint32_t)WorldTimer : 0u;",
      "relaxed == 1 ? (uint32_t)WorldTimer : 0u;"),
    D("dl-tick", "#define DRIVINGLOCATION_TICK 0.00025f",
      "#define DRIVINGLOCATION_TICK 0.00024f"),
    D("dl-signed", "int32_t ticks = (int32_t)((uint32_t)WorldTimer",
      "uint32_t ticks = ((uint32_t)WorldTimer"),
    D("dl-clamp", "return 0.0f <= left ? left : 0.0f;",
      "return left;"),
    D("dl-are-we", "return 0.0f < drivinglocation_get_num_seconds_left",
      "return 0.0f <= drivinglocation_get_num_seconds_left"),
]

EQUIVALENT = {}


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
        todo, SOURCES, "nearbycar_test",
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
