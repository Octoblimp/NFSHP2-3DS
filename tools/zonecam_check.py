#!/usr/bin/env python3
"""Cross-check 3DS Files/source/zonecam.c, the freeze zone's camera, and
the parts of spline.c and banim.c it brought with it, against the retail
image itself, run in mipsemu.

The model is the image. ZoneFreezeCameraMover's constructor (0x00160298),
destructor (0x00161000) and Update (0x001610a8) run as shipped, through
retail's vtable (0x002b20d0) where the game goes through it, with
ConstrainToTopology (0x0015fd80), EnsureEyeAboveGround (0x00160048), Spline's
allocating constructor (0x00189198), AddControlPoint (0x00189480), GetPoint
and GetDerivative (0x001899f8), tCubic3D's setters, GetVal and SplineSeek,
the CameraMover base, Camera::SetCameraMatrix, the matrix layer, bATan,
bSin and IsGameFlowPaused under them, over retail's own eView table. The
harness (tools/src/zonecam_test.c) runs the port over the same script, and
the two transcripts are diffed.

Stubs, printing what they are given on both sides: bMalloc hands out
blocks from a patterned arena, __builtin_delete and __builtin_vec_delete
print the block; TopologyCoordinate's constructor and destructor,
SetInterestBBox (0x00136e00), GetElevation (answers from a scripted list)
and ConstrainToTopology's member (0x001528b0, moves `to` and answers from a
scripted list); RadialBlurOff, RadialBlurAlpha and Player::UpdateZoneSound
(0x001784c0). The saved mover's IsExteriorView answers from the script, a
stub in a copy of the base vtable. Everything else the mover reads is laid
out by the script: the car (Position at 96, Velocity at 112, BodyMatrix at
144, VelocityMagnitude at 964), the players' numbers, the camera's keys,
the race coordinator at gp-22216, WorldTimeElapsed at gp-19560,
RealTimeElapsed at gp-19596, Camera::StopUpdating at gp-21808 and
SoundEnabled at gp-23056.

Every camera, mover, car and block starts from a byte pattern, so what a
call leaves alone shows. A float prints as its bits, a NaN as "nan", and a
pointer by what it is. The topology stubs print their vectors without the
pad lanes: Update's eye and look come from tCubic3D::GetVal, which writes
three lanes, and retail leaves stack words in the fourth.

    python tools/zonecam_check.py
    python tools/zonecam_check.py --mutate [--only a,b]
    python tools/zonecam_check.py --dump out/zonecam
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

HARNESS = "tools/src/zonecam_test.c"
ZCC = "3DS Files/source/zonecam.c"
SPC = "3DS Files/source/spline.c"
BAC = "3DS Files/source/banim.c"
SOURCES = [HARNESS, ZCC, SPC, BAC] + ["3DS Files/source/" + f for f in (
    "cammover.c", "race.c", "camera.c", "eview.c", "emath.c", "bmatrix.c",
    "bmath.c", "replay.c", "p32.c", "bmathtab.c", "bvector.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
CAM_CTOR = 0x00156be0
ZF_CTOR = 0x00160298
ZF_UPDATE = 0x001610a8
ZF_DTOR = 0x00161000
ZF_VTBL = 0x002b20d0
BASE_VTBL = 0x002b1e50
SPL_ALLOC = 0x00189198
SPL_CTOR = 0x00189238
SPL_DTOR = 0x00189268
SPL_ADD = 0x00189480
SPL_GETPT = 0x00189948
SPL_DERIV = 0x001899f8
BMALLOC = 0x002577c0
DELETE = 0x00114e98
VEC_DELETE = 0x00114e90
TOPO_CTOR = 0x00151c28
TOPO_DTOR = 0x00151c70
SET_BBOX3 = 0x00136e00            # SetInterestBBox(bVector3), j 0x00151d30
GET_ELEV = 0x00152070
CONSTRAIN = 0x001528b0            # TopologyCoordinate::ConstrainToTopology
BLUR_OFF = 0x0010f1b0
BLUR_ALPHA = 0x0010f238
ZONE_SOUND = 0x001784c0           # Player::UpdateZoneSound
FUNK_EXISTS = 0x0025d220
EMATH_SINIT = 0x0011bf70          # writes eMulVector's (0, 0, 0, 1)
BMATRIX_SINIT = 0x0025afa8        # 0x00320a60 = (0, 0, 0, 1), bMulMatrix's
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
G_SOUND = GP - 23056              # SoundEnabled

CAM_SIZE = 464
CAMS = 0x01000000
NCAM = 2
MOVS = 0x01010000
MOV_STRIDE = 0x400
NMOV = 2
CARS = 0x01020000
CAR_STRIDE = 0x1000
NCAR = 2
PLAYERS = 0x01030000
PL_STRIDE = 0x100
NPL = 2
SAVED = 0x01031000
SVTBL = 0x01031100
EXT_FN = 0x01031200               # the saved mover's IsExteriorView
SPL = 0x01031400
OUTV = 0x01031440
RC = 0x01031480
FOVT = 0x01032000
EYEV = 0x01032400
NFOV = 32
NEYE = 8
ARENA = 0x01040000
ARENA_SIZE = 0x40000

C_POS = 96
C_VEL = 112
C_BODY = 144
C_VMAG = 964
P_NUMBER = 16
M_TC = 168

PATTERN = 0xa5

# The vtable's slots, by the function's offset.
SLOTS = {
    "destroy": 12, "update": 20, "render": 28, "info": 52, "pov": 60,
    "ext": 68, "lookback": 76, "gap": 84, "car": 116, "target": 124,
}

ARRAYS = {"f": FOVT, "e": EYEV}


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


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def bits_f(w):
    return struct.unpack("<f", struct.pack("<I", w & M32))[0]


def cam_at(k):
    return CAMS + CAM_SIZE * k


def mov_at(j):
    return MOVS + MOV_STRIDE * j


def car_at(i):
    return 0 if i < 0 else CARS + CAR_STRIDE * i


def pl_at(i):
    return 0 if i < 0 else PLAYERS + PL_STRIDE * i


def view_at(i):
    return VIEWS + VIEW_STRIDE * i


# ============================================================ the scenarios


def vec(*xs):
    return " ".join(h(x) for x in xs)


def rot_rows(rnd):
    """A body matrix: a rotation by three random angles and a translation
    row."""
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
    return m


def upright_rows(rnd, eps):
    """A car standing on its tail: the nose's z `eps` short of 1, the
    roof's x and y well off 0."""
    m = rot_rows(rnd)
    m[0:4] = [rnd.choice((-1, 1)) * rnd.uniform(0.001, 0.04),
              rnd.choice((-1, 1)) * rnd.uniform(0.001, 0.04), 1.0 - eps, 0.0]
    a = rnd.uniform(-math.pi, math.pi)
    m[8:12] = [math.cos(a), math.sin(a), rnd.uniform(-0.05, 0.05), 0.0]
    return m


