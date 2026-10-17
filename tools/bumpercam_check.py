#!/usr/bin/env python3
"""Cross-check 3DS Files/source/bumpercam.c, the pre-race's mover, against
the retail image itself, run in mipsemu.

The model is the image. BumperCameraMover's constructor (0x00158800),
destructor (0x00158910), Update (0x00158a68), IsFinished (0x001589c8),
GetTarget (0x001589a8), GetCarToFollow (0x0015fb10) and the wall routine
Update calls while the race is racing (0x00157c60) run as shipped,
through retail's vtable (0x002b1bd0) where the game goes through it, with
IsFinished called directly as PreRaceCameraCoordinator::Update calls it.
Under them run Spline, the CameraMover base and its ComputeBankedUpVector,
Camera::SetCameraMatrix, the matrix layer, bATan and IsGameFlowPaused,
over retail's own eView table. The harness (tools/src/bumpercam_test.c)
runs the port over the same script, and the two transcripts are diffed.

Stubs, each printing what it was given as the harness's stand-ins do:
TopologyCoordinate's constructor (0x00151c28) and destructor (0x00151c70),
SetInterestBBox (0x00136e00), GetElevation (0x00152070), GetRoadNoise
(0x00153498), Car::GetCarSpaceBoundingBox (0x00135170) and the two wall
helpers (0x00157930, 0x00157b60; drivecam_check runs those). The road
noise cycles through three values, the elevation, the wall offset and the
cars' boxes are the script's. bFunkDoesServerExist answers 0, and
__builtin_vec_delete and __builtin_delete print the block, as the
harness's bFree does. Everything else the mover reads is laid out in
memory by the script: the cars (GeometryPosition at 80, Position at 96,
BodyMatrix at 144, the ratio round the track at 2032), the record it is
built from and the record's FOV, eye, bank and look arrays, the race
coordinator at gp-22216, the race at gp-22272 (its RaceStage first),
WorldTimeElapsed at gp-19560, RealTimeElapsed at gp-19596,
Camera::StopUpdating at gp-21808 and TheRaceParameters.TrackDirection at
0x0031a8a4.

The road noise's fourth lane is a stack word Update never writes, added
into the eye's; the model zeroes its stack before each Update, so that
word is the port's 0.

The scenarios start with the retail disc's own pre-race cameras,
INGAMEB's Cam_01 to Cam_04, flown round a car on the grid as the
coordinator flies them, then built records.

Every camera, mover, record and array starts from a byte pattern, so what
a call leaves alone shows. A float prints as its bits, a NaN as "nan", and
a pointer by what it is.

    python tools/bumpercam_check.py
    python tools/bumpercam_check.py --mutate [--only a,b]
    python tools/bumpercam_check.py --dump out/bumpercam
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

HARNESS = "tools/src/bumpercam_test.c"
BMC = "3DS Files/source/bumpercam.c"
SOURCES = [HARNESS, BMC] + ["3DS Files/source/" + f for f in (
    "spline.c", "cammover.c", "race.c", "camera.c", "eview.c", "emath.c",
    "replay.c", "p32.c",
    "bmatrix.c", "bmath.c", "bmathtab.c", "bvector.c", "banim.c")]

HARNESS_TIMEOUT = 120

# INGAMEB's pre-race cameras: the 80034410 container.
DISC = ROOT / "extracted-retail"
PRERACE = ("INGAMEB.BUN", 0x1d8500)

# ================================================================ the image

GP = 0x003358f0
CAM_CTOR = 0x00156be0
BM_CTOR = 0x00158800
BM_UPDATE = 0x00158a68
BM_FINISHED = 0x001589c8
BM_VTBL = 0x002b1bd0
BASE_VTBL = 0x002b1e50
VEC_DELETE = 0x00114e90
DELETE = 0x00114e98
FUNK_EXISTS = 0x0025d220
EMATH_SINIT = 0x0011bf70          # writes eMulVector's (0, 0, 0, 1)
TOPO_CTOR = 0x00151c28
TOPO_DTOR = 0x00151c70
TOPO_BBOX = 0x00136e00
TOPO_ELEV = 0x00152070
ROAD_NOISE = 0x00153498
CAR_BOX = 0x00135170
WALL_OFFSET = 0x00157930
LOOK_OFFSET = 0x00157b60
JOLLY = 0x002fa860
VIEWS = 0x002c95b0
VIEW_STRIDE = 128
NVIEWS = 10
V_CAMERA = 56
V_LIST = 60

G_STOP = GP - 21808               # Camera::StopUpdating
G_RC = GP - 22216                 # pRaceCoordinator
G_RACE = GP - 22272               # pCurrentRace
G_WTE = GP - 19560                # WorldTimeElapsed
G_RTE = GP - 19596                # RealTimeElapsed
TRACKDIR = 0x0031a8a4             # TheRaceParameters.TrackDirection

CAM_SIZE = 464
CAMS = 0x01000000
NCAM = 4
MOVS = 0x01010000
MOV_STRIDE = 0x500
MOV_TC = 412
NMOV = 3
CARS = 0x01020000
CAR_STRIDE = 0x1000
NCAR = 3
CDT = 0x01030000
NARR = 32
FOVT = 0x01031000
EYEV = 0x01031200
BANKV = 0x01031400
LOOKV = 0x01031600
RC = 0x01032000
RACE = 0x01032100

C_GPOS = 80
C_POS = 96
C_BODY = 144
C_RATIO = 2032

PATTERN = 0xa5
STACK_CLEAR = 0x4000

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
    "ep": (304, "f"), "lp": (356, "f"), "car": (408, "car"),
    "es": (44 + 20, "f"), "ls": (44 + 24, "f"), "ne": (44 + 80, "i"),
    "nl": (44 + 92, "i"),
}

ARRAYS = {"f": FOVT, "e": EYEV, "b": BANKV, "l": LOOKV}
SYMS = {"-": 0, "fovt": FOVT, "eyev": EYEV, "bankv": BANKV, "lookv": LOOKV}


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


# ============================================================== the disc


def disc_bundle(name):
    for f in DISC.rglob(name):
        return f.read_bytes()
    raise SystemExit("no %s under %s" % (name, DISC))


def disc_prerace():
    """INGAMEB's pre-race records, as the parser reads a type 1 record:
    the fields as words, then the FOV table and the eye, bank and look
    arrays as words, four to an element."""
    name, off = PRERACE
    b = disc_bundle(name)
    typ, size = struct.unpack_from("<II", b, off)
    assert typ == 0x80034410, (name, hex(typ))
    out = []
    p, end = off + 8, off + 8 + size
    while p < end:
        t, s = struct.unpack_from("<II", b, p)
        if t in (0x34460, 0x34470):
            out.append(parse_prerace(b, (p + 23) & ~15))
        p += 8 + s
    assert len(out) == 4, len(out)
    return out


def parse_prerace(b, d):
    w = lambda o: struct.unpack_from("<I", b, o)[0]
    assert w(d) == 1
    names = ["EyeSplineSpeed", "LookSplineSpeed", "LockEyeSpeedToCar",
             "LockLookSpeedToCar", "MinAreaPercent", "MaxAreaPercent",
             "IsFOVIso", "MinPercent", "MaxPercent", "NumAreaVerts",
             "NumAreaFaces", "NumEyeVerts", "NumLookVerts", "NearClip",
             "FarClip", "Backwards"]
    rec = {"Type": 1}
    q = d + 36
    for n in names:
        rec[n] = w(q)
        q += 4
    q += 12
    arr = {}
    for key, count in (("f", NARR), ("e", rec["NumEyeVerts"]),
                       ("b", rec["NumEyeVerts"]), ("l", rec["NumLookVerts"])):
        arr[key] = [[w(q + 16 * i + 4 * k) for k in range(4)]
                    for i in range(count)]
        q += 16 * count
    return rec, arr


# ============================================================ the scenarios


def vec(*xs):
    return " ".join(h(x) for x in xs)


def car_line(rnd, i, pos, ratio):
    """Car `i` at `pos`, its geometry position near it, and the ratio
    round the track."""
    g = [p + rnd.uniform(-0.5, 0.5) for p in pos]
    return "K %d %s %s %s" % (i, vec(pos[0], pos[1], pos[2],
                                     rnd.choice((0.0, 1.0,
                                                 rnd.uniform(-2, 2)))),
                              vec(g[0], g[1], g[2], 1.0), h(ratio))


def body_line(rnd, i, yaw=None, tilt=0.2):
    """Car `i`'s BodyMatrix: turned by `yaw` about z, tipped a little
    about the other two, its fourth row (0, 0, 0, 1) or off it."""
    if yaw is None:
        yaw = rnd.uniform(-math.pi, math.pi)
    p, r = rnd.uniform(-tilt, tilt), rnd.uniform(-tilt, tilt)
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(p), math.sin(p)
    cr, sr = math.cos(r), math.sin(r)
    rows = [[cy * cp, sy * cp, -sp],
            [cy * sp * sr - sy * cr, sy * sp * sr + cy * cr, cp * sr],
            [cy * sp * cr + sy * sr, sy * sp * cr - cy * sr, cp * cr]]
    t = [0.0, 0.0, 0.0]
    if rnd.random() < 0.2:
        t = [rnd.uniform(-3, 3) for _ in range(3)]
    words = []
    for row in rows:
        words += row + [0.0]
    words += t + [1.0]
    return "M %d %s" % (i, vec(*words))


def cams(n):
    out = []
    for k in range(n):
        out += ["C %d" % k, "V %d %d" % (k, k)]
    return out


def base_cd():
    """The fields a type 1 record's parser zeroes or leaves, as the
    coordinator's copy has them."""
    return ["F Type 00000001", "F Name 002b51e0", "F FOVSplineSpeed 00000000",
            "F AreaVerts -", "F AreaFaces -", "F SpringXVel 00000000",
            "F SpringYVel 00000000", "F SpringZVel 00000000",
            "F SpringDamp 00000000", "F SpringConst 00000000",
            "F LookOffsetX 00000000", "F LookOffsetY 00000000",
            "F LookOffsetZ 00000000", "F EnterVertComp 00000000",
            "F EnterHorizComp 00000000", "F LeaveVertComp 00000000",
            "F LeaveHorizComp 00000000", "F IsLeaveSet 00000000",
            "F WipeDistance 00000000", "F WipeAutoDisable 00000000",
            "F ShakeBankNumber 00000000", "F FOVTable fovt",
            "F EyeVerts eyev", "F BankVerts bankv", "F LookVerts lookv"]


