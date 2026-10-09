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
           "3DS Files/source/coputil.c",
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

# tAICop::Think's, and what it reaches.
F_HST = 0x0022e1f0
F_MMT = 0x0022e578
S_RENDER = 0x001cb600                   # DriveTargetRenderer::SetTargetToRender
S_COLLON = 0x001d6f18                   # CollisionBody, collisions on
S_COLLOFF = 0x001d6f08                  # and off
S_EBRAKE = 0x0013b558                   # RealDriver::ForceEBrakeStop
S_DIST = 0x0014e3e8                     # World's 2D distance to a player
S_REPAIR = 0x001b5c20                   # CarDamage's repair
S_PTHINK = 0x0022d5c8                   # tPlayerCop::Think
S_NDSPEED = 0x00136bd8                  # NullDriver::SetDesiredSpeed

# 12g-2's: the radar trap's, roadblock's and patrol's logic, and coputil's
# two it reaches.
F_TELE = 0x0022de70
F_SETTRAP = 0x0022ded8
F_SETRB = 0x0022df18
F_VALID = 0x0022ea88
F_SEE = 0x0022ed68
F_ISTRAP = 0x0022e798
F_IROAD = 0x0022ebc0
F_STRAP = 0x0022e838
F_ROAD = 0x0022ec38
F_PATROL = 0x0022ee50
F_CANTELE = 0x00230ff0
F_CAUSED = 0x00231118
S_REQP = 0x00225078                     # tCopManager::RequestPursuit
S_GETCOL = 0x001d6f38                   # CollisionBody::GetCollision
S_TWOCAR = 0x0021eb20                   # Collision::IsTwoCarCollision
S_CARS = 0x0021eb48                     # Collision::GetCollidingCars
S_INFRONT = 0x00133898                  # Car::IsCarInFront

# 12g-3's: the chase, and what it reaches.
F_HOT = 0x0022ff58                      # DoHotPursuitLogic
F_CAUGHT = 0x002303c8                   # DoCaughtSpeederLogic
F_RTP = 0x00230cb0                      # ReturnToPatrol
F_BFS = 0x00230248                      # GetBestFlankSide
S_RANDI = 0x0014e520                    # World::Random(int)
S_RANDF = 0x0014e548                    # World::Random(float)
S_W2C = 0x001c0b18                      # CarState::WorldToCar, 2D
TPM = 0x0031bc38                        # TheTrackPathManager, TrackLength 0
RP_CS = 648                             # TheRaceParameters.CopStrength
CB_PHYSMODE, CB_IMPULSE = 112, 128      # its slots
NCOLS = 8
VT_NULLDRIVER = 0x002ae7c0
DTR = 0x00314630                        # TheDriveTargetRenderer
G_WTE = GP - 19560                      # WorldTimeElapsed
G_CAMF = GP - 21528                     # CameraFollowThisCarInstead
G_SKID = GP - 13336                     # the u16 its static initializer sets

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
PURSUIT_SIZE = 1600
NPURSUITS = 5
CAR_DRIVER = 44
DRIVER_SIZE = 560
CAR_MOVER, CAR_BODY = 48, 52
# The world cars' fields Think reads and writes, at retail's offsets: the
# `cf` op's names, each with its width (f a float, w a word, h a half, b
# a byte).
CAR_FIELDS = {
    "upz": (184, "f"), "vmag": (964, "f"), "fwd": (960, "f"),
    "vx": (112, "f"), "vy": (116, "f"), "vz": (120, "f"),
    "wx": (208, "f"), "wy": (212, "f"), "wz": (216, "f"),
    "ang": (932, "h"), "wheels": (848, "w"), "blown": (2124, "b"),
    "nblown": (2125, "b"), "rumble": (2128, "f"), "trac": (1116, "f"),
    "move": (CAR_MOVE, "w"), "mode": (CAR_MODE, "w"), "drvnum": (10, "h"),
    "idx": (CAR_INDEX, "h"), "mv": (1088, "w"), "render": (CAR_RENDER, "b"),
    "lights": (CAR_LIGHTS, "w"), "siren": (CAR_SIREN, "w"),
    "vis": (CAR_VIS, "w"), "z": (CAR_POS + 8, "f"), "dat": (2036, "f")}
DRIVER_FIELDS = {"steer": (528, "h"), "thr": (532, "f"), "brk": (536, "f"),
                 "eb": (540, "f"), "dg": (544, "w"), "sg": (548, "w")}
COP_FIELDS = {"n32": 32, "sst": 44, "phys": 84, "delay": 88, "n48x": 48,
              "n48y": 52, "dlx": 56, "dly": 60, "n64": 64, "n68": 68,
              "ls": 12, "ds": 16, "lss": 20, "dlss": 24, "rbi": 40,
              "flank": 72, "line": 92}
MOVER_AIRBORNE = 112
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


def ulps(f, n):
    """The float32 n steps on from f (back, for n below 0)."""
    b = fbits(f)
    if f < 0:
        n = -n
    return struct.unpack("<f", struct.pack("<I", b + n))[0]


NAN, INF = float("nan"), float("inf")


def prep(k=0, j=1):
    """Every field tAICop::Think reads or writes, on cop k and its car j,
    set to something to see it change."""
    s = []
    for name, val in (("upz", H(1.0)), ("vmag", H(5.0)), ("fwd", H(4.5)),
                      ("vx", H(3.0)), ("vy", H(4.0)), ("vz", H(0.5)),
                      ("wx", H(0.1)), ("wy", H(0.2)), ("wz", H(0.3)),
                      ("ang", "0"), ("wheels", "01010101"), ("blown", "0"),
                      ("nblown", "3"), ("rumble", H(0.75)),
                      ("trac", H(1.5)), ("move", "1"), ("mode", "4"),
                      ("drvnum", "7"), ("mv", "1"), ("render", "5"),
                      ("lights", "11223344"), ("siren", "9"), ("vis", "7"),
                      ("air", "0"), ("dmg", "0")):
        s.append("cf|%d|%s|%s" % (j, name, val))
    for name, val in (("steer", "1234"), ("thr", H(0.25)), ("brk", H(0.5)),
                      ("eb", H(0.125)), ("dg", "3"), ("sg", "2")):
        s.append("df|%d|%s|%s" % (j, name, val))
    s.append("kf|%d|9" % j)
    s.append("dl|%d|%s|%s|-1" % (k, H(0.0), H(0.0)))
    for name, val in (("n32", H(0.0)), ("sst", H(0.0)), ("phys", H(0.0)),
                      ("delay", H(0.0)), ("n48x", H(0.0)), ("n48y", H(0.0)),
                      ("n64", H(6.0)), ("n68", H(3.0)), ("ls", "1"),
                      ("ds", "1"), ("lss", "e"), ("dlss", "0")):
        s.append("af|%d|%s|%s" % (k, name, val))
    s += ["setp|%d|-1" % k, "strap|%d|-1" % k, "g|wte|%s" % H(1.0 / 30),
          "g|camf|ffffffff", "g|dist|%s" % H(100.0),
          "mdmg|0|%s" % H(0.125), "mdmg|1|%s" % H(0.25),
          "mdmg|3|%s" % H(0.5)]
    return s


def think_script():
    """tAICop::Think, HandleStateTransitions and MovementModeTransitions,
    on AI cop 0 in world car A1, made ready by `rig`, with routes for the
    patrol's drive target; and tPlayerCop's Think through the table."""
    rnd = random.Random(1215)
    s = types() + fresh()
    s += ["wcar|0|0|%s|%s|1|2" % (F(10.0), F(20.0)),
          "wcar|1|3|%s|%s|0|0" % (F(-30.0), F(5.5)),
          "wcar|2|5|%s|%s|0|1" % (F(0.0), F(0.0)),
          "wcar|3|7|%s|%s|1|3" % (F(74.0), F(0.0))]
    s += traps([(1.0, 2.0, 0, 0), (3.0, 4.0, 100, 4)])
    s += ["acop|0|0|4", "mycar|0|1", "rig|1", "pursuit|0|2"]
    for q, (num, cnt, link, start, hd) in enumerate((
            (5, 12, 1, (0.0, 0.0), 0.0),
            (9, 30, -1, (130.0, 5.0), 10.0),
            (200, 3, 2, (-50.0, 40.0), 95.0))):
        s.append("qroute|%d|%d|%d|%d" % (q, num, cnt, link))
        pts, _ = route_points(rnd, cnt, start, hd)
        for i, w in enumerate(pts):
            s.append("qpt|%d|%d|%s" % (q, i, "|".join(w)))
    s += ["carq|1|0|2", "nearq|1|1|0", "carq|0|0|5", "carq|2|1|3",
          "carq|3|0|7"]

    # ---- HandleStateTransitions, every way out and in
    for frm in (-1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9):
        for to in (-1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9):
            s += prep() + ["af|0|ds|%x" % (to & M32), "setp|0|0",
                           "strap|0|1", "af|0|sst|%s" % H(2.5),
                           "af|0|lss|63", "af|0|dlss|62",
                           "hst|0|%d|%d" % (frm, to), "tdump|0"]
    # A car with a damage model; a player's car; on patrol following an
    # offset.
    for frm, to in ((2, 1), (1, 5), (3, 4), (8, 8), (2, 3), (1, 7)):
        for mode, dmg in ((1, 1), (1, 0), (4, 1), (0, 0)):
            s += prep() + ["cf|1|mode|%x" % mode, "cf|1|dmg|%d" % dmg,
                           "cf|1|blown|5", "cf|1|idx|1", "af|0|ds|%d" % to,
                           "hst|0|%d|%d" % (frm, to), "tdump|0"]
    s += prep() + ["af|0|ds|5", "af|0|lss|2", "nearq|1|2|1|0|0|6",
                   "hst|0|1|5", "tdump|0", "nearq|1|1|0"]

    # ---- MovementModeTransitions
    # No movement, or DISABLED asked for: nothing.
    for move, ds in ((0, 1), (0, 2), (1, 2), (5, 2), (4, 2), (0, 5)):
        s += prep() + ["cf|1|move|%d" % move, "af|0|ds|%d" % ds,
                       "af|0|phys|%s" % H(-3.0), "cf|1|air|1",
                       "af|0|delay|%s" % H(0.05), "mmt|0", "tdump|0"]
    # Off COP_MOVEMENT: the time in physics first.
    for move in (1, 2, 3, 4, 6, 7, -1):
        for phys, wte in ((-1.0, 0.5), (-0.5, 0.5), (-0.6, 0.5),
                          (0.0, 0.0), (NAN, 0.1), (2.0, 0.1), (-INF, 1.0),
                          (-0.0, -0.0), (1.0, -1.0), (1.0, -1.5)):
            s += prep() + ["cf|1|move|%x" % (move & M32),
                           "af|0|phys|%s" % H(phys), "g|wte|%s" % H(wte),
                           "af|0|delay|%s" % H(0.05), "mmt|0", "tdump|0"]
    # The wheels on the ground.
    for wheels in ("01010101", "00010101", "01000101", "01010001",
                   "01010100", "ff010101", "80808080", "00000000",
                   "7f017f01", "000000ff"):
        for delay in (0.05, 0.5):
            s += prep() + ["cf|1|wheels|%s" % wheels,
                           "af|0|delay|%s" % H(delay), "mmt|0", "tdump|0"]
    # Skidding: the velocity's heading against the car's, past 10 degrees
    # at more than 17.88109 m/s. Each axis and a diagonal, against
    # headings around each quarter.
    skid = 17.88109
    for vx, vy in ((10.0, 0.0), (0.0, 10.0), (-10.0, 0.0), (0.0, -10.0),
                   (7.0, 7.0), (-3.0, 9.0), (0.0, 0.0)):
        for base in (0, 0x4000, 0x8000, 0xc000, 0x2000, 0xa000):
            for off in (-1822, -1821, -1820, -1819, -5, 0, 5, 1819, 1820,
                        1821, 1822, 0x7fff, 0x8000, 0x8001):
                for vmag in (skid, ulps(skid, 1)):
                    s += prep() + ["cf|1|vx|%s" % H(vx), "cf|1|vy|%s" % H(vy),
                                   "cf|1|ang|%x" % ((base + off) & 0xffff),
                                   "cf|1|vmag|%s" % H(vmag),
                                   "af|0|delay|%s" % H(0.5), "mmt|0",
                                   "tdump|0"]
    for vmag in (ulps(skid, -1), 0.0, 100.0, -100.0, NAN, INF):
        s += prep() + ["cf|1|vx|%s" % H(10.0), "cf|1|vy|%s" % H(0.0),
                       "cf|1|ang|8000", "cf|1|vmag|%s" % H(vmag),
                       "af|0|delay|%s" % H(0.5), "mmt|0", "tdump|0"]
    # Spinning: faster than a radian a second.
    for w in ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0),
              (ulps(1.0, 1), 0.0, 0.0), (0.0, 0.0, ulps(-1.0, 1)),
              (0.6, 0.8, 0.0), (0.5, 0.5, 0.70710677), (0.5, 0.5, 0.7071068),
              (0.999, 0.0, 0.0), (NAN, 0.0, 0.0), (0.0, INF, 0.0),
              (0.0, 0.0, 0.0), (-0.0, -0.0, -0.0), (1e20, 1e20, 1e20)):
        s += prep() + ["cf|1|wx|%s" % H(w[0]), "cf|1|wy|%s" % H(w[1]),
                       "cf|1|wz|%s" % H(w[2]), "af|0|delay|%s" % H(0.5),
                       "mmt|0", "tdump|0"]
    # Spins around a radian a second, each way round the sum.
    srnd = random.Random(77)
    for _ in range(120):
        v = [srnd.gauss(0.0, 1.0) for _ in range(3)]
        n = math.sqrt(sum(x * x for x in v))
        v = [x / n * srnd.choice((1.0, 1.0, ulps(1.0, 1), ulps(1.0, -1)))
             for x in v]
        s += prep() + ["cf|1|wx|%s" % H(v[0]), "cf|1|wy|%s" % H(v[1]),
                       "cf|1|wz|%s" % H(v[2]), "af|0|delay|%s" % H(0.5),
                       "mmt|0", "tdump|0"]
    # The delay's countdown, to the switch.
    for delay, wte in ((0.3, 0.1), (0.1, 0.1), (0.2, 0.1), (NAN, 0.1),
                       (0.0, 0.0), (-1.0, 0.0), (0.05, -0.1), (INF, 1.0),
                       (0.1, 0.0)):
        s += prep() + ["af|0|delay|%s" % H(delay), "g|wte|%s" % H(wte)]
        s += ["mmt|0", "tdump|0"] * 4
    # On COP_MOVEMENT: the time in physics back to 0, and an airborne car
    # dropped to MELLOW_MOVEMENT.
    for air in (0, 1, -1, 0x100):
        s += prep() + ["cf|1|move|5", "af|0|phys|%s" % H(7.5),
                       "cf|1|air|%x" % (air & M32), "mmt|0", "tdump|0"]
    for vz in (3.0, 2.0, ulps(2.0, 1), ulps(2.0, -1), 1.0, -5.0, NAN, INF,
               -INF, 0.0):
        for fwd in (4.5, -2.0):
            s += prep() + ["cf|1|move|5", "cf|1|air|1",
                           "cf|1|vz|%s" % H(vz), "cf|1|fwd|%s" % H(fwd),
                           "af|0|delay|%s" % H(0.75), "mmt|0", "tdump|0"]
    s += prep() + ["cf|1|move|5", "cf|1|air|1", "cf|1|vx|%s" % H(1e20),
                   "cf|1|vy|%s" % H(1e20), "cf|1|vz|%s" % H(1e20), "mmt|0",
                   "tdump|0"]

    # ---- Think
    # New32's countdown.
    for n32 in (1.0, 0.0, -1.0, NAN, 1e-30, 0.01, -0.0, INF):
        s += prep() + ["af|0|n32|%s" % H(n32), "g|wte|%s" % H(0.25),
                       "think|0", "tdump|0"]
    # The camera's car shows its target.
    for camf, drvnum in ((7, 7), (8, 7), (-1, -1), (-1, 7), (0x10007, 7),
                         (0xffff, -1)):
        s += prep() + ["g|camf|%x" % (camf & M32),
                       "cf|1|drvnum|%x" % (drvnum & 0xffff), "think|0",
                       "tdump|0"]
    # On its side or roof and all but stopped, or a tire blown: disabled.
    base = 10.0 / 2.237
    for st in (5, 1, 2, 6):
        for upz in (0.1, ulps(0.1, 1), ulps(0.1, -1), -1.0, NAN, 1.0, 0.0):
            for vmag in [ulps(base, n) for n in range(-3, 4)] + [0.0, NAN]:
                s += prep() + ["af|0|ls|%d" % st, "af|0|ds|%d" % st,
                               "setp|0|%d" % (0 if st == 6 else -1),
                               "cf|1|upz|%s" % H(upz),
                               "cf|1|vmag|%s" % H(vmag), "think|0",
                               "tdump|0"]
        for blown in (0, 1, 0x80, 0xff, 0x10):
            s += prep() + ["af|0|ls|%d" % st, "af|0|ds|%d" % st,
                           "setp|0|%d" % (0 if st == 6 else -1),
                           "cf|1|blown|%x" % blown, "cf|1|dmg|1", "think|0",
                           "tdump|0"]
    # In a chase of a player 42.5 m off: RemovePrimarySpeaker's flag is 1
    # when on its roof, 0 for a tire.
    s += ["pursuit|1|0"]
    for upz, blown in ((0.05, 0), (1.0, 1), (0.05, 4)):
        s += prep() + ["af|0|ls|6", "af|0|ds|6", "setp|0|1",
                       "cf|1|upz|%s" % H(upz), "cf|1|vmag|%s" % H(0.0),
                       "cf|1|blown|%x" % blown, "think|0", "tdump|0"]
    # The sub-state's timer.
    for sst in (1.0, 0.1, 0.0, NAN, -0.0, 0.25, -5.0, INF):
        for wte in (0.25, 0.0, -0.0):
            s += prep() + ["af|0|sst|%s" % H(sst), "g|wte|%s" % H(wte),
                           "af|0|lss|5", "think|0", "tdump|0"]
    # Each state, staying in it and coming into it from limbo.
    for st in (-1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9):
        for ls in (st, 1):
            s += prep() + ["af|0|ls|%x" % (ls & M32),
                           "af|0|ds|%x" % (st & M32), "setp|0|0",
                           "strap|0|0", "think|0", "tdump|0"]
    # Limbo: out of DISABLED's wait.
    for sst, lss in ((0.25, 13), (0.3, 13), (0.0, 13), (0.25, 14),
                     (0.25, 12), (NAN, 13), (-0.0, 13)):
        s += prep() + ["af|0|sst|%s" % H(sst), "af|0|lss|%x" % lss,
                       "g|wte|%s" % H(0.25), "think|0", "tdump|0"]
    # Disabled: back to limbo once 250 m from every player.
    for dist in (100.0, 249.99998, 250.0, 250.00002, NAN, INF, -1.0):
        s += prep() + ["af|0|ls|2", "af|0|ds|2", "g|dist|%s" % H(dist),
                       "think|0", "tdump|0", "think|0", "tdump|0"]
    # The offset easing to MyDLOffset.
    for dl, n48, rate, wte in (
            ((1.0, -1.0), (0.0, 0.0), (6.0, 3.0), 1.0 / 30),
            ((0.1, -0.05), (0.0, 0.0), (6.0, 3.0), 1.0 / 30),
            ((0.0, 0.0), (0.0, 0.0), (6.0, 3.0), 1.0 / 30),
            ((0.0, 0.0), (0.0, 0.0), (6.0, 3.0), 0.0),
            ((2.0, 2.0), (2.0, 2.0), (6.0, 3.0), 0.0),
            ((-0.0, 0.0), (0.0, -0.0), (6.0, 3.0), 0.5),
            ((5.0, -5.0), (-5.0, 5.0), (0.0, 0.0), 0.1),
            ((5.0, -5.0), (-5.0, 5.0), (-6.0, -3.0), 0.1),
            ((5.0, -5.0), (-5.0, 5.0), (6.0, 3.0), -0.1),
            ((1e-40, -1e-40), (0.0, 0.0), (6.0, 3.0), 0.1),
            ((NAN, INF), (0.0, 0.0), (6.0, 3.0), 0.1),
            ((3.0, 3.0), (0.0, 0.0), (3.4e38, 3.4e38), 2.0),
            ((0.0, 0.0), (0.0, 0.0), (3.4e38, 3.4e38), 2.0),
            ((0.2, 0.1), (0.0, 0.0), (6.0, 3.0), ulps(1.0 / 30, 1)),
            ((0.2, 0.1), (0.0, 0.0), (6.0, 3.0), 0.0333),
            # a step exactly the rest, against it or with it
            ((3.0, -1.5), (0.0, 0.0), (-6.0, -3.0), 0.5),
            ((3.0, -1.5), (0.0, 0.0), (6.0, 3.0), -0.5),
            ((3.0, -1.5), (0.0, 0.0), (6.0, 3.0), 0.5)):
        s += prep() + ["af|0|dlx|%s" % H(dl[0]), "af|0|dly|%s" % H(dl[1]),
                       "af|0|n48x|%s" % H(n48[0]),
                       "af|0|n48y|%s" % H(n48[1]),
                       "af|0|n64|%s" % H(rate[0]),
                       "af|0|n68|%s" % H(rate[1]), "g|wte|%s" % H(wte)]
        s += ["think|0", "tdump|0"] * 3
    # tPlayerCop's Think, through its table.
    s += ["pcop|2|3|0", "think|2"]

    # ---- a cop's life: limbo, patrol, a chase, disabled and back
    s += prep() + ["think|0", "tdump|0", "af|0|ds|5", "think|0", "tdump|0",
                   "think|0", "af|0|ds|6", "setp|0|0", "think|0", "tdump|0",
                   "cf|1|blown|1", "cf|1|dmg|1", "think|0", "tdump|0",
                   "cf|1|blown|0", "think|0", "tdump|0", "g|dist|%s" % H(300.0),
                   "think|0", "tdump|0", "think|0", "tdump|0", "af|0|ds|8",
                   "think|0", "tdump|0", "af|0|ds|7", "think|0", "tdump|0"]

    # ---- at random
    for run in range(400):
        s += prep()
        ls = rnd.choice((1, 2, 3, 4, 5, 6, 7, 8))
        ds = rnd.choice((ls, ls, rnd.choice((1, 2, 3, 4, 5, 6, 7, 8))))
        s += ["af|0|ls|%d" % ls, "af|0|ds|%d" % ds,
              "af|0|lss|%x" % rnd.choice((0, 2, 3, 13, 14, 15)),
              "cf|1|move|%d" % rnd.choice((0, 1, 4, 5, 5)),
              "cf|1|air|%d" % rnd.choice((0, 0, 1)),
              "cf|1|wheels|%s" % rnd.choice(("01010101", "01010101",
                                              "00010101")),
              "cf|1|upz|%s" % H(rnd.choice((1.0, 0.5, 0.05, -0.3))),
              "cf|1|vmag|%s" % H(rnd.uniform(0.0, 30.0)),
              "cf|1|vx|%s" % H(rnd.uniform(-30.0, 30.0)),
              "cf|1|vy|%s" % H(rnd.uniform(-30.0, 30.0)),
              "cf|1|vz|%s" % H(rnd.uniform(-3.0, 3.0)),
              "cf|1|wx|%s" % H(rnd.uniform(-1.0, 1.0)),
              "cf|1|wy|%s" % H(rnd.uniform(-1.0, 1.0)),
              "cf|1|wz|%s" % H(rnd.uniform(-1.0, 1.0)),
              "cf|1|ang|%x" % rnd.randrange(0x10000),
              "cf|1|blown|%x" % rnd.choice((0, 0, 0, 2)),
              "cf|1|mode|%d" % rnd.choice((1, 4)),
              "cf|1|dmg|%d" % rnd.choice((0, 1)),
              "af|0|n32|%s" % H(rnd.choice((0.0, rnd.uniform(-1.0, 3.0)))),
              "af|0|sst|%s" % H(rnd.choice((0.0, rnd.uniform(-1.0, 3.0)))),
              "af|0|phys|%s" % H(rnd.uniform(-1.0, 3.0)),
              "af|0|delay|%s" % H(rnd.uniform(-0.1, 0.3)),
              "af|0|dlx|%s" % H(rnd.uniform(-4.0, 4.0)),
              "af|0|dly|%s" % H(rnd.uniform(-4.0, 4.0)),
              "af|0|n48x|%s" % H(rnd.uniform(-4.0, 4.0)),
              "af|0|n48y|%s" % H(rnd.uniform(-4.0, 4.0)),
              "g|wte|%s" % H(rnd.choice((1.0 / 30, 1.0 / 60,
                                         rnd.uniform(0.0, 0.1)))),
              "g|dist|%s" % H(rnd.uniform(150.0, 350.0)),
              "g|camf|%x" % rnd.choice((7, 0xffffffff))]
        if rnd.random() < 0.3:
            s += ["setp|0|0"]
        elif 6 in (ls, ds):
            # the chase reads its pursuit unchecked
            s += ["setp|0|0"]
        s += ["strap|0|0"]
        for _ in range(rnd.randrange(1, 4)):
            s += ["think|0", "tdump|0"]
    return s


def lprep():
    """prep(), and 12g-2's world put back: the cars where they start, all
    four counted, no queued distances, no pursuits granted, no
    collisions, no pullovers, timers or player cop, nothing chased."""
    s = prep()
    for j, (x, y) in enumerate(((10.0, 20.0), (-30.0, 5.5), (0.0, 0.0),
                                (74.0, 0.0))):
        s += ["wpos|%d|%s|%s" % (j, H(x), H(y)), "cf|%d|z|%s" % (j, H(0.0)),
              "cf|%d|fwd|%s" % (j, H(4.5)), "cf|%d|vx|%s" % (j, H(3.0)),
              "cf|%d|vy|%s" % (j, H(4.0)), "cf|%d|ang|0" % j,
              "coll|%d|0" % j]
    s += ["wcount|4|4", "distq", "g|reqp|0", "front|clear", "pidx|-1",
          "plist", "prb|0|-1", "prb|1|-1", "af|0|rbi|0"]
    for j in range(8):
        s += ["pull|%d|0" % j, "ptimer|%d|0" % j]
    return s


