#!/usr/bin/env python3
"""Cross-check 3DS Files/source/orbitcam.c, the orbit camera, against the
retail image itself, run in mipsemu.

The model is the image. OrbitCarCameraMover's constructor (0x00157e48),
destructor (0x00158080), Update (0x00158298), GetTarget (0x001580e0),
GetCarToFollow (0x0015fb18), AddJoyHandlers (0x00158100),
RemoveJoyHandlers (0x001581f8) and JoyHandler (0x001586c8) run as shipped,
through retail's vtable (0x002b1c50) where the game goes through it. Under
them run the CameraMover base, Camera::SetCameraMatrix, the matrix layer
and IsGameFlowPaused (0x001680b8), over retail's own eView table. The
harness (tools/src/orbit_test.c) runs the port over the same script, and
the two transcripts are diffed.

Stubs: bFunkDoesServerExist answers 0, as no debug server does for the
shipped game, and AddJoyHandler (0x00154140) and RemoveJoyHandler
(0x001541e8) print their arguments and do nothing else. The harness's
joystick layer prints the same. Everything else the mover reads is laid
out in memory by the script: the World at gp-22120 with its car list and
its Helicopter at 24, the cars (their links at 0 and 4, GeometryPosition
at 80, BodyMatrix at 144), a Chopper (Plan at 728, CurrentPos at 832,
Matrix at 848), the race coordinator at gp-22216, RealTimeElapsed at
gp-19596, Camera::StopUpdating at gp-21808, and the nine statics at
gp-21720 .. gp-21696 with the boom offset at 0x00334190.

Every camera and mover starts from a byte pattern, so what a call leaves
alone shows. A float prints as its bits, a NaN as "nan", and a pointer by
what it is.

    python tools/orbit_check.py
    python tools/orbit_check.py --mutate [--only a,b]
    python tools/orbit_check.py --dump out/orbit
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
from mipsemu import M32, f_to_bits, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/orbit_test.c"
ORBC = "3DS Files/source/orbitcam.c"
ORBH = "3DS Files/source/orbitcam.h"
RACEC = "3DS Files/source/race.c"
SOURCES = [HARNESS, ORBC, RACEC] + ["3DS Files/source/" + f for f in (
    "camera.c", "cammover.c", "eview.c", "emath.c", "bmatrix.c", "bmath.c",
    "bmathtab.c", "bvector.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
CAM_CTOR = 0x00156be0
ORBIT_CTOR = 0x00157e48
ORBIT_UPDATE = 0x00158298
ORBIT_JOY = 0x001586c8
ORBIT_VTBL = 0x002b1c50
BASE_VTBL = 0x002b1e50
ADD_JOY_HANDLER = 0x00154140
REMOVE_JOY_HANDLER = 0x001541e8
FUNK_EXISTS = 0x0025d220
EMATH_SINIT = 0x0011bf70          # writes eMulVector's (0, 0, 0, 1)
VIEWS = 0x002c95b0
VIEW_STRIDE = 128
NVIEWS = 10
V_CAMERA = 56
V_LIST = 60
JOLLY = 0x002fa860
BOOM = 0x00334190

G_STOP = GP - 21808               # Camera::StopUpdating
G_WORLD = GP - 22120              # pCurrentWorld
G_RC = GP - 22216                 # pRaceCoordinator
G_ELAPSED = GP - 19596            # RealTimeElapsed

# The statics: name -> (address, kind). `f` a float, `h` a halfword, `w` a
# word; the boom's four lanes are floats.
STATICS = {
    "use": (GP - 21720, "w"), "trad": (GP - 21716, "f"),
    "tah": (GP - 21712, "h"), "tav": (GP - 21710, "h"),
    "look": (GP - 21708, "f"), "ingame": (GP - 21704, "h"),
    "fefov": (GP - 21702, "h"), "th": (GP - 21700, "f"),
    "tfov": (GP - 21696, "h"),
    "bx": (BOOM, "f"), "by": (BOOM + 4, "f"), "bz": (BOOM + 8, "f"),
    "bw": (BOOM + 12, "f"),
}

CAM_SIZE = 464
CAMS = 0x01000000
NCAM = 6
MOV_SIZE = 208
MOVS = 0x01010000
MOV_STRIDE = 256
NMOV = 6
WORLD = 0x01020000
CARS = 0x01030000
CAR_STRIDE = 0x400
NCAR = 6
CHOPPER = 0x01040000
RC = 0x01050000

PATTERN = 0xa5

# The vtable's slots, by the function's offset.
SLOTS = {
    "destroy": 12, "update": 20, "render": 28, "addjoy": 36, "remjoy": 44,
    "info": 52, "pov": 60, "ext": 68, "lookback": 76, "gap": 84,
    "reset": 92, "enable": 100, "disable": 108, "car": 116, "target": 124,
}

# The fields a script sets, by retail's offset.
FIELDS = {
    "radius": (44, "f"), "dradius": (72, "f"), "minr": (80, "f"),
    "maxr": (76, "f"), "mult": (88, "f"), "angh": (48, "h"),
    "angv": (50, "h"), "dangv": (52, "h"), "minv": (84, "h"),
    "maxv": (86, "h"), "hs": (56, "w"), "vs": (60, "w"), "dhs": (64, "w"),
    "dvs": (68, "w"), "acc": (96, "w"), "appr": (104, "w"),
    "fe": (100, "w"), "chop": (180, "w"), "car": (176, "car"),
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


def car_at(i):
    return 0 if i < 0 else CARS + CAR_STRIDE * i


def view_at(i):
    return VIEWS + VIEW_STRIDE * i


# ============================================================ the scenarios


def rrot(rnd, row3=True):
    """A body matrix: a rotation by three random angles, now and then a
    scaled or sheared one, and a translation row the car path takes into
    its transpose with the rest."""
    a, b, c = (rnd.uniform(-math.pi, math.pi) for _ in range(3))
    ca, sa, cb, sb, cc, sc = (math.cos(a), math.sin(a), math.cos(b),
                              math.sin(b), math.cos(c), math.sin(c))
    rot = [[cb * cc, cb * sc, -sb],
           [sa * sb * cc - ca * sc, sa * sb * sc + ca * cc, sa * cb],
           [ca * sb * cc + sa * sc, ca * sb * sc - sa * cc, ca * cb]]
    m = []
    for r in range(3):
        m += [rot[r][0], rot[r][1], rot[r][2], 0.0]
    m += [0.0, 0.0, 0.0, 1.0]
    k = rnd.random()
    if k < 0.15:
        s = rnd.uniform(0.5, 2.0)
        for i in range(12):
            m[i] *= s
    elif k < 0.25:
        for r in range(3):
            m[4 * r + 3] = rnd.uniform(-2, 2)
    if row3 and rnd.random() < 0.5:
        m[12] = rnd.uniform(-50, 50)
        m[13] = rnd.uniform(-50, 50)
        m[14] = rnd.uniform(-50, 50)
        m[15] = rnd.choice((1.0, 1.0, 0.0, 2.5))
    return " ".join("%08x" % fb(x) for x in m)


def rvec(rnd, span=500.0):
    return " ".join("%08x" % fb(x) for x in (
        rnd.uniform(-span, span), rnd.uniform(-span, span),
        rnd.uniform(-span / 10, span / 10),
        rnd.choice((0.0, 0.0, 1.0, rnd.uniform(-3, 3)))))


def cars(rnd, n):
    return ["L %d" % n] + ["K %d %s %s" % (i, rvec(rnd), rrot(rnd))
                           for i in range(NCAR)]


def s_ctor(rnd):
    """Construction, destruction and the vtable's other slots."""
    # Camera 0 holds a car and a dash, which the constructor clears; the
    # frozen camera 3 keeps its.
    out = ["C 0", "C 1", "C 2", "V 0 0", "V 1 1", "V 4 2",
           "N 0 01030400 00000001"] + cars(rnd, 3)
    out += ["O 0 0 0 1", "P 0", "G 0", "O 1 1 -1 0", "G 1",
            "O 2 4 2 3", "G 2"]
    # Twice each way: the flag stops the second.
    out += ["v 0 addjoy", "v 0 remjoy", "v 0 remjoy", "v 0 addjoy",
            "v 0 addjoy"]
    out += ["v 1 reset", "v 1 render", "v 1 disable", "v 1 disable",
            "v 1 enable", "v 1 enable"]
    out += ["D 0", "D 1", "D 2"]
    # Built and destroyed while frozen: neither touches the camera, and a
    # detached one has none to touch.
    out += ["C 3", "V 2 3", "N 3 01030800 00000001", "Z 1", "O 3 2 1 0",
            "P 3", "D 3", "P 3", "O 4 -1 1 2", "G 4",
            "v 4 remjoy", "v 4 addjoy", "D 4", "Z 0"]
    # Two on one view: the second goes to the front.
    out += ["O 5 2 -1 7", "O 0 2 4 2", "U 0", "U 5", "D 5", "U 0", "D 0"]
    return out


