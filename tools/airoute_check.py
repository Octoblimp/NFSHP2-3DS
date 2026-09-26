#!/usr/bin/env python3
"""Cross-check 3DS Files/source/airoute.c -- GetNearestRoutePoint,
GetNextRoutePoint, GetNextRoutePointAhead and NearestRoutePointInfo::IsValid,
the AI's "where on the route network am I" -- against the image itself, run
in mipsemu.

The model is the image: the four functions as shipped, and beneath them
TrackRoute::FindClosestPoint, bBoundingBoxIsInside, GetDistanceAway,
TrackPathManager::CompareDistances, GetSignpost, both Signpost accessors,
and TrackRouteManager's constructor, AddRouteToRightList and Loader. So this
also checks trackroute.c's search against the image, which
trackroute_check.py's Python model cannot. The harness runs the same op
script on the port and prints the same lines. `Emu(ieee=True)`: nothing here
divides.

**The arena.** Every route either side sees lives in one byte arena, laid
out identically on both: routes back to back as the loader finds them on
the disc, each cut off after its last point. A pointer that is not a route's
own point -- a point from another route, a point four bytes out of step --
gives an index that is garbage, and the image and the port compute the same
garbage only when the bytes sit the same distance apart. In the arena they
do. The routes' list words are the image's own in the model (it strings
them) and untouched in the port (which keeps arrays), and nothing prints
them.

**Labels, not pointers.** A pointer prints as `rK` (route slot K), `rK.pJ`
(its point J) or `a+N` (N bytes from the arena, as a signed word) -- the same
string on both sides for the same bytes.

**The signposts.** A 256-entry table on both sides, so any sign byte reads
inside it. The entries a scenario does not set are sign 1, which does not
branch, so they never reach GetNewRoute.

**What the port does not follow.** Three reads the image makes through
nothing (see airoute.h and trackroute.h) are hooked in the model, and a
scenario that reaches one fails loudly instead of comparing:
GetNewRoutePoint on an empty route slot (the image returns 1064 + 112 *
NewPoint, the port NULL), a sign naming a route past slot 99, and
GetNextRoutePoint handed a NULL point or route. The fourth, the second step
of GetNextRoutePointAhead running off a route, is allowed where the image's
read of address 0 -- zero here -- is at least 8 from the start, since both
sides then stop with the point NULL.

Scenarios: IsValid over the route-number boundary, the index boundaries
and foreign and misaligned points; GetNextRoutePoint over every sign value,
the Backwards bit and the other flags, the last point, garbage indices, and
steps chained from below a route's table; GetNextRoutePointAhead's three
steps and every boundary between them; the search over both lists, the four
RoutesToSearch and the values beyond them, the TrackDirection the port
starts with and both it can be set to, the traffic numbering boundary at 60, each flag bit,
ties, the shrinking radius, track distance against plane distance, and the
nothing-found cases; and TRACKB12's own 17 routes and 56 signs, when
extracted/ has them.

    python tools/airoute_check.py
    python tools/airoute_check.py --mutate [--only a,b]
    python tools/airoute_check.py --dump out/airoute
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
from mipsemu import Emu, M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/airoute_test.c"
ARC = "3DS Files/source/airoute.c"
ARH = "3DS Files/source/airoute.h"
SOURCES = [HARNESS, ARC,
           "3DS Files/source/race.c",
           "3DS Files/source/trackroute.c",
           "3DS Files/source/trackpath.c",
           "3DS Files/source/quickspline.c",
           "3DS Files/source/bmem.c",
           "3DS Files/source/bmatrix.c",
           "3DS Files/source/bvector.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c",
           "3DS Files/source/bchunk.c"]

HARNESS_TIMEOUT = 300

TRACKB12 = ROOT / "extracted" / "TRACKS" / "TRACKB12.BUN"
TRACKB12_PATHS = 0x007a8270         # the 0x80034147 track path chunk
TRACKB12_ROUTES = 0x007af66c        # 0x00034121
TRACKB12_SIGNS = 0x007f922c         # 0x00034122

# ================================================================ the image

MGR = 0x0030c458                    # TheTrackRouteManager
SIGN_PTR = 0x003241d0               # SignpostArray
NSIGN_PTR = 0x003241d4              # NumSignposts
TPM = 0x00313768                    # TheTrackPathManager; TrackLength at 0
TRACKDIR = 0x0031252c               # TheRaceParameters.TrackDirection

ARENA = 0x01A00000
ARENA_SIZE = 0x80000
SIGNS = 0x01B00000
NSIGNS = 256
INFO = 0x01B01000
POS = 0x01B01010

HDR, PT = 1064, 112
FULL_ROUTE = 115752

SYM = dict(
    nearest="GetNearestRoutePoint__FP21NearestRoutePointInfoP8bVector2"
            "14RoutesToSearchif",
    next="GetNextRoutePoint__FP21NearestRoutePointInfo",
    ahead="GetNextRoutePointAhead__FP21NearestRoutePointInfo",
    valid="IsValid__21NearestRoutePointInfo",
    ctor="__17TrackRouteManager",
    add="AddRouteToRightList__17TrackRouteManagerP10TrackRoute",
    loader="Loader__17TrackRouteManagerP6bChunk",
)

# The instructions the hooks sit on.
AT_NEWROUTE_INDEX = 0x001b6f70      # GetNewRoute: v1 = NewRoute
AT_NEWPOINT_INDEX = 0x001b6f98      # GetNewRoutePoint: v1 = NewRoute
AT_NEWPOINT_ROUTE = 0x001b6fac      # GetNewRoutePoint: a1 = the route
AT_NEXT_ENTRY = 0x001c1808          # GetNextRoutePoint
AT_AHEAD_SECOND = 0x001c19b4        # GetNextRoutePointAhead: v0 = step 2

# ---- the ops -----------------------------------------------------------------
#
# Each op is its code, its argument count and its arguments, so OP_WORDS and
# OP_SIGNS can carry a run.

(OP_TAG, OP_CLEAR, OP_WORDS, OP_ROUTE, OP_SIGNS, OP_NSIGNS, OP_RESET,
 OP_ADD, OP_LOADER, OP_LEN, OP_DIR, OP_INFO, OP_NEAREST, OP_NEXT,
 OP_AHEAD, OP_VALID) = range(16)

ARGS = {OP_TAG: 1, OP_CLEAR: 0, OP_WORDS: None, OP_ROUTE: 2,
        OP_SIGNS: None, OP_NSIGNS: 1, OP_RESET: 0, OP_ADD: 1, OP_LOADER: 1,
        OP_LEN: 1, OP_DIR: 1, OP_INFO: 2, OP_NEAREST: 5, OP_NEXT: 0,
        OP_AHEAD: 0, OP_VALID: 0}

# RoutesToSearch
RACING, TRAFFIC, FORWARD, ONCOMING = range(4)

# The FindClosestPoint flags.
F_AHEAD, F_POSTED, F_NOHELI, F_SKIPR, F_SKIPT, F_TRACK = (1, 2, 4, 8, 16, 32)

# A point's Bits with no signpost, road block or radar trap.
NO_SIGN = 0xff | (0x3f << 8) | (0x3f << 22)
TRP_NO_HELISHEET = 0x4000
TRP_POSTED = 0x8000

# Signpost flag bits, above the three-bit sign.
SP_BACKWARDS = 0x08
SP_OTHERS = 0x10 | 0x20 | 0x40      # NoStakeout, Hairpin, Cloaked
DEFAULT_SIGN = (0x01 << 8, 0)       # route 0, sign 1, point 0, distance 0


def fb(x):
    """A Python float's single-precision bits."""
    return struct.unpack("<I", struct.pack("<f", x))[0]


