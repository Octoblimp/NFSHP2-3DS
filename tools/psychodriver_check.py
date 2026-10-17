"""Cross-check 3DS Files/source/psychodriver.c against the retail image's own
code.

PsychoDriver is the AI's CarDriver: retail's PsychoDriver.obj, 0x00139700
to 0x0013a6ac and 0x0013ab68 to 0x0013ad84, with AIDrivingInfo.obj's
SteerStraightVector3D and SteerStraightVelocity3D. The oracle is
SLES_507.31 itself, run in tools/mipsemu.py:

- RadianWrap, the constructor (0x00139760), the destructor (0x001398e8,
  through the table at 0x002aec50), SetDesiredSpeed, GetError,
  Zero/ClearSteeringMemory, Zero/ClearThrottleMemory, GetMovementIndex,
  Drive (through the table), SetTarget, CalcSteerToPoint,
  CalcThrottleAndBrake, the horn, the getters and setters, and the two
  SteerStraight functions;
- run as shipped under them: ~CarDriver and ~DriveTarget, Average,
  PidError's Record, Reset and destructor, Table, bATan, bSinCos,
  bNormalize, and the start-up code (_GLOBAL_$I$PidProportionalData,
  0x0013ab68) that builds the seven Tables and fPsychoCounterDiff.

Stood in on both sides, each call logged: bMalloc and the frees;
DriveTarget's constructor (which clears its 528 bytes), Clear, operator=
(which copies them), Resample and InterpolatePoint (a scripted point);
CollisionBody::GetCollision and Collision::IsTwoCarCollision (scripted);
CarState::GetYawAlways (scripted); and BaseCarSound's StartHonkHorn,
StopHonkHorn and IsHonking (scripted).

The CarDriver's table is printed by name, as the port's CarDriver keeps
the demo's address; a PidError's host size is logged as the console's 40.

    python tools/psychodriver_check.py
    python tools/psychodriver_check.py --mutate [--only a,b] [--jobs N]
    python tools/psychodriver_check.py --dump PREFIX
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

HARNESS = "tools/src/psychodriver_test.c"
PDC = "3DS Files/source/psychodriver.c"
SOURCES = [HARNESS, PDC,
           "3DS Files/source/cardriver.c",
           "3DS Files/source/average.c",
           "3DS Files/source/table.c",
           "3DS Files/source/bmem.c",
           "3DS Files/source/bvector.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c",
           "3DS Files/source/replay.c", "3DS Files/source/p32.c",
           "3DS Files/source/vtable.c"]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = retail_model.RETAIL_GP

F = dict(
    wrap=0x00139700,
    ctor=0x00139760,
    getError=0x00139a68,
    zeroThrottle=0x00139bb0,
    clearThrottle=0x00139bc0,
    moveIndex=0x00139be0,
    calcSteerTo=0x0013a438,
    calcThrottle=0x0013a548,
    sinit=0x0013ab68,
    jeeves=0x0013acc0,
    maxThrottle=0x0013acf8,
    ebrakeTimer=0x0013ad08,
    ssVector=0x001cd148,
    ssVelocity=0x001cd1d8,
)

BMALLOC = 0x002577c0
BDELETE = 0x00114e98
BFREE = 0x00257850
DT_CTOR = 0x0021b918
DT_CLEAR = 0x0021bbb0
DT_ASSIGN = 0x0021b9a8
DT_RESAMPLE = 0x0021c5c8
DT_INTERP = 0x0021be08
GET_COLLISION = 0x001d6f38
TWO_CAR = 0x0021eb20
YAW_ALWAYS = 0x001c08d0
SND_START = 0x0018d780
SND_STOP = 0x0018d7c0
SND_IS = 0x0018d800
TABLE_GET = 0x0018f838

PSYCHO_VT = 0x002aec50
CARDRIVER_VT = 0x002ae868

COUNTER_DIFF_GP = -13408
WARNED_GP = -22576

# The seven Tables, in psychodriver.h's order, and the four weight arrays.
TABLES = (0x002f0628, 0x002f0640, 0x002f0658, 0x002f0670, 0x002f06f0,
          0x002f0708, 0x002f0720)
WEIGHTS = (0x002aecf8, 0x002aed10, 0x002aed28, 0x002aed40)

PD = 0x01E00000                     # the PsychoDriver
CAR = 0x01E01000
CS = CAR + 64
CTI = 0x01E02000
BODY = 0x01E03000                   # the car's collision body
COLL = 0x01E03100                   # the fake collisions, 16 bytes each
SOUND = 0x01E03800                  # the fake BaseCarSound
SRC = 0x01E04000                    # a DriveTarget for SetTarget
SCR = 0x01E05000                    # out parameters
PD_SIZE = 624
DT_SIZE = 528
SLACK = 16

# Retail's Car offsets, and the script's fields: (offset from the car,
# kind). The harness has the same list by name.
CF = ([(96 + 4 * k, "f") for k in range(4)]               # 0..3 Position
      + [(112 + 4 * k, "f") for k in range(4)]            # 4..7 Velocity
      + [(848 + k, "b") for k in range(4)]                # 8..11 wheels
      + [(932, "h"), (960, "f"), (964, "f"), (988, "w"),  # 12..15
         (10, "h"), (32, "w"), (36, "w")])                # 16..18
C_POS, C_VEL, C_WTG = 0, 4, 8
C_ANGLE, C_FS, C_VM, C_DMODE, C_DNUM, C_CMODE, C_MMODE = range(12, 19)

(OP_TAG, OP_JUNK, OP_FIELD, OP_CTI, OP_SET, OP_SRC, OP_NEW, OP_DEL,
 OP_DRIVE, OP_SDS, OP_TARGET, OP_SSTP, OP_DRVNUM, OP_HONK, OP_ZS, OP_CLS,
 OP_GDS, OP_GTTS, OP_GSTP, OP_LOWGEAR, OP_BASE, OP_ZT, OP_CT, OP_GETERR,
 OP_MOVIDX, OP_CSTP, OP_CTB, OP_JEEVES, OP_MAXTHR, OP_EBT, OP_WRAP, OP_SS,
 OP_TABLE, OP_POKE, OP_PID, OP_NULLPID, OP_DUMP, OP_STATIC) = range(38)

ARGS = {OP_TAG: 1, OP_JUNK: 1, OP_FIELD: 2, OP_CTI: 1, OP_SET: 2,
        OP_SRC: 1, OP_NEW: 0, OP_DEL: 1, OP_DRIVE: 1, OP_SDS: 4,
        OP_TARGET: 1, OP_SSTP: 2, OP_DRVNUM: 0, OP_HONK: 1, OP_ZS: 0,
        OP_CLS: 0, OP_GDS: 0, OP_GTTS: 0, OP_GSTP: 0, OP_LOWGEAR: 0,
        OP_BASE: 1, OP_ZT: 0, OP_CT: 0, OP_GETERR: 0, OP_MOVIDX: 0,
        OP_CSTP: 0, OP_CTB: 0, OP_JEEVES: 0, OP_MAXTHR: 1, OP_EBT: 1,
        OP_WRAP: 1, OP_SS: 2, OP_TABLE: 2, OP_POKE: 2, OP_PID: 3,
        OP_NULLPID: 1, OP_DUMP: 0, OP_STATIC: 0}

# OP_SET's keys: what the stand-ins answer.
(K_YAW, K_IPX, K_IPY, K_IPZ, K_IPW, K_NCOLL, K_TWOCAR, K_SOUND,
 K_HONKING) = range(9)

# OP_POKE's offsets, the console's.
P_STEER, P_THR, P_BRK, P_EB, P_GEAR = 528, 532, 536, 540, 544
P_STPX, P_STPY, P_MAXTHR, P_DS, P_T, P_TOL = 564, 568, 572, 576, 580, 584
P_OK, P_EBT, P_LATCH = 588, 592, 600
POKES = (P_STEER, P_THR, P_BRK, P_EB, P_GEAR, P_STPX, P_STPY, P_MAXTHR,
         P_DS, P_T, P_TOL, P_OK, P_EBT, P_LATCH)
INT_POKES = (P_GEAR, P_OK, P_LATCH)

# OP_PID's PidErrors and fields (console offsets): the integral's total
# and mean, the derivative's, the current and previous errors.
PID_BODY, PID_HEAD, PID_VEL = range(3)
PIDS = (604, 608, 612)
PF_ITOTAL, PF_IAVG, PF_DTOTAL, PF_DAVG, PF_CUR, PF_PREV = 4, 8, 20, 24, 32, 36

# OP_BASE's slots: CarDriver's own, which PsychoDriver keeps.
BASE_SLOTS = (32, 40, 112, 152)

HONK_START, HONK_STOP, HONK_IS = range(3)


def fb(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def bf(b):
    return struct.unpack("<f", struct.pack("<I", b & M32))[0]


def f32(x):
    return bf(fb(x))


def fx(b):
    return "%08x" % (b & M32)


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

    def field(self, f, v):
        kind = CF[f][1]
        if kind == "f":
            self.op(OP_FIELD, f, v if isinstance(v, Fb) else float(v))
        else:
            self.op(OP_FIELD, f, int(v))

    def set(self, key, v):
        self.op(OP_SET, key, v if isinstance(v, (int, Fb)) else float(v))

    def poke(self, off, v):
        if off in INT_POKES or off == P_STEER:
            self.op(OP_POKE, off, int(v))
        else:
            self.op(OP_POKE, off, v if isinstance(v, Fb) else float(v))

    def pid(self, which, off, v):
        self.op(OP_PID, which, off, v if isinstance(v, Fb) else float(v))

    def car(self, pos=(0.0, 0.0, 0.0), heading_deg=0.0, speed=20.0,
            fs=None, vel_deg=None, wheels=(1, 1, 1, 1), dmode=0, mmode=1,
            cmode=2, dnum=3, vz=0.0):
        """The car at `pos`, heading along the angle, moving at `speed`
        along vel_deg (the heading unless given)."""
        a = math.radians(heading_deg)
        va = math.radians(heading_deg if vel_deg is None else vel_deg)
        for k, v in enumerate(pos):
            self.field(C_POS + k, f32(v))
        self.field(C_POS + 3, 0.375)
        self.field(C_VEL, f32(speed * math.cos(va)))
        self.field(C_VEL + 1, f32(speed * math.sin(va)))
        self.field(C_VEL + 2, f32(vz))
        self.field(C_VEL + 3, -0.625)
        for i in range(4):
            self.field(C_WTG + i, wheels[i])
        self.field(C_ANGLE, int(round(heading_deg * 65536.0 / 360.0))
                   & 0xffff)
        self.field(C_VM, f32(abs(speed)))
        self.field(C_FS, f32(speed * 0.97 if fs is None else fs))
        self.field(C_DMODE, dmode)
        self.field(C_MMODE, mmode)
        self.field(C_CMODE, cmode)
        self.field(C_DNUM, dnum)

    def interp(self, x, y, z=1.5, w=0.25):
        for k, v in zip((K_IPX, K_IPY, K_IPZ, K_IPW), (x, y, z, w)):
            self.set(k, f32(v))

    def target(self, n):
        """A target of n points in the source, copied in by SetTarget."""
        self.op(OP_SRC, n)
        self.op(OP_TARGET, 1)


# ============================================================== the script

def table_xs(lo, hi, n):
    """Every grid point of a table, an ulp either side, the midpoints and
    the ends' far sides."""
    xs = [lo - 10.0, lo - 1.0, f32(lo - 0.001), hi + 1.0, hi + 50.0]
    step = (hi - lo) / (n - 1)
    for i in range(n):
        g = f32(lo + step * i)
        xs += [g, nextup(g, -1), nextup(g, 1), f32(g + step * 0.5),
               f32(g + step * 0.25)]
    return xs


