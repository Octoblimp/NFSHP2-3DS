"""Cross-check 3DS Files/source/drivetarget.c against a model of DriveTarget.

DriveTarget is the tenth slice of task 25, after CarState, Engine,
CarTypeInfo, CarDriver, Steering, RigidBody, Suspension, Wheel and
DriveTrain. It is the short list of points the AI is steering through and
the speed it wants at each one -- 528 bytes, embedded at offset 0 of every
CarDriver.

This model is written from the disassembly at 0x002086f8..0x0020a840, from
the copy constructor at 0x001da210 in CarCollisionDetect.obj, and from the
three free functions the class calls (0x001c0e30, 0x001c0c20, 0x001c3338),
not from the C. Every constant it uses is read out of
`PS2 Files/NFSHP2.ELF` by address: all ten slots of the object's own .lit4
pool at 0x00321fa8, the two look-ahead globals at 0x00323a50, the minimum
distance at 0x00324a60 and the two camera globals at 0x003235d0. A typo in
the header shows as a diff rather than as two files agreeing with each
other.

The pool is read slot by slot rather than once per distinct value. The
compiler pooled 0.001 three times -- Clear's speed floor, CalculateMaxSpeed's
epsilon and CalculateTime's -- and 0.4 three times, once per use site in
EstimateScore, and drivetarget.h names each one separately. Reading them
apart is what makes those names a checked claim instead of an assumption.

bMath and bVector come from their own checkers' models rather than being
written again here: GetAngle is one bATan, five methods normalise, and
re-deriving bASin's twelve-octave table would duplicate a model that
already has its own transcript. CarState is a local stand-in, because
DriveTarget touches five of its fields and calls exactly one of its
methods; TrackRoute is a local stand-in for the same reason.

Eight things the transcript exists to pin down.

**The clamp in GetAngle is one-sided.** `movz` raises the index from -1 to
0 and `movn` then lowers it to NumPoints - 2, in that order and never back
up. A NumPoints of 0 or 1 leaves it at -1, and the read comes off the front
of the array -- the record's own first sixteen bytes, read as a vector. The
`ga one` line drives exactly that, on a record the constructor zeroed, so
the out-of-bounds read is deterministic and both sides can state it.

**Assignment and copy-construction disagree about the padding.**
`operator=` is one `bMemCpy` of 528 bytes; the copy constructor is five
twenty-iteration loops and eight scalar stores. The `ct` scenario dirties
both destinations with different bytes and prints all three pad runs, so
the asymmetry is a line rather than a comment.

**ShiftRight blanks three fields out of five.** The three stores are
`sw zero,24` / `sw zero,16` / `sw zero,20` -- z, x and y -- plus
RoutePointNumber and CalculatedSpeed. Route, DrivingLine and Points[i].pad
keep whatever the slot held. `pdt` is called with a slot count larger than
NumPoints for that reason.

**Resample's Length stops being a length.** The method respaces the points
along the path, and then writes the distance of the *last point emitted*
into Length rather than the path length it started from. The two differ by
one step.

**EstimateScore's second walk measures from a point that does not move.**
The inner loop runs `nxt` forward while measuring back to
`Points[outer - 1]`, which stays put, so the legs get longer rather than
being consecutive. That is what the image does and it is what makes the
skip-ahead threshold mean anything.

**CalculateMaxSpeed computes a magnitude it never uses.** Two multiplies,
an add and a sqrt on the parallel component, dead in the shipped build.
It is kept, and it is argued in `EQUIVALENT` rather than dropped.

**Dump prints nothing and is still observable.** The print calls are gone
from the shipped image; what is left asks the CarState for its transform,
which sets MatrixValid. That flag is the only way to see the guard from
outside and it is enough to see it, so the `du` scenario reads it after
each of the guard's four outcomes.

**GetFirstPoint's empty arm clears the stamp instead of setting it.** The
store is in a branch-likely delay slot on that arm alone, so an empty
target re-answers on every call inside the same frame, where a full one
answers once.

Usage:

    python tools/drivetarget_check.py
    python tools/drivetarget_check.py --mutate
    python tools/drivetarget_check.py --dump out/drivetarget
"""
import argparse
import difflib
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import bmath_check as BM
import bvector_check as BV

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

SOURCES = [
    "tools/src/drivetarget_test.c",
    "3DS Files/source/drivetarget.c",
    "3DS Files/source/carstate.c",
    "3DS Files/source/trackroute.c",   # drivetarget.c's trmgr_get_route
    "3DS Files/source/trackpath.c",    # and trackroute.c's own dependencies
    "3DS Files/source/quickspline.c",
    "3DS Files/source/bmem.c",
    "3DS Files/source/bchunk.c",
    "3DS Files/source/emath.c",
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/bvector.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
]

DH = "3DS Files/source/drivetarget.h"
CARH = "3DS Files/source/car.h"

# The host widening car.h states as CAR_SLACK. Zero on ARM.
CAR_SLACK = 8 - 4
DC = "3DS Files/source/drivetarget.c"

# The host this runs on, not the handheld. The PS2's pointer is four bytes
# and this one's is eight, which moves two offsets in the DrivingLocation
# stand-in and nothing at all inside DriveTarget itself -- the record has
# no pointers in it, which is why its own layout needs no slack term.
PTR = 8

f32 = BV.f32
fmul, fadd, fsub, fdiv, fneg = BV.fmul, BV.fadd, BV.fsub, BV.fdiv, BV.fneg
fsqrt, fabs32 = BV.fsqrt, BV.fabs32

ZERO = f32(0.0)
ONE = f32(1.0)
HALF = f32(0.5)
MAX_POINTS = 20


def g9(x):
    return "%.9g" % x


OUT = []


def emit(s):
    OUT.append(s)


def pf(tag, x):
    emit("%s %s" % (tag, g9(x)))


def pint(tag, x):
    emit("%s %d" % (tag, x))


# --------------------------------------------------------- the image's data

def elf_f(addr):
    return f32(struct.unpack("<f", BM.ELF.read(addr, 4))[0])


def elf_i(addr):
    return struct.unpack("<i", BM.ELF.read(addr, 4))[0]


# DriveTarget.obj's .lit4: 0x00321fa8, 0x28 long, ten anonymous slots. The
# gp offsets are what the listing quotes (_gp is 0x00328bf0); the names are
# this file's and drivetarget.h's, and they have to agree.
K_CLEAR_EPS = elf_f(0x00321FA8)      # gp-27720
K_AHEAD_DOT = elf_f(0x00321FAC)      # gp-27716
K_SCORE_T1 = elf_f(0x00321FB0)       # gp-27712
K_SCORE_T2 = elf_f(0x00321FB4)       # gp-27708
K_SCORE_T3 = elf_f(0x00321FB8)       # gp-27704
K_MAXSPEED_EPS = elf_f(0x00321FBC)   # gp-27700
K_TIME_EPS = elf_f(0x00321FC0)       # gp-27696
K_NO_TIME = elf_f(0x00321FC4)        # gp-27692
K_PREDICT_DT = elf_f(0x00321FC8)     # gp-27688
K_BLEND_SCALE = elf_f(0x00321FCC)    # gp-27684

# Inline `lui at,...` literals rather than pooled ones.
K_FAST_CAR = f32(30.0)        # 0x41f00000, GetFirstPoint's speed gate
K_MAX_LATERAL = f32(30.0)     # 0x41f00000, and the grip limit
K_ACC_DOMINATES = f32(0.75)   # 0x3f400000, FillWithCurrentAcceleration
K_BLEND_WINDOW = f32(0.75)    # 0x3f400000, BlendWithCurrentAcceleration

# .sdata, named in the MAP file.
AI_SECONDS = elf_f(0x00323A50)
AI_DEFAULT = elf_f(0x00323A54)
MIN_DIST = elf_f(0x00324A60)
CAM_DEFAULT_INIT = elf_i(0x003235D0)
CAM_INSTEAD = elf_i(0x003235D4)

# 0x00325354 is .sbss -- no bytes in the file, because
# _GLOBAL_$I$__11DriveTarget computes it at start-up out of MIN_DIST. The
# model runs that initialiser rather than folding the answer, so the four
# instructions at 0x0020ab48 are modelled and not assumed.
MIN_DIST_SQ = ZERO
CAM_DEFAULT = CAM_DEFAULT_INIT
WORLD_TIMER = 0


def static_init():
    """0x0020ab48: lwc1 gp-16784 ; mul.s ; swc1 gp-14492."""
    global MIN_DIST_SQ
    MIN_DIST_SQ = fmul(MIN_DIST, MIN_DIST)


def check_pool():
    """The pool is ten slots and several of them hold the same number. If
    the image ever stops agreeing with that, say so here rather than
    letting a macro in the header carry the claim alone."""
    want = [0.001, 0.342, 0.4, 0.4, 0.4, 0.001, 0.001, 9999999.0, 0.1,
            1.3333333]
    for i, w in enumerate(want):
        got = elf_f(0x00321FA8 + 4 * i)
        if abs(got - w) > abs(w) * 1e-6 + 1e-9:
            sys.exit("lit4 slot %d is %r, expected about %r" % (i, got, w))


# ------------------------------------------------------------ float helpers

def len3(x, y, z):
    """The VU0 three-lane length: vmul.xyz, vaddy.x, vaddz.x, sqrt.s. The
    sum associates left."""
    return fsqrt(fadd(fadd(fmul(x, x), fmul(y, y)), fmul(z, z)))


def len2(x, y):
    """The two-lane one, which the FPU does directly."""
    return fsqrt(fadd(fmul(x, x), fmul(y, y)))


def i8(v):
    v &= 0xFF
    return v - 256 if v >= 128 else v


def u8(v):
    return v & 0xFF


def i16(v):
    v &= 0xFFFF
    return v - 65536 if v >= 32768 else v


# ------------------------------------------------------------- the records
#
# The 528-byte layout, spelled as fields plus the three padding runs. The
# pads are modelled as bytes because the assignment operator copies them and
# the copy constructor does not, and that difference is one of the things
# the transcript is for.


class DriveTarget(object):
    def __init__(self):
        self.fill(0)

    def fill(self, b):
        """bMemSet(this, b, 528), spelled field by field."""
        w = struct.unpack("<f", bytes([b, b, b, b]))[0]
        self.NumPoints = i8(b)
        self.pad0 = bytearray([b] * 15)
        self.P = [[f32(w)] * 4 for _ in range(MAX_POINTS)]
        self.S = [f32(w)] * MAX_POINTS
        self.R = [i8(b)] * MAX_POINTS
        self.RPN = [i16(b | (b << 8))] * MAX_POINTS
        self.DL = [i8(b)] * MAX_POINTS
        w32 = struct.unpack("<i", bytes([b, b, b, b]))[0]
        self.TType = w32
        self.Pick = i8(b)
        self.pad1 = bytearray([b] * 3)
        self.CalcT = w32
        self.BlendT = w32
        self.Length = f32(w)
        self.pad2 = bytearray([b] * 12)

    def header_vec(self):
        """The record's own first sixteen bytes read as a bVector3. GetAngle
        reaches this when NumPoints is 0 or 1 -- `sll v0,i,4 ; addiu v0,v0,16`
        with i at -1 is a byte offset of zero, not an array subscript."""
        raw = bytes([u8(self.NumPoints)]) + bytes(self.pad0)
        return [f32(struct.unpack("<f", raw[k * 4:k * 4 + 4])[0])
                for k in range(4)]

    def point_at(self, i):
        if i >= 0:
            return self.P[i]
        if i == -1:
            return self.header_vec()
        # -2 is off the front of the whole record. No scenario reaches it
        # and the image would read the allocation's own header, so say so
        # rather than inventing a number.
        raise AssertionError("GetAngle index %d is off the record" % i)

    def clone(self):
        d = DriveTarget()
        assign(d, self)
        return d


def assign(dst, src):
    """0x00208788: bMemCpy(a0, a1, 528) and `move v0,s0`. The size is an
    immediate, so every byte goes -- padding included."""
    dst.NumPoints = src.NumPoints
    dst.pad0 = bytearray(src.pad0)
    dst.P = [list(p) for p in src.P]
    dst.S = list(src.S)
    dst.R = list(src.R)
    dst.RPN = list(src.RPN)
    dst.DL = list(src.DL)
    dst.TType = src.TType
    dst.Pick = src.Pick
    dst.pad1 = bytearray(src.pad1)
    dst.CalcT = src.CalcT
    dst.BlendT = src.BlendT
    dst.Length = src.Length
    dst.pad2 = bytearray(src.pad2)
    return dst


def copy_ctor(dst, src):
    """0x001da210, out of line in CarCollisionDetect.obj: five twenty-
    iteration loops and eight scalar stores. No memcpy, so the three pad
    runs keep whatever the destination already held."""
    for i in range(MAX_POINTS):
        dst.P[i] = list(src.P[i])
    for i in range(MAX_POINTS):
        dst.S[i] = src.S[i]
    for i in range(MAX_POINTS):
        dst.R[i] = src.R[i]
    for i in range(MAX_POINTS):
        dst.RPN[i] = src.RPN[i]
    for i in range(MAX_POINTS):
        dst.DL[i] = src.DL[i]
    dst.NumPoints = src.NumPoints
    dst.TType = src.TType
    dst.Pick = src.Pick
    dst.CalcT = src.CalcT
    dst.BlendT = src.BlendT
    dst.Length = src.Length
    return dst


def same_bytes(a, b):
    """What the harness's memcmp answers."""
    for name in ("NumPoints", "TType", "Pick", "CalcT", "BlendT"):
        if getattr(a, name) != getattr(b, name):
            return 0
    if a.Length != b.Length or struct.pack("<f", a.Length) != struct.pack(
            "<f", b.Length):
        return 0
    if bytes(a.pad0) != bytes(b.pad0):
        return 0
    if bytes(a.pad1) != bytes(b.pad1):
        return 0
    if bytes(a.pad2) != bytes(b.pad2):
        return 0
    for i in range(MAX_POINTS):
        if a.P[i] != b.P[i] or a.S[i] != b.S[i]:
            return 0
        if a.R[i] != b.R[i] or a.RPN[i] != b.RPN[i] or a.DL[i] != b.DL[i]:
            return 0
    return 1


class CarState(object):
    def __init__(self):
        self.Position = [ZERO] * 4
        self.Velocity = [ZERO] * 4
        self.Acceleration = [ZERO] * 4
        self.Angle = 0
        self.ForwardSpeed = ZERO
        self.VelocityMagnitude = ZERO
        self.MatrixValid = 0


class Car(object):
    """The stand-in drivetarget.h carries. Three live fields: DriverNumber
    at 10, pPlayer at 24 and the CarState at 64."""

    def __init__(self):
        self.DriverNumber = 0
        self.pPlayer = None
        self.State = CarState()


class TrackRoute(object):
    def __init__(self, number):
        self.RouteNumber = number


class RouteManager(object):
    def __init__(self):
        self.pTrackRoutes = [None] * 100

    def get(self, n):
        """trmgr_get_route's bound. The image has no upper test at all --
        see drivetarget.h -- and the port's divergence is this bound."""
        if n < 0 or n >= 100:
            return None
        return self.pTrackRoutes[n]


class DrivingLocation(object):
    def __init__(self, route=None, point=None, line=0):
        self.pRoute = route
        self.pRoutePoint = point   # an index, which is what the divide gives
        self.DrivingLine = line


TRM = RouteManager()


# ------------------------------------------------------ the free functions

def is_point_ahead_of_car(p, car, thresh):
    """0x001c0e30. Both vectors are normalised in place and the answer is a
    strict `thresh < dot`."""
    v = BV.bNormalize2((car.State.Velocity[0], car.State.Velocity[1]))
    d = BV.bNormalize2((fsub(p[0], car.State.Position[0]),
                        fsub(p[1], car.State.Position[1])))
    return 1 if thresh < fadd(fmul(v[0], d[0]), fmul(v[1], d[1])) else 0


def calculate_look_ahead_distance(car):
    """0x001c0c20, six instructions ending in max.s."""
    d = fmul(car.State.VelocityMagnitude, AI_SECONDS)
    return AI_DEFAULT if d < AI_DEFAULT else d


def straight_line_predict(car, t):
    """0x001c3338. One point, one look-ahead distance in front."""
    look = calculate_look_ahead_distance(car)

    if car.State.VelocityMagnitude < ONE:
        # bSinCos writes sine first and cosine second; the caller puts the
        # cosine in x. dir.pad is never written -- STACK-W, and the port
        # spells it 0.
        s, c = BM.bSinCos(car.State.Angle)
        d = [f32(c), f32(s), ZERO, ZERO]
    else:
        v = car.State.Velocity
        nx, ny, nz = BV.bNormalize3To((v[0], v[1], v[2]), ONE)
        d = [nx, ny, nz, v[3]]

    p = [fadd(fmul(d[k], look), car.State.Position[k]) for k in range(4)]
    clear(t, None, ZERO)
    add_point3(t, p, -1, -1, -1, 0, None)


# ------------------------------------------------------------ the lifetime

def init(t):
    """0x002086f8. The twenty-iteration loop at the top is nops; the two
    stamps are stored and then zeroed again by the memset behind them."""
    t.CalcT = 0
    t.BlendT = 0
    t.fill(0)
    clear(t, None, ZERO)
    return t


def destroy(t):
    """0x00208768 is the deleting destructor: `if (flag & 1) operator
    delete(this);` and nothing else."""
    return t


# ------------------------------------------------------------- the queries

def get_angle(t, i):
    """0x002087b8. `movz` up from -1 to 0, then `movn` down to
    NumPoints - 2, and nothing back up."""
    if i <= -1:
        i = 0
    if t.NumPoints - 2 < i:
        i = t.NumPoints - 2

    a = t.point_at(i)
    b = t.point_at(i + 1)
    return BM.bATan(fsub(b[0], a[0]), fsub(b[1], a[1]))


def calculate_time(a, b, c):
    """0x00209f40. Distance over the mean of the two speeds, with a
    sentinel when both are at rest."""
    if fabs32(b) <= K_TIME_EPS and fabs32(c) <= K_TIME_EPS:
        return K_NO_TIME
    return fdiv(a, fmul(fadd(b, c), HALF))


def get_max_lateral_acceleration():
    """0x00209f30: lui at,0x41f0 ; mtc1 at,$f0 ; jr ra."""
    return K_MAX_LATERAL


def recalculate_length(t):
    """0x0020a748. Length is zeroed in the branch's delay slot, so it
    happens whether the loop runs or not, and is reloaded from and stored
    back to the record on every pass."""
    n = t.NumPoints
    t.Length = ZERO
    if n - 1 <= 0:
        return
    for i in range(1, n):
        d = len3(fsub(t.P[i - 1][0], t.P[i][0]),
                 fsub(t.P[i - 1][1], t.P[i][1]),
                 fsub(t.P[i - 1][2], t.P[i][2]))
        t.Length = fadd(t.Length, d)


def get_route_and_route_point(t, i):
    """0x0020a7a8. Five ways to fail before the manager is touched, and a
    sixth -- a null test on a pointer 1064 bytes into an object -- that can
    never fire. Returns (rc, route, point index)."""
    if i < 0:
        return 0, None, None
    if not (i < t.NumPoints):
        return 0, None, None
    if t.R[i] == -1:
        return 0, None, None
    if t.RPN[i] == -1:
        return 0, None, None
    tr = None if t.R[i] < 0 else TRM.get(t.R[i])
    if tr is None:
        return 0, None, None
    return 1, tr, t.RPN[i]


def get_first_point(t, cs):
    """0x002091f0. Cached for the frame; the empty arm clears the stamp
    rather than setting it, so an empty target re-answers every call."""
    if WORLD_TIMER == t.CalcT:
        return t.Pick

    n = t.NumPoints
    if n <= 0:
        t.Pick = 0
        t.CalcT = 0
        return t.Pick

    thresh = K_AHEAD_DOT
    best = n - 1
    if K_FAST_CAR < cs.ForwardSpeed:
        thresh = ZERO

    vel = BV.bNormalize2((cs.Velocity[0], cs.Velocity[1]))

    i = 0
    while i < t.NumPoints:
        dx = fsub(t.P[i][0], cs.Position[0])
        dy = fsub(t.P[i][1], cs.Position[1])
        dn = BV.bNormalize2((dx, dy))
        if thresh < fadd(fmul(dn[0], vel[0]), fmul(dn[1], vel[1])):
            # The length test uses the unnormalised delta, still on the
            # stack.
            if MIN_DIST_SQ < fadd(fmul(dx, dx), fmul(dy, dy)):
                best = i
                break
        i += 1

    t.Pick = i8(best)
    t.CalcT = WORLD_TIMER
    return t.Pick


# ------------------------------------------------------------- the editors

def set_point3(t, i, p, route, rpn, dl, speed):
    """0x0020a6d0. The three narrow arguments arrive widened and are
    sign-extended back before anything else happens."""
    if i < 0:
        return
    if not (i < t.NumPoints):
        return

    t.P[i] = list(p)              # lqc2/sqc2, all sixteen bytes
    t.R[i] = i8(route)
    t.RPN[i] = i16(rpn)
    t.DL[i] = i8(dl)
    t.S[i] = speed
    t.CalcT = 0
    recalculate_length(t)


def set_point2(t, i, p, route, rpn, dl, speed):
    """0x0020a688. x, y, z = 0 and w left where it was -- STACK-W."""
    set_point3(t, i, [p[0], p[1], ZERO, ZERO], route, rpn, dl, speed)