def disc_cd(rec, arr):
    out = base_cd()
    for n, v in rec.items():
        out.append("F %s %08x" % (n, v))
    for key, rows in arr.items():
        for i, r in enumerate(rows):
            out.append("A %s %d %s" % (key, i, " ".join("%08x" % x
                                                         for x in r)))
    return out


def world_lines(rnd):
    """The stand-ins' answers: the road noise, the ground under the eye,
    the wall offset and the cars' boxes, small and car-sized, or big
    enough to hold the eye."""
    out = ["N %s" % vec(*(rnd.choice((0.0, rnd.uniform(-0.12, 0.12)))
                          for _ in range(3))),
           "E %s" % h(rnd.uniform(-1.5, 2.5)),
           "H %s" % vec(*(rnd.choice((0.0, rnd.uniform(-0.6, 0.6)))
                          for _ in range(3)), 0.0)]
    for i in range(NCAR):
        big = rnd.random() < 0.4
        hx = rnd.uniform(3.0, 9.0) if big else rnd.uniform(0.8, 1.3)
        lo = -hx * rnd.uniform(0.7, 1.3)
        hi = hx * rnd.uniform(0.7, 1.3)
        out.append("X %d %s %s" % (
            i, vec(lo, -rnd.uniform(1.8, 2.6), -rnd.uniform(0, 0.4), 0.0),
            vec(hi, rnd.uniform(1.8, 2.6), rnd.uniform(0.9, 1.6), 0.0)))
    return out


def s_disc(rnd, rec, arr):
    """A disc pre-race camera flown round a car on the grid, as the
    coordinator flies it: from the start until both splines run out and
    on past it, with IsFinished each frame; a stretch with the race
    racing, where the wall routine runs; then the other slots."""
    out = cams(2)
    out += disc_cd(rec, arr)
    out += world_lines(rnd)
    pos = [rnd.uniform(-400, 400), rnd.uniform(-400, 400),
           rnd.uniform(-5, 30)]
    out += [car_line(rnd, 0, pos, rnd.uniform(0, 0.02)),
            body_line(rnd, 0, tilt=0.03),
            "R %d" % rnd.choice((0, 1)), "O 0 1 0", "G 0", "I 0"]
    for i in range(52):
        if i == 30:
            out.append("T %s %s" % (h(1 / 60.0), h(1 / 60.0)))
        if i % 9 == 4:
            out += world_lines(rnd)
        out += ["U 0", "I 0"]
    out += ["T %s %s" % (h(1 / 30.0), h(1 / 30.0)), "S 4"]
    for i in range(12):
        out += world_lines(rnd) + [body_line(rnd, 0, tilt=0.1), "U 0"]
    out += ["S 2", "G 0", "D 0"]
    return out


def random_cd(rnd):
    out = base_cd()
    lo = rnd.uniform(0.0, 0.6)
    hi = lo + rnd.uniform(0.02, 0.4)
    if rnd.random() < 0.1:
        lo, hi = hi, lo
    alo = rnd.uniform(0.0, 0.6)
    ahi = alo + rnd.uniform(0.02, 0.4)
    if rnd.random() < 0.1:
        alo, ahi = ahi, alo
    ne = rnd.randrange(1, 9)
    nl = rnd.randrange(1, 9)
    vals = {
        "IsFOVIso": rnd.choice((0, 0, 1)),
        "MinPercent": lo, "MaxPercent": hi,
        "EyeSplineSpeed": rnd.choice((0.0, rnd.uniform(0.002, 0.08),
                                      rnd.uniform(0.002, 0.08),
                                      -rnd.uniform(0, 0.02))),
        "LookSplineSpeed": rnd.choice((0.0, rnd.uniform(0.002, 0.3),
                                       rnd.uniform(0.002, 0.08))),
        "FOVSplineSpeed": rnd.uniform(0, 0.2),
        "LockEyeSpeedToCar": rnd.choice((0, 0, 1)),
        "LockLookSpeedToCar": rnd.choice((0, 0, 1)),
        "MinAreaPercent": alo, "MaxAreaPercent": ahi,
        "NearClip": rnd.uniform(0.1, 2.0),
        "FarClip": rnd.uniform(500.0, 20000.0),
        "Backwards": rnd.choice((0, 1)), "NumAreaVerts": rnd.randrange(0, 9),
        "NumAreaFaces": rnd.randrange(0, 9), "NumEyeVerts": ne,
        "NumLookVerts": nl,
    }
    for name, v in vals.items():
        kind = CD_BY_NAME[name][1]
        out.append("F %s %08x" % (name, fb(v) if kind == "f" else v & M32))
    out.append("F Name %08x" % rnd.getrandbits(32))
    return out, ne, nl


def random_arrays(rnd, iso):
    """The record's arrays, the eye and the look point in the car's
    frame, as the disc's are."""
    out = []
    for i in range(NARR):
        x = rnd.uniform(8.0, 110.0) if not iso else rnd.uniform(0.5, 40.0)
        if rnd.random() < 0.3:
            x = 71.5
        out.append("A f %d %s" % (i, vec(x, rnd.uniform(-1, 1), 0.0,
                                         rnd.uniform(-5, 5))))
    for i in range(NARR):
        out.append("A e %d %s" % (i, vec(rnd.uniform(-10, 10),
                                         rnd.uniform(-10, 10),
                                         rnd.uniform(-1, 4),
                                         rnd.choice((0.0, rnd.uniform(-1,
                                                                      1))))))
        out.append("A b %d %s" % (i, vec(rnd.choice((0.0, rnd.uniform(
            -6000, 6000), rnd.uniform(0, 70000))), rnd.uniform(-5, 5),
            rnd.uniform(-5, 5), 0.0)))
        out.append("A l %d %s" % (i, vec(rnd.uniform(-2, 2),
                                         rnd.uniform(-2, 2),
                                         rnd.uniform(-1, 1),
                                         rnd.choice((0.0, rnd.uniform(-1,
                                                                      1))))))
    return out


