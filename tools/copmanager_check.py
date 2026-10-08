#!/usr/bin/env python3
"""Cross-check 3DS Files/source/copmgr.c, tCopManager's building, against
the retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own copmgr.obj: LoaderCops (0x00227dc0),
UnloaderCops (0x00227e78), InitCops (0x00227c58) and so the constructor
(0x002235f8) with InitRoadBlockStructures, InitSpeedTrapStructures,
GetBaseSpeedTrapSpawnTime and ReserveCopSpeaker under it, CleanupCops
(0x00227ca0) and so the destructor (0x002239e8), the two loaded-data
lookups, the speakers' four functions, FindLandmark, and retail's new
0x002244a0 (a free pursuit id) and 0x00224560 (DeletePursuit). Then
CarCollisionBody::AddDamage (0x001d83d0), with no damage model and no
player so that only its last part runs, the cop manager's: the 1.0 gate,
the two-car scan, and MonitorImpact (0x00228310) with GetCopByCar and the
cops' own IsAIControlled under it. bATan and bToPolar run as shipped. The harness (tools/src/copmanager_test.c) runs
copmgr.c, copmanager.c, vtable.c and bmath.c and prints the same lines.

**The stubs**, logged and answered by the same rule on both sides:
bMalloc (a block of 0xcd), __builtin_delete, bNewSlotPool and
bDeleteSlotPool, the cop speech manager's AllocateVoices and FlushQueue,
GetNearestRoutePoint (a point by a hash of the position, or none),
TopologyCoordinate's constructor, HasTopology (by another hash) and
destructor, TrackPathCoordinate's constructor (a distance from the
position's bits), TrackRoutePoint::GetPosition (the along and across
offsets, mixed), World::Random, IsPointInPoly, CollisionBody::GetCollision
and Collision::IsTwoCarCollision (scripted), tAICop::DisableMyCar, and
the destructors of
tPursuit, tAICop, tPlayerCop and tSpikeStrip, reached through their
real tables (0x002bd460, 0x002bd698, 0x002bd6c0, 0x002be688).

**Compared** are the stubs' logs and, on `dump`, every field of the
manager at retail's offsets -- the 64 roadblocks and 64 speed traps
whole, the bytes retail leaves alone included -- and the three chunk
statics after each load.

**The script** loads every track's distinct cop chunk and a few made by
hand (empty, the wrong id, children out of order, one twice, an unknown
one); builds a manager on several tracks, each way round, with and
without roadblocks, as Be A Cop and not, at each cop strength, with and
without chunks; looks up every index; times the radar traps over the
race lengths at each threshold, the AI demo and SkipFE; runs the
speakers' queue round and past both ends; searches the landmarks; and
tears managers down with pursuits, cops and spike strips on them.

    python tools/copmanager_check.py
    python tools/copmanager_check.py --mutate [--only a,b]
    python tools/copmanager_check.py --dump out/copmanager
"""
import argparse
import hashlib
import os
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
SD = Path(os.environ.get("APPDATA", "")) / "Azahar" / "sdmc" / "NFSHP2"

HARNESS = "tools/src/copmanager_test.c"
COPMGR = "3DS Files/source/copmgr.c"
SOURCES = [HARNESS, COPMGR, "3DS Files/source/cop.c",
           "3DS Files/source/copmanager.c",
           "3DS Files/source/vtable.c", "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c"]
HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = retail_model.RETAIL_GP
RP = 0x0031a898                         # TheRaceParameters
TRACKLEN = 0x0031bc38                   # TheTrackPathManager.TrackLength
G_LAND = GP - 15656
G_TRAPS = GP - 15652
G_BLOCKS = GP - 15648
G_POOLS = (GP - 15644, GP - 15640, GP - 15636)
G_COPMGR = GP - 15620
G_SKIPFE = GP - 23220
G_SKIPFE_TIME = GP - 23200
G_WORLD = GP - 22120

F_LOAD = 0x00227dc0
F_UNLOAD = 0x00227e78
F_INIT = 0x00227c58
F_CLEANUP = 0x00227ca0
F_INITRB = 0x00225ec8
F_INITST = 0x002269a8
F_RB = 0x00226448
F_ST = 0x00226bb0
F_BASE = 0x00224958
F_CURRENT = 0x002254e8
F_NEXT = 0x00225550
F_RESERVE = 0x002255b8
F_RELEASE = 0x00225610
F_LANDMARK = 0x00228a58
F_FREEID = 0x002244a0
F_DELPURSUIT = 0x00224560
F_ADDDAMAGE = 0x001d83d0

S_MALLOC = 0x002577c0
S_DELETE = 0x00114e98
S_NEWPOOL = 0x00257c10
S_DELPOOL = 0x00257c48
S_VOICES = 0x0020a288
S_FLUSH = 0x0020a230
S_NRP = 0x001cb7a0
S_TOPO_CTOR = 0x00151c28
S_TOPO_HAS = 0x00152558
S_TOPO_DTOR = 0x00151c70
S_TPC_CTOR = 0x002086f0
S_TPC_DTOR = 0x00208748
S_GETPOS = 0x001c1390
S_RANDOM = 0x0014e548
S_POLY = 0x001cb1f0
S_GETCOLL = 0x001d6f38
S_TWOCAR = 0x0021eb20
S_DISABLE = 0x00230ac8

VT_PURSUIT = 0x002bd460
VT_AICOP = 0x002bd698
VT_PLAYERCOP = 0x002bd6c0
VT_SPIKE = 0x002be688
S_DTORS = {0x00229198: "pursuit", 0x0022dcc0: "aicop",
           0x0022d5b0: "playercop", 0x00241430: "spike"}

RP_FIELDS = {"TrackDirection": 12, "AIDemoMode": 24, "TimeTrialTime": 36,
             "Point2Point": 40, "NumLaps": 44, "nMaxCops": 604,
             "bRoadBlocks": 612, "BeACop": 628, "BeACopRB": 640,
             "BeACopChoppers": 644, "CopStrength": 648,
             "NumPlayerCars": 48}

# The cars and their collision bodies, at retail's offsets.
CAR_SIZE = 2304
CAR_INDEX, CAR_PLAYER, CAR_MODE, CAR_POS, CAR_DAMAGE = 8, 24, 32, 96, 2120
BODY_SIZE = 352
BODY_NCOLL, BODY_CAR = 18, 256
NCARS = 6

MGR_SIZE = 10516
PURSUIT_SIZE = 1600
COP_SIZE = 128
SPIKE_SIZE = 2304
MAX_PTS = 16
PT_SIZE = 64

CONTAINER = 0x80034500
TRAPS, BLOCKS, LAND = 0x34510, 0x34520, 0x34530


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def F(f):
    return "0x%08x" % fbits(f)


# ============================================================== the chunks

def bun_chunks():
    """Each distinct cop container on the card: (name, path, offset,
    size), the size counting its header."""
    out, seen = [], set()
    for p in sorted((SD / "TRACKS").glob("TRACKB*.BUN")):
        b = p.read_bytes()
        key = struct.pack("<I", CONTAINER)
        i = b.find(key)
        while i >= 0:
            if i % 4 == 0:
                size = struct.unpack_from("<I", b, i + 4)[0]
                q, end = i + 8, i + 8 + size
                while q < end:
                    q += 8 + struct.unpack_from("<I", b, q + 4)[0]
                if q == end:
                    h = hashlib.sha1(b[i:end]).hexdigest()
                    if h not in seen:
                        seen.add(h)
                        out.append((p.stem, p, i, size + 8))
                    break
            i = b.find(key, i + 1)
    return out


def child(cid, payload):
    return struct.pack("<II", cid, len(payload)) + payload


def container(kids, cid=CONTAINER):
    body = b"".join(kids)
    return struct.pack("<II", cid, len(body)) + body


def traps(recs):
    b = struct.pack("<I", len(recs))
    for name, x, y, a, r in recs:
        b += name.encode().ljust(16, b"\0") + struct.pack("<ffii", x, y, a, r)
    return b


def blocks(recs):
    b = struct.pack("<I", len(recs))
    for name, x, y, bits in recs:
        b += name.encode().ljust(16, b"\0") + struct.pack("<ffI", x, y, bits)
    return b


def lands(recs):
    b = struct.pack("<I", len(recs))
    for n, typ, unc in recs:
        verts = b"".join(struct.pack("<ff", 10.0 * k, -3.5 * k)
                         for k in range(6))
        b += struct.pack("<i", n) + verts + struct.pack("<ii", typ, unc)
    return b


