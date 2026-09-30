#!/usr/bin/env python3
"""Cross-check 3DS Files/source/drivecam.c, DriveCameraMover, against the
retail image itself, run in mipsemu.

The model is the image. Retail's constructor (0x0015c258), destructor
(0x0015c400, through the vtable), ResetState (0x0015c470), SetPOVIndex
(0x0015c520), every slot of its vtable (0x002b1dd0) but Render -- Update
(0x0015c880) with GetLookbackCar (0x0015c680) and the two wall helpers
(0x00157930, 0x00157b60) among them -- the three corrections (0x0015c158,
0x0015c1d0, 0x0015c218), CalculateLookbackAngle (0x0015c5a8) and the
out-of-line accessors (0x0015fbf8 .. 0x0015fc9c) run as shipped, over
CameraMover's base, the Camera constructor and SetCameraMatrix, eMath,
bCos, bASin, bATan, bNormalize, retail's own eView table and its terrain
table. The harness (tools/src/drivecam_test.c) runs the port over the same
script, and the two transcripts are diffed.

The stubs print what they were given and answer from the script, the same
on both sides: TopologyCoordinate's constructor (0x00151c28) and
destructor (0x00151c70), which print whose they were; and Update's callees
outside the camera and the maths -- GetCarByDriverNumber, the cop
manager's GetCopByCar and GetCopByChase, GetYaw, GetRoadNoise,
SetInterestBBox, GetElevation, ConstrainToTopology, PointInShaft (a plane
distance worked out the same way on both sides), GetCarSpaceBoundingBox
and ApplyCameraShake. bRefreshTweaker, which redraws the debug menu, does
nothing; the port has no menu and no call.

Every camera, mover, car, car type, player, polygon and cop starts from a
byte pattern, so what a call leaves alone shows. A float prints as its
bits, a NaN as "nan", and a pointer by what it is: a camera or its target,
a mover or its TopologyCoordinate, a car, its State or its
GeometryPosition, a player, a view or its list's head, a vtable, a
polygon, a cop, a pursuit, the cop manager, or a car type and the offset
into it. Most resets follow a scribble over the words only Update writes.
After each Update the mover, every word of its camera and the two tuning
words Update writes print.

    python tools/drivecam_check.py
    python tools/drivecam_check.py --mutate [--only a,b]
    python tools/drivecam_check.py --dump out/drivecam
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

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import physicscar_check as pcc
import retail_model
from mipsemu import M32, f_to_bits, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/drivecam_test.c"
DRVC = "3DS Files/source/drivecam.c"
SOURCES = [HARNESS, DRVC] + ["3DS Files/source/" + f for f in (
    "camera.c", "cammover.c", "eview.c", "emath.c", "bmatrix.c", "bmath.c",
    "bmathtab.c", "bvector.c", "copmanager.c", "terraintypetab.c")]

HARNESS_TIMEOUT = 120
UPDATE_FRAMES = 150

# ================================================================ the image

GP = 0x003358f0
CAM_CTOR = 0x00156be0
DCM_CTOR = 0x0015c258
SET_POV = 0x0015c520
YAW = 0x0015c158
PITCH = 0x0015c1d0
INCAR = 0x0015c218
CALC_LB = 0x0015c5a8
GET_LBA = 0x0015fbf8
GET_SPEED = 0x0015fc00
SET_SPEED = 0x0015fc08
GET_LAG = 0x0015fc10
SET_LAG = 0x0015fc18
LOOKING_BACK = 0x0015fc28
SET_LOOK = 0x0015fc50
IS_LOOKING_BACK = 0x0015fc70      # the non-virtual one
SET_PLAYER = 0x0015fca0
TOPO_CTOR = 0x00151c28
TOPO_DTOR = 0x00151c70
# Update's callees that are stubs.
BY_DRIVER = 0x0014d5d0            # GetCarByDriverNumber
REFRESH_TWEAKER = 0x0025d2c8
COP_BY_CAR = 0x00224f70
COP_BY_CHASE = 0x00224fc8
GET_YAW = 0x001c0888              # CarState::GetYaw
ROAD_NOISE = 0x00153498
SET_BBOX3 = 0x00136e00            # SetInterestBBox(bVector3), j 0x00151d30
GET_ELEV = 0x00152070
CONSTRAIN = 0x001528b0            # ConstrainToTopology
IN_SHAFT = 0x001517d8             # TrackPolygon::PointInShaft
CAR_BOX = 0x00135170              # Car::GetCarSpaceBoundingBox
SHAKE = 0x00156560                # ApplyCameraShake
EMATH_SINIT = 0x0011bf70
FUNK_EXISTS = 0x0025d220
BASE_VTBL = 0x002b1e50
DCM_VTBL = 0x002b1dd0
VIEWS = 0x002c95b0
VIEW_STRIDE = 128
NVIEWS = 10
V_CAMERA = 56
V_LIST = 60

G_STOP = GP - 21808               # Camera::StopUpdating
G_VIEWMODE = GP - 24888           # CurrentViewMode
G_CTI = GP - 20616                # CarTypeInfoArray
G_COPMGR = GP - 15620             # pCopManager

# The tuning Update reads: name, gp offset, kind (0 float, 1 int32, 2 u16).
# Each scenario starts from the image's values, but for the two elapsed
# times, which the image leaves 0 until the game runs: a sixtieth.
TUNING = [
    ("DriveUseTweakables", -21760, 1), ("DriveLag", -21756, 0),
    ("DriveHeight", -21752, 0), ("DriveLatOffset", -21748, 0),
    ("DriveAngle", -21744, 2), ("DriveMaxAngle", -21742, 2),
    ("CamGlobalMultiplier", -21636, 0), ("CamAdjustment", -21632, 0),
    ("CamBackAdjust", -21628, 0), ("CamHoldTimeout", -21624, 0),
    ("CamYawAdjuster", -21608, 0), ("CamAccelScaleRatio", -21604, 0),
    ("CamDecelScaleRatio", -21600, 0), ("CamRangeCheckA", -21596, 0),
    ("CamRangeCheckD", -21592, 0), ("CamLagMultiplier", -21588, 0),
    ("CamSpeedAdjust", -21580, 0), ("CamHeightMultiplierD", -21564, 0),
    ("CamAccelCap", -21560, 0), ("CamDecelCap", -21556, 0),
    ("CamDisableAdjust", -21552, 0), ("CamBackAdjustQuicker", -21548, 0),
    ("RoadNoiseAmplitude", -21536, 0),
    ("CameraFollowDefaultCar", -21532, 1),
    ("CameraFollowThisCarInstead", -21528, 1),
    ("WorldTimeElapsed", -19560, 0), ("RealTimeElapsed", -19596, 0),
]
TUNE = {n: (GP + o, k) for n, o, k in TUNING}
SIXTIETH = 0x3c888889

CAM_SIZE = 464
CAMS = 0x01000000
NCAM = 4
DRVS = 0x01010000
DRV_STRIDE = 0x400
DRV_SIZE = 1008
NDRV = 4
CARS = 0x01020000
CAR_STRIDE = 0x800
NCAR = 4
CTIS = 0x01030000
CTI_STRIDE = 1376
NCTI = 3
PLAYERS = 0x01040000
PL_STRIDE = 0x100
NPL = 2
MATRIX = 0x01050000
POLYS = 0x01060000
POLY_SIZE = 128
NPOLY = 24
COPS = 0x01070000
COP_SIZE = 32
NCOP = 3
PURS = 0x01070100
PUR_SIZE = 32
NPUR = 2
COPMGR = 0x01070200
NDRIVER = 12

PATTERN = 0xa5

# Retail's offsets.
C_TGT, C_FD, C_DOF, C_NEAR, C_FAR, C_CARNOT, C_DASH = (96, 116, 120, 124,
                                                       128, 444, 448)
CAR_CTI, CAR_GPOS, CAR_POS, CAR_BODYZ, CAR_ANGLE, CAR_FWD = (12, 80, 96, 152,
                                                             932, 960)
# The rest of the State Update reads: Velocity, Acceleration, BodyMatrix,
# nWheelsTouchingGround and DriverMode (retail's 892 and 924 in the State).
CAR_STATE, CAR_VELV, CAR_ACC, CAR_BODY, CAR_NWHEELS, CAR_MODE = (
    64, 112, 128, 144, 956, 988)
CTI_ZDIM = 492                    # Body.Zdim
CTI_CAMERA = 960
PL_LOOKBACK = 44                  # PlayerSettings (32) + 12

SLOTS = {
    "destroy": 12, "update": 20, "info": 52, "pov": 60, "ext": 68,
    "lookback": 76, "gap": 84, "reset": 92, "car": 116, "target": 124,
}

DRIVE_FIELDS = {"want": 124, "lbp": 128, "pov": 120, "lba": 140}

# The words only Update writes, which the constructor leaves at 0 or 1 and
# nothing else in this slice moves: X scribbles over each, in this order, as
# a frame of Update would, so that a ResetState that leaves one shows.
UPDATE_WORDS = ([132, 136, 144, 148, 152, 156, 160, 164, 168, 172, 176]
                + [892 + 4 * i for i in range(20)]
                + [972, 976, 980, 984, 988])


def scribble_word(seed, k):
    """The harness's scribble_word(): a finite float's bits, never 0 or 1."""
    v = (seed ^ (k * 0x9e3779b9)) & M32 & ~0x40000000
    return v | 1 if v in (0, 0x3f800000) else v
CAM_FIELDS = {"carnot": C_CARNOT, "dash": C_DASH, "fd": C_FD, "dof": C_DOF}

POV_FULL = CTI_CAMERA + 16
POV_SPLIT = CTI_CAMERA + 144


def fb(v):
    if isinstance(v, int):
        return v & M32
    return f_to_bits(v)


def bits_f(w):
    return struct.unpack("<f", struct.pack("<I", w & M32))[0]


def fx(w):
    w &= M32
    if (w & 0x7f800000) == 0x7f800000 and (w & 0x7fffff):
        return "nan"
    return "%08x" % w


def cam_at(k):
    return CAMS + CAM_SIZE * k


def drv_at(j):
    return DRVS + DRV_STRIDE * j


def car_at(c):
    return CARS + CAR_STRIDE * c


def cti_at(t):
    return CTIS + CTI_STRIDE * t


def pl_at(p):
    return PLAYERS + PL_STRIDE * p


def view_at(i):
    return VIEWS + VIEW_STRIDE * i


# ============================================================ the scenarios

F32 = np.float32


def f32(x):
    return F32(x)


def f32_bits(x):
    return struct.unpack("<I", struct.pack("<f", float(F32(x))))[0]


def lookback_port(fp, tp, r0, r1, sumorder=0, dotorder=0, divide=False):
    """CalculateLookbackAngle in float32, as the port has it and as a few
    of the mutants would: used only to find inputs that tell them apart."""
    with np.errstate(all="ignore"):
        d = [F32(tp[i]) - F32(fp[i]) for i in range(3)]
        sq = [d[i] * d[i] for i in range(3)]
        s = (sq[0] + sq[1]) + sq[2] if sumorder == 0 else \
            sq[0] + (sq[1] + sq[2])
        r = np.sqrt(F32(s))
        if divide:
            n = [d[i] / r for i in range(3)]
        else:
            inv = F32(1.0) / r
            n = [d[i] * inv for i in range(3)]

        def dot(m):
            p = [F32(m[i]) * n[i] for i in range(3)]
            return (p[0] + p[1]) + p[2] if dotorder == 0 else \
                p[0] + (p[1] + p[2])
        fwd, side = dot(r0), dot(r1)
    if F32(0.7071) < fwd:
        return 0
    if fwd < F32(-0.7071):
        return 0x8000
    if side < F32(0.0):
        return 0x4000
    return 0xc000


def rvec(rnd, spread):
    return [rnd.uniform(-spread, spread) for _ in range(3)]


def car_line(rnd, c, t, pos=None, gpos=None):
    ang = rnd.choice((0, 1, 0x4000, 0x7fff, 0x8000, 0xc000, 0xffff,
                      rnd.getrandbits(16)))
    z = rnd.choice((0.0, -0.0, 1.0, -1.0, 0.5, -0.5, 0.9999, -0.0001,
                    rnd.uniform(-1, 1), rnd.uniform(-1, 1)))
    vel = rnd.choice((0.0, 12.5, 88.0, rnd.uniform(0, 100)))
    if gpos is None:
        gpos = rvec(rnd, 500) + [rnd.choice((0.0, 1.0))]
    if pos is None:
        pos = rvec(rnd, 500) + [rnd.choice((0.0, 1.0, 7.0))]
    return "A %d %d %04x %08x %08x %s %s" % (
        c, t, ang, fb(z), fb(vel), " ".join("%08x" % fb(x) for x in gpos),
        " ".join("%08x" % fb(x) for x in pos))


def pov_offsets():
    """Every POV slot a count below 6 and an index from -1 reach."""
    out = []
    for i in range(-1, 5):
        out.append(POV_FULL + 32 * i)
        out.append(POV_SPLIT + 32 * i)
    return sorted(set(out))


POV_TYPES = (0, 1, 2, 3, 0xffffffff, 2, 2)
LOOKBACKS = (0, 0, 0, 1, 2, 0xffffffff)
COUNTS = (0, 1, 2, 3, 4, 4, 4, 5, 0xffffffff)


def setup(rnd, out):
    for k in range(NCAM):
        out.append("C %d" % k)
        out.append("V %d %d" % (k, k))
    for t in range(NCTI):
        out.append("I %d %x %x" % (t, rnd.choice(COUNTS), rnd.choice(COUNTS)))
        for off in pov_offsets():
            if rnd.random() < 0.8:
                out.append("P %d %d %x" % (t, off, rnd.choice(POV_TYPES)))
    for c in range(NCAR):
        out.append(car_line(rnd, c, rnd.randrange(NCTI)))
    for p in range(NPL):
        out.append("L %d %x" % (p, rnd.choice(LOOKBACKS)))


def ctor_line(rnd, j, view, car):
    pov = rnd.choice((0, 1, 2, 3, -1, 4, 7))
    speed = rnd.choice((0.0, 1.0, 2.5, 4.0, 0.3, rnd.uniform(0, 10)))
    lag = rnd.choice((0, 1, 2, 0xffffffff))
    lb = rnd.choice((0, 1, 1, 5, 0xffffffff))
    pf = rnd.choice((0, 1, 3))
    return "N %d %d %d %d %08x %x %x %x" % (j, view, car, pov, fb(speed), lag,
                                            lb, pf)


FLOATS = (0.0, -0.0, 1.0, 0.5, 0.25, 1e-30, -0.25, 1.0000001, 0.9999999,
          2.0, float("nan"))


def float_bits(v):
    if v != v:
        return 0x7fc00000
    return fb(v)


def s_ctor(rnd):
    """Built on every camera, against every car type's counts, with the
    fallback's array moved, frozen and not."""
    out = []
    setup(rnd, out)
    out += ["I 0 4 4", "I 1 0 4", "I 2 4 0"]
    for c, t in ((0, 0), (1, 1), (2, 2), (3, 0)):
        out.append(car_line(rnd, c, t))
    for k in range(NCAM):
        out.append("c %d carnot 12345678" % k)
        out.append("c %d dash 00000003" % k)
        out.append("c %d fd %08x" % (k, fb(7.5)))
        out.append("c %d dof %08x" % (k, fb(2.25)))
    for j in range(NDRV):
        out.append(ctor_line(rnd, j, j, j))
        out.append("Q %d" % j)
    for j in range(NDRV):
        out.append("c %d carnot 0badf00d" % j)
        out.append("c %d fd %08x" % (j, fb(3.0)))
        out.append("c %d dof %08x" % (j, fb(1.5)))
        out.append("D %d" % j)
    # The fallback reads the array's pointer, wherever it points.
    out += ["G 2", "I 2 3 2", "I 1 0 0"]
    out.append(ctor_line(rnd, 0, 0, 1))
    out.append("Q 0")
    out.append("D 0")
    out += ["G 1"]
    out.append(ctor_line(rnd, 1, 1, 2))
    out.append("Q 1")
    out.append("D 1")
    # Frozen: neither the constructor nor the destructor touches the camera.
    for k in range(2):
        out.append("c %d carnot 22222222" % k)
        out.append("c %d dash 00000005" % k)
        out.append("c %d fd %08x" % (k, fb(9.0)))
    out.append("Z 1")
    out.append(ctor_line(rnd, 2, 0, 0))
    out.append("Z 0")
    out.append("Q 2")
    out.append("Z 1")
    out.append("D 2")
    out.append("Z 0")
    out.append(ctor_line(rnd, 3, 1, 3))
    out.append("Z 1")
    out.append("D 3")
    out.append("Z 0")
    # Detached, which only a frozen camera allows.
    out.append("Z 1")
    out.append(ctor_line(rnd, 0, -1, 2))
    out.append("Q 0")
    out.append("R 0")
    out.append("D 0")
    out.append("Z 0")
    # Two on one view, and the second destroyed first.
    out.append(ctor_line(rnd, 0, 2, 0))
    out.append(ctor_line(rnd, 1, 2, 1))
    out += ["D 1", "D 0"]
    # Every lookBack value, and each lookback speed kept as given.
    for lb in (0, 1, 2, 0x80000000, 0xffffffff):
        out.append("N 0 3 0 0 %08x 0 %x 0" % (fb(rnd.uniform(0, 8)), lb))
        out.append("Q 0")
        out.append("D 0")
    return out


def s_walk(rnd, n_ops):
    """A random walk over four movers, their fields and their queries."""
    out = []
    setup(rnd, out)
    live = {}                     # mover -> its view; -1 is detached
    nocar = set()
    # The scribbles draw on their own stream, so the walk is the same walk.
    xr = random.Random(0x5c21b0 + n_ops)
    for step in range(n_ops):
        r = rnd.random()
        j = rnd.randrange(NDRV)
        if j not in live or r < 0.08:
            if j in live:
                if live[j] == -1:
                    out += ["Z 1", "D %d" % j, "Z 0"]
                else:
                    out.append("D %d" % j)
            view = rnd.choice((0, 1, 2, 3, 0, 1, -1))
            car = rnd.randrange(NCAR)
            if view == -1:
                out += ["Z 1", ctor_line(rnd, j, view, car), "Z 0"]
            else:
                out.append(ctor_line(rnd, j, view, car))
            live[j] = view
            nocar.discard(j)
        elif r < 0.30:
            if rnd.random() < 0.4:
                out.append("M %d" % rnd.choice((0, 1, 2, 3, 3, 4)))
            out.append("Q %d" % j)
        elif r < 0.36 and j not in nocar:
            if xr.random() < 0.75:
                out.append("X %d %08x" % (j, xr.getrandbits(32)))
            out.append("R %d" % j)
        elif r < 0.42:
            out.append("S %d %x" % (j, rnd.choice((0, 1, 2, 3, 4, 0xffffffff))))
        elif r < 0.56:
            f = rnd.choice(("want", "lbp", "lbp", "want", "pov", "lba"))
            if f in ("want", "lbp"):
                v = float_bits(rnd.choice(FLOATS + (rnd.random(),)))
            elif f == "pov":
                v = rnd.choice((0, 1, 2, 3, 4, 0xffffffff))
            else:
                v = rnd.getrandbits(16)
            out.append("F %d %s %08x" % (j, f, v))
        elif r < 0.64:
            out.append("F %d player %d" % (j, rnd.choice((0, 1, 1, 0, -1))))
        elif r < 0.67 and live[j] != -1:
            c = rnd.choice((0, 1, 2, 3, -1))
            out.append("F %d car %d" % (j, c))
            if c < 0:
                nocar.add(j)
            else:
                nocar.discard(j)
        elif r < 0.74:
            f = rnd.choice(("speed", "lag", "look"))
            if f == "speed":
                v = float_bits(rnd.choice(FLOATS + (rnd.uniform(0, 9),)))
            elif f == "lag":
                v = rnd.choice((0, 1, 2, 0xffffffff))
            else:
                v = rnd.choice((0, 1, 2, 0xffffffff))
            out.append("W %d %s %08x" % (j, f, v))
        elif r < 0.78:
            out.append("L %d %x" % (rnd.randrange(NPL),
                                    rnd.choice(LOOKBACKS)))
        elif r < 0.82:
            t = rnd.randrange(NCTI)
            if rnd.random() < 0.5:
                out.append("I %d %x %x" % (t, rnd.choice(COUNTS),
                                           rnd.choice(COUNTS)))
            else:
                out.append("P %d %d %x" % (t, rnd.choice(pov_offsets()),
                                           rnd.choice(POV_TYPES)))
        elif r < 0.86:
            out.append(car_line(rnd, rnd.randrange(NCAR), rnd.randrange(NCTI)))
        elif r < 0.88:
            out.append("G %d" % rnd.randrange(NCTI))
        elif r < 0.92:
            k = rnd.randrange(NCAM)
            f = rnd.choice(("carnot", "dash", "fd", "dof"))
            v = rnd.getrandbits(32) if f in ("carnot", "dash") else \
                fb(rnd.uniform(0.5, 50))
            out.append("c %d %s %08x" % (k, f, v))
        elif r < 0.95 and live[j] != -1:
            out += ["Z 1", "D %d" % j, "Z 0"]
            del live[j]
        else:
            out.append("M %d" % rnd.choice((0, 1, 2, 3, 3, 4)))
            out.append("Q %d" % j)
    for j in sorted(live):
        if live[j] == -1:
            out += ["Z 1", "D %d" % j, "Z 0"]
        else:
            out.append("D %d" % j)
    return out


