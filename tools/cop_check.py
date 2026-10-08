#!/usr/bin/env python3
"""Cross-check 3DS Files/source/cop.c, and CreateCop and AddCopCarToRace in
copmgr.c, against the retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own cop.obj: tCop's constructor (0x0022d3f8)
and destructor (0x0022d418), tPlayerCop's (0x0022d548, 0x0022d5b0),
tAICop's (0x0022db20, 0x0022dcc0) with its operator new (0x00230d78) and
delete (0x00230d68), the three setters, ClearPursuit (0x0022e510),
ClearSpeedTrap (0x0022e558), DisableMyCar (0x00230ac8), the zone
permissions (0x0022f770, 0x0022f810, 0x0022f850), the two
IsAIControlled (0x00230d60, 0x00230d98), reached through the image's own
tables (0x002bd6e8, 0x002bd6c0, 0x002bd698), and the drive target:
IsNearPursuitTarget (0x00230bf8), InitializeDriveTarget (0x00230638) and
UpdateDriveTarget (0x002307d0), with TrackRoutePoint::GetPosition
(0x001c1408) run as shipped under it. Then copmgr.obj's CreateCop
(0x002272e8), 0x002276a0 (the cop cars' largest size) and
AddCopCarToRace (0x00227d78). The harness (tools/src/cop_test.c) runs
cop.c, copmgr.c, copmanager.c, trackroute.c and vtable.c and prints the
same lines.

**The drive target's world** is three routes of real points, laid out as
retail's (a 1064-byte header, then 112-byte points), each car's driver,
and four stand-ins answering by rules the script sets:
GetNearestRoutePoint (a queue of answers: the return and the route and
point it leaves), GetNextRoutePoint (a point on; off a route's end, point
0 of the route it links to, or NULL), and Car::GetRoute and
GetRoutePoint (a route and point per car). DriveTarget::Clear and
AddPointToTarget are logged with their arguments.

**The stubs**, logged and answered by the same rule on both sides: both
bMallocs (a block of 0xcd), __builtin_delete, bOMalloc and bFree on the
cops' slot pool, Car's constructor (the car's type by its DriverInfo, and
its position), SetControlMode (a fresh CopDriver of 0xcd),
SetMovementMode, ResetToPosition, tPursuit::RemoveCopFromPursuit and
RemovePrimarySpeaker (which can move the cop to another pursuit), and
CarDamage's wreck (0x001b5bc8).

**Compared** are the stubs' logs and, on `dump`, the manager's counts,
cops, largest size, radar-trap spawn timers and traps' cops; the world's
car list both ways; the car types' mass and inertia; and every word of
each cop, its car's fields the constructor sets, and its CopDriver.

The port names the nameless bMalloc(52, 16) for its own diagnostics;
both sides log it as `malloc2`.

    python tools/cop_check.py
    python tools/cop_check.py --mutate [--only a,b]
    python tools/cop_check.py --dump out/cop
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
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/cop_test.c"
COP = "3DS Files/source/cop.c"
COPMGR = "3DS Files/source/copmgr.c"
SOURCES = [HARNESS, COP, COPMGR, "3DS Files/source/copmanager.c",
           "3DS Files/source/trackroute.c",
           "3DS Files/source/trackpath.c",
           "3DS Files/source/quickspline.c",
           "3DS Files/source/bchunk.c",
           "3DS Files/source/emath.c",
           "3DS Files/source/vtable.c", "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c",
           "3DS Files/source/bvector.c",
           "3DS Files/source/bmatrix.c"]
HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = retail_model.RETAIL_GP
RP = 0x0031a898                         # TheRaceParameters
RP_DIR, RP_MAXCOPS = 12, 604
G_COPMGR = GP - 15620
G_COPPOOL = GP - 15640
G_WORLD = GP - 22120
ZONES = 0x0031c5c8                      # nZonePermissionTable

F_TCOP = 0x0022d3f8
F_PCOP = 0x0022d548
F_ACOP = 0x0022db20
F_NEW = 0x00230d78
F_DEL = 0x00230d68
F_SETP = 0x0022d530
F_SETDS = 0x0022d538
F_SETDSS = 0x0022d540
F_CLEARP = 0x0022e510
F_CLEARST = 0x0022e558
F_DISABLE = 0x00230ac8
F_ZINIT = 0x0022f770
F_ZREQ = 0x0022f810
F_ZGET = 0x0022f850
F_CREATE = 0x002272e8
F_MAXDIM = 0x002276a0
F_ADD = 0x00227d78
F_ISNEAR = 0x00230bf8
F_INITDT = 0x00230638
F_UPDDT = 0x002307d0

S_MALLOC = 0x002577c0
S_MALLOC2 = 0x00257690
S_DELETE = 0x00114e98
S_OMALLOC = 0x00257c80
S_SFREE = 0x00257ca0
S_CARCTOR = 0x00130a48
S_CTRLMODE = 0x00131410
S_MOVEMODE = 0x00131618
S_RESET = 0x00132eb8
S_RMCOP = 0x0022c740
S_RMSPK = 0x0022c990
S_WRECK = 0x001b5bc8
S_NEAREST = 0x001cb7a0
S_NEXT = 0x001cb960
S_GETROUTE = 0x001332a8
S_GETRP = 0x001332d8
S_DTCLEAR = 0x0021bbb0
S_ADDPT = 0x0021c2b8

VT_TCOP = 0x002bd6e8
VT_PCOP = 0x002bd6c0
VT_ACOP = 0x002bd698
KINDS = {VT_TCOP: "tcop", VT_PCOP: "player", VT_ACOP: "ai"}

# The cars, at retail's offsets.
CAR_SIZE = 2304
CAR_INDEX, CAR_TYPE, CAR_PLAYER, CAR_MODE, CAR_MOVE, CAR_CTRL = \
    8, 12, 24, 32, 36, 40
CAR_POS, CAR_RENDER, CAR_LIGHTS, CAR_SIREN, CAR_DAMAGE, CAR_VIS = \
    96, 1192, 2056, 2104, 2120, 2164
NCARS = 4
TYPE_SIZE = 576
BODY = 480
MGR_SIZE = 10516
PURSUIT_SIZE = 64
NPURSUITS = 4
CAR_DRIVER = 44
DRIVER_SIZE = 560
NQ, QPTS = 3, 40                        # the routes, and points each
Q_HDR, Q_PT = 1064, 112


def s8(v):
    v &= 0xff
    return v - 0x100 if v & 0x80 else v


def s16(v):
    v &= 0xffff
    return v - 0x10000 if v & 0x8000 else v


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def F(f):
    return "0x%08x" % fbits(f)


# ================================================================== script

def types():
    s = []
    for t, (mass, x, y, z) in enumerate(((1500.0, 0.9, 2.3, 0.7),
                                         (1.75, 1.0, 2.5, 0.75),
                                         (2210.5, 0.95, 2.45, 0.8),
                                         (3.0e-3, 1.25, 3.0, 1.1))):
        rows = [F(1000.0 * (t + 1) + 37.25 * k - (k == 5) * 12.5)
                for k in range(16)]
        s.append("type|%d|%s|%s|%s|%s|%s" % (t, F(mass), F(x), F(y), F(z),
                                             "|".join(rows)))
    return s


def fresh(diff=1, maxcops=3, direction=0):
    return ["rp|dir|%d" % direction, "rp|maxcops|%d" % maxcops,
            "world|%d" % NCARS, "mgr|%d" % diff]


def traps(recs):
    s = ["ntraps|%d" % len(recs)]
    for i, (x, y, ang, flags) in enumerate(recs):
        s.append("trap|%d|%s|%s|%d|%d" % (i, F(x), F(y), ang, flags))
    return s


def H(f):
    """A float's bits, as the hex word the route ops take."""
    return "%08x" % fbits(f)


def route_points(rnd, n, start, heading, step=10.0, wiggle=12.0):
    """n route points along a wandering line: each a TrackRoutePoint's 28
    words, Direction the unit way to the next."""
    pos = [start]
    h = heading
    for i in range(n):
        h += rnd.uniform(-wiggle, wiggle)
        d = step * rnd.uniform(0.6, 1.4)
        x, y = pos[-1]
        pos.append((x + d * math.cos(math.radians(h)),
                    y + d * math.sin(math.radians(h))))
    pts = []
    dist = rnd.uniform(0.0, 500.0)
    for i in range(n):
        (x, y), (nx, ny) = pos[i], pos[i + 1]
        ln = math.hypot(nx - x, ny - y)
        words = [H(x), H(y), H(rnd.uniform(-3.0, 3.0)), H((nx - x) / ln),
                 H((ny - y) / ln), H(ln), H(rnd.uniform(3.0, 9.0)),
                 H(rnd.uniform(3.0, 9.0)), H(rnd.uniform(-0.1, 0.1)),
                 H(rnd.uniform(-0.1, 0.1)), H(dist),
                 "%08x" % rnd.getrandbits(32)]
        dist += ln
        offs = [rnd.randrange(-32768, 32768) for _ in range(21)]
        speeds = [rnd.randrange(256) for _ in range(21)] + [rnd.randrange(256)]
        raw = struct.pack("<21h", *offs) + bytes(speeds)
        words += ["%08x" % w for w in struct.unpack("<16I", raw)]
        pts.append(words)
    return pts, pos