def s_joy(rnd):
    """Every event from 40 to 60 at five values, with and without FEMode,
    and the car list walked both ways past its head."""
    out = ["C 0", "V 0 0"] + cars(rnd, 3) + ["O 0 0 0 1"]
    for fe in (0, 1, 3):
        out.append("F 0 fe %08x" % fe)
        for ev in range(40, 61):
            for val in (1, 0, 0x100, 0x1ff, 0x80):
                out.append("J 0 %d %d %08x" % (rnd.randrange(4), ev, val))
    out.append("F 0 fe 00000000")
    for _ in range(4):
        out.append("J 0 1 52 00000001")
    for _ in range(4):
        out.append("J 0 1 53 00000001")
    out += ["L 1", "F 0 car 00000000", "J 0 0 52 00000001",
            "J 0 0 53 00000001"]
    # A car on no list links to itself.
    out += ["F 0 car 00000004", "J 0 0 52 00000001", "J 0 0 53 00000001"]
    out += ["L 6", "F 0 car 00000005", "J 0 0 52 00000001",
            "J 0 0 53 00000001", "J 0 0 53 00000001", "G 0"]
    # Carless, the car keys do nothing unless they would step.
    out += ["F 0 car ffffffff", "J 0 0 52 00000000", "J 0 0 53 00000100",
            "F 0 fe 00000001", "J 0 0 52 00000001", "J 0 0 53 00000001",
            "F 0 fe 00000000"]
    return out


def update_frames(rnd, j, n):
    return ["U %d" % j for _ in range(n)]


def s_chopper(rnd):
    """FollowChopper against every Plan, with and without a Helicopter,
    a car, and the boom offset."""
    out = ["C 0", "V 0 0"] + cars(rnd, 2) + ["O 0 0 1 0", "O 1 0 -1 0",
                                             "F 0 chop 00000001",
                                             "F 1 chop 00000001", "U 0",
                                             "U 1"]
    for plan in (0, 1, 2, 3, 4, 5, 6, 7, 100, -1, -4):
        out.append("H %d %s %s" % (plan, rvec(rnd, 300.0), rrot(rnd)))
        out += ["U 0", "U 1"]
    out += ["S bx 3f800000", "S by c0000000", "S bz 40400000",
            "S bw 3e800000"]
    for plan in (4, 5):
        out.append("H %d %s %s" % (plan, rvec(rnd, 300.0), rrot(rnd)))
        out += ["U 0", "U 1"]
    out += ["S look 3fc00000", "U 0", "U 1", "H -", "U 0", "U 1",
            "J 0 0 54 00000001", "U 0", "J 0 0 54 00000001", "U 0"]
    return out


def s_pause(rnd):
    out = ["C 0", "V 0 0"] + cars(rnd, 1) + ["O 0 0 0 0",
                                             "F 0 dhs 000001f4"]
    for st in (-1, 0, 1, 5, 6, 7, 6, 12, -1):
        out += ["Q %d" % st, "U 0", "U 0"]
    return out