def s_corrections(rnd):
    angles = [0, 1, 2, 3, 6, 7, 8, 9, 14, 15, 16, 17, 100, 0x3fff, 0x4000,
              0x7ffe, 0x7fff, 0x8000, 0x8001, 0x8002, 0xbfff, 0xc000,
              0xfff0, 0xfff7, 0xfff8, 0xfff9, 0xfffa, 0xfffd, 0xfffe, 0xffff]
    angles += [rnd.getrandbits(16) for _ in range(200)]
    angles += [rnd.randrange(-40, 40) & 0xffff for _ in range(60)]
    return ["Y %04x" % a for a in angles]


def k_line(fc, tc, r0, r1):
    return "K %d %d %s" % (fc, tc, " ".join("%08x" % fb(float(x))
                                           for x in list(r0) + list(r1)))


def s_lookback(rnd):
    """CalculateLookbackAngle: random directions and frames, the two
    thresholds and the side's zero hit exactly, the two cars on one spot,
    and inputs found to tell the rounding orders apart."""
    out = []
    setup(rnd, out)
    pos = {}
    for c in range(NCAR):
        p = rvec(rnd, 300) + [rnd.choice((0.0, 1.0))]
        pos[c] = p
        out.append(car_line(rnd, c, 0, pos=p))

    def place(c, p):
        pos[c] = list(p) + [1.0]
        out.append(car_line(rnd, c, 0, pos=pos[c]))

    for _ in range(150):
        a, b = rnd.sample(range(NCAR), 2)
        r0 = [rnd.uniform(-1, 1) for _ in range(3)] + [rnd.uniform(-2, 2)]
        r1 = [rnd.uniform(-1, 1) for _ in range(3)] + [rnd.uniform(-2, 2)]
        out.append(k_line(a, b, r0, r1))
        if rnd.random() < 0.1:
            c = rnd.randrange(NCAR)
            place(c, rvec(rnd, 300))
    # Exactly on the thresholds: along x, the first row's x is +-0.7071.
    place(0, (0.0, 0.0, 0.0))
    place(1, (10.0, 0.0, 0.0))
    for fwd in (0.7071, -0.7071, 0.70710677, -0.70710677, 0.7070999,
                -0.7070999):
        for side in (0.0, -0.0, 1e-38, -1e-38, 0.5, -0.5):
            out.append(k_line(0, 1, (fwd, 0.0, 0.0, 0.0),
                              (side, 0.0, 1.0, 0.0)))
    # The side row perpendicular: its dot is 0 or -0.
    for r1 in ((0.0, 1.0, 0.0), (0.0, -1.0, 0.0), (-0.0, 0.0, -1.0)):
        out.append(k_line(0, 1, (0.0, 0.0, 1.0, 0.0), tuple(r1) + (0.0,)))
    # On one spot: the direction is NaN and every compare fails.
    place(2, (10.0, 0.0, 0.0))
    out.append(k_line(1, 2, (1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0)))
    out.append(k_line(1, 2, (-1.0, 0.0, 0.0, 0.0), (0.0, -1.0, 0.0, 0.0)))
    # Searched: a direction 0.7071 +- 1e-6 along the first row, forward or
    # back, so that a different rounding order would land on the other side
    # of the threshold.
    srnd = random.Random(0xd21e)
    found = {"sum": 0, "dot": 0, "div": 0}
    tries = 0

    def unit(v):
        n = sum(x * x for x in v) ** 0.5
        return [x / n for x in v]

    while min(found.values()) < 4 and tries < 200000:
        tries += 1
        r0 = unit([srnd.uniform(-1, 1) for _ in range(3)])
        u = [srnd.uniform(-1, 1) for _ in range(3)]
        k = sum(u[i] * r0[i] for i in range(3))
        u = unit([u[i] - k * r0[i] for i in range(3)])
        c = srnd.choice((0.7071, -0.7071)) + srnd.uniform(-1e-6, 1e-6)
        s = (1.0 - c * c) ** 0.5
        dist = srnd.uniform(0.5, 400)
        fp = [float(F32(srnd.uniform(-300, 300))) for _ in range(3)]
        tp = [float(F32(fp[i] + dist * (c * r0[i] + s * u[i])))
              for i in range(3)]
        r0 = [float(F32(x)) for x in r0]
        r1 = [float(F32(x)) for x in u]
        base = lookback_port(fp, tp, r0, r1)
        for key, kw in (("sum", {"sumorder": 1}), ("dot", {"dotorder": 1}),
                        ("div", {"divide": True})):
            if found[key] < 4 and lookback_port(fp, tp, r0, r1, **kw) != base:
                found[key] += 1
                place(0, fp)
                place(1, tp)
                out.append(k_line(0, 1, r0 + [0.0], r1 + [0.0]))
    if min(found.values()) < 4:
        raise SystemExit("the look-back search found only %r" % (found,))
    return out

# ---- Update's scenarios ----------------------------------------------------

# Terrains retail's table lets the camera through (ShouldCameraGoThroughIt).
THROUGH = (16, 28, 29, 30, 32)


def pov_lines(rnd, t, split=False, kinds=(2, 2, 1, 0)):
    """Four POVs of the given kinds, with plausible lags, heights and
    angles, and now and then a short outside boom that brings the eye
    within the car's reach."""
    base = POV_SPLIT if split else POV_FULL
    out = []
    for i, ty in enumerate(kinds):
        a = base + 32 * i
        if ty == 2:
            lag = rnd.choice((rnd.uniform(4.5, 9.0), rnd.uniform(4.5, 9.0),
                              rnd.uniform(0.5, 2.5)))
            height = rnd.uniform(1.0, 3.2)
        elif ty == 1:
            lag = rnd.uniform(-0.6, 0.6)
            height = rnd.uniform(0.6, 1.3)
        else:
            lag = rnd.uniform(-2.5, -1.0)
            height = rnd.uniform(0.3, 0.9)
        lat = rnd.choice((0.0, 0.0, rnd.uniform(-0.6, 0.6)))
        ang = rnd.choice((0, 0, rnd.randrange(0, 1600)))
        mx = rnd.choice((2000, ang + rnd.randrange(0, 3000)))
        out.append("P %d %d %x" % (t, a, ty))
        out.append("P %d %d %08x" % (t, a + 4, fb(lag)))
        out.append("P %d %d %08x" % (t, a + 8, fb(height)))
        out.append("P %d %d %08x" % (t, a + 12, fb(lat)))
        out.append("P %d %d %08x" % (t, a + 16,
                                     (ang & 0xffff) | ((mx & 0xffff) << 16)))
    return out


def hx(*vals):
    return " ".join("%08x" % fb(float(v)) for v in vals)


class Sim(object):
    """A car driven through phases -- calm, a hard pull away, braking, a
    jump -- so that the lag's ten-and-ten samples line up."""

    def __init__(self, rnd, c, t):
        self.c, self.t = c, t
        self.pos = [rnd.uniform(-400, 400), rnd.uniform(-400, 400),
                    rnd.uniform(-5, 30)]
        self.yaw = rnd.uniform(-math.pi, math.pi)
        self.pitch = rnd.uniform(-0.12, 0.12)
        self.roll = rnd.uniform(-0.05, 0.05)
        self.speed = rnd.choice((0.0, rnd.uniform(0, 60), rnd.uniform(0, 60)))
        self.acc = 0.0
        self.turn = 0.0
        self.slip = 0.0
        self.up = 0.0
        self.left = 0
        self.kind = "calm"
        self.wheels = 4
        self.mode = 0
        self.pw = rnd.choice((0.0, 1.0))
        self.gpos_same = False

    def axes(self):
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        cr, sr = math.cos(self.roll), math.sin(self.roll)
        fwd = (cp * cy, cp * sy, sp)
        left0 = (-sy, cy, 0.0)
        up0 = (-sp * cy, -sp * sy, cp)
        left = tuple(left0[i] * cr + up0[i] * sr for i in range(3))
        up = tuple(up0[i] * cr - left0[i] * sr for i in range(3))
        return fwd, left, up

    def step(self, rnd, dt):
        if self.left <= 0:
            k = rnd.random()
            if self.speed < 12 and 0.35 <= k < 0.85:
                k = 0.4
            if k < 0.35:
                self.kind, self.left = "calm", rnd.randrange(10, 24)
                self.acc = rnd.uniform(-3.0, 1.0)
            elif k < 0.6:
                self.kind, self.left = "accel", rnd.randrange(8, 28)
                self.acc = rnd.choice((rnd.uniform(1.3, 9.0),
                                       rnd.uniform(9.0, 16.0)))
            elif k < 0.85:
                self.kind, self.left = "brake", rnd.randrange(8, 20)
                self.acc = rnd.choice((rnd.uniform(-16.0, -6.0),
                                       rnd.uniform(-32.0, -16.0)))
            else:
                self.kind, self.left = "air", rnd.randrange(3, 14)
                self.acc = rnd.uniform(-2.0, 2.0)
            self.turn = rnd.choice((0.0, rnd.uniform(-1.2, 1.2)))
            self.slip = rnd.choice((0.0, 0.0, rnd.uniform(-4, 4)))
            self.mode = rnd.choice((0, 0, 0, 1, 2))
        self.left -= 1
        self.wheels = rnd.choice((0, 1, 2)) if self.kind == "air" else \
            rnd.choice((4, 4, 4, 4, 3, 2))
        self.up = rnd.uniform(-9.8, 3.0) if self.kind == "air" else \
            rnd.uniform(-1.0, 1.0)
        self.speed += self.acc * dt
        if self.speed < -15:
            self.speed = -15.0
        self.yaw += self.turn * dt
        self.pitch = max(-0.5, min(0.5, self.pitch
                                   + rnd.uniform(-0.03, 0.03)))
        self.roll = max(-0.3, min(0.3, self.roll + rnd.uniform(-0.02, 0.02)))
        fwd, left, _ = self.axes()
        for i in range(3):
            self.pos[i] += (fwd[i] * self.speed + left[i] * self.slip) * dt

    def lines(self, rnd):
        fwd, left, up = self.axes()
        vel = [fwd[i] * self.speed + left[i] * self.slip for i in range(3)]
        acc = [fwd[i] * self.acc + left[i] * self.turn * self.speed * 0.2
               + up[i] * self.up + rnd.uniform(-0.3, 0.3) for i in range(3)]
        ang = int(self.yaw / (2 * math.pi) * 65536) & 0xffff
        gpos = [self.pos[i] + fwd[i] * 0.2 + up[i] * 0.35 for i in range(3)]
        if self.gpos_same:
            gpos = list(self.pos)
        body = list(fwd) + [0.0] + list(left) + [0.0] + list(up) + [0.0] + \
            self.pos + [1.0]
        a = "A %d %d %04x %s %s %s %s" % (
            self.c, self.t, ang, hx(fwd[2]), hx(self.speed),
            hx(*(gpos + [self.pw])), hx(*(self.pos + [self.pw])))
        e = "E %d %s %s %s %x %x" % (self.c, hx(*(vel + [0.0])),
                                    hx(*(acc + [rnd.choice((0.0, 1.0))])),
                                    hx(*body), self.wheels, self.mode)
        return [a, e]

    def eye(self, lag, height):
        fwd, _, up = self.axes()
        return [self.pos[i] - fwd[i] * lag + up[i] * height
                for i in range(3)]


def poly_line(rnd, k, eye):
    """A polygon whose plane passes within a metre or so of `eye`."""
    r = rnd.random()
    if r < 0.6:
        a = rnd.uniform(-math.pi, math.pi)
        n = (math.cos(a), math.sin(a), 0.0)
    elif r < 0.85:
        n = (rnd.uniform(-0.1, 0.1), rnd.uniform(-0.1, 0.1), 1.0)
    else:
        n = tuple(rnd.uniform(-1, 1) for _ in range(3))
    ln = math.sqrt(sum(x * x for x in n)) or 1.0
    n = tuple(x / ln for x in n)
    target = rnd.uniform(-0.4, 1.3)
    dist = -sum(n[i] * eye[i] for i in range(3)) + target
    flags = rnd.choice((0, 0, 2, 1, 3, 0x42, 0))
    terrain = rnd.choice((0, 1, 2, 3, 5, 0, 0) + THROUGH[:2])
    if rnd.random() < 0.08:
        terrain = rnd.choice(THROUGH)
    inside = 1 if rnd.random() < 0.75 else 0
    return "p %d %x %x %s %x" % (k, flags, terrain, hx(n[0], n[1], n[2], dist),
                                 inside)


def frame_env(rnd, out, sim, outside, lagest, hest):
    """The stubs' answers for one Update of the camera behind `sim`."""
    eye = sim.eye(lagest, hest) if outside else sim.eye(0.0, 1.0)
    for _ in range(rnd.choice((0, 1, 2, 3, 3, 5))):
        out.append(poly_line(rnd, rnd.randrange(NPOLY), eye))
    n = rnd.choice((0, 1, 2, 3, 4, 6, 8, 3, 2))
    out.append(("l %d %s" % (n, " ".join(str(rnd.randrange(NPOLY))
                                         for _ in range(n)))).rstrip())
    out.append("e %s" % hx(eye[2] - 0.7 + rnd.uniform(-0.6, 0.4)))
    out.append("n %s" % hx(rnd.uniform(-1, 1)))
    if rnd.random() < 0.3:
        out.append("t %s %x" % (hx(*[rnd.uniform(-0.4, 0.4)
                                     for _ in range(3)]),
                                rnd.choice((0, 1))))
    elif rnd.random() < 0.3:
        out.append("t %s 0" % hx(0, 0, 0))
    if rnd.random() < 0.15:
        out.append("s %s" % hx(*[rnd.uniform(-0.2, 0.2) for _ in range(3)]))
    elif rnd.random() < 0.2:
        out.append("s %s" % hx(0, 0, 0))
    out.append("a %d %s" % (sim.c, hx(rnd.choice((
        rnd.uniform(-0.1, 0.1), rnd.uniform(-0.3, 0.3), 0.0)))))


def update_setup(rnd, out, kinds=None):
    for k in range(NCAM):
        out.append("C %d" % k)
        out.append("V %d %d" % (k, k))
    for t in range(NCTI):
        out.append("I %d 4 4" % t)
        ks = kinds or (2, 2, 1, 0)
        out += pov_lines(rnd, t, False, ks)
        out += pov_lines(rnd, t, True, ks)
        out.append("z %d %s" % (t, hx(rnd.uniform(1.1, 1.7))))
    sims = []
    for c in range(NCAR):
        sim = Sim(rnd, c, c % NCTI)
        sims.append(sim)
        out += sim.lines(rnd)
        mnx = -rnd.uniform(1.6, 2.8)
        mxx = rnd.uniform(1.6, 2.8)
        out.append("b %d %s %s" % (c, hx(mnx, -1.0, -0.4, 0.0),
                                   hx(mxx, 1.0, 1.2, 1.0)))
    for p in range(NPL):
        out.append("L %d %x" % (p, p))    # p0 counts a look back, p1 not
    return sims


def run_frames(rnd, out, sims, frames, movers, events=None, dt=1.0 / 60,
               quiet=None):
    """`frames` steps of every car, each followed by an Update of every
    mover. `events(f, out)` may add ops before a frame's Updates; no X
    scribbles mover j in frame f when `quiet(f, j)`."""
    lagest = {j: rnd.uniform(3, 9) for j in movers}
    for f in range(frames):
        for sim in sims:
            sim.step(rnd, dt)
            out += sim.lines(rnd)
        if events:
            events(f, out)
        for j, car in movers.items():
            frame_env(rnd, out, sims[car], rnd.random() < 0.75, lagest[j],
                      rnd.uniform(1.0, 3.0))
            if rnd.random() < 0.02 and not (quiet and quiet(f, j)):
                out.append("X %d %08x" % (j, rnd.getrandbits(32)))
            out.append("U %d" % j)


def s_update_chase(rnd, frames):
    """Four chase cameras on four views, one car each, with the POV and
    the view mode moving under them and a freeze now and then."""
    out = []
    sims = update_setup(rnd, out)
    movers = {}
    for j in range(NDRV):
        pov = rnd.choice((0, 0, 1, 2, 3))
        out.append("N %d %d %d %d %08x %x 0 %x" % (
            j, j, j, pov, fb(rnd.uniform(1, 4)), rnd.choice((0, 0, 1)),
            rnd.choice((0, 0, 1))))
        movers[j] = j

    def events(f, o):
        if f in (25, 70, 120):
            o.append("S %d %x" % (f % NDRV, 4 if f < 100 else 0xffffffff))
        r = rnd.random()
        if r < 0.04:
            o.append("M %d" % rnd.choice((0, 3, 3, 1)))
        elif r < 0.08:
            o.append("S %d %x" % (rnd.randrange(NDRV),
                                  rnd.choice((0, 1, 2, 3, 4, 0xffffffff))))
        elif r < 0.10:
            o.append("Z 1")
        elif r < 0.16:
            o.append("Z 0")
        elif r < 0.19:
            o.append("W %d lag %x" % (rnd.randrange(NDRV), rnd.choice((0, 1))))
        elif r < 0.21:
            o.append("T WorldTimeElapsed %08x" % fb(rnd.choice(
                (1.0 / 60, 1.0 / 30, 0.1, 0.0, 1.0 / 120, 0.5, 0.034))))
        elif r < 0.22:
            o.append("T RealTimeElapsed %08x" % fb(rnd.choice(
                (1.0 / 60, 1.0 / 30, 0.02))))
    run_frames(rnd, out, sims, frames, movers, events)
    out.append("Z 0")
    for j in range(NDRV):
        out.append("D %d" % j)
    return out


def s_update_lookback(rnd, frames):
    """The player's look back: movers with the player whose setting counts
    it, the wish to look back flipping, split screen and full."""
    out = []
    sims = update_setup(rnd, out)
    movers = {}
    for j in range(NDRV):
        out.append("N %d %d %d %d %08x 0 %x 0" % (
            j, j, j, rnd.choice((0, 1, 2, 3)), fb(rnd.uniform(1.5, 5)),
            rnd.choice((0, 1))))
        out.append("F %d player %d" % (j, rnd.choice((0, 0, 1, -1))))
        movers[j] = j

    def events(f, o):
        r = rnd.random()
        if r < 0.10:
            o.append("F %d want %08x" % (rnd.randrange(NDRV), fb(rnd.choice(
                (1.0, 0.0, 1.0, 0.5)))))
        elif r < 0.14:
            o.append("F %d player %d" % (rnd.randrange(NDRV),
                                         rnd.choice((0, 1, -1))))
        elif r < 0.18:
            o.append("M %d" % rnd.choice((0, 3)))
        elif r < 0.21:
            o.append("S %d %x" % (rnd.randrange(NDRV), rnd.choice((0, 1, 2,
                                                                  3))))
        elif r < 0.23:
            o.append("L %d %x" % (rnd.randrange(NPL), rnd.choice((0, 1))))
    run_frames(rnd, out, sims, frames, movers, events)
    for j in range(NDRV):
        out.append("D %d" % j)
    return out


