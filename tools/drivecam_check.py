#!/usr/bin/env python3
"""Cross-check 3DS Files/source/drivecam.c, DriveCameraMover's small members,
against the retail image itself, run in mipsemu.

The model is the image. Retail's constructor (0x0015c258), destructor
(0x0015c400, through the vtable), ResetState (0x0015c470), SetPOVIndex
(0x0015c520), every slot of its vtable (0x002b1dd0) but Update and Render,
the three corrections (0x0015c158, 0x0015c1d0, 0x0015c218),
CalculateLookbackAngle (0x0015c5a8) and the out-of-line accessors
(0x0015fbf8 .. 0x0015fc9c) run as shipped, over CameraMover's base, the
Camera constructor, bASin, bATan and retail's own eView table. The harness
(tools/src/drivecam_test.c) runs the port over the same script, and the
two transcripts are diffed.

Only TopologyCoordinate's constructor (0x00151c28) and destructor
(0x00151c70) are stubs, which print whose they were. Retail's is 704 bytes
and the port's is still the demo's 560, so what they write inside is left
to their own checker; that they are called, and on the right mover, shows.

Every camera, mover, car, car type and player starts from a byte pattern,
so what a call leaves alone shows. A float prints as its bits, a NaN as
"nan", and a pointer by what it is: a camera or its target, a mover, a car
or its GeometryPosition, a player, a view or its list's head, a vtable, or
a car type and the offset into it. Most resets follow a scribble over the
words only Update writes, standing in for the frames 7b will run.

    python tools/drivecam_check.py
    python tools/drivecam_check.py --mutate [--only a,b]
    python tools/drivecam_check.py --dump out/drivecam
"""
import argparse
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
    "bmathtab.c", "bvector.c")]

HARNESS_TIMEOUT = 120

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

PATTERN = 0xa5

# Retail's offsets.
C_TGT, C_FD, C_DOF, C_NEAR, C_FAR, C_CARNOT, C_DASH = (96, 116, 120, 124,
                                                       128, 444, 448)
CAR_CTI, CAR_GPOS, CAR_POS, CAR_BODYZ, CAR_ANGLE, CAR_VEL = (12, 80, 96, 152,
                                                             932, 960)
CTI_CAMERA = 960
PL_LOOKBACK = 44                  # PlayerSettings (32) + 12

SLOTS = {
    "destroy": 12, "info": 52, "pov": 60, "ext": 68, "lookback": 76,
    "gap": 84, "reset": 92, "car": 116, "target": 124,
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


def script():
    rnd = random.Random(0xd21ec0de)
    sc = [s_ctor(rnd), s_corrections(rnd), s_lookback(rnd)]
    for n in (60, 200, 400, 400, 400):
        sc.append(s_walk(rnd, n))
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
        e.call(EMATH_SINIT)
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
            self.emit("    cam %s carnot %08x dash %08x fd %s dof %s near %s"
                      " far %s" % (self.name(c), w(c + C_CARNOT),
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
            e.put32(a + CAR_VEL, int(t[5], 16))
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
    M("ctor_speed_fwd", DRVC,
      "    d->LastCarSpeed = car->State.VelocityMagnitude;\n    if",
      "    d->LastCarSpeed = car->State.ForwardSpeed;\n    if"),
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
    M("reset_speed_fwd", DRVC,
      "    d->LastCarSpeed = car->State.VelocityMagnitude;\n}",
      "    d->LastCarSpeed = car->State.ForwardSpeed;\n}"),
    # Retail's ResetState leaves AmountToUseYawCorrection as Update left it.
    M("reset_amount", DRVC,
      "    d->LastBoomYaw = 0;\n    d->LastCarPitch = (uint16_t)",
      "    d->LastBoomYaw = 0;\n    d->AmountToUseYawCorrection = 0.0f;\n"
      "    d->LastCarPitch = (uint16_t)"),
    M("reset_dlag", DRVC,
      "    d->LastCarSpeed = car->State.VelocityMagnitude;\n}",
      "    d->LastCarSpeed = car->State.VelocityMagnitude;\n"
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
    M("ext_incar", DRVC, "pov->Type == POV_OUTSIDE)",
      "pov->Type == POV_INCAR)"),
    M("ext_no_counts", DRVC, "    return counts && 0.0f < d->LookBackParam;",
      "    return 0.0f < d->LookBackParam;"),
    M("ext_want", DRVC, "    return counts && 0.0f < d->LookBackParam;",
      "    return counts && 0.0f < d->DesiredLookBackParam;"),
    M("ext_le", DRVC, "    return counts && 0.0f < d->LookBackParam;",
      "    return counts && 0.0f <= d->LookBackParam;"),
    M("ext_no_look_back", DRVC,
      "    return counts && 0.0f < d->LookBackParam;",
      "    return counts && 0;"),
    M("ext_pov0", DRVC, "m->vtbl->GetPOV(m, d->POVIndex);",
      "m->vtbl->GetPOV(m, 0);"),
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