def s_car(rnd, frames):
    """A record of random values round a car moving round the track
    through the record's windows; the clocks, the freeze, the direction,
    the pause, the race's stage and the stand-ins' answers changing on
    the way."""
    out = cams(3)
    out.append("R %d" % rnd.choice((0, 1)))
    cd, ne, nl = random_cd(rnd)
    iso = rnd.random() < 0.4
    out += cd + ["F IsFOVIso %08x" % iso] + random_arrays(rnd, iso)
    out += world_lines(rnd)
    pos = [rnd.uniform(-500, 500), rnd.uniform(-500, 500),
           rnd.uniform(-20, 80)]
    ratio = rnd.uniform(-0.1, 1.1)
    yaw = rnd.uniform(-math.pi, math.pi)
    out += [car_line(rnd, 1, pos, ratio), body_line(rnd, 1, yaw)]
    out.append("Z %d" % rnd.choice((0, 0, 0, 1)))
    view = rnd.randrange(3)
    out += ["O 0 %d 1" % view, "G 0", "I 0", "Z 0"]
    vel = [rnd.uniform(-3, 3) for _ in range(3)]
    for i in range(frames):
        pos = [p + v for p, v in zip(pos, vel)]
        ratio = min(1.3, max(-0.3, ratio + rnd.uniform(-0.01, 0.03)))
        yaw += rnd.uniform(-0.1, 0.1)
        out += [car_line(rnd, 1, pos, ratio), body_line(rnd, 1, yaw)]
        k = rnd.random()
        if k < 0.05:
            out.append("T %s %s" % (h(rnd.choice((0.0, rnd.uniform(0, 0.1)))),
                                    h(rnd.uniform(0, 0.1))))
        elif k < 0.08:
            out.append("Z %d" % rnd.choice((0, 0, 1)))
        elif k < 0.10:
            out.append("R %d" % rnd.choice((0, 1)))
        elif k < 0.12:
            out.append("W 0 ep %s" % h(rnd.uniform(-1, ne + 1)))
        elif k < 0.14:
            out.append("W 0 lp %s" % h(rnd.uniform(-1, nl + 1)))
        elif k < 0.17:
            out.append("Q %d" % rnd.choice((-1, 3, 6, 6, 5)))
        elif k < 0.22:
            out.append("S %d" % rnd.choice((0, 1, 2, 3, 4, 4)))
        elif k < 0.35:
            out += world_lines(rnd)
        out += ["U 0", "I 0"]
    out += ["Q -1", "G 0", "W 0 car -1", "G 0", "W 0 car 1",
            "Z %d" % rnd.choice((0, 1)), "D 0"]
    return out


def s_locked(rnd):
    """Both splines locked to the car: the ratio swept through and past
    the area window both ways round, so the share runs from its floor of
    0 to past 1, where the parameter is held at the last point."""
    out = cams(1)
    for r in (0, 1, 0):
        cd, ne, nl = random_cd(rnd)
        out += cd + random_arrays(rnd, False) + world_lines(rnd)
        alo = rnd.uniform(0.1, 0.5)
        out += ["R %d" % r, "F LockEyeSpeedToCar 00000001",
                "F LockLookSpeedToCar %08x" % rnd.choice((0, 1)),
                "F NumEyeVerts %08x" % max(ne, 3),
                "F NumLookVerts %08x" % max(nl, 2),
                "F MinAreaPercent %s" % h(alo),
                "F MaxAreaPercent %s" % h(alo + rnd.uniform(0.05, 0.3)),
                "F MinPercent %s" % h(0.0), "F MaxPercent %s" % h(1.0)]
        pos = [rnd.uniform(-300, 300), rnd.uniform(-300, 300), 10.0]
        out += [car_line(rnd, 0, pos, 0.0), body_line(rnd, 0), "O 0 0 0"]
        for i in range(40):
            out.append(car_line(rnd, 0, pos, -0.05 + i * 0.03))
            out += ["U 0", "I 0"]
        out += ["D 0"]
    out.append("R 0")
    return out


def s_iso(rnd):
    """IsFOVIso: the field of view from the distance between the eye, in
    the car's frame, and the car's Position, in the world's, held at 1
    when that is under a unit."""
    out = cams(1)
    cd, ne, nl = random_cd(rnd)
    out += cd + random_arrays(rnd, True) + world_lines(rnd)
    out += ["F IsFOVIso 00000001", "F NumEyeVerts 00000002",
            "F EyeSplineSpeed 00000000", "F LockEyeSpeedToCar 00000000",
            "E %s" % h(-50.0), "N 00000000 00000000 00000000"]
    eye = [3.0, -2.0, 1.2]
    out += ["A e 0 %s" % vec(eye[0], eye[1], eye[2], 0.0),
            "A e 1 %s" % vec(eye[0], eye[1], eye[2], 0.0)]
    out += [car_line(rnd, 0, eye, 0.3), body_line(rnd, 0), "O 0 0 0"]
    for d in (0.0, 0.2, 0.5, 0.9, 0.99, 1.0, 1.01, 1.5, 3.0, 40.0, 900.0):
        for k in range(2):
            a = rnd.uniform(-math.pi, math.pi)
            out.append(car_line(rnd, 0, [eye[0] + d * math.cos(a),
                                         eye[1] + d * math.sin(a),
                                         eye[2] + 0.05 * k],
                                rnd.uniform(0, 1)))
            out.append("U 0")
    out.append("D 0")
    return out


def s_ground(rnd):
    """The eye held over the ground: the ground just under, at and just
    over the eye less 0.7, the road noise moving it across."""
    out = cams(1)
    cd, ne, nl = random_cd(rnd)
    out += cd + random_arrays(rnd, False) + world_lines(rnd)
    z = 1.25
    out += ["F NumEyeVerts 00000002", "F EyeSplineSpeed 00000000",
            "F LockEyeSpeedToCar 00000000",
            "A e 0 %s" % vec(1.5, -4.0, z, 0.0),
            "A e 1 %s" % vec(1.5, -4.0, z, 0.0)]
    pos = [rnd.uniform(-300, 300), rnd.uniform(-300, 300), 4.0]
    out += [car_line(rnd, 0, pos, 0.5), body_line(rnd, 0), "O 0 0 0"]
    for g in (-3.0, 0.5, 0.549, 0.55, 0.5500001, 0.5502, 0.5504, 0.551, 0.6,
              2.0, 40.0):
        for n in (0.0, 0.05, -0.05):
            out += ["E %s" % h(g), "N %s" % vec(n, -n, n), "U 0"]
    out.append("D 0")
    return out


def s_wall(rnd):
    """The race racing: the wall routine round cars of every size, the
    eye pushed off a wall and not, and lifted on to the car's sphere
    when it ends up within it."""
    out = cams(2)
    for rep in range(6):
        cd, ne, nl = random_cd(rnd)
        out += cd + random_arrays(rnd, False)
        pos = [rnd.uniform(-300, 300), rnd.uniform(-300, 300),
               rnd.uniform(-5, 20)]
        out += [car_line(rnd, rep % NCAR, pos, rnd.uniform(0, 1)),
                body_line(rnd, rep % NCAR), "S 4",
                "O %d %d %d" % (rep % 2, rep % 2, rep % NCAR)]
        for i in range(10):
            out += world_lines(rnd)
            if i % 3 == 1:
                hx = rnd.uniform(5.0, 14.0)
                out.append("X %d %s %s" % (rep % NCAR,
                                           vec(-hx, -2, 0, 0),
                                           vec(rnd.uniform(0.5, 1.0) * hx,
                                               2, 1, 0)))
            if i % 4 == 2:
                out.append("X %d %s %s" % (rep % NCAR,
                                           vec(-1.0, -2, 0, 0),
                                           vec(rnd.uniform(6, 14), 2, 1, 0)))
            if i == 5:
                out.append("Z 1")
            if i == 7:
                out.append("Z 0")
            out += ["U %d" % (rep % 2), "I %d" % (rep % 2)]
        out += ["S %d" % rnd.choice((2, 3)), "U %d" % (rep % 2),
                "D %d" % (rep % 2)]
    return out


