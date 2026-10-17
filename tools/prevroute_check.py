#!/usr/bin/env python3
"""Cross-check 3DS Files/source/previewroute.c, the jump cam's route, and
playerzone.c's Player::IsJumpCamAvailable against the retail image itself,
run in mipsemu.

The model is the image. PreviewRoute's constructor (0x00164630),
destructor (0x00164848), NextPoint (0x001648a0), ClosestDistance
(0x00164aa0) and ClosestPoint (0x00164c80) run as shipped, and so does
IsJumpCamAvailable (0x001769e8), over retail's TrackRoute::FindClosestPoint,
the TrackRoutePoint GetPositions and bEqual. The harness
(tools/src/prevroute_test.c) runs the port over the same script, and the
two transcripts are diffed.

Stubs: bMalloc hands out blocks filled with 0xa5 from a pool and prints its
file name, its line and what the block is for; bFree prints the block.
Car::GetRoute and GetRoutePoint answer the script's route and point. Player
::CleanUpJumpCam, which tools/player_check.py checks, prints the route and
frees it as retail's destructor does.

The routes are built in both memories from the script: each point's 112
bytes as words, the header's count, type, bounding box and the 21 driving
lines' flags. Racing routes go on the manager's racing list (retail's
0x00314438) in the script's order, traffic routes on the traffic list.
The car is retail's at its offsets (the class byte at CarTypeInfo +230,
the position at +96, the track direction at +2040) and the port's by name.

A float prints as its bits, a NaN as "nan", and a pointer by what it is:
R2 a route, R2:17 a route point, A3 the fourth block bMalloc gave, pr the
script's PreviewRoute, pat the fill.

    python tools/prevroute_check.py
    python tools/prevroute_check.py --mutate [--only a,b]
    python tools/prevroute_check.py --dump out/prevroute
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

HARNESS = "tools/src/prevroute_test.c"
PRC = "3DS Files/source/previewroute.c"
PZC = "3DS Files/source/playerzone.c"
SOURCES = [HARNESS, PRC, PZC] + ["3DS Files/source/" + f for f in (
    "trackroute.c", "trackpath.c", "quickspline.c", "bvector.c", "bmath.c",
    "replay.c", "p32.c",
    "bmathtab.c", "bmatrix.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
PR_CTOR = 0x00164630
PR_DTOR = 0x00164848
PR_NEXT = 0x001648a0
PR_DIST = 0x00164aa0
PR_CLOSEST = 0x00164c80
IS_JUMP_CAM = 0x001769e8
CLEAN_UP_JUMP_CAM = 0x00176ab0
B_MALLOC = 0x002577c0
B_FREE = 0x00257850
GET_ROUTE = 0x001332a8
GET_ROUTE_POINT = 0x001332d8

MANAGER = 0x00314438              # TheTrackRouteManager: racing, traffic
POINT2POINT = 0x0031a8c0          # TheRaceParameters.Point2Point
G_TRACK = GP - 21952              # CurrentTrackInfo

ROUTES = 0x01000000
ROUTE_STRIDE = 0x20000
NROUTES = 6
POOL = 0x01200000
POOL_END = 0x01300000
PLAYER = 0x01300000
CAR = 0x01302000
CTI = 0x01303000
TRACK = 0x01304000
PR = 0x01305000
OUTP = 0x01305100
VEC = 0x01305200

P_CAR = 4
P_JUMP_ROUTE = 1764
C_CTI = 12
C_POS = 96
C_DIR = 2040
CTI_CLASS = 230
T_SAME = 66

RT_HEADER = 1064
RT_POINT = 112
LINES = 21

PATTERN = 0xa5
PAT32 = 0xa5a5a5a5


def fb(v):
    if isinstance(v, int):
        return v & M32
    return f_to_bits(v)


def h(v):
    return "%08x" % fb(v)


def f32(v):
    return struct.unpack("<f", struct.pack("<f", v))[0]


def fx(w):
    """A float's bits, with every NaN the one "nan"."""
    w &= M32
    if (w & 0x7f800000) == 0x7f800000 and (w & 0x7fffff):
        return "nan"
    return "%08x" % w


def route_at(k):
    return ROUTES + ROUTE_STRIDE * k


# ============================================================ the scenarios


