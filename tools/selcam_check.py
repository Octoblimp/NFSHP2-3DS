#!/usr/bin/env python3
"""Cross-check 3DS Files/source/selcam.c, the car select's turntable camera,
against the retail image itself, run in mipsemu.

The model is the image. SelectCarCameraMover's constructor (0x0015a698),
destructor (0x0015a880) and Update (0x0015abb0) run as shipped, the last
two through retail's vtable (0x002b1950), with the setters (0x0015a940 ..
0x0015a9f8, 0x0015fab8 .. 0x0015fad8), SetMode (0x0015aa08) and the three
quaternion helpers Update calls, MyQuaternionMultiply (0x0015aab0),
NormalizeQuaternion (0x0015ab58) and Slerp (0x001a7280). Under them run
the CameraMover base, Camera::SetCameraMatrix and the matrix layer, over
retail's own eView table. The harness (tools/src/selcam_test.c) runs the
port over the same script, and the two transcripts are diffed.

Stubs: bFunkDoesServerExist answers 0, and the sound is a recorder. The
constructor's bSound::Region, bOMalloc, the bSample constructor, Sample,
Initialize and SetCategory build a fake sample that knows its name, and
SetCategory prints it; Play, Stop, SetVolume and SetPitch print the
sample's name and their floats, and the destructor's delete through the
sample's vtable prints the name. The harness's sound hooks print the same.
RealTimeElapsed is at gp-19596, SoundEnabled at gp-23056, Update's frame
counter at gp-21664, Camera::StopUpdating at gp-21808.

Every camera and mover starts from a byte pattern, so what a call leaves
alone shows. The constructor never writes the two quaternions (112, 128)
and fills the two offsets' w lanes (92, 108) from its stack, which nothing
reads, so the dumps leave those two lanes out. A float prints as its bits,
a NaN as "nan", and a pointer by what it is.

Retail's SetMode, Update's bumps and its hum test SoundEnabled and not the
sample, so a mover built without sound plays through null samples once
it is turned on; the script never does that.

    python tools/selcam_check.py
    python tools/selcam_check.py --mutate [--only a,b]
    python tools/selcam_check.py --dump out/selcam
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

HARNESS = "tools/src/selcam_test.c"
SELC = "3DS Files/source/selcam.c"
SOURCES = [HARNESS, SELC] + ["3DS Files/source/" + f for f in (
    "camera.c", "cammover.c", "eview.c", "emath.c", "bmatrix.c", "bmath.c",
    "bmathtab.c", "bvector.c", "bquat.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
CAM_CTOR = 0x00156be0
SEL_CTOR = 0x0015a698
SEL_DTOR = 0x0015a880
SEL_UPDATE = 0x0015abb0
SEL_VTBL = 0x002b1950
BASE_VTBL = 0x002b1e50
SET_RADIUS_STATS = 0x0015a940
SET_OFFSET_STATS = 0x0015a948
SET_OFFSET_ORBIT = 0x0015a958
SET_FOV_STATS = 0x0015a968
SET_FOV_ORBIT = 0x0015a970
SET_ORIENT_STATS = 0x0015a978
SET_VERT_ORBIT = 0x0015a9f8
SET_MODE = 0x0015aa08
QUAT_MUL = 0x0015aab0
QUAT_NORM = 0x0015ab58
SET_DRADIUS = 0x0015fab8
SET_DVERT = 0x0015fac0
SET_DHORIZ = 0x0015fac8
GET_MODE_PARAM = 0x0015fad8
SLERP = 0x001a7280
FUNK_EXISTS = 0x0025d220
EMATH_SINIT = 0x0011bf70          # writes eMulVector's (0, 0, 0, 1)
JOLLY = 0x002fa860

# The sound.
S_REGION = 0x00277a18             # bSound::Region(char *)
S_OMALLOC = 0x00257c80            # bOMalloc(SlotPool *)
S_CTOR = 0x00272ff0               # bSample::bSample()
S_SAMPLE = 0x002719b8             # bRegion::Sample(char *)
S_INIT = 0x00273210               # bSample::Initialize(bSample *)
S_CATEGORY = 0x00273618           # bSample::SetCategory(unsigned)
S_PLAY = 0x00274080               # bSample::Play(float, float, float)
S_STOP = 0x00274618               # bSample::Stop()
S_VOLUME = 0x00273d50             # bSample::SetVolume(float)
S_PITCH = 0x00273738              # bSample::SetPitch(float)

VIEWS = 0x002c95b0
VIEW_STRIDE = 128
NVIEWS = 10
V_CAMERA = 56
V_LIST = 60

G_STOP = GP - 21808               # Camera::StopUpdating
G_ELAPSED = GP - 19596            # RealTimeElapsed
G_SOUND = GP - 23056              # SoundEnabled
G_COUNT = GP - 21664              # Update's frame counter

CAM_SIZE = 464
CAMS = 0x01000000
NCAM = 4
MOV_SIZE = 192
MOVS = 0x01010000
MOV_STRIDE = 256
NMOV = 3
SAMPLES = 0x01020000              # the fake bSamples, 256 bytes each
NSAMPLES = 256
SAMPLE_VT = 0x01060000            # their vtable: delta 0 at 8, delete at 12
SAMPLE_DEL = 0x01060100           # the delete, a stub
REGION = 0x01070000
VEC = 0x01080000                  # a setter's vector
QA = 0x01080100                   # the helpers' quaternions
QB = 0x01080110
QO = 0x01080120

PATTERN = 0xa5

# The vtable's slots, by the function's offset.
SLOTS = {
    "destroy": 12, "update": 20, "info": 52, "pov": 60, "ext": 68,
    "lookback": 76, "gap": 84, "car": 116, "target": 124,
}

# The fields a script pokes, by retail's offset.
FIELDS = {
    "mode": (44, "w"), "blend": (48, "w"), "az": (56, "h"), "ts": (60, "h"),
    "to": (62, "h"), "hs": (148, "w"), "vs": (156, "w"), "or": (164, "w"),
    "rsp": (168, "w"),
}


def fb(v):
    if isinstance(v, int):
        return v & M32
    return f_to_bits(v)


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


def view_at(i):
    return VIEWS + VIEW_STRIDE * i


# ============================================================ the scenarios


def h(v):
    return "%08x" % fb(v)


def rquat(rnd, unit=True):
    q = [rnd.uniform(-1, 1) for _ in range(4)]
    if unit:
        n = math.sqrt(sum(x * x for x in q)) or 1.0
        q = [x / n for x in q]
    else:
        s = rnd.choice((0.5, 0.9, 1.1, 3.0))
        q = [x * s for x in q]
    return q


def qs(q):
    return " ".join(h(x) for x in q)


def near(rnd, q, ang):
    """A unit quaternion `ang` radians (of the 4-sphere) from q."""
    r = [rnd.uniform(-1, 1) for _ in range(4)]
    d = sum(a * b for a, b in zip(r, q))
    r = [a - d * b for a, b in zip(r, q)]
    n = math.sqrt(sum(x * x for x in r)) or 1.0
    r = [x / n for x in r]
    return [math.cos(ang) * a + math.sin(ang) * b for a, b in zip(q, r)]


def frames(j, n):
    return ["U %d" % j] * n


def turntable(j, rnd=None):
    """The car select's own setup, as CarSelector::Tick makes it."""
    out = ["R %d %s" % (j, h(7.25)),
           "A %d %s %s %s %s" % (j, h(0.0), h(0.0), h(0.55), h(1.0)),
           "a %d %s %s %s %s" % (j, h(0.0), h(0.0), h(0.4), h(1.0)),
           "W %d 2800" % j, "w %d 3200" % j,
           "S %d 2200 0900" % j, "s %d 0c00" % j]
    if rnd is not None:
        out = ["R %d %s" % (j, h(rnd.uniform(4.0, 12.0))),
               "A %d %s %s %s %s" % (j, h(rnd.uniform(-1, 1)),
                                     h(rnd.uniform(-1, 1)),
                                     h(rnd.uniform(-1, 1)), h(1.0)),
               "a %d %s %s %s %s" % (j, h(rnd.uniform(-1, 1)),
                                     h(rnd.uniform(-1, 1)),
                                     h(rnd.uniform(-1, 1)), h(0.0)),
               "W %d %04x" % (j, rnd.randrange(0x10000)),
               "w %d %04x" % (j, rnd.randrange(0x10000)),
               "S %d %04x %04x" % (j, rnd.randrange(0x10000),
                                   rnd.randrange(0x2000)),
               "s %d %04x" % (j, rnd.randrange(0x10000))]
    return out


