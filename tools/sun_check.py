#!/usr/bin/env python3
"""Cross-check 3DS Files/source/sundraw.c (StuffSun and StuffSunGlare, the
draw half of Sun.obj) and epoly.c (ePoly's constructor) against the image
itself, run in mipsemu.

The model is the image: StuffSun and StuffSunGlare run as shipped, and so
do ePoly's constructor and destructor. Every other callee is stubbed. Each
stub prints its name and its arguments. The ones whose answer matters do
the same small thing on both sides:

    eRotTransPers      the scenario's next screen position
    eMulVector         the scenario's next eye z, and moves to the next
    bSin, bCos         (a - 32768) / 32768 and ((7a) & 0xffff) / 65536 - 0.5
    ePoly::Render      prints the poly, field by field
    eTransferZBufferRect  prints the rect

The harness links sundraw.c, epoly.c and sun.c with the same stubs, and
prints the same lines. After each step both dump the glare's globals,
WorldTimer, and the rect of each of the 15 SunZBuffers.

Scenarios cover:
- TRACKB12's own sun, and layers of every kind: BLEND and ADD, a NULL
  texture, IntensityScale 0, negative and large, and every angle;
- view IDs other than 1, and no sun chunk;
- the sun behind the view, at -0 and NaN, and off each edge and on it;
- SunPosX and SunPosY, alone, together, -0 and NaN;
- the count over each shape of rect, and the rect clipped at each edge;
- the glare from its start through each phase and around again, the
  reset, time running back, and GlareDist.

    python tools/sun_check.py
    python tools/sun_check.py --mutate [--only a,b]
    python tools/sun_check.py --dump out/sun
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import physicscar_check as pcc
from mipsemu import Emu, M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/sun_test.c"
SDC = "3DS Files/source/sundraw.c"
SDH = "3DS Files/source/sundraw.h"
EPC = "3DS Files/source/epoly.c"
EPH = "3DS Files/source/epoly.h"
SUC = "3DS Files/source/sun.c"
SOURCES = [HARNESS, SDC, EPC, SUC]

HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = 0x00328bf0
SUN_INFO = GP - 24144
SUN_POSX = GP - 24140
SUN_POSY = GP - 24136
GLARE_DIST = GP - 24132
START_GLARE = GP - 24128
RESET_GLARE = GP - 24124
GLARE_START = GP - 24120
GLARE_PHASE = GP - 24116
WORLD_TIMER = GP - 20224
PHASE_TIMES = 0x00290e50
SUN_ZB = 0x002dfe00
ZB_SIZE = 2064
SUN_TEX = 0x002e76f0

STUFF_SUN = 0x00123ec0
STUFF_GLARE = 0x001244c8
ROT_TRANS_PERS = 0x0011bb98
MUL_VECTOR = 0x0011bb28
BSIN = 0x00241df8
BCOS = 0x00241ec8
RENDER = 0x0010e580
TRANSFER = 0x00110610

TEX = 0x01001000                     # t0..t4, 256 apart
VIEW = 0x01002000
RT = 0x01002100
CAM = 0x01002200
WV = 0x01002400
WS = 0x01002440
INFO = 0x01003000
POLY = 0x01004000
EPOLY_CTOR = 0x0010e480

NAN = 0x7fc00001


def fbits(f):
    if isinstance(f, int):
        return f & M32
    return struct.unpack("<I", struct.pack("<f", f))[0]


def bitsf(b):
    return struct.unpack("<f", struct.pack("<I", b & M32))[0]


# TRACKB12's SunChunkInfoE: four layers, all ADD, then two empty.
B12_LAYERS = [
    (0, 1, 1.0, 60.0, 0.0, 0.0, (255, 200, 100, 128), 0, 0.0),
    (0, 1, 0.5, 320.0, 0.0, 0.0, (130, 110, 25, 128), 0, 0.0),
    (2, 1, 0x3f333333, 800.0, -9.0, 28.0, (159, 122, 75, 128), 0,
     0x3e4ccccd),
    (2, 1, 0x3ea3d70a, 800.0, 28.0, 9.0, (166, 119, 72, 128), 16384,
     0x3e4ccccd),
    (0, 0, 0.0, 0.0, 0.0, 0.0, (0, 0, 0, 0), 0, 0.0),
    (0, 0, 0.0, 0.0, 0.0, 0.0, (0, 0, 0, 0), 0, 0.0),
]

# Every kind of layer: BLEND and ADD, each texture, a negative and a large
# intensity, an angle past 16 bits, offsets, and a sweep.
MIXED_LAYERS = [
    (0, 0, 1.0, 40.0, 3.5, -2.25, (0x80, 0x40, 0x20, 0x11), 0x12345, 0.25),
    (1, 1, -0.75, 90.0, -10.0, 4.0, (1, 2, 3, 4), -5000, -0.5),
    (2, 0, 3.0, 150.0, 0.0, 0.0, (255, 255, 255, 255), 32768, 1.0),
    (3, 1, 0.3, 17.0, 100.0, -100.0, (9, 8, 7, 6), 65535, 0.125),
    (4, 0, -3.5, 64.0, 0.5, 0.5, (0x7f, 0x80, 0x81, 0x82), -1, 2.0),
    (0, 1, 0.01, 12.0, 0.0, 1.0, (10, 20, 30, 40), 100, 0.0),
]


def record(layers, pos=(-16384.0, 800.0, 6000.0), version=2):
    rec = struct.pack("<i", version)
    rec += b"".join(struct.pack("<I", fbits(p)) for p in pos)
    rec += b"".join(struct.pack("<I", fbits(p)) for p in pos)
    for (tex, at, inten, size, ox, oy, col, ang, sweep) in layers:
        rec += struct.pack("<ii", tex, at)
        rec += b"".join(struct.pack("<I", fbits(v))
                        for v in (inten, size, ox, oy))
        rec += bytes(col)
        rec += struct.pack("<iI", ang, fbits(sweep))
    assert len(rec) == 244
    return rec


def at(px, py, ez=10.0, w=640, h=448):
    """eRotTransPers's screen x and y that put the sun at pixel (px, py)."""
    return (fbits(float(px) + 2048.0 - (w >> 1)),
            fbits(float(py) + 2048.0 - (h >> 1)), fbits(ez))


