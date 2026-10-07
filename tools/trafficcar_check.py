"""Cross-check 3DS Files/source/trafficcar.c against the retail image's own
code.

TrafficCar is the mover of a traffic car: retail's TrafficCar.obj,
0x00167a08 to 0x00168098. The oracle is SLES_507.31 itself, run in
tools/mipsemu.py:

- the constructor (0x00167a08), the destructor (0x00168088) and Move
  (0x00167af8), both reached through the table at 0x002b2190,
  CalculateStopDistance (0x00167fb8) and the start-up code
  (_GLOBAL_$I$TrafficAccelerationTable, 0x00167fe0) that builds the three
  Tables;
- run as shipped under them: Table's constructor and GetValue, bSin,
  bScaleAdd (bVector2) and bNormalize (bVector3).

Stood in on both sides, each call logged: Car::GetSteering (the driver's
Steering, as the image's two instructions read it), Car::PutFlatOnTrack
(which moves the car along x and up by scripted steps, so the velocity is
seen to come from the position after it), CarState::SetWheelTouchingGround,
SetWheelTerrain, CalculateWheelMatrices and CalculateGeometryPosition,
Car::ComputeFakeRPM and ~CarMover.

Two words Move stores come from its own stack, which it never writes: the
car's new Position's fourth (sp+60) and AngularVelocity's fourth (sp+140).
The port keeps the old Position's and writes 0; the model puts those in the
two stack words before each Move, so the rest of the comparison holds them
to it.

    python tools/trafficcar_check.py
    python tools/trafficcar_check.py --mutate [--only a,b] [--jobs N]
    python tools/trafficcar_check.py --dump PREFIX
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

HARNESS = "tools/src/trafficcar_test.c"
TCC = "3DS Files/source/trafficcar.c"
TCH = "3DS Files/source/trafficcar.h"
SOURCES = [HARNESS, TCC,
           "3DS Files/source/table.c",
           "3DS Files/source/bvector.c",
           "3DS Files/source/bmatrix.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c",
           "3DS Files/source/vtable.c"]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = retail_model.RETAIL_GP

F = dict(
    ctor=0x00167a08,
    stop=0x00167fb8,
    sinit=0x00167fe0,
    getvalue=0x0018f838,
)
VTABLE = 0x002b2190
TABLES = (0x002fad50, 0x002fad78, 0x002fae88)

GET_STEERING = 0x00132af0
PUT_FLAT = 0x00132910
TOUCH = 0x001c0cf8
TERRAIN = 0x001c0d48
WMAT = 0x001c0ef0
GEOM_POS = 0x001c0f40
FAKE_RPM = 0x00132b00
CARMOVER_DTOR = 0x00136b78

# The .lit4 pool Move and the start-up code read, and the bits the port's
# trafficcar.c spells.
POOL = {-30556: 0x38c90fdb, -30552: 0x3fc90fdc, -30548: 0x38c90fdb,
        -30544: 0x40490fd0, -30540: 0x40c90fd0, -30536: 0x3c23d70a,
        -30532: 0x3fc90fdc, -30528: 0x41c4b127, -30524: 0x4622f983,
        -30520: 0x38c90fda, -30516: 0x41c4b127}

TC = 0x01E00000                     # the TrafficCar
CAR = 0x01E01000
CS = CAR + 64
CTI = 0x01E02000
DRV = 0x01E03000
TC_SIZE = 36
MOVE_FRAME = 384

# Retail's CarState offsets.
CS_POS, CS_VEL, CS_AV = 32, 48, 144
CS_WAV, CS_WANG, CS_WZF, CS_WBO, CS_WSH = 688, 704, 720, 752, 768
CS_WSLIP, CS_WTU = 820, 852
CS_ANGLE, CS_STEER, CS_FS, CS_VM, CS_MV = 868, 870, 896, 900, 1024

# The script's CarState fields: (retail offset, kind). The harness has the
# same list by name.
CSF = ([(CS_POS + 4 * k, "f") for k in range(4)]          # 0..3
       + [(CS_VEL + 4 * k, "f") for k in range(4)]        # 4..7
       + [(CS_AV + 4 * k, "f") for k in range(4)]         # 8..11
       + [(CS_WAV + 4 * k, "f") for k in range(4)]        # 12..15
       + [(CS_WANG + 4 * k, "f") for k in range(4)]       # 16..19
       + [(CS_WZF + 4 * k, "f") for k in range(4)]        # 20..23
       + [(CS_WBO + 4 * k, "f") for k in range(4)]        # 24..27
       + [(CS_WSH + 4 * k, "f") for k in range(4)]        # 28..31
       + [(CS_WSLIP + 4 * k, "f") for k in range(8)]      # 32..39
       + [(CS_WTU + 4 * k, "f") for k in range(4)]        # 40..43
       + [(CS_ANGLE, "h"), (CS_STEER, "h"), (CS_FS, "f"),  # 44..46
          (CS_VM, "f"), (CS_MV, "w")])                    # 47..48
C_POS, C_VEL, C_AV, C_WAV, C_WANG, C_WZF, C_WBO, C_WSH = (
    0, 4, 8, 12, 16, 20, 24, 28)
C_WSLIP, C_WTU, C_ANGLE, C_STEER, C_FS, C_VM, C_MV = (
    32, 40, 44, 45, 46, 47, 48)

# CarTypeInfo, whose prefix the port lays out as the console does.
T_WHEEL = 288                       # + 32 i: PositionX +0, Radius +12

(OP_TAG, OP_JUNK, OP_CS, OP_CTI, OP_DRV, OP_SET, OP_NEW, OP_DEL, OP_MOVE,
 OP_POKE, OP_STOP, OP_TABLE, OP_TABLES, OP_DUMP) = range(14)

ARGS = {OP_TAG: 1, OP_JUNK: 1, OP_CS: 2, OP_CTI: 2, OP_DRV: 2, OP_SET: 2,
        OP_NEW: 0, OP_DEL: 1, OP_MOVE: 1, OP_POKE: 2, OP_STOP: 2,
        OP_TABLE: 2, OP_TABLES: 0, OP_DUMP: 0}

# OP_SET's keys: PutFlatOnTrack's two steps.
K_FLATDX, K_FLATDZ = range(2)
# What OP_DEL puts in the vptr before the destructor runs.
DEL_JUNK_VPTR = 0x00c0ffee
# OP_DRV's fields.
D_STEER, D_THROTTLE, D_BRAKE = range(3)
# OP_POKE's offsets, the console's.
P_X, P_Y, P_ANGLE, P_SPEED, P_PITCH, P_ROLL = 12, 16, 20, 24, 28, 32


def fb(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def bf(b):
    return struct.unpack("<f", struct.pack("<I", b & M32))[0]


def f32(x):
    return bf(fb(x))


def fx(b):
    """A float's bits, or "nan" for any NaN: the EE has none, and which one
    an IEEE host or the model makes is neither's to say."""
    b &= M32
    if (b & 0x7f800000) == 0x7f800000 and b & 0x007fffff:
        return "nan"
    return "%08x" % b


