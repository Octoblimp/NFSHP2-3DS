#!/usr/bin/env python3
"""Cross-check 3DS Files/source/scenery.c against Scenery.obj in the image.

Scenery.obj is 0x0014c3a0 .. 0x0014e734. This checks its data half: the
loader and unloader for the scenery sections and the visible zones, the
three finds, IsPointInPoly and FindVisibleZone, the zones' two index
lookups, Init/CloseVisibleZones, the blink and zone-number accessors,
IsInTable and ToggleIsInTable, CreateFacadeMatrix, the backwards-track
flip, and the static initialiser and destructor. The image is the oracle:
tools/mipsemu.py runs the shipped functions out of NFSHP2.ELF, the harness
(tools/src/scenery_test.c) runs the port, both walk the same script, and
the two transcripts are diffed. No address is printed; the harness's head
has the naming scheme. Floats are compared as bits, with every NaN printed
as the one quiet NaN.

eModel.obj is the renderer's and is not ported: bOMalloc, eModel::Init,
the model's deleting destructor and bFree are stubbed in the model and
defined or seamed in the harness, and each prints its call. Both sides run
eMathInit first, as eInit does at boot: without it eMathIdentityMatrix is
zero on both, and CreateFacadeMatrix's rotation with it.

The script covers:

  * the statics: both lists empty at boot, CurrentZoneNumber's -1, and the
    destructor over lists still holding nodes (each handed to bFree);
  * every one of TRACKB12's 122 sections loaded at the disc's alignment --
    the list order (below 90 at the tail, the rest at the head), the table,
    each header's filled pointers and counts, every kind with its models
    and a CRC over the objects and the tree -- then its 23 visible zones;
    FindSceneryInfo on every first-LOD name and on misses, FindSceneryInstance
    by name on a sample and by section and index on every section and on
    sections not loaded, and FindVisibleZone on every zone's centre and
    corners and on points scattered over the track; then all unloaded in
    a shuffled order;
  * some sections loaded again on a backwards track, and some repacked for
    the three other alignments;
  * made-up sections: sections 0, 89, 90 and 299, the header alone, junk in
    the header's words, children in another order, two kinds chunks, an
    unknown child, a kinds chunk with a remainder, junk model pointers
    under LODs with no name (kept, and destroyed by the unloader), two
    sections with one number, a pad larger than the objects chunk, and
    chunks that are neither kind;
  * the flip on a backwards track and called again, over rotations proper,
    extreme and rounding;
  * IsPointInPoly on squares, triangles, a concave outline, degenerate
    counts, horizontal edges, points on vertices and edges, -0, NaN and
    infinities, and on random polygons over a small grid;
  * FindIndexTo and FindNextFreeIndex to 64 and past it, IsInTable and
    ToggleIsInTable with wrapping, negative counts and values that do not
    fit a short, CreateFacadeMatrix, and the blink and zone accessors.

The model runs with the EE's divide on, and the run fails if any divide
took its divide-by-zero path: the port follows IEEE there, so the script
keeps clear of it.

    python tools/scenery_check.py
    python tools/scenery_check.py --mutate
    python tools/scenery_check.py --dump out/scenery
"""
import argparse
import difflib
import math
import os
import random
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import mipsemu as me
import retail_model

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)
M32 = 0xFFFFFFFF

SOURCES = [
    "tools/src/scenery_test.c",
    "3DS Files/source/scenery.c",
    "3DS Files/source/emath.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/bvector.c",
    "3DS Files/source/race.c",
]

SC = "3DS Files/source/scenery.c"

(OP_TAG, OP_SINIT, OP_SCLOSE, OP_LIST, OP_TABLE, OP_CHUNK, OP_LOAD,
 OP_UNLOAD, OP_DIR, OP_FIND_INFO, OP_FIND_INST_HASH, OP_FIND_INST,
 OP_PIP, OP_FIND_ZONE, OP_ZSET, OP_ZINDEX, OP_ZFREE, OP_INIT_VZ,
 OP_CLOSE_VZ, OP_BLINK, OP_SETZONE, OP_GETZONE, OP_TSET, OP_IS,
 OP_TOGGLE, OP_FACADE, OP_DUMP_INST, OP_FLIP) = range(1, 29)

NCHUNK = 256
NPOLY = 64
TGUARD, TSIZE = 16, 64

CONTAINER = 0x80034100
HEADER, INFO, INSTANCE, TREE = 0x34101, 0x34102, 0x34103, 0x34104
ZONES = 0x34106

DISC_RS = {HEADER: 56, INFO: 40, INSTANCE: 48, TREE: 24}
LETTER = {HEADER: "h", INFO: "i", INSTANCE: "n", TREE: "t"}
ZONE_RS = 288

GP = 0x00328bf0
SSHL = GP - 22576
VZL = GP - 22568
BOUNDARY = GP - 22560
CURZONE = GP - 22584
BLINK = GP - 22544
POOLVAR = GP - 25728
TABLE = 0x002f1018
DIRECTION = 0x0031252c      # TheRaceParameters + 12
POOL = 0x0bad0f00           # eModelSlotPool, only ever compared

RETAIL_BATAN = 0x0025a890         # retail's bATan, which the port follows

SYM = {
    "load": "LoaderScenery__FP6bChunk",
    "unload": "UnloaderScenery__FP6bChunk",
    "find_info": "FindSceneryInfo__FUi",
    "find_inst_hash": "FindSceneryInstance__FUi",
    "find_inst": "FindSceneryInstance__Fii",
    "pip": "IsPointInPoly__FPC8bVector2T0i",
    "find_zone": "FindVisibleZone__FPC8bVector2",
    "zindex": "FindIndexTo__11VisibleZonei",
    "zfree": "FindNextFreeIndex__11VisibleZonei",
    "init_vz": "InitVisibleZones__Fv",
    "close_vz": "CloseVisibleZones__Fv",
    "blink": "HandleJoystickBlinkSection__Fi",
    "getzone": "GetCurrentZoneNumber__Fv",
    "is": "IsInTable__FPsii",
    "toggle": "ToggleIsInTable__FPsiii",
    "facade": "CreateFacadeMatrix__FP8bMatrix4PC8bVector3T1",
    "flip": "FlipObjectsOnBackwardsTrack__20ScenerySectionHeader",
    "sinit": "_GLOBAL_$I$CurrentZoneNumber",
    "sclose": "_GLOBAL_$D$CurrentZoneNumber",
}

EXTRACTED = ROOT / "extracted"
TRACKB12 = EXTRACTED / "TRACKS" / "TRACKB12.BUN"

bits = me.f_to_bits
fbits = me.fbits_to


def s32(x):
    x &= M32
    return x - (1 << 32) if x & 0x80000000 else x


def s16(x):
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


def cdiv(a, b):
    """C's division, truncated toward zero."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def fx(b):
    """Bits, with every NaN as the one quiet NaN."""
    b &= M32
    if (b & 0x7f800000) == 0x7f800000 and (b & 0x007fffff):
        return 0x7fc00000
    return b


def u32at(d, o):
    return struct.unpack_from("<I", d, o)[0]


def align16(a):
    return (a + 15) & ~15


def padded(cid):
    return cid in (HEADER, INSTANCE)


# ------------------------------------------------------------------ disc


def disc_chunks(path):
    """(offset, bytes) of every scenery container and zone chunk."""
    d = path.read_bytes()
    out = []

    def walk(off, end):
        while off + 8 <= end:
            cid, size = struct.unpack_from("<II", d, off)
            if off + 8 + size > end:
                return
            if cid in (CONTAINER, ZONES):
                out.append((off, d[off:off + 8 + size]))
            elif cid & 0x80000000:
                walk(off + 8, off + 8 + size)
            off += 8 + size

    walk(0, len(d))
    return out


def groups(data):
    """The child chunks of a container as (offset, id, size), in order."""
    size = u32at(data, 4)
    o, out = 8, []
    while o < 8 + size:
        cid, csize = struct.unpack_from("<II", data, o)
        out.append((o, cid, csize))
        o += 8 + csize
    return out


def repack(data, mis, disc_mis):
    """A container laid out for misalignment `mis` rather than the disc's:
    the pad before a header or the objects redone for where it now lies.
    The kinds and the tree start at their chunk's payload and have none."""
    out = bytearray(data[:8])
    for o, cid, csize in groups(data):
        pad = 0
        if padded(cid):
            da = disc_mis + o
            pad = align16(da + 8) - (da + 8)
        body = data[o + 8 + pad:o + 8 + csize]
        npad = 0
        if padded(cid):
            na = mis + len(out)
            npad = align16(na + 8) - (na + 8)
        out += struct.pack("<II", cid, npad + len(body)) + bytes(npad) + body
    struct.pack_into("<I", out, 4, len(out) - 8)
    return bytes(out)


def container(children, mis=0):
    """A made-up container for misalignment `mis`: (id, body) children, a
    header or the objects given the pad the image's loader expects, or
    (id, body, pad) to force one."""
    out = bytearray(struct.pack("<II", CONTAINER, 0))
    for ch in children:
        cid, body = ch[0], ch[1]
        if len(ch) > 2:
            pad = ch[2]
        elif padded(cid):
            na = mis + len(out)
            pad = align16(na + 8) - (na + 8)
        else:
            pad = 0
        out += struct.pack("<II", cid, pad + len(body)) + bytes(pad) + body
    struct.pack_into("<I", out, 4, len(out) - 8)
    return bytes(out)