class Route(object):
    """A route the generator laid out: its points' places and directions,
    for putting cars on it, and its script lines."""

    def __init__(self, k, typ, pts, flags):
        self.k, self.typ, self.pts, self.flags = k, typ, pts, flags

    def ops(self, rnd):
        xs = [p["x"] for p in self.pts]
        ys = [p["y"] for p in self.pts]
        pad = rnd.choice((0.0, 2.0, 10.0))
        box = (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
        out = ["G %d %d %d %s %s" % (
            self.k, self.typ, len(self.pts), " ".join(h(f32(v)) for v in box),
            " ".join("%x" % f for f in self.flags))]
        for p in self.pts:
            out.append("P " + " ".join("%08x" % w for w in
                                       struct.unpack("<28I", p["raw"])))
        return out


def lay_route(rnd, k, typ, x, y, heading, n, dat=None, flags=None,
              turn=0.2, step=(8.0, 20.0)):
    pos = []
    z = rnd.uniform(-20.0, 20.0)
    hd = heading
    for i in range(n):
        pos.append((f32(x), f32(y), f32(z)))
        s = rnd.uniform(*step)
        hd += rnd.uniform(-turn, turn)
        x += s * math.cos(hd)
        y += s * math.sin(hd)
        z += rnd.uniform(-1.0, 1.0)
    if dat is None:
        dat = rnd.uniform(0.0, 3000.0)
    pts = []
    for i in range(n):
        px, py, pz = pos[i]
        if i + 1 < n:
            nx, ny = pos[i + 1][0], pos[i + 1][1]
        else:
            nx = px + (px - pos[i - 1][0])
            ny = py + (py - pos[i - 1][1])
        dx, dy = nx - px, ny - py
        ln = math.hypot(dx, dy) or 1.0
        dirx, diry = f32(dx / ln), f32(dy / ln)
        offs = [rnd.choice((0, rnd.randint(-2560, 2560), rnd.randint(-300, 300)))
                for _ in range(LINES)]
        speeds = [rnd.randrange(256) for _ in range(LINES)]
        raw = struct.pack("<12f", px, py, pz, dirx, diry, f32(ln),
                          f32(rnd.uniform(4.0, 16.0)),
                          f32(rnd.uniform(4.0, 16.0)),
                          f32(rnd.uniform(-0.05, 0.05)),
                          f32(rnd.uniform(-0.1, 0.1)), f32(dat),
                          0.0)[:44]
        raw += struct.pack("<I", rnd.getrandbits(32))
        raw += struct.pack("<21h", *offs)
        raw += bytes(speeds) + bytes([k])
        assert len(raw) == RT_POINT
        pts.append({"x": px, "y": py, "z": pz, "dx": dirx, "dy": diry,
                    "raw": raw})
        dat += ln
    if flags is None:
        flags = [rnd.choice((0, 0, 1, 2, 3, 4, 5, 8, 0x10, 0xff))
                 for _ in range(LINES)]
    return Route(k, typ, pts, flags)


def car_op(rnd, r, j, side=None, back=False, cls=None, given=True):
    """The car beside point j of route r."""
    p = r.pts[j]
    if side is None:
        side = rnd.uniform(-8.0, 8.0)
    x = p["x"] + p["dy"] * side + rnd.uniform(-1.0, 1.0)
    y = p["y"] - p["dx"] * side + rnd.uniform(-1.0, 1.0)
    z = p["z"] + rnd.uniform(-1.0, 2.0)
    a = math.atan2(p["dy"], p["dx"]) + rnd.uniform(-0.4, 0.4)
    if back:
        a += math.pi
    if cls is None:
        cls = rnd.randrange(10)
    route = r.k if given else -1
    point = "%d:%d" % (r.k, j) if given else "-"
    return "C %s %s %s %s %s %d %d %s" % (
        h(f32(x)), h(f32(y)), h(f32(z)), h(f32(math.cos(a))),
        h(f32(math.sin(a))), cls, route, point)


def car_at(x, y, z, a, cls, route=-1, point="-"):
    return "C %s %s %s %s %s %d %d %s" % (
        h(f32(x)), h(f32(y)), h(f32(z)), h(f32(math.cos(a))),
        h(f32(math.sin(a))), cls, route, point)


def new_route(rnd, rad=None, ln=None):
    if rad is None:
        rad = rnd.choice((50.0, 50.0, 20.0, 5.0, 100.0))
    if ln is None:
        ln = rnd.choice((75.0, 75.0, 40.0, 200.0, 8.0, 11.0, 300.0))
    return "N %s %s" % (h(f32(rad)), h(f32(ln)))


def s_one(rnd):
    r = lay_route(rnd, 0, 0, 0.0, 0.0, rnd.uniform(-3, 3), 60)
    ops = r.ops(rnd)
    for _ in range(24):
        j = rnd.randrange(60)
        ops.append(car_op(rnd, r, j, back=rnd.random() < 0.2))
        ops.append(new_route(rnd))
        ops.append("D")
    return ops


def s_noroute(rnd):
    r = lay_route(rnd, 0, 0, 100.0, -50.0, rnd.uniform(-3, 3), 50)
    t = lay_route(rnd, 1, 1, 110.0, -40.0, rnd.uniform(-3, 3), 30)
    ops = r.ops(rnd) + t.ops(rnd)
    for _ in range(24):
        j = rnd.randrange(50)
        ops.append(car_op(rnd, r, j, given=False))
        ops.append(new_route(rnd))
        ops.append("D")
    # A route but no point, and the other way round.
    ops.append(car_op(rnd, r, 5).replace(" 0:5", " -"))
    ops.append(new_route(rnd, 50.0, 75.0))
    ops.append("D")
    c = car_op(rnd, r, 7).split()
    c[7] = "-1"
    ops.append(" ".join(c))
    ops.append(new_route(rnd, 50.0, 75.0))
    ops.append("D")
    return ops


def chain(rnd, ks, typ=0, n=(12, 30), gap=6.0, p2p_back=False):
    """Routes that each start just past the last one's end."""
    out = []
    x, y, hd = 0.0, 0.0, rnd.uniform(-3, 3)
    dat = 0.0
    for k in ks:
        r = lay_route(rnd, k, typ, x, y, hd, rnd.randint(*n), dat=dat)
        out.append(r)
        e = r.pts[-1]
        hd = math.atan2(e["dy"], e["dx"]) + rnd.uniform(-0.3, 0.3)
        x = e["x"] + e["dx"] * gap + rnd.uniform(-3, 3)
        y = e["y"] + e["dy"] * gap + rnd.uniform(-3, 3)
        dat = struct.unpack("<f", r.pts[-1]["raw"][40:44])[0] + gap
        if p2p_back and rnd.random() < 0.5:
            dat -= rnd.uniform(50, 400)
    return out


def s_multi(rnd):
    rs = chain(rnd, (0, 1, 2, 3))
    t = lay_route(rnd, 4, 1, rs[1].pts[0]["x"], rs[1].pts[0]["y"],
                  math.atan2(rs[1].pts[0]["dy"], rs[1].pts[0]["dx"]), 20)
    ops = []
    for r in rs + [t]:
        ops += r.ops(rnd)
    for _ in range(30):
        r = rnd.choice(rs[:3])
        j = rnd.randrange(max(1, len(r.pts) - 12), len(r.pts))
        ops.append(car_op(rnd, r, j, given=rnd.random() < 0.8))
        ops.append(new_route(rnd, rnd.choice((50.0, 20.0, 30.0)),
                             rnd.choice((75.0, 200.0, 400.0))))
        ops.append("D")
    return ops


def s_p2p(rnd):
    rs = chain(rnd, (0, 1, 2), p2p_back=True)
    ops = ["K 1"]
    for r in rs:
        ops += r.ops(rnd)
    for _ in range(24):
        r = rnd.choice(rs[:2])
        j = rnd.randrange(max(1, len(r.pts) - 10), len(r.pts))
        ops.append(car_op(rnd, r, j, given=rnd.random() < 0.85))
        ops.append(new_route(rnd, 50.0, rnd.choice((75.0, 200.0))))
        ops.append("D")
    ops.append("K 0")
    r = rs[0]
    ops.append(car_op(rnd, r, len(r.pts) - 3))
    ops.append(new_route(rnd, 50.0, 200.0))
    ops.append("D")
    return ops


def s_loop(rnd):
    """A route whose end comes round to its start."""
    n = 36
    pts = []
    k = 0
    r = lay_route(rnd, 0, 0, 0.0, 0.0, 0.0, n, turn=0.0)
    # Bend it into a circle by hand.
    rad = 80.0
    raw = []
    for i, p in enumerate(r.pts):
        a = 2 * math.pi * i / n
        x, y = f32(rad * math.cos(a)), f32(rad * math.sin(a))
        dx, dy = f32(-math.sin(a + math.pi / n)), f32(math.cos(a + math.pi / n))
        b = bytearray(p["raw"])
        struct.pack_into("<2f", b, 0, x, y)
        struct.pack_into("<2f", b, 12, dx, dy)
        struct.pack_into("<f", b, 20, f32(2 * rad * math.sin(math.pi / n)))
        p.update(x=x, y=y, dx=dx, dy=dy, raw=bytes(b))
    ops = r.ops(rnd)
    for _ in range(16):
        j = rnd.randrange(n - 8, n)
        ops.append(car_op(rnd, r, j, given=rnd.random() < 0.7))
        ops.append(new_route(rnd, rnd.choice((50.0, 30.0)),
                             rnd.choice((75.0, 200.0))))
        ops.append("D")
    return ops


def s_far(rnd):
    r = lay_route(rnd, 0, 0, 0.0, 0.0, rnd.uniform(-3, 3), 40)
    ops = r.ops(rnd)
    for _ in range(16):
        j = rnd.randrange(40)
        ops.append(car_op(rnd, r, j, side=rnd.choice((20.0, -30.0, 60.0,
                                                      -120.0)),
                          given=rnd.random() < 0.6))
        ops.append(new_route(rnd, rnd.choice((50.0, 5.0, 0.5, 25.0)), 75.0))
        ops.append("D")
    return ops


def s_centre(rnd):
    """No driving line for any class: the centre, when the point runs the
    car's way."""
    r = lay_route(rnd, 0, 0, 0.0, 0.0, rnd.uniform(-3, 3), 40,
                  flags=[rnd.choice((0, 4, 8)) for _ in range(LINES)])
    ops = r.ops(rnd)
    for _ in range(20):
        j = rnd.randrange(40)
        ops.append(car_op(rnd, r, j, back=rnd.random() < 0.4,
                          given=rnd.random() < 0.6))
        ops.append(new_route(rnd, 50.0, rnd.choice((75.0, 40.0))))
        ops.append("D")
    return ops


def s_jump(rnd):
    rs = chain(rnd, (0, 1, 2))
    short = lay_route(rnd, 3, 0, 900.0, 900.0, 1.0, 3)
    ops = []
    for r in rs + [short]:
        ops += r.ops(rnd)
    for _ in range(16):
        r = rnd.choice(rs)
        j = rnd.randrange(len(r.pts))
        ops.append(car_op(rnd, r, j, given=rnd.random() < 0.8))
        ops.append("J")
    ops.append(car_op(rnd, short, 0))
    ops.append("J")
    ops.append(car_op(rnd, short, 2, given=False))
    ops.append("J")
    ops.append("J")
    # The place with no jump cam, on track 21 and not.
    place = lay_route(rnd, 4, 0, 1600.0, -884.0, 0.0, 12, turn=0.0)
    ops += place.ops(rnd)
    for same in (21, 20, 21):
        ops.append("S %d" % same)
        for dx, dy in ((0.0, 0.0), (39.0, -39.0), (40.0, 0.0), (41.0, 0.0),
                       (-20.0, 40.5), (0.0, -40.0), (0.0, 40.0),
                       (0.0, -40.5)):
            ops.append(car_at(1646.0 + dx, -884.0 + dy, 0.0, 0.0, 2))
            ops.append("J")
            ops.append(car_at(1646.0 + dx, -884.0 + dy, 0.0, 0.0, 2, 4,
                              "4:3"))
            ops.append("J")
    ops.append("S 0")
    return ops


def s_direct(rnd):
    rs = chain(rnd, (0, 1, 2))
    t = lay_route(rnd, 3, 1, rs[0].pts[5]["x"], rs[0].pts[5]["y"], 0.3, 15)
    ops = []
    for r in rs + [t]:
        ops += r.ops(rnd)
    for _ in range(10):
        r = rnd.choice(rs)
        j = rnd.randrange(len(r.pts))
        ops.append(car_op(rnd, r, j))
        ops.append(new_route(rnd, 50.0, 200.0))
        for _ in range(8):
            c = rnd.randrange(4)
            r2 = rnd.choice(rs)
            j2 = rnd.randrange(len(r2.pts))
            p = r2.pts[j2]
            x = f32(p["x"] + rnd.uniform(-15, 15))
            y = f32(p["y"] + rnd.uniform(-15, 15))
            line = rnd.choice((0, 1, 2, 5, 9))
            if c == 0:
                prev = rnd.choice(("-", "%d:%d" % (r2.k, j2),
                                   "%d:%d" % (r2.k, max(0, j2 - 2))))
                ops.append("Q %s %s %s %d %d %s" % (
                    h(x), h(y), h(f32(rnd.choice((50.0, 20.0, 5.0)))), line,
                    rnd.randrange(50), prev))
            elif c == 1:
                ops.append("W %d %d %s %s %d" % (r2.k, j2, h(x), h(y), line))
            elif c == 2:
                ops.append("X %d %s %d" % (rnd.randrange(1, 50),
                                           h(f32(rnd.choice((50.0, 20.0)))),
                                           line))
            else:
                ops.append("K %d" % rnd.randrange(2))
        ops.append("D")
    return ops


def set_line(r, j, line, s):
    """Point j's driving line `line` at s/256 across."""
    b = bytearray(r.pts[j]["raw"])
    struct.pack_into("<h", b, 48 + 2 * line, s)
    r.pts[j]["raw"] = bytes(b)


def s_edges(rnd):
    """The ties and the far ends: a line exactly 1000000 away, a line past
    that with the centre inside it, a candidate further than 50 from the
    position, and a point-to-point join whose two DistanceAroundTracks are
    equal."""
    r0 = lay_route(rnd, 0, 0, 0.0, 0.0, 0.0, 12, flags=[1] * LINES, turn=0.0)
    for line, s in ((2, 0), (3, 0), (4, -25600), (5, -25600), (6, 25600),
                    (7, 0)):
        set_line(r0, 0, line, s)
    for j in range(1, 12):
        set_line(r0, j, 2, 0)
        set_line(r0, j, 3, 0)
    e = r0.pts[-1]
    dat = struct.unpack("<f", e["raw"][40:44])[0]
    r1 = lay_route(rnd, 1, 0, e["x"] + 6.0, 0.0, 0.0, 12, dat=dat,
                   flags=[1] * LINES, turn=0.0)
    ops = r0.ops(rnd) + r1.ops(rnd)
    ops.append(car_at(5.0, 0.0, 0.0, 0.0, 1, 0, "0:0"))
    ops.append(new_route(rnd, 50.0, 200.0))
    for j in (2, 5, 8):
        p = r0.pts[j]
        for y in (150.0, -150.0, 60.0):
            ops.append("Q %s %s %s 1 3 -" % (h(f32(p["x"] - 2.0)), h(f32(y)),
                                            h(f32(300.0))))
    ops.append("K 1")
    p = r1.pts[0]
    for y in (3.0, -3.0):
        ops.append("Q %s %s %s 1 2 0:11" % (h(f32(p["x"] - 1.0)), h(f32(y)),
                                          h(f32(20.0))))
    ops.append("K 0")
    ops.append("D")
    for x, y, line in ((1e6, 0.0, 1), (-1e6, 0.0, 1), (0.0, 1e6, 1),
                       (0.0, -999990.0, 2), (0.0, 999990.0, 2),
                       (0.0, -999990.0, 3), (0.0, 999990.0, 3),
                       (0.0, -1000050.0, 2), (0.0, 1e6, 3)):
        ops.append("W 0 0 %s %s %d" % (h(f32(x)), h(f32(y)), line))
    return ops


def script():
    rnd = random.Random(0x9e71e3)
    sc = [s_one(rnd), s_noroute(rnd), s_multi(rnd), s_p2p(rnd), s_loop(rnd),
          s_far(rnd), s_centre(rnd), s_jump(rnd), s_direct(rnd)]
    sc.append(s_edges(random.Random(0x5ed9e5)))
    for _ in range(4):
        sc.append(s_multi(rnd))
        sc.append(s_direct(rnd))
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
        e.stub(B_MALLOC, self.s_malloc)
        e.stub(B_FREE, self.s_free)
        e.stub(GET_ROUTE, lambda em: self.car_route)
        e.stub(GET_ROUTE_POINT, lambda em: self.car_point)
        e.stub(CLEAN_UP_JUMP_CAM, self.s_cleanup)
        self.w = e.u32

    def emit(self, s):
        self.out.append(s)

    def arg(self, i):
        return self.e.reg[(4, 5, 6, 7, 8, 9)[i]] & M32

    def cstr(self, a):
        mem = self.e.mem
        end = mem.index(0, a)
        return bytes(mem[a:end]).decode("latin-1")

    def fill(self, a, n):
        self.e.mem[a:a + n] = bytes([PATTERN]) * n

    # ---- names -----------------------------------------------------------

    def name(self, a):
        a &= M32
        if a == 0:
            return "null"
        if a == PAT32:
            return "pat"
        if a == PR:
            return "pr"
        if ROUTES <= a < ROUTES + ROUTE_STRIDE * NROUTES:
            k, off = divmod(a - ROUTES, ROUTE_STRIDE)
            if off == 0:
                return "R%d" % k
            if off >= RT_HEADER and (off - RT_HEADER) % RT_POINT == 0:
                return "R%d:%d" % (k, (off - RT_HEADER) // RT_POINT)
        for i, (b, n) in enumerate(self.allocs):
            if a == b:
                return "A%d" % i
        return "?%08x" % a

    # ---- the stubs -------------------------------------------------------

    def s_malloc(self, em):
        size, name, line = s32(self.arg(0)), self.arg(1), s32(self.arg(2))
        a = (self.pool + 15) & ~15
        self.pool = a + max(size, 0)
        assert self.pool < POOL_END
        self.fill(a, max(size, 0))
        self.allocs.append((a, size))
        if line == 1538:
            what = "pts %d" % (size // 24)
            assert size % 24 == 0
        elif line == 1245:
            what = "route"
            assert size == 24
        else:
            what = "size %d" % size
        self.emit("  malloc A%d %s %d %s" % (len(self.allocs) - 1,
                                            self.cstr(name), line, what))
        return a

    def s_free(self, em):
        self.emit("  free %s" % self.name(self.arg(0)))

    def s_cleanup(self, em):
        p = self.arg(0)
        r = self.w(p + P_JUMP_ROUTE)
        self.emit("  cleanup %s" % self.name(r))
        if r:
            pts = self.w(r)
            if pts:
                self.emit("  free %s" % self.name(pts))
            self.emit("  free %s" % self.name(r))
        self.e.put32(p + P_JUMP_ROUTE, 0)

    # ---- the dumps -------------------------------------------------------

    def count_of(self, a):
        for b, n in self.allocs:
            if a == b:
                return n // 24
        return 0

    def dump_point(self, tag, a):
        w = self.w
        self.emit("    %s %s %s len %s off %s line %d gap %s" % (
            tag, self.name(w(a)), self.name(w(a + 4)), fx(w(a + 8)),
            fx(w(a + 12)), s32(w(a + 16)), fx(w(a + 20))))

    def dump_pr(self, a):
        w = self.w
        pts = w(a)
        self.emit("  %s n %d dir %s %s dist %s off %s pts %s" % (
            self.name(a), s32(w(a + 4)), fx(w(a + 8)), fx(w(a + 12)),
            fx(w(a + 16)), fx(w(a + 20)), self.name(pts)))
        for i in range(min(self.count_of(pts), 120)):
            self.dump_point("%d" % i, pts + 24 * i)

    # ---- the world -------------------------------------------------------

    def reset(self):
        e = self.e
        self.pool = POOL
        self.allocs = []
        self.racing, self.traffic = [], []
        self.link()
        e.put32(POINT2POINT, 0)
        e.put32(G_TRACK, TRACK)
        self.fill(TRACK, 256)
        e.mem[TRACK + T_SAME] = 0
        self.fill(PLAYER, 2752)
        e.put32(PLAYER + P_CAR, CAR)
        e.put32(PLAYER + P_JUMP_ROUTE, 0)
        self.fill(CAR, 2200)
        self.fill(CTI, 256)
        e.put32(CAR + C_CTI, CTI)
        self.car_route = 0
        self.car_point = 0

    def link(self):
        e = self.e
        for head, lst in ((MANAGER, self.racing),
                          (MANAGER + 8, self.traffic)):
            nodes = [head] + lst
            for i, n in enumerate(nodes):
                e.put32(n, nodes[(i + 1) % len(nodes)])
                e.put32(n + 4, nodes[i - 1])

    def route_hdr(self, t):
        e = self.e
        k, typ, n = int(t[1]), int(t[2]), int(t[3])
        a = route_at(k)
        e.mem[a:a + RT_HEADER] = bytes(RT_HEADER)
        struct.pack_into("<hh", e.mem, a + 8, 1, k)
        e.put32(a + 12, typ)
        e.put32(a + 16, n)
        e.put32(a + 20, n)
        for i in range(4):
            e.put32(a + 1048 + 4 * i, int(t[4 + i], 16))
        for i in range(LINES):
            e.put32(a + 40 + 48 * i, int(t[8 + i], 16))
        (self.racing if typ == 0 else self.traffic).append(a)
        self.link()
        self.cur_route = a
        self.cur_n = 0

    def point_of(self, s):
        if s == "-":
            return 0
        k, j = s.split(":")
        return route_at(int(k)) + RT_HEADER + RT_POINT * int(j)

    # ---- the ops ---------------------------------------------------------

    def call(self, fn, *args, **f):
        e = self.e
        for i, v in f.items():
            e.fpr[int(i[1:])] = v & M32
        return e.call(fn, *args, limit=2000000)

    def pr_ok(self, need):
        pts = self.w(PR)
        return pts not in (0, PAT32) and need < self.count_of(pts)

    def op(self, t):
        e = self.e
        c = t[0]
        if c == "G":
            self.route_hdr(t)
        elif c == "P":
            a = self.cur_route + RT_HEADER + RT_POINT * self.cur_n
            for i in range(28):
                e.put32(a + 4 * i, int(t[1 + i], 16))
            self.cur_n += 1
        elif c == "K":
            e.put32(POINT2POINT, int(t[1]))
        elif c == "S":
            e.mem[TRACK + T_SAME] = int(t[1]) & 0xff
        elif c == "C":
            for i, off in enumerate((C_POS, C_POS + 4, C_POS + 8, C_DIR,
                                     C_DIR + 4)):
                e.put32(CAR + off, int(t[1 + i], 16))
            e.mem[CTI + CTI_CLASS] = int(t[6]) & 0xff
            k = int(t[7])
            self.car_route = route_at(k) if k >= 0 else 0
            self.car_point = self.point_of(t[8])
        elif c == "N":
            self.fill(PR, 24)
            self.call(PR_CTOR, PR, CAR, f12=int(t[1], 16), f13=int(t[2], 16))
            self.dump_pr(PR)
        elif c == "D":
            self.call(PR_DTOR, PR, 0)
            self.e.put32(PR, 0)
            self.emit("  destroyed")
        elif c == "J":
            got = self.call(IS_JUMP_CAM, PLAYER)
            r = self.w(PLAYER + P_JUMP_ROUTE)
            self.emit("  jump %d route %s" % (got, self.name(r)))
            if r:
                self.dump_pr(r)
        elif c == "Q":
            if not self.pr_ok(int(t[5])):
                self.emit("  skip")
                return
            e.put32(VEC, int(t[1], 16))
            e.put32(VEC + 4, int(t[2], 16))
            got = self.call(PR_CLOSEST, PR, VEC, int(t[4]), int(t[5]),
                            self.point_of(t[6]), f12=int(t[3], 16))
            self.emit("  closest %d" % got)
            self.dump_pr(PR)
        elif c == "W":
            e.put32(VEC, int(t[3], 16))
            e.put32(VEC + 4, int(t[4], 16))
            self.fill(OUTP, 24)
            self.call(PR_DIST, PR, OUTP, route_at(int(t[1])),
                      self.point_of("%s:%s" % (t[1], t[2])), VEC, int(t[5]))
            self.emit("  dist %s" % fx(e.fpr[0]))
            self.dump_point("out", OUTP)
        elif c == "X":
            i = int(t[1])
            if not self.pr_ok(i) or self.w(self.w(PR) + 24 * (i - 1) + 4) \
                    in (0, PAT32):
                self.emit("  skip")
                return
            self.call(PR_NEXT, PR, i, int(t[3]), f12=int(t[2], 16))
            self.emit("  next %s" % fx(e.fpr[0]))
            self.dump_pr(PR)
        else:
            raise SystemExit("bad op %r" % (t,))

    def run(self, scenarios):
        for i, sc in enumerate(scenarios):
            self.emit("B %d" % i)
            self.reset()
            for ln in sc:
                if ln[0] not in "GP":
                    self.emit("> " + ln[:48])
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


def build_harness(tmp, name="prevroute_test"):
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


def M(name, before, after, rel=PRC):
    return (name, rel, before, after)


MUTATIONS = [
    # The constructor.
    M("init-npoints", "pr->nPoints = ee_trunc_w(length * 0.25f);",
      "pr->nPoints = ee_trunc_w(length * 0.2f);"),
    M("init-direction",
      "pr->vTrackDirection = car->TheTrackPathCoordinate.PathDirection;",
      "pr->vTrackDirection.x = -car->TheTrackPathCoordinate.PathDirection.x;"
      " pr->vTrackDirection.y = -car->TheTrackPathCoordinate.PathDirection.y;"),
    M("init-line", "line = car->pCarTypeInfo->CarClass;", "line = 0;"),
    M("init-given-both", "if (r != NULL && p != NULL)", "if (r != NULL)"),
    M("init-radius-le", "<= radius;", "< radius * 0.5f;"),
    M("init-closest-radius",
      "ok = preview_route_closest_point(pr, pos, radius, line, 0, NULL);",
      "ok = preview_route_closest_point(pr, pos, radius * 2.0f, line, 0,"
      " NULL);"),
    M("init-fail-free", "bFree(pr->pPoints);" + NL + "        pr->pPoints = NULL;",
      "pr->pPoints = NULL;"),
    M("init-fail-npoints", "pr->nPoints = 0;", "pr->nPoints = 1;"),
    M("init-offset-sign", "pr->fOffset = (pos->x - p->Position.x)",
      "pr->fOffset = (p->Position.x - pos->x)"),
    M("init-offset-cross", "- (pos->y - p->Position.y) * p->Direction.x;",
      "+ (pos->y - p->Position.y) * p->Direction.x;"),
    M("init-loop-end", "for (i = 1; i < pr->nPoints; i++) {",
      "for (i = 1; i < pr->nPoints - 1; i++) {"),
    M("init-distance-cmp", "if (pr->fDistance < total)",
      "if (pr->fDistance < total + 1.0f)"),
    M("init-null-break", "if (pr->pPoints[i].pPoint == NULL)",
      "if (pr->pPoints[i].pPoint == NULL && i < 0)"),
    M("init-distance", "pr->fDistance = total;", "pr->fDistance = length;"),
    M("init-npoints-end", "pr->nPoints = i;", "pr->nPoints = i - 1;"),

    # The destructor.
    M("destroy-self", "if (flags & 1)", "if (flags & 4)"),

    # NextPoint.
    M("next-same-route", "troute_get_point_number(r, pp) + 1 < r->NumPoints",
      "troute_get_point_number(r, pp) + 2 < r->NumPoints"),
    M("next-line", "cur->nLine = prevLine;", "cur->nLine = line;"),
    M("next-offset-line", "if (prevLine != -1)", "if (prevLine > 0)"),
    M("next-offset-centre", "cur->fOffset = 0.0f;", "cur->fOffset = 1.0f;"),
    M("next-gap-zero", "cur->fRouteGap = 0.0f;", "cur->fRouteGap = 1.0f;"),
    M("next-fail", "return 0.0f;", "return 1.0f;"),
    M("next-prev", "line, i, pp))", "line, i, NULL))"),
    M("next-gap-sign", "(pp->Position.x - cur->pPoint->Position.x)",
      "(cur->pPoint->Position.x - pp->Position.x)"),
    M("next-gap-cross", "- (pp->Position.y - cur->pPoint->Position.y)",
      "+ (pp->Position.y - cur->pPoint->Position.y)"),
    M("next-length-z", "d = sqrtf(dx * dx + dy * dy + dz * dz);",
      "d = sqrtf(dx * dx + dy * dy);"),
    M("next-length-order", "d = sqrtf(dx * dx + dy * dy + dz * dz);",
      "d = sqrtf(dx * dx + (dy * dy + dz * dz));"),
    M("next-length-slot", "pr->pPoints[i - 1].fLength = d;",
      "pr->pPoints[i].fLength = d;"),

    # ClosestDistance.
    M("cd-best-init", "float best = PREVIEW_ROUTE_FAR;",
      "float best = 100.0f;"),
    M("cd-centre-found", "if (i == 2) {" + NL + "            if (found)",
      "if (i == 2) {" + NL + "            if (0)"),
    M("cd-centre-way", "* pr->vTrackDirection.y < 0.0f)",
      "* pr->vTrackDirection.y > 0.0f)"),
    M("cd-centre-offset", "            offset = 0.0f;",
      "            offset = 1.0f;"),
    M("cd-line-index", "l = 2 * line + i;", "l = 2 * line + 1 - i;"),
    M("cd-flag-valid", "if (!(flags & LINE_VALID) && !(flags & LINE_FAKE))",
      "if (!(flags & LINE_VALID))"),
    M("cd-flag-fake", "if (!(flags & LINE_VALID) && !(flags & LINE_FAKE))",
      "if (!(flags & LINE_FAKE))"),
    M("cd-distance", "d = sqrtf(dx * dx + dy * dy);",
      "d = dx * dx + dy * dy;"),
    M("cd-best-lt", "if (d < best) {", "if (d <= best) {"),
    M("cd-first-wins", "bestLine = l;" + NL + "            if (found)",
      "bestLine = l;" + NL + "            if (0)"),
    M("cd-out-offset", "out->fOffset = bestOffset;", "out->fOffset = 0.0f;"),
    M("cd-out-line", "out->nLine = bestLine;", "out->nLine = -1;"),

    # ClosestPoint.
    M("cp-best-init", "float bestDist = PREVIEW_ROUTE_FAR;",
      "float bestDist = 50.0f;"),
    M("cp-ahead", "TRFIND_AHEAD_ONLY,", "0,"),
    M("cp-prev-skip", "if (p == NULL || p == prev)", "if (p == NULL)"),
    M("cp-best-lt", "if (d < bestDist) {", "if (d <= bestDist) {"),
    M("cp-last-p", "if (p == NULL || best.pPoint == NULL)",
      "if (best.pPoint == NULL)"),
    M("cp-p2p", "if (!RaceParametersPoint2Point || prev == NULL)",
      "if (prev == NULL)"),
    M("cp-backwards",
      "return !(best.pPoint->DistanceAroundTrack < prev->DistanceAroundTrack);",
      "return 1;"),
    M("cp-backwards-tie",
      "return !(best.pPoint->DistanceAroundTrack < prev->DistanceAroundTrack);",
      "return best.pPoint->DistanceAroundTrack > prev->DistanceAroundTrack;"),

    # IsJumpCamAvailable.
    M("jc-track", "SameAsTrackNumber == PLAYER_NO_JUMP_CAM_TRACK",
      "SameAsTrackNumber != PLAYER_NO_JUMP_CAM_TRACK", PZC),
    M("jc-radius", "PLAYER_NO_JUMP_CAM_RADIUS))",
      "PLAYER_NO_JUMP_CAM_RADIUS * 0.5f))", PZC),
    M("jc-place", "{ 1646.0f, -884.0f }", "{ 1646.0f, -885.0f }", PZC),
    M("jc-cleanup-first", "player_clean_up_jump_cam(p);" + NL
      + "    car = p->MyCar;", "car = p->MyCar;", PZC),
    M("jc-alloc-line", "PLAYER_CPP, 1245, 16", "PLAYER_CPP, 1246, 16", PZC),
    M("jc-radius-arg", "car, 50.0f,", "car, 40.0f,", PZC),
    M("jc-length", "75.0f);", "70.0f);", PZC),
    M("jc-five", "nPoints < 5)", "nPoints < 4)", PZC),
    M("jc-cleanup-short", "nPoints < 5) {" + NL
      + "        player_clean_up_jump_cam(p);", "nPoints < 5) {", PZC),
]

EQUIVALENT = {}


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
        todo, SOURCES, "prevroute_test",
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