class Scenario(object):
    def __init__(self, ops, layers=None, info=1, texmask=0x1f, view_id=1,
                 rt_id=1, w=640, h=448, cam_pos=(10.0, 20.0, 30.0),
                 cam_dir=(0.0, 0.6, 0.8), posx=0.0, posy=0.0, dist=1.0,
                 start=0, reset=0, gtime=0.0, phase=0,
                 ptimes=(0.05, 0.2, 0.65, 5.0), zb=(0, 32, 0, 32), seed=0,
                 proj=None, timers=(4000,)):
        self.ops = ops
        self.rec = record(layers if layers is not None else B12_LAYERS)
        self.info = info
        self.texmask = texmask
        self.view_id = view_id
        self.rt_id = rt_id
        self.w, self.h = w, h
        self.cam = [fbits(v) for v in cam_pos] + [0x0badf00d] \
            + [fbits(v) for v in cam_dir] + [0x0badf00e]
        self.glare = [fbits(posx), fbits(posy), fbits(dist), start, reset,
                      fbits(gtime), phase]
        self.ptimes = [fbits(v) for v in ptimes]
        self.zb = list(zb)
        self.seed = seed
        self.proj = list(proj) if proj is not None else [at(320, 224, w=w,
                                                            h=h)]
        self.timers = list(timers)

    def lines(self):
        out = []
        out.append("I %d %d %s" % (self.info, self.texmask, self.rec.hex()))
        out.append("V %d %d %d %d %s" % (
            self.view_id, self.rt_id, self.w, self.h,
            " ".join("%x" % c for c in self.cam)))
        out.append("G %s %s" % (" ".join("%x" % (g & M32)
                                         for g in self.glare),
                                " ".join("%x" % p for p in self.ptimes)))
        out.append("Z %d %d %d %d %d" % tuple(self.zb + [self.seed]))
        out.append("P %d %s" % (len(self.proj), " ".join(
            "%x %x %x" % p for p in self.proj)))
        out.append("T %d %s" % (len(self.timers), " ".join(
            str(t) for t in self.timers)))
        out.append("S %s" % self.ops)
        return out


PAT = (0, 63, 64, 65, 1, 0xffff, 32, 100, 0x8000, 63)


def zvalue(b, k, seed):
    return PAT[(k * 7 + b * 3 + seed * 5 + (k >> 5)) % len(PAT)]


