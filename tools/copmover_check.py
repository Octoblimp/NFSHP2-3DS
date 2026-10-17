#!/usr/bin/env python3
"""Cross-check CopMover, in 3DS Files/source/copdriver.c, against the retail
image, SLES_507.31, run in mipsemu.

**The model** is retail's own copdriver.obj: CopMover's constructor
(0x001a0dd8), its destructor (0x001a0e88) and Move (0x001a1030) through the
image's table (0x002b5a08), ResetMaxThrottleAccel (0x001a0ea0),
CalculateFacingAngle (0x001a1bd0) and the accessors (0x001a32f0 ..
0x001a3344). Run as shipped under them: bSin, bCos, bFixATan, eIdentity,
eRotateX, eRotateY and eRotateZ (with eMulMatrix). The harness
(tools/src/copmover_test.c) runs copdriver.c, bmath.c, emath.c and
vtable.c and prints the same lines.

**The stubs**, logged and answered by the same rule on both sides:
TopologyCoordinate::GetElevation (a plane, with a step up past a given x,
its normal, terrain and whether it found a polygon scripted), CarState's
CalculateGeometryPosition, CalculateWheelMatrices, SetWheelTouchingGround
and SetWheelTerrain, Car::ComputeFakeRPM, and ~CarMover.

**Compared** are the stubs' logs (each ground sample's point among them),
every return, and on `dump` every word of the mover but the Driver and the
ground normal's fourth (the image's stack, in the constructor and when no
ground is found), and the CarState fields Move writes but AngularVelocity's
fourth (the stack again), the car's NitroEffectFlag and the driver's
Steering, Throttle, Brake and EBrake.

    python tools/copmover_check.py
    python tools/copmover_check.py --mutate [--only a,b]
    python tools/copmover_check.py --dump out/copmover
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

HARNESS = "tools/src/copmover_test.c"
CMC = "3DS Files/source/copdriver.c"
SOURCES = [HARNESS, CMC,
           "3DS Files/source/emath.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c",
           "3DS Files/source/bvector.c",
           "3DS Files/source/bmatrix.c",
           "3DS Files/source/replay.c", "3DS Files/source/p32.c",
           "3DS Files/source/vtable.c"]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = retail_model.RETAIL_GP
G_COPMGR = GP - 15620                   # pCopManager

F_CTOR = 0x001a0dd8
F_DTOR = 0x001a0e88
F_RMTA = 0x001a0ea0
F_CFA = 0x001a1bd0
F_GTA = 0x001a32f0
F_AIR = 0x001a32f8
F_SMT = 0x001a3300
F_SMB = 0x001a3308
F_SBM = 0x001a3310
F_GMS = 0x001a3318
F_SDV = 0x001a3320
F_SDS = 0x001a3330
F_SDA = 0x001a3338
F_SST = 0x001a3340

S_ELEV = 0x00152070
S_GEOM = 0x001c0f40
S_WMAT = 0x001c0ef0
S_TOUCH = 0x001c0cf8
S_TERRAIN = 0x001c0d48
S_RPM = 0x00132b00
S_CMDTOR = 0x00136b78

VT_DTOR, VT_MOVE = 8, 16

MV_SIZE = 128
CAR_SIZE = 2304
CTI_SIZE = 1536
DRV_SIZE = 1024
MGR_SIZE = 10528
CS = 64                                 # the car's CarState
TC = 1312                               # its TopologyCoordinate
NITRO = 2064
MGR_LEVEL = 10476

# The groups each object dumps, and `set` writes: name, the image's
# offset, count and kind (f a float, h a u16, w a word). The harness has
# the same lists by field.
GROUPS = {
    "mv": [("vel", 16, 4, "f"), ("ta", 32, 2, "f"), ("face", 40, 2, "h"),
           ("spd", 44, 6, "f"), ("n68", 68, 3, "w"), ("dvel", 80, 4, "f"),
           ("norm", 96, 3, "f"), ("st", 112, 2, "w"), ("pad", 120, 2, "w")],
    "cs": [("gp", 16, 4, "f"), ("pos", 32, 4, "f"), ("vel", 48, 4, "f"),
           ("bm", 80, 16, "f"), ("av", 144, 3, "f"), ("wav", 688, 4, "f"),
           ("wang", 704, 4, "f"), ("wzf", 720, 4, "f"), ("wbo", 752, 4, "f"),
           ("wsh", 768, 4, "f"), ("wslip", 820, 8, "f"), ("wtu", 852, 4, "f"),
           ("angle", 868, 2, "h"), ("fs", 896, 2, "f"), ("mv", 1024, 1, "w")],
    "car": [("nitro", NITRO, 1, "w")],
    "drv": [("steer", 528, 1, "h"), ("thr", 532, 3, "f")],
    "cti": [("type", 1332, 1, "w"), ("cog", 272, 4, "f")]
           + [("w%d" % i, 288 + 32 * i, 4, "f") for i in range(4)],
}


def fb(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def bf(b):
    return struct.unpack("<f", struct.pack("<I", b & M32))[0]


def f32(x):
    return bf(fb(x))


def hx(b):
    b &= M32
    if (b & 0x7f800000) == 0x7f800000 and (b & 0x007fffff):
        return "nan"
    return "%08x" % b


def F(x):
    """A float argument, as its bits."""
    return "0x%08x" % fb(x)


# ============================================================== the script

def bam(deg):
    return int(round(deg * 65536.0 / 360.0)) & 0xffff


class Script(object):
    def __init__(self):
        self.lines = []

    def add(self, *parts):
        self.lines.append("|".join(str(p) for p in parts))

    def tag(self, s):
        self.add("tag", s)

    def set(self, obj, group, i, v):
        if isinstance(v, float):
            v = F(v)
        self.add("set", obj, group, i, v)

    def vec(self, obj, group, vals):
        for i, v in enumerate(vals):
            self.set(obj, group, i, float(v))

    def ground(self, gz=0.0, gx=0.0, gy=0.0, sx=1e9, sz=0.0, found=1,
               n=(0.0, 0.0, 1.0, -0.5), terrain=3, sy=-1e9):
        self.add("ground", F(gz), F(gx), F(gy), F(sx), F(sz), found,
                 *([F(v) for v in n] + [terrain, F(sy)]))

    def car(self, pos=(100.0, -50.0, 2.0, 0.25), heading=30.0, speed=20.0,
            vz=0.0, vw=0.125, fs=None, steer=1234):
        a = math.radians(heading)
        self.vec("cs", "pos", pos)
        self.vec("cs", "vel", (f32(speed * math.cos(a)),
                               f32(speed * math.sin(a)), vz, vw))
        self.set("cs", "angle", 0, bam(heading))
        self.set("cs", "angle", 1, 777)
        self.set("cs", "fs", 0, f32(speed * 0.97 if fs is None else fs))
        self.set("cs", "fs", 1, f32(abs(speed)))
        self.set("cs", "mv", 0, 1)
        self.vec("cs", "gp", (9.0, 9.5, 10.0, 10.5))
        self.vec("cs", "av", (0.5, -0.25, 0.75))
        self.vec("cs", "wav", (1.0, 2.0, 3.0, 4.0))
        self.vec("cs", "wang", (0.5, 1.5, 2.5, 3.5))
        self.vec("cs", "wzf", (100.0, 200.0, 300.0, 400.0))
        self.vec("cs", "wbo", (0.1, 0.2, 0.3, 0.4))
        self.vec("cs", "wsh", (0.01, 0.02, 0.03, 0.04))
        self.vec("cs", "wslip", [0.05 * (k + 1) for k in range(8)])
        self.vec("cs", "wtu", (0.6, 0.7, 0.8, 0.9))
        self.vec("cs", "bm", [0.0625 * (k + 1) for k in range(16)])
        self.set("drv", "steer", 0, steer)
        self.vec("drv", "thr", (0.75, 0.625, 0.5))
        self.set("car", "nitro", 0, 7)

    def cartype(self, t=4, cog=(0.0, 0.1, 0.45, 0.0), z3=-0.2,
                radius=(0.33, 0.34, 0.35, 0.36)):
        self.set("cti", "type", 0, t & M32)
        self.vec("cti", "cog", cog)
        for i in range(4):
            self.vec("cti", "w%d" % i, (1.2 if i < 2 else -1.3,
                                        0.8 if i % 2 else -0.8,
                                        z3 if i == 3 else -0.15, radius[i]))


def script():
    s = Script()
    rnd = random.Random(1237)

    s.tag("setup")
    s.add("lvl", 2)
    s.cartype()
    s.ground()
    s.car()

    # ---- the constructor on each car type
    s.tag("ctor by type")
    for t in (4, 31, 32, 33, 34, 3, 5, 30, 35, 0, -1, 100):
        s.cartype(t=t)
        s.car(heading=float(t * 7), speed=float(t), fs=float(t) * 0.5)
        s.add("new")
        s.add("dump")
        s.add("rmta")
    s.cartype(t=4)

    # ---- ResetMaxThrottleAccel on its own, over a value set first
    s.tag("rmta")
    for t in (4, 31, 32, 33, 34, 2, 35, 36, -5):
        s.set("cti", "type", 0, t & M32)
        s.add("smt", F(99.5))
        s.add("rmta")
    s.cartype(t=4)

    # ---- the accessors
    s.tag("accessors")
    s.car()
    s.add("new")
    s.add("gta")
    s.add("air")
    s.add("smt", F(13.5))
    s.add("smb", F(-22.0))
    s.add("sbm", F(61.25))
    s.add("gms")
    s.add("sdv", F(1.5), F(-2.5), F(3.5), F(4.5))
    s.add("sds", F(-7.25))
    s.add("sda", 65535)
    s.add("sst", 1)
    s.add("dump")
    s.set("mv", "st", 0, 1)
    s.add("air")
    s.set("mv", "st", 0, 0)
    s.add("sst", 0)

    # ---- CalculateFacingAngle over a grid
    s.tag("cfa grid")
    s.add("new")
    # 1e-20 against a top speed of 0: the slope is -FLT_MAX, not -inf.
    speeds = (0.0, -0.0, 0.001, 1.0, 10.0, 40.0, 84.9351806640625, 100.0,
              -5.0, -60.0, 1e-20)
    pairs = ((0, 0), (0, 100), (0, 30000), (0, 35536), (65000, 500),
             (32768, 0), (0, 32768), (1000, 900), (12000, 0), (0, 12001),
             (40000, 52000), (5, 65530))
    maxes = (80.46490478515625, 84.9351806640625, 1.0, 0.0, -10.0)
    for sp in speeds:
        for face, dface in pairs:
            for mx in maxes:
                for dt in (1.0 / 30.0, 0.5):
                    s.set("mv", "spd", 0, f32(sp))
                    s.set("mv", "face", 0, face)
                    s.set("mv", "face", 1, dface)
                    s.add("cfa", F(mx), F(f32(dt)))

    def frames(n, dt=1.0 / 30.0, every=1, hook=None):
        for i in range(n):
            if hook:
                hook(i)
            s.add("move", F(f32(dt)))
            if (i + 1) % every == 0 or i == n - 1:
                s.add("dump")

    # ---- STEERING
    for lvl in (0, 1, 2):
        s.tag("steer accelerate lvl %d" % lvl)
        s.add("lvl", lvl)
        s.ground(gz=1.0, gx=0.01, gy=-0.02, n=(-0.01, 0.02, 0.9997, 0.0))
        s.car(speed=5.0)
        s.add("new")
        s.add("sds", F(90.0))
        s.add("sda", bam(80.0))
        frames(12)

    s.tag("steer brake")
    s.add("lvl", 2)
    s.car(speed=40.0)
    s.add("new")
    s.add("sds", F(0.0))
    frames(40, every=2)

    s.tag("steer brake gently")
    s.car(speed=20.0)
    s.add("new")
    s.add("sds", F(19.9))
    frames(6)
    s.add("sds", F(19.0))
    frames(6)

    s.tag("steer reverse")
    s.car(speed=2.0, heading=-100.0)
    s.add("new")
    s.add("sds", F(-15.0))
    s.add("sda", bam(-80.0))
    frames(30, every=3)

    s.tag("steer big dt")
    s.car(speed=30.0, heading=170.0)
    s.add("new")
    s.add("sds", F(85.0))
    s.add("sda", bam(-170.0))
    frames(5, dt=0.5)
    s.add("sds", F(-85.0))
    frames(5, dt=0.25)

    s.tag("steer over max")
    s.car(speed=120.0, fs=120.0)
    s.add("new")
    s.add("sds", F(150.0))
    frames(3)
    s.add("sbm", F(30.0))
    frames(3)
    s.add("sbm", F(0.0))
    s.add("lvl", 2)
    frames(2)
    s.add("sbm", F(-5.0))
    frames(2)
    s.add("sbm", F(84.9351806640625))

    s.tag("steer no ground")
    s.ground(found=0)
    s.car(speed=10.0)
    s.add("new")
    s.add("sds", F(12.0))
    frames(3)

    s.tag("steer into the ground")
    s.ground(n=(0.6, 0.0, 0.8, 1.0))
    s.car(speed=30.0, heading=0.0)
    s.add("new")
    s.add("sds", F(30.0))
    frames(3)
    s.ground(n=(-0.6, 0.0, 0.8, 1.0))
    frames(3)
    s.ground(n=(0.0, 0.8, 0.6, 1.0))
    s.car(speed=4.0, heading=90.0)
    s.add("new")
    s.add("sds", F(5.5))
    frames(4)

    s.tag("steer on a step")
    s.ground(gz=0.5, sx=100.5, sz=2.5)
    s.car(pos=(98.0, 10.0, 1.0, 0.0), speed=10.0, heading=0.0)
    s.add("new")
    s.add("sds", F(10.0))
    frames(10)
    s.ground(gz=0.5, sx=150.0, sz=-1.75)
    s.car(pos=(147.0, 10.0, 1.0, 0.0), speed=10.0, heading=0.0)
    s.add("new")
    s.add("sds", F(10.0))
    frames(10)
    s.ground(gz=0.5, sx=150.0, sz=2.0)
    s.car(pos=(149.5, 10.0, 1.0, 0.0), speed=0.0, heading=0.0)
    s.add("new")
    frames(2)

    s.tag("steer steep plane")
    s.ground(gz=-3.0, gx=0.4, gy=-0.7, n=(-0.35, 0.6, 0.72, 2.0))
    s.car(pos=(10.0, 20.0, 5.0, 1.0), speed=15.0, heading=45.0)
    s.add("new")
    s.add("sds", F(25.0))
    s.add("sda", bam(135.0))
    frames(8)

    # ---- TRANSLATING
    s.tag("translate")
    s.ground(gz=1.0, gx=0.01, gy=-0.02, n=(-0.01, 0.02, 0.9997, 0.0))
    for lvl in (0, 1, 2):
        s.add("lvl", lvl)
        s.car(speed=12.0, heading=20.0)
        s.add("new")
        s.add("sst", 1)
        s.add("sdv", F(30.0), F(5.0), F(9.0), F(0.5))
        frames(10)
        s.add("sdv", F(-10.0), F(25.0), F(0.0), F(0.0))
        frames(10, every=2)
        s.add("sdv", F(0.0), F(0.0), F(0.0), F(0.0))
        frames(20, every=4)

    s.tag("translate from rest")
    s.car(speed=0.0, heading=0.0, vz=0.0, vw=0.0)
    s.add("new")
    s.add("sst", 1)
    s.add("sdv", F(0.0), F(0.0), F(0.0), F(0.0))
    frames(2)
    s.add("sdv", F(5.0), F(-3.0), F(0.0), F(0.0))
    frames(6)

    s.tag("translate hard")
    s.car(speed=60.0, heading=-30.0)
    s.add("new")
    s.add("sst", 1)
    s.add("sdv", F(-60.0), F(10.0), F(0.0), F(0.0))
    frames(8, dt=0.25)
    s.add("sdv", F(200.0), F(200.0), F(0.0), F(0.0))
    frames(8, dt=1.0 / 60.0)

    s.tag("translate brake limits")
    s.car(speed=40.0, heading=0.0)
    s.add("new")
    s.add("sst", 1)
    s.add("smb", F(4.0))
    s.add("sdv", F(39.0), F(0.0), F(0.0), F(0.0))
    frames(10)
    s.add("smb", F(400.0))
    s.add("sdv", F(0.0), F(0.0), F(0.0), F(0.0))
    frames(10)

    s.tag("translate into the ground")
    s.ground(n=(0.6, 0.0, 0.8, 1.0))
    s.car(speed=30.0, heading=0.0)
    s.add("new")
    s.add("sst", 1)
    s.add("sdv", F(30.0), F(0.0), F(0.0), F(0.0))
    frames(3)
    s.ground(found=0)
    frames(2)

    s.tag("translate step")
    s.ground(gz=0.5, sx=100.5, sz=3.0)
    s.car(pos=(98.0, 10.0, 1.0, 0.0), speed=10.0, heading=0.0)
    s.add("new")
    s.add("sst", 1)
    s.add("sdv", F(12.0), F(1.0), F(0.0), F(0.0))
    frames(8)

    # ---- neither state
    s.tag("other states")
    s.ground(gz=1.0, gx=0.01, gy=-0.02, n=(-0.01, 0.02, 0.9997, 0.0))
    for st in (2, -1, 7):
        s.car(speed=8.0, heading=60.0)
        s.add("new")
        s.add("sst", st & M32)
        s.add("sds", F(30.0))
        frames(2)

    # ---- a long random run
    s.tag("random")
    for run in range(12):
        s.add("lvl", rnd.randrange(3))
        s.cartype(t=rnd.choice((4, 31, 32, 33, 34, 7)),
                  cog=(rnd.uniform(-0.2, 0.2), rnd.uniform(-0.2, 0.2),
                       rnd.uniform(0.3, 0.6), 0.0),
                  z3=rnd.uniform(-0.3, 0.0),
                  radius=[rnd.uniform(0.3, 0.4) for _ in range(4)])
        g = (rnd.uniform(-2.0, 2.0), rnd.uniform(-0.1, 0.1),
             rnd.uniform(-0.1, 0.1))
        nn = (rnd.uniform(-0.1, 0.1), rnd.uniform(-0.1, 0.1), 0.99,
              rnd.uniform(-1.0, 1.0))
        s.ground(gz=g[0], gx=g[1], gy=g[2],
                 sx=rnd.choice((1e9, rnd.uniform(-50.0, 50.0))),
                 sz=rnd.choice((0.5, 2.5, -3.0)),
                 found=rnd.choice((1, 1, 1, 0)), n=nn)
        s.car(pos=(rnd.uniform(-50.0, 50.0), rnd.uniform(-50.0, 50.0),
                   rnd.uniform(-1.0, 3.0), 0.0),
              heading=rnd.uniform(-180.0, 180.0),
              speed=rnd.uniform(-10.0, 60.0),
              steer=rnd.randrange(65536))
        s.add("new")
        s.add("sst", rnd.choice((0, 1)))
        for i in range(25):
            k = rnd.random()
            if k < 0.2:
                s.add("sds", F(rnd.uniform(-20.0, 95.0)))
            elif k < 0.35:
                s.add("sda", rnd.randrange(65536))
            elif k < 0.5:
                s.add("sdv", F(rnd.uniform(-60.0, 60.0)),
                      F(rnd.uniform(-60.0, 60.0)), F(rnd.uniform(-5.0, 5.0)),
                      F(rnd.uniform(-1.0, 1.0)))
            elif k < 0.55:
                s.add("sst", rnd.choice((0, 1)))
            elif k < 0.6:
                s.add("smb", F(rnd.uniform(5.0, 60.0)))
            s.add("move", F(f32(rnd.choice((1.0 / 30.0, 1.0 / 60.0, 0.1)))))
            s.add("dump")

    # ---- the edges
    flat = dict(n=(0.0, 0.0, 1.0, 0.0))
    s.tag("ground high and low")
    s.add("lvl", 2)
    s.cartype()
    for gz in (500.0, -500.0):
        s.ground(gz=gz, **flat)
        s.car(pos=(10.0, 10.0, gz, 0.0), speed=5.0)
        s.add("new")
        s.add("sds", F(5.0))
        frames(2)

    # NaN past a step in x, then in the last sample alone, below y.
    s.tag("ground NaN past a step")
    s.ground(gz=0.5, sx=100.5, sz=float("nan"), **flat)
    s.car(pos=(100.0, 10.0, 1.0, 0.0), speed=0.0, heading=0.0, vz=0.0)
    s.add("new")
    frames(2)
    s.ground(gz=0.5, sz=float("nan"), sy=9.5, **flat)
    s.car(pos=(100.0, 10.0, 1.0, 0.0), speed=0.0, heading=0.0, vz=0.0)
    s.add("new")
    frames(2)

    # A slope where ((e1 - e0) - (e2 - e0)) and e1 - e2 round apart.
    s.tag("ground rounding")
    s.ground(gz=0.2702261209487915, gx=-0.8219885230064392, **flat)
    s.car(pos=(-0.641567587852478, 5.0, 1.0, 0.0), speed=0.0, heading=0.0,
          vz=0.0, vw=0.0)
    s.add("new")
    frames(1)

    s.tag("into the ground at 4")
    s.ground(**flat)
    s.car(speed=10.0, heading=0.0, vz=4.0)
    s.add("new")
    s.add("sds", F(10.0))
    frames(2)

    # Braking at exactly 0.3 of fMaxBrakingAccel, the ramp at 0.5: Brake
    # stays. Then gently with the ramp full at once: Brake is set.
    s.tag("brake shown edges")
    t = f32(40.0 * f32(0.3))
    s.car(speed=0.0, fs=0.0, heading=0.0)
    s.add("new")
    s.add("sds", F(f32(-t / 4.0)))
    frames(1, dt=0.25)
    s.car(speed=10.0, fs=10.0, heading=0.0)
    s.add("new")
    s.add("sds", F(9.0))
    frames(1, dt=1.0)

    s.tag("reverse to a stop")
    s.car(speed=-20.0, heading=0.0)
    s.add("new")
    s.add("sds", F(0.0))
    frames(3)

    # The car moved by something else between frames.
    s.tag("moved between frames")
    s.ground(gz=1.0, gx=0.01, gy=-0.02, n=(-0.01, 0.02, 0.9997, 0.0))
    for st in (0, 1):
        s.car(speed=10.0, heading=0.0)
        s.add("new")
        s.add("sst", st)
        s.add("sds", F(12.0))
        s.add("sdv", F(12.0), F(1.0), F(0.0), F(0.0))
        frames(1)
        s.set("cs", "angle", 0, bam(45.0))
        s.vec("cs", "vel", (3.0, 7.0, 0.5, 0.25))
        frames(2)

    s.tag("translate over max")
    s.ground(n=(0.6, 0.0, 0.8, 0.0))
    s.car(speed=120.0, fs=120.0, heading=90.0, vz=-2.0, vw=0.5)
    s.add("new")
    s.add("sst", 1)
    s.add("sdv", F(0.0), F(150.0), F(0.0), F(0.0))
    frames(3)

    # Too slow for dot3 to see: the direction is FLT_MAX times it.
    s.tag("translate denormal")
    s.ground(**flat)
    s.car(speed=0.0, fs=0.0, heading=0.0, vz=0.0, vw=0.0)
    s.vec("cs", "vel", (1e-40, 3e-41, 0.0, 0.0))
    s.add("new")
    s.add("sst", 1)
    s.add("sdv", F(1e-40), F(3e-41), F(0.0), F(0.0))
    frames(1)

    s.tag("cog fourth word")
    s.cartype(cog=(0.0, 0.1, 0.45, 0.5))
    s.ground(gz=1.0, **flat)
    s.car(speed=5.0)
    s.add("new")
    frames(1)
    s.cartype()

    # ---- the destructor, through the table and directly
    s.tag("dtor")
    for flags in (0, 1, 3):
        s.add("new")
        s.add("del", flags)
    for flags in (0, 1):
        s.add("new")
        s.add("dtor", flags, 0x1234)
    return s.lines


# ================================================================== model

class Model(object):
    def __init__(self):
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        self.out = []
        self.mv = self.block(MV_SIZE + 16, 0xcd)
        self.car = self.block(CAR_SIZE, 0)
        self.cti = self.block(CTI_SIZE, 0)
        self.drv = self.block(DRV_SIZE, 0)
        self.mgr = self.block(MGR_SIZE, 0)
        self.scr = self.block(64, 0)
        e.put32(self.car + 12, self.cti)
        e.put32(self.car + 44, self.drv)
        e.put32(G_COPMGR, self.mgr)
        self.base = {"mv": self.mv, "cs": self.car + CS, "car": self.car,
                     "drv": self.drv, "cti": self.cti}
        self.gr = dict(gz=0.0, gx=0.0, gy=0.0, sx=0.0, sz=0.0, found=0,
                       n=(0, 0, 0, 0), terrain=0, sy=0.0)
        for a, fn in ((S_ELEV, self.s_elev), (S_GEOM, self.s_geom),
                      (S_WMAT, self.s_wmat), (S_TOUCH, self.s_touch),
                      (S_TERRAIN, self.s_terrain), (S_RPM, self.s_rpm),
                      (S_CMDTOR, self.s_cmdtor)):
            e.stub(a, fn)

    def block(self, size, fill):
        p = self.e.alloc(size, align=16)
        self.e.write(p, bytes([fill]) * size)
        return p

    def emit(self, line):
        self.out.append(line)

    def lab(self, a):
        a &= M32
        if a == 0:
            return "null"
        return {self.mv: "mv", self.mv + 32: "ta", self.mv + 96: "mvn",
                self.car: "car", self.car + CS: "cs",
                self.car + TC: "tc"}.get(a, "?")

    def fl(self, a):
        return bf(self.e.u32(a))

    # ---- stubs

    def s_elev(self, em):
        e, r = self.e, self.e.reg
        tc, pt, ter, nrm, fnd = (r[4] & M32, r[5] & M32, r[6] & M32,
                                 r[7] & M32, r[8] & M32)
        g = self.gr
        x, y, z = self.fl(pt), self.fl(pt + 4), self.fl(pt + 8)
        el = f32(f32(f32(g["gx"] * x) + f32(g["gy"] * y)) + g["gz"])
        if x > g["sx"] or y < g["sy"]:
            el = f32(el + g["sz"])
        self.emit("  elev %s %s %s %s %s %s %s -> %s"
                  % (self.lab(tc), hx(fb(x)), hx(fb(y)), hx(fb(z)),
                     "t" if ter else "-", self.lab(nrm),
                     "f" if fnd else "-", hx(fb(el))))
        if ter:
            e.put32(ter, g["terrain"] & M32)
        if nrm:
            if g["found"]:
                for k in range(4):
                    e.put32(nrm + 4 * k, g["n"][k])
            else:
                e.put32(nrm, 0)
                e.put32(nrm + 4, 0)
                e.put32(nrm + 8, fb(-1.0))
        if fnd:
            e.put32(fnd, g["found"] & M32)
        e.fpr[0] = fb(el)

    def s_geom(self, em):
        self.emit("  geom %s" % self.lab(self.e.reg[4]))

    def s_wmat(self, em):
        self.emit("  wmat %s" % self.lab(self.e.reg[4]))

    def s_touch(self, em):
        r = self.e.reg
        self.emit("  touch %s %d %d" % (self.lab(r[4]), s32(r[5]),
                                         s32(r[6] & 0xff) if (r[6] & 0xff) < 128
                                         else (r[6] & 0xff) - 256))

    def s_terrain(self, em):
        r = self.e.reg
        self.emit("  terrain %s %d %d" % (self.lab(r[4]), s32(r[5]),
                                           s32(r[6])))

    def s_rpm(self, em):
        self.emit("  rpm %s" % self.lab(self.e.reg[4]))

    def s_cmdtor(self, em):
        r = self.e.reg
        self.emit("  cmdtor %s %d %08x" % (self.lab(r[4]), s32(r[5]),
                                            self.e.u32((r[4] & M32) + 4)))

    # ---- the fields

    def group(self, obj, name):
        for g in GROUPS[obj]:
            if g[0] == name:
                return g
        raise KeyError("%s.%s" % (obj, name))

    def show(self, obj):
        e, base = self.e, self.base[obj]
        for name, off, n, kind in GROUPS[obj]:
            vals = []
            for k in range(n):
                if kind == "h":
                    a = base + off + 2 * k
                    vals.append("%d" % (e.u8(a) | (e.u8(a + 1) << 8)))
                elif kind == "f":
                    vals.append(hx(e.u32(base + off + 4 * k)))
                else:
                    vals.append("%08x" % e.u32(base + off + 4 * k))
            self.emit("  %s.%s %s" % (obj, name, " ".join(vals)))

    # ---- the ops

    def vcall(self, slot, *args):
        e = self.e
        vt = e.u32(self.mv + 4)
        delta = e.u32(vt + slot) & 0xffff
        if delta & 0x8000:
            delta -= 0x10000
        fn = e.u32(vt + slot + 4)
        return e.call(fn, (self.mv + delta) & M32, *args, limit=4000000)

    def op(self, a):
        e, o = self.e, a[0]
        n = [int(x, 0) for x in a[1:] if x[:1] in "-0123456789"]
        if o == "tag":
            self.emit("# %s" % a[1])
        elif o == "set":
            name, off, cnt, kind = self.group(a[1], a[2])
            i, v = int(a[3], 0), int(a[4], 0) & M32
            addr = self.base[a[1]] + off
            if kind == "h":
                e.write(addr + 2 * i, struct.pack("<H", v & 0xffff))
            else:
                e.put32(addr + 4 * i, v)
        elif o == "ground":
            v = [int(x, 0) & M32 for x in a[1:]]
            self.gr = dict(gz=bf(v[0]), gx=bf(v[1]), gy=bf(v[2]),
                           sx=bf(v[3]), sz=bf(v[4]), found=s32(v[5]),
                           n=tuple(v[6:10]), terrain=s32(v[10]),
                           sy=bf(v[11]))
        elif o == "lvl":
            e.put32(self.mgr + MGR_LEVEL, n[0] & M32)
        elif o == "new":
            e.write(self.mv, b"\xcd" * MV_SIZE)
            r = e.call(F_CTOR, self.mv, self.car, limit=100000)
            self.emit("new -> %s %08x" % (self.lab(r), e.u32(self.mv + 4)))
        elif o == "move":
            e.fpr[12] = n[0] & M32
            self.vcall(VT_MOVE)
            self.emit("move -> %s" % hx(e.fpr[0]))
        elif o == "del":
            self.vcall(VT_DTOR, n[0] & M32)
            self.emit("del")
        elif o == "dtor":
            e.put32(self.mv + 4, n[1] & M32)
            e.call(F_DTOR, self.mv, n[0] & M32, limit=100000)
            self.emit("dtor")
        elif o == "cfa":
            e.fpr[12] = n[0] & M32
            e.fpr[13] = n[1] & M32
            e.call(F_CFA, self.mv, limit=100000)
            face = e.u8(self.mv + 40) | (e.u8(self.mv + 41) << 8)
            self.emit("cfa -> %s %d" % (hx(e.fpr[0]), face))
        elif o == "rmta":
            e.call(F_RMTA, self.mv, limit=100000)
            self.emit("rmta %s" % hx(e.u32(self.mv + 60)))
        elif o == "gta":
            self.emit("gta -> %s" % self.lab(e.call(F_GTA, self.mv)))
        elif o == "air":
            self.emit("air -> %d" % e.call(F_AIR, self.mv))
        elif o in ("smt", "smb", "sbm", "sds"):
            e.fpr[12] = n[0] & M32
            e.call({"smt": F_SMT, "smb": F_SMB, "sbm": F_SBM,
                    "sds": F_SDS}[o], self.mv)
        elif o == "gms":
            e.call(F_GMS, self.mv)
            self.emit("gms -> %s" % hx(e.fpr[0]))
        elif o == "sdv":
            for k in range(4):
                e.put32(self.scr + 4 * k, n[k] & M32)
            e.call(F_SDV, self.mv, self.scr)
        elif o == "sda":
            e.call(F_SDA, self.mv, n[0] & 0xffff)
        elif o == "sst":
            e.call(F_SST, self.mv, n[0] & M32)
        elif o == "dump":
            self.emit("dump")
            for obj in ("mv", "cs", "car", "drv"):
                self.show(obj)
        else:
            raise ValueError("bad op %s" % o)

    def run(self, lines):
        for line in lines:
            self.op(line.split("|"))
        return self.out


def model(lines):
    return Model().run(lines)


# ================================================================== build

def build_harness(tmp, name="copmover_test"):
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


def write_script(d, lines):
    sc = Path(d) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    return sc


# ============================================================= mutations

C = CMC

MUTATIONS = [
    # ---- the tuning
    ("base_speed", C, "84.9351806640625f", "84.9351f"),
    ("brake_shown", C, "0.3f               // gp-29504", "0.25f  // gp-29504"),
    ("elev_low", C, "1000000.0f         // gp-29496", "100.0f  // gp-29496"),
    ("elev_high", C, "-1000000.0f        // gp-29492", "-100.0f  // gp-29492"),
    ("rad_to_bam", C, "10435.66796875f", "10430.0f"),
    ("turn_slope", C, "-9000.0f ", "-9500.0f "),
    ("turn_limit", C, "12000.0f           // gp-29480",
     "12500.0f  // gp-29480"),
    ("turn_gain", C, "0.3f               // gp-29472", "0.35f  // gp-29472"),
    ("braking_accel", C, "40.0f              // 42200000",
     "45.0f  // 42200000"),
    ("max_transverse", C, "35.0f              // 420c0000",
     "30.0f  // 420c0000"),
    ("max_jerk", C, "150.0f             // 43160000",
     "140.0f  // 43160000"),
    ("into_ground", C, "4.0f               // 40800000",
     "3.0f  // 40800000"),
    ("max_step", C, "2.0f               // 40000000",
     "1.5f  // 40000000"),
    ("dir_scale", C, "65536.0f           // 47800000",
     "65535.0f  // 47800000"),
    ("turn_rate", C, "(0x780000 / 360)", "(0x780000 / 361)"),
    ("offset_easy", C, "-4.470272541046143f", "-4.47f"),
    ("offset_medium", C, "-2.2351362705230713f", "-2.235f"),
    ("offset_hard", C, "    0.0f\n};", "    0.5f\n};"),
    ("sample_px", C, "{ 1.0f, 0.0f }, { -1.0f", "{ 1.5f, 0.0f }, { -1.0f"),
    ("sample_nx", C, "{ -1.0f, 0.0f },", "{ -1.5f, 0.0f },"),
    ("sample_py", C, "{ 0.0f, 1.0f }, { 0.0f, -1.0f }",
     "{ 0.0f, 1.5f }, { 0.0f, -1.0f }"),
    ("sample_ny", C, "{ 0.0f, -1.0f }\n", "{ 0.0f, -1.5f }\n"),
    ("sample_centre", C, "{ 0.0f, 0.0f }, { 1.0f",
     "{ 0.0f, 0.25f }, { 1.0f"),
    # ---- the idioms
    ("dot3_order", C, "return (a->x * b->x + a->y * b->y) + a->z * b->z;",
     "return a->x * b->x + (a->y * b->y + a->z * b->z);"),
    ("min_nan", C, "return b < a ? b : a;", "return a < b ? a : b;"),
    ("max_nan", C, "return a < b ? b : a;", "return a > b ? a : b;"),
    # ---- the constructor
    ("ctor_no_vptr", C,
     "    m->Mover._vtable = COPMOVER_VTABLE;\n    m->pCar = car;\n",
     "    m->pCar = car;\n"),
    ("ctor_no_car", C, "    m->pCar = car;\n    m->v3Velocity",
     "    m->v3Velocity"),
    ("ctor_no_vel", C, "    m->v3Velocity = car->State.Velocity;\n", ""),
    ("ctor_no_dvel", C, "    m->v3DesiredVelocity = m->v3Velocity;\n", ""),
    ("ctor_state", C, "    m->State = eCMS_STEERING;\n",
     "    m->State = eCMS_TRANSLATING;\n"),
    ("ctor_no_dspeed", C,
     "    m->fDesiredSpeed = car->State.ForwardSpeed;\n", ""),
    ("ctor_no_dangle", C,
     "    m->aDesiredFacingAngle = car->State.Angle;\n", ""),
    ("ctor_no_base", C, "    m->fBaseMaxSpeed = CM_BASE_MAX_SPEED;\n", ""),
    ("ctor_no_speed", C, "    m->fSpeed = car->State.ForwardSpeed;\n", ""),
    ("ctor_no_face", C, "    m->aFacingAngle = car->State.Angle;\n", ""),
    ("ctor_no_rmta", C,
     "    copmover_reset_max_throttle_accel(m);\n\n", "\n"),
    ("ctor_no_brake", C, "    m->fMaxBrakingAccel = CM_BRAKING_ACCEL;\n", ""),
    ("ctor_no_tax", C, "    m->v2TransverseAccel.x = 0.0f;\n", ""),
    ("ctor_no_tay", C, "    m->v2TransverseAccel.y = 0.0f;\n", ""),
    ("ctor_normal_z", C,
     "    m->v3GroundNormal.z = 1.0f;\n    m->v3GroundNormal.pad = 0.0f;\n"
     "    m->bIsAirborne = 0;\n",
     "    m->v3GroundNormal.z = 0.5f;\n    m->v3GroundNormal.pad = 0.0f;\n"
     "    m->bIsAirborne = 0;\n"),
    ("ctor_normal_x", C,
     "    m->v3GroundNormal.x = 0.0f;\n    m->v3GroundNormal.y = 0.0f;\n"
     "    m->v3GroundNormal.z = 1.0f;\n    m->v3GroundNormal.pad = 0.0f;\n"
     "    m->bIsAirborne = 0;\n",
     "    m->v3GroundNormal.y = 0.0f;\n"
     "    m->v3GroundNormal.z = 1.0f;\n    m->v3GroundNormal.pad = 0.0f;\n"
     "    m->bIsAirborne = 0;\n"),
    ("ctor_no_air", C,
     "    m->bIsAirborne = 0;\n    m->New64 = 0.0f;\n",
     "    m->New64 = 0.0f;\n"),
    ("ctor_no_ramp", C,
     "    m->New64 = 0.0f;\n    return m;", "    return m;"),
    # ---- the destructor
    ("dtor_no_vptr", C,
     "    m->Mover._vtable = COPMOVER_VTABLE;\n    carmover_destroy",
     "    carmover_destroy"),
    ("dtor_flags", C, "carmover_destroy(&m->Mover, flags);",
     "carmover_destroy(&m->Mover, flags & 1);"),
    # ---- ResetMaxThrottleAccel
    ("rmta_4", C, "        m->fMaxThrottleAccel = 11.25f;",
     "        m->fMaxThrottleAccel = 11.0f;"),
    ("rmta_31", C, "    case 31:", "    case 30:"),
    ("rmta_32", C, "    case 32:\n    case 33:", "    case 33:"),
    ("rmta_33_falls", C, "        m->fMaxThrottleAccel = 15.0f;\n        break;",
     "        m->fMaxThrottleAccel = 15.0f;"),
    ("rmta_34", C, "        m->fMaxThrottleAccel = 14.25f;",
     "        m->fMaxThrottleAccel = 14.0f;"),
    ("rmta_default", C, "    default:\n        break;",
     "    default:\n        m->fMaxThrottleAccel = 0.0f;\n        break;"),
    # ---- the braking ramp
    ("ramp_rate", C, "m->New64 + (dt + dt);", "m->New64 + dt;"),
    ("ramp_no_store", C, "    m->New64 = r;\n", ""),
    ("ramp_le", C, "    if (1.0f < r)", "    if (1.0f <= r)"),
    ("ramp_no_cap", C, "    if (1.0f < r)\n        m->New64 = 1.0f;\n", ""),
    ("ramp_return", C, "return m->fMaxBrakingAccel * m->New64;",
     "return m->fMaxBrakingAccel * r;"),
    # ---- hold_to_ground
    ("htg_order", C,
     "    m->v3Velocity.z = m->v3Velocity.z - m->v3GroundNormal.z * k;\n"
     "    m->v3Velocity.x = vx - m->v3GroundNormal.x * k;\n",
     "    m->v3Velocity.x = vx - m->v3GroundNormal.x * k;\n"
     "    m->v3Velocity.z = m->v3Velocity.z - m->v3GroundNormal.z * k;\n"),
    ("htg_no_z", C,
     "    m->v3Velocity.z = m->v3Velocity.z - m->v3GroundNormal.z * k;\n", ""),
    ("htg_y_sign", C, "    m->v3Velocity.y = vy - m->v3GroundNormal.y * k;",
     "    m->v3Velocity.y = vy + m->v3GroundNormal.y * k;"),
    ("htg_no_clamp", C, "    k = min_f(dot, CM_MAX_INTO_GROUND);",
     "    k = dot;"),
    ("htg_air_le", C, "    if (CM_MAX_INTO_GROUND < dot)",
     "    if (CM_MAX_INTO_GROUND <= dot)"),
    ("htg_air_k", C, "    if (CM_MAX_INTO_GROUND < dot)",
     "    if (CM_MAX_INTO_GROUND < k)"),
    # ---- STEERING
    ("st_no_cfa", C,
     "    copmover_calculate_facing_angle(m, max_speed, dt);\n    speed",
     "    speed"),
    ("st_no_angle", C,
     "    cs->Angle = m->aFacingAngle;\n    a = ", "    a = "),
    ("st_accel_dt", C, "a = (m->fDesiredSpeed - speed) / dt;",
     "a = (m->fDesiredSpeed - speed) * dt;"),
    ("st_brake_le", C, "    if (a < 0.0f) {", "    if (a <= 0.0f) {"),
    ("st_lim_le", C, "        if (lim < mag)\n", "        if (lim <= mag)\n"),
    ("st_lim_no", C, "            a = a * (lim / mag);\n", ""),
    ("st_shown_le", C,
     "        if (m->fMaxBrakingAccel * CM_BRAKE_SHOWN < mag ||",
     "        if (m->fMaxBrakingAccel * CM_BRAKE_SHOWN <= mag ||"),
    ("st_shown_no_full", C,
     " < mag || m->New64 == 1.0f)", " < mag)"),
    ("st_shown_clamped", C,
     "            car->pCarDriver->Brake = mag / m->fMaxBrakingAccel;",
     "            car->pCarDriver->Brake = fabsf(a) / m->fMaxBrakingAccel;"),
    ("st_no_ramp_reset", C,
     "        m->New64 = 0.0f;\n        if (throttle < mag) {",
     "        if (throttle < mag) {"),
    ("st_thr_le", C, "        if (throttle < mag) {",
     "        if (throttle <= mag) {"),
    ("st_no_nitro", C,
     "            car->NitroEffectFlag = 1;\n            a = a * (throttle",
     "            a = a * (throttle"),
    ("st_thr_no", C, "            a = a * (throttle / mag);\n", ""),
    ("st_no_brake0", C,
     "        }\n        car->pCarDriver->Brake = 0.0f;\n    }\n\n    s = ",
     "        }\n    }\n\n    s = "),
    ("st_speed", C, "    s = speed + a * dt;", "    s = m->fSpeed + a;"),
    ("st_max_le", C, "    if (max_speed < fabsf(s))",
     "    if (max_speed <= fabsf(s))"),
    ("st_max_no", C,
     "        m->fSpeed = s * (max_speed / fabsf(s));\n", ""),
    ("st_no_fs", C, "    cs->ForwardSpeed = m->fSpeed;\n", ""),
    ("st_sincos", C, "hold_to_ground(m, s * bCosBam(ang), s * bSinBam(ang));",
     "hold_to_ground(m, s * bSinBam(ang), s * bCosBam(ang));"),
    ("st_vmag", C,
     "    cs->VelocityMagnitude = sqrtf(dot3(&m->v3Velocity, &m->v3Velocity));"
     "\n    cs->MatrixValid = 0;\n}\n\n// eCMS_TRANSLATING",
     "    cs->VelocityMagnitude = fabsf(m->fSpeed);"
     "\n    cs->MatrixValid = 0;\n}\n\n// eCMS_TRANSLATING"),
    ("st_no_mv", C,
     "    cs->MatrixValid = 0;\n}\n\n// eCMS_TRANSLATING",
     "}\n\n// eCMS_TRANSLATING"),
    # ---- TRANSLATING
    ("tr_unit_div", C, "    uy = ee_div(m->v3Velocity.y, len);",
     "    uy = m->v3Velocity.y / len;"),
    ("tr_unit_swap", C, "    ux = ee_div(m->v3Velocity.x, len);",
     "    ux = ee_div(m->v3Velocity.y, len);"),
    ("tr_along", C, "    along = dvx * ux + dvy * uy;",
     "    along = dvx * ux - dvy * uy;"),
    ("tr_no_old", C, "    old = m->v2TransverseAccel;\n",
     "    old.x = 0.0f;\n    old.y = 0.0f;\n"),
    ("tr_t_sign", C, "    ty = dvy - ly;", "    ty = dvy + ly;"),
    ("tr_t_le", C, "    if (CM_MAX_TRANSVERSE < n) {",
     "    if (CM_MAX_TRANSVERSE <= n) {"),
    ("tr_t_no", C,
     "        m->v2TransverseAccel.x = tx * k;\n"
     "        m->v2TransverseAccel.y = ty * k;\n", ""),
    ("tr_j_dt", C, "    jx = (m->v2TransverseAccel.x - old.x) / dt;",
     "    jx = (m->v2TransverseAccel.x - old.x);"),
    ("tr_j_le", C, "    if (CM_MAX_JERK < n) {", "    if (CM_MAX_JERK <= n) {"),
    ("tr_j_no", C,
     "        m->v2TransverseAccel.y = old.y + jy * dt;\n"
     "        m->v2TransverseAccel.x = old.x + jx * dt;\n", ""),
    ("tr_j_y", C, "        m->v2TransverseAccel.y = old.y + jy * dt;",
     "        m->v2TransverseAccel.y = old.y + jx * dt;"),
    ("tr_lmag", C, "    lmag = sqrtf(lx * lx + ly * ly);",
     "    lmag = fabsf(along);"),
    ("tr_brake_le", C, "    if (along < 0.0f) {", "    if (along <= 0.0f) {"),
    ("tr_lim_le", C, "        if (lim < lmag) {", "        if (lim <= lmag) {"),
    ("tr_no_shown", C, "            shown = lim;\n", ""),
    ("tr_lim_no", C,
     "            k = lim / lmag;\n            shown = lim;\n"
     "            ly = ly * k;\n            lx = lx * k;\n",
     "            shown = lim;\n"),
    ("tr_shown_unclamped", C,
     "            car->pCarDriver->Brake = shown / m->fMaxBrakingAccel;",
     "            car->pCarDriver->Brake = lmag / m->fMaxBrakingAccel;"),
    ("tr_shown_no_full", C, " < shown || m->New64 == 1.0f)", " < shown)"),
    ("tr_no_ramp_reset", C,
     "        m->New64 = 0.0f;\n        car->pCarDriver->Brake = 0.0f;\n"
     "        if (throttle < lmag) {",
     "        car->pCarDriver->Brake = 0.0f;\n"
     "        if (throttle < lmag) {"),
    ("tr_no_brake0", C,
     "        car->pCarDriver->Brake = 0.0f;\n        if (throttle < lmag) {",
     "        if (throttle < lmag) {"),
    ("tr_thr_le", C, "        if (throttle < lmag) {",
     "        if (throttle <= lmag) {"),
    ("tr_no_nitro", C,
     "            car->NitroEffectFlag = 1;\n            k = throttle / lmag;",
     "            k = throttle / lmag;"),
    ("tr_thr_no", C,
     "            k = throttle / lmag;\n            ly = ly * k;\n"
     "            lx = lx * k;\n",
     "            k = throttle / lmag;\n"),
    ("tr_no_transverse", C,
     "m->v3Velocity.x + (lx + m->v2TransverseAccel.x) * dt,",
     "m->v3Velocity.x + lx * dt,"),
    ("tr_max_le", C, "    if (max_speed < fabsf(len)) {",
     "    if (max_speed <= fabsf(len)) {"),
    ("tr_max_no_z", C, "        m->v3Velocity.z = m->v3Velocity.z * k;\n",
     ""),
    ("tr_max_no_pad", C,
     "        m->v3Velocity.pad = m->v3Velocity.pad * k;\n", ""),
    ("tr_max_no_len", C, "        len = len * k;\n", ""),
    ("tr_fs", C, "    cs->ForwardSpeed = len;",
     "    cs->ForwardSpeed = m->fSpeed;"),
    ("tr_inv_plain", C,
     "    inv = 0.0f + ee_div(1.0f, sqrtf(dot3(&d, &d)));",
     "    inv = 1.0f / sqrtf(dot3(&d, &d));"),
    ("tr_atan_swap", C,
     "ee_trunc_w(d.x * CM_DIR_SCALE), ee_trunc_w(d.y * CM_DIR_SCALE));",
     "ee_trunc_w(d.y * CM_DIR_SCALE), ee_trunc_w(d.x * CM_DIR_SCALE));"),
    ("tr_no_cfa", C,
     "    copmover_calculate_facing_angle(m, max_speed, dt);\n"
     "    cs->Angle = m->aFacingAngle;\n}",
     "    cs->Angle = m->aFacingAngle;\n}"),
    ("tr_no_angle", C,
     "    copmover_calculate_facing_angle(m, max_speed, dt);\n"
     "    cs->Angle = m->aFacingAngle;\n}",
     "    copmover_calculate_facing_angle(m, max_speed, dt);\n}"),
    # ---- Move
    ("mv_no_normal_reset", C,
     "    if (!found) {\n", "    if (0) {\n"),
    ("mv_normal_z", C,
     "        m->v3GroundNormal.z = 1.0f;\n        m->v3GroundNormal.pad",
     "        m->v3GroundNormal.z = -1.0f;\n        m->v3GroundNormal.pad"),
    ("mv_no_face", C, "    m->aFacingAngle = cs->Angle;\n", ""),
    ("mv_no_speed", C, "    m->fSpeed = cs->ForwardSpeed;\n", ""),
    ("mv_no_vel", C, "    m->v3Velocity = cs->Velocity;\n", ""),
    ("mv_level", C, "CopMaxSpeedOffset[pCopManager->nDifficultyLevel];",
     "CopMaxSpeedOffset[2];"),
    ("mv_no_air0", C,
     "    m->bIsAirborne = 0;\n    throttle", "    throttle"),
    ("mv_throttle", C,
     "    throttle = ee_div(-m->fMaxThrottleAccel, max_speed) * fabsf(m->fSpeed)",
     "    throttle = ee_div(-m->fMaxThrottleAccel, max_speed) * m->fSpeed"),
    ("mv_dspeed_le", C, "    if (max_speed < m->fDesiredSpeed)",
     "    if (max_speed <= m->fDesiredSpeed)"),
    ("mv_no_dspeed", C,
     "        m->fDesiredSpeed = max_speed;\n", ""),
    ("mv_no_nitro0", C, "    car->NitroEffectFlag = 0;\n\n", "\n"),
    ("mv_translating_default", C,
     "    else if (m->State == eCMS_TRANSLATING)", "    else"),
    ("mv_pos_dt", C,
     "    cs->Position.y = m->v3Velocity.y * dt + cs->Position.y;",
     "    cs->Position.y = m->v3Velocity.y + cs->Position.y;"),
    ("mv_pos_no_pad", C,
     "    cs->Position.pad = m->v3Velocity.pad * dt + cs->Position.pad;\n", ""),
    ("mv_air_skip", C, "    if (!m->bIsAirborne) {", "    if (1) {"),
    ("mv_sample_z", C, "            p.z = cs->Position.z;",
     "            p.z = 0.0f;"),
    ("mv_sample_pad", C, "            p.pad = 0.0f;",
     "            p.pad = cs->Position.pad;"),
    ("mv_step_le", C, "    if (fabsf(hi - lo) <= CM_MAX_STEP) {",
     "    if (fabsf(hi - lo) < CM_MAX_STEP) {"),
    ("mv_sx", C,
     "sx = (((e[1] - e[0]) - (e[2] - e[0])) * 0.5f) * CM_RAD_TO_BAM;",
     "sx = ((e[1] - e[2]) * 0.5f) * CM_RAD_TO_BAM;"),
    ("mv_sy_half", C,
     "sy = (((e[3] - e[0]) - (e[4] - e[0])) * 0.5f) * CM_RAD_TO_BAM;",
     "sy = (((e[3] - e[0]) - (e[4] - e[0]))) * CM_RAD_TO_BAM;"),
    ("mv_about_y", C,
     "about_y = (uint16_t)(0u - (uint32_t)ee_trunc_w(sx));",
     "about_y = (uint16_t)ee_trunc_w(sx);"),
    ("mv_about_x", C, "about_x = (uint16_t)ee_trunc_w(sy);",
     "about_x = (uint16_t)(0u - (uint32_t)ee_trunc_w(sy));"),
    ("mv_wheel", C, "cti->Wheels[3].Radius)", "cti->Wheels[2].Radius)"),
    ("mv_wheel_z", C, "- cti->Wheels[3].PositionZ)",
     "+ cti->Wheels[3].PositionZ)"),
    ("mv_cog", C, "                           + cti->CenterOfGravity.z;",
     "                           - cti->CenterOfGravity.z;"),
    ("mv_rot_order", C,
     "            eRotateZ(&mat, &mat, cs->Angle);\n"
     "            eRotateX(&mat, &mat, about_x);\n",
     "            eRotateX(&mat, &mat, about_x);\n"
     "            eRotateZ(&mat, &mat, cs->Angle);\n"),
    ("mv_rot_face", C, "eRotateZ(&mat, &mat, cs->Angle);",
     "eRotateZ(&mat, &mat, m->aDesiredFacingAngle);"),
    ("mv_gp_x", C,
     "cs->GeometryPosition.x = cs->Position.x - cti->CenterOfGravity.x;",
     "cs->GeometryPosition.x = cs->Position.x;"),
    ("mv_gp_pad", C,
     "                cs->Position.pad - cti->CenterOfGravity.pad;",
     "                cs->Position.pad;"),
    ("mv_no_airborne", C,
     "        } else {\n            m->bIsAirborne = 1;\n        }",
     "        }"),
    ("mv_no_geom", C, "    carstate_calculate_geometry_position(cs);\n", ""),
    ("mv_no_av", C, "    cs->AngularVelocity.y = 0.0f;\n", ""),
    ("mv_no_steer", C,
     "    cs->SteeringAngle = car->pCarDriver->Steering;\n", ""),
    ("mv_wav", C, "float w = m->fSpeed / cti->Wheels[i].Radius;",
     "float w = m->fSpeed / cti->Wheels[0].Radius;"),
    ("mv_wang", C, "cs->WheelAngle[i] = cs->WheelAngle[i] + w * dt;",
     "cs->WheelAngle[i] = cs->WheelAngle[i] + w;"),
    ("mv_no_wsh", C, "        cs->WheelSuspensionHeight[i] = 0.0f;\n", ""),
    ("mv_touch", C, "carstate_set_wheel_touching_ground(cs, i, 1);",
     "carstate_set_wheel_touching_ground(cs, i, 0);"),
    ("mv_terrain", C, "carstate_set_wheel_terrain(cs, i, TERRAIN_DEFAULT);",
     "carstate_set_wheel_terrain(cs, i, TERRAIN_DEFAULT + 1);"),
    ("mv_no_slip", C, "        cs->WheelSlip[i].y = 0.0f;\n", ""),
    ("mv_no_tu", C, "        cs->WheelTractionUsage[i] = 0.0f;\n", ""),
    ("mv_no_zf", C, "        cs->WheelZForce[i] = 0.0f;\n", ""),
    ("mv_bo_one", C, "        for (j = 3; j >= 0; j--)",
     "        for (j = 3; j >= 1; j--)"),
    ("mv_no_wmat", C, "    carstate_calculate_wheel_matrices(cs);\n", ""),
    ("mv_no_rpm", C, "    car_compute_fake_rpm(car);\n", ""),
    ("mv_return", C, "    return dt;\n}", "    return 0.0f;\n}"),
    # ---- CalculateFacingAngle
    ("cfa_reverse_le", C, "    if (0.0f <= speed)", "    if (0.0f < speed)"),
    ("cfa_slope_div", C,
     "limit = ee_div(CM_TURN_SLOPE, max_speed) * fabsf(speed)",
     "limit = CM_TURN_SLOPE / max_speed * fabsf(speed)"),
    ("cfa_reverse_limit", C,
     "    else\n        limit = CM_TURN_LIMIT;",
     "    else\n        limit = CM_TURN_LIMIT * 0.5f;"),
    ("cfa_d_unsigned", C,
     "d = (float)(int16_t)(uint16_t)(m->aDesiredFacingAngle - m->aFacingAngle);",
     "d = (float)(uint16_t)(m->aDesiredFacingAngle - m->aFacingAngle);"),
    ("cfa_limit_le", C, "    if (limit < fabsf(d))",
     "    if (limit <= fabsf(d))"),
    ("cfa_limit_no", C, "        d = d * ee_div(limit, fabsf(d));\n", ""),
    ("cfa_rate_abs", C, "    r = d * (fabsf(speed) * CM_TURN_GAIN);",
     "    r = d * (speed * CM_TURN_GAIN);"),
    ("cfa_rate_le", C, "    if (CM_MAX_TURN_RATE < fabsf(r))",
     "    if (CM_MAX_TURN_RATE <= fabsf(r))"),
    ("cfa_rate_sign", C, "(0.0f <= r) ? CM_MAX_TURN_RATE : -CM_MAX_TURN_RATE",
     "(0.0f < r) ? CM_MAX_TURN_RATE : -CM_MAX_TURN_RATE"),
    ("cfa_rate_no", C,
     "        r = (0.0f <= r) ? CM_MAX_TURN_RATE : -CM_MAX_TURN_RATE;\n", ""),
    ("cfa_step_le", C, "    if (fabsf(d) < fabsf(step))",
     "    if (fabsf(d) <= fabsf(step))"),
    ("cfa_step_no", C, "        step = d;\n", ""),
    ("cfa_trunc", C, "m->aFacingAngle + ee_trunc_w(step));",
     "m->aFacingAngle + (int32_t)lrintf(step));"),
    ("cfa_return", C, "    return r;\n}", "    return step;\n}"),
    # ---- the accessors
    ("gta", C, "    return &m->v2TransverseAccel;",
     "    return (const bVector2 *)&m->v3Velocity;"),
    ("air", C, "    return m->bIsAirborne;", "    return m->bIsAirborne + 1;"),
    ("smt", C, "    m->fMaxThrottleAccel = a;\n}",
     "    m->fMaxBrakingAccel = a;\n}"),
    ("smb", C, "    m->fMaxBrakingAccel = a;\n}",
     "    m->fMaxThrottleAccel = a;\n}"),
    ("sbm", C, "    m->fBaseMaxSpeed = s;", "    m->fSpeed = s;"),
    ("gms", C, "    return m->fBaseMaxSpeed;", "    return m->fSpeed;"),
    ("sdv_z", C, "    m->v3DesiredVelocity.z = 0.0f;\n", ""),
    ("sds", C, "    m->fDesiredSpeed = s;", "    m->fDesiredSpeed = -s;"),
    ("sda", C, "    m->aDesiredFacingAngle = a;",
     "    m->aDesiredFacingAngle = (uint16_t)(a + 1);"),
    ("sst", C, "    m->State = s;", "    m->State = s & 1;"),
    # ---- the table
    ("vt_move", C, "vt_install(COPMOVER_VTABLE, copmover_vt, COPMOVER_VT_ENTRIES);",
     "vt_install(COPMOVER_VTABLE, copmover_vt, COPMOVER_VT_ENTRIES - 2);"),
    ("seam", C, "    gCopMoverCtorFn = copmover_construct;",
     "    gCopMoverCtorFn = NULL;"),
]

EQUIVALENT = {
    "ramp_le": "at r == 1 the cap stores the 1 already there",
    "htg_order": "z comes from z and x from vx; neither reads the other",
    "st_lim_le": "at lim == mag the scale is exactly 1",
    "tr_t_le": "at 35 the scale is exactly 1",
    "tr_j_le": "at exactly 150 the scale is 1, and old + j*dt gives the "
               "accel back but for a rounding no script reaches",
    "tr_lim_le": "at lim == lmag shown is lmag either way and the scale 1",
    "tr_thr_le": "at throttle == lmag the scale is exactly 1",
    "tr_max_le": "at |len| == max_speed the scale is exactly 1",
    "mv_dspeed_le": "stores max_speed over max_speed",
    "mv_sample_pad": "GetElevation reads the point's x, y and z only",
    "cfa_reverse_le": "at speed 0 the rate is d * 0, whatever the limit",
    "cfa_limit_le": "at |d| == limit the scale is exactly 1",
    "cfa_rate_le": "at |r| == 21845 r is that already",
    "cfa_rate_sign": "r == 0 is never past 21845",
    "cfa_step_le": "with dt >= 0 the step has d's sign, so |d| == |step| "
                   "is step == d",
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    lines = script()
    base = model(lines)
    indir = tempfile.TemporaryDirectory()
    scp = write_script(indir.name, lines)
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
        todo, SOURCES, "copmover_test",
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

    lines = script()
    got = model(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = write_script(tmp, lines)
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
