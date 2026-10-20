#!/usr/bin/env python3
"""Cross-check 3DS Files/source/zonepreview.c, the preview zone's camera,
against the retail image itself, run in mipsemu.

The model is the image. ZonePreviewCameraMover's constructor (0x00161f98),
destructor (0x00163620), Update (0x001639d0), Render (0x00163790),
Duration (0x001637c8), Enable (0x00163978) and Disable (0x001639a0) run as
shipped, through retail's vtable (0x002b2050) where the game goes through
it, and FindRoute (0x00163708), ViolatesTopology (0x00164180),
EnsureTopology (0x0015fea0) and Spline::LinearEstimateLength (0x0018a030)
are called directly. Under them run ConstrainToTopology (0x0015fd80),
Spline's allocating constructor, destructor, GetPoint and GetDerivative,
Linear's Init and GetValue, tCubic3D's setters, GetVal and SplineSeek,
tCubic1D's SplineSeek, the CameraMover base, Camera::SetCameraMatrix,
eCreateLookAtMatrix, bATan, bSin, bCos and IsGameFlowPaused, over retail's
own eView table. The harness (tools/src/zonepreview_test.c) runs the port
over the same script, and the two transcripts are diffed.

Stubs, printing what they are given on both sides: bMalloc hands out
blocks from a patterned arena, __builtin_delete prints the block;
TopologyCoordinate's constructor and destructor, SetInterestBBox
(0x00136e00) and ConstrainToTopology's member (0x001528b0, moves `to` and
answers from a scripted list); RadialBlurOn, Off and Alpha and
Player::UpdateZoneSound (0x001784c0). The pieces checked on their own are
stubbed too: PreviewRoute's constructor and destructor (0x00164630,
0x00164848; the constructor answers from the script),
PreviewRoute::MakeSplines (0x00166570) and the stops (0x00165a70), which
fill the splines and the four stops from the script, and PreviewComet's
constructor, destructor, Enable, Disable and Render (0x001614c8,
0x00161678, 0x00161720, 0x001617a0, 0x00161820). Everything else the
mover reads is laid out by the script: the route's fDistance, the players'
numbers, the camera's keys, the race coordinator at gp-22216,
WorldTimeElapsed at gp-19560, RealTimeElapsed at gp-19596,
Camera::StopUpdating at gp-21808 and SoundEnabled at gp-23056.

Every camera, mover and block starts from a byte pattern, so what a call
leaves alone shows. A float prints as its bits, a NaN as "nan", and a
pointer by what it is. The topology stubs print their vectors without the
pad lanes.

    python tools/zonepreview_check.py
    python tools/zonepreview_check.py --mutate [--only a,b]
    python tools/zonepreview_check.py --dump out/zonepreview
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

HARNESS = "tools/src/zonepreview_test.c"
ZPC = "3DS Files/source/zonepreview.c"
SOURCES = [HARNESS, ZPC] + ["3DS Files/source/" + f for f in (
    "zonecam.c", "spline.c", "banim.c", "average.c", "cammover.c", "race.c",
    "camera.c", "eview.c", "emath.c", "bmatrix.c", "bmath.c", "replay.c",
    "p32.c", "bmathtab.c", "bvector.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
CAM_CTOR = 0x00156be0
ZP_CTOR = 0x00161f98
ZP_DTOR = 0x00163620
ZP_UPDATE = 0x001639d0
ZP_RENDER = 0x00163790
ZP_DURATION = 0x001637c8
ZP_ENABLE = 0x00163978
ZP_DISABLE = 0x001639a0
ZP_FIND = 0x00163708
ZP_VIOLATES = 0x00164180
ZP_ENSURE = 0x0015fea0
ZP_VTBL = 0x002b2050
BASE_VTBL = 0x002b1e50
LIN_LEN = 0x0018a030
MKSPL = 0x00166570
STOPS = 0x00165a70
COMET_CTOR = 0x001614c8
COMET_DTOR = 0x00161678
COMET_EN = 0x00161720
COMET_DIS = 0x001617a0
COMET_RENDER = 0x00161820
CPARAMS = 0x002fa9f0
ROUTE_CTOR = 0x00164630
ROUTE_DTOR = 0x00164848
BMALLOC = 0x002577c0
DELETE = 0x00114e98
VEC_DELETE = 0x00114e90
TOPO_CTOR = 0x00151c28
TOPO_DTOR = 0x00151c70
SET_BBOX3 = 0x00136e00
GET_ELEV = 0x00152070
CONSTRAIN = 0x001528b0
BLUR_ON = 0x0010f178
BLUR_OFF = 0x0010f1b0
BLUR_ALPHA = 0x0010f238
ZONE_SOUND = 0x001784c0
FUNK_EXISTS = 0x0025d220
EMATH_SINIT = 0x0011bf70
BMATRIX_SINIT = 0x0025afa8
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
MOV_STRIDE = 0x500
MOV_SIZE = 1104
NMOV = 2
PLAYERS = 0x01030000
PL_STRIDE = 0x100
NPL = 2
ROUTE = 0x01031000
RPOS = 0x01031040
RPTS = 0x01031080
CAR = 0x010310c0
RC = 0x01031100
SPL = 0x01031400
ARR = 0x01032000
NARR = 64
GV = 0x01033000
GTC = 0x01034000
ARENA = 0x01040000
ARENA_SIZE = 0x80000
MAXPTS = 100

P_NUMBER = 16

PATTERN = 0xa5

# The vtable's slots, by the function's offset.
SLOTS = {
    "destroy": 12, "update": 20, "render": 28, "info": 52, "pov": 60,
    "ext": 68, "lookback": 76, "gap": 84, "enable": 100, "disable": 108,
    "car": 116, "target": 124,
}

# The mover's parts, by offset, as both sides name them.
PARTS = ((92, "stops"), (108, "look"), (156, "ahead"), (204, "eyef"),
         (252, "eyeb"), (300, "ep"), (308, "lp"), (316, "comet"),
         (364, "tc"))


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


def pl_at(i):
    return 0 if i < 0 else PLAYERS + PL_STRIDE * i


def view_at(i):
    return VIEWS + VIEW_STRIDE * i


# ============================================================ the scenarios


def vec(*xs):
    return " ".join(h(x) for x in xs)


def road(rnd, n, start, head, step, lift, pads=None):
    """`n` points about `step` apart along a road that bends and climbs a
    little, `lift` above it."""
    x, y, z = start
    bend = rnd.uniform(-0.12, 0.12)
    climb = rnd.uniform(-0.08, 0.08)
    pts = []
    for i in range(n):
        pad = pads if pads is not None else rnd.choice((0.0, 0.0, 1.0))
        pts.append((x, y, z + lift, pad))
        s = step * rnd.uniform(0.85, 1.15)
        x += math.cos(head) * s
        y += math.sin(head) * s
        z += climb * s + rnd.uniform(-0.2, 0.2)
        head += bend + rnd.uniform(-0.05, 0.05)
    return pts


def w_line(k, pts):
    return "W %d %d %s" % (k, len(pts), " ".join(vec(*p) for p in pts))


def cam_line(rnd, k, pos, tgt, vpos, vtgt, fov):
    pads = [rnd.choice((0.0, 1.0, rnd.uniform(-1, 1))) for _ in range(4)]
    return "J %d %s %s %s %s %04x" % (
        k, vec(*(list(pos) + [pads[0]])), vec(*(list(tgt) + [pads[1]])),
        vec(*(list(vpos) + [pads[2]])), vec(*(list(vtgt) + [pads[3]])), fov)


def constrain_line(rnd, hit=0.0):
    """The answers ConstrainToTopology's member cycles through; each says 1
    with chance `hit`, and some move the point."""
    n = rnd.randrange(2, 7)
    parts = []
    for _ in range(n):
        r = 1 if rnd.random() < hit else 0
        d = ((0.0, 0.0, 0.0) if rnd.random() < 0.6 else
             tuple(rnd.uniform(-1.5, 1.5) for _ in range(3)))
        parts.append("%d %s" % (r, vec(*d)))
    return "X %d %s" % (n, " ".join(parts))


def clocks(rnd):
    return "T %s %s" % (h(rnd.choice((0.0, 1 / 60.0, 1 / 30.0, 0.05,
                                      rnd.uniform(0.005, 0.1)))),
                        h(rnd.choice((1 / 60.0, 1 / 30.0, 1 / 30.0, 0.05,
                                      rnd.uniform(0.005, 0.1)))))


def cams(n):
    out = []
    for k in range(n):
        out += ["C %d" % k, "V %d %d" % (k, k)]
    return out


def stops_line(rnd, last):
    """Four stops: none (0), inside the run (as look parameters), equal
    pairs, past the end and before the start."""
    s = []
    for _ in range(4):
        k = rnd.random()
        if k < 0.35:
            s.append(0.0)
        elif k < 0.85:
            s.append(rnd.uniform(0.25, 0.97) * last)
        elif k < 0.92:
            s.append(last + rnd.uniform(0.1, 3))
        else:
            s.append(rnd.uniform(0.0, 0.2) * last)
    if rnd.random() < 0.15:
        s[1] = s[0]
    return "H " + vec(*s)


def setup(rnd, k=0, dist=None, n=None):
    """A route of `dist` and the four splines along it, the camera `k`
    behind its start, the stops and the constraint answers: the lines
    before "O"."""
    if dist is None:
        dist = rnd.choice((320.0, rnd.uniform(60, 330), rnd.uniform(200, 320),
                           float(rnd.randrange(40, 330))))
    if n is None:
        n = max(4, min(MAXPTS, int(dist / 10) + rnd.choice((-2, 0, 0, 1))))
    start = (rnd.uniform(-800, 800), rnd.uniform(-800, 800),
             rnd.uniform(-20, 60))
    head = rnd.uniform(-math.pi, math.pi)
    step = dist / max(1, n - 1)
    look = road(rnd, n, start, head, step, 1.5)
    out = [w_line(0, look)]
    out.append(w_line(1, [(p[0], p[1], p[2] + 0.5, p[3]) for p in look]
                      if rnd.random() < 0.6 else
                      road(rnd, n + rnd.choice((0, 0, -1, 2)), start, head,
                           step, 2.0)))
    out.append(w_line(2, [(p[0] + rnd.uniform(-0.5, 0.5),
                           p[1] + rnd.uniform(-0.5, 0.5), p[2] + 10.0, p[3])
                          for p in look]))
    out.append(w_line(3, [(p[0], p[1], p[2], p[3]) for p in look]
                      if rnd.random() < 0.5 else
                      road(rnd, n + rnd.choice((0, -1, 1, 3)), start, head,
                           step, 1.5)))
    out.append(stops_line(rnd, n - 1))
    out.append("N %s" % h(dist))
    back = rnd.uniform(4, 12)
    fwd = (math.cos(head), math.sin(head))
    pos = [start[0] - fwd[0] * back, start[1] - fwd[1] * back,
           start[2] + rnd.uniform(1.5, 4)]
    tgt = [start[0] + rnd.uniform(-1, 1), start[1] + rnd.uniform(-1, 1),
           start[2] + rnd.uniform(0, 2)]
    sp = rnd.uniform(0, 50)
    vpos = [fwd[0] * sp + rnd.uniform(-3, 3), fwd[1] * sp + rnd.uniform(-3, 3),
            rnd.uniform(-2, 2)]
    vtgt = [v + rnd.uniform(-2, 2) for v in vpos]
    out.append(cam_line(rnd, k, pos, tgt, vpos, vtgt,
                        rnd.randrange(0x0a00, 0x3000)))
    out.append(constrain_line(rnd))
    return out


def updates(rnd, j, frames, view=0, poke=True):
    out = []
    for i in range(frames):
        k = rnd.random()
        if k < 0.05:
            out.append(clocks(rnd))
        elif k < 0.08:
            out.append("Q %d" % rnd.choice((-1, 0, 6, 6, 5)))
        elif k < 0.10:
            out.append("Y %d" % rnd.choice((0, 1)))
        elif k < 0.12:
            out.append("Z %d" % rnd.choice((0, 0, 1)))
        elif k < 0.14 and poke:
            out.append("F %d fv %s" % (j, h(rnd.choice(
                (1.0, 0.5, rnd.uniform(0.2, 1.6))))))
        elif k < 0.15:
            out.append(constrain_line(rnd))
        elif k < 0.22:
            out.append("r %d %d" % (j, view))
        elif k < 0.25:
            out.append("u %d" % j)
        out.append("U %d" % j)
    return out


def s_length(rnd):
    """LinearEstimateLength on its own: each type, from no points to many,
    dirty or not, over a length already there."""
    out = []
    for i in range(36):
        typ = (0, 1, 2)[i % 3]
        n = (0, 1, 2, 3, 5, 9, 17, 40)[i % 8]
        dirty = rnd.choice((0, 1, 1, 7))
        ln = rnd.choice((0.0, 123.5, rnd.uniform(-5, 500)))
        pts = [vec(*(rnd.uniform(-300, 300) for _ in range(4)))
               for _ in range(n)]
        out.append("l %d %d %d %s %s" % (typ, n, dirty, h(ln), " ".join(pts)))
    return out


def s_ensure(rnd):
    """EnsureTopology on its own: the halves near and past the box of 15,
    exactly on it, and with the constraint moving the points."""
    out = []
    for i in range(40):
        if i % 8 == 0:
            out.append(constrain_line(rnd))
        vs = []
        for half in range(2):
            p = [rnd.uniform(-500, 500) for _ in range(3)] + [
                rnd.choice((0.0, 1.0, rnd.uniform(-2, 2)))]
            k = rnd.random()
            if k < 0.25:
                d = [rnd.uniform(-8, 8) for _ in range(3)]
            elif k < 0.45:
                ax = rnd.randrange(3)
                d = [0.0, 0.0, 0.0]
                d[ax] = rnd.choice((30.0, -30.0, 29.999998, 30.000004))
            else:
                d = [rnd.uniform(-60, 60) for _ in range(3)]
            a = [p[0] + d[0], p[1] + d[1], p[2] + d[2],
                 rnd.choice((0.0, 1.0, rnd.uniform(-2, 2)))]
            vs += [a, p]
        out.append("g %s" % " ".join(vec(*v) for v in vs))
    return out


def s_find(rnd):
    """FindRoute: no points, too few, just enough, many."""
    out = []
    for flag, n in ((0, 0), (0, 9), (1, 0), (1, 3), (1, 4), (1, 31), (1, -2),
                    (0, 4), (1, 5)):
        out += ["I %d %d" % (flag, n), "f"]
    return out


def s_ctor(rnd):
    """Construction on its own, many times: routes short and long, the
    splines' counts, the stopped camera and its render flags, the queries
    and Duration, straight to the destructor with and without a player."""
    out = cams(2) + ["L 0 0", "L 1 1"]
    for i in range(18):
        view = i % 2
        dist = (320.0, 40.0, 75.5, None)[i % 4]
        out += setup(rnd, view, dist)
        out += [clocks(rnd),
                "M %d %08x %d" % (view, rnd.getrandbits(32),
                                  rnd.choice((0, 1, 2))),
                "Z %d" % (i % 3 == 2), "O 0 %d" % view, "Z 0",
                "P %d" % view, "G 0", "u 0"]
        if i % 3 == 0:
            out += ["S 0 %d 0" % (i % 4), "u 0", "S 0 %d 1" % ((i + 1) % 4),
                    "u 0"]
        out += ["R 0 %s" % (-1 if i % 4 == 1 else i % 2), "D 0"]
    return out


def s_run(rnd, frames=None):
    """A preview from start to end: the constructor, Enable, then Update
    through the blend in, the run out with its stops, the turn, the run
    back and the blend out and a little past, rendering on the way, with
    the clocks, the pause, the sound, the stopped camera and the focus pull
    changing; then Disable and the destructor."""
    out = cams(2)
    pn = rnd.choice(((0, 1), (1, 0)))
    out += ["L 0 %d" % pn[0], "L 1 %d" % pn[1]]
    view = rnd.randrange(2)
    out += setup(rnd, view)
    out.append(clocks(rnd))
    if rnd.random() < 0.3:
        out += ["M %d %08x %d" % (view, rnd.getrandbits(32),
                                  rnd.choice((0, 1))),
                "Z %d" % rnd.choice((0, 1))]
    out += ["O 0 %d" % view, "Z 0", "R 0 %d" % rnd.randrange(2), "E 0",
            "G 0", "u 0", "P %d" % view]
    out += updates(rnd, 0, frames or rnd.randrange(170, 230), view)
    out += ["Q -1", "Z 0", "r 0 %d" % view, "e 0", "D 0"]
    return out


def ft_before(target, rte):
    """The fTime that one step of `rte` takes to exactly `target`."""
    old = f32(f32(target) - rte)
    assert f32(old + rte) == f32(target), (target, rte)
    return old


def bounds(dist):
    """The stages' ends for a route of `dist`, as the mover works them
    out."""
    fout = f32(f32(dist) * f32(0.01))
    fback = f32(f32(dist) * f32(0.0033333334))
    out_end = f32(fout + 0.25)
    turn_end = f32(out_end + f32(0.4))
    back_end = f32(turn_end + fback)
    return out_end, turn_end, back_end


def s_edges(rnd):
    """The bounds: an Update landing exactly on 0.25 and on each stage's
    end, and one stepping from each; a stop exactly at the next step's look
    parameter and one exactly at the last; holds running out to 0 and
    under; Render either side of the run out's end."""
    out = cams(1) + ["L 0 1", "L 1 0"]
    rte = 0.0625
    for dist in (320.0, 200.0, 96.0, rnd.uniform(60, 330)):
        dist = f32(dist)
        out += setup(rnd, 0, dist)
        out += ["T %s %s" % (h(1 / 30.0), h(rte)), "O 0 0", "R 0 0",
                "U 0", "U 0"]
        oe, te, be = bounds(dist)
        for target in (0.25, oe, te, be):
            if target != 0.25:
                out.append("F 0 fv %s" % h(rnd.choice((1.0, 0.6))))
            out += ["F 0 ft %s" % h(ft_before(target, rte)), "F 0 fh 0",
                    "U 0", "r 0 0", "U 0", "r 0 0"]
        # Stops exactly where the next step lands, and where it is now.
        out += ["F 0 ft %s" % h(0.5), "F 0 fh 0", "S 0 0 n", "S 0 1 o",
                "U 0", "U 0", "U 0"]
        out += ["F 0 fh %s" % h(rte), "U 0", "U 0",
                "F 0 fh %s" % h(1e-7), "U 0", "U 0",
                "F 0 fh %s" % h(-0.25), "U 0"]
        out += ["S 0 2 0", "S 0 3 1", "u 0", "D 0"]
    return out