def script():
    S = Scenario
    m = MIXED_LAYERS
    big = 3e38
    sc = [
        # TRACKB12's sun in the middle, the whole rect, and the next frame.
        S("SSzS"),
        # The same with every texture missing, and each one alone.
        S("S", texmask=0),
        S("S", texmask=0x01), S("S", texmask=0x04), S("S", texmask=0x1b),
        # Every kind of layer, and at another place and target.
        S("SzS", layers=m, proj=[at(100.5, 50.25), at(600, 400)]),
        S("S", layers=m, rt_id=7, w=512, h=256,
          proj=[at(30, 200, w=512, h=256)], seed=3),
        # Odd sizes: the halves round down.
        S("S", layers=m, w=641, h=449, proj=[at(320, 224, w=641, h=449)]),
        S("S", layers=m, w=-7, h=-9, proj=[(fbits(2048.0), fbits(2048.0),
                                            fbits(1.0))]),
        # Other views, and no sun chunk.
        S("S", view_id=0), S("S", view_id=2), S("S", view_id=-1),
        S("S", view_id=257),
        S("S", info=0),
        # Behind the view, and just not.
        S("S", proj=[at(320, 224, -1.0)]),
        S("S", proj=[at(320, 224, 0x80000000)]),
        S("S", proj=[at(320, 224, NAN)]),
        S("S", proj=[at(320, 224, -1e-30)]),
        # Off each edge by the largest CENTER, and on it. TRACKB12's is
        # 320; MIXED's is 40.
        S("S", proj=[at(-320, 224)]), S("S", proj=[at(-320.03125, 224)]),
        S("S", proj=[at(960, 224)]), S("S", proj=[at(960.0625, 224)]),
        S("S", proj=[at(320, -320)]), S("S", proj=[at(320, -320.03125)]),
        S("S", proj=[at(320, 768)]), S("S", proj=[at(320, 768.0625)]),
        S("S", layers=m, proj=[at(-40, 5)]),
        S("S", layers=m, proj=[at(-40.0625, 5)]),
        S("S", layers=m, proj=[at(5, 488)]),
        S("S", layers=m, proj=[at(5, 488.0625)]),
        # No CENTER layer, a negative one, and a NaN one.
        S("S", layers=[(1, 0, 1.0, 50.0, 0, 0, (1, 1, 1, 1), 0, 0.5)] * 6,
          proj=[at(-0.5, 10)]),
        S("S", layers=[(0, 0, 1.0, -50.0, 0, 0, (1, 1, 1, 1), 0, 0.5)]
          + [(1, 1, 1.0, 20.0, 0, 0, (2, 2, 2, 2), 0, 0.5)] * 5,
          proj=[at(0.0, 10)]),
        S("S", layers=[(0, 0, 1.0, NAN, 0, 0, (1, 1, 1, 1), 0, 0.5),
                       (0, 1, 1.0, 30.0, 0, 0, (3, 3, 3, 3), 0, 0.5)] * 3,
          proj=[at(-30.0, 10)]),
        # SunPosX and SunPosY.
        S("S", posx=100.0, proj=[at(900, 900)]),
        S("S", posy=-20.0, proj=[at(900, 900)]),
        S("S", posx=5.5, posy=6.5),
        S("S", posx=-0.0, posy=0.0, proj=[at(1, 2)]),
        S("S", posx=0.0, posy=0x80000000, proj=[at(3, 4)]),
        S("S", posx=NAN, layers=[(1, 0, 1.0, 5.0, 0, 0, (1, 1, 1, 1), 0,
                                  0.5)] * 6),
        S("S", posx=2000.0, posy=10.0),
        # The count: the rect's every shape, each pattern.
        S("S", zb=(0, 0, 0, 32)), S("S", zb=(5, 20, 3, 31), seed=1),
        S("S", zb=(31, 32, 31, 32), seed=2), S("S", zb=(20, 10, 0, 32)),
        S("S", zb=(0, 32, 16, 8)), S("SzSzS", zb=(1, 31, 1, 31), seed=4),
        S("S", zb=(0, 32, 0, 32), seed=7, layers=m),
        # The rect clipped at each edge, and wholly off.
        S("SS", proj=[at(3.75, 224), at(-15.5, 224)]),
        S("SS", proj=[at(630, 224), at(655.9, 224)]),
        S("SS", proj=[at(320, 8), at(320, -300)]),
        S("SS", proj=[at(320, 440), at(320, 700)]),
        S("SS", proj=[at(-100, -100), at(740, 548)]),
        S("SSS", proj=[at(16, 16), at(15.99, 15.99), at(624, 432)]),
        # The largest CENTER is the last layer.
        S("S", layers=[(1, 0, 1.0, 10.0, 0, 0, (1, 1, 1, 1), 0, 0.5)] * 5
          + [(0, 1, 1.0, 100.0, 0, 0, (2, 2, 2, 2), 0, 0.5)],
          proj=[at(-50, 10)]),
        # -0 through SunPosX and SunPosY, onto an offset of -0 and a quad of
        # no size.
        S("S", posx=0x80000000, posy=5.0,
          layers=[(0, 0, 1.0, 0.0, 0x80000000, 0x80000000, (1, 1, 1, 1), 0,
                   0.5)] * 6),
        S("S", posx=5.0, posy=0x80000000,
          layers=[(0, 1, 1.0, 0.0, 0x80000000, 0x80000000, (1, 1, 1, 1), 0,
                   0.5)] * 6),
        # The alpha: the count over and under, large and wrapping.
        S("S", layers=[(0, 0, 1.5, 10.0, 0, 0, (5, 6, 7, 8), 0, 0.0),
                       (1, 1, 2.0, 10.0, 0, 0, (5, 6, 7, 8), 0, 0.0),
                       (2, 0, -2.5, 10.0, 0, 0, (5, 6, 7, 8), 0, 0.0),
                       (3, 1, 1e10, 10.0, 0, 0, (5, 6, 7, 8), 0, 0.0),
                       (4, 0, -1e10, 10.0, 0, 0, (5, 6, 7, 8), 0, 0.0),
                       (0, 1, 0x80000000, 10.0, 0, 0, (5, 6, 7, 8), 0,
                        0.0)]),
        S("S", zb=(0, 32, 0, 32), seed=1,
          layers=[(i % 5, i & 1, 1000.0 + 77.0 * i, 10.0, 0, 0,
                   (5, 6, 7, 8), 0, 0.0) for i in range(6)]),
        S("S", zb=(0, 32, 0, 32), seed=5,
          layers=[(0, 0, NAN, 10.0, 0, 0, (5, 6, 7, 8), 0, 0.0)] * 6),
        # The angle: sweeps that saturate, and angles at each end.
        S("S", layers=[(0, 0, 1.0, 20.0, 0, 0, (1, 2, 3, 4), a, sw)
                       for a, sw in ((0, big), (1, -big), (-32768, 1e5),
                                     (0x7fffffff, -1e5), (0xffff, 0.5),
                                     (0x10000, NAN))],
          proj=[at(10, 10)]),
        # The glare: started, through each phase and around.
        S("bGGGGGGGGG", timers=(0, -4, 4, 100, 200, 800, 1500, 2000, 4700,
                                 25000)),
        S("bGGGGGG", timers=(40, 60, 80, 400, 1000, 2600, 3000)),
        S("GGGG", gtime=1.0, phase=1, timers=(4000, 4200, 4900, 5000)),
        S("GGG", gtime=1.0, phase=2, timers=(4100, 5000, 6700)),
        S("GGG", gtime=1.0, phase=3, timers=(4100, 30000, 30100)),
        S("GGG", gtime=2.0, phase=0, timers=(8000, 8100, 8200)),
        # The phase ends exactly, and time runs back.
        S("GG", gtime=1.0, phase=0, ptimes=(0.5, 0.25, 0.75, 1.0),
          timers=(6000, 6001)),
        S("GG", gtime=0.5, phase=0, ptimes=(0.5, 0.25, 0.75, 1.0),
          timers=(4000, 4001)),
        S("GG", gtime=1.5, phase=1, ptimes=(0.5, 0.5, 0.75, 1.0),
          timers=(8000, 8001)),
        # Phase 3 runs past its time, and wraps to 0.
        S("GG", gtime=1.0, phase=3, timers=(30000, 30100)),
        # A start over a phase left from before.
        S("bGGG", phase=2, timers=(40, 100, 300)),
        S("GG", gtime=1.0, phase=0, timers=(3000, 3999)),
        S("GG", gtime=1.0, phase=2, timers=(3000, 2000)),
        # The reset, before a start and after.
        S("bGrGbG", timers=(100, 200, 300)),
        S("rbG", timers=(100,)),
        S("G", reset=1, gtime=5.0, phase=1, start=1, timers=(500,)),
        S("bG", start=1, gtime=3.0, timers=(900,)),
        # GlareDist and the camera, and the glare off each edge.
        S("G", gtime=1.0, phase=1, dist=250.0, cam_pos=(-1.5, 2.5, 1e6),
          cam_dir=(0.25, -0.5, 0.75), timers=(4400,)),
        S("G", gtime=1.0, phase=1, dist=-0.0, timers=(4400,)),
        S("GG", gtime=1.0, phase=1, proj=[at(-300, 10), at(-400, 10)],
          timers=(4100,)),
        S("GG", gtime=1.0, phase=1, proj=[at(10, 767), at(10, 769)],
          timers=(4100,)),
        S("G", gtime=1.0, phase=1, proj=[at(10, 10, -2.0)],
          timers=(4100,)),
        S("G", gtime=1.0, phase=1, posx=7.0, posy=-7.0, timers=(4100,)),
        S("G", gtime=1.0, phase=1, layers=m, texmask=0x0d, timers=(4100,)),
        S("GG", gtime=1.0, phase=0, layers=m, ptimes=(1.0, 1.0, 1.0, 1.0),
          timers=(4400, 7000)),
        # The glare with no sun chunk, behind the view: both stop first.
        S("G", info=0, gtime=1.0, phase=1, proj=[at(10, 10, -1.0)],
          timers=(4100,)),
        # StuffSun with the glare on, both drawing, and for another view.
        S("bSSSS", layers=m, timers=(4000, 4100, 4300, 5000)),
        S("bSS", view_id=3, timers=(4000, 4100)),
        S("bS", info=0, proj=[at(10, 10, -1.0)], timers=(4000,)),
        # The whole of it, twice.
        # ePoly's constructor on its own.
        S("c"),
        S("SzbSSrSzS", layers=m, proj=[at(200, 100), at(0, 0),
                                       at(-35, 470), at(630, 5)],
          timers=(1000, 1100, 1300, 1400, 1500), seed=6, zb=(2, 30, 4, 28)),
    ]
    return sc