def header(sec, words=None):
    w = [0] * 14
    w[2] = sec
    for i, v in (words or {}).items():
        w[i] = v
    return struct.pack("<14I", *[x & M32 for x in w])


def info(hashes, clip=(0, 0, 0), dummy=0, models=(0, 0, 0),
         facade=(0, 0, 0), dummy2=0, radius=1.0):
    return struct.pack("<3I3hh3I3BBf", *(list(hashes) + list(clip)
                                         + [dummy] + list(models)
                                         + list(facade) + [dummy2, radius]))


def instance(kind, flags=0, box=(0, 0, 0, 0, 0, 0), pos=(0.0, 0.0, 0.0),
             rot=(16384, 0, 0, 0, 16384, 0, 0, 0, 16384), pad=0):
    return struct.pack("<6hhH3f9hH", *(list(box) + [kind, flags]
                                       + list(pos) + list(rot) + [pad]))


def tree_node(box=(0, 0, 0, 0, 0, 0), n=0, codes=(0, 0, 0, 0, 0)):
    return struct.pack("<6hh5h", *(list(box) + [n] + list(codes)))


def zone(number, center, sections, points, links=(0, 0), caffeine=0):
    secs = list(sections) + [0] * (64 - len(sections))
    pts = []
    for p in points:
        pts += list(p)
    pts += [0.0] * (32 - len(pts))
    return struct.pack("<IIiffIi64hi32f", links[0], links[1], number,
                       center[0], center[1], caffeine, len(sections),
                       *(secs + [len(points)] + pts))


def zone_chunk(zones, extra=b""):
    body = b"".join(zones) + extra
    return struct.pack("<II", ZONES, len(body)) + body


# ---------------------------------------------------------------- script