def s_update_cops(rnd, frames):
    """A cop looking back at the car it chases and a chased car at its
    cop, with no player to count the look back; the cars placed ahead,
    behind, beside and far off."""
    out = []
    sims = update_setup(rnd, out)
    out.append("H 1")
    out += ["u 0 2", "u 1 3", "o 0 0 1", "o 1 1 0", "o 2 -1 2"]
    # car0 is cop0, chasing car2; car1 is being chased by cop1 (car0);
    # car2 is cop2, with no pursuit; car3 is being chased by cop0 (car1).
    out += ["O 0 0 -1", "O 1 -1 1", "O 2 2 -1", "O 3 -1 0"]
    movers = {}
    for j in range(NDRV):
        out.append("N %d %d %d %d %08x %x 1 0" % (
            j, j, j, 0 if j == 0 else rnd.choice((0, 0, 1, 2, 3)),
            fb(rnd.uniform(1, 4)), rnd.choice((0, 0, 1))))
        movers[j] = j
    # (bearing off the nose, distance, frames): the look back settles on
    # each, some over the slow 20000 a second and some the fast 60000;
    # 0.845 leaves it just short of the 45 degrees behind, so the next,
    # straight back and far, wraps to 65536.
    pins = ((-math.pi / 2, 15.0, 30), (0.0, 15.0, 16), (math.pi / 2, 8.0, 20),
            (math.pi, 60.0, 30), (2.6, 60.0, 16), (0.845, 20.0, 40),
            (0.3, 70.0, 12), (-0.845, 20.0, 40), (-0.3, 70.0, 12))
    starts = [20]
    for pin in pins:
        starts.append(starts[-1] + pin[2])

    def events(f, o):
        if starts[0] <= f < starts[-1]:
            k = max(i for i in range(len(pins)) if starts[i] <= f)
            ang, d, _ = pins[k]
            # No slip, so the heading is the nose, and the pin is placed in
            # this frame's lines.
            sims[0].slip = 0.0
            fwd, left, _ = sims[0].axes()
            for i in range(3):
                sims[2].pos[i] = sims[0].pos[i] + d * (
                    math.cos(ang) * fwd[i] + math.sin(ang) * left[i])
            o += sims[0].lines(rnd) + sims[2].lines(rnd)
            if f == starts[k]:
                o += ["H 1", "u 0 2", "F 0 player -1", "S 0 0",
                      "F 0 want 3f800000"]
                if k == 3:
                    # A low boom, so the rise over the roof goes up; the
                    # view mode that adds nothing; car3 no cop's.
                    o += ["P 0 %d %08x" % (POV_FULL + 8, fb(0.5)),
                          "P 0 %d %08x" % (POV_SPLIT + 8, fb(0.5)),
                          "M 3", "O 3 -1 -1"]
                elif k == 4:
                    o.append("M 0")
            if f == starts[-1] - 4:
                # A player who counts the look back.
                o.append("F 0 player 0")
            return
        r = rnd.random()
        if r < 0.05:
            # Bring one car near another, at a chosen bearing.
            a, b = rnd.sample(range(NCAR), 2)
            fwd, left, _ = sims[a].axes()
            ang = rnd.choice((0.0, math.pi, math.pi / 2, -math.pi / 2,
                              rnd.uniform(-math.pi, math.pi)))
            d = rnd.choice((5.0, 20.0, 60.0, rnd.uniform(1, 90)))
            for i in range(3):
                sims[b].pos[i] = sims[a].pos[i] + d * (
                    math.cos(ang) * fwd[i] + math.sin(ang) * left[i])
        elif r < 0.10:
            o.append("F %d want %08x" % (rnd.randrange(NDRV), fb(rnd.choice(
                (1.0, 1.0, 0.0, 0.75)))))
        elif r < 0.13:
            o.append("H %d" % rnd.choice((0, 1, 1)))
        elif r < 0.16:
            o.append("F %d player %d" % (rnd.randrange(NDRV),
                                         rnd.choice((1, 1, 0, -1))))
        elif r < 0.19:
            o.append("M %d" % rnd.choice((0, 3)))
        elif r < 0.22:
            o.append("S %d %x" % (rnd.randrange(NDRV), rnd.choice((0, 1, 2,
                                                                  3))))
        elif r < 0.24:
            o.append("u %d %d" % (rnd.randrange(NPUR), rnd.choice((0, 1, 2, 3,
                                                                  -1))))
    # The cars start in a bunch, so the chases are close.
    for sim in sims[1:]:
        for i in range(3):
            sim.pos[i] = sims[0].pos[i] + rnd.uniform(-30, 30)
    run_frames(rnd, out, sims, max(frames, starts[-1] + 20), movers, events,
               quiet=lambda f, j: j == 0 and starts[0] <= f < starts[-1])
    for j in range(NDRV):
        out.append("D %d" % j)
    return out


def s_update_tuning(rnd, frames):
    """The debug menu's words: the Drive* set in place of the POV, a car
    followed by driver number, the Cam* set changed, the lag disabled,
    and the elapsed times."""
    out = []
    sims = update_setup(rnd, out)
    movers = {}
    for j in range(NDRV):
        out.append("N %d %d %d %d %08x %x 0 %x" % (
            j, j, j, rnd.choice((0, 1, 2, 3)), fb(rnd.uniform(1, 4)),
            rnd.choice((0, 1)), rnd.choice((0, 1))))
        movers[j] = j
    for n in range(NDRIVER):
        if rnd.random() < 0.4:
            out.append("g %d %d" % (n, rnd.randrange(NCAR)))

    floats = {
        "DriveLag": (2.0, 12.0), "DriveHeight": (0.5, 4.0),
        "DriveLatOffset": (-1.0, 1.0), "CamGlobalMultiplier": (0.5, 2.0),
        "CamAdjustment": (0.01, 0.1), "CamBackAdjust": (0.005, 0.05),
        "CamHoldTimeout": (0.1, 3.0), "CamYawAdjuster": (0.0, 10.0),
        "CamAccelScaleRatio": (0.2, 1.5), "CamDecelScaleRatio": (0.02, 0.2),
        "CamRangeCheckA": (0.2, 1.5), "CamRangeCheckD": (-1.0, -0.1),
        "CamLagMultiplier": (0.2, 3.0), "CamSpeedAdjust": (50.0, 800.0),
        "CamHeightMultiplierD": (0.0, 1.0), "CamAccelCap": (0.5, 8.0),
        "CamDecelCap": (-4.0, -0.2), "CamDisableAdjust": (0.1, 1.0),
        "CamBackAdjustQuicker": (0.5, 5.0), "RoadNoiseAmplitude": (0, 2000),
    }

    def events(f, o):
        if f == 10:
            o.append("T DriveUseTweakables 1")
        elif f == 50:
            o.append("T DriveUseTweakables 0")
            o.append("T CameraFollowDefaultCar 0")
            o.append("T CameraFollowThisCarInstead 00000005")
        elif f == 70:
            o.append("T CameraFollowThisCarInstead 0000000b")
        elif f == 90:
            o.append("T CameraFollowDefaultCar 1")
        if f == 30:
            o.append("Z 1")
        elif f == 42:
            o.append("Z 0")
        r = rnd.random()
        if r < 0.06:
            o.append("T DriveUseTweakables %x" % rnd.choice((0, 1, 1, 7)))
        elif r < 0.10:
            o.append("T DriveAngle %x" % rnd.choice((0, 300, 1500, 0xff00)))
            o.append("T DriveMaxAngle %x" % rnd.choice((2000, 0, 4000)))
        elif r < 0.20:
            name = rnd.choice(sorted(floats))
            lo, hi = floats[name]
            o.append("T %s %08x" % (name, fb(rnd.uniform(lo, hi))))
        elif r < 0.24:
            o.append("T CameraFollowDefaultCar %x" % rnd.choice((0, 0, 1)))
        elif r < 0.28:
            o.append("T CameraFollowThisCarInstead %08x"
                     % (rnd.choice((-1, 0, 3, 5, 11, 20)) & M32))
        elif r < 0.30:
            o.append("g %d %d" % (rnd.randrange(NDRIVER),
                                  rnd.choice((-1, 0, 1, 2, 3))))
        elif r < 0.34:
            o.append("W %d lag %x" % (rnd.randrange(NDRV), rnd.choice((0, 1))))
        elif r < 0.37:
            o.append("T WorldTimeElapsed %08x" % fb(rnd.choice(
                (1.0 / 60, 1.0 / 30, 0.1, 0.0, 0.25, 0.034, 1.0 / 60))))
        elif r < 0.39:
            o.append("M %d" % rnd.choice((0, 3)))
    run_frames(rnd, out, sims, frames, movers, events)
    for j in range(NDRV):
        out.append("D %d" % j)
    return out


def s_update_corners(rnd):
    """The corners the random scenarios miss, one after another, behind
    one outside camera on car 0, driven slowly near the origin so that a
    last-place change in the lag reaches the eye:
    - StopUpdating from the first Update, over the camera's focus of 0
    - the acceleration lag (calm, a hard pull away, calm, braking) with
      DriveUseTweakables 1 and DriveLag 0, so the boom is the lag alone,
      then 7 and 5, then the POV's words
    - one sample of pull, nine calm and then the pull, so that only the
      twentieth sample holds the lag back
    - the lag disabled, then CamSpeedAdjust under the car's speed
    - braking through walking pace with the lag held, twice
    - the nose straight up (bASin's 16384), on the ground and in the air
    - CameraFollowThisCarInstead at 0 with no car for driver 0
    - a cop's look back wanted half way, then at a chased car 45 m off
      at 50 degrees either side, between the step speeds' distances.
    The tuning scenario's random phases never lined the lag's ten and ten
    samples up while it held the tweakables on, and the other scenarios'
    cars, hundreds of metres out, round a last-place change away."""
    out = []
    sims = update_setup(rnd, out)
    sim = sims[0]
    sim.pos = [0.5, -0.3, 0.2]
    sim.yaw, sim.pitch, sim.roll, sim.speed = 0.3, 0.0, 0.0, 0.0
    out += sim.lines(rnd)
    # Not looking back: a look back's round of 1 takes the lag out of the
    # POV's boom, and its LookBackAngle takes the pitch past the nose.
    out += ["N 0 0 0 0 %08x 0 0 0" % fb(2.0), "F 0 player -1"]
    cops = ["H 1", "u 0 2", "u 1 3", "o 0 0 1", "o 1 1 0", "o 2 -1 2",
            "O 0 0 -1", "O 1 -1 1", "O 2 2 -1", "O 3 -1 0"]
    # (kind, frames, acceleration, speed to set or None, ops at the start,
    #  frames in it with the nose up, the chased car's bearing and distance)
    steps = (
        # CamLagMultiplier off 1, so that grouping it with the speed's
        # factor rounds differently.
        ("calm", 3, 0.0, None, ["Z 1", "T DriveUseTweakables 1",
                                "T DriveLag 0", "T CamLagMultiplier %08x"
                                % fb(1.37)], (), None),
        ("calm", 11, 0.0, None, ["Z 0"], (), None),
        ("accel", 22, 12.0, None, [], (), None),
        ("calm", 14, 0.0, None, [], (), None),
        ("brake", 18, -20.0, None, [], (), None),
        ("calm", 14, 0.0, None, ["T DriveUseTweakables 7",
                                 "T DriveLag %08x" % fb(5.0)], (), None),
        ("accel", 22, 12.0, None, [], (), None),
        ("calm", 14, 0.0, None, [], (), None),
        ("brake", 18, -20.0, None, [], (), None),
        ("calm", 14, 0.0, None, ["T DriveUseTweakables 0"], (), None),
        ("accel", 1, 12.0, None, [], (), None),
        ("calm", 9, 0.0, None, [], (), None),
        ("accel", 22, 12.0, None, [], (), None),
        ("calm", 14, 0.0, None, ["W 0 lag 1"], (), None),
        ("brake", 18, -20.0, None, [], (), None),
        ("calm", 14, 0.0, 30.0, ["W 0 lag 0", "T CamSpeedAdjust %08x"
                                 % fb(50.0)], (), None),
        ("accel", 22, 12.0, None, [], (), None),
        ("calm", 14, 0.0, None, ["T CamSpeedAdjust %08x" % fb(500.0)], (),
         None),
        ("calm", 20, 0.0, 5.0, [], (), None),
        ("brake", 30, -8.0, None, [], (), None),
        ("accel", 22, 12.0, None, [], (), None),
        ("calm", 20, 0.0, 5.0, [], (), None),
        ("brake", 30, -8.0, None, [], (), None),
        ("calm", 8, 0.0, 10.0, [], (4,), None),
        ("air", 10, 0.0, None, [], (7, 8), None),
        ("calm", 8, 0.0, None, [], (), None),
        ("calm", 1, 0.0, None, ["g 0 -1", "T CameraFollowDefaultCar 0",
                                "T CameraFollowThisCarInstead 0"], (), None),
        ("calm", 4, 0.0, None, ["T CameraFollowDefaultCar 1"], (), None),
        ("calm", 6, 0.0, None, cops + ["F 0 want 3f000000"], (), None),
        ("calm", 20, 0.0, None, ["F 0 want 3f800000"], (), (0.873, 45.0)),
        ("calm", 20, 0.0, None, [], (), (-0.873, 45.0)),
    )
    starts = [0]
    for st in steps:
        starts.append(starts[-1] + st[1])

    def phase(f):
        return max(i for i in range(len(steps)) if starts[i] <= f)

    def arm(k):
        # The sim draws no phase of its own.
        kind, _, acc, speed = steps[k][:4]
        sim.kind, sim.acc, sim.left = kind, acc, 1 << 20
        sim.turn = sim.slip = 0.0
        sim.mode = 0
        if speed is not None:
            sim.speed = speed

    arm(0)

    def events(f, o):
        k = phase(f)
        ops, nose, chased = steps[k][4:]
        if f == starts[k]:
            o += ops
        if f + 1 == starts[k + 1] and k + 1 < len(steps):
            arm(k + 1)
        if f - starts[k] in nose:
            p = sim.pitch
            sim.pitch = math.pi / 2
            o += sim.lines(rnd)
            sim.pitch = p
        if chased:
            ang, dist = chased
            fwd, left, _ = sim.axes()
            for i in range(3):
                sims[2].pos[i] = sim.pos[i] + dist * (
                    math.cos(ang) * fwd[i] + math.sin(ang) * left[i])
            o += sim.lines(rnd) + sims[2].lines(rnd)
    run_frames(rnd, out, sims, starts[-1], {0: 0}, events,
               quiet=lambda f, j: True)
    out.append("D 0")
    return out


def s_update_edges(rnd):
    """Cars placed on the edges: at rest (bNormalize's (1, 0)), reversing,
    at the swing's 8.32 and 13 m/s, pitched past the half turn, on the
    ground and off it, at walk pace for the 5 mph test, and with the lag
    held past its timeout."""
    out = []
    sims = update_setup(rnd, out, kinds=(2, 1, 0, 2))
    for j in range(2):
        out.append("N %d %d %d 0 %08x %x 0 0" % (j, j, j, fb(2.0), j))
    for t in range(2):
        a = POV_FULL + 32 * 3
        out += ["P %d %d 2" % (t, a), "P %d %d 0" % (t, a + 4),
                "P %d %d 0" % (t, a + 8), "P %d %d 0" % (t, a + 12),
                "P %d %d 07d00000" % (t, a + 16)]
        a = POV_FULL + 32 * 1
        out += ["P %d %d 2" % (t, a), "P %d %d %08x" % (t, a + 4, fb(0.4)),
                "P %d %d %08x" % (t, a + 8, fb(0.6)),
                "P %d %d 0" % (t, a + 12), "P %d %d 07d00190" % (t, a + 16)]
    for pov in (3, 1):
        for c in range(2):
            out.append("S %d %d" % (c, pov))
        for k in range(12):
            for c in range(2):
                sim = sims[c]
                sim.gpos_same = pov == 3 and k < 8
                sim.speed = (0.0, 250.0, 30.0, -4.0)[k % 4]
                sim.pitch = 0.0
                sim.roll = 0.0
                out += sim.lines(rnd)
                frame_env(rnd, out, sim, True, 0.0, 0.0)
                out.append("U %d" % c)
    for c in range(2):
        sims[c].gpos_same = False
        out.append("S %d 0" % c)
    speeds = (0.0, -0.0, 0.5, -3.0, -12.0, 8.32, 8.33, 13.0, 12.99, 13.02,
              2.235, 2.24, 20.0, 60.0)
    for sp in speeds:
        for pitch in (0.0, 0.3, -0.3, 0.49, -0.49):
            for c in range(2):
                sim = sims[c]
                sim.speed = sp
                sim.pitch = pitch
                sim.slip = rnd.choice((0.0, 0.0, 1.5))
                sim.wheels = rnd.choice((4, 2, 0, 3))
                out += sim.lines(rnd)
                frame_env(rnd, out, sim, True, 6.0, 2.0)
                out.append("U %d" % c)
    # A hard pull away after a calm, then held: the hold times out.
    out.append("T WorldTimeElapsed %08x" % fb(0.1))
    for disable in (0, 1):
        # Past CamBackAdjustQuicker, the lag comes back twice as fast.
        out.append("T CamBackAdjustQuicker %08x" % fb(0.2 if disable == 0
                                                       else 3.0))
        for c in range(2):
            out.append("W %d lag %x" % (c, disable))
        for k in range(60):
            for c in range(2):
                sim = sims[c]
                sim.speed = 30.0
                sim.pitch = 0.0
                sim.mode = disable
                sim.acc = 0.0 if k < 12 or k > 40 else \
                    (4.0 if c == 0 else -10.0)
                out += sim.lines(rnd)
                frame_env(rnd, out, sim, True, 6.0, 2.0)
                out.append("U %d" % c)
    out.append("T WorldTimeElapsed %08x" % fb(1.0 / 60))
    for j in range(2):
        out.append("D %d" % j)
    return out


