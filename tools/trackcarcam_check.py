#!/usr/bin/env python3
"""Cross-check 3DS Files/source/trackcarcam.c, the jump cam's mover, and
spline.c, the splines it flies along, against the retail image itself, run
in mipsemu.

The model is the image. TrackCarCameraMover's constructor (0x00159130),
destructor (0x00159490), Update (0x00159588), GetTarget (0x00159520),
GetCarToFollow (0x0015fb00) and CalcSpringForce (0x00159540) run as
shipped, through retail's vtable (0x002b1ad0) where the game goes through
it, and so do Spline's constructor (0x00189238), destructor (0x00189268),
GetControlPoint (0x001895c8), Evaluate (0x00189810) and GetPoint
(0x00189948). Under them run the CameraMover base, its
ComputeBankedUpVector (0x00157888), Camera::SetCameraMatrix, the matrix
layer, bATan, bNormalize, bRandom, cPoint::SplineSeek and IsGameFlowPaused,
over retail's own eView table. The harness (tools/src/trackcarcam_test.c)
runs the port over the same script, and the two transcripts are diffed.

Stubs: bFunkDoesServerExist answers 0, and __builtin_vec_delete and
__builtin_delete print the block, as the harness's bFree does. Everything
else the mover reads is laid out in memory by the script: the cars
(GeometryPosition at 80, Position at 96, BodyMatrix at 144, the ratio round
the track at 2032), the record and the shake it is built from and the
record's FOV, eye and bank arrays, the race coordinator at gp-22216,
WorldTimeElapsed at gp-19560, RealTimeElapsed at gp-19596,
Camera::StopUpdating at gp-21808, TheRaceParameters.TrackDirection at
0x0031a8a4 and bRandom's default seed at gp-14472.

Every camera, mover, record and array starts from a byte pattern, so what
a call leaves alone shows. A float prints as its bits, a NaN as "nan", and
a pointer by what it is. The mover's look point and spring vectors print
without their pad lanes: retail leaves stack words there (the up vector's,
bNormalize's and the look offset's fourth lanes), which the port zeroes.

    python tools/trackcarcam_check.py
    python tools/trackcarcam_check.py --mutate [--only a,b]
    python tools/trackcarcam_check.py --dump out/trackcarcam
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

HARNESS = "tools/src/trackcarcam_test.c"
TCC = "3DS Files/source/trackcarcam.c"
SPC = "3DS Files/source/spline.c"
CMC = "3DS Files/source/cammover.c"
SOURCES = [HARNESS, TCC, SPC, CMC] + ["3DS Files/source/" + f for f in (
    "race.c", "camera.c", "eview.c", "emath.c", "bmatrix.c", "bmath.c",
    "bmathtab.c", "bvector.c", "banim.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
CAM_CTOR = 0x00156be0
TC_CTOR = 0x00159130
TC_UPDATE = 0x00159588
TC_VTBL = 0x002b1ad0
BASE_VTBL = 0x002b1e50
SPL_CTOR = 0x00189238
SPL_DTOR = 0x00189268
SPL_GCP = 0x001895c8
SPL_EVAL = 0x00189810
SPL_GETPT = 0x00189948
VEC_DELETE = 0x00114e90
DELETE = 0x00114e98
EXT = 0x003341a0                  # GetControlPoint's extrapolated point
FUNK_EXISTS = 0x0025d220
EMATH_SINIT = 0x0011bf70          # writes eMulVector's (0, 0, 0, 1)
JOLLY = 0x002fa860
VIEWS = 0x002c95b0
VIEW_STRIDE = 128
NVIEWS = 10
V_CAMERA = 56
V_LIST = 60

G_STOP = GP - 21808               # Camera::StopUpdating
G_RC = GP - 22216                 # pRaceCoordinator
G_WTE = GP - 19560                # WorldTimeElapsed
G_RTE = GP - 19596                # RealTimeElapsed
G_SEED = GP - 14472               # bRandom's default seed
TRACKDIR = 0x0031a8a4             # TheRaceParameters.TrackDirection

CAM_SIZE = 464
CAMS = 0x01000000
NCAM = 4
MOVS = 0x01010000
MOV_STRIDE = 0x500
NMOV = 3
CARS = 0x01020000
CAR_STRIDE = 0x1000
NCAR = 3
CDT = 0x01030000
SHK = 0x01030100
FOVT = 0x01031000
EYEV = 0x01031200
BANKV = 0x01031300
NFOV = 32
NEYE = 8
SPL = 0x01031400
OUTV = 0x01031440
BLK0 = 0x01031500
BLK1 = 0x01031510
RC = 0x01032000

C_GPOS = 80
C_POS = 96
C_BODY = 144
C_RATIO = 2032

PATTERN = 0xa5

# The vtable's slots, by the function's offset.
SLOTS = {
    "destroy": 12, "update": 20, "render": 28, "info": 52, "pov": 60,
    "ext": 68, "lookback": 76, "gap": 84, "car": 116, "target": 124,
}

# CameraDataItems, the .mdebug record: name -> (offset, kind), `i` a
# word, `f` a float, `p` a pointer, in the harness's order.
CD_FIELDS = [
    ("Type", 0, "i"), ("Name", 4, "p"), ("IsFOVIso", 8, "i"),
    ("MinPercent", 12, "f"), ("MaxPercent", 16, "f"),
    ("EyeSplineSpeed", 20, "f"), ("LookSplineSpeed", 24, "f"),
    ("FOVSplineSpeed", 28, "f"), ("LockEyeSpeedToCar", 32, "i"),
    ("LockLookSpeedToCar", 36, "i"), ("MinAreaPercent", 40, "f"),
    ("MaxAreaPercent", 44, "f"), ("NearClip", 48, "f"), ("FarClip", 52, "f"),
    ("Backwards", 56, "i"), ("FOVTable", 60, "p"), ("NumAreaVerts", 64, "i"),
    ("AreaVerts", 68, "p"), ("NumAreaFaces", 72, "i"), ("AreaFaces", 76, "p"),
    ("NumEyeVerts", 80, "i"), ("EyeVerts", 84, "p"), ("BankVerts", 88, "p"),
    ("NumLookVerts", 92, "i"), ("LookVerts", 96, "p"),
    ("SpringXVel", 100, "f"), ("SpringYVel", 104, "f"),
    ("SpringZVel", 108, "f"), ("SpringDamp", 112, "f"),
    ("SpringConst", 116, "f"), ("LookOffsetX", 120, "f"),
    ("LookOffsetY", 124, "f"), ("LookOffsetZ", 128, "f"),
    ("EnterVertComp", 132, "f"), ("EnterHorizComp", 136, "f"),
    ("LeaveVertComp", 140, "f"), ("LeaveHorizComp", 144, "f"),
    ("IsLeaveSet", 148, "i"), ("WipeDistance", 152, "f"),
    ("WipeAutoDisable", 156, "i"), ("ShakeBankNumber", 160, "i"),
]
CD_BY_NAME = {n: (o, k) for n, o, k in CD_FIELDS}

# The mover's fields a script sets: name -> (offset, kind).
MOV_FIELDS = {
    "ep": (1024, "f"), "sp": (1028, "f"), "halt": (1072, "i"),
    "apart": (1076, "f"), "car": (1080, "car"), "fe": (1132, "i"),
    "val": (1084, "f"), "k": (96, "f"), "d": (100, "f"),
}

ARRAYS = {"f": FOVT, "e": EYEV, "b": BANKV}
SYMS = {"-": 0, "fovt": FOVT, "eyev": EYEV, "bankv": BANKV,
        "blk0": BLK0, "blk1": BLK1}


def fb(v):
    if isinstance(v, int):
        return v & M32
    return f_to_bits(v)


def h(v):
    return "%08x" % fb(v)


def fx(w):
    """A float's bits, with every NaN the one "nan"."""
    w &= M32
    if (w & 0x7f800000) == 0x7f800000 and (w & 0x7fffff):
        return "nan"
    return "%08x" % w


def cam_at(k):
    return CAMS + CAM_SIZE * k


def mov_at(j):
    return MOVS + MOV_STRIDE * j


def car_at(i):
    return 0 if i < 0 else CARS + CAR_STRIDE * i


def view_at(i):
    return VIEWS + VIEW_STRIDE * i


# ============================================================ the scenarios


def vec(*xs):
    return " ".join(h(x) for x in xs)