def s_ctor(rnd):
    """Construction with and without a car, the camera frozen and not,
    left rendering a car and its dash with a focus on it; then the
    vtable's other slots, with a car a first Update frozen, which leaves
    the focus alone, and the destructor, frozen and not."""
    out = cams(4)
    for i in range(10):
        cd, ne, nl = random_cd(rnd)
        out += cd + random_arrays(rnd, False) + world_lines(rnd)
        out.append(car_line(rnd, i % NCAR,
                            [rnd.uniform(-50, 50) for _ in range(3)],
                            rnd.uniform(0, 1)))
        out.append(body_line(rnd, i % NCAR))
        car = -1 if i % 3 == 0 else i % NCAR
        j = i % NMOV
        out += ["Z %d" % (i % 3 == 2),
                "L %d %s %s" % (i % 4, h(rnd.uniform(2, 90)),
                                h(rnd.uniform(0.5, 9))),
                "Y %d %d %d %04x" % (i % 4, (i + 1) % NCAR, rnd.choice((0, 1)),
                                     rnd.getrandbits(16)),
                "O %d %d %d" % (j, i % 4, car),
                "G %d" % j, "I %d" % j]
        if car >= 0:
            out += ["Z 1", "U %d" % j]
        out += ["Z %d" % (i % 4 == 1), "D %d" % j, "Z 0"]
    return out


def s_finished(rnd):
    """IsFinished at its edges: each speed 0 and not, each parameter just
    short of its last point, at it and past it, and counts down to 0."""
    out = cams(1)
    cd, ne, nl = random_cd(rnd)
    out += cd + random_arrays(rnd, False)
    out += ["F NumEyeVerts 00000005", "F NumLookVerts 00000003", "O 0 0 -1"]
    for es in (0.0, 0.01, -0.01):
        for ls in (0.0, 0.02):
            for ne, nl in ((5, 3), (1, 1), (0, 0), (2, 8)):
                for ep in (ne - 1.0001, float(ne - 1), ne - 0.5, ne + 3.0,
                           0.0, -1.0):
                    for lp in (nl - 1.0001, float(nl - 1), nl + 1.0, 0.0):
                        out += ["W 0 es %s" % h(es), "W 0 ls %s" % h(ls),
                                "W 0 ne %08x" % (ne & M32),
                                "W 0 nl %08x" % (nl & M32),
                                "W 0 ep %s" % h(ep), "W 0 lp %s" % h(lp),
                                "I 0"]
    out += ["W 0 ep 7fc00000", "I 0", "W 0 ne 00000005", "W 0 nl 00000003",
            "D 0"]
    return out


def s_steps(rnd):
    """Single steps: from 0, where the step is the parameter, and from
    just short of the last point, over it, the clocks different each
    time; and paused, which steps nothing."""
    out = cams(2)
    cd, ne, nl = random_cd(rnd)
    out += cd + random_arrays(rnd, False) + world_lines(rnd)
    ne, nl = max(ne, 3), max(nl, 3)
    pos = [rnd.uniform(-300, 300), rnd.uniform(-300, 300), 10.0]
    out += ["F NumEyeVerts %08x" % ne, "F NumLookVerts %08x" % nl,
            "F LockEyeSpeedToCar 00000000", "F LockLookSpeedToCar 00000000",
            "F EyeSplineSpeed %s" % h(rnd.uniform(0.003, 0.09)),
            "F LookSplineSpeed %s" % h(rnd.uniform(0.003, 0.09)),
            car_line(rnd, 2, pos, 0.4), body_line(rnd, 2), "O 1 1 2"]
    for i in range(40):
        out.append("T %s %s" % (h(rnd.uniform(-0.01, 0.1)),
                                h(rnd.uniform(0.005, 0.1))))
        out.append("W 1 ep %s" % h(rnd.choice(
            (0.0, 0.0, ne - 1 - rnd.uniform(0, 0.01),
             ne - 1 + rnd.uniform(0, 1)))))
        out.append("W 1 lp %s" % h(rnd.choice(
            (0.0, nl - 1 - rnd.uniform(0, 0.01), rnd.uniform(0, nl)))))
        out.append("Z %d" % (i % 5 == 3))
        out.append("Q %d" % (6 if i % 7 == 2 else rnd.choice((-1, 3))))
        out += ["U 1", "I 1"]
    out += ["Q -1", "Z 0", "D 1"]
    return out


def s_focus(rnd):
    """The eye within 2 of the look point, where the focal distance is
    held at 2 and the target distance is not, and on the look point."""
    out = cams(1)
    cd, ne, nl = random_cd(rnd)
    out += cd + random_arrays(rnd, False) + world_lines(rnd)
    out += ["F NumEyeVerts 00000004", "F NumLookVerts 00000004",
            "F LockEyeSpeedToCar 00000000", "F LockLookSpeedToCar 00000000",
            "F EyeSplineSpeed %s" % h(0.02), "F LookSplineSpeed %s" % h(0.03),
            "E %s" % h(-50.0)]
    for i in range(4):
        p = [rnd.uniform(-0.8, 0.8) for _ in range(3)]
        q = [rnd.uniform(-0.8, 0.8) for _ in range(3)]
        if i == 2:
            q = p
        out.append("A e %d %s" % (i, vec(p[0], p[1], p[2], 0.0)))
        out.append("A l %d %s" % (i, vec(q[0], q[1], q[2], 0.0)))
    pos = [rnd.uniform(-300, 300), rnd.uniform(-300, 300), 10.0]
    out += [car_line(rnd, 0, pos, 0.2), body_line(rnd, 0), "O 0 0 0"]
    for i in range(30):
        out += ["U 0", "I 0"]
        if i == 12:
            out += ["W 0 ep %s" % h(2.0), "W 0 lp %s" % h(2.0),
                    "N 00000000 00000000 00000000"]
    out += ["D 0"]
    return out


