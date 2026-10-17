#!/usr/bin/env python3
"""Cross-check 3DS Files/source/trackgraph.c, retail's tTrackGraph, the
two coputil.c helpers it calls and coputil.c's DoSegmentsIntersect, against
the retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own TrackGraph.obj: InitTrackGraph (0x0024ec40)
and so the constructor (0x0024dd58) with AddVertex, GetVertexNumber and
AddEdge under it; CleanupTrackGraph (0x0024ec70) through the class's table
(0x002bf3d8) and so the destructor (0x0024e148) with the infos', edges' and
vertices' destructors and bTList's, bList's and bNode's; the destructor
called with flags 0; UncloakAllEdges, GetVertexNumber,
FindEdgeByRouteAndPoint, HasCloakedEdges, GetVertex and GetEdge; and
FindRoadBlock (0x0024e880) and FindSpeedTrap (0x0024ea68) with
TrackRoutePoint::GetSignpost, GetForwardTrackDistance (0x00230de8),
IsTeleportLocationClear (0x00230e18) and World::GetDistanceToClosestPlayer
(0x0014e3e8) running as shipped; and DoSegmentsIntersect
(0x00230f00), the spike strips' test, alone. The harness (tools/src/trackgraph_test.c)
runs trackgraph.c, coputil.c, world.c and trackroute.c's loader and prints
the same lines.

**The stubs**, logged and answered by the same rule on both sides:
bMalloc(int, int) (a block of 0xcd), __builtin_delete, bNewSlotPool,
bDeleteSlotPool, bOMalloc (12 bytes of 0xcd) and bFree(SlotPool *, void *);
TrackPathCoordinate's constructor, whose distance is the position's x, and
destructor; Car::GetRoute and Car::GetRoutePoint (scripted per car); and
tCopManager's GetRoadBlockFromLoadedDataIndex and
GetSpeedTrapFromLoadedDataIndex (scripted spots, or none).

**The word before the graph's block** is -1 in the model. Walking forward
from an edge that ran off its route, retail reads Vertex[-1]'s first
forward edge, which is that word: bMalloc's header on the PS2. The port
stops there, as retail does when the word is -1.

**Compared** are the stubs' logs and, on `dump`, the graph whole: every
vertex's sign, route, point, distance and edges, and every edge's ends,
route, points, flags and both lists walked forward with each node's back
link checked, the 400 - nNumEdges unused edges' lists, and the two pools;
on `signs`, every sign's flag byte.

**The script** builds the graph of every retail track (TRACKB*.BUN), of
graphs made by hand for the rare paths (dead ends, signs to unloaded and
traffic routes, three edges into one vertex, every sign type, Backwards
and Cloaked on each, NoHelisheet at both ends of an edge) and of a few
hundred made at random; looks up vertices and edges at every point and
past both ends; finds roadblocks and radar traps from cars all over each
graph, both ways, over several ranges, with spots near players and cars;
uncloaks; and tears the graphs down both ways. Segments are crossed,
touched at their ends, laid end to end, along each other and side by side,
made tiny, infinite and NaN, put a rounding from the other's line and
thrown at random.

    python tools/trackgraph_check.py
    python tools/trackgraph_check.py --mutate [--only a,b]
    python tools/trackgraph_check.py --dump out/trackgraph
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
from trackroute_check import find_chunk  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)
TRACKS = ROOT / "extracted-retail" / "TRACKS"

HARNESS = "tools/src/trackgraph_test.c"
TG = "3DS Files/source/trackgraph.c"
CU = "3DS Files/source/coputil.c"
SOURCES = [HARNESS, TG, CU, "3DS Files/source/world.c",
           "3DS Files/source/trackroute.c", "3DS Files/source/trackpath.c",
           "3DS Files/source/replay.c", "3DS Files/source/p32.c",
           "3DS Files/source/quickspline.c", "3DS Files/source/bchunk.c",
           "3DS Files/source/vtable.c", "3DS Files/source/bmatrix.c",
           "3DS Files/source/bvector.c", "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c", "3DS Files/source/emath.c"]
HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = retail_model.RETAIL_GP
G_GRAPH = GP - 14840
G_RBPOOL = GP - 14848
G_STPOOL = GP - 14844
G_COPMGR = GP - 15620
G_WORLD = GP - 22120
G_SIGNS = GP - 18376
G_NSIGNS = GP - 18372
ROUTE_TABLE = 0x00314438 + 16           # TheTrackRouteManager.pTrackRoutes
TRACKLEN = 0x0031bc38                   # TheTrackPathManager.TrackLength

F_INIT = 0x0024ec40
F_CLEANUP = 0x0024ec70
F_DTOR = 0x0024e148
F_UNCLOAK = 0x0024e3b8
F_VNUM = 0x0024e4d0
F_FEDGE = 0x0024e790
F_FINDRB = 0x0024e880
F_FINDST = 0x0024ea68
F_HASC = 0x0024ecb8
F_GETV = 0x0024ecc0
F_GETE = 0x0024ecd8
F_GFTD = 0x00230de8
F_CLEAR = 0x00230e18
F_DSI = 0x00230f00

S_MALLOC2 = 0x00257690
S_DELETE = 0x00114e98
S_NEWPOOL = 0x00257c10
S_DELPOOL = 0x00257c48
S_OMALLOC = 0x00257c80
S_SFREE = 0x00257ca0
S_TPC_CTOR = 0x002086f0
S_TPC_DTOR = 0x00208748
S_GETROUTE = 0x001332a8
S_GETRP = 0x001332d8
S_RBGET = 0x00226448
S_STGET = 0x00226bb0

GRAPH_SIZE = 23216
V0, VSIZE = 12, 40
E0, ESIZE = 4012, 48
CAR_SIZE = 2304
CAR_POS, CAR_DIST = 96, 2036
WORLD_SIZE = 512
W_NCARS, W_CARS, W_PLAYERS = 28, 44, 336
RB_SIZE, RB_POS, RB_DIST = 120, 68, 100
ST_SIZE, ST_POS, ST_DIST = 28, 4, 20
NCARS = 8
NSPOTS = 64

ROUTES_ID = 0x00034121
SIGNS_ID = 0x00034122
ROUTE_HEAD = 1064
POINT_SIZE = 112
NONE_BITS = 0x0fc03fff


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def F(f):
    return "0x%08x" % fbits(f)


def r16(n):
    return (n + 15) & ~15


# ============================================================== the blobs

def blob(routes, signs):
    """A routes chunk, padded so the signs chunk follows 16 bytes on from
    the payload's 16-byte end, and a signs chunk."""
    b = struct.pack("<II", ROUTES_ID, len(routes)) + routes
    b += bytes(8 + r16(len(routes)) - len(b))
    return b + struct.pack("<II", SIGNS_ID, len(signs)) + signs


def bun_blob(path):
    data = path.read_bytes()
    ro = find_chunk(data, ROUTES_ID)
    so = find_chunk(data, SIGNS_ID)
    rs = struct.unpack_from("<I", data, ro + 4)[0]
    ss = struct.unpack_from("<I", data, so + 4)[0]
    return blob(data[ro + 8:ro + 8 + rs], data[so + 8:so + 8 + ss])


def route_rec(num, bits, typ=0):
    """One route record: the header and len(bits) points."""
    h = bytearray(ROUTE_HEAD)
    struct.pack_into("<IIhhii", h, 0, 0, 0, 1, num, typ, len(bits))
    body = bytearray()
    for i, b in enumerate(bits):
        p = bytearray(POINT_SIZE)
        struct.pack_into("<fff", p, 0, num * 1000.0 + i * 10.25,
                         i * 0.5 - num, 1.0)
        struct.pack_into("<I", p, 44, b & M32)
        p[111] = num & 0xff
        body += p
    return bytes(h) + bytes(body)


def sign_rec(new_route, flags, new_point, hint=0):
    return struct.pack("<BBHfi", new_route & 0xff, flags & 0xff,
                       new_point & 0xffff, 0.0, hint)


def pt_bits(sign=0xff, rb=0x3f, st=0x3f, heli=False, extra=0):
    b = (NONE_BITS & ~0xff & ~0x3f00 & ~0x0fc00000) | sign | rb << 8 \
        | st << 22 | extra
    return b | (0x4000 if heli else 0)


def routes_info(raw):
    """{route number: (offset of the record in the blob, NumPoints)}, and
    the signs' count."""
    rs = struct.unpack_from("<I", raw, 4)[0]
    p, end, out = 8, 8 + rs, {}
    while p < end:
        num = struct.unpack_from("<h", raw, p + 10)[0]
        n = struct.unpack_from("<i", raw, p + 16)[0]
        out[num] = (p, n)
        p += ROUTE_HEAD + n * POINT_SIZE
    so = 8 + r16(rs)
    return out, struct.unpack_from("<I", raw, so + 4)[0] // 12


