#!/usr/bin/env python3
"""Cross-check 3DS Files/source/chopper.c, the police helicopter's object
(12k-2), its chase logic (12k-3a), its plans (12k-3b) and its flying
(12k-4a), against the retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own code: Chopper's constructor (0x001e7a90),
destructor (0x001e7b80), ClearVariables (0x001e7c38), FollowThisCar
(0x001e7f80), AttackCar (0x001e8040), AdjustBombTarget (0x001e8140),
ShiftTarget (0x001e81d8), FindUnobstructedSpot (0x001e82c0),
FindGroundHeight (0x001e8358), PlaceChopperInWorld (0x001e83b0),
RemoveChopperFromWorld (0x001e84a8), ChopperBehindCar (0x001e84f0),
RotateToChopperCoord (0x001e8540) with RotateVector (0x002313e0) and
bSinCos under it, GetMaxDeceleration (0x001e8560), AbortBombingRun
(0x001eadf0), Mute (0x001ead80), UpdateSound (0x001eadb0),
FindChopperPointFromScratch (0x001e8798), FindChopperRoutePoint
(0x001e87e8), CalcMatrix (0x001ea3f8) with bIdentity and eRotateX, Y
and Z under it, and the WorldObject update (0x001ea578); the chase
logic, StartChaseLogic (0x001e8590), EndChaseLogic (0x001e8608),
SetFollowSpeed (0x001e88c0), FindPreviousFork (0x001e88e0),
SwitchToNearbyFork (0x001e8990), TargetChopperPoint (0x001e8a80),
FollowRoute (0x001e8a98), BeginStakeout (0x001e8ce8), HangoutNearHere
(0x001e8e70), BailToPointNearChopper (0x001e8f30),
CalcMinRouteFollowDistance (0x001e8f40), AdjustTargetInBounds
(0x001e8f70), ChopperOnDifferentFork (0x001e90f0), AdjustTargetLocal
(0x001e9368), TestLocation (0x001e98d0) and AdjustByThinkTime
(0x001e9940); the plans, CleverPursuitPlan (0x001e9150), BombRunLogic
(0x001e9398) and HighLevelPlanning (0x001e9648) with bScaleAdd
(0x002589d8) under it; the flying, SetXAccel (0x001e9950), SetYAccel
(0x001e9a20), SetRotateTarget (0x001e9ae8), HoverTime (0x001e9b30),
CheckMomentumWithinBounds (0x001e9c68), Think (0x001e9d48),
CalcChopperRotation (0x001e9e40) and SubtractFromYaw (0x001e9e80), with
bATan (0x0025a890) and MakeRelativeAngle (0x00231478) under them;
bStringHash and the bombing runs' table (0x0031a7c8) as shipped. The
harness (tools/src/chopper_test.c) runs chopper.c, coputil.c, emath.c,
bmath.c, bmatrix.c and bvector.c and prints the same lines.

**The stubs**, logged and answered by the same rule on both sides: the
TopologyCoordinate's constructor, destructor, SetInterestBBox,
ClearInterestBBox and GetElevation; the TrackPathCoordinate's
constructor, ResetPosition and the manager's CompareDistances; bOMalloc,
__builtin_delete, and WorldObject's constructor and destructor;
afxGetEmitters and afxDeleteEmitters; HasSignposts; Car::GetRoute and
GetRoutePoint; GuessTargetDestinations, GetNextRoutePoint and
GetNearestRoutePoint; FindNearbySignpost and FindPointsToTarget;
HeliSheet::FindZValue, answered per point or by boxes of the plane;
TrackRoute::FindClosestPoint, FindClosestPointAhead and
GetRelativePoint; TrackRoutePoint::GetSignpost and GetPosition;
Signpost::GetNewRoute and GetNewRoutePoint; Chopper::FireSalvo (12k-6's),
which logs the run's type and counts; and sound::CreateChopperSound,
whose sound's table is the checker's own, with a this-adjustment of 8.
The routes' points are inside their tables, so BeginStakeout's indexes
are the image's own.

**The port's divergences**, which the model is made to share:
  - With no sound (gCreateChopperSoundFn NULL) the port skips every call
    through it. Retail always builds one and calls it unguarded, so the
    model hands the calls to a silent sound of its own.
  - FindUnobstructedSpot's flags word starts at 0 in the port. Retail's
    first FindZValue may miss and leave it as the stack had it, so the
    model zeroes that word on entry.
  - HangoutNearHere stops after a miss once both of its offsets are
    below the least normal float, or NaN. The EE has flushed them to
    zero by then and the image tries the point itself for ever; mipsemu
    is IEEE and would shrink them to the least denormal and stay. A
    hook after the image's FindZValue (0x001e8f04) ends the model's loop
    by the same rule.
  - BombRunLogic skips the car's progress when its point or the last one
    is NULL, where the image reads address 0 for the position. A hook at
    the image's compare of the two (0x001e93c8) makes them equal then.

**Compared** are the stubs' logs, each method's result, and after each
call every field of the helicopter at retail's offsets, the padding
included.

**The script** builds helicopters with each demo flag and the egg on and
off, with and without a sound, and frees them with and without delete;
clears one after scrambling it; follows cars from every plan with and
without the egg's word, a sheet and signposts; starts bombing runs of
each type from each plan, at speeds and distances either side of the
run's lead, ahead of the car and behind it; shifts targets past points
the sheet does not cover; walks to open ground over runs of covered
polygons, misses included; places, removes, turns and rebuilds the
helicopter's matrix at angles round the circle and past it; and runs the
chase logic over four routes with signs of every kind (always-take,
backwards, no-stakeout), boxes of sheet with gaps between them, forks
behind the helicopter, lists of points ahead that do and do not reach
the target, and targets near, far, off the sheet and NaN; and the plans
from every plan, with the timeout either side of its tick, the car's
spot on and off the sheet over each flag, the car's progress forward,
back, onto another route and to and from NULL, the helicopter either
side of the road's edges and the target's reach, each bomb type to its
last salvo with the sheet and the ground height either side, and the
stakeout either side of its give-up and reach distances; and the flying,
with the accelerations, rolls, turn rates and angles either side of each
bound and wrap, NaN among them, from every plan; hovering either side of
its speed, reach and acceleration, at headings round the circle; every
mix of the three momentum probes on and off the sheet; and Think from
each plan's ending, over targets round the helicopter at speeds either
side of turning on the spot.

    python tools/chopper_check.py
    python tools/chopper_check.py --mutate [--only a,b]
    python tools/chopper_check.py --dump out/chopper
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
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/chopper_test.c"
CHOP = "3DS Files/source/chopper.c"
COPUTIL = "3DS Files/source/coputil.c"
SOURCES = [HARNESS, CHOP, COPUTIL, "3DS Files/source/emath.c",
           "3DS Files/source/bmath.c", "3DS Files/source/bmathtab.c",
           "3DS Files/source/bmatrix.c", "3DS Files/source/bvector.c",
           "3DS Files/source/vtable.c"]
HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = retail_model.RETAIL_GP
G_SHEET = GP - 17128                    # TheHeliSheet
G_WORLD = GP - 22120                    # pCurrentWorld
G_WOP = GP - 18112                      # WorldObjectSlotPool
RP = 0x0031a898                         # TheRaceParameters
EGGS = 0x0031d7f4                       # the egg table's pointer
TPM = 0x0031bc38                        # TheTrackPathManager

F_CTOR = 0x001e7a90
F_DTOR = 0x001e7b80
F_CLEAR = 0x001e7c38
F_FOLLOW = 0x001e7f80
F_ATTACK = 0x001e8040
F_ADJUST = 0x001e8140
F_SHIFT = 0x001e81d8
F_SPOT = 0x001e82c0
F_GROUND = 0x001e8358
F_PLACE = 0x001e83b0
F_REMOVE = 0x001e84a8
F_BEHIND = 0x001e84f0
F_ROTATE = 0x001e8540
F_DECEL = 0x001e8560
F_SCRATCH = 0x001e8798
F_ROUTEPT = 0x001e87e8
F_MATRIX = 0x001ea3f8
F_WOBJ = 0x001ea578
F_MUTE = 0x001ead80
F_USOUND = 0x001eadb0
F_ABORT = 0x001eadf0
# 12k-3a's chase logic.
F_START = 0x001e8590
F_ENDCHASE = 0x001e8608
F_FSPEED = 0x001e88c0
F_PREVFORK = 0x001e88e0
F_SWITCH = 0x001e8990
F_TCP = 0x001e8a80
F_FOLLOWRT = 0x001e8a98
F_STAKEOUT = 0x001e8ce8
F_HANGOUT = 0x001e8e70
F_BAIL = 0x001e8f30
F_MINFOLLOW = 0x001e8f40
F_INBOUNDS = 0x001e8f70
F_DIFFFORK = 0x001e90f0
F_LOCAL = 0x001e9368
F_TESTLOC = 0x001e98d0
F_BYTHINK = 0x001e9940
HANGOUT_MISS = 0x001e8f04               # its `beql` after FindZValue
F_CLEVER = 0x001e9150
F_BOMBRUN = 0x001e9398
F_HLP = 0x001e9648
BOMB_NULL = 0x001e93c8                  # its `beq` of the car's points
F_XACCEL = 0x001e9950
F_YACCEL = 0x001e9a20
F_ROTTGT = 0x001e9ae8
F_HOVER = 0x001e9b30
F_MOMENTUM = 0x001e9c68
F_THINK = 0x001e9d48
F_CALCROT = 0x001e9e40
F_SUBYAW = 0x001e9e80
F_RELANGLE = 0x00231478

S_TOPO_CTOR = 0x00151c28
S_TOPO_DTOR = 0x00151c70
S_BBOX = 0x00151d30
S_CLEARBB = 0x00151cd0
S_ELEV = 0x00152070
S_TP_CTOR = 0x002086b8
S_TP_RESET = 0x00208838
S_CMP = 0x00208598
S_OMALLOC = 0x00257c80
S_DELETE = 0x00114e98
S_WOCTOR = 0x001cd760
S_WODTOR = 0x001cd828
S_AFXGET = 0x001272e0
S_AFXDEL = 0x00127368
S_TLIST_DTOR = 0x00124bf0
S_HASSIGN = 0x001c2fe8
S_GETROUTE = 0x001332a8
S_GETPOINT = 0x001332d8
S_GUESS = 0x001cbb70
S_NEXT = 0x001cb960
S_ZVAL = 0x001ebad8
S_NEAREST = 0x001cb7a0
S_CLOSEST = 0x001c1b48
S_GETSIGN = 0x001c14f8
S_NEWROUTE = 0x001c0ff8
S_NEWPOINT = 0x001c1020
S_RELPT = 0x001c1910
S_NEARBY = 0x001cc838
S_PTT = 0x001cc5d0
S_GETPOS = 0x001c1390
S_AHEAD = 0x001c1d30
S_FIRE = 0x001ea8c0
S_SNDNEW = 0x00215098

CHOPPER_SIZE = 976
CAR_SIZE = 2304
WORLD_SIZE = 5936
NCARS, NROUTES, NPOINTS, PER_ROUTE = 3, 4, 24, 6
POINT_TABLE = 1064                      # TrackRoutePointTable
POINT_SIZE = 112
ROUTE_SIZE = POINT_TABLE + POINT_SIZE * PER_ROUTE
SND_DELTA = 8

NO_HELISHEET = 0x4000
FLT_MIN = 2.0 ** -126


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def bitsf(u):
    return struct.unpack("<f", struct.pack("<I", u & M32))[0]


def fx(f):
    return "%08x" % fbits(f)


# ================================================================ the model

class Model:
    def __init__(self):
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True,
                                            eesqrt=True)
        self.lines = []
        self.names = {}
        self.H = None
        self.cars = [self.block(CAR_SIZE, "C%d" % i) for i in range(NCARS)]
        self.world = self.block(WORLD_SIZE, "WORLD")
        e.put32(self.world + 44, self.cars[0])
        e.put32(G_WORLD, self.world)
        # The points in their routes' tables, as the harness has them.
        self.routes = [self.block(ROUTE_SIZE, "R%d" % i)
                       for i in range(NROUTES)]
        self.points = []
        for i in range(NPOINTS):
            p = (self.routes[i // PER_ROUTE] + POINT_TABLE
                 + POINT_SIZE * (i % PER_ROUTE))
            self.points.append(p)
            self.names[p] = "P%d" % i
        self.signs = [self.block(16, "S%d" % i) for i in range(NPOINTS)]
        self.T = self.block(16, "T")
        self.sheet = self.block(536, "SHEET")
        self.wo = self.block(96, "WO")
        self.snd = self.block(32, "SND")
        self.pool = self.block(16, "WOP")
        e.put32(G_WOP, self.pool)
        self.names[TPM] = "TPM"
        self.eggs = self.block(400, None)
        e.put32(EGGS, self.eggs)
        for a in (RP + 24, RP + 28):
            e.put32(a, 0)
        e.put32(G_SHEET, 0)
        self.sound_on = 1
        self.q = dict(signs=1, elev=0.0, terrain=0, cmp=0.0, guess=[],
                      near=0, near_info=(0, 0), newroute=0)
        self.car_route = [(0, 0)] * NCARS
        self.zhit = [0] * NPOINTS
        self.zflags = [0] * NPOINTS
        self.closest = [0] * NROUTES
        self.ahead = [0] * NROUTES
        self.boxes = []                 # (x0, y0, x1, y1, z, flags)
        self.end = [0] * NPOINTS
        self.signto = [None] * NPOINTS
        self.nearby = [(0, 0, 0)] * NPOINTS
        self.ptt = [[] for _ in range(NPOINTS)]
        self.loud = self.table(True)
        self.silent_vt = self.table(False)
        self.silent = self.block(32, None)
        e.put32(self.silent + 28, self.silent_vt)
        self.install()

    def block(self, size, name):
        a = self.e.alloc(size, 16)
        self.e.write(a, bytes(size))
        if name:
            self.names[a] = name
        return a

    # The sound's table: five entries of {delta, index, fn}, the fns stub
    # addresses of the checker's own. The silent one logs nothing.
    def table(self, loud):
        e = self.e
        vt = self.block(40, None)
        kinds = ("dtor", "activate", "update", "mute")
        for i, k in enumerate(kinds):
            fn = self.block(16, None)
            e.write(vt + 8 * (i + 1), struct.pack("<hhI", SND_DELTA, 0, fn))
            e.stub(fn, self.snd_stub(k) if loud else (lambda e_: None))
        return vt

    def snd_stub(self, kind):
        def fn(e):
            this = "SND%+d" % (s32(e.reg[4]) - self.snd)
            if kind == "update":
                self.log("snd_update %s %s %u %s" % (
                    this, fx(e.f(12)), e.reg[5] & 0xffff, fx(e.f(13))))
            else:
                self.log("snd_%s %s %d" % (kind, this, s32(e.reg[5])))
        return fn

    def log(self, s):
        self.lines.append("  " + s)

    def name(self, a):
        a &= M32
        if a == 0:
            return "NULL"
        if self.H is not None:
            rel = {0: "H", 8: "H.topo", 712: "H.dust", 752: "H.tp",
                   832: "H.pos"}
            if a - self.H in rel:
                return rel[a - self.H]
        return self.names.get(a, "?")

    def addr(self, n):
        if n == "NULL":
            return 0
        i = int(n[1:])
        return {"C": self.cars, "R": self.routes, "P": self.points}[n[0]][i]

    def pidx(self, a):
        return self.points.index(a & M32)

    def find_point(self, a):
        a &= M32
        return self.points.index(a) if a in self.points else -1

    def f32(self, a):
        return bitsf(self.e.u32(a))

    # ---- the stubs --------------------------------------------------------

    def install(self):
        e = self.e
        r = e.reg
        L = self.log
        n = self.name

        def topo_ctor(e):
            L("topo_init %s" % n(r[4]))

        def topo_dtor(e):
            L("topo_dtor %s" % n(r[4]))

        def bbox(e):
            p = r[5] & M32
            L("topo_bbox %s %s %s %s %s %s" % (
                n(r[4]), n(p), fx(self.f32(p)), fx(self.f32(p + 4)),
                fx(e.f(12)), n(r[6])))

        def clearbb(e):
            L("topo_clear %s" % n(r[4]))

        def elev(e):
            p = r[5] & M32
            L("topo_elev %s %s %s %s %s %s %s" % (
                n(r[4]), fx(self.f32(p)), fx(self.f32(p + 4)),
                fx(self.f32(p + 8)), "T" if r[6] & M32 else "NULL",
                n(r[7]), n(r[8])))
            if r[6] & M32:
                e.put32(r[6] & M32, self.q["terrain"])
            e.set_f(0, self.q["elev"])

        def tp_ctor(e):
            a = r[4] & M32
            L("tp_init %s" % n(a))
            e.write(a, bytes(40))
            e.put32(a + 24, fbits(1.0))
            return a

        def tp_reset(e):
            a, p = r[4] & M32, r[5] & M32
            L("tp_reset %s %s %s %s" % (n(a), n(p), fx(self.f32(p)),
                                        fx(self.f32(p + 4))))
            e.put32(a + 8, 0)

        def cmp(e):
            L("tp_cmp %s %s %s" % (n(r[4]), fx(e.f(12)), fx(e.f(13))))
            e.set_f(0, self.q["cmp"])

        def omalloc(e):
            L("omalloc %s" % n(r[4]))
            e.write(self.wo, b"\xcd" * 96)
            return self.wo

        def delete(e):
            L("free %s" % n(r[4]))

        def woctor(e):
            L("wo_ctor %s %08x %s %d" % (n(r[4]), r[5] & M32, n(r[6]),
                                         s32(r[7])))
            return r[4] & M32

        def wodtor(e):
            L("wo_dtor %s %d" % (n(r[4]), s32(r[5])))

        def afxget(e):
            L("afx_get %s %08x" % (n(r[4]), r[5] & M32))

        def afxdel(e):
            L("afx_del %s" % n(r[4]))

        def hassign(e):
            L("has_signposts")
            return self.q["signs"]

        def getroute(e):
            c = self.cars.index(r[4] & M32)
            L("get_route %s %d" % (n(r[4]), s32(r[5])))
            return self.car_route[c][0]

        def getpoint(e):
            c = self.cars.index(r[4] & M32)
            L("get_point %s %d" % (n(r[4]), s32(r[5])))
            return self.car_route[c][1]

        def guess(e):
            out = r[4] & M32
            L("guess %u %s %s %s %d" % (r[5] & M32, n(r[6]), n(r[7]),
                                        fx(e.f(12)), s32(r[8])))
            for i, (ro, po) in enumerate(self.q["guess"]):
                e.put32(out + 8 * i, ro)
                e.put32(out + 8 * i + 4, po)
            return len(self.q["guess"])

        def nxt(e):
            info = r[4] & M32
            ro, po = e.u32(info), e.u32(info + 4)
            L("next %s %s" % (n(ro), n(po)))
            i = self.pidx(po)
            if self.end[i] or i + 1 >= NPOINTS:
                e.put32(info + 4, 0)
                return
            i += 1
            e.put32(info, self.routes[i // PER_ROUTE])
            e.put32(info + 4, self.points[i])

        # A point's polygon is the script's, per point; anywhere else, the
        # first box holding the spot.
        def zval(e):
            p = r[5] & M32
            x, y = self.f32(p), self.f32(p + 4)
            i = self.find_point(p)
            L("zval %s %s %s %s %08x %08x" % (
                n(r[4]), n(p), "Z" if r[6] & M32 else "NULL",
                "F" if r[7] & M32 else "NULL", e.u32(p), e.u32(p + 4)))
            if i >= 0:
                if not self.zhit[i]:
                    return 0
                z, fl = 1.0, self.zflags[i]
            else:
                for x0, y0, x1, y1, z, fl in self.boxes:
                    if x0 <= x <= x1 and y0 <= y <= y1:
                        break
                else:
                    return 0
            if r[6] & M32:
                e.put32(r[6] & M32, fbits(z))
            if r[7] & M32:
                e.put32(r[7] & M32, fl)
            return 1

        def nearest(e):
            p = r[5] & M32
            L("nearest %s %s %s %d %d %s" % (
                n(p), fx(self.f32(p)), fx(self.f32(p + 4)), s32(r[6]),
                s32(r[7]), fx(e.f(12))))
            if not self.q["near"]:
                return 0
            ro, po = self.q["near_info"]
            e.put32(r[4] & M32, ro)
            e.put32((r[4] & M32) + 4, po)
            return 1

        def closest(e):
            i = self.routes.index(r[4] & M32)
            L("closest %s %s %s %d %s" % (n(r[4]), n(r[5]), fx(e.f(12)),
                                          s32(r[6]), fx(e.f(13))))
            return self.closest[i]

        def ahead(e):
            i = self.routes.index(r[4] & M32)
            p = r[5] & M32
            L("ahead %s %s %08x %08x %s" % (n(r[4]), n(p), e.u32(p),
                                            e.u32(p + 4), n(r[6])))
            return self.ahead[i]

        # 12k-6's; here, what the run stands at when it fires.
        def fire(e):
            h = r[4] & M32
            L("fire_salvo %s %d %d %d" % (n(h), s32(e.u32(h + 804)),
                                          s32(e.u32(h + 808)),
                                          s32(e.u32(h + 828))))

        def getsign(e):
            L("get_sign %s" % n(r[4]))
            return self.signs[self.pidx(r[4])]

        def newroute(e):
            i = self.signs.index(r[4] & M32)
            L("new_route %s" % n(r[4]))
            if self.signto[i] is not None:
                return self.signto[i][0]
            return self.q["newroute"]

        def newpoint(e):
            i = self.signs.index(r[4] & M32)
            L("new_point %s" % n(r[4]))
            if self.signto[i] is not None:
                return self.signto[i][1]
            return 0

        # The neighbour within the point's own route, or NULL.
        def relpt(e):
            L("relpt %s %s %d" % (n(r[4]), n(r[5]), s32(r[6])))
            i = self.find_point(r[5])
            if i < 0:
                return 0
            j = i + 1 if s32(r[6]) else i - 1
            if j < 0 or j // PER_ROUTE != i // PER_ROUTE:
                return 0
            return self.points[j]

        def nearby(e):
            info = r[4] & M32
            ro, po = e.u32(info), e.u32(info + 4)
            L("nearby %s %s %d" % (n(ro), n(po), s32(r[5])))
            i = self.find_point(po)
            if i < 0 or self.nearby[i][0] == 0:
                e.put32(info + 4, 0)
                return 0
            k, ro, po = self.nearby[i]
            e.put32(info, ro)
            e.put32(info + 4, po)
            return k

        def ptt(e):
            st, tg, out = r[4] & M32, r[5] & M32, r[6] & M32
            count = r[7] & M32
            L("ptt %s %s %s %s %u %d %d" % (
                n(e.u32(st)), n(e.u32(st + 4)), n(e.u32(tg)),
                n(e.u32(tg + 4)), count, s32(r[8]), s32(r[9])))
            i = self.find_point(e.u32(st + 4))
            if i < 0:
                return 0
            got = self.ptt[i][:count]
            for k, (ro, po) in enumerate(got):
                e.put32(out + 8 * k, ro)
                e.put32(out + 8 * k + 4, po)
            return len(got)

        # The spot is (d, l) itself, which the boxes then judge.
        def getpos(e):
            o = r[5] & M32
            d, l = e.fpr[12] & M32, e.fpr[13] & M32
            L("getpos %s %s %08x %08x" % (n(r[4]), n(o), d, l))
            e.put32(o, d)
            e.put32(o + 4, l)

        def sndnew(e):
            if not self.sound_on:
                return 0
            L("snd_new %s" % n(r[4]))
            e.write(self.snd, bytes(32))
            e.put32(self.snd + 28, self.loud)
            return self.snd

        def nothing(e):
            return None

        # The flags word FindZValue writes: 0 to start with, as the port's.
        def spot_entry(e):
            e.put32((r[29] - 80 + 16) & M32, 0)

        # HangoutNearHere off the sheet with both below the least normal
        # float, or NaN: the port stops, where the EE has flushed them to
        # zero and tries the point for ever.
        def hangout_miss(e):
            if ((r[2] & M32) == 0 and not abs(e.f(20)) >= FLT_MIN
                    and not abs(e.f(21)) >= FLT_MIN):
                r[2] = 1

        # BombRunLogic with the car's point or the last one NULL: the port
        # skips the progress, where the image reads address 0.
        def bomb_null(e):
            if (r[17] & M32) == 0 or (r[2] & M32) == 0:
                r[17] = r[2]

        for a, f in ((S_TOPO_CTOR, topo_ctor), (S_TOPO_DTOR, topo_dtor),
                     (S_BBOX, bbox), (S_CLEARBB, clearbb), (S_ELEV, elev),
                     (S_TP_CTOR, tp_ctor), (S_TP_RESET, tp_reset),
                     (S_CMP, cmp), (S_OMALLOC, omalloc), (S_DELETE, delete),
                     (S_WOCTOR, woctor), (S_WODTOR, wodtor),
                     (S_AFXGET, afxget), (S_AFXDEL, afxdel),
                     (S_TLIST_DTOR, nothing), (S_HASSIGN, hassign),
                     (S_GETROUTE, getroute), (S_GETPOINT, getpoint),
                     (S_GUESS, guess), (S_NEXT, nxt), (S_ZVAL, zval),
                     (S_NEAREST, nearest), (S_CLOSEST, closest),
                     (S_GETSIGN, getsign), (S_NEWROUTE, newroute),
                     (S_NEWPOINT, newpoint), (S_RELPT, relpt),
                     (S_NEARBY, nearby), (S_PTT, ptt), (S_GETPOS, getpos),
                     (S_AHEAD, ahead), (S_FIRE, fire),
                     (S_SNDNEW, sndnew)):
            e.stub(a, f)
        e.hook(F_SPOT, spot_entry)
        e.hook(HANGOUT_MISS, hangout_miss)
        e.hook(BOMB_NULL, bomb_null)

    # ---- the dump ---------------------------------------------------------

    def dump(self):
        e, h, n = self.e, self.H, self.name
        u = lambda o: e.u32(h + o)                     # noqa: E731
        i = lambda o: s32(e.u32(h + o))                # noqa: E731
        x = lambda o: "%08x" % e.u32(h + o)            # noqa: E731
        out = self.lines
        out.append("dump plan %d mm %d think %s car %s" % (
            i(728), i(732), x(720), n(u(724))))
        out.append("  route %s %s target %s %s old %s %s td %s" % (
            n(u(736)), n(u(740)), n(u(744)), n(u(748)), n(u(796)),
            n(u(800)), x(792)))
        out.append("  bomb %d %d %s %d timeout %s stuck %s total %d" % (
            i(804), i(808), x(812), i(816), x(820), x(824), i(828)))
        out.append("  pos %s %s %s %s" % (x(832), x(836), x(840), x(844)))
        out.append("  mat " + " ".join(x(848 + 4 * k) for k in range(16)))
        out.append("  speed %s acc %s %s roll %s %s yaw %s pitch %s %s" % (
            x(912), x(916), x(920), x(924), x(928), x(932), x(936),
            x(940)))
        out.append("  rot %s zv %s gz %s dust %d n960 %d" % (
            x(944), x(948), x(952), i(956), i(960)))
        out.append("  tp %s %s %s %s %s %s %s %s %s %s" % (
            x(752), x(756), n(u(760)), x(764), x(768), x(772), x(776),
            x(780), n(u(784)), x(788)))
        out.append("  snd %s wo %s dust %s %s pad %s" % (
            n(u(0)), n(u(4)), n(u(712)), n(u(716)),
            " ".join("%02x" % b for b in e.read(h + 964, 12))))
        out.append("  tgt %08x %08x %08x" % tuple(
            e.u32(self.T + 4 * k) for k in range(3)))

    # ---- the ops ----------------------------------------------------------

    def with_sound(self, fn):
        """Retail calls the sound unguarded; with none, the port skips the
        call, which the model shares by lending it a silent one."""
        e, h = self.e, self.H
        if e.u32(h) != 0:
            return fn()
        e.put32(h, self.silent)
        try:
            return fn()
        finally:
            e.put32(h, 0)

    def run(self, t):
        e = self.e
        op = t[0]
        self.lines.append(op)
        if op == "q":
            self.answer(t)
            return
        if op == "car":
            c = self.cars[int(t[1])]
            for k, o in enumerate((96, 100, 104)):
                e.put32(c + o, int(t[2 + k], 16))
            struct.pack_into("<H", e.mem, c + 932, int(t[5]))
            e.put32(c + 964, int(t[6], 16))
            e.put32(c + 2036, int(t[7], 16))
            return
        if op == "point":
            p = self.points[int(t[1])]
            e.put32(p, int(t[2], 16))
            e.put32(p + 4, int(t[3], 16))
            e.put32(p + 20, int(t[4], 16))
            e.put32(p + 44, int(t[5], 16))
            e.put32(p + 12, int(t[6], 16))
            e.put32(p + 16, int(t[7], 16))
            return
        if op == "carvel":
            c = self.cars[int(t[1])]
            for k in range(3):
                e.put32(c + 112 + 4 * k, int(t[2 + k], 16))
            return
        if op == "width":
            p = self.points[int(t[1])]
            e.put32(p + 24, int(t[2], 16))
            e.put32(p + 28, int(t[3], 16))
            return
        if op == "sign":
            e.put32(self.signs[int(t[1])], int(t[2], 16))
            return
        if op == "tgt":
            for k in range(3):
                e.put32(self.T + 4 * k, int(t[1 + k], 16))
            return
        if op == "relangle":
            e.set_f(12, bitsf(int(t[1], 16)))
            e.call(F_RELANGLE)
            self.log("ret %08x" % (e.fpr[0] & M32))
            return
        h = self.H
        T = self.T
        if op == "new":
            h = self.H = e.alloc(CHOPPER_SIZE, 16)
            e.write(h, b"\xcd" * CHOPPER_SIZE)
            self.log("ret %s" % self.name(e.call(F_CTOR, h)))
        elif op == "del":
            e.call(F_DTOR, h, int(t[1]))
            return
        elif op == "clear":
            e.call(F_CLEAR, h)
        elif op == "follow":
            self.log("ret %d" % e.call(F_FOLLOW, h, self.addr(t[1])))
        elif op == "attack":
            self.log("ret %d" % e.call(F_ATTACK, h, int(t[1])))
        elif op == "adjust":
            e.call(F_ADJUST, h)
        elif op == "shift":
            e.set_f(12, bitsf(int(t[1], 16)))
            e.call(F_SHIFT, h)
        elif op == "spot":
            e.call(F_SPOT, h)
        elif op == "ground":
            self.log("ret %d" % e.call(F_GROUND, h))
        elif op == "place":
            v = self.vec(t[1], t[2])
            e.set_f(12, bitsf(int(t[3], 16)))
            self.with_sound(lambda: e.call(F_PLACE, h, v))
        elif op == "remove":
            self.with_sound(lambda: e.call(F_REMOVE, h))
            self.log("wo %d" % s32(e.u32(self.wo + 12)))
        elif op == "behind":
            self.log("ret %d" % e.call(F_BEHIND, h))
        elif op == "rotate":
            v = self.vec(t[1], t[2])
            o = self.vec("0", "0")
            e.call(F_ROTATE, h, o, v)
            self.log("out %08x %08x" % (e.u32(o), e.u32(o + 4)))
            e.call(F_ROTATE, h, v, v)
            self.log("same %08x %08x" % (e.u32(v), e.u32(v + 4)))
        elif op == "maxdecel":
            e.call(F_DECEL, h)
            self.log("ret %s" % fx(e.f(0)))
        elif op == "abort":
            e.call(F_ABORT, h)
        elif op == "mute":
            self.with_sound(lambda: e.call(F_MUTE, h, int(t[1])))
        elif op == "usound":
            self.with_sound(lambda: e.call(F_USOUND, h))
        elif op == "scratch":
            e.call(F_SCRATCH, h)
        elif op == "routepoint":
            e.call(F_ROUTEPT, h)
        elif op == "matrix":
            e.call(F_MATRIX, h)
        elif op == "wobj":
            e.call(F_WOBJ, h)
            self.log("wo %d " % s32(e.u32(self.wo + 12)) + " ".join(
                "%08x" % e.u32(self.wo + 32 + 4 * k) for k in range(16)))
        elif op == "set":
            self.set_field(t)
        elif op == "start":
            e.set_f(12, bitsf(int(t[3], 16)))
            self.log("ret %d" % self.with_sound(lambda: e.call(
                F_START, h, T, int(t[1]), int(t[2], 16))))
        elif op == "endchase":
            self.log("ret %d" % self.with_sound(
                lambda: e.call(F_ENDCHASE, h, T)))
        elif op == "fspeed":
            e.call(F_FSPEED, h, T)
        elif op == "prevfork":
            info = self.info(t[1], t[2])
            ret = e.call(F_PREVFORK, h, info, int(t[3]))
            self.log("ret %d %s %s" % (ret, self.name(e.u32(info)),
                                       self.name(e.u32(info + 4))))
        elif op == "switchfork":
            inf = self.info(t[1], t[2])
            out = self.info("NULL", "NULL")
            e.write(out, b"\xcd" * 8)
            e.set_f(12, bitsf(int(t[4], 16)))
            ret = e.call(F_SWITCH, h, out, inf, int(t[3]))
            self.log("ret %d %s %s" % (ret, self.name(e.u32(out)),
                                       self.name(e.u32(out + 4))))
        elif op == "tcp":
            e.call(F_TCP, h, T)
        elif op == "followroute":
            e.call(F_FOLLOWRT, h, T, self.addr(t[1]), self.addr(t[2]),
                   int(t[3]))
        elif op == "stakeout":
            e.call(F_STAKEOUT, h, T, self.addr(t[1]), self.addr(t[2]))
        elif op == "hangout":
            e.call(F_HANGOUT, h, T, self.addr(t[1]), self.addr(t[2]))
        elif op == "bail":
            e.call(F_BAIL, h, T)
        elif op == "minfollow":
            e.call(F_MINFOLLOW, h, T)
            self.log("ret %08x" % (e.fpr[0] & M32))
        elif op == "inbounds":
            self.log("ret %d" % e.call(F_INBOUNDS, h, T))
        elif op == "difffork":
            self.log("ret %d" % e.call(F_DIFFFORK, h, self.addr(t[1]),
                                       self.addr(t[2])))
        elif op == "local":
            e.call(F_LOCAL, h, T)
        elif op == "testloc":
            e.set_f(12, bitsf(int(t[1], 16)))
            e.set_f(13, bitsf(int(t[2], 16)))
            self.log("ret %d" % e.call(F_TESTLOC, h))
        elif op == "bythink":
            e.set_f(12, bitsf(int(t[1], 16)))
            e.call(F_BYTHINK, h)
            self.log("ret %08x" % (e.fpr[0] & M32))
        elif op == "clever":
            e.call(F_CLEVER, h, T, int(t[1]), int(t[2], 16))
        elif op == "bombrun":
            e.call(F_BOMBRUN, h, T)
        elif op == "hlp":
            self.log("ret %d" % self.with_sound(
                lambda: e.call(F_HLP, h, T)))
        elif op == "xaccel":
            e.call(F_XACCEL, h, T)
        elif op == "yaccel":
            e.set_f(12, bitsf(int(t[1], 16)))
            e.call(F_YACCEL, h, T)
        elif op == "rottgt":
            e.set_f(12, bitsf(int(t[1], 16)))
            e.set_f(13, bitsf(int(t[2], 16)))
            e.call(F_ROTTGT, h)
        elif op == "hover":
            self.log("ret %d" % e.call(F_HOVER, h, T))
        elif op == "momentum":
            e.call(F_MOMENTUM, h)
        elif op == "think":
            self.with_sound(lambda: e.call(F_THINK, h))
        elif op == "calcrot":
            v = self.vec(t[2], t[3])
            e.set_f(12, bitsf(int(t[1], 16)))
            e.call(F_CALCROT, h, v, v + 4)
            self.log("out %08x %08x" % (e.u32(v), e.u32(v + 4)))
            s = self.vec(t[3], "0")
            e.set_f(12, bitsf(int(t[1], 16)))
            e.call(F_CALCROT, h, s, s)
            self.log("same %08x" % e.u32(s))
        elif op == "subyaw":
            e.set_f(12, bitsf(int(t[1], 16)))
            e.call(F_SUBYAW, h)
        else:
            raise SystemExit("no op %s" % op)
        self.dump()

    def info(self, ro, po):
        a = self.e.alloc(8, 8)
        self.e.put32(a, self.addr(ro))
        self.e.put32(a + 4, self.addr(po))
        return a

    def vec(self, xs, ys):
        v = self.e.alloc(16, 16)
        self.e.put32(v, int(xs, 16))
        self.e.put32(v + 4, int(ys, 16))
        return v

    def set_field(self, t):
        e, h = self.e, self.H
        f = t[1]
        word = {"plan": 728, "n960": 960, "bomb": 804, "mm": 732,
                "salvos": 808, "launcher": 816, "total": 828, "dust": 956}
        flt = {"yaw": 932, "roll": 924, "pitch": 936, "gz": 952,
               "td": 792, "tpd": 772, "think": 720, "nsalvo": 812,
               "timeout": 820, "stuck": 824, "speed": 912, "droll": 928,
               "dpitch": 940, "rot": 944, "zv": 948}
        if f in word:
            e.put32(h + word[f], int(t[2]))
        elif f in flt:
            e.put32(h + flt[f], int(t[2], 16))
        elif f == "acc":
            e.put32(h + 916, int(t[2], 16))
            e.put32(h + 920, int(t[3], 16))
        elif f == "car":
            e.put32(h + 724, self.addr(t[2]))
        elif f == "pos":
            for k in range(3):
                e.put32(h + 832 + 4 * k, int(t[2 + k], 16))
        elif f == "chop":
            e.put32(h + 736, self.addr(t[2]))
            e.put32(h + 740, self.addr(t[3]))
        elif f == "target":
            e.put32(h + 744, self.addr(t[2]))
            e.put32(h + 748, self.addr(t[3]))
        elif f == "old":
            e.put32(h + 796, self.addr(t[2]))
            e.put32(h + 800, self.addr(t[3]))
        else:
            raise SystemExit("no field %s" % f)

    def answer(self, t):
        e, q = self.e, self.q
        k = t[1]
        if k == "egg":
            e.put32(self.eggs + 328, int(t[2]))
        elif k == "demo":
            e.put32(RP + 24, int(t[2]))
            e.put32(RP + 28, int(t[3]))
        elif k == "sheet":
            e.put32(G_SHEET, self.sheet if int(t[2]) else 0)
        elif k == "signs":
            q["signs"] = int(t[2])
        elif k == "elev":
            q["elev"] = bitsf(int(t[2], 16))
            q["terrain"] = int(t[3])
        elif k == "cmp":
            q["cmp"] = bitsf(int(t[2], 16))
        elif k == "carroute":
            self.car_route[int(t[2])] = (self.addr(t[3]), self.addr(t[4]))
        elif k == "guess":
            q["guess"] = [(self.addr(t[i]), self.addr(t[i + 1]))
                          for i in range(2, len(t) - 1, 2)]
        elif k == "zval":
            self.zhit[int(t[2])] = int(t[3])
            self.zflags[int(t[2])] = int(t[4], 16)
        elif k == "near":
            q["near"] = int(t[2])
            q["near_info"] = (self.addr(t[3]), self.addr(t[4]))
        elif k == "closest":
            self.closest[int(t[2])] = self.addr(t[3])
        elif k == "ahead":
            self.ahead[int(t[2])] = self.addr(t[3])
        elif k == "newroute":
            q["newroute"] = self.addr(t[2])
        elif k == "sound":
            self.sound_on = int(t[2])
        elif k == "zbox":
            if len(t) == 2:
                self.boxes = []
            else:
                self.boxes.append(tuple(bitsf(int(v, 16)) for v in t[2:7])
                                  + (int(t[7], 16),))
        elif k == "end":
            self.end[int(t[2])] = int(t[3])
        elif k == "signto":
            self.signto[int(t[2])] = (self.addr(t[3]), self.addr(t[4]))
        elif k == "nearby":
            self.nearby[int(t[2])] = (int(t[3]), self.addr(t[4]),
                                      self.addr(t[5]))
        elif k == "ptt":
            self.ptt[int(t[2])] = [(self.addr(t[i]), self.addr(t[i + 1]))
                                   for i in range(3, len(t) - 1, 2)]
        else:
            raise SystemExit("no answer %s" % k)


def model(lines):
    m = Model()
    for ln in lines:
        m.run(ln.split("|"))
    return m.lines


# ================================================================ the script

def F(v):
    return fx(v)


def setup():
    """The cars, the routes' points, and default answers."""
    out = []
    for i in range(NCARS):
        out.append("car|%d|%s|%s|%s|%d|%s|%s" % (
            i, F(100.0 * i + 3.5), F(-40.0 * i + 7.25), F(12.0 + i),
            [0, 16384, 50000][i], F([30.0, 55.5, 0.0][i]),
            F(1000.0 + 37.5 * i)))
    for i in range(NPOINTS):
        bits = 0xff | (0x3f << 8) | (0x3f << 22) | 0x8000
        if i % 5 == 2:
            bits |= NO_HELISHEET
        if i % 7 == 3:
            bits &= ~0xff
            bits |= i
        out.append("point|%d|%s|%s|%s|%08x|%s|%s" % (
            i, F(10.0 * i - 50.0), F(3.0 * i + 1.0), F(8.0 + i * 0.75),
            bits, F(math.cos(0.7 * i)), F(math.sin(0.7 * i))))
    out += ["q|carroute|%d|R%d|P%d" % (i, i, PER_ROUTE * i + 1)
            for i in range(NCARS)]
    out += ["q|elev|%s|3" % F(4.5), "q|cmp|%s" % F(-12.0),
            "q|near|1|R2|P13", "q|newroute|R3", "q|sheet|1", "q|signs|1"]
    for i in range(NPOINTS):
        out.append("q|zval|%d|1|%x" % (i, 0 if i % 4 else 2))
    return out