def logic_script():
    """12g-2: Teleport, SetSpeedTrap and SetRoadBlock, IsValidPursuitTarget
    and CanPatrollerSeeThisCar, the radar trap's, roadblock's and patrol's
    logic, and coputil's CanTeleport and CarCausedRecentCollision. AI cop 0
    drives world car A1 at (-30, 5.5), as in think_script; car indices
    0, 3, 5 and 7."""
    rnd = random.Random(1222)
    s = types() + fresh()
    s += ["wcar|0|0|%s|%s|1|2" % (F(10.0), F(20.0)),
          "wcar|1|3|%s|%s|0|0" % (F(-30.0), F(5.5)),
          "wcar|2|5|%s|%s|0|1" % (F(0.0), F(0.0)),
          "wcar|3|7|%s|%s|1|3" % (F(74.0), F(0.0))]
    s += traps([(1.0, 2.0, 0, 0), (-30.0, 5.5, 100, 4),
                (-30.0, 5.5, 65436, 0), (0.0, 0.0, 0, 0)])
    s += ["acop|0|0|4", "mycar|0|1", "rig|0", "rig|1", "rig|2", "rig|3",
          "pursuit|0|2", "pursuit|1|0", "pursuit|2|1", "pursuit|3|-1"]
    for q, (num, cnt, link, start, hd) in enumerate((
            (5, 12, 1, (-40.0, 5.0), 0.0),
            (9, 30, -1, (130.0, 5.0), 10.0),
            (200, 3, 2, (-50.0, 40.0), 95.0))):
        s.append("qroute|%d|%d|%d|%d" % (q, num, cnt, link))
        pts, _ = route_points(rnd, cnt, start, hd)
        for i, w in enumerate(pts):
            s.append("qpt|%d|%d|%s" % (q, i, "|".join(w)))
    s += ["carq|1|0|2", "nearq|1|0|1", "carq|0|0|5", "carq|2|1|3",
          "carq|3|0|7"]
    s += ["rbspot|5|0|%s|%s|0" % (H(-30.0), H(5.5)),
          "rbspot|5|1|%s|%s|40000" % (H(-25.0), H(9.0)),
          "rbspot|6|0|%s|%s|65535" % (H(-30.01), H(5.5)),
          "rbspot|6|1|%s|%s|32768" % (H(1000.0), H(-1000.0))]

    # ---- Teleport, SetSpeedTrap, SetRoadBlock
    for x, y, ang in ((1.5, -2.25, 0), (-30.0, 5.5, 65535),
                      (1e10, -1e10, 32768), (NAN, -0.0, 12345)):
        s += lprep() + ["tele|0|%s|%s|%d" % (H(x), H(y), ang), "tdump|0"]
    s += lprep() + ["mycar|0|-1", "tele|0|%s|%s|7" % (H(1.0), H(2.0)),
                    "mycar|0|1"]
    for t in (0, 1, 2):
        s += lprep() + ["strap|0|-1", "settrap|0|%d" % t, "tdump|0", "dump"]
    for r, k, i in ((5, 0, 0), (5, 1, 1), (6, -1, 1), (6, 3, 0)):
        s += lprep() + ["setp|0|-1", "setrb|0|%d|%d|%d" % (r, k, i),
                        "tdump|0"]

    # ---- IsValidPursuitTarget
    base = 80.0 / 2.237
    for j in range(4):
        for b in (0, 1, 2, -1):
            for fwd in (0.0, base, ulps(base, 1), ulps(base, -1), -base,
                        -ulps(base, 1), 100.0, -100.0, NAN, 1e20):
                s += lprep() + ["cf|%d|fwd|%s" % (j, H(fwd)),
                                "valid|0|%d|%d" % (j, b)]
        # Pulled over, or its pursuable timer running.
        idx = (0, 3, 5, 7)[j]
        for pull in (1, 0x100, -1):
            s += lprep() + ["pull|%d|%d" % (idx, pull & M32),
                            "cf|%d|fwd|%s" % (j, H(100.0)),
                            "valid|0|%d|1" % j]
        for t in (1.0, 1e-30, 0.0, -0.0, -1.0, NAN, INF):
            s += lprep() + ["ptimer|%d|%s" % (idx, H(t)),
                            "cf|%d|fwd|%s" % (j, H(100.0)),
                            "valid|0|%d|1" % j]
        # Chased already.
        for pl in (["plist|0"], ["plist|1"], ["plist|0|1|2"],
                   ["plist|3|2"], ["plist|1|3"]):
            for b in (0, 1):
                s += lprep() + pl + ["cf|%d|fwd|%s" % (j, H(1.0)),
                                     "valid|0|%d|%d" % (j, b)]
    # The player cop's own car, and no cop at its index.
    s += lprep() + ["pcop|2|9|0"]
    for pidx in (2, 5, -1, 0):
        for j in (0, 1):
            s += ["pidx|%d" % pidx, "cf|%d|fwd|%s" % (j, H(100.0)),
                  "valid|0|%d|1" % j]
    s += ["dtor|2|0"]
    s += lprep() + ["pcop|2|9|0", "mycar|2|-1", "pidx|2", "valid|0|1|1",
                    "valid|0|0|1", "dtor|2|0"]
    # A collision it caused: yes at once, past the pullover tests.
    s += lprep() + ["coll|0|1|1:0:2", "cf|2|fwd|%s" % H(0.0),
                    "cf|0|fwd|%s" % H(0.0), "valid|0|0|0", "valid|0|0|1",
                    "pull|0|1", "valid|0|0|1"]

    # ---- CarCausedRecentCollision
    colls = [
        ["0"], ["1", "0:1:2"], ["1", "1:1:2"], ["1", "1:2:1"],
        ["1", "1:1:-1"], ["1", "1:-1:1"], ["1", "1:1:1"],
        ["2", "1:1:-1", "1:1:2"], ["3", "0:1:2", "1:1:2", "1:3:1"],
        ["2", "1:1:3", "1:1:2", "1:1:0"], ["-1", "1:1:2"],
        ["8"] + ["1:1:%d" % (k % 4) for k in range(8)],
        ["4", "1:0:1", "0:1:3", "1:1:3", "1:2:1"]]
    for c in colls:
        for o_fwd, my_fwd, front in ((0.0, 4.5, 0), (-0.0, 4.5, 0),
                                     (3.0, 4.5, 1), (3.0, 4.5, 0),
                                     (4.5, 4.5, 1), (ulps(4.5, -1), 4.5, 1),
                                     (-1.0, 4.5, 1), (NAN, 4.5, 1),
                                     (3.0, NAN, 1), (1e-30, 0.0, 1),
                                     (-1e-30, 4.5, 1)):
            s += lprep() + ["coll|1|%s" % "|".join(c)]
            for k in (0, 2, 3):
                s += ["cf|%d|fwd|%s" % (k, H(o_fwd)),
                      "front|1|%d|%d" % (k, front)]
            s += ["cf|1|fwd|%s" % H(my_fwd), "caused|1"]
    # Ahead, but only one of them.
    s += lprep() + ["coll|1|3|1:1:0|1:1:2|1:3:1", "cf|0|fwd|%s" % H(3.0),
                    "cf|2|fwd|%s" % H(3.0), "cf|3|fwd|%s" % H(3.0),
                    "front|1|3|1", "caused|1", "front|1|2|1", "caused|1",
                    "front|1|0|1", "caused|1", "caused|0", "caused|2"]

    # ---- CanPatrollerSeeThisCar: car A2 off cop car A1 at (-30, 5.5)
    for dx, dy in ((20.0, 0.0), (ulps(20.0, -1), 0.0), (ulps(20.0, 1), 0.0),
                   (49.99, 0.0), (50.0, 0.0), (ulps(50.0, -1), 0.0),
                   (-20.0, 0.0), (0.0, 0.0), (12.0, 16.0), (16.0, 12.0),
                   (35.0, 35.0), (35.4, 35.4), (-30.0, 30.0), (0.0, 25.0),
                   (NAN, 0.0)):
        for vx, vy in ((1.0, 0.0), (0.0, 0.0), (-1.0, 0.0), (0.6, 0.8),
                       (0.8, 0.6), (30.0, 40.0), (0.0, 1.0), (NAN, 1.0),
                       (1e18, 1e18), (-0.0, -0.0), (3.0, -4.0)):
            s += lprep() + ["wpos|2|%s|%s" % (H(-30.0 + dx), H(5.5 + dy)),
                            "cf|2|vx|%s" % H(vx), "cf|2|vy|%s" % H(vy),
                            "see|0|2"]

    # ---- CanTeleport, car A1 to a spot: both players far, and no car
    # within 15 m of it (itself not counted)
    for dq in ((300.0, 300.0), (100.0, 300.0), (300.0, 100.0),
               (250.0, 250.0), (ulps(250.0, -1), 300.0),
               (300.0, ulps(250.0, -1)), (NAN, NAN), (INF, 300.0)):
        s += lprep() + ["distq|%s|%s" % (H(dq[0]), H(dq[1])),
                        "canteleport|1|%s|%s" % (H(1.0), H(2.0))]
    for x, y in ((-15.0, 5.5), (-15.01, 5.5), (ulps(-15.0, 1), 5.5),
                 (-30.0, 20.5), (-30.0, 20.6), (-39.0, 17.5),
                 (-41.0, 16.5)):
        for total in (0, 1, 2, 3, 4, -1):
            s += lprep() + ["wpos|2|%s|%s" % (H(x), H(y)),
                            "wcount|%d|4" % total,
                            "distq|%s|%s" % (H(300.0), H(300.0)),
                            "canteleport|1|%s|%s" % (H(-15.0), H(5.5))]
    s += lprep() + ["wpos|0|%s|%s" % (H(-30.0), H(5.5)),
                    "distq|%s|%s" % (H(300.0), H(300.0)),
                    "canteleport|1|%s|%s" % (H(0.0), H(0.0))]

    # ---- InitSpeedTrapLogic and InitRoadBlockLogic
    for op in ("listrap", "liroad"):
        for pu in (-1, 0):
            s += lprep() + ["setp|0|%d" % pu, "af|0|lss|5",
                            "af|0|sst|%s" % H(2.5), "%s|0" % op, "tdump|0"]

    # ---- DoSpeedTrapLogic
    # The timer and the players: no distance asked while it runs.
    for sst in (1.0, 0.0, -0.0, -1.0, NAN, 1e-30):
        for dist in (100.0, 250.0, ulps(250.0, -1), NAN, 300.0):
            s += lprep() + ["strap|0|1", "af|0|ls|3", "af|0|ds|3",
                            "af|0|sst|%s" % H(sst), "g|dist|%s" % H(dist),
                            "lstrap|0", "tdump|0"]
    # Off its spot: 1 cm, 100 BAM, and CanTeleport's answer.
    for dx, ang in ((0.0, 0), (0.01, 0), (ulps(0.01, 1), 0),
                    (ulps(0.01, -1), 0), (-0.01, 0), (-0.0101, 0),
                    (0.0, 100), (0.0, 0xffff), (0.0, 65535 - 100),
                    (0.0, 0x8000), (0.0, 0x7fff), (5.0, 50), (0.0, 150),
                    (0.0, 50), (NAN, 0)):
        for t in (1, 2):
            for dq in ((300.0, 300.0), (300.0, 10.0)):
                s += lprep() + ["strap|0|%d" % t, "af|0|ls|3",
                                "af|0|ds|3", "af|0|sst|%s" % H(1.0),
                                "wpos|1|%s|%s" % (H(-30.0 + dx), H(5.5)),
                                "cf|1|ang|%x" % ang,
                                "distq|%s|%s" % (H(dq[0]), H(dq[1])),
                                "lstrap|0", "tdump|0"]
    s += lprep() + ["strap|0|0", "af|0|sst|%s" % H(1.0),
                    "distq|%s|%s" % (H(300.0), H(300.0)), "lstrap|0",
                    "tdump|0"]
    # Exactly 1 cm off trap 3 at the origin, and either side.
    for x in (0.01, -0.01, ulps(0.01, 1), ulps(0.01, -1), 0.0):
        for y in (0.0, 0.01):
            s += lprep() + ["strap|0|3", "af|0|sst|%s" % H(1.0),
                            "wpos|1|%s|%s" % (H(x), H(y)),
                            "distq|%s|%s" % (H(300.0), H(300.0)),
                            "lstrap|0", "tdump|0"]
    # The search: 45 m in x and y, 2.5 m in z, the target test and the
    # manager's answer.
    for x, y, z in ((-10.0, 5.5, 0.0), (15.0, 5.5, 0.0),
                    (ulps(15.0, -1), 5.5, 0.0), (-30.0, 50.5, 0.0),
                    (-30.0, 50.4, 0.0), (-10.0, 5.5, 2.5),
                    (-10.0, 5.5, ulps(2.5, -1)), (-10.0, 5.5, -2.4),
                    (-10.0, 5.5, -3.0), (-10.0, 5.5, NAN),
                    (NAN, 5.5, 0.0)):
        for fwd in (100.0, 1.0):
            for reqp in (0, 1):
                s += lprep() + ["strap|0|1", "af|0|ls|3", "af|0|ds|3",
                                "af|0|sst|%s" % H(1.0), "cf|1|ang|64",
                                "wpos|2|%s|%s" % (H(x), H(y)),
                                "cf|2|z|%s" % H(z),
                                "cf|2|fwd|%s" % H(fwd),
                                "g|reqp|%d" % reqp, "lstrap|0", "tdump|0"]
    # The count, read once; its own car is in the table too.
    for coppos in (0, 1, 2, 3, 4, -1):
        s += lprep() + ["strap|0|1", "af|0|ls|3", "af|0|ds|3",
                        "af|0|sst|%s" % H(1.0), "cf|1|ang|64",
                        "wpos|0|%s|%s" % (H(-20.0), H(5.5)),
                        "wpos|2|%s|%s" % (H(-10.0), H(5.5)),
                        "wpos|3|%s|%s" % (H(-30.0), H(6.0)),
                        "cf|0|fwd|%s" % H(100.0), "cf|1|fwd|%s" % H(100.0),
                        "cf|2|fwd|%s" % H(100.0), "cf|3|fwd|%s" % H(100.0),
                        "wcount|4|%d" % coppos, "g|reqp|1",
                        "lstrap|0", "tdump|0"]

    # ---- DoRoadBlockLogic
    for pu, rb in ((-1, -1), (0, -1), (0, 5), (1, 6), (2, 5)):
        for rbi in (0, 1):
            for dx, ang in ((0.0, 0), (0.02, 0), (0.0, 0x9c40),
                            (5.0, 0x9c40), (-0.01, 0xffff)):
                for dq in ((300.0, 300.0), (10.0, 300.0)):
                    s += lprep() + ["setp|0|%d" % pu, "prb|0|5",
                                    "prb|1|6", "prb|2|-1",
                                    "prb|%d|%d" % (max(pu, 0), rb),
                                    "af|0|rbi|%d" % rbi, "af|0|ls|4",
                                    "af|0|ds|4", "af|0|n32|%s" % H(0.5),
                                    "wpos|1|%s|%s" % (H(-30.0 + dx),
                                                      H(5.5)),
                                    "cf|1|ang|%x" % ang,
                                    "distq|%s|%s" % (H(dq[0]), H(dq[1])),
                                    "lroad|0", "tdump|0"]

    # ---- DoDrivingOnPatrolLogic
    for dist in (100.0, ulps(250.0, -1), 250.0, NAN):
        s += lprep() + ["af|0|ds|5", "af|0|dlx|%s" % H(1.5),
                        "af|0|dly|%s" % H(-2.5),
                        "af|0|n48x|%s" % H(0.75), "af|0|n48y|%s" % H(-1.0),
                        "rinfo|0|0|1", "nearq|1|0|1",
                        "g|dist|%s" % H(dist), "lpatrol|0", "tdump|0"]
    # Who it sees: ahead and going away, or not; fast or slow.
    for x, y, vx, vy, fwd in ((-5.0, 5.5, 1.0, 0.0, 1.0),
                              (-5.0, 5.5, -1.0, 0.0, 1.0),
                              (-5.0, 5.5, 1.0, 0.0, 100.0),
                              (-5.0, 5.5, -1.0, 0.0, 100.0),
                              (-15.0, 5.5, 1.0, 0.0, 1.0),
                              (-50.0, 5.5, -1.0, 0.0, 1.0),
                              (-30.0, 30.0, 0.0, 1.0, 1.0),
                              (-30.0, 30.0, 0.0, 0.0, 1.0)):
        for reqp in (0, 1):
            for pl in ([], ["plist|1"]):
                s += lprep() + pl + ["rinfo|0|0|1", "nearq|1|0|1",
                                     "pursuit|1|2",
                                     "wpos|2|%s|%s" % (H(x), H(y)),
                                     "cf|2|vx|%s" % H(vx),
                                     "cf|2|vy|%s" % H(vy),
                                     "cf|2|fwd|%s" % H(fwd),
                                     "g|reqp|%d" % reqp, "lpatrol|0",
                                     "tdump|0", "pursuit|1|0"]

    # ---- through Think: into each and on
    for st, extra in ((3, ["strap|0|1"]), (4, ["setp|0|0", "prb|0|5"]),
                      (5, ["rinfo|0|0|1", "nearq|1|0|1"])):
        for ls in (1, st):
            s += lprep() + extra + ["af|0|ls|%d" % ls, "af|0|ds|%d" % st,
                                    "g|reqp|1", "cf|2|fwd|%s" % H(100.0),
                                    "wpos|2|%s|%s" % (H(-10.0), H(5.5)),
                                    "think|0", "tdump|0", "think|0",
                                    "tdump|0"]

    # ---- at random
    for run in range(300):
        s += lprep()
        st = rnd.choice((3, 4, 5))
        s += ["af|0|ls|%d" % rnd.choice((st, st, 1)), "af|0|ds|%d" % st,
              "strap|0|%d" % rnd.choice((0, 1, 2)),
              "setp|0|%d" % rnd.choice((-1, 0, 1, 2)),
              "prb|0|%d" % rnd.choice((-1, 5, 6)),
              "prb|1|%d" % rnd.choice((-1, 5, 6)),
              "prb|2|%d" % rnd.choice((-1, 5, 6)),
              "af|0|rbi|%d" % rnd.choice((0, 1)),
              "rinfo|0|0|%d" % rnd.randrange(4), "nearq|1|0|1",
              "af|0|sst|%s" % H(rnd.choice((0.0, rnd.uniform(-1.0, 3.0)))),
              "g|dist|%s" % H(rnd.uniform(150.0, 350.0)),
              "g|reqp|%d" % rnd.choice((0, 1)),
              "cf|1|ang|%x" % rnd.choice((0, 64, 100, 0x9c40, 0xffff,
                                          rnd.randrange(0x10000))),
              "wpos|1|%s|%s" % (H(rnd.choice((-30.0, -25.0,
                                              rnd.uniform(-40.0, -20.0)))),
                                H(rnd.choice((5.5, 9.0,
                                              rnd.uniform(0.0, 10.0)))))]
        if rnd.random() < 0.5:
            s += ["distq|%s|%s" % (H(rnd.choice((300.0, 100.0))),
                                   H(rnd.choice((300.0, 100.0))))]
        for j in (0, 2, 3):
            s += ["wpos|%d|%s|%s" % (j, H(rnd.uniform(-80.0, 20.0)),
                                     H(rnd.uniform(-20.0, 30.0))),
                  "cf|%d|z|%s" % (j, H(rnd.choice((0.0, 1.0, 3.0)))),
                  "cf|%d|fwd|%s" % (j, H(rnd.choice((1.0, 40.0, -40.0)))),
                  "cf|%d|vx|%s" % (j, H(rnd.uniform(-30.0, 30.0))),
                  "cf|%d|vy|%s" % (j, H(rnd.uniform(-30.0, 30.0)))]
        if rnd.random() < 0.3:
            s += ["plist|%d" % rnd.choice((0, 1, 2))]
        if rnd.random() < 0.3:
            k = rnd.choice((0, 2, 3))
            s += ["coll|%d|1|1:%d:%d" % (k, k, rnd.choice((0, 1, 2, 3))),
                  "front|%d|%d|1" % (k, rnd.choice((0, 1, 2, 3)))]
        if rnd.random() < 0.2:
            s += ["ptimer|%d|%s" % (rnd.choice((0, 5, 7)), H(1.0))]
        for _ in range(rnd.randrange(1, 4)):
            s += ["think|0", "tdump|0"]
    return s


def chase_pt(i, x, y, dx, dy, lw, rw):
    """Route Q2's point i, the chased cars': at (x, y), on the way
    (dx, dy), lw wide to the left and rw to the right."""
    w = [H(x), H(y), H(0.0), H(dx), H(dy), H(10.0), H(lw), H(rw)]
    return "qpt|2|%d|%s" % (i, "|".join(w + ["00000000"] * 20))


def cprep(ls=6, lss=3, dlss=None):
    """lprep(), and the chase's world put back: cop 0 in state `ls`
    chasing A2 -- at the origin, nobody's -- in U0 as its primary; cop 1
    an AI cop in A3 following on the right, and cop 2 the player's,
    neither in the chase; nothing drawn, no track length, every car level
    round the track, at 5 m/s by its VelocityMagnitude and moving;
    CopStrength 0, level 1, no behaviour bits; and A2's route point under
    it, along x and 5 m wide each side."""
    s = lprep()
    s += ["wcar|2|5|%s|%s|0|1" % (H(0.0), H(0.0)), "randi", "randf", "w2c",
          "tlen|0", "rp|cs|0", "mdiff|1", "pursuit|0|2", "pcops|0|0|-1",
          "pflags|0|0", "setp|0|0", "af|0|ls|%x" % (ls & M32),
          "af|0|ds|%x" % (ls & M32), "af|0|lss|%x" % (lss & M32),
          "af|0|dlss|%x" % ((lss if dlss is None else dlss) & M32),
          "af|0|flank|%s" % H(0.0), "mycar|1|3", "af|1|lss|3",
          "af|1|flank|%s" % H(1.0), "lss|2|0",
          chase_pt(0, 0.0, 0.0, 1.0, 0.0, 5.0, 5.0)]
    for j in range(4):
        s += ["cf|%d|dat|%s" % (j, H(0.0)), "cf|%d|vmag|%s" % (j, H(5.0)),
              "cf|%d|move|1" % j]
    return s


def b2f(b):
    return struct.unpack("<f", struct.pack("<I", b))[0]


