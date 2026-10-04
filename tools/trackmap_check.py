#!/usr/bin/env python3
"""Cross-check 3DS Files/source/trackmap.c, the minimap's first part (step
8m-6a), against the retail image, SLES_507.31.

**The model** is retail's own: InitTrackMapModeInfo (0x001bd1f8), the
constructor (0x001babb8), GetAngle (0x001bb678) with EvalCubic
(0x001bdad0), GetCameraDirection (0x001bd0b0), GetCarUVPosition
(0x001bca50) and GetBoxOnMap (0x001bcae8), with bSPrintf, bStringHash and
the matrix code under them run as they are. The harness
(tools/src/trackmap_test.c) runs trackmap.c over emath.c and bmath.c.

**The stubs** are GetTextureInfo (0x001abf48), which answers each of the
seven names from a mask, and eGetView (0x00107c90), which answers the one
view. Both log their calls. WorldTimer, pCurrentRace's RaceStage and
TheRaceParameters.Point2Point are set in memory.

**Compared**, after each op, are the map's fields by name, its pointers
by what they point at; the two tables after InitTrackMapModeInfo, field
by field (the padding is left out: retail never writes it); and what each
call answers.

**The script** builds the tables over a pattern; constructs with each of
the three pointers missing, every texture mask with and without
Point2Point, and a spread of track numbers, rotations and times; takes
points to the map under several calibrations and hand-set matrices; turns
boxes; runs EvalCubic alone; asks the camera's direction with no mover,
other movers and the drive camera, each race stage, look backs and eased
directions about the 0.001 test; and eases GetAngle through a turning
camera and every mode, with time steps from none to a wrap.

    python tools/trackmap_check.py
    python tools/trackmap_check.py --mutate [--only a,b]
    python tools/trackmap_check.py --dump out/trackmap
"""
import argparse
import math
import os
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flailer_check as fc              # noqa: E402
import hostbuild                        # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from bhash import bhash                 # noqa: E402
from mipsemu import M32                 # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/trackmap_test.c"
TRACKMAP = "3DS Files/source/trackmap.c"
SOURCES = [HARNESS, TRACKMAP] + ["3DS Files/source/" + f for f in (
    "emath.c", "bmatrix.c", "bvector.c", "bmath.c", "bmathtab.c",
    "bprintf.c", "bmem.c")]

F_INIT = 0x001bd1f8
F_CTOR = 0x001babb8
F_ANGLE = 0x001bb678
F_CAMDIR = 0x001bd0b0
F_UV = 0x001bca50
F_BOX = 0x001bcae8
F_CUBIC = 0x001bdad0
EMATH_INIT = 0x0011b138
EMATH_SINIT = 0x0011bf70                # 0x002dc400 = (0, 0, 0, 1)
S_TEXINFO = 0x001abf48
S_GETVIEW = 0x00107c90

MODES = 0x003140b8
COLOURS = 0x003143a8
GP = 0x003358f0
WORLD_TIMER = GP - 19576
CURRENT_RACE = GP - 22272
POINT2POINT = 0x0031a8c0

MAP_SIZE = 176
TEX_NAMES = ["TRACK%d_MAP", "CAR_MARKER", "CAR_MARKERB", "TRACKMAPFRAME",
             "MAPBACK", "START_LINE", "BKGBMP"]


def F(v):
    return "%#x" % struct.unpack("<I", struct.pack("<f", v))[0]


def s8(v):
    return v - 256 if v & 0x80 else v


def s32(v):
    v &= M32
    return v - (1 << 32) if v & 0x80000000 else v


# ================================================================== script

def scenario_tables():
    # The tables over a pattern, then again by the constructor.
    return ["fillmodes", "init", "fillmodes", "track|3", "cal|0|0|%s|0"
            % F(100.0), "ctor|1|1|1", "tables"]


def scenario_ctor():
    s = ["track|3", "cal|%s|%s|%s|0x1234" % (F(-1200.5), F(830.25),
                                              F(2400.0)),
         "world|5000"]
    # Each pointer missing.
    for t in (0, 1):
        for c in (0, 1):
            for p in (0, 1):
                s += ["fill", "ctor|%d|%d|%d" % (t, c, p)]
    # Every texture mask, a loop and a point to point.
    for p2p in (0, 1):
        s += ["p2p|%d" % p2p]
        for m in range(128):
            s += ["fill", "mask|%d" % m, "ctor|1|1|1"]
    s += ["mask|0"]
    for p2p in (2, -1, 0x100, 0):
        s += ["p2p|%#x" % (p2p & M32), "mask|0x20", "fill", "ctor|1|1|1"]
    s += ["mask|0"]
    # Track numbers, an int8 printed signed.
    for n in (-128, -1, 0, 1, 9, 10, 15, 99, 127):
        s += ["track|%#x" % (n & 0xff), "fill", "ctor|1|1|1"]
    s += ["track|3"]
    # Rotations and times.
    for r in (0, 1, 0x4000, 0x8000, 0xc000, 0xffff, 0x1234, 0xd5da, 0x7fff):
        s += ["cal|0|0|%s|%#x" % (F(100.0), r), "fill", "ctor|1|1|1"]
    for w in (0, 1, 0x7fffffff, 0x80000000, 0xffffffff):
        s += ["world|%#x" % w, "fill", "ctor|1|1|1"]
    # A second construction over a used map.
    s += ["world|77", "ctor|1|1|1", "f|0|%s" % F(0.5), "f|164|2",
          "ctor|1|1|1", "ctor|0|1|1"]
    return s