def s_ctor(rnd):
    """Construction, destruction and the vtable's queries."""
    out = ["C 0", "C 1", "V 0 0", "V 3 1"]
    out += ["O 0 0", "G 0", "O 1 3", "G 1", "O 2 0", "G 2"]
    out += ["D 0", "D 2", "D 1"]
    # Without sound: no samples, and the destructor deletes none.
    out += ["E 0", "O 0 3", "G 0", "D 0", "E 1"]
    # Frozen: the constructor does not touch the camera either way.
    out += ["Z 1", "O 1 0", "D 1", "Z 0"]
    # Sound turned off under a mover that has it: nothing plays.
    out += ["O 2 3", "E 0", "M 2 1", "M 2 0", "D 2", "E 1"]
    return out


def s_setters(rnd):
    out = ["C 0", "V 0 0", "O 0 0"]
    for r in (0.0, -0.0, 7.25, -3.5, 1e30, float("inf")):
        out.append("R 0 %s" % h(r))
    out.append("R 0 7fc00001")
    for _ in range(4):
        out.append("A 0 %s" % qs([rnd.uniform(-5, 5) for _ in range(4)]))
        out.append("a 0 %s" % qs([rnd.uniform(-5, 5) for _ in range(4)]))
    for f in (0, 1, 0x2800, 0x8000, 0xffff):
        out += ["W 0 %04x" % f, "w 0 %04x" % ((f * 7) & 0xffff)]
    for a, t in ((0, 0), (1, 1), (0x2200, 0x0900), (0x8000, 0x8000),
                 (0xffff, 0xffff), (0x4000, 0xc000), (0xc000, 0x0001)):
        out += ["S 0 %04x %04x" % (a, t), "s 0 %04x" % t]
    for _ in range(6):
        out.append("S 0 %04x %04x" % (rnd.randrange(0x10000),
                                      rnd.randrange(0x10000)))
    for k in "rvh":
        for v in (0.0, -0.0, 12.5, -40000.0, 1e-30, 3e38):
            out.append("P 0 %s %s" % (k, h(v)))
    out += ["G 0", "F 0 blend 3f000000", "G 0", "D 0"]
    return out


def s_modes(rnd):
    """SetMode's sounds, and a mode that is neither."""
    out = ["C 0", "V 0 0", "O 0 0"] + turntable(0)
    out += ["M 0 0", "M 0 1", "M 0 1", "M 0 0", "M 0 5", "M 0 -1"]
    # Updates in a mode that is neither: no spin, no tilt, no blend.
    out += ["F 0 blend 3f000000"] + frames(0, 3)
    out += ["M 0 1"] + frames(0, 4) + ["M 0 5"] + frames(0, 4)
    out += ["E 0", "M 0 1", "M 0 0", "E 1", "D 0"]
    return out


def s_run(rnd):
    """The car select's flow: the stats view, into the orbit, the sticks
    pushed to every stop, and back out."""
    out = ["C 0", "V 0 0", "O 0 0"] + turntable(0) + ["M 0 0"]
    out += frames(0, 6)
    out += ["M 0 1"] + frames(0, 40)
    # Round, up and out, then held against the stops.
    out += ["P 0 h %s" % h(30000.0), "P 0 v %s" % h(20000.0),
            "P 0 r %s" % h(9.0)] + frames(0, 70)
    out += ["P 0 h %s" % h(-30000.0), "P 0 v %s" % h(-20000.0),
            "P 0 r %s" % h(-9.0)] + frames(0, 90)
    out += ["T %s" % h(1.0 / 30.0), "P 0 v %s" % h(25000.0),
            "P 0 r %s" % h(17.0)] + frames(0, 30)
    out += ["P 0 h 0", "P 0 v 0", "P 0 r 0"] + frames(0, 40)
    out += ["T %s" % h(1.0 / 60.0), "M 0 0"] + frames(0, 40)
    out += ["M 0 1"] + frames(0, 10) + ["M 0 0"] + frames(0, 10)
    out += ["D 0"]
    return out