def made_chunks():
    """Containers made by hand: (name, bytes)."""
    t = traps([("TRAP_A", 100.5, -20.25, 0, 0), ("TRAP_B", -7.0, 3.0, 1, 0),
               ("TRAP_C", 55.0, 66.0, 0, 1), ("TRAP_D", 1.0, 2.0, 1, 1),
               ("TRAP_E", -300.0, 12.5, 0, 0)])
    # Every direction, spike side, difficulty and closure, and garbage
    # above bit 6.
    bl = blocks([("RB%d" % k, 13.0 * k - 40.0, 7.5 * k + 1.0,
                  (k & 3) | ((k >> 2) & 3) << 2 | ((k >> 4) & 3) << 4
                  | ((k >> 1) & 1) << 6 | (0xabcd0000 if k & 1 else 0))
                 for k in range(24)])
    la = lands([(3, 1, 0), (4, 2, 1), (6, 3, 0), (5, 0, 1)])
    return [
        ("empty", container([])),
        ("wrongid", container([child(TRAPS, t)], cid=0x80034501)),
        ("leaf", child(TRAPS, t)),
        ("order", container([child(LAND, la), child(0x34540, b"\1\2\3\4"),
                             child(BLOCKS, bl), child(TRAPS, t)])),
        ("twice", container([child(TRAPS, traps([])), child(BLOCKS, bl),
                             child(TRAPS, t)])),
        ("landonly", container([child(LAND, la)])),
        ("notraps", container([child(TRAPS, traps([])),
                               child(BLOCKS, blocks([]))])),
        ("odd", container([child(0x34511, t), child(0x3451f, bl),
                           child(0x34531, la), child(0x80034500, b"")])),
    ]


# ================================================================== script

POINTS = [
    # x, y, dx, dy, left, right
    (0.0, 0.0, 1.0, 0.0, 4.5, 4.5),
    (10.0, -5.0, 0.0, 1.0, 3.0, 5.999),
    (-20.0, 7.0, 0.6, 0.8, 6.0, 6.0),
    (300.0, 300.0, -0.8, 0.6, 2.0, 2.0),
    (1.5, 2.5, 0.70710677, -0.70710677, 5.25, 7.75),
    (-1000.0, 50.0, -1.0, 0.0, 9.0, 0.0),
    (42.0, -42.0, 0.28, -0.96, 4.4999995, 4.5),
    (7.0, 8.0, -0.6, -0.8, 12.0, 1.0),
]


def points(pts):
    s = ["npts|%d" % len(pts)]
    for i, (x, y, dx, dy, lw, rw) in enumerate(pts):
        s.append("pt|%d|%s" % (i, "|".join(F(v) for v in
                                             (x, y, dx, dy, lw, rw))))
    return s


def rp(**kw):
    return ["rp|%s|%d" % (k, v) for k, v in kw.items()]


def track(k, **kw):
    """A manager on chunk k."""
    s = ["static|all|none", "load|%d" % k]
    s += rp(**dict(dict(TrackDirection=0, AIDemoMode=0, TimeTrialTime=0,
                        Point2Point=0, NumLaps=3, nMaxCops=4, bRoadBlocks=1,
                        BeACop=0, BeACopRB=0, BeACopChoppers=0,
                        CopStrength=1), **kw))
    return s + ["initcops", "dump"]


def lookups(n):
    return ["rb|%d" % i for i in range(n)] + ["st|%d" % i for i in range(n)]


def script(chunks, made):
    s = ["g|world|1", "g|skipfe|0", "g|skipfetime|%s" % F(1.0),
         "g|tracklen|%s" % F(5000.0), "topo|-1", "polyhit|-1"]
    s += points(POINTS)
    nb = len(chunks)
    for k, (_n, path, off, size) in enumerate(chunks):
        raw = path.read_bytes()[off:off + size]
        s.append("raw|%d|%s" % (k, raw.hex()))
    for j, (_n, raw) in enumerate(made):
        s.append("raw|%d|%s" % (nb + j, raw.hex()))
    m = {n: nb + j for j, (n, _r) in enumerate(made)}

    # ---- the loader
    s += ["static|all|none"]
    for k in range(nb + len(made)):
        s += ["load|%d" % k]
    s += ["static|all|none", "load|%d" % m["landonly"], "load|0",
          "load|%d" % m["landonly"], "unload|%d" % m["landonly"],
          "unload|%d" % m["empty"], "unload|%d" % m["wrongid"],
          "unload|%d" % m["leaf"], "unload|0", "load|%d" % m["twice"],
          "unload|%d" % m["order"], "load|%d" % m["odd"],
          "unload|%d" % m["odd"]]

    # ---- the manager on every track, forward
    for k in range(nb):
        s += track(k)
        s += lookups(64) if k < 3 else lookups(3)
        s += ["cleanup"]

    # ---- the two directions, no roadblocks, the strengths, Be A Cop
    s += track(1, TrackDirection=1) + ["cleanup"]
    s += track(1, TrackDirection=2) + ["cleanup"]
    s += track(1, TrackDirection=-1, CopStrength=0) + ["cleanup"]
    s += track(m["order"], TrackDirection=0) + lookups(26) + ["cleanup"]
    s += track(m["order"], TrackDirection=1, CopStrength=2) + lookups(26)
    s += ["cleanup"]
    s += track(2, bRoadBlocks=0, CopStrength=3) + lookups(2) + ["cleanup"]
    s += track(2, CopStrength=-1) + ["cleanup"]
    s += track(0, BeACop=1, BeACopRB=5, BeACopChoppers=2,
               TimeTrialTime=4000 * 185 + 123) + ["cleanup"]
    s += track(0, BeACop=7, BeACopRB=-1, BeACopChoppers=0,
               TimeTrialTime=-4000) + ["cleanup"]
    s += track(0, BeACop=1, TimeTrialTime=0x7fffffff) + ["cleanup"]
    s += track(0, nMaxCops=0) + ["cleanup"]
    s += track(0, nMaxCops=-3) + ["cleanup"]
    # No chunks, and chunks with nothing in them.
    s += ["static|all|none"] + rp(nMaxCops=1) + ["initcops", "dump",
                                                 "cleanup"]
    s += track(m["notraps"]) + ["cleanup"]
    s += track(m["landonly"]) + ["cleanup"]

    # ---- the route search and the topology, other ways
    s += points(POINTS[:3]) + track(0) + ["cleanup"]
    s += points([(0.0, 0.0, 1.0, 0.0, 4.5, 4.5)]) + track(m["order"])
    s += ["cleanup"]
    s += points(POINTS) + ["topo|1"] + track(1) + ["cleanup"]
    s += ["topo|0"] + track(1) + ["cleanup"]
    s += ["topo|1"] + track(m["order"]) + lookups(26) + ["cleanup", "topo|-1"]
    s += track(1) + rp(TrackDirection=1) + ["initrb", "dump", "initst",
                                            "dump"]
    s += rp(bRoadBlocks=0) + ["initrb", "dump"]
    s += ["static|all|none", "initrb", "initst", "dump", "cleanup"]

    # ---- the radar traps' first wait
    s += track(0)
    for p2p, laps, length in ((0, 3, 4999.999), (0, 3, 5000.0),
                              (1, 3, 14999.999), (1, 3, 15000.0),
                              (1, 9, 29999.998), (1, 9, 30000.0),
                              (0, 6, 5000.0), (0, 10, 2999.9998),
                              (0, 0, 1e9), (0, -2, 20000.0),
                              (0, 1, float("nan")), (0, 1, float("inf")),
                              (0, 1, -1.0)):
        s += rp(Point2Point=p2p, NumLaps=laps)
        s += ["g|tracklen|%s" % F(length), "base"]
    s += ["g|skipfetime|%s" % F(-2.5)] + rp(AIDemoMode=1)
    s += ["base", "g|skipfe|1", "base"] + rp(AIDemoMode=0)
    s += ["base", "g|skipfetime|%s" % F(7.25), "base", "g|skipfe|0",
          "g|world|0", "base", "g|world|1", "g|tracklen|%s" % F(5000.0),
          "g|skipfetime|%s" % F(1.0)]
    s += rp(Point2Point=0, NumLaps=3) + ["cleanup"]

    # ---- the speakers
    s += track(0)
    s += ["current", "reserve", "current", "reserve", "reserve", "reserve",
          "current", "reserve", "reserve", "next", "current",
          "release|7", "current", "next", "current", "release|8",
          "release|9", "release|10", "release|11", "next", "current",
          "reserve", "release|12", "next", "next", "current", "reserve",
          "reserve", "release|0xffffffff", "release|5", "current", "dump",
          "cleanup"]
    s += track(0, BeACop=1) + ["current", "next", "current", "reserve",
                               "release|3", "next", "current", "dump",
                               "cleanup"]

    # ---- the landmarks
    s += track(1)
    for hit in (-1, 0, 7, 19, 20, 50):
        s += ["polyhit|%d" % hit]
        for x, y in ((0.0, 0.0), (123.5, -77.25), (-5000.0, 3.0),
                     (1.0, 1e-30)):
            s += ["landmark|%s|%s" % (F(x), F(y))]
    s += ["polyhit|-1", "cleanup"]
    s += track(m["order"]) + ["landmark|%s|%s" % (F(1.0), F(2.0)),
                              "polyhit|3", "landmark|%s|%s" % (F(1.0),
                                                               F(2.0)),
                              "polyhit|-1", "cleanup"]

    # ---- the pursuits' ids, and tearing down
    s += track(0)
    s += ["freeid", "pursuit|0|0", "freeid", "pursuit|1|1", "pursuit|2|3",
          "freeid", "pursuit|3|2", "pursuit|4|4", "freeid", "pursuit|5|5",
          "freeid", "dump", "delpursuit|2", "freeid", "dump",
          "delpursuit|-1", "delpursuit|0", "freeid", "dump"]
    s += ["cop|0|ai", "cop|2|player", "cop|6|ai", "cop|3|ai",
          "spike|0", "spike|1", "spike|2", "new76|4", "dump", "cleanup",
          "dump"]
    s += track(0) + ["pursuit|6|5", "new76|-1", "cop|1|player", "dump",
                     "cleanup"]
    s += track(0) + ["spike|3", "cleanup"]
    s += ["cleanup"]
    s += impacts()
    return s