def life():
    out = []
    for egg in (0, 1):
        for ai in (0, 1, 7):
            for rep in (0, 1, -1):
                out += ["q|egg|%d" % egg, "q|demo|%d|%d" % (ai, rep), "new",
                        "del|%d" % (3 if (ai + rep) % 2 else 2)]
    out += ["q|egg|1", "q|demo|0|0", "q|sound|0", "new", "set|car|C0", "place|%s|%s|%s"
            % (F(1.0), F(2.0), F(3.0)), "mute|1", "usound", "remove",
            "del|1", "q|sound|1", "q|egg|0"]
    # ClearVariables over a scrambled helicopter.
    out += ["new", "set|plan|2", "set|car|C2", "set|n960|1",
            "set|pos|%s|%s|%s" % (F(5.0), F(-6.0), F(7.0)),
            "set|yaw|%s" % F(33.0), "set|roll|%s" % F(-4.0),
            "set|pitch|%s" % F(9.0), "set|gz|%s" % F(3.0),
            "set|td|%s" % F(40.0), "set|bomb|3", "set|chop|R1|P7",
            "set|target|R2|P14", "set|tpd|%s" % F(88.0), "attack|1",
            "set|mm|1", "set|salvos|5", "set|launcher|2", "set|total|9",
            "set|dust|1", "set|think|%s" % F(0.75),
            "set|nsalvo|%s" % F(1.25), "set|timeout|%s" % F(3.0),
            "set|stuck|%s" % F(0.5), "set|speed|%s" % F(41.0),
            "set|acc|%s|%s" % (F(-2.0), F(6.5)), "set|droll|%s" % F(11.0),
            "set|dpitch|%s" % F(-7.0), "set|rot|%s" % F(0.25),
            "set|zv|%s" % F(-1.5), "clear", "del|3"]
    return out


def follows():
    out = ["new"]
    for n960 in (0, 1):
        for sheet in (0, 1):
            for signs in (0, 1):
                for car in ("NULL", "C1", "C0"):
                    for plan in range(-1, 8):
                        out += ["q|sheet|%d" % sheet, "q|signs|%d" % signs,
                                "set|plan|%d" % plan, "set|car|C2",
                                "set|n960|%d" % n960, "follow|%s" % car]
    out += ["q|sheet|1", "q|signs|1", "set|n960|0", "del|3"]
    return out


def attacks(rng):
    out = ["new", "set|chop|R1|P8", "set|pos|%s|%s|%s" % (
        F(20.0), F(-15.0), F(30.0))]
    # Every plan, with and without a car.
    for plan in range(-1, 8):
        for car in ("NULL", "C1"):
            if plan == 0 and car == "NULL":
                continue                # retail reads through it
            out += ["set|plan|%d" % plan, "set|car|%s" % car,
                    "set|n960|0", "attack|2"]
    # The run itself: each type, speed and distance.
    guesses = ["q|guess",
               "q|guess|R0|P2",
               "q|guess|R0|P2|R0|P3",
               "q|guess|R1|P7|R1|P12|R2|P13",
               "q|guess|R0|P2|R1|P7|R1|P12|R2|P17|R3|P22",
               "q|guess|R0|P2|R1|P7|R1|P12|R2|P17|R3|P19"]
    k = 0
    for typ in range(5):
        for vel in (0.0, 20.0, 49.0, 50.0, 70.0, 101.5, float("nan")):
            for cmpv in (-1.0, 0.0, 3.0, float("nan")):
                k += 1
                cpx = rng.choice((10.0, 120.0, -300.0, 3.5))
                out += ["car|1|%s|%s|%s|%d|%s|%s" % (
                    F(cpx), F(rng.uniform(-200, 200)), F(5.0),
                    rng.randrange(65536), F(vel), F(500.0)),
                    "q|cmp|%s" % F(cmpv), guesses[k % len(guesses)],
                    "set|plan|0", "set|car|C1", "attack|%d" % typ]
    # AdjustBombTarget's edge: TargetDistance + 24 against the lead.
    out += ["car|1|%s|%s|%s|0|%s|%s" % (F(0.0), F(0.0), F(0.0), F(60.0),
                                         F(0.0)), guesses[3]]
    for typ in (0, 2, 4):
        ahead = [2.0, 2.0, 1.5, 2.0, 1.0][typ] * 60.0
        lead = max(ahead, 100.0)
        for td in (lead - 24.0, lead - 24.0001, lead - 23.9999, -500.0,
                   float("nan"), lead):
            out += ["set|bomb|%d" % typ, "set|td|%s" % F(td), "adjust"]
    out.append("del|3")
    return out


def shifts():
    out = ["new", "set|car|C2", "set|target|R3|P20"]
    for g in ("q|guess",
              "q|guess|R0|P2",
              "q|guess|R0|P2|R0|P7",
              "q|guess|R0|P7|R0|P2",
              "q|guess|R0|P2|R1|P12|R2|P17|R3|P22|R3|P23",
              "q|guess|R0|P2|R1|P12|R2|P17|R3|P22|R3|P2",
              "q|guess|R0|P3|R2|P13|R3|P19",
              "q|guess|R0|P2|R2|P13|R3|P19|R3|P20"):
        for d in (0.0, 150.0, -3.0):
            out += [g, "shift|%s" % F(d)]
    out.append("del|3")
    return out