def s_edges(rnd):
    """The stops hit exactly, the counter at its turns, odd blends, a
    frozen camera, no time, and sound off through the bumps."""
    out = ["C 0", "V 0 0", "O 0 0"] + turntable(0)
    out += ["M 0 1", "F 0 blend 3f800000"]
    out += ["P 0 h 0", "P 0 v 0", "P 0 r 0"]
    # The tilt: at the top, one past, at the bottom, one past, wrapped.
    for to in (0xebab, 0xebac, 0xc34f, 0xc350, 0xc34e, 0x0000, 0xffff,
               0x8000, 0x7fff):
        out += ["F 0 vs 00000000", "F 0 to %04x" % to, "U 0"]
        out += ["F 0 vs %s" % h(rnd.choice((-3000.0, 3000.0, 0.1))),
                "F 0 to %04x" % to, "U 0"]
    # The radius: at both stops, past them, and bumps either side of the
    # floor.
    for r in (15.5, 15.6, 10.95, 10.9, 13.0, 1e9, -1e9):
        out += ["F 0 rsp 00000000", "F 0 or %s" % h(r), "U 0"]
        out += ["F 0 rsp 80000000", "F 0 or %s" % h(r), "U 0"]
    for sp in (0.6, 0.7, 0.72, 0.73, 0.8, 5.0, -0.6, -0.73, -5.0):
        out += ["F 0 rsp %s" % h(sp), "F 0 or %s" % h(15.49), "U 0"]
        out += ["F 0 rsp %s" % h(-sp), "F 0 or %s" % h(10.96), "U 0"]
    for vs in (170.0, 180.0, 181.0, 200.0, 5000.0):
        out += ["F 0 vs %s" % h(vs), "F 0 to eba0", "U 0"]
        out += ["F 0 vs %s" % h(-vs), "F 0 to c360", "U 0"]
    # Bumps just past the floor (0.107 against 0.1), the speed held so the
    # ramp leaves it alone.
    for vs in (1020.0, 1050.0, 1075.0, 1100.0):
        out += ["P 0 v %s" % h(vs), "F 0 vs %s" % h(vs), "F 0 to eba0", "U 0"]
        out += ["P 0 v %s" % h(-vs), "F 0 vs %s" % h(-vs), "F 0 to c360",
                "U 0"]
    for sp in (0.77, 0.79, 0.805, 0.82):
        out += ["P 0 r %s" % h(sp), "F 0 rsp %s" % h(sp),
                "F 0 or %s" % h(15.49), "U 0"]
        out += ["P 0 r %s" % h(-sp), "F 0 rsp %s" % h(-sp),
                "F 0 or %s" % h(10.96), "U 0"]
    out += ["P 0 v 0", "P 0 r 0"]
    # Sound off through a bounce and the hum.
    out += ["E 0", "F 0 vs %s" % h(5000.0), "F 0 to eba0", "U 0",
            "F 0 rsp %s" % h(5.0), "F 0 or %s" % h(15.49), "U 0", "E 1"]
    # The counter, either side of its multiples, negative too.
    for n in (0, 59, 60, 61, 119, 120, 0x7fffffff, 0xffffffff, 0xffffffc4,
              0xffffffc5, 0x80000000):
        out += ["N %08x" % n, "U 0"]
    # The blend: past both ends, a NaN, small ones round the reset.
    for b in (1.5, -0.5, 0.01, 0.03, 0.0, -0.0, 2.5, 1e-30, -1e-30):
        out += ["F 0 blend %s" % h(b), "U 0"]
    out += ["F 0 blend 7fc00000", "U 0", "M 0 0", "F 0 blend 7fc00000",
            "U 0", "F 0 blend 3f000000", "U 0"]
    # Big speeds, a speed past the int range of a frame's step.
    for hs in (1e6, -1e6, 65536.0 * 60.0, 3e9, -3e9):
        out += ["M 0 1", "F 0 hs %s" % h(hs), "P 0 h %s" % h(hs), "U 0"]
    out += ["P 0 h 0"]
    # No time, then a long frame, then a frozen camera.
    out += ["T 00000000", "U 0", "U 0", "T %s" % h(0.25), "U 0",
            "Z 1", "U 0", "U 0", "Z 0", "T %s" % h(1.0 / 60.0), "U 0"]
    out += ["D 0"]
    return out


def s_two(rnd):
    """Two movers on two views share the frame counter."""
    out = ["C 0", "C 1", "V 0 0", "V 2 1", "O 0 0", "O 1 2"]
    out += turntable(0, rnd) + turntable(1, rnd)
    out += ["M 0 1", "M 1 1", "N 0000003a"]
    for _ in range(70):
        out += ["U 0", "U 1"]
    out += ["D 1", "D 0"]
    return out


def s_slerp(rnd):
    """Slerp straight, at every branch."""
    out = []
    ts = (0.0, 1.0, 0.5, 0.25, 0.97, -0.5, 1.5, 1e-7)
    # Equal, opposite, at right angles (the dot exactly 0 and -0).
    q = rquat(rnd)
    for t in ts:
        out.append("L %s %s %s" % (qs(q), qs(q), h(t)))
        out.append("L %s %s %s" % (qs(q), qs([-x for x in q]), h(t)))
    for a, b in (([1, 0, 0, 0], [0, 1, 0, 0]), ([0, 0, 0, 1], [0, 0, 1, 0]),
                 ([1, 0, 0, 0], [-0.0, 1, 0, 0]), ([0, 0, 0, -1], [0, 0, 1, 0])):
        for t in (0.3, 0.75):
            out.append("L %s %s %s" % (qs(a), qs(b), h(t)))
    # Every angle, both signs of the dot, round the linear cut-off.
    for ang in (0.0, 1e-4, 0.01, 0.2, 0.3, 0.31, 0.3176, 0.32, 0.33, 0.35,
                0.4, 0.8, 1.2, 1.5, 1.5707, 2.0, 2.8, 3.0, 3.1, 3.14159):
        for _ in range(3):
            a = rquat(rnd)
            b = near(rnd, a, ang)
            out.append("L %s %s %s" % (qs(a), qs(b), h(rnd.choice(ts))))
            out.append("L %s %s %s" % (qs(a), qs(b), h(rnd.random())))
    # Off the unit sphere, and NaNs: a NaN dot takes the far branch.
    for _ in range(20):
        out.append("L %s %s %s" % (qs(rquat(rnd, False)),
                                   qs(rquat(rnd, False)), h(rnd.random())))
    for lane in range(4):
        a = rquat(rnd)
        a[lane] = float("nan")
        # The last two round apart between (t * pi) * k and t * (pi * k).
        for t in (0.0, 0.3, 0.5, 0.8, 1.0, -0.25, 0.89166259765625,
                  0.425506591796875):
            out.append("L %s %s %s" % (qs(a), qs(rquat(rnd)), h(t)))
    for _ in range(4):
        b = rquat(rnd)
        b[rnd.randrange(4)] = float("inf")
        out.append("L %s %s %s" % (qs(rquat(rnd)), qs(b), h(0.4)))
    for _ in range(150):
        a = rquat(rnd)
        b = near(rnd, a, rnd.uniform(0, math.pi))
        out.append("L %s %s %s" % (qs(a), qs(b), h(rnd.random())))
    return out


def s_quat(rnd):
    out = []
    for _ in range(80):
        out.append("X %s %s" % (qs(rquat(rnd, rnd.random() < 0.5)),
                                qs(rquat(rnd, rnd.random() < 0.5))))
        out.append("Y %s" % qs(rquat(rnd, False)))
    out += ["Y %s" % qs([0.0, 0.0, 0.0, 0.0]),
            "Y %s" % qs([-0.0, 0.0, 0.0, 1e-30]),
            "Y %s" % qs([3e38, 3e38, 0.0, 1.0]),
            "Y %s" % qs([1.0, 0.0, 0.0, 0.0]),
            "X %s %s" % (qs([0.0, 0.0, 0.0, 1.0]), qs([0.0, 0.0, 0.0, 1.0]))]
    return out


def s_walk(rnd, n):
    """A random car select: the sticks, the modes, the time and the
    setters, in any order."""
    out = ["C 0", "V 1 0", "O 0 1"] + turntable(0, rnd)
    out.append("N %08x" % rnd.randrange(0x100000000))
    mode = 0
    for _ in range(n):
        k = rnd.random()
        if k < 0.70:
            out.append("U 0")
        elif k < 0.80:
            out.append("P 0 %s %s" % (rnd.choice("rvh"), h(rnd.choice((
                0.0, rnd.uniform(-60000, 60000), rnd.uniform(-30000, 30000),
                rnd.uniform(-20, 20))))))
        elif k < 0.85:
            mode = rnd.choice((0, 1, 1, mode))
            out.append("M 0 %d" % mode)
        elif k < 0.89:
            out.append("T %s" % h(rnd.choice((1.0 / 60.0, 1.0 / 30.0,
                                               rnd.uniform(0, 0.1)))))
        elif k < 0.92:
            out.append(rnd.choice(turntable(0, rnd)))
        elif k < 0.94:
            out.append("G 0")
        elif k < 0.96:
            out.append("F 0 %s %s" % (rnd.choice(("vs", "hs")),
                                      h(rnd.uniform(-40000, 40000))))
        elif k < 0.98:
            out.append("F 0 rsp %s" % h(rnd.uniform(-30, 30)))
        else:
            out.append("Z %d" % (rnd.random() < 0.5))
    out += ["Z 0", "D 0"]
    return out