def shift_right(t, n):
    """0x0020a478. The copy runs downwards so it can overlap, and the blank
    it leaves is partial: `sw zero,24` / `sw zero,16` / `sw zero,20` is z, x
    and y, plus RoutePointNumber and CalculatedSpeed. Route, DrivingLine
    and Points[i].pad keep what the slot held."""
    if not (n < MAX_POINTS):
        return

    for i in range(t.NumPoints - n - 1, -1, -1):
        d = i + n
        t.P[d] = list(t.P[i])
        t.R[d] = t.R[i]
        t.RPN[d] = t.RPN[i]
        t.DL[d] = t.DL[i]
        t.S[d] = t.S[i]

    # The store is in the branch's delay slot and is overwritten on the
    # clamped arm, so the truncation to int8_t shows either way.
    m = u8(t.NumPoints) + n
    t.NumPoints = i8(m)
    if not (i8(m) < 21):
        t.NumPoints = MAX_POINTS

    if n > 0:
        for i in range(n):
            t.P[i][2] = ZERO
            t.P[i][0] = ZERO
            t.P[i][1] = ZERO
            t.RPN[i] = -1
            t.S[i] = ZERO

    t.BlendT = 0
    t.CalcT = 0


def shift_left(t, n, recalc):
    """0x0020a5a8. The loop bound is recomputed from the record on every
    pass -- `lb v0,0(t2) ; subu v0,v0,t3` -- though nothing in the body
    writes NumPoints."""
    if not (n < t.NumPoints):
        return

    m = u8(t.NumPoints)
    if t.NumPoints - n > 0:
        for i in range(t.NumPoints - n):
            s = i + n
            t.P[i] = list(t.P[s])
            t.R[i] = t.R[s]
            t.RPN[i] = t.RPN[s]
            t.DL[i] = t.DL[s]
            t.S[i] = t.S[s]
            m = u8(t.NumPoints)

    t.CalcT = 0
    t.NumPoints = i8(m - n)
    t.BlendT = 0
    if recalc:
        recalculate_length(t)


# ---------------------------------------------------------- adding a point

def add_point3(t, p, route, rpn, dl, check, car):
    """0x00209048, the one every other overload funnels into."""
    n = t.NumPoints
    ok = 1

    if not (n < MAX_POINTS):
        return

    if check:
        if n < 2:
            # No direction in the target yet, so the car supplies one --
            # and with no car the point is simply accepted.
            if car is not None:
                ok = is_point_ahead_of_car(p, car, ZERO)
        else:
            ax = fsub(t.P[n - 1][0], t.P[n - 2][0])
            ay = fsub(t.P[n - 1][1], t.P[n - 2][1])
            az = fsub(t.P[n - 1][2], t.P[n - 2][2])
            bx = fsub(p[0], t.P[n - 1][0])
            by = fsub(p[1], t.P[n - 1][1])
            bz = fsub(p[2], t.P[n - 1][2])
            if fadd(fadd(fmul(ax, bx), fmul(ay, by)), fmul(az, bz)) < ZERO:
                ok = 0
    if not ok:
        return

    t.P[t.NumPoints] = list(p)
    t.R[t.NumPoints] = i8(route)
    t.RPN[t.NumPoints] = i16(rpn)
    t.DL[t.NumPoints] = i8(dl)
    t.CalcT = 0
    t.BlendT = 0
    t.S[t.NumPoints] = ZERO

    if t.NumPoints > 0:
        k = t.NumPoints
        t.Length = fadd(t.Length, len3(fsub(p[0], t.P[k - 1][0]),
                                       fsub(p[1], t.P[k - 1][1]),
                                       fsub(p[2], t.P[k - 1][2])))
    t.NumPoints = i8(u8(t.NumPoints) + 1)


def add_point2(t, p, route, rpn, dl, check, car):
    """0x00208f58. z is zeroed in the tail call's delay slot; w is not
    written at all -- STACK-W."""
    add_point3(t, [p[0], p[1], ZERO, ZERO], route, rpn, dl, check, car)


def add_point3_dl(t, p, loc, check, car):
    """0x00208e60. IsClear is called three times and the second and third
    can only answer what the first did, so the two -1 arms they guard are
    unreachable."""
    if loc.pRoute is None:
        return
    route = i8(loc.pRoute.RouteNumber)
    # The image divides the byte offset by 112 with (x * 0xB6DB6DB7) >> 4.
    # 112 is 16 * 7 and 0xB6DB6DB7 is 7's inverse mod 2^32, so it is exact
    # for any whole number of route points -- which is what an index is.
    rpn = i16(loc.pRoutePoint)
    dl = loc.DrivingLine
    add_point3(t, p, route, rpn, dl, check, car)


def add_point2_dl(t, p, loc, check, car):
    """0x00208e30. z is stored before the two loads rather than after,
    which changes nothing; w is left alone as usual."""
    add_point3_dl(t, [p[0], p[1], ZERO, ZERO], loc, check, car)


# -------------------------------------------------------- the path walkers

def interpolate_point(t, car, dist, out):
    """0x00208b98. The cumulative-distance array is indexed by point number
    rather than packed, so entries below `first` are never written and never
    read. Returns the index of the point *before* the one it landed on."""
    cum = [ZERO] * MAX_POINTS
    n = t.NumPoints

    if n == 0:
        return -1              # `out` is not written on this arm

    if n == 1:
        # Strike out towards the only point and stop at `dist`, overshoot or
        # not. All four lanes: pad rides through the subtract, the normalise
        # -- which does not write it -- and the add.
        d = [fsub(t.P[0][k], car.State.Position[k]) for k in range(4)]
        nx, ny, nz = BV.bNormalize3To((d[0], d[1], d[2]), dist)
        d[0], d[1], d[2] = nx, ny, nz
        for k in range(4):
            out[k] = fadd(car.State.Position[k], d[k])
        return 0

    first = get_first_point(t, car.State)
    i = first
    cum[i] = len3(fsub(t.P[i][0], car.State.Position[0]),
                  fsub(t.P[i][1], car.State.Position[1]),
                  fsub(t.P[i][2], car.State.Position[2]))

    if cum[i] < dist:
        i = first + 1
        while i < t.NumPoints:
            seg = len3(fsub(t.P[i][0], t.P[i - 1][0]),
                       fsub(t.P[i][1], t.P[i - 1][1]),
                       fsub(t.P[i][2], t.P[i - 1][2]))
            cum[i] = fadd(seg, cum[i - 1])
            # DummyFunction (0x00208b90) is a bare `jr ra` in the shipped
            # image -- a debug hook that survived as a call site.
            if dist <= cum[i]:
                break
            i += 1

    last = t.NumPoints - 1
    if last < i:
        # Ran off the end: carry on past the last point along the last leg.
        d = [fsub(t.P[last][k], t.P[last - 1][k]) for k in range(4)]
        nx, ny, nz = BV.bNormalize3To((d[0], d[1], d[2]),
                                      fsub(dist, cum[last]))
        d[0], d[1], d[2] = nx, ny, nz
        for k in range(4):
            out[k] = fadd(t.P[last][k], d[k])
        return last

    # Lerp across the segment that holds `dist`. The base is the car itself
    # on the first segment and the previous point after that, which is also
    # what the return value distinguishes.
    if first < i:
        prev = cum[i - 1]
        base = t.P[i - 1]
        ret = i - 1
    else:
        prev = ZERO
        base = car.State.Position
        ret = -1

    d = [fsub(t.P[i][k], base[k]) for k in range(4)]
    s = fdiv(fsub(dist, prev), fsub(cum[i], prev))
    for k in range(4):
        out[k] = fadd(fmul(d[k], s), base[k])
    return ret


def clear(t, car, speed):
    """0x00208980. Everything last frame decided is thrown away except the
    part of the path still in front of the car."""
    n = t.NumPoints
    if n == 0:
        t.Length = ZERO
        t.BlendT = 0
        t.CalcT = 0
        return

    # Standing still, or reversing, means there is no path worth keeping.
    if fabs32(speed) <= K_CLEAR_EPS or speed < ZERO:
        t.NumPoints = 0
        t.Length = ZERO
        t.BlendT = 0
        t.CalcT = 0
        return

    # Walk forward to the first point the car is still heading towards. The
    # comparison is against the raw velocity, not a normalised one, and it
    # is strict.
    i = 0
    while i < n:
        dx = fsub(t.P[i][0], car.State.Position[0])
        dy = fsub(t.P[i][1], car.State.Position[1])
        if ZERO < fadd(fmul(car.State.Velocity[0], dx),
                       fmul(car.State.Velocity[1], dy)):
            break
        i += 1
    if not (i < n):
        t.NumPoints = 0
        t.Length = ZERO
        t.BlendT = 0
        t.CalcT = 0
        return

    if i > 0:
        shift_left(t, i, 0)

    p = [ZERO] * 4
    r = interpolate_point(t, car, speed, p)
    if r < t.NumPoints - 1:
        if r >= 0:
            t.NumPoints = i8(r + 1)
            add_point3(t, p, t.R[r], t.RPN[r], t.DL[r], 0, None)
            recalculate_length(t)
            t.BlendT = 0
            t.CalcT = 0
            return
    elif r >= 0:
        t.BlendT = 0
        t.CalcT = 0
        return

    # r < 0: the interpolated point is on the first leg, so the whole target
    # collapses to it. The route data comes out of the slot GetFirstPoint
    # chose, read before NumPoints is zeroed.
    f = get_first_point(t, car.State)
    route = t.R[f]
    rpn = t.RPN[f]
    dl = t.DL[f]
    t.NumPoints = 0
    add_point3(t, p, route, rpn, dl, 0, None)
    recalculate_length(t)
    t.BlendT = 0
    t.CalcT = 0


def resample(t, car):
    """0x00209358. Respaces the points evenly along the path they already
    describe. The Car is taken and never read."""
    if t.NumPoints < 3:
        return

    raw = u8(t.NumPoints)
    n = i8(raw)
    out = [None] * MAX_POINTS
    seg = [[ZERO] * 4 for _ in range(MAX_POINTS)]
    ln = [ZERO] * MAX_POINTS

    t.Length = ZERO
    for k in range(n - 1):
        for c in range(4):
            seg[k][c] = fsub(t.P[k + 1][c], t.P[k][c])
        ln[k] = len3(seg[k][0], seg[k][1], seg[k][2])
        t.Length = fadd(t.Length, ln[k])

    # The last segment is a copy of the one before it, so the walk has
    # somewhere to go if it reaches the end.
    seg[n - 1] = list(seg[n - 2])
    ln[n - 1] = ln[n - 2]
    step = fdiv(t.Length, f32(float(n - 1)))

    k = 0
    emitted = ZERO     # f1, where the next point will sit
    travelled = ZERO   # f2, how far into segment k we are
    nxt = ZERO         # f3, where the point just emitted sits
    limit = n
    j = 0

    if n > 0 and ZERO <= t.Length:
        while True:
            nxt = emitted
            emitted = fadd(nxt, step)
            frac = fdiv(travelled, ln[k])
            out[j] = [fadd(t.P[k][c], fmul(seg[k][c], frac))
                      for c in range(4)]
            travelled = fadd(travelled, step)
            j += 1

            if not (emitted <= t.Length):
                break
            if not (k < n):
                break
            if ln[k] <= travelled:
                # Step over as many whole segments as the accumulator covers.
                done = False
                while True:
                    if not (emitted <= t.Length):
                        break
                    travelled = fsub(travelled, ln[k])
                    k += 1
                    if not (k < limit):
                        done = True
                        break
                    if not (ln[k] <= travelled):
                        break
                if done:
                    break
            if not (k < n):
                break
            if not (emitted <= t.Length):
                break

    # Length becomes the distance of the *last* point emitted, not the path
    # length it started from.
    t.Length = nxt
    if j < n:
        # The image would memcpy stack it never wrote. No scenario reaches
        # it; say so loudly rather than inventing zeroes.
        raise AssertionError("Resample emitted %d of %d points" % (j, n))
    for k in range(n):
        t.P[k] = list(out[k])
    t.BlendT = 0
    t.CalcT = 0


# ------------------------------------------------------------- the scoring

def calculate_max_speed(car, p0, p1, p2, dist, speed, out):
    """0x00209cf0. Two velocity vectors, the acceleration between them, and
    whether its lateral part fits inside the grip. Returns (rc, out)."""
    if fabs32(speed) <= K_MAXSPEED_EPS:
        return 1, out
    if fabs32(dist) <= K_MAXSPEED_EPS:
        return 1, speed

    v1 = BV.bNormalize2To((fsub(p1[0], p0[0]), fsub(p1[1], p0[1])), speed)
    v2 = BV.bNormalize2To((fsub(p2[0], p1[0]), fsub(p2[1], p1[1])), out)
    dvx = fsub(v2[0], v1[0])
    dvy = fsub(v2[1], v1[1])

    time = calculate_time(dist, speed, out)
    if fabs32(time) <= K_MAXSPEED_EPS:
        return 1, speed

    # The reciprocal is taken once and multiplied twice, which is not the
    # same as dividing twice.
    inv = fdiv(ONE, time)
    accy = fmul(dvy, inv)
    accx = fmul(dvx, inv)

    k = fdiv(fadd(fmul(v1[0], accx), fmul(v1[1], accy)),
             fadd(fmul(v1[0], v1[0]), fmul(v1[1], v1[1])))
    pary = fmul(v1[1], k)
    parx = fmul(v1[0], k)
    perpy = fsub(accy, pary)
    perpx = fsub(accx, parx)

    mag = len2(perpx, perpy)

    # The parallel magnitude is computed here too and never used. Dead in
    # the shipped image, kept because the image has it.
    len2(parx, pary)

    grip = get_max_lateral_acceleration()
    if mag < grip:
        return 1, out
    if fabs32(fsub(mag, grip)) <= K_MAXSPEED_EPS:
        return 1, out
    return 0, out


def estimate_score(t, car):
    """0x002096b0, 1596 bytes. Fills CalculatedSpeed with the car's current
    speed, walks the points in two nested passes asking CalculateMaxSpeed
    whether each corner fits, and returns the distance-weighted mean of the
    speeds -- or -1.0f if any corner did not."""
    # The image leaves this stack array untouched below `first`, and a stale
    # WhichPointIPicked past NumPoints would then read an entry nothing
    # wrote. The port zeroes it and says so; the model does the same.
    dist = [ZERO] * MAX_POINTS
    ok = 1
    bail = 0
    max_ok = 1
    leg = ZERO

    if t.NumPoints == 0:
        return f32(-1.0)

    cs = car.State
    if t.NumPoints == 1:
        # A single point is scored off the car's own speed and bails before
        # any of the corner tests.
        t.S[0] = cs.VelocityMagnitude
        dist[0] = len2(fsub(car.State.Position[0], t.P[0][0]),
                       fsub(car.State.Position[1], t.P[0][1]))
        bail = 1

    first = get_first_point(t, cs)
    if first < t.NumPoints and not bail:
        i = first
        while True:
            t.S[i] = cs.VelocityMagnitude
            if first < i:
                dx = fsub(t.P[i][0], t.P[i - 1][0])
                dy = fsub(t.P[i][1], t.P[i - 1][1])
            else:
                dx = fsub(t.P[i][0], car.State.Position[0])
                dy = fsub(t.P[i][1], car.State.Position[1])
            dist[i] = len2(dx, dy)
            i += 1
            if not (i < t.NumPoints):
                break
            if bail:
                break

    if not bail:
        # Pass one: from the chosen point, skip forward while the car
        # reaches the next point inside the first threshold.
        cur = first
        leg = dist[first]
        max_ok = 1
        if calculate_time(leg, cs.VelocityMagnitude, t.S[first]) < K_SCORE_T1:
            if first < t.NumPoints:
                cur = first + 1
                while True:
                    dx = fsub(car.State.Position[0], t.P[cur][0])
                    dy = fsub(car.State.Position[1], t.P[cur][1])
                    leg = len2(dx, dy)
                    if not (calculate_time(leg, cs.VelocityMagnitude,
                                           t.S[cur]) < K_SCORE_T2):
                        break
                    if not (cur < t.NumPoints):
                        break
                    cur += 1

        nxt = cur + 1
        if nxt < t.NumPoints:
            max_ok, t.S[cur] = calculate_max_speed(
                car, car.State.Position, t.P[cur], t.P[nxt],
                leg, cs.VelocityMagnitude, t.S[cur])
        if max_ok == 0:
            ok = 0
            bail = 1

        if not bail:
            cur = nxt
            if cur + 1 < t.NumPoints:
                nxt = cur + 1

                # Pass two: the same question for every remaining corner,
                # with the same skip-ahead inside it. The inner walk always
                # measures back to Points[outer - 1], which stays put.
                while True:
                    outer = cur
                    leg = len2(fsub(t.P[outer - 1][0], t.P[outer][0]),
                               fsub(t.P[outer - 1][1], t.P[outer][1]))

                    if calculate_time(leg, t.S[outer - 1],
                                      t.S[outer]) < K_SCORE_T3:
                        if outer < t.NumPoints:
                            while True:
                                cur = nxt
                                leg = len2(
                                    fsub(t.P[outer - 1][0], t.P[nxt][0]),
                                    fsub(t.P[outer - 1][1], t.P[nxt][1]))
                                if not (calculate_time(leg, t.S[outer - 1],
                                                       t.S[nxt]) < K_SCORE_T3):
                                    nxt += 1
                                    break
                                if not (nxt < t.NumPoints):
                                    nxt += 1
                                    break
                                nxt += 1

                    if nxt < t.NumPoints:
                        max_ok, t.S[cur] = calculate_max_speed(
                            car, t.P[outer - 1], t.P[cur], t.P[nxt],
                            leg, t.S[outer - 1], t.S[cur])
                        cur = nxt
                    else:
                        bail = 1

                    if max_ok == 0:
                        ok = 0
                        bail = 1
                    if bail:
                        break
                    nxt = cur + 1
                    if not (nxt < t.NumPoints):
                        break

    if not ok:
        return f32(-1.0)

    # A trapezoid sum of speed against distance divided by the distance:
    # the mean speed weighted by how long the car spends at it.
    total = dist[first]
    acc = fmul(fmul(dist[first], HALF),
               fadd(t.S[first], cs.VelocityMagnitude))
    for i in range(first + 1, t.NumPoints):
        total = fadd(total, dist[i])
        acc = fadd(acc, fmul(fmul(dist[i], HALF),
                             fadd(t.S[i], t.S[i - 1])))
        if not ok:
            break

    if ZERO < total:
        return fdiv(acc, total)
    return f32(-1.0)


# ------------------------------------------------------- the two predictors

def fill_with_current_acceleration(t, car):
    """0x00209fb0. Where the car would go if it kept accelerating exactly as
    it is now. The acceleration is sampled once and held."""
    clear(t, None, ZERO)
    look = calculate_look_ahead_distance(car)

    px, py = car.State.Position[0], car.State.Position[1]
    vx, vy = car.State.Velocity[0], car.State.Velocity[1]
    ax, ay = car.State.Acceleration[0], car.State.Acceleration[1]

    # Past three quarters of the speed the acceleration is not trusted and
    # a straight line is used: `c.lt.s $f0,$f2` with $f0 the speed times
    # 0.75 and $f2 the acceleration, then `bc1f` past the call. This model
    # once had the test negated, and so did the port, and they agreed;
    # realcontroller_check.py runs the image and is what found it.
    if fmul(len2(vx, vy), K_ACC_DOMINATES) < len2(ax, ay):
        straight_line_predict(car, t)
        return

    if not (ZERO < look):
        return
    if not (t.NumPoints < MAX_POINTS):
        return

    travelled = ZERO
    while True:
        nvx, nvy = BV.bScaleAdd2((vx, vy), (ax, ay), K_PREDICT_DT)
        npx, npy = BV.bScaleAdd2((px, py), (nvx, nvy), K_PREDICT_DT)
        add_point2(t, (npx, npy), -1, -1, -1, 1, None)

        travelled = fadd(travelled, len2(fsub(px, npx), fsub(py, npy)))

        # The turn-back test is against the car's *original* velocity,
        # re-read out of the CarState every pass.
        dot = fadd(fmul(nvx, car.State.Velocity[0]),
                   fmul(nvy, car.State.Velocity[1]))
        px, py = npx, npy
        vx, vy = nvx, nvy
        if dot < ZERO:
            return
        if not (travelled < look):
            return
        if not (t.NumPoints < MAX_POINTS):
            return


def blend_with_current_acceleration(t, car):
    """0x0020a1d8. The same integration, but each point is dragged part of
    the way towards where the car is actually heading -- all the way at
    t = 0, not at all by 0.75s."""
    if t.BlendT == WORLD_TIMER:
        return
    if car.pPlayer is not None:
        return          # a human's target is left alone
    t.BlendT = WORLD_TIMER

    px, py = car.State.Position[0], car.State.Position[1]
    vx, vy = car.State.Velocity[0], car.State.Velocity[1]
    ax, ay = car.State.Acceleration[0], car.State.Acceleration[1]
    vel_mag = car.State.VelocityMagnitude

    i = get_first_point(t, car.State)
    if vel_mag < ONE:
        return
    if not (i < t.NumPoints):
        return

    acc_time = ZERO
    while True:
        # The leg is measured from the car for the point GetFirstPoint
        # chose and from the previous point for everything after it.
        # WhichPointIPicked is re-read every pass.
        if i == t.Pick:
            dx = fsub(car.State.Position[0], t.P[i][0])
            dy = fsub(car.State.Position[1], t.P[i][1])
        else:
            dx = fsub(t.P[i - 1][0], t.P[i][0])
            dy = fsub(t.P[i - 1][1], t.P[i][1])

        dt = fdiv(len2(dx, dy), vel_mag)
        acc_time = fadd(acc_time, dt)
        nvx, nvy = BV.bScaleAdd2((vx, vy), (ax, ay), dt)
        npx, npy = BV.bScaleAdd2((px, py), (nvx, nvy), dt)

        blend = fmul(acc_time, K_BLEND_SCALE)
        if ONE < blend:
            blend = ONE
        inv = fsub(ONE, blend)

        bx = fadd(fmul(t.P[i][0], blend), fmul(npx, inv))
        by = fadd(fmul(t.P[i][1], blend), fmul(npy, inv))

        route = t.R[i]
        rpn = t.RPN[i]
        dl = t.DL[i]
        vx, vy = nvx, nvy
        px, py = npx, npy
        set_point3(t, i, [bx, by, ZERO, ZERO], route, rpn, dl, ZERO)
        i += 1

        if not (acc_time < K_BLEND_WINDOW):
            return
        if not (i < t.NumPoints):
            return


