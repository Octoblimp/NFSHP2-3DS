#!/usr/bin/env python3
"""Cross-check 3DS Files/source/realcontroller.c -- TrackedController and
RealController, the human player's car controller -- against the image
itself, run in mipsemu.

The model is the image: every method of both classes but the two
DoSnapshots runs as shipped, and so does everything beneath them that the
port has too -- CarController's constructor, destructor and small methods,
RealDriver's constructor and destructor and CarDriver's, SetTarget,
DriveTarget's constructor, Clear, AddPointToTarget,
FillWithCurrentAcceleration and BlendWithCurrentAcceleration,
StraightLinePredict and CalculateLookAheadDistance, Average and QuickSpline
whole, GetNearestRoutePoint, GetNextRoutePointAhead and IsValid,
TrackRoute::FindClosestPoint and TrackRoutePoint::GetPosition, the
TrackRouteManager's constructor and AddRouteToRightList,
Car::GetCarSpaceBoundingBox, bNormalize2, DriveTargetRenderer's
SetTargetToRender, and the vtable dispatch at every call either class makes
through a table. The harness runs the same op script on the port and prints
the same lines.

**The stand-ins.** Four calls are other tasks' and are stubbed by symbol in
the model and defined in the harness, each logging what it was handed:
RadialBlurOff (RealDriver's destructor), Car::SetMovementMode (CarController
::SetToPhysicsMode), and the joystick's AddJoyHandler and RemoveJoyHandler,
which fail loudly -- a RealDriver built here never adds its handlers.

**The heap.** Every bMalloc is logged on both sides with its name, the
image's size, flags and pool, and each block is named `hK` by the order the
blocks were asked for. A block is filled with 0xC3 before its constructor
runs, on both sides, so a field nothing writes reads the same poison. The
one exception is QuickSpline's point buffer: the image leaves it as the
heap had it and the port clears it (see quickspline.c), so the model clears
it too. Frees are logged by name and never done.

**Unset fields are poison in the model.** The Car, CarTypeInfo, Player and
collision body the model hands the image are filled with 0x55 before the
script sets the fields the controller is meant to read, image offset by
image offset; the harness's are zeroed and set by name. A field the image
reads that the port does not then shows as a difference. Each controller is
filled with a byte the script chooses, on both sides, before it is built.

**The routes** live in one byte arena laid out identically on both sides,
as airoute_check.py lays them out, and a pointer into it prints as `rK`,
`rK.pJ` or `a+N`. The manager is built and filled through the image's own
constructor and AddRouteToRightList in the model and the port's in the
harness.

**What is not compared.** Points[i].pad in a DriveTarget, for any point.
The points with no route come from the bVector2 forms of AddPointToTarget
and from StraightLinePredict's slow path, where the image leaves stack
garbage and the port writes 0 (drivetarget.h, STACK-W). The ones
RouteDeltaPredict adds are garbage on the console too: the image's
GetPosition(bVector3) stores all four VU0 lanes, and the fourth comes from
two stack words (12(sp) and 44(sp)) it never sets. The port's
trpoint_get_position3 leaves the pad as the car's position had it.

Scenarios: both tables slot by slot; the constructors over two fills, with
the car on a route and off every one; TrackedController's methods, its
Think across the update period, FindWhereIAm's every path and
GetAmountOutOfBounds either side of both widths; PlayerDriveLineNumber;
RouteDeltaPredict over targets already holding 0 to 20 points, every exit,
both clamps and a signposted branch; ComboPredict either side of each of its
four tests; CalculateLateral over its history filling and shifting, invalid
entries, the repeat and NULL-route cases, and too few points; Think over
laps of a route at speed, slow, off every route, the wrong way, at a route's
end, followed by the camera and with DoSpeedDifferencePrinting on; every
slot through each table; and the destructors with each pointer NULL.

    python tools/realcontroller_check.py
    python tools/realcontroller_check.py --mutate [--only a,b]
    python tools/realcontroller_check.py --dump out/realcontroller
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
import airoute_check as ar
import hostbuild
import physicscar_check as pcc
from mipsemu import Emu, M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/realcontroller_test.c"
RCC = "3DS Files/source/realcontroller.c"
RCH = "3DS Files/source/realcontroller.h"
DTRC = "3DS Files/source/drivetargetrenderer.c"
SOURCES = [HARNESS, RCC, DTRC,
           "3DS Files/source/carcontroller.c",
           "3DS Files/source/realdriver.c",
           "3DS Files/source/cardriver.c",
           "3DS Files/source/drivetarget.c",
           "3DS Files/source/airoute.c",
           "3DS Files/source/average.c",
           "3DS Files/source/table.c",
           "3DS Files/source/car.c",
           "3DS Files/source/carstate.c",
           "3DS Files/source/trackroute.c",
           "3DS Files/source/trackpath.c",
           "3DS Files/source/quickspline.c",
           "3DS Files/source/bchunk.c",
           "3DS Files/source/world.c",
           "3DS Files/source/graph.c",
           "3DS Files/source/race.c",
           "3DS Files/source/copmanager.c",
           "3DS Files/source/replay.c",
           "3DS Files/source/p32.c",
           "3DS Files/source/bmem.c",
           "3DS Files/source/vtable.c",
           "3DS Files/source/emath.c",
           "3DS Files/source/bmatrix.c",
           "3DS Files/source/bvector.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c"]

HARNESS_TIMEOUT = 300

# ================================================================ the image

# The fixed objects, above the emulator's heap and below its stack.
CAR = 0x01E01000                    # Car, 0x1000 reserved
CTI = 0x01E02000                    # CarTypeInfo
PLAYER = 0x01E03000                 # Player, 0x400
BODY = 0x01E03800                   # CarCollisionBody, 336 bytes
CTRL = [0x01E04000, 0x01E04100]     # two controllers, 84 bytes each
TGT = 0x01E04400                    # a DriveTarget, 528 bytes
OUT = 0x01E04800                    # CalculateLateral's two outputs
HEAP = 0x01C00000                   # bMalloc's blocks
HEAP_END = 0x01D00000

STATE = CAR + 64
POS = STATE + 32
VEL = STATE + 48
ACC = STATE + 64
FILL = 0x55
HEAP_FILL = 0xC3
CTRL_SIZE = 84
TGT_SIZE = 528
OUT_FILL = 0x7F7F7F7F

ARENA, ARENA_SIZE = ar.ARENA, ar.ARENA_SIZE
SIGNS, NSIGNS = ar.SIGNS, ar.NSIGNS
HDR, PT = ar.HDR, ar.PT
MGR = ar.MGR

VT_TC = 0x002A0960
VT_RC = 0x002A0B00
VT_CC = 0x0029A6E0
VT_RD = 0x00292A70
VT_CD = 0x002924A8
BASIS = "OverhauserBasisMatricies"

# The globals the script sets, by name or address.
GLOBS = [
    ("WorldTimer", "WorldTimer"),
    ("CameraFollowThisCarInstead", "CameraFollowThisCarInstead"),
    ("DoSpeedDifferencePrinting", "DoSpeedDifferencePrinting"),
    ("HasTargetMarkers", "TheDriveTargetRenderer"),
    ("TrackLength", ar.TPM),
    ("TrackDirection", ar.TRACKDIR),
    ("NumSignposts", ar.NSIGN_PTR),
]
G = {name: i for i, (name, _) in enumerate(GLOBS)}

# The fields the script sets, at their image addresses. Width 2 is the
# int16 DriverNumber and the uint16 Angle.
CARF = [
    ("DriverNumber", CAR + 10, 2),
    ("TheMovementMode", CAR + 36, 4),
    ("Position.x", POS, 4), ("Position.y", POS + 4, 4),
    ("Position.z", POS + 8, 4), ("Position.pad", POS + 12, 4),
    ("Velocity.x", VEL, 4), ("Velocity.y", VEL + 4, 4),
    ("Velocity.z", VEL + 8, 4), ("Velocity.pad", VEL + 12, 4),
    ("Acceleration.x", ACC, 4), ("Acceleration.y", ACC + 4, 4),
    ("BodyMatrix.v1.x", STATE + 96, 4), ("BodyMatrix.v1.y", STATE + 100, 4),
    ("Angle", STATE + 868, 2),
    ("ForwardSpeed", STATE + 892, 4),
    ("VelocityMagnitude", STATE + 896, 4),
    ("BoostFactor", STATE + 924, 4),
    ("DistanceAroundTrack", CAR + 1860, 4),
    ("CarClass", CTI + 236, 4),
    ("PlayerNumber", PLAYER + 16, 4),
    ("bWrongWay", PLAYER + 736, 4),
    ("LocalBBMin.x", BODY + 224, 4), ("LocalBBMin.y", BODY + 228, 4),
    ("LocalBBMin.z", BODY + 232, 4),
    ("LocalBBMax.x", BODY + 240, 4), ("LocalBBMax.y", BODY + 244, 4),
    ("LocalBBMax.z", BODY + 248, 4),
]
C = {name: i for i, (name, _, _) in enumerate(CARF)}

# The controller's fields the script may set, at image offsets. A `ref`
# field takes an arena offset, -1 for NULL; a `clear` field only NULL.
CTLF = [
    ("RoutePoint", 12, "ref"), ("TimeBeforeUpdate", 16, "word"),
    ("Acceleration", 20, "word"), ("PrevSpeed", 24, "word"),
    ("PreviousLateralOffsetFromLine", 36, "word"),
    ("NumPreviousRoutePoints", 44, "word"),
    ("Prev0.Route", 48, "ref"), ("Prev0.Point", 52, "ref"),
    ("Prev1.Route", 56, "ref"), ("Prev1.Point", 60, "ref"),
    ("Prev2.Route", 64, "ref"), ("Prev2.Point", 68, "ref"),
    ("Prev3.Route", 72, "ref"), ("Prev3.Point", 76, "ref"),
    ("Driver", 4, "clear"), ("Average", 40, "clear"),
    ("Spline", 80, "clear"),
]
K = {name: i for i, (name, _, _) in enumerate(CTLF)}

# ---- the ops -----------------------------------------------------------------
#
# Each op is its code, its argument count and its arguments, so OP_WORDS and
# OP_SIGNS can carry a run.

(OP_TAG, OP_CLEAR, OP_WORDS, OP_ROUTE, OP_SIGNS, OP_RESET, OP_ADD,
 OP_FILL, OP_INIT, OP_TINIT, OP_DUMP, OP_CARF, OP_GLOB, OP_CTLF, OP_CALL,
 OP_VT, OP_TGT, OP_STATIC) = range(18)

ARGS = {OP_TAG: 1, OP_CLEAR: 0, OP_WORDS: None, OP_ROUTE: 2,
        OP_SIGNS: None, OP_RESET: 0, OP_ADD: 1, OP_FILL: 2, OP_INIT: 1,
        OP_TINIT: 1, OP_DUMP: 1, OP_CARF: 2, OP_GLOB: 2, OP_CTLF: 3,
        OP_CALL: 6, OP_VT: 4, OP_TGT: None, OP_STATIC: 0}

(F_THINK, F_TTHINK, F_FIND, F_OOB, F_SET_ROUTE, F_GET_ROUTE, F_GET_POINT,
 F_GET_ACC, F_JUST_RESET, F_LINE, F_RDP, F_COMBO, F_LATERAL, F_DESTROY,
 F_TDESTROY) = range(15)

FN_SYM = {
    F_THINK: "Think__14RealControllerf",
    F_TTHINK: "Think__17TrackedControllerf",
    F_FIND: "FindWhereIAm__17TrackedController",
    F_OOB: "GetAmountOutOfBounds__17TrackedController",
    F_SET_ROUTE: "SetCurrentRoute__17TrackedControllerP10TrackRoute"
                 "P15TrackRoutePoint",
    F_GET_ROUTE: "GetCurrentRoute__17TrackedController",
    F_GET_POINT: "GetCurrentRoutePoint__17TrackedController",
    F_GET_ACC: "GetAcceleration__17TrackedController",
    F_JUST_RESET: "JustReset__17TrackedController",
    F_LINE: "PlayerDriveLineNumber__14RealController",
    F_RDP: "RouteDeltaPredict__14RealControllerP11DriveTargetff"
           "P10TrackRouteP15TrackRoutePoint",
    F_COMBO: "ComboPredict__14RealControllerP11DriveTargetff"
             "P10TrackRouteP15TrackRoutePoint",
    F_LATERAL: "CalculateLateralPostionAndVelocityWRTDrivingLine"
               "__14RealControllerPfT1fP10TrackRouteP15TrackRoutePoint",
    F_DESTROY: "_$_14RealController",
    F_TDESTROY: "_$_17TrackedController",
}

# The port's function for each image symbol a table slot holds.
FNMAP = {
    "_$_17TrackedController": "trackedcontroller_destroy",
    "_$_14RealController": "realcontroller_destroy",
    "DebugDisplay__13CarController": "carcontroller_debug_display",
    "DoSnapshot__17TrackedControllerP14ReplaySnapshot":
        "trackedcontroller_do_snapshot",
    "DoSnapshot__14RealControllerP14ReplaySnapshot":
        "realcontroller_do_snapshot",
    "Think__17TrackedControllerf": "trackedcontroller_think",
    "Think__14RealControllerf": "realcontroller_think",
    FN_SYM[F_SET_ROUTE]: "trackedcontroller_set_current_route",
    FN_SYM[F_GET_ROUTE]: "trackedcontroller_get_current_route",
    FN_SYM[F_GET_POINT]: "trackedcontroller_get_current_route_point",
    FN_SYM[F_OOB]: "trackedcontroller_get_amount_out_of_bounds",
    FN_SYM[F_FIND]: "trackedcontroller_find_where_i_am",
    FN_SYM[F_JUST_RESET]: "trackedcontroller_just_reset",
    "SetToPhysicsMode__13CarControllerP3Car":
        "carcontroller_set_to_physics_mode",
    "ForceBoost__13CarControllerf": "carcontroller_force_boost",
    "ReleaseBoost__13CarController": "carcontroller_release_boost",
}

# Every slot but DoSnapshot's (24) is called through the table.
VT_SLOTS = [8, 16, 32, 40, 48, 56, 64, 72, 80, 88, 96, 104]

# FindClosestPoint's flags, and a point's Bits with no sign, Posted.
POSTED = ar.TRP_POSTED
BITS = ar.NO_SIGN | POSTED


def fb(x):
    """A Python float's single-precision bits."""
    return struct.unpack("<I", struct.pack("<f", x))[0]