def script():
    sc = Script()
    rnd = random.Random(0x9e5c)

    sc.op(OP_CTI, 0.875)

    # -- the data ----------------------------------------------------------
    sc.tag("static")
    sc.op(OP_STATIC)
    for t in range(7):
        hi = 1.0 if t == 6 else 160.0
        n = 6 if t == 6 else 10
        for x in table_xs(0.0, hi, n):
            sc.op(OP_TABLE, t, f32(x))

    sc.tag("wrap")
    bams = [0, 1, 2, 100, 0x3fff, 0x4000, 0x7ffe, 0x7fff, 0x8000, 0x8001,
            0x8002, 0xbfff, 0xc000, 0xfffe, 0xffff]
    bams += [rnd.randrange(0x10000) for _ in range(40)]
    for b in bams:
        sc.op(OP_WRAP, b)

    # -- SteerStraight -------------------------------------------------------
    sc.tag("steer straight")
    for k in range(40):
        pos = (rnd.uniform(-500, 500), rnd.uniform(-500, 500),
               rnd.uniform(-20, 20))
        h = rnd.uniform(-180, 180)
        speed = rnd.choice((0.0, 0.5, 3.0, 25.0, -12.0, rnd.uniform(0, 60)))
        if k % 5 == 1:
            pos = (pos[0], pos[1], -0.0)
        sc.car(pos, h, speed, vel_deg=h + rnd.uniform(-40, 40),
               vz=rnd.choice((0.0, rnd.uniform(-3, 3))))
        if k == 0:
            sc.field(C_ANGLE, 0x8000)
        for d in (-3.0, 0.0, 4.999, 5.0, nextup(5.0), 15.0,
                  rnd.uniform(5, 80)):
            sc.op(OP_SS, 0, f32(d))
            sc.op(OP_SS, 1, f32(d))

    # -- the constructor and the destructor -----------------------------------
    sc.car((10.0, -4.0, 1.0), 30.0, 20.0)
    for flags in (0, 1, 3, 2):
        sc.tag("new, del %d" % flags)
        sc.op(OP_JUNK, flags)
        sc.op(OP_NEW)
        sc.op(OP_DUMP)
        sc.set(K_SOUND, flags & 1)
        sc.op(OP_DEL, flags)
        sc.op(OP_DUMP)
    for nulls in ((0,), (1,), (2,), (0, 1), (1, 2), (0, 2), (0, 1, 2)):
        sc.tag("del with no %s" % (nulls,))
        sc.op(OP_JUNK, 7)
        sc.op(OP_NEW)
        for n in nulls:
            sc.op(OP_NULLPID, n)
        sc.op(OP_DEL, 1)

    # The driver the rest of the script drives.
    sc.tag("new")
    sc.op(OP_JUNK, 9)
    sc.op(OP_NEW)
    sc.op(OP_DUMP)

    # -- the small methods -------------------------------------------------
    sc.tag("setters")
    sc.op(OP_SDS, 31.5, 2.5, 0.75, 1)
    sc.op(OP_GDS)
    sc.op(OP_GTTS)
    sc.op(OP_SDS, -7.25, 0.0, 0.0, 0)
    sc.op(OP_GDS)
    sc.op(OP_GTTS)
    sc.op(OP_SDS, 12.0, 1.0, 0.5, -3)
    sc.op(OP_DUMP)
    sc.op(OP_SSTP, -12.5, 99.25)
    sc.op(OP_GSTP)
    sc.op(OP_LOWGEAR)
    sc.op(OP_JEEVES)
    sc.op(OP_MAXTHR, 0.625)
    sc.op(OP_EBT, 1.75)
    sc.op(OP_DRVNUM)
    sc.field(C_DNUM, -2)
    sc.op(OP_DRVNUM)
    sc.field(C_DNUM, 0x7fff)
    sc.op(OP_DRVNUM)
    for s in BASE_SLOTS:
        sc.op(OP_BASE, s)
    sc.op(OP_DUMP)

    sc.tag("horn")
    for snd in (0, 1):
        sc.set(K_SOUND, snd)
        for honking in (0, 1, 5):
            sc.set(K_HONKING, honking)
            sc.op(OP_HONK, HONK_START)
            sc.op(OP_HONK, HONK_IS)
            sc.op(OP_HONK, HONK_STOP)
    sc.set(K_SOUND, 1)
    sc.set(K_HONKING, 0)

    sc.tag("set target")
    for n in (-128, -1, 0, 1, 2, 20, 21, 22, 127, 5):
        sc.op(OP_SRC, n)
        sc.op(OP_TARGET, 1)
        sc.op(OP_DUMP)
    sc.op(OP_TARGET, 0)
    sc.op(OP_DUMP)

    # -- GetError ----------------------------------------------------------
    sc.tag("get error")
    for k in range(60):
        h = rnd.uniform(-180, 180)
        sc.car((rnd.uniform(-300, 300), rnd.uniform(-300, 300), 0.0), h,
               rnd.uniform(-5, 40), vel_deg=h + rnd.uniform(-90, 90))
        fs = rnd.choice((1.0, nextup(1.0, -1), nextup(1.0), 0.0, -3.0,
                         rnd.uniform(-10, 50)))
        sc.field(C_FS, f32(fs))
        sc.poke(P_STPX, f32(rnd.uniform(-400, 400)))
        sc.poke(P_STPY, f32(rnd.uniform(-400, 400)))
        sc.op(OP_GETERR)
    # Straight ahead, behind, and on the car.
    sc.car((0.0, 0.0, 0.0), 0.0, 10.0)
    for x, y in ((100.0, 0.0), (-100.0, 0.0), (0.0, 0.0), (0.0, 100.0),
                 (-100.0, f32(-0.001)), (-100.0, f32(0.001))):
        sc.poke(P_STPX, x)
        sc.poke(P_STPY, y)
        sc.op(OP_GETERR)

    # -- the memories ------------------------------------------------------
    sc.tag("memories")
    sc.car((5.0, 5.0, 0.0), 45.0, 15.0, vel_deg=60.0)
    sc.poke(P_STPX, 80.0)
    sc.poke(P_STPY, -20.0)
    for which in range(3):
        for off in (PF_ITOTAL, PF_IAVG, PF_DTOTAL, PF_DAVG, PF_CUR, PF_PREV):
            sc.pid(which, off, f32(0.125 * (which + 1) + off * 0.01))
    sc.op(OP_DUMP)
    sc.op(OP_CLS)
    sc.op(OP_DUMP)
    sc.op(OP_ZS)
    sc.op(OP_DUMP)
    sc.poke(P_DS, -22.5)
    sc.op(OP_CT)
    sc.op(OP_DUMP)
    sc.op(OP_ZT)
    sc.op(OP_DUMP)

    # -- GetMovementIndex ---------------------------------------------------
    sc.tag("movement index")
    for mm in range(-2, 9):
        for cm in (0, 1, 2, 3, 4, 5):
            sc.field(C_MMODE, mm)
            sc.field(C_CMODE, cm)
            sc.op(OP_MOVIDX)
    sc.field(C_MMODE, 0x7fffffff)
    sc.op(OP_MOVIDX)
    sc.field(C_MMODE, -0x80000000)
    sc.op(OP_MOVIDX)

    # -- CalcSteerToPoint ---------------------------------------------------
    sc.tag("steer to point")
    for mm, cm in ((1, 2), (2, 3), (3, 2), (4, 3), (4, 2), (5, 4), (6, 2),
                   (0, 2)):
        for n in (0, 1, 2, 7):
            for dm in (0, 1):
                for fs in (0.0, 4.999, 5.0, 25.0, 50.0, 49.9, -8.0, 120.0,
                           170.0):
                    h = rnd.uniform(-180, 180)
                    sc.car((rnd.uniform(-50, 50), rnd.uniform(-50, 50), 2.0),
                           h, abs(fs) + 1.0, fs=f32(fs),
                           vel_deg=h + rnd.uniform(-30, 30), dmode=dm,
                           mmode=mm, cmode=cm)
                    sc.target(n)
                    sc.interp(rnd.uniform(-90, 90), rnd.uniform(-90, 90))
                    sc.op(OP_CSTP)
                    sc.op(OP_GSTP)

    # -- CalcThrottleAndBrake ----------------------------------------------
    sc.tag("throttle and brake")
    for k in range(120):
        sc.car(speed=rnd.uniform(0, 40))
        vm = rnd.uniform(0, 40)
        sc.field(C_VM, f32(vm))
        ds = rnd.choice((vm, -vm, vm + 3.0, rnd.uniform(-40, 40)))
        sc.poke(P_DS, f32(ds))
        gap = abs(abs(f32(ds)) - f32(vm))
        tol = rnd.choice((0.0, f32(gap), nextup(f32(gap), -1),
                          nextup(f32(gap), 1), rnd.uniform(0, 5)))
        sc.poke(P_TOL, f32(tol))
        sc.pid(PID_VEL, PF_CUR, f32(rnd.uniform(-6, 6)))
        sc.pid(PID_VEL, PF_DAVG, f32(rnd.choice(
            (2.0, -2.0, 2.5, -9.0, rnd.uniform(-3, 3)))))
        sc.pid(PID_VEL, PF_ITOTAL, f32(rnd.uniform(-8, 8)))
        sc.poke(P_THR, f32(rnd.choice((0.0, 1.0, rnd.uniform(0, 1)))))
        sc.poke(P_BRK, f32(rnd.choice((0.0, 1.0, rnd.uniform(0, 1)))))
        sc.op(OP_CTB)
    # The clamps at their edges: c at +-0.25 and the pedal at 1 and -0.94.
    sc.poke(P_TOL, 0.0)
    sc.poke(P_DS, 30.0)
    sc.field(C_VM, 10.0)
    for cur, thr, brk in ((2.5, 0.0, 0.0), (-2.5, 0.0, 0.0), (3.0, 0.9, 0.0),
                          (-3.0, 0.0, 0.8), (0.0, 0.0, 0.0), (0.0, 0.5, 0.5),
                          (-1.0, 0.0, 0.84), (-1.0, 0.0, 0.85),
                          (1.0, 0.9, 0.0), (1.0, 0.95, 0.0)):
        sc.pid(PID_VEL, PF_CUR, cur)
        sc.pid(PID_VEL, PF_DAVG, 0.0)
        sc.pid(PID_VEL, PF_ITOTAL, 0.0)
        sc.poke(P_THR, thr)
        sc.poke(P_BRK, brk)
        sc.op(OP_CTB)

    # -- Drive -------------------------------------------------------------
    drive_scenarios(sc, rnd)
    return sc


def fresh(sc, junk):
    """A new driver: the old one deleted without its memory freed."""
    sc.op(OP_DEL, 0)
    sc.op(OP_JUNK, junk)
    sc.op(OP_NEW)


ROUNDING_SEEDS = (133, 161, 163, 15632)


