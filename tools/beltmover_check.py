"""Cross-check 3DS Files/source/beltmover.c against the retail image's own
code.

BeltMover is the cheap mover an AI car rides when no player is near:
retail's BeltMover.obj, 0x00204098 to 0x002056b4. The oracle is SLES_507.31
itself, run in tools/mipsemu.py:

- the constructor (0x00204098), the destructor (0x002043a0, reached
  through the table at 0x002bb090), Dot, GetAccelerationDueToGravity,
  GetMaximumAcceleration, FindCoordinates, SetBelt, SlideCoef, AverageAir,
  Move (through the table), GetPoint, GetDerivative and
  GetSecondDerivative;
- run as shipped under them: QuickSpline, Average, Graph, tCubic1D and
  tCubic2D (SetVal, SetdVal, SetValDesired, GetVal, GetdVal, SplineSeek,
  GetddVal), bSin, bCos, bATan, bNormalize and the start-up code
  (_GLOBAL_$I$fBeltAccelCoef, 0x002055c8) that builds the two Graphs, which
  the port has as data.

Stood in on both sides, each call logged: bOMalloc and Wheel's
constructor, SetState, MaybeMakeSkids and destructor (through a fake
table); DriveTarget::Resample; CalculateMaxAcceleration (scripted);
Car::PutFlatOnTrack (which moves the car up by a scripted step, so Move's
velocity is seen to come from the position after it), ComputeFakeRPM and
ShouldVisualEffectsBeGenerated (scripted); CarState::
CalculateGeometryPosition; World::GetDistanceToClosestPlayer (scripted);
~CarMover; and the driver's GetDesiredSpeed (136) and
GetDesiredTimeToSpeed (144), through a fake driver table.

The port's QuickSpline clears its buffer and allocates one point more
(quickspline.c), so the model's bMalloc clears quickspline.cpp's block, as
quickspline_check's does, and the harness logs that block one point
short. Host sizes of the Average and the QuickSpline are logged as the
console's. AngularVelocity's fourth word is Move's stack in the image, and
is not compared.

    python tools/beltmover_check.py
    python tools/beltmover_check.py --mutate [--only a,b]
    python tools/beltmover_check.py --dump PREFIX
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
import hostbuild
import physicscar_check as pcc
import retail_model
from mipsemu import M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/beltmover_test.c"
BMC = "3DS Files/source/beltmover.c"
BAC = "3DS Files/source/banim.c"
SOURCES = [HARNESS, BMC, BAC,
           "3DS Files/source/average.c",
           "3DS Files/source/graph.c",
           "3DS Files/source/quickspline.c",
           "3DS Files/source/bmem.c",
           "3DS Files/source/bmatrix.c",
           "3DS Files/source/bvector.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c",
           "3DS Files/source/replay.c", "3DS Files/source/p32.c",
           "3DS Files/source/vtable.c"]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = retail_model.RETAIL_GP

F = dict(
    ctor=0x00204098,
    dot=0x002045b8,
    grav=0x00204668,
    maxacc=0x002046f0,
    find=0x00204718,
    setbelt=0x00204990,
    slide=0x00204a30,
    air=0x00204bd8,
    gp=0x002053a8,
    gd=0x00205458,
    gdd=0x002054d8,
    sinit=0x002055c8,
)

BMALLOC = 0x002577c0
BDELETE = 0x00114e98
BFREE = 0x00257850
BOMALLOC = 0x00257c80
WHEEL_CTOR = 0x001a3f10
WHEEL_SETSTATE = 0x001a4170
WHEEL_SKIDS = 0x001a5520
RESAMPLE = 0x0021c5c8
CALC_MAXACC = 0x001cce50
PUT_FLAT = 0x00132910
GEOM_POS = 0x001c0f40
VFX = 0x00135e18
DIST = 0x0014e440
FAKE_RPM = 0x00132b00
CARMOVER_DTOR = 0x00136b78

STUB_GDS = 0x010b3500               # the driver's GetDesiredSpeed (136)
STUB_GTTS = 0x010b3510              # ... GetDesiredTimeToSpeed (144)
STUB_WDTOR = 0x010b3520             # the Wheels' destructor (8)

WHEEL_POOL_GP = -22824
WORLD_GP = -22120
SLIDE_GRAPH_GP = -16592
SLIDING_GRAPH_GP = -16584

BMA = 0x01E00000                    # the BeltMover
CAR = 0x01E01000
CS = CAR + 64
CTI = 0x01E02000
DRV = 0x01E03000
AICC = 0x01E04000
WORLD = 0x01E05000
DVT = 0x01E06000                    # the fake driver table
WVT = 0x01E06200                    # the fake Wheel table
POOL = 0x01E06400                   # Wheel's SlotPool, never read
SCR = 0x01E07000                    # Dot's and the getters' vectors
BM_SIZE = 72
SLACK = 16
WHEEL_SIZE = 400

# Retail's CarState offsets.
CS_POS, CS_VEL, CS_ROW0, CS_ROW1, CS_AV = 32, 48, 80, 96, 144
CS_WAV, CS_WANG, CS_WSLIP, CS_WTU = 688, 704, 820, 852
CS_ANGLE, CS_FS, CS_VM, CS_MV = 868, 896, 900, 1024

# The script's CarState fields: (retail offset, kind). The harness has the
# same list by name.
CSF = ([(CS_POS + 4 * k, "f") for k in range(4)]          # 0..3
       + [(CS_VEL + 4 * k, "f") for k in range(4)]        # 4..7
       + [(CS_ROW0 + 4 * k, "f") for k in range(4)]       # 8..11
       + [(CS_ROW1 + 4 * k, "f") for k in range(4)]       # 12..15
       + [(CS_AV + 4 * k, "f") for k in range(4)]         # 16..19
       + [(CS_WAV + 4 * k, "f") for k in range(4)]        # 20..23
       + [(CS_WANG + 4 * k, "f") for k in range(4)]       # 24..27
       + [(CS_WSLIP + 4 * k, "f") for k in range(8)]      # 28..35
       + [(CS_WTU + 4 * k, "f") for k in range(4)]        # 36..39
       + [(CS_ANGLE, "h"), (CS_FS, "f"), (CS_VM, "f"),    # 40..42
          (CS_MV, "w")])                                  # 43
C_POS, C_VEL, C_ROW0, C_ROW1, C_AV = 0, 4, 8, 12, 16
C_WAV, C_WANG, C_WSLIP, C_WTU = 20, 24, 28, 36
C_ANGLE, C_FS, C_VM, C_MV = 40, 41, 42, 43

# CarTypeInfo, whose prefix the port lays out as the console does.
T_WHEEL = 288                       # + 32 i: Radius +12, WheelNumber +20
T_TIRE = 416                        # + 32 i: ForceScale +8, static +12,
                                    #         dynamic +16
T_MASS = 480
T_FDOWN, T_RDOWN = 756, 760
T_CONTROL = 768

(OP_TAG, OP_JUNK, OP_CS, OP_CTI, OP_DTN, OP_DTP, OP_DTL, OP_STEER, OP_SET,
 OP_NEW, OP_DEL, OP_SETBELT, OP_FIND, OP_MOVE, OP_GRAV, OP_MAXACC,
 OP_SLIDE, OP_AIR, OP_GP, OP_GD, OP_GDD, OP_DOT, OP_POKE, OP_CUBIC,
 OP_AVGREC, OP_DUMP, OP_TIMER, OP_NULLP, OP_DDVAL, OP_CPW) = range(30)

ARGS = {OP_TAG: 1, OP_JUNK: 1, OP_CS: 2, OP_CTI: 2, OP_DTN: 1, OP_DTP: 4,
        OP_DTL: 1, OP_STEER: 1, OP_SET: 2, OP_NEW: 0, OP_DEL: 1,
        OP_SETBELT: 0, OP_FIND: 0, OP_MOVE: 1, OP_GRAV: 0, OP_MAXACC: 0,
        OP_SLIDE: 1, OP_AIR: 1, OP_GP: 1, OP_GD: 1, OP_GDD: 1, OP_DOT: 5,
        OP_POKE: 2, OP_CUBIC: 3, OP_AVGREC: 1, OP_DUMP: 0, OP_TIMER: 1,
        OP_NULLP: 1, OP_DDVAL: 2, OP_CPW: 2}

# OP_SET's keys: what the stand-ins answer.
K_DSPEED, K_DTTS, K_MAXACC, K_VFX, K_DIST, K_FLATDZ = range(6)

# OP_POKE's offsets, the console's: fTime, fScale, v, dv, ddv, bSliding.
P_TIME, P_SCALE, P_V, P_DV, P_DDV, P_SLIDING = 12, 16, 28, 32, 36, 52
# OP_CUBIC's cubics: the across-belt one, then x and y of the two 2Ds.
CU_U, CU_AX, CU_AY, CU_SX, CU_SY = range(5)
# OP_NULLP's pointers: the Average, the QuickSpline, the Wheels.
NP_AVG, NP_SPLINE, NP_WHEEL0 = 0, 1, 2


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

    def cs3(self, field, x, y, z, w=0.0):
        for k, v in enumerate((x, y, z, w)):
            self.cs(field + k, float(v))

    def set(self, key, v):
        self.op(OP_SET, key, v if isinstance(v, (int, Fb)) else float(v))

    def belt(self, pts, length=None):
        """The driver's DriveTarget: the points and their length, the sum of
        the straight runs unless given."""
        self.op(OP_DTN, len(pts))
        for i, p in enumerate(pts):
            self.op(OP_DTP, i, float(p[0]), float(p[1]), float(p[2]))
        if length is None:
            length = 0.0
            for a, b in zip(pts, pts[1:]):
                length += math.sqrt(sum((b[k] - a[k]) ** 2 for k in range(3)))
        self.op(OP_DTL, f32(length))

    def car(self, pos, heading_deg, speed, yaw_rate=0.0, ang=None):
        """The car at `pos`, heading along the angle, at `speed`, its body
        rows along the heading and to its left."""
        a = math.radians(heading_deg)
        c, s = math.cos(a), math.sin(a)
        # A w the velocity's fourth lane takes the old position's of.
        self.cs3(C_POS, pos[0], pos[1], pos[2], 0.375)
        self.cs3(C_VEL, f32(speed * c), f32(speed * s), 0.0)
        self.cs3(C_ROW0, f32(c), f32(s), 0.0)
        self.cs3(C_ROW1, f32(-s), f32(c), 0.0)
        # x and y, which Move clears, and the traction, which it zeroes.
        self.cs3(C_AV, 0.015, -0.025, yaw_rate)
        for i in range(4):
            self.cs(C_WTU + i, 0.25 + 0.125 * i)
        if ang is None:
            ang = int(round(heading_deg * 65536.0 / 360.0)) & 0xffff
        self.cs(C_ANGLE, ang)
        # The forward speed a little under the magnitude, so a read of
        # the one for the other shows.
        self.cs(C_VM, f32(abs(speed)))
        self.cs(C_FS, f32(speed * 0.97))
        self.cs(C_MV, 1)

    def car_type(self, radius=0.33, numbers=(0, 1, 2, 3), mass=1450.0,
                 force=(1.0, 1.1), static=(1.2, 1.15), dynamic=(0.9, 0.85),
                 down=(0.6, 0.8)):
        for i in range(4):
            self.op(OP_CTI, T_WHEEL + 32 * i + 12, fb(f32(radius + 0.01 * i)))
            self.op(OP_CTI, T_WHEEL + 32 * i + 20, numbers[i])
        for i in range(2):
            self.op(OP_CTI, T_TIRE + 32 * i + 8, fb(f32(force[i])))
            self.op(OP_CTI, T_TIRE + 32 * i + 12, fb(f32(static[i])))
            self.op(OP_CTI, T_TIRE + 32 * i + 16, fb(f32(dynamic[i])))
        self.op(OP_CTI, T_MASS, fb(f32(mass)))
        self.op(OP_CTI, T_FDOWN, fb(f32(down[0])))
        self.op(OP_CTI, T_RDOWN, fb(f32(down[1])))

    def wheels(self, av, ang):
        for i in range(4):
            self.cs(C_WAV + i, f32(av[i]))
            self.cs(C_WANG + i, f32(ang[i]))

    def moves(self, dt, n, every=1):
        for i in range(n):
            self.op(OP_MOVE, f32(dt))
            if (i + 1) % every == 0 or i == n - 1:
                self.op(OP_DUMP)


# ============================================================== the script

def straight(n=11, step=10.0, y=0.0, z=0.0):
    return [(step * i, y, z) for i in range(n)]


def arc(n, r, deg_step, cx=0.0, cy=0.0, z=0.0, start=-90.0):
    out = []
    for i in range(n):
        a = math.radians(start + deg_step * i)
        out.append((f32(cx + r * math.cos(a)), f32(cy + r * math.sin(a)),
                    z))
    return out


def crest(n=12):
    """Up a ramp and over the edge."""
    out = []
    for i in range(n):
        x = 10.0 * i
        z = 0.8 * i if i < 5 else 4.0 - 3.0 * (i - 5) ** 1.5
        out.append((x, 0.0, f32(z)))
    return out


def walk(rnd, n, step=10.0, bend=0.25, climb=0.15):
    out = []
    x = y = z = 0.0
    h = rnd.uniform(-math.pi, math.pi)
    for i in range(n):
        out.append((f32(x), f32(y), f32(z)))
        h += rnd.uniform(-bend, bend)
        x += step * math.cos(h)
        y += step * math.sin(h)
        z += rnd.uniform(-climb, climb) * step
    return out


def standard(sc, speed=20.0, dspeed=30.0, dtts=2.0, maxacc=6.0):
    sc.set(K_DSPEED, dspeed)
    sc.set(K_DTTS, dtts)
    sc.set(K_MAXACC, maxacc)
    sc.set(K_VFX, 1)
    sc.set(K_DIST, 150.0)
    sc.set(K_FLATDZ, 0.0)


def script():
    sc = Script()
    rnd = random.Random(0xbe17)

    sc.car_type()
    sc.wheels((30.0, 31.0, 29.5, 30.5), (0.5, 1.0, 1.5, 2.0))
    sc.op(OP_STEER, 1200)

    # -- the constructor --------------------------------------------------
    sc.tag("new")
    standard(sc)
    sc.car((-3.0, 1.0, 0.0), 0.0, 20.0, yaw_rate=0.25)
    sc.op(OP_JUNK, 1)
    sc.op(OP_NEW)
    sc.op(OP_DUMP)
    sc.op(OP_GRAV)                       # no control points yet
    sc.op(OP_DEL, 3)

    for heading, speed, yaw, ang in ((90.0, 35.0, -0.6, None),
                                     (200.0, 0.0, 0.0, None),
                                     (-45.0, 12.5, 1.25, 0xc000),
                                     (0.0, 50.0, 0.0, 0xffff),
                                     (0.0, 8.0, 3.0, 0x3fff)):
        sc.tag("new %s %s" % (heading, speed))
        sc.car((0.0, 0.0, 0.0), heading, speed, yaw_rate=yaw, ang=ang)
        sc.op(OP_JUNK, 2)
        sc.op(OP_NEW)
        sc.op(OP_DUMP)
        sc.op(OP_DEL, 1)

    # -- straight cruising -------------------------------------------------
    sc.tag("straight")
    standard(sc)
    sc.car((2.0, 1.5, 0.0), 0.0, 20.0)
    sc.belt(straight())
    sc.op(OP_JUNK, 3)
    sc.op(OP_NEW)
    sc.op(OP_SETBELT)
    sc.op(OP_DUMP)
    sc.op(OP_GRAV)
    sc.op(OP_MAXACC)
    sc.moves(1.0 / 30.0, 24, every=4)
    for t in (0.0, 0.5, 1.0, -0.25, 3.0):
        sc.op(OP_GP, f32(t))
        sc.op(OP_GD, f32(t))
        sc.op(OP_GDD, f32(t))
    for c in (CU_U, CU_AX, CU_AY, CU_SX, CU_SY):
        for t in (0.0, 0.5, 1.0):
            sc.op(OP_DDVAL, c, f32(t))
    sc.op(OP_DOT, 5.0, 2.0, 0.0, 0.0, 0.4)
    sc.op(OP_DOT, -1.0, -1.0, 3.0, 7.0, 1.6)
    sc.op(OP_AIR, 0.5)
    sc.op(OP_AIR, 0.0)
    sc.op(OP_DEL, 3)

    # -- a hill, the gravity's slope ----------------------------------------
    sc.tag("hill")
    pts = [(10.0 * i, 0.0, f32(0.12 * (10.0 * i))) for i in range(11)]
    sc.car((1.0, 0.0, 0.2), 0.0, 15.0)
    sc.belt(pts)
    sc.op(OP_JUNK, 4)
    sc.op(OP_NEW)
    sc.op(OP_SETBELT)
    sc.op(OP_GRAV)
    sc.op(OP_DUMP)
    sc.moves(1.0 / 30.0, 12, every=3)
    sc.op(OP_GRAV)
    sc.op(OP_DEL, 3)

    # -- the parameter before the belt: GetPoint's floor --------------------
    sc.tag("before the belt")
    sc.car((-14.0, 0.5, 0.0), 0.0, 10.0)
    sc.belt(pts)
    sc.op(OP_JUNK, 5)
    sc.op(OP_NEW)
    sc.op(OP_SETBELT)
    sc.op(OP_DUMP)
    for v in (-2.0, -0.5, -0.01, 0.0, 0.01):
        sc.op(OP_POKE, P_V, fb(f32(v)))
        for t in (0.0, 0.1, 0.4):
            sc.op(OP_GP, f32(t))
            sc.op(OP_GD, f32(t))
    sc.op(OP_FIND)
    sc.moves(1.0 / 30.0, 10, every=2)
    # Downhill into the start: the floor is the first point's height.
    sc.belt([(p[0], p[1], f32(-p[2])) for p in pts])
    sc.op(OP_SETBELT)
    for v in (-1.5, -0.25):
        sc.op(OP_POKE, P_V, fb(f32(v)))
        sc.op(OP_GP, 0.0)
    sc.op(OP_DEL, 3)

    # -- the desired speed: each way to ddv ---------------------------------
    for name, ds, tts, mx, speed in (
            ("tts > 0", 30.0, 2.0, 50.0, 20.0),
            ("tts 0", 30.0, 0.0, 50.0, 20.0),
            ("tts -0", 30.0, Fb(0x80000000), 50.0, 20.0),
            ("tts < 0", 30.0, -1.0, 50.0, 20.0),
            ("max", 60.0, 0.5, 2.0, 20.0),
            ("floor", 0.0, 0.05, 50.0, 40.0),
            ("both", 0.0, 0.05, -100.0, 40.0),
            ("max under the floor", 30.0, 2.0, -30.0, 20.0),
            ("tiny tts", 25.0, Fb(1), 3.0, 25.0)):
        sc.tag("ddv %s" % name)
        standard(sc, dspeed=ds, dtts=tts, maxacc=mx)
        sc.car((0.0, -0.5, 0.0), 0.0, speed)
        sc.belt(straight(15, 8.0))
        sc.op(OP_JUNK, 6)
        sc.op(OP_NEW)
        sc.op(OP_SETBELT)
        sc.op(OP_DUMP)
        sc.moves(1.0 / 30.0, 3)
        sc.op(OP_FIND)
        sc.op(OP_DUMP)
        sc.op(OP_DEL, 3)
    standard(sc)

    # The most acceleration and ddv the same float, under the floor: the
    # floor is the else's, so the tie keeps it out. Four points over 8 m
    # make the scale 0.5; a standing car, a time to speed of 1 and a
    # desired speed of -100 make ddv (0.5 x -100) x 0.899 exactly, which a
    # most acceleration of twice that meets.
    sc.tag("ddv tie")
    ddv = f32(f32(0.5 * -100.0) * f32(0.899))
    standard(sc, dspeed=-100.0, dtts=1.0, maxacc=f32(2.0 * ddv))
    sc.car((0.0, -0.5, 0.0), 0.0, 0.0)
    sc.belt(straight(4, 2.0), 8.0)
    sc.op(OP_JUNK, 6)
    sc.op(OP_NEW)
    sc.op(OP_SETBELT)
    sc.op(OP_DUMP)
    sc.op(OP_DEL, 3)
    standard(sc)

    # -- a standing car with nowhere to go: every tangent of the belt's
    # clock is 0, so the normalise divides by 0 the EE's way -----------------
    sc.tag("standing")
    standard(sc, dspeed=0.0)
    sc.car((1.0, 0.5, 0.0), 0.0, 0.0)
    sc.belt(straight())
    sc.op(OP_JUNK, 21)
    sc.op(OP_NEW)
    sc.op(OP_SETBELT)
    sc.op(OP_DUMP)
    sc.moves(1.0 / 30.0, 3)
    sc.op(OP_DEL, 3)
    standard(sc)

    # -- a DriveTarget of no length: the scale is the EE's FLT_MAX. With
    # the car standing and wanting nothing the speeds stay 0; no Move, which
    # would overflow ----------------------------------------------------------
    sc.tag("no length")
    standard(sc, dspeed=0.0, maxacc=0.5)
    sc.car((1.0, 0.5, 0.0), 0.0, 0.0)
    sc.belt(straight(5), 0.0)
    sc.op(OP_JUNK, 22)
    sc.op(OP_NEW)
    sc.op(OP_SETBELT)
    sc.op(OP_DUMP)
    sc.op(OP_GRAV)
    sc.op(OP_MAXACC)
    sc.op(OP_DEL, 3)
    standard(sc)

    # -- a hairpin: the car nearest point 3, with point 0 nearer than 1, so
    # the closest point is found by starting at 0 -----------------------------
    sc.tag("hairpin")
    sc.car((0.0, 3.0, 0.0), 180.0, 12.0)
    sc.belt([(0.0, -2.0, 0.0), (10.0, -2.0, 0.0), (10.0, 5.0, 0.0),
             (0.0, 4.0, 0.0), (-10.0, 4.0, 0.0), (-20.0, 4.0, 0.0)])
    sc.op(OP_JUNK, 23)
    sc.op(OP_NEW)
    sc.op(OP_SETBELT)
    sc.op(OP_DUMP)
    sc.moves(1.0 / 30.0, 6, every=2)
    sc.op(OP_DEL, 3)

    # -- the fourth lanes: SetBelt's w of 0 overwritten, so the spline's w
    # lane runs through the cross products, the normalise and the place ----
    sc.tag("w lanes")
    sc.car((0.0, 0.5, 0.0), 0.0, 24.0)
    pts = arc(10, 40.0, 12.0, cy=40.0)
    sc.belt(pts)
    sc.op(OP_JUNK, 24)
    sc.op(OP_NEW)
    sc.op(OP_SETBELT)
    for i in range(len(pts)):
        sc.op(OP_CPW, i, fb(f32(0.5 + 0.25 * i)))
    sc.op(OP_DUMP)
    for t in (0.0, 0.3, 1.0):
        sc.op(OP_GP, f32(t))
        sc.op(OP_GD, f32(t))
        sc.op(OP_GDD, f32(t))
    sc.op(OP_DOT, 5.0, 2.0, 0.0, 0.25, 0.4)
    sc.op(OP_GRAV)
    sc.op(OP_FIND)
    sc.op(OP_DUMP)
    sc.moves(1.0 / 30.0, 12, every=2)
    sc.op(OP_DEL, 3)

    # -- a scale of 0 in Move: the speed is the EE's 0/0, FLT_MAX. Wheels of
    # a metre and no downforce keep everything after it from overflowing --
    sc.tag("zero scale move")
    sc.car_type(radius=1.0, down=(0.0, 0.0))
    sc.car((0.0, 0.5, 0.0), 0.0, 0.0)
    sc.belt(straight())
    sc.op(OP_JUNK, 25)
    sc.op(OP_NEW)
    sc.op(OP_SETBELT)
    sc.op(OP_POKE, P_SCALE, 0)
    sc.op(OP_POKE, P_DV, 0)
    sc.op(OP_POKE, P_DDV, 0)
    sc.moves(1.0 / 30.0, 2)
    sc.op(OP_DEL, 3)
    sc.car_type()

    # -- a bend: the slide starts, and stops on the straight after ----------
    sc.tag("bend")
    pts = (arc(9, 30.0, 18.0, cx=0.0, cy=30.0)
           + [(f32(30.0 + 0.0), f32(30.0 + 10.0 * k), 0.0)
              for k in range(1, 9)])
    sc.car((0.0, 0.0, 0.0), 0.0, 32.0)
    sc.set(K_DSPEED, 40.0)
    sc.belt(pts)
    sc.op(OP_JUNK, 7)
    sc.op(OP_NEW)
    sc.op(OP_SETBELT)
    sc.op(OP_DUMP)
    sc.moves(1.0 / 30.0, 150, every=3)
    for c in (CU_U, CU_AX, CU_AY, CU_SX, CU_SY):
        sc.op(OP_DDVAL, c, f32(0.25))
    sc.op(OP_DEL, 3)
    standard(sc)

    # -- SlideCoef by itself ------------------------------------------------
    sc.tag("slide coef")
    sc.car((0.0, 0.0, 0.0), 0.0, 25.0)
    sc.belt(straight())
    sc.op(OP_JUNK, 8)
    sc.op(OP_NEW)
    sc.op(OP_SETBELT)
    for a in (0.0, Fb(0x80000000), 1.0, -1.0, 5.0, 9.0, 11.0, 12.5, -12.5,
              13.0, 15.0, 18.0, 25.0, -40.0, 8.0, 3.0, 0.5):
        sc.op(OP_SLIDE, a if isinstance(a, Fb) else f32(a))
        sc.op(OP_DUMP)
    # A grip the force meets exactly: hold = (down + 9.8 m) x grip, and the
    # need m x |a| x scale. Scale 1, no downforce: a = 9.8 x grip.
    sc.car_type(force=(1.0, 1.0), static=(1.0, 1.0), dynamic=(0.5, 0.5),
                down=(0.0, 0.0), mass=1000.0)
    sc.op(OP_POKE, P_SLIDING, 0)
    for a in (f32(9.8), bf(fb(f32(9.8)) + 1), bf(fb(f32(9.8)) - 1)):
        sc.op(OP_SLIDE, a)
        sc.op(OP_DUMP)
    sc.op(OP_POKE, P_SLIDING, 1)
    for a in (f32(4.9), bf(fb(f32(4.9)) + 1), bf(fb(f32(4.9)) - 1)):
        sc.op(OP_SLIDE, a)
        sc.op(OP_DUMP)
    # A zero scale, so the speed is the EE's quotient.
    sc.op(OP_POKE, P_SCALE, 0)
    sc.op(OP_POKE, P_SLIDING, 0)
    sc.op(OP_SLIDE, 2.0)
    sc.op(OP_AIR, 0.5)
    sc.op(OP_MAXACC)
    sc.op(OP_POKE, P_DV, 0)
    sc.op(OP_SLIDE, 2.0)
    sc.op(OP_AIR, 0.5)
    sc.op(OP_MAXACC)
    sc.op(OP_DUMP)
    sc.op(OP_DEL, 3)
    sc.car_type()

    # -- the crest: the car leaves the belt ---------------------------------
    sc.tag("crest")
    sc.car((0.0, 0.0, 0.0), 0.0, 25.0)
    sc.belt(crest())
    sc.op(OP_TIMER, 0x12345)
    sc.op(OP_JUNK, 9)
    sc.op(OP_NEW)
    sc.op(OP_SETBELT)
    sc.op(OP_DUMP)
    for dt in (0.25, 0.5, 1.0, 2.0):
        sc.op(OP_AIR, f32(dt))
    # Move asks over 0.5 s, a power of two, where (dt x i) x 0.1 and
    # dt x (i x 0.1) round alike; 0.7 tells them apart.
    for i in range(30):
        sc.moves(1.0 / 30.0, 2, every=2)
        sc.op(OP_AIR, 0.5)
        sc.op(OP_AIR, f32(0.7))
    sc.op(OP_DEL, 3)

    # -- small steps: dt 0, 0.0001 and a tick either side, and negative -----
    sc.tag("dt")
    sc.car((0.0, 0.5, 0.0), 0.0, 18.0)
    sc.belt(arc(10, 60.0, 9.0, cy=60.0))
    sc.op(OP_JUNK, 10)
    sc.op(OP_NEW)
    sc.op(OP_SETBELT)
    sc.moves(1.0 / 30.0, 4)
    b = fb(f32(0.0001))
    for d in (Fb(0), Fb(b), Fb(b - 1), Fb(b + 1), Fb(b | 0x80000000),
              Fb((b + 1) | 0x80000000), Fb(0x80000000), f32(1.0 / 60.0),
              f32(0.1)):
        sc.op(OP_MOVE, d)
        sc.op(OP_DUMP)
    sc.op(OP_DEL, 3)

    # -- the wheels: front by number, not by slot ---------------------------
    sc.tag("wheel numbers")
    sc.car_type(numbers=(3, 2, 1, 0))
    sc.op(OP_STEER, 0xffff)
    sc.car((0.0, 0.0, 0.0), 0.0, 22.0)
    sc.belt(arc(12, 50.0, 10.0, cy=50.0))
    sc.op(OP_JUNK, 11)
    sc.op(OP_NEW)
    sc.op(OP_SETBELT)
    sc.moves(1.0 / 30.0, 4)
    sc.op(OP_STEER, 0x8000)
    sc.moves(1.0 / 30.0, 2)
    sc.op(OP_STEER, 0)
    sc.moves(1.0 / 30.0, 1)
    sc.op(OP_DEL, 3)
    sc.car_type(numbers=(1, -5, 2, 7))
    sc.op(OP_STEER, 77)
    sc.op(OP_JUNK, 12)
    sc.op(OP_NEW)
    sc.op(OP_SETBELT)
    sc.moves(1.0 / 30.0, 3)
    sc.op(OP_DEL, 3)
    sc.car_type()
    sc.op(OP_STEER, 1200)

    # -- the skids: effects on and off, the player at 200 m ------------------
    sc.tag("skids")
    sc.car((0.0, 0.0, 0.0), 0.0, 20.0)
    sc.belt(straight())
    sc.op(OP_JUNK, 13)
    sc.op(OP_NEW)
    sc.op(OP_SETBELT)
    for vfx, dist in ((1, 199.0), (1, 200.0), (1, bf(fb(200.0) - 1)),
                      (1, bf(fb(200.0) + 1)), (0, 10.0), (1, 0.0),
                      (5, 50.0), (1, -3.0)):
        sc.set(K_VFX, vfx)
        sc.set(K_DIST, f32(dist))
        sc.op(OP_MOVE, f32(1.0 / 30.0))
    sc.op(OP_DUMP)
    sc.op(OP_DEL, 3)
    standard(sc)

    # -- PutFlatOnTrack moves the car before the velocity is taken ----------
    sc.tag("flat")
    sc.set(K_FLATDZ, 0.75)
    sc.car((0.0, 0.0, 0.0), 0.0, 20.0)
    sc.belt(straight())
    sc.op(OP_JUNK, 14)
    sc.op(OP_NEW)
    sc.op(OP_SETBELT)
    sc.moves(1.0 / 30.0, 3)
    sc.set(K_FLATDZ, 0.0)
    sc.op(OP_DEL, 3)

    # -- short belts: one point, two, none ----------------------------------
    # One point's DriveTarget has no length, and the scale over it is the
    # EE's FLT_MAX: Move then overflows to infinities, which the EE clamps
    # and the host makes NaNs of. The point is given a length.
    for name, pts, length in (
            ("one point", [(5.0, 0.0, 0.0)], 10.0),
            ("two points", [(0.0, 0.0, 0.0), (20.0, 5.0, 1.0)], None),
            ("three points", [(0.0, 0.0, 0.0), (20.0, 5.0, 1.0),
                              (40.0, 0.0, 0.0)], None)):
        sc.tag(name)
        sc.car((1.0, 1.0, 0.0), 10.0, 15.0)
        sc.belt(pts, length)
        sc.op(OP_JUNK, 15)
        sc.op(OP_NEW)
        sc.op(OP_SETBELT)
        sc.op(OP_DUMP)
        sc.op(OP_GRAV)
        sc.moves(1.0 / 30.0, 4, every=2)
        sc.op(OP_GRAV)
        sc.op(OP_DEL, 3)
    # Move with no belt yet sets it first.
    sc.tag("move sets the belt")
    sc.car((1.0, 1.0, 0.0), 0.0, 15.0)
    sc.belt(straight(8))
    sc.op(OP_JUNK, 16)
    sc.op(OP_NEW)
    sc.moves(1.0 / 30.0, 2)
    sc.op(OP_DEL, 3)
    # Twenty points, the spline's most.
    sc.tag("twenty points")
    sc.car((0.0, 0.0, 0.0), 0.0, 30.0)
    sc.belt(walk(rnd, 20))
    sc.op(OP_JUNK, 17)
    sc.op(OP_NEW)
    sc.op(OP_SETBELT)
    sc.op(OP_DUMP)
    sc.moves(1.0 / 30.0, 30, every=5)
    # SetBelt again with fewer: the spline's count and points follow.
    sc.belt(straight(6, 12.0, y=3.0))
    sc.op(OP_SETBELT)
    sc.op(OP_DUMP)
    sc.moves(1.0 / 30.0, 6, every=3)
    sc.op(OP_DEL, 3)

    # -- the cubics poked: the seeks' states and the slide's end rate ------
    sc.tag("cubics")
    sc.car((0.0, 0.0, 0.0), 0.0, 20.0)
    sc.belt(straight())
    sc.op(OP_JUNK, 18)
    sc.op(OP_NEW)
    sc.op(OP_SETBELT)
    sc.op(OP_CUBIC, CU_SX, 4, fb(2.5))
    sc.op(OP_CUBIC, CU_SY, 4, fb(-1.5))
    sc.op(OP_POKE, P_SLIDING, 1)
    sc.op(OP_SLIDE, 0.0)                 # stops: the rate times 1.6
    sc.op(OP_DUMP)
    sc.op(OP_CUBIC, CU_SX, 12, fb(2.5 * 1.6))
    sc.op(OP_CUBIC, CU_SY, 12, fb(f32(-1.5 * 1.6)))
    sc.op(OP_POKE, P_SLIDING, 1)
    sc.op(OP_SLIDE, 0.0)
    sc.op(OP_DUMP)
    sc.op(OP_CUBIC, CU_U, 44, 0)
    sc.op(OP_CUBIC, CU_U, 0, fb(-0.0))
    sc.op(OP_CUBIC, CU_U, 8, fb(0.0))
    sc.op(OP_CUBIC, CU_U, 12, fb(0.0))
    sc.op(OP_CUBIC, CU_U, 4, fb(0.0))
    sc.op(OP_FIND)
    sc.op(OP_DUMP)
    sc.op(OP_CUBIC, CU_AX, 44, 0)
    sc.op(OP_CUBIC, CU_AY, 44, 0)
    sc.moves(1.0 / 30.0, 3)
    for k in range(40):
        sc.op(OP_AVGREC, f32(25.0 if k % 3 else -30.0))
    sc.moves(1.0 / 30.0, 6, every=2)
    sc.op(OP_DEL, 3)

    # -- the destructor: each pointer NULL, and the flags --------------------
    for name, nulls, flags in (("del 0", (), 0), ("del 2", (), 2),
                               ("del avg", (NP_AVG,), 1),
                               ("del spline", (NP_SPLINE,), 3),
                               ("del wheels", (NP_WHEEL0, NP_WHEEL0 + 2), 3),
                               ("del all", (NP_AVG, NP_SPLINE, 2, 3, 4, 5),
                                3)):
        sc.tag(name)
        sc.car((0.0, 0.0, 0.0), 0.0, 20.0)
        sc.op(OP_JUNK, 19)
        sc.op(OP_NEW)
        for k in nulls:
            sc.op(OP_NULLP, k)
        sc.op(OP_DEL, flags)

    # -- random belts --------------------------------------------------------
    for r in range(24):
        sc.tag("random %d" % r)
        n = rnd.randint(4, 20)
        pts = walk(rnd, n, step=rnd.uniform(5.0, 15.0),
                   bend=rnd.uniform(0.05, 0.6), climb=rnd.uniform(0.0, 0.3))
        p0, p1 = pts[0], pts[1]
        hd = math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0]))
        hd += rnd.uniform(-25.0, 25.0)
        off = rnd.uniform(-3.0, 3.0)
        pos = (f32(p0[0] + off * -math.sin(math.radians(hd))
                   + rnd.uniform(-5.0, 5.0)),
               f32(p0[1] + off * math.cos(math.radians(hd))),
               f32(p0[2] + rnd.uniform(-0.5, 0.5)))
        speed = f32(rnd.uniform(0.0, 50.0))
        sc.car(pos, hd, speed, yaw_rate=f32(rnd.uniform(-1.0, 1.0)))
        sc.car_type(radius=f32(rnd.uniform(0.28, 0.4)),
                    mass=f32(rnd.uniform(900.0, 2200.0)),
                    force=(f32(rnd.uniform(0.6, 1.4)),
                           f32(rnd.uniform(0.6, 1.4))),
                    static=(f32(rnd.uniform(0.5, 1.5)),
                            f32(rnd.uniform(0.5, 1.5))),
                    dynamic=(f32(rnd.uniform(0.3, 1.2)),
                             f32(rnd.uniform(0.3, 1.2))),
                    down=(f32(rnd.uniform(0.0, 2.0)),
                          f32(rnd.uniform(0.0, 2.0))))
        sc.wheels([f32(rnd.uniform(-50, 50)) for _ in range(4)],
                  [f32(rnd.uniform(-10, 10)) for _ in range(4)])
        sc.op(OP_STEER, rnd.randrange(0x10000))
        standard(sc, dspeed=f32(rnd.uniform(0.0, 60.0)),
                 dtts=f32(rnd.choice((0.0, rnd.uniform(-1.0, 4.0)))),
                 maxacc=f32(rnd.uniform(-5.0, 15.0)))
        sc.set(K_VFX, rnd.randrange(2))
        sc.set(K_DIST, f32(rnd.uniform(100.0, 300.0)))
        sc.set(K_FLATDZ, f32(rnd.choice((0.0, rnd.uniform(-0.2, 0.2)))))
        sc.op(OP_TIMER, 0)
        sc.op(OP_JUNK, 20 + r)
        sc.op(OP_NEW)
        sc.op(OP_SETBELT)
        sc.op(OP_DUMP)
        frames = rnd.randint(10, 60)
        for i in range(frames):
            sc.op(OP_MOVE, f32(rnd.choice((1.0 / 30.0, 1.0 / 60.0,
                                           rnd.uniform(0.0, 0.1)))))
            if i % 6 == 5:
                sc.op(OP_DUMP)
            if i % 17 == 16:
                sc.op(OP_SETBELT)
        sc.op(OP_DUMP)
        for t in (0.0, f32(rnd.uniform(-1.0, 3.0))):
            sc.op(OP_GP, t)
            sc.op(OP_GD, t)
            sc.op(OP_GDD, t)
        sc.op(OP_GRAV)
        sc.op(OP_DEL, 3)
    sc.car_type()
    standard(sc)
    return sc


# ================================================================ the model

class Model(object):
    def __init__(self, sc):
        self.sc = sc
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        e.stub_bware()
        self.heap = []                  # (addr, span, label)
        self.wheels = []                # addr
        self.vals = {K_DSPEED: 0, K_DTTS: 0, K_MAXACC: 0, K_VFX: 0,
                     K_DIST: 0, K_FLATDZ: 0}
        for base, n in ((CAR, 0x1000), (CTI, 0x1000), (DRV, 0x1000),
                        (AICC, 0x1000), (WORLD, 0x1000), (DVT, 0x1000),
                        (SCR, 0x1000)):
            e.mem[base:base + n] = bytes(n)
        e.put32(CAR + 12, CTI)
        e.put32(CAR + 40, AICC)
        e.put32(CAR + 44, DRV)
        e.put32(DRV + 556, DVT)
        e.put32(DVT + 136 + 4, STUB_GDS)
        e.put32(DVT + 144 + 4, STUB_GTTS)
        e.put32(WVT + 8 + 4, STUB_WDTOR)
        e.put32(GP + WHEEL_POOL_GP, POOL)
        e.put32(GP + WORLD_GP, WORLD)
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
        for base, name in ((BMA, "bm"), (CAR, "car"), (CS, "cs"),
                           (DRV, "drv"), (AICC, "aicc"), (WORLD, "world")):
            if a == base:
                return name
        if CTI <= a < CTI + 0x1000:
            return "cti" if a == CTI else "cti+%d" % (a - CTI)
        for i, p in enumerate(self.wheels):
            if a == p:
                return "w%d" % i
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
            fill = 0 if name.endswith("quickspline.cpp") else 0xcd
            e.mem[p:p + span] = bytes([fill]) * span
            lab = "h%d" % len(self.heap)
            self.heap.append((p, span, lab))
            self.emit("  alloc %s size %d name %s flags %d pool %d"
                      % (lab, size, name, s32(arg(2)), s32(arg(3))))
            return p

        def free(em):
            self.emit("  free %s" % self.label(arg(0)))

        def omalloc(em):
            p = e.alloc(WHEEL_SIZE + SLACK, align=16)
            e.mem[p:p + WHEEL_SIZE + SLACK] = bytes([0xcd]) * (WHEEL_SIZE
                                                              + SLACK)
            self.wheels.append(p)
            self.emit("  omalloc %s -> w%d"
                      % ("pool" if arg(0) == POOL else "?",
                         len(self.wheels) - 1))
            return p

        def wheel_ctor(em):
            w = arg(0)
            self.emit("  wheel %s wi %s ti %s ci %s cs %s"
                      % (self.label(w), self.label(arg(1)),
                         self.label(arg(2)), self.label(arg(3)),
                         self.label(e.reg[8])))
            e.put32(w + 8, WVT)
            e.put32(w + 12, arg(1))
            return w

        def wheel_dtor(em):
            self.emit("  wdtor %s %d" % (self.label(arg(0)), s32(arg(1))))

        def setstate(em):
            self.emit("  setstate %s %s %s %s %s %d %s"
                      % (self.label(arg(0)), self.label(arg(1)),
                         self.label(arg(2)), fx(e.fpr[12]), fx(e.fpr[13]),
                         arg(3) & 0xffff, fx(e.fpr[14])))

        def skids(em):
            self.emit("  skids %s %s" % (self.label(arg(0)), fx(e.fpr[12])))

        def resample(em):
            self.emit("  resample %s %s" % (self.label(arg(0)),
                                            self.label(arg(1))))

        def calc_maxacc(em):
            self.emit("  maxacc %s %s" % (self.label(arg(0)), fx(e.fpr[12])))
            e.fpr[0] = self.vals[K_MAXACC]

        def put_flat(em):
            self.emit("  flat %s" % self.label(arg(0)))
            z = CS + CS_POS + 8
            e.put32(z, fb(f32(bf(self.w(z)) + bf(self.vals[K_FLATDZ]))))

        def geom(em):
            self.emit("  geom %s" % self.label(arg(0)))

        def vfx(em):
            self.emit("  vfx %s -> %d" % (self.label(arg(0)),
                                          s32(self.vals[K_VFX])))
            return self.vals[K_VFX]

        def dist(em):
            p = arg(1)
            self.emit("  dist %s %s %s %s %s -> %s"
                      % (self.label(arg(0)),
                         "pos" if p == CS + CS_POS else self.label(p),
                         fx(self.w(p)), fx(self.w(p + 4)), fx(self.w(p + 8)),
                         fx(self.vals[K_DIST])))
            e.fpr[0] = self.vals[K_DIST]

        def rpm(em):
            self.emit("  rpm %s" % self.label(arg(0)))

        def cm_dtor(em):
            self.emit("  carmover dtor %s %d" % (self.label(arg(0)),
                                                  s32(arg(1))))

        def gds(em):
            self.emit("  gds %s" % self.label(arg(0)))
            e.fpr[0] = self.vals[K_DSPEED]

        def gtts(em):
            self.emit("  gtts %s" % self.label(arg(0)))
            e.fpr[0] = self.vals[K_DTTS]

        e.stub(BMALLOC, malloc)
        e.stub(BDELETE, free)
        e.stub(BFREE, free)
        e.stub(BOMALLOC, omalloc)
        e.stub(WHEEL_CTOR, wheel_ctor)
        e.stub(STUB_WDTOR, wheel_dtor)
        e.stub(WHEEL_SETSTATE, setstate)
        e.stub(WHEEL_SKIDS, skids)
        e.stub(RESAMPLE, resample)
        e.stub(CALC_MAXACC, calc_maxacc)
        e.stub(PUT_FLAT, put_flat)
        e.stub(GEOM_POS, geom)
        e.stub(VFX, vfx)
        e.stub(DIST, dist)
        e.stub(FAKE_RPM, rpm)
        e.stub(CARMOVER_DTOR, cm_dtor)
        e.stub(STUB_GDS, gds)
        e.stub(STUB_GTTS, gtts)

    # ---- the dump --------------------------------------------------------

    def words(self, a, n):
        return " ".join(fx(self.w(a + 4 * k)) for k in range(n))

    def cubic(self, name, a):
        e = self.e
        self.emit("%s %s st %d fl %d" % (name, self.words(a, 11),
                                         self.s16(a + 44), self.s16(a + 46)))

    def dump(self):
        e, w = self.e, self.w
        m = BMA
        self.emit("bm vt %08x car %s t %s s %s v %s dv %s ddv %s sl %d"
                  % (w(m + 4), self.label(w(m + 8)), fx(w(m + 12)),
                     fx(w(m + 16)), fx(w(m + 28)), fx(w(m + 32)),
                     fx(w(m + 36)), s32(w(m + 52))))
        self.emit("bm spl %s u %s ang %s sld %s avg %s w %s"
                  % (self.label(w(m + 20)), self.label(w(m + 24)),
                     self.label(w(m + 40)), self.label(w(m + 44)),
                     self.label(w(m + 48)),
                     " ".join(self.label(w(m + 56 + 4 * i))
                              for i in range(4))))
        self.cubic("u", w(m + 24))
        self.cubic("ax", w(m + 40))
        self.cubic("ay", w(m + 40) + 48)
        self.cubic("sx", w(m + 44))
        self.cubic("sy", w(m + 44) + 48)
        a = w(m + 48)
        self.emit("avg %d %d %d %s %s" % (e.u8(a), e.u8(a + 1), e.u8(a + 2),
                                          fx(w(a + 4)), fx(w(a + 8))))
        s = w(m + 20)
        n = e.u16(s + 26)
        self.emit("spl n %d max %d dirty %d minc %d maxp %s minp %s len %s"
                  % (n, e.u16(s + 24), self.s8(s + 20), self.s8(s + 22),
                     fx(w(s + 8)), fx(w(s + 12)), fx(w(s + 16))))
        cp = w(s + 32)
        for i in range(-1, n + 2):
            self.emit("  cp%d %s" % (i, self.words(cp + 16 * i, 4)))
        for name, off in (("slide", SLIDE_GRAPH_GP),
                          ("sliding", SLIDING_GRAPH_GP)):
            g = GP + off
            self.emit("graph %s %d %s" % (name, s32(w(g + 4)),
                                          self.words(w(g), 8)))
        c = CS
        self.emit("cs pos %s vel %s av %s ang %d fs %s vm %s mv %d"
                  % (self.words(c + CS_POS, 4), self.words(c + CS_VEL, 4),
                     self.words(c + CS_AV, 3), e.u16(c + CS_ANGLE),
                     fx(w(c + CS_FS)), fx(w(c + CS_VM)), s32(w(c + CS_MV))))
        self.emit("cs slip %s tu %s" % (self.words(c + CS_WSLIP, 8),
                                        self.words(c + CS_WTU, 4)))
        self.emit("timer %s" % fx(w(AICC + 568)))
        for i in range(4):
            p = w(m + 56 + 4 * i)
            if p == 0:
                continue
            self.emit("w%d slip %s %s sl %d cur %s"
                      % (i, fx(w(p + 256)), fx(w(p + 260)), e.u8(p + 340),
                         fx(w(p + 352))))

    # ---- the run ---------------------------------------------------------

    def vcall(self, slot, *args):
        e = self.e
        vt = self.w(BMA + 4)
        delta = self.s16(vt + slot)
        fn = self.w(vt + slot + 4)
        return e.call(fn, (BMA + delta) & M32, *args)

    def vec(self, name, a):
        self.emit("  %s %s" % (name, self.words(a, 4)))

    def run(self):
        e, w = self.e, self.w
        tags = self.sc.tags
        for o in self.sc.ops:
            code, a = o[0], o[1:]
            if code == OP_TAG:
                self.emit("[%s]" % tags[a[0]])
            elif code == OP_JUNK:
                e.mem[BMA:BMA + BM_SIZE] = bytes(
                    [(0xa1 + a[0] + 7 * k) & 0xff for k in range(BM_SIZE)])
            elif code == OP_CS:
                off, kind = CSF[a[0]]
                if kind == "h":
                    e.write(CS + off, struct.pack("<H", a[1] & 0xffff))
                else:
                    e.put32(CS + off, a[1])
            elif code == OP_CTI:
                e.put32(CTI + a[0], a[1])
            elif code == OP_DTN:
                e.write(DRV, bytes([a[0] & 0xff]))
            elif code == OP_DTP:
                p = DRV + 16 + 16 * a[0]
                e.put32(p, a[1])
                e.put32(p + 4, a[2])
                e.put32(p + 8, a[3])
                # A w that SetBelt must not copy.
                e.put32(p + 12, 0x40400000 + a[0])
            elif code == OP_DTL:
                e.put32(DRV + 512, a[0])
            elif code == OP_STEER:
                e.write(DRV + 528, struct.pack("<H", a[0] & 0xffff))
            elif code == OP_SET:
                self.vals[a[0]] = a[1] & M32
            elif code == OP_TIMER:
                e.put32(AICC + 568, a[0])
            elif code == OP_NEW:
                self.emit("new")
                r = e.call(F["ctor"], BMA, CAR)
                self.emit("new -> %s" % self.label(r))
            elif code == OP_DEL:
                self.emit("del %d" % a[0])
                self.vcall(8, a[0])
            elif code == OP_SETBELT:
                self.emit("setbelt")
                e.call(F["setbelt"], BMA)
            elif code == OP_FIND:
                self.emit("find")
                e.call(F["find"], BMA)
            elif code == OP_MOVE:
                self.emit("move %s" % fx(a[0]))
                e.fpr[12] = a[0]
                self.vcall(16)
                self.emit("move -> %s" % fx(e.fpr[0]))
            elif code == OP_GRAV:
                e.call(F["grav"], BMA)
                self.emit("grav -> %s" % fx(e.fpr[0]))
            elif code == OP_MAXACC:
                e.call(F["maxacc"], BMA)
                self.emit("maxacc -> %s" % fx(e.fpr[0]))
            elif code == OP_SLIDE:
                self.emit("slide %s" % fx(a[0]))
                e.fpr[12] = a[0]
                e.call(F["slide"], BMA)
                self.emit("slide -> %s" % fx(e.fpr[0]))
            elif code == OP_AIR:
                e.fpr[12] = a[0]
                e.call(F["air"], BMA)
                self.emit("air %s -> %s" % (fx(a[0]), fx(e.fpr[0])))
            elif code in (OP_GP, OP_GD, OP_GDD):
                name = {OP_GP: "gp", OP_GD: "gd", OP_GDD: "gdd"}[code]
                e.mem[SCR:SCR + 16] = bytes([0x5a]) * 16
                e.fpr[12] = a[0]
                r = e.call(F[name], BMA, SCR)
                self.emit("%s %s -> %s %s" % (name, fx(a[0]),
                                              "out" if r == SCR else "?",
                                              self.words(SCR, 4)))
            elif code == OP_DOT:
                pos, va, vb = SCR + 0x100, SCR + 0x200, SCR + 0x300
                for k in range(4):
                    e.put32(pos + 4 * k, a[k])
                e.mem[va:va + 16] = bytes([0x5a]) * 16
                e.mem[vb:vb + 16] = bytes([0x5a]) * 16
                e.fpr[12] = a[4]
                e.call(F["dot"], BMA, pos, va, vb)
                self.emit("dot %s -> %s a %s b %s"
                          % (fx(a[4]), fx(e.fpr[0]), self.words(va, 4),
                             self.words(vb, 4)))
            elif code == OP_POKE:
                e.put32(BMA + a[0], a[1])
            elif code == OP_CPW:
                e.put32(w(w(BMA + 20) + 32) + 16 * a[0] + 12, a[1])
            elif code == OP_CUBIC:
                c = {CU_U: w(BMA + 24), CU_AX: w(BMA + 40),
                     CU_AY: w(BMA + 40) + 48, CU_SX: w(BMA + 44),
                     CU_SY: w(BMA + 44) + 48}[a[0]]
                if a[1] >= 44:
                    e.write(c + a[1], struct.pack("<H", a[2] & 0xffff))
                else:
                    e.put32(c + a[1], a[2])
            elif code == OP_AVGREC:
                e.fpr[12] = a[0]
                e.call(0x0018fcb8, w(BMA + 48))
            elif code == OP_DDVAL:
                c = {CU_U: w(BMA + 24), CU_AX: w(BMA + 40),
                     CU_AY: w(BMA + 40) + 48, CU_SX: w(BMA + 44),
                     CU_SY: w(BMA + 44) + 48}[a[0]]
                e.fpr[12] = a[1]
                e.call(0x001da830, c)
                self.emit("ddval %d %s -> %s" % (a[0], fx(a[1]),
                                                 fx(e.fpr[0])))
            elif code == OP_NULLP:
                e.put32(BMA + (48, 20, 56, 60, 64, 68)[a[0]], 0)
            elif code == OP_DUMP:
                self.dump()
            else:
                raise ValueError("op %d" % code)
        return self.out


def model(sc):
    return Model(sc).run()


# ================================================================ the build


def build_harness(tmp, name="beltmover_test"):
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
    # -- the tuning ---------------------------------------------------------
    ("k-spin", BMC, "BM_SPIN_SCALE         0.4f", "BM_SPIN_SCALE         0.5f"),
    ("k-slide-dur", BMC, "BM_SLIDE_DURATION     0.3f",
     "BM_SLIDE_DURATION     0.35f"),
    ("k-tol", BMC, "BM_PARAM_TOLERANCE    0.005f",
     "BM_PARAM_TOLERANCE    0.05f"),
    ("k-fraction", BMC, "BM_SPEED_FRACTION     0.899f",
     "BM_SPEED_FRACTION     0.9f"),
    ("k-ang-dur", BMC, "BM_ANGLE_DURATION     0.4f",
     "BM_ANGLE_DURATION     0.45f"),
    ("k-knee-low", BMC, "BM_KNEE_LOW           0.9f",
     "BM_KNEE_LOW           0.85f"),
    ("k-knee-high", BMC, "BM_KNEE_HIGH          1.1f",
     "BM_KNEE_HIGH          1.2f"),
    ("k-end-dur", BMC, "BM_SLIDE_END_DURATION 0.3f",
     "BM_SLIDE_END_DURATION 0.25f"),
    ("k-end-rate", BMC, "BM_SLIDE_END_RATE     1.6f",
     "BM_SLIDE_END_RATE     1.5f"),
    ("k-air-step", BMC, "BM_AIR_STEP           0.1f",
     "BM_AIR_STEP           0.11f"),
    ("k-air-scale", BMC, "BM_AIR_SCALE          0.1f",
     "BM_AIR_SCALE          0.2f"),
    ("k-air-threshold", BMC, "BM_AIR_THRESHOLD      0.002f",
     "BM_AIR_THRESHOLD      0.02f"),
    ("k-off-ticks", BMC, "BM_OFF_BELT_TICKS     2400.5f",
     "BM_OFF_BELT_TICKS     2000.5f"),
    ("k-look-ahead", BMC, "BM_SLIDE_LOOK_AHEAD   0.3f",
     "BM_SLIDE_LOOK_AHEAD   0.35f"),
    ("k-bam", BMC, "9.587379463482648e-05f", "9.5873802e-05f"),
    ("k-min-dt", BMC, "BM_MIN_DT             0.0001f",
     "BM_MIN_DT             0.0002f"),
    ("k-gravity", BMC, "BM_GRAVITY            9.8f",
     "BM_GRAVITY            9.81f"),
    ("g-slide-p0", BMC, "{ 0.0f, 0.0f }, { 18.0f, 0.1f }",
     "{ 0.0f, 0.05f }, { 18.0f, 0.1f }"),
    ("g-slide-p1", BMC, "{ 18.0f, 0.1f }", "{ 18.0f, 0.15f }"),
    ("g-slide-p2", BMC, "{ 22.0f, 0.4f }", "{ 22.0f, 0.45f }"),
    ("g-slide-p3", BMC, "{ 30.0f, 0.7f }", "{ 30.0f, 0.75f }"),
    ("g-sliding-p1", BMC, "{ 14.5f, 0.4f }", "{ 14.5f, 0.45f }"),
    ("g-sliding-p2", BMC, "{ 16.5f, 0.6f }", "{ 16.5f, 0.65f }"),
    ("g-sliding-p3", BMC, "{ 30.0f, 1.0f }", "{ 30.0f, 0.95f }"),
    ("g-slide-n", BMC, "BeltSlideGraph   = { BeltSlidePoints, 4 }",
     "BeltSlideGraph   = { BeltSlidePoints, 3 }"),
    ("g-sliding-n", BMC, "BeltSlidingGraph = { BeltSlidingPoints, 4 }",
     "BeltSlidingGraph = { BeltSlidingPoints, 3 }"),

    # -- the VU idioms ------------------------------------------------------
    ("dot3-order", BMC,
     "    return (a->x * b->x + a->y * b->y) + a->z * b->z;",
     "    return a->x * b->x + (a->y * b->y + a->z * b->z);"),
    ("cross-x", BMC, "    float x = a->y * b->z - b->y * a->z;",
     "    float x = b->y * a->z - a->y * b->z;"),
    ("cross-y", BMC, "    float y = a->z * b->x - b->z * a->x;",
     "    float y = b->z * a->x - a->z * b->x;"),
    ("cross-z", BMC, "    float z = a->x * b->y - b->x * a->y;",
     "    float z = b->x * a->y - a->x * b->y;"),
    ("cross-w", BMC, "    o->pad = a->pad;", "    o->pad = b->pad;"),
    ("norm-w", BMC, "    v->pad = v->pad * inv;\n", ""),
    ("norm-ee", BMC, "0.0f + ee_div(1.0f, sqrtf(dot3(v, v)))",
     "1.0f / sqrtf(dot3(v, v))"),
    ("scale-w", BMC, "    o->pad = v->pad * k;", "    o->pad = v->pad;"),
    ("point-w", BMC, "    out->pad = q.w;", "    out->pad = 0.0f;"),
    ("cset-val", BMC,
     "    c->val = f;\n    if (f != c->valDesired)\n        c->state = 2;",
     "    c->val = f;"),
    ("cset-dval", BMC,
     "    c->dval = f;\n    if (f != c->dvalDesired)\n        c->state = 2;",
     "    c->dval = f;"),
    ("cset-dval-cmp", BMC, "    if (f != c->dvalDesired)",
     "    if (f != c->dval)"),
    ("cset-desired", BMC,
     "    c->valDesired = f;\n    if (f != c->val)\n        c->state = 2;",
     "    c->valDesired = f;"),
    ("cinit-val", BMC, "    c->val = 0.0f;\n    c->dval = 0.0f;\n",
     "    c->dval = 0.0f;\n"),
    ("cinit-desired", BMC,
     "    c->valDesired = 0.0f;\n    c->dvalDesired = 0.0f;\n",
     "    c->valDesired = 0.0f;\n"),
    ("cinit-flags", BMC, "    c->flags = 1;", "    c->flags = 0;"),
    ("cinit-duration", BMC, "    c->duration = 1.0f;\n    c->arrivalThreshold",
     "    c->duration = 2.0f;\n    c->arrivalThreshold"),
    ("cinit-threshold", BMC, "    c->arrivalThreshold = 1.0f;\n    c->state = 0;",
     "    c->arrivalThreshold = 0.5f;\n    c->state = 0;"),
    ("cinit-state", BMC, "    c->arrivalThreshold = 1.0f;\n    c->state = 0;",
     "    c->arrivalThreshold = 1.0f;\n    c->state = 1;"),
    ("tts-slot", BMC, "#define BM_VT_GET_DESIRED_TIME_TO_SPEED 144",
     "#define BM_VT_GET_DESIRED_TIME_TO_SPEED 136"),

    # -- the constructor ----------------------------------------------------
    ("init-car", BMC, "    m->pCar = car;\n", ""),
    ("init-ddv", BMC, "    m->ddv = 0.0f;\n    m->dv = 0.0f;\n",
     "    m->dv = 0.0f;\n"),
    ("init-time", BMC, "    m->fScale = 0.0f;\n    m->fTime = 0.0f;\n",
     "    m->fScale = 0.0f;\n"),
    ("init-sliding", BMC, "    m->bSliding = 0;\n", ""),
    ("init-vptr", BMC,
     "    m->bSliding = 0;\n    m->Mover._vtable = BELTMOVER_VTABLE;",
     "    m->bSliding = 0;"),
    ("init-avg-n", BMC, "CAR_MEMORY_POOL), 30);", "CAR_MEMORY_POOL), 20);"),
    ("init-avg-line", BMC, "BELTMOVER_FILE, 124,", "BELTMOVER_FILE, 125,"),
    ("init-avg-pool", BMC, "CAR_MEMORY_POOL), 30);", "0), 30);"),
    ("init-spl-line", BMC, "BELTMOVER_FILE, 126,", "BELTMOVER_FILE, 125,"),
    ("init-spl-ept", BMC, "        QUICKSPLINE_EXTRAPOLATED, QUICKSPLINE_OVERHAUSER, 20);",
     "        QUICKSPLINE_LOOP, QUICKSPLINE_OVERHAUSER, 20);"),
    ("init-spl-n", BMC, "QUICKSPLINE_OVERHAUSER, 20);",
     "QUICKSPLINE_OVERHAUSER, 21);"),
    ("init-u-line", BMC, "BELTMOVER_FILE, 127,", "BELTMOVER_FILE, 128,"),
    ("init-ang-line", BMC, "BELTMOVER_FILE, 128,", "BELTMOVER_FILE, 129,"),
    ("init-slide-line", BMC, "BELTMOVER_FILE, 129,", "BELTMOVER_FILE, 128,"),
    ("init-ang-y", BMC,
     "    cubic_init(&c2->x);\n    cubic_init(&c2->y);\n    m->pCubicAng = c2;",
     "    cubic_init(&c2->x);\n    m->pCubicAng = c2;"),
    ("init-slide-x", BMC,
     "    cubic_init(&c2->x);\n    cubic_init(&c2->y);\n    m->pCubicSlide = c2;",
     "    cubic_init(&c2->y);\n    m->pCubicSlide = c2;"),
    ("init-lat", BMC, "    lat = s * (cs->AngularVelocity.z * BM_SPIN_SCALE);",
     "    lat = (s * cs->AngularVelocity.z) * BM_SPIN_SCALE;"),
    ("init-lat-z", BMC, "    lat = s * (cs->AngularVelocity.z * BM_SPIN_SCALE);",
     "    lat = s * (cs->AngularVelocity.y * BM_SPIN_SCALE);"),
    ("init-quarter", BMC, "    b = (uint16_t)(cs->Angle + 16384);",
     "    b = (uint16_t)(cs->Angle - 16384);"),
    ("init-speed", BMC, "    s = cs->VelocityMagnitude;",
     "    s = cs->ForwardSpeed;"),
    ("init-val-x", BMC, "    val.x = s * bCosBam(a);", "    val.x = s * bSinBam(a);"),
    ("init-val-y", BMC, "    val.y = s * bSinBam(a);", "    val.y = s * bSinBam(b);"),
    ("init-dval-x", BMC, "    dval.x = lat * bCosBam(b);",
     "    dval.x = lat * bCosBam(a);"),
    ("init-dval-y", BMC, "    dval.y = lat * bSinBam(b);",
     "    dval.y = s * bSinBam(b);"),
    ("init-setval", BMC, "    bspline2d_set_val(m->pCubicAng, &val);\n", ""),
    ("init-setdval", BMC, "    bspline2d_set_dval(m->pCubicAng, &dval);\n", ""),
    ("init-slide-dur-y", BMC,
     "    m->pCubicSlide->y.duration = BM_SLIDE_DURATION;\n", ""),
    ("init-slide-dur-x", BMC,
     "    m->pCubicSlide->x.duration = BM_SLIDE_DURATION;\n", ""),
    ("init-wheel-info", BMC, "wheel_init(wheel_new(), &cti->Wheels[i],",
     "wheel_init(wheel_new(), &cti->Wheels[3 - i],"),
    ("init-wheel-tire", BMC, "&cti->Tires[i / 2]", "&cti->Tires[i % 2]"),
    ("init-wheel-ci", BMC, "&cti->Control,\n", "(const ControlInfo *)&cti->Aero,\n"),
    ("init-wheel-n", BMC,
     "    for (i = 0; i < 4; i++)\n        m->pWheels[i] = wheel_init",
     "    for (i = 0; i < 3; i++)\n        m->pWheels[i] = wheel_init"),
    ("init-return", BMC, "    beltmover_clear_calculated_variables(m);\n    return m;",
     "    beltmover_clear_calculated_variables(m);\n    return NULL;"),

    # -- the destructor -----------------------------------------------------
    ("del-vptr", BMC,
     "    m->Mover._vtable = BELTMOVER_VTABLE;\n    if (m->pAvgAccel != NULL)",
     "    if (m->pAvgAccel != NULL)"),
    ("del-avg-null", BMC, "    if (m->pAvgAccel != NULL)\n", "    if (1)\n"),
    ("del-avg-flags", BMC, "average_destroy(m->pAvgAccel, 3);",
     "average_destroy(m->pAvgAccel, 2);"),
    ("del-spl-null", BMC, "    if (m->pSpline != NULL)\n", "    if (1)\n"),
    ("del-spl-flags", BMC, "quickspline_destroy(m->pSpline, 3);",
     "quickspline_destroy(m->pSpline, 2);"),
    ("del-order", BMC,
     "    bFree(m->pCubicAng);\n    bFree(m->pCubicSlide);",
     "    bFree(m->pCubicSlide);\n    bFree(m->pCubicAng);"),
    ("del-u", BMC, "    bFree(m->pCubicU);\n", ""),
    ("del-wheel-null", BMC, "        if (w != NULL) {", "        if (1) {"),
    ("del-wheel-flags", BMC, "((PhysicsDtorFn)e->fn)(vt_this(w, e), 3);",
     "((PhysicsDtorFn)e->fn)(vt_this(w, e), 1);"),
    ("del-wheel-n", BMC,
     "    for (i = 0; i < 4; i++) {\n        Wheel *w = m->pWheels[i];\n        if (w != NULL) {",
     "    for (i = 1; i < 4; i++) {\n        Wheel *w = m->pWheels[i];\n        if (w != NULL) {"),
    ("del-flags", BMC, "    carmover_destroy(&m->Mover, flags);",
     "    carmover_destroy(&m->Mover, 1);"),

    # -- Dot, gravity, the most acceleration -------------------------------
    ("dot-basis", BMC, "    spline_point(m->pSpline, b, t, 1);",
     "    spline_point(m->pSpline, b, t, 0);"),
    ("dot-sub", BMC, "    a->x = a->x - pos->x;", "    a->x = pos->x - a->x;"),
    ("dot-w", BMC, "    a->pad = a->pad - pos->pad;\n", ""),
    ("dot-ret", BMC, "    return dot3(a, b);", "    return dot3(a, a);"),
    ("grav-empty", BMC, "    if (m->pSpline->NumControlPoints == 0)\n        return 0.0f;\n    spline_point",
     "    if (m->pSpline->NumControlPoints < 2)\n        return 0.0f;\n    spline_point"),
    ("grav-v", BMC, "    spline_point(m->pSpline, &t, m->v, 1);",
     "    spline_point(m->pSpline, &t, m->fTime, 1);"),
    ("grav-norm", BMC, "    normalize4(&t);\n    return -BM_GRAVITY * t.z;",
     "    return -BM_GRAVITY * t.z;"),
    ("grav-sign", BMC, "    return -BM_GRAVITY * t.z;",
     "    return BM_GRAVITY * t.z;"),
    ("maxacc-div", BMC,
     "    return ai_calculate_max_acceleration(m->pCar, ee_div(m->dv, m->fScale));",
     "    return ai_calculate_max_acceleration(m->pCar, m->dv / m->fScale);"),
    ("maxacc-arg", BMC,
     "    return ai_calculate_max_acceleration(m->pCar, ee_div(m->dv, m->fScale));",
     "    return ai_calculate_max_acceleration(m->pCar, m->dv);"),

    # -- FindCoordinates ----------------------------------------------------
    ("fc-time", BMC, "    m->fTime = 0.0f;\n    m->fScale = ee_div(",
     "    m->fScale = ee_div("),
    ("fc-scale", BMC, "ee_div((float)m->pSpline->NumControlPoints,\n                       drv->MyDriveTarget.Length)",
     "ee_div((float)(m->pSpline->NumControlPoints - 1),\n                       drv->MyDriveTarget.Length)"),
    ("fc-scale-div", BMC, "ee_div((float)m->pSpline->NumControlPoints,\n                       drv->MyDriveTarget.Length)",
     "((float)m->pSpline->NumControlPoints /\n                       drv->MyDriveTarget.Length)"),
    ("fc-from", BMC, "                                                    &m->pCar->State.Position,\n                                                    0);",
     "                                                    &m->pCar->State.Position,\n                                                    1);"),
    ("fc-param-start", BMC, "(float)i, BM_PARAM_TOLERANCE);",
     "(float)(i + 1), BM_PARAM_TOLERANCE);"),
    ("fc-v", BMC, "    m->v = t;\n", "    m->v = (float)i;\n"),
    ("fc-norm", BMC, "    m->v = t;\n    normalize4(&b);\n", "    m->v = t;\n"),
    ("fc-dv", BMC, "    m->dv = m->fScale * m->pCar->State.VelocityMagnitude;",
     "    m->dv = m->fScale * m->pCar->State.ForwardSpeed;"),
    ("fc-f", BMC, "        * BM_SPEED_FRACTION - m->dv;",
     "        * BM_SPEED_FRACTION;"),
    ("fc-f-order", BMC,
     "    f = (m->fScale * driver_float(drv, CARDRIVER_VT_GET_DESIRED_SPEED))\n        * BM_SPEED_FRACTION - m->dv;",
     "    f = m->fScale * (driver_float(drv, CARDRIVER_VT_GET_DESIRED_SPEED)\n        * BM_SPEED_FRACTION) - m->dv;"),
    ("fc-tts-le", BMC,
     "    if (0.0f < driver_float(drv, BM_VT_GET_DESIRED_TIME_TO_SPEED))",
     "    if (0.0f <= driver_float(drv, BM_VT_GET_DESIRED_TIME_TO_SPEED))"),
    ("fc-tts-once", BMC,
     "    if (0.0f < driver_float(drv, BM_VT_GET_DESIRED_TIME_TO_SPEED))\n        m->ddv = f / driver_float(drv, BM_VT_GET_DESIRED_TIME_TO_SPEED);",
     "    mx = driver_float(drv, BM_VT_GET_DESIRED_TIME_TO_SPEED);\n    if (0.0f < mx)\n        m->ddv = f / mx;"),
    ("fc-half", BMC, "        m->ddv = f / 0.5f;", "        m->ddv = f * 0.5f;"),
    ("fc-max-le", BMC, "    if (mx < m->ddv) {", "    if (mx <= m->ddv) {"),
    ("fc-max-store", BMC, "        m->ddv = mx;\n    } else {", "    } else {"),
    ("fc-max-scale", BMC, "    mx = m->fScale * beltmover_get_maximum_acceleration(m);",
     "    mx = beltmover_get_maximum_acceleration(m);"),
    ("fc-floor", BMC, "        mx = m->fScale * -20.0f;",
     "        mx = m->fScale * -10.0f;"),
    ("fc-floor-cmp", BMC, "        if (m->ddv < mx)\n            m->ddv = mx;",
     "        if (m->ddv > mx)\n            m->ddv = mx;"),
    ("fc-floor-always", BMC,
     "        m->ddv = mx;\n    } else {\n        mx = m->fScale * -20.0f;",
     "        m->ddv = mx;\n    }\n    {\n        mx = m->fScale * -20.0f;"),
    ("fc-up", BMC, "    up.z = 1.0f;\n    up.pad = 0.0f;\n    cross3(&side, &b, &up);",
     "    up.z = -1.0f;\n    up.pad = 0.0f;\n    cross3(&side, &b, &up);"),
    ("fc-side", BMC, "    cross3(&side, &b, &up);", "    cross3(&side, &up, &b);"),
    ("fc-da", BMC, "    da = dot3(&a, &side);", "    da = dot3(&b, &side);"),
    ("fc-dvel", BMC, "    dvel = dot3(&m->pCar->State.Velocity, &side);",
     "    dvel = dot3(&m->pCar->State.Position, &side);"),
    ("fc-val", BMC, "    cubic_set_val(m->pCubicU, -da);",
     "    cubic_set_val(m->pCubicU, da);"),
    ("fc-dval", BMC, "    cubic_set_dval(m->pCubicU, dvel * 0.5f);",
     "    cubic_set_dval(m->pCubicU, dvel);"),
    ("fc-udur", BMC, "    m->pCubicU->duration = 0.5f;",
     "    m->pCubicU->duration = 1.0f;"),
    ("fc-angdur-y", BMC, "    m->pCubicAng->y.duration = BM_ANGLE_DURATION;\n", ""),
    ("fc-angdur-x", BMC, "    m->pCubicAng->x.duration = BM_ANGLE_DURATION;\n", ""),

    # -- SetBelt ------------------------------------------------------------
    ("sb-flags", BMC, "    m->pCubicU->flags = 0;", "    m->pCubicU->flags = 1;"),
    ("sb-resample", BMC, "    drivetarget_resample(dt, m->pCar);\n", ""),
    ("sb-count", BMC,
     "    quickspline_set_num_control_points(m->pSpline, dt->NumPoints);",
     "    quickspline_set_num_control_points(m->pSpline, dt->NumPoints + 1);"),
    ("sb-points", BMC, "    for (i = 0; i < dt->NumPoints; i++) {",
     "    for (i = 1; i < dt->NumPoints; i++) {"),
    ("sb-y", BMC, "        cp->y = dt->Points[i].y;", "        cp->y = dt->Points[i].x;"),
    ("sb-w", BMC, "        cp->w = 0.0f;", "        cp->w = dt->Points[i].pad;"),
    ("sb-dirty", BMC, "        s->ControlPointsDirty = 1;\n", ""),
    ("sb-find", BMC, "    beltmover_find_coordinates(m);\n}", "}"),

    # -- SlideCoef ----------------------------------------------------------
    ("sc-sign", BMC, "    sign = ee_div(accel, mag);",
     "    sign = accel < 0.0f ? -1.0f : 1.0f;"),
    ("sc-sign-div", BMC, "    sign = ee_div(accel, mag);",
     "    sign = accel / mag;"),
    ("sc-need", BMC,
     "    need = (cti->Body.Mass * mag)\n           * ((rear->ForceScale + front->ForceScale) * 0.5f);",
     "    need = cti->Body.Mass * (mag\n           * ((rear->ForceScale + front->ForceScale) * 0.5f));"),
    ("sc-need-tire", BMC, "((rear->ForceScale + front->ForceScale) * 0.5f)",
     "((front->ForceScale + front->ForceScale) * 0.5f)"),
    ("sc-down", BMC,
     "    down = ee_div(m->dv, m->fScale)\n           * ((cti->Aero.FrontDownforce + cti->Aero.RearDownforce) * 0.5f);",
     "    down = ee_div(m->dv, m->fScale)\n           * ((cti->Aero.FrontDownforce + cti->Aero.FrontDownforce) * 0.5f);"),
    ("sc-down-speed", BMC,
     "    down = ee_div(m->dv, m->fScale)\n",
     "    down = m->dv\n"),
    ("sc-grip-dyn", BMC,
     "        grip = (rear->DynamicFrictionCoefficient\n                + front->DynamicFrictionCoefficient) * 0.5f;",
     "        grip = (rear->StaticFrictionCoefficient\n                + front->StaticFrictionCoefficient) * 0.5f;"),
    ("sc-grip-static", BMC,
     "        grip = (rear->StaticFrictionCoefficient\n                + front->StaticFrictionCoefficient) * 0.5f;",
     "        grip = (rear->StaticFrictionCoefficient\n                + rear->StaticFrictionCoefficient) * 0.5f;"),
    ("sc-graph", BMC, "    g = m->bSliding ? &BeltSlidingGraph : &BeltSlideGraph;",
     "    g = m->bSliding ? &BeltSlideGraph : &BeltSlidingGraph;"),
    ("sc-hold", BMC, "    hold = (down + BM_GRAVITY * cti->Body.Mass) * grip;",
     "    hold = down + (BM_GRAVITY * cti->Body.Mass) * grip;"),
    ("sc-p1", BMC, "    p[1].x = hold * BM_KNEE_LOW;", "    p[1].x = hold;"),
    ("sc-p2", BMC, "    p[2].x = hold * BM_KNEE_HIGH;", "    p[2].x = hold * BM_KNEE_LOW;"),
    ("sc-p3", BMC, "    p[3].x = hold * 1.5f;", "    p[3].x = hold * 2.0f;"),
    ("sc-slide-le", BMC, "    sliding = (hold < need);", "    sliding = (hold <= need);"),
    ("sc-start-y", BMC, "            m->pCubicSlide->y.duration = 1.0f;\n", ""),
    ("sc-start-x", BMC, "            m->pCubicSlide->x.duration = 1.0f;",
     "            m->pCubicSlide->x.duration = 0.5f;"),
    ("sc-end-y", BMC, "            m->pCubicSlide->y.duration = BM_SLIDE_END_DURATION;\n", ""),
    ("sc-end-x", BMC, "            m->pCubicSlide->x.duration = BM_SLIDE_END_DURATION;\n", ""),
    ("sc-end-rate-x", BMC, "            d.x = d.x * BM_SLIDE_END_RATE;\n", ""),
    ("sc-end-rate-y", BMC, "            d.y = d.y * BM_SLIDE_END_RATE;\n", ""),
    ("sc-end-set", BMC, "            bspline2d_set_dval(m->pCubicSlide, &d);\n", ""),
    ("sc-store", BMC, "        m->bSliding = sliding;\n", ""),
    ("sc-ret", BMC, "    return sign * graph_get_value(g, need);",
     "    return graph_get_value(g, need);"),
    ("sc-ret-x", BMC, "    return sign * graph_get_value(g, need);",
     "    return sign * graph_get_value(g, hold);"),

    # -- AverageAir ---------------------------------------------------------
    ("air-g", BMC, "    g = g / cti->Body.Mass + BM_GRAVITY;", "    g = BM_GRAVITY;"),
    ("air-mass", BMC, "    g = g / cti->Body.Mass + BM_GRAVITY;",
     "    g = g * cti->Body.Mass + BM_GRAVITY;"),
    ("air-down", BMC,
     "    g = ee_div(m->dv, m->fScale)\n        * ((cti->Aero.FrontDownforce + cti->Aero.RearDownforce) * 0.5f);",
     "    g = ee_div(m->dv, m->fScale)\n        * ((cti->Aero.RearDownforce + cti->Aero.RearDownforce) * 0.5f);"),
    ("air-start", BMC, "    beltmover_get_point(m, &p, m->fTime);\n    beltmover_get_derivative(m, &d, m->fTime);",
     "    beltmover_get_point(m, &p, m->fTime);\n    beltmover_get_derivative(m, &d, 0.0f);"),
    ("air-steps", BMC, "    for (i = 1; i < 10; i++) {", "    for (i = 1; i < 9; i++) {"),
    ("air-s", BMC, "        float s = (dt * (float)i) * BM_AIR_STEP;",
     "        float s = dt * ((float)i * BM_AIR_STEP);"),
    ("air-tau", BMC, "        float tau = s - last;", "        float tau = s;"),
    ("air-z", BMC, "        float z = tau * (tau * ng + dz) + pz;",
     "        float z = tau * (tau * ng * 0.5f + dz) + pz;"),
    ("air-h-le", BMC, "        if (0.0f < h) {", "        if (0.0f <= h) {"),
    ("air-sum", BMC, "            sum = sum + h;", "            sum = h;"),
    ("air-d", BMC, "            beltmover_get_derivative(m, &d, t);\n            last = s;",
     "            last = s;"),
    ("air-last", BMC, "            last = s;\n", ""),
    ("air-pz", BMC, "            pz = p.z;\n", ""),
    ("air-dz", BMC, "            dz = d.z;\n", ""),
    ("air-scale", BMC, "    return sum * BM_AIR_SCALE;", "    return sum;"),

    # -- Move ---------------------------------------------------------------
    ("mv-setbelt-lt", BMC, "    if (m->pSpline->NumControlPoints < 2)\n        beltmover_set_belt(m);",
     "    if (m->pSpline->NumControlPoints < 1)\n        beltmover_set_belt(m);"),
    ("mv-setbelt-le", BMC, "    if (m->pSpline->NumControlPoints < 2)\n        beltmover_set_belt(m);",
     "    if (m->pSpline->NumControlPoints <= 2)\n        beltmover_set_belt(m);"),
    ("mv-air-arg", BMC, "beltmover_average_air(m, 0.5f)", "beltmover_average_air(m, dt)"),
    ("mv-air-cmp", BMC, "    if (BM_AIR_THRESHOLD < beltmover_average_air(m, 0.5f))",
     "    if (BM_AIR_THRESHOLD > beltmover_average_air(m, 0.5f))"),
    ("mv-timer", BMC, "            (uint32_t)ee_trunc_w(BM_OFF_BELT_TICKS);",
     "            (uint32_t)ee_trunc_w(BM_OFF_BELT_TICKS) + 1u;"),
    ("mv-old", BMC, "    old = car->State.Position;\n\n",
     "    old = car->State.Position;\n    old.pad = 0.0f;\n\n"),
    ("mv-ftime", BMC, "    m->fTime = m->fTime + dt;", "    m->fTime = dt;"),
    ("mv-speed", BMC, "    speed = ee_div(m->dv + m->ddv * m->fTime, m->fScale);",
     "    speed = ee_div(m->dv + 2.0f * m->ddv * m->fTime, m->fScale);"),
    ("mv-speed-div", BMC, "    speed = ee_div(m->dv + m->ddv * m->fTime, m->fScale);",
     "    speed = (m->dv + m->ddv * m->fTime) / m->fScale;"),
    ("mv-heading-t", BMC, "    beltmover_get_derivative(m, &d, m->fTime + 0.5f);",
     "    beltmover_get_derivative(m, &d, m->fTime + 0.4f);"),
    ("mv-ang-x", BMC, "    xy.x = d.x;\n    xy.y = d.y;\n    bspline2d_set_val_desired(m->pCubicAng, &xy);",
     "    xy.x = d.y;\n    xy.y = d.y;\n    bspline2d_set_val_desired(m->pCubicAng, &xy);"),
    ("mv-ang-seek", BMC, "    bspline2d_seek(m->pCubicAng, dt);",
     "    bspline2d_seek(m->pCubicAng, dt + dt);"),
    ("mv-ang-get", BMC, "    bspline2d_get_val(m->pCubicAng, &xy);\n    d.x = xy.x;",
     "    d.x = xy.x;"),
    ("mv-side-t", BMC, "    t = m->fTime + BM_SLIDE_LOOK_AHEAD;", "    t = m->fTime;"),
    ("mv-up", BMC, "    up.z = 1.0f;\n    up.pad = 0.0f;\n    beltmover_get_derivative(m, &dd, t);",
     "    up.z = -1.0f;\n    up.pad = 0.0f;\n    beltmover_get_derivative(m, &dd, t);"),
    ("mv-side-cross", BMC, "    beltmover_get_derivative(m, &dd, t);\n    cross3(&side, &dd, &up);",
     "    beltmover_get_derivative(m, &dd, t);\n    cross3(&side, &up, &dd);"),
    ("mv-side-norm", BMC, "    cross3(&side, &dd, &up);\n    normalize4(&side);\n    beltmover_get_second_derivative",
     "    cross3(&side, &dd, &up);\n    beltmover_get_second_derivative"),
    ("mv-record", BMC, "    average_record(m->pAvgAccel, dot3(&side, &dd));",
     "    average_record(m->pAvgAccel, -dot3(&side, &dd));"),
    ("mv-record-t", BMC, "    beltmover_get_second_derivative(m, &dd, t);",
     "    beltmover_get_second_derivative(m, &dd, m->fTime);"),
    ("mv-slide-arg", BMC, "    slide = beltmover_slide_coef(m, m->pAvgAccel->fAverage);",
     "    slide = beltmover_slide_coef(m, m->pAvgAccel->fTotal);"),
    ("mv-k", BMC, "    k = speed * (slide * BM_SLIDE_LOOK_AHEAD);",
     "    k = (speed * slide) * BM_SLIDE_LOOK_AHEAD;"),
    ("mv-s-w", BMC, "    d.pad = d.pad + s.pad;\n", ""),
    ("mv-slide-seek", BMC, "    bspline2d_seek(m->pCubicSlide, dt);",
     "    bspline2d_seek(m->pCubicSlide, dt + dt);"),
    ("mv-slide-get", BMC, "    bspline2d_get_val(m->pCubicSlide, &xy);\n", ""),
    ("mv-slide-y", BMC, "    xy.x = s.x;\n    xy.y = s.y;", "    xy.x = s.x;\n    xy.y = s.x;"),
    ("mv-dsum", BMC, "    d.x = d.x + s.x;", "    d.x = d.x - s.x;"),
    ("mv-atan", BMC, "    newA = (uint16_t)bATan(d.x, d.y);",
     "    newA = (uint16_t)bATan(d.y, d.x);"),
    ("mv-angle", BMC, "    cs->Angle = newA;\n", ""),
    ("mv-side2-t", BMC, "    beltmover_get_derivative(m, &dd, m->fTime);\n    cross3(&side, &dd, &up);",
     "    beltmover_get_derivative(m, &dd, t);\n    cross3(&side, &dd, &up);"),
    ("mv-side2-norm", BMC, "    normalize4(&side);\n    cubic_set_val_desired",
     "    cubic_set_val_desired"),
    ("mv-u-desired", BMC, "    cubic_set_val_desired(m->pCubicU, -slide);",
     "    cubic_set_val_desired(m->pCubicU, slide);"),
    ("mv-u-seek", BMC, "    bspline_seek(m->pCubicU, dt);",
     "    bspline_seek(m->pCubicU, dt + dt);"),
    ("mv-u-val", BMC, "    k = m->pCubicU->val;", "    k = m->pCubicU->valDesired;"),
    ("mv-pos-t", BMC, "    beltmover_get_point(m, &pos, m->fTime);",
     "    beltmover_get_point(m, &pos, t);"),
    ("mv-pos-side", BMC, "    scale4(&side, &side, k);\n    pos.x",
     "    scale4(&side, &side, -k);\n    pos.x"),
    ("mv-pos-w", BMC, "    pos.pad = side.pad + pos.pad;", "    pos.pad = pos.pad;"),
    ("mv-flat", BMC, "    car_put_flat_on_track(m->pCar);\n", ""),
    ("mv-geom", BMC, "    carstate_calculate_geometry_position(cs);\n", ""),
    ("mv-av-x", BMC, "    car->State.AngularVelocity.x = 0.0f;\n", ""),
    ("mv-av-y", BMC, "    car->State.AngularVelocity.y = 0.0f;\n", ""),
    ("mv-av-short", BMC, "ee_div((float)(int16_t)(uint16_t)(newA - oldA) * BM_BAM_TO_RAD, dt);",
     "ee_div((float)(uint16_t)(newA - oldA) * BM_BAM_TO_RAD, dt);"),
    ("mv-av-div", BMC, "ee_div((float)(int16_t)(uint16_t)(newA - oldA) * BM_BAM_TO_RAD, dt);",
     "(float)(int16_t)(uint16_t)(newA - oldA) * BM_BAM_TO_RAD / dt;"),
    ("mv-av-order", BMC, "ee_div((float)(int16_t)(uint16_t)(newA - oldA) * BM_BAM_TO_RAD, dt);",
     "ee_div((float)(int16_t)(uint16_t)(oldA - newA) * BM_BAM_TO_RAD, dt);"),
    ("mv-vel-x", BMC, "    vel.x = m->pCar->State.Position.x - old.x;",
     "    vel.x = old.x - m->pCar->State.Position.x;"),
    ("mv-vel-z", BMC, "    vel.z = m->pCar->State.Position.z - old.z;",
     "    vel.z = pos.z - old.z;"),
    ("mv-vel-w", BMC, "    vel.pad = m->pCar->State.Position.pad - old.pad;",
     "    vel.pad = 0.0f;"),
    ("mv-mindt-lt", BMC, "    if (fabsf(dt) <= BM_MIN_DT)", "    if (fabsf(dt) < BM_MIN_DT)"),
    ("mv-mindt-abs", BMC, "    if (fabsf(dt) <= BM_MIN_DT)", "    if (dt <= BM_MIN_DT)"),
    ("mv-normalize", BMC, "        bNormalize3To(&vel, &vel, speed);",
     "        bNormalize3To(&vel, &vel, 1.0f);"),
    ("mv-inverse", BMC, "        scale4(&vel, &vel, 1.0f / dt);",
     "        { vel.x = vel.x / dt; vel.y = vel.y / dt; vel.z = vel.z / dt;\n          vel.pad = vel.pad / dt; }"),
    ("mv-vel-store", BMC, "    cs->Velocity = vel;\n", ""),
    ("mv-mag", BMC, "    mag = sqrtf(dot3(&vel, &vel));", "    mag = speed;"),
    ("mv-fs", BMC, "    cs->ForwardSpeed = mag;", "    cs->ForwardSpeed = speed;"),
    ("mv-vm", BMC, "    cs->VelocityMagnitude = mag;\n", ""),
    ("mv-matrix", BMC, "    cs->MatrixValid = 0;", "    cs->MatrixValid = 1;"),
    ("mv-lng", BMC, "    lng = speed - dot3(&vel, (const bVector3 *)(const void *)\n                              &m->pCar->State.BodyMatrix.v0);",
     "    lng = speed - dot3(&vel, (const bVector3 *)(const void *)\n                              &m->pCar->State.BodyMatrix.v2);"),
    ("mv-lat", BMC, "    lat = -dot3(&vel,", "    lat = dot3(&vel,"),
    ("mv-wangle", BMC, "        angle = cs->WheelAngle[i] + cs->WheelAngularVelocity[i] * m->fTime;",
     "        angle = cs->WheelAngle[i] + cs->WheelAngularVelocity[i] * dt;"),
    ("mv-steer-front", BMC, "        if (w->WI->WheelNumber < 2)\n            steer",
     "        if (i < 2)\n            steer"),
    ("mv-steer-le", BMC, "        if (w->WI->WheelNumber < 2)\n            steer",
     "        if (w->WI->WheelNumber <= 2)\n            steer"),
    ("mv-steer", BMC, "            steer = (float)m->pCar->pCarDriver->Steering;",
     "            steer = (float)(int16_t)m->pCar->pCarDriver->Steering;"),
    ("mv-radius", BMC, "speed / cti->Wheels[i].Radius", "speed / cti->Wheels[0].Radius"),
    ("mv-susp", BMC, "(uint16_t)ee_trunc_w(steer), 0.0f);",
     "(uint16_t)ee_trunc_w(steer), 1.0f);"),
    ("mv-slip", BMC, "        cs->WheelSlip[i].x = lng;", "        cs->WheelSlip[i].x = lat;"),
    ("mv-tu", BMC, "        cs->WheelTractionUsage[i] = 0.0f;\n", ""),
    ("mv-rear", BMC, "        if (!(w->WI->WheelNumber < 2)) {", "        if (!(i < 2)) {"),
    ("mv-wslip0", BMC, "            w->Slip[0] = lng;", "            w->Slip[0] = lat;"),
    ("mv-wslip1", BMC, "            w->Slip[1] = lat;", "            w->Slip[1] = lng;"),
    ("mv-slipping", BMC, "            w->Slipping = (uint8_t)m->bSliding;",
     "            w->Slipping = 1;"),
    ("mv-cur", BMC, "            w->CurrentSlip = lng;", "            w->CurrentSlip = lat;"),
    ("mv-vfx-le", BMC, "           < 200.0f)", "           <= 200.0f)"),
    ("mv-vfx", BMC, "    if (car_should_visual_effects_be_generated(m->pCar)\n        && ",
     "    if ("),
    ("mv-skids-dt", BMC, "            wheel_maybe_make_skids(m->pWheels[i], dt);",
     "            wheel_maybe_make_skids(m->pWheels[i], m->fTime);"),
    ("mv-rpm", BMC, "    car_compute_fake_rpm(m->pCar);\n", ""),
    ("mv-ret", BMC, "    car_compute_fake_rpm(m->pCar);\n    return dt;",
     "    car_compute_fake_rpm(m->pCar);\n    return 0.0f;"),

    # -- the getters --------------------------------------------------------
    ("gp-u", BMC, "    float u = t * (t * m->ddv + m->dv) + m->v;\n\n    spline_point(m->pSpline, out, u, 0);",
     "    float u = t * m->dv + m->v;\n\n    spline_point(m->pSpline, out, u, 0);"),
    ("gp-floor", BMC, "    if (u < 0.0f) {", "    if (u < -1.0f) {"),
    ("gp-floor-cmp", BMC, "        if (out->z < z0)", "        if (out->z > z0)"),
    ("gp-floor-cp", BMC, "pControlPoints[0].z;", "pControlPoints[1].z;"),
    ("gp-ret", BMC, "    return out;\n}\n\nbVector3 *beltmover_get_derivative",
     "    return NULL;\n}\n\nbVector3 *beltmover_get_derivative"),
    ("gd-du", BMC, "    float du = (t + t) * m->ddv + m->dv;\n    float u = t * (t * m->ddv + m->dv) + m->v;\n\n    spline_point(m->pSpline, out, u, 1);",
     "    float du = t * m->ddv + m->dv;\n    float u = t * (t * m->ddv + m->dv) + m->v;\n\n    spline_point(m->pSpline, out, u, 1);"),
    ("gd-basis", BMC, "    spline_point(m->pSpline, out, u, 1);\n    scale4(out, out, du);",
     "    spline_point(m->pSpline, out, u, 0);\n    scale4(out, out, du);"),
    ("gd-scale", BMC, "    spline_point(m->pSpline, out, u, 1);\n    scale4(out, out, du);",
     "    spline_point(m->pSpline, out, u, 1);"),
    ("gdd-dd", BMC, "    float dd = m->ddv + m->ddv;", "    float dd = m->ddv;"),
    ("gdd-du2", BMC, "    scale4(&b, &b, du * du);", "    scale4(&b, &b, du);"),
    ("gdd-basis", BMC, "    spline_point(m->pSpline, &b, u, 2);",
     "    spline_point(m->pSpline, &b, u, 1);"),
    ("gdd-du", BMC, "    float dd = m->ddv + m->ddv;\n    float du = (t + t) * m->ddv + m->dv;",
     "    float dd = m->ddv + m->ddv;\n    float du = t * m->ddv + m->dv;"),

    # -- the table and the seams -------------------------------------------
    ("vt-move", BMC, "    { 0, 0, (VtFn)vt_BeltMover_Move },",
     "    { 0, 0, NULL },"),
    ("seam-ctor", BMC, "    gBeltMoverCtorFn = beltmover_construct;\n", ""),

    # -- banim.c's tCubic1D and tCubic2D -----------------------------------
    ("ddval-6", BAC, "s->coeff[0] * (t * 6.0f)", "s->coeff[0] * (t * 3.0f)"),
    ("ddval-c1", BAC, "(s->coeff[1] + s->coeff[1])", "s->coeff[1]"),
    ("b2-setval-x", BAC, "    s->x.val = v->x;\n    if (v->x != s->x.valDesired) s->x.state = 2;",
     "    s->x.val = v->x;"),
    ("b2-setval-y", BAC, "    if (v->y != s->y.valDesired) s->y.state = 2;\n",
     ""),
    ("b2-setval-store", BAC, "    s->y.val = v->y;\n", ""),
    ("b2-setdval-x", BAC, "    if (v->x != s->x.dvalDesired) s->x.state = 2;\n", ""),
    ("b2-setdval-y", BAC, "    s->y.dval = v->y;\n", "    s->y.dval = v->x;\n"),
    ("b2-setdval-cmp", BAC, "    if (v->y != s->y.dvalDesired) s->y.state = 2;",
     "    if (v->y != s->y.dval) s->y.state = 2;"),
    ("b2-desired-x", BAC, "    if (v->x != s->x.val) s->x.state = 2;\n", ""),
    ("b2-desired-y", BAC, "    s->y.valDesired = v->y;\n", ""),
    ("b2-getval", BAC, "    out->y = s->y.val;", "    out->y = s->y.valDesired;"),
    ("b2-getdval", BAC, "    out->x = s->x.dval;", "    out->x = s->x.dvalDesired;"),
    ("b2-seek-y", BAC, "    bspline_seek(&s->y, dt);\n}", "}"),
]

EQUIVALENT = {
    "cross-z": "every cross product here is against (0, 0, 1), so its z is "
               "a zero either way; only the zero's sign changes, and it "
               "is added to a nonzero sum or multiplied into another zero "
               "(the standing scenario, all zeros, shows no word moves)",
    "del-vptr": "nothing derives from BeltMover, so its destructor is "
                "reached only through its own table and the vptr already "
                "holds it",
    "sb-dirty": "SetNumControlPoints has set ControlPointsDirty just "
                "before, and nothing in the loop clears it",
    "air-h-le": "h is exactly 0 only for a dt of 0, where every step is "
                "the car's own point and the touch the else branch "
                "records is the one it already has",
    "mv-s-w": "only the sum's x and y are read, by bATan",
    "mv-steer": "the steering goes back to 16 bits through cvt.w.s and a "
                "halfword store, which give the same bits for 65535.0 and "
                "-1.0",
}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name


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

    for name, rel, before, after in todo:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if probe not in text:
            missing.append(name)
            print("  %-28s PATTERN NOT FOUND" % name)
            continue
        try:
            hostbuild.write_source(path, text.replace(probe, repl, 1))
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = build_harness(tmp)
                except SystemExit:
                    print("  %-28s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, ops, out)
                if rc == pcc.HARNESS_HUNG:
                    print("  %-28s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-28s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-28s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-28s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-28s SURVIVED" % name)
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