def script():
    rnd = random.Random(0x5e1ca111)
    sc = [s_ctor(rnd), s_setters(rnd), s_modes(rnd), s_run(rnd),
          s_edges(rnd), s_two(rnd), s_slerp(rnd), s_quat(rnd)]
    for n in (300, 900, 1500):
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
        e.stub(S_REGION, self.s_region)
        e.stub(S_OMALLOC, self.s_omalloc)
        e.stub(S_CTOR, self.s_ctor)
        e.stub(S_SAMPLE, self.s_sample)
        e.stub(S_INIT, self.s_init)
        e.stub(S_CATEGORY, self.s_category)
        e.stub(S_PLAY, self.s_play)
        e.stub(S_STOP, self.s_stop)
        e.stub(S_VOLUME, self.s_volume)
        e.stub(S_PITCH, self.s_pitch)
        e.stub(SAMPLE_DEL, self.s_delete)
        e.put32(JOLLY, 0)
        e.call(EMATH_SINIT)
        assert e.u32(SEL_VTBL + SLOTS["update"]) == SEL_UPDATE
        assert e.u32(SEL_VTBL + SLOTS["destroy"]) == SEL_DTOR
        e.put32(SAMPLE_VT + 8, 0)
        e.put32(SAMPLE_VT + 12, SAMPLE_DEL)
        self.region = None
        self.next_sample = 0
        self.sample_names = {}
        self.names = {0: "null", BASE_VTBL: "base", SEL_VTBL: "selcam"}
        for k in range(NCAM):
            c = cam_at(k)
            self.names[c] = "c%d" % k
            self.names[c + 96] = "c%d.tgt" % k
        for j in range(NMOV):
            self.names[mov_at(j)] = "o%d" % j
        for i in range(NVIEWS):
            self.names[view_at(i)] = "v%d" % i
            self.names[view_at(i) + V_LIST] = "v%d.list" % i

    def emit(self, s):
        self.out.append(s)

    def name(self, a):
        return self.names.get(a & M32, "?%08x" % (a & M32))

    def arg(self, i):
        return self.e.reg[(4, 5, 6, 7)[i]] & M32

    def cstr(self, a):
        mem = self.e.mem
        end = mem.index(0, a)
        return bytes(mem[a:end]).decode("latin-1")

    # ---- the sound -------------------------------------------------------

    def s_region(self, em):
        self.region = self.cstr(self.arg(1))
        return REGION

    def s_omalloc(self, em):
        a = SAMPLES + 256 * (self.next_sample % NSAMPLES)
        self.next_sample += 1
        return a

    def s_ctor(self, em):
        a = self.arg(0)
        self.e.put32(a + 184, SAMPLE_VT)
        return a

    def s_sample(self, em):
        assert self.arg(0) == REGION
        return self.arg(1)

    def s_init(self, em):
        self.sample_names[self.arg(0)] = self.cstr(self.arg(1))

    def s_category(self, em):
        self.emit("  snd new %s/%s cat %d" % (
            self.region, self.sample_names[self.arg(0)], s32(self.arg(1))))

    def sname(self):
        return self.sample_names.get(self.arg(0), "?%08x" % self.arg(0))

    def s_play(self, em):
        f = self.e.fpr
        self.emit("  snd play %s %s %s %s" % (self.sname(), fx(f[12]),
                                              fx(f[13]), fx(f[14])))

    def s_stop(self, em):
        self.emit("  snd stop %s" % self.sname())

    def s_volume(self, em):
        self.emit("  snd vol %s %s" % (self.sname(), fx(self.e.fpr[12])))

    def s_pitch(self, em):
        self.emit("  snd pitch %s %s" % (self.sname(), fx(self.e.fpr[12])))

    def s_delete(self, em):
        assert self.arg(1) == 3
        self.emit("  snd del %s" % self.sname())

    # ---- memory ----------------------------------------------------------

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
        self.fill(MOVS, MOV_STRIDE * NMOV)
        for i in range(NVIEWS):
            v = view_at(i)
            e.put32(v + V_CAMERA, 0)
            e.put32(v + V_LIST, v + V_LIST)
            e.put32(v + V_LIST + 4, v + V_LIST)
        e.put32(G_STOP, 0)
        e.put32(G_ELAPSED, fb(1.0 / 60.0))
        e.put32(G_SOUND, 1)
        e.put32(G_COUNT, 0)

    # ---- the dumps -------------------------------------------------------

    def dump_key(self, tag, a):
        w = self.w
        self.emit("    %s m %s" % (tag, " ".join(fx(w(a + 4 * i))
                                                  for i in range(16))))
        self.emit("    %s p %s d %s t %s" % (
            tag, " ".join(fx(w(a + 64 + 4 * i)) for i in range(4)),
            " ".join(fx(w(a + 80 + 4 * i)) for i in range(4)),
            " ".join(fx(w(a + 96 + 4 * i)) for i in range(4))))
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

    def dump_mov(self, j):
        m = mov_at(j)
        w, hw = self.w, self.e.u16
        self.emit("  o%d type %d view %d en %d pview %s pcam %s player %08x"
                  " carnot %08x dash %08x vtbl %s next %s prev %s"
                  % (j, s32(w(m + 8)), s32(w(m + 12)), s32(w(m + 16)),
                     self.name(w(m + 20)), self.name(w(m + 24)), w(m + 28),
                     w(m + 32), w(m + 36), self.name(w(m + 40)),
                     self.name(w(m)), self.name(w(m + 4))))
        self.emit("    mode %d blend %s u52 %08x az %04x u58 %04x ts %04x"
                  " to %04x rs %s"
                  % (s32(w(m + 44)), fx(w(m + 48)), w(m + 52), hw(m + 56),
                     hw(m + 58), hw(m + 60), hw(m + 62), fx(w(m + 64))))
        self.emit("    os %s oo %s" % (
            " ".join(fx(w(m + 80 + 4 * i)) for i in range(3)),
            " ".join(fx(w(m + 96 + 4 * i)) for i in range(3))))
        self.emit("    qs %s qo %s" % (
            " ".join(fx(w(m + 112 + 4 * i)) for i in range(4)),
            " ".join(fx(w(m + 128 + 4 * i)) for i in range(4))))
        self.emit("    fov %04x %04x hs %s %s vs %s %s or %s rsp %s %s"
                  " snd %s n %d"
                  % (hw(m + 144), hw(m + 146), fx(w(m + 148)),
                     fx(w(m + 152)), fx(w(m + 156)), fx(w(m + 160)),
                     fx(w(m + 164)), fx(w(m + 168)), fx(w(m + 172)),
                     "".join("%d" % (w(m + 176 + 4 * i) != 0)
                             for i in range(4)),
                     s32(w(G_COUNT))))

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

    def dump_quat(self, tag, a):
        return " %s %s" % (tag, " ".join(fx(self.w(a + 4 * i))
                                         for i in range(4)))

    # ---- the ops ---------------------------------------------------------

    def vcall(self, j, slot, *args):
        e = self.e
        m = mov_at(j)
        vt = self.w(m + 40)
        delta = struct.unpack("<h", struct.pack("<H", e.u16(vt + slot - 4)))[0]
        fn = self.w(vt + slot)
        return e.call(fn, (m + delta) & M32, *args, limit=400000)

    def query(self, j):
        e = self.e
        e.call(GET_MODE_PARAM, mov_at(j), limit=1000)
        mode = e.fpr[0]
        info = self.vcall(j, SLOTS["info"])
        pov = self.vcall(j, SLOTS["pov"], 0)
        ext = self.vcall(j, SLOTS["ext"])
        lb = self.vcall(j, SLOTS["lookback"])
        self.vcall(j, SLOTS["gap"])
        gap = e.fpr[0]
        car = self.vcall(j, SLOTS["car"])
        tgt = self.vcall(j, SLOTS["target"])
        self.emit("  q o%d mode %s info %s pov %s ext %d lb %d gap %s car %s"
                  " tgt %s"
                  % (j, fx(mode), self.name(info), self.name(pov), ext, lb,
                     fx(gap), self.name(car), self.name(tgt)))

    def put_words(self, a, t):
        for i, x in enumerate(t):
            self.e.put32(a + 4 * i, int(x, 16))

    def call_f(self, fn, j, bits):
        self.e.fpr[12] = bits & M32
        self.e.call(fn, mov_at(j), limit=10000)

    def op(self, t):
        e = self.e
        c = t[0]
        if c == "C":
            k = int(t[1])
            self.fill(cam_at(k), CAM_SIZE)
            e.call(CAM_CTOR, cam_at(k), limit=200000)
            self.dump_cam(cam_at(k))
        elif c == "V":
            e.put32(view_at(int(t[1])) + V_CAMERA, cam_at(int(t[2])))
        elif c == "Z":
            e.put32(G_STOP, int(t[1]))
        elif c == "T":
            e.put32(G_ELAPSED, int(t[1], 16))
        elif c == "E":
            e.put32(G_SOUND, int(t[1]))
        elif c == "N":
            e.put32(G_COUNT, int(t[1], 16))
        elif c == "O":
            j, view = int(t[1]), int(t[2])
            self.fill(mov_at(j), MOV_SIZE)
            e.call(SEL_CTOR, mov_at(j), view, limit=400000)
            self.dump_mov(j)
            self.dump_views()
        elif c == "D":
            j = int(t[1])
            self.vcall(j, SLOTS["destroy"], 0)
            self.dump_mov(j)
            self.dump_views()
        elif c == "U":
            j = int(t[1])
            self.vcall(j, SLOTS["update"])
            self.dump_mov(j)
            cam = self.w(mov_at(j) + 24)
            if cam:
                self.dump_cam(cam)
        elif c == "M":
            j = int(t[1])
            e.call(SET_MODE, mov_at(j), int(t[2]), limit=10000)
            self.dump_mov(j)
        elif c == "R":
            j = int(t[1])
            self.call_f(SET_RADIUS_STATS, j, int(t[2], 16))
            self.dump_mov(j)
        elif c in "Aa":
            j = int(t[1])
            self.put_words(VEC, t[2:6])
            e.call(SET_OFFSET_STATS if c == "A" else SET_OFFSET_ORBIT,
                   mov_at(j), VEC, limit=1000)
            self.dump_mov(j)
        elif c in "Ww":
            j = int(t[1])
            e.call(SET_FOV_STATS if c == "W" else SET_FOV_ORBIT,
                   mov_at(j), int(t[2], 16), limit=1000)
            self.dump_mov(j)
        elif c == "S":
            j = int(t[1])
            e.call(SET_ORIENT_STATS, mov_at(j), int(t[2], 16),
                   int(t[3], 16), limit=100000)
            self.dump_mov(j)
        elif c == "s":
            j = int(t[1])
            e.call(SET_VERT_ORBIT, mov_at(j), int(t[2], 16), limit=1000)
            self.dump_mov(j)
        elif c == "P":
            j = int(t[1])
            fn = {"r": SET_DRADIUS, "v": SET_DVERT, "h": SET_DHORIZ}[t[2]]
            self.call_f(fn, j, int(t[3], 16))
            self.dump_mov(j)
        elif c == "G":
            self.query(int(t[1]))
        elif c == "F":
            j, (off, kind) = int(t[1]), FIELDS[t[2]]
            v = int(t[3], 16)
            a = mov_at(j) + off
            if kind == "h":
                self.put16(a, v)
            else:
                e.put32(a, v)
        elif c == "L":
            self.put_words(QA, t[1:5])
            self.put_words(QB, t[5:9])
            self.fill(QO, 16)
            e.fpr[12] = int(t[9], 16)
            e.call(SLERP, QO, QA, QB, limit=100000)
            self.emit("  slerp" + self.dump_quat("o", QO)
                      + self.dump_quat("a", QA) + self.dump_quat("b", QB))
        elif c == "X":
            self.put_words(QA, t[1:5])
            self.put_words(QB, t[5:9])
            self.fill(QO, 16)
            e.call(QUAT_MUL, QO, QA, QB, limit=10000)
            e.call(QUAT_MUL, QB, QA, QB, limit=10000)
            self.emit("  mul" + self.dump_quat("o", QO)
                      + self.dump_quat("b", QB))
        elif c == "Y":
            self.put_words(QA, t[1:5])
            e.call(QUAT_NORM, QA, limit=10000)
            self.emit("  norm" + self.dump_quat("q", QA))
        else:
            raise SystemExit("bad op %r" % (t,))

    def run(self, scenarios):
        for i, sc in enumerate(scenarios):
            self.emit("B %d" % i)
            self.reset()
            for ln in sc:
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