def rounding_drive(sc, seed):
    """One step that swaps to the body's error, so that the wheel's target
    is neither clamped nor (in a long enough step) rate-limited: an even
    seed on a speed-table index, an odd one on a fixed index with a steering
    ratio of hundreds, which brings the wheel angle's last bits up into the
    BAMs."""
    r = random.Random(seed)
    fresh(sc, 14)
    a = r.uniform(0.5, 25.0)
    if seed & 1:
        mm, cm, cs, dt = 2, 2, r.uniform(200.0, 700.0), r.choice((2.0, 5.0))
    else:
        mm, cm, cs, dt = r.choice((1, 5, 6)), 2, 0.875, 1.0 / 30.0
    sc.car((0.0, 0.0, 0.0), a, r.uniform(6.0, 40.0),
           vel_deg=-r.uniform(0.5, 25.0), dmode=r.choice((0, 1)), mmode=mm,
           cmode=cm)
    sc.op(OP_CTI, f32(cs))
    sc.target(3)
    sc.interp(60.0, 0.0)
    sc.pid(0, PF_CUR, f32(r.uniform(-0.5, 0.5)))
    sc.pid(0, PF_ITOTAL, f32(r.uniform(-1.0, 1.0)))
    sc.pid(0, PF_DTOTAL, f32(r.uniform(-1.0, 1.0)))
    sc.op(OP_SDS, 25.0, 1.0, 0.0, 1)
    sc.op(OP_DRIVE, f32(dt))
    sc.op(OP_DUMP)


def drive_scenarios(sc, rnd):
    # A run of steps on one car, the dump after each.
    sc.tag("drive, a run")
    fresh(sc, 11)
    sc.car((0.0, 0.0, 0.0), 10.0, 18.0, vel_deg=14.0)
    sc.target(6)
    sc.interp(40.0, 12.0)
    sc.op(OP_SDS, 30.0, 2.0, 0.5, 1)
    for i in range(12):
        sc.op(OP_DRIVE, f32(1.0 / 30.0))
        sc.op(OP_DUMP)

    # Every combination of wheels down.
    sc.tag("drive, the wheels")
    for m in range(16):
        fresh(sc, m)
        sc.car((3.0, 4.0, 0.0), -20.0, 12.0, vel_deg=-5.0,
               wheels=[(m >> i) & 1 for i in range(4)])
        sc.target(4)
        sc.interp(30.0, -6.0)
        sc.set(K_YAW, f32(0.3 - 0.05 * m))
        sc.op(OP_SDS, 20.0, 1.0, 0.25, 1)
        sc.op(OP_DRIVE, f32(1.0 / 30.0))
        sc.op(OP_DUMP)

    # The collisions: none, one that isn't two cars, the second of three.
    sc.tag("drive, collisions")
    for n, mask in ((0, 0), (1, 0), (1, 1), (3, 2), (3, 6), (3, 0), (-1, 1),
                    (4, 8)):
        fresh(sc, 20 + n)
        sc.car((0.0, 0.0, 0.0), 0.0, 15.0, vel_deg=3.0)
        sc.target(3)
        sc.interp(25.0, 5.0)
        sc.set(K_NCOLL, n)
        sc.set(K_TWOCAR, mask)
        sc.op(OP_SDS, 20.0, 0.0, 0.0, 1)
        sc.op(OP_DRIVE, f32(1.0 / 30.0))
        sc.op(OP_DRIVE, f32(1.0 / 30.0))
        sc.op(OP_DUMP)
    sc.set(K_NCOLL, 0)
    sc.set(K_TWOCAR, 0)

    # The gears: the desired speed's sign and size, the car's speed about
    # the latch's edges, with the latch either way.
    sc.tag("drive, gears")
    dss = (0.0, 1.0, nextup(2.0, -1), 2.0, nextup(2.0), 15.0, -1.0,
           nextup(-2.0, 1), -2.0, nextup(-2.0, -1), -15.0)
    spds = (-12.0, -7.0, nextup(-7.0, -1), nextup(-7.0), -3.0, -2.0,
            nextup(-2.0, -1), nextup(-2.0), 0.0, 1.5, nextup(2.0, -1), 2.0,
            nextup(2.0), 5.0, 7.0, nextup(7.0, -1), nextup(7.0), 12.0)
    k = 0
    for ds in dss:
        for spd in spds:
            for latch in (0, 1):
                fresh(sc, k & 31)
                k += 1
                sc.car((0.0, 0.0, 0.0), 30.0, abs(spd),
                       fs=f32(spd if spd else -0.0) if spd < 0
                       else f32(spd * 0.97), vel_deg=35.0)
                sc.target(3)
                sc.interp(20.0, 15.0)
                sc.op(OP_SDS, f32(ds), 0.5, 0.0, 1)
                sc.poke(P_LATCH, latch)
                sc.op(OP_DRIVE, f32(1.0 / 60.0))
                sc.op(OP_DUMP)

    # The time to the speed, about 0.001 either way, and its countdown.
    sc.tag("drive, the time")
    for t in (0.0, 0.001, nextup(0.001), nextup(0.001, -1), -0.001,
              nextup(-0.001, -1), 0.5, -0.5, 0.01, 0.0334, 0.0333, 3.0):
        fresh(sc, 3)
        sc.car((0.0, 0.0, 0.0), 0.0, 10.0)
        sc.target(3)
        sc.interp(30.0, 0.0)
        sc.op(OP_SDS, 25.0, f32(t), 0.0, 1)
        sc.op(OP_DRIVE, f32(1.0 / 30.0))
        sc.op(OP_DUMP)

    # The e-brake timer and the speed about 20 mph; not allowed the pedals.
    sc.tag("drive, e-brake")
    ebs = (0.0, 0.01, f32(1.0 / 30.0), nextup(f32(1.0 / 30.0)), 1.0, -1.0)
    for eb in ebs:
        for spd in (8.940545, nextup(8.940545), nextup(8.940545, -1), 20.0,
                    -20.0, 0.0):
            for ok in (1, 0):
                fresh(sc, 5)
                sc.car((0.0, 0.0, 0.0), 0.0, abs(spd),
                       fs=f32(spd) if spd < 0 else f32(spd))
                sc.target(3)
                sc.interp(30.0, 2.0)
                sc.op(OP_SDS, 30.0, 1.0, 0.0, ok)
                sc.op(OP_EBT, f32(eb))
                sc.op(OP_DRIVE, f32(1.0 / 30.0))
                sc.op(OP_DUMP)

    # The steering wheel about 180 degrees, and dt under 0.0001.
    sc.tag("drive, the wheel and dt")
    for steer in (0, 1, 0x7fff, 0x8000, 0x8001, 0xffff, 0x2000, 0xe000,
                  0x4000, 0xc000):
        for dt in (1.0 / 30.0, 0.0001, nextup(0.0001, -1), 0.0, 0.00001):
            fresh(sc, 6)
            sc.car((0.0, 0.0, 0.0), 0.0, 20.0, vel_deg=2.0, mmode=2)
            sc.target(3)
            sc.interp(30.0, -8.0)
            sc.poke(P_STEER, steer)
            sc.op(OP_SDS, 25.0, 1.0, 0.0, 1)
            sc.op(OP_DRIVE, f32(dt))
            sc.op(OP_DUMP)

    # A time left of -0 in a step of 0: the countdown's -0 is not below 0.
    for t in (-0.0, 0.0):
        fresh(sc, 6)
        sc.car((0.0, 0.0, 0.0), 0.0, 20.0, vel_deg=2.0)
        sc.target(3)
        sc.interp(30.0, -8.0)
        sc.op(OP_SDS, 25.0, Fb(fb(t)), 0.0, 1)
        sc.op(OP_DRIVE, 0.0)
        sc.op(OP_DUMP)

    # The swap: the errors' signs, and |v - h| about the counter's diff.
    sc.tag("drive, the swap")
    for mm, cm in ((1, 2), (2, 3), (4, 3), (5, 2)):
        for h, va, stp in ((0.0, 5.0, (50.0, 10.0)), (0.0, -5.0, (50.0, 10.0)),
                           (0.0, 20.0, (50.0, 1.0)), (0.0, 0.0, (50.0, 0.0)),
                           (10.0, 10.0, (50.0, 0.0)), (0.0, 60.0, (50.0, 30.0)),
                           (0.0, 0.03, (50.0, 0.04)),
                           (0.0, 0.1, (50.0, 0.1))):
            for fs in (4.0, 20.0):
                fresh(sc, 8)
                sc.car((0.0, 0.0, 0.0), h, fs + 1.0, fs=fs, vel_deg=va,
                       mmode=mm, cmode=cm)
                sc.target(3)
                sc.interp(*stp)
                sc.op(OP_SDS, 25.0, 1.0, 0.0, 1)
                sc.op(OP_DRIVE, f32(1.0 / 30.0))
                sc.op(OP_DRIVE, f32(1.0 / 30.0))
                sc.op(OP_DUMP)

    # The swap's tests met exactly: |v - h| the counter's diff (10 BAMs
    # against 0, 13 against 3), and 2|v| = |h| (22 and 11, 40 and 20), at a
    # forward speed of 5, where the body's error is taken anyway, and over.
    sc.tag("drive, exact swaps")
    for bh, bv in ((10, 0), (13, 3), (22, 11), (22, 10.7), (22, 11.3),
                   (40, 20), (40, 20.25), (0, 5), (0, 0)):
        for fs in (nextup(5.0, -1), 5.0, 20.0):
            fresh(sc, 10)
            sc.car((0.0, 0.0, 0.0), bh * 360.0 / 65536.0, fs + 1.0, fs=fs,
                   vel_deg=bv * 360.0 / 65536.0)
            sc.target(3)
            sc.interp(50.0, 0.0)
            sc.op(OP_SDS, 25.0, 1.0, 0.0, 1)
            sc.op(OP_DRIVE, f32(1.0 / 30.0))
            sc.op(OP_DUMP)

    # Sliding sideways: no forward speed, of either sign, and some
    # magnitude.
    sc.tag("drive, sideways")
    for fs in (0.0, -0.0):
        for ds in (20.0, -20.0, 1.0):
            fresh(sc, 12)
            sc.car((0.0, 0.0, 0.0), 0.0, 10.0, fs=fs, vel_deg=90.0,
                   mmode=2)
            sc.target(3)
            sc.interp(30.0, 3.0)
            sc.op(OP_SDS, ds, 1.0, 0.0, 1)
            sc.op(OP_EBT, 1.0)
            sc.op(OP_DRIVE, f32(1.0 / 30.0))
            sc.op(OP_DUMP)

    # The e-brake on and running out.
    sc.tag("drive, e-brake run")
    fresh(sc, 13)
    sc.car((0.0, 0.0, 0.0), 0.0, 20.0, vel_deg=1.0)
    sc.target(3)
    sc.interp(30.0, 1.0)
    sc.op(OP_SDS, 25.0, 1.0, 0.0, 1)
    sc.op(OP_EBT, 0.05)
    for i in range(4):
        sc.op(OP_DRIVE, f32(1.0 / 30.0))
        sc.op(OP_DUMP)

    # The steer-to point over 200 m off, and exactly 200.
    sc.tag("drive, far")
    for x in (199.0, 200.0, nextup(200.0), 250.0):
        fresh(sc, 4)
        sc.car((0.0, 0.0, 0.0), 0.0, 20.0)
        sc.target(3)
        sc.interp(x, 0.0)
        sc.op(OP_SDS, 25.0, 1.0, 0.0, 1)
        sc.op(OP_DRIVE, f32(1.0 / 30.0))
        sc.op(OP_DUMP)

    # No front wheel down: the yaw rate turned to degrees, and turned back
    # by the latch's brake and by reverse.
    sc.tag("drive, in the air")
    k = 0
    for wheels in ((0, 0, 1, 1), (0, 0, 0, 1), (0, 0, 0, 0)):
        for ds in (20.0, -20.0, 1.0):
            for spd in (12.0, -9.0):
                for yaw in (0.1, 0.47, -0.62, 0.9):
                    fresh(sc, k & 31)
                    k += 1
                    sc.car((0.0, 0.0, 0.0), 15.0, abs(spd), fs=f32(spd * 0.97),
                           vel_deg=12.0, wheels=wheels)
                    sc.target(3)
                    sc.interp(30.0, 5.0)
                    sc.set(K_YAW, f32(yaw))
                    sc.op(OP_SDS, ds, 1.0, 0.0, 1)
                    sc.op(OP_DRIVE, f32(1.0 / 30.0))
                    sc.op(OP_DUMP)

    # A fixed index fast enough for the range table's last rows, the wheel
    # free to move a long way in a long step.
    sc.tag("drive, fast and fixed")
    for mm, cm in ((2, 2), (4, 3), (3, 2)):
        for spd in (100.0, 107.0, 115.0, 125.0, 140.0, 160.0, 175.0):
            for dt in (1.0 / 30.0, 0.5, 2.0, 10.0):
                fresh(sc, 15)
                sc.car((0.0, 0.0, 0.0), 0.0, spd, vel_deg=3.0, mmode=mm,
                       cmode=cm)
                sc.target(3)
                sc.interp(60.0, 40.0 if dt < 1.0 else -40.0)
                sc.op(OP_SDS, 25.0, 1.0, 0.0, 1)
                sc.op(OP_DRIVE, f32(dt))
                sc.op(OP_DUMP)

    # A steering ratio big enough to take the wheel's angle past what a word
    # holds in BAMs x 360, where `cvt.w.s` saturates.
    sc.tag("drive, huge steering")
    for cs in (300.0, 1000.0, 5000.0, -5000.0, 40000.0):
        for stp, steer in (((40.0, 30.0), 0), ((40.0, -30.0), 0x2000),
                           ((40.0, 2.0), 0xe000)):
            fresh(sc, 16)
            sc.car((0.0, 0.0, 0.0), 0.0, 20.0, vel_deg=2.0, mmode=2)
            sc.op(OP_CTI, cs)
            sc.target(3)
            sc.interp(*stp)
            sc.poke(P_STEER, steer)
            sc.op(OP_SDS, 25.0, 1.0, 0.0, 1)
            sc.op(OP_DRIVE, 1.0)
            sc.op(OP_DUMP)
            sc.op(OP_DRIVE, f32(1.0 / 30.0))
            sc.op(OP_DUMP)
    sc.op(OP_CTI, 0.875)

    # The order of the sums in the steering and its wheel angle shows only
    # where it moves the angle across a BAM; these steps, found by
    # searching rounding_drive's seeds, are ones where it does.
    sc.tag("drive, rounding")
    for seed in ROUNDING_SEEDS:
        rounding_drive(sc, seed)
    sc.op(OP_CTI, 0.875)

    # Random drives: every movement mode, driver mode, speeds of both
    # signs, a few steps each.
    sc.tag("drive, random")
    for k in range(150):
        fresh(sc, k & 31)
        mm = rnd.choice((0, 1, 2, 3, 4, 5, 6, 7))
        cm = rnd.choice((2, 3, 3, 4))
        h = rnd.uniform(-180, 180)
        spd = rnd.choice((rnd.uniform(-15, 50), rnd.uniform(0, 70),
                          rnd.uniform(-3, 3)))
        wheels = [1, 1, 1, 1] if rnd.random() < 0.7 else \
            [rnd.randrange(2) for _ in range(4)]
        sc.car((rnd.uniform(-300, 300), rnd.uniform(-300, 300),
                rnd.uniform(-5, 5)), h, abs(spd),
               fs=f32(spd * rnd.uniform(0.8, 1.0)),
               vel_deg=h + rnd.uniform(-35, 35), wheels=wheels,
               dmode=rnd.choice((0, 1, 1, 2)), mmode=mm, cmode=cm)
        sc.op(OP_CTI, f32(rnd.choice((0.875, 1.0, 0.6))))
        sc.target(rnd.choice((0, 1, 2, 5, 12)))
        a = math.radians(h + rnd.uniform(-70, 70))
        d = rnd.uniform(5, 120)
        sc.interp(d * math.cos(a), d * math.sin(a))
        sc.set(K_YAW, f32(rnd.uniform(-1.5, 1.5)))
        sc.poke(P_STEER, rnd.randrange(0x10000))
        sc.op(OP_SDS, f32(rnd.choice((rnd.uniform(-20, 60), 0.0, 1.0))),
              f32(rnd.choice((0.0, rnd.uniform(0, 3)))),
              f32(rnd.choice((0.0, rnd.uniform(0, 4)))),
              rnd.choice((1, 1, 1, 0)))
        if rnd.random() < 0.2:
            sc.op(OP_EBT, f32(rnd.uniform(0, 2)))
        if rnd.random() < 0.2:
            sc.set(K_NCOLL, rnd.randrange(4))
            sc.set(K_TWOCAR, rnd.randrange(16))
        for i in range(rnd.choice((1, 3, 6))):
            sc.op(OP_DRIVE, f32(rnd.choice((1.0 / 30.0, 1.0 / 60.0,
                                            rnd.uniform(0, 0.1)))))
            if rnd.random() < 0.3:
                sc.interp(rnd.uniform(-100, 100), rnd.uniform(-100, 100))
        sc.op(OP_DUMP)
        sc.set(K_NCOLL, 0)
        sc.set(K_TWOCAR, 0)
    sc.op(OP_CTI, 0.875)

    sc.tag("globals")
    sc.op(OP_STATIC)