def chase_script():
    """12g-3: the chase -- ReturnToPatrol, GetBestFlankSide, the hot
    pursuit logic's way in and each of its ten sub-logics, the caught
    speeder logic, and both through Think. Cop 0 drives A1, as in
    logic_script; the chased car is A2 at the origin, and cop 0's car is
    moved round it. Cop 1 is an AI cop in A3 and cop 2 a player's cop in
    A0, each the chase's other cop when put in U0's Cops."""
    rnd = random.Random(1233)
    s = types() + fresh()
    s += ["wcar|0|0|%s|%s|1|2" % (F(10.0), F(20.0)),
          "wcar|1|3|%s|%s|0|0" % (F(-30.0), F(5.5)),
          "wcar|2|5|%s|%s|0|1" % (F(0.0), F(0.0)),
          "wcar|3|7|%s|%s|1|3" % (F(74.0), F(0.0))]
    s += traps([(1.0, 2.0, 0, 0), (-30.0, 5.5, 100, 4)])
    s += ["acop|0|0|4", "mycar|0|1", "rig|0", "rig|1", "rig|2", "rig|3",
          "acop|1|0|5", "mycar|1|3", "pcop|2|9|0", "pursuit|1|0",
          "pursuit|2|1", "pursuit|3|-1", "pursuit|4|-1"]
    for q, (num, cnt, link, start, hd) in enumerate((
            (5, 12, 1, (-40.0, 5.0), 0.0),
            (9, 30, -1, (130.0, 5.0), 10.0))):
        s.append("qroute|%d|%d|%d|%d" % (q, num, cnt, link))
        pts, _ = route_points(rnd, cnt, start, hd)
        for i, w in enumerate(pts):
            s.append("qpt|%d|%d|%s" % (q, i, "|".join(w)))
    s += ["qroute|2|200|4|-1",
          chase_pt(1, 10.0, 20.0, 0.0, 1.0, 4.0, 6.0),
          chase_pt(2, -30.0, 5.5, 1.0, 0.0, 5.0, 5.0),
          chase_pt(3, 74.0, 0.0, -1.0, 0.0, 6.0, 4.0),
          "carq|0|2|1", "carq|1|0|2", "carq|2|2|0", "carq|3|2|3",
          "nearq|1|0|1"]
    mph20 = 20.0 / 2.237
    mph5 = 5.0 / 2.237

    def cop_at(x, y):
        return "wpos|1|%s|%s" % (H(x), H(y))

    def run(extra, n=1):
        return extra + ["lhot|0", "tdump|0"] * n

    # ---- ReturnToPatrol: racing on above 30 mph
    racing = b2f(0x415692b6)
    for fwd in (racing, ulps(racing, 1), ulps(racing, -1), 0.0, -20.0,
                100.0, NAN):
        s += cprep() + ["cf|1|fwd|%s" % H(fwd), "rtp|0", "tdump|0"]

    # ---- GetBestFlankSide: the lanes either side of the chased car, and
    # where cop 0's car is from it
    s += cprep()
    for dx, dy in ((1.0, 0.0), (0.6, 0.8)):
        for lw, rw in ((5.0, 5.0), (3.0, 3.0), (ulps(3.0, -1), 5.0),
                       (5.0, ulps(3.0, -1)), (0.0, 0.0), (3.0, 0.0),
                       (0.0, 3.0), (NAN, 5.0), (-1.0, 9.0)):
            for off in (0.0, 0.5, -0.5, 2.0):
                for lx, ly in ((-1.0, 0.0), (1.0, 0.0), (0.0, 0.0),
                               (-0.0, 0.0), (-1.0, 2.5),
                               (1.0, ulps(2.5, -1)), (1.0, -2.5),
                               (-1.0, -2.4), (NAN, 0.0), (1.0, NAN)):
                    s += [chase_pt(0, 0.0, off, dx, dy, lw, rw),
                          "w2c|%s|%s" % (H(lx), H(ly)), "bfs|0|2"]

    # ---- the way in: the gap round the track, above 0 with cop 0 ahead;
    # the chased car's speed and its way along its route. No sub-state,
    # so nothing more.
    for tlen, mine, theirs in (
            (0.0, 0.0, 0.0), (0.0, 450.0, 0.0), (0.0, ulps(450.0, -1), 0.0),
            (0.0, 0.0, 450.0), (0.0, 0.0, ulps(450.0, -1)),
            (0.0, 451.0, 0.0), (0.0, -180.0, 0.0),
            (0.0, ulps(-180.0, 1), 0.0), (0.0, ulps(-180.0, -1), 0.0),
            (0.0, -181.0, 0.0), (0.0, 0.0, 180.0), (0.0, 6.0, 0.0),
            (0.0, ulps(6.0, -1), 0.0), (0.0, 5.0, 0.0), (0.0, 100.0, 0.0),
            (0.0, -0.0, 0.0), (0.0, NAN, 0.0), (0.0, INF, 0.0),
            (1000.0, 990.0, 10.0), (1000.0, 10.0, 990.0),
            (1000.0, 1000.0, 0.0), (1000.0, 750.0, 250.0),
            (1000.0, 0.0, 500.0), (1000.0, 300.0, 0.0),
            (3000.0, 2900.0, 100.0)):
        for fwd, vx in ((100.0, 3.0), (100.0, -3.0), (100.0, 0.0),
                        (100.0, -0.0), (-100.0, -3.0), (mph20, -3.0),
                        (ulps(mph20, 1), 3.0), (ulps(mph20, -1), 3.0),
                        (0.0, 3.0)):
            s += cprep(lss=0) + run([
                "tlen|%s" % H(tlen), "cf|1|dat|%s" % H(mine),
                "cf|2|dat|%s" % H(theirs), "cf|2|fwd|%s" % H(fwd),
                "cf|2|vx|%s" % H(vx), "cf|2|vy|%s" % H(0.0)])
    # The sub-state taken up, or not.
    for lss, dlss in ((0, 0), (3, 3), (0, 3), (3, 0), (12, 5), (5, 12),
                      (13, 3), (3, 13), (-1, 3), (16, 16), (2, 1)):
        s += cprep(lss=lss, dlss=dlss) + run([])

    # ---- PURSUIT_FOLLOW
    # Coming in or staying; primary, the other cop or alone; 21 m off or
    # nearer; MyDLOffset.x 0 or not.
    for lss in (0, 3):
        for cops in ((0, -1), (1, 0), (-1, -1), (2, 0)):
            for x in (-21.0, ulps(-21.0, -1), ulps(-21.0, 1), -10.0, NAN):
                for dlx in (0.0, -0.0, 5.0):
                    s += cprep(lss=lss, dlss=3) + run([
                        "pcops|0|%d|%d" % cops, cop_at(x, 0.0),
                        "af|0|dlx|%s" % H(dlx), "af|0|dly|%s" % H(1.0),
                        "af|0|sst|%s" % H(1.0), "cf|2|fwd|%s" % H(100.0)])
    # The draw for a flank, from a base that takes it.
    fbase = [cop_at(-10.0, 0.0), "cf|2|fwd|%s" % H(100.0),
             "randf|%s" % H(0.5), "af|0|sst|%s" % H(0.0),
             "w2c|%s|%s" % (H(1.0), H(0.0))]
    variants = [[]]
    variants += [["randf|%s" % H(r)]
                 for r in (1.0, ulps(1.0, -1), NAN, 0.0, -1.0, INF)]
    variants += [["wcar|2|5|%s|%s|1|1" % (H(0.0), H(0.0)), "mdiff|%d" % d]
                 for d in (0, 1, 2)]
    variants += [["af|0|sst|%s" % H(t)] for t in (0.5, -0.0, 1e-30, NAN)]
    variants += [["coll|1|1|1:1:2"], ["coll|1|1|1:1:0"],
                 ["coll|1|2|1:1:0|1:2:1"], ["coll|1|1|0:1:2"],
                 ["coll|1|1|1:2:1"], ["coll|1|0|1:1:2"]]
    variants += [["w2c|%s|%s" % (H(-1.0), H(0.0))],
                 ["w2c|%s|%s" % (H(0.0), H(1.0))],
                 [chase_pt(0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)],
                 [chase_pt(0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0),
                  "w2c|%s|%s" % (H(1.0), H(3.0))],
                 [chase_pt(0, 0.0, 0.0, 1.0, 0.0, 5.0, 0.0)],
                 [chase_pt(0, 0.0, 0.0, 1.0, 0.0, 0.0, 5.0),
                  "w2c|%s|%s" % (H(-1.0), H(0.0))]]
    for lss1 in (0, 3, 4, 5, 7, 8, 9, 10, 11, 12):
        for fl in (1.0, -1.0, 0.0, -0.0):
            for cops in ("0|1", "1|0"):
                variants.append(["pcops|0|%s" % cops, "af|1|lss|%x" % lss1,
                                 "af|1|flank|%s" % H(fl)])
    for lx in (1.0, -1.0):
        for lss1 in (4, 7, 8, 10):
            for fl in (1.0, -1.0):
                variants.append(["w2c|%s|%s" % (H(lx), H(0.0)),
                                 "pcops|0|0|1", "af|1|lss|%x" % lss1,
                                 "af|1|flank|%s" % H(fl)])
    variants += [["pcops|0|0|1", "mycar|1|-1"], ["pcops|0|1|0", "mycar|1|-1"],
                 ["pcops|0|0|1", "mycar|1|-1", "af|1|lss|9"],
                 ["pcops|0|1|0", "mycar|1|-1", "af|1|lss|9"]]
    for lss2 in (0, 3, 5, 9, 11, 12):
        variants += [["pcops|0|0|2", "lss|2|%d" % lss2],
                     ["pcops|0|2|0", "lss|2|%d" % lss2]]
    for fwd in (mph20, ulps(mph20, 1), ulps(mph20, -1), -100.0, 0.0, NAN,
                -mph20, -ulps(mph20, -1)):
        variants += [["cf|2|fwd|%s" % H(fwd)],
                     ["cf|2|fwd|%s" % H(fwd), cop_at(-30.0, 0.0)]]
    for v in variants:
        s += cprep(lss=3) + run(fbase + v)

    # ---- FOLLOW_OFFSET: 6.5 m back and 3 m out on the flank side
    def obase(fl=1.0):
        return ["af|0|flank|%s" % H(fl), "w2c|%s|%s" % (H(fl), H(0.0)),
                "af|0|sst|%s" % H(0.0), "af|0|n48x|%s" % H(6.5),
                "af|0|n48y|%s" % H(3.0 * fl), cop_at(-10.0, 0.0)]
    for lss in (0, 4):
        for fl in (1.0, -1.0):
            s += cprep(lss=lss, dlss=4) + run(obase(fl))
    variants = [["w2c|%s|%s" % (H(-1.0), H(0.0))],
                ["af|0|flank|%s" % H(0.0),
                 chase_pt(0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)],
                ["af|0|flank|%s" % H(0.0)]]
    variants += [["af|0|sst|%s" % H(t)] for t in (0.5, -0.0, NAN)]
    for n48x in (6.51, 6.49, 6.509999, 6.5099998, 6.490001, NAN):
        variants.append(["af|0|n48x|%s" % H(n48x)])
    for n48y in (3.01, 2.99, 3.0099998, 2.9900002, NAN):
        variants.append(["af|0|n48y|%s" % H(n48y)])
    variants += [["coll|1|1|1:1:2"], ["coll|1|1|1:1:3"]]
    for v in variants:
        s += cprep(lss=4) + run(obase() + v)
    # Where cop 0's car is: round the chased car, and the chased car's
    # heading.
    for ang in (0, 0x4000, 0xc000, 0x2000):
        for r in (10.0, 15.0, ulps(15.0, 1), 30.0):
            for k in range(16):
                t = math.radians(22.5 * k)
                s += cprep(lss=4) + run(obase() + [
                    cop_at(r * math.cos(t), r * math.sin(t)),
                    "cf|2|ang|%x" % ang])

    # ---- LOW_SPEED_CLOSE_FOLLOW: 6 m back, until the chased car is above
    # 20 mph, or stops within 10 m
    for lss in (0, 5):
        for fwd in (mph20, ulps(mph20, 1), ulps(mph20, -1), mph5,
                    ulps(mph5, 1), ulps(mph5, -1), 0.0, -100.0, 100.0, NAN,
                    -mph5):
            for x in (-10.0, ulps(-10.0, 1), ulps(-10.0, -1), -5.0, -30.0):
                s += cprep(lss=lss, dlss=5) + run([
                    "cf|2|fwd|%s" % H(fwd), cop_at(x, 0.0)])

    # ---- FOLLOW_BACKWARDS
    for cops in ((0, -1), (1, 0)):
        for x in (-20.0, ulps(-20.0, 1), ulps(-20.0, -1), -5.0, -40.0):
            for sst in (0.0, 0.5):
                for ri in (0, 1, 2):
                    for side in ([], ["w2c|%s|%s" % (H(-1.0), H(0.0))],
                                 [chase_pt(0, 0.0, 0.0, 1.0, 0.0, 0.0,
                                           0.0)]):
                        s += cprep(lss=6) + run([
                            "pcops|0|%d|%d" % cops, cop_at(x, 0.0),
                            "af|0|sst|%s" % H(sst), "randi|%d" % ri,
                            "w2c|%s|%s" % (H(1.0), H(0.0)),
                            "cf|2|vx|%s" % H(-3.0), "cf|2|vy|%s" % H(0.0),
                            "cf|2|fwd|%s" % H(-100.0)] + side)
    for fwd in (mph5, ulps(mph5, 1), ulps(mph5, -1), 0.0, -mph5,
                -ulps(mph5, -1), 100.0):
        for x in (-10.0, ulps(-10.0, 1), ulps(-10.0, -1), -5.0):
            for vx in (-3.0, 1.0, ulps(1.0, 1), 2.0, NAN):
                s += cprep(lss=6) + run([
                    cop_at(x, 0.0), "af|0|sst|%s" % H(1.0),
                    "cf|2|vx|%s" % H(vx), "cf|2|vy|%s" % H(0.0),
                    "cf|2|fwd|%s" % H(fwd)])

    # ---- FLANK: level with the chased car, out on the flank side
    def kbase(fl=1.0):
        return ["af|0|flank|%s" % H(fl), "w2c|%s|%s" % (H(fl), H(0.0)),
                "af|0|sst|%s" % H(1.0), "af|0|dly|%s" % H(3.0 * fl),
                "af|0|n48y|%s" % H(3.0 * fl)]
    for lss in (0, 7):
        for fl in (1.0, -1.0):
            s += cprep(lss=lss, dlss=7) + run(kbase(fl))
    s += cprep(lss=7) + run(kbase() + ["w2c|%s|%s" % (H(-1.0), H(0.0))])
    pos8 = ((10.0, 0.0), (0.0, 10.0), (-10.0, 0.0), (0.0, -10.0),
            (7.0, 7.0), (-7.0, 7.0), (-7.0, -7.0), (7.0, -7.0))
    for x, y in pos8:
        for player in (0, 1):
            for flags in (0, 4, 0xfb, 0xffffffff):
                for ri in (0, 1, 2):
                    for cops in ((0, -1), (1, 0)):
                        s += cprep(lss=7) + run(kbase() + [
                            "wcar|2|5|%s|%s|%d|1" % (H(0.0), H(0.0),
                                                     player),
                            cop_at(x, y), "pflags|0|%x" % flags,
                            "randi|%d" % ri, "pcops|0|%d|%d" % cops])
    # The timer, the offset and how far back, from beside or behind.
    for x, y in pos8 + ((0.0, 10.0), (-10.0, 10.0)):
        for ang in (0, 1, 0xffff, 2, 0xfffe):
            for sst, n48x in ((0.0, 0.0), (0.0, 0.02), (0.5, 0.0),
                              (-0.0, 0.01)):
                s += cprep(lss=7) + run(kbase() + [
                    cop_at(x, y), "cf|2|ang|%x" % ang,
                    "af|0|sst|%s" % H(sst), "af|0|n48x|%s" % H(n48x),
                    "pflags|0|4"])

    # ---- BUMP
    for lss in (0, 8):
        for sst in (1.75, 0.875, 0.4375, ulps(0.4375, -1), 0.1, 0.0, -0.0,
                    NAN, 3.0, -1.0):
            for cs, coll in ((0, "coll|1|1|1:1:2"), (2, "coll|1|1|1:1:2"),
                             (0, "coll|1|1|1:1:0"), (1, "coll|1|1|1:2:1")):
                for fl in (1.0, -1.0):
                    s += cprep(lss=lss, dlss=8) + run([
                        "af|0|sst|%s" % H(sst), "rp|cs|%d" % cs, coll,
                        "af|0|flank|%s" % H(fl), cop_at(-3.0, 1.0),
                        "cf|1|z|%s" % H(0.5)])
    for player, d in ((0, 1), (1, 0), (1, 1), (1, 2)):
        for move in (0, 1, 5):
            for x, y, z in ((-3.0, 1.0, 0.5), (0.0, 0.0, 0.0),
                            (4.0, -3.0, -1.0), (1e-3, 0.0, 0.0),
                            (-30.0, 40.0, 2.0)):
                s += cprep(lss=8) + run([
                    "wcar|2|5|%s|%s|%d|1" % (H(0.0), H(0.0), player),
                    "mdiff|%d" % d, "cf|2|move|%d" % move,
                    "af|0|sst|%s" % H(0.25), "coll|1|1|1:1:2",
                    "af|0|flank|%s" % H(1.0), cop_at(x, y),
                    "cf|1|z|%s" % H(z)])

    # ---- BLOCK
    for lss in (0, 9):
        for mine, theirs in ((0.0, 0.0), (0.0, 10.0), (-0.0, 0.0),
                             (5.0, 0.0), (0.0, 179.0), (0.0, 1e-3)):
            s += cprep(lss=lss, dlss=9) + run([
                "cf|1|dat|%s" % H(mine), "cf|2|dat|%s" % H(theirs),
                "cf|2|vmag|%s" % H(100.0), "cf|2|vx|%s" % H(-3.0),
                "cf|2|fwd|%s" % H(100.0), cop_at(-30.0, 0.0)])
    for vmag in (100.0, mph20, ulps(mph20, 1), ulps(mph20, -1), -100.0, 5.0):
        for vx in (-3.0, 3.0, -0.0):
            for x in (-30.0, -20.0, ulps(-20.0, 1), ulps(-20.0, -1), -15.0):
                s += cprep(lss=9) + run([
                    "cf|2|vmag|%s" % H(vmag), "cf|2|vx|%s" % H(vx),
                    "cf|2|vy|%s" % H(0.0), "cf|2|fwd|%s" % H(100.0),
                    cop_at(x, 0.0)])
    for fwd in (mph20, ulps(mph20, 1), ulps(mph20, -1), -mph20, 0.0, 100.0,
                NAN):
        for x in (-10.0, ulps(-10.0, 1), ulps(-10.0, -1), -5.0, -30.0):
            s += cprep(lss=9) + run(["cf|2|fwd|%s" % H(fwd), cop_at(x, 0.0)])

    # ---- GET_AHEAD: once, on the way in
    for lss in (0, 10):
        for x, y in ((-30.0, 5.5), (-25.0, 9.0), (-40.0, 0.0), (NAN, 0.0)):
            s += cprep(lss=lss, dlss=10) + run([cop_at(x, y)])

    # ---- ACQUIRE: until back within 180 m
    for lss in (0, 11):
        for mine in (-180.0, ulps(-180.0, 1), ulps(-180.0, -1), -100.0,
                     -300.0, 0.0, NAN):
            s += cprep(lss=lss, dlss=11) + run(["cf|1|dat|%s" % H(mine)])

    # ---- STOP
    for lss in (0, 12):
        for sst in (0.0, -0.0, 0.25, -1.0, NAN):
            for fwd in (mph5, ulps(mph5, 1), ulps(mph5, -1), -mph5, 0.0):
                for x in (-10.0, ulps(-10.0, -1), -5.0):
                    s += cprep(lss=lss, dlss=12) + run([
                        "af|0|sst|%s" % H(sst), "cf|2|fwd|%s" % H(fwd),
                        cop_at(x, 0.0)])

    # ---- DoCaughtSpeederLogic: held; WAITING goes back on patrol when
    # its time is up, or to limbo 250 m from every player, and looks round
    for lss in (15, 16, 0, 14):
        for dist in (100.0, 250.0, ulps(250.0, -1), NAN):
            for sst in (0.0, 1.0, -0.0):
                for fwd in (20.0, 1.0):
                    s += cprep(ls=7, lss=lss) + [
                        "g|dist|%s" % H(dist), "af|0|sst|%s" % H(sst),
                        "cf|1|fwd|%s" % H(fwd), "lcaught|0", "tdump|0"]
    for reqp in (0, 1):
        for fwd in (100.0, 1.0):
            for sst in (0.0, 1.0):
                s += cprep(ls=7, lss=16) + [
                    "setp|0|-1", "g|reqp|%d" % reqp, "af|0|sst|%s" % H(sst),
                    "wpos|2|%s|%s" % (H(-10.0), H(5.5)),
                    "cf|2|fwd|%s" % H(fwd), "lcaught|0", "tdump|0"]

    # ---- through Think
    # From patrol into a chase: A2 seen going fast, the pursuit granted.
    for wte in (0.5, 1.0 / 30):
        s += cprep(ls=5, lss=1) + [
            "setp|0|-1", "rinfo|0|0|1", "g|reqp|1", "g|wte|%s" % H(wte),
            "cf|2|fwd|%s" % H(100.0), "wpos|2|%s|%s" % (H(-10.0), H(5.5)),
            "randf|%s" % H(0.5), "w2c|%s|%s" % (H(1.0), H(0.0))]
        s += ["think|0", "tdump|0"] * 10
    # Caught: ticketing, then waiting, then back on patrol or in limbo.
    for dist in (100.0, 300.0):
        s += cprep() + ["af|0|ds|7", "g|wte|%s" % H(0.5),
                        "g|dist|%s" % H(dist), "rinfo|0|0|1"]
        s += ["think|0", "tdump|0"] * 2
        s += ["lss|0|16"] + ["think|0", "tdump|0"] * 4
    # The gap opening: back on patrol.
    for wte in (0.5, 0.0):
        s += cprep() + ["cf|1|dat|%s" % H(500.0), "g|wte|%s" % H(wte),
                        "rinfo|0|0|1", "cf|1|fwd|%s" % H(20.0)]
        s += ["think|0", "tdump|0"] * 3

    # ---- at random
    for runno in range(500):
        lss = rnd.choice((3, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 0))
        dlss = rnd.choice((lss, lss, rnd.choice((3, 4, 5, 6, 7, 8, 9, 10, 11,
                                                 12))))
        s += cprep(lss=lss, dlss=dlss)
        a = rnd.uniform(0.0, 2.0 * math.pi)
        r = rnd.choice((rnd.uniform(0.0, 12.0), rnd.uniform(0.0, 25.0),
                        rnd.uniform(15.0, 40.0)))
        h = rnd.uniform(0.0, 2.0 * math.pi)
        fl = rnd.choice((-1.0, 0.0, 1.0))
        dlx = rnd.choice((0.0, 6.5, 13.0, rnd.uniform(-3.0, 13.0)))
        dly = rnd.choice((0.0, 3.0 * fl, 2.5, rnd.uniform(-4.0, 4.0)))
        ch_dat = rnd.uniform(0.0, 1000.0)
        gap = rnd.choice((rnd.uniform(-20.0, 20.0), rnd.uniform(-250.0, 50.0),
                          rnd.uniform(-500.0, 500.0)))
        s += ["wcar|2|5|%s|%s|%d|1" % (H(0.0), H(0.0), rnd.choice((0, 1))),
              cop_at(r * math.cos(a), r * math.sin(a)),
              "cf|1|z|%s" % H(rnd.uniform(-1.0, 1.0)),
              "cf|2|z|%s" % H(rnd.uniform(-1.0, 1.0)),
              "cf|2|ang|%x" % rnd.randrange(0x10000),
              "cf|2|fwd|%s" % H(rnd.choice((rnd.uniform(-40.0, 40.0),
                                             rnd.uniform(0.0, 10.0), 100.0))),
              "cf|2|vmag|%s" % H(rnd.uniform(0.0, 40.0)),
              "cf|2|vx|%s" % H(rnd.uniform(-30.0, 30.0)),
              "cf|2|vy|%s" % H(rnd.uniform(-30.0, 30.0)),
              "cf|1|fwd|%s" % H(rnd.uniform(0.0, 40.0)),
              "cf|2|move|%d" % rnd.choice((0, 1, 1, 5)),
              "mdiff|%d" % rnd.randrange(3),
              "rp|cs|%d" % rnd.choice((0, 1, 2)),
              "pflags|0|%x" % rnd.choice((0, 4, 0xffffffff, 0xfb)),
              "tlen|%s" % H(rnd.choice((0.0, 1000.0, 3000.0))),
              "cf|2|dat|%s" % H(ch_dat), "cf|1|dat|%s" % H(ch_dat + gap),
              chase_pt(0, rnd.uniform(-3.0, 3.0), rnd.uniform(-3.0, 3.0),
                       math.cos(h), math.sin(h), rnd.uniform(0.0, 8.0),
                       rnd.uniform(0.0, 8.0)),
              "af|0|flank|%s" % H(fl), "af|0|dlx|%s" % H(dlx),
              "af|0|dly|%s" % H(dly),
              "af|0|n48x|%s" % H(dlx + rnd.choice((0.0, 0.0, 0.005, -0.005,
                                                   0.02,
                                                   rnd.uniform(-2.0, 2.0)))),
              "af|0|n48y|%s" % H(dly + rnd.choice((0.0, 0.0, 0.005, 0.02,
                                                   rnd.uniform(-2.0, 2.0)))),
              "af|0|sst|%s" % H(rnd.choice((0.0, 0.0, 0.3,
                                            rnd.uniform(0.0, 3.0)))),
              "af|0|line|%x" % (rnd.choice((-1, 0, 2)) & M32),
              "pcops|0|%d|%d" % rnd.choice(((0, -1), (0, 1), (1, 0), (0, 2),
                                            (2, 0), (-1, -1))),
              "af|1|lss|%x" % rnd.randrange(13),
              "af|1|flank|%s" % H(rnd.choice((-1.0, 0.0, 1.0))),
              "mycar|1|%d" % rnd.choice((3, 3, -1)),
              "lss|2|%d" % rnd.choice((0, 3, 5, 9, 11, 12)),
              "randi|%s" % "|".join(str(rnd.randrange(3)) for _ in range(4)),
              "randf|%s" % "|".join(H(rnd.choice((0.5, 0.99, 1.0, 1.5, 0.0)))
                                    for _ in range(3)),
              "w2c|%s" % "|".join("%s|%s" % (H(rnd.uniform(-5.0, 5.0)),
                                             H(rnd.uniform(-4.0, 4.0)))
                                  for _ in range(3)),
              "rinfo|0|0|%d" % rnd.randrange(4),
              "g|dist|%s" % H(rnd.uniform(150.0, 350.0)),
              "g|reqp|%d" % rnd.choice((0, 1)),
              "g|wte|%s" % H(rnd.choice((1.0 / 30, 0.25,
                                         rnd.uniform(0.0, 0.5))))]
        if rnd.random() < 0.3:
            s += ["coll|1|1|1:1:%d" % rnd.choice((0, 2, 3))]
        if rnd.random() < 0.5:
            for _ in range(rnd.randrange(1, 4)):
                s += ["setp|0|0", "lhot|0", "tdump|0"]
        else:
            for _ in range(rnd.randrange(1, 5)):
                s += ["think|0", "tdump|0"]
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

    # ---- Think
    s += think_script()

    # ---- the radar traps, roadblocks and patrols
    s += logic_script()

    # ---- the chase
    s += chase_script()
    return s


# =================================================================== model

