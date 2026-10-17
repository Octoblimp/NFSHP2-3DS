#!/usr/bin/env python3
"""Cross-check 3DS Files/source/trackflycam.c, the fly-by's mover, against
the retail image itself, run in mipsemu.

The model is the image. TrackFlyCameraMover's constructor (0x00159d08),
destructor (0x00159de8), Update (0x00159e98), IsFinished (0x0015a2a0),
GetTarget (0x00159e78) and GetCarToFollow (0x0015faf8) run as shipped,
through retail's vtable (0x002b1a50) where the game goes through it, with
IsFinished called directly as FlyByCameraCoordinator::Update calls it.
Under them run Spline, the CameraMover base and its ComputeBankedUpVector,
Camera::SetCameraMatrix, the matrix layer and bATan, over retail's own
eView table. The harness (tools/src/trackflycam_test.c) runs the port over
the same script, and the two transcripts are diffed.

Stubs: bFunkDoesServerExist answers 0, and __builtin_vec_delete and
__builtin_delete print the block, as the harness's bFree does. Everything
else the mover reads is laid out in memory by the script: the cars
(GeometryPosition at 80, Position at 96, the ratio round the track at
2032), the record it is built from and the record's FOV, eye, bank and
look arrays, WorldTimeElapsed at gp-19560, RealTimeElapsed at gp-19596,
Camera::StopUpdating at gp-21808 and TheRaceParameters.TrackDirection at
0x0031a8a4.

The scenarios start with the retail disc's own fly-bys, the PreRace_01
camera of each of the fifteen TRACKB bundles, flown with no car as the
coordinator flies them, then built records with a car to follow.

Every camera, mover, record and array starts from a byte pattern, so what
a call leaves alone shows. A float prints as its bits, a NaN as "nan", and
a pointer by what it is.

    python tools/trackflycam_check.py
    python tools/trackflycam_check.py --mutate [--only a,b]
    python tools/trackflycam_check.py --dump out/trackflycam
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

HARNESS = "tools/src/trackflycam_test.c"
TFC = "3DS Files/source/trackflycam.c"
SOURCES = [HARNESS, TFC] + ["3DS Files/source/" + f for f in (
    "spline.c", "cammover.c", "race.c", "camera.c", "eview.c", "emath.c",
    "replay.c", "p32.c",
    "bmatrix.c", "bmath.c", "bmathtab.c", "bvector.c", "banim.c")]

HARNESS_TIMEOUT = 120

# The disc's fly-bys: each TRACKB bundle's 80034425 container.
DISC = ROOT / "extracted-retail"
FLY_BYS = (("TRACKB11.BUN", 0x890880), ("TRACKB12.BUN", 0x88db80),
           ("TRACKB13.BUN", 0x966600), ("TRACKB21.BUN", 0x964100),
           ("TRACKB22.BUN", 0x99cf80), ("TRACKB23.BUN", 0xa97980),
           ("TRACKB31.BUN", 0x723980), ("TRACKB32.BUN", 0x715f80),
           ("TRACKB33.BUN", 0x7caf00), ("TRACKB41.BUN", 0x9fbe80),
           ("TRACKB42.BUN", 0x9a4680), ("TRACKB43.BUN", 0x9d8300),
           ("TRACKB61.BUN", 0xa19c80), ("TRACKB62.BUN", 0xa4b480),
           ("TRACKB63.BUN", 0xa29780))

# ================================================================ the image

GP = 0x003358f0
CAM_CTOR = 0x00156be0
TF_CTOR = 0x00159d08
TF_UPDATE = 0x00159e98
TF_FINISHED = 0x0015a2a0
TF_VTBL = 0x002b1a50
BASE_VTBL = 0x002b1e50
VEC_DELETE = 0x00114e90
DELETE = 0x00114e98
FUNK_EXISTS = 0x0025d220
EMATH_SINIT = 0x0011bf70          # writes eMulVector's (0, 0, 0, 1)
JOLLY = 0x002fa860
VIEWS = 0x002c95b0
VIEW_STRIDE = 128
NVIEWS = 10
V_CAMERA = 56
V_LIST = 60

G_STOP = GP - 21808               # Camera::StopUpdating
G_WTE = GP - 19560                # WorldTimeElapsed
G_RTE = GP - 19596                # RealTimeElapsed
TRACKDIR = 0x0031a8a4             # TheRaceParameters.TrackDirection

CAM_SIZE = 464
CAMS = 0x01000000
NCAM = 4
MOVS = 0x01010000
MOV_STRIDE = 0x200
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

C_GPOS = 80
C_POS = 96
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
    "ep": (400, "f"), "lp": (404, "f"), "car": (408, "car"),
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
    p = DISC / "TRACKS" / name
    if p.exists():
        return p.read_bytes()
    for f in DISC.rglob(name):
        return f.read_bytes()
    raise SystemExit("no %s under %s" % (name, DISC))


def disc_fly_bys():
    """Each bundle's fly-by records, as the parser reads a type 2 record:
    the fields as words, then the FOV table and the eye, bank and look
    arrays as words, four to an element."""
    out = []
    for name, off in FLY_BYS:
        b = disc_bundle(name)
        typ, size = struct.unpack_from("<II", b, off)
        assert typ == 0x80034425, (name, hex(typ))
        p, end = off + 8, off + 8 + size
        while p < end:
            t, s = struct.unpack_from("<II", b, p)
            if t == 0x34490:
                out.append((name, parse_fly_by(b, (p + 23) & ~15)))
            p += 8 + s
    return out


def parse_fly_by(b, d):
    w = lambda o: struct.unpack_from("<I", b, o)[0]
    assert w(d) == 2
    names = ["EyeSplineSpeed", "LookSplineSpeed", "FOVSplineSpeed",
             "LockEyeSpeedToCar", "LockLookSpeedToCar", "MinAreaPercent",
             "MaxAreaPercent", "IsFOVIso", "MinPercent", "MaxPercent",
             "NumAreaVerts", "NumAreaFaces", "NumEyeVerts", "NumLookVerts",
             "NearClip", "FarClip", "Backwards"]
    rec = {"Type": 2}
    q = d + 36
    for n in names:
        rec[n] = w(q)
        q += 4
    q += 8
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


def cams(n):
    out = []
    for k in range(n):
        out += ["C %d" % k, "V %d %d" % (k, k)]
    return out


def base_cd():
    """The fields a fly-by's parser zeroes or leaves, as the coordinator's
    copy has them."""
    return ["F Type 00000002", "F Name 002b51e0", "F FOVSplineSpeed 00000000",
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


def s_disc(rnd, name, rec, arr):
    """A disc fly-by flown with no car, as the coordinator flies it: the
    first frames at 30 and 60 a second, then points along both splines,
    then the last stretch to the end, with IsFinished each frame."""
    out = cams(2)
    out += disc_cd(rec, arr)
    ne, nl = rec["NumEyeVerts"], rec["NumLookVerts"]
    out += ["O 0 1 -1", "G 0", "I 0"]
    for i in range(12):
        if i == 6:
            out.append("T %s %s" % (h(1 / 60.0), h(1 / 60.0)))
        out += ["U 0", "I 0"]
    out.append("T %s %s" % (h(1 / 30.0), h(1 / 30.0)))
    for k in range(10):
        f = rnd.random()
        out += ["W 0 ep %s" % h(f * (ne - 1)),
                "W 0 lp %s" % h(rnd.uniform(0, 1) * (nl - 1)), "U 0", "I 0"]
    for k in range(ne - 1):
        out += ["W 0 ep %s" % h(float(k)), "W 0 lp %s" % h(
            float(min(k, nl - 1))), "U 0"]
    # The last stretch: big steps until both run out, and on past it.
    out += ["W 0 ep %s" % h(ne - 1 - 0.03), "W 0 lp %s" % h(nl - 1 - 0.2),
            "T %s %s" % (h(0.25), h(1 / 30.0))]
    for i in range(14):
        out += ["U 0", "I 0"]
    out += ["G 0", "D 0"]
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
        "LookSplineSpeed": rnd.choice((0.0, rnd.uniform(0.002, 0.08),
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


def random_world(rnd, centre, iso):
    out = []
    for i in range(NARR):
        x = rnd.uniform(8.0, 110.0) if not iso else rnd.uniform(0.5, 40.0)
        if rnd.random() < 0.3:
            x = 71.5
        out.append("A f %d %s" % (i, vec(x, rnd.uniform(-1, 1), 0.0,
                                         rnd.uniform(-5, 5))))
    for i in range(NARR):
        p = [c + rnd.uniform(-60, 60) for c in centre]
        out.append("A e %d %s" % (i, vec(p[0], p[1], p[2],
                                         rnd.uniform(-1, 1))))
        out.append("A b %d %s" % (i, vec(rnd.choice((0.0, rnd.uniform(
            -6000, 6000), rnd.uniform(0, 70000))), rnd.uniform(-5, 5),
            rnd.uniform(-5, 5), 0.0)))
        p = [c + rnd.uniform(-20, 20) for c in centre]
        out.append("A l %d %s" % (i, vec(p[0], p[1], p[2],
                                         rnd.uniform(-1, 1))))
    return out


def s_car(rnd, frames):
    """A record of random values with a car to follow, moving round the
    track through the record's windows, the clocks, the freeze and the
    direction changing on the way."""
    centre = [rnd.uniform(-500, 500), rnd.uniform(-500, 500),
              rnd.uniform(-20, 80)]
    out = cams(3)
    out.append("R %d" % rnd.choice((0, 1)))
    cd, ne, nl = random_cd(rnd)
    iso = rnd.random() < 0.4
    out += cd + ["F IsFOVIso %08x" % iso] + random_world(rnd, centre, iso)
    pos = [c + rnd.uniform(-20, 20) for c in centre]
    ratio = rnd.uniform(-0.1, 1.1)
    out.append(car_line(rnd, 1, pos, ratio))
    out.append("Z %d" % rnd.choice((0, 0, 0, 1)))
    view = rnd.randrange(3)
    out += ["O 0 %d 1" % view, "G 0", "I 0", "Z 0"]
    vel = [rnd.uniform(-3, 3) for _ in range(3)]
    for i in range(frames):
        pos = [p + v for p, v in zip(pos, vel)]
        ratio = min(1.3, max(-0.3, ratio + rnd.uniform(-0.01, 0.03)))
        out.append(car_line(rnd, 1, pos, ratio))
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
        elif k < 0.15:
            out.append("W 0 car %d" % rnd.choice((-1, 1, 2)))
        out += ["U 0", "I 0"]
    out += ["G 0", "W 0 car -1", "G 0", "W 0 car 1",
            "Z %d" % rnd.choice((0, 1)), "D 0"]
    return out


def s_locked(rnd):
    """Both splines locked to the car: the ratio swept through and past
    the area window both ways round, so the share runs from its floor of
    0 to past 1, where the parameter is held at the last point."""
    out = cams(1)
    centre = [rnd.uniform(-300, 300), rnd.uniform(-300, 300), 10.0]
    for r in (0, 1, 0):
        cd, ne, nl = random_cd(rnd)
        out += cd + random_world(rnd, centre, False)
        alo = rnd.uniform(0.1, 0.5)
        out += ["R %d" % r, "F LockEyeSpeedToCar 00000001",
                "F LockLookSpeedToCar %08x" % rnd.choice((0, 1)),
                "F NumEyeVerts %08x" % max(ne, 3),
                "F NumLookVerts %08x" % max(nl, 2),
                "F MinAreaPercent %s" % h(alo),
                "F MaxAreaPercent %s" % h(alo + rnd.uniform(0.05, 0.3)),
                "F MinPercent %s" % h(0.0), "F MaxPercent %s" % h(1.0)]
        pos = [centre[0] + 5, centre[1] - 5, 10.0]
        out.append(car_line(rnd, 0, pos, 0.0))
        out += ["O 0 0 0"]
        for i in range(40):
            out.append(car_line(rnd, 0, pos, -0.05 + i * 0.03))
            out += ["U 0", "I 0"]
        out += ["D 0"]
    out.append("R 0")
    return out


def s_iso(rnd):
    """IsFOVIso: the field of view from the eye's distance to the car,
    held at 1 when the car is within a unit of the eye."""
    out = cams(1)
    centre = [rnd.uniform(-300, 300), rnd.uniform(-300, 300), 12.0]
    cd, ne, nl = random_cd(rnd)
    out += cd + random_world(rnd, centre, True)
    out += ["F IsFOVIso 00000001", "F NumEyeVerts 00000002",
            "F EyeSplineSpeed 00000000", "F LockEyeSpeedToCar 00000000"]
    eye = [centre[0] + 3.0, centre[1] - 2.0, 12.0]
    out += ["A e 0 %s" % vec(eye[0], eye[1], eye[2], 0.0),
            "A e 1 %s" % vec(eye[0], eye[1], eye[2], 0.0)]
    out.append(car_line(rnd, 0, eye, 0.3))
    out += ["O 0 0 0"]
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


def s_ctor(rnd):
    """Construction with and without a car, the camera frozen and not, a
    focus left on the camera; then the vtable's other slots and the
    destructor, frozen and not."""
    out = cams(4)
    centre = [100.0, -200.0, 5.0]
    for i in range(10):
        cd, ne, nl = random_cd(rnd)
        out += cd + random_world(rnd, centre, False)
        out.append(car_line(rnd, i % NCAR,
                            [c + rnd.uniform(-5, 5) for c in centre],
                            rnd.uniform(0, 1)))
        car = -1 if i % 3 == 0 else i % NCAR
        out += ["Z %d" % (i % 3 == 2),
                "L %d %s %s" % (i % 4, h(rnd.uniform(2, 90)),
                                h(rnd.uniform(0.5, 9))),
                "O %d %d %d" % (i % NMOV, i % 4, car),
                "G %d" % (i % NMOV), "I %d" % (i % NMOV),
                "Z %d" % (i % 4 == 1), "D %d" % (i % NMOV), "Z 0"]
    return out


def s_finished(rnd):
    """IsFinished at its edges: each speed 0 and not, each parameter just
    short of its last point, at it and past it, and counts down to 0."""
    out = cams(1)
    centre = [0.0, 0.0, 0.0]
    cd, ne, nl = random_cd(rnd)
    out += cd + random_world(rnd, centre, False)
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
    """Single steps without a car: from 0, where the step is the
    parameter, and from just short of the last point, over it, the clocks
    different each time."""
    out = cams(2)
    centre = [rnd.uniform(-300, 300), rnd.uniform(-300, 300), 10.0]
    cd, ne, nl = random_cd(rnd)
    out += cd + random_world(rnd, centre, False)
    ne, nl = max(ne, 3), max(nl, 3)
    out += ["F NumEyeVerts %08x" % ne, "F NumLookVerts %08x" % nl,
            "F EyeSplineSpeed %s" % h(rnd.uniform(0.003, 0.09)),
            "F LookSplineSpeed %s" % h(rnd.uniform(0.003, 0.09)),
            "O 1 1 -1"]
    for i in range(40):
        out.append("T %s %s" % (h(rnd.uniform(-0.01, 0.1)),
                                h(rnd.uniform(0.005, 0.1))))
        out.append("W 1 ep %s" % h(rnd.choice(
            (0.0, 0.0, ne - 1 - rnd.uniform(0, 0.01),
             ne - 1 + rnd.uniform(0, 1)))))
        out.append("W 1 lp %s" % h(rnd.choice(
            (0.0, nl - 1 - rnd.uniform(0, 0.01), rnd.uniform(0, nl)))))
        out.append("Z %d" % (i % 5 == 3))
        out += ["U 1", "I 1"]
    out += ["Z 0", "D 1"]
    return out


def s_edges(rnd):
    """No car with the locks set, which steps at the speeds; a camera
    frozen under a mover with no car, which keeps its field of view; and
    the eye within 2 of the look point, where the focal distance is held
    at 2 and the target distance is not."""
    out = cams(2)
    centre = [rnd.uniform(-300, 300), rnd.uniform(-300, 300), 10.0]
    cd, ne, nl = random_cd(rnd)
    out += cd + random_world(rnd, centre, False)
    out += ["F LockEyeSpeedToCar 00000001", "F LockLookSpeedToCar 00000001",
            "F NumEyeVerts 00000004", "F NumLookVerts 00000004",
            "F EyeSplineSpeed %s" % h(0.02), "F LookSplineSpeed %s" % h(0.03)]
    for i in range(4):
        p = [c + rnd.uniform(-0.8, 0.8) for c in centre]
        q = [c + rnd.uniform(-0.8, 0.8) for c in centre]
        if i == 2:
            q = p
        out.append("A e %d %s" % (i, vec(p[0], p[1], p[2], 0.0)))
        out.append("A l %d %s" % (i, vec(q[0], q[1], q[2], 0.0)))
    out += ["Z 1", "O 0 0 -1"]
    for i in range(6):
        out += ["U 0", "I 0"]
    out += ["Z 0"]
    for i in range(30):
        out += ["U 0", "I 0"]
        if i == 12:
            out += ["W 0 ep %s" % h(2.0), "W 0 lp %s" % h(2.0)]
    out += ["D 0", "Z 1", "O 1 1 -1", "U 1", "Z 0", "U 1", "D 1"]
    return out


def script():
    rnd = random.Random(0x7f1b7ca3)
    sc = [s_ctor(rnd), s_finished(rnd), s_edges(rnd)]
    for name, (rec, arr) in disc_fly_bys():
        sc.append(s_disc(rnd, name, rec, arr))
    sc += [s_locked(rnd), s_iso(rnd), s_steps(rnd)]
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
        e.put32(JOLLY, 0)
        e.call(EMATH_SINIT)
        assert e.u32(TF_VTBL + SLOTS["update"]) == TF_UPDATE
        self.names = {0: "null", BASE_VTBL: "base", TF_VTBL: "fly",
                      FOVT: "fovt", EYEV: "eyev", BANKV: "bankv",
                      LOOKV: "lookv"}
        for k in range(NCAM):
            c = cam_at(k)
            self.names[c] = "c%d" % k
            self.names[c + 96] = "c%d.tgt" % k
        for j in range(NMOV):
            self.names[mov_at(j)] = "o%d" % j
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
        w = self.w
        self.emit("  o%d type %d view %d en %d pview %s pcam %s player %08x"
                  " carnot %08x dash %08x vtbl %s next %s prev %s"
                  % (j, s32(w(m + 8)), s32(w(m + 12)), s32(w(m + 16)),
                     self.name(w(m + 20)), self.name(w(m + 24)), w(m + 28),
                     w(m + 32), w(m + 36), self.name(w(m + 40)),
                     self.name(w(m)), self.name(w(m + 4))))
        self.dump_cd(m + 44)
        for tag, off in (("eye", 208), ("bank", 256), ("look", 304),
                         ("fov", 352)):
            self.dump_spline(tag, m + off)
        self.emit("    ep %s lp %s car %s" % (fx(w(m + 400)), fx(w(m + 404)),
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
        return e.call(fn, (m + delta) & M32, *args, limit=2000000)

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
        elif c == "K":
            a = car_at(int(t[1]))
            self.put_words(a + C_POS, t[2:6])
            self.put_words(a + C_GPOS, t[6:10])
            e.put32(a + C_RATIO, int(t[10], 16))
        elif c == "A":
            self.put_words(ARRAYS[t[1]] + 16 * int(t[2]), t[3:7])
        elif c == "F":
            off, kind = CD_BY_NAME[t[1]]
            e.put32(CDT + off, self.sym(t[2]) if kind == "p"
                    else int(t[2], 16))
        elif c == "O":
            j, view, car = (int(x) for x in t[1:4])
            self.fill(mov_at(j), MOV_STRIDE)
            e.call(TF_CTOR, mov_at(j), view, CDT, car_at(car), limit=2000000)
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
        elif c == "I":
            j = int(t[1])
            r = e.call(TF_FINISHED, mov_at(j), limit=200000)
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
                if ln[0] not in "AFK":
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


def build_harness(tmp, name="trackflycam_test"):
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


def M(name, before, after, rel=TFC):
    return (name, rel, before, after)


UPD_LOOK = ("m->LookSplineParam = step_param(m->LookSplineParam," + NL
            + "                                    cd->LockLookSpeedToCar," + NL
            + "                                    cd->LookSplineSpeed,"
            + " cd->NumLookVerts,")
UPD_EYE = ("m->EyeSplineParam = step_param(m->EyeSplineParam,"
           + " cd->LockEyeSpeedToCar," + NL
           + "                                   cd->EyeSplineSpeed,"
           + " cd->NumEyeVerts, car,")

MUTATIONS = [
    # The vtable.
    M("vt-clocks", "WorldTimeElapsed," + NL
      + "                                  RealTimeElapsed);",
      "RealTimeElapsed," + NL
      + "                                  WorldTimeElapsed);"),
    M("vt-car", "return ((TrackFlyCameraMover *)m)->CarToFollow;",
      "return NULL;"),

    # The constructor.
    M("ctor-type", "camera_mover_init(&m->base, viewID, CM_TRACK_FLY);",
      "camera_mover_init(&m->base, viewID, CM_TRACK_FLY + 1);"),
    M("ctor-vtbl", "    m->base.vtbl = &TrackFlyCameraMoverVtbl;" + NL
      + "    m->CD = *cd;", "    m->CD = *cd;"),
    M("ctor-eye-n", "spline_init(&m->EyeSpline, SPLINE_CLAMP, m->CD.NumEyeVerts,",
      "spline_init(&m->EyeSpline, SPLINE_CLAMP, m->CD.NumLookVerts,"),
    M("ctor-eye-type", "spline_init(&m->EyeSpline, SPLINE_CLAMP,",
      "spline_init(&m->EyeSpline, SPLINE_EXTRAPOLATE,"),
    M("ctor-bank-type", "spline_init(&m->BankSpline, SPLINE_CLAMP,",
      "spline_init(&m->BankSpline, SPLINE_EXTRAPOLATE,"),
    M("ctor-bank-verts", "m->CD.BankVerts, TRACK_FLY_SPLINE_TABLE",
      "m->CD.EyeVerts, TRACK_FLY_SPLINE_TABLE"),
    M("ctor-look-n",
      "spline_init(&m->LookSpline, SPLINE_CLAMP, m->CD.NumLookVerts,",
      "spline_init(&m->LookSpline, SPLINE_CLAMP, m->CD.NumEyeVerts,"),
    M("ctor-look-type", "spline_init(&m->LookSpline, SPLINE_CLAMP,",
      "spline_init(&m->LookSpline, SPLINE_EXTRAPOLATE,"),
    M("ctor-look-verts", "m->CD.LookVerts, TRACK_FLY_SPLINE_TABLE",
      "m->CD.EyeVerts, TRACK_FLY_SPLINE_TABLE"),
    M("ctor-fov-n", "SPLINE_CLAMP, 32, m->CD.FOVTable",
      "SPLINE_CLAMP, 31, m->CD.FOVTable"),
    M("ctor-table", "#define TRACK_FLY_SPLINE_TABLE 16384",
      "#define TRACK_FLY_SPLINE_TABLE 16383"),
    M("ctor-ep", "    m->EyeSplineParam = 0.0f;",
      "    m->EyeSplineParam = 1.0f;"),
    M("ctor-lp", "    m->LookSplineParam = 0.0f;",
      "    m->LookSplineParam = 1.0f;"),
    M("ctor-near", "cam->CurrentKey.NearZ = m->CD.NearClip;",
      "cam->CurrentKey.NearZ = m->CD.FarClip;"),
    M("ctor-far", "    cam->CurrentKey.FarZ = m->CD.FarClip;" + NL, ""),
    M("ctor-car", "    m->CarToFollow = car;", "    m->CarToFollow = NULL;"),

    # The destructor.
    M("dtor-stop", "    if (!CameraStopUpdating) {" + NL
      + "        cam->CurrentKey.FocalDistance = 0.0f;",
      "    if (1) {" + NL + "        cam->CurrentKey.FocalDistance = 0.0f;"),
    M("dtor-focal", "        cam->CurrentKey.FocalDistance = 0.0f;" + NL, ""),
    M("dtor-dof", "        cam->CurrentKey.DepthOfField = 0.0f;" + NL, ""),
    M("dtor-clear", "    cam->ClearVelocity = 1;",
      "    cam->ClearVelocity = 0;"),
    M("dtor-base", "    camera_mover_destroy(&m->base);" + NL, ""),

    # GetTarget.
    M("tgt-pos", "return &m->CarToFollow->State.GeometryPosition;",
      "return &m->CarToFollow->State.Position;"),
    M("tgt-null", "    if (m->CarToFollow != NULL)" + NL + "        return",
      "    if (0)" + NL + "        return"),
    M("tgt-cam", "return &m->base.pCamera->CurrentKey.Target;",
      "return &m->base.pCamera->CurrentKey.Position;"),

    # IsFinished.
    M("fin-eye-speed", "    if (m->CD.EyeSplineSpeed == 0.0f" + NL + "        || ",
      "    if (0" + NL + "        || "),
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
    M("step-lock-car", "    if (lock && car != NULL)", "    if (lock)"),
    M("step-lock", "    if (lock && car != NULL)", "    if (car != NULL)"),
    M("step-area", "        param = last * area;", "        param = area;"),
    M("step-25", "        param = param + speed * dt * 25.0f;",
      "        param = param + speed * dt * 30.0f;"),
    M("step-order", "        param = param + speed * dt * 25.0f;",
      "        param = param + speed * (dt * 25.0f);"),
    M("step-clamp", "    if (last < param)" + NL + "        param = last;" + NL,
      ""),
    M("step-last", "    float last = (float)(n - 1);",
      "    float last = (float)n;"),

    # Update.
    M("upd-area-floor", "        if (area < 0.0f)" + NL
      + "            area = 0.0f;" + NL, ""),
    M("upd-area-min", "area = (track_percent(car) - cd->MinAreaPercent)",
      "area = (track_percent(car) - cd->MinPercent)"),
    M("upd-area-div", "/ (cd->MaxAreaPercent - cd->MinAreaPercent);",
      "/ (cd->MaxPercent - cd->MinAreaPercent);"),
    M("upd-look-lock", UPD_LOOK, UPD_LOOK.replace("cd->LockLookSpeedToCar",
                                                  "cd->LockEyeSpeedToCar")),
    M("upd-look-speed", UPD_LOOK, UPD_LOOK.replace("cd->LookSplineSpeed",
                                                   "cd->EyeSplineSpeed")),
    M("upd-look-n", UPD_LOOK, UPD_LOOK.replace("cd->NumLookVerts",
                                               "cd->NumEyeVerts")),
    M("upd-eye-lock", UPD_EYE, UPD_EYE.replace("cd->LockEyeSpeedToCar",
                                               "cd->LockLookSpeedToCar")),
    M("upd-eye-speed", UPD_EYE, UPD_EYE.replace("cd->EyeSplineSpeed",
                                                "cd->LookSplineSpeed")),
    M("upd-eye-n", UPD_EYE, UPD_EYE.replace("cd->NumEyeVerts",
                                            "cd->NumLookVerts")),
    M("upd-eye-param", "spline_get_point(&m->EyeSpline, &eye, m->EyeSplineParam);",
      "spline_get_point(&m->EyeSpline, &eye, m->LookSplineParam);"),
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
    M("upd-up-order", "&up, &eye, &look," + NL,
      "&up, &look, &eye," + NL),
    M("upd-lookat", "eCreateLookAtMatrix(&mat, &eye, &look, &up);",
      "eCreateLookAtMatrix(&mat, &look, &eye, &up);"),
    M("upd-span-min", "float span = (track_percent(car) - cd->MinPercent)",
      "float span = (track_percent(car) - cd->MinAreaPercent)"),
    M("upd-span-div", "/ (cd->MaxPercent - cd->MinPercent);",
      "/ (cd->MaxAreaPercent - cd->MinPercent);"),
    M("upd-span-lo", "        if (span < 0.0f)" + NL
      + "            span = 0.0f;" + NL, ""),
    M("upd-span-hi", "        if (1.0f < span)" + NL
      + "            span = 1.0f;" + NL, ""),
    M("upd-span-31", "span * 31.0f", "span * 32.0f"),
    M("upd-iso", "        if (cd->IsFOVIso) {", "        if (0) {"),
    M("upd-iso-pos", "v_sub(&d, &eye, &car->State.Position);",
      "v_sub(&d, &eye, &car->State.GeometryPosition);"),
    M("upd-iso-min", "            if (dist < 1.0f)" + NL
      + "                dist = 1.0f;" + NL, ""),
    M("upd-iso-quarter", "fov.x * 0.25f", "fov.x * 0.5f"),
    M("upd-iso-shift", "(uint16_t)(bATan(dist, fov.x * 0.25f) << 1)",
      "(uint16_t)bATan(dist, fov.x * 0.25f)"),
    M("upd-iso-args", "bATan(dist, fov.x * 0.25f)",
      "bATan(fov.x * 0.25f, dist)"),
    M("upd-deg", "#define TRACK_FLY_DEG_TO_BAM   182.044449f",
      "#define TRACK_FLY_DEG_TO_BAM   182.0f"),
    M("upd-deg-y", "ee_trunc_w(fov.x * TRACK_FLY_DEG_TO_BAM)",
      "ee_trunc_w(fov.y * TRACK_FLY_DEG_TO_BAM)"),
    M("upd-fov-stop", "        if (!CameraStopUpdating)" + NL
      + "            cam->CurrentKey.FieldOfView = fovBam;",
      "        if (1)" + NL + "            cam->CurrentKey.FieldOfView = fovBam;"),
    M("upd-nocar-fov", "#define TRACK_FLY_FOV_NO_CAR   13020",
      "#define TRACK_FLY_FOV_NO_CAR   13021"),
    M("upd-nocar-stop", "    } else if (!CameraStopUpdating) {",
      "    } else {"),
    M("upd-dist", "    v_sub(&d, &eye, &look);", "    v_sub(&d, &eye, &bank);"),
    M("upd-dot-order", "return (a->x * b->x + a->y * b->y) + a->z * b->z;",
      "return a->x * b->x + (a->y * b->y + a->z * b->z);"),
    M("upd-focal-min", "    focal = dist < 2.0f ? 2.0f : dist;",
      "    focal = dist;"),
    M("upd-td", "        cam->CurrentKey.TargetDistance = dist;",
      "        cam->CurrentKey.TargetDistance = focal;"),
    M("upd-fd", "        cam->CurrentKey.FocalDistance = focal;",
      "        cam->CurrentKey.FocalDistance = dist;"),
    M("upd-dof", "#define TRACK_FLY_DOF          30.0f",
      "#define TRACK_FLY_DOF          7.5f"),
    M("upd-focus-stop", "    if (!CameraStopUpdating) {" + NL
      + "        cam->CurrentKey.TargetDistance",
      "    if (1) {" + NL + "        cam->CurrentKey.TargetDistance"),
    M("upd-elapsed", "camera_set_matrix(cam, &mat, elapsed);",
      "camera_set_matrix(cam, &mat, dt);"),
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
        todo, SOURCES, "trackflycam_test",
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