def s_two(rnd):
    """Two previews at once on the two views, updated in turn, destroyed
    in the other order."""
    out = cams(2) + ["L 0 0", "L 1 1"]
    out += setup(rnd, 0)
    out += ["O 0 0", "R 0 0", "E 0"]
    out += setup(rnd, 1)
    out += ["O 1 1", "R 1 1", "E 1", "G 1"]
    for i in range(120):
        if i % 17 == 3:
            out.append(clocks(rnd))
        out += ["U %d" % (i & 1)]
        if i % 9 == 0:
            out += ["r %d %d" % (i & 1, i & 1)]
    out += ["e 0", "D 0", "U 1", "e 1", "D 1"]
    return out


def s_violate(rnd):
    """ViolatesTopology over look splines of each spacing: the walk clear,
    crossing at its first step, its last and in between, and a second walk
    from the length the first one left."""
    out = cams(1) + ["L 0 0"]
    for i in range(10):
        dist = (320.0, 120.0, 64.0, None, 300.0)[i % 5]
        out += setup(rnd, 0, dist)
        out += ["O 0 0", "R 0 0"]
        out.append(constrain_line(rnd, (0.0, 0.0, 0.05, 0.3, 1.0)[i % 5]))
        out.append("v 0")
        out.append(constrain_line(rnd, 0.02))
        out += ["v 0", "D 0"]
    # Straight and exactly 10 apart: the walk's step is exactly 1, so it
    # lands on the spline's last parameter.
    for n in (4, 9, 23):
        out += setup(rnd, 0, 10.0 * (n - 1), n)
        x0, y0 = float(rnd.randrange(-500, 500)), float(rnd.randrange(-500,
                                                                     500))
        out.append(w_line(0, [(x0 + 10.0 * i, y0, 7.0, 0.0)
                              for i in range(n)]))
        out += ["O 0 0", "R 0 0", "X 1 0 %s" % vec(0.0, 0.0, 0.0), "v 0",
                "D 0"]
    return out