# ------------------------------------------------------------------- debug

def dump(t, car, check_camera):
    """0x002095f8. The prints are gone from the shipped image; what is left
    asks the CarState for its transform, which is the only observable thing
    it still does."""
    if check_camera:
        if CAM_DEFAULT != 0:
            return
        if car.DriverNumber != CAM_INSTEAD:
            return

    for _ in range(t.NumPoints):
        if car is not None:
            # CarState::GetTransformMatrix builds RelCoordMatrix and sets
            # MatrixValid the first time it is asked.
            car.State.MatrixValid = 1


# ------------------------------------------------------------ the transcript

def timer(v):
    global WORLD_TIMER
    WORLD_TIMER = v


def pdt(tag, t, n):
    """The scalars, then `n` slots. The slot count is given per call site
    rather than taken from NumPoints, because the interesting part of
    ShiftRight and ShiftLeft is what they leave past the end."""
    emit("%s n %d len %s pick %d calct %d blendt %d ttype %d"
         % (tag, t.NumPoints, g9(t.Length), t.Pick, t.CalcT, t.BlendT,
            t.TType))
    for i in range(n):
        emit("%s [%02d] %s %s %s %s  s %s r %d p %d d %d"
             % (tag, i, g9(t.P[i][0]), g9(t.P[i][1]), g9(t.P[i][2]),
                g9(t.P[i][3]), g9(t.S[i]), t.R[i], t.RPN[i], t.DL[i]))


def ppad(tag, t):
    emit("%s pad0 %s" % (tag, " ".join("%02x" % b for b in t.pad0)))
    emit("%s pad1 %02x %02x %02x" % (tag, t.pad1[0], t.pad1[1], t.pad1[2]))
    emit("%s pad2 %s" % (tag, " ".join("%02x" % b for b in t.pad2)))


def pv3(tag, v):
    emit("%s %s %s %s %s" % (tag, g9(v[0]), g9(v[1]), g9(v[2]), g9(v[3])))


# ---------------------------------------------------------------- fixtures

def dt_reset(t):
    t.fill(0)


def dt_point(t, i, x, y, z, speed, route, rpn, dl):
    t.P[i] = [f32(x), f32(y), f32(z), ZERO]
    t.S[i] = f32(speed)
    t.R[i] = i8(route)
    t.RPN[i] = i16(rpn)
    t.DL[i] = i8(dl)


def car_set(c, px, py, vx, vy, ax, ay, angle, fwd, vmag):
    c.DriverNumber = 0
    c.pPlayer = None
    s = c.State
    s.Position = [f32(px), f32(py), ZERO, ZERO]
    s.Velocity = [f32(vx), f32(vy), ZERO, ZERO]
    s.Acceleration = [f32(ax), f32(ay), ZERO, ZERO]
    s.Angle = angle & 0xFFFF
    s.ForwardSpeed = f32(fwd)
    s.VelocityMagnitude = f32(vmag)
    s.MatrixValid = 0


def dt_dirty_pads(t):
    """ShiftRight blanks x, y, z, CalculatedSpeed and RoutePointNumber and
    leaves Route, DrivingLine and the fourth lane alone. dt_point writes
    0.0 into every pad, so a kept pad and a blanked one are the same
    number until something puts a different one there."""
    for i in range(MAX_POINTS):
        t.P[i][3] = f32(100 + i)


def dt_straight(t):
    """Five points ten metres apart, running east."""
    dt_reset(t)
    dt_point(t, 0, 10.0, 0.0, 0.0, 20.0, 3, 11, 1)
    dt_point(t, 1, 20.0, 0.0, 0.0, 21.0, 3, 12, 1)
    dt_point(t, 2, 30.0, 0.0, 0.0, 22.0, 3, 13, 1)
    dt_point(t, 3, 40.0, 0.0, 0.0, 23.0, 3, 14, 2)
    dt_point(t, 4, 50.0, 0.0, 0.0, 24.0, 4, 15, 2)
    t.NumPoints = 5
    recalculate_length(t)


def dt_corner(t):
    """The same five bent into a corner, with a z step so the three-lane
    sums cannot pass by accident."""
    dt_reset(t)
    dt_point(t, 0, 10.0, 1.0, 0.25, 18.0, 3, 11, 1)
    dt_point(t, 1, 19.0, 5.0, 0.5, 17.0, 3, 12, 1)
    dt_point(t, 2, 25.0, 13.0, 0.75, 16.0, 3, 13, 1)
    dt_point(t, 3, 28.0, 23.0, 1.0, 15.0, 3, 14, 2)
    dt_point(t, 4, 28.5, 34.0, 1.25, 14.0, 4, 15, 2)
    t.NumPoints = 5
    recalculate_length(t)


ROUTE_A = TrackRoute(3)
ROUTE_B = TrackRoute(4)
# Route zero: the sentinel for "no route" is -1, so only a route the
# manager actually has at index zero can say which of the two it is.
ROUTE_C = TrackRoute(0)


def routes_init():
    TRM.pTrackRoutes = [None] * 100
    TRM.pTrackRoutes[0] = ROUTE_C
    TRM.pTrackRoutes[3] = ROUTE_A
    TRM.pTrackRoutes[4] = ROUTE_B


# ------------------------------------------------------------- the scenarios

def s_layout():
    pint("ly sizeof", 528)
    pint("ly points", 16)
    pint("ly speed", 336)
    pint("ly route", 416)
    pint("ly rpn", 436)
    pint("ly dline", 476)
    pint("ly ttype", 496)
    pint("ly pick", 500)
    pint("ly calct", 504)
    pint("ly blendt", 508)
    pint("ly length", 512)
    pint("ly maxpoints", MAX_POINTS)
    # The three Car offsets DriveTarget reads. They were 10, 24 and 64
    # flat while drivetarget.h carried its own stand-in Car, whose
    # padding was written to cancel the host pointer slack. The stand-in
    # is gone and car.h's real 2016-byte record is included instead, so
    # the host offsets now carry the slack the way car.h spells them --
    # CAR_AT(DriverNumber, 10, 2), CAR_AT(pPlayer, 24, 6),
    # CAR_AT(State, 64, 12). On ARM the slack is zero and all three are
    # the PS2 numbers again.
    pint("ly car driver", 10 + 2 * CAR_SLACK)
    pint("ly car player", 24 + 6 * CAR_SLACK)
    pint("ly car state", 64 + 12 * CAR_SLACK)
    # DrivingLocation is two pointers and a byte, so its offsets widen with
    # the host's pointer where DriveTarget's do not.
    pint("ly dl route", 0)
    pint("ly dl point", PTR)
    pint("ly dl line", 2 * PTR)


def s_constants():
    static_init()
    pf("k seconds", AI_SECONDS)
    pf("k default", AI_DEFAULT)
    pf("k mindist", MIN_DIST)
    pf("k mindistsq", MIN_DIST_SQ)
    pint("k camdefault", CAM_DEFAULT)
    pint("k caminstead", CAM_INSTEAD)
    pf("k maxlat", get_max_lateral_acceleration())


def s_ctor():
    t = DriveTarget()

    # Dirty every byte first, so the memset has something to prove.
    t.fill(0xA5)
    t.NumPoints = 7
    init(t)
    pdt("ct init", t, 3)
    ppad("ct init", t)

    dt_corner(t)
    for i in range(1, 16):
        t.pad0[i - 1] = (0x10 + i) & 0xFF
    t.pad1[0], t.pad1[1], t.pad1[2] = 0x71, 0x72, 0x73
    for i in range(516, 528):
        t.pad2[i - 516] = (0x80 + i - 516) & 0xFF
    t.TType = 9
    t.Pick = 2
    t.CalcT = 44
    t.BlendT = 55

    a = DriveTarget()
    b = DriveTarget()
    a.fill(0x3C)
    b.fill(0x3C)
    pint("ct assign is dst", 1 if assign(a, t) is a else 0)
    copy_ctor(b, t)
    # All twenty slots: the copy constructor's five loops run to twenty and
    # the destinations start dirty, so a loop one short shows.
    pdt("ct assign", a, 20)
    ppad("ct assign", a)
    pdt("ct copy", b, 20)
    ppad("ct copy", b)
    pint("ct same", same_bytes(a, b))

    destroy(t)
    pdt("ct dtor", t, 1)


def s_get_angle():
    t = DriveTarget()

    dt_corner(t)
    for i in range(-3, 7):
        pint("ga corner", get_angle(t, i))

    # Two points is the smallest list the clamp keeps inside the array.
    dt_reset(t)
    dt_point(t, 0, 1.0, 2.0, 0.0, 0.0, -1, -1, -1)
    dt_point(t, 1, 4.0, 6.0, 0.0, 0.0, -1, -1, -1)
    t.NumPoints = 2
    for i in range(-1, 3):
        pint("ga two", get_angle(t, i))

    # One point clamps the index to -1, which reads the record's own first
    # sixteen bytes as a vector. They are zero on a record the constructor
    # built, so this is defined and deterministic.
    init(t)
    dt_point(t, 0, 3.0, 4.0, 0.0, 0.0, -1, -1, -1)
    t.NumPoints = 1
    pint("ga one", get_angle(t, 0))


def s_calculate_time():
    d = [f32(100.0), ZERO, f32(-50.0)]
    b = [f32(20.0), ZERO, f32(0.0005), f32(-20.0), f32(0.001)]
    c = [f32(30.0), ZERO, f32(0.0005), f32(0.001)]
    for i in range(3):
        for j in range(5):
            for k in range(4):
                pf("ti", calculate_time(d[i], b[j], c[k]))


def s_recalculate_length():
    t = DriveTarget()

    dt_corner(t)
    t.Length = f32(123.0)
    t.NumPoints = 0
    recalculate_length(t)
    pf("rl zero", t.Length)

    t.NumPoints = 1
    t.Length = f32(123.0)
    recalculate_length(t)
    pf("rl one", t.Length)

    t.NumPoints = 2
    recalculate_length(t)
    pf("rl two", t.Length)

    t.NumPoints = 5
    recalculate_length(t)
    pf("rl five", t.Length)

    # (x*x + y*y) + z*z and no other grouping. A half-ulp fixture is no
    # use here: the two sums differ by one ulp and the square root halves
    # that, so it rounds back to the same float. These three legs are one
    # of the triples where the two groupings round apart and the root
    # keeps them apart -- 25.4676304 against 25.4676323.
    dt_reset(t)
    dt_point(t, 0, 0.0, 0.0, 0.0, 0.0, -1, -1, -1)
    dt_point(t, 1, -0.599609375, -20.515625, -15.078125, 0.0, -1, -1, -1)
    t.NumPoints = 2
    recalculate_length(t)
    pf("rl assoc", t.Length)

    # A negative count takes the same early-out as zero.
    t.NumPoints = -3
    t.Length = f32(123.0)
    recalculate_length(t)
    pf("rl neg", t.Length)


def s_set_point():
    t = DriveTarget()

    dt_corner(t)
    p3 = [f32(99.0), f32(98.0), f32(97.0), f32(96.0)]
    set_point3(t, 2, p3, 7, 71, 3, f32(33.0))
    pdt("sp wide", t, 5)

    set_point3(t, -1, p3, 8, 81, 4, f32(34.0))
    set_point3(t, 5, p3, 8, 81, 4, f32(34.0))
    set_point3(t, 19, p3, 8, 81, 4, f32(34.0))
    pdt("sp oob", t, 6)

    set_point2(t, 0, (f32(55.0), f32(44.0)), -1, -1, -1, ZERO)
    pdt("sp narrow", t, 2)

    # The time stamp is cleared by every accepted write and left alone by
    # every rejected one.
    t.CalcT = 12
    set_point3(t, 7, p3, 1, 1, 1, ONE)
    pint("sp calct kept", t.CalcT)
    set_point3(t, 1, p3, 1, 1, 1, ONE)
    pint("sp calct cleared", t.CalcT)


def s_shift_right():
    t = DriveTarget()

    for n in range(4):
        dt_corner(t)
        dt_dirty_pads(t)
        t.CalcT = 5
        t.BlendT = 6
        shift_right(t, n)
        pdt("sr", t, 9)

    # Twenty is refused; nineteen is not.
    dt_corner(t)
    shift_right(t, 20)
    pdt("sr twenty", t, 6)
    dt_corner(t)
    shift_right(t, 19)
    pdt("sr nineteen", t, 20)

    # The clamp: seventeen points plus five slots would be twenty-two.
    dt_reset(t)
    for n in range(17):
        dt_point(t, n, float(n), 0.0, 0.0, 1.0, 2, n, 1)
    t.NumPoints = 17
    shift_right(t, 5)
    pdt("sr clamp", t, 20)


def s_shift_left():
    t = DriveTarget()

    for n in range(6):
        dt_corner(t)
        t.CalcT = 5
        t.BlendT = 6
        shift_left(t, n, 1)
        pdt("sl recalc", t, 6)

    dt_corner(t)
    shift_left(t, 2, 0)
    pdt("sl keep", t, 6)

    # n == NumPoints is refused, so the list can never be emptied this way.
    dt_corner(t)
    shift_left(t, 5, 1)
    pdt("sl all", t, 6)


def s_route_point():
    t = DriveTarget()

    routes_init()
    dt_corner(t)
    t.R[2] = -1                 # no route
    t.RPN[3] = -1               # no point
    t.R[1] = 7                  # a route the manager does not have

    # Three more slots, because the first five cannot separate the bound
    # from the sentinel: route zero is a route the manager has and not a
    # refusal, -3 is below the sentinel rather than equal to it, and slot
    # 7 is past NumPoints rather than past twenty.
    t.NumPoints = 7
    t.R[5], t.RPN[5], t.DL[5] = 0, 4, 1
    t.R[6], t.RPN[6], t.DL[6] = -3, 5, 1
    t.R[7], t.RPN[7], t.DL[7] = 4, 6, 1

    for i in range(-1, 9):
        got, r, p = get_route_and_route_point(t, i)
        emit("rp %d -> %d route %d point %d"
             % (i, got, r.RouteNumber if r is not None else -99,
                p if p is not None else -99))


def s_first_point():
    t = DriveTarget()
    car = Car()

    routes_init()
    timer(100)

    # Straight ahead at 20 m/s: the first point is already further away
    # than the four-metre minimum, so it wins.
    dt_straight(t)
    car_set(car, 0.0, 0.0, 20.0, 0.0, 0.0, 0.0, 0, 20.0, 20.0)
    pint("fp ahead", get_first_point(t, car.State))
    pint("fp calct", t.CalcT)

    # The answer is cached for the frame.
    car.State.Position[0] = f32(45.0)
    pint("fp cached", get_first_point(t, car.State))
    timer(101)
    pint("fp uncached", get_first_point(t, car.State))

    # Sitting on top of the first point: it fails the distance test.
    timer(102)
    car_set(car, 8.0, 0.0, 20.0, 0.0, 0.0, 0.0, 0, 20.0, 20.0)
    pint("fp tooclose", get_first_point(t, car.State))

    # Driving away from the whole list: the fallback is the last point.
    timer(103)
    car_set(car, 0.0, 0.0, -20.0, 0.0, 0.0, 0.0, 0, -20.0, 20.0)
    pint("fp behind", get_first_point(t, car.State))

    # The cone is 70 degrees wide, until the car is over 30 m/s.
    timer(104)
    dt_reset(t)
    dt_point(t, 0, 5.0, 8.66025, 0.0, 0.0, 2, 1, 1)        # 60 degrees
    dt_point(t, 1, 1.73648, 9.84808, 0.0, 0.0, 2, 2, 1)
    dt_point(t, 2, 30.0, 0.0, 0.0, 0.0, 2, 3, 1)
    t.NumPoints = 3
    car_set(car, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 0, 10.0, 10.0)
    pint("fp cone60", get_first_point(t, car.State))

    timer(105)
    dt_reset(t)
    dt_point(t, 0, 1.73648, 9.84808, 0.0, 0.0, 2, 2, 1)    # 80 degrees
    dt_point(t, 1, 30.0, 0.0, 0.0, 0.0, 2, 3, 1)
    t.NumPoints = 2
    pint("fp cone80", get_first_point(t, car.State))

    timer(106)
    car.State.ForwardSpeed = f32(31.0)
    pint("fp cone80 fast", get_first_point(t, car.State))

    # Exactly 30 is not "fast": the test is strict.
    timer(107)
    car.State.ForwardSpeed = f32(30.0)
    pint("fp cone80 at30", get_first_point(t, car.State))

    # Sixty-five degrees off the heading is a dot of 0.42262, clear of
    # the 0.342 threshold on one side and of a half on the other. The
    # sixty-degree point above is 0.50000018 after the normalise -- one
    # ulp the wrong side of a half, and so no use for saying where the
    # threshold is.
    timer(109)
    dt_reset(t)
    dt_point(t, 0, 4.2262, 9.0631, 0.0, 0.0, 2, 1, 1)
    dt_point(t, 1, 30.0, 0.0, 0.0, 0.0, 2, 3, 1)
    t.NumPoints = 2
    car_set(car, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 0, 10.0, 10.0)
    pint("fp cone65", get_first_point(t, car.State))

    # Over thirty the threshold is exactly zero, and a point straight
    # abeam normalises to (0,1) against a heading of (1,0) for a dot of
    # exactly zero. The test is strict, so the point is refused.
    timer(110)
    dt_reset(t)
    dt_point(t, 0, 0.0, 10.0, 0.0, 0.0, 2, 1, 1)
    dt_point(t, 1, 30.0, 0.0, 0.0, 0.0, 2, 3, 1)
    t.NumPoints = 2
    car.State.ForwardSpeed = f32(31.0)
    pint("fp perp fast", get_first_point(t, car.State))

    # An empty target answers zero and clears the stamp.
    timer(108)
    dt_reset(t)
    t.Pick = 9
    pint("fp empty", get_first_point(t, car.State))
    pint("fp empty calct", t.CalcT)


def s_add_point():
    t = DriveTarget()
    car = Car()

    routes_init()
    timer(200)

    # No check: everything lands, and Length grows by each leg.
    dt_reset(t)
    for i in range(3):
        p3 = [f32(10.0 * (i + 1)), ZERO, f32(0.5), f32(0.25)]
        add_point3(t, p3, i + 1, i + 10, i, 0, None)
    pdt("ap free", t, 4)

    # Checked with two points already there.
    p3 = [f32(40.0), ZERO, f32(0.5), ZERO]
    add_point3(t, p3, 5, 15, 1, 1, None)
    pint("ap forward n", t.NumPoints)
    p3 = [f32(5.0), ZERO, f32(0.5), ZERO]
    add_point3(t, p3, 6, 16, 1, 1, None)
    pint("ap back n", t.NumPoints)

    # Exactly perpendicular gives a dot of zero, which is not less than
    # zero, so it is accepted.
    p3 = [f32(40.0), f32(12.0), f32(0.5), ZERO]
    add_point3(t, p3, 7, 17, 1, 1, None)
    pint("ap perp n", t.NumPoints)
    pdt("ap checked", t, 6)

    # Checked with fewer than two points: the car decides, and with no car
    # the point is simply taken.
    dt_reset(t)
    car_set(car, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 0, 10.0, 10.0)
    p3 = [f32(20.0), ZERO, ZERO, ZERO]
    add_point3(t, p3, 1, 1, 1, 1, car)
    pint("ap car ahead", t.NumPoints)
    p3 = [f32(-20.0), ZERO, ZERO, ZERO]
    add_point3(t, p3, 2, 2, 2, 1, car)
    pint("ap car behind", t.NumPoints)
    add_point3(t, p3, 2, 2, 2, 1, None)
    pint("ap nocar", t.NumPoints)

    # The doubling-back test is three lanes and every fixture above is
    # flat, so the third has never mattered. Here it decides: the two-lane
    # dot is -0.5 and the z term is +6.
    dt_reset(t)
    dt_point(t, 0, 0.0, 0.0, 0.0, 0.0, 1, 1, 1)
    dt_point(t, 1, 1.0, 0.0, 3.0, 0.0, 1, 2, 1)
    t.NumPoints = 2
    add_point3(t, [f32(0.5), ZERO, f32(5.0), ZERO], 2, 3, 1, 1, None)
    pint("ap z saves n", t.NumPoints)

    # The car form is called with a threshold of zero, so seventy-five
    # degrees off the heading -- a dot of 0.25882 -- still counts.
    dt_reset(t)
    car_set(car, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 0, 10.0, 10.0)
    add_point3(t, [f32(2.5882), f32(9.6593), ZERO, ZERO], 1, 1, 1, 1, car)
    pint("ap car 75deg", t.NumPoints)

    # Both stamps are cleared on the way through, and they are cleared
    # separately -- two stores, not one.
    dt_reset(t)
    t.CalcT = 44
    t.BlendT = 45
    add_point3(t, [f32(1.0), f32(2.0), f32(3.0), ZERO], 2, 3, 1, 0, None)
    pdt("ap stamps", t, 1)

    # Twenty is the wall.
    dt_reset(t)
    for i in range(25):
        add_point3(t, [f32(float(i)), ZERO, ZERO, ZERO], 0, i, 0, 0, None)
    pint("ap full", t.NumPoints)

    # The narrow overload zeroes z and the port zeroes pad with it.
    dt_reset(t)
    add_point2(t, (f32(3.0), f32(4.0)), -1, -1, -1, 0, None)
    pdt("ap narrow", t, 1)

    # The DrivingLocation overloads unpack the location. A clear one is
    # dropped before anything else happens.
    dt_reset(t)
    loc = DrivingLocation(None, None, 5)
    p3 = [f32(1.0), f32(2.0), f32(3.0), f32(4.0)]
    add_point3_dl(t, p3, loc, 0, None)
    pint("ap dl clear n", t.NumPoints)

    loc.pRoute = ROUTE_B
    loc.pRoutePoint = 17
    add_point3_dl(t, p3, loc, 0, None)
    loc.pRoutePoint = 0
    loc.DrivingLine = -1
    add_point2_dl(t, (f32(9.0), f32(8.0)), loc, 0, None)
    pdt("ap dl", t, 2)


