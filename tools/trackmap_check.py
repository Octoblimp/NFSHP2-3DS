#!/usr/bin/env python3
"""Cross-check 3DS Files/source/trackmap.c, the minimap (steps 8m-6a,
8m-6b and 8m-6c), against the retail image, SLES_507.31.

**The model** is retail's own: InitTrackMapModeInfo (0x001bd1f8), the
constructor (0x001babb8), GetAngle (0x001bb678) with EvalCubic
(0x001bdad0), GetCameraDirection (0x001bd0b0), GetCarUVPosition
(0x001bca50) and GetBoxOnMap (0x001bcae8); and DrawMap (0x001bb7a8),
MapToScreen (0x001bcc58), ClipPolygon (0x001bc140) with EmitPoint,
GetSideOfLine (0x001cb138), CalculateCentroidOfQuad (0x001bda40) and
DrawOverOrUnderLay (0x001bbf88); and IsPointInPoly (0x001cb1f0),
DrawMarker (0x001bbc50) and Render (0x001bade8), with tCopManager's
GetNumActiveRoadBlocks (0x00226968) and GetActiveRoadBlock (0x00226238)
and Race::GetRacingCar (0x00149158). bSPrintf, bStringHash, bATan, the
matrix code and ePoly's constructor run under them as they are. The
harness (tools/src/trackmap_test.c) runs trackmap.c over emath.c, bmath.c,
epoly.c and copmanager.c.

**The stubs** are GetTextureInfo (0x001abf48), which answers each of the
seven names from a mask; eGetView (0x00107c90), which answers the one
view; and ePoly::Render (0x0010fa68), the port's gEPolyRenderFn. All three
log their calls, Render with the whole poly. WorldTimer, pCurrentRace's
RaceStage and TheRaceParameters.Point2Point are set in memory, and for
Render pCurrentWorld, pCurrentRace, pCopManager and the player tables,
over a World, a Race, eight cars with their types and racing cars, two
players, seven cops, four pursuits, four roadblocks and a ghost, each at
retail's offsets.

**Compared**, after each op, are the map's fields by name, its pointers
by what they point at; a test ePoly's fields, retail's offsets 16 to 152;
the two tables after InitTrackMapModeInfo, field by field (the padding is
left out: retail never writes it); and what each call answers.

**The script** builds the tables over a pattern; constructs with each of
the three pointers missing, every texture mask with and without
Point2Point, and a spread of track numbers, rotations and times; takes
points to the map under several calibrations and hand-set matrices; turns
boxes; runs EvalCubic alone; asks the camera's direction with no mover,
other movers and the drive camera, each race stage, look backs and eased
directions about the 0.001 test; and eases GetAngle through a turning
camera and every mode, with time steps from none to a wrap.

For 8m-6b it tests points against lines, on them and either side; takes
centroids; projects point sets in each drawn mode and under hand-set
tilts, distances, places (loaded without their sign) and heights, fading
to both saturations; clips quads inside, outside, across one edge and two,
around the box, exactly on it, as an octagon, with ties for the top point
about 0.001, both windings and sixty seeded random convex quads, in each
mode's box and hand-set ones, with UVs, colours, layers and textures; draws
the frame and the backing in each mode and with IsDrawn and HasBorder set
by hand; and draws the map in every mode from several places and turns,
zoomed to a pursued car at several distances, without scrolling, at
hand-set alphas, heights and view distances, without a map texture and
under a second calibration. Only convex quads are clipped: retail's
buffers hold the eight points those can make.

For 8m-6c it tests points against polygons of none to eight sides, inside,
outside, on their edges and corners and level with them; draws markers in
every mode, in and out of the box, about several centres and turns, with
and without scrolling, at hand-set view distances, sizes, turns, colours,
layers and textures; and renders the map with nothing to render, with no
world or race, in every mode, through each way to Be The Cop's targeting
and each way out of it, with the AI's cars and the cops drawn, hidden and
pursued, the roadblocks in and out of the pursuits, a ghost turned and
still, one player and two in both orders, cop cars, a pursued player, and
loops and point to points.

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
    "bprintf.c", "bmem.c", "epoly.c", "copmanager.c")]

F_INIT = 0x001bd1f8
F_CTOR = 0x001babb8
F_ANGLE = 0x001bb678
F_CAMDIR = 0x001bd0b0
F_UV = 0x001bca50
F_BOX = 0x001bcae8
F_CUBIC = 0x001bdad0
F_M2S = 0x001bcc58
F_SIDE = 0x001cb138
F_CENTROID = 0x001bda40
F_CLIP = 0x001bc140
F_OVERLAY = 0x001bbf88
F_DRAWMAP = 0x001bb7a8
F_IPP = 0x001cb1f0
F_MARKER = 0x001bbc50
F_RENDER = 0x001bade8
EMATH_INIT = 0x0011b138
EMATH_SINIT = 0x0011bf70                # 0x002dc400 = (0, 0, 0, 1)
S_TEXINFO = 0x001abf48
S_GETVIEW = 0x00107c90
S_RENDER = 0x0010fa68                   # ePoly::Render

MODES = 0x003140b8
COLOURS = 0x003143a8
GP = 0x003358f0
WORLD_TIMER = GP - 19576
CURRENT_RACE = GP - 22272
CURRENT_WORLD = GP - 22120
COP_MANAGER = GP - 15620
NUM_PLAYERS = GP - 20920
BY_INDEX = GP - 20928
BY_NUMBER = GP - 20936
NUM_POOL = 8
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


# ---- 8m-6b

def scenario_side():
    lines = [((0.0, 0.0), (1.0, 0.0)), ((22.0, 193.0), (122.0, 193.0)),
             ((122.0, 293.0), (22.0, 293.0)), ((22.0, 293.0), (22.0, 193.0)),
             ((-1.5, 2.5), (3.25, -7.0)), ((0.0, 0.0), (0.0, 0.0)),
             ((1e4, -1e4), (-1e4, 1e4))]
    points = [(0.0, 0.0), (0.5, 1.0), (0.5, -1.0), (2.0, 0.0), (-3.0, 5.0),
              (72.0, 243.0), (22.0, 193.0), (122.0, 192.999),
              (100.0, 100.0), (1e-7, 1e-7), (-0.0, 0.0), (22.0, 500.0),
              (0.875, -2.25)]
    s = []
    for a, b in lines:
        for p in points:
            s += ["side|" + "|".join(F(v) for v in a + b + p)]
    return s


QUADS = [
    ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
    ((0.25, -0.5), (1.5, 0.125), (0.75, 2.0), (-1.0, 0.875)),
    ((0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0)),
    ((1e4, -2e4), (3e4, 5e3), (-7e3, 9e3), (-1e4, -1e4)),
    ((0.1, 0.2), (0.3, 0.4), (0.5, 0.6), (0.7, 0.8)),
    ((22.0, 193.0), (122.0, 193.0), (122.0, 293.0), (22.0, 293.0)),
    ((-0.0, -0.0), (3.0, -0.0), (-0.0, 7.0), (5.0, 5.0)),
]


def scenario_centroid():
    return ["centroid|" + "|".join(F(v) for p in q for v in p)
            for q in QUADS]


def m2s(pts):
    return "m2s|" + "|".join(F(v) for p in pts for v in p)


M2S_POINTS = [
    [(-65.0, -65.0, 0.0), (65.0, -65.0, 0.0), (65.0, 65.0, 0.0),
     (-65.0, 65.0, 0.0)],
    [(-95.0, -95.0, 0.0), (95.0, -95.0, 0.0), (95.0, 95.0, 0.0),
     (-95.0, 95.0, 0.0)],
    [(0.0, 0.0, 0.0), (10.5, -3.25, 40.0), (-7.0, 12.0, -60.0),
     (1.0, 1.0, 126.0)],
    [(3.0, 4.0, 1e-3), (-3.0, 4.0, -1e-3), (0.0, 0.0, 200.0),
     (2.0, -2.0, 1e12)],
    [(131.0, -17.0, 5.0), (-0.0, -0.0, -0.0), (50.0, 50.0, 90.0),
     (-120.0, 30.0, -100.0)],
]


def scenario_m2s():
    s = ["fillmodes", "init", "cal|0|0|%s|0" % F(100.0), "mask|0", "fill",
         "ctor|1|1|1", "poly"]
    for m in (0, 1, 2, 3, 4, 5, 7, 8, 9, 10):
        s += ["f|164|%d" % m]
        for pts in M2S_POINTS:
            s += [m2s(pts)]
    # Hand-set tilts, distances, places and heights in mode 0.
    s += ["f|164|0"]
    for ang in (0, 0x4000, 0x2000, 0xc000, 0x8000, 0x1234):
        s += ["mode|0|0|2|%#x" % ang, m2s(M2S_POINTS[2])]
    s += ["mode|0|0|2|0xd5da"]
    for h in (50.0, 1000.0, 0.5, 333.25):
        s += ["mode|0|4|4|%s" % F(h), m2s(M2S_POINTS[0]),
              m2s(M2S_POINTS[4])]
    s += ["mode|0|4|4|%s" % F(200.0)]
    for x, y in ((0x8000, 0xffff), (0x7fff, 0), (0xffff, 0x8000),
                 (0x1234, 0xfedc)):
        s += ["mode|0|8|2|%#x" % x, "mode|0|10|2|%#x" % y,
              m2s(M2S_POINTS[0])]
    for ht in (1.0, -190.0, 1e-3, 3000.0):
        s += ["mode|0|16|4|%s" % F(ht), m2s(M2S_POINTS[2]),
              m2s(M2S_POINTS[3])]
    s += ["init"]
    return s


def clip_quad(q, uvs=None, cols=None):
    s = ["poly"]
    for i, (x, y) in enumerate(q):
        s += ["pv|%d|%s|%s" % (i, F(x), F(y))]
    for i in range(4):
        u, v, w = uvs[i] if uvs else (0.25 * i, 1.0 - 0.125 * i, 1.0)
        s += ["puv|%d|%s|%s|%s" % (i, F(u), F(v), F(w))]
    for i in range(4):
        c = cols[i] if cols else (0x80402010 + 0x01030507 * i)
        s += ["pc|%d|%#x" % (i, c)]
    return s


def rot_rect(cx, cy, hw, hh, deg):
    a = math.radians(deg)
    c, d = math.cos(a), math.sin(a)
    return tuple((cx + x * c - y * d, cy + x * d + y * c)
                 for x, y in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)))


CLIP_QUADS = [
    ((40.0, 210.0), (100.0, 210.0), (100.0, 280.0), (40.0, 280.0)),
    ((200.0, 0.0), (300.0, 0.0), (300.0, 50.0), (200.0, 50.0)),
    ((-90.0, 200.0), (0.0, 200.0), (0.0, 250.0), (-90.0, 250.0)),
    ((40.0, 300.0), (90.0, 300.0), (90.0, 400.0), (40.0, 400.0)),
    ((40.0, 100.0), (90.0, 100.0), (90.0, 190.0), (40.0, 190.0)),
    ((0.0, 170.0), (150.0, 170.0), (150.0, 320.0), (0.0, 320.0)),
    ((10.0, 220.0), (60.0, 220.0), (60.0, 260.0), (10.0, 260.0)),
    ((100.0, 180.0), (140.0, 180.0), (140.0, 210.0), (100.0, 210.0)),
    ((72.0, 151.0), (164.0, 243.0), (72.0, 335.0), (-20.0, 243.0)),
    ((22.0, 193.0), (122.0, 193.0), (122.0, 293.0), (22.0, 293.0)),
    ((50.0, 200.0), (90.0, 200.0005), (90.0, 260.0), (50.0, 260.0)),
    ((90.0, 200.0), (90.0, 260.0), (50.0, 260.0), (50.0, 200.0005)),
    ((90.0, 200.0), (90.0, 260.0), (50.0, 260.0), (50.0, 200.0011)),
    ((30.0, 200.0), (30.0, 200.0), (110.0, 250.0), (40.0, 280.0)),
    ((0.0, 230.0), (40.0, 170.0), (60.0, 175.0), (10.0, 260.0)),
    ((115.0, 280.0), (160.0, 285.0), (150.0, 330.0), (110.0, 300.0)),
    ((-20.0, 243.0), (72.0, 335.0), (164.0, 243.0), (72.0, 151.0)),
    ((0.0, 320.0), (150.0, 320.0), (150.0, 170.0), (0.0, 170.0)),
]
CLIP_QUADS += [rot_rect(72.0, 243.0, 80.0, 40.0, d)
               for d in (30.0, 45.0, 60.0, 135.0, -17.0)]
CLIP_QUADS += [rot_rect(72.0, 243.0, 65.0, 65.0, d)
               for d in (0.0, 45.0, 10.0, 80.0)]
CLIP_QUADS += [rot_rect(30.0, 200.0, 20.0, 12.0, 25.0),
               rot_rect(120.0, 290.0, 9.0, 30.0, 70.0)]


def convex(q):
    sg = 0
    for i in range(4):
        a, b, c = q[i], q[(i + 1) % 4], q[(i + 2) % 4]
        cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(cr) < 1.0:
            return False
        if sg and (cr > 0) != (sg > 0):
            return False
        sg = cr
    return True


def random_quads(n, seed):
    import random
    r = random.Random(seed)
    out = []
    while len(out) < n:
        cx, cy = r.uniform(0.0, 150.0), r.uniform(170.0, 320.0)
        angs = sorted(r.uniform(0.0, 2 * math.pi) for _ in range(4))
        if r.random() < 0.3:
            angs.reverse()
        q = tuple((round(cx + rr * math.cos(a), 3),
                   round(cy + rr * math.sin(a), 3))
                  for a, rr in ((a, r.uniform(10.0, 130.0)) for a in angs))
        if convex(q):
            out.append(q)
    return out


def scenario_clip():
    s = ["fillmodes", "init", "cal|0|0|%s|0" % F(100.0), "mask|0", "fill",
         "ctor|1|1|1", "f|164|2"]
    for q in CLIP_QUADS:
        s += clip_quad(q) + ["clip|0|14"]
    # UVs, colours, alphas, textures and layers.
    uvs = [(0.0, 0.0, 0.005), (1.0, 0.0, 0.004), (1.0, 1.0, 0.0045),
           (0.0, 1.0, 0.0055)]
    cols = [0x00ffffff, 0x80000000, 0xff123456, 0x7f00ff00]
    for q in (CLIP_QUADS[5], CLIP_QUADS[8], CLIP_QUADS[6], CLIP_QUADS[14]):
        s += clip_quad(q, uvs, cols) + ["clip|0|14"]
        for t, l in ((3, 0), (4, 15), (-1, 13), (6, -3), (0, 1000)):
            s += ["clip|%d|%d" % (t, l)]
    # Each mode's box.
    for m in (0, 1, 3, 4, 5, 7, 8, 9, 10):
        s += ["f|164|%d" % m]
        for q in (CLIP_QUADS[5], CLIP_QUADS[8], rot_rect(80.0, 240.0, 70.0,
                                                         50.0, 20.0)):
            s += clip_quad(q) + ["clip|0|14"]
    # Hand-set boxes: a place loaded as a halfword without its sign.
    s += ["f|164|2"]
    for cx, cy, cw, ch in ((0x8000, 0xffff, 100.0, 100.0),
                           (72, 243, 37.5, 151.25), (72, 243, 0.0, 0.0),
                           (60, 250, 3.0, 200.0), (0xffff, 243, 200.0, 100.0),
                           (72, 0xfff0, 100.0, 600.0)):
        s += ["mode|2|20|2|%#x" % cx, "mode|2|22|2|%#x" % cy,
              "mode|2|24|4|%s" % F(cw), "mode|2|28|4|%s" % F(ch)]
        for q in (CLIP_QUADS[5], CLIP_QUADS[8], CLIP_QUADS[0]):
            s += clip_quad(q) + ["clip|0|14"]
    s += ["init"]
    for q in random_quads(60, 8062):
        s += clip_quad(q) + ["clip|0|14"]
    return s


def scenario_overlay():
    s = ["fillmodes", "init", "cal|0|0|%s|0" % F(100.0), "mask|0", "fill",
         "ctor|1|1|1"]
    for m in range(11):
        s += ["f|164|%d" % m]
        for t, l in ((3, 0), (4, 15), (-1, 7)):
            s += ["overlay|%d|%d" % (t, l)]
    s += ["f|164|2"]
    for drawn in (0, 1, 2, 0x80):
        for border in (0, 1, 2, 0x80):
            s += ["mode|2|64|1|%#x" % drawn, "mode|2|65|1|%#x" % border,
                  "overlay|3|0"]
    s += ["mode|2|20|2|0x8000", "mode|2|22|2|0xffff",
          "mode|2|24|4|%s" % F(37.5), "mode|2|28|4|%s" % F(-12.25),
          "overlay|4|15", "init"]
    return s


DM_POS = [(0.0, 0.0), (-1200.5, 830.25), (-150.0, -900.0),
          (1199.5, -1569.75), (37.25, 412.5)]
DM_ANGLES = (0, 0x4000, 0x1234, 0xc000, 0xffff, 0x8000)


def scenario_drawmap():
    s = ["fillmodes", "init",
         "cal|%s|%s|%s|0x1234" % (F(-1200.5), F(830.25), F(2400.0)),
         "mask|0", "fill", "ctor|1|1|1", "pursued|0",
         "ppos|%s|%s" % (F(-100.0), F(50.0))]
    for m in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10):
        s += ["f|164|%d" % m]
        for x, y in DM_POS[:4]:
            s += ["pos|%s|%s" % (F(x), F(y))]
            for a in DM_ANGLES[:4]:
                s += ["drawmap|%#x" % a]
    # Zooming to keep the pursued car in view, mode 10's.
    s += ["f|164|10", "pos|%s|%s" % (F(-150.0), F(-900.0))]
    for px, py in ((-150.0, -900.0), (-100.0, -900.0), (-150.0, -1000.0),
                   (500.0, 300.0), (-1200.5, 830.25), (-149.0, -899.5)):
        s += ["pursued|1", "ppos|%s|%s" % (F(px), F(py))]
        for a in (0, 0x1234):
            s += ["drawmap|%#x" % a]
    s += ["pursued|0", "drawmap|0x1234"]
    # Hand-set: no scrolling, zooming in mode 2, alphas.
    s += ["f|164|2", "pos|%s|%s" % (F(37.25), F(412.5))]
    s += ["mode|2|57|1|0", "drawmap|0", "drawmap|0x4000",
          "mode|2|57|1|2", "drawmap|0x1234", "mode|2|57|1|1"]
    s += ["mode|2|40|1|1", "pursued|1", "ppos|%s|%s" % (F(-37.0), F(80.0)),
          "drawmap|0x2000", "mode|2|40|1|0x80", "drawmap|0x2000",
          "pursued|0", "drawmap|0x2000", "mode|2|40|1|0", "pursued|1",
          "drawmap|0x2000", "pursued|0"]
    for al in (0.5, 0.29, 2.0, -1.0, 0.0, 1.0001, 3e7):
        s += ["mode|2|60|4|%s" % F(al), "drawmap|0x1234"]
    s += ["mode|2|60|4|%s" % F(1.0)]
    for ht in (100.0, 260.0):
        s += ["mode|2|16|4|%s" % F(ht), "drawmap|0x1234"]
    s += ["mode|2|16|4|%s" % F(130.0)]
    for fwd, back in ((0.1, 0.9), (1.0, 0.0), (0.0, 0.0), (2.5, 0.75)):
        s += ["mode|2|32|4|%s" % F(fwd), "mode|2|36|4|%s" % F(back),
              "drawmap|0x5555"]
    s += ["init"]
    # A missing map texture, then the other places and angles in mode 0.
    s += ["mask|1", "fill", "ctor|1|1|1", "f|164|2", "drawmap|0",
          "mask|0", "fill", "ctor|1|1|1", "f|164|0"]
    for x, y in DM_POS:
        s += ["pos|%s|%s" % (F(x), F(y))]
        for a in DM_ANGLES:
            s += ["drawmap|%#x" % a]
    # Another calibration's turn.
    s += ["cal|%s|%s|%s|0xd5da" % (F(512.0), F(-256.0), F(1024.0)), "fill",
          "ctor|1|1|1", "f|164|2", "pos|%s|%s" % (F(1000.0), F(-700.0)),
          "drawmap|0x1234", "f|164|3", "drawmap|0x1234", "f|164|10",
          "pursued|1", "ppos|%s|%s" % (F(700.0), F(-650.0)), "drawmap|0x1234",
          "pursued|0"]
    return s


# ---- 8m-6c

def octagon(cx, cy, r):
    return [(cx + r * math.cos(k * math.pi / 4 + 0.3),
             cy + r * math.sin(k * math.pi / 4 + 0.3)) for k in range(8)]


IPP_POLYS = [
    [],
    [(0.0, 0.0)],
    [(0.0, 0.0), (4.0, 4.0)],
    [(0.0, 0.0), (4.0, 0.0), (2.0, 3.0)],
    [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)],
    [(0.0, 4.0), (4.0, 4.0), (4.0, 0.0), (0.0, 0.0)],
    [(2.0, -1.0), (5.0, 2.0), (2.0, 5.0), (-1.0, 2.0)],
    [(0.0, 0.0), (4.0, 0.0), (4.0, 0.0), (0.0, 4.0)],
    [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (2.0, 1.0), (0.0, 4.0)],
    [(0.0, 0.0), (4.0, 0.0), (0.0, 4.0), (4.0, 4.0)],
    octagon(2.0, 2.0, 2.5),
    [(-0.0661, 1.0838), (0.6047, 1.2604), (0.7813, 0.5896),
     (0.1105, 0.4130)],
]

IPP_POINTS = [
    (1.0, 1.0), (2.0, 2.0), (0.0, 0.0), (4.0, 4.0), (2.0, 0.0), (0.0, 2.0),
    (4.0, 2.0), (2.0, 4.0), (-1.0, 2.0), (5.0, 2.0), (2.0, -1.0),
    (2.0, 5.0), (3.999, 3.999), (1.0, 3.5), (2.0, 1.5), (2.0, 0.5),
    (3.0, 3.0), (-0.0, -0.0), (2.0, 3.0), (1e-7, 1e-7), (0.35, 0.85),
    (0.7, 0.5), (1e9, 2.0),
]


def scenario_ipp():
    s = []
    for poly in IPP_POLYS:
        for pt in IPP_POINTS:
            s += ["ipp|%d|%s|%s|" % ((len(poly),) + tuple(F(v) for v in pt))
                  + "|".join(F(v) for q in poly for v in q)]
    return s


OUTER = [(-0.2, -0.2), (1.2, -0.2), (1.2, 1.2), (-0.2, 1.2)]
TILTED = [(0.30, 0.10), (0.85, 0.35), (0.60, 0.90), (0.05, 0.65)]


def marker(pos, centre, a, col, layer, tex, ma, w, h, outer=OUTER):
    return ("marker|" + "|".join(F(v) for v in pos) + "|"
            + "|".join(F(v) for v in centre)
            + "|%#x|%d|%d|%d|%#x|%s|%s|" % (a, col, layer, tex, ma, F(w),
                                             F(h))
            + "|".join(F(v) for q in outer for v in q))


MK_POS = [(500.0, -500.0, 0.0), (100.0, -900.0, 3.0), (990.0, -10.0, -2.0),
          (1500.0, -500.0, 0.0), (-150.0, -480.0, 0.0), (430.0, -380.0, 7.0),
          (500.0, 150.0, 0.0), (0.0, 0.0, 0.0)]


def scenario_marker():
    s = ["fillmodes", "init", "cal|0|0|%s|0" % F(1000.0), "mask|0", "fill",
         "ctor|1|1|1", "f|148|%s" % F(0.33), "f|152|%s" % F(0.33)]
    # Every mode, places in and out of the box, two centres and turns.
    for m in range(11):
        s += ["f|164|%d" % m]
        for pos in MK_POS:
            for centre, a in (((0.5, 0.5), 0), ((0.45, 0.52), 0x1234)):
                s += [marker(pos, centre, a, 3, 5, 1, 0x4000, 0.1, 0.1)]
    # Turns, sizes, colours, layers and textures in a mode that scrolls and
    # one that does not.
    for m in (2, 5):
        s += ["f|164|%d" % m]
        for a in (0, 0x4000, 0x8000, 0xc000, 0xffff, 0x2aaa):
            for ma in (0, 0x2000, 0xc000, 0x8001):
                s += [marker(MK_POS[5], (0.5, 0.5), a, 0, 1, 2, ma, 0.1,
                             0.1)]
        for w, h in ((0.06, 0.06), (0.1, 0.05), (0.0, 0.0), (-0.02, 0.3),
                     (0.039982, 0.18498), (2.0, 1.5)):
            s += [marker(MK_POS[4], (0.5, 0.5), 0x1234, 6, 13, 5, 0x3000,
                         w, h)]
        for col in range(-1, 9):
            s += [marker(MK_POS[0], (0.5, 0.5), 0, col, col + 3, 1, 0, 0.1,
                         0.1)]
        for tex, layer in ((6, 7), (-1, 0), (3, 15), (4, 2)):
            s += [marker(MK_POS[1], (0.48, 0.55), 0x7000, 8, layer, tex,
                         0x0123, 0.05, 0.15)]
    # View distances for the scroll, a hand-set height and width.
    s += ["f|164|2"]
    for fwd, back in ((0.1, 0.9), (1.0, 0.25), (0.441781, 0.202055),
                      (5.0, 3.0)):
        s += ["f|148|%s" % F(fwd), "f|152|%s" % F(back),
              marker(MK_POS[5], (0.5, 0.5), 0x1234, 3, 5, 2, 0x5555, 0.1,
                     0.1)]
    s += ["f|148|%s" % F(0.33), "f|152|%s" % F(0.33)]
    for wd, ht in ((100.0, 260.0), (40.0, 40.0)):
        s += ["mode|2|12|4|%s" % F(wd), "mode|2|16|4|%s" % F(ht),
              marker(MK_POS[5], (0.5, 0.5), 0x1234, 3, 5, 2, 0x5555, 0.1,
                     0.1)]
    s += ["init"]
    # A tilted box: points either side of each edge.
    s += ["f|164|5"]
    for x, y in ((300.0, -100.0), (310.0, -150.0), (850.0, -350.0),
                 (860.0, -350.0), (600.0, -900.0), (600.0, -910.0),
                 (50.0, -650.0), (40.0, -650.0), (450.0, -500.0)):
        s += [marker((x, y, 0.0), (0.5, 0.5), 0, 4, 6, 2, 0x1000, 0.1, 0.1,
                     TILTED)]
    # A turned calibration and an undrawn mode by hand.
    s += ["cal|%s|%s|%s|0xd5da" % (F(-1200.5), F(830.25), F(2400.0)),
          "fill", "ctor|1|1|1", "f|148|%s" % F(0.33), "f|152|%s" % F(0.33),
          "f|164|0"]
    for pos in ((0.0, 0.0, 0.0), (-150.0, -900.0, 0.0), (37.25, 412.5, 1.0)):
        s += [marker(pos, (0.5, 0.5), 0x1234, 2, 1, 1, 0x4000, 0.09589,
                     0.09589)]
    s += ["mode|0|64|1|0", marker((0.0, 0.0, 0.0), (0.5, 0.5), 0, 2, 1, 1,
                                  0, 0.1, 0.1),
          "mode|0|64|1|0x80", marker((0.0, 0.0, 0.0), (0.5, 0.5), 0, 2, 1,
                                     1, 0, 0.1, 0.1), "init"]
    return s


# The cars for Render, about the tracked car at (37.25, 412.5): the two
# players' c0 and c1, the AI's c2 to c4, the cops c5 and c6, and c7.
RENDER_CARS = [
    ((37.25, 412.5), 0x0000), ((80.0, 390.0), 0x1000),
    ((-60.0, 500.0), 0x4000), ((150.0, 300.0), 0x8000),
    ((10.0, 700.0), 0xc000), ((-200.0, 250.0), 0x2345),
    ((260.0, 520.0), 0xfedc), ((2000.0, -2000.0), 0x0100),
]


def render_setup():
    s = ["fillmodes", "init",
         "cal|%s|%s|%s|0x1234" % (F(-1200.5), F(830.25), F(2400.0)),
         "mask|0", "fill", "ctor|1|1|1", "pos|%s|%s" % (F(37.25), F(412.5)),
         "mover|1", "stage|4", "view|0", "lookback|0",
         "camdir|%s|%s|%s" % (F(0.6), F(0.8), F(0.0)), "world|1000",
         "f|0|%s" % F(0.6), "f|4|%s" % F(0.8), "f|8|0", "f|12|0",
         "f|16|1000", "lines|0x0400|0x9000",
         "sline|%s|%s|%s|%s" % (F(30.0), F(420.0), F(-90.0), F(610.0))]
    for i, ((x, y), a) in enumerate(RENDER_CARS):
        s += ["cpos|%d|%s|%s" % (i, F(x), F(y)), "cang|%d|%#x" % (i, a),
              "cvis|%d|1|1" % i, "wcar|%d|%d" % (i, i)]
    s += ["wpos|2|5|7", "pcar|0|0", "pcar|1|1", "players|1|0|-1|0|-1"]
    return s


def scenario_render():
    s = render_setup()
    # Nothing to render: no data, no world, no race.
    s += ["f|160|2", "render", "wnull|1", "rnull|0", "render", "rnull|1",
          "f|156|0", "render", "f|156|1", "render"]
    # Every mode.
    for m in range(11):
        s += ["f|160|%d" % m, "render"]
    s += ["f|160|2"]
    # Be The Cop's targeting, each way in and out of it.
    s += ["cmgr|1", "render", "copidx|2", "cop|2|-2", "render",
          "cop|2|-1", "render", "pursuit|0|-1|-1", "cop|2|0", "render",
          "pursuit|0|3|-1", "render", "f|160|6", "render", "f|160|0",
          "render", "f|160|4", "render", "f|160|2"]
    for c in (0, 5, 2, 7):
        s += ["pursuit|0|%d|-1" % c, "render"]
    s += ["copidx|0", "cop|0|1", "pursuit|1|4|-1", "render", "copidx|-1",
          "render"]
    # The AI's cars and the cops hidden and shown.
    for c, r, v in ((2, 0, 1), (3, 1, 0), (4, 0x80, 1), (5, 1, 2),
                    (6, 0, 0), (2, 1, 0x80000000)):
        s += ["cvis|%d|%#x|%#x" % (c, r, v), "render"]
    for c in range(7):
        s += ["cvis|%d|1|1" % c]
    for ai, cop, tr in ((2, 2, 2), (5, 2, 7), (0, 7, 8), (3, 3, 6),
                        (2, 5, 4)):
        s += ["wpos|%d|%d|%d" % (ai, cop, tr), "render"]
    s += ["wpos|2|5|7"]
    # The roadblocks.
    for r, (x, y, a) in enumerate(((50.0, 450.0, 0x0000),
                                   (-100.0, 380.0, 0x4000),
                                   (120.0, 600.0, 0x9abc),
                                   (5000.0, 5000.0, 0x1111))):
        s += ["rb|%d|%s|%s|%#x" % (r, F(x), F(y), a)]
    s += ["pursuit|0|3|0", "pursuit|1|-1|-1", "pursuit|2|4|2",
          "pursuit|3|-1|1"]
    for order in ((0, 1, 2, 3), (1,), (), (3, 2, 1, 0), (2,), (0, 2)):
        s += ["plist" + "".join("|%d" % k for k in order), "render"]
    s += ["plist|0|1|2|3", "f|160|4", "render", "f|160|5", "render",
          "f|160|2", "cmgr|0", "render", "cmgr|1", "plist", "copidx|-1"]
    # A ghost, turned and still.
    s += ["ghost|1", "gmat|%s|%s|%s|%s|%s" % (F(0.6), F(-0.8), F(-20.0),
                                              F(440.0), F(3.0))]
    for m in (2, 4, 5, 0):
        s += ["f|160|%d" % m, "render"]
    s += ["gmat|%s|%s|%s|%s|%s" % (F(-1.0), F(0.0), F(5000.0), F(0.0),
                                   F(0.0)), "render", "ghost|0", "f|160|2"]
    # One player: none, no car, hidden, a cop car, pursued.
    s += ["players|1|-1|-1|-1|-1", "render", "players|1|0|-1|0|-1",
          "pcar|0|-1", "render", "pcar|0|0", "cvis|0|0|1", "render",
          "cvis|0|1|0", "render", "cvis|0|1|1", "cusage|0|1", "render",
          "cusage|0|2", "render", "cusage|0|0", "cmgr|1", "copidx|3",
          "cop|3|0", "pursuit|0|0|-1", "render", "cusage|0|1", "render",
          "cusage|0|0", "copidx|-1", "players|1|1|-1|0|-1", "render"]
    # Two players, in both orders and level.
    s += ["players|2|0|1|0|1", "f|160|7"]
    for p0, p1 in ((1, 2), (2, 1), (3, 3), (-1, 5), (0x7f, 0x80)):
        s += ["crace|0|%#x" % (p0 & 0xff), "crace|1|%#x" % (p1 & 0xff),
              "render"]
    s += ["crace|0|1", "crace|1|2"]
    for v0, v1 in ((0, 1), (1, 0), (0, 0)):
        s += ["cvis|0|%d|1" % v0, "cvis|1|1|%d" % v1, "render"]
    s += ["cvis|0|1|1", "cvis|1|1|1", "cusage|1|1", "render", "cusage|0|1",
          "render", "copidx|3", "pursuit|0|1|-1", "render",
          "pursuit|0|0|-1", "crace|0|4", "render", "copidx|-1",
          "cusage|0|0", "cusage|1|0", "players|2|0|1|1|0", "render"]
    s += ["players|0|0|1|0|1", "render", "players|3|0|1|0|1", "render",
          "players|1|0|-1|0|-1", "f|160|2"]
    # Point to point: the finish line too.
    s += ["p2p|1", "render", "lines|0xffff|0x0001", "render", "p2p|0x100",
          "render", "f|160|5", "render", "p2p|1",
          "sline|%s|%s|%s|%s" % (F(-30.0), F(395.0), F(5000.0), F(0.0)),
          "render", "p2p|0", "f|160|2"]
    # The camera turning while the map scrolls.
    w = 1000
    for k in range(6):
        a = k * 2 * math.pi / 5.0
        w += 120
        s += ["camdir|%s|%s|%s" % (F(math.cos(a)), F(math.sin(a)), F(0.0)),
              "world|%d" % w, "render"]
    # A missing START_LINE texture.
    s += ["mask|0x20", "fill", "ctor|1|1|1", "f|160|2", "render",
          "mask|0", "init"]
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
    s += scenario_side()
    s += scenario_centroid()
    s += scenario_m2s()
    s += scenario_clip()
    s += scenario_overlay()
    s += scenario_drawmap()
    s += scenario_ipp()
    s += scenario_marker()
    s += scenario_render()
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
        self.race = e.alloc(1720, align=16)
        self.texs = [e.alloc(16, align=16) for _ in TEX_NAMES]
        self.scratch = e.alloc(64, align=16)
        self.pcar = e.alloc(2400, align=16)
        self.poly = e.alloc(160, align=16)
        self.pts = e.alloc(64, align=16)
        self.buf = e.alloc(128, align=16)
        self.world = e.alloc(112, align=16)
        self.pool = [e.alloc(2400, align=16) for _ in range(NUM_POOL)]
        self.types = [e.alloc(1344, align=16) for _ in range(NUM_POOL)]
        self.racing = [e.alloc(192, align=16) for _ in range(NUM_POOL)]
        self.players = [e.alloc(256, align=16) for _ in range(2)]
        self.ghost = e.alloc(128, align=16)
        self.mgr = e.alloc(64, align=16)
        self.cops = [e.alloc(32, align=16) for _ in range(7)]
        self.pursuits = [e.alloc(32, align=16) for _ in range(4)]
        self.rbs = [e.alloc(120, align=16) for _ in range(4)]
        self.pattern = e.alloc(16, align=16)
        for a, n in ((self.track, 176), (self.car, 2400),
                     (self.player, 256), (self.view, 256),
                     (self.camera, 128), (self.mover, 256),
                     (self.race, 1720), (self.pcar, 2400), (self.poly, 160),
                     (self.world, 112), (self.ghost, 128), (self.mgr, 64)):
            e.write(a, bytes(n))
        for group, n in ((self.pool, 2400), (self.types, 1344),
                         (self.racing, 192), (self.players, 256),
                         (self.cops, 32), (self.pursuits, 32),
                         (self.rbs, 120)):
            for a in group:
                e.write(a, bytes(n))
        for i in range(NUM_POOL):
            e.put32(self.pool[i] + 12, self.types[i])
            e.put32(self.pool[i] + 28, self.racing[i])
        e.put32(self.mgr + 12, -1)
        e.put32(self.mgr + 44, self.mgr + 44)
        e.put32(self.mgr + 48, self.mgr + 44)
        e.write(self.pattern, bytes([0xa1, 0xb2, 0xc3, 0]))
        for g in (CURRENT_WORLD, COP_MANAGER, NUM_PLAYERS, BY_INDEX,
                  BY_INDEX + 4, BY_NUMBER, BY_NUMBER + 4):
            e.put32(g, 0)
        e.put32(self.view + 60, self.view + 60)
        e.put32(self.view + 64, self.view + 60)
        e.put32(self.mover + 24, self.camera)
        e.put32(CURRENT_RACE, self.race)
        e.put32(WORLD_TIMER, 0)
        e.put32(POINT2POINT, 0)
        self.mask = 0
        self.last = None
        self.last_poly = None
        self.names = {self.track: "track", self.car: "car",
                      self.player: "player", self.pcar: "pcar"}
        for i, a in enumerate(self.texs):
            self.names[a] = "tex%d" % i
        for i, a in enumerate(self.pool):
            self.names[a] = "c%d" % i
        e.stub(S_TEXINFO, self.s_texinfo)
        e.stub(S_GETVIEW, self.s_getview)
        e.stub(S_RENDER, self.s_render)
        self.fill()
        self.fill_poly()

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

    def s_render(self, em):
        t = em.reg[5] & M32
        name = "0" if t == 0 else self.names.get(t, "?%08x" % t)
        self.emit("  render %s %d%s" % (name, s32(em.reg[6]),
                                        self.poly_fields(em.reg[4] & M32)))

    # ---- output

    def ptr(self, off, w):
        if w == 0:
            return "0"
        if w == (0xa5000000 + off) & M32:
            return "junk"
        return self.names.get(w, "?%08x" % w)

    def poly_fields(self, a):
        # As the harness prints an ePoly: retail's offsets 16 to 152, and
        # whether pDynamicFrameMemory is set.
        e = self.e
        parts = ["%08x" % e.u32(a + o) for o in range(16, 128, 4)]
        b = e.read(a + 128, 28)
        parts += ["%02x%02x%02x%02x" % tuple(b[4 * i:4 * i + 4])
                  for i in range(4)]
        parts += ["%d" % b[16 + k] for k in range(9)]
        parts += ["%d" % (e.u32(a + 156) != 0)]
        return " " + " ".join(parts)

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
        line = "  poly" + self.poly_fields(self.poly)
        if line != self.last_poly:
            self.last_poly = line
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

    def fill_poly(self):
        for o in range(16, 156, 4):
            self.e.put32(self.poly + o, 0xa5000000 + o)
        self.e.put32(self.poly + 156, 0)

    def tex_arg(self, w):
        i = s32(w)
        return self.texs[i] if 0 <= i < len(self.texs) else 0

    def car_arg(self, w):
        i = s32(w)
        return self.pool[i] if 0 <= i < NUM_POOL else 0

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
        elif o == "mode":
            n = v(3)
            e.write(MODES + 68 * v(1) + v(2),
                    struct.pack("<I", v(4))[:n])
        elif o == "pos":
            e.put32(self.car + 96, v(1))
            e.put32(self.car + 100, v(2))
        elif o == "ppos":
            e.put32(self.pcar + 96, v(1))
            e.put32(self.pcar + 100, v(2))
        elif o == "pursued":
            e.put32(self.map + 144, self.pcar if v(1) else 0)
        elif o == "poly":
            self.fill_poly()
        elif o == "pv":
            e.put32(self.poly + 16 + 16 * v(1), v(2))
            e.put32(self.poly + 20 + 16 * v(1), v(3))
        elif o == "puv":
            for k in range(3):
                e.put32(self.poly + 80 + 12 * v(1) + 4 * k, v(2 + k))
        elif o == "pc":
            e.put32(self.poly + 128 + 4 * v(1), v(2))
        elif o == "m2s":
            p = self.pts
            for i in range(4):
                for k in range(3):
                    e.put32(p + 16 * i + 4 * k, v(1 + 3 * i + k))
            e.call(F_M2S, self.map, self.poly, p, p + 16, p + 32, p + 48,
                   limit=1000000)
            self.emit("  pts " + " ".join(
                "%08x" % e.u32(p + 16 * i + 4 * k)
                for i in range(4) for k in range(3)))
        elif o == "side":
            p = self.scratch
            for k in range(6):
                e.put32(p + 4 * k, v(1 + k))
            r = e.call(F_SIDE, p, p + 8, p + 16, limit=10000)
            self.emit("  side %d" % r)
        elif o == "centroid":
            p, q = self.scratch, self.scratch + 32
            for k in range(8):
                e.put32(p + 4 * k, v(1 + k))
            e.put32(q, 0x7f7f0051)
            e.put32(q + 4, 0x7f7f0052)
            e.call(F_CENTROID, q, p, limit=10000)
            self.emit("  centroid %08x %08x" % (e.u32(q), e.u32(q + 4)))
        elif o == "clip":
            e.call(F_CLIP, self.map, self.poly, self.tex_arg(v(1)), v(2),
                   limit=10000000)
        elif o == "overlay":
            e.call(F_OVERLAY, self.map, self.tex_arg(v(1)), v(2),
                   limit=1000000)
        elif o == "drawmap":
            c, q = self.scratch, self.scratch + 16
            e.put32(c, 0x7f7f0031)
            e.put32(c + 4, 0x7f7f0032)
            for k in range(4):
                e.put32(q + 8 * k, 0x7f7f0040 + 2 * k)
                e.put32(q + 8 * k + 4, 0x7f7f0041 + 2 * k)
            e.call(F_DRAWMAP, self.map, c, q, v(1) & 0xffff, limit=10000000)
            self.emit("  drawmap " + " ".join(
                "%08x" % e.u32(a_) for a_ in
                [c, c + 4] + [q + 4 * k for k in range(8)]))
        elif o == "tables":
            tables = True
        elif o == "ipp":
            p, q = self.buf, self.buf + 16
            n = s32(v(1))
            e.put32(p, v(2))
            e.put32(p + 4, v(3))
            for k in range(min(n, 8)):
                e.put32(q + 8 * k, v(4 + 2 * k))
                e.put32(q + 8 * k + 4, v(5 + 2 * k))
            r = e.call(F_IPP, p, q, v(1), limit=100000)
            self.emit("  ipp %d" % r)
        elif o == "marker":
            p, c, q = self.buf, self.buf + 16, self.buf + 32
            for k in range(3):
                e.put32(p + 4 * k, v(1 + k))
            e.put32(c, v(4))
            e.put32(c + 4, v(5))
            for k in range(8):
                e.put32(q + 4 * k, v(13 + k))
            col = s32(v(7))
            colour = self.pattern if col < 0 else COLOURS + 3 * col
            e.put32(e.reg[29], v(10) & 0xffff)
            e.fpr[12] = v(11)
            e.fpr[13] = v(12)
            e.call(F_MARKER, self.map, p, c, v(6) & 0xffff, q, colour, v(8),
                   self.tex_arg(v(9)), limit=10000000)
        elif o == "render":
            e.call(F_RENDER, self.map, limit=100000000)
        elif o == "wnull":
            e.put32(CURRENT_WORLD, self.world if v(1) else 0)
        elif o == "rnull":
            e.put32(CURRENT_RACE, self.race if v(1) else 0)
        elif o == "cmgr":
            e.put32(COP_MANAGER, self.mgr if v(1) else 0)
        elif o == "wpos":
            for k in range(3):
                e.put32(self.world + 32 + 4 * k, v(1 + k))
        elif o == "wcar":
            e.put32(self.world + 44 + 4 * v(1), self.car_arg(v(2)))
        elif o == "cpos":
            e.put32(self.pool[v(1)] + 96, v(2))
            e.put32(self.pool[v(1)] + 100, v(3))
        elif o == "cang":
            e.write(self.pool[v(1)] + 932, struct.pack("<H", v(2) & 0xffff))
        elif o == "cvis":
            e.mem[self.pool[v(1)] + 1192] = v(2) & 0xff
            e.put32(self.pool[v(1)] + 2164, v(3))
        elif o == "cusage":
            e.put32(self.types[v(1)] + 1336, v(2))
        elif o == "crace":
            e.mem[self.racing[v(1)] + 10] = v(2) & 0xff
        elif o == "pcar":
            e.put32(self.players[v(1)] + 4, self.car_arg(v(2)))
        elif o == "players":
            e.put32(NUM_PLAYERS, v(1))
            for k in range(2):
                ix, bn = s32(v(2 + k)), s32(v(4 + k))
                e.put32(BY_INDEX + 4 * k,
                        self.players[ix] if 0 <= ix < 2 else 0)
                e.put32(BY_NUMBER + 4 * k,
                        self.players[bn] if 0 <= bn < 2 else 0)
        elif o == "copidx":
            e.put32(self.mgr + 12, v(1))
        elif o == "cop":
            k, pu = v(1), s32(v(2))
            if pu == -2:
                e.put32(self.mgr + 16 + 4 * k, 0)
            else:
                e.put32(self.mgr + 16 + 4 * k, self.cops[k])
                e.put32(self.cops[k],
                        self.pursuits[pu] if 0 <= pu < 4 else 0)
        elif o == "pursuit":
            pu, r = v(1), s32(v(3))
            e.put32(self.pursuits[pu] + 16, self.car_arg(v(2)))
            e.put32(self.pursuits[pu] + 20,
                    self.rbs[r] if 0 <= r < 4 else 0)
        elif o == "plist":
            head = self.mgr + 44
            prev = head
            for k in range(1, len(a)):
                node = self.pursuits[v(k)]
                e.put32(prev, node)
                e.put32(node + 4, prev)
                prev = node
            e.put32(prev, head)
            e.put32(head + 4, prev)
        elif o == "rb":
            r = self.rbs[v(1)]
            e.put32(r + 68, v(2))
            e.put32(r + 72, v(3))
            e.write(r + 28, struct.pack("<H", v(4) & 0xffff))
        elif o == "ghost":
            e.put32(self.race + 1660, self.ghost if v(1) else 0)
        elif o == "gmat":
            for k, off in enumerate((32, 36, 80, 84, 88)):
                e.put32(self.ghost + off, v(1 + k))
        elif o == "sline":
            for k in range(4):
                e.put32(self.race + 1640 + 4 * k, v(1 + k))
        elif o == "lines":
            e.write(self.track + 106, struct.pack("<HH", v(1) & 0xffff,
                                                  v(2) & 0xffff))
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
    M("ctor-no-pursued", "    m->CurrentlyPursuedCar = NULL;\n    m->CurrentMode = 6;", "    m->CurrentMode = 6;"),
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

    # MapToScreen.
    M("m2s-no-tilt", "    eRotateX(&tilt, &tilt, info->AngleX);\n", ""),
    M("m2s-x-signed", "h) + (float)(uint16_t)info->X;", "h) + (float)info->X;"),
    M("m2s-y-signed", "h) + (float)(uint16_t)info->Y;", "h) + (float)info->Y;"),
    M("m2s-no-projection", "            p[i]->y * h / (p[i]->z + h)", "            p[i]->y"),
    M("m2s-projection-minus", "            p[i]->x * h / (p[i]->z + h)", "            p[i]->x * h / (h - p[i]->z)"),
    M("m2s-fade-from-1", "        if (0.0f < p[i]->z)", "        if (1.0f < p[i]->z)"),
    M("m2s-fade-half", "(info->Height * 0.666666687f)) * 128.0f);", "(info->Height * 0.5f)) * 128.0f);"),
    M("m2s-fade-127", "(info->Height * 0.666666687f)) * 128.0f);", "(info->Height * 0.666666687f)) * 127.0f);"),
    M("m2s-fade-unsaturated", "(uint8_t)ee_trunc_w(\n                (1.0f", "(uint8_t)(int32_t)(\n                (1.0f"),
    M("m2s-near-127", "            poly->Colours[i][3] = 128;", "            poly->Colours[i][3] = 127;"),

    # GetSideOfLine.
    M("side-cross-sign", "    float c = ex * dy + ey * -dx;", "    float c = ex * dy - ey * -dx;"),
    M("side-on-line-1", "    if (c < 0.0f)\n        return -1;\n    return 0;", "    if (c < 0.0f)\n        return -1;\n    return 1;"),
    M("side-le", "    if (0.0f < c)\n        return 1;", "    if (0.0f <= c)\n        return 1;"),

    # CalculateCentroidOfQuad.
    M("centroid-third", "    const float third = 0.333333343f;", "    const float third = 0.3333333f;"),
    M("centroid-b-from-1", "    float bx = ((q[0].x + q[2].x) + q[3].x) * third;", "    float bx = ((q[1].x + q[2].x) + q[3].x) * third;"),
    M("centroid-assoc", "    float ay = ((q[0].y + q[1].y) + q[2].y) * third;", "    float ay = (q[0].y + (q[1].y + q[2].y)) * third;"),

    # ClipPolygon.
    M("clip-corner-hh", "    clip[0].x = cx - hw;", "    clip[0].x = cx - hh;"),
    M("clip-cx-signed", "    cx = (float)(uint16_t)info->ClippingX;\n    cy = (float)(uint16_t)info->ClippingY;\n    clip[0]", "    cx = (float)info->ClippingX;\n    cy = (float)(uint16_t)info->ClippingY;\n    clip[0]"),
    M("clip-cy-signed", "    cy = (float)(uint16_t)info->ClippingY;\n    clip[0]", "    cy = (float)info->ClippingY;\n    clip[0]"),
    M("clip-on-line-out", "!= -1;\n            int in_j", "== 1;\n            int in_j"),
    M("clip-prev-1", "    prev = 3;", "    prev = 1;"),
    M("clip-prev-stays", "        prev = k;\n", ""),
    M("clip-t-num-plus", "lx - (pts[i].x - a->x) * ly)", "lx + (pts[i].x - a->x) * ly)"),
    M("clip-t-den-plus", "/ (dx * ly - (pts[j].y - pts[i].y) * lx);", "/ (dx * ly + (pts[j].y - pts[i].y) * lx);"),
    M("clip-ip-y-from-j", "ip.y = pts[i].y + t * (pts[j].y - pts[i].y);", "ip.y = pts[j].y + t * (pts[j].y - pts[i].y);"),
    M("clip-uv-z-flat", "iuv.z = uvs[i].z + t * (uvs[j].z - uvs[i].z);", "iuv.z = uvs[i].z;"),
    M("clip-uv-x-from-y", "iuv.x = uvs[i].x + t * (uvs[j].x - uvs[i].x);", "iuv.x = uvs[i].y + t * (uvs[j].x - uvs[i].x);"),
    M("clip-alpha-flat", "+ t * (float)((int32_t)alphas[j] - (int32_t)alphas[i]));", "+ 0.0f);"),
    M("clip-alpha-unsigned", "(float)((int32_t)alphas[j] - (int32_t)alphas[i])", "(float)(uint8_t)(alphas[j] - alphas[i])"),
    M("clip-emit-i", "            if (in_j)\n", "            if (in_i)\n"),
    M("clip-top-le", "        if (outPts[i].y < outPts[top].y)", "        if (outPts[i].y <= outPts[top].y)"),
    M("clip-top-exact", "outPts[top].y) <= 0.001f", "outPts[top].y) <= 0.0f"),
    M("clip-top-0.01", "outPts[top].y) <= 0.001f", "outPts[top].y) <= 0.01f"),
    M("clip-top-rightmost", "&& outPts[i].x < outPts[top].x)", "&& outPts[i].x > outPts[top].x)"),
    M("clip-top-first", "    top = 0;\n    for (i = 1; i < count; i++) {", "    top = 0;\n    for (i = count; i < count; i++) {"),
    M("clip-fan-start-2", "    start = 1;\n    while", "    start = 2;\n    while"),
    M("clip-fan-short", "    while (start < count - 1) {", "    while (start < count - 2) {"),
    M("clip-fan-clamp-le", "            if (!(last < count))", "            if (!(last <= count))"),
    M("clip-fan-no-wrap", "                idx -= count;", "                idx = count - 1;"),
    M("clip-fan-step", "        start = last;\n", "        start = last + 1;\n"),
    M("clip-rgb-0", "                out.Colours[s][c] = poly->Colours[s][c];", "                out.Colours[s][c] = poly->Colours[0][c];"),
    M("clip-rgb-top", "            out.Colours[0][c] = poly->Colours[0][c];", "            out.Colours[0][c] = poly->Colours[top & 3][c];"),
    M("clip-layer-14", "    z = (float)layer;\n    start = 1;", "    z = 14.0f;\n    start = 1;"),
    M("clip-no-flailer", "        out.Flailer = 1;\n", ""),
    M("clip-flags-1", "            gEPolyRenderFn(&out, tex, 0);", "            gEPolyRenderFn(&out, tex, 1);"),
    M("clip-top-q-of-v", "        out.UVs[0][2] = outUVs[top].z;", "        out.UVs[0][2] = outUVs[top].y;"),
    M("clip-top-alpha-0", "        out.Colours[0][3] = outAlphas[top];", "        out.Colours[0][3] = outAlphas[0];"),

    # DrawOverOrUnderLay.
    M("overlay-no-border-test", "    if (info->HasBorder == 0)\n        return;\n", ""),
    M("overlay-no-drawn-test", "    if (info->IsDrawn == 0)\n        return;\n    poly.Flailer = 1;", "    poly.Flailer = 1;"),
    M("overlay-z-0", "        poly.Vertices[i].z = z;", "        poly.Vertices[i].z = 0.0f;"),
    M("overlay-corner-2", "    poly.Vertices[2].y = cy + hh;", "    poly.Vertices[2].y = cy - hh;"),
    M("overlay-x-signed", "    cx = (float)(uint16_t)info->ClippingX;\n    cy = (float)(uint16_t)info->ClippingY;\n    poly.", "    cx = (float)info->ClippingX;\n    cy = (float)(uint16_t)info->ClippingY;\n    poly."),
    M("overlay-no-flailer", "    poly.Flailer = 1;\n    if (gEPolyRenderFn != NULL)\n        gEPolyRenderFn(&poly, tex, 0);", "    if (gEPolyRenderFn != NULL)\n        gEPolyRenderFn(&poly, tex, 0);"),

    # DrawMap.
    M("dm-no-drawn-test", "    if (info->IsDrawn == 0)\n        return;\n    epoly_init(&poly);\n    carUV", "    epoly_init(&poly);\n    carUV"),
    M("dm-always-scrolls", "    if (info->HasScrolling != 0) {\n        if (info->ZoomToKeepPursuedCarInView", "    if (1) {\n        if (info->ZoomToKeepPursuedCarInView"),
    M("dm-zoom-untested", "        if (info->ZoomToKeepPursuedCarInView != 0\n            && m->CurrentlyPursuedCar", "        if (m->CurrentlyPursuedCar"),
    M("dm-dist-dy-x", "            float dy = a->y - b->y;", "            float dy = a->x - b->y;"),
    M("dm-dist-squared", "            float dist = sqrtf(dx * dx + dy * dy);", "            float dist = dx * dx + dy * dy;"),
    M("dm-zoom-ratio-flipped", "* (info->Width / info->ClippingWidth) + 0.1f;", "* (info->ClippingWidth / info->Width) + 0.1f;"),
    M("dm-zoom-tenth", "* (info->Width / info->ClippingWidth) + 0.1f;", "* (info->Width / info->ClippingWidth) + 0.2f;"),
    M("dm-zoom-width", "            fwd = dist / m->CurrentTrack->TrackMapCalibrationMapWidthMetres", "            fwd = dist / 2400.0f"),
    M("dm-side-forward", "            side = (fwd + back) * 0.5f;", "            side = fwd;"),
    M("dm-current-forward-back", "        m->CurrentViewDistanceForward = fwd;", "        m->CurrentViewDistanceForward = back;"),
    M("dm-no-current-back", "        m->CurrentViewDistanceBackward = back;\n", ""),
    M("dm-outer-1.1", "side * 1.2f, side * 1.2f, angle, outer);", "side * 1.1f, side * 1.2f, angle, outer);"),
    M("dm-box-angle-0", "fwd, back, side, side, angle, box);", "fwd, back, side, side, 0, box);"),
    M("dm-unit-box-x", "            box[i].x = (i == 1 || i == 2) ? 1.0f : 0.0f;", "            box[i].x = (i == 1 || i == 3) ? 1.0f : 0.0f;"),
    M("dm-unit-no-outer", "            outer[i] = box[i];\n", ""),
    M("dm-centroid-outer", "    calculate_centroid_of_quad(centre, box);", "    calculate_centroid_of_quad(centre, outer);"),
    M("dm-height-of-width", "    hh = info->Height * 0.5f;\n    p[0]", "    hh = info->Width * 0.5f;\n    p[0]"),
    M("dm-p1-x", "    p[1].x = hw;", "    p[1].x = -hw;"),
    M("dm-no-alpha", "(uint8_t)ee_trunc_w((float)poly.Colours[i][3] * info->Alpha);", "(uint8_t)ee_trunc_w((float)poly.Colours[i][3] * 1.0f);"),
    M("dm-alpha-unsaturated", "(uint8_t)ee_trunc_w((float)poly.Colours[i][3] * info->Alpha);", "(uint8_t)(int32_t)((float)poly.Colours[i][3] * info->Alpha);"),
    M("dm-q-flat", "        float r = 1.0f / (p[i].z + info->H);", "        float r = 1.0f / info->H;"),
    M("dm-q-not-scaled", "        poly.UVs[i][2] *= r;\n", ""),
    M("dm-layer-13", "    trackmap_clip_polygon(m, &poly, m->TrackMapTexture, 14);", "    trackmap_clip_polygon(m, &poly, m->TrackMapTexture, 13);"),
    M("dm-no-car-uv", "    trackmap_get_car_uv_position(m, &carUV, &m->CarToTrack->State.Position);\n", ""),

    # IsPointInPoly.
    M("ipp-lower-lt", "        if ((poly[i].y <= p->y && p->y < poly[j].y)", "        if ((poly[i].y < p->y && p->y < poly[j].y)"),
    M("ipp-upper-le", "            || (poly[j].y <= p->y && p->y < poly[i].y)) {", "            || (poly[j].y <= p->y && p->y <= poly[i].y)) {"),
    M("ipp-x-le", "            if (p->x < (poly[j].x - poly[i].x)", "            if (p->x <= (poly[j].x - poly[i].x)"),
    M("ipp-no-pi-x", "                       / (poly[j].y - poly[i].y) + poly[i].x)", "                       / (poly[j].y - poly[i].y))"),
    M("ipp-j-from-0", "    int32_t c = 0, i, j = n - 1;", "    int32_t c = 0, i, j = 0;"),
    M("ipp-j-stays", "        j = i;\n    }\n    return c;", "    }\n    return c;"),
    M("ipp-sets", "                c ^= 1;", "                c = 1;"),

    # DrawMarker.
    M("mk-no-drawn-test", "    if (info->IsDrawn == 0)\n        return;\n    uv.x = 0.0f;", "    uv.x = 0.0f;"),
    M("mk-of-current-mode", "        &TrackMapModeInfo[m->CurrentlyDisplayedMode];\n    ePoly    poly;\n    bMatrix4 rot;", "        &TrackMapModeInfo[m->CurrentMode];\n    ePoly    poly;\n    bMatrix4 rot;"),
    M("mk-no-in-test", "    if (is_point_in_poly(&uv, outer, 4) == 0)\n        return;\n", ""),
    M("mk-in-3", "    if (is_point_in_poly(&uv, outer, 4) == 0)", "    if (is_point_in_poly(&uv, outer, 3) == 0)"),
    M("mk-turn-not-negated", "    eRotateZ(&rot, &rot, (uint16_t)-angle);", "    eRotateZ(&rot, &rot, angle);"),
    M("mk-centre-y-of-x", "    v.y = uv.y - centre->y;", "    v.y = uv.y - centre->x;"),
    M("mk-not-turned", "    eMulVector3(&v, &rot, &v);\n    uv.x = v.x;", "    uv.x = v.x;"),
    M("mk-always-scrolls", "    if (info->HasScrolling != 0) {\n        float d", "    if (1) {\n        float d"),
    M("mk-scroll-forward-twice", "                + m->CurrentViewDistanceBackward;", "                + m->CurrentViewDistanceForward;"),
    M("mk-scroll-x-unscaled", "        uv.x = v.x / d;\n", ""),
    M("mk-scroll-reciprocal", "        uv.y = v.y / d;", "        uv.y = v.y * (1.0f / d);"),
    M("mk-box-width-height-swapped", "    trackmap_get_box_on_map(m, &uv, height * 0.5f, height * 0.5f,\n                            width * 0.5f, width * 0.5f, markerAngle, box);",
      "    trackmap_get_box_on_map(m, &uv, width * 0.5f, width * 0.5f,\n                            height * 0.5f, height * 0.5f, markerAngle, box);"),
    M("mk-box-forward-whole", "    trackmap_get_box_on_map(m, &uv, height * 0.5f, height * 0.5f,", "    trackmap_get_box_on_map(m, &uv, height, height * 0.5f,"),
    M("mk-box-not-turned", "width * 0.5f, width * 0.5f, markerAngle, box);", "width * 0.5f, width * 0.5f, 0, box);"),
    M("mk-x-not-negated", "        poly.Vertices[i].x = -box[i].x * info->Width;", "        poly.Vertices[i].x = box[i].x * info->Width;"),
    M("mk-y-by-width", "        poly.Vertices[i].y = -box[i].y * info->Height;", "        poly.Vertices[i].y = -box[i].y * info->Width;"),
    M("mk-z-1", "        p[i].z = 0.0f;\n    }\n    trackmap_map_to_screen", "        p[i].z = 1.0f;\n    }\n    trackmap_map_to_screen"),
    M("mk-green-of-red", "        poly.Colours[i][1] = colour->Green;", "        poly.Colours[i][1] = colour->Red;"),
    M("mk-no-blue", "        poly.Colours[i][2] = colour->Blue;\n", ""),
    M("mk-layer-14", "    trackmap_clip_polygon(m, &poly, tex, layer);", "    trackmap_clip_polygon(m, &poly, tex, 14);"),

    # The dots' turn, the players' and the cars' colours and layers.
    M("dot-always-turns", "    if (TrackMapModeInfo[m->CurrentlyDisplayedMode].HasRotatingCarDots == 0)\n        return 0;\n", ""),
    M("dot-heading-added", "TrackMapCalibrationRotation - heading\n", "TrackMapCalibrationRotation + heading\n"),
    M("dot-no-quarter", "                      - angle + 16384);\n}", "                      - angle);\n}"),
    M("player-pursued-layer-1", "        layer = 3;\n    } else if", "        layer = 1;\n    } else if"),
    M("player-no-cop-colour", "    } else if (c->pCarTypeInfo->UsageType == CAR_USAGE_TYPE_COP) {\n        marker = TRACKMAP_MARKER_PLAYER_COP;\n    }", "    }"),
    M("player-cop-over-pursued", "    } else if (c->pCarTypeInfo->UsageType", "    }\n    if (c->pCarTypeInfo->UsageType"),
    M("player-cop-is-2", "UsageType == CAR_USAGE_TYPE_COP) {", "UsageType == 2) {"),
    M("car-no-render-test", "    if (c->RenderingEnabled == 0 || c->bVisibleOnTrackMap == 0)\n        return;", "    if (c->bVisibleOnTrackMap == 0)\n        return;"),
    M("car-no-visible-test", "    if (c->RenderingEnabled == 0 || c->bVisibleOnTrackMap == 0)\n        return;", "    if (c->RenderingEnabled == 0)\n        return;"),
    M("car-pursued-always", "    if (pursued && c == m->CurrentlyPursuedCar) {", "    if (c == m->CurrentlyPursuedCar) {"),
    M("car-pursued-never", "    if (pursued && c == m->CurrentlyPursuedCar) {", "    if (pursued && c == NULL) {"),
    M("car-pursued-layer-1", "        layer = 3;\n    }\n    trackmap_draw_marker", "        layer = 1;\n    }\n    trackmap_draw_marker"),
    M("line-layer-12", "                         13, m->StartFinishLineTexture,", "                         12, m->StartFinishLineTexture,"),
    M("line-not-turned", "                         (uint16_t)(lineAngle + turn),", "                         (uint16_t)lineAngle,"),
    M("line-size-swapped", "                         info->StartFinishLineWidth,\n                         info->StartFinishLineHeight);",
      "                         info->StartFinishLineHeight,\n                         info->StartFinishLineWidth);"),

    # Render.
    M("render-no-data-test", "    if (m->SufficientDataToRenderMe == 0 || pCurrentWorld == NULL\n", "    if (pCurrentWorld == NULL\n"),
    M("render-no-world-test", "    if (m->SufficientDataToRenderMe == 0 || pCurrentWorld == NULL\n", "    if (m->SufficientDataToRenderMe == 0\n"),
    M("render-no-race-test", "        || pCurrentRace == NULL)\n        return;", "        )\n        return;"),
    M("render-pursued-kept", "    m->CurrentlyPursuedCar = NULL;\n    m->CurrentlyDisplayedMode = m->CurrentMode;", "    m->CurrentlyDisplayedMode = m->CurrentMode;"),
    M("render-off-targets", "    if (m->CurrentMode != 6 && pCopManager != NULL) {", "    if (pCopManager != NULL) {"),
    M("render-no-chase-targets", "            if (m->CurrentlyPursuedCar != NULL)\n                m->CurrentlyDisplayedMode", "            m->CurrentlyDisplayedMode"),
    M("render-targets-large", "                m->CurrentlyDisplayedMode = TRACKMAP_MODE_COP_TARGETING;", "                m->CurrentlyDisplayedMode = TRACKMAP_MODE_COP_LARGE;"),
    M("render-no-underlay", "    trackmap_draw_over_or_under_lay(m, m->UnderlayTexture, 15);\n", ""),
    M("render-underlay-14", "    trackmap_draw_over_or_under_lay(m, m->UnderlayTexture, 15);", "    trackmap_draw_over_or_under_lay(m, m->UnderlayTexture, 14);"),
    M("render-overlay-1", "    trackmap_draw_over_or_under_lay(m, m->OverlayTexture, 0);", "    trackmap_draw_over_or_under_lay(m, m->OverlayTexture, 1);"),
    M("render-turn-plus", "    turn = (uint16_t)(m->CurrentTrack->TrackMapCalibrationRotation - angle);", "    turn = (uint16_t)(m->CurrentTrack->TrackMapCalibrationRotation + angle);"),
    M("render-finish-always", "    if (TheRaceParameters.Point2Point != 0)\n        draw_line", "    if (1)\n        draw_line"),
    M("render-finish-byte", "    if (TheRaceParameters.Point2Point != 0)\n        draw_line", "    if ((int8_t)TheRaceParameters.Point2Point != 0)\n        draw_line"),
    M("render-finish-start-angle", "                  m->CurrentTrack->TrackMapFinishLineAngle, turn, &centre,", "                  m->CurrentTrack->TrackMapStartLineAngle, turn, &centre,"),
    M("render-start-finish-angle", "              m->CurrentTrack->TrackMapStartLineAngle, turn, &centre, angle,", "              m->CurrentTrack->TrackMapFinishLineAngle, turn, &centre, angle,"),
    M("render-finish-at-start", "        draw_line(m, &pCurrentRace->FinishLinePosition,", "        draw_line(m, &pCurrentRace->StartLinePosition,"),
    M("render-dots-swapped", "    dots = info->HasRotatingCarDots != 0 ? m->CarMarkerRotatingTexture\n                                         : m->CarMarkerNonrotatingTexture;",
      "    dots = info->HasRotatingCarDots != 0 ? m->CarMarkerNonrotatingTexture\n                                         : m->CarMarkerRotatingTexture;"),
    M("render-ai-from-0", "        draw_car(m, pCurrentWorld->CarTable[pCurrentWorld->AICarPos + i],", "        draw_car(m, pCurrentWorld->CarTable[i],"),
    M("render-ai-to-traffic", "    for (i = 0; i < pCurrentWorld->CopCarPos - pCurrentWorld->AICarPos; i++)", "    for (i = 0; i < pCurrentWorld->TrafficCarPos - pCurrentWorld->AICarPos; i++)"),
    M("render-ai-cop-colour", "                 TRACKMAP_MARKER_AI, 5, 1,", "                 TRACKMAP_MARKER_COP, 5, 1,"),
    M("render-ai-layer-6", "                 TRACKMAP_MARKER_AI, 5, 1,", "                 TRACKMAP_MARKER_AI, 6, 1,"),
    M("render-ai-not-pursued", "                 TRACKMAP_MARKER_AI, 5, 1,", "                 TRACKMAP_MARKER_AI, 5, 0,"),
    M("render-cops-from-ai", "        draw_car(m, pCurrentWorld->CarTable[pCurrentWorld->CopCarPos + i],", "        draw_car(m, pCurrentWorld->CarTable[pCurrentWorld->AICarPos + i],"),
    M("render-cops-pursued", "                 TRACKMAP_MARKER_COP, 6, 0,", "                 TRACKMAP_MARKER_COP, 6, 1,"),
    M("render-cops-layer-5", "                 TRACKMAP_MARKER_COP, 6, 0,", "                 TRACKMAP_MARKER_COP, 5, 0,"),
    M("render-rb-no-manager-test", "    if (pCopManager != NULL) {\n        for (i = 0;", "    {\n        for (i = 0;"),
    M("render-rb-pre-increment", "copmanager_get_active_road_block(pCopManager, i++);", "copmanager_get_active_road_block(pCopManager, ++i);"),
    M("render-rb-angle-added", "                           - rb->aTrackMapIconAngle - angle + 16384),", "                           + rb->aTrackMapIconAngle - angle + 16384),"),
    M("render-rb-no-quarter", "                           - rb->aTrackMapIconAngle - angle + 16384),", "                           - rb->aTrackMapIconAngle - angle),"),
    M("render-rb-dot-size", "                info->StartFinishLineWidth, info->StartFinishLineHeight);\n        }", "                info->CarDotSize, info->CarDotSize);\n        }"),
    M("render-rb-layer-8", "                &TrackMapMarkerInfo[TRACKMAP_MARKER_ROADBLOCK], 7,", "                &TrackMapMarkerInfo[TRACKMAP_MARKER_ROADBLOCK], 8,"),
    M("render-rb-dot-texture", "                m->RoadblockTexture,\n", "                dots,\n"),
    M("render-ghost-always-turns", "        if (info->HasRotatingCarDots != 0)\n            a = (uint16_t)", "        if (1)\n            a = (uint16_t)"),
    M("render-ghost-atan-swapped", "bATan(g->Matrix.v0.x, g->Matrix.v0.y)", "bATan(g->Matrix.v0.y, g->Matrix.v0.x)"),
    M("render-ghost-v1", "bATan(g->Matrix.v0.x, g->Matrix.v0.y)", "bATan(g->Matrix.v1.x, g->Matrix.v1.y)"),
    M("render-ghost-at-v2", "(const bVector3 *)(const void *)&g->Matrix.v3,", "(const bVector3 *)(const void *)&g->Matrix.v2,"),
    M("render-ghost-layer-5", "&TrackMapMarkerInfo[TRACKMAP_MARKER_GHOST], 4,", "&TrackMapMarkerInfo[TRACKMAP_MARKER_GHOST], 5,"),
    M("render-ghost-ai-colour", "&TrackMapMarkerInfo[TRACKMAP_MARKER_GHOST], 4,", "&TrackMapMarkerInfo[TRACKMAP_MARKER_AI], 4,"),
    M("render-one-by-number", "        Player *p = PlayerPlayersByIndex[0];", "        Player *p = PlayerPlayersByNumber[0];"),
    M("render-one-no-render-test", "        if (c != NULL && c->RenderingEnabled != 0\n            && c->bVisibleOnTrackMap != 0)", "        if (c != NULL\n            && c->bVisibleOnTrackMap != 0)"),
    M("render-one-no-visible-test", "        if (c != NULL && c->RenderingEnabled != 0\n            && c->bVisibleOnTrackMap != 0)", "        if (c != NULL && c->RenderingEnabled != 0)"),
    M("render-one-layer-2", "            draw_player(m, c, TRACKMAP_MARKER_PLAYER_1, 1, &centre, angle,", "            draw_player(m, c, TRACKMAP_MARKER_PLAYER_1, 2, &centre, angle,"),
    M("render-two-for-three", "    } else if (PlayerNumPlayers == 2) {", "    } else if (PlayerNumPlayers >= 2) {"),
    M("render-two-by-index", "        Car *c2 = PlayerPlayersByNumber[1]->MyCar;", "        Car *c2 = PlayerPlayersByIndex[1]->MyCar;"),
    M("render-two-order-le", "        if (r2->RacePosition < r1->RacePosition) {", "        if (r2->RacePosition <= r1->RacePosition) {"),
    M("render-two-order-flipped", "        if (r2->RacePosition < r1->RacePosition) {", "        if (r1->RacePosition < r2->RacePosition) {"),
    M("render-two-order-unsigned", "        if (r2->RacePosition < r1->RacePosition) {", "        if ((uint8_t)r2->RacePosition < (uint8_t)r1->RacePosition) {"),
    M("render-two-l2-stays", "            l1 = 2;\n            l2 = 1;\n", "            l1 = 2;\n"),
    M("render-two-c1-of-c2", "        if (c1->RenderingEnabled != 0 && c1->bVisibleOnTrackMap != 0)", "        if (c2->RenderingEnabled != 0 && c1->bVisibleOnTrackMap != 0)"),
    M("render-two-c2-no-visible-test", "        if (c2->RenderingEnabled != 0 && c2->bVisibleOnTrackMap != 0)", "        if (c2->RenderingEnabled != 0)"),
    M("render-two-c2-player-1", "            draw_player(m, c2, TRACKMAP_MARKER_PLAYER_2, l2,", "            draw_player(m, c2, TRACKMAP_MARKER_PLAYER_1, l2,"),

    # The roadblock walks.
    M("rbn-all-pursuits", "        if (((tPursuit *)(void *)n)->pRoadBlock != NULL)\n            count++;", "        count++;", "3DS Files/source/copmanager.c"),
    M("rbg-from-1", "    int32_t       k = 0;\n\n    for (n = list->Next; n != list; n = n->Next) {\n        tRoadBlock", "    int32_t       k = 1;\n\n    for (n = list->Next; n != list; n = n->Next) {\n        tRoadBlock", "3DS Files/source/copmanager.c"),
    M("rbg-counts-empty", "        if (rb == NULL)\n            continue;\n        if (k == i)", "        if (k == i && rb != NULL)", "3DS Files/source/copmanager.c"),
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