def spots():
    """Runs of covered polygons to walk over, misses included."""
    out = ["new"]
    cases = [
        (0, []),                              # a first-try miss
        (0, [(0, 1, 0)]),                     # a hit, open ground
        (0, [(0, 1, 1), (1, 1, 0)]),
        (0, [(0, 1, 3), (1, 1, 1), (2, 1, 2), (3, 1, 0xfe)]),
        (4, [(4, 1, 1), (5, 0, 0), (6, 1, 0)]),   # a miss after a hit
        (7, [(7, 1, 0xff), (8, 0, 0), (9, 0, 0), (10, 1, 0x10)]),
        (12, [(12, 1, 5), (13, 1, 7), (14, 1, 9), (15, 1, 4)]),
        (18, [(18, 0, 0), (19, 0, 0)]),       # a first-try miss again
    ]
    for start, run in cases:
        out += ["q|zval|%d|0|0" % i for i in range(NPOINTS)]
        for i, hit, fl in run:
            out.append("q|zval|%d|%d|%x" % (i, hit, fl))
        out += ["set|target|R%d|P%d" % (start // PER_ROUTE, start),
                "set|td|%s" % F(17.5), "spot"]
    out += ["q|zval|%d|1|0" % i for i in range(NPOINTS)]
    # AttackCar through to the walk.
    out += ["q|zval|13|1|1", "q|zval|14|1|1", "q|guess|R2|P12|R2|P13",
            "set|chop|R0|P1",
            "car|2|%s|%s|%s|0|%s|%s" % (F(0.0), F(0.0), F(0.0), F(90.0),
                                         F(0.0)),
            "set|plan|0", "set|car|C2", "set|td|%s" % F(0.0), "attack|1"]
    out += ["q|zval|13|1|0", "q|zval|14|1|2", "del|3"]
    return out


def world_ops(rng):
    out = ["new", "set|car|C1"]
    for z, ter in ((4.5, 3), (-2.25, 0), (float("inf"), 7), (0.0, -1)):
        out += ["q|elev|%s|%d" % (F(z), ter), "set|gz|%s" % F(z * 2 + 1),
                "set|pos|%s|%s|%s" % (F(z), F(-z), F(9.0)), "ground"]
    for ang in (0, 1, 182, 16384, 32767, 32768, 49152, 65535):
        for near in (0, 1):
            out += ["car|1|%s|%s|%s|%d|%s|%s" % (
                F(rng.uniform(-500, 500)), F(rng.uniform(-500, 500)),
                F(rng.uniform(-10, 40)), ang, F(33.0), F(10.0)),
                "q|near|%d|R%d|P%d" % (near, ang % 4, ang % 24),
                "q|elev|%s|%d" % (F(rng.uniform(-5, 50)), ang % 9),
                "set|roll|%s" % F(rng.uniform(-30, 30)),
                "set|pitch|%s" % F(rng.uniform(-30, 30)),
                "set|droll|%s" % F(rng.uniform(-30, 30)),
                "set|dpitch|%s" % F(rng.uniform(-30, 30)),
                "set|speed|%s" % F(rng.uniform(0, 90)),
                "place|%s|%s|%s" % (F(rng.uniform(-900, 900)),
                                    F(rng.uniform(-900, 900)),
                                    F(rng.uniform(0, 80))),
                "wobj", "remove"]
    for c in (-1.0, 0.0, -0.0, 1e-30, -1e-30, 5.0, float("nan"),
              float("-inf")):
        out += ["q|cmp|%s" % F(c), "set|tpd|%s" % F(c * 3 + 1),
                "behind"]
    for plan in range(-1, 8):
        out += ["set|plan|%d" % plan, "maxdecel", "abort"]
    for i in (0, 1, -1, 7):
        out += ["mute|%d" % i]
    out += ["usound"]
    out.append("del|3")
    return out


def routes():
    out = ["new"]
    for near in (0, 1):
        out += ["q|near|%d|R1|P9" % near, "set|chop|R0|P0",
                "set|pos|%s|%s|%s" % (F(1.5), F(2.5), F(3.5)), "scratch"]
    # The chopper's point: P3 has a signpost, P4 none.
    for cp in ("P3", "P4", "P10"):
        for first in ("NULL", "P5"):
            for second in ("NULL", "P20"):
                for near in (0, 1):
                    out += ["q|closest|0|%s" % first,
                            "q|closest|1|%s" % first,
                            "q|closest|3|%s" % second,
                            "q|newroute|R3",
                            "q|near|%d|R2|P15" % near,
                            "set|chop|R%d|%s" % (int(cp[1:]) // PER_ROUTE,
                                                 cp),
                            "routepoint"]
    out.append("del|3")
    return out


def matrices(rng):
    out = ["new"]
    angles = [0.0, 1.0, -1.0, 90.0, 179.99, 180.0, 180.01, 270.0, 359.9,
              360.0, 361.0, -720.5, 1e6, -1e6, 32767.0, 0.0001,
              # 180 - Yaw is 359/65536, whose sum with 360 rounds up to a
              # whole BAM: the one place where `< 0` is not `< 1`.
              180.0 - 359.0 / 65536.0]
    for k in range(60):
        out += ["set|roll|%s" % F(rng.choice(angles + [rng.uniform(-400,
                                                                    400)])),
                "set|pitch|%s" % F(rng.choice(angles + [rng.uniform(-400,
                                                                     400)])),
                "set|yaw|%s" % F(rng.choice(angles + [rng.uniform(-400,
                                                                   400)])),
                "set|pos|%s|%s|%s" % (F(rng.uniform(-3000, 3000)),
                                      F(rng.uniform(-3000, 3000)),
                                      F(rng.uniform(-50, 200))),
                "matrix"]
        if k % 10 == 0:
            out.append("wobj")
    for yaw in angles + [45.0, -45.0, 123.456]:
        for v in ((1.0, 0.0), (0.0, 1.0), (-3.5, 7.25), (1e-3, -2e4)):
            out += ["set|yaw|%s" % F(yaw), "rotate|%s|%s" % (F(v[0]),
                                                              F(v[1]))]
    out.append("del|0")
    return out


# ---- 12k-3a's chase logic --------------------------------------------------
#
# The points run along a line, P_i at (10i - 50, 3i + 1), so P_k is about
# 10.44 * |k - j| from P_j. Signposts come from FindNearbySignpost's
# answers; each sign's word has junk round its Flags byte.

def T(x, y, s=3.0):
    return "tgt|%s|%s|%s" % (F(x), F(y), F(s))


def PP(i):
    return (10.0 * i - 50.0, 3.0 * i + 1.0)


def POS(x, y, z=20.0):
    return "set|pos|%s|%s|%s" % (F(x), F(y), F(z))


def SIGN(i, flags):
    return "sign|%d|%08x" % (i, 0x5a170021 | (flags << 8))


def BOX(x0, y0, x1, y1, z=0.0, fl=0):
    return "q|zbox|%s|%s|%s|%s|%s|%x" % (F(x0), F(y0), F(x1), F(y1), F(z),
                                         fl)


def forks():
    """The signposts FindPreviousFork walks back through, as answers:
    from P1 to sign 4, plain, into R2 at P14; from P8 to sign 9, a 2,
    into R2 at P13, a step on, then from P12 to sign 15, a 3, into R3 at
    P19; from P20 to sign 21, a 2 with Backwards, into R0 at P0; from P6
    to sign 6, plain, into R1 at P7."""
    return ["q|nearby|1|3|R0|P4", SIGN(4, 0), "q|signto|4|R2|P14",
            "q|nearby|8|2|R1|P9", SIGN(9, 2), "q|signto|9|R2|P13",
            "q|nearby|12|4|R2|P15", SIGN(15, 3), "q|signto|15|R3|P19",
            "q|nearby|20|1|R3|P21", SIGN(21, 0x0a), "q|signto|21|R0|P0",
            "q|nearby|6|1|R1|P6", SIGN(6, 0x16), "q|signto|6|R1|P7",
            "q|nearby|10|2|R1|P11", SIGN(11, 0x7c), "q|signto|11|R3|P18"]


def chase_start(rng):
    out = ["new", "set|car|C1", "set|chop|R0|P1"]
    for on in (0, 1, 2):
        for fl in (0, 1, 2, 3, 4, 5, 0xfffffffe):
            for z in (0.0, 37.25, -150.0, float("nan")):
                out += [T(rng.uniform(-500, 500), rng.uniform(-500, 500),
                          9.0),
                        "set|plan|3", "set|zv|%s" % F(1.0), "set|dust|7",
                        "start|%d|%x|%s" % (on, fl, F(z))]
    out.append("del|3")
    return out


def chase_end():
    out = ["new", "set|car|C1", "set|chop|R0|P1"]
    # Over the sheet: high enough to go, still over a flag-1 polygon, or
    # climbing.
    for z in (180.0 - 150.0, 50.0, 50.0001, 49.9999, float("nan"), -1e30):
        for fl in (0, 1, 2, 3, 0xfffffffd):
            for zv in (0.0, -0.0, 25.0, float("nan")):
                out += ["q|zbox", BOX(-40.0, 0.0, -20.0, 10.0, z, fl),
                        POS(-30.0, 7.0, 200.0), "set|zv|%s" % F(zv),
                        "set|plan|5", T(1.0, 2.0), "endchase"]
    # Off it: the walk on from the helicopter's point.
    out.append("q|zbox")
    for cp, ends, pos in ((1, (), PP(2)), (1, (1,), PP(2)),
                          (1, (3,), PP(2)), (4, (5,), PP(2)),
                          (5, (), PP(2)), (22, (), PP(2)),
                          (23, (), PP(2)), (1, (), (500.0, 500.0)),
                          (2, (), (-30.0, 37.0)), (2, (), (-30.0, 36.9)),
                          # P4 30.5 away, then exactly 30 (18, 24).
                          (1, (), (PP(4)[0] - 30.5, PP(4)[1])),
                          (1, (), (PP(4)[0] - 18.0, PP(4)[1] - 24.0))):
        out += ["q|end|%d|1" % k for k in ends]
        out += ["set|chop|R%d|P%d" % (cp // PER_ROUTE, cp), POS(*pos),
                T(1.0, 2.0), "endchase"]
        out += ["q|end|%d|0" % k for k in ends]
    out.append("del|3")
    return out


def chase_forks():
    out = ["new", "set|car|C2", "set|chop|R0|P1"] + forks()
    for cp in (0, 1, 6, 8, 10, 14, 20, 23):
        for b in (0, 1):
            out.append("prevfork|R%d|P%d|%d" % (cp // PER_ROUTE, cp, b))
    # SwitchToNearbyFork: found at once, part way, at the end of its count
    # and past it, off the route, or never.
    for pos, cp, b, maxd in (
            (PP(22), 8, 1, 200.0), (PP(22), 8, 1, 15.0),
            (PP(22), 8, 1, 5.0), (PP(22), 8, 1, 0.0),
            (PP(22), 8, 1, float("nan")), (PP(22), 8, 0, 15.0),
            (PP(9), 6, 1, 5.0), (PP(9), 6, 1, 15.0),
            (PP(9), 6, 1, 25.0), (PP(9), 6, 0, 15.0),
            (PP(9), 0, 1, 1e9), (PP(13), 20, 0, 1.0),
            (PP(13), 20, 0, 11.0), (PP(13), 20, 1, 11.0),
            (PP(17), 10, 1, 10.5), (PP(17), 10, 0, 10.5)):
        out += [POS(*pos), "switchfork|R%d|P%d|%d|%s" % (
            cp // PER_ROUTE, cp, b, F(maxd))]
    # ChopperOnDifferentFork.
    for cp in (0, 1, 8, 20):
        out.append("set|chop|R%d|P%d" % (cp // PER_ROUTE, cp))
        for r in range(NROUTES):
            out.append("difffork|R%d|P%d" % (r, 5 * r + 1))
    out.append("del|3")
    return out


def chase_follow():
    out = ["new", "set|car|C1", "set|chop|R0|P1"] + forks()
    # Speed 0 makes the least distance 30; 2000, 200; NaN, NaN.
    lists = {"a": "q|ptt|1|R0|P2|R0|P3|R0|P4|R0|P5",
             "b": "q|ptt|1|R0|P2|R0|P3",
             "c": "q|ptt|1",
             "d": "q|ptt|1|R0|P2|R0|P3|R0|P4|R0|P5|R1|P6|R1|P7",
             "e": "q|ptt|1|R0|P5|R0|P4"}
    cases = [
        # (list, pos, speed, point, fwd)
        ("a", PP(1), 0.0, "P1", 1), ("a", (60.0, 4.0), 0.0, "P1", 1),
        ("a", (60.0, 4.0), 0.0, "P3", 1), ("a", (60.0, 4.0), 2000.0, "P3",
                                           1),
        ("a", PP(1), 0.0, "P5", 1), ("a", PP(1), 0.0, "P3", 0),
        ("a", PP(1), 0.0, "P4", 1), ("b", PP(1), 0.0, "P20", 1),
        ("b", PP(1), 0.0, "P3", 1), ("d", PP(1), 2000.0, "P20", 1),
        ("d", PP(1), float("nan"), "P5", 1), ("e", PP(1), 0.0, "P4", 1),
        ("e", PP(1), 0.0, "P5", 0), ("b", (-30.0, -23.0), 0.0, "P20", 1),
        ("b", (-30.0, -22.9), 0.0, "P20", 1),
        ("b", (-30.0, -23.1), 0.0, "P20", 1),
        # P1 exactly 30 away (18, 24): not far.
        ("a", (PP(1)[0] + 18.0, PP(1)[1] + 24.0), 0.0, "P3", 1),
        # None: a fork near enough, or none.
        ("c", PP(1), 0.0, "P20", 1), ("c", PP(1), 2000.0, "P17", 1),
        ("c", PP(1), 2000.0, "P20", 1), ("c", PP(1), 2000.0, "P20", 0),
        # Least distance 100: the fork's P14 to P17 are all further.
        ("c", PP(1), 1000.0, "P20", 1),
    ]
    for ptt14 in ("q|ptt|14|R2|P15|R2|P16|R2|P17", "q|ptt|14"):
        out.append(ptt14)
        for lst, pos, speed, pt, fwd in cases:
            k = int(pt[1:])
            out += [lists[lst], POS(*pos), "set|speed|%s" % F(speed),
                    T(-1.0, -2.0, 7.0),
                    "followroute|R%d|%s|%d" % (k // PER_ROUTE, pt, fwd)]
    out += ["set|chop|R2|P13", "tcp", "set|car|C0", "fspeed", "set|car|C2",
            "fspeed"]
    out.append("del|3")
    return out


def chase_stakeout():
    out = ["new", "set|car|C1", "set|chop|R0|P1", POS(*PP(1)),
           "set|speed|%s" % F(0.0), "q|ptt|1|R0|P2|R0|P3|R2|P14",
           BOX(-1e9, -1e9, 1e9, 1e9)]
    # P3, P10 and P17 have signposts; P17 is TRP_NO_HELISHEET too. P3's
    # and P10's signs lead to R2 at P14 and R3 at P19.
    out += ["q|signto|3|R2|P14", "q|signto|10|R3|P19",
            "q|signto|17|R1|P8"]
    for f3 in (0x00, 0x08, 0x10, 0x18, 0xe7):
        for f10 in (0x00, 0x08, 0x10):
            for start in ("R0|P0", "R0|P3", "R0|P4", "R1|P11", "R3|P21"):
                for cl in ("NULL", "lo", "same", "hi"):
                    out += [SIGN(3, f3), SIGN(10, f10),
                            "set|chop|R0|P1", "set|plan|0",
                            "set|timeout|%s" % F(1.0), T(5.0, 6.0)]
                    for r, (lo, same, hi) in ((0, ("P2", "P3", "P4")),
                                              (1, ("P9", "P10", "P11")),
                                              (2, ("P13", "P14", "P16")),
                                              (3, ("P18", "P19", "P23"))):
                        pick = {"NULL": "NULL", "lo": lo, "same": same,
                                "hi": hi}[cl]
                        out.append("q|closest|%d|%s" % (r, pick))
                    out.append("stakeout|" + start)
    # Run off the end: BailToPointNearChopper.
    out += ["q|end|5|1", SIGN(3, 0x10), "set|chop|R1|P8", "stakeout|R0|P4",
            "q|end|5|0"]
    for r in range(NROUTES):
        out.append("q|closest|%d|NULL" % r)
    out += ["q|zbox", "del|3"]
    return out


def chase_hangout(rng):
    out = ["new", "set|car|C1", "set|chop|R1|P8"]
    boxes = [[(-1e9, -1e9, 1e9, 1e9)], [(-1.0, -1.0, 1.0, 1.0)],
             [(5.0, -100.0, 6.0, 100.0)], [], [(-3.0, 2.0, 3.0, 2.5)],
             [(0.0, 0.0, 0.0, 0.0)],
             [(30.0, -2.0, 40.0, 2.0), (-0.5, -0.5, 0.5, 0.5)]]
    for k, bx in enumerate(boxes):
        for pt in (8, 15, 21):
            for tx, ty in ((PP(pt)[0] + 40.0, PP(pt)[1] - 13.0),
                           (PP(pt)[0] - 3.0, PP(pt)[1] + 70.0), PP(pt),
                           (rng.uniform(-300, 300), rng.uniform(-300, 300)),
                           (float("nan"), 1.0)):
                out.append("q|zbox")
                out += [BOX(*b) for b in bx]
                out += [T(tx, ty, 4.0),
                        "hangout|R%d|P%d" % (k % NROUTES, pt)]
    out += ["q|zbox", BOX(-0.25, -0.25, 0.25, 0.25), T(500.0, -400.0),
            "bail", "q|zbox", "del|3"]
    return out


def chase_bounds(rng):
    out = ["new", "set|car|C1"]
    for sp in (0.0, 299.99, 300.0, 300.0001, 1e30, -5.0, float("nan"),
               float("inf")):
        out += ["set|speed|%s" % F(sp), "minfollow"]
    # AdjustTargetInBounds: still, settling and never settling.
    fixed = [((0.0, 0.0), [(95.0, 190.0, 110.0, 230.0)]),
             ((0.0, 0.0), [(80.0, -1e3, 97.0, 1e3)]),
             ((0.0, 0.0), [(103.0, -1e3, 120.0, 1e3)]),
             ((0.0, 0.0), [(-1e3, 202.0, 1e3, 300.0)]),
             ((0.0, 0.0), [(-1e3, 100.0, 1e3, 197.0)]),
             ((0.0, 0.0), [(80.0, 180.0, 98.0, 198.0)]),
             ((0.0, 0.0), []),
             ((1.5, 0.0), [(80.0, -1e3, 97.0, 1e3)]),
             ((3.0, 0.0), [(80.0, -1e3, 97.0, 1e3)])]
    for (tx, ty), bx in fixed:
        out.append("q|zbox")
        out += [BOX(*b) for b in bx]
        out += [POS(100.0, 200.0, 50.0), "set|yaw|%s" % F(0.0), T(tx, ty),
                "inbounds"]
    for _ in range(80):
        out.append("q|zbox")
        for _ in range(rng.randrange(1, 4)):
            x0, y0 = rng.uniform(-30, 30), rng.uniform(-30, 30)
            out.append(BOX(x0, y0, x0 + rng.uniform(0, 20),
                           y0 + rng.uniform(0, 20)))
        out += [POS(rng.uniform(-20, 20), rng.uniform(-20, 20), 50.0),
                "set|yaw|%s" % F(rng.choice((0.0, 90.0, 180.0, 270.0,
                                             rng.uniform(-400, 400)))),
                T(rng.uniform(-15, 15), rng.uniform(-15, 15)), "inbounds"]
    # TestLocation, AdjustTargetLocal and AdjustByThinkTime.
    out += ["q|zbox", BOX(0.0, 0.0, 10.0, 10.0, 0.0, 0)]
    for yaw in (0.0, 45.0, 90.0, -30.0, 400.0):
        for x, y in ((1.0, 1.0), (5.0, -5.0), (-3.0, 4.0), (0.0, 0.0)):
            out += [POS(2.0, 3.0), "set|yaw|%s" % F(yaw),
                    "testloc|%s|%s" % (F(x), F(y)), T(x * 7.0, y - 2.0),
                    "local"]
    for f in (0.0, 0.25, -1.5, 1e37, float("nan")):
        out.append("bythink|%s" % F(f))
    out += ["q|zbox", "del|3"]
    return out


def chase(rng):
    return (chase_start(rng) + chase_end() + chase_forks()
            + chase_follow() + chase_stakeout() + chase_hangout(rng)
            + chase_bounds(rng))


# ---- 12k-3b's plans --------------------------------------------------------
#
# P_i's direction is (cos 0.7i, sin 0.7i); a spot k to its right is
# P_i + k * (dir.y, -dir.x), whose cross with the direction is k.

def RIGHT(i, k):
    x, y = PP(i)
    return (x + k * math.sin(0.7 * i), y - k * math.cos(0.7 * i))


def CAR(i, x, y, vel=10.0, z=5.0):
    return "car|%d|%s|%s|%s|0|%s|%s" % (i, F(x), F(y), F(z), F(vel),
                                         F(500.0))


def plans_world():
    """Points to follow, stake out and fork from, as answers."""
    return (["q|ptt|1|R0|P2|R0|P3|R0|P4|R0|P5",
             "q|ptt|2|R0|P3|R0|P4",
             "q|ptt|8|R1|P9|R1|P10|R1|P11",
             "q|ptt|20|R3|P21|R3|P22",
             "q|signto|3|R2|P14", "q|signto|10|R3|P19",
             "q|signto|17|R1|P8", SIGN(3, 0x10), SIGN(10, 0x00),
             "q|closest|0|P3", "q|closest|1|P10", "q|closest|2|P14",
             "q|closest|3|P19"] + forks())


def plans_clever():
    out = ["new", "set|car|C1", "set|chop|R0|P1", POS(*PP(1)),
           "q|zbox", BOX(-1e9, -1e9, 1e9, 1e9), "q|cmp|%s" % F(-12.0)]
    out += plans_world()
    # The early way out: climbing or falling, off the sheet or over flag 2.
    for zv in (0.0, -0.0, 25.0, float("nan")):
        for on in (0, 1, 2):
            for fl in (0, 1, 2, 3, 0xfffffffd):
                out += ["set|zv|%s" % F(zv), T(7.0, 8.0, 2.0),
                        "q|carroute|1|R0|P3", "q|ahead|0|NULL",
                        "set|speed|%s" % F(25.0),
                        "clever|%d|%x" % (on, fl)]
    out.append("set|zv|%s" % F(0.0))
    # The car's point, and the point ahead of the spot.
    cars = [("NULL", "P3", "NULL"), ("R0", "NULL", "NULL"),
            ("NULL", "NULL", "NULL"), ("R0", "P3", "NULL"),
            ("R0", "P3", "P4"), ("R0", "P2", "NULL"), ("R0", "P3", "P2"),
            ("R1", "P7", "NULL"), ("R1", "P8", "P9"), ("R2", "P13", "P14"),
            ("R3", "P20", "P22"), ("R3", "P19", "NULL")]
    chops = [(0, 1), (1, 8), (3, 20)]
    k = 0
    for ro, po, ah in cars:
        for on in (0, 1):
            for speed in (0.0, 20.0, 20.0001, 1000.0, float("nan")):
                for off in ((10.0, 5.0), (150.0, -40.0)):
                    r, c = chops[k % 3]
                    x, y = PP(c)
                    out.append("q|zbox")
                    if k % 4:
                        out.append(BOX(-1e9, -1e9, 1e9, 1e9))
                    out += ["set|chop|R%d|P%d" % (r, c), POS(x, y),
                            "q|cmp|%s" % F((-12.0, 5.0)[k % 2]),
                            "q|carroute|1|%s|%s" % (ro, po)]
                    if ro != "NULL":
                        out.append("q|ahead|%s|%s" % (ro[1:], ah))
                    out += ["set|speed|%s" % F(speed), "set|plan|0",
                            T(x + off[0], y + off[1], 3.0),
                            "clever|%d|%x" % (on, (0, 1)[k % 2])]
                    k += 1
    # Least distance 30: the spot exactly 30 away (18, 24), or just in.
    out += ["q|zbox", BOX(-1e9, -1e9, 1e9, 1e9), "set|chop|R0|P1",
            POS(*PP(1)), "q|carroute|1|R0|P3", "q|ahead|0|P4",
            "set|speed|%s" % F(0.0)]
    for dx in (18.0, 17.99):
        for on in (0, 1):
            out += [T(PP(1)[0] + dx, PP(1)[1] + 24.0), "clever|%d|0" % on]
    out += ["q|zbox", "del|3"]
    return out


def plans_bombrun(rng):
    out = ["new", "set|car|C1", "set|chop|R0|P1", "set|target|R0|P2",
           "q|guess|R0|P2|R0|P3", CAR(1, 0.0, 0.0),
           "width|1|%s|%s" % (F(6.0), F(6.0))] + plans_world()
    # The car's progress since the last time. Each point is its route's,
    # as GetRoute and GetRoutePoint give them: another's index would be
    # the harness's memory layout.
    moves = [("R0|P3", "R0|P3"), ("R0|P4", "R0|P2"), ("R0|P2", "R0|P5"),
             ("R1|P8", "R0|P5"), ("R0|NULL", "R0|P3"), ("R0|P3", "R0|NULL"),
             ("R0|NULL", "R0|NULL"), ("R1|P3", "R0|P3"),
             ("NULL|P3", "R0|P5"), ("R2|P13", "R2|P15"),
             ("R2|P15", "R2|P13"), ("R1|P9", "R1|P9")]
    for now, old in moves:
        for td in (500.0, 0.0, float("nan")):
            out += ["q|carroute|1|" + now, "set|old|" + old,
                    "set|td|%s" % F(td), "set|plan|4", "set|bomb|1",
                    "set|salvos|1", "set|nsalvo|%s" % F(5.0),
                    "set|timeout|%s" % F(5.0), POS(*PP(1)), "bombrun"]
    # Over the road at P1, its widths 4 and 6, a spot k to its right.
    out += ["q|carroute|1|R0|P3", "set|old|R0|P3"]
    for k in (0.0, -0.0, 5.0, -5.0, 3.9, 4.0, 4.1, -3.9, -4.0, -4.1, 6.0,
              -6.0, float("nan")):
        for lw, rw in ((4.0, 6.0), (6.0, 4.0), (0.0, 0.0), (0.0, 6.0),
                       (6.0, 0.0)):
            out += ["width|1|%s|%s" % (F(lw), F(rw)), "q|zbox",
                    BOX(-1e9, -1e9, 1e9, 1e9), "q|elev|%s|3" % F(15.0),
                    "set|plan|4", "set|bomb|2", "set|salvos|0",
                    "set|nsalvo|%s" % F(5.0), "set|td|%s" % F(500.0),
                    "set|timeout|%s" % F(5.0), POS(*RIGHT(1, k)),
                    "bombrun"]
    # The reach to the target, P2: exactly 30 from it, or just in, and
    # within 30 of the helicopter's P1 alone. P1's road is wide enough to
    # fire from anywhere here.
    out.append("width|1|%s|%s" % (F(50.0), F(50.0)))
    x1, y1 = PP(1)
    x2, y2 = PP(2)
    for pos in ((x2 + 18.0, y2 + 24.0), (x2 + 17.99, y2 + 24.0),
                (x2 + 30.0, y2), (x2 - 29.99, y2), (x1 - 25.0, y1),
                (float("nan"), y2)):
        out += ["set|plan|4", "set|bomb|2", "set|salvos|0",
                "set|target|R0|P2", "set|td|%s" % F(500.0),
                "set|timeout|%s" % F(5.0), POS(*pos), "bombrun"]
    out.append("width|1|%s|%s" % (F(4.0), F(6.0)))
    # The salvos' clock, the sheet and the height, each type to its last
    # salvo.
    for typ in range(5):
        for salvos in range(-1, [1, 8, 3, 1, 2][typ] + 1):
            for nsalvo in (0.05, 0.1, 0.15, -0.0, float("nan")):
                for hit, elev in ((1, 10.0), (1, 9.5), (0, 15.0),
                                  (1, float("nan")), (1, 15.0)):
                    out.append("q|zbox")
                    if hit:
                        out.append(BOX(-1e9, -1e9, 1e9, 1e9, 2.0, 1))
                    out += ["q|elev|%s|%d" % (F(elev), typ),
                            "set|plan|4", "set|bomb|%d" % typ,
                            "set|salvos|%d" % salvos, "set|total|%d" % typ,
                            "set|nsalvo|%s" % F(nsalvo),
                            "set|timeout|%s" % F((5.0, 0.0)[salvos % 2]),
                            "set|td|%s" % F(500.0), POS(*PP(1)),
                            "bombrun"]
    # The timeout, with no salvo to fire.
    for to in (0.0, -0.0, 5.0, float("nan"), 1e-45):
        out += ["q|zbox", "set|plan|4", "set|bomb|0", "set|salvos|0",
                "set|timeout|%s" % F(to), POS(500.0, 500.0), "bombrun"]
    # Mixed.
    for _ in range(120):
        now, old = rng.choice(moves)
        typ = rng.randrange(5)
        out.append("q|zbox")
        if rng.random() < 0.7:
            out.append(BOX(-1e9, -1e9, 1e9, 1e9))
        out += ["q|carroute|1|" + now, "set|old|" + old,
                CAR(1, rng.uniform(-100, 100), rng.uniform(-100, 100),
                    rng.choice((0.0, 30.0, 80.0))),
                "width|1|%s|%s" % (F(rng.uniform(0, 8)),
                                   F(rng.uniform(0, 8))),
                "q|elev|%s|1" % F(rng.choice((10.0, 12.0, 30.0))),
                "set|plan|4", "set|bomb|%d" % typ,
                "set|salvos|%d" % rng.randrange(-1, 4),
                "set|nsalvo|%s" % F(rng.choice((0.05, 0.2, 1.0))),
                "set|td|%s" % F(rng.uniform(-50, 300)),
                "set|timeout|%s" % F(rng.choice((0.0, 0.1, 5.0))),
                POS(*RIGHT(1, rng.uniform(-8, 8))), "bombrun"]
    out += ["q|zbox", "del|3"]
    return out


def plans_hlp(rng):
    out = ["new", "set|car|C1", "set|chop|R0|P1", "set|target|R0|P2",
           "q|near|1|R2|P15", "q|carroute|1|R0|P3", "q|ahead|0|P4",
           "width|1|%s|%s" % (F(4.0), F(6.0)), "q|elev|%s|3" % F(4.5),
           "q|cmp|%s" % F(-12.0)] + plans_world()
    # Every plan, the timeout's tick, on or off the sheet; the car's spot
    # 0.3 s on is (3, 6), 50 from the helicopter.
    for plan in range(-1, 8):
        for to in (0.05, 0.1, 0.15, 5.0, float("nan"), 0.0):
            for fl in (None, 0, 2, 1):
                out.append("q|zbox")
                if fl is not None:
                    out.append(BOX(2.0, 5.0, 4.0, 7.0, 37.25, fl))
                out += [CAR(1, 0.0, 0.0), "carvel|1|%s|%s|%s" % (
                    F(10.0), F(20.0), F(-3.0)), "set|car|C1",
                    "set|chop|R0|P1", "set|target|R0|P2",
                    "set|plan|%d" % plan,
                    "set|timeout|%s" % F(to), "set|zv|%s" % F(0.0),
                    "set|speed|%s" % F(25.0), "set|bomb|1",
                    "set|salvos|0", "set|td|%s" % F(500.0),
                    "set|old|R0|P3", POS(33.0, 46.0, 30.0),
                    T(-7.0, -8.0, 9.0), "hlp"]
    # The stakeout: given up within 60 of the car's spot, reached within
    # 30 of its point, P2.
    x2, y2 = PP(2)
    for plan in (1, 2):
        for pos in ((3.0 + 36.0, 6.0 + 48.0), (3.0 + 35.99, 6.0 + 48.0),
                    (x2 + 18.0, y2 + 24.0), (x2 + 17.99, y2 + 24.0),
                    (x2, y2), (-200.0, 300.0)):
            for fl in (None, 0):
                for to in (5.0, 0.1):
                    out.append("q|zbox")
                    if fl is not None:
                        out.append(BOX(2.0, 5.0, 4.0, 7.0, 0.0, fl))
                    out += ["set|plan|%d" % plan, "set|target|R0|P2",
                            "set|timeout|%s" % F(to), "set|chop|R0|P1",
                            POS(*pos), "hlp"]
    # The chopper's point: kept, from the sign's route, or from scratch.
    for cl in ("P1", "NULL"):
        for chop in ("R0|P1", "R0|P3"):
            out += ["q|closest|0|%s" % cl, "q|zbox",
                    BOX(-1e9, -1e9, 1e9, 1e9), "set|chop|" + chop,
                    "set|plan|0", "set|timeout|%s" % F(5.0),
                    POS(*PP(1)), "hlp"]
    out.append("q|closest|0|P3")
    # End chase with no car.
    for z in (180.0, 40.0):
        out += ["q|zbox", BOX(-1e9, -1e9, 1e9, 1e9, 30.0, 0),
                "set|car|NULL", "set|plan|5", "set|chop|R0|P1",
                POS(-30.0, 7.0, z), "set|timeout|%s" % F(1.0), "hlp"]
    out.append("set|car|C1")
    # Mixed.
    for _ in range(200):
        plan = rng.choice((0, 0, 1, 2, 3, 4, 5, 6))
        out.append("q|zbox")
        bx = rng.random()
        if bx < 0.5:
            out.append(BOX(-1e9, -1e9, 1e9, 1e9, rng.uniform(-200, 200),
                           rng.choice((0, 0, 1, 2, 3))))
        elif bx < 0.8:
            x0, y0 = rng.uniform(-60, 60), rng.uniform(-60, 60)
            out.append(BOX(x0, y0, x0 + rng.uniform(0, 60),
                           y0 + rng.uniform(0, 60), rng.uniform(0, 80),
                           rng.choice((0, 1, 2))))
        r, c = rng.choice(((0, 1), (1, 8), (3, 20), (0, 2)))
        x, y = PP(c)
        out += [CAR(1, rng.uniform(-80, 80), rng.uniform(-80, 80),
                    rng.choice((0.0, 30.0, 60.0))),
                "carvel|1|%s|%s|%s" % (F(rng.uniform(-60, 60)),
                                       F(rng.uniform(-60, 60)),
                                       F(rng.uniform(-5, 5))),
                "q|carroute|1|%s" % rng.choice(("R0|P3", "R0|P2", "R1|P8",
                                                "R3|P20", "R2|P13",
                                                "NULL|P3")),
                "q|ahead|%d|%s" % (rng.randrange(NROUTES),
                                   rng.choice(("NULL", "P4", "P9", "P22"))),
                "q|cmp|%s" % F(rng.choice((-12.0, 5.0))),
                "q|elev|%s|2" % F(rng.choice((4.5, 15.0, 25.0))),
                "set|chop|R%d|P%d" % (r, c), "set|plan|%d" % plan,
                "set|timeout|%s" % F(rng.choice((0.05, 0.1, 3.0, 30.0))),
                "set|zv|%s" % F(rng.choice((0.0, 0.0, 4.0))),
                "set|speed|%s" % F(rng.choice((0.0, 25.0, 300.0, 1000.0))),
                "set|bomb|%d" % rng.randrange(5),
                "set|salvos|%d" % rng.randrange(0, 3),
                "set|nsalvo|%s" % F(rng.choice((0.05, 0.5))),
                "set|td|%s" % F(rng.uniform(-20, 300)),
                "set|old|%s" % rng.choice(("R0|P3", "R0|P1", "R1|P9")),
                POS(x + rng.uniform(-40, 40), y + rng.uniform(-40, 40),
                    rng.uniform(5, 200)),
                T(rng.uniform(-50, 50), rng.uniform(-50, 50), 4.0), "hlp"]
    out += ["q|zbox", "del|3"]
    return out


def plans(rng):
    return plans_clever() + plans_bombrun(rng) + plans_hlp(rng)


# ---- 12k-4a's flying -------------------------------------------------------

NAN = float("nan")


def CARH(i, x, y, heading):
    return "car|%d|%s|%s|%s|%d|%s|%s" % (i, F(x), F(y), F(5.0), heading,
                                         F(10.0), F(500.0))


def ACC(x, y):
    return "set|acc|%s|%s" % (F(x), F(y))


def fly_angles():
    return ["relangle|%s" % F(f) for f in (
        0.0, -0.0, 180.0, 180.00002, -180.0, -180.00002, 179.99998, 540.0,
        541.0, -541.0, 359.9, -359.9, 720.5, 10000.0, -10000.25, NAN)]


def fly_accel():
    out = ["new", "set|car|C1"]
    # SetXAccel: toward DesiredSpeed or by the think time, then no lower
    # than -60 or -120 by the plan and no higher than 20.
    for plan in (0, 1, 2, 3):
        for ds in (-1.0, 0.0, -0.0, 5.0, 50.0, NAN):
            for x in (-10.0, -0.61, -0.59, -0.0, 0.0, 1e-4, 0.19, 0.21,
                      3.0, 100.0, NAN):
                for sp in (0.0, 10.0, 40.0, -5.0, NAN):
                    out += ["set|plan|%d" % plan, "set|speed|%s" % F(sp),
                            ACC(1.5, 2.5), T(x, 7.0, ds), "xaccel"]
    # SetYAccel: none from 90 off the nose; the roll past 5, at most 20.
    for ang in (0.0, -0.0, 45.0, 89.99, 90.0, -90.0, 90.0001, -89.99,
                180.0, NAN):
        for y in (0.0, 0.04, 0.05, 0.051, -0.05, -0.051, 0.2, 0.25, -0.25,
                  0.3, -0.3, 1e3, -1e3, NAN):
            out += ["set|droll|%s" % F(77.0), ACC(1.5, 2.5), T(9.0, y),
                    "yaccel|%s" % F(ang)]
    # SetRotateTarget.
    for rot in (-200.0, -180.0, -180.0001, -90.0, -90.0001, -89.99, -0.0,
                0.0, 45.0, 89.99, 90.0, 90.0001, 179.99, 180.0, 200.0, NAN):
        for sc in (1.0, 2.0, 0.5, 0.0, -0.0, -1.0, NAN):
            out += ["set|droll|%s" % F(-33.0), "set|rot|%s" % F(1.25),
                    "rottgt|%s|%s" % (F(rot), F(sc))]
    out.append("del|3")
    return out


def fly_hover():
    out = ["new", "set|car|C1", POS(10.0, 20.0, 30.0)]

    def case(speed=0.0, tx=3.0, ty=3.99, ax=0.0, plan=0, heading=16384,
             car=(40.0, -5.0), yaw=0.0):
        return ["set|plan|%d" % plan, "set|speed|%s" % F(speed),
                ACC(ax, 6.0), T(tx, ty), CARH(1, car[0], car[1], heading),
                "set|yaw|%s" % F(yaw), "set|mm|7",
                "set|rot|%s" % F(1.25), "set|droll|%s" % F(-33.0), "hover"]
    # Still, near and not speeding up, one at a time.
    for sp in (0.0, -0.0, 0.001, -0.001, 0.0010001, -0.0010001, 0.0015,
               1.0, -1.0, NAN):
        out += case(speed=sp)
    for tx, ty in ((3.0, 4.0), (4.99, 0.0), (5.0, 0.0), (5.5, 0.0),
                   (0.0, -4.999), (0.0, 0.0), (-3.0, -3.99), (NAN, 0.0),
                   (0.0, NAN)):
        out += case(tx=tx, ty=ty)
    for ax in (0.1, 0.0999, 0.1000001, 0.15, -50.0, NAN):
        out += case(ax=ax)
    # The turn: the car's heading in PURSUIT, else bATan's way to it.
    for plan in range(7):
        for heading in (0, 16384, 32768, 49152, 50000, 65535):
            for yaw in (0.0, 90.0, 200.0, 359.5):
                for car in ((40.0, -5.0), (10.0, 20.0), (-60.0, 90.0)):
                    out += case(plan=plan, heading=heading, yaw=yaw,
                                car=car)
    # PURSUIT's heading read unsigned: past 32768, a yaw with low bits a
    # turn of under 90 away rounds apart from the signed reading's.
    for heading in (32768, 40000, 50000, 60001, 65535):
        f = heading * 360.0 / 65536.0
        for delta in (-71.3, -3.21, 0.0173, 45.678):
            out += case(heading=heading, yaw=(360.0 - f + delta) % 360.0)
    out.append("del|3")
    return out


def fly_momentum(rng):
    out = ["new", "set|car|C1"]
    # At (0, 0) facing 0 with speed 10 and no acceleration, the probes are
    # (1, 4.5), (1, -4.5) and (5.5, 0): each box holds one, edges on it.
    boxes = [(0.5, 4.5, 1.5, 5.0), (1.0, -5.0, 1.5, -4.5),
             (5.5, -0.5, 6.0, 0.5)]
    for sp, ax, ay in ((10.0, 0.0, 0.0), (-10.0, 0.0, 0.0),
                       (10.0, 3.0, -7.0), (NAN, 0.0, 0.0)):
        for mask in range(8):
            out.append("q|zbox")
            out += [BOX(*bx) for k, bx in enumerate(boxes) if mask >> k & 1]
            out += [POS(0.0, 0.0, 50.0), "set|yaw|%s" % F(0.0),
                    "set|speed|%s" % F(sp), ACC(ax, ay), "momentum"]
    for _ in range(150):
        out.append("q|zbox")
        for _ in range(rng.randrange(0, 4)):
            x0, y0 = rng.uniform(-12, 12), rng.uniform(-12, 12)
            out.append(BOX(x0, y0, x0 + rng.uniform(0, 10),
                           y0 + rng.uniform(0, 10)))
        out += [POS(rng.uniform(-3, 3), rng.uniform(-3, 3), 50.0),
                "set|yaw|%s" % F(rng.choice((0.0, 90.0, 180.0,
                                             rng.uniform(0, 360)))),
                "set|speed|%s" % F(rng.uniform(-20, 60)),
                ACC(rng.uniform(-120, 20), rng.uniform(-40, 40)),
                "momentum"]
    out.append("q|zbox")
    # CalcChopperRotation and SubtractFromYaw.
    for step in (1.0, 0.0, 5.0, -1.0, 0.25, NAN):
        for to, cur in ((10.0, 0.0), (0.0, 10.0), (3.0, 3.0), (-5.0, 5.0),
                        (0.5, 0.0), (0.0, 0.5), (1.0, 0.0), (NAN, 0.0),
                        (0.0, NAN), (-0.0, 0.0), (0.0, -0.0)):
            out.append("calcrot|%s|%s|%s" % (F(step), F(to), F(cur)))
    for yaw in (0.0, 10.0, 350.0, 359.0, 360.0, 180.0):
        for f in (0.0, 10.0, -10.0, 360.0, -0.0, 370.0, -360.5, 1e-3, -1e-3,
                  180.0, NAN):
            out += ["set|yaw|%s" % F(yaw), "subyaw|%s" % F(f)]
    out.append("del|3")
    return out


def fly_think(rng):
    out = ["new", "set|car|C1", "set|chop|R0|P1", "set|target|R0|P2",
           "q|near|1|R2|P15", "q|carroute|1|R0|P3", "q|ahead|0|P4",
           "width|1|%s|%s" % (F(4.0), F(6.0)), "q|elev|%s|3" % F(4.5),
           "q|cmp|%s" % F(-12.0)] + plans_world()
    # AT_STAKEOUT off the sheet: the target is the car's spot, here the car
    # itself, round the helicopter at (10, 20) every 3 degrees, 40 away and
    # 4 away.
    out += ["q|zbox", "carvel|1|%s|%s|%s" % (F(0.0), F(0.0), F(0.0))]
    for deg in range(0, 360, 3):
        for r, speeds in ((40.0, (0.0, 0.001, 0.0015, 10.0, -0.0015,
                                  -10.0)),
                          (4.0, (0.0, 0.0015, -0.0015))):
            for sp in speeds:
                c = math.cos(math.radians(deg))
                s = math.sin(math.radians(deg))
                out += [CARH(1, 10.0 + r * c, 20.0 + r * s, 16384),
                        "set|plan|2", "set|timeout|%s" % F(5.0),
                        "set|chop|R0|P1", POS(10.0, 20.0, 30.0),
                        "set|yaw|%s" % F((0.0, 30.0, 250.0)[deg % 3]),
                        "set|speed|%s" % F(sp), ACC(0.0, 0.0), "set|mm|7",
                        "set|rot|%s" % F(1.25), "set|droll|%s" % F(-3.0),
                        "think"]
    # The plans' 1: START_CHASE off the sheet, END_CHASE high enough to go.
    out += [CARH(1, 50.0, 60.0, 0), "set|plan|3", "set|mm|7", "think",
            BOX(-1e9, -1e9, 1e9, 1e9, 30.0, 0), "set|plan|5",
            POS(-30.0, 7.0, 180.0), "set|mm|7", "think", "q|zbox"]
    # Mixed.
    for _ in range(250):
        plan = rng.choice((0, 0, 1, 2, 3, 4, 5, 6))
        out.append("q|zbox")
        bx = rng.random()
        if bx < 0.5:
            out.append(BOX(-1e9, -1e9, 1e9, 1e9, rng.uniform(-200, 200),
                           rng.choice((0, 0, 1, 2, 3))))
        elif bx < 0.8:
            x0, y0 = rng.uniform(-60, 60), rng.uniform(-60, 60)
            out.append(BOX(x0, y0, x0 + rng.uniform(0, 60),
                           y0 + rng.uniform(0, 60), rng.uniform(0, 80),
                           rng.choice((0, 1, 2))))
        r, c = rng.choice(((0, 1), (1, 8), (3, 20), (0, 2)))
        x, y = PP(c)
        out += [CARH(1, rng.uniform(-80, 80), rng.uniform(-80, 80),
                     rng.randrange(65536)),
                "carvel|1|%s|%s|%s" % (F(rng.uniform(-60, 60)),
                                       F(rng.uniform(-60, 60)),
                                       F(rng.uniform(-5, 5))),
                "q|carroute|1|%s" % rng.choice(("R0|P3", "R0|P2", "R1|P8",
                                                "R3|P20", "R2|P13",
                                                "NULL|P3")),
                "q|ahead|%d|%s" % (rng.randrange(NROUTES),
                                   rng.choice(("NULL", "P4", "P9", "P22"))),
                "q|cmp|%s" % F(rng.choice((-12.0, 5.0))),
                "q|elev|%s|2" % F(rng.choice((4.5, 15.0, 25.0))),
                "set|chop|R%d|P%d" % (r, c), "set|plan|%d" % plan,
                "set|timeout|%s" % F(rng.choice((0.05, 0.1, 3.0, 30.0))),
                "set|zv|%s" % F(rng.choice((0.0, 0.0, 4.0))),
                "set|speed|%s" % F(rng.choice((0.0, 0.0005, 25.0, 300.0))),
                ACC(rng.uniform(-60, 20), rng.uniform(-30, 30)),
                "set|yaw|%s" % F(rng.uniform(0, 360)),
                "set|bomb|%d" % rng.randrange(5),
                "set|salvos|%d" % rng.randrange(0, 3),
                "set|nsalvo|%s" % F(rng.choice((0.05, 0.5))),
                "set|td|%s" % F(rng.uniform(-20, 300)),
                "set|old|%s" % rng.choice(("R0|P3", "R0|P1", "R1|P9")),
                POS(x + rng.uniform(-40, 40), y + rng.uniform(-40, 40),
                    rng.uniform(5, 200)), "set|mm|7", "think"]
    out += ["q|zbox", "set|car|C1", "del|3"]
    return out


def flying(rng):
    return (fly_angles() + fly_accel() + fly_hover() + fly_momentum(rng)
            + fly_think(rng))


def script():
    rng = random.Random(0xc40)
    return (setup() + life() + follows() + attacks(rng) + shifts()
            + spots() + world_ops(rng) + routes() + matrices(rng)
            + chase(random.Random(0x3a)) + plans(random.Random(0x3b))
            + flying(random.Random(0x4a)))


# ================================================================= running

def build_harness(tmp, name="chopper_test"):
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


def write_inputs(d):
    lines = script()
    sc = Path(d) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    return lines, sc


# ============================================================= mutations

C = CHOP
CH = "3DS Files/source/chopper.h"
U = COPUTIL
MUTATIONS = [
    # ---- the constructor
    ("ctor_topo", C, "    topology_init(&h->TopologyCoord);\n", ""),
    ("ctor_dust_next", C, "h->DustEmitters.next = &h->DustEmitters;",
     "h->DustEmitters.next = NULL;"),
    ("ctor_dust_prev", C, "h->DustEmitters.prev = &h->DustEmitters;",
     "h->DustEmitters.prev = NULL;"),
    ("ctor_tp", C, "    trackpath_coord_init(&h->TP);\n", ""),
    ("ctor_wo_name", C, '"TRACK_HELICOPTER"', '"TRACK_HELICOPTERS"'),
    ("ctor_wo_matrix", C, "bchunk_hash(\"TRACK_HELICOPTER\"),\n"
     "                                        NULL, 1);",
     "bchunk_hash(\"TRACK_HELICOPTER\"),\n"
     "                                        &h->Matrix, 1);"),
    ("ctor_wo_light", C, "                                        NULL, 1);",
     "                                        NULL, 0);"),
    ("ctor_wo_store", C, "h->WorldObj = worldobject_construct(wo,",
     "h->WorldObj = wo; (void)worldobject_construct(wo + 1,"),
    ("ctor_sound", C, "? gCreateChopperSoundFn(h) : NULL;", "? NULL : NULL;"),
    ("ctor_dust_hash", C, '"XEM_HELI_DUST"', '"XEM_HELI_DUSTS"'),
    ("ctor_clear", C, "    chopper_clear_variables(h);\n    h->Plan", "    h->Plan"),
    ("ctor_plan", C, "h->Plan = CHOPPLAN_EATING_DONUTS;\n    if (TheRace",
     "h->Plan = CHOPPLAN_END_CHASE;\n    if (TheRace"),
    ("ctor_aidemo", C, "if (TheRaceParameters.AIDemoMode == 0\n        && ",
     "if ("),
    ("ctor_replay", C, "        && TheRaceParameters.ReplayDemoMode == 0\n", ""),
    ("ctor_egg_num", C, "gEggIsOnFn(EGG_HELICOPTER)",
     "gEggIsOnFn(EGG_HELICOPTER + 1)"),
    ("ctor_egg_test", C, "gEggIsOnFn(EGG_HELICOPTER) != 0)",
     "gEggIsOnFn(EGG_HELICOPTER) == 0)"),
    ("ctor_n960", C, "        h->New960 = 1;\n    return h;",
     "        h->New960 = 2;\n    return h;"),
    # ---- the destructor
    ("dtor_afx", C, "    afx_delete_emitters(&h->DustEmitters);\n", ""),
    ("dtor_snd_slot", C, "sound_slot(h, CHOPPERSOUND_VT_DTOR)",
     "sound_slot(h, CHOPPERSOUND_VT_MUTE)"),
    ("dtor_snd_flags", C, "vt_this(h->pChopperSound, e), 3);",
     "vt_this(h->pChopperSound, e), 1);"),
    ("dtor_wo_flags", C, "worldobject_destruct(h->WorldObj, 3);",
     "worldobject_destruct(h->WorldObj, 1);"),
    ("dtor_topo", C, "    topology_destroy(&h->TopologyCoord);\n", ""),
    ("dtor_free", C, "if (flags & 1)\n        bFree(h);",
     "if (flags & 2)\n        bFree(h);"),
    # ---- ClearVariables
    ("clr_think", C, "    h->TimeUntilThink = 0.0f;\n    h->CurrentPos.x",
     "    h->CurrentPos.x"),
    ("clr_posx", C, "    h->CurrentPos.x = 0.0f;\n", ""),
    ("clr_car", C, "    h->CurrentCar = NULL;\n    h->MoveMode",
     "    h->MoveMode"),
    ("clr_mm", C, "h->MoveMode = CHOPMOVE_PURSUIT;\n    h->TargetRoute",
     "h->MoveMode = CHOPMOVE_ROTATE;\n    h->TargetRoute"),
    ("clr_tr", C, "    h->TargetRoute = NULL;\n    h->TargetPoint = NULL;\n",
     "    h->TargetPoint = NULL;\n"),
    ("clr_tp", C, "    h->TargetPoint = NULL;\n    h->ChopperRoute = NULL;\n",
     "    h->ChopperRoute = NULL;\n"),
    ("clr_cr", C, "    h->ChopperRoute = NULL;\n    h->ChopperPoint = NULL;\n",
     "    h->ChopperPoint = NULL;\n"),
    ("clr_cp", C, "    h->ChopperPoint = NULL;\n    h->OldCarRoute = NULL;\n",
     "    h->OldCarRoute = NULL;\n"),
    ("clr_or", C, "    h->OldCarRoute = NULL;\n", ""),
    ("clr_op", C, "    h->OldCarPoint = NULL;\n", ""),
    ("clr_posy", C, "    h->CurrentPos.y = 0.0f;\n", ""),
    ("clr_posz", C, "    h->CurrentPos.z = 0.0f;\n", ""),
    ("clr_ident", C, "    bIdentity(&h->Matrix);\n", ""),
    ("clr_tp_reset", C, "    trackpath_coord_reset_position(&h->TP, (const "
     "bVector2 *)&h->CurrentPos);\n    h->New960", "    h->New960"),
    ("clr_n960", C, "    h->New960 = 0;\n", ""),
    ("clr_timeout", C, "    h->Timeout = CHOPPER_TIMEOUT;\n    h->Speed",
     "    h->Speed"),
    ("clr_timeout_val", CH, "#define CHOPPER_TIMEOUT 25.0f",
     "#define CHOPPER_TIMEOUT 25.5f"),
    ("clr_speed", C, "    h->Speed = 0.0f;\n    h->Acceleration.x",
     "    h->Acceleration.x"),
    ("clr_accx", C, "    h->Acceleration.x = 0.0f;\n", ""),
    ("clr_accy", C, "    h->Acceleration.y = 0.0f;\n    h->Roll", "    h->Roll"),
    ("clr_roll", C, "    h->Roll = 0.0f;\n    h->DesiredRoll = 0.0f;\n"
     "    h->Yaw", "    h->DesiredRoll = 0.0f;\n    h->Yaw"),
    ("clr_droll", C, "    h->DesiredRoll = 0.0f;\n    h->Yaw", "    h->Yaw"),
    ("clr_yaw", C, "    h->Yaw = 0.0f;\n", ""),
    ("clr_pitch", C, "    h->Pitch = 0.0f;\n    h->DesiredPitch = 0.0f;\n"
     "    h->RotRate", "    h->DesiredPitch = 0.0f;\n    h->RotRate"),
    ("clr_dpitch", C, "    h->DesiredPitch = 0.0f;\n    h->RotRate",
     "    h->RotRate"),
    ("clr_rot", C, "    h->RotRate = 0.0f;\n", ""),
    ("clr_zv", C, "    h->ZVelocity = 0.0f;\n", ""),
    ("clr_gz", C, "    h->GroundZ = 0.0f;\n", ""),
    ("clr_dust", C, "    h->EmitDust = 0;\n", ""),
    ("clr_td", C, "    h->TargetDistance = 0.0f;\n", ""),
    ("clr_bomb", C, "h->BombRunType = CHOPATTACK_ROCKET;",
     "h->BombRunType = CHOPATTACK_SMOKE_BOMB_1;"),
    ("clr_salvos", C, "    h->NumSalvosReleased = 0;\n    h->NextLauncher",
     "    h->NextLauncher"),
    ("clr_launcher", C, "    h->NextLauncher = 0;\n", ""),
    ("clr_nsalvo", C, "    h->TimeUntilNextSalvo = 0.0f;\n    h->TotalSalvos",
     "    h->TotalSalvos"),
    ("clr_total", C, "    h->TotalSalvos = 0;\n", ""),
    ("clr_stuck", C, "    h->StuckTime = 0.0f;\n", ""),
    # ---- FollowThisCar
    ("fol_n960", C, "if (h->New960 != 0)", "if (h->New960 == 0)"),
    ("fol_table", C, "car = pCurrentWorld->CarTable[0];",
     "car = pCurrentWorld->CarTable[1];"),
    ("fol_sheet", C, "if (TheHeliSheet == NULL || !signposts_present())",
     "if (!signposts_present())"),
    ("fol_signs", C, "if (TheHeliSheet == NULL || !signposts_present())",
     "if (TheHeliSheet == NULL)"),
    ("fol_order", C, "if (TheHeliSheet == NULL || !signposts_present())",
     "if (!signposts_present() || TheHeliSheet == NULL)"),
    ("fol_null", C, "    if (car == NULL) {", "    if (car != NULL) {"),
    ("fol_start", C, "if (h->Plan == CHOPPLAN_START_CHASE\n"
     "            || h->Plan == CHOPPLAN_EATING_DONUTS) {",
     "if (h->Plan == CHOPPLAN_EATING_DONUTS) {"),
    ("fol_donuts", C, "if (h->Plan == CHOPPLAN_START_CHASE\n"
     "            || h->Plan == CHOPPLAN_EATING_DONUTS) {",
     "if (h->Plan == CHOPPLAN_START_CHASE) {"),
    ("fol_nullcar", C, "            h->CurrentCar = NULL;\n", ""),
    ("fol_eat", C, "            h->Plan = CHOPPLAN_EATING_DONUTS;\n"
     "        } else {", "            h->Plan = CHOPPLAN_START_CHASE;\n"
     "        } else {"),
    ("fol_end", C, "h->Plan = CHOPPLAN_END_CHASE;",
     "h->Plan = CHOPPLAN_PURSUIT;"),
    ("fol_ne_eat", C, "if (h->Plan != CHOPPLAN_EATING_DONUTS\n"
     "            && h->Plan != CHOPPLAN_START_CHASE)",
     "if (h->Plan != CHOPPLAN_START_CHASE)"),
    ("fol_ne_start", C, "if (h->Plan != CHOPPLAN_EATING_DONUTS\n"
     "            && h->Plan != CHOPPLAN_START_CHASE)",
     "if (h->Plan != CHOPPLAN_EATING_DONUTS)"),
    ("fol_ret0", C, "            return 0;\n        h->CurrentCar = car;",
     "            return 1;\n        h->CurrentCar = car;"),
    ("fol_setcar", C, "        h->CurrentCar = car;\n", ""),
    ("fol_plan", C, "h->Plan = CHOPPLAN_START_CHASE;\n    }",
     "h->Plan = CHOPPLAN_HEAD_TO_STAKEOUT;\n    }"),
    ("fol_think", C, "    h->TimeUntilThink = 0.0f;\n    return 1;",
     "    h->TimeUntilThink = 1.0f;\n    return 1;"),
    ("fol_ret1", C, "    h->TimeUntilThink = 0.0f;\n    return 1;",
     "    h->TimeUntilThink = 0.0f;\n    return 2;"),
    ("fol_ret_early", C, "if (TheHeliSheet == NULL || !signposts_present())\n"
     "        return 0;", "if (TheHeliSheet == NULL || !signposts_present())\n"
     "        return 1;"),
    # ---- AttackCar
    ("att_plan", C, "if (h->Plan != CHOPPLAN_PURSUIT) {",
     "if (h->Plan != CHOPPLAN_HEAD_TO_STAKEOUT) {"),
    ("att_car", C, "        if (h->CurrentCar != NULL)\n",
     "        if (h->CurrentCar != NULL && h->Plan != 4)\n"),
    ("att_no_follow", C, "            chopper_follow_this_car(h, h->CurrentCar);"
     "\n", ""),
    ("att_ret0", C, "        return 0;\n    }\n    h->TimeUntilNextSalvo",
     "        return 1;\n    }\n    h->TimeUntilNextSalvo"),
    ("att_salvo", C, "h->TimeUntilNextSalvo = 0.0f;\n    h->Timeout",
     "h->TimeUntilNextSalvo = 1.0f;\n    h->Timeout"),
    ("att_timeout", C, "h->Timeout = CHOPPER_TIMEOUT;\n    car",
     "h->Timeout = 0.0f;\n    car"),
    ("att_dx", C, "dx = car->State.Position.x - h->CurrentPos.x;",
     "dx = car->State.Position.x + h->CurrentPos.x;"),
    ("att_dy", C, "dy = car->State.Position.y - h->CurrentPos.y;",
     "dy = car->State.Position.x - h->CurrentPos.y;"),
    ("att_plan4", C, "h->Plan = CHOPPLAN_BOMBING_RUN;",
     "h->Plan = CHOPPLAN_END_CHASE;"),
    ("att_type", C, "h->BombRunType = type;", "h->BombRunType = type & 3;"),
    ("att_salvos", C, "h->NumSalvosReleased = 0;\n    h->TargetDistance",
     "h->NumSalvosReleased = 1;\n    h->TargetDistance"),
    ("att_sqrt", C, "h->TargetDistance = sqrtf(dx * dx + dy * dy);",
     "h->TargetDistance = (dx * dx + dy * dy);"),
    ("att_behind", C, "if (chopper_behind_car(h))\n",
     "if (!chopper_behind_car(h))\n"),
    ("att_neg", C, "h->TargetDistance = -h->TargetDistance;",
     "h->TargetDistance = h->TargetDistance;"),
    ("att_tr", C, "h->TargetDistance;\n    h->TargetRoute = h->ChopperRoute;",
     "h->TargetDistance;\n    h->TargetRoute = NULL;"),
    ("att_oldr", C, "h->OldCarRoute = car_get_route(h->CurrentCar, FIND_ROUTE);",
     "h->OldCarRoute = car_get_route(h->CurrentCar, 0);"),
    ("att_oldp", C, "h->OldCarPoint = car_get_route_point(h->CurrentCar, "
     "FIND_ROUTE);", "h->OldCarPoint = car_get_route_point(h->CurrentCar, 0);"),
    ("att_adjust", C, "    chopper_adjust_bomb_target(h);\n    return 1;",
     "    return 1;"),
    ("att_ret1", C, "    chopper_adjust_bomb_target(h);\n    return 1;",
     "    chopper_adjust_bomb_target(h);\n    return 2;"),
    # ---- AdjustBombTarget
    ("adj_type", C, "&BombRunBehaviours[h->BombRunType];\n    float ahead",
     "&BombRunBehaviours[h->BombRunType & 3];\n    float ahead"),
    ("adj_ahead", C, "b->Ahead * h->CurrentCar->State.VelocityMagnitude",
     "b->Ahead + h->CurrentCar->State.VelocityMagnitude"),
    ("adj_min_cmp", C, "if (ahead < BOMB_MIN_AHEAD)",
     "if (ahead > BOMB_MIN_AHEAD)"),
    ("adj_min_val", C, "#define BOMB_MIN_AHEAD     100.0f",
     "#define BOMB_MIN_AHEAD     100.5f"),
    ("adj_slack", C, "#define BOMB_TARGET_SLACK  24.0f",
     "#define BOMB_TARGET_SLACK  24.5f"),
    ("adj_le", C, "if (h->TargetDistance + BOMB_TARGET_SLACK < ahead) {",
     "if (h->TargetDistance + BOMB_TARGET_SLACK <= ahead) {"),
    ("adj_sub", C, "if (h->TargetDistance + BOMB_TARGET_SLACK < ahead) {",
     "if (h->TargetDistance - BOMB_TARGET_SLACK < ahead) {"),
    ("adj_nan", C, "if (h->TargetDistance + BOMB_TARGET_SLACK < ahead) {",
     "if (!(ahead <= h->TargetDistance + BOMB_TARGET_SLACK)) {"),
    ("adj_shift", C, "chopper_shift_target(h, ahead);",
     "chopper_shift_target(h, ahead + 1.0f);"),
    ("adj_spot", C, "        chopper_find_unobstructed_spot(h);\n    }\n}",
     "    }\n}"),
    ("tab_ahead0", C, "{ CM_ROCKET,         2.0f,",
     "{ CM_ROCKET,         2.5f,"),
    ("tab_ahead1", C, "{ CM_SMOKEBOMB,      2.0f,",
     "{ CM_SMOKEBOMB,      2.5f,"),
    ("tab_ahead2", C, "{ CM_SMOKEBOMB,      1.5f,",
     "{ CM_SMOKEBOMB,      1.75f,"),
    ("tab_ahead3", C, "{ CM_DROPPED_SPIKES, 2.0f,",
     "{ CM_DROPPED_SPIKES, 2.5f,"),
    ("tab_ahead4", C, "{ CM_DROPPED_SPIKES, 1.0f,",
     "{ CM_DROPPED_SPIKES, 1.25f,"),
    # ---- ShiftTarget
    ("sh_route_flag", C, "TrackRoute *route = car_get_route(h->CurrentCar, "
     "FIND_ROUTE);", "TrackRoute *route = car_get_route(h->CurrentCar, 0);"),
    ("sh_point_flag", C, "TrackRoutePoint *point = car_get_route_point("
     "h->CurrentCar, FIND_ROUTE);",
     "TrackRoutePoint *point = car_get_route_point(h->CurrentCar, 0);"),
    ("sh_count", C, "ai_guess_target_destinations(out, 5,",
     "ai_guess_target_destinations(out, 4,"),
    ("sh_slack", C, "dist + BOMB_TARGET_SLACK, 1);", "dist, 1);"),
    ("sh_fwd", C, "dist + BOMB_TARGET_SLACK, 1);",
     "dist + BOMB_TARGET_SLACK, 0);"),
    ("sh_td", C, "h->TargetDistance = dist;\n",
     "h->TargetDistance = dist + 1.0f;\n"),
    ("sh_bit", C, "(out[i].Point->Bits & TRP_NO_HELISHEET) == 0",
     "(out[i].Point->Bits & TRP_NO_HELISHEET) != 0"),
    ("sh_tp", C, "h->TargetPoint = out[i].Point;",
     "h->TargetPoint = out[0].Point;"),
    ("sh_tr", C, "h->TargetRoute = out[i].Route;",
     "h->TargetRoute = out[0].Route;"),
    ("sh_noreturn", C, "            h->TargetRoute = out[i].Route;\n"
     "            return;\n", "            h->TargetRoute = out[i].Route;\n"),
    ("sh_loop", C, "for (i = 0; i < n; i++) {",
     "for (i = 0; i + 1 < n; i++) {"),
    # ---- FindUnobstructedSpot
    ("sp_route", C, "info.Route = h->TargetRoute;",
     "info.Route = h->ChopperRoute;"),
    ("sp_sheet", C, "        helisheet_find_z_value(TheHeliSheet,\n",
     "        helisheet_find_z_value(NULL,\n"),
    ("sp_bit", C, "if ((flags & 1) == 0)", "if ((flags & 3) == 0)"),
    ("sp_flags0", C, "    uint32_t flags = 0;\n\n",
     "    uint32_t flags = 1;\n\n"),
    ("sp_len", C, "h->TargetDistance + info.Point->Length;",
     "h->TargetDistance - info.Point->Length;"),
    ("sp_store_r", C, "    h->TargetRoute = info.Route;\n"
     "    h->TargetPoint = info.Point;\n}",
     "    h->TargetPoint = info.Point;\n}"),
    ("sp_store_p", C, "    h->TargetRoute = info.Route;\n"
     "    h->TargetPoint = info.Point;\n}",
     "    h->TargetRoute = info.Route;\n}"),
    # ---- AbortBombingRun
    ("ab_cmp", C, "if (h->Plan == CHOPPLAN_BOMBING_RUN)\n"
     "        h->Plan = CHOPPLAN_PURSUIT;",
     "if (h->Plan != CHOPPLAN_BOMBING_RUN)\n        h->Plan = CHOPPLAN_PURSUIT;"),
    ("ab_val", C, "if (h->Plan == CHOPPLAN_BOMBING_RUN)\n"
     "        h->Plan = CHOPPLAN_PURSUIT;",
     "if (h->Plan == CHOPPLAN_BOMBING_RUN)\n        h->Plan = CHOPPLAN_END_CHASE;"),
    # ---- FindGroundHeight
    ("gr_x", C, "pt.x = h->CurrentPos.x;", "pt.x = h->CurrentPos.y;"),
    ("gr_y", C, "pt.y = h->CurrentPos.y;", "pt.y = h->CurrentPos.x;"),
    ("gr_z", C, "pt.z = h->GroundZ;", "pt.z = h->CurrentPos.z;"),
    ("gr_store", C, "h->GroundZ = topology_get_elevation(",
     "(void)topology_get_elevation("),
    ("gr_ret", C, "    return terrain;", "    return terrain + 1;"),
    # ---- Place and Remove
    ("pl_act", C, "    sound_activate(h, 1);\n", "    sound_activate(h, 0);\n"),
    ("pl_x", C, "h->CurrentPos.x = pos->x;", "h->CurrentPos.x = pos->y;"),
    ("pl_z", C, "h->CurrentPos.z = z;", "h->CurrentPos.z = z + 1.0f;"),
    ("pl_pitch", C, "    h->Pitch = 0.0f;\n    h->DesiredPitch = 0.0f;\n"
     "    h->Roll = 0.0f;", "    h->DesiredPitch = 0.0f;\n    h->Roll = 0.0f;"),
    ("pl_dpitch", C, "    h->DesiredPitch = 0.0f;\n    h->Roll = 0.0f;",
     "    h->Roll = 0.0f;"),
    ("pl_roll", C, "    h->Roll = 0.0f;\n    h->DesiredRoll = 0.0f;\n"
     "    h->Speed", "    h->DesiredRoll = 0.0f;\n    h->Speed"),
    ("pl_droll", C, "    h->DesiredRoll = 0.0f;\n    h->Speed = 0.0f;\n"
     "    h->CurrentPos.y", "    h->Speed = 0.0f;\n    h->CurrentPos.y"),
    ("pl_speed", C, "    h->Speed = 0.0f;\n    h->CurrentPos.y",
     "    h->CurrentPos.y"),
    ("pl_y", C, "h->CurrentPos.y = pos->y;", "h->CurrentPos.y = pos->x;"),
    ("pl_yaw", C, "h->CurrentCar->State.Angle * 0.0054931640625f",
     "h->CurrentCar->State.Angle * 0.0055f"),
    ("pl_tp", C, "    trackpath_coord_reset_position(&h->TP, (const bVector2 "
     "*)&h->CurrentPos);\n    topology_set", "    topology_set"),
    ("pl_bbox_r", C, "(const bVector2 *)&h->CurrentPos, 1.0f, NULL);",
     "(const bVector2 *)&h->CurrentPos, 2.0f, NULL);"),
    ("pl_bbox", C, "    topology_set_interest_bbox(&h->TopologyCoord,\n"
     "                               (const bVector2 *)&h->CurrentPos, 1.0f, "
     "NULL);\n", ""),
    ("pl_gz", C, "h->GroundZ = h->CurrentCar->State.Position.z;",
     "h->GroundZ = h->CurrentCar->State.Position.y;"),
    ("pl_ground", C, "    chopper_find_ground_height(h);\n"
     "    chopper_find_point_from_scratch(h);\n    chopper_calc_matrix(h);",
     "    chopper_find_point_from_scratch(h);\n    chopper_calc_matrix(h);"),
    ("pl_scratch", C, "    chopper_find_point_from_scratch(h);\n"
     "    chopper_calc_matrix(h);", "    chopper_calc_matrix(h);"),
    ("pl_matrix", C, "    chopper_find_point_from_scratch(h);\n"
     "    chopper_calc_matrix(h);", "    chopper_find_point_from_scratch(h);"),
    ("rm_en", C, "h->WorldObj->Enabled = 0;", "h->WorldObj->Enabled = 2;"),
    ("rm_act", C, "    sound_activate(h, 0);\n", "    sound_activate(h, 1);\n"),
    ("rm_clear", C, "    topology_clear_interest_bbox(&h->TopologyCoord);\n",
     ""),
    # ---- the sound
    ("snd_act_slot", C, "e = sound_slot(h, CHOPPERSOUND_VT_ACTIVATE);",
     "e = sound_slot(h, CHOPPERSOUND_VT_MUTE);"),
    ("snd_act_arg", C, "vt_this(h->pChopperSound, e), on);",
     "vt_this(h->pChopperSound, e), !on);"),
    ("mu_slot", C, "sound_slot(h, CHOPPERSOUND_VT_MUTE)",
     "sound_slot(h, CHOPPERSOUND_VT_ACTIVATE)"),
    ("mu_arg", C, "vt_this(h->pChopperSound, e), i);",
     "vt_this(h->pChopperSound, e), i + 1);"),
    ("us_a", C, "1.0f, 0, 1.0f);", "0.5f, 0, 1.0f);"),
    ("us_b", C, "1.0f, 0, 1.0f);", "1.0f, 1, 1.0f);"),
    ("us_c", C, "1.0f, 0, 1.0f);", "1.0f, 0, 0.5f);"),
    # ---- BehindCar, Rotate, MaxDeceleration
    ("be_a", C, "&TheTrackPathManager, h->TP.DistanceAroundTrack,",
     "&TheTrackPathManager, h->TP.RatioAroundTrack,"),
    ("be_b", C, "h->CurrentCar->TheTrackPathCoordinate.DistanceAroundTrack)",
     "h->CurrentCar->TheTrackPathCoordinate.RatioAroundTrack)"),
    ("be_lt", C, "           <= 0.0f;", "           < 0.0f;"),
    ("be_ge", C, "           <= 0.0f;", "           >= 0.0f;"),
    ("rot_360", C, "rotate_vector(out, v, 360.0f - h->Yaw);",
     "rotate_vector(out, v, h->Yaw);"),
    ("de_cmp", C, "(uint32_t)(h->Plan - 1) < 2u", "(uint32_t)(h->Plan - 1) < 3u"),
    ("de_sub", C, "(uint32_t)(h->Plan - 1) < 2u", "(uint32_t)(h->Plan - 2) < 2u"),
    ("de_signed", C, "(uint32_t)(h->Plan - 1) < 2u", "(h->Plan - 1) < 2"),
    ("de_a", C, "return -120.0f;", "return -121.0f;"),
    ("de_b", C, "return -60.0f;", "return -61.0f;"),
    # ---- the route points
    ("sc_which", C, "ALL_RACING_ROUTES, ROUTE_FLAGS,",
     "(RoutesToSearch)(ALL_RACING_ROUTES + 1), ROUTE_FLAGS,"),
    ("sc_flags", C, "#define ROUTE_FLAGS        6", "#define ROUTE_FLAGS        7"),
    ("sc_dist", C, "                                   0.0f)) {",
     "                                   1.0f)) {"),
    ("sc_r", C, "        h->ChopperRoute = info.Route;\n"
     "        h->ChopperPoint = info.Point;\n",
     "        h->ChopperPoint = info.Point;\n"),
    ("sc_p", C, "        h->ChopperRoute = info.Route;\n"
     "        h->ChopperPoint = info.Point;\n",
     "        h->ChopperRoute = info.Route;\n"),
    ("rp_radius", C, "#define ROUTE_POINT_RADIUS 24.0f",
     "#define ROUTE_POINT_RADIUS 25.0f"),
    ("rp_dist", C, "ROUTE_POINT_RADIUS, ROUTE_FLAGS, 0.0f);\n    if (p == NULL &&",
     "ROUTE_POINT_RADIUS, ROUTE_FLAGS, 1.0f);\n    if (p == NULL &&"),
    ("rp_nosign", C, "if (p == NULL && trpoint_has_signpost(h->ChopperPoint)) {",
     "if (p == NULL) {"),
    ("rp_sign", C, "if (p == NULL && trpoint_has_signpost(h->ChopperPoint)) {",
     "if (p == NULL && !trpoint_has_signpost(h->ChopperPoint)) {"),
    ("rp_null", C, "if (p == NULL && trpoint_has_signpost(h->ChopperPoint)) {",
     "if (trpoint_has_signpost(h->ChopperPoint)) {"),
    ("rp_route2", C, "        p = troute_find_closest_point(route,\n",
     "        p = troute_find_closest_point(h->ChopperRoute,\n"),
    ("rp_scratch", C, "    if (p == NULL) {\n"
     "        chopper_find_point_from_scratch(h);\n        return;\n    }\n",
     "    if (p == NULL)\n        return;\n"),
    ("rp_p", C, "    h->ChopperPoint = p;\n    h->ChopperRoute = route;",
     "    h->ChopperRoute = route;"),
    ("rp_r", C, "    h->ChopperPoint = p;\n    h->ChopperRoute = route;",
     "    h->ChopperPoint = p;"),
    # ---- CalcMatrix and the WorldObject
    ("mx_scale", C, "#define CHOPPER_SCALE      1.1f",
     "#define CHOPPER_SCALE      1.0f"),
    ("mx_raise", C, "#define CHOPPER_RAISE      2.3f",
     "#define CHOPPER_RAISE      2.0f"),
    ("mx_180", C, "yaw = 180.0f - h->Yaw;", "yaw = h->Yaw - 180.0f;"),
    ("mx_v0", C, "m.v0.x = CHOPPER_SCALE;", "m.v0.x = 1.0f;"),
    ("mx_v1", C, "m.v1.y = CHOPPER_SCALE;", "m.v1.y = 1.0f;"),
    ("mx_v2", C, "m.v2.z = CHOPPER_SCALE;", "m.v2.z = 1.0f;"),
    ("mx_lt", C, "if (yaw < 0.0f)", "if (yaw < 1.0f)"),
    ("mx_wrap", C, "yaw = yaw + 360.0f;", "yaw = yaw + 180.0f;"),
    ("mx_rx", C, "eRotateX(&m, &m, deg_to_bam(h->Roll));",
     "eRotateX(&m, &m, deg_to_bam(-h->Roll));"),
    ("mx_ry", C, "deg_to_bam(360.0f - h->Pitch)", "deg_to_bam(h->Pitch)"),
    ("mx_rz", C, "eRotateZ(&m, &m, deg_to_bam(yaw));",
     "eRotateY(&m, &m, deg_to_bam(yaw));"),
    ("mx_order", C, "    eRotateX(&m, &m, deg_to_bam(h->Roll));\n"
     "    eRotateY(&m, &m, deg_to_bam(360.0f - h->Pitch));\n",
     "    eRotateY(&m, &m, deg_to_bam(360.0f - h->Pitch));\n"
     "    eRotateX(&m, &m, deg_to_bam(h->Roll));\n"),
    ("mx_tx", C, "m.v3.x = h->CurrentPos.x;", "m.v3.x = h->CurrentPos.y;"),
    ("mx_ty", C, "m.v3.y = h->CurrentPos.y;", "m.v3.y = h->CurrentPos.x;"),
    ("mx_tz", C, "m.v3.z = h->CurrentPos.z + CHOPPER_RAISE;",
     "m.v3.z = h->CurrentPos.z;"),
    ("mx_store", C, "    h->Matrix = m;\n", "    h->Matrix.v3 = m.v3;\n"),
    ("mx_bam_div", C, "ee_trunc_w(deg * 65536.0f) / 360)",
     "ee_trunc_w(deg * 65536.0f) / 361)"),
    ("mx_bam_float", C, "(uint16_t)(ee_trunc_w(deg * 65536.0f) / 360)",
     "(uint16_t)ee_trunc_w(deg * (65536.0f / 360.0f))"),
    ("wo_mat", C, "    h->WorldObj->Matrix = h->Matrix;\n", ""),
    ("wo_en", C, "h->WorldObj->Enabled = 1;", "h->WorldObj->Enabled = 2;"),
    # ---- the chase logic's helpers
    ("pi_div", C, "return (int32_t)(d * 0xb6db6db7u) >> 4;",
     "return (int32_t)(d / 112u);"),
    ("pi_ushift", C, "return (int32_t)(d * 0xb6db6db7u) >> 4;",
     "return (int32_t)((d * 0xb6db6db7u) >> 4);"),
    ("dist_dx", C, "float dx = p->x - h->CurrentPos.x;",
     "float dx = p->x - h->CurrentPos.y;"),
    ("dist_dy", C, "float dy = p->y - h->CurrentPos.y;",
     "float dy = p->y - h->CurrentPos.x;"),
    ("dist_sq", C, "return sqrtf(dx * dx + dy * dy);",
     "return sqrtf(dx * dx + dy * dx);"),
    ("dist_sqrt", C, "return sqrtf(dx * dx + dy * dy);",
     "return dx * dx + dy * dy;"),
    # ---- StartChaseLogic
    ("sc_on", C, "if (!on_sheet || (flags & 2))", "if ((flags & 2))"),
    ("sc_f2", C, "if (!on_sheet || (flags & 2))",
     "if (!on_sheet || (flags & 1))"),
    ("sc_height", C, "chopper_place_in_world(h, &t->Location, z + CHASE_HEIGHT);",
     "chopper_place_in_world(h, &t->Location, z);"),
    ("sc_hconst", C, "#define CHASE_HEIGHT       150.0f",
     "#define CHASE_HEIGHT       100.0f"),
    ("sc_plan", C, "    h->Plan = CHOPPLAN_PURSUIT;\n    h->EmitDust",
     "    h->EmitDust"),
    ("sc_dust", C, "(int32_t)((flags ^ 1) & 1)", "(int32_t)(flags & 1)"),
    ("sc_drop", C, "#define CHASE_DROP         -25.0f",
     "#define CHASE_DROP         25.0f"),
    ("sc_ret", C, "    h->ZVelocity = CHASE_DROP;\n    return 0;",
     "    h->ZVelocity = CHASE_DROP;\n    return 1;"),
    # ---- EndChaseLogic
    ("ec_le", C, "if (z + CHASE_HEIGHT <= h->CurrentPos.z)",
     "if (z + CHASE_HEIGHT < h->CurrentPos.z)"),
    ("ec_hgt", C, "if (z + CHASE_HEIGHT <= h->CurrentPos.z)",
     "if (z <= h->CurrentPos.z)"),
    ("ec_remove", C, "            chopper_remove_from_world(h);\n"
     "            h->Plan = CHOPPLAN_EATING_DONUTS;\n",
     "            h->Plan = CHOPPLAN_EATING_DONUTS;\n"),
    ("ec_plan", C, "            h->Plan = CHOPPLAN_EATING_DONUTS;\n"
     "            return 1;", "            return 1;"),
    ("ec_ret1", C, "            h->Plan = CHOPPLAN_EATING_DONUTS;\n"
     "            return 1;",
     "            h->Plan = CHOPPLAN_EATING_DONUTS;\n            return 0;"),
    ("ec_flag2", C, "if (!((flags & 2) && h->ZVelocity == 0.0f))",
     "if (!((flags & 1) && h->ZVelocity == 0.0f))"),
    ("ec_zv", C, "if (!((flags & 2) && h->ZVelocity == 0.0f))",
     "if (!(flags & 2))"),
    ("ec_and", C, "if (!((flags & 2) && h->ZVelocity == 0.0f))",
     "if (!((flags & 2) || h->ZVelocity == 0.0f))"),
    ("ec_climb", C, "#define CHASE_CLIMB        25.0f",
     "#define CHASE_CLIMB        20.0f"),
    ("ec_cx", C, "            t->Location.x = h->CurrentPos.x;\n", ""),
    ("ec_cy", C, "            t->Location.y = h->CurrentPos.y;\n", ""),
    ("ec_climb_ret", C, "            t->Location.y = h->CurrentPos.y;\n"
     "            return 0;", "            t->Location.y = h->CurrentPos.y;\n"
     "            return 1;"),
    ("ec_route", C, "    last.Route = h->ChopperRoute;\n",
     "    last.Route = h->TargetRoute;\n"),
    ("ec_point", C, "    last.Point = h->ChopperPoint;\n",
     "    last.Point = h->TargetPoint;\n"),
    ("ec_last", C, "        last = next;\n        if (END_CHASE_REACH",
     "        if (END_CHASE_REACH"),
    ("ec_reach", C, "if (END_CHASE_REACH < distance_to(h, &last.Point->Position))",
     "if (END_CHASE_REACH > distance_to(h, &last.Point->Position))"),
    ("ec_reachc", C, "#define END_CHASE_REACH    30.0f",
     "#define END_CHASE_REACH    31.0f"),
    ("ec_speed", C, "#define END_CHASE_SPEED    50.0f",
     "#define END_CHASE_SPEED    40.0f"),
    ("ec_lx", C, "    t->Location.x = last.Point->Position.x;\n", ""),
    ("ec_ly", C, "    t->Location.y = last.Point->Position.y;\n", ""),
    ("ec_dspeed", C, "    t->DesiredSpeed = END_CHASE_SPEED;\n", ""),
    # ---- SetFollowSpeed
    ("fs_lead", C, "#define FOLLOW_LEAD        30.0f",
     "#define FOLLOW_LEAD        20.0f"),
    ("fs_vel", C, "h->CurrentCar->State.VelocityMagnitude + FOLLOW_LEAD",
     "FOLLOW_LEAD"),
    # ---- FindPreviousFork
    ("pf_back", C, "int back = b ^ 1;", "int back = b;"),
    ("pf_zero_ret", C, "        if (n == 0)\n            return 0;\n"
     "        count +=", "        if (n == 0)\n"
     "            return (int32_t)count;\n        count +="),
    ("pf_count", C, "        count += (uint32_t)n;\n", ""),
    ("pf_newr", C, "        info->Route = signpost_get_new_route(s);\n", ""),
    ("pf_newp", C, "        info->Point = signpost_get_new_route_point(s);\n",
     ""),
    ("pf_mask", C, "if ((s->Flags & SIGNPOST_SIGN_MASK) != SIGN_ALWAYS_TAKE)",
     "if (s->Flags != SIGN_ALWAYS_TAKE)"),
    ("pf_eq", C, "!= SIGN_ALWAYS_TAKE)\n            return (int32_t)count;",
     "== SIGN_ALWAYS_TAKE)\n            return (int32_t)count;"),
    ("pf_rel_b", C, "info->Point,\n"
     "                                                back);",
     "info->Point,\n                                                b);"),
    ("pf_inc", C, "                                                back);\n"
     "        count++;", "                                                back);"),
    ("pf_rel_skip", C, "        info->Point = troute_get_relative_point("
     "info->Route, info->Point,\n                                                back);\n",
     ""),
    # ---- SwitchToNearbyFork
    ("sw_copy", C, "    *out = *in;\n", ""),
    ("sw_k0r", C, "    if (k == 0)\n        return 0;\n    // `sll`",
     "    if (k == 0)\n        return 1;\n    // `sll`"),
    ("sw_shift", C, "for (k <<= 1; k != 0; k--)", "for (; k != 0; k--)"),
    ("sw_shift2", C, "for (k <<= 1; k != 0; k--)", "for (k <<= 2; k != 0; k--)"),
    ("sw_le", C, "if (distance_to(h, &out->Point->Position) < maxd)",
     "if (distance_to(h, &out->Point->Position) <= maxd)"),
    ("sw_gt", C, "if (distance_to(h, &out->Point->Position) < maxd)",
     "if (distance_to(h, &out->Point->Position) > maxd)"),
    ("sw_rel_b", C, "troute_get_relative_point(out->Route, out->Point, b);",
     "troute_get_relative_point(out->Route, out->Point, b ^ 1);"),
    ("sw_null", C, "        if (out->Point == NULL)\n            return 0;\n", ""),
    ("sw_end", C, "            return 0;\n    }\n    return 0;\n}",
     "            return 0;\n    }\n    return 1;\n}"),
    # ---- TargetChopperPoint
    ("tcp_x", C, "    t->Location.x = h->ChopperPoint->Position.x;\n", ""),
    ("tcp_y", C, "    t->Location.y = h->ChopperPoint->Position.y;\n", ""),
    ("tcp_xy", C, "t->Location.x = h->ChopperPoint->Position.x;",
     "t->Location.x = h->ChopperPoint->Position.y;"),
    # ---- FollowRoute
    ("fr_mind", C, "    float mind = chopper_calc_min_route_follow_distance(h, t);",
     "    float mind = FOLLOW_MIN;"),
    ("fr_far_le", C, "int far = mind < distance_to(h, &h->ChopperPoint->Position);",
     "int far = mind <= distance_to(h, &h->ChopperPoint->Position);"),
    ("fr_far_gt", C, "int far = mind < distance_to(h, &h->ChopperPoint->Position);",
     "int far = mind > distance_to(h, &h->ChopperPoint->Position);"),
    ("fr_eq", C, "if (h->ChopperPoint == point || far)", "if (far)"),
    ("fr_far", C, "if (h->ChopperPoint == point || far)",
     "if (h->ChopperPoint == point)"),
    ("fr_speed", C, "        if (far)\n            chopper_set_follow_speed(h, t);\n",
     "        chopper_set_follow_speed(h, t);\n"),
    ("fr_speed_none", C, "        if (far)\n"
     "            chopper_set_follow_speed(h, t);\n", ""),
    ("fr_start_r", C, "    start.Route = h->ChopperRoute;\n",
     "    start.Route = route;\n"),
    ("fr_start_p", C, "    start.Point = h->ChopperPoint;\n",
     "    start.Point = point;\n"),
    ("fr_tr", C, "    target.Route = route;\n",
     "    target.Route = h->ChopperRoute;\n"),
    ("fr_points", C, "#define FOLLOW_POINTS      5", "#define FOLLOW_POINTS      4"),
    ("fr_fwd", C, "out, FOLLOW_POINTS, fwd, 1);", "out, FOLLOW_POINTS, 1, 1);"),
    ("fr_heli", C, "out, FOLLOW_POINTS, fwd, 1);", "out, FOLLOW_POINTS, fwd, 0);"),
    ("fr_sw_b", C, "chopper_switch_to_nearby_fork(h, &fork, &start, fwd, mind)",
     "chopper_switch_to_nearby_fork(h, &fork, &start, fwd ^ 1, mind)"),
    ("fr_sw_d", C, "chopper_switch_to_nearby_fork(h, &fork, &start, fwd, mind)",
     "chopper_switch_to_nearby_fork(h, &fork, &start, fwd, mind * 2)"),
    ("fr_sw_n", C, "if (n == 0 && chopper_switch", "if (chopper_switch"),
    ("fr_retry", C, "n = ai_find_points_to_target(&fork,",
     "n = ai_find_points_to_target(&start,"),
    ("fr_ret0", C, "    if (n == 0)\n        return;\n    for (i = 0",
     "    for (i = 0"),
    ("fr_pick_pt", C, "        if (out[i].Point == point\n            || mind",
     "        if (mind"),
    ("fr_pick_d", C, "        if (out[i].Point == point\n"
     "            || mind < distance_to(h, &out[i].Point->Position))",
     "        if (out[i].Point == point)"),
    ("fr_pick_lt", C, "|| mind < distance_to(h, &out[i].Point->Position))",
     "|| mind > distance_to(h, &out[i].Point->Position))"),
    ("fr_last", C, "        i = n - 1;", "        i = 0;"),
    ("fr_ne", C, "    if (out[i].Point != point)\n        chopper_set_follow_speed",
     "    if (out[i].Point == point)\n        chopper_set_follow_speed"),
    ("fr_ne_all", C, "    if (out[i].Point != point)\n", ""),
    ("fr_lx", C, "    t->Location.x = out[i].Point->Position.x;\n", ""),
    ("fr_ly", C, "    t->Location.y = out[i].Point->Position.y;\n", ""),
    # ---- BeginStakeout
    ("bs_ir", C, "    info.Route = route;\n    info.Point = point;\n    for (;;",
     "    info.Route = h->ChopperRoute;\n    info.Point = point;\n    for (;;"),
    ("bs_bail", C, "            chopper_bail_to_point_near_chopper(h, t);\n"
     "            return;\n        }\n        if ((info.Point->Bits",
     "            return;\n        }\n        if ((info.Point->Bits"),
    ("bs_heli", C, "if ((info.Point->Bits & TRP_NO_HELISHEET)\n"
     "            || !trpoint_has_signpost(info.Point))",
     "if (!trpoint_has_signpost(info.Point))"),
    ("bs_nostake", C, "        if (s->Flags & SIGNPOST_NO_STAKEOUT)\n"
     "            continue;\n", ""),
    ("bs_nostake_bit", C, "if (s->Flags & SIGNPOST_NO_STAKEOUT)",
     "if (s->Flags & SIGNPOST_BACKWARDS)"),
    ("bs_back", C, "if (s->Flags & SIGNPOST_BACKWARDS) {",
     "if (s->Flags & SIGNPOST_NO_STAKEOUT) {"),
    ("bs_back_not", C, "if (s->Flags & SIGNPOST_BACKWARDS) {",
     "if (!(s->Flags & SIGNPOST_BACKWARDS)) {"),
    ("bs_br", C, "        h->TargetRoute = info.Route;\n", ""),
    ("bs_bp", C, "        h->TargetPoint = info.Point;\n", ""),
    ("bs_nr", C, "        h->TargetRoute = signpost_get_new_route(s);\n", ""),
    ("bs_np", C, "        h->TargetPoint = signpost_get_new_route_point(s);\n", ""),
    ("bs_radius", C, "#define STAKEOUT_RADIUS    400.0f",
     "#define STAKEOUT_RADIUS    300.0f"),
    ("bs_closest_r", C, "c = troute_find_closest_point(h->TargetRoute,",
     "c = troute_find_closest_point(h->ChopperRoute,"),
    # Dropping the check would index NULL, whose value is the harness's
    # memory layout; the mutant takes the other way on NULL instead.
    ("bs_c_null", C, "if (c != NULL && point_index",
     "if (c == NULL || point_index"),
    ("bs_idx_le", C, "                         < point_index(h->TargetRoute, c)",
     "                         <= point_index(h->TargetRoute, c)"),
    ("bs_idx_gt", C, "                         < point_index(h->TargetRoute, c)",
     "                         > point_index(h->TargetRoute, c)"),
    ("bs_cr", C, "        h->TargetRoute = h->ChopperRoute;\n", ""),
    ("bs_cp", C, "        h->TargetPoint = h->ChopperPoint;\n", ""),
    ("bs_tcp", C, "        h->TargetPoint = h->ChopperPoint;\n"
     "        chopper_target_chopper_point(h, t);\n",
     "        h->TargetPoint = h->ChopperPoint;\n"),
    ("bs_plan", C, "    h->Plan = CHOPPLAN_HEAD_TO_STAKEOUT;\n", ""),
    ("bs_timeout", C, "#define STAKEOUT_TIMEOUT   60.0f",
     "#define STAKEOUT_TIMEOUT   50.0f"),
    ("bs_fwd", C, "STAKEOUT_TIMEOUT;\n    chopper_follow_route(h, t, "
     "h->TargetRoute, h->TargetPoint, 1);", "STAKEOUT_TIMEOUT;\n"
     "    chopper_follow_route(h, t, h->TargetRoute, h->TargetPoint, 0);"),
    # ---- HangoutNearHere and BailToPointNearChopper
    ("ho_dx", C, "float dx = t->Location.x - point->Position.x;",
     "float dx = point->Position.x - t->Location.x;"),
    ("ho_dy", C, "float dy = t->Location.y - point->Position.y;",
     "float dy = t->Location.x - point->Position.y;"),
    ("ho_along", C, "dx * point->Direction.x + dy * point->Direction.y;",
     "dx * point->Direction.x - dy * point->Direction.y;"),
    ("ho_dirs", C, "dx * point->Direction.x + dy * point->Direction.y;",
     "dx * point->Direction.y + dy * point->Direction.x;"),
    ("ho_across", C, "(dx * point->Direction.y - dy * point->Direction.x)",
     "(dy * point->Direction.x - dx * point->Direction.y)"),
    ("ho_across_k", C, "- dy * point->Direction.x)\n                   * HANGOUT_SHRINK;",
     "- dy * point->Direction.x);"),
    ("ho_shrink", C, "#define HANGOUT_SHRINK     0.7f",
     "#define HANGOUT_SHRINK     0.75f"),
    ("ho_along_k", C, "        along = along * HANGOUT_SHRINK;\n", ""),
    ("ho_along_75", C, "along = along * HANGOUT_SHRINK;",
     "along = along * 0.75f;"),
    ("ho_across_75", C, "across = across * HANGOUT_SHRINK;",
     "across = across * 0.75f;"),
    ("ho_hit", C, "        if (helisheet_find_z_value(TheHeliSheet, &t->Location, "
     "NULL, NULL))\n            return;\n", ""),
    ("ho_stop_al", C, "if (!(fabsf(along) >= FLT_MIN) && !(fabsf(across) >= FLT_MIN))",
     "if (!(fabsf(along) >= FLT_MIN))"),
    ("ho_stop_ac", C, "if (!(fabsf(along) >= FLT_MIN) && !(fabsf(across) >= FLT_MIN))",
     "if (!(fabsf(across) >= FLT_MIN))"),
    ("ho_stop_or", C, "if (!(fabsf(along) >= FLT_MIN) && !(fabsf(across) >= FLT_MIN))",
     "if (!(fabsf(along) >= FLT_MIN) || !(fabsf(across) >= FLT_MIN))"),
    ("ho_getpos", C, "trpoint_get_position2(point, &t->Location, along, across);",
     "trpoint_get_position2(point, &t->Location, across, along);"),
    ("bail_p", C, "chopper_hangout_near_here(h, t, h->ChopperRoute, h->ChopperPoint);",
     "chopper_hangout_near_here(h, t, h->ChopperRoute, h->TargetPoint);"),
    # ---- CalcMinRouteFollowDistance
    ("cm_scale", C, "#define FOLLOW_SCALE       0.1f",
     "#define FOLLOW_SCALE       0.2f"),
    ("cm_min", C, "#define FOLLOW_MIN         30.0f",
     "#define FOLLOW_MIN         20.0f"),
    ("cm_gt", C, "    if (d < FOLLOW_MIN)\n        d = FOLLOW_MIN;",
     "    if (d > FOLLOW_MIN)\n        d = FOLLOW_MIN;"),
    ("cm_speed", C, "float d = h->Speed * FOLLOW_SCALE;", "float d = h->Speed;"),
    # ---- AdjustTargetInBounds
    ("ib_tries2", C, "#define BOUNDS_TRIES       3u", "#define BOUNDS_TRIES       2u"),
    ("ib_tries4", C, "#define BOUNDS_TRIES       3u", "#define BOUNDS_TRIES       4u"),
    ("ib_probe", C, "#define BOUNDS_PROBE       4.5f",
     "#define BOUNDS_PROBE       4.0f"),
    ("ib_step", C, "#define BOUNDS_STEP        1.5f",
     "#define BOUNDS_STEP        1.0f"),
    ("ib_xm", C, "xm = chopper_test_location(h, t->Location.x - BOUNDS_PROBE,",
     "xm = chopper_test_location(h, t->Location.x + BOUNDS_PROBE,"),
    ("ib_xp", C, "xp = chopper_test_location(h, t->Location.x + BOUNDS_PROBE,",
     "xp = chopper_test_location(h, t->Location.x - BOUNDS_PROBE,"),
    ("ib_yp", C, "t->Location.y + BOUNDS_PROBE);", "t->Location.y - BOUNDS_PROBE);"),
    ("ib_ym", C, "t->Location.y - BOUNDS_PROBE);", "t->Location.y + BOUNDS_PROBE);"),
    ("ib_xm_c", C, "if (xm && !xp) {", "if (xm) {"),
    ("ib_xp_c", C, "} else if (!xm && xp) {", "} else if (xp) {"),
    ("ib_yp_c", C, "if (yp && !ym) {", "if (yp) {"),
    ("ib_ym_c", C, "} else if (!yp && ym) {", "} else if (ym) {"),
    ("ib_xminus", C, "t->Location.x = t->Location.x - BOUNDS_STEP;",
     "t->Location.x = t->Location.x + BOUNDS_STEP;"),
    ("ib_xplus", C, "t->Location.x = t->Location.x + BOUNDS_STEP;",
     "t->Location.x = t->Location.x - BOUNDS_STEP;"),
    ("ib_yplus", C, "t->Location.y = t->Location.y + BOUNDS_STEP;",
     "t->Location.y = t->Location.y - BOUNDS_STEP;"),
    ("ib_yminus", C, "t->Location.y = t->Location.y - BOUNDS_STEP;",
     "t->Location.y = t->Location.y + BOUNDS_STEP;"),
    ("ib_mv_xm", C, "            t->Location.x = t->Location.x - BOUNDS_STEP;\n"
     "            moved = 1;\n",
     "            t->Location.x = t->Location.x - BOUNDS_STEP;\n"),
    ("ib_mv_xp", C, "            t->Location.x = t->Location.x + BOUNDS_STEP;\n"
     "            moved = 1;\n",
     "            t->Location.x = t->Location.x + BOUNDS_STEP;\n"),
    ("ib_mv_yp", C, "            t->Location.y = t->Location.y + BOUNDS_STEP;\n"
     "            moved = 1;\n",
     "            t->Location.y = t->Location.y + BOUNDS_STEP;\n"),
    ("ib_mv_ym", C, "            t->Location.y = t->Location.y - BOUNDS_STEP;\n"
     "            moved = 1;\n",
     "            t->Location.y = t->Location.y - BOUNDS_STEP;\n"),
    ("ib_ret1", C, "        if (!moved)\n            return 1;",
     "        if (!moved)\n            return 0;"),
    ("ib_ret0", C, "        if (!moved)\n            return 1;\n    }\n    return 0;",
     "        if (!moved)\n            return 1;\n    }\n    return 1;"),
    # ---- ChopperOnDifferentFork
    ("df_same", C, "    if (route == h->ChopperRoute)\n        return 0;\n", ""),
    ("df_ir", C, "    info.Route = h->ChopperRoute;\n    info.Point = h->ChopperPoint;\n"
     "    if (chopper_find_previous_fork",
     "    info.Route = h->TargetRoute;\n    info.Point = h->ChopperPoint;\n"
     "    if (chopper_find_previous_fork"),
    ("df_ip", C, "    info.Point = h->ChopperPoint;\n    if (chopper_find_previous_fork",
     "    info.Point = h->TargetPoint;\n    if (chopper_find_previous_fork"),
    ("df_b", C, "if (chopper_find_previous_fork(h, &info, 1) == 0)",
     "if (chopper_find_previous_fork(h, &info, 0) == 0)"),
    ("df_zero", C, "    if (chopper_find_previous_fork(h, &info, 1) == 0)\n"
     "        return 0;\n", "    chopper_find_previous_fork(h, &info, 1);\n"),
    ("df_eq", C, "    return info.Route == route;", "    return info.Route != route;"),
    # ---- AdjustTargetLocal, TestLocation and AdjustByThinkTime
    ("lo_x", C, "t->Location.x = t->Location.x - h->CurrentPos.x;",
     "t->Location.x = h->CurrentPos.x - t->Location.x;"),
    ("lo_y", C, "t->Location.y = t->Location.y - h->CurrentPos.y;",
     "t->Location.y = t->Location.y - h->CurrentPos.x;"),
    ("lo_rot", C, "    chopper_rotate_to_chopper_coord(h, &t->Location, "
     "&t->Location);\n", ""),
    ("tl_yaw", C, "rotate_vector(&v, &v, h->Yaw);",
     "rotate_vector(&v, &v, -h->Yaw);"),
    ("tl_rot", C, "    rotate_vector(&v, &v, h->Yaw);\n", ""),
    ("tl_x", C, "v.x = v.x + h->CurrentPos.x;", "v.x = v.x + h->CurrentPos.y;"),
    ("tl_y", C, "v.y = v.y + h->CurrentPos.y;", "v.y = v.y - h->CurrentPos.y;"),
    ("tl_swap", C, "    v.x = x;\n    v.y = y;\n", "    v.x = y;\n    v.y = x;\n"),
    ("bt_scale", C, "#define THINK_SCALE        100.0f",
     "#define THINK_SCALE        10.0f"),
    ("bt_op", C, "return f * THINK_SCALE;", "return f / THINK_SCALE;"),
    # ---- RotateVector
    ("rv_y", U, "out->y = y * c - x * s;", "out->y = y * c + x * s;"),
    ("rv_x", U, "out->x = x * c + y * s;", "out->x = x * c - y * s;"),
    ("rv_alias", U, "out->x = x * c + y * s;",
     "out->x = x * c + v->y * s;"),
    ("rv_bam", U, "(uint16_t)(ee_trunc_w(deg * 65536.0f) / 360)",
     "(uint16_t)(ee_trunc_w(deg * 65536.0f) / 361)"),
    ("rv_sc", U, "bSinCos(&s, &c,", "bSinCos(&c, &s,"),
    # ---- 12k-3b: the plans' constants
    ("hl_tick", C, "#define PLAN_TICK          0.1f",
     "#define PLAN_TICK          0.2f"),
    ("hl_lead", C, "#define PLAN_LEAD          0.3f",
     "#define PLAN_LEAD          0.25f"),
    ("hl_giveup", C, "#define STAKEOUT_GIVE_UP   60.0f",
     "#define STAKEOUT_GIVE_UP   60.5f"),
    ("hl_reach", C, "#define STAKEOUT_REACH     30.0f",
     "#define STAKEOUT_REACH     30.5f"),
    ("hl_wait", C, "#define STAKEOUT_WAIT      45.0f",
     "#define STAKEOUT_WAIT      44.0f"),
    ("cp_leadspeed", C, "#define PURSUIT_LEAD_SPEED 20.0f",
     "#define PURSUIT_LEAD_SPEED 19.99f"),
    ("br_tick", C, "#define SALVO_TICK         0.1f",
     "#define SALVO_TICK         0.2f"),
    ("br_reach", C, "#define BOMB_REACH         30.0f",
     "#define BOMB_REACH         30.5f"),
    ("br_height", C, "#define BOMB_HEIGHT        10.0f",
     "#define BOMB_HEIGHT        10.5f"),
    # ---- CleverPursuitPlan
    ("cp_zv", C, "if (!(h->ZVelocity == 0.0f) && ((flags & 2) || !on_sheet))",
     "if ((h->ZVelocity == 0.0f) && ((flags & 2) || !on_sheet))"),
    ("cp_flag2", C, "&& ((flags & 2) || !on_sheet)) {",
     "&& ((flags & 1) || !on_sheet)) {"),
    ("cp_or", C, "&& ((flags & 2) || !on_sheet)) {",
     "&& ((flags & 2) && !on_sheet)) {"),
    ("cp_on", C, "&& ((flags & 2) || !on_sheet)) {",
     "&& ((flags & 2) || on_sheet)) {"),
    ("cp_ey", C, "!on_sheet)) {\n        t->Location.y = h->CurrentPos.y;\n",
     "!on_sheet)) {\n"),
    ("cp_ey_x", C, "!on_sheet)) {\n        t->Location.y = h->CurrentPos.y;\n",
     "!on_sheet)) {\n        t->Location.y = h->CurrentPos.x;\n"),
    ("cp_ex", C, "        t->Location.x = h->CurrentPos.x;\n        return;\n"
     "    }\n    near =", "        return;\n    }\n    near ="),
    ("cp_eret", C, "        t->Location.x = h->CurrentPos.x;\n        return;\n"
     "    }\n    near =", "        t->Location.x = h->CurrentPos.x;\n    }\n"
     "    near ="),
    ("cp_near", C, "    near = distance_to(h, &t->Location)\n           <",
     "    near = distance_to(h, &t->Location)\n           <="),
    ("cp_rnull", C, "if (route == NULL || point == NULL) {\n"
     "        chopper_bail_to_point_near_chopper",
     "if (route == NULL && point == NULL) {\n"
     "        chopper_bail_to_point_near_chopper"),
    ("cp_rnull_r", C, "if (route == NULL || point == NULL) {\n"
     "        chopper_bail_to_point_near_chopper",
     "if (point == NULL) {\n        chopper_bail_to_point_near_chopper"),
    ("cp_bail", C, "        chopper_bail_to_point_near_chopper(h, t);\n"
     "        return;\n    }\n    ahead =", "        return;\n    }\n"
     "    ahead ="),
    ("cp_ahead_arg", C, "troute_find_closest_point_ahead(route, &t->Location, "
     "point);", "troute_find_closest_point_ahead(route, &t->Location, "
     "h->ChopperPoint);"),
    ("cp_ahead_use", C, "    if (ahead != NULL)\n        point = ahead;\n", ""),
    ("cp_onsheet", C, "    if (on_sheet) {\n        if (near) {",
     "    if (!on_sheet) {\n        if (near) {"),
    ("cp_near1", C, "    if (on_sheet) {\n        if (near) {",
     "    if (on_sheet) {\n        if (!near) {"),
    ("cp_lead_le", C, "if (PURSUIT_LEAD_SPEED < h->Speed) {",
     "if (PURSUIT_LEAD_SPEED <= h->Speed) {"),
    ("cp_along_dx", C, "(t->Location.x - point->Position.x)\n"
     "                            * point->Direction.x",
     "(t->Location.x - point->Position.x)\n"
     "                            * point->Direction.y"),
    ("cp_along_dy", C, "(t->Location.y - point->Position.y)\n"
     "                              * point->Direction.y;",
     "(t->Location.y - point->Position.y)\n"
     "                              * point->Direction.x;"),
    ("cp_along_px", C, "along = (t->Location.x - point->Position.x)",
     "along = (t->Location.x - point->Position.y)"),
    ("cp_along_py", C, "+ (t->Location.y - point->Position.y)\n",
     "+ (t->Location.y - point->Position.x)\n"),
    ("cp_along_add", C, "+ (t->Location.y - point->Position.y)\n",
     "- (t->Location.y - point->Position.y)\n"),
    ("cp_gp2_l", C, "trpoint_get_position2(point, &t->Location, along, 0.0f);",
     "trpoint_get_position2(point, &t->Location, along, 1.0f);"),
    ("cp_gp2_d", C, "trpoint_get_position2(point, &t->Location, along, 0.0f);",
     "trpoint_get_position2(point, &t->Location, -along, 0.0f);"),
    ("cp_gp2", C, "                trpoint_get_position2(point, &t->Location, "
     "along, 0.0f);\n", ""),
    ("cp_lead_ret", C, "along, 0.0f);\n            }\n            return;\n",
     "along, 0.0f);\n            }\n"),
    ("cp_nohs", C, "} else if (point->Bits & TRP_NO_HELISHEET) {",
     "} else if (!(point->Bits & TRP_NO_HELISHEET)) {"),
    ("cp_nohs_bit", C, "} else if (point->Bits & TRP_NO_HELISHEET) {",
     "} else if (point->Bits & 0x8000) {"),
    ("cp_stake1", C, "TRP_NO_HELISHEET) {\n        chopper_begin_stakeout(h, t, "
     "route, point);\n", "TRP_NO_HELISHEET) {\n"),
    ("cp_stake1_ret", C, "        chopper_begin_stakeout(h, t, route, point);\n"
     "        return;\n    }\n    if (chopper_on_different_fork",
     "        chopper_begin_stakeout(h, t, route, point);\n    }\n"
     "    if (chopper_on_different_fork"),
    ("cp_fork", C, "if (chopper_on_different_fork(h, route, point)) {",
     "if (!chopper_on_different_fork(h, route, point)) {"),
    ("cp_fork_stake", C, "different_fork(h, route, point)) {\n"
     "        chopper_begin_stakeout(h, t, route, point);\n",
     "different_fork(h, route, point)) {\n"),
    ("cp_fork_ret", C, "        chopper_begin_stakeout(h, t, route, point);\n"
     "        return;\n    }\n    if (near)",
     "        chopper_begin_stakeout(h, t, route, point);\n    }\n"
     "    if (near)"),
    ("cp_near2", C, "    if (near)\n        chopper_hangout_near_here(",
     "    if (!near)\n        chopper_hangout_near_here("),
    ("cp_hang_pt", C, "chopper_hangout_near_here(h, t, route, point);",
     "chopper_hangout_near_here(h, t, route, h->ChopperPoint);"),
    ("cp_follow_fwd", C, "chopper_follow_route(h, t, route, point, "
     "chopper_behind_car(h));", "chopper_follow_route(h, t, route, point, "
     "!chopper_behind_car(h));"),
    ("cp_follow_pt", C, "chopper_follow_route(h, t, route, point, "
     "chopper_behind_car(h));", "chopper_follow_route(h, t, route, "
     "h->ChopperPoint, chopper_behind_car(h));"),
    # ---- BombRunLogic
    ("br_pt_arg", C, "car_get_route_point(h->CurrentCar, FIND_ROUTE);\n"
     "    // The port's", "car_get_route_point(h->CurrentCar, 0);\n"
     "    // The port's"),
    ("br_same", C, "if (point != h->OldCarPoint && point != NULL && "
     "h->OldCarPoint != NULL) {", "if (point != NULL && h->OldCarPoint != "
     "NULL) {"),
    ("br_null_pt", C, "if (point != h->OldCarPoint && point != NULL && "
     "h->OldCarPoint != NULL) {", "if (point != h->OldCarPoint && "
     "h->OldCarPoint != NULL) {"),
    ("br_null_old", C, "if (point != h->OldCarPoint && point != NULL && "
     "h->OldCarPoint != NULL) {", "if (point != h->OldCarPoint && "
     "point != NULL) {"),
    ("br_route_arg", C, "        route = car_get_route(h->CurrentCar, "
     "FIND_ROUTE);\n        d =", "        route = car_get_route(h->CurrentCar, "
     "0);\n        d ="),
    ("br_dx", C, "d = point->Position.x - h->OldCarPoint->Position.x;",
     "d = point->Position.x - h->OldCarPoint->Position.y;"),
    ("br_dy", C, "across = point->Position.y - h->OldCarPoint->Position.y;",
     "across = point->Position.y - h->OldCarPoint->Position.x;"),
    ("br_sqrt", C, "        d = sqrtf(d * d + across * across);\n        if (route",
     "        d = sqrtf(d * d + across * d);\n        if (route"),
    ("br_rt", C, "if (route != h->OldCarRoute\n            || point_index",
     "if (route == h->OldCarRoute\n            || point_index"),
    ("br_or", C, "            || point_index(route, h->OldCarPoint) < ",
     "            && point_index(route, h->OldCarPoint) < "),
    ("br_lt", C, "point_index(route, h->OldCarPoint) < point_index(route, "
     "point))", "point_index(route, h->OldCarPoint) > point_index(route, "
     "point))"),
    ("br_neg", C, "            d = -d;\n        h->OldCarPoint = point;",
     "            d = d;\n        h->OldCarPoint = point;"),
    ("br_oldpt", C, "        h->OldCarPoint = point;\n        h->TargetDistance",
     "        h->TargetDistance"),
    ("br_td", C, "h->TargetDistance = h->TargetDistance + d;",
     "h->TargetDistance = h->TargetDistance - d;"),
    ("br_oldrt", C, "        h->OldCarRoute = route;\n    }\n"
     "    chopper_adjust_bomb_target(h);", "    }\n"
     "    chopper_adjust_bomb_target(h);"),
    ("br_adjust", C, "    }\n    chopper_adjust_bomb_target(h);\n"
     "    if (h->NumSalvosReleased > 0) {", "    }\n"
     "    if (h->NumSalvosReleased > 0) {"),
    ("br_salvos", C, "if (h->NumSalvosReleased > 0) {",
     "if (h->NumSalvosReleased >= 0) {"),
    ("br_tuns", C, "h->TimeUntilNextSalvo = h->TimeUntilNextSalvo - SALVO_TICK;",
     "h->TimeUntilNextSalvo = h->TimeUntilNextSalvo + SALVO_TICK;"),
    ("br_fire1", C, "fire = h->TimeUntilNextSalvo < 0.0f;",
     "fire = h->TimeUntilNextSalvo <= 0.0f;"),
    ("br_reach_le", C, "&h->TargetPoint->Position) < BOMB_REACH) {",
     "&h->TargetPoint->Position) <= BOMB_REACH) {"),
    ("br_reach_pt", C, "&h->TargetPoint->Position) < BOMB_REACH) {",
     "&h->ChopperPoint->Position) < BOMB_REACH) {"),
    ("br_cp", C, "        cp = h->ChopperPoint;\n", "        cp = h->TargetPoint;\n"),
    ("br_ax", C, "across = (h->CurrentPos.x - cp->Position.x) * cp->Direction.y",
     "across = (h->CurrentPos.x - cp->Position.x) * cp->Direction.x"),
    ("br_ax_p", C, "across = (h->CurrentPos.x - cp->Position.x) * "
     "cp->Direction.y", "across = (h->CurrentPos.x - cp->Position.y) * "
     "cp->Direction.y"),
    ("br_ay", C, "- (h->CurrentPos.y - cp->Position.y) * cp->Direction.x;",
     "+ (h->CurrentPos.y - cp->Position.y) * cp->Direction.x;"),
    ("br_ay_p", C, "- (h->CurrentPos.y - cp->Position.y) * cp->Direction.x;",
     "- (h->CurrentPos.y - cp->Position.x) * cp->Direction.x;"),
    ("br_ay_d", C, "- (h->CurrentPos.y - cp->Position.y) * cp->Direction.x;",
     "- (h->CurrentPos.y - cp->Position.y) * cp->Direction.y;"),
    ("br_side", C, "if (0.0f < across)\n            across = across - "
     "cp->RightWidth;", "if (0.0f <= across)\n            across = across - "
     "cp->RightWidth;"),
    ("br_side_flip", C, "if (0.0f < across)\n            across = across - "
     "cp->RightWidth;", "if (across < 0.0f)\n            across = across - "
     "cp->RightWidth;"),
    ("br_rw", C, "across = across - cp->RightWidth;",
     "across = across - cp->LeftWidth;"),
    ("br_lw", C, "across = -(across + cp->LeftWidth);",
     "across = -(across + cp->RightWidth);"),
    ("br_lw_neg", C, "across = -(across + cp->LeftWidth);",
     "across = (across + cp->LeftWidth);"),
    ("br_fire2", C, "fire = across < 0.0f;", "fire = across <= 0.0f;"),
    ("br_fire_or", C, "if (fire && helisheet_find_z_value(TheHeliSheet,",
     "if (fire || helisheet_find_z_value(TheHeliSheet,"),
    ("br_fire_not", C, "if (fire && helisheet_find_z_value(TheHeliSheet,",
     "if (!fire && helisheet_find_z_value(TheHeliSheet,"),
    ("br_sheet", C, "if (fire && helisheet_find_z_value(TheHeliSheet,",
     "if (fire && !helisheet_find_z_value(TheHeliSheet,"),
    ("br_ground", C, "        chopper_find_ground_height(h);\n"
     "        if (h->CurrentPos.z - h->GroundZ <= BOMB_HEIGHT) {",
     "        if (h->CurrentPos.z - h->GroundZ <= BOMB_HEIGHT) {"),
    ("br_height_lt", C, "if (h->CurrentPos.z - h->GroundZ <= BOMB_HEIGHT) {",
     "if (h->CurrentPos.z - h->GroundZ < BOMB_HEIGHT) {"),
    ("br_fire_call", C, "            chopper_fire_salvo(h);\n", ""),
    ("br_n", C, "            h->NumSalvosReleased++;\n", ""),
    ("br_total", C, "            h->TotalSalvos++;\n", ""),
    ("br_order", C, "            chopper_fire_salvo(h);\n"
     "            h->NumSalvosReleased++;\n", "            h->NumSalvosReleased++;\n"
     "            chopper_fire_salvo(h);\n"),
    ("br_btype", C, "            b = &BombRunBehaviours[h->BombRunType];\n"
     "            h->Timeout", "            b = &BombRunBehaviours[1];\n"
     "            h->Timeout"),
    ("br_timeout", C, "            h->Timeout = CHOPPER_TIMEOUT;\n"
     "            h->TimeUntilNextSalvo = b->SalvoDelay;",
     "            h->TimeUntilNextSalvo = b->SalvoDelay;"),
    ("br_delay", C, "h->TimeUntilNextSalvo = b->SalvoDelay;",
     "h->TimeUntilNextSalvo = b->SalvoSpread;"),
    ("br_nsalvos", C, "if (!(h->NumSalvosReleased < b->NumSalvos)) {",
     "if (!(h->NumSalvosReleased <= b->NumSalvos)) {"),
    ("br_last_plan", C, "b->NumSalvos)) {\n                h->Plan = "
     "CHOPPLAN_PURSUIT;\n", "b->NumSalvos)) {\n"),
    ("br_last_ret", C, "                h->Plan = CHOPPLAN_PURSUIT;\n"
     "                return;\n", "                h->Plan = "
     "CHOPPLAN_PURSUIT;\n"),
    ("br_to", C, "    if (h->Timeout == 0.0f) {\n        h->Plan = "
     "CHOPPLAN_PURSUIT;\n        return;\n    }\n    chopper_follow_route(h, t, "
     "h->TargetRoute", "    if (h->Timeout != 0.0f) {\n        h->Plan = "
     "CHOPPLAN_PURSUIT;\n        return;\n    }\n    chopper_follow_route(h, t, "
     "h->TargetRoute"),
    ("br_to_plan", C, "        h->Plan = CHOPPLAN_PURSUIT;\n        return;\n"
     "    }\n    chopper_follow_route(h, t, h->TargetRoute, h->TargetPoint, 1);"
     "\n}", "        return;\n    }\n    chopper_follow_route(h, t, "
     "h->TargetRoute, h->TargetPoint, 1);\n}"),
    ("br_to_ret", C, "        h->Plan = CHOPPLAN_PURSUIT;\n        return;\n"
     "    }\n    chopper_follow_route(h, t, h->TargetRoute, h->TargetPoint, 1);"
     "\n}", "        h->Plan = CHOPPLAN_PURSUIT;\n    }\n"
     "    chopper_follow_route(h, t, h->TargetRoute, h->TargetPoint, 1);\n}"),
    ("br_follow_fwd", C, "    }\n    chopper_follow_route(h, t, "
     "h->TargetRoute, h->TargetPoint, 1);\n}", "    }\n"
     "    chopper_follow_route(h, t, h->TargetRoute, h->TargetPoint, 0);\n}"),
    ("br_follow", C, "    }\n    chopper_follow_route(h, t, h->TargetRoute, "
     "h->TargetPoint, 1);\n}", "    }\n}"),
    # ---- HighLevelPlanning
    ("hl_on_init", C, "    int32_t on_sheet = 0;\n    uint32_t flags = 0;",
     "    int32_t on_sheet = 1;\n    uint32_t flags = 0;"),
    ("hl_flags_init", C, "    uint32_t flags = 0;\n    float z = 0.0f;",
     "    uint32_t flags = 2;\n    float z = 0.0f;"),
    ("hl_z_init", C, "    uint32_t flags = 0;\n    float z = 0.0f;",
     "    uint32_t flags = 0;\n    float z = 1.0f;"),
    ("hl_to", C, "h->Timeout = h->Timeout - PLAN_TICK;",
     "h->Timeout = h->Timeout + PLAN_TICK;"),
    ("hl_clamp", C, "    if (h->Timeout < 0.0f)\n        h->Timeout = 0.0f;\n"
     "    if (h->Plan != CHOPPLAN_END_CHASE) {",
     "    if (h->Plan != CHOPPLAN_END_CHASE) {"),
    ("hl_clamp_val", C, "        h->Timeout = 0.0f;\n    if (h->Plan != "
     "CHOPPLAN_END_CHASE) {", "        h->Timeout = -0.0f;\n    if (h->Plan "
     "!= CHOPPLAN_END_CHASE) {"),
    ("hl_end", C, "    if (h->Plan != CHOPPLAN_END_CHASE) {\n        bScaleAdd2",
     "    if (h->Plan != CHOPPLAN_EATING_DONUTS) {\n        bScaleAdd2"),
    ("hl_lead_v", C, "&h->CurrentCar->State.Velocity,\n                   "
     "PLAN_LEAD);", "&h->CurrentCar->State.Position,\n                   "
     "PLAN_LEAD);"),
    ("hl_lead_p", C, "                   (const bVector2 *)&h->CurrentCar->"
     "State.Position,\n", "                   (const bVector2 *)&h->"
     "CurrentCar->State.Velocity,\n"),
    ("hl_zv_flags", C, "&t->Location, &z,\n                                  "
     "        &flags);", "&t->Location, &z,\n                              "
     "            NULL);"),
    ("hl_on", C, "on_sheet = helisheet_find_z_value(TheHeliSheet, &t->Location",
     "on_sheet = !helisheet_find_z_value(TheHeliSheet, &t->Location"),
    ("hl_frp", C, "    if (h->Plan != CHOPPLAN_START_CHASE)\n"
     "        chopper_find_route_point(h);", "    if (h->Plan != "
     "CHOPPLAN_END_CHASE)\n        chopper_find_route_point(h);"),
    ("hl_frp_rm", C, "        chopper_find_route_point(h);\n"
     "    t->DesiredSpeed = -1.0f;", "    t->DesiredSpeed = -1.0f;"),
    ("hl_ds", C, "    t->DesiredSpeed = -1.0f;\n    switch (h->Plan) {",
     "    t->DesiredSpeed = 1.0f;\n    switch (h->Plan) {"),
    ("hl_bomb", C, "    case CHOPPLAN_BOMBING_RUN:\n        chopper_bomb_run_logic"
     "(h, t);\n", "    case CHOPPLAN_BOMBING_RUN:\n"),
    ("hl_bomb_brk", C, "        chopper_bomb_run_logic(h, t);\n        break;\n",
     "        chopper_bomb_run_logic(h, t);\n"),
    ("hl_case_at", C, "    case CHOPPLAN_HEAD_TO_STAKEOUT:\n"
     "    case CHOPPLAN_AT_STAKEOUT:\n", "    case CHOPPLAN_HEAD_TO_STAKEOUT:\n"),
    ("hl_case_head", C, "    case CHOPPLAN_HEAD_TO_STAKEOUT:\n"
     "    case CHOPPLAN_AT_STAKEOUT:\n", "    case CHOPPLAN_AT_STAKEOUT:\n"),
    ("hl_st_on", C, "if (on_sheet && (distance_to(h, &t->Location) < "
     "STAKEOUT_GIVE_UP", "if (!on_sheet && (distance_to(h, &t->Location) < "
     "STAKEOUT_GIVE_UP"),
    ("hl_st_and", C, "if (on_sheet && (distance_to(h, &t->Location) < "
     "STAKEOUT_GIVE_UP", "if (on_sheet || (distance_to(h, &t->Location) < "
     "STAKEOUT_GIVE_UP"),
    ("hl_st_lt", C, "&t->Location) < STAKEOUT_GIVE_UP\n",
     "&t->Location) <= STAKEOUT_GIVE_UP\n"),
    ("hl_st_or", C, "                         || h->Timeout == 0.0f)) {",
     "                         && h->Timeout == 0.0f)) {"),
    ("hl_st_to", C, "                         || h->Timeout == 0.0f)) {",
     "                         || h->Timeout != 0.0f)) {"),
    ("hl_st_plan", C, "            h->Plan = CHOPPLAN_PURSUIT;\n            break;"
     "\n        }\n        if (h->Plan != CHOPPLAN_HEAD_TO_STAKEOUT)",
     "            break;\n        }\n        if (h->Plan != "
     "CHOPPLAN_HEAD_TO_STAKEOUT)"),
    ("hl_st_head", C, "if (h->Plan != CHOPPLAN_HEAD_TO_STAKEOUT)\n            "
     "break;", "if (h->Plan != CHOPPLAN_AT_STAKEOUT)\n            break;"),
    ("hl_st_reach_le", C, "&h->TargetPoint->Position) < STAKEOUT_REACH) {",
     "&h->TargetPoint->Position) <= STAKEOUT_REACH) {"),
    ("hl_st_reach_pt", C, "&h->TargetPoint->Position) < STAKEOUT_REACH) {",
     "&h->ChopperPoint->Position) < STAKEOUT_REACH) {"),
    ("hl_st_at", C, "            h->Plan = CHOPPLAN_AT_STAKEOUT;\n",
     "            h->Plan = CHOPPLAN_HEAD_TO_STAKEOUT;\n"),
    ("hl_st_wait", C, "            h->Timeout = STAKEOUT_WAIT;\n", ""),
    ("hl_st_lx", C, "            t->Location.x = h->TargetPoint->Position.x;\n",
     ""),
    ("hl_st_ly", C, "            t->Location.y = h->TargetPoint->Position.y;\n",
     "            t->Location.y = h->TargetPoint->Position.x;\n"),
    ("hl_st_follow_fwd", C, "            chopper_follow_route(h, t, "
     "h->TargetRoute, h->TargetPoint, 1);\n        }",
     "            chopper_follow_route(h, t, h->TargetRoute, h->TargetPoint, "
     "0);\n        }"),
    ("hl_st_follow", C, "        } else {\n            chopper_follow_route(h, "
     "t, h->TargetRoute, h->TargetPoint, 1);\n        }", "        }"),
    ("hl_sc_ret", C, "        if (chopper_start_chase_logic(h, t, on_sheet, "
     "flags, z))\n            return 1;", "        if (chopper_start_chase_"
     "logic(h, t, on_sheet, flags, z))\n            return 0;"),
    ("hl_sc_z", C, "chopper_start_chase_logic(h, t, on_sheet, flags, z)",
     "chopper_start_chase_logic(h, t, on_sheet, flags, 0.0f)"),
    ("hl_sc_fl", C, "chopper_start_chase_logic(h, t, on_sheet, flags, z)",
     "chopper_start_chase_logic(h, t, on_sheet, 0, z)"),
    ("hl_sc_on", C, "chopper_start_chase_logic(h, t, on_sheet, flags, z)",
     "chopper_start_chase_logic(h, t, 1, flags, z)"),
    ("hl_sc_brk", C, "            return 1;\n        break;\n"
     "    case CHOPPLAN_END_CHASE:", "            return 1;\n"
     "    case CHOPPLAN_END_CHASE:"),
    ("hl_ec_ret", C, "        if (chopper_end_chase_logic(h, t))\n"
     "            return 1;", "        if (chopper_end_chase_logic(h, t))\n"
     "            return 0;"),
    ("hl_ec_rm", C, "        if (chopper_end_chase_logic(h, t))\n"
     "            return 1;\n", ""),
    ("hl_pur", C, "    if (h->Plan == CHOPPLAN_PURSUIT)\n"
     "        chopper_clever_pursuit_plan", "    if (h->Plan != "
     "CHOPPLAN_PURSUIT)\n        chopper_clever_pursuit_plan"),
    ("hl_pur_fl", C, "chopper_clever_pursuit_plan(h, t, on_sheet, flags);",
     "chopper_clever_pursuit_plan(h, t, on_sheet, 0);"),
    ("hl_pur_on", C, "chopper_clever_pursuit_plan(h, t, on_sheet, flags);",
     "chopper_clever_pursuit_plan(h, t, 1, flags);"),
    ("hl_inb", C, "    chopper_adjust_target_in_bounds(h, t);\n"
     "    chopper_adjust_target_local(h, t);\n    return 0;",
     "    chopper_adjust_target_local(h, t);\n    return 0;"),
    ("hl_local", C, "    chopper_adjust_target_in_bounds(h, t);\n"
     "    chopper_adjust_target_local(h, t);\n    return 0;",
     "    chopper_adjust_target_in_bounds(h, t);\n    return 0;"),
    ("hl_order", C, "    chopper_adjust_target_in_bounds(h, t);\n"
     "    chopper_adjust_target_local(h, t);\n    return 0;",
     "    chopper_adjust_target_local(h, t);\n"
     "    chopper_adjust_target_in_bounds(h, t);\n    return 0;"),
    ("hl_ret", C, "    chopper_adjust_target_local(h, t);\n    return 0;\n}",
     "    chopper_adjust_target_local(h, t);\n    return 1;\n}"),
    # ---- 12k-4a: MakeRelativeAngle
    ("ra_hi", U, "while (180.0f < deg)", "while (180.0f <= deg)"),
    ("ra_hi_val", U, "deg = deg - 360.0f;", "deg = deg - 361.0f;"),
    ("ra_hi_once", U, "    while (180.0f < deg)", "    if (180.0f < deg)"),
    ("ra_lo", U, "while (deg < -180.0f)", "while (deg <= -180.0f)"),
    ("ra_lo_val", U, "deg = deg + 360.0f;", "deg = deg + 361.0f;"),
    ("ra_lo_once", U, "    while (deg < -180.0f)", "    if (deg < -180.0f)"),
    # ---- SetXAccel
    ("xa_ds", C, "if (0.0f < t->DesiredSpeed && 0.0f < t->Location.x)",
     "if (0.0f <= t->DesiredSpeed && 0.0f < t->Location.x)"),
    ("xa_x", C, "if (0.0f < t->DesiredSpeed && 0.0f < t->Location.x)",
     "if (0.0f < t->DesiredSpeed && 0.0f <= t->Location.x)"),
    ("xa_and", C, "if (0.0f < t->DesiredSpeed && 0.0f < t->Location.x)",
     "if (0.0f < t->DesiredSpeed || 0.0f < t->Location.x)"),
    ("xa_gain", C, "#define SPEED_GAIN         10.0f",
     "#define SPEED_GAIN         11.0f"),
    ("xa_order", C, "(t->DesiredSpeed - h->Speed) * SPEED_GAIN",
     "(h->Speed - t->DesiredSpeed) * SPEED_GAIN"),
    ("xa_damp", C, "#define SPEED_DAMP         0.1f",
     "#define SPEED_DAMP         0.2f"),
    ("xa_damp_sign", C, "t->Location.x - h->Speed * SPEED_DAMP",
     "t->Location.x + h->Speed * SPEED_DAMP"),
    ("xa_think", C, "h->Acceleration.x = chopper_adjust_by_think_time(\n"
     "            h, t->Location.x - h->Speed * SPEED_DAMP);",
     "h->Acceleration.x = t->Location.x - h->Speed * SPEED_DAMP;"),
    ("xa_min", C, "if (h->Acceleration.x < chopper_get_max_deceleration(h))",
     "if (h->Acceleration.x > chopper_get_max_deceleration(h))"),
    ("xa_min_set", C, "        h->Acceleration.x = "
     "chopper_get_max_deceleration(h);\n",
     "        h->Acceleration.x = -60.0f;\n"),
    ("xa_max", C, "else if (MAX_ACCEL < h->Acceleration.x)",
     "else if (MAX_ACCEL > h->Acceleration.x)"),
    ("xa_max_val", C, "#define MAX_ACCEL          20.0f",
     "#define MAX_ACCEL          21.0f"),
    ("xa_max_set", C, "        h->Acceleration.x = MAX_ACCEL;",
     "        h->Acceleration.x = 21.0f;"),
    # ---- SetYAccel
    ("ya_lim", C, "if (SIDE_LIMIT <= fabsf(angle))",
     "if (SIDE_LIMIT < fabsf(angle))"),
    ("ya_lim_val", C, "#define SIDE_LIMIT         90.0f",
     "#define SIDE_LIMIT         89.0f"),
    ("ya_abs", C, "if (SIDE_LIMIT <= fabsf(angle))",
     "if (SIDE_LIMIT <= angle)"),
    ("ya_zero", C, "        h->Acceleration.y = 0.0f;\n    else",
     "        h->Acceleration.y = 1.0f;\n    else"),
    ("ya_think", C, "chopper_adjust_by_think_time(h, t->Location.y)",
     "t->Location.y"),
    ("ya_absacc", C, "a = fabsf(h->Acceleration.y);",
     "a = h->Acceleration.y;"),
    ("ya_reset", C, "    h->DesiredRoll = 0.0f;\n    if (!(ROLL_START < a))",
     "    if (!(ROLL_START < a))"),
    ("ya_start", C, "if (!(ROLL_START < a))", "if (!(ROLL_START <= a))"),
    ("ya_start_val", C, "#define ROLL_START         5.0f",
     "#define ROLL_START         6.0f"),
    ("ya_sub", C, "h->DesiredRoll = a - ROLL_START;", "h->DesiredRoll = a;"),
    ("ya_max", C, "if (ROLL_MAX < h->DesiredRoll)",
     "if (ROLL_MAX > h->DesiredRoll)"),
    ("ya_max_val", C, "#define ROLL_MAX           20.0f",
     "#define ROLL_MAX           21.0f"),
    ("ya_neg", C, "    if (h->Acceleration.y < 0.0f)\n"
     "        h->DesiredRoll = -h->DesiredRoll;",
     "    if (h->Acceleration.y > 0.0f)\n"
     "        h->DesiredRoll = -h->DesiredRoll;"),
    ("ya_neg_drop", C, "        h->DesiredRoll = -h->DesiredRoll;\n", ""),
    # ---- SetRotateTarget
    ("rt_rate", C, "#define ROTATE_RATE        90.0f",
     "#define ROTATE_RATE        91.0f"),
    ("rt_lo", C, "    if (rot < -lim)", "    if (rot <= -lim)"),
    ("rt_hi", C, "    else if (lim < rot)", "    else if (lim <= rot)"),
    ("rt_else", C, "    else if (lim < rot)", "    if (lim < rot)"),
    ("rt_store", C, "    h->RotRate = rot;\n", "    h->RotRate = 0.0f;\n"),
    ("rt_neg", C, "        h->RotRate = -lim;", "        h->RotRate = lim;"),
    ("rt_droll", C, "        h->RotRate = lim;\n    h->DesiredRoll = 0.0f;",
     "        h->RotRate = lim;"),
    ("rt_scale", C, "float lim = scale * ROTATE_RATE;",
     "float lim = ROTATE_RATE;"),
    # ---- HoverTime
    ("hv_still", C, "if (!(fabsf(h->Speed) <= HOVER_STILL)",
     "if (!(fabsf(h->Speed) < HOVER_STILL)"),
    ("hv_abs", C, "if (!(fabsf(h->Speed) <= HOVER_STILL)",
     "if (!(h->Speed <= HOVER_STILL)"),
    ("hv_still_val", C, "#define HOVER_STILL        0.001f",
     "#define HOVER_STILL        0.002f"),
    ("hv_near", C, "|| !(d < HOVER_NEAR)", "|| !(d <= HOVER_NEAR)"),
    ("hv_near_val", C, "#define HOVER_NEAR         5.0f",
     "#define HOVER_NEAR         6.0f"),
    ("hv_d", C, "                    + t->Location.y * t->Location.y);",
     "                    - t->Location.y * t->Location.y);"),
    ("hv_dx", C, "float d = sqrtf(t->Location.x * t->Location.x",
     "float d = sqrtf(t->Location.y * t->Location.x"),
    ("hv_acc", C, "!(h->Acceleration.x < HOVER_ACCEL)",
     "!(h->Acceleration.x <= HOVER_ACCEL)"),
    ("hv_acc_val", C, "#define HOVER_ACCEL        0.1f",
     "#define HOVER_ACCEL        0.2f"),
    ("hv_or", C, "    if (!(fabsf(h->Speed) <= HOVER_STILL) || !(d < HOVER_NEAR)",
     "    if (!(fabsf(h->Speed) <= HOVER_STILL) && !(d < HOVER_NEAR)"),
    ("hv_mm", C, "    h->MoveMode = CHOPMOVE_ROTATE;\n    car = h->CurrentCar;",
     "    car = h->CurrentCar;"),
    ("hv_plan", C, "    if (h->Plan == CHOPPLAN_PURSUIT)\n        f = BAM_TO_DEG",
     "    if (h->Plan != CHOPPLAN_PURSUIT)\n        f = BAM_TO_DEG"),
    ("hv_bam", C, "f = BAM_TO_DEG * (float)car->State.Angle;",
     "f = BAM_TO_DEG * (float)(int16_t)car->State.Angle;"),
    ("hv_bam_val", C, "#define BAM_TO_DEG         (360.0f / 65536.0f)",
     "#define BAM_TO_DEG         (360.0f / 65535.0f)"),
    ("hv_atan_swap", C, "bATan(car->State.Position.x - h->CurrentPos.x,\n"
     "                         car->State.Position.y - h->CurrentPos.y)",
     "bATan(car->State.Position.y - h->CurrentPos.y,\n"
     "                         car->State.Position.x - h->CurrentPos.x)"),
    ("hv_atan_sub", C, "bATan(car->State.Position.x - h->CurrentPos.x,",
     "bATan(h->CurrentPos.x - car->State.Position.x,"),
    ("hv_full", C, "make_relative_angle(h->Yaw - (FULL_TURN - f))",
     "make_relative_angle(h->Yaw + (FULL_TURN - f))"),
    ("hv_full_sign", C, "make_relative_angle(h->Yaw - (FULL_TURN - f))",
     "make_relative_angle(h->Yaw - (f - FULL_TURN))"),
    ("hv_rel", C, "make_relative_angle(h->Yaw - (FULL_TURN - f))",
     "(h->Yaw - (FULL_TURN - f))"),
    ("hv_scale", C, "#define HOVER_TURN         1.0f",
     "#define HOVER_TURN         1.5f"),
    ("hv_ret", C, "HOVER_TURN);\n    return 1;", "HOVER_TURN);\n    return 0;"),
    # ---- CheckMomentumWithinBounds
    ("mo_acc_val", C, "#define MOMENTUM_ACCEL     0.05f",
     "#define MOMENTUM_ACCEL     0.06f"),
    ("mo_ahead_val", C, "#define MOMENTUM_AHEAD     0.1f",
     "#define MOMENTUM_AHEAD     0.2f"),
    ("mo_push_val", C, "#define MOMENTUM_PUSH      0.29999998f",
     "#define MOMENTUM_PUSH      0.3f"),
    ("mo_ay", C, "float ay = h->Acceleration.y * MOMENTUM_ACCEL;",
     "float ay = h->Acceleration.y;"),
    ("mo_ax", C, "(h->Speed + h->Acceleration.x * MOMENTUM_ACCEL)",
     "(h->Speed + h->Acceleration.x)"),
    ("mo_x", C, "(h->Speed + h->Acceleration.x * MOMENTUM_ACCEL) * "
     "MOMENTUM_AHEAD;", "(h->Speed + h->Acceleration.x * MOMENTUM_ACCEL);"),
    ("mo_push", C, "float push = h->Speed * MOMENTUM_PUSH;",
     "float push = MOMENTUM_PUSH;"),
    ("mo_l", C, "    if (!chopper_test_location(h, x, ay + BOUNDS_PROBE))",
     "    if (chopper_test_location(h, x, ay + BOUNDS_PROBE))"),
    ("mo_l_sub", C, "        h->Acceleration.y = h->Acceleration.y - push;",
     "        h->Acceleration.y = h->Acceleration.y + push;"),
    ("mo_l_probe", C, "x, ay + BOUNDS_PROBE))", "x, ay + BOUNDS_STEP))"),
    ("mo_else", C, "    else if (!chopper_test_location(h, x, ay - "
     "BOUNDS_PROBE))", "    if (!chopper_test_location(h, x, ay - "
     "BOUNDS_PROBE))"),
    ("mo_r", C, "    else if (!chopper_test_location(h, x, ay - "
     "BOUNDS_PROBE))", "    else if (chopper_test_location(h, x, ay - "
     "BOUNDS_PROBE))"),
    ("mo_r_add", C, "        h->Acceleration.y = h->Acceleration.y + push;",
     "        h->Acceleration.y = h->Acceleration.y - push;"),
    ("mo_r_probe", C, "x, ay - BOUNDS_PROBE))", "x, ay + BOUNDS_PROBE))"),
    ("mo_f", C, "    if (!chopper_test_location(h, x + BOUNDS_PROBE, ay))",
     "    if (chopper_test_location(h, x + BOUNDS_PROBE, ay))"),
    ("mo_f_sub", C, "        h->Acceleration.x = h->Acceleration.x - push;",
     "        h->Acceleration.x = h->Acceleration.x + push;"),
    ("mo_f_probe", C, "x + BOUNDS_PROBE, ay))", "x - BOUNDS_PROBE, ay))"),
    # ---- Think
    ("th_mm", C, "    h->MoveMode = CHOPMOVE_PURSUIT;\n"
     "    if (chopper_high_level_planning(h, &t))",
     "    if (chopper_high_level_planning(h, &t))"),
    ("th_hlp", C, "    if (chopper_high_level_planning(h, &t))\n"
     "        return;", "    chopper_high_level_planning(h, &t);"),
    ("th_hover", C, "    if (chopper_hover_time(h, &t))\n        return;",
     "    chopper_hover_time(h, &t);"),
    ("th_rel", C, "a = make_relative_angle((float)bATan(t.Location.x, "
     "t.Location.y)", "a = ((float)bATan(t.Location.x, t.Location.y)"),
    ("th_atan_swap", C, "bATan(t.Location.x, t.Location.y)",
     "bATan(t.Location.y, t.Location.x)"),
    ("th_still", C, "if (fabsf(h->Speed) <= TURN_STILL",
     "if (fabsf(h->Speed) < TURN_STILL"),
    ("th_abs", C, "if (fabsf(h->Speed) <= TURN_STILL",
     "if (h->Speed <= TURN_STILL"),
    ("th_still_val", C, "#define TURN_STILL         0.001f",
     "#define TURN_STILL         0.002f"),
    ("th_and", C, "<= TURN_STILL && TURN_ANGLE < fabsf(a))",
     "<= TURN_STILL || TURN_ANGLE < fabsf(a))"),
    ("th_angle_val", C, "#define TURN_ANGLE         20.0f",
     "#define TURN_ANGLE         22.0f"),
    ("th_angle_abs", C, "TURN_ANGLE < fabsf(a))", "TURN_ANGLE < a)"),
    ("th_scale", C, "#define TURN_SCALE         2.0f",
     "#define TURN_SCALE         1.5f"),
    ("th_rot_mm", C, "        h->MoveMode = CHOPMOVE_ROTATE;\n"
     "        chopper_set_rotate_target(h, a, TURN_SCALE);",
     "        chopper_set_rotate_target(h, a, TURN_SCALE);"),
    ("th_rot_ret", C, "        chopper_set_rotate_target(h, a, TURN_SCALE);\n"
     "        return;", "        chopper_set_rotate_target(h, a, "
     "TURN_SCALE);"),
    ("th_y", C, "    chopper_set_y_accel(h, &t, a);",
     "    chopper_set_y_accel(h, &t, 0.0f);"),
    ("th_y_drop", C, "    chopper_set_y_accel(h, &t, a);\n", ""),
    ("th_x_drop", C, "    chopper_set_x_accel(h, &t);\n    chopper_check",
     "    chopper_check"),
    ("th_mom", C, "    chopper_check_momentum_within_bounds(h);\n}", "}"),
    # ---- CalcChopperRotation and SubtractFromYaw
    ("cr_lt", C, "    if (d < step)\n        step = d;",
     "    if (d > step)\n        step = d;"),
    ("cr_dir", C, "    if (to < from)\n        step = -step;",
     "    if (to > from)\n        step = -step;"),
    ("cr_add", C, "*cur = from + step;", "*cur = from - step;"),
    ("cr_abs", C, "float d = fabsf(to - from);", "float d = to - from;"),
    ("sy_sub", C, "float y = h->Yaw - f;", "float y = h->Yaw + f;"),
    ("sy_store", C, "    h->Yaw = y;\n    if (y < 0.0f)",
     "    if (y < 0.0f)"),
    ("sy_lt", C, "    if (y < 0.0f)\n        h->Yaw = y + FULL_TURN;",
     "    if (y <= 0.0f)\n        h->Yaw = y + FULL_TURN;"),
    ("sy_gt", C, "    else if (FULL_TURN < y)", "    else if (FULL_TURN <= y)"),
    ("sy_add", C, "h->Yaw = y + FULL_TURN;", "h->Yaw = y - FULL_TURN;"),
    ("sy_sub2", C, "h->Yaw = y - FULL_TURN;", "h->Yaw = y + FULL_TURN;"),
    ("sy_full", C, "#define FULL_TURN          360.0f",
     "#define FULL_TURN          361.0f"),
]

EQUIVALENT = {
    "pi_div": "BeginStakeout's two points are in the target route's table "
              "(its sign's or FindClosestPoint's), so d is 112k and both "
              "give k",
    "pi_ushift": "as pi_div: d is 112k, 16k is below 2^31, and the shift's "
                 "sign never shows",
    "hl_on_init": "on_sheet is read only by the stakeouts, START_CHASE and "
                  "PURSUIT, each after FindZValue set it; END_CHASE skips "
                  "the call and never ends in PURSUIT",
    "hl_flags_init": "flags is read only after a hit, which sets it, or by "
                     "CleverPursuitPlan's `(flags & 2) || !on_sheet` and "
                     "StartChaseLogic, which with on_sheet 0 never look",
    "hl_z_init": "as hl_flags_init: z goes only to StartChaseLogic, which "
                 "returns 1 before it with on_sheet 0",
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    indir = tempfile.TemporaryDirectory()
    lines, scp = write_inputs(indir.name)
    base = model(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text(encoding="latin-1").splitlines()
        if diff(base, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "chopper_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs)
    indir.cleanup()
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

    with tempfile.TemporaryDirectory() as tmp:
        lines, scp = write_inputs(tmp)
        got = model(lines)
        exe = build_harness(tmp)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text(encoding="latin-1").splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(got) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(got, harness)
    print("%d ops, %d lines, %d differ" % (len(lines), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