def script():
    rnd = random.Random(0xd21ec0de)
    sc = [s_ctor(rnd), s_corrections(rnd), s_lookback(rnd)]
    for n in (60, 200, 400, 400, 400):
        sc.append(s_walk(rnd, n))
    # Update's own stream, so the scenarios above keep their draws.
    urnd = random.Random(0x0015c880)
    sc.append(s_update_edges(urnd))
    sc.append(s_update_chase(urnd, UPDATE_FRAMES))
    sc.append(s_update_lookback(urnd, UPDATE_FRAMES))
    sc.append(s_update_cops(urnd, UPDATE_FRAMES))
    sc.append(s_update_tuning(urnd, UPDATE_FRAMES))
    sc.append(s_update_corners(urnd))
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
        e = self.e
        e.stub(FUNK_EXISTS, lambda em: 0)
        e.stub(TOPO_CTOR, self.topo_init)
        e.stub(TOPO_DTOR, self.topo_destroy)
        e.stub(BY_DRIVER, self.by_driver)
        e.stub(REFRESH_TWEAKER, lambda em: None)
        e.stub(COP_BY_CAR, lambda em: self.cop_by(em, "copbycar", 0))
        e.stub(COP_BY_CHASE, lambda em: self.cop_by(em, "copbychase", 1))
        e.stub(GET_YAW, self.get_yaw)
        e.stub(ROAD_NOISE, self.road_noise)
        e.stub(SET_BBOX3, self.set_bbox)
        e.stub(GET_ELEV, self.get_elev)
        e.stub(CONSTRAIN, self.constrain)
        e.stub(IN_SHAFT, self.in_shaft)
        e.stub(CAR_BOX, self.car_box)
        e.stub(SHAKE, self.shake)
        e.call(EMATH_SINIT)
        self.tuning = {}
        for n, (a, k) in TUNE.items():
            self.tuning[n] = e.u16(a) if k == 2 else self.w(a)
        self.tuning["WorldTimeElapsed"] = SIXTIETH
        self.tuning["RealTimeElapsed"] = SIXTIETH
        self.names = {0: "null", BASE_VTBL: "base", DCM_VTBL: "drive"}
        for k in range(NCAM):
            self.names[cam_at(k)] = "c%d" % k
            self.names[cam_at(k) + C_TGT] = "c%d.tgt" % k
        for j in range(NDRV):
            self.names[drv_at(j)] = "d%d" % j
        for c in range(NCAR):
            self.names[car_at(c)] = "car%d" % c
            self.names[car_at(c) + CAR_GPOS] = "car%d.gpos" % c
        for p in range(NPL):
            self.names[pl_at(p)] = "p%d" % p
        for i in range(NVIEWS):
            self.names[view_at(i)] = "v%d" % i
            self.names[view_at(i) + V_LIST] = "v%d.list" % i
        for c in range(NCAR):
            self.names[car_at(c) + CAR_STATE] = "car%d.state" % c
        for j in range(NDRV):
            self.names[drv_at(j) + 180] = "d%d.tc" % j
        for k in range(NPOLY):
            self.names[POLYS + POLY_SIZE * k] = "poly%d" % k
        for k in range(NCOP):
            self.names[COPS + COP_SIZE * k] = "cop%d" % k
        for k in range(NPUR):
            self.names[PURS + PUR_SIZE * k] = "pur%d" % k
        self.names[COPMGR] = "copmgr"

    def emit(self, s):
        self.out.append(s)

    def name(self, a):
        a &= M32
        if a in self.names:
            return self.names[a]
        for t in range(NCTI):
            base = cti_at(t)
            if base - 256 <= a < base + CTI_STRIDE:
                return "t%d%+d" % (t, a - base)
        return "?%08x" % a

    def drv_of_topo(self, a):
        return ((a & M32) - 180 - DRVS) // DRV_STRIDE

    def topo_init(self, em):
        self.emit("  topo init d%d" % self.drv_of_topo(em.reg[4]))
        return em.reg[4]

    def topo_destroy(self, em):
        self.emit("  topo destroy d%d" % self.drv_of_topo(em.reg[4]))

    # ---- Update's stubs --------------------------------------------------

    def f(self, a):
        return F32(struct.unpack("<f", struct.pack("<I", self.w(a)))[0])

    def putf(self, a, v):
        self.e.put32(a, f32_bits(v))

    def v4(self, a):
        return " ".join(fx(self.w(a + 4 * i)) for i in range(4))

    def by_driver(self, em):
        n = s32(em.reg[4])
        c = self.bydriver[n] if 0 <= n < NDRIVER else -1
        r = 0 if c < 0 else car_at(c)
        self.emit("  bydriver %d -> %s" % (n, self.name(r)))
        return r

    def cop_by(self, em, tag, which):
        car = em.reg[5] & M32
        k = self.coptab[(car - CARS) // CAR_STRIDE][which]
        r = 0 if k < 0 else COPS + COP_SIZE * k
        self.emit("  %s %s %s -> %s" % (tag, self.name(em.reg[4]),
                                        self.name(car), self.name(r)))
        return r

    def get_yaw(self, em):
        st = em.reg[4] & M32
        y = self.yaws[(st - CAR_STATE - CARS) // CAR_STRIDE]
        self.emit("  getyaw %s -> %s" % (self.name(st), fx(y)))
        em.fpr[0] = y

    def road_noise(self, em):
        p = em.reg[4] & M32
        self.emit("  noise %s %s %d -> %s" % (fx(self.w(p)), fx(self.w(p + 4)),
                                              s32(em.reg[5]), fx(self.noise)))
        em.fpr[0] = self.noise

    def set_bbox(self, em):
        tc = em.reg[4] & M32
        self.emit("  bbox %s pos %s r %s vel %s"
                  % (self.name(tc), self.v4(em.reg[5] & M32), fx(em.fpr[12]),
                     self.v4(em.reg[6] & M32)))
        for i, k in enumerate(self.cand):
            em.put32(tc + 32 + 4 * i, POLYS + POLY_SIZE * k)
        em.put32(tc + 672, len(self.cand))

    def get_elev(self, em):
        args = "".join("1" if em.reg[r] & M32 else "0" for r in (6, 7, 8))
        self.emit("  elev %s pt %s args %s -> %s"
                  % (self.name(em.reg[4]), self.v4(em.reg[5] & M32), args,
                     fx(self.elev)))
        em.fpr[0] = self.elev

    def constrain(self, em):
        to = em.reg[8] & M32
        self.emit("  constrain %s type %d two %d from %s to %s dist %s lift %s"
                  % (self.name(em.reg[4]), s32(em.reg[5]), s32(em.reg[6]),
                     self.v4(em.reg[7] & M32), self.v4(to), fx(em.fpr[12]),
                     fx(em.fpr[13])))
        with np.errstate(all="ignore"):
            for i in range(3):
                self.putf(to + 4 * i, self.f(to + 4 * i)
                          + F32(bits_f(self.cdelta[i])))
        return self.cret

    def in_shaft(self, em):
        tp, pt, out = (em.reg[r] & M32 for r in (4, 5, 6))
        k = (tp - POLYS) // POLY_SIZE
        with np.errstate(all="ignore"):
            d = self.f(tp + 112) * self.f(pt)
            d = d + self.f(tp + 116) * self.f(pt + 4)
            d = d + self.f(tp + 120) * self.f(pt + 8)
            d = d + self.f(tp + 124)
        self.putf(out, d)
        self.emit("  shaft %s at %s %s %s -> %d %s"
                  % (self.name(tp), fx(self.w(pt)), fx(self.w(pt + 4)),
                     fx(self.w(pt + 8)), self.inside[k], fx(f32_bits(d))))
        return self.inside[k]

    def car_box(self, em):
        car, mn, mx = (em.reg[r] & M32 for r in (4, 5, 6))
        c = (car - CARS) // CAR_STRIDE
        self.emit("  box %s" % self.name(car))
        for i in range(4):
            em.put32(mn + 4 * i, self.box[c][i])
            em.put32(mx + 4 * i, self.box[c][4 + i])

    def shake(self, em):
        m = em.reg[5] & M32
        self.emit("  shake view %d" % s32(em.reg[4]))
        self.emit("    " + " ".join(fx(self.w(m + 4 * i)) for i in range(16)))
        with np.errstate(all="ignore"):
            for i in range(3):
                self.putf(m + 48 + 4 * i, self.f(m + 48 + 4 * i)
                          + F32(bits_f(self.sdelta[i])))

    def fill(self, a, n):
        self.e.write(a, bytes([PATTERN]) * n)

    def w(self, a):
        return self.e.u32(a)

    def put16(self, a, v):
        self.e.mem[a] = v & 0xff
        self.e.mem[a + 1] = (v >> 8) & 0xff

    def reset(self):
        e = self.e
        self.fill(CAMS, CAM_SIZE * NCAM)
        self.fill(DRVS, DRV_STRIDE * NDRV)
        self.fill(CARS, CAR_STRIDE * NCAR)
        self.fill(CTIS, CTI_STRIDE * NCTI)
        self.fill(PLAYERS, PL_STRIDE * NPL)
        for i in range(NVIEWS):
            v = view_at(i)
            e.put32(v + V_CAMERA, 0)
            e.put32(v + V_LIST, v + V_LIST)
            e.put32(v + V_LIST + 4, v + V_LIST)
        e.put32(G_STOP, 0)
        e.put32(G_VIEWMODE, 0)
        e.put32(G_CTI, cti_at(0))
        self.fill(POLYS, POLY_SIZE * NPOLY)
        self.fill(COPS, COP_SIZE * NCOP)
        self.fill(PURS, PUR_SIZE * NPUR)
        self.inside = [0] * NPOLY
        self.cand = []
        self.bydriver = [-1] * NDRIVER
        self.coptab = [[-1, -1] for _ in range(NCAR)]
        self.yaws = [0] * NCAR
        self.noise = 0
        self.elev = 0
        self.cdelta = [0, 0, 0]
        self.cret = 0
        self.box = [[0] * 8 for _ in range(NCAR)]
        self.sdelta = [0, 0, 0]
        e.put32(G_COPMGR, 0)
        for n, v in self.tuning.items():
            self.tune(n, v)

    def tune(self, n, v):
        a, k = TUNE[n]
        if k == 2:
            self.put16(a, v)
        else:
            self.e.put32(a, v)

    # ---- the dumps -------------------------------------------------------

    def dump_drv(self, j):
        d = drv_at(j)
        w = self.w
        self.emit("  d%d type %d view %d en %d pview %s pcam %s player %s"
                  " carnot %08x dash %08x vtbl %s next %s prev %s"
                  % (j, s32(w(d + 8)), s32(w(d + 12)), s32(w(d + 16)),
                     self.name(w(d + 20)), self.name(w(d + 24)),
                     self.name(w(d + 28)), w(d + 32), w(d + 36),
                     self.name(w(d + 40)), self.name(w(d)),
                     self.name(w(d + 4))))
        self.emit("    car %s info %s pov %08x want %s lbp %s ilbp %08x"
                  " ilbh %s lba %04x"
                  % (self.name(w(d + 112)), self.name(w(d + 116)),
                     w(d + 120), fx(w(d + 124)), fx(w(d + 128)),
                     w(d + 132), fx(w(d + 136)), self.e.u16(d + 140)))
        self.emit("    yaw %08x %08x amount %s pitch %08x %08x"
                  " lag %s %s speed %s touch %s"
                  % (w(d + 144), w(d + 148), fx(w(d + 152)), w(d + 156),
                     w(d + 160), fx(w(d + 164)), fx(w(d + 168)),
                     fx(w(d + 172)), fx(w(d + 176))))
        self.emit("    dlag %08x lbspeed %s pf %08x cur %s adj %s hold %s"
                  " fract %s mult %s"
                  % (w(d + 884), fx(w(d + 888)), w(d + 992), fx(w(d + 972)),
                     fx(w(d + 976)), fx(w(d + 980)), fx(w(d + 984)),
                     fx(w(d + 988))))
        self.emit("    accel " + " ".join(fx(w(d + 892 + 4 * i))
                                          for i in range(20)))
        c = w(d + 24)
        if c:
            self.emit("    cam %s carnot %s dash %08x fd %s dof %s near %s"
                      " far %s" % (self.name(c), self.name(w(c + C_CARNOT)),
                                   w(c + C_DASH), fx(w(c + C_FD)),
                                   fx(w(c + C_DOF)), fx(w(c + C_NEAR)),
                                   fx(w(c + C_FAR))))

    def dump_views(self):
        parts = []
        for i in range(NVIEWS):
            head = view_at(i) + V_LIST
            n, names = self.w(head), []
            while n != head and len(names) < 20:
                names.append(self.name(n))
                n = self.w(n)
            if names:
                parts.append("v%d:%s" % (i, ",".join(names)))
        self.emit("  views %s mode %d" % (" ".join(parts) or "-",
                                          s32(self.w(G_VIEWMODE))))

    # ---- the ops ---------------------------------------------------------

    def vcall(self, j, slot, *args):
        e = self.e
        m = drv_at(j)
        vt = self.w(m + 40)
        delta = struct.unpack("<h", struct.pack("<H", e.u16(vt + slot - 4)))[0]
        fn = self.w(vt + slot)
        return e.call(fn, (m + delta) & M32, *args, limit=400000)

    def query(self, j):
        e = self.e
        d = drv_at(j)
        info = self.vcall(j, SLOTS["info"])
        povs = [self.name(self.vcall(j, SLOTS["pov"], i))
                for i in range(-1, 5)]
        ext = self.vcall(j, SLOTS["ext"])
        lb = self.vcall(j, SLOTS["lookback"])
        self.vcall(j, SLOTS["gap"])
        gap = e.fpr[0]
        car = self.vcall(j, SLOTS["car"])
        tgt = self.vcall(j, SLOTS["target"])
        self.emit("  q d%d info %s pov %s ext %d lb %d gap %s car %s tgt %s"
                  % (j, self.name(info), " ".join(povs), ext, lb, fx(gap),
                     self.name(car), self.name(tgt)))
        lba = e.call(GET_LBA, d) & 0xffff
        e.call(GET_SPEED, d)
        speed = e.fpr[0]
        lag = e.call(GET_LAG, d) & M32
        want = e.call(LOOKING_BACK, d)
        full = e.call(IS_LOOKING_BACK, d)
        self.emit("  a d%d lba %04x speed %s lag %08x want %d full %d"
                  % (j, lba, fx(speed), lag, want, full))

    def op(self, t):
        e = self.e
        c = t[0]
        if c == "B":
            self.reset()
            return
        if c == "C":
            e.call(CAM_CTOR, cam_at(int(t[1])), limit=200000)
        elif c == "c":
            e.put32(cam_at(int(t[1])) + CAM_FIELDS[t[2]], int(t[3], 16))
        elif c == "V":
            e.put32(view_at(int(t[1])) + V_CAMERA, cam_at(int(t[2])))
        elif c == "A":
            a = car_at(int(t[1]))
            e.put32(a + CAR_CTI, cti_at(int(t[2])))
            self.put16(a + CAR_ANGLE, int(t[3], 16))
            e.put32(a + CAR_BODYZ, int(t[4], 16))
            e.put32(a + CAR_FWD, int(t[5], 16))
            for i in range(4):
                e.put32(a + CAR_GPOS + 4 * i, int(t[6 + i], 16))
                e.put32(a + CAR_POS + 4 * i, int(t[10 + i], 16))
        elif c == "I":
            a = cti_at(int(t[1])) + CTI_CAMERA
            e.put32(a, int(t[2], 16))
            e.put32(a + 4, int(t[3], 16))
        elif c == "P":
            e.put32(cti_at(int(t[1])) + int(t[2]), int(t[3], 16))
        elif c == "G":
            e.put32(G_CTI, cti_at(int(t[1])))
        elif c == "L":
            e.put32(pl_at(int(t[1])) + PL_LOOKBACK, int(t[2], 16))
        elif c == "N":
            j, view, car, pov = int(t[1]), int(t[2]), int(t[3]), int(t[4])
            self.fill(drv_at(j), DRV_SIZE)
            e.fpr[12] = int(t[5], 16)
            e.call(DCM_CTOR, drv_at(j), view, car_at(car), pov,
                   int(t[6], 16), int(t[7], 16), int(t[8], 16), limit=400000)
            self.dump_drv(j)
            self.dump_views()
        elif c == "D":
            j = int(t[1])
            self.vcall(j, SLOTS["destroy"], 0)
            self.dump_drv(j)
            self.dump_views()
        elif c == "R":
            j = int(t[1])
            self.vcall(j, SLOTS["reset"])
            self.dump_drv(j)
        elif c == "X":
            d, seed = drv_at(int(t[1])), int(t[2], 16)
            for k, off in enumerate(UPDATE_WORDS):
                e.put32(d + off, scribble_word(seed, k))
        elif c == "S":
            e.call(SET_POV, drv_at(int(t[1])), s32(int(t[2], 16)))
        elif c == "F":
            j, f = int(t[1]), t[2]
            d = drv_at(j)
            if f == "car":
                v = int(t[3])
                e.put32(d + 112, 0 if v < 0 else car_at(v))
            elif f == "player":
                v = int(t[3])
                e.call(SET_PLAYER, d, 0 if v < 0 else pl_at(v))
            elif f == "lba":
                self.put16(d + 140, int(t[3], 16))
            else:
                e.put32(d + DRIVE_FIELDS[f], int(t[3], 16))
        elif c == "W":
            d, f, v = drv_at(int(t[1])), t[2], int(t[3], 16)
            if f == "speed":
                e.fpr[12] = v
                e.call(SET_SPEED, d)
            elif f == "lag":
                e.call(SET_LAG, d, s32(v))
            else:
                e.call(SET_LOOK, d, s32(v))
        elif c == "Q":
            self.query(int(t[1]))
        elif c == "M":
            e.put32(G_VIEWMODE, int(t[1]))
        elif c == "Z":
            e.put32(G_STOP, int(t[1]))
        elif c == "Y":
            a = int(t[1], 16)
            e.call(YAW, a, limit=200000)
            yaw = e.fpr[0]
            pitch = e.call(PITCH, a) & M32
            incar = e.call(INCAR, a) & M32
            self.emit("  y %04x yaw %s pitch %08x incar %08x"
                      % (a, fx(yaw), pitch, incar))
        elif c == "K":
            for i in range(8):
                e.put32(MATRIX + 4 * i, int(t[3 + i], 16))
            for i in range(8, 16):
                e.put32(MATRIX + 4 * i, 0)
            v = e.call(CALC_LB, car_at(int(t[1])), car_at(int(t[2])), MATRIX)
            self.emit("  k %04x" % (v & 0xffff))
        elif c == "E":
            a = car_at(int(t[1]))
            for i in range(4):
                e.put32(a + CAR_VELV + 4 * i, int(t[2 + i], 16))
                e.put32(a + CAR_ACC + 4 * i, int(t[6 + i], 16))
            for i in range(16):
                e.put32(a + CAR_BODY + 4 * i, int(t[10 + i], 16))
            e.put32(a + CAR_NWHEELS, int(t[26], 16))
            e.put32(a + CAR_MODE, int(t[27], 16))
        elif c == "z":
            e.put32(cti_at(int(t[1])) + CTI_ZDIM, int(t[2], 16))
        elif c == "T":
            self.tune(t[1], int(t[2], 16))
        elif c == "g":
            self.bydriver[int(t[1])] = int(t[2])
        elif c == "H":
            e.put32(G_COPMGR, COPMGR if int(t[1]) else 0)
        elif c == "o":
            k, pur, car = int(t[1]), int(t[2]), int(t[3])
            e.put32(COPS + COP_SIZE * k, 0 if pur < 0 else PURS + PUR_SIZE * pur)
            e.put32(COPS + COP_SIZE * k + 4, 0 if car < 0 else car_at(car))
        elif c == "u":
            car = int(t[2])
            e.put32(PURS + PUR_SIZE * int(t[1]) + 16,
                    0 if car < 0 else car_at(car))
        elif c == "O":
            self.coptab[int(t[1])] = [int(t[2]), int(t[3])]
        elif c == "a":
            self.yaws[int(t[1])] = int(t[2], 16)
        elif c == "n":
            self.noise = int(t[1], 16)
        elif c == "e":
            self.elev = int(t[1], 16)
        elif c == "p":
            k = int(t[1])
            a = POLYS + POLY_SIZE * k
            e.mem[a + 10] = int(t[2], 16) & 0xff
            e.mem[a + 11] = int(t[3], 16) & 0xff
            for i in range(4):
                e.put32(a + 112 + 4 * i, int(t[4 + i], 16))
            self.inside[k] = int(t[8], 16)
        elif c == "l":
            n = int(t[1])
            self.cand = [int(x) for x in t[2:2 + n]]
        elif c == "t":
            self.cdelta = [int(x, 16) for x in t[1:4]]
            self.cret = int(t[4], 16)
        elif c == "b":
            self.box[int(t[1])] = [int(x, 16) for x in t[2:10]]
        elif c == "s":
            self.sdelta = [int(x, 16) for x in t[1:4]]
        elif c == "U":
            j = int(t[1])
            self.vcall(j, SLOTS["update"])
            self.dump_drv(j)
            cam = self.w(drv_at(j) + 24)
            if cam:
                self.emit("    camera %s %s carnot %s dash %08x"
                          % (self.name(cam),
                             " ".join("%08x" % self.w(cam + 4 * i)
                                      for i in range(111)),
                             self.name(self.w(cam + C_CARNOT)),
                             self.w(cam + C_DASH)))
            self.emit("  g follow %d cgm %s"
                      % (s32(self.w(TUNE["CameraFollowThisCarInstead"][0])),
                         fx(self.w(TUNE["CamGlobalMultiplier"][0]))))
        else:
            raise SystemExit("bad op %r" % (t,))

    def run(self, scenarios):
        for i, sc in enumerate(scenarios):
            self.emit("B %d" % i)
            self.op(["B"])
            for ln in sc:
                self.emit("> " + ln[:40])
                self.op(ln.split())
        return self.out


# ================================================================ the build


def build_harness(tmp, name="drivecam_test"):
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


def M(name, rel, before, after=None):
    return (name, rel, before, after)


def D(name, line, after):
    """Drop `line`, found by the text that follows it."""
    return M(name, DRVC, line + after, after)


CTOR_LAGS = ("    d->DesiredAccelLag = 0.0f;\n", "    d->CurrentAccelLag = 0.0f;\n",
             "    d->CamCurrentAccel = 0.0f;\n", "    d->CamHoldLagTime = 0.0f;\n",
             "    d->CamLagAdjust = 0.0f;\n")


def lag_drops(prefix, names, tail):
    out = []
    for i, name in enumerate(names):
        out.append(D(prefix + name, CTOR_LAGS[i], "".join(CTOR_LAGS[i + 1:])
                     + tail))
    return out


LAG_NAMES = ("no_accel_lag", "no_cur_lag", "no_cur_accel", "no_hold",
             "no_adj")

MUTATIONS = [
    # the constructor
    M("ctor_type", DRVC, "viewID, CM_DRIVE);", "viewID, CM_BUMPER);"),
    M("ctor_no_vtbl", DRVC, "    d->base.vtbl = &DriveCameraMoverVtbl;\n", ""),
    D("ctor_no_lba", "    d->LookBackAngle = 0;\n",
      "    d->DesiredLookBackParam = 0.0f;\n"),
    D("ctor_no_lbp", "    d->LookBackParam = 0.0f;\n",
      "    d->iLookBackHeight = 0.0f;\n    d->CarToFollow"),
    D("ctor_no_ilbh", "    d->iLookBackHeight = 0.0f;\n", "    d->CarToFollow"),
    D("ctor_no_ilbp", "    d->iLookBackParam = 0;\n",
      "    d->LastBoomYaw = 0;\n    d->base.vtbl"),
    D("ctor_no_boomyaw", "    d->LastBoomYaw = 0;\n", "    d->base.vtbl"),
    M("ctor_yaw_steer", DRVC,
      "    d->LastCarYaw = car->State.Angle;\n    d->LastCarPitch",
      "    d->LastCarYaw = car->State.SteeringAngle;\n    d->LastCarPitch"),
    M("ctor_pitch_signed", DRVC,
      "(uint16_t)bASin(car->State.BodyMatrix.v0.z);\n    d->LastBoomPitch = 0;\n"
      "    topology_init",
      "bASin(car->State.BodyMatrix.v0.z);\n    d->LastBoomPitch = 0;\n"
      "    topology_init"),
    M("ctor_pitch_row", DRVC,
      "bASin(car->State.BodyMatrix.v0.z);\n    d->LastBoomPitch = 0;\n"
      "    topology_init",
      "bASin(car->State.BodyMatrix.v2.z);\n    d->LastBoomPitch = 0;\n"
      "    topology_init"),
    D("ctor_no_boompitch", "    d->LastBoomPitch = 0;\n", "    topology_init"),
    M("ctor_no_topo", DRVC, "    topology_init(&d->TheTopologyCoordinate);\n",
      ""),
    M("ctor_dlag", DRVC, "    d->DisableLag = disableLag;",
      "    d->DisableLag = 0;"),
    M("ctor_speed", DRVC, "    d->LookbackSpeed = lookbackSpeed;",
      "    d->LookbackSpeed = 4.0f;"),
    M("ctor_pf", DRVC, "    d->PerfectFocus = perfectFocus;",
      "    d->PerfectFocus = 1;"),
    M("ctor_lookback_float", DRVC,
      "    d->DesiredLookBackParam = lookBack ? 1.0f : 0.0f;\n    d->Desired",
      "    d->DesiredLookBackParam = (float)lookBack;\n    d->Desired"),
    M("ctor_lookback_off", DRVC,
      "    d->DesiredLookBackParam = lookBack ? 1.0f : 0.0f;\n    d->Desired",
      "    d->DesiredLookBackParam = 0.0f;\n    d->Desired"),
] + lag_drops("ctor_", LAG_NAMES, "    cam =") + [
    M("ctor_loop_short", DRVC,
      "    cam = d->base.pCamera;\n    for (i = 19; i >= 0; i--)",
      "    cam = d->base.pCamera;\n    for (i = 19; i > 0; i--)"),
    D("ctor_no_fract", "    d->CamTimeFract = 0.0f;\n",
      "    d->CamAdjustMultiplier = 1.0f;\n    d->LastCarSpeed"),
    M("ctor_mult", DRVC,
      "    d->CamAdjustMultiplier = 1.0f;\n    d->LastCarSpeed",
      "    d->CamAdjustMultiplier = 0.0f;\n    d->LastCarSpeed"),
    M("ctor_speed_vel", DRVC,
      "    d->LastCarSpeed = car->State.ForwardSpeed;\n    if",
      "    d->LastCarSpeed = car->State.VelocityMagnitude;\n    if"),
    M("ctor_no_freeze", DRVC,
      "    if (!CameraStopUpdating) {\n        cam->CarNotToRender = NULL;\n"
      "        cam->RenderDash = 0;\n",
      "    {\n        cam->CarNotToRender = NULL;\n"
      "        cam->RenderDash = 0;\n"),
    D("ctor_no_carnot", "        cam->CarNotToRender = NULL;\n",
      "        cam->RenderDash = 0;\n"),
    M("ctor_no_dash", DRVC,
      "        cam->CarNotToRender = NULL;\n        cam->RenderDash = 0;\n",
      "        cam->CarNotToRender = NULL;\n"),
    M("ctor_no_pov", DRVC, "    drive_cam_set_pov_index(d, povIndex);\n", ""),
    M("ctor_fallback_and", DRVC,
      "NumFullScreenPOVs == 0 || info->NumSplitScreenPOVs == 0)",
      "NumFullScreenPOVs == 0 && info->NumSplitScreenPOVs == 0)"),
    M("ctor_fallback_full", DRVC,
      "NumFullScreenPOVs == 0 || info->NumSplitScreenPOVs == 0)",
      "NumFullScreenPOVs == 0)"),
    M("ctor_fallback_split", DRVC,
      "(info->NumFullScreenPOVs == 0 || info->NumSplitScreenPOVs == 0)",
      "(info->NumSplitScreenPOVs == 0)"),
    M("ctor_fallback_le", DRVC, "NumFullScreenPOVs == 0 ||",
      "NumFullScreenPOVs <= 0 ||"),
    M("ctor_fallback_index", DRVC, "&CarTypeInfoArray[0].Camera;",
      "&CarTypeInfoArray[1].Camera;"),
    M("ctor_fallback_none", DRVC,
      "        d->pCameraInfo = &CarTypeInfoArray[0].Camera;\n",
      "        (void)0;\n"),
    M("ctor_touch", DRVC,
      "    d->TouchingGroundFactor = 1.0f;\n}\n\n// 0x0015c400",
      "    d->TouchingGroundFactor = 0.0f;\n}\n\n// 0x0015c400"),
    # the destructor
    M("dtor_no_vtbl", DRVC, "    m->vtbl = &DriveCameraMoverVtbl;\n", ""),
    M("dtor_no_freeze", DRVC,
      "    if (!CameraStopUpdating) {\n        cam->CarNotToRender = NULL;\n"
      "        cam->CurrentKey",
      "    {\n        cam->CarNotToRender = NULL;\n        cam->CurrentKey"),
    D("dtor_no_carnot", "        cam->CarNotToRender = NULL;\n",
      "        cam->CurrentKey.FocalDistance"),
    M("dtor_no_fd", DRVC, "        cam->CurrentKey.FocalDistance = 0.0f;\n",
      ""),
    M("dtor_no_dof", DRVC, "        cam->CurrentKey.DepthOfField = 0.0f;\n",
      ""),
    M("dtor_dash", DRVC, "        cam->CurrentKey.DepthOfField = 0.0f;\n",
      "        cam->CurrentKey.DepthOfField = 0.0f;\n"
      "        cam->RenderDash = 0;\n"),
    M("dtor_no_topo", DRVC,
      "    topology_destroy(&d->TheTopologyCoordinate);\n", ""),
    M("dtor_no_base", DRVC,
      "    topology_destroy(&d->TheTopologyCoordinate);\n"
      "    camera_mover_destroy(m);\n",
      "    topology_destroy(&d->TheTopologyCoordinate);\n"),
    M("dtor_base_first", DRVC, [
        ("    m->vtbl = &DriveCameraMoverVtbl;\n    if",
         "    camera_mover_destroy(m);\n    if"),
        ("    topology_destroy(&d->TheTopologyCoordinate);\n"
         "    camera_mover_destroy(m);\n",
         "    topology_destroy(&d->TheTopologyCoordinate);\n")]),
    # ResetState
    D("reset_no_lba", "    d->LookBackAngle = 0;\n", "    car = d->CarToFollow;\n"
      "    d->DesiredLookBackParam"),
    M("reset_no_want", DRVC,
      "    car = d->CarToFollow;\n    d->DesiredLookBackParam = 0.0f;\n",
      "    car = d->CarToFollow;\n"),
    D("reset_no_lbp", "    d->LookBackParam = 0.0f;\n",
      "    d->iLookBackHeight = 0.0f;\n    d->LastCarYaw"),
    D("reset_no_ilbh", "    d->iLookBackHeight = 0.0f;\n", "    d->LastCarYaw"),
    D("reset_no_yaw", "    d->LastCarYaw = car->State.Angle;\n",
      "    d->iLookBackParam"),
    D("reset_no_ilbp", "    d->iLookBackParam = 0;\n",
      "    d->LastBoomYaw = 0;\n    d->LastCarPitch"),
    D("reset_no_boomyaw", "    d->LastBoomYaw = 0;\n", "    d->LastCarPitch"),
    M("reset_pitch_signed", DRVC,
      "    d->LastCarPitch = (uint16_t)bASin(car->State.BodyMatrix.v0.z);\n"
      "    car = d->CarToFollow;",
      "    d->LastCarPitch = bASin(car->State.BodyMatrix.v0.z);\n"
      "    car = d->CarToFollow;"),
    D("reset_no_boompitch", "    d->LastBoomPitch = 0;\n",
      "    d->DesiredAccelLag"),
] + lag_drops("reset_", LAG_NAMES, "    for") + [
    M("reset_loop_short", DRVC,
      "    d->CamLagAdjust = 0.0f;\n    for (i = 19; i >= 0; i--)",
      "    d->CamLagAdjust = 0.0f;\n    for (i = 19; i > 0; i--)"),
    D("reset_no_fract", "    d->CamTimeFract = 0.0f;\n",
      "    d->CamAdjustMultiplier = 1.0f;\n    d->TouchingGroundFactor"),
    M("reset_mult", DRVC,
      "    d->CamAdjustMultiplier = 1.0f;\n    d->TouchingGroundFactor",
      "    d->CamAdjustMultiplier = 0.5f;\n    d->TouchingGroundFactor"),
    D("reset_no_touch", "    d->TouchingGroundFactor = 1.0f;\n",
      "    d->LastCarSpeed"),
    M("reset_speed_vel", DRVC,
      "    d->LastCarSpeed = car->State.ForwardSpeed;\n}",
      "    d->LastCarSpeed = car->State.VelocityMagnitude;\n}"),
    # Retail's ResetState leaves AmountToUseYawCorrection as Update left it.
    M("reset_amount", DRVC,
      "    d->LastBoomYaw = 0;\n    d->LastCarPitch = (uint16_t)",
      "    d->LastBoomYaw = 0;\n    d->AmountToUseYawCorrection = 0.0f;\n"
      "    d->LastCarPitch = (uint16_t)"),
    M("reset_dlag", DRVC,
      "    d->LastCarSpeed = car->State.ForwardSpeed;\n}",
      "    d->LastCarSpeed = car->State.ForwardSpeed;\n"
      "    d->DisableLag = 0;\n}"),
    # the points of view
    M("setpov_none", DRVC, "    d->POVIndex = index;",
      "    (void)d;\n    (void)index;"),
    M("getpov_mode", DRVC, "eGetCurrentViewMode() == 3) {",
      "eGetCurrentViewMode() == 2) {"),
    M("getpov_mode_ge", DRVC, "eGetCurrentViewMode() == 3) {",
      "eGetCurrentViewMode() >= 3) {"),
    M("getpov_split_le", DRVC, "        if (index < info->NumSplitScreenPOVs)",
      "        if (index <= info->NumSplitScreenPOVs)"),
    M("getpov_full_le", DRVC, "    if (index < info->NumFullScreenPOVs)",
      "    if (index <= info->NumFullScreenPOVs)"),
    M("getpov_split_count", DRVC,
      "        if (index < info->NumSplitScreenPOVs)",
      "        if (index < info->NumFullScreenPOVs)"),
    M("getpov_full_count", DRVC,
      "    if (index < info->NumFullScreenPOVs)",
      "    if (index < info->NumSplitScreenPOVs)"),
    M("getpov_split_array", DRVC,
      "            return &info->SplitScreenPOVArray[index];",
      "            return &info->FullScreenPOVArray[index];"),
    M("getpov_full_array", DRVC,
      "        return &info->FullScreenPOVArray[index];\n    return NULL;\n}",
      "        return &info->SplitScreenPOVArray[index];\n    return NULL;\n}"),
    M("getpov_unsigned", DRVC, "    if (index < info->NumFullScreenPOVs)",
      "    if ((unsigned)index < (unsigned)info->NumFullScreenPOVs)"),
    M("getpov_split_unsigned", DRVC,
      "        if (index < info->NumSplitScreenPOVs)",
      "        if ((unsigned)index < (unsigned)info->NumSplitScreenPOVs)"),
    M("getpov_split_null", DRVC,
      "            return &info->SplitScreenPOVArray[index];\n"
      "        return NULL;",
      "            return &info->SplitScreenPOVArray[index];\n"
      "        return &info->SplitScreenPOVArray[0];"),
    # the plain virtuals
    M("info_car", DRVC, "    return ((DriveCameraMover *)m)->pCameraInfo;",
      "    return &((DriveCameraMover *)m)->CarToFollow->pCarTypeInfo"
      "->Camera;"),
    M("car_info", DRVC, "    return ((DriveCameraMover *)m)->CarToFollow;",
      "    return (void *)((DriveCameraMover *)m)->pCameraInfo;"),
    M("target_pos", DRVC, "        return &car->State.GeometryPosition;",
      "        return &car->State.Position;"),
    M("target_nocar", DRVC, "    return &m->pCamera->CurrentKey.Target;",
      "    return &m->pCamera->CurrentKey.Position;"),
    M("target_camera", DRVC,
      "    if (car != NULL)\n        return &car->State.GeometryPosition;\n",
      "    (void)car;\n"),
    M("vt_ext_lb", DRVC,
      "    drive_cam_is_exterior_view,\n    drive_cam_is_looking_back,\n",
      "    drive_cam_is_looking_back,\n    drive_cam_is_exterior_view,\n"),
    M("vt_reset_base", DRVC, "    drive_cam_reset_state,\n",
      "    camera_mover_nothing,\n"),
    # the look back
    M("counts_any_player", DRVC,
      "    return p != NULL && p->PlayerSettings.Lookback == 0;",
      "    return p != NULL;"),
    M("counts_ne", DRVC, "p->PlayerSettings.Lookback == 0;",
      "p->PlayerSettings.Lookback != 0;"),
    M("counts_no_player", DRVC,
      "    return p != NULL && p->PlayerSettings.Lookback == 0;",
      "    return p == NULL || p->PlayerSettings.Lookback == 0;"),
    M("counts_le", DRVC, "p->PlayerSettings.Lookback == 0;",
      "p->PlayerSettings.Lookback <= 0;"),
    M("counts_not_one", DRVC, "p->PlayerSettings.Lookback == 0;",
      "p->PlayerSettings.Lookback != 1;"),
    M("ext_null_inside", DRVC,
      "    if (pov == NULL || pov->Type == POV_OUTSIDE)",
      "    if (pov != NULL && pov->Type == POV_OUTSIDE)"),
    M("ext_incar", DRVC, "    if (pov == NULL || pov->Type == POV_OUTSIDE)",
      "    if (pov == NULL || pov->Type == POV_INCAR)"),
    M("ext_no_counts", DRVC, "    return counts && 0.0f < d->LookBackParam;",
      "    return 0.0f < d->LookBackParam;"),
    M("ext_want", DRVC, "    return counts && 0.0f < d->LookBackParam;",
      "    return counts && 0.0f < d->DesiredLookBackParam;"),
    M("ext_le", DRVC, "    return counts && 0.0f < d->LookBackParam;",
      "    return counts && 0.0f <= d->LookBackParam;"),
    M("ext_no_look_back", DRVC,
      "    return counts && 0.0f < d->LookBackParam;",
      "    return counts && 0;"),
    M("ext_pov0", DRVC,
      "    const POV *pov = m->vtbl->GetPOV(m, d->POVIndex);\n"
      "    int counts",
      "    const POV *pov = m->vtbl->GetPOV(m, 0);\n    int counts"),
    M("lb_want", DRVC,
      "    return lookback_counts(m) && 0.0f < d->LookBackParam;",
      "    return lookback_counts(m) && 0.0f < d->DesiredLookBackParam;"),
    M("lb_le", DRVC,
      "    return lookback_counts(m) && 0.0f < d->LookBackParam;",
      "    return lookback_counts(m) && 0.0f <= d->LookBackParam;"),
    M("lb_no_counts", DRVC,
      "    return lookback_counts(m) && 0.0f < d->LookBackParam;",
      "    return 0.0f < d->LookBackParam;"),
    M("gap_near", DRVC, "(1.0f - p) * 0.7f + p * 3.0f",
      "(1.0f - p) * 0.75f + p * 3.0f"),
    M("gap_far", DRVC, "(1.0f - p) * 0.7f + p * 3.0f",
      "(1.0f - p) * 0.7f + p * 2.5f"),
    M("gap_lerp", DRVC, "(1.0f - p) * 0.7f + p * 3.0f",
      "0.7f + p * (3.0f - 0.7f)"),
    M("gap_no_counts", DRVC,
      "    if (lookback_counts(m))\n        p = d->LookBackParam;",
      "    p = d->LookBackParam;"),
    M("gap_want", DRVC, "        p = d->LookBackParam;",
      "        p = d->DesiredLookBackParam;"),
    M("gap_start", DRVC, "    float p = 0.0f;", "    float p = 1.0f;"),
    # the corrections
    M("yaw_wrap", DRVC, "    int32_t s = (int16_t)a;",
      "    int32_t s = a > 0x8000 ? (int32_t)a - 65536 : (int32_t)a;"),
    M("yaw_const", DRVC, "(float)mag * 0.000261f)", "(float)mag * 0.00026f)"),
    M("yaw_scale", DRVC, " * -1.9088f;", " * 1.9088f;"),
    M("yaw_no_sign", DRVC, "    return s < 0 ? -r : r;", "    return r;"),
    M("yaw_no_abs", DRVC, "    int32_t mag = s < 0 ? -s : s;",
      "    int32_t mag = s;"),
    M("yaw_args", DRVC, "bATan(1.0f, (float)mag * 0.000261f)",
      "bATan((float)mag * 0.000261f, 1.0f)"),
    M("signed_ge", DRVC, "    return a > 0x8000 ? (int32_t)a - 65536",
      "    return a >= 0x8000 ? (int32_t)a - 65536"),
    M("pitch_band", DRVC, "    if (s >= -7 && s <= 7)",
      "    if (s >= -8 && s <= 8)"),
    M("pitch_band_neg", DRVC, "    if (s >= -7 && s <= 7)",
      "    if (s >= -6 && s <= 7)"),
    M("pitch_band_pos", DRVC, "    if (s >= -7 && s <= 7)",
      "    if (s >= -7 && s <= 6)"),
    M("pitch_band_sign", DRVC, "    if (s >= -7 && s <= 7)\n        return -s;",
      "    if (s >= -7 && s <= 7)\n        return s;"),
    M("pitch_shift", DRVC, "    return -s / 8;", "    return -s >> 3;"),
    M("pitch_div4", DRVC, "    return -s / 8;", "    return -s / 4;"),
    M("incar_band", DRVC, "    if (s >= -1 && s <= 1)",
      "    if (s >= -2 && s <= 2)"),
    M("incar_shift", DRVC, "    return -s / 2;", "    return -s >> 1;"),
    M("incar_no_band", DRVC, "    if (s >= -1 && s <= 1)\n        return -s;\n",
      ""),
    M("incar_int16", DRVC, "    int32_t s = signed_angle(a);\n\n    if (s >= -1",
      "    int32_t s = (int16_t)a;\n\n    if (s >= -1"),
    # CalculateLookbackAngle
    M("lba_fwd", DRVC, "    if (0.7071f < fwd)", "    if (0.7f < fwd)"),
    M("lba_fwd_le", DRVC, "    if (0.7071f < fwd)", "    if (0.7071f <= fwd)"),
    M("lba_back", DRVC, "    if (fwd < -0.7071f)", "    if (fwd < -0.7f)"),
    M("lba_back_le", DRVC, "    if (fwd < -0.7071f)", "    if (fwd <= -0.7071f)"),
    M("lba_side_le", DRVC, "    if (side < 0.0f)", "    if (side <= 0.0f)"),
    M("lba_side_swap", DRVC, "        return 0x4000;\n    return 0xc000;",
      "        return 0xc000;\n    return 0x4000;"),
    M("lba_side_row", DRVC,
      "    side = (m->v1.x * d.x + m->v1.y * d.y) + m->v1.z * d.z;",
      "    side = (m->v2.x * d.x + m->v2.y * d.y) + m->v2.z * d.z;"),
    M("lba_fwd_w", DRVC,
      "    fwd = (m->v0.x * d.x + m->v0.y * d.y) + m->v0.z * d.z;",
      "    fwd = (m->v0.x * d.x + m->v0.y * d.y) + m->v0.w * d.z;"),
    M("lba_dir", DRVC,
      "    d.x = to->State.Position.x - from->State.Position.x;",
      "    d.x = from->State.Position.x - to->State.Position.x;"),
    M("lba_gpos", DRVC,
      "    d.y = to->State.Position.y - from->State.Position.y;",
      "    d.y = to->State.GeometryPosition.y"
      " - from->State.GeometryPosition.y;"),
    M("lba_no_norm", DRVC, "    d.x *= inv;\n    d.y *= inv;\n    d.z *= inv;\n",
      ""),
    M("lba_sum_order", DRVC,
      "sqrtf((d.x * d.x + d.y * d.y) + d.z * d.z);",
      "sqrtf(d.x * d.x + (d.y * d.y + d.z * d.z));"),
    M("lba_dot_order", DRVC,
      "    fwd = (m->v0.x * d.x + m->v0.y * d.y) + m->v0.z * d.z;",
      "    fwd = m->v0.x * d.x + (m->v0.y * d.y + m->v0.z * d.z);"),
    M("lba_divide", DRVC,
      "    inv = 1.0f / sqrtf((d.x * d.x + d.y * d.y) + d.z * d.z);\n"
      "    d.x *= inv;\n    d.y *= inv;\n    d.z *= inv;\n",
      "    inv = sqrtf((d.x * d.x + d.y * d.y) + d.z * d.z);\n"
      "    d.x /= inv;\n    d.y /= inv;\n    d.z /= inv;\n"),
    # the accessors
    M("acc_lba", DRVC, "    return d->LookBackAngle;",
      "    return (uint16_t)d->LastCarYaw;"),
    M("acc_speed_get", DRVC, "    return d->LookbackSpeed;",
      "    return d->LastCarSpeed;"),
    M("acc_speed_set", DRVC, "    d->LookbackSpeed = speed;",
      "    d->LastCarSpeed = speed;"),
    M("acc_lag_get", DRVC, "    return d->DisableLag;",
      "    return d->PerfectFocus;"),
    M("acc_lag_set", DRVC, "    d->DisableLag = lag;",
      "    d->DisableLag = lag != 0;"),
    M("acc_want_le", DRVC, "    return 0.0f < d->DesiredLookBackParam;",
      "    return 0.0f <= d->DesiredLookBackParam;"),
    M("acc_want_lbp", DRVC, "    return 0.0f < d->DesiredLookBackParam;",
      "    return 0.0f < d->LookBackParam;"),
    M("acc_set_float", DRVC, "    d->DesiredLookBackParam = on ? 1.0f : 0.0f;",
      "    d->DesiredLookBackParam = (float)on;"),
    M("acc_set_lbp", DRVC, "    d->DesiredLookBackParam = on ? 1.0f : 0.0f;",
      "    d->LookBackParam = on ? 1.0f : 0.0f;"),
    M("acc_full_ge", DRVC, "    return d->DesiredLookBackParam == 1.0f;",
      "    return d->DesiredLookBackParam >= 1.0f;"),
    M("acc_full_lbp", DRVC, "    return d->DesiredLookBackParam == 1.0f;",
      "    return d->LookBackParam == 1.0f;"),
    # GetLookbackCar
    M("glb_iscop_one", DRVC, "    *isCop = 0;\n    if (pCopManager == NULL)",
      "    *isCop = 1;\n    if (pCopManager == NULL)"),
    M("glb_iscop_zero", DRVC, "            *isCop = 1;\n", "            *isCop = 0;\n"),
    M("glb_no_pursuit_test", DRVC,
      "        if (cop->pMyPursuit != NULL) {\n"
      "            r = cop->pMyPursuit->pChasedCar;\n"
      "            *isCop = 1;\n        }\n",
      "        r = cop->pMyPursuit->pChasedCar;\n        *isCop = 1;\n"),
    M("glb_chased_mycar", DRVC, "            r = cop->pMyPursuit->pChasedCar;",
      "            r = cop->pMyCar;"),
    M("glb_chase_null", DRVC, "            r = cop->pMyCar;", "            r = NULL;"),
    M("glb_no_cm_test", DRVC,
      "    if (pCopManager == NULL)\n        return NULL;\n    cop =",
      "    cop ="),
    # the wall push
    M("wall_two_sided", DRVC, "TOPOLOGY_CONSTRAIN_BY_SCALE, 1, from",
      "TOPOLOGY_CONSTRAIN_BY_SCALE, 0, from"),
    M("wall_dist", DRVC, "from, &c, 0.01f,", "from, &c, 0.02f,"),
    M("wall_lift", DRVC, "                       1.0f);\n    push.x",
      "                       0.5f);\n    push.x"),
    M("wall_from_eye", DRVC, "TOPOLOGY_CONSTRAIN_BY_SCALE, 1, from, &c,",
      "TOPOLOGY_CONSTRAIN_BY_SCALE, 1, eye, &c,"),
    M("wall_push_x", DRVC, "    push.x = c.x - eye->x;", "    push.x = eye->x - c.x;"),
    M("wall_push_y", DRVC, "    push.y = c.y - eye->y;", "    push.y = c.y - eye->x;"),
    M("wall_push_z", DRVC, "    push.z = c.z - eye->z;", "    push.z = c.z;"),
    M("wall_iters_2", DRVC, "iter < 3; iter++", "iter < 2; iter++"),
    M("wall_iters_4", DRVC, "iter < 3; iter++", "iter < 4; iter++"),
    M("wall_probe_x", DRVC, "        probe.x = eye->x + push.x;",
      "        probe.x = eye->x;"),
    M("wall_probe_y", DRVC, "        probe.y = eye->y + push.y;",
      "        probe.y = eye->y - push.y;"),
    M("wall_probe_z", DRVC, "        probe.z = eye->z + push.z;",
      "        probe.z = eye->z;"),
    M("wall_poly_first", DRVC, "for (i = 0; i < tc->TotalNumTrackPolygons; i++)",
      "for (i = 1; i < tc->TotalNumTrackPolygons; i++)"),
    M("wall_poly_last", DRVC, "for (i = 0; i < tc->TotalNumTrackPolygons; i++)",
      "for (i = 0; i < tc->TotalNumTrackPolygons - 1; i++)"),
    M("wall_through", DRVC,
      "            if (TerrainTypeInfoTable[tp->TheTerrainType]\n"
      "                    .ShouldCameraGoThroughIt)\n                continue;\n",
      ""),
    M("wall_through_inv", DRVC, "                    .ShouldCameraGoThroughIt)",
      "                    .ShouldCameraGoThroughIt == 0)"),
    M("wall_shaft_ignored", DRVC,
      "            if (!trackpolygon_point_in_shaft(tp, &probe, &dist))\n"
      "                continue;\n",
      "            trackpolygon_point_in_shaft(tp, &probe, &dist);\n"),
    M("wall_shaft_eye", DRVC, "trackpolygon_point_in_shaft(tp, &probe, &dist)",
      "trackpolygon_point_in_shaft(tp, eye, &dist)"),
    M("wall_flag_bit", DRVC, "if (tp->Flags & 2)", "if (tp->Flags & 1)"),
    M("wall_gap_const", DRVC, "                gap = 0.7f;", "                gap = 0.75f;"),
    M("wall_gap_nogap", DRVC, "                gap = m->vtbl->GetWallGap(m);",
      "                gap = 0.7f;"),
    M("wall_dist_neg", DRVC, "if (!(0.0f <= dist) || !(dist < gap))",
      "if (!(-1.0f <= dist) || !(dist < gap))"),
    M("wall_dist_gap", DRVC, "if (!(0.0f <= dist) || !(dist < gap))",
      "if (!(0.0f <= dist) || !(dist < gap + 0.5f))"),
    M("wall_k", DRVC, "            k = gap - dist;", "            k = dist - gap;"),
    M("wall_acc_x", DRVC, "acc.x = tp->Normal.x * k + acc.x;",
      "acc.x = tp->Normal.x * k;"),
    M("wall_acc_y", DRVC, "acc.y = tp->Normal.y * k + acc.y;",
      "acc.y = tp->Normal.x * k + acc.y;"),
    M("wall_acc_z", DRVC, "acc.z = tp->Normal.z * k + acc.z;",
      "acc.z = tp->Normal.z + acc.z;"),
    M("wall_acc_pad", DRVC, "acc.pad = tp->PlaneDistance * k + acc.pad;",
      "acc.pad = 0.0f;"),
    M("wall_no_count", DRVC, "            n++;\n", ""),
    M("wall_no_break", DRVC, "        if (n == 0)\n            break;\n", ""),
    M("wall_continue", DRVC, "            break;\n        {\n",
      "            continue;\n        {\n"),
    M("wall_inv", DRVC, "float inv = 1.0f / (float)n;", "float inv = 1.0f;"),
    M("wall_push_add_x", DRVC, "push.x = acc.x * inv + push.x;",
      "push.x = acc.x * inv;"),
    M("wall_push_add_y", DRVC, "push.y = acc.y * inv + push.y;",
      "push.y = acc.y + push.y;"),
    M("wall_push_add_z", DRVC, "push.z = acc.z * inv + push.z;",
      "push.z = acc.z * inv - push.z;"),
    M("wall_out_pad", DRVC, "    *out = push;\n    out->pad = 0.0f;\n",
      "    *out = push;\n"),
    # the look-at offset
    M("look_up_down", DRVC, "    up.z = 1.0f;\n    up.pad = 0.0f;\n"
      "    eCreateLookAtMatrix(&l",
      "    up.z = -1.0f;\n    up.pad = 0.0f;\n    eCreateLookAtMatrix(&l"),
    M("look_up_x", DRVC, "    up.x = 0.0f;\n    up.y = 0.0f;\n    up.z = 1.0f;",
      "    up.x = 0.25f;\n    up.y = 0.0f;\n    up.z = 1.0f;"),
    M("look_t_inverse", DRVC, "    eMulVector3(&t, &l, target);",
      "    eMulVector3(&t, &li, target);"),
    M("look_t2_forward", DRVC, "    eMulVector3(&t2, &li, &t);",
      "    eMulVector3(&t2, &l, &t);"),
    M("look_off_y", DRVC, "    t.y = t.y - t.z * off->y;",
      "    t.y = t.y + t.z * off->y;"),
    M("look_off_x", DRVC, "    t.x = t.x - t.z * off->x;",
      "    t.x = t.x - t.z * off->y;"),
    M("look_off_depth", DRVC, "    t.x = t.x - t.z * off->x;",
      "    t.x = t.x - t.x * off->x;"),
    M("look_final", DRVC, "    eCreateLookAtMatrix(out, eye, &t2, &up);",
      "    eCreateLookAtMatrix(out, eye, target, &up);"),
    # the car to follow
    M("follow_default_inv", DRVC, "    if (CameraFollowDefaultCar != 0)\n",
      "    if (CameraFollowDefaultCar == 0)\n"),
    M("follow_no_first", DRVC,
      "    car = world_get_car_by_driver_number(CameraFollowThisCarInstead);\n"
      "    if (car != NULL)\n        return car;\n    while",
      "    while"),
    M("follow_gt", DRVC, "while (CameraFollowThisCarInstead >= 0)",
      "while (CameraFollowThisCarInstead > 0)"),
    M("follow_dec_late", DRVC,
      "        CameraFollowThisCarInstead--;\n"
      "        car = world_get_car_by_driver_number(CameraFollowThisCarInstead);\n",
      "        car = world_get_car_by_driver_number(CameraFollowThisCarInstead);\n"
      "        CameraFollowThisCarInstead--;\n"),
    M("follow_fallback", DRVC, "    }\n    return d->CarToFollow;\n}",
      "    }\n    return NULL;\n}"),
    # the lag
    M("lag_gm_kept", DRVC, "    CamGlobalMultiplier = 1.0f;\n    a =", "    a ="),
    M("lag_velocity", DRVC, "    a = car->State.Acceleration;",
      "    a = car->State.Velocity;"),
    M("lag_no_transpose", DRVC,
      "    eTransposeMatrix(&t, &car->State.BodyMatrix);\n"
      "    eMulVector3(&a, &t, &a);",
      "    eMulVector3(&a, &car->State.BodyMatrix, &a);"),
    M("lag_decel_ratio", DRVC,
      "if ((a.x * CamDecelScaleRatio) * gm < CamRangeCheckD * gm)",
      "if ((a.x * CamAccelScaleRatio) * gm < CamRangeCheckD * gm)"),
    M("lag_decel_sample", DRVC, "sample = a.x * (CamDecelScaleRatio * gm);",
      "sample = a.x * (CamAccelScaleRatio * gm);"),
    M("lag_decel_sign", DRVC, "        sign = -1;\n", "        sign = 1;\n"),
    M("lag_accel_range", DRVC,
      "} else if (CamRangeCheckA * gm < (a.x * CamAccelScaleRatio) * gm) {",
      "} else if (CamRangeCheckD * gm < (a.x * CamAccelScaleRatio) * gm) {"),
    M("lag_accel_sample", DRVC, "sample = a.x * (CamAccelScaleRatio * gm);",
      "sample = a.x;"),
    M("lag_accel_sign", DRVC, "        sign = 1;\n        sample",
      "        sign = 0;\n        sample"),
    M("lag_mid_sample", DRVC, "        sample = 0.0f;\n        sign = 0;",
      "        sample = a.x;\n        sign = 0;"),
    M("lag_no_fract", DRVC, "f = dt * 60.0f + d->CamTimeFract;",
      "f = dt * 60.0f;"),
    M("lag_fract_zero", DRVC, "d->CamTimeFract = f - (float)n;",
      "d->CamTimeFract = 0.0f;"),
    M("lag_n_round", DRVC, "    n = (int32_t)f;", "    n = (int32_t)(f + 0.5f);"),
    M("lag_shift_short", DRVC, "for (i = 19; i > 0; i--)",
      "for (i = 18; i > 0; i--)"),
    M("lag_sample_lost", DRVC, "        d->CamLastAccel[0] = sample;",
      "        d->CamLastAccel[0] = 0.0f;"),
    M("lag_accel_cur_le", DRVC, "if (!(0.0f < d->CamCurrentAccel)) {",
      "if (!(0.0f <= d->CamCurrentAccel)) {"),
    M("lag_accel_sum0", DRVC, "                sum = sample;\n                ok = 1;",
      "                sum = 0.0f;\n                ok = 1;"),
    M("lag_accel_head", DRVC,
      "                    if (d->CamLastAccel[i] < lim)\n"
      "                        ok = 0;\n                }\n",
      "                    if (d->CamLastAccel[i] < 0.0f)\n"
      "                        ok = 0;\n                }\n"),
    M("lag_accel_tail", DRVC,
      "                        if (lim < d->CamLastAccel[i])\n"
      "                            ok = 0;\n            }\n        } else if",
      "                        if (0.0f < d->CamLastAccel[i])\n"
      "                            ok = 0;\n            }\n        } else if"),
    M("lag_tail_short", DRVC,
      "                    for (i = 10; i < 20; i++)\n"
      "                        if (lim < d->CamLastAccel[i])",
      "                    for (i = 10; i < 19; i++)\n"
      "                        if (lim < d->CamLastAccel[i])"),
    M("lag_decel_cur_le", DRVC, "if (!(d->CamCurrentAccel < 0.0f)) {",
      "if (!(d->CamCurrentAccel <= 0.0f)) {"),
    M("lag_decel_ok_one", DRVC, "                ok = -1;\n",
      "                ok = 1;\n"),
    M("lag_decel_head", DRVC,
      "                    if (lim < d->CamLastAccel[i])\n"
      "                        ok = 0;\n                }\n",
      "                    if (0.0f < d->CamLastAccel[i])\n"
      "                        ok = 0;\n                }\n"),
    M("lag_decel_tail", DRVC,
      "                        if (d->CamLastAccel[i] < lim)\n"
      "                            ok = 0;\n            }\n        } else {",
      "                        if (d->CamLastAccel[i] < 0.0f)\n"
      "                            ok = 0;\n            }\n        } else {"),
    M("lag_range_kept", DRVC,
      "&& CamRangeCheckD * gm < d->CamLastAccel[i])\n"
      "                    d->CamLagAdjust = 0.0f;",
      "&& CamRangeCheckD * gm < d->CamLastAccel[i])\n"
      "                    d->CamLagAdjust = d->CamLagAdjust;"),
    M("lag_range_or", DRVC,
      "if (d->CamLastAccel[i] < CamRangeCheckA * gm\n                    &&",
      "if (d->CamLastAccel[i] < CamRangeCheckA * gm\n                    ||"),
    M("lag_range_from0", DRVC,
      "            for (i = 1; i < 10; i++)\n"
      "                if (d->CamLastAccel[i] < CamRangeCheckA",
      "            for (i = 0; i < 10; i++)\n"
      "                if (d->CamLastAccel[i] < CamRangeCheckA"),
    M("lag_ok_inv", DRVC, "        if (!ok)\n            continue;",
      "        if (ok)\n            continue;"),
    M("lag_sum_scale", DRVC, "d->CamLagAdjust = sum * 0.1f;",
      "d->CamLagAdjust = sum * 0.125f;"),
    M("lag_yaw_signed", DRVC,
      "        if (k < 0.0f)\n            k = -k;\n        k = 1.0f - k",
      "        k = 1.0f - k"),
    M("lag_yaw_plus", DRVC, "k = 1.0f - k * CamYawAdjuster;",
      "k = 1.0f + k * CamYawAdjuster;"),
    M("lag_yaw_unclamped", DRVC,
      "        if (k < 0.0f)\n            k = 0.0f;\n"
      "        d->CamLagAdjust = d->CamLagAdjust * k;",
      "        d->CamLagAdjust = d->CamLagAdjust * k;"),
    M("lag_yaw_unused", DRVC,
      "        d->CamLagAdjust = d->CamLagAdjust * k;\n        if (CamAccelCap",
      "        if (CamAccelCap"),
    M("lag_no_cap_hi", DRVC,
      "        if (CamAccelCap * gm < d->CamLagAdjust)\n"
      "            d->CamLagAdjust = CamAccelCap * gm;\n", ""),
    M("lag_no_cap_lo", DRVC,
      "        if (d->CamLagAdjust < CamDecelCap * gm)\n"
      "            d->CamLagAdjust = CamDecelCap * gm;\n", ""),
    M("lag_hold_kept", DRVC, "        d->CamHoldLagTime = 0.0f;\n        if (d->DisableLag",
      "        if (d->DisableLag"),
    M("lag_disable_any_speed", DRVC,
      "if (d->DisableLag != 0 && 5.0f < car->State.ForwardSpeed) {",
      "if (d->DisableLag != 0) {"),
    M("lag_disable_speed", DRVC, "5.0f < car->State.ForwardSpeed) {",
      "15.0f < car->State.ForwardSpeed) {"),
    M("lag_mode0", DRVC, "            if (car->State.DriverMode == 1)",
      "            if (car->State.DriverMode == 0)"),
    M("lag_mode_scale", DRVC, "d->CamLagAdjust = d->CamLagAdjust * 0.75f;",
      "d->CamLagAdjust = d->CamLagAdjust * 0.5f;"),
    M("lag_disable_mult", DRVC, "            d->CamAdjustMultiplier = CamDisableAdjust;\n",
      "            d->CamAdjustMultiplier = 1.0f;\n"),
    M("lag_disable_unscaled", DRVC,
      "            d->CamLagAdjust = d->CamLagAdjust * CamDisableAdjust;\n", ""),
    M("lag_mult_one", DRVC, "            d->CamAdjustMultiplier = 1.0f;\n        }\n    }",
      "            d->CamAdjustMultiplier = 0.5f;\n        }\n    }"),
    M("lag_f_frame", DRVC, "    f = dt * 60.0f;\n    if (lag == 0.0f) {",
      "    f = 1.0f;\n    if (lag == 0.0f) {"),
    M("lag_back_nomult", DRVC,
      "float step = (CamBackAdjust * f) * d->CamAdjustMultiplier;",
      "float step = CamBackAdjust * f;"),
    M("lag_quicker_neg", DRVC, "if (CamBackAdjustQuicker < cur)",
      "if (CamBackAdjustQuicker < -cur)"),
    M("lag_quicker_single", DRVC, "d->CamCurrentAccel = cur - (step + step);",
      "d->CamCurrentAccel = cur - step;"),
    M("lag_back_pos_over", DRVC,
      "d->CamCurrentAccel = step < cur ? cur - step : 0.0f;",
      "d->CamCurrentAccel = cur - step;"),
    M("lag_back_neg_over", DRVC,
      "d->CamCurrentAccel = cur < -step ? cur + step : 0.0f;",
      "d->CamCurrentAccel = cur + step;"),
    M("lag_pos_hold_skip", DRVC, "        if (0.0f < diff)\n            goto hold;",
      "        if (0.0f < diff)\n            goto slowed;"),
    M("lag_pos_near", DRVC, "if (-0.4f < diff)", "if (-0.5f < diff)"),
    M("lag_pos_near_k", DRVC, "* f) * 0.3f;", "* f) * 0.35f;"),
    M("lag_pos_mid", DRVC, "else if (-1.0f < diff)", "else if (-1.5f < diff)"),
    M("lag_pos_mid_k", DRVC, "* f) * 0.6f;", "* f) * 0.5f;"),
    M("lag_pos_far", DRVC,
      "                cur + (CamAdjustment * d->CamAdjustMultiplier) * f;\n"
      "    } else if",
      "                cur + CamAdjustment * f;\n    } else if"),
    M("lag_walk", DRVC, "} else if (car->State.ForwardSpeed * 2.237f < 5.0f) {",
      "} else if (car->State.ForwardSpeed * 2.237f < 6.0f) {"),
    M("lag_walk_cur", DRVC,
      "        d->CamLagAdjust = 0.0f;\n    } else {\n        cur = d->CamCurrentAccel;",
      "        d->CamCurrentAccel = 0.0f;\n    } else {\n        cur = d->CamCurrentAccel;"),
    M("lag_neg_hold_inv", DRVC, "        if (cur < lag)\n            goto hold;",
      "        if (lag < cur)\n            goto hold;"),
    M("lag_neg_nomult", DRVC,
      "cur + (-CamAdjustment * d->CamAdjustMultiplier) * f;",
      "cur + (-CamAdjustment) * f;"),
    M("lag_hold_rate", DRVC, "d->CamHoldLagTime = d->CamHoldLagTime + dt;",
      "d->CamHoldLagTime = d->CamHoldLagTime + 2.0f * dt;"),
    M("lag_hold_nosign", DRVC,
      "if (CamHoldTimeout < d->CamHoldLagTime || sign == 0)",
      "if (CamHoldTimeout < d->CamHoldLagTime)"),
    M("lag_hold_sign1", DRVC, "|| sign == 0)", "|| sign != 1)"),
    M("lag_hold_notime", DRVC,
      "if (CamHoldTimeout < d->CamHoldLagTime || sign == 0)",
      "if (sign == 0)"),
    M("lag_speed_mph", DRVC,
      "k = CamSpeedAdjust - car->State.ForwardSpeed * 2.237f;",
      "k = CamSpeedAdjust - car->State.ForwardSpeed;"),
    M("lag_speed_unclamped", DRVC,
      "    if (k < 0.0f)\n        k = 0.0f;\n    k = k / CamSpeedAdjust;",
      "    k = k / CamSpeedAdjust;"),
    M("lag_speed_recip", DRVC, "k = k / CamSpeedAdjust;",
      "k = k * (1.0f / CamSpeedAdjust);"),
    M("lag_disable_ret", DRVC,
      "    if (d->DisableLag != 0)\n        return 0.0f;\n    return (d->CamCurrentAccel",
      "    return (d->CamCurrentAccel"),
    M("lag_ret_order", DRVC,
      "return (d->CamCurrentAccel * CamLagMultiplier) * k;",
      "return d->CamCurrentAccel * (CamLagMultiplier * k);"),
    # the update: the look back's rate and the POV
    M("up_dt_real", DRVC, "    float dt = WorldTimeElapsed;",
      "    float dt = RealTimeElapsed;"),
    M("up_rate_one", DRVC, "    rate = d->LookbackSpeed;\n", "    rate = 1.0f;\n"),
    M("up_lb_nocm", DRVC,
      "if (pCopManager != NULL && d->DesiredLookBackParam == 1.0f && !canLB) {",
      "if (d->DesiredLookBackParam == 1.0f && !canLB) {"),
    M("up_lb_any_want", DRVC,
      "&& d->DesiredLookBackParam == 1.0f && !canLB) {",
      "&& 0.0f < d->DesiredLookBackParam && !canLB) {"),
    M("up_lb_canlb", DRVC, "== 1.0f && !canLB) {\n        lbCar",
      "== 1.0f) {\n        lbCar"),
    M("up_cop_rate", DRVC, "rate = 1.3333334f;", "rate = 1.25f;"),
    M("up_cop_always", DRVC, "        if (isCop)\n            rate = 1.3333334f;",
      "        rate = 1.3333334f;"),
    M("up_ilbp_kept", DRVC,
      "        d->iLookBackParam = 0;\n        d->iLookBackHeight = 0.0f;\n    }\n",
      "        d->iLookBackHeight = 0.0f;\n    }\n"),
    M("up_ilbh_kept", DRVC,
      "        d->iLookBackHeight = 0.0f;\n    }\n    if (d->LookBackParam",
      "    }\n    if (d->LookBackParam"),
    M("up_lbp_up_nodt", DRVC, "d->LookBackParam = d->LookBackParam + rate * dt;",
      "d->LookBackParam = d->LookBackParam + rate;"),
    M("up_lbp_up_over", DRVC,
      "        if (d->DesiredLookBackParam < d->LookBackParam)\n"
      "            d->LookBackParam = d->DesiredLookBackParam;\n    } else if",
      "    } else if"),
    M("up_lbp_down_fast", DRVC, "d->LookBackParam = d->LookBackParam - rate * dt;",
      "d->LookBackParam = d->LookBackParam - rate * dt * 2.0f;"),
    M("up_lbp_down_over", DRVC,
      "        if (d->LookBackParam < d->DesiredLookBackParam)\n"
      "            d->LookBackParam = d->DesiredLookBackParam;\n    }\n\n    pov",
      "    }\n\n    pov"),
    M("up_pov_idx1", DRVC, "        drive_cam_set_pov_index(d, 0);",
      "        drive_cam_set_pov_index(d, 1);"),
    M("up_pov_idx_kept", DRVC,
      "        drive_cam_set_pov_index(d, 0);\n"
      "        pov = m->vtbl->GetPOV(m, d->POVIndex);",
      "        pov = m->vtbl->GetPOV(m, 0);"),
    M("up_round_minus", DRVC,
      "(bCosBam((uint16_t)(int32_t)(d->LookBackParam * 32768.0f)) + 1.0f)",
      "(bCosBam((uint16_t)(int32_t)(d->LookBackParam * 32768.0f)) - 1.0f)"),
    M("up_round_quarter", DRVC, "        * 0.5f;\n    if (DriveUseTweakables) {",
      "        * 0.25f;\n    if (DriveUseTweakables) {"),
    M("up_round_scale", DRVC, "d->LookBackParam * 32768.0f)) + 1.0f)",
      "d->LookBackParam * 16384.0f)) + 1.0f)"),
    # the tweakables and the POV's words
    M("up_tw_nolag", DRVC,
      "        if (pov->Type == POV_OUTSIDE)\n            lag = DriveLag + boomLag;",
      "        if (pov->Type == POV_OUTSIDE)\n            lag = DriveLag;"),
    M("up_tw_lag_pov", DRVC, "        lag = DriveLag;\n        if",
      "        lag = pov->Lag;\n        if"),
    M("up_tw_angle", DRVC, "        angle = DriveAngle;", "        angle = pov->Angle;"),
    M("up_tw_max", DRVC, "        maxAngle = DriveMaxAngle;",
      "        maxAngle = pov->MaxAngle;"),
    M("up_tw_height", DRVC, "        height = DriveHeight;",
      "        height = pov->Height;"),
    M("up_tw_lat", DRVC, "        lat = DriveLatOffset;",
      "        lat = pov->LatOffset;"),
    M("up_pov_lag_round", DRVC, "lag = pov->Lag + boomLag * (1.0f - round);",
      "lag = pov->Lag + boomLag;"),
    M("up_pov_lag_inside", DRVC, "        else\n            lag = pov->Lag;",
      "        else\n            lag = pov->Lag + boomLag;"),
    M("up_pov_angle", DRVC, "        angle = pov->Angle;\n        height",
      "        angle = pov->MaxAngle;\n        height"),
    M("up_pov_height", DRVC, "        height = pov->Height;\n        lat",
      "        height = pov->Lag;\n        lat"),
    M("up_pov_lat", DRVC, "        lat = pov->LatOffset;\n        maxAngle",
      "        lat = 0.0f;\n        maxAngle"),
    M("up_pov_max", DRVC, "        maxAngle = pov->MaxAngle;\n    }",
      "        maxAngle = pov->Angle;\n    }"),
    M("up_decel_gt", DRVC, "if (pov->Type == POV_OUTSIDE && boomLag < 0.0f)",
      "if (pov->Type == POV_OUTSIDE && boomLag > 0.0f)"),
    M("up_decel_inside", DRVC, "if (pov->Type == POV_OUTSIDE && boomLag < 0.0f)",
      "if (boomLag < 0.0f)"),
    M("up_decel_sign", DRVC, "height = height + boomLag * CamHeightMultiplierD;",
      "height = height - boomLag * CamHeightMultiplierD;"),
    # the base matrix
    M("up_tocar_x", DRVC, "    toCar.v3.x = -car->State.GeometryPosition.x;",
      "    toCar.v3.x = -car->State.Position.x;"),
    M("up_tocar_y", DRVC, "    toCar.v3.y = -car->State.GeometryPosition.y;",
      "    toCar.v3.y = -car->State.Position.y;"),
    M("up_tocar_z", DRVC, "    toCar.v3.z = -car->State.GeometryPosition.z;",
      "    toCar.v3.z = -car->State.Position.z;"),
    M("up_lba_round", DRVC,
      "d->LookBackAngle = (uint16_t)(int32_t)(round * 32768.0f);",
      "d->LookBackAngle = (uint16_t)(int32_t)(round * 32767.0f);"),
    M("up_in_no_transpose", DRVC, "        eTransposeMatrix(&boom, &body);",
      "        boom = body;"),
    M("up_in_lba_swapped", DRVC,
      "            d->LookBackAngle = calculate_lookback_angle(car, lbCar, &body);",
      "            d->LookBackAngle = calculate_lookback_angle(lbCar, car, &body);"),
    M("up_in_lba_never", DRVC,
      "        if (lbCar != NULL)\n            d->LookBackAngle = calculate",
      "        if (0)\n            d->LookBackAngle = calculate"),
    M("up_in_canlb", DRVC,
      "        if (!canLB)\n            eRotateZ(&boom, &boom, d->LookBackAngle);\n"
      "        eMulMatrix(&base",
      "        eRotateZ(&boom, &boom, d->LookBackAngle);\n        eMulMatrix(&base"),
    M("up_in_base_order", DRVC, "        eMulMatrix(&base, &toCar, &boom);",
      "        eMulMatrix(&base, &boom, &toCar);"),
    M("up_head_dot", DRVC, "dot = vel.x * body.v0.x + vel.y * body.v0.y;",
      "dot = vel.x * body.v0.x + vel.y * body.v1.y;"),
    M("up_head_dot_gt", DRVC, "        if (dot < 0.0f) {\n            float s",
      "        if (dot > 0.0f) {\n            float s"),
    M("up_head_reflect", DRVC, "float s = dot * -2.0f;", "float s = dot * -1.0f;"),
    M("up_head_ry", DRVC, "vel.y = vel.y + body.v0.y * s;",
      "vel.y = vel.y + body.v0.x * s;"),
    M("up_head_rx", DRVC, "vel.x = vel.x + body.v0.x * s;",
      "vel.x = vel.x - body.v0.x * s;"),
    M("up_head_speed", DRVC, "vel.y * vel.y) - 8.32f) * 0.21276592f;",
      "vel.y * vel.y) - 8.0f) * 0.212766f;"),
    M("up_head_k", DRVC, "vel.y * vel.y) - 8.32f) * 0.21276592f;",
      "vel.y * vel.y) - 8.32f) * 0.2f;"),
    M("up_head_w_lo", DRVC,
      "        if (w < 0.0f)\n            w = 0.0f;\n        if (1.0f < w)",
      "        if (1.0f < w)"),
    M("up_head_w_hi", DRVC, "        if (1.0f < w)\n            w = 1.0f;\n", ""),
    M("up_head_norm", DRVC, "bNormalize2To(&vel, &vel, w);",
      "bNormalize2To(&vel, &vel, 1.0f);"),
    M("up_head_dy", DRVC, "dir.y = body.v0.y * (1.0f - w) + vel.y;",
      "dir.y = body.v0.y + vel.y;"),
    M("up_head_dx", DRVC, "dir.x = body.v0.x * (1.0f - w) + vel.x;",
      "dir.x = body.v0.x * (1.0f - w) - vel.x;"),
    M("up_head_atan", DRVC, "yaw = bATan(dir.x, dir.y);", "yaw = bATan(dir.y, dir.x);"),
    M("up_head_rot", DRVC, "eRotateZ(&base, &toCar, (uint16_t)-yaw);",
      "eRotateZ(&base, &toCar, (uint16_t)yaw);"),
    # the cop's look back
    M("up_lb_canlb_out", DRVC,
      "        if (lbCar != NULL && !canLB) {\n            // Round",
      "        if (lbCar != NULL) {\n            // Round"),
    M("up_lb_dx", DRVC,
      "float dx = lbCar->State.Position.x - car->State.Position.x;",
      "float dx = car->State.Position.x - lbCar->State.Position.x;"),
    M("up_lb_dy", DRVC,
      "float dy = lbCar->State.Position.y - car->State.Position.y;",
      "float dy = lbCar->State.Position.y - car->State.Position.x;"),
    M("up_lb_dist_sq", DRVC, "float dist = sqrtf(dx * dx + dy * dy);",
      "float dist = dx * dx + dy * dy;"),
    M("up_lb_want_rev", DRVC, "int32_t want = (uint16_t)(yaw - bATan(dx, dy));",
      "int32_t want = (uint16_t)(bATan(dx, dy) - yaw);"),
    M("up_lb_want_signed", DRVC, "(uint16_t)(yaw - bATan(dx, dy))",
      "(int16_t)(yaw - bATan(dx, dy))"),
    M("up_lb_add_vm", DRVC,
      "float add = eGetCurrentViewMode() == 3 ? 0.0f : 0.4f;",
      "float add = 0.4f;"),
    M("up_lb_add_k", DRVC, "== 3 ? 0.0f : 0.4f;", "== 3 ? 0.0f : 0.5f;"),
    M("up_lb_top", DRVC, "float top = car->pCarTypeInfo->Body.Zdim - height;",
      "float top = car->pCarTypeInfo->Body.Zdim;"),
    M("up_lb_cone_wide", DRVC, "if ((uint32_t)(want - 8192) > 0xbfffu) {",
      "if ((uint32_t)(want - 8192) > 0xafffu) {"),
    M("up_lb_cone_lo", DRVC, "if ((uint32_t)(want - 8192) > 0xbfffu) {",
      "if ((uint32_t)(want - 4096) > 0xbfffu) {"),
    M("up_lb_cone_kept", DRVC,
      "                want = 0;\n                top = top + add * 0.75f;",
      "                top = top + add * 0.75f;"),
    M("up_lb_cone_add", DRVC, "top = top + add * 0.75f;", "top = top + add;"),
    M("up_lb_side_add", DRVC,
      "            } else {\n                top = top + add;\n            }",
      "            } else {\n                top = top + add * 0.75f;\n            }"),
    M("up_lb_no_wrap_dn", DRVC,
      "            if (cur < want - 32768)\n                want -= 65536;\n", ""),
    M("up_lb_no_wrap_up", DRVC,
      "            if (want + 32768 < cur)\n                want += 65536;\n", ""),
    M("up_lb_up_gap", DRVC, "if (cur + 10000 < want ||", "if (cur + 5000 < want ||"),
    M("up_lb_up_far", DRVC,
      "if (cur + 10000 < want || (50.0f < dist && (want & 0xffff)))",
      "if (cur + 10000 < want || 50.0f < dist)"),
    M("up_lb_up_far_k", DRVC, "if (cur + 10000 < want || (50.0f < dist",
      "if (cur + 10000 < want || (40.0f < dist"),
    M("up_lb_up_fast", DRVC, "cur + (int32_t)(rate * (dt * 60000.0f));",
      "cur + (int32_t)(rate * (dt * 50000.0f));"),
    M("up_lb_up_slow", DRVC, "cur + (int32_t)(rate * (dt * 20000.0f));",
      "cur + (int32_t)(rate * (dt * 25000.0f));"),
    M("up_lb_up_over", DRVC,
      "                if (want < d->iLookBackParam)\n"
      "                    d->iLookBackParam = want;\n", ""),
    M("up_lb_dn_gap", DRVC, "if (want < cur - 10000 ||", "if (want < cur - 5000 ||"),
    M("up_lb_dn_far", DRVC,
      "if (want < cur - 10000 || (50.0f < dist && (want & 0xffff)))",
      "if (want < cur - 10000 || 50.0f < dist)"),
    M("up_lb_dn_fast", DRVC, "cur - (int32_t)(rate * (dt * 60000.0f));",
      "cur - (int32_t)(rate * (dt * 50000.0f));"),
    M("up_lb_dn_slow", DRVC, "cur - (int32_t)(rate * (dt * 20000.0f));",
      "cur - (int32_t)(rate * (dt * 25000.0f));"),
    M("up_lb_dn_over", DRVC,
      "                if (d->iLookBackParam < want)\n"
      "                    d->iLookBackParam = want;\n", ""),
    M("up_lb_no_mask", DRVC, "            d->iLookBackParam &= 0xffff;\n", ""),
    M("up_lb_h_up", DRVC, "d->iLookBackHeight = d->iLookBackHeight + rate * dt;",
      "d->iLookBackHeight = d->iLookBackHeight + rate * dt * 0.5f;"),
    M("up_lb_h_up_over", DRVC,
      "                if (top < d->iLookBackHeight)\n"
      "                    d->iLookBackHeight = top;\n            } else if",
      "            } else if"),
    M("up_lb_h_dn", DRVC, "d->iLookBackHeight = d->iLookBackHeight - rate * dt;",
      "d->iLookBackHeight = d->iLookBackHeight - rate * dt * 0.5f;"),
    M("up_lb_h_dn_over", DRVC,
      "                if (d->iLookBackHeight < top)\n"
      "                    d->iLookBackHeight = top;\n            }\n",
      "            }\n"),
    M("up_lb_lba_kept", DRVC,
      "            d->LookBackAngle = (uint16_t)d->iLookBackParam;\n", ""),
    # the boom
    M("up_outside_nolb", DRVC,
      "outside = pov->Type == POV_OUTSIDE || (canLB && 0.0f < d->LookBackParam);",
      "outside = pov->Type == POV_OUTSIDE;"),
    M("up_outside_canlb", DRVC, "|| (canLB && 0.0f < d->LookBackParam);",
      "|| 0.0f < d->LookBackParam;"),
    M("up_turn_wide", DRVC,
      "uint16_t turn = (uint16_t)(yaw - (uint16_t)d->LastCarYaw);",
      "uint16_t turn = (uint16_t)yaw;"),
    M("up_air_two", DRVC, "nWheelsTouchingGround < 3 ? -1.0f : 1.0f;",
      "nWheelsTouchingGround < 2 ? -1.0f : 1.0f;"),
    M("up_air_zero", DRVC, "nWheelsTouchingGround < 3 ? -1.0f : 1.0f;",
      "nWheelsTouchingGround < 3 ? 0.0f : 1.0f;"),
    M("up_tg_k", DRVC, "air * 0.24316f;", "air * 0.25f;"),
    M("up_tg_hi", DRVC, "        if (1.0f < tg)\n            d->TouchingGroundFactor = 1.0f;",
      "        if (2.0f < tg)\n            d->TouchingGroundFactor = 1.0f;"),
    M("up_tg_lo", DRVC, "        else if (tg < 0.0f)\n            d->TouchingGroundFactor = 0.0f;",
      "        else if (tg < -1.0f)\n            d->TouchingGroundFactor = 0.0f;"),
    M("up_corr_yaw_arg", DRVC,
      "            (uint16_t)(turn + (uint16_t)d->LastBoomYaw));",
      "            (uint16_t)d->LastBoomYaw);"),
    M("up_boomyaw_notg", DRVC,
      "+ (int32_t)((d->TouchingGroundFactor * tg)\n                                         * dt));",
      "+ (int32_t)(tg * dt));"),
    M("up_boomyaw_noturn", DRVC, "boomYaw = (uint16_t)(turn + (uint16_t)d->LastBoomYaw\n",
      "boomYaw = (uint16_t)((uint16_t)d->LastBoomYaw\n"),
    M("up_boomyaw_rot", DRVC, "        eRotateZ(&boom, &boom, boomYaw);\n",
      "        eRotateZ(&boom, &boom, (uint16_t)-boomYaw);\n"),
    M("up_boomyaw_store", DRVC, "        d->LastBoomYaw = boomYaw;\n",
      "        d->LastBoomYaw = turn;\n"),
    M("up_caryaw_store", DRVC, "        d->LastCarYaw = yaw;\n",
      "        d->LastCarYaw = car->State.Angle;\n"),
    M("up_pitch_row", DRVC,
      "        p = (uint16_t)bASin(car->State.BodyMatrix.v0.z);\n        if (d->LookBackAngle",
      "        p = (uint16_t)bASin(car->State.BodyMatrix.v1.z);\n        if (d->LookBackAngle"),
    M("up_pitch_lba", DRVC,
      "        if (d->LookBackAngle != 0)\n            s = (uint16_t)d->LastBoomPitch - p;",
      "        if (0)\n            s = (uint16_t)d->LastBoomPitch - p;"),
    M("up_pitch_tgf", DRVC, "        else if (d->TouchingGroundFactor == 0.0f)",
      "        else if (d->TouchingGroundFactor < 0.5f)"),
    M("up_pitch_air9", DRVC, "- (p <= 32767 ? p - p / 9 : p + (0xffff - p) / 3);",
      "- (p <= 32767 ? p - p / 8 : p + (0xffff - p) / 3);"),
    M("up_pitch_air3", DRVC, "p + (0xffff - p) / 3);", "p + (0xffff - p) / 2);"),
    M("up_pitch_air_half", DRVC, "- (p <= 32767 ? p - p / 9",
      "- (p <= 16383 ? p - p / 9"),
    M("up_pitch_gnd9", DRVC, "- (p <= 32767 ? p + p / 9 : p - (0xffff - p) / 3);",
      "- (p <= 32767 ? p + p / 8 : p - (0xffff - p) / 3);"),
    M("up_pitch_gnd3", DRVC, "p - (0xffff - p) / 3);", "p - (0xffff - p) / 4);"),
    M("up_pitch_gnd_half", DRVC, "- (p <= 32767 ? p + p / 9",
      "- (p <= 16383 ? p + p / 9"),
    M("up_pitch_mask1", DRVC, "        s &= 0xffff;\n        if (air != 0.0f)",
      "        if (air != 0.0f)"),
    M("up_pitch_corr_k", DRVC, "(uint16_t)s) * dt) * 25.0f);",
      "(uint16_t)s) * dt) * 20.0f);"),
    M("up_pitch_corr_base", DRVC,
      "            s = (uint16_t)d->LastBoomPitch\n                + (int32_t)(((float)",
      "            s = (uint16_t)p\n                + (int32_t)(((float)"),
    M("up_pitch_mask2", DRVC, "        s &= 0xffff;\n        {\n", "        {\n"),
    M("up_noise_sign", DRVC, "(uint16_t)(int32_t)((float)s + RoadNoiseAmplitude",
      "(uint16_t)(int32_t)((float)s - RoadNoiseAmplitude"),
    M("up_noise_terrain", DRVC, "&at, TERRAIN_TYPE_DIRT)));",
      "&at, TERRAIN_TYPE_DIRTROAD)));"),
    M("up_noise_at", DRVC,
      "            at.x = car->State.Position.x;\n            at.y = car->State.Position.y;",
      "            at.x = car->State.Position.y;\n            at.y = car->State.Position.x;"),
    M("up_lb_rot_canlb", DRVC,
      "        if (!canLB)\n            eRotateZ(&boom, &boom, d->LookBackAngle);\n"
      "        d->LastCarPitch = p;",
      "        eRotateZ(&boom, &boom, d->LookBackAngle);\n        d->LastCarPitch = p;"),
    M("up_carpitch_store", DRVC, "        d->LastCarPitch = p;\n        d->LastBoomPitch = s;",
      "        d->LastCarPitch = 0;\n        d->LastBoomPitch = s;"),
    M("up_boompitch_store", DRVC, "        d->LastBoomPitch = s;\n    } else {",
      "        d->LastBoomPitch = p;\n    } else {"),
    M("up_in_boomyaw", DRVC,
      "        d->LastBoomYaw = 0;\n        d->LastCarYaw = car->State.Angle;",
      "        d->LastCarYaw = car->State.Angle;"),
    M("up_in_caryaw", DRVC,
      "        d->LastCarYaw = car->State.Angle;\n        d->LastCarPitch = (uint16_t)bASin",
      "        d->LastCarYaw = yaw;\n        d->LastCarPitch = (uint16_t)bASin"),
    M("up_in_carpitch", DRVC,
      "        d->LastCarPitch = (uint16_t)bASin(car->State.BodyMatrix.v0.z);\n"
      "        d->LastBoomPitch = 0;\n    }",
      "        d->LastCarPitch = 0;\n        d->LastBoomPitch = 0;\n    }"),
    M("up_in_boompitch", DRVC, "        d->LastBoomPitch = 0;\n    }\n\n    // A look back",
      "    }\n\n    // A look back"),
    # the player's look back
    M("up_lbsw_nocanlb", DRVC,
      "    if (canLB && 0.0f < d->LookBackParam) {\n        float p",
      "    if (0.0f < d->LookBackParam) {\n        float p"),
    M("up_lbsw_h_vm3", DRVC, "height = vm3 ? t * height - p : t * height + p * -3.0f;",
      "height = vm3 ? t * height + p : t * height + p * -3.0f;"),
    M("up_lbsw_h", DRVC, "t * height + p * -3.0f;", "t * height + p * -2.0f;"),
    M("up_lbsw_lag", DRVC, "(vm3 ? 16.0f : 18.0f)", "(vm3 ? 16.0f : 17.0f)"),
    M("up_lbsw_lag3", DRVC, "(vm3 ? 16.0f : 18.0f)", "(vm3 ? 15.0f : 18.0f)"),
    M("up_lbsw_lag_t", DRVC, "lagx = t * lag + p *", "lagx = lag + p *"),
    M("up_lbsw_ang", DRVC, "(vm3 ? 3540.0f : 5200.0f)", "(vm3 ? 3540.0f : 5000.0f)"),
    M("up_lbsw_ang3", DRVC, "(vm3 ? 3540.0f : 5200.0f)", "(vm3 ? 3500.0f : 5200.0f)"),
    M("up_lbsw_ang_sign", DRVC, "(uint16_t)-(int32_t)(t * (float)angle",
      "(uint16_t)(int32_t)(t * (float)angle"),
    M("up_lbsw_vm", DRVC, "int vm3 = eGetCurrentViewMode() == 3;",
      "int vm3 = eGetCurrentViewMode() == 2;"),
    M("up_lbsw_t", DRVC, "float p = d->LookBackParam, t = 1.0f - p;",
      "float p = d->LookBackParam, t = 1.0f;"),
    M("up_lagx_init", DRVC, "    lagx = lag;\n    if (canLB", "    lagx = 0.0f;\n    if (canLB"),
    M("up_raise_init", DRVC, "    raise = 0.0f;\n    lagx = lag;",
      "    raise = 0.1f;\n    lagx = lag;"),
    # the eye outside
    M("up_lbh_kept", DRVC, "            height = height + d->iLookBackHeight;\n", ""),
    M("up_lbh_lag", DRVC, "            lagx = 2.24f;", "            lagx = 2.0f;"),
    M("up_eye_lag", DRVC,
      "        v.x = lagx;\n        v.y = lat;\n        v.z = -height;\n"
      "        v.pad = 0.0f;\n        eTranslate(&e,",
      "        v.x = lag;\n        v.y = lat;\n        v.z = -height;\n"
      "        v.pad = 0.0f;\n        eTranslate(&e,"),
    M("up_eye_lat", DRVC,
      "        v.y = lat;\n        v.z = -height;\n        v.pad = 0.0f;\n"
      "        eTranslate(&e,",
      "        v.y = -lat;\n        v.z = -height;\n        v.pad = 0.0f;\n"
      "        eTranslate(&e,"),
    M("up_eye_h", DRVC,
      "        v.z = -height;\n        v.pad = 0.0f;\n        eTranslate(&e,",
      "        v.z = height;\n        v.pad = 0.0f;\n        eTranslate(&e,"),
    M("up_eye_base", DRVC, "        eMulMatrix(&e, &base, &e);",
      "        eMulMatrix(&e, &e, &base);"),
    M("up_eye_inv", DRVC, "        eInvertTransformationMatrix(&f, &e);\n        mid.x",
      "        eTransposeMatrix(&f, &e);\n        mid.x"),
    M("up_mid_x", DRVC, "mid.x = (f.v3.x + car->State.Position.x) * 0.5f;",
      "mid.x = f.v3.x;"),
    M("up_mid_y", DRVC, "mid.y = (f.v3.y + car->State.Position.y) * 0.5f;",
      "mid.y = (f.v3.y + car->State.Position.x) * 0.5f;"),
    M("up_mid_z", DRVC, "mid.z = (f.v3.z + car->State.Position.z) * 0.5f;",
      "mid.z = car->State.Position.z;"),
    M("up_bbox_r", DRVC, "+ dv.z * dv.z) * 0.5f + 1.0f;",
      "+ dv.z * dv.z) * 0.5f + 2.0f;"),
    M("up_bbox_r_half", DRVC, "+ dv.z * dv.z) * 0.5f + 1.0f;",
      "+ dv.z * dv.z) * 0.25f + 1.0f;"),
    M("up_bbox_r_dz", DRVC, "        dv.z = car->State.Position.z - f.v3.z;\n",
      "        dv.z = 0.0f;\n"),
    M("up_bbox_vel", DRVC, "&mid, r,\n                                    &car->State.Velocity);",
      "&mid, r,\n                                    &car->State.Acceleration);"),
    M("up_pc_f", DRVC, "        eMulVector3(&pc, &e, &car->State.Position);",
      "        eMulVector3(&pc, &f, &car->State.Position);"),
    M("up_r_inv", DRVC, "        r = 1.0f / pc.x;\n", "        r = 1.0f / pc.z;\n"),
    M("up_r_no_lo", DRVC, "        if (r < -1000.0f)\n            r = -1000.0f;\n", ""),
    M("up_r_no_hi", DRVC, "        if (1000.0f < r)\n            r = 1000.0f;\n", ""),
    M("up_r_no_neg", DRVC, "        r = -r;\n", ""),
    M("up_offs_y", DRVC, "        offs.y = r * pc.z;", "        offs.y = r * pc.y;"),
    M("up_offs_x", DRVC, "        offs.x = r * pc.y;", "        offs.x = r * pc.z;"),
    M("up_wall_from", DRVC,
      "camera_wall_offset(m, &d->TheTopologyCoordinate, &car->State.Position,",
      "camera_wall_offset(m, &d->TheTopologyCoordinate, &car->State.GeometryPosition,"),
    M("up_eye_wx", DRVC, "        eye.x = f.v3.x + wall.x;", "        eye.x = f.v3.x;"),
    M("up_eye_wy", DRVC, "        eye.y = f.v3.y + wall.y;", "        eye.y = f.v3.y - wall.y;"),
    M("up_eye_wz", DRVC, "        eye.z = f.v3.z + wall.z;", "        eye.z = f.v3.z;"),
    M("up_reach_always", DRVC, "        if (lbCar == NULL) {\n            float dist, reach;",
      "        if (1) {\n            float dist, reach;"),
    M("up_reach_dz", DRVC,
      "            dv.z = car->State.Position.z - eye.z;\n            dist",
      "            dv.z = 0.0f;\n            dist"),
    M("up_reach_min", DRVC, "            reach = fabsf(bmin.x);", "            reach = bmin.x;"),
    M("up_reach_no_max", DRVC, "            if (reach < bmax.x)\n                reach = bmax.x;\n",
      ""),
    M("up_reach_pad", DRVC, "            reach = reach + 0.7f;", "            reach = reach + 0.5f;"),
    M("up_reach_cmp", DRVC, "            if (dist < reach) {", "            if (dist < reach - 0.1f) {"),
    M("up_reach_s", DRVC,
      "float s = sqrtf(reach * reach\n                                - (dv.x * dv.x + dv.y * dv.y));",
      "float s = reach;"),
    M("up_reach_dz_sign", DRVC, "float dz = eye.z - car->State.Position.z;",
      "float dz = car->State.Position.z - eye.z;"),
    M("up_raise_calc", DRVC, "                raise = dz / s;", "                raise = s / dz;"),
    M("up_raise_eye", DRVC, "eye.z = eye.z + (s - dz);", "eye.z = eye.z + s;"),
    M("up_raise_wall", DRVC, "wall.z = wall.z + (s - dz);", "wall.z = wall.z + s;"),
    M("up_o_f", DRVC, "eMulVector4(&o, &e, (const bVector4 *)&wall);",
      "eMulVector4(&o, &f, (const bVector4 *)&wall);"),
    M("up_o_h", DRVC, "        height = height + o.z;", "        height = height - o.z;"),
    M("up_o_lat", DRVC, "        lat = lat - o.y;", "        lat = lat + o.y;"),
    M("up_o_lag", DRVC, "        lagx = lagx - o.x;", "        lagx = lagx + o.x;"),
    # the boom's last words and the inside eye
    M("up_boom_lag", DRVC,
      "    v.x = lagx;\n    v.y = lat;\n    v.z = -height;\n    v.pad = 0.0f;\n"
      "    eTranslate(&boom,",
      "    v.x = lag;\n    v.y = lat;\n    v.z = -height;\n    v.pad = 0.0f;\n"
      "    eTranslate(&boom,"),
    M("up_boom_lat", DRVC,
      "    v.y = lat;\n    v.z = -height;\n    v.pad = 0.0f;\n    eTranslate(&boom,",
      "    v.y = 0.0f;\n    v.z = -height;\n    v.pad = 0.0f;\n    eTranslate(&boom,"),
    M("up_boom_h", DRVC, "    v.z = -height;\n    v.pad = 0.0f;\n    eTranslate(&boom,",
      "    v.z = height;\n    v.pad = 0.0f;\n    eTranslate(&boom,"),
    M("up_boom_ang_sign", DRVC, "(uint16_t)-(angle + (int32_t)(raise\n",
      "(uint16_t)(angle + (int32_t)(raise\n"),
    M("up_boom_raise", DRVC, "* (float)(maxAngle - angle))));",
      "* (float)maxAngle)));"),
    M("up_look_target", DRVC,
      "camera_look_at_offset(&f, &eye, &car->State.Position, &offs);",
      "camera_look_at_offset(&f, &eye, &car->State.GeometryPosition, &offs);"),
    M("up_in_mul", DRVC,
      "        eMulMatrix(&e, &base, &boom);\n        eInvertTransformationMatrix(&e, &e);",
      "        eMulMatrix(&e, &boom, &base);\n        eInvertTransformationMatrix(&e, &e);"),
    M("up_in_elev", DRVC, "NULL) + 0.7f;", "NULL) + 0.5f;"),
    M("up_in_gt", DRVC, "        if (e.v3.z < el) {", "        if (e.v3.z > el) {"),
    M("up_in_no_lift", DRVC, "            e.v3.z = el;\n            lifted = 1;",
      "            lifted = 1;"),
    M("up_in_lifted_lost", DRVC, "            lifted = 1;\n", ""),
    M("up_in_never_inv", DRVC,
      "        if (lifted)\n            eInvertTransformationMatrix(&f, &e);\n"
      "        else\n            eMulMatrix(&f, &base, &boom);",
      "        eMulMatrix(&f, &base, &boom);"),
    M("up_in_always_inv", DRVC,
      "        if (lifted)\n            eInvertTransformationMatrix(&f, &e);\n"
      "        else\n            eMulMatrix(&f, &base, &boom);",
      "        eInvertTransformationMatrix(&f, &e);"),
    M("up_in_rx", DRVC, "eRotateX(&f, &f, 16384);", "eRotateX(&f, &f, 49152);"),
    M("up_in_ry", DRVC, "eRotateY(&f, &f, 0xc000);", "eRotateY(&f, &f, 0x4000);"),
    # the camera's words
    M("up_dash_kept", DRVC, "    if (!CameraStopUpdating)\n        cam->RenderDash = 0;\n", ""),
    M("up_dash_stop", DRVC, "    if (!CameraStopUpdating)\n        cam->RenderDash = 0;\n",
      "    cam->RenderDash = 0;\n"),
    M("up_carnot_null", DRVC, "            cam->CarNotToRender = car;",
      "            cam->CarNotToRender = NULL;"),
    M("up_carnot_stop", DRVC,
      "        if (!CameraStopUpdating)\n            cam->CarNotToRender = car;",
      "        cam->CarNotToRender = car;"),
    M("up_dash_bumper", DRVC,
      "if (pov->Type == POV_INCAR && d->DesiredLookBackParam != 1.0f",
      "if (pov->Type == POV_BUMPER && d->DesiredLookBackParam != 1.0f"),
    M("up_dash_lbp", DRVC, "&& d->DesiredLookBackParam != 1.0f\n",
      "&& d->LookBackParam != 1.0f\n"),
    M("up_dash_nostop", DRVC,
      "&& d->DesiredLookBackParam != 1.0f\n            && !CameraStopUpdating)",
      "&& d->DesiredLookBackParam != 1.0f)"),
    M("up_carnot_out", DRVC, "        cam->CarNotToRender = NULL;\n    }\n    // The image",
      "        cam->CarNotToRender = car;\n    }\n    // The image"),
    M("up_carnot_out_stop", DRVC,
      "    } else if (!CameraStopUpdating) {\n        cam->CarNotToRender = NULL;",
      "    } else {\n        cam->CarNotToRender = NULL;"),
    M("up_fov_in", DRVC, "cam->CurrentKey.FieldOfView = 16384;",
      "cam->CurrentKey.FieldOfView = 13020;"),
    M("up_fov_nobumper", DRVC, "if (pov->Type == POV_INCAR || pov->Type == POV_BUMPER) {",
      "if (pov->Type == POV_INCAR) {"),
    M("up_fov_in_stop", DRVC,
      "        if (!CameraStopUpdating)\n            cam->CurrentKey.FieldOfView = 16384;",
      "        cam->CurrentKey.FieldOfView = 16384;"),
    M("up_fov_out", DRVC, "cam->CurrentKey.FieldOfView = 13020;",
      "cam->CurrentKey.FieldOfView = 16384;"),
    M("up_fov_out_stop", DRVC,
      "        if (!CameraStopUpdating)\n            cam->CurrentKey.FieldOfView = 13020;",
      "        cam->CurrentKey.FieldOfView = 13020;"),
    M("up_nearz_in", DRVC, "pov->Type == POV_INCAR ? 0.4f : 0.5f;",
      "pov->Type == POV_INCAR ? 0.5f : 0.5f;"),
    M("up_nearz_out", DRVC, "pov->Type == POV_INCAR ? 0.4f : 0.5f;",
      "pov->Type == POV_INCAR ? 0.4f : 0.6f;"),
    M("up_shake_view", DRVC, "    apply_camera_shake(m->ViewID, &f);",
      "    apply_camera_shake(0, &f);"),
    M("up_shake_lost", DRVC, "    apply_camera_shake(m->ViewID, &f);\n", ""),
    M("up_td_gpos", DRVC,
      "float dx = cam->CurrentKey.Position.x - car->State.Position.x;",
      "float dx = cam->CurrentKey.Position.x - car->State.GeometryPosition.x;"),
    M("up_td_dz", DRVC,
      "float dz = cam->CurrentKey.Position.z - car->State.Position.z;",
      "float dz = 0.0f;"),
    M("up_td_stop", DRVC,
      "        if (!CameraStopUpdating)\n            cam->CurrentKey.TargetDistance = dist;",
      "        cam->CurrentKey.TargetDistance = dist;"),
    M("up_focus_perfect", DRVC, "if (!d->PerfectFocus && !CameraStopUpdating) {",
      "if (!CameraStopUpdating) {"),
    M("up_focus_stop", DRVC, "if (!d->PerfectFocus && !CameraStopUpdating) {",
      "if (!d->PerfectFocus) {"),
    M("up_focal", DRVC, "cam->CurrentKey.FocalDistance = 15.0f;",
      "cam->CurrentKey.FocalDistance = 16.0f;"),
    M("up_dof", DRVC, "cam->CurrentKey.DepthOfField = 65.0f;",
      "cam->CurrentKey.DepthOfField = 60.0f;"),
    M("up_setmat_world", DRVC, "camera_set_matrix(cam, &f, RealTimeElapsed);",
      "camera_set_matrix(cam, &f, WorldTimeElapsed);"),
    M("up_lba_kept", DRVC, "    if (canLB)\n        d->LookBackAngle = 0;\n}", "}"),
]

# Mutants that cannot change what either side computes, each with why.
EQUIVALENT = {
    # The base's destructor, called next, sets the base's vtable, and
    # nothing between the two reads it.
    "dtor_no_vtbl": "the base's destructor sets its own vtable next",
    # The image masks bASin's result (andi 0xffff) and the cast mirrors
    # that, but the port's bASin already returns r & 0xffff.
    "ctor_pitch_signed": "bASin already returns 0..0xffff",
    "reset_pitch_signed": "bASin already returns 0..0xffff",
    # Update calls GetLookbackCar only with a cop manager.
    "glb_no_cm_test": "Update calls it only when pCopManager is set",
    # Nothing reads the fourth lane of the push: PointInShaft reads the
    # probe's x, y and z, and the push is stored with pad 0.
    "wall_acc_pad": "the fourth lane is never read",
    # Left in the push, that lane reaches only the eye's pad, which the
    # look-at never reads, and o, which only the dead boom below uses.
    "wall_out_pad": "the eye's pad is never read, and o feeds the dead boom",
    # Outside, the camera is the look-at from the eye; the boom's last
    # translate and turn, after the eye, go nowhere. Inside, o is never
    # worked out, raise is 0 and lagx is lag. The image works them out
    # all the same. maxAngle is read only in that turn.
    "up_raise_calc": "raise feeds only the boom's last turn, dead outside",
    "up_raise_wall": "wall.z after the eye feeds only o, which is dead",
    "up_o_f": "o feeds only the boom's last translate, dead outside",
    "up_o_h": "o feeds only the boom's last translate, dead outside",
    "up_o_lat": "o feeds only the boom's last translate, dead outside",
    "up_o_lag": "o feeds only the boom's last translate, dead outside",
    "up_boom_lag": "lagx is lag inside, and the translate is dead outside",
    "up_boom_raise": "raise is 0 inside, and the turn is dead outside",
    "up_tw_max": "maxAngle is read only in the boom's last turn",
    "up_pov_max": "maxAngle is read only in the boom's last turn",
    # ok is only ever tested against 0.
    "lag_decel_ok_one": "ok is only tested against 0",
    # lbCar is only set when the look back does not count.
    "up_lb_canlb_out": "lbCar is NULL whenever canLB is set",
    # The correction takes (uint16_t)s, and s is masked again after it.
    "up_pitch_mask1": "the correction's argument is cast to 16 bits anyway",
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    hostbuild.recover()
    m = Model()
    sc = script()
    base = m.run(sc)
    caught, survived, missing, equivalent = 0, [], [], []
    scdir = tempfile.TemporaryDirectory()
    scp = Path(scdir.name) / "scenarios.txt"
    scp.write_text(encode(sc))
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, scp, out)
        if diff(base, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for mut in todo:
        name, rel, before, after = mut
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        edits = before if isinstance(before, list) else [(before, after)]
        new, bad = text, None
        for b, a in edits:
            probe = b.replace(NL, "\r\n") if crlf else b
            repl = a.replace(NL, "\r\n") if crlf else a
            if new.count(probe) != 1:
                bad = "NOT FOUND" if not new.count(probe) else "NOT UNIQUE"
                break
            new = new.replace(probe, repl, 1)
        if bad:
            missing.append(name)
            print("  %-44s PATTERN %s" % (name, bad))
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
                rc = run_harness(exe, scp, out)
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
    scdir.cleanup()

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

    m = Model()
    sc = script()
    lines = m.run(sc)
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