def script():
    rnd = random.Random(0x5b0c3a71)
    sc = [s_ctor(rnd), s_finished(rnd), s_focus(rnd)]
    for rec, arr in disc_prerace():
        sc.append(s_disc(rnd, rec, arr))
    sc += [s_locked(rnd), s_iso(rnd), s_ground(rnd), s_wall(rnd),
           s_steps(rnd)]
    for n in (60, 120, 200, 200):
        sc.append(s_car(rnd, n))
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
        e.stub(TOPO_CTOR, self.s_topo_init)
        e.stub(TOPO_DTOR, self.s_topo_destroy)
        e.stub(TOPO_BBOX, self.s_bbox)
        e.stub(TOPO_ELEV, self.s_elev)
        e.stub(ROAD_NOISE, self.s_noise)
        e.stub(CAR_BOX, self.s_box)
        e.stub(WALL_OFFSET, self.s_wall)
        e.stub(LOOK_OFFSET, self.s_lookoff)
        e.put32(JOLLY, 0)
        e.call(EMATH_SINIT)
        assert e.u32(BM_VTBL + SLOTS["update"]) == BM_UPDATE
        self.sp = e.reg[29] & M32
        self.names = {0: "null", BASE_VTBL: "base", BM_VTBL: "bumper",
                      FOVT: "fovt", EYEV: "eyev", BANKV: "bankv",
                      LOOKV: "lookv"}
        for k in range(NCAM):
            c = cam_at(k)
            self.names[c] = "c%d" % k
            self.names[c + 96] = "c%d.tgt" % k
        for j in range(NMOV):
            self.names[mov_at(j)] = "o%d" % j
            self.names[mov_at(j) + MOV_TC] = "o%d.tc" % j
        for i in range(NCAR):
            self.names[car_at(i)] = "k%d" % i
            self.names[car_at(i) + C_GPOS] = "k%d.gpos" % i
            self.names[car_at(i) + C_POS] = "k%d.pos" % i
        for i in range(NVIEWS):
            self.names[view_at(i)] = "v%d" % i
            self.names[view_at(i) + V_LIST] = "v%d.list" % i

    def emit(self, s):
        self.out.append(s)

    def name(self, a):
        return self.names.get(a & M32, "?%08x" % (a & M32))

    def tcn(self, a):
        a &= M32
        for j in range(NMOV):
            if a == mov_at(j) + MOV_TC:
                return self.name(a)
        return "local"

    # ---- the stand-ins -------------------------------------------------

    def s_free(self, em):
        self.emit("  free %s" % self.name(self.e.reg[4] & M32))

    def s_topo_init(self, em):
        self.emit("  topo init %s" % self.tcn(em.reg[4]))

    def s_topo_destroy(self, em):
        self.emit("  topo destroy %s" % self.tcn(em.reg[4]))

    def s_bbox(self, em):
        self.emit("  bbox %s pos %s r %s vel %s"
                  % (self.tcn(em.reg[4]), self.vec4(em.reg[5] & M32),
                     fx(em.fpr[12]), self.name(em.reg[6])))

    def s_elev(self, em):
        args = "".join("%d" % ((em.reg[r] & M32) != 0) for r in (6, 7, 8))
        self.emit("  elev %s pt %s args %s -> %s"
                  % (self.tcn(em.reg[4]), self.vec4(em.reg[5] & M32), args,
                     fx(self.elev)))
        em.fpr[0] = self.elev

    def s_noise(self, em):
        n = self.noise[self.noise_at]
        self.noise_at = (self.noise_at + 1) % 3
        p = em.reg[4] & M32
        self.emit("  noise %s %s %d -> %s" % (fx(self.w(p)), fx(self.w(p + 4)),
                                              s32(em.reg[5]), fx(n)))
        em.fpr[0] = n

    def s_box(self, em):
        c = em.reg[4] & M32
        self.emit("  box %s" % self.name(c))
        i = (c - CARS) // CAR_STRIDE
        for k in range(4):
            em.put32((em.reg[5] & M32) + 4 * k, self.box_min[i][k])
            em.put32((em.reg[6] & M32) + 4 * k, self.box_max[i][k])

    def s_wall(self, em):
        self.emit("  wall %s %s from %s eye %s -> %s"
                  % (self.name(em.reg[4]), self.tcn(em.reg[5]),
                     self.name(em.reg[6]), self.vec4(em.reg[7] & M32),
                     " ".join(fx(x) for x in self.wall)))
        out = em.reg[8] & M32
        for k in range(4):
            em.put32(out + 4 * k, self.wall[k])

    def s_lookoff(self, em):
        mat = em.reg[5] & M32
        eye = em.reg[6] & M32
        off = em.reg[8] & M32
        self.emit("  lookoff eye %s tgt %s off %s %s"
                  % (self.vec4(eye), self.name(em.reg[7]), fx(self.w(off)),
                     fx(self.w(off + 4))))
        self.emit("    " + " ".join(fx(self.w(mat + 4 * i))
                                    for i in range(16)))
        for k in range(3):
            em.put32(mat + 48 + 4 * k, self.w(eye + 4 * k))
        em.put32(mat + 60, fb(1.0))

    # ---- the memory ----------------------------------------------------

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
        for a in (FOVT, EYEV, BANKV, LOOKV):
            self.fill(a, 16 * NARR)
        for i in range(NVIEWS):
            v = view_at(i)
            e.put32(v + V_CAMERA, 0)
            e.put32(v + V_LIST, v + V_LIST)
            e.put32(v + V_LIST + 4, v + V_LIST)
        e.put32(G_STOP, 0)
        e.put32(G_WTE, fb(1.0 / 30.0))
        e.put32(G_RTE, fb(1.0 / 30.0))
        e.put32(TRACKDIR, 0)
        e.put32(G_RC, 0)
        e.write(RACE, bytes(16))
        e.put32(RACE, 2)
        e.put32(G_RACE, RACE)
        self.noise = [0, 0, 0]
        self.noise_at = 0
        self.elev = 0
        self.wall = [0, 0, 0, 0]
        self.box_min = [[0] * 4 for _ in range(NCAR)]
        self.box_max = [[0] * 4 for _ in range(NCAR)]

    # ---- the dumps -------------------------------------------------------

    def vec4(self, a):
        return " ".join(fx(self.w(a + 4 * i)) for i in range(4))

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
        self.emit("    clear %08x elapsed %s last %08x carnot %s dash %08x"
                  % (w(c + 432), fx(w(c + 436)), w(c + 440),
                     self.name(w(c + 444)), w(c + 448)))

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
        w = self.w
        self.emit("  o%d type %d view %d en %d pview %s pcam %s player %08x"
                  " carnot %s dash %08x vtbl %s next %s prev %s"
                  % (j, s32(w(m + 8)), s32(w(m + 12)), s32(w(m + 16)),
                     self.name(w(m + 20)), self.name(w(m + 24)), w(m + 28),
                     self.name(w(m + 32)), w(m + 36), self.name(w(m + 40)),
                     self.name(w(m)), self.name(w(m + 4))))
        self.dump_cd(m + 44)
        for tag, off in (("eye", 208), ("bank", 256), ("look", 308),
                         ("fov", 360)):
            self.dump_spline(tag, m + off)
        self.emit("    ep %s lp %s car %s" % (fx(w(m + 304)), fx(w(m + 356)),
                                              self.name(w(m + 408))))

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
        return e.call(fn, (m + delta) & M32, *args, limit=4000000)

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

    def op(self, t):
        e = self.e
        c = t[0]
        if c == "C":
            k = int(t[1])
            self.fill(cam_at(k), CAM_SIZE)
            e.call(CAM_CTOR, cam_at(k), limit=200000)
            self.dump_cam(cam_at(k))
        elif c == "L":
            k = int(t[1])
            e.put32(cam_at(k) + 116, int(t[2], 16))
            e.put32(cam_at(k) + 120, int(t[3], 16))
        elif c == "Y":
            k = int(t[1])
            e.put32(cam_at(k) + 444, car_at(int(t[2])))
            e.put32(cam_at(k) + 448, int(t[3]))
            e.write(cam_at(k) + 132, struct.pack("<H", int(t[4], 16)))
        elif c == "P":
            self.dump_cam(cam_at(int(t[1])))
        elif c == "V":
            e.put32(view_at(int(t[1])) + V_CAMERA, cam_at(int(t[2])))
        elif c == "Z":
            e.put32(G_STOP, int(t[1]))
        elif c == "T":
            e.put32(G_WTE, int(t[1], 16))
            e.put32(G_RTE, int(t[2], 16))
        elif c == "R":
            e.put32(TRACKDIR, int(t[1]))
        elif c == "Q":
            s = int(t[1])
            if s < 0:
                e.put32(G_RC, 0)
            else:
                e.put32(RC, s)
                e.put32(G_RC, RC)
        elif c == "S":
            e.put32(RACE, int(t[1]))
        elif c == "N":
            self.noise = [int(x, 16) for x in t[1:4]]
            self.noise_at = 0
        elif c == "E":
            self.elev = int(t[1], 16)
        elif c == "H":
            self.wall = [int(x, 16) for x in t[1:5]]
        elif c == "X":
            i = int(t[1])
            self.box_min[i] = [int(x, 16) for x in t[2:6]]
            self.box_max[i] = [int(x, 16) for x in t[6:10]]
        elif c == "K":
            a = car_at(int(t[1]))
            self.put_words(a + C_POS, t[2:6])
            self.put_words(a + C_GPOS, t[6:10])
            e.put32(a + C_RATIO, int(t[10], 16))
        elif c == "M":
            self.put_words(car_at(int(t[1])) + C_BODY, t[2:18])
        elif c == "A":
            self.put_words(ARRAYS[t[1]] + 16 * int(t[2]), t[3:7])
        elif c == "F":
            off, kind = CD_BY_NAME[t[1]]
            e.put32(CDT + off, self.sym(t[2]) if kind == "p"
                    else int(t[2], 16))
        elif c == "O":
            j, view, car = (int(x) for x in t[1:4])
            self.fill(mov_at(j), MOV_STRIDE)
            e.call(BM_CTOR, mov_at(j), view, car_at(car), CDT, limit=2000000)
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
            e.write(self.sp - STACK_CLEAR, bytes(STACK_CLEAR))
            self.vcall(j, SLOTS["update"])
            self.dump_mov(j)
            self.dump_cam(self.w(mov_at(j) + 24))
        elif c == "I":
            j = int(t[1])
            r = e.call(BM_FINISHED, mov_at(j), limit=200000)
            self.emit("  fin o%d %d" % (j, s32(r)))
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
        else:
            raise SystemExit("bad op %r" % (t,))

    def run(self, scenarios):
        for i, sc in enumerate(scenarios):
            self.emit("B %d" % i)
            self.reset()
            for ln in sc:
                if ln[0] not in "AFKM":
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