def s_interpolate():
    t = DriveTarget()
    car = Car()
    dists = [f32(5.0), f32(15.0), f32(25.0), f32(55.0), f32(100.0)]

    routes_init()
    timer(300)

    # No points: the answer is -1 and `out` is not written.
    dt_reset(t)
    car_set(car, 0.0, 0.0, 20.0, 0.0, 0.0, 0.0, 0, 20.0, 20.0)
    out = [f32(1.0), f32(2.0), f32(3.0), f32(4.0)]
    r = interpolate_point(t, car, f32(10.0), out)
    pint("ip none", r)
    pv3("ip none out", out)

    # One point: strike out towards it and stop at `dist`.
    dt_reset(t)
    dt_point(t, 0, 30.0, 40.0, 0.0, 0.0, 1, 1, 1)
    t.P[0][3] = f32(5.0)
    t.NumPoints = 1
    car.State.Position[3] = f32(2.0)
    r = interpolate_point(t, car, f32(10.0), out)
    pint("ip one", r)
    pv3("ip one out", out)
    r = interpolate_point(t, car, f32(100.0), out)
    pint("ip one far", r)
    pv3("ip one far out", out)
    car.State.Position[3] = ZERO

    # The z lane, which every other one-point case leaves flat.
    timer(301)
    dt_reset(t)
    dt_point(t, 0, 30.0, 40.0, 24.0, 0.0, 1, 1, 1)
    t.NumPoints = 1
    r = interpolate_point(t, car, f32(10.0), out)
    pint("ip one z", r)
    pv3("ip one z out", out)

    # `dist` exactly on the first point. The walk test is strict, so the
    # loop is not entered and the answer is the -1 of the first leg rather
    # than the 0 of the second.
    timer(302)
    dt_straight(t)
    r = interpolate_point(t, car, f32(10.0), out)
    pint("ip walk eq", r)
    pv3("ip walk eq out", out)

    # `dist` inside the last leg, so the break lands on the last point
    # itself. Lerping that segment and extrapolating back along it give the
    # same place; only the returned index says which arm ran.
    timer(303)
    dt_straight(t)
    r = interpolate_point(t, car, f32(45.0), out)
    pint("ip tail eq", r)
    pv3("ip tail eq out", out)

    for i in range(5):
        timer(310 + i)
        dt_straight(t)
        car_set(car, 0.0, 0.0, 20.0, 0.0, 0.0, 0.0, 0, 20.0, 20.0)
        r = interpolate_point(t, car, dists[i], out)
        pint("ip straight", r)
        pv3("ip straight out", out)

    for i in range(5):
        timer(320 + i)
        dt_corner(t)
        car_set(car, 0.0, 0.0, 15.0, 2.0, 0.0, 0.0, 0, 15.0, 15.13275)
        r = interpolate_point(t, car, dists[i], out)
        pint("ip corner", r)
        pv3("ip corner out", out)

    # Starting from the middle, so `first` is not zero.
    timer(330)
    dt_straight(t)
    car_set(car, 22.0, 0.0, 20.0, 0.0, 0.0, 0.0, 0, 20.0, 20.0)
    r = interpolate_point(t, car, f32(5.0), out)
    pint("ip mid", r)
    pv3("ip mid out", out)
    pint("ip mid pick", t.Pick)


def s_clear():
    t = DriveTarget()
    car = Car()

    routes_init()
    timer(400)

    # Empty: Length is zeroed and the null Car is never touched.
    dt_reset(t)
    t.Length = f32(77.0)
    t.BlendT = 3
    t.CalcT = 4
    clear(t, None, f32(12.0))
    pdt("cl empty", t, 1)

    # A speed inside the epsilon, and a negative one, both empty the list.
    dt_straight(t)
    car_set(car, 0.0, 0.0, 20.0, 0.0, 0.0, 0.0, 0, 20.0, 20.0)
    clear(t, car, f32(0.001))
    pdt("cl eps", t, 1)

    dt_straight(t)
    clear(t, car, f32(-5.0))
    pdt("cl neg", t, 1)

    # Just outside the epsilon is a real clear.
    timer(401)
    dt_straight(t)
    clear(t, car, f32(0.00101))
    pdt("cl just", t, 2)

    # Everything behind the car: the list is emptied.
    timer(402)
    dt_straight(t)
    car_set(car, 100.0, 0.0, 20.0, 0.0, 0.0, 0.0, 0, 20.0, 20.0)
    clear(t, car, f32(25.0))
    pdt("cl behind", t, 1)

    # The ordinary case: keep the path up to 25 metres ahead.
    timer(403)
    dt_straight(t)
    car_set(car, 0.0, 0.0, 20.0, 0.0, 0.0, 0.0, 0, 20.0, 20.0)
    clear(t, car, f32(25.0))
    pdt("cl keep", t, 5)

    # A short keep that lands on the first leg.
    timer(404)
    dt_straight(t)
    clear(t, car, f32(5.0))
    pdt("cl collapse", t, 2)

    # A keep longer than the path extrapolates.
    timer(405)
    dt_straight(t)
    clear(t, car, f32(200.0))
    pdt("cl past", t, 6)

    # Starting behind the first two points, so the shift runs first.
    timer(406)
    dt_straight(t)
    car_set(car, 25.0, 0.0, 20.0, 0.0, 0.0, 0.0, 0, 20.0, 20.0)
    clear(t, car, f32(15.0))
    pdt("cl shifted", t, 4)

    # A point exactly abeam: the dot against the raw velocity is zero and
    # the test is strict, so the walk steps over it.
    timer(408)
    dt_reset(t)
    dt_point(t, 0, 0.0, 10.0, 0.0, 20.0, 3, 11, 1)
    dt_point(t, 1, 20.0, 0.0, 0.0, 21.0, 3, 12, 1)
    dt_point(t, 2, 30.0, 0.0, 0.0, 22.0, 3, 13, 1)
    dt_point(t, 3, 40.0, 0.0, 0.0, 23.0, 3, 14, 2)
    t.NumPoints = 4
    recalculate_length(t)
    car_set(car, 0.0, 0.0, 20.0, 0.0, 0.0, 0.0, 0, 20.0, 20.0)
    clear(t, car, f32(15.0))
    pdt("cl abeam", t, 4)

    # A switchback at the point the truncation lands on. The truncating
    # AddPointToTarget is the unchecked one, so the doubling-back point
    # goes in; the checked overload would refuse it.
    timer(409)
    dt_reset(t)
    dt_point(t, 0, 10.0, 0.0, 0.0, 20.0, 3, 11, 1)
    dt_point(t, 1, 20.0, 0.0, 0.0, 21.0, 3, 12, 1)
    dt_point(t, 2, 10.0, 10.0, 0.0, 22.0, 3, 13, 1)
    dt_point(t, 3, 0.0, 20.0, 0.0, 23.0, 3, 14, 2)
    t.NumPoints = 4
    recalculate_length(t)
    clear(t, car, f32(25.0))
    pdt("cl switchback", t, 4)

    # The collapse arm reads its route data out of the slot GetFirstPoint
    # chose, and that is not always slot zero: the first point here is
    # inside the minimum distance, so the cone test steps past it while
    # Clear's own velocity walk does not.
    timer(410)
    dt_reset(t)
    dt_point(t, 0, 2.0, 0.0, 0.0, 20.0, 3, 11, 1)
    dt_point(t, 1, 20.0, 5.0, 0.0, 21.0, 4, 12, 2)
    dt_point(t, 2, 30.0, 10.0, 0.0, 22.0, 3, 13, 1)
    dt_point(t, 3, 40.0, 15.0, 0.0, 23.0, 3, 14, 2)
    t.NumPoints = 4
    recalculate_length(t)
    clear(t, car, f32(15.0))
    pdt("cl collapse pick", t, 2)

    # The corner, where the leg lengths differ.
    timer(407)
    dt_corner(t)
    car_set(car, 0.0, 0.0, 15.0, 2.0, 0.0, 0.0, 0, 15.0, 15.13275)
    clear(t, car, f32(20.0))
    pdt("cl corner", t, 5)


def s_resample():
    t = DriveTarget()
    car = Car()

    car_set(car, 0.0, 0.0, 20.0, 0.0, 0.0, 0.0, 0, 20.0, 20.0)

    # Fewer than three points is refused.
    dt_corner(t)
    t.NumPoints = 2
    resample(t, car)
    pdt("rs two", t, 3)

    dt_corner(t)
    t.NumPoints = 3
    resample(t, car)
    pdt("rs three", t, 4)

    dt_corner(t)
    resample(t, car)
    pdt("rs corner", t, 6)

    dt_straight(t)
    resample(t, car)
    pdt("rs straight", t, 6)

    # Unevenly spaced: one very long leg among short ones is where the
    # segment-skipping inner loop has to run more than once.
    dt_reset(t)
    dt_point(t, 0, 0.0, 0.0, 0.0, 1.0, 1, 1, 1)
    dt_point(t, 1, 1.0, 0.0, 0.0, 1.0, 1, 2, 1)
    dt_point(t, 2, 2.0, 0.0, 0.0, 1.0, 1, 3, 1)
    dt_point(t, 3, 62.0, 0.0, 0.0, 1.0, 1, 4, 1)
    dt_point(t, 4, 63.0, 0.0, 0.0, 1.0, 1, 5, 1)
    dt_point(t, 5, 64.0, 0.0, 0.0, 1.0, 1, 6, 1)
    t.NumPoints = 6
    recalculate_length(t)
    resample(t, car)
    pdt("rs uneven", t, 7)

    # The pads and both stamps carry through: Resample interpolates the
    # fourth lane with the other three and clears the two stamps.
    dt_corner(t)
    dt_dirty_pads(t)
    t.CalcT = 51
    t.BlendT = 52
    resample(t, car)
    pdt("rs pads", t, 6)

    # Integer legs of 10, 20, 10, 15, 20 and 5. The even step is 13 1/3,
    # which lands exactly on a segment end twice, and that is the only
    # place the inner walk's test can tell <= from <.
    dt_reset(t)
    for i, (x, y) in enumerate([(0.0, 0.0), (6.0, -8.0), (22.0, 4.0),
                                (22.0, 14.0), (34.0, 23.0), (50.0, 11.0),
                                (54.0, 8.0)]):
        dt_point(t, i, x, y, 0.0, 1.0, 2, i, 1)
    t.NumPoints = 7
    recalculate_length(t)
    resample(t, car)
    pdt("rs exact", t, 7)

    # The inner walk's <= against <, with nothing else in the way. Three
    # points, legs of exactly 5 m: Length is 10, the step is 5, and the
    # accumulator lands on the end of segment 0 dead on. The real test
    # steps over it and emits point 1 at frac 0; a strict one stays on
    # segment 0 and emits P0 + seg0 at frac 1. Everything after that
    # re-syncs -- the mutant just spends the next pass stepping over the
    # segment it should already have left -- so the whole difference is
    # one slot.
    #
    # That slot only differs where the addition does not undo the
    # subtraction, which is why the pad carries it. 16777218 - 1 is a tie
    # and rounds to 16777216; 1 + 16777216 is the same tie and rounds back
    # to 16777216, two ulps short of the 16777218 the other arm copies
    # straight across. The pad is not in len3, so the geometry stays a
    # plain 3-4-5 ladder and the walk above does not notice it. The pads
    # are written here rather than through dt_point, whose fourth float is
    # the CalculatedSpeed -- it puts 0.0 in every pad.
    dt_reset(t)
    dt_point(t, 0, 0.0, 0.0, 0.0, 1.0, 2, 0, 1)
    dt_point(t, 1, 3.0, 4.0, 0.0, 1.0, 2, 1, 1)
    dt_point(t, 2, 6.0, 8.0, 0.0, 1.0, 2, 2, 1)
    t.P[0][3] = f32(1.0)
    t.P[1][3] = f32(16777218.0)
    t.NumPoints = 3
    recalculate_length(t)
    resample(t, car)
    pdt("rs frac one", t, 3)

    # Twenty points, so the walk uses every slot.
    dt_reset(t)
    for i in range(20):
        dt_point(t, i, float(i) * 3.0, float(i) * float(i) * 0.25, 0.0,
                 1.0, 2, i, 1)
    t.NumPoints = 20
    recalculate_length(t)
    resample(t, car)
    pdt("rs twenty", t, 20)


def s_max_speed():
    car = Car()
    exits = [f32(20.0), f32(5.0), f32(40.0)]

    car_set(car, 0.0, 0.0, 20.0, 0.0, 0.0, 0.0, 0, 20.0, 20.0)
    p0 = [ZERO, ZERO]
    p1 = [f32(20.0), ZERO]
    p2 = [f32(40.0), ZERO]

    # A speed inside the epsilon answers yes without touching pOut.
    r, out = calculate_max_speed(car, p0, p1, p2, f32(20.0), f32(0.0005),
                                 f32(33.0))
    pint("ms slow", r)
    pf("ms slow out", out)

    # A distance inside the epsilon answers yes and pins pOut to the entry
    # speed.
    r, out = calculate_max_speed(car, p0, p1, p2, f32(0.0005), f32(20.0),
                                 f32(33.0))
    pint("ms short", r)
    pf("ms short out", out)

    # Straight ahead: no lateral acceleration at all.
    for i in range(3):
        r, out = calculate_max_speed(car, p0, p1, p2, f32(20.0), f32(20.0),
                                     exits[i])
        pint("ms straight", r)
        pf("ms straight out", out)

    # A gentle corner fits; a hard one at speed does not.
    p2 = [f32(36.0), f32(8.0)]
    r, out = calculate_max_speed(car, p0, p1, p2, f32(20.0), f32(20.0),
                                 f32(20.0))
    pint("ms gentle", r)

    p2 = [f32(22.0), f32(20.0)]
    r, out = calculate_max_speed(car, p0, p1, p2, f32(20.0), f32(40.0),
                                 f32(40.0))
    pint("ms hard", r)

    # A right-angle turn taken slowly enough to stay inside the grip.
    r, out = calculate_max_speed(car, p0, p1, p2, f32(20.0), f32(3.0),
                                 f32(3.0))
    pint("ms slowturn", r)

    # Coincident points, so both normalises take their zero arm.
    p1 = list(p0)
    p2 = list(p0)
    r, out = calculate_max_speed(car, p0, p1, p2, f32(20.0), f32(20.0),
                                 f32(20.0))
    pint("ms same", r)
    pf("ms same out", out)

    # The entry-speed epsilon is 0.001 and the test is inclusive, so a car
    # crawling at exactly that answers yes without looking at the corner.
    # At 0.01 the same doubling-back corner has to be answered, and is
    # refused.
    p0 = [ZERO, ZERO]
    p1 = [f32(20.0), ZERO]
    p2 = [ZERO, f32(2.0)]
    r, out = calculate_max_speed(car, p0, p1, p2, f32(0.25),
                                 f32(0.00100000005), f32(20.0))
    pint("ms eps speed", r)
    r, out = calculate_max_speed(car, p0, p1, p2, f32(0.25), f32(0.01),
                                 f32(20.0))
    pint("ms eps between", r)

    # Distance goes through fabsf and is then divided by unchanged, so a
    # negative one makes a negative time -- which the second fabsf catches
    # and a bare comparison would not.
    p2 = [f32(22.0), f32(20.0)]
    r, out = calculate_max_speed(car, p0, p1, p2, f32(-20.0), f32(20.0),
                                 f32(30.0))
    pint("ms neg dist", r)
    pf("ms neg dist out", out)

    # A pure speed change along a straight line: all of the acceleration is
    # parallel to v1, so the lateral part is zero however hard the braking.
    p2 = [f32(40.0), ZERO]
    r, out = calculate_max_speed(car, p0, p1, p2, f32(1.0), f32(20.0),
                                 f32(1.0))
    pint("ms brake hard", r)

    # One corner, two exit speeds one ulp apart, both landing the lateral
    # demand on the last float inside the margin -- 30.000999 against a
    # limit of 30 and a margin of 0.001. The answer is yes on both, and it
    # stops being yes if the reciprocal is divided by rather than
    # multiplied, if v1 is scaled by the exit speed instead of the entry
    # speed, or if the margin is dropped.
    p1 = [f32(9.125), f32(17.3125)]
    p2 = [f32(-24.375), f32(-28.3125)]
    r, out = calculate_max_speed(car, p0, p1, p2, f32(33.625), f32(26.5625),
                                 f32(104.335945))
    pint("ms grip edge", r)
    r, out = calculate_max_speed(car, p0, p1, p2, f32(33.625), f32(26.5625),
                                 f32(104.335953))
    pint("ms grip edge up", r)


def s_estimate_score():
    t = DriveTarget()
    car = Car()

    routes_init()
    timer(500)

    dt_reset(t)
    car_set(car, 0.0, 0.0, 20.0, 0.0, 0.0, 0.0, 0, 20.0, 20.0)
    pf("es none", estimate_score(t, car))

    timer(501)
    dt_reset(t)
    dt_point(t, 0, 30.0, 40.0, 0.0, 9.0, 1, 1, 1)
    t.NumPoints = 1
    pf("es one", estimate_score(t, car))
    pdt("es one after", t, 2)

    timer(502)
    dt_straight(t)
    pf("es straight", estimate_score(t, car))
    pdt("es straight after", t, 5)

    timer(503)
    dt_corner(t)
    car_set(car, 0.0, 0.0, 15.0, 2.0, 0.0, 0.0, 0, 15.0, 15.13275)
    pf("es corner", estimate_score(t, car))
    pdt("es corner after", t, 5)

    # Fast into the same corner: the lateral demand goes past the grip.
    timer(504)
    dt_corner(t)
    car_set(car, 0.0, 0.0, 60.0, 8.0, 0.0, 0.0, 0, 60.0, 60.5310)
    pf("es corner fast", estimate_score(t, car))

    # Twenty points of gentle sweep, so both nested walks run.
    timer(505)
    dt_reset(t)
    for i in range(20):
        dt_point(t, i, float(i) * 6.0, float(i) * float(i) * 0.5, 0.0,
                 0.0, 2, i, 1)
    t.NumPoints = 20
    recalculate_length(t)
    car_set(car, 0.0, 0.0, 25.0, 0.0, 0.0, 0.0, 0, 25.0, 25.0)
    pf("es sweep", estimate_score(t, car))
    pdt("es sweep after", t, 20)

    # A crawling car, where CalculateTime's sentinel arm is live.
    timer(506)
    dt_straight(t)
    car_set(car, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0)
    pf("es stopped", estimate_score(t, car))

    # ForwardSpeed and VelocityMagnitude apart, because the one-point arm
    # reads the second and every other fixture passes the same number for
    # both.
    timer(508)
    dt_reset(t)
    dt_point(t, 0, 30.0, 40.0, 0.0, 9.0, 1, 1, 1)
    t.NumPoints = 1
    car_set(car, 0.0, 0.0, 20.0, 0.0, 0.0, 0.0, 0, 7.0, 20.0)
    pf("es one fwd", estimate_score(t, car))
    pdt("es one fwd after", t, 2)

    # Four points sitting on the car. Nothing clears the cone, every leg is
    # zero, and the distance total the score divides by is zero -- which is
    # what the guard on that divide is for.
    timer(509)
    dt_reset(t)
    for i in range(4):
        dt_point(t, i, 0.0, 0.0, 0.0, 0.0, 2, i, 1)
    t.NumPoints = 4
    car_set(car, 0.0, 0.0, 20.0, 0.0, 0.0, 0.0, 0, 20.0, 20.0)
    pf("es coincident", estimate_score(t, car))

    # The first point is 6 m out: far enough to clear the minimum distance
    # -- 4 m, and that test is strict, so a point at exactly 4 m would be
    # stepped over -- and 0.3 s at 20 m/s, inside the first threshold, so
    # the skip-ahead opens. The second point is 8 m out, which is 0.4 s
    # exactly: the second threshold itself, and that test is strict too.
    timer(510)
    dt_reset(t)
    for i, (x, y) in enumerate([(6.0, 0.0), (8.0, 0.0), (12.0, 16.0),
                                (-6.0, 10.0), (-10.0, 30.0)]):
        dt_point(t, i, x, y, 0.0, 0.0, 2, i, 1)
    t.NumPoints = 5
    recalculate_length(t)
    pf("es t2 edge", estimate_score(t, car))

    # Three layouts that reach the second walk with legs it can tell apart:
    # the outer leg is measured from the point before `outer`, the inner
    # one keeps measuring from that same point while `nxt` runs on, and the
    # skip-ahead inside it has to actually run.
    timer(511)
    dt_reset(t)
    for i, (x, y) in enumerate([(6.0, -11.25), (12.0, -14.25), (15.0, -10.75),
                                (26.0, -11.0), (29.5, -15.25),
                                (42.0, -25.5)]):
        dt_point(t, i, x, y, 0.0, 0.0, 2, i, 1)
    t.NumPoints = 6
    recalculate_length(t)
    car_set(car, 0.0, 0.0, 22.25, 0.0, 0.0, 0.0, 0, 22.25, 22.25)
    pf("es p2 base", estimate_score(t, car))

    timer(512)
    dt_reset(t)
    for i, (x, y) in enumerate([(8.0, 12.0), (11.75, 14.25), (22.0, 15.75),
                                (35.0, 6.5), (45.5, 8.0)]):
        dt_point(t, i, x, y, 0.0, 0.0, 2, i, 1)
    t.NumPoints = 5
    recalculate_length(t)
    car_set(car, 0.0, 0.0, 31.75, 0.0, 0.0, 0.0, 0, 31.75, 31.75)
    pf("es p2 inner", estimate_score(t, car))

    timer(513)
    dt_reset(t)
    for i, (x, y) in enumerate([(4.25, -5.25), (16.0, -1.75), (27.75, -5.5),
                                (31.25, -10.5), (42.75, -16.0),
                                (49.0, -18.0)]):
        dt_point(t, i, x, y, 0.0, 0.0, 2, i, 1)
    t.NumPoints = 6
    recalculate_length(t)
    car_set(car, 0.0, 0.0, 21.75, 0.0, 0.0, 0.0, 0, 21.75, 21.75)
    pf("es p2 skip", estimate_score(t, car))
    pdt("es p2 skip after", t, 6)

    # Two points only, which stops before the second walk.
    timer(507)
    dt_straight(t)
    t.NumPoints = 2
    car_set(car, 0.0, 0.0, 20.0, 0.0, 0.0, 0.0, 0, 20.0, 20.0)
    pf("es two", estimate_score(t, car))

    # The same skip-ahead, one notch the other side of the threshold. At
    # 35.5 m/s the first point is 0.145 s out, so the gate opens; the
    # second is 13.87 m, which is 0.391 s -- inside the threshold, so the
    # walk steps over it -- and the third is 15.01 m, or 0.423 s, which
    # stops it. The walk therefore ends on the third point and asks about
    # the corner that follows it, which fits. Halve the threshold and the
    # walk stops one point earlier instead, on a corner that does not.
    timer(514)
    dt_reset(t)
    for i, (x, y) in enumerate([(1.25, -5.0), (6.5, -12.25), (15.0, -0.5),
                                (26.25, 2.5)]):
        dt_point(t, i, x, y, 0.0, 0.0, 2, i, 1)
    t.NumPoints = 4
    recalculate_length(t)
    car_set(car, 0.0, 0.0, 35.5, 0.0, 0.0, 0.0, 0, 35.5, 35.5)
    pf("es t2 mid", estimate_score(t, car))


