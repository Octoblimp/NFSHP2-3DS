#!/usr/bin/env python3
"""Cross-check 3DS Files/source/track.c and terraintype.c -- the track's
collision surface, its markers, its info table and its road noise --
against the image itself, run in mipsemu.

The model is the image: every Track.obj function but the two exit-time
destructors runs as shipped, with bWare's slot pool, bVector and
bStringHash beneath it, and TerrainType.obj's two lookups beside it. The
harness runs the same op script on the port and prints the same lines.
Every float goes both ways as its bits.

**The floats.** `Emu(ieee=True, eediv=True)`. track.c divides plainly --
the normal's reciprocal square root in the TrackPolygon constructor and
GetElevation's divide by the normal's z are the two a bad polygon could
zero -- so the checker holds the image to that: after the run no division
in Track.obj may have taken the EE's divide-by-zero path, and every one of
TRACKB12's 15708 polygons is counted for a non-zero normal and, unless it
is a wall, a non-zero normal z.

**The pool.** InitTree makes a 1024-slot pool of TrackPolygons. In the
model bMalloc hands every pool the same fixed block, zeroed; the harness's
bSetSlotPoolAllocator does the same with a static arena. So TrackPolygon
addresses recur from pool to pool on both sides -- the host's p32 registry
never holds more than one pool's worth -- and a pointer left over from a
closed pool labels the same way on both. Both log the allocation, the
free and every bPrintf (the pool keeps WARN_IF_NONEMPTY_DELETE). Slots
are 128 bytes in the image and 144 on the host; a TrackPolygon prints as
tpN, its slot number, which is what agrees.

**Labels, not pointers.** Chunk k's bytes print as cK+off from the chunk's
first byte; the marker list head as `markers`, the tree's list head as
`tplist`; the checker's vectors as vN. The list links the harness keeps
as p32 handles are followed, never printed.

**The chunks.** Up to eight, each in its own 1 MB window at a chosen
misalignment mod 16 -- the node and square loaders pad to the next 16-byte
boundary, so the misalignment decides their counts. TRACKB12's and
GLOBALB's own chunks load at their file offsets' misalignments.

**The ticks.** GetElevation times itself through bGetTicker and
bGetTickerDifference. Both sides draw ticks from the same LCG, and the
model runs the image's bGetTickerDifference rather than stub_bware's zero,
so TopologyTiming is compared too, differences past 2**31 included.

**What is not run.** bBreak (FlushUnusedTrackPolygons with every slot
held) is fatal on both sides -- the next AssignTrackPolygon builds into a
NULL slot -- so the model stops the run if a scenario reaches it.

Scenarios: the pure functions (GetSquareCorner, the road-noise grid and
its bilinear noise for every terrain, both MatchTerrainTypes); the track
info tables and their loader, entry 54's clear included; markers, loaded,
counted, fetched, appended and unlinked; a synthetic world -- floors,
quads, triangles whose fourth vertex is not their third, a bridge over a
floor, walls, a ceiling, INFINITELY_HIGH and Z_TIMES_FOUR polygons, a
square past 128 polygons, a lone far square for the nearest search --
through every TopologyTree, TrackPolygon and TopologyCoordinate entry
point; a malformed tree for GetSquare's nearest-with-nothing path; and
TRACKB12 itself, driven along its squares until the pool has flushed
several times over, then filled on purpose for the 101-at-a-time cap.

    python tools/track_check.py
    python tools/track_check.py --mutate [--only a,b]
    python tools/track_check.py --dump out/track
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
from bhash import bhash
from mipsemu import Emu, M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/track_test.c"
TRC = "3DS Files/source/track.c"
TRH = "3DS Files/source/track.h"
TOPH = "3DS Files/source/topology.h"
TTC = "3DS Files/source/terraintype.c"
CTC = "3DS Files/source/cartrack.c"
SOURCES = [HARNESS, TRC, TTC, CTC,
           "3DS Files/source/carstate.c",
           "3DS Files/source/emath.c",
           "3DS Files/source/bmatrix.c",
           "3DS Files/source/terraintypetab.c",
           "3DS Files/source/bslotpool.c",
           "3DS Files/source/bticker.c",
           "3DS Files/source/bvector.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c",
           "3DS Files/source/bchunk.c",
           "3DS Files/source/p32.c"]

HARNESS_TIMEOUT = 300

TRACKB12 = ROOT / "extracted" / "TRACKS" / "TRACKB12.BUN"
GLOBALB = ROOT / "extracted" / "GLOBAL" / "GLOBALB.BUN"

# ================================================================ the image

TREE = 0x002f14c8                   # TheTopologyTree
POOLVAR = 0x00323424                # TrackPolygonSlotPool
TIMING = 0x002f1530                 # TopologyTiming[10]
TIDX = 0x00323418                   # TopologyTimingIndex
MARKERS = 0x00323410                # TrackPositionMarkerList
CUR, TABLE, HIGHEST, LOADED = 0x00323428, 0x0032342c, 0x00323430, 0x00323434
TRACK_TEXT = (0x0014e7d0, 0x001509d4)
TERRAIN_TEXT = (0x001ca078, 0x001ca16c)

NCHUNK, CH_BASE, CH_SPAN = 8, 0x01000000, 0x100000
NTC, TC_BASE, TC_STRIDE = 4, 0x01900000, 0x400
NVEC, VEC_BASE = 16, 0x01910000
NH, OUTS = 16, 0x01920000           # NH * 0x200
GIPOUT = 0x01928000
CAR, CTI, FLATM = 0x01930000, 0x01930800, 0x01931000   # a Car, its type
SCR = 0x01929000                    # the out-parameters a call is handed
AIRT = SCR + 0x200                  # AverageAir's time, then its height
TERR, NORM, FOUND, DIST, BEST, OUTV = (SCR, SCR + 16, SCR + 32, SCR + 48,
                                       SCR + 64, SCR + 80)
POOLMEM, POOLSPAN = 0x01A00000, 0x40000
NSLOTS, SLOT = 1024, 128
SENTINEL = 0x5a5a5a5a
MAX_WALK = 1100

SYM = dict(
    nmark="GetNumTrackPositionMarkers__FUi",
    gmark="GetTrackPositionMarker__FUii",
    nmarkn="GetNumTrackPositionMarkers__FPCc",
    gmarkn="GetTrackPositionMarker__FPCci",
    tpinit="__12TrackPolygonP19TopologyTreePolygon",
    tpdestroy="_$_12TrackPolygon",
    shaft="PointInShaft__12TrackPolygonP8bVector3Pf",
    tpseg="SegmentIntersects__12TrackPolygonP8bVector3T1T1",
    tptest="TestSegmentToPoly__12TrackPolygonPfP8bVector3T2T2T2b",
    tcinit="__18TopologyCoordinate",
    tcdestroy="_$_18TopologyCoordinate",
    tcclear="ClearInterestBBox__18TopologyCoordinate",
    sib="SetInterestBBox__18TopologyCoordinatePC8bVector2fT1",
    elev="GetElevation__18TopologyCoordinatePC8bVector3P11TerrainType"
         "P8bVector3Pb",
    hastopo="HasTopology__18TopologyCoordinatePC8bVector2",
    tcseg="SegmentIntersects__18TopologyCoordinateP8bVector3T1f",
    constrain="ConstrainToTopology__18TopologyCoordinate15eConstraintType"
              "bP8bVector3T3ff",
    treeinit="__12TopologyTree",
    inittree="InitTree__12TopologyTree",
    closetree="CloseTree__12TopologyTree",
    ttloader="Loader__12TopologyTreeP6bChunk",
    ttunloader="Unloader__12TopologyTreeP6bChunk",
    corner="GetSquareCorner__12TopologyTreef",
    square="GetSquare__12TopologyTreeffi",
    gip="GetIntersectingPolygons__12TopologyTreePP19TopologyTreePolygoni"
        "P18TopologyTreeSquarePC8bVector2T4",
    flush="FlushUnusedTrackPolygons__12TopologyTree",
    assign="AssignTrackPolygon__12TopologyTreeP19TopologyTreePolygon",
    unassign="UnAssignTrackPolygon__12TopologyTreeP12TrackPolygon",
    build="BuildTrackPolygons__12TopologyTreePP12TrackPolygoniPC8bVector2T3",
    remove="RemoveTrackPolygons__12TopologyTreePP12TrackPolygoni",
    info="GetTrackInfo__Fi",
    grid="GetRoadNoiseGridValue__Fii",
    noise="GetRoadNoise__FP8bVector211TerrainType",
    loader="LoaderTrackGeometry__FP6bChunk",
    unloader="UnloaderTrackGeometry__FP6bChunk",
    matchname="MatchTerrainType__FPCc",
    matchhash="MatchTerrainType__FUi",
    flat="FindFlatOnTrackPosition__3CarP8bMatrix4P8bVector3Us"
         "P18TopologyCoordinate",
    putflat="PutFlatOnTrack__3Car",
    sib3="SetInterestBBox__18TopologyCoordinatePC8bVector3fT1",
    air="AverageAir__3CarRfT1",
    begin="BeginMovement__3Carf",
)

# ---- the ops -----------------------------------------------------------------

(OP_TAG, OP_CLEAR, OP_CHUNKW, OP_FILE, OP_LOADER, OP_UNLOADER,
 OP_TTLOADER, OP_TTUNLOADER, OP_MEM, OP_TREEINIT, OP_INITTREE,
 OP_CLOSETREE, OP_TREEDUMP, OP_POOL, OP_TPINIT, OP_TPDESTROY, OP_TPDUMP,
 OP_VEC, OP_SHAFT, OP_TPSEG, OP_TPTEST, OP_TCINIT, OP_TCDESTROY,
 OP_TCCLEAR, OP_TCDUMP, OP_TCPOKE, OP_TCSET, OP_SIB, OP_ELEV,
 OP_HASTOPO, OP_TCSEG, OP_CONSTRAIN, OP_CORNER, OP_SQUARE, OP_GIP,
 OP_BUILD, OP_REMOVE, OP_ASSIGN, OP_UNASSIGN, OP_FLUSH, OP_NMARK,
 OP_GMARK, OP_NMARKN, OP_GMARKN, OP_MARKDUMP, OP_INFO, OP_GLOBALS,
 OP_GRID, OP_NOISE, OP_MATCHNAME, OP_MATCHHASH, OP_TICKSEED,
 OP_HSET, OP_TPCB, OP_COG, OP_WHEEL, OP_CARPOS, OP_FLAT, OP_PUTFLAT,
 OP_SIB3, OP_CARVEC, OP_CARF, OP_AIR, OP_BEGIN) = range(64)

ARGS = {OP_TAG: 1, OP_CLEAR: 2, OP_CHUNKW: 3, OP_FILE: 5, OP_LOADER: 1,
        OP_UNLOADER: 1, OP_TTLOADER: 1, OP_TTUNLOADER: 1, OP_MEM: 3,
        OP_TREEINIT: 0, OP_INITTREE: 0, OP_CLOSETREE: 0, OP_TREEDUMP: 1,
        OP_POOL: 0, OP_TPINIT: 3, OP_TPDESTROY: 2, OP_TPDUMP: 1, OP_VEC: 5,
        OP_SHAFT: 3, OP_TPSEG: 4, OP_TPTEST: 7, OP_TCINIT: 1,
        OP_TCDESTROY: 1, OP_TCCLEAR: 1, OP_TCDUMP: 1, OP_TCPOKE: 3,
        OP_TCSET: 3, OP_SIB: 4, OP_ELEV: 3, OP_HASTOPO: 2, OP_TCSEG: 4,
        OP_CONSTRAIN: 7, OP_CORNER: 1, OP_SQUARE: 3, OP_GIP: 6,
        OP_BUILD: 4, OP_REMOVE: 2, OP_ASSIGN: 4, OP_UNASSIGN: 2,
        OP_FLUSH: 0, OP_NMARK: 1, OP_GMARK: 2, OP_NMARKN: 1, OP_GMARKN: 2,
        OP_MARKDUMP: 0, OP_INFO: 1, OP_GLOBALS: 0, OP_GRID: 2, OP_NOISE: 2,
        OP_MATCHNAME: 1, OP_MATCHHASH: 1, OP_TICKSEED: 1, OP_HSET: 3,
        OP_TPCB: 1, OP_COG: 4, OP_WHEEL: 3, OP_CARPOS: 5, OP_FLAT: 3,
        OP_PUTFLAT: 1, OP_SIB3: 4, OP_CARVEC: 5, OP_CARF: 2, OP_AIR: 4,
        OP_BEGIN: 2}
assert len(ARGS) == 64

# CARVEC's vectors: the body matrix's rows, Velocity, AngularVelocity, the
# four wheel matrices' rows, vOldVel, vOldAngVel and Position.
def car_vec(k):
    if k < 4:
        return CAR + 144 + 16 * k
    if k < 6:
        return (CAR + 112, CAR + 208)[k - 4]
    if k < 22:
        return CAR + 240 + 16 * (k - 6)
    return (CAR + 1120, CAR + 1136, CAR + 96)[k - 22]


# CARF's words: VelocityMagnitude, nWheelsTouchingGround,
# LastInTroughPosition, the type's mass and four aero numbers, and the four
# CrossedWheelTerrains.
def car_word(k):
    if k < 4:
        return (CAR + 960, CAR + 952, CAR + 1968, CAR + 1972)[k]
    if k < 9:
        return (CTI + 480, CTI + 752, CTI + 756, CTI + 760, CTI + 764)[k - 4]
    return CAR + 868 + 4 * (k - 9)


(CV_VEL, CV_ANG, CV_WHEEL, CV_OLDVEL, CV_OLDANG, CV_POS) = (4, 5, 6, 22, 23,
                                                            24)
(CF_SPEED, CF_WHEELS, CF_TROUGH, CF_MASS, CF_AERO, CF_CROSSED) = (0, 1, 2, 4,
                                                                  5, 9)


# ELEV's mask: which out-parameters are passed.
E_TERR, E_NORM, E_FOUND = 1, 2, 4


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
        self.strs = []
        self.index = {}

    def s(self, text):
        """The string table's index for `text`, adding it once."""
        if text not in self.index:
            self.index[text] = len(self.strs)
            self.strs.append(text)
        return self.index[text]

    def op(self, code, *args):
        assert len(args) == ARGS[code], (code, args)
        self.ops.append((code,) + tuple(
            fb(a) if isinstance(a, float) else int(a) & M32 for a in args))

    def tag(self, text):
        self.op(OP_TAG, self.s(text))

    def encode(self):
        out = [len(self.strs)]
        for text in self.strs:
            b = text.encode("latin-1")
            out.append(len(b))
            out.extend(b)
        flat = []
        for o in self.ops:
            flat.extend(o)
        out.append(len(flat))
        out.extend(flat)
        return struct.pack("<%di" % len(out), *[s32(v & M32) for v in out])

    # ---- sugar -----------------------------------------------------------

    def vec(self, i, x, y, z=0.0, w=0.0):
        self.op(OP_VEC, i, float(x), float(y), float(z), float(w))

    def chunk(self, k, mis, data):
        """Chunk k at misalignment `mis`, from its bytes, header and all."""
        self.op(OP_CLEAR, k, mis)
        data = data + bytes(-len(data) % 4)
        for i in range(0, len(data), 4):
            w = struct.unpack_from("<I", data, i)[0]
            if w:
                self.op(OP_CHUNKW, k, i, w)

    def elev(self, tc, v, mask=7):
        self.op(OP_ELEV, tc, v, mask)


# ================================================================ the worlds

def chunk_bytes(ctype, body, mis=0, aligned=False, extra=b""):
    """A chunk, header and all. With `aligned`, the body starts with the
    pad the node and square loaders skip, for a chunk at `mis`."""
    pad = b""
    if aligned:
        pad = bytes(((mis + 23) & ~15) - (mis + 8))
    payload = pad + body + extra
    return struct.pack("<II", ctype, len(payload)) + payload


class World(object):
    """A synthetic topology: polygons, the squares that list them, and the
    quadtree over the squares, as the four chunks."""

    def __init__(self):
        self.polys = []             # the eight words of each
        self.meta = []              # (flags, box) per polygon
        self.cells = {}             # (cx, cy) -> [polygon index]

    @staticmethod
    def cell(x, y):
        return (int(math.floor((x + 16384.0) / 32.0)),
                int(math.floor((y + 16384.0) / 32.0)))

    def poly(self, xy, z, flags=0, terrain=1, zbase=0, fourth=None, mm=None,
             cells=None, used=0, number=0x1234):
        """`xy` three or four (x, y) in world units, eighths exact; `z` the
        world heights, which ZBase and Z_TIMES_FOUR are taken out of. A
        triangle's fourth vertex is its third unless `fourth` gives one."""
        nv = 4 if flags & 0x10 else 3
        assert len(xy) == nv and len(z) == nv
        xy = list(xy)
        z = list(z)
        if nv == 3:
            fx, fy, fz = fourth if fourth is not None else (xy[2] + (z[2],))
            xy.append((fx, fy))
            z.append(fz)
        X, Y, Z = [], [], []
        for (x, y), zz in zip(xy, z):
            vx, vy = int(round(x * 8)), int(round(y * 8))
            assert vx / 8.0 == x and vy / 8.0 == y, (x, y)
            pre = zz / 4.0 if flags & 0x04 else zz
            vz = (pre - zbase) * 256.0
            assert vz == int(vz) and -32768 <= vz < 32768, (zz, zbase)
            X.append(vx)
            Y.append(vy)
            Z.append(int(vz))
        if mm is None:
            xs, ys = X[:nv], Y[:nv]
            mm = (xs.index(min(xs)) | ys.index(min(ys)) << 2
                  | xs.index(max(xs)) << 4 | ys.index(max(ys)) << 6)
        raw = struct.pack("<bBBBhh4h4h4h", used, mm, terrain, flags, zbase,
                          number, *(X + Y + Z))
        idx = len(self.polys)
        self.polys.append(raw)
        box = (X[mm & 3] / 8.0, Y[(mm >> 2) & 3] / 8.0,
               X[(mm >> 4) & 3] / 8.0, Y[mm >> 6] / 8.0)
        self.meta.append((flags, box))
        if cells is None:
            c0 = self.cell(box[0], box[1])
            c1 = self.cell(box[2], box[3])
            cells = [(cx, cy) for cx in range(c0[0], c1[0] + 1)
                     for cy in range(c0[1], c1[1] + 1)]
        for c in cells:
            self.cells.setdefault(c, []).append(idx)
        return idx

    def build(self, mis):
        """The four chunks for misalignments mis = (nodes, squares, polys,
        indices); returns them with each polygon's byte offset in its
        chunk and each square's in its."""
        order = sorted(self.cells)
        squares = [struct.pack("<ffHh", 999999.0, 999999.0, 0, 0)]
        index = []
        sqnum = {}
        for c in order:
            sqnum[c] = len(squares)
            cx, cy = c
            squares.append(struct.pack(
                "<ffHh", -16384.0 + 32 * cx + 16, -16384.0 + 32 * cy + 16,
                len(index), len(self.cells[c])))
            index.extend(self.cells[c])
        nodes = [[0, 0, 0, 0]]
        for c in order:
            cx, cy = c
            node = 0
            for lvl in range(10, 0, -1):
                q = ((cx >> (lvl - 1)) & 1) | (((cy >> (lvl - 1)) & 1) << 1)
                if lvl == 1:
                    nodes[node][q] = sqnum[c]
                    break
                if nodes[node][q] == 0:
                    nodes[node][q] = len(nodes)
                    nodes.append([0, 0, 0, 0])
                node = nodes[node][q]
        node_body = b"".join(struct.pack("<4H", *n) for n in nodes)
        c_nodes = chunk_bytes(0x34130, node_body, mis[0], True, b"\x07\x07")
        c_squares = chunk_bytes(0x34131, b"".join(squares), mis[1], True,
                                b"\x05" * 11)
        c_polys = chunk_bytes(0x34132, b"".join(self.polys), mis[2], False,
                              b"\x01" * 31)
        c_index = chunk_bytes(0x34133, struct.pack("<%dH" % len(index),
                                                   *index), mis[3], False,
                              b"\x09")
        sq_off = {c: 8 + (((mis[1] + 23) & ~15) - (mis[1] + 8)) + 12 * n
                  for c, n in sqnum.items()}
        return (c_nodes, c_squares, c_polys, c_index), sq_off

    def poly_off(self, i):
        return 8 + 32 * i


def floor_z(x, y):
    return 10.0 + x / 16.0 + y / 32.0