def build_harness(tmp, name="bumpercam_test"):
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


def M(name, before, after, rel=BMC):
    return (name, rel, before, after)


MUTATIONS = [
    # The vtable.
    M("vt-clocks", "WorldTimeElapsed," + NL
      + "                               RealTimeElapsed);",
      "RealTimeElapsed," + NL
      + "                               WorldTimeElapsed);"),
    M("vt-car", "return ((BumperCameraMover *)m)->CarToFollow;",
      "return NULL;"),

    # The constructor.
    M("ctor-type", "camera_mover_init(&m->base, viewID, CM_BUMPER);",
      "camera_mover_init(&m->base, viewID, CM_BUMPER + 1);"),
    M("ctor-vtbl", "    m->base.vtbl = &BumperCameraMoverVtbl;" + NL
      + "    m->CD = *cd;", "    m->CD = *cd;"),
    M("ctor-eye-n",
      "spline_init(&m->EyeSpline, SPLINE_CLAMP, m->CD.NumEyeVerts,",
      "spline_init(&m->EyeSpline, SPLINE_CLAMP, m->CD.NumLookVerts,"),
    M("ctor-eye-type", "spline_init(&m->EyeSpline, SPLINE_CLAMP,",
      "spline_init(&m->EyeSpline, SPLINE_EXTRAPOLATE,"),
    M("ctor-eye-verts", "m->CD.EyeVerts, BUMPER_SPLINE_TABLE",
      "m->CD.LookVerts, BUMPER_SPLINE_TABLE"),
    M("ctor-bank-n",
      "spline_init(&m->BankSpline, SPLINE_CLAMP, m->CD.NumEyeVerts,",
      "spline_init(&m->BankSpline, SPLINE_CLAMP, m->CD.NumLookVerts,"),
    M("ctor-bank-type", "spline_init(&m->BankSpline, SPLINE_CLAMP,",
      "spline_init(&m->BankSpline, SPLINE_EXTRAPOLATE,"),
    M("ctor-bank-verts", "m->CD.BankVerts, BUMPER_SPLINE_TABLE",
      "m->CD.EyeVerts, BUMPER_SPLINE_TABLE"),
    M("ctor-look-n",
      "spline_init(&m->LookSpline, SPLINE_CLAMP, m->CD.NumLookVerts,",
      "spline_init(&m->LookSpline, SPLINE_CLAMP, m->CD.NumEyeVerts,"),
    M("ctor-look-type", "spline_init(&m->LookSpline, SPLINE_CLAMP,",
      "spline_init(&m->LookSpline, SPLINE_EXTRAPOLATE,"),
    M("ctor-look-verts", "m->CD.LookVerts, BUMPER_SPLINE_TABLE",
      "m->CD.EyeVerts, BUMPER_SPLINE_TABLE"),
    M("ctor-fov-n", "SPLINE_CLAMP, 32, m->CD.FOVTable",
      "SPLINE_CLAMP, 31, m->CD.FOVTable"),
    M("ctor-fov-type", "spline_init(&m->FOVSpline, SPLINE_CLAMP,",
      "spline_init(&m->FOVSpline, SPLINE_EXTRAPOLATE,"),
    M("ctor-table", "#define BUMPER_SPLINE_TABLE 16384",
      "#define BUMPER_SPLINE_TABLE 16383"),
    M("ctor-ep", "    m->EyeSplineParam = 0.0f;",
      "    m->EyeSplineParam = 1.0f;"),
    M("ctor-lp", "    m->LookSplineParam = 0.0f;",
      "    m->LookSplineParam = 1.0f;"),
    M("ctor-car", "    m->CarToFollow = car;", "    m->CarToFollow = NULL;"),
    M("ctor-topo", "    topology_init(&m->TheTopologyCoordinate);" + NL, ""),
    M("ctor-carnot", "        cam->CarNotToRender = NULL;",
      "        cam->CarNotToRender = car;"),
    M("ctor-carnot-stop", "    if (!CameraStopUpdating)" + NL
      + "        cam->CarNotToRender = NULL;",
      "    if (1)" + NL + "        cam->CarNotToRender = NULL;"),
    M("ctor-dash", "        cam->RenderDash = 0;", "        cam->RenderDash = 1;"),
    M("ctor-dash-stop", "    if (!CameraStopUpdating)" + NL
      + "        cam->RenderDash = 0;",
      "    if (1)" + NL + "        cam->RenderDash = 0;"),
    M("ctor-fov", "#define BUMPER_FOV_START    13020",
      "#define BUMPER_FOV_START    13021"),
    M("ctor-fov-stop", "    if (!CameraStopUpdating)" + NL
      + "        cam->CurrentKey.FieldOfView = BUMPER_FOV_START;",
      "    if (1)" + NL
      + "        cam->CurrentKey.FieldOfView = BUMPER_FOV_START;"),
    M("ctor-near", "cam->CurrentKey.NearZ = m->CD.NearClip;",
      "cam->CurrentKey.NearZ = m->CD.FarClip;"),
    M("ctor-far", "    cam->CurrentKey.FarZ = m->CD.FarClip;" + NL, ""),
    M("ctor-clip-stop", "    cam->CurrentKey.NearZ = m->CD.NearClip;",
      "    if (!CameraStopUpdating)" + NL
      + "        cam->CurrentKey.NearZ = m->CD.NearClip;"),

    # The destructor.
    M("dtor-focal", "        cam->CurrentKey.FocalDistance = 0.0f;",
      "        cam->CurrentKey.FocalDistance = 1.0f;"),
    M("dtor-focal-stop", "    if (!CameraStopUpdating)" + NL
      + "        cam->CurrentKey.FocalDistance = 0.0f;",
      "    if (1)" + NL + "        cam->CurrentKey.FocalDistance = 0.0f;"),
    M("dtor-dof", "        cam->CurrentKey.DepthOfField = 0.0f;",
      "        cam->CurrentKey.DepthOfField = 1.0f;"),
    M("dtor-dof-stop", "    if (!CameraStopUpdating)" + NL
      + "        cam->CurrentKey.DepthOfField = 0.0f;",
      "    if (1)" + NL + "        cam->CurrentKey.DepthOfField = 0.0f;"),
    M("dtor-clear", "    topology_destroy(&m->TheTopologyCoordinate);",
      "    cam->ClearVelocity = 1;" + NL
      + "    topology_destroy(&m->TheTopologyCoordinate);"),
    M("dtor-topo", "    topology_destroy(&m->TheTopologyCoordinate);" + NL, ""),
    M("dtor-base", "    camera_mover_destroy(&m->base);" + NL, ""),

    # GetTarget.
    M("tgt-pos", "return &m->CarToFollow->State.GeometryPosition;",
      "return &m->CarToFollow->State.Position;"),
    M("tgt-null", "    if (m->CarToFollow != NULL)" + NL + "        return",
      "    if (0)" + NL + "        return"),
    M("tgt-cam", "return &m->base.pCamera->CurrentKey.Target;",
      "return &m->base.pCamera->CurrentKey.Position;"),

    # IsFinished.
    M("fin-eye-speed", "    if (m->CD.EyeSplineSpeed == 0.0f" + NL
      + "        || ", "    if (0" + NL + "        || "),
    M("fin-eye-le", "(float)(m->CD.NumEyeVerts - 1) <= m->EyeSplineParam",
      "(float)(m->CD.NumEyeVerts - 1) < m->EyeSplineParam"),
    M("fin-eye-n", "(float)(m->CD.NumEyeVerts - 1) <= m->EyeSplineParam",
      "(float)m->CD.NumEyeVerts <= m->EyeSplineParam"),
    M("fin-look-speed", "    if (m->CD.LookSplineSpeed == 0.0f" + NL
      + "        || ", "    if (0" + NL + "        || "),
    M("fin-look-le", "(float)(m->CD.NumLookVerts - 1) <= m->LookSplineParam",
      "(float)(m->CD.NumLookVerts - 1) < m->LookSplineParam"),
    M("fin-look-n", "(float)(m->CD.NumLookVerts - 1) <= m->LookSplineParam",
      "(float)(m->CD.NumEyeVerts - 1) <= m->LookSplineParam"),
    M("fin-or", "    return eyeDone ? lookDone : 0;",
      "    return eyeDone || lookDone;"),
    M("fin-look-only", "    return eyeDone ? lookDone : 0;",
      "    return lookDone;"),

    # How far round the track.
    M("pct-dir", "    if (RaceParametersTrackDirection == 0)",
      "    if (RaceParametersTrackDirection != 0)"),
    M("pct-scale", "        return ratio * 100.0f * 0.01f;",
      "        return ratio;"),
    M("pct-back", "    return (100.0f - ratio * 100.0f) * 0.01f;",
      "    return 1.0f - ratio;"),

    # The parameters' steps.
    M("step-lock", "    if (lock)" + NL + "        param = last * area;",
      "    if (!lock)" + NL + "        param = last * area;"),
    M("step-area", "        param = last * area;", "        param = area;"),
    M("step-25", "        param = param + speed * dt * 25.0f;",
      "        param = param + speed * dt * 30.0f;"),
    M("step-order", "        param = param + speed * dt * 25.0f;",
      "        param = param + speed * (dt * 25.0f);"),
    M("step-clamp", "    if (last < param)" + NL + "        param = last;" + NL,
      ""),
    M("step-floor", "    if (last < param)" + NL + "        param = last;",
      "    if (last < param)" + NL + "        param = last;" + NL
      + "    if (param < 0.0f)" + NL + "        param = 0.0f;"),
    M("step-last", "    float last = (float)(n - 1);",
      "    float last = (float)n;"),

    # Update: the pause and the parameters.
    M("upd-pause", "    if (is_game_flow_paused())" + NL + "        return;" + NL,
      ""),
    M("upd-area-floor", "    if (area < 0.0f)" + NL + "        area = 0.0f;" + NL,
      ""),
    M("upd-area-min", "area = (pct - cd->MinAreaPercent)",
      "area = (pct - cd->MinPercent)"),
    M("upd-area-div", "/ (cd->MaxAreaPercent - cd->MinAreaPercent);",
      "/ (cd->MaxPercent - cd->MinAreaPercent);"),
    M("upd-eye-lock", "m->EyeSplineParam, cd->LockEyeSpeedToCar,",
      "m->EyeSplineParam, cd->LockLookSpeedToCar,"),
    M("upd-eye-speed", "cd->EyeSplineSpeed, cd->NumEyeVerts, area,",
      "cd->LookSplineSpeed, cd->NumEyeVerts, area,"),
    M("upd-eye-n", "cd->EyeSplineSpeed, cd->NumEyeVerts, area,",
      "cd->EyeSplineSpeed, cd->NumLookVerts, area,"),
    M("upd-eye-dt", "cd->NumEyeVerts, area," + NL
      + "                                   dt);",
      "cd->NumEyeVerts, area," + NL
      + "                                   elapsed);"),
    M("upd-look-lock", "                                    cd->LockLookSpeedToCar,",
      "                                    cd->LockEyeSpeedToCar,"),
    M("upd-look-speed", "cd->LookSplineSpeed, cd->NumLookVerts,",
      "cd->EyeSplineSpeed, cd->NumLookVerts,"),
    M("upd-look-n", "cd->LookSplineSpeed, cd->NumLookVerts,",
      "cd->LookSplineSpeed, cd->NumEyeVerts,"),

    # Update: the car's frame.
    M("upd-tocar-pos", "    toCar.v3.x = -car->State.GeometryPosition.x;",
      "    toCar.v3.x = -car->State.Position.x;"),
    M("upd-tocar-z", "    toCar.v3.z = -car->State.GeometryPosition.z;" + NL,
      ""),
    M("upd-body", "    eTransposeMatrix(&body, &car->State.BodyMatrix);",
      "    body = car->State.BodyMatrix;"),
    M("upd-world-order", "eMulMatrix(&world, &toCar, &body);",
      "eMulMatrix(&world, &body, &toCar);"),

    # Update: the eye.
    M("upd-eye-param",
      "spline_get_point(&m->EyeSpline, &eye, m->EyeSplineParam);",
      "spline_get_point(&m->EyeSpline, &eye, m->LookSplineParam);"),
    M("upd-noise-pos", "    at.x = car->State.Position.x;",
      "    at.x = car->State.GeometryPosition.x;"),
    M("upd-noise-terrain", "    noise.x = track_get_road_noise(&at, TERRAIN_TYPE_DIRT)",
      "    noise.x = track_get_road_noise(&at, TERRAIN_TYPE_DIRTROAD)"),
    M("upd-noise-scale", "#define BUMPER_NOISE_SCALE  0.877f",
      "#define BUMPER_NOISE_SCALE  0.87f"),
    M("upd-noise-y1", "    at.y = at.y - 1.0f;", "    at.x = at.x - 1.0f;"),
    M("upd-noise-y2", "    at.y = at.y + 2.0f;", "    at.y = at.y + 1.0f;"),
    M("upd-noise-pad", "    noise.pad = 0.0f;", "    noise.pad = 1.0f;"),
    M("upd-noise-sub", "    v_add(&eye, &eye, &noise);",
      "    v_sub(&eye, &eye, &noise);"),
    M("upd-noise-gone", "    v_add(&eye, &eye, &noise);" + NL, ""),
    M("upd-elev-lift", "#define BUMPER_EYE_LIFT     0.7f",
      "#define BUMPER_EYE_LIFT     0.6f"),
    M("upd-elev-tc", "elev = topology_get_elevation(&m->TheTopologyCoordinate,",
      "elev = topology_get_elevation(NULL,"),
    M("upd-elev-margin", "    if (eye.z < elev)",
      "    if (eye.z + 0.0005f < elev)"),
    M("upd-elev-gt", "    if (eye.z < elev)", "    if (eye.z > elev)"),
    M("upd-elev-gone", "    if (eye.z < elev)" + NL + "        eye.z = elev;" + NL,
      ""),

    # Update: the look-at.
    M("upd-look-param",
      "spline_get_point(&m->LookSpline, &look, m->LookSplineParam);",
      "spline_get_point(&m->LookSpline, &look, m->EyeSplineParam);"),
    M("upd-bank-param",
      "spline_get_point(&m->BankSpline, &bank, m->EyeSplineParam);",
      "spline_get_point(&m->BankSpline, &bank, m->LookSplineParam);"),
    M("upd-bank-x", "(uint16_t)ee_trunc_w(bank.x));",
      "(uint16_t)ee_trunc_w(bank.y));"),
    M("upd-bank-round", "(uint16_t)ee_trunc_w(bank.x));",
      "(uint16_t)ee_trunc_w(bank.x + 0.5f));"),
    M("upd-up-order", "&up, &eye, &look," + NL, "&up, &look, &eye," + NL),
    M("upd-lookat", "eCreateLookAtMatrix(&look_at, &eye, &look, &up);",
      "eCreateLookAtMatrix(&look_at, &look, &eye, &up);"),
    M("upd-mat-order", "eMulMatrix(&mat, &world, &look_at);",
      "eMulMatrix(&mat, &look_at, &world);"),

    # Update: the field of view.
    M("upd-span-min", "span = (pct - cd->MinPercent)",
      "span = (pct - cd->MinAreaPercent)"),
    M("upd-span-div", "/ (cd->MaxPercent - cd->MinPercent);",
      "/ (cd->MaxAreaPercent - cd->MinPercent);"),
    M("upd-span-lo", "    if (span < 0.0f)" + NL + "        span = 0.0f;" + NL,
      ""),
    M("upd-span-hi", "    if (1.0f < span)" + NL + "        span = 1.0f;" + NL,
      ""),
    M("upd-span-31", "span * 31.0f", "span * 32.0f"),
    M("upd-iso", "    if (cd->IsFOVIso) {", "    if (0) {"),
    M("upd-iso-pos", "v_sub(&d, &eye, &car->State.Position);",
      "v_sub(&d, &eye, &car->State.GeometryPosition);"),
    M("upd-iso-min", "        if (dist < 1.0f)" + NL
      + "            dist = 1.0f;" + NL, ""),
    M("upd-iso-quarter", "fov.x * 0.25f", "fov.x * 0.5f"),
    M("upd-iso-shift", "(uint16_t)(bATan(dist, fov.x * 0.25f) << 1)",
      "(uint16_t)bATan(dist, fov.x * 0.25f)"),
    M("upd-iso-args", "bATan(dist, fov.x * 0.25f)",
      "bATan(fov.x * 0.25f, dist)"),
    M("upd-deg", "#define BUMPER_DEG_TO_BAM   182.044449f",
      "#define BUMPER_DEG_TO_BAM   182.0f"),
    M("upd-deg-y", "ee_trunc_w(fov.x * BUMPER_DEG_TO_BAM)",
      "ee_trunc_w(fov.y * BUMPER_DEG_TO_BAM)"),
    M("upd-fov-stop", "    if (!CameraStopUpdating)" + NL
      + "        cam->CurrentKey.FieldOfView = fovBam;",
      "    if (1)" + NL + "        cam->CurrentKey.FieldOfView = fovBam;"),

    # Update: the focus.
    M("upd-dist", "    v_sub(&d, &eye, &look);", "    v_sub(&d, &eye, &bank);"),
    M("upd-dot-order", "return (a->x * b->x + a->y * b->y) + a->z * b->z;",
      "return a->x * b->x + (a->y * b->y + a->z * b->z);"),
    M("upd-focal-min", "    focal = dist < 2.0f ? 2.0f : dist;",
      "    focal = dist;"),
    M("upd-td", "        cam->CurrentKey.TargetDistance = dist;",
      "        cam->CurrentKey.TargetDistance = focal;"),
    M("upd-fd", "        cam->CurrentKey.FocalDistance = focal;",
      "        cam->CurrentKey.FocalDistance = dist;"),
    M("upd-dof", "#define BUMPER_DOF          7.5f",
      "#define BUMPER_DOF          30.0f"),
    M("upd-td-stop", "    if (!CameraStopUpdating)" + NL
      + "        cam->CurrentKey.TargetDistance = dist;",
      "    if (1)" + NL + "        cam->CurrentKey.TargetDistance = dist;"),
    M("upd-fd-stop", "    if (!CameraStopUpdating)" + NL
      + "        cam->CurrentKey.FocalDistance = focal;",
      "    if (1)" + NL + "        cam->CurrentKey.FocalDistance = focal;"),
    M("upd-dof-stop", "    if (!CameraStopUpdating)" + NL
      + "        cam->CurrentKey.DepthOfField = BUMPER_DOF;",
      "    if (1)" + NL + "        cam->CurrentKey.DepthOfField = BUMPER_DOF;"),
    M("upd-stage", "== RACE_STAGE_RACING)", "== RACE_STAGE_COUNTDOWN)"),
    M("upd-stage-ge", "== RACE_STAGE_RACING)", ">= RACE_STAGE_COUNTDOWN)"),
    M("upd-elapsed", "camera_set_matrix(cam, &mat, elapsed);",
      "camera_set_matrix(cam, &mat, dt);"),

    # The wall routine.
    M("wall-eye-pad", "    eye.pad = inv.v3.w;", "    eye.pad = 1.0f;"),
    M("wall-mid", "    mid.x = geo->x * 0.5f + eye.x * 0.5f;",
      "    mid.x = geo->x * 0.5f + eye.x * 0.4f;"),
    M("wall-mid-order", "    mid.y = geo->y * 0.5f + eye.y * 0.5f;",
      "    mid.y = (geo->y + eye.y) * 0.5f;"),
    M("wall-mid-pad", "    mid.pad = geo->pad * 0.5f + eye.pad * 0.5f;",
      "    mid.pad = 0.0f;"),
    M("wall-r", "r = sqrtf(v_dot(&d, &d)) * 0.5f + 0.5f;",
      "r = sqrtf(v_dot(&d, &d)) * 0.5f + 1.0f;"),
    M("wall-r-half", "r = sqrtf(v_dot(&d, &d)) * 0.5f + 0.5f;",
      "r = sqrtf(v_dot(&d, &d)) + 0.5f;"),
    M("wall-tc", "    topology_init(&tc);" + NL, ""),
    M("wall-bbox-vel", "topology_set_interest_bbox3(&tc, &mid, r, NULL);",
      "topology_set_interest_bbox3(&tc, &mid, r, geo);"),
    M("wall-bbox-pos", "topology_set_interest_bbox3(&tc, &mid, r, NULL);",
      "topology_set_interest_bbox3(&tc, geo, r, NULL);"),
    M("wall-o", "eMulVector3(&o, mat, geo);", "eMulVector3(&o, mat, &eye);"),
    M("wall-off-x", "    off.x = o.x / o.z;", "    off.x = o.x / o.y;"),
    M("wall-off-y", "    off.y = o.y / o.z;", "    off.y = o.y;"),
    M("wall-offset-tc", "camera_wall_offset(&m->base, &tc, geo, &eye, &wall);",
      "camera_wall_offset(&m->base, &m->TheTopologyCoordinate, geo, &eye,"
      + " &wall);"),
    M("wall-offset-from",
      "camera_wall_offset(&m->base, &tc, geo, &eye, &wall);",
      "camera_wall_offset(&m->base, &tc, &car->State.Position, &eye,"
      + " &wall);"),
    M("wall-add", "    v_add(&eye, &eye, &wall);", "    v_sub(&eye, &eye, &wall);"),
    M("wall-d", "    v_sub(&d, &eye, geo);" + NL + "    dist",
      "    v_sub(&d, &eye, &mid);" + NL + "    dist"),
    M("wall-abs", "    reach = fabsf(bmin.x);", "    reach = bmin.x;"),
    M("wall-min-y", "    reach = fabsf(bmin.x);", "    reach = fabsf(bmin.y);"),
    M("wall-max", "    if (reach < bmax.x)" + NL + "        reach = bmax.x;" + NL,
      ""),
    M("wall-max-y", "        reach = bmax.x;", "        reach = bmax.y;"),
    M("wall-room", "#define BUMPER_CAR_ROOM     0.7f",
      "#define BUMPER_CAR_ROOM     0.6f"),
    M("wall-gt", "    if (dist < reach)", "    if (dist > reach)"),
    M("wall-lift", "eye.z = geo->z + sqrtf(reach * reach - (d.x * d.x + d.y * d.y));",
      "eye.z = geo->z + sqrtf(reach * reach - d.x * d.x);"),
    M("wall-lift-base", "eye.z = geo->z + sqrtf(",
      "eye.z = eye.z + sqrtf("),
    M("wall-lookoff-tgt", "camera_look_at_offset(mat, &eye, geo, &off);",
      "camera_look_at_offset(mat, &eye, &mid, &off);"),
    M("wall-tc-destroy", "    topology_destroy(&tc);" + NL, ""),
]

EQUIVALENT = {
    "wall-eye-pad": "eInvertTransformationMatrix's fourth row ends in "
                    "exactly 1 for any finite matrix",
    "wall-mid-order": "halving is exact, so a/2 + b/2 and (a + b)/2 round "
                      "alike away from the subnormals",
}


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
        todo, SOURCES, "bumpercam_test",
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