class Script(object):
    def __init__(self):
        self.words = []
        self.tags = []
        self.chunks = 0

    def op(self, code, *args):
        self.words.append(code)
        for a in args:
            if isinstance(a, float):
                self.words.append(bits(a))
            else:
                self.words.append(a & M32)

    def tag(self, name):
        self.tags.append(name)
        self.op(OP_TAG, len(self.tags) - 1)

    def chunk(self, data, mis):
        k = self.chunks
        self.chunks += 1
        assert k < NCHUNK
        n = len(data)
        pad = data + bytes((-n) % 4)
        self.op(OP_CHUNK, k, mis, n,
                *struct.unpack("<%dI" % (len(pad) // 4), pad))
        return k

    def pip(self, pt, pts, n=None):
        n = len(pts) if n is None else n
        ws = []
        for p in pts[:max(n, 0)]:
            ws += [p[0], p[1]]
        self.op(OP_PIP, n, pt[0], pt[1], *[float(x) if not isinstance(x, int)
                                           else x for x in ws])

    def pipw(self, ptw, ptsw):
        """IsPointInPoly on raw bits."""
        ws = []
        for p in ptsw:
            ws += list(p)
        self.op(OP_PIP, len(ptsw), ptw[0], ptw[1], *ws)

    def facade(self, pos, eye):
        self.op(OP_FACADE, *[float(x) if not isinstance(x, int) else x
                             for x in list(pos) + list(eye)])

    def zset(self, num, secs):
        secs = list(secs) + [0] * (64 - len(secs))
        ws = [(secs[i] & 0xFFFF) | ((secs[i + 1] & 0xFFFF) << 16)
              for i in range(0, 64, 2)]
        self.op(OP_ZSET, num, *ws)

    def tset(self, vals):
        n = TGUARD + TSIZE + TGUARD
        vals = list(vals) + [0] * (n - len(vals))
        ws = [(vals[i] & 0xFFFF) | ((vals[i + 1] & 0xFFFF) << 16)
              for i in range(0, n, 2)]
        self.op(OP_TSET, *ws)


def f32(x):
    return fbits(bits(x))


def boot_section(sc):
    sc.tag("boot")
    sc.op(OP_SINIT)
    sc.op(OP_GETZONE)           # -1 before anything sets it
    sc.op(OP_TABLE)


def accessor_section(sc):
    sc.tag("blink and zone number")
    for v in (0, 2, 1, 0, -2, -1, 5, 1, 0x7fffffff, -1, 0x80000001,
              0x10001, -0x10001, 1):
        sc.op(OP_BLINK, v)
    for v in (5, -7, 0, 299, -1):
        sc.op(OP_SETZONE, v)
        sc.op(OP_GETZONE)


def table_section(sc):
    sc.tag("IsInTable and ToggleIsInTable")
    t = [0x5a5a - 0x10000] * TGUARD
    t += [3, -1, 7, 12, -1, 7, -32768, 32767, 0, 5]
    t += [0x1234] * (TSIZE - 10)
    t += [0x5a5a - 0x10000] * TGUARD
    sc.tset(t)
    for n, v in ((0, 3), (-5, 3), (1, 3), (10, 3), (10, 7), (10, -1),
                 (1, -1), (10, 5), (9, 5), (10, -32768), (10, 0x18000),
                 (10, 32767), (10, 0x7fff0000), (10, 0x1234), (64, 0x1234),
                 (10, 99), (64, 99), (10, 0)):
        sc.op(OP_IS, n, v)
    # found: struck out with -1 and the count stays
    for n, mx, v in ((10, 64, 7), (10, 64, 7), (10, 64, 7), (10, 64, -1)):
        sc.op(OP_TOGGLE, n, mx, v)
    sc.tset(t)
    # not found: written at n mod max
    for n, mx, v in ((10, 64, 99), (11, 64, 0x12345), (12, 64, -40000),
                     (64, 64, 44), (70, 64, 45), (10, 4, 46), (7, 3, 47),
                     (0, 1, 48), (-3, 5, 49), (-7, 4, 50), (6, -4, 51),
                     (-6, -4, 52), (9, 10, 53), (11, 10, 53), (12, 10, 53)):
        sc.op(OP_TOGGLE, n, mx, v)
    # a run with the count carried from each answer, as the debug view does
    tab = [0] * (TGUARD + TSIZE + TGUARD)
    sc.tset(tab)
    tab, n = tab[TGUARD:], 0
    for v in (1, 2, 3, 2, 4, 1, 5, 6, 7, 8, 9, 3, -1, 10, 11):
        sc.op(OP_TOGGLE, n, 6, v)
        n = toggle_sim(tab, n, 6, v)


def toggle_sim(tab, n, mx, v):
    for i in range(n):
        if tab[i] == v:
            tab[i] = -1
            return n
    tab[n - cdiv(n, mx) * mx] = s16(v)
    return n + 1


def facade_section(sc, rnd):
    sc.tag("CreateFacadeMatrix")
    cases = [
        ((0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0)),
        ((10.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 0.0)),
        ((0.0, 10.0, 1.0, 0.0), (0.0, 0.0, 0.0, 0.0)),
        ((-10.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 0.0)),
        ((0.0, -10.0, 1.0, 0.0), (0.0, 0.0, 0.0, 0.0)),
        ((5.0, 5.0, 2.0, 0.0), (0.0, 0.0, 7.0, 0.0)),
        ((-0.0, -0.0, -0.0, -0.0), (0.0, 0.0, 0.0, 0.0)),
        ((0.0, -0.0, 3.0, 0.0), (-0.0, 0.0, 3.0, 0.0)),
        ((1234.5, -987.25, 12.0, 99.0), (1200.0, -1000.0, 0.0, 5.0)),
        ((3.0, 4.0, 5.0, 0xdeadbeef), (1.0, 1.0, 1.0, 0x7fc00000)),
        ((1e30, 1e30, 1.0, 0.0), (-1e30, -1e30, 0.0, 0.0)),
        ((0.001, 0.002, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0)),
    ]
    for pos, eye in cases:
        sc.facade(pos, eye)
    for _ in range(40):
        pos = tuple(f32(rnd.uniform(-3000, 3000)) for _ in range(3)) + (0.0,)
        eye = tuple(f32(rnd.uniform(-3000, 3000)) for _ in range(3)) + (0.0,)
        sc.facade(pos, eye)


def pip_section(sc, rnd):
    sc.tag("IsPointInPoly")
    sq = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    sq_pts = [(0.5, 0.5), (1.5, 0.5), (-0.5, 0.5), (0.5, 1.5), (0.5, -0.5),
              (0.0, 0.5), (1.0, 0.5), (0.5, 0.0), (0.5, 1.0), (0.0, 0.0),
              (1.0, 1.0), (1.0, 0.0), (0.0, 1.0), (-0.0, 0.5), (0.5, -0.0),
              (-0.0, -0.0), (0.999999, 0.999999), (1e-7, 1e-7)]
    for p in sq_pts:
        sc.pip(p, sq)
        sc.pip(p, list(reversed(sq)))
    tri = [(0.0, 0.0), (4.0, 0.0), (2.0, 3.0)]
    for p in ((2.0, 1.0), (2.0, 3.0), (2.0, 0.0), (1.0, 1.5), (3.0, 1.5),
              (0.9, 1.5), (3.1, 1.5), (2.0, 2.999), (-1.0, 0.0)):
        sc.pip(p, tri)
    # a U: two prongs and the gap between them
    u = [(0.0, 0.0), (3.0, 0.0), (3.0, 3.0), (2.0, 3.0), (2.0, 1.0),
         (1.0, 1.0), (1.0, 3.0), (0.0, 3.0)]
    for p in ((0.5, 2.0), (1.5, 2.0), (2.5, 2.0), (1.5, 0.5), (1.5, 1.0),
              (1.0, 2.0), (2.0, 2.0), (1.5, 3.0), (0.5, 3.0), (3.5, 1.0)):
        sc.pip(p, u)
    # counts that are not polygons
    sc.pip((0.5, 0.5), sq, 0)
    sc.pip((0.5, 0.5), sq, -1)
    sc.pip((0.5, 0.5), sq, 1)
    sc.pip((0.5, 0.5), sq, 2)
    sc.pip((0.5, 0.5), sq, 3)
    sc.pip((0.25, 0.1), sq, 3)
    # a vertex on the scanline, from above and below
    diamond = [(0.0, 1.0), (1.0, 0.0), (2.0, 1.0), (1.0, 2.0)]
    for p in ((1.0, 1.0), (-1.0, 1.0), (3.0, 1.0), (0.5, 1.0), (1.0, 0.0),
              (1.0, 2.0), (0.9, 0.0), (1.0, -0.0)):
        sc.pip(p, diamond)
    # NaN and infinities
    nan, inf = float("nan"), float("inf")
    for p in ((nan, 0.5), (0.5, nan), (inf, 0.5), (-inf, 0.5),
              (0.5, inf), (0.5, -inf)):
        sc.pip(p, sq)
    for poly in ([(0.0, 0.0), (1.0, nan), (0.0, 1.0)],
                 [(0.0, -inf), (1.0, 0.0), (0.0, inf)],
                 [(-inf, 0.0), (inf, 0.0), (0.0, 1.0)],
                 [(0.0, 0.0), (inf, 1.0), (0.0, 2.0)]):
        for p in ((0.25, 0.5), (0.1, 0.1), (-0.5, 0.5), (5.0, 0.5)):
            sc.pip(p, poly)
    # the image reads the x and y words as they are: a -0 corner
    sc.pipw((bits(0.0), bits(0.0)),
            [(bits(-0.0), bits(-0.0)), (bits(1.0), bits(-0.0)),
             (bits(1.0), bits(1.0)), (bits(-0.0), bits(1.0))])
    # random polygons over a small grid, so corners land on the scanline
    for _ in range(150):
        n = rnd.randint(3, 16)
        pts = [(float(rnd.randint(-4, 4)), float(rnd.randint(-4, 4)))
               for _ in range(n)]
        for _ in range(4):
            if rnd.random() < 0.5:
                p = (float(rnd.randint(-5, 5)), float(rnd.randint(-5, 5)))
            else:
                p = (f32(rnd.uniform(-5, 5)), f32(rnd.uniform(-5, 5)))
            sc.pip(p, pts)
    for _ in range(60):
        n = rnd.randint(3, 16)
        pts = [(f32(rnd.uniform(-1000, 1000)), f32(rnd.uniform(-1000, 1000)))
               for _ in range(n)]
        for _ in range(3):
            sc.pip((f32(rnd.uniform(-1000, 1000)),
                    f32(rnd.uniform(-1000, 1000))), pts)


def zscratch_section(sc):
    sc.tag("FindIndexTo and FindNextFreeIndex")
    sc.zset(5, [4, -1, 9, 4, -1, 12, 13])
    for s in (4, 9, -1, 12, 13, 0, 0x10004, -0x10001):
        sc.op(OP_ZINDEX, s)
    sc.op(OP_ZFREE)
    sc.zset(3, [-1, 5, 6])
    sc.op(OP_ZFREE)
    sc.zset(0, [-1] * 64)
    sc.op(OP_ZINDEX, -1)
    for _ in range(66):
        sc.op(OP_ZFREE)
    sc.zset(64, [7] * 20 + [-1] + [8] * 43)
    sc.op(OP_ZFREE)
    sc.op(OP_ZFREE)
    sc.op(OP_ZINDEX, 8)
    # past the end of the array: the image reads on into the corners
    sc.zset(70, [3] * 64)
    sc.op(OP_ZINDEX, 0xa5a5 - 0x10000)
    sc.op(OP_ZFREE)
    sc.zset(63, [3] * 64)
    sc.op(OP_ZFREE)
    sc.op(OP_ZFREE)
    sc.zset(-3, [-1] * 64)
    sc.op(OP_ZINDEX, -1)
    sc.op(OP_ZFREE)
    sc.op(OP_ZFREE)


def vz_models_section(sc):
    sc.tag("Init and CloseVisibleZones")
    sc.op(OP_CLOSE_VZ)
    sc.op(OP_INIT_VZ)
    sc.op(OP_CLOSE_VZ)
    sc.op(OP_CLOSE_VZ)
    sc.op(OP_INIT_VZ)
    sc.op(OP_INIT_VZ)
    sc.op(OP_CLOSE_VZ)


class Track(object):
    """TRACKB12's scenery, parsed once."""

    def __init__(self):
        self.containers = []    # (offset, data)
        self.zones = None
        for off, data in disc_chunks(TRACKB12):
            if u32at(data, 0) == CONTAINER:
                self.containers.append((off, data))
            else:
                assert self.zones is None
                self.zones = (off, data)

    def infos(self, data, mis):
        """(section, [hash triples], instance count) of a container."""
        sec, hs, ni = None, [], 0
        for o, cid, csize in groups(data):
            if cid == HEADER:
                da = mis + o
                pad = align16(da + 8) - (da + 8)
                sec = s32(u32at(data, o + 8 + pad + 8))
            elif cid == INFO:
                for i in range(csize // 40):
                    hs.append(struct.unpack_from("<3I", data,
                                                 o + 8 + 40 * i))
            elif cid == INSTANCE:
                da = mis + o
                pad = align16(da + 8) - (da + 8)
                ni = (csize - pad) // 48
        return sec, hs, ni

    def zone_records(self):
        data = self.zones[1]
        out = []
        for i in range(u32at(data, 4) // ZONE_RS):
            r = 8 + ZONE_RS * i
            n = s32(u32at(data, r + 156))
            pts = [struct.unpack_from("<ff", data, r + 160 + 8 * j)
                   for j in range(max(0, min(n, 16)))]
            center = struct.unpack_from("<ff", data, r + 12)
            out.append((center, pts))
        return out


def track_section(sc, tr, rnd, quick=False):
    sc.tag("TRACKB12 forward")
    sc.op(OP_DIR, 0)
    ks = []
    for off, data in tr.containers:
        k = sc.chunk(data, off % 16)
        ks.append((k, off % 16, data))
        sc.op(OP_LOAD, k, 1)
    sc.op(OP_TABLE)
    zoff, zdata = tr.zones
    kz = sc.chunk(zdata, zoff % 16)
    sc.op(OP_LOAD, kz, 1)

    sc.tag("TRACKB12 finds")
    seen, order, secs, lod1 = set(), [], [], []
    for k, mis, data in ks:
        sec, hs, ni = tr.infos(data, mis)
        secs.append((sec, ni))
        for h in hs:
            if h[0] not in seen:
                seen.add(h[0])
                order.append(h[0])
            if h[1] and h[1] not in seen:
                lod1.append(h[1])
    names = order[::7] if quick else order
    for h in names:
        sc.op(OP_FIND_INFO, h)
    for h in [0, 0xdeadbeef, 0xffffffff] + lod1[:6]:
        sc.op(OP_FIND_INFO, h)
    for h in rnd.sample(order, 12 if quick else 60):
        sc.op(OP_FIND_INST_HASH, h)
    for h in (0, 0xdeadbeef):
        sc.op(OP_FIND_INST_HASH, h)
    for sec, ni in secs:
        for i in sorted(set((0, max(ni - 1, 0), ni))):
            sc.op(OP_FIND_INST, sec, i)
    for sec in (0, 1, 10, 86, 90, 98, 110, 296, 299):
        sc.op(OP_FIND_INST, sec, 0)

    sc.tag("TRACKB12 zones")
    zr = tr.zone_records()
    for center, pts in zr:
        sc.op(OP_FIND_ZONE, center[0], center[1])
    for center, pts in zr[::(4 if quick else 1)]:
        for p in pts:
            sc.op(OP_FIND_ZONE, p[0], p[1])
        for a, b in zip(pts, pts[1:] + pts[:1]):
            sc.op(OP_FIND_ZONE, f32((a[0] + b[0]) * 0.5),
                  f32((a[1] + b[1]) * 0.5))
    xs = [p[0] for _, pts in zr for p in pts]
    ys = [p[1] for _, pts in zr for p in pts]
    for _ in range(40 if quick else 200):
        sc.op(OP_FIND_ZONE, f32(rnd.uniform(min(xs) - 50, max(xs) + 50)),
              f32(rnd.uniform(min(ys) - 50, max(ys) + 50)))

    sc.tag("TRACKB12 unload")
    sc.op(OP_UNLOAD, kz)
    sc.op(OP_FIND_ZONE, zr[0][0][0], zr[0][0][1])
    order = list(ks)
    rnd.shuffle(order)
    for k, mis, data in order:
        sc.op(OP_UNLOAD, k)
    sc.op(OP_TABLE)
    sc.op(OP_FIND_INFO, names[0])
    sc.op(OP_FIND_INST, secs[0][0], 0)
    return ks


def backwards_section(sc, ks, rnd):
    sc.tag("TRACKB12 backwards")
    sc.op(OP_DIR, 1)
    pick = rnd.sample(ks, 10)
    for k, mis, data in pick:
        sc.op(OP_LOAD, k, 1)
    for k, mis, data in pick:
        sc.op(OP_UNLOAD, k)
    sc.op(OP_DIR, 0)


def repack_section(sc, ks, rnd):
    sc.tag("TRACKB12 repacked")
    at0 = [x for x in ks if x[1] == 0]
    at8 = [x for x in ks if x[1] == 8]
    for (k, mis, data), new in zip(rnd.sample(at0, 3) + rnd.sample(at8, 3),
                                   (4, 8, 12, 0, 4, 12)):
        kn = sc.chunk(repack(data, new, mis), new)
        sc.op(OP_LOAD, kn, 1)
        sc.op(OP_UNLOAD, kn)


def synthetic_section(sc):
    sc.tag("made-up sections")
    H = 0x11110000
    kinds = info((H + 1, 0, 0), clip=(10, 20, 30), dummy=-2,
                 facade=(1, 0, 2), dummy2=7, radius=2.5)
    kinds += info((H + 2, H + 3, 0), clip=(-1, -2, -3), radius=-0.0)
    kinds += info((H + 4, H + 5, H + 6), facade=(255, 1, 0))
    kinds += info((0, 0, 0))
    kinds += info((0, H + 7, 0), radius=float("nan"))
    kinds += info((0x80000001, 0, 0x80000002))
    objs = b"".join(instance(i % 6, flags=[0, 4, 0x400, 0xffff][i % 4],
                             box=(i, -i, 2 * i, 3 * i, -3 * i, 100),
                             pos=(i * 1.5, -i * 2.0, 0.25))
                    for i in range(5))
    tree = tree_node((0, 0, 0, 5, 5, 5), 2, (1, -2, 3, 0, 0))
    tree += tree_node((-1, -1, -1, 1, 1, 1), 5, (0, 1, 2, 3, 4))

    # children are laid out for the alignment they are loaded at
    def load(data, mis, full=1, unload=True):
        if isinstance(data, list):
            data = container(data, mis)
        k = sc.chunk(data, mis)
        sc.op(OP_LOAD, k, full)
        if unload:
            sc.op(OP_UNLOAD, k)
        return k

    # the header alone, at the split and at the table's ends
    ka = load([(HEADER, header(89))], 0, unload=False)
    kb = load([(HEADER, header(90))], 8, unload=False)
    kc = load([(HEADER, header(0))], 0, unload=False)
    kd = load([(HEADER, header(299))], 8, unload=False)
    sc.op(OP_TABLE)
    for k in (kb, ka, kd, kc):
        sc.op(OP_UNLOAD, k)
    # junk in the header's words the loader leaves alone
    load([(HEADER, header(40, {0: 0xfeed0000, 1: 0xfeed0004, 3: 7, 4: -9,
                               11: 0xfeed0010, 12: 3, 13: 0x12345678}))], 0)
    # a full section, then its children in other orders
    full = [(HEADER, header(41)), (INSTANCE, objs), (INFO, kinds),
            (TREE, tree)]
    k = load(full, 0, unload=False)
    for h in (H + 1, H + 2, H + 3, H + 4, 0, H + 7, 0x80000001,
              0x80000002):
        sc.op(OP_FIND_INFO, h)
        sc.op(OP_FIND_INST_HASH, h)
    for i in range(6):
        sc.op(OP_FIND_INST, 41, i)
    sc.op(OP_UNLOAD, k)
    sc.op(OP_FIND_INFO, H + 1)
    load([(HEADER, header(42)), (TREE, tree), (INFO, kinds),
          (INSTANCE, objs)], 0)
    load([(HEADER, header(43)), (INFO, kinds), (INSTANCE, objs),
          (TREE, tree)], 8)
    # two kinds chunks: the second is the one kept, and built
    load([(HEADER, header(44)), (INFO, info((H + 8, H + 9, 0))),
          (INSTANCE, objs[:48]), (INFO, kinds[:80])], 0)
    # an unknown child, and one with a container's bit
    load([(HEADER, header(45)), (0x34105, b"\x01" * 24), (INFO, kinds[:40]),
          (0x80034101, b"\x02" * 8), (TREE, tree)], 0)
    # a kinds chunk with a remainder
    load([(HEADER, header(46)), (INFO, kinds[:80] + b"\x03" * 16),
          (TREE, tree)], 0)
    # junk model pointers under LODs with no name: kept, then destroyed
    load([(HEADER, header(47)),
          (INFO, info((H + 10, 0, 0), models=(0, 0xfeed0020, 0xfeed0024))
           + info((0, 0, 0), models=(0xfeed0028, 0, 0)))], 8)
    # two sections with one number
    k1 = load([(HEADER, header(50)), (INFO, kinds[:40])], 0, unload=False)
    k2 = load([(HEADER, header(50)), (INFO, kinds[40:80])], 8, unload=False)
    sc.op(OP_FIND_INFO, H + 1)
    sc.op(OP_FIND_INFO, H + 2)
    sc.op(OP_UNLOAD, k2)
    sc.op(OP_TABLE)
    sc.op(OP_FIND_INFO, H + 1)
    sc.op(OP_UNLOAD, k1)
    sc.op(OP_TABLE)
    # a pad larger than the objects chunk: the count wraps. The empty
    # child puts the objects' payload 8 short of a line.
    load([(HEADER, header(51)), (0x34105, b""), (INSTANCE, b"", 0),
          (INFO, kinds[:40])], 0)
    load([(HEADER, header(52)), (0x34105, b""), (INSTANCE, b"\x04" * 4, 0),
          (0x34105, b"\x00" * 4), (INFO, kinds[:40])], 0)
    # a header with the disc's pad of 8, and one with a pad the loader
    # does not expect: it reads the header from the pad's start
    load([(HEADER, header(53)), (INFO, kinds[:40])], 8)
    load([(HEADER, header(54), 8), (INFO, kinds[:40])], 0)
    # neither kind of chunk
    for cid in (0x80034101, 0x00034100, 0x80034106, 0x34107, 0):
        body = b"\x05" * 16
        load(struct.pack("<II", cid, len(body)) + body, 0)
    # zone chunks: empty, and with a remainder
    load(zone_chunk([]), 0)
    zs = [zone(i, (float(i), 0.0), [i, i + 1], [(0.0, 0.0), (1.0, 0.0),
                                                 (1.0, 1.0)])
          for i in range(2)]
    load(zone_chunk(zs, b"\x06" * 100), 4)


def synthetic_zones_section(sc):
    sc.tag("made-up zones")
    sq = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    big = [(-5.0, -5.0), (20.0, -5.0), (20.0, 20.0), (-5.0, 20.0)]
    tri = [(0.0, 0.0), (30.0, 0.0), (15.0, 30.0)]
    zs = [zone(10, (5.0, 5.0), [1, 2, 3], sq, links=(0xfeed0100, 0),
               caffeine=0xfeed0104),
          zone(11, (7.0, 7.0), [4], big),
          zone(12, (0.0, 0.0), [], []),
          zone(13, (15.0, 10.0), list(range(64)), tri)]
    k = sc.chunk(zone_chunk(zs), 12)
    sc.op(OP_LOAD, k, 1)
    for p in ((5.0, 5.0), (15.0, 15.0), (5.0, 5.0), (25.0, 5.0),
              (-4.0, -4.0), (100.0, 100.0), (15.0, 15.0), (0.0, 0.0),
              (10.0, 10.0), (5.0, 5.0), (20.0, 5.0)):
        sc.op(OP_FIND_ZONE, p[0], p[1])
    k2 = sc.chunk(zone_chunk([zone(20, (1.0, 1.0), [9], sq)]), 0)
    sc.op(OP_LOAD, k2, 1)
    sc.op(OP_FIND_ZONE, 5.0, 5.0)
    sc.op(OP_UNLOAD, k)
    sc.op(OP_FIND_ZONE, 5.0, 5.0)
    sc.op(OP_UNLOAD, k2)
    sc.op(OP_FIND_ZONE, 5.0, 5.0)


def flip_section(sc):
    sc.tag("the backwards-track flip")
    rots = [
        (16384, 0, 0, 0, 16384, 0, 0, 0, 16384),
        (0, 16384, 0, -16384, 0, 0, 0, 0, 16384),
        (11585, 11585, 0, -11585, 11585, 0, 0, 0, 16384),
        (-32768, 32767, 1, -1, 3, -3, 12345, -12345, 0),
        (16383, 1, 2, 3, 16383, 5, 7, 11, 16383),
        (1, 1, 1, 1, 1, 1, 1, 1, 1),
        (-1, -1, -1, -1, -1, -1, -1, -1, -1),
        (32767, 32767, 32767, -32768, -32768, -32768, 0, 0, 0),
        (9459, -13377, 2, 13377, 9459, -2, 5, 7, 16380),
    ]
    objs = b""
    for i, r in enumerate(rots):
        for flags in (0x400, 0x0, 0x7fff, 0x8400):
            objs += instance(i % 2, flags=flags, box=(i, i, i, -i, -i, -i),
                             pos=(i * 3.25, -i * 1.5, 100.0 + i), rot=r,
                             pad=0xa000 + i)
    kinds = info((0x22220001, 0, 0)) + info((0x22220002, 0x22220003, 0))
    data = container([(HEADER, header(60)), (INSTANCE, objs),
                      (INFO, kinds)])
    k = sc.chunk(data, 0)
    j = [cid for o, cid, _ in groups(data)].index(INSTANCE)
    sc.op(OP_DIR, 1)
    sc.op(OP_LOAD, k, 1)
    sc.op(OP_DUMP_INST, k, j)
    sc.op(OP_FLIP, k, 0)
    sc.op(OP_DUMP_INST, k, j)
    sc.op(OP_UNLOAD, k)
    sc.op(OP_DIR, 0)
    sc.op(OP_LOAD, k, 0)
    sc.op(OP_DUMP_INST, k, j)
    sc.op(OP_UNLOAD, k)
    # a direction that is neither
    sc.op(OP_DIR, 2)
    sc.op(OP_LOAD, k, 0)
    sc.op(OP_DUMP_INST, k, j)
    sc.op(OP_UNLOAD, k)
    sc.op(OP_DIR, 0)


def close_section(sc):
    sc.tag("the static destructor")
    ka = sc.chunk(container([(HEADER, header(70)),
                             (INFO, info((0x33330001, 0, 0)))]), 0)
    kb = sc.chunk(container([(HEADER, header(170))], 8), 8)
    kz = sc.chunk(zone_chunk([zone(i, (0.0, 0.0), [], [])
                              for i in range(3)]), 0)
    for k in (ka, kb, kz):
        sc.op(OP_LOAD, k, 0)
    sc.op(OP_SCLOSE)
    sc.op(OP_SCLOSE)
    sc.op(OP_SINIT)
    sc.op(OP_LIST)


def script(quick=False):
    sc = Script()
    rnd = random.Random(0x5ce7e)
    tr = Track()
    boot_section(sc)
    accessor_section(sc)
    table_section(sc)
    facade_section(sc, rnd)
    pip_section(sc, rnd)
    zscratch_section(sc)
    vz_models_section(sc)
    ks = track_section(sc, tr, rnd, quick)
    backwards_section(sc, ks, rnd)
    repack_section(sc, ks, rnd)
    synthetic_section(sc)
    synthetic_zones_section(sc)
    flip_section(sc)
    close_section(sc)
    return sc


# ---------------------------------------------------------------- model


class ChunkRec(object):
    pass


class Model(object):
    def __init__(self, sc):
        self.sc = sc
        self.out = []
        e = self.e = me.Emu(ieee=True, eediv=True)
        e.stub_bware()
        # The port's bATan is retail's (0x0025a890), which leaves the
        # argument at 0 below a squared length of 1e-4; the demo's has no
        # such floor. CreateFacadeMatrix is the same on both discs, so the
        # demo's runs, and the bATan under it runs on retail's image.
        ret = retail_model.RetailEmu(ieee=True, eediv=True)

        def batan(em):
            ret.fpr[12] = em.fpr[12]
            ret.fpr[13] = em.fpr[13]
            return ret.call(RETAIL_BATAN, limit=100000)

        e.stub("bATan__Fff", batan)
        # eInit's, before any facade: the identity CreateFacadeMatrix turns
        e.call("eMathInit__Fv")
        self.fn = {k: e.addr_of(v) for k, v in SYM.items()}
        self.chunks = [None] * NCHUNK
        self.models = []
        self.zs = e.alloc(ZONE_RS + 16, 16)
        e.write(self.zs, b"\xa5" * ZONE_RS)
        self.tbuf = e.alloc(2 * (TGUARD + TSIZE + TGUARD), 16)
        self.poly = e.alloc(8 * NPOLY, 16)
        self.pt = e.alloc(16, 16)
        self.pos = e.alloc(16, 16)
        self.eye = e.alloc(16, 16)
        self.m = e.alloc(64, 16)
        self.w32(POOLVAR, POOL)
        emit = self.emit

        def omalloc(em):
            pool = em.reg[4] & M32
            p = em.alloc(32, 16)
            em.write(p, b"\xa5" * 24)
            if pool == POOL:
                emit("  omalloc #%d pool" % len(self.models))
            else:
                emit("  omalloc #%d pool %s" % (len(self.models),
                                                 self.name(pool)))
            self.models.append(p)
            return p

        def init(em):
            m, h = em.reg[4] & M32, em.reg[5] & M32
            emit("  init %s hash %08x name %08x solid %08x"
                 % (self.name(m), h, em.u32(m + 8), em.u32(m + 12)))
            return 0

        def destroy(em):
            emit("  ~model %s %d" % (self.name(em.reg[4] & M32),
                                     s32(em.reg[5])))
            return 0

        def free(em):
            emit("  free %s" % self.name(em.reg[4] & M32))
            return 0

        e.stub("bOMalloc__FP8SlotPool", omalloc)
        e.stub("Init__6eModelUi", init)
        e.stub("_$_6eModel", destroy)
        e.stub("bFree__FPv", free)

    def w32(self, a, v):
        self.e.write(a, struct.pack("<I", v & M32))

    def emit(self, line):
        self.out.append(line)

    def call(self, name, *args):
        # A 32-bit value lives in a register sign-extended, and the image
        # compares whole registers.
        return s32(self.e.call(self.fn[name], *[s32(a) for a in args]))

    # ---- naming

    def name(self, p):
        p &= M32
        if p == 0:
            return "null"
        if p == SSHL:
            return "S"
        if p == VZL:
            return "Z"
        if p == self.zs:
            return "zs"
        if p in self.models:
            return "#%d" % self.models.index(p)
        for k, ck in enumerate(self.chunks):
            if ck is None:
                continue
            if ck.zones:
                base = ck.chunk + 8
                if base <= p <= base + max(ck.nzones, 0) * ZONE_RS:
                    idx, r = divmod(p - base, ZONE_RS)
                    return ("z%d[%d]+%d" % (k, idx, r) if r
                            else "z%d[%d]" % (k, idx))
                continue
            for j, ch in enumerate(ck.child):
                if ch.letter == "c":
                    continue
                if ch.base <= p <= ch.base + max(ch.nrec, 0) * ch.rs:
                    idx, r = divmod(p - ch.base, ch.rs)
                    if ch.letter == "h" and idx == 0 and r == 0:
                        return "h%d.%d" % (k, j)
                    if r:
                        return "%s%d.%d[%d]+%d" % (ch.letter, k, j, idx, r)
                    return "%s%d.%d[%d]" % (ch.letter, k, j, idx)
            for j, ch in enumerate(ck.child):
                if ch.c <= p < ch.c + 8 + ch.size:
                    return "c%d.%d%+d" % (k, j, p - (ch.c + 8))
        return "?%08x" % p

    # ---- chunks

    def put_chunk(self, k, data, mis):
        e = self.e
        ck = ChunkRec()
        base = e.alloc(len(data) + 48, 16) + mis
        e.write(base, data)
        ck.chunk = base
        ck.id = u32at(data, 0)
        ck.size = u32at(data, 4)
        ck.zones = ck.id == ZONES
        ck.nzones = ck.size // ZONE_RS if ck.zones else 0
        ck.child = []
        if ck.id == CONTAINER:
            for o, cid, csize in groups(data):
                ch = ChunkRec()
                ch.id, ch.size = cid, csize
                ch.c = base + o
                pad = 0
                if padded(cid):
                    pad = align16(ch.c + 8) - (ch.c + 8)
                ch.base = ch.c + 8 + pad
                ch.letter = LETTER.get(cid, "c")
                ch.rs = DISC_RS.get(cid, 1)
                if cid == HEADER:
                    ch.nrec = 1
                elif cid == INSTANCE:
                    ch.nrec = cdiv(csize - pad, 48)
                else:
                    ch.nrec = csize // ch.rs
                ck.child.append(ch)
        self.chunks[k] = ck

    # ---- dumps

    def dump_list(self, label, head):
        u = self.e.u32
        parts = ["  %s:" % label]
        n, prev, i = u(head), head, 0
        while n != head and i < 1000:
            parts.append(" %s" % self.name(n))
            if u(n + 4) != prev:
                parts.append("<%s" % self.name(u(n + 4)))
            prev = n
            n = u(n)
            i += 1
        if i == 1000:
            parts.append(" ...")
        elif u(head + 4) != prev:
            parts.append(" tail %s" % self.name(u(head + 4)))
        self.emit("".join(parts))

    def dump_lists(self):
        self.dump_list("S", SSHL)
        self.dump_list("Z", VZL)

    def dump_header(self, k, j):
        u, n = self.e.u32, self.name
        b = self.chunks[k].child[j].base
        self.emit("  h%d.%d next %s prev %s sec %d polys %d %d info %s %d "
                  "inst %s %d tree %s %d group %s %d views %08x"
                  % (k, j, n(u(b)), n(u(b + 4)), s32(u(b + 8)),
                     s32(u(b + 12)), s32(u(b + 16)), n(u(b + 20)),
                     s32(u(b + 24)), n(u(b + 28)), s32(u(b + 32)),
                     n(u(b + 36)), s32(u(b + 40)), n(u(b + 44)),
                     s32(u(b + 48)), u(b + 52)))

    def dump_info(self, k, j):
        e, n = self.e, self.name
        ch = self.chunks[k].child[j]
        for i in range(ch.nrec):
            r = bytes(e.mem[ch.base + 40 * i:ch.base + 40 * i + 40])
            h = struct.unpack_from("<3I", r, 0)
            clip = struct.unpack_from("<4h", r, 12)
            m = struct.unpack_from("<3I", r, 20)
            self.emit("  i%d.%d[%d] hash %08x %08x %08x clip %d %d %d %d "
                      "models %s %s %s facade %d %d %d %d radius %08x"
                      % ((k, j, i) + h + clip + (n(m[0]), n(m[1]), n(m[2]))
                         + tuple(r[32:36]) + (fx(u32at(r, 36)),)))

    def dump_crc(self, k, j):
        ch = self.chunks[k].child[j]
        nr = max(ch.nrec, 0)
        self.emit("  %s%d.%d %d crc %08x"
                  % (ch.letter, k, j, ch.nrec,
                     zlib.crc32(bytes(self.e.mem[ch.base:ch.base
                                                 + nr * ch.rs]))))

    def dump_instances(self, k, j):
        ch = self.chunks[k].child[j]
        for i in range(ch.nrec):
            r = bytes(self.e.mem[ch.base + 48 * i:ch.base + 48 * i + 48])
            v = struct.unpack("<6hhH3I9hH", r)
            self.emit("  n%d.%d[%d] box %d %d %d %d %d %d kind %d flags %04x "
                      "pos %08x %08x %08x rot %s pad %04x"
                      % ((k, j, i) + v[0:8] + (fx(v[8]), fx(v[9]),
                                               fx(v[10]),
                                               " ".join("%d" % x
                                                        for x in v[11:20]),
                                               v[20])))

    def dump_zones(self, k):
        u, n = self.e.u32, self.name
        ck = self.chunks[k]
        for i in range(ck.nzones):
            z = ck.chunk + 8 + ZONE_RS * i
            self.emit("  z%d[%d] next %s prev %s zone %d caffeine %s"
                      % (k, i, n(u(z)), n(u(z + 4)), s32(u(z + 8)),
                         n(u(z + 20))))

    def dump_table_for(self, k):
        u = self.e.u32
        for ch in self.chunks[k].child:
            if ch.letter == "h":
                s = s32(u(ch.base + 8))
                if 0 <= s < 300:
                    self.emit("  table[%d] %s"
                              % (s, self.name(u(TABLE + 4 * s))))

    def dump_table(self):
        u = self.e.u32
        self.emit("  table:" + "".join(
            " %d=%s" % (s, self.name(u(TABLE + 4 * s)))
            for s in range(300) if u(TABLE + 4 * s)))

    def dump_chunk(self, k, full):
        ck = self.chunks[k]
        self.dump_lists()
        if ck.zones:
            self.dump_zones(k)
            return
        if ck.id != CONTAINER:
            return
        self.dump_table_for(k)
        for j, ch in enumerate(ck.child):
            if ch.letter == "h":
                self.dump_header(k, j)
            elif ch.letter == "i" and full:
                self.dump_info(k, j)
            elif ch.letter in "nt" and full:
                self.dump_crc(k, j)

    def dump_zone(self, label, z):
        u = self.e.u32
        secs = struct.unpack("<64h", bytes(self.e.mem[z + 28:z + 156]))
        self.emit("  %s num %d:%s" % (label, s32(u(z + 24)),
                                      "".join(" %d" % x for x in secs)))

    def dump_tbuf(self):
        n = TGUARD + TSIZE + TGUARD
        vals = struct.unpack("<%dh" % n,
                             bytes(self.e.mem[self.tbuf:self.tbuf + 2 * n]))
        self.emit("  tbuf" + "".join(" %d" % x for x in vals))

    # ---- the run

    def run(self):
        e, w, emit = self.e, self.sc.words, self.emit
        i = 0

        def arg():
            nonlocal i
            i += 1
            return w[i - 1]

        def args(n):
            nonlocal i
            i += n
            return w[i - n:i]

        while i < len(w):
            code = arg()
            if code == OP_TAG:
                emit("[%d]" % arg())
            elif code == OP_SINIT:
                self.call("sinit")
                emit("static init")
                self.dump_lists()
            elif code == OP_SCLOSE:
                emit("static close")
                self.call("sclose")
                self.dump_lists()
            elif code == OP_LIST:
                emit("list")
                self.dump_lists()
            elif code == OP_TABLE:
                emit("table")
                self.dump_table()
            elif code == OP_CHUNK:
                k, mis, n = arg(), arg(), arg()
                ws = args((n + 3) // 4)
                data = struct.pack("<%dI" % len(ws), *ws)[:n]
                self.put_chunk(k, data, mis)
                emit("chunk %d mis %d" % (k, mis))
            elif code == OP_LOAD:
                k, full = arg(), arg()
                r = self.call("load", self.chunks[k].chunk)
                emit("load %d -> %d" % (k, r))
                self.dump_chunk(k, full)
            elif code == OP_UNLOAD:
                k = arg()
                r = self.call("unload", self.chunks[k].chunk)
                emit("unload %d -> %d" % (k, r))
                self.dump_chunk(k, 0)
            elif code == OP_DIR:
                d = arg()
                self.w32(DIRECTION, d)
                emit("direction %d" % s32(d))
            elif code == OP_FIND_INFO:
                h = arg()
                emit("find info %08x -> %s"
                     % (h, self.name(self.call("find_info", h))))
            elif code == OP_FIND_INST_HASH:
                h = arg()
                emit("find instance %08x -> %s"
                     % (h, self.name(self.call("find_inst_hash", h))))
            elif code == OP_FIND_INST:
                s, j = arg(), arg()
                emit("find instance %d %d -> %s"
                     % (s32(s), s32(j),
                        self.name(self.call("find_inst", s, j))))
            elif code == OP_PIP:
                n = s32(arg())
                x, y = arg(), arg()
                pts = args(2 * max(n, 0))
                e.write(self.pt, struct.pack("<II", x, y))
                if pts:
                    e.write(self.poly, struct.pack("<%dI" % len(pts), *pts))
                emit("pip %d %08x %08x -> %d"
                     % (n, x, y, self.call("pip", self.pt, self.poly, n)))
            elif code == OP_FIND_ZONE:
                x, y = arg(), arg()
                e.write(self.pt, struct.pack("<II", x, y))
                emit("find zone %08x %08x -> %s"
                     % (x, y, self.name(self.call("find_zone", self.pt))))
                self.dump_list("Z", VZL)
            elif code == OP_ZSET:
                self.w32(self.zs + 24, arg())
                e.write(self.zs + 28, struct.pack("<32I", *args(32)))
                self.dump_zone("zs", self.zs)
            elif code == OP_ZINDEX:
                s = arg()
                emit("zone index %d -> %d"
                     % (s32(s), self.call("zindex", self.zs, s)))
            elif code == OP_ZFREE:
                r = self.call("zfree", self.zs)
                emit("zone free -> %d num %d"
                     % (r, s32(e.u32(self.zs + 24))))
            elif code == OP_INIT_VZ:
                emit("init visible zones")
                self.call("init_vz")
                emit("  boundary %s" % self.name(e.u32(BOUNDARY)))
            elif code == OP_CLOSE_VZ:
                emit("close visible zones")
                self.call("close_vz")
                emit("  boundary %s" % self.name(e.u32(BOUNDARY)))
            elif code == OP_BLINK:
                s = arg()
                self.call("blink", s)
                emit("blink %d -> %d" % (s32(s), s32(e.u32(BLINK))))
            elif code == OP_SETZONE:
                self.w32(CURZONE, arg())
            elif code == OP_GETZONE:
                emit("zone number %d" % self.call("getzone"))
            elif code == OP_TSET:
                n = (TGUARD + TSIZE + TGUARD) // 2
                e.write(self.tbuf, struct.pack("<%dI" % n, *args(n)))
            elif code == OP_IS:
                n, v = arg(), arg()
                emit("is in table %d %d -> %d"
                     % (s32(n), s32(v),
                        self.call("is", self.tbuf + 2 * TGUARD, n, v)))
            elif code == OP_TOGGLE:
                n, mx, v = arg(), arg(), arg()
                r = self.call("toggle", self.tbuf + 2 * TGUARD, n, mx, v)
                emit("toggle %d %d %d -> %d" % (s32(n), s32(mx), s32(v), r))
                self.dump_tbuf()
            elif code == OP_FACADE:
                e.write(self.pos, struct.pack("<4I", *args(4)))
                e.write(self.eye, struct.pack("<4I", *args(4)))
                e.write(self.m, b"\xa5" * 64)
                self.call("facade", self.m, self.pos, self.eye)
                emit("facade" + "".join(" %08x" % fx(e.u32(self.m + 4 * j))
                                        for j in range(16)))
            elif code == OP_DUMP_INST:
                k, j = arg(), arg()
                emit("instances %d.%d" % (k, j))
                self.dump_instances(k, j)
            elif code == OP_FLIP:
                k, j = arg(), arg()
                emit("flip h%d.%d" % (k, j))
                self.call("flip", self.chunks[k].child[j].base)
            else:
                raise SystemExit("unknown op %d" % code)
        return self.out


def model(sc):
    m = Model(sc)
    lines = m.run()
    if m.e.eediv_pcs:
        sys.exit("the model divided by zero at %s -- the port follows IEEE "
                 "there; keep the script clear of it"
                 % " ".join("%08x" % p for p in sorted(m.e.eediv_pcs)))
    return lines


# ---------------------------------------------------------------- running

HARNESS_TIMEOUT = 30
HARNESS_HUNG = -9999


def write_script(sc, path):
    Path(path).write_text(" ".join("%x" % x for x in sc.words) + NL)


def run_harness(exe, script_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(script_path)], stdout=fh,
                               stderr=subprocess.PIPE, text=True,
                               timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("harness hung, killed after %d s" % HARNESS_TIMEOUT)
        return HARNESS_HUNG
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
    return r.returncode


def diff(model_lines, harness_lines, quiet=False):
    bad = 0
    for line in difflib.unified_diff(model_lines, harness_lines,
                                     "model", "harness", lineterm="", n=1):
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith(("+", "-")):
            bad += 1
            if not quiet and bad <= 40:
                print(line[:400])
    return bad


def build(tmp):
    return hostbuild.build(tmp, SOURCES, name="scenery_test")


# -------------------------------------------------------------- mutations
#
# (name, file, old, new). Each replaces the first match, so every pattern is
# spelled to match code and not a comment.


def _m(name, old, new, rel=SC):
    return (name, rel, old, new)


MUTATIONS = [
    # the loader
    _m("ld-type",
       "    if (type == SCENERY_CONTAINER_ID) {\n"
       "        ScenerySectionHeader *h = NULL;",
       "    if (type == SCENERY_CONTAINER_ID + 1) {\n"
       "        ScenerySectionHeader *h = NULL;"),
    _m("payload16-short",
       "return (uint8_t *)(((uintptr_t)chunk + 8 + 15) & ~(uintptr_t)15);",
       "return (uint8_t *)(((uintptr_t)chunk + 8 + 7) & ~(uintptr_t)15);"),
    _m("ld-header-nopad",
       "h = (ScenerySectionHeader *)(void *)payload16(c);",
       "h = (ScenerySectionHeader *)(void *)(c + 8);"),
    _m("ld-no-table",
       "                ScenerySectionHeaderTable[h->SectionNumber] = h;\n", ""),
    _m("ld-split-le", "if (h->SectionNumber < 90)",
       "if (h->SectionNumber <= 90)"),
    _m("ld-split-swap",
       "                    add_tail(&ScenerySectionHeaderList, &h->Node);\n"
       "                else\n"
       "                    add_head(&ScenerySectionHeaderList, &h->Node);",
       "                    add_head(&ScenerySectionHeaderList, &h->Node);\n"
       "                else\n"
       "                    add_tail(&ScenerySectionHeaderList, &h->Node);"),
    _m("ld-info-pad",
       "h->pSceneryInfo = (SceneryInfo *)(void *)(c + 8);",
       "h->pSceneryInfo = (SceneryInfo *)(void *)payload16(c);"),
    _m("ld-info-count",
       "h->NumSceneryInfo = (int32_t)(size / sizeof(SceneryInfo));",
       "h->NumSceneryInfo = (int32_t)(size / sizeof(SceneryInfo)) - 1;"),
    _m("ld-inst-nopad",
       "h->pSceneryInstance = (SceneryInstance *)(void *)a;",
       "h->pSceneryInstance = (SceneryInstance *)(void *)(c + 8);"),
    _m("ld-inst-count", "(size - (uint32_t)(a - (c + 8)))", "size"),
    _m("ld-inst-signed",
       "                    (size - (uint32_t)(a - (c + 8)))\n"
       "                    / sizeof(SceneryInstance));",
       "                    ((int32_t)size - (int32_t)(a - (c + 8)))\n"
       "                    / (int32_t)sizeof(SceneryInstance));"),
    _m("ld-tree-pad",
       "h->SceneryTreeNodeTable = (SceneryTreeNode *)(void *)(c + 8);",
       "h->SceneryTreeNodeTable = (SceneryTreeNode *)(void *)payload16(c);"),
    _m("ld-tree-count", "(int32_t)(size / sizeof(SceneryTreeNode))",
       "(int32_t)(size / sizeof(SceneryInstance))"),
    _m("ld-model-all", "                if (info->NameHash[k] != 0) {",
       "                if (1) {"),
    _m("ld-model-lods",
       "            for (k = 0; k < 3; k++) {\n"
       "                if (info->NameHash[k] != 0) {",
       "            for (k = 0; k < 2; k++) {\n"
       "                if (info->NameHash[k] != 0) {"),
    _m("ld-model-after-init",
       "                    info->pModel[k] = m;\n"
       "                    model_init(m, info->NameHash[k]);",
       "                    model_init(m, info->NameHash[k]);\n"
       "                    info->pModel[k] = m;"),
    _m("new-no-namehash", "    m->NameHash = 0;\n", ""),
    _m("new-no-solid", "    m->Solid = NULL;\n", ""),
    _m("ld-no-flip",
       "        if (RaceParametersTrackDirection == TRACK_DIRECTION_BACKWARD)\n"
       "            scenery_flip_objects_on_backwards_track(h);\n", ""),
    _m("ld-flip-dir",
       "RaceParametersTrackDirection == TRACK_DIRECTION_BACKWARD",
       "RaceParametersTrackDirection != TRACK_DIRECTION_FORWARD"),
    _m("ld-ret-container",
       "            scenery_flip_objects_on_backwards_track(h);\n"
       "        return 1;",
       "            scenery_flip_objects_on_backwards_track(h);\n"
       "        return 0;"),
    _m("ld-zone-head", "            add_tail(&VisibleZoneList, &z->Node);",
       "            add_head(&VisibleZoneList, &z->Node);"),
    _m("ld-zone-caffeine", "            z->pCaffeineObj = NULL;\n", ""),
    _m("ld-zone-le",
       "        for (i = 0; i < n; i++) {\n            VisibleZone *z",
       "        for (i = 0; i <= n; i++) {\n            VisibleZone *z"),
    _m("ld-zone-ret",
       "            z->pCaffeineObj = NULL;\n        }\n        return 1;",
       "            z->pCaffeineObj = NULL;\n        }\n        return 0;"),
    _m("ld-other-ret",
       "        return 1;\n    }\n    return 0;\n}\n\nint32_t scenery_unloader",
       "        return 1;\n    }\n    return 1;\n}\n\nint32_t scenery_unloader"),
    # the unloader
    _m("ul-type",
       "    if (type == SCENERY_CONTAINER_ID) {\n"
       "        ScenerySectionHeader *h =\n",
       "    if (type == SCENERY_CONTAINER_ID + 1) {\n"
       "        ScenerySectionHeader *h =\n"),
    _m("ul-first-child",
       "(ScenerySectionHeader *)(void *)payload16(chunk + 8);",
       "(ScenerySectionHeader *)(void *)(chunk + 16);"),
    _m("ul-no-unlink", "        unlink_node(&h->Node);\n", ""),
    _m("ul-no-table",
       "        ScenerySectionHeaderTable[h->SectionNumber] = NULL;\n", ""),
    _m("ul-flags", "model_destroy(info->pModel[k], 3);",
       "model_destroy(info->pModel[k], 1);"),
    _m("ul-null",
       "                if (info->pModel[k] != NULL)\n"
       "                    model_destroy",
       "                if (1)\n"
       "                    model_destroy"),
    _m("ul-lods",
       "            for (k = 0; k < 3; k++)\n"
       "                if (info->pModel[k] != NULL)",
       "            for (k = 0; k < 2; k++)\n"
       "                if (info->pModel[k] != NULL)"),
    _m("ul-zone-first",
       "        for (i = 0; i < n; i++)\n            unlink_node(",
       "        for (i = 1; i < n; i++)\n            unlink_node("),
    _m("ul-zone-ret",
       "            unlink_node(&((VisibleZone *)(void *)(chunk + 8) + i)->Node);"
       "\n        return 1;",
       "            unlink_node(&((VisibleZone *)(void *)(chunk + 8) + i)->Node);"
       "\n        return 0;"),
    _m("ul-other-ret",
       "        return 1;\n    }\n    return 0;\n}\n\nSceneryInfo *scenery_find_info",
       "        return 1;\n    }\n    return 1;\n}\n\nSceneryInfo *scenery_find_info"),
    # the finds
    _m("fi-lod",
       "            if (h->pSceneryInfo[i].NameHash[0] == name_hash)",
       "            if (h->pSceneryInfo[i].NameHash[1] == name_hash)"),
    _m("fi-reverse",
       "    for (n = ScenerySectionHeaderList.next; n != &ScenerySectionHeaderList;"
       "\n         n = n->next) {\n"
       "        ScenerySectionHeader *h = (ScenerySectionHeader *)(void *)n;\n\n"
       "        for (i = 0; i < h->NumSceneryInfo; i++)",
       "    for (n = ScenerySectionHeaderList.prev; n != &ScenerySectionHeaderList;"
       "\n         n = n->prev) {\n"
       "        ScenerySectionHeader *h = (ScenerySectionHeader *)(void *)n;\n\n"
       "        for (i = 0; i < h->NumSceneryInfo; i++)"),
    _m("fih-lod",
       "            if (h->pSceneryInfo[s->SceneryInfoNumber].NameHash[0]",
       "            if (h->pSceneryInfo[s->SceneryInfoNumber].NameHash[1]"),
    _m("fih-kind", "h->pSceneryInfo[s->SceneryInfoNumber]",
       "h->pSceneryInfo[i]"),
    _m("fis-null",
       "    if (h == NULL)\n        return NULL;\n"
       "    return &h->pSceneryInstance[index];",
       "    return &h->pSceneryInstance[index];"),
    # IsPointInPoly and FindVisibleZone
    _m("pip-le",
       "if ((pi->y <= y && y < pj->y) || (pj->y <= y && y < pi->y)) {",
       "if ((pi->y < y && y < pj->y) || (pj->y <= y && y < pi->y)) {"),
    _m("pip-lt",
       "if ((pi->y <= y && y < pj->y) || (pj->y <= y && y < pi->y)) {",
       "if ((pi->y <= y && y <= pj->y) || (pj->y <= y && y < pi->y)) {"),
    _m("pip-half2",
       "if ((pi->y <= y && y < pj->y) || (pj->y <= y && y < pi->y)) {",
       "if ((pi->y <= y && y < pj->y) || (pj->y < y && y <= pi->y)) {"),
    _m("pip-xle", "            if (x < xc)", "            if (x <= xc)"),
    _m("pip-div-first",
       "float xc = (pj->x - pi->x) * (y - pi->y) / (pj->y - pi->y)",
       "float xc = (pj->x - pi->x) * ((y - pi->y) / (pj->y - pi->y))"),
    _m("pip-j0", "int32_t i, j = n - 1, c = 0;", "int32_t i, j = 0, c = 0;"),
    _m("pip-base", "                       + pi->x;",
       "                       + pj->x;"),
    _m("fz-no-front",
       "            unlink_node(n);\n            add_head(&VisibleZoneList, n);\n",
       ""),
    _m("fz-back", "            add_head(&VisibleZoneList, n);",
       "            add_tail(&VisibleZoneList, n);"),
    # the zones' lookups
    _m("zi-unsigned",
       "        if (s[i] == section)",
       "        if ((uint16_t)s[i] == section)"),
    _m("zf-first",
       "    if (i >= 0)\n        return i;\n    i = z->NumVisibleScenerySections;",
       "    if (i > 0)\n        return i;\n    i = z->NumVisibleScenerySections;"),
    _m("zf-cap", "    if (i == VISIBLE_ZONE_MAX_SECTIONS)",
       "    if (i >= VISIBLE_ZONE_MAX_SECTIONS)"),
    _m("zf-no-count", "    z->NumVisibleScenerySections = i + 1;\n", ""),
    _m("ivz-name", 'bchunk_hash("MARKER_BOUNDARY")',
       'bchunk_hash("MARKER_BOUNDARIES")'),
    _m("cvz-keep", "    pVisibleZoneBoundaryModel = NULL;\n}", "}"),
    _m("cvz-flags", "        model_destroy(pVisibleZoneBoundaryModel, 3);",
       "        model_destroy(pVisibleZoneBoundaryModel, 1);"),
    _m("bl-plus-only", "    if (step == 1 || step == -1)",
       "    if (step == 1)"),
    _m("bl-nonzero", "    if (step == 1 || step == -1)",
       "    if (step != 0)"),
    _m("czn-zero", "int32_t CurrentZoneNumber = -1;",
       "int32_t CurrentZoneNumber;"),
    # the tables
    _m("it-unsigned", "        if (table[i] == value)",
       "        if ((uint16_t)table[i] == value)"),
    _m("tt-no-strike", "        table[i] = -1;\n", ""),
    _m("tt-found-count", "        table[i] = -1;\n        return n;",
       "        table[i] = -1;\n        return n - 1;"),
    _m("tt-no-mod", "    table[n % max] = (int16_t)value;",
       "    table[n] = (int16_t)value;"),
    _m("tt-umod", "    table[n % max] = (int16_t)value;",
       "    table[(uint32_t)n % (uint32_t)max] = (int16_t)value;"),
    # CreateFacadeMatrix
    _m("fa-swap", "int32_t a = bATan(pos->x - eye->x, pos->y - eye->y);",
       "int32_t a = bATan(pos->y - eye->y, pos->x - eye->x);"),
    _m("fa-sign", "int32_t a = bATan(pos->x - eye->x, pos->y - eye->y);",
       "int32_t a = bATan(eye->x - pos->x, eye->y - pos->y);"),
    _m("fa-w-pad", "    m->v3.w = 1.0f;\n}", "    m->v3.w = pos->pad;\n}"),
    _m("fa-not-identity",
       "    eRotateZ(m, &eMathIdentityMatrix, (uint16_t)a);",
       "    eRotateZ(m, m, (uint16_t)a);"),
    # the flip
    _m("fl-flag", "if (!(s->ExcludeFlags & SCENERY_FLIP_ON_BACKWARDS))",
       "if (!(s->ExcludeFlags & 0x0200))"),
    _m("fl-all",
       "        if (!(s->ExcludeFlags & SCENERY_FLIP_ON_BACKWARDS))\n"
       "            continue;\n", ""),
    _m("fl-angle", "        eRotateZ(&m, &m, 0x8000);",
       "        eRotateZ(&m, &m, 0x7fff);"),
    _m("fl-scale", "(float)s->Rotation[3 * r + k] * (1.0f / 16384.0f)",
       "(float)s->Rotation[3 * r + k] / 16383.0f"),
    _m("fl-saturate", "(int16_t)ee_trunc_w(row[r][k] * 16384.0f)",
       "(int16_t)(ee_trunc_w(row[r][k] * 16384.0f) > 32767 ? 32767\n"
       "                              : ee_trunc_w(row[r][k] * 16384.0f))"),
    _m("fl-transpose", "                s->Rotation[3 * r + k] =",
       "                s->Rotation[3 * k + r] ="),
    _m("fl-row3-w", "        m.v3.w = 1.0f;\n        eRotateZ(&m, &m, 0x8000);",
       "        m.v3.w = 0.0f;\n        eRotateZ(&m, &m, 0x8000);"),
    # the statics
    _m("si-cross", "    ScenerySectionHeaderList.next = &ScenerySectionHeaderList;",
       "    ScenerySectionHeaderList.next = &VisibleZoneList;"),
    _m("sc-order",
       "    close_list(&VisibleZoneList);\n"
       "    close_list(&ScenerySectionHeaderList);",
       "    close_list(&ScenerySectionHeaderList);\n"
       "    close_list(&VisibleZoneList);"),
    _m("sc-no-free", "        unlink_node(n);\n        bFree(n);",
       "        unlink_node(n);"),
]

EQUIVALENT = {
    # eModel::Init is a seam that reads its model and the name, not the
    # kind the model is stored in; the listing stores it first (the jal's
    # delay slot), and nothing can tell.
    "ld-model-after-init",
    # The fourth row of the flip's matrix is turned with the rest and never
    # read back: only the three rows of the rotation are stored.
    "fl-row3-w",
}

write_source = hostbuild.write_source


def mutate_pass(sc, base_model):
    survived, missing, equivalent, caught = [], [], [], 0

    with tempfile.TemporaryDirectory() as tmp:
        sp = Path(tmp) / "script.txt"
        write_script(sc, sp)
        exe = build(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, sp, out)
        if diff(base_model, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for name, rel, before, after in MUTATIONS:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = (chr(13) + NL) in text
        probe = before.replace(NL, chr(13) + NL) if crlf else before
        repl = after.replace(NL, chr(13) + NL) if crlf else after

        if probe not in text:
            missing.append(name)
            print("  %-28s PATTERN NOT FOUND" % name)
            continue
        try:
            write_source(path, text.replace(probe, repl, 1))
            with tempfile.TemporaryDirectory() as tmp:
                sp = Path(tmp) / "script.txt"
                write_script(sc, sp)
                try:
                    exe = build(tmp)
                except SystemExit:
                    print("  %-28s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, sp, out)
                if rc == HARNESS_HUNG:
                    print("  %-28s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-28s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base_model, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-28s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-28s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-28s SURVIVED" % name)
                    survived.append(name)
        finally:
            try:
                write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))

    real = [m for m in MUTATIONS if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    # An entry whose mutant was caught is a wrong reason, not a spare one.
    stale = [n for n in EQUIVALENT
             if n not in equivalent and n not in missing]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally below is over %d of %d"
              % (len(missing), len(real), len(MUTATIONS)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
    for name in holes:
        print("  unexplained: %s" % name)
    for name in stale:
        ran = any(m[0] == name for m in MUTATIONS)
        print("  listed as equivalent but %s: %s"
              % ("caught" if ran else "names no mutation", name))
    return 1 if (holes or missing or stale) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--dump", metavar="DIR")
    ap.add_argument("--quick", action="store_true",
                    help="a sample of the finds on TRACKB12, not all")
    args = ap.parse_args()

    sc = script(quick=args.quick)
    lines = model(sc)
    if args.mutate:
        sys.exit(mutate_pass(sc, lines))

    with tempfile.TemporaryDirectory() as tmp:
        sp = Path(tmp) / "script.txt"
        write_script(sc, sp)
        exe = build(tmp)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, sp, out)
        harness = out.read_text().splitlines()

        if args.dump:
            d = Path(args.dump)
            d.mkdir(parents=True, exist_ok=True)
            (d / "model.txt").write_text(NL.join(lines) + NL)
            (d / "harness.txt").write_text(NL.join(harness) + NL)
            (d / "script.txt").write_text(sp.read_text())

    bad = diff(lines, harness)
    ops = sum(1 for line in lines if not line.startswith(("  ", "[")))
    models = sum(1 for line in lines if line.startswith("  omalloc "))
    print("%d scenarios, %d ops, %d lines, %d differ; %d models built"
          % (len(sc.tags), ops, len(harness), bad, models))
    sys.exit(1 if (bad or rc) else 0)


if __name__ == "__main__":
    main()