def s_fill():
    t = DriveTarget()
    car = Car()

    routes_init()
    timer(600)

    # Acceleration past three quarters of the speed -- 16 sideways
    # against 20 forward, whose three quarters is 15 -- so the
    # straight-line predictor takes over and leaves exactly one point.
    dt_straight(t)
    car_set(car, 0.0, 0.0, 20.0, 0.0, 0.0, 16.0, 0, 20.0, 20.0)
    fill_with_current_acceleration(t, car)
    pdt("fi straight", t, 2)

    # Stationary but accelerating, which is past three quarters of no
    # speed at all, so the straight line comes off State.Angle.
    timer(601)
    dt_straight(t)
    car_set(car, 5.0, 6.0, 0.0, 0.0, 0.5, 0.0, 8192, 0.0, 0.0)
    fill_with_current_acceleration(t, car)
    pdt("fi angle", t, 2)

    # A real integration: cornering acceleration of 5.39 at a modest
    # speed of 8, under the bar of 6. The eighteenth step takes the
    # walk past the 20 m look-ahead.
    timer(602)
    dt_straight(t)
    car_set(car, 0.0, 0.0, 8.0, 0.0, 2.0, 5.0, 0, 8.0, 8.0)
    fill_with_current_acceleration(t, car)
    pdt("fi integrate", t, 20)

    # Braking at 2.8 against a speed of 4, under the bar of 3, for long
    # enough to turn the velocity round. The fifteenth step doubles
    # back, the checked AddPointToTarget refuses it, and the dot test
    # ends the walk with fourteen points.
    timer(603)
    dt_straight(t)
    car_set(car, 0.0, 0.0, 4.0, 0.0, -2.8, 0.0, 0, 4.0, 4.0)
    fill_with_current_acceleration(t, car)
    pdt("fi brake", t, 16)

    # Enough acceleration, under the bar, and little enough distance
    # per step that the twenty-point wall is what stops it.
    timer(604)
    dt_straight(t)
    car_set(car, 0.0, 0.0, 5.0, 0.0, 1.0, 3.0, 0, 5.0, 5.0)
    fill_with_current_acceleration(t, car)
    pdt("fi full", t, 20)

    # Three quarters exactly: a speed of 8 against an acceleration of
    # 6. The test is strict, so this integrates, sixteen points to the
    # look-ahead.
    timer(605)
    dt_straight(t)
    car_set(car, 0.0, 0.0, 8.0, 0.0, 6.0, 0.0, 0, 8.0, 8.0)
    fill_with_current_acceleration(t, car)
    pdt("fi ratio", t, 17)

    # Braking across the lane. The forward velocity turns over at the
    # fourteenth step, but the constant sideways drift keeps every leg
    # within a right angle of the one before, so AddPointToTarget
    # takes each point. It is the dot against the car's own velocity,
    # re-read every pass, that ends the walk a step later, with the
    # fifteenth point in.
    timer(606)
    dt_straight(t)
    car_set(car, 0.0, 0.0, 2.5, 0.25, -1.8, 0.0, 0, 2.5, 2.5125)
    fill_with_current_acceleration(t, car)
    pdt("fi turnback", t, 16)

    # Nine steps of a car at 20 m/s gaining 10 m/s^2 cover 22.5 m
    # exactly, and a VelocityMagnitude of 11.25 makes the look-ahead
    # 22.5 m exactly too. The distance test is strict, so the ninth
    # point is the last.
    timer(607)
    dt_straight(t)
    car_set(car, 0.0, 0.0, 20.0, 0.0, 10.0, 0.0, 0, 20.0, 11.25)
    fill_with_current_acceleration(t, car)
    pdt("fi look eq", t, 11)

    # No speed and no acceleration. Nothing is past three quarters of
    # nothing, so this integrates: every step lands on the car, the
    # zero-length legs pass the strict doubling-back test, the dot is
    # 0 and the distance never grows. The wall stops it at twenty.
    timer(608)
    dt_straight(t)
    car_set(car, 5.0, 6.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0)
    fill_with_current_acceleration(t, car)
    pdt("fi still", t, 20)

    # Just past the bar: 6.01 against a speed of 8 is
    # the straight line again.
    timer(609)
    dt_straight(t)
    car_set(car, 0.0, 0.0, 8.0, 0.0, 6.01, 0.0, 0, 8.0, 8.0)
    fill_with_current_acceleration(t, car)
    pdt("fi ratio over", t, 2)


def s_blend():
    t = DriveTarget()
    car = Car()

    routes_init()
    timer(700)

    # A car with a player on it is left alone.
    dt_straight(t)
    car_set(car, 0.0, 0.0, 20.0, 0.0, 1.0, 3.0, 0, 20.0, 20.0)
    car.pPlayer = "player"
    blend_with_current_acceleration(t, car)
    pdt("bl player", t, 3)

    # Once per frame: the second call inside the same tick returns.
    timer(701)
    dt_straight(t)
    car.pPlayer = None
    blend_with_current_acceleration(t, car)
    pdt("bl first", t, 5)
    blend_with_current_acceleration(t, car)
    pdt("bl second", t, 5)

    # Under 1 m/s the stamp is still taken but nothing is blended.
    timer(702)
    dt_straight(t)
    car_set(car, 0.0, 0.0, 0.5, 0.0, 1.0, 3.0, 0, 0.5, 0.5)
    blend_with_current_acceleration(t, car)
    pdt("bl slow", t, 3)

    # A slow car with a long path: the 0.75s window closes first.
    timer(703)
    dt_straight(t)
    car_set(car, 0.0, 0.0, 12.0, 0.0, 2.0, 6.0, 0, 12.0, 12.0)
    blend_with_current_acceleration(t, car)
    pdt("bl window", t, 5)

    # A fast car on the corner: the points run out before the window does.
    timer(704)
    dt_corner(t)
    car_set(car, 0.0, 0.0, 40.0, 5.0, 1.0, -4.0, 0, 40.0, 40.3113)
    blend_with_current_acceleration(t, car)
    pdt("bl fast", t, 5)

    # Starting from the middle, so the first leg is measured from the car
    # and the rest from the previous point.
    timer(705)
    dt_straight(t)
    car_set(car, 22.0, 0.0, 20.0, 0.0, 0.5, 2.0, 0, 20.0, 20.0)
    blend_with_current_acceleration(t, car)
    pdt("bl mid", t, 5)

    # Legs of 5 m and then 2.5 m at 10 m/s: half a second and a quarter,
    # which is the 0.75 s window exactly. The test is strict, so the second
    # point is the last one dragged.
    #
    # The z of 3 is what makes that visible. On the pass that lands on the
    # boundary the blend is 0.75 * 1.33333337, which clamps to 1, so a
    # further pass would leave x and y exactly where they are. SetPoint3
    # writes z as 0 whatever the blend is, though, and Length follows it --
    # so with a z here an inclusive window drags a third point and says so,
    # and without one it drags a third point in silence.
    timer(706)
    dt_reset(t)
    for i, x in enumerate([5.0, 7.5, 10.0, 12.5, 15.0]):
        dt_point(t, i, x, 0.0, 3.0, 0.0, 2, i, 1)
    t.NumPoints = 5
    recalculate_length(t)
    car_set(car, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 0, 10.0, 10.0)
    blend_with_current_acceleration(t, car)
    pdt("bl window eq", t, 5)


def s_dump():
    global CAM_DEFAULT
    t = DriveTarget()
    car = Car()

    routes_init()
    timer(800)

    # Dump prints nothing in the shipped image. What it still does is ask
    # the CarState for its transform, which sets MatrixValid -- the only
    # way to see the guard from outside, and enough to see it.
    dt_straight(t)
    car_set(car, 1.0, 2.0, 20.0, 3.0, 0.0, 0.0, 0, 20.0, 20.24846)
    car.DriverNumber = -1
    dump(t, car, 1)
    pint("du guarded", car.State.MatrixValid)

    # With the camera default off and the driver number matching, it runs.
    CAM_DEFAULT = 0
    dump(t, car, 1)
    pint("du matched", car.State.MatrixValid)

    car.State.MatrixValid = 0
    car.DriverNumber = 7
    dump(t, car, 1)
    pint("du wrongcar", car.State.MatrixValid)

    # No guard at all.
    dump(t, car, 0)
    pint("du unguarded", car.State.MatrixValid)

    # An empty target never reaches the transform.
    car.State.MatrixValid = 0
    dt_reset(t)
    dump(t, car, 0)
    pint("du empty", car.State.MatrixValid)

    # A null car takes the other arm of the loop and touches nothing.
    dt_straight(t)
    dump(t, None, 0)
    pdt("du nocar", t, 1)

    CAM_DEFAULT = 1


def s_frames():
    t = DriveTarget()
    car = Car()

    routes_init()
    dt_straight(t)
    car_set(car, 0.0, 0.0, 18.0, 1.0, 0.75, 2.5, 0, 18.0, 18.02776)

    # Ten ticks of what the AI actually does with one of these.
    for f in range(10):
        timer(900 + f)
        blend_with_current_acceleration(t, car)
        clear(t, car, f32(30.0))
        pf("fr score", estimate_score(t, car))
        pdt("fr", t, 4)

        car.State.Position[0] = fadd(car.State.Position[0], f32(1.8))
        car.State.Position[1] = fadd(car.State.Position[1], f32(0.1))
        car.State.Velocity[0] = fadd(car.State.Velocity[0], f32(0.075))
        car.State.Velocity[1] = fadd(car.State.Velocity[1], f32(0.25))


def s_free():
    """DriveTarget's four free functions, called directly.

    Three are in DriveTarget.obj's call graph and the fourth,
    DrivingLocation::IsClear, is the two instructions the AddPointToTarget
    overloads branch on. Everywhere else they are reached sideways, which
    is how eight mutations to them lived through a pass that every other
    line of the class survived.
    """
    t = DriveTarget()
    car = Car()
    routes_init()

    # IsClear reads pRoute and nothing else.
    loc = DrivingLocation(None, None, 1)
    pint("fn clear 00", 1 if loc.pRoute is None else 0)
    loc.pRoutePoint = 3
    pint("fn clear 01", 1 if loc.pRoute is None else 0)
    loc.pRoute, loc.pRoutePoint = ROUTE_B, None
    pint("fn clear 10", 1 if loc.pRoute is None else 0)
    loc.pRoutePoint = 3
    pint("fn clear 11", 1 if loc.pRoute is None else 0)

    # IsPointAheadOfCar. Straight ahead is a dot of exactly 1.0, which the
    # strict test refuses at a threshold of 1.0.
    car_set(car, 0.0, 0.0, 12.0, 0.0, 0.0, 0.0, 0, 12.0, 12.0)
    p = (f32(5.0), ZERO)
    pint("fn ahead dot1 t1", is_point_ahead_of_car(p, car, ONE))
    pint("fn ahead dot1 t0.9", is_point_ahead_of_car(p, car, f32(0.9)))

    # The delta is normalised too, so distance cannot change the answer.
    near = (f32(3.0), f32(4.0))
    far = (f32(30.0), f32(40.0))
    pint("fn ahead near 0.0", is_point_ahead_of_car(near, car, ZERO))
    pint("fn ahead near 5.0", is_point_ahead_of_car(near, car, f32(5.0)))
    pint("fn ahead far 0.0", is_point_ahead_of_car(far, car, ZERO))
    pint("fn ahead far 5.0", is_point_ahead_of_car(far, car, f32(5.0)))
    pint("fn ahead behind", is_point_ahead_of_car((f32(-3.0), f32(4.0)),
                                                  car, ZERO))

    # CalculateLookAheadDistance reads VelocityMagnitude, not ForwardSpeed.
    car.State.VelocityMagnitude = f32(12.0)
    car.State.ForwardSpeed = f32(40.0)
    pf("fn look 12", calculate_look_ahead_distance(car))
    car.State.VelocityMagnitude = f32(5.0)
    pf("fn look 5", calculate_look_ahead_distance(car))
    car.State.VelocityMagnitude = f32(10.0)
    pf("fn look 10", calculate_look_ahead_distance(car))

    # StraightLinePredict clears first, so five points come back as one.
    # 0x1555 is thirty degrees -- not 0x2000, where a sine/cosine swap
    # would not show.
    dt_straight(t)
    car_set(car, 1.0, 2.0, 0.2, 0.1, 0.0, 0.0, 0x1555, 0.22360680, 0.5)
    straight_line_predict(car, t)
    pdt("fn slp slow", t, 2)

    # Above 1 m/s the velocity is used, all four lanes through the
    # normalise.
    dt_straight(t)
    car_set(car, 1.0, 2.0, 0.9, 1.2, 0.0, 0.0, 0x1555, 1.5, 1.5)
    car.State.Velocity[2] = f32(0.3)
    car.State.Velocity[3] = f32(0.7)
    car.State.Position[2] = f32(4.0)
    car.State.Position[3] = f32(8.0)
    straight_line_predict(car, t)
    pdt("fn slp fast", t, 2)

    # The gate is strict, so exactly 1.0 takes the velocity arm too.
    dt_straight(t)
    car.State.VelocityMagnitude = ONE
    straight_line_predict(car, t)
    pdt("fn slp at1", t, 2)

    # Rolling backwards with the body still pointing forwards: heading and
    # velocity oppose. The AddPointToTarget call is unchecked and carries
    # no car, so the point lands anyway.
    dt_reset(t)
    car_set(car, 0.0, 0.0, -0.2, 0.0, 0.0, 0.0, 0, -0.2, 0.2)
    straight_line_predict(car, t)
    pdt("fn slp reversing", t, 2)


SCENARIOS = [
    ("layout", s_layout),
    ("constants", s_constants),
    ("ctor", s_ctor),
    ("get-angle", s_get_angle),
    ("calculate-time", s_calculate_time),
    ("recalculate-length", s_recalculate_length),
    ("set-point", s_set_point),
    ("shift-right", s_shift_right),
    ("shift-left", s_shift_left),
    ("route-point", s_route_point),
    ("first-point", s_first_point),
    ("add-point", s_add_point),
    ("interpolate", s_interpolate),
    ("clear", s_clear),
    ("resample", s_resample),
    ("max-speed", s_max_speed),
    ("estimate-score", s_estimate_score),
    ("fill", s_fill),
    ("blend", s_blend),
    ("dump", s_dump),
    ("free-functions", s_free),
    ("frames", s_frames),
]


def model():
    global OUT, CAM_DEFAULT, MIN_DIST_SQ
    OUT = []
    CAM_DEFAULT = CAM_DEFAULT_INIT
    MIN_DIST_SQ = ZERO
    timer(0)
    check_pool()
    for _, fn in SCENARIOS:
        fn()
    return OUT


# ------------------------------------------------------------------ driver

# A mutant can turn one of the class's `for (;;)` walks into a loop with
# no exit. One in this list does, and with no deadline here it spun for
# ten minutes of CPU and stalled the whole pass rather than being counted.
# The harness itself runs in well under a second.
HARNESS_TIMEOUT = 60
HARNESS_HUNG = -9999


def run_harness(exe, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe)], stdout=fh, stderr=subprocess.PIPE,
                               text=True, timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        return HARNESS_HUNG
    if r.returncode != 0:
        print("harness exited %d" % r.returncode)
        if r.stderr:
            print(r.stderr[:2000])
    return r.returncode


def diff(a, b, quiet=False):
    d = list(difflib.unified_diff(a, b, "model", "harness", lineterm="", n=1))
    if d and not quiet:
        for ln in d[:80]:
            print(ln)
        if len(d) > 80:
            print("... %d more diff lines" % (len(d) - 80))
    return len([x for x in d if x.startswith(("+", "-"))
                and not x.startswith(("+++", "---"))])


