#!/usr/bin/env python3
"""Cross-check 3DS Files/source/weatherman.c (WeatherMan.obj, and
eView::GetWeatherQuery) and efog.c (EcstasyE.obj's fog) against the image
itself, run in mipsemu.

The model is the image: LoaderWeatherMan, UnloaderWeatherMan,
WeatherAddRegion, WeatherRemoveRegion, WeatherSetRegionState,
WeatherSetGroupState, WeatherManQuery, eView::GetWeatherQuery, fpow,
RemapLinearIntoClut8, GetFogPalette, CreateFogPalette,
eAttachDepthIntoAlpha and eAttachFog run as shipped. Stubbed:

    eGetView                the scenario's views, 128 apart
    eGetRenderTarget        a render target of the model's
    bMemSet                 a memset
    AttachImageDataPacket   silent; eAttachFog's names the palette
    eDmaChain::Add          for eAttachFog's packet, the line the port's
                            seam prints: the view, the palette and the
                            ALPHA_1 the packet holds

The harness links weatherman.c and efog.c, gives them eGetView and
eFrameCounter, and prints the same lines; gEFogAttachFn prints the view,
the palette and the ALPHA_1 of the FogModeInfo it is handed. After each
step both dump the five lists walked both ways and every region's links.
The palettes, the queries and the depth palettes are dumped where a step
makes them.

The PICA's side, efog_depth_alpha, efog_colour and efog_keep, has nothing
in the image to run. For it the model is the spec written out here, over
the image's own depth palettes and fog palette: the depth alpha through the
CLUT, and the fraction the GS's ALPHA_1 leaves.

The model's chunk gives each region its own address in its first eight
bytes, where the disc has a PS2 pointer. The image leaves a region of a
type past 3 holding those bytes, and the port links it to itself, so with
them the two unlink it the same way.

Scenarios: TRACKB12's kinds of region at the points that matter; roots
that overlap, tie and touch; hits past three, past a sum of one, with a
fade start past the radius and at 0; each type; types past 3 and below 0;
colours with the top bit of each byte; the chunk at each misalignment,
each version and the wrong type; the region and group states; the tweaker;
the query's cache by frame; each palette mode with the amounts, starts and
powers at their edges; the palettes by view ID; the depth palettes on and
off; eAttachFog for each view state, DrawFog and mode; and the PICA's
colour and fraction for each mode's palette under each blend.

    python tools/weather_check.py
    python tools/weather_check.py --mutate [--only a,b]
    python tools/weather_check.py --dump out/weather
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

HARNESS = "tools/src/weather_test.c"
WMC = "3DS Files/source/weatherman.c"
WMH = "3DS Files/source/weatherman.h"
EFC = "3DS Files/source/efog.c"
EFH = "3DS Files/source/efog.h"
SOURCES = [HARNESS, WMC, EFC, "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c"]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x00328bf0
LISTS = 0x00308fe0
INACTIVE = 0x00323df8
LIST_NAMES = 0x00323e00             # WeatherRainList .. WeatherWindList
CACHE = 0x002d47b8
FRAME = 0x00322740
TW_USE = 0x00323e10                 # then Fog, FogStart, R, G, B
DRAW_FOG = 0x00322bd8
MODE1 = 0x00322bd0
MODE2 = 0x00322bd4
POWER = 0x00322bdc
ENABLE = 0x00322bb8
DIA_BUFFER = 0x00322b8c
FOG_PAL = 0x002da980                # three, then FocusPalettes[0]
UPPER = 0x002d9e20
LOWER = 0x002da220
MODE_INFOS = 0x002d9d30
MAIN_DISP = GP - 25496
DIA_TARGET = GP - 25488
DIA_PACKETS = [GP - k for k in (24672, 24668, 24664, 24660, 24656, 24652,
                                24648)]
DMA_PTR = GP - 20044
DMA_END = GP - 20040
DMA_FAIL = GP - 20028
DMA_WANT = GP - 20024

LOADER = 0x0019dff8
UNLOADER = 0x0019e078
ADD_REGION = 0x0019e0f8
REMOVE_REGION = 0x0019e138
SET_STATE = 0x0019e150
SET_GROUP = 0x0019e198
QUERY = 0x0019e290
GET_QUERY = 0x001123f8
REMAP = 0x00118878
GET_PALETTE = 0x001195f8
FPOW = 0x00119628
CREATE = 0x00119678
DEPTH_INTO_ALPHA = 0x00119330
ATTACH_FOG = 0x00119af8
STATIC_CTOR = 0x0019ebd8

E_GET_VIEW = 0x001071f0
E_GET_TARGET = 0x00104d00
ATTACH_IMAGE = 0x001087e0
DMA_ADD = 0x00103e08
BMEMSET = 0x00238140
FOG_ATTACH_IMAGE_RA = 0x00119bd4
FOG_ADD_RA = 0x00119e08

WEATHER_CHUNK = 0x00034250

# Where the model keeps the scenario's objects.
CHUNK = 0x01003000                  # 16-aligned; the scenario adds 0..12
VIEWS = 0x01010000                  # 128 apart
RTS = 0x01011000                    # 256 apart
CAMS = 0x01012000                   # 512 apart
QS = 0x01014000
PAL = 0x01014100
TMP_VIEW = 0x01014600
POSV = 0x01014700
REMAP_SRC = 0x01015000
REMAP_DST = 0x01015400
CHAIN = 0x01016000
DMA = 0x01020000
DIA_PKT = 0x01130000
RT15 = 0x01131000
MAIN_RT = 0x01132000
NUM_VIEWS = 5

ZS = (0, 1, 16, 63, 64, 100, 575, 576, 640, 1000, 4095, 4096, 8000, 12345,
      16320, 16383, 16384, 30000, 65535)

FPOW_XY = ((0.0, 4.6), (0.5, 4.6), (1.0, 4.6), (0.01, 2.0), (2.0, 0.5),
           (-1.0, 3.0), (1e-3, 1.0), (100.0, 2.0), (0.25, 0.0),
           (1e30, 10.0), (0.75, 4.5999999), (0.9, -2.0), (0.3, 3.1),
           (0.35, 1.7), (0.42, 1.1))

GET_PALETTE_IDS = (-1, 0, 1, 2, 3, 4, 5, 9, 0x7fffffff, -0x80000000)


def fb(x):
    if isinstance(x, int):
        return x & M32
    return struct.unpack("<I", struct.pack("<f", x))[0]


def bf(u):
    return struct.unpack("<f", struct.pack("<I", u & M32))[0]


class Region(object):
    def __init__(self, type=1, group=0, colour=0xff82a0a0, start=246.0,
                 pos=(0.0, 0.0, 0.0), radius=100.0, intensity=0.5,
                 far=None):
        self.type = type
        self.group = group
        self.colour = colour
        self.start = fb(start)
        self.pos = [fb(p) for p in pos]
        self.radius = fb(radius)
        self.intensity = fb(intensity)
        self.far = fb(radius if far is None else far)

    def line(self):
        return "R %d %x %x %x %x %x %x %x %x %x" % (
            self.type, self.group, self.colour, self.start, self.pos[0],
            self.pos[1], self.pos[2], self.radius, self.intensity, self.far)


class Scenario(object):
    def __init__(self, ops, regions=(), version=2, cid=WEATHER_CHUNK, mis=0,
                 tweak=(0, 0.0, 0.0, 0, 0, 0), draw=1, modes=(0, 0),
                 enable=1, power=4.6, views=None, frame=1, pos=()):
        self.ops = ops
        self.regions = list(regions)
        self.version = version
        self.cid = cid
        self.mis = mis
        self.tweak = (tweak[0], fb(tweak[1]), fb(tweak[2])) + tuple(tweak[3:])
        self.draw = draw
        self.modes = modes
        self.enable = enable
        self.power = fb(power)
        v = {0: (1, 1, (0.0, 0.0, 0.0), 0), 1: (1, 1, (0.0, 0.0, 0.0), 0),
             2: (0, 0, (5.0, 0.0, 0.0), 0), 3: (0, 0, (0.0, 0.0, 0.0), 0),
             4: (1, 1, (0.0, 0.0, 0.0), 0)}
        v.update(views or {})
        self.views = [(a, r, tuple(fb(p) for p in xyz), c)
                      for (a, r, xyz, c) in (v[i] for i in range(NUM_VIEWS))]
        self.frame = frame
        self.pos = [tuple(fb(p) for p in xyz) for xyz in pos]

    def lines(self):
        out = ["C %d %x %d" % (self.mis, self.cid, self.version)]
        out += [r.line() for r in self.regions]
        t = self.tweak
        out.append("T %d %x %x %d %d %d" % t)
        out.append("M %d %d %d %d %x" % (self.draw, self.modes[0],
                                         self.modes[1], self.enable,
                                         self.power))
        for i, (a, r, xyz, c) in enumerate(self.views):
            out.append("V %d %d %d %x %x %x %u" % ((i, a, r) + xyz + (c,)))
        out.append("F %u" % self.frame)
        out += ["X %x %x %x" % p for p in self.pos]
        out.append("S %s" % self.ops)
        return out


# TRACKB12's kinds: the main fog, a tunnel, and the smoke.
MAIN = dict(type=1, colour=0xff82a0a0, start=246.0,
            pos=(-294.26, 15.93, -66.81), radius=2005.38, intensity=0.1)
TUNNEL = dict(type=1, colour=0xff876664, start=240.0, pos=(100.0, 0.0, 0.0),
              radius=85.0, intensity=0.0, far=55.0)
SMOKE = dict(type=1, colour=0xff6e6e6e, start=240.0, pos=(300.0, 2.0, 0.0),
             radius=50.0, intensity=0.8, far=25.0)


def script():
    S, R = Scenario, Region
    track = [R(**MAIN), R(**TUNNEL), R(**SMOKE),
             R(**dict(TUNNEL, pos=(110.0, 0.0, 30.0))),
             R(**dict(SMOKE, pos=(290.0, 0.0, 10.0), intensity=0.6))]
    track_pos = [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (160.0, 10.0, 0.0),
                 (300.0, 2.0, 0.0), (310.0, 0.0, 20.0), (105.0, 0.0, 15.0),
                 (5000.0, 0.0, 0.0), (295.0, 1.0, 5.0)]
    roots = [R(pos=(0.0, 0.0, 0.0), radius=100.0, intensity=0.25,
               colour=0x00102030, start=200.0),
             R(pos=(10.0, 0.0, 0.0), radius=100.0, intensity=0.75,
               colour=0x00ffeedd, start=250.0),
             R(pos=(-500.0, 0.0, 0.0), radius=10.0, intensity=1.0)]
    root_pos = [(2.0, 0.0, 0.0), (8.0, 0.0, 0.0), (5.0, 0.0, 0.0),
                (100.0, 0.0, 0.0), (-100.0, 0.0, 0.0), (5.0, 99.0, 0.0),
                (-500.0, 0.0, 10.0), (-500.0, 0.0, 9.99)]
    hits = [R(pos=(0.0, 0.0, 0.0), radius=50.0, far=10.0, intensity=0.9,
              colour=0x80808080, start=10.0),
            R(pos=(1.0, 0.0, 0.0), radius=60.0, far=0.0, intensity=0.5,
              colour=0xffffffff, start=20.0),
            R(pos=(0.0, 2.0, 0.0), radius=40.0, far=39.0, intensity=0.3,
              colour=0x00ff0080, start=30.0),
            R(pos=(0.0, 0.0, 3.0), radius=70.0, far=5.0, intensity=0.7,
              colour=0x7f7f7f7f, start=40.0),
            R(pos=(0.0, 0.0, 0.0), radius=1000.0, intensity=0.2,
              colour=0x11223344, start=50.0)]
    hit_pos = [(0.0, 0.0, 0.0), (20.0, 0.0, 0.0), (45.0, 0.0, 0.0),
               (0.0, 38.5, 0.0), (65.0, 0.0, 0.0), (500.0, 0.0, 0.0),
               (5.0, 5.0, 5.0), (0.1, 9.1, 22.1), (1.7, 2.9, 22.1)]
    odd = [R(pos=(0.0, 0.0, 0.0), radius=100.0, far=200.0, intensity=0.4),
           R(pos=(0.0, 0.0, 0.0), radius=100.0, far=0.0, intensity=0.4),
           R(pos=(0.0, 0.0, 0.0), radius=0.0, far=0.0, intensity=0.4),
           R(pos=(0.0, 0.0, 0.0), radius=-30.0, far=-30.0, intensity=0.6),
           R(pos=(0.0, 0.0, 0.0), radius=100.0, far=99.999, intensity=0.5)]
    odd_pos = [(0.0, 0.0, 0.0), (50.0, 0.0, 0.0), (99.9995, 0.0, 0.0),
               (29.0, 0.0, 0.0)]
    types = [R(type=0, pos=(0.0, 0.0, 0.0), radius=100.0, intensity=0.6),
             R(type=0, pos=(0.0, 0.0, 0.0), radius=50.0, far=10.0,
               intensity=0.5),
             R(type=2, pos=(0.0, 0.0, 0.0), radius=50.0, far=20.0,
               intensity=0.25),
             R(type=2, pos=(3.0, 0.0, 0.0), radius=50.0, far=30.0,
               intensity=0.5),
             R(type=3, pos=(0.0, 0.0, 0.0), radius=100.0, intensity=0.9),
             R(type=3, pos=(0.0, 0.0, 0.0), radius=60.0, far=1.0,
               intensity=0.3),
             R(type=1, pos=(0.0, 0.0, 0.0), radius=60.0, far=1.0,
               intensity=0.3),
             R(type=4, pos=(0.0, 0.0, 0.0), radius=100.0, intensity=1.0),
             R(type=-1, pos=(0.0, 0.0, 0.0), radius=100.0, intensity=1.0),
             R(type=7, pos=(0.0, 0.0, 0.0), radius=100.0, intensity=1.0),
             R(type=3, pos=(0.0, 0.0, 0.0), radius=100.0, intensity=0.1),
             R(type=-5, pos=(0.0, 0.0, 0.0), radius=100.0, intensity=1.0)]
    types_pos = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (25.0, 0.0, 0.0)]
    groups = [R(group=0x10, pos=(0.0, 0.0, 0.0), intensity=0.1),
              R(group=0x20, pos=(0.0, 0.0, 0.0), radius=50.0, far=5.0),
              R(type=0, group=0x10, pos=(0.0, 0.0, 0.0)),
              R(type=2, group=0x20, pos=(0.0, 0.0, 0.0)),
              R(type=3, group=0, pos=(0.0, 0.0, 0.0)),
              R(group=0x10, pos=(1.0, 0.0, 0.0), radius=50.0, far=2.0)]
    at_smoke = {1: (1, 1, (300.0, 2.0, 0.0), 0)}
    fog = lambda amount, start, r, g, b: (1, amount, start, r, g, b)

    sc = [
        # The globals as the image starts them are printed before these.
        S("I p m G"),
        # TRACKB12's kinds, loaded, queried, unloaded.
        S("L q0 q1 q2 q3 q4 q5 q6 q7 U q0 q3", regions=track, pos=track_pos),
        S("L U L q0 U q0", regions=track[:3], pos=track_pos),
        # Roots that overlap, tie and touch.
        S("L q0 q1 q2 q3 q4 q5 q6 q7", regions=roots, pos=root_pos),
        S("A1 A0 q0 q1 q2 -1 q1", regions=roots, pos=root_pos),
        # Hits: past three, past a sum of 1, the root after them.
        S("L q0 q1 q2 q3 q4 q5 q6 q7 q8", regions=hits, pos=hit_pos),
        S("A0 q7 q8", regions=hits, pos=hit_pos),
        S("A4 A3 A2 q0 q1 q2 q6 A0 q0 A1 q0", regions=hits, pos=hit_pos),
        S("L q0 q1 q2 q3", regions=odd, pos=odd_pos),
        # Each type, and the types past 3 and below 0.
        S("L q0 q1 q2 U q0", regions=types, pos=types_pos),
        S("A7 A8 A9 -7 -8 -9 L U A0 A0 -0", regions=types, pos=types_pos),
        # The chunk: each misalignment, each version, the wrong type.
        S("L U", regions=track[:2], mis=4),
        S("L q0 U", regions=track[:2], mis=8, pos=track_pos),
        S("L X x U", regions=track[:3], mis=12),
        S("L U", regions=track, version=1),
        S("L U", regions=track, version=3),
        S("L", regions=track, version=0x102),
        S("L U", regions=track, cid=WEATHER_CHUNK + 1),
        S("L U", regions=track, cid=0x80034250),
        S("L U", regions=track, cid=0x00034251, mis=4),
        S("L U"),
        S("X x L", regions=track[:1]),
        # The region and group states.
        S("L g10:0 q0 g20:0 q0 g0:1 q0 s3:0 s1:0 q0 s1:1 g0:0 g10:1 q0 "
          "g20:2 g99:1 g0:0 g0:0 g0:5 q0", regions=groups,
          pos=[(0.0, 0.0, 0.0)]),
        S("L s0:0 s0:0 s0:1 s5:0 g10:0 s0:1 U", regions=groups),
        # The tweaker.
        S("L q0 P1", regions=track, pos=track_pos,
          tweak=(1, 0.5, 200.0, 300, -1, 7)),
        S("q0 Q1", tweak=(2, -0.25, 1e9, 0, 255, 128), pos=[(1.0, 2.0,
                                                               3.0)]),
        # The cache: by frame, each view, and a counter already at it.
        S("L Q1 U Q1 + Q1 Q2 Q1 Q2 + Q2 Q4", regions=track,
          views={1: (1, 1, (300.0, 2.0, 0.0), 0),
                 2: (0, 0, (100.0, 0.0, 0.0), 0)}),
        S("L Q3 Q1 + Q1 Q3", regions=track, frame=7,
          views={1: (1, 1, (0.0, 0.0, 0.0), 7), 3: (1, 1, (0.0, 0.0, 0.0),
                                                     8)}),
        S("L + + Q1", regions=track, frame=0xffffffff, views=at_smoke),
        # The palette, mode 0: the track's own, then the edges.
        S("L P1 + P1", regions=track, views=at_smoke),
        S("P1", tweak=fog(0.8, 240.0, 0x6e, 0x6e, 0x6e)),
        S("P1", tweak=fog(1.0, 0.0, 255, 0, 128)),
        S("P1", tweak=fog(1.5, 254.5, 1, 2, 3)),
        S("P1", tweak=fog(2.5, 255.0, 10, 20, 30)),
        S("P1", tweak=fog(0.6, 256.0, 10, 20, 30)),
        S("P1", tweak=fog(0.6, -10.0, 10, 20, 30)),
        S("P1", tweak=fog(-0.5, 100.0, 10, 20, 30)),
        S("P1", tweak=fog(0.9, 128.0, 300, -5, 511), power=1.0),
        S("P1", tweak=fog(0.9, 128.0, 9, 8, 7), power=0.0),
        S("P1", tweak=fog(0.9, 128.0, 9, 8, 7), power=10.0),
        S("P1", tweak=fog(0.9, 128.0, 9, 8, 7), power=-1.5),
        S("P1 P2", tweak=fog(0.7, 200.0, 1, 2, 3), modes=(5, -1)),
        # Mode 1.
        S("P1 P2", tweak=fog(0.8, 240.0, 1, 2, 3), modes=(1, 0)),
        S("P1", tweak=fog(1.0, 0.0, 1, 2, 3), modes=(1, 0)),
        S("P1", tweak=fog(0.5, 254.0, 1, 2, 3), modes=(1, 0)),
        S("P1", tweak=fog(3.0, -20.0, 1, 2, 3), modes=(1, 0)),
        S("P2 P3 P4", tweak=fog(0.5, 100.0, 1, 2, 3), modes=(0, 1)),
        # Modes 2 and 3.
        S("P1", tweak=fog(0.8, 240.0, 1, 2, 3), modes=(2, 0)),
        S("P1", tweak=fog(0.8, 100.5, 11, 22, 33), modes=(3, 0)),
        S("P1", tweak=fog(1.0, 0.0, 255, 254, 253), modes=(3, 0)),
        S("P1", tweak=fog(2.0, 255.0, 256, 257, -1), modes=(3, 0)),
        S("P1", tweak=fog(0.5, 252.0, 1, 2, 3), modes=(3, 0)),
        # No view, no palette.
        S("N n1", tweak=fog(0.8, 240.0, 1, 2, 3)),
        # The depth palettes.
        S("Z"),
        S("Z", enable=0),
        S("Z", enable=-1),
        # eAttachFog: each view state, DrawFog, the modes.
        S("F", tweak=fog(0.8, 240.0, 5, 6, 7)),
        S("F", tweak=fog(0.8, 240.0, 5, 6, 7), draw=0),
        S("F", tweak=fog(0.8, 240.0, 5, 6, 7), draw=-3),
        S("F", tweak=fog(0.8, 240.0, 5, 6, 7), modes=(1, 3),
          views={2: (1, 1, (0.0, 0.0, 0.0), 0)}),
        S("F", tweak=fog(0.8, 240.0, 5, 6, 7), modes=(2, 1),
          views={1: (0, 1, (0.0, 0.0, 0.0), 0),
                 2: (1, 1, (0.0, 0.0, 0.0), 0)}),
        S("F", tweak=fog(0.8, 240.0, 5, 6, 7),
          views={1: (1, 0, (0.0, 0.0, 0.0), 0),
                 2: (1, 1, (0.0, 0.0, 0.0), 0)}),
        S("F", tweak=fog(0.8, 240.0, 5, 6, 7),
          views={1: (0, 0, (0.0, 0.0, 0.0), 0),
                 2: (1, 0, (0.0, 0.0, 0.0), 0)}),
        S("F v1:0:1 F v1:1:1 v2:1:1 F", modes=(3, 0), regions=track,
          views=at_smoke),
        S("L F + F", regions=track, views=at_smoke),
        # The PICA's side: each mode's palette under each blend.
        S("L Z P1 K0 K1 K2 K3 K4", regions=track, views=at_smoke),
        S("Z P1 K0 K1 K2 K3 K4", tweak=fog(0.8, 240.0, 1, 2, 3),
          modes=(1, 0)),
        S("Z P1 K0 K1 K4", tweak=fog(0.8, 240.0, 1, 2, 3), modes=(2, 0)),
        S("Z P1 K0 K1 K3", tweak=fog(0.8, 100.5, 11, 22, 33), modes=(3, 0)),
        S("Z P1 K0 K1", tweak=fog(0.0, 240.0, 1, 2, 3)),
        S("Z P1 K0 K1", tweak=fog(2.0, 0.0, 200, 100, 50), power=1.0),
        S("P1 K0", tweak=fog(0.8, 240.0, 1, 2, 3)),
        S("Z P1 K0 K1", tweak=fog(0.01, 100.0, 11, 22, 33), modes=(3, 0)),
        S("Z K0 K1"),
        # The whole of it, twice.
        S("L Z F Q1 + F U Z F Q1", regions=track,
          views={1: (1, 1, (300.0, 2.0, 0.0), 0),
                 2: (1, 1, (100.0, 0.0, 0.0), 0)}, modes=(0, 1)),
    ]
    return sc


class Model(object):
    def __init__(self):
        self.out = []
        self.e = Emu(ieee=True)
        self.sc = None
        self.last_palette = 0
        self.last_view = 0
        e = self.e
        e.stub(E_GET_VIEW, self.get_view)
        e.stub(E_GET_TARGET, lambda em: RT15)
        e.stub(BMEMSET, self.memset)
        e.stub(ATTACH_IMAGE, self.attach_image)
        e.stub(DMA_ADD, self.dma_add)

    def emit(self, s):
        self.out.append(s)

    def arg(self, i):
        return self.e.reg[4 + i] & M32

    # ---- the chunk ---------------------------------------------------------

    def chunk(self):
        return CHUNK + self.sc.mis

    def pack(self):
        return (self.chunk() + 8 + 15) & ~15

    def region(self, i):
        return self.pack() + 16 + 128 * i

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        for i in range(4):
            if a == LISTS + 8 * i:
                return "L%d" % i
        if a == INACTIVE:
            return "Li"
        for i in range(len(self.sc.regions) if self.sc else 0):
            if a == self.region(i):
                return "r%d" % i
            if a == self.region(i) + 16:
                return "n%d" % i
        for i in range(4):
            if a == FOG_PAL + 1024 * i:
                return "fog%d" % i
        for i in range(10):
            if a == CACHE + 96 * i:
                return "cache%d" % i
        if a == PAL:
            return "pal"
        return "x"

    def is_node(self, a):
        if a in [LISTS + 8 * i for i in range(4)] or a == INACTIVE:
            return True
        return any(a == self.region(i) for i in range(len(self.sc.regions)))

    # ---- the stubs ---------------------------------------------------------

    def get_view(self, em):
        self.last_view = s32(self.arg(0))
        return (VIEWS + 128 * self.last_view) & M32

    def memset(self, em):
        a, v, n = self.arg(0), self.arg(1), self.arg(2)
        em.write(a, bytes([v & 0xff]) * n)

    def attach_image(self, em):
        if em.reg[31] & M32 == FOG_ATTACH_IMAGE_RA:
            self.last_palette = self.arg(1)

    def dma_add(self, em):
        if em.reg[31] & M32 != FOG_ADD_RA:
            return
        p = self.arg(1)
        alpha = em.u32(p + 96) | em.u32(p + 100) << 32
        self.emit("  attach view %d %s alpha %x" % (
            s32(em.u32(VIEWS + 128 * self.last_view)),
            self.label(self.last_palette), alpha))

    # ---- the dumps ---------------------------------------------------------

    def walk(self, name, head, back):
        e = self.e
        parts = ["  %s%s" % (name, "<" if back else ">")]
        n = e.u32(head + (4 if back else 0))
        steps = 0
        while steps < 32 and n != head:
            parts.append(self.label(n))
            steps += 1
            if not self.is_node(n):
                break
            n = e.u32(n + (4 if back else 0))
        if steps == 32:
            parts.append("...")
        self.emit(" ".join(parts))

    def dump_lists(self):
        e = self.e
        for i, name in enumerate(("L0", "L1", "L2", "L3", "Li")):
            h = LISTS + 8 * i if i < 4 else INACTIVE
            self.walk(name, h, 0)
            self.walk(name, h, 1)
        self.emit("  nodes" + "".join(
            " %s/%s" % (self.label(e.u32(self.region(i))),
                        self.label(e.u32(self.region(i) + 4)))
            for i in range(len(self.sc.regions))))

    def dump_query(self, q):
        u = [self.e.u32(q + 4 * k) for k in range(24)]
        self.emit("  q %08x %08x %08x %08x c %08x s %08x rs %08x hs %08x"
                  % tuple(u[:8]))
        parts = ["  R %s %08x %08x %08x" % (self.label(u[8]), u[9], u[10],
                                            u[11])]
        for k in range(3):
            b = 12 + 4 * k
            parts.append("%d %s %08x %08x %08x" % (
                k, self.label(u[b]), u[b + 1], u[b + 2], u[b + 3]))
        self.emit(" ".join(parts))

    def dump_palette(self, name, a):
        e = self.e
        for i in range(0, 256, 32):
            self.emit("  %s %3d %s" % (name, i, " ".join(
                "%08x" % e.u32(a + 4 * (i + j)) for j in range(32))))

    # ---- the PICA's side, as efog.h has it --------------------------------

    @staticmethod
    def clut_index(k):
        return (k & ~0x18) | ((k & 8) << 1) | ((k & 0x10) >> 1)

    def depth_alpha(self, z):
        e = self.e
        hi = e.u32(UPPER + 4 * self.clut_index(z >> 8 & 0xff))
        lo = e.u32(LOWER + 4 * self.clut_index(z & 0xff))
        return ((hi & 0xfc000000) | (lo & 0x03000000)) >> 24

    def pica(self, m):
        e = self.e
        pal = [e.u32(PAL + 4 * i) for i in range(256)]
        mode = None
        if m < 4:
            mode = tuple(e.read(MODE_INFOS + 32 * m, 4))
        over = mode == (0, 1, 0, 1)
        darken = mode == (1, 0, 0, 2)
        # The PICA's fog is one colour: the palette's, where its alpha
        # is not 0, must be the one, and for mode 1's blend, black.
        ok, colour = 0, 0
        rgbs = {c & 0xffffff for c in pal if c >> 24}
        if (over or darken) and len(rgbs) <= 1:
            rgb = rgbs.pop() if rgbs else 0
            if not (darken and rgb):
                ok, colour = 1, rgb
        self.emit("  colour %d %06x" % (ok, colour))
        parts = []
        for z in ZS:
            da = self.depth_alpha(z)
            a = pal[self.clut_index(da)] >> 24
            if over:
                k = fb(1.0 - a / 128.0)
            elif darken:
                k = fb(a / 128.0)
            else:
                k = fb(1.0)
            parts.append("%u:%u:%08x" % (z, da, k))
        self.emit("  keep " + " ".join(parts))

    # ---- the scenario ------------------------------------------------------

    def reset(self, sc):
        e = self.e
        for i in range(4):
            e.put32(LISTS + 8 * i, LISTS + 8 * i)
            e.put32(LISTS + 8 * i + 4, LISTS + 8 * i)
        e.put32(INACTIVE, INACTIVE)
        e.put32(INACTIVE + 4, INACTIVE)
        e.write(CACHE, bytes(960))
        e.write(FOG_PAL, bytes(4096))
        e.write(UPPER, bytes(1024))
        e.write(LOWER, bytes(1024))
        use, fog, start, r, g, b = sc.tweak
        for k, v in enumerate((use, fog, start, r, g, b)):
            e.put32(TW_USE + 4 * k, v & M32)
        e.put32(DRAW_FOG, sc.draw & M32)
        e.put32(MODE1, sc.modes[0] & M32)
        e.put32(MODE2, sc.modes[1] & M32)
        e.put32(ENABLE, sc.enable & M32)
        e.put32(POWER, sc.power)
        e.put32(FRAME, sc.frame & M32)
        e.put32(DIA_BUFFER, DIA_PKT)
        e.put32(MAIN_DISP, MAIN_RT)
        e.put32(DIA_TARGET, MAIN_RT)
        for k, a in enumerate(DIA_PACKETS):
            e.put32(a, DIA_PKT + 0x100 + 0x100 * k)
        e.write(DMA, bytes(0x10000))
        e.put32(DMA_PTR, DMA)
        e.put32(DMA_END, DMA + 0x100000)
        e.put32(DMA_FAIL, 0)
        e.put32(DMA_WANT, 0)
        e.write(VIEWS, bytes(128 * 10))
        e.write(RTS, bytes(256 * 10))
        e.write(CAMS, bytes(512 * 10))
        for i, (a, rt, xyz, c) in enumerate(sc.views):
            v = VIEWS + 128 * i
            e.put32(v, i)
            e.mem[v + 4] = a & 0xff
            e.put32(v + 48, RTS + 256 * i)
            e.put32(v + 56, CAMS + 512 * i)
            e.put32(v + 100, c & M32)
            e.put32(RTS + 256 * i + 8, rt & M32)
            for k in range(3):
                e.put32(CAMS + 512 * i + 64 + 4 * k, xyz[k])
        for i in range(256):
            e.put32(PAL + 4 * i, 0xdead0000 + i)
        # The chunk, as the disc has it but for each region's first eight
        # bytes, which hold its own address.
        e.write(CHUNK - 16, bytes(64 + 128 * 32))
        c = self.chunk()
        n = len(sc.regions)
        body = bytearray(b"\x5a" * (self.pack() - c - 8))
        body += struct.pack("<IIii", 0, 0, sc.version, n)
        for i, r in enumerate(sc.regions):
            a = self.region(i)
            reg = struct.pack("<IIII", a, a, 0x1000 + i, r.group)
            reg += ("REGION%02d" % i).encode().ljust(32, b"\0")
            reg += ("G%08x" % r.group).encode().ljust(32, b"\0")
            reg += struct.pack("<iII", r.type, r.colour, r.start)
            reg += struct.pack("<I", fb(0.5))
            reg += struct.pack("<6I", r.pos[0], r.pos[1], r.pos[2],
                               r.radius, r.intensity, r.far)
            reg += bytes(8)
            assert len(reg) == 128
            body += reg
        e.write(c, struct.pack("<II", sc.cid, 24 + 128 * n) + bytes(body))

    def op(self, o):
        e = self.e
        sc = self.sc
        self.emit(" %s" % o)
        k = o[0]
        if k == "L":
            self.emit("  -> %d" % e.call(LOADER, self.chunk(), limit=100000))
        elif k == "U":
            self.emit("  -> %d" % e.call(UNLOADER, self.chunk(),
                                         limit=100000))
        elif k in "Xx":
            c = self.chunk()
            cid = e.u32(c)
            e.put32(c, cid ^ 1)
            self.emit("  -> %d" % e.call(LOADER if k == "X" else UNLOADER, c,
                                         limit=100000))
            e.put32(c, cid)
        elif k == "A":
            e.call(ADD_REGION, self.region(int(o[1:])), limit=1000)
        elif k == "-":
            e.call(REMOVE_REGION, self.region(int(o[1:])), limit=1000)
        elif k == "s":
            a, b = o[1:].split(":")
            e.call(SET_STATE, self.region(int(a)), int(b), limit=1000)
        elif k == "g":
            h, b = o[1:].split(":")
            e.call(SET_GROUP, int(h, 16), int(b), limit=100000)
        elif k == "q":
            p = sc.pos[int(o[1:])]
            e.write(QS, b"\xa5" * 96)
            e.write(POSV, struct.pack("<4I", p[0], p[1], p[2], 0))
            e.call(QUERY, QS, POSV, limit=100000)
            self.dump_query(QS)
        elif k == "Q":
            v = VIEWS + 128 * int(o[1:])
            q = e.call(GET_QUERY, v, limit=100000) & M32
            self.emit("  -> %s counter %u" % (self.label(q), e.u32(v + 100)))
            self.dump_query(q)
        elif k == "+":
            e.put32(FRAME, (e.u32(FRAME) + 1) & M32)
        elif k == "P":
            e.call(CREATE, VIEWS + 128 * int(o[1:]), PAL, limit=1000000)
            self.dump_palette("pal", PAL)
        elif k == "N":
            e.call(CREATE, 0, PAL, limit=1000000)
            self.dump_palette("pal", PAL)
        elif k == "n":
            e.call(CREATE, VIEWS + 128 * int(o[1:]), 0, limit=1000000)
        elif k == "G":
            parts = []
            for i in GET_PALETTE_IDS:
                e.put32(TMP_VIEW, i & M32)
                parts.append(self.label(e.call(GET_PALETTE, TMP_VIEW,
                                               limit=100)))
            self.emit("  palettes " + " ".join(parts))
        elif k == "Z":
            self.emit("  -> %d" % e.call(DEPTH_INTO_ALPHA, CHAIN, 0x2c0400,
                                         limit=1000000))
            self.dump_palette("upper", UPPER)
            self.dump_palette("lower", LOWER)
        elif k == "F":
            self.emit("  -> %d" % e.call(ATTACH_FOG, CHAIN, 0x2c0800,
                                         limit=3000000))
            self.dump_palette("fog0", FOG_PAL)
            self.dump_palette("fog1", FOG_PAL + 1024)
        elif k == "K":
            self.pica(int(o[1:]))
        elif k == "p":
            parts = []
            for x, y in FPOW_XY:
                e.fpr[12] = fb(x)
                e.fpr[13] = fb(y)
                e.call(FPOW, limit=100)
                parts.append("%08x" % (e.fpr[0] & M32))
            self.emit("  fpow " + " ".join(parts))
        elif k == "m":
            for i in range(256):
                e.put32(REMAP_SRC + 4 * i, i | (255 - i) << 8 | 0xab000000)
                e.put32(REMAP_DST + 4 * i, 0)
            e.call(REMAP, REMAP_DST, REMAP_SRC, limit=10000)
            self.dump_palette("remap", REMAP_DST)
        elif k == "v":
            a, b, c = (int(t) for t in o[1:].split(":"))
            e.mem[VIEWS + 128 * a + 4] = b & 0xff
            e.put32(RTS + 256 * a + 8, c & M32)
        elif k == "I":
            for m in range(4):
                a = MODE_INFOS + 32 * m
                self.emit("  mode %d %s %s" % (m, " ".join(
                    "%d" % b for b in e.read(a, 5)), " ".join(
                    "%08x" % e.u32(a + 8 + 4 * j) for j in range(6))))
        else:
            self.emit("  ? %s" % o)
        self.dump_lists()

    def run(self, scenarios):
        e = self.e
        # The globals as the image starts them, and the lists once the
        # static constructor has linked them.
        self.emit("start draw %d modes %d %d power %08x enable %d tweak %d "
                  "%08x %08x %d %d %d" % (
                      s32(e.u32(DRAW_FOG)), s32(e.u32(MODE1)),
                      s32(e.u32(MODE2)), e.u32(POWER), s32(e.u32(ENABLE)),
                      s32(e.u32(TW_USE)), e.u32(TW_USE + 4),
                      e.u32(TW_USE + 8), s32(e.u32(TW_USE + 12)),
                      s32(e.u32(TW_USE + 16)), s32(e.u32(TW_USE + 20))))
        e.call(STATIC_CTOR, limit=1000)
        self.sc = Scenario("")
        self.emit("lists %s" % " ".join(
            self.label(e.u32(LIST_NAMES + 4 * i)) for i in range(4))
            + " heads " + " ".join(
            "%s/%s" % (self.label(e.u32(h)), self.label(e.u32(h + 4)))
            for h in [LISTS + 8 * i for i in range(4)] + [INACTIVE]))
        for k, sc in enumerate(scenarios):
            self.sc = sc
            self.reset(sc)
            self.emit("scenario %d %s" % (k, sc.ops))
            for o in sc.ops.split():
                self.op(o)
        return self.out


def model(scenarios):
    return Model().run(scenarios)


# ================================================================ the build


def build_harness(tmp, name="weather_test"):
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
    # ---- weatherman.c: the globals and the lists
    ("wm-fog-list-name", WMC,
     "bNode *WeatherFogList  = &WeatherRegionLists[WEATHER_FOG];",
     "bNode *WeatherFogList  = &WeatherRegionLists[WEATHER_RAIN];"),
    ("wm-add-type", WMC,
     "add_tail(&WeatherRegionLists[r->Type], &r->Node);",
     "add_tail(&WeatherRegionLists[r->Type & 1], &r->Node);"),
    ("wm-add-head", WMC,
     "    tail->next = n;\n    list->prev = n;\n    n->next    = list;\n"
     "    n->prev    = tail;",
     "    n->next    = list->next;\n    n->prev    = list;\n"
     "    list->next->prev = n;\n    list->next = n;\n    (void)tail;"),
    ("wm-add-signed", WMC,
     "if ((uint32_t)r->Type < WEATHER_NUM_TYPES) {",
     "if (r->Type < WEATHER_NUM_TYPES && r->Type != -1) {"),
    ("wm-type-selflink", WMC,
     "        r->Node.next = &r->Node;\n        r->Node.prev = &r->Node;\n",
     ""),
    ("wm-remove-half", WMC,
     "    bNode *prev = r->Node.prev;\n    bNode *next = r->Node.next;\n\n"
     "    prev->next = next;\n    next->prev = prev;",
     "    bNode *prev = r->Node.prev;\n    bNode *next = r->Node.next;\n\n"
     "    prev->next = next;\n    (void)next;"),
    ("wm-state-no-unlink", WMC,
     "    bNode *next = r->Node.next;\n    bNode *prev = r->Node.prev;\n\n"
     "    prev->next = next;\n    next->prev = prev;\n",
     "    bNode *next = r->Node.next;\n    bNode *prev = r->Node.prev;\n\n"
     "    (void)next;\n    (void)prev;\n"),
    ("wm-state-inverted", WMC,
     "add_tail(state ? &WeatherRegionLists[r->Type]\n"
     "                   : &WeatherRegionInactiveList, &r->Node);",
     "add_tail(!state ? &WeatherRegionLists[r->Type]\n"
     "                   : &WeatherRegionInactiveList, &r->Node);"),
    ("wm-group-next-late", WMC,
     "        n = next;\n    }", "        n = n->next;\n        (void)next;\n    }"),
    ("wm-group-hash0", WMC,
     "if (group_hash == 0 || r->GroupNameHash == group_hash) {",
     "if (r->GroupNameHash == group_hash) {"),
    ("wm-group-branch", WMC,
     "    if (state) {\n        set_list_state(",
     "    if (state == 1) {\n        set_list_state("),
    # ---- the loader
    ("wm-loader-cid", WMC,
     "    if (bchunk_u32(chunk) != WEATHER_CHUNK_ID) {\n        return 0;\n"
     "    }\n    pack = chunk_pack(chunk);\n"
     "    if (pack->Version != WEATHER_PACK_VERSION) {\n        return 1;\n"
     "    }\n    r = (WeatherRegion *)(pack + 1);\n"
     "    for (n = pack->NumRegions; n > 0; n--) {\n"
     "        WeatherAddRegion",
     "    if ((bchunk_u32(chunk) & 0xffff) != (WEATHER_CHUNK_ID & 0xffff)) {"
     "\n        return 0;\n"
     "    }\n    pack = chunk_pack(chunk);\n"
     "    if (pack->Version != WEATHER_PACK_VERSION) {\n        return 1;\n"
     "    }\n    r = (WeatherRegion *)(pack + 1);\n"
     "    for (n = pack->NumRegions; n > 0; n--) {\n"
     "        WeatherAddRegion"),
    ("wm-loader-version", WMC,
     "    if (pack->Version != WEATHER_PACK_VERSION) {\n        return 1;\n"
     "    }\n    r = (WeatherRegion *)(pack + 1);\n"
     "    for (n = pack->NumRegions; n > 0; n--) {\n"
     "        WeatherAddRegion",
     "    if (pack->Version < WEATHER_PACK_VERSION) {\n        return 1;\n"
     "    }\n    r = (WeatherRegion *)(pack + 1);\n"
     "    for (n = pack->NumRegions; n > 0; n--) {\n"
     "        WeatherAddRegion"),
    ("wm-loader-version-ret", WMC,
     "    if (pack->Version != WEATHER_PACK_VERSION) {\n        return 1;\n"
     "    }\n    r = (WeatherRegion *)(pack + 1);\n"
     "    for (n = pack->NumRegions; n > 0; n--) {\n"
     "        WeatherAddRegion",
     "    if (pack->Version != WEATHER_PACK_VERSION) {\n        return 0;\n"
     "    }\n    r = (WeatherRegion *)(pack + 1);\n"
     "    for (n = pack->NumRegions; n > 0; n--) {\n"
     "        WeatherAddRegion"),
    ("wm-unloader-count", WMC,
     "    for (n = pack->NumRegions; n > 0; n--) {\n"
     "        WeatherRemoveRegion(r++);",
     "    for (n = pack->NumRegions; n > 1; n--) {\n"
     "        WeatherRemoveRegion(r++);"),
    ("wm-chunk-align", WMC, "& ~(uintptr_t)15);", "& ~(uintptr_t)7);"),
    # ---- the query
    ("wm-tweak-test", WMC, "if (WeatherUseTweakerValues) {",
     "if (WeatherUseTweakerValues == 1) {"),
    ("wm-tweak-colour", WMC, "(uint32_t)WeatherFogColourB << 16",
     "(uint32_t)WeatherFogColourR << 16"),
    ("wm-tweak-snow", WMC, "        q->Snow = 0.0f;\n", ""),
    ("wm-tweak-clears", WMC, "    if (WeatherUseTweakerValues) {",
     "    memset(q, 0, sizeof *q);\n    if (WeatherUseTweakerValues) {"),
    ("wm-clear-part", WMC, "memset(q, 0, sizeof *q);\n\n",
     "memset(q, 0, 32);\n\n"),
    ("wm-far", WMC, "#define WEATHER_FAR 9999999.0f",
     "#define WEATHER_FAR 100.0f"),
    ("wm-d2-order", WMC, "float          d2 = dx * dx + dy * dy + dz * dz;",
     "float          d2 = dx * dx + (dy * dy + dz * dz);"),
    ("wm-inside-le", WMC, "if (d2 < r2) {", "if (d2 <= r2) {"),
    ("wm-root-test", WMC, "if (r2 == f2) {", "if (r2 <= f2) {"),
    ("wm-nearest-tie", WMC, "if (d2 < nearest) {", "if (d2 <= nearest) {"),
    ("wm-hit-scale", WMC,
     "float s = 1.0f - (d2 - f2) / (r2 - f2);",
     "float s = 1.0f - (d2 - f2) / r2;"),
    ("wm-three-hits", WMC, "if (hits >= 3) {", "if (hits >= 2) {"),
    ("wm-sum-order", WMC, "sum        = scale[0] + scale[1] + scale[2];",
     "sum        = scale[0] + (scale[1] + scale[2]);"),
    ("wm-sum-le", WMC, "if (1.0f < sum) {", "if (1.0f <= sum) {"),
    ("wm-root-kept", WMC, "            root_scale = 0.0f;\n", ""),
    ("wm-fog-type", WMC, "if (type == WEATHER_FOG) {",
     "if (type == WEATHER_RAIN) {"),
    ("wm-fog-mask", WMC,
     "q->FogColour = ((uint32_t)ee_trunc_w(t.b) & 0xffu) << 16",
     "q->FogColour = ((uint32_t)ee_trunc_w(t.b)) << 16"),
    ("wm-share-colour", WMC, "*colour  = (uint32_t)ee_trunc_w(s.b) << 16",
     "*colour  = (uint32_t)ee_trunc_w(s.r) << 16"),
    ("wm-share-scale", WMC, "*scale   = w;", "*scale   = s.amount;"),
    ("wm-share-start", WMC, "s.start  = reg->FogStart * w;",
     "s.start  = reg->FogStart;"),
    ("wm-hit-weight", WMC,
     "s = fog_share(hit[k], scale[k] * hit_scale, name, colour,",
     "s = fog_share(hit[k], scale[k], name, colour,"),
    ("wm-rest-weight", WMC,
     "value += hit[hits]->Intensity * hit_scale;",
     "value += hit[hits]->Intensity * hit_scale * scale[hits];"),
    ("wm-rest-root", WMC, "value = root->Intensity * root_scale;",
     "value = root->Intensity;"),
    ("wm-rest-snow", WMC, "            q->Snow = value;",
     "            q->Wind = value;"),
    # ---- the view's cache
    ("wm-view-counter", WMC,
     "        view->WeatherQueryCounter = eFrameCounter;\n", ""),
    ("wm-view-test", WMC, "if (view->WeatherQueryCounter != eFrameCounter)",
     "if (view->WeatherQueryCounter < eFrameCounter)"),
    # ---- efog.c: the globals
    ("ef-mode-info", EFC, "{ 1, 0, 0, 2, 128,", "{ 1, 0, 0, 2, 127,"),
    ("ef-mode-info-start", EFC, "244.0f, 255.0f,", "240.0f, 255.0f,"),
    ("ef-draw-fog", EFC, "int32_t DrawFog = 1;", "int32_t DrawFog = 2;"),
    ("ef-power", EFC, "float   FogPower = 4.5999999046325684f;",
     "float   FogPower = 4.5f;"),
    ("ef-enable", EFC, "int32_t EnableDepthIntoAlpha = 1;",
     "int32_t EnableDepthIntoAlpha = 0;"),
    # ---- the helpers
    ("ef-fpow-clamp", EFC, "float m = x < 0.01f ? 0.01f : x;",
     "float m = x < 0.001f ? 0.001f : x;"),
    ("ef-fpow-trunc", EFC,
     "u.i = ee_trunc_w((float)u.i * y + (one - k));",
     "u.i = (int32_t)(double)((float)u.i * y + (one - k));"),
    ("ef-fpow-order", EFC,
     "u.i = ee_trunc_w((float)u.i * y + (one - k));",
     "u.i = ee_trunc_w(((float)u.i * y + one) - k);"),
    ("ef-remap", EFC, "memcpy(dst + b + 8,  src + b + 16,",
     "memcpy(dst + b + 8,  src + b + 8, "),
    ("ef-getpal-range", EFC, "return n < 4 ? FogPalette[n] : NULL;",
     "return n < 3 ? FogPalette[n] : NULL;"),
    ("ef-getpal-signed", EFC, "uint32_t n = (uint32_t)(view->ID - 1);",
     "int32_t n = view->ID - 1;"),
    ("ef-view-mode", EFC, "return view->ID == 1 ? FogMode1 : FogMode2;",
     "return view->ID == 1 ? FogMode2 : FogMode1;"),
    # ---- the palette
    ("ef-null-view", EFC, "if (view == NULL || palette == NULL) {",
     "if (palette == NULL) {"),
    ("ef-mode-dispatch", EFC, "} else if (mode == 2) {",
     "} else if (mode == 2 || mode == 5) {"),
    ("ef-mode1-span", EFC, "float span = 255.0f - start;",
     "float span = 256.0f - start;"),
    ("ef-mode1-reverse", EFC,
     "linear[255 - i] = (uint32_t)ee_trunc_w(v * amount) << 24;",
     "linear[i] = (uint32_t)ee_trunc_w(v * amount) << 24;"),
    ("ef-mode1-round", EFC,
     "linear[255 - i] = (uint32_t)ee_trunc_w(v * amount) << 24;",
     "linear[255 - i] = (uint32_t)ee_trunc_w(v * amount + 0.5f) << 24;"),
    ("ef-mode2-alpha", EFC, "| 0x80000000u;", "| 0x7f000000u;"),
    ("ef-mode3-order", EFC,
     "                   | ((uint32_t)ee_trunc_w(b) & 0xffu) << 16\n"
     "                   | ((uint32_t)ee_trunc_w(g)",
     "                   | ((uint32_t)ee_trunc_w(r) & 0xffu) << 16\n"
     "                   | ((uint32_t)ee_trunc_w(g)"),
    ("ef-mode3-guard", EFC, "if (at >= 0 && at < 256) {",
     "if (at > 0 && at < 256) {"),
    ("ef-mode3-trunc", EFC, "int32_t  at = ee_trunc_w(start);",
     "int32_t  at = ee_trunc_w(start + 0.5f);"),
    ("ef-mode0-x", EFC, "x = (fi - start) / (255.0f - start);",
     "x = (fi - start) / (256.0f - start);"),
    ("ef-mode0-top", EFC, "} else if (fi < 255.0f) {",
     "} else if (fi <= 255.0f) {"),
    ("ef-mode0-power", EFC, "fpow(x, FogPower)", "fpow(x, 4.6f)"),
    ("ef-mode0-rgb", EFC,
     "| ((uint32_t)ee_trunc_w(b) & 0xffu) << 16;",
     "| ((uint32_t)ee_trunc_w(g) & 0xffu) << 16;"),
    ("ef-mode0-amount", EFC,
     "(uint32_t)ee_trunc_w(fpow(x, FogPower) * amount) << 24 | rgb;",
     "(uint32_t)ee_trunc_w(fpow(x, FogPower) * amount * 0.5f) << 24 | rgb;"),
    ("ef-amount", EFC, "amount = q->Fog * 128.0f;",
     "amount = q->Fog * 127.0f;"),
    ("ef-near", EFC, "    linear[252] = linear[255];\n", ""),
    # ---- the attaches
    ("ef-dia-enable", EFC, "if (!EnableDepthIntoAlpha) {",
     "if (EnableDepthIntoAlpha <= 0) {"),
    ("ef-dia-upper", EFC, "(i & 0xc0) ? 0xff000000u",
     "(i & 0x80) ? 0xff000000u"),
    ("ef-dia-lower", EFC, "(uint32_t)(i >> 6 & 3) << 24",
     "(uint32_t)(i >> 5 & 3) << 24"),
    ("ef-dia-ret", EFC, "    return 1;\n}\n\nint eattach_fog",
     "    return 2;\n}\n\nint eattach_fog"),
    ("ef-fog-draw", EFC, "if (!DrawFog) {", "if (DrawFog <= 0) {"),
    ("ef-fog-views", EFC, "for (id = 1; id < 3; id++) {",
     "for (id = 1; id < 2; id++) {"),
    ("ef-fog-active", EFC, "if (!view->Active || !rt->Active || pal == NULL)",
     "if (!rt->Active || pal == NULL)"),
    ("ef-fog-rt", EFC, "if (!view->Active || !rt->Active || pal == NULL)",
     "if (!view->Active || pal == NULL)"),
    ("ef-fog-mode", EFC, "? &FogModeInfos[mode] : NULL);",
     "? &FogModeInfos[0] : NULL);"),
    # ---- the PICA's side
    ("ef-depth-mask", EFC, "(hi & 0xfc000000u)", "(hi & 0xff000000u)"),
    ("ef-depth-swizzle", EFC,
     "DepthUpperPalette[efog_clut_index(z >> 8 & 0xffu)]",
     "DepthUpperPalette[z >> 8 & 0xffu]"),
    ("ef-over-test", EFC,
     "return m->AlphaA == 0 && m->AlphaB == 1 && m->AlphaC == 0\n"
     "        && m->AlphaD == 1;",
     "return m->AlphaA == 0 && m->AlphaB == 1 && m->AlphaC == 0;"),
    ("ef-colour-alpha", EFC, "if ((c >> 24) == 0) {", "if ((c >> 25) == 0) {"),
    ("ef-colour-mixed", EFC, "if (seen && (c & 0xffffffu) != rgb) {",
     "if (seen && (c & 0xffffffu) != rgb && 0) {"),
    ("ef-colour-darken", EFC, "if (is_darken(mode) && rgb != 0) {",
     "if (is_darken(mode) && rgb == 1) {"),
    ("ef-keep-over", EFC, "return 1.0f - (float)a / 128.0f;",
     "return 1.0f - (float)a / 127.0f;"),
    ("ef-keep-darken", EFC, "return (float)a / 128.0f;",
     "return 1.0f - (float)a / 128.0f;"),
    ("ef-keep-null", EFC, "    if (mode == NULL) {\n        return 1.0f;",
     "    if (mode == NULL) {\n        return 0.5f;"),
    ("ef-keep-index", EFC,
     "uint32_t a = palette[efog_clut_index(efog_depth_alpha(z))] >> 24;",
     "uint32_t a = palette[efog_depth_alpha(z)] >> 24;"),
]

# Mutations that survive because they change nothing the image can tell.
EQUIVALENT = {
    # Both chunks hold each region's own address in its first eight bytes,
    # the model's so that the image's unlink is safe; so a region of a type
    # past 3 is linked to itself whether or not the add links it.
    "wm-type-selflink",
    # At a sum of exactly 1, 1 - sum and the branch's both give the root 0,
    # and 1 / sum is 1.
    "wm-sum-le",
    # The weights are none below 0 and sum to at most 1, so no byte of the
    # blended colour passes 255.
    "wm-fog-mask",
    # No FogModeInfo has A, B and C of 0, 1 and 0 with a D other than 1.
    "ef-over-test",
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