class Fb(object):
    """A float argument given as its bits."""
    def __init__(self, bits):
        self.bits = bits & M32


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

    def cs(self, field, v):
        self.op(OP_CS, field, v if isinstance(v, (int, Fb)) else float(v))

    def set(self, key, v):
        self.op(OP_SET, key, v if isinstance(v, (int, Fb)) else float(v))

    def drv(self, steer=None, throttle=None, brake=None):
        if steer is not None:
            self.op(OP_DRV, D_STEER, steer & 0xffff)
        if throttle is not None:
            self.op(OP_DRV, D_THROTTLE,
                    throttle if isinstance(throttle, Fb) else f32(throttle))
        if brake is not None:
            self.op(OP_DRV, D_BRAKE,
                    brake if isinstance(brake, Fb) else f32(brake))

    def poke(self, off, v):
        self.op(OP_POKE, off, v if isinstance(v, Fb) else f32(v))

    def car_type(self, front=1.35, rear=-1.3, radius=(0.33, 0.335, 0.34,
                                                       0.345)):
        """The wheels' x: 0 at `front`, 3 at `rear`, and 1 and 2 a little in
        from them, so a read of the wrong wheel shows."""
        for i in range(4):
            x = (front, f32(front - 0.03125), f32(rear + 0.0625), rear)[i]
            self.op(OP_CTI, T_WHEEL + 32 * i, fb(f32(x)))
            r = radius[i]
            self.op(OP_CTI, T_WHEEL + 32 * i + 12,
                    r.bits if isinstance(r, Fb) else fb(f32(r)))

    def car(self, pos, ang, vm, fs=None, w=0.375):
        """The car at `pos` (its fourth word `w`), heading `ang` in BAM,
        VelocityMagnitude `vm`; the rest of what Move writes filled with
        junk, so a field it skips shows."""
        for k, v in enumerate(tuple(pos) + (w,)):
            self.cs(C_POS + k, f32(v))
        for k in range(4):
            self.cs(C_VEL + k, f32(1.5 + k))
            self.cs(C_AV + k, f32(-0.5 - k))
            self.cs(C_WAV + k, f32(11.0 + k))
            self.cs(C_WANG + k, f32(0.25 * (k + 1)))
            self.cs(C_WZF + k, f32(3000.0 + k))
            self.cs(C_WBO + k, f32(0.125 + k))
            self.cs(C_WSH + k, f32(0.0625 * (k + 1)))
            self.cs(C_WTU + k, f32(0.5 + 0.0625 * k))
        for k in range(8):
            self.cs(C_WSLIP + k, f32(0.75 - 0.125 * k))
        self.cs(C_ANGLE, ang & 0xffff)
        self.cs(C_STEER, 0x1234)
        self.cs(C_FS, f32(vm * 0.97 if fs is None else fs))
        self.cs(C_VM, f32(vm))
        self.cs(C_MV, 1)

    def moves(self, dt, n, every=1):
        for i in range(n):
            self.op(OP_MOVE, f32(dt))
            if (i + 1) % every == 0 or i == n - 1:
                self.op(OP_DUMP)


# ============================================================== the script

BAM = f32(9.58738e-05)              # gp-30548
STRAIGHT = f32(0.01)                # gp-30536
PI = bf(0x40490fd0)
TWO_PI = bf(0x40c90fd0)


def steer_angle(s):
    a = f32(float(s & 0xffff) * BAM)
    if PI < a:
        a = f32(a - TWO_PI)
    return a


def limit_of(wb):
    return f32(wb * STRAIGHT)


def edge_wheelbase(target):
    """A wheelbase whose straight-ahead limit is `target` exactly, or None."""
    guess = fb(f32(target / STRAIGHT))
    for d in range(-8, 9):
        wb = bf(guess + d)
        if limit_of(wb) == target:
            return wb
    return None


def edges():
    """(steering, wheelbase) pairs at the straight-ahead limit, either side
    of the wheel."""
    out = []
    for s in range(150, 600):
        a = steer_angle(s)
        wb = edge_wheelbase(a)
        if wb is not None and 1.5 < wb < 6.0:
            out.append((s, wb))
            break
    for s in range(150, 600):
        a = steer_angle(0x10000 - s)
        wb = edge_wheelbase(-a)
        if wb is not None and 1.5 < wb < 6.0:
            out.append((0x10000 - s, wb))
            break
    assert len(out) == 2, out
    return out


def fresh(sc, pos=(10.0, -4.0, 1.5), ang=0, vm=12.0, seed=1, w=0.375,
          front=1.35, rear=-1.3, radius=(0.33, 0.335, 0.34, 0.345)):
    sc.car_type(front, rear, radius)
    sc.car(pos, ang, vm, w=w)
    sc.op(OP_JUNK, seed)
    sc.op(OP_NEW)