def s_limits(rnd):
    """The clamps and the approaches at their edges."""
    out = ["C 0", "V 0 0"] + cars(rnd, 1) + ["O 0 0 0 0"]
    # MinRadius above MaxRadius, from both sides.
    for dr, mn, mx in ((3.0, 5.0, 2.0), (1.0, 5.0, 2.0), (7.0, 5.0, 2.0),
                       (2.0, 5.0, 2.0), (4.0, 1.0, 8.0), (0.5, 1.0, 8.0),
                       (9.0, 1.0, 8.0), (-3.0, 0.0, 4.0)):
        out += ["F 0 dradius %08x" % fb(dr), "F 0 minr %08x" % fb(mn),
                "F 0 maxr %08x" % fb(mx), "F 0 radius %08x" % fb(99.0),
                "U 0"]
    out += ["F 0 minr 3f800000", "F 0 maxr 41400000",
            "F 0 dradius 40a00000"]
    for mult in (0.99, 1.01, 0.5, 1.0000001, 1.0, 2.0):
        out += ["F 0 mult %08x" % fb(mult)] + update_frames(rnd, 0, 4)
    out.append("F 0 mult 3f800000")
    # The speed approach: a gap of accel-1, accel and accel+1, both ways,
    # then a negative accel, which walks away.
    for acc, cur, want in ((24, 0, 23), (24, 0, 24), (24, 0, 25),
                           (24, 100, 76), (24, 100, 75), (24, 7, 7),
                           (0, 5, 9), (-24, 30, 30), (-24, 0, 50),
                           (-24, 50, 0), (100000, -70000, 70000)):
        out += ["F 0 acc %08x" % fb(acc), "F 0 hs %08x" % fb(cur),
                "F 0 dhs %08x" % fb(want), "F 0 vs %08x" % fb(cur),
                "F 0 dvs %08x" % fb(want), "U 0", "U 0"]
    out += ["F 0 acc 00000018", "F 0 hs 0", "F 0 dhs 0", "F 0 vs 0",
            "F 0 dvs 0"]
    # The AngleV walk: gaps of 79 .. 82 each way, across the halfword's
    # sign, and round zero the long way.
    out.append("F 0 appr 00000001")
    for cur, want in ((1000, 1079), (1000, 1080), (1000, 1081),
                      (1000, 1082), (1082, 1000), (1081, 1000),
                      (1080, 1000), (1079, 1000), (0x7fd0, 0x8030),
                      (0x8030, 0x7fd0), (100, 65000), (65000, 100),
                      (500, 500)):
        out += ["F 0 angv %08x" % cur, "F 0 dangv %08x" % want,
                "U 0", "U 0", "U 0"]
    out += ["F 0 appr 00000007", "F 0 vs 00000064", "F 0 dvs 00000064",
            "F 0 dangv 0000c350"] + update_frames(rnd, 0, 6)
    out.append("F 0 appr 00000000")
    # No clamp on AngleV any more: a held speed walks it anywhere.
    out += ["F 0 vs 000001f4", "F 0 dvs 000001f4", "F 0 minv 0000c738",
            "F 0 maxv 0000f8f4"] + update_frames(rnd, 0, 8)
    return out


def s_tweak(rnd):
    """The statics: the tweakables' switch, the FOVs, the two heights."""
    out = ["C 0", "C 1", "V 0 0", "V 1 1"] + cars(rnd, 1)
    out += ["O 0 0 0 0", "O 1 1 -1 0", "F 0 dhs 00000064",
            "F 1 dvs ffffff9c", "U 0", "U 1"]
    out += ["S use 00000001", "S trad 41200000", "S tah 00001234",
            "S tav 0000e000", "U 0", "U 1", "F 0 radius 40000000",
            "U 0", "S use 00000005", "U 0", "S use 00000000", "U 0"]
    out += ["S tfov 00000fa0", "S ingame 00001388", "U 0", "O 2 0 0 0",
            "U 2", "S fefov 00000064", "U 2"]
    out += ["S th bf000000", "U 1", "S look 40000000", "U 0", "U 1",
            "S th 00000000", "U 1"]
    out += ["T 3d088889", "U 0", "T 3f000000", "U 0", "T 00000000", "U 1",
            "T bf800000", "U 0", "T 3c888889", "U 0"]
    out += ["Z 1", "U 0", "U 1", "Z 0", "U 0"]
    return out


VALS_R = (0.5, 1.0, 2.5, 5.0, 12.0, 100.0, 1000.0, -3.0, 0.0, 7.25)
VALS_M = (1.0, 1.0, 0.99, 1.01, 0.5, 2.0, 1.0000001)
VALS_S = (0, 0, 24, -24, 500, -500, 300, -300, 7, 5000, -5000, 70000)


def s_walk(rnd, n):
    """A random walk over three movers on three views."""
    out = ["C 0", "C 1", "C 2", "V 0 0", "V 1 1", "V 2 2"] + cars(rnd, NCAR)
    car = {0: 0, 1: -1, 2: 2}
    fe = {0: 0, 1: 0, 2: 0}
    out += ["O 0 0 0 0", "O 1 1 -1 1", "O 2 2 2 3"]
    for _ in range(n):
        r = rnd.random()
        j = rnd.randrange(3)
        if r < 0.40:
            out.append("U %d" % j)
        elif r < 0.60:
            ev = rnd.randrange(44, 57)
            val = rnd.choice((0, 1, 1, 0x80, 0xff, 0x100, 0x1ff, 0xffffffff))
            steps = ev in (52, 53) and (val & 0xff) and not fe[j]
            if steps and car[j] < 0:
                continue
            if steps:
                car[j] = (car[j] + (1 if ev == 52 else -1)) % NCAR
            out.append("J %d %d %d %08x" % (j, rnd.randrange(4), ev, val))
        elif r < 0.76:
            f = rnd.choice(list(FIELDS))
            if f in ("radius", "dradius", "minr", "maxr"):
                v = fb(rnd.choice(VALS_R))
            elif f == "mult":
                v = fb(rnd.choice(VALS_M))
            elif f in ("angh", "angv", "dangv", "minv", "maxv"):
                v = rnd.getrandbits(16)
            elif f in ("hs", "vs", "dhs", "dvs"):
                v = fb(rnd.choice(VALS_S))
            elif f == "acc":
                v = fb(rnd.choice((24, 24, 0, 1, 500, 100000, -24)))
            elif f == "appr":
                v = rnd.choice((0, 0, 1, 2))
            elif f == "fe":
                v = rnd.choice((0, 0, 1, 5))
                fe[j] = v
            elif f == "chop":
                v = rnd.choice((0, 1))
            else:
                v = rnd.randrange(-1, NCAR)
                car[j] = v
                v = fb(v)
            out.append("F %d %s %08x" % (j, f, v))
        elif r < 0.80:
            s = rnd.choice(list(STATICS))
            f = STATICS[s][1]
            if s == "use":
                v = rnd.choice((0, 0, 0, 1))
            elif f == "h":
                v = rnd.getrandbits(16)
            elif s in ("bx", "by", "bz", "bw"):
                v = fb(rnd.choice((0.0, 0.0, 1.5, -2.0)))
            else:
                v = fb(rnd.choice((0.0, 0.3, 5.0, -1.25, 10.0)))
            out.append("S %s %08x" % (s, v))
        elif r < 0.83:
            out.append("T %08x" % fb(rnd.choice(
                (1.0 / 60, 1.0 / 30, 0.5, 1e-3, 2.0))))
        elif r < 0.86:
            out.append("Q %d" % rnd.choice((-1, -1, 0, 3, 6, 6, 7)))
        elif r < 0.88:
            out.append("Z %d" % rnd.choice((0, 0, 1)))
        elif r < 0.91:
            i = rnd.randrange(NCAR)
            out.append("K %d %s %s" % (i, rvec(rnd), rrot(rnd)))
        elif r < 0.94:
            if rnd.random() < 0.25:
                out.append("H -")
            else:
                out.append("H %d %s %s" % (rnd.choice(
                    (0, 1, 2, 3, 4, 5, 6, 7, -1)), rvec(rnd, 300.0),
                    rrot(rnd)))
        elif r < 0.96:
            out.append("G %d" % j)
        elif r < 0.98:
            out.append("v %d %s" % (j, rnd.choice(
                ("addjoy", "remjoy", "reset", "render", "enable",
                 "disable"))))
        else:
            # Rebuilt, on its own view, with a car or none.
            c = rnd.randrange(-1, NCAR)
            out += ["D %d" % j, "O %d %d %d %d" % (j, j, c, rnd.randrange(4))]
            car[j] = c
            fe[j] = 0
    out += ["Z 0", "Q -1"]
    return out