def bf(b):
    return struct.unpack("<f", struct.pack("<I", b & M32))[0]


def f32(x):
    return bf(fb(x))


def fnv(data):
    h = 0x811C9DC5
    for b in data:
        h = ((h ^ b) * 0x01000193) & M32
    return h


def s8(v):
    return (v ^ 0x80) - 0x80


def s16(v):
    return (v ^ 0x8000) - 0x8000


class Script(object):
    def __init__(self):
        self.ops = []
        self.tags = []

    def op(self, code, *args):
        assert ARGS[code] is None or len(args) == ARGS[code], (code, args)
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
            flat.append(o[0])
            flat.append(len(o) - 1)
            flat.extend(o[1:])
        out.append(len(flat))
        out.extend(flat)
        return struct.pack("<%di" % len(out), *[s32(v & M32) for v in out])

    # ---- sugar -----------------------------------------------------------

    def blob(self, off, data):
        assert off % 4 == 0 and len(data) % 4 == 0
        self.op(OP_WORDS, off,
                *struct.unpack("<%dI" % (len(data) // 4), bytes(data)))

    def word(self, off, w):
        self.op(OP_WORDS, off, w & M32)

    def signs(self, table):
        """All 256 entries: `table` maps an index to its two words."""
        ws = []
        for i in range(NSIGNS):
            ws.extend(table.get(i, ar.DEFAULT_SIGN))
        self.op(OP_SIGNS, 0, *ws)

    def carf(self, name, v):
        self.op(OP_CARF, C[name], v)

    def glob(self, name, v):
        self.op(OP_GLOB, G[name], v)

    def ctlf(self, slot, name, v):
        self.op(OP_CTLF, slot, K[name], v)

    def call(self, fn, slot=0, a=0, b=0, c=0, d=0, dump=True):
        self.op(OP_CALL, fn, slot, a, b, c, d)
        if dump:
            self.op(OP_DUMP, slot)

    def target(self, seed, n):
        self.op(OP_TGT, *struct.unpack("<%dI" % (TGT_SIZE // 4),
                                       target_bytes(seed, n)))

    def vt(self, slot, vslot, a=0, b=0, dump=True):
        self.op(OP_VT, slot, vslot, a, b)
        if dump:
            self.op(OP_DUMP, slot)


# ================================================================ the routes


class Road(object):
    """A route's points as the script built them, for placing the car."""

    def __init__(self, slot, off, number, pts, dists):
        self.slot, self.off, self.number = slot, off, number
        self.pts, self.dists = pts, dists

    def ref(self, i=None):
        return self.off if i is None else self.off + HDR + PT * i

    def frame(self, i):
        """Point i's position and unit direction, as floats."""
        p = self.pts[i]
        j = min(i, len(self.pts) - 2)
        if len(self.pts) < 2:
            return p.x, p.y, 1.0, 0.0
        q, r = self.pts[j], self.pts[j + 1]
        ln = math.hypot(r.x - q.x, r.y - q.y)
        return p.x, p.y, (r.x - q.x) / ln, (r.y - q.y) / ln


def road_bytes(number, rtype, pts, rnd, posted=True, lines=True,
               widths=None):
    """airoute_check's route, with widths, slopes, elevations, driving
    lines and speeds that vary point to point. `widths` fixes (left,
    right) on every point; the random ones are drawn either way."""
    b = ar.route_bytes(number, rtype, pts)
    for i in range(len(pts)):
        o = HDR + PT * i
        struct.pack_into("<f", b, o + 8, rnd.uniform(-2.0, 6.0))
        lw, rw = rnd.uniform(5.0, 10.0), rnd.uniform(5.0, 10.0)
        struct.pack_into("<ff", b, o + 24, *(widths or (lw, rw)))
        struct.pack_into("<ff", b, o + 32, rnd.uniform(-0.1, 0.1),
                         rnd.uniform(-0.05, 0.05))
        struct.pack_into("<I", b, o + 44, BITS if posted else ar.NO_SIGN)
        if lines:
            for k in range(21):
                off = (k - 10) * 0.45 + 0.8 * math.sin(0.7 * i + k)
                struct.pack_into("<h", b, o + 48 + 2 * k,
                                 int(round(off * 256.0)))
                b[o + 90 + k] = rnd.randrange(12, 90)
    return b


class Arena(object):
    """Routes back to back, as the loader finds them."""

    def __init__(self, sc, start=64):
        self.sc = sc
        self.at = start
        self.roads = []
        sc.op(OP_CLEAR)

    def route(self, number, rtype, pts, rnd, **kw):
        b = road_bytes(number, rtype, pts, rnd, **kw)
        off = self.at
        self.sc.blob(off, b)
        slot = len(self.roads)
        self.sc.op(OP_ROUTE, slot, off)
        dists = [struct.unpack_from("<f", b, HDR + PT * i + 40)[0]
                 for i in range(len(pts))]
        road = Road(slot, off, number, pts, dists)
        self.roads.append(road)
        self.at += len(b)
        assert self.at <= ARENA_SIZE
        return road

    def register(self):
        self.sc.op(OP_RESET)
        for r in self.roads:
            self.sc.op(OP_ADD, r.off)


def curve(n, x0, y0, step, amp, period):
    return [ar.Pt(x0 + step * i, y0 + amp * math.sin(i / period))
            for i in range(n)]


def network(sc, seed=0x5ca1e):
    """The routes every scenario but the branch's drives on.

    r0  number 3, racing: 48 points, a gentle S.
    r1  number 7, racing: 6 points in a straight line, for running out.
    r2  number 75, traffic: IsValid refuses anything 70 or above.
    r3  number 12, racing: a single point.
    r4  number 20, racing, no point Posted: FindWhereIAm never finds it.
    """
    rnd = random.Random(seed)
    a = Arena(sc)
    sc.signs({})
    sc.glob("NumSignposts", 0)
    a.route(3, 0, curve(48, 0.0, 0.0, 10.0, 25.0, 7.0), rnd)
    a.route(7, 0, ar.line(6, 600.0, 200.0, 12.0, 0.0), rnd)
    a.route(75, 1, ar.line(5, 0.0, -300.0, 15.0, 0.0), rnd)
    a.route(12, 0, [ar.Pt(-400.0, 0.0)], rnd)
    a.route(20, 0, ar.line(30, 0.0, 500.0, 10.0, 0.0), rnd, posted=False)
    a.register()
    sc.glob("TrackLength", 480.0)
    sc.glob("TrackDirection", 0)
    return a


def place(sc, road, i, lat=0.0, along=0.0, speed=20.0, fs=None, side=1,
          slip=0.0, acc=(0.0, 0.0)):
    """The car on `road` at point i, `lat` to the right and `along` ahead,
    moving at `speed` along the road, `slip` of it sideways."""
    x, y, dx, dy = road.frame(i)
    rx, ry = dy, -dx
    sc.carf("Position.x", x + dx * along + rx * lat)
    sc.carf("Position.y", y + dy * along + ry * lat)
    sc.carf("Velocity.x", dx * speed + rx * slip)
    sc.carf("Velocity.y", dy * speed + ry * slip)
    sc.carf("VelocityMagnitude", math.hypot(speed, slip))
    sc.carf("ForwardSpeed", speed if fs is None else fs)
    sc.carf("BodyMatrix.v1.x", -dy * side)
    sc.carf("BodyMatrix.v1.y", dx * side)
    sc.carf("Acceleration.x", acc[0])
    sc.carf("Acceleration.y", acc[1])
    sc.carf("Angle", int(math.atan2(dy, dx) / (2 * math.pi) * 65536)
            & 0xFFFF)
    sc.carf("DistanceAroundTrack", road.dists[i] + along)


# ================================================================ the script


def setup(sc):
    """Every field the script sets, to a sane car at rest."""
    for name, v in [("DriverNumber", 2), ("TheMovementMode", 1),
                    ("Position.x", 0.0), ("Position.y", 0.0),
                    ("Position.z", 1.25), ("Position.pad", 0.5),
                    ("Velocity.x", 0.0), ("Velocity.y", 0.0),
                    ("Velocity.z", 0.0), ("Velocity.pad", -0.25),
                    ("Acceleration.x", 0.0), ("Acceleration.y", 0.0),
                    ("BodyMatrix.v1.x", 0.0), ("BodyMatrix.v1.y", 1.0),
                    ("Angle", 0), ("ForwardSpeed", 0.0),
                    ("VelocityMagnitude", 0.0), ("BoostFactor", 1.0),
                    ("DistanceAroundTrack", 0.0), ("CarClass", 2),
                    ("PlayerNumber", 1), ("bWrongWay", 0),
                    ("LocalBBMin.x", -2.1), ("LocalBBMin.y", -0.95),
                    ("LocalBBMin.z", -0.4), ("LocalBBMax.x", 2.3),
                    ("LocalBBMax.y", 0.9), ("LocalBBMax.z", 1.1)]:
        sc.carf(name, v)
    sc.glob("WorldTimer", 5000)
    sc.glob("CameraFollowThisCarInstead", -1)
    sc.glob("DoSpeedDifferencePrinting", 0)
    sc.glob("HasTargetMarkers", 0)


def fresh(sc, slot=0, fill=0xA5, tracked=False):
    sc.op(OP_FILL, slot, fill)
    sc.op(OP_TINIT if tracked else OP_INIT, slot)


def scenario_static(sc):
    sc.tag("static")
    sc.op(OP_STATIC)


def scenario_ctor(sc):
    sc.tag("ctor")
    net = network(sc)
    r0 = net.roads[0]
    # On the road: FindWhereIAm's search from nothing finds a point.
    place(sc, r0, 5, lat=1.5, speed=0.0)
    fresh(sc, 0, 0xA5)
    sc.op(OP_DUMP, 0)
    # Off every road.
    sc.carf("Position.x", 5000.0)
    sc.carf("Position.y", -5000.0)
    fresh(sc, 1, 0x5A)
    sc.op(OP_DUMP, 1)
    sc.call(F_DESTROY, 0, 3)
    sc.call(F_DESTROY, 1, 2)
    # TrackedController alone, on and off the road.
    place(sc, r0, 20, lat=-2.0, speed=15.0)
    fresh(sc, 0, 0x3C, tracked=True)
    sc.op(OP_DUMP, 0)
    sc.carf("Position.x", 5000.0)
    fresh(sc, 1, 0x00, tracked=True)
    sc.op(OP_DUMP, 1)
    sc.call(F_TDESTROY, 0, 0)
    sc.call(F_TDESTROY, 1, 1)


def scenario_tracked(sc, rnd):
    sc.tag("tracked")
    net = network(sc)
    r0, r1, r2, r3, r4 = net.roads
    place(sc, r0, 10, speed=12.0)
    for tracked in (True, False):
        slot = 0 if tracked else 1
        fresh(sc, slot, 0x77, tracked=tracked)
        sc.op(OP_DUMP, slot)
        # The small ones.
        for route, point in ((r0.ref(), r0.ref(10)), (-1, r1.ref(3)),
                             (r2.ref(), r2.ref(1)), (r0.ref(), -1),
                             (r3.ref(), r3.ref(0))):
            sc.carf("VelocityMagnitude", rnd.uniform(0.0, 40.0))
            sc.call(F_SET_ROUTE, slot, route, point)
            sc.call(F_GET_ROUTE, slot, dump=False)
            sc.call(F_GET_POINT, slot, dump=False)
            sc.call(F_GET_ACC, slot, dump=False)
            sc.call(F_JUST_RESET, slot)
        # Out of bounds either side of both widths, and with no point.
        sc.call(F_SET_ROUTE, slot, r0.ref(), r0.ref(12), dump=False)
        for lat in (-12.0, -9.5, -8.0, -5.0, -0.5, 0.0, 0.5, 4.0, 7.9,
                    9.99, 10.0, 11.0, 30.0):
            for along in (-3.0, 0.0, 4.0):
                place(sc, r0, 12, lat=lat, along=along)
                sc.call(F_OOB, slot, dump=False)
        sc.ctlf(slot, "RoutePoint", -1)
        sc.call(F_OOB, slot, dump=False)
        # FindWhereIAm from a point, from none, off the road, too far.
        cases = [
            (r0.ref(10), r0, 11, 0.0),      # the next point
            (r0.ref(10), r0, 10, 6.0),      # inside the width
            (r0.ref(10), r0, 10, 13.0),     # found, then over 5 outside
            (r0.ref(10), r0, 10, -16.0),
            (r0.ref(10), r0, 30, 0.0),      # nothing within 24 of it
            (-1, r0, 25, 2.0),              # from nothing
            (-1, r4, 5, 0.0),               # r4's points are not Posted
            (r1.ref(2), r1, 4, 0.0),
            (r1.ref(2), r0, 40, 0.0),       # r1's point, the car on r0
            (r3.ref(0), r3, 0, 1.0),
            (r0.ref(47), r0, 47, 0.0),
            (r0.ref(0), r0, 0, -3.0),
        ]
        for rp, road, i, lat in cases:
            place(sc, road, i, lat=lat, speed=rnd.uniform(5.0, 30.0))
            sc.ctlf(slot, "RoutePoint", rp)
            sc.call(F_FIND, slot)
        # The track distance changes what the search prefers.
        for dat in (0.0, 100.0, 240.0, 479.0, -20.0):
            place(sc, r0, 20, lat=1.0)
            sc.carf("DistanceAroundTrack", dat)
            sc.ctlf(slot, "RoutePoint", -1)
            sc.call(F_FIND, slot)
        # Think across the period: straight in, through the table.
        place(sc, r0, 15, speed=20.0)
        sc.call(F_FIND, slot)
        for dt in (0.03, 0.03, 0.03, 0.03, 0.1, 0.0999, 0.0001, 0.25, 0.5,
                   0.0, 0.1, 0.1, 1.0 / 30.0, 1.0 / 30.0, 1.0 / 30.0):
            sc.carf("VelocityMagnitude", rnd.uniform(0.0, 50.0))
            sc.call(F_TTHINK, slot, fb(dt))
        for k in range(30):
            place(sc, r0, 15 + k // 3, lat=rnd.uniform(-4.0, 4.0),
                  along=rnd.uniform(0.0, 9.0), speed=rnd.uniform(0.0, 50.0))
            sc.vt(slot, 32, fb(rnd.choice((1.0 / 60.0, 1.0 / 30.0, 0.07))))
        sc.ctlf(slot, "TimeBeforeUpdate", 0.0)
        sc.ctlf(slot, "PrevSpeed", 7.0)
        sc.call(F_TTHINK, slot, fb(0.0))
    sc.call(F_TDESTROY, 0, 0)
    sc.call(F_DESTROY, 1, 2)


def scenario_line(sc):
    sc.tag("line")
    net = network(sc)
    place(sc, net.roads[0], 3)
    fresh(sc, 0)
    for cls in (0, 1, 2, 3, 4, 5, 7, 10, 15):
        sc.carf("CarClass", cls)
        sc.call(F_LINE, 0, dump=False)
    sc.carf("CarClass", 2)
    sc.call(F_DESTROY, 0, 2)


def scenario_rdp(sc, rnd):
    sc.tag("rdp")
    net = network(sc)
    r0, r1 = net.roads[0], net.roads[1]
    place(sc, r0, 4, speed=20.0)
    fresh(sc, 0)
    # A grid over the offset and its speed first, then at random.
    for vel in (-3.0, -0.5, 0.0, 0.4, 2.5):
        for pos in (-9.0, -2.0, 0.0, 1.5, 7.0, 15.0):
            place(sc, r0, 6, speed=25.0)
            sc.target(0, 0)
            sc.call(F_RDP, 0, fb(vel), fb(pos), r0.ref(), r0.ref(6),
                    dump=False)
    # A NULL route with a point. GetNextRoutePointAhead leaves both as
    # they are, so only the route's test sends the walk to its end.
    place(sc, r0, 6, speed=25.0)
    sc.target(0, 5)
    sc.call(F_RDP, 0, fb(0.5), fb(1.0), -1, r0.ref(6), dump=False)
    for n in range(120):
        road = r0 if rnd.random() < 0.8 else r1
        i = rnd.randrange(len(road.pts))
        speed = rnd.choice((0.5, 3.0, 10.0, 18.0, 30.0, 55.0, 90.0))
        place(sc, road, i, lat=rnd.uniform(-3.0, 3.0), speed=speed)
        sc.carf("CarClass", rnd.choice((0, 1, 2, 3, 4, 7, 10, 13)))
        if rnd.random() < 0.2:
            sc.carf("LocalBBMax.y", rnd.uniform(0.2, 4.0))
            sc.carf("LocalBBMin.y", -rnd.uniform(0.2, 4.0))
        sc.carf("Position.pad", rnd.uniform(-3.0, 3.0))
        sc.target(rnd.randrange(256),
              rnd.choice((0, 0, 0, 1, 5, 12, 17, 19, 20)))
        sc.call(F_RDP, 0, fb(rnd.uniform(-5.0, 5.0)),
                fb(rnd.uniform(-20.0, 20.0)), road.ref(), road.ref(i),
                dump=False)
    sc.carf("CarClass", 2)
    sc.carf("LocalBBMin.y", -0.95)
    sc.carf("LocalBBMax.y", 0.9)
    sc.call(F_DESTROY, 0, 2)


def scenario_branch(sc, rnd):
    """A signposted point: RouteDeltaPredict and Think follow the branch."""
    sc.tag("branch")
    a = Arena(sc)
    brnd = random.Random(0xb4a)
    main = a.route(3, 0, ar.line(20, 0.0, 0.0, 10.0, 0.0), brnd)
    side = a.route(9, 0, ar.line(20, 105.0, 3.0, 9.0, 1.5), brnd)
    back = a.route(11, 0, ar.line(20, 60.0, -40.0, 10.0, 0.0), brnd)
    # r0.p8 branches to r1.p0, ahead; r1.p10 to r2.p0, behind, which
    # GetNextRoutePointAhead steps on from.
    sc.word(main.ref(8) + 44, (BITS & ~0xFF) | 5)
    sc.word(side.ref(10) + 44, (BITS & ~0xFF) | 6)
    sc.signs({5: ar.sign(9, 2, 0), 6: ar.sign(11, 0, 0)})
    sc.glob("NumSignposts", NSIGNS)
    a.register()
    sc.glob("TrackLength", 480.0)
    sc.glob("TrackDirection", 0)
    place(sc, main, 2, speed=30.0)
    fresh(sc, 0)
    for i in (2, 5, 7, 8):
        for speed in (12.0, 40.0, 70.0):
            place(sc, main, i, speed=speed)
            sc.target(i, 0)
            sc.call(F_RDP, 0, fb(0.5), fb(-1.0), main.ref(), main.ref(i),
                    dump=False)
    for i in (6, 9, 10, 12):
        place(sc, side, i, speed=35.0)
        sc.target(i, 0)
        sc.call(F_RDP, 0, fb(-0.5), fb(2.0), side.ref(), side.ref(i),
                dump=False)
    for k in range(40):
        place(sc, main, min(2 + k // 4, 19), lat=rnd.uniform(-1.0, 1.0),
              along=rnd.uniform(0.0, 9.0), speed=30.0)
        sc.call(F_THINK, 0, fb(1.0 / 30.0))
    sc.call(F_DESTROY, 0, 2)


def scenario_combo(sc, rnd):
    sc.tag("combo")
    net = network(sc)
    r0 = net.roads[0]
    place(sc, r0, 4)
    fresh(sc, 0)
    for n in range(90):
        i = rnd.randrange(2, 40)
        x, y, dx, dy = r0.frame(i)
        # The heading off the road's by an angle whose cosine straddles
        # 0.99.
        ang = rnd.choice((0.0, 0.1, 0.14, 0.1415, 0.142, 0.2, 1.0, 3.0))
        ang *= rnd.choice((-1, 1))
        speed = rnd.choice((5.0, 20.0, 40.0, 70.0))
        place(sc, r0, i, lat=rnd.uniform(-2.0, 2.0), speed=speed)
        c, s = math.cos(ang), math.sin(ang)
        sc.carf("Velocity.x", (dx * c - dy * s) * speed)
        sc.carf("Velocity.y", (dy * c + dx * s) * speed)
        # When it falls through to FillWithCurrentAcceleration: either side
        # of the bar there, an acceleration of three quarters of the speed.
        k = rnd.choice((0.0, 0.3, 0.7, 0.8, 1.5))
        aa = rnd.uniform(0.0, 2.0 * math.pi)
        sc.carf("Acceleration.x", math.cos(aa) * speed * k)
        sc.carf("Acceleration.y", math.sin(aa) * speed * k)
        vel = rnd.choice((0.0, 3.0, 5.99, 6.0, 6.01, 9.0))
        pos = rnd.choice((0.0, 5.0, 11.99, 12.0, 12.01, 20.0))
        sc.carf("VelocityMagnitude", rnd.choice((speed, 1.0, 30.0, 63.0)))
        sc.carf("CarClass", rnd.choice((0, 1, 2, 3, 4)))
        sc.target(n, rnd.choice((0, 0, 3)))
        sc.call(F_COMBO, 0, fb(vel * rnd.choice((-1, 1))),
                fb(pos * rnd.choice((-1, 1))), r0.ref(), r0.ref(i),
                dump=False)
    sc.carf("CarClass", 2)
    sc.call(F_DESTROY, 0, 2)


def scenario_lateral(sc, rnd):
    sc.tag("lateral")
    net = network(sc)
    r0, r1, r2, r3 = net.roads[:4]
    place(sc, r0, 3)
    fresh(sc, 0)
    # Too few points: none kept and a lone point, and no point at all.
    place(sc, r3, 0, lat=0.5)
    sc.call(F_LATERAL, 0, fb(0.05), r3.ref(), r3.ref(0))
    sc.call(F_LATERAL, 0, fb(0.05), -1, -1)
    fresh(sc, 0, 0x11)
    # The history filling and shifting as the car goes down r0.
    j = 3
    for k in range(60):
        if rnd.random() < 0.35:
            j = min(j + 1, 46)
        place(sc, r0, j, lat=rnd.uniform(-5.0, 5.0),
              along=rnd.uniform(0.0, 8.0), speed=25.0,
              side=rnd.choice((1, -1)))
        sc.carf("CarClass", rnd.choice((0, 2, 2, 4)))
        sc.call(F_LATERAL, 0, fb(rnd.choice((1.0 / 30.0, 0.001, 0.1))),
                r0.ref(), r0.ref(j))
    # The same point again, and a NULL route, with some kept.
    sc.call(F_LATERAL, 0, fb(0.03), r0.ref(), r0.ref(j))
    sc.call(F_LATERAL, 0, fb(0.03), -1, r0.ref(j - 1))
    # Entries that are no longer good: a route IsValid refuses, a point
    # from another route, a NULL route, and a point past the end.
    for bad in ((r2.ref(), r2.ref(1)), (r0.ref(), r1.ref(2)),
                (-1, r0.ref(5)), (r1.ref(), r1.ref(0) + PT * 7)):
        for e in range(4):
            sc.ctlf(0, "Prev%d.Route" % e, r0.ref())
            sc.ctlf(0, "Prev%d.Point" % e, r0.ref(20 + e))
        sc.ctlf(0, "NumPreviousRoutePoints", 4)
        sc.ctlf(0, "Prev%d.Route" % rnd.randrange(4), bad[0])
        sc.ctlf(0, "Prev%d.Point" % rnd.randrange(4), bad[1])
        place(sc, r0, 22, lat=1.0, speed=25.0)
        sc.call(F_LATERAL, 0, fb(0.03), r0.ref(), r0.ref(24))
    # The newest gone bad, and every one: the walk starts from `p`.
    sc.ctlf(0, "Prev3.Route", -1)
    sc.call(F_LATERAL, 0, fb(0.03), r0.ref(), r0.ref(26))
    for e in range(4):
        sc.ctlf(0, "Prev%d.Route" % e, r2.ref())
    sc.call(F_LATERAL, 0, fb(0.03), r0.ref(), r0.ref(27))
    # A NULL route with none kept: IsValid refuses it, so there are no
    # points, and the too-few exit returns before anything is kept.
    fresh(sc, 0, 0x22)
    sc.call(F_LATERAL, 0, fb(0.03), -1, r0.ref(9))
    sc.call(F_LATERAL, 0, fb(0.03), r0.ref(), r0.ref(10))
    # Near the end of r1, the walk runs out.
    for i in range(6):
        place(sc, r1, i, lat=0.7)
        sc.call(F_LATERAL, 0, fb(0.03), r1.ref(), r1.ref(i))
    sc.call(F_DESTROY, 0, 2)
    # Too few points once the Average has been fed: the velocity is its
    # mean, not 0. Every too-few exit above came before any feeding.
    fresh(sc, 1, 0x23)
    for i in (10, 11, 12, 13):
        place(sc, r0, i, lat=0.4 * i - 3.0, speed=25.0)
        sc.call(F_LATERAL, 1, fb(0.03), r0.ref(), r0.ref(i))
    sc.ctlf(1, "NumPreviousRoutePoints", 0)
    sc.call(F_LATERAL, 1, fb(0.03), r2.ref(), r2.ref(1))
    sc.call(F_DESTROY, 1, 2)


def drive(sc, rnd, slot, road, frames, start=0, speed=25.0, dt=1.0 / 30.0,
          wobble=3.0, wrong=None, fs=None):
    """Frames of the car going down `road` at `speed`, a Think each."""
    def seg(i):
        p, q = road.pts[i], road.pts[i + 1]
        return math.hypot(q.x - p.x, q.y - p.y)

    along = 0.0
    i = start
    lat = 0.0
    for f in range(frames):
        along += speed * dt
        while i + 1 < len(road.pts) and along >= seg(i):
            along -= seg(i)
            i += 1
        lat += rnd.uniform(-0.3, 0.3)
        lat = max(-wobble, min(wobble, lat))
        acc = (rnd.uniform(-8.0, 8.0), rnd.uniform(-8.0, 8.0))
        place(sc, road, i, lat=lat, along=along, speed=speed, fs=fs,
              slip=rnd.uniform(-1.0, 1.0), acc=acc)
        if wrong is not None:
            sc.carf("bWrongWay", wrong(f))
        sc.call(F_THINK, slot, fb(dt))


def scenario_think(sc, rnd):
    sc.tag("think")
    net = network(sc)
    r0, r1, r2, r3, r4 = net.roads
    place(sc, r0, 1, speed=25.0)
    fresh(sc, 0)
    sc.op(OP_DUMP, 0)
    drive(sc, rnd, 0, r0, 150, speed=25.0)
    sc.tag("think-wrong-way")
    drive(sc, rnd, 0, r0, 30, start=20, speed=25.0,
          wrong=lambda f: [0, 1, 2, -1][(f // 5) % 4])
    sc.carf("bWrongWay", 0)
    sc.tag("think-speeds")
    for fs in (9.99, 10.0, 10.01, 3.0, -12.0, 40.0):
        drive(sc, rnd, 0, r0, 6, start=30, speed=abs(fs) + 0.5, fs=fs)
    # Slow enough that StraightLinePredict uses the angle.
    drive(sc, rnd, 0, r0, 6, start=30, speed=0.5, fs=0.5)
    sc.tag("think-fast")
    drive(sc, rnd, 0, r0, 20, start=5, speed=80.0, dt=1.0 / 60.0)
    sc.tag("think-end")
    fresh(sc, 0, 0x33)
    drive(sc, rnd, 0, r1, 30, speed=15.0, wobble=1.0)
    sc.tag("think-off")
    for x, y in ((5000.0, 5000.0), (-400.0, 30.0), (0.0, 500.0)):
        sc.carf("Position.x", x)
        sc.carf("Position.y", y)
        sc.carf("ForwardSpeed", 20.0)
        for f in range(5):
            sc.call(F_THINK, 0, fb(0.05))
    sc.tag("think-camera")
    fresh(sc, 0, 0x44)
    sc.glob("CameraFollowThisCarInstead", 2)
    sc.glob("HasTargetMarkers", 1)
    drive(sc, rnd, 0, r0, 3, start=10)
    sc.glob("HasTargetMarkers", 1)
    sc.carf("DriverNumber", 5)
    drive(sc, rnd, 0, r0, 3, start=11)
    sc.glob("CameraFollowThisCarInstead", -1)
    sc.glob("HasTargetMarkers", 0)
    sc.carf("DriverNumber", 2)
    sc.tag("think-printing")
    sc.glob("DoSpeedDifferencePrinting", 1)
    drive(sc, rnd, 0, r0, 10, start=12)
    sc.carf("Position.x", 5000.0)
    sc.call(F_THINK, 0, fb(0.05))
    sc.glob("DoSpeedDifferencePrinting", 0)
    sc.tag("think-dt")
    for dt in (0.0001, 0.0, 0.001, 0.2):
        drive(sc, rnd, 0, r0, 4, start=14, dt=dt)
    sc.tag("think-fill-at-ten")
    # Nothing predicted, the wrong way, at a ForwardSpeed of exactly 10:
    # FillWithCurrentAcceleration, not a straight line. The acceleration
    # is small enough that Fill integrates.
    for fs in (10.0, 9.99):
        place(sc, r0, 32, speed=10.5, fs=fs, acc=(0.5, 0.25))
        sc.carf("bWrongWay", 1)
        sc.call(F_THINK, 0, fb(1.0 / 30.0))
    sc.carf("bWrongWay", 0)
    sc.tag("think-lost-route")
    # A point whose route the manager does not hold: GetCurrentRoute is
    # NULL and the point is not. With the history kept from r0,
    # CalculateLateral would fit it and RouteDeltaPredict would run; the
    # route test sends Think to Fill instead. The countdown is held off
    # so that FindWhereIAm does not move the point first.
    ghost = net.route(33, 0, ar.line(10, 0.0, 60.0, 10.0, 0.0),
                      random.Random(0x6057))
    for i in (33, 34, 35):
        place(sc, r0, i, lat=0.5, speed=25.0, acc=(0.5, 0.25))
        sc.call(F_THINK, 0, fb(1.0 / 30.0))
    sc.ctlf(0, "TimeBeforeUpdate", 5.0)
    sc.ctlf(0, "RoutePoint", ghost.ref(3))
    place(sc, r0, 36, lat=0.5, speed=25.0, acc=(0.5, 0.25))
    sc.call(F_THINK, 0, fb(1.0 / 30.0))
    sc.op(OP_DUMP, 0)
    sc.call(F_DESTROY, 0, 2)


def scenario_vtable(sc, rnd):
    sc.tag("vtable")
    net = network(sc)
    r0 = net.roads[0]
    for tracked in (False, True):
        place(sc, r0, 8, speed=20.0)
        fresh(sc, 0, 0x66, tracked=tracked)
        sc.vt(0, 16)
        sc.vt(0, 32, fb(0.2))
        sc.vt(0, 40, r0.ref(), r0.ref(9))
        sc.vt(0, 48)
        sc.vt(0, 56)
        place(sc, r0, 9, lat=9.5)
        sc.vt(0, 64)
        sc.vt(0, 72)
        sc.vt(0, 80)
        for mode in (1, 4, 0, 2):
            sc.carf("TheMovementMode", mode)
            sc.vt(0, 88)
        sc.carf("TheMovementMode", 1)
        sc.vt(0, 96, fb(1.75))
        sc.vt(0, 104)
        sc.vt(0, 8, 2)


def scenario_destroy(sc):
    sc.tag("destroy")
    net = network(sc)
    place(sc, net.roads[0], 8)
    for fields in ((), ("Driver",), ("Average",), ("Spline",),
                   ("Driver", "Average", "Spline")):
        for flags in (0, 1, 2, 3):
            fresh(sc, 0, 0x99)
            for name in fields:
                sc.ctlf(0, name, 0)
            sc.call(F_DESTROY, 0, flags)
    # The player gone: RealDriver's destructor leaves the blur alone.
    for flags in (0, 1):
        fresh(sc, 1, 0x98, tracked=True)
        sc.call(F_TDESTROY, 1, flags)


def scenario_find_oob(sc):
    """FindWhereIAm's out-of-bounds drop and its radius, on a traffic
    lane 14 wide each side. The fallback searches the racing routes
    only, so a lane point the drop throws away comes back as the racing
    route's instead, and the drop shows. On network()'s routes the
    fallback found the same point again."""
    sc.tag("find-oob")
    rnd = random.Random(0xf1d)
    a = Arena(sc)
    sc.signs({})
    sc.glob("NumSignposts", 0)
    a.route(3, 0, ar.line(12, 0.0, 0.0, 10.0, 0.0), rnd)
    lane = a.route(75, 1, ar.line(12, 0.0, -200.0, 10.0, 0.0), rnd,
                   widths=(14.0, 14.0))
    a.register()
    sc.glob("TrackLength", 480.0)
    sc.glob("TrackDirection", 0)
    place(sc, lane, 5)
    fresh(sc, 0, 0x5D, tracked=True)
    # 19 out is exactly 5 past the width, and kept; 19.5 is dropped,
    # where a limit of 6 would keep it; 18 is inside 24 and outside 12,
    # and kept; 22 is dropped; 26 is past the radius; 4 is on the road.
    # Each on both sides.
    for lat in (19.0, 19.5, 18.0, 22.0, 26.0, 4.0):
        for side in (1.0, -1.0):
            place(sc, lane, 5, lat=lat * side, speed=10.0)
            sc.ctlf(0, "RoutePoint", lane.ref(5))
            sc.call(F_FIND, 0)
    sc.call(F_TDESTROY, 0, 0)


def script():
    rnd = random.Random(0x4ea1)
    sc = Script()
    setup(sc)
    scenario_static(sc)
    scenario_ctor(sc)
    scenario_tracked(sc, rnd)
    scenario_line(sc)
    scenario_rdp(sc, rnd)
    scenario_branch(sc, rnd)
    scenario_combo(sc, rnd)
    scenario_lateral(sc, rnd)
    scenario_think(sc, rnd)
    scenario_vtable(sc, rnd)
    scenario_destroy(sc)
    scenario_find_oob(sc)
    return sc


def target_bytes(seed, n):
    """A DriveTarget already holding `n` points, deterministic in `seed`.
    The pads are zero, as DriveTarget's constructor leaves them."""
    rnd = random.Random(seed)
    b = bytearray(TGT_SIZE)
    b[0] = n & 0xFF
    for i in range(20):
        struct.pack_into("<4f", b, 16 + 16 * i, rnd.uniform(-50.0, 50.0),
                         rnd.uniform(-50.0, 50.0), rnd.uniform(-2.0, 2.0),
                         rnd.uniform(-1.0, 1.0))
        struct.pack_into("<f", b, 336 + 4 * i, rnd.uniform(0.0, 60.0))
        b[416 + i] = rnd.choice((0xFF, 3, 7)) if i < n else 0
        struct.pack_into("<h", b, 436 + 2 * i, rnd.randrange(-1, 48))
        b[476 + i] = rnd.randrange(0, 21) if i < n else 0xFF
    struct.pack_into("<i", b, 496, 0)
    b[500] = 0xFF
    struct.pack_into("<ii", b, 504, 0, 0)
    struct.pack_into("<f", b, 512, rnd.uniform(0.0, 200.0) if n else 0.0)
    return bytes(b)


# ================================================================ the model


class Model(object):
    def __init__(self, sc):
        self.sc = sc
        self.out = []
        e = self.e = Emu(ieee=True)
        e.stub_bware()
        # Clear leaves retail's -1 in LastPointToScore.
        pcc.retail_clear(e)
        self.fn = {k: e.addr_of(v) for k, v in FN_SYM.items()}
        self.glob_addr = [e.addr_of(a) for _, a in GLOBS]
        self.portname = {e.addr_of(k): v for k, v in FNMAP.items()}
        self.fixed = {CAR: "car", CTI: "cti", PLAYER: "pl", BODY: "body",
                      CTRL[0]: "c0", CTRL[1]: "c1", TGT: "tgt",
                      e.addr_of(BASIS): "basis"}
        self.routes = {}
        self.blocks = []
        self.heap = HEAP
        # Poison, then the pointers the image follows.
        e.mem[CAR:CAR + 0x1000] = bytes([FILL]) * 0x1000
        e.mem[CTI:CTI + 0x600] = bytes([FILL]) * 0x600
        e.mem[PLAYER:PLAYER + 0x400] = bytes([FILL]) * 0x400
        e.mem[BODY:BODY + 336] = bytes([FILL]) * 336
        e.put32(CAR + 12, CTI)
        e.put32(CAR + 24, PLAYER)
        e.put32(CAR + 52, BODY)
        e.put32(ar.SIGN_PTR, SIGNS)
        e.put32(ar.NSIGN_PTR, 0)
        self.stubs()

    # ---- helpers ---------------------------------------------------------

    def emit(self, s):
        self.out.append(s)

    def cstr(self, p):
        if p == 0:
            return "(null)"
        end = self.e.mem.index(b"\0", p)
        return self.e.mem[p:end].decode("latin-1")

    def label(self, a):
        e = self.e
        a &= M32
        if a == 0:
            return "null"
        if a in self.fixed:
            return self.fixed[a]
        for base, size, k in self.blocks:
            if base <= a < base + size:
                return "h%d" % k if a == base else "h%d+%d" % (k, a - base)
        if ARENA <= a < ARENA + ARENA_SIZE:
            off = a - ARENA
            for slot in sorted(self.routes):
                base = self.routes[slot]
                if off == base:
                    return "r%d" % slot
                t = base + HDR
                n = s32(e.u32(ARENA + base + 16))
                if n > 0 and t <= off < t + PT * n and (off - t) % PT == 0:
                    return "r%d.p%d" % (slot, (off - t) // PT)
            return "a%+d" % off
        b = a & 0xFF
        if a == b * 0x01010101:
            return "fill%02x" % b
        return "?"

    def is_block(self, a):
        return any(base == a for base, _, _ in self.blocks)

    def vtname(self, v):
        return {VT_TC: "tc", VT_RC: "rc", VT_CC: "cc", VT_RD: "rd",
                VT_CD: "cd"}.get(v, "%08x" % v)

    def ref(self, v):
        v = s32(v)
        if v < 0:
            return 0
        assert v < ARENA_SIZE, v
        return ARENA + v

    def stubs(self):
        e = self.e
        emit = self.emit
        lab = self.label

        def arg(i):
            return e.reg[4 + i] & M32

        def malloc(em):
            size, name = s32(arg(0)), self.cstr(arg(1))
            p = (self.heap + 15) & ~15
            self.heap = p + size
            assert self.heap <= HEAP_END
            k = len(self.blocks)
            self.blocks.append((p, size, k))
            fill = 0 if name.endswith("quickspline.cpp") else HEAP_FILL
            e.mem[p:p + size] = bytes([fill]) * size
            emit("  malloc %s %d flags %d pool %d -> h%d"
                 % (name, size, s32(arg(2)), s32(arg(3)), k))
            return p

        def malloc2(em):
            raise AssertionError("the two-argument bMalloc")

        def free(em):
            if arg(0):
                emit("  free %s" % lab(arg(0)))

        e.stub("bMalloc__FiPCcii", malloc)
        e.stub("bMalloc__Fii", malloc2)
        e.stub("bFree__FPv", free)
        e.stub("__builtin_delete", free)
        e.stub(0x00114AB0, free)            # __builtin_vec_delete

        def blur_off(em):
            emit("  blur-off %d" % s32(arg(0)))

        def movement(em):
            emit("  set-movement-mode %s %d" % (lab(arg(0)), s32(arg(1))))

        def joy(what):
            def f(em):
                raise AssertionError("%s: a RealDriver here never adds "
                                     "its handlers" % what)
            return f

        # Retail's CarController::SetToPhysicsMode (0x001c0100), which the
        # port follows: the demo's goes to MELLOW_MOVEMENT for any car,
        # retail's to PHYSICS_MOVEMENT for a player's. The test is on
        # this->pCar, not the argument.
        def to_physics(em):
            car = e.u32(arg(0))
            if s32(e.u32(car + 36)) in (1, 4):
                return None
            emit("  set-movement-mode %s %d"
                 % (lab(car), 1 if e.u32(car + 24) else 4))
            return None

        e.stub("RadialBlurOff__Fi", blur_off)
        e.stub("SetMovementMode__3Car12MovementMode", movement)
        e.stub("SetToPhysicsMode__13CarControllerP3Car", to_physics)
        e.stub("AddJoyHandler__F12JoystickPort8JoyEventPF12JoystickPort"
               "8JoyEventUcPv_vPv", joy("AddJoyHandler"))
        e.stub("RemoveJoyHandler__F12JoystickPort8JoyEvent",
               joy("RemoveJoyHandler"))

    # ---- the prints ------------------------------------------------------

    def target(self, a, who):
        e = self.e
        u8, u16, u32 = e.u8, e.u16, e.u32
        pads = fnv(bytes(e.mem[a + 1:a + 16]) + bytes(e.mem[a + 501:a + 504])
                   + bytes(e.mem[a + 516:a + 528]))
        self.emit("  %s n %d tt %d wp %d wpct %d wpt %d len %08x pads %08x"
                  % (who, s8(u8(a)), s32(u32(a + 496)), s8(u8(a + 500)),
                     s32(u32(a + 504)), s32(u32(a + 508)), u32(a + 512),
                     pads))
        for i in range(20):
            p = a + 16 + 16 * i
            route = s8(u8(a + 416 + i))
            self.emit("   p%d %08x %08x %08x spd %08x r %d n %d dl %d"
                      % (i, u32(p), u32(p + 4), u32(p + 8),
                         u32(a + 336 + 4 * i), route,
                         s16(u16(a + 436 + 2 * i)), s8(u8(a + 476 + i))))

    def dump(self, slot):
        e = self.e
        c = CTRL[slot]
        u8, u16, u32 = e.u8, e.u16, e.u32
        L = self.label
        prev = " ".join("%s/%s" % (L(u32(c + 48 + 8 * i)),
                                   L(u32(c + 52 + 8 * i))) for i in range(4))
        self.emit(
            "c%d vt %s car %s drv %s rp %s tbu %08x acc %08x ps %08x "
            "caf %s %08x lat %08x avg %s np %d prev %s spl %s rend %d "
            "boost %08x"
            % (slot, self.vtname(u32(c + 8)), L(u32(c)), L(u32(c + 4)),
               L(u32(c + 12)), u32(c + 16), u32(c + 20), u32(c + 24),
               L(u32(c + 28)), u32(c + 32), u32(c + 36), L(u32(c + 40)),
               s32(u32(c + 44)), prev, L(u32(c + 80)),
               s32(u32(self.glob_addr[G["HasTargetMarkers"]])),
               u32(STATE + 924)))
        a = u32(c + 40)
        if self.is_block(a):
            n = s32(u32(a))
            data = u32(a + 20)
            vals = ""
            if self.is_block(data):
                vals = " ".join("%08x" % u32(data + 4 * i)
                                for i in range(max(0, min(n, 8))))
            self.emit("  avg n %d cur %d ns %d tot %08x av %08x data %s %s"
                      % (n, s32(u32(a + 4)), s32(u32(a + 8)), u32(a + 12),
                         u32(a + 16), L(data), vals))
        s = u32(c + 80)
        if self.is_block(s):
            maxc = u16(s + 24)
            self.emit(
                "  spl ept %d bt %d max %08x min %08x len %08x dirty %d "
                "ba %d minc %d maxc %d num %d buf %s cp %s basis %s"
                % (s32(u32(s)), s32(u32(s + 4)), u32(s + 8), u32(s + 12),
                   u32(s + 16), s8(u8(s + 20)), s8(u8(s + 21)),
                   s8(u8(s + 22)), maxc, u16(s + 26), L(u32(s + 28)),
                   L(u32(s + 32)), L(u32(s + 36))))
            buf = u32(s + 28)
            if self.is_block(buf):
                for i in range(min(maxc, 8) + 3):
                    q = buf + 16 * i
                    self.emit("   b%d %08x %08x %08x %08x"
                              % (i, u32(q), u32(q + 4), u32(q + 8),
                                 u32(q + 12)))
        d = u32(c + 4)
        if self.is_block(d):
            self.emit("  drv vt %s car %s port %d ha %d"
                      % (self.vtname(u32(d + 556)), L(u32(d + 560)),
                         s32(u32(d + 564)), s32(u32(d + 568))))
            self.target(d, "dtgt")

    def static(self):
        e = self.e
        for name, vt in (("tc", VT_TC), ("rc", VT_RC)):
            for k in range(1, 14):
                ent = vt + 8 * k
                self.emit("vt %s %d %d %d %s"
                          % (name, 8 * k, s16(e.u16(ent)),
                             s16(e.u16(ent + 2)),
                             self.portname.get(e.u32(ent + 4), "?")))

    # ---- the run ---------------------------------------------------------

    def run(self):
        tag = "?"
        for i, o in enumerate(self.sc.ops):
            if o[0] == OP_TAG:
                tag = self.sc.tags[o[1]]
            try:
                self.step(o)
            except AssertionError as x:
                raise AssertionError("op %d %r in [%s]: %s"
                                     % (i, o[:6], tag, x))
        return self.out

    def poke(self, addr, w, v):
        e = self.e
        if w == 4:
            e.put32(addr, v)
        elif w == 2:
            struct.pack_into("<H", e.mem, addr, v & 0xFFFF)
        else:
            e.mem[addr] = v & 0xFF

    def step(self, o):
        sc, e, emit = self.sc, self.e, self.emit
        code, a = o[0], o[1:]
        if code == OP_TAG:
            emit("[%s]" % sc.tags[a[0]])
        elif code == OP_CLEAR:
            e.mem[ARENA:ARENA + ARENA_SIZE] = bytes(ARENA_SIZE)
            self.routes = {}
        elif code == OP_WORDS:
            off, ws = a[0], a[1:]
            e.mem[ARENA + off:ARENA + off + 4 * len(ws)] = struct.pack(
                "<%dI" % len(ws), *[w & M32 for w in ws])
        elif code == OP_ROUTE:
            self.routes[a[0]] = a[1]
        elif code == OP_SIGNS:
            first, ws = a[0], a[1:]
            e.mem[SIGNS + 8 * first:SIGNS + 8 * first + 4 * len(ws)] = \
                struct.pack("<%dI" % len(ws), *[w & M32 for w in ws])
        elif code == OP_RESET:
            e.call("__17TrackRouteManager", MGR)
        elif code == OP_ADD:
            e.call("AddRouteToRightList__17TrackRouteManagerP10TrackRoute",
                   MGR, self.ref(a[0]))
        elif code == OP_FILL:
            c = CTRL[a[0]]
            e.mem[c:c + CTRL_SIZE] = bytes([a[1] & 0xFF]) * CTRL_SIZE
        elif code == OP_INIT:
            emit("init c%d" % a[0])
            r = e.call("__14RealControllerP3Car", CTRL[a[0]], CAR)
            emit("  -> %s" % self.label(r))
        elif code == OP_TINIT:
            emit("tinit c%d" % a[0])
            r = e.call("__17TrackedControllerP3Car", CTRL[a[0]], CAR)
            emit("  -> %s" % self.label(r))
        elif code == OP_DUMP:
            self.dump(a[0])
        elif code == OP_CARF:
            _, addr, w = CARF[a[0]]
            self.poke(addr, w, a[1])
        elif code == OP_GLOB:
            e.put32(self.glob_addr[a[0]], a[1])
        elif code == OP_CTLF:
            slot, field, v = a
            _, off, kind = CTLF[field]
            if kind == "ref":
                v = self.ref(v)
            elif kind == "clear":
                v = 0
            e.put32(CTRL[slot] + off, v)
        elif code == OP_CALL:
            self.call(*a)
        elif code == OP_VT:
            self.vcall(*a)
        elif code == OP_TGT:
            e.write(TGT, struct.pack("<%dI" % len(a), *[w & M32 for w in a]))
        elif code == OP_STATIC:
            self.static()
        else:
            raise ValueError("op %d" % code)

    def call(self, fn, slot, a, b, c, d):
        e = self.e
        emit = self.emit
        this = CTRL[slot]
        sym = self.fn[fn]
        name = FN_SYM[fn].split("__")[0]
        if fn in (F_THINK, F_TTHINK):
            emit("%s c%d %08x" % (name, slot, a & M32))
            e.fpr[12] = a & M32
            e.call(sym, this)
        elif fn == F_SET_ROUTE:
            emit("%s c%d %s %s" % (name, slot, self.label(self.ref(a)),
                                   self.label(self.ref(b))))
            e.call(sym, this, self.ref(a), self.ref(b))
        elif fn in (F_RDP, F_COMBO):
            emit("%s c%d %08x %08x %s %s"
                 % (name, slot, a & M32, b & M32, self.label(self.ref(c)),
                    self.label(self.ref(d))))
            e.fpr[12] = a & M32
            e.fpr[13] = b & M32
            e.call(sym, this, TGT, self.ref(c), self.ref(d))
            self.target(TGT, "tgt")
        elif fn == F_LATERAL:
            emit("%s c%d %08x %s %s" % (name, slot, a & M32,
                                        self.label(self.ref(b)),
                                        self.label(self.ref(c))))
            e.put32(OUT, OUT_FILL)
            e.put32(OUT + 4, OUT_FILL)
            e.fpr[12] = a & M32
            r = e.call(sym, this, OUT, OUT + 4, self.ref(b), self.ref(c))
            emit("  ret %d pos %08x vel %08x" % (r, e.u32(OUT),
                                                 e.u32(OUT + 4)))
        elif fn in (F_DESTROY, F_TDESTROY):
            emit("%s c%d %d" % (name, slot, a))
            e.call(sym, this, a)
        else:
            emit("%s c%d" % (name, slot))
            r = e.call(sym, this)
            if fn in (F_GET_ROUTE, F_GET_POINT):
                emit("  ret %s" % self.label(r))
            elif fn in (F_OOB, F_GET_ACC):
                emit("  ret %08x" % e.fpr[0])
            elif fn == F_LINE:
                emit("  ret %d" % r)

    def vcall(self, slot, vslot, a, b):
        e = self.e
        c = CTRL[slot]
        ent = e.u32(c + 8) + vslot
        delta = s16(e.u16(ent))
        fn = e.u32(ent + 4)
        this = (c + delta) & M32
        self.emit("vt c%d %d %s" % (slot, vslot,
                                    self.portname.get(fn, "?")))
        e.fpr[12] = a & M32
        if vslot == 8:
            r = e.call(fn, this, a)
        elif vslot == 40:
            r = e.call(fn, this, self.ref(a), self.ref(b))
        elif vslot == 88:
            r = e.call(fn, this, CAR)
        else:
            r = e.call(fn, this)
        if vslot in (48, 56):
            self.emit("  ret %s" % self.label(r))
        elif vslot == 64:
            self.emit("  ret %08x" % e.fpr[0])


def model(sc):
    return Model(sc).run()


# ================================================================ the build


def build_harness(tmp, name="realcontroller_test"):
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
    # -- the helpers ---------------------------------------------------
    ("oob-strict", RCC, "    if (0.0f < f)" + NL + "        return f - p->RightWidth;",
     "    if (0.0f <= f)" + NL + "        return f - p->RightWidth;"),
    ("oob-right-width", RCC, "        return f - p->RightWidth;",
     "        return f - p->LeftWidth;"),
    ("oob-left-unsigned", RCC, "    return -(f + p->LeftWidth);",
     "    return f + p->LeftWidth;"),
    ("oob-cross-sign", RCC,
     "              - (pos->y - p->Position.y) * p->Direction.x;",
     "              + (pos->y - p->Position.y) * p->Direction.x;"),
    ("route-of-first", RCC,
     "    return TheTrackRouteManager.pTrackRoutes[p->RouteNumber];",
     "    return TheTrackRouteManager.pTrackRoutes[0];"),
    ("line-offset-q7", RCC, "    return (float)((int32_t)v * 256) * (1.0f / 65536.0f);",
     "    return (float)((int32_t)v * 128) * (1.0f / 65536.0f);"),
    ("line-offset-stride", RCC, "(const uint8_t *)p + 48 + 2 * line",
     "(const uint8_t *)p + 48 + line"),
    ("line-speed-base", RCC, "    return ((const uint8_t *)p)[90 + line];",
     "    return ((const uint8_t *)p)[91 + line];"),
    ("min-s-is-max", RCC,
     "static float min_s(float fs, float ft) { return (ft < fs) ? ft : fs; }",
     "static float min_s(float fs, float ft) { return (fs < ft) ? ft : fs; }"),
    ("line-number-shift", RCC, "                     << 1);",
     "                     << 2);"),

    # -- TrackedController ---------------------------------------------
    ("tc-init-no-point", RCC,
     "    carcontroller_init(&c->Base, car);" + NL
     + "    c->RoutePoint = NULL;" + NL,
     "    carcontroller_init(&c->Base, car);" + NL),
    ("tc-init-acc", RCC, "    c->Acceleration = 0.0f;",
     "    c->Acceleration = 1.0f;"),
    ("tc-init-no-caffeine", RCC, "    c->pCaffeineObj = NULL;" + NL, ""),
    ("tc-init-caffeine-high", RCC, "    c->CaffeineObjHigh = 0;",
     "    c->CaffeineObjHigh = 1;"),
    ("tc-init-no-find", RCC,
     "    trackedcontroller_find_where_i_am(c);" + NL + "    return c;",
     "    return c;"),
    ("tc-dtor-flags", RCC, "    carcontroller_destroy(&c->Base, flags);",
     "    carcontroller_destroy(&c->Base, 0);"),
    ("tc-think-inclusive", RCC, "    if (0.0f < left)" + NL + "        return;",
     "    if (0.0f <= left)" + NL + "        return;"),
    ("tc-think-period", RCC, "                      / (TRACKED_UPDATE_PERIOD - left);",
     "                      / TRACKED_UPDATE_PERIOD;"),
    ("tc-think-overshoot-sign", RCC,
     "                      / (TRACKED_UPDATE_PERIOD - left);",
     "                      / (TRACKED_UPDATE_PERIOD + left);"),
    ("tc-think-acc-sign", RCC,
     "    c->Acceleration = (c->Base.pCar->State.VelocityMagnitude - c->PrevSpeed)",
     "    c->Acceleration = (c->PrevSpeed - c->Base.pCar->State.VelocityMagnitude)"),
    ("tc-think-no-store", RCC, "    c->TimeBeforeUpdate = left;" + NL, ""),
    ("tc-think-no-find", RCC,
     "    ((ControllerFn)e->fn)(vt_this(c, e));" + NL + "}",
     "    (void)e;" + NL + "}"),
    ("tc-think-direct-find", RCC,
     "    e = vt_slot(c->Base._vtable, CARCONTROLLER_VT_FIND_WHERE_I_AM);" + NL
     + "    ((ControllerFn)e->fn)(vt_this(c, e));",
     "    (void)e;" + NL + "    trackedcontroller_find_where_i_am(c);"),
    ("tc-set-route-tbu", RCC,
     "    (void)r;" + NL + "    c->TimeBeforeUpdate = TRACKED_UPDATE_PERIOD;",
     "    (void)r;" + NL + "    c->TimeBeforeUpdate = 0.2f;"),
    ("tc-set-route-point", RCC,
     "    c->RoutePoint = p;" + NL + "    c->PrevSpeed",
     "    c->RoutePoint = NULL;" + NL + "    c->PrevSpeed"),
    ("tc-set-route-no-speed", RCC,
     "    c->RoutePoint = p;" + NL
     + "    c->PrevSpeed = c->Base.pCar->State.VelocityMagnitude;",
     "    c->RoutePoint = p;"),
    ("tc-get-route-no-null", RCC,
     "    if (c->RoutePoint == NULL)" + NL + "        return NULL;" + NL
     + "    return route_of(c->RoutePoint);",
     "    return route_of(c->RoutePoint);"),
    ("tc-oob-null", RCC, "    if (p == NULL)" + NL + "        return 0.0f;",
     "    if (p == NULL)" + NL + "        return -1.0f;"),
    ("find-radius", RCC, "#define TRACKED_SEARCH_RADIUS 24.0f",
     "#define TRACKED_SEARCH_RADIUS 12.0f"),
    ("find-flags-unposted", RCC,
     "#define TRACKED_SEARCH_FLAGS  (TRFIND_POSTED_ONLY | TRFIND_BY_TRACK_DISTANCE)",
     "#define TRACKED_SEARCH_FLAGS  (TRFIND_BY_TRACK_DISTANCE)"),
    ("find-flags-straight", RCC,
     "#define TRACKED_SEARCH_FLAGS  (TRFIND_POSTED_ONLY | TRFIND_BY_TRACK_DISTANCE)",
     "#define TRACKED_SEARCH_FLAGS  (TRFIND_POSTED_ONLY)"),
    ("find-oob-limit", RCC, "5.0f < out_of_bounds(p, &car->State.Position)",
     "6.0f < out_of_bounds(p, &car->State.Position)"),
    ("find-oob-inclusive", RCC, "5.0f < out_of_bounds(p, &car->State.Position)",
     "5.0f <= out_of_bounds(p, &car->State.Position)"),
    ("find-no-oob", RCC,
     "        if (p != NULL && 5.0f < out_of_bounds(p, &car->State.Position))"
     + NL + "            c->RoutePoint = NULL;" + NL, ""),
    ("find-no-fallback", RCC,
     "    if (c->RoutePoint == NULL) {" + NL + "        NearestRoutePointInfo info;",
     "    if (0) {" + NL + "        NearestRoutePointInfo info;"),
    ("find-dist-zero", RCC,
     "            TRACKED_SEARCH_FLAGS, car->TheTrackPathCoordinate.DistanceAroundTrack);",
     "            TRACKED_SEARCH_FLAGS, 0.0f);"),
    ("find-no-tbu", RCC,
     "    c->TimeBeforeUpdate = TRACKED_UPDATE_PERIOD;" + NL
     + "    c->PrevSpeed = c->Base.pCar->State.VelocityMagnitude;" + NL + "}"
     + NL + NL + "void trackedcontroller_just_reset",
     "    c->PrevSpeed = c->Base.pCar->State.VelocityMagnitude;" + NL + "}"
     + NL + NL + "void trackedcontroller_just_reset"),
    ("find-no-speed", RCC,
     "    c->TimeBeforeUpdate = TRACKED_UPDATE_PERIOD;" + NL
     + "    c->PrevSpeed = c->Base.pCar->State.VelocityMagnitude;" + NL + "}"
     + NL + NL + "void trackedcontroller_just_reset",
     "    c->TimeBeforeUpdate = TRACKED_UPDATE_PERIOD;" + NL + "}"
     + NL + NL + "void trackedcontroller_just_reset"),

    # -- RealController's lifetime -------------------------------------
    ("rc-init-prevlat", RCC, "    c->PreviousLateralOffsetFromLine = 0.0f;",
     "    c->PreviousLateralOffsetFromLine = 1.0f;"),
    ("rc-init-vt", RCC,
     "    c->PreviousLateralOffsetFromLine = 0.0f;" + NL
     + "    c->Base.Base._vtable = REALCONTROLLER_VTABLE;",
     "    c->PreviousLateralOffsetFromLine = 0.0f;" + NL
     + "    c->Base.Base._vtable = TRACKEDCONTROLLER_VTABLE;"),
    ("rc-init-driver-flags", RCC, "\"RealDriver\", 0,", "\"RealDriver\", 1,"),
    ("rc-init-average-8", RCC, "average_init(a, 8)", "average_init(a, 4)"),
    ("rc-init-spline-min", RCC, "QUICKSPLINE_OVERHAUSER," + NL
     + "                         4);",
     "QUICKSPLINE_OVERHAUSER," + NL + "                         3);"),
    ("rc-init-no-set-num", RCC,
     "    quickspline_set_num_control_points(s, 0);" + NL, ""),
    ("rc-init-numprev", RCC, "    c->NumPreviousRoutePoints = 0;",
     "    c->NumPreviousRoutePoints = 1;"),
    ("rc-init-clears-four", RCC, "    for (i = 0; i < 2; i++) {",
     "    for (i = 0; i < 4; i++) {"),
    ("rc-init-clears-one", RCC, "    for (i = 0; i < 2; i++) {",
     "    for (i = 0; i < 1; i++) {"),
    ("rc-init-clears-point-only", RCC,
     "        c->PreviousRoutePoints[i].Route = NULL;" + NL, ""),
    ("rc-dtor-vt", RCC,
     "    c->Base.Base._vtable = REALCONTROLLER_VTABLE;" + NL
     + "    d = c->Base.Base.Driver;",
     "    c->Base.Base._vtable = TRACKEDCONTROLLER_VTABLE;" + NL
     + "    d = c->Base.Base.Driver;"),
    ("rc-dtor-driver-flags", RCC, "        ((DriverDtorFn)e->fn)(vt_this(d, e), 3);",
     "        ((DriverDtorFn)e->fn)(vt_this(d, e), 2);"),
    ("rc-dtor-driver-no-null", RCC, "    if (d != NULL) {",
     "    if (1) {"),
    ("rc-dtor-average-flags", RCC,
     "        average_destroy(c->LateralVelocityWRTLineAverage, 3);",
     "        average_destroy(c->LateralVelocityWRTLineAverage, 2);"),
    ("rc-dtor-average-no-null", RCC,
     "    if (c->LateralVelocityWRTLineAverage != NULL)" + NL
     + "        average_destroy",
     "    if (1)" + NL + "        average_destroy"),
    ("rc-dtor-spline-flags", RCC,
     "        quickspline_destroy(c->DrivingLineSpline, 3);",
     "        quickspline_destroy(c->DrivingLineSpline, 2);"),
    ("rc-dtor-spline-no-null", RCC,
     "    if (c->DrivingLineSpline != NULL)" + NL + "        quickspline_destroy",
     "    if (1)" + NL + "        quickspline_destroy"),

    # -- RouteDeltaPredict ---------------------------------------------
    ("rdp-look-inclusive", RCC,
     "    if (!(0.0f < look))" + NL + "        return;" + NL
     + "    while (t->NumPoints < 20) {",
     "    if (!(0.0f <= look))" + NL + "        return;" + NL
     + "    while (t->NumPoints < 20) {"),
    ("rdp-wall", RCC, "    while (t->NumPoints < 20) {",
     "    while (t->NumPoints < 19) {"),
    ("rdp-end-no-clear", RCC,
     "            drivetarget_clear(t, NULL, 0.0f);" + NL, ""),
    ("rdp-end-point-only", RCC,
     "        if (info.Route == NULL || info.Point == NULL) {",
     "        if (info.Point == NULL) {"),
    ("rdp-end-route-only", RCC,
     "        if (info.Route == NULL || info.Point == NULL) {",
     "        if (info.Route == NULL) {"),
    ("rdp-dir-new", RCC,
     "        d = (np->Position.x - prev.Point->Position.x) * prev.Point->Direction.x",
     "        d = (np->Position.x - prev.Point->Position.x) * np->Direction.x"),
    ("rdp-dir-y", RCC, "              * prev.Point->Direction.y;",
     "              * prev.Point->Direction.x;"),
    ("rdp-step-look", RCC, "        step = d / speed;",
     "        step = d / look;"),
    ("rdp-pos-no-step", RCC, "        pos = pos + vel * step;",
     "        pos = pos + vel;"),
    ("rdp-vel-inclusive", RCC, "        if (vel < 0.0f)" + NL + "            vel = vel + step;",
     "        if (vel <= 0.0f)" + NL + "            vel = vel + step;"),
    ("rdp-vel-no-rise", RCC, "            vel = vel + step;",
     "            vel = vel;"),
    ("rdp-vel-no-fall", RCC, "            vel = vel - step;",
     "            vel = vel;"),
    ("rdp-half-quarter", RCC, "    half = (hi.y - lo.y) * 0.5f;",
     "    half = (hi.y - lo.y) * 0.25f;"),
    ("rdp-half-length", RCC, "    half = (hi.y - lo.y) * 0.5f;",
     "    half = (hi.x - lo.x) * 0.5f;"),
    ("rdp-no-left-clamp", RCC,
     "        lat = max_s(lat, half - np->LeftWidth);" + NL, ""),
    ("rdp-no-right-clamp", RCC,
     "        lat = min_s(np->RightWidth - half, lat);" + NL, ""),
    ("rdp-left-sign", RCC, "        lat = max_s(lat, half - np->LeftWidth);",
     "        lat = max_s(lat, np->LeftWidth - half);"),
    ("rdp-right-width", RCC, "        lat = min_s(np->RightWidth - half, lat);",
     "        lat = min_s(np->LeftWidth - half, lat);"),
    ("rdp-line-int", RCC, "        line = ee_trunc_w(lineF);",
     "        line = realcontroller_player_drive_line_number(c);"),
    ("rdp-no-pos", RCC, "        lat = line_offset(np, line) + pos;",
     "        lat = line_offset(np, line);"),
    ("rdp-get-along", RCC, "        trpoint_get_position3(np, &at, 0.0f, lat);",
     "        trpoint_get_position3(np, &at, 1.0f, lat);"),
    ("rdp-route-given", RCC, "            t, &at, (int8_t)info.Route->RouteNumber,",
     "            t, &at, (int8_t)r->RouteNumber,"),
    ("rdp-rpn-shift", RCC, "<< 12) >> 16),", "<< 12) >> 15),"),
    ("rdp-dl-none", RCC, "            (int8_t)line, 0, NULL);",
     "            (int8_t)-1, 0, NULL);"),
    ("rdp-checked", RCC, "            (int8_t)line, 0, NULL);",
     "            (int8_t)line, 1, NULL);"),
    ("rdp-travel-new", RCC, "        travelled = travelled + prev.Point->Length;",
     "        travelled = travelled + np->Length;"),
    ("rdp-travel-inclusive", RCC,
     "        if (!(travelled < look))" + NL + "            return;" + NL
     + "    }" + NL + "}",
     "        if (!(travelled <= look))" + NL + "            return;" + NL
     + "    }" + NL + "}"),

    # -- ComboPredict --------------------------------------------------
    ("combo-dot", RCC, "    if (0.99f < dir.x * p->Direction.x",
     "    if (0.98f < dir.x * p->Direction.x"),
    ("combo-dot-y", RCC, "dir.x * p->Direction.x + dir.y * p->Direction.y",
     "dir.x * p->Direction.x + dir.x * p->Direction.y"),
    ("combo-vel-inclusive", RCC, "        && fabsf(vel) < 6.0f",
     "        && fabsf(vel) <= 6.0f"),
    ("combo-vel-signed", RCC, "        && fabsf(vel) < 6.0f",
     "        && vel < 6.0f"),
    ("combo-pos-inclusive", RCC, "        && fabsf(pos) < 12.0f",
     "        && fabsf(pos) <= 12.0f"),
    ("combo-pos-signed", RCC, "        && fabsf(pos) < 12.0f",
     "        && pos < 12.0f"),
    ("combo-speed-ratio", RCC, "        && speed * 0.7f <", "        && speed * 0.8f <"),
    ("combo-speed-forward", RCC,
     "        && speed * 0.7f < c->Base.Base.pCar->State.VelocityMagnitude) {",
     "        && speed * 0.7f < c->Base.Base.pCar->State.ForwardSpeed) {"),
    ("combo-line-zero", RCC, "    float    speed = (float)line_speed(p, line);",
     "    float    speed = (float)line_speed(p, 0);"),

    # -- CalculateLateral ----------------------------------------------
    ("lat-keep-invalid", RCC, "        if (nrpi_is_valid(&prev[i])) {",
     "        if (1) {"),
    ("lat-old-line-zero", RCC, "                                  line_offset(prev[i].Point, line));",
     "                                  line_offset(prev[i].Point, 0));"),
    ("lat-newest-again", RCC,
     "        info = prev[num - 1];" + NL
     + "        ai_get_next_route_point_ahead(&info);" + NL,
     "        info = prev[num - 1];" + NL),
    ("lat-newest-unchecked", RCC,
     "    if (num > 0 && nrpi_is_valid(&prev[num - 1])) {",
     "    if (num > 0) {"),
    ("lat-three", RCC,
     "    while (n < REALCONTROLLER_PREVIOUS_POINTS && nrpi_is_valid(&info)) {",
     "    while (n < 3 && nrpi_is_valid(&info)) {"),
    ("lat-new-line-zero", RCC,
     "        trpoint_get_position3(info.Point, &pts[n], 0.0f," + NL
     + "                              line_offset(info.Point, line));",
     "        trpoint_get_position3(info.Point, &pts[n], 0.0f," + NL
     + "                              line_offset(info.Point, 0));"),
    ("lat-min-two", RCC, "    if (n < s->MinControlPoints) {",
     "    if (n < 2) {"),
    ("lat-short-pos", RCC, "        *pos = 0.0f;" + NL
     + "        *vel = c->LateralVelocityWRTLineAverage->fAverage;",
     "        *pos = 1.0f;" + NL
     + "        *vel = c->LateralVelocityWRTLineAverage->fAverage;"),
    ("lat-short-vel", RCC, "        *pos = 0.0f;" + NL
     + "        *vel = c->LateralVelocityWRTLineAverage->fAverage;",
     "        *pos = 0.0f;" + NL + "        *vel = 0.0f;"),
    ("lat-short-true", RCC, "        return 0;" + NL + "    }",
     "        return 1;" + NL + "    }"),
    ("lat-cp-w", RCC, "        cp->w = 0.0f;", "        cp->w = 1.0f;"),
    ("lat-cp-z", RCC, "        cp->z = pts[i].z;", "        cp->z = 0.0f;"),
    ("lat-no-dirty", RCC,
     "        c->DrivingLineSpline->ControlPointsDirty = 1;" + NL, ""),
    ("lat-param-start", RCC, "&car->State.Position, 0.0f, 0.1f);",
     "&car->State.Position, 0.5f, 0.1f);"),
    ("lat-param-step", RCC, "&car->State.Position, 0.0f, 0.1f);",
     "&car->State.Position, 0.0f, 0.2f);"),
    ("lat-side-flipped", RCC, "        < 0.0f)" + NL + "        *pos = -*pos;",
     "        > 0.0f)" + NL + "        *pos = -*pos;"),
    ("lat-side-row", RCC,
     "    if (car->State.BodyMatrix.v1.x * dx + car->State.BodyMatrix.v1.y * dy",
     "    if (car->State.BodyMatrix.v1.x * dy + car->State.BodyMatrix.v1.y * dx"),
    ("lat-record-no-dt", RCC,
     "                   (*pos - c->PreviousLateralOffsetFromLine) / dt);",
     "                   (*pos - c->PreviousLateralOffsetFromLine));"),
    ("lat-record-absolute", RCC,
     "                   (*pos - c->PreviousLateralOffsetFromLine) / dt);",
     "                   *pos / dt);"),
    ("lat-no-keep-offset", RCC,
     "    c->PreviousLateralOffsetFromLine = *pos;" + NL, ""),
    ("lat-vel-zero", RCC,
     "    *vel = c->LateralVelocityWRTLineAverage->fAverage;" + NL
     + "    c->PreviousLateralOffsetFromLine = *pos;",
     "    *vel = 0.0f;" + NL + "    c->PreviousLateralOffsetFromLine = *pos;"),
    ("lat-no-same-point", RCC,
     "        if (prev[num - 1].Point == p)" + NL + "            return 1;" + NL,
     ""),
    ("lat-no-null-route", RCC,
     "        if (r == NULL)" + NL + "            return 1;" + NL, ""),
    ("lat-shift-short", RCC,
     "        for (i = 0; i < c->NumPreviousRoutePoints - 1; i++)",
     "        for (i = 0; i < c->NumPreviousRoutePoints - 2; i++)"),
    ("lat-full-three", RCC, "    if (num == REALCONTROLLER_PREVIOUS_POINTS) {",
     "    if (num == 3) {"),
    ("lat-store-no-route", RCC, "    prev[num].Route = r;",
     "    prev[num].Route = NULL;"),

    # -- Think ---------------------------------------------------------
    ("think-dt-floor", RCC, "    dt = max_s(dt, 0.001f);",
     "    dt = max_s(dt, 0.0001f);"),
    ("think-no-dt-floor", RCC, "    dt = max_s(dt, 0.001f);" + NL, ""),
    ("think-wrong-way-sign", RCC,
     "    if (base->pCar->pPlayer->bWrongWay == 0) {",
     "    if (base->pCar->pPlayer->bWrongWay <= 0) {"),
    ("think-no-wrong-way", RCC,
     "    if (base->pCar->pPlayer->bWrongWay == 0) {",
     "    if (1) {"),
    ("think-next-unread", RCC,
     "        // A step ahead whose result nothing reads." + NL
     + "        ai_get_next_route_point_ahead(&info);" + NL,
     "        // A step ahead whose result nothing reads." + NL),
    ("think-route-unchecked", RCC,
     "        if (route != NULL && point != NULL",
     "        if (point != NULL"),
    ("think-fs-route", RCC,
     "            if (10.0f <= base->pCar->State.ForwardSpeed) {",
     "            if (10.0f < base->pCar->State.ForwardSpeed) {"),
    ("think-fs-fill", RCC,
     "        if (10.0f <= base->pCar->State.ForwardSpeed)" + NL
     + "            drivetarget_fill",
     "        if (10.0f < base->pCar->State.ForwardSpeed)" + NL
     + "            drivetarget_fill"),
    ("think-fs-magnitude", RCC,
     "            if (10.0f <= base->pCar->State.ForwardSpeed) {",
     "            if (10.0f <= base->pCar->State.VelocityMagnitude) {"),
    ("think-no-blend", RCC,
     "                drivetarget_blend_with_current_acceleration(&t, base->pCar);"
     + NL, ""),
    ("think-fill-not-blend", RCC,
     "                drivetarget_blend_with_current_acceleration(&t, base->pCar);",
     "                drivetarget_fill_with_current_acceleration(&t, base->pCar);"),
    ("think-predicted-unset", RCC, "            predicted = 1;" + NL, ""),
    ("think-no-set-target", RCC,
     "    ((DriverSetTargetFn)e->fn)(vt_this(d, e), &t);" + NL, ""),
    ("think-camera-inverted", RCC,
     "    if ((int32_t)base->pCar->DriverNumber == CameraFollowThisCarInstead)",
     "    if ((int32_t)base->pCar->DriverNumber != CameraFollowThisCarInstead)"),

    # -- the tables ----------------------------------------------------
    ("vt-entry-index", RCC, "#define E(f) { 0, 0, (VtFn)(f) }",
     "#define E(f) { 0, 1, (VtFn)(f) }"),
    ("vt-tc-think-real", RCC,
     "    E(trackedcontroller_think),                     //  32  0x002243f0",
     "    E(realcontroller_think),                        //  32  0x002243f0"),
    ("vt-rc-think-tracked", RCC,
     "    E(realcontroller_think),                        //  32  0x00224db8",
     "    E(trackedcontroller_think),                     //  32  0x00224db8"),
    ("vt-rc-snapshot-tracked", RCC,
     "    E(realcontroller_do_snapshot),                  //  24  0x002248c8",
     "    E(trackedcontroller_do_snapshot),               //  24  0x002248c8"),
    ("vt-rc-dtor-tracked", RCC,
     "    E(realcontroller_destroy),                      //   8  0x00224840",
     "    E(trackedcontroller_destroy),                   //   8  0x00224840"),
    ("vt-rc-find-reset", RCC,
     "    E(realcontroller_think),                        //  32  0x00224db8" + NL
     + "    E(trackedcontroller_set_current_route),         //  40  0x002244e0" + NL
     + "    E(trackedcontroller_get_current_route),         //  48  0x00224500" + NL
     + "    E(trackedcontroller_get_current_route_point),   //  56  0x00224738" + NL
     + "    E(trackedcontroller_get_amount_out_of_bounds),  //  64  0x00224668" + NL
     + "    E(trackedcontroller_find_where_i_am),",
     "    E(realcontroller_think),                        //  32  0x00224db8" + NL
     + "    E(trackedcontroller_set_current_route),         //  40  0x002244e0" + NL
     + "    E(trackedcontroller_get_current_route),         //  48  0x00224500" + NL
     + "    E(trackedcontroller_get_current_route_point),   //  56  0x00224738" + NL
     + "    E(trackedcontroller_get_amount_out_of_bounds),  //  64  0x00224668" + NL
     + "    E(trackedcontroller_just_reset),"),

    # -- DriveTargetRenderer -------------------------------------------
    ("dtr-flag-inverted", DTRC, "    if (!RenderDriveTargetPoints) {",
     "    if (RenderDriveTargetPoints) {"),
    ("dtr-unguarded", DTRC,
     "        if (r->HasTargetMarkers)" + NL
     + "            drivetargetrenderer_destroy_target_markers(r);",
     "        drivetargetrenderer_destroy_target_markers(r);"),
    ("dtr-no-destroy", DTRC,
     "        if (r->HasTargetMarkers)" + NL
     + "            drivetargetrenderer_destroy_target_markers(r);" + NL, ""),
    ("dtr-keeps-flag", DTRC, "    r->HasTargetMarkers = 0;",
     "    r->HasTargetMarkers = 1;"),
]

EQUIVALENT = {
    # Three tables in the image hold FindWhereIAm, TrackedController's,
    # RealController's and CopDriver's (0x00298d68), and all three hold
    # 0x00224530 at slot 72. No class overrides it, so the table and the
    # direct call reach the same function.
    "tc-think-direct-find":
        "no table in the image overrides slot 72: TrackedController's, "
        "RealController's and CopDriver's all hold 0x00224530",
    # QuickSpline's constructor ends in Setup, which calls
    # SetNumControlPoints(0) itself. The second call writes the same four
    # fields with the same values.
    "rc-init-no-set-num":
        "the spline's own constructor has already called "
        "SetNumControlPoints(0)",
    # ~TrackedController stores its own vptr before anything reads this
    # one. The three deletes between go through the driver's table and the
    # pools, never the controller's.
    "rc-dtor-vt":
        "~TrackedController overwrites the vptr before anything reads it",
    # CalculateLookAheadDistance is max(speed * 2, 20): never 0, and a NaN
    # speed gives a NaN that both tests refuse. Nothing writes
    # AIDriverDefaultLookAhead.
    "rdp-look-inclusive":
        "the look-ahead is at least AIDriverDefaultLookAhead, 20.0, so it "
        "is never 0",
    # StraightLinePredict starts with the same Clear(t, 0, 0). A second
    # Clear finds no points and writes the same three fields the first one
    # did.
    "rdp-end-no-clear":
        "StraightLinePredict clears the target itself, and Clear(t, 0, 0) "
        "twice is Clear once",
    # The line through an unsigned float and back with cvt.w.s is exact for
    # every line below 2^24. The classes are 0 to 4 and the script's go to
    # 15. A negative class or one past 2^23 would tell them apart, but the
    # port's `48 + 2 * line` is then a signed overflow, not a fixture.
    "rdp-line-int":
        "the unsigned round trip is exact for every line below 2^24",
    # Setup sets MinControlPoints to 2, or 3 for a LOOP spline, and the
    # constructor asks for EXTRAPOLATED. Nothing changes it afterwards.
    "lat-min-two":
        "an EXTRAPOLATED spline's MinControlPoints is 2",
    # SetNumControlPoints(n) raises the dirty flag just before the loop, and
    # nothing in the loop lowers it.
    "lat-no-dirty":
        "SetNumControlPoints has just raised the flag",
    # GetNextRoutePointAhead writes only the copy it is handed. It reads the
    # signposts and the manager and calls nothing that writes.
    "think-next-unread":
        "GetNextRoutePointAhead writes only its own argument, a copy "
        "nothing reads",
    # BlendWithCurrentAcceleration returns at once for a car with a Player
    # (0x0020a1d8's second test), and Think has already read through
    # pPlayer for bWrongWay. So a RealController's blend does nothing.
    "think-no-blend":
        "Blend returns at once for a car with a Player, and Think has "
        "already read through pPlayer",
    # DestroyTargetMarkers makes the same test first and returns.
    "dtr-unguarded":
        "DestroyTargetMarkers tests HasTargetMarkers itself",
}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name
assert len({_m[0] for _m in MUTATIONS}) == len(MUTATIONS)


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