def script():
    rnd = random.Random(0x7a0e9b1e)
    sc = [s_length(rnd), s_ensure(rnd), s_find(rnd), s_ctor(rnd),
          s_edges(rnd), s_violate(rnd), s_two(rnd)]
    for i in range(6):
        sc.append(s_run(rnd))
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
        e.stub(BLUR_ON, self.s_blur_on)
        e.stub(BLUR_OFF, self.s_blur_off)
        e.stub(BLUR_ALPHA, self.s_blur_alpha)
        e.stub(ZONE_SOUND, self.s_zone_sound)
        e.stub(ROUTE_CTOR, self.s_route_init)
        e.stub(ROUTE_DTOR, self.s_route_destroy)
        e.stub(MKSPL, self.s_mksplines)
        e.stub(STOPS, self.s_stops)
        e.stub(COMET_CTOR, self.s_comet_init)
        e.stub(COMET_DTOR, lambda em: self.emit(
            "  comet destroy %s" % self.name(em.reg[4])))
        e.stub(COMET_EN, lambda em: self.emit(
            "  comet enable %s" % self.name(em.reg[4])))
        e.stub(COMET_DIS, lambda em: self.emit(
            "  comet disable %s" % self.name(em.reg[4])))
        e.stub(COMET_RENDER, lambda em: self.emit(
            "  comet render %s %s %s" % (self.name(em.reg[4]),
                                         self.name(em.reg[5]),
                                         fx(em.fpr[12]))))
        e.put32(JOLLY, 0)
        e.call(EMATH_SINIT)
        e.call(BMATRIX_SINIT)
        for slot, fn in (("update", ZP_UPDATE), ("destroy", ZP_DTOR),
                         ("render", ZP_RENDER), ("enable", ZP_ENABLE),
                         ("disable", ZP_DISABLE)):
            assert e.u32(ZP_VTBL + SLOTS[slot]) == fn, slot
        self.names = {0: "null", BASE_VTBL: "base", ZP_VTBL: "zone",
                      CPARAMS: "cparams", ROUTE: "route", RPOS: "rpos",
                      RPTS: "rpts", CAR: "car", SPL: "spl", ARR: "arr",
                      GTC: "tc"}
        for k in range(NCAM):
            c = cam_at(k)
            self.names[c] = "c%d" % k
            self.names[c + 96] = "c%d.tgt" % k
        for j in range(NMOV):
            m = mov_at(j)
            self.names[m] = "o%d" % j
            for off, part in PARTS:
                self.names[m + off] = "o%d.%s" % (j, part)
        for i in range(NPL):
            self.names[pl_at(i)] = "p%d" % i
        for i in range(NVIEWS):
            self.names[view_at(i)] = "v%d" % i
            self.names[view_at(i) + V_LIST] = "v%d.list" % i
        self.blocks = {}
        self.ltc = None

    def emit(self, s):
        self.out.append(s)

    def name(self, a):
        a &= M32
        if a in self.blocks:
            return self.blocks[a]
        if a in self.names:
            return self.names[a]
        if self.ltc is not None and a == self.ltc:
            return "ltc"
        return "?%08x" % a

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
        self.fill(PLAYERS, PL_STRIDE * NPL)
        self.fill(ROUTE, 0x100)
        self.fill(SPL, 48)
        self.fill(ARR, 16 * NARR)
        self.fill(GV, 64)
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
        self.ltc = None
        self.cons, self.nc = [(0, 0, 0, 0)], 0
        self.wpts = [[], [], [], []]
        self.wstops = [0, 0, 0, 0]
        self.rc = (0, 0)

    # ---- the stubs -------------------------------------------------------

    def s_malloc(self, em):
        size, line, align = s32(em.reg[4]), s32(em.reg[6]), s32(em.reg[7])
        p = (self.heap + 15) & ~15
        self.heap = p + size
        assert self.heap <= ARENA + ARENA_SIZE, "arena full"
        tag = "m%d" % len(self.blocks)
        self.blocks[p] = tag
        self.emit("  malloc %d %s %d %d -> %s"
                  % (size, self.cstr(em.reg[5] & M32), line, align, tag))
        return p

    def s_free(self, em):
        self.emit("  free %s" % self.name(em.reg[4]))

    def s_topo_init(self, em):
        a = em.reg[4] & M32
        if self.name(a).startswith("?"):
            self.ltc = a
        self.emit("  topo init %s" % self.name(a))
        return a

    def s_topo_destroy(self, em):
        a = em.reg[4] & M32
        self.emit("  topo destroy %s" % self.name(a))
        if a == self.ltc:
            self.ltc = None

    def s_bbox(self, em):
        vel = em.reg[6] & M32
        self.emit("  bbox %s pos %s r %s vel %s"
                  % (self.name(em.reg[4]), self.vec3(em.reg[5] & M32),
                     fx(em.fpr[12]),
                     self.vec3(vel) if vel else "null"))

    def s_elev(self, em):
        self.emit("  elev %s pt %s" % (self.name(em.reg[4]),
                                        self.vec3(em.reg[5] & M32)))
        em.fpr[0] = 0

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

    def s_blur_on(self, em):
        self.emit("  blur on %d" % s32(em.reg[4]))

    def s_blur_off(self, em):
        self.emit("  blur off %d" % s32(em.reg[4]))

    def s_blur_alpha(self, em):
        self.emit("  blur alpha %d %s %s"
                  % (s32(em.reg[4]), fx(em.fpr[12]), fx(em.fpr[13])))

    def s_zone_sound(self, em):
        self.emit("  zsound %s %s %s %04x %s"
                  % (self.name(em.reg[4]), fx(em.fpr[12]), fx(em.fpr[13]),
                     em.reg[5] & 0xffff, fx(em.fpr[14])))

    def s_route_init(self, em):
        r = em.reg[4] & M32
        flag, n = self.rc
        self.emit("  route init %s car %s r %s len %s -> %s %d"
                  % (self.name(r), self.name(em.reg[5]), fx(em.fpr[12]),
                     fx(em.fpr[13]), "rpts" if flag else "null", n))
        self.e.put32(r, RPTS if flag else 0)
        self.e.put32(r + 4, n & M32)
        return r

    def s_route_destroy(self, em):
        self.emit("  route destroy %s %d" % (self.name(em.reg[4]),
                                              s32(em.reg[5])))

    def fill_spline(self, s, k):
        p = self.w(s + 12)
        for i, pt in enumerate(self.wpts[k]):
            for li, x in enumerate(pt):
                self.e.put32(p + 16 * i + 4 * li, x)
        self.e.put32(s + 4, len(self.wpts[k]))
        self.e.put32(s + 20, 1)

    def s_mksplines(self, em):
        a = [em.reg[r] & M32 for r in range(4, 10)]
        self.emit("  mksplines %s" % " ".join(self.name(x) for x in a))
        self.fill_spline(a[2], 0)
        self.fill_spline(a[3], 1)
        self.fill_spline(a[4], 2)

    def s_stops(self, em):
        a = [em.reg[r] & M32 for r in range(4, 12)]
        n = s32(self.w(em.reg[29] & M32))
        self.emit("  stops %s %d" % (" ".join(self.name(x) for x in a), n))
        self.fill_spline(a[4], 3)
        for i in range(4):
            self.e.put32(a[7] + 4 * i, self.wstops[i])

    def s_comet_init(self, em):
        self.emit("  comet init %s %s %s"
                  % tuple(self.name(em.reg[r]) for r in (4, 5, 6)))
        return em.reg[4]

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

    def dump_spline(self, tag, a, points=True):
        w = self.w
        self.emit("    %s %08x %08x %08x %s %s %08x %08x %08x %s %s %08x %s"
                  % (tag, w(a), w(a + 4), w(a + 8), self.name(w(a + 12)),
                     self.name(w(a + 16)), w(a + 20), w(a + 24), w(a + 28),
                     fx(w(a + 32)), fx(w(a + 36)), w(a + 40),
                     self.name(w(a + 44))))
        p, n = w(a + 12), s32(w(a + 4))
        if points and p in self.blocks and 0 < n <= MAXPTS:
            for i in range(n):
                self.emit("    %s %d %s" % (tag, i, self.vec4(p + 16 * i)))

    def dump_cubic(self, tag, c):
        w, u16 = self.w, self.e.u16
        self.emit("    %s %s st %04x fl %04x"
                  % (tag, " ".join(fx(w(c + 4 * i)) for i in range(11)),
                     u16(c + 44), u16(c + 46)))

    def dump_blend(self, tag, b):
        if b in self.blocks:
            for lane, lo in (("x", 0), ("y", 48), ("z", 96)):
                self.dump_cubic(tag + lane, b + lo)

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
        self.emit("    ft %s tan %s out %s back %s hold %s stops %s"
                  % (fx(w(m + 72)), fx(w(m + 76)), fx(w(m + 80)),
                     fx(w(m + 84)), fx(w(m + 88)),
                     " ".join(fx(w(m + 92 + 4 * i)) for i in range(4))))
        self.emit("    ei %s li %s em %s lm %s eo %s lo %s fp %s"
                  % tuple(self.name(w(m + o))
                          for o in (44, 48, 52, 56, 60, 64, 68)))
        self.emit("    ep %s %s lp %s %s ae %s al %s"
                  % (fx(w(m + 300)), fx(w(m + 304)), fx(w(m + 308)),
                     fx(w(m + 312)), self.vec4(m + 1072),
                     self.vec4(m + 1088)))
        if full == 2:
            return
        if full or bits_f(w(m + 72)) < 0.25:
            self.dump_blend("ei", w(m + 44))
            self.dump_blend("li", w(m + 48))
        for tag, off in (("em", 52), ("lm", 56), ("eo", 60), ("lo", 64)):
            self.dump_blend(tag, w(m + off))
        if w(m + 68) in self.blocks:
            self.dump_cubic("fp", w(m + 68))
        if full:
            for tag, off in (("look", 108), ("ahead", 156), ("eyef", 204),
                             ("eyeb", 252)):
                self.dump_spline(tag, m + off)

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
        return e.call(fn, (m + delta) & M32, *args, limit=20000000)

    def call(self, fn, *args, **f):
        e = self.e
        for i, v in f.items():
            e.fpr[int(i[1:])] = v & M32
        return e.call(fn, *args, limit=20000000)

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

    def stop_at(self, j, i, which):
        """The harness's stop_at, in the same single-precision steps."""
        m = mov_at(j)
        w = self.w
        t = bits_f(w(m + 72))
        if which in ("0", "1"):
            u = float(int(which))
        else:
            if which == "n":
                t = f32(t + bits_f(w(G_RTE)))
            u = f32(f32(t - 0.25) / bits_f(w(m + 80)))
        last = f32(float(s32(w(m + 108 + 4)) - 1))
        lm, lb = bits_f(w(m + 308)), bits_f(w(m + 312))
        v = f32(f32(f32(lm * u) + lb) * last)
        self.e.put32(m + 92 + 4 * i, f_to_bits(v))

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
        elif c == "L":
            e.put32(pl_at(int(t[1])) + P_NUMBER, int(t[2]))
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
        elif c == "X":
            n = int(t[1])
            self.cons = []
            for i in range(n):
                q = t[2 + 4 * i:6 + 4 * i]
                self.cons.append((int(q[0]), int(q[1], 16), int(q[2], 16),
                                  int(q[3], 16)))
            self.nc = 0
        elif c == "W":
            k, n = int(t[1]), int(t[2])
            self.wpts[k] = [tuple(int(x, 16) for x in t[3 + 4 * i:7 + 4 * i])
                            for i in range(n)]
        elif c == "H":
            self.wstops = [int(x, 16) for x in t[1:5]]
        elif c == "N":
            e.put32(ROUTE + 16, int(t[1], 16))
        elif c == "I":
            self.rc = (int(t[1]), int(t[2]))
        elif c == "O":
            j, view = int(t[1]), int(t[2])
            self.fill(mov_at(j), MOV_STRIDE)
            self.call(ZP_CTOR, mov_at(j), view, ROUTE, RPOS)
            self.dump_mov(j, 1)
            self.dump_views()
            self.dump_cam(self.w(mov_at(j) + 24))
        elif c == "R":
            e.put32(mov_at(int(t[1])) + 28, pl_at(int(t[2])))
        elif c == "U":
            j = int(t[1])
            self.vcall(j, SLOTS["update"])
            self.dump_mov(j, 0)
            self.dump_cam(self.w(mov_at(j) + 24))
        elif c == "D":
            j = int(t[1])
            cam = self.w(mov_at(j) + 24)
            self.vcall(j, SLOTS["destroy"], 0)
            self.dump_mov(j, 2)
            self.dump_views()
            self.dump_cam(cam)
        elif c in "Ee":
            j = int(t[1])
            self.vcall(j, SLOTS["enable" if c == "E" else "disable"])
            self.dump_mov(j, 2)
            self.dump_views()
            self.dump_cam(self.w(mov_at(j) + 24))
        elif c == "r":
            self.vcall(int(t[1]), SLOTS["render"], view_at(int(t[2])))
        elif c == "u":
            self.call(ZP_DURATION, mov_at(int(t[1])))
            self.emit("  duration %s" % fx(e.fpr[0]))
        elif c == "v":
            j = int(t[1])
            r = self.call(ZP_VIOLATES, mov_at(j))
            self.emit("  violates %d" % r)
            self.dump_spline("look", mov_at(j) + 108, points=False)
        elif c == "f":
            r = self.call(ZP_FIND, CAR) & M32
            self.emit("  found %s" % self.name(r))
        elif c == "F":
            m = mov_at(int(t[1]))
            v = int(t[3], 16)
            if t[2] == "ft":
                e.put32(m + 72, v)
            elif t[2] == "fh":
                e.put32(m + 88, v)
            elif t[2] == "fv":
                e.put32(self.w(m + 68), v)
            else:
                e.put32(m + 92 + 4 * int(t[2][1]), v)
        elif c == "S":
            self.stop_at(int(t[1]), int(t[2]), t[3])
        elif c == "G":
            self.query(int(t[1]))
        elif c == "l":
            typ, n, dirty = int(t[1]), int(t[2]), int(t[3])
            self.fill(SPL, 48)
            e.put32(SPL + 8, typ)
            e.put32(SPL + 4, n)
            e.put32(SPL + 20, dirty)
            e.put32(SPL + 32, int(t[4], 16))
            e.put32(SPL + 12, ARR)
            self.put_words(ARR, t[5:5 + 4 * min(n, NARR)])
            self.call(LIN_LEN, SPL)
            self.emit("  length %s dirty %08x len %s"
                      % (fx(e.fpr[0]), self.w(SPL + 20),
                         fx(self.w(SPL + 32))))
        elif c == "g":
            self.put_words(GV, t[1:17])
            self.call(ZP_ENSURE, GTC, GV, GV + 16, GV + 32, GV + 48)
            self.emit("  ensured %s" % " ".join(
                "v " + self.vec4(GV + 16 * i) for i in range(4)))
        else:
            raise SystemExit("bad op %r" % (t,))

    def run(self, scenarios):
        for i, sc in enumerate(scenarios):
            self.emit("B %d" % i)
            self.reset()
            for ln in sc:
                if ln[0] not in "JWX":
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