def rrot(rnd):
    """A body matrix: a rotation by three random angles, now and then a
    scaled one, and a translation row."""
    a, b, c = (rnd.uniform(-math.pi, math.pi) for _ in range(3))
    ca, sa, cb, sb, cc, sc = (math.cos(a), math.sin(a), math.cos(b),
                              math.sin(b), math.cos(c), math.sin(c))
    rot = [[cb * cc, cb * sc, -sb],
           [sa * sb * cc - ca * sc, sa * sb * sc + ca * cc, sa * cb],
           [ca * sb * cc + sa * sc, ca * sb * sc - sa * cc, ca * cb]]
    m = []
    for r in range(3):
        m += [rot[r][0], rot[r][1], rot[r][2], 0.0]
    m += [rnd.uniform(-50, 50), rnd.uniform(-50, 50), rnd.uniform(-50, 50),
          1.0]
    if rnd.random() < 0.15:
        s = rnd.uniform(0.5, 2.0)
        for i in range(12):
            m[i] *= s
    return " ".join(h(x) for x in m)


def car_line(rnd, i, pos, ratio):
    """Car `i` at `pos`, its geometry position near it, a body matrix and
    the ratio round the track."""
    g = [p + rnd.uniform(-0.5, 0.5) for p in pos]
    return "K %d %s %s %s %s" % (i, vec(pos[0], pos[1], pos[2],
                                         rnd.choice((0.0, 1.0,
                                                     rnd.uniform(-2, 2)))),
                                 vec(g[0], g[1], g[2], 1.0), rrot(rnd),
                                 h(ratio))


def cams(n):
    out = []
    for k in range(n):
        out += ["C %d" % k, "V %d %d" % (k, k)]
    return out


def fov_table(rnd, kind):
    out = []
    for i in range(NFOV):
        if kind == 15:
            x = 20.0
        elif kind == 16:
            x = 20.0 - 0.25 * i
        else:
            x = rnd.uniform(8.0, 110.0)
        out.append("A f %d %s" % (i, vec(x, rnd.uniform(-1, 1) if kind
                                         not in (15, 16) else 0.0,
                                         0.0, rnd.uniform(-5, 5))))
    return out


def jumper_cd(rnd, kind, lo, hi, eye, other, horiz):
    """The record ChangeCameraMover builds for player types 15 and 16."""
    out = ["F Type 00000000", "F Name -", "F IsFOVIso 00000000",
           "F MinPercent %s" % h(lo), "F MaxPercent %s" % h(hi),
           "F EyeSplineSpeed 00000000", "F LookSplineSpeed 00000000",
           "F FOVSplineSpeed 00000000", "F LockEyeSpeedToCar 00000001",
           "F LockLookSpeedToCar 00000000",
           "F MinAreaPercent %s" % h(lo), "F MaxAreaPercent %s" % h(hi),
           "F NearClip %s" % h(0.5), "F FarClip %s" % h(10000.0),
           "F Backwards 00000000", "F FOVTable fovt",
           "F NumEyeVerts 00000002", "F EyeVerts eyev", "F BankVerts bankv",
           "F NumLookVerts 00000000", "F LookVerts -",
           "F SpringXVel 00000000", "F SpringYVel 00000000",
           "F SpringZVel 00000000", "F SpringDamp 00000000",
           "F SpringConst 00000000", "F LookOffsetX 00000000",
           "F LookOffsetY 00000000", "F LookOffsetZ 00000000",
           "F EnterVertComp %s" % h(0.2), "F EnterHorizComp %s" % h(horiz),
           "F LeaveVertComp 00000000", "F LeaveHorizComp 00000000",
           "F IsLeaveSet 00000000", "F WipeDistance 00000000",
           "F WipeAutoDisable 00000000"]
    out += fov_table(rnd, kind)
    for i, p in enumerate((eye, eye, other)):
        out.append("A e %d %s" % (i, vec(p[0], p[1], p[2], 0.0)))
    for i in range(3):
        out.append("A b %d %s" % (i, vec(0.0, 0.0, 0.0, 0.0)))
    out.append("H 00000000 00000002 00000000")
    for i in range(32):
        out.append("h %d %s" % (i, vec(0.0, 0.0, 0.0, 0.0)))
    return out


def s_jumper(rnd, kind):
    """A jump: the car flies off a ramp past the two eye points while its
    ratio round the track runs from the record's low to its high."""
    lo = rnd.uniform(0.1, 0.8)
    hi = lo + rnd.uniform(0.005, 0.03)
    start = [rnd.uniform(-800, 800), rnd.uniform(-800, 800),
             rnd.uniform(0, 60)]
    head = rnd.uniform(-math.pi, math.pi)
    fwd = (math.cos(head), math.sin(head))
    side = (-fwd[1], fwd[0])
    w = rnd.choice((-1, 1)) * rnd.uniform(5, 12)
    eye = [start[0] + fwd[0] * 30 + side[0] * w,
           start[1] + fwd[1] * 30 + side[1] * w, start[2] + 1.0]
    other = [start[0] + fwd[0] * 60 - side[0] * w,
             start[1] + fwd[1] * 60 - side[1] * w, start[2] + 1.0]
    out = cams(2)
    out += ["Y %08x" % rnd.getrandbits(32), "R %d" % rnd.choice((0, 0, 1))]
    out.append(car_line(rnd, 0, start, lo))
    out += jumper_cd(rnd, kind, lo, hi, eye, other,
                     rnd.choice((0.4, -0.4)))
    out += ["O 0 0 0 %d" % (1 if kind == 16 else 0), "G 0"]
    n = 40
    for i in range(n):
        f = (i + 1) / float(n)
        p = [start[0] + fwd[0] * 90 * f, start[1] + fwd[1] * 90 * f,
             start[2] + 25 * math.sin(math.pi * f)]
        r = lo + (hi - lo) * (f * 1.2 - 0.1)
        out.append(car_line(rnd, 0, p, r))
        if i % 9 == 4:
            out.append("T %s %s" % (h(rnd.choice((0.0, 1 / 60.0, 1 / 30.0,
                                                  0.05))),
                                    h(rnd.choice((1 / 60.0, 1 / 30.0)))))
        out.append("U 0")
    out += ["G 0", "D 0"]
    return out


def random_cd(rnd):
    out = []
    lo = rnd.uniform(0.0, 0.6)
    hi = lo + rnd.uniform(0.02, 0.4)
    if rnd.random() < 0.1:
        lo, hi = hi, lo
    alo = rnd.uniform(0.0, 0.6)
    ahi = alo + rnd.uniform(0.02, 0.4)
    nev = rnd.randrange(1, 7)
    vals = {
        "Type": rnd.randrange(0, 5), "IsFOVIso": rnd.choice((0, 1)),
        "MinPercent": lo, "MaxPercent": hi,
        "EyeSplineSpeed": rnd.uniform(0, 0.2),
        "LookSplineSpeed": rnd.uniform(0, 0.2),
        "FOVSplineSpeed": rnd.uniform(0, 0.2),
        "LockEyeSpeedToCar": rnd.choice((0, 1, 1)),
        "LockLookSpeedToCar": rnd.choice((0, 1)),
        "MinAreaPercent": alo, "MaxAreaPercent": ahi,
        "NearClip": rnd.uniform(0.1, 2.0),
        "FarClip": rnd.uniform(500.0, 20000.0),
        "Backwards": rnd.choice((0, 1)), "NumAreaVerts": rnd.randrange(0, 9),
        "NumAreaFaces": rnd.randrange(0, 9), "NumEyeVerts": nev,
        "NumLookVerts": rnd.randrange(0, 9),
        "SpringXVel": rnd.uniform(-0.2, 0.2),
        "SpringYVel": rnd.uniform(-0.2, 0.2),
        "SpringZVel": rnd.uniform(-0.2, 0.2),
        "SpringDamp": rnd.uniform(0.0, 0.5),
        "SpringConst": rnd.uniform(0.0, 0.3),
        "LookOffsetX": rnd.uniform(-2, 2), "LookOffsetY": rnd.uniform(-2, 2),
        "LookOffsetZ": rnd.uniform(-2, 2),
        "EnterVertComp": rnd.uniform(-0.5, 0.5),
        "EnterHorizComp": rnd.uniform(-0.5, 0.5),
        "LeaveVertComp": rnd.uniform(-0.5, 0.5),
        "LeaveHorizComp": rnd.uniform(-0.5, 0.5),
        "IsLeaveSet": rnd.choice((0, 1)),
        "WipeDistance": rnd.choice((0.0, 0.0, rnd.uniform(1, 10),
                                    -rnd.uniform(1, 10))),
        "WipeAutoDisable": rnd.choice((0, 1)),
        "ShakeBankNumber": rnd.randrange(0, 40),
    }
    # A wipe between one point and itself is 0 / 0 from its first frame.
    if vals["WipeDistance"] != 0.0 and nev < 2:
        nev = vals["NumEyeVerts"] = 2
    for name, off, kind in CD_FIELDS:
        if kind == "p":
            continue
        v = vals[name]
        out.append("F %s %08x" % (name, fb(v) if kind == "f" else v & M32))
    out += ["F Name %08x" % rnd.getrandbits(32), "F FOVTable fovt",
            "F AreaVerts %08x" % rnd.getrandbits(32),
            "F AreaFaces -", "F EyeVerts eyev", "F BankVerts bankv",
            "F LookVerts %08x" % rnd.getrandbits(32)]
    return out, nev