# ----------------------------------------------------------- made by hand

S_FAST, S_SLOW, S_ALWAYS, S_STOP, S_EQUIV, S_DONT = 0, 1, 2, 3, 4, 5
BACK, CLOAK = 0x08, 0x40


def made_blobs():
    """Graphs made by hand: (name, bytes)."""
    out = []

    # A loop of route 0, with spurs. Signs every five points.
    signs = []

    def sg(*a):
        signs.append(sign_rec(*a))
        return len(signs) - 1

    r0 = [pt_bits() for _ in range(60)]
    kinds = [S_FAST, S_SLOW, S_EQUIV, S_DONT]
    for k, i in enumerate(range(0, 60, 5)):
        r0[i] = pt_bits(sg(0, kinds[k % 4] | (0x30 if k & 1 else 0), i))
    # 20 and 25 branch to route 1, 25 cloaked; 30 to route 2.
    r0[20] = pt_bits(sg(1, S_FAST, 0))
    r0[25] = pt_bits(sg(1, S_FAST | CLOAK, 0))
    r0[30] = pt_bits(sg(2, S_SLOW, 0), rb=7)
    # 50 is a Backwards Faster: no vertex, but a stop for the edges via
    # route 2's sign, whose target it is.
    r0[50] = pt_bits(sg(0, S_FAST | BACK, 50), st=9)
    # 55 closes the loop.
    r0[55] = pt_bits(sg(0, S_ALWAYS, 0))
    # A Stop at 57, not Backwards: a vertex with no edges.
    r0[57] = pt_bits(sg(0, S_STOP, 57))
    for i, (rb, st) in ((1, (3, 0x3f)), (2, (4, 11)), (6, (0, 0)),
                        (12, (62, 61)), (15, (5, 0x3f)), (33, (8, 12)),
                        (44, (9, 13)), (47, (10, 14)), (52, (11, 15))):
        r0[i] = pt_bits(r0[i] & 0xff, rb, st)
    r0[3] |= 0x4000
    r0[10] |= 0x4000
    r0[45] |= 0x4000
    r0[59] = pt_bits(extra=0x10008000)
    r1 = [pt_bits() for _ in range(12)]
    r1[11] = pt_bits(sg(0, S_ALWAYS | CLOAK, 40), rb=20, st=21)
    r1[4] = pt_bits(rb=22, st=23, heli=True)
    r2 = [pt_bits() for _ in range(10)]
    r2[9] = pt_bits(sg(0, S_ALWAYS, 50))
    r2[0] = pt_bits(rb=24)
    # A Backwards Stop on route 3 into route 0 at 35.
    r3 = [pt_bits() for _ in range(6)]
    r3[2] = pt_bits(sg(0, S_STOP | BACK, 35), st=25)
    # Route 60, traffic, reached from route 4's sign; route 61 is not
    # loaded; route 5 runs out.
    r4 = [pt_bits() for _ in range(8)]
    r4[1] = pt_bits(sg(60, S_FAST, 2))
    r4[3] = pt_bits(sg(61, S_SLOW | CLOAK, 0))
    r4[5] = pt_bits(sg(5, S_EQUIV, 0), rb=26)
    r4[7] = pt_bits(sg(0, S_ALWAYS, 5))
    r5 = [pt_bits(rb=27 + k % 3, st=30 + k % 2) for k in range(4)]
    r60 = [pt_bits() for _ in range(9)]
    r60[6] = pt_bits(sg(4, S_FAST, 3))
    r60[8] = pt_bits(sg(0, S_ALWAYS, 10), rb=31)
    out.append(("loop", blob(
        route_rec(0, r0) + route_rec(1, r1) + route_rec(2, r2)
        + route_rec(3, r3) + route_rec(4, r4) + route_rec(5, r5)
        + route_rec(60, r60, typ=1), b"".join(signs))))

    # Swaps: three edges into one vertex, the last on the first forward
    # edge's route or not, cloaked or not.
    for case in range(4):
        signs = []
        a = [pt_bits() for _ in range(20)]
        b = [pt_bits() for _ in range(10)]
        a[0] = pt_bits(sg(1, S_FAST | (CLOAK if case == 1 else 0), 0))
        a[10] = pt_bits(sg(0 if case != 2 else 1, S_SLOW, 10))
        a[5] = pt_bits(sg(1, S_EQUIV | (CLOAK if case == 3 else 0), 2))
        b[8] = pt_bits(sg(0, S_ALWAYS, 10))
        a[19] = pt_bits(sg(0, S_ALWAYS, 0))
        out.append(("swap%d" % case, blob(
            route_rec(0, a) + route_rec(1, b), b"".join(signs))))

    # Every sign type with every combination of Backwards and Cloaked, one
    # vertex each, all on route 0, every one sending to route 1.
    signs = []
    a = [pt_bits() for _ in range(70)]
    k = 0
    for t in range(8):
        for f in (0, BACK, CLOAK, BACK | CLOAK):
            a[2 + 2 * k] = pt_bits(sg(1, t | f, k % 5))
            k += 1
    b = [pt_bits() for _ in range(5)]
    b[4] = pt_bits(sg(0, S_ALWAYS, 0))
    out.append(("types", blob(route_rec(0, a) + route_rec(1, b),
                              b"".join(signs))))

    # A route with nothing on it; an empty chunk; one sign that names
    # itself.
    out.append(("bare", blob(route_rec(0, [pt_bits()] * 5), b"")))
    out.append(("empty", blob(b"", b"")))
    signs = []
    a = [pt_bits() for _ in range(6)]
    a[3] = pt_bits(sg(0, S_FAST, 3))
    out.append(("self", blob(route_rec(0, a), b"".join(signs))))
    return out


# ------------------------------------------------------------- at random

def random_blob(rng):
    nroutes = rng.randint(1, 9)
    nums = sorted(rng.sample(list(range(0, 12)) + [47, 48, 49, 50, 55, 62],
                             nroutes))
    lens = {r: rng.randint(1, 30) for r in nums}
    nsigns = rng.randint(1, 40)
    signs = []
    for _ in range(nsigns):
        if rng.random() < 0.85:
            nr = rng.choice(nums)
            np_ = rng.randrange(lens[nr] + 2) if rng.random() < 0.95 \
                else rng.randrange(1000)
        else:
            nr = rng.choice([13, 20, 48, 63, 70, 99])
            np_ = rng.randrange(20)
        fl = rng.randrange(8)
        if rng.random() < 0.25:
            fl |= BACK
        if rng.random() < 0.2:
            fl |= CLOAK
        if rng.random() < 0.2:
            fl |= rng.choice((0x10, 0x20, 0x80))
        signs.append(sign_rec(nr, fl, np_, rng.randrange(3)))
    recs = b""
    nverts = 0
    for r in nums:
        bits = []
        for i in range(lens[r]):
            s = 0xff
            if rng.random() < 0.3 and (r >= 49 or nverts < 90):
                s = rng.randrange(nsigns)
                nverts += r < 49
            rb = rng.randrange(63) if rng.random() < 0.15 else 0x3f
            st = rng.randrange(63) if rng.random() < 0.15 else 0x3f
            bits.append(pt_bits(s, rb, st, rng.random() < 0.1,
                                rng.choice((0, 0, 0x8000, 0x10000000,
                                            0x00150000))))
        recs += route_rec(r, bits, typ=int(r >= 49))
    return blob(recs, b"".join(signs))


# ================================================================== script

def spots(rng, tracklen, spread):
    s = []
    for k in range(NSPOTS):
        for kind in ("rb", "st"):
            if rng.random() < 0.15:
                s.append("%s|%d|none" % (kind, k))
            else:
                s.append("%s|%d|%s|%s|%s" % (
                    kind, k, F(rng.uniform(0.0, tracklen)),
                    F(rng.uniform(-spread, spread)),
                    F(rng.uniform(-spread, spread))))
    return s


def world(rng, spread):
    n = rng.randint(0, NCARS)
    s = ["world|%d|%s" % (n, "|".join(
        F(rng.uniform(-spread, spread)) for _ in range(4)))]
    for k in range(NCARS):
        s.append("carpos|%d|%s|%s" % (k, F(rng.uniform(-spread, spread)),
                                       F(rng.uniform(-spread, spread))))
    return s


NAN, INF = float("nan"), float("inf")
RANGES = [(0.0, 500.0), (100.0, 1000.0), (200.0, 4000.0), (0.0, 100000.0),
          (300.0, 300.0), (50.0, 2500.0), (-100.0, 50.0), (NAN, 1000.0),
          (0.0, NAN), (0.0, INF), (-INF, 3000.0)]