def script():
    sc = Script()
    rnd = random.Random(0x167af8)

    # -- the start-up code's Tables ---------------------------------------
    sc.tag("tables")
    sc.op(OP_TABLES)
    args = [-1.0, 0.0, 1e-6, 3.0, 8.19, 8.1955, 12.29, 16.39, 20.0,
            24.5865, 24.6, 30.0, float("inf"), float("-inf")]
    args += [f32(rnd.uniform(-2.0, 27.0)) for _ in range(30)]
    for which in range(3):
        for a in args:
            sc.op(OP_TABLE, which, f32(a))
    for a in args[:12]:
        sc.op(OP_STOP, f32(rnd.uniform(-5.0, 5.0)), f32(a))
    sc.op(OP_STOP, float("nan"), 7.5)

    # -- the constructor and the destructor -------------------------------
    for ang, vm, fs in ((0, 12.0, None), (0x4000, 0.0, 3.0),
                        (0xffff, 24.5865, None), (0x8000, 31.0, -2.0),
                        (0x7fff, 0.5, None), (0x0001, 7.25, 7.25)):
        sc.tag("new %04x %s" % (ang, vm))
        sc.car_type()
        sc.car((-3.0, 1.0, 0.5), ang, vm, fs=fs)
        sc.op(OP_JUNK, ang & 0xff)
        sc.op(OP_NEW)
        sc.op(OP_DUMP)
    for flags in (0, 1, 2, 3):
        sc.tag("del %d" % flags)
        fresh(sc, seed=flags + 9)
        sc.op(OP_DEL, flags)

    # -- straight on ------------------------------------------------------
    sc.tag("straight")
    fresh(sc, ang=0x1555)
    sc.drv(steer=0, throttle=1.0, brake=0.0)
    sc.moves(1.0 / 30.0, 30, every=5)
    sc.drv(throttle=0.0, brake=1.0)
    sc.moves(1.0 / 30.0, 40, every=8)

    sc.tag("straight, small steering")
    fresh(sc, ang=0xe000, vm=18.0)
    for s in (1, 100, 0xffff, 0x10000 - 100):
        sc.drv(steer=s, throttle=0.5, brake=0.0)
        sc.moves(1.0 / 30.0, 3)

    # -- round the circle ---------------------------------------------------
    for s in (0x0400, 0x1000, 0x3000, 0x7fff, 0x8000, 0x8001, 0xc000,
              0xf000, 0xfc00):
        sc.tag("turn %04x" % s)
        fresh(sc, ang=0x2000, vm=15.0)
        sc.drv(steer=s, throttle=0.6, brake=0.1)
        sc.moves(1.0 / 30.0, 12, every=3)

    # -- the straight-ahead limit, exactly, either side ---------------------
    for s, wb in edges():
        for k in (-1, 0, 1):
            sc.tag("edge %04x %+d" % (s, k))
            fresh(sc, ang=0x0800, vm=20.0, front=wb, rear=0.0)
            sc.drv(steer=(s + k) & 0xffff, throttle=0.3, brake=0.0)
            sc.moves(1.0 / 30.0, 2)

    # -- the wheelbase: none, and backwards --------------------------------
    # With none and the wheel dead centre the image divides 0 by 0, and
    # backwards with it centred by 0: the EE's divide, then infinities and
    # NaNs, which the dump prints as "nan" whatever their bits.
    for front, rear, s in ((1.0, 1.0, 0), (1.0, 1.0, 1), (1.0, 1.0, 0xffff),
                           (1.0, 1.0, 0x0200), (-1.2, 1.4, 0x0200),
                           (-1.2, 1.4, 0), (-1.2, 1.4, 1),
                           (-1.2, 1.4, 0xffff), (0.0, 0.0, 0xfe00)):
        sc.tag("wheelbase %s %s %04x" % (front, rear, s))
        fresh(sc, front=front, rear=rear, vm=9.0)
        sc.drv(steer=s, throttle=0.2, brake=0.0)
        sc.moves(1.0 / 30.0, 3)

    # -- the speed's clamps --------------------------------------------------
    sc.tag("speed: brake below 0")
    fresh(sc, vm=0.5)
    sc.drv(steer=0x0100, throttle=0.0, brake=1.0)
    sc.moves(1.0 / 30.0, 3)
    sc.tag("speed: throttle past 55 mph")
    fresh(sc, vm=24.5)
    sc.drv(steer=0xff00, throttle=1.0, brake=0.0)
    sc.moves(1.0 / 30.0, 3)
    sc.moves(0.5, 2)
    sc.tag("speed: exactly 0 and the most")
    fresh(sc, vm=0.0)
    sc.drv(steer=0, throttle=0.0, brake=0.0)
    sc.moves(1.0 / 30.0, 2)
    sc.poke(P_SPEED, 24.5865)
    sc.moves(1.0 / 30.0, 2)
    sc.poke(P_SPEED, Fb(fb(24.5865) + 1))
    sc.moves(1.0 / 30.0, 1)
    sc.poke(P_SPEED, -1.0)
    sc.moves(1.0 / 30.0, 1)
    sc.poke(P_SPEED, Fb(0x80000000))
    sc.moves(1.0 / 30.0, 1)
    # -0 throttled by -0: the sum is -0, which is not below 0.
    sc.poke(P_SPEED, Fb(0x80000000))
    sc.drv(throttle=Fb(0x80000000), brake=0.0)
    sc.moves(1.0 / 30.0, 1)
    sc.tag("speed: both pedals, reversed")
    fresh(sc, vm=10.0)
    sc.drv(steer=0x0080, throttle=1.0, brake=1.0)
    sc.moves(1.0 / 30.0, 6, every=2)
    sc.drv(throttle=-0.5, brake=-0.25)
    sc.moves(1.0 / 30.0, 6, every=2)

    # -- dt ------------------------------------------------------------------
    sc.tag("dt 0")
    fresh(sc, vm=10.0)
    sc.drv(steer=0x0300, throttle=0.5, brake=0.0)
    sc.moves(0.0, 2)
    sc.tag("dt 0, straight")
    fresh(sc, vm=10.0)
    sc.drv(steer=0, throttle=0.5, brake=0.0)
    sc.moves(0.0, 2)
    sc.tag("dt negative and large")
    fresh(sc, vm=10.0)
    sc.drv(steer=0x0300, throttle=0.5, brake=0.0)
    sc.moves(-1.0 / 30.0, 2)
    sc.moves(2.5, 2)

    # -- the wheels: no radius ------------------------------------------------
    sc.tag("radius 0")
    fresh(sc, vm=6.0, radius=(0.0, 0.33, -0.34, 0.34))
    sc.drv(steer=0x0200, throttle=0.5, brake=0.0)
    sc.moves(1.0 / 30.0, 2)
    sc.tag("radius 0, standing")
    fresh(sc, vm=0.0, radius=(0.0, 0.0, 0.0, 0.0))
    sc.drv(steer=0x0200, throttle=0.0, brake=0.0)
    sc.moves(1.0 / 30.0, 2)

    # -- PutFlatOnTrack moves the car ----------------------------------------
    sc.tag("flat moves the car")
    fresh(sc, vm=14.0, w=-2.5)
    sc.set(K_FLATDX, 0.75)
    sc.set(K_FLATDZ, -0.375)
    sc.drv(steer=0x0280, throttle=0.4, brake=0.0)
    sc.moves(1.0 / 30.0, 4)
    sc.tag("flat, the fourth word infinite")
    fresh(sc, vm=14.0, w=float("inf"))
    sc.drv(steer=0x0280, throttle=0.4, brake=0.0)
    sc.moves(1.0 / 30.0, 2)
    sc.tag("flat lifts a standing car")
    fresh(sc, vm=0.0)
    sc.drv(steer=0, throttle=0.0, brake=0.0)
    sc.moves(1.0 / 30.0, 2)
    sc.set(K_FLATDX, 0.0)
    sc.set(K_FLATDZ, 0.0)

    # -- the heading ----------------------------------------------------------
    for a in (6.2831, 6.2832, -0.0001, -3.5, 100.0, 205887.0, 205888.0,
              1e7, -1e7, 3e9, -3e9):
        sc.tag("angle %s" % a)
        fresh(sc, vm=8.0, ang=0x4321)
        sc.poke(P_ANGLE, a)
        sc.drv(steer=0x0180, throttle=0.3, brake=0.0)
        sc.moves(1.0 / 30.0, 2)
    sc.tag("angle wraps the yaw rate")
    fresh(sc, vm=8.0, ang=0xfff0)
    sc.poke(P_ANGLE, 6.28)
    sc.drv(steer=0xf800, throttle=0.0, brake=0.0)
    sc.moves(1.0 / 30.0, 3)
    sc.tag("angle, the car's heading not the mover's")
    fresh(sc, vm=8.0, ang=0)
    sc.cs(C_ANGLE, 0x8000)
    sc.drv(steer=0, throttle=0.0, brake=0.0)
    sc.moves(1.0 / 30.0, 1)

    # -- a long drive ---------------------------------------------------------
    sc.tag("drive")
    fresh(sc, pos=(250.0, 120.0, 3.0), ang=0x9abc, vm=0.0)
    for i in range(90):
        if i % 10 == 0:
            sc.drv(steer=rnd.randrange(0x10000) if i % 20 else 0,
                   throttle=f32(rnd.uniform(0.0, 1.0)),
                   brake=f32(rnd.uniform(0.0, 0.3) if i % 30 else 0.0))
        sc.op(OP_MOVE, f32(1.0 / 30.0))
        if i % 9 == 8:
            sc.op(OP_DUMP)

    # -- random --------------------------------------------------------------
    for n in range(40):
        sc.tag("random %d" % n)
        fresh(sc, pos=(f32(rnd.uniform(-900, 900)), f32(rnd.uniform(-900, 900)),
                       f32(rnd.uniform(-20, 40))),
              ang=rnd.randrange(0x10000), vm=f32(rnd.uniform(0.0, 26.0)),
              seed=n, w=f32(rnd.uniform(-2, 2)),
              front=f32(rnd.uniform(0.8, 2.0)),
              rear=f32(rnd.uniform(-2.0, -0.6)),
              radius=tuple(f32(rnd.uniform(0.25, 0.45)) for _ in range(4)))
        sc.set(K_FLATDX, f32(rnd.uniform(-0.05, 0.05)) if n % 3 == 0 else 0.0)
        sc.set(K_FLATDZ, f32(rnd.uniform(-0.2, 0.2)) if n % 2 == 0 else 0.0)
        for k in range(4):
            r = rnd.random()
            s = (rnd.randrange(-300, 300) if r < 0.3
                 else rnd.randrange(0x10000))
            sc.drv(steer=s & 0xffff, throttle=f32(rnd.uniform(0.0, 1.0)),
                   brake=f32(rnd.uniform(0.0, 1.0) if r < 0.5 else 0.0))
            sc.op(OP_MOVE, f32(rnd.choice((1.0 / 30.0, 1.0 / 60.0,
                                           rnd.uniform(0.001, 0.2)))))
            sc.op(OP_DUMP)
    sc.set(K_FLATDX, 0.0)
    sc.set(K_FLATDZ, 0.0)

    sc.tag("end")
    sc.op(OP_TABLES)
    return sc