def random_world(rnd, nev, centre):
    out = fov_table(rnd, 0)
    for i in range(NEYE):
        p = [c + rnd.uniform(-30, 30) for c in centre]
        out.append("A e %d %s" % (i, vec(p[0], p[1], p[2],
                                         rnd.uniform(-1, 1))))
        out.append("A b %d %s" % (i, vec(rnd.uniform(-6000, 6000),
                                         rnd.uniform(-5, 5),
                                         rnd.uniform(-5, 5), 0.0)))
    ncv = rnd.randrange(1, 7)
    out.append("H %s %08x %08x" % (h(rnd.choice((0.0, rnd.uniform(0, 3)))),
                                   ncv, rnd.randrange(0, 40)))
    for i in range(32):
        out.append("h %d %s" % (i, vec(rnd.uniform(-0.5, 0.5),
                                       rnd.uniform(-0.5, 0.5),
                                       rnd.uniform(-0.5, 0.5),
                                       rnd.uniform(-1, 1))))
    return out


def s_random(rnd, frames):
    """A record of random values, a car moving through its window, and
    the clocks, the pause, the freeze and the direction changing on the
    way."""
    centre = [rnd.uniform(-500, 500), rnd.uniform(-500, 500),
              rnd.uniform(-20, 80)]
    out = cams(3)
    out += ["Y %08x" % rnd.getrandbits(32), "R %d" % rnd.choice((0, 1))]
    cd, nev = random_cd(rnd)
    out += cd + random_world(rnd, nev, centre)
    pos = [c + rnd.uniform(-20, 20) for c in centre]
    ratio = rnd.uniform(0, 1)
    out.append(car_line(rnd, 1, pos, ratio))
    out.append("Z %d" % rnd.choice((0, 0, 0, 1)))
    view = rnd.randrange(3)
    out += ["O 0 %d 1 %d" % (view, rnd.choice((0, 1))), "G 0", "Z 0"]
    vel = [rnd.uniform(-3, 3) for _ in range(3)]
    for i in range(frames):
        pos = [p + v for p, v in zip(pos, vel)]
        ratio = min(1.2, max(-0.2, ratio + rnd.uniform(-0.01, 0.03)))
        out.append(car_line(rnd, 1, pos, ratio))
        k = rnd.random()
        if k < 0.05:
            out.append("T %s %s" % (h(rnd.choice((0.0, rnd.uniform(0, 0.1)))),
                                    h(rnd.uniform(0, 0.1))))
        elif k < 0.08:
            out.append("Q %d" % rnd.choice((-1, 0, 6, 6, 5)))
        elif k < 0.10:
            out.append("Z %d" % rnd.choice((0, 0, 1)))
        elif k < 0.12:
            out.append("R %d" % rnd.choice((0, 1)))
        elif k < 0.14:
            out.append("W 0 ep %s" % h(rnd.uniform(-1, nev + 1)))
        elif k < 0.15:
            out.append("W 0 halt %08x" % rnd.choice((0, 1)))
        elif k < 0.16:
            out.append("W 0 val %s" % h(rnd.uniform(-60, 60)))
        out.append("U 0")
    out += ["Q -1", "G 0", "W 0 car -1", "G 0", "W 0 car 1",
            "Z %d" % rnd.choice((0, 1)), "D 0"]
    return out


def s_wipe(rnd):
    """The wipe: the eye on the line between the first and last eye points
    at the car's projection, pushed WipeDistance along it, until the car
    starts to pull away with WipeAutoDisable set."""
    out = cams(1)
    centre = [rnd.uniform(-300, 300), rnd.uniform(-300, 300), 10.0]
    for auto in (0, 1, 1):
        cd, nev = random_cd(rnd)
        out += cd + random_world(rnd, nev, centre)
        out += ["F WipeDistance %s" % h(rnd.choice((4.0, -3.0, 7.5))),
                "F WipeAutoDisable %08x" % auto,
                "F NumEyeVerts %08x" % rnd.randrange(2, 7)]
        pos = [centre[0] - 40, centre[1] - 40, 10.0]
        out.append(car_line(rnd, 0, pos, 0.5))
        out += ["O 0 0 0 1"]
        for i in range(30):
            pos = [pos[0] + 3.0, pos[1] + 3.0 + rnd.uniform(-1, 1),
                   pos[2] + rnd.uniform(-0.5, 0.5)]
            out.append(car_line(rnd, 0, pos, 0.5))
            out.append("U 0")
        out.append("D 0")
    return out


def s_ctor(rnd):
    """Construction: frozen and not, with and without the focus effects,
    seeds that take both signs, a stopped camera's render flags, then the
    vtable's other slots and the destructor, frozen and not."""
    out = cams(4)
    centre = [100.0, -200.0, 5.0]
    for i in range(10):
        out += ["N %d %08x %08x" % (i % 4, rnd.getrandbits(32),
                                    rnd.randrange(0, 3))]
        cd, nev = random_cd(rnd)
        out += cd + random_world(rnd, nev, centre)
        out.append(car_line(rnd, i % NCAR,
                            [c + rnd.uniform(-5, 5) for c in centre],
                            rnd.uniform(0, 1)))
        out += ["Y %08x" % rnd.getrandbits(32), "Z %d" % (i % 3 == 2),
                "L %d %s %s" % (i % 4, h(rnd.uniform(2, 90)),
                                h(rnd.uniform(0.5, 9))),
                "O %d %d %d %d" % (i % NMOV, i % 4, i % NCAR, i % 2),
                "G %d" % (i % NMOV), "Z %d" % (i % 4 == 1),
                "D %d" % (i % NMOV), "Z 0"]
    return out


def s_spline(rnd):
    """Spline on its own: the three types over a few arrays, at points
    before, inside and after, Evaluate with given weights, and the
    destructor with and without its blocks."""
    out = []
    for i in range(NEYE):
        out.append("A e %d %s" % (i, vec(*(rnd.uniform(-100, 100)
                                            for _ in range(4)))))
    for i in range(NFOV):
        out.append("A f %d %s" % (i, vec(*(rnd.uniform(-10, 10)
                                            for _ in range(4)))))
    for typ in (0, 1, 2):
        for n in (1, 2, 3, 5, 6):
            if typ == 2 and n < 2:
                continue
            ts = [-3.5, -1.0, -0.5, -1e-7, 0.0, 0.25, 0.999, 1.0, n - 1.5,
                  n - 1.0, n - 0.5, float(n), n + 0.75, n + 3.0, 1e9, -1e9]
            ts += [rnd.uniform(-3, n + 3) for _ in range(6)]
            for t in ts:
                out.append("s %d %d e %s" % (typ, n, h(t)))
            for _ in range(3):
                t = rnd.uniform(-2, n + 2)
                cs = [rnd.uniform(-1, 1) for _ in range(4)]
                out.append("e %d %d e %s %s" % (typ, n, h(t), vec(*cs)))
        for n in (16, 30):
            for _ in range(4):
                out.append("s %d %d f %s" % (typ, n, h(rnd.uniform(-2, 34))))
    for flags in (0, 1, 2, 3):
        for a, c in (("-", "-"), ("blk0", "-"), ("-", "blk1"),
                     ("blk0", "blk1")):
            out.append("x %d %s %s" % (flags, a, c))
    return out