# ================================================================ the model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        e.stub_bware()
        self.heap = []                  # (addr, span, label)
        self.vals = dict.fromkeys(range(9), 0)
        for base, n in ((PD, 0x1000), (CAR, 0x1000), (CTI, 0x1000),
                        (BODY, 0x1000), (SRC, 0x1000), (SCR, 0x1000)):
            e.mem[base:base + n] = bytes(n)
        e.put32(CAR + 12, CTI)
        e.put32(CAR + 52, BODY)
        self.stubs()
        e.call(F["sinit"])

    def emit(self, s):
        self.out.append(s)

    def w(self, a):
        return self.e.u32(a)

    def s16(self, a):
        v = self.e.u16(a)
        return v - 0x10000 if v & 0x8000 else v

    def s8(self, a):
        v = self.e.u8(a)
        return v - 0x100 if v & 0x80 else v

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        for base, name in ((PD, "pd"), (CAR, "car"), (CS, "cs"),
                           (BODY, "body"), (SOUND, "snd"), (SRC, "src"),
                           (CTI, "cti")):
            if a == base:
                return name
        if PD < a < PD + PD_SIZE:
            return "pd+%d" % (a - PD)
        if COLL <= a < COLL + 16 * 64 and (a - COLL) % 16 == 0:
            return "c%d" % ((a - COLL) // 16)
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

        def dt_ctor(em):
            t = arg(0)
            self.emit("  dt init %s" % self.label(t))
            e.mem[t:t + DT_SIZE] = bytes(DT_SIZE)
            return t

        def dt_clear(em):
            self.emit("  dt clear %s %s %s" % (self.label(arg(0)),
                                                self.label(arg(1)),
                                                fx(e.fpr[12])))

        def dt_assign(em):
            d, s = arg(0), arg(1)
            self.emit("  dt assign %s %s" % (self.label(d), self.label(s)))
            e.mem[d:d + DT_SIZE] = e.mem[s:s + DT_SIZE]
            return d

        def resample(em):
            self.emit("  resample %s %s" % (self.label(arg(0)),
                                            self.label(arg(1))))

        def interp(em):
            out = arg(2)
            self.emit("  interp %s %s %s" % (self.label(arg(0)),
                                             self.label(arg(1)),
                                             fx(e.fpr[12])))
            for k, key in enumerate((K_IPX, K_IPY, K_IPZ, K_IPW)):
                e.put32(out + 4 * k, self.vals[key])
            return 1

        def get_coll(em):
            i = s32(arg(1))
            self.emit("  getcoll %s %d" % (self.label(arg(0)), i))
            return COLL + 16 * i

        def two_car(em):
            c = arg(0)
            i = (c - COLL) // 16
            r = (self.vals[K_TWOCAR] >> i) & 1
            self.emit("  twocar %s -> %d" % (self.label(c), r))
            return r

        def yaw(em):
            self.emit("  yaw %s -> %s" % (self.label(arg(0)),
                                          fx(self.vals[K_YAW])))
            e.fpr[0] = self.vals[K_YAW]

        def snd_start(em):
            self.emit("  honk start %s" % self.label(arg(0)))

        def snd_stop(em):
            self.emit("  honk stop %s" % self.label(arg(0)))

        def snd_is(em):
            self.emit("  honk is %s -> %d" % (self.label(arg(0)),
                                              s32(self.vals[K_HONKING])))
            return self.vals[K_HONKING]

        e.stub(BMALLOC, malloc)
        e.stub(BDELETE, free)
        e.stub(BFREE, free)
        e.stub(DT_CTOR, dt_ctor)
        e.stub(DT_CLEAR, dt_clear)
        e.stub(DT_ASSIGN, dt_assign)
        e.stub(DT_RESAMPLE, resample)
        e.stub(DT_INTERP, interp)
        e.stub(GET_COLLISION, get_coll)
        e.stub(TWO_CAR, two_car)
        e.stub(YAW_ALWAYS, yaw)
        e.stub(SND_START, snd_start)
        e.stub(SND_STOP, snd_stop)
        e.stub(SND_IS, snd_is)

    # ---- the dump --------------------------------------------------------

    def words(self, a, n):
        return " ".join(fx(self.w(a + 4 * k)) for k in range(n))

    def vtname(self, v):
        return {PSYCHO_VT: "psycho", CARDRIVER_VT: "cardriver"}.get(
            v, "%08x" % v)

    def average(self, name, a):
        e = self.e
        n = e.u8(a)
        self.emit("  %s %d %d %d %s %s %s" % (
            name, n, e.u8(a + 1), e.u8(a + 2), fx(self.w(a + 4)),
            fx(self.w(a + 8)), self.words(self.w(a + 12), n)))

    def dump(self):
        w, m = self.w, PD
        self.emit("pd vt %s steer %d thr %s brk %s eb %s gear %d sport %s "
                  "nitro %d dtn %d"
                  % (self.vtname(w(m + 556)), self.e.u16(m + 528),
                     fx(w(m + 532)), fx(w(m + 536)), fx(w(m + 540)),
                     s32(w(m + 544)), fx(w(m + 548)), s32(w(m + 552)),
                     self.s8(m)))
        self.emit("pd car %s stp %s %s mt %s ds %s t %s tol %s ok %d ebt %s "
                  "latch %d"
                  % (self.label(w(m + 560)), fx(w(m + 564)), fx(w(m + 568)),
                     fx(w(m + 572)), fx(w(m + 576)), fx(w(m + 580)),
                     fx(w(m + 584)), s32(w(m + 588)), fx(w(m + 592)),
                     s32(w(m + 600))))
        for name, off in (("body", 604), ("head", 608), ("vel", 612)):
            p = w(m + off)
            self.emit("pid %s %s" % (name, self.label(p)))
            if p == 0:
                continue
            self.emit("  err %s %s" % (fx(w(p + 32)), fx(w(p + 36))))
            self.average("int", p)
            self.average("der", p + 16)
        self.emit("g warned %d" % s32(w(GP + WARNED_GP)))

    def static(self):
        e, w = self.e, self.w
        self.emit("g diff %s warned %d" % (fx(w(GP + COUNTER_DIFF_GP)),
                                           s32(w(GP + WARNED_GP))))
        for i, t in enumerate(TABLES):
            n = s32(w(t + 4))
            self.emit("table %d n %d min %s max %s mul %s data %s"
                      % (i, n, fx(w(t + 8)), fx(w(t + 12)), fx(w(t + 16)),
                         self.words(w(t), n)))
        for i, a in enumerate(WEIGHTS):
            self.emit("weights %d %s" % (i, self.words(a, 5)))

    # ---- the run ---------------------------------------------------------

    def vcall(self, slot, *args):
        e = self.e
        vt = self.w(PD + 556)
        delta = self.s16(vt + slot)
        fn = self.w(vt + slot + 4)
        return e.call(fn, (PD + delta) & M32, *args)

    def run(self, sc):
        e, w = self.e, self.w
        tags = sc.tags
        for o in sc.ops:
            code, a = o[0], o[1:]
            if code == OP_TAG:
                self.emit("[%s]" % tags[a[0]])
            elif code == OP_JUNK:
                e.mem[PD:PD + PD_SIZE] = bytes(
                    [(0xa1 + a[0] + 7 * k) & 0xff for k in range(PD_SIZE)])
            elif code == OP_FIELD:
                off, kind = CF[a[0]]
                if kind == "h":
                    e.write(CAR + off, struct.pack("<H", a[1] & 0xffff))
                elif kind == "b":
                    e.write(CAR + off, bytes([a[1] & 0xff]))
                else:
                    e.put32(CAR + off, a[1])
            elif code == OP_CTI:
                e.put32(CTI + 768, a[0])
            elif code == OP_SET:
                self.vals[a[0]] = a[1] & M32
                if a[0] == K_NCOLL:
                    e.write(BODY + 18, bytes([a[1] & 0xff]))
                elif a[0] == K_SOUND:
                    e.put32(CAR + 2132, SOUND if a[1] else 0)
            elif code == OP_SRC:
                e.mem[SRC:SRC + DT_SIZE] = bytes(
                    [(0x30 + 5 * k) & 0xff for k in range(DT_SIZE)])
                e.write(SRC, bytes([a[0] & 0xff]))
            elif code == OP_NEW:
                self.emit("new")
                r = e.call(F["ctor"], PD, CAR)
                self.emit("new -> %s" % self.label(r))
            elif code == OP_DEL:
                self.emit("del %d" % a[0])
                self.vcall(8, a[0])
            elif code == OP_DRIVE:
                self.emit("drive %s" % fx(a[0]))
                e.fpr[12] = a[0]
                self.vcall(16)
            elif code == OP_SDS:
                e.fpr[12], e.fpr[13], e.fpr[14] = a[0], a[1], a[2]
                self.vcall(56, a[3])
            elif code == OP_TARGET:
                self.emit("target %s" % ("src" if a[0] else "null"))
                self.vcall(64, SRC if a[0] else 0)
            elif code == OP_SSTP:
                e.put32(SCR, a[0])
                e.put32(SCR + 4, a[1])
                self.vcall(72, SCR)
            elif code == OP_DRVNUM:
                self.emit("drvnum -> %d" % self.vcall(80))
            elif code == OP_HONK:
                r = self.vcall((88, 96, 104)[a[0]])
                if a[0] == HONK_IS:
                    self.emit("honking -> %d" % r)
            elif code == OP_ZS:
                self.vcall(120)
            elif code == OP_CLS:
                self.vcall(128)
            elif code == OP_GDS:
                self.vcall(136)
                self.emit("gds -> %s" % fx(e.fpr[0]))
            elif code == OP_GTTS:
                self.vcall(144)
                self.emit("gtts -> %s" % fx(e.fpr[0]))
            elif code == OP_GSTP:
                r = self.vcall(160)
                self.emit("gstp -> %s %s" % (self.label(r),
                                             self.words(r, 2)))
            elif code == OP_LOWGEAR:
                self.vcall(48)
            elif code == OP_BASE:
                e.fpr[0] = 0x5a5a5a5a
                e.reg[2] = 0x5a5a5a5a
                if a[0] == 112:
                    self.vcall(a[0], SRC)
                    self.emit("base %d -> %s" % (a[0], fx(e.fpr[0])))
                else:
                    self.vcall(a[0], 3)
                    self.emit("base %d" % a[0])
            elif code == OP_ZT:
                e.call(F["zeroThrottle"], PD)
            elif code == OP_CT:
                e.call(F["clearThrottle"], PD)
            elif code == OP_GETERR:
                e.mem[SCR:SCR + 8] = bytes([0x5a]) * 8
                r = e.call(F["getError"], PD, SCR, SCR + 4)
                self.emit("geterr -> %d %s" % (r, self.words(SCR, 2)))
            elif code == OP_MOVIDX:
                self.emit("movidx -> %d" % e.call(F["moveIndex"], PD))
            elif code == OP_CSTP:
                e.call(F["calcSteerTo"], PD)
            elif code == OP_CTB:
                e.mem[SCR:SCR + 8] = bytes([0x5a]) * 8
                e.call(F["calcThrottle"], PD, SCR, SCR + 4)
                self.emit("ctb -> %s" % self.words(SCR, 2))
            elif code == OP_JEEVES:
                e.call(F["jeeves"], PD)
            elif code == OP_MAXTHR:
                e.fpr[12] = a[0]
                e.call(F["maxThrottle"], PD)
            elif code == OP_EBT:
                e.fpr[12] = a[0]
                e.call(F["ebrakeTimer"], PD)
            elif code == OP_WRAP:
                e.call(F["wrap"], a[0] & 0xffff)
                self.emit("wrap %d -> %s" % (a[0] & 0xffff, fx(e.fpr[0])))
            elif code == OP_SS:
                e.mem[SCR:SCR + 16] = bytes([0x5a]) * 16
                e.fpr[12] = a[1]
                e.call(F["ssVelocity" if a[0] else "ssVector"], SCR, CAR)
                # The w lane is a stack word the image never writes.
                self.emit("ss %d %s -> %s" % (a[0], fx(a[1]),
                                              self.words(SCR, 3)))
            elif code == OP_TABLE:
                e.fpr[12] = a[1]
                e.call(TABLE_GET, TABLES[a[0]])
                self.emit("table %d %s -> %s" % (a[0], fx(a[1]),
                                                 fx(e.fpr[0])))
            elif code == OP_POKE:
                if a[0] == P_STEER:
                    e.write(PD + a[0], struct.pack("<H", a[1] & 0xffff))
                else:
                    e.put32(PD + a[0], a[1])
            elif code == OP_PID:
                e.put32(w(PD + PIDS[a[0]]) + a[1], a[2])
            elif code == OP_NULLPID:
                e.put32(PD + PIDS[a[0]], 0)
            elif code == OP_DUMP:
                self.dump()
            elif code == OP_STATIC:
                self.static()
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


def build_harness(tmp, name="psychodriver_test"):
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
    return (name, PDC, before, after)


MUTATIONS = [
    # -- the data -----------------------------------------------------------
    M("d-prop0", "0.275f, 0.204f", "0.276f, 0.204f"),
    M("d-prop9", "0.043f, 0.04f,", "0.043f, 0.041f,"),
    M("d-der", "0.156f, 0.123f", "0.157f, 0.123f"),
    M("d-int", "0.21f, 0.244f", "0.21f, 0.245f"),
    M("d-steerto", "40.3f, 45.8f", "40.3f, 45.9f"),
    M("d-range", "6.0f, 4.5f, 4.2f", "6.0f, 4.5f, 4.3f"),
    M("d-speed", "0.14f, 0.1f, 0.1f, 0.1f, 0.1f",
      "0.14f, 0.1f, 0.1f, 0.1f, 0.11f"),
    M("d-curve", "0.24f, 0.53f", "0.24f, 0.54f"),
    M("d-wprop", "0.9f, 1.0f, 0.8f, 1.0f, 0.5f", "0.9f, 1.0f, 0.8f, 1.0f, 0.6f"),
    M("d-wint", "0.2f, 0.0f, 0.1f, 0.0f, 0.0f", "0.2f, 0.0f, 0.1f, 0.0f, 0.1f"),
    M("d-wder", "0.3f, 0.08f, 0.18f, 0.0f, 0.5f",
      "0.3f, 0.08f, 0.18f, 0.0f, 0.4f"),
    M("d-ahead3", "0.55f, 0.4f, 0.35f, 0.3f, 1.0f",
      "0.55f, 0.4f, 0.35f, 0.31f, 1.0f"),
    M("d-ahead4", "0.55f, 0.4f, 0.35f, 0.3f, 1.0f",
      "0.55f, 0.4f, 0.35f, 0.3f, 1.1f"),

    # -- the constants --------------------------------------------------------
    M("k-diff", "0.000958738034f", "0.00095f"),
    M("k-bam", "9.58738e-05f", "9.5874e-05f"),
    M("k-pi", "PD_WRAP_PI          3.14159f", "PD_WRAP_PI          3.1416f"),
    M("k-2pi", "6.28318f", "6.2832f"),
    M("k-mindt", "PD_MIN_DT           0.0001f", "PD_MIN_DT           0.001f"),
    M("k-dmgain", "PD_DRIVER_MODE_GAIN 1.2f", "PD_DRIVER_MODE_GAIN 1.25f"),
    M("k-maxsteer", "0.7853982f", "0.78f"),
    M("k-teps", "PD_TIME_EPSILON     0.001f", "PD_TIME_EPSILON     0.002f"),
    M("k-tgain", "PD_TIME_GAIN        0.3f", "PD_TIME_GAIN        0.31f"),
    M("k-d2r", "0.017453294f", "0.0175f"),
    M("k-r2d", "57.29578f", "57.3f"),
    M("k-ebspeed", "8.940545f", "8.94f"),
    M("k-stgain", "PD_STEER_TO_GAIN    1.2f", "PD_STEER_TO_GAIN    1.25f"),
    M("k-kp", "PD_THROTTLE_KP      0.1f", "PD_THROTTLE_KP      0.11f"),
    M("k-kd", "PD_THROTTLE_KD      0.01f", "PD_THROTTLE_KD      0.011f"),
    M("k-ki", "PD_THROTTLE_KI      0.02f", "PD_THROTTLE_KI      0.021f"),
    M("k-minpedal", "(-0.94f)", "(-0.95f)"),
    M("k-bam2deg", "0.0054931640625f", "0.0055f"),
    M("k-name", "\"Phsycho Body Pid\"", "\"Psycho Body Pid\""),
    M("k-pool", "PD_POOL          16", "PD_POOL          15"),

    # -- the start-up code ------------------------------------------------------
    M("si-diff", "fPsychoCounterDiff = PD_COUNTER_DIFF;",
      "fPsychoCounterDiff = 0.0f;"),
    M("si-n", "PidProportionalData, 10, 0.0f, 160.0f);",
      "PidProportionalData, 9, 0.0f, 160.0f);"),
    M("si-max", "PidSteerToData, 10, 0.0f, 160.0f);",
      "PidSteerToData, 10, 0.0f, 150.0f);"),
    M("si-swap", "table_init(&PidDerivativeTable, PidDerivativeData,",
      "table_init(&PidDerivativeTable, PidIntegralData,"),
    M("si-range", "PsychoSteeringRangeData, 10,", "PsychoSteeringRangeData, 9,"),
    M("si-speed", "PsychoSteeringSpeedData, 10,", "PsychoSteeringSpeedData, 9,"),
    M("si-curve", "PsychoSteeringCurveData, 6,", "PsychoSteeringCurveData, 5,"),

    # -- max.s, min.s and RadianWrap --------------------------------------------
    M("maxs", "return fs < ft ? ft : fs;", "return fs < ft ? fs : ft;"),
    M("mins", "return fs < ft ? fs : ft;", "return fs < ft ? ft : fs;"),
    M("rw-cast", "(float)(int32_t)bam * PD_BAM_TO_RADIANS",
      "(float)(int16_t)bam * PD_BAM_TO_RADIANS"),
    M("rw-le", "if (PD_WRAP_PI < f)", "if (PD_WRAP_PI <= f)"),
    M("rw-sub", "f = f - PD_WRAP_TWO_PI;", "f = f + PD_WRAP_TWO_PI;"),
    M("rw-neg", "else if (f < -PD_WRAP_PI)", "else if (f < PD_WRAP_PI)"),
    M("rw-dead", "f = f + PD_WRAP_TWO_PI;", "f = f - PD_WRAP_TWO_PI;"),

    # -- SteerStraight ----------------------------------------------------------
    M("ssv-max", "d = max_s(5.0f, dist);", "d = dist;"),
    M("ssv-angle", "bSinCos(&s, &c, car->State.Angle);",
      "bSinCos(&c, &s, car->State.Angle);"),
    M("ssv-x", "out->x = c * d + p->x;", "out->x = s * d + p->x;"),
    M("ssv-y", "out->y = s * d + p->y;", "out->y = s * d - p->y;"),
    M("ssv-z", "out->z = 0.0f * d + p->z;", "out->z = p->z;"),
    M("ssl-max", "&car->State.Velocity, max_s(5.0f, dist));",
      "&car->State.Velocity, dist);"),
    M("ssl-x", "out->x = n.x + p->x;", "out->x = n.y + p->x;"),
    M("ssl-z", "out->z = n.z + p->z;", "out->z = p->z;"),

    # -- the constructor -------------------------------------------------------
    M("ni-size", "bMalloc((int)sizeof(PidError), name, 0,",
      "bMalloc((int)sizeof(PidError) + 4, name, 0,"),
    M("ni-flags", "bMalloc((int)sizeof(PidError), name, 0,",
      "bMalloc((int)sizeof(PidError), name, 1,"),
    M("ni-body", "new_pid_error(PD_FILE_BODY, 15, 5);",
      "new_pid_error(PD_FILE_BODY, 14, 5);"),
    M("ni-head", "new_pid_error(PD_FILE_HEADING, 15, 5);",
      "new_pid_error(PD_FILE_HEADING, 15, 4);"),
    M("ni-vel", "new_pid_error(PD_FILE_VELOCITY, 6, 3);",
      "new_pid_error(PD_FILE_VELOCITY, 6, 4);"),
    M("ni-order",
      "    d->pBodyError = new_pid_error(PD_FILE_BODY, 15, 5);\n"
      "    d->pHeadingError = new_pid_error(PD_FILE_HEADING, 15, 5);\n",
      "    d->pHeadingError = new_pid_error(PD_FILE_HEADING, 15, 5);\n"
      "    d->pBodyError = new_pid_error(PD_FILE_BODY, 15, 5);\n"),
    M("ni-latch", "d->DirectionLatch = 1;\n    d->AllowedToUseThrottleAndBrake",
      "d->DirectionLatch = 0;\n    d->AllowedToUseThrottleAndBrake"),
    M("ni-ok", "d->AllowedToUseThrottleAndBrake = 1;",
      "d->AllowedToUseThrottleAndBrake = 0;"),
    M("ni-steer", "    d->Base.Steering = 0;\n", ""),
    M("ni-ds", "d->DesiredSpeed = 0.0f;", "d->DesiredSpeed = 1.0f;"),
    M("ni-t", "    d->TimeToGetToDesiredSpeed = 0.0f;\n"
      "    d->DesiredSpeedTolerance = 0.0f;\n",
      "    d->DesiredSpeedTolerance = 0.0f;\n"),
    M("ni-tol", "d->DesiredSpeedTolerance = 0.0f;",
      "d->DesiredSpeedTolerance = 1.0f;"),
    M("ni-ebt", "    d->EBrakeTimer = 0.0f;\n", ""),
    M("ni-vt", "d->Base._vtable = PSYCHODRIVER_VTABLE;\n    d->MaxThrottle",
      "d->Base._vtable = CARDRIVER_VTABLE;\n    d->MaxThrottle"),
    M("ni-mt", "d->MaxThrottle = 1.0f;", "d->MaxThrottle = 0.0f;"),
    M("ni-zs", "    // Called, not dispatched.\n"
      "    psychodriver_zero_steering_memory(d);\n",
      "    // Called, not dispatched.\n"),
    M("ni-zt", "    psychodriver_zero_throttle_memory(d);\n"
      "    d->SteerToPoint.x = 0.0f;\n",
      "    d->SteerToPoint.x = 0.0f;\n"),
    M("ni-stp", "    d->SteerToPoint.x = 0.0f;\n    d->SteerToPoint.y = 0.0f;\n",
      "    d->SteerToPoint.y = 0.0f;\n"),
    M("ni-ret", "    return d;\n}\n\nvoid psychodriver_destroy",
      "    return NULL;\n}\n\nvoid psychodriver_destroy"),

    # -- the destructor --------------------------------------------------------
    M("dd-vt", "    d->Base._vtable = PSYCHODRIVER_VTABLE;\n"
      "    if (d->pBodyError != NULL)",
      "    if (d->pBodyError != NULL)"),
    M("dd-flags3", "pid_error_destroy(d->pBodyError, 3);",
      "pid_error_destroy(d->pBodyError, 2);"),
    M("dd-null", "if (d->pHeadingError != NULL)", "if (1)"),
    M("dd-order",
      "    if (d->pHeadingError != NULL)\n"
      "        pid_error_destroy(d->pHeadingError, 3);\n"
      "    if (d->pVelocityError != NULL)\n"
      "        pid_error_destroy(d->pVelocityError, 3);\n",
      "    if (d->pVelocityError != NULL)\n"
      "        pid_error_destroy(d->pVelocityError, 3);\n"
      "    if (d->pHeadingError != NULL)\n"
      "        pid_error_destroy(d->pHeadingError, 3);\n"),
    M("dd-horn", "    psychodriver_stop_honk_horn(d);\n    cardriver_destroy",
      "    cardriver_destroy"),
    M("dd-flags", "cardriver_destroy(&d->Base, flags);",
      "cardriver_destroy(&d->Base, 1);"),

    # -- SetDesiredSpeed and SetTarget -----------------------------------------
    M("sds-ok", "d->AllowedToUseThrottleAndBrake = allowed;",
      "d->AllowedToUseThrottleAndBrake = allowed != 0;"),
    M("sds-t", "d->TimeToGetToDesiredSpeed = time;",
      "d->TimeToGetToDesiredSpeed = speed;"),
    M("sds-tol", "d->DesiredSpeedTolerance = tolerance;",
      "d->DesiredSpeedTolerance = time;"),
    M("st-max", "21 <= t->NumPoints", "20 <= t->NumPoints"),
    M("st-neg", "t->NumPoints < 0 ||", "t->NumPoints < -1 ||"),
    M("st-assign", "    drivetarget_assign(&d->Base.MyDriveTarget, t);\n", ""),
    M("st-resample",
      "    drivetarget_resample(&d->Base.MyDriveTarget, d->pCar);\n", ""),

    # -- GetError and the memories ---------------------------------------------
    M("ge-x", "bATan(d->SteerToPoint.x - car->State.Position.x,",
      "bATan(car->State.Position.x - d->SteerToPoint.x,"),
    M("ge-sub", "- (uint32_t)ang));\n    *head = h;",
      "+ (uint32_t)ang));\n    *head = h;"),
    M("ge-le", "if (1.0f <= car->State.ForwardSpeed)",
      "if (1.0f < car->State.ForwardSpeed)"),
    M("ge-vm", "if (1.0f <= car->State.ForwardSpeed)",
      "if (1.0f <= car->State.VelocityMagnitude)"),
    M("ge-vel", "bATan(car->State.Velocity.x,", "bATan(car->State.Velocity.z,"),
    M("ge-else", "        *vel = h;\n", "        *vel = 0.0f;\n"),
    M("ge-ret", "    return ang;\n", "    return 0;\n"),
    M("zs-head", "pid_error_reset(d->pHeadingError, 0.0f);",
      "pid_error_reset(d->pHeadingError, 1.0f);"),
    M("cls-swap", "pid_error_reset(d->pBodyError, h);\n"
      "    pid_error_reset(d->pHeadingError, v);",
      "pid_error_reset(d->pBodyError, v);\n"
      "    pid_error_reset(d->pHeadingError, h);"),
    M("zt", "pid_error_reset(d->pVelocityError, 0.0f);",
      "pid_error_reset(d->pVelocityError, 1.0f);"),
    M("ct", "pid_error_reset(d->pVelocityError, fabsf(d->DesiredSpeed)",
      "pid_error_reset(d->pVelocityError, (d->DesiredSpeed)"),

    # -- GetMovementIndex -------------------------------------------------------
    M("mi-phys", "case PHYSICS_MOVEMENT:\n        return PD_INDEX_PHYSICS;",
      "case PHYSICS_MOVEMENT:\n        return PD_INDEX_COP;"),
    M("mi-mellow", "car->TheControlMode == TRAFFIC_CONTROL ? PD_INDEX_MELLOW",
      "car->TheControlMode != TRAFFIC_CONTROL ? PD_INDEX_MELLOW"),
    M("mi-mellow-else", ": PD_INDEX_BELT;\n    case COP_MOVEMENT:",
      ": PD_INDEX_TRAFFIC;\n    case COP_MOVEMENT:"),
    M("mi-cop", "case COP_MOVEMENT:\n        return PD_INDEX_COP;",
      "case COP_MOVEMENT:\n        return PD_INDEX_PHYSICS;"),
    M("mi-belt", "case BELT_MOVEMENT:\n        return PD_INDEX_BELT;",
      "case BELT_MOVEMENT:\n        return PD_INDEX_TRAFFIC;"),
    M("mi-default", "out of range\n        return PD_INDEX_TRAFFIC;",
      "out of range\n        return PD_INDEX_MELLOW;"),
    M("mi-fixed", "return (uint32_t)(idx - 3) < 2u;",
      "return (uint32_t)(idx - 3) < 1u;"),

    # -- CalcSteerToPoint -------------------------------------------------------
    M("cs-max", "dist = max_s(15.0f, car->State.ForwardSpeed",
      "dist = min_s(15.0f, car->State.ForwardSpeed"),
    M("cs-15", "dist = max_s(15.0f,", "dist = max_s(14.0f,"),
    M("cs-arr", "* PsychoDriverSteerToPointSecondsAhead[idx]);",
      "* PsychoDriverSteerToPointSecondsAhead[idx - 1]);"),
    M("cs-table", "table_get_value(&PidSteerToTable, car->State.ForwardSpeed);",
      "table_get_value(&PidSteerToTable, car->State.VelocityMagnitude);"),
    M("cs-dmode", "if (car->State.DriverMode == 1)\n            dist = dist",
      "if (car->State.DriverMode == 2)\n            dist = dist"),
    M("cs-two", "if (d->Base.MyDriveTarget.NumPoints < 2) {",
      "if (d->Base.MyDriveTarget.NumPoints < 3) {"),
    M("cs-five", "if (car->State.ForwardSpeed < 5.0f)\n            ai_steer",
      "if (car->State.ForwardSpeed <= 5.0f)\n            ai_steer"),
    M("cs-swapfn",
      "ai_steer_straight_vector3d(&p, car, dist);\n        else\n"
      "            ai_steer_straight_velocity3d(&p, car, dist);",
      "ai_steer_straight_velocity3d(&p, car, dist);\n        else\n"
      "            ai_steer_straight_vector3d(&p, car, dist);"),
    M("cs-y", "d->SteerToPoint.y = p.y;", "d->SteerToPoint.y = p.z;"),

    # -- CalcThrottleAndBrake -------------------------------------------------
    M("ctb-dhi", "float dd = min_s(2.0f,", "float dd = min_s(2.5f,"),
    M("ctb-dlo", "max_s(p->aDerivative.fAverage, -2.0f));",
      "max_s(p->aDerivative.fAverage, -2.5f));"),
    M("ctb-pp", "float pp = p->fCurrentError;", "float pp = p->fPreviousError;"),
    M("ctb-ii", "float ii = p->aIntegral.fTotal;",
      "float ii = p->aIntegral.fAverage;"),
    M("ctb-tol", "if (!(d->DesiredSpeedTolerance\n          < fabsf(",
      "if (!(d->DesiredSpeedTolerance\n          <= fabsf("),
    M("ctb-abs", "< fabsf(fabsf(d->DesiredSpeed) - d->pCar",
      "< fabsf((d->DesiredSpeed) - d->pCar"),
    M("ctb-zero", "        *thr = 0.0f;\n        *brk = 0.0f;\n        return;",
      "        *thr = 0.0f;\n        return;"),
    M("ctb-c", "dd * PD_THROTTLE_KD) + ii * PD_THROTTLE_KI;",
      "dd * PD_THROTTLE_KI) + ii * PD_THROTTLE_KD;"),
    M("ctb-assoc",
      "c = (pp * PD_THROTTLE_KP + dd * PD_THROTTLE_KD) + ii * PD_THROTTLE_KI;",
      "c = pp * PD_THROTTLE_KP + (dd * PD_THROTTLE_KD + ii * PD_THROTTLE_KI);"),
    M("ctb-clo", "max_s(c, -0.25f));", "max_s(c, -0.3f));"),
    M("ctb-chi", "c = min_s(0.25f,", "c = min_s(0.3f,"),
    M("ctb-f", "f = (d->Base.Throttle - d->Base.Brake) + c;",
      "f = (d->Base.Throttle + d->Base.Brake) + c;"),
    M("ctb-fhi", "f = min_s(1.0f, max_s(f, PD_MIN_PEDAL));",
      "f = min_s(0.99f, max_s(f, PD_MIN_PEDAL));"),
    M("ctb-flo", "max_s(f, PD_MIN_PEDAL));", "max_s(f, -1.0f));"),
    M("ctb-lt", "if (f < 0.0f) {", "if (f <= 0.0f) {"),
    M("ctb-brk", "*brk = -f;", "*brk = f;"),

    # -- Drive: the start -------------------------------------------------------
    M("dr-bam", "steerDeg = (float)(int32_t)d->Base.Steering",
      "steerDeg = (float)(int16_t)d->Base.Steering"),
    M("dr-180", "if (180.0f < steerDeg)", "if (180.0f <= steerDeg)"),
    M("dr-360", "steerDeg = steerDeg - 360.0f;", "steerDeg = steerDeg - 359.0f;"),
    M("dr-dtc", "dtc = max_s(dt, PD_MIN_DT);", "dtc = dt;"),
    M("dr-spd", "spd = car->State.VelocityMagnitude;",
      "spd = car->State.ForwardSpeed;"),
    M("dr-neg", "if (car->State.ForwardSpeed < 0.0f)\n        spd = -spd;",
      "if (car->State.ForwardSpeed <= 0.0f)\n        spd = -spd;"),
    M("dr-far", "if (200.0f < sqrtf(dx * dx + dy * dy))",
      "if (200.0f <= sqrtf(dx * dx + dy * dy))"),
    M("dr-far-y", "dy = d->SteerToPoint.y - car->State.Position.y;",
      "dy = d->SteerToPoint.y - car->State.Position.x;"),
    M("dr-front", "if (i < 2)\n                front = 1;",
      "if (i < 1)\n                front = 1;"),
    M("dr-wheels", "for (i = 0; i < 4; i++)\n        if (car->State.Wheel",
      "for (i = 0; i < 3; i++)\n        if (car->State.Wheel"),

    # -- Drive: the steering ----------------------------------------------------
    M("dr-rec-body", "pid_error_record(d->pBodyError, h, dt);",
      "pid_error_record(d->pBodyError, h, dtc);"),
    M("dr-rec-head", "pid_error_record(d->pHeadingError, v, dt);",
      "pid_error_record(d->pHeadingError, h, dt);"),
    M("dr-coll-break", "                ((PsychoVoidFn)e->fn)(vt_this(d, e));\n"
      "                break;\n",
      "                ((PsychoVoidFn)e->fn)(vt_this(d, e));\n"),
    M("dr-coll-slot", "CARDRIVER_VT_CLEAR_STEERING_MEMORY);",
      "CARDRIVER_VT_ZERO_STEERING_MEMORY);"),
    M("dr-coll-n", "for (i = 0; i < b->NumCollisions; i++)",
      "for (i = 0; i <= b->NumCollisions; i++)"),
    M("dr-swap-sign", "if (h * v < 0.0f)", "if (h * v <= 0.0f)"),
    M("dr-swap-diff", "else if (fPsychoCounterDiff < fabsf(v - h)",
      "else if (fPsychoCounterDiff <= fabsf(v - h)"),
    M("dr-swap-2v", "&& fabsf(v) + fabsf(v) < fabsf(h))",
      "&& fabsf(v) + fabsf(v) <= fabsf(h))"),
    M("dr-swap-hv", "&& fabsf(v) + fabsf(v) < fabsf(h))",
      "&& fabsf(h) + fabsf(h) < fabsf(v))"),
    M("dr-pid-swap", "        if (swap)\n            pid = d->pBodyError;",
      "        if (swap)\n            pid = d->pHeadingError;"),
    M("dr-pid-fs", "else if (d->pCar->State.ForwardSpeed < 5.0f)",
      "else if (d->pCar->State.ForwardSpeed <= 5.0f)"),
    M("dr-dhi", "dd = min_s(0.5f,", "dd = min_s(0.6f,"),
    M("dr-dlo", "max_s(pid->aDerivative.fAverage, -0.5f));",
      "max_s(pid->aDerivative.fAverage, -0.6f));"),
    M("dr-pp", "pp = pid->fCurrentError;", "pp = pid->fPreviousError;"),
    M("dr-ii", "ii = pid->aIntegral.fTotal;", "ii = pid->aIntegral.fAverage;"),
    M("dr-kp-fixed", "kp = PsychoSteeringProportionalWeight[idx];",
      "kp = PsychoSteeringProportionalWeight[idx - 1];"),
    M("dr-ki-fixed", "ki = PsychoSteeringIntegralWeight[idx];",
      "ki = PsychoSteeringDerivativeWeight[idx];"),
    M("dr-kd-fixed", "kd = PsychoSteeringDerivativeWeight[idx];",
      "kd = PsychoSteeringIntegralWeight[idx];"),
    M("dr-kp", "kp = table_get_value(&PidProportionalTable, spd);",
      "kp = table_get_value(&PidProportionalTable,\n"
      "                                 car->State.VelocityMagnitude);"),
    M("dr-kd", "kd = table_get_value(&PidDerivativeTable, spd);",
      "kd = table_get_value(&PidIntegralTable, spd);"),
    M("dr-ki", "ki = table_get_value(&PidIntegralTable, spd);",
      "ki = table_get_value(&PidDerivativeTable, spd);"),
    M("dr-dmode", "if (d->pCar->State.DriverMode == 1)\n                kd",
      "if (d->pCar->State.DriverMode != 1)\n                kd"),
    M("dr-half", "ki = ki * 0.5f;", "ki = ki * 0.25f;"),
    M("dr-steer", "steer = (-pp * kp - dd * kd) - ii * ki;",
      "steer = (-pp * kp + dd * kd) - ii * ki;"),
    M("dr-steer-assoc", "steer = (-pp * kp - dd * kd) - ii * ki;",
      "steer = -pp * kp - (dd * kd + ii * ki);"),
    M("dr-yaw", "steer = -carstate_get_yaw_always(",
      "steer = carstate_get_yaw_always("),
    M("dr-clamp", "steer = min_s(PD_MAX_STEER, max_s(steer, -PD_MAX_STEER));",
      "steer = min_s(PD_MAX_STEER, steer);"),
    M("dr-copy", "copy = steer;", "copy = -steer;"),

    # -- Drive: the speed and the gears ----------------------------------------
    M("dr-ve", "ve = fabsf(d->DesiredSpeed) - car->State.VelocityMagnitude;",
      "ve = d->DesiredSpeed - car->State.VelocityMagnitude;"),
    M("dr-teps", "<= PD_TIME_EPSILON))", "< PD_TIME_EPSILON))"),
    M("dr-tabs", "if (!(fabsf(d->TimeToGetToDesiredSpeed) <= PD_TIME_EPSILON))",
      "if (!(d->TimeToGetToDesiredSpeed <= PD_TIME_EPSILON))"),
    M("dr-tdiv", "ve = ve / d->TimeToGetToDesiredSpeed * PD_TIME_GAIN;",
      "ve = ve * PD_TIME_GAIN / d->TimeToGetToDesiredSpeed;"),
    M("dr-rec-vel", "pid_error_record(d->pVelocityError, ve, dt);",
      "pid_error_record(d->pVelocityError, ve, dtc);"),
    M("dr-norear-gear", "gear = 1;\n        thr = 0.0f;",
      "gear = 0;\n        thr = 0.0f;"),
    M("dr-norear-zt", "        psychodriver_zero_throttle_memory(d);\n"
      "    } else if", "    } else if"),
    M("dr-slow", "} else if (fabsf(d->DesiredSpeed) < 2.0f) {",
      "} else if (fabsf(d->DesiredSpeed) <= 2.0f) {"),
    M("dr-slow-brk", "brk = 1.0f;\n    } else if (0.0f < d->DesiredSpeed) {",
      "brk = 0.5f;\n    } else if (0.0f < d->DesiredSpeed) {"),
    M("dr-fwd", "} else if (0.0f < d->DesiredSpeed) {",
      "} else if (0.0f <= d->DesiredSpeed) {"),
    M("dr-f-m7", "if (spd < -7.0f)", "if (spd <= -7.0f)"),
    M("dr-f-m2", "else if (-2.0f < spd)", "else if (-2.0f <= spd)"),
    M("dr-f-latch", "else if (-2.0f < spd)\n            d->DirectionLatch = 1;",
      "else if (-2.0f < spd)\n            d->DirectionLatch = 0;"),
    M("dr-f-gear", "gear = -1;\n        if (d->DirectionLatch) {\n"
      "            doCalc = 1;",
      "gear = 0;\n        if (d->DirectionLatch) {\n            doCalc = 1;"),
    M("dr-f-brk", "brk = 0.5f;", "brk = 1.0f;"),
    M("dr-f-steer", "brk = 0.5f;\n            steer = -copy;",
      "brk = 0.5f;\n            steer = copy;"),
    M("dr-b-7", "if (7.0f < spd)", "if (7.0f <= spd)"),
    M("dr-b-2", "else if (spd < 2.0f)", "else if (spd <= 2.0f)"),
    M("dr-b-steer", "steer = -copy;\n            doCalc = 1;",
      "steer = copy;\n            doCalc = 1;"),
    M("dr-b-gear", "doCalc = 1;\n            gear = 0;",
      "doCalc = 1;\n            gear = 1;"),
    M("dr-b-brk", "brk = 1.0f;\n            gear = -1;",
      "brk = 0.5f;\n            gear = -1;"),
    M("dr-calc", "if (doCalc)\n", "if (1)\n"),

    # -- Drive: the wheel -------------------------------------------------------
    M("dr-maxa", "maxA = 45.0f;\n        if (fixed)",
      "maxA = 40.0f;\n        if (fixed)"),
    M("dr-range-hi", "maxA = min_s(45.0f,", "maxA = min_s(44.0f,"),
    M("dr-range-lo", "0.0f));\n        cur = steerDeg / maxA;",
      "4.5f));\n        cur = steerDeg / maxA;"),
    M("dr-range-tbl", "&PsychoSteeringRangeTable, spd),",
      "&PsychoSteeringSpeedTable, spd),"),
    M("dr-cur", "cur = steerDeg / maxA;", "cur = steerDeg / 45.0f;"),
    M("dr-des", "des = steer / (maxA * PD_DEG_TO_RAD);",
      "des = steer / (maxA * PD_RAD_TO_DEG);"),
    M("dr-des-assoc", "des = steer / (maxA * PD_DEG_TO_RAD);",
      "des = steer / maxA / PD_DEG_TO_RAD;"),
    M("dr-desclamp", "if (!swap && fixed)\n", "if (fixed)\n"),
    M("dr-desclamp-hi", "des = min_s(1.0f, max_s(des, -1.0f));",
      "des = min_s(1.5f, max_s(des, -1.0f));"),
    M("dr-desclamp-lo", "des = min_s(1.0f, max_s(des, -1.0f));",
      "des = min_s(1.0f, max_s(des, -1.5f));"),
    M("dr-ratecond", "if (fixed || !swap) {", "if (!swap) {"),
    M("dr-rate", "spd) * 0.5f;", "spd) * 0.25f;"),
    M("dr-rate-tbl", "rate = table_get_value(&PsychoSteeringSpeedTable, spd)",
      "rate = table_get_value(&PsychoSteeringSpeedTable, steerDeg)"),
    M("dr-rate-pos", "if (0.0f < cur) {", "if (0.0f <= cur) {"),
    M("dr-rate-dbl1", "if (des < cur)\n", "if (des <= cur)\n"),
    M("dr-rate-dbl1b", "if (des < cur)\n                    rate = rate + rate;",
      "if (des < cur)\n                    rate = rate;"),
    M("dr-rate-neg", "} else if (cur < 0.0f) {", "} else if (cur <= 0.0f) {"),
    M("dr-rate-dbl2", "if (cur < des)\n", "if (cur <= des)\n"),
    M("dr-rate-dbl2b", "if (cur < des)\n                    rate = rate + rate;",
      "if (cur < des)\n                    rate = rate;"),
    M("dr-rate-dtc", "rate = rate * dtc;", "rate = rate * dt;"),
    M("dr-delta", "delta = min_s(rate, max_s(delta, -rate));",
      "delta = min_s(rate, delta);"),
    M("dr-out", "out = (cur + delta) * maxA;", "out = (cur + delta) * 45.0f;"),
    M("dr-ctl", "out = out * d->pCar->pCarTypeInfo->Control.Steering;",
      "out = out * 1.0f;"),
    M("dr-ctl-fixed", "if (fixed)\n            out = out",
      "if (!fixed)\n            out = out"),
    M("dr-r2d", "out = steer * PD_RAD_TO_DEG;", "out = copy * PD_RAD_TO_DEG;"),

    # -- Drive: the end ---------------------------------------------------------
    M("dr-t", "t = d->TimeToGetToDesiredSpeed - dt;",
      "t = d->TimeToGetToDesiredSpeed - dtc;"),
    M("dr-tfloor", "if (t < 0.0f)\n        d->TimeToGetToDesiredSpeed = 0.0f;",
      "if (t <= 0.0f)\n        d->TimeToGetToDesiredSpeed = 0.0f;"),
    M("dr-ok", "if (d->AllowedToUseThrottleAndBrake) {", "if (1) {"),
    M("dr-ok-zero", "        d->Base.Brake = 0.0f;\n"
      "        d->Base.Throttle = 0.0f;\n    }\n",
      "        d->Base.Brake = brk;\n"
      "        d->Base.Throttle = 0.0f;\n    }\n"),
    M("dr-ebt", "t = d->EBrakeTimer - dt;", "t = d->EBrakeTimer - dtc;"),
    M("dr-eb-lt", "if (0.0f < t && PD_EBRAKE_SPEED",
      "if (0.0f <= t && PD_EBRAKE_SPEED"),
    M("dr-eb-speed", "PD_EBRAKE_SPEED < fabsf(spd)) {",
      "PD_EBRAKE_SPEED <= fabsf(spd)) {"),
    M("dr-eb-abs", "PD_EBRAKE_SPEED < fabsf(spd)) {",
      "PD_EBRAKE_SPEED < spd) {"),
    M("dr-eb-brk", "        d->Base.Brake = 0.0f;\n        d->Base.EBrake = 1.0f;",
      "        d->Base.EBrake = 1.0f;"),
    M("dr-eb-thr", "d->Base.EBrake = 1.0f;\n        d->Base.Throttle = 0.0f;",
      "d->Base.EBrake = 1.0f;"),
    M("dr-eb-off", "    } else {\n        d->Base.EBrake = 0.0f;\n    }\n",
      "    }\n"),
    M("dr-gear", "d->Base.DesiredGear = gear;", "d->Base.DesiredGear = -1;"),
    M("dr-steer-out", "(uint16_t)(ee_trunc_w(out * 65536.0f) / 360);",
      "(uint16_t)ee_trunc_w(out * 65536.0f / 360.0f);"),

    # -- the horn and the getters ----------------------------------------------
    M("h-start", "if (s != NULL && gBaseCarSoundStartHonkHornFn != NULL)",
      "if (gBaseCarSoundStartHonkHornFn != NULL)"),
    M("h-stop", "if (s != NULL && gBaseCarSoundStopHonkHornFn != NULL)",
      "if (gBaseCarSoundStopHonkHornFn != NULL)"),
    M("h-is", "if (s == NULL || gBaseCarSoundIsHonkingFn == NULL)\n"
      "        return 0;",
      "if (s == NULL || gBaseCarSoundIsHonkingFn == NULL)\n        return 1;"),
    M("h-is-ret", "return gBaseCarSoundIsHonkingFn(s);",
      "return gBaseCarSoundIsHonkingFn(s) != 0;"),
    M("g-drvnum", "return d->pCar->DriverNumber;",
      "return (uint16_t)d->pCar->DriverNumber;"),
    M("g-jeeves-eb", "d->Base.EBrake = 0.0f;\n    d->Base.Throttle = 1.0f;",
      "d->Base.EBrake = 1.0f;\n    d->Base.Throttle = 1.0f;"),
    M("g-jeeves-thr", "d->Base.Throttle = 1.0f;\n    d->Base.Brake = 0.0f;",
      "d->Base.Throttle = 0.5f;\n    d->Base.Brake = 0.0f;"),
    M("g-jeeves-brk", "    d->Base.Brake = 0.0f;\n}\n",
      "    d->Base.Brake = 1.0f;\n}\n"),
    M("g-lowgear", "d->Base.DesiredGear = -1;", "d->Base.DesiredGear = 0;"),
    M("g-gtts", "return d->TimeToGetToDesiredSpeed;", "return d->DesiredSpeed;"),
    M("g-gds", "    return d->DesiredSpeed;\n",
      "    return d->DesiredSpeedTolerance;\n"),
    M("g-mt", "d->MaxThrottle = f;", "d->MaxThrottle = 1.0f;"),
    M("g-gstp", "return &d->SteerToPoint;",
      "return (bVector2 *)&d->MaxThrottle;"),
    M("g-ebt", "d->EBrakeTimer = f;", "d->EBrakeTimer = 0.0f;"),
    M("g-sstp", "d->SteerToPoint.y = p->y;", "d->SteerToPoint.y = p->x;"),

    # -- the table --------------------------------------------------------------
    M("vt-lowgear", "E(psychodriver_set_low_gear),", "{ 0, 0, NULL },"),
    M("vt-zs", "E(psychodriver_zero_steering_memory),",
      "E(psychodriver_clear_steering_memory),"),
    M("vt-gds", "E(psychodriver_get_desired_speed),",
      "E(psychodriver_get_desired_time_to_speed),"),
    M("vt-drvnum", "E(psychodriver_get_driver_number),",
      "E(psychodriver_is_honking),"),
]

EQUIVALENT = {
    "rw-le": "no BAM is 3.14159 radians exactly: 32767 is 3.141497 and 32768 "
             "3.1415927",
    "ni-steer": "cardriver_init has already zeroed Steering",
    "ni-zs": "the PidErrors are fresh from pid_error_init, which leaves "
             "exactly what Reset(0) stores",
    "ni-zt": "the PidErrors are fresh from pid_error_init, which leaves "
             "exactly what Reset(0) stores",
    "dd-vt": "nothing derives from PsychoDriver, nothing between the store "
             "and ~CarDriver's own dispatches, and ~CarDriver stores its "
             "own vptr",
    "rw-dead": "RadianWrap's angle comes in unsigned, so f is never below "
               "-3.14159 and the add never runs",
    "dr-fwd": "a DesiredSpeed of 0 has already gone to the |DesiredSpeed| < 2 "
              "branch",
    "dr-rate-dbl1": "with des == cur the step is 0 whatever the rate",
    "dr-rate-dbl2": "with des == cur the step is 0 whatever the rate",
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
        todo, SOURCES, "psychodriver_test",
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
