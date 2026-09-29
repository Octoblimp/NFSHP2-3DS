#!/usr/bin/env python3
"""Cross-check 3DS Files/source/shake.c, and player.c's IsCameraPOVInCar,
against the retail image itself, run in mipsemu.

The model is the image. Retail's tEnvelope (GetIndex 0x00155948, OutOfRange
0x001559a8, both GetSlopes 0x001559f0 and 0x00155a40, GetValue 0x00155aa0,
GetIntegral 0x00155b28), tShaker (the constructor 0x00156b10, GetAmplitude
0x001562b0, StartShaking 0x001562e8, Update 0x00156320, GetValue
0x00156370), the static initialiser's shake share (0x00156958),
ResetCameraShakers (0x00156480), UpdateCameraShakers (0x00156400),
GetShake (0x00156528), IsShakeActive (0x00156540), ApplyCameraShake
(0x00156560) with the matrix layer under it, MaybeCameraShake (0x001566c0)
with bNormalize, Car::MaybeCameraShake (0x001346b0) and
Player::IsCameraPOVInCar (0x00178808) run as shipped. The harness
(tools/src/shake_test.c) runs the port over the same script, and the two
transcripts are diffed.

Nothing is stubbed but a test vtable's GetCameraInfo and GetPOV, which
print their arguments and answer what the script set. The Players, the
movers, the POVs, the Car and the World are blobs at retail's offsets on
the model side and the port's structs on the harness side.

The scratch envelopes and shakers start from a byte pattern, so what a call
leaves alone shows. The players' shakers print three lanes: their fourth
is MaybeCameraShake's stack garbage in the image (see shake.c). A float
prints as its bits, a NaN as "nan".

    python tools/shake_check.py
    python tools/shake_check.py --mutate [--only a,b]
    python tools/shake_check.py --dump out/shake
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

HARNESS = "tools/src/shake_test.c"
SHKC = "3DS Files/source/shake.c"
PLYC = "3DS Files/source/player.c"
SOURCES = [HARNESS, SHKC, PLYC] + ["3DS Files/source/" + f for f in (
    "emath.c", "bmatrix.c", "bmath.c", "bmathtab.c", "bvector.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
ENV_INDEX = 0x00155948
ENV_OOR = 0x001559a8
ENV_SLOPE_AT = 0x001559f0
ENV_SLOPE = 0x00155a40
ENV_VALUE = 0x00155aa0
ENV_INTEGRAL = 0x00155b28
SH_CTOR = 0x00156b10
SH_AMP = 0x001562b0
SH_START = 0x001562e8
SH_UPDATE = 0x00156320
SH_VALUE = 0x00156370
UPDATE_SHAKERS = 0x00156400
RESET_SHAKERS = 0x00156480
GET_SHAKE = 0x00156528
IS_ACTIVE = 0x00156540
APPLY = 0x00156560
MAYBE = 0x001566c0
CAR_MAYBE = 0x001346b0
INCAR = 0x00178808
SINIT = 0x00156958
EMATH_SINIT = 0x0011bf70

CAMERA_SHAKERS = 0x002fa820
SHAKE_TEST = 0x002fa6e0
AMP_POINTS = 0x002fa7a0
ACCEL_BIAS = 0x00334080
ROTATION = 0x00334090
COEFFS = 0x002b13f0
G_ENVELOPE = GP - 21848           # ShakeAmplitudeEnvelope
G_TEST = GP - 21912               # bShakeTest
G_WORLD = GP - 22120              # pCurrentWorld
G_ELAPSED = GP - 19560            # WorldTimeElapsed
G_BYNUMBER = GP - 20936           # PlayerPlayersByNumber

ENVS = 0x01000000
PTS = 0x01001000
PTS_STRIDE = 0x100
NENV = 8
NPTS = 17
XS = 0x01002000
NXS = 4
WORLD = 0x01003000
W_SCALE = 388
PLAYERS = 0x01004000
PLAYER_STRIDE = 0x400
P_NUMBER = 16
P_POV = 36
P_ZONE = 88
P_MOVER = 200
MOVS = 0x01006000
MOV_STRIDE = 0x40
M_TYPE = 8
M_ENABLED = 16
M_VTBL = 40
TEST_VTBL = 0x01007000
POVS = 0x01008000
NPOV = 4
CAMERA_INFO = 0x01008800
CAR = 0x01009000
C_PLAYER = 24
C_ACCEL = 128
MATRIX = 0x0100a000
VEC = 0x0100b000
OUT = 0x0100b100
STUB_INFO = 0x0100c000
STUB_POV = 0x0100c008

PATTERN = 0xa5
NAN = 0x7fc00000


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


def shaker_at(name):
    i = int(name[1:])
    if name[0] == "x":
        return XS + 32 * i, True
    return CAMERA_SHAKERS + 32 * i, False


# ============================================================ the scenarios


def rtime(rnd, env):
    """A time to ask an envelope at: one of its points, between two, past
    either end, or an odd one."""
    k = rnd.random()
    ts = [t for t, _ in env[:-1]]
    if ts and k < 0.25:
        return fb(rnd.choice(ts))
    if len(ts) > 1 and k < 0.6:
        a, b = rnd.sample(ts, 2)
        return fb(a + (b - a) * rnd.random())
    if k < 0.85:
        return fb(rnd.uniform(-0.5, 2.5))
    return rnd.choice((NAN, 0x7f800000, 0xff800000, 0x80000000, 0,
                       fb(1.0), fb(-1.0), fb(1e30)))


def renv(rnd, n, sorted_=True):
    """n points and a sentinel after them, which only GetIntegral reads."""
    if sorted_:
        ts = sorted(rnd.uniform(0, 2) for _ in range(n))
        if n and rnd.random() < 0.3:
            ts[0] = 0.0
    else:
        ts = [rnd.uniform(-1, 2) for _ in range(n)]
    pts = [(t, rnd.uniform(-1, 2)) for t in ts]
    pts.append((rnd.uniform(0, 3), rnd.uniform(-1, 2)))
    return pts


def env_line(k, env):
    return "E %d %d %s" % (k, len(env) - 1, " ".join(
        "%08x %08x" % (fb(t), fb(v)) for t, v in env))


def s_envelopes(rnd):
    out = []
    shipped = [(0.0, 1.0), (0.1, 0.7), (0.3, 0.5), (0.5, 0.4), (1.0, 0.0),
               (5.0, 9.0)]
    envs = [shipped] + [renv(rnd, n) for n in (1, 2, 3, 5, 8, 16)] + \
        [renv(rnd, 6, sorted_=False)]
    for k, env in enumerate(envs):
        out.append(env_line(k, env))
    for step in range(900):
        k = rnd.randrange(len(envs))
        env = envs[k]
        r = rnd.random()
        if r < 0.15:
            out.append("I %d %08x" % (k, rtime(rnd, env)))
        elif r < 0.3:
            out.append("O %d %08x" % (k, rtime(rnd, env)))
        elif r < 0.42:
            out.append("s %d %d" % (k, rnd.randrange(-2, len(env) + 1)))
        elif r < 0.55:
            out.append("S %d %08x" % (k, rtime(rnd, env)))
        elif r < 0.75:
            out.append("V %d %08x" % (k, rtime(rnd, env)))
        else:
            out.append("G %d %08x %08x" % (k, rtime(rnd, env),
                                           rtime(rnd, env)))
    # Out of order, with a point past the last one's time: only here does
    # clamping b to the last point change the sum, since in order the loop
    # reaches the last point first either way.
    out.append(env_line(7, [(0.0, 1.0), (2.0, 1.0), (1.0, 1.0), (3.0, 0.0)]))
    for a, b in ((0.5, 1.5), (1.5, 0.5), (0.0, 2.5), (0.25, 1.0)):
        out.append("G 7 %08x %08x" % (fb(a), fb(b)))
    # No points: GetIndex and GetSlope(i) read none.
    out.append("E 7 0 %08x %08x" % (fb(0.5), fb(0.25)))
    for t in (0.0, -1.0, 1.0):
        out.append("I 7 %08x" % fb(t))
    for i in (-1, 0, 1):
        out.append("s 7 %d" % i)
    return out


DTS = (1.0 / 60, 1.0 / 30, 0.1, 0.25, 0.5, 1.0, 0.0, -0.05, 3.0)


def rvec(rnd, scale=1.0):
    return [fb(rnd.uniform(-scale, scale)) for _ in range(4)]


def s_shakers(rnd):
    out = [env_line(1, renv(rnd, 4)), env_line(2, renv(rnd, 3))]
    names = ["x%d" % j for j in range(NXS)]
    for n in names:
        out.append("hi %s" % n)
    for step in range(700):
        n = rnd.choice(names)
        r = rnd.random()
        if r < 0.15:
            v = rvec(rnd, rnd.choice((0.1, 1.0, 100.0)))
            d = fb(rnd.choice((0.3, 0.6, 0.7, 1.2, 2.0, 0.05)))
            f = fb(rnd.choice((17.0, 17.0, 5.0, 0.5, 31.5)))
            out.append("hs %s %s %08x %08x" % (
                n, " ".join("%08x" % w for w in v), d, f))
        elif r < 0.45:
            out.append("hu %s %08x" % (n, fb(rnd.choice(DTS))))
        elif r < 0.65:
            out.append("hv %s" % n)
        elif r < 0.75:
            out.append("ha %s" % n)
        elif r < 0.8:
            out.append("hi %s" % n)
        elif r < 0.86:
            out.append("hf %s amp %d" % (n, rnd.choice((-1, -2, 1, 2))))
        elif r < 0.92:
            v = rnd.choice((fb(rnd.uniform(0, 1)), fb(rnd.uniform(-1, 3)),
                            fb(1e10), fb(-1e10), NAN, 0x80000000,
                            fb(0.5 / 17), fb(1.0 / 17)))
            out.append("hf %s time %08x" % (n, v))
        elif r < 0.96:
            v = rnd.choice((fb(17.0), fb(3.0), fb(1e9), fb(-17.0), 0))
            out.append("hf %s freq %08x" % (n, v))
        else:
            v = rnd.choice((fb(1.0), fb(0.25), fb(4.0), 0, fb(-1.0)))
            out.append("hf %s dur %08x" % (n, v))
    return out


def s_globals():
    return ["D", "a 0", "a 1", "g 0", "g 1", "R", "T 1", "U %08x" % fb(0.0),
            "a 0", "g 0", "U %08x" % fb(1.0 / 60), "g 0", "D"]


def s_update(rnd):
    out = ["R"]
    for step in range(250):
        r = rnd.random()
        if r < 0.08:
            out.append("T %d" % rnd.choice((1, 1, 2, -1)))
        elif r < 0.5:
            out.append("U %08x" % fb(rnd.choice(DTS)))
        elif r < 0.65:
            out.append("g %d" % rnd.randrange(2))
        elif r < 0.75:
            out.append("a %d" % rnd.randrange(2))
        elif r < 0.85:
            v = rvec(rnd, rnd.choice((0.2, 1.0)))
            out.append("hs c%d %s %08x %08x" % (
                rnd.randrange(2), " ".join("%08x" % w for w in v),
                fb(rnd.choice((0.3, 0.7, 1.0))), fb(17.0)))
        elif r < 0.9:
            out.append("R")
        else:
            out.append("hf c%d time %08x" % (rnd.randrange(2),
                                             fb(rnd.uniform(0, 1))))
    return out


def rmatrix(rnd):
    """A camera matrix: a rotation by three random angles, with a random
    translation row -- and now and then a stray fourth column or a scaled
    third."""
    a, b, c = (rnd.uniform(-math.pi, math.pi) for _ in range(3))
    ca, sa, cb, sb, cc, sc = (math.cos(a), math.sin(a), math.cos(b),
                              math.sin(b), math.cos(c), math.sin(c))
    rot = [[cb * cc, cb * sc, -sb],
           [sa * sb * cc - ca * sc, sa * sb * sc + ca * cc, sa * cb],
           [ca * sb * cc + sa * sc, ca * sb * sc - sa * cc, ca * cb]]
    m = []
    for r in range(3):
        m += [rot[r][0], rot[r][1], rot[r][2], 0.0]
    m += [rnd.uniform(-500, 500), rnd.uniform(-500, 500),
          rnd.uniform(-50, 50), 1.0]
    k = rnd.random()
    if k < 0.1:
        for r in range(3):
            m[4 * r + 3] = rnd.uniform(-100, 100)
    elif k < 0.2:
        s = rnd.uniform(0.1, 10)
        for r in range(3):
            m[4 * r + 2] *= s
    return [fb(x) for x in m]


def s_apply(rnd):
    out = ["R", "W %08x" % fb(1.0)]
    for step in range(400):
        r = rnd.random()
        if r < 0.2:
            scale = rnd.choice((0.1, 0.3, 1.0, 10.0, 1e5, 1e7))
            v = rvec(rnd, scale)
            out.append("hs c%d %s %08x %08x" % (
                rnd.randrange(2), " ".join("%08x" % w for w in v),
                fb(rnd.choice((0.3, 0.7, 1.0))), fb(17.0)))
        elif r < 0.35:
            out.append("U %08x" % fb(rnd.choice(DTS[:6])))
        elif r < 0.43:
            out.append("W %08x" % rnd.choice((
                fb(1.0), fb(1.0), fb(0.5), fb(0.999), fb(2.0), NAN, 0,
                fb(1.0000001))))
        elif r < 0.48:
            # vShakeRotation: retail's z is 0, which leaves the turn about z
            # untested, so the script moves all three now and then.
            if rnd.random() < 0.3:
                rot = (-1200.0, 2000.0, 0.0)
            else:
                rot = [rnd.uniform(-3000, 3000) for _ in range(3)]
            out.append("X %s" % " ".join("%08x" % fb(x) for x in rot))
        else:
            view = rnd.choice((1, 1, 2, 2, 3, 3, 0, 4, -1, 9))
            out.append("A %d %s" % (view, " ".join(
                "%08x" % w for w in rmatrix(rnd))))
    return out


def raccel(rnd):
    """An acceleration: mostly round the range the shake reads (a biased
    length of 250 to 600), and now and then on its edges exactly -- z is
    weighed by 2, so 125 and 300 are 250 and 600 on the nose."""
    k = rnd.random()
    if k < 0.08:
        return [0, 0, fb(rnd.choice((125.0, -125.0, 300.0, -300.0)))]
    if k < 0.12:
        return [fb(rnd.uniform(-1, 1)), 0, fb(124.99)]
    if k < 0.15:
        return [NAN, 0, 0]
    s = rnd.choice((100.0, 300.0, 600.0, 1000.0, 3000.0))
    return [fb(rnd.uniform(-s, s)) for _ in range(3)]


def s_maybe(rnd, pov):
    """The players' shakes, from pov: the POV both drive cameras start on,
    0 outside the car and 1 in it."""
    out = ["R",
           "v 0 0", "v 1 1", "v 2 2", "v 3 1",
           "M 0 1 1 1 %d" % pov, "M 1 1 1 1 %d" % pov,
           "P 0 0 0 0 0", "P 1 1 0 0 1",
           "pp 0 0", "pp 1 1"]
    for step in range(900):
        r = rnd.random()
        p = rnd.randrange(2)
        if r < 0.35:
            out.append("C %d %s" % (p, " ".join("%08x" % w
                                                for w in raccel(rnd))))
        elif r < 0.5:
            q = rnd.choice((0, 1, -1))
            out.append("c %d %s" % (q, " ".join("%08x" % w
                                                for w in raccel(rnd))))
        elif r < 0.62:
            out.append("U %08x" % fb(rnd.choice(DTS[:6])))
        elif r < 0.7:
            out.append("Q %d" % p)
        elif r < 0.78:
            # A drive camera, enabled, with a CameraInfo, on an in-car POV
            # -- and half the time one of the four knocked out.
            cfg = [1, rnd.choice((1, 2)), 1, rnd.choice((1, 3))]
            j = rnd.randrange(8)
            if j < 4:
                cfg[j] = rnd.choice(((0, 4, 5), (0,), (0,), (0, 2, -1))[j])
            out.append("M %d %s" % (p, " ".join(str(x) for x in cfg)))
        elif r < 0.86:
            # The POV index byte is read signed; the number stays the
            # player's own, as the game keeps it.
            out.append("P %d %d %d %d %d" % (
                p, p, rnd.choice((0, 1, 2, 3, -1, 127, -128)),
                rnd.choice((0, 7, 7, 6, 8, -7)), rnd.choice((p, p, p, -1))))
        elif r < 0.9:
            k = rnd.randrange(NPOV)
            out.append("v %d %d" % (k, rnd.choice((0, 2, -1, 257)
                                               if k in (1, 3) and
                                               rnd.random() < 0.3
                                               else (1, 1, 0, 2))))
        elif r < 0.95:
            out.append("g %d" % p)
        else:
            out.append("R")
    return out


def script():
    rnd = random.Random(0x5ba4e002)
    return [s_globals(), s_envelopes(rnd), s_shakers(rnd), s_update(rnd),
            s_apply(rnd), s_maybe(rnd, 0), s_maybe(rnd, 1)]


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
        self.info_answer = [0, 0]
        self.pov_answer = [0, 0]
        e.stub(STUB_INFO, self.rec_info)
        e.stub(STUB_POV, self.rec_pov)
        # The emulator runs no static constructors. The matrix layer's
        # (0x0011bf70) writes the (0, 0, 0, 1) eMulVector adds into, and
        # the shake's writes its vectors, the envelope and the shakers.
        e.call(EMATH_SINIT)
        e.call(SINIT, limit=200000)
        # The test vtable: every delta 0, GetCameraInfo and GetPOV recorded.
        for off in range(0, 132, 4):
            e.put32(TEST_VTBL + off, 0)
        e.put32(TEST_VTBL + 52, STUB_INFO)
        e.put32(TEST_VTBL + 60, STUB_POV)
        for k in range(2):
            e.write(MOVS + MOV_STRIDE * k, bytes(MOV_STRIDE))
            e.put32(MOVS + MOV_STRIDE * k + M_VTBL, TEST_VTBL)
            e.write(PLAYERS + PLAYER_STRIDE * k, bytes(PLAYER_STRIDE))
        e.write(POVS, bytes(32 * NPOV))
        e.write(CAR, bytes(256))
        e.write(WORLD, bytes(512))
        e.put32(G_WORLD, WORLD)
        e.put32(G_BYNUMBER, 0)
        e.put32(G_BYNUMBER + 4, 0)
        self.envnames = {0: "null", G_ENVELOPE: "global"}
        for k in range(NENV):
            self.envnames[ENVS + 8 * k] = "e%d" % k

    def emit(self, s):
        self.out.append(s)

    def arg(self, i):
        return self.e.reg[(4, 5, 6, 7)[i]] & M32

    def mov_index(self, a):
        return (a - MOVS) // MOV_STRIDE

    def rec_info(self, em):
        k = self.mov_index(self.arg(0))
        self.emit("  info m%d" % k)
        return CAMERA_INFO if self.info_answer[k] else 0

    def rec_pov(self, em):
        k = self.mov_index(self.arg(0))
        self.emit("  pov m%d %d" % (k, s32(self.arg(1))))
        a = self.pov_answer[k]
        return 0 if a < 0 else POVS + 32 * a

    def w(self, a):
        return self.e.u32(a)

    def env_name(self, a):
        return self.envnames.get(a & M32, "?%08x" % (a & M32))

    def reset(self):
        e = self.e
        e.write(ENVS, bytes([PATTERN]) * (8 * NENV))
        e.write(PTS, bytes([PATTERN]) * (PTS_STRIDE * NENV))
        e.write(XS, bytes([PATTERN]) * (32 * NXS))

    # ---- the dumps -------------------------------------------------------

    def pshaker(self, name):
        a, full = shaker_at(name)
        w = self.w
        lanes = 4 if full else 3
        self.emit("  %s v %s amp %s t %s d %s f %s" % (
            name, " ".join(fx(w(a + 4 * i)) for i in range(lanes)),
            self.env_name(w(a + 16)), fx(w(a + 20)), fx(w(a + 24)),
            fx(w(a + 28))))

    def pcams(self):
        self.pshaker("c0")
        self.pshaker("c1")

    def vec4(self, tag, a):
        return " %s %s" % (tag, " ".join(fx(self.w(a + 4 * i))
                                         for i in range(4)))

    def pglobals(self):
        w = self.w
        self.emit("  glob%s%s%s flag %d" % (
            self.vec4("test", SHAKE_TEST), self.vec4("rot", ROTATION),
            self.vec4("bias", ACCEL_BIAS), s32(w(G_TEST))))
        self.emit("  env %s n %d pts %s k %s" % (
            "pts" if w(G_ENVELOPE) == AMP_POINTS else "?",
            s32(w(G_ENVELOPE + 4)),
            " ".join(fx(w(AMP_POINTS + 4 * i)) for i in range(10)),
            " ".join(fx(w(COEFFS + 4 * i)) for i in range(6))))
        self.pcams()

    # ---- the ops ---------------------------------------------------------

    def fcall(self, fn, *args, f12=None, f13=None):
        e = self.e
        if f12 is not None:
            e.fpr[12] = f12
        if f13 is not None:
            e.fpr[13] = f13
        return e.call(fn, *args, limit=200000)

    def shaker_op(self, op, t):
        e = self.e
        name = t[1]
        a, full = shaker_at(name)
        if op == "hi":
            self.fcall(SH_CTOR, a)
            self.pshaker(name)
        elif op == "hs":
            for i in range(4):
                e.put32(VEC + 4 * i, int(t[2 + i], 16))
            self.fcall(SH_START, a, VEC, f12=int(t[6], 16),
                       f13=int(t[7], 16))
            self.pshaker(name)
        elif op == "hu":
            self.fcall(SH_UPDATE, a, f12=int(t[2], 16))
            self.pshaker(name)
        elif op == "hv":
            e.write(OUT, bytes([PATTERN]) * 16)
            self.fcall(SH_VALUE, a, OUT)
            self.emit("  value%s" % self.vec4("v", OUT))
        elif op == "ha":
            self.fcall(SH_AMP, a)
            self.emit("  amp %s" % fx(e.fpr[0]))
        elif op == "hf":
            f = t[2]
            if f == "amp":
                k = int(t[3])
                e.put32(a + 16, 0 if k == -1 else
                        G_ENVELOPE if k == -2 else ENVS + 8 * k)
            else:
                off = {"time": 20, "dur": 24, "freq": 28}[f]
                e.put32(a + off, int(t[3], 16))
        else:
            raise SystemExit("bad op %r" % (t,))

    def op(self, t):
        e = self.e
        c = t[0]
        if c == "B":
            self.reset()
            return
        if c == "E":
            k, n = int(t[1]), int(t[2])
            p = PTS + PTS_STRIDE * k
            for i in range(2 * (n + 1)):
                e.put32(p + 4 * i, int(t[3 + i], 16))
            e.put32(ENVS + 8 * k, p)
            e.put32(ENVS + 8 * k + 4, n)
        elif c in "IO":
            k = int(t[1])
            fn = ENV_INDEX if c == "I" else ENV_OOR
            v = self.fcall(fn, ENVS + 8 * k, f12=int(t[2], 16))
            self.emit("  %s %d" % ("idx" if c == "I" else "oor", s32(v)))
        elif c == "s":
            self.fcall(ENV_SLOPE_AT, ENVS + 8 * int(t[1]), int(t[2]))
            self.emit("  slope %s" % fx(e.fpr[0]))
        elif c == "S":
            self.fcall(ENV_SLOPE, ENVS + 8 * int(t[1]), f12=int(t[2], 16))
            self.emit("  slope %s" % fx(e.fpr[0]))
        elif c == "V":
            self.fcall(ENV_VALUE, ENVS + 8 * int(t[1]), f12=int(t[2], 16))
            self.emit("  value %s" % fx(e.fpr[0]))
        elif c == "G":
            self.fcall(ENV_INTEGRAL, ENVS + 8 * int(t[1]),
                       f12=int(t[2], 16), f13=int(t[3], 16))
            self.emit("  integral %s" % fx(e.fpr[0]))
        elif c[0] == "h" and len(c) == 2:
            self.shaker_op(c, t)
        elif c == "R":
            self.fcall(RESET_SHAKERS)
            self.pcams()
        elif c == "U":
            e.put32(G_ELAPSED, int(t[1], 16))
            self.fcall(UPDATE_SHAKERS)
            self.emit("  flag %d" % s32(self.w(G_TEST)))
            self.pcams()
        elif c == "T":
            e.put32(G_TEST, int(t[1]))
        elif c == "g":
            e.write(OUT, bytes([PATTERN]) * 16)
            self.fcall(GET_SHAKE, int(t[1]), OUT)
            self.emit("  shake %s" % " ".join(fx(self.w(OUT + 4 * i))
                                              for i in range(3)))
        elif c == "a":
            v = self.fcall(IS_ACTIVE, int(t[1]))
            self.emit("  active %d" % s32(v))
        elif c == "W":
            e.put32(WORLD + W_SCALE, int(t[1], 16))
        elif c == "X":
            for i in range(3):
                e.put32(ROTATION + 4 * i, int(t[1 + i], 16))
        elif c == "A":
            for i in range(16):
                e.put32(MATRIX + 4 * i, int(t[2 + i], 16))
            self.fcall(APPLY, int(t[1]), MATRIX)
            self.emit("  m %s" % " ".join(fx(self.w(MATRIX + 4 * i))
                                          for i in range(16)))
        elif c == "P":
            p, num, pov, zone, mv = (int(x) for x in t[1:6])
            a = PLAYERS + PLAYER_STRIDE * p
            e.put32(a + P_NUMBER, num)
            e.mem[a + P_POV] = pov & 0xff
            e.put32(a + P_ZONE, zone)
            e.put32(a + P_MOVER, 0 if mv < 0 else MOVS + MOV_STRIDE * mv)
        elif c == "pp":
            slot, p = int(t[1]), int(t[2])
            e.put32(G_BYNUMBER + 4 * slot,
                    0 if p < 0 else PLAYERS + PLAYER_STRIDE * p)
        elif c == "M":
            k, ty, en, info, pov = (int(x) for x in t[1:6])
            a = MOVS + MOV_STRIDE * k
            e.put32(a + M_TYPE, ty)
            e.put32(a + M_ENABLED, en)
            self.info_answer[k] = info
            self.pov_answer[k] = pov
        elif c == "v":
            e.put32(POVS + 32 * int(t[1]), int(t[2]))
        elif c == "Q":
            v = self.fcall(INCAR, PLAYERS + PLAYER_STRIDE * int(t[1]))
            self.emit("  incar %d" % s32(v))
        elif c == "C":
            for i in range(3):
                e.put32(VEC + 4 * i, int(t[2 + i], 16))
            e.put32(VEC + 12, 0)
            self.fcall(MAYBE, int(t[1]), VEC)
            self.pcams()
        elif c == "c":
            p = int(t[1])
            e.put32(CAR + C_PLAYER, 0 if p < 0 else
                    PLAYERS + PLAYER_STRIDE * p)
            for i in range(3):
                e.put32(CAR + C_ACCEL + 4 * i, int(t[2 + i], 16))
            self.fcall(CAR_MAYBE, CAR)
            self.pcams()
        elif c == "D":
            self.pglobals()
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


def build_harness(tmp, name="shake_test"):
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
    # tEnvelope
    M("idx_le", SHKC, "!(t < e->pPoints[i].fTime)", "t > e->pPoints[i].fTime"),
    M("idx_cap", SHKC, "    while (i < e->nPoints && !(t",
      "    while (i < e->nPoints - 1 && !(t"),
    M("oor_first_le", SHKC, "    return t < e->pPoints[0].fTime\n",
      "    return t <= e->pPoints[0].fTime\n"),
    M("oor_last_lt", SHKC, "        || e->pPoints[e->nPoints - 1].fTime <= t;",
      "        || e->pPoints[e->nPoints - 1].fTime < t;"),
    M("slope_at_neg", SHKC, "    if (i < 0 || i > e->nPoints - 2)",
      "    if (i > e->nPoints - 2)"),
    M("slope_at_last", SHKC, "    if (i < 0 || i > e->nPoints - 2)",
      "    if (i < 0 || i > e->nPoints - 1)"),
    M("slope_swap", SHKC,
      "    return (p[1].fValue - p[0].fValue) / (p[1].fTime - p[0].fTime);",
      "    return (p[1].fTime - p[0].fTime) / (p[1].fValue - p[0].fValue);"),
    M("slope_t_no_oor", SHKC,
      "    if (tenvelope_out_of_range(e, t))\n        return 0.0f;\n"
      "    return tenvelope_get_slope_at",
      "    return tenvelope_get_slope_at"),
    M("value_no_oor", SHKC,
      "    if (tenvelope_out_of_range(e, t))\n        return 0.0f;\n"
      "    i = tenvelope_get_index(e, t);",
      "    i = tenvelope_get_index(e, t);"),
    M("value_from_zero", SHKC, "    return p->fValue + s * (t - p->fTime);",
      "    return p->fValue + s * t;"),
    M("integral_no_swap", SHKC,
      "    if (b < a) {\n        float t = a;\n        a = b;\n        b = t;\n    }\n",
      ""),
    M("integral_no_clamp_a", SHKC,
      "    if (a < e->pPoints[0].fTime)\n        a = e->pPoints[0].fTime;\n", ""),
    M("integral_no_clamp_b", SHKC,
      "    if (e->pPoints[e->nPoints - 1].fTime < b)\n"
      "        b = e->pPoints[e->nPoints - 1].fTime;\n", ""),
    M("integral_quarter", SHKC, "        v = v + (tenvelope_get_value(e, x1) - v) * 0.5f;",
      "        v = v + (tenvelope_get_value(e, x1) - v) * 0.25f;"),
    M("integral_mean", SHKC, "        v = v + (tenvelope_get_value(e, x1) - v) * 0.5f;",
      "        v = (v + tenvelope_get_value(e, x1)) * 0.5f;"),
    M("integral_index", SHKC, "    i = tenvelope_get_index(e, a) + 1;",
      "    i = tenvelope_get_index(e, a);"),
    M("integral_no_min", SHKC, "        if (b < x1)\n            x1 = b;\n", ""),
    M("integral_no_count", SHKC,
      "        if (!(x0 < b) || i >= e->nPoints)",
      "        if (!(x0 < b) || i > e->nPoints)"),
    M("integral_no_end", SHKC,
      "        if (!(x0 < b) || i >= e->nPoints)",
      "        if (i >= e->nPoints)"),
    # tShaker
    M("init_dur", SHKC, "    s->fDuration = 1.0f;", "    s->fDuration = 2.0f;"),
    M("init_freq", SHKC, "    s->fFrequency = 17.0f;", "    s->fFrequency = 16.0f;"),
    M("init_amp", SHKC,
      "    s->vShake.z = 0.0f;\n    s->pAmplitude = NULL;\n",
      "    s->vShake.z = 0.0f;\n"),
    M("init_time", SHKC, "    s->pAmplitude = NULL;\n    s->fTime = 0.0f;\n}",
      "    s->pAmplitude = NULL;\n}"),
    M("init_pad", SHKC, "    s->vShake.z = 0.0f;\n    s->pAmplitude = NULL;\n",
      "    s->vShake.z = 0.0f;\n    s->vShake.pad = 0.0f;\n"
      "    s->pAmplitude = NULL;\n"),
    M("amp_still_1", SHKC,
      "    if (s->pAmplitude == NULL)\n        return 0.0f;\n"
      "    return tenvelope_get_value(s->pAmplitude, s->fTime);",
      "    if (s->pAmplitude == NULL)\n        return 1.0f;\n"
      "    return tenvelope_get_value(s->pAmplitude, s->fTime);"),
    M("start_no_negate", SHKC, "    s->vShake.y = v->y * -1.0f;",
      "    s->vShake.y = v->y;"),
    M("start_pad", SHKC, "    s->vShake.pad = v->pad * -1.0f;",
      "    s->vShake.pad = 0.0f;"),
    M("start_env_kept", SHKC, "    s->pAmplitude = &ShakeAmplitudeEnvelope;\n",
      ""),
    M("start_time_kept", SHKC,
      "    s->fDuration = duration;\n    s->fTime = 0.0f;",
      "    s->fDuration = duration;"),
    M("start_swap", SHKC,
      "    s->fFrequency = frequency;\n    s->pAmplitude = &ShakeAmplitudeEnvelope;\n"
      "    s->fDuration = duration;",
      "    s->fFrequency = duration;\n    s->pAmplitude = &ShakeAmplitudeEnvelope;\n"
      "    s->fDuration = frequency;"),
    M("update_mul", SHKC, "    s->fTime = s->fTime + dt / s->fDuration;",
      "    s->fTime = s->fTime + dt * s->fDuration;"),
    M("update_no_stop", SHKC,
      "    if (tenvelope_out_of_range(s->pAmplitude, s->fTime))\n"
      "        s->pAmplitude = NULL;\n", ""),
    M("update_still", SHKC,
      "    if (s->pAmplitude == NULL)\n        return;\n"
      "    s->fTime = s->fTime + dt", "    s->fTime = s->fTime + dt"),
    M("value_odd", SHKC, "    if (!(ee_trunc_w(s->fTime * s->fFrequency) & 1)",
      "    if ((ee_trunc_w(s->fTime * s->fFrequency) & 1)"),
    M("value_round", SHKC, "ee_trunc_w(s->fTime * s->fFrequency)",
      "ee_trunc_w(s->fTime * s->fFrequency + 0.5f)"),
    M("value_pad", SHKC, "    out->pad = s->vShake.pad * a;",
      "    out->pad = 0.0f;"),
    # the globals
    M("points_value", SHKC, "{ 0.1f, 0.7f }", "{ 0.1f, 0.75f }"),
    M("coeff_min", SHKC, "    250.0f, 600.0f,", "    200.0f, 600.0f,"),
    M("coeff_max", SHKC, "    250.0f, 600.0f,", "    250.0f, 500.0f,"),
    M("coeff_amp", SHKC, " 0.08f, 0.16f,", " 0.08f, 0.15f,"),
    M("coeff_dur", SHKC, " 0.3f, 0.7f,\n};", " 0.3f, 0.8f,\n};"),
    M("sinit_test_z", SHKC, "    vShakeTest.z = 0.3f;", "    vShakeTest.z = 0.25f;"),
    M("sinit_rot_x", SHKC, "    vShakeRotation.x = -1200.0f;",
      "    vShakeRotation.x = 1200.0f;"),
    M("sinit_rot_y", SHKC, "    vShakeRotation.y = 2000.0f;",
      "    vShakeRotation.y = 2048.0f;"),
    M("sinit_rot_z", SHKC, "    vShakeRotation.z = 0.0f;",
      "    vShakeRotation.z = 500.0f;"),
    M("sinit_bias_x", SHKC, "    vShakeAccelBias.x = 0.7f;",
      "    vShakeAccelBias.x = 0.75f;"),
    M("sinit_bias_z", SHKC, "    vShakeAccelBias.z = 2.0f;",
      "    vShakeAccelBias.z = 1.0f;"),
    M("sinit_env_n", SHKC, "    ShakeAmplitudeEnvelope.nPoints = 5;",
      "    ShakeAmplitudeEnvelope.nPoints = 4;"),
    M("sinit_no_shakers", SHKC,
      "    ShakeAmplitudeEnvelope.nPoints = 5;\n    for (i = 0; i < 2; i++)\n"
      "        tshaker_init(&CameraShakers[i]);\n",
      "    ShakeAmplitudeEnvelope.nPoints = 5;\n    (void)i;\n"),
    M("reset_one", SHKC,
      "void reset_camera_shakers(void)\n{\n    int32_t i;\n\n"
      "    for (i = 0; i < 2; i++)",
      "void reset_camera_shakers(void)\n{\n    int32_t i;\n\n"
      "    for (i = 0; i < 1; i++)"),
    M("test_kept", SHKC, "        bShakeTest = 0;\n", ""),
    M("test_dur", SHKC, "#define SHAKE_TEST_DURATION   0.6f",
      "#define SHAKE_TEST_DURATION   0.5f"),
    M("test_player2", SHKC,
      "        tshaker_start_shaking(&CameraShakers[0], &vShakeTest,",
      "        tshaker_start_shaking(&CameraShakers[1], &vShakeTest,"),
    M("update_one", SHKC,
      "    for (i = 0; i < 2; i++)\n        tshaker_update(&CameraShakers[i],",
      "    for (i = 0; i < 1; i++)\n        tshaker_update(&CameraShakers[i],"),
    M("freq", SHKC, "#define SHAKE_FREQUENCY      17.0f",
      "#define SHAKE_FREQUENCY      16.0f"),
    M("active_time", SHKC, "    return CameraShakers[i].pAmplitude != NULL;",
      "    return CameraShakers[i].fTime < 1.0f;"),
    # ApplyCameraShake
    M("apply_scale_le", SHKC, "    if (pCurrentWorld->fTimeScale < 1.0f)",
      "    if (pCurrentWorld->fTimeScale <= 1.0f)"),
    M("apply_no_scale", SHKC,
      "    if (pCurrentWorld->fTimeScale < 1.0f)\n        return;\n", ""),
    M("apply_no_rvm", SHKC,
      "    if (view == EVIEW_ID_PLAYER1 || view == EVIEW_ID_PLAYER1_RVM)",
      "    if (view == EVIEW_ID_PLAYER1)"),
    M("apply_p2_first", SHKC, "        i = 1;\n    else\n        return;",
      "        i = 0;\n    else\n        return;"),
    M("apply_any_view", SHKC, "        i = 1;\n    else\n        return;",
      "        i = 1;\n    else\n        i = 0;"),
    M("apply_w", SHKC, "    v.w = 0.0f;", "    v.w = 1.0f;"),
    M("apply_trans_w", SHKC, "    rot.v3.w = 1.0f;\n", ""),
    M("apply_lv_apart", SHKC, [
        ("    bVector4 v;\n", "    bVector4 v, lv;\n"),
        ("    eMulVector4(&rot.v3, m, &v);\n    rot.v3.w = 1.0f;\n"
         "    eRotateX(&rot, &rot, (uint16_t)ee_trunc_w(vShakeRotation.x\n"
         "                                              * (rot.v3.z + rot.v3.y)));\n"
         "    eRotateY(&rot, &rot, (uint16_t)ee_trunc_w(vShakeRotation.y * rot.v3.x));\n"
         "    eRotateZ(&rot, &rot, (uint16_t)ee_trunc_w(vShakeRotation.z\n"
         "                                              * (rot.v3.x + rot.v3.y)));",
         "    eMulVector4(&lv, m, &v);\n"
         "    eRotateX(&rot, &rot, (uint16_t)ee_trunc_w(vShakeRotation.x\n"
         "                                              * (lv.z + lv.y)));\n"
         "    eRotateY(&rot, &rot, (uint16_t)ee_trunc_w(vShakeRotation.y * lv.x));\n"
         "    eRotateZ(&rot, &rot, (uint16_t)ee_trunc_w(vShakeRotation.z\n"
         "                                              * (lv.x + lv.y)));")]),
    M("apply_x_diff", SHKC, "* (rot.v3.z + rot.v3.y)));",
      "* (rot.v3.z - rot.v3.y)));"),
    M("apply_y_axis", SHKC, "(vShakeRotation.y * rot.v3.x));",
      "(vShakeRotation.y * rot.v3.y));"),
    M("apply_z_sum", SHKC, "* (rot.v3.x + rot.v3.y)));",
      "* (rot.v3.x + rot.v3.z)));"),
    M("apply_no_z", SHKC,
      "    eRotateZ(&rot, &rot, (uint16_t)ee_trunc_w(vShakeRotation.z\n"
      "                                              * (rot.v3.x + rot.v3.y)));\n",
      ""),
    M("apply_order", SHKC, "    eMulMatrix(m, m, &rot);",
      "    eMulMatrix(m, &rot, m);"),
    M("apply_yx", SHKC, [
        ("    eRotateX(&rot, &rot, (uint16_t)ee_trunc_w(vShakeRotation.x\n"
         "                                              * (rot.v3.z + rot.v3.y)));\n"
         "    eRotateY(&rot, &rot, (uint16_t)ee_trunc_w(vShakeRotation.y * rot.v3.x));\n",
         "    eRotateY(&rot, &rot, (uint16_t)ee_trunc_w(vShakeRotation.y * rot.v3.x));\n"
         "    eRotateX(&rot, &rot, (uint16_t)ee_trunc_w(vShakeRotation.x\n"
         "                                              * (rot.v3.z + rot.v3.y)));\n")]),
    # MaybeCameraShake
    M("maybe_no_incar", SHKC,
      "    if (player_is_camera_pov_in_car(*pp))\n        return;\n", ""),
    M("maybe_bias_y", SHKC, "    a.y = vShakeAccelBias.y * accel->y;",
      "    a.y = accel->y;"),
    M("maybe_bias_swap", SHKC, "    a.z = vShakeAccelBias.z * accel->z;",
      "    a.z = vShakeAccelBias.x * accel->z;"),
    M("maybe_len_order", SHKC,
      "    len = sqrtf((a.x * a.x + a.y * a.y) + a.z * a.z);",
      "    len = sqrtf(a.x * a.x + (a.y * a.y + a.z * a.z));"),
    M("maybe_min_le", SHKC, "    if (len < k[0])\n", "    if (len <= k[0])\n"),
    M("maybe_no_clamp", SHKC, "    if (k[1] < len)\n        len = k[1];\n", ""),
    M("maybe_amp_le", SHKC, "    if (!(tshaker_get_amplitude(s) < amplitude))",
      "    if (tshaker_get_amplitude(s) > amplitude)"),
    M("maybe_no_amp", SHKC,
      "    if (!(tshaker_get_amplitude(s) < amplitude))\n        return;\n", ""),
    M("maybe_amp_lerp", SHKC, "    amplitude = k[2] + f * (k[3] - k[2]);",
      "    amplitude = k[3] + f * (k[3] - k[2]);"),
    M("maybe_dur_lerp", SHKC, "    duration = k[4] + f * (k[5] - k[4]);",
      "    duration = k[4] + f * (k[5] - k[2]);"),
    M("maybe_f", SHKC, "    f = (len - k[0]) / (k[1] - k[0]);",
      "    f = (len - k[0]) / k[1];"),
    M("maybe_zone", SHKC, "(*pp)->nZoneCurrent == PLAYER_ZONE_AFTER_JUMP)",
      "(*pp)->nZoneCurrent == PLAYER_ZONE_AFTER_JUMP - 1)"),
    M("maybe_zone_amp", SHKC, "#define SHAKE_ZONE_AMPLITUDE  0.8f",
      "#define SHAKE_ZONE_AMPLITUDE  1.0f"),
    M("maybe_zone_dur", SHKC, "#define SHAKE_ZONE_DURATION   1.2f",
      "#define SHAKE_ZONE_DURATION   1.0f"),
    M("maybe_norm", SHKC, "    bNormalize3To(&v, &a, amplitude);",
      "    bNormalize3To(&v, &a, duration);"),
    M("maybe_shaker", SHKC, "    tShaker *s = &CameraShakers[player];",
      "    tShaker *s = &CameraShakers[0];"),
    M("maybe_null_player", SHKC,
      "    if (*pp != NULL && (*pp)->nZoneCurrent", "    if ((*pp)->nZoneCurrent"),
    M("maybe_pad", SHKC, "    v.pad = 0.0f;\n    bNormalize3To", "    bNormalize3To"),
    M("car_null", SHKC, "    if (c->pPlayer != NULL)\n        maybe", "        maybe"),
    M("car_number", SHKC, "maybe_camera_shake(c->pPlayer->PlayerNumber,",
      "maybe_camera_shake(0,"),
    # IsCameraPOVInCar
    M("incar_no_null", PLYC, "    if (m == NULL || m->Type != CM_DRIVE)",
      "    if (m->Type != CM_DRIVE)"),
    M("incar_type", PLYC, "    if (m == NULL || m->Type != CM_DRIVE)",
      "    if (m == NULL || m->Type < CM_DRIVE)"),
    M("incar_no_info", PLYC,
      "    if (m->vtbl->GetCameraInfo(m) == NULL)\n        return 0;\n",
      "    m->vtbl->GetCameraInfo(m);\n"),
    M("incar_no_enabled", PLYC, "    if (!m->Enabled)\n        return 0;\n", ""),
    M("incar_enabled_first", PLYC, [
        ("    if (m == NULL || m->Type != CM_DRIVE)\n        return 0;\n",
         "    if (m == NULL || m->Type != CM_DRIVE)\n        return 0;\n"
         "    if (!m->Enabled)\n        return 0;\n"),
        ("    m = p->pCameraMover;\n    if (!m->Enabled)\n        return 0;\n",
         "    m = p->pCameraMover;\n")]),
    M("incar_pov_type", PLYC, "    return pov != NULL && pov->Type == POV_INCAR;",
      "    return pov != NULL && pov->Type != POV_BUMPER;"),
    M("incar_no_pov_null", PLYC, "    return pov != NULL && pov->Type == POV_INCAR;",
      "    return pov->Type == POV_INCAR;"),
    M("incar_index_unsigned", PLYC,
      "    pov = m->vtbl->GetPOV(m, p->PlayerSettings.DriveCameraPOVIndex);",
      "    pov = m->vtbl->GetPOV(m, (uint8_t)p->PlayerSettings.DriveCameraPOVIndex);"),
]

# Mutants that cannot change what either side computes, each with why.
EQUIVALENT = {
    # IsCameraPOVInCar reads the player's mover before the zone test, so a
    # NULL player never gets that far, in the image or here.
    "maybe_null_player": "IsCameraPOVInCar reads *pp first",
    # The fourth lane bNormalize leaves is the image's stack garbage. Only
    # the players' shakers hold it, their dumps print three lanes, GetShake's
    # prints three, and ApplyCameraShake zeroes it.
    "maybe_pad": "the fourth lane is never read",
    # b is clamped to the last point's time, so the segment that reads the
    # last point ends at b, and the time test ends the loop before the count
    # can. The count only matters without the clamp (integral_no_clamp_b).
    "integral_no_count": "the time test always ends the loop first",
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
