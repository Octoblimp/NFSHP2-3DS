#!/usr/bin/env python3
"""Cross-check CopDriver, in 3DS Files/source/copdriver.c, against the retail
image, SLES_507.31, run in mipsemu.

**The model** is retail's own copdriver.obj: CopDriver's constructor
(0x001a1ce8), its destructor (0x001a1e30) and Think (0x001a2110) through the
image's table (0x002b5998), GetPursuitTargetPoint (0x001a1e90), AreWeStuck
(0x001a2a90), FindDriveTargetPointByDistance (0x001a2c30),
GetDriveTargetPointByDLOffsetFromStart (0x001a2ef0) and the accessors
(0x001a32d0 .. 0x001a32e8). Run as shipped under them: CopMover's
ResetMaxThrottleAccel, bToPolar, bNormalize, tPursuitHistory::VelocityAt
(0x0022d080) and CarInRecentCollision (0x00231258). The harness
(tools/src/copdriver_test.c) runs copdriver.c, cardriver.c, copmanager.c,
coputil.c, bmath.c, bvector.c and vtable.c and prints the same lines.

**The stubs**, logged and answered by the same rule on both sides: bMalloc
(the NullDriver's block), TrackedController's constructor (which stores the
car), destructor and Think, DriveTarget's constructor, Clear and
operator=, Car::GetRoutePoint (a route point per car), tAICop's
IsNearPursuitTarget (scripted), InitializeDriveTarget and
UpdateDriveTarget, and the NullDriver's destructor and SetDesiredSpeed,
through its table.

**Compared** are the stubs' logs, every return and written point, and on
`dump` CopDriver's every word, the CopMover words CopDriver writes (but
v3DesiredVelocity's fourth, the image's stack) and the NullDriver's.

    python tools/copdriver_check.py
    python tools/copdriver_check.py --mutate [--only a,b]
    python tools/copdriver_check.py --dump out/copdriver
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

HARNESS = "tools/src/copdriver_test.c"
CDC = "3DS Files/source/copdriver.c"
SOURCES = [HARNESS, CDC,
           "3DS Files/source/cardriver.c",
           "3DS Files/source/copmanager.c",
           "3DS Files/source/coputil.c",
           "3DS Files/source/world.c",
           "3DS Files/source/trackroute.c",
           "3DS Files/source/trackpath.c",
           "3DS Files/source/quickspline.c",
           "3DS Files/source/bchunk.c",
           "3DS Files/source/emath.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c",
           "3DS Files/source/bvector.c",
           "3DS Files/source/bmatrix.c",
           "3DS Files/source/vtable.c"]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = retail_model.RETAIL_GP
G_COPMGR = GP - 15620                   # pCopManager

F_CTOR = 0x001a1ce8
F_DTOR = 0x001a1e30
F_GPTP = 0x001a1e90
F_STUCK = 0x001a2a90
F_FPD = 0x001a2c30
F_GPDL = 0x001a2ef0
F_GRN = 0x001a32d0
F_SPS = 0x001a32d8
F_SST = 0x001a32e0
F_SCI = 0x001a32e8

S_TCCTOR = 0x0023a020
S_TCDTOR = 0x0023a070
S_TCTHINK = 0x0023a088
S_MALLOC = 0x002577c0
S_DTCTOR = 0x0021b918
S_DTCLEAR = 0x0021bbb0
S_DTASSIGN = 0x0021b9a8
S_NEAR = 0x00230bf8
S_INIT = 0x00230638
S_UPDATE = 0x002307d0
S_GETRP = 0x001332d8

VT_COPDRIVER = 0x002b5998
VT_NULLDRIVER = 0x002ae7c0
VT_CARDRIVER = 0x002ae868
VT_NAMES = {VT_COPDRIVER: "copdriver", VT_NULLDRIVER: "nulldriver",
            VT_CARDRIVER: "cardriver"}
S_NDDTOR = 0x00136be8
S_NDSPEED = 0x00136bd8

VT_DTOR, VT_THINK = 8, 32
ND_DTOR, ND_SPEED = 8, 56

COP_SLOT = 3
CD_SIZE = 76
ND_SIZE = 560
CAR_SIZE = 2304
CTI_SIZE = 1536
MV_SIZE = 128
DCB_SIZE = 64
AIC_SIZE = 96
PUR_SIZE = 1600
MGR_SIZE = 10528
RP_SIZE = 112
CS = 64                                 # the car's CarState
MGR_LEVEL = 10476
MGR_COPS = 16
PUR_FAR, PUR_NEAR, PUR_HIST = 48, 576, 1104

# The groups each object dumps, and `set` writes: name, the image's
# offset, count and kind (f a float, h a u16, w a word, b a byte). The
# harness has the same lists by field.
GROUPS = {
    "cd": [("st", 36, 3, "w"), ("tm", 48, 3, "f"), ("idx", 60, 1, "w"),
           ("steer", 64, 2, "f"), ("cls", 72, 1, "w")],
    "mv": [("face", 40, 2, "h"), ("spd", 44, 5, "f"), ("dvel", 80, 3, "f"),
           ("st", 116, 1, "w")],
    "nd": [("steer", 528, 1, "h"), ("thr", 532, 3, "f"), ("gear", 544, 2, "w"),
           ("nitro", 552, 1, "w")],
    "cop": [("pos", CS + 32, 2, "f"), ("vel", CS + 48, 2, "f"),
            ("angle", CS + 868, 1, "h"), ("fs", CS + 896, 1, "f"),
            ("vm", CS + 900, 1, "f"), ("mode", 36, 1, "w"),
            ("col", -1, 1, "b")],
    "ch": [("pos", CS + 32, 2, "f"), ("vel", CS + 48, 2, "f"),
           ("angle", CS + 868, 1, "h"), ("fs", CS + 896, 1, "f"),
           ("vm", CS + 900, 1, "f")],
    "ctic": [("type", 1332, 1, "w"), ("cls", 230, 1, "b")],
    "ctih": [("type", 1332, 1, "w"), ("cls", 230, 1, "b")],
    "aic": [("ls", 12, 4, "w"), ("n48", 48, 2, "f")],
    "rpc": [("pos", 0, 2, "f"), ("dir", 12, 2, "f"), ("spd", 90, 21, "b")],
    "rph": [("pos", 0, 2, "f"), ("dir", 12, 2, "f"), ("spd", 90, 21, "b")],
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


def bam(deg):
    return int(round(deg * 65536.0 / 360.0)) & 0xffff


# ============================================================== the script

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

    def car(self, who, pos=(0.0, 0.0), heading=0.0, speed=0.0, fs=None,
            vm=None):
        a = math.radians(heading)
        self.vec(who, "pos", pos)
        self.vec(who, "vel", (f32(speed * math.cos(a)),
                              f32(speed * math.sin(a))))
        self.set(who, "angle", 0, bam(heading))
        self.set(who, "fs", 0, f32(speed if fs is None else fs))
        self.set(who, "vm", 0, f32(abs(speed) if vm is None else vm))

    def rp(self, who, pos=(0.0, 0.0), heading=0.0, speeds=None):
        a = math.radians(heading)
        self.vec(who, "pos", pos)
        self.vec(who, "dir", (f32(math.cos(a)), f32(math.sin(a))))
        if speeds is None:
            speeds = [20 + 3 * k for k in range(21)]
        for k, v in enumerate(speeds):
            self.set(who, "spd", k, v & 0xff)

    def pts(self, target, points):
        flat = []
        for p in points:
            p = tuple(p) + (0.0,) * (4 - len(p))
            flat += [F(f32(v)) for v in p[:4]]
        self.add("pts", target, len(points), *flat)

    def hist(self, entries):
        flat = []
        for vx, vy, t in entries:
            flat += [F(f32(vx)), F(f32(vy)), F(f32(t))]
        self.add("hist", len(entries), *flat)

    def ls(self, state, desired, sub, dsub=0):
        for i, v in enumerate((state, desired, sub, dsub)):
            self.set("aic", "ls", i, v & M32)

    def fpd(self, target, pos, dist, off=(0.0, 0.0)):
        self.add("fpd", target, F(f32(pos[0])), F(f32(pos[1])), F(f32(dist)),
                 F(f32(off[0])), F(f32(off[1])))

    def gpdl(self, target, off):
        self.add("gpdl", target, F(f32(off[0])), F(f32(off[1])))


def line_points(rnd, n, start=(0.0, 0.0), heading=0.0, step=8.0, wiggle=20.0,
                dup=False):
    pts = []
    x, y = start
    h = heading
    for i in range(n):
        pts.append((x, y, rnd.uniform(-2.0, 2.0), rnd.uniform(-1.0, 1.0)))
        if dup and rnd.random() < 0.2:
            continue
        h += rnd.uniform(-wiggle, wiggle)
        s = step * rnd.uniform(0.5, 1.5)
        x += s * math.cos(math.radians(h))
        y += s * math.sin(math.radians(h))
    return pts


def script():
    s = Script()
    rnd = random.Random(4121)

    s.tag("setup")
    s.add("lvl", 2)
    s.set("ctic", "type", 0, 32)
    s.set("ctic", "cls", 0, 3)
    s.set("ctih", "type", 0, 7)
    s.set("ctih", "cls", 0, 2)
    s.set("cop", "mode", 0, 5)
    s.set("cop", "col", 0, 0)
    s.add("pursuit", 1)
    s.add("player", "ch", 1)
    s.add("player", "cop", 0)
    s.ls(6, 6, 3)
    s.vec("aic", "n48", (0.0, 0.0))
    s.car("cop", pos=(0.0, 0.0), heading=0.0, speed=20.0)
    s.car("ch", pos=(30.0, 2.0), heading=5.0, speed=25.0)
    s.rp("rpc", pos=(-5.0, -3.0), heading=0.0)
    s.rp("rph", pos=(25.0, -1.0), heading=3.0)
    s.set("mv", "spd", 2, 84.9351806640625)

    # ---- the constructor on each car type
    s.tag("ctor by type")
    for t in (4, 31, 32, 33, 34, 0, 3, 5, 30, 35, 36, -1, 100):
        s.set("ctic", "type", 0, t & M32)
        s.add("new")
        s.add("dump")
    s.set("ctic", "type", 0, 32)

    # ---- the accessors
    s.tag("accessors")
    s.add("new")
    s.add("grn")
    s.add("sps", F(17.5))
    s.add("sst", 3)
    s.add("sci", 7)
    s.add("dump")
    s.add("sst", 0xffffffff)
    s.add("sci", 0x80000000)
    s.add("sps", F(-0.0))
    s.add("dump")

    # ---- the destructor, through the table and directly
    s.tag("dtor")
    for flags in (0, 1, 3):
        s.add("new")
        s.add("del", flags)
    s.add("new")
    s.add("nodrv")
    s.add("del", 1)
    s.add("new")
    s.add("dtor", 0, 0x1234)
    s.add("drv")

    # ---- FindDriveTargetPointByDistance
    s.tag("fpd fixed")
    straight = [(0.0, 0.0, 0.5, 0.25), (10.0, 0.0, 0.5, 0.25),
                (20.0, 0.0, 0.5, 0.25), (30.0, 0.0, 0.5, 0.25),
                (40.0, 0.0, 0.5, 0.25)]
    s.pts("far", straight)
    for pos in ((-1.0, 0.0), (0.0, 0.0), (0.0, 3.0), (5.0, -2.0),
                (10.0, 0.0), (19.999, 1.0), (35.0, 5.0), (40.0, 0.0),
                (41.0, 0.0), (25.0, 100.0)):
        for dist in (0.0, 1.0, 5.0, 15.0, 20.0, 35.0, 60.0, -3.0):
            for off in ((0.0, 0.0), (2.0, -1.5)):
                s.fpd("far", pos, dist, off)
    # one point; none
    s.pts("far", [(3.0, 4.0, 1.0, 2.0)])
    for pos in ((0.0, 0.0), (3.0, 4.0), (100.0, 0.0)):
        for dist in (0.0, 4.999, 5.0, 5.001, 20.0):
            s.fpd("far", pos, dist, (1.0, 1.0))
    s.pts("far", [])
    s.fpd("far", (0.0, 0.0), 20.0)
    s.pts("far", [(3.0, 4.0, 1.0, 2.0)] + [(0.0, 0.0, 0.0, 0.0)] * 2)
    s.add("pts", "far", 0)
    s.fpd("far", (0.0, 0.0), 20.0)
    # zero-length segments
    s.pts("far", [(0.0, 0.0), (0.0, 0.0), (10.0, 0.0), (10.0, 0.0),
                  (20.0, 5.0)])
    for pos in ((0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (15.0, 2.0)):
        for dist in (0.0, 3.0, 10.0, 30.0):
            s.fpd("far", pos, dist, (0.5, 0.5))
    # a bend, the point alongside two segments
    s.pts("far", [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
    for pos in ((9.0, 1.0), (11.0, -1.0), (5.0, 5.0), (9.5, 9.5)):
        for dist in (0.0, 2.0, 10.0, 25.0):
            s.fpd("far", pos, dist, (-1.0, 2.0))

    s.tag("fpd random")
    for run in range(60):
        n = rnd.choice((2, 3, 5, 8, 12, 20))
        pts = line_points(rnd, n, start=(rnd.uniform(-50, 50),
                                         rnd.uniform(-50, 50)),
                          heading=rnd.uniform(-180, 180),
                          dup=rnd.random() < 0.3)
        tgt = rnd.choice(("far", "near", "nd"))
        s.pts(tgt, pts)
        for k in range(6):
            i = rnd.randrange(n)
            pos = (pts[i][0] + rnd.uniform(-6, 6), pts[i][1] +
                   rnd.uniform(-6, 6))
            s.fpd(tgt, pos, rnd.choice((0.0, 20.0, rnd.uniform(0, 80))),
                  (rnd.uniform(-3, 3), rnd.uniform(-3, 3)))

    # ---- GetDriveTargetPointByDLOffsetFromStart
    s.tag("gpdl fixed")
    s.pts("near", straight)
    for offx in (-5.0, -0.0, 0.0, 0.5, 9.999, 10.0, 10.001, 25.0, 40.0,
                 40.001, 100.0):
        for offy in (0.0, 1.5, -2.0):
            s.gpdl("near", (offx, offy))
    for n in (0, 1, 2, 3):
        s.pts("near", straight[:n] + [(77.0, 88.0, 0.0, 0.0)] * 0)
        for offx in (-1.0, 0.0, 5.0, 15.0, 50.0):
            s.gpdl("near", (offx, 1.0))
    s.pts("near", [(0.0, 0.0), (0.0, 0.0), (10.0, 0.0), (10.0, 0.0)])
    for offx in (-1.0, 0.0, 5.0, 10.0, 50.0):
        s.gpdl("near", (offx, 1.0))

    s.tag("gpdl random")
    for run in range(60):
        n = rnd.choice((2, 3, 4, 7, 12, 20))
        pts = line_points(rnd, n, start=(rnd.uniform(-50, 50),
                                         rnd.uniform(-50, 50)),
                          heading=rnd.uniform(-180, 180),
                          dup=rnd.random() < 0.3)
        tgt = rnd.choice(("far", "near", "nd"))
        s.pts(tgt, pts)
        for k in range(5):
            s.gpdl(tgt, (rnd.choice((rnd.uniform(-5, 120), 0.0)),
                         rnd.uniform(-4, 4)))

    # ---- AreWeStuck
    s.tag("stuck")
    s.add("new")
    for col in (0, 1, 0xff, 0x80):
        s.set("cop", "col", 0, col)
        for st in (0, 1, 2, 3, 4, 5, -1):
            for vm in (0.0, 1.999, 2.0, 5.0):
                s.add("sst", st & M32)
                s.set("cop", "vm", 0, f32(vm))
                s.set("cd", "tm", 0, 0.75)
                s.add("stuck", F(0.25))
                s.add("stuck", F(0.0))
                s.add("stuck", F(0.5))
    s.set("cop", "col", 0, 0)

    # ---- GetPursuitTargetPoint
    s.tag("gptp")
    s.add("new")
    s.add("sci", COP_SLOT)
    s.pts("far", line_points(rnd, 10, start=(-10.0, 1.0), heading=3.0))
    s.pts("near", line_points(rnd, 6, start=(20.0, 1.0), heading=3.0))
    s.pts("nd", line_points(rnd, 15, start=(-30.0, -5.0), heading=0.0))
    s.vec("aic", "n48", (4.0, -1.5))
    s.add("pursuit", 0)
    s.add("gptp")
    s.add("pursuit", 1)
    for sub in list(range(0, 16)) + [-1, 100]:
        s.ls(6, 6, sub)
        for chp in ((15.0, 1.5), (19.99, 1.5), (20.0, 1.5), (20.0, 0.0),
                    (12.0, 16.0), (30.0, 1.5)):
            s.car("ch", pos=chp, heading=4.0, speed=25.0)
            s.add("gptp")
            s.add("dump")
    s.car("ch", pos=(30.0, 2.0), heading=5.0, speed=25.0)

    # ---- Think
    def think(n=1, dt=1.0 / 30.0, every=1):
        for i in range(n):
            s.add("think", F(f32(dt)))
            if (i + 1) % every == 0 or i == n - 1:
                s.add("dump")

    s.tag("think not cop movement")
    s.add("new")
    s.add("sci", COP_SLOT)
    for mode in (0, 1, 4, 6, -1):
        s.set("cop", "mode", 0, mode & M32)
        think()
    s.set("cop", "mode", 0, 5)

    s.tag("think states")
    for st in (0, 1, 2, 3, 4, 5, -1):
        s.add("new")
        s.add("sci", COP_SLOT)
        s.add("sst", st & M32)
        s.set("cd", "tm", 1, 0.5)
        think(2)

    s.tag("think patrol")
    s.add("new")
    s.add("sci", COP_SLOT)
    s.add("sst", 2)
    s.add("sps", F(31.0))
    for k in range(4):
        s.pts("nd", line_points(rnd, 12, start=(-20.0 + 5 * k, -3.0),
                                heading=rnd.uniform(-20, 20)))
        s.vec("aic", "n48", (rnd.uniform(-3, 3), rnd.uniform(-3, 3)))
        s.car("cop", pos=(rnd.uniform(-10, 10), rnd.uniform(-3, 3)),
              heading=rnd.uniform(-30, 30), speed=rnd.uniform(0, 30))
        think(2)

    s.tag("think stuck")
    s.pts("nd", line_points(rnd, 12, start=(-20.0, -3.0), heading=0.0))
    s.car("cop", pos=(1.0, 0.5), heading=10.0, speed=1.0)
    for before, near in ((2, 0), (3, 0), (2, 1), (3, 1)):
        s.add("new")
        s.add("sci", COP_SLOT)
        s.add("sst", before)
        s.add("near", near)
        s.set("cop", "col", 0, 1)
        think(40, every=5)
        s.set("cop", "col", 0, 0)
        think(70, every=10)
    s.add("near", 0)

    s.tag("think backing up")
    for before in (0, 1, 2, 3, 4, 7):
        s.add("new")
        s.add("sci", COP_SLOT)
        s.add("sst", 4)
        s.set("cd", "st", 1, before & M32)
        s.set("cd", "tm", 1, 0.1)
        think(5, dt=0.04)

    # PURSUIT, steering: far from the chased car, or going the other way,
    # or slow.
    s.tag("think pursuit steering")
    s.add("new")
    s.add("sci", COP_SLOT)
    s.add("sst", 3)
    s.pts("far", line_points(rnd, 12, start=(-10.0, 1.0), heading=3.0))
    s.pts("near", line_points(rnd, 6, start=(20.0, 1.0), heading=3.0))
    s.pts("nd", line_points(rnd, 15, start=(-30.0, -5.0), heading=0.0))
    s.vec("aic", "n48", (2.0, 1.0))
    for lvl in (0, 1, 2):
        s.add("lvl", lvl)
        for pl in (1, 0):
            s.add("player", "ch", pl)
            for sub in list(range(0, 15)) + [20]:
                s.ls(6, 6, sub)
                for cfg in ((60.0, 0.0, 25.0, 20.0),   # far
                            (30.0, 180.0, 25.0, 20.0),  # opposite way
                            (15.0, 0.0, 25.0, 10.0),    # slow
                            (15.0, 0.0, 5.0, 0.0),      # chased slow
                            (-30.0, 0.0, 25.0, 20.0)):  # chased behind
                    chx, chh, chs, mys = cfg
                    s.car("ch", pos=(chx, 1.5), heading=chh, speed=chs)
                    s.car("cop", pos=(0.0, 0.0), heading=0.0, speed=mys)
                    think()
    s.add("lvl", 2)
    s.add("player", "ch", 1)

    s.tag("think pursuit classes")
    s.ls(6, 6, 3)
    s.car("ch", pos=(60.0, 1.5), heading=0.0, speed=40.0)
    s.car("cop", pos=(0.0, 0.0), heading=0.0, speed=20.0)
    for cls in (0, 1, 2, 3, 4):
        for cc in (0, 1, 2, 3, 4, 5):
            s.set("cd", "cls", 0, cls)
            s.set("ctih", "cls", 0, cc)
            think()
    s.set("cd", "cls", 0, 3)
    s.set("ctih", "cls", 0, 2)

    s.tag("think pursuit quarter turn")
    s.ls(6, 6, 3)
    for chh in (0.0, 45.0, 89.0, 91.0, 135.0, 180.0, -90.5, -89.5):
        a = math.radians(chh)
        for r in (0.5, 1.0, 1.5, 50.0):
            s.car("ch", pos=(f32(r * math.cos(a)), f32(r * math.sin(a))),
                  heading=0.0, speed=30.0)
            s.car("cop", pos=(0.0, 0.0), heading=0.0, speed=20.0)
            think()
            s.car("cop", pos=(0.0, 0.0), heading=170.0, speed=20.0)
            think()

    # PURSUIT, translating: within 40 m, the same way, at 30 mph or more.
    s.tag("think pursuit translating")
    s.hist([(25.0, 1.0, 0.1), (24.0, 2.0, 0.2), (20.0, 3.0, 0.3),
            (15.0, 5.0, 0.4), (10.0, 4.0, 0.5)])
    for pl in (1, 0):
        s.add("player", "ch", pl)
        for sub in list(range(0, 15)) + [20]:
            s.ls(6, 6, sub)
            for cfg in ((10.0, 2.0, 25.0, 20.0, 1.0),
                        (30.0, -3.0, 40.0, 14.0, -1.0),
                        (5.0, 0.5, 20.0, 13.410818099975586, 0.0),
                        (-10.0, 1.0, 27.0, 30.0, 2.0)):
                chx, chy, chs, mys, lane = cfg
                s.car("ch", pos=(chx, chy), heading=2.0, speed=chs,
                      fs=chs * 0.98)
                s.car("cop", pos=(0.0, lane), heading=0.0, speed=mys)
                think()
    s.add("player", "ch", 1)

    s.tag("think acquire lanes")
    s.ls(6, 6, 9)
    s.rp("rph", pos=(20.0, 0.0), heading=0.0)
    s.rp("rpc", pos=(-5.0, 0.0), heading=0.0)
    for tr in (1, 0):
        for chy, myy in ((0.0, 0.0), (2.5, 0.0), (2.6, 0.0), (0.0, -2.5),
                         (3.0, -3.0), (-1.0, 1.4)):
            # 26.821636199951172 is 0x41d692b6: times the factor, 60.0.
            for fsp in (26.8, 26.82, 26.821636199951172, 26.83, 40.0, 5.0):
                s.car("ch", pos=(20.0 if tr else 70.0, chy), heading=0.0,
                      speed=30.0, fs=fsp)
                s.car("cop", pos=(0.0, myy), heading=0.0, speed=20.0)
                think()

    s.tag("think history")
    s.ls(6, 6, 3)
    s.car("ch", pos=(10.0, 1.0), heading=0.0, speed=30.0)
    s.car("cop", pos=(0.0, 0.0), heading=0.0, speed=20.0)
    for hs in ([], [(5.0, 1.0, 0.3)], [(0.0, 0.0, 0.3), (9.0, 1.0, 0.3)],
               [(20.0, 0.0, 0.1), (21.0, 1.0, 0.1), (22.0, 2.0, 0.1),
                (23.0, 3.0, 0.1), (24.0, 4.0, 0.1), (25.0, 5.0, 0.1),
                (26.0, 6.0, 0.1), (27.0, 7.0, 0.1)],
               [(10.0, 0.0, 0.25), (12.0, 0.0, 0.4), (0.0, 0.0, 0.65)],
               [(10.0, 0.0, 0.0), (12.0, 0.0, 0.0), (14.0, 0.0, 1.0)],
               [(10.0, 0.0, 0.1), (14.0, 1.0, 0.1), (19.0, 3.0, 0.06),
                (25.0, 2.0, 0.1), (28.0, 0.0, 0.1), (30.0, 1.0, 0.2),
                (31.0, 0.0, 0.2)],
               # 0.25 s back too small to square, 0.65 s back not
               [(1e-25, 0.0, 0.3), (1e-25, 0.0, 0.3), (5.0, 0.0, 0.1),
                (6.0, 0.0, 0.3)]):
        s.hist(hs)
        think()

    s.tag("think boundaries")
    s.add("new")
    s.add("sci", COP_SLOT)
    s.add("sst", 3)
    s.add("player", "ch", 1)
    s.ls(6, 6, 3)
    s.hist([(25.0, 1.0, 0.1), (24.0, 2.0, 0.2), (20.0, 3.0, 0.3)])
    # 40 m: exactly, just inside, and inside the 39 a mutant would use
    for chx in (40.0, 39.999996185302734, 39.5, 40.000003814697266):
        s.car("ch", pos=(chx, 0.0), heading=0.0, speed=25.0)
        s.car("cop", pos=(0.0, 0.0), heading=0.0, speed=20.0)
        s.set("mv", "dvel", 2, 7.5)
        think()
    # the cars' velocities square to each other: the dot product is 0
    s.car("ch", pos=(10.0, 1.0), heading=0.0, speed=25.0)
    s.car("cop", pos=(0.0, 0.0), heading=0.0, speed=20.0)
    for chv, myv in (((0.0, 25.0), (20.0, 0.0)), ((0.0, -25.0), (20.0, 0.0)),
                     ((-0.0, 0.0), (20.0, 0.0)), ((1.0, 0.0), (20.0, 0.0))):
        s.vec("ch", "vel", chv)
        s.vec("cop", "vel", myv)
        think()
    # the translating speed exactly: VelocityMagnitude 30 mph
    s.car("ch", pos=(10.0, 1.0), heading=0.0, speed=25.0)
    for vm in (13.410818099975586, 13.410817146301270, 13.410819053649902):
        s.car("cop", pos=(0.0, 0.0), heading=0.0, speed=20.0, vm=vm)
        think()
    # a quarter turn exactly, the chased car square to each side
    s.ls(6, 6, 4)
    for chp in ((0.0, 10.0), (0.0, -10.0), (10.0, 0.0), (-10.0, 0.0),
                (7.0, 7.0)):
        for ang in (0, 1, 8192, 16383, 16384, 16385, 24576, 32767, 32768,
                    32769, 49151, 49152, 49153, 57344, 65535):
            s.car("ch", pos=chp, heading=0.0, speed=30.0)
            s.car("cop", pos=(0.0, 0.0), heading=0.0, speed=5.0)
            s.set("cop", "angle", 0, ang)
            think()
    # a NaN chased speed: min.s keeps the line's limit
    s.ls(6, 6, 3)
    for vm in (float("nan"), -0.0, float("inf")):
        s.car("ch", pos=(60.0, 1.5), heading=0.0, speed=40.0, vm=vm)
        s.car("cop", pos=(0.0, 0.0), heading=0.0, speed=20.0)
        think()

    # DISABLED from a car that was driving: every field it sets, set first
    s.tag("think disabled from driving")
    for thr, steer in ((0.75, 1234), (-0.5, 65535), (0.0, 0)):
        s.add("new")
        s.add("sci", COP_SLOT)
        s.add("sst", 0)
        s.vec("nd", "thr", (thr, 0.25, 0.5))
        s.set("nd", "steer", 0, steer)
        s.set("nd", "gear", 0, 3)
        s.set("nd", "gear", 1, 2)
        think()

    # BACKING_UP's timer landing on 0 exactly, and on -0
    s.tag("think backing up to zero")
    for tm, dt in ((0.25, 0.25), (0.5, 0.25), (0.0, 0.0), (-0.0, 0.0),
                   (0.0, -0.0)):
        for before in (2, 3):
            s.add("new")
            s.add("sci", COP_SLOT)
            s.add("sst", 4)
            s.set("cd", "st", 1, before)
            s.set("cd", "tm", 1, tm)
            think(2, dt=dt)

    # GetDriveTargetPointByDLOffsetFromStart: one point at -0, and a
    # segment too short to square
    s.tag("gpdl signs")
    s.pts("near", [(-0.0, -0.0, 0.0, 0.0)])
    for off in ((0.5, 1.0), (-1.0, 1.0), (0.0, -2.0)):
        s.gpdl("near", off)
    for pts in ([(0.0, 0.0), (1e-25, 0.0)], [(0.0, 0.0), (0.0, -1e-25)],
                [(5.0, 5.0), (5.0, 5.0)], [(1e-25, 1e-25), (0.0, 0.0),
                                           (10.0, 0.0)]):
        s.pts("near", pts)
        for off in ((0.5, 0.0), (0.0, 0.0), (-0.5, 1.0), (20.0, 0.5)):
            s.gpdl("near", off)

    s.tag("think random")
    for run in range(40):
        s.add("new")
        s.add("sci", COP_SLOT)
        s.add("lvl", rnd.randrange(3))
        s.add("player", "ch", rnd.choice((0, 1)))
        s.add("sst", rnd.choice((0, 1, 2, 3, 3, 3, 4)))
        s.set("cd", "st", 1, rnd.choice((2, 3)))
        s.set("cd", "tm", 1, rnd.uniform(0.0, 2.0))
        s.set("cd", "cls", 0, rnd.randrange(5))
        s.set("ctih", "cls", 0, rnd.randrange(5))
        s.set("ctic", "type", 0, rnd.choice((4, 31, 32, 33, 34)))
        s.ls(6, 6, rnd.randrange(15))
        s.vec("aic", "n48", (rnd.uniform(-4, 4), rnd.uniform(-4, 4)))
        hp = (rnd.uniform(-40, 40), rnd.uniform(-40, 40))
        hh = rnd.uniform(-180, 180)
        s.car("ch", pos=hp, heading=hh, speed=rnd.uniform(0, 60))
        a = math.radians(hh + rnd.uniform(-90, 90))
        d = rnd.uniform(0, 60)
        s.car("cop", pos=(hp[0] - d * math.cos(a), hp[1] - d * math.sin(a)),
              heading=hh + rnd.uniform(-40, 40), speed=rnd.uniform(0, 50))
        s.rp("rph", pos=(hp[0] + rnd.uniform(-5, 5), hp[1] + rnd.uniform(-5, 5)),
             heading=hh + rnd.uniform(-20, 20),
             speeds=[rnd.randrange(256) for _ in range(21)])
        s.rp("rpc", pos=(hp[0] + rnd.uniform(-5, 5), hp[1] + rnd.uniform(-5, 5)),
             heading=hh + rnd.uniform(-20, 20),
             speeds=[rnd.randrange(256) for _ in range(21)])
        s.pts("far", line_points(rnd, rnd.randrange(1, 20), start=hp,
                                 heading=hh))
        s.pts("near", line_points(rnd, rnd.randrange(1, 20), start=hp,
                                  heading=hh))
        s.pts("nd", line_points(rnd, rnd.randrange(1, 20),
                                start=(hp[0] - d, hp[1]), heading=hh))
        s.hist([(rnd.uniform(-30, 30), rnd.uniform(-30, 30),
                 rnd.uniform(0.0, 0.3)) for _ in range(rnd.randrange(0, 8))])
        s.set("cop", "col", 0, rnd.choice((0, 0, 1)))
        s.add("near", rnd.choice((0, 1)))
        for i in range(6):
            s.add("think", F(f32(rnd.choice((1.0 / 30.0, 0.5, 0.2)))))
            s.add("dump")
    return s.lines


# ================================================================== model

class Model(object):
    def __init__(self):
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        self.out = []
        self.cd = self.block(CD_SIZE + 20, 0xcd)
        self.nd = self.block(ND_SIZE + 16, 0xab)
        self.carc = self.block(CAR_SIZE, 0)
        self.carh = self.block(CAR_SIZE, 0)
        self.ctic = self.block(CTI_SIZE, 0)
        self.ctih = self.block(CTI_SIZE, 0)
        self.mv = self.block(MV_SIZE, 0)
        self.dcbc = self.block(DCB_SIZE, 0)
        self.dcbh = self.block(DCB_SIZE, 0)
        self.aic = self.block(AIC_SIZE, 0)
        self.pur = self.block(PUR_SIZE, 0)
        self.mgr = self.block(MGR_SIZE, 0)
        self.rpc = self.block(RP_SIZE, 0)
        self.rph = self.block(RP_SIZE, 0)
        self.pl = [self.block(64, 0), self.block(64, 0)]
        self.scr = self.block(64, 0)
        self.near = 0
        e.put32(G_COPMGR, self.mgr)
        e.put32(self.mgr + MGR_COPS + 4 * COP_SLOT, self.aic)
        e.put32(self.aic + 4, self.carc)
        e.put32(self.pur + 16, self.carh)
        e.put32(self.carc + 12, self.ctic)
        e.put32(self.carh + 12, self.ctih)
        e.put32(self.carc + 48, self.mv)
        e.put32(self.mv + 8, self.carc)
        e.put32(self.carc + 44, self.nd)
        e.put32(self.carc + 52, self.dcbc)
        e.put32(self.carh + 52, self.dcbh)
        self.base = {"cd": self.cd, "mv": self.mv, "nd": self.nd,
                     "cop": self.carc, "ch": self.carh, "ctic": self.ctic,
                     "ctih": self.ctih, "aic": self.aic, "rpc": self.rpc,
                     "rph": self.rph}
        self.targets = {"far": self.pur + PUR_FAR, "near": self.pur + PUR_NEAR,
                        "nd": self.nd}
        self.labels = {self.cd: "cd", self.cd + 64: "cd.st", self.nd: "nd",
                       self.carc: "cop", self.carh: "ch",
                       self.carc + CS + 32: "cop.pos",
                       self.carh + CS + 32: "ch.pos", self.aic: "aic",
                       self.pur + PUR_FAR: "far", self.pur + PUR_NEAR: "near",
                       self.mv: "mv", self.rpc: "rpc", self.rph: "rph",
                       self.scr: "out"}
        # The NullDriver's table: its destructor and SetDesiredSpeed.
        for slot, want in ((ND_DTOR, S_NDDTOR), (ND_SPEED, S_NDSPEED)):
            got = e.u32(VT_NULLDRIVER + slot + 4)
            assert got == want, "nulldriver slot %d is %08x" % (slot, got)
        for a, fn in ((S_TCCTOR, self.s_tcctor), (S_TCDTOR, self.s_tcdtor),
                      (S_TCTHINK, self.s_tcthink), (S_MALLOC, self.s_malloc),
                      (S_DTCTOR, self.s_dtctor), (S_DTCLEAR, self.s_dtclear),
                      (S_DTASSIGN, self.s_assign), (S_NEAR, self.s_near),
                      (S_INIT, self.s_init), (S_UPDATE, self.s_update),
                      (S_GETRP, self.s_getrp), (S_NDDTOR, self.s_nddtor),
                      (S_NDSPEED, self.s_ndspeed)):
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
        return self.labels.get(a, "?")

    def vt(self, v):
        v &= M32
        return VT_NAMES.get(v, "%08x" % v)

    def fx(self, i):
        return hx(self.e.fpr[i])

    # ---- stubs

    def s_malloc(self, em):
        e, r = self.e, self.e.reg
        name = bytearray()
        a = r[5] & M32
        while e.u8(a):
            name.append(e.u8(a))
            a += 1
        self.emit("  malloc %d %s %d %d" % (s32(r[4]), name.decode(),
                                             s32(r[6]), s32(r[7])))
        return self.nd

    def s_tcctor(self, em):
        r = self.e.reg
        self.emit("  tcinit %s %s" % (self.lab(r[4]), self.lab(r[5])))
        self.e.put32(r[4] & M32, r[5] & M32)
        return r[4] & M32

    def s_tcdtor(self, em):
        r = self.e.reg
        self.emit("  tcdtor %s %d %s" % (self.lab(r[4]), s32(r[5]),
                                          self.vt(self.e.u32((r[4] & M32) + 8))))

    def s_tcthink(self, em):
        self.emit("  tcthink %s %s" % (self.lab(self.e.reg[4]), self.fx(12)))

    def s_dtctor(self, em):
        r = self.e.reg
        self.emit("  dtinit %s %s" % (self.lab(r[4]),
                                       self.vt(self.e.u32((r[4] & M32) + 556))))
        return r[4] & M32

    def s_dtclear(self, em):
        r = self.e.reg
        self.emit("  dtclear %s %s %s %d"
                  % (self.lab(r[4]), self.lab(r[5]), self.fx(12),
                     s32(self.e.u32((r[4] & M32) + 544))))

    def s_assign(self, em):
        r = self.e.reg
        self.emit("  assign %s %s" % (self.lab(r[4]), self.lab(r[5])))
        return r[4] & M32

    def s_getrp(self, em):
        r = self.e.reg
        a = r[4] & M32
        self.emit("  rp %s %d" % (self.lab(a), s32(r[5])))
        return {self.carc: self.rpc, self.carh: self.rph}.get(a, 0)

    def s_near(self, em):
        self.emit("  near %s -> %d" % (self.lab(self.e.reg[4]), self.near))
        return self.near

    def s_init(self, em):
        self.emit("  init %s" % self.lab(self.e.reg[4]))

    def s_update(self, em):
        r = self.e.reg
        self.emit("  update %s %s %d" % (self.lab(r[4]), self.lab(r[5]),
                                          s32(r[6])))

    def s_nddtor(self, em):
        r = self.e.reg
        self.emit("  nddtor %s %d" % (self.lab(r[4]), s32(r[5])))

    def s_ndspeed(self, em):
        r = self.e.reg
        self.emit("  ndspeed %s %s %s %s %d"
                  % (self.lab(r[4]), self.fx(12), self.fx(13), self.fx(14),
                     s32(r[5])))

    # ---- the fields

    def addr(self, obj, off):
        if obj == "cop" and off < 0:
            return self.dcbc + 18
        return self.base[obj] + off

    def group(self, obj, name):
        for g in GROUPS[obj]:
            if g[0] == name:
                return g
        raise KeyError("%s.%s" % (obj, name))

    def show(self, obj):
        e = self.e
        for name, off, n, kind in GROUPS[obj]:
            a0 = self.addr(obj, off)
            vals = []
            for k in range(n):
                if kind == "h":
                    a = a0 + 2 * k
                    vals.append("%d" % (e.u8(a) | (e.u8(a + 1) << 8)))
                elif kind == "b":
                    vals.append("%d" % e.u8(a0 + k))
                elif kind == "f":
                    vals.append(hx(e.u32(a0 + 4 * k)))
                else:
                    vals.append("%08x" % e.u32(a0 + 4 * k))
            self.emit("  %s.%s %s" % (obj, name, " ".join(vals)))

    # ---- the ops

    def vcall(self, slot, *args):
        e = self.e
        vt = e.u32(self.cd + 8)
        delta = e.u32(vt + slot) & 0xffff
        if delta & 0x8000:
            delta -= 0x10000
        fn = e.u32(vt + slot + 4)
        return e.call(fn, (self.cd + delta) & M32, *args, limit=4000000)

    def op(self, a):
        e, o = self.e, a[0]
        n = [int(x, 0) for x in a[1:] if x[:1] in "-0123456789"]
        if o == "tag":
            self.emit("# %s" % a[1])
        elif o == "set":
            name, off, cnt, kind = self.group(a[1], a[2])
            i, v = int(a[3], 0), int(a[4], 0) & M32
            addr = self.addr(a[1], off)
            if kind == "h":
                e.write(addr + 2 * i, struct.pack("<H", v & 0xffff))
            elif kind == "b":
                e.write(addr + i, bytes([v & 0xff]))
            else:
                e.put32(addr + 4 * i, v)
        elif o == "lvl":
            e.put32(self.mgr + MGR_LEVEL, n[0] & M32)
        elif o == "near":
            self.near = n[0]
        elif o == "pursuit":
            e.put32(self.aic, self.pur if n[0] else 0)
        elif o == "player":
            car = self.carc if a[1] == "cop" else self.carh
            e.put32(car + 24, (self.pl[0] if a[1] == "cop" else self.pl[1])
                    if n[0] else 0)
        elif o == "pts":
            t = self.targets[a[1]]
            cnt = int(a[2], 0)
            e.write(t, bytes([cnt & 0xff]))
            vals = [int(x, 0) & M32 for x in a[3:]]
            for i in range(min(cnt, len(vals) // 4)):
                for k in range(4):
                    e.put32(t + 16 + 16 * i + 4 * k, vals[4 * i + k])
        elif o == "hist":
            h = self.pur + PUR_HIST
            cnt = int(a[1], 0)
            e.put32(h, cnt & M32)
            vals = [int(x, 0) & M32 for x in a[2:]]
            for i in range(min(cnt, 30)):
                e.put32(h + 4 + 8 * i, vals[3 * i])
                e.put32(h + 8 + 8 * i, vals[3 * i + 1])
                e.put32(h + 244 + 4 * i, vals[3 * i + 2])
        elif o == "new":
            e.write(self.cd, b"\xcd" * CD_SIZE)
            e.write(self.nd, b"\xab" * ND_SIZE)
            r = e.call(F_CTOR, self.cd, self.carc, limit=100000)
            self.emit("new -> %s" % self.lab(r))
        elif o == "del":
            self.vcall(VT_DTOR, n[0] & M32)
            self.emit("del")
        elif o == "dtor":
            e.put32(self.cd + 8, n[1] & M32)
            e.call(F_DTOR, self.cd, n[0] & M32, limit=100000)
            self.emit("dtor")
        elif o == "nodrv":
            e.put32(self.cd + 4, 0)
        elif o == "drv":
            e.put32(self.cd + 4, self.nd)
        elif o == "think":
            e.fpr[12] = n[0] & M32
            self.vcall(VT_THINK)
            self.emit("think")
        elif o == "gptp":
            e.put32(self.scr, 0x41414141)
            e.put32(self.scr + 4, 0x42424242)
            e.call(F_GPTP, self.cd, self.scr, limit=1000000)
            self.emit("gptp -> %s %s" % (hx(e.u32(self.scr)),
                                         hx(e.u32(self.scr + 4))))
        elif o == "stuck":
            e.fpr[12] = n[0] & M32
            r = e.call(F_STUCK, self.cd, limit=100000)
            self.emit("stuck -> %d %s" % (r, hx(e.u32(self.cd + 48))))
        elif o == "fpd":
            sc = self.scr
            e.put32(sc, 0x41414141)
            e.put32(sc + 4, 0x42424242)
            e.put32(sc + 8, 0x43434343)
            e.put32(sc + 16, n[0] & M32)
            e.put32(sc + 20, n[1] & M32)
            e.put32(sc + 24, n[3] & M32)
            e.put32(sc + 28, n[4] & M32)
            e.fpr[12] = n[2] & M32
            r = e.call(F_FPD, sc, sc + 8, self.targets[a[1]], sc + 16,
                       sc + 24, limit=1000000)
            self.emit("fpd -> %d %s %s %s" % (r, hx(e.u32(sc)),
                                              hx(e.u32(sc + 4)),
                                              hx(e.u32(sc + 8))))
        elif o == "gpdl":
            sc = self.scr
            e.put32(sc, 0x41414141)
            e.put32(sc + 4, 0x42424242)
            e.put32(sc + 24, n[0] & M32)
            e.put32(sc + 28, n[1] & M32)
            e.call(F_GPDL, sc, self.targets[a[1]], sc + 24, limit=1000000)
            self.emit("gpdl -> %s %s" % (hx(e.u32(sc)), hx(e.u32(sc + 4))))
        elif o == "grn":
            e.call(F_GRN, self.cd, 0, 0)
        elif o == "sps":
            e.fpr[12] = n[0] & M32
            e.call(F_SPS, self.cd)
        elif o == "sst":
            e.call(F_SST, self.cd, n[0] & M32)
        elif o == "sci":
            e.call(F_SCI, self.cd, n[0] & M32)
        elif o == "dump":
            self.emit("dump")
            self.emit("  cd.ctl %s %s %s" % (self.lab(e.u32(self.cd)),
                                              self.lab(e.u32(self.cd + 4)),
                                              self.vt(e.u32(self.cd + 8))))
            self.show("cd")
            self.show("mv")
            self.emit("  nd.vt %s" % self.vt(e.u32(self.nd + 556)))
            self.show("nd")
        else:
            raise ValueError("bad op %s" % o)

    def run(self, lines):
        for line in lines:
            self.op(line.split("|"))
        return self.out


def model(lines):
    return Model().run(lines)


# ================================================================== build

def build_harness(tmp, name="copdriver_test"):
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

C = CDC
CM = "3DS Files/source/copmanager.c"
CU = "3DS Files/source/coputil.c"

MUTATIONS = [
    # ---- the tuning
    ("patrol_speed", C, "29.056772232055664f", "29.0f"),
    ("translate_speed", C, "13.410818099975586f", "13.5f"),
    ("mph", C, "2.236999988555908f", "2.25f"),
    ("speed_up", C, "1.100000023841858f", "1.125f"),
    ("slow_speed", C, "    8.940545082092285f   // gp-29444",
     "    8.9f   // gp-29444"),
    ("back_up_speed", C, "-8.940545082092285f", "-8.9f"),
    ("hist_early", C, "0.25f                // 3e800000",
     "0.3f  // 3e800000"),
    ("hist_late", C, "0.6499999761581421f", "0.6f"),
    ("target_dist", C, "20.0f                // 41a00000",
     "21.0f  // 41a00000"),
    ("translate_dist", C, "40.0f                // 42200000",
     "39.0f  // 42200000"),
    ("turn_throttle", C, "4.0f                 // 40800000",
     "4.5f  // 40800000"),
    ("back_up_time", C, "#define CD_BACK_UP_TIME     2.0f",
     "#define CD_BACK_UP_TIME     2.5f"),
    ("stuck_speed", C, "#define CD_STUCK_SPEED      2.0f",
     "#define CD_STUCK_SPEED      2.5f"),
    ("stuck_time", C, "1.0f                 // 3f800000",
     "1.5f  // 3f800000"),
    ("acquire_lane", C, "2.5f                 // 40200000",
     "2.4f  // 40200000"),
    ("acquire_mph", C, "60.0f                // 42700000",
     "59.0f  // 42700000"),
    ("quarter_turn", C, "16384.0f             // 46800000",
     "16000.0f  // 46800000"),
    ("scale_0", C, "1.149999976158142f", "1.15f + 0.01f"),
    ("scale_1", C, "1.2000000476837158f", "1.21f"),
    ("scale_2", C, "1.25f                                        // 3fa00000",
     "1.26f  // 3fa00000"),
    # ---- the helpers
    ("cop_of", C, "pCopManager->Cops[d->nCopIndex]",
     "pCopManager->Cops[d->nCopIndex & 1]"),
    ("lateral_sign", C,
     "    return (car->State.Position.x - rp->Position.x) * rp->Direction.y\n"
     "         - (car->State.Position.y - rp->Position.y) * rp->Direction.x;",
     "    return (car->State.Position.x - rp->Position.x) * rp->Direction.y\n"
     "         + (car->State.Position.y - rp->Position.y) * rp->Direction.x;"),
    ("lateral_point", C,
     "    const TrackRoutePoint *rp = car_get_route_point(car, 1);\n\n    return",
     "    const TrackRoutePoint *rp = car_get_route_point(car, 0);\n\n    return"),
    # ---- the constructor
    ("ctor_vptr", C,
     "    trackedcontroller_init(&d->Base, car);\n"
     "    d->Base.Base._vtable = COPDRIVER_VTABLE;\n",
     "    trackedcontroller_init(&d->Base, car);\n"),
    ("ctor_malloc_size", C, "bMalloc((int)sizeof(NullDriver), \"NullDriver\", 0,",
     "bMalloc((int)sizeof(CarDriver), \"NullDriver\", 0,"),
    ("ctor_malloc_pool", C, "                               CAR_MEMORY_POOL);",
     "                               0);"),
    ("ctor_no_cdinit", C, "    cardriver_init(drv);\n", ""),
    ("ctor_stuck", C, "    d->fStuckTimer = 0.0f;\n    drv->_vtable",
     "    d->fStuckTimer = 1.0f;\n    drv->_vtable"),
    ("ctor_nd_vptr", C, "    drv->_vtable = NULLDRIVER_VTABLE;\n", ""),
    ("ctor_nitro", C, "    drv->NitroFlag = 0;\n    d->nCopIndex = -1;",
     "    drv->NitroFlag = 1;\n    d->nCopIndex = -1;"),
    ("ctor_index", C, "    d->nCopIndex = -1;\n", "    d->nCopIndex = 0;\n"),
    ("ctor_steer_x", C, "    d->v2SteerTarget.x = d->fStuckTimer;\n", ""),
    ("ctor_steer_y", C, "    d->v2SteerTarget.y = d->fStuckTimer;\n", ""),
    ("ctor_patrol", C, "    d->fPatrolSpeed = CD_PATROL_SPEED;\n", ""),
    ("ctor_before", C, "    d->StateBeforeGettingStuck = eCDS_PARKED;\n",
     "    d->StateBeforeGettingStuck = eCDS_PATROLLING;\n"),
    ("ctor_driver", C, "    d->Base.Base.Driver = drv;\n", ""),
    ("ctor_gear", C, "    d->Base.Base.Driver = drv;\n    drv->DesiredGear = -1;\n",
     "    d->Base.Base.Driver = drv;\n"),
    ("ctor_backing", C, "    d->fBackingUpTimer = 0.0f;\n    d->v2SteerTarget.y",
     "    d->v2SteerTarget.y"),
    ("ctor_substate", C, "    d->SubState = 1;\n    d->State = eCDS_PARKED;",
     "    d->SubState = 0;\n    d->State = eCDS_PARKED;"),
    ("ctor_state", C, "    d->SubState = 1;\n    d->State = eCDS_PARKED;",
     "    d->SubState = 1;\n    d->State = eCDS_DISABLED;"),
    ("ctor_32", C, "    case 32:\n        d->nCarClass = 0;",
     "    case 30:\n        d->nCarClass = 0;"),
    ("ctor_33", C, "        d->nCarClass = 1;", "        d->nCarClass = 5;"),
    ("ctor_34", C, "    case 34:\n        d->nCarClass = 2;",
     "    case 35:\n        d->nCarClass = 2;"),
    ("ctor_31", C, "    case 31:\n        d->nCarClass = 3;",
     "    case 3:\n        d->nCarClass = 3;"),
    ("ctor_4", C, "    case 4:\n        d->nCarClass = 4;\n        break;",
     "    case 4:\n        d->nCarClass = 2;\n        break;"),
    ("ctor_default", C,
     "        d->nCarClass = 4;\n        break;\n    default:\n        break;",
     "        d->nCarClass = 4;\n        break;\n    default:\n"
     "        d->nCarClass = 0;\n        break;"),
    ("ctor_seam", C, "    return &copdriver_init((CopDriver *)mem, car)->Base.Base;",
     "    copdriver_init((CopDriver *)mem, car);\n    return NULL;"),
    # ---- the destructor
    ("dtor_vptr", C,
     "    d->Base.Base._vtable = COPDRIVER_VTABLE;\n    drv = d->Base.Base.Driver;",
     "    drv = d->Base.Base.Driver;"),
    ("dtor_no_test", C, "    if (drv != NULL) {\n        const VtEntry *e = vt_slot(drv->_vtable, CARDRIVER_VT_DTOR);",
     "    if (drv != NULL && 0) {\n        const VtEntry *e = vt_slot(drv->_vtable, CARDRIVER_VT_DTOR);"),
    ("dtor_drv_flags", C, "((DriverDtorFn)e->fn)(vt_this(drv, e), 3);",
     "((DriverDtorFn)e->fn)(vt_this(drv, e), 1);"),
    ("dtor_flags", C, "    trackedcontroller_destroy(&d->Base, flags);",
     "    trackedcontroller_destroy(&d->Base, flags & 1);"),
    # ---- FindDriveTargetPointByDistance
    ("fpd_one_le", C, "        if (sqrtf(dx * dx + dy * dy) <= dist) {",
     "        if (sqrtf(dx * dx + dy * dy) < dist) {"),
    ("fpd_one_lat", C, "            *lateral = 0.0f;\n        }",
     "        }"),
    ("fpd_one_y", C, "            out->y = p[0].y;\n            found = 1;",
     "            out->y = p[0].x;\n            found = 1;"),
    ("fpd_zero", C, "    } else if (n != 0) {", "    } else if (n > 1) {"),
    ("fpd_from_first", C, "        for (i = n - 2; i >= 0; i--) {",
     "        for (i = 0; i <= n - 2; i++) {"),
    ("fpd_len0", C, "            if (len != 0.0f) {\n                float inv = ee_div(1.0f, len);",
     "            if (1) {\n                float inv = ee_div(1.0f, len);"),
    ("fpd_ux", C, "                ux = dx * inv;\n", ""),
    ("fpd_along", C,
     "            along = (pos->x - p[i].x) * ux + (pos->y - p[i].y) * uy;",
     "            along = (pos->x - p[i].x) * ux - (pos->y - p[i].y) * uy;"),
    ("fpd_along_le", C, "            if (!(0.0f <= along && along < len))",
     "            if (!(0.0f < along && along < len))"),
    ("fpd_along_lt", C, "            if (!(0.0f <= along && along < len))",
     "            if (!(0.0f <= along && along <= len))"),
    ("fpd_acc", C, "            acc = -along;", "            acc = along;"),
    ("fpd_dist_le", C, "                if (dist <= acc) {",
     "                if (dist < acc) {"),
    ("fpd_over", C, "                    float over = acc - dist;",
     "                    float over = dist - acc;"),
    ("fpd_out_x_off", C,
     "                    out->x = ((p[j + 1].x - vx * over) + vx * off->x)\n"
     "                             + vy * off->y;",
     "                    out->x = ((p[j + 1].x - vx * over) + vx * off->x)\n"
     "                             - vy * off->y;"),
    ("fpd_out_x_along", C,
     "                    out->x = ((p[j + 1].x - vx * over) + vx * off->x)",
     "                    out->x = ((p[j + 1].x - vx * over) + vy * off->x)"),
    ("fpd_out_y_off", C, "                             + -vx * off->y;",
     "                             + vx * off->y;"),
    ("fpd_out_y_along", C,
     "                    out->y = ((p[j + 1].y - vy * over) + vy * off->x)",
     "                    out->y = ((p[j + 1].y - vy * over) - vy * off->x)"),
    ("fpd_lat_abs", C, "                    *lateral = fabsf((pos->x - out->x) * vy",
     "                    *lateral = ((pos->x - out->x) * vy"),
    ("fpd_lat_y", C, "                                     + (pos->y - out->y) * -vx);",
     "                                     + (pos->y - out->y) * vx);"),
    ("fpd_no_break", C, "                    found = 1;\n                    break;\n                }\n            }\n            break;",
     "                    found = 1;\n                }\n            }\n            break;"),
    ("fpd_continue", C, "                }\n            }\n            break;\n        }\n    }\n    if (!found) {",
     "                }\n            }\n        }\n    }\n    if (!found) {"),
    ("fpd_fallback", C, "        const bVector3 *q = &p[n >= 2 ? 1 : 0];",
     "        const bVector3 *q = &p[0];"),
    ("fpd_fallback_2", C, "        const bVector3 *q = &p[n >= 2 ? 1 : 0];",
     "        const bVector3 *q = &p[n > 2 ? 1 : 0];"),
    ("fpd_return", C, "        out->x = q->x;\n    }\n    return found;",
     "        out->x = q->x;\n    }\n    return 1;"),
    # ---- GetDriveTargetPointByDLOffsetFromStart
    ("gpdl_last", C, "        ((const uint8_t *)t + n * 16);",
     "        ((const uint8_t *)t + n * 16 + 16);"),
    ("gpdl_few", C, "    if (n < 2) {\n        out->x = a->x;",
     "    if (n < 1) {\n        out->x = a->x;"),
    ("gpdl_neg", C, "    if (0.0f <= off->x) {\n        int32_t left",
     "    if (0.0f < off->x) {\n        int32_t left"),
    ("gpdl_left", C, "        int32_t left = n - 1;", "        int32_t left = n - 2;"),
    ("gpdl_acc_le", C, "            if (!(acc <= off->x))", "            if (!(acc < off->x))"),
    ("gpdl_no_b", C, "                break;\n            b = a;\n        }",
     "                break;\n        }"),
    ("gpdl_d0", C, "    if (0.0f < d) {\n        float s = ee_div(acc - off->x, d);",
     "    if (1) {\n        float s = ee_div(acc - off->x, d);"),
    ("gpdl_s", C, "        float s = ee_div(acc - off->x, d);",
     "        float s = ee_div(off->x - acc, d);"),
    ("gpdl_out", C, "    out->x = a->x + dx;\n", "    out->x = b->x + dx;\n"),
    ("gpdl_py", C, "    py = -(b->x - a->x);", "    py = b->x - a->x;"),
    ("gpdl_l0", C, "    if (l != 0.0f) {\n        py = ee_div(py, l);",
     "    if (1) {\n        py = ee_div(py, l);"),
    ("gpdl_unit", C, "        px = ee_div(px, l);\n", ""),
    ("gpdl_across", C, "    out->y = out->y + py * off->y;",
     "    out->y = out->y + px * off->y;"),
    # ---- GetPursuitTargetPoint
    ("gptp_null", C, "    if (p == NULL)\n        return;\n    chased = p->pChasedCar;",
     "    chased = p->pChasedCar;"),
    ("gptp_close", C, "    case LSS_LOW_SPEED_CLOSE_FOLLOW:\n    case LSS_FOLLOW_BACKWARDS:\n    case LSS_FLANK:\n    case LSS_BUMP:\n    case LSS_BLOCK:\n    case LSS_GET_AHEAD:\n    case LSS_LIMBO_READY: {",
     "    case LSS_FOLLOW_BACKWARDS:\n    case LSS_FLANK:\n    case LSS_BUMP:\n    case LSS_BLOCK:\n    case LSS_GET_AHEAD:\n    case LSS_LIMBO_READY: {"),
    ("gptp_limbo_ready", C, "    case LSS_GET_AHEAD:\n    case LSS_LIMBO_READY: {",
     "    case LSS_GET_AHEAD: {"),
    ("gptp_substate1", C, "        car = d->Base.Base.pCar;\n        d->SubState = 1;",
     "        car = d->Base.Base.pCar;\n        d->SubState = 2;"),
    ("gptp_near_lt", C, "        if (sqrtf(dx * dx + dy * dy) < CD_TARGET_DIST) {\n            drivetarget_assign(&drv->MyDriveTarget, &p->NearDriveTarget);",
     "        if (sqrtf(dx * dx + dy * dy) <= CD_TARGET_DIST) {\n            drivetarget_assign(&drv->MyDriveTarget, &p->NearDriveTarget);"),
    ("gptp_near_off", C, "                out, &p->NearDriveTarget, &cop->New48);",
     "                out, &p->NearDriveTarget, &cop->MyDLOffset);"),
    ("gptp_far_target", C, "                out, &lateral, &p->FarDriveTarget, car_pos(d->Base.Base.pCar),",
     "                out, &lateral, &drv->MyDriveTarget, car_pos(d->Base.Base.pCar),"),
    ("gptp_far_assign", C, "            drivetarget_assign(&drv->MyDriveTarget, &p->FarDriveTarget);\n", ""),
    ("gptp_acq_sub", C, "    case LSS_ACQUIRE:\n        // Along the chased car's route, as far across it as the car is.\n        d->SubState = 0;",
     "    case LSS_ACQUIRE:\n        // Along the chased car's route, as far across it as the car is.\n        d->SubState = 1;"),
    ("gptp_acq_init", C, "        d->SubState = 0;\n        taicop_initialize_drive_target(cop);\n        taicop_update_drive_target(cop, car_pos(chased), 0);\n        drv = d->Base.Base.Driver;",
     "        d->SubState = 0;\n        taicop_update_drive_target(cop, car_pos(chased), 0);\n        drv = d->Base.Base.Driver;"),
    ("gptp_acq_off", C, "        off.y = route_lateral(chased);",
     "        off.y = -route_lateral(chased);"),
    ("gptp_acq_offx", C, "        off.x = 0.0f;\n", "        off.x = 1.0f;\n"),
    ("gptp_stop_pos", C, "        taicop_update_drive_target(cop, car_pos(chased), 0);\n        copdriver_find_point_by_distance(out, &lateral, &drv->MyDriveTarget,\n                                         car_pos(chased), CD_TARGET_DIST,\n                                         &none);",
     "        taicop_update_drive_target(cop, car_pos(chased), 1);\n        copdriver_find_point_by_distance(out, &lateral, &drv->MyDriveTarget,\n                                         car_pos(chased), CD_TARGET_DIST,\n                                         &none);"),
    ("gptp_stop_none", C, "                                         car_pos(chased), CD_TARGET_DIST,\n                                         &none);",
     "                                         car_pos(chased), CD_TARGET_DIST,\n                                         &cop->New48);"),
    ("gptp_limbo_pos", C, "        taicop_update_drive_target(cop, car_pos(d->Base.Base.pCar), 0);",
     "        taicop_update_drive_target(cop, car_pos(chased), 0);"),
    ("gptp_limbo_dist", C, "            car_pos(d->Base.Base.pCar), CD_TARGET_DIST, &none);",
     "            car_pos(d->Base.Base.pCar), CD_TRANSLATE_DIST, &none);"),
    # ---- AreWeStuck
    ("stuck_no_col", C, "    if (!car_in_recent_collision(d->Base.Base.pCar))\n        return 0;", ""),
    ("stuck_patrol", C, "    case eCDS_PATROLLING:\n    case eCDS_PURSUIT:\n        if (!(d->Base",
     "    case eCDS_PURSUIT:\n        if (!(d->Base"),
    ("stuck_speed_lt", C, "        if (!(d->Base.Base.pCar->State.VelocityMagnitude < CD_STUCK_SPEED)) {",
     "        if (!(d->Base.Base.pCar->State.VelocityMagnitude <= CD_STUCK_SPEED)) {"),
    ("stuck_reset_fast", C, "            d->fStuckTimer = 0.0f;\n            return 0;\n        }",
     "            return 0;\n        }"),
    ("stuck_dt", C, "        d->fStuckTimer = d->fStuckTimer + dt;",
     "        d->fStuckTimer = d->fStuckTimer + dt * 2.0f;"),
    ("stuck_lt", C, "        return CD_STUCK_TIME < d->fStuckTimer;",
     "        return CD_STUCK_TIME <= d->fStuckTimer;"),
    ("stuck_others", C, "    case eCDS_BACKING_UP:\n        d->fStuckTimer = 0.0f;\n        return 0;",
     "    case eCDS_BACKING_UP:\n        return 0;"),
    ("stuck_default", C, "        return 0;\n    default:\n        return 0;\n    }\n}",
     "        return 0;\n    default:\n        d->fStuckTimer = 0.0f;\n        return 0;\n    }\n}"),
    # ---- DISABLED
    ("dis_brake_accel", C, "    m->fMaxBrakingAccel = 2.0f;", "    m->fMaxBrakingAccel = 3.0f;"),
    ("dis_speed", C, "    m->fMaxBrakingAccel = 2.0f;\n    m->fDesiredSpeed = 0.0f;",
     "    m->fMaxBrakingAccel = 2.0f;"),
    ("dis_throttle", C, "    drv->Throttle = 0.0f;\n    drv->EBrake = 1.0f;",
     "    drv->EBrake = 1.0f;"),
    ("dis_ebrake", C, "    drv->EBrake = 1.0f;", "    drv->EBrake = 0.5f;"),
    ("dis_sport", C, "    drv->SportGear = -1;\n", ""),
    ("dis_brake", C, "    drv->Brake = 1.0f;\n    drv->Steering = 0;",
     "    drv->Steering = 0;"),
    ("dis_steer", C, "    drv->Steering = 0;\n    drv->DesiredGear = -1;",
     "    drv->DesiredGear = -1;"),
    ("dis_gear", C, "    drv->Steering = 0;\n    drv->DesiredGear = -1;",
     "    drv->Steering = 0;\n    drv->DesiredGear = 0;"),
    ("dis_state", C, "    drv->DesiredGear = -1;\n    m->State = eCMS_STEERING;\n    e = vt_slot",
     "    drv->DesiredGear = -1;\n    e = vt_slot"),
    ("dis_call_time", C, "((DriverDesiredSpeedFn)e->fn)(vt_this(drv, e), drv->Throttle, 10.0f,",
     "((DriverDesiredSpeedFn)e->fn)(vt_this(drv, e), drv->Throttle, 1.0f,"),
    ("dis_call_allowed", C, "                                  drv->Throttle, 1);",
     "                                  drv->Throttle, 0);"),
    # ---- steer_at_target
    ("sat_x", C, "    to.x = d->v2SteerTarget.x - car->State.Position.x;\n    to.y = d->v2SteerTarget.y - car->State.Position.y;\n    bToPolar(&pol, &to);\n    m->aDesiredFacingAngle = pol.a;\n    m->fMaxThrottleAccel",
     "    to.x = car->State.Position.x - d->v2SteerTarget.x;\n    to.y = d->v2SteerTarget.y - car->State.Position.y;\n    bToPolar(&pol, &to);\n    m->aDesiredFacingAngle = pol.a;\n    m->fMaxThrottleAccel"),
    ("sat_angle", C, "    m->aDesiredFacingAngle = pol.a;\n    m->fMaxThrottleAccel = CD_TURN_THROTTLE;",
     "    m->fMaxThrottleAccel = CD_TURN_THROTTLE;"),
    ("sat_throttle", C, "    m->fMaxThrottleAccel = CD_TURN_THROTTLE;\n", ""),
    ("sat_speed", C, "    m->fMaxThrottleAccel = CD_TURN_THROTTLE;\n    m->fDesiredSpeed = speed;",
     "    m->fMaxThrottleAccel = CD_TURN_THROTTLE;\n    m->fDesiredSpeed = -speed;"),
    # ---- translating
    ("tr_state", C, "    m->State = eCMS_TRANSLATING;\n", ""),
    ("tr_player", C, "    if (chased->pPlayer != NULL) {\n        bVector2 w;",
     "    if (chased->pPlayer == NULL) {\n        bVector2 w;"),
    ("tr_hist_n0", C, "        if (0.0f < n0) {", "        if (0.0f <= n0) {"),
    ("tr_hist_s", C, "            s = ee_div(sqrtf(w.x * w.x + w.y * w.y), n0);",
     "            s = ee_div(n0, sqrtf(w.x * w.x + w.y * w.y));"),
    ("tr_hist_scale", C, "            v.x = v.x * s;\n            v.y = v.y * s;\n        }\n    } else {",
     "            v.x = v.x * s;\n        }\n    } else {"),
    ("tr_vel", C, "        v.x = chased->State.Velocity.x;\n        v.y = chased->State.Velocity.y;",
     "        v.x = chased->State.Velocity.x;\n        v.y = chased->State.Velocity.x;"),
    ("tr_block", C, "    case LSS_BLOCK:\n    case LSS_STOP:\n        along = 1.5f;",
     "    case LSS_STOP:\n        along = 1.5f;"),
    ("tr_stop", C, "    case LSS_STOP:\n        along = 1.5f;", "    case LSS_FLANK:\n        along = 1.5f;"),
    ("tr_block_along", C, "        along = 1.5f;\n        extra = 3.0f;", "        along = 1.25f;\n        extra = 3.0f;"),
    ("tr_block_extra", C, "        along = 1.5f;\n        extra = 3.0f;", "        along = 1.5f;\n        extra = 2.0f;"),
    ("tr_ahead_extra", C, "        extra = 3.0f;\n        across = 10.0f;", "        extra = 2.0f;\n        across = 10.0f;"),
    ("tr_ahead_across", C, "        across = 10.0f;", "        across = 9.0f;"),
    ("tr_acq_lane", C, "        if (fabsf(lc - lm) <= CD_ACQUIRE_LANE) {\n            if (chased->State.ForwardSpeed * CD_MPS_TO_MPH < CD_ACQUIRE_MPH) {\n                v.x = 0.0f;",
     "        if (fabsf(lc - lm) < CD_ACQUIRE_LANE) {\n            if (chased->State.ForwardSpeed * CD_MPS_TO_MPH < CD_ACQUIRE_MPH) {\n                v.x = 0.0f;"),
    ("tr_acq_mph", C, "            if (chased->State.ForwardSpeed * CD_MPS_TO_MPH < CD_ACQUIRE_MPH) {\n                v.x = 0.0f;",
     "            if (chased->State.ForwardSpeed * CD_MPS_TO_MPH <= CD_ACQUIRE_MPH) {\n                v.x = 0.0f;"),
    ("tr_acq_fs", C, "            if (chased->State.ForwardSpeed * CD_MPS_TO_MPH < CD_ACQUIRE_MPH) {\n                v.x = 0.0f;",
     "            if (chased->State.VelocityMagnitude * CD_MPS_TO_MPH < CD_ACQUIRE_MPH) {\n                v.x = 0.0f;"),
    ("tr_acq_zero", C, "                v.x = 0.0f;\n                v.y = 0.0f;\n                break;",
     "                v.x = 0.0f;\n                break;"),
    ("tr_acq_half", C, "            s = 0.5f;", "            s = 0.6f;"),
    ("tr_acq_up", C, "        } else {\n            s = CD_SPEED_UP;\n        }",
     "        } else {\n            s = 1.0f;\n        }"),
    ("tr_limbo_brake", C, "        m->fMaxBrakingAccel = 14.0f;", "        m->fMaxBrakingAccel = 13.0f;"),
    ("tr_limbo_across", C, "        m->fMaxBrakingAccel = 14.0f;\n        across = 3.0f;",
     "        m->fMaxBrakingAccel = 14.0f;\n        across = 2.0f;"),
    ("tr_along1", C, "    float    along = 1.0f, across = 1.5f, extra = 0.0f, proj, len;",
     "    float    along = 1.1f, across = 1.5f, extra = 0.0f, proj, len;"),
    ("tr_across1", C, "    float    along = 1.0f, across = 1.5f, extra = 0.0f, proj, len;",
     "    float    along = 1.0f, across = 1.25f, extra = 0.0f, proj, len;"),
    ("tr_norm_vel", C, "    bNormalize2(&u, (const bVector2 *)(const void *)&car->State.Velocity);",
     "    bNormalize2(&u, (const bVector2 *)(const void *)&chased->State.Velocity);"),
    ("tr_proj", C, "    proj = to->x * u.x + to->y * u.y;", "    proj = to->x * u.x - to->y * u.y;"),
    ("tr_q", C, "    q.y = to->y - a.y;", "    q.y = to->y + a.y;"),
    ("tr_limbo_zero", C, "    if (cop->Base.LogicSubState == LSS_LIMBO_READY) {\n        want.x = 0.0f;",
     "    if (0) {\n        want.x = 0.0f;"),
    ("tr_want_y", C, "        want.y = (a.y * along + q.y * across) + v.y;",
     "        want.y = (a.y * along + q.y * across) - v.y;"),
    ("tr_want_x", C, "        want.x = (a.x * along + q.x * across) + v.x;",
     "        want.x = (a.x * across + q.x * along) + v.x;"),
    ("tr_len0", C, "    if (0.0f < len) {\n        float s = ee_div(len + extra, len);",
     "    if (0.0f <= len) {\n        float s = ee_div(len + extra, len);"),
    ("tr_extra", C, "        float s = ee_div(len + extra, len);", "        float s = ee_div(len - extra, len);"),
    ("tr_out_y", C, "    m->v3DesiredVelocity.y = want.y;\n", ""),
    ("tr_out_z", C, "    m->v3DesiredVelocity.y = want.y;\n    m->v3DesiredVelocity.z = 0.0f;",
     "    m->v3DesiredVelocity.y = want.y;"),
    # ---- steering
    ("st_state", C, "    m->State = eCMS_STEERING;\n    bToPolar(&pol, to);", "    bToPolar(&pol, to);"),
    ("st_angle", C, "    bToPolar(&pol, to);\n    m->aDesiredFacingAngle = pol.a;\n\n",
     "    bToPolar(&pol, to);\n\n"),
    ("st_close", C, "    case LSS_LOW_SPEED_CLOSE_FOLLOW:\n    case LSS_FOLLOW_BACKWARDS:\n    case LSS_BUMP:",
     "    case LSS_FOLLOW_BACKWARDS:\n    case LSS_BUMP:"),
    ("st_backwards", C, "    case LSS_FOLLOW_BACKWARDS:\n    case LSS_BUMP:", "    case LSS_BUMP:"),
    ("st_bump", C, "    case LSS_BUMP:\n    case LSS_BLOCK:\n    case LSS_GET_AHEAD:\n        speed = dist + ch_speed;",
     "    case LSS_BLOCK:\n    case LSS_GET_AHEAD:\n        speed = dist + ch_speed;"),
    ("st_block", C, "    case LSS_BLOCK:\n    case LSS_GET_AHEAD:\n        speed = dist + ch_speed;",
     "    case LSS_GET_AHEAD:\n        speed = dist + ch_speed;"),
    ("st_ahead", C, "    case LSS_GET_AHEAD:\n        speed = dist + ch_speed;",
     "    case LSS_PURSUIT_FOLLOW:\n        speed = dist + ch_speed;"),
    ("st_follow", C, "        speed = dist + ch_speed;", "        speed = dist - ch_speed;"),
    ("st_flank", C, "        speed = dist * 5.0f + ch_speed;", "        speed = dist * 4.0f + ch_speed;"),
    ("st_acq_lane", C, "        if (fabsf(lc - lm) <= CD_ACQUIRE_LANE) {\n            if (chased->State.ForwardSpeed * CD_MPS_TO_MPH < CD_ACQUIRE_MPH)\n                speed = 0.0f;",
     "        if (fabsf(lc + lm) <= CD_ACQUIRE_LANE) {\n            if (chased->State.ForwardSpeed * CD_MPS_TO_MPH < CD_ACQUIRE_MPH)\n                speed = 0.0f;"),
    ("st_acq_mph", C, "            if (chased->State.ForwardSpeed * CD_MPS_TO_MPH < CD_ACQUIRE_MPH)\n                speed = 0.0f;",
     "            if (chased->State.ForwardSpeed * CD_MPS_TO_MPH <= CD_ACQUIRE_MPH)\n                speed = 0.0f;"),
    ("st_acq_half", C, "                speed = ch_speed * 0.5f;", "                speed = ch_speed * 0.6f;"),
    ("st_acq_up", C, "        } else {\n            speed = ch_speed * CD_SPEED_UP;\n        }\n        break;",
     "        } else {\n            speed = ch_speed;\n        }\n        break;"),
    ("st_stop", C, "    case LSS_STOP:\n        speed = ch_speed * CD_SPEED_UP;", "    case LSS_STOP:\n        speed = ch_speed;"),
    ("st_limbo", C, "        speed = m->fBaseMaxSpeed;", "        speed = m->fSpeed;"),
    ("st_cls_min", C, "    if (cc < cls)\n        cls = cc;", "    if (cc > cls)\n        cls = cc;"),
    ("st_rp", C, "    rp = car_get_route_point(d->Base.Base.pCar, 1);\n    lvl", "    rp = car_get_route_point(chased, 1);\n    lvl"),
    ("st_lvl", C, "    lvl = chased->pPlayer != NULL ? pCopManager->nDifficultyLevel : 2;",
     "    lvl = pCopManager->nDifficultyLevel;"),
    ("st_lvl_2", C, "    lvl = chased->pPlayer != NULL ? pCopManager->nDifficultyLevel : 2;",
     "    lvl = chased->pPlayer != NULL ? pCopManager->nDifficultyLevel : 1;"),
    ("st_lim", C, "    lim = trpoint_get_driving_line_speed(rp, cls) * CopLineSpeedScale[lvl];",
     "    lim = trpoint_get_driving_line_speed(rp, cls);"),
    ("st_min", C, "    speed = min_f(lim, speed);", "    speed = min_f(speed, lim);"),
    ("st_no_min", C, "    speed = min_f(lim, speed);\n", ""),
    ("st_slow_lt", C, "    if (CD_SLOW_SPEED < speed) {", "    if (CD_SLOW_SPEED <= speed) {"),
    ("st_ahead_x", C, "        ahead.x = chased->State.Position.x - car->State.Position.x;",
     "        ahead.x = car->State.Position.x - chased->State.Position.x;"),
    ("st_turn_signed", C, "        turn = (int16_t)(uint16_t)(pc.a - d->Base.Base.pCar->State.Angle);\n        if (CD_QUARTER_TURN < fabsf((float)turn)",
     "        turn = (int16_t)(uint16_t)(pc.a - d->Base.Base.pCar->State.Angle);\n        if (CD_QUARTER_TURN < (float)(uint16_t)turn"),
    ("st_turn_lt", C, "        if (CD_QUARTER_TURN < fabsf((float)turn) && 1.0f < pc.r)",
     "        if (CD_QUARTER_TURN <= fabsf((float)turn) && 1.0f < pc.r)"),
    ("st_r_lt", C, "        if (CD_QUARTER_TURN < fabsf((float)turn) && 1.0f < pc.r)",
     "        if (CD_QUARTER_TURN < fabsf((float)turn) && 1.0f <= pc.r)"),
    ("st_r_no", C, "        if (CD_QUARTER_TURN < fabsf((float)turn) && 1.0f < pc.r)",
     "        if (CD_QUARTER_TURN < fabsf((float)turn))"),
    ("st_out", C, "            speed = CD_SLOW_SPEED;\n    }\n    m->fDesiredSpeed = speed;",
     "            speed = CD_SLOW_SPEED;\n    }\n    m->fDesiredSpeed = lim;"),
    # ---- think_pursuit
    ("tp_no_gptp", C, "    copdriver_get_pursuit_target_point(d, &d->v2SteerTarget);\n    car = d->Base.Base.pCar;\n    to.x",
     "    car = d->Base.Base.pCar;\n    to.x"),
    ("tp_to_y", C, "    to.y = d->v2SteerTarget.y - car->State.Position.y;\n    // (The image",
     "    to.y = car->State.Position.y - d->v2SteerTarget.y;\n    // (The image"),
    ("tp_ch_speed", C, "    float     ch_speed = chased->State.VelocityMagnitude;",
     "    float     ch_speed = chased->State.ForwardSpeed;"),
    ("tp_dist", C, "    dy = car->State.Position.y - chased->State.Position.y;\n    dist",
     "    dy = 0.0f;\n    dist"),
    ("tp_dot", C, "        + chased->State.Velocity.y * car->State.Velocity.y;",
     "        - chased->State.Velocity.y * car->State.Velocity.y;"),
    ("tp_dist_lt", C, "    if (dist < CD_TRANSLATE_DIST && 0.0f < dot", "    if (dist <= CD_TRANSLATE_DIST && 0.0f < dot"),
    ("tp_dot_lt", C, "    if (dist < CD_TRANSLATE_DIST && 0.0f < dot", "    if (dist < CD_TRANSLATE_DIST && 0.0f <= dot"),
    ("tp_speed_le", C, "        && CD_TRANSLATE_SPEED <= car->State.VelocityMagnitude)",
     "        && CD_TRANSLATE_SPEED < car->State.VelocityMagnitude)"),
    ("tp_speed_ch", C, "        && CD_TRANSLATE_SPEED <= car->State.VelocityMagnitude)",
     "        && CD_TRANSLATE_SPEED <= chased->State.VelocityMagnitude)"),
    # ---- Think
    ("th_no_tc", C, "    trackedcontroller_think(&d->Base, dt);\n    car = d->Base.Base.pCar;",
     "    car = d->Base.Base.pCar;"),
    ("th_mode", C, "    if (car->TheMovementMode != COP_MOVEMENT)\n        return;",
     "    if (car->TheMovementMode == 0)\n        return;"),
    ("th_stuck_near", C, "    if (copdriver_are_we_stuck(d, dt) && !taicop_is_near_pursuit_target(cop)) {",
     "    if (copdriver_are_we_stuck(d, dt)) {"),
    ("th_stuck_before", C, "        d->StateBeforeGettingStuck = d->State;\n        d->State = eCDS_BACKING_UP;",
     "        d->State = eCDS_BACKING_UP;"),
    ("th_stuck_timer", C, "        d->fBackingUpTimer = CD_BACK_UP_TIME;\n    }",
     "        d->fBackingUpTimer = CD_BACK_UP_TIME * 0.5f;\n    }"),
    ("th_brake", C, "    m->fMaxBrakingAccel = CM_BRAKING_ACCEL;\n    copmover_reset_max_throttle_accel(m);\n\n    switch",
     "    copmover_reset_max_throttle_accel(m);\n\n    switch"),
    ("th_rmta", C, "    m->fMaxBrakingAccel = CM_BRAKING_ACCEL;\n    copmover_reset_max_throttle_accel(m);\n\n    switch",
     "    m->fMaxBrakingAccel = CM_BRAKING_ACCEL;\n\n    switch"),
    ("th_parked_speed", C, "    case eCDS_PARKED:\n        m->fDesiredSpeed = 0.0f;",
     "    case eCDS_PARKED:\n        m->fDesiredSpeed = 1.0f;"),
    ("th_parked_state", C, "        m->fDesiredSpeed = 0.0f;\n        m->State = eCMS_STEERING;\n        break;\n    case eCDS_PATROLLING:",
     "        m->fDesiredSpeed = 0.0f;\n        break;\n    case eCDS_PATROLLING:"),
    ("th_patrol_state", C, "        // Along the cop's own drive target (its AI's), 20 m on.\n        m->State = eCMS_STEERING;\n",
     "        // Along the cop's own drive target (its AI's), 20 m on.\n"),
    ("th_patrol_off", C, "                                         CD_TARGET_DIST, &cop->New48);\n        steer_at_target(d, m, d->fPatrolSpeed);",
     "                                         CD_TARGET_DIST, &cop->MyDLOffset);\n        steer_at_target(d, m, d->fPatrolSpeed);"),
    ("th_patrol_speed", C, "        steer_at_target(d, m, d->fPatrolSpeed);", "        steer_at_target(d, m, CD_PATROL_SPEED);"),
    ("th_pursuit_null", C, "        if (p != NULL)\n            think_pursuit(d, cop, p, chased, m);",
     "        if (p != NULL && chased->pPlayer != NULL)\n            think_pursuit(d, cop, p, chased, m);"),
    ("th_back_dt", C, "        d->fBackingUpTimer = d->fBackingUpTimer - dt;",
     "        d->fBackingUpTimer = d->fBackingUpTimer - dt * 0.5f;"),
    ("th_back_lt", C, "        if (d->fBackingUpTimer < 0.0f) {", "        if (d->fBackingUpTimer <= 0.0f) {"),
    ("th_back_restore", C, "            d->State = d->StateBeforeGettingStuck;\n            break;",
     "            d->State = eCDS_PATROLLING;\n            break;"),
    ("th_back_continue", C, "            d->State = d->StateBeforeGettingStuck;\n            break;\n        }",
     "            d->State = d->StateBeforeGettingStuck;\n        }"),
    ("th_back_patrol", C, "        if (d->StateBeforeGettingStuck == eCDS_PATROLLING)\n",
     "        if (d->StateBeforeGettingStuck == eCDS_PARKED)\n"),
    ("th_back_pursuit", C, "        else if (d->StateBeforeGettingStuck == eCDS_PURSUIT)\n",
     "        else if (d->StateBeforeGettingStuck != eCDS_PURSUIT)\n"),
    ("th_back_state", C, "            copdriver_get_pursuit_target_point(d, &d->v2SteerTarget);\n        m->State = eCMS_STEERING;\n        steer_at_target(d, m, CD_BACK_UP_SPEED);",
     "            copdriver_get_pursuit_target_point(d, &d->v2SteerTarget);\n        steer_at_target(d, m, CD_BACK_UP_SPEED);"),
    # ---- the accessors and the table
    ("sps", C, "    d->fPatrolSpeed = s;", "    d->fPatrolSpeed = s + 1.0f;"),
    ("sst", C, "    d->State = s;\n}", "    d->State = s & 3;\n}"),
    ("sci", C, "    d->nCopIndex = n;", "    d->nCopIndex = n + 0 * n - (n < 0);"),
    ("vt_think", C, "    E(vt_CopDriver_Think),                          //  32  0x001a2110",
     "    { 0, 0, NULL },                                 //  32  0x001a2110"),
    ("seam", C, "    gCopDriverCtorFn = copdriver_construct;", "    gCopDriverCtorFn = NULL;"),
    # ---- VelocityAt (copmanager.c)
    ("va_le", CM, "        if (t <= acc) {", "        if (t < acc) {"),
    ("va_last", CM, "            if (i < h->nCount - 1) {", "            if (i < h->nCount) {"),
    ("va_first", CM, "                acc -= h->fTime[0];", "                acc -= ft;"),
    ("va_dx", CM, "                dx = ee_div(a->x - b->x, ft);", "                dx = ee_div(b->x - a->x, ft);"),
    ("va_dy", CM, "                dy = ee_div(a->y - b->y, ft);", "                dy = ee_div(a->y - b->y, h->fTime[0]);"),
    ("va_rx", CM, "                r.x = a->x + dx * acc;", "                r.x = b->x + dx * acc;"),
    ("va_ry", CM, "                r.y = a->y + dy * acc;", "                r.y = a->y + dx * acc;"),
    ("va_no_break", CM, "            }\n            break;\n        }\n    }\n    *out = r;",
     "            }\n        }\n    }\n    *out = r;"),
    ("va_start", CM, "    bVector2 r = h->v2Velocity[0];", "    bVector2 r = h->v2Velocity[1];"),
    # ---- CarInRecentCollision (coputil.c)
    ("crc", CU, "    return car->pDynamicCollisionBody->Dynamic.Body.NumCollisions != 0;",
     "    return car->pDynamicCollisionBody->Dynamic.Body.NumCollisions > 0;"),
]

EQUIVALENT = {
    "tr_len0": "len is a root, so 0 <= len fails only at 0, where s is "
               "(0 + extra) / 0 and want is 0 * s: 0, or NaN with extra",
    "ctor_malloc_size": "a NullDriver is a CarDriver and nothing more: "
                        "both are 560 bytes",
    "fpd_zero": "below 0 the segment loop starts at n - 2 < 0 and runs no "
                "times, so both reach the not-found fallback, Points[0]",
    "fpd_len0": "a zero-length segment fails 0 <= along < len for any along "
                "(and a NaN fails both), so its unit is never read",
    "tr_limbo_across": "LIMBO_READY zeroes want, so its across is never "
                       "read; the image stores 3.0 to $f21 and branches past "
                       "it too (0x001a25fc, 0x001a2664)",
    "st_slow_lt": "at exactly 20 mph the clamp sets the speed it already "
                  "has, and bToPolar has no side effects",
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
        todo, SOURCES, "copdriver_test",
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