def s_close(rnd):
    """The car within a unit of the eye, and at it: the field of view's
    distance is held at 1."""
    out = cams(1)
    eye = [rnd.uniform(-300, 300), rnd.uniform(-300, 300), 12.0]
    other = [eye[0] + 40.0, eye[1] - 25.0, 14.0]
    out += jumper_cd(rnd, 15, 0.4, 0.42, eye, other, 0.4)
    out += ["F IsFOVIso 00000001", "F EnterVertComp %s" % h(0.3)]
    out.append(car_line(rnd, 0, [eye[0] + 0.5, eye[1], eye[2]], 0.3))
    out += ["O 0 0 0 1"]
    for d in (0.0, 0.2, 0.5, 0.9, 0.99, 1.0, 1.01, 1.5, 3.0):
        for k in range(2):
            a = rnd.uniform(-math.pi, math.pi)
            out.append(car_line(rnd, 0, [eye[0] + d * math.cos(a),
                                         eye[1] + d * math.sin(a),
                                         eye[2] + 0.05 * k], 0.3))
            out.append("U 0")
    out.append("D 0")
    return out


def s_frozen(rnd):
    """Updates with the camera frozen and thawed in turn: a frozen camera
    keeps its field of view and focus. Then the far direction, the eye
    locked to the car, the car's ratio swept through the window."""
    out = cams(2)
    centre = [rnd.uniform(-300, 300), rnd.uniform(-300, 300), 10.0]
    cd, nev = random_cd(rnd)
    out += cd + random_world(rnd, nev, centre)
    out += ["F WipeDistance %s" % h(0.0), "F IsFOVIso 00000000",
            "F MinPercent %s" % h(0.1), "F MaxPercent %s" % h(0.9)]
    pos = [centre[0] + 5, centre[1] - 5, 10.0]
    out.append(car_line(rnd, 0, pos, 0.5))
    out += ["O 0 1 0 1"]
    for i in range(24):
        pos = [pos[0] + 1.5, pos[1] + 0.5, pos[2]]
        out.append(car_line(rnd, 0, pos, 0.1 + i * 0.033))
        out += ["Z %d" % (i % 3 != 0), "U 0"]
    out += ["Z 0", "D 0"]
    for r in (1, 0):
        cd, nev = random_cd(rnd)
        out += cd + random_world(rnd, nev, centre)
        out += ["R %d" % r, "F WipeDistance %s" % h(0.0),
                "F LockEyeSpeedToCar 00000001",
                "F NumEyeVerts %08x" % max(nev, 3),
                "F MinAreaPercent %s" % h(0.0),
                "F MaxAreaPercent %s" % h(1.0),
                "F MinPercent %s" % h(0.0), "F MaxPercent %s" % h(1.0)]
        out += ["O 1 0 0 0"]
        for i in range(60):
            out.append(car_line(rnd, 0, pos, rnd.uniform(0, 1)))
            out.append("U 1")
        out += ["D 1"]
    out.append("R 0")
    # The eye's own speed, the clocks changing, until it runs off the end.
    cd, nev = random_cd(rnd)
    out += cd + random_world(rnd, nev, centre)
    out += ["F WipeDistance %s" % h(0.0), "F LockEyeSpeedToCar 00000000",
            "F NumEyeVerts %08x" % max(nev, 3),
            "F EyeSplineSpeed %s" % h(rnd.uniform(0.03, 0.09))]
    out += ["O 2 0 0 0"]
    for i in range(50):
        if i % 5 == 0:
            out.append("T %s %s" % (h(rnd.uniform(0.01, 0.07)),
                                    h(rnd.uniform(0.01, 0.07))))
        out.append(car_line(rnd, 0, pos, rnd.uniform(0, 1)))
        out.append("U 2")
    # Single steps from nothing, where the step is the parameter, and from
    # just short of the last point, over it.
    last = max(nev, 3) - 1
    for i in range(40):
        out.append("T %s %s" % (h(rnd.uniform(0.005, 0.1)),
                                h(rnd.uniform(0.005, 0.1))))
        out.append("W 2 ep %s" % h(rnd.choice(
            (0.0, 0.0, last - rnd.uniform(0, 0.01), last + rnd.uniform(0, 1)))))
        out.append("U 2")
    out += ["D 2"]
    return out