def script():
    rnd = random.Random(0x0cb17a11)
    sc = [s_ctor(rnd), s_joy(rnd), s_chopper(rnd), s_pause(rnd),
          s_limits(rnd), s_tweak(rnd)]
    for n in (200, 800, 1500):
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
        e.stub(ADD_JOY_HANDLER, self.rec_add)
        e.stub(REMOVE_JOY_HANDLER, self.rec_remove)
        e.put32(JOLLY, 0)
        e.call(EMATH_SINIT)
        assert e.u32(ORBIT_VTBL + SLOTS["update"]) == ORBIT_UPDATE
        e.put32(G_WORLD, WORLD)
        # The statics as the image ships them, put back for each scenario.
        self.statics = {s: self.get_static(s) for s in STATICS}
        self.names = {0: "null", BASE_VTBL: "base", ORBIT_VTBL: "orbit",
                      ORBIT_JOY: "joy", WORLD: "w", CHOPPER: "h"}
        for k in range(NCAM):
            c = cam_at(k)
            self.names[c] = "c%d" % k
            self.names[c + 64] = "c%d.pos" % k
            self.names[c + 80] = "c%d.dir" % k
            self.names[c + 96] = "c%d.tgt" % k
        for j in range(NMOV):
            self.names[mov_at(j)] = "o%d" % j
        for i in range(NCAR):
            self.names[car_at(i)] = "k%d" % i
            self.names[car_at(i) + 80] = "k%d.gpos" % i
        for i in range(NVIEWS):
            self.names[view_at(i)] = "v%d" % i
            self.names[view_at(i) + V_LIST] = "v%d.list" % i

    def emit(self, s):
        self.out.append(s)

    def name(self, a):
        return self.names.get(a & M32, "?%08x" % (a & M32))

    def arg(self, i):
        return self.e.reg[(4, 5, 6, 7)[i]] & M32

    def rec_add(self, em):
        self.emit("  addjoy port %d ev %d fn %s obj %s"
                  % (s32(self.arg(0)), s32(self.arg(1)),
                     self.name(self.arg(2)), self.name(self.arg(3))))

    def rec_remove(self, em):
        self.emit("  remjoy port %d ev %d" % (s32(self.arg(0)),
                                              s32(self.arg(1))))

    def fill(self, a, n):
        self.e.write(a, bytes([PATTERN]) * n)

    def w(self, a):
        return self.e.u32(a)

    def put16(self, a, v):
        self.e.mem[a] = v & 0xff
        self.e.mem[a + 1] = (v >> 8) & 0xff

    def get_static(self, s):
        a, kind = STATICS[s]
        return self.e.u16(a) if kind == "h" else self.w(a)

    def set_static(self, s, v):
        a, kind = STATICS[s]
        if kind == "h":
            self.put16(a, v)
        else:
            self.e.put32(a, v)

    def link_cars(self, n):
        e = self.e
        for i in range(NCAR):
            c = car_at(i)
            e.put32(c, c)
            e.put32(c + 4, c)
        e.put32(WORLD, WORLD)
        e.put32(WORLD + 4, WORLD)
        for i in range(n):
            c = car_at(i)
            tail = self.w(WORLD + 4)
            e.put32(c + 4, tail)
            e.put32(c, WORLD)
            e.put32(tail, c)
            e.put32(WORLD + 4, c)

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
        e.put32(G_RC, 0)
        e.put32(WORLD + 24, 0)
        self.link_cars(0)
        for s, v in self.statics.items():
            self.set_static(s, v)

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
        w, h = self.w, self.e.u16
        self.emit("  o%d type %d view %d en %d pview %s pcam %s player %08x"
                  " carnot %08x dash %08x vtbl %s next %s prev %s"
                  % (j, s32(w(m + 8)), s32(w(m + 12)), s32(w(m + 16)),
                     self.name(w(m + 20)), self.name(w(m + 24)), w(m + 28),
                     w(m + 32), w(m + 36), self.name(w(m + 40)),
                     self.name(w(m)), self.name(w(m + 4))))
        self.emit("    r %s dr %s h %04x v %04x dv %04x hs %d vs %d dhs %d"
                  " dvs %d"
                  % (fx(w(m + 44)), fx(w(m + 72)), h(m + 48), h(m + 50),
                     h(m + 52), s32(w(m + 56)), s32(w(m + 60)),
                     s32(w(m + 64)), s32(w(m + 68))))
        self.emit("    minr %s maxr %s minv %04x maxv %04x mult %s mrv %s"
                  " acc %d fe %d appr %d"
                  % (fx(w(m + 80)), fx(w(m + 76)), h(m + 84), h(m + 86),
                     fx(w(m + 88)), fx(w(m + 92)), s32(w(m + 96)),
                     s32(w(m + 100)), s32(w(m + 104))))
        self.emit("    car %s chop %d fecar %08x port %d ha %d tm %s"
                  % (self.name(w(m + 176)), s32(w(m + 180)), w(m + 184),
                     s32(w(m + 188)), s32(w(m + 192)),
                     "".join("%02x" % self.e.mem[m + 112 + i]
                             for i in range(64))))
        c = w(m + 24)
        if c:
            self.emit("    cam %s near %s far %s fd %s dof %s fov %04x"
                      " carnot %08x dash %08x"
                      % (self.name(c), fx(w(c + 124)), fx(w(c + 128)),
                         fx(w(c + 116)), fx(w(c + 120)), h(c + 132),
                         w(c + 444), w(c + 448)))

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
        return e.call(fn, (m + delta) & M32, *args, limit=400000)

    def query(self, j):
        e = self.e
        info = self.vcall(j, SLOTS["info"])
        pov0 = self.vcall(j, SLOTS["pov"], 0)
        pov3 = self.vcall(j, SLOTS["pov"], 3)
        ext = self.vcall(j, SLOTS["ext"])
        lb = self.vcall(j, SLOTS["lookback"])
        self.vcall(j, SLOTS["gap"])
        gap = e.fpr[0]
        car = self.vcall(j, SLOTS["car"])
        tgt = self.vcall(j, SLOTS["target"])
        self.emit("  q o%d info %s pov %s %s ext %d lb %d gap %s car %s tgt %s"
                  % (j, self.name(info), self.name(pov0), self.name(pov3),
                     ext, lb, fx(gap), self.name(car), self.name(tgt)))

    def put_vec(self, a, t):
        for i in range(4):
            self.e.put32(a + 4 * i, int(t[i], 16))

    def put_mat(self, a, t):
        for i in range(16):
            self.e.put32(a + 4 * i, int(t[i], 16))

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
        elif c == "P":
            self.dump_cam(cam_at(int(t[1])))
        elif c == "V":
            e.put32(view_at(int(t[1])) + V_CAMERA, cam_at(int(t[2])))
        elif c == "Z":
            e.put32(G_STOP, int(t[1]))
        elif c == "T":
            e.put32(G_ELAPSED, int(t[1], 16))
        elif c == "Q":
            s = int(t[1])
            if s < 0:
                e.put32(G_RC, 0)
            else:
                e.put32(RC, s)
                e.put32(G_RC, RC)
        elif c == "L":
            self.link_cars(int(t[1]))
        elif c == "K":
            a = car_at(int(t[1]))
            self.put_vec(a + 80, t[2:6])
            self.put_mat(a + 144, t[6:22])
        elif c == "H":
            if t[1] == "-":
                e.put32(WORLD + 24, 0)
            else:
                e.put32(CHOPPER + 728, int(t[1]))
                self.put_vec(CHOPPER + 832, t[2:6])
                self.put_mat(CHOPPER + 848, t[6:22])
                e.put32(WORLD + 24, CHOPPER)
        elif c == "S":
            self.set_static(t[1], int(t[2], 16))
        elif c == "O":
            j, view, car, port = (int(x) for x in t[1:5])
            self.fill(mov_at(j), MOV_STRIDE)
            e.call(ORBIT_CTOR, mov_at(j), view, car_at(car), port,
                   limit=400000)
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
        elif c == "J":
            j, port, ev = int(t[1]), int(t[2]), int(t[3])
            e.call(ORBIT_JOY, port, ev, int(t[4], 16), mov_at(j),
                   limit=100000)
            self.dump_mov(j)
        elif c == "v":
            j = int(t[1])
            if t[2] == "render":
                self.vcall(j, SLOTS["render"], view_at(3))
            else:
                self.vcall(j, SLOTS[t[2]])
            self.dump_mov(j)
            self.dump_views()
        elif c == "G":
            self.query(int(t[1]))
        elif c == "F":
            j, (off, kind) = int(t[1]), FIELDS[t[2]]
            v = int(t[3], 16)
            a = mov_at(j) + off
            if kind == "h":
                self.put16(a, v)
            elif kind == "car":
                e.put32(a, car_at(s32(v)))
            else:
                e.put32(a, v)
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