def car_line(rnd, i, pos, vel, body, vmag, pads=None):
    pp, vp = pads if pads else (rnd.choice((0.0, 1.0, rnd.uniform(-2, 2))),
                                rnd.choice((0.0, 0.0, rnd.uniform(-1, 1))))
    return "K %d %s %s %s %s" % (i, vec(pos[0], pos[1], pos[2], pp),
                                 vec(vel[0], vel[1], vel[2], vp),
                                 vec(*body), h(vmag))


def cam_line(rnd, k, pos, tgt, vpos, vtgt, fov):
    pads = [rnd.choice((0.0, 1.0, rnd.uniform(-1, 1))) for _ in range(4)]
    return "J %d %s %s %s %s %04x" % (
        k, vec(*(list(pos) + [pads[0]])), vec(*(list(tgt) + [pads[1]])),
        vec(*(list(vpos) + [pads[2]])), vec(*(list(vtgt) + [pads[3]])), fov)


def elev_line(rnd, ez, exact=False):
    ds = [-3.0, -1.5, -0.99, -0.5, 0.0, 0.3, 0.999, 1.5, 4.0, -20.0]
    n = rnd.randrange(3, 8)
    vals = [ez + rnd.choice(ds) + rnd.uniform(-0.05, 0.05) for _ in range(n)]
    if exact:
        # ground - 1 and ground + 1 on the eye itself, both bounds.
        vals += [f32(ez + 1.0), f32(ez - 1.0)]
    return "E %d %s" % (len(vals), vec(*vals))


def constrain_line(rnd, still=False):
    """The answers ConstrainToTopology's member cycles through; `still`
    ones never move the point, so the eye keeps its exact height."""
    n = rnd.randrange(2, 7)
    parts = []
    for _ in range(n):
        r = rnd.choice((0, 0, 0, 1, 2))
        d = ((0.0, 0.0, 0.0) if still or (r == 0 and rnd.random() < 0.8) else
             tuple(rnd.uniform(-1.5, 1.5) for _ in range(3)))
        parts.append("%d %s" % (r, vec(*d)))
    return "X %d %s" % (n, " ".join(parts))


def clocks(rnd):
    return "T %s %s" % (h(rnd.choice((0.0, 1 / 60.0, 1 / 30.0, 0.05,
                                      rnd.uniform(0.005, 0.1)))),
                        h(rnd.choice((1 / 60.0, 1 / 30.0, 1 / 30.0,
                                      rnd.uniform(0.005, 0.1)))))


def cams(n):
    out = []
    for k in range(n):
        out += ["C %d" % k, "V %d %d" % (k, k)]
    return out


UPRIGHT_EPS = (0.0, 0.0005, 0.0009, 0.0011, 0.002, -0.0005)


def setup(rnd, kind, j=0, k=0, car=0, eps=None):
    """A car of `kind` and camera `k` behind it, the lists the topology
    answers from, the saved mover's answer: the lines before "O". An
    upright car is `eps` short of straight up, else a random one of
    UPRIGHT_EPS."""
    centre = [rnd.uniform(-800, 800), rnd.uniform(-800, 800),
              rnd.uniform(-20, 80)]
    head = rnd.uniform(-math.pi, math.pi)
    fwd = (math.cos(head), math.sin(head))
    pads = None
    if kind == "moving":
        sp = rnd.uniform(3, 60)
        vel = [fwd[0] * sp, fwd[1] * sp, rnd.uniform(-3, 3)]
        body = rot_rows(rnd)
        vmag = rnd.choice((math.sqrt(sum(v * v for v in vel)),
                           rnd.uniform(0.011, 80)))
    elif kind == "stopped":
        vel = [rnd.uniform(-0.005, 0.005) for _ in range(3)]
        body = rot_rows(rnd)
        vmag = rnd.choice((0.0, 0.004, 0.01))
    elif kind == "upright":
        vel = [0.0, 0.0, rnd.uniform(-0.005, 0.005)]
        body = upright_rows(rnd, rnd.choice(UPRIGHT_EPS) if eps is None
                            else eps)
        vmag = rnd.choice((0.0, 0.01))
    else:                              # "flat": exact heights
        centre[2] = float(rnd.randrange(-10, 40))
        sp = rnd.uniform(3, 40)
        vel = [fwd[0] * sp, fwd[1] * sp, 0.0]
        body = rot_rows(rnd)
        vmag = sp
        pads = (1.0, 0.0)
    out = [car_line(rnd, car, centre, vel, body, vmag, pads)]
    back = rnd.uniform(4, 12)
    side = rnd.uniform(-4, 4)
    pos = [centre[0] - fwd[0] * back - fwd[1] * side,
           centre[1] - fwd[1] * back + fwd[0] * side,
           centre[2] + rnd.uniform(0.5, 4)]
    tgt = [centre[0] + rnd.uniform(-1, 1), centre[1] + rnd.uniform(-1, 1),
           centre[2] + rnd.uniform(0, 2)]
    r = rnd.random()
    if r < 0.15:
        vpos = list(vel)               # no speed against the car
    else:
        vpos = [v + rnd.uniform(-4, 4) for v in vel]
    vtgt = [v + rnd.uniform(-2, 2) for v in vel]
    out.append(cam_line(rnd, k, pos, tgt, vpos, vtgt,
                        rnd.randrange(0x0a00, 0x3000)))
    ez = centre[2] + 2.0
    out += [elev_line(rnd, ez, kind == "flat"),
            constrain_line(rnd, kind == "flat"),
            "S %d" % rnd.choice((0, 1, 1))]
    return out