# =============================================================== the model


class Model(object):
    def __init__(self, sc=None):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        e.stub_bware()
        self.vals = {K_FLATDX: 0, K_FLATDZ: 0}
        for base, n in ((TC, 0x1000), (CAR, 0x1000), (CTI, 0x1000),
                        (DRV, 0x1000)):
            e.mem[base:base + n] = bytes(n)
        for off, bits in POOL.items():
            assert e.u32(GP + off) == bits, (off, hex(e.u32(GP + off)))
        e.put32(CAR + 12, CTI)
        e.put32(CAR + 44, DRV)
        self.stubs()
        e.call(F["sinit"])

    def emit(self, s):
        self.out.append(s)

    def w(self, a):
        return self.e.u32(a)

    def s16(self, a):
        v = self.e.u16(a)
        return v - 0x10000 if v & 0x8000 else v

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        for base, name in ((TC, "tc"), (CAR, "car"), (CS, "cs"),
                           (DRV, "drv"), (CTI, "cti")):
            if a == base:
                return name
        return "?"

    # ---- the stand-ins ---------------------------------------------------

    def stubs(self):
        e = self.e

        def arg(i):
            return e.reg[4 + i] & M32

        def steer(em):
            v = e.u16(self.w(arg(0) + 44) + 528)
            self.emit("  steer %s -> %d" % (self.label(arg(0)), v))
            return v

        def put_flat(em):
            self.emit("  flat %s" % self.label(arg(0)))
            for off, key in ((0, K_FLATDX), (8, K_FLATDZ)):
                a = CS + CS_POS + off
                e.put32(a, fb(f32(bf(self.w(a)) + bf(self.vals[key]))))

        def touch(em):
            on = arg(2) & 0xff
            self.emit("  touch %s %d %d" % (self.label(arg(0)), s32(arg(1)),
                                            on - 256 if on & 0x80 else on))

        def terrain(em):
            self.emit("  terrain %s %d %d" % (self.label(arg(0)), s32(arg(1)),
                                              s32(arg(2))))

        def wmat(em):
            self.emit("  wmat %s" % self.label(arg(0)))

        def geom(em):
            self.emit("  geom %s" % self.label(arg(0)))

        def rpm(em):
            self.emit("  rpm %s" % self.label(arg(0)))

        def cm_dtor(em):
            self.emit("  carmover dtor %s %d" % (self.label(arg(0)),
                                                  s32(arg(1))))

        e.stub(GET_STEERING, steer)
        e.stub(PUT_FLAT, put_flat)
        e.stub(TOUCH, touch)
        e.stub(TERRAIN, terrain)
        e.stub(WMAT, wmat)
        e.stub(GEOM_POS, geom)
        e.stub(FAKE_RPM, rpm)
        e.stub(CARMOVER_DTOR, cm_dtor)

    # ---- the dump --------------------------------------------------------

    def words(self, a, n):
        return " ".join(fx(self.w(a + 4 * k)) for k in range(n))

    def dump(self):
        e, w = self.e, self.w
        m = TC
        self.emit("tc vt %08x drv %s car %s pos %s %s ang %s spd %s p %s r %s"
                  % (w(m + 4), self.label(w(m)), self.label(w(m + 8)),
                     fx(w(m + 12)), fx(w(m + 16)), fx(w(m + 20)),
                     fx(w(m + 24)), fx(w(m + 28)), fx(w(m + 32))))
        c = CS
        self.emit("cs pos %s vel %s av %s ang %d st %d fs %s vm %s mv %d"
                  % (self.words(c + CS_POS, 4), self.words(c + CS_VEL, 4),
                     self.words(c + CS_AV, 4), e.u16(c + CS_ANGLE),
                     e.u16(c + CS_STEER), fx(w(c + CS_FS)), fx(w(c + CS_VM)),
                     s32(w(c + CS_MV))))
        self.emit("cs wav %s wang %s zf %s bo %s sh %s"
                  % (self.words(c + CS_WAV, 4), self.words(c + CS_WANG, 4),
                     self.words(c + CS_WZF, 4), self.words(c + CS_WBO, 4),
                     self.words(c + CS_WSH, 4)))
        self.emit("cs slip %s tu %s" % (self.words(c + CS_WSLIP, 8),
                                        self.words(c + CS_WTU, 4)))

    def tables(self):
        w = self.w
        for i, t in enumerate(TABLES):
            n = s32(w(t + 4))
            self.emit("table %d n %d min %s max %s mul %s"
                      % (i, n, fx(w(t + 8)), fx(w(t + 12)), fx(w(t + 16))))
            self.emit("  data %s" % self.words(w(t), n))

    # ---- the run ---------------------------------------------------------

    def vcall(self, slot, *args):
        e = self.e
        vt = self.w(TC + 4)
        delta = self.s16(vt + slot)
        fn = self.w(vt + slot + 4)
        return e.call(fn, (TC + delta) & M32, *args)

    def run(self, sc):
        e = self.e
        tags = sc.tags
        for o in sc.ops:
            code, a = o[0], o[1:]
            if code == OP_TAG:
                self.emit("[%s]" % tags[a[0]])
            elif code == OP_JUNK:
                e.mem[TC:TC + TC_SIZE] = bytes(
                    [(0xa1 + a[0] + 7 * k) & 0xff for k in range(TC_SIZE)])
            elif code == OP_CS:
                off, kind = CSF[a[0]]
                if kind == "h":
                    e.write(CS + off, struct.pack("<H", a[1] & 0xffff))
                else:
                    e.put32(CS + off, a[1])
            elif code == OP_CTI:
                e.put32(CTI + a[0], a[1])
            elif code == OP_DRV:
                if a[0] == D_STEER:
                    e.write(DRV + 528, struct.pack("<H", a[1] & 0xffff))
                else:
                    e.put32(DRV + (532 if a[0] == D_THROTTLE else 536), a[1])
            elif code == OP_SET:
                self.vals[a[0]] = a[1] & M32
            elif code == OP_NEW:
                self.emit("new")
                r = e.call(F["ctor"], TC, CAR)
                self.emit("new -> %s" % self.label(r))
            elif code == OP_DEL:
                # The table's entry, then a vptr not its own, so that the
                # destructor's store shows.
                vt = self.w(TC + 4)
                delta = self.s16(vt + 8)
                fn = self.w(vt + 8 + 4)
                e.put32(TC + 4, DEL_JUNK_VPTR)
                self.emit("del %d" % a[0])
                e.call(fn, (TC + delta) & M32, a[0])
                self.emit("del vt %08x" % self.w(TC + 4))
            elif code == OP_MOVE:
                e.put32(TC, DRV)
                # The two stack words Move stores and never writes: the
                # port's choices, the old Position's fourth and 0.
                sp = (e.reg[29] & M32) - MOVE_FRAME
                e.put32(sp + 60, self.w(CS + CS_POS + 12))
                e.put32(sp + 140, 0)
                self.emit("move %s" % fx(a[0]))
                e.fpr[12] = a[0]
                self.vcall(16)
                self.emit("move -> %s" % fx(e.fpr[0]))
            elif code == OP_POKE:
                e.put32(TC + a[0], a[1])
            elif code == OP_STOP:
                e.fpr[12] = a[0]
                e.fpr[13] = a[1]
                e.call(F["stop"], TC)
                self.emit("stop %s %s -> %s" % (fx(a[0]), fx(a[1]),
                                                fx(e.fpr[0])))
            elif code == OP_TABLE:
                e.fpr[12] = a[1]
                e.call(F["getvalue"], TABLES[a[0]])
                self.emit("value %d %s -> %s" % (a[0], fx(a[1]),
                                                 fx(e.fpr[0])))
            elif code == OP_TABLES:
                self.tables()
            elif code == OP_DUMP:
                self.dump()
            else:
                raise ValueError("op %d" % code)
        return self.out


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc.encode().hex().splitlines()
                               + sc.tags, lambda s: Model().run(sc),
                               cut=MUTATIONS_HEADER)