def queries(rng, info, nsigns, tracklen, nfind, spread=400.0):
    s = []
    nums = sorted(info)
    for r in nums + [-1, 70]:
        n = info[r][1] if r in info else 3
        for p in sorted({-1, 0, 1, n // 2, n - 1, n, n + 1}):
            s.append("vnum|%d|%d" % (r, p))
            s.append("fedge|%d|%d" % (r, p))
    s += spots(rng, tracklen, spread)
    s += world(rng, spread)
    for _ in range(nfind):
        k = rng.randrange(NCARS)
        if nums and rng.random() < 0.93:
            r = rng.choice(nums)
            p = rng.randrange(-1, info[r][1] + 1) if info[r][1] else 0
            if rng.random() < 0.04:
                p = "none"
        else:
            r, p = rng.choice(((-1, 0), (99, 0)))
        s.append("car|%d|%d|%s|%s" % (k, r, p,
                                      F(rng.uniform(0.0, tracklen))))
        lo, hi = rng.choice(RANGES)
        fwd = rng.choice((0, 1, 1, 2))
        s.append("%s|%d|%s|%s|%d" % (rng.choice(("findrb", "findst")), k,
                                     F(lo), F(hi), fwd))
        if rng.random() < 0.1:
            s += world(rng, spread)
        if rng.random() < 0.05:
            s += spots(rng, tracklen, spread)
    return s


def loop_bounds():
    """Finds on the "loop" graph at the range's two ends exactly. Car 0 is
    on route 0 at point 7, the edge from 5 to 10, whose one roadblock and
    one radar trap are number 0 (point 6). Forward, the fifth edge on runs
    from 25 to 30 and has number 7 at 30; the sixth, from 30 to 35, has 7
    again and 8 (point 33)."""
    s = ["tracklen|%s" % F(5000.0),
         "world|0|%s|%s|%s|%s" % (F(1e6), F(1e6), F(1e6), F(1e6))]
    s += ["%s|%d|none" % (kind, k) for k in range(NSPOTS)
          for kind in ("rb", "st")]

    def find(kind, car, lo, hi, fwd):
        return ["car|0|0|7|%s" % F(car),
                "find%s|0|%s|%s|%d" % (kind, F(lo), F(hi), fwd)]

    for kind in ("rb", "st"):
        s.append("%s|0|%s|%s|%s" % (kind, F(1100.0), F(0.0), F(0.0)))
        for lo, hi in ((100.0, 200.0), (50.0, 100.0), (100.00001, 200.0),
                       (99.99999, 100.00001), (NAN, 200.0), (100.0, NAN),
                       (100.0, INF), (-INF, 100.0), (-INF, INF)):
            s += find(kind, 1000.0, lo, hi, 1)
        for lo, hi in ((4900.0, 5000.0), (4800.0, 4900.0), (0.0, 4900.0),
                       (0.0, 4900.0005)):
            s += find(kind, 1000.0, lo, hi, 0)
        # Wrapped: spot 100 ahead of a car at 4950.
        s.append("%s|0|%s|%s|%s" % (kind, F(100.0), F(0.0), F(0.0)))
        s += find(kind, 4950.0, 150.0, 151.0, 1)
        s += find(kind, 4950.0, 149.0, 150.0, 1)
        s += find(kind, 4950.0, 4850.0, 4851.0, 0)
        s.append("%s|0|none" % kind)
        # Five edges on and no further.
        for k in (7, 8):
            s.append("%s|%d|%s|%s|%s" % (kind, k, F(1500.0), F(0.0),
                                         F(0.0)))
            s += find(kind, 1000.0, 0.0, 5000.0, 1)
            s.append("%s|%d|none" % (kind, k))
        s.append("%s|8|%s|%s|%s" % (kind, F(1500.0), F(0.0), F(0.0)))
        s += find(kind, 1000.0, 0.0, 5000.0, 0)
        s.append("%s|8|none" % kind)
    # A roadblock too near a player, then too near a car, then clear.
    s.append("rb|0|%s|%s|%s" % (F(1100.0), F(10.0), F(20.0)))
    s.append("world|1|%s|%s|%s|%s" % (F(200.0), F(20.0), F(1e6), F(1e6)))
    s.append("carpos|0|%s|%s" % (F(5000.0), F(5000.0)))
    s += find("rb", 1000.0, 0.0, 200.0, 1)
    s.append("world|1|%s|%s|%s|%s" % (F(1e6), F(1e6), F(1e6), F(1e6)))
    s.append("carpos|0|%s|%s" % (F(15.0), F(25.0)))
    s += find("rb", 1000.0, 0.0, 200.0, 1)
    s.append("carpos|0|%s|%s" % (F(30.0), F(20.0)))
    s += find("rb", 1000.0, 0.0, 200.0, 1)
    # Cars on no route, on no point, and on no edge.
    s += ["car|0|-1|0|%s" % F(1000.0), "findrb|0|%s|%s|1" % (F(0.0),
                                                          F(5000.0)),
          "car|0|0|none|%s" % F(1000.0), "findst|0|%s|%s|1" % (F(0.0),
                                                            F(5000.0)),
          "car|0|0|900|%s" % F(1000.0), "findrb|0|%s|%s|0" % (F(0.0),
                                                           F(5000.0))]
    return s


def graph_block(rng, path, raw, tracklen, nfind, teardown, extra=()):
    info, nsigns = routes_info(raw)
    s = ["load|%s" % path, "tracklen|%s" % F(tracklen), "init", "dump",
         "signs", "hasc"]
    s += ["getv|%d" % i for i in (0, 1, 99)]
    s += ["gete|%d" % i for i in (0, 7, 399)]
    s += list(extra)
    s += queries(rng, info, nsigns, tracklen, nfind)
    s += ["uncloak", "dump", "signs", "hasc"]
    s += queries(rng, info, nsigns, tracklen, nfind // 2)
    s += ["uncloak", "hasc"]
    s += [teardown, "dump"]
    return s


def coputil_ops(rng):
    s = []
    for tl in (5000.0, 0.0, 12345.5):
        s.append("tracklen|%s" % F(tl))
        for a, b in ((10.0, 20.0), (20.0, 10.0), (0.0, 0.0), (-0.0, 0.0),
                     (0.0, -0.0), (5000.0, 0.0), (1e-30, 2e-30),
                     (float("nan"), 1.0), (1.0, float("inf")),
                     (float("inf"), float("inf"))):
            s.append("gftd|%s|%s" % (F(a), F(b)))
        for _ in range(20):
            s.append("gftd|%s|%s" % (F(rng.uniform(-9000, 9000)),
                                     F(rng.uniform(-9000, 9000))))
    # The 250 and 15 boundaries, exactly and either side.
    s.append("world|3|%s|%s|%s|%s" % (F(0.0), F(0.0), F(1000.0), F(1000.0)))
    s += ["carpos|0|%s|%s" % (F(600.0), F(0.0)),
          "carpos|1|%s|%s" % (F(-600.0), F(15.0)),
          "carpos|2|%s|%s" % (F(0.0), F(-700.0))]
    for x, y in ((250.0, 0.0), (249.99998, 0.0), (250.00002, 0.0),
                 (0.0, 250.0), (150.0, 200.0), (1000.0, 1250.0),
                 (750.0, 1000.0), (615.0, 0.0), (614.99994, 0.0),
                 (600.0, 15.0), (609.0, 12.0), (-600.0, 0.0),
                 (-600.0, 30.0), (0.0, -685.0), (0.0, -715.0),
                 (float("nan"), 0.0), (300.0, float("nan")),
                 (1e30, 1e30), (-400.0, -400.0), (0.0, -690.0)):
        s.append("clear|%s|%s" % (F(x), F(y)))
    s.append("world|0|%s|%s|%s|%s" % (F(5000.0), F(5000.0), F(5000.0),
                                      F(5000.0)))
    s.append("clear|%s|%s" % (F(600.0), F(0.0)))
    for _ in range(60):
        s += world(rng, 400.0)
        s.append("clear|%s|%s" % (F(rng.uniform(-400, 400)),
                                  F(rng.uniform(-400, 400))))
    return s


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def dsi_ops(rng):
    """DoSegmentsIntersect: p to p + d against q to q + e."""
    s = []

    def dsi(p, d, q, e):
        s.append("dsi|" + "|".join(F(v) for v in p + d + q + e))

    NAN, INF = float("nan"), float("inf")
    for p, d, q, e in (
            ((0.0, 0.0), (10.0, 0.0), (5.0, -5.0), (0.0, 10.0)),
            ((0.0, 0.0), (10.0, 0.0), (5.0, 1.0), (0.0, 10.0)),
            ((0.0, 0.0), (10.0, 0.0), (5.0, -11.0), (0.0, 10.0)),
            ((0.0, 0.0), (10.0, 0.0), (10.0, -5.0), (0.0, 10.0)),
            ((0.0, 0.0), (10.0, 0.0), (10.000001, -5.0), (0.0, 10.0)),
            ((0.0, 0.0), (10.0, 0.0), (-0.000001, -5.0), (0.0, 10.0)),
            ((0.0, 0.0), (10.0, 0.0), (5.0, 0.0), (0.0, 10.0)),
            ((0.0, 0.0), (10.0, 0.0), (5.0, -5.0), (0.0, 5.0)),
            ((0.0, 0.0), (10.0, 0.0), (5.0, -5.0), (0.0, 4.9999995)),
            ((0.0, 0.0), (10.0, 0.0), (2.0, 0.0), (3.0, 0.0)),
            ((0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (3.0, 0.0)),
            ((0.0, 0.0), (10.0, 0.0), (0.0, 1.0), (10.0, 0.0)),
            ((0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0)),
            ((0.0, 0.0), (0.0, 0.0), (3.0, 3.0), (1.0, -2.0)),
            ((-0.0, 0.0), (0.0, -0.0), (-0.0, -0.0), (-0.0, 0.0)),
            ((5.0, -5.0), (0.0, 10.0), (0.0, 0.0), (10.0, 0.0)),
            ((1.0, 1.0), (4.0, 4.0), (1.0, 5.0), (4.0, -4.0)),
            ((1.0, 1.0), (4.0, 4.0), (6.0, 0.0), (4.0, -4.0)),
            ((-3.5, 2.25), (7.0, -4.5), (0.0, 0.0), (-2.0, 1.0)),
            ((0.0, 0.0), (NAN, 0.0), (5.0, -5.0), (0.0, 10.0)),
            ((0.0, 0.0), (10.0, 0.0), (NAN, -5.0), (0.0, 10.0)),
            ((0.0, 0.0), (10.0, 0.0), (5.0, -5.0), (0.0, NAN)),
            ((NAN, 0.0), (10.0, 0.0), (5.0, -5.0), (0.0, 10.0)),
            ((0.0, 0.0), (INF, 0.0), (5.0, -5.0), (0.0, 10.0)),
            ((0.0, 0.0), (10.0, 0.0), (5.0, -INF), (0.0, INF)),
            ((0.0, 0.0), (10.0, 0.0), (5.0, -5.0), (INF, 10.0)),
            ((0.0, 0.0), (1e30, 1e30), (1e30, 0.0), (-1e30, 1e30)),
            ((0.0, 0.0), (1e-20, 0.0), (5e-21, -1e-20), (0.0, -1e-20)),
            ((0.0, 0.0), (1e-20, 0.0), (5e-21, -1e-20), (0.0, 3e-20)),
            ((0.0, 0.0), (1e20, 0.0), (5e19, -1e20), (0.0, -1e20)),
            ((0.0, 0.0), (1e-20, 1e-20), (1e-20, 0.0), (-1e-20, 1e-20)),
            ((1e-30, 0.0), (1e-30, 0.0), (1.5e-30, 1e-30), (0.0, -1e-30)),
            # An end on the other's line, its side's other end overflowing:
            # infinity times 0.
            ((0.0, 0.0), (1e30, 0.0), (5.0, 1e9), (0.0, -1e9)),
    ):
        # Each both ways round, so each side's test meets each case.
        dsi(p, d, q, e)
        dsi(q, e, p, d)
    for _ in range(150):
        dsi(*[(f32(rng.uniform(-60, 60)), f32(rng.uniform(-60, 60)))
              for _ in range(4)])
    for _ in range(100):
        dsi(*[(float(rng.randint(-4, 4)), float(rng.randint(-4, 4)))
              for _ in range(4)])
    # q a rounding from p's line, or q + e from it; the sign of each side
    # is the order the image does its sums in.
    for k in range(240):
        p = (f32(rng.uniform(-60, 60)), f32(rng.uniform(-60, 60)))
        d = (f32(rng.uniform(-30, 30)), f32(rng.uniform(-30, 30)))
        t = rng.uniform(0.05, 0.95)
        on = (f32(p[0] + t * d[0]), f32(p[1] + t * d[1]))
        e = (f32(rng.uniform(-30, 30)), f32(rng.uniform(-30, 30)))
        if k % 3 == 0:
            q = on
        elif k % 3 == 1:
            q = (f32(on[0] - e[0]), f32(on[1] - e[1]))
        else:
            q, e = on, (f32(-rng.uniform(0, 1) * e[0]), e[1])
        if k % 2:
            p, d, q, e = q, e, p, d
        dsi(p, d, q, e)
    return s


def script(blobdir):
    """The script, and the blobs it loads written to `blobdir`."""
    rng = random.Random(0x7247)
    s = coputil_ops(rng) + dsi_ops(random.Random(0x5e6))
    blobs = []
    for p in sorted(TRACKS.glob("TRACKB*.BUN")):
        blobs.append((p.stem, bun_blob(p), 60))
    for name, raw in made_blobs():
        blobs.append((name, raw, 120))
    for k in range(300):
        blobs.append(("rand%d" % k, random_blob(rng), 25))
    for k, (name, raw, nfind) in enumerate(blobs):
        path = Path(blobdir) / ("%s.bin" % name)
        path.write_bytes(raw)
        tl = rng.choice((5000.0, 12000.0, 800.0))
        teardown = ("cleanup", "cleanup", "dtor|0", "dtor|1", "dtor|2")[k % 5]
        s += graph_block(rng, path, raw, tl, nfind, teardown,
                         loop_bounds() if name == "loop" else ())
    s.append("dump")
    return s


# ================================================================= model

class Model(object):
    def __init__(self, maxblob):
        e = self.e = retail_model.emu(retail=True, ieee=True)
        self.out = []
        self.names = {}
        self.mallocs = self.pools = self.infos = 0
        self.graphs = []
        self.blob = e.alloc(maxblob + 64, align=16)
        self.nsigns = 0
        self.mgr = e.alloc(16, align=16)
        self.names[self.mgr] = "M0"
        e.put32(G_COPMGR, self.mgr)
        self.world = e.alloc(WORLD_SIZE, align=16)
        e.write(self.world, bytes(WORLD_SIZE))
        e.put32(G_WORLD, self.world)
        self.cars = []
        for k in range(NCARS):
            c = e.alloc(CAR_SIZE, align=16)
            e.write(c, bytes(CAR_SIZE))
            self.names[c] = "A%d" % k
            self.cars.append(c)
        self.car_route = [-1] * NCARS
        self.car_point = [0] * NCARS
        self.rbs = e.alloc(RB_SIZE * NSPOTS, align=16)
        self.sts = e.alloc(ST_SIZE * NSPOTS, align=16)
        e.write(self.rbs, bytes(RB_SIZE * NSPOTS))
        e.write(self.sts, bytes(ST_SIZE * NSPOTS))
        for k in range(NSPOTS):
            self.names[self.rbs + RB_SIZE * k] = "RB%d" % k
            self.names[self.sts + ST_SIZE * k] = "ST%d" % k
        self.rb_has = [0] * NSPOTS
        self.st_has = [0] * NSPOTS
        self.vec = e.alloc(16, align=16)
        self.segs = e.alloc(32, align=16)
        for a, fn in ((S_MALLOC2, self.s_malloc2), (S_DELETE, self.s_delete),
                      (S_NEWPOOL, self.s_newpool),
                      (S_DELPOOL, self.s_delpool),
                      (S_OMALLOC, self.s_omalloc), (S_SFREE, self.s_sfree),
                      (S_TPC_CTOR, self.s_tpc), (S_TPC_DTOR, lambda em: 0),
                      (S_GETROUTE, self.s_getroute),
                      (S_GETRP, self.s_getrp), (S_RBGET, self.s_rbget),
                      (S_STGET, self.s_stget)):
            e.stub(a, fn)

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
        for k in range(len(self.graphs) - 1, -1, -1):
            o = v - self.graphs[k] - E0
            if 0 <= o < ESIZE * 400:
                i, f = divmod(o, ESIZE)
                if f in (32, 40):
                    return "G%d.E%d.%s" % (k, i, "rb" if f == 32 else "st")
                break
        return "?"

    def cstr(self, a):
        b = self.e.read(a, 64)
        return b.split(b"\0")[0].decode("latin-1")

    def route_addr(self, n):
        if n < 0 or n >= 100:
            return 0
        return self.e.u32(ROUTE_TABLE + 4 * n)

    # ---- stubs

    def s_malloc2(self, em):
        e = self.e
        size = s32(em.reg[4])
        p = e.alloc(size + 16, align=16) + 16
        e.put32(p - 4, 0xffffffff)
        e.write(p, b"\xcd" * size)
        n = "G%d" % self.mallocs
        self.names[p] = n
        self.graphs.append(p)
        self.emit("  malloc2 %d %d -> %s" % (size, s32(em.reg[5]), n))
        self.mallocs += 1
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

    def s_omalloc(self, em):
        p = self.e.alloc(16, align=16)
        self.e.write(p, b"\xcd" * 12)
        n = "I%d" % self.infos
        self.infos += 1
        self.names[p] = n
        self.emit("  omalloc %s -> %s" % (self.sym(em.reg[4]), n))
        return p

    def s_sfree(self, em):
        self.emit("  sfree %s %s" % (self.sym(em.reg[4]),
                                     self.sym(em.reg[5])))

    def s_tpc(self, em):
        e = self.e
        c, pos = em.reg[4] & M32, em.reg[5] & M32
        e.put32(c, e.u32(pos))
        e.put32(c + 4, e.u32(pos + 4))
        e.put32(c + 20, e.u32(pos))

    def car_index(self, c):
        return self.cars.index(c & M32)

    def s_getroute(self, em):
        k = self.car_index(em.reg[4])
        self.emit("  getroute A%d %d" % (k, s32(em.reg[5])))
        return self.route_addr(self.car_route[k])

    def s_getrp(self, em):
        k = self.car_index(em.reg[4])
        self.emit("  getrp A%d %d" % (k, s32(em.reg[5])))
        r = self.route_addr(self.car_route[k])
        if r == 0 or self.car_point[k] is None:
            return 0
        return (r + ROUTE_HEAD + POINT_SIZE * self.car_point[k]) & M32

    def s_rbget(self, em):
        i = s32(em.reg[5])
        has = 0 <= i < NSPOTS and self.rb_has[i]
        p = self.rbs + RB_SIZE * i if has else 0
        self.emit("  rbget %s %d -> %s" % (self.sym(em.reg[4]), i,
                                           self.sym(p)))
        return p

    def s_stget(self, em):
        i = s32(em.reg[5])
        has = 0 <= i < NSPOTS and self.st_has[i]
        p = self.sts + ST_SIZE * i if has else 0
        self.emit("  stget %s %d -> %s" % (self.sym(em.reg[4]), i,
                                           self.sym(p)))
        return p

    # ---- the dump

    def dump_list(self, what, i, l):
        e = self.e
        n, prev, k = e.u32(l), l, 0
        parts = ["E%d %s" % (i, what)]
        while n != l and k < 400:
            parts.append("%s:%d%s" % (self.sym(n), s32(e.u32(n + 8)),
                                      "" if e.u32(n + 4) == prev else "!"))
            prev, n, k = n, e.u32(n), k + 1
        parts.append("end%s" % ("" if e.u32(l + 4) == prev else "!"))
        self.emit(" ".join(parts))

    def dump(self):
        e = self.e
        self.emit("pools %s %s" % (self.sym(e.u32(G_RBPOOL)),
                                   self.sym(e.u32(G_STPOOL))))
        g = e.u32(G_GRAPH)
        if g == 0:
            self.emit("G none")
            return
        i32 = lambda o: s32(e.u32(g + o))           # noqa: E731
        nv, ne = i32(0), i32(4)
        self.emit("G %s nv %d ne %d hc %d vptr %08x" % (
            self.sym(g), nv, ne, i32(8), e.u32(g + 23212)))
        signs = e.u32(G_SIGNS)
        for i in range(nv):
            v = V0 + VSIZE * i
            sp = e.u32(g + v + 8)
            self.emit("V%d S%d r%d p%d d%08x f%d %d b%d %d" % (
                i, s32(sp - signs) // 12, i32(v + 12), i32(v + 16),
                e.u32(g + v + 20), i32(v + 24), i32(v + 28), i32(v + 32),
                i32(v + 36)))
        for i in range(ne):
            o = E0 + ESIZE * i
            self.emit("E%d %d>%d r%d %d..%d c%d %d h%d" % (
                i, i32(o), i32(o + 4), i32(o + 8), i32(o + 12),
                i32(o + 16), i32(o + 20), i32(o + 24), i32(o + 28)))
            self.dump_list("rb", i, g + o + 32)
            self.dump_list("st", i, g + o + 40)
        rest = 0
        for i in range(ne, 400):
            o = g + E0 + ESIZE * i
            if (e.u32(o + 32) != o + 32 or e.u32(o + 36) != o + 32
                    or e.u32(o + 40) != o + 40 or e.u32(o + 44) != o + 40):
                rest += 1
        self.emit("rest %d" % rest)

    def dump_signs(self):
        e = self.e
        base = e.u32(G_SIGNS)
        parts = []
        for i in range(self.nsigns):
            parts.append(("" if i % 32 else " ")
                         + "%02x" % e.read(base + 12 * i + 1, 1)[0])
        self.emit("signs" + "".join(parts))

    # ---- the ops

    def load(self, path):
        e = self.e
        raw = Path(path).read_bytes()
        e.write(self.blob, raw)
        for n in range(100):
            e.put32(ROUTE_TABLE + 4 * n, 0)
        info, nsigns = routes_info(raw)
        for num, (off, _n) in info.items():
            e.put32(ROUTE_TABLE + 4 * num, self.blob + off)
        rs = struct.unpack_from("<I", raw, 4)[0]
        e.put32(G_SIGNS, self.blob + 8 + r16(rs) + 8)
        e.put32(G_NSIGNS, nsigns)
        self.nsigns = nsigns
        self.emit("load signs %d" % nsigns)

    def find(self, a, fn):
        e = self.e
        k = int(a[1])
        fwd = int(a[4], 0)
        self.emit("%s A%d %s %s %s %d" % (a[0], k, a[2], a[3], a[4],
                                          fwd != 0))
        e.fpr[12] = int(a[2], 0) & M32
        e.fpr[13] = int(a[3], 0) & M32
        r = e.call(fn, e.u32(G_GRAPH), self.cars[k], fwd)
        self.emit("  -> %s" % self.sym(r))

    def op(self, a):
        e = self.e
        o = a[0]
        n = lambda k: int(a[k], 0)                  # noqa: E731
        g = e.u32(G_GRAPH)
        if o == "load":
            self.load(a[1])
        elif o == "tracklen":
            e.put32(TRACKLEN, n(1) & M32)
        elif o == "init":
            self.emit("init")
            e.call(F_INIT)
        elif o == "cleanup":
            self.emit("cleanup")
            e.call(F_CLEANUP)
        elif o == "dtor":
            self.emit("dtor %d" % n(1))
            e.call(F_DTOR, g, n(1))
            e.put32(G_GRAPH, 0)
        elif o == "dump":
            self.dump()
        elif o == "signs":
            self.dump_signs()
        elif o == "uncloak":
            self.emit("uncloak")
            e.call(F_UNCLOAK, g)
        elif o == "vnum":
            self.emit("vnum %d %d -> %d" % (n(1), n(2),
                                            e.call(F_VNUM, g, n(1), n(2))))
        elif o == "fedge":
            r = e.call(F_FEDGE, g, n(1), n(2)) & M32
            self.emit("fedge %d %d -> %s" % (
                n(1), n(2), "0" if r == 0 else
                "E%d" % ((r - g - E0) // ESIZE)))
        elif o == "hasc":
            self.emit("hasc %d" % e.call(F_HASC, g))
        elif o == "getv":
            r = e.call(F_GETV, g, n(1)) & M32
            self.emit("getv %d -> V%d" % (n(1), s32(r - g - V0) // VSIZE))
        elif o == "gete":
            r = e.call(F_GETE, g, n(1)) & M32
            self.emit("gete %d -> E%d" % (n(1), s32(r - g - E0) // ESIZE))
        elif o == "car":
            k = n(1)
            self.car_route[k] = n(2)
            self.car_point[k] = None if a[3] == "none" else n(3)
            e.put32(self.cars[k] + CAR_DIST, n(4) & M32)
        elif o == "carpos":
            e.put32(self.cars[n(1)] + CAR_POS, n(2) & M32)
            e.put32(self.cars[n(1)] + CAR_POS + 4, n(3) & M32)
        elif o == "world":
            w = self.world
            e.put32(w + W_NCARS, n(1))
            for k in range(NCARS):
                e.put32(w + W_CARS + 4 * k, self.cars[k])
            e.put32(w + W_PLAYERS, n(2) & M32)
            e.put32(w + W_PLAYERS + 4, n(3) & M32)
            e.put32(w + W_PLAYERS + 16, n(4) & M32)
            e.put32(w + W_PLAYERS + 20, n(5) & M32)
        elif o in ("rb", "st"):
            k = n(1)
            has = a[2] != "none"
            if o == "rb":
                self.rb_has[k] = has
                base, pos, dist = self.rbs + RB_SIZE * k, RB_POS, RB_DIST
            else:
                self.st_has[k] = has
                base, pos, dist = self.sts + ST_SIZE * k, ST_POS, ST_DIST
            if has:
                e.put32(base + dist, n(2) & M32)
                e.put32(base + pos, n(3) & M32)
                e.put32(base + pos + 4, n(4) & M32)
        elif o == "findrb":
            self.find(a, F_FINDRB)
        elif o == "findst":
            self.find(a, F_FINDST)
        elif o == "gftd":
            e.fpr[12] = n(1) & M32
            e.fpr[13] = n(2) & M32
            e.call(F_GFTD)
            self.emit("gftd %s %s -> %08x" % (a[1], a[2], e.fpr[0] & M32))
        elif o == "clear":
            e.put32(self.vec, n(1) & M32)
            e.put32(self.vec + 4, n(2) & M32)
            self.emit("clear %s %s -> %d" % (a[1], a[2],
                                             e.call(F_CLEAR, self.vec)))
        elif o == "dsi":
            for k in range(8):
                e.put32(self.segs + 4 * k, n(1 + k) & M32)
            r = e.call(F_DSI, self.segs, self.segs + 8, self.segs + 16,
                       self.segs + 24)
            self.emit("dsi %s -> %d" % (" ".join(a[1:9]), r))
        else:
            raise ValueError(o)

    def run(self, lines):
        for line in lines:
            self.op(line.split("|"))
        return self.out


def model(lines):
    maxblob = 0
    for line in lines:
        if line.startswith("load|"):
            maxblob = max(maxblob, os.path.getsize(line[5:]))
    return Model(maxblob).run(lines)


# ================================================================== build

def build_harness(tmp, name="trackgraph_test"):
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

C = TG
U = CU
MUTATIONS = [
    # ---- the lists
    ("tail_prev_is_list", C,
     "    info->Link.prev = tail;\n",
     "    info->Link.prev = l;\n"),
    ("tail_list_prev_kept", C,
     "    l->prev = &info->Link;\n",
     "    (void)0;\n"),
    ("drain_wrong_pool", C,
     "        bSlotFree(pool, n);\n",
     "        bSlotFree(TrackGraphRoadBlockInfoSlotPool, n);\n"),
    ("drain_no_unlink", C,
     "        n->next->prev = n->prev;\n",
     "        (void)0;\n"),
    # ---- AddVertex and GetVertexNumber
    ("vertex_fwd1_0", C,
     "    v->ForwardEdgeIndecies[1] = -1;\n",
     "    v->ForwardEdgeIndecies[1] = 0;\n"),
    ("vertex_point_off", C,
     "    v->nRoutePointNumber = (int32_t)(p - r->TrackRoutePointTable);\n",
     "    v->nRoutePointNumber = (int32_t)(p - r->TrackRoutePointTable) + 1;\n"),
    ("vertex_ratio", C,
     "    v->fDistanceAroundTrack = c.DistanceAroundTrack;\n",
     "    v->fDistanceAroundTrack = c.RatioAroundTrack;\n"),
    ("vnum_point_ge", C,
     "        if (v->nRouteNumber == route && v->nRoutePointNumber == point)\n",
     "        if (v->nRouteNumber == route && v->nRoutePointNumber >= point)\n"),
    ("vnum_no_target", C,
     "            && v->pSignpost->NewPoint == point)\n",
     "            && v->pSignpost->NewPoint == point + 1)\n"),
    ("vnum_target_route", C,
     "        if (v->pSignpost->NewRoute == route\n",
     "        if (v->pSignpost->NewRoute == point\n"),
    ("vnum_skip_last", C,
     "    for (i = 0; i < g->nNumVerticies; ++i) {\n        const tTrackGraphVertex *v = &g->Vertex[i];\n",
     "    for (i = 0; i < g->nNumVerticies - 1; ++i) {\n        const tTrackGraphVertex *v = &g->Vertex[i];\n"),
    # ---- AddEdge
    ("edge_cloakable_0", C,
     "    e->bCloakable = cloaked;\n",
     "    e->bCloakable = 0;\n"),
    ("edge_cloaked_0", C,
     "    e->bIsCloaked = cloaked;\n",
     "    e->bIsCloaked = 0;\n"),
    ("edge_route_unfollowed", C,
     "    e->nRouteNumber = follow ? (int32_t)v->pSignpost->NewRoute\n",
     "    e->nRouteNumber = !follow ? (int32_t)v->pSignpost->NewRoute\n"),
    ("edge_first_unfollowed", C,
     "    e->nFirstRoutePoint = follow ? (int32_t)v->pSignpost->NewPoint\n",
     "    e->nFirstRoutePoint = !follow ? (int32_t)v->pSignpost->NewPoint\n"),
    ("edge_heli_0", C,
     "    e->bHelisheet = 1;\n",
     "    e->bHelisheet = 0;\n"),
    ("edge_route0_null", C,
     "    r = e->nRouteNumber >= 0\n",
     "    r = e->nRouteNumber > 0\n"),
    ("edge_skip_first", C,
     "    for (i = e->nFirstRoutePoint; i < r->NumPoints; ++i) {\n",
     "    for (i = e->nFirstRoutePoint + 1; i < r->NumPoints; ++i) {\n"),
    ("edge_skip_end", C,
     "    for (i = e->nFirstRoutePoint; i < r->NumPoints; ++i) {\n",
     "    for (i = e->nFirstRoutePoint; i < r->NumPoints - 1; ++i) {\n"),
    ("edge_heli_bit", C,
     "        if (p->Bits & TRP_NO_HELISHEET)\n",
     "        if (p->Bits & TRP_POSTED)\n"),
    ("edge_rb_any", C,
     "        if ((p->Bits & TRP_ROADBLOCK_MASK) != TRP_ROADBLOCK_MASK)\n",
     "        if ((p->Bits & TRP_ROADBLOCK_MASK) != 0)\n"),
    ("edge_st_any", C,
     "        if ((p->Bits & TRP_RADARTRAP_MASK) != TRP_RADARTRAP_MASK)\n",
     "        if ((p->Bits & TRP_RADARTRAP_MASK) != 0)\n"),
    ("edge_rb_index", C,
     "                     (int32_t)trpoint_road_block_number(p));\n",
     "                     (int32_t)trpoint_road_block_number(p) ^ 1);\n"),
    ("edge_st_on_rb_list", C,
     "            add_tail(&e->SpeedTrapList,\n",
     "            add_tail(&e->RoadBlockList,\n"),
    ("edge_sign_at_first", C,
     "        if (i != e->nFirstRoutePoint && trpoint_has_signpost(p)) {\n",
     "        if (trpoint_has_signpost(p)) {\n"),
    ("edge_any_sign_ends", C,
     "            if (to != -1) {\n",
     "            if (1) {\n"),
    ("edge_last_off", C,
     "                e->nLastRoutePoint = i;\n",
     "                e->nLastRoutePoint = i - 1;\n"),
    ("edge_no_break", C,
     "                e->nToVertex = to;\n                break;\n",
     "                e->nToVertex = to;\n"),
    # ---- the constructor
    ("ctor_hc_garbage", C,
     "    g->bHasCloakedEdge = 0;\n    TrackGraphRoadBlockInfoSlotPool =\n",
     "    TrackGraphRoadBlockInfoSlotPool =\n"),
    ("ctor_pool_slots", C,
     "        bNewSlotPool(INFO_SLOT_SIZE, 128, \"stSlotPool\", 16);\n",
     "        bNewSlotPool(INFO_SLOT_SIZE, 64, \"stSlotPool\", 16);\n"),
    ("ctor_pool_name", C,
     "        bNewSlotPool(INFO_SLOT_SIZE, 128, \"rbSlotPool\", 16);\n",
     "        bNewSlotPool(INFO_SLOT_SIZE, 128, \"stSlotPool\", 16);\n"),
    ("ctor_pool_mem", C,
     "        bNewSlotPool(INFO_SLOT_SIZE, 128, \"rbSlotPool\", 16);\n",
     "        bNewSlotPool(INFO_SLOT_SIZE, 128, \"rbSlotPool\", 0);\n"),
    ("ctor_route_49", C,
     "    for (r = 0; r < TRACKGRAPH_NUM_ROUTES; ++r) {\n",
     "    for (r = 0; r <= TRACKGRAPH_NUM_ROUTES; ++r) {\n"),
    ("ctor_route_from_1", C,
     "    for (r = 0; r < TRACKGRAPH_NUM_ROUTES; ++r) {\n",
     "    for (r = 1; r < TRACKGRAPH_NUM_ROUTES; ++r) {\n"),
    ("ctor_back_keeps_always", C,
     "                && (s->Flags & SIGNPOST_SIGN_MASK) != SIGN_STOP)\n",
     "                && (s->Flags & SIGNPOST_SIGN_MASK) != SIGN_ALWAYS_TAKE)\n"),
    ("ctor_back_bit", C,
     "            if ((s->Flags & SIGNPOST_BACKWARDS)\n",
     "            if ((s->Flags & SIGNPOST_HAIRPIN)\n"),
    ("ctor_cloak_before_skip", C,
     "            s = trpoint_get_signpost(p);\n            if ((s->Flags & SIGNPOST_BACKWARDS)\n",
     "            s = trpoint_get_signpost(p);\n            if (s->Flags & SIGNPOST_CLOAKED)\n                g->bHasCloakedEdge = 1;\n            if ((s->Flags & SIGNPOST_BACKWARDS)\n"),
    ("ctor_cloak_no_hc", C,
     "            if (s->Flags & SIGNPOST_CLOAKED)\n                g->bHasCloakedEdge = 1;\n            add_vertex",
     "            add_vertex"),
    ("ctor_stop_back_none", C,
     "        if (sign == SIGN_STOP && !(v->pSignpost->Flags & SIGNPOST_BACKWARDS))\n",
     "        if (sign == SIGN_STOP && (v->pSignpost->Flags & SIGNPOST_BACKWARDS))\n"),
    ("ctor_stop_two", C,
     "        if (sign == SIGN_ALWAYS_TAKE || sign == SIGN_STOP) {\n",
     "        if (sign == SIGN_ALWAYS_TAKE) {\n"),
    ("ctor_dont_take_one", C,
     "        if (sign == SIGN_ALWAYS_TAKE || sign == SIGN_STOP) {\n",
     "        if (sign == SIGN_ALWAYS_TAKE || sign == SIGN_STOP || sign == SIGN_DONT_TAKE) {\n"),
    ("ctor_always_own", C,
     "            v->ForwardEdgeIndecies[0] = add_edge(g, i, 1, 0);\n",
     "            v->ForwardEdgeIndecies[0] = add_edge(g, i, 0, 0);\n"),
    ("ctor_two_follow", C,
     "            v->ForwardEdgeIndecies[0] = add_edge(g, i, 0, 0);\n",
     "            v->ForwardEdgeIndecies[0] = add_edge(g, i, 1, 0);\n"),
    ("ctor_second_uncloaked", C,
     "                g, i, 1, (v->pSignpost->Flags & SIGNPOST_CLOAKED) != 0);\n",
     "                g, i, 1, 0);\n"),
    ("ctor_back1_0", C,
     "        g->Vertex[i].BackwardEdgeIndecies[1] = -1;\n",
     "        g->Vertex[i].BackwardEdgeIndecies[1] = 0;\n"),
    ("ctor_dead_hc_1", C,
     "            g->bHasCloakedEdge = i;\n",
     "            g->bHasCloakedEdge = 1;\n"),
    ("ctor_back_first_only", C,
     "        b[b[0] != -1] = i;\n",
     "        b[0] = i;\n"),
    ("ctor_back_keep_first", C,
     "        b[b[0] != -1] = i;\n",
     "        if (b[b[0] != -1] == -1)\n            b[b[0] != -1] = i;\n"),
    ("swap_cloak_flag", C,
     "        if (g->Edge[b1].bIsCloaked)\n",
     "        if (g->Edge[b1].bHelisheet)\n"),
    ("swap_route_any", C,
     "        if (g->Edge[b1].nRouteNumber != g->Edge[f0].nRouteNumber)\n",
     "        if (g->Edge[b1].nRouteNumber != g->Edge[b1].nRouteNumber)\n"),
    ("swap_never", C,
     "        v->BackwardEdgeIndecies[1] = v->BackwardEdgeIndecies[0];\n",
     "        v->BackwardEdgeIndecies[1] = v->BackwardEdgeIndecies[1];\n"),
    ("swap_b0_lost", C,
     "        v->BackwardEdgeIndecies[1] = v->BackwardEdgeIndecies[0];\n",
     "        v->BackwardEdgeIndecies[1] = b1;\n"),
    # ---- the destructor
    ("dtor_no_st_drain", C,
     "        drain(&g->Edge[i].SpeedTrapList, TrackGraphSpeedTrapInfoSlotPool);\n",
     "        (void)0;\n"),
    ("dtor_skip_last_edge", C,
     "    for (i = 0; i < g->nNumEdges; ++i) {\n        drain(",
     "    for (i = 0; i < g->nNumEdges - 1; ++i) {\n        drain("),
    ("dtor_rb_pool_kept", C,
     "    TrackGraphRoadBlockInfoSlotPool = NULL;\n",
     "    (void)0;\n"),
    ("dtor_free_bit", C,
     "    if (flags & 1)\n        bFree(g);\n",
     "    if (flags & 2)\n        bFree(g);\n"),
    ("dtor_pools_order", C,
     "    bDeleteSlotPool(TrackGraphRoadBlockInfoSlotPool);\n    TrackGraphRoadBlockInfoSlotPool = NULL;\n    bDeleteSlotPool(TrackGraphSpeedTrapInfoSlotPool);\n",
     "    bDeleteSlotPool(TrackGraphSpeedTrapInfoSlotPool);\n    bDeleteSlotPool(TrackGraphRoadBlockInfoSlotPool);\n    TrackGraphRoadBlockInfoSlotPool = NULL;\n"),
    # ---- UncloakAllEdges
    ("uncloak_wrong_flag", C,
     "                (uint8_t)~SIGNPOST_CLOAKED;\n",
     "                (uint8_t)~SIGNPOST_BACKWARDS;\n"),
    ("uncloak_edge_kept", C,
     "            e->bIsCloaked = 0;\n",
     "            (void)0;\n"),
    ("uncloak_hc_kept", C,
     "    }\n    g->bHasCloakedEdge = 0;\n}\n",
     "    }\n}\n"),
    ("uncloak_sign_kept", C,
     "            g->Vertex[e->nFromVertex].pSignpost->Flags &=\n",
     "            g->Vertex[e->nFromVertex].pSignpost->Flags |=\n"),
    # ---- FindEdgeByRouteAndPoint
    ("fedge_cloaked_ok", C,
     "        if (e->bIsCloaked)\n            continue;\n        if (e->nRouteNumber != route)\n",
     "        if (e->nRouteNumber != route)\n"),
    ("fedge_first_open", C,
     "        if (point < e->nFirstRoutePoint)\n",
     "        if (point <= e->nFirstRoutePoint)\n"),
    ("fedge_last_open", C,
     "        if (e->nLastRoutePoint < point)\n",
     "        if (e->nLastRoutePoint <= point)\n"),
    ("fedge_route_any", C,
     "        if (e->nRouteNumber != route)\n            continue;\n",
     "        if (e->nRouteNumber == -2)\n            continue;\n"),
    # ---- the finds
    ("car_route_find0", C,
     "    TrackRoute      *r = car_get_route(car, 1);\n",
     "    TrackRoute      *r = car_get_route(car, 0);\n"),
    ("car_point_find0", C,
     "    TrackRoutePoint *p = car_get_route_point(car, 1);\n",
     "    TrackRoutePoint *p = car_get_route_point(car, 0);\n"),
    ("next_ends_swapped", C,
     "    int32_t v = forward ? e->nToVertex : e->nFromVertex;\n",
     "    int32_t v = forward ? e->nFromVertex : e->nToVertex;\n"),
    ("next_fwd1", C,
     "    n = forward ? g->Vertex[v].ForwardEdgeIndecies[0]\n",
     "    n = forward ? g->Vertex[v].ForwardEdgeIndecies[1]\n"),
    ("next_back1", C,
     "                : g->Vertex[v].BackwardEdgeIndecies[0];\n",
     "                : g->Vertex[v].BackwardEdgeIndecies[1];\n"),
    ("next_dead_end_reads", C,
     "    if (v < 0)\n        return NULL;\n",
     "    if (v < -1)\n        return NULL;\n"),
    ("range_fwd_swapped", C,
     "    float d = forward ? get_forward_track_distance(spot, car)\n",
     "    float d = forward ? get_forward_track_distance(car, spot)\n"),
    ("range_back_swapped", C,
     "                      : get_forward_track_distance(car, spot);\n",
     "                      : get_forward_track_distance(spot, car);\n"),
    ("range_max_closed", C,
     "    return d < fMax && fMin <= d;\n",
     "    return d <= fMax && fMin <= d;\n"),
    ("range_min_open", C,
     "    return d < fMax && fMin <= d;\n",
     "    return d < fMax && fMin < d;\n"),
    ("range_max_nan", C,
     "    return d < fMax && fMin <= d;\n",
     "    return !(d >= fMax) && fMin <= d;\n"),
    ("range_min_nan", C,
     "    return d < fMax && fMin <= d;\n",
     "    return d < fMax && !(d < fMin);\n"),
    ("rb_no_clear_check", C,
     "            if (!is_teleport_location_clear(&rb->v2Position))\n                continue;\n",
     ""),
    ("rb_index_off", C,
     "                pCopManager, ((tTrackGraphInfo *)n)->nIndexIntoLoadedData);\n\n            if (rb == NULL)\n",
     "                pCopManager, ((tTrackGraphInfo *)n)->nIndexIntoLoadedData + 1);\n\n            if (rb == NULL)\n"),
    ("rb_four_edges", C,
     "            return rb;\n        }\n        if (++steps >= 5)\n",
     "            return rb;\n        }\n        if (++steps >= 4)\n"),
    ("st_six_edges", C,
     "            return st;\n        }\n        if (++steps >= 5)\n",
     "            return st;\n        }\n        if (++steps >= 6)\n"),
    ("rb_ratio", C,
     "    d = car->TheTrackPathCoordinate.DistanceAroundTrack;\n    for (;;) {\n        bNode *n;\n\n        for (n = e->RoadBlockList.next;",
     "    d = car->TheTrackPathCoordinate.RatioAroundTrack;\n    for (;;) {\n        bNode *n;\n\n        for (n = e->RoadBlockList.next;"),
    ("st_dir_flipped", C,
     "            if (!in_range(st->fDistanceAroundTrack, d, fMin, fMax, forward))\n",
     "            if (!in_range(st->fDistanceAroundTrack, d, fMin, fMax, !forward))\n"),
    ("st_always_forward", C,
     "            return st;\n        }\n        if (++steps >= 5)\n            return NULL;\n        e = next_edge(g, e, forward);\n",
     "            return st;\n        }\n        if (++steps >= 5)\n            return NULL;\n        e = next_edge(g, e, 1);\n"),
    ("st_on_rb_list", C,
     "        for (n = e->SpeedTrapList.next; n != &e->SpeedTrapList;\n",
     "        for (n = e->RoadBlockList.next; n != &e->RoadBlockList;\n"),
    ("rb_distance_off", C,
     "            if (!in_range(rb->fDistanceAroundTrack, d, fMin, fMax, forward))\n",
     "            if (!in_range(rb->fDistanceAroundTrack + 0.5f, d, fMin, fMax, forward))\n"),
    # ---- the rest
    ("init_pool_0", C,
     "        (tTrackGraph *)bMalloc((int)sizeof(tTrackGraph), \"TrackGraph\", 0,\n                               16));\n",
     "        (tTrackGraph *)bMalloc((int)sizeof(tTrackGraph), \"TrackGraph\", 0,\n                               0));\n"),
    ("cleanup_flags_2", C,
     "        ((DtorFn)e->fn)(vt_this(g, e), 3);\n",
     "        ((DtorFn)e->fn)(vt_this(g, e), 2);\n"),
    ("cleanup_keeps_pointer", C,
     "    }\n    TheTrackGraph = NULL;\n}\n",
     "    }\n}\n"),
    ("hasc_bool", C,
     "    return g->bHasCloakedEdge;\n",
     "    return g->bHasCloakedEdge != 0;\n"),
    ("getv_off", C,
     "    return &g->Vertex[i];\n",
     "    return &g->Vertex[i + 1];\n"),
    ("gete_off", C,
     "    return &g->Edge[i];\n}\n",
     "    return &g->Edge[i ^ 1];\n}\n"),
    # ---- coputil
    ("gftd_le", U,
     "    if (d < 0.0f)\n",
     "    if (d <= 0.0f)\n"),
    ("gftd_minus", U,
     "        d += TheTrackPathManager.TrackLength;\n",
     "        d -= TheTrackPathManager.TrackLength;\n"),
    ("gftd_order", U,
     "    float d = a - b;\n",
     "    float d = b - a;\n"),
    ("clear_250_le", U,
     "    if (world_get_distance_to_closest_player_2d(w, p) < 250.0f)\n",
     "    if (world_get_distance_to_closest_player_2d(w, p) <= 250.0f)\n"),
    ("clear_15_le", U,
     "        if (sqrtf(dx * dx + dy * dy) < 15.0f)\n",
     "        if (sqrtf(dx * dx + dy * dy) <= 15.0f)\n"),
    ("clear_skip_last_car", U,
     "    for (i = 0; i < pCurrentWorld->TotalNumCars; ++i) {\n",
     "    for (i = 0; i < pCurrentWorld->TotalNumCars - 1; ++i) {\n"),
    ("clear_dy_x", U,
     "        float dy = p->y - c->State.Position.y;\n",
     "        float dy = p->y - c->State.Position.x;\n"),
    ("clear_player_ok", U,
     "        return 0;\n    for (i = 0;",
     "        return 1;\n    for (i = 0;"),
    ("clear_player_nan", U,
     "    if (world_get_distance_to_closest_player_2d(w, p) < 250.0f)\n",
     "    if (!(world_get_distance_to_closest_player_2d(w, p) >= 250.0f))\n"),
    ("clear_car_nan", U,
     "        if (sqrtf(dx * dx + dy * dy) < 15.0f)\n",
     "        if (!(sqrtf(dx * dx + dy * dy) >= 15.0f))\n"),
    ("dsi_lt_first", U,
     "    if (!(s0 * s1 <= 0.0f))\n",
     "    if (!(s0 * s1 < 0.0f))\n"),
    ("dsi_lt_second", U,
     "    return s0 * s1 <= 0.0f;\n",
     "    return s0 * s1 < 0.0f;\n"),
    ("dsi_nan_first", U,
     "    if (!(s0 * s1 <= 0.0f))\n",
     "    if (s0 * s1 > 0.0f)\n"),
    ("dsi_nan_second", U,
     "    return s0 * s1 <= 0.0f;\n",
     "    return !(s0 * s1 > 0.0f);\n"),
    ("dsi_double_first", U,
     "    if (!(s0 * s1 <= 0.0f))\n",
     "    if (!((double)s0 * s1 <= 0.0))\n"),
    ("dsi_double_second", U,
     "    return s0 * s1 <= 0.0f;\n",
     "    return (double)s0 * s1 <= 0.0;\n"),
    ("dsi_no_second", U,
     "    return s0 * s1 <= 0.0f;\n",
     "    return 1;\n"),
    ("dsi_q2x_minus", U,
     "    float q2x = q->x + e->x, q2y = q->y + e->y;\n",
     "    float q2x = q->x - e->x, q2y = q->y + e->y;\n"),
    ("dsi_q2y_minus", U,
     "    float q2x = q->x + e->x, q2y = q->y + e->y;\n",
     "    float q2x = q->x + e->x, q2y = q->y - e->y;\n"),
    ("dsi_p2y_minus", U,
     "    p2y = p->y + d->y;\n",
     "    p2y = p->y - d->y;\n"),
    ("dsi_s1_q", U,
     "    s1 = (q2x - p->x) * d->y - (q2y - p->y) * d->x;\n",
     "    s1 = (q->x - p->x) * d->y - (q2y - p->y) * d->x;\n"),
    ("dsi_s1_assoc", U,
     "    s1 = (q2x - p->x) * d->y - (q2y - p->y) * d->x;\n",
     "    s1 = (q->x - p->x + e->x) * d->y - (q2y - p->y) * d->x;\n"),
    ("dsi_s1b_assoc", U,
     "    s1 = (p2x - q->x) * e->y - (p2y - q->y) * e->x;\n",
     "    s1 = (p2x - q->x) * e->y - (p->y - q->y + d->y) * e->x;\n"),
    ("dsi_s0_swap", U,
     "    s0 = (q->x - p->x) * d->y - (q->y - p->y) * d->x;\n",
     "    s0 = (q->x - p->x) * d->x - (q->y - p->y) * d->y;\n"),
    ("dsi_s0_sign", U,
     "    s0 = (q->x - p->x) * d->y - (q->y - p->y) * d->x;\n",
     "    s0 = (q->y - p->y) * d->x - (q->x - p->x) * d->y;\n"),
    ("dsi_s0b_sign", U,
     "    s0 = (p->x - q->x) * e->y - (p->y - q->y) * e->x;\n",
     "    s0 = (p->y - q->y) * e->x - (p->x - q->x) * e->y;\n"),
    ("dsi_s0b_e_d", U,
     "    s0 = (p->x - q->x) * e->y - (p->y - q->y) * e->x;\n",
     "    s0 = (p->x - q->x) * d->y - (p->y - q->y) * e->x;\n"),
    ("dsi_s1b_p", U,
     "    s1 = (p2x - q->x) * e->y - (p2y - q->y) * e->x;\n",
     "    s1 = (p2x - q->x) * e->y - (p->y - q->y) * e->x;\n"),
    ("dsi_s0_neg", U,
     "    s0 = (q->x - p->x) * d->y - (q->y - p->y) * d->x;\n",
     "    s0 = (p->x - q->x) * d->y - (p->y - q->y) * d->x;\n"),
    ("dsi_first_return", U,
     "    if (!(s0 * s1 <= 0.0f))\n        return 0;\n",
     "    if (!(s0 * s1 <= 0.0f))\n        return 1;\n"),
]

EQUIVALENT = {}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    indir = tempfile.TemporaryDirectory()
    lines = script(indir.name)
    base = model(lines)
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
        todo, SOURCES, "trackgraph_test",
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

    with tempfile.TemporaryDirectory() as tmp:
        lines = script(tmp)
        got = model(lines)
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