def updates(rnd, j, frames, poke=True):
    out = []
    for i in range(frames):
        k = rnd.random()
        if k < 0.06:
            out.append(clocks(rnd))
        elif k < 0.09:
            out.append("Q %d" % rnd.choice((-1, 0, 6, 6, 5)))
        elif k < 0.11:
            out.append("Y %d" % rnd.choice((0, 1)))
        elif k < 0.13:
            out.append("Z %d" % rnd.choice((0, 0, 1)))
        elif k < 0.15 and poke:
            out.append("F %d fv %s" % (j, h(rnd.choice((1.0, 0.5,
                                                        rnd.uniform(0.2,
                                                                    1.6))))))
        elif k < 0.16:
            out.append(elev_line(rnd, rnd.uniform(-20, 80)))
        elif k < 0.17:
            out.append(constrain_line(rnd))
        out.append("U %d" % j)
    return out


def s_freeze(rnd, kind, frames=110):
    """A freeze from start to end: the constructor over a car of `kind`,
    the vtable's other slots, then Update through the blend in, the swing
    and the blend out and a little past, with the clocks, the pause, the
    sound, the stopped camera and the focus pull changing on the way."""
    out = cams(2)
    pn = rnd.choice(((0, 1), (1, 0)))
    out += ["L 0 %d" % pn[0], "L 1 %d" % pn[1]]
    view = rnd.randrange(2)
    out += setup(rnd, kind, 0, view, 0)
    out.append(clocks(rnd))
    if rnd.random() < 0.3:
        out += ["M %d %08x %d" % (view, rnd.getrandbits(32),
                                  rnd.choice((0, 1))),
                "Z %d" % rnd.choice((0, 1))]
    out += ["O 0 %d 0" % view, "Z 0", "R 0 %d" % rnd.randrange(2), "G 0",
            "P %d" % view]
    out += updates(rnd, 0, frames)
    out += ["Q -1", "Z 0", "G 0", "D 0"]
    return out


def ft_before(target, rte):
    """The fTime that one step of `rte` takes to exactly `target`."""
    old = f32(f32(target) - rte)
    assert f32(old + rte) == f32(target)
    return old


def s_edges(rnd):
    """The bounds: an Update landing on 0.4, on 2.4 and on 3, one from 2.4
    itself, the focus pull away from 1 as the blend out starts, and steps
    over the end."""
    out = cams(1) + ["L 0 1", "L 1 0"]
    for target, poke in ((0.4, False), (2.4, True), (2.4, False),
                         (3.0, True)):
        out += setup(rnd, rnd.choice(("moving", "flat")), 0, 0, 0)
        out += ["T %s %s" % (h(1 / 30.0), h(0.0625)), "O 0 0 0", "R 0 0"]
        out += ["U 0", "U 0"]
        if poke:
            out.append("F 0 fv %s" % h(rnd.uniform(0.3, 0.9)))
        out += ["F 0 ft %s" % h(ft_before(target, 0.0625)), "U 0", "U 0",
                "U 0"]
        out += ["F 0 ft %s" % h(target), "U 0", "U 0"]
        if poke:
            out.append("F 0 fv %s" % h(rnd.uniform(1.1, 1.5)))
        out += ["F 0 ft %s" % h(2.3999), "U 0", "U 0"]
        out += ["T %s %s" % (h(1 / 30.0), h(0.5)), "U 0", "U 0", "D 0"]
    return out


def s_two(rnd):
    """Two freezes at once on the two views, updated in turn, destroyed in
    the other order."""
    out = cams(2) + ["L 0 0", "L 1 1"]
    out += setup(rnd, "moving", 0, 0, 0)
    out += ["O 0 0 0", "R 0 0"]
    out += setup(rnd, "stopped", 1, 1, 1)
    out += ["O 1 1 1", "R 1 1", "G 1"]
    for i in range(100):
        if i % 17 == 3:
            out.append(clocks(rnd))
        out += ["U %d" % (i & 1)]
    out += ["D 0", "U 1", "D 1"]
    return out