def impacts():
    """CarCollisionBody::AddDamage's cop part and MonitorImpact."""
    def car(k, idx, mode, x, y):
        return "car|%d|%d|%d|%s|%s" % (k, idx, mode, F(x), F(y))

    def hit(k, *amounts):
        return ["impact|%d|%s" % (k, F(f)) for f in amounts] + ["dmg"]

    def hits(k, *amounts):
        return sum((hit(k, f) for f in amounts), [])

    s = ["colls|0"]
    # An AI cop's car (A0, its New32 run out), another (A3, 2.5 s left),
    # a player cop's (A4), a racer's (A1) and an AI car's (A2).
    s += [car(0, 3, 4, 0.0, 0.0), car(1, 5, 1, 30.0, 40.0),
          car(2, 7, 2, 1.0, 1.0), car(3, 0, 4, 2.0, 2.0),
          car(4, 13, 4, 3.0, 3.0), car(5, 9, 4, 4.0, 4.0)]
    for strength in (1, 0, 2):
        s += track(0, CopStrength=strength)
        s += ["cop|0|ai", "cop|1|ai", "cop|2|player", "copcar|0|0",
              "copcar|1|3", "copcar|2|4", "copn|3",
              "copt|0|%s" % F(0.0), "copt|1|%s" % F(2.5)]
        s += hit(0, 0.5, 0.99999994, 1.0, 39.99, 40.0, 59.99, 60.0,
                 74.99, 75.0, float("nan"), float("inf"), -1e9)
        s += hit(3, 100.0) + hit(4, 100.0) + hit(1, 100.0) + hit(2, 100.0)
        s += hit(5, 100.0)
        # AddDamage's gate, seen through the scan.
        s += ["colls|1|0"] + hit(0, 0.99999994, 1.0, float("nan"), -1.0)
        # Two-car collisions, the scan stopping at the first.
        for colls in (["1", "0"], ["0", "0", "7"], ["0", "0", "0"],
                      ["0", "1", "1"], ["-1"]):
            s += ["colls|%d|%s" % (len(colls), "|".join(colls))]
            s += hit(0, 26.67, 39.99, 40.0, 50.0)
        s += ["colls|0", "copt|0|%s" % F(-0.0), "copt|1|%s" % F(-1.0)]
        s += hit(0, 100.0) + hit(3, 100.0)
        s += [car(3, 0, 1, 2.0, 2.0)] + hit(3, 100.0)
        s += [car(3, 0, 4, 2.0, 2.0), "copn|2"] + hit(3, 100.0)
        s += ["copcar|1|0"] + hit(0, 100.0) + ["copcar|1|3", "copn|3"]
        s += ["copt|0|%s" % F(1e-30), "copn|1"] + hit(0, 100.0) + hit(3, 100.0)
        s += ["copn|0"] + hit(0, 100.0) + ["cleanup"]

    # Be A Cop: the player's cop (on A0) chasing A1.
    for strength, players, idx in ((1, 1, 0), (0, 1, 3), (2, 1, 6),
                                   (1, 2, 9)):
        s += [car(1, idx, 1, 30.0, 40.0)]
        s += track(0, BeACop=1, CopStrength=strength,
                   NumPlayerCars=players)
        s += ["pursuit|7|0", "cop|0|player", "cop|1|ai", "copcar|0|0",
              "copcar|1|3", "copp|0|7", "copp|1|-1", "chase|7|1",
              "copidx|0", "copn|2"]
        s += hits(1, 100.0, 4.99)
        s += [car(1, idx + 1, 1, 29.0, 40.0)]
        s += hits(1, 4.99, 5.0, 10.0, 0.5, -30.0, 7.0, 45.0, 26.0, 39.99,
                  26.0)
        # The level's own threshold first, on a fresh slot.
        s += [car(1, idx + 2, 1, 0.0, -49.9)]
        s += hits(1, (40.0, 60.0, 75.0)[strength], 5.5, 40.0, 59.99, 75.0)
        s += [car(1, 12, 1, -20.0, 10.0)] + hit(1, 6.0, 7.5, 1e30)
        s += [car(1, 13, 1, float("nan"), 0.0)] + hit(1, 8.0)
        s += hit(2, 50.0) + hit(0, 50.0)
        s += ["copp|0|-1"] + hit(1, 50.0)
        s += ["copidx|1"] + hit(1, 50.0)
        s += ["copidx|0", "copp|0|7", "colls|2|1|1"] + hit(1, 6.0)
        s += ["colls|0", "cleanup"]
    s += [car(1, 5, 1, 30.0, 40.0)]
    s += hit(0, 100.0)[:-1]
    return s


# =================================================================== model