class Model(object):
    def __init__(self):
        self.out = []
        self.e = Emu(ieee=True)
        self.sc = None
        self.k = 0
        e = self.e
        e.stub(ROT_TRANS_PERS, self.rot_trans_pers)
        e.stub(MUL_VECTOR, self.mul_vector)
        e.stub(BSIN, self.bsin)
        e.stub(BCOS, self.bcos)
        e.stub(RENDER, self.render)
        e.stub(TRANSFER, self.transfer)

    def emit(self, s):
        self.out.append(s)

    def arg(self, i):
        return self.e.reg[4 + i] & M32

    def label(self, a):
        a &= M32
        names = {0: "null", VIEW: "view", RT: "rt", CAM: "cam", WV: "wv",
                 WS: "ws", INFO: "info"}
        if a in names:
            return names[a]
        for i in range(5):
            if a == TEX + 256 * i:
                return "t%d" % i
        if SUN_ZB <= a < SUN_ZB + 15 * ZB_SIZE and (a - SUN_ZB) % ZB_SIZE == 0:
            return "zb%d" % ((a - SUN_ZB) // ZB_SIZE)
        return "x%08x" % a

    def words(self, a, n):
        return " ".join("%08x" % self.e.u32(a + 4 * i) for i in range(n))

    # ---- the stubs ---------------------------------------------------------

    def proj(self):
        p = self.sc.proj
        return p[self.k % len(p)]

    def rot_trans_pers(self, em):
        o, mt, v = self.arg(0), self.arg(1), self.arg(2)
        self.emit("  eRotTransPers %s v %s" % (self.label(mt),
                                               self.words(v, 4)))
        p = self.proj()
        em.put32(o, p[0])
        em.put32(o + 4, p[1])
        em.put32(o + 8, fbits(0.5))
        em.put32(o + 12, fbits(1.0))

    def mul_vector(self, em):
        o, mt, v = self.arg(0), self.arg(1), self.arg(2)
        self.emit("  eMulVector %s v %s" % (self.label(mt), self.words(v, 4)))
        p = self.proj()
        em.put32(o, fbits(7.0))
        em.put32(o + 4, fbits(-7.0))
        em.put32(o + 8, p[2])
        em.put32(o + 12, fbits(1.0))
        self.k += 1

    def bsin(self, em):
        a = self.arg(0)
        self.emit("  bSin %d" % a)
        em.fpr[0] = fbits(float(s32(a) - 32768) / 32768.0)

    def bcos(self, em):
        a = self.arg(0)
        self.emit("  bCos %d" % a)
        em.fpr[0] = fbits(float((a * 7) & 0xffff) / 65536.0 - 0.5)

    def render(self, em):
        p, tex, flags = self.arg(0), self.arg(1), self.arg(2)
        e = self.e
        self.emit("  Render %s %d v %s uv %s c %s a %s %s" % (
            self.label(tex), s32(flags), self.words(p + 16, 16),
            self.words(p + 80, 12), bytes(e.mem[p + 128:p + 144]).hex(),
            " ".join(str(e.u8(p + 144 + i)) for i in range(9)),
            self.label(e.u32(p + 156))))

    def transfer(self, em):
        self.emit("  eTransferZBufferRect %s %d %d %d %d" % (
            self.label(self.arg(0)), s32(self.arg(1)), s32(self.arg(2)),
            s32(self.arg(3)), s32(self.e.reg[8] & M32)))

    # ---- the state ---------------------------------------------------------

    def dump(self):
        e = self.e
        self.emit("  = pos %08x %08x dist %08x start %d reset %d time %08x "
                  "phase %d timer %d info %s" % (
                      e.u32(SUN_POSX), e.u32(SUN_POSY), e.u32(GLARE_DIST),
                      s32(e.u32(START_GLARE)), s32(e.u32(RESET_GLARE)),
                      e.u32(GLARE_START), s32(e.u32(GLARE_PHASE)),
                      s32(e.u32(WORLD_TIMER)), self.label(e.u32(SUN_INFO))))
        self.emit("  zb " + " ".join(
            "%d,%d,%d,%d" % tuple(s32(e.u32(SUN_ZB + ZB_SIZE * b + 2048 + 4 * j))
                                  for j in range(4))
            for b in range(15)))

    def fill(self, seed):
        buf = bytearray()
        for b in range(15):
            buf = bytearray(struct.pack("<1024H", *(zvalue(b, k, seed)
                                                    for k in range(1024))))
            self.e.write(SUN_ZB + ZB_SIZE * b, bytes(buf))

    def ctor(self):
        """ePoly's constructor over 0xa5s, and the poly as it leaves it."""
        e = self.e
        e.write(POLY, bytes([0xa5]) * 160)
        e.call(EPOLY_CTOR, POLY, limit=10000)
        self.emit("  ePoly node %s v %s uv %s c %s a %s pad %s %s" % (
            bytes(e.mem[POLY:POLY + 16]).hex(), self.words(POLY + 16, 16),
            self.words(POLY + 80, 12), bytes(e.mem[POLY + 128:POLY + 144]).hex(),
            " ".join(str(e.u8(POLY + 144 + i)) for i in range(9)),
            bytes(e.mem[POLY + 153:POLY + 156]).hex(),
            self.label(e.u32(POLY + 156))))

    def reset(self, sc):
        e = self.e
        e.write(INFO, sc.rec)
        e.put32(SUN_INFO, INFO if sc.info else 0)
        for i in range(5):
            e.put32(SUN_TEX + 4 * i, TEX + 256 * i if sc.texmask >> i & 1
                    else 0)
        for i, a in enumerate((SUN_POSX, SUN_POSY, GLARE_DIST, START_GLARE,
                               RESET_GLARE, GLARE_START, GLARE_PHASE)):
            e.put32(a, sc.glare[i])
        for i in range(4):
            e.put32(PHASE_TIMES + 4 * i, sc.ptimes[i])
        self.seed = sc.seed
        self.fill(self.seed)
        for b in range(15):
            for j in range(4):
                e.put32(SUN_ZB + ZB_SIZE * b + 2048 + 4 * j, sc.zb[j])
        e.write(VIEW, bytes(128))
        e.put32(VIEW, sc.view_id)
        e.put32(VIEW + 48, RT)
        e.put32(VIEW + 56, CAM)
        e.put32(VIEW + 68, WV)
        e.put32(VIEW + 76, WS)
        e.write(RT, bytes(64))
        e.put32(RT, sc.rt_id)
        e.put32(RT + 28, sc.w)
        e.put32(RT + 32, sc.h)
        e.write(CAM, bytes(144))
        for i, c in enumerate(sc.cam):
            e.put32(CAM + 64 + 4 * i, c)
        self.k = 0
        self.t = 0

    def run(self, scenarios):
        e = self.e
        # The values no scenario sets: the glare's globals as the image
        # starts, and PhaseTimes.
        self.emit("initial times %s" % self.words(PHASE_TIMES, 4))
        self.sc = scenarios[0]
        self.dump()
        for n, sc in enumerate(scenarios):
            self.sc = sc
            self.reset(sc)
            self.emit("scenario %d %s" % (n, sc.ops))
            for o in sc.ops:
                self.emit(" %s" % o)
                if o in "SG":
                    t = sc.timers[self.t % len(sc.timers)]
                    self.t += 1
                    e.put32(WORLD_TIMER, t)
                    e.call(STUFF_SUN if o == "S" else STUFF_GLARE, VIEW,
                           limit=200000)
                elif o == "b":
                    e.put32(START_GLARE, 1)
                elif o == "r":
                    e.put32(RESET_GLARE, 1)
                elif o == "z":
                    self.seed += 1
                    self.fill(self.seed)
                elif o == "c":
                    self.ctor()
                self.dump()
        return self.out


def model(scenarios):
    return Model().run(scenarios)


# ================================================================ the build


def build_harness(tmp, name="sun_test"):
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


def encode(scenarios):
    return NL.join(l for s in scenarios for l in s.lines()) + NL


diff = pcc.diff

# ============================================================ the mutations

MUTATIONS = [
    # ePoly's constructor.
    ("ctor_z_0", EPH,
     "#define EPOLY_DEFAULT_Z 65535.0f", "#define EPOLY_DEFAULT_Z 0.0f"),
    ("ctor_w_1", EPC,
     "        p->Vertices[i].w = 0.0f;", "        p->Vertices[i].w = 1.0f;"),
    ("ctor_v1_x", EPC,
     "    p->Vertices[1].x = 64.0f;", "    p->Vertices[1].x = 0.0f;"),
    ("ctor_v2_y", EPC,
     "    p->Vertices[2].y = 64.0f;", "    p->Vertices[2].y = 0.0f;"),
    ("ctor_v3_y", EPC,
     "    p->Vertices[3].y = 64.0f;", "    p->Vertices[3].y = 32.0f;"),
    ("ctor_q_0", EPC,
     "        p->UVs[i][2] = 1.0f;", "        p->UVs[i][2] = 0.0f;"),
    ("ctor_colour_ff", EPC,
     "        p->Colours[i][0] = 0x80;", "        p->Colours[i][0] = 0xff;"),
    ("ctor_alpha_b_zero", EPC,
     "    p->AlphaB              = EPOLY_ALPHA_CD;",
     "    p->AlphaB              = EPOLY_ALPHA_ZERO;"),
    ("ctor_alpha_d_cs", EPC,
     "    p->AlphaD              = EPOLY_ALPHA_CD;",
     "    p->AlphaD              = EPOLY_ALPHA_CS;"),
    ("ctor_aspect_0", EPC,
     "    p->ApplyAspectRatio    = 1;", "    p->ApplyAspectRatio    = 0;"),
    ("ctor_flailer_1", EPC,
     "    p->Flailer             = 0;", "    p->Flailer             = 1;"),
    ("ctor_sun_1", EPC,
     "    p->SunPoly             = 0;", "    p->SunPoly             = 1;"),
    ("ctor_fix_64", EPC,
     "    p->AlphaFix            = 128;", "    p->AlphaFix            = 64;"),
    # The globals.
    ("glare_dist_0", SDC,
     "float   GlareDist = 1.0f;", "float   GlareDist = 0.0f;"),
    ("phase_time_2", SDC,
     "    0.05f, 0.2f, 0.65f, 5.0f", "    0.05f, 0.2f, 0.6f, 5.0f"),
    # The projection.
    ("proj_no_offset", SDC,
     "#define SCREEN_OFFSET 2048.0f", "#define SCREEN_OFFSET 2047.0f"),
    ("proj_half_h_for_x", SDC,
     "    *sx = (screen.x - SCREEN_OFFSET) + halfW;",
     "    *sx = (screen.x - SCREEN_OFFSET) + halfH;"),
    ("proj_override_x_only", SDC,
     "    if (SunPosX != 0.0f || SunPosY != 0.0f) {",
     "    if (SunPosX != 0.0f) {"),
    ("proj_override_both", SDC,
     "    if (SunPosX != 0.0f || SunPosY != 0.0f) {",
     "    if (SunPosX != 0.0f && SunPosY != 0.0f) {"),
    ("proj_override_y_swapped", SDC,
     "        *sy = SunPosY;", "        *sy = SunPosX;"),
    ("proj_behind_le", SDC,
     "    return !(eye.z < 0.0f);", "    return !(eye.z <= 0.0f);"),
    ("proj_behind_nan", SDC,
     "    return !(eye.z < 0.0f);", "    return eye.z >= 0.0f;"),
    ("proj_mul_first", SDC,
     "    eRotTransPers(&screen, view->WorldScreenMatrix, pos);\n"
     "    eMulVector4(&eye, view->WorldViewMatrix, pos);",
     "    eMulVector4(&eye, view->WorldViewMatrix, pos);\n"
     "    eRotTransPers(&screen, view->WorldScreenMatrix, pos);"),
    ("proj_wrong_matrix", SDC,
     "    eMulVector4(&eye, view->WorldViewMatrix, pos);",
     "    eMulVector4(&eye, view->WorldScreenMatrix, pos);"),
    # The largest CENTER, and the edges.
    ("center_any_texture", SDC,
     "        if (l->Texture == SUNTEX_CENTER && m < l->Size) {",
     "        if (m < l->Size) {"),
    ("center_halo", SDC,
     "        if (l->Texture == SUNTEX_CENTER && m < l->Size) {",
     "        if (l->Texture == SUNTEX_HALO && m < l->Size) {"),
    ("center_last_not_largest", SDC,
     "        if (l->Texture == SUNTEX_CENTER && m < l->Size) {",
     "        if (l->Texture == SUNTEX_CENTER) {"),
    ("center_five", SDC,
     "    for (i = 0; i < SUN_NUM_LAYERS; i++) {\n        const SunLayer *l = &info->SunLayers[i];\n\n        if (l->Texture == SUNTEX_CENTER",
     "    for (i = 0; i < SUN_NUM_LAYERS - 1; i++) {\n        const SunLayer *l = &info->SunLayers[i];\n\n        if (l->Texture == SUNTEX_CENTER"),
    ("edge_left_le", SDC,
     "    if (sx < -m || w + m < sx) {", "    if (sx <= -m || w + m < sx) {"),
    ("edge_right_no_m", SDC,
     "    if (sx < -m || w + m < sx) {", "    if (sx < -m || w < sx) {"),
    ("edge_top_no_m", SDC,
     "    if (sy < -m || h + m < sy) {", "    if (sy < 0.0f || h + m < sy) {"),
    ("edge_bottom_w", SDC,
     "    if (sy < -m || h + m < sy) {", "    if (sy < -m || w + m < sy) {"),
    # The count.
    ("count_le_64", SDC,
     "            if (zb->Buffer[y * SUN_ZBUFFER_SIZE + x] < SKY_Z) {",
     "            if (zb->Buffer[y * SUN_ZBUFFER_SIZE + x] <= SKY_Z) {"),
    ("count_signed", SDC,
     "            if (zb->Buffer[y * SUN_ZBUFFER_SIZE + x] < SKY_Z) {",
     "            if ((int16_t)zb->Buffer[y * SUN_ZBUFFER_SIZE + x] < SKY_Z) {"),
    ("count_transposed", SDC,
     "            if (zb->Buffer[y * SUN_ZBUFFER_SIZE + x] < SKY_Z) {",
     "            if (zb->Buffer[x * SUN_ZBUFFER_SIZE + y] < SKY_Z) {"),
    ("count_y_from_0", SDC,
     "    for (y = zb->StartY; y < zb->EndY; y++) {",
     "    for (y = 0; y < zb->EndY; y++) {"),
    ("count_x_to_32", SDC,
     "        for (x = zb->StartX; x < zb->EndX; x++) {",
     "        for (x = zb->StartX; x < SUN_ZBUFFER_SIZE; x++) {"),
    ("count_over_1023", SDC,
     "    count *= 1.0f / 1024.0f;", "    count *= 1.0f / 1023.0f;"),
    ("count_other_buffer", SDC,
     "    zb    = &SunZBuffers[rt->ID];", "    zb    = &SunZBuffers[view->ID];"),
    # The layers.
    ("layer_intensity_unchecked", SDC,
     "        if (tex == NULL || l->IntensityScale == 0.0f) {",
     "        if (tex == NULL) {"),
    ("layer_texture_unchecked", SDC,
     "        if (tex == NULL || l->IntensityScale == 0.0f) {",
     "        if (l->IntensityScale == 0.0f) {"),
    ("layer_half_size", SDC,
     "        draw_layer(&poly, l, tex, sx, sy, m, w + m, l->Size * 0.5f,\n",
     "        draw_layer(&poly, l, tex, sx, sy, m, w + m, l->Size,\n"),
    ("layer_span_no_m", SDC,
     "    frac  = (sx + m) / (span + m);", "    frac  = (sx + m) / span;"),
    ("layer_frac_no_m", SDC,
     "    frac  = (sx + m) / (span + m);", "    frac  = sx / (span + m);"),
    ("layer_angle_high_bits", SDC,
     "    angle = (uint16_t)((uint16_t)l->Angle\n",
     "    angle = (uint16_t)((uint16_t)(l->Angle >> 16)\n"),
    ("layer_sweep_32768", SDC,
     "                       + ee_trunc_w(l->SweepAngleAmount * frac * 65536.0f));",
     "                       + ee_trunc_w(l->SweepAngleAmount * frac * 32768.0f));"),
    ("layer_sweep_unsat", SDC,
     "                       + ee_trunc_w(l->SweepAngleAmount * frac * 65536.0f));",
     "                       + (int32_t)(int64_t)(l->SweepAngleAmount * frac * 65536.0f));"),
    ("layer_cos_first", SDC,
     "    s  = bSinBam(angle);\n    c  = bCosBam(angle);",
     "    c  = bCosBam(angle);\n    s  = bSinBam(angle);"),
    ("layer_sin_cos_swapped", SDC,
     "    hc = half * c;\n    hs = half * s;",
     "    hc = half * s;\n    hs = half * c;"),
    ("layer_b_sum", SDC,
     "    b  = hc - hs;", "    b  = hc + hs;"),
    ("layer_a_diff", SDC,
     "    a  = hs + hc;", "    a  = hs - hc;"),
    ("layer_negative_counted", SDC,
     "        alpha = -intensity * 128.0f;",
     "        alpha = fade * (-intensity * 128.0f);"),
    ("layer_negative_kept", SDC,
     "    if (intensity < 0.0f) {", "    if (intensity < -1e30f) {"),
    ("layer_alpha_uncounted", SDC,
     "        alpha = fade * (intensity * 128.0f);",
     "        alpha = intensity * 128.0f;"),
    ("layer_alpha_255", SDC,
     "        alpha = fade * (intensity * 128.0f);",
     "        alpha = fade * (intensity * 255.0f);"),
    ("layer_alpha_clamped", SDC,
     "    ab = (uint8_t)ee_trunc_w(alpha);",
     "    ab = (uint8_t)(ee_trunc_w(alpha) > 255 ? 255 : ee_trunc_w(alpha));"),
    ("layer_no_zero_add", SDC,
     "    cx = (sx + 0.0f) + l->OffsetX;", "    cx = sx + l->OffsetX;"),
    ("layer_offset_swapped", SDC,
     "    cy = (sy + 0.0f) + l->OffsetY;", "    cy = (sy + 0.0f) + l->OffsetX;"),
    ("layer_colour_alpha_kept", SDC,
     "        p->Colours[i][3] = ab;", "        p->Colours[i][3] = l->Colour[3];"),
    ("layer_colour_bgr", SDC,
     "        p->Colours[i][0] = l->Colour[0];", "        p->Colours[i][0] = l->Colour[2];"),
    ("layer_first_colour_only", SDC,
     "    for (i = 0; i < 4; i++) {\n        p->Colours[i][0]",
     "    for (i = 0; i < 1; i++) {\n        p->Colours[i][0]"),
    ("layer_v0_y", SDC,
     "    p->Vertices[0].y = cy - b;", "    p->Vertices[0].y = cy - a;"),
    ("layer_v1_x", SDC,
     "    p->Vertices[1].x = cx + b;", "    p->Vertices[1].x = cx - b;"),
    ("layer_v2", SDC,
     "    p->Vertices[2].x = cx + a;\n    p->Vertices[2].y = cy + b;",
     "    p->Vertices[2].x = cx + b;\n    p->Vertices[2].y = cy + a;"),
    ("layer_v3_y", SDC,
     "    p->Vertices[3].y = cy + a;", "    p->Vertices[3].y = cy + b;"),
    ("layer_add_is_blend", SDC,
     "    p->AlphaB  = l->AlphaType == SUNALPHA_BLEND ? EPOLY_ALPHA_CD\n"
     "                                                : EPOLY_ALPHA_ZERO;",
     "    p->AlphaB  = EPOLY_ALPHA_CD;"),
    ("layer_add_cs", SDC,
     "                                                : EPOLY_ALPHA_ZERO;",
     "                                                : EPOLY_ALPHA_CS;"),
    ("layer_d_zero", SDC,
     "    p->AlphaD  = EPOLY_ALPHA_CD;", "    p->AlphaD  = EPOLY_ALPHA_ZERO;"),
    ("layer_no_sunpoly", SDC,
     "    p->SunPoly = 1;\n", ""),
    ("layer_flags_1", SDC,
     "        gEPolyRenderFn(p, tex, 0);", "        gEPolyRenderFn(p, tex, 1);"),
    ("layer_five", SDC,
     "    begin_poly(&poly);\n    for (i = 0; i < SUN_NUM_LAYERS; i++) {\n        const SunLayer *l   = &info->SunLayers[i];\n        TextureInfo    *tex = SunTextures[l->Texture];\n\n        if (tex == NULL || l->IntensityScale",
     "    begin_poly(&poly);\n    for (i = 0; i < SUN_NUM_LAYERS - 1; i++) {\n        const SunLayer *l   = &info->SunLayers[i];\n        TextureInfo    *tex = SunTextures[l->Texture];\n\n        if (tex == NULL || l->IntensityScale"),
    ("poly_enabled_0", SDC,
     "    p->AlphaEnabled = 1;", "    p->AlphaEnabled = 0;"),
    ("poly_fix_128", SDC,
     "    p->AlphaFix     = 64;", "    p->AlphaFix     = 128;"),
    ("poly_uv_flipped", SDC,
     "    p->UVs[3][1]    = 1.0f;", "    p->UVs[3][1]    = 0.0f;"),
    # The rect for the next frame.
    ("rect_no_transfer", SDC,
     "        gETransferZBufferRectFn((uint8_t *)zb, x0, y0, SUN_ZBUFFER_SIZE,\n"
     "                                SUN_ZBUFFER_SIZE);\n", ""),
    ("rect_xy_swapped", SDC,
     "        gETransferZBufferRectFn((uint8_t *)zb, x0, y0, SUN_ZBUFFER_SIZE,",
     "        gETransferZBufferRectFn((uint8_t *)zb, y0, x0, SUN_ZBUFFER_SIZE,"),
    ("rect_centre_15", SDC,
     "    x0 = ee_trunc_w(sx - 16.0f);", "    x0 = ee_trunc_w(sx - 15.0f);"),
    ("rect_rounded", SDC,
     "    y0 = ee_trunc_w(sy - 16.0f);", "    y0 = ee_trunc_w(sy - 15.5f);"),
    ("rect_start_x_kept_0", SDC,
     "    zb->StartX = x0 < 0 ? (int32_t)(0u - (uint32_t)x0) : 0;",
     "    zb->StartX = 0;"),
    ("rect_start_y_x", SDC,
     "    zb->StartY = y0 < 0 ? (int32_t)(0u - (uint32_t)y0) : 0;",
     "    zb->StartY = x0 < 0 ? (int32_t)(0u - (uint32_t)x0) : 0;"),
    ("rect_end_x_le", SDC,
     "    zb->EndX   = sw < x ?", "    zb->EndX   = sw <= x ?"),
    ("rect_end_y_w", SDC,
     "    zb->EndY   = sh < y ? (int32_t)(SUN_ZBUFFER_SIZE - ((uint32_t)y\n"
     "                                                       - (uint32_t)sh))",
     "    zb->EndY   = sw < y ? (int32_t)(SUN_ZBUFFER_SIZE - ((uint32_t)y\n"
     "                                                       - (uint32_t)sw))"),
    ("rect_end_x_32", SDC,
     "                        : SUN_ZBUFFER_SIZE;\n    zb->StartY",
     "                        : SUN_ZBUFFER_SIZE - 1;\n    zb->StartY"),
    # The views.
    ("stuff_any_view", SDC,
     "    if (info == NULL || view->ID != EVIEW_ID_PLAYER1) {",
     "    if (info == NULL) {"),
    ("stuff_glare_after", SDC,
     "    StuffSunGlare(view);\n    info = SunInfo;\n"
     "    if (info == NULL || view->ID != EVIEW_ID_PLAYER1) {\n        return;\n    }",
     "    info = SunInfo;\n"
     "    if (info == NULL || view->ID != EVIEW_ID_PLAYER1) {\n        return;\n    }\n"
     "    StuffSunGlare(view);"),
    ("stuff_no_glare", SDC,
     "    StuffSunGlare(view);\n    info = SunInfo;", "    info = SunInfo;"),
    # The glare.
    ("glare_reset_keeps_start", SDC,
     "        GlareStartTime = 0.0f;\n        bStartGlare    = 0;\n        bResetGlare    = 0;",
     "        GlareStartTime = 0.0f;\n        bResetGlare    = 0;"),
    ("glare_reset_kept", SDC,
     "        bStartGlare    = 0;\n        bResetGlare    = 0;\n    }",
     "        bStartGlare    = 0;\n    }"),
    ("glare_reset_keeps_time", SDC,
     "    if (bResetGlare) {\n        GlareStartTime = 0.0f;\n",
     "    if (bResetGlare) {\n"),
    ("glare_start_at_0", SDC,
     "        if (0.0f < t && start == 0.0f) {", "        if (0.0f <= t && start == 0.0f) {"),
    ("glare_start_restarts", SDC,
     "        if (0.0f < t && start == 0.0f) {", "        if (0.0f < t) {"),
    ("glare_start_keeps_flag", SDC,
     "            start          = t;\n            bStartGlare    = 0;\n",
     "            start          = t;\n"),
    ("glare_start_keeps_phase", SDC,
     "            GlareStartTime = t;\n            iGlarePhase    = 0;\n",
     "            GlareStartTime = t;\n"),
    ("glare_start_ms", SDC,
     "#define GLARE_START_SECONDS 0.00025f", "#define GLARE_START_SECONDS 0.001f"),
    ("glare_now_ms", SDC,
     "#define GLARE_NOW_SECONDS   0.00025f", "#define GLARE_NOW_SECONDS   0.001f"),
    ("glare_off_runs", SDC,
     "    if (start == 0.0f) {\n        return;\n    }\n", ""),
    ("glare_advance_le", SDC,
     "    if (PhaseTimes[phase] < el) {", "    if (PhaseTimes[phase] <= el) {"),
    ("glare_advance_keeps_el", SDC,
     "        el -= PhaseTimes[phase];\n", ""),
    ("glare_advance_keeps_time", SDC,
     "        GlareStartTime = now;\n        phase = ", "        phase = "),
    ("glare_advance_no_wrap", SDC,
     "        phase = (int32_t)((uint32_t)phase + 1u) % NUM_GLARE_PHASES;",
     "        phase = (int32_t)((uint32_t)phase + 1u);"),
    ("glare_advance_unstored", SDC,
     "        iGlarePhase = phase;\n", ""),
    ("glare_grow_by_1", SDC,
     "        size  = el / PhaseTimes[0];", "        size  = el / PhaseTimes[1];"),
    ("glare_hold_half", SDC,
     "    case 1:\n        alpha = 1.0f;\n        size  = 1.0f;",
     "    case 1:\n        alpha = 0.5f;\n        size  = 1.0f;"),
    ("glare_fade_size", SDC,
     "        size  = 1.0f;\n        alpha = 1.0f - el / PhaseTimes[2];",
     "        size  = 1.0f - el / PhaseTimes[2];\n        alpha = 1.0f;"),
    ("glare_end_keeps_time", SDC,
     "        alpha          = 0.0f;\n        GlareStartTime = 0.0f;\n",
     "        alpha          = 0.0f;\n"),
    ("glare_size_2", SDC,
     "#define GLARE_SIZE 1.9f", "#define GLARE_SIZE 2.0f"),
    ("glare_no_dist", SDC,
     "    pos.y = cam->CurrentKey.Direction.y * GlareDist\n",
     "    pos.y = cam->CurrentKey.Direction.y\n"),
    ("glare_target", SDC,
     "    pos.z = cam->CurrentKey.Direction.z * GlareDist\n          + cam->CurrentKey.Position.z;",
     "    pos.z = cam->CurrentKey.Target.z;"),
    ("glare_w_0", SDC,
     "    pos.w = 1.0f;\n    size *= GLARE_SIZE;", "    pos.w = 0.0f;\n    size *= GLARE_SIZE;"),
    ("glare_halves_swapped", SDC,
     "    halfW = (float)(rt->ScissorW >> 1);\n    halfH = (float)(rt->ScissorH >> 1);\n    pos.x",
     "    halfW = (float)(rt->ScissorH >> 1);\n    halfH = (float)(rt->ScissorW >> 1);\n    pos.x"),
    ("glare_size_unchecked", SDC,
     "        if (tex == NULL || size == 0.0f) {", "        if (tex == NULL) {"),
    ("glare_half_unscaled", SDC,
     "        draw_layer(&poly, l, tex, sx, sy, m, w + m, l->Size * 0.5f * size,",
     "        draw_layer(&poly, l, tex, sx, sy, m, w + m, l->Size * 0.5f,"),
    ("glare_intensity", SDC,
     "                   size, alpha);", "                   l->IntensityScale, alpha);"),
    ("glare_alpha_unused", SDC,
     "                   size, alpha);", "                   size, 1.0f);"),
    ("glare_edge_h", SDC,
     "    if (!on_target(sx, sy, m, w, h)) {\n        return;\n    }\n\n    begin_poly(&poly);\n    for (i = 0; i < SUN_NUM_LAYERS; i++) {\n        const SunLayer *l   = &info->SunLayers[i];\n        TextureInfo    *tex = SunTextures[l->Texture];\n\n        if (tex == NULL || size",
     "    if (!on_target(sx, sy, m, w, w)) {\n        return;\n    }\n\n    begin_poly(&poly);\n    for (i = 0; i < SUN_NUM_LAYERS; i++) {\n        const SunLayer *l   = &info->SunLayers[i];\n        TextureInfo    *tex = SunTextures[l->Texture];\n\n        if (tex == NULL || size"),
]

# Mutations that survive because they change nothing the image can tell.
EQUIVALENT = {
    # A rect that ends at the target's edge exactly is 32 - 0 across either
    # way.
    "rect_end_x_le",
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    base = model(sc)
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

    for m in todo:
        name, rel, before, after = m
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if text.count(probe) != 1:
            missing.append(name)
            print("  %-44s PATTERN %s" % (
                name, "NOT FOUND" if not text.count(probe) else "NOT UNIQUE"))
            continue
        new = text.replace(probe, repl, 1)
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

    sc = script()
    lines = model(sc)
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
    print("%d scenarios, %d lines, %d differ" % (len(sc), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