def s_ctor(rnd):
    """Construction on its own, many times: the three ways to the heading,
    the camera in and out of the car, render flags and a stopped camera,
    straight to the destructor."""
    out = cams(2) + ["L 0 0", "L 1 1"]
    for i in range(24):
        kind = ("moving", "stopped", "upright", "flat")[i % 4]
        view = i % 2
        out += setup(rnd, kind, 0, view, i % 2,
                     UPRIGHT_EPS[i // 4 % len(UPRIGHT_EPS)])
        out += [clocks(rnd),
                "M %d %08x %d" % (view, rnd.getrandbits(32),
                                  rnd.choice((0, 1, 2))),
                "Z %d" % (i % 3 == 2), "O 0 %d %d" % (view, i % 2), "Z 0",
                "P %d" % view, "R 0 %d" % (i % 2), "D 0"]
    return out


def s_spline(rnd):
    """Spline on its own: the allocating constructor and AddControlPoint
    growing the buffer, from its own block and from an array it does not
    own, then GetPoint and GetDerivative at points before, inside and
    after, and the destructor."""
    out = []
    for i in range(NEYE):
        out.append("A e %d %s" % (i, vec(*(rnd.uniform(-100, 100)
                                            for _ in range(4)))))
    for i in range(NFOV):
        out.append("A f %d %s" % (i, vec(*(rnd.uniform(-10, 10)
                                            for _ in range(4)))))
    for typ in (0, 1, 2):
        for buf, k in ((1, 5), (2, 9), (3, 3), (4, 13), (100, 32), (7, 40)):
            if typ == 2 and k < 2:
                continue
            ts = [-1.5, -1e-7, 0.0, 0.3, 1.0, k - 1.5, k - 1.0, k - 0.5,
                  float(k), k + 0.7] + [rnd.uniform(-2, k + 2)
                                        for _ in range(3)]
            out.append("a %d %d %d %s" % (typ, buf, k, vec(*ts)))
        for cnt, k in ((2, 0), (3, 0), (5, 0), (8, 0), (1, 4), (4, 1),
                       (4, 9), (8, 20)):
            ts = [-1.5, -0.5, -1e-7, 0.0, 0.25, 0.999, 1.0,
                  cnt + k - 1.5, cnt + k - 1.0, float(cnt + k),
                  cnt + k + 0.75] + [rnd.uniform(-3, cnt + k + 3)
                                     for _ in range(4)]
            out.append("n %d %d %d %s" % (typ, cnt, k, vec(*ts)))
    return out


def script():
    rnd = random.Random(0x20ef4e2e)
    sc = [s_spline(rnd), s_ctor(rnd), s_edges(rnd), s_two(rnd)]
    for kind in ("moving", "stopped", "upright", "flat", "moving",
                 "moving", "stopped", "flat"):
        sc.append(s_freeze(rnd, kind))
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
        e.stub(BMALLOC, self.s_malloc)
        e.stub(TOPO_CTOR, self.s_topo_init)
        e.stub(TOPO_DTOR, self.s_topo_destroy)
        e.stub(SET_BBOX3, self.s_bbox)
        e.stub(GET_ELEV, self.s_elev)
        e.stub(CONSTRAIN, self.s_constrain)
        e.stub(BLUR_OFF, self.s_blur_off)
        e.stub(BLUR_ALPHA, self.s_blur_alpha)
        e.stub(ZONE_SOUND, self.s_zone_sound)
        e.stub(EXT_FN, lambda em: self.ext)
        e.put32(JOLLY, 0)
        e.call(EMATH_SINIT)
        e.call(BMATRIX_SINIT)
        assert e.u32(ZF_VTBL + SLOTS["update"]) == ZF_UPDATE
        assert e.u32(ZF_VTBL + SLOTS["destroy"]) == ZF_DTOR
        self.names = {0: "null", BASE_VTBL: "base", ZF_VTBL: "zone",
                      FOVT: "fovt", EYEV: "eyev", SPL: "spl",
                      SAVED: "saved"}
        for k in range(NCAM):
            c = cam_at(k)
            self.names[c] = "c%d" % k
            self.names[c + 96] = "c%d.tgt" % k
        for j in range(NMOV):
            self.names[mov_at(j)] = "o%d" % j
            self.names[mov_at(j) + M_TC] = "o%d.tc" % j
        for i in range(NCAR):
            self.names[car_at(i)] = "k%d" % i
        for i in range(NPL):
            self.names[pl_at(i)] = "p%d" % i
        for i in range(NVIEWS):
            self.names[view_at(i)] = "v%d" % i
            self.names[view_at(i) + V_LIST] = "v%d.list" % i
        self.blocks = {}

    def emit(self, s):
        self.out.append(s)

    def name(self, a):
        a &= M32
        if a in self.blocks:
            return self.blocks[a]
        return self.names.get(a, "?%08x" % a)

    def fill(self, a, n):
        self.e.write(a, bytes([PATTERN]) * n)

    def w(self, a):
        return self.e.u32(a)

    def put_words(self, a, t):
        for i, x in enumerate(t):
            self.e.put32(a + 4 * i, int(x, 16))

    def cstr(self, a):
        s = bytearray()
        while self.e.mem[a] and len(s) < 200:
            s.append(self.e.mem[a])
            a += 1
        return s.decode("latin-1")

    def reset(self):
        e = self.e
        self.fill(CAMS, CAM_SIZE * NCAM)
        self.fill(MOVS, MOV_STRIDE * NMOV)
        self.fill(CARS, CAR_STRIDE * NCAR)
        self.fill(PLAYERS, PL_STRIDE * NPL)
        self.fill(SAVED, 64)
        e.write(SVTBL, e.read(BASE_VTBL, 128))
        e.put32(SVTBL + SLOTS["ext"], EXT_FN)
        e.put32(SAVED + 40, SVTBL)
        self.fill(SPL, 48)
        self.fill(FOVT, 16 * NFOV)
        self.fill(EYEV, 16 * NEYE)
        self.fill(ARENA, ARENA_SIZE)
        for i in range(NVIEWS):
            v = view_at(i)
            e.put32(v + V_CAMERA, 0)
            e.put32(v + V_LIST, v + V_LIST)
            e.put32(v + V_LIST + 4, v + V_LIST)
        e.put32(G_STOP, 0)
        e.put32(G_WTE, fb(1.0 / 30.0))
        e.put32(G_RTE, fb(1.0 / 30.0))
        e.put32(G_RC, 0)
        e.put32(G_SOUND, 1)
        self.heap = ARENA
        self.blocks = {}
        self.ext = 1
        self.elevs, self.ne = [0], 0
        self.cons, self.nc = [(0, 0, 0, 0)], 0

    # ---- the stubs -------------------------------------------------------

    def s_malloc(self, em):
        size, line, align = s32(em.reg[4]), s32(em.reg[6]), s32(em.reg[7])
        p = (self.heap + 15) & ~15
        self.heap = p + size
        tag = "m%d" % len(self.blocks)
        self.blocks[p] = tag
        self.emit("  malloc %d %s %d %d -> %s"
                  % (size, self.cstr(em.reg[5] & M32), line, align, tag))
        return p

    def s_free(self, em):
        self.emit("  free %s" % self.name(em.reg[4]))

    def s_topo_init(self, em):
        self.emit("  topo init %s" % self.name(em.reg[4]))
        return em.reg[4]

    def s_topo_destroy(self, em):
        self.emit("  topo destroy %s" % self.name(em.reg[4]))

    def s_bbox(self, em):
        vel = em.reg[6] & M32
        self.emit("  bbox %s pos %s r %s vel %s"
                  % (self.name(em.reg[4]), self.vec3(em.reg[5] & M32),
                     fx(em.fpr[12]),
                     self.vec3(vel) if vel else "null"))

    def s_elev(self, em):
        args = "".join("1" if em.reg[r] & M32 else "0" for r in (6, 7, 8))
        v = self.elevs[self.ne % len(self.elevs)]
        self.ne += 1
        self.emit("  elev %s pt %s args %s -> %s"
                  % (self.name(em.reg[4]), self.vec3(em.reg[5] & M32), args,
                     fx(v)))
        em.fpr[0] = v

    def s_constrain(self, em):
        to = em.reg[8] & M32
        r, dx, dy, dz = self.cons[self.nc % len(self.cons)]
        self.nc += 1
        self.emit("  constrain %s type %d two %d from %s to %s dist %s"
                  " lift %s -> %d"
                  % (self.name(em.reg[4]), s32(em.reg[5]), s32(em.reg[6]),
                     self.vec3(em.reg[7] & M32), self.vec3(to),
                     fx(em.fpr[12]), fx(em.fpr[13]), r))
        for i, d in enumerate((dx, dy, dz)):
            a = to + 4 * i
            self.e.put32(a, f_to_bits(f32(bits_f(self.w(a)) + bits_f(d))))
        return r

    def s_blur_off(self, em):
        self.emit("  blur off %d" % s32(em.reg[4]))

    def s_blur_alpha(self, em):
        self.emit("  blur alpha %d %s %s"
                  % (s32(em.reg[4]), fx(em.fpr[12]), fx(em.fpr[13])))

    def s_zone_sound(self, em):
        self.emit("  zsound %s %s %s %04x %s"
                  % (self.name(em.reg[4]), fx(em.fpr[12]), fx(em.fpr[13]),
                     em.reg[5] & 0xffff, fx(em.fpr[14])))

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

    def dump_spline(self, tag, a):
        w = self.w
        self.emit("    %s %08x %08x %08x %s %s %08x %08x %08x %s %s %08x %s"
                  % (tag, w(a), w(a + 4), w(a + 8), self.name(w(a + 12)),
                     self.name(w(a + 16)), w(a + 20), w(a + 24), w(a + 28),
                     fx(w(a + 32)), fx(w(a + 36)), w(a + 40),
                     self.name(w(a + 44))))
        p, n = w(a + 12), s32(w(a + 4))
        if (p in self.blocks or p == EYEV) and 0 < n <= 256:
            for i in range(n):
                self.emit("    %s %d %s" % (tag, i, self.vec4(p + 16 * i)))

    def dump_cubic(self, tag, c):
        w, u16 = self.w, self.e.u16
        self.emit("    %s %s st %04x fl %04x"
                  % (tag, " ".join(fx(w(c + 4 * i)) for i in range(11)),
                     u16(c + 44), u16(c + 46)))

    def dump_mov(self, j, full):
        m = mov_at(j)
        w = self.w
        self.emit("  o%d type %d view %d en %d pview %s pcam %s player %s"
                  " carnot %08x dash %08x vtbl %s next %s prev %s"
                  % (j, s32(w(m + 8)), s32(w(m + 12)), s32(w(m + 16)),
                     self.name(w(m + 20)), self.name(w(m + 24)),
                     self.name(w(m + 28)), w(m + 32), w(m + 36),
                     self.name(w(m + 40)), self.name(w(m)),
                     self.name(w(m + 4))))
        self.emit("    ft %s tan %s ei %s eo %s li %s lo %s fp %s"
                  % ((fx(w(m + 44)), fx(w(m + 48)))
                     + tuple(self.name(w(m + o))
                             for o in (52, 56, 60, 64, 68))))
        for tag, off in (("ei", 52), ("eo", 56), ("li", 60), ("lo", 64)):
            b = w(m + off)
            if b in self.blocks:
                for lane, lo in (("x", 0), ("y", 48), ("z", 96)):
                    self.dump_cubic(tag + lane, b + lo)
        b = w(m + 68)
        if b in self.blocks:
            self.dump_cubic("fp", b)
        if full:
            self.dump_spline("eye", m + 72)
            self.dump_spline("look", m + 120)

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

    def call(self, fn, *args, **f):
        e = self.e
        for i, v in f.items():
            e.fpr[int(i[1:])] = v & M32
        return e.call(fn, *args, limit=4000000)

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

    def spline_op(self, t, alloc):
        typ, cnt, k = int(t[1]), int(t[2]), int(t[3])
        self.fill(SPL, 48)
        if alloc:
            self.call(SPL_ALLOC, SPL, typ, cnt, 16384)
        else:
            self.call(SPL_CTOR, SPL, typ, cnt, EYEV, 16384)
        for i in range(k):
            self.call(SPL_ADD, SPL, FOVT + 16 * (i % NFOV))
        self.dump_spline("spl", SPL)
        for x in t[4:]:
            tt = int(x, 16)
            self.fill(OUTV, 16)
            self.call(SPL_GETPT, SPL, OUTV, f12=tt)
            p = self.vec4(OUTV)
            self.fill(OUTV, 16)
            self.call(SPL_DERIV, SPL, OUTV, f12=tt)
            self.emit("  at %s p %s d %s" % (fx(tt), p, self.vec4(OUTV)))
        self.call(SPL_DTOR, SPL, 2)
        self.emit("  destroyed")

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
        elif c == "J":
            a = cam_at(int(t[1]))
            self.put_words(a + 64, t[2:6])
            self.put_words(a + 96, t[6:10])
            self.put_words(a + 352, t[10:14])
            self.put_words(a + 384, t[14:18])
            v = int(t[18], 16)
            e.mem[a + 132] = v & 0xff
            e.mem[a + 133] = v >> 8
        elif c == "M":
            a = cam_at(int(t[1]))
            e.put32(a + 444, int(t[2], 16))
            e.put32(a + 448, int(t[3]))
        elif c == "P":
            self.dump_cam(cam_at(int(t[1])))
        elif c == "K":
            a = car_at(int(t[1]))
            self.put_words(a + C_POS, t[2:6])
            self.put_words(a + C_VEL, t[6:10])
            self.put_words(a + C_BODY, t[10:26])
            e.put32(a + C_VMAG, int(t[26], 16))
        elif c == "L":
            e.put32(pl_at(int(t[1])) + P_NUMBER, int(t[2]))
        elif c == "S":
            self.ext = int(t[1])
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
        elif c == "Y":
            e.put32(G_SOUND, int(t[1]))
        elif c == "E":
            n = int(t[1])
            self.elevs = [int(x, 16) for x in t[2:2 + n]]
            self.ne = 0
        elif c == "X":
            n = int(t[1])
            self.cons = []
            for i in range(n):
                q = t[2 + 4 * i:6 + 4 * i]
                self.cons.append((int(q[0]), int(q[1], 16), int(q[2], 16),
                                  int(q[3], 16)))
            self.nc = 0
        elif c == "O":
            j, view, car = (int(x) for x in t[1:4])
            self.fill(mov_at(j), MOV_STRIDE)
            self.call(ZF_CTOR, mov_at(j), view, car_at(car), SAVED)
            self.dump_mov(j, True)
            self.dump_views()
            self.dump_cam(self.w(mov_at(j) + 24))
        elif c == "R":
            e.put32(mov_at(int(t[1])) + 28, pl_at(int(t[2])))
        elif c == "U":
            j = int(t[1])
            self.vcall(j, SLOTS["update"])
            self.dump_mov(j, False)
            self.dump_cam(self.w(mov_at(j) + 24))
        elif c == "D":
            j = int(t[1])
            cam = self.w(mov_at(j) + 24)
            self.vcall(j, SLOTS["destroy"], 0)
            self.dump_mov(j, False)
            self.dump_views()
            self.dump_cam(cam)
        elif c == "F":
            m = mov_at(int(t[1]))
            if t[2] == "ft":
                e.put32(m + 44, int(t[3], 16))
            else:
                e.put32(self.w(m + 68), int(t[3], 16))
        elif c == "G":
            self.query(int(t[1]))
        elif c == "A":
            self.put_words(ARRAYS[t[1]] + 16 * int(t[2]), t[3:7])
        elif c == "a":
            self.spline_op(t, True)
        elif c == "n":
            self.spline_op(t, False)
        else:
            raise SystemExit("bad op %r" % (t,))

    def run(self, scenarios):
        for i, sc in enumerate(scenarios):
            self.emit("B %d" % i)
            self.reset()
            for ln in sc:
                if ln[0] not in "AEJKX":
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


def build_harness(tmp, name="zonecam_test"):
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


def M(name, before, after, rel=ZCC):
    return (name, rel, before, after)


MUTATIONS = [
    # The vtable, the type and ConstrainToTopology.
    M("type", "viewID, CM_STILL);", "viewID, CM_ZONE_FREEZE);"),
    M("vt-car", "    (void)m;" + NL + "    return NULL;", "    return m;"),
    M("c-ways", "if (ways == 1) {", "if (ways == 0) {"),
    M("c-sides", "int twoSided = sides == 1;", "int twoSided = 1;"),
    M("c-gap", "#define ZONE_WALL_GAP        0.7f",
      "#define ZONE_WALL_GAP        0.75f"),
    M("c-back", "TOPOLOGY_CONSTRAIN_BY_ROTATION, twoSided," + NL
      + "                                to, from,",
      "TOPOLOGY_CONSTRAIN_BY_ROTATION, twoSided," + NL
      + "                                from, to,"),
    M("e-box", "topology_set_interest_bbox3(tc, eye, 10.0f, NULL);",
      "topology_set_interest_bbox3(tc, eye, 8.0f, NULL);"),
    M("e-lo", "if (ground - clearance < eye->z",
      "if (ground - clearance <= eye->z"),
    M("e-hi", "eye->z < ground + clearance)", "eye->z <= ground + clearance)"),
    M("e-set", "eye->z = ground + clearance;", "eye->z = ground - clearance;"),

    # The constructor: the frame.
    M("cross-order", "cross3(&frame.v1, &frame.v2, &frame.v0);",
      "cross3(&frame.v1, &frame.v0, &frame.v2);"),
    M("moving", "if (ZF_MOVING < car->State.VelocityMagnitude)",
      "if (ZF_MOVING <= car->State.VelocityMagnitude)"),
    M("upright-sign", "heading.x = -car->State.BodyMatrix.v2.x;",
      "heading.x = car->State.BodyMatrix.v2.x;"),
    M("upright-test", "BodyMatrix.v0.z) <= ZF_UPRIGHT",
      "BodyMatrix.v0.z) <= 0.0015f"),
    M("nose", "heading.y = car->State.BodyMatrix.v0.y;",
      "heading.y = car->State.BodyMatrix.v1.y;"),
    M("v3-wte", "frame.v3.x = car->State.Velocity.x * WorldTimeElapsed",
      "frame.v3.x = car->State.Velocity.x * RealTimeElapsed"),
    M("v3-w", "frame.v3.w = car->State.Velocity.pad * WorldTimeElapsed",
      "frame.v3.w = 1.0f + 0.0f * WorldTimeElapsed"),
    M("eye-wte", "scale_add(&eye, &cam->VelocityKey.Position, WorldTimeElapsed,",
      "scale_add(&eye, &cam->VelocityKey.Position, RealTimeElapsed,"),
    M("look-from", "WorldTimeElapsed," + NL
      + "              &cam->CurrentKey.Target);",
      "WorldTimeElapsed," + NL
      + "              &cam->CurrentKey.Position);"),

    # The constructor: where the swing starts and which way it goes.
    M("sign", "? 1.0f : -1.0f;" + NL + "    scale(&local",
      "? -1.0f : 1.0f;" + NL + "    scale(&local"),
    M("local-sign", "scale(&local, &local, sign);", "(void)0;"),
    M("rel-w", "rel4.w = 0.0f;", "rel4.w = 1.0f;"),
    M("d-ge", "(0.0f <= d ? 1.0f : -1.0f)", "(0.0f < d ? 1.0f : -1.0f)"),
    M("lead", "+ dir * ZF_LEAD;", "- dir * ZF_LEAD;"),
    M("atan-args", "bATan(local.x, local.y)", "bATan(local.y, local.x)"),
    M("sweep", "(float)i * ZF_STEP * dir * ZF_SWEEP;",
      "(float)i * ZF_STEP * ZF_SWEEP;"),

    # The constructor: the points.
    M("look-r", "pt.x = c * ZF_LOOK_RADIUS;", "pt.x = s * ZF_LOOK_RADIUS;"),
    M("look-h", "pt.z = ZF_LOOK_HEIGHT;", "pt.z = ZF_EYE_HEIGHT;"),
    M("eye-h", "pt.z = ZF_EYE_HEIGHT;", "pt.z = ZF_LOOK_HEIGHT;"),
    M("pt-pad", "pt.pad = 0.0f;", "pt.pad = 1.0f;"),
    M("box", "topology_set_interest_bbox3(&m->Topology, &at, ZF_LOOK_BOX,",
      "topology_set_interest_bbox3(&m->Topology, &from, ZF_LOOK_BOX,"),
    M("c-call", "zone_constrain_to_topology(&m->Topology, &at, &from, 1, 1);",
      "zone_constrain_to_topology(&m->Topology, &at, &from, 0, 1);"),
    M("ensure-arg", "zone_ensure_eye_above_ground(&m->Topology, &from, 1.0f);",
      "zone_ensure_eye_above_ground(&m->Topology, &from, 2.0f);"),
    M("add-look", "spline_add_control_point(&m->LookSpline, &at);",
      "spline_add_control_point(&m->LookSpline, &from);"),

    # The constructor: the blends.
    M("in-dv", "sub(&dv, &cam->VelocityKey.Position, &car->State.Velocity);",
      "sub(&dv, &cam->VelocityKey.Target, &car->State.Velocity);"),
    M("in-tan", "scale(&dp, &dp, last * 0.5f * ZF_TANGENT);" + NL
      + "    scale(&dv, &dv, ZF_BLEND_IN);" + NL + "    m->pEyeBlendIn",
      "scale(&dp, &dp, last * ZF_TANGENT);" + NL
      + "    scale(&dv, &dv, ZF_BLEND_IN);" + NL + "    m->pEyeBlendIn"),
    M("in-dur", "new_blend(ZF_BLEND_IN, 573)", "new_blend(ZF_BLEND_OUT, 573)"),
    M("line", "new_blend(ZF_BLEND_IN, 590)", "new_blend(ZF_BLEND_IN, 591)"),
    M("in-desired", "bspline3d_set_val_desired(m->pEyeBlendIn, &p);",
      "bspline3d_set_val_desired(m->pEyeBlendIn, &eye);"),
    M("out-last", "last = spline_last(&m->EyeSpline);" + NL
      + "    spline_get_point(&m->EyeSpline, &p, last);",
      "last = spline_last(&m->EyeSpline);" + NL
      + "    spline_get_point(&m->EyeSpline, &p, 0.0f);"),
    M("out-dv", "scale(&dv, &cam->VelocityKey.Position, ZF_BLEND_OUT);",
      "scale(&dv, &cam->VelocityKey.Position, ZF_BLEND_IN);"),
    M("out-val", "bspline3d_set_val(m->pLookBlendOut, &p);",
      "bspline3d_set_val(m->pLookBlendOut, &look);"),
    M("lout-dd", "bspline3d_set_dval_desired(m->pLookBlendOut, &dv);",
      "bspline3d_set_dval_desired(m->pLookBlendOut, &dp);"),
    M("blend-arr", "lane[i]->arrivalThreshold = 1.0f;",
      "lane[i]->arrivalThreshold = 0.9f;"),
    M("blend-flags", "lane[i]->flags = 0;", "lane[i]->flags = 1;"),
    M("focus-state", "m->pFocusPull->state = 2;", "m->pFocusPull->state = 0;"),
    M("focus-dur", "m->pFocusPull->duration = ZF_BLEND_IN;",
      "m->pFocusPull->duration = ZF_BLEND_OUT;"),
    M("focus-arr", "m->pFocusPull->arrivalThreshold = 1.0f;",
      "m->pFocusPull->arrivalThreshold = 0.5f;"),
    M("focus-flags", "m->pFocusPull->flags = 0;", "m->pFocusPull->flags = 1;"),
    M("tanfov", "m->fTanFov = bSinBam(fov) / bCosBam(fov);",
      "m->fTanFov = bCosBam(fov) / bSinBam(fov);"),
    M("render", "cam->RenderDash = 0;", "cam->RenderDash = 1;"),
    M("render-stop", "if (!CameraStopUpdating) {", "if (1) {"),

    # The destructor.
    M("dtor-blur", "gRadialBlurOffFn(zf_player(m)->PlayerNumber);",
      "gRadialBlurOffFn(0);"),
    M("dtor-order", "bFree(m->pEyeBlendOut);" + NL
      + "    bFree(m->pLookBlendIn);",
      "bFree(m->pLookBlendIn);" + NL + "    bFree(m->pEyeBlendOut);"),
    M("dtor-spl", "spline_destroy(&m->LookSpline, 2);" + NL
      + "    spline_destroy(&m->EyeSpline, 2);",
      "spline_destroy(&m->EyeSpline, 2);" + NL
      + "    spline_destroy(&m->LookSpline, 2);"),

    # Update.
    M("paused", "    if (is_game_flow_paused())" + NL + "        return;" + NL
      + "    old", "    old"),
    M("rte", "t = old + RealTimeElapsed;", "t = old + WorldTimeElapsed;"),
    M("in-gate", "if (t < ZF_BLEND_IN) {", "if (t <= ZF_BLEND_IN) {"),
    M("in-seek", "bspline3d_seek(m->pEyeBlendIn, RealTimeElapsed);",
      "bspline3d_seek(m->pEyeBlendIn, WorldTimeElapsed);"),
    M("in-look", "bspline3d_get_val(m->pLookBlendIn, &look);",
      "bspline3d_get_val(m->pLookBlendOut, &look);"),
    M("u-constrain", "zone_constrain_to_topology(&m->Topology, &look, &eye, 0, 0);"
      + NL + "        blur = m->fTime",
      "zone_constrain_to_topology(&m->Topology, &eye, &look, 0, 0);"
      + NL + "        blur = m->fTime"),
    M("blur-in", "blur = m->fTime * ZF_BLUR_IN_RATE;",
      "blur = old * ZF_BLUR_IN_RATE;"),
    M("blur-in-k", "zf_blur(m, blur * ZF_BLUR);" + NL + "    } else if",
      "zf_blur(m, blur);" + NL + "    } else if"),
    M("out-gate", "} else if (ZF_BLEND_OUT_AT < t) {",
      "} else if (ZF_BLEND_OUT_AT <= t) {"),
    M("focus-gate", "if (old <= ZF_BLEND_OUT_AT) {",
      "if (old < ZF_BLEND_OUT_AT) {"),
    M("focus-vd", "focus->valDesired = 1.0f;", "focus->valDesired = 0.5f;"),
    M("focus-dur2", "focus->duration = zone_freeze_camera_mover_duration() - m->fTime;",
      "focus->duration = zone_freeze_camera_mover_duration() - old;"),
    M("focus-ne", "if (focus->val != 1.0f)", "if (focus->val == 1.0f)"),
    M("out-seek", "bspline3d_seek(m->pLookBlendOut, RealTimeElapsed);",
      "bspline3d_seek(m->pLookBlendIn, RealTimeElapsed);"),
    M("blur-out", "* ZF_BLUR_OUT_RATE;", "* ZF_BLUR_IN_RATE;"),
    M("out-out", "out = 1.0f - blur;", "out = blur;"),
    M("mid-u", "float u = (t - ZF_BLEND_IN) * 0.5f;",
      "float u = (t - ZF_BLEND_IN) * 0.25f;"),
    M("mid-blur", "blur = 1.0f;" + NL + "    }", "blur = 0.5f;" + NL + "    }"),
    M("focus-seek", "bspline_seek(focus, RealTimeElapsed);",
      "bspline_seek(focus, WorldTimeElapsed);"),
    M("pull", "scale_add(&eye, &d, focus->val, &look);",
      "scale_add(&eye, &d, 1.0f, &look);"),
    M("fov", "fov = bATan(focus->val, m->fTanFov);",
      "fov = bATan(m->fTanFov, focus->val);"),
    M("fov-stop", "if (!CameraStopUpdating)" + NL
      + "        m->base.pCamera->CurrentKey.FieldOfView",
      "if (1)" + NL + "        m->base.pCamera->CurrentKey.FieldOfView"),
    M("up", "up.z = 1.0f;", "up.z = -1.0f;"),
    M("setmat", "camera_set_matrix(m->base.pCamera, &mat, RealTimeElapsed);",
      "camera_set_matrix(m->base.pCamera, &mat, WorldTimeElapsed);"),
    M("sound-gate", "if (SoundEnabled) {", "if (1) {"),
    M("az", "m->fTime / zone_freeze_camera_mover_duration() * 65536.0f);",
      "m->fTime / zone_freeze_camera_mover_duration() * 65535.0f);"),
    M("pitch-phase", "* ZF_DEG_TO_RAD + ZF_QUARTER_TURN;", "* ZF_DEG_TO_RAD;"),
    M("pitch", "bSinF(a) * 0.5f + 0.5f;", "bSinF(a) * 0.5f;"),
    M("muffle", "out + out, blur, az, pitch", "out, blur, az, pitch"),
    M("blur-from", "PlayerNumber, 0.0f, to);", "PlayerNumber, to, to);"),

    # Spline: the allocating constructor, AddControlPoint, GetDerivative.
    M("alloc-buf", "s->ControlPointBufferSize = bufSize;",
      "s->ControlPointBufferSize = bufSize + 1;", SPC),
    M("alloc-line", "SPLINE_CPP," + NL + "                                 37, 16);",
      "SPLINE_CPP," + NL + "                                 38, 16);", SPC),
    M("alloc-own", "    s->pControlPointArray = points;" + NL
      + "    s->pControlPoints = points;" + NL + "    return s;",
      "    s->pControlPointArray = NULL;" + NL
      + "    s->pControlPoints = points;" + NL + "    return s;", SPC),
    M("add-grow", "int32_t size = s->NumControlPoints * 2;",
      "int32_t size = s->NumControlPoints + 2;", SPC),
    M("add-copy", "(size_t)s->NumControlPoints * sizeof(bVector3));",
      "(size_t)(s->NumControlPoints - 1) * sizeof(bVector3));", SPC),
    M("add-free", "        if (s->pControlPointArray != NULL)" + NL
      + "            bFree(s->pControlPointArray);" + NL
      + "        s->pControlPointArray = points;",
      "        s->pControlPointArray = points;", SPC),
    M("der-floor", "    if (t < base)" + NL + "        base = base - 1.0f;" + NL
      + "    u = t - base;" + NL + "    u2 = u * u;" + NL
      + "    // In the image's order",
      "    if (t <= base)" + NL + "        base = base - 1.0f;" + NL
      + "    u = t - base;" + NL + "    u2 = u * u;" + NL
      + "    // In the image's order", SPC),
    M("der-c0", "c0 = ((u2 * -3.0f + u * 4.0f) - 1.0f) * 0.5f;",
      "c0 = ((u2 * -3.0f + u * 4.0f) + 1.0f) * 0.5f;", SPC),
    M("der-c1", "c1 = (u2 * 9.0f - u * 10.0f) * 0.5f;",
      "c1 = (u2 * 9.0f - u * 10.0f) * 0.25f;", SPC),
    M("der-c3", "c3 = (u2 * 3.0f - (u + u)) * 0.5f;",
      "c3 = (u2 * 3.0f - u) * 0.5f;", SPC),

    # tCubic3D.
    M("3d-dvd", "s->z.dvalDesired = v->z;" + NL + "}",
      "s->z.dvalDesired = v->y;" + NL + "}", BAC),
    M("3d-get", "out->z = s->z.val;", "out->z = s->z.dval;", BAC),
    M("3d-seek", "bspline_seek(&s->z, dt);", "bspline_seek(&s->y, dt);", BAC),
    M("3d-dval", "s->x.dval = v->x;" + NL
      + "    if (v->x != s->x.dvalDesired) s->x.state = 2;" + NL
      + "    s->y.dval = v->y;" + NL + "    if (v->y != s->y.dvalDesired)"
      + " s->y.state = 2;" + NL + "    s->z.dval = v->z;" + NL
      + "    if (v->z != s->z.dvalDesired) s->z.state = 2;" + NL + "}",
      "s->x.dval = v->y;" + NL
      + "    if (v->x != s->x.dvalDesired) s->x.state = 2;" + NL
      + "    s->y.dval = v->y;" + NL + "    if (v->y != s->y.dvalDesired)"
      + " s->y.state = 2;" + NL + "    s->z.dval = v->z;" + NL
      + "    if (v->z != s->z.dvalDesired) s->z.state = 2;" + NL + "}", BAC),
]

EQUIVALENT = {
    "pt-pad": "eMulVector3 multiplies the point with its w as 1, whatever "
              "the fourth lane holds; retail leaves a stack word there",
    "e-hi": "at eye z exactly ground + clearance the eye is set to "
            "ground + clearance, the height it already has",
    "der-floor": "at a whole t the end of one segment and the start of the "
                 "next weight the same two points by the same halves, the "
                 "other weights 0",
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
        todo, SOURCES, "zonecam_test",
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
