#!/usr/bin/env python3
"""Cross-check 3DS Files/source/trackpath.c -- TrackPathManager and
TrackPathCoordinate, the measuring tape every "who is ahead" and "how far
round the lap" asks -- against the image itself, run in mipsemu.

The model is the image: every TrackPath.obj function but the two
DoSnapshots and PlotToCaffeine runs as shipped, and so does QuickSpline
beneath it (quickspline_check.py checks that on its own), with bNormalize
and bScaleAdd under that. The harness runs the same op script on the port
and prints the same lines. Every float goes both ways as its bits.

**The floats.** The model is `Emu(ieee=True, eediv=True)`: IEEE single, as
the port has it, except that a `div.s` by zero gives the EE's +/-FLT_MAX.
UpdatePosition's ratio divides by TrackLength, which a track whose first
path ends at distance zero leaves at zero; the port spells that division
ee_div. Every division QuickSpline does is guarded, so the switch changes
nothing there.

**The heap.** bMalloc is stubbed in the model and hooked in the harness;
both log the request and label the block h0, h1, ... in order, and both
log a free by label. Init asks for each path's QuickSpline (40 bytes on the
disc, from trackpath.cpp) and QuickSpline's constructor for its buffer
(from quickspline.cpp). The harness prints the image's sizes: 40 for the
spline, whatever the host's struct is, and the buffer less the vector the
port adds. The model's buffers get sixteen zeroed bytes past their end, as
in quickspline_check.

**The spline word.** The disc keeps a QuickSpline * in each path's last
word; the port keeps a handle there (see trackpath.h). The dump prints
either as the label of the spline behind it.

**The stale direction.** UpdatePosition(along, side, path) builds its
position from a direction in the first eight bytes of its frame, and one
way out of its walk reads that without writing it (see trackpath.c). The
port keeps the direction in a static. The model keeps the eight bytes
between calls, puts them back at that stack address before each call and
reads them out after, so both sides start at zero and carry the same
direction from call to call.

**Labels, not pointers.** The checker's path table is `paths`, its point
table `points`, its chunk buffer `chunk`, the QuickSpline basis matrices
`basis`; a pointer inside one prints as name+offset.

**Two images.** The script runs on the demo's image and again on
retail's (retail_model.RetailEmu), where TrackPath.obj is the same but for
three functions retail added: FindClosestPoint weighted by the distance
round the track (0x00207d48), and TrackPathCoordinate::ResetPosition moved
in from Car.obj (0x00208838) with an overload that seeds the search with
the weighted one (0x00208848). The retail run adds their scenarios; the
demo's ResetPosition (0x00134f18, in Car.obj) runs in both.

Scenarios: the three comparisons over their boundaries; an empty manager;
a looping path, an open one and a pair joined by neighbour links, loaded,
measured along and across, reversed, jumped more than 128 units, and
walked with UpdatePosition(along, side) the way CalculateRacerPositions
walks it; both searches, ties included; Init twice, Close, Unload and the
destructor; the loader and unloader over a built chunk, through the global
wrappers too; and TRACKB12's own chunk, when extracted/ has it.

    python tools/trackpath_check.py
    python tools/trackpath_check.py --mutate [--only a,b]
    python tools/trackpath_check.py --dump out/trackpath
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
import retail_model
from mipsemu import M32, MipsError, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/trackpath_test.c"
TPC = "3DS Files/source/trackpath.c"
TPH = "3DS Files/source/trackpath.h"
SOURCES = [HARNESS, TPC,
           "3DS Files/source/quickspline.c",
           "3DS Files/source/bmem.c",
           "3DS Files/source/bmatrix.c",
           "3DS Files/source/bvector.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c",
           "3DS Files/source/bchunk.c"]

HARNESS_TIMEOUT = 300

TRACKB12 = ROOT / "extracted" / "TRACKS" / "TRACKB12.BUN"
TRACKB12_CHUNK = 0x007a8270

# ================================================================ the image

MGR = 0x00313768                    # TheTrackPathManager
BASIS = 0x00314490                  # QuickSplineBasisMatricies

NPATHS, NPOINTS, CHUNK_W, NCOORDS = 16, 512, 4096, 4
PATHS = 0x01E00000                  # NPATHS * 40
POINTS = 0x01E01000                 # NPOINTS * 20
CHUNK = 0x01E04000                  # CHUNK_W words
COORD = 0x01E08000                  # NCOORDS * 40
POS = 0x01E08200                    # the bVector2 a call is handed
SLACK = 16
MAX_DUMP = 80
STALE = 160                         # UpdatePosition(ff)'s frame: 0(sp)

SYM = dict(
    ctor="__16TrackPathManager",
    dtor="_$_16TrackPathManager",
    init="Init__16TrackPathManager",
    close="Close__16TrackPathManager",
    load="Load__16TrackPathManagerP14TrackPathPointiP9TrackPathi",
    unload="Unload__16TrackPathManager",
    loader="Loader__16TrackPathManagerP6bChunk",
    unloader="Unloader__16TrackPathManagerP6bChunk",
    fcp="FindClosestPoint__16TrackPathManagerPC8bVector2",
    fcap="FindClosestAdjacentPointOnSamePath__16TrackPathManager"
         "PC8bVector2P14TrackPathPoint",
    update="UpdatePosition__16TrackPathManagerP19TrackPathCoordinate"
           "PC8bVector2",
    along="UpdatePosition__16TrackPathManagerP19TrackPathCoordinateffi",
    cmp0="CompareDistances__16TrackPathManagerff",
    cmp1="ComparePercentDistances__16TrackPathManagerff",
    cmp2="CompareRatios__16TrackPathManagerff",
    cctor="__19TrackPathCoordinate",
    cctor_at="__19TrackPathCoordinatePC8bVector2",
    cupdate="UpdatePosition__19TrackPathCoordinatePC8bVector2",
    calong="UpdatePosition__19TrackPathCoordinateff",
    g_init="InitTrackPaths__Fv",
    g_close="CloseTrackPaths__Fv",
    g_loader="LoaderTrackPath__FP6bChunk",
    g_unloader="UnloaderTrackPath__FP6bChunk",
    g_load="LoadTrackPaths__FP14TrackPathPointiP9TrackPathi",
    g_unload="UnloadTrackPaths__Fv",
    creset="ResetPosition__19TrackPathCoordinatePC8bVector2",
)
# Retail's own, which have no demo twin; retail's ResetPosition(pos) is
# the same code as the demo's, moved from Car.obj into TrackPath.obj.
RETAIL_FN = dict(fcpd=0x00207d48, creset=0x00208838, cresetd=0x00208848)

# ---- the ops -----------------------------------------------------------------

(OP_TAG, OP_PATH, OP_POINT, OP_CHUNK, OP_LOAD, OP_SETUP, OP_CLOSE,
 OP_UNLOAD, OP_CTOR, OP_DTOR, OP_LOADER, OP_UNLOADER, OP_MPOKE, OP_DUMP,
 OP_FCP, OP_FCAP, OP_CINIT, OP_CINITAT, OP_UPDATE, OP_ALONG, OP_CPOKE,
 OP_CDUMP, OP_CMP, OP_FCPD, OP_CRESET, OP_CRESETD) = range(26)

ARGS = {OP_TAG: 1, OP_PATH: 11, OP_POINT: 6, OP_CHUNK: 2, OP_LOAD: 3,
        OP_SETUP: 1, OP_CLOSE: 1, OP_UNLOAD: 1, OP_CTOR: 0, OP_DTOR: 0,
        OP_LOADER: 1, OP_UNLOADER: 1, OP_MPOKE: 2, OP_DUMP: 1, OP_FCP: 2,
        OP_FCAP: 3, OP_CINIT: 1, OP_CINITAT: 3, OP_UPDATE: 4, OP_ALONG: 5,
        OP_CPOKE: 3, OP_CDUMP: 1, OP_CMP: 3, OP_FCPD: 3, OP_CRESET: 3,
        OP_CRESETD: 4}

M_LEN, M_REV, M_NPATHS, M_PATHS, M_NPOINTS, M_POINTS = range(6)
MFIELD = [(0, "f"), (4, "i"), (8, "i"), (12, "paths"), (16, "i"),
          (20, "points")]
(C_X, C_Y, C_PT, C_PARAM, C_RATIO, C_DIST, C_DIRX, C_DIRY, C_CAF,
 C_CAFHI) = range(10)
CFIELD = {C_X: 0, C_Y: 4, C_PT: 8, C_PARAM: 12, C_RATIO: 16, C_DIST: 20,
          C_DIRX: 24, C_DIRY: 28, C_CAF: 32, C_CAFHI: 36}
# What C_CAF writes: an address in no labelled region on either side, so
# both print it as "?".
CAF_JUNK = 0x00001234


def fb(x):
    """A Python float's single-precision bits."""
    return struct.unpack("<I", struct.pack("<f", x))[0]


def bf(b):
    return struct.unpack("<f", struct.pack("<I", b & M32))[0]


def f32(x):
    return bf(fb(x))