class Model(object):
    def __init__(self):
        e = self.e = retail_model.emu(retail=True, ieee=True, eediv=True,
                                      eesqrt=True, eemul=True)
        self.out = []
        self.dist = 0
        e.write(G_SKID, struct.pack("<H", 1820))
        self.names = {DTR: "DTR"}
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
            for off in (20, 28, 32, 1588):
                e.put32(p + off, 0)
            self.names[p] = "U%d" % k
        e.write(self.world, bytes(128))
        self.distq = []
        self.reqp = 0
        self.cbs = {}
        self.colls = [[] for _ in range(NCARS)]
        self.coltok = {}
        for j in range(NCARS):
            for i in range(NCOLS):
                t = e.alloc(16, align=16)
                self.coltok[t] = (j, i)
                self.names[t] = "X%d" % (10 * j + i)
        self.front = {}
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
        self.randi = []
        self.randf = []
        self.w2c = []
        self.randi_at = self.randf_at = self.w2c_at = 0
        # The chased car's body's table, two entries logged by their stubs.
        vt = self.cbvt = self.block(256)
        code = self.block(256)
        for slot, fn in ((CB_PHYSMODE, self.s_physmode),
                         (CB_IMPULSE, self.s_impulse)):
            e.write(vt + slot, struct.pack("<hhI", 0, 0, code + slot))
            e.stub(code + slot, fn)
        for a, fn in ((S_MALLOC, self.s_malloc), (S_MALLOC2, self.s_malloc2),
                      (S_DELETE, self.s_delete), (S_OMALLOC, self.s_omalloc),
                      (S_SFREE, self.s_sfree), (S_CARCTOR, self.s_carctor),
                      (S_CTRLMODE, self.s_ctrlmode),
                      (S_MOVEMODE, self.s_movemode), (S_RESET, self.s_reset),
                      (S_RMCOP, self.s_rmcop), (S_RMSPK, self.s_rmspk),
                      (S_WRECK, self.s_wreck), (S_NEAREST, self.s_nearest),
                      (S_NEXT, self.s_next), (S_GETROUTE, self.s_getroute),
                      (S_GETRP, self.s_getrp), (S_DTCLEAR, self.s_dtclear),
                      (S_ADDPT, self.s_addpt), (S_RENDER, self.s_render),
                      (S_COLLON, self.s_collon),
                      (S_COLLOFF, self.s_colloff),
                      (S_EBRAKE, self.s_ebrake), (S_DIST, self.s_dist),
                      (S_REPAIR, self.s_repair), (S_PTHINK, self.s_pthink),
                      (S_NDSPEED, self.s_ndspeed), (S_REQP, self.s_reqp),
                      (S_GETCOL, self.s_getcol), (S_TWOCAR, self.s_twocar),
                      (S_CARS, self.s_cars), (S_INFRONT, self.s_infront),
                      (S_RANDI, self.s_randi), (S_RANDF, self.s_randf),
                      (S_W2C, self.s_w2c)):
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

    def s_render(self, em):
        self.emit("  render %s %s" % (self.sym(em.reg[4]),
                                      self.sym(em.reg[5])))

    def s_collon(self, em):
        self.emit("  collon %s" % self.sym(em.reg[4]))

    def s_colloff(self, em):
        self.emit("  colloff %s" % self.sym(em.reg[4]))

    def s_ebrake(self, em):
        self.emit("  ebrake %s %08x" % (self.sym(em.reg[4]),
                                        em.fpr[12] & M32))

    def s_dist(self, em):
        e = self.e
        pos = em.reg[5] & M32
        r = self.distq.pop(0) if self.distq else self.dist
        self.emit("  dist %s %08x %08x -> %08x" % (
            self.sym(em.reg[4]), e.u32(pos), e.u32(pos + 4), r))
        em.fpr[0] = r

    def s_reqp(self, em):
        self.emit("  reqp %s %s %s -> %d" % (
            self.sym(em.reg[4]), self.sym(em.reg[5]), self.sym(em.reg[6]),
            s32(self.reqp)))
        if self.reqp:
            # A pursuit granted is U4's, chasing the car, with the cop its
            # primary.
            u4, cop = self.pursuits[4], em.reg[5] & M32
            self.e.put32(u4 + 16, em.reg[6] & M32)
            self.e.put32(u4 + 28, cop)
            self.e.put32(u4 + 32, 0)
            self.e.put32(cop, u4)
        return self.reqp

    def s_randi(self, em):
        r = 0
        if self.randi:
            r = self.randi[self.randi_at % len(self.randi)]
            self.randi_at += 1
        self.emit("  randi %s %d -> %d" % (self.sym(em.reg[4]),
                                           s32(em.reg[5]), r))
        return r & M32

    def s_randf(self, em):
        r = 0
        if self.randf:
            r = self.randf[self.randf_at % len(self.randf)]
            self.randf_at += 1
        self.emit("  randf %s %08x -> %08x" % (self.sym(em.reg[4]),
                                               em.fpr[12] & M32, r))
        em.fpr[0] = r

    def s_w2c(self, em):
        e = self.e
        x = y = 0
        if self.w2c:
            x, y = self.w2c[self.w2c_at % len(self.w2c)]
            self.w2c_at += 1
        st, out, vin = (em.reg[r] & M32 for r in (4, 5, 6))
        e.put32(out, x)
        e.put32(out + 4, y)
        self.emit("  w2c A%d %08x %08x -> %08x %08x" % (
            self.car_k(st - 64) if self.car_k(st - 64) >= 0 else NCARS,
            e.u32(vin), e.u32(vin + 4), x, y))

    def s_physmode(self, em):
        self.emit("  physmode %s %s" % (self.sym(em.reg[4]),
                                        self.sym(em.reg[5])))

    def s_impulse(self, em):
        e = self.e
        j, at = em.reg[5] & M32, em.reg[6] & M32
        self.emit("  impulse %s %08x %08x %08x %08x at %08x %08x %08x" % (
            self.sym(em.reg[4]), e.u32(j), e.u32(j + 4), e.u32(j + 8),
            e.u32(j + 12), e.u32(at), e.u32(at + 4), e.u32(at + 8)))

    def car_or_0(self, k):
        return self.cars[k] if k >= 0 else 0

    def s_getcol(self, em):
        body, i = em.reg[4] & M32, s32(em.reg[5])
        j = self.cbs.get(body, -1)
        r = 0
        if j >= 0 and 0 <= i < NCOLS:
            r = [t for t, ji in self.coltok.items() if ji == (j, i)][0]
        self.emit("  getcol %s %d -> %s" % (self.sym(body), i, self.sym(r)))
        return r

    def coll(self, col):
        j, i = self.coltok[col & M32]
        lst = self.colls[j]
        return lst[i] if i < len(lst) else (0, -1, -1)

    def s_twocar(self, em):
        two = self.coll(em.reg[4])[0]
        self.emit("  twocar %s -> %d" % (self.sym(em.reg[4]), two))
        return two

    def s_cars(self, em):
        _, a, b = self.coll(em.reg[4])
        self.e.put32(em.reg[5] & M32, self.car_or_0(a))
        self.e.put32(em.reg[6] & M32, self.car_or_0(b))
        self.emit("  cars %s -> %s %s" % (
            self.sym(em.reg[4]), self.sym(self.car_or_0(a)),
            self.sym(self.car_or_0(b))))

    def s_infront(self, em):
        r = self.front.get((self.car_k(em.reg[4]), self.car_k(em.reg[5])), 0)
        self.emit("  infront %s %s %d -> %d" % (
            self.sym(em.reg[4]), self.sym(em.reg[5]), em.reg[6] & 0xffff, r))
        return r

    def s_repair(self, em):
        self.emit("  repair %s" % self.sym(em.reg[4]))

    def s_pthink(self, em):
        self.emit("  pthink %s" % self.sym(em.reg[4]))

    def s_ndspeed(self, em):
        self.emit("  ndspeed %s %08x %08x %08x %d" % (
            self.sym(em.reg[4]), em.fpr[12] & M32, em.fpr[13] & M32,
            em.fpr[14] & M32, s32(em.reg[5])))

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

    def tdump(self, k):
        e, o = self.e, self.emit
        c = self.cop(k)
        u = lambda off: e.u32(c + off)                    # noqa: E731
        o("T%d cop ls %08x %08x lss %08x %08x n32 %08x sst %08x n48 %08x "
          "%08x n64 %08x %08x phys %08x delay %08x pu %s st %s rbi %08x "
          "dl %08x %08x flank %08x line %08x"
          % (k, u(12), u(16), u(20), u(24), u(32), u(44), u(48), u(52),
             u(64), u(68), u(84), u(88), self.sym(u(0)), self.sym(u(36)),
             u(40), u(56), u(60), u(72), u(92)))
        car = u(4)
        w = lambda off: e.u32(car + off)                  # noqa: E731
        idx = s16(e.u16(car + CAR_INDEX))
        o("T%d car render %02x lights %08x siren %08x vis %08x move %08x "
          "vel %08x %08x %08x vmag %08x mv %08x blown %02x %02x rumble %08x "
          "trac %08x cdmg %08x"
          % (k, e.u8(car + CAR_RENDER), w(CAR_LIGHTS), w(CAR_SIREN),
             w(CAR_VIS), w(CAR_MOVE), w(112), w(116), w(120), w(964),
             w(1088), e.u8(car + 2124), e.u8(car + 2125), w(2128), w(1116),
             e.u32(self.m + 10420 + 4 * idx)))
        d = w(CAR_DRIVER)
        o("T%d drv steer %04x thr %08x brk %08x eb %08x dg %08x sg %08x "
          "ctl %08x ri %s %s n %02x pt0 %08x %08x"
          % (k, e.u16(d + 528), e.u32(d + 532), e.u32(d + 536),
             e.u32(d + 540), e.u32(d + 544), e.u32(d + 548),
             e.u32(w(CAR_CTRL) + 36), self.sym(u(76)), self.sym(u(80)),
             e.u8(d), e.u32(d + 16), e.u32(d + 20)))

    # ---- the script

    def vcall(self, c, slot, *args, limit=200000):
        e = self.e
        vt = e.u32(c + 28)
        delta = struct.unpack("<h", e.read(vt + slot, 2))[0]
        return e.call(e.u32(vt + slot + 4), c + delta, *args, limit=limit)

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
            e.put32(RP + {"dir": RP_DIR, "maxcops": RP_MAXCOPS,
                          "cs": RP_CS}[a[1]], v(2))
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
            # The pursuit list empty, no pullovers, no pursuable timers.
            e.put32(m + 44, m + 44)
            e.put32(m + 48, m + 44)
            for j in range(8):
                e.put32(m + 100 + 28 * j, 0)
                e.put32(m + 10356 + 4 * j, 0)
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
        elif o == "rig":
            j = int(a[1])
            car = self.cars[j]
            k = self.block(76)
            mv = self.block(128)
            cb = self.block(96)
            e.put32(cb + 80, self.cbvt)
            self.names[k] = "KJ%d" % j
            self.names[mv] = "MV%d" % j
            self.names[cb] = "CB%d" % j
            self.cbs[cb] = j
            e.put32(mv + MOVER_AIRBORNE, 0)
            e.put32(car + CAR_CTRL, k)
            e.put32(car + CAR_MOVER, mv)
            e.put32(car + CAR_BODY, cb)
            e.put32(self.drivers[j] + 556, VT_NULLDRIVER)
        elif o in ("cf", "df"):
            j, name, x = int(a[1]), a[2], int(a[3], 16)
            if o == "cf" and name == "air":
                e.put32(e.u32(self.cars[j] + CAR_MOVER) + MOVER_AIRBORNE, x)
            elif o == "cf" and name == "dmg":
                e.put32(self.cars[j] + CAR_DAMAGE, self.dmg if x else 0)
            else:
                off, kind = (CAR_FIELDS if o == "cf" else DRIVER_FIELDS)[name]
                at = (self.cars[j] if o == "cf" else self.drivers[j]) + off
                if kind in "fw":
                    e.put32(at, x)
                elif kind == "h":
                    e.write(at, struct.pack("<H", x & 0xffff))
                else:
                    e.write(at, bytes([x & 0xff]))
        elif o == "kf":
            e.put32(e.u32(self.cars[int(a[1])] + CAR_CTRL) + 36,
                    int(a[2], 16))
        elif o == "af":
            e.put32(self.cop(int(a[1])) + COP_FIELDS[a[2]], int(a[3], 16))
        elif o == "g":
            x = int(a[2], 16)
            if a[1] == "wte":
                e.put32(G_WTE, x)
            elif a[1] == "camf":
                e.put32(G_CAMF, x)
            elif a[1] == "reqp":
                self.reqp = x
            else:
                self.dist = x
        elif o == "mdmg":
            e.put32(self.m + 10420 + 4 * int(a[1]), int(a[2], 16))
        elif o == "think":
            self.vcall(self.cop(int(a[1])), 24, limit=2000000)
            self.emit("think %s" % a[1])
        elif o == "hst":
            e.call(F_HST, self.cop(int(a[1])), v(2), v(3), limit=2000000)
            self.emit("hst %s %s %s" % (a[1], a[2], a[3]))
        elif o == "mmt":
            e.call(F_MMT, self.cop(int(a[1])), limit=200000)
            self.emit("mmt %s" % a[1])
        elif o == "tdump":
            self.tdump(int(a[1]))
        elif o == "wcount":
            e.put32(self.world + 28, v(1))
            e.put32(self.world + 36, v(2))
        elif o == "distq":
            self.distq = [int(x, 16) for x in a[1:]]
        elif o == "coll":
            j = int(a[1])
            e.write(e.u32(self.cars[j] + CAR_BODY) + 18,
                    bytes([int(a[2]) & 0xff]))
            self.colls[j] = [tuple(int(x) for x in t.split(":"))
                             for t in a[3:]]
        elif o == "front":
            if a[1] == "clear":
                self.front = {}
            else:
                self.front[(int(a[1]), int(a[2]))] = int(a[3])
        elif o == "pidx":
            e.put32(self.m + 12, v(1))
        elif o == "pull":
            e.put32(self.m + 100 + 28 * int(a[1]), v(2))
        elif o == "ptimer":
            e.put32(self.m + 10356 + 4 * int(a[1]), int(a[2], 16))
        elif o == "plist":
            head = self.m + 44
            prev = head
            for t in a[1:]:
                pu = self.pursuits[int(t)]
                e.put32(prev, pu)
                e.put32(pu + 4, prev)
                prev = pu
            e.put32(prev, head)
            e.put32(head + 4, prev)
        elif o == "prb":
            r = int(a[2])
            e.put32(self.pursuits[int(a[1])] + 20,
                    self.m + 320 + 120 * r if r >= 0 else 0)
        elif o == "rbspot":
            rb = self.m + 320 + 120 * int(a[1])
            i = int(a[2])
            e.put32(rb + 8 + 8 * i, int(a[3], 16))
            e.put32(rb + 12 + 8 * i, int(a[4], 16))
            e.write(rb + 24 + 2 * i, struct.pack("<H", int(a[5]) & 0xffff))
        elif o == "tele":
            e.put32(self.dtpos, int(a[2], 16))
            e.put32(self.dtpos + 4, int(a[3], 16))
            e.call(F_TELE, self.cop(int(a[1])), self.dtpos, v(4))
            self.emit("tele %s" % a[1])
        elif o == "settrap":
            e.call(F_SETTRAP, self.cop(int(a[1])),
                   self.m + 8260 + 28 * int(a[2]))
            self.emit("settrap %s %s" % (a[1], a[2]))
        elif o == "setrb":
            k = int(a[3])
            e.call(F_SETRB, self.cop(int(a[1])),
                   self.m + 320 + 120 * int(a[2]),
                   self.pursuits[k] if k >= 0 else 0, v(4))
            self.emit("setrb %s %s %s %s" % (a[1], a[2], a[3], a[4]))
        elif o == "valid":
            r = e.call(F_VALID, self.cop(int(a[1])), self.cars[int(a[2])],
                       v(3), limit=200000)
            self.emit("valid %s %s %s -> %d" % (a[1], a[2], a[3], r & 0xff))
        elif o == "see":
            r = e.call(F_SEE, self.cop(int(a[1])), self.cars[int(a[2])])
            self.emit("see %s %s -> %d" % (a[1], a[2], s32(r)))
        elif o in ("listrap", "liroad", "lstrap", "lroad", "lpatrol"):
            f = {"listrap": F_ISTRAP, "liroad": F_IROAD, "lstrap": F_STRAP,
                 "lroad": F_ROAD, "lpatrol": F_PATROL}[o]
            e.call(f, self.cop(int(a[1])), limit=2000000)
            self.emit("%s %s" % (o, a[1]))
        elif o == "canteleport":
            e.put32(self.dtpos, int(a[2], 16))
            e.put32(self.dtpos + 4, int(a[3], 16))
            r = e.call(F_CANTELE, self.cars[int(a[1])], self.dtpos,
                       limit=200000)
            self.emit("canteleport %s -> %d" % (a[1], s32(r)))
        elif o == "caused":
            r = e.call(F_CAUSED, self.cars[int(a[1])], limit=200000)
            self.emit("caused %s -> %s" % (a[1], self.sym(r)))
        elif o == "pcops":
            pu = self.pursuits[int(a[1])]
            for j in range(2):
                c = int(a[2 + j])
                e.put32(pu + 28 + 4 * j, self.cop(c) if c >= 0 else 0)
        elif o == "mdiff":
            e.put32(self.m + 10476, v(1))
        elif o == "pflags":
            e.put32(self.pursuits[int(a[1])] + 1588, int(a[2], 16))
        elif o == "tlen":
            e.put32(TPM, int(a[1], 16))
        elif o == "randi":
            self.randi = [int(x, 0) for x in a[1:]]
            self.randi_at = 0
        elif o == "randf":
            self.randf = [int(x, 16) for x in a[1:]]
            self.randf_at = 0
        elif o == "w2c":
            self.w2c = [(int(a[1 + 2 * j], 16), int(a[2 + 2 * j], 16))
                        for j in range((len(a) - 1) // 2)]
            self.w2c_at = 0
        elif o in ("lhot", "lcaught", "rtp"):
            f = {"lhot": F_HOT, "lcaught": F_CAUGHT, "rtp": F_RTP}[o]
            e.call(f, self.cop(int(a[1])), limit=2000000)
            self.emit("%s %s" % (o, a[1]))
        elif o == "bfs":
            e.call(F_BFS, self.cop(int(a[1])), self.cars[int(a[2])],
                   limit=200000)
            self.emit("bfs %s %s -> %08x" % (a[1], a[2], e.fpr[0] & M32))
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
CU = "3DS Files/source/coputil.c"
MUTATIONS = [
    # ---- 12g-2: Teleport, SetSpeedTrap, SetRoadBlock
    ("tele_no_null", C,
     "    if (car == NULL)\n        return;\n    car_set_movement_mode(car, COP_MOVEMENT);",
     "    car_set_movement_mode(car, COP_MOVEMENT);"),
    ("tele_no_mode", C,
     "    car_set_movement_mode(car, COP_MOVEMENT);\n    // Retail's stack",
     "    // Retail's stack"),
    ("tele_mellow", C,
     "    car_set_movement_mode(car, COP_MOVEMENT);\n    // Retail's stack",
     "    car_set_movement_mode(car, MELLOW_MOVEMENT);\n    // Retail's stack"),
    ("tele_xy_swap", C, "    v.x = pos->x;\n    v.y = pos->y;\n",
     "    v.x = pos->y;\n    v.y = pos->x;\n"),
    ("tele_z", C, "    v.z = 0.0f;\n    car_reset_to_position",
     "    v.z = pos->y;\n    car_reset_to_position"),
    ("tele_speed", C, "car_reset_to_position(car, &v, 0.0f, ang);",
     "car_reset_to_position(car, &v, 1.0f, ang);"),
    ("settrap_no_ptr", C,
     "    c->pMySpeedTrap = t;\n    t->cop = &c->Base;\n",
     "    t->cop = &c->Base;\n"),
    ("settrap_no_cop", C,
     "    t->cop = &c->Base;\n    taicop_teleport(c, &t->v2Position",
     "    taicop_teleport(c, &t->v2Position"),
    ("settrap_no_tele", C,
     "    taicop_teleport(c, &t->v2Position, t->ang);\n", ""),
    ("settrap_state", C,
     "    tcop_set_desired_logic_state(&c->Base, LS_SPEED_TRAP);\n}",
     "    tcop_set_desired_logic_state(&c->Base, LS_ROAD_BLOCK);\n}"),
    ("setrb_no_pursuit", C,
     "    tcop_set_pursuit(&c->Base, p);\n    c->nMyRoadBlockIndex = i;\n",
     "    c->nMyRoadBlockIndex = i;\n"),
    ("setrb_no_index", C,
     "    c->nMyRoadBlockIndex = i;\n    taicop_teleport(c, &rb->CopPos[i]",
     "    taicop_teleport(c, &rb->CopPos[i]"),
    ("setrb_spot0", C,
     "    taicop_teleport(c, &rb->CopPos[i], rb->CopAng[i]);\n    tcop_set",
     "    taicop_teleport(c, &rb->CopPos[0], rb->CopAng[i]);\n    tcop_set"),
    ("setrb_ang0", C,
     "    taicop_teleport(c, &rb->CopPos[i], rb->CopAng[i]);\n    tcop_set",
     "    taicop_teleport(c, &rb->CopPos[i], rb->CopAng[0]);\n    tcop_set"),
    ("setrb_state", C,
     "    tcop_set_desired_logic_state(&c->Base, LS_ROAD_BLOCK);\n}",
     "    tcop_set_desired_logic_state(&c->Base, LS_GUARD_LOCATION);\n}"),

    # ---- IsValidPursuitTarget
    ("valid_no_player", C, "    if (car == pcar)\n        return 0;\n", ""),
    ("valid_player_nonnull", C,
     " && m->Cops[m->nPlayerCopIndex] != NULL)\n        pcar", ")\n        pcar"),
    ("valid_no_pull", C, "    if (pl[idx].bActive != 0)\n        return 0;\n",
     ""),
    ("valid_pull_byte", C, "    if (pl[idx].bActive != 0)",
     "    if ((pl[idx].bActive & 0xff) != 0)"),
    ("valid_timer_le", C, "    if (0.0f < m->fPursuableTimer[idx])",
     "    if (0.0f <= m->fPursuableTimer[idx])"),
    ("valid_timer_ne", C, "    if (0.0f < m->fPursuableTimer[idx])",
     "    if (m->fPursuableTimer[idx] != 0.0f)"),
    ("valid_no_coll", C,
     "    if (car_caused_recent_collision(car) != NULL)\n        return 1;\n",
     ""),
    ("valid_coll_0", C,
     "    if (car_caused_recent_collision(car) != NULL)\n        return 1;\n",
     "    if (car_caused_recent_collision(car) != NULL)\n        return 0;\n"),
    ("valid_no_b", C, "    if (!b)\n        return 0;\n", ""),
    ("valid_fast_le", C, "    if (COP_FAST_MPH < fabsf(",
     "    if (COP_FAST_MPH <= fabsf("),
    ("valid_fast_noabs", C,
     "fabsf(car->State.ForwardSpeed * COP_MPS_TO_MPH)",
     "(car->State.ForwardSpeed * COP_MPS_TO_MPH)"),
    ("valid_fast_0", C, "COP_MPS_TO_MPH))\n        return 1;",
     "COP_MPS_TO_MPH))\n        return 0;"),
    ("valid_no_pursued", C,
     "    return copmanager_is_being_pursued(m, car) != NULL;",
     "    return 0;"),
    ("valid_pursued_1", C,
     "    return copmanager_is_being_pursued(m, car) != NULL;",
     "    return 1;"),

    # ---- CanPatrollerSeeThisCar
    ("see_range_le", C, "    if (!(sqrtf(dx * dx + dy * dy) < COP_SIGHT_RANGE))",
     "    if (!(sqrtf(dx * dx + dy * dy) <= COP_SIGHT_RANGE))"),
    ("see_still_1", C, "    if (!(0.0f < s))\n        return 0;",
     "    if (!(0.0f < s))\n        return 1;"),
    ("see_ahead_lt", C, "COP_SIGHT_AHEAD <= vx", "COP_SIGHT_AHEAD < vx"),
    ("see_dot_x", C, "vx * inv * dx + vy * inv * dy", "vx * inv * dx"),
    ("see_dot_swap", C, "vx * inv * dx + vy * inv * dy",
     "vx * inv * dy + vy * inv * dx"),
    ("see_no_norm", C, "vx * inv * dx + vy * inv * dy", "vx * dx + vy * dy"),
    ("see_flip", C,
     "    float      dy = car->State.Position.y - mine->State.Position.y;\n"
     "    float      dx = car->State.Position.x - mine->State.Position.x;",
     "    float      dy = mine->State.Position.y - car->State.Position.y;\n"
     "    float      dx = mine->State.Position.x - car->State.Position.x;"),

    # ---- the two Init logics
    ("park_keep_lss", C,
     "    c->Base.LogicSubState = LSS_NONE;\n    car->bVisibleOnTrackMap = 0;\n"
     "    car->State.ForwardSpeed = 0.0f;\n",
     "    car->bVisibleOnTrackMap = 0;\n    car->State.ForwardSpeed = 0.0f;\n"),
    ("park_keep_vis", C,
     "    car->bVisibleOnTrackMap = 0;\n    car->State.ForwardSpeed = 0.0f;\n",
     "    car->State.ForwardSpeed = 0.0f;\n"),
    ("park_keep_fwd", C,
     "    car->State.ForwardSpeed = 0.0f;\n    ((CopDriver *)", "    ((CopDriver *)"),
    ("park_patrolling", C,
     "->State = eCDS_PARKED;\n    car->State.Velocity.x = 0.0f;",
     "->State = eCDS_PATROLLING;\n    car->State.Velocity.x = 0.0f;"),
    ("park_keep_vx", C, "    car->State.Velocity.x = 0.0f;\n", ""),
    ("park_keep_vy", C, "    car->State.Velocity.y = 0.0f;\n", ""),
    ("park_keep_vz", C, "    car->State.Velocity.z = 0.0f;\n", ""),
    ("park_keep_vmag", C, "    car->State.VelocityMagnitude = 0.0f;\n}", "}"),
    ("istrap_no_clear", C, "    taicop_clear_pursuit(c);\n    park(c);",
     "    park(c);"),
    ("istrap_timer", C, "    c->fSubStateTimer = COP_TRAP_WAIT;",
     "    c->fSubStateTimer = 10.0f;"),
    ("istrap_keep_mv", C,
     "    car->State.MatrixValid = 0;\n    set_cop_lights(car, 0);",
     "    set_cop_lights(car, 0);"),
    ("istrap_lights", C,
     "    set_cop_lights(car, 0);\n    car->TheSirenMode = SIREN_MODE_NONE;\n}\n\nvoid taicop_init_road",
     "    set_cop_lights(car, 1);\n    car->TheSirenMode = SIREN_MODE_NONE;\n}\n\nvoid taicop_init_road"),
    ("istrap_keep_siren", C,
     "    car->TheSirenMode = SIREN_MODE_NONE;\n}\n\nvoid taicop_init_road",
     "}\n\nvoid taicop_init_road"),
    ("iroad_lights", C,
     "    set_cop_lights(car, 1);\n    car->State.MatrixValid = 0;",
     "    set_cop_lights(car, 0);\n    car->State.MatrixValid = 0;"),
    ("iroad_keep_mv", C,
     "    set_cop_lights(car, 1);\n    car->State.MatrixValid = 0;",
     "    set_cop_lights(car, 1);"),
    ("iroad_keep_siren", C,
     "    car->TheSirenMode = SIREN_MODE_NONE;\n}\n\n// A car more", "}\n\n// A car more"),
    ("iroad_timer", C, "    park(c);\n    car = c->Base.pMyCar;\n    set_cop_lights(car, 1);",
     "    park(c);\n    c->fSubStateTimer = COP_TRAP_WAIT;\n    car = c->Base.pMyCar;\n"
     "    set_cop_lights(car, 1);"),
    ("iroad_clears", C, "    park(c);\n    car = c->Base.pMyCar;\n    set_cop_lights(car, 1);",
     "    taicop_clear_pursuit(c);\n    park(c);\n    car = c->Base.pMyCar;\n"
     "    set_cop_lights(car, 1);"),

    # ---- back to the spot
    ("ret_spot_le", C, "    if (!(COP_OFF_SPOT < sqrtf(", "    if (!(COP_OFF_SPOT <= sqrtf("),
    ("ret_ang_le", C, "|| COP_OFF_HEADING < da))", "|| COP_OFF_HEADING <= da))"),
    ("ret_and", C, "dy * dy) || COP_OFF_HEADING", "dy * dy) && COP_OFF_HEADING"),
    ("ret_no_abs", C, "fabsf((float)(int16_t)(uint16_t)(ang - car->State.Angle))",
     "((float)(int16_t)(uint16_t)(ang - car->State.Angle))"),
    ("ret_unsigned", C, "fabsf((float)(int16_t)(uint16_t)(ang - car->State.Angle))",
     "fabsf((float)(uint16_t)(ang - car->State.Angle))"),
    ("ret_no_can", C, "    return can_teleport(car, spot);", "    return 1;"),
    ("ret_never", C, "    return can_teleport(car, spot);", "    return 0;"),

    # ---- the search
    ("search_total", C, "    int32_t n = pCurrentWorld->CopCarPos;",
     "    int32_t n = pCurrentWorld->TotalNumCars;"),
    ("search_xy_le", C, "< COP_SEARCH_XY))", "<= COP_SEARCH_XY))"),
    ("search_z_le", C, "              < COP_SEARCH_Z))", "              <= COP_SEARCH_Z))"),
    ("search_z_noabs", C, "fabsf(o->State.Position.z - mine->State.Position.z)",
     "(o->State.Position.z - mine->State.Position.z)"),
    ("search_see_1", C, "        b = see ? taicop_can_patroller_see_this_car(c, o) : 1;",
     "        b = 1;"),
    ("search_see_0", C, "        b = see ? taicop_can_patroller_see_this_car(c, o) : 1;",
     "        b = see ? taicop_can_patroller_see_this_car(c, o) : 0;"),
    ("search_no_reqp", C,
     "            && gCopManagerRequestPursuitFn != NULL\n"
     "            && gCopManagerRequestPursuitFn(pCopManager, &c->Base, o))",
     "            && gCopManagerRequestPursuitFn != NULL)"),
    ("search_break", C,
     "            tcop_set_desired_logic_state(&c->Base, LS_HOT_PURSUIT);\n    }",
     "        {\n            tcop_set_desired_logic_state(&c->Base, LS_HOT_PURSUIT);\n"
     "            break;\n        }\n    }"),
    ("search_state", C,
     "            tcop_set_desired_logic_state(&c->Base, LS_HOT_PURSUIT);\n    }",
     "            tcop_set_desired_logic_state(&c->Base, LS_CAUGHT_SPEEDER);\n    }"),

    # ---- DoSpeedTrapLogic
    ("strap_no_hold", C,
     "    taicop_hold_position(c);\n    if (c->fSubStateTimer <= 0.0f\n",
     "    if (c->fSubStateTimer <= 0.0f\n"),
    ("strap_timer_lt", C,
     "    if (c->fSubStateTimer <= 0.0f\n        && !(world_get",
     "    if (c->fSubStateTimer < 0.0f\n        && !(world_get"),
    ("strap_no_timer", C,
     "    if (c->fSubStateTimer <= 0.0f\n        && !(world_get",
     "    if (1\n        && !(world_get"),
    ("strap_dist_le", C,
     "&c->Base.pMyCar->State.Position) < COP_FAR_FROM_PLAYERS)) {",
     "&c->Base.pMyCar->State.Position) <= COP_FAR_FROM_PLAYERS)) {"),
    ("strap_no_return", C,
     "        tcop_set_desired_logic_state(&c->Base, LS_LIMBO);\n        return;\n    }\n    t = ",
     "        tcop_set_desired_logic_state(&c->Base, LS_LIMBO);\n    }\n    t = "),
    ("strap_disabled", C,
     "        tcop_set_desired_logic_state(&c->Base, LS_LIMBO);\n        return;\n    }\n    t = ",
     "        tcop_set_desired_logic_state(&c->Base, LS_DISABLED);\n        return;\n    }\n    t = "),
    ("strap_no_tele", C,
     "        taicop_teleport(c, &c->pMySpeedTrap->v2Position,\n"
     "                        c->pMySpeedTrap->ang);\n", "        ;\n"),
    ("strap_no_search", C,
     "                        c->pMySpeedTrap->ang);\n    search(c, 0);\n}",
     "                        c->pMySpeedTrap->ang);\n}"),
    ("strap_search_see", C,
     "                        c->pMySpeedTrap->ang);\n    search(c, 0);\n}",
     "                        c->pMySpeedTrap->ang);\n    search(c, 1);\n}"),

    # ---- DoRoadBlockLogic
    ("road_no_hold", C, "    taicop_hold_position(c);\n    p = c->Base.pMyPursuit;",
     "    p = c->Base.pMyPursuit;"),
    ("road_no_rb_test", C, "    if (p != NULL && p->pRoadBlock != NULL) {",
     "    if (p != NULL) {"),
    ("road_no_grace", C, "    c->New32 = COP_ROADBLOCK_GRACE;\n}", "}"),
    ("road_grace_1", C, "    c->New32 = COP_ROADBLOCK_GRACE;\n}",
     "    c->New32 = 1.0f;\n}"),
    ("road_grace_inside", C,
     "                            rb->CopAng[c->nMyRoadBlockIndex]);\n    }\n"
     "    c->New32 = COP_ROADBLOCK_GRACE;\n}",
     "                            rb->CopAng[c->nMyRoadBlockIndex]);\n"
     "        c->New32 = COP_ROADBLOCK_GRACE;\n    }\n}"),
    ("road_spot0", C,
     "        if (should_return(c, &rb->CopPos[i], rb->CopAng[i]))",
     "        if (should_return(c, &rb->CopPos[0], rb->CopAng[0]))"),
    ("road_tele0", C,
     "            taicop_teleport(c, &rb->CopPos[c->nMyRoadBlockIndex],\n"
     "                            rb->CopAng[c->nMyRoadBlockIndex]);",
     "            taicop_teleport(c, &rb->CopPos[0],\n"
     "                            rb->CopAng[0]);"),
    ("road_no_tele", C,
     "            taicop_teleport(c, &rb->CopPos[c->nMyRoadBlockIndex],\n"
     "                            rb->CopAng[c->nMyRoadBlockIndex]);",
     "            ;"),

    # ---- DoDrivingOnPatrolLogic
    ("patrol_keep_dlx", C, "    c->MyDLOffset.x = 0.0f;\n    c->New48.y = 0.0f;\n",
     "    c->New48.y = 0.0f;\n"),
    ("patrol_keep_n48y", C,
     "    c->MyDLOffset.x = 0.0f;\n    c->New48.y = 0.0f;\n    c->New48.x = 0.0f;\n",
     "    c->MyDLOffset.x = 0.0f;\n    c->New48.x = 0.0f;\n"),
    ("patrol_keep_n48x", C,
     "    c->New48.x = 0.0f;\n    c->MyDLOffset.y = 0.0f;\n    taicop_update",
     "    c->MyDLOffset.y = 0.0f;\n    taicop_update"),
    ("patrol_keep_dly", C, "    c->MyDLOffset.y = 0.0f;\n    taicop_update_drive_target(",
     "    taicop_update_drive_target("),
    ("patrol_keep_route", C,
     "&c->Base.pMyCar->State.Position,\n        0);",
     "&c->Base.pMyCar->State.Position,\n        1);"),
    ("patrol_no_update", C,
     "    taicop_update_drive_target(\n        c, (const bVector2 *)(const void *)"
     "&c->Base.pMyCar->State.Position,\n        0);\n", ""),
    ("patrol_dist_le", C,
     "          < COP_FAR_FROM_PLAYERS)) {\n        tcop_set_desired_logic_state(&c->Base, LS_LIMBO);\n"
     "        return;\n    }\n    search(c, 1);",
     "          <= COP_FAR_FROM_PLAYERS)) {\n        tcop_set_desired_logic_state(&c->Base, LS_LIMBO);\n"
     "        return;\n    }\n    search(c, 1);"),
    ("patrol_no_return", C,
     "        tcop_set_desired_logic_state(&c->Base, LS_LIMBO);\n"
     "        return;\n    }\n    search(c, 1);",
     "        tcop_set_desired_logic_state(&c->Base, LS_LIMBO);\n"
     "    }\n    search(c, 1);"),
    ("patrol_search0", C, "    search(c, 1);\n}", "    search(c, 0);\n}"),

    # ---- reached through HandleStateTransitions and Think
    ("hst_no_istrap", C, "        taicop_init_speed_trap_logic(c);\n", ""),
    ("think_no_strap", C, "        taicop_do_speed_trap_logic(c);\n", ""),
    ("think_no_road", C, "        taicop_do_road_block_logic(c);\n", ""),
    ("think_no_patrol", C, "        taicop_do_driving_on_patrol_logic(c);\n", ""),

    # ---- coputil: CanTeleport
    ("ctele_no_car", CU,
     "    if (world_get_distance_to_closest_player_2d(\n"
     "            w, (const bVector2 *)(const void *)&car->State.Position) < 250.0f)\n"
     "        return 0;\n", ""),
    ("ctele_car_le", CU,
     "(const bVector2 *)(const void *)&car->State.Position) < 250.0f)",
     "(const bVector2 *)(const void *)&car->State.Position) <= 250.0f)"),
    ("ctele_dest_le", CU, "dest)\n        < 250.0f)", "dest)\n        <= 250.0f)"),
    ("ctele_no_dest", CU,
     "    if (world_get_distance_to_closest_player_2d(pCurrentWorld, dest)\n"
     "        < 250.0f)\n        return 0;\n", ""),
    ("ctele_self", CU, "        if (o == car)\n            continue;\n", ""),
    ("ctele_near_le", CU,
     "        dy = car->State.Position.y - o->State.Position.y;\n"
     "        if (sqrtf(dx * dx + dy * dy) < 15.0f)",
     "        dy = car->State.Position.y - o->State.Position.y;\n"
     "        if (sqrtf(dx * dx + dy * dy) <= 15.0f)"),
    ("ctele_dest_pos", CU,
     "        dx = car->State.Position.x - o->State.Position.x;",
     "        dx = dest->x - o->State.Position.x;"),
    ("ctele_coppos", CU, "    n = w->TotalNumCars;", "    n = w->CopCarPos;"),
    ("ctele_end_0", CU, "    return 1;\n}\n\n// Retail walks", "    return 0;\n}\n\n// Retail walks"),

    # ---- coputil: CarCausedRecentCollision
    ("caused_any_coll", CU,
     "collisionbody_get_collision(b, i++);\n\n            if (collision_is_two_car_collision(col)) {",
     "collisionbody_get_collision(b, i++);\n\n            if (1) {"),
    ("caused_other_c2", CU, "                other = c1 == car ? c2 : c1;",
     "                other = c2;"),
    ("caused_other_ne", CU, "                other = c1 == car ? c2 : c1;",
     "                other = c1 != car ? c2 : c1;"),
    ("caused_null_skips", CU, "        if (other == NULL)\n            return NULL;",
     "        if (other == NULL && i >= b->NumCollisions)\n            return NULL;\n"
     "        if (other == NULL)\n            continue;"),
    ("caused_no_stopped", CU,
     "        if (other->State.ForwardSpeed == 0.0f)\n            return other;\n", ""),
    ("caused_angle", CU, "car_is_car_in_front(car, other, 8192)",
     "car_is_car_in_front(car, other, 4096)"),
    ("caused_front_swap", CU, "car_is_car_in_front(car, other, 8192)",
     "car_is_car_in_front(other, car, 8192)"),
    ("caused_any_sign", CU, "            && 0.0f <= other->State.ForwardSpeed\n", ""),
    ("caused_slower_le", CU,
     "            && other->State.ForwardSpeed < car->State.ForwardSpeed)",
     "            && other->State.ForwardSpeed <= car->State.ForwardSpeed)"),
    ("caused_from1", CU,
     "Dynamic.Body;\n    int32_t        i = 0;\n\n    for (;;) {\n        Car *other = NULL;\n\n        while (i < b->",
     "Dynamic.Body;\n    int32_t        i = 1;\n\n    for (;;) {\n        Car *other = NULL;\n\n        while (i < b->"),
    ("caused_n_unsigned", CU, "        while (i < b->NumCollisions) {",
     "        while (i < (uint8_t)b->NumCollisions) {"),

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
    ("acop_substate_timer", C,
     "    c->fSubStateTimer = 0.0f;\n    c->Base.vptr = TAICOP_VTABLE;",
     "    c->Base.vptr = TAICOP_VTABLE;"),
    ("acop_no_vptr", C,
     "    c->fSubStateTimer = 0.0f;\n    c->Base.vptr = TAICOP_VTABLE;",
     "    c->fSubStateTimer = 0.0f;"),
    ("acop_clears_trap", C,
     "    c->fSubStateTimer = 0.0f;\n    c->Base.vptr = TAICOP_VTABLE;",
     "    c->fSubStateTimer = 0.0f;\n    c->pMySpeedTrap = NULL;\n"
     "    c->Base.vptr = TAICOP_VTABLE;"),
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
    ("acop_drv_state", C, "    drv->State = eCDS_PARKED;\n    drv->nCopIndex",
     "    drv->State = eCDS_PATROLLING;\n    drv->nCopIndex"),
    ("acop_drv_no_state", C, "    drv->State = eCDS_PARKED;\n    drv->nCopIndex",
     "    drv->nCopIndex"),
    ("acop_drv_index", C, "    drv->nCopIndex = c->Base.nCopNumber;",
     "    drv->nCopIndex = 0;"),
    ("acop_move_physics", C,
     "    car_set_movement_mode(car, eNO_MOVEMENT);\n    car->RenderingEnabled = 0;\n\n",
     "    car_set_movement_mode(car, COP_MOVEMENT);\n    car->RenderingEnabled = 0;\n\n"),
    ("acop_rendering", C,
     "    car->RenderingEnabled = 0;\n\n    c->fSecondsInPhysicsMode",
     "\n    c->fSecondsInPhysicsMode"),
    ("acop_phys_time", C,
     "    c->fSecondsInPhysicsMode = 0.0f;\n    c->Base.DesiredLogicState = LS_LIMBO;",
     "    c->Base.DesiredLogicState = LS_LIMBO;"),
    ("acop_desired_disabled", C, "    c->Base.DesiredLogicState = LS_LIMBO;",
     "    c->Base.DesiredLogicState = LS_DISABLED;"),
    ("acop_n52", C,
     "    c->Base.DesiredLogicState = LS_LIMBO;\n    c->New48.y = 0.0f;\n",
     "    c->Base.DesiredLogicState = LS_LIMBO;\n"),
    ("acop_n48", C,
     "    c->New48.x = 0.0f;\n    c->MyDLOffset.y = 0.0f;\n    c->MyDLOffset.x",
     "    c->MyDLOffset.y = 0.0f;\n    c->MyDLOffset.x"),
    ("acop_dl_y", C,
     "    c->MyDLOffset.y = 0.0f;\n    c->MyDLOffset.x = 0.0f;\n",
     "    c->MyDLOffset.x = 0.0f;\n"),
    ("acop_dl_x", C, "    c->MyDLOffset.x = 0.0f;\n    c->fFlankSide",
     "    c->fFlankSide"),
    ("acop_flank", C, "    c->fFlankSide = 0.0f;\n", ""),
    ("acop_delay", C,
     "    c->fMovementModeSwitchDelay = 0.0f;\n    c->nDrivingLineIndex = 0;",
     "    c->nDrivingLineIndex = 0;"),
    ("acop_line", C, "    c->nDrivingLineIndex = 0;\n    c->New64 = 6.0f;",
     "    c->New64 = 6.0f;"),
    ("acop_n64", C, "    c->New64 = 6.0f;", "    c->New64 = 3.0f;"),
    ("acop_n68", C, "    c->New68 = 3.0f;", "    c->New68 = 6.0f;"),
    ("acop_visible", C,
     "    car->bVisibleOnTrackMap = 0;\n    car->TheSirenMode = 0;",
     "    car->TheSirenMode = 0;"),
    ("acop_siren", C, "    car->TheSirenMode = 0;\n", ""),
    ("acop_lights", C, "    car->CopLights = 0;\n", ""),
    ("acop_lights_byte", C,
     "    memset(car->_hole2025, 0, sizeof car->_hole2025);\n"
     "    init_zone_permission_table();", "    init_zone_permission_table();"),
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
    ("clearp_keeps", C,
     "        gPursuitRemoveCopFromPursuitFn(c->Base.pMyPursuit, &c->Base);\n"
     "        tcop_set_pursuit(&c->Base, NULL);\n",
     "        gPursuitRemoveCopFromPursuitFn(c->Base.pMyPursuit, &c->Base);\n"),
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
    ("zone_pursuit_follow", C, "    case LSS_PURSUIT_FOLLOW:\n        return 4;",
     "    case LSS_PURSUIT_FOLLOW:\n        return 5;"),
    ("zone_offset_le", C, "        return side < 0.0f ? 3 : 5;",
     "        return side <= 0.0f ? 3 : 5;"),
    ("zone_offset_swap", C, "        return side < 0.0f ? 3 : 5;",
     "        return side < 0.0f ? 5 : 3;"),
    ("zone_offset_nan", C, "        return side < 0.0f ? 3 : 5;",
     "        return !(side >= 0.0f) ? 3 : 5;"),
    ("zone_flank_swap", C, "        return side < 0.0f ? 1 : 2;",
     "        return side < 0.0f ? 2 : 1;"),
    ("zone_flank_le", C, "        return side < 0.0f ? 1 : 2;",
     "        return side <= 0.0f ? 1 : 2;"),
    ("zone_bump_6", C, "    case LSS_FLANK:\n    case LSS_BUMP:\n",
     "    case LSS_FLANK:\n"),
    ("zone_ahead_6", C, "    case LSS_GET_AHEAD:\n        return side", "        return side"),
    ("zone_block", C, "    case LSS_BLOCK:\n        return 0;",
     "    case LSS_BLOCK:\n        return 6;"),
    ("zone_close_4", C, "    case LSS_PURSUIT_FOLLOW:\n        return 4;",
     "    case LSS_LOW_SPEED_CLOSE_FOLLOW:\n    case LSS_PURSUIT_FOLLOW:\n        return 4;"),
    ("zone_default_0", C, "        // LOW_SPEED_CLOSE_FOLLOW, FOLLOW_BACKWARDS, ACQUIRE, STOP, the rest.\n        return 6;",
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
    ("isn_dx_y", C,
     "    dx = ch->State.Position.x - mine->State.Position.x;\n    return sqrtf(dx * dx + dy * dy) < 20.0f;",
     "    dx = ch->State.Position.x - mine->State.Position.y;\n    return sqrtf(dx * dx + dy * dy) < 20.0f;"),
    ("isn_dy_x", C,
     "    dy = ch->State.Position.y - mine->State.Position.y;\n    dx = ch",
     "    dy = ch->State.Position.x - mine->State.Position.y;\n    dx = ch"),
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
    ("init_oncoming_ne", C,
     "        if (c->Base.LogicSubState == LSS_PATROL_ONCOMING)\n            ok =",
     "        if (c->Base.LogicSubState != LSS_PATROL_ONCOMING)\n            ok ="),
    ("init_oncoming_desired", C,
     "        if (c->Base.LogicSubState == LSS_PATROL_ONCOMING)\n            ok =",
     "        if (c->Base.DesiredLogicSubState == LSS_PATROL_ONCOMING)\n            ok ="),
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
    ("init_hot_desired_sub", C, "        switch (c->Base.LogicSubState) {\n        case LSS_BLOCK:",
     "        switch (c->Base.DesiredLogicSubState) {\n        case LSS_BLOCK:"),
    ("init_no_ahead", C, "        case LSS_BLOCK:\n        case LSS_GET_AHEAD:\n",
     "        case LSS_BLOCK:\n"),
    ("init_no_block", C, "        case LSS_BLOCK:\n        case LSS_GET_AHEAD:\n",
     "        case LSS_GET_AHEAD:\n"),
    ("init_oncoming_too", C, "        case LSS_BLOCK:\n        case LSS_GET_AHEAD:\n",
     "        case LSS_BLOCK:\n        case LSS_GET_AHEAD:\n        case LSS_PATROL_ONCOMING:\n"),
    ("init_stop_too", C, "        case LSS_ACQUIRE:\n",
     "        case LSS_ACQUIRE:\n        case LSS_STOP:\n"),
    ("init_acquire_chased", C,
     "            c->RouteInfo.Route = car_get_route(c->Base.pMyCar, 1);\n            car = c->Base.pMyCar;",
     "            c->RouteInfo.Route = car_get_route(c->Base.pMyPursuit->pChasedCar, 1);\n            car = c->Base.pMyCar;"),
    ("init_acquire_point_chased", C,
     "            c->RouteInfo.Route = car_get_route(c->Base.pMyCar, 1);\n            car = c->Base.pMyCar;",
     "            c->RouteInfo.Route = car_get_route(c->Base.pMyCar, 1);\n            car = c->Base.pMyPursuit->pChasedCar;"),
    ("init_acquire_find", C,
     "            c->RouteInfo.Route = car_get_route(c->Base.pMyCar, 1);",
     "            c->RouteInfo.Route = car_get_route(c->Base.pMyCar, 0);"),
    ("init_block_own", C,
     "            c->RouteInfo.Route = car_get_route(c->Base.pMyPursuit->pChasedCar,\n                                               1);\n            car = c->Base.pMyPursuit->pChasedCar;",
     "            c->RouteInfo.Route = car_get_route(c->Base.pMyCar,\n                                               1);\n            car = c->Base.pMyPursuit->pChasedCar;"),
    ("init_block_point_own", C,
     "                                               1);\n            car = c->Base.pMyPursuit->pChasedCar;",
     "                                               1);\n            car = c->Base.pMyCar;"),
    ("init_block_find", C,
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
    # ---- tAICop::Think
    ("think_n32_le", C, "    if (0.0f < c->New32)\n        c->New32 =",
     "    if (0.0f <= c->New32)\n        c->New32 ="),
    ("think_n32_always", C, "    if (0.0f < c->New32)\n        c->New32 =",
     "    if (1)\n        c->New32 ="),
    ("think_n32_plus", C, "        c->New32 = c->New32 - WorldTimeElapsed;",
     "        c->New32 = c->New32 + WorldTimeElapsed;"),
    ("think_cam_ne", C, "    if (CameraFollowThisCarInstead == car->DriverNumber)",
     "    if (CameraFollowThisCarInstead != car->DriverNumber)"),
    ("think_cam_index", C, "    if (CameraFollowThisCarInstead == car->DriverNumber)",
     "    if (CameraFollowThisCarInstead == car->CarIndex)"),
    ("think_cam_u16", C, "    if (CameraFollowThisCarInstead == car->DriverNumber)",
     "    if (CameraFollowThisCarInstead == (uint16_t)car->DriverNumber)"),
    ("think_no_mmt", C, "    taicop_movement_mode_transitions(c);\n\n    // On its side",
     "\n    // On its side"),
    ("upset_lt", C, "    if (car->State.BodyMatrix.v2.z <= COP_UPRIGHT_Z",
     "    if (car->State.BodyMatrix.v2.z < COP_UPRIGHT_Z"),
    ("upset_y", C, "    if (car->State.BodyMatrix.v2.z <= COP_UPRIGHT_Z",
     "    if (car->State.BodyMatrix.v2.y <= COP_UPRIGHT_Z"),
    ("upset_mph_le", C, "        && car->State.VelocityMagnitude * COP_MPS_TO_MPH < COP_UPSET_MPH)",
     "        && car->State.VelocityMagnitude * COP_MPS_TO_MPH <= COP_UPSET_MPH)"),
    ("upset_no_mph", C, "        && car->State.VelocityMagnitude * COP_MPS_TO_MPH < COP_UPSET_MPH)",
     "        && car->State.VelocityMagnitude < COP_UPSET_MPH)"),
    ("upset_or", C, "COP_UPRIGHT_Z\n        && car->State.VelocityMagnitude",
     "COP_UPRIGHT_Z\n        || car->State.VelocityMagnitude"),
    ("upset_flag0", C, "        taicop_disable_my_car(c, 1);\n    if (c->Base.pMyCar->BlownTireBits",
     "        taicop_disable_my_car(c, 0);\n    if (c->Base.pMyCar->BlownTireBits"),
    ("blown_flag1", C, "    if (c->Base.pMyCar->BlownTireBits != 0)\n        taicop_disable_my_car(c, 0);",
     "    if (c->Base.pMyCar->BlownTireBits != 0)\n        taicop_disable_my_car(c, 1);"),
    ("blown_ignored", C, "    if (c->Base.pMyCar->BlownTireBits != 0)\n        taicop_disable_my_car(c, 0);\n",
     ""),
    ("blown_count", C, "    if (c->Base.pMyCar->BlownTireBits != 0)",
     "    if (c->Base.pMyCar->NumBlownTires != 0)"),
    ("sst_le", C, "    if (t < 0.0f)\n        c->fSubStateTimer = 0.0f;",
     "    if (t <= 0.0f)\n        c->fSubStateTimer = 0.0f;"),
    ("sst_no_clamp", C, "    if (t < 0.0f)\n        c->fSubStateTimer = 0.0f;\n", ""),
    ("sst_no_count", C, "    t = c->fSubStateTimer - WorldTimeElapsed;",
     "    t = c->fSubStateTimer;"),
    ("think_trans_always", C,
     "    if (c->Base.LogicState != c->Base.DesiredLogicState) {\n        taicop_handle_state_transitions",
     "    {\n        taicop_handle_state_transitions"),
    ("think_trans_swapped", C,
     "        taicop_handle_state_transitions(c, c->Base.LogicState,\n                                        c->Base.DesiredLogicState);",
     "        taicop_handle_state_transitions(c, c->Base.DesiredLogicState,\n                                        c->Base.LogicState);"),
    ("think_no_state_store", C,
     "        c->Base.LogicState = c->Base.DesiredLogicState;\n    }\n    switch",
     "    }\n    switch"),
    ("think_limbo_guard", C, "    case LS_LIMBO:\n        taicop_do_limbo_logic(c);",
     "    case LS_LIMBO:\n        taicop_do_guard_location_logic(c);"),
    ("think_disabled_limbo", C, "    case LS_DISABLED:\n        taicop_do_disabled_logic(c);",
     "    case LS_DISABLED:\n        taicop_do_limbo_logic(c);"),
    ("think_strap_road", C, "        taicop_do_speed_trap_logic(c);",
     "        taicop_do_road_block_logic(c);"),
    ("think_road_patrol", C, "        taicop_do_road_block_logic(c);",
     "        taicop_do_driving_on_patrol_logic(c);"),
    ("think_patrol_hot", C, "        taicop_do_driving_on_patrol_logic(c);",
     "        taicop_do_hot_pursuit_logic(c);"),
    ("think_hot_caught", C, "        taicop_do_hot_pursuit_logic(c);",
     "        taicop_do_caught_speeder_logic(c);"),
    ("think_caught_none", C, "        taicop_do_caught_speeder_logic(c);\n",
     ""),
    ("think_guard_none", C, "    case LS_GUARD_LOCATION:\n        taicop_do_guard_location_logic(c);\n",
     "    case LS_GUARD_LOCATION:\n"),
    ("think_default_limbo", C, "        taicop_do_guard_location_logic(c);\n        break;\n    default:\n        break;",
     "        taicop_do_guard_location_logic(c);\n        break;\n    default:\n        taicop_do_limbo_logic(c);\n        break;"),
    ("ease_x_signed", C, "    if (fabsf(dx) < fabsf(sx))", "    if (dx < sx)"),
    ("ease_x_le", C, "    if (fabsf(dx) < fabsf(sx))", "    if (fabsf(dx) <= fabsf(sx))"),
    ("ease_y_le", C, "    if (fabsf(dy) < fabsf(sy))", "    if (fabsf(dy) <= fabsf(sy))"),
    ("ease_x_rate_y", C,
     "    sx = ee_mul(ee_mul(ee_div(dx, fabsf(dx)), c->New64), WorldTimeElapsed);",
     "    sx = ee_mul(ee_mul(ee_div(dx, fabsf(dx)), c->New68), WorldTimeElapsed);"),
    ("ease_y_rate_x", C,
     "    sy = ee_mul(ee_mul(ee_div(dy, fabsf(dy)), c->New68), WorldTimeElapsed);",
     "    sy = ee_mul(ee_mul(ee_div(dy, fabsf(dy)), c->New64), WorldTimeElapsed);"),
    ("ease_no_wte", C,
     "    sx = ee_mul(ee_mul(ee_div(dx, fabsf(dx)), c->New64), WorldTimeElapsed);",
     "    sx = ee_mul(ee_div(dx, fabsf(dx)), c->New64);"),
    ("ease_plain_div", C,
     "    sx = ee_mul(ee_mul(ee_div(dx, fabsf(dx)), c->New64), WorldTimeElapsed);",
     "    sx = ee_mul(ee_mul(dx / fabsf(dx), c->New64), WorldTimeElapsed);"),
    ("ease_plain_mul", C,
     "    sy = ee_mul(ee_mul(ee_div(dy, fabsf(dy)), c->New68), WorldTimeElapsed);",
     "    sy = ee_div(dy, fabsf(dy)) * c->New68 * WorldTimeElapsed;"),
    ("ease_x_always_step", C,
     "        c->New48.x = c->New48.x + dx;\n    else",
     "        c->New48.x = c->New48.x + sx;\n    else"),
    ("ease_y_always_rest", C,
     "    else\n        c->New48.y = c->New48.y + sy;",
     "    else\n        c->New48.y = c->New48.y + dy;"),
    ("ease_dy_from_x", C, "    dy = c->MyDLOffset.y - c->New48.y;",
     "    dy = c->MyDLOffset.y - c->New48.x;"),
    ("ease_dx_sign", C, "    dx = c->MyDLOffset.x - c->New48.x;",
     "    dx = c->New48.x - c->MyDLOffset.x;"),
    ("ease_n64_3", C, "    c->New64 = COP_OFFSET_RATE_X;", "    c->New64 = COP_OFFSET_RATE_Y;"),
    ("ease_n68_kept", C, "    c->New68 = COP_OFFSET_RATE_Y;\n}", "}"),
    ("ease_rate_x_5", C, "#define COP_OFFSET_RATE_X    6.0f", "#define COP_OFFSET_RATE_X    5.0f"),

    # ---- MovementModeTransitions
    ("mmt_none_runs", C,
     "    if (mode == eNO_MOVEMENT || c->Base.DesiredLogicState == LS_DISABLED)",
     "    if (c->Base.DesiredLogicState == LS_DISABLED)"),
    ("mmt_disabled_runs", C,
     "    if (mode == eNO_MOVEMENT || c->Base.DesiredLogicState == LS_DISABLED)",
     "    if (mode == eNO_MOVEMENT)"),
    ("mmt_disabled_state", C,
     "    if (mode == eNO_MOVEMENT || c->Base.DesiredLogicState == LS_DISABLED)",
     "    if (mode == eNO_MOVEMENT || c->Base.LogicState == LS_DISABLED)"),
    ("mmt_phys_minus", C, "        float t = c->fSecondsInPhysicsMode + WorldTimeElapsed;",
     "        float t = c->fSecondsInPhysicsMode - WorldTimeElapsed;"),
    ("mmt_phys_no_store", C,
     "        c->fSecondsInPhysicsMode = t;\n        if (!(0.0f <= t))",
     "        if (!(0.0f <= t))"),
    ("mmt_phys_lt", C, "        if (!(0.0f <= t))\n            return;",
     "        if (!(0.0f < t))\n            return;"),
    ("mmt_phys_nan", C, "        if (!(0.0f <= t))\n            return;",
     "        if (t < 0.0f)\n            return;"),
    ("mmt_phys_no_wait", C, "        if (!(0.0f <= t))\n            return;\n", ""),
    ("mmt_wheels_3", C, "        if (num_wheels_on_ground(car) < 4) {",
     "        if (num_wheels_on_ground(car) < 3) {"),
    ("mmt_wheels_pos", C, "        if (car->State.WheelTouchingGround[i] != 0)",
     "        if (car->State.WheelTouchingGround[i] > 0)"),
    ("mmt_wheels_3_only", C, "    for (i = 0; i < 4; i++)\n        if (car->State.WheelTouchingGround",
     "    for (i = 0; i < 3; i++)\n        if (car->State.WheelTouchingGround"),
    ("mmt_skid_le", C, "            if (COP_SKID_ANGLE < (uint16_t)off",
     "            if (COP_SKID_ANGLE <= (uint16_t)off"),
    ("mmt_skid_angle", C, "#define COP_SKID_ANGLE       1820",
     "#define COP_SKID_ANGLE       1821"),
    ("mmt_skid_or", C, "                && COP_SKID_SPEED < car->State.VelocityMagnitude)",
     "                || COP_SKID_SPEED < car->State.VelocityMagnitude)"),
    ("mmt_skid_speed_le", C, "                && COP_SKID_SPEED < car->State.VelocityMagnitude)",
     "                && COP_SKID_SPEED <= car->State.VelocityMagnitude)"),
    ("mmt_skid_speed_fwd", C, "                && COP_SKID_SPEED < car->State.VelocityMagnitude)",
     "                && COP_SKID_SPEED < car->State.ForwardSpeed)"),
    ("mmt_skid_no_abs", C, "            if (off < 0)\n                off = -off;\n", ""),
    ("mmt_skid_unsigned", C,
     "            off = (int16_t)(uint16_t)(pol.a - car->State.Angle);",
     "            off = (uint16_t)(pol.a - car->State.Angle);"),
    ("mmt_skid_steer", C,
     "            off = (int16_t)(uint16_t)(pol.a - car->State.Angle);",
     "            off = (int16_t)(uint16_t)(pol.a - car->State.SteeringAngle);"),
    ("mmt_skid_no_spin", C,
     "                reset = 1;\n            else if (COP_SPIN_RATE",
     "                reset = 1;\n            else if (0 && COP_SPIN_RATE"),
    ("mmt_spin_le", C, "            else if (COP_SPIN_RATE\n                     < sqrtf(",
     "            else if (COP_SPIN_RATE\n                     <= sqrtf("),
    ("mmt_spin_no_z", C,
     "                     < sqrtf((w->x * w->x + w->y * w->y) + w->z * w->z))",
     "                     < sqrtf(w->x * w->x + w->y * w->y))"),
    ("mmt_spin_order", C,
     "                     < sqrtf((w->x * w->x + w->y * w->y) + w->z * w->z))",
     "                     < sqrtf(w->x * w->x + (w->y * w->y + w->z * w->z)))"),
    ("mmt_no_reset_delay", C,
     "        if (reset)\n            c->fMovementModeSwitchDelay = COP_SWITCH_DELAY;\n", ""),
    ("mmt_reset_switches", C,
     "        if (reset)\n            c->fMovementModeSwitchDelay = COP_SWITCH_DELAY;\n",
     "        if (reset)\n            c->fMovementModeSwitchDelay = 0.0f;\n"),
    ("mmt_delay_lt", C, "        if (t <= 0.0f) {\n            c->fMovementModeSwitchDelay = 0.0f;",
     "        if (t < 0.0f) {\n            c->fMovementModeSwitchDelay = 0.0f;"),
    ("mmt_delay_no_count", C, "        t = c->fMovementModeSwitchDelay - WorldTimeElapsed;",
     "        t = c->fMovementModeSwitchDelay;"),
    ("mmt_delay_no_zero", C,
     "            c->fMovementModeSwitchDelay = 0.0f;\n            car_set_movement_mode(car, COP_MOVEMENT);",
     "            car_set_movement_mode(car, COP_MOVEMENT);"),
    ("mmt_switch_mellow", C,
     "            c->fMovementModeSwitchDelay = 0.0f;\n            car_set_movement_mode(car, COP_MOVEMENT);",
     "            c->fMovementModeSwitchDelay = 0.0f;\n            car_set_movement_mode(car, MELLOW_MOVEMENT);"),
    ("mmt_cop_phys_kept", C,
     "    c->fSecondsInPhysicsMode = 0.0f;\n    if (((CopMover", "    if (((CopMover"),
    ("mmt_air_ignored", C,
     "    if (((CopMover *)(void *)car->pCarMover)->bIsAirborne == 0)\n        return;\n",
     "    return;\n"),
    ("mmt_air_any", C,
     "    if (((CopMover *)(void *)car->pCarMover)->bIsAirborne == 0)\n        return;\n",
     ""),
    ("mmt_air_clamp_abs", C, "        if (COP_AIRBORNE_MAX_Z < v->z)",
     "        if (COP_AIRBORNE_MAX_Z < fabsf(v->z))"),
    ("mmt_air_no_clamp", C, "        if (COP_AIRBORNE_MAX_Z < v->z)\n            v->z = COP_AIRBORNE_MAX_Z;\n", ""),
    ("mmt_air_clamp_1", C, "#define COP_AIRBORNE_MAX_Z   2.0f", "#define COP_AIRBORNE_MAX_Z   1.0f"),
    ("mmt_air_mag_old", C,
     "        car->State.VelocityMagnitude =\n            sqrtf((v->x * v->x + v->y * v->y) + v->z * v->z);\n", ""),
    ("mmt_air_mag_2d", C,
     "            sqrtf((v->x * v->x + v->y * v->y) + v->z * v->z);",
     "            sqrtf(v->x * v->x + v->y * v->y);"),
    ("mmt_air_mv", C, "        car->State.MatrixValid = 0;\n", ""),
    ("mmt_air_delay", C,
     "        c->fMovementModeSwitchDelay = COP_SWITCH_DELAY;\n        car_set_movement_mode(car, MELLOW_MOVEMENT);",
     "        car_set_movement_mode(car, MELLOW_MOVEMENT);"),
    ("mmt_air_physics", C,
     "        c->fMovementModeSwitchDelay = COP_SWITCH_DELAY;\n        car_set_movement_mode(car, MELLOW_MOVEMENT);",
     "        c->fMovementModeSwitchDelay = COP_SWITCH_DELAY;\n        car_set_movement_mode(car, PHYSICS_MOVEMENT);"),
    ("mmt_air_gear", C, "        d->DesiredGear = AUTOMATIC;\n        d->Brake = 0.0f;",
     "        d->Brake = 0.0f;"),
    ("mmt_air_brake", C, "        d->DesiredGear = AUTOMATIC;\n        d->Brake = 0.0f;",
     "        d->DesiredGear = AUTOMATIC;"),
    ("mmt_air_throttle", C, "        d->Throttle = 1.0f;", "        d->Throttle = 0.0f;"),
    ("mmt_air_ebrake", C, "        d->Throttle = 1.0f;\n        d->EBrake = 0.0f;",
     "        d->Throttle = 1.0f;"),
    ("mmt_air_steer", C, "        d->EBrake = 0.0f;\n        d->Steering = 0;", "        d->EBrake = 0.0f;"),
    ("mmt_air_speed_vmag", C,
     "        set_desired_speed(d, car->State.ForwardSpeed, 0.5f, d->Brake);",
     "        set_desired_speed(d, car->State.VelocityMagnitude, 0.5f, d->Brake);"),
    ("mmt_air_time", C,
     "        set_desired_speed(d, car->State.ForwardSpeed, 0.5f, d->Brake);",
     "        set_desired_speed(d, car->State.ForwardSpeed, 1.0f, d->Brake);"),
    ("mmt_air_tol", C,
     "        set_desired_speed(d, car->State.ForwardSpeed, 0.5f, d->Brake);",
     "        set_desired_speed(d, car->State.ForwardSpeed, 0.5f, d->Throttle);"),

    # ---- HandleStateTransitions
    ("hst_no_sst", C, "    c->fSubStateTimer = 0.0f;\n\n    // Leaving.", "\n    // Leaving."),
    ("hst_from_disabled_kept", C,
     "    if (from == LS_DISABLED) {\n        copmanager_reset_all_damage(pCopManager, car);\n",
     "    if (from == LS_DISABLED) {\n"),
    ("hst_from_limbo_coll", C,
     "        collisionbody_enable_collisions(&car->pDynamicCollisionBody->Dynamic.Body);\n", ""),
    ("hst_from_limbo_render", C,
     "        car->RenderingEnabled = 1;\n        car_set_movement_mode(car, COP_MOVEMENT);",
     "        car_set_movement_mode(car, COP_MOVEMENT);"),
    ("hst_from_limbo_mellow", C,
     "        car->RenderingEnabled = 1;\n        car_set_movement_mode(car, COP_MOVEMENT);",
     "        car->RenderingEnabled = 1;\n        car_set_movement_mode(car, MELLOW_MOVEMENT);"),
    ("hst_from_limbo_no_reset", C,
     "        car_set_movement_mode(car, COP_MOVEMENT);\n        copmanager_reset_all_damage(pCopManager, car);\n    } else if (from == LS_SPEED_TRAP) {",
     "        car_set_movement_mode(car, COP_MOVEMENT);\n    } else if (from == LS_SPEED_TRAP) {"),
    ("hst_from_strap_kept", C,
     "    } else if (from == LS_SPEED_TRAP) {\n        taicop_clear_speed_trap(c);\n",
     "    } else if (from == LS_SPEED_TRAP) {\n"),
    ("hst_from_road_clears", C, "    } else if (from == LS_SPEED_TRAP) {",
     "    } else if (from == LS_SPEED_TRAP || from == LS_ROAD_BLOCK) {"),
    ("hst_limbo_keeps_pursuit", C,
     "    case LS_LIMBO:\n        taicop_clear_pursuit(c);\n", "    case LS_LIMBO:\n"),
    ("hst_limbo_vis", C,
     "        taicop_clear_pursuit(c);\n        car->bVisibleOnTrackMap = 0;\n        car->TheSirenMode = SIREN_MODE_NONE;\n        set_cop_lights(car, 0);\n        car_set_movement_mode(car, eNO_MOVEMENT);",
     "        taicop_clear_pursuit(c);\n        car->TheSirenMode = SIREN_MODE_NONE;\n        set_cop_lights(car, 0);\n        car_set_movement_mode(car, eNO_MOVEMENT);"),
    ("hst_limbo_siren", C,
     "        car->TheSirenMode = SIREN_MODE_NONE;\n        set_cop_lights(car, 0);\n        car_set_movement_mode(car, eNO_MOVEMENT);",
     "        set_cop_lights(car, 0);\n        car_set_movement_mode(car, eNO_MOVEMENT);"),
    ("hst_limbo_lights_byte", C,
     "        set_cop_lights(car, 0);\n        car_set_movement_mode(car, eNO_MOVEMENT);",
     "        car->CopLights = 0;\n        car_set_movement_mode(car, eNO_MOVEMENT);"),
    ("hst_limbo_move", C, "        car_set_movement_mode(car, eNO_MOVEMENT);\n        drv->State = eCDS_PARKED;",
     "        drv->State = eCDS_PARKED;"),
    ("hst_limbo_drv", C, "        car_set_movement_mode(car, eNO_MOVEMENT);\n        drv->State = eCDS_PARKED;",
     "        car_set_movement_mode(car, eNO_MOVEMENT);\n        drv->State = eCDS_DISABLED;"),
    ("hst_limbo_coll", C,
     "        collisionbody_disable_collisions(\n            &car->pDynamicCollisionBody->Dynamic.Body);\n", ""),
    ("hst_limbo_render", C,
     "        car->RenderingEnabled = 0;\n        if (from == LS_DISABLED) {",
     "        if (from == LS_DISABLED) {"),
    ("hst_limbo_from_any", C,
     "        if (from == LS_DISABLED) {\n            c->Base.LogicSubState = LSS_LIMBO_DISABLED;",
     "        if (from != LS_DISABLED) {\n            c->Base.LogicSubState = LSS_LIMBO_DISABLED;"),
    ("hst_limbo_timer", C, "            c->fSubStateTimer = 1.0f;", "            c->fSubStateTimer = 0.5f;"),
    ("hst_limbo_no_timer", C, "            c->fSubStateTimer = 1.0f;\n", ""),
    ("hst_limbo_ready", C,
     "        } else {\n            c->Base.LogicSubState = LSS_LIMBO_READY;\n        }",
     "        } else {\n            c->Base.LogicSubState = LSS_NONE;\n        }"),
    ("hst_dis_keeps_trap", C,
     "        taicop_clear_speed_trap(c);\n        taicop_clear_pursuit(c);\n        drv->State = eCDS_DISABLED;",
     "        taicop_clear_pursuit(c);\n        drv->State = eCDS_DISABLED;"),
    ("hst_dis_keeps_pursuit", C,
     "        taicop_clear_pursuit(c);\n        drv->State = eCDS_DISABLED;",
     "        drv->State = eCDS_DISABLED;"),
    ("hst_dis_drv", C, "        drv->State = eCDS_DISABLED;\n        c->Base.LogicSubState = LSS_NONE;",
     "        drv->State = eCDS_PARKED;\n        c->Base.LogicSubState = LSS_NONE;"),
    ("hst_dis_lss", C,
     "        drv->State = eCDS_DISABLED;\n        c->Base.LogicSubState = LSS_NONE;\n",
     "        drv->State = eCDS_DISABLED;\n"),
    ("hst_dis_siren", C, "        car->TheSirenMode = SIREN_MODE_BROKEN;",
     "        car->TheSirenMode = SIREN_MODE_NONE;"),
    ("hst_dis_lights", C,
     "        car->TheSirenMode = SIREN_MODE_BROKEN;\n        set_cop_lights(car, 1);",
     "        car->TheSirenMode = SIREN_MODE_BROKEN;\n        set_cop_lights(car, 2);"),
    ("hst_dis_vis", C,
     "        set_cop_lights(car, 1);\n        car->bVisibleOnTrackMap = 0;\n        car_set_movement_mode(car, MELLOW_MOVEMENT);",
     "        set_cop_lights(car, 1);\n        car_set_movement_mode(car, MELLOW_MOVEMENT);"),
    ("hst_dis_move", C,
     "        car->bVisibleOnTrackMap = 0;\n        car_set_movement_mode(car, MELLOW_MOVEMENT);\n        d = car->pCarDriver;",
     "        car->bVisibleOnTrackMap = 0;\n        d = car->pCarDriver;"),
    ("hst_dis_thr", C, "        d->Throttle = 0.0f;\n        d->Brake = COP_DISABLED_BRAKE;",
     "        d->Brake = COP_DISABLED_BRAKE;"),
    ("hst_dis_brake", C, "        d->Brake = COP_DISABLED_BRAKE;", "        d->Brake = 1.0f;"),
    ("hst_dis_ebrake", C, "        d->EBrake = 1.0f;\n        d->SportGear", "        d->EBrake = 0.0f;\n        d->SportGear"),
    ("hst_dis_sport", C, "        d->SportGear = AUTOMATIC;\n", ""),
    ("hst_dis_steer", C, "        d->SportGear = AUTOMATIC;\n        d->Steering = 0;",
     "        d->SportGear = AUTOMATIC;"),
    ("hst_dis_gear", C, "        d->Steering = 0;\n        d->DesiredGear = AUTOMATIC;\n        set_desired_speed(d, d->Throttle",
     "        d->Steering = 0;\n        set_desired_speed(d, d->Throttle"),
    ("hst_dis_speed_time", C, "        set_desired_speed(d, d->Throttle, 10.0f, d->Throttle);",
     "        set_desired_speed(d, d->Throttle, 0.5f, d->Throttle);"),
    ("hst_dis_speed_brake", C, "        set_desired_speed(d, d->Throttle, 10.0f, d->Throttle);",
     "        set_desired_speed(d, d->Brake, 10.0f, d->Throttle);"),
    ("hst_dis_no_speed", C, "        set_desired_speed(d, d->Throttle, 10.0f, d->Throttle);\n", ""),
    ("hst_strap_no_reset", C,
     "    case LS_SPEED_TRAP:\n        copmanager_reset_all_damage(pCopManager, car);\n",
     "    case LS_SPEED_TRAP:\n"),
    ("hst_strap_init_road", C,
     "        taicop_init_speed_trap_logic(c);", "        taicop_init_road_block_logic(c);"),
    ("hst_road_no_reset", C,
     "    case LS_ROAD_BLOCK:\n        copmanager_reset_all_damage(pCopManager, car);\n",
     "    case LS_ROAD_BLOCK:\n"),
    ("hst_road_init_none", C,
     "        taicop_init_road_block_logic(c);\n", ""),
    ("hst_patrol_keeps_pursuit", C,
     "    case LS_DRIVING_ON_PATROL:\n        taicop_clear_pursuit(c);\n",
     "    case LS_DRIVING_ON_PATROL:\n"),
    ("hst_patrol_vis", C,
     "        taicop_clear_pursuit(c);\n        car->bVisibleOnTrackMap = 0;\n        taicop_initialize_drive_target(c);",
     "        taicop_clear_pursuit(c);\n        taicop_initialize_drive_target(c);"),
    ("hst_patrol_no_init", C,
     "        car->bVisibleOnTrackMap = 0;\n        taicop_initialize_drive_target(c);\n",
     "        car->bVisibleOnTrackMap = 0;\n"),
    ("hst_patrol_no_update", C,
     "        taicop_update_drive_target(\n            c, (const bVector2 *)(const void *)&car->State.Position, 0);\n", ""),
    ("hst_patrol_keep", C,
     "            c, (const bVector2 *)(const void *)&car->State.Position, 0);",
     "            c, (const bVector2 *)(const void *)&car->State.Position, 1);"),
    ("hst_patrol_drv", C, "        drv->State = eCDS_PATROLLING;", "        drv->State = eCDS_PARKED;"),
    ("hst_patrol_lights", C,
     "        drv->State = eCDS_PATROLLING;\n        set_cop_lights(car, 0);\n",
     "        drv->State = eCDS_PATROLLING;\n"),
    ("hst_patrol_siren", C,
     "        set_cop_lights(car, 0);\n        car->TheSirenMode = SIREN_MODE_NONE;\n        break;\n    case LS_HOT_PURSUIT:",
     "        set_cop_lights(car, 0);\n        break;\n    case LS_HOT_PURSUIT:"),
    ("hst_hot_lights", C, "        set_cop_lights(car, 2);\n        drv->State = eCDS_PURSUIT;",
     "        set_cop_lights(car, 1);\n        drv->State = eCDS_PURSUIT;"),
    ("hst_hot_drv", C, "        drv->State = eCDS_PURSUIT;", "        drv->State = eCDS_PATROLLING;"),
    ("hst_hot_dlss", C,
     "        drv->State = eCDS_PURSUIT;\n        c->Base.DesiredLogicSubState = LSS_PURSUIT_FOLLOW;",
     "        drv->State = eCDS_PURSUIT;\n        c->Base.LogicSubState = LSS_PURSUIT_FOLLOW;"),
    ("hst_hot_siren", C, "        car->TheSirenMode = SIREN_MODE_01;", "        car->TheSirenMode = SIREN_MODE_02;"),
    ("hst_hot_vis", C,
     "        car->TheSirenMode = SIREN_MODE_01;\n        car->bVisibleOnTrackMap = 1;",
     "        car->TheSirenMode = SIREN_MODE_01;"),
    ("hst_hot_lss", C,
     "        car->bVisibleOnTrackMap = 1;\n        c->Base.LogicSubState = LSS_NONE;\n        break;\n    case LS_CAUGHT_SPEEDER:",
     "        car->bVisibleOnTrackMap = 1;\n        break;\n    case LS_CAUGHT_SPEEDER:"),
    ("hst_caught_clears", C,
     "    case LS_CAUGHT_SPEEDER:\n        tcop_set_pursuit(&c->Base, NULL);",
     "    case LS_CAUGHT_SPEEDER:\n        taicop_clear_pursuit(c);"),
    ("hst_caught_keeps", C,
     "    case LS_CAUGHT_SPEEDER:\n        tcop_set_pursuit(&c->Base, NULL);\n",
     "    case LS_CAUGHT_SPEEDER:\n"),
    ("hst_caught_drv", C,
     "        tcop_set_pursuit(&c->Base, NULL);\n        drv->State = eCDS_PARKED;",
     "        tcop_set_pursuit(&c->Base, NULL);\n        drv->State = eCDS_PURSUIT;"),
    ("hst_caught_lss", C, "        c->Base.LogicSubState = LSS_CAUGHTSPEEDER_TICKETING;",
     "        c->Base.LogicSubState = LSS_CAUGHTSPEEDER_WAITING;"),
    ("hst_caught_lights", C,
     "        c->Base.LogicSubState = LSS_CAUGHTSPEEDER_TICKETING;\n        set_cop_lights(car, 1);",
     "        c->Base.LogicSubState = LSS_CAUGHTSPEEDER_TICKETING;\n        set_cop_lights(car, 2);"),
    ("hst_caught_vis", C,
     "        set_cop_lights(car, 1);\n        car->bVisibleOnTrackMap = 1;\n        car->TheSirenMode = SIREN_MODE_NONE;\n        break;\n    case LS_GUARD",
     "        set_cop_lights(car, 1);\n        car->TheSirenMode = SIREN_MODE_NONE;\n        break;\n    case LS_GUARD"),
    ("hst_caught_siren", C,
     "        car->bVisibleOnTrackMap = 1;\n        car->TheSirenMode = SIREN_MODE_NONE;\n        break;\n    case LS_GUARD",
     "        car->bVisibleOnTrackMap = 1;\n        break;\n    case LS_GUARD"),
    ("hst_guard_keeps_trap", C,
     "    case LS_GUARD_LOCATION:\n        taicop_clear_speed_trap(c);\n",
     "    case LS_GUARD_LOCATION:\n"),
    ("hst_guard_keeps_pursuit", C,
     "        taicop_clear_speed_trap(c);\n        taicop_clear_pursuit(c);\n        copmanager_reset_all_damage(pCopManager, car);\n        drv->State = eCDS_PARKED;",
     "        taicop_clear_speed_trap(c);\n        copmanager_reset_all_damage(pCopManager, car);\n        drv->State = eCDS_PARKED;"),
    ("hst_guard_no_reset", C,
     "        copmanager_reset_all_damage(pCopManager, car);\n        drv->State = eCDS_PARKED;\n        set_cop_lights(car, 0);",
     "        drv->State = eCDS_PARKED;\n        set_cop_lights(car, 0);"),
    ("hst_guard_drv", C,
     "        drv->State = eCDS_PARKED;\n        set_cop_lights(car, 0);\n        c->Base.LogicSubState = LSS_NONE;",
     "        set_cop_lights(car, 0);\n        c->Base.LogicSubState = LSS_NONE;"),
    ("hst_guard_lights", C,
     "        set_cop_lights(car, 0);\n        c->Base.LogicSubState = LSS_NONE;\n        car->bVisibleOnTrackMap = 0;",
     "        c->Base.LogicSubState = LSS_NONE;\n        car->bVisibleOnTrackMap = 0;"),
    ("hst_guard_lss", C,
     "        c->Base.LogicSubState = LSS_NONE;\n        car->bVisibleOnTrackMap = 0;\n        car->TheSirenMode = SIREN_MODE_NONE;\n        break;\n    default:",
     "        car->bVisibleOnTrackMap = 0;\n        car->TheSirenMode = SIREN_MODE_NONE;\n        break;\n    default:"),
    ("hst_guard_vis", C,
     "        car->bVisibleOnTrackMap = 0;\n        car->TheSirenMode = SIREN_MODE_NONE;\n        break;\n    default:",
     "        car->TheSirenMode = SIREN_MODE_NONE;\n        break;\n    default:"),
    ("hst_guard_siren", C,
     "        car->bVisibleOnTrackMap = 0;\n        car->TheSirenMode = SIREN_MODE_NONE;\n        break;\n    default:",
     "        car->bVisibleOnTrackMap = 0;\n        break;\n    default:"),

    # ---- the limbo, disabled and guard logic
    ("hold_no_clear", C, "        drivetarget_clear((DriveTarget *)(void *)d, NULL, 0.0f);\n",
     "        ;\n"),
    ("hold_clear_car", C, "        drivetarget_clear((DriveTarget *)(void *)d, NULL, 0.0f);",
     "        drivetarget_clear((DriveTarget *)(void *)d, car, 0.0f);"),
    ("hold_route_0", C,
     "    drivetarget_add_point3((DriveTarget *)(void *)d, &car->State.Position, -1,\n                           -1, -1, 0, NULL);",
     "    drivetarget_add_point3((DriveTarget *)(void *)d, &car->State.Position, 0,\n                           -1, -1, 0, NULL);"),
    ("hold_check_1", C,
     "                           -1, -1, 0, NULL);",
     "                           -1, -1, 1, NULL);"),
    ("hold_car", C,
     "                           -1, -1, 0, NULL);",
     "                           -1, -1, 0, car);"),
    ("limbo_ready_any", C,
     "    if (c->Base.LogicSubState == LSS_LIMBO_DISABLED\n        && c->fSubStateTimer == 0.0f)",
     "    if (c->fSubStateTimer == 0.0f)"),
    ("limbo_ready_now", C,
     "    if (c->Base.LogicSubState == LSS_LIMBO_DISABLED\n        && c->fSubStateTimer == 0.0f)",
     "    if (c->Base.LogicSubState == LSS_LIMBO_DISABLED)"),
    ("limbo_ready_le", C, "        && c->fSubStateTimer == 0.0f)",
     "        && c->fSubStateTimer <= 0.0f)"),
    ("limbo_ready_none", C, "        c->Base.LogicSubState = LSS_LIMBO_READY;\n}",
     "        c->Base.LogicSubState = LSS_NONE;\n}"),
    ("dis_far_le", C,
     "          < COP_FAR_FROM_PLAYERS))\n        tcop_set_desired_logic_state(&c->Base, LS_LIMBO);\n}\n\nvoid taicop_do_guard",
     "          <= COP_FAR_FROM_PLAYERS))\n        tcop_set_desired_logic_state(&c->Base, LS_LIMBO);\n}\n\nvoid taicop_do_guard"),
    ("dis_far_nan", C,
     "    taicop_hold_position(c);\n    if (!(world_get_distance_to_closest_player_2d(pCurrentWorld,\n              (const bVector2 *)(const void *)&c->Base.pMyCar->State.Position)\n          < COP_FAR_FROM_PLAYERS))\n        tcop",
     "    taicop_hold_position(c);\n    if (world_get_distance_to_closest_player_2d(pCurrentWorld,\n              (const bVector2 *)(const void *)&c->Base.pMyCar->State.Position)\n          >= COP_FAR_FROM_PLAYERS)\n        tcop"),
    ("dis_far_200", C, "#define COP_FAR_FROM_PLAYERS 250.0f", "#define COP_FAR_FROM_PLAYERS 200.0f"),
    ("dis_to_patrol", C,
     "        tcop_set_desired_logic_state(&c->Base, LS_LIMBO);\n}\n\nvoid taicop_do_guard",
     "        tcop_set_desired_logic_state(&c->Base, LS_DRIVING_ON_PATROL);\n}\n\nvoid taicop_do_guard"),
    ("dis_no_hold", C,
     "void taicop_do_disabled_logic(tAICop *c)\n{\n    taicop_hold_position(c);\n",
     "void taicop_do_disabled_logic(tAICop *c)\n{\n"),
    ("guard_no_hold", C,
     "void taicop_do_guard_location_logic(tAICop *c)\n{\n    taicop_hold_position(c);\n}",
     "void taicop_do_guard_location_logic(tAICop *c)\n{\n    (void)c;\n}"),
    ("pthink_none", C,
     "    if (gPlayerCopThinkFn != NULL)\n        gPlayerCopThinkFn((tPlayerCop *)self);",
     "    (void)self;"),

    # ---- ResetAllDamage
    ("rad_rumble", M, "    car->fBlownTireControllerRumbleTimer = 0.0f;\n", ""),
    ("rad_bits", M, "    car->BlownTireBits = 0;\n    car->NumBlownTires = 0;\n",
     "    car->NumBlownTires = 0;\n"),
    ("rad_num", M, "    car->BlownTireBits = 0;\n    car->NumBlownTires = 0;\n",
     "    car->BlownTireBits = 0;\n"),
    ("rad_traction", M, "    car->fTractionBoostOverride = 1.0f;", "    car->fTractionBoostOverride = 0.0f;"),
    ("rad_cdmg_kept", M, "    m->fCarDamage[car->CarIndex] = 0.0f;\n", ""),
    ("rad_cdmg_idx0", M, "    m->fCarDamage[car->CarIndex] = 0.0f;", "    m->fCarDamage[0] = 0.0f;"),
    ("rad_no_repair", M, "        gCarDamageRepairAllFn(car->pCarDamage);\n", ""),
    ("rad_repair_any", M, "    if (car->pCarDamage != NULL) {\n        if (gCarDamageRepairAllFn == NULL) {",
     "    if (1) {\n        if (gCarDamageRepairAllFn == NULL) {"),
    ("rad_ebrake_any", M,
     "    if (car->TheControlMode == REAL_CONTROL)\n        realdriver_force_ebrake_stop",
     "    if (1)\n        realdriver_force_ebrake_stop"),
    ("rad_ebrake_never", M,
     "    if (car->TheControlMode == REAL_CONTROL)\n        realdriver_force_ebrake_stop((RealDriver *)(void *)car->pCarDriver,\n                                     0.0f);\n",
     ""),
    ("rad_ebrake_on", M,
     "car->pCarDriver,\n                                     0.0f);",
     "car->pCarDriver,\n                                     1.0f);"),
    # 12g-3: the chase.
    ("rtp_ge", C, "COP_PATROL_RACING < c->Base.pMyCar->State.ForwardSpeed",
     "COP_PATROL_RACING <= c->Base.pMyCar->State.ForwardSpeed"),
    ("rtp_swap", C, "? LSS_PATROL_RACING : LSS_PATROL_ONCOMING;",
     "? LSS_PATROL_ONCOMING : LSS_PATROL_RACING;"),
    ("rtp_ds", C,
     "    tcop_set_desired_logic_state(&c->Base, LS_DRIVING_ON_PATROL);\n    c->Base.LogicSubState =",
     "    tcop_set_desired_logic_state(&c->Base, LS_LIMBO);\n    c->Base.LogicSubState ="),
    ("bfs_lat_sign", C,
     "    lat = (ch->State.Position.x - rp->Position.x) * rp->Direction.y\n        - (ch",
     "    lat = (ch->State.Position.x - rp->Position.x) * rp->Direction.y\n        + (ch"),
    ("bfs_left_lt", C, "left = -rp->LeftWidth - lat <= -COP_LANE;",
     "left = -rp->LeftWidth - lat < -COP_LANE;"),
    ("bfs_right_lt", C, "right = COP_LANE <= rp->RightWidth - lat;",
     "right = COP_LANE < rp->RightWidth - lat;"),
    ("bfs_left_rw", C, "left = -rp->LeftWidth - lat",
     "left = -rp->RightWidth - lat"),
    ("bfs_level_le", C, "level = fabsf(local.y) < COP_FOLLOW_SIDE;",
     "level = fabsf(local.y) <= COP_FOLLOW_SIDE;"),
    ("bfs_x_le", C, "    if (local.x < 0.0f) {\n        if (left)",
     "    if (local.x <= 0.0f) {\n        if (left)"),
    ("bfs_no_level", C, "    if (level)\n        return 0.0f;\n", ""),
    ("bfs_left_first", C,
     "    if (right)\n        return 1.0f;\n    if (left)\n        return -1.0f;\n    return 0.0f;",
     "    if (left)\n        return -1.0f;\n    if (right)\n        return 1.0f;\n    return 0.0f;"),
    ("bfs_w2c_own", C,
     "                           &c->Base.pMyCar->State.Position);\n    level",
     "                           &ch->State.Position);\n    level"),
    ("bfs_no_getroute", C, "    car_get_route(ch, 1);\n", ""),
    ("bfs_rp_mine", C, "    rp = car_get_route_point(ch, 1);\n    lat",
     "    rp = car_get_route_point(c->Base.pMyCar, 1);\n    lat"),
    ("cd_dx_twice", C, "    return sqrtf(dx * dx + dy * dy);",
     "    return sqrtf(dx * dx + dx * dx);"),
    ("gap_swap", C,
     "        c->Base.pMyCar->TheTrackPathCoordinate.DistanceAroundTrack,\n        ch->TheTrackPathCoordinate.DistanceAroundTrack);",
     "        ch->TheTrackPathCoordinate.DistanceAroundTrack,\n        c->Base.pMyCar->TheTrackPathCoordinate.DistanceAroundTrack);"),
    ("mph_abs", C, "    return ch->State.ForwardSpeed * COP_MPS_TO_MPH;",
     "    return fabsf(ch->State.ForwardSpeed) * COP_MPS_TO_MPH;"),
    ("mph_vmag", C, "    return ch->State.ForwardSpeed * COP_MPS_TO_MPH;",
     "    return ch->State.VelocityMagnitude * COP_MPS_TO_MPH;"),
    ("prim_cops1", C, "    return c->Base.pMyPursuit->Cops[0] == &c->Base;",
     "    return c->Base.pMyPursuit->Cops[1] == &c->Base;"),
    ("fd_swap", C,
     "    return is_primary(c) ? COP_FOLLOW_PRIMARY : COP_FOLLOW_OTHER;",
     "    return is_primary(c) ? COP_FOLLOW_OTHER : COP_FOLLOW_PRIMARY;"),
    ("lvl_eq", C, "    return ch->pPlayer != NULL ? pCopManager->nDifficultyLevel : 2;",
     "    return ch->pPlayer == NULL ? pCopManager->nDifficultyLevel : 2;"),
    ("lvl_1", C, "    return ch->pPlayer != NULL ? pCopManager->nDifficultyLevel : 2;",
     "    return ch->pPlayer != NULL ? pCopManager->nDifficultyLevel : 1;"),
    ("ato_lt", C, "    return fabsf(c->New48.x - c->MyDLOffset.x) <= COP_AT_OFFSET",
     "    return fabsf(c->New48.x - c->MyDLOffset.x) < COP_AT_OFFSET"),
    ("ato_or", C, "        && fabsf(c->New48.y - c->MyDLOffset.y) <= COP_AT_OFFSET;",
     "        || fabsf(c->New48.y - c->MyDLOffset.y) <= COP_AT_OFFSET;"),
    ("ato_yx", C, "        && fabsf(c->New48.y - c->MyDLOffset.y) <= COP_AT_OFFSET;",
     "        && fabsf(c->New48.y - c->MyDLOffset.x) <= COP_AT_OFFSET;"),
    ("ar_sign", C, "         + car->State.Velocity.y * rp->Direction.y;",
     "         - car->State.Velocity.y * rp->Direction.y;"),
    ("ao_vsign", C, "    v.x = mine->State.Position.x - ch->State.Position.x;",
     "    v.x = ch->State.Position.x - mine->State.Position.x;"),
    ("ao_noabs", C, "    return (uint16_t)(d < 0 ? -d : d);",
     "    return (uint16_t)d;"),
    ("ao_unsigned", C, "    d = (int16_t)(uint16_t)(p.a - ch->State.Angle);",
     "    d = (uint16_t)(p.a - ch->State.Angle);"),
    ("oz_zero", C,
     "        side = ((const tAICop *)(const void *)o)->fFlankSide;",
     "        side = 0.0f;"),
    ("f_entry_sst", C,
     "        c->fSubStateTimer = COP_FOLLOW_TIME;\n        c->MyDLOffset.x = follow_distance(c);\n        c->MyDLOffset.y = 0.0f;\n    }",
     "        c->fSubStateTimer = COP_OFFSET_TIME;\n        c->MyDLOffset.x = follow_distance(c);\n        c->MyDLOffset.y = 0.0f;\n    }"),
    ("f_entry_dly", C,
     "        c->MyDLOffset.x = follow_distance(c);\n        c->MyDLOffset.y = 0.0f;\n    }",
     "        c->MyDLOffset.x = follow_distance(c);\n    }"),
    ("f_range_le", C, "    if (!(chase_distance(c, ch) < COP_FOLLOW_RANGE)) {",
     "    if (!(chase_distance(c, ch) <= COP_FOLLOW_RANGE)) {"),
    ("f_far_side", C,
     "        c->MyDLOffset.y = is_primary(c) ? 0.0f : COP_FOLLOW_SIDE;",
     "        c->MyDLOffset.y = is_primary(c) ? COP_FOLLOW_SIDE : 0.0f;"),
    ("f_far_no_sst", C,
     "        c->fSubStateTimer = COP_FOLLOW_TIME;\n        c->MyDLOffset.x = follow_distance(c);\n        c->MyDLOffset.y = is_primary",
     "        c->MyDLOffset.x = follow_distance(c);\n        c->MyDLOffset.y = is_primary"),
    ("f_far_no_return", C,
     "        c->MyDLOffset.y = is_primary(c) ? 0.0f : COP_FOLLOW_SIDE;\n        return;",
     "        c->MyDLOffset.y = is_primary(c) ? 0.0f : COP_FOLLOW_SIDE;"),
    ("f_dlx_ne", C,
     "    if (c->MyDLOffset.x == 0.0f)\n        c->MyDLOffset.x = follow_distance(c);",
     "    if (c->MyDLOffset.x != 0.0f)\n        c->MyDLOffset.x = follow_distance(c);"),
    ("f_draw_le", C, "kFlankDraw[chase_level(ch)]) < 1.0f",
     "kFlankDraw[chase_level(ch)]) <= 1.0f"),
    ("f_draw_table", C, "kFlankDraw[chase_level(ch)]) < 1.0f",
     "kBumpPush[chase_level(ch)]) < 1.0f"),
    ("f_sst_ne", C,
     "        && c->fSubStateTimer == 0.0f\n        && !did_these_cars_collide",
     "        && c->fSubStateTimer != 0.0f\n        && !did_these_cars_collide"),
    ("f_no_collide", C,
     "        && !did_these_cars_collide(c->Base.pMyCar, ch)\n        && (side",
     "        && (side"),
    ("f_side_any", C,
     "        && (side = taicop_get_best_flank_side(c, ch)) != 0.0f) {",
     "        && ((side = taicop_get_best_flank_side(c, ch)), 1)) {"),
    ("f_other_first", C,
     "        tCop     *o = p->Cops[0] == &c->Base ? p->Cops[1] : p->Cops[0];",
     "        tCop     *o = p->Cops[0];"),
    ("f_o_nocar", C, "        if (o == NULL || o->pMyCar == NULL\n",
     "        if (o == NULL\n"),
    ("f_zone_lss", C,
     "                   get_zone_from_sub_state(LSS_FOLLOW_OFFSET, side),",
     "                   get_zone_from_sub_state(LSS_FLANK, side),"),
    ("f_zone_swap", C,
     "                   get_zone_from_sub_state(LSS_FOLLOW_OFFSET, side),\n                   other_zone(o))) {",
     "                   other_zone(o),\n                   get_zone_from_sub_state(LSS_FOLLOW_OFFSET, side))) {"),
    ("f_no_flank_set", C,
     "            c->fFlankSide = side;\n            c->Base.DesiredLogicSubState = LSS_FOLLOW_OFFSET;",
     "            c->Base.DesiredLogicSubState = LSS_FOLLOW_OFFSET;"),
    ("f_slow_le", C,
     "    if (fabsf(chased_mph(ch)) < COP_CHASE_MPH)\n        c->Base.DesiredLogicSubState = LSS_LOW_SPEED_CLOSE_FOLLOW;\n}",
     "    if (fabsf(chased_mph(ch)) <= COP_CHASE_MPH)\n        c->Base.DesiredLogicSubState = LSS_LOW_SPEED_CLOSE_FOLLOW;\n}"),
    ("f_slow_noabs", C,
     "    if (fabsf(chased_mph(ch)) < COP_CHASE_MPH)\n        c->Base.DesiredLogicSubState = LSS_LOW_SPEED_CLOSE_FOLLOW;\n}",
     "    if (chased_mph(ch) < COP_CHASE_MPH)\n        c->Base.DesiredLogicSubState = LSS_LOW_SPEED_CLOSE_FOLLOW;\n}"),
    ("fo_entry_sst", C,
     "        c->fSubStateTimer = COP_OFFSET_TIME;\n    c->MyDLOffset.x = COP_FOLLOW_PRIMARY;",
     "        c->fSubStateTimer = COP_FOLLOW_TIME;\n    c->MyDLOffset.x = COP_FOLLOW_PRIMARY;"),
    ("fo_dlx", C,
     "    c->MyDLOffset.x = COP_FOLLOW_PRIMARY;\n    c->MyDLOffset.y = c->fFlankSide * COP_LANE;\n    if (taicop_get_best_flank_side(c, ch) != c->fFlankSide) {\n        c->Base.DesiredLogicSubState = LSS_PURSUIT_FOLLOW;",
     "    c->MyDLOffset.x = COP_FOLLOW_OTHER;\n    c->MyDLOffset.y = c->fFlankSide * COP_LANE;\n    if (taicop_get_best_flank_side(c, ch) != c->fFlankSide) {\n        c->Base.DesiredLogicSubState = LSS_PURSUIT_FOLLOW;"),
    ("fo_dly", C,
     "    c->MyDLOffset.y = c->fFlankSide * COP_LANE;\n    if (taicop_get_best_flank_side(c, ch) != c->fFlankSide) {\n        c->Base.DesiredLogicSubState = LSS_PURSUIT_FOLLOW;",
     "    c->MyDLOffset.y = c->fFlankSide * COP_FOLLOW_SIDE;\n    if (taicop_get_best_flank_side(c, ch) != c->fFlankSide) {\n        c->Base.DesiredLogicSubState = LSS_PURSUIT_FOLLOW;"),
    ("fo_side_no_return", C,
     "        c->Base.DesiredLogicSubState = LSS_PURSUIT_FOLLOW;\n        return;\n    }\n    if (c->fSubStateTimer != 0.0f || !at_offset(c))\n        return;\n    if (did",
     "        c->Base.DesiredLogicSubState = LSS_PURSUIT_FOLLOW;\n    }\n    if (c->fSubStateTimer != 0.0f || !at_offset(c))\n        return;\n    if (did"),
    ("fo_or_and", C,
     "    if (c->fSubStateTimer != 0.0f || !at_offset(c))\n        return;\n    if (did",
     "    if (c->fSubStateTimer != 0.0f && !at_offset(c))\n        return;\n    if (did"),
    ("fo_collide_sst", C,
     "        c->fSubStateTimer = COP_OFFSET_TIME;\n        return;\n    }\n    da = angle_off",
     "        c->fSubStateTimer = COP_FLANK_TIME;\n        return;\n    }\n    da = angle_off"),
    ("fo_collide_no_return", C,
     "        c->fSubStateTimer = COP_OFFSET_TIME;\n        return;\n    }\n    da = angle_off",
     "        c->fSubStateTimer = COP_OFFSET_TIME;\n    }\n    da = angle_off"),
    ("fo_arc_le", C, "    if (da < COP_SIDE_ARC || !(COP_DRAW_UP < r))",
     "    if (da <= COP_SIDE_ARC || !(COP_DRAW_UP < r))"),
    ("fo_r_le", C, "    if (da < COP_SIDE_ARC || !(COP_DRAW_UP < r))",
     "    if (da < COP_SIDE_ARC || !(COP_DRAW_UP <= r))"),
    ("fo_and", C, "    if (da < COP_SIDE_ARC || !(COP_DRAW_UP < r))",
     "    if (da < COP_SIDE_ARC && !(COP_DRAW_UP < r))"),
    ("fo_front_arc", C, "    if (da < COP_SIDE_ARC || !(COP_DRAW_UP < r))",
     "    if (da < COP_FRONT_ARC || !(COP_DRAW_UP < r))"),
    ("lscf_entry", C,
     "        c->MyDLOffset.y = 0.0f;\n        c->MyDLOffset.x = COP_LOW_SPEED_X;",
     "        c->MyDLOffset.y = 0.0f;\n        c->MyDLOffset.x = COP_FOLLOW_PRIMARY;"),
    ("lscf_fast_le", C, "    if (COP_CHASE_MPH < s)\n",
     "    if (COP_CHASE_MPH <= s)\n"),
    ("lscf_slow_le", C,
     "    if (s < COP_SLOW_MPH && chase_distance(c, ch) < COP_STOP_RANGE)",
     "    if (s <= COP_SLOW_MPH && chase_distance(c, ch) < COP_STOP_RANGE)"),
    ("lscf_range_le", C,
     "    if (s < COP_SLOW_MPH && chase_distance(c, ch) < COP_STOP_RANGE)",
     "    if (s < COP_SLOW_MPH && chase_distance(c, ch) <= COP_STOP_RANGE)"),
    ("lscf_noabs", C, "    s = fabsf(chased_mph(ch));", "    s = chased_mph(ch);"),
    ("fb_close_le", C,
     "        if (d < COP_CLOSE_RANGE) {\n            c->MyDLOffset.x = COP_FOLLOW_PRIMARY;",
     "        if (d <= COP_CLOSE_RANGE) {\n            c->MyDLOffset.x = COP_FOLLOW_PRIMARY;"),
    ("fb_sst_ne", C,
     "            if (c->fSubStateTimer == 0.0f) {\n                float   side",
     "            if (c->fSubStateTimer != 0.0f) {\n                float   side"),
    ("fb_rand2", C, "world_random_i(pCurrentWorld, 3);",
     "world_random_i(pCurrentWorld, 2);"),
    ("fb_sst_val", C, "                c->fSubStateTimer = COP_BACK_OFF_TIME;",
     "                c->fSubStateTimer = COP_STOP_TIME;"),
    ("fb_share_sign", C, "                c->MyDLOffset.y = kBackOffShare[i] * side;",
     "                c->MyDLOffset.y = -kBackOffShare[i] * side;"),
    ("fb_share_table", C, "                c->MyDLOffset.y = kBackOffShare[i] * side;",
     "                c->MyDLOffset.y = kFlankDraw[i] * side;"),
    ("fb_far_keep_y", C,
     "            c->MyDLOffset.x = 0.0f;\n            c->MyDLOffset.y = 0.0f;\n        }\n    } else {",
     "            c->MyDLOffset.x = 0.0f;\n        }\n    } else {"),
    ("fb_far_keep_x", C,
     "            c->MyDLOffset.x = 0.0f;\n            c->MyDLOffset.y = 0.0f;\n        }\n    } else {",
     "            c->MyDLOffset.y = 0.0f;\n        }\n    } else {"),
    ("fb_other_close", C,
     "        c->MyDLOffset.x = d < COP_CLOSE_RANGE ? COP_FOLLOW_OTHER : 0.0f;",
     "        c->MyDLOffset.x = d < COP_CLOSE_RANGE ? COP_FOLLOW_PRIMARY : 0.0f;"),
    ("fb_other_close_le", C,
     "        c->MyDLOffset.x = d < COP_CLOSE_RANGE ? COP_FOLLOW_OTHER : 0.0f;",
     "        c->MyDLOffset.x = d <= COP_CLOSE_RANGE ? COP_FOLLOW_OTHER : 0.0f;"),
    ("fb_other_side", C,
     "        c->MyDLOffset.y = COP_FOLLOW_SIDE;\n    }\n    if (fabsf(chased_mph(ch)) < COP_SLOW_MPH",
     "        c->MyDLOffset.y = -COP_FOLLOW_SIDE;\n    }\n    if (fabsf(chased_mph(ch)) < COP_SLOW_MPH"),
    ("fb_stop_le", C,
     "    if (fabsf(chased_mph(ch)) < COP_SLOW_MPH && d < COP_STOP_RANGE)",
     "    if (fabsf(chased_mph(ch)) <= COP_SLOW_MPH && d < COP_STOP_RANGE)"),
    ("fb_stop_d_le", C,
     "    if (fabsf(chased_mph(ch)) < COP_SLOW_MPH && d < COP_STOP_RANGE)",
     "    if (fabsf(chased_mph(ch)) < COP_SLOW_MPH && d <= COP_STOP_RANGE)"),
    ("fb_stop_noabs", C,
     "    if (fabsf(chased_mph(ch)) < COP_SLOW_MPH && d < COP_STOP_RANGE)",
     "    if (chased_mph(ch) < COP_SLOW_MPH && d < COP_STOP_RANGE)"),
    ("fb_way_le", C,
     "    if (COP_ITS_WAY < along_route(ch, car_get_route_point(ch, 1)))",
     "    if (COP_ITS_WAY <= along_route(ch, car_get_route_point(ch, 1)))"),
    ("fb_way_zero", C,
     "    if (COP_ITS_WAY < along_route(ch, car_get_route_point(ch, 1)))",
     "    if (0.0f < along_route(ch, car_get_route_point(ch, 1)))"),
    ("fb_order", C,
     "    if (fabsf(chased_mph(ch)) < COP_SLOW_MPH && d < COP_STOP_RANGE)\n        c->Base.DesiredLogicSubState = LSS_STOP;\n    if (COP_ITS_WAY < along_route(ch, car_get_route_point(ch, 1)))\n        c->Base.DesiredLogicSubState = LSS_PURSUIT_FOLLOW;",
     "    if (COP_ITS_WAY < along_route(ch, car_get_route_point(ch, 1)))\n        c->Base.DesiredLogicSubState = LSS_PURSUIT_FOLLOW;\n    if (fabsf(chased_mph(ch)) < COP_SLOW_MPH && d < COP_STOP_RANGE)\n        c->Base.DesiredLogicSubState = LSS_STOP;"),
    ("k_entry_dlx", C,
     "        c->MyDLOffset.x = 0.0f;\n        c->fSubStateTimer = COP_FLANK_TIME;",
     "        c->MyDLOffset.x = COP_FOLLOW_PRIMARY;\n        c->fSubStateTimer = COP_FLANK_TIME;"),
    ("k_entry_sst", C,
     "        c->MyDLOffset.x = 0.0f;\n        c->fSubStateTimer = COP_FLANK_TIME;",
     "        c->MyDLOffset.x = 0.0f;\n        c->fSubStateTimer = COP_BUMP_TIME;"),
    ("k_entry_dly", C,
     "        c->fSubStateTimer = COP_FLANK_TIME;\n        c->MyDLOffset.y = c->fFlankSide * COP_LANE;\n    }",
     "        c->fSubStateTimer = COP_FLANK_TIME;\n        c->MyDLOffset.y = c->fFlankSide * COP_FOLLOW_SIDE;\n    }"),
    ("k_side_target", C,
     "        c->Base.DesiredLogicSubState = LSS_FOLLOW_OFFSET;\n        return;\n    }\n    da = angle_off(c, ch, &r);\n    front",
     "        c->Base.DesiredLogicSubState = LSS_PURSUIT_FOLLOW;\n        return;\n    }\n    da = angle_off(c, ch, &r);\n    front"),
    ("k_side_no_return", C,
     "        c->Base.DesiredLogicSubState = LSS_FOLLOW_OFFSET;\n        return;\n    }\n    da = angle_off(c, ch, &r);\n    front",
     "        c->Base.DesiredLogicSubState = LSS_FOLLOW_OFFSET;\n    }\n    da = angle_off(c, ch, &r);\n    front"),
    ("k_front_le", C, "    front = da < COP_FRONT_ARC;",
     "    front = da <= COP_FRONT_ARC;"),
    ("k_front_side", C, "    front = da < COP_FRONT_ARC;",
     "    front = da < COP_SIDE_ARC;"),
    ("k_flag_bit", C, "            if (!(f & 4))", "            if (!(f & 2))"),
    ("k_player_nf", C,
     "            if (!(f & 4))\n                c->Base.DesiredLogicSubState = LSS_GET_AHEAD;",
     "            if (!(f & 4))\n                c->Base.DesiredLogicSubState = LSS_BUMP;"),
    ("k_rand14", C,
     "            else if ((uint32_t)world_random_i(pCurrentWorld, 15) < 2",
     "            else if ((uint32_t)world_random_i(pCurrentWorld, 14) < 2"),
    ("k_rand_lt3", C,
     "            else if ((uint32_t)world_random_i(pCurrentWorld, 15) < 2",
     "            else if ((uint32_t)world_random_i(pCurrentWorld, 15) < 3"),
    ("k_rand_lt1", C,
     "            else if ((uint32_t)world_random_i(pCurrentWorld, 15) < 2",
     "            else if ((uint32_t)world_random_i(pCurrentWorld, 15) < 1"),
    ("k_noprim", C, "                     && is_primary(c))\n", ")\n"),
    ("k_player_bump", C,
     "            else\n                c->Base.DesiredLogicSubState = LSS_BUMP;",
     "            else\n                c->Base.DesiredLogicSubState = LSS_FLANK;"),
    ("k_nonplayer_noflag", C, "        } else if (f & 4) {", "        } else {"),
    ("k_nonplayer_swap", C, "                    ? LSS_GET_AHEAD : LSS_BUMP;",
     "                    ? LSS_BUMP : LSS_GET_AHEAD;"),
    ("k_nonplayer_lt3", C,
     "                (uint32_t)world_random_i(pCurrentWorld, 15) < 2\n                    ? LSS_GET_AHEAD",
     "                (uint32_t)world_random_i(pCurrentWorld, 15) < 3\n                    ? LSS_GET_AHEAD"),
    ("k_or_and", C,
     "    if (c->fSubStateTimer != 0.0f || !at_offset(c))\n        return;\n    c->fSubStateTimer = COP_FLANK_TIME;",
     "    if (c->fSubStateTimer != 0.0f && !at_offset(c))\n        return;\n    c->fSubStateTimer = COP_FLANK_TIME;"),
    ("k_no_restart", C,
     "    c->fSubStateTimer = COP_FLANK_TIME;\n    if (!front", "    if (!front"),
    ("k_back_le", C, "    if (!front && !(da < COP_SIDE_ARC))",
     "    if (!front && !(da <= COP_SIDE_ARC))"),
    ("k_back_arc", C, "    if (!front && !(da < COP_SIDE_ARC))",
     "    if (!front && !(da < COP_FRONT_ARC + 4096))"),
    ("k_back_target", C,
     "    if (!front && !(da < COP_SIDE_ARC))\n        c->Base.DesiredLogicSubState = LSS_FOLLOW_OFFSET;",
     "    if (!front && !(da < COP_SIDE_ARC))\n        c->Base.DesiredLogicSubState = LSS_PURSUIT_FOLLOW;"),
    ("b_entry", C,
     "        c->fSubStateTimer = COP_BUMP_TIME;\n    t = c->fSubStateTimer;",
     "        c->fSubStateTimer = COP_FLANK_TIME;\n    t = c->fSubStateTimer;"),
    ("b_rate", C,
     "    c->New68 = COP_PULL_RATE;\n    c->New64 = COP_PULL_RATE;\n    s = fabsf",
     "    c->New68 = COP_PULL_RATE;\n    c->New64 = COP_LANE;\n    s = fabsf"),
    ("b_mid", C, "    s = fabsf(t - COP_BUMP_MID);", "    s = t - COP_BUMP_MID;"),
    ("b_dly", C,
     "    c->MyDLOffset.y = ((s + s) / COP_BUMP_TIME) * (c->fFlankSide * COP_LANE);",
     "    c->MyDLOffset.y = (s / COP_BUMP_TIME) * (c->fFlankSide * COP_LANE);"),
    ("b_dlx", C,
     "    c->MyDLOffset.x = 0.0f;\n    c->New68 = COP_PULL_RATE;\n    c->New64 = COP_PULL_RATE;\n    s = fabsf",
     "    c->MyDLOffset.x = 1.0f;\n    c->New68 = COP_PULL_RATE;\n    c->New64 = COP_PULL_RATE;\n    s = fabsf"),
    ("b_t_le", C,
     "    if (t == 0.0f) {\n        c->Base.DesiredLogicSubState = LSS_FLANK;",
     "    if (t <= 0.0f) {\n        c->Base.DesiredLogicSubState = LSS_FLANK;"),
    ("b_cs1", C, "    if (TheRaceParameters.CopStrength == 2\n",
     "    if (TheRaceParameters.CopStrength == 1\n"),
    ("b_cs_and", C,
     "    if (TheRaceParameters.CopStrength == 2\n        || !did_these",
     "    if (TheRaceParameters.CopStrength == 2\n        && !did_these"),
    ("b_hit_le", C, "    if (!(c->fSubStateTimer < COP_BUMP_HIT)) {",
     "    if (!(c->fSubStateTimer <= COP_BUMP_HIT)) {"),
    ("b_hit_t", C, "    if (!(c->fSubStateTimer < COP_BUMP_HIT)) {",
     "    if (!(c->fSubStateTimer < COP_BUMP_MID)) {"),
    ("b_hit_no_return", C,
     "        c->Base.DesiredLogicSubState = LSS_FLANK;\n        return;\n    }\n\n    // The VU0",
     "        c->Base.DesiredLogicSubState = LSS_FLANK;\n    }\n\n    // The VU0"),
    ("b_dir", C, "    j.x = ch->State.Position.x - mine->State.Position.x;",
     "    j.x = mine->State.Position.x - ch->State.Position.x;"),
    ("b_z0", C, "    j.z = ch->State.Position.z - mine->State.Position.z;",
     "    j.z = 0.0f;"),
    ("b_norm_noz", C, "sqrtf((j.x * j.x + j.y * j.y) + j.z * j.z)",
     "sqrtf(j.x * j.x + j.y * j.y)"),
    ("b_push", C, "    k = kBumpPush[lvl];", "    k = kFlankDraw[lvl];"),
    ("b_push_y", C, "    j.y = j.y * q * k;", "    j.y = j.y * q;"),
    ("b_at", C, "    at.x = 0.0f;\n    at.y = 0.0f;", "    at.x = 1.0f;\n    at.y = 0.0f;"),
    ("b_move", C, "    if (ch->TheMovementMode != eNO_MOVEMENT) {", "    if (1) {"),
    ("b_nophys", C,
     "        e = vt_slot(b->_vtable, COLLISIONBODY_VT_SET_TO_PHYSICS_MODE);\n        ((BodyOtherFn)e->fn)(vt_this(b, e), NULL);\n",
     ""),
    ("b_noimpulse", C,
     "        ((BodyImpulseFn)e->fn)(vt_this(b, e), &j, &at);\n", ""),
    ("b_after", C,
     "    c->Base.DesiredLogicSubState = LSS_FLANK;\n}\n\n// 0x0022fc20",
     "}\n\n// 0x0022fc20"),
    ("bl_entry_line", C,
     "        c->nDrivingLineIndex = -1;\n    }\n    c->MyDLOffset.x = 0.0f;\n    c->New68",
     "        c->nDrivingLineIndex = 0;\n    }\n    c->MyDLOffset.x = 0.0f;\n    c->New68"),
    ("bl_rate", C,
     "    c->New68 = COP_PULL_RATE;\n    c->New64 = COP_PULL_RATE;\n    c->MyDLOffset.y = 0.0f;\n    d =",
     "    c->New68 = COP_PULL_RATE;\n    c->New64 = COP_LANE;\n    c->MyDLOffset.y = 0.0f;\n    d ="),
    ("bl_dly", C,
     "    c->MyDLOffset.y = 0.0f;\n    d = chase_distance(c, ch);\n    if (track_gap",
     "    d = chase_distance(c, ch);\n    if (track_gap"),
    ("bl_gap_le", C, "    if (track_gap(c, ch) < 0.0f) {",
     "    if (track_gap(c, ch) <= 0.0f) {"),
    ("bl_vmag_fwd", C, "fabsf(ch->State.VelocityMagnitude * COP_MPS_TO_MPH)",
     "fabsf(ch->State.ForwardSpeed * COP_MPS_TO_MPH)"),
    ("bl_vmag_le", C, "        if (COP_CHASE_MPH\n                < fabsf",
     "        if (COP_CHASE_MPH\n                <= fabsf"),
    ("bl_along_le", C, "            && along_route(ch, rp) < 0.0f && COP_CLOSE_RANGE < d)",
     "            && along_route(ch, rp) <= 0.0f && COP_CLOSE_RANGE < d)"),
    ("bl_close_le", C, "            && along_route(ch, rp) < 0.0f && COP_CLOSE_RANGE < d)",
     "            && along_route(ch, rp) < 0.0f && COP_CLOSE_RANGE <= d)"),
    ("bl_lscf_le", C,
     "    if (fabsf(chased_mph(ch)) < COP_CHASE_MPH && COP_STOP_RANGE < d)",
     "    if (fabsf(chased_mph(ch)) <= COP_CHASE_MPH && COP_STOP_RANGE < d)"),
    ("bl_lscf_d_le", C,
     "    if (fabsf(chased_mph(ch)) < COP_CHASE_MPH && COP_STOP_RANGE < d)",
     "    if (fabsf(chased_mph(ch)) < COP_CHASE_MPH && COP_STOP_RANGE <= d)"),
    ("bl_else", C,
     "        c->Base.DesiredLogicSubState = LSS_PURSUIT_FOLLOW;\n    } else {\n        const TrackRoutePoint *rp",
     "        c->Base.DesiredLogicSubState = LSS_PURSUIT_FOLLOW;\n    }\n    {\n        const TrackRoutePoint *rp"),
    ("ga_always", C,
     "    if (old == c->Base.LogicSubState)\n        return;\n    c->MyDLOffset.x = 0.0f;\n    rp",
     "    c->MyDLOffset.x = 0.0f;\n    rp"),
    ("ga_rp_ch", C, "    rp = car_get_route_point(c->Base.pMyCar, 1);\n    mine",
     "    rp = car_get_route_point(ch, 1);\n    mine"),
    ("ga_line0", C, "    c->nDrivingLineIndex = -1;\n    c->MyDLOffset.y = (mine",
     "    c->nDrivingLineIndex = 0;\n    c->MyDLOffset.y = (mine"),
    ("ga_lat_sign", C,
     "                    - (mine->State.Position.y - rp->Position.y)",
     "                    + (mine->State.Position.y - rp->Position.y)"),
    ("aq_line", C, "        c->nDrivingLineIndex = 0;\n        c->MyDLOffset.x = 0.0f;",
     "        c->nDrivingLineIndex = -1;\n        c->MyDLOffset.x = 0.0f;"),
    ("aq_le", C, "    if (COP_FAR_BEHIND < track_gap(c, ch))",
     "    if (COP_FAR_BEHIND <= track_gap(c, ch))"),
    ("aq_target", C,
     "        c->Base.DesiredLogicSubState = LSS_PURSUIT_FOLLOW;\n}\n\n// 0x0022fe28",
     "        c->Base.DesiredLogicSubState = LSS_FOLLOW_OFFSET;\n}\n\n// 0x0022fe28"),
    ("st_sst", C,
     "        c->fSubStateTimer = COP_STOP_TIME;\n        c->MyDLOffset.y = 0.0f;\n    }\n    if (c->fSubStateTimer <= 0.0f",
     "        c->fSubStateTimer = COP_BUMP_HIT;\n        c->MyDLOffset.y = 0.0f;\n    }\n    if (c->fSubStateTimer <= 0.0f"),
    ("st_lt", C, "    if (c->fSubStateTimer <= 0.0f\n        && (COP_SLOW_MPH",
     "    if (c->fSubStateTimer < 0.0f\n        && (COP_SLOW_MPH"),
    ("st_mph_le", C, "        && (COP_SLOW_MPH < fabsf(chased_mph(ch))",
     "        && (COP_SLOW_MPH <= fabsf(chased_mph(ch))"),
    ("st_noabs", C, "        && (COP_SLOW_MPH < fabsf(chased_mph(ch))",
     "        && (COP_SLOW_MPH < chased_mph(ch)"),
    ("st_or_and", C, "            || COP_STOP_RANGE < chase_distance(c, ch)))",
     "            && COP_STOP_RANGE < chase_distance(c, ch)))"),
    ("st_d_le", C, "            || COP_STOP_RANGE < chase_distance(c, ch)))",
     "            || COP_STOP_RANGE <= chase_distance(c, ch)))"),
    ("h_noupdate", C,
     "    if (old != c->Base.DesiredLogicSubState)\n        c->Base.LogicSubState = c->Base.DesiredLogicSubState;\n    gap",
     "    gap"),
    ("h_giveup_lt", C, "    if (COP_GIVE_UP <= fabsf(gap)) {",
     "    if (COP_GIVE_UP < fabsf(gap)) {"),
    ("h_giveup_noabs", C, "    if (COP_GIVE_UP <= fabsf(gap)) {",
     "    if (COP_GIVE_UP <= gap) {"),
    ("h_giveup_noclear", C,
     "        taicop_return_to_patrol(c);\n        taicop_clear_pursuit(c);\n        return;",
     "        taicop_return_to_patrol(c);\n        return;"),
    ("h_giveup_no_return", C,
     "        taicop_return_to_patrol(c);\n        taicop_clear_pursuit(c);\n        return;",
     "        taicop_return_to_patrol(c);\n        taicop_clear_pursuit(c);"),
    ("h_behind_lt", C, "    if (gap <= COP_FAR_BEHIND)", "    if (gap < COP_FAR_BEHIND)"),
    ("h_ahead_lt", C, "    else if (COP_AHEAD <= gap && COP_CHASE_MPH <= chased_mph(ch))",
     "    else if (COP_AHEAD < gap && COP_CHASE_MPH <= chased_mph(ch))"),
    ("h_ahead_mph_lt", C,
     "    else if (COP_AHEAD <= gap && COP_CHASE_MPH <= chased_mph(ch))",
     "    else if (COP_AHEAD <= gap && COP_CHASE_MPH < chased_mph(ch))"),
    ("h_ahead_abs", C,
     "    else if (COP_AHEAD <= gap && COP_CHASE_MPH <= chased_mph(ch))",
     "    else if (COP_AHEAD <= gap && COP_CHASE_MPH <= fabsf(chased_mph(ch)))"),
    ("h_way_le", C,
     "            along_route(ch, car_get_route_point(ch, 1)) < 0.0f\n                ? LSS_FOLLOW_BACKWARDS",
     "            along_route(ch, car_get_route_point(ch, 1)) <= 0.0f\n                ? LSS_FOLLOW_BACKWARDS"),
    ("h_way_swap", C, "                ? LSS_FOLLOW_BACKWARDS : LSS_BLOCK;",
     "                ? LSS_BLOCK : LSS_FOLLOW_BACKWARDS;"),
    ("h_sw_follow", C, "    case LSS_PURSUIT_FOLLOW:\n        follow(c, old, ch);",
     "    case LSS_PURSUIT_FOLLOW:\n        follow_offset(c, old, ch);"),
    ("h_sw_offset", C, "        follow_offset(c, old, ch);\n        break;\n    case LSS_LOW",
     "        break;\n    case LSS_LOW"),
    ("h_sw_lscf", C, "        low_speed_close_follow(c, old, ch);\n        break;", "        break;"),
    ("h_sw_fb", C, "        follow_backwards(c, old, ch);\n        break;", "        break;"),
    ("h_sw_flank", C, "        flank(c, old, ch);\n        break;", "        bump(c, old, ch);\n        break;"),
    ("h_sw_bump", C, "        bump(c, old, ch);\n        break;", "        break;"),
    ("h_sw_block", C, "        block(c, old, ch);\n        break;", "        break;"),
    ("h_sw_get_ahead", C, "        get_ahead(c, old, ch);\n        break;", "        break;"),
    ("h_sw_acquire", C, "        acquire(c, old, ch);\n        break;", "        break;"),
    ("h_sw_stop", C, "        stop(c, old, ch);\n        break;", "        break;"),
    ("c_nohold", C,
     "    taicop_hold_position(c);\n    if (c->Base.LogicSubState != LSS_CAUGHTSPEEDER_WAITING)",
     "    if (c->Base.LogicSubState != LSS_CAUGHTSPEEDER_WAITING)"),
    ("c_lss", C,
     "    if (c->Base.LogicSubState != LSS_CAUGHTSPEEDER_WAITING)\n        return;",
     "    if (c->Base.LogicSubState != LSS_CAUGHTSPEEDER_TICKETING)\n        return;"),
    ("c_dist_le", C,
     "          < COP_FAR_FROM_PLAYERS))\n        tcop_set_desired_logic_state(&c->Base, LS_LIMBO);\n    else if",
     "          <= COP_FAR_FROM_PLAYERS))\n        tcop_set_desired_logic_state(&c->Base, LS_LIMBO);\n    else if"),
    ("c_else", C,
     "    else if (c->fSubStateTimer == 0.0f)\n        taicop_return_to_patrol(c);",
     "    if (c->fSubStateTimer == 0.0f)\n        taicop_return_to_patrol(c);"),
    ("c_sst_ne", C,
     "    else if (c->fSubStateTimer == 0.0f)\n        taicop_return_to_patrol(c);",
     "    else if (c->fSubStateTimer != 0.0f)\n        taicop_return_to_patrol(c);"),
    ("c_search1", C, "        taicop_return_to_patrol(c);\n    search(c, 0);",
     "        taicop_return_to_patrol(c);\n    search(c, 1);"),
    ("c_nosearch", C, "        taicop_return_to_patrol(c);\n    search(c, 0);",
     "        taicop_return_to_patrol(c);"),
    ("dtc_other_c2", CU, "                other = c1 == a ? c2 : c1;",
     "                other = c2;"),
    ("dtc_first_only", CU, "        if (other == b)\n            return 1;\n    }",
     "        return other == b;\n    }"),
    ("dtc_any", CU, "collisionbody_get_collision(body, i++);\n\n            if (collision_is_two_car_collision(col)) {",
     "collisionbody_get_collision(body, i++);\n\n            if (1) {"),
    ("dtc_le", CU, "        while (i < body->NumCollisions) {\n            Collision *col = collisionbody_get_collision(body, i++);\n\n            if (collision_is_two_car_collision(col)) {\n                Car *c1, *c2;",
     "        while (i <= body->NumCollisions) {\n            Collision *col = collisionbody_get_collision(body, i++);\n\n            if (collision_is_two_car_collision(col)) {\n                Car *c1, *c2;"),
]

EQUIVALENT = {
    "adtor_no_vptr": "tCop's destructor, run straight after, stores its own "
                     "table over tAICop's",
    "upd_restart_ge": "the loop's top sees n at 0 or 10 only: it goes round "
                      "again only when n is 10",
    "limbo_ready_le": "Think has just clamped fSubStateTimer to 0 or above "
                      "(or left a NaN), and HandleStateTransitions sets 0 or "
                      "1: never below 0 here",
    "bfs_left_first": "the fall-through comes with left false (x < 0) or "
                      "right false: never both true",
    "f_zone_lss": "zones 1 and 3, and 2 and 5, have the same column in "
                  "the permission table",
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