def drive_target_script():
    """IsNearPursuitTarget, InitializeDriveTarget and UpdateDriveTarget,
    on two AI cops (cop 0 in A1 chasing A2 through U0, cop 1 in A3)."""
    rnd = random.Random(1213)
    s = types() + fresh()
    s += ["acop|0|0|4", "acop|1|1|5", "mycar|0|1", "mycar|1|3",
          "pursuit|0|2", "setp|0|0", "pursuit|1|-1"]
    # Q0 links on to Q1; Q1 ends; Q2, route 200 (-56 as a byte), loops.
    paths = {}
    for q, (num, cnt, link, start, hd) in enumerate((
            (5, 12, 1, (0.0, 0.0), 0.0),
            (9, 30, -1, (130.0, 5.0), 10.0),
            (200, 3, 2, (-50.0, 40.0), 95.0))):
        s.append("qroute|%d|%d|%d|%d" % (q, num, cnt, link))
        pts, pos = route_points(rnd, cnt, start, hd)
        paths[q] = pos
        for i, w in enumerate(pts):
            s.append("qpt|%d|%d|%s" % (q, i, "|".join(w)))

    # ---- IsNearPursuitTarget: no pursuit, then about 20 m
    s += ["setp|0|-1", "isnear|0", "setp|0|0"]
    s.append("wpos|1|%s|%s" % (H(0.0), H(0.0)))
    for x, y in ((0.0, 0.0), (19.99, 0.0), (20.0, 0.0), (12.0, -16.0),
                 (-12.0, 16.0), (20.01, 0.0), (0.0, -19.999998),
                 (14.142135, 14.142136), (300.0, -2.0), (float("nan"), 0.0),
                 (float("inf"), 0.0), (-0.0, -0.0)):
        s += ["wpos|2|%s|%s" % (H(x), H(y)), "isnear|0"]
    s.append("wpos|1|%s|%s" % (H(5.0), H(-7.0)))
    for x, y in ((17.0, 9.0), (-7.0, -23.0), (5.0, 12.9), (24.99, -7.0),
                 (5.0, -7.0), (-7.0, 5.0), (25.0, 13.0)):
        s += ["wpos|2|%s|%s" % (H(x), H(y)), "isnear|0"]

    # ---- InitializeDriveTarget
    s.append("wpos|1|%s|%s" % (H(3.0), H(1.0)))
    s.append("wpos|2|%s|%s" % (H(40.0), H(-2.0)))
    s += ["carq|1|0|2", "carq|2|1|4", "carq|3|2|1"]
    s.append("rinfo|0|1|7")
    # Not on patrol or in pursuit: only the clear.
    for ds in (0, 1, 2, 3, 4, 7, 8, -1):
        s += ["setds|0|%d" % ds, "lss|0|9", "rinfo|0|1|7", "initdt|0"]
    # On patrol, not following an offset: straight to the racing routes.
    for lss in (0, 1, 3, 9, -1):
        s += ["setds|0|5", "lss|0|%d" % lss, "nearq|1|0|5|0|1|3",
              "initdt|0"]
    # Following an offset: the oncoming point found, across the car's own
    # route point within its width or not, left and right.
    s += ["setds|0|5", "lss|0|2"]
    for found, q, i in ((0, 1, 3), (1, 2, 0), (1, 2, 1), (1, 2, 2),
                        (1, 0, 2), (1, 0, 3), (1, 1, 0), (1, 1, 11),
                        (-1, 0, 4), (0, -1, 0), (1, 1, 29)):
        s += ["nearq|%d|%d|%d|0|0|6" % (found, q, i), "initdt|0"]
    s.append("carq|1|0|2")
    # Hot pursuit: by the sub-state.
    s += ["setds|0|6"]
    for lss in list(range(0, 14)) + [-1, 100]:
        s += ["lss|0|%d" % lss, "rinfo|0|1|7", "initdt|0"]
    # Cars with no route.
    s += ["carq|2|-1|-1", "lss|0|9", "initdt|0", "lss|0|10", "initdt|0",
          "carq|1|-1|-1", "lss|0|11", "initdt|0", "carq|2|1|4",
          "carq|1|0|2"]

    # ---- UpdateDriveTarget, keeping the route point: just the target
    s.append("dl|0|%s|%s|-1" % (H(0.0), H(0.0)))
    for line, dx, dy in ((-1, 0.0, 0.0), (-1, 1.5, -2.25), (0, 0.0, 0.0),
                         (3, -0.75, 1.0), (20, 2.0, 0.5), (7, -0.0, -0.0)):
        s.append("dl|0|%s|%s|%d" % (H(dx), H(dy), line))
        for q, i in ((0, 0), (0, 5), (0, 11), (1, 0), (1, 15), (1, 29),
                     (2, 0), (2, 2)):
            s += ["rinfo|0|%d|%d" % (q, i),
                  "upddt|0|%s|%s|1" % (H(1.0), H(2.0))]
    s.append("dl|0|%s|%s|-1" % (H(0.5), H(-1.0)))
    for keep in (2, -1):
        s += ["rinfo|0|0|3", "upddt|0|%s|%s|%d" % (H(1.0), H(2.0), keep)]
        x0, y0 = paths[1][5]
        x1, y1 = paths[1][6]
        s += ["rinfo|0|1|0", "upddt|0|%s|%s|%d" % (
            H((x0 + x1) / 2), H((y0 + y1) / 2), keep)]

    # ---- UpdateDriveTarget, moving the route point up to pos first
    s += ["setds|0|5", "lss|0|2", "nearq|1|1|0", "carq|1|0|2"]
    path = paths[1]
    for start in (0, 3, 18, 25):
        for k in range(start, min(start + 16, 30)):
            # just short of point k, on it, and just past it
            x0, y0 = path[k]
            x1, y1 = path[k + 1]
            for f in (-0.01, 0.0, 0.01, 0.5):
                px = x0 + (x1 - x0) * f
                py = y0 + (y1 - y0) * f
                s += ["rinfo|0|1|%d" % start,
                      "upddt|0|%s|%s|0" % (H(px), H(py))]
    # Past the route's end: the steps stop on the last point.
    x, y = path[30]
    s += ["rinfo|0|1|20", "upddt|0|%s|%s|0" % (H(x + 50.0), H(y))]
    # Ten steps exactly from the start: InitializeDriveTarget, once, by
    # each answer.
    for ans in ("1|1|0", "1|1|9", "1|1|10", "1|1|12", "0|1|5", "1|0|0",
                "1|2|1"):
        for k in (9, 10, 11):
            x0, y0 = path[k]
            x1, y1 = path[k + 1]
            s += ["nearq|" + ans, "rinfo|0|1|0",
                  "upddt|0|%s|%s|0" % (H((x0 + x1) / 2), H((y0 + y1) / 2))]
    # Across Q0's end into Q1, and round Q2's loop.
    p0 = paths[0]
    s += ["rinfo|0|0|8", "upddt|0|%s|%s|0" % (H(p0[11][0] + 1.0),
                                               H(p0[11][1]))]
    p2 = paths[2]
    s += ["nearq|1|2|0", "rinfo|0|2|0", "upddt|0|%s|%s|0" % (
        H(p2[3][0] + 5.0), H(p2[3][1] + 5.0))]
    # Random positions near the routes.
    for run in range(60):
        q = rnd.choice((0, 1, 1, 2))
        pth = paths[q]
        k = rnd.randrange(len(pth))
        s.append("dl|0|%s|%s|%d" % (H(rnd.uniform(-3, 3)),
                                    H(rnd.uniform(-3, 3)),
                                    rnd.choice((-1, 0, 5, 20))))
        s.append("nearq|1|%d|%d" % (q, rnd.randrange(3)))
        s.append("rinfo|0|%d|%d" % (q, rnd.randrange(max(1, k))))
        s.append("upddt|0|%s|%s|%d" % (
            H(pth[k][0] + rnd.uniform(-8, 8)),
            H(pth[k][1] + rnd.uniform(-8, 8)), rnd.choice((0, 0, 1))))

    # ---- InitializeDriveTarget's width test exactly: Q2 rebuilt, the
    # car on p0 and the oncoming point p1 across it
    def flat(i, x, y, dx, dy, lw, rw):
        w = [H(x), H(y), H(0.0), H(dx), H(dy), H(10.0), H(lw), H(rw)]
        return "qpt|2|%d|%s" % (i, "|".join(w + ["00000000"] * 20))

    s += ["setds|0|5", "lss|0|2", "carq|1|2|0", "isnear|1"]
    edge = (-6.0, -6.0000005, -5.9999995, 4.0, 4.0000005, 3.9999998, 0.0,
            -0.0, 100.0, -100.0, float("nan"))
    for ox, oy in ((0.0, 0.0), (10.0, -20.0)):
        for dx, dy in ((1.0, 0.0), (0.0, 1.0), (0.6, 0.8)):
            for lw, rw in ((4.0, 6.0), (6.0, 4.0), (-1.0, 6.0), (4.0, -1.0),
                           (0.0, 0.0)):
                s.append(flat(0, ox, oy, dx, dy, lw, rw))
                for d in edge:
                    # across the car's point: (3, d) square to x, (-d, 3)
                    # to y
                    x, y = (3.0, d) if dy == 0.0 else (-d, 3.0)
                    s += [flat(1, ox + x, oy + y, 1.0, 0.0, 5.0, 5.0),
                          "nearq|1|2|1|0|0|6", "initdt|0"]
    s.append("dump")
    return s


def script():
    s = types()
    s += ["info|0|0", "info|1|1", "info|2|2", "info|3|3", "info|-1|1"]
    s += ["wcar|0|0|%s|%s|1|2" % (F(10.0), F(20.0)),
          "wcar|1|1|%s|%s|1|0" % (F(-300.0), F(5.5)),
          "wcar|2|5|%s|%s|0|1" % (F(0.0), F(0.0)),
          "wcar|3|7|%s|%s|1|3" % (F(74.0), F(0.0))]

    # ---- the zones
    s += ["zinit", "zdump"]
    s += ["zreq|%d|%d" % (a, b) for a in range(7) for b in range(7)]
    s += ["zset|%d|%d" % (i, 100 + i) for i in range(36)]
    s += ["zreq|%d|%d" % (a, b) for a in range(7) for b in range(7)]
    s += ["zreq|6|-50", "zreq|-50|6", "zreq|6|6"]
    s += ["zinit", "zdump"]
    for st in range(-2, 17):
        for f in (-1.0, -0.0, 0.0, 1.0, -1e-30, float("nan"),
                  float("-inf"), 2.5):
            s.append("zget|%d|%s" % (st, F(f)))

    # ---- AI cops through AddCopCarToRace, at each strength
    for diff in (0, 1, 2):
        s += types() + fresh(diff=diff)
        s += ["add|0|0", "dump", "add|1|0", "add|0|0", "dump"]
        s += ["isai|0", "isai|1", "isai|2"]
        s += ["dtor|1|0", "dump", "dtor|2|3", "dump"]
    # No cops allowed: nothing happens.
    s += types() + fresh(maxcops=0) + ["add|0|0", "add|0|1", "dump"]
    s += fresh(maxcops=-1) + ["add|1|0", "dump"]
    # CreateCop and 0x002276a0 on their own; a NULL DriverInfo.
    s += types() + fresh(diff=2) + ["create|2|0", "create|-1|0", "dump",
                                    "maxdim", "dump", "create|3|0",
                                    "maxdim", "dump"]

    # ---- Be A Cop
    trapsets = [
        [],
        [(1.0, 2.0, 0, 0), (3.0, 4.0, 100, 4)],
        [(1.0, 2.0, 0, 2), (5.5, -6.25, 32000, 1), (7.0, 8.0, 5, 1)],
        [(11.0, 12.0, 31999, 3), (13.0, 14.0, 7, 1)],
        [(21.0, 22.0, 65535, 0), (23.0, 24.0, 40000, 2),
         (25.0, 26.0, 0, 3)],
        [(31.0, 32.0, 12345, 0xfffffff8), (33.0, 34.0, 1, 0)],
    ]
    for direction in (0, 1, -1, 2):
        for ts in trapsets:
            s += fresh(direction=direction) + traps(ts)
            s += ["add|-1|1", "dump", "isai|0"]
    # After two AI cops, and an AI cop after the player's.
    s += types() + fresh(diff=0) + traps(trapsets[2])
    s += ["add|0|0", "add|1|0", "add|-1|1", "dump", "isai|2", "add|2|0",
          "dump", "maxdim", "dump", "dtor|2|1", "dump", "dtor|1|1",
          "dump"]
    # The player cop as the first: 0x002276a0 reads the player's car.
    s += types() + fresh() + ["add|3|1", "dump"]

    # ---- the constructors on their own, on fresh blocks
    s += types() + fresh()
    s += ["tcop|0|5", "pcop|1|9|2", "acop|2|0|11", "acop|3|0|-4",
          "dump", "isai|1", "isai|2", "dtor|0|0", "dtor|1|0", "dtor|0|1",
          "dtor|1|1", "dump", "new", "new", "del|2", "del|3", "dump"]
    # tPlayerCop's destructor passes its flags on.
    s += ["pcop|4|3|0", "dtor|4|0", "pcop|5|-2|1", "dtor|5|1", "dump"]
    # tAICop's constructor fills the zones afresh.
    s += ["zset|4|7", "zset|35|9", "zdump", "acop|6|1|2", "zdump"]

    # ---- the setters and the two clears
    s += types() + fresh() + traps(trapsets[4])
    s += ["add|0|0", "add|1|0", "pursuit|0|0", "pursuit|1|1"]
    s += ["setp|0|0", "setds|0|7", "setdss|0|13", "setp|1|1",
          "setdss|1|-3", "dump", "clearp|0", "dump", "clearp|0",
          "setp|0|-1", "clearp|0", "dump"]
    s += ["strap|0|1", "strap|1|2", "dump", "clearst|0", "dump",
          "clearst|0", "strap|1|-1", "clearst|1", "dump"]

    # ---- DisableMyCar
    for diff in (1, 2):
        s += types() + fresh(diff=diff)
        s += ["add|0|0", "add|1|0", "add|2|0", "pursuit|0|0",
              "pursuit|1|1", "pursuit|2|2", "pursuit|3|3"]
        # Limbo and disabled do nothing.
        for st in (1, 2):
            s += ["state|0|%d" % st, "setp|0|0", "cdmg|0|1",
                  "disable|0|1", "dump"]
        for st in (0, 3, 4, 5, 6, 7, 8, -1, 9):
            s += ["state|0|%d" % st, "setds|0|0", "cdmg|0|0",
                  "setp|0|-1", "disable|0|1", "dump"]
        # A pursuit of a player's car, near and far.
        s += ["state|1|6", "cpos|1|%s|%s" % (F(10.0), F(-54.9)),
              "setp|1|0", "cdmg|1|1", "disable|1|1", "dump"]
        s += ["cpos|1|%s|%s" % (F(10.0), F(-55.0)), "setp|1|0",
              "disable|1|0", "dump"]
        s += ["cpos|1|%s|%s" % (F(10.0), F(-55.1)), "setp|1|0",
              "disable|1|1", "dump"]
        s += ["cpos|1|%s|%s" % (F(-300.0 + 52.0), F(5.5 + 53.0)),
              "setp|1|1", "disable|1|0", "dump"]
        s += ["cpos|1|%s|%s" % (F(1e30), F(0.0)), "setp|1|1",
              "disable|1|1", "dump"]
        # Not a player's: no speaker, no time.
        s += ["cpos|1|%s|%s" % (F(0.0), F(0.0)), "setp|1|2",
              "disable|1|1", "dump"]
        # The 75 m from the other side, and its edge.
        s += ["cpos|1|0|0", "setp|1|3", "disable|1|1", "dump"]
        s += ["cpos|1|%s|0" % F(-1.0), "setp|1|3", "disable|1|1", "dump"]
        s += ["cpos|1|%s|0" % F(-1.0001), "setp|1|3", "disable|1|1",
              "dump"]
        # RemovePrimarySpeaker moves the cop to another pursuit, or off.
        s += ["cpos|1|%s|%s" % (F(10.0), F(20.0)), "setp|1|0",
              "respk|2", "disable|1|1", "dump"]
        s += ["setp|1|0", "respk|1", "disable|1|1", "dump"]
        s += ["setp|1|0", "respk|-2", "state|2|5", "cpos|2|0|0",
              "setp|2|1", "disable|2|1", "dump"]

    # ---- the drive target
    s += drive_target_script()
    return s