# ================================================================ the build


def build_harness(tmp, name="trafficcar_test"):
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
    return (name, TCC, before, after)


def MH(name, before, after):
    return (name, TCH, before, after)


MUTATIONS = [
    # -- the constants -------------------------------------------------------
    M("c-bam", "9.58738e-05f    // gp-30556", "9.5874e-05f     // gp-30556"),
    M("c-halfpi", "1.5707965f      // gp-30552",
      "1.5707963f      // gp-30552"),
    M("c-pi", "3.14159f        // gp-30544", "3.1416f         // gp-30544"),
    M("c-twopi", "6.28318f        // gp-30540",
      "6.28319f        // gp-30540"),
    M("c-straight", "0.01f           // gp-30536",
      "0.011f          // gp-30536"),
    M("c-max", "24.5865f        // gp-30528", "24.5f           // gp-30528"),
    M("c-radbam", "10430.378f      // gp-30524",
      "10430.0f        // gp-30524"),
    M("c-yaw", "9.5873795e-05f  // gp-30520", "9.58738e-05f    // gp-30520"),

    # -- the Tables ------------------------------------------------------------
    M("ta-0", "3.5762181f, 2.6821637f", "3.5f, 2.6821637f"),
    M("ta-3", "2.0116227f, 1.3410819f", "2.0116227f, 1.35f"),
    M("tb-0", "6.705409f, 13.410818f", "6.7f, 13.410818f"),
    M("tb-3", "20.116226f, 26.821636f", "20.116226f, 26.8f"),
    M("sd-1", "0.0f, 0.018f,", "0.0f, 0.019f,"),
    M("sd-0", "0.0f, 0.018f,", "0.001f, 0.018f,"),
    M("sd-mid", "9.647f,", "9.648f,"),
    M("sd-last", "    19.34f,", "    19.3f,"),
    M("ti-acc-n", "TrafficAccelerationTable, 4, 0.0f,",
      "TrafficAccelerationTable, 3, 0.0f,"),
    M("ti-acc-min", "TrafficAccelerationTable, 4, 0.0f,",
      "TrafficAccelerationTable, 4, 0.5f,"),
    M("ti-brk-n", "TrafficBrakingTable, 4, 0.0f, TC_MAX_SPEED);",
      "TrafficBrakingTable, 3, 0.0f, TC_MAX_SPEED);"),
    M("ti-brk-max", "TrafficBrakingTable, 4, 0.0f, TC_MAX_SPEED);",
      "TrafficBrakingTable, 4, 0.0f, 24.0f);"),
    M("ti-brk-data", "table_init(&TrafficBraking, TrafficBrakingTable",
      "table_init(&TrafficBraking, TrafficAccelerationTable"),
    M("ti-sd-n", "StoppingDistanceBySpeed, 61, 0.0f,",
      "StoppingDistanceBySpeed, 60, 0.0f,"),
    M("ti-sd-max", "StoppingDistanceBySpeed, 61, 0.0f,\n"
      "               TC_MAX_SPEED);",
      "StoppingDistanceBySpeed, 61, 0.0f,\n"
      "               30.0f);"),

    # -- the constructor and destructor ---------------------------------------
    M("ct-vt", "m->Mover._vtable = TRAFFICCAR_VTABLE;\n    m->pCar = car;",
      "m->pCar = car;"),
    M("ct-car", "m->pCar = car;", "m->pCar = car + 1;"),
    M("ct-x", "m->Position.x = car->State.Position.x;",
      "m->Position.x = car->State.Position.y;"),
    M("ct-y", "m->Position.y = car->State.Position.y;",
      "m->Position.y = car->State.Position.z;"),
    M("ct-ang-s16", "(float)(int32_t)car->State.Angle",
      "(float)(int16_t)car->State.Angle"),
    M("ct-ang-k", "car->State.Angle * TC_BAM_TO_RAD",
      "car->State.Angle * TC_YAW_BAM_TO_RAD"),
    M("ct-speed", "m->Speed = car->State.VelocityMagnitude;",
      "m->Speed = car->State.ForwardSpeed;"),
    M("ct-pitch", "    m->Pitch = 0.0f;\n", ""),
    M("ct-roll", "    m->Roll = 0.0f;\n", ""),
    M("dt-vt", "    m->Mover._vtable = TRAFFICCAR_VTABLE;\n    // `j", "    // `j"),
    M("dt-flags", "carmover_destroy(&m->Mover, flags);",
      "carmover_destroy(&m->Mover, flags & 1);"),
    MH("vt-addr", "#define TRAFFICCAR_VTABLE     0x002b2190u",
       "#define TRAFFICCAR_VTABLE     0x002b2198u"),
    M("vt-move", "{ 0, 0, (VtFn)vt_TrafficCar_Move },     // 16",
      "{ 0, 0, NULL },     // 16"),
    M("vt-dtor", "{ 0, 0, (VtFn)vt_TrafficCar_dtor },     //  8",
      "{ 0, 0, NULL },     //  8"),

    # -- Move: the wheelbase and the heading ------------------------------------
    M("mv-dist", "dist = m->Speed * dt;", "dist = m->Speed;"),
    M("mv-rear", "rear = cti->Wheels[3].PositionX;",
      "rear = cti->Wheels[2].PositionX;"),
    M("mv-front", "wb = cti->Wheels[0].PositionX + -rear;",
      "wb = cti->Wheels[1].PositionX + -rear;"),
    M("mv-wb-sign", "wb = cti->Wheels[0].PositionX + -rear;",
      "wb = cti->Wheels[0].PositionX + rear;"),
    M("mv-c", "c = bSinF(m->Angle + TC_HALF_PI);",
      "c = bSinF(m->Angle - TC_HALF_PI);"),
    M("mv-s", "s = bSinF(m->Angle);", "s = bSinF(-m->Angle);"),
    M("mv-fwd", "fwd.x = c;\n    fwd.y = s;", "fwd.x = s;\n    fwd.y = c;"),
    M("mv-side-x", "side.x = -s;", "side.x = s;"),
    M("mv-side-y", "side.y = c;", "side.y = -c;"),

    # -- the steering -------------------------------------------------------------
    M("st-k", "car_get_steering(m->pCar) * TC_BAM_TO_RAD;",
      "car_get_steering(m->pCar) * TC_YAW_BAM_TO_RAD;"),
    M("st-s16", "steer = (float)(int32_t)car_get_steering",
      "steer = (float)(int16_t)car_get_steering"),
    M("st-pi-le", "if (TC_PI < steer)", "if (TC_PI <= steer)"),
    M("st-nowrap", "if (TC_PI < steer)", "if (0)"),
    M("st-wrap-k", "steer = steer - TC_TWO_PI;", "steer = steer - TC_PI;"),
    M("st-limit", "limit = wb * TC_STRAIGHT;", "limit = TC_STRAIGHT;"),
    M("st-lt-le", "if (steer < limit && -limit < steer)",
      "if (steer <= limit && -limit < steer)"),
    M("st-gt-ge", "if (steer < limit && -limit < steer)",
      "if (steer < limit && -limit <= steer)"),
    M("st-or", "if (steer < limit && -limit < steer)",
      "if (steer < limit || -limit < steer)"),
    M("st-one", "if (steer < limit && -limit < steer)",
      "if (steer < limit)"),

    # -- straight on ---------------------------------------------------------------
    M("sa-x", "m->Position.x = m->Position.x + fwd.x * dist;",
      "m->Position.x = m->Position.x + fwd.y * dist;"),
    M("sa-y", "m->Position.y = m->Position.y + fwd.y * dist;",
      "m->Position.y = m->Position.y - fwd.y * dist;"),

    # -- round the circle -----------------------------------------------------------
    M("ci-r-div", "r = ee_div(wb, steer);", "r = wb / steer;"),
    M("ci-r-swap", "r = ee_div(wb, steer);", "r = ee_div(steer, wb);"),
    M("ci-front-k", "bScaleAdd2(&front, &m->Position, &fwd, rear);",
      "bScaleAdd2(&front, &m->Position, &fwd, wb);"),
    M("ci-front-v", "bScaleAdd2(&front, &m->Position, &fwd, rear);",
      "bScaleAdd2(&front, &m->Position, &side, rear);"),
    M("ci-turn", "turn = ee_div(dist, r);", "turn = ee_div(dist, wb);"),
    M("ci-turn-div", "turn = ee_div(dist, r);", "turn = dist / r;"),
    M("ci-center-v", "bScaleAdd2(&center, &front, &side, r);",
      "bScaleAdd2(&center, &front, &fwd, r);"),
    M("ci-center-neg", "bScaleAdd2(&center, &front, &side, r);",
      "bScaleAdd2(&center, &front, &side, -r);"),
    M("ci-center-pos", "bScaleAdd2(&center, &front, &side, r);",
      "bScaleAdd2(&center, &m->Position, &side, r);"),
    M("ci-c", "c = bSinF(turn + TC_HALF_PI);", "c = bSinF(turn - TC_HALF_PI);"),
    M("ci-s", "s = bSinF(turn);", "s = bSinF(-turn);"),
    M("ci-rx", "rx = m->Position.x - center.x;",
      "rx = center.x - m->Position.x;"),
    M("ci-ry", "ry = m->Position.y - center.y;",
      "ry = m->Position.y - center.x;"),
    M("ci-nx", "nx = c * rx - s * ry;", "nx = c * rx + s * ry;"),
    M("ci-ny", "ny = s * rx + c * ry;", "ny = s * rx - c * ry;"),
    M("ci-ny-v", "ny = s * rx + c * ry;", "ny = s * ry + c * rx;"),
    M("ci-px", "m->Position.x = center.x + nx;", "m->Position.x = nx;"),
    M("ci-py", "m->Position.y = center.y + ny;",
      "m->Position.y = center.y + nx;"),
    M("ci-ang", "m->Angle = m->Angle + turn;", "m->Angle = m->Angle - turn;"),
    M("ci-ang-off", "        m->Angle = m->Angle + turn;\n", ""),

    # -- the pedals and the speed ------------------------------------------------------
    M("sp-acc-tab", "table_get_value(&TrafficAcceleration, m->Speed)",
      "table_get_value(&TrafficBraking, m->Speed)"),
    M("sp-brk-tab", "table_get_value(&TrafficBraking, m->Speed)",
      "table_get_value(&TrafficAcceleration, m->Speed)"),
    M("sp-acc-arg", "table_get_value(&TrafficAcceleration, m->Speed)",
      "table_get_value(&TrafficAcceleration, dist)"),
    M("sp-acc-dt", "push = (dt * drv->Throttle)", "push = (drv->Throttle)"),
    M("sp-acc-order", "push = (dt * drv->Throttle)\n"
      "           * table_get_value(&TrafficAcceleration, m->Speed);",
      "push = dt * (drv->Throttle\n"
      "           * table_get_value(&TrafficAcceleration, m->Speed));"),
    M("sp-brk-pedal", "brake = (dt * drv->Brake)", "brake = (dt * drv->Throttle)"),
    M("sp-brk-order",
      "brake = (dt * drv->Brake) * table_get_value(&TrafficBraking, m->Speed);",
      "brake = dt * (drv->Brake * table_get_value(&TrafficBraking, m->Speed));"),
    M("sp-sum", "speed = m->Speed + (push - brake);",
      "speed = (m->Speed + push) - brake;"),
    M("sp-sum-sign", "speed = m->Speed + (push - brake);",
      "speed = m->Speed + (push + brake);"),
    M("sp-negzero", "    m->Speed = speed;\n    if", "    m->Speed = speed + 0.0f;\n    if"),
    M("sp-lo-le", "if (speed < 0.0f)", "if (speed <= 0.0f)"),
    M("sp-lo-val", "        m->Speed = 0.0f;\n    else",
      "        m->Speed = 0.001f;\n    else"),
    M("sp-lo-off", "if (speed < 0.0f)", "if (0)"),
    M("sp-hi-le", "else if (TC_MAX_SPEED < speed)",
      "else if (TC_MAX_SPEED <= speed)"),
    M("sp-hi-else", "else if (TC_MAX_SPEED < speed)",
      "if (TC_MAX_SPEED < speed)"),
    M("sp-hi-off", "else if (TC_MAX_SPEED < speed)", "else if (0)"),
    M("sp-hi-val", "        m->Speed = TC_MAX_SPEED;",
      "        m->Speed = 24.5f;"),

    # -- the car's position --------------------------------------------------------------
    M("ps-x", "pos.x = m->Position.x;", "pos.x = m->Position.y;"),
    M("ps-y", "pos.y = m->Position.y;", "pos.y = old.y;"),
    M("ps-z", "pos.z = old.z;", "pos.z = 0.0f;"),
    M("ps-w", "pos.pad = old.pad;", "pos.pad = 0.0f;"),
    M("ps-flat-off", "    car_put_flat_on_track(m->pCar);\n\n", "\n"),
    M("ps-flat-first", "    cs->Position = pos;\n    car_put_flat_on_track(m->pCar);",
      "    car_put_flat_on_track(m->pCar);\n    cs->Position = pos;"),

    # -- the velocity --------------------------------------------------------------------
    M("ve-x", "vel.x = cs->Position.x - old.x;", "vel.x = pos.x - old.x;"),
    M("ve-y", "vel.y = cs->Position.y - old.y;", "vel.y = old.y - cs->Position.y;"),
    M("ve-z", "vel.z = cs->Position.z - old.z;", "vel.z = pos.z - old.z;"),
    M("ve-w", "vel.pad = cs->Position.pad - old.pad;", "vel.pad = 0.0f;"),
    M("ve-len", "bNormalize3To(&vel, &vel, m->Speed);",
      "bNormalize3To(&vel, &vel, speed);"),
    M("ve-norm-off", "    bNormalize3To(&vel, &vel, m->Speed);\n", ""),
    M("ve-store", "    cs->Velocity = vel;\n", ""),
    M("ve-vm", "cs->VelocityMagnitude = sqrtf((vel.x * vel.x + vel.y * vel.y)\n"
      "                                  + vel.z * vel.z);",
      "cs->VelocityMagnitude = m->Speed;"),
    M("ve-vm-order",
      "sqrtf((vel.x * vel.x + vel.y * vel.y)\n"
      "                                  + vel.z * vel.z)",
      "sqrtf(vel.x * vel.x + (vel.y * vel.y\n"
      "                                  + vel.z * vel.z))"),
    M("ve-fs", "cs->ForwardSpeed = m->Speed;", "cs->ForwardSpeed = speed;"),
    M("ve-mv", "cs->MatrixValid = 0;", "cs->MatrixValid = 1;"),

    # -- the heading and the yaw rate ----------------------------------------------------
    M("an-old", "oldA = cs->Angle;", "oldA = 0;"),
    M("an-trunc", "newA = (uint16_t)ee_trunc_w(m->Angle * TC_RAD_TO_BAM);",
      "newA = (uint16_t)(int32_t)(m->Angle * TC_RAD_TO_BAM);"),
    M("an-round", "ee_trunc_w(m->Angle * TC_RAD_TO_BAM)",
      "ee_trunc_w(m->Angle * TC_RAD_TO_BAM + 0.5f)"),
    M("an-store", "    cs->Angle = newA;\n", ""),
    M("av-u16", "(float)(int16_t)(uint16_t)(newA - oldA)",
      "(float)(uint16_t)(newA - oldA)"),
    M("av-div", "cs->AngularVelocity.z = ee_div(\n"
      "        (float)(int16_t)(uint16_t)(newA - oldA) * TC_YAW_BAM_TO_RAD, dt);",
      "cs->AngularVelocity.z =\n"
      "        (float)(int16_t)(uint16_t)(newA - oldA) * TC_YAW_BAM_TO_RAD / dt;"),
    M("av-k", "* TC_YAW_BAM_TO_RAD, dt);", "* TC_BAM_TO_RAD, dt);"),
    M("av-x", "    cs->AngularVelocity.x = 0.0f;\n", ""),
    M("av-y", "    cs->AngularVelocity.y = 0.0f;\n", ""),
    M("av-w", "    cs->AngularVelocity.pad = 0.0f;\n", ""),
    M("st-store", "cs->SteeringAngle = car_get_steering(m->pCar);",
      "cs->SteeringAngle = 0;"),

    # -- the wheels ------------------------------------------------------------------------
    M("wh-n", "for (i = 0; i < 4; i++) {", "for (i = 0; i < 3; i++) {"),
    M("wh-radius", "ee_div(m->Speed, cti->Wheels[i].Radius)",
      "ee_div(m->Speed, cti->Wheels[0].Radius)"),
    M("wh-div", "w = ee_div(m->Speed, cti->Wheels[i].Radius);",
      "w = m->Speed / cti->Wheels[i].Radius;"),
    M("wh-speed", "w = ee_div(m->Speed, cti->Wheels[i].Radius);",
      "w = ee_div(speed, cti->Wheels[i].Radius);"),
    M("wh-av", "        cs->WheelAngularVelocity[i] = w;\n", ""),
    M("wh-ang", "cs->WheelAngle[i] = cs->WheelAngle[i] + w * dt;",
      "cs->WheelAngle[i] = w * dt;"),
    M("wh-ang-dt", "cs->WheelAngle[i] = cs->WheelAngle[i] + w * dt;",
      "cs->WheelAngle[i] = cs->WheelAngle[i] + w;"),
    M("wh-susp", "        cs->WheelSuspensionHeight[i] = 0.0f;\n", ""),
    M("wh-touch", "carstate_set_wheel_touching_ground(cs, i, 1);",
      "carstate_set_wheel_touching_ground(cs, i, 0);"),
    M("wh-terrain", "carstate_set_wheel_terrain(cs, i, TERRAIN_DEFAULT);",
      "carstate_set_wheel_terrain(cs, i, (TerrainType)0);"),
    M("wh-calls", "        carstate_set_wheel_touching_ground(cs, i, 1);\n"
      "        carstate_set_wheel_terrain(cs, i, TERRAIN_DEFAULT);\n",
      "        carstate_set_wheel_terrain(cs, i, TERRAIN_DEFAULT);\n"
      "        carstate_set_wheel_touching_ground(cs, i, 1);\n"),
    M("wh-slip-x", "        cs->WheelSlip[i].x = 0.0f;\n", ""),
    M("wh-slip-y", "        cs->WheelSlip[i].y = 0.0f;\n", ""),
    M("wh-tu", "        cs->WheelTractionUsage[i] = 0.0f;\n", ""),
    M("wh-zf", "        cs->WheelZForce[i] = 0.0f;\n", ""),
    M("wh-bo", "for (k = 3; k >= 0; k--)", "for (k = 3; k > 0; k--)"),
    M("wh-bo-off", "            cs->WheelBottomOutMagnitude[k] = 0.0f;\n",
      "            (void)k;\n"),

    # -- the tail -----------------------------------------------------------------------------
    M("tl-wmat", "    carstate_calculate_wheel_matrices(cs);\n", ""),
    M("tl-geom", "    carstate_calculate_geometry_position(cs);\n", ""),
    M("tl-order", "    carstate_calculate_wheel_matrices(cs);\n"
      "    carstate_calculate_geometry_position(cs);\n",
      "    carstate_calculate_geometry_position(cs);\n"
      "    carstate_calculate_wheel_matrices(cs);\n"),
    M("tl-rpm", "    car_compute_fake_rpm(m->pCar);\n", ""),
    M("tl-ret", "    return dt;\n}", "    return 0.0f;\n}"),

    # -- CalculateStopDistance -----------------------------------------------------------------
    M("sd-table", "table_get_value(&StoppingDistanceTable, speed)",
      "table_get_value(&TrafficBraking, speed)"),
    M("sd-arg", "table_get_value(&StoppingDistanceTable, speed)",
      "table_get_value(&StoppingDistanceTable, unused)"),

    # -- the seam -------------------------------------------------------------------------------
    M("seam", "gTrafficCarCtorFn = trafficcar_construct;",
      "gTrafficCarCtorFn = NULL;"),
]

EQUIVALENT = {
    # No steering is pi' (40490fd0) as an angle: 32767 makes 40490e49 and
    # 32768 40490fdb.
    "st-pi-le",
    # At exactly the most the speed is the most either way.
    "sp-hi-le",
    # A speed below 0 is not above the most.
    "sp-hi-else",
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
        todo, SOURCES, "trafficcar_test",
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