def build_flags():
    return list(hostbuild.FLAGS)


def build_harness(tmp, name="zonepreview_test"):
    return hostbuild.build(tmp, SOURCES, name=name, flags=build_flags())


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


def M(name, before, after, rel=ZPC):
    return (name, rel, before, after)


MUTATIONS = [
    # The constructor.
    M("type", "viewID, CM_STILL);", "viewID, CM_ZONE_PREVIEW);"),
    M("ctor-time", "    m->fTime = 0.0f;" + NL + "    m->fHoldTime = 0.0f;",
      "    m->fTime = 0.5f;" + NL + "    m->fHoldTime = 0.0f;"),
    M("ctor-hold", "m->fHoldTime = 0.0f;" + NL + "    m->base.vtbl",
      "m->fHoldTime = 0.5f;" + NL + "    m->base.vtbl"),
    M("spl-type", "spline_init_alloc(&m->LookSpline, SPLINE_EXTRAPOLATE,",
      "spline_init_alloc(&m->LookSpline, SPLINE_CLAMP,"),
    M("spl-order",
      "spline_init_alloc(&m->LookSpline, SPLINE_EXTRAPOLATE, 100, 16384);" + NL
      + "    spline_init_alloc(&m->LookAheadSpline, SPLINE_EXTRAPOLATE, 100,"
      + " 16384);",
      "spline_init_alloc(&m->LookAheadSpline, SPLINE_EXTRAPOLATE, 100, 16384);"
      + NL + "    spline_init_alloc(&m->LookSpline, SPLINE_EXTRAPOLATE, 100,"
      + " 16384);"),
    M("comet-spline", "preview_comet_init(&m->Comet, &m->LookSpline,",
      "preview_comet_init(&m->Comet, &m->LookAheadSpline,"),
    M("out-rate", "#define ZP_OUT_RATE          0.01f",
      "#define ZP_OUT_RATE          0.011f"),
    M("back-rate", "#define ZP_BACK_RATE         0.0033333334f",
      "#define ZP_BACK_RATE         0.0033f"),
    M("infrac", "inFrac = ZP_IN / (m->fOutTime + ZP_IN);",
      "inFrac = ZP_IN / m->fOutTime;"),
    M("lead", "lead = ZP_LOOK_LEAD / route->fDistance;",
      "lead = 10.0f / route->fDistance;"),
    M("eye-lin", "inFrac, 1.0f, 1.0f - lead);", "inFrac, 1.0f, 1.0f);"),
    M("look-lin", "inFrac + lead, 1.0f, 1.0f);", "inFrac, 1.0f, 1.0f);"),
    M("mk-args", "&m->EyeForwardSpline, &m->EyeBackwardSpline,",
      "&m->EyeBackwardSpline, &m->EyeForwardSpline,"),
    M("stops-args", "&m->LookSpline, &m->LookAheadSpline,",
      "&m->LookAheadSpline, &m->LookSpline,"),
    M("stops-n", "m->fStops," + NL + "                             4);",
      "m->fStops," + NL + "                             3);"),
    M("anchor-look", "m->vAnchorLook = cam->CurrentKey.Target;",
      "m->vAnchorLook = cam->CurrentKey.Position;"),
    M("eye-wte", "scale_add(&eye, &cam->VelocityKey.Position, WorldTimeElapsed,",
      "scale_add(&eye, &cam->VelocityKey.Position, RealTimeElapsed,"),
    M("ei-u", "u = last * linear_get_value(&m->EyeParameter, 0.0f);" + NL
      + "    spline_get_point(&m->EyeForwardSpline, &p, u);",
      "u = last * linear_get_value(&m->EyeParameter, 1.0f);" + NL
      + "    spline_get_point(&m->EyeForwardSpline, &p, u);"),
    M("ei-dv", "scale(&dv, &cam->VelocityKey.Position, ZP_IN);",
      "scale(&dv, &cam->VelocityKey.Position, ZP_OUT);"),
    M("ei-tan", "last * linear_span(&m->EyeParameter) / m->fOutTime" + NL
      + "                    * ZP_IN);",
      "last * linear_span(&m->EyeParameter) / m->fOutTime" + NL
      + "                    * ZP_TURN);"),
    M("ei-line", "make_blend(ZP_IN, 1049,", "make_blend(ZP_IN, 1050,"),
    M("li-spline", "u = last * linear_get_value(&m->LookParameter, 0.0f);" + NL
      + "    spline_get_point(&m->LookAheadSpline, &p, u);",
      "u = last * linear_get_value(&m->LookParameter, 0.0f);" + NL
      + "    spline_get_point(&m->LookSpline, &p, u);"),
    M("li-dv", "scale(&dv, &cam->VelocityKey.Target, ZP_IN);",
      "scale(&dv, &cam->VelocityKey.Position, ZP_IN);"),
    M("li-val", "make_blend(ZP_IN, 1065, &look,", "make_blend(ZP_IN, 1065, &eye,"),
    M("em-u", "u = last * linear_get_value(&m->EyeParameter, 1.0f);" + NL
      + "    spline_get_point(&m->EyeForwardSpline, &p, u);",
      "u = last * linear_get_value(&m->EyeParameter, 0.0f);" + NL
      + "    spline_get_point(&m->EyeForwardSpline, &p, u);"),
    M("em-tan", "last * linear_span(&m->EyeParameter) / m->fOutTime" + NL
      + "                    * ZP_TURN);",
      "last * linear_span(&m->EyeParameter) / m->fOutTime" + NL
      + "                    * ZP_OUT);"),
    M("em-sign", "scale(&dq, &dq, -last * linear_span(&m->EyeParameter)",
      "scale(&dq, &dq, last * linear_span(&m->EyeParameter)"),
    M("lm-look", "spline_get_point(&m->LookSpline, &q, u);",
      "spline_get_point(&m->LookAheadSpline, &q, u);"),
    M("lm-last2", "last2 * linear_span(&m->LookParameter)",
      "last * linear_span(&m->LookParameter)"),
    M("lm-u", "last = spline_last(&m->LookSpline);" + NL
      + "    u = last * linear_get_value(&m->LookParameter, 1.0f);",
      "last = spline_last(&m->LookAheadSpline);" + NL
      + "    u = last * linear_get_value(&m->LookParameter, 1.0f);"),
    M("eo-dv", "scale(&dv, &cam->VelocityKey.Position, ZP_OUT);",
      "scale(&dv, &cam->VelocityKey.Position, ZP_IN);"),
    M("eo-order", "make_blend(ZP_OUT, 1131, &p, &dp, &eye, &dv);",
      "make_blend(ZP_OUT, 1131, &eye, &dv, &p, &dp);"),
    M("lo-sign", "scale(&dp, &dp, -last * linear_span(&m->LookParameter) / m->fBackTime" + NL
      + "                    * ZP_OUT);",
      "scale(&dp, &dp, last * linear_span(&m->LookParameter) / m->fBackTime" + NL
      + "                    * ZP_OUT);"),
    M("lo-val", "make_blend(ZP_OUT, 1147, &p, &dp, &look, &dv);",
      "make_blend(ZP_OUT, 1147, &p, &dp, &eye, &dv);"),
    M("blend-arr", "lane[i]->arrivalThreshold = 1.0f;",
      "lane[i]->arrivalThreshold = 0.9f;"),
    M("blend-flags", "lane[i]->flags = 0;", "lane[i]->flags = 1;"),
    M("fp-state", "m->pFocusPull->state = 2;", "m->pFocusPull->state = 0;"),
    M("fp-val", "m->pFocusPull->val = 1.0f;", "m->pFocusPull->val = 0.5f;"),
    M("fp-dur", "m->pFocusPull->duration = ZP_IN;",
      "m->pFocusPull->duration = ZP_TURN;"),
    M("fp-line", "ZONECAMERAS_CPP," + NL + "                                       1157, 16);",
      "ZONECAMERAS_CPP," + NL + "                                       1158, 16);"),
    M("tanfov", "m->fTanFov = bSinBam(fov) / bCosBam(fov);",
      "m->fTanFov = bCosBam(fov) / bSinBam(fov);"),
    M("render-stop", "if (!CameraStopUpdating) {", "if (1) {"),
    M("dash", "cam->RenderDash = 0;", "cam->RenderDash = 1;"),

    # The destructor.
    M("dtor-blur", "    if (m->base.pPlayer != NULL)" + NL
      + "        zp_blur_off(m);" + NL + "    bFree", "    bFree"),
    M("dtor-order", "bFree(m->pEyeBlendMid);" + NL + "    bFree(m->pEyeBlendOut);",
      "bFree(m->pEyeBlendOut);" + NL + "    bFree(m->pEyeBlendMid);"),
    M("dtor-spl", "spline_destroy(&m->EyeBackwardSpline, 2);" + NL
      + "    spline_destroy(&m->EyeForwardSpline, 2);",
      "spline_destroy(&m->EyeForwardSpline, 2);" + NL
      + "    spline_destroy(&m->EyeBackwardSpline, 2);"),
    M("dtor-comet", "preview_comet_destroy(&m->Comet);", "(void)0;"),

    # Duration, Render, Enable and Disable.
    M("dur-lo", "if (from < m->fStops[i] && m->fStops[i] < to)",
      "if (from <= m->fStops[i] && m->fStops[i] < to)"),
    M("dur-hi", "if (from < m->fStops[i] && m->fStops[i] < to)",
      "if (from < m->fStops[i] && m->fStops[i] <= to)"),
    M("dur-sum", "+ m->fBackTime)" + NL + "           + ZP_OUT;",
      "+ m->fBackTime)" + NL + "           + ZP_IN;"),
    M("dur-hold", "holds += ZP_HOLD;", "holds += ZP_TURN;"),
    M("render-gate", "if (end < m->fTime)", "if (end <= m->fTime)"),
    M("render-t", "preview_comet_render(&m->Comet, view, m->fTime / end);",
      "preview_comet_render(&m->Comet, view, m->fTime);"),
    M("enable-comet", "preview_comet_enable(&m->Comet);", "(void)0;"),
    M("disable-comet", "preview_comet_disable(&m->Comet);", "(void)0;"),

    # FindRoute.
    M("find-n", "r->nPoints < 4", "r->nPoints < 3"),
    M("find-null", "if (r->pPoints == NULL || r->nPoints < 4) {",
      "if (r->nPoints < 4) {"),
    M("find-args", "preview_route_init(r, car, 40.0f, 320.0f);",
      "preview_route_init(r, car, 320.0f, 40.0f);"),
    M("find-flag", "preview_route_destroy(r, 3);", "preview_route_destroy(r, 1);"),

    # ViolatesTopology and LinearEstimateLength.
    M("viol-step", "#define ZP_WALK_STEP         10.0f",
      "#define ZP_WALK_STEP         5.0f"),
    M("viol-le", "t <= spline_last(s); t += step", "t < spline_last(s); t += step"),
    M("viol-gap", "r = length3(&h) + ZP_WALK_GAP;", "r = length3(&h);"),
    M("viol-sides", "TOPOLOGY_CONSTRAIN_BY_SCALE, 1, prev,",
      "TOPOLOGY_CONSTRAIN_BY_SCALE, 0, prev,"),
    M("viol-dir", "1, prev," + NL + "                               cur, ZP_WALK_GAP",
      "1, cur," + NL + "                               prev, ZP_WALK_GAP"),
    M("viol-centre", "add(&centre, &h, prev);", "add(&centre, &h, cur);"),
    M("viol-first", "if (i <= 0)" + NL + "            continue;",
      "if (i < 0)" + NL + "            continue;"),
    M("viol-ret", "            topology_destroy(&tc);" + NL + "            return 1;",
      "            topology_destroy(&tc);" + NL + "            return 2;"),
    M("len-dirty", "if (s->Dirty != 0) {", "if (1) {"),
    M("len-clear", "        s->Dirty = 0;" + NL + "    }" + NL
      + "    return s->Length;", "    }" + NL + "    return s->Length;"),
    M("len-from", "for (i = 1; i < s->NumControlPoints; i++) {",
      "for (i = 2; i < s->NumControlPoints; i++) {"),
    M("len-zero", "        s->Length = 0.0f;" + NL + "        for",
      "        for"),
    M("len3", "return sqrtf((v->x * v->x + v->y * v->y) + v->z * v->z);",
      "return sqrtf(v->x * v->x + (v->y * v->y + v->z * v->z));"),

    # EnsureTopology.
    M("ens-order", "ensure_pair(tc, anchorLook, look);" + NL
      + "    ensure_pair(tc, anchorEye, eye);",
      "ensure_pair(tc, anchorEye, eye);" + NL
      + "    ensure_pair(tc, anchorLook, look);"),
    M("ens-box", "if (ZP_ENSURE_BOX < r) {", "if (ZP_ENSURE_BOX <= r) {"),
    M("ens-bug", "scale(&h, &h, ZP_ENSURE_BOX);",
      "scale(&h, &h, ZP_ENSURE_BOX / r);"),
    M("ens-half", "scale(&h, &h, 0.5f);" + NL + "    r = length3(&h);" + NL
      + "    if (ZP_ENSURE",
      "scale(&h, &h, 0.25f);" + NL + "    r = length3(&h);" + NL
      + "    if (ZP_ENSURE"),
    M("ens-centre", "add(&centre, &h, pt);", "add(&centre, &h, anchor);"),
    M("ens-args", "zone_constrain_to_topology(tc, anchor, pt, 0, 0);",
      "zone_constrain_to_topology(tc, pt, anchor, 0, 0);"),

    # Update.
    M("paused", "    if (is_game_flow_paused())" + NL + "        return;" + NL
      + "    // The image", "    // The image"),
    M("up", "up.z = 1.0f;", "up.z = -1.0f;"),
    M("hold-gate", "if (0.0f < m->fHoldTime) {", "if (0.0f <= m->fHoldTime) {"),
    M("hold-rte", "m->fHoldTime = m->fHoldTime - RealTimeElapsed;",
      "m->fHoldTime = m->fHoldTime - WorldTimeElapsed;"),
    M("t-rte", "t = old + RealTimeElapsed;", "t = old + WorldTimeElapsed;"),
    M("in-gate", "if (t < ZP_IN) {", "if (t <= ZP_IN) {"),
    M("in-seek", "bspline3d_seek(m->pEyeBlendIn, RealTimeElapsed);",
      "bspline3d_seek(m->pEyeBlendIn, WorldTimeElapsed);"),
    M("in-look", "bspline3d_get_val(m->pLookBlendIn, &look);",
      "bspline3d_get_val(m->pEyeBlendIn, &look);"),
    M("in-blur", "zp_blur(m, 0.0f, m->fTime * 4.0f * ZP_BLUR_IN);",
      "zp_blur(m, 0.0f, m->fTime * 3.0f * ZP_BLUR_IN);"),
    M("in-ensure", "zone_ensure_topology(&m->Topology, &m->vAnchorEye, &eye,"
      + NL + "                             &m->vAnchorLook, &look);" + NL
      + "        zp_blur",
      "zone_ensure_topology(&m->Topology, &m->vAnchorLook, &eye,"
      + NL + "                             &m->vAnchorEye, &look);" + NL
      + "        zp_blur"),
    M("out-gate", "} else if (t < outEnd) {", "} else if (t <= outEnd) {"),
    M("out-u", "float u = (t - ZP_IN) / m->fOutTime;",
      "float u = (t - ZP_IN) / m->fBackTime;"),
    M("out-uo", "float uo = (old - ZP_IN) / m->fOutTime;",
      "float uo = (t - ZP_IN) / m->fOutTime;"),
    M("sound-rise", "sound = u * ZP_SOUND_RISE + ZP_SOUND;",
      "sound = u * ZP_SOUND_RISE;"),
    M("out-eye", "spline_get_point(&m->EyeForwardSpline, &eye,",
      "spline_get_point(&m->EyeBackwardSpline, &eye,"),
    M("out-look", "spline_get_point(&m->LookAheadSpline, &look, to);",
      "spline_get_point(&m->LookSpline, &look, to);"),
    M("stop-lo", "if (from < m->fStops[i] && m->fStops[i] <= to) {",
      "if (from <= m->fStops[i] && m->fStops[i] <= to) {"),
    M("stop-hi", "if (from < m->fStops[i] && m->fStops[i] <= to) {",
      "if (from < m->fStops[i] && m->fStops[i] < to) {"),
    M("stop-hold", "m->fHoldTime = ZP_HOLD;", "m->fHoldTime = ZP_TURN;"),
    M("stop-sound", "sound = 0.0f;" + NL + "                break;",
      "sound = 0.5f;" + NL + "                break;"),
    M("run-blur", "zp_blur(m, f * ZP_BLUR_RUN_FROM,", "zp_blur(m, f * ZP_BLUR_RUN_TO,"),
    M("run-far", "f * ZP_BLUR_RUN_TO + (1.0f - f) * ZP_BLUR_RUN_START);",
      "(1.0f - f) * ZP_BLUR_RUN_TO);"),
    M("run-on", "            zp_blur_on(m);" + NL, ""),
    M("run-off", "        } else {" + NL + "            zp_blur_off(m);" + NL
      + "        }", "        } else {" + NL + "        }"),
    M("turn-gate", "} else if (t < turnEnd) {", "} else if (t <= turnEnd) {"),
    M("focus-gate", "if (old < outEnd) {", "if (old <= outEnd) {"),
    M("focus-dur", "focus->duration = ZP_TURN;", "focus->duration = ZP_OUT;"),
    M("focus-vd", "focus->valDesired = 1.0f;", "focus->valDesired = 0.5f;"),
    M("focus-ne", "if (focus->val != 1.0f)", "if (focus->val == 1.0f)"),
    M("turn-seek", "bspline3d_seek(m->pLookBlendMid, RealTimeElapsed);",
      "bspline3d_seek(m->pLookBlendMid, WorldTimeElapsed);"),
    M("turn-sound", "- m->fOutTime) * ZP_TURN_RATE;",
      "- m->fOutTime) * 2.0f;"),
    M("turn-k", "+ ZP_TURN) - m->fTime) * ZP_TURN_RATE;",
      "+ ZP_TURN) - m->fTime) * 2.0f;"),
    M("turn-blur", "zp_blur(m, k * ZP_BLUR_TURN_FROM, k * ZP_BLUR_TURN_TO);",
      "zp_blur(m, k * ZP_BLUR_TURN_TO, k * ZP_BLUR_TURN_FROM);"),
    M("back-gate", "} else if (t < turnEnd + m->fBackTime) {",
      "} else if (t <= turnEnd + m->fBackTime) {"),
    M("back-off", "if (old < turnEnd)", "if (old <= turnEnd)"),
    M("back-v", "v = 1.0f - (((m->fTime", "v = (((m->fTime"),
    M("back-look", "spline_get_point(&m->LookSpline, &look,",
      "spline_get_point(&m->LookAheadSpline, &look,"),
    M("back-param", "linear_get_value(&m->EyeParameter, v)",
      "linear_get_value(&m->LookParameter, v)"),
    M("end-sound", "        sound = 0.0f;" + NL
      + "        bspline3d_seek(m->pEyeBlendOut",
      "        sound = 0.25f;" + NL
      + "        bspline3d_seek(m->pEyeBlendOut"),
    M("end-seek", "bspline3d_seek(m->pLookBlendOut, RealTimeElapsed);",
      "bspline3d_seek(m->pLookBlendOut, WorldTimeElapsed);"),
    M("end-ensure", "bspline3d_get_val(m->pLookBlendOut, &look);" + NL
      + "        zone_ensure_topology(&m->Topology, &m->vAnchorEye, &eye,"
      + NL + "                             &m->vAnchorLook, &look);",
      "bspline3d_get_val(m->pLookBlendOut, &look);"),
    M("focus-seek", "bspline_seek(focus, RealTimeElapsed);",
      "bspline_seek(focus, WorldTimeElapsed);"),
    M("pull", "scale_add(&eye, &d, focus->val, &look);",
      "scale_add(&eye, &d, 1.0f, &look);"),
    M("fov", "fov = bATan(focus->val, m->fTanFov);",
      "fov = bATan(m->fTanFov, focus->val);"),
    M("fov-stop", "if (!CameraStopUpdating)" + NL
      + "        m->base.pCamera->CurrentKey.FieldOfView",
      "if (1)" + NL + "        m->base.pCamera->CurrentKey.FieldOfView"),
    M("lookat", "eCreateLookAtMatrix(&mat, &eye, &look, &up);",
      "eCreateLookAtMatrix(&mat, &look, &eye, &up);"),
    M("setmat", "camera_set_matrix(m->base.pCamera, &mat, RealTimeElapsed);",
      "camera_set_matrix(m->base.pCamera, &mat, WorldTimeElapsed);"),
    M("sound-gate", "if (SoundEnabled)", "if (1)"),
    M("muffle", "1.0f - sound, sound, 0,", "sound, sound, 0,"),
    M("pitch", "sound * 0.5f + -0.5f);", "sound * 0.5f + 0.5f);"),

    # The helpers.
    M("span", "return linear_get_value(l, 1.0f) - linear_get_value(l, 0.0f);",
      "return linear_get_value(l, 1.0f);"),
    M("scale-add-pad", "o->pad = a->pad * k + b->pad;", "o->pad = b->pad;"),
    M("blur-view", "gRadialBlurAlphaFn(zp_player(m)->PlayerNumber, from, to);",
      "gRadialBlurAlphaFn(0, from, to);"),
]

EQUIVALENT = {
    "scale-add-pad": "scale_add's three results (Enable's eye and look a "
                     "frame on, Update's pulled eye) are locals whose fourth "
                     "lane nothing reads: the blends take x, y and z, and so "
                     "does eCreateLookAtMatrix",
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
        todo, SOURCES, "zonepreview_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs, flags=build_flags())
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