CALS = [
    (0.0, 0.0, 100.0, 0),
    (-1200.5, 830.25, 2400.0, 0x1234),
    (512.0, -256.0, 1024.0, 0x4000),
    (-3000.0, 3000.0, 6000.0, 0x8000),
    (13.7, -91.3, 0.75, 0xd5da),
    (1e5, -1e5, 3.0e5, 0xffff),
    (-0.0, 0.0, -50.0, 0xc000),
]

POINTS = [
    (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (-1200.5, 830.25, 7.0),
    (1199.5, -1569.75, -3.0), (100.0, -50.0, 0.0), (-250.0, 125.5, 10.0),
    (3.14159, 2.71828, 1.41421), (1e6, -1e6, 0.0), (-0.0, -0.0, -0.0),
    (512.0, -256.0, 1.0), (1536.0, -1280.0, 0.0), (-17.25, 1e-3, 5.5),
]


def scenario_uv():
    s = []
    for x, y, w, r in CALS:
        s += ["cal|%s|%s|%s|%#x" % (F(x), F(y), F(w), r), "ctor|1|1|1"]
        for p in POINTS:
            s += ["uv|%s|%s|%s" % tuple(F(v) for v in p)]
    # Hand-set matrices: every row, the translation's too, reaches the
    # answer through z = 1 and w = 1.
    s += ["cal|%s|%s|%s|0" % (F(-1200.5), F(830.25), F(2400.0)),
          "ctor|1|1|1"]
    vals = [0.5, -1.25, 2.0, 0.125, 3.0, -0.75, 1.5, 0.0625, -2.5, 0.375,
            4.0, -0.875, 0.25, 7.0, -3.5, 1.0]
    for k in range(16):
        s += ["f|%d|%s" % (32 + 4 * k, F(vals[k]))]
    for p in POINTS[:6]:
        s += ["uv|%s|%s|%s" % tuple(F(v) for v in p)]
    for k in range(16):
        s += ["f|%d|%s" % (32 + 4 * k, F(vals[(k * 7 + 3) % 16] * 1.5))]
        s += ["uv|%s|%s|%s" % (F(10.0), F(-20.0), F(3.0))]
    return s


def scenario_box():
    s = ["cal|0|0|%s|0" % F(100.0), "ctor|1|1|1"]
    boxes = [
        (0.0, 0.0, 1.0, 2.0, 3.0, 4.0),
        (0.5, 0.25, 0.1, 0.05, 0.02, 0.03),
        (-0.3, 0.7, 0.441781, 0.202055, 0.2, 0.2),
        (10.0, -20.0, -1.0, -2.0, -3.0, -4.0),
        (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        (1e4, -1e4, 250.0, 125.0, 62.5, 31.25),
        (-0.0, -0.0, 0.33, 0.33, 0.165, 0.165),
    ]
    for b in boxes:
        for a in (0, 1, 0x2000, 0x4000, 0x8000, 0xc000, 0xffff, 0x1234,
                  0xd5da, 0x5555):
            s += ["box|%s|%s|%s|%s|%s|%s|%#x"
                  % (tuple(F(v) for v in b) + (a,))]
    return s


def scenario_cubic():
    s = []
    for x, v, t, dt in [
            (0.0, 0.0, 1.0, 0.5), (1.0, 0.0, 0.0, 1.0),
            (0.3, -0.2, 0.9, 0.0225), (-1.0, 2.0, 3.0, 0.0),
            (0.5, 0.5, 0.5, 0.25), (0.0, 1.0, 0.0, 2.0),
            (-0.7071, 0.31, 0.7071, 0.0297), (2.5, -3.5, -1.25, 10.0),
            (0.1, 0.2, 0.3, -0.5), (1e3, -1e3, 5e2, 0.9),
            (0.0, 0.0, 0.0, 0.0), (-0.0, -0.0, -0.0, 1.0),
            (0.99, 0.01, -0.99, 0.0009), (3.0, 7.0, -11.0, 1.5)]:
        s += ["cubic|%s|%s|%s|%s" % (F(x), F(v), F(t), F(dt))]
    return s


def scenario_camdir():
    s = ["cal|0|0|%s|0" % F(100.0), "world|1000", "fill", "ctor|1|1|1",
         "body|%s|%s" % (F(0.6), F(-0.8))]
    # No mover, by race stage.
    s += ["mover|-"]
    for st in (0, 1, 3, 4, 5, 6, -1):
        s += ["stage|%#x" % (st & M32), "dir"]
    s += ["f|0|%s" % F(0.25), "f|4|%s" % F(-0.5)]
    for st in (3, 4, 5):
        s += ["stage|%d" % st, "dir"]
    # Other movers.
    for t in (0, 2, 4, 5, 6, 7, 17, -1, 0x101):
        s += ["mover|%#x" % (t & M32)]
        for st in (3, 4):
            s += ["stage|%d" % st, "dir"]
    # The drive camera, its look back, and the ease's start.
    s += ["mover|1", "stage|4"]
    for vid in (0, 1, 3):
        s += ["view|%d" % vid, "dir"]
    s += ["view|0"]
    dirs = [(0.0, 1.0, 0.0), (0.6, 0.8, 0.0), (-0.28, 0.96, 0.05),
            (0.7071, -0.7071, -0.1), (0.0, 0.0, 1.0), (-1.0, 0.0, 0.0),
            (0.12, -0.34, 0.93)]
    for d in dirs:
        s += ["camdir|%s|%s|%s" % tuple(F(v) for v in d)]
        for lb in (0, 0x8000, 0x4000, 0xc000, 0x1234, 0xffff):
            s += ["lookback|%#x" % lb, "f|0|0", "f|4|0", "world|2000",
                  "dir", "world|3000", "dir"]
    s += ["lookback|0", "camdir|%s|%s|%s" % (F(0.6), F(0.8), F(0.0))]
    edge = [0.0, -0.0, 0.001, -0.001, 0.0010001, -0.0010001, 0.00099,
            0.5, -2.0]
    w = 4000
    for x in edge:
        for y in edge:
            w += 7
            s += ["f|0|%s" % F(x), "f|4|%s" % F(y), "f|16|0",
                  "world|%d" % w, "dir"]
    return s


def scenario_angle():
    s = ["fillmodes", "init", "cal|0|0|%s|0" % F(100.0), "world|0",
         "fill", "ctor|1|1|1", "mover|1", "stage|4", "lookback|0",
         "camdir|%s|%s|%s" % (F(0.0), F(1.0), F(0.0))]
    # Each mode, with and without rotation.
    for m in range(11):
        s += ["f|164|%d" % m, "world|%d" % (100 * m), "angle"]
    # The camera turning a whole circle, a frame at a time.
    s += ["f|164|0", "f|0|0", "f|4|0", "f|8|0", "f|12|0", "world|10000"]
    w = 10000
    for k in range(80):
        a = k * 2 * math.pi / 60.0
        w += 33
        s += ["camdir|%s|%s|%s" % (F(math.cos(a)), F(math.sin(a)), F(0.1)),
              "world|%d" % w, "angle"]
    # Looking back, then the other modes' rotation.
    s += ["lookback|0x8000"]
    for k in range(10):
        w += 17
        s += ["world|%d" % w, "angle"]
    s += ["lookback|0", "f|164|2"]
    for k in range(10):
        w += 50
        s += ["world|%d" % w, "angle"]
    s += ["f|164|10"]
    for k in range(5):
        w += 100
        s += ["world|%d" % w, "angle"]
    # Time steps: none, one, long, backward, each from a settled ease. The
    # longest a 32-bit WorldTimer can hold, once: in one step the ease
    # stays finite (about 2e17), and only steps of hours, one after the
    # other, reach the infinity the EE would have saturated.
    settle = ["f|0|%s" % F(0.6), "f|4|%s" % F(0.8), "f|8|%s" % F(0.01),
              "f|12|%s" % F(-0.02)]
    for dw in (0, 1, 4000, 100000, -33, -100000, 0x7fffffff, -0x7fffffff,
               0x80000000):
        s += settle + ["f|16|%#x" % w]
        w = (w + dw) & M32
        s += ["world|%#x" % w, "angle"]
    # WorldTimer wraps past PreviousTime.
    s += settle + ["f|16|0xffffffe0", "world|0x10", "angle",
                   "world|0x31", "angle"]
    w = 0x31
    # Big speeds, and the ease from far off.
    s += ["f|0|%s" % F(-1.0), "f|4|%s" % F(0.0), "f|8|%s" % F(5.0),
          "f|12|%s" % F(-7.5), "f|16|%#x" % w]
    for k in range(6):
        w = (w + 40) & M32
        s += ["world|%#x" % w, "angle"]
    # The ease starts with a speed: the start sets PreviousTime, so that
    # step is t = 0 and the speed does not move it.
    w = (w + 500) & M32
    s += ["camdir|%s|%s|%s" % (F(0.6), F(0.8), F(0.0)), "f|0|0", "f|4|0",
          "f|8|%s" % F(0.5), "f|12|%s" % F(-0.3), "world|%#x" % w, "angle"]
    w = (w + 33) & M32
    s += ["world|%#x" % w, "angle"]
    # No drive camera: the eased direction while racing, the car's before.
    s += ["mover|4"]
    for k in range(4):
        w = (w + 33) & M32
        s += ["world|%#x" % w, "angle"]
    s += ["stage|3", "body|%s|%s" % (F(-0.6), F(0.8))]
    for k in range(4):
        w = (w + 33) & M32
        s += ["world|%#x" % w, "angle"]
    s += ["mover|-", "stage|4", "world|%#x" % ((w + 33) & M32), "angle"]
    # Every mode turns while the table is the pattern.
    s += ["fillmodes", "mover|1"]
    for m in (1, 3, 4, 6):
        w = (w + 33) & M32
        s += ["f|164|%d" % m, "world|%#x" % w, "angle"]
    s += ["init"]
    return s


def script():
    s = []
    s += scenario_tables()
    s += scenario_ctor()
    s += scenario_uv()
    s += scenario_box()
    s += scenario_cubic()
    s += scenario_camdir()
    s += scenario_angle()
    return s


# =================================================================== model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        e.stub_bware()
        # The emulator runs no static constructors, and eMulVector adds its
        # vector into the (0, 0, 0, 1) at 0x002dc400 that the one at
        # 0x0011bf70 writes. eInit runs eMathInit at boot.
        e.call(EMATH_INIT, limit=10000)
        e.call(EMATH_SINIT, limit=1000)
        self.map = e.alloc(MAP_SIZE, align=16)
        self.track = e.alloc(176, align=16)
        self.car = e.alloc(2400, align=16)
        self.player = e.alloc(256, align=16)
        self.view = e.alloc(256, align=16)
        self.camera = e.alloc(128, align=16)
        self.mover = e.alloc(256, align=16)
        self.race = e.alloc(16, align=16)
        self.texs = [e.alloc(16, align=16) for _ in TEX_NAMES]
        self.scratch = e.alloc(64, align=16)
        for a, n in ((self.track, 176), (self.car, 2400),
                     (self.player, 256), (self.view, 256),
                     (self.camera, 128), (self.mover, 256),
                     (self.race, 16)):
            e.write(a, bytes(n))
        e.put32(self.view + 60, self.view + 60)
        e.put32(self.view + 64, self.view + 60)
        e.put32(self.mover + 24, self.camera)
        e.put32(CURRENT_RACE, self.race)
        e.put32(WORLD_TIMER, 0)
        e.put32(POINT2POINT, 0)
        self.mask = 0
        self.last = None
        self.names = {self.track: "track", self.car: "car",
                      self.player: "player"}
        for i, a in enumerate(self.texs):
            self.names[a] = "tex%d" % i
        e.stub(S_TEXINFO, self.s_texinfo)
        e.stub(S_GETVIEW, self.s_getview)
        self.fill()

    def emit(self, s):
        self.out.append(s)

    # ---- stubs

    def tex_name(self, h):
        n = "TRACK%d_MAP" % s8(self.e.mem[self.track + 65])
        if bhash(n) == h:
            return 0, n
        for i in range(1, len(TEX_NAMES)):
            if bhash(TEX_NAMES[i]) == h:
                return i, TEX_NAMES[i]
        return -1, "%08x" % h

    def s_texinfo(self, em):
        h, d, u = (em.reg[i] & M32 for i in (4, 5, 6))
        i, n = self.tex_name(h)
        self.emit("  texinfo %s %d %d" % (n, s32(d), s32(u)))
        if i < 0 or (self.mask >> i) & 1:
            return 0
        return self.texs[i]

    def s_getview(self, em):
        self.emit("  view %d" % s32(em.reg[4]))
        return self.view

    # ---- output

    def ptr(self, off, w):
        if w == 0:
            return "0"
        if w == (0xa5000000 + off) & M32:
            return "junk"
        return self.names.get(w, "?%08x" % w)

    def dump(self):
        e = self.e
        u = lambda o: e.u32(self.map + o)      # noqa: E731
        parts = ["%08x" % u(o) for o in (0, 4, 8, 12, 16)] + ["m"]
        parts += ["%08x" % u(o) for o in range(32, 96, 4)] + ["t"]
        parts += [self.ptr(o, u(o)) for o in range(96, 132, 4)]
        parts += [self.ptr(o, u(o)) for o in (132, 136, 140, 144)]
        parts += ["%08x" % u(148), "%08x" % u(152)]
        parts += ["%d" % s32(u(o)) for o in (156, 160, 164)]
        line = "  map " + " ".join(parts)
        if line != self.last:
            self.last = line
            self.emit(line)

    def dump_tables(self):
        e = self.e
        for k in range(11):
            r = e.read(MODES + 68 * k, 68)
            H = lambda o: struct.unpack_from("<H", r, o)[0]   # noqa: E731
            h = lambda o: struct.unpack_from("<h", r, o)[0]   # noqa: E731
            W = lambda o: "%08x" % struct.unpack_from("<I", r, o)[0]  # noqa
            self.emit("  mode %d %04x %s %d %d %s %s %d %d %s %s %s %s %d "
                      "%s %s %s %d %d %d %s %d %d"
                      % (k, H(0), W(4), h(8), h(10), W(12), W(16), h(20),
                         h(22), W(24), W(28), W(32), W(36), r[40], W(44),
                         W(48), W(52), r[56], r[57], r[58], W(60), r[64],
                         r[65]))
        c = e.read(COLOURS, 27)
        for k in range(9):
            self.emit("  colour %d %d %d %d" % ((k,) + tuple(c[3 * k:3 * k + 3])))

    # ---- ops

    def fill(self):
        for o in range(0, MAP_SIZE, 4):
            self.e.put32(self.map + o, 0xa5000000 + o)

    def op(self, a):
        e = self.e
        o = a[0]
        v = lambda i: int(a[i], 0) & M32      # noqa: E731
        tables = False
        if o == "fill":
            self.fill()
        elif o == "fillmodes":
            e.write(MODES, b"\xaa" * (68 * 11))
            e.write(COLOURS, b"\xaa" * 27)
            tables = True
        elif o == "init":
            e.call(F_INIT, self.map, limit=100000)
            tables = True
        elif o == "tables":
            tables = True
        elif o == "ctor":
            e.call(F_CTOR, self.map, self.track if v(1) else 0,
                   self.car if v(2) else 0, self.player if v(3) else 0,
                   limit=1000000)
        elif o == "mask":
            self.mask = v(1)
        elif o == "p2p":
            e.put32(POINT2POINT, v(1))
        elif o == "track":
            e.mem[self.track + 65] = v(1) & 0xff
        elif o == "cal":
            e.put32(self.track + 92, v(1))
            e.put32(self.track + 96, v(2))
            e.put32(self.track + 100, v(3))
            e.write(self.track + 104, struct.pack("<H", v(4) & 0xffff))
        elif o == "world":
            e.put32(WORLD_TIMER, v(1))
        elif o == "stage":
            e.put32(self.race, v(1))
        elif o == "view":
            e.put32(self.player + 24, v(1))
        elif o == "mover":
            if a[1] == "-":
                e.put32(self.view + 60, self.view + 60)
            else:
                e.put32(self.view + 60, self.mover)
                e.put32(self.mover + 8, v(1))
        elif o == "camdir":
            for k in range(3):
                e.put32(self.camera + 80 + 4 * k, v(1 + k))
        elif o == "lookback":
            e.write(self.mover + 140, struct.pack("<H", v(1) & 0xffff))
        elif o == "body":
            e.put32(self.car + 144, v(1))
            e.put32(self.car + 148, v(2))
        elif o == "f":
            off = v(1)
            if off not in (0, 4, 8, 12, 16, 148, 152, 156, 160, 164) and \
                    not (32 <= off < 96 and off % 4 == 0):
                raise ValueError("field %d" % off)
            e.put32(self.map + off, v(2))
        elif o == "angle":
            p = self.scratch
            e.write(p, struct.pack("<H", 0x1234))
            r = e.call(F_ANGLE, self.map, p, limit=1000000)
            self.emit("  angle %d %04x" % (r, e.u16(p)))
        elif o == "dir":
            p = self.scratch
            for k in range(3):
                e.put32(p + 4 * k, 0x7f7f0001 + k)
            r = e.call(F_CAMDIR, self.map, p, limit=1000000)
            self.emit("  dir %d %08x %08x %08x"
                      % (r, e.u32(p), e.u32(p + 4), e.u32(p + 8)))
        elif o == "uv":
            p, q = self.scratch, self.scratch + 32
            for k in range(3):
                e.put32(p + 4 * k, v(1 + k))
            e.put32(q, 0x7f7f0011)
            e.put32(q + 4, 0x7f7f0012)
            e.call(F_UV, self.map, q, p, limit=100000)
            self.emit("  uv %08x %08x" % (e.u32(q), e.u32(q + 4)))
        elif o == "box":
            c, q = self.scratch, self.scratch + 16
            e.put32(c, v(1))
            e.put32(c + 4, v(2))
            for k in range(4):
                e.put32(q + 8 * k, 0x7f7f0020 + 2 * k)
                e.put32(q + 8 * k + 4, 0x7f7f0021 + 2 * k)
            for k in range(4):
                e.fpr[12 + k] = v(3 + k)
            e.call(F_BOX, self.map, c, v(7), q, limit=100000)
            self.emit("  box " + " ".join("%08x" % e.u32(q + 4 * k)
                                          for k in range(8)))
        elif o == "cubic":
            p = self.scratch
            e.put32(p, v(1))
            e.put32(p + 4, v(2))
            e.fpr[12] = v(3)
            e.fpr[13] = v(4)
            e.call(F_CUBIC, p, p + 4, limit=1000)
            self.emit("  cubic %08x %08x" % (e.u32(p), e.u32(p + 4)))
        else:
            raise ValueError(o)
        if tables:
            self.dump_tables()
        self.dump()

    def run(self, lines):
        e = self.e
        for line in lines:
            self.emit("> " + line)
            sp = e.reg[29]
            self.op(line.split("|"))
            e.reg[29] = sp
        return self.out


def model(lines):
    return Model().run(lines)


# ================================================================= build

def build_harness(tmp, name="trackmap_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


run_harness = fc.run_harness
diff = pcc.diff
write_script = fc.write_script


# ============================================================= mutations

T = TRACKMAP


def M(name, before, after, rel=T):
    return (name, rel, before, after)


MUTATIONS = [
    # The tables.
    M("mode0-anglex", "    // 0, 3D\n    { 0xd5da,", "    // 0, 3D\n    { 0xd5db,"),
    M("mode1-sf-height", "0.03499f, 0.169987f, 0, 1, 1,", "0.03499f, 0.169988f, 0, 1, 1,"),
    M("mode1-rotates", "0.03499f, 0.169987f, 0, 1, 1,", "0.03499f, 0.169987f, 1, 1, 1,"),
    M("mode3-scrolls-not", "0.03998f, 0.194978f, 0, 1, 1,", "0.03998f, 0.194978f, 0, 0, 1,"),
    M("mode4-clip-y", "    // 4, fixed\n    { 0xffff, {0}, 200.0f, 79, 256, 130.0f, 130.0f, 79, 218,",
      "    // 4, fixed\n    { 0xffff, {0}, 200.0f, 79, 256, 130.0f, 130.0f, 79, 256,"),
    M("mode5-alpha", "1.0f, 1.0f, 0, {0}, 0.06f, 0.03f, 0.095f, 0, 0, 1, 0, 0.29f, 1, 0, {0} },\n    // 6",
      "1.0f, 1.0f, 0, {0}, 0.06f, 0.03f, 0.095f, 0, 0, 1, 0, 0.3f, 1, 0, {0} },\n    // 6"),
    M("mode6-drawn", "      0.0f, 0.0f, 0, {0}, 0.0f, 0.0f, 0.0f, 0, 0, 0, 0, 0.0f, 0, 0, {0} },",
      "      0.0f, 0.0f, 0, {0}, 0.0f, 0.0f, 0.0f, 0, 0, 0, 0, 0.0f, 1, 0, {0} },"),
    M("mode7-clip-height", "83, 245, 140.0f, 140.0f,", "83, 245, 140.0f, 130.0f,"),
    M("mode8-x", "    // 8, Be The Cop, small: as fixed\n    { 0xffff, {0}, 200.0f, 79,",
      "    // 8, Be The Cop, small: as fixed\n    { 0xffff, {0}, 200.0f, 80,"),
    M("mode10-no-zoom", "      0.33f, 0.33f, 1, {0},", "      0.33f, 0.33f, 0, {0},"),
    M("mode2-dot", "    // 2, 2D\n    { 0xffff, {0}, 200.0f, 72, 243, 130.0f, 130.0f, 72, 243, 100.0f, 100.0f,\n      0.33f, 0.33f, 0, {0}, 0.1f,",
      "    // 2, 2D\n    { 0xffff, {0}, 200.0f, 72, 243, 130.0f, 130.0f, 72, 243, 100.0f, 100.0f,\n      0.33f, 0.33f, 0, {0}, 0.11f,"),
    M("colour-7-blue", "{ 0, 64, 122 }", "{ 0, 64, 123 }"),
    M("colour-0-blue", "    { 172, 53, 0 }, { 75,", "    { 172, 53, 1 }, { 75,"),
    M("init-no-colours", "    memcpy(TrackMapMarkerInfo, kMarkerColours, sizeof TrackMapMarkerInfo);\n", ""),
    M("init-ten-modes", "    memcpy(TrackMapModeInfo, kModes, sizeof TrackMapModeInfo);",
      "    memcpy(TrackMapModeInfo, kModes, sizeof TrackMapModeInfo - 68);"),

    # The constructor.
    M("ctor-no-sufficient-1", "    m->SufficientDataToRenderMe = 1;\n    m->PreviousTime = 0;\n", "    m->PreviousTime = 0;\n"),
    M("ctor-no-time-0", "    m->SufficientDataToRenderMe = 1;\n    m->PreviousTime = 0;\n", "    m->SufficientDataToRenderMe = 1;\n"),
    M("ctor-player-not-needed", "    if (track == NULL || car == NULL || player == NULL) {", "    if (track == NULL || car == NULL) {"),
    M("ctor-car-not-needed", "    if (track == NULL || car == NULL || player == NULL) {", "    if (track == NULL || player == NULL) {"),
    M("ctor-null-sufficient", "        m->SufficientDataToRenderMe = 0;\n        return;", "        return;"),
    M("ctor-no-init", "    trackmap_init_mode_info();\n    m->CarToTrack", "    m->CarToTrack"),
    M("ctor-player-is-car", "    m->PlayerToTrack = player;", "    m->PlayerToTrack = (Player *)car;"),
    M("ctor-displayed-0", "    m->CurrentlyDisplayedMode = 6;", "    m->CurrentlyDisplayedMode = 0;"),
    M("ctor-mode-0", "    m->CurrentMode = 6;", "    m->CurrentMode = 0;"),
    M("ctor-time-0", "    m->PreviousTime = (uint32_t)WorldTimer;\n    m->CurrentTrack", "    m->PreviousTime = 0;\n    m->CurrentTrack"),
    M("ctor-no-pursued", "    m->CurrentlyPursuedCar = NULL;\n", ""),
    M("ctor-no-prev-x", "    m->PreviousCameraDirection.x = 0.0f;\n    m->PreviousCameraDirection.y = 0.0f;\n    m->CurrentCameraSpeed",
      "    m->PreviousCameraDirection.y = 0.0f;\n    m->CurrentCameraSpeed"),
    M("ctor-no-speed-y", "    m->CurrentCameraSpeed.y = 0.0f;\n", ""),
    M("ctor-map-default", "    m->TrackMapTexture = get_texture_info(bchunk_hash(name), 0, 0);",
      "    m->TrackMapTexture = get_texture_info(bchunk_hash(name), 1, 0);"),
    M("ctor-map-number-unsigned", "\"TRACK%d_MAP\", track->TrackNumber);", "\"TRACK%d_MAP\", (uint8_t)track->TrackNumber);"),
    M("ctor-map-name-02d", "\"TRACK%d_MAP\", track->TrackNumber);", "\"TRACK%02d_MAP\", track->TrackNumber);"),
    M("ctor-map-not-needed", "    if (m->TrackMapTexture == NULL)\n        m->SufficientDataToRenderMe = 0;\n", ""),
    M("ctor-marker-no-default", "get_texture_info(bchunk_hash(\"CAR_MARKER\"), 1, 0);", "get_texture_info(bchunk_hash(\"CAR_MARKER\"), 0, 0);"),
    M("ctor-markerb-name", "bchunk_hash(\"CAR_MARKERB\")", "bchunk_hash(\"CAR_MARKER\")"),
    M("ctor-frame-unloaded", "get_texture_info(bchunk_hash(\"TRACKMAPFRAME\"), 1, 0);", "get_texture_info(bchunk_hash(\"TRACKMAPFRAME\"), 1, 1);"),
    M("ctor-underlay-at-116", "    m->UnderlayTexture = get_texture_info", "    m->StartLineTexture = get_texture_info"),
    M("ctor-start-at-120", "    m->StartFinishLineTexture =\n", "    m->FinishLineTexture =\n"),
    M("ctor-no-roadblock", "    m->RoadblockTexture = get_texture_info(bchunk_hash(\"BKGBMP\"), 1, 0);\n", ""),
    M("ctor-underlay-not-needed", "        || m->OverlayTexture == NULL || m->UnderlayTexture == NULL)", "        || m->OverlayTexture == NULL)"),
    M("ctor-markerb-not-needed", "        || m->CarMarkerRotatingTexture == NULL\n", ""),
    M("ctor-roadblock-needed", "        || m->OverlayTexture == NULL || m->UnderlayTexture == NULL)",
      "        || m->OverlayTexture == NULL || m->UnderlayTexture == NULL\n        || m->RoadblockTexture == NULL)"),
    M("ctor-start-always-needed", "    if (TheRaceParameters.Point2Point == 0 && m->StartFinishLineTexture == NULL)",
      "    if (m->StartFinishLineTexture == NULL)"),
    M("ctor-start-p2p-inverted", "    if (TheRaceParameters.Point2Point == 0 && m->StartFinishLineTexture == NULL)",
      "    if (TheRaceParameters.Point2Point != 0 && m->StartFinishLineTexture == NULL)"),
    M("ctor-p2p-byte", "    if (TheRaceParameters.Point2Point == 0 && m->StartFinishLineTexture == NULL)",
      "    if ((int8_t)TheRaceParameters.Point2Point == 0 && m->StartFinishLineTexture == NULL)"),
    M("ctor-no-identity", "    eIdentity(&m->MapRotationMatrix);\n", ""),
    M("ctor-no-rotation", "    eRotateZ(&m->MapRotationMatrix, &m->MapRotationMatrix,\n             m->CurrentTrack->TrackMapCalibrationRotation);\n", ""),
    M("ctor-rotation-negated", "             m->CurrentTrack->TrackMapCalibrationRotation);", "             (uint16_t)-m->CurrentTrack->TrackMapCalibrationRotation);"),

    # EvalCubic.
    M("cubic-d-negated", "    float d = target - x0;", "    float d = x0 - target;"),
    M("cubic-a-sign", "    float a = (v0 - d) - d;", "    float a = (d - v0) - d;"),
    M("cubic-b-2d", "    float b = ((d + d) + d - v0) - v0;", "    float b = ((d + d) - v0) - v0;"),
    M("cubic-b-one-v0", "    float b = ((d + d) + d - v0) - v0;", "    float b = (d + d) + d - v0;"),
    M("cubic-x-no-x0", "    *x = ((a * t + b) * t + v0) * t + x0;", "    *x = ((a * t + b) * t + v0) * t;"),
    M("cubic-x-expanded", "    *x = ((a * t + b) * t + v0) * t + x0;", "    *x = a * t * t * t + b * t * t + v0 * t + x0;"),
    M("cubic-v-2a", "    *v = (((a + a) + a) * t + (b + b)) * t + v0;", "    *v = ((a + a) * t + (b + b)) * t + v0;"),
    M("cubic-v-b", "    *v = (((a + a) + a) * t + (b + b)) * t + v0;", "    *v = (((a + a) + a) * t + b) * t + v0;"),
    M("cubic-v-no-v0", "    *v = (((a + a) + a) * t + (b + b)) * t + v0;", "    *v = (((a + a) + a) * t + (b + b)) * t;"),

    # GetAngle.
    M("angle-always-turns", "    if (TrackMapModeInfo[m->CurrentlyDisplayedMode].HasRotation == 0) {", "    if (0) {"),
    M("angle-of-current-mode", "    if (TrackMapModeInfo[m->CurrentlyDisplayedMode].HasRotation == 0) {",
      "    if (TrackMapModeInfo[m->CurrentMode].HasRotation == 0) {"),
    M("angle-of-scrolling", "    if (TrackMapModeInfo[m->CurrentlyDisplayedMode].HasRotation == 0) {",
      "    if (TrackMapModeInfo[m->CurrentlyDisplayedMode].HasScrolling == 0) {"),
    M("angle-still-0", "        *angle = 0x8000;\n        return 1;", "        *angle = 0;\n        return 1;"),
    M("angle-still-answers-0", "        *angle = 0x8000;\n        return 1;", "        *angle = 0x8000;\n        return 0;"),
    M("angle-time-unsigned", "    t = (float)(int32_t)((uint32_t)WorldTimer - m->PreviousTime) * 0.00025f;",
      "    t = (float)((uint32_t)WorldTimer - m->PreviousTime) * 0.00025f;"),
    M("angle-time-one-constant", "    t = (float)(int32_t)((uint32_t)WorldTimer - m->PreviousTime) * 0.00025f;\n    t = t * 0.9f;\n",
      "    t = (float)(int32_t)((uint32_t)WorldTimer - m->PreviousTime) * 0.000225f;\n"),
    M("angle-time-no-0.9", "    t = t * 0.9f;\n", ""),
    M("angle-time-before-dir",
      "    if (trackmap_get_camera_direction(m, &dir) == 0)\n        return 0;\n\n    // GetCameraDirection may have started the ease: read it after.\n    t = (float)(int32_t)((uint32_t)WorldTimer - m->PreviousTime) * 0.00025f;\n",
      "    t = (float)(int32_t)((uint32_t)WorldTimer - m->PreviousTime) * 0.00025f;\n    if (trackmap_get_camera_direction(m, &dir) == 0)\n        return 0;\n"),
    M("angle-y-after-x", "    eval_cubic(&y, &m->CurrentCameraSpeed.y, dir.y, t);", "    eval_cubic(&y, &m->CurrentCameraSpeed.y, dir.x, t);"),
    M("angle-speeds-swapped", "    eval_cubic(&x, &m->CurrentCameraSpeed.x, dir.x, t);", "    eval_cubic(&x, &m->CurrentCameraSpeed.y, dir.x, t);"),
    M("angle-y-not-kept", "    m->PreviousCameraDirection.y = y;\n    m->PreviousTime", "    m->PreviousTime"),
    M("angle-time-not-kept", "    m->PreviousTime = (uint32_t)WorldTimer;\n    *angle", "    *angle"),
    M("angle-atan-swapped", "    *angle = (uint16_t)(bATan(y, x) - 32768);", "    *angle = (uint16_t)(bATan(x, y) - 32768);"),
    M("angle-no-half-turn", "    *angle = (uint16_t)(bATan(y, x) - 32768);", "    *angle = (uint16_t)bATan(y, x);"),
    M("angle-plus-half-turn", "    *angle = (uint16_t)(bATan(y, x) - 32768);", "    *angle = (uint16_t)(bATan(y, x) + 32768);"),
    M("angle-quarter-turn", "    *angle = (uint16_t)(bATan(y, x) - 32768);", "    *angle = (uint16_t)(bATan(y, x) - 16384);"),

    # GetCameraDirection.
    M("dir-any-mover", "    if (mover == NULL || mover->Type != CM_DRIVE) {", "    if (mover == NULL) {"),
    M("dir-no-null-test", "    if (mover == NULL || mover->Type != CM_DRIVE) {", "    if (mover->Type != CM_DRIVE) {"),
    M("dir-orbit-mover", "    if (mover == NULL || mover->Type != CM_DRIVE) {", "    if (mover == NULL || mover->Type != CM_ORBIT_CAR) {"),
    M("dir-stage-inverted", "        if (race_get_race_stage(pCurrentRace) != RACE_STAGE_RACING) {",
      "        if (race_get_race_stage(pCurrentRace) == RACE_STAGE_RACING) {"),
    M("dir-stage-before", "        if (race_get_race_stage(pCurrentRace) != RACE_STAGE_RACING) {",
      "        if (race_get_race_stage(pCurrentRace) < RACE_STAGE_RACING) {"),
    M("dir-body-v1", "            dir->x = m->CarToTrack->State.BodyMatrix.v0.x;", "            dir->x = m->CarToTrack->State.BodyMatrix.v1.x;"),
    M("dir-body-y-of-x", "            dir->y = m->CarToTrack->State.BodyMatrix.v0.y;", "            dir->y = m->CarToTrack->State.BodyMatrix.v0.x;"),
    M("dir-eased-y-of-x", "            dir->y = m->PreviousCameraDirection.y;", "            dir->y = m->PreviousCameraDirection.x;"),
    M("dir-other-z", "            dir->y = m->PreviousCameraDirection.y;\n", "            dir->y = m->PreviousCameraDirection.y;\n            dir->z = 0.0f;\n"),
    M("dir-other-answers-0", "        }\n        return 1;\n    }\n", "        }\n        return 0;\n    }\n"),
    M("dir-no-z", "        dir->z = cam->CurrentKey.Direction.z;\n", "        dir->z = 0.0f;\n"),
    M("dir-target", "        dir->x = cam->CurrentKey.Direction.x;", "        dir->x = cam->CurrentKey.Target.x;"),
    M("dir-no-look-back", "        eRotateZ(&r, &r, ((DriveCameraMover *)mover)->LookBackAngle);\n", ""),
    M("dir-look-back-negated", "        eRotateZ(&r, &r, ((DriveCameraMover *)mover)->LookBackAngle);",
      "        eRotateZ(&r, &r, (uint16_t)-((DriveCameraMover *)mover)->LookBackAngle);"),
    M("dir-start-lt", "    if (fabsf(m->PreviousCameraDirection.x) <= 0.001f", "    if (fabsf(m->PreviousCameraDirection.x) < 0.001f"),
    M("dir-start-or", "        && fabsf(m->PreviousCameraDirection.y) <= 0.001f) {", "        || fabsf(m->PreviousCameraDirection.y) <= 0.001f) {"),
    M("dir-start-y-signed", "        && fabsf(m->PreviousCameraDirection.y) <= 0.001f) {", "        && m->PreviousCameraDirection.y <= 0.001f) {"),
    M("dir-start-0.01", "    if (fabsf(m->PreviousCameraDirection.x) <= 0.001f", "    if (fabsf(m->PreviousCameraDirection.x) <= 0.01f"),
    M("dir-start-no-time", "        m->PreviousTime = (uint32_t)WorldTimer;\n        m->PreviousCameraDirection.y", "        m->PreviousCameraDirection.y"),
    M("dir-start-y-of-x", "        m->PreviousCameraDirection.y = dir->y;", "        m->PreviousCameraDirection.y = dir->x;"),
    M("dir-other-answers-at-start", "    if (fabsf(m->PreviousCameraDirection.x) <= 0.001f\n        && fabsf(m->PreviousCameraDirection.y) <= 0.001f) {",
      "    if (0) {"),

    # GetCarUVPosition.
    M("uv-y-not-negated", "    v.y = -pos->y;", "    v.y = pos->y;"),
    M("uv-z-0", "    v.z = 1.0f;", "    v.z = 0.0f;"),
    M("uv-left-added", "    v.x = v.x - t->TrackMapCalibrationUpperLeft.x;", "    v.x = v.x + t->TrackMapCalibrationUpperLeft.x;"),
    M("uv-top-subtracted", "    v.y = v.y + t->TrackMapCalibrationUpperLeft.y;", "    v.y = v.y - t->TrackMapCalibrationUpperLeft.y;"),
    M("uv-reciprocal", "    v.x = v.x / t->TrackMapCalibrationMapWidthMetres;", "    v.x = v.x * (1.0f / t->TrackMapCalibrationMapWidthMetres);"),
    M("uv-y-not-scaled", "    v.y = v.y / t->TrackMapCalibrationMapWidthMetres;\n", ""),
    M("uv-no-rotation", "    eMulVector3(&v, &m->MapRotationMatrix, &v);\n", ""),
    M("uv-out-swapped", "    out->x = v.x;\n    out->y = v.y;", "    out->x = v.y;\n    out->y = v.x;"),

    # GetBoxOnMap.
    M("box-order", "    eMulMatrix(&t, &r, &t);", "    eMulMatrix(&t, &t, &r);"),
    M("box-no-turn", "    eRotateZ(&r, &r, angle);\n", ""),
    M("box-turn-negated", "    eRotateZ(&r, &r, angle);", "    eRotateZ(&r, &r, (uint16_t)-angle);"),
    M("box-centre-y-of-x", "    c.y = centre->y;", "    c.y = centre->x;"),
    M("box-c0-x", "    corner[0].x = right;", "    corner[0].x = -left;"),
    M("box-c1-y", "    corner[1].y = forward;", "    corner[1].y = -backward;"),
    M("box-c2-x", "    corner[2].x = -left;", "    corner[2].x = left;"),
    M("box-c3-y", "    corner[3].y = -backward;", "    corner[3].y = -forward;"),
    M("box-three-corners", "    for (i = 0; i < 4; i++) {\n        corner[i].z", "    for (i = 0; i < 3; i++) {\n        corner[i].z"),
]

EQUIVALENT = {
    "angle-plus-half-turn":
        "bATan's answer less 32768 and plus 32768 are the same halfword: "
        "they differ by 65536.",
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    lines = script()
    base = model(lines)
    caught, survived, missing, equivalent = 0, [], [], []
    indir = tempfile.TemporaryDirectory()
    scp = write_script(indir.name, lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, scp, out)
        if diff(base, out.read_text(encoding="latin-1").splitlines(),
                quiet=True):
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
                n = diff(base, out.read_text(encoding="latin-1")
                         .splitlines(), quiet=True)
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
    indir.cleanup()

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

    lines = script()
    got = model(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = write_script(tmp, lines)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text(encoding="latin-1").splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(got) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(got, harness)
    print("%d ops, %d lines, %d differ" % (len(lines), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