def words(fmt, *vals):
    raw = struct.pack(fmt, *vals)
    return list(struct.unpack("<%dI" % (len(raw) // 4), raw))


def path_words(num, looping, begin, end, n, bd, ed, ratio, bp, ep, word=0):
    return words("<bbhhhfffffffI", num, looping, begin, end, n, bd, ed,
                 ratio, bp[0], bp[1], ep[0], ep[1], word)


def point_words(x, y, num, dont, nb, dist):
    return words("<ffbbhhhf", x, y, num, dont, nb[0], nb[1], nb[2], dist)


class Script(object):
    def __init__(self):
        self.ops = []
        self.tags = []

    def op(self, code, *args):
        assert len(args) == ARGS[code], (code, args)
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
            flat.extend(o)
        out.append(len(flat))
        out.extend(flat)
        return struct.pack("<%di" % len(out), *[s32(v & M32) for v in out])

    # ---- sugar -----------------------------------------------------------

    def tables(self, t):
        for i, p in enumerate(t.paths):
            self.op(OP_PATH, i, *p)
        for i, p in enumerate(t.points):
            self.op(OP_POINT, i, *p)

    def chunk(self, ws):
        for i, w in enumerate(ws):
            self.op(OP_CHUNK, 4 * i, w)

    def mpoke(self, k, v):
        self.op(OP_MPOKE, k, v)

    def cpoke(self, slot, k, v):
        self.op(OP_CPOKE, slot, k, v)

    def update(self, slot, x, y, via=0):
        self.op(OP_UPDATE, slot, float(x), float(y), via)
        self.op(OP_CDUMP, slot)

    def along(self, slot, a, side, path=0, via=0):
        self.op(OP_ALONG, slot, float(a), float(side), path, via)
        self.op(OP_CDUMP, slot)

    def reset(self, slot, x, y, dist=None):
        if dist is None:
            self.op(OP_CRESET, slot, float(x), float(y))
        else:
            self.op(OP_CRESETD, slot, float(x), float(y), dist)
        self.op(OP_CDUMP, slot)


# ================================================================ the tracks


class Track(object):
    """A path table and a point table, built path by path."""

    def __init__(self):
        self.paths = []
        self.points = []
        self.pos = []           # (x, y) per point, as floats

    def add_path(self, pts, looping, begin_dist=0.0, ratio=1.0,
                 end_dist=None, links=None, dists=None):
        """`pts` a list of (x, y); distances are the running chord length
        times `ratio` from `begin_dist`, unless `dists` gives them. `links`
        maps a local index to a neighbour triple of global indices."""
        given = dists
        num = len(self.paths)
        begin = len(self.points)
        d = begin_dist
        dists = []
        for i, (x, y) in enumerate(pts):
            if i:
                px, py = pts[i - 1]
                d += math.hypot(x - px, y - py) * ratio
            dists.append(d)
        if looping:
            x0, y0 = pts[0]
            xn, yn = pts[-1]
            total = d + math.hypot(x0 - xn, y0 - yn) * ratio
        else:
            total = d
        if end_dist is None:
            end_dist = total
        if given is not None:
            dists = given
        for i, (x, y) in enumerate(pts):
            nb = (links or {}).get(i, (-1, -1, -1))
            self.points.append(point_words(x, y, num, 0, nb, dists[i]))
            self.pos.append((f32(x), f32(y)))
        self.paths.append(path_words(num, looping, begin, begin + len(pts),
                                     len(pts), begin_dist, end_dist, ratio,
                                     pts[0], pts[-1]))
        return begin

    def link(self, idx, nb):
        """Rewrite point `idx`'s neighbour triple."""
        w = self.points[idx]
        x, y = bf(w[0]), bf(w[1])
        num = w[2] & 0xFF
        dist = bf(w[4])
        self.points[idx] = point_words(x, y, num if num < 128 else num - 256,
                                       0, nb, dist)

    def chunk_words(self):
        paths = [w for p in self.paths for w in p]
        points = [w for p in self.points for w in p]
        body = ([0x00034148, 4 * len(paths)] + paths +
                [0x00034149, 4 * len(points)] + points)
        return [0x80034147, 4 * len(body)] + body


def circle(n, r=100.0, cx=0.0, cy=0.0, a0=0.0):
    return [(cx + r * math.cos(a0 + 2 * math.pi * i / n),
             cy + r * math.sin(a0 + 2 * math.pi * i / n)) for i in range(n)]


def road(n, step=40.0):
    return [(step * i, 25.0 * math.sin(0.7 * i)) for i in range(n)]


# ================================================================ the script


CMP_VALS = [0.0, -0.0, 1.0, -1.0, 49.5, 50.0, 50.5, -50.0, -50.5, 0.25, 0.5,
            0.75, -0.5, 99.0, 100.0, 3582.0, 3582.5, 7164.28, -7164.28,
            1e-7, 1e30, -1e30, float("inf")]


def scenario_compare(sc):
    sc.tag("compare")
    for length in (0.0, 1.0, 100.0, 7164.28, -40.0, 3e38):
        sc.mpoke(M_LEN, fb(length))
        for a in CMP_VALS:
            for b in (0.0, 0.5, 50.0, 3582.14, -1.0):
                for kind in (0, 1, 2):
                    sc.op(OP_CMP, kind, a, b)
    sc.mpoke(M_LEN, 0)


def scenario_empty(sc):
    sc.tag("empty manager")
    sc.op(OP_CTOR)
    sc.op(OP_DUMP, 1)
    sc.op(OP_SETUP, 0)
    sc.op(OP_DUMP, 1)
    sc.op(OP_FCP, 1.0, 2.0)
    sc.op(OP_CINIT, 0)
    sc.op(OP_CDUMP, 0)
    garbage(sc, 0)
    sc.update(0, 5.0, -7.0)
    garbage(sc, 0)
    sc.update(0, 500.0, 500.0, via=1)
    garbage(sc, 1)
    sc.op(OP_CINITAT, 1, 12.5, 13.5)
    sc.op(OP_CDUMP, 1)
    garbage(sc, 1)
    sc.along(1, 10.0, 3.0)
    garbage(sc, 1)
    sc.along(1, 10.0, 3.0, via=1)
    garbage(sc, 2)
    sc.op(OP_CINIT, 2)
    sc.op(OP_CDUMP, 2)
    sc.mpoke(M_REV, 1)
    sc.op(OP_UNLOAD, 0)
    sc.op(OP_DUMP, 0)
    sc.op(OP_DTOR)
    sc.op(OP_DUMP, 0)
    sc.op(OP_CTOR)
    sc.op(OP_DUMP, 0)


def garbage(sc, slot):
    """Every field of a coordinate but its point set to something no reset
    writes, so that a reset which forgets a field shows."""
    for k, v in ((C_X, 1.25), (C_Y, -2.5), (C_PARAM, 3.5), (C_RATIO, 0.75),
                 (C_DIST, 81.0), (C_DIRX, -0.6), (C_DIRY, 0.8)):
        sc.cpoke(slot, k, fb(v))
    sc.cpoke(slot, C_CAF, CAF_JUNK)
    sc.cpoke(slot, C_CAFHI, 0x5678)


def ring_walk(sc, slot, t, rnd, steps, radius, wobble, via=0):
    """Round a ring near its points, a few units off the line."""
    for k in range(steps):
        a = 2 * math.pi * k / steps
        r = radius + rnd.uniform(-wobble, wobble)
        sc.update(slot, r * math.cos(a), r * math.sin(a), via)


def scenario_loop(sc, rnd):
    t = Track()
    t.add_path(circle(12, 100.0), 1)
    sc.tag("loop: load")
    sc.tables(t)
    sc.op(OP_LOAD, len(t.points), len(t.paths), 0)
    sc.op(OP_DUMP, 1)

    sc.tag("loop: walk")
    sc.op(OP_CINIT, 0)
    ring_walk(sc, 0, t, rnd, 40, 100.0, 6.0)
    sc.tag("loop: walk backwards")
    for k in range(30, -1, -1):
        a = 2 * math.pi * k / 30
        sc.update(0, 97.0 * math.cos(a), 97.0 * math.sin(a))

    sc.tag("loop: jumps")
    for x, y in ((0.0, 100.0), (0.0, -100.0), (-100.0, 5.0), (-100.0, 5.0),
                 (-99.0, 131.0), (80.0, 60.0), (300.0, 0.0), (0.0, 0.0),
                 (-0.0, -0.0), (1e5, -1e5), (100.0, 0.0)):
        sc.update(0, x, y)

    sc.tag("loop: through the coordinate")
    sc.op(OP_CINITAT, 1, 70.0, 70.0)
    sc.op(OP_CDUMP, 1)
    ring_walk(sc, 1, t, rnd, 16, 104.0, 3.0, via=1)

    sc.tag("loop: reversed")
    sc.mpoke(M_REV, 1)
    sc.op(OP_CINIT, 2)
    ring_walk(sc, 2, t, rnd, 24, 100.0, 4.0)
    sc.mpoke(M_REV, 0)

    sc.tag("loop: stale point and param")
    # A point from the table the coordinate was not given by a search, and
    # a parameter far from it.
    sc.op(OP_CINIT, 3)
    sc.cpoke(3, C_PT, 7)
    sc.cpoke(3, C_X, fb(98.0))
    sc.cpoke(3, C_Y, fb(2.0))
    sc.update(3, 99.0, 3.0)
    sc.cpoke(3, C_PARAM, fb(9.25))
    sc.update(3, 99.0, 4.0)
    sc.cpoke(3, C_PARAM, fb(-30.0))
    sc.update(3, 99.0, 5.0)
    sc.cpoke(3, C_PARAM, fb(1e9))
    sc.update(3, 98.0, 6.0)

    sc.tag("loop: searches")
    for k in range(24):
        a = 2 * math.pi * k / 24
        sc.op(OP_FCP, 90.0 * math.cos(a), 90.0 * math.sin(a))
    # Halfway between points 0 and 1, and the centre: ties.
    x0, y0 = t.pos[0]
    x1, y1 = t.pos[1]
    sc.op(OP_FCP, (x0 + x1) / 2, (y0 + y1) / 2)
    sc.op(OP_FCP, 0.0, 0.0)
    for idx in (0, 1, 5, 10, 11):
        for x, y in ((100.0, 0.0), (0.0, 100.0), (-100.0, 0.0), (0.0, -100.0),
                     (x0, y0), ((x0 + x1) / 2, (y0 + y1) / 2)):
            sc.op(OP_FCAP, x, y, idx)

    sc.tag("loop: init twice")
    sc.op(OP_SETUP, 0)
    sc.op(OP_DUMP, 0)
    sc.op(OP_CLOSE, 0)
    sc.op(OP_DUMP, 0)
    sc.op(OP_CLOSE, 0)
    sc.op(OP_SETUP, 1)
    sc.op(OP_DUMP, 1)
    sc.mpoke(M_REV, 1)
    sc.op(OP_DTOR)
    sc.op(OP_DUMP, 0)
    sc.op(OP_CTOR)
    sc.op(OP_DUMP, 0)
    sc.op(OP_LOAD, len(t.points), len(t.paths), 0)
    sc.op(OP_CINIT, 0)
    sc.update(0, 3.0, 99.0)
    sc.op(OP_UNLOAD, 0)
    sc.op(OP_DUMP, 0)


def scenario_open(sc, rnd):
    t = Track()
    t.add_path(road(10), 0, begin_dist=250.0, ratio=0.75, end_dist=900.0)
    sc.tag("open: load")
    sc.tables(t)
    sc.op(OP_LOAD, len(t.points), len(t.paths), 1)
    sc.op(OP_DUMP, 1)

    sc.tag("open: drive")
    sc.op(OP_CINIT, 0)
    for k in range(-8, 400, 7):
        x = float(k)
        y = 25.0 * math.sin(0.7 * x / 40.0) + rnd.uniform(-5.0, 5.0)
        sc.update(0, x, y)
    sc.tag("open: past the ends")
    for x, y in ((-60.0, 0.0), (-200.0, 30.0), (400.0, 0.0), (420.0, -10.0),
                 (560.0, 40.0), (360.0, 25.0)):
        sc.update(0, x, y)

    sc.tag("open: ends")
    for idx in (0, 1, 8, 9):
        for x, y in ((-10.0, 0.0), (0.0, 0.0), (400.0, 0.0), (330.0, 10.0),
                     (40.0, 10.0)):
            sc.op(OP_FCAP, x, y, idx)

    sc.tag("open: reversed")
    sc.mpoke(M_REV, 1)
    sc.op(OP_CINIT, 1)
    for k in range(0, 380, 19):
        sc.update(1, float(k), 25.0 * math.sin(0.7 * k / 40.0) - 2.0)
    sc.mpoke(M_REV, 0)

    sc.tag("open: along")
    along_walk(sc, 2, [10.0 * i for i in range(1, 11)], 0.0)
    along_grid(sc, 3)
    sc.op(OP_UNLOAD, 1)
    sc.op(OP_DUMP, 0)


def along_walk(sc, slot, alongs, side, path=0, via=0):
    sc.op(OP_CINIT, slot)
    for a in alongs:
        sc.along(slot, a, side, path, via)


def along_grid(sc, slot):
    """CalculateRacerPositions' grid: ten metres at a time to a hundred,
    then two abreast, seventeen apart, three either side."""
    sc.op(OP_CINIT, slot)
    for a in range(10, 101, 10):
        sc.along(slot, float(a), 0.0)
    for i in range(8):
        sc.op(OP_CINIT, slot)
        sc.along(slot, 100.0 + 17.0 * (i // 2), 3.0 if i & 1 else -3.0)


def scenario_linked(sc, rnd):
    # A ring of sixteen, and a chord of six across its top from point 2 to
    # point 6, with links both ways at the ends and along the way.
    t = Track()
    ring = circle(16, 200.0)
    t.add_path(ring, 1)
    ax, ay = ring[2]
    bx, by = ring[6]
    chord = [(ax + (bx - ax) * k / 5.0, ay + (by - ay) * k / 5.0 - 30.0)
             for k in range(6)]
    begin_dist = bf(t.points[2][4])
    t.add_path(chord, 0, begin_dist=begin_dist, ratio=0.9)
    # ring 2 <-> chord 16, ring 6 <-> chord 21, ring 4 -> chord 18/19
    t.link(2, (16, -1, -1))
    t.link(16, (-1, 2, -1))
    t.link(6, (-1, -1, 21))
    t.link(21, (6, -1, -1))
    t.link(4, (18, 19, -1))
    t.link(18, (-1, 4, 3))
    t.link(19, (5, -1, 4))
    sc.tag("linked: load")
    sc.tables(t)
    sc.op(OP_LOAD, len(t.points), len(t.paths), 0)
    sc.op(OP_DUMP, 1)

    sc.tag("linked: ring, then the chord")
    sc.op(OP_CINIT, 0)
    for k in range(0, 5):
        a = 2 * math.pi * k / 16
        sc.update(0, 200.0 * math.cos(a), 200.0 * math.sin(a))
    for x, y in chord:
        for dx in (-8.0, 0.0, 8.0):
            sc.update(0, x + dx, y + rnd.uniform(-4.0, 4.0))
    for k in range(6, 17):
        a = 2 * math.pi * k / 16
        sc.update(0, 199.0 * math.cos(a), 199.0 * math.sin(a))

    sc.tag("linked: chained links")
    # From ring 4, whose first link is chord 18: 18's own links decide.
    sc.op(OP_CINIT, 1)
    sc.cpoke(1, C_PT, 4)
    x4, y4 = t.pos[4]
    sc.cpoke(1, C_X, fb(x4))
    sc.cpoke(1, C_Y, fb(y4))
    for x, y in (t.pos[18], t.pos[19], t.pos[3],
                 ((t.pos[18][0] + t.pos[3][0]) / 2,
                  (t.pos[18][1] + t.pos[3][1]) / 2)):
        sc.cpoke(1, C_PT, 4)
        sc.update(1, x, y)

    sc.tag("linked: along the chord")
    along_walk(sc, 2, [begin_dist + 25.0 * i for i in range(12)], 2.0,
               path=1)
    along_walk(sc, 3, [1.0, 50.0, 400.0, 900.0, 1e4, -50.0], -4.0, path=0)
    along_walk(sc, 3, [30.0, 60.0, 90.0], 1.0, via=1)

    sc.tag("linked: searches")
    for k in range(40):
        sc.op(OP_FCP, rnd.uniform(-220.0, 220.0), rnd.uniform(-220.0, 220.0))
    for idx in (15, 16, 21, 0, 2, 6):
        for k in range(4):
            sc.op(OP_FCAP, rnd.uniform(-220.0, 220.0),
                  rnd.uniform(-220.0, 220.0), idx)
    sc.op(OP_CLOSE, 0)
    sc.op(OP_UNLOAD, 1)


def scenario_along_edges(sc):
    # A short open path whose distances do not start at zero, walked from
    # a fresh coordinate and then from a poked point, in both directions.
    t = Track()
    t.add_path([(0.0, 0.0), (30.0, 0.0), (60.0, 10.0), (90.0, 30.0),
                (120.0, 60.0)], 0, begin_dist=40.0)
    t.add_path([(500.0, 500.0)], 0, begin_dist=7.0)
    sc.tag("along edges: load")
    sc.tables(t)
    sc.op(OP_LOAD, len(t.points), len(t.paths), 0)
    sc.op(OP_DUMP, 1)

    sc.tag("along edges: fresh")
    for a in (0.0, 39.0, 40.0, 41.0, 70.0, 100.0, 130.0, 170.0, 1e6, -5.0):
        along_walk(sc, 0, [a], 1.5)
    sc.tag("along edges: carried")
    # The last point is at 180.1: past it, the image's walk reads a NULL
    # point's distance, so the walks stay short of it.
    along_walk(sc, 1, [45.0, 80.0, 120.0, 160.0, 175.0, 160.0, 120.0, 80.0,
                       45.0, 10.0, 45.0], -2.0)
    sc.tag("along edges: from a poked point")
    last = bf(t.points[4][4])
    for pt in (0, 1, 2, 3, 4):
        for a in (10.0, 40.0, 70.0, 75.0, 140.0, 179.0, last):
            sc.op(OP_CINIT, 2)
            sc.cpoke(2, C_PT, pt)
            sc.along(2, a, 0.5)

    # NumPoints one: the step count reaches zero after the first step and
    # the walk takes a second.
    sc.tag("along edges: one point in the table")
    sc.mpoke(M_NPOINTS, 1)
    for pt in (None, 0):
        for a in (-10.0, 10.0, 35.0, 80.0):
            sc.op(OP_CINIT, 3)
            if pt is not None:
                sc.cpoke(3, C_PT, pt)
            sc.along(3, a, 2.0)
    sc.mpoke(M_NPOINTS, 0)
    sc.tag("along edges: no points counted")
    for a in (-10.0, 10.0, 80.0):
        sc.op(OP_CINIT, 3)
        sc.cpoke(3, C_PT, 3)
        sc.along(3, a, -1.0)
    sc.mpoke(M_NPOINTS, len(t.points))

    # The one-point path on its own: no neighbour either way. Its spline
    # has one point; UpdatePosition's parameter search runs on it.
    sc.tag("along edges: one-point path")
    sc.op(OP_CINIT, 0)
    sc.update(0, 501.0, 499.0)
    sc.update(0, 520.0, 530.0)
    sc.op(OP_FCAP, 500.0, 510.0, 5)
    sc.op(OP_UNLOAD, 0)


def scenario_ties(sc):
    # Integer points, so that equal distances are equal to the bit.
    t = Track()
    t.add_path([(0.0, 0.0), (10.0, 20.0), (20.0, 0.0), (30.0, 20.0),
                (40.0, 0.0)], 0)
    t.add_path([(10.0, -10.0), (60.0, -10.0)], 0, begin_dist=5.0)
    sc.tag("ties")
    sc.tables(t)
    sc.op(OP_LOAD, len(t.points), len(t.paths), 0)
    # (10, 0): points 0 and 2 at ten, and path 1's first at ten too.
    sc.op(OP_FCP, 10.0, 0.0)
    sc.op(OP_FCP, 30.0, 0.0)
    sc.op(OP_FCP, 10.0, -5.0)
    sc.op(OP_FCP, 35.0, -5.0)
    for idx in (1, 2, 3, 0, 4):
        for x, y in ((10.0, 0.0), (5.0, 10.0), (15.0, 10.0), (30.0, 0.0),
                     (25.0, 10.0), (35.0, 10.0), (20.0, 10.0)):
            sc.op(OP_FCAP, x, y, idx)
    sc.op(OP_CINIT, 0)
    for x, y in ((10.0, 0.0), (20.0, 10.0), (30.0, 0.0), (10.0, -10.0),
                 (35.0, -10.0)):
        sc.update(0, x, y)
    sc.op(OP_UNLOAD, 0)


def scenario_links_chain(sc):
    # An open road of three and four one-point paths stacked above its
    # middle, each linked to the next through a different slot: 1's
    # first, 3's second, 4's third, 5's first. 6 sits exactly as far from
    # (100, 90) as 5 does.
    t = Track()
    t.add_path([(0.0, 0.0), (100.0, 0.0), (200.0, 0.0)], 0)
    for y in (50.0, 80.0, 88.0, 92.0):
        t.add_path([(100.0, y)], 0, begin_dist=y)
    t.link(1, (3, -1, -1))
    t.link(3, (-1, 4, -1))
    t.link(4, (-1, -1, 5))
    t.link(5, (6, -1, -1))
    sc.tag("links chain")
    sc.tables(t)
    sc.op(OP_LOAD, len(t.points), len(t.paths), 0)
    sc.op(OP_DUMP, 0)
    for start in (1, 3, 4, 5, 6):
        sc.op(OP_CINIT, 0)
        sc.cpoke(0, C_PT, start)
        x, y = t.pos[start]
        sc.cpoke(0, C_X, fb(x))
        sc.cpoke(0, C_Y, fb(y))
        sc.update(0, 100.0, 90.0)
        sc.update(0, 100.0, 90.0)
    sc.op(OP_CINIT, 1)
    sc.update(1, 100.0, 90.0)
    sc.update(1, 100.0, 1.0)
    sc.update(1, 100.0, 49.0)
    sc.op(OP_UNLOAD, 0)


def scenario_links_best(sc):
    # The link loop compares each link against the nearest so far, and the
    # nearest so far moves when a link wins. From point 1, 90 away, link 0
    # jumps to 3, 5 away. Link 1 is then read from 3 and leads to 4, 20
    # away: nearer than where the search started, but not nearer than 3.
    t = Track()
    t.add_path([(0.0, 0.0), (100.0, 0.0), (200.0, 0.0)], 0)
    t.add_path([(100.0, 95.0)], 0, begin_dist=95.0)
    t.add_path([(100.0, 70.0)], 0, begin_dist=70.0)
    t.link(1, (3, -1, -1))
    t.link(3, (-1, 4, -1))
    sc.tag("links best")
    sc.tables(t)
    sc.op(OP_LOAD, len(t.points), len(t.paths), 0)
    sc.op(OP_CINIT, 0)
    sc.cpoke(0, C_PT, 1)
    sc.cpoke(0, C_X, fb(100.0))
    sc.cpoke(0, C_Y, fb(0.0))
    sc.update(0, 100.0, 90.0)
    sc.op(OP_UNLOAD, 0)

    # Paths but no count: TrackLength is still the first path's
    # EndDistance, because the load sits ahead of the count test.
    sc.tag("no paths counted")
    sc.op(OP_LOAD, len(t.points), 0, 0)
    sc.op(OP_DUMP, 0)
    sc.op(OP_UNLOAD, 0)
    sc.op(OP_DUMP, 0)


def scenario_odd_distances(sc):
    # Distances that are not in order: the walk's tests are the only thing
    # that says which way to go, and each is read as written.
    t = Track()
    t.add_path([(0.0, 0.0), (40.0, 0.0), (80.0, 10.0), (120.0, 0.0),
                (160.0, 0.0)], 0, dists=[100.0, 20.0, 60.0, 50.0, 200.0])
    sc.tag("odd distances")
    sc.tables(t)
    sc.op(OP_LOAD, len(t.points), len(t.paths), 0)
    for pt in (None, 0, 1, 2, 3):
        for a in (10.0, 30.0, 55.0, 70.0, 150.0):
            sc.op(OP_CINIT, 0)
            if pt is not None:
                sc.cpoke(0, C_PT, pt)
            sc.along(0, a, 1.0)
    sc.op(OP_UNLOAD, 0)


def scenario_many_loads(sc):
    # More loads than the port has spline handles: each Close has to give
    # its handle back.
    t = Track()
    t.add_path([(0.0, 0.0), (30.0, 40.0)], 0)
    sc.tag("many loads")
    sc.tables(t)
    for i in range(70):
        sc.op(OP_LOAD, len(t.points), len(t.paths), i & 1)
        if i % 10 == 9:
            sc.op(OP_DUMP, 0)
        sc.op(OP_UNLOAD, i & 1)
    sc.op(OP_LOAD, len(t.points), len(t.paths), 0)
    sc.op(OP_CINIT, 0)
    sc.update(0, 15.0, 20.0)
    sc.op(OP_UNLOAD, 0)


def scenario_zero_length(sc):
    # TrackLength from path 0's EndDistance: zero here, so the ratio is a
    # divide by zero -- the EE's FLT_MAX, and FLT_MAX for 0/0 too.
    t = Track()
    t.add_path(circle(6, 50.0), 1, end_dist=0.0)
    sc.tag("zero length")
    sc.tables(t)
    sc.op(OP_LOAD, len(t.points), len(t.paths), 0)
    sc.op(OP_DUMP, 0)
    sc.op(OP_CINIT, 0)
    for x, y in ((50.0, 0.0), (0.0, 50.0), (-50.0, 1.0), (49.0, -3.0)):
        sc.update(0, x, y)
    sc.mpoke(M_REV, 1)
    sc.update(0, 50.0, 0.0)
    sc.update(0, 0.0, -50.0)
    sc.mpoke(M_REV, 0)
    # No paths counted, but a table to read TrackLength from.
    sc.op(OP_CLOSE, 0)
    sc.mpoke(M_NPATHS, 0)
    sc.mpoke(M_LEN, fb(-1.0))
    sc.op(OP_SETUP, 0)
    sc.op(OP_DUMP, 0)
    sc.op(OP_UNLOAD, 0)


def scenario_loader(sc, rnd):
    t = Track()
    t.add_path(circle(9, 150.0, 20.0, -30.0, 0.3), 1)
    t.add_path(road(5, 50.0), 0, begin_dist=100.0, ratio=1.25)
    ws = t.chunk_words()
    sc.tag("loader: built chunk")
    sc.chunk(ws)
    sc.op(OP_LOADER, 0)
    sc.op(OP_DUMP, 1)
    sc.op(OP_CINIT, 0)
    for k in range(12):
        a = 0.3 + 2 * math.pi * k / 12
        sc.update(0, 20.0 + 148.0 * math.cos(a), -30.0 + 148.0 * math.sin(a))
    sc.op(OP_CHUNK, 0, 0x80034148)
    sc.op(OP_UNLOADER, 0)
    sc.op(OP_DUMP, 0)
    sc.op(OP_CHUNK, 0, 0x80034147)
    sc.op(OP_UNLOADER, 0)
    sc.op(OP_DUMP, 0)

    sc.tag("loader: not ours")
    sc.op(OP_CHUNK, 0, 0x00034147)
    sc.op(OP_LOADER, 1)
    sc.op(OP_DUMP, 0)
    sc.op(OP_CHUNK, 0, 0x80034147)

    sc.tag("loader: through the wrappers")
    sc.op(OP_LOADER, 1)
    sc.op(OP_DUMP, 1)
    sc.op(OP_SETUP, 1)
    sc.op(OP_CINITAT, 1, 60.0, 0.0)
    sc.op(OP_CDUMP, 1)
    sc.along(1, 30.0, 1.0, via=1)
    sc.op(OP_CLOSE, 1)
    sc.op(OP_DUMP, 0)
    sc.op(OP_SETUP, 1)
    sc.op(OP_DUMP, 0)
    sc.op(OP_UNLOADER, 1)
    sc.op(OP_DUMP, 0)

    # Sizes the divisions do not come out even on: a path table of 76
    # bytes (one path and most of another) and a point table of 68 (three
    # points and eight bytes). Word multiples both, as every payload is.
    sc.tag("loader: uneven sizes")
    t2 = Track()
    t2.add_path(road(3, 60.0), 0)
    t2.add_path(road(2, 10.0), 0)
    paths = [w for p in t2.paths for w in p][:19]
    points = [w for p in t2.points for w in p][:17]
    body = [0x00034148, 76] + paths + [0x00034149, 68] + points
    sc.chunk([0x80034147, 4 * len(body)] + body)
    sc.op(OP_LOADER, 0)
    sc.op(OP_DUMP, 1)
    sc.op(OP_UNLOADER, 0)


def scenario_trackb12(sc, rnd):
    if not TRACKB12.exists():
        return
    data = TRACKB12.read_bytes()
    o = TRACKB12_CHUNK
    typ, size = struct.unpack_from("<II", data, o)
    assert typ == 0x80034147, hex(typ)
    ws = list(struct.unpack_from("<%dI" % ((8 + size) // 4), data, o))
    pts = []
    base = o + 8 + 8 + 40 + 8
    for i in range(56):
        x, y = struct.unpack_from("<ff", data, base + 20 * i)
        pts.append((x, y))

    sc.tag("TRACKB12: load")
    sc.chunk(ws)
    sc.op(OP_LOADER, 1)
    sc.op(OP_DUMP, 1)

    sc.tag("TRACKB12: a lap")
    sc.op(OP_CINIT, 0)
    for i in range(56):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % 55]
        for k in range(4):
            f = k / 4.0
            sc.update(0, x0 + (x1 - x0) * f + rnd.uniform(-9.0, 9.0),
                      y0 + (y1 - y0) * f + rnd.uniform(-9.0, 9.0))

    sc.tag("TRACKB12: reversed")
    sc.mpoke(M_REV, 1)
    sc.op(OP_CINIT, 1)
    for i in range(55, -1, -3):
        x, y = pts[i]
        sc.update(1, x + 4.0, y - 4.0, via=1)
    sc.mpoke(M_REV, 0)

    sc.tag("TRACKB12: grid")
    along_grid(sc, 2)
    sc.tag("TRACKB12: far off")
    for x, y in ((0.0, 0.0), (-2000.0, 2000.0), (5000.0, -5000.0),
                 (-800.0, 450.0)):
        sc.update(2, x, y)
    sc.op(OP_UNLOADER, 1)
    sc.op(OP_DUMP, 0)


def scenario_reset(sc, rnd):
    """ResetPosition(pos): the point dropped, then a fresh search."""
    t = Track()
    t.add_path(circle(10, 80.0), 1)
    sc.tag("reset")
    sc.tables(t)
    sc.op(OP_LOAD, len(t.points), len(t.paths), 0)
    sc.op(OP_SETUP, 0)
    sc.op(OP_CINIT, 0)
    sc.update(0, 80.0, 1.0)
    for k in range(12):
        a = 2 * math.pi * (5 * k % 12) / 12
        garbage(sc, 0)
        # A stale point the reset has to drop.
        sc.cpoke(0, C_PT, (3 * k) % 10)
        sc.reset(0, 83.0 * math.cos(a), 78.0 * math.sin(a))
    sc.op(OP_CLOSE, 0)
    sc.op(OP_UNLOAD, 0)
    sc.op(OP_CINIT, 1)
    garbage(sc, 1)
    sc.reset(1, 3.0, 4.0)


def scenario_near(sc, rnd):
    """Retail's weighted search and ResetPosition(pos, dist): a loop and an
    open road whose distances overlap the loop's, reversed, ties, NaN and
    distances past either end."""
    t = Track()
    t.add_path(circle(12, 100.0), 1)
    t.add_path(road(8), 0, begin_dist=30.0, ratio=0.5)
    sc.tag("near: load")
    sc.tables(t)
    sc.op(OP_LOAD, len(t.points), len(t.paths), 0)
    sc.op(OP_SETUP, 0)
    sc.op(OP_DUMP, 0)
    dists = [0.0, 25.0, 52.3, 150.0, 313.0, 600.0, 626.0, -20.0, -700.0,
             1e4, -0.0, float("nan"), float("inf")]

    sc.tag("near: searches")
    for k in range(10):
        a = 2 * math.pi * k / 10
        x, y = 95.0 * math.cos(a), 95.0 * math.sin(a)
        for d in dists:
            sc.op(OP_FCPD, x, y, d)
    for x, y in ((0.0, 0.0), (120.0, 20.0), (40.0, 10.0), (-300.0, 400.0)):
        for d in dists:
            sc.op(OP_FCPD, x, y, d)

    sc.tag("near: reversed")
    sc.mpoke(M_REV, 1)
    for k in range(6):
        a = 2 * math.pi * k / 6
        for d in (0.0, 150.0, 313.0, 500.0, -40.0):
            sc.op(OP_FCPD, 97.0 * math.cos(a), 97.0 * math.sin(a), d)
    # Halfway between two points, where only the distance term decides:
    # at the second's distance the forward search takes the second, and
    # the reversed one, measuring from the other end, the first.
    chord = 2 * 100.0 * math.sin(math.pi / 12)
    for i in (0, 3, 7, 10):
        (x0, y0), (x1, y1) = t.pos[i], t.pos[i + 1]
        for d in (chord * (i + 1), chord * i, 621.0 - chord * i):
            for rev in (1, 0):
                sc.mpoke(M_REV, rev)
                sc.op(OP_FCPD, (x0 + x1) / 2, (y0 + y1) / 2, d)
    sc.mpoke(M_REV, 0)

    sc.tag("near: resets")
    sc.op(OP_CINIT, 0)
    for k in range(16):
        a = 2 * math.pi * (7 * k % 16) / 16
        garbage(sc, 0)
        sc.cpoke(0, C_PT, (5 * k) % len(t.points))
        sc.reset(0, 101.0 * math.cos(a), 99.0 * math.sin(a),
                 dists[k % len(dists)])
    sc.mpoke(M_REV, 1)
    for d in (10.0, 400.0):
        garbage(sc, 0)
        sc.reset(0, -100.0, 3.0, d)
    sc.mpoke(M_REV, 0)
    sc.tag("near: the road")
    for d in (30.0, 60.0, 120.0, 300.0):
        garbage(sc, 0)
        sc.reset(0, 80.0 + rnd.uniform(-5.0, 5.0), rnd.uniform(-5.0, 5.0), d)
    sc.op(OP_CLOSE, 0)
    sc.op(OP_UNLOAD, 0)

    # Integer points and distances, and a length of 100 so that nothing
    # wraps, so that equal scores are equal to the bit. At (20, 0) and 20
    # the first path's points 0 and 1 score 10 + 5 each; at (40, 0) and 60
    # its 1 and 2 and the second path's 1 all score 15.
    t = Track()
    t.add_path([(10.0, 0.0), (30.0, 0.0), (50.0, 0.0)], 0, end_dist=100.0,
               dists=[0.0, 40.0, 80.0])
    t.add_path([(20.0, -15.0), (40.0, 15.0)], 0, dists=[30.0, 60.0])
    sc.tag("near: ties")
    sc.tables(t)
    sc.op(OP_LOAD, len(t.points), len(t.paths), 0)
    sc.op(OP_SETUP, 0)
    for x, y in ((20.0, 0.0), (40.0, 0.0), (20.0, -5.0), (30.0, 0.0),
                 (30.0, 15.0)):
        for d in (20.0, 30.0, 40.0, 60.0, 0.0, 100.0):
            sc.op(OP_FCPD, x, y, d)
    sc.op(OP_CLOSE, 0)
    sc.op(OP_UNLOAD, 0)

    sc.tag("near: empty")
    sc.op(OP_FCPD, 1.0, 2.0, 3.0)
    sc.op(OP_CINIT, 1)
    garbage(sc, 1)
    sc.reset(1, 5.0, 6.0, 7.0)


def script():
    rnd = random.Random(0x7ac4)
    sc = Script()
    scenario_compare(sc)
    scenario_empty(sc)
    scenario_loop(sc, rnd)
    scenario_open(sc, rnd)
    scenario_linked(sc, rnd)
    scenario_along_edges(sc)
    scenario_ties(sc)
    scenario_links_chain(sc)
    scenario_links_best(sc)
    scenario_odd_distances(sc)
    scenario_many_loads(sc)
    scenario_zero_length(sc)
    scenario_loader(sc, rnd)
    scenario_trackb12(sc, rnd)
    scenario_reset(sc, rnd)
    return sc


def retail_script():
    """The same, on retail, with retail's three new functions after it."""
    sc = script()
    scenario_near(sc, random.Random(0x7ac5))
    return sc


# ================================================================ the model


class Model(object):
    def __init__(self, sc, retail=False):
        self.sc = sc
        self.out = []
        e = self.e = retail_model.emu(retail, ieee=True, eediv=True)
        e.stub_bware()
        self.fn = {}
        for k, v in SYM.items():
            try:
                self.fn[k] = e.addr_of(v)
            except MipsError:
                assert retail, v
        if retail:
            self.fn.update(RETAIL_FN)
        self.MGR, self.BASIS = e.data(MGR), e.data(BASIS)
        self.heap = []                  # (addr, span, label)
        self.stale = bytes(8)
        self.stubs()

    def emit(self, s):
        self.out.append(s)

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        regions = [(PATHS, NPATHS * 40, "paths"),
                   (POINTS, NPOINTS * 20, "points"),
                   (CHUNK, CHUNK_W * 4, "chunk"),
                   (self.BASIS, 192, "basis")]
        regions += self.heap
        for base, size, name in regions:
            if base <= a < base + size:
                return name if a == base else "%s+%d" % (name, a - base)
        return "?"

    def stubs(self):
        e = self.e

        def arg(i):
            return e.reg[4 + i] & M32

        def cstr(p):
            end = e.mem.index(b"\0", p)
            return e.mem[p:end].decode("latin-1")

        def malloc(em):
            size = s32(arg(0))
            name = cstr(arg(1))
            span = size + (SLACK if name.endswith("quickspline.cpp") else 0)
            p = e.alloc(span, align=16)
            e.mem[p:p + span] = bytes(span)
            lab = "h%d" % len(self.heap)
            self.heap.append((p, span, lab))
            self.emit("  alloc %s size %d name %s flags %d pool %d"
                      % (lab, size, name, s32(arg(2)), s32(arg(3))))
            return p

        def free(em):
            self.emit("  free %s" % self.label(arg(0)))

        e.stub("bMalloc__FiPCcii", malloc)
        e.stub("__builtin_vec_delete", free)
        e.stub("__builtin_delete", free)

        # The two reads through a NULL point the port does not follow (see
        # trackpath.c): the walk's next->Distance at a path's last point,
        # and the direction from `prev` with no `prev`. On the console they
        # read the kernel's first page; a scenario that gets there is
        # asking about that page, not the port.
        def next_null(em):
            if e.reg[4] & M32 == 0:
                raise AssertionError("scenario reads next->Distance at a "
                                     "path's last point")

        def prev_null(em):
            if e.reg[3] & M32 == 0:
                raise AssertionError("scenario walks a point with neither "
                                     "neighbour")

        e.hook(e.code(0x001f5a68), next_null)
        e.hook(e.code(0x001f5ab8), prev_null)

    # ---- the prints ------------------------------------------------------

    def vec(self, a):
        e = self.e
        return "%08x %08x %08x %08x" % (e.u32(a), e.u32(a + 4),
                                        e.u32(a + 8), e.u32(a + 12))

    def sb(self, a):
        return (self.e.u8(a) ^ 0x80) - 0x80

    def sh(self, a):
        return (self.e.u16(a) ^ 0x8000) - 0x8000

    def dump_spline(self, s):
        e, sb = self.e, self.sb
        maxc = e.u16(s + 24)
        self.emit("    ept %d bt %d max %08x min %08x len %08x dirty %d "
                  "alloc %d minc %d maxc %d n %d buf %s cp %s basis %s"
                  % (s32(e.u32(s)), s32(e.u32(s + 4)), e.u32(s + 8),
                     e.u32(s + 12), e.u32(s + 16), sb(s + 20), sb(s + 21),
                     sb(s + 22), maxc, e.u16(s + 26),
                     self.label(e.u32(s + 28)), self.label(e.u32(s + 32)),
                     self.label(e.u32(s + 36))))
        b = e.u32(s + 28)
        for i in range(min(maxc + 3, MAX_DUMP)):
            self.emit("    b%d %s" % (i, self.vec(b + 16 * i)))
        if self.label(b).startswith("h") and maxc + 3 <= MAX_DUMP:
            self.emit("    slack %s" % self.vec(b + 16 * (maxc + 3)))

    def dump(self, splines):
        e, sb, sh = self.e, self.sb, self.sh
        paths = e.u32(self.MGR + 12)
        npaths = s32(e.u32(self.MGR + 8))
        self.emit("mgr len %08x rev %d npaths %d paths %s npoints %d "
                  "points %s"
                  % (e.u32(self.MGR), s32(e.u32(self.MGR + 4)), npaths,
                     self.label(paths), s32(e.u32(self.MGR + 16)),
                     self.label(e.u32(self.MGR + 20))))
        if paths == 0:
            return
        for i in range(min(npaths, NPATHS)):
            p = paths + 40 * i
            word = e.u32(p + 36)
            self.emit("  path%d num %d loop %d begin %d end %d n %d bd %08x "
                      "ed %08x ratio %08x bp %08x %08x ep %08x %08x spline %s"
                      % (i, sb(p), sb(p + 1), sh(p + 2), sh(p + 4),
                         sh(p + 6), e.u32(p + 8), e.u32(p + 12),
                         e.u32(p + 16), e.u32(p + 20), e.u32(p + 24),
                         e.u32(p + 28), e.u32(p + 32), self.label(word)))
            if splines and word:
                self.dump_spline(word)

    def cdump(self, slot):
        e = self.e
        c = COORD + 40 * slot
        self.emit("c%d pos %08x %08x pt %s param %08x ratio %08x dist %08x "
                  "dir %08x %08x caf %s %08x"
                  % (slot, e.u32(c), e.u32(c + 4), self.label(e.u32(c + 8)),
                     e.u32(c + 12), e.u32(c + 16), e.u32(c + 20),
                     e.u32(c + 24), e.u32(c + 28), self.label(e.u32(c + 32)),
                     e.u32(c + 36)))

    def mpoint(self, idx):
        return (self.e.u32(self.MGR + 20) + 20 * idx) & M32

    def put_pos(self, x, y):
        self.e.put32(POS, x)
        self.e.put32(POS + 4, y)

    # ---- the run ---------------------------------------------------------

    def run(self):
        tag = "?"
        for i, o in enumerate(self.sc.ops):
            if o[0] == OP_TAG:
                tag = self.sc.tags[o[1]]
            try:
                self.step(o)
            except AssertionError as x:
                raise AssertionError("op %d %r in [%s]: %s"
                                     % (i, o, tag, x))
        return self.out

    def step(self, o):
        sc, e, emit, fn = self.sc, self.e, self.emit, self.fn
        MGR = self.MGR
        if True:
            code, a = o[0], o[1:]
            if code == OP_TAG:
                emit("[%s]" % sc.tags[a[0]])
            elif code == OP_PATH:
                for k in range(10):
                    e.put32(PATHS + 40 * a[0] + 4 * k, a[1 + k])
            elif code == OP_POINT:
                for k in range(5):
                    e.put32(POINTS + 20 * a[0] + 4 * k, a[1 + k])
            elif code == OP_CHUNK:
                e.put32(CHUNK + a[0], a[1])
            elif code == OP_LOAD:
                npoints, npaths, wrap = a
                emit("load points %d paths %d" % (npoints, npaths))
                if wrap:
                    e.call(fn["g_load"], POINTS, npoints, PATHS, npaths)
                else:
                    e.call(fn["load"], MGR, POINTS, npoints, PATHS, npaths)
            elif code in (OP_SETUP, OP_CLOSE, OP_UNLOAD):
                name = {OP_SETUP: "init", OP_CLOSE: "close",
                        OP_UNLOAD: "unload"}[code]
                emit(name)
                if a[0]:
                    e.call(fn["g_" + name])
                else:
                    e.call(fn[name], MGR)
            elif code == OP_CTOR:
                emit("ctor")
                e.call(fn["ctor"], MGR)
            elif code == OP_DTOR:
                emit("dtor")
                e.call(fn["dtor"], MGR, 2)
            elif code == OP_LOADER:
                if a[0]:
                    r = e.call(fn["g_loader"], CHUNK)
                else:
                    r = e.call(fn["loader"], MGR, CHUNK)
                emit("loader -> %d" % r)
            elif code == OP_UNLOADER:
                if a[0]:
                    r = e.call(fn["g_unloader"], CHUNK)
                else:
                    r = e.call(fn["unloader"], MGR, CHUNK)
                emit("unloader -> %d" % r)
            elif code == OP_MPOKE:
                k, v = a
                off, kind = MFIELD[k]
                if kind == "paths":
                    v = 0 if s32(v) < 0 else PATHS + v
                elif kind == "points":
                    v = 0 if s32(v) < 0 else POINTS + v
                e.put32(MGR + off, v)
            elif code == OP_DUMP:
                self.dump(a[0])
            elif code == OP_FCP:
                self.put_pos(a[0], a[1])
                r = e.call(fn["fcp"], MGR, POS)
                emit("fcp %08x %08x -> %s" % (a[0] & M32, a[1] & M32,
                                               self.label(r)))
            elif code == OP_FCAP:
                self.put_pos(a[0], a[1])
                r = e.call(fn["fcap"], MGR, POS, self.mpoint(a[2]))
                emit("fcap %08x %08x pt %d -> %s"
                     % (a[0] & M32, a[1] & M32, a[2], self.label(r)))
            elif code == OP_CINIT:
                emit("cinit c%d" % a[0])
                e.call(fn["cctor"], COORD + 40 * a[0])
            elif code == OP_CINITAT:
                slot, x, y = a
                emit("cinit c%d at %08x %08x" % (slot, x & M32, y & M32))
                self.put_pos(x, y)
                e.call(fn["cctor_at"], COORD + 40 * slot, POS)
            elif code == OP_UPDATE:
                slot, x, y, via = a
                emit("update c%d %08x %08x" % (slot, x & M32, y & M32))
                self.put_pos(x, y)
                if via:
                    e.call(fn["cupdate"], COORD + 40 * slot, POS)
                else:
                    e.call(fn["update"], MGR, COORD + 40 * slot, POS)
            elif code == OP_ALONG:
                slot, along, side, path, via = a
                emit("along c%d %08x %08x path %d"
                     % (slot, along & M32, side & M32, 0 if via else path))
                sp = e.reg[29] & M32
                e.mem[sp - STALE:sp - STALE + 8] = self.stale
                e.fpr[12] = along & M32
                e.fpr[13] = side & M32
                if via:
                    e.call(fn["calong"], COORD + 40 * slot)
                else:
                    e.call(fn["along"], MGR, COORD + 40 * slot, path)
                assert e.reg[29] & M32 == sp
                self.stale = bytes(e.mem[sp - STALE:sp - STALE + 8])
            elif code == OP_CPOKE:
                slot, k, v = a
                if k == C_PT:
                    v = 0 if s32(v) < 0 else self.mpoint(v)
                e.put32(COORD + 40 * slot + CFIELD[k], v)
            elif code == OP_CDUMP:
                self.cdump(a[0])
            elif code == OP_FCPD:
                x, y, d = a
                self.put_pos(x, y)
                e.fpr[12] = d & M32
                r = e.call(fn["fcpd"], MGR, POS)
                emit("fcpd %08x %08x %08x -> %s"
                     % (x & M32, y & M32, d & M32, self.label(r)))
            elif code == OP_CRESET:
                slot, x, y = a
                emit("reset c%d %08x %08x" % (slot, x & M32, y & M32))
                self.put_pos(x, y)
                e.call(fn["creset"], COORD + 40 * slot, POS)
            elif code == OP_CRESETD:
                slot, x, y, d = a
                emit("reset c%d %08x %08x near %08x"
                     % (slot, x & M32, y & M32, d & M32))
                self.put_pos(x, y)
                e.fpr[12] = d & M32
                e.call(fn["cresetd"], COORD + 40 * slot, POS)
            elif code == OP_CMP:
                kind, x, y = a
                e.fpr[12] = x & M32
                e.fpr[13] = y & M32
                e.call(fn["cmp%d" % kind], MGR)
                emit("cmp%d %08x %08x -> %08x" % (kind, x & M32, y & M32,
                                                  e.fpr[0]))
            else:
                raise ValueError("op %d" % code)


def model(sc, retail=False):
    return Model(sc, retail).run()


# ================================================================ the build


def build_harness(tmp, name="trackpath_test"):
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

# The weighted search's loop head, its distance term and its test, which
# FindClosestPoint's own lines would otherwise match first.
LOOP = ("        dist = m->TrackLength - dist;\n"
        "    for (i = 0; i < m->NumPaths; i++) {\n"
        "        const TrackPath *path = &m->pPaths[i];\n\n"
        "        for (j = path->BeginPointNumber; j < path->EndPointNumber; "
        "j++) {")
TERM = ("            d += fabsf(trackpath_compare_distances(m, p->Distance, "
        "dist)\n                       * 0.25f);\n")
TEST = TERM + "            if (best == NULL || d < bestd) {"

MUTATIONS = [
    # -- the spline table ---------------------------------------------------
    ("handle-index", TPC, "return Splines[h - 1];",
     "return Splines[h % TRACKPATH_MAX_SPLINES];"),
    ("handle-store", TPC, "path->pQuickSpline = (uint32_t)slot + 1u;",
     "path->pQuickSpline = (uint32_t)slot + 2u;"),
    ("slot-scan", TPC, "if (Splines[k] == NULL)", "if (Splines[k] != NULL)"),
    ("slot-release", TPC,
     "            Splines[path->pQuickSpline - 1] = NULL;\n", ""),
    ("hdr-max-splines", TPH, "#define TRACKPATH_MAX_SPLINES 64",
     "#define TRACKPATH_MAX_SPLINES 1"),
    ("dist2-y", TPC, "return sqrtf(dx * dx + dy * dy);",
     "return sqrtf(dx * dx + dx * dy);"),
    ("dist2-sqrt", TPC, "return sqrtf(dx * dx + dy * dy);",
     "return dx * dx + dy * dy;"),
    # -- construction -------------------------------------------------------
    ("ctor-npaths", TPC, "    m->NumPaths              = 0;\n", ""),
    ("ctor-paths", TPC, "    m->pPaths                = NULL;\n", ""),
    ("ctor-npoints", TPC, "    m->NumPoints             = 0;\n", ""),
    ("ctor-points", TPC, "    m->pPoints               = NULL;\n", ""),
    ("ctor-len", TPC, "    m->TrackLength           = 0.0f;\n", ""),
    ("ctor-rev", TPC, "    m->ReverseTrackDirection = 0;\n", ""),
    ("dtor-close", TPC,
     "void trackpath_manager_dtor(TrackPathManager *m)\n{\n"
     "    trackpath_manager_close(m);",
     "void trackpath_manager_dtor(TrackPathManager *m)\n{\n    (void)m;"),
    # -- Init ---------------------------------------------------------------
    ("setup-len", TPC, "m->pPaths[0].EndDistance : 0.0f;",
     "m->pPaths[0].BeginDistance : 0.0f;"),
    ("setup-len-null", TPC, "m->pPaths != NULL ? m->pPaths[0].EndDistance",
     "m->NumPaths > 0 ? m->pPaths[0].EndDistance"),
    ("setup-paths", TPC,
     "    for (i = 0; i < m->NumPaths; i++) {\n"
     "        TrackPath   *path = &m->pPaths[i];\n"
     "        QuickSpline *s;\n        int          slot, j;",
     "    for (i = 0; i < m->NumPaths - 1; i++) {\n"
     "        TrackPath   *path = &m->pPaths[i];\n"
     "        QuickSpline *s;\n        int          slot, j;"),
    ("setup-skip", TPC,
     "        if (path->pQuickSpline != 0)\n            continue;\n", ""),
    ("setup-loop-type", TPC, "path->Looping != 0 ? QUICKSPLINE_LOOP",
     "path->Looping == 0 ? QUICKSPLINE_LOOP"),
    ("setup-open-type", TPC, ": QUICKSPLINE_EXTRAPOLATED,",
     ": QUICKSPLINE_LINE,"),
    ("setup-basis", TPC, "QUICKSPLINE_OVERHAUSER, path->NumPoints);",
     "QUICKSPLINE_OVERHAUSER + 1, path->NumPoints);"),
    ("setup-ctor-n", TPC, "QUICKSPLINE_OVERHAUSER, path->NumPoints);",
     "QUICKSPLINE_OVERHAUSER, path->NumPoints + 1);"),
    ("setup-size", TPC, "s = bMalloc((int)sizeof(QuickSpline),",
     "s = bMalloc((int)sizeof(QuickSpline) + 8,"),
    ("setup-name", TPC, 'src\\\\trackpath.cpp",\n                    73',
     'src\\\\trackpath.c",\n                    73'),
    ("setup-line", TPC, "                    73, 16);",
     "                    74, 16);"),
    ("setup-pool", TPC, "                    73, 16);",
     "                    73, 0);"),
    ("setup-setn", TPC,
     "quickspline_set_num_control_points(s, path->NumPoints);",
     "quickspline_set_num_control_points(s, path->NumPoints - 1);"),
    ("setup-cp-count", TPC, "for (j = 0; j < path->NumPoints; j++) {",
     "for (j = 1; j < path->NumPoints; j++) {"),
    ("setup-cp-begin", TPC, "&m->pPoints[path->BeginPointNumber + j];",
     "&m->pPoints[j];"),
    ("setup-cp-x", TPC, "cp->x = pt->Position.x;", "cp->x = pt->Position.y;"),
    ("setup-cp-y", TPC, "cp->y = pt->Position.y;", "cp->y = pt->Position.x;"),
    ("setup-cp-z", TPC, "cp->z = 0.0f;", "cp->z = 0.5f;"),
    ("setup-cp-w", TPC, "cp->w = 0.0f;", "cp->w = 0.5f;"),
    ("setup-cp-dirty", TPC,
     "            s->ControlPointsDirty = 1;\n        }\n", "        }\n"),
    ("setup-calibrate", TPC, "quickspline_calibrate_length(s, 16);",
     "quickspline_calibrate_length(s, 15);"),
    # -- Close, Load, Unload ------------------------------------------------
    ("close-flags", TPC, "quickspline_destroy(s, 3);",
     "quickspline_destroy(s, 1);"),
    ("close-zero", TPC,
     "        path->pQuickSpline = 0;\n    }\n}", "    }\n}"),
    ("close-paths", TPC,
     "    for (i = 0; i < m->NumPaths; i++) {\n"
     "        TrackPath   *path = &m->pPaths[i];\n"
     "        QuickSpline *s;\n\n",
     "    for (i = 1; i < m->NumPaths; i++) {\n"
     "        TrackPath   *path = &m->pPaths[i];\n"
     "        QuickSpline *s;\n\n"),
    ("load-npaths", TPC, "    m->NumPaths  = npaths;",
     "    m->NumPaths  = npaths - 1;"),
    ("load-npoints", TPC, "    m->NumPoints = npoints;",
     "    m->NumPoints = npoints - 1;"),
    ("load-setup", TPC,
     "    m->pPoints   = points;\n    trackpath_manager_setup(m);",
     "    m->pPoints   = points;"),
    ("unload-close", TPC,
     "    trackpath_manager_close(m);\n    m->TrackLength = 0.0f;",
     "    m->TrackLength = 0.0f;"),
    ("unload-len", TPC,
     "    m->TrackLength = 0.0f;\n    m->NumPaths    = 0;",
     "    m->NumPaths    = 0;"),
    ("unload-npaths", TPC,
     "    m->NumPaths    = 0;\n    m->pPaths      = NULL;",
     "    m->pPaths      = NULL;"),
    ("unload-paths", TPC,
     "    m->pPaths      = NULL;\n    m->NumPoints   = 0;",
     "    m->NumPoints   = 0;"),
    ("unload-npoints", TPC,
     "    m->NumPoints   = 0;\n    m->pPoints     = NULL;",
     "    m->pPoints     = NULL;"),
    ("unload-points", TPC, "    m->pPoints     = NULL;\n}", "}"),
    ("unload-rev", TPC, "    m->pPoints     = NULL;\n}",
     "    m->pPoints     = NULL;\n    m->ReverseTrackDirection = 0;\n}"),
    # -- the loader ---------------------------------------------------------
    ("loader-type", TPC,
     "    if (bchunk_u32(chunk) != CHUNK_TRACKPATH) return 0;\n\n    first",
     "    first"),
    ("loader-first", TPC, "    first     = chunk + 8;",
     "    first     = chunk + 16;"),
    ("loader-size", TPC, "    pathSize  = bchunk_u32(first + 4);",
     "    pathSize  = bchunk_u32(first + 4) - 4;"),
    ("loader-second", TPC, "    second    = first + 8 + pathSize;",
     "    second    = first + 16 + pathSize;"),
    ("loader-point-size", TPC, "    pointSize = bchunk_u32(second + 4);",
     "    pointSize = bchunk_u32(second + 4) - 20;"),
    ("loader-points", TPC, "(TrackPathPoint *)(uintptr_t)(second + 8),",
     "(TrackPathPoint *)(uintptr_t)(second + 12),"),
    ("loader-points-div", TPC, "(int)(pointSize / 20u),",
     "(int)(pointSize / 40u),"),
    ("loader-paths", TPC, "(TrackPath *)(uintptr_t)(first + 8),",
     "(TrackPath *)(uintptr_t)(first + 12),"),
    ("loader-paths-div", TPC, "(int)(pathSize / 40u));",
     "(int)(pathSize / 20u));"),
    ("loader-ret", TPC,
     "(int)(pathSize / 40u));\n    return 1;",
     "(int)(pathSize / 40u));\n    return 2;"),
    ("unloader-type", TPC,
     "    if (bchunk_u32(chunk) != CHUNK_TRACKPATH) return 0;\n"
     "    trackpath_manager_unload(m);",
     "    trackpath_manager_unload(m);"),
    ("unloader-ret", TPC, "    trackpath_manager_unload(m);\n    return 1;",
     "    trackpath_manager_unload(m);\n    return 2;"),
    ("hdr-chunk-type", TPC, "#define CHUNK_TRACKPATH        0x80034147u",
     "#define CHUNK_TRACKPATH        0x80034148u"),
    # -- FindClosestPoint ---------------------------------------------------
    ("fcp-paths", TPC,
     "    for (i = 0; i < m->NumPaths; i++) {\n        const TrackPath *path",
     "    for (i = 0; i < m->NumPaths - 1; i++) {\n"
     "        const TrackPath *path"),
    ("fcp-begin", TPC,
     "for (j = path->BeginPointNumber; j < path->EndPointNumber; j++) {",
     "for (j = path->BeginPointNumber + 1; j < path->EndPointNumber; "
     "j++) {"),
    ("fcp-end", TPC,
     "for (j = path->BeginPointNumber; j < path->EndPointNumber; j++) {",
     "for (j = path->BeginPointNumber; j < path->EndPointNumber - 1; "
     "j++) {"),
    ("fcp-y", TPC,
     "d = dist2(p->Position.x - pos->x, p->Position.y - pos->y);",
     "d = dist2(p->Position.x - pos->x, p->Position.y - pos->x);"),
    ("fcp-tie", TPC,
     "if (best == NULL || d < bestd) {\n                bestd = d;",
     "if (best == NULL || d <= bestd) {\n                bestd = d;"),
    ("fcp-first", TPC,
     "if (best == NULL || d < bestd) {\n                bestd = d;",
     "if (d < bestd) {\n                bestd = d;"),
    # -- retail's FindClosestPoint(pos, dist) -------------------------------
    ("fcpd-rev", TPC,
     "    if (m->ReverseTrackDirection)\n"
     "        dist = m->TrackLength - dist;\n",
     ""),
    ("fcpd-rev-sign", TPC,
     "        dist = m->TrackLength - dist;\n    for",
     "        dist = dist - m->TrackLength;\n    for"),
    ("fcpd-paths", TPC, LOOP, LOOP.replace("i < m->NumPaths;",
                                          "i < m->NumPaths - 1;")),
    ("fcpd-begin", TPC, LOOP, LOOP.replace("j = path->BeginPointNumber;",
                                          "j = path->BeginPointNumber + 1;")),
    ("fcpd-end", TPC, LOOP, LOOP.replace("j < path->EndPointNumber;",
                                        "j < path->EndPointNumber - 1;")),
    ("fcpd-term", TPC, TERM, ""),
    ("fcpd-quarter", TPC, "                       * 0.25f);",
     "                       * 0.5f);"),
    ("fcpd-abs", TPC,
     "d += fabsf(trackpath_compare_distances(m, p->Distance, dist)",
     "d += (trackpath_compare_distances(m, p->Distance, dist)"),
    ("fcpd-y", TPC, TERM,
     TERM.replace("p->Distance, dist", "p->Distance, p->Position.y")),
    ("fcpd-tie", TPC, TEST, TEST.replace("d < bestd", "d <= bestd")),
    ("fcpd-first", TPC, TEST, TEST.replace("best == NULL || ", "")),
    # -- ResetPosition, and retail's ResetPosition(pos, dist) ---------------
    ("reset-null", TPC,
     "    c->pTrackPoint = NULL;\n"
     "    trackpath_coord_update_position(c, pos);\n}",
     "    trackpath_coord_update_position(c, pos);\n}"),
    ("rnear-null", TPC,
     "    c->pTrackPoint = NULL;\n    p = trackpath_find_closest_point_near",
     "    p = trackpath_find_closest_point_near"),
    ("rnear-seed", TPC,
     "    if (p != NULL)\n"
     "        trackpath_coord_update_position(c, &p->Position);\n",
     ""),
    ("rnear-plain", TPC,
     "p = trackpath_find_closest_point_near(&TheTrackPathManager, pos, dist);",
     "p = trackpath_find_closest_point(&TheTrackPathManager, pos);"),
    ("rnear-pos", TPC,
     "        trackpath_coord_update_position(c, &p->Position);\n"
     "    trackpath_coord_update_position(c, pos);",
     "        trackpath_coord_update_position(c, &p->Position);"),
    # -- FindClosestAdjacentPointOnSamePath ---------------------------------
    ("fcap-path", TPC,
     "const TrackPath *path = &m->pPaths[pt->PathNumber];\n"
     "    int              idx",
     "const TrackPath *path = &m->pPaths[0];\n    int              idx"),
    ("fcap-self", TPC, "    cand[0] = pt;\n", "    cand[0] = pt + 1;\n"),
    ("fcap-begin-test", TPC, "if (idx != path->BeginPointNumber) {",
     "if (idx != path->BeginPointNumber + 1) {"),
    ("fcap-prev", TPC, "cand[n++] = pt - 1;", "cand[n++] = pt;"),
    ("fcap-wrap-loop", TPC,
     "} else if (path->Looping != 0 && path->EndPointNumber - 1 >= 0) {",
     "} else if (path->EndPointNumber - 1 >= 0) {"),
    ("fcap-wrap-prev", TPC,
     "cand[n++] = &m->pPoints[path->EndPointNumber - 1];",
     "cand[n++] = &m->pPoints[path->EndPointNumber - 2];"),
    ("fcap-end-test", TPC, "if (idx != path->EndPointNumber - 1) {",
     "if (idx != path->EndPointNumber - 2) {"),
    ("fcap-next", TPC, "cand[n++] = pt + 1;", "cand[n++] = pt;"),
    ("fcap-wrap-loop2", TPC,
     "} else if (path->Looping != 0 && path->BeginPointNumber >= 0) {",
     "} else if (path->BeginPointNumber >= 0) {"),
    ("fcap-wrap-next", TPC,
     "cand[n++] = &m->pPoints[path->BeginPointNumber];",
     "cand[n++] = &m->pPoints[path->BeginPointNumber + 1];"),
    ("fcap-y", TPC,
     "float d = dist2(pos->x - q->Position.x, pos->y - q->Position.y);",
     "float d = dist2(pos->x - q->Position.x, pos->x - q->Position.y);"),
    ("fcap-tie", TPC,
     "if (best == NULL || d < bestd) {\n            best = q;",
     "if (best == NULL || d <= bestd) {\n            best = q;"),
    ("fcap-order", TPC,
     "    for (k = 0; k < n; k++) {\n        TrackPathPoint *q = cand[k];",
     "    for (k = n - 1; k >= 0; k--) {\n"
     "        TrackPathPoint *q = cand[k];"),
    # -- UpdatePosition(pos) ------------------------------------------------
    ("upd-research", TPC, "|| TRACKPATH_RESEARCH_DISTANCE < dist2(",
     "|| TRACKPATH_RESEARCH_DISTANCE > dist2("),
    ("upd-research-x", TPC, "pos->x - c->Position.x,",
     "pos->x - c->Position.y,"),
    ("upd-research-y", TPC, "pos->y - c->Position.y))",
     "pos->y - c->Position.x))"),
    ("hdr-research", TPH, "#define TRACKPATH_RESEARCH_DISTANCE 128.0f",
     "#define TRACKPATH_RESEARCH_DISTANCE 100.0f"),
    ("upd-none-pos", TPC,
     "    if (pt == NULL) {\n        c->Position = *pos;\n"
     "        c->PathDirection.x = 1.0f;",
     "    if (pt == NULL) {\n        c->PathDirection.x = 1.0f;"),
    ("upd-none-dirx", TPC,
     "        c->PathDirection.x = 1.0f;\n        c->RatioAroundTrack = 0.0f;",
     "        c->RatioAroundTrack = 0.0f;"),
    ("upd-none-ratio", TPC,
     "        c->RatioAroundTrack = 0.0f;\n        c->PathDirection.y = 0.0f;",
     "        c->PathDirection.y = 0.0f;"),
    ("upd-none-diry", TPC,
     "        c->PathDirection.y = 0.0f;\n"
     "        c->DistanceAroundTrack = 0.0f;\n        return;\n    }\n\n    pt =",
     "        c->DistanceAroundTrack = 0.0f;\n        return;\n    }\n\n    pt ="),
    ("upd-none-dist", TPC,
     "        c->DistanceAroundTrack = 0.0f;\n        return;\n    }\n\n    pt =",
     "        return;\n    }\n\n    pt ="),
    ("upd-adjacent", TPC,
     "    pt = trackpath_find_closest_adjacent_point(m, pos, pt);\n", ""),
    ("upd-best", TPC,
     "best = dist2(pos->x - pt->Position.x, pos->y - pt->Position.y);",
     "best = dist2(pos->x - pt->Position.x, 0.0f);"),
    ("upd-links", TPC,
     "    for (k = 0; k < 3; k++) {\n        int16_t",
     "    for (k = 0; k < 2; k++) {\n        int16_t"),
    ("upd-links-from", TPC, "int16_t         nb = pt->NeighbourNumbers[k];",
     "int16_t         nb = c->pTrackPoint != NULL ? "
     "c->pTrackPoint->NeighbourNumbers[k] : pt->NeighbourNumbers[k];"),
    ("upd-link-strict", TPC, "        if (d < best) {\n            pt = q;",
     "        if (d <= best) {\n            pt = q;"),
    ("upd-link-best", TPC, "            pt = q;\n            best = d;\n",
     "            pt = q;\n"),
    ("upd-link-y", TPC,
     "d = dist2(pos->x - q->Position.x, pos->y - q->Position.y);\n"
     "        if (d < best)",
     "d = dist2(pos->x - q->Position.x, pos->y - q->Position.x);\n"
     "        if (d < best)"),
    ("upd-path", TPC,
     "    path = &m->pPaths[pt->PathNumber];\n    if (pt != old) {",
     "    path = &m->pPaths[0];\n    if (pt != old) {"),
    ("upd-old", TPC, "    if (pt != old) {", "    if (pt == old) {"),
    ("upd-store-pt", TPC, "        c->pTrackPoint = pt;\n", ""),
    ("upd-guess-new", TPC,
     "guess = (float)((int)(pt - m->pPoints) - path->BeginPointNumber);",
     "guess = (float)((int)(pt - m->pPoints));"),
    ("upd-guess-same", TPC, "    guess = c->SplineParam;",
     "    guess = 0.0f;"),
    ("hdr-tolerance", TPH, "#define TRACKPATH_PARAM_TOLERANCE 0.05f",
     "#define TRACKPATH_PARAM_TOLERANCE 0.04f"),
    ("upd-fcp-x", TPC, "    p.x = pos->x;\n    p.y = pos->y;",
     "    p.x = pos->y;\n    p.y = pos->y;"),
    ("upd-tangent", TPC, "quickspline_get_point(s, &v, param, 1);",
     "quickspline_get_point(s, &v, param, 2);"),
    ("upd-dir-x", TPC, "    dir.x = v.x;", "    dir.x = v.y;"),
    ("upd-dir-y", TPC, "    dir.y = v.y;", "    dir.y = v.x;"),
    ("upd-w", TPC,
     "quickspline_get_point(s, &v, param, 0);\n    bNormalize2",
     "quickspline_get_point(s, &v, param, 1);\n    bNormalize2"),
    ("upd-normalize", TPC, "    bNormalize2(&dir, &dir);\n", ""),
    ("upd-dist-ratio", TPC,
     "dist = path->BeginDistance + v.w * path->DistanceRatio;",
     "dist = path->BeginDistance + v.w;"),
    ("upd-dist-begin", TPC,
     "dist = path->BeginDistance + v.w * path->DistanceRatio;",
     "dist = v.w * path->DistanceRatio;"),
    ("upd-rev", TPC, "if (m->ReverseTrackDirection != 0) {",
     "if (m->ReverseTrackDirection == 0) {"),
    ("upd-rev-dirx", TPC, "        dir.x = -dir.x;\n", ""),
    ("upd-rev-diry", TPC, "        dir.y = -dir.y;\n", ""),
    ("upd-rev-dist", TPC, "        dist = m->TrackLength - dist;\n    }",
     "        dist = dist - m->TrackLength;\n    }"),
    ("upd-store-param", TPC, "    c->SplineParam = param;\n", ""),
    ("upd-store-pos", TPC,
     "    c->Position = *pos;\n    c->PathDirection = dir;",
     "    c->PathDirection = dir;"),
    ("upd-store-dir", TPC, "    c->PathDirection = dir;\n", ""),
    ("upd-store-dist", TPC, "    c->DistanceAroundTrack = dist;\n", ""),
    ("upd-ratio-eediv", TPC,
     "c->RatioAroundTrack = ee_div(dist, m->TrackLength);",
     "c->RatioAroundTrack = dist / m->TrackLength;"),
    ("upd-ratio-dist", TPC,
     "c->RatioAroundTrack = ee_div(dist, m->TrackLength);",
     "c->RatioAroundTrack = ee_div(v.w, m->TrackLength);"),
    # -- UpdatePosition(along, side, path) ----------------------------------
    ("along-fresh-path", TPC,
     "pt = &m->pPoints[m->pPaths[path].BeginPointNumber];",
     "pt = &m->pPoints[m->pPaths[0].BeginPointNumber];"),
    ("along-reset-ratio", TPC,
     "            c->RatioAroundTrack = 0.0f;\n"
     "            c->PathDirection.x = 1.0f;\n",
     "            c->PathDirection.x = 1.0f;\n"),
    ("along-reset-dirx", TPC,
     "            c->PathDirection.x = 1.0f;\n            c->Position.x = 0.0f;",
     "            c->Position.x = 0.0f;"),
    ("along-reset-x", TPC,
     "            c->Position.x = 0.0f;\n            c->Position.y = 0.0f;",
     "            c->Position.y = 0.0f;"),
    ("along-reset-y", TPC,
     "            c->Position.y = 0.0f;\n            c->PathDirection.y = 0.0f;",
     "            c->PathDirection.y = 0.0f;"),
    ("along-reset-diry", TPC,
     "            c->PathDirection.y = 0.0f;\n"
     "            c->DistanceAroundTrack = 0.0f;",
     "            c->DistanceAroundTrack = 0.0f;"),
    ("along-reset-dist", TPC,
     "            c->DistanceAroundTrack = 0.0f;\n            return;",
     "            return;"),
    ("along-tp", TPC, "    tp = &m->pPaths[pt->PathNumber];",
     "    tp = &m->pPaths[0];"),
    ("along-last", TPC, "? &m->pPoints[tp->EndPointNumber - 1] : NULL;",
     "? &m->pPoints[tp->EndPointNumber - 2] : NULL;"),
    ("along-first", TPC, "? &m->pPoints[tp->BeginPointNumber] : NULL;",
     "? &m->pPoints[tp->BeginPointNumber + 1] : NULL;"),
    ("along-next", TPC, "ptr_below(pt, last) ? pt + 1 : NULL;",
     "ptr_below(pt, last) ? pt + 2 : NULL;"),
    ("along-next-cmp", TPC, "ptr_below(pt, last) ? pt + 1 : NULL;",
     "!ptr_below(last, pt) ? pt + 1 : NULL;"),
    ("along-prev-cmp", TPC, "ptr_below(first, pt) ? pt - 1 : NULL;",
     "!ptr_below(pt, first) ? pt - 1 : NULL;"),
    ("along-back-tie", TPC, "if (along < pt->Distance && prev != NULL) {",
     "if (along <= pt->Distance && prev != NULL) {"),
    ("along-back-prev", TPC, "if (along < pt->Distance && prev != NULL) {",
     "if (along < pt->Distance) {"),
    ("along-fwd-pt", TPC,
     "} else if (pt->Distance < along && next != NULL\n"
     "                   && next->Distance < along) {",
     "} else if (next != NULL\n                   && next->Distance < along) {"),
    ("along-fwd-tie", TPC, "&& next->Distance < along) {",
     "&& next->Distance <= along) {"),
    ("along-fwd-step", TPC, "            pt = next;\n", "            pt = pt;\n"),
    ("along-back-step", TPC, "            pt = prev;\n", "            pt = pt;\n"),
    ("along-left-init", TPC, "for (left = m->NumPoints;;) {",
     "for (left = m->NumPoints + 1;;) {"),
    ("along-left-test", TPC, "        if (left != 0)\n            break;",
     "        if (left == 0)\n            break;"),
    ("along-dir-next-x", TPC,
     "AlongDirection.x = next->Position.x - pt->Position.x;",
     "AlongDirection.x = next->Position.x - pt->Position.y;"),
    ("along-dir-next-y", TPC,
     "AlongDirection.y = next->Position.y - pt->Position.y;",
     "AlongDirection.y = next->Position.y - pt->Position.x;"),
    ("along-dir-prev-x", TPC,
     "AlongDirection.x = pt->Position.x - prev->Position.x;",
     "AlongDirection.x = pt->Position.y - prev->Position.x;"),
    ("along-dir-prev-y", TPC,
     "AlongDirection.y = pt->Position.y - prev->Position.y;",
     "AlongDirection.y = pt->Position.x - prev->Position.y;"),
    ("along-normalize", TPC,
     "            bNormalize2(&AlongDirection, &AlongDirection);\n", ""),
    ("along-fresh-dir", TPC,
     "    // A fresh coordinate starts at path",
     "    AlongDirection.x = 0.0f;\n    AlongDirection.y = 0.0f;\n"
     "    // A fresh coordinate starts at path"),
    ("along-scale", TPC,
     "bScaleAdd2(&p, &pt->Position, &AlongDirection, along);",
     "bScaleAdd2(&p, &pt->Position, &AlongDirection, "
     "along - pt->Distance);"),
    ("along-perp", TPC,
     "    perp.x = AlongDirection.y;\n    perp.y = -AlongDirection.x;",
     "    perp.x = -AlongDirection.y;\n    perp.y = AlongDirection.x;"),
    ("along-side", TPC, "    bScaleAdd2(&p, &p, &perp, side);\n", ""),
    ("along-update", TPC,
     "    bScaleAdd2(&p, &p, &perp, side);\n"
     "    trackpath_manager_update_position(m, c, &p);",
     "    bScaleAdd2(&p, &p, &perp, side);\n    c->Position = p;"),
    # -- the comparisons ----------------------------------------------------
    ("cmp-d", TPC, "float d   = a - b;", "float d   = b - a;"),
    ("cmp-lo", TPC, "if (d < -len * 0.5f) return d + len;",
     "if (d <= -len * 0.5f) return d + len;"),
    ("cmp-lo-half", TPC, "if (d < -len * 0.5f) return d + len;",
     "if (d < -len * 0.25f) return d + len;"),
    ("cmp-lo-add", TPC, "if (d < -len * 0.5f) return d + len;",
     "if (d < -len * 0.5f) return d - len;"),
    ("cmp-hi", TPC, "if (len * 0.5f < d)  return d - len;",
     "if (len * 0.5f <= d)  return d - len;"),
    ("cmp-hi-half", TPC, "if (len * 0.5f < d)  return d - len;",
     "if (len * 0.25f < d)  return d - len;"),
    ("cmp-hi-sub", TPC, "if (len * 0.5f < d)  return d - len;",
     "if (len * 0.5f < d)  return d + len;"),
    ("cmpp-d", TPC,
     "    float d = a - b;\n\n    (void)m;\n    if (d < -50.0f)",
     "    float d = b - a;\n\n    (void)m;\n    if (d < -50.0f)"),
    ("cmpp-lo", TPC, "if (d < -50.0f) return d + 100.0f;",
     "if (d <= -50.0f) return d + 100.0f;"),
    ("cmpp-lo-add", TPC, "if (d < -50.0f) return d + 100.0f;",
     "if (d < -50.0f) return d + 99.0f;"),
    ("cmpp-hi", TPC, "if (50.0f < d)  return d - 100.0f;",
     "if (50.0f <= d)  return d - 100.0f;"),
    ("cmpp-hi-sub", TPC, "if (50.0f < d)  return d - 100.0f;",
     "if (50.0f < d)  return d - 99.0f;"),
    ("cmpr-d", TPC,
     "    float d = a - b;\n\n    (void)m;\n    if (d < -0.5f)",
     "    float d = b - a;\n\n    (void)m;\n    if (d < -0.5f)"),
    ("cmpr-lo", TPC, "if (d < -0.5f) return d + 1.0f;",
     "if (d <= -0.5f) return d + 1.0f;"),
    ("cmpr-lo-add", TPC, "if (d < -0.5f) return d + 1.0f;",
     "if (d < -0.5f) return d + 2.0f;"),
    ("cmpr-hi", TPC, "if (0.5f < d)  return d - 1.0f;",
     "if (0.5f <= d)  return d - 1.0f;"),
    ("cmpr-hi-sub", TPC, "if (0.5f < d)  return d - 1.0f;",
     "if (0.5f < d)  return d - 2.0f;"),
    # -- TrackPathCoordinate ------------------------------------------------
    ("coord-x", TPC, "    c->Position.x          = 0.0f;\n", ""),
    ("coord-y", TPC, "    c->Position.y          = 0.0f;\n", ""),
    ("coord-pt", TPC, "    c->pTrackPoint         = NULL;\n", ""),
    ("coord-param", TPC, "    c->SplineParam         = 0.0f;\n", ""),
    ("coord-ratio", TPC, "    c->RatioAroundTrack    = 0.0f;\n", ""),
    ("coord-dist", TPC,
     "    c->DistanceAroundTrack = 0.0f;\n    c->PathDirection.x     = 1.0f;",
     "    c->PathDirection.x     = 1.0f;"),
    ("coord-dirx", TPC, "    c->PathDirection.x     = 1.0f;\n", ""),
    ("coord-diry", TPC, "    c->PathDirection.y     = 0.0f;\n", ""),
    ("coord-caf", TPC, "    c->pCaffeineObj        = NULL;\n", ""),
    ("coord-caf-high", TPC, "    c->CaffeineObjHigh     = 0;\n", ""),
    ("coord-at-init", TPC,
     "    trackpath_coord_init(c);\n    trackpath_coord_update_position(c, pos);",
     "    trackpath_coord_update_position(c, pos);"),
    ("coord-at-update", TPC,
     "    trackpath_coord_init(c);\n    trackpath_coord_update_position(c, pos);",
     "    trackpath_coord_init(c);"),
    ("coord-update", TPC,
     "    trackpath_manager_update_position(&TheTrackPathManager, c, pos);\n}",
     "}"),
    ("coord-along-path", TPC,
     "                                            side, 0);",
     "                                            side, 1);"),
    # -- the global wrappers ------------------------------------------------
    ("g-init", TPC,
     "void init_track_paths(void)\n{\n"
     "    trackpath_manager_setup(&TheTrackPathManager);",
     "void init_track_paths(void)\n{\n"),
    ("g-close", TPC,
     "void close_track_paths(void)\n{\n"
     "    trackpath_manager_close(&TheTrackPathManager);",
     "void close_track_paths(void)\n{\n"),
    ("g-loader", TPC,
     "    return trackpath_loader(&TheTrackPathManager, chunk);",
     "    (void)chunk;\n    return 1;"),
    ("g-unloader", TPC,
     "    return trackpath_unloader(&TheTrackPathManager, chunk);",
     "    (void)chunk;\n    return 1;"),
    ("g-load", TPC,
     "    trackpath_manager_load(&TheTrackPathManager, points, npoints, "
     "paths,\n                           npaths);",
     "    trackpath_manager_load(&TheTrackPathManager, points, npoints, "
     "paths,\n                           0);"),
    ("g-unload", TPC,
     "void unload_track_paths(void)\n{\n"
     "    trackpath_manager_unload(&TheTrackPathManager);",
     "void unload_track_paths(void)\n{\n"
     "    trackpath_manager_close(&TheTrackPathManager);"),
]

EQUIVALENT = {
    # Init's zero in each control point's w lane. CalibrateLength writes
    # point i's w before it evaluates segment i. The evaluations of segment
    # i do read the w lanes of later points, still holding Init's value,
    # but only through the result's own w, and the arc length sums x, y and
    # z. By the last evaluation every w has been written, including for an
    # EXTRAPOLATED spline, whose MaxParam of 9999999 has the last point
    # start a segment too. So the fixup points left in the buffer come from
    # final values, and the next evaluation redoes them because Calibrate
    # leaves the flag up.
    "setup-cp-w":
        "CalibrateLength writes every w before any evaluation whose output "
        "depends on it",

    # Init's dirty flag. CalibrateLength raises it before every segment's
    # first evaluation and once more, unconditionally, after the loop.
    "setup-cp-dirty":
        "CalibrateLength raises the flag before it evaluates anything and "
        "again at the end",

    # delete with flags 1 rather than 3. QuickSpline's destructor
    # (0x00228200) tests only bit 0 -- `andi v0,s1,0x0001` -- and so does
    # quickspline_destroy. Bit 1 has no reader.
    "close-flags":
        "the QuickSpline destructor reads only bit 0 of its flags",
}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name


def mutate_pass(only=None):
    sc = script()
    base = model(sc)
    rsc = retail_script()
    rbase = model(rsc, retail=True)
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
    rops = Path(opsdir.name) / "rops.bin"
    rops.write_bytes(rsc.encode())
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, ops, out)
        rout = Path(tmp) / "rbase.txt"
        run_harness(exe, rops, rout)
        if (diff(base, out.read_text().splitlines(), quiet=True)
                or diff(rbase, rout.read_text().splitlines(), quiet=True)):
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
                rout = Path(tmp) / "rm.txt"
                if rc == 0:
                    rc = run_harness(exe, rops, rout)
                if rc == pcc.HARNESS_HUNG:
                    print("  %-44s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-44s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = (diff(base, out.read_text().splitlines(), quiet=True)
                     + diff(rbase, rout.read_text().splitlines(),
                            quiet=True))
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
    rsc = retail_script()
    rlines = model(rsc, retail=True)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        ops = Path(tmp) / "ops.bin"
        ops.write_bytes(sc.encode())
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, ops, out)
        harness = out.read_text().splitlines()
        rops = Path(tmp) / "rops.bin"
        rops.write_bytes(rsc.encode())
        rout = Path(tmp) / "rharness.txt"
        rc = rc or run_harness(exe, rops, rout)
        rharness = rout.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)
        d.with_suffix(".rmodel").write_text(NL.join(rlines) + NL)
        d.with_suffix(".rharness").write_text(NL.join(rharness) + NL)

    n = diff(lines, harness)
    print("demo image: %d ops, %d lines, %d differ"
          % (len(sc.ops), len(harness), n))
    rn = diff(rlines, rharness)
    print("retail image: %d ops, %d lines, %d differ"
          % (len(rsc.ops), len(rharness), rn))
    sys.exit(1 if (n or rn or rc) else 0)


if __name__ == "__main__":
    main()