class Model(object):
    def __init__(self):
        e = self.e = retail_model.emu(retail=True, ieee=True)
        self.out = []
        self.names = {}
        self.chunks = {}
        self.mgrs = 0
        self.pools = 0
        self.pursuits = {}
        self.cops = {}
        self.spikes = {}
        self.npts = 0
        self.ncoll = 0
        self.topo_force = -1
        self.polyhit = -1
        self.topo = None
        self.pts = e.alloc(PT_SIZE * MAX_PTS, align=16)
        for i in range(MAX_PTS):
            self.names[self.pts + PT_SIZE * i] = "P%d" % i
        self.routes = e.alloc(64 * 3, align=16)
        for i in range(3):
            self.names[self.routes + 64 * i] = "R%d" % i
        self.world = e.alloc(64, align=16)
        self.names[self.world] = "W0"
        for a, fn in ((S_MALLOC, self.s_malloc), (S_DELETE, self.s_delete),
                      (S_NEWPOOL, self.s_newpool),
                      (S_DELPOOL, self.s_delpool),
                      (S_VOICES, self.s_voices), (S_FLUSH, self.s_flush),
                      (S_NRP, self.s_nrp), (S_TOPO_CTOR, self.s_topo_ctor),
                      (S_TOPO_HAS, self.s_topo_has),
                      (S_TOPO_DTOR, self.s_topo_dtor),
                      (S_TPC_CTOR, self.s_tpc), (S_TPC_DTOR, lambda em: 0),
                      (S_GETPOS, self.s_getpos), (S_RANDOM, self.s_random),
                      (S_POLY, self.s_poly)):
            e.stub(a, fn)
        for a, kind in S_DTORS.items():
            e.stub(a, self.dtor_stub(kind))
        self.cars = [e.alloc(CAR_SIZE, align=16) for _ in range(NCARS)]
        self.bodies = [e.alloc(BODY_SIZE, align=16) for _ in range(NCARS)]
        for k in range(NCARS):
            e.write(self.cars[k], bytes(CAR_SIZE))
            e.write(self.bodies[k], bytes(BODY_SIZE))
            e.put32(self.bodies[k] + BODY_CAR, self.cars[k])
            self.names[self.cars[k]] = "A%d" % k
        self.colls = []
        self.ktok = e.alloc(16 * 16, align=16)
        for a, fn in ((S_GETCOLL, self.s_getcoll), (S_TWOCAR, self.s_twocar),
                      (S_DISABLE, self.s_disable)):
            e.stub(a, fn)
        # InitSpeedTrapStructures never sets its route search's result
        # (sp+768) before the first search, and reads the point back
        # whether or not one was found: on a first miss retail reads
        # whatever the stack held. The port starts it at NULL, as this
        # does, so a first miss reads the direction at address 12 (zero).
        e.hook(F_INITST, self.clear_nrpi)

    def clear_nrpi(self, em):
        sp = em.reg[29] & M32
        em.put32(sp - 944 + 768, 0)
        em.put32(sp - 944 + 772, 0)

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
        for k, (base, size) in self.chunks.items():
            if base <= v < base + size:
                return "c%d+%d" % (k, v - base)
        return "?"

    # ---- stubs

    def s_malloc(self, em):
        size = s32(em.reg[4])
        name = self.cstr(em.reg[5] & M32)
        p = self.e.alloc(size, align=16)
        self.e.write(p, b"\xcd" * size)
        n = "M%d" % self.mgrs
        self.mgrs += 1
        self.names[p] = n
        self.names[p + 44] = n + ".plist"
        self.names[p + 80] = n + ".slist"
        self.emit("  malloc %d %s %d %d -> %s" % (
            size, name, s32(em.reg[6]), s32(em.reg[7]), n))
        return p

    def s_delete(self, em):
        self.emit("  delete %s" % self.sym(em.reg[4]))

    def s_newpool(self, em):
        p = self.e.alloc(64, align=16)
        n = "pool%d" % self.pools
        self.pools += 1
        self.names[p] = n
        self.emit("  newpool %d %d %s %d -> %s" % (
            s32(em.reg[4]), s32(em.reg[5]), self.cstr(em.reg[6] & M32),
            s32(em.reg[7]), n))
        return p

    def s_delpool(self, em):
        self.emit("  delpool %s" % self.sym(em.reg[4]))

    def s_voices(self, em):
        self.emit("  voices")

    def s_flush(self, em):
        self.emit("  flush")

    def s_nrp(self, em):
        e = self.e
        info, pos = em.reg[4] & M32, em.reg[5] & M32
        x, y = e.u32(pos), e.u32(pos + 4)
        line = "  nrp %08x %08x w%d f%d %08x" % (
            x, y, s32(em.reg[6]), s32(em.reg[7]), em.fpr[12] & M32)
        h = (x * 0x9E3779B1 + y) & M32
        k = (h >> 7) % (self.npts + 1)
        if k == self.npts:
            self.emit(line + " -> none")
            return 0
        e.put32(info, self.routes + 64 * (k % 3))
        e.put32(info + 4, self.pts + PT_SIZE * k)
        self.emit(line + " -> R%d P%d" % (k % 3, k))
        return 1

    def s_topo_ctor(self, em):
        self.topo = em.reg[4] & M32
        self.emit("  topo init")

    def s_topo_has(self, em):
        e = self.e
        pos = em.reg[5] & M32
        x, y = e.u32(pos), e.u32(pos + 4)
        has = ((x ^ (y >> 3) ^ 0x5bd1e995) % 7) != 0
        if self.topo_force >= 0:
            has = bool(self.topo_force)
        self.emit("  topo has %08x %08x %s -> %d" % (
            x, y, "same" if em.reg[4] & M32 == self.topo else "other",
            has))
        return int(has)

    def s_topo_dtor(self, em):
        self.emit("  topo destroy %s" % (
            "same" if em.reg[4] & M32 == self.topo else "other"))
        self.topo = None

    def s_tpc(self, em):
        e = self.e
        c, pos = em.reg[4] & M32, em.reg[5] & M32
        x, y = e.u32(pos), e.u32(pos + 4)
        e.put32(c + 20, ((x >> 1) + (y >> 2)) & 0x3fffffff)
        self.emit("  tpc %08x %08x" % (x, y))

    def s_getpos(self, em):
        e = self.e
        p, o = em.reg[4] & M32, em.reg[5] & M32
        k = (p - self.pts) // PT_SIZE
        d, l = em.fpr[12] & M32, em.fpr[13] & M32
        e.put32(o, d ^ 0x00012345)
        e.put32(o + 4, (l + 0x100 + k) & M32)
        self.emit("  getpos %s %08x %08x" % (self.sym(p), d, l))

    def s_random(self, em):
        f = em.fpr[12] & M32
        self.emit("  random %s %08x" % (self.sym(em.reg[4]), f))
        em.fpr[0] = f ^ 0x00300000

    def s_poly(self, em):
        e = self.e
        pos, verts, n = em.reg[4] & M32, em.reg[5] & M32, s32(em.reg[6])
        x, y = e.u32(pos), e.u32(pos + 4)
        land = e.u32(G_LAND)
        idx = (verts - 4 - (land + 4)) // 60
        if self.polyhit >= 0:
            inside = idx == self.polyhit
        else:
            inside = ((x + 3 * y + idx * 0x10001) & M32) % 5 == 0
        self.emit("  poly L%d n%d %08x %08x -> %d" % (idx, n, x, y, inside))
        return int(inside)

    def s_getcoll(self, em):
        i = s32(em.reg[5])
        self.emit("  getcoll %d" % i)
        return self.ktok + 16 * i

    def s_twocar(self, em):
        i = ((em.reg[4] & M32) - self.ktok) // 16
        v = self.colls[i]
        self.emit("  twocar %d -> %d" % (i, v))
        return v

    def s_disable(self, em):
        self.emit("  disable %s %d" % (self.sym(em.reg[4]), s32(em.reg[5])))

    def dtor_stub(self, kind):
        def fn(em):
            self.emit("  %s dtor %s flags %d" % (kind, self.sym(em.reg[4]),
                                                 s32(em.reg[5])))
        return fn

    def cstr(self, a):
        b = self.e.read(a, 64)
        return b.split(b"\0")[0].decode("latin-1")

    # ---- the dump

    def statics(self):
        e = self.e
        self.emit("statics traps %s blocks %s land %s" % (
            self.sym(e.u32(G_TRAPS)), self.sym(e.u32(G_BLOCKS)),
            self.sym(e.u32(G_LAND))))

    def dump(self):
        e = self.e
        m = e.u32(G_COPMGR)
        pools = " ".join(self.sym(e.u32(g)) for g in G_POOLS)
        if m == 0:
            self.emit("M none pools %s" % pools)
            return
        w = lambda o: e.u32(m + o)                      # noqa: E731
        i = lambda o: s32(e.u32(m + o))                 # noqa: E731
        o = self.emit
        o("M %s head %d %d %d %d" % (self.sym(m), i(0), i(4), i(8), i(12)))
        o("M cops %s" % " ".join(self.sym(w(16 + 4 * k)) for k in range(7)))
        o("M plist %s %s" % (self.sym(w(44)), self.sym(w(48))))
        o("M byid %s" % " ".join(self.sym(w(52 + 4 * k)) for k in range(6)))
        o("M new76 %s" % self.sym(w(76)))
        o("M slist %s %s" % (self.sym(w(80)), self.sym(w(84))))
        for k in range(8):
            b = 88 + 28 * k
            o("M pull%d %d %08x %d %s %d %d %d %d" % (
                k, i(b), w(b + 4), s32(e.u8(m + b + 8) << 24) >> 24,
                e.read(m + b + 9, 3).hex(), i(b + 12), i(b + 16),
                i(b + 20), i(b + 24)))
        o("M chopper %d nrb %d" % (i(312), i(316)))
        for k in range(64):
            b = 320 + 120 * k
            o("M rb%02d %s %s pos %s ang %08x icon %04x %04x name %s pt %s "
              "rt %s w %08x side %d belt %s pos %08x %08x D %08x %08x "
              "L %08x %08x esc %08x %08x dist %08x idx %d diff %d flags "
              "%08x spk %08x" % (
                  k, self.sym(w(b)), self.sym(w(b + 4)),
                  " ".join("%08x" % w(b + 8 + 4 * j) for j in range(4)),
                  w(b + 24), e.u16(m + b + 28), e.u16(m + b + 30),
                  self.sym(w(b + 32)), self.sym(w(b + 36)),
                  self.sym(w(b + 40)), w(b + 44), i(b + 48),
                  " ".join("%08x" % w(b + 52 + 4 * j) for j in range(4)),
                  w(b + 68), w(b + 72), w(b + 76), w(b + 80), w(b + 84),
                  w(b + 88), w(b + 92), w(b + 96), w(b + 100), i(b + 104),
                  i(b + 108), w(b + 112), w(b + 116)))
        o("M rbidx %s" % " ".join(str(i(8000 + 4 * k)) for k in range(64)))
        o("M nst %d" % i(8256))
        for k in range(64):
            b = 8260 + 28 * k
            o("M st%02d %s pos %08x %08x ang %04x %04x name %s dist %08x "
              "flags %08x" % (k, self.sym(w(b)), w(b + 4), w(b + 8),
                              e.u16(m + b + 12), e.u16(m + b + 14),
                              self.sym(w(b + 16)), w(b + 20), w(b + 24)))
        o("M stidx %s" % " ".join(str(i(10052 + 4 * k)) for k in range(64)))
        o("M spk %s %d %d %d" % (
            " ".join("%08x" % w(10308 + 4 * k) for k in range(4)),
            i(10324), i(10328), i(10332)))
        o("M id %08x speech %08x %08x %08x %08x" % (
            w(10336), w(10340), w(10344), w(10348), w(10352)))
        o("M pursuable %s" % " ".join("%08x" % w(10356 + 4 * k)
                                      for k in range(8)))
        o("M sttimer %s" % " ".join("%08x" % w(10388 + 4 * k)
                                    for k in range(8)))
        o("M dmg %s" % " ".join("%08x" % w(10420 + 4 * k)
                                for k in range(14)))
        o("M diff %d time %08x said %d n10488 %d choppers %d arrests %d "
          "n10500 %d xdim %08x ydim %08x vptr %08x" % (
              i(10476), w(10480), i(10484), i(10488), i(10492), i(10496),
              i(10500), w(10504), w(10508), w(10512)))
        o("M pools %s" % pools)

    # ---- the ops

    def link_tail(self, lst, node):
        e = self.e
        prev = e.u32(lst + 4)
        e.put32(node, lst)
        e.put32(node + 4, prev)
        e.put32(prev, node)
        e.put32(lst + 4, node)

    def op(self, a):
        e = self.e
        o = a[0]
        v = lambda j: int(a[j], 0) & M32        # noqa: E731
        m = e.u32(G_COPMGR)
        if o == "raw":
            self.put_chunk(int(a[1]), bytes.fromhex(a[2]))
        elif o in ("load", "unload"):
            k = int(a[1])
            r = e.call(F_LOAD if o == "load" else F_UNLOAD,
                       self.chunks[k][0])
            self.emit("%s c%d -> %d" % (o, k, r))
            self.statics()
        elif o == "static":
            for g in (G_TRAPS, G_BLOCKS, G_LAND):
                e.put32(g, 0)
            self.statics()
        elif o == "rp":
            e.put32(RP + RP_FIELDS[a[1]], v(2))
        elif o == "g":
            g = {"world": G_WORLD, "skipfe": G_SKIPFE,
                 "skipfetime": G_SKIPFE_TIME, "tracklen": TRACKLEN}[a[1]]
            val = v(2)
            if a[1] == "world":
                val = self.world if val else 0
            e.put32(g, val)
        elif o == "npts":
            self.npts = int(a[1])
        elif o == "pt":
            p = self.pts + PT_SIZE * int(a[1])
            x, y, dx, dy, lw, rw = (int(t, 16) for t in a[2:8])
            for off, val in ((0, x), (4, y), (12, dx), (16, dy), (24, lw),
                             (28, rw)):
                e.put32(p + off, val)
        elif o == "topo":
            self.topo_force = int(a[1])
        elif o == "polyhit":
            self.polyhit = int(a[1])
        elif o == "initcops":
            e.call(F_INIT, limit=20000000)
            self.emit("initcops -> %s" % self.sym(e.u32(G_COPMGR)))
        elif o == "dump":
            self.dump()
        elif o == "cleanup":
            e.call(F_CLEANUP, limit=2000000)
            self.emit("cleanup -> %s" % self.sym(e.u32(G_COPMGR)))
        elif o == "initrb":
            e.call(F_INITRB, m, limit=20000000)
            self.emit("initrb")
        elif o == "initst":
            e.call(F_INITST, m, limit=20000000)
            self.emit("initst")
        elif o in ("rb", "st"):
            r = e.call(F_RB if o == "rb" else F_ST, m, v(1)) & M32
            if r == 0:
                self.emit("%s %d -> none" % (o, s32(v(1))))
            else:
                # The spot the index names, however far out of the table.
                base, size, idx = ((320, 120, 8000) if o == "rb" else
                                   (8260, 28, 10052))
                k = s32(e.u32(m + idx + 4 * v(1)))
                self.emit("%s %d -> %s" % (
                    o, s32(v(1)), k if r == (m + base + size * k) & M32
                    else "?"))
        elif o == "base":
            e.call(F_BASE, m)
            self.emit("base -> %08x" % (e.fpr[0] & M32))
        elif o == "current":
            self.emit("current -> %08x" % (e.call(F_CURRENT, m) & M32))
        elif o == "reserve":
            # Empty, retail hands back its a2: 0 here, as the port does.
            self.emit("reserve -> %08x" % (e.call(F_RESERVE, m, 0, 0) & M32))
        elif o == "release":
            e.call(F_RELEASE, m, v(1))
            self.emit("release %08x" % v(1))
        elif o == "next":
            e.call(F_NEXT, m)
            self.emit("next")
        elif o == "landmark":
            pos = e.alloc(16, align=16)
            e.put32(pos, v(1))
            e.put32(pos + 4, v(2))
            r = e.call(F_LANDMARK, pos) & M32
            land = e.u32(G_LAND)
            self.emit("landmark %08x %08x -> %s" % (
                v(1), v(2), "none" if r == 0 else
                "L%d" % ((r - land - 4) // 60)))
        elif o == "freeid":
            self.emit("freeid -> %d" % e.call(F_FREEID, m))
        elif o == "pursuit":
            u, pid = int(a[1]), int(a[2])
            p = e.alloc(PURSUIT_SIZE, align=16)
            e.write(p, b"\xcd" * PURSUIT_SIZE)
            self.names[p] = "U%d" % u
            self.pursuits[u] = p
            self.link_tail(m + 44, p)
            e.write(p + 1480, bytes([pid & 0xff]))
            e.put32(p + 1592, VT_PURSUIT)
            e.put32(m + 52 + 4 * pid, p)
        elif o == "new76":
            u = int(a[1])
            e.put32(m + 76, self.pursuits[u] if u >= 0 else 0)
        elif o == "delpursuit":
            u = int(a[1])
            e.call(F_DELPURSUIT, m, self.pursuits[u] if u >= 0 else 0)
            self.emit("delpursuit %d" % u)
        elif o == "cop":
            k = int(a[1])
            c = e.alloc(COP_SIZE, align=16)
            e.write(c, b"\xcd" * COP_SIZE)
            self.names[c] = "C%d" % k
            e.put32(c + 28, VT_AICOP if a[2] == "ai" else VT_PLAYERCOP)
            e.put32(m + 16 + 4 * k, c)
        elif o == "car":
            c = self.cars[int(a[1])]
            e.write(c + CAR_INDEX, struct.pack("<h", int(a[2])))
            e.put32(c + CAR_MODE, v(3))
            e.put32(c + CAR_POS, v(4))
            e.put32(c + CAR_POS + 4, v(5))
        elif o == "copcar":
            e.put32(e.u32(m + 16 + 4 * int(a[1])) + 4, self.cars[int(a[2])])
        elif o == "copp":
            u = int(a[2])
            e.put32(e.u32(m + 16 + 4 * int(a[1])),
                    self.pursuits[u] if u >= 0 else 0)
        elif o == "copt":
            e.put32(e.u32(m + 16 + 4 * int(a[1])) + 32, v(2))
        elif o == "copn":
            e.put32(m + 8, v(1))
        elif o == "copidx":
            e.put32(m + 12, v(1))
        elif o == "chase":
            e.put32(self.pursuits[int(a[1])] + 16, self.cars[int(a[2])])
        elif o == "colls":
            self.colls = [int(t, 0) for t in a[2:]]
            self.ncoll = int(a[1])
        elif o == "impact":
            k = int(a[1])
            b = self.bodies[k]
            e.write(b + BODY_NCOLL, struct.pack("<b", self.ncoll))
            e.fpr[12] = v(2)
            e.call(F_ADDDAMAGE, b, 0, limit=200000)
            self.emit("impact A%d %08x" % (k, v(2)))
        elif o == "dmg":
            self.emit("dmg %s" % " ".join(
                "%08x" % e.u32(m + 10420 + 4 * k) for k in range(14)))
        elif o == "spike":
            k = int(a[1])
            p = e.alloc(SPIKE_SIZE, align=16)
            e.write(p, b"\xcd" * SPIKE_SIZE)
            self.names[p] = "S%d" % k
            self.link_tail(m + 80, p)
            e.put32(p + 2288, VT_SPIKE)
        else:
            raise ValueError(o)

    def put_chunk(self, k, raw):
        p = self.e.alloc(len(raw) + 16, align=16)
        self.e.write(p, raw)
        self.chunks[k] = (p, len(raw))

    def run(self, lines):
        for line in lines:
            self.op(line.split("|"))
        return self.out


def model(lines):
    return Model().run(lines)


# ================================================================== build

def build_harness(tmp, name="copmanager_test"):
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

C = COPMGR
MUTATIONS = [
    # ---- LoaderCops and UnloaderCops
    ("loader_any_id", C,
     "    if (bchunk_u32(c) != COPS_CONTAINER)\n",
     "    if (bchunk_u32(c) == 0)\n"),
    ("loader_empty_returns_0", C,
     "    if (p == end)\n        return 1;\n",
     "    if (p == end)\n        return 0;\n"),
    ("loader_empty_clears", C,
     "    if (p == end)\n        return 1;\n",
     "    if (p == end) {\n        RoadblockData = NULL;\n        return 1;\n"
     "    }\n"),
    ("unloader_keeps_traps", C,
     "traps = load ? (RadarTrapChunk *)(void *)(p + 8) : NULL;",
     "traps = load ? (RadarTrapChunk *)(void *)(p + 8) : traps;"),
    ("loader_land_header", C,
     "land = load ? (LandmarkChunk *)(void *)(p + 8) : NULL;",
     "land = load ? (LandmarkChunk *)(void *)(p + 4) : NULL;"),
    ("unloader_clears_all", C,
     "    RoadblockData = blocks;\n",
     "    RoadblockData = load ? blocks : NULL;\n"),
    ("loader_blocks_as_traps", C,
     "        if (id == COPS_ROADBLOCKS)\n",
     "        if (id == COPS_ROADBLOCKS || id == COPS_SPEEDTRAPS + 1)\n"),

    # ---- the speakers
    ("deque_empty_ignores_full", C,
     "    return d->Full == 0 && d->Tail == d->Head;",
     "    return d->Tail == d->Head;"),
    ("current_no_empty_check", C,
     "    return deque_empty(d) ? 0 : d->Data[d->Head];",
     "    return d->Data[d->Head];"),
    ("reserve_keeps_full", C,
     "    d->Full = 0;\n    return v;",
     "    return v;"),
    ("reserve_wraps_at_3", C,
     "    d->Head = d->Head + 1 == 4 ? 0 : d->Head + 1;",
     "    d->Head = d->Head + 1 == 3 ? 0 : d->Head + 1;"),
    ("release_ignores_full", C,
     "    if (d->Full != 0)\n        return;\n    d->Data[d->Tail] = v;",
     "    d->Data[d->Tail] = v;"),
    ("release_never_full", C,
     "    d->Tail = d->Tail + 1 == 4 ? 0 : d->Tail + 1;\n"
     "    d->Full = d->Tail == d->Head;",
     "    d->Tail = d->Tail + 1 == 4 ? 0 : d->Tail + 1;\n"
     "    d->Full = 0;"),
    ("next_always", C,
     "    if (!deque_empty(&m->CopSpeakers))\n",
     "    if (1)\n"),
    ("push_head_reversed", C,
     "        push_head(&m->CopSpeakers, (uint32_t)i);",
     "        push_head(&m->CopSpeakers, (uint32_t)(3 - i));"),
    ("push_head_wrap", C,
     "    d->Head = d->Head == 0 ? 3 : d->Head - 1;",
     "    d->Head = d->Head == 0 ? 2 : d->Head - 1;"),

    # ---- InitRoadBlockStructures
    ("rb_forward_not_1", C,
     "    int32_t  forward = TheRaceParameters.TrackDirection == 0;",
     "    int32_t  forward = TheRaceParameters.TrackDirection != 1;"),
    ("rb_dir3_kept", C,
     "        if (dir == 3 || (dir == 1 && !forward)",
     "        if ((dir == 1 && !forward)"),
    ("rb_dirs_swapped", C,
     "(dir == 1 && !forward) || (dir == 2 && forward)",
     "(dir == 2 && !forward) || (dir == 1 && forward)"),
    ("rb_ignores_bRoadBlocks", C,
     "    if (RoadblockData == NULL || TheRaceParameters.bRoadBlocks == 0)",
     "    if (RoadblockData == NULL)"),
    ("rb_count_not_reset", C,
     "    m->nNumRoadBlocks = 0;\n    if (RoadblockData",
     "    if (RoadblockData"),
    ("rb_index_not_cleared", C,
     "        m->RealRoadBlockIndexFromDataIndex[i] = -1;\n",
     "        m->RealRoadBlockIndexFromDataIndex[i] = 0;\n"),
    ("rb_width_le", C,
     "        if (rb->fRoadWidth < 9.0f)",
     "        if (rb->fRoadWidth <= 9.0f)"),
    ("rb_width_checked_first", C,
     "        rb->Route = nrpi.Route;\n        rb->RoutePoint = nrpi.Point;\n"
     "        rb->fRoadWidth = pt->LeftWidth + pt->RightWidth;\n"
     "        if (rb->fRoadWidth < 9.0f)\n            continue;\n",
     "        if (pt->LeftWidth + pt->RightWidth < 9.0f)\n            continue;\n"
     "        rb->Route = nrpi.Route;\n        rb->RoutePoint = nrpi.Point;\n"
     "        rb->fRoadWidth = pt->LeftWidth + pt->RightWidth;\n"),
    ("rb_topo_miss_not_destroyed", C,
     "        if (topology_has_topology(&tc, &info->Centre) == 0) {\n"
     "            topology_destroy(&tc);\n            continue;\n",
     "        if (topology_has_topology(&tc, &info->Centre) == 0) {\n"
     "            continue;\n"),
    ("rb_name_next", C,
     "        rb->Name = info;",
     "        rb->Name = info + 1;"),
    ("rb_spikeside_is_difficulty", C,
     "        rb->nSpikeSide = (int32_t)ROADBLOCKINFO_SPIKESIDE(info->Bits);",
     "        rb->nSpikeSide = (int32_t)ROADBLOCKINFO_DIFFICULTY(info->Bits);"),
    ("rb_index_is_n", C,
     "        rb->nIndexIntoLoadedData = (int32_t)i;",
     "        rb->nIndexIntoLoadedData = n;"),
    ("rb_flags_not_cleared", C,
     "        rb->Flags = 0;\n        rb->Difficulty",
     "        rb->Difficulty"),
    ("rb_closure_flag_3", C,
     "            rb->Flags = 1;",
     "            rb->Flags = 3;"),
    ("rb_real_index_is_i", C,
     "        m->RealRoadBlockIndexFromDataIndex[i] = n;",
     "        m->RealRoadBlockIndexFromDataIndex[i] = (int32_t)i;"),
    ("rb_along_minus", C,
     "              + (info->Centre.y - pt->Position.y) * pt->Direction.y;",
     "              - (info->Centre.y - pt->Position.y) * pt->Direction.y;"),
    ("rb_lateral_flipped", C,
     "        lateral = (pt->RightWidth - pt->LeftWidth) * 0.5f;",
     "        lateral = (pt->LeftWidth - pt->RightWidth) * 0.5f;"),
    ("rb_L_left", C,
     "        rb->L.y = -rb->D.x;",
     "        rb->L.y = rb->D.x;"),
    ("rb_icon_from_D", C,
     "bATan(rb->L.x, rb->L.y)",
     "bATan(rb->D.x, rb->D.y)"),
    ("rb_cop1_kept", C,
     "        rb->cops[1] = NULL;\n",
     ""),
    ("rb_dist_at_record", C,
     "        trackpath_coord_init_at(&tpc, &rb->v2Position);",
     "        trackpath_coord_init_at(&tpc, &info->Centre);"),
    ("rb_count_short", C,
     "    m->nNumRoadBlocks = n;",
     "    m->nNumRoadBlocks = n - (n > 0);"),

    # ---- InitSpeedTrapStructures
    ("st_count_not_reset", C,
     "    m->nNumSpeedTraps = 0;\n    if (SpeedTrapData",
     "    if (SpeedTrapData"),
    ("st_index_not_cleared", C,
     "        m->RealSpeedTrapIndexFromDataIndex[i] = -1;\n",
     "        m->RealSpeedTrapIndexFromDataIndex[i] = 0;\n"),
    ("st_reverse_too", C,
     "            else if (info->BeACopReverseSpawnSpot != 0)",
     "            if (info->BeACopReverseSpawnSpot != 0)"),
    ("st_beacop_bit", C,
     "                t->Flags |= SPEEDTRAP_BEACOP;",
     "                t->Flags |= SPEEDTRAP_BEACOP_REVERSE;"),
    ("st_flags_not_cleared", C,
     "            t->Flags = 0;\n",
     ""),
    ("st_cop_kept", C,
     "            t->cop = NULL;\n",
     ""),
    ("st_nrpi_fresh", C,
     "        m->RealSpeedTrapIndexFromDataIndex[i] = -1;\n",
     "        m->RealSpeedTrapIndexFromDataIndex[i] = -1;\n"
     "        nrpi.Point = NULL;\n"),
    ("st_ang_plus_1", C,
     "            t->ang = polar.a;",
     "            t->ang = (uint16_t)(polar.a + 1);"),
    ("st_real_index_is_i", C,
     "            m->RealSpeedTrapIndexFromDataIndex[i] = m->nNumSpeedTraps;",
     "            m->RealSpeedTrapIndexFromDataIndex[i] = (int32_t)i;"),
    ("st_topo_not_destroyed", C,
     "        }\n        topology_destroy(&tc);\n    }\n}",
     "        }\n    }\n}"),
    ("st_dist_late", C,
     "            trackpath_coord_init_at(&tpc, &pos);\n",
     "            trackpath_coord_init_at(&tpc, &info->Centre);\n"
     "            tpc.DistanceAroundTrack = -tpc.DistanceAroundTrack;\n"),

    # ---- the lookups
    ("rb_lookup_negative", C,
     "    return k == -1 ? NULL : &m->RoadBlocks[k];",
     "    return k < 0 ? NULL : &m->RoadBlocks[k];"),
    ("st_lookup_never_null", C,
     "    return k == -1 ? NULL : &m->SpeedTraps[k];",
     "    return &m->SpeedTraps[k];"),

    # ---- GetBaseSpeedTrapSpawnTime
    ("base_p2p_flipped", C,
     "    if (TheRaceParameters.Point2Point == 0)\n",
     "    if (TheRaceParameters.Point2Point != 0)\n"),
    ("base_p2p_two_laps", C,
     "    float laps = 1.0f, len, base = 45.0f;",
     "    float laps = 2.0f, len, base = 45.0f;"),
    ("base_15000_le", C,
     "    if (len < 15000.0f)",
     "    if (len <= 15000.0f)"),
    ("base_30000_le", C,
     "    else if (len < 30000.0f)",
     "    else if (len <= 30000.0f)"),
    ("base_nan_short", C,
     "    float laps = 1.0f, len, base = 45.0f;",
     "    float laps = 1.0f, len, base = 15.0f;"),
    ("base_skipfe_first", C,
     "    if (TheRaceParameters.AIDemoMode != 0)\n        return 1.0f;\n"
     "    if (config_skip_fe() != 0)\n        return SkipFETimeUntilCopsAppear;\n",
     "    if (config_skip_fe() != 0)\n        return SkipFETimeUntilCopsAppear;\n"
     "    if (TheRaceParameters.AIDemoMode != 0)\n        return 1.0f;\n"),
    ("base_random_len", C,
     "    return base + world_random_f(pCurrentWorld, base);",
     "    return base + world_random_f(pCurrentWorld, len);"),

    # ---- FindLandmark
    ("landmark_six_verts", C,
     "is_point_in_poly(pos, l->VertsForArea, l->NumVerts)",
     "is_point_in_poly(pos, l->VertsForArea, 6)"),
    ("landmark_from_1", C,
     "    for (i = 0; i < LandmarkData->NumLandmarks; i++) {\n        Landmark",
     "    for (i = 1; i < LandmarkData->NumLandmarks; i++) {\n        Landmark"),

    # ---- the pursuits
    ("freeid_five", C,
     "    for (i = 0; i < COPMANAGER_MAX_PURSUITS; i++)\n"
     "        if (m->PursuitsById[i] == NULL)",
     "    for (i = 0; i < COPMANAGER_MAX_PURSUITS - 1; i++)\n"
     "        if (m->PursuitsById[i] == NULL)"),
    ("delpursuit_keeps_id", C,
     "    m->PursuitsById[p->nPursuitId] = NULL;\n",
     ""),
    ("delpursuit_flags_1", C,
     "    ((DtorFn)e->fn)(vt_this(p, e), 3);",
     "    ((DtorFn)e->fn)(vt_this(p, e), 1);"),
    ("delpursuit_null", C,
     "    if (p == NULL)\n        return;\n    p->Node",
     "    p->Node"),

    # ---- the constructor
    ("ctor_cop_pool_7", C,
     'bNewSlotPool(TAICOP_SLOT_SIZE, 6, "CopSlotPool", 16)',
     'bNewSlotPool(TAICOP_SLOT_SIZE, 7, "CopSlotPool", 16)'),
    ("ctor_byid_five", C,
     "    for (i = COPMANAGER_MAX_PURSUITS - 1; i >= 0; i--)",
     "    for (i = COPMANAGER_MAX_PURSUITS - 1; i >= 1; i--)"),
    ("ctor_new76_kept", C,
     "    m->New76 = NULL;\n    m->bChopperBusy",
     "    m->bChopperBusy"),
    ("ctor_chopper_kept", C,
     "    m->bChopperBusy = 0;\n",
     ""),
    ("ctor_st_before_rb", C,
     "    copmanager_init_road_block_structures(m);\n"
     "    copmanager_init_speed_trap_structures(m);\n",
     "    copmanager_init_speed_trap_structures(m);\n"
     "    copmanager_init_road_block_structures(m);\n"),
    ("ctor_player_index_0", C,
     "    m->nPlayerCopIndex = -1;",
     "    m->nPlayerCopIndex = 0;"),
    ("ctor_cops_six", C,
     "    for (i = 0; i < COPMANAGER_MAX_COPS; i++)\n        m->Cops[i] = NULL;",
     "    for (i = 1; i < COPMANAGER_MAX_COPS; i++)\n        m->Cops[i] = NULL;"),
    ("ctor_supervisor", C,
     "    m->fSupervisorTimer = -50.0f;",
     "    m->fSupervisorTimer = -5.0f;"),
    ("ctor_gap", C,
     "    m->MaxSpeechGapTime = 12.0f;",
     "    m->MaxSpeechGapTime = 10.0f;"),
    ("ctor_flush_first", C,
     "    if (gCopSpeechAllocateVoicesFn != NULL)\n"
     "        gCopSpeechAllocateVoicesFn();\n"
     "    if (gCopSpeechFlushQueueFn != NULL)\n"
     "        gCopSpeechFlushQueueFn();\n",
     "    if (gCopSpeechFlushQueueFn != NULL)\n"
     "        gCopSpeechFlushQueueFn();\n"
     "    if (gCopSpeechAllocateVoicesFn != NULL)\n"
     "        gCopSpeechAllocateVoicesFn();\n"),
    ("ctor_pullover_cop_0", C,
     "        pl->nCopIndex = -1;",
     "        pl->nCopIndex = 0;"),
    ("ctor_pullover_tickets_kept", C,
     "        pl->nNumTickets = 0;\n",
     ""),
    ("ctor_pullover_busted_cleared", C,
     "        pl->bActive = 0;\n",
     "        pl->bActive = 0;\n        pl->bShouldDisplayBustedText = 0;\n"),
    ("ctor_pursuable_kept", C,
     "        m->fPursuableTimer[i] = 0.0f;\n",
     ""),
    ("ctor_hold_kept", C,
     "        pl->fHoldTimer = 0.0f;\n",
     ""),
    ("ctor_sttimer_seven", C,
     "    for (i = 0; i < 8; i++)\n        m->fSpeedTrapSpawnTimer[i] =",
     "    for (i = 0; i < 7; i++)\n        m->fSpeedTrapSpawnTimer[i] ="),
    ("ctor_cookie_kept", C,
     "    m->SpeechFillerCookie = 0;\n",
     ""),
    ("ctor_damage_13", C,
     "    for (i = 0; i < COPMANAGER_NUM_CARS; i++)\n        m->fCarDamage[i]",
     "    for (i = 1; i < COPMANAGER_NUM_CARS; i++)\n        m->fCarDamage[i]"),
    ("ctor_beacop_peeks", C,
     "        m->BeACopId = copmanager_reserve_cop_speaker(m);",
     "        m->BeACopId = copmanager_get_current_cop_speaker(m);"),
    ("ctor_beacop_rb_choppers", C,
     "        m->nBeACopNumRoadBlocks = rp->nNumBeACopRoadBlocks;",
     "        m->nBeACopNumRoadBlocks = rp->nNumBeACopChoppers;"),
    ("ctor_beacop_time_unsigned", C,
     "        m->fBeACopTime = (float)(int32_t)rp->TimeTrialTime.PackedTime",
     "        m->fBeACopTime = (float)rp->TimeTrialTime.PackedTime"),
    ("ctor_beacop_time_ms", C,
     "                       * 0.00025f;",
     "                       * 0.001f;"),
    ("ctor_nobeacop_rb_kept", C,
     "        m->fBeACopTime = 0.0f;\n        m->nBeACopNumRoadBlocks = 0;\n",
     "        m->fBeACopTime = 0.0f;\n"),
    ("ctor_nobeacop_choppers_kept", C,
     "        m->nBeACopNumRoadBlocks = 0;\n        m->nBeACopNumChopperAttacks = 0;\n",
     "        m->nBeACopNumRoadBlocks = 0;\n"),
    ("ctor_strength_0_le", C,
     "    if (rp->CopStrength == 0)",
     "    if (rp->CopStrength <= 0)"),
    ("ctor_strength_1_ge", C,
     "    else if (rp->CopStrength == 1)",
     "    else if (rp->CopStrength >= 1)"),
    ("ctor_said_kept", C,
     "    m->bBeACopAlreadySaidLookOutForSpeeders = 0;\n",
     ""),
    ("ctor_10488_kept", C,
     "    m->New10488 = 0;\n",
     ""),
    ("ctor_arrests_kept", C,
     "    m->nBeACopNumArrestsMade = 0;\n",
     ""),
    ("ctor_10500_kept", C,
     "    m->New10500 = 0;\n",
     ""),
    ("ctor_ydim_kept", C,
     "    m->fMaxCopCarYdim = 0.0f;\n",
     ""),

    # ---- the destructor
    ("dtor_new76_in_order", C,
     "    if (m->New76 != NULL) {\n"
     "        copmanager_delete_pursuit(m, m->New76);\n",
     "    if (0) {\n"
     "        copmanager_delete_pursuit(m, m->New76);\n"),
    ("dtor_cops_six", C,
     "    for (i = 0; i < COPMANAGER_MAX_COPS; i++) {\n        tCop *c",
     "    for (i = 0; i < COPMANAGER_MAX_COPS - 1; i++) {\n        tCop *c"),
    ("dtor_cop_flags_1", C,
     "            ((DtorFn)e->fn)(vt_this(c, e), 3);",
     "            ((DtorFn)e->fn)(vt_this(c, e), 1);"),
    ("dtor_spike_flags_2", C,
     "        ((DtorFn)e->fn)(vt_this(s, e), 3);",
     "        ((DtorFn)e->fn)(vt_this(s, e), 2);"),
    ("dtor_spike_not_unlinked", C,
     "        n->Prev->Next = n->Next;\n",
     ""),
    ("dtor_pools_swapped", C,
     "    bDeleteSlotPool(PursuitSlotPool);\n    PursuitSlotPool = NULL;\n"
     "    bDeleteSlotPool(CopSlotPool);\n",
     "    bDeleteSlotPool(CopSlotPool);\n    PursuitSlotPool = NULL;\n"
     "    bDeleteSlotPool(PursuitSlotPool);\n"),
    ("dtor_spike_pool_kept", C,
     "    SpikeStripSlotPool = NULL;\n",
     ""),
    ("dtor_not_freed", C,
     "    if (flags & 1)\n        bFree(m);",
     "    (void)flags;"),

    # ---- InitCops and CleanupCops
    ("initcops_nonzero", C,
     "    if (TheRaceParameters.nMaxCops > 0)",
     "    if (TheRaceParameters.nMaxCops != 0)"),
    ("initcops_name", C,
     '"CopMgr", 0,',
     '"CopManager", 0,'),
    ("initcops_flags", C,
     '"CopMgr", 0,',
     '"CopMgr", 1,'),
    ("cleanup_keeps_pointer", C,
     "        ((DtorFn)e->fn)(vt_this(m, e), 3);\n        pCopManager = NULL;",
     "        ((DtorFn)e->fn)(vt_this(m, e), 3);"),
    ("cleanup_flags_2", C,
     "        ((DtorFn)e->fn)(vt_this(m, e), 3);\n        pCopManager = NULL;",
     "        ((DtorFn)e->fn)(vt_this(m, e), 2);\n        pCopManager = NULL;"),
    # ---- the impacts
    ("gcbc_from_1", C,
     "    for (i = 0; i < m->nNumCops; i++)\n        if (m->Cops[i]->pMyCar == c)",
     "    for (i = 1; i < m->nNumCops; i++)\n        if (m->Cops[i]->pMyCar == c)"),
    ("gcbc_one_short", C,
     "    for (i = 0; i < m->nNumCops; i++)\n        if (m->Cops[i]->pMyCar == c)",
     "    for (i = 0; i < m->nNumCops - 1; i++)\n        if (m->Cops[i]->pMyCar == c)"),
    ("gcbc_last", C,
     "    for (i = 0; i < m->nNumCops; i++)\n        if (m->Cops[i]->pMyCar == c)\n            return m->Cops[i];\n    return NULL;",
     "    tCop *r = NULL;\n\n    for (i = 0; i < m->nNumCops; i++)\n        if (m->Cops[i]->pMyCar == c)\n            r = m->Cops[i];\n    return r;"),
    ("mi_scale_0", C,
     "{ 100.0f, 4.0f, 2.5f }", "{ 4.0f, 4.0f, 2.5f }"),
    ("mi_scale_1", C,
     "{ 100.0f, 4.0f, 2.5f }", "{ 100.0f, 2.5f, 2.5f }"),
    ("mi_scale_2", C,
     "{ 100.0f, 4.0f, 2.5f }", "{ 100.0f, 4.0f, 4.0f }"),
    ("mi_no_pursuit_test", C,
     "if (cop == NULL || (pu = cop->pMyPursuit) == NULL)\n            return;",
     "if (cop == NULL)\n            return;\n        pu = cop->pMyPursuit;"),
    ("mi_any_chased", C,
     "        if (pu->pChasedCar != c)\n            return;\n", ""),
    ("mi_dist_always", C,
     "        if (rp->NumPlayerCars != 2) {\n            float dx",
     "        if (1) {\n            float dx"),
    ("mi_dist_never", C,
     "        if (rp->NumPlayerCars != 2) {\n            float dx",
     "        if (0) {\n            float dx"),
    ("mi_dist_le", C,
     "            if (!(sqrtf(dx * dx + dy * dy) < 50.0f))",
     "            if (!(sqrtf(dx * dx + dy * dy) <= 50.0f))"),
    ("mi_dist_40", C,
     "            if (!(sqrtf(dx * dx + dy * dy) < 50.0f))",
     "            if (!(sqrtf(dx * dx + dy * dy) < 40.0f))"),
    ("mi_dist_x_only", C,
     "            if (!(sqrtf(dx * dx + dy * dy) < 50.0f))",
     "            if (!(sqrtf(dx * dx) < 50.0f))"),
    ("mi_dist_not_nan", C,
     "            if (!(sqrtf(dx * dx + dy * dy) < 50.0f))",
     "            if (sqrtf(dx * dx + dy * dy) >= 50.0f)"),
    ("mi_min_lt", C,
     "        if (!(5.0f <= amount))\n            return;",
     "        if (!(5.0f < amount))\n            return;"),
    ("mi_min_4", C,
     "        if (!(5.0f <= amount))\n            return;",
     "        if (!(4.0f <= amount))\n            return;"),
    ("mi_no_min", C,
     "        if (!(5.0f <= amount))\n            return;\n        i = c->CarIndex;",
     "        i = c->CarIndex;"),
    ("mi_bac_table_lt", C,
     "        if (fDisablingImpactMagnitudeTable[lvl] <= amount) {",
     "        if (fDisablingImpactMagnitudeTable[lvl] < amount) {"),
    ("mi_bac_table_lvl0", C,
     "        if (fDisablingImpactMagnitudeTable[lvl] <= amount) {",
     "        if (fDisablingImpactMagnitudeTable[0] <= amount) {"),
    ("mi_bac_full_add", C,
     "            m->fCarDamage[i] = 1.0f;\n            return;",
     "            m->fCarDamage[i] = ee_min(m->fCarDamage[i] + 1.0f, 2.0f);\n            return;"),
    ("mi_scale_factor", C,
     "        scale = damageScale[lvl] * 0.005f;",
     "        scale = damageScale[lvl] * 0.01f;"),
    ("mi_two_scale", C,
     "            scale = 0.01f;", "            scale = 0.005f;"),
    ("mi_two_scale_never", C,
     "        if (rp->NumPlayerCars == 2)\n            scale = 0.01f;", ""),
    ("mi_outer_min", C,
     "        m->fCarDamage[i] = ee_min(m->fCarDamage[i]\n                                  + ee_min(amount * scale, 1.0f), 1.0f);",
     "        m->fCarDamage[i] = m->fCarDamage[i]\n                                  + ee_min(amount * scale, 1.0f);"),
    ("mi_inner_cap_half", C,
     "+ ee_min(amount * scale, 1.0f), 1.0f);",
     "+ ee_min(amount * scale, 0.5f), 1.0f);"),
    ("mi_set_not_add", C,
     "        m->fCarDamage[i] = ee_min(m->fCarDamage[i]\n                                  + ee_min(amount * scale, 1.0f), 1.0f);",
     "        m->fCarDamage[i] = ee_min(amount * scale, 1.0f);"),
    ("mi_any_mode", C,
     "    if (c->TheControlMode != COP_CONTROL)\n        return;\n", ""),
    ("mi_two_car_ignored", C,
     "    if (twoCar != 0)\n        amount *= 1.5f;\n", ""),
    ("mi_two_car_2x", C,
     "        amount *= 1.5f;", "        amount *= 2.0f;"),
    ("mi_two_car_always", C,
     "    if (twoCar != 0)\n        amount *= 1.5f;",
     "    amount *= 1.5f;"),
    ("mi_two_car_positive", C,
     "    if (twoCar != 0)\n        amount *= 1.5f;",
     "    if (twoCar > 0)\n        amount *= 1.5f;"),
    ("mi_ai_table_lt", C,
     "    if (!(fDisablingImpactMagnitudeTable[lvl] <= amount))",
     "    if (!(fDisablingImpactMagnitudeTable[lvl] < amount))"),
    ("mi_ai_table_lvl1", C,
     "    if (!(fDisablingImpactMagnitudeTable[lvl] <= amount))",
     "    if (!(fDisablingImpactMagnitudeTable[1] <= amount))"),
    ("mi_ai_table_nan", C,
     "    if (!(fDisablingImpactMagnitudeTable[lvl] <= amount))",
     "    if (fDisablingImpactMagnitudeTable[lvl] > amount)"),
    ("mi_table_0", C,
     "{ 40.0f, 60.0f, 75.0f }", "{ 45.0f, 60.0f, 75.0f }"),
    ("mi_table_1", C,
     "{ 40.0f, 60.0f, 75.0f }", "{ 40.0f, 50.0f, 75.0f }"),
    ("mi_table_2", C,
     "{ 40.0f, 60.0f, 75.0f }", "{ 40.0f, 60.0f, 70.0f }"),
    ("mi_any_cop_type", C,
     "        if (((int32_t (*)(void *))e->fn)(vt_this(cop, e)) == 0)\n            return;",
     "        (void)e;"),
    ("mi_timer_lt", C,
     "    if (((tAICop *)(void *)cop)->New32 <= 0.0f) {",
     "    if (((tAICop *)(void *)cop)->New32 < 0.0f) {"),
    ("mi_timer_ignored", C,
     "    if (((tAICop *)(void *)cop)->New32 <= 0.0f) {",
     "    if (1) {"),
    ("mi_disable_0", C,
     "        gAICopDisableMyCarFn(cop, 1);", "        gAICopDisableMyCarFn(cop, 0);"),
    ("ci_gate_lt", C,
     "    if (!(1.0f <= amount))\n        return;\n    if (cb->NumCollisions",
     "    if (!(1.0f < amount))\n        return;\n    if (cb->NumCollisions"),
    ("ci_gate_nan", C,
     "    if (!(1.0f <= amount))\n        return;\n    if (cb->NumCollisions",
     "    if (1.0f > amount)\n        return;\n    if (cb->NumCollisions"),
    ("ci_no_gate", C,
     "    if (!(1.0f <= amount))\n        return;\n    if (cb->NumCollisions",
     "    if (cb->NumCollisions"),
    ("ci_scan_all", C,
     "        } while (i < cb->NumCollisions && twoCar == 0);",
     "        } while (i < cb->NumCollisions);"),
    ("ci_scan_first", C,
     "        } while (i < cb->NumCollisions && twoCar == 0);",
     "        } while (0);"),
    ("ci_scan_from_1", C,
     "    int32_t        twoCar = 0, i = 0;",
     "    int32_t        twoCar = 0, i = 1;"),
    ("ci_no_twocar", C,
     "    copmanager_monitor_impact(m, b->pCar, amount, twoCar);",
     "    copmanager_monitor_impact(m, b->pCar, amount, 0);"),
]

EQUIVALENT = {
    "mi_ai_table_nan": "MonitorImpact's one caller, AddDamage, passes only "
                       "amounts of 1.0 or more, so the AI branch never sees "
                       "a NaN, and for the rest the two tests agree",
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    lines = script(bun_chunks(), made_chunks())
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
        todo, SOURCES, "copmanager_test",
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

    lines = script(bun_chunks(), made_chunks())
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