MUTATIONS = [
    # -- the literal pool ----------------------------------------------
    ("k-clear-eps", DC, "#define K_CLEAR_EPS        0.00100000005f",
     "#define K_CLEAR_EPS        0.00200000009f"),
    ("k-ahead-dot", DC, "#define K_AHEAD_DOT        0.342000008f",
     "#define K_AHEAD_DOT        0.5f"),
    ("k-score-t1", DC,
     "#define K_SCORE_T1         0.400000006f    // gp-27712, EstimateScore",
     "#define K_SCORE_T1         0.200000003f    // gp-27712, EstimateScore"),
    ("k-score-t2", DC,
     "#define K_SCORE_T2         0.400000006f    // gp-27708, EstimateScore",
     "#define K_SCORE_T2         0.200000003f    // gp-27708, EstimateScore"),
    ("k-score-t3", DC,
     "#define K_SCORE_T3         0.400000006f    // gp-27704, EstimateScore",
     "#define K_SCORE_T3         0.200000003f    // gp-27704, EstimateScore"),
    ("k-maxspeed-eps", DC, "#define K_MAXSPEED_EPS     0.00100000005f",
     "#define K_MAXSPEED_EPS     0.100000001f"),
    ("k-time-eps", DC, "#define K_TIME_EPS         0.00100000005f",
     "#define K_TIME_EPS         0.00050000002f"),
    ("k-no-time", DC, "#define K_NO_TIME          9999999.0f",
     "#define K_NO_TIME          1000000.0f"),
    ("k-predict-dt", DC, "#define K_PREDICT_DT       0.100000001f",
     "#define K_PREDICT_DT       0.0500000007f"),
    ("k-blend-scale", DC, "#define K_BLEND_SCALE      1.33333337f",
     "#define K_BLEND_SCALE      1.0f"),
    ("k-fast-car", DC, "#define K_FAST_CAR         30.0f",
     "#define K_FAST_CAR         25.0f"),
    ("k-max-lateral", DC, "#define K_MAX_LATERAL      30.0f",
     "#define K_MAX_LATERAL      20.0f"),
    ("k-acc-dominates", DC, "#define K_ACC_DOMINATES    0.75f",
     "#define K_ACC_DOMINATES    0.5f"),
    ("k-blend-window", DC, "#define K_BLEND_WINDOW     0.75f",
     "#define K_BLEND_WINDOW     0.5f"),

    # -- the named globals ---------------------------------------------
    ("g-seconds-three", DC, "float AIDriverSecondsToLookAhead = 2.0f;",
     "float AIDriverSecondsToLookAhead = 3.0f;"),
    ("g-default-ten", DC, "float AIDriverDefaultLookAhead   = 20.0f;",
     "float AIDriverDefaultLookAhead   = 10.0f;"),
    ("g-mindist-five", DC,
     "float DriveTargetMinDistanceToPoint        = 4.0f;",
     "float DriveTargetMinDistanceToPoint        = 5.0f;"),
    ("g-mindistsq-prefilled", DC,
     "float DriveTargetMinDistanceToPointSquared = 0.0f;",
     "float DriveTargetMinDistanceToPointSquared = 16.0f;"),
    ("g-cam-default-off", DC, "int32_t CameraFollowDefaultCar     = 1;",
     "int32_t CameraFollowDefaultCar     = 0;"),
    ("g-cam-instead-zero", DC, "int32_t CameraFollowThisCarInstead = -1;",
     "int32_t CameraFollowThisCarInstead = 0;"),
    ("si-not-squared", DC,
     "    DriveTargetMinDistanceToPointSquared =" + NL
     + "        DriveTargetMinDistanceToPoint * DriveTargetMinDistanceToPoint;",
     "    DriveTargetMinDistanceToPointSquared =" + NL
     + "        DriveTargetMinDistanceToPoint;"),

    # -- the two lengths -----------------------------------------------
    ("ln3-drops-z", DC, "    return sqrtf((x * x + y * y) + z * z);",
     "    return sqrtf(x * x + y * y);"),
    ("ln3-regrouped", DC, "    return sqrtf((x * x + y * y) + z * z);",
     "    return sqrtf(x * x + (y * y + z * z));"),
    ("ln2-adds-nothing", DC, "    return sqrtf(x * x + y * y);",
     "    return sqrtf(x * x);"),
    ("pa-stride-twelve", DC,
     "    return (const bVector3 *)((const char *)t + 16 + i * 16);",
     "    return (const bVector3 *)((const char *)t + 16 + i * 12);"),
    ("pa-base-zero", DC,
     "    return (const bVector3 *)((const char *)t + 16 + i * 16);",
     "    return (const bVector3 *)((const char *)t + i * 16);"),

    # -- the free functions --------------------------------------------
    ("fr-isclear-tests-point", DC, "    return d->pRoute == 0;",
     "    return d->pRoutePoint == 0;"),
    ("fr-ahead-inclusive", DC,
     "    return thresh < (v.x * d.x + v.y * d.y) ? 1 : 0;",
     "    return thresh <= (v.x * d.x + v.y * d.y) ? 1 : 0;"),
    ("fr-ahead-flipped", DC,
     "    return thresh < (v.x * d.x + v.y * d.y) ? 1 : 0;",
     "    return (v.x * d.x + v.y * d.y) < thresh ? 1 : 0;"),
    ("fr-ahead-skips-normalise", DC,
     "    bNormalize2(&v, &v);" + NL + "    bNormalize2(&d, &d);",
     "    bNormalize2(&v, &v);"),
    ("fr-look-uses-forward", DC,
     "    float d = car->State.VelocityMagnitude * AIDriverSecondsToLookAhead;",
     "    float d = car->State.ForwardSpeed * AIDriverSecondsToLookAhead;"),
    ("fr-look-takes-min", DC,
     "    return d < AIDriverDefaultLookAhead ? AIDriverDefaultLookAhead : d;",
     "    return AIDriverDefaultLookAhead < d ? AIDriverDefaultLookAhead : d;"),
    ("fr-slp-speed-gate", DC,
     "    if (car->State.VelocityMagnitude < 1.0f) {",
     "    if (car->State.VelocityMagnitude < 2.0f) {"),
    ("fr-slp-sincos-swapped", DC,
     "        dir.x = c;" + NL + "        dir.y = s;",
     "        dir.x = s;" + NL + "        dir.y = c;"),
    ("fr-slp-keeps-points", DC,
     "    drivetarget_clear(t, 0, 0.0f);" + NL
     + "    drivetarget_add_point3(t, &p, -1, -1, -1, 0, 0);",
     "    drivetarget_add_point3(t, &p, -1, -1, -1, 0, 0);"),
    ("fr-slp-checks", DC,
     "    drivetarget_add_point3(t, &p, -1, -1, -1, 0, 0);" + NL + "}",
     "    drivetarget_add_point3(t, &p, -1, -1, -1, 1, car);" + NL + "}"),

    # -- lifetime ------------------------------------------------------
    ("ct-no-memset", DC, "    memset(t, 0, sizeof(DriveTarget));",
     "    t->NumPoints = 0;"),
    ("ct-no-clear", DC,
     "    drivetarget_clear(t, 0, 0.0f);" + NL + "    return t;",
     "    return t;"),
    ("as-copies-half", DC, "    memcpy(dst, src, sizeof(DriveTarget));",
     "    memcpy(dst, src, sizeof(DriveTarget) / 2);"),
    ("as-returns-src", DC,
     "    memcpy(dst, src, sizeof(DriveTarget));" + NL + "    return dst;",
     "    memcpy(dst, src, sizeof(DriveTarget));" + NL
     + "    return (DriveTarget *)src;"),
    ("cp-is-memcpy", DC,
     "    for (i = 0; i < DRIVETARGET_MAX_POINTS; i++) dst->Points[i] = src->Points[i];",
     "    memcpy(dst, src, sizeof(DriveTarget));"),
    ("cp-drops-ttype", DC,
     "    dst->NumPoints = src->NumPoints;" + NL + "    dst->TType = src->TType;",
     "    dst->NumPoints = src->NumPoints;"),
    ("cp-drops-length", DC, "    dst->Length = src->Length;" + NL
     + "    return dst;", "    return dst;"),
    ("cp-points-nineteen", DC,
     "    for (i = 0; i < DRIVETARGET_MAX_POINTS; i++) dst->Points[i] = src->Points[i];",
     "    for (i = 0; i < DRIVETARGET_MAX_POINTS - 1; i++) dst->Points[i] = src->Points[i];"),
    ("dt-dtor-clears", DC,
     "    // body to port, and the delete belongs to the caller here." + NL
     + "    (void)t;",
     "    // body to port, and the delete belongs to the caller here." + NL
     + "    t->NumPoints = 0;"),

    # -- GetAngle ------------------------------------------------------
    ("ga-clamp-back-up", DC,
     "    if (i <= -1) i = 0;" + NL
     + "    if (t->NumPoints - 2 < i) i = t->NumPoints - 2;",
     "    if (i <= -1) i = 0;" + NL
     + "    if (t->NumPoints - 2 < i) i = t->NumPoints - 2;" + NL
     + "    if (i < 0) i = 0;"),
    ("ga-clamp-order-swapped", DC,
     "    if (i <= -1) i = 0;" + NL
     + "    if (t->NumPoints - 2 < i) i = t->NumPoints - 2;",
     "    if (t->NumPoints - 2 < i) i = t->NumPoints - 2;" + NL
     + "    if (i <= -1) i = 0;"),
    ("ga-clamp-is-zero", DC, "    if (i <= -1) i = 0;", "    if (i < -1) i = 0;"),
    ("ga-top-is-numpoints", DC,
     "    if (t->NumPoints - 2 < i) i = t->NumPoints - 2;",
     "    if (t->NumPoints - 1 < i) i = t->NumPoints - 1;"),
    ("ga-delta-reversed", DC,
     "    dx = b->x - a->x;" + NL + "    dy = b->y - a->y;",
     "    dx = a->x - b->x;" + NL + "    dy = a->y - b->y;"),
    ("ga-atan-args-swapped", DC, "    return bATan(dx, dy);",
     "    return bATan(dy, dx);"),

    # -- CalculateTime -------------------------------------------------
    ("ti-eps-is-or", DC,
     "    if (fabsf(b) <= K_TIME_EPS && fabsf(c) <= K_TIME_EPS) return K_NO_TIME;",
     "    if (fabsf(b) <= K_TIME_EPS || fabsf(c) <= K_TIME_EPS) return K_NO_TIME;"),
    ("ti-eps-strict", DC,
     "    if (fabsf(b) <= K_TIME_EPS && fabsf(c) <= K_TIME_EPS) return K_NO_TIME;",
     "    if (fabsf(b) < K_TIME_EPS && fabsf(c) < K_TIME_EPS) return K_NO_TIME;"),
    ("ti-no-abs", DC,
     "    if (fabsf(b) <= K_TIME_EPS && fabsf(c) <= K_TIME_EPS) return K_NO_TIME;",
     "    if (b <= K_TIME_EPS && c <= K_TIME_EPS) return K_NO_TIME;"),
    ("ti-mean-distributed", DC, "    return a / ((b + c) * 0.5f);",
     "    return a / (b * 0.5f + c * 0.5f);"),
    ("ti-sum-not-halved", DC, "    return a / ((b + c) * 0.5f);",
     "    return a / (b + c);"),
    ("ti-uses-entry-only", DC, "    return a / ((b + c) * 0.5f);",
     "    return a / b;"),

    # -- GetMaxLateralAcceleration -------------------------------------
    ("ml-is-twenty", DC, "    return K_MAX_LATERAL;", "    return 20.0f;"),

    # -- RecalculateLength ---------------------------------------------
    ("rl-no-zero-on-earlyout", DC,
     "    n = t->NumPoints;" + NL + "    t->Length = 0.0f;" + NL
     + "    if (n - 1 <= 0) return;",
     "    n = t->NumPoints;" + NL + "    if (n - 1 <= 0) return;" + NL
     + "    t->Length = 0.0f;"),
    ("rl-one-point-sums", DC, "    if (n - 1 <= 0) return;",
     "    if (n <= 0) return;"),
    ("rl-loop-from-zero", DC, "    for (i = 1; i < n; i++) {",
     "    for (i = 0; i < n; i++) {"),
    ("rl-loop-stops-early", DC, "    for (i = 1; i < n; i++) {",
     "    for (i = 1; i < n - 1; i++) {"),
    ("rl-two-lane", DC,
     "        float d = dt_len3(t->Points[i - 1].x - t->Points[i].x,",
     "        float d = dt_len2(t->Points[i - 1].x - t->Points[i].x,"),
    ("rl-assigns-not-adds", DC, "        t->Length = t->Length + d;",
     "        t->Length = d;"),

    # -- GetRouteAndRoutePoint -----------------------------------------
    ("rp-no-null-out", DC, "    *route = 0;" + NL + "    *pt = 0;",
     "    (void)0;"),
    ("rp-negative-ok", DC, "    if (i < 0) return 0;", "    if (i < -1) return 0;"),
    ("rp-no-upper-bound", DC, "    if (!(i < t->NumPoints)) return 0;",
     "    if (!(i < DRIVETARGET_MAX_POINTS)) return 0;"),
    ("rp-route-zero-refused", DC, "    if (t->Route[i] == -1) return 0;",
     "    if (t->Route[i] <= 0) return 0;"),
    ("rp-no-rpn-test", DC,
     "    if (t->RoutePointNumber[i] == -1) return 0;", "    (void)0;"),
    ("rp-negative-route-indexes", DC,
     "    tr = t->Route[i] < 0 ? 0 : trmgr_get_route(&TheTrackRouteManager, t->Route[i]);",
     "    tr = trmgr_get_route(&TheTrackRouteManager, t->Route[i]);"),
    ("rp-no-manager-test", DC, "    if (tr == 0) return 0;", "    (void)0;"),
    ("rp-point-off-by-one", DC, "    *pt = &tr->TrackRoutePointTable[rn];",
     "    *pt = &tr->TrackRoutePointTable[rn + 1];"),

    # -- GetFirstPoint -------------------------------------------------
    ("fp-no-cache", DC,
     "    if (WorldTimer == t->WhichPointIPickedCalculationTime)" + NL
     + "        return t->WhichPointIPicked;",
     "    if (0)" + NL + "        return t->WhichPointIPicked;"),
    ("fp-empty-sets-stamp", DC,
     "        t->WhichPointIPicked = 0;" + NL
     + "        t->WhichPointIPickedCalculationTime = 0;" + NL
     + "        return t->WhichPointIPicked;",
     "        t->WhichPointIPicked = 0;" + NL
     + "        t->WhichPointIPickedCalculationTime = WorldTimer;" + NL
     + "        return t->WhichPointIPicked;"),
    ("fp-empty-is-negative", DC,
     "    if (n <= 0) {", "    if (n < 0) {"),
    ("fp-fallback-is-zero", DC, "    best = n - 1;", "    best = 0;"),
    ("fp-fast-inclusive", DC,
     "    if (K_FAST_CAR < cs->ForwardSpeed) thresh = 0.0f;",
     "    if (K_FAST_CAR <= cs->ForwardSpeed) thresh = 0.0f;"),
    ("fp-fast-uses-magnitude", DC,
     "    if (K_FAST_CAR < cs->ForwardSpeed) thresh = 0.0f;",
     "    if (K_FAST_CAR < cs->VelocityMagnitude) thresh = 0.0f;"),
    ("fp-no-fast-arm", DC,
     "    if (K_FAST_CAR < cs->ForwardSpeed) thresh = 0.0f;", "    (void)0;"),
    ("fp-vel-not-normalised", DC, "    bNormalize2(&vel, &vel);", "    (void)0;"),
    ("fp-cone-inclusive", DC,
     "        if (thresh < (dn.x * vel.x + dn.y * vel.y)) {",
     "        if (thresh <= (dn.x * vel.x + dn.y * vel.y)) {"),
    ("fp-cone-uses-raw-delta", DC,
     "        if (thresh < (dn.x * vel.x + dn.y * vel.y)) {",
     "        if (thresh < (d.x * vel.x + d.y * vel.y)) {"),
    ("fp-dist-uses-normalised", DC,
     "            if (DriveTargetMinDistanceToPointSquared < (d.x * d.x + d.y * d.y)) {",
     "            if (DriveTargetMinDistanceToPointSquared < (dn.x * dn.x + dn.y * dn.y)) {"),
    ("fp-dist-not-squared", DC,
     "            if (DriveTargetMinDistanceToPointSquared < (d.x * d.x + d.y * d.y)) {",
     "            if (DriveTargetMinDistanceToPoint < (d.x * d.x + d.y * d.y)) {"),
    ("fp-no-dist-test", DC,
     "            if (DriveTargetMinDistanceToPointSquared < (d.x * d.x + d.y * d.y)) {",
     "            if (1) {"),
    ("fp-stamp-not-written", DC,
     "    t->WhichPointIPickedCalculationTime = WorldTimer;" + NL
     + "    return t->WhichPointIPicked;",
     "    return t->WhichPointIPicked;"),

    # -- SetPoint ------------------------------------------------------
    ("sp-negative-accepted", DC, "    if (i < 0) return;" + NL
     + "    if (!(i < t->NumPoints)) return;" + NL + NL
     + "    t->Points[i] = *p;",
     "    if (!(i < t->NumPoints)) return;" + NL + NL + "    t->Points[i] = *p;"),
    ("sp-bound-is-array", DC,
     "    if (!(i < t->NumPoints)) return;" + NL + NL + "    t->Points[i] = *p;",
     "    if (!(i < DRIVETARGET_MAX_POINTS)) return;" + NL + NL
     + "    t->Points[i] = *p;"),
    ("sp-no-stamp-clear", DC,
     "    t->WhichPointIPickedCalculationTime = 0;" + NL
     + "    drivetarget_recalculate_length(t);",
     "    drivetarget_recalculate_length(t);"),
    ("sp-no-recalc", DC,
     "    t->WhichPointIPickedCalculationTime = 0;" + NL
     + "    drivetarget_recalculate_length(t);",
     "    t->WhichPointIPickedCalculationTime = 0;"),
    ("sp-narrow-keeps-z", DC,
     "    v.x = p->x;" + NL + "    v.y = p->y;" + NL + "    v.z = 0.0f;" + NL
     + "    v.pad = 0.0f;   // STACK-W" + NL
     + "    drivetarget_set_point3(t, i, &v, route, rpn, dl, speed);",
     "    v.x = p->x;" + NL + "    v.y = p->y;" + NL + "    v.z = 1.0f;" + NL
     + "    v.pad = 0.0f;   // STACK-W" + NL
     + "    drivetarget_set_point3(t, i, &v, route, rpn, dl, speed);"),

    # -- ShiftRight ----------------------------------------------------
    ("sr-twenty-allowed", DC,
     "    if (!(n < DRIVETARGET_MAX_POINTS)) return;" + NL + NL
     + "    for (i = t->NumPoints - n - 1; i >= 0; i--) {",
     "    if (!(n <= DRIVETARGET_MAX_POINTS)) return;" + NL + NL
     + "    for (i = t->NumPoints - n - 1; i >= 0; i--) {"),
    ("sr-copy-upwards", DC, "    for (i = t->NumPoints - n - 1; i >= 0; i--) {",
     "    for (i = 0; i <= t->NumPoints - n - 1; i++) {"),
    ("sr-copy-off-by-one", DC,
     "    for (i = t->NumPoints - n - 1; i >= 0; i--) {",
     "    for (i = t->NumPoints - n - 2; i >= 0; i--) {"),
    ("sr-copies-no-route", DC, "        t->Route[d] = t->Route[i];", "        (void)0;"),
    ("sr-copies-no-speed", DC,
     "        t->CalculatedSpeed[d] = t->CalculatedSpeed[i];", "        (void)0;"),
    ("sr-clamp-at-twenty", DC, "    if (!((int8_t)m < 21)) t->NumPoints = DRIVETARGET_MAX_POINTS;",
     "    if (!((int8_t)m < 20)) t->NumPoints = DRIVETARGET_MAX_POINTS;"),
    ("sr-no-clamp", DC,
     "    if (!((int8_t)m < 21)) t->NumPoints = DRIVETARGET_MAX_POINTS;",
     "    (void)0;"),
    ("sr-count-signed", DC, "    m = (uint8_t)t->NumPoints + n;",
     "    m = t->NumPoints + n;"),
    ("sr-blank-includes-route", DC,
     "            t->RoutePointNumber[i] = -1;" + NL
     + "            t->CalculatedSpeed[i] = 0.0f;",
     "            t->RoutePointNumber[i] = -1;" + NL
     + "            t->Route[i] = -1;" + NL
     + "            t->CalculatedSpeed[i] = 0.0f;"),
    ("sr-blank-includes-pad", DC,
     "            t->Points[i].z = 0.0f;" + NL + "            t->Points[i].x = 0.0f;",
     "            t->Points[i].z = 0.0f;" + NL + "            t->Points[i].pad = 0.0f;" + NL
     + "            t->Points[i].x = 0.0f;"),
    ("sr-blank-rpn-zero", DC, "            t->RoutePointNumber[i] = -1;",
     "            t->RoutePointNumber[i] = 0;"),
    ("sr-no-blank", DC, "    if (n > 0) {" + NL
     + "        for (i = 0; i < n; i++) {", "    if (0) {" + NL
     + "        for (i = 0; i < n; i++) {"),
    ("sr-no-stamp-clear", DC,
     "    t->WhichPointIPickedTime = 0;" + NL
     + "    t->WhichPointIPickedCalculationTime = 0;" + NL + "}" + NL + NL
     + "void drivetarget_shift_left",
     "    t->WhichPointIPickedCalculationTime = 0;" + NL + "}" + NL + NL
     + "void drivetarget_shift_left"),

    # -- ShiftLeft -----------------------------------------------------
    ("sl-n-equal-allowed", DC,
     "    if (!(n < t->NumPoints)) return;" + NL + NL
     + "    m = (uint8_t)t->NumPoints;",
     "    if (!(n <= t->NumPoints)) return;" + NL + NL
     + "    m = (uint8_t)t->NumPoints;"),
    ("sl-source-off-by-one", DC, "            int s = i + n;",
     "            int s = i + n + 1;"),
    ("sl-loop-one-more", DC, "        for (i = 0; i < t->NumPoints - n; i++) {",
     "        for (i = 0; i <= t->NumPoints - n; i++) {"),
    ("sl-drops-dline", DC, "            t->DrivingLine[i] = t->DrivingLine[s];",
     "            (void)0;"),
    ("sl-count-not-reduced", DC, "    t->NumPoints = (int8_t)(m - n);",
     "    t->NumPoints = (int8_t)m;"),
    ("sl-recalc-always", DC, "    if (recalc) drivetarget_recalculate_length(t);",
     "    drivetarget_recalculate_length(t);"),
    ("sl-recalc-never", DC, "    if (recalc) drivetarget_recalculate_length(t);",
     "    (void)recalc;"),
    ("sl-no-stamp-clear", DC,
     "    t->WhichPointIPickedCalculationTime = 0;" + NL
     + "    t->NumPoints = (int8_t)(m - n);",
     "    t->NumPoints = (int8_t)(m - n);"),

    # -- AddPointToTarget ----------------------------------------------
    ("ap-wall-at-nineteen", DC,
     "    if (!(n < DRIVETARGET_MAX_POINTS)) return;" + NL + NL
     + "    if (check) {",
     "    if (!(n < DRIVETARGET_MAX_POINTS - 1)) return;" + NL + NL
     + "    if (check) {"),
    ("ap-no-wall", DC,
     "    if (!(n < DRIVETARGET_MAX_POINTS)) return;" + NL + NL
     + "    if (check) {", "    if (0) return;" + NL + NL + "    if (check) {"),
    ("ap-car-arm-at-one", DC, "        if (n < 2) {", "        if (n < 1) {"),
    ("ap-nocar-refuses", DC,
     "            if (car != 0) ok = ai_is_point_ahead_of_car((const bVector2 *)p, car, 0.0f);",
     "            ok = car != 0 ? ai_is_point_ahead_of_car((const bVector2 *)p, car, 0.0f) : 0;"),
    ("ap-car-thresh-nonzero", DC,
     "            if (car != 0) ok = ai_is_point_ahead_of_car((const bVector2 *)p, car, 0.0f);",
     "            if (car != 0) ok = ai_is_point_ahead_of_car((const bVector2 *)p, car, 0.5f);"),
    ("ap-doubleback-inclusive", DC,
     "            if ((ax * bx + ay * by) + az * bz < 0.0f) ok = 0;",
     "            if ((ax * bx + ay * by) + az * bz <= 0.0f) ok = 0;"),
    ("ap-doubleback-two-lane", DC,
     "            if ((ax * bx + ay * by) + az * bz < 0.0f) ok = 0;",
     "            if ((ax * bx + ay * by) < 0.0f) ok = 0;"),
    ("ap-doubleback-flipped", DC,
     "            if ((ax * bx + ay * by) + az * bz < 0.0f) ok = 0;",
     "            if (0.0f < (ax * bx + ay * by) + az * bz) ok = 0;"),
    ("ap-leg-from-wrong-pair", DC,
     "            float ax = t->Points[n - 1].x - t->Points[n - 2].x;",
     "            float ax = t->Points[n - 2].x - t->Points[n - 1].x;"),
    ("ap-speed-not-zeroed", DC,
     "    t->CalculatedSpeed[t->NumPoints] = 0.0f;", "    (void)0;"),
    ("ap-length-not-grown", DC,
     "    if (t->NumPoints > 0) {" + NL + "        int k = t->NumPoints;",
     "    if (0) {" + NL + "        int k = t->NumPoints;"),
    ("ap-length-from-zero", DC, "    if (t->NumPoints > 0) {",
     "    if (t->NumPoints >= 0) {"),
    ("ap-count-not-advanced", DC,
     "    t->NumPoints = (int8_t)((uint8_t)t->NumPoints + 1);", "    (void)0;"),
    ("ap-no-blend-clear", DC,
     "    t->WhichPointIPickedCalculationTime = 0;" + NL
     + "    t->WhichPointIPickedTime = 0;" + NL
     + "    t->CalculatedSpeed[t->NumPoints] = 0.0f;",
     "    t->WhichPointIPickedCalculationTime = 0;" + NL
     + "    t->CalculatedSpeed[t->NumPoints] = 0.0f;"),
    ("ap-narrow-keeps-z", DC,
     "    v.x = p->x;" + NL + "    v.y = p->y;" + NL + "    v.z = 0.0f;" + NL
     + "    v.pad = 0.0f;   // STACK-W" + NL
     + "    drivetarget_add_point3(t, &v, route, rpn, dl, check, car);",
     "    v.x = p->x;" + NL + "    v.y = p->y;" + NL + "    v.z = 2.0f;" + NL
     + "    v.pad = 0.0f;   // STACK-W" + NL
     + "    drivetarget_add_point3(t, &v, route, rpn, dl, check, car);"),
    ("ap-dl-clear-accepted", DC,
     "    if (drivinglocation_is_clear(loc)) return;" + NL + NL
     + "    route = drivinglocation_is_clear(loc) ? -1 : (int8_t)loc->pRoute->RouteNumber;",
     "    if (0) return;" + NL + NL
     + "    route = drivinglocation_is_clear(loc) ? -1 : (int8_t)loc->pRoute->RouteNumber;"),
    ("ap-dl-rpn-off-by-one", DC,
     "        rpn = (int16_t)(loc->pRoutePoint - loc->pRoute->TrackRoutePointTable);",
     "        rpn = (int16_t)(loc->pRoutePoint - loc->pRoute->TrackRoutePointTable) + 1;"),
    ("ap-dl-line-negated", DC, "    dl = loc->DrivingLine;",
     "    dl = (int8_t)-loc->DrivingLine;"),
    ("ap-dl2-keeps-z", DC,
     "    v.z = 0.0f;" + NL + "    v.y = p->y;" + NL + "    v.x = p->x;",
     "    v.z = 3.0f;" + NL + "    v.y = p->y;" + NL + "    v.x = p->x;"),
]