def script():
    rnd = random.Random(0x7ca4ca11)
    sc = [s_spline(rnd), s_ctor(rnd), s_jumper(rnd, 15), s_jumper(rnd, 16),
          s_jumper(rnd, 15), s_jumper(rnd, 16), s_wipe(rnd),
          s_close(rnd), s_frozen(rnd)]
    for n in (60, 120, 200, 200, 300):
        sc.append(s_random(rnd, n))
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
        e.stub(VEC_DELETE, self.s_free)
        e.stub(DELETE, self.s_free)
        e.put32(JOLLY, 0)
        e.call(EMATH_SINIT)
        assert e.u32(TC_VTBL + SLOTS["update"]) == TC_UPDATE
        self.names = {0: "null", BASE_VTBL: "base", TC_VTBL: "track",
                      FOVT: "fovt", EYEV: "eyev", BANKV: "bankv",
                      SPL: "spl", BLK0: "blk0", BLK1: "blk1"}
        for k in range(NCAM):
            c = cam_at(k)
            self.names[c] = "c%d" % k
            self.names[c + 96] = "c%d.tgt" % k
        for j in range(NMOV):
            self.names[mov_at(j)] = "o%d" % j
            self.names[mov_at(j) + 320] = "o%d.cv" % j
        for i in range(NCAR):
            self.names[car_at(i)] = "k%d" % i
            self.names[car_at(i) + C_GPOS] = "k%d.gpos" % i
        for i in range(NVIEWS):
            self.names[view_at(i)] = "v%d" % i
            self.names[view_at(i) + V_LIST] = "v%d.list" % i

    def emit(self, s):
        self.out.append(s)

    def name(self, a):
        return self.names.get(a & M32, "?%08x" % (a & M32))

    def name_point(self, p):
        for a, n, s in ((FOVT, NFOV, "fovt"), (EYEV, NEYE, "eyev"),
                        (BANKV, NEYE, "bankv")):
            if a <= p < a + 16 * n:
                return "%s:%d" % (s, (p - a) // 16)
        return "ext"

    def s_free(self, em):
        self.emit("  free %s" % self.name(self.e.reg[4] & M32))

    def fill(self, a, n):
        self.e.write(a, bytes([PATTERN]) * n)

    def w(self, a):
        return self.e.u32(a)

    def put_words(self, a, t):
        for i, x in enumerate(t):
            self.e.put32(a + 4 * i, int(x, 16))

    def reset(self):
        e = self.e
        self.fill(CAMS, CAM_SIZE * NCAM)
        self.fill(MOVS, MOV_STRIDE * NMOV)
        self.fill(CARS, CAR_STRIDE * NCAR)
        self.fill(CDT, 164)
        self.fill(SHK, 560)
        self.fill(FOVT, 16 * NFOV)
        self.fill(EYEV, 16 * NEYE)
        self.fill(BANKV, 16 * NEYE)
        for i in range(NVIEWS):
            v = view_at(i)
            e.put32(v + V_CAMERA, 0)
            e.put32(v + V_LIST, v + V_LIST)
            e.put32(v + V_LIST + 4, v + V_LIST)
        e.put32(G_STOP, 0)
        e.put32(G_WTE, fb(1.0 / 30.0))
        e.put32(G_RTE, fb(1.0 / 30.0))
        e.put32(G_RC, 0)
        e.put32(TRACKDIR, 0)
        e.put32(G_SEED, 0x12345678)

    # ---- the dumps -------------------------------------------------------

    def vec4(self, a):
        return " ".join(fx(self.w(a + 4 * i)) for i in range(4))

    def vec3(self, a):
        return " ".join(fx(self.w(a + 4 * i)) for i in range(3))

    def dump_key(self, tag, a):
        w = self.w
        self.emit("    %s m %s" % (tag, " ".join(fx(w(a + 4 * i))
                                                  for i in range(16))))
        self.emit("    %s p %s d %s t %s" % (tag, self.vec4(a + 64),
                                             self.vec4(a + 80),
                                             self.vec4(a + 96)))
        self.emit("    %s s %s fov %04x" % (
            tag, " ".join(fx(w(a + 112 + 4 * i)) for i in range(5)),
            self.e.u16(a + 132)))

    def dump_cam(self, c):
        w = self.w
        self.emit("  %s" % self.name(c))
        self.dump_key("cur", c)
        self.dump_key("prev", c + 144)
        self.dump_key("vel", c + 288)
        self.emit("    clear %08x elapsed %s last %08x carnot %08x dash %08x"
                  % (w(c + 432), fx(w(c + 436)), w(c + 440), w(c + 444),
                     w(c + 448)))

    def dump_cd(self, a):
        parts = []
        for name, off, kind in CD_FIELDS:
            v = self.w(a + off)
            if kind == "p":
                parts.append(self.name(v))
            elif kind == "f":
                parts.append(fx(v))
            else:
                parts.append("%08x" % v)
        self.emit("    cd " + " ".join(parts))

    def dump_spline(self, tag, a):
        w = self.w
        self.emit("    %s %08x %08x %08x %s %s %08x %08x %08x %s %s %08x %s"
                  % (tag, w(a), w(a + 4), w(a + 8), self.name(w(a + 12)),
                     self.name(w(a + 16)), w(a + 20), w(a + 24), w(a + 28),
                     fx(w(a + 32)), fx(w(a + 36)), w(a + 40),
                     self.name(w(a + 44))))

    def dump_mov(self, j):
        m = mov_at(j)
        w, u16 = self.w, self.e.u16
        self.emit("  o%d type %d view %d en %d pview %s pcam %s player %08x"
                  " carnot %08x dash %08x vtbl %s next %s prev %s pad %08x"
                  % (j, s32(w(m + 8)), s32(w(m + 12)), s32(w(m + 16)),
                     self.name(w(m + 20)), self.name(w(m + 24)), w(m + 28),
                     w(m + 32), w(m + 36), self.name(w(m + 40)),
                     self.name(w(m)), self.name(w(m + 4)), w(m + 44)))
        self.emit("    look %s sv %s sd %s k %s d %s"
                  % (self.vec3(m + 48), self.vec3(m + 64), self.vec3(m + 80),
                     fx(w(m + 96)), fx(w(m + 100))))
        self.dump_cd(m + 104)
        self.emit("    pad %08x shk %s"
                  % (w(m + 268), bytes(self.e.mem[m + 272:m + 832]).hex()))
        for tag, off in (("fov", 832), ("eye", 880), ("bank", 928),
                         ("shake", 976)):
            self.dump_spline(tag, m + off)
        self.emit("    ep %s sp %s pad %08x %08x ws %s we %s halt %08x"
                  " apart %s car %s"
                  % (fx(w(m + 1024)), fx(w(m + 1028)), w(m + 1032),
                     w(m + 1036), self.vec4(m + 1040), self.vec4(m + 1056),
                     w(m + 1072), fx(w(m + 1076)), self.name(w(m + 1080))))
        c = m + 1084
        self.emit("    cub %s st %04x fl %04x fe %08x"
                  % (" ".join(fx(w(c + 4 * i)) for i in range(11)),
                     u16(c + 44), u16(c + 46), w(m + 1132)))

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
        self.emit("  views %s" % (" ".join(parts) or "-"))

    # ---- the ops ---------------------------------------------------------

    def vcall(self, j, slot, *args):
        e = self.e
        m = mov_at(j)
        vt = self.w(m + 40)
        delta = struct.unpack("<h", struct.pack("<H", e.u16(vt + slot - 4)))[0]
        fn = self.w(vt + slot)
        return e.call(fn, (m + delta) & M32, *args, limit=2000000)

    def call(self, fn, *args, **f):
        e = self.e
        for i, v in f.items():
            e.fpr[int(i[1:])] = v & M32
        return e.call(fn, *args, limit=2000000)

    def query(self, j):
        e = self.e
        info = self.vcall(j, SLOTS["info"]) & M32
        pov0 = self.vcall(j, SLOTS["pov"], 0) & M32
        ext = self.vcall(j, SLOTS["ext"])
        lb = self.vcall(j, SLOTS["lookback"])
        self.vcall(j, SLOTS["gap"])
        gap = e.fpr[0]
        car = self.vcall(j, SLOTS["car"]) & M32
        tgt = self.vcall(j, SLOTS["target"]) & M32
        self.emit("  q o%d info %s pov %s ext %d lb %d gap %s car %s tgt %s"
                  % (j, self.name(info), self.name(pov0), ext, lb, fx(gap),
                     self.name(car), self.name(tgt)))

    def sym(self, s):
        return SYMS[s] if s in SYMS else int(s, 16)

    def spline_op(self, t, evaluate):
        typ, n, arr = int(t[1]), int(t[2]), ARRAYS[t[3]]
        tt = int(t[4], 16)
        self.fill(SPL, 48)
        self.call(SPL_CTOR, SPL, typ, n, arr, 16384)
        self.dump_spline("spl", SPL)
        self.fill(OUTV, 16)
        if evaluate:
            cs = [int(x, 16) for x in t[5:9]]
            self.call(SPL_EVAL, SPL, OUTV, f12=tt, f13=cs[0], f14=cs[1],
                      f15=cs[2], f16=cs[3])
            self.emit("  ev o %s" % self.vec4(OUTV))
            return
        p = self.call(SPL_GCP, SPL, f12=tt) & M32
        line = "  cp %s v %s" % (self.name_point(p), self.vec4(p))
        self.call(SPL_GETPT, SPL, OUTV, f12=tt)
        self.emit(line + " o %s" % self.vec4(OUTV))

    def op(self, t):
        e = self.e
        c = t[0]
        if c == "C":
            k = int(t[1])
            self.fill(cam_at(k), CAM_SIZE)
            e.call(CAM_CTOR, cam_at(k), limit=200000)
            self.dump_cam(cam_at(k))
        elif c == "N":
            k = int(t[1])
            e.put32(cam_at(k) + 444, int(t[2], 16))
            e.put32(cam_at(k) + 448, int(t[3], 16))
        elif c == "L":
            k = int(t[1])
            e.put32(cam_at(k) + 116, int(t[2], 16))
            e.put32(cam_at(k) + 120, int(t[3], 16))
        elif c == "P":
            self.dump_cam(cam_at(int(t[1])))
        elif c == "V":
            e.put32(view_at(int(t[1])) + V_CAMERA, cam_at(int(t[2])))
        elif c == "Z":
            e.put32(G_STOP, int(t[1]))
        elif c == "T":
            e.put32(G_WTE, int(t[1], 16))
            e.put32(G_RTE, int(t[2], 16))
        elif c == "Q":
            s = int(t[1])
            if s < 0:
                e.put32(G_RC, 0)
            else:
                e.put32(RC, s)
                e.put32(G_RC, RC)
        elif c == "R":
            e.put32(TRACKDIR, int(t[1]))
        elif c == "Y":
            e.put32(G_SEED, int(t[1], 16))
        elif c == "K":
            a = car_at(int(t[1]))
            self.put_words(a + C_POS, t[2:6])
            self.put_words(a + C_GPOS, t[6:10])
            self.put_words(a + C_BODY, t[10:26])
            e.put32(a + C_RATIO, int(t[26], 16))
        elif c == "A":
            self.put_words(ARRAYS[t[1]] + 16 * int(t[2]), t[3:7])
        elif c == "F":
            off, kind = CD_BY_NAME[t[1]]
            e.put32(CDT + off, self.sym(t[2]) if kind == "p"
                    else int(t[2], 16))
        elif c == "H":
            e.put32(SHK + 36, int(t[1], 16))
            e.put32(SHK + 40, int(t[2], 16))
            e.put32(SHK + 32, int(t[3], 16))
        elif c == "h":
            self.put_words(SHK + 48 + 16 * int(t[1]), t[2:6])
        elif c == "O":
            j, view, car, fe = (int(x) for x in t[1:5])
            self.fill(mov_at(j), MOV_STRIDE)
            self.call(TC_CTOR, mov_at(j), view, car_at(car), CDT, SHK, fe)
            self.dump_mov(j)
            self.dump_views()
            self.dump_cam(self.w(mov_at(j) + 24))
        elif c == "D":
            j = int(t[1])
            cam = self.w(mov_at(j) + 24)
            self.vcall(j, SLOTS["destroy"], 0)
            self.dump_mov(j)
            self.dump_views()
            self.dump_cam(cam)
        elif c == "U":
            j = int(t[1])
            self.vcall(j, SLOTS["update"])
            self.dump_mov(j)
            self.dump_cam(self.w(mov_at(j) + 24))
        elif c == "G":
            self.query(int(t[1]))
        elif c == "W":
            j = int(t[1])
            off, kind = MOV_FIELDS[t[2]]
            a = mov_at(j) + off
            if kind == "car":
                e.put32(a, car_at(int(t[3])))
            else:
                e.put32(a, int(t[3], 16))
        elif c == "s":
            self.spline_op(t, False)
        elif c == "e":
            self.spline_op(t, True)
        elif c == "x":
            self.fill(SPL, 48)
            self.call(SPL_CTOR, SPL, 0, 4, EYEV, 16384)
            e.put32(SPL + 16, self.sym(t[2]))
            e.put32(SPL + 44, self.sym(t[3]))
            self.call(SPL_DTOR, SPL, int(t[1]))
            self.emit("  destroyed")
        else:
            raise SystemExit("bad op %r" % (t,))

    def run(self, scenarios):
        for i, sc in enumerate(scenarios):
            self.emit("B %d" % i)
            self.reset()
            for ln in sc:
                if ln[0] not in "AFHhK":
                    self.emit("> " + ln[:40])
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


def build_harness(tmp, name="trackcarcam_test"):
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


def M(name, before, after, rel=TCC):
    return (name, rel, before, after)


MUTATIONS = [
    # The vtable.
    M("vt-clocks", "WorldTimeElapsed," + NL
      + "                                  RealTimeElapsed);",
      "RealTimeElapsed," + NL
      + "                                  WorldTimeElapsed);"),
    M("vt-car", "return ((TrackCarCameraMover *)m)->CarToFollow;",
      "return NULL;"),

    # The constructor.
    M("ctor-vtbl", "m->base.vtbl = &TrackCarCameraMoverVtbl;" + NL
      + "    m->CD = *cd;", "m->CD = *cd;"),
    M("ctor-fov-n", "SPLINE_CLAMP, 32, m->CD.FOVTable",
      "SPLINE_CLAMP, 31, m->CD.FOVTable"),
    M("ctor-eye-type", "spline_init(&m->EyeSpline, SPLINE_CLAMP,",
      "spline_init(&m->EyeSpline, SPLINE_EXTRAPOLATE,"),
    M("ctor-bank-verts", "m->CD.BankVerts, TRACK_CAR_SPLINE_TABLE",
      "m->CD.EyeVerts, TRACK_CAR_SPLINE_TABLE"),
    M("ctor-shake-n", "m->TheCameraShake.NumCVs," + NL,
      "m->TheCameraShake.NumCVs + 1," + NL),
    M("ctor-table", "#define TRACK_CAR_SPLINE_TABLE 16384",
      "#define TRACK_CAR_SPLINE_TABLE 16383"),
    M("ctor-ep", "    m->EyeSplineParam = 0.0f;",
      "    m->EyeSplineParam = 1.0f;"),
    M("ctor-sp", "    m->ShakeSplineParam = 0.0f;",
      "    m->ShakeSplineParam = 0.5f;"),
    M("ctor-flags", "    c->flags = 1;" + NL + "    c->duration",
      "    c->flags = 0;" + NL + "    c->duration"),
    M("ctor-threshold", "c->arrivalThreshold = 1.0f;",
      "c->arrivalThreshold = 2.0f;"),
    M("ctor-dval", "    c->dval = 0.0f;", "    c->dval = 1.0f;"),
    M("ctor-dvd", "    c->dvalDesired = 0.0f;", "    c->dvalDesired = 1.0f;"),
    M("ctor-carnot", "        cam->CarNotToRender = NULL;" + NL, ""),
    M("ctor-dash", "        cam->RenderDash = 0;" + NL, ""),
    M("ctor-stop", "    if (!CameraStopUpdating) {" + NL
      + "        cam->CarNotToRender = NULL;",
      "    if (1) {" + NL + "        cam->CarNotToRender = NULL;"),
    M("ctor-look", "m->Look = car->State.Position;" + NL + "    // The pad",
      "m->Look = car->State.GeometryPosition;" + NL + "    // The pad"),
    M("ctor-svx", "m->SpringVelocity.x = m->CD.SpringXVel;",
      "m->SpringVelocity.x = m->CD.SpringYVel;"),
    M("ctor-svz", "m->SpringVelocity.z = m->CD.SpringYVel;",
      "m->SpringVelocity.z = m->CD.SpringZVel;"),
    M("ctor-k", "m->SpringConstant = m->CD.SpringConst;",
      "m->SpringConstant = m->CD.SpringDamp;"),
    M("ctor-d", "m->DampingConstant = m->CD.SpringDamp;",
      "m->DampingConstant = m->CD.SpringConst;"),
    M("ctor-sd", "    m->SpringDisplacement.y = 0.0f;",
      "    m->SpringDisplacement.y = 1.0f;"),
    M("ctor-ws", "m->WipeStart = m->CD.EyeVerts[0];",
      "m->WipeStart = m->CD.EyeVerts[1];"),
    M("ctor-we", "m->WipeEnd = m->CD.EyeVerts[m->CD.NumEyeVerts - 1];",
      "m->WipeEnd = m->CD.EyeVerts[m->CD.NumEyeVerts - 2];"),
    M("ctor-apart", "#define TRACK_CAR_WIPE_FAR    1000000.0f",
      "#define TRACK_CAR_WIPE_FAR    100.0f"),
    M("ctor-near", "cam->CurrentKey.NearZ = m->CD.NearClip;",
      "cam->CurrentKey.NearZ = 0.5f;"),
    M("ctor-far", "    cam->CurrentKey.FarZ = m->CD.FarClip;" + NL, ""),
    M("ctor-halt", "    m->WipeTrackingHalted = 0;",
      "    m->WipeTrackingHalted = 1;"),
    M("ctor-time", "#define TRACK_CAR_FOCAL_TIME  0.42f",
      "#define TRACK_CAR_FOCAL_TIME  0.5f"),
    M("ctor-rand-range", "r = bRandomI(19, bViewSeed) + 26;",
      "r = bRandomI(20, bViewSeed) + 26;"),
    M("ctor-rand-base", "r = bRandomI(19, bViewSeed) + 26;",
      "r = bRandomI(19, bViewSeed) + 25;"),
    M("ctor-rand-sign", "if (bRandomI(2, bViewSeed) != 0)",
      "if (bRandomI(2, bViewSeed) == 0)"),
    M("ctor-vdes", "    c->valDesired = 0.0f;" + NL + "    if (c->val != 0.0f)",
      "    c->valDesired = 1.0f;" + NL + "    if (c->val != 0.0f)"),
    M("ctor-focus-stop", "if (!m->FocusEffects && !CameraStopUpdating)",
      "if (!m->FocusEffects)"),
    M("ctor-focus", "if (!m->FocusEffects && !CameraStopUpdating)",
      "if (!CameraStopUpdating)"),
    M("ctor-fe", "m->FocusEffects = focusEffects;", "m->FocusEffects = 1;"),

    # The destructor.
    M("dtor-stop", "    m->base.vtbl = &TrackCarCameraMoverVtbl;" + NL
      + "    if (!CameraStopUpdating) {",
      "    m->base.vtbl = &TrackCarCameraMoverVtbl;" + NL + "    if (1) {"),
    M("dtor-dof", "        cam->CurrentKey.DepthOfField = 0.0f;" + NL
      + "    }" + NL + "    cam->ClearVelocity = 1;",
      "        cam->CurrentKey.DepthOfField = 1.0f;" + NL
      + "    }" + NL + "    cam->ClearVelocity = 1;"),
    M("dtor-clear", "    cam->ClearVelocity = 1;", "    cam->ClearVelocity = 0;"),
    M("dtor-base", "    camera_mover_destroy(&m->base);" + NL, ""),

    # CalcSpringForce and GetTarget.
    M("spr-damp", "v_scale(&d, velocity, m->DampingConstant);",
      "v_scale(&d, velocity, m->SpringConstant);"),
    M("spr-add", "    v_add(o, &d, &s);", "    v_sub(o, &d, &s);"),
    M("tgt-pos", "return &m->CarToFollow->State.GeometryPosition;",
      "return &m->CarToFollow->State.Position;"),
    M("tgt-null", "    if (m->CarToFollow != NULL)" + NL + "        return",
      "    if (0)" + NL + "        return"),

    # The compensations.
    M("comp-leave", "float c = enter + t * (leave - enter);",
      "float c = leave + t * (enter - leave);"),
    M("comp-t", "float c = enter + t * (leave - enter);",
      "float c = enter + (1.0f - t) * (leave - enter);"),
    M("comp-tan", "        tanHalf = bSinBam(half) / bCosBam(half);" + NL
      + "        return c",
      "        tanHalf = bCosBam(half) / bSinBam(half);" + NL
      + "        return c"),
    M("comp-enter", "return enter * dist * tanHalf;",
      "return enter * tanHalf;"),
    M("comp-order", "return enter * dist * tanHalf;",
      "return enter * (dist * tanHalf);"),

    # Update: the pause, the percentages, the eye.
    M("upd-pause", "    if (is_game_flow_paused())" + NL + "        return;" + NL,
      ""),
    M("upd-dir", "if (RaceParametersTrackDirection == 0)",
      "if (RaceParametersTrackDirection != 0)"),
    M("upd-pct", "pct = ratio * 100.0f * 0.01f;", "pct = ratio;"),
    M("upd-pct-rev", "pct = (100.0f - ratio * 100.0f) * 0.01f;",
      "pct = 1.0f - ratio;"),
    M("upd-area-lo", "    if (area < 0.0f)" + NL + "        area = 0.0f;" + NL,
      ""),
    M("upd-area-hi", "    if (1.0f < area)" + NL + "        area = 1.0f;" + NL,
      ""),
    M("upd-area-min", "area = (pct - cd->MinAreaPercent)",
      "area = (pct - cd->MinPercent)"),
    M("upd-wipe-test", "if (cd->WipeDistance == 0.0f) {",
      "if (cd->WipeDistance <= 0.0f) {"),
    M("upd-lock", "if (cd->LockEyeSpeedToCar)", "if (!cd->LockEyeSpeedToCar)"),
    M("upd-lock-last", "m->EyeSplineParam = last * area;",
      "m->EyeSplineParam = area;"),
    M("upd-speed", "cd->EyeSplineSpeed * dt * 25.0f;",
      "cd->EyeSplineSpeed * dt * 30.0f;"),
    M("upd-speed-order", "cd->EyeSplineSpeed * dt * 25.0f;",
      "cd->EyeSplineSpeed * (dt * 25.0f);"),
    M("upd-eye-clamp", "        if (last < m->EyeSplineParam)" + NL
      + "            m->EyeSplineParam = last;" + NL, ""),
    M("upd-wipe-halted", "if (!m->WipeTrackingHalted) {", "if (1) {"),
    M("upd-wipe-a-hi", "            if (1.0f < a)" + NL
      + "                a = 1.0f;" + NL, ""),
    M("upd-wipe-a-lo", "            if (a < 0.0f)" + NL
      + "                a = 0.0f;" + NL, ""),
    M("upd-wipe-norm", "bNormalize3To(&n, &d, cd->WipeDistance);",
      "bNormalize3To(&n, &d, 1.0f);"),
    M("upd-wipe-base", "v_add(&eye, &m->WipeStart, &s);",
      "v_add(&eye, &m->WipeEnd, &s);"),
    M("upd-wipe-proj", "a = v_dot(&d, &v) / v_dot(&d, &d);",
      "a = v_dot(&d, &v) / v_dot(&v, &v);"),
    M("upd-wipe-push", "            v_add(&eye, &eye, &n);" + NL, ""),
    M("upd-halt-eye", "            eye = cam->CurrentKey.Position;",
      "            eye = cam->CurrentKey.Target;"),
    M("upd-auto", "if (cd->WipeAutoDisable) {", "if (0) {"),
    M("upd-auto-cmp", "if (m->WipeDistApart < dist)",
      "if (dist < m->WipeDistApart)"),
    M("upd-auto-apart", "            m->WipeDistApart = dist;" + NL, ""),

    # Update: the field of view and the shake.
    M("upd-span-lo", "    if (span < 0.0f)" + NL + "        span = 0.0f;" + NL,
      ""),
    M("upd-span-hi", "    if (1.0f < span)" + NL + "        span = 1.0f;" + NL,
      ""),
    M("upd-span-31", "span * 31.0f", "span * 32.0f"),
    M("upd-span-max", "/ (cd->MaxPercent - cd->MinPercent);",
      "/ (cd->MaxAreaPercent - cd->MinPercent);"),
    M("upd-dist-clamp", "    if (dist < 1.0f)" + NL + "        dist = 1.0f;" + NL,
      ""),
    M("upd-iso", "if (cd->IsFOVIso)", "if (!cd->IsFOVIso)"),
    M("upd-iso-q", "bATan(dist, fov.x * 0.25f) << 1",
      "bATan(dist, fov.x * 0.5f) << 1"),
    M("upd-iso-arg", "bATan(dist, fov.x * 0.25f)", "bATan(fov.x * 0.25f, dist)"),
    M("upd-deg", "#define TRACK_CAR_DEG_TO_BAM  182.044449f",
      "#define TRACK_CAR_DEG_TO_BAM  182.0f"),
    M("upd-fov-stop", "    if (!CameraStopUpdating)" + NL
      + "        cam->CurrentKey.FieldOfView = fovBam;",
      "    cam->CurrentKey.FieldOfView = fovBam;"),
    M("upd-shake-dt", "m->ShakeSplineParam + m->TheCameraShake.Speed * dt;",
      "m->ShakeSplineParam + m->TheCameraShake.Speed * elapsed;"),
    M("upd-shake-clamp", "    if ((float)(m->TheCameraShake.NumCVs - 1)"
      " < m->ShakeSplineParam)" + NL
      + "        m->ShakeSplineParam = (float)(m->TheCameraShake.NumCVs - 1);"
      + NL, ""),

    # Update: the look point.
    M("upd-look-reset", "    m->Look = car->State.Position;" + NL + "    half",
      "    half"),
    M("upd-half", "half = (uint16_t)(fovBam >> 1);", "half = fovBam;"),
    M("upd-vert-shake", "m->Look.z + (comp - shake.y);",
      "m->Look.z + (comp + shake.y);"),
    M("upd-vert-shake-x", "(comp - shake.y)", "(comp - shake.x)"),
    M("upd-vert-area", "cd->LeaveVertComp, area, dist,",
      "cd->LeaveVertComp, pct, dist,"),
    M("upd-horiz-enter", "compensation(cd, cd->EnterHorizComp,",
      "compensation(cd, cd->EnterVertComp,"),
    M("upd-horiz-leave", "cd->EnterHorizComp, cd->LeaveHorizComp,",
      "cd->EnterHorizComp, cd->LeaveVertComp,"),
    M("upd-unit", "    v_scale(&toEye, &toEye, 1.0f / dist);" + NL, ""),
    M("upd-cross-sign", "side.x = toEye.y * up.z - up.y * toEye.z;",
      "side.x = up.y * toEye.z - toEye.y * up.z;"),
    M("upd-cross-y", "side.y = toEye.z * up.x - up.z * toEye.x;",
      "side.y = up.z * toEye.x - toEye.z * up.x;"),
    M("upd-side-shake", "v_scale(&side, &side, comp + shake.x);",
      "v_scale(&side, &side, comp);"),
    M("upd-side-y", "    m->Look.y = m->Look.y + side.y;" + NL, ""),
    M("upd-off-body", "    eMulVector3(&off, &car->State.BodyMatrix, &off);"
      + NL, ""),
    M("upd-off-y", "off.y = cd->LookOffsetY;", "off.y = cd->LookOffsetX;"),
    M("upd-off-z", "off.z = cd->LookOffsetZ;", "off.z = cd->LookOffsetY;"),

    # Update: the spring.
    M("upd-dir-norm", "v_scale(&dir, &dir, 1.0f / sqrtf(v_dot(&dir, &dir)));",
      "v_scale(&dir, &dir, 1.0f);"),
    M("upd-spring-args", "&m->SpringDisplacement," + NL
      + "                                             &m->SpringVelocity);",
      "&m->SpringVelocity," + NL
      + "                                             &m->SpringDisplacement);"),
    M("upd-sv", "v_sub(&m->SpringVelocity, &m->SpringVelocity, &force);",
      "v_add(&m->SpringVelocity, &m->SpringVelocity, &force);"),
    M("upd-sd", "v_add(&m->SpringDisplacement, &m->SpringDisplacement,",
      "v_sub(&m->SpringDisplacement, &m->SpringDisplacement,"),
    M("upd-dir-disp", "    v_add(&dir, &dir, &m->SpringDisplacement);" + NL, ""),
    M("upd-look-eye", "v_add(&m->Look, &eye, &dir);",
      "v_add(&m->Look, &m->Look, &dir);"),

    # Update: the bank, the matrix and the camera.
    M("upd-bank-param",
      "spline_get_point(&m->BankSpline, &bank, m->EyeSplineParam);",
      "spline_get_point(&m->BankSpline, &bank, 0.0f);"),
    M("upd-bank-x", "(uint16_t)ee_trunc_w(bank.x)", "(uint16_t)ee_trunc_w(bank.y)"),
    M("upd-bank-up", "camera_mover_compute_banked_up_vector(&m->base, &up,",
      "camera_mover_compute_banked_up_vector(&m->base, &bank,"),
    M("upd-td-pos", "        v_sub(&d, &car->State.Position, &eye);" + NL
      + "        dist = sqrtf(v_dot(&d, &d));" + NL + "    }",
      "        v_sub(&d, &car->State.GeometryPosition, &eye);" + NL
      + "        dist = sqrtf(v_dot(&d, &d));" + NL + "    }"),
    M("upd-td-stop", "    if (!CameraStopUpdating)" + NL
      + "        cam->CurrentKey.TargetDistance = dist;",
      "    cam->CurrentKey.TargetDistance = dist;"),
    M("upd-near", "    cam->CurrentKey.NearZ = 0.5f;",
      "    cam->CurrentKey.NearZ = 1.0f;"),
    M("upd-focal-speed", "#define TRACK_CAR_FOCAL_SPEED 6.27f",
      "#define TRACK_CAR_FOCAL_SPEED 6.0f"),
    M("upd-seek", "    bspline_seek(c, dt);", "    bspline_seek(c, elapsed);"),
    M("upd-focal-min", "    if (focal < 2.0f)" + NL + "        focal = 2.0f;" + NL,
      ""),
    M("upd-focal-val", "cam->CurrentKey.FocalDistance = focal + c->val;",
      "cam->CurrentKey.FocalDistance = focal;"),
    M("upd-dof", "cam->CurrentKey.DepthOfField = 7.5f;",
      "cam->CurrentKey.DepthOfField = 8.0f;"),
    M("upd-focus-stop", "if (m->FocusEffects && !CameraStopUpdating) {",
      "if (m->FocusEffects) {"),
    M("upd-elapsed", "camera_set_matrix(cam, &mat, elapsed);",
      "camera_set_matrix(cam, &mat, dt);"),

    # Spline.
    M("sp-dirty", "    s->Dirty = 1;", "    s->Dirty = 0;", SPC),
    M("sp-buffer", "    s->ControlPointBufferSize = n;",
      "    s->ControlPointBufferSize = 0;", SPC),
    M("sp-length", "    s->Length = 0.0f;", "    s->Length = 1.0f;", SPC),
    M("sp-table", "    s->TableSize = tableSize;", "    s->TableSize = 0;", SPC),
    M("sp-array", "    s->pControlPointArray = NULL;" + NL + "    return s;",
      "    return s;", SPC),
    M("sp-dtor-arr", "    if (s->pControlPointArray != NULL)" + NL
      + "        bFree(s->pControlPointArray);" + NL, "", SPC),
    M("sp-dtor-cal", "    if (s->pCalTable != NULL)" + NL
      + "        bFree(s->pCalTable);" + NL, "", SPC),
    M("sp-dtor-self", "    if (flags & 1)", "    if (flags & 2)", SPC),
    M("sp-loop-last", "        last = (float)n;", "        last = (float)(n - 1);",
      SPC),
    M("sp-clamp-last", "SPLINE_EXTRAPOLATE)" + NL + "        last = (float)(n - 1);",
      "SPLINE_EXTRAPOLATE)" + NL + "        last = (float)n;", SPC),
    M("sp-loop", "        t = bFMod(t, last);",
      "        t = bFMod(t, last + 1.0f);", SPC),
    M("sp-clamp-hi", "        else if (last < t)" + NL + "            t = last;",
      "        else if (last + 1.0f < t)" + NL + "            t = last;", SPC),
    M("sp-ext-lo-t", "scale_add(&SplineExtrapolated, &d, t, &cv[0]);",
      "scale_add(&SplineExtrapolated, &d, -t, &cv[0]);", SPC),
    M("sp-ext-lo-d", "            d.y = cv[1].y - cv[0].y;",
      "            d.y = cv[0].y - cv[1].y;", SPC),
    M("sp-ext-lo-pad", "            d.pad = cv[1].pad - cv[0].pad;",
      "            d.pad = 0.0f;", SPC),
    M("sp-ext-hi-t", "scale_add(&SplineExtrapolated, &d, t - last, e);",
      "scale_add(&SplineExtrapolated, &d, t, e);", SPC),
    M("sp-ext-hi-base", "scale_add(&SplineExtrapolated, &d, t - last, e);",
      "scale_add(&SplineExtrapolated, &d, t - last, e - 1);", SPC),
    M("sp-ext-hi-z", "            d.z = e->z - e[-1].z;",
      "            d.z = e->z - e[-2].z;", SPC),
    M("sp-ext-lt", "        if (t < 0.0f) {", "        if (t <= 0.0f) {", SPC),
    M("sp-ext-gt", "        if (last < t) {", "        if (last <= t) {", SPC),
    M("sp-trunc", "    return &cv[ee_trunc_w(t)];",
      "    return &cv[ee_trunc_w(t + 0.5f)];", SPC),
    M("sp-eval-t", "p = spline_get_control_point(s, t - 1.0f);",
      "p = spline_get_control_point(s, t - 2.0f);", SPC),
    M("sp-eval-c2", "scale_add(&acc, p, c2, &acc);",
      "scale_add(&acc, p, c1, &acc);", SPC),
    M("sp-eval-first", "    acc.x = p->x * c0;", "    acc.x = p->x * c1;", SPC),
    M("sp-eval-pad", "    acc.pad = p->pad * c0;", "    acc.pad = 0.0f;", SPC),
    M("sp-eval-t2", "p = spline_get_control_point(s, t + 2.0f);",
      "p = spline_get_control_point(s, t + 1.0f);", SPC),
    M("sp-floor", "    if (t < base)" + NL + "        base = base - 1.0f;" + NL,
      "", SPC),
    M("sp-c3", "c3 = (u3 - u2) * 0.5f;", "c3 = (u3 - u) * 0.5f;", SPC),
    M("sp-c0-order", "c0 = (((u2 + u2) - u3) - u) * 0.5f;",
      "c0 = ((u2 + u2) - (u3 + u)) * 0.5f;", SPC),
    M("sp-c1", "c1 = ((u3 * 3.0f - u2 * 5.0f) + 2.0f) * 0.5f;",
      "c1 = ((u3 * 3.0f - u2 * 5.0f) + 1.0f) * 0.5f;", SPC),
    M("sp-c2-order", "c2 = ((u2 * 4.0f - u3 * 3.0f) + u) * 0.5f;",
      "c2 = (u2 * 4.0f - (u3 * 3.0f - u)) * 0.5f;", SPC),
    M("sp-base", "spline_evaluate(s, o, base, c0, c1, c2, c3);",
      "spline_evaluate(s, o, t, c0, c1, c2, c3);", SPC),

    # ComputeBankedUpVector.
    M("bank-axis", "    axis.x = look->x - eye->x;",
      "    axis.x = eye->x - look->x;", CMC),
    M("bank-norm", "q = 1.0f / sqrtf((axis.x * axis.x + axis.y * axis.y)"
      " + axis.z * axis.z);", "q = 1.0f;", CMC),
    M("bank-norm-order", "q = 1.0f / sqrtf((axis.x * axis.x + axis.y * axis.y)"
      " + axis.z * axis.z);",
      "q = 1.0f / sqrtf(axis.x * axis.x + (axis.y * axis.y"
      " + axis.z * axis.z));", CMC),
    M("bank-up", "    up.z = 1.0f;" + NL + "    up.pad = 0.0f;" + NL
      + "    eMulVector3(out, &r, &up);",
      "    up.z = -1.0f;" + NL + "    up.pad = 0.0f;" + NL
      + "    eMulVector3(out, &r, &up);", CMC),
    M("bank-roll", "eCreateAxisRotationMatrix(&r, &axis, roll);",
      "eCreateAxisRotationMatrix(&r, &axis, (uint16_t)-roll);", CMC),
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
        todo, SOURCES, "trackcarcam_test",
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