# =================================================================== model

class Model(object):
    def __init__(self):
        e = self.e = retail_model.emu(retail=True, ieee=True)
        self.out = []
        self.names = {}
        self.kinds = {}
        self.nm = self.no = self.nk = self.nr = 0
        self.infos = {}
        self.respk = -2
        self.disabling = 0
        self.pool = e.alloc(64, align=16)
        self.names[self.pool] = "pool"
        self.player = e.alloc(16, align=16)
        self.names[self.player] = "PL"
        self.dmg = e.alloc(16, align=16)
        self.names[self.dmg] = "DMG"
        self.world = e.alloc(128, align=16)
        self.names[self.world] = "W"
        e.put32(G_WORLD, self.world)
        self.cars = [e.alloc(CAR_SIZE, align=16) for _ in range(NCARS)]
        for k, c in enumerate(self.cars):
            e.write(c, bytes(CAR_SIZE))
            self.names[c] = "A%d" % k
        self.types = [e.alloc(TYPE_SIZE, align=16) for _ in range(4)]
        for k, t in enumerate(self.types):
            e.write(t, bytes(TYPE_SIZE))
            self.names[t] = "T%d" % k
        self.dinfo = [e.alloc(16, align=16) for _ in range(4)]
        for k, d in enumerate(self.dinfo):
            self.names[d] = "D%d" % k
        self.pursuits = [e.alloc(PURSUIT_SIZE, align=16)
                         for _ in range(NPURSUITS)]
        for k, p in enumerate(self.pursuits):
            e.write(p, b"\xcd" * PURSUIT_SIZE)
            self.names[p] = "U%d" % k
        self.drivers = []
        for k, c in enumerate(self.cars):
            d = self.block(DRIVER_SIZE)
            self.names[d] = "V%d" % k
            e.put32(c + CAR_DRIVER, d)
            self.drivers.append(d)
        self.qr = []
        for k in range(NQ):
            q = self.block(Q_HDR + QPTS * Q_PT, 0)
            self.names[q] = "Q%d" % k
            self.qr.append(q)
        self.qcount = [0] * NQ
        self.qlink = [-1] * NQ
        self.car_q = [-1] * NCARS
        self.car_i = [-1] * NCARS
        self.nearq = []
        self.near_at = 0
        self.dtpos = e.alloc(16, align=16)
        self.m = 0
        for a, fn in ((S_MALLOC, self.s_malloc), (S_MALLOC2, self.s_malloc2),
                      (S_DELETE, self.s_delete), (S_OMALLOC, self.s_omalloc),
                      (S_SFREE, self.s_sfree), (S_CARCTOR, self.s_carctor),
                      (S_CTRLMODE, self.s_ctrlmode),
                      (S_MOVEMODE, self.s_movemode), (S_RESET, self.s_reset),
                      (S_RMCOP, self.s_rmcop), (S_RMSPK, self.s_rmspk),
                      (S_WRECK, self.s_wreck), (S_NEAREST, self.s_nearest),
                      (S_NEXT, self.s_next), (S_GETROUTE, self.s_getroute),
                      (S_GETRP, self.s_getrp), (S_DTCLEAR, self.s_dtclear),
                      (S_ADDPT, self.s_addpt)):
            e.stub(a, fn)
        e.put32(G_COPPOOL, self.pool)

    def emit(self, line):
        self.out.append(line)

    def sym(self, v):
        v &= M32
        if v == 0:
            return "0"
        if v == 0xcdcdcdcd:
            return "cd"
        if v in self.names:
            return self.names[v]
        for k, q in enumerate(self.qr):
            t = q + Q_HDR
            if t <= v < t + QPTS * Q_PT and (v - t) % Q_PT == 0:
                return "Q%d.p%d" % (k, (v - t) // Q_PT)
        if self.m and self.m + 8260 <= v < self.m + 8260 + 28 * 64:
            k, r = divmod(v - self.m - 8260, 28)
            if r == 0:
                return "ST%d" % k
        return "?"

    def block(self, size, fill=0xcd):
        p = self.e.alloc(size, align=16)
        self.e.write(p, bytes([fill]) * size)
        return p

    # ---- stubs

    def cstr(self, a):
        b = self.e.read(a, 64)
        return b.split(b"\0")[0].decode("latin-1")

    def s_malloc(self, em):
        size = s32(em.reg[4])
        p = self.block(size)
        n = "M%d" % self.nm
        self.nm += 1
        self.names[p] = n
        self.emit("  malloc %d %s %d %d -> %s" % (
            size, self.cstr(em.reg[5] & M32), s32(em.reg[6]),
            s32(em.reg[7]), n))
        return p

    def s_malloc2(self, em):
        size = s32(em.reg[4])
        p = self.block(size)
        n = "M%d" % self.nm
        self.nm += 1
        self.names[p] = n
        self.emit("  malloc2 %d %d -> %s" % (size, s32(em.reg[5]), n))
        return p

    def s_delete(self, em):
        self.emit("  delete %s" % self.sym(em.reg[4]))

    def s_omalloc(self, em):
        p = self.block(96)
        n = "O%d" % self.no
        self.no += 1
        self.names[p] = n
        self.emit("  omalloc %s -> %s" % (self.sym(em.reg[4]), n))
        return p

    def s_sfree(self, em):
        self.emit("  sfree %s %s" % (self.sym(em.reg[4]),
                                     self.sym(em.reg[5])))

    def s_carctor(self, em):
        e = self.e
        car, info, pos = (em.reg[i] & M32 for i in (4, 5, 6))
        x, y, z = e.u32(pos), e.u32(pos + 4), e.u32(pos + 8)
        self.emit("  carctor %s %s pos %08x %08x %08x ang %d dist %08x" % (
            self.sym(car), self.sym(info), x, y, z, em.reg[7] & 0xffff,
            em.fpr[12] & M32))
        k = self.infos.get(info, 0)
        e.put32(car + CAR_TYPE, self.types[k])
        e.put32(car + CAR_POS, x)
        e.put32(car + CAR_POS + 4, y)
        return car

    def s_ctrlmode(self, em):
        e = self.e
        car = em.reg[4] & M32
        p = self.block(76)
        n = "K%d" % self.nk
        self.nk += 1
        self.names[p] = n
        e.put32(car + CAR_MODE, em.reg[5])
        e.put32(car + CAR_CTRL, p)
        self.emit("  ctrlmode %s %d -> %s" % (self.sym(car), s32(em.reg[5]),
                                             n))

    def s_movemode(self, em):
        car = em.reg[4] & M32
        self.e.put32(car + CAR_MOVE, em.reg[5])
        self.emit("  movemode %s %d" % (self.sym(car), s32(em.reg[5])))

    def s_reset(self, em):
        e = self.e
        car, pos = em.reg[4] & M32, em.reg[5] & M32
        self.emit("  reset %s pos %08x %08x %08x speed %08x ang %d" % (
            self.sym(car), e.u32(pos), e.u32(pos + 4), e.u32(pos + 8),
            em.fpr[12] & M32, em.reg[6] & 0xffff))

    def s_rmcop(self, em):
        self.emit("  rmcop %s %s" % (self.sym(em.reg[4]),
                                     self.sym(em.reg[5])))

    def s_rmspk(self, em):
        self.emit("  rmspk %s %d" % (self.sym(em.reg[4]), s32(em.reg[5])))
        if self.respk != -2:
            self.e.put32(self.disabling,
                         self.pursuits[self.respk] if self.respk >= 0 else 0)

    def s_wreck(self, em):
        self.emit("  wreck %s" % self.sym(em.reg[4]))

    def qpoint(self, q, i):
        if q < 0 or i < 0:
            return 0
        return self.qr[q] + Q_HDR + Q_PT * i

    def s_nearest(self, em):
        e = self.e
        info, pos = em.reg[4] & M32, em.reg[5] & M32
        line = "  nearest %08x %08x %d %d %08x" % (
            e.u32(pos), e.u32(pos + 4), s32(em.reg[6]), s32(em.reg[7]),
            em.fpr[12] & M32)
        r = 0
        if self.nearq:
            a = self.nearq[min(self.near_at, len(self.nearq) - 1)]
            self.near_at += 1
            r = a[0]
            if a[1] == -1:
                e.put32(info, 0)
                e.put32(info + 4, 0)
            elif a[1] >= 0:
                e.put32(info, self.qr[a[1]])
                e.put32(info + 4, self.qpoint(a[1], a[2]))
        self.emit("%s -> %d %s %s" % (line, r, self.sym(e.u32(info)),
                                      self.sym(e.u32(info + 4))))
        return r

    def s_next(self, em):
        e = self.e
        info = em.reg[4] & M32
        route, pt = e.u32(info), e.u32(info + 4)
        line = "  next %s %s" % (self.sym(route), self.sym(pt))
        q = self.qr.index(route) if route in self.qr else NQ
        i = -1
        if q < NQ and pt:
            t = self.qr[q] + Q_HDR
            if t <= pt < t + QPTS * Q_PT and (pt - t) % Q_PT == 0:
                i = (pt - t) // Q_PT
        if q == NQ or i < 0:
            e.put32(info + 4, 0)
        elif i + 1 < self.qcount[q]:
            e.put32(info + 4, self.qpoint(q, i + 1))
        elif self.qlink[q] >= 0:
            e.put32(info, self.qr[self.qlink[q]])
            e.put32(info + 4, self.qpoint(self.qlink[q], 0))
        else:
            e.put32(info + 4, 0)
        self.emit("%s -> %s %s" % (line, self.sym(e.u32(info)),
                                   self.sym(e.u32(info + 4))))

    def car_k(self, car):
        car &= M32
        return self.cars.index(car) if car in self.cars else -1

    def s_getroute(self, em):
        k = self.car_k(em.reg[4])
        r = self.qr[self.car_q[k]] if k >= 0 and self.car_q[k] >= 0 else 0
        self.emit("  getroute %s %d -> %s" % (self.sym(em.reg[4]),
                                              s32(em.reg[5]), self.sym(r)))
        return r

    def s_getrp(self, em):
        k = self.car_k(em.reg[4])
        r = self.qpoint(self.car_q[k], self.car_i[k]) if k >= 0 else 0
        self.emit("  getrp %s %d -> %s" % (self.sym(em.reg[4]),
                                           s32(em.reg[5]), self.sym(r)))
        return r

    def s_dtclear(self, em):
        self.emit("  dtclear %s %s %08x" % (self.sym(em.reg[4]),
                                            self.sym(em.reg[5]),
                                            em.fpr[12] & M32))

    def s_addpt(self, em):
        e = self.e
        v = em.reg[5] & M32
        self.emit("  addpt %s %08x %08x %08x %d %d %d %d %s" % (
            self.sym(em.reg[4]), e.u32(v), e.u32(v + 4), e.u32(v + 8),
            s8(em.reg[6]), s16(em.reg[7]), s8(em.reg[8]), s32(em.reg[9]),
            self.sym(em.reg[10])))

    # ---- the dump

    def cop(self, k):
        return self.e.u32(self.m + 16 + 4 * k)

    def dump(self):
        e, m, o = self.e, self.m, self.emit
        w = lambda off: e.u32(m + off)                    # noqa: E731
        i = lambda off: s32(e.u32(m + off))               # noqa: E731
        o("M ai %d n %d pidx %d max %08x %08x" % (i(4), i(8), i(12),
                                                  w(10504), w(10508)))
        o("M cops %s" % " ".join(self.sym(w(16 + 4 * k)) for k in range(7)))
        o("M timers %s dmg %s" % (
            " ".join("%08x" % w(10388 + 4 * k) for k in range(8)),
            " ".join("%08x" % w(10420 + 4 * k) for k in range(2))))
        o("M traps %s" % " ".join(self.sym(w(8260 + 28 * k))
                                  for k in range(i(8256))))
        # The world's list, forward and back.
        fw, n = [], e.u32(self.world)
        while n != self.world and len(fw) < 24:
            fw.append(self.sym(n))
            n = e.u32(n)
        bw, n = [], e.u32(self.world + 4)
        while n != self.world and len(bw) < 24:
            bw.append(self.sym(n))
            n = e.u32(n + 4)
        o("W %s | %s" % (" ".join(fw), " ".join(bw)))
        for k, t in enumerate(self.types):
            o("T%d %s" % (k, " ".join("%08x" % e.u32(t + BODY + 4 * j)
                                      for j in (0, 1, 2, 3) + tuple(
                                          range(4, 20)))))
        for k in range(7):
            c = self.cop(k)
            if c:
                self.dump_cop(k, c)

    def dump_cop(self, k, c):
        e, o = self.e, self.emit
        u = lambda off: e.u32(c + off)                    # noqa: E731
        kind = self.kinds.setdefault(c, KINDS.get(u(28), "?"))
        o("C%d %s %s vt %08x pu %s car %s n %d ls %08x %08x lss %08x %08x"
          % (k, self.sym(c), kind, u(28), self.sym(u(0)), self.sym(u(4)),
             s32(u(8)), u(12), u(16), u(20), u(24)))
        if kind == "ai":
            o("C%d ai %08x st %s rb %08x sst %08x %08x %08x dl %08x %08x "
              "%08x %08x flank %08x route %s %s phys %08x delay %08x "
              "line %08x" % (k, u(32), self.sym(u(36)), u(40), u(44),
                             u(48), u(52), u(56), u(60), u(64), u(68),
                             u(72), self.sym(u(76)), self.sym(u(80)),
                             u(84), u(88), u(92)))
        elif kind == "player":
            o("C%d pl %08x %08x %08x %08x %08x" % (
                k, u(32), u(36), u(40), u(44), u(48)))
        car = u(4)
        if car and car != 0xcdcdcdcd and car not in self.cars:
            self.dump_car(k, car)

    def dump_car(self, k, car):
        e, o = self.e, self.emit
        u = lambda off: e.u32(car + off)                  # noqa: E731
        o("C%d car type %s next %s prev %s render %02x lights %08x "
          "siren %08x vis %08x dmg %s mode %08x move %08x pos %08x %08x "
          "ctrl %s" % (k, self.sym(u(CAR_TYPE)), self.sym(u(0)),
                       self.sym(u(4)), e.u8(car + CAR_RENDER),
                       u(CAR_LIGHTS), u(CAR_SIREN), u(CAR_VIS),
                       self.sym(u(CAR_DAMAGE)), u(CAR_MODE), u(CAR_MOVE),
                       u(CAR_POS), u(CAR_POS + 4), self.sym(u(CAR_CTRL))))
        d = u(CAR_CTRL)
        if d and d != 0xcdcdcdcd:
            o("C%d drv %s" % (k, " ".join("%08x" % e.u32(d + 36 + 4 * j)
                                          for j in range(10))))

    # ---- the script

    def vcall(self, c, slot, *args):
        e = self.e
        vt = e.u32(c + 28)
        delta = struct.unpack("<h", e.read(vt + slot, 2))[0]
        return e.call(e.u32(vt + slot + 4), c + delta, *args,
                      limit=200000)

    def op(self, a):
        e, o = self.e, a[0]
        v = lambda i: int(a[i], 0) & M32                  # noqa: E731

        def info(t):
            k = int(t)
            return self.dinfo[k] if k >= 0 else 0

        if o == "type":
            t = self.types[int(a[1])]
            for j in range(4):
                e.put32(t + BODY + 4 * j, int(a[2 + j], 16))
            for j in range(16):
                e.put32(t + BODY + 16 + 4 * j, int(a[6 + j], 16))
        elif o == "info":
            self.infos[info(a[1])] = int(a[2])
        elif o == "rp":
            e.put32(RP + {"dir": RP_DIR, "maxcops": RP_MAXCOPS}[a[1]], v(2))
        elif o == "world":
            w = self.world
            e.put32(w, w)
            e.put32(w + 4, w)
            for j in range(14):
                e.put32(w + 44 + 4 * j, 0)
            for j in range(int(a[1])):
                c = self.cars[j]
                tail = e.u32(w + 4)
                e.put32(tail, c)
                e.put32(w + 4, c)
                e.put32(c + 4, tail)
                e.put32(c, w)
                e.put32(w + 44 + 4 * j, c)
        elif o == "wcar":
            c = self.cars[int(a[1])]
            e.write(c + CAR_INDEX, struct.pack("<h", int(a[2])))
            e.put32(c + CAR_POS, int(a[3], 16))
            e.put32(c + CAR_POS + 4, int(a[4], 16))
            e.put32(c + CAR_PLAYER, self.player if int(a[5]) else 0)
            e.put32(c + CAR_TYPE, self.types[int(a[6])])
        elif o == "mgr":
            m = self.m = self.block(MGR_SIZE)
            self.names[m] = "MG"
            e.put32(m + 4, 0)
            e.put32(m + 8, 0)
            e.put32(m + 12, M32)
            for j in range(7):
                e.put32(m + 16 + 4 * j, 0)
            e.put32(m + 8256, 0)
            for j in range(8):
                e.put32(m + 10388 + 4 * j, 0)
            for j in range(14):
                e.put32(m + 10420 + 4 * j, 0)
            e.put32(m + 10476, v(1))
            e.put32(m + 10504, 0)
            e.put32(m + 10508, 0)
            e.put32(G_COPMGR, m)
        elif o == "ntraps":
            e.put32(self.m + 8256, v(1))
        elif o == "trap":
            t = self.m + 8260 + 28 * int(a[1])
            e.put32(t, 0)
            e.put32(t + 4, int(a[2], 16))
            e.put32(t + 8, int(a[3], 16))
            e.write(t + 12, struct.pack("<H", int(a[4]) & 0xffff))
            e.put32(t + 24, v(5))
        elif o == "add":
            e.call(F_ADD, info(a[1]), v(2), limit=2000000)
            self.emit("add %s %d" % (a[1], s32(v(2))))
        elif o == "create":
            e.call(F_CREATE, self.m, info(a[1]), v(2), limit=2000000)
            self.emit("create %s %d" % (a[1], s32(v(2))))
        elif o == "maxdim":
            e.call(F_MAXDIM, self.m)
            self.emit("maxdim")
        elif o == "dump":
            self.dump()
        elif o == "isai":
            self.emit("isai %s -> %d" % (a[1], self.vcall(self.cop(int(a[1])),
                                                         16)))
        elif o == "dtor":
            self.vcall(self.cop(int(a[1])), 8, v(2))
            self.emit("dtor %s %d" % (a[1], s32(v(2))))
        elif o in ("setp", "setds", "setdss"):
            c = self.cop(int(a[1]))
            if o == "setp":
                k = int(a[2])
                e.call(F_SETP, c, self.pursuits[k] if k >= 0 else 0)
            else:
                e.call(F_SETDS if o == "setds" else F_SETDSS, c, v(2))
            self.emit("%s %s %s" % (o, a[1], a[2]))
        elif o == "clearp":
            e.call(F_CLEARP, self.cop(int(a[1])))
            self.emit("clearp %s" % a[1])
        elif o == "clearst":
            e.call(F_CLEARST, self.cop(int(a[1])))
            self.emit("clearst %s" % a[1])
        elif o == "strap":
            c, i = self.cop(int(a[1])), int(a[2])
            if i < 0:
                e.put32(c + 36, 0)
            else:
                t = self.m + 8260 + 28 * i
                e.put32(c + 36, t)
                e.put32(t, c)
        elif o == "state":
            e.put32(self.cop(int(a[1])) + 12, v(2))
        elif o == "cpos":
            car = e.u32(self.cop(int(a[1])) + 4)
            e.put32(car + CAR_POS, v(2))
            e.put32(car + CAR_POS + 4, v(3))
        elif o == "cdmg":
            car = e.u32(self.cop(int(a[1])) + 4)
            e.put32(car + CAR_DAMAGE, self.dmg if v(2) else 0)
        elif o == "pursuit":
            k = int(a[2])
            e.put32(self.pursuits[int(a[1])] + 16,
                    self.cars[k] if k >= 0 else 0)
        elif o == "respk":
            self.respk = int(a[1])
        elif o == "disable":
            c = self.disabling = self.cop(int(a[1]))
            e.call(F_DISABLE, c, v(2), limit=200000)
            self.emit("disable %s %d" % (a[1], s32(v(2))))
        elif o == "zinit":
            e.call(F_ZINIT)
            self.emit("zinit")
        elif o == "zdump":
            self.emit("Z %s" % " ".join("%d" % s32(e.u32(ZONES + 4 * j))
                                        for j in range(36)))
        elif o == "zset":
            e.put32(ZONES + 4 * int(a[1]), v(2))
        elif o == "zreq":
            self.emit("zreq %s %s -> %d" % (a[1], a[2],
                                            e.call(F_ZREQ, v(1), v(2))))
        elif o == "zget":
            e.fpr[12] = v(2)
            self.emit("zget %s %08x -> %d" % (a[1], v(2),
                                              e.call(F_ZGET, v(1))))
        elif o in ("tcop", "pcop", "acop"):
            k = int(a[1])
            c = self.block(96)
            n = "R%d" % self.nr
            self.nr += 1
            self.names[c] = n
            if o == "tcop":
                r = e.call(F_TCOP, c, v(2))
            elif o == "pcop":
                r = e.call(F_PCOP, c, self.cars[int(a[3])], v(2))
            else:
                r = e.call(F_ACOP, c, info(a[2]), v(3), limit=2000000)
            e.put32(self.m + 16 + 4 * k, c)
            self.emit("%s %d -> %s" % (o, k, self.sym(r)))
        elif o == "qroute":
            q = int(a[1])
            e.write(self.qr[q] + 10, struct.pack("<h", int(a[2])))
            self.qcount[q] = int(a[3])
            self.qlink[q] = int(a[4])
        elif o == "qpt":
            pt = self.qpoint(int(a[1]), int(a[2]))
            for j in range(28):
                e.put32(pt + 4 * j, int(a[3 + j], 16))
        elif o == "nearq":
            self.nearq = [(int(a[1 + 3 * j]), int(a[2 + 3 * j]),
                           int(a[3 + 3 * j])) for j in range((len(a) - 1) // 3)]
            self.near_at = 0
        elif o == "carq":
            k = int(a[1])
            self.car_q[k] = int(a[2])
            self.car_i[k] = int(a[3])
        elif o == "mycar":
            k = int(a[2])
            e.put32(self.cop(int(a[1])) + 4, self.cars[k] if k >= 0 else 0)
        elif o == "dl":
            c = self.cop(int(a[1]))
            e.put32(c + 56, int(a[2], 16))
            e.put32(c + 60, int(a[3], 16))
            e.put32(c + 92, v(4))
        elif o == "rinfo":
            c, q = self.cop(int(a[1])), int(a[2])
            e.put32(c + 76, self.qr[q] if q >= 0 else 0)
            e.put32(c + 80, self.qpoint(q, int(a[3])))
        elif o == "lss":
            e.put32(self.cop(int(a[1])) + 20, v(2))
        elif o == "wpos":
            c = self.cars[int(a[1])]
            e.put32(c + CAR_POS, int(a[2], 16))
            e.put32(c + CAR_POS + 4, int(a[3], 16))
        elif o == "isnear":
            self.emit("isnear %s -> %d" % (
                a[1], e.call(F_ISNEAR, self.cop(int(a[1])))))
        elif o in ("initdt", "upddt"):
            c = self.cop(int(a[1]))
            if o == "initdt":
                e.call(F_INITDT, c, limit=200000)
            else:
                e.put32(self.dtpos, int(a[2], 16))
                e.put32(self.dtpos + 4, int(a[3], 16))
                e.call(F_UPDDT, c, self.dtpos, v(4), limit=2000000)
            line = "%s %s ri %s %s" % (o, a[1], self.sym(e.u32(c + 76)),
                                       self.sym(e.u32(c + 80)))
            car = e.u32(c + 4)
            if car:
                d = e.u32(car + CAR_DRIVER)
                line += " pt0 %08x %08x" % (e.u32(d + 16), e.u32(d + 20))
            self.emit(line)
        elif o == "new":
            self.emit("new -> %s" % self.sym(e.call(F_NEW)))
        elif o == "del":
            e.call(F_DEL, self.cop(int(a[1])))
            self.emit("del %s" % a[1])
        else:
            raise ValueError(o)

    def run(self, lines):
        for line in lines:
            self.op(line.split("|"))
        return self.out


def model(lines):
    return Model().run(lines)


# ================================================================== build

def build_harness(tmp, name="cop_test"):
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


def write_script(d, lines):
    sc = Path(d) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    return sc


# ============================================================= mutations

C, M = COP, COPMGR
MUTATIONS = [
    # ---- tCop
    ("tcop_no_number", C, "    c->nCopNumber = n;\n", ""),
    ("tcop_keeps_pursuit", C,
     "    c->pMyPursuit = NULL;\n    c->vptr = TCOP_VTABLE;\n",
     "    c->vptr = TCOP_VTABLE;\n"),
    ("tcop_no_vptr", C,
     "    c->pMyPursuit = NULL;\n    c->vptr = TCOP_VTABLE;\n",
     "    c->pMyPursuit = NULL;\n"),
    ("tcop_keeps_state", C, "    c->LogicState = LS_INVALID;\n    return c;",
     "    return c;"),
    ("tcop_clears_desired", C,
     "    c->LogicState = LS_INVALID;\n    return c;",
     "    c->LogicState = LS_INVALID;\n    c->DesiredLogicState = 0;\n"
     "    return c;"),
    ("tcop_dtor_no_vptr", C,
     "    c->vptr = TCOP_VTABLE;\n    if (flags & 1)\n        bFree(c);",
     "    if (flags & 1)\n        bFree(c);"),
    ("tcop_dtor_always_frees", C,
     "    if (flags & 1)\n        bFree(c);", "    bFree(c);"),
    ("tcop_dtor_bit1", C,
     "    if (flags & 1)\n        bFree(c);", "    if (flags & 2)\n        bFree(c);"),
    ("setp_noop", C, "    c->pMyPursuit = p;\n", ""),
    ("setds_sub", C, "    c->DesiredLogicState = s;\n",
     "    c->DesiredLogicSubState = s;\n"),
    ("setdss_state", C, "    c->DesiredLogicSubState = s;\n",
     "    c->LogicSubState = s;\n"),

    # ---- tPlayerCop
    ("pcop_no_vptr", C,
     "    c->Base.vptr = TPLAYERCOP_VTABLE;\n    c->Base.pMyCar = car;",
     "    c->Base.pMyCar = car;"),
    ("pcop_no_car", C, "    c->Base.pMyCar = car;\n    c->nPrevSelection",
     "    c->nPrevSelection"),
    ("pcop_sel0", C, "    c->nPrevSelection[0] = -1;",
     "    c->nPrevSelection[0] = 0;"),
    ("pcop_sel1", C, "    c->nPrevSelection[1] = -1;",
     "    c->nPrevSelection[1] = 1;"),
    ("pcop_timer0", C, "    c->fPrevSelectionTimer[0] = 0.0f;\n", ""),
    ("pcop_timer1", C, "    c->fPrevSelectionTimer[1] = 0.0f;\n", ""),
    ("pcop_lights", C, "    c->bPrevCopLightState = 0;\n", ""),
    ("pcop_desired", C,
     "    c->Base.DesiredLogicState = LS_INVALID;\n    return c;\n}\n\nvoid "
     "tplayercop_destruct",
     "    return c;\n}\n\nvoid tplayercop_destruct"),
    ("pcop_number", C, "    tcop_construct(&c->Base, n);\n    c->Base.vptr = "
     "TPLAYERCOP_VTABLE;",
     "    tcop_construct(&c->Base, n + 1);\n    c->Base.vptr = "
     "TPLAYERCOP_VTABLE;"),
    ("pcop_dtor_flags0", C,
     "    c->Base.vptr = TPLAYERCOP_VTABLE;\n    tcop_destruct(&c->Base, flags);",
     "    c->Base.vptr = TPLAYERCOP_VTABLE;\n    tcop_destruct(&c->Base, 0);"),

    # ---- tAICop's constructor
    ("acop_rb_index", C, "    c->nMyRoadBlockIndex = 0;\n", ""),
    ("acop_route", C,
     "    c->nMyRoadBlockIndex = 0;\n    c->RouteInfo.Route = NULL;\n",
     "    c->nMyRoadBlockIndex = 0;\n"),
    ("acop_point", C,
     "    c->RouteInfo.Point = NULL;\n    c->fSubStateTimer = 0.0f;\n",
     "    c->fSubStateTimer = 0.0f;\n"),
    ("acop_substate_timer", C, "    c->fSubStateTimer = 0.0f;\n", ""),
    ("acop_no_vptr", C,
     "    c->fSubStateTimer = 0.0f;\n    c->Base.vptr = TAICOP_VTABLE;",
     "    c->fSubStateTimer = 0.0f;"),
    ("acop_clears_trap", C, "    c->fSubStateTimer = 0.0f;\n",
     "    c->fSubStateTimer = 0.0f;\n    c->pMySpeedTrap = NULL;\n"),
    ("acop_car_pool", C,
     "\"Car (cop)\", 0, CAR_MEMORY_POOL);", "\"Car (cop)\", 0, 0);"),
    ("acop_car_angle", C, "car_construct(car, info, &origin, 0, -1.0f);",
     "car_construct(car, info, &origin, 1, -1.0f);"),
    ("acop_car_dist", C, "car_construct(car, info, &origin, 0, -1.0f);",
     "car_construct(car, info, &origin, 0, 0.0f);"),
    ("acop_no_car", C, "    c->Base.pMyCar = car;\n    scale",
     "    scale"),
    ("acop_scale_level", C,
     "fCopMassTable[pCopManager->nDifficultyLevel]", "fCopMassTable[0]"),
    ("acop_mass_table_0", C, "{ 1.5f, 1.75f, 2.0f }",
     "{ 1.25f, 1.75f, 2.0f }"),
    ("acop_mass_table_1", C, "{ 1.5f, 1.75f, 2.0f }",
     "{ 1.5f, 1.5f, 2.0f }"),
    ("acop_mass_table_2", C, "{ 1.5f, 1.75f, 2.0f }",
     "{ 1.5f, 1.75f, 2.5f }"),
    ("acop_mass_direct", C, "    type->Body.Mass = type->Body.Mass * scale;",
     "    type->Body.Mass = fCopMassTable[pCopManager->nDifficultyLevel];"),
    ("acop_mass_kept", C, "    type->Body.Mass = type->Body.Mass * scale;\n",
     ""),
    ("acop_rows_2", C, "        for (k = 0; k < 3; k++) {",
     "        for (k = 0; k < 2; k++) {"),
    ("acop_rows_4", C,
     "        bVector4 *rows[3] = { &type->Body.InertiaTensor.v0,\n"
     "                              &type->Body.InertiaTensor.v1,\n"
     "                              &type->Body.InertiaTensor.v2 };",
     "        bVector4 *rows[3] = { &type->Body.InertiaTensor.v0,\n"
     "                              &type->Body.InertiaTensor.v1,\n"
     "                              &type->Body.InertiaTensor.v3 };"),
    ("acop_no_w", C, "            rows[k]->w *= scale;\n", ""),
    ("acop_no_z", C, "            rows[k]->z *= scale;\n", ""),
    ("acop_list_head", C,
     "    tail = w->CarList.prev;\n    tail->Link.next = &car->Link;\n"
     "    w->CarList.prev = car;\n    car->Link.prev = &tail->Link;\n"
     "    car->Link.next = (CarNode *)(void *)&w->CarList;",
     "    tail = w->CarList.next;\n    w->CarList.next = car;\n"
     "    tail->Link.prev = &car->Link;\n"
     "    car->Link.next = &tail->Link;\n"
     "    car->Link.prev = (CarNode *)(void *)&w->CarList;"),
    ("acop_list_no_back", C, "    car->Link.prev = &tail->Link;\n", ""),
    ("acop_list_no_tail", C, "    w->CarList.prev = car;\n", ""),
    ("acop_ctrl_ai", C, "    car_set_control_mode(car, COP_CONTROL);",
     "    car_set_control_mode(car, AI_CONTROL);"),
    ("acop_drv_state", C, "    drv->State = eCDS_PARKED;",
     "    drv->State = eCDS_PATROLLING;"),
    ("acop_drv_no_state", C, "    drv->State = eCDS_PARKED;\n", ""),
    ("acop_drv_index", C, "    drv->nCopIndex = c->Base.nCopNumber;",
     "    drv->nCopIndex = 0;"),
    ("acop_move_physics", C, "    car_set_movement_mode(car, eNO_MOVEMENT);",
     "    car_set_movement_mode(car, COP_MOVEMENT);"),
    ("acop_rendering", C, "    car->RenderingEnabled = 0;\n", ""),
    ("acop_phys_time", C, "    c->fSecondsInPhysicsMode = 0.0f;\n", ""),
    ("acop_desired_disabled", C, "    c->Base.DesiredLogicState = LS_LIMBO;",
     "    c->Base.DesiredLogicState = LS_DISABLED;"),
    ("acop_n52", C, "    c->New48.y = 0.0f;\n", ""),
    ("acop_n48", C, "    c->New48.x = 0.0f;\n", ""),
    ("acop_dl_y", C, "    c->MyDLOffset.y = 0.0f;\n", ""),
    ("acop_dl_x", C, "    c->MyDLOffset.x = 0.0f;\n", ""),
    ("acop_flank", C, "    c->fFlankSide = 0.0f;\n", ""),
    ("acop_delay", C, "    c->fMovementModeSwitchDelay = 0.0f;\n", ""),
    ("acop_line", C, "    c->nDrivingLineIndex = 0;\n", ""),
    ("acop_n64", C, "    c->New64 = 6.0f;", "    c->New64 = 3.0f;"),
    ("acop_n68", C, "    c->New68 = 3.0f;", "    c->New68 = 6.0f;"),
    ("acop_visible", C, "    car->bVisibleOnTrackMap = 0;\n", ""),
    ("acop_siren", C, "    car->TheSirenMode = 0;\n", ""),
    ("acop_lights", C, "    car->CopLights = 0;\n", ""),
    ("acop_lights_byte", C,
     "    memset(car->_hole2025, 0, sizeof car->_hole2025);\n", ""),
    ("acop_no_zones", C,
     "    init_zone_permission_table();\n    c->New32 = 0.0f;",
     "    c->New32 = 0.0f;"),
    ("acop_grace", C, "    c->New32 = 0.0f;\n    return c;",
     "    c->New32 = 3.0f;\n    return c;"),
    ("acop_number", C, "    tcop_construct(&c->Base, n);\n    c->nMyRoadBlockIndex",
     "    tcop_construct(&c->Base, 0);\n    c->nMyRoadBlockIndex"),

    # ---- tAICop's destructor, new and delete
    ("adtor_no_vptr", C,
     "    c->Base.vptr = TAICOP_VTABLE;\n    tcop_destruct(&c->Base, 0);",
     "    tcop_destruct(&c->Base, 0);"),
    ("adtor_flags_through", C, "    tcop_destruct(&c->Base, 0);",
     "    tcop_destruct(&c->Base, flags);"),
    ("adtor_never_frees", C,
     "    if (flags & 1)\n        taicop_delete(c);", ""),
    ("adtor_always_frees", C,
     "    if (flags & 1)\n        taicop_delete(c);",
     "    taicop_delete(c);"),
    ("adtor_bfree", C, "        taicop_delete(c);", "        bFree(c);"),
    ("adel_heap", C, "    bSlotFree(CopSlotPool, p);", "    bFree(p);"),

    # ---- IsAIControlled
    ("isai_ai_0", C, "    return 1;                                   // 0x00230d60",
     "    return 0;"),
    ("isai_player_1", C, "    return 0;                                   // 0x00230d98",
     "    return 1;"),

    # ---- ClearPursuit, ClearSpeedTrap
    ("clearp_keeps", C, "        tcop_set_pursuit(&c->Base, NULL);\n", ""),
    ("clearp_no_remove", C,
     "        gPursuitRemoveCopFromPursuitFn(c->Base.pMyPursuit, &c->Base);\n",
     ""),
    ("clearst_keeps_trap", C, "        c->pMySpeedTrap->cop = NULL;\n", ""),
    ("clearst_keeps_own", C,
     "        c->pMySpeedTrap->cop = NULL;\n        c->pMySpeedTrap = NULL;",
     "        c->pMySpeedTrap->cop = NULL;"),

    # ---- DisableMyCar
    ("dis_limbo_runs", C,
     "    if (c->Base.LogicState == LS_LIMBO || c->Base.LogicState == LS_DISABLED)",
     "    if (c->Base.LogicState == LS_DISABLED)"),
    ("dis_disabled_runs", C,
     "    if (c->Base.LogicState == LS_LIMBO || c->Base.LogicState == LS_DISABLED)",
     "    if (c->Base.LogicState == LS_LIMBO)"),
    ("dis_invalid_stops", C,
     "    if (c->Base.LogicState == LS_LIMBO || c->Base.LogicState == LS_DISABLED)",
     "    if (c->Base.LogicState <= LS_DISABLED)"),
    ("dis_no_wreck", C,
     "        gCarDamageWreckFn(mine->pCarDamage);\n", ""),
    ("dis_no_pursuit_no_state", C,
     "    if (pu == NULL) {\n        tcop_set_desired_logic_state(&c->Base, LS_DISABLED);\n        return;",
     "    if (pu == NULL) {\n        return;"),
    ("dis_dist_le", C, "        if (sqrtf(dx * dx + dy * dy) < 75.0f) {",
     "        if (sqrtf(dx * dx + dy * dy) <= 75.0f) {"),
    ("dis_dist_50", C, "        if (sqrtf(dx * dx + dy * dy) < 75.0f) {",
     "        if (sqrtf(dx * dx + dy * dy) < 50.0f) {"),
    ("dis_dist_x", C, "        if (sqrtf(dx * dx + dy * dy) < 75.0f) {",
     "        if (sqrtf(dx * dx) < 75.0f) {"),
    ("dis_speaker_b", C, "            gPursuitRemovePrimarySpeakerFn(pu, b);",
     "            gPursuitRemovePrimarySpeakerFn(pu, 1);"),
    ("dis_no_reread", C,
     "            gPursuitRemovePrimarySpeakerFn(pu, b);\n            pu = c->Base.pMyPursuit;\n",
     "            gPursuitRemovePrimarySpeakerFn(pu, b);\n"),
    ("dis_speaker_any", C,
     "    if (pu->pChasedCar->pPlayer != NULL) {",
     "    if (pu->pChasedCar != NULL) {"),
    ("dis_timer_any", C,
     "        if (ch != NULL && ch->pPlayer != NULL)\n            pCopManager",
     "        if (ch != NULL)\n            pCopManager"),
    ("dis_timer_5", C, "->fSpeedTrapSpawnTimer[ch->CarIndex] += 10.0f;",
     "->fSpeedTrapSpawnTimer[ch->CarIndex] += 5.0f;"),
    ("dis_timer_set", C, "->fSpeedTrapSpawnTimer[ch->CarIndex] += 10.0f;",
     "->fSpeedTrapSpawnTimer[ch->CarIndex] = 10.0f;"),
    ("dis_timer_idx0", C, "->fSpeedTrapSpawnTimer[ch->CarIndex] += 10.0f;",
     "->fSpeedTrapSpawnTimer[0] += 10.0f;"),
    ("dis_no_clear", C,
     "    taicop_clear_pursuit(c);\n    tcop_set_desired_logic_state(&c->Base, LS_DISABLED);\n}",
     "    tcop_set_desired_logic_state(&c->Base, LS_DISABLED);\n}"),
    ("dis_state_limbo", C,
     "    taicop_clear_pursuit(c);\n    tcop_set_desired_logic_state(&c->Base, LS_DISABLED);\n}",
     "    taicop_clear_pursuit(c);\n    tcop_set_desired_logic_state(&c->Base, LS_LIMBO);\n}"),

    # ---- the zones
    ("zone_table_4", C, "        0, 0, 0, 0, 1, 0,\n", "        0, 0, 0, 0, 0, 0,\n"),
    ("zone_table_6", C, "        1, 0, 1, 0, 1, 1,\n        1, 1, 0",
     "        0, 0, 1, 0, 1, 1,\n        1, 1, 0"),
    ("zone_table_35", C, "        1, 1, 0, 1, 1, 0,\n    };",
     "        1, 1, 0, 1, 1, 1,\n    };"),
    ("zone_req_a6", C, "    if (a == 6 || b == 6)", "    if (b == 6)"),
    ("zone_req_b6", C, "    if (a == 6 || b == 6)", "    if (a == 6)"),
    ("zone_req_transposed", C, "    return nZonePermissionTable[a + b * 6];",
     "    return nZonePermissionTable[a * 6 + b];"),
    ("zone_low_speed", C, "    case LSS_LOW_SPEED_CLOSE_FOLLOW:\n        return 4;",
     "    case LSS_LOW_SPEED_CLOSE_FOLLOW:\n        return 5;"),
    ("zone_back_le", C, "        return side < 0.0f ? 3 : 5;",
     "        return side <= 0.0f ? 3 : 5;"),
    ("zone_back_swap", C, "        return side < 0.0f ? 3 : 5;",
     "        return side < 0.0f ? 5 : 3;"),
    ("zone_back_nan", C, "        return side < 0.0f ? 3 : 5;",
     "        return !(side >= 0.0f) ? 3 : 5;"),
    ("zone_block_swap", C, "        return side < 0.0f ? 1 : 2;",
     "        return side < 0.0f ? 2 : 1;"),
    ("zone_block_le", C, "        return side < 0.0f ? 1 : 2;",
     "        return side <= 0.0f ? 1 : 2;"),
    ("zone_get_ahead_6", C, "    case LSS_GET_AHEAD:\n", ""),
    ("zone_stop_6", C, "    case LSS_STOP:\n        return side", "        return side"),
    ("zone_acquire", C, "    case LSS_ACQUIRE:\n        return 0;",
     "    case LSS_ACQUIRE:\n        return 6;"),
    ("zone_flank_4", C, "    case LSS_LOW_SPEED_CLOSE_FOLLOW:\n",
     "    case LSS_FLANK:\n    case LSS_LOW_SPEED_CLOSE_FOLLOW:\n"),
    ("zone_default_0", C, "        // LSS_FLANK, LSS_BUMP, the two limbo ones, and the rest.\n        return 6;",
     "        return 0;"),

    # ---- CreateCop
    ("cc_pidx_ai_after", M, "        m->nPlayerCopIndex = m->nNumAICops;",
     "        m->nPlayerCopIndex = m->nNumAICops + 1;"),
    ("cc_player_slot_0", M,
     "        tCop       **slot = &m->Cops[m->nNumAICops];",
     "        tCop       **slot = &m->Cops[0];"),
    ("cc_player_car_1", M, "        car = pCurrentWorld->CarTable[0];",
     "        car = pCurrentWorld->CarTable[1];"),
    ("cc_player_number", M,
     "        *slot = &tplayercop_construct(pc, car, m->nPlayerCopIndex)->Base;",
     "        *slot = &tplayercop_construct(pc, car, 0)->Base;"),
    ("cc_mask_swapped", M,
     "        mask = TheRaceParameters.TrackDirection == 0 ? SPEEDTRAP_BEACOP\n"
     "                                                     : SPEEDTRAP_BEACOP_REVERSE;",
     "        mask = TheRaceParameters.TrackDirection == 0 ? SPEEDTRAP_BEACOP_REVERSE\n"
     "                                                     : SPEEDTRAP_BEACOP;"),
    ("cc_mask_dir1", M,
     "        mask = TheRaceParameters.TrackDirection == 0 ? SPEEDTRAP_BEACOP\n",
     "        mask = TheRaceParameters.TrackDirection != 1 ? SPEEDTRAP_BEACOP\n"),
    ("cc_mask_both", M, "            if (st->Flags & mask) {",
     "            if (st->Flags & 3u) {"),
    ("cc_last_trap", M, "                                      (uint16_t)(st->ang - 32000));\n"
     "                break;", "                                      (uint16_t)(st->ang - 32000));"),
    ("cc_from_1", M, "        for (i = 0; i < m->nNumSpeedTraps; i++) {",
     "        for (i = 1; i < m->nNumSpeedTraps; i++) {"),
    ("cc_angle", M, "(uint16_t)(st->ang - 32000)", "(uint16_t)(st->ang + 32768)"),
    ("cc_angle_raw", M, "(uint16_t)(st->ang - 32000)", "st->ang"),
    ("cc_speed", M, "car_reset_to_position(car, &pos, 0.0f,",
     "car_reset_to_position(car, &pos, 1.0f,"),
    ("cc_pos_xx", M, "                pos.y = st->v2Position.y;",
     "                pos.y = st->v2Position.x;"),
    ("cc_player_counts_ai", M,
     "        *slot = &taicop_construct(c, info, m->nNumAICops)->Base;\n"
     "        m->nNumAICops++;\n    }",
     "        *slot = &taicop_construct(c, info, m->nNumAICops)->Base;\n"
     "        m->nNumAICops++;\n    }\n    if (beACop != 0)\n        m->nNumAICops++;"),
    ("cc_ai_number", M,
     "        *slot = &taicop_construct(c, info, m->nNumAICops)->Base;",
     "        *slot = &taicop_construct(c, info, m->nNumCops)->Base;"),
    ("cc_ai_no_count", M, "        m->nNumAICops++;\n    }\n    m->nNumCops++;",
     "    }\n    m->nNumCops++;"),
    ("cc_no_total", M, "    }\n    m->nNumCops++;\n}", "    }\n}"),
    ("cc_player_no_total", M, "    }\n    m->nNumCops++;\n}",
     "        m->nNumCops++;\n    }\n}"),

    # ---- 0x002276a0 and AddCopCarToRace
    ("md_x_z", M, "    m->fMaxCopCarXdim = body->Xdim * 1.1f;",
     "    m->fMaxCopCarXdim = body->Zdim * 1.1f;"),
    ("md_y_x", M, "    m->fMaxCopCarYdim = body->Ydim * 1.1f;",
     "    m->fMaxCopCarYdim = body->Xdim * 1.1f;"),
    ("md_factor", M, "    m->fMaxCopCarXdim = body->Xdim * 1.1f;",
     "    m->fMaxCopCarXdim = body->Xdim * 1.2f;"),
    ("md_last_cop", M,
     "    const RigidBodyInfo *body = &m->Cops[0]->pMyCar->pCarTypeInfo->Body;",
     "    const RigidBodyInfo *body = &m->Cops[m->nNumCops - 1]->pMyCar->pCarTypeInfo->Body;"),
    ("add_ge", M, "    if (TheRaceParameters.nMaxCops > 0) {\n        copmanager_create_cop",
     "    if (TheRaceParameters.nMaxCops >= 0) {\n        copmanager_create_cop"),
    ("add_no_dims", M,
     "        copmanager_calculate_max_cop_car_dimensions(pCopManager);\n", ""),
    ("add_beacop_0", M,
     "        copmanager_create_cop(pCopManager, info, beACop);",
     "        copmanager_create_cop(pCopManager, info, 0);"),

    # ---- IsNearPursuitTarget
    ("isn_no_null", C, "    if (p == NULL)\n        return 0;\n    ch = p->pChasedCar;",
     "    ch = p->pChasedCar;"),
    ("isn_null_1", C, "    if (p == NULL)\n        return 0;\n    ch = p->pChasedCar;",
     "    if (p == NULL)\n        return 1;\n    ch = p->pChasedCar;"),
    ("isn_le", C, "    return sqrtf(dx * dx + dy * dy) < 20.0f;",
     "    return sqrtf(dx * dx + dy * dy) <= 20.0f;"),
    ("isn_dist", C, "    return sqrtf(dx * dx + dy * dy) < 20.0f;",
     "    return sqrtf(dx * dx + dy * dy) < 19.999f;"),
    ("isn_dx_y", C, "    dx = ch->State.Position.x - mine->State.Position.x;",
     "    dx = ch->State.Position.x - mine->State.Position.y;"),
    ("isn_dy_x", C, "    dy = ch->State.Position.y - mine->State.Position.y;",
     "    dy = ch->State.Position.x - mine->State.Position.y;"),
    ("isn_no_dy", C, "    return sqrtf(dx * dx + dy * dy) < 20.0f;",
     "    return sqrtf(dx * dx + dx * dy) < 20.0f;"),
    ("isn_no_sqrt", C, "    return sqrtf(dx * dx + dy * dy) < 20.0f;",
     "    return dx * dx + dy * dy < 20.0f;"),

    # ---- InitializeDriveTarget
    ("init_keep_point", C,
     "    c->RouteInfo.Point = NULL;\n    c->RouteInfo.Route = NULL;\n\n    if (c->Base.DesiredLogicState == LS_DRIVING_ON_PATROL) {",
     "    c->RouteInfo.Route = NULL;\n\n    if (c->Base.DesiredLogicState == LS_DRIVING_ON_PATROL) {"),
    ("init_keep_route", C,
     "    c->RouteInfo.Point = NULL;\n    c->RouteInfo.Route = NULL;\n\n    if (c->Base.DesiredLogicState == LS_DRIVING_ON_PATROL) {",
     "    c->RouteInfo.Point = NULL;\n\n    if (c->Base.DesiredLogicState == LS_DRIVING_ON_PATROL) {"),
    ("init_patrol_state", C,
     "    if (c->Base.DesiredLogicState == LS_DRIVING_ON_PATROL) {",
     "    if (c->Base.LogicState == LS_DRIVING_ON_PATROL) {"),
    ("init_patrol_le", C,
     "    if (c->Base.DesiredLogicState == LS_DRIVING_ON_PATROL) {",
     "    if (c->Base.DesiredLogicState <= LS_DRIVING_ON_PATROL) {"),
    ("init_follow_ne", C,
     "        if (c->Base.LogicSubState == LSS_FOLLOW_OFFSET)\n            ok =",
     "        if (c->Base.LogicSubState != LSS_FOLLOW_OFFSET)\n            ok ="),
    ("init_follow_desired", C,
     "        if (c->Base.LogicSubState == LSS_FOLLOW_OFFSET)\n            ok =",
     "        if (c->Base.DesiredLogicSubState == LSS_FOLLOW_OFFSET)\n            ok ="),
    ("init_oncoming_racing", C, "ONCOMING_TRAFFIC_ROUTES, 2, 0.0f);",
     "ALL_RACING_ROUTES, 2, 0.0f);"),
    ("init_oncoming_flags", C, "ONCOMING_TRAFFIC_ROUTES, 2, 0.0f);",
     "ONCOMING_TRAFFIC_ROUTES, 0, 0.0f);"),
    ("init_oncoming_dist", C, "ONCOMING_TRAFFIC_ROUTES, 2, 0.0f);",
     "ONCOMING_TRAFFIC_ROUTES, 2, 1.0f);"),
    ("init_rp_find", C,
     "car_get_route_point(c->Base.pMyCar, 1);\n            const TrackRoutePoint *pt",
     "car_get_route_point(c->Base.pMyCar, 0);\n            const TrackRoutePoint *pt"),
    ("init_lat_dx", C,
     "            float lat = (pt->Position.x - rp->Position.x) * rp->Direction.y",
     "            float lat = (pt->Position.x - rp->Position.x) * rp->Direction.x"),
    ("init_lat_dy", C,
     "                      - (pt->Position.y - rp->Position.y) * rp->Direction.x;",
     "                      - (pt->Position.y - rp->Position.y) * rp->Direction.y;"),
    ("init_lat_plus", C,
     "                      - (pt->Position.y - rp->Position.y) * rp->Direction.x;",
     "                      + (pt->Position.y - rp->Position.y) * rp->Direction.x;"),
    ("init_lat_px", C,
     "            float lat = (pt->Position.x - rp->Position.x) * rp->Direction.y",
     "            float lat = (pt->Position.x - rp->Position.y) * rp->Direction.y"),
    ("init_lat_le", C, "            if (lat < 0.0f) {\n                lat = -lat;",
     "            if (lat <= 0.0f) {\n                lat = -lat;"),
    ("init_lat_no_abs", C, "                lat = -lat;\n", ""),
    ("init_left_right", C, "                w = rp->LeftWidth;",
     "                w = rp->RightWidth;"),
    ("init_right_left", C, "                w = rp->RightWidth;",
     "                w = rp->LeftWidth;"),
    ("init_w_le", C, "            if (w < lat)\n                ok = 0;",
     "            if (w <= lat)\n                ok = 0;"),
    ("init_w_nan", C, "            if (w < lat)\n                ok = 0;",
     "            if (!(lat <= w))\n                ok = 0;"),
    ("init_no_return", C, "            if (ok)\n                return;\n", ""),
    ("init_no_racing", C,
     "        ai_get_nearest_route_point(&c->RouteInfo, pos, ALL_RACING_ROUTES, 2,\n                                   0.0f);\n",
     ""),
    ("init_racing_oncoming", C,
     "        ai_get_nearest_route_point(&c->RouteInfo, pos, ALL_RACING_ROUTES, 2,\n                                   0.0f);\n",
     "        ai_get_nearest_route_point(&c->RouteInfo, pos, ONCOMING_TRAFFIC_ROUTES, 2,\n                                   0.0f);\n"),
    ("init_racing_flags", C,
     "        ai_get_nearest_route_point(&c->RouteInfo, pos, ALL_RACING_ROUTES, 2,\n                                   0.0f);\n",
     "        ai_get_nearest_route_point(&c->RouteInfo, pos, ALL_RACING_ROUTES, 1,\n                                   0.0f);\n"),
    ("init_racing_dist", C,
     "        ai_get_nearest_route_point(&c->RouteInfo, pos, ALL_RACING_ROUTES, 2,\n                                   0.0f);\n",
     "        ai_get_nearest_route_point(&c->RouteInfo, pos, ALL_RACING_ROUTES, 2,\n                                   2.0f);\n"),
    ("init_hot_any", C,
     "    } else if (c->Base.DesiredLogicState == LS_HOT_PURSUIT) {\n        Car *car;",
     "    } else {\n        Car *car;"),
    ("init_hot_state", C,
     "    } else if (c->Base.DesiredLogicState == LS_HOT_PURSUIT) {\n        Car *car;",
     "    } else if (c->Base.LogicState == LS_HOT_PURSUIT) {\n        Car *car;"),
    ("init_hot_desired_sub", C, "        switch (c->Base.LogicSubState) {\n        case LSS_ACQUIRE:",
     "        switch (c->Base.DesiredLogicSubState) {\n        case LSS_ACQUIRE:"),
    ("init_no_stop", C, "        case LSS_ACQUIRE:\n        case LSS_STOP:\n",
     "        case LSS_ACQUIRE:\n"),
    ("init_no_acquire", C, "        case LSS_ACQUIRE:\n        case LSS_STOP:\n",
     "        case LSS_STOP:\n"),
    ("init_follow_too", C, "        case LSS_ACQUIRE:\n        case LSS_STOP:\n",
     "        case LSS_ACQUIRE:\n        case LSS_STOP:\n        case LSS_FOLLOW_OFFSET:\n"),
    ("init_limbo_ready", C, "        case LSS_LIMBO_DISABLED:\n",
     "        case LSS_LIMBO_DISABLED:\n        case LSS_LIMBO_READY:\n"),
    ("init_limbo_chased", C,
     "            c->RouteInfo.Route = car_get_route(c->Base.pMyCar, 1);\n            car = c->Base.pMyCar;",
     "            c->RouteInfo.Route = car_get_route(c->Base.pMyPursuit->pChasedCar, 1);\n            car = c->Base.pMyCar;"),
    ("init_limbo_point_chased", C,
     "            c->RouteInfo.Route = car_get_route(c->Base.pMyCar, 1);\n            car = c->Base.pMyCar;",
     "            c->RouteInfo.Route = car_get_route(c->Base.pMyCar, 1);\n            car = c->Base.pMyPursuit->pChasedCar;"),
    ("init_limbo_find", C,
     "            c->RouteInfo.Route = car_get_route(c->Base.pMyCar, 1);",
     "            c->RouteInfo.Route = car_get_route(c->Base.pMyCar, 0);"),
    ("init_acq_own", C,
     "            c->RouteInfo.Route = car_get_route(c->Base.pMyPursuit->pChasedCar,\n                                               1);\n            car = c->Base.pMyPursuit->pChasedCar;",
     "            c->RouteInfo.Route = car_get_route(c->Base.pMyCar,\n                                               1);\n            car = c->Base.pMyPursuit->pChasedCar;"),
    ("init_acq_point_own", C,
     "                                               1);\n            car = c->Base.pMyPursuit->pChasedCar;",
     "                                               1);\n            car = c->Base.pMyCar;"),
    ("init_acq_find", C,
     "            c->RouteInfo.Route = car_get_route(c->Base.pMyPursuit->pChasedCar,\n                                               1);",
     "            c->RouteInfo.Route = car_get_route(c->Base.pMyPursuit->pChasedCar,\n                                               0);"),
    ("init_default_own", C, "        default:\n            return;\n        }\n        c->RouteInfo.Point",
     "        default:\n            car = c->Base.pMyCar;\n            break;\n        }\n        c->RouteInfo.Point"),
    ("init_point_find", C, "        c->RouteInfo.Point = car_get_route_point(car, 1);",
     "        c->RouteInfo.Point = car_get_route_point(car, 0);"),
    ("init_no_point", C, "        c->RouteInfo.Point = car_get_route_point(car, 1);\n", ""),

    # ---- UpdateDriveTarget
    ("past_dx_y", C, "    return (pos->x - pt->Position.x) * pt->Direction.x",
     "    return (pos->x - pt->Position.x) * pt->Direction.y"),
    ("past_minus", C, "         + (pos->y - pt->Position.y) * pt->Direction.y;",
     "         - (pos->y - pt->Position.y) * pt->Direction.y;"),
    ("past_py_x", C, "         + (pos->y - pt->Position.y) * pt->Direction.y;",
     "         + (pos->y - pt->Position.x) * pt->Direction.y;"),
    ("upd_walk_keep", C, "    if (keep == 0) {\n        int32_t again = 0;",
     "    if (keep != 1) {\n        int32_t again = 0;"),
    ("upd_walk_neg", C, "    if (keep == 0) {\n        int32_t again = 0;",
     "    if (keep <= 0) {\n        int32_t again = 0;"),
    ("upd_restart_9", C, "            if (n == 10) {\n                taicop_initialize_drive_target(c);",
     "            if (n == 9) {\n                taicop_initialize_drive_target(c);"),
    ("upd_restart_ge", C, "            if (n == 10) {\n                taicop_initialize_drive_target(c);",
     "            if (n >= 10) {\n                taicop_initialize_drive_target(c);"),
    ("upd_no_restart", C, "                taicop_initialize_drive_target(c);\n", ""),
    ("upd_n_kept", C, "                again = 1;\n                n = 0;\n", "                again = 1;\n"),
    ("upd_break_again", C, "            if (n != 10 || again)\n                break;",
     "            if (n != 10 || !again)\n                break;"),
    ("upd_break_only_n", C, "            if (n != 10 || again)\n                break;",
     "            if (n != 10 || n == 10)\n                break;"),
    ("upd_first_le", C,
     "            if (0.0f < past_point(pos, c->RouteInfo.Point) && n++ < 10) {",
     "            if (0.0f <= past_point(pos, c->RouteInfo.Point) && n++ < 10) {"),
    ("upd_first_no_count", C,
     "            if (0.0f < past_point(pos, c->RouteInfo.Point) && n++ < 10) {",
     "            if (0.0f < past_point(pos, c->RouteInfo.Point) && n < 10) {"),
    ("upd_first_skip", C,
     "            if (0.0f < past_point(pos, c->RouteInfo.Point) && n++ < 10) {",
     "            if (n++ < 10) {"),
    ("upd_while_le", C,
     "                } while (0.0f < past_point(pos, c->RouteInfo.Point)\n                         && n++ < 10);",
     "                } while (0.0f <= past_point(pos, c->RouteInfo.Point)\n                         && n++ < 10);"),
    ("upd_while_9", C,
     "                } while (0.0f < past_point(pos, c->RouteInfo.Point)\n                         && n++ < 10);",
     "                } while (0.0f < past_point(pos, c->RouteInfo.Point)\n                         && n++ < 9);"),
    ("upd_while_11", C,
     "                } while (0.0f < past_point(pos, c->RouteInfo.Point)\n                         && n++ < 10);",
     "                } while (0.0f < past_point(pos, c->RouteInfo.Point)\n                         && n++ <= 10);"),
    ("upd_while_once", C,
     "                } while (0.0f < past_point(pos, c->RouteInfo.Point)\n                         && n++ < 10);",
     "                } while (0);"),
    ("upd_next_null", C,
     "                    if (info.Point != NULL)\n                        c->RouteInfo = info;",
     "                    c->RouteInfo = info;"),
    ("upd_next_point_only", C,
     "                    if (info.Point != NULL)\n                        c->RouteInfo = info;",
     "                    if (info.Point != NULL)\n                        c->RouteInfo.Point = info.Point;"),
    ("upd_clear_car", C, "    drivetarget_clear(t, NULL, 0.0f);",
     "    drivetarget_clear(t, c->Base.pMyCar, 0.0f);"),
    ("upd_clear_speed", C, "    drivetarget_clear(t, NULL, 0.0f);",
     "    drivetarget_clear(t, NULL, 1.0f);"),
    ("upd_no_clear", C, "    drivetarget_clear(t, NULL, 0.0f);\n", ""),
    ("upd_info_stale", C, "    drivetarget_clear(t, NULL, 0.0f);\n    info = c->RouteInfo;\n",
     "    drivetarget_clear(t, NULL, 0.0f);\n"),
    ("upd_19", C, "    for (i = 0; i < 20; ) {", "    for (i = 0; i < 19; ) {"),
    ("upd_21", C, "    for (i = 0; i < 20; ) {", "    for (i = 0; i <= 20; ) {"),
    ("upd_l_x", C, "        float    l = c->MyDLOffset.y;", "        float    l = c->MyDLOffset.x;"),
    ("upd_line_any", C, "        if (c->nDrivingLineIndex != -1)\n            l +=",
     "        if (c->nDrivingLineIndex > 0)\n            l +="),
    ("upd_line_sub", C, "            l += trpoint_get_driving_line_offset(info.Point,",
     "            l -= trpoint_get_driving_line_offset(info.Point,"),
    ("upd_line_none", C, "            l += trpoint_get_driving_line_offset(info.Point,",
     "            l = trpoint_get_driving_line_offset(info.Point,"),
    ("upd_pos_swap", C, "        trpoint_get_position3(info.Point, &v, c->MyDLOffset.x, l);",
     "        trpoint_get_position3(info.Point, &v, l, c->MyDLOffset.x);"),
    ("upd_pos_route_point", C, "        trpoint_get_position3(info.Point, &v, c->MyDLOffset.x, l);",
     "        trpoint_get_position3(c->RouteInfo.Point, &v, c->MyDLOffset.x, l);"),
    ("upd_route_own", C,
     "        drivetarget_add_point3(t, &v, (int8_t)info.Route->RouteNumber,",
     "        drivetarget_add_point3(t, &v, (int8_t)c->RouteInfo.Route->RouteNumber,"),
    ("upd_ptnum", C, "                                                                info.Point),",
     "                                                                info.Point) + 1,"),
    ("upd_ptnum_own", C, "                                                                info.Point),",
     "                                                                c->RouteInfo.Point),"),
    ("upd_dl_1", C, "                               0, 0, NULL);", "                               1, 0, NULL);"),
    ("upd_check_1", C, "                               0, 0, NULL);", "                               0, 1, NULL);"),
    ("upd_car", C, "                               0, 0, NULL);",
     "                               0, 0, c->Base.pMyCar);"),
    ("upd_no_next", C, "        ai_get_next_route_point(&info);\n        i++;",
     "        i++;"),
    ("upd_no_end", C, "        i++;\n        if (info.Point == NULL)\n            break;\n", "        i++;\n"),
    ("upd_pt0_keep", C, "    if (keep == 0) {\n        t->Points[0].y = pos->y;",
     "    if (keep != 1) {\n        t->Points[0].y = pos->y;"),
    ("upd_pt0_y_x", C, "        t->Points[0].y = pos->y;", "        t->Points[0].y = pos->x;"),
    ("upd_pt0_no_x", C, "        t->Points[0].x = pos->x;\n", ""),
    ("upd_pt0_no_y", C, "        t->Points[0].y = pos->y;\n", ""),
]

EQUIVALENT = {
    "adtor_no_vptr": "tCop's destructor, run straight after, stores its own "
                     "table over tAICop's",
    "upd_restart_ge": "the loop's top sees n at 0 or 10 only: it goes round "
                      "again only when n is 10",
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    lines = script()
    base = model(lines)
    indir = tempfile.TemporaryDirectory()
    scp = write_script(indir.name, lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text(encoding="latin-1").splitlines()
        if diff(base, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "cop_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs)
    indir.cleanup()
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