def build_harness(tmp, name="orbit_test"):
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


MUTATIONS = [
    # the constructor
    M("ctor_no_vtbl", ORBC,
      "    o->base.vtbl = &OrbitCarCameraMoverVtbl;\n\n    o->Radius", "    o->Radius"),
    M("ctor_radius", ORBC, "    o->Radius = 5.0f;", "    o->Radius = 4.0f;"),
    M("ctor_angleh", ORBC, "    o->AngleH = 26000;", "    o->AngleH = 26001;"),
    M("ctor_anglev", ORBC, "    o->AngleV = 0xf230;", "    o->AngleV = 0xf231;"),
    M("ctor_dangv", ORBC, "    o->DesiredAngleV = 0xf230;",
      "    o->DesiredAngleV = 0xf231;"),
    M("ctor_hs", ORBC, "    o->HRotationSpeed = 0;", "    o->HRotationSpeed = 1;"),
    M("ctor_vs", ORBC, "    o->VRotationSpeed = 0;", "    o->VRotationSpeed = 1;"),
    M("ctor_dhs", ORBC, "    o->DesiredHRotationSpeed = 0;",
      "    o->DesiredHRotationSpeed = 1;"),
    M("ctor_dvs", ORBC, "    o->DesiredVRotationSpeed = 0;",
      "    o->DesiredVRotationSpeed = 1;"),
    M("ctor_dradius", ORBC, "    o->DesiredRadius = 5.0f;",
      "    o->DesiredRadius = 6.0f;"),
    M("ctor_maxr", ORBC, "    o->MaxRadius = 1000.0f;", "    o->MaxRadius = 500.0f;"),
    M("ctor_minr", ORBC, "    o->MinRadius = 1.0f;", "    o->MinRadius = 0.5f;"),
    M("ctor_minv", ORBC, "    o->MinAngleV = 0xc738;", "    o->MinAngleV = 0xc739;"),
    M("ctor_maxv", ORBC, "    o->MaxAngleV = 0xf8f4;", "    o->MaxAngleV = 0xf8f5;"),
    M("ctor_mult", ORBC, "    o->RadiusMultiplier = 1.0f;",
      "    o->RadiusMultiplier = 0.99f;"),
    M("ctor_mrv", ORBC, "    o->MaxRadiusVel = 0.4f;", "    o->MaxRadiusVel = 0.5f;"),
    M("ctor_acc", ORBC, "    o->MaxRotationAccel = 24;",
      "    o->MaxRotationAccel = 25;"),
    M("ctor_fe", ORBC, "    o->FEMode = 0;", "    o->FEMode = 1;"),
    M("ctor_appr", ORBC, "    o->ApproachAngleV = 0;", "    o->ApproachAngleV = 1;"),
    M("ctor_car", ORBC, "    o->CarToFollow = car;", "    o->CarToFollow = NULL;"),
    M("ctor_chop", ORBC, "    o->FollowChopper = 0;", "    o->FollowChopper = 1;"),
    M("ctor_fecar", ORBC, "    o->FECarToFollow = NULL;",
      "    o->FECarToFollow = car;"),
    M("ctor_port", ORBC, "    o->JoyPort = joyPort;", "    o->JoyPort = 0;"),
    M("ctor_tm", ORBC, "    o->JoyPort = joyPort;\n",
      "    o->JoyPort = joyPort;\n    eIdentity(&o->TM);\n"),
    M("ctor_flags_frozen", ORBC,
      "    if (!CameraStopUpdating) {\n        cam->CarNotToRender = NULL;",
      "    if (1) {\n        cam->CarNotToRender = NULL;"),
    M("ctor_no_carnot", ORBC, "        cam->CarNotToRender = NULL;\n", ""),
    M("ctor_no_dash", ORBC, "        cam->RenderDash = 0;\n", ""),
    M("ctor_fov", ORBC, "cam->CurrentKey.FieldOfView = OrbitInGameFOV;",
      "cam->CurrentKey.FieldOfView = OrbitFrontEndFOV;"),
    M("ctor_ha_set", ORBC, "    o->HandlersAdded = 0;\n    orbit_add_joy_handlers(o);",
      "    o->HandlersAdded = 1;\n    orbit_add_joy_handlers(o);"),
    M("ctor_no_add", ORBC, "    o->HandlersAdded = 0;\n    orbit_add_joy_handlers(o);",
      "    o->HandlersAdded = 0;"),
    # the destructor
    M("dtor_no_vtbl", ORBC,
      "    o->base.vtbl = &OrbitCarCameraMoverVtbl;\n    orbit_remove_joy_handlers(o);",
      "    orbit_remove_joy_handlers(o);"),
    M("dtor_no_remove", ORBC, "    orbit_remove_joy_handlers(o);\n    cam", "    cam"),
    M("dtor_frozen", ORBC,
      "    if (!CameraStopUpdating) {\n        cam->CurrentKey.FocalDistance = 0.0f;",
      "    if (1) {\n        cam->CurrentKey.FocalDistance = 0.0f;"),
    M("dtor_fd", ORBC, "        cam->CurrentKey.FocalDistance = 0.0f;",
      "        cam->CurrentKey.FocalDistance = 1.0f;"),
    M("dtor_dof", ORBC, "        cam->CurrentKey.DepthOfField = 0.0f;",
      "        cam->CurrentKey.DepthOfField = 1.0f;"),
    M("dtor_no_base", ORBC, "    camera_mover_destroy(&o->base);\n", ""),
    # Update: the pause, the chopper, the car
    M("upd_no_pause", ORBC, "    if (is_game_flow_paused())\n        return;\n", ""),
    M("upd_chop_ignored", ORBC, "    if (o->FollowChopper) {", "    if (0) {"),
    M("upd_plan_signed", ORBC,
      "(uint32_t)h->Plan < (uint32_t)CHOPPLAN_START_CHASE",
      "h->Plan < CHOPPLAN_START_CHASE"),
    M("upd_plan_le", ORBC,
      "(uint32_t)h->Plan < (uint32_t)CHOPPLAN_START_CHASE",
      "(uint32_t)h->Plan <= (uint32_t)CHOPPLAN_START_CHASE"),
    M("upd_plan_bombing", ORBC, "h->Plan == CHOPPLAN_BOMBING_RUN",
      "h->Plan == CHOPPLAN_END_CHASE"),
    M("upd_chop_row3_kept", ORBC, "            body.v3.x = 0.0f;\n", ""),
    M("upd_chop_w_zeroed", ORBC, "            body.v3.z = 0.0f;\n",
      "            body.v3.z = 0.0f;\n            body.v3.w = 0.0f;\n"),
    M("upd_chop_boom", ORBC, "            followed = 1;\n",
      "            followed = 1;\n            m.v3.x = m.v3.x + OrbitBoomOffset.x;\n"),
    M("upd_follow_look", ORBC, "    trans.v3.z = -pos->z - OrbitLookHeight;",
      "    trans.v3.z = -pos->z + OrbitLookHeight;"),
    M("upd_follow_sign", ORBC, "    trans.v3.x = -pos->x;", "    trans.v3.x = pos->x;"),
    M("upd_follow_order", ORBC, "    eMulMatrix(m, &trans, &inv);",
      "    eMulMatrix(m, &inv, &trans);"),
    M("upd_follow_no_transpose", ORBC, "    eTransposeMatrix(&inv, body);",
      "    inv = *body;"),
    M("upd_boom_no_w", ORBC, "            m.v3.w = m.v3.w + OrbitBoomOffset.pad;\n", ""),
    M("upd_boom_sign", ORBC, "            m.v3.x = m.v3.x + OrbitBoomOffset.x;",
      "            m.v3.x = m.v3.x - OrbitBoomOffset.x;"),
    M("upd_carless_look", ORBC, "            m.v3.z = -OrbitTargetHeight;",
      "            m.v3.z = -OrbitLookHeight;"),
    M("upd_carless_sign", ORBC, "            m.v3.z = -OrbitTargetHeight;",
      "            m.v3.z = OrbitTargetHeight;"),
    # Update: the radius
    M("upd_mult_always", ORBC, "    if (o->RadiusMultiplier != 1.0f)\n",
      "    if (1)\n"),
    M("upd_mult_above", ORBC, "    if (o->RadiusMultiplier != 1.0f)\n",
      "    if (o->RadiusMultiplier > 1.0f)\n"),
    M("upd_mult_on_radius", ORBC,
      "        o->DesiredRadius = o->DesiredRadius * o->RadiusMultiplier;",
      "        o->Radius = o->DesiredRadius * o->RadiusMultiplier;"),
    M("upd_radius_no_min", ORBC,
      "    if (o->DesiredRadius < o->MinRadius)\n        o->Radius = o->MinRadius;\n", ""),
    M("upd_radius_max_desired", ORBC, "    if (o->MaxRadius < o->Radius)\n",
      "    if (o->MaxRadius < o->DesiredRadius)\n"),
    M("upd_dr_no_min", ORBC,
      "    if (o->DesiredRadius < o->MinRadius)\n        o->DesiredRadius = o->MinRadius;\n",
      ""),
    M("upd_dr_no_max", ORBC,
      "    if (o->MaxRadius < o->DesiredRadius)\n        o->DesiredRadius = o->MaxRadius;\n",
      ""),
    M("upd_dr_order", ORBC,
      "    if (o->DesiredRadius < o->MinRadius)\n        o->DesiredRadius = o->MinRadius;\n"
      "    if (o->MaxRadius < o->DesiredRadius)\n        o->DesiredRadius = o->MaxRadius;\n",
      "    if (o->MaxRadius < o->DesiredRadius)\n        o->DesiredRadius = o->MaxRadius;\n"
      "    if (o->DesiredRadius < o->MinRadius)\n        o->DesiredRadius = o->MinRadius;\n"),
    # Update: the speeds and the angles
    M("upd_approach_le", ORBC, "    return accel < diff ? stepped : want;",
      "    return accel <= diff ? stepped : want;"),
    M("upd_approach_never_snaps", ORBC, "    return accel < diff ? stepped : want;",
      "    return stepped;"),
    M("upd_approach_instant", ORBC, "    return accel < diff ? stepped : want;",
      "    return want;"),
    M("upd_approach_tie_up", ORBC, "    if (cur < want) {", "    if (cur <= want) {"),
    M("upd_v_wants_h", ORBC,
      "o->VRotationSpeed = approach(o->VRotationSpeed, o->DesiredVRotationSpeed,",
      "o->VRotationSpeed = approach(o->VRotationSpeed, o->DesiredHRotationSpeed,"),
    M("upd_anglev_sub", ORBC,
      "    o->AngleV = (uint16_t)(o->AngleV + o->VRotationSpeed);",
      "    o->AngleV = (uint16_t)(o->AngleV - o->VRotationSpeed);"),
    M("upd_angleh_vspeed", ORBC,
      "    o->AngleH = (uint16_t)(o->AngleH + o->HRotationSpeed);",
      "    o->AngleH = (uint16_t)(o->AngleH + o->VRotationSpeed);"),
    M("upd_anglev_clamped", ORBC,
      "    o->AngleH = (uint16_t)(o->AngleH + o->HRotationSpeed);\n",
      "    o->AngleH = (uint16_t)(o->AngleH + o->HRotationSpeed);\n"
      "    if (o->MaxAngleV < o->AngleV)\n        o->AngleV = o->MaxAngleV;\n"
      "    if (o->AngleV < o->MinAngleV)\n        o->AngleV = o->MinAngleV;\n"),
    M("upd_appr_off", ORBC, "    if (o->ApproachAngleV) {", "    if (0) {"),
    M("upd_appr_signed", ORBC, "        if (o->AngleV < o->DesiredAngleV) {",
      "        if ((int16_t)o->AngleV < (int16_t)o->DesiredAngleV) {"),
    M("upd_appr_up_step", ORBC, "(uint16_t)(o->AngleV + 80)",
      "(uint16_t)(o->AngleV + 79)"),
    M("upd_appr_down_step", ORBC, "(uint16_t)(o->AngleV - 80)",
      "(uint16_t)(o->AngleV - 79)"),
    M("upd_appr_up_80", ORBC, "if ((int)(o->DesiredAngleV - o->AngleV) < 81)",
      "if ((int)(o->DesiredAngleV - o->AngleV) < 80)"),
    M("upd_appr_up_82", ORBC, "if ((int)(o->DesiredAngleV - o->AngleV) < 81)",
      "if ((int)(o->DesiredAngleV - o->AngleV) < 82)"),
    M("upd_appr_down_82", ORBC, "if ((int)(o->AngleV - o->DesiredAngleV) < 81)",
      "if ((int)(o->AngleV - o->DesiredAngleV) < 82)"),
    # Update: the tweakables, the rotations, the camera
    M("upd_tweak_ignored", ORBC, "    if (OrbitUseTweakables) {", "    if (0) {"),
    M("upd_tweak_h", ORBC, "        angleH = OrbitTweakAngleH;",
      "        angleH = o->AngleH;"),
    M("upd_tweak_v", ORBC, "        angleV = OrbitTweakAngleV;",
      "        angleV = o->AngleV;"),
    M("upd_tweak_r", ORBC, "        radius = OrbitTweakRadius;",
      "        radius = o->Radius;"),
    M("upd_rot_order", ORBC,
      "    eRotateZ(&m, &m, angleH);\n    eRotateY(&m, &m, angleV);",
      "    eRotateY(&m, &m, angleV);\n    eRotateZ(&m, &m, angleH);"),
    M("upd_boom_y", ORBC, "    boom.x = radius;\n    boom.y = 0.0f;",
      "    boom.x = 0.0f;\n    boom.y = radius;"),
    M("upd_rotx", ORBC, "    eRotateX(&m, &m, 16384);", "    eRotateX(&m, &m, 49152);"),
    M("upd_roty", ORBC, "    eRotateY(&m, &m, 0xc000);", "    eRotateY(&m, &m, 0x4000);"),
    M("upd_cam_frozen", ORBC,
      "    if (!CameraStopUpdating) {\n        // TweakOrbitFOV",
      "    if (1) {\n        // TweakOrbitFOV"),
    M("upd_fov_ingame", ORBC, "cam->CurrentKey.FieldOfView = OrbitTweakOrbitFOV;",
      "cam->CurrentKey.FieldOfView = OrbitInGameFOV;"),
    M("upd_td_desired", ORBC, "        cam->CurrentKey.TargetDistance = o->Radius;",
      "        cam->CurrentKey.TargetDistance = o->DesiredRadius;"),
    M("upd_td_tweak", ORBC, "        cam->CurrentKey.TargetDistance = o->Radius;",
      "        cam->CurrentKey.TargetDistance = radius;"),
    M("upd_fd", ORBC, "        cam->CurrentKey.FocalDistance = o->Radius;",
      "        cam->CurrentKey.FocalDistance = 0.0f;"),
    M("upd_dof", ORBC, "        cam->CurrentKey.DepthOfField = 8.0f;",
      "        cam->CurrentKey.DepthOfField = 4.0f;"),
    M("upd_elapsed", ORBC,
      "    orbit_update((OrbitCarCameraMover *)m, RealTimeElapsed);",
      "    orbit_update((OrbitCarCameraMover *)m, 1.0f / 60.0f);"),
    M("upd_no_setmatrix", ORBC, "    camera_set_matrix(cam, &m, elapsed);\n", ""),
    # GetTarget, GetCarToFollow and the vtable
    M("tgt_position", ORBC, "    return &o->CarToFollow->State.GeometryPosition;",
      "    return &o->CarToFollow->State.Position;"),
    M("tgt_carless", ORBC, "    return &o->base.pCamera->CurrentKey.Target;",
      "    return &o->base.pCamera->CurrentKey.Position;"),
    M("car_none", ORBC, "    return ((OrbitCarCameraMover *)m)->CarToFollow;",
      "    return NULL;"),
    M("vtbl_joy_swapped", ORBC,
      "    orbit_add_joy_handlers_thunk,\n    orbit_remove_joy_handlers_thunk,",
      "    orbit_remove_joy_handlers_thunk,\n    orbit_add_joy_handlers_thunk,"),
    M("vtbl_reset_removes", ORBC, "    camera_mover_nothing,       // ResetState",
      "    orbit_remove_joy_handlers_thunk,"),
    # the joystick
    M("add_twice", ORBC, "    if (o->HandlersAdded)\n        return;\n", ""),
    M("add_no_flag", ORBC, "    o->HandlersAdded = 1;\n}", "}"),
    M("add_last_short", ORBC,
      "         ev <= JOY_EVENT_DEBUG_CAMERA_FOLLOW_CHOPPER; ev++)\n        AddJoyHandler",
      "         ev < JOY_EVENT_DEBUG_CAMERA_FOLLOW_CHOPPER; ev++)\n        AddJoyHandler"),
    M("add_obj", ORBC, "AddJoyHandler(o->JoyPort, ev, orbit_joy_handler, o);",
      "AddJoyHandler(o->JoyPort, ev, orbit_joy_handler, NULL);"),
    M("add_port", ORBC, "AddJoyHandler(o->JoyPort, ev,", "AddJoyHandler(0, ev,"),
    M("rem_twice", ORBC, "    if (!o->HandlersAdded)\n        return;\n", ""),
    M("rem_no_flag", ORBC, "    o->HandlersAdded = 0;\n}\n\n// The car after", "}\n\n// The car after"),
    M("rem_port", ORBC, "RemoveJoyHandler(o->JoyPort, ev);", "RemoveJoyHandler(0, ev);"),
    M("joy_speed_swapped", ORBC, "o->FEMode ? ORBIT_JOY_SPEED_FE : ORBIT_JOY_SPEED",
      "o->FEMode ? ORBIT_JOY_SPEED : ORBIT_JOY_SPEED_FE"),
    M("joy_right_sign", ORBC, "o->DesiredHRotationSpeed = value ? -speed : 0;",
      "o->DesiredHRotationSpeed = value ? speed : 0;"),
    M("joy_left_rest", ORBC, "o->DesiredHRotationSpeed = value ? speed : 0;",
      "o->DesiredHRotationSpeed = value ? speed : o->DesiredHRotationSpeed;"),
    M("joy_up_sign", ORBC, "o->DesiredVRotationSpeed = value ? -speed : 0;",
      "o->DesiredVRotationSpeed = value ? speed : 0;"),
    M("joy_down_rest", ORBC, "o->DesiredVRotationSpeed = value ? speed : 0;",
      "o->DesiredVRotationSpeed = value ? speed : o->DesiredVRotationSpeed;"),
    M("joy_closer_out", ORBC, "value ? ORBIT_ZOOM_IN : 1.0f", "value ? ORBIT_ZOOM_OUT : 1.0f"),
    M("joy_farther_rest", ORBC, "value ? ORBIT_ZOOM_OUT : 1.0f",
      "value ? ORBIT_ZOOM_OUT : 0.99f"),
    # One ULP each way. The hex literal's last digit carries a bit past the
    # float's 23, so a step of one there rounds back to the same float.
    M("joy_zoom_in_value", ORBH, "0x1.fae148p-1f", "0x1.fae146p-1f"),
    M("joy_zoom_out_value", ORBH, "0x1.028f5cp+0f", "0x1.028f5ep+0f"),
    M("joy_speed_value", ORBH, "#define ORBIT_JOY_SPEED     500",
      "#define ORBIT_JOY_SPEED     501"),
    M("joy_speed_fe_value", ORBH, "#define ORBIT_JOY_SPEED_FE  300",
      "#define ORBIT_JOY_SPEED_FE  301"),
    M("joy_next_in_fe", ORBC,
      "        if (!o->FEMode && value)\n            o->CarToFollow = orbit_step_car(o->CarToFollow, 0);",
      "        if (value)\n            o->CarToFollow = orbit_step_car(o->CarToFollow, 0);"),
    M("joy_prev_on_release", ORBC,
      "        if (!o->FEMode && value)\n            o->CarToFollow = orbit_step_car(o->CarToFollow, 1);",
      "        if (!o->FEMode)\n            o->CarToFollow = orbit_step_car(o->CarToFollow, 1);"),
    M("joy_next_back", ORBC, "orbit_step_car(o->CarToFollow, 0)",
      "orbit_step_car(o->CarToFollow, 1)"),
    M("joy_no_skip", ORBC,
      "    if (n == (CarNode *)(void *)pCurrentWorld)\n        n = back ? n->prev : n->next;\n",
      ""),
    M("joy_skip_back", ORBC, "        n = back ? n->prev : n->next;",
      "        n = back ? n->next : n->prev;"),
    M("joy_chop_on_release", ORBC,
      "        if (value)\n            o->FollowChopper = !o->FollowChopper;",
      "        o->FollowChopper = !o->FollowChopper;"),
    M("joy_chop_set", ORBC, "o->FollowChopper = !o->FollowChopper;",
      "o->FollowChopper = 1;"),
    # IsGameFlowPaused
    M("paused_state", RACEC, "        && racecoordinator_get_current_state(pRaceCoordinator) == RCSTATE_PAUSE;",
      "        && racecoordinator_get_current_state(pRaceCoordinator) != RCSTATE_PAUSE;"),
    M("paused_no_null", RACEC, "    return pRaceCoordinator != NULL\n        && ", "    return "),
]

# Mutants that cannot change what either side computes, each with why.
EQUIVALENT = {
    "dtor_no_vtbl": "the destructor's own vtable store is dead: nothing "
                    "between it and the base destructor's store reads it",
    "upd_mult_always": "multiplying by exactly 1.0f gives back the same "
                       "float, zeros and NaNs included",
    "upd_approach_le": "at a gap of exactly accel the step lands exactly on "
                       "want, so both arms agree",
    "upd_appr_up_80": "a gap of exactly 80 is snapped to or stepped onto, "
                      "and both give DesiredAngleV",
    "upd_td_desired": "Radius and DesiredRadius go through the same two "
                      "compares from the same value, so they are equal "
                      "when TargetDistance reads one",
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