def world_one():
    """Floors over [0, 64)^2, a bridge, walls, a ceiling, the odd flags, a
    square past 128 polygons at [96, 128) x [0, 32), and a lone square far
    off at cell (606, 402), a flat floor under its sloped one -- x and y
    are eighths in an int16, so the world ends at +-4096."""
    w = World()
    names = {}
    terr = [1, 2, 6, 9, 3, 15, 12, 0]
    for i in range(8):
        for j in range(8):
            x0, y0 = 8.0 * i, 8.0 * j
            x1, y1 = x0 + 8.0, y0 + 8.0
            t = terr[(i + 2 * j) % len(terr)]
            zs = [floor_z(x0, y0), floor_z(x1, y0), floor_z(x1, y1),
                  floor_z(x0, y1)]
            if (i, j) == (3, 3):
                # A quad whose last edge has no length: v3 on v2.
                names["zero-edge"] = w.poly(
                    [(x0, y0), (x1, y0), (x1, y1), (x1, y1)],
                    [zs[0], zs[1], zs[2], zs[2]], flags=0x10, terrain=t)
            elif (i, j) == (5, 2):
                names["inf-quad"] = w.poly(
                    [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], zs, 0x11, t)
            elif (i, j) == (6, 6):
                names["x4-quad"] = w.poly(
                    [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                    [z + 30.0 for z in zs], 0x14, t, zbase=2)
            elif (i + j) % 3 == 0:
                w.poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], zs, 0x10, t,
                       zbase=int(zs[0]) - 4)
            else:
                # Two triangles; on some tiles the first's fourth vertex is
                # a point of its own, which GetElevation's fourth edge sees.
                odd = (i * 7 + j) % 4 == 1
                fourth = (x0 + 2.0, y1 + 3.0, zs[3]) if odd else None
                a = w.poly([(x0, y0), (x1, y0), (x1, y1)], zs[:3], 0, t,
                           fourth=fourth)
                b = w.poly([(x0, y0), (x1, y1), (x0, y1)],
                           [zs[0], zs[2], zs[3]], 0x01 if (i, j) == (1, 6)
                           else 0, t)
                if odd and "odd-fourth" not in names:
                    names["odd-fourth"] = a
                if (i, j) == (1, 6):
                    names["inf-tri"] = b
    # The bridge, over four squares' corner at (32, 32).
    names["bridge"] = w.poly([(16.0, 24.0), (48.0, 24.0), (48.0, 40.0),
                              (16.0, 40.0)], [22.0, 22.5, 22.5, 22.0],
                             0x10, 18)
    # Walls along x = 60, facing -x, and one triangular wall.
    for j in range(4):
        y0 = 16.0 * j
        w.poly([(60.0, y0 + 16.0), (60.0, y0), (60.0, y0), (60.0, y0 + 16.0)],
               [12.0, 12.0, 18.0, 18.0], 0x12, 17, zbase=10,
               mm=(0 | 1 << 2 | 0 << 4 | 0 << 6))
    names["wall-tri"] = w.poly([(40.0, 60.0), (56.0, 60.0), (48.0, 60.0)],
                               [12.0, 12.0, 20.0], 0x02, 15, zbase=11)
    # Vertical and upside down at once, beside a ceiling: SetInterestBBox's
    # second and third passes both place it, the third because the ceiling
    # left the count short.
    names["wall-ud"] = w.poly([(20.0, 50.0), (28.0, 50.0), (24.0, 50.0)],
                              [14.0, 14.0, 19.0], 0x0a, 16, zbase=13)
    names["ceiling-ud"] = w.poly([(22.0, 46.0), (22.0, 49.0), (26.0, 49.0),
                                  (26.0, 46.0)], [18.0, 18.0, 18.0, 18.0],
                                 0x18, 14, zbase=17)
    # The ceiling: clockwise, so its normal points down.
    names["ceiling"] = w.poly([(8.0, 8.0), (8.0, 24.0), (24.0, 24.0),
                               (24.0, 8.0)], [16.0, 16.0, 16.5, 16.5],
                              0x18, 14, zbase=14)
    # The dense square: 140 slivers in [96, 128) x [0, 32).
    for k in range(140):
        x0 = 96.0 + (k % 28) * 1.125
        y0 = (k // 28) * 6.25
        w.poly([(x0, y0), (x0 + 1.0, y0), (x0 + 0.5, y0 + 6.0)],
               [5.0, 5.0 + k / 64.0, 5.5], 0, 2)
    # The lone far square.
    fx, fy = 3008.0, -3520.0
    names["far"] = w.poly([(fx + 4, fy + 4), (fx + 28, fy + 4),
                           (fx + 28, fy + 28), (fx + 4, fy + 28)],
                          [100.0, 100.0, 101.0, 101.0], 0x10, 5, zbase=100)
    # Flat, at height 0, under the middle of it: the one floor below
    # HasTopology's reach if its probe started at 0 rather than 99999. Its
    # sides are 16, so the normal is exactly (0, 0, 1) and a vertical
    # segment through it crosses at an exact distance.
    names["far-low"] = w.poly([(fx + 8, fy + 8), (fx + 24, fy + 8),
                               (fx + 24, fy + 24), (fx + 8, fy + 24)],
                              [0.0, 0.0, 0.0, 0.0], 0x10, 2)
    return w, names


# ================================================================ the script


CORNER_VALS = [0.0, -0.0, 1.0, -1.0, 31.0, 31.999998, 32.0, -32.0,
               -31.999998, -32.000004, 63.9, 64.0, 100.5, -100.5, 16383.99,
               16384.0, -16384.0, 30000.0, -30000.0, 32767.0, -32768.0,
               40000.0, -40000.0, 1e-30, -1e-30, 1.5e5, -1.5e5]


def scenario_pure(sc, rnd):
    sc.tag("corner")
    for f in CORNER_VALS:
        sc.op(OP_CORNER, f)
    for _ in range(40):
        sc.op(OP_CORNER, rnd.uniform(-20000.0, 20000.0))

    sc.tag("grid")
    for x in (-3, -2, -1, 0, 1, 2, 3, 17, 65535, -65536, 0x7fffffff,
              -0x80000000):
        for y in (-2, -1, 0, 1, 5, 0x7ffffffe, -0x7fffffff):
            sc.op(OP_GRID, x, y)
    for _ in range(40):
        sc.op(OP_GRID, rnd.randint(-5000, 5000), rnd.randint(-5000, 5000))

    sc.tag("noise")
    pts = [(0.0, 0.0), (0.5, 0.25), (-0.5, -0.25), (3.0, 7.0), (-3.0, -7.0),
           (12.75, -8.125), (1000.3, 2000.7), (-4096.1, 55.9),
           (1e-7, -1e-7), (0.999999, -0.999999)]
    for k, (x, y) in enumerate(pts):
        sc.vec(k % NVEC, x, y)
    for t in range(33):
        for k in range(len(pts)):
            sc.op(OP_NOISE, k, t)
    for k in range(6):
        sc.vec(k, rnd.uniform(-900.0, 900.0), rnd.uniform(-900.0, 900.0))
        for t in (0, 1, 2, 6, 9, 15, 21, 31, 32):
            sc.op(OP_NOISE, k, t)
    # Where the floor's correction shows: at an integer it does nothing,
    # but past 2^24 an integer minus one rounds, so taking one off there
    # moves to another row.
    for x, y in ((0.5, 16777218.0), (16777218.0, 0.5), (0.5, -16777218.0),
                 (3.25, 16777216.0), (0.5, 7.0)):
        sc.vec(0, x, y)
        for t in (2, 19):
            sc.op(OP_NOISE, 0, t)
    # Enough fractions for the weights' rounding to show.
    for _ in range(120):
        sc.vec(0, rnd.uniform(-4096.0, 4096.0), rnd.uniform(-4096.0, 4096.0))
        for t in (2, 12, 19):
            sc.op(OP_NOISE, 0, t)

    sc.tag("terrain names")
    names = ["NONE", "ROAD", "DIRT", "DIRTROAD", "PUDDLE", "DEEP_WATER",
             "GRASS", "SAND", "SNOW", "DIRT_SHOULDER", "SAND_SHOULDER",
             "SNOW_SHOULDER", "SIDEWALK", "SNOW_SIDEWALK", "ROCK",
             "WOOD_WALL", "CACTUS_WALL", "SOLID_WALL", "BOARDWALK",
             "COBBLESTONE", "MUD_PUDDLE", "ROUGH_ROAD", "GRASS_SHOULDER",
             "AUTUMN_LEAVES", "AUTUMN_LEAVES_SHOULDER", "MULCH",
             "MULCH_SHOULDER", "ROAD_AUTUMN", "PLANT", "POST", "METAL_GRATE",
             "POTHOLE", "CAR"]
    probes = names + [n.lower() for n in names] + [
        "Road", "rOaD", "", "ROA", "ROADS", "ROAD ", " ROAD", "DIRT_",
        "SNOW_SIDEWALKS", "car", "C", "\xe9ROAD", "ROAD\xe9", "\xff",
        "GRASS_SHOULDEr", "{ROAD", "ROAD`", "@", "["]
    sc.op(OP_MATCHNAME, -1)
    for p in probes:
        sc.op(OP_MATCHNAME, sc.s(p))
    for n in names:
        sc.op(OP_MATCHHASH, bhash(n))
        sc.op(OP_MATCHHASH, bhash(n.lower()))
    for h in (0, 1, 0xffffffff, 0x12345678):
        sc.op(OP_MATCHHASH, h)


def info_record(name, number, loc="", valid=1):
    b = bytearray(160)
    nb = name.encode("latin-1")[:31]
    b[0:len(nb)] = nb
    lb = loc.encode("latin-1")[:31]
    b[32:32 + len(lb)] = lb
    # SameAsTrackNumber is not TrackNumber, so the loader's pick shows.
    struct.pack_into("<bbbbhh", b, 64, valid, number, (number + 64) & 0x7f, 0,
                     3, 7)
    struct.pack_into("<f", b, 80, 1234.5 + number)
    b[128:131] = b"RGN"
    return bytes(b)


def scenario_info(sc):
    sc.tag("info: empty")
    sc.op(OP_GLOBALS)
    for i in (-1, 0, 1, 54):
        sc.op(OP_INFO, i)

    sc.tag("info: sixty tracks")
    recs = []
    for n in range(1, 61):
        name = "" if n in (7, 33) else "Track %d" % n
        recs.append(info_record(name, n, "Loc %d" % n))
    sc.chunk(0, 0, chunk_bytes(0x34201, b"".join(recs), extra=b"\x01" * 100))
    sc.op(OP_MEM, 0, 8 + 160 * 53, 40)
    sc.op(OP_LOADER, 0)
    sc.op(OP_GLOBALS)
    sc.op(OP_MEM, 0, 8 + 160 * 53, 40)
    sc.op(OP_MEM, 0, 8 + 160 * 52, 4)
    sc.op(OP_MEM, 0, 8 + 160 * 54, 4)
    for i in list(range(-2, 64)) + [0x7fffffff, -0x80000000]:
        sc.op(OP_INFO, i)

    sc.tag("info: this track")
    sc.chunk(1, 4, chunk_bytes(0x34200, info_record("Here", 12, "There")))
    sc.op(OP_LOADER, 1)
    sc.op(OP_GLOBALS)
    sc.chunk(2, 8, chunk_bytes(0x34200, info_record("Neg", -5, "")))
    sc.op(OP_LOADER, 2)
    sc.op(OP_GLOBALS)
    sc.op(OP_UNLOADER, 2)
    sc.op(OP_GLOBALS)
    sc.op(OP_UNLOADER, 0)
    sc.op(OP_GLOBALS)
    sc.op(OP_INFO, 1)

    sc.tag("info: thirty tracks")
    recs = [info_record("T%d" % n, n) for n in range(1, 31)]
    sc.chunk(3, 12, chunk_bytes(0x34201, b"".join(recs)))
    sc.op(OP_LOADER, 3)
    sc.op(OP_GLOBALS)
    for i in (29, 30, 31, 54):
        sc.op(OP_INFO, i)
    sc.op(OP_UNLOADER, 3)
    sc.op(OP_UNLOADER, 1)
    sc.op(OP_GLOBALS)

    sc.tag("info: fifty-four exactly")
    recs = [info_record("F%d" % n, n) for n in range(1, 55)]
    sc.chunk(4, 0, chunk_bytes(0x34201, b"".join(recs)))
    sc.op(OP_LOADER, 4)
    sc.op(OP_MEM, 0 + 4, 8 + 160 * 53, 40)
    sc.op(OP_INFO, 54)
    sc.op(OP_INFO, 53)
    sc.op(OP_UNLOADER, 4)

    sc.tag("info: not ours")
    for k, t in enumerate((0x34202, 0x34145, 0x34147, 0x3412f, 0x34134,
                           0x80034130, 0)):
        sc.chunk(5, 4 * (k % 4), chunk_bytes(t, bytes(48)))
        sc.op(OP_LOADER, 5)
        sc.op(OP_UNLOADER, 5)
    sc.op(OP_GLOBALS)


def marker_bytes(marks, junk=0x11111111):
    out = b""
    for h, param, x, y in marks:
        out += struct.pack("<IIIiff", junk, junk + 1, h, param, x, y)
    return out


def scenario_markers(sc):
    A, B, C = bhash("StartGrid"), bhash("CopSpawn"), bhash("Finish")
    sc.tag("markers: empty")
    sc.op(OP_MARKDUMP)
    sc.op(OP_NMARK, A)
    sc.op(OP_GMARK, A, 0)

    sc.tag("markers: one chunk")
    first = [(A, 0, 1.0, 2.0), (B, 0, -5.5, 3.25), (A, 1, 7.0, 8.0),
             (C, 9, 0.0, -0.0), (A, 2, 1e5, -1e5), (B, 1, 4.0, 4.0),
             (0, 0, 0.0, 0.0)]
    sc.chunk(0, 0, chunk_bytes(0x34146, marker_bytes(first), extra=b"\x03" * 20))
    sc.op(OP_LOADER, 0)
    sc.op(OP_MARKDUMP)
    for h in (A, B, C, 0, 0xdeadbeef):
        sc.op(OP_NMARK, h)
        for i in (-1, 0, 1, 2, 3, 7):
            sc.op(OP_GMARK, h, i)
    for n in ("StartGrid", "CopSpawn", "Finish", "startgrid", ""):
        sc.op(OP_NMARKN, sc.s(n))
        for i in (0, 1, 2, 5):
            sc.op(OP_GMARKN, sc.s(n), i)

    sc.tag("markers: appended")
    second = [(C, 1, 9.0, 9.0), (A, 3, 10.0, 11.0)]
    sc.chunk(1, 8, chunk_bytes(0x34146, marker_bytes(second, 0x22222222)))
    sc.op(OP_LOADER, 1)
    sc.op(OP_MARKDUMP)
    sc.op(OP_NMARK, A)
    sc.op(OP_GMARK, A, 3)
    sc.op(OP_GMARK, C, 1)

    sc.tag("markers: first unloaded")
    sc.op(OP_UNLOADER, 0)
    sc.op(OP_MARKDUMP)
    sc.op(OP_NMARK, A)
    sc.op(OP_GMARK, A, 0)
    sc.op(OP_LOADER, 0)
    sc.op(OP_MARKDUMP)
    sc.op(OP_UNLOADER, 1)
    sc.op(OP_MARKDUMP)
    sc.op(OP_UNLOADER, 0)
    sc.op(OP_MARKDUMP)

    sc.tag("markers: an empty chunk")
    sc.chunk(2, 4, chunk_bytes(0x34146, b"\x01" * 23))
    sc.op(OP_LOADER, 2)
    sc.op(OP_MARKDUMP)
    sc.op(OP_UNLOADER, 2)
    sc.op(OP_MARKDUMP)


# ---- the synthetic world ------------------------------------------------------

W_MIS = (4, 8, 12, 0)               # nodes, squares, polys, indices


def load_world(sc, w, mis=W_MIS, base=0):
    chunks, sq_off = w.build(mis)
    for k, (c, m) in enumerate(zip(chunks, mis)):
        sc.chunk(base + k, m, c)
    return sq_off


def scenario_world(sc, rnd):
    w, names = world_one()
    sq_off = load_world(sc, w)
    NODES, SQS, POLYS, IDX = 0, 1, 2, 3
    npolys = len(w.polys)

    sc.tag("world: load")
    sc.op(OP_TREEDUMP, 0)
    for k in (NODES, SQS, POLYS, IDX):
        sc.op(OP_LOADER, k)
    sc.op(OP_TREEDUMP, 1)
    for i in (0, 1, npolys - 1):
        sc.op(OP_MEM, POLYS, w.poly_off(i), 2)
    sc.op(OP_POOL)
    sc.op(OP_INITTREE)
    sc.op(OP_POOL)
    sc.op(OP_GLOBALS)

    sc.tag("world: squares")
    pts = [(0.0, 0.0), (-0.0, -0.0), (1.0, 1.0), (31.9, 31.9), (32.0, 32.0),
           (63.99, 0.5), (64.0, 0.5), (100.0, 10.0), (127.9, 31.9),
           (128.0, 0.0), (-1.0, 5.0), (5.0, -1.0), (-5000.0, -5000.0),
           (5000.0, 5000.0), (3022.0, -3506.0), (3008.0, -3520.0),
           (3042.0, -3536.0), (16384.0, 16384.0), (-16384.0, -16384.0),
           (20000.0, -20000.0), (-20000.0, 20000.0), (float("nan"), 3.0),
           (40.0, float("nan"))]
    for _ in range(30):
        pts.append((rnd.uniform(-10.0, 140.0), rnd.uniform(-10.0, 70.0)))
    for x, y in pts:
        for near in (0, 1):
            sc.op(OP_SQUARE, x, y, near)

    sc.tag("world: gather")
    cells = sorted(sq_off)
    boxes = [((0.0, 0.0), (31.0, 31.0)), ((20.0, 20.0), (40.0, 40.0)),
             ((8.0, 8.0), (8.0, 8.0)), ((-10.0, -10.0), (0.0, 0.0)),
             ((33.0, 1.0), (47.5, 30.0)), ((96.0, 0.0), (128.0, 32.0)),
             ((10.0, 10.0), (5.0, 5.0)), ((-1e9, -1e9), (1e9, 1e9))]
    for c in cells:
        for bi, (mn, mx) in enumerate(boxes):
            sc.vec(0, *mn)
            sc.vec(1, *mx)
            for mxn in ((128, 3) if bi % 3 == 0 else (128,)):
                sc.op(OP_GIP, SQS, sq_off[c], 0, 1, mxn, 0)
    sc.vec(0, -1e9, -1e9)
    sc.vec(1, 1e9, 1e9)
    sc.op(OP_GIP, -1, 0, 0, 1, 128, 0)
    sc.op(OP_GIP, SQS, sq_off[cells[0]], 0, 1, 0, 0)
    # Kept marks: the second square skips what the first listed.
    sc.vec(0, 0.0, 0.0)
    sc.vec(1, 64.0, 64.0)
    c0 = World.cell(1.0, 1.0)
    c1 = World.cell(33.0, 1.0)
    sc.op(OP_GIP, SQS, sq_off[c0], 0, 1, 128, 1)
    sc.op(OP_GIP, SQS, sq_off[c1], 0, 1, 128, 1)
    sc.op(OP_GIP, SQS, sq_off[c0], 0, 1, 128, 1)
    for i in range(npolys):
        sc.op(OP_CHUNKW, POLYS, w.poly_off(i),
              struct.unpack_from("<I", w.polys[i], 0)[0])

    sc.tag("world: standalone polygons")
    solo = [0, 1, 2, names["zero-edge"], names["inf-quad"], names["x4-quad"],
            names["odd-fourth"], names["bridge"], names["ceiling"],
            names["wall-tri"], names["far"], names["far-low"]]
    for s, p in enumerate(solo):
        slot = 1000 + s
        # A collision body left in the slot, for the constructor to clear.
        sc.op(OP_TPCB, slot)
        sc.op(OP_TPINIT, slot, POLYS, w.poly_off(p))
        sc.op(OP_TPDUMP, slot)
        sc.op(OP_MEM, POLYS, w.poly_off(p), 2)
    shaft_probe(sc, rnd, [1000 + s for s in range(len(solo))])
    far_probe(sc, 1000 + solo.index(names["far"]),
              1000 + solo.index(names["far-low"]))
    sc.op(OP_TPDESTROY, 1000, 0)
    sc.op(OP_MEM, POLYS, w.poly_off(solo[0]), 2)
    sc.op(OP_POOL)
    # Bit 2 alone: the polygon forgets its slot and the slot stays taken.
    sc.op(OP_TPDESTROY, 1001, 2)
    sc.op(OP_MEM, POLYS, w.poly_off(solo[1]), 2)
    sc.op(OP_POOL)
    sc.op(OP_CLOSETREE)
    sc.op(OP_POOL)
    sc.op(OP_INITTREE)
    for i in range(npolys):
        sc.op(OP_CHUNKW, POLYS, w.poly_off(i) + 4,
              struct.unpack_from("<I", w.polys[i], 4)[0] | 0xffff0000)

    sc.tag("world: assign")
    for i, p in enumerate((5, 6, 7, 5, names["bridge"], 6)):
        sc.op(OP_ASSIGN, 0, i, POLYS, w.poly_off(p))
    sc.op(OP_TREEDUMP, 1)
    sc.op(OP_POOL)
    for i in (0, 1, 2, 4, 5):
        sc.op(OP_TPDUMP, i)
    sc.op(OP_UNASSIGN, 0, 0)
    sc.op(OP_UNASSIGN, 0, 2)
    sc.op(OP_TREEDUMP, 1)
    sc.op(OP_FLUSH)
    sc.op(OP_TREEDUMP, 1)
    sc.op(OP_POOL)
    for i in range(npolys):
        if i % 5 == 0:
            sc.op(OP_MEM, POLYS, w.poly_off(i), 2)
    # h0[0] and h0[2] let go above: seat them again, so the remove of all
    # seven below drops exactly the references the table holds.
    sc.op(OP_ASSIGN, 0, 0, POLYS, w.poly_off(8))
    sc.op(OP_ASSIGN, 0, 2, POLYS, w.poly_off(5))
    sc.op(OP_ASSIGN, 0, 6, POLYS, w.poly_off(7))
    sc.op(OP_TREEDUMP, 1)
    sc.op(OP_REMOVE, 0, 7)
    sc.op(OP_TREEDUMP, 1)
    sc.op(OP_FLUSH)
    sc.op(OP_TREEDUMP, 1)
    sc.op(OP_POOL)

    sc.tag("world: build")
    for h, ((x0, y0), (x1, y1), mx) in enumerate([
            ((1.0, 1.0), (2.0, 2.0), 128), ((30.0, 30.0), (34.0, 34.0), 128),
            ((0.0, 0.0), (63.0, 63.0), 128), ((0.0, 0.0), (63.0, 63.0), 20),
            ((96.5, 1.0), (100.0, 20.0), 128), ((90.0, -5.0), (130.0, 40.0),
                                                 128),
            ((-100.0, -100.0), (-90.0, -90.0), 128),
            ((-5.0, -5.0), (5.0, 5.0), 128),
            ((3012.0, -3516.0), (3022.0, -3506.0), 128),
            ((20.0, 20.0), (10.0, 10.0), 128)]):
        sc.vec(0, x0, y0)
        sc.vec(1, x1, y1)
        sc.op(OP_BUILD, h, 0, 1, mx)
    sc.op(OP_TREEDUMP, 1)
    sc.op(OP_POOL)
    for h, n in ((0, 1), (1, 3), (2, 50), (4, 128)):
        sc.op(OP_REMOVE, h, n)
    sc.op(OP_TREEDUMP, 1)
    sc.op(OP_FLUSH)
    sc.op(OP_TREEDUMP, 1)
    sc.op(OP_POOL)
    for h in range(10):
        sc.op(OP_HSET, 15, h, h)

    sc.tag("world: coordinate")
    sc.op(OP_TCINIT, 0)
    sc.op(OP_TCDUMP, 0)
    walk = [(4.0, 4.0), (4.5, 4.25), (12.0, 20.0), (30.0, 30.0),
            (31.5, 33.0), (20.0, 30.0), (40.0, 30.0), (50.0, 50.0),
            (59.0, 10.0), (61.0, 10.0), (100.0, 10.0), (110.0, 20.0),
            (-3.0, -3.0), (70.0, 70.0), (3020.0, -3512.0), (24.0, 47.0)]
    for x, y in walk:
        sc.vec(2, x, y)
        sc.op(OP_SIB, 0, 2, 3.0, -1)
        sc.op(OP_TCDUMP, 0)
    # Floors and the wall that is vertical and upside down, with the
    # ceiling beside it left out (the build's box is y >= 49.5): the second
    # pass places the wall and fills the count, so the third does not run.
    sc.vec(2, 24.0, 52.0)
    sc.op(OP_SIB, 0, 2, 2.0, -1)
    sc.op(OP_TCDUMP, 0)
    sc.vec(2, 12.0, 12.0)
    sc.op(OP_SIB, 0, 2, 3.0, -1)
    sc.op(OP_SIB, 0, 2, 2.0, -1)
    sc.op(OP_TCDUMP, 0)
    for r, (vx, vy) in ((1.0, (10.0, 0.0)), (1.0, (100.0, 50.0)),
                        (12.0, (0.0, 0.0)), (11.0, (3.0, 4.0)),
                        (0.5, (-1000.0, 2000.0)), (0.0, (0.0, 0.0))):
        sc.vec(3, vx, vy)
        sc.vec(2, 24.0, 28.0)
        sc.op(OP_TCCLEAR, 0)
        sc.op(OP_SIB, 0, 2, r, 3)
        sc.op(OP_TCDUMP, 0)
    sc.op(OP_TREEDUMP, 1)

    sc.tag("world: elevation")
    sc.op(OP_TICKSEED, 0xfff00000)
    sc.op(OP_TCCLEAR, 0)
    for k in range(60):
        x = rnd.uniform(0.25, 63.75)
        y = rnd.uniform(0.25, 63.75)
        z = rnd.choice([floor_z(x, y) + 0.5, 30.0, 0.0, -50.0, 22.5,
                        floor_z(x, y) - 0.99])
        sc.vec(4, x, y, z)
        sc.elev(0, 4, 7 if k % 8 else k % 7)
        if k % 10 == 0:
            sc.op(OP_TCDUMP, 0)
    # Exactly on edges and vertices, and on the bridge from above and below.
    for x, y in ((8.0, 8.0), (16.0, 4.0), (4.0, 16.0), (12.0, 12.0),
                 (24.0, 20.0), (27.0, 27.0), (26.0, 25.0), (29.0, 28.0),
                 (16.0, 24.0), (48.0, 40.0), (32.0, 32.0), (47.0, 25.0),
                 (43.0, 21.0), (44.0, 19.0), (52.0, 52.0), (18.0, 50.0),
                 (13.0, 50.0), (0.0, 0.0), (64.0, 64.0), (63.99, 0.01)):
        for z in (floor_z(x, y) + 0.5, 30.0, 21.0, -100.0):
            sc.vec(4, x, y, z)
            sc.elev(0, 4)
    sc.op(OP_TCDUMP, 0)
    # Off the world, and in the dense square.
    for x, y, z in ((70.0, 70.0, 5.0), (80.0, 10.0, 3.0), (100.0, 5.0, 6.0),
                    (100.0, 5.0, 4.0), (97.3, 0.7, 50.0), (3022.0, -3516.0,
                                                            100.5),
                    (3022.0, -3516.0, 99.0), (-2.0, -2.0, 0.0)):
        sc.vec(4, x, y, z)
        for mask in (7, 0, 1, 2, 4):
            sc.elev(0, 4, mask)
        sc.op(OP_HASTOPO, 0, 4)
    sc.op(OP_GLOBALS)
    # A long table, to see a hit at five and past it move to the front.
    sc.vec(2, 12.0, 12.0)
    sc.op(OP_SIB, 0, 2, 7.5, -1)
    sc.op(OP_TCDUMP, 0)
    for x, y in ((17.0, 18.5), (5.0, 5.0), (19.0, 3.0), (3.0, 19.0),
                 (17.0, 18.5), (11.0, 11.0), (18.9, 5.2)):
        sc.vec(4, x, y, 40.0)
        sc.elev(0, 4)
        sc.op(OP_TCDUMP, 0)

    sc.tag("world: has topology")
    for x, y in ((1.0, 1.0), (63.0, 63.0), (65.0, 65.0), (-1.0, 3.0),
                 (100.0, 16.0), (127.0, 31.0), (130.0, 2.0)):
        sc.vec(5, x, y, 1234.0)
        sc.op(OP_HASTOPO, 1, 5)
    sc.op(OP_TCDUMP, 1)

    sc.tag("world: segments")
    sc.vec(2, 24.0, 20.0)
    sc.op(OP_SIB, 2, 2, 12.0, -1)
    sc.op(OP_TCDUMP, 2)
    segs = [((20.0, 20.0, 30.0), (20.0, 20.0, 0.0)),
            ((20.0, 20.0, 0.0), (20.0, 20.0, 30.0)),
            ((30.0, 30.0, 25.0), (30.0, 30.0, 21.0)),
            ((30.0, 30.0, 21.0), (30.0, 30.0, 25.0)),
            ((12.0, 12.0, 14.0), (12.0, 12.0, 20.0)),
            ((12.0, 12.0, 20.0), (12.0, 12.0, 14.0)),
            ((10.0, 30.0, 12.0), (14.0, 30.0, 12.0)),
            ((1.0, 1.0, 1.0), (2.0, 2.0, 2.0)),
            ((16.0, 16.0, 11.5), (16.0, 16.0, 11.0))]
    for (a, b) in segs:
        sc.vec(6, *a, w=0.5)
        sc.vec(7, *b, w=-2.0)
        for r in (0.0, 0.25, 3.0):
            sc.op(OP_TCSEG, 2, 6, 7, r)
    sc.vec(2, 58.0, 20.0)
    sc.op(OP_SIB, 3, 2, 10.0, -1)
    sc.op(OP_TCDUMP, 3)
    for (a, b) in [((55.0, 20.0, 14.0), (65.0, 20.0, 14.0)),
                   ((65.0, 20.0, 14.0), (55.0, 20.0, 14.0)),
                   ((55.0, 20.0, 20.0), (65.0, 20.0, 20.0)),
                   ((48.0, 55.0, 13.0), (48.0, 65.0, 13.0)),
                   ((48.0, 65.0, 13.0), (48.0, 55.0, 13.0))]:
        sc.vec(6, *a)
        sc.vec(7, *b)
        sc.op(OP_TCSEG, 3, 6, 7, 0.5)

    sc.tag("world: constrain")
    moves = [(2, (20.0, 20.0, 30.0), (21.0, 20.5, 5.0)),
             (2, (30.0, 30.0, 25.0), (30.5, 31.0, 20.0)),
             (2, (12.0, 12.0, 13.0), (12.5, 12.0, 20.0)),
             (2, (5.0, 5.0, 12.0), (6.0, 6.0, 12.5)),
             (2, (16.0, 16.0, 11.5), (16.0, 16.0, 11.3)),
             (3, (55.0, 20.0, 14.0), (65.0, 20.0, 14.0)),
             (3, (55.0, 20.0, 14.0), (61.0, 26.0, 13.0)),
             (3, (65.0, 20.0, 14.0), (55.0, 20.0, 14.0)),
             (3, (48.0, 55.0, 13.0), (48.0, 65.0, 13.0)),
             (3, (59.5, 5.0, 12.5), (60.5, 5.0, 12.5))]
    for tc, a, b in moves:
        for typ in (0, 1, 2):
            for two in (0, 1):
                for dist, lift in ((0.3, 1.0), (2.0, -0.5)):
                    sc.vec(8, *a, w=1.5)
                    sc.vec(9, *b, w=-0.75)
                    sc.op(OP_CONSTRAIN, tc, typ, two, 8, 9, dist, lift)

    sc.tag("world: polygons in place")
    sc.op(OP_TCDUMP, 2)
    sc.op(OP_TREEDUMP, 1)
    for s in range(0, 40, 3):
        sc.op(OP_TPDUMP, s)
    sc.op(OP_POOL)

    sc.tag("world: poked table")
    sc.op(OP_TCINIT, 1)
    for f, v in enumerate((-1e6, -1e6, 1e6, 1e6, -1e6, -1e6, 1e6, 1e6)):
        sc.op(OP_TCPOKE, 1, f, fb(v))
    live = [s for s in range(0, 40)]
    for i, s in enumerate(live[:12]):
        sc.op(OP_TCSET, 1, i, s)
    sc.op(OP_TCPOKE, 1, 8, 12)
    sc.op(OP_TCPOKE, 1, 9, 12)
    sc.op(OP_TCDUMP, 1)
    for k in range(20):
        x = rnd.uniform(0.0, 64.0)
        y = rnd.uniform(0.0, 64.0)
        sc.vec(4, x, y, 50.0)
        sc.elev(1, 4)
    sc.op(OP_TCDUMP, 1)
    for s in (0, 3):
        sc.op(OP_TCSET, 1, 0, s)
        sc.op(OP_TCPOKE, 1, 9, 1)
        sc.vec(4, 1.0, 1.0, 50.0)
        sc.elev(1, 4)
    sc.op(OP_TCPOKE, 1, 8, 0)
    sc.op(OP_TCPOKE, 1, 9, 0)

    sc.tag("world: release")
    sc.op(OP_TCDESTROY, 0)
    sc.op(OP_TCDUMP, 0)
    sc.op(OP_TCCLEAR, 2)
    sc.op(OP_TCDUMP, 2)
    sc.op(OP_TCDESTROY, 3)
    sc.op(OP_TREEDUMP, 1)
    sc.op(OP_FLUSH)
    sc.op(OP_TREEDUMP, 1)
    sc.op(OP_POOL)
    sc.op(OP_CLOSETREE)
    sc.op(OP_TREEDUMP, 1)
    sc.op(OP_POOL)
    sc.op(OP_GLOBALS)
    sc.op(OP_CLOSETREE)
    for i in range(0, npolys, 7):
        sc.op(OP_MEM, POLYS, w.poly_off(i), 2)
    for k in (IDX, NODES, POLYS, SQS):
        sc.op(OP_UNLOADER, k)
        sc.op(OP_TREEDUMP, 0)
    for k in (NODES, SQS, POLYS, IDX):
        sc.op(OP_TTLOADER, k)
    sc.op(OP_TREEDUMP, 0)
    # The constructor over a loaded tree: every table and count cleared.
    sc.op(OP_TREEINIT)
    sc.op(OP_TREEDUMP, 1)
    for k in (NODES, SQS, POLYS, IDX):
        sc.op(OP_TTLOADER, k)
    for k in (NODES, SQS, POLYS, IDX):
        sc.op(OP_TTUNLOADER, k)
    sc.op(OP_TREEDUMP, 0)


def shaft_probe(sc, rnd, slots):
    """PointInShaft, SegmentIntersects and TestSegmentToPoly on built
    polygons, at their corners, centres, edges and outside."""
    pts = [(1.0, 1.0, 20.0), (4.0, 2.0, 5.0), (7.0, 7.0, 12.0),
           (0.0, 0.0, 10.0), (8.0, 0.0, 0.0), (26.0, 25.0, 12.0),
           (28.0, 30.0, 30.0), (30.0, 28.0, 10.0), (47.0, 26.0, 21.0),
           (12.0, 12.0, 17.0), (12.0, 12.0, 15.0), (48.0, 60.0, 14.0),
           (3022.0, -3516.0, 101.0), (97.0, 1.0, 4.0), (60.0, 60.0, 0.0)]
    for x, y, z in pts:
        sc.vec(10, x, y, z, 0.25)
        for s in slots:
            sc.op(OP_SHAFT, s, 10, 1)
        sc.op(OP_SHAFT, slots[0], 10, 0)
    segs = []
    for x, y, z in pts:
        segs.append(((x, y, z + 10.0), (x + 0.5, y - 0.25, z - 20.0)))
        segs.append(((x + 0.5, y - 0.25, z - 20.0), (x, y, z + 10.0)))
    segs.append(((40.0, 55.0, 14.0), (56.0, 65.0, 14.0)))
    segs.append(((56.0, 65.0, 14.0), (40.0, 55.0, 14.0)))
    for a, b in segs:
        sc.vec(11, *a, w=2.0)
        sc.vec(12, *b, w=-6.0)
        for s in slots:
            sc.op(OP_TPSEG, s, 11, 12, 1)
        sc.op(OP_TPSEG, slots[1], 11, 12, 0)
    boxes = [((-1e6, -1e6, -1e6), (1e6, 1e6, 1e6)),
             ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
             ((3.0, 3.0, 9.0), (9.0, 9.0, 11.0))]
    for a, b in segs[:12] + segs[-2:]:
        sc.vec(11, *a)
        sc.vec(12, *b)
        for mn, mx in boxes:
            sc.vec(13, *mn)
            sc.vec(14, *mx)
            for s in slots:
                for best in (1e6, 5.0):
                    sc.op(OP_TPTEST, s, best, 11, 12, 13, 14, s & 1)


def far_probe(sc, high, low):
    """The far square's two floors in a table of their own, on coordinate
    3: the sloped one five times, then the flat one at height 0 below it.
    The probes are the inputs where a detail is visible at all."""
    sc.tag("world: the far floors")
    for f, v in enumerate((-1e6, -1e6, 1e6, 1e6, -1e6, -1e6, 1e6, 1e6)):
        sc.op(OP_TCPOKE, 3, f, fb(v))
    for i, s in enumerate([high] * 5 + [low]):
        sc.op(OP_TCSET, 3, i, s)
    sc.op(OP_TCPOKE, 3, 8, 6)
    sc.op(OP_TCPOKE, 3, 9, 6)
    sc.op(OP_TCDUMP, 3)
    # HasTopology probes from 99999 down: the sloped floor, first in the
    # table, is found and the table stays as it is. From 0 only the flat
    # one would do, at index 5, and it would move to the front.
    sc.vec(5, 3024.0, -3504.0, 0.0)
    sc.op(OP_HASTOPO, 3, 5)
    sc.op(OP_TCDUMP, 3)
    # Straight down through the flat floor from 3 above: the crossing is
    # exactly 3 away, so a best of exactly 3 is not beaten.
    sc.vec(11, 3024.0, -3504.0, 3.0)
    sc.vec(12, 3024.0, -3504.0, -3.0)
    sc.vec(13, -1e6, -1e6, -1e6)
    sc.vec(14, 1e6, 1e6, 1e6)
    for best in (3.0, 3.0000002, 2.9999998):
        for two in (0, 1):
            sc.op(OP_TPTEST, low, best, 11, 12, 13, 14, two)
    # A move that crosses nothing, with a clearance past the 999999 that
    # stands for no crossing: still no crossing, so nothing is done.
    for typ in (0, 2, 1):
        sc.vec(8, 3024.0, -3504.0, 5.0)
        sc.vec(9, 3024.0, -3504.0, 4.0)
        sc.op(OP_CONSTRAIN, 3, typ, 0, 8, 9, 2e6, 0.5)
    # A negative clearance shrinks the box round the move's end, the one
    # input where the box's clearance shows: a real crossing lies inside
    # the move's own box. Here it keeps the flat floor out.
    for typ in (0, 1, 2):
        for dist in (-1.0, -0.25):
            sc.vec(8, 3024.0, -3504.0, 5.0)
            sc.vec(9, 3024.0, -3504.0, -0.5)
            sc.op(OP_CONSTRAIN, 3, typ, 1, 8, 9, dist, 0.5)
    # Nothing to release: coordinate 3 goes back to empty for the
    # segments further on.
    for f in (8, 9):
        sc.op(OP_TCPOKE, 3, f, 0)
    sc.op(OP_TCCLEAR, 3)
    sc.op(OP_TCDUMP, 3)


def scenario_bad_tree(sc, rnd):
    """A root with nothing under one quadrant and a node with no children
    at all: GetSquare's nearest search picks -1 there and walks on from
    the entry before the table. At each misalignment the node and square
    loaders pad differently."""
    for m in (0, 4, 8, 12):
        sc.tag("bad tree: misaligned %d" % m)
        nodes = [[0, 0, 0, 1], [0, 0, 0, 0]] + [[0, 0, 0, 0]] * 3
        nb = b"".join(struct.pack("<4H", *n) for n in nodes)
        sq = struct.pack("<ffHh", 1.0, 2.0, 0, 0) * 3
        sc.chunk(0, m, chunk_bytes(0x34130, nb, m, True))
        sc.chunk(1, (m + 4) % 16, chunk_bytes(0x34131, sq, (m + 4) % 16,
                                              True, b"\x01" * (m // 4)))
        sc.op(OP_TTLOADER, 0)
        sc.op(OP_TTLOADER, 1)
        sc.op(OP_TREEDUMP, 0)
        for x, y in ((-5.0, -5.0), (5.0, 5.0), (5.0, -5.0), (100.0, 9000.0)):
            sc.op(OP_SQUARE, x, y, 0)
            sc.op(OP_SQUARE, x, y, 1)
        sc.op(OP_TTUNLOADER, 0)
        sc.op(OP_TTUNLOADER, 1)
        sc.op(OP_TREEDUMP, 0)


# ---- FindFlatOnTrackPosition ----------------------------------------------------

def flat_z(x, y):
    """A slope whose steps are not powers of two, in 256ths."""
    return 5.0 + x * (77 / 256.0) - y * (179 / 256.0)


def world_flat():
    """Ground for Car::FindFlatOnTrackPosition to stand on: a skew slope
    over [0, 32)^2, two floors either side of a gap too narrow for the
    car's five samples at [40, 41.5) and another across y at [48, 49.5), a
    cliff from 0 to 300 at x = 72, and a
    floor at 30000 beside one at -40. A sample that finds nothing gets the
    probe's own z back, and that is what reaches the float rounding: the
    slopes are differences of differences, and only when one height is far
    from the others do the two spellings round apart."""
    w = World()
    for i in range(4):
        for j in range(4):
            x0, y0 = 8.0 * i, 8.0 * j
            x1, y1 = x0 + 8.0, y0 + 8.0
            zs = [flat_z(x0, y0), flat_z(x1, y0), flat_z(x1, y1),
                  flat_z(x0, y1)]
            w.poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], zs, 0x10, 1,
                   zbase=int(zs[0]))
    # The gap.
    w.poly([(32.0, 0.0), (40.0, 0.0), (40.0, 16.0), (32.0, 16.0)],
           [2.5, 2.75, 2.75, 2.5], 0x10, 2)
    w.poly([(41.5, 0.0), (56.0, 0.0), (56.0, 16.0), (41.5, 16.0)],
           [3.125, 3.0, 3.0, 3.125], 0x10, 2)
    # The cliff.
    w.poly([(64.0, 0.0), (72.0, 0.0), (72.0, 16.0), (64.0, 16.0)],
           [0.0, 0.0, 0.0, 0.0], 0x10, 3)
    w.poly([(72.0, 0.0), (80.0, 0.0), (80.0, 16.0), (72.0, 16.0)],
           [300.0, 300.0, 300.5, 300.5], 0x10, 3, zbase=300)
    # High and low, side by side in y.
    w.poly([(96.0, 0.0), (112.0, 0.0), (112.0, 8.0), (96.0, 8.0)],
           [30000.0, 30000.0, 30000.25, 30000.25], 0x10, 4, zbase=30000)
    w.poly([(96.0, 8.0), (112.0, 8.0), (112.0, 16.0), (96.0, 16.0)],
           [-40.0, -40.0, -39.5, -39.5], 0x10, 4, zbase=-40)
    # The gap again, across y, for the pitch.
    w.poly([(0.0, 40.0), (16.0, 40.0), (16.0, 48.0), (0.0, 48.0)],
           [1.375, 1.5, 1.5, 1.375], 0x10, 2)
    w.poly([(0.0, 49.5), (16.0, 49.5), (16.0, 56.0), (0.0, 56.0)],
           [0.625, 0.75, 0.75, 0.625], 0x10, 2)
    return w


FLAT_ANGLES = [0, 0x4000, 0x8000, 0xc000, 0xffff, 0x1234, 0x12345, 0xfffe0001]


def flat_probe(sc, tc, v, x, y, z, angle, vel=-1, r=3.0):
    """SetInterestBBox(bVector3) around (x, y), then FindFlatOnTrackPosition
    from (x, y, z) -- the interest box first, as Car::BeginMovement does."""
    sc.vec(v, x, y, z, 0.75)
    sc.op(OP_SIB3, tc, v, r, vel)
    sc.op(OP_FLAT, tc, v, angle)


def scenario_flat(sc, rnd):
    w = world_flat()
    load_world(sc, w)
    sc.tag("flat: load")
    for k in range(4):
        sc.op(OP_LOADER, k)
    sc.op(OP_INITTREE)
    sc.op(OP_TCINIT, 2)
    sc.op(OP_TICKSEED, 0x51ed270b)
    # Wheels[3] is the one read; the other three are there to differ.
    sc.op(OP_COG, 0.25, -0.5, 0.375, 1.5)
    for i, (z, r) in enumerate(((-0.125, 0.3), (-0.25, 0.3125),
                                (-0.3125, 0.34375), (-0.21875, 0.328125))):
        sc.op(OP_WHEEL, i, z, r)
    sc.vec(9, 5.0, -3.0, 0.0)

    sc.tag("flat: the slope")
    zs = [50.0, 1000.0, -1000.0, 8.0]
    k = 0
    for x in (4.0, 11.25, 16.0, 20.5, 27.75):
        for y in (3.5, 8.0, 15.0, 22.125, 28.0):
            flat_probe(sc, 2, 8, x, y, zs[k % 4], FLAT_ANGLES[k % 8],
                       9 if k % 3 == 0 else -1)
            k += 1
    for _ in range(40):
        flat_probe(sc, 2, 8, rnd.uniform(1.5, 30.5), rnd.uniform(1.5, 30.5),
                   rnd.choice(zs), rnd.randrange(0x10000))
    # The edges of the slope: a sample or two off it.
    for x, y in ((0.5, 16.0), (31.5, 16.0), (16.0, 0.5), (16.0, 31.5),
                 (0.0, 0.0), (31.25, 31.75)):
        for z in (40.0, 123456.78):
            flat_probe(sc, 2, 8, x, y, z, 0x2000)
    sc.op(OP_TCDUMP, 2)

    sc.tag("flat: the gap")
    for x in (40.75, 40.5, 41.0, 39.0, 42.5):
        for z in (123456.78, 1e6 + 0.5, 3.0, -77.7, 2.9e9):
            flat_probe(sc, 2, 8, x, 8.0, z, 0x0400)
    for y in (48.75, 48.5, 49.0, 47.0, 50.5):
        for z in (123456.78, 1e6 + 0.5, 3.0, -77.7, 2.9e9):
            flat_probe(sc, 2, 8, 8.0, y, z, 0xf000)
    sc.tag("flat: the cliff")
    for x in (71.0, 71.5, 72.0, 72.5, 73.0):
        for y in (8.0, 15.5):
            for z in (310.0, 5.0, 1e6):
                flat_probe(sc, 2, 8, x, y, z, 0x7ffe)
    sc.tag("flat: high and low")
    for y in (7.0, 7.5, 8.0, 8.5, 9.0):
        for z in (30010.0, 0.0, -1e5):
            flat_probe(sc, 2, 8, 100.0, y, z, 0x9000, 9)
    sc.tag("flat: nothing under it")
    for z in (0.0, 17.5, -3e7, 3e9):
        flat_probe(sc, 2, 8, 500.0, 500.0, z, 0x1111)
    sc.tag("flat: saturating")
    # One side sample in the gap or off the floor's edge and the centre on
    # it: that side's height is the probe's z, and from 3e9 the slope is
    # past 2^31 once scaled, both ways -- cvt.w.s's two saturations, each
    # through the negated x slope and the plain y one. (With the centre in
    # the gap as well, the two differences share the huge h0 and cancel.)
    for x, y in ((39.5, 8.0), (42.0, 8.0), (36.0, 15.5), (36.0, 0.5),
                 (8.0, 47.5), (8.0, 50.0)):
        for z in (3e9, -3e9, 2.1e5):
            flat_probe(sc, 2, 8, x, y, z, 0)

    sc.tag("flat: put flat on track")
    for k, (x, y, z) in enumerate(((5.0, 5.0, 60.0), (40.75, 8.0, 1234.5),
                                   (71.5, 8.0, 310.0), (100.0, 8.0, 30010.0),
                                   (500.0, 500.0, 9.0), (20.0, 27.0, -5.0))):
        sc.vec(8, x, y, z, 0.0)
        sc.op(OP_SIB3, 2, 8, 2.5, -1)
        sc.op(OP_CARPOS, x, y, z, 1.5 + k, FLAT_ANGLES[k])
        sc.op(OP_PUTFLAT, 2)
        sc.op(OP_TCDUMP, 2)
    # The same car twice: the second starts from the first's new z.
    sc.op(OP_PUTFLAT, 2)

    scenario_air(sc, random.Random(0xa1e0))

    sc.tag("flat: release")
    sc.op(OP_TCDESTROY, 2)
    sc.op(OP_CLOSETREE)
    for k in range(4):
        sc.op(OP_UNLOADER, k)
    sc.op(OP_TREEDUMP, 0)


# ---- AverageAir and BeginMovement -------------------------------------------

def rot(yaw, pitch=0.0):
    """The body matrix's first three rows for a yaw and then a pitch."""
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    return [(cy * cp, sy * cp, -sp, 0.0), (-sy, cy, 0.0, 0.0),
            (cy * sp, sy * sp, cp, 0.0)]


def air_car(sc, pos, vel, speed=None, yaw=0.5, pitch=0.0, wheels=4):
    """Set the state AverageAir and BeginMovement read. The speed is the
    velocity's length unless it is given."""
    for k, row in enumerate(rot(yaw, pitch)):
        sc.op(OP_CARVEC, k, *[f32(x) for x in row])
    sc.op(OP_CARVEC, CV_POS, f32(pos[0]), f32(pos[1]), f32(pos[2]), 0.625)
    sc.op(OP_CARVEC, CV_VEL, f32(vel[0]), f32(vel[1]), f32(vel[2]), -0.375)
    if speed is None:
        speed = math.sqrt(sum(v * v for v in vel))
    sc.op(OP_CARF, CF_SPEED, f32(speed))
    sc.op(OP_CARF, CF_WHEELS, wheels)


def begin(sc, dt):
    """BeginMovement with the fields it writes set to values it would not."""
    sc.op(OP_CARVEC, CV_OLDVEL, 111.0, 112.0, 113.0, 114.0)
    sc.op(OP_CARVEC, CV_OLDANG, 121.0, 122.0, 123.0, 124.0)
    sc.op(OP_CARF, CF_TROUGH, 131.5)
    sc.op(OP_CARF, CF_TROUGH + 1, 132.25)
    for i in range(4):
        sc.op(OP_CARF, CF_CROSSED + i, 5 + i)
    sc.op(OP_BEGIN, 2, dt)


def air(sc, time, height=77.0, alias=0):
    sc.op(OP_AIR, 2, time, height, alias)


def scenario_air(sc, rnd):
    """Car::BeginMovement and then Car::AverageAir, as FinishMovement asks
    for it, over the flat scenario's world, which is still loaded in tc 2.
    The ground under the slope is flat_z; the gap, the cliff and the
    nothing are where they were."""
    sc.tag("air: the car")
    sc.op(OP_CARF, CF_MASS, 1450.0)
    for k, v in enumerate((0.35, 1.75, 2.25, 0.5)):
        sc.op(OP_CARF, CF_AERO + k, v)
    sc.op(OP_CARVEC, CV_ANG, 0.125, -0.25, 1.5, 0.0625)
    # Each wheel matrix a little turned and set out to its corner; only
    # wheel 0's is read, the others are there to differ.
    for w, (x, y, z, turn) in enumerate(((1.25, 0.75, -0.25, 0.05),
                                         (1.25, -0.75, -0.3125, -0.075),
                                         (-1.375, 0.8125, -0.1875, 0.0),
                                         (-1.375, -0.8125, -0.375, 0.1))):
        c, sn = math.cos(turn), math.sin(turn)
        rows = [(c, sn, 0.0, 0.0), (-sn, c, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0),
                (x, y, z, 1.0)]
        for r, row in enumerate(rows):
            sc.op(OP_CARVEC, CV_WHEEL + 4 * w + r, *[f32(v) for v in row])

    sc.tag("air: begin")
    # The old velocities are kept only with time to move; the trough only
    # over the topology and with two wheels down, compared signed.
    air_car(sc, (16.0, 16.0, flat_z(16.0, 16.0) + 0.5), (3.0, -4.0, 0.5))
    for dt in (1 / 30.0, 0.0, -0.0, -0.01, 1e-30):
        begin(sc, dt)
    for wheels in (0, 1, 2, 3, -1, 0x7fffffff, 0x80000000):
        sc.op(OP_CARF, CF_WHEELS, wheels)
        begin(sc, 1 / 60.0)
    sc.op(OP_TCDUMP, 2)
    for pos in ((40.75, 8.0, 3.0), (500.0, 500.0, 0.0), (71.5, 8.0, 1.0),
                (100.0, 8.0, 30001.0), (31.75, 31.5, 0.0)):
        air_car(sc, pos, (-12.0, 30.0, 2.5))
        begin(sc, 1 / 30.0)
        sc.op(OP_TCDUMP, 2)
    # The box's size is the velocity's own length, not VelocityMagnitude.
    air_car(sc, (8.0, 24.0, 0.0), (0.0, 0.0, 0.0), speed=400.0)
    begin(sc, 1 / 30.0)
    sc.op(OP_TCDUMP, 2)
    air_car(sc, (8.0, 24.0, 0.0), (150.0, -80.0, 0.0), speed=0.0)
    begin(sc, 1 / 30.0)
    sc.op(OP_TCDUMP, 2)
    # (x x + y y) + z z: the other association is a speed one ulp over,
    # and a box two ulps wider. A square root halves a one-ulp difference,
    # so most velocities, 2^24 and two 0.765625s among them, round it away.
    air_car(sc, (8.0, 24.0, 0.0), (138.234375, 2.46875, 1.90625))
    begin(sc, 1 / 30.0)
    sc.op(OP_TCDUMP, 2)

    sc.tag("air: over the slope")
    cases = [
        # pos, vel, speed, time
        ((16.0, 16.0, 2.5), (10.0, 5.0, 4.0), None, 2.0),
        ((16.0, 16.0, 2.5), (10.0, 5.0, 4.0), None, 0.25),
        ((16.0, 16.0, 2.5), (0.0, 0.0, 0.0), 0.0, 2.0),
        ((12.0, 20.0, -4.0), (5.0, 1.0, 0.0), None, 3.0),       # under it
        ((6.0, 10.0, 8.0), (4.0, 2.0, 1.0), None, 0.75),        # n == 1
        ((6.0, 10.0, 8.0), (4.0, 2.0, 1.0), 8.0, 0.75),         # n == 2
        ((6.0, 10.0, 8.0), (4.0, 2.0, -60.0), None, 1.0),       # down at once
        ((20.0, 6.0, 12.0), (-3.0, 7.0, 9.0), 30.0, 4.0),       # a long one
        ((20.0, 6.0, 12.0), (-3.0, 7.0, 9.0), -30.0, -2.0),     # t below 0
        ((20.0, 6.0, 12.0), (-3.0, 7.0, 9.0), 1e10, -1.0),      # saturates
        # Up as well, from under the ground: 0x7fffffff samples, and the
        # first one ends it. A plain cast gives 0x80000000 and none.
        ((12.0, 20.0, -4.0), (5.0, 1.0, 0.0), 1e10, 1.0),
        ((28.0, 28.0, -1.0), (2.0, 2.0, 12.0), None, 2.5),      # off the edge
    ]
    for k, (pos, vel, speed, time) in enumerate(cases):
        air_car(sc, (pos[0], pos[1], flat_z(pos[0], pos[1]) + pos[2]), vel,
                speed, yaw=0.3 * k, pitch=0.05 * (k % 3 - 1))
        begin(sc, 1 / 30.0)
        air(sc, time, (77.0, -5.0, 0.0)[k % 3])
    # Time and height the one float: it is zeroed before time is read.
    air_car(sc, (16.0, 16.0, flat_z(16.0, 16.0) + 2.5), (10.0, 5.0, 4.0))
    begin(sc, 1 / 30.0)
    air(sc, 2.0, 0.0, 1)
    for _ in range(40):
        x, y = rnd.uniform(3.0, 29.0), rnd.uniform(3.0, 29.0)
        vel = (rnd.uniform(-15.0, 15.0), rnd.uniform(-15.0, 15.0),
               rnd.uniform(-6.0, 14.0))
        air_car(sc, (x, y, flat_z(x, y) + rnd.uniform(-1.0, 6.0)), vel,
                None if rnd.random() < 0.7 else rnd.uniform(0.0, 40.0),
                yaw=rnd.uniform(-3.0, 3.0), pitch=rnd.uniform(-0.3, 0.3))
        begin(sc, 1 / 30.0)
        air(sc, rnd.uniform(0.2, 3.0), rnd.choice((77.0, -5.0, 0.0)))

    sc.tag("air: gap, cliff and nothing")
    for pos, vel, time in (((36.0, 8.0, 3.5), (9.0, 0.0, 1.5), 1.5),
                           ((60.0, 8.0, 6.0), (20.0, 0.0, 3.0), 1.0),
                           ((78.0, 8.0, 301.0), (-15.0, 0.0, 2.0), 1.2),
                           ((104.0, 7.5, 30001.0), (0.0, 6.0, 1.0), 1.0),
                           ((500.0, 500.0, 5.0), (10.0, 0.0, 0.0), 1.0),
                           ((4.0, 46.0, 2.5), (0.0, 12.0, 0.5), 1.25)):
        air_car(sc, pos, vel)
        begin(sc, 1 / 30.0)
        air(sc, time)

    sc.tag("air: under the ground, and up the whole way")
    # A level car at yaw 0.5 starts from wheel 0's corner, 0.571 below its
    # position on average over the four radii. BeginMovement's box is three
    # dimensional, so a car further under the ground than the box is wide
    # finds nothing and gets its own z: these are under and inside it.
    rs = (0.3, 0.3125, 0.34375, 0.328125)
    drop = 0.25 + sum(rs) / 4
    cy, sy = math.cos(0.5), math.sin(0.5)
    for (x, y), under, vel, time in (
            ((16.0, 16.0), 0.5, (2.0, 1.0, 8.0), 1.5),     # below pt.z + 1
            ((20.0, 12.0), 0.5, (1.0, 0.5, 0.5), 0.5),     # and n == 0
            ((12.0, 20.0), 3.5, (60.0, 0.0, 0.0), 0.25)):  # the second pass
        ax, ay = x + 1.25 * cy - 0.75 * sy, y + 1.25 * sy + 0.75 * cy
        air_car(sc, (x, y, flat_z(ax, ay) - under + drop), vel)
        begin(sc, 1 / 30.0)
        air(sc, time)
    # Ten samples and none of them down: the last one is short of `time`.
    air_car(sc, (16.0, 16.0, flat_z(16.0, 16.0) + 20.0), (1.0, 1.0, 2.0),
            30.0)
    begin(sc, 1 / 30.0)
    air(sc, 1.0)
    # A car of 2^-13 kg, whose downforce is all of `down` but gravity's
    # 9.8: thrown up at `down` times the window, it comes back at the end
    # of it, and near there the fall and the throw cancel, so an ulp of
    # the downforce is ten ulps of the height. The throw comes after
    # BeginMovement: the box would be 15000 wide, and the tree gathers
    # only the squares under its four corners, none of them the slope's.
    sc.op(OP_CARF, CF_MASS, 2.0 ** -13)
    for speed, time in ((3.0, 10.0), (5.0, 6.0)):
        down = speed * ((1.75 + 2.25) * 0.3) * 2 ** 13 + 9.8
        air_car(sc, (16.0, 16.0, flat_z(16.0, 16.0) + 2.0), (0.0, 0.0, 1.0),
                speed)
        begin(sc, 1 / 30.0)
        sc.op(OP_CARVEC, CV_VEL, 0.0, 0.0, f32(down * time), -0.375)
        air(sc, time)
    sc.op(OP_CARF, CF_MASS, 1450.0)
    sc.op(OP_TCDUMP, 2)


# ---- TRACKB12 ------------------------------------------------------------------

B12_CHUNKS = [(0x7f93f4, 0x34130), (0x7fa010, 0x34131), (0x7fbe68, 0x34132),
              (0x8769f0, 0x34133), (0x7a7e80, 0x34146), (0x884580, 0x34200)]
G_INFO = (0x0a2680, 0x34201)


def b12_polygons():
    d = TRACKB12.read_bytes()
    t, s = struct.unpack_from("<II", d, 0x7fbe68)
    assert t == 0x34132
    return d, 0x7fbe68 + 8, s // 32


def b12_floor_points(rnd, n):
    """`n` points of TRACKB12's floors, (x, y, z) at a polygon's centroid."""
    d, body, count = b12_polygons()
    out = []
    while len(out) < n:
        o = body + 32 * rnd.randrange(count)
        vals = struct.unpack_from("<bBBBhh4h4h4h", d, o)
        flags, zbase = vals[3], vals[4]
        X, Y, Z = vals[6:10], vals[10:14], vals[14:18]
        if flags & 0x0a:            # vertical or upside down
            continue
        zs = [(z / 256.0 + zbase) * (4.0 if flags & 0x04 else 1.0)
              for z in Z[:3]]
        out.append((sum(X[:3]) / 24.0, sum(Y[:3]) / 24.0, sum(zs) / 3.0))
    return out


def degenerate_count():
    """(polygons, zero normals, floors or ceilings with a zero normal z),
    the vertices unpacked and crossed as the constructor does, in float."""
    d, body, n = b12_polygons()
    zero = flat = 0
    for i in range(n):
        o = body + 32 * i
        fl = d[o + 3]
        zb = struct.unpack_from("<h", d, o + 4)[0]
        X = struct.unpack_from("<4h", d, o + 8)
        Y = struct.unpack_from("<4h", d, o + 16)
        Z = struct.unpack_from("<4h", d, o + 24)
        v = []
        for k in range(3):
            x = f32(float(s32((X[k] << 13) & M32)) / 65536.0)
            y = f32(float(s32((Y[k] << 13) & M32)) / 65536.0)
            z = f32(float(s32(((Z[k] << 8) + (zb << 16)) & M32)) / 65536.0)
            if fl & 4:
                z = f32(z * 4.0)
            v.append((x, y, z))
        a = [f32(v[1][k] - v[0][k]) for k in range(3)]
        b = [f32(v[2][k] - v[0][k]) for k in range(3)]
        cx = f32(f32(a[1] * b[2]) - f32(b[1] * a[2]))
        cy = f32(f32(a[2] * b[0]) - f32(b[2] * a[0]))
        cz = f32(f32(a[0] * b[1]) - f32(b[0] * a[1]))
        if f32(f32(f32(cx * cx) + f32(cy * cy)) + f32(cz * cz)) == 0.0:
            zero += 1
        elif not fl & 2 and fb(cz) & 0x7f800000 == 0:
            flat += 1
    return n, zero, flat


def b12_route(n):
    """`n` square centres of TRACKB12 in a nearest-neighbour chain from the
    start grid."""
    d = TRACKB12.read_bytes()
    t, s = struct.unpack_from("<II", d, 0x7fa010)
    al = (0x7fa010 + 23) & ~15
    cnt = (s - (al - 0x7fa018)) // 12
    cs = [struct.unpack_from("<ff", d, al + 12 * i) for i in range(1, cnt)]
    route = []
    x, y = 45.5, 779.3
    left = list(cs)
    while left and len(route) < n:
        k = min(range(len(left)), key=lambda i: (left[i][0] - x) ** 2
                + (left[i][1] - y) ** 2)
        x, y = left.pop(k)
        route.append((x, y))
    return route


def scenario_trackb12(sc, rnd):
    if not TRACKB12.exists() or not GLOBALB.exists():
        return False
    tb, gb = sc.s(str(TRACKB12)), sc.s(str(GLOBALB))
    d = TRACKB12.read_bytes()
    g = GLOBALB.read_bytes()

    sc.tag("trackb12: load")
    for k, (off, t) in enumerate(B12_CHUNKS):
        assert struct.unpack_from("<I", d, off)[0] == t
        size = struct.unpack_from("<I", d, off + 4)[0]
        sc.op(OP_FILE, k, off % 16, tb, off, size + 8)
    off, t = G_INFO
    assert struct.unpack_from("<I", g, off)[0] == t
    size = struct.unpack_from("<I", g, off + 4)[0]
    sc.op(OP_FILE, 6, off % 16, gb, off, size + 8)
    for k in (6, 5, 4, 0, 1, 2, 3):
        sc.op(OP_LOADER, k)
    sc.op(OP_TREEDUMP, 0)
    sc.op(OP_GLOBALS)
    sc.op(OP_MARKDUMP)
    for i in range(0, 66):
        sc.op(OP_INFO, i)
    sc.op(OP_MEM, 6, 8 + 160 * 53, 40)
    for h in (0x8f90f7bf, 0x8e55c895, 0xe5fae1cf, 0xe5fae1d0, 0xeec70374,
              0x6a56b90a):
        sc.op(OP_NMARK, h)
        for i in (0, 1, 7, 8):
            sc.op(OP_GMARK, h, i)
    sc.op(OP_INITTREE)
    sc.op(OP_POOL)

    sc.tag("trackb12: squares")
    route = b12_route(260)
    for x, y in route[::9]:
        for dx, dy in ((0.0, 0.0), (15.9, 15.9), (-16.0, -16.0)):
            sc.op(OP_SQUARE, x + dx, y + dy, 0)
            sc.op(OP_SQUARE, x + dx + 40.0, y + dy - 70.0, 1)

    sc.tag("trackb12: drive")
    sc.op(OP_TICKSEED, 0x9e3779b9)
    sc.op(OP_TCINIT, 0)
    sc.op(OP_TCINIT, 1)
    for step, (x, y) in enumerate(route):
        jx, jy = rnd.uniform(-9.0, 9.0), rnd.uniform(-9.0, 9.0)
        sc.vec(0, x + jx, y + jy, 1000.0)
        sc.elev(0, 0)
        sc.vec(1, x + jx, y + jy, -1000.0)
        sc.elev(0, 1, 7 if step % 5 else 3)
        sc.vec(2, x + jx + 1.5, y + jy - 1.0, 1000.0)
        sc.elev(1, 2, 7)
        sc.op(OP_HASTOPO, 1, 2)
        if step % 4 == 0:
            sc.op(OP_TCDUMP, 0)
            sc.vec(3, x + jx, y + jy, 1000.0, 0.5)
            sc.vec(4, x + jx, y + jy, -1000.0, -0.5)
            sc.op(OP_TCSEG, 0, 3, 4, 0.5)
            sc.op(OP_TCSEG, 0, 4, 3, 0.5)
            a = rnd.uniform(0.0, 2 * math.pi)
            for typ in (0, 1):
                sc.vec(5, x + jx, y + jy, 400.0, 1.0)
                sc.vec(6, x + jx + 3 * math.cos(a), y + jy + 3 * math.sin(a),
                       -400.0, 2.0)
                sc.op(OP_CONSTRAIN, 0, typ, step & 1, 5, 6, 0.4, 1.5)
            for typ in (0, 1):
                sc.vec(5, x + jx, y + jy, 0.0)
                sc.vec(6, x + jx + 14 * math.cos(a), y + jy + 14 * math.sin(a),
                       0.0)
                sc.op(OP_CONSTRAIN, 0, typ, 1, 5, 6, 0.4, 1.5)
        if step % 40 == 39:
            sc.op(OP_POOL)
            sc.op(OP_TREEDUMP, 1)
            sc.op(OP_GLOBALS)
    sc.op(OP_TCDUMP, 0)
    sc.op(OP_TCDUMP, 1)
    sc.op(OP_POOL)

    sc.tag("trackb12: flat on the road")
    # Car::FindFlatOnTrackPosition and PutFlatOnTrack on the shipped road:
    # each probe starts 1.5 over a floor polygon's first-three-vertex
    # centroid, so it stands on that polygon even under a bridge.
    for n, (x, y, z) in enumerate(b12_floor_points(rnd, 90)):
        ang = rnd.randrange(0x10000)
        if n % 3:
            flat_probe(sc, 1, 8, x, y, z + 1.5, ang,
                       9 if n % 5 == 0 else -1, 2.5)
        else:
            sc.vec(8, x, y, z + 1.5)
            sc.op(OP_SIB3, 1, 8, 2.5, -1)
            sc.op(OP_CARPOS, x, y, z + 1.5, 0.5, ang)
            sc.op(OP_PUTFLAT, 1)
    sc.op(OP_TCDUMP, 1)

    sc.tag("trackb12: road noise under the route")
    for x, y in route[:40]:
        sc.vec(7, x + 0.37, y - 0.61)
        for t in (1, 2, 6, 9):
            sc.op(OP_NOISE, 7, t)

    sc.tag("trackb12: fill the pool")
    sc.op(OP_TCDESTROY, 0)
    sc.op(OP_TCDESTROY, 1)
    sc.op(OP_CLOSETREE)
    sc.op(OP_POOL)
    sc.op(OP_INITTREE)
    body = 8
    # 1024 distinct polygons held, eight handles of 128.
    for i in range(NSLOTS):
        sc.op(OP_ASSIGN, i // 128, i % 128, 2, body + 32 * (3 * i))
    sc.op(OP_POOL)
    # Let go of 60 of the oldest and 200 of the newest: a flush frees 101,
    # the oldest first, and stops.
    sc.op(OP_REMOVE, 0, 60)
    for h in (6, 7):
        sc.op(OP_REMOVE, h, 100)
    sc.op(OP_ASSIGN, 8, 0, 2, body + 32 * 5000)
    sc.op(OP_POOL)
    sc.op(OP_TREEDUMP, 1)
    for i in range(1, 102):
        sc.op(OP_ASSIGN, 8, i, 2, body + 32 * (5000 + 7 * i))
    sc.op(OP_POOL)
    sc.op(OP_TREEDUMP, 1)
    # Re-assign some whose slots were flushed: they are built again.
    for i in range(10):
        sc.op(OP_ASSIGN, 9, i, 2, body + 32 * (3 * i))
    sc.op(OP_POOL)
    sc.op(OP_TREEDUMP, 1)
    sc.op(OP_FLUSH)
    sc.op(OP_POOL)
    sc.op(OP_TREEDUMP, 1)
    sc.op(OP_CLOSETREE)
    sc.op(OP_POOL)
    sc.op(OP_GLOBALS)

    sc.tag("trackb12: unload")
    for k in (0, 1, 2, 3, 4, 5, 6):
        sc.op(OP_UNLOADER, k)
    sc.op(OP_TREEDUMP, 1)
    sc.op(OP_MARKDUMP)
    sc.op(OP_GLOBALS)
    return True


def script():
    rnd = random.Random(0x7ac12)
    sc = Script()
    scenario_pure(sc, rnd)
    scenario_info(sc)
    scenario_markers(sc)
    scenario_world(sc, rnd)
    scenario_bad_tree(sc, rnd)
    scenario_flat(sc, rnd)
    sc.b12 = scenario_trackb12(sc, rnd)
    return sc


# ================================================================ the model


class Model(object):
    def __init__(self, sc):
        self.sc = sc
        self.out = []
        e = self.e = Emu(ieee=True, eediv=True)
        e.stub_bware()
        self.fn = {k: e.addr_of(v) for k, v in SYM.items()}
        self.mis = [0] * NCHUNK
        self.held = [0] * NH        # how many of each handle's table are set
        self.tick = 0
        self.files = {}
        self.stubs()
        for pat in (r"bNewSlotPool__FiiPCci$", r"TrackPositionMarkerList$",
                    r"TerrainTypeInfoTable$"):
            done = e.run_ctors(pat)
            assert len(done) == 1, (pat, done)
        e.put32(CAR + 12, CTI)

    def emit(self, s):
        self.out.append(s)

    def stubs(self):
        e = self.e

        def arg(i):
            return e.reg[4 + i] & M32

        def cstr(p):
            end = e.mem.index(b"\0", p)
            return e.mem[p:end].decode("latin-1")

        def malloc(em):
            size = s32(arg(0))
            assert 0 < size <= POOLSPAN, size
            self.emit("  pool alloc %s mp %d" % (cstr(arg(1)), s32(arg(3))))
            e.mem[POOLMEM:POOLMEM + POOLSPAN] = bytes(POOLSPAN)
            return POOLMEM

        def free(em):
            self.emit("  pool free")

        def printf(em):
            self.emit("  printf")

        def brk(em):
            raise AssertionError("scenario reaches bBreak: a flush with "
                                 "every slot held")

        def ticker(em):
            self.tick = (self.tick * 1664525 + 1013904223) & M32
            return s32(self.tick)

        e.stub("bMalloc__FiPCcii", malloc)
        e.stub("bFree__FPv", free)
        e.stub("bPrintf__FPCce", printf)
        e.stub("bBreak__Fv", brk)
        e.stub("bGetTicker__Fv", ticker)
        del e.stubs[e.addr_of("bGetTickerDifference__FUiUi")]

    # ---- addresses and labels -------------------------------------------

    def chunk(self, k):
        return CH_BASE + CH_SPAN * k + self.mis[k]

    def vec(self, i):
        return VEC_BASE + 16 * i

    def tc(self, i):
        return TC_BASE + TC_STRIDE * i

    def pool(self):
        return self.e.u32(POOLVAR)

    def slot(self, s):
        p = self.pool()
        if s32(s) < 0 or p == 0:
            return 0
        return p + 48 + SLOT * s

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        if a == MARKERS:
            return "markers"
        if a == TREE:
            return "tree"
        if a == TREE + 32:
            return "tplist"
        p = self.pool()
        if p and p + 48 <= a < p + 48 + NSLOTS * SLOT:
            off = a - p - 48
            return ("tp%d" % (off // SLOT) if off % SLOT == 0
                    else "tp%d+?" % (off // SLOT))
        for k in range(NCHUNK):
            base = CH_BASE + CH_SPAN * k
            if base <= a < base + CH_SPAN:
                return "c%d%+d" % (k, a - self.chunk(k))
        for k in range(NTC):
            if self.tc(k) <= a < self.tc(k) + 560:
                return "tc%d" % k if a == self.tc(k) else "tc%d+?" % k
        for k in range(NVEC):
            if a == self.vec(k):
                return "v%d" % k
        return "?"

    # ---- the prints ------------------------------------------------------

    def sb(self, a):
        return (self.e.u8(a) ^ 0x80) - 0x80

    def i32(self, a):
        return s32(self.e.u32(a))

    def labels(self, pre, addrs):
        for i in range(0, len(addrs), 16):
            self.emit(pre + "".join(" " + self.label(x)
                                    for x in addrs[i:i + 16]))

    def tree_dump(self, lst):
        e, L = self.e, self.label
        t = TREE
        self.emit("tree nodes %s %d squares %s %d polys %s %d idx %s %d "
                  "list %s %s"
                  % (L(e.u32(t)), self.i32(t + 4), L(e.u32(t + 8)),
                     self.i32(t + 12), L(e.u32(t + 16)), self.i32(t + 20),
                     L(e.u32(t + 24)), self.i32(t + 28), L(e.u32(t + 32)),
                     L(e.u32(t + 36))))
        if not lst:
            return
        head = t + 32
        fwd = []
        n = e.u32(head)
        while n != head and len(fwd) < MAX_WALK:
            fwd.append("%s:%d" % (L(n), e.u8(n + 8)))
            n = e.u32(n)
        for i in range(0, len(fwd), 16):
            self.emit("  fwd " + " ".join(fwd[i:i + 16]))
        back = []
        n = e.u32(head + 4)
        while n != head and len(back) < MAX_WALK:
            back.append(n)
            n = e.u32(n + 4)
        self.labels("  back", back)

    def pool_dump(self):
        e, p = self.e, self.pool()
        if p == 0:
            self.emit("pool null")
            return
        self.emit("pool flags %d alloc %d most %d slots %d total %d free %s"
                  % (e.u32(p + 20), self.i32(p + 24), self.i32(p + 28),
                     self.i32(p + 36), self.i32(p + 44),
                     self.label(e.u32(p + 16))))

    def tp_dump(self, s):
        e, L = self.e, self.label
        tp = self.slot(s)
        if tp == 0:
            self.emit("tp%d none" % s)
            return
        v = " ".join("%08x %08x %08x" % (e.u32(tp + 48 + 16 * i),
                                         e.u32(tp + 52 + 16 * i),
                                         e.u32(tp + 56 + 16 * i))
                     for i in range(4))
        self.emit("tp%d ref %d nv %d fl %d ty %d poly %s cb %s bb %08x %08x "
                  "%08x %08x v %s n %08x %08x %08x pd %08x"
                  % (s, e.u8(tp + 8), e.u8(tp + 9), e.u8(tp + 10),
                     e.u8(tp + 11), L(e.u32(tp + 12)), L(e.u32(tp + 16)),
                     e.u32(tp + 20), e.u32(tp + 24), e.u32(tp + 28),
                     e.u32(tp + 32), v, e.u32(tp + 112), e.u32(tp + 116),
                     e.u32(tp + 120), e.u32(tp + 124)))

    def tc_dump(self, i):
        e, c = self.e, self.tc(i)
        n = self.i32(c + 544)
        self.emit("tc%d ib %08x %08x %08x %08x cb %08x %08x %08x %08x "
                  "total %d num %d vert %d ud %d"
                  % ((i,) + tuple(e.u32(c + 4 * k) for k in range(8))
                     + (n, self.i32(c + 548), self.i32(c + 552),
                        self.i32(c + 556))))
        n = max(0, min(n, 128))
        self.labels("  t", [e.u32(c + 32 + 4 * k) for k in range(n)])

    def mark_dump(self):
        e, L = self.e, self.label
        self.emit("markers next %s prev %s" % (L(e.u32(MARKERS)),
                                               L(e.u32(MARKERS + 4))))
        n = e.u32(MARKERS)
        k = 0
        while n != MARKERS and k < MAX_WALK:
            self.emit("  mk %s hash %08x param %d pos %08x %08x"
                      % (L(n), e.u32(n + 8), self.i32(n + 12),
                         e.u32(n + 16), e.u32(n + 20)))
            n = e.u32(n)
            k += 1
        back = []
        n = e.u32(MARKERS + 4)
        while n != MARKERS and len(back) < MAX_WALK:
            back.append(n)
            n = e.u32(n + 4)
        self.labels("  back", back)

    def globals_dump(self):
        e, L = self.e, self.label
        self.emit("globals cur %s table %s highest %d loaded %d pool %s "
                  "tidx %d"
                  % (L(e.u32(CUR)), L(e.u32(TABLE)), self.i32(HIGHEST),
                     self.i32(LOADED), "pool" if self.pool() else "null",
                     e.u32(TIDX)))
        self.emit("  timing" + "".join(" %08x" % e.u32(TIMING + 4 * k)
                                       for k in range(10)))

    def pv(self, a):
        e = self.e
        return "%08x %08x %08x %08x" % (e.u32(a), e.u32(a + 4), e.u32(a + 8),
                                        e.u32(a + 12))

    def mat_dump(self, a):
        self.emit("  m" + "".join(" %08x" % self.e.u32(a + 4 * k)
                                  for k in range(16)))

    def timing_line(self):
        idx = self.e.u32(TIDX)
        self.emit("  timing %d %08x" % (idx, self.e.u32(TIMING + 4 * ((idx + 9)
                                                                    % 10))))

    def fill(self, a, n):
        for k in range(0, n, 4):
            self.e.put32(a + k, SENTINEL)

    # ---- the run ---------------------------------------------------------

    def run(self):
        tag = "?"
        for i, o in enumerate(self.sc.ops):
            if o[0] == OP_TAG:
                tag = self.sc.strs[o[1]]
            try:
                self.step(o)
            except AssertionError as x:
                raise AssertionError("op %d %r in [%s]: %s" % (i, o, tag, x))
        return self.out

    def cstring(self, i):
        """String i of the table, NUL-terminated, at a scratch address."""
        b = self.sc.strs[i].encode("latin-1") + b"\0"
        a = SCR + 0x400
        self.e.mem[a:a + len(b)] = b
        return a

    def step(self, o):
        sc, e, emit, fn, L = self.sc, self.e, self.emit, self.fn, self.label
        code, a = o[0], [s32(v) for v in o[1:]]
        u = [v & M32 for v in o[1:]]
        # The EE's registers are 64 bits and every lw sign-extends: a
        # 32-bit argument goes in as its sign extension, or a hash with
        # its top bit set never compares equal.
        def call(f, *xs):
            return e.call(f, *[s32(x & M32) for x in xs])
        if code == OP_TAG:
            emit("[%s]" % sc.strs[a[0]])
        elif code == OP_CLEAR:
            base = CH_BASE + CH_SPAN * a[0]
            e.mem[base:base + CH_SPAN] = bytes(CH_SPAN)
            self.mis[a[0]] = a[1]
        elif code == OP_CHUNKW:
            e.put32(self.chunk(a[0]) + a[1], u[2])
        elif code == OP_FILE:
            k, m, si, off, n = a
            base = CH_BASE + CH_SPAN * k
            e.mem[base:base + CH_SPAN] = bytes(CH_SPAN)
            self.mis[k] = m
            path = sc.strs[si]
            if path not in self.files:
                self.files[path] = Path(path).read_bytes()
            data = self.files[path][off:off + n]
            assert len(data) == n
            e.mem[base + m:base + m + n] = data
        elif code == OP_LOADER:
            emit("loader c%d -> %d" % (a[0], call(fn["loader"],
                                                  self.chunk(a[0]))))
        elif code == OP_UNLOADER:
            emit("unloader c%d -> %d" % (a[0], call(fn["unloader"],
                                                    self.chunk(a[0]))))
        elif code == OP_TTLOADER:
            emit("ttloader c%d -> %d" % (a[0], call(fn["ttloader"], TREE,
                                                    self.chunk(a[0]))))
        elif code == OP_TTUNLOADER:
            emit("ttunloader c%d -> %d" % (a[0], call(fn["ttunloader"], TREE,
                                                      self.chunk(a[0]))))
        elif code == OP_MEM:
            p = self.chunk(a[0]) + a[1]
            emit("mem c%d%+d" % (a[0], a[1])
                 + "".join(" %08x" % e.u32(p + 4 * i) for i in range(a[2])))
        elif code == OP_TREEINIT:
            emit("treeinit")
            call(fn["treeinit"], TREE)
        elif code == OP_INITTREE:
            emit("inittree")
            call(fn["inittree"], TREE)
        elif code == OP_CLOSETREE:
            emit("closetree")
            call(fn["closetree"], TREE)
        elif code == OP_TREEDUMP:
            self.tree_dump(a[0])
        elif code == OP_POOL:
            self.pool_dump()
        elif code == OP_TPINIT:
            p = self.chunk(a[1]) + a[2]
            r = call(fn["tpinit"], self.slot(a[0]), p)
            emit("tpinit tp%d %s -> %s" % (a[0], L(p), L(r)))
        elif code == OP_TPDESTROY:
            emit("tpdestroy tp%d %d" % (a[0], a[1]))
            call(fn["tpdestroy"], self.slot(a[0]), a[1])
        elif code == OP_TPDUMP:
            self.tp_dump(a[0])
        elif code == OP_VEC:
            for k in range(4):
                e.put32(self.vec(a[0]) + 4 * k, u[1 + k])
        elif code == OP_SHAFT:
            self.fill(DIST, 4)
            r = call(fn["shaft"], self.slot(a[0]), self.vec(a[1]),
                     DIST if a[2] else 0)
            emit("shaft tp%d v%d -> %d dist %08x" % (a[0], a[1], r,
                                                     e.u32(DIST)))
        elif code == OP_TPSEG:
            self.fill(OUTV, 16)
            r = call(fn["tpseg"], self.slot(a[0]), self.vec(a[1]),
                     self.vec(a[2]), OUTV if a[3] else 0)
            emit("tpseg tp%d v%d v%d -> %d out %s" % (a[0], a[1], a[2], r,
                                                     self.pv(OUTV)))
        elif code == OP_TPTEST:
            e.put32(BEST, u[1])
            r = call(fn["tptest"], self.slot(a[0]), BEST, self.vec(a[2]),
                     self.vec(a[3]), self.vec(a[4]), self.vec(a[5]), a[6])
            emit("tptest tp%d v%d v%d box v%d v%d two %d -> %d best %08x"
                 % (a[0], a[2], a[3], a[4], a[5], a[6], r, e.u32(BEST)))
        elif code == OP_TCINIT:
            emit("tcinit tc%d" % a[0])
            call(fn["tcinit"], self.tc(a[0]))
        elif code == OP_TCDESTROY:
            emit("tcdestroy tc%d" % a[0])
            call(fn["tcdestroy"], self.tc(a[0]), 2)
        elif code == OP_TCCLEAR:
            emit("tcclear tc%d" % a[0])
            call(fn["tcclear"], self.tc(a[0]))
        elif code == OP_TCDUMP:
            self.tc_dump(a[0])
        elif code == OP_TCPOKE:
            assert 0 <= a[1] < 12
            off = 4 * a[1] if a[1] < 8 else 544 + 4 * (a[1] - 8)
            e.put32(self.tc(a[0]) + off, u[2])
        elif code == OP_TCSET:
            e.put32(self.tc(a[0]) + 32 + 4 * a[1], self.slot(a[2]))
        elif code == OP_SIB:
            emit("sib tc%d v%d r %08x vel %s"
                 % (a[0], a[1], u[2], "null" if a[3] < 0
                    else L(self.vec(a[3]))))
            e.fpr[12] = u[2]
            call(fn["sib"], self.tc(a[0]), self.vec(a[1]),
                 0 if a[3] < 0 else self.vec(a[3]))
        elif code == OP_ELEV:
            self.fill(TERR, 4)
            self.fill(FOUND, 4)
            self.fill(NORM, 16)
            m = a[2]
            call(fn["elev"], self.tc(a[0]), self.vec(a[1]),
                 TERR if m & E_TERR else 0, NORM if m & E_NORM else 0,
                 FOUND if m & E_FOUND else 0)
            emit("elev tc%d v%d -> %08x terr %08x norm %s found %08x"
                 % (a[0], a[1], e.fpr[0], e.u32(TERR), self.pv(NORM),
                    e.u32(FOUND)))
            idx = e.u32(TIDX)
            emit("  timing %d %08x" % (idx, e.u32(TIMING + 4 * ((idx + 9)
                                                                % 10))))
        elif code == OP_HASTOPO:
            emit("hastopo tc%d v%d -> %d"
                 % (a[0], a[1], call(fn["hastopo"], self.tc(a[0]),
                                     self.vec(a[1]))))
        elif code == OP_TCSEG:
            e.fpr[12] = u[3]
            r = call(fn["tcseg"], self.tc(a[0]), self.vec(a[1]),
                     self.vec(a[2]))
            emit("tcseg tc%d v%d v%d r %08x -> %d" % (a[0], a[1], a[2], u[3],
                                                     r))
        elif code == OP_CONSTRAIN:
            e.fpr[12] = u[5]
            e.fpr[13] = u[6]
            r = call(fn["constrain"], self.tc(a[0]), a[1], a[2],
                     self.vec(a[3]), self.vec(a[4]))
            emit("constrain tc%d type %d two %d v%d v%d dist %08x lift %08x "
                 "-> %d to %s" % (a[0], a[1], a[2], a[3], a[4], u[5], u[6], r,
                                  self.pv(self.vec(a[4]))))
        elif code == OP_CORNER:
            e.fpr[12] = u[0]
            call(fn["corner"], TREE)
            emit("corner %08x -> %08x" % (u[0], e.fpr[0]))
        elif code == OP_SQUARE:
            e.fpr[12] = u[0]
            e.fpr[13] = u[1]
            r = call(fn["square"], TREE, a[2])
            emit("square %08x %08x near %d -> %s" % (u[0], u[1], a[2], L(r)))
        elif code == OP_GIP:
            sq = 0 if a[0] < 0 else self.chunk(a[0]) + a[1]
            n = call(fn["gip"], TREE, GIPOUT, a[4], sq, self.vec(a[2]),
                     self.vec(a[3]))
            emit("gip %s v%d v%d max %d -> %d" % (L(sq), a[2], a[3], a[4], n))
            outs = [e.u32(GIPOUT + 4 * i) for i in range(n)]
            self.labels("  g", outs)
            if not a[5]:
                for p in outs:
                    e.mem[p] = 0
        elif code == OP_BUILD:
            out = OUTS + 0x200 * a[0]
            n = call(fn["build"], TREE, out, a[3], self.vec(a[1]),
                     self.vec(a[2]))
            self.held[a[0]] = n
            emit("build h%d v%d v%d max %d -> %d" % (a[0], a[1], a[2], a[3],
                                                     n))
            self.labels("  b", [e.u32(out + 4 * i) for i in range(n)])
        elif code == OP_REMOVE:
            n = self.held[a[0]]
            n = n if a[1] < 0 or a[1] > n else a[1]
            emit("remove h%d %d" % (a[0], n))
            call(fn["remove"], TREE, OUTS + 0x200 * a[0], n)
        elif code == OP_ASSIGN:
            p = self.chunk(a[2]) + a[3]
            r = call(fn["assign"], TREE, p)
            e.put32(OUTS + 0x200 * a[0] + 4 * a[1], r)
            self.held[a[0]] = max(self.held[a[0]], a[1] + 1)
            emit("assign h%d[%d] %s -> %s" % (a[0], a[1], L(p), L(r)))
        elif code == OP_UNASSIGN:
            tp = e.u32(OUTS + 0x200 * a[0] + 4 * a[1])
            emit("unassign h%d[%d] %s" % (a[0], a[1], L(tp)))
            call(fn["unassign"], TREE, tp)
        elif code == OP_FLUSH:
            emit("flush")
            call(fn["flush"], TREE)
        elif code == OP_NMARK:
            emit("nmark %08x -> %d" % (u[0], call(fn["nmark"], u[0])))
        elif code == OP_GMARK:
            emit("gmark %08x %d -> %s" % (u[0], a[1],
                                          L(call(fn["gmark"], u[0], a[1]))))
        elif code == OP_NMARKN:
            emit("nmarkn s%d -> %d" % (a[0], call(fn["nmarkn"],
                                                  self.cstring(a[0]))))
        elif code == OP_GMARKN:
            r = call(fn["gmarkn"], self.cstring(a[0]), a[1])
            emit("gmarkn s%d %d -> %s" % (a[0], a[1], L(r)))
        elif code == OP_MARKDUMP:
            self.mark_dump()
        elif code == OP_INFO:
            emit("info %d -> %s" % (a[0], L(call(fn["info"], a[0]))))
        elif code == OP_GLOBALS:
            self.globals_dump()
        elif code == OP_GRID:
            call(fn["grid"], a[0], a[1])
            emit("grid %d %d -> %08x" % (a[0], a[1], e.fpr[0]))
        elif code == OP_NOISE:
            call(fn["noise"], self.vec(a[0]), a[1])
            emit("noise v%d %d -> %08x" % (a[0], a[1], e.fpr[0]))
        elif code == OP_MATCHNAME:
            p = 0 if a[0] < 0 else self.cstring(a[0])
            emit("matchname s%d -> %d" % (a[0], call(fn["matchname"], p)))
        elif code == OP_MATCHHASH:
            emit("matchhash %08x -> %d" % (u[0], call(fn["matchhash"], u[0])))
        elif code == OP_TICKSEED:
            self.tick = u[0]
        elif code == OP_HSET:
            e.put32(OUTS + 0x200 * a[0] + 4 * a[1], self.slot(a[2]))
            self.held[a[0]] = max(self.held[a[0]], a[1] + 1)
        elif code == OP_TPCB:
            e.put32(self.slot(a[0]) + 16, TREE)
        elif code == OP_COG:
            for k in range(4):
                e.put32(CTI + 272 + 4 * k, u[k])
        elif code == OP_WHEEL:
            e.put32(CTI + 288 + 32 * a[0] + 8, u[1])
            e.put32(CTI + 288 + 32 * a[0] + 12, u[2])
        elif code == OP_CARPOS:
            for k in range(4):
                e.put32(CAR + 96 + 4 * k, u[k])
            struct.pack_into("<H", e.mem, CAR + 932, u[4] & 0xffff)
        elif code == OP_FLAT:
            emit("flat tc%d v%d angle %d" % (a[0], a[1], u[2] & 0xffff))
            self.fill(FLATM, 64)
            # The whole word goes in: the image's own `andi a3,a3,0xffff`
            # is what masks it, as the port's uint16_t parameter does.
            call(fn["flat"], CAR, FLATM, self.vec(a[1]), u[2], self.tc(a[0]))
            emit("  pos " + self.pv(self.vec(a[1])))
            self.mat_dump(FLATM)
            self.timing_line()
        elif code == OP_PUTFLAT:
            emit("putflat tc%d" % a[0])
            self.fill(CAR + 144, 64)
            self.fill(CAR + 80, 16)
            tc = self.tc(a[0])
            e.mem[CAR + 1280:CAR + 1840] = e.mem[tc:tc + 560]
            call(fn["putflat"], CAR)
            e.mem[tc:tc + 560] = e.mem[CAR + 1280:CAR + 1840]
            emit("  pos %s geom %s angle %d"
                 % (self.pv(CAR + 96), self.pv(CAR + 80), e.u16(CAR + 932)))
            self.mat_dump(CAR + 144)
            self.timing_line()
        elif code == OP_CARVEC:
            for k in range(4):
                e.put32(car_vec(a[0]) + 4 * k, u[1 + k])
        elif code == OP_CARF:
            e.put32(car_word(a[0]), u[1])
        elif code == OP_AIR:
            emit("air tc%d time %08x height %08x%s"
                 % (a[0], u[1], u[2], " alias" if a[3] else ""))
            h = AIRT if a[3] else AIRT + 4
            e.put32(AIRT + 4, u[2])
            e.put32(AIRT, u[1])
            tc = self.tc(a[0])
            e.mem[CAR + 1280:CAR + 1840] = e.mem[tc:tc + 560]
            call(fn["air"], CAR, AIRT, h)
            r = e.fpr[0] & M32
            e.mem[tc:tc + 560] = e.mem[CAR + 1280:CAR + 1840]
            emit("  -> %08x time %08x height %08x"
                 % (r, e.u32(AIRT), e.u32(h)))
            self.timing_line()
        elif code == OP_BEGIN:
            emit("begin tc%d dt %08x" % (a[0], u[1]))
            tc = self.tc(a[0])
            e.mem[CAR + 1280:CAR + 1840] = e.mem[tc:tc + 560]
            e.fpr[12] = u[1]
            call(fn["begin"], CAR)
            e.mem[tc:tc + 560] = e.mem[CAR + 1280:CAR + 1840]
            emit("  old %s ang %s" % (self.pv(CAR + 1120),
                                      self.pv(CAR + 1136)))
            emit("  trough %08x %08x crossed %s"
                 % (e.u32(CAR + 1968), e.u32(CAR + 1972),
                    " ".join("%d" % self.i32(CAR + 868 + 4 * k)
                             for k in range(4))))
            self.timing_line()
        elif code == OP_SIB3:
            emit("sib3 tc%d v%d r %08x vel %s"
                 % (a[0], a[1], u[2], "null" if a[3] < 0
                    else L(self.vec(a[3]))))
            e.fpr[12] = u[2]
            call(fn["sib3"], self.tc(a[0]), self.vec(a[1]),
                 0 if a[3] < 0 else self.vec(a[3]))
        else:
            raise ValueError("op %d" % code)


def model(sc):
    m = Model(sc)
    out = m.run()
    divs = sorted(pc for pc in m.e.eediv_pcs
                  if TRACK_TEXT[0] <= pc < TRACK_TEXT[1]
                  or TERRAIN_TEXT[0] <= pc < TERRAIN_TEXT[1])
    return out, divs


# ================================================================ the build


def build_harness(tmp, name="track_test"):
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
    # ---- the helpers
    ("xy-shift", TRC,
     "(uint32_t)(int32_t)v << 13) * TRACK_Q16",
     "(uint32_t)(int32_t)v << 12) * TRACK_Q16"),
    ("z-shift", TRC,
     "uint32_t w = ((uint32_t)(int32_t)v << 8)",
     "uint32_t w = ((uint32_t)(int32_t)v << 9)"),
    ("zbase-shift", TRC,
     "+ ((uint32_t)(int32_t)zbase << 16);",
     "+ ((uint32_t)(int32_t)zbase << 15);"),
    ("dot-order", TRC,
     "return (a->x * nx + a->y * ny) + a->z * nz;",
     "return a->x * nx + (a->y * ny + a->z * nz);"),
    ("cross-z", TRC,
     "float z = a->x * b->y - b->x * a->y;",
     "float z = b->x * a->y - a->x * b->y;"),
    ("unlink-prev", TRC,
     "    prev->pNext = p32_of(next);",
     "    prev->pNext = p32_of(n);"),
    ("append-next", TRC,
     "    n->pNext    = p32_of(head);",
     "    n->pNext    = p32_of(tail);"),

    # ---- the markers
    ("nmark-eq", TRC,
     "->NameHash == hash)\n            count++;",
     "->NameHash != hash)\n            count++;"),
    ("gmark-index", TRC,
     "        if (seen == i)",
     "        if (seen == i + 1)"),
    ("gmark-seen", TRC,
     "        seen++;\n    }\n    return NULL;",
     "    }\n    return NULL;"),
    ("nmarkn-hash", TRC,
     "return track_get_num_position_markers(bchunk_hash(name));",
     "return track_get_num_position_markers(bchunk_hash(name) + 1);"),
    ("gmarkn-index", TRC,
     "return track_get_position_marker(bchunk_hash(name), i);",
     "return track_get_position_marker(bchunk_hash(name), i + 1);"),

    # ---- TrackPolygon
    ("tpinit-terrain", TRC,
     "tp->TheTerrainType = p->Type;",
     "tp->TheTerrainType = p->Type + 1;"),
    ("tpinit-refcount", TRC,
     "    tp->ReferenceCount = 0;\n    tp->Flags",
     "    tp->ReferenceCount = 1;\n    tp->Flags"),
    ("tpinit-flags", TRC,
     "tp->Flags = p->Flags;",
     "tp->Flags = p->Flags | 32;"),
    ("tpinit-cb", TRC,
     "    tp->pCollisionBody = NULL;\n",
     ""),
    ("tpinit-bbminx", TRC,
     "tp->BBoxMin.x = xy_of(p->VerticesX[m & 3]);",
     "tp->BBoxMin.x = xy_of(p->VerticesX[(m + 1) & 3]);"),
    ("tpinit-bbmaxy", TRC,
     "tp->BBoxMax.y = xy_of(p->VerticesY[m >> 6]);",
     "tp->BBoxMax.y = xy_of(p->VerticesY[(m >> 2) & 3]);"),
    ("tpinit-three-verts", TRC,
     "for (i = 0; i < 4; i++) {\n        tp->Vertices[i].x = xy_of",
     "for (i = 0; i < 3; i++) {\n        tp->Vertices[i].x = xy_of"),
    ("tpinit-numverts", TRC,
     "(tp->Flags & TRACKPOLY_QUAD) ? 4 : 3;",
     "(tp->Flags & TRACKPOLY_QUAD) ? 4 : 4;"),
    ("tpinit-x4", TRC,
     "tp->Vertices[i].z = tp->Vertices[i].z * 4.0f;",
     "tp->Vertices[i].z = tp->Vertices[i].z * 2.0f;"),
    ("tpinit-x4-flag", TRC,
     "if (tp->Flags & TRACKPOLY_Z_TIMES_FOUR) {",
     "if (tp->Flags & TRACKPOLY_INFINITELY_HIGH) {"),
    ("tpinit-edge-b", TRC,
     "b.x = tp->Vertices[2].x - tp->Vertices[0].x;",
     "b.x = tp->Vertices[3].x - tp->Vertices[0].x;"),
    ("tpinit-rsqrt-order", TRC,
     "q = 1.0f / sqrtf((c.x * c.x + c.y * c.y) + c.z * c.z);",
     "q = 1.0f / sqrtf(c.x * c.x + (c.y * c.y + c.z * c.z));"),
    ("tpinit-pd-vertex", TRC,
     "tp->PlaneDistance = dot3(&tp->Vertices[0],",
     "tp->PlaneDistance = dot3(&tp->Vertices[1],"),
    ("tpinit-slotnum", TRC,
     "(int16_t)bGetSlotNumber(TrackPolygonSlotPool, tp);",
     "(int16_t)(bGetSlotNumber(TrackPolygonSlotPool, tp) + 1);"),
    ("tpinit-ppolygon", TRC,
     "    tp->pPolygon = p;\n    return tp;",
     "    return tp;"),
    ("tpdestroy-number", TRC,
     "tp->pPolygon->TrackPolygonNumber = -1;",
     "tp->pPolygon->TrackPolygonNumber = 0;"),
    ("tpdestroy-flag", TRC,
     "    if (flags & 1)\n        bSlotFree",
     "    if (flags & 2)\n        bSlotFree"),

    ("shaft-edge", TRC,
     "tp->Normal.z) < 0.0f)\n            return 0;\n    }\n    if (dist",
     "tp->Normal.z) <= 0.0f)\n            return 0;\n    }\n    if (dist"),
    ("shaft-tri-close", TRC,
     "        cross3(&c[2], &d[2], &d[0]);",
     "        cross3(&c[2], &d[2], &d[3]);"),
    ("shaft-quad-test", TRC,
     "    if (n == 4) {\n        cross3(&c[2], &d[2], &d[3]);",
     "    if (n == 5) {\n        cross3(&c[2], &d[2], &d[3]);"),
    ("shaft-dist-sign", TRC,
     "*dist = -dot3(&d[0],",
     "*dist = dot3(&d[0],"),
    ("seg-strict", TRC,
     "if (!(sa * sb < 0.0f))",
     "if (!(sa * sb <= 0.0f))"),
    ("seg-t", TRC,
     "t = fabsf(sa) / (fabsf(sa) + fabsf(sb));",
     "t = fabsf(sb) / (fabsf(sa) + fabsf(sb));"),
    ("seg-pad", TRC,
     "hit.pad = (b->pad - a->pad) * t + a->pad;",
     "hit.pad = a->pad;"),
    ("seg-no-shaft", TRC,
     "    if (!trackpolygon_point_in_shaft(tp, &hit, NULL))\n        return 0;\n",
     ""),
    ("test-bbox-three", TRC,
     "for (i = 1; i < (int8_t)tp->NumVertices; i++)",
     "for (i = 1; i < 3; i++)"),
    ("test-no-overlap", TRC,
     "    if (!bBoundingBoxOverlapping3(&mn, &mx, bmin, bmax))\n        return 0;\n",
     ""),
    ("test-twosided", TRC,
     "    if (!twoSided) {",
     "    if (twoSided) {"),
    ("test-facing", TRC,
     "if (!(dot3(&d, tp->Normal.x, tp->Normal.y, tp->Normal.z) < 0.0f))",
     "if (!(dot3(&d, tp->Normal.x, tp->Normal.y, tp->Normal.z) > 0.0f))"),
    ("test-best-le", TRC,
     "if (!(len < *best))",
     "if (!(len <= *best))"),
    ("test-best-kept", TRC,
     "    *best = len;\n    return 1;",
     "    return 1;"),

    # ---- TopologyCoordinate
    ("tcinit-counts", TRC,
     "{\n    tc->TotalNumTrackPolygons = 0;\n    tc->NumTrackPolygons = 0;\n"
     "    tc->NumVerticalTrackPolygons = 0;\n"
     "    tc->NumUpsideDownTrackPolygons = 0;\n"
     "    topology_clear_interest_bbox(tc);",
     "{\n    topology_clear_interest_bbox(tc);"),
    ("tcdestroy-num", TRC,
     "    topotree_remove(&TheTopologyTree, tc->TrackPolygonTable,\n"
     "                    tc->TotalNumTrackPolygons);\n}",
     "    topotree_remove(&TheTopologyTree, tc->TrackPolygonTable,\n"
     "                    tc->NumTrackPolygons);\n}"),
    ("tcclear-num", TRC,
     "tc->TotalNumTrackPolygons);\n    tc->NumUpsideDownTrackPolygons = 0;",
     "tc->NumTrackPolygons);\n    tc->NumUpsideDownTrackPolygons = 0;"),
    ("tcclear-cache", TRC,
     "    bInitializeBoundingBox2(&tc->CachedBBoxMin, &tc->CachedBBoxMax);\n"
     "    topotree_remove",
     "    topotree_remove"),
    ("sib-contains", TRC,
     "&tc->InterestBBoxMin, &tc->InterestBBoxMax))\n        return;\n",
     "&tc->InterestBBoxMin, &tc->InterestBBoxMax))\n        ;\n"),
    ("sib-rpad", TRC,
     "    r = r + 0.5f;",
     "    r = r + 0.25f;"),
    ("sib-scale", TRC,
     "        scale = scale * 0.5f;",
     "        scale = scale * 0.25f;"),
    ("sib-32", TRC,
     "if (sqrtf(dx * dx + dy * dy) < 32.0f)",
     "if (sqrtf(dx * dx + dy * dy) < 16.0f)"),
    ("sib-tries", TRC,
     "    for (i = 0; i < 10; i++) {\n        float dx, dy;",
     "    for (i = 0; i < 3; i++) {\n        float dx, dy;"),
    ("sib-vel-scale", TRC,
     "bScaleAdd2(&ahead, pos, vel, scale);",
     "bScaleAdd2(&ahead, pos, vel, 1.0f);"),
    ("sib-pass1-ud", TRC,
     "        if (local[i]->Flags & TRACKPOLY_UPSIDE_DOWN)\n            continue;\n",
     ""),
    ("sib-pass2-flag", TRC,
     "            if (local[i]->Flags & TRACKPOLY_VERTICAL)\n"
     "                table[k++] = local[i];",
     "            if (local[i]->Flags & TRACKPOLY_UPSIDE_DOWN)\n"
     "                table[k++] = local[i];"),
    ("sib-pass3-guard", TRC,
     "    if (k != n) {\n        for (i = 0; i < n; i++) {\n"
     "            if (local[i]->Flags & TRACKPOLY_UPSIDE_DOWN)",
     "    if (1) {\n        for (i = 0; i < n; i++) {\n"
     "            if (local[i]->Flags & TRACKPOLY_UPSIDE_DOWN)"),
    ("sib-ud-count", TRC,
     "tc->NumUpsideDownTrackPolygons = k - vertical;",
     "tc->NumUpsideDownTrackPolygons = k - vertical - tc->NumTrackPolygons;"),
    ("sib-total", TRC,
     "    tc->TotalNumTrackPolygons = n;\n    tc->NumUpsideDown",
     "    tc->TotalNumTrackPolygons = k;\n    tc->NumUpsideDown"),
    ("sib-vertical-count", TRC,
     "        vertical = k - base;",
     "        vertical = k;"),

    ("elev-found-init", TRC,
     "    if (found != NULL)\n        *found = 1;\n",
     ""),
    ("elev-inside-border", TRC,
     "&xy, 0.0f))\n        topology_set_interest_bbox",
     "&xy, 1.0f))\n        topology_set_interest_bbox"),
    ("elev-r8", TRC,
     "topology_set_interest_bbox(tc, &xy, 8.0f, NULL);",
     "topology_set_interest_bbox(tc, &xy, 4.0f, NULL);"),
    ("elev-hi", TRC,
     "    hi = pt->z + 1.0f;",
     "    hi = pt->z + 0.5f;"),
    ("elev-one-pass", TRC,
     "for (pass = 0; pass < 2 && hit < 0; pass++) {",
     "for (pass = 0; pass < 1 && hit < 0; pass++) {"),
    ("elev-bbminx", TRC,
     "if (!(tp->BBoxMin.x <= px) || !(px <= tp->BBoxMax.x))",
     "if (!(tp->BBoxMin.x < px) || !(px <= tp->BBoxMax.x))"),
    ("elev-bbmaxy", TRC,
     "!(py <= tp->BBoxMax.y))",
     "!(py < tp->BBoxMax.y))"),
    ("elev-three-edges", TRC,
     "&tp->Vertices[(e + 1) % 4];",
     "&tp->Vertices[(e + 1) % 3];"),
    ("elev-zero-edge", TRC,
     "                if (ve->x == vj->x && ve->y == vj->y)\n"
     "                    continue;\n",
     ""),
    ("elev-cross-sign", TRC,
     "cross = (vj->y - ve->y) * (px - ve->x)\n"
     "                      - (vj->x - ve->x) * (py - ve->y);",
     "cross = (vj->x - ve->x) * (py - ve->y)\n"
     "                      - (vj->y - ve->y) * (px - ve->x);"),
    ("elev-m-init", TRC,
     "            m = -1.0f;",
     "            m = 0.0f;"),
    ("elev-m-strict", TRC,
     "            if (!(m <= 0.0f))\n                continue;",
     "            if (!(m < 0.0f))\n                continue;"),
    ("elev-lo-le", TRC,
     "if (!(lo < elev) || !(elev < hi))",
     "if (!(lo <= elev) || !(elev < hi))"),
    ("elev-hi-le", TRC,
     "if (!(lo < elev) || !(elev < hi))",
     "if (!(lo < elev) || !(elev <= hi))"),
    ("elev-inf-ignored", TRC,
     "if ((tp->Flags & TRACKPOLY_INFINITELY_HIGH) || !(m < 0.0f)) {",
     "if (!(m < 0.0f)) {"),
    ("elev-edge-strict", TRC,
     "if ((tp->Flags & TRACKPOLY_INFINITELY_HIGH) || !(m < 0.0f)) {",
     "if (tp->Flags & TRACKPOLY_INFINITELY_HIGH) {"),
    ("elev-lo-kept", TRC,
     "                lo = elev;\n                cand = i;",
     "                cand = i;"),
    ("elev-second-hi", TRC,
     "        hi = BVECTOR_FLT_MAX;",
     "        hi = hi + 100.0f;"),
    ("elev-miss-z", TRC,
     "        result = pt->z;\n        if (found != NULL)",
     "        result = 0.0f;\n        if (found != NULL)"),
    ("elev-miss-terrain", TRC,
     "            *terrain = 1;",
     "            *terrain = 0;"),
    ("elev-miss-normal", TRC,
     "            normal->z = -1.0f;",
     "            normal->z = 1.0f;"),
    ("elev-reorder-6", TRC,
     "        if (hit >= 5) {",
     "        if (hit >= 6) {"),
    ("elev-reorder-swap", TRC,
     "            for (k = hit; k > 0; k--)\n"
     "                table[k] = table[k - 1];\n",
     "            table[hit] = table[0];\n"),
    ("elev-normal-pad", TRC,
     "            normal->pad = tp->PlaneDistance;",
     "            normal->pad = 0.0f;"),
    ("elev-timing-scale", TRC,
     "bGetTickerDifference(start, bGetTicker()) * 1000.0f;",
     "bGetTickerDifference(start, bGetTicker()) * 100.0f;"),
    ("elev-timing-slot", TRC,
     "TopologyTiming[TopologyTimingIndex % 10u] =",
     "TopologyTiming[(TopologyTimingIndex + 1) % 10u] ="),
    ("elev-timing-order", TRC,
     "bGetTickerDifference(start, bGetTicker())",
     "bGetTickerDifference(bGetTicker(), start)"),
    ("elev-timing-index", TRC,
     "    TopologyTimingIndex++;\n",
     ""),

    ("hastopo-z", TRC,
     "    p.z = TRACK_PROBE_Z;",
     "    p.z = 0.0f;"),
    ("tcseg-twosided", TRC,
     "&mn, &mx, 0))\n            return 1;",
     "&mn, &mx, 1))\n            return 1;"),
    ("tcseg-floors-only", TRC,
     "    for (i = 0; i < tc->TotalNumTrackPolygons; i++) {\n"
     "        if (trackpolygon_test_segment",
     "    for (i = 0; i < tc->NumTrackPolygons; i++) {\n"
     "        if (trackpolygon_test_segment"),
    ("tcseg-far", TRC,
     "    float best = TRACK_FAR;\n    int i;\n\n"
     "    bInitializeBoundingBox3At(&mn, &mx, a);",
     "    float best = 1.0f;\n    int i;\n\n"
     "    bInitializeBoundingBox3At(&mn, &mx, a);"),

    ("con-floors-only", TRC,
     "    for (i = 0; i < tc->TotalNumTrackPolygons; i++) {\n"
     "        const TrackPolygon *tp",
     "    for (i = 0; i < tc->NumTrackPolygons; i++) {\n"
     "        const TrackPolygon *tp"),
    ("con-box-dist", TRC,
     "bExpandBoundingBox3R(&mn, &mx, to, dist);",
     "bExpandBoundingBox3R(&mn, &mx, to, 0.0f);"),
    ("con-len", TRC,
     "    if (!(best < len))\n        return 0;",
     "    if (!(best < len + dist))\n        return 0;"),
    ("con-vertical-flag", TRC,
     "        if (hitp->Flags & TRACKPOLY_VERTICAL) {",
     "        if (hitp->Flags & TRACKPOLY_UPSIDE_DOWN) {"),
    ("con-k", TRC,
     "            k = s / len;",
     "            k = s / best;"),
    ("con-lift", TRC,
     "d.z = d.z + lift * (1.0f - k);",
     "d.z = d.z + lift * k;"),
    ("con-rot-pad", TRC,
     "            to->pad = from->pad + d.pad;\n        } else if",
     "            to->pad = d.pad;\n        } else if"),
    ("con-ud-sign", TRC,
     "/ hitp->Normal.z - dist;",
     "/ hitp->Normal.z + dist;"),
    ("con-floor-dist", TRC,
     "/ hitp->Normal.z + dist;\n        }\n        return 1;",
     "/ hitp->Normal.z;\n        }\n        return 1;"),
    ("con-scale-s", TRC,
     "        s = best - dist;\n        bNormalize3To(&d, &d, s);",
     "        s = best + dist;\n        bNormalize3To(&d, &d, s);"),
    ("con-scale-pad", TRC,
     "        to->pad = from->pad + d.pad;\n        return 1;\n    }\n    return 1;",
     "        to->pad = from->pad;\n        return 1;\n    }\n    return 1;"),
    ("con-other-type", TRC,
     "        return 1;\n    }\n    return 1;\n}",
     "        return 1;\n    }\n    return 0;\n}"),
    ("con-dpad", TRC,
     "    d.pad = to->pad - from->pad;",
     "    d.pad = 0.0f;"),

    # ---- TopologyTree
    ("treeinit-prev", TRC,
     "    t->TrackPolygonList.pPrev = p32_of(&t->TrackPolygonList);\n",
     ""),
    ("treeinit-polys", TRC,
     "    t->NumPolygons = 0;\n    t->pPolygonIndexTable = NULL;",
     "    t->pPolygonIndexTable = NULL;"),
    ("inittree-overflow", TRC,
     "    bClearSlotPoolFlag(TrackPolygonSlotPool, BSP_OVERFLOW_IF_FULL);\n",
     ""),
    ("inittree-zero", TRC,
     "    bClearSlotPoolFlag(TrackPolygonSlotPool, BSP_ZERO_ALLOCATED_MEMORY);\n",
     ""),
    ("close-keep-slots", TRC,
     "        trackpolygon_destroy((TrackPolygon *)n, 3);\n    }\n"
     "    bDeleteSlotPool",
     "        trackpolygon_destroy((TrackPolygon *)n, 2);\n    }\n"
     "    bDeleteSlotPool"),
    ("close-keep-pointer", TRC,
     "    bDeleteSlotPool(TrackPolygonSlotPool);\n"
     "    TrackPolygonSlotPool = NULL;\n",
     "    bDeleteSlotPool(TrackPolygonSlotPool);\n"),
    ("loader-pad", TRC,
     "(((uintptr_t)chunk + 23) & ~(uintptr_t)15)",
     "(((uintptr_t)chunk + 15) & ~(uintptr_t)15)"),
    ("loader-nodes", TRC,
     "(uint32_t)(aligned - body)) >> 3);",
     "(uint32_t)(aligned - body)) >> 2);"),
    ("loader-squares", TRC,
     "(uint32_t)(aligned - body)) / 12u);",
     "(uint32_t)(aligned - body)) / 16u);"),
    ("loader-polys-reset", TRC,
     "t->pPolygonTable[i].TrackPolygonNumber = -1;",
     "t->pPolygonTable[i].TrackPolygonNumber = 0;"),
    ("loader-polys-count", TRC,
     "int32_t n = (int32_t)(size >> 5);",
     "int32_t n = (int32_t)(size >> 6);"),
    ("loader-index", TRC,
     "t->NumPolygonIndicies = (int32_t)(size >> 1);",
     "t->NumPolygonIndicies = (int32_t)(size >> 2);"),
    ("unloader-nodes", TRC,
     "        t->NumNodes = 0;\n        t->pNodeTable = NULL;",
     "        t->pNodeTable = NULL;"),
    ("unloader-other", TRC,
     "        t->pPolygonIndexTable = NULL;\n        return 1;\n    }\n"
     "    return 0;",
     "        t->pPolygonIndexTable = NULL;\n        return 1;\n    }\n"
     "    return 1;"),
    ("corner-mask", TRC,
     "& -2097152;",
     "& -1048576;"),
    ("corner-floor", TRC,
     "int32_t q = ee_trunc_w(f * 65536.0f) & -2097152;",
     "int32_t q = (int32_t)floorf(f * 65536.0f) & -2097152;"),
    ("sq-x-strict", TRC,
     "        if (mx <= x)\n            q = 1;",
     "        if (mx < x)\n            q = 1;"),
    ("sq-y-strict", TRC,
     "        if (my <= y)\n            q += 2;",
     "        if (my < y)\n            q += 2;"),
    ("sq-nearest", TRC,
     "            if (!nearest)\n                return NULL;",
     "            if (nearest)\n                return NULL;"),
    ("sq-pick-last", TRC,
     "if (dd < best || pick < 0) {",
     "if (dd <= best || pick < 0) {"),
    ("sq-pick-none", TRC,
     "            int32_t pick = -1;",
     "            int32_t pick = 0;"),
    ("gip-reuse", TRC,
     "        if (p->UsedByNeighbourFlag != 0)\n            continue;\n",
     ""),
    ("gip-minx", TRC,
     "if (!(xy_of(p->VerticesX[m & 3]) <= bmax->x))",
     "if (!(xy_of(p->VerticesX[m & 3]) < bmax->x))"),
    ("gip-maxy", TRC,
     "if (!(bmin->y <= xy_of(p->VerticesY[m >> 6])))",
     "if (!(bmin->y < xy_of(p->VerticesY[m >> 6])))"),
    ("gip-no-mark", TRC,
     "            p->UsedByNeighbourFlag = 1;\n",
     ""),
    ("gip-max", TRC,
     "        if (count < max) {",
     "        if (count <= max) {"),
    ("flush-ref", TRC,
     "->ReferenceCount != 0) {",
     "->ReferenceCount > 1) {"),
    ("flush-cap", TRC,
     "if (!(deleted < 101))",
     "if (!(deleted < 100))"),
    ("flush-resume", TRC,
     "        n = node_at(prev->pNext);",
     "        n = node_at(head->pNext);"),
    ("assign-lookup", TRC,
     "if (p->TrackPolygonNumber >= 0) {",
     "if (p->TrackPolygonNumber > 0) {"),
    ("assign-append", TRC,
     "        append_node(&t->TrackPolygonList, &tp->node);\n",
     ""),
    ("assign-ref", TRC,
     "tp->ReferenceCount = (uint8_t)(tp->ReferenceCount + 1);",
     "tp->ReferenceCount = (uint8_t)(tp->ReferenceCount + 2);"),
    ("unassign-zero", TRC,
     "tp->ReferenceCount = (uint8_t)(tp->ReferenceCount - 1);",
     "tp->ReferenceCount = 0;"),
    ("build-s1", TRC,
     "s1 = topotree_get_square(t, bmax->x, bmin->y, 0);",
     "s1 = topotree_get_square(t, bmin->x, bmax->y, 0);"),
    ("build-keep-flag", TRC,
     "        stack[i]->UsedByNeighbourFlag = 0;\n",
     ""),
    ("build-max", TRC,
     "        n += topotree_get_intersecting_polygons(t, stack + n, max - n, s1,",
     "        n += topotree_get_intersecting_polygons(t, stack + n, max, s1,"),
    ("remove-first", TRC,
     "        topotree_unassign(t, table[i]);",
     "        topotree_unassign(t, table[0]);"),

    # ---- TrackInfo, road noise, the loader
    ("info-zero", TRC,
     "if (i <= 0 || HighestTrackNumber < i)",
     "if (i < 0 || HighestTrackNumber < i)"),
    ("info-highest", TRC,
     "if (i <= 0 || HighestTrackNumber < i)",
     "if (i <= 0 || HighestTrackNumber <= i)"),
    ("info-unnamed", TRC,
     "return p->Name[0] != 0 ? p : NULL;",
     "return p;"),
    ("grid-11", TRC,
     "(uint32_t)x * (uint32_t)y * 11u;",
     "(uint32_t)x * (uint32_t)y * 7u;"),
    ("grid-13", TRC,
     "((uint32_t)y + 1u) * 13u;",
     "((uint32_t)y + 1u) * 17u;"),
    ("grid-xor", TRC,
     "RoadNoiseTable[(a + b) & 15u]",
     "RoadNoiseTable[(a ^ b) & 15u]"),
    ("noise-floor-x", TRC,
     "    if (fx < flx)\n        flx = flx - 1.0f;\n",
     ""),
    ("noise-floor-y", TRC,
     "    if (fy < fly)",
     "    if (fy <= fly)"),
    ("noise-corner", TRC,
     "* track_get_road_noise_grid_value(ix, iy + 1);",
     "* track_get_road_noise_grid_value(ix + 1, iy + 1);"),
    ("noise-order", TRC,
     "acc = ((1.0f - tx) * (1.0f - ty)) * track_get_road_noise_grid_value(ix, iy);",
     "acc = (1.0f - tx) * ((1.0f - ty) * track_get_road_noise_grid_value(ix, iy));"),
    ("noise-scale", TRC,
     "    return acc * info->RoadNoiseScale;",
     "    return acc;"),
    ("noise-spacing", TRC,
     "float fy = p->y * info->RoadNoiseGridSpacingInverse;",
     "float fy = p->y * info->RoadNoiseScale;"),
    ("loader-trackno", TRC,
     "LoadedTrackNumber = CurrentTrackInfo->TrackNumber;",
     "LoadedTrackNumber = CurrentTrackInfo->SameAsTrackNumber;"),
    ("loader-54", TRC,
     "hidden = track_get_info(54);",
     "hidden = track_get_info(53);"),
    ("loader-54-name", TRC,
     "memset(hidden, 0, sizeof(TrackInfo));",
     "memset(hidden, 0, 32);"),
    ("loader-highest", TRC,
     "HighestTrackNumber = (int32_t)(size / 160u);",
     "HighestTrackNumber = (int32_t)(size / 160u) - 1;"),
    ("loader-markers-round", TRC,
     "int32_t n = (int32_t)(size / 24u);",
     "int32_t n = (int32_t)((size + 23) / 24u);"),
    ("loader-fallthrough", TRC,
     "    return topotree_loader(&TheTopologyTree, chunk) != 0;",
     "    return 1;"),
    ("unloader-markers", TRC,
     "            unlink_node(&m->node);\n",
     ""),
    ("unloader-cur", TRC,
     "        CurrentTrackInfo = NULL;\n",
     ""),
    ("unloader-highest", TRC,
     "        HighestTrackNumber = 0;\n",
     ""),
    ("unloader-loaded", TRC,
     "        LoadedTrackNumber = 0;\n",
     ""),
    ("static-tree", TRC,
     "    topotree_init(&TheTopologyTree);\n}",
     "}"),

    # ---- TerrainType
    ("upper-fold", TTC,
     "        v &= 0x5f;",
     "        v &= 0x7f;"),
    ("icmp-stop", TTC,
     "if (ca == 0 || cb == 0 || ca != cb)",
     "if (ca == 0 || cb == 0)"),
    ("icmp-diff", TTC,
     "            return ca - cb;",
     "            return ca != cb;"),
    ("match-null", TTC,
     "    if (name == NULL)\n        return TERRAIN_TYPE_NONE;\n",
     ""),
    ("match-last", TTC,
     "    for (i = 0; i < NUM_TERRAIN_TYPES; i++) {\n        if (str_icmp",
     "    for (i = 0; i < NUM_TERRAIN_TYPES - 1; i++) {\n        if (str_icmp"),
    ("matchhash-last", TTC,
     "    for (i = 0; i < NUM_TERRAIN_TYPES; i++) {\n        if (TerrainTypeInfoTable",
     "    for (i = 0; i < NUM_TERRAIN_TYPES - 1; i++) {\n        if (TerrainTypeInfoTable"),
    ("hash-init", TTC,
     "bchunk_hash(TerrainTypeInfoTable[i].Name);",
     "bchunk_hash(TerrainTypeInfoTable[i].Name) ^ 1;"),
    ("hash-init-last", TTC,
     "    for (i = 0; i < NUM_TERRAIN_TYPES; i++)\n        TerrainTypeInfoTable[i].NameHash",
     "    for (i = 0; i < NUM_TERRAIN_TYPES - 1; i++)\n        TerrainTypeInfoTable[i].NameHash"),
    # ---- Car::FindFlatOnTrackPosition and PutFlatOnTrack (cartrack.c)
    ("flat-off-centre", CTC,
     "{ 0.0f, 0.0f }, { 1.0f, 0.0f }",
     "{ 0.5f, 0.0f }, { 1.0f, 0.0f }"),
    ("flat-off-east", CTC,
     "{ 1.0f, 0.0f }, { -1.0f, 0.0f }",
     "{ 2.0f, 0.0f }, { -1.0f, 0.0f }"),
    ("flat-off-swap-ew", CTC,
     "{ 1.0f, 0.0f }, { -1.0f, 0.0f }",
     "{ -1.0f, 0.0f }, { 1.0f, 0.0f }"),
    ("flat-off-swap-ns", CTC,
     "{ 0.0f, 1.0f }, { 0.0f, -1.0f }",
     "{ 0.0f, -1.0f }, { 0.0f, 1.0f }"),
    ("flat-off-axes", CTC,
     "{ 0.0f, 0.0f }, { 1.0f, 0.0f }, { -1.0f, 0.0f },\n"
     "        { 0.0f, 1.0f }, { 0.0f, -1.0f },",
     "{ 0.0f, 0.0f }, { 0.0f, 1.0f }, { 0.0f, -1.0f },\n"
     "        { 1.0f, 0.0f }, { -1.0f, 0.0f },"),
    ("flat-probe-y", CTC,
     "probe.y = offs[i][1] + pos->y;",
     "probe.y = offs[i][0] + pos->y;"),
    ("flat-probe-z", CTC,
     "probe.z = pos->z;",
     "probe.z = pos->z + 1.0f;"),
    ("flat-samples-4", CTC,
     "    for (i = 0; i < 5; i++) {\n        probe.x",
     "    for (i = 0; i < 4; i++) {\n        probe.x"),
    ("flat-terrain-null", CTC,
     "h[i] = topology_get_elevation(tc, &probe, &terrain[i], NULL, NULL);",
     "h[i] = topology_get_elevation(tc, &probe, NULL, NULL, NULL);"),
    ("flat-roll-direct", CTC,
     "(((h[1] - h[0]) - (h[2] - h[0])) * 0.5f)",
     "((h[1] - h[2]) * 0.5f)"),
    ("flat-pitch-direct", CTC,
     "(((h[3] - h[0]) - (h[4] - h[0])) * 0.5f)",
     "((h[3] - h[4]) * 0.5f)"),
    ("flat-roll-sides", CTC,
     "(((h[1] - h[0]) - (h[2] - h[0])) * 0.5f)",
     "(((h[2] - h[0]) - (h[1] - h[0])) * 0.5f)"),
    ("flat-roll-unnegated", CTC,
     "roll = (uint16_t)(0u - (uint32_t)ee_trunc_w(",
     "roll = (uint16_t)((uint32_t)ee_trunc_w("),
    ("flat-pitch-negated", CTC,
     "pitch = (uint16_t)ee_trunc_w(",
     "pitch = (uint16_t)-ee_trunc_w("),
    ("flat-roll-round", CTC,
     "* 0.5f) * CAR_BAMS_PER_RADIAN));",
     "* 0.5f) * CAR_BAMS_PER_RADIAN + 0.5f));"),
    # C's own conversion where cvt.w.s saturates: out of range, x86 gives
    # 0x80000000 either way, which the saturating fixtures separate.
    ("flat-roll-no-saturate", CTC,
     "roll = (uint16_t)(0u - (uint32_t)ee_trunc_w(",
     "roll = (uint16_t)(0u - (uint32_t)(int32_t)("),
    ("flat-pitch-no-saturate", CTC,
     "pitch = (uint16_t)ee_trunc_w(",
     "pitch = (uint16_t)(int32_t)("),
    ("flat-pitch-half", CTC,
     "(((h[3] - h[0]) - (h[4] - h[0])) * 0.5f)",
     "(((h[3] - h[0]) - (h[4] - h[0])) * 0.25f)"),
    ("flat-const-2pi", CTC,
     "#define CAR_BAMS_PER_RADIAN 10435.66796875f",
     "#define CAR_BAMS_PER_RADIAN 10430.3779296875f"),
    ("flat-const-ulp", CTC,
     "#define CAR_BAMS_PER_RADIAN 10435.66796875f",
     "#define CAR_BAMS_PER_RADIAN 10435.6689453125f"),
    ("flat-z-radius", CTC,
     "(h[0] + cti->Wheels[3].Radius)",
     "(h[0] + cti->Wheels[0].Radius)"),
    ("flat-z-posz", CTC,
     "- cti->Wheels[3].PositionZ)",
     "- cti->Wheels[2].PositionZ)"),
    ("flat-z-order", CTC,
     "((h[0] + cti->Wheels[3].Radius) - cti->Wheels[3].PositionZ)",
     "(h[0] + (cti->Wheels[3].Radius - cti->Wheels[3].PositionZ))"),
    # ---- Car::AverageAir and BeginMovement (cartrack.c) --------------------
    ("air-height-kept", CTC, "    *height = 0.0f;\n    cti", "    cti"),
    ("air-height-late", CTC, [
        ("    *height = 0.0f;\n    cti", "    cti", 1),
        ("    sum = 0.0f < d ? d : 0.0f;",
         "    *height = 0.0f;\n    sum = 0.0f < d ? d : 0.0f;", 1)]),
    ("air-front-twice", CTC,
     "(cti->Aero.FrontDownforce + cti->Aero.RearDownforce)",
     "(cti->Aero.FrontDownforce + cti->Aero.FrontDownforce)"),
    ("air-rear-autobalance", CTC,
     "(cti->Aero.FrontDownforce + cti->Aero.RearDownforce)",
     "(cti->Aero.FrontDownforce + cti->Aero.AutoBalanceDownforce)"),
    ("air-share-ulp", CTC,
     "#define CAR_AIR_DOWNFORCE_SHARE 0.300000012f",
     "#define CAR_AIR_DOWNFORCE_SHARE 0.300000042f"),
    ("air-no-gravity", CTC,
     "/ cti->Body.Mass + RIGIDBODY_GRAVITY);",
     "/ cti->Body.Mass);"),
    ("air-gravity-in-mass", CTC,
     "/ cti->Body.Mass + RIGIDBODY_GRAVITY);",
     "/ (cti->Body.Mass + RIGIDBODY_GRAVITY));"),
    ("air-down-up", CTC, "    down = -(speed", "    down = (speed"),
    ("air-downforce-unscaled", CTC,
     "    down = -(speed * ((", "    down = -(((" ),
    ("air-speed-forward", CTC,
     "    speed = st->VelocityMagnitude;", "    speed = st->ForwardSpeed;"),
    ("air-wheel-matrix-i", CTC,
     "bMulMatrixVec3(&p, &st->WheelMatrix[0], &p);",
     "bMulMatrixVec3(&p, &st->WheelMatrix[i], &p);"),
    ("air-no-wheel-matrix", CTC,
     "        bMulMatrixVec3(&p, &st->WheelMatrix[0], &p);\n", ""),
    ("air-matrix-order", CTC,
     "        bMulMatrixVec3(&p, &st->WheelMatrix[0], &p);\n"
     "        bMulMatrixVec3(&p, &body, &p);",
     "        bMulMatrixVec3(&p, &body, &p);\n"
     "        bMulMatrixVec3(&p, &st->WheelMatrix[0], &p);"),
    ("air-body-translation", CTC,
     "    body.v3.y = st->Position.y;", "    body.v3.y = st->Position.x;"),
    ("air-body-row", CTC,
     "    body.v1 = st->BodyMatrix.v1;", "    body.v1 = st->BodyMatrix.v2;"),
    ("air-radius-0", CTC, "Wheels[i].Radius", "Wheels[0].Radius"),
    ("air-radius-up", CTC,
     "        p.z = -c->pCarTypeInfo", "        p.z = c->pCarTypeInfo"),
    ("air-radius-in-x", CTC,
     "        p.x = 0.0f;\n        p.y = 0.0f;\n        p.z = -c",
     "        p.y = 0.0f;\n        p.x = p.z = -c"),
    ("air-no-accumulate", CTC,
     "acc.x = p.x * 0.25f + acc.x;", "acc.x = p.x * 0.25f;"),
    ("air-accumulate-cross", CTC,
     "acc.y = p.y * 0.25f + acc.y;", "acc.y = p.y * 0.25f + acc.x;"),
    ("air-half", CTC,
     "acc.z = p.z * 0.25f + acc.z;", "acc.z = p.z * 0.5f + acc.z;"),
    ("air-three-wheels", CTC,
     "    for (i = 0; i < 4; i++) {\n        p.x",
     "    for (i = 0; i < 3; i++) {\n        p.x"),
    ("air-first-normal", CTC,
     "topology_get_elevation(tc, &acc, NULL, NULL, NULL);",
     "topology_get_elevation(tc, &acc, NULL, &normal, NULL);"),
    ("air-sample-no-normal", CTC,
     "topology_get_elevation(tc, &q, NULL, &normal, NULL);",
     "topology_get_elevation(tc, &q, NULL, NULL, NULL);"),
    ("air-rate-half", CTC,
     "#define CAR_AIR_SAMPLE_RATE     0.333333343f",
     "#define CAR_AIR_SAMPLE_RATE     0.5f"),
    ("air-n-round", CTC,
     "ee_trunc_w(speed * *time * CAR_AIR_SAMPLE_RATE);",
     "ee_trunc_w(speed * *time * CAR_AIR_SAMPLE_RATE + 0.5f);"),
    ("air-n-no-saturate", CTC,
     "ee_trunc_w(speed * *time * CAR_AIR_SAMPLE_RATE);",
     "(int32_t)(speed * *time * CAR_AIR_SAMPLE_RATE);"),
    ("air-n-no-speed", CTC,
     "ee_trunc_w(speed * *time * CAR_AIR_SAMPLE_RATE);",
     "ee_trunc_w(*time * CAR_AIR_SAMPLE_RATE);"),
    ("air-no-floor", CTC,
     "    sum = 0.0f < d ? d : 0.0f;", "    sum = d;"),
    ("air-start-0", CTC, "    i = 1;\n    if (i < n)", "    i = 0;\n    if (i < n)"),
    ("air-t-last", CTC,
     "t = (*time * (float)i) / samples;",
     "t = (*time * (float)i) / (samples - 1.0f);"),
    ("air-t-halved", CTC,
     "q.z = (fall.z * t + vel.z) * t + acc.z;",
     "q.z = (fall.z * 0.5f * t + vel.z) * t + acc.z;"),
    ("air-no-fall", CTC,
     "q.z = (fall.z * t + vel.z) * t + acc.z;",
     "q.z = vel.z * t + acc.z;"),
    ("air-q-cross", CTC,
     "q.y = (fall.y * t + vel.y) * t + acc.y;",
     "q.y = (fall.y * t + vel.x) * t + acc.y;"),
    ("air-q-start", CTC,
     "q.x = (fall.x * t + vel.x) * t + acc.x;",
     "q.x = (fall.x * t + vel.x) * t + st->Position.x;"),
    ("air-height-any", CTC,
     "            if (*height < d)\n                *height = d;",
     "            *height = d;"),
    ("air-stop-below", CTC, "if (!(0.0f < d)) {", "if (d < 0.0f) {"),
    ("air-stop-time-kept", CTC, "                *time = t;\n", ""),
    ("air-stop-uncounted", CTC,
     "                *time = t;\n                i++;\n",
     "                *time = t;\n"),
    ("air-stop-summed", CTC,
     "                *time = t;\n",
     "                *time = t;\n                sum += d;\n"),
    ("air-no-stop", CTC,
     "                i++;\n                break;\n",
     "                i++;\n                continue;\n"),
    ("air-while-le", CTC, "        } while (i < n);", "        } while (i <= n);"),
    ("air-mean-plain", CTC,
     "    return sum / (float)i - 1.0f;", "    return sum / (float)i;"),
    ("air-mean-less-one", CTC,
     "    return sum / (float)i - 1.0f;",
     "    return sum / (float)(i - 1);"),
    ("air-one-always-mean", CTC,
     "    if (i == 1)\n        return sum;\n", ""),
    ("bm-dt-ge", CTC, "    if (0.0f < dt) {", "    if (0.0f <= dt) {"),
    ("bm-dt-any", CTC, "    if (0.0f < dt) {", "    if (dt != 1.0f) {"),
    ("bm-no-old-vel", CTC, "        c->vOldVel = st->Velocity;\n", ""),
    ("bm-no-old-ang", CTC, "        c->vOldAngVel = st->AngularVelocity;\n",
     ""),
    ("bm-old-ang-vel", CTC,
     "        c->vOldAngVel = st->AngularVelocity;",
     "        c->vOldAngVel = st->Velocity;"),
    ("bm-speed-magnitude", CTC,
     "    speed = sqrtf((v->x * v->x + v->y * v->y) + v->z * v->z);",
     "    speed = st->VelocityMagnitude;"),
    ("bm-speed-order", CTC,
     "    speed = sqrtf((v->x * v->x + v->y * v->y) + v->z * v->z);",
     "    speed = sqrtf(v->x * v->x + (v->y * v->y + v->z * v->z));"),
    ("bm-speed-flat", CTC,
     "    speed = sqrtf((v->x * v->x + v->y * v->y) + v->z * v->z);",
     "    speed = sqrtf(v->x * v->x + v->y * v->y);"),
    ("bm-box-base", CTC,
     "#define CAR_INTEREST_BASE       3.0f",
     "#define CAR_INTEREST_BASE       2.0f"),
    ("bm-box-rate-ulp", CTC,
     "#define CAR_INTEREST_PER_SPEED  0.0500000007f",
     "#define CAR_INTEREST_PER_SPEED  0.0500000045f"),
    ("bm-box-unled", CTC,
     "                                &st->Velocity);",
     "                                NULL);"),
    ("bm-no-topology-test", CTC,
     "    if (topology_has_topology(&c->TheTopologyCoordinate,\n"
     "                              (const bVector2 *)&st->Position)\n"
     "        && 2 <= st->nWheelsTouchingGround) {",
     "    if (2 <= st->nWheelsTouchingGround) {"),
    ("bm-no-wheels-test", CTC,
     "\n        && 2 <= st->nWheelsTouchingGround) {", ") {"),
    ("bm-wheels-gt", CTC,
     "&& 2 <= st->nWheelsTouchingGround", "&& 2 < st->nWheelsTouchingGround"),
    ("bm-wheels-unsigned", CTC,
     "&& 2 <= st->nWheelsTouchingGround",
     "&& 2u <= (uint32_t)st->nWheelsTouchingGround"),
    ("bm-trough-x-twice", CTC,
     "        c->LastInTroughPosition.y = st->Position.y;",
     "        c->LastInTroughPosition.y = st->Position.x;"),
    ("bm-no-timestep", CTC, "    carstate_begin_timestep(st);\n}", "}"),
    ("flat-z-cog", CTC,
     "+ cti->CenterOfGravity.z;",
     "+ cti->CenterOfGravity.y;"),
    ("flat-z-centre", CTC,
     "pos->z = ((h[0] + cti",
     "pos->z = ((h[3] + cti"),
    ("flat-rot-xy", CTC,
     "    eRotateX(&local, &local, pitch);\n    eRotateY(m, &local, roll);",
     "    eRotateY(&local, &local, roll);\n    eRotateX(m, &local, pitch);"),
    ("flat-rot-swapped", CTC,
     "    eRotateX(&local, &local, pitch);\n    eRotateY(m, &local, roll);",
     "    eRotateX(&local, &local, roll);\n    eRotateY(m, &local, pitch);"),
    ("flat-yaw-last", CTC,
     "    eRotateZ(&local, &local, angle);\n"
     "    eRotateX(&local, &local, pitch);\n"
     "    eRotateY(m, &local, roll);",
     "    eRotateX(&local, &local, pitch);\n"
     "    eRotateY(&local, &local, roll);\n"
     "    eRotateZ(m, &local, angle);"),
    ("flat-no-identity", CTC,
     "    eIdentity(&local);\n",
     "    local = *m;\n"),
    ("put-angle", CTC,
     "st->Angle, &c->TheTopologyCoordinate);",
     "st->SteeringAngle, &c->TheTopologyCoordinate);"),
    ("put-geom-sign", CTC,
     "st->GeometryPosition.x   = st->Position.x   - cog->x;",
     "st->GeometryPosition.x   = st->Position.x   + cog->x;"),
    ("put-geom-y", CTC,
     "st->GeometryPosition.y   = st->Position.y   - cog->y;",
     "st->GeometryPosition.y   = st->Position.y   - cog->x;"),
    ("put-geom-z", CTC,
     "st->GeometryPosition.z   = st->Position.z   - cog->z;",
     "st->GeometryPosition.z   = st->Position.z;"),
    ("put-geom-pad", CTC,
     "st->GeometryPosition.pad = st->Position.pad - cog->pad;",
     "st->GeometryPosition.pad = st->Position.pad;"),
    ("put-geom-first", CTC,
     "    car_find_flat_on_track_position(c, &st->BodyMatrix, &st->Position,\n"
     "                                    st->Angle, &c->TheTopologyCoordinate);\n"
     "    st->GeometryPosition.x   = st->Position.x   - cog->x;\n"
     "    st->GeometryPosition.y   = st->Position.y   - cog->y;\n"
     "    st->GeometryPosition.z   = st->Position.z   - cog->z;\n"
     "    st->GeometryPosition.pad = st->Position.pad - cog->pad;\n",
     "    st->GeometryPosition.x   = st->Position.x   - cog->x;\n"
     "    st->GeometryPosition.y   = st->Position.y   - cog->y;\n"
     "    st->GeometryPosition.z   = st->Position.z   - cog->z;\n"
     "    st->GeometryPosition.pad = st->Position.pad - cog->pad;\n"
     "    car_find_flat_on_track_position(c, &st->BodyMatrix, &st->Position,\n"
     "                                    st->Angle, &c->TheTopologyCoordinate);\n"),

    # ---- SetInterestBBox(bVector3), emitted in Car.obj
    ("sib3-r", TRC,
     "    topology_set_interest_bbox(tc, (const bVector2 *)pos, r,\n",
     "    topology_set_interest_bbox(tc, (const bVector2 *)pos, r + 1.0f,\n"),
    ("sib3-vel", TRC,
     "                               (const bVector2 *)vel);\n}",
     "                               NULL);\n}"),
]

EQUIVALENT = {
    "flush-resume":
        "every node from the head up to `prev` was walked with a non-zero "
        "reference count, and nothing in the loop changes a count, so a "
        "walk from the head comes back to prev->pNext with `deleted` as it "
        "was: only the time differs",
    "icmp-diff":
        "str_icmp is static and its one caller, terrain_match_name, tests "
        "it against 0 only; ca and cb are sign-extended chars in "
        "[-128, 127], so ca - cb is 0 exactly when ca != cb is",
    "flat-terrain-null":
        "the terrain goes to a local FindFlatOnTrackPosition never reads, "
        "and GetElevation's only use of the pointer is the store into it",
    "air-first-normal":
        "the normal goes to a local AverageAir never reads, and "
        "GetElevation's only use of the pointer is the store into it",
    "air-sample-no-normal":
        "the normal goes to a local AverageAir never reads, and "
        "GetElevation's only use of the pointer is the store into it",
}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name


def mutate_pass(only=None):
    sc = script()
    base, _ = model(sc)
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
    lines, divs = model(sc)
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

    bad = 0
    if divs:
        print("the image divided by zero at %s -- track.c needs ee_div there"
              % " ".join("0x%08x" % pc for pc in divs))
        bad += 1
    if sc.b12:
        n, zero, flat = degenerate_count()
        print("TRACKB12: %d polygons, %d with no normal, %d floors or "
              "ceilings with a zero normal z" % (n, zero, flat))
        if zero or flat:
            bad += 1
    else:
        print("TRACKB12 or GLOBALB not extracted -- their scenarios skipped")
    n = diff(lines, harness)
    print("%d ops, %d lines, %d differ" % (len(sc.ops), len(harness), n))
    sys.exit(1 if (n or rc or bad) else 0)


if __name__ == "__main__":
    main()