def bf(b):
    return struct.unpack("<f", struct.pack("<I", b & M32))[0]


def f32(x):
    return bf(fb(x))


class Script(object):
    def __init__(self):
        self.ops = []
        self.tags = []

    def op(self, code, *args):
        assert ARGS[code] is None or len(args) == ARGS[code], (code, args)
        self.ops.append((code,) + tuple(
            fb(a) if isinstance(a, float) else int(a) for a in args))

    def tag(self, s):
        self.tags.append(s)
        self.op(OP_TAG, len(self.tags) - 1)

    def encode(self):
        out = [len(self.tags)]
        for s in self.tags:
            b = s.encode("latin-1")
            out.append(len(b))
            out.extend(b)
        flat = []
        for o in self.ops:
            flat.append(o[0])
            flat.append(len(o) - 1)
            flat.extend(o[1:])
        out.append(len(flat))
        out.extend(flat)
        return struct.pack("<%di" % len(out), *[s32(v & M32) for v in out])

    # ---- sugar -----------------------------------------------------------

    def blob(self, off, data):
        assert off % 4 == 0 and len(data) % 4 == 0
        self.op(OP_WORDS, off,
                *struct.unpack("<%dI" % (len(data) // 4), bytes(data)))

    def word(self, off, w):
        self.op(OP_WORDS, off, w & M32)

    def signs(self, table):
        """All 256 entries: `table` maps an index to its two words."""
        ws = []
        for i in range(NSIGNS):
            ws.extend(table.get(i, DEFAULT_SIGN))
        self.op(OP_SIGNS, 0, *ws)

    def info(self, route, point):
        self.op(OP_INFO, -1 if route is None else route,
                -1 if point is None else point)

    def nearest(self, x, y, which, flags, around=0.0):
        self.op(OP_NEAREST, float(x), float(y), which, flags, float(around))


def sign(new_route, kind, new_point=0, flags=0, distance=0.0):
    return (new_route | ((kind | flags) << 8) | (new_point << 16),
            fb(distance))


# ================================================================ the routes


class Pt(object):
    """One route point. `d` is the direction, worked out from the next
    point when not given; `dist` the distance around the track, the running
    chord length when not given."""

    def __init__(self, x, y, d=None, dist=None, bits=NO_SIGN):
        self.x, self.y, self.d, self.dist, self.bits = x, y, d, dist, bits


def route_bytes(number, rtype, pts, dist0=0.0):
    n = len(pts)
    b = bytearray(HDR + PT * n)
    struct.pack_into("<IIhhiiiIiff", b, 0, 0, 0, 1, number, rtype, n, n,
                     1, -1, 0.0, 0.0)
    if n:
        xs = [p.x for p in pts]
        ys = [p.y for p in pts]
        struct.pack_into("<ffff", b, 1048, min(xs), min(ys), max(xs),
                         max(ys))
    d = dist0
    dirs = []
    for i, p in enumerate(pts):
        if i + 1 < n:
            q = pts[i + 1]
            ln = math.hypot(q.x - p.x, q.y - p.y)
            dirs.append(((q.x - p.x) / ln, (q.y - p.y) / ln, ln)
                        if ln else (1.0, 0.0, 0.0))
        else:
            dirs.append(dirs[-1][:2] + (0.0,) if dirs else (1.0, 0.0, 0.0))
    for i, p in enumerate(pts):
        if i:
            d += dirs[i - 1][2]
        dx, dy = p.d if p.d is not None else dirs[i][:2]
        struct.pack_into("<11fI", b, HDR + PT * i, p.x, p.y, 0.0, dx, dy,
                         dirs[i][2], 8.0, 8.0, 0.0, 0.0,
                         d if p.dist is None else p.dist, p.bits)
        # The driving lines are 0xff, so a point read out of step mostly
        # finds 0xff -- no signpost -- where a sign number would be.
        b[HDR + PT * i + 48:HDR + PT * i + 111] = b"\xff" * 63
        b[HDR + PT * i + 111] = number & 0xff
    return b


class Arena(object):
    """Routes back to back, as the loader finds them."""

    def __init__(self, sc, start=64):
        self.sc = sc
        self.at = start
        self.slots = []
        sc.op(OP_CLEAR)

    def route(self, number, rtype, pts, **kw):
        b = route_bytes(number, rtype, pts, **kw)
        off = self.at
        self.sc.blob(off, b)
        slot = len(self.slots)
        self.sc.op(OP_ROUTE, slot, off)
        self.slots.append((off, len(pts)))
        self.at += len(b)
        assert self.at <= ARENA_SIZE
        return slot

    def r(self, slot):
        return self.slots[slot][0]

    def p(self, slot, i):
        return self.slots[slot][0] + HDR + PT * i

    def bits(self, slot, i, bits):
        self.sc.word(self.p(slot, i) + 44, bits)

    def add(self, *slots):
        for s in slots:
            self.sc.op(OP_ADD, self.r(s))


def line(n, x0, y0, dx, dy):
    return [Pt(x0 + dx * i, y0 + dy * i) for i in range(n)]


# ================================================================ the script


def scenario_valid(sc):
    sc.tag("valid")
    a = Arena(sc)
    sc.signs({})
    rs = [a.route(1, 0, line(5, 0.0, 0.0, 20.0, 0.0)),
          a.route(69, 1, line(3, 0.0, 10.0, 20.0, 0.0)),
          a.route(70, 1, line(3, 0.0, 20.0, 20.0, 0.0)),
          a.route(-1, 0, line(2, 0.0, 30.0, 20.0, 0.0)),
          a.route(-32768, 0, line(2, 0.0, 40.0, 20.0, 0.0)),
          a.route(32767, 0, line(2, 0.0, 50.0, 20.0, 0.0)),
          a.route(2, 0, []),
          a.route(0, 0, line(1, 0.0, 60.0, 20.0, 0.0)),
          a.route(3, 0, line(9, 0.0, 70.0, 20.0, 0.0))]
    for s in rs:
        n = a.slots[s][1]
        other = rs[(s + 1) % len(rs)]
        prev = rs[s - 1]
        cases = [(a.r(s), None), (None, a.p(s, 0)), (None, None),
                 (a.r(s), a.p(s, 0)), (a.r(s), a.p(s, max(n - 1, 0))),
                 (a.r(s), a.p(s, n)), (a.r(s), a.p(s, -1)),
                 (a.r(s), a.p(s, -2)), (a.r(s), a.p(s, 0) + 4),
                 (a.r(s), a.p(s, 0) + 56), (a.r(s), a.p(s, 1) + 108),
                 (a.r(s), a.r(s)), (a.r(s), a.p(other, 0)),
                 (a.r(s), a.p(prev, 0)),
                 (a.r(s), a.p(other, a.slots[other][1] - 1)),
                 (a.r(s), 0), (a.r(s), ARENA_SIZE - 16)]
        for rr, pp in cases:
            sc.info(rr, pp)
            sc.op(OP_VALID)


NEXT_SIGNS = {
    0: sign(7, 0, 2),
    1: sign(7, 2, 3),
    2: sign(7, 1, 1),
    3: sign(7, 3, 1),
    4: sign(7, 4, 1),
    5: sign(7, 5, 1),
    6: sign(7, 6, 1),
    7: sign(7, 7, 1),
    8: sign(7, 0, 2, SP_BACKWARDS),
    9: sign(7, 2, 2, SP_BACKWARDS),
    10: sign(7, 0, 4, SP_OTHERS),
    11: sign(7, 2, 4, SP_OTHERS),
    12: sign(50, 0, 0),
    13: sign(3, 2, 7),
    14: sign(7, 0, 5),
    15: sign(7, 1, 1, SP_BACKWARDS),
    16: sign(3, 0, 0, 0, 123.5),
    17: sign(7, 3, 1, SP_BACKWARDS | SP_OTHERS),
    18: sign(7, 2, 0, 0x80),
    255: sign(7, 0, 1),
}


def scenario_next(sc):
    a = Arena(sc)
    sc.signs(NEXT_SIGNS)
    sc.op(OP_NSIGNS, 20)
    A = a.route(3, 0, line(8, 0.0, 0.0, 20.0, 0.0))
    B = a.route(7, 0, line(6, 0.0, 40.0, 20.0, 0.0))
    C = a.route(50, 1, line(5, 0.0, -40.0, 20.0, 0.0))
    D = a.route(9, 0, line(3, 0.0, 80.0, 20.0, 0.0))
    sc.op(OP_RESET)
    a.add(A, B, C)          # D is in the arena and in no slot

    sc.tag("next: along")
    for s in (A, B, C, D):
        for i in range(a.slots[s][1]):
            sc.info(a.r(s), a.p(s, i))
            sc.op(OP_NEXT)

    sc.tag("next: every sign")
    for at in (3, 0, 7):
        for k in sorted(NEXT_SIGNS) + [19, 200, 254]:
            a.bits(A, at, (NO_SIGN & ~0xff) | k)
            sc.info(a.r(A), a.p(A, at))
            sc.op(OP_NEXT)
        a.bits(A, at, NO_SIGN)

    sc.tag("next: the rest of the bits")
    for bits in (NO_SIGN | TRP_POSTED | TRP_NO_HELISHEET, 0xffffffff,
                 0x000000ff, 0x100000ff, (NO_SIGN & ~0xff) | 0xfe,
                 0xffffff00, 0x0000ff01, 0x00000100 | 12):
        a.bits(A, 2, bits)
        sc.info(a.r(A), a.p(A, 2))
        sc.op(OP_NEXT)
    a.bits(A, 2, NO_SIGN)

    sc.tag("next: the route stays")
    # The step works on the route it is handed, not the point's own.
    for rr, pp in ((B, (A, 2)), (A, (B, 2)), (C, (A, 0)), (B, (A, 0)),
                   (A, (B, 5)), (C, (B, 3)), (D, (A, 7)), (A, (D, 0))):
        sc.info(a.r(rr), a.p(*pp))
        sc.op(OP_NEXT)
    for off in (4, 56, 108, -4, -56, -1064, 112 * 3 + 8):
        sc.info(a.r(A), a.p(A, 2) + off)
        sc.op(OP_NEXT)
        sc.info(a.r(B), a.p(A, 5) + off)
        sc.op(OP_NEXT)

    sc.tag("next: twice, from behind the table")
    # A point below the route's table gives a negative index, and the step
    # lands below the table too. The second step reads through it, which
    # on a 64-bit host only works if the step subtracted.
    for rr, pp in ((B, (A, 2)), (B, (A, 0)), (C, (A, 7)), (C, (B, 3)),
                   (D, (A, 1)), (D, (C, 4))):
        for off in (0, 4, -56):
            sc.info(a.r(rr), a.p(*pp) + off)
            sc.op(OP_NEXT)
            sc.op(OP_NEXT)
            sc.op(OP_NEXT)


def scenario_ahead(sc):
    """Each case is its own route, starting at (1000, 500) so that the image's
    read of address 0 is never within 8 of the start."""
    a = Arena(sc)
    X, Y = 1000.0, 500.0
    B_PTS = [Pt(X + 30.0, Y), Pt(X - 30.0, Y), Pt(X - 20.0, Y),
             Pt(X + 5.0, Y), Pt(X - 7.0, Y + 4.0), Pt(X - 40.0, Y)]
    B = a.route(7, 0, B_PTS)
    signs = {
        0: sign(7, 0, 0),       # branch to B0, ahead
        1: sign(7, 0, 1),       # branch to B1, behind; B2 is 20 off
        2: sign(7, 2, 2),       # branch to B2, behind; B3 is 5 off
        3: sign(7, 0, 5),       # branch to B's last point, behind
        4: sign(7, 1, 0),       # no branch
        5: sign(7, 0, 4, SP_BACKWARDS),     # no branch
        6: sign(7, 0, 3),       # branch to B3: ahead by 5
        7: sign(7, 0, 4),       # branch to B4, behind; B5 is 40 off
    }
    sc.signs(signs)
    sc.op(OP_NSIGNS, 8)

    def s(k):
        return (NO_SIGN & ~0xff) | k

    cases = [
        # (name, points after the start, start sign, start direction)
        ("plain", [Pt(X + 20.0, Y), Pt(X + 40.0, Y)], None, None),
        ("plain behind", [Pt(X - 20.0, Y), Pt(X + 3.0, Y)], None, None),
        ("no branch, ahead", [Pt(X + 20.0, Y), Pt(X + 40.0, Y)], 4, None),
        ("no branch, behind, far", [Pt(X - 10.0, Y), Pt(X + 40.0, Y),
                                    Pt(X + 60.0, Y)], 4, None),
        ("no branch, behind, near", [Pt(X - 5.0, Y), Pt(X + 6.0, Y),
                                     Pt(X + 26.0, Y)], 4, None),
        ("no branch, behind, 8", [Pt(X - 5.0, Y), Pt(X + 8.0, Y),
                                  Pt(X + 28.0, Y)], 4, None),
        ("no branch, behind, 8 in y", [Pt(X - 5.0, Y), Pt(X, Y + 8.0),
                                       Pt(X + 28.0, Y)], 4, None),
        ("no branch, behind, under 8", [Pt(X - 5.0, Y),
                                        Pt(f32(X + 7.99994), Y),
                                        Pt(X + 28.0, Y)], 4, None),
        ("no branch, dot +0", [Pt(X, Y + 5.0), Pt(X + 3.0, Y)], 4, None),
        ("no branch, dot -0", [Pt(X, Y + 5.0), Pt(X + 3.0, Y)], 4,
         (-1.0, -0.0)),
        ("no branch, a hair behind", [Pt(f32(X - 0.00006), Y),
                                      Pt(X + 3.0, Y), Pt(X + 30.0, Y)],
         5, None),
        ("no branch, start's direction", [Pt(X + 10.0, Y, d=(-1.0, 0.0)),
                                          Pt(X + 3.0, Y)], 4, None),
        ("no branch, the start's own direction", [Pt(X + 10.0, Y),
                                                  Pt(X + 3.0, Y),
                                                  Pt(X + 30.0, Y)], 4,
         (-1.0, 0.0)),
        ("no branch, behind in y", [Pt(X, Y - 10.0), Pt(X, Y + 4.0),
                                    Pt(X, Y + 30.0)], 4, (0.0, 1.0)),
        ("no branch, diagonal", [Pt(X - 3.0, Y + 1.0), Pt(X + 4.0, Y + 4.0),
                                 Pt(X + 30.0, Y)], 4, (0.6, 0.8)),
        ("no branch, dy only", [Pt(X + 3.0, Y - 5.0), Pt(X + 20.0, Y),
                                Pt(X + 30.0, Y)], 4, (0.6, 0.8)),
        ("no branch, dx only", [Pt(X - 5.0, Y + 3.0), Pt(X + 20.0, Y),
                                Pt(X + 30.0, Y)], 4, (0.8, 0.6)),
        ("no branch, second step branches", [Pt(X - 5.0, Y, bits=s(0)),
                                             Pt(X + 40.0, Y)], 4, None),
        ("no branch, second step branches near", [Pt(X - 5.0, Y,
                                                     bits=s(6)),
                                                  Pt(X + 40.0, Y)], 4, None),
        ("no branch, third step branches", [Pt(X - 5.0, Y),
                                            Pt(X + 4.0, Y, bits=s(0)),
                                            Pt(X + 40.0, Y)], 4, None),
        ("no branch, third step off the end", [Pt(X - 5.0, Y),
                                               Pt(X + 4.0, Y)], 4, None),
        ("no branch, second step off the end", [Pt(X - 5.0, Y)], 4, None),
        ("no branch, last point", [], 4, None),
        ("last point", [], None, None),
        ("branch ahead", [Pt(X - 20.0, Y), Pt(X - 40.0, Y)], 0, None),
        ("branch behind, far", [Pt(X + 20.0, Y)], 1, None),
        ("branch behind, near", [Pt(X + 20.0, Y)], 2, None),
        ("branch behind, off the end", [Pt(X + 20.0, Y)], 3, None),
        ("branch ahead by 5", [Pt(X + 20.0, Y)], 6, None),
        ("branch behind, then 40 off", [Pt(X + 20.0, Y)], 7, None),
        ("branch from the last point", [], 1, None),
    ]
    starts = []
    for name, rest, k, d in cases:
        # The start faces +x unless the case says otherwise: left to
        # itself it would face its next point, which is never behind it.
        pts = [Pt(X, Y, d=(1.0, 0.0) if d is None else d,
                  bits=NO_SIGN if k is None else s(k))] + rest
        starts.append((name, a.route(3, 0, pts)))
    sc.op(OP_RESET)
    a.add(B)

    sc.tag("ahead")
    for name, slot in starts:
        sc.tag("ahead: " + name)
        sc.info(a.r(slot), a.p(slot, 0))
        sc.op(OP_AHEAD)

    sc.tag("ahead: nothing to start from")
    sc.info(a.r(starts[0][1]), None)
    sc.op(OP_AHEAD)
    sc.info(None, a.p(starts[0][1], 0))
    sc.op(OP_AHEAD)
    sc.info(None, None)
    sc.op(OP_AHEAD)
    sc.info(None, a.p(starts[3][1], 0))
    sc.op(OP_AHEAD)

    sc.tag("ahead: the route it is handed")
    # An unsigned point stepped on a route it is not in: one garbage step,
    # stored and never read.
    sc.info(a.r(starts[1][1]), a.p(B, 1))
    sc.op(OP_AHEAD)
    for i in range(len(B_PTS)):
        sc.info(a.r(B), a.p(B, i))
        sc.op(OP_AHEAD)


def scenario_nearest(sc, rnd):
    a = Arena(sc)
    sc.signs({})
    n, step = 11, 20.0
    R1 = a.route(1, 0, line(n, 0.0, 0.0, step, 0.0))
    R2 = a.route(2, 0, line(n, 0.0, 30.0, step, 0.0), dist0=200.0)
    R3 = a.route(5, 0, line(n, 0.0, 0.0, step, 0.0))
    R4 = a.route(6, 0, line(n, 0.0, 0.8, step, 0.0))
    T50 = a.route(50, 1, line(n, 0.0, -40.0, step, 0.0))
    T59 = a.route(59, 1, line(n, 0.0, -60.0, step, 0.0))
    T60 = a.route(60, 1, line(n, 0.0, -80.0, step, 0.0))
    T61 = a.route(61, 1, line(n, 0.0, -100.0, step, 0.0))
    T45 = a.route(45, 1, line(n, 0.0, -120.0, step, 0.0))
    ODD = a.route(8, 2, line(n, 0.0, 10.0, step, 0.0))
    # Posted and NoHelisheet on a few points each.
    for i in (2, 3, 7):
        a.bits(R1, i, NO_SIGN | TRP_POSTED)
    for i in (5, 6):
        a.bits(R2, i, NO_SIGN | TRP_POSTED | TRP_NO_HELISHEET)
    for i in (4, 5, 6):
        a.bits(R1, i, NO_SIGN | TRP_NO_HELISHEET)
    a.bits(T59, 5, NO_SIGN | TRP_POSTED)

    # This has to come before anything in the script sets the direction:
    # it checks the port starts where the disc's .data does (0, forward).
    sc.tag("nearest: the direction before anything sets it")
    sc.op(OP_RESET)
    a.add(T50, T60)
    for which in (FORWARD, ONCOMING):
        for y in (-45.0, -75.0):
            sc.info(None, None)
            sc.nearest(100.0, y, which, 0)

    sc.op(OP_LEN, 400.0)
    sc.op(OP_DIR, 0)

    sc.tag("nearest: nothing in the lists")
    sc.op(OP_RESET)
    for which in (RACING, TRAFFIC, FORWARD, ONCOMING, 4, -1):
        sc.info(a.r(R1), a.p(R1, 3))
        sc.nearest(100.0, 0.0, which, 0)

    sc.tag("nearest: traffic only")
    a.add(T50, ODD)
    for which in (RACING, TRAFFIC, FORWARD, ONCOMING):
        sc.info(a.r(R1), a.p(R1, 3))
        sc.nearest(100.0, 10.0, which, 0)

    sc.tag("nearest: the lot")
    sc.op(OP_RESET)
    a.add(R2, R1, R3, R4, T61, T50, T60, ODD, T45, T59)
    xs = (-50.0, 10.0, 100.0, 190.0, 260.0)
    ys = (-130.0, -110.0, -90.0, -70.0, -50.0, -20.0, 0.0, 0.5, 15.0, 29.0,
          45.0)
    for which in (RACING, TRAFFIC):
        for x in xs:
            for y in ys:
                sc.info(None, None)
                sc.nearest(x, y, which, 0)

    sc.tag("nearest: which and direction")
    for direction in (0, 1, 2):
        sc.op(OP_DIR, direction)
        for which in (RACING, TRAFFIC, FORWARD, ONCOMING, 4, -1, 7):
            for x, y in ((100.0, -45.0), (100.0, -65.0), (100.0, -75.0),
                         (100.0, -85.0), (100.0, -95.0), (100.0, -125.0),
                         (100.0, -140.0), (100.0, 10.0)):
                sc.info(None, None)
                sc.nearest(x, y, which, 0)
    sc.op(OP_DIR, 0)

    sc.tag("nearest: flags")
    around = (0.0, 100.0, 300.0, 390.0)
    for flags in (0, F_AHEAD, F_POSTED, F_NOHELI, F_SKIPR, F_SKIPT, F_TRACK,
                  F_TRACK | F_AHEAD, F_TRACK | F_POSTED, F_POSTED | F_NOHELI,
                  F_TRACK | F_POSTED | F_NOHELI | F_AHEAD, 0x3f, 0x40):
        for x, y in ((100.0, 15.0), (95.0, 12.0), (41.0, 5.0), (150.0, 26.0),
                     (100.0, -61.0), (205.0, 0.0), (-5.0, 3.0)):
            for d in (around if flags & F_TRACK else (0.0,)):
                for which in (RACING, TRAFFIC):
                    sc.info(None, None)
                    sc.nearest(x, y, which, flags, d)

    sc.tag("nearest: track distance")
    for length in (400.0, 0.0, 250.0, 1e6):
        sc.op(OP_LEN, length)
        for d in (0.0, 50.0, 100.0, 199.0, 200.0, 300.0, 399.0, -100.0,
                  800.0):
            for x, y in ((100.0, 15.0), (100.0, 14.0), (100.0, 16.0),
                         (60.0, 29.0), (140.0, 1.0)):
                sc.info(None, None)
                sc.nearest(x, y, RACING, F_TRACK, d)
                sc.info(None, None)
                sc.nearest(x, y, RACING, F_TRACK | F_POSTED, d)
    sc.op(OP_LEN, 400.0)

    sc.tag("nearest: ties and the shrinking radius")
    for x, y in ((100.0, 15.0), (100.0, 0.4), (100.0, 0.5), (100.0, 0.6),
                 (110.0, 0.4), (110.0, 15.4), (110.0, 14.6), (0.0, 0.0),
                 (200.0, 30.0), (100.0, -50.0), (100.0, -110.0)):
        for which in (RACING, TRAFFIC, FORWARD, ONCOMING):
            sc.info(None, None)
            sc.nearest(x, y, which, 0)

    sc.tag("nearest: far away")
    for x, y in ((900000.0, 0.0), (0.0, -999000.0), (999999.0, 0.0),
                 (1000199.0, 0.0), (1000200.0, 0.0), (5e6, 5e6),
                 (-999999.0, 0.0), (-999998.0, 30.0)):
        for which in (RACING, TRAFFIC):
            sc.info(a.r(R2), a.p(R2, 1))
            sc.nearest(x, y, which, 0)
            sc.info(a.r(R2), a.p(R2, 1))
            sc.nearest(x, y, which, F_TRACK, 100.0)

    sc.tag("nearest: random")
    for _ in range(120):
        x = rnd.uniform(-60.0, 260.0)
        y = rnd.uniform(-140.0, 50.0)
        which = rnd.choice((RACING, TRAFFIC, FORWARD, ONCOMING))
        flags = rnd.choice((0, 0, F_TRACK, F_POSTED | F_TRACK, F_AHEAD,
                            F_NOHELI))
        sc.op(OP_DIR, rnd.choice((0, 1)))
        sc.info(None, None)
        sc.nearest(x, y, which, flags, rnd.uniform(0.0, 400.0))
    sc.op(OP_DIR, 0)


def scenario_trackb12(sc, rnd):
    if not TRACKB12.exists():
        print("  (no %s -- the disc scenario is skipped)" % TRACKB12)
        return
    d = TRACKB12.read_bytes()
    cid, size = struct.unpack_from("<II", d, TRACKB12_ROUTES)
    assert cid == 0x00034121
    chunk = d[TRACKB12_ROUTES:TRACKB12_ROUTES + 8 + size]
    scid, ssize = struct.unpack_from("<II", d, TRACKB12_SIGNS)
    assert scid == 0x00034122
    nsigns = ssize // 8
    pcid, _ = struct.unpack_from("<II", d, TRACKB12_PATHS)
    assert pcid == 0x80034147
    # The first path's EndDistance: InitTrackPaths' TrackLength.
    length = struct.unpack_from("<f", d, TRACKB12_PATHS + 16 + 12)[0]

    sc.tag("trackb12: load")
    sc.op(OP_CLEAR)
    sc.blob(0, chunk)
    routes = []
    off = 8
    while off < 8 + size:
        num, rtype, npts = struct.unpack_from("<hii", chunk, off + 10)
        routes.append((off, num, rtype, npts))
        sc.op(OP_ROUTE, len(routes) - 1, off)
        off += FULL_ROUTE - (1024 - npts) * PT
    table = {}
    for i in range(nsigns):
        table[i] = struct.unpack_from("<II", d, TRACKB12_SIGNS + 8 + 8 * i)
    sc.signs(table)
    sc.op(OP_NSIGNS, nsigns)
    sc.op(OP_LEN, length)
    sc.op(OP_DIR, 0)
    sc.op(OP_RESET)
    sc.op(OP_LOADER, 0)

    def pt(r, i):
        return r[0] + HDR + PT * i

    def pfloat(r, i, k):
        return struct.unpack_from("<f", chunk, pt(r, i) + k)[0]

    sc.tag("trackb12: next and ahead from every point")
    for r in routes:
        for i in range(r[3]):
            sc.info(r[0], pt(r, i))
            sc.op(OP_NEXT)
            sc.info(r[0], pt(r, i))
            sc.op(OP_AHEAD)

    sc.tag("trackb12: valid")
    for k, r in enumerate(routes):
        o = routes[(k + 5) % len(routes)]
        for i in (0, r[3] - 1, r[3], -1):
            sc.info(r[0], pt(r, i))
            sc.op(OP_VALID)
        for i in (0, o[3] // 2, o[3] - 1):
            sc.info(r[0], pt(o, i))
            sc.op(OP_VALID)

    sc.tag("trackb12: nearest along the racing routes")
    for r in routes:
        if r[2] != 0:
            continue
        for i in range(0, r[3], 23):
            x, y = pfloat(r, i, 0), pfloat(r, i, 4)
            dx, dy = pfloat(r, i, 12), pfloat(r, i, 16)
            dist = pfloat(r, i, 40)
            for side in (0.0, 6.5, -11.0):
                px, py = x + side * dy, y - side * dx
                sc.info(None, None)
                sc.nearest(px, py, RACING, F_POSTED | F_TRACK, dist)
            sc.info(None, None)
            sc.nearest(x + 3.0, y - 2.0, rnd.choice((TRAFFIC, FORWARD,
                                                     ONCOMING)), 0)
            sc.info(None, None)
            sc.nearest(x, y, RACING, F_TRACK, dist + rnd.uniform(-60, 60))

    sc.tag("trackb12: nearest anywhere")
    for _ in range(40):
        r = rnd.choice(routes)
        i = rnd.randrange(r[3])
        x = pfloat(r, i, 0) + rnd.uniform(-80.0, 80.0)
        y = pfloat(r, i, 4) + rnd.uniform(-80.0, 80.0)
        sc.op(OP_DIR, rnd.choice((0, 1)))
        sc.info(None, None)
        sc.nearest(x, y, rnd.choice((RACING, TRAFFIC, FORWARD, ONCOMING)),
                   rnd.choice((0, F_AHEAD, F_TRACK, F_POSTED | F_TRACK)),
                   rnd.uniform(0.0, length))
    sc.op(OP_DIR, 0)


def script():
    rnd = random.Random(0xa120)
    sc = Script()
    scenario_valid(sc)
    scenario_next(sc)
    scenario_ahead(sc)
    scenario_nearest(sc, rnd)
    scenario_trackb12(sc, rnd)
    return sc


# ================================================================ the model


class Model(object):
    def __init__(self, sc):
        self.sc = sc
        self.out = []
        e = self.e = Emu(ieee=True)
        self.fn = {k: e.addr_of(v) for k, v in SYM.items()}
        self.routes = {}
        e.put32(SIGN_PTR, SIGNS)
        e.put32(NSIGN_PTR, 0)
        self.hooks()

    def emit(self, s):
        self.out.append(s)

    def label(self, a):
        e = self.e
        a &= M32
        if a == 0:
            return "null"
        off = s32((a - ARENA) & M32)
        for slot in sorted(self.routes):
            base = self.routes[slot]
            if off == base:
                return "r%d" % slot
            t = base + HDR
            n = s32(e.u32(ARENA + base + 16))
            if n > 0 and t <= off < t + PT * n and (off - t) % PT == 0:
                return "r%d.p%d" % (slot, (off - t) // PT)
        return "a%+d" % off

    def pinfo(self):
        e = self.e
        return "%s %s" % (self.label(e.u32(INFO)), self.label(e.u32(INFO + 4)))

    def hooks(self):
        e = self.e

        def route_index(em):
            if e.reg[3] & M32 >= 100:
                raise AssertionError("a sign names route %d, past the "
                                     "manager's table" % (e.reg[3] & M32))

        def empty_slot(em):
            if e.reg[5] & M32 == 0:
                raise AssertionError("a sign names an empty route slot: "
                                     "the image returns 1064 + 112 * "
                                     "NewPoint there, the port NULL")

        def next_entry(em):
            a0 = e.reg[4] & M32
            if e.u32(a0) == 0 or e.u32(a0 + 4) == 0:
                raise AssertionError("GetNextRoutePoint handed a NULL "
                                     "route or point")

        def ahead_second(em):
            if e.reg[2] & M32:
                return
            s0 = e.reg[16] & M32
            assert e.u32(0) == 0 and e.u32(4) == 0
            sx, sy = bf(e.u32(s0)), bf(e.u32(s0 + 4))
            if math.hypot(sx, sy) < 8.5:
                raise AssertionError("the second step ran off the route "
                                     "within 8 of address 0's position")

        e.hook(AT_NEWROUTE_INDEX, route_index)
        e.hook(AT_NEWPOINT_INDEX, route_index)
        e.hook(AT_NEWPOINT_ROUTE, empty_slot)
        e.hook(AT_NEXT_ENTRY, next_entry)
        e.hook(AT_AHEAD_SECOND, ahead_second)

    def ref(self, v):
        v = s32(v)
        if v < 0:
            return 0
        assert v < ARENA_SIZE, v
        return ARENA + v

    def run(self):
        tag = "?"
        for i, o in enumerate(self.sc.ops):
            if o[0] == OP_TAG:
                tag = self.sc.tags[o[1]]
            try:
                self.step(o)
            except AssertionError as x:
                raise AssertionError("op %d %r in [%s]: %s"
                                     % (i, o[:6], tag, x))
        return self.out

    def step(self, o):
        sc, e, emit, fn = self.sc, self.e, self.emit, self.fn
        code, a = o[0], o[1:]
        if code == OP_TAG:
            emit("[%s]" % sc.tags[a[0]])
        elif code == OP_CLEAR:
            e.mem[ARENA:ARENA + ARENA_SIZE] = bytes(ARENA_SIZE)
            self.routes = {}
        elif code == OP_WORDS:
            off, ws = a[0], a[1:]
            e.mem[ARENA + off:ARENA + off + 4 * len(ws)] = struct.pack(
                "<%dI" % len(ws), *[w & M32 for w in ws])
        elif code == OP_ROUTE:
            self.routes[a[0]] = a[1]
        elif code == OP_SIGNS:
            first, ws = a[0], a[1:]
            e.mem[SIGNS + 8 * first:SIGNS + 8 * first + 4 * len(ws)] = \
                struct.pack("<%dI" % len(ws), *[w & M32 for w in ws])
        elif code == OP_NSIGNS:
            e.put32(NSIGN_PTR, a[0])
        elif code == OP_RESET:
            emit("reset")
            e.call(fn["ctor"], MGR)
        elif code == OP_ADD:
            p = self.ref(a[0])
            emit("add %s" % self.label(p))
            e.call(fn["add"], MGR, p)
        elif code == OP_LOADER:
            emit("loader")
            e.call(fn["loader"], MGR, self.ref(a[0]))
        elif code == OP_LEN:
            e.put32(TPM, a[0])
        elif code == OP_DIR:
            e.put32(TRACKDIR, a[0])
        elif code == OP_INFO:
            e.put32(INFO, self.ref(a[0]))
            e.put32(INFO + 4, self.ref(a[1]))
        elif code == OP_NEAREST:
            x, y, which, flags, around = a
            e.put32(POS, x)
            e.put32(POS + 4, y)
            e.fpr[12] = around & M32
            r = e.call(fn["nearest"], INFO, POS, which, flags)
            emit("nearest %08x %08x which %d flags %d around %08x -> %d %s"
                 % (x & M32, y & M32, s32(which), s32(flags), around & M32,
                    r, self.pinfo()))
        elif code in (OP_NEXT, OP_AHEAD):
            before = self.pinfo()
            e.call(fn["next" if code == OP_NEXT else "ahead"], INFO)
            emit("%s %s -> %s" % ("next" if code == OP_NEXT else "ahead",
                                  before, self.pinfo()))
        elif code == OP_VALID:
            r = e.call(fn["valid"], INFO)
            emit("valid %s -> %d" % (self.pinfo(), r))
        else:
            raise ValueError("op %d" % code)


def model(sc):
    return Model(sc).run()


# ================================================================ the build


def build_harness(tmp, name="airoute_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, ops_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(ops_path)], stdout=fh,
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

MUTATIONS = [
    # -- IsValid ------------------------------------------------------------
    ("valid-route-null", ARC, "    if (r == NULL || info->Point == NULL)",
     "    if (info->Point == NULL)"),
    ("valid-point-null", ARC, "    if (r == NULL || info->Point == NULL)",
     "    if (r == NULL)"),
    ("valid-number-69", ARC, "(int32_t)r->RouteNumber < 70u))",
     "(int32_t)r->RouteNumber < 69u))"),
    ("valid-number-71", ARC, "(int32_t)r->RouteNumber < 70u))",
     "(int32_t)r->RouteNumber < 71u))"),
    ("valid-number-signed", ARC,
     "    if (!((uint32_t)(int32_t)r->RouteNumber < 70u))",
     "    if (!(r->RouteNumber < 70))"),
    ("valid-number-drop", ARC,
     "    if (!((uint32_t)(int32_t)r->RouteNumber < 70u))\n        return 0;\n",
     ""),
    ("valid-negative", ARC, "    if (idx < 0)\n        return 0;\n", ""),
    ("valid-end", ARC, "    return idx < r->NumPoints;",
     "    return idx <= r->NumPoints;"),
    ("valid-end-minus", ARC, "    return idx < r->NumPoints;",
     "    return idx < r->NumPoints - 1;"),
    # -- the index ------------------------------------------------------------
    ("index-inverse", ARC, "return (int32_t)(d * 0xb6db6db7u) >> 4;",
     "return (int32_t)(d / 7u) >> 4;"),
    ("index-shift", ARC, "return (int32_t)(d * 0xb6db6db7u) >> 4;",
     "return (int32_t)(d * 0xb6db6db7u) >> 3;"),
    ("index-logical", ARC, "return (int32_t)(d * 0xb6db6db7u) >> 4;",
     "return (int32_t)((d * 0xb6db6db7u) >> 4);"),
    ("index-divide", ARC, "return (int32_t)(d * 0xb6db6db7u) >> 4;",
     "return (int32_t)d / 112;"),
    ("index-at-stride", ARC, "+ (int32_t)((uint32_t)idx * 112u));",
     "+ (int32_t)((uint32_t)idx * 104u));"),
    ("index-at-unsigned", ARC, "+ (int32_t)((uint32_t)idx * 112u));",
     "+ (uint32_t)idx * 112u);"),
    # -- GetNearestRoutePoint -------------------------------------------------
    ("near-racing-which", ARC, "    if (which == ALL_RACING_ROUTES) {",
     "    if (which != ALL_TRAFFIC_ROUTES && which < FORWARD_TRAFFIC_ROUTES) {"),
    ("near-lists-swapped", ARC,
     "        list = m->Racing;\n        count = m->NumRacing;",
     "        list = m->Traffic;\n        count = m->NumTraffic;"),
    ("near-traffic-list", ARC,
     "        list = m->Traffic;\n        count = m->NumTraffic;",
     "        list = m->Racing;\n        count = m->NumRacing;"),
    ("near-count-one-short", ARC, "    for (i = 0; i < count; i++) {",
     "    for (i = 0; i < count - 1; i++) {"),
    ("near-all-traffic-filters", ARC,
     "        if (which != ALL_TRAFFIC_ROUTES) {",
     "        if (1) {"),
    ("near-filter-above-one", ARC,
     "        if (which != ALL_TRAFFIC_ROUTES) {",
     "        if (which > ALL_TRAFFIC_ROUTES) {"),
    ("near-oncoming-is-2", ARC,
     "            if (which == ONCOMING_TRAFFIC_ROUTES)",
     "            if (which == FORWARD_TRAFFIC_ROUTES)"),
    ("near-oncoming-from-3", ARC,
     "            if (which == ONCOMING_TRAFFIC_ROUTES)",
     "            if (which >= ONCOMING_TRAFFIC_ROUTES)"),
    ("near-no-flip", ARC, "                forward = !forward;\n", ""),
    ("near-direction", ARC,
     "RaceParametersTrackDirection == TRACK_DIRECTION_FORWARD;",
     "RaceParametersTrackDirection != TRACK_DIRECTION_BACKWARD;"),
    ("near-direction-inverted", ARC,
     "RaceParametersTrackDirection == TRACK_DIRECTION_FORWARD;",
     "RaceParametersTrackDirection != TRACK_DIRECTION_FORWARD;"),
    ("near-filter-sense", ARC,
     "&& (r->RouteNumber < AIROUTE_FORWARD_TRAFFIC_LIMIT) != forward)",
     "&& (r->RouteNumber < AIROUTE_FORWARD_TRAFFIC_LIMIT) == forward)"),
    ("near-filter-le", ARC,
     "&& (r->RouteNumber < AIROUTE_FORWARD_TRAFFIC_LIMIT) != forward)",
     "&& (r->RouteNumber <= AIROUTE_FORWARD_TRAFFIC_LIMIT) != forward)"),
    ("near-limit-59", ARH, "#define AIROUTE_FORWARD_TRAFFIC_LIMIT 60",
     "#define AIROUTE_FORWARD_TRAFFIC_LIMIT 59"),
    ("near-limit-61", ARH, "#define AIROUTE_FORWARD_TRAFFIC_LIMIT 60",
     "#define AIROUTE_FORWARD_TRAFFIC_LIMIT 61"),
    ("near-radius-small", ARH, "#define AIROUTE_SEARCH_RADIUS 999999.0f",
     "#define AIROUTE_SEARCH_RADIUS 99999.0f"),
    ("near-radius-large", ARH, "#define AIROUTE_SEARCH_RADIUS 999999.0f",
     "#define AIROUTE_SEARCH_RADIUS 1000001.0f"),
    ("near-radius-fixed", ARC,
     "p = troute_find_closest_point(r, pos, best, flags, distanceAround);",
     "p = troute_find_closest_point(r, pos, AIROUTE_SEARCH_RADIUS, flags,"
     " distanceAround);"),
    ("near-flags-dropped", ARC,
     "p = troute_find_closest_point(r, pos, best, flags, distanceAround);",
     "p = troute_find_closest_point(r, pos, best, 0, distanceAround);"),
    ("near-flags-track-only", ARC,
     "p = troute_find_closest_point(r, pos, best, flags, distanceAround);",
     "p = troute_find_closest_point(r, pos, best, flags & TRFIND_BY_TRACK_"
     "DISTANCE, distanceAround);"),
    ("near-around-dropped", ARC,
     "p = troute_find_closest_point(r, pos, best, flags, distanceAround);",
     "p = troute_find_closest_point(r, pos, best, flags, 0.0f);"),
    ("near-bytrack-bit", ARC,
     "    int                byTrack = flags & TRFIND_BY_TRACK_DISTANCE;",
     "    int                byTrack = flags & TRFIND_POSTED_ONLY;"),
    ("near-bytrack-never", ARC,
     "    int                byTrack = flags & TRFIND_BY_TRACK_DISTANCE;",
     "    int                byTrack = 0;"),
    ("near-away-around", ARC,
     "            d = trpoint_get_distance_away(p, pos, distanceAround);",
     "            d = trpoint_get_distance_away(p, pos, 0.0f);"),
    ("near-plane-y", ARC,
     "            float dy = p->Position.y - pos->y;",
     "            float dy = p->Position.y - pos->x;"),
    ("near-plane-sum", ARC,
     "            d = sqrtf(dx * dx + dy * dy);",
     "            d = sqrtf(dx * dx + dx * dy);"),
    ("near-plane-squared", ARC,
     "            d = sqrtf(dx * dx + dy * dy);",
     "            d = dx * dx + dy * dy;"),
    ("near-plane-manhattan", ARC,
     "            d = sqrtf(dx * dx + dy * dy);",
     "            d = fabsf(dx) + fabsf(dy);"),
    ("near-best-test", ARC, "        if (d < best) {", "        if (1) {"),
    ("near-best-le", ARC, "        if (d < best) {",
     "        if (d <= best) {"),
    ("near-best-not-kept", ARC,
     "            best = d;\n            bestPoint = p;",
     "            bestPoint = p;"),
    ("near-null-skip", ARC,
     "        if (p == NULL)\n            continue;\n", ""),
    ("near-found-route-only", ARC,
     "    if (bestRoute == NULL || bestPoint == NULL)",
     "    if (bestRoute == NULL)"),
    ("near-returns-0", ARC,
     "    info->Route = bestRoute;\n    return 1;",
     "    info->Route = bestRoute;\n    return 0;"),
    ("near-route-kept", ARC, "    info->Route = bestRoute;\n", ""),
    ("near-point-kept", ARC, "    info->Point = bestPoint;\n", ""),
    ("near-clears-on-miss", ARC,
     "    if (bestRoute == NULL || bestPoint == NULL)\n        return 0;",
     "    if (bestRoute == NULL || bestPoint == NULL) {\n"
     "        info->Route = NULL;\n        info->Point = NULL;\n"
     "        return 0;\n    }"),
    # -- GetNextRoutePoint ----------------------------------------------------
    ("next-no-signposts", ARC,
     "    if (trpoint_has_signpost(p)) {\n        Signpost *s",
     "    if (0) {\n        Signpost *s"),
    ("next-backwards-ignored", ARC,
     "        if (!(s->Flags & SIGNPOST_BACKWARDS) && (sign == 2 || sign == 0))",
     "        if (sign == 2 || sign == 0)"),
    ("next-backwards-other-bit", ARC,
     "        if (!(s->Flags & SIGNPOST_BACKWARDS) && (sign == 2 || sign == 0))",
     "        if (!(s->Flags & SIGNPOST_HAIRPIN) && (sign == 2 || sign == 0))"),
    ("next-sign-1", ARC,
     "(sign == 2 || sign == 0))", "(sign == 1 || sign == 0))"),
    ("next-sign-3", ARC,
     "(sign == 2 || sign == 0))", "(sign == 2 || sign == 0 || sign == 3))"),
    ("next-sign-0-only", ARC,
     "(sign == 2 || sign == 0))", "(sign == 0))"),
    ("next-sign-2-only", ARC,
     "(sign == 2 || sign == 0))", "(sign == 2))"),
    ("next-sign-even", ARC,
     "(sign == 2 || sign == 0))", "((sign & 1) == 0))"),
    ("next-sign-mask", ARC,
     "        uint32_t  sign = s->Flags & SIGNPOST_SIGN_MASK;",
     "        uint32_t  sign = s->Flags & 0x03u;"),
    ("next-sign-unmasked", ARC,
     "        uint32_t  sign = s->Flags & SIGNPOST_SIGN_MASK;",
     "        uint32_t  sign = s->Flags;"),
    ("next-branch-route-kept", ARC,
     "            info->Route = signpost_get_new_route(s);\n", ""),
    ("next-branch-point-kept", ARC,
     "            info->Point = signpost_get_new_route_point(s);\n", ""),
    ("next-branch-falls-through", ARC,
     "            info->Point = signpost_get_new_route_point(s);\n"
     "            return;",
     "            info->Point = signpost_get_new_route_point(s);"),
    ("next-end-le", ARC, "    if (idx + 1 < r->NumPoints)",
     "    if (idx + 1 <= r->NumPoints)"),
    ("next-end-own", ARC, "    if (idx + 1 < r->NumPoints)",
     "    if (idx < r->NumPoints)"),
    ("next-step-2", ARC, "        info->Point = point_at(r, idx + 1);",
     "        info->Point = point_at(r, idx + 2);"),
    ("next-end-kept", ARC,
     "    else\n        info->Point = NULL;\n", ""),
    ("next-end-last", ARC,
     "    else\n        info->Point = NULL;",
     "    else\n        info->Point = point_at(r, idx);"),
    # -- GetNextRoutePointAhead -------------------------------------------------
    ("ahead-no-start-test", ARC,
     "    if (start == NULL || info->Route == NULL)",
     "    if (info->Route == NULL)"),
    ("ahead-no-route-test", ARC,
     "    if (start == NULL || info->Route == NULL)",
     "    if (start == NULL)"),
    ("ahead-sign-of-new", ARC,
     "    if (!trpoint_has_signpost(start))\n        return;\n    p = info->Point;\n"
     "    if (p == NULL)\n        return;",
     "    p = info->Point;\n    if (p == NULL)\n        return;\n"
     "    if (!trpoint_has_signpost(p))\n        return;"),
    ("ahead-sign-ignored", ARC,
     "    if (!trpoint_has_signpost(start))\n        return;\n", ""),
    ("ahead-sign-inverted", ARC,
     "    if (!trpoint_has_signpost(start))\n        return;\n",
     "    if (trpoint_has_signpost(start))\n        return;\n"),
    ("ahead-dot-le", ARC, "    if (!(d < 0.0f))", "    if (!(d <= 0.0f))"),
    ("ahead-dot-gt", ARC, "    if (!(d < 0.0f))", "    if (d < 0.0f)"),
    ("ahead-dot-new-direction", ARC,
     "    d = (p->Position.x - start->Position.x) * start->Direction.x\n"
     "        + (p->Position.y - start->Position.y) * start->Direction.y;",
     "    d = (p->Position.x - start->Position.x) * p->Direction.x\n"
     "        + (p->Position.y - start->Position.y) * p->Direction.y;"),
    ("ahead-dot-x-only", ARC,
     "        + (p->Position.y - start->Position.y) * start->Direction.y;",
     ";"),
    ("ahead-dot-y-dir", ARC,
     "    d = (p->Position.x - start->Position.x) * start->Direction.x\n",
     "    d = (p->Position.x - start->Position.x) * start->Direction.y\n"),
    ("ahead-dot-x-dir", ARC,
     "        + (p->Position.y - start->Position.y) * start->Direction.y;",
     "        + (p->Position.y - start->Position.y) * start->Direction.x;"),
    ("ahead-dot-reversed", ARC,
     "    d = (p->Position.x - start->Position.x) * start->Direction.x\n"
     "        + (p->Position.y - start->Position.y) * start->Direction.y;",
     "    d = (start->Position.x - p->Position.x) * start->Direction.x\n"
     "        + (start->Position.y - p->Position.y) * start->Direction.y;"),
    ("ahead-no-second", ARC,
     "    ai_get_next_route_point(info);\n    p = info->Point;\n"
     "    // The image", "    p = info->Point;\n    // The image"),
    ("ahead-second-null", ARC,
     "    if (p == NULL)\n        return;\n    dx = start",
     "    dx = start"),
    ("ahead-near-le", ARC, "    if (sqrtf(dx * dx + dy * dy) < 8.0f)",
     "    if (sqrtf(dx * dx + dy * dy) <= 8.0f)"),
    ("ahead-near-7", ARC, "    if (sqrtf(dx * dx + dy * dy) < 8.0f)",
     "    if (sqrtf(dx * dx + dy * dy) < 7.9f)"),
    ("ahead-near-squared", ARC, "    if (sqrtf(dx * dx + dy * dy) < 8.0f)",
     "    if (dx * dx + dy * dy < 8.0f)"),
    ("ahead-near-y", ARC, "    dy = start->Position.y - p->Position.y;",
     "    dy = 0.0f;"),
    ("ahead-near-from-first", ARC,
     "    ai_get_next_route_point(info);\n    p = info->Point;\n"
     "    // The image",
     "    start = p;\n    ai_get_next_route_point(info);\n"
     "    p = info->Point;\n    // The image"),
    ("ahead-no-third", ARC,
     "    if (sqrtf(dx * dx + dy * dy) < 8.0f)\n"
     "        ai_get_next_route_point(info);",
     "    (void)dx;\n    (void)dy;"),
    # -- the race parameter -------------------------------------------------------
    ("race-direction-initial", "3DS Files/source/race.c",
     "eTrackDirection RaceParametersTrackDirection; // 0x0031252c",
     "eTrackDirection RaceParametersTrackDirection = 1; // 0x0031252c"),
]

# Mutations that cannot change what the image does, each with its reason.
EQUIVALENT = {
    # FindClosestPoint only returns a point nearer than the radius it is
    # handed, and it measures exactly as the search does -- the same
    # subtraction order, the same GetDistanceAway -- so with the running
    # best as that radius the `d < best` after it always holds.
    "near-best-test":
        "FindClosestPoint only returns a point nearer than the running "
        "best it is handed, measured the same way",
    "near-best-le":
        "the same: `d < best` always holds, so `<=` never sees a tie",
    # The other half of the same redundancy. A route searched with the
    # fixed radius returns its nearest point, or one no nearer than the
    # best; the `d < best` test then throws away exactly the points the
    # running radius would have kept FindClosestPoint from returning. Its
    # walk and its skips do not depend on the radius, only its bounding-box
    # test does, and a box the running radius would have rejected cannot
    # hold a point nearer than it.
    "near-radius-fixed":
        "the `d < best` after the call throws away exactly what the "
        "running radius would have",
    # bestRoute and bestPoint are only ever written together.
    "near-found-route-only":
        "bestRoute and bestPoint are written together",
    # With a NULL point the index is (0 - table) * inverse >> 4, garbage
    # that depends on where the host put the arena. The image never
    # computes it. The mutant survives unless that garbage happens to land
    # in [0, NumPoints), which at a 64-bit host's addresses it does not.
    "valid-point-null":
        "a NULL point's index is garbage the host's addresses keep out of "
        "range",
}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name


def mutate_pass(only=None):
    sc = script()
    base = model(sc)
    caught = 0
    survived = []
    missing = []
    equivalent = []
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only is not None:
        unknown = sorted(set(only) - {m[0] for m in MUTATIONS})
        if unknown:
            sys.exit("no such mutation: " + " ".join(unknown))

    opsdir = tempfile.TemporaryDirectory()
    ops = Path(opsdir.name) / "ops.bin"
    ops.write_bytes(sc.encode())
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, ops, out)
        if diff(base, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for m in todo:
        name, rel = m[0], m[1]
        edits = m[2] if len(m) == 3 else [(m[2], m[3], 1)]
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        new = text
        ok = True
        for before, after, count in edits:
            probe = before.replace(NL, "\r\n") if crlf else before
            repl = after.replace(NL, "\r\n") if crlf else after
            if new.count(probe) < count:
                ok = False
                break
            new = new.replace(probe, repl, count)
        if not ok:
            missing.append(name)
            print("  %-44s PATTERN NOT FOUND" % name)
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
                rc = run_harness(exe, ops, out)
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
    opsdir.cleanup()

    real = [m for m in todo if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    # An entry whose mutant was caught is a wrong reason, not a spare one.
    # --only leaves the others unrun, so only the ones that ran are judged.
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
        ops = Path(tmp) / "ops.bin"
        ops.write_bytes(sc.encode())
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, ops, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(lines, harness)
    print("%d ops, %d lines, %d differ" % (len(sc.ops), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