MUTATIONS += [
    # -- InterpolatePoint ----------------------------------------------
    ("ip-empty-returns-zero", DC,
     "    if (n == 0) return -1;   // `out` is not written on this arm",
     "    if (n == 0) return 0;   // `out` is not written on this arm"),
    ("ip-one-point-two-lane", DC,
     "        d.z = t->Points[0].z - car->State.Position.z;" + NL
     + "        d.pad = t->Points[0].pad - car->State.Position.pad;",
     "        d.z = 0.0f;" + NL
     + "        d.pad = t->Points[0].pad - car->State.Position.pad;"),
    ("ip-one-point-no-pad", DC,
     "        d.pad = t->Points[0].pad - car->State.Position.pad;",
     "        d.pad = 0.0f;"),
    ("ip-one-normalise-to-one", DC, "        bNormalize3To(&d, &d, dist);",
     "        bNormalize3To(&d, &d, 1.0f);"),
    ("ip-one-returns-minus", DC,
     "        out->pad = car->State.Position.pad + d.pad;" + NL
     + "        return 0;",
     "        out->pad = car->State.Position.pad + d.pad;" + NL
     + "        return -1;"),
    ("ip-first-is-zero", DC,
     "    first = drivetarget_get_first_point(t, &car->State);" + NL
     + "    i = first;", "    first = 0;" + NL + "    i = first;"),
    ("ip-cum-two-lane", DC,
     "    cum[i] = dt_len3(t->Points[i].x - car->State.Position.x,",
     "    cum[i] = dt_len2(t->Points[i].x - car->State.Position.x,"),
    ("ip-walk-inclusive", DC, "    if (cum[i] < dist) {",
     "    if (cum[i] <= dist) {"),
    ("ip-walk-from-first", DC,
     "        for (i = first + 1; i < t->NumPoints; i++) {",
     "        for (i = first; i < t->NumPoints; i++) {"),
    ("ip-cum-not-cumulative", DC, "            cum[i] = seg + cum[i - 1];",
     "            cum[i] = seg;"),
    ("ip-break-strict", DC, "            if (dist <= cum[i]) break;",
     "            if (dist < cum[i]) break;"),
    ("ip-tail-inclusive", DC,
     "    last = t->NumPoints - 1;" + NL + "    if (last < i) {",
     "    last = t->NumPoints - 1;" + NL + "    if (last <= i) {"),
    ("ip-tail-full-dist", DC,
     "        bNormalize3To(&d, &d, dist - cum[last]);",
     "        bNormalize3To(&d, &d, dist);"),
    ("ip-tail-returns-i", DC,
     "        out->pad = t->Points[last].pad + d.pad;" + NL
     + "        return last;",
     "        out->pad = t->Points[last].pad + d.pad;" + NL + "        return i;"),
    ("ip-base-always-car", DC,
     "        if (first < i) {" + NL + "            prev = cum[i - 1];",
     "        if (0) {" + NL + "            prev = cum[i - 1];"),
    ("ip-base-inclusive", DC, "        if (first < i) {" + NL
     + "            prev = cum[i - 1];",
     "        if (first <= i) {" + NL + "            prev = cum[i - 1];"),
    ("ip-lerp-denominator", DC, "        s = (dist - prev) / (cum[i] - prev);",
     "        s = (dist - prev) / cum[i];"),
    ("ip-lerp-numerator", DC, "        s = (dist - prev) / (cum[i] - prev);",
     "        s = dist / (cum[i] - prev);"),
    ("ip-ret-is-i", DC, "            ret = i - 1;", "            ret = i;"),

    # -- Clear ---------------------------------------------------------
    ("cl-empty-keeps-length", DC,
     "    if (n == 0) {" + NL + "        t->Length = 0.0f;",
     "    if (n == 0) {" + NL + "        t->Length = t->Length;"),
    ("cl-eps-strict", DC,
     "    if (fabsf(speed) <= K_CLEAR_EPS || speed < 0.0f) {",
     "    if (fabsf(speed) < K_CLEAR_EPS || speed < 0.0f) {"),
    ("cl-negative-kept", DC,
     "    if (fabsf(speed) <= K_CLEAR_EPS || speed < 0.0f) {",
     "    if (fabsf(speed) <= K_CLEAR_EPS) {"),
    ("cl-eps-no-abs", DC,
     "    if (fabsf(speed) <= K_CLEAR_EPS || speed < 0.0f) {",
     "    if (speed <= K_CLEAR_EPS || speed < 0.0f) {"),
    ("cl-ahead-inclusive", DC,
     "        if (0.0f < (car->State.Velocity.x * dx + car->State.Velocity.y * dy))",
     "        if (0.0f <= (car->State.Velocity.x * dx + car->State.Velocity.y * dy))"),
    ("cl-ahead-uses-accel", DC,
     "        if (0.0f < (car->State.Velocity.x * dx + car->State.Velocity.y * dy))",
     "        if (0.0f < (car->State.Acceleration.x * dx + car->State.Acceleration.y * dy))"),
    ("cl-no-shift", DC, "    if (i > 0) drivetarget_shift_left(t, i, 0);",
     "    (void)0;"),
    ("cl-shift-recalcs", DC, "    if (i > 0) drivetarget_shift_left(t, i, 0);",
     "    if (i > 0) drivetarget_shift_left(t, i, 1);"),
    ("cl-truncate-inclusive", DC, "    if (r < t->NumPoints - 1) {",
     "    if (r <= t->NumPoints - 1) {"),
    ("cl-truncate-off-by-one", DC, "            t->NumPoints = (int8_t)(r + 1);",
     "            t->NumPoints = (int8_t)r;"),
    ("cl-truncate-checks", DC,
     "            drivetarget_add_point3(t, &p, t->Route[r], t->RoutePointNumber[r]," + NL
     + "                                   t->DrivingLine[r], 0, 0);",
     "            drivetarget_add_point3(t, &p, t->Route[r], t->RoutePointNumber[r]," + NL
     + "                                   t->DrivingLine[r], 1, 0);"),
    ("cl-truncate-no-recalc", DC,
     "                                   t->DrivingLine[r], 0, 0);" + NL
     + "            drivetarget_recalculate_length(t);",
     "                                   t->DrivingLine[r], 0, 0);"),
    ("cl-collapse-uses-zero", DC,
     "        int f = drivetarget_get_first_point(t, &car->State);", "        int f = 0;"),
    ("cl-collapse-reads-after", DC,
     "        int8_t route = t->Route[f];" + NL
     + "        int16_t rpn = t->RoutePointNumber[f];" + NL
     + "        int8_t dl = t->DrivingLine[f];" + NL + NL
     + "        t->NumPoints = 0;" + NL
     + "        drivetarget_add_point3(t, &p, route, rpn, dl, 0, 0);",
     "        t->NumPoints = 0;" + NL
     + "        drivetarget_add_point3(t, &p, t->Route[f], t->RoutePointNumber[f]," + NL
     + "                               t->DrivingLine[f], 0, 0);"),

    # -- Resample ------------------------------------------------------
    ("rs-two-points-allowed", DC, "    if (t->NumPoints < 3) return;",
     "    if (t->NumPoints < 2) return;"),
    ("rs-seg-loop-full", DC, "    for (k = 0; k < n - 1; k++) {",
     "    for (k = 0; k < n; k++) {"),
    ("rs-last-seg-not-copied", DC,
     "    seg[n - 1] = seg[n - 2];" + NL + "    len[n - 1] = len[n - 2];",
     "    len[n - 1] = len[n - 2];"),
    ("rs-step-over-n", DC, "    step = t->Length / (float)(n - 1);",
     "    step = t->Length / (float)n;"),
    ("rs-frac-over-step", DC, "        frac = travelled / len[k];",
     "        frac = travelled / step;"),
    ("rs-emit-uses-next-point", DC,
     "        out[j].x = t->Points[k].x + seg[k].x * frac;",
     "        out[j].x = t->Points[k + 1].x + seg[k].x * frac;"),
    ("rs-emit-no-pad", DC,
     "        out[j].pad = t->Points[k].pad + seg[k].pad * frac;",
     "        out[j].pad = 0.0f;"),
    ("rs-travel-not-advanced", DC, "        travelled = travelled + step;",
     "        travelled = step;"),
    ("rs-outer-test-strict", DC,
     "        if (!(emitted <= t->Length)) break;" + NL
     + "        if (!(k < n)) goto done_keep;",
     "        if (!(emitted < t->Length)) break;" + NL
     + "        if (!(k < n)) goto done_keep;"),
    ("rs-inner-test-strict", DC, "        if (len[k] <= travelled) {",
     "        if (len[k] < travelled) {"),
    ("rs-inner-no-subtract", DC, "                travelled = travelled - len[k];",
     "                (void)0;"),
    ("rs-length-is-path", DC, "    t->Length = next;", "    t->Length = emitted;"),
    ("rs-copy-count", DC,
     "    memcpy(&t->Points[0], out, (size_t)((int8_t)raw * 16));",
     "    memcpy(&t->Points[0], out, (size_t)(((int8_t)raw - 1) * 16));"),
    ("rs-no-stamp-clear", DC,
     "    t->WhichPointIPickedTime = 0;" + NL
     + "    t->WhichPointIPickedCalculationTime = 0;" + NL + "}" + NL + NL
     + "// -------------------------------------------------------------- the scoring",
     "    t->WhichPointIPickedCalculationTime = 0;" + NL + "}" + NL + NL
     + "// -------------------------------------------------------------- the scoring"),

    # -- CalculateMaxSpeed ---------------------------------------------
    ("ms-slow-writes-out", DC,
     "    if (fabsf(speed) <= K_MAXSPEED_EPS) return 1;",
     "    if (fabsf(speed) <= K_MAXSPEED_EPS) { *pOut = speed; return 1; }"),
    ("ms-slow-strict", DC, "    if (fabsf(speed) <= K_MAXSPEED_EPS) return 1;",
     "    if (fabsf(speed) < K_MAXSPEED_EPS) return 1;"),
    ("ms-short-no-write", DC,
     "    if (fabsf(dist) <= K_MAXSPEED_EPS) {" + NL + "        *pOut = speed;",
     "    if (fabsf(dist) <= K_MAXSPEED_EPS) {" + NL + "        (void)speed;"),
    ("ms-v1-scaled-by-out", DC, "    bNormalize2To(&v1, &v1, speed);",
     "    bNormalize2To(&v1, &v1, *pOut);"),
    ("ms-v2-scaled-by-speed", DC, "    bNormalize2To(&v2, &v2, *pOut);",
     "    bNormalize2To(&v2, &v2, speed);"),
    ("ms-dv-reversed", DC,
     "    dv.x = v2.x - v1.x;" + NL + "    dv.y = v2.y - v1.y;",
     "    dv.x = v1.x - v2.x;" + NL + "    dv.y = v1.y - v2.y;"),
    ("ms-time-args-swapped", DC,
     "    time = drivetarget_calculate_time(t, dist, speed, *pOut);",
     "    time = drivetarget_calculate_time(t, dist, *pOut, speed);"),
    ("ms-time-eps-no-abs", DC, "    if (fabsf(time) <= K_MAXSPEED_EPS) {",
     "    if (time <= K_MAXSPEED_EPS) {"),
    ("ms-divides-twice", DC,
     "    inv = 1.0f / time;" + NL + "    acc.y = dv.y * inv;" + NL
     + "    acc.x = dv.x * inv;",
     "    inv = 1.0f / time;" + NL + "    acc.y = dv.y / time;" + NL
     + "    acc.x = dv.x / time;"),
    ("ms-projection-no-divide", DC,
     "    k = (v1.x * acc.x + v1.y * acc.y) / (v1.x * v1.x + v1.y * v1.y);",
     "    k = (v1.x * acc.x + v1.y * acc.y);"),
    ("ms-perp-is-par", DC,
     "    perp.y = acc.y - par.y;" + NL + "    perp.x = acc.x - par.x;",
     "    perp.y = par.y;" + NL + "    perp.x = par.x;"),
    ("ms-mag-uses-par", DC, "    mag = dt_len2(perp.x, perp.y);",
     "    mag = dt_len2(par.x, par.y);"),
    ("ms-grip-inclusive", DC, "    if (mag < grip) return 1;",
     "    if (mag <= grip) return 1;"),
    ("ms-grip-flipped", DC, "    if (mag < grip) return 1;",
     "    if (grip < mag) return 1;"),
    ("ms-no-margin", DC,
     "    if (fabsf(mag - grip) <= K_MAXSPEED_EPS) return 1;" + NL
     + "    return 0;", "    return 0;"),

    # -- EstimateScore -------------------------------------------------
    ("es-empty-returns-zero", DC,
     "    if (t->NumPoints == 0) return -1.0f;", "    if (t->NumPoints == 0) return 0.0f;"),
    ("es-one-uses-forward", DC,
     "        t->CalculatedSpeed[0] = cs->VelocityMagnitude;",
     "        t->CalculatedSpeed[0] = cs->ForwardSpeed;"),
    ("es-one-dist-reversed", DC,
     "        dx = car->State.Position.x - t->Points[0].x;",
     "        dx = t->Points[0].x - car->State.Position.x;"),
    ("es-one-no-bail", DC, "        dist[0] = dt_len2(dx, dy);" + NL
     + "        bail = 1;", "        dist[0] = dt_len2(dx, dy);"),
    ("es-fill-from-zero", DC, "        for (i = first;;) {", "        for (i = 0;;) {"),
    ("es-fill-base-inclusive", DC,
     "            if (first < i) {" + NL
     + "                dx = t->Points[i].x - t->Points[i - 1].x;",
     "            if (first <= i) {" + NL
     + "                dx = t->Points[i].x - t->Points[i - 1].x;"),
    ("es-fill-always-car", DC,
     "            if (first < i) {" + NL
     + "                dx = t->Points[i].x - t->Points[i - 1].x;" + NL
     + "                dy = t->Points[i].y - t->Points[i - 1].y;" + NL
     + "            } else {",
     "            if (0) {" + NL
     + "                dx = t->Points[i].x - t->Points[i - 1].x;" + NL
     + "                dy = t->Points[i].y - t->Points[i - 1].y;" + NL
     + "            } else {"),
    ("es-fill-three-lane", DC, "            dist[i] = dt_len2(dx, dy);",
     "            dist[i] = dt_len3(dx, dy, 0.0f);"),
    ("es-pass1-threshold-t3", DC,
     "    if (drivetarget_calculate_time(t, leg, cs->VelocityMagnitude," + NL
     + "                                   t->CalculatedSpeed[first]) < K_SCORE_T1) {",
     "    if (drivetarget_calculate_time(t, leg, cs->VelocityMagnitude," + NL
     + "                                   t->CalculatedSpeed[first]) < K_SCORE_T3 * 0.5f) {"),
    ("es-pass1-leg-from-prev", DC,
     "                float dx = car->State.Position.x - t->Points[cur].x;",
     "                float dx = t->Points[cur - 1].x - t->Points[cur].x;"),
    ("es-pass1-inclusive", DC,
     "                if (!(drivetarget_calculate_time(t, leg, cs->VelocityMagnitude," + NL
     + "                                                 t->CalculatedSpeed[cur])" + NL
     + "                      < K_SCORE_T2))",
     "                if (!(drivetarget_calculate_time(t, leg, cs->VelocityMagnitude," + NL
     + "                                                 t->CalculatedSpeed[cur])" + NL
     + "                      <= K_SCORE_T2))"),
    ("es-nxt-is-cur", DC, "    nxt = cur + 1;" + NL
     + "    if (nxt < t->NumPoints) {", "    nxt = cur;" + NL
     + "    if (nxt < t->NumPoints) {"),
    ("es-maxspeed-not-consulted", DC,
     "        maxSpeedOK = drivetarget_calculate_max_speed(" + NL
     + "            t, car, (const bVector2 *)&car->State.Position,",
     "        maxSpeedOK = 1; (void)drivetarget_calculate_max_speed(" + NL
     + "            t, car, (const bVector2 *)&car->State.Position,"),
    ("es-maxspeed-failure-ignored", DC,
     "    if (maxSpeedOK == 0) {" + NL + "        ok = 0;" + NL
     + "        bail = 1;" + NL + "    }" + NL + "    if (bail) goto final;" + NL + NL
     + "    cur = nxt;",
     "    if (maxSpeedOK == 0) {" + NL + "        bail = 1;" + NL + "    }" + NL
     + "    if (bail) goto final;" + NL + NL + "    cur = nxt;"),
    ("es-pass2-outer-base", DC,
     "        leg = dt_len2(t->Points[outer - 1].x - t->Points[outer].x,",
     "        leg = dt_len2(t->Points[outer].x - t->Points[outer + 1].x,"),
    ("es-pass2-inner-follows", DC,
     "                    leg = dt_len2(t->Points[outer - 1].x - t->Points[nxt].x,",
     "                    leg = dt_len2(t->Points[nxt - 1].x - t->Points[nxt].x,"),
    ("es-pass2-no-skip", DC,
     "        if (drivetarget_calculate_time(t, leg, t->CalculatedSpeed[outer - 1]," + NL
     + "                                       t->CalculatedSpeed[outer]) < K_SCORE_T3) {",
     "        if (0) {"),
    ("es-pass2-cur-not-advanced", DC,
     "                leg, t->CalculatedSpeed[outer - 1], &t->CalculatedSpeed[cur]);" + NL
     + "            cur = nxt;",
     "                leg, t->CalculatedSpeed[outer - 1], &t->CalculatedSpeed[cur]);"),
    ("es-pass2-no-bail-at-end", DC,
     "        } else {" + NL + "            bail = 1;" + NL + "        }",
     "        } else {" + NL + "            (void)0;" + NL + "        }"),
    ("es-total-excludes-first", DC, "    total = dist[first];",
     "    total = 0.0f;"),
    ("es-trapezoid-not-halved", DC,
     "    acc = (dist[first] * 0.5f) * (t->CalculatedSpeed[first] + cs->VelocityMagnitude);",
     "    acc = dist[first] * (t->CalculatedSpeed[first] + cs->VelocityMagnitude);"),
    ("es-trapezoid-one-sided", DC,
     "    acc = (dist[first] * 0.5f) * (t->CalculatedSpeed[first] + cs->VelocityMagnitude);",
     "    acc = (dist[first] * 0.5f) * (t->CalculatedSpeed[first] + t->CalculatedSpeed[first]);"),
    ("es-sum-from-zero", DC,
     "    for (i = first + 1; i < t->NumPoints; i++) {" + NL
     + "        total = total + dist[i];",
     "    for (i = 1; i < t->NumPoints; i++) {" + NL
     + "        total = total + dist[i];"),
    ("es-sum-pairs-shifted", DC,
     "        acc = acc + (dist[i] * 0.5f)" + NL
     + "                    * (t->CalculatedSpeed[i] + t->CalculatedSpeed[i - 1]);",
     "        acc = acc + (dist[i] * 0.5f)" + NL
     + "                    * (t->CalculatedSpeed[i] + t->CalculatedSpeed[i]);"),
    ("es-total-inclusive", DC, "    if (0.0f < total) return acc / total;",
     "    if (0.0f <= total) return acc / total;"),
    ("es-no-score", DC, "    if (0.0f < total) return acc / total;" + NL
     + "    return -1.0f;", "    return acc;"),

    # -- FillWithCurrentAcceleration -----------------------------------
    ("fi-no-clear", DC,
     "    drivetarget_clear(t, 0, 0.0f);" + NL
     + "    look = ai_calculate_look_ahead_distance(car);",
     "    look = ai_calculate_look_ahead_distance(car);"),
    # The first is the bug the port shipped with, and this model agreed
    # with it; see fill_with_current_acceleration.
    ("fi-dominates-flipped", DC,
     "    if (dt_len2(vel.x, vel.y) * K_ACC_DOMINATES < dt_len2(acc.x, acc.y)) {",
     "    if (!(dt_len2(vel.x, vel.y) * K_ACC_DOMINATES < dt_len2(acc.x, acc.y))) {"),
    ("fi-dominates-inclusive", DC,
     "    if (dt_len2(vel.x, vel.y) * K_ACC_DOMINATES < dt_len2(acc.x, acc.y)) {",
     "    if (dt_len2(vel.x, vel.y) * K_ACC_DOMINATES <= dt_len2(acc.x, acc.y)) {"),
    ("fi-dominates-scales-acc", DC,
     "    if (dt_len2(vel.x, vel.y) * K_ACC_DOMINATES < dt_len2(acc.x, acc.y)) {",
     "    if (dt_len2(vel.x, vel.y) < dt_len2(acc.x, acc.y) * K_ACC_DOMINATES) {"),
    ("fi-look-gate-inclusive", DC, "    if (!(0.0f < look)) return;",
     "    if (!(0.0f <= look)) return;"),
    ("fi-step-order-swapped", DC,
     "        bScaleAdd2(&newVel, &vel, &acc, K_PREDICT_DT);" + NL
     + "        bScaleAdd2(&newPos, &pos, &newVel, K_PREDICT_DT);",
     "        bScaleAdd2(&newPos, &pos, &vel, K_PREDICT_DT);" + NL
     + "        bScaleAdd2(&newVel, &vel, &acc, K_PREDICT_DT);"),
    ("fi-adds-unchecked", DC,
     "        drivetarget_add_point2(t, &newPos, -1, -1, -1, 1, 0);",
     "        drivetarget_add_point2(t, &newPos, -1, -1, -1, 0, 0);"),
    ("fi-travel-from-origin", DC,
     "        travelled = travelled + dt_len2(pos.x - newPos.x, pos.y - newPos.y);",
     "        travelled = dt_len2(pos.x - newPos.x, pos.y - newPos.y);"),
    ("fi-dot-against-running", DC,
     "            float dot = newVel.x * car->State.Velocity.x" + NL
     + "                        + newVel.y * car->State.Velocity.y;",
     "            float dot = newVel.x * vel.x" + NL + "                        + newVel.y * vel.y;"),
    ("fi-dot-inclusive", DC, "            if (dot < 0.0f) return;",
     "            if (dot <= 0.0f) return;"),
    ("fi-distance-inclusive", DC, "        if (!(travelled < look)) return;",
     "        if (!(travelled <= look)) return;"),
    ("fi-no-wall", DC,
     "        if (!(t->NumPoints < DRIVETARGET_MAX_POINTS)) return;" + NL
     + "    }" + NL + "}",
     "    }" + NL + "}"),

    # -- BlendWithCurrentAcceleration ----------------------------------
    ("bl-no-frame-gate", DC,
     "    if (t->WhichPointIPickedTime == WorldTimer) return;", "    (void)0;"),
    ("bl-player-blended", DC,
     "    if (car->pPlayer != 0) return;   // a human's target is left alone",
     "    (void)0;   // a human's target is left alone"),
    ("bl-stamp-before-player", DC,
     "    if (car->pPlayer != 0) return;   // a human's target is left alone" + NL
     + "    t->WhichPointIPickedTime = WorldTimer;",
     "    t->WhichPointIPickedTime = WorldTimer;" + NL
     + "    if (car->pPlayer != 0) return;"),
    ("bl-slow-gate", DC, "    if (velMag < 1.0f) return;",
     "    if (velMag < 0.25f) return;"),
    ("bl-slow-before-pick", DC,
     "    i = drivetarget_get_first_point(t, &car->State);" + NL
     + "    if (velMag < 1.0f) return;",
     "    if (velMag < 1.0f) return;" + NL
     + "    i = drivetarget_get_first_point(t, &car->State);"),
    ("bl-leg-always-from-car", DC,
     "        if (i == t->WhichPointIPicked) {",
     "        if (1) {"),
    ("bl-leg-never-from-car", DC, "        if (i == t->WhichPointIPicked) {",
     "        if (0) {"),
    ("bl-dt-uses-forward", DC, "        dt = dt_len2(dx, dy) / velMag;",
     "        dt = dt_len2(dx, dy) / car->State.ForwardSpeed;"),
    ("bl-blend-not-scaled", DC, "        blend = accTime * K_BLEND_SCALE;",
     "        blend = accTime;"),
    ("bl-blend-not-clamped", DC,
     "        if (1.0f < blend) blend = 1.0f;", "        (void)0;"),
    ("bl-blend-inverted", DC, "        inv = 1.0f - blend;",
     "        inv = blend; blend = 1.0f - inv;"),
    ("bl-blend-weights-swapped", DC,
     "        blended.x = t->Points[i].x * blend + newPos.x * inv;" + NL
     + "        blended.y = t->Points[i].y * blend + newPos.y * inv;",
     "        blended.x = t->Points[i].x * inv + newPos.x * blend;" + NL
     + "        blended.y = t->Points[i].y * inv + newPos.y * blend;"),
    ("bl-writes-speed", DC,
     "            drivetarget_set_point3(t, i, &blended, route, rpn, dl, 0.0f);",
     "            drivetarget_set_point3(t, i, &blended, route, rpn, dl, 1.0f);"),
    ("bl-route-read-after", DC,
     "            int8_t route = t->Route[i];" + NL
     + "            int16_t rpn = t->RoutePointNumber[i];" + NL
     + "            int8_t dl = t->DrivingLine[i];",
     "            int8_t route = t->Route[i];" + NL
     + "            int16_t rpn = (int16_t)(t->RoutePointNumber[i] + 1);" + NL
     + "            int8_t dl = t->DrivingLine[i];"),
    ("bl-window-inclusive", DC,
     "        if (!(accTime < K_BLEND_WINDOW)) return;",
     "        if (!(accTime <= K_BLEND_WINDOW)) return;"),

    # -- Dump ----------------------------------------------------------
    ("du-guard-inverted", DC,
     "        if (CameraFollowDefaultCar != 0) return;",
     "        if (CameraFollowDefaultCar == 0) return;"),
    ("du-no-car-test", DC,
     "        if (car->DriverNumber != CameraFollowThisCarInstead) return;",
     "        (void)0;"),
    ("du-ignores-flag", DC, "    if (checkCamera) {",
     "    if (0) {"),
    ("du-transform-on-null", DC, "        if (car == 0) {",
     "        if (car != 0 && 0) {"),
    ("du-loop-runs-once", DC,
     "    for (i = 0; i < t->NumPoints; i++) {" + NL + "        if (car == 0) {",
     "    for (i = 0; i < 1; i++) {" + NL + "        if (car == 0) {"),

    # -- the header ----------------------------------------------------
    ("h-max-points-nineteen", DH, "#define DRIVETARGET_MAX_POINTS 20",
     "#define DRIVETARGET_MAX_POINTS 19"),
    ("h-points-not-aligned", DH,
     "    uint8_t  _pad0[15];                        //   1  (Points is 16-aligned)",
     "    uint8_t  _pad0[11];                        //   1  (Points is 16-aligned)"),
    ("h-route-is-int16", DH,
     "    int8_t   Route[DRIVETARGET_MAX_POINTS];            // 416",
     "    int16_t  Route[DRIVETARGET_MAX_POINTS];            // 416"),
    ("h-rpn-is-int8", DH,
     "    int16_t  RoutePointNumber[DRIVETARGET_MAX_POINTS]; // 436",
     "    int8_t   RoutePointNumber[DRIVETARGET_MAX_POINTS]; // 436"),
    ("h-pick-is-int32", DH,
     "    int8_t   WhichPointIPicked;                // 500",
     "    int32_t  WhichPointIPicked;                // 500"),
    ("h-numpoints-unsigned", DH, "    int8_t   NumPoints;                        //   0",
     "    uint8_t  NumPoints;                        //   0"),
    ("h-tail-pad-short", DH, "    uint8_t  _pad2[12];                        // 516",
     "    uint8_t  _pad2[8];                         // 516"),

    # The stand-in Car these two used to mutate is gone. They now aim at
    # the real record in car.h, which is what drivetarget.h includes, so
    # the three offsets DriveTarget reads stay under test -- and against
    # the header the game is actually built from.
    ("h-car-state-at-sixty", CARH,
     "    uint8_t           _hole56[8];               // 56   to align State",
     "    uint8_t           _hole56[12];              // 56   to align State"),
    ("h-car-player-moved", CARH,
     "    Player           *pPlayer;                  // 24",
     "    uint8_t           _extra[8];                // 24" + NL +
     "    Player           *pPlayer;                  // 32"),
]