def build_harness(tmp, name="selcam_test"):
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


def M(name, before, after, rel=SELC):
    return (name, rel, before, after)


MUTATIONS = [
    # the constructor
    M("ctor-vtbl", "    o->base.vtbl = &SelectCarCameraMoverVtbl;\n"
      "    o->RadiusStats = 5.0f;", "    o->RadiusStats = 5.0f;"),
    M("ctor-type", "viewID, CM_SELECT_CAR);", "viewID, CM_SELECT_CAR + 1);"),
    M("ctor-radius-stats", "o->RadiusStats = 5.0f;",
      "o->RadiusStats = 5.5f;"),
    M("ctor-mode", "    o->Mode = 0;\n", "    o->Mode = 1;\n"),
    M("ctor-blend", "    o->Blend = 0.0f;\n    o->Unused52",
      "    o->Blend = 0.5f;\n    o->Unused52"),
    M("ctor-u52", "o->Unused52 = 0;", "o->Unused52 = 1;"),
    M("ctor-os", "o->OffsetStats.x = o->OffsetStats.y = o->OffsetStats.z"
      " = 0.0f;", "o->OffsetStats.x = o->OffsetStats.y = 0.0f;"
      " o->OffsetStats.z = 1.0f;"),
    M("ctor-oo", "    o->OffsetOrbit = o->OffsetStats;\n",
      "    o->OffsetOrbit = o->OffsetStats;\n    o->OffsetOrbit.y = 2.0f;\n"),
    M("ctor-fov-orbit", "o->FOVOrbit = 10000;", "o->FOVOrbit = 10001;"),
    M("ctor-fov-stats", "o->FOVStats = 10000;", "o->FOVStats = 9999;"),
    M("ctor-dvs", "o->DesiredVertSpeed = 300.0f;",
      "o->DesiredVertSpeed = 0.0f;"),
    M("ctor-or", "o->OrbitRadius = ORBIT_RADIUS;\n    o->FOVStats",
      "o->OrbitRadius = RADIUS_MIN;\n    o->FOVStats"),
    M("ctor-az", "    o->AngleZ = 0;\n", "    o->AngleZ = 1;\n"),
    M("ctor-u58", "o->Unused58 = 0;", "o->Unused58 = 1;"),
    M("ctor-ts", "    o->TiltStats = 0;\n", "    o->TiltStats = 1;\n"),
    M("ctor-to", "    o->TiltOrbit = 0;\n", "    o->TiltOrbit = TILT_RESET;\n"),
    M("ctor-hs", "    o->HorizSpeed = 300.0f;\n", "    o->HorizSpeed = 0.0f;\n"),
    M("ctor-dhs", "o->DesiredHorizSpeed = 300.0f;",
      "o->DesiredHorizSpeed = 0.0f;"),
    M("ctor-vs", "    o->VertSpeed = 300.0f;\n", "    o->VertSpeed = 0.0f;\n"),
    M("ctor-rsp", "    o->RadiusSpeed = 0.0f;\n    o->DesiredRadiusSpeed",
      "    o->RadiusSpeed = 1.0f;\n    o->DesiredRadiusSpeed"),
    M("ctor-drsp", "    o->DesiredRadiusSpeed = 0.0f;\n    for",
      "    o->DesiredRadiusSpeed = 1.0f;\n    for"),
    M("ctor-snd-always", "o->Samples[i] = SoundEnabled != 0;",
      "o->Samples[i] = 1;"),
    M("ctor-snd-none", "if (o->Samples[i]) snd_create(i);", "(void)0;"),
    # the destructor
    M("dtor-vtbl", "    o->base.vtbl = &SelectCarCameraMoverVtbl;\n"
      "    for (i = 0; i < SELCAM_SND_COUNT; i++) {\n"
      "        if (o->Samples[i]) snd_destroy(i);",
      "    for (i = 0; i < SELCAM_SND_COUNT; i++) {\n"
      "        if (o->Samples[i]) snd_destroy(i);"),
    M("dtor-no-del", "if (o->Samples[i]) snd_destroy(i);", "(void)0;"),
    M("dtor-zero", "if (o->Samples[i]) snd_destroy(i);",
      "if (o->Samples[i]) snd_destroy(i);\n        o->Samples[i] = 0;"),
    M("dtor-no-base", "    camera_mover_destroy(&o->base);\n}", "}"),
    # the setters
    M("set-rs", "    o->RadiusStats = r;", "    o->RadiusStats = -r;"),
    M("set-os", "    o->OffsetStats = *v;",
      "    o->OffsetStats = *v; o->OffsetStats.x = v->y;"),
    M("set-oo", "    o->OffsetOrbit = *v;",
      "    o->OffsetOrbit = *v; o->OffsetOrbit.z = v->x;"),
    M("set-fovs", "    o->FOVStats = fov;", "    o->FOVOrbit = fov;"),
    M("set-fovo", "    o->FOVOrbit = fov;", "    o->FOVStats = fov;"),
    M("set-az", "    o->AngleZ = angle;", "    o->AngleZ = tilt;"),
    M("set-ts-neg", "o->TiltStats = (uint16_t)-tilt;",
      "o->TiltStats = tilt;"),
    M("set-qs-angle", "quat_from_angle(&o->QuatStats, angle);",
      "quat_from_angle(&o->QuatStats, (uint16_t)-angle);"),
    M("set-to-neg", "o->TiltOrbit = (uint16_t)-tilt;",
      "o->TiltOrbit = tilt;"),
    M("set-drs", "o->DesiredRadiusSpeed = s;", "o->DesiredRadiusSpeed = -s;"),
    M("set-dvs", "o->DesiredVertSpeed = s;", "o->DesiredHorizSpeed = s;"),
    M("set-dhs", "o->DesiredHorizSpeed = s;\n}",
      "o->DesiredVertSpeed = s;\n}"),
    M("get-mode", "    return o->Blend;", "    return o->Blend + 1.0f;"),
    M("qfa-roty", "eRotateY(&m, &m, 0x8000);", "eRotateY(&m, &m, 0);"),
    M("qfa-rotz", "eRotateZ(&m, &m, angle);",
      "eRotateZ(&m, &m, (uint16_t)(angle + 1));"),
    # SetMode
    M("mode-store", "    o->Mode = mode;\n    if", "    o->Mode = 1;\n    if"),
    M("mode-snd-gate", "    if (!SoundEnabled) return;\n", ""),
    M("mode-off-vol", "snd_play(SELCAM_SND_OFF, 1.0f);",
      "snd_play(SELCAM_SND_OFF, 0.0f);"),
    M("mode-off-stop", "        snd_stop(SELCAM_SND_ACTIVE);\n", ""),
    M("mode-on-hum", "snd_play(SELCAM_SND_ACTIVE, 0.0f);",
      "snd_play(SELCAM_SND_ACTIVE, 1.0f);"),
    M("mode-on-on", "snd_play(SELCAM_SND_ON, 1.0f);",
      "snd_play(SELCAM_SND_BUMP, 1.0f);"),
    M("mode-other", "} else if (mode == SELCAM_MODE_ORBIT) {\n        snd_play",
      "} else {\n        snd_play"),
    # the speeds
    M("appr-up-clamp", "        if (want < v) *cur = want;", "        (void)0;"),
    M("appr-down-clamp", "        if (v < want) *cur = want;",
      "        (void)0;"),
    M("appr-up-rate", "v = v + RealTimeElapsed * rate;",
      "v = v + RealTimeElapsed * rate * 2.0f;"),
    M("appr-down-rate", "v = v - RealTimeElapsed * rate;",
      "v = v - RealTimeElapsed * rate * 0.5f;"),
    M("appr-h-rate", "o->DesiredHorizSpeed, HORIZ_RATE);",
      "o->DesiredHorizSpeed, VERT_RATE);"),
    M("appr-v-rate", "o->DesiredVertSpeed, VERT_RATE);",
      "o->DesiredVertSpeed, HORIZ_RATE);"),
    M("appr-r-rate", "o->DesiredRadiusSpeed, RADIUS_RATE);",
      "o->DesiredRadiusSpeed, 17.0f);"),
    # the bump
    M("bump-floor", "if (BUMP_MIN < volume && SoundEnabled)",
      "if (0.1f < volume && SoundEnabled)"),
    M("bump-snd", "if (BUMP_MIN < volume && SoundEnabled)",
      "if (BUMP_MIN < volume)"),
    M("bump-vol", "snd_play(SELCAM_SND_BUMP, volume);",
      "snd_play(SELCAM_SND_BUMP, 1.0f);"),
    # Update: the blend's curve and the reset
    M("upd-t-scale", "ee_trunc_w(o->Blend * 32768.0f)",
      "ee_trunc_w(o->Blend * 32767.0f)"),
    M("upd-t-one", "    t = 1.0f - (bCosBam", "    t = 1.001f - (bCosBam"),
    M("upd-t-clamp-hi", "    if (1.0f < t) t = 1.0f;\n", ""),
    M("upd-t-clamp-lo", "    if (t < 0.0f) t = 0.0f;\n", ""),
    M("upd-reset-cond", "if (o->Blend == 0.0f) {", "if (o->Blend <= 0.0f) {"),
    M("upd-reset-to", "        o->TiltOrbit = TILT_RESET;\n        o->OrbitRadius",
      "        o->TiltOrbit = TILT_MIN;\n        o->OrbitRadius"),
    M("upd-reset-or", "        o->OrbitRadius = ORBIT_RADIUS;\n        quat_from",
      "        o->OrbitRadius = RADIUS_MIN;\n        quat_from"),
    M("upd-reset-q", "quat_from_angle(&o->QuatOrbit, o->AngleZ);",
      "quat_from_angle(&o->QuatOrbit, 0);"),
    # Update: the spin
    M("upd-spin-mode", "    if (o->Mode == SELCAM_MODE_ORBIT) {\n"
      "        bMatrix4 spin;", "    if (o->Mode != SELCAM_MODE_STATS) {\n"
      "        bMatrix4 spin;"),
    M("upd-spin-sign", "(uint16_t)ee_trunc_w(o->HorizSpeed * RealTimeElapsed)",
      "(uint16_t)-ee_trunc_w(o->HorizSpeed * RealTimeElapsed)"),
    M("upd-spin-order", "selcam_quat_multiply(&o->QuatOrbit, &step,"
      " &o->QuatOrbit);", "selcam_quat_multiply(&o->QuatOrbit,"
      " &o->QuatOrbit, &step);"),
    M("upd-norm-mod", "if (n % 60 == 0)", "if (n % 61 == 0)"),
    M("upd-norm-new", "if (n % 60 == 0)", "if ((n + 1) % 60 == 0)"),
    M("upd-norm-unsigned", "if (n % 60 == 0)",
      "if ((uint32_t)n % 60u == 0)"),
    M("upd-norm-none", "if (n % 60 == 0) selcam_quat_normalize(&o->QuatOrbit);",
      "(void)0;"),
    M("upd-count", "SelCamNormalizeCount = (int32_t)((uint32_t)n + 1u);",
      "SelCamNormalizeCount = (int32_t)((uint32_t)n + 2u);"),
    # Update: the view's point and turn
    M("upd-slerp-t", "&o->QuatOrbit, t);", "&o->QuatOrbit, 1.0f - t);"),
    M("upd-pos-x", "pos.x = (o->OffsetOrbit.x - o->OffsetStats.x) * t"
      " + o->OffsetStats.x;", "pos.x = (o->OffsetOrbit.x - o->OffsetStats.x)"
      " * t;"),
    M("upd-pos-y", "pos.y = (o->OffsetOrbit.y - o->OffsetStats.y) * t"
      " + o->OffsetStats.y;", "pos.y = o->OffsetOrbit.y * t"
      " + o->OffsetStats.y * (1.0f - t);"),
    M("upd-pos-z", "pos.z = (o->OffsetOrbit.z - o->OffsetStats.z) * t"
      " + o->OffsetStats.z;", "pos.z = o->OffsetStats.z;"),
    M("upd-pos-pad", "    pos.pad = (o->OffsetOrbit.pad - o->OffsetStats.pad)"
      " * t\n              + o->OffsetStats.pad;", "    pos.pad = 7.0f;"),
    M("upd-rot-order", "eMulMatrix(&m, &m, &rot);",
      "eMulMatrix(&m, &rot, &m);"),
    # Update: the tilt
    M("upd-tilt-mode", "    if (o->Mode == SELCAM_MODE_ORBIT) {\n"
      "        float v = o->VertSpeed;", "    if (o->Mode != SELCAM_MODE_STATS)"
      " {\n        float v = o->VertSpeed;"),
    M("upd-tilt-step", "+ ee_trunc_w(v * RealTimeElapsed));",
      "+ ee_trunc_w(v * RealTimeElapsed) + 1);"),
    M("upd-tilt-max-cmp", "if (TILT_MAX < o->TiltOrbit) {",
      "if (TILT_MAX <= o->TiltOrbit) {"),
    M("upd-tilt-max-val", "            o->TiltOrbit = TILT_MAX;\n",
      "            o->TiltOrbit = TILT_MAX - 1;\n"),
    M("upd-tilt-max-bounce", "o->VertSpeed = -v * BOUNCE;",
      "o->VertSpeed = v * BOUNCE;"),
    M("upd-tilt-max-bump", "bump(fabsf(o->VertSpeed) * TILT_BUMP);\n"
      "        }\n        if (!(TILT_MIN", "bump(fabsf(o->VertSpeed) * TILT_BUMP"
      " * 2.0f);\n        }\n        if (!(TILT_MIN"),
    M("upd-tilt-min-cmp", "if (!(TILT_MIN < o->TiltOrbit)) {",
      "if (o->TiltOrbit < TILT_MIN) {"),
    M("upd-tilt-min-val", "            o->TiltOrbit = TILT_RESET;\n"
      "            o->VertSpeed", "            o->TiltOrbit = TILT_MIN;\n"
      "            o->VertSpeed"),
    M("upd-tilt-min-bounce", "o->VertSpeed = -o->VertSpeed * BOUNCE;",
      "o->VertSpeed = o->VertSpeed * BOUNCE;"),
    M("upd-tilt-min-bump", "            bump(fabsf(o->VertSpeed) * TILT_BUMP);\n"
      "        }\n    }", "        }\n    }"),
    M("upd-tilt-lerp", "+ t * (float)((int32_t)o->TiltOrbit",
      "+ 0.5f * t * (float)((int32_t)o->TiltOrbit"),
    M("upd-tilt-signed", "- (int32_t)o->TiltStats)));",
      "- (int32_t)(int16_t)o->TiltStats)));"),
    # Update: the radius and the hum
    M("upd-rad-mode", "    if (o->Mode == SELCAM_MODE_ORBIT) {\n"
      "        float vol;", "    if (o->Mode != SELCAM_MODE_STATS) {\n"
      "        float vol;"),
    M("upd-rad-step", "o->RadiusSpeed * RealTimeElapsed;",
      "o->RadiusSpeed * RealTimeElapsed * 0.5f;"),
    M("upd-rad-max-cmp", "if (RADIUS_MAX < o->OrbitRadius) {",
      "if (RADIUS_MAX <= o->OrbitRadius) {"),
    M("upd-rad-max-val", "o->OrbitRadius = RADIUS_MAX;",
      "o->OrbitRadius = 15.0f;"),
    M("upd-rad-max-bounce", "            o->RadiusSpeed = o->RadiusSpeed"
      " * -BOUNCE;\n            bump(fabsf(o->RadiusSpeed) * RADIUS_BUMP);\n"
      "        }\n        if (o->OrbitRadius < RADIUS_MIN)",
      "            o->RadiusSpeed = o->RadiusSpeed * BOUNCE;\n"
      "            bump(fabsf(o->RadiusSpeed) * RADIUS_BUMP);\n"
      "        }\n        if (o->OrbitRadius < RADIUS_MIN)"),
    M("upd-rad-min-cmp", "if (o->OrbitRadius < RADIUS_MIN) {",
      "if (o->OrbitRadius <= RADIUS_MIN) {"),
    M("upd-rad-min-val", "            o->OrbitRadius = RADIUS_MIN;\n",
      "            o->OrbitRadius = 11.0f;\n"),
    M("upd-rad-min-bump", "            bump(fabsf(o->RadiusSpeed)"
      " * RADIUS_BUMP);\n        }\n        // The hum",
      "            bump(fabsf(o->RadiusSpeed));\n        }\n        // The hum"),
    M("upd-vol-vert", "vol = fabsf(o->VertSpeed) * VOL_VERT;",
      "vol = fabsf(o->VertSpeed) * VOL_HORIZ;"),
    M("upd-vol-h-cmp", "if (vol < fabsf(o->HorizSpeed) * VOL_HORIZ)",
      "if (vol > fabsf(o->HorizSpeed) * VOL_HORIZ)"),
    M("upd-vol-r-cmp", "if (vol < fabsf(o->RadiusSpeed) * VOL_RADIUS)",
      "if (0)"),
    M("upd-vol-gate", "if (SoundEnabled && gSelCamSound) {",
      "if (gSelCamSound) {"),
    M("upd-pitch-order", "* PITCH_SCALE * PITCH_SLOPE",
      "* PITCH_SLOPE * PITCH_SCALE"),
    M("upd-pitch-base", "+ PITCH_BASE) - 1.0f);", "+ PITCH_BASE));"),
    M("upd-pitch-min", "((o->OrbitRadius - RADIUS_MIN)",
      "((o->OrbitRadius - 11.0f)"),
    # Update: the distance, the blend and the camera
    M("upd-dist", "dist = o->RadiusStats + t * (o->OrbitRadius"
      " - o->RadiusStats);", "dist = o->OrbitRadius + (1.0f - t)"
      " * (o->RadiusStats - o->OrbitRadius);"),
    M("upd-push-y", "    push.y = 0.0f;\n", "    push.y = 0.5f;\n"),
    M("upd-blend-down", "o->Blend = o->Blend - BLEND_STEP;",
      "o->Blend = o->Blend - 2.0f * BLEND_STEP;"),
    M("upd-blend-floor", "if (o->Blend < 0.0f) o->Blend = 0.0f;", "(void)0;"),
    M("upd-blend-up", "o->Blend = o->Blend + BLEND_STEP;",
      "o->Blend = o->Blend + 0.0301f;"),
    M("upd-blend-cap", "if (1.0f < o->Blend) o->Blend = 1.0f;", "(void)0;"),
    M("upd-blend-other", "    } else if (o->Mode == SELCAM_MODE_ORBIT) {\n"
      "        o->Blend", "    } else {\n        o->Blend"),
    M("upd-stop-gate", "    if (!CameraStopUpdating) {\n", "    if (1) {\n"),
    M("upd-fov", "cam->CurrentKey.FieldOfView = 4500;",
      "cam->CurrentKey.FieldOfView = 4501;"),
    M("upd-td", "cam->CurrentKey.TargetDistance = dist;",
      "cam->CurrentKey.TargetDistance = dist + 1.0f;"),
    M("upd-cam-time", "camera_set_matrix(cam, &m, RealTimeElapsed);",
      "camera_set_matrix(cam, &m, 1.0f / 60.0f);"),
    # the quaternion helpers
    M("mul-w", "float w = ((a->w * b->w - a->x * b->x) - a->y * b->y)",
      "float w = ((a->w * b->w - a->y * b->y) - a->x * b->x)"),
    M("mul-x", "- a->z * b->y) + a->w * b->x) + a->x * b->w;",
      "- a->z * b->y) + a->x * b->w) + a->w * b->x;"),
    M("mul-y", "+ a->w * b->y) + a->y * b->w;",
      "+ a->w * b->y) - a->y * b->w;"),
    M("mul-z", "float z = ((a->x * b->y - a->y * b->x)",
      "float z = ((a->y * b->x - a->x * b->y)"),
    M("mul-alias", "    o->w = w;\n    o->x = x;\n    o->y = y;\n"
      "    o->z = z;\n}\n\nvoid selcam_quat_normalize",
      "    o->w = w;\n    o->x = ((a->y * b->z - a->z * b->y) + a->w * b->x)"
      " + a->x * b->w;\n    o->y = y;\n"
      "    o->z = z;\n}\n\nvoid selcam_quat_normalize"),
    M("norm-sum", "float n = sqrtf(((q->x * q->x + q->y * q->y) + q->z * q->z)"
      "\n                    + q->w * q->w);",
      "float n = sqrtf(((q->w * q->w + q->x * q->x) + q->y * q->y)"
      "\n                    + q->z * q->z);"),
    M("norm-div", "    float w = q->w / n;", "    float w = q->w * (1.0f / n);"),
    # Slerp
    M("sl-neg-cmp", "if (c < 0.0f) {", "if (c <= 0.0f) {"),
    M("sl-neg-w", "        a->w = -a->w;\n", ""),
    M("sl-neg-c", "        c = -c;\n", ""),
    M("sl-eps", "if (SLERP_EPS < c + 1.0f) {", "if (1) {"),
    M("sl-near", "if (1.0f - c < SLERP_EPS) {", "if (1.0f - c < 0.06f) {"),
    M("sl-lin", "w0 = 1.0f - t;\n            w1 = t;",
      "w0 = 1.0f - t;\n            w1 = 1.0f - w0;"),
    M("sl-ang", "(uint16_t)(16384 - bASin(c));", "(uint16_t)(16383 - bASin(c));"),
    M("sl-w0", "w0 = bSinBam((uint16_t)ee_trunc_w(angf * (1.0f - t))) / s;",
      "w0 = bSinBam((uint16_t)ee_trunc_w(angf * (1.0f - t))) * (1.0f / s);"),
    M("sl-w1", "w1 = bSinBam((uint16_t)ee_trunc_w(angf * t)) / s;",
      "w1 = bSinBam((uint16_t)ee_trunc_w(angf * t + 0.5f)) / s;"),
    M("sl-rt-b", "        b->x = -ay;\n", "        b->x = ay;\n"),
    M("sl-rt-bw", "        b->w = az;\n", "        b->w = -az;\n"),
    M("sl-rt-w0", "((0.5f - t) * SLERP_PI)", "((1.0f - t) * SLERP_PI)"),
    M("sl-rt-w1", "ee_trunc_w((t * SLERP_PI) * SLERP_RAD_TO_BAM)",
      "ee_trunc_w(t * (SLERP_PI * SLERP_RAD_TO_BAM))"),
    M("sl-out-x", "o->x = w0 * a->x + w1 * b->x;",
      "o->x = w0 * a->x - w1 * b->x;"),
    M("sl-out-z", "o->z = w0 * a->z + w1 * b->z;", "o->z = w0 * a->z;"),
    # the vtable
    M("vt-target", "    return &m->pCamera->CurrentKey.Target;",
      "    return &m->pCamera->CurrentKey.Position;"),
    M("vt-car", "    (void)m;\n    return NULL;", "    return m;"),
]

EQUIVALENT = {
    "dtor-vtbl": "the base's destructor puts its own vtable in straight "
                 "after, and the deletes between go through the samples'",
    "upd-pos-pad": "eTranslate's translation matrix takes x, y and z only",
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
        todo, SOURCES, "selcam_test",
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