# Mutations that change the source without changing what it computes. Each
# one is an argument, not an excuse: a mutant lives here only when the two
# versions can be shown to agree on every input, not when no fixture happened
# to reach it.
EQUIVALENT = {
    # -- the record ----------------------------------------------------
    "ct-no-clear":
        "The copy constructor memsets the destination and then calls Clear "
        "on it. Clear's own first act on a record with NumPoints == 0 is to "
        "zero Length and the two stamps, and the memset has already zeroed "
        "all three. There is no byte Clear can reach that the memset left "
        "alone, so dropping the call cannot change a byte.",
    "ti-mean-distributed":
        "CalculateTime divides by (b + c) * 0.5f. Scaling by a half is exact "
        "in binary -- it only decrements the exponent -- so (b + c) * 0.5f "
        "and b * 0.5f + c * 0.5f round identically for every finite pair, "
        "and the quotient is the same float.",
    "rl-one-point-sums":
        "RecalculateLength returns early when NumPoints - 1 <= 0, and the "
        "loop it guards runs from 1 to NumPoints. Those are the same "
        "condition: the guard fires exactly when the loop body would not "
        "execute, so removing the guard changes only how many instructions "
        "run to reach the same zero.",
    "sr-clamp-at-twenty":
        "ShiftRight clamps the shift with `if (n > 20) n = 20;` and the "
        "mutant with `>=`. The two arms differ only at n == 20, where one "
        "stores the 20 it already holds and the other leaves it alone -- the "
        "same number either way.",
    "sr-count-signed":
        "The count is read as int8_t and the mutant reads it as uint8_t. The "
        "two differ by exactly 256 for a negative NumPoints, and every use "
        "of the value downstream is either a comparison against a positive "
        "bound that both fail or a store back through (int8_t), which "
        "discards the difference again.",
    "rp-negative-route-indexes":
        "GetRouteAndRoutePoint hands a negative Route straight to "
        "TrackRouteManager::GetRoute. The image indexes its table with it "
        "and reads whatever is in front of the array; the port's "
        "trmgr_get_route bounds the index and answers null. This mutation "
        "removes a bound the image does not have, and it survives because "
        "the port already refuses negatives -- which is the documented "
        "divergence, not a hole in the transcript.",
    "g-mindistsq-prefilled":
        "DriveTargetMinDistanceToPointSquared has no bytes in the file: it "
        "lives in .sbss and the static initialiser at 0x0020ab48 computes "
        "4.0f * 4.0f into it. That product is exact, so writing 16.0f into "
        "the definition gives the same float. What the static initialiser "
        "buys is that the value is computed rather than assumed, which the "
        "`k mindistsq` line states either way.",

    # -- CalculateMaxSpeed ---------------------------------------------
    "ms-dv-reversed":
        "dv is used for nothing but acc = dv * inv, and acc for nothing but "
        "k = (v1 . acc) / |v1|^2, par = v1 * k and perp = acc - par. "
        "Negating dv negates acc exactly (a sign flip is exact), hence k, "
        "hence par, hence perp; and perp reaches the answer only through "
        "sqrt(px*px + py*py), where the squares put the sign back. The "
        "magnitude is bit-identical.",
    "ms-time-args-swapped":
        "CalculateTime is symmetric in its last two arguments: the guard is "
        "`fabsf(b) <= eps && fabsf(c) <= eps` and the divisor is (b + c) * "
        "0.5f. IEEE addition is commutative, so swapping the entry and exit "
        "speeds gives the same float.",
    "ms-grip-inclusive":
        "`mag < grip` and `mag <= grip` can only disagree at mag == grip, "
        "and the very next line answers that case the same way: "
        "fabsf(mag - grip) is then zero, which is inside the margin, so both "
        "versions return 1.",

    # -- EstimateScore -------------------------------------------------
    "es-one-dist-reversed":
        "The one-point arm's dx reaches the record only through "
        "dt_len2(dx, dy), which squares it. Reversing the subtraction "
        "negates dx exactly and the square puts it back.",
    "es-one-no-bail":
        "With NumPoints == 1 the flag guards three things, and none of them "
        "can write a different number. The fill loop writes "
        "CalculatedSpeed[first] = VelocityMagnitude, which the one-point arm "
        "has already written, and dist[first] with the subtraction reversed "
        "-- squared again, so the same length. Pass one's inner walk and "
        "both CalculateMaxSpeed calls are gated on an index being less than "
        "NumPoints, which one point cannot satisfy. The score is read off "
        "dist[first] and CalculatedSpeed[first] either way.",
    "es-fill-three-lane":
        "dt_len3(dx, dy, 0.0f) computes sqrtf((dx*dx + dy*dy) + 0.0f*0.0f). "
        "The two-lane sum is a sum of squares and so is never negative zero, "
        "and adding positive zero to it is the identity. Same argument to "
        "the same sqrt.",
    "es-pass2-no-bail-at-end":
        "The flag that arm sets is read two lines later by `if (bail) "
        "break;`, and the loop's own tail breaks on the same condition. That "
        "arm is reached when nxt >= NumPoints, and on every path into it "
        "cur is either nxt - 1 (the inner walk sets cur = nxt and then steps "
        "nxt past it) or nxt - 1 by construction (`nxt = cur + 1` closes "
        "each outer pass). So cur + 1 >= NumPoints, and the tail test "
        "`if (!(nxt < NumPoints)) break;` leaves by the same door.",
    "es-trapezoid-one-sided":
        "CalculatedSpeed[first] is VelocityMagnitude on every path that "
        "reaches the sum. The fill loop writes it on its first iteration, "
        "and the one-point arm writes it before that; the only later writes "
        "are CalculateMaxSpeed's two `*pOut = speed` arms, and the speed it "
        "is handed for the first point is VelocityMagnitude itself. The two "
        "ends of the first trapezoid are the same float, so adding either "
        "one twice is the same sum.",
    "es-sum-pairs-shifted":
        "Same reason, one point further along. CalculateMaxSpeed never "
        "writes anything to CalculatedSpeed but the entry speed it was "
        "given, and in the second walk that entry speed is "
        "CalculatedSpeed[outer - 1]. By induction from the fill loop every "
        "entry from `first` up is VelocityMagnitude, so "
        "CalculatedSpeed[i] + CalculatedSpeed[i - 1] and "
        "CalculatedSpeed[i] + CalculatedSpeed[i] add the same two floats. "
        "The array the method is named for never holds anything the car was "
        "not already doing.",

    # -- Clear ----------------------------------------------------------
    "cl-eps-no-abs":
        "The test is `fabsf(speed) <= eps || speed < 0.0f`. The second "
        "clause already covers every negative speed, so the first only has "
        "to decide the range [0, eps] -- where speed and fabsf(speed) are "
        "the same number. `speed <= eps || speed < 0.0f` is the same "
        "predicate written without the call.",
    "cl-collapse-reads-after":
        "The collapse arm loads Route[f], RoutePointNumber[f] and "
        "DrivingLine[f] before storing zero into NumPoints, which is what "
        "the listing does. Zeroing NumPoints does not write to any of those "
        "three arrays, and AddPointToTarget reads the arguments the caller "
        "has already evaluated, so reading them after the store yields the "
        "same three values. The order is faithful to the image rather than "
        "load-bearing.",

    # -- FillWithCurrentAcceleration ------------------------------------
    "fi-look-gate-inclusive":
        "`!(0.0f < look)` and `!(0.0f <= look)` differ only at look == 0, "
        "and CalculateLookAheadDistance cannot return it: it answers "
        "max(VelocityMagnitude * AIDriverSecondsToLookAhead, "
        "AIDriverDefaultLookAhead), and the default in the image is 20.0f. "
        "No CarState drives that gate to zero.",
}


# A name here that no mutation uses would be an argument for something that
# is not being tested. Catch the typo at import rather than in the tally.
_unknown = sorted(set(EQUIVALENT) - set(m[0] for m in MUTATIONS))
assert not _unknown, "EQUIVALENT names no mutation uses: %s" % _unknown


# The write, its OneDrive retry, and the journal that lets a killed pass be
# recovered from are all hostbuild's.
write_source = hostbuild.write_source


def mutate_pass(only=None):
    """`only` is a set of mutation names; the rest are skipped. The full
    pass is half an hour, and re-testing the handful a new fixture was
    written for should not be."""
    base_model = model()
    survived, missing, caught = [], [], 0
    equivalent_survivors = []

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="drivetarget_test")
        out = Path(tmp) / "base.txt"
        run_harness(exe, out)
        if diff(base_model, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for name, rel, before, after in MUTATIONS:
        if only is not None and name not in only:
            continue
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")

        # The ported sources are CRLF and the tools are LF, so a multi-line
        # pattern written with bare newlines misses every time against a
        # source file -- silently, as a pattern that is not found rather
        # than as a mutant that survived.
        crlf = (chr(13) + NL) in text
        probe = before.replace(NL, chr(13) + NL) if crlf else before
        repl = after.replace(NL, chr(13) + NL) if crlf else after

        if probe not in text:
            missing.append(name)
            print("  %-34s PATTERN NOT FOUND" % name)
            continue
        try:
            write_source(path, text.replace(probe, repl, 1))
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = hostbuild.build(tmp, SOURCES,
                                          name="drivetarget_test")
                except SystemExit:
                    print("  %-34s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, out)
                if rc == HARNESS_HUNG:
                    print("  %-34s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-34s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base_model, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-34s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    equivalent_survivors.append(name)
                    print("  %-34s survived, equivalent by construction"
                          % name)
                else:
                    print("  %-34s SURVIVED" % name)
                    survived.append(name)
        finally:
            try:
                write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))

    real = [m for m in MUTATIONS
            if m[0] not in missing and (only is None or m[0] in only)]
    holes = [s for s in survived if s not in EQUIVALENT]
    equiv = [name for name, _, _, _ in MUTATIONS
             if name in EQUIVALENT and name in equivalent_survivors]
    # A pattern that is not found is dropped from the denominator above, so
    # without this the tally line reads clean while a mutation never ran.
    if missing:
        print("%d PATTERN NOT FOUND -- the tally below is over %d of them"
              % (len(missing), len(real)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equiv), len(holes)))
    # Named again here so the tail of a long run is enough to act on.
    for name in holes:
        print("  unexplained: %s" % name)
    return 1 if (holes or missing) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAMES",
                    help="comma-separated mutation names to run alone")
    ap.add_argument("--dump", metavar="DIR")
    args = ap.parse_args()

    if args.mutate:
        only = set(args.only.split(",")) if args.only else None
        if only:
            known = set(m[0] for m in MUTATIONS)
            unknown = sorted(only - known)
            if unknown:
                print("no such mutation: %s" % ", ".join(unknown))
                sys.exit(2)
        sys.exit(mutate_pass(only))

    lines = model()
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="drivetarget_test")
        out = Path(tmp) / "harness.txt"
        run_harness(exe, out)
        harness = out.read_text().splitlines()

        if args.dump:
            d = Path(args.dump)
            d.mkdir(parents=True, exist_ok=True)
            (d / "model.txt").write_text(NL.join(lines) + NL)
            (d / "harness.txt").write_text(NL.join(harness) + NL)
            print("wrote %s" % d)

    n = diff(lines, harness)
    print("%d scenarios, %d lines, %d differ" % (len(SCENARIOS), len(lines), n))
    sys.exit(1 if n else 0)


if __name__ == "__main__":
    main()
