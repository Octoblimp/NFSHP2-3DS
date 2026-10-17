#!/usr/bin/env python3
"""Cross-check 3DS Files/source/polyhedra.c against polyhedra.cpp in the image.

polyhedra.cpp is 0x00205058 .. 0x00206440: the Rect, Cube, Wafer and
Pipeline polyhedra the collision bodies hand to VClip, the loader for the
collision volumes that come off the disc, and four debug tests. The image
is the oracle. tools/mipsemu.py runs the shipped functions out of
NFSHP2.ELF, the harness (tools/src/polyhedra_test.c) runs the port, both
walk the same script, and the two transcripts are diffed.

Every polyhedron and feature is named, not printed as an address (the
harness's head has the scheme), and floats are compared as bits with every
NaN printed as the one quiet NaN.

The script covers:

  * the ten neighbour tables and the three gp constants;
  * RectPolyhedron's constructor over boxes proper, inverted, flat, thin,
    with bounds at +0 and -0, and far from the origin, and
    CubePolyhedron's inline one, of every sign and of size +0 and -0;
  * WaferPolyhedron::Init over every one of TRACKB12's 15708 polygons, as
    the image's TrackPolygon constructor makes them (the first forty
    dumped in full, the rest folded into a CRC32 each), and over made-up
    quads and triangles: corners either side of bEqual's 0.001, junk in
    the fourth lanes, -0 in the normal, origins off zero, and three edges
    whose length squared rounds differently summed the other way;
  * the loader and unloader over every collision volume on the disc --
    fourteen cars, INGAMEB and TRACKB12 -- at the disc's alignment, and
    repacked for the three others, and over containers made to be wrong:
    an empty one, one whose top id is not 0x80034020, one whose header
    chunk has another id (loaded, then skipped by the unloader), one with
    an Espresso object, and one with a vertex at -0;
  * FindPipelinePolyhedron with and without a centre of gravity, on a
    name listed twice and on one not listed; MoveCenterOfGravity; the
    destructors; and the list's globals -- the script boots on the static
    initialiser alone, runs the constructor again with a volume listed,
    and runs the destructor;
  * RandomLocation; TestCubes over a run of seeds; InitVoronoiClip,
    stopped at the first ticker after a given number of tests; and
    TestVClipRepeatability with its outer count patched down, on
    DIABLO_CV, from a seed whose first pair of poses penetrates as well.

The tests throw every result away, so what they call is compared instead:
the witness constructor (and the two cubes on its stack), VClip's arguments
and the witness it leaves, the destructors (with TestCubes's heap cube
dumped as it goes), bGetTicker, bMalloc and bFree. A volume whose container
never loaded prints as not loaded: its array pointers are the tool's junk.
TestCubes leaves the fourth lane of both translations as stack junk, so the
translations are printed three lanes wide; the contact points likewise.

The model runs with the EE's divide on, and the run fails if any divide
anywhere took its divide-by-zero path: the ports follow IEEE there, so the
script keeps clear of it.

    python tools/polyhedra_check.py
    python tools/polyhedra_check.py --mutate
    python tools/polyhedra_check.py --dump out/polyhedra
"""
import argparse
import difflib
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

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)
M32 = 0xFFFFFFFF

SOURCES = [
    "tools/src/polyhedra_test.c",
    "3DS Files/source/polyhedra.c",
    "3DS Files/source/vclip.c",
    "3DS Files/source/replay.c", "3DS Files/source/p32.c",
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/bvector.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
    "3DS Files/source/emath.c",
    "3DS Files/source/bmem.c",
    "3DS Files/source/espresso.c",
]

FLAGS = hostbuild.FLAGS + [
    "-Wl,--wrap=vcwitness_init,--wrap=vcwitness_vclip,"
    "--wrap=vcwitness_destroy,--wrap=vcpoly_destroy",
]

PH = "3DS Files/source/polyhedra.c"
PHH = "3DS Files/source/polyhedra.h"

(OP_TAG, OP_TABLES, OP_CONSTS, OP_RECT, OP_CUBE, OP_WAFER, OP_DESTROY,
 OP_CHUNK, OP_LOAD, OP_UNLOAD, OP_FIND, OP_MOVECOG, OP_LIST, OP_DUMP_VOL,
 OP_INIT_GLOBALS, OP_CLOSE_GLOBALS, OP_SEED, OP_RANDLOC, OP_TESTCUBES,
 OP_INITVC, OP_REPEAT, OP_SETOBJ, OP_BOOT) = range(1, 24)

KIND_RECT, KIND_CUBE, KIND_WAFER, KIND_VOLUME = range(4)

NRECT = 4
NWAFER = 4
NCHUNK = 32

SIZE_V, SIZE_E, SIZE_F, SIZE_PL = 20, 12, 24, 24
KIND_SIZE = (SIZE_V, SIZE_E, SIZE_F)
RECT_SIZE, WAFER_SIZE = 2800, 992

LIST_HEAD = 0x00324a30
TEST_COUNTER = 0x00324a28
DEFAULT_SEED = 0x00324f90
GP = 0x00328bf0
TABLES = (
    ("RectEdgesNearFaces", 0x00313a08, 24),
    ("RectEdgesNearVertices", 0x00313a68, 24),
    ("RectFacesNearEdges", 0x00313ac8, 24),
    ("RectVerticesNearEdges", 0x00313b28, 24),
    ("WaferEdgesNearFaces", 0x00313b88, 8),
    ("WaferEdgesNearVertices", 0x00313ba8, 8),
    ("WaferFacesNearEdges", 0x00313bc8, 8),
    ("WaferVerticesNearEdges", 0x00313be8, 8),
    ("TriWaferEdgesNearVertices", 0x00313c08, 8),
    ("TriWaferVerticesNearEdges", 0x00313c28, 8),
)
POLY_LO, POLY_HI = 0x00205058, 0x00206440

# TestVClipRepeatability's outer count, `lui v0,0xf ; ori v1,v1,0x423f`.
REPEAT_LUI = (0x00206144, 0x3c02000f)
REPEAT_ORI = (0x002061a0, 0x3463423f)

# VClip's return addresses in TestCubes and TestVClipRepeatability.
VCLIP_RETURNS = (0x00205b10, 0x00205b44, 0x0020623c, 0x002062a8, 0x002062c0)

SYM = {
    "rect": "__14RectPolyhedronffffff",
    "wafer": "Init__15WaferPolyhedronP12TrackPolygonRC8bVector3",
    "testcubes": "TestCubes__Fv",
    "initvc": "InitVoronoiClip__Fv",
    "load": "LoaderCollisionVolumes__FP6bChunk",
    "unload": "UnloaderCollisionVolumes__FP6bChunk",
    "find": "FindPipelinePolyhedron__FUiP8bVector3",
    "movecog": "MoveCenterOfGravity__18PipelinePolyhedronP8bVector3",
    "randloc": "RandomLocation__FP8bVector3P8bMatrix4",
    "repeat": "TestVClipRepeatability__Fv",
    "gdtor": "_GLOBAL_$D$RectEdgesNearFaces",
    "gctor": "_GLOBAL_$I$RectEdgesNearFaces",
    "d_pipe": "_$_18PipelinePolyhedron",
    "d_cube": "_$_14CubePolyhedron",
    "d_rect": "_$_14RectPolyhedron",
    "d_wafer": "_$_15WaferPolyhedron",
    "wit_ctor": "__9VCWitnessP12VCPolyhedronT1",
    "wit_dtor": "_$_9VCWitness",
    "vclip": "VClip__9VCWitnessP8bMatrix4P8bVector3T1T2",
    "poly_dtor": "_$_12VCPolyhedron",
    "tpinit": "__12TrackPolygonP19TopologyTreePolygon",
}

EXTRACTED = ROOT / "extracted"
TRACKB12 = EXTRACTED / "TRACKS" / "TRACKB12.BUN"
INGAMEB = EXTRACTED / "GLOBAL" / "INGAMEB.BUN"
CARS = EXTRACTED / "CARS"

bits = me.f_to_bits
fbits = me.fbits_to
f32 = me.f32


def s32(x):
    x &= M32
    return x - (1 << 32) if x & 0x80000000 else x


def s16(x):
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


def s8(x):
    x &= 0xFF
    return x - 0x100 if x & 0x80 else x


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


# ------------------------------------------------------------------ disc


def containers(path):
    """(offset, bytes) of every 0x80034020 in a file, walking the chunk tree."""
    d = path.read_bytes()
    out = []

    def walk(off, end):
        while off + 8 <= end:
            cid, size = struct.unpack_from("<II", d, off)
            if off + 8 + size > end:
                return
            if cid == 0x80034020:
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


def repack(data, mis, disc_mis=0):
    """A container laid out for misalignment `mis` rather than the disc's:
    each child's pad before its records redone for where it now lies. The
    pads are part of the layout -- a container moved without them has every
    record array read from the wrong place."""
    out = bytearray(data[:8])
    for o, cid, csize in groups(data):
        da = disc_mis + o
        pad = align16(da + 8) - (da + 8)
        body = data[o + 8 + pad:o + 8 + csize]
        na = mis + len(out)
        npad = align16(na + 8) - (na + 8)
        out += struct.pack("<II", cid, npad + len(body)) + bytes(npad) + body
    struct.pack_into("<I", out, 4, len(out) - 8)
    return bytes(out)


def b12_track_polygons(step=1):
    """TRACKB12's TopologyTreePolygons through the image's TrackPolygon
    constructor: for each, the 20 words WaferPolyhedron::Init reads --
    the four corners, the normal and the plane distance."""
    d = TRACKB12.read_bytes()
    t, s = struct.unpack_from("<II", d, 0x7fbe68)
    assert t == 0x34132
    body, count = 0x7fbe68 + 8, s // 32
    e = me.Emu(ieee=True, eediv=True)
    e.stub_bware()
    e.stub("bGetSlotNumber__FP8SlotPoolPv", lambda em: 0)
    tp, src = e.alloc(128, 16), e.alloc(32, 16)
    fn = e.addr_of(SYM["tpinit"])
    out = []
    for i in range(0, count, step):
        e.write(src, d[body + 32 * i:body + 32 * i + 32])
        e.call(fn, tp, src)
        out.append([e.u32(tp + 48 + 4 * k) for k in range(16)]
                   + [e.u32(tp + 112 + 4 * k) for k in range(4)])
    if e.eediv_pcs:
        sys.exit("the TrackPolygon constructor divided by zero at %s"
                 % " ".join("%08x" % p for p in sorted(e.eediv_pcs)))
    return out


# ---------------------------------------------------------------- script


class Script(object):
    def __init__(self):
        self.words = []
        self.tags = []
        self.chunks = 0
        self.containers = {}    # name -> (chunk, data)
        # the harness numbers volumes by header slot, every fifth child
        self.nvols = 0
        self.first_vol = {}     # chunk -> its first volume's number

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

    def v(self, x, y, z, w=0.0):
        return [bits(x), bits(y), bits(z), bits(w)]

    def rect(self, i, *b):
        self.op(OP_RECT, i, *[float(x) for x in b])

    def cube(self, i, s):
        self.op(OP_CUBE, i, float(s))

    def wafer(self, i, corners, normal, dist, origin=(0.0, 0.0, 0.0, 0.0),
              digest=False):
        ws = []
        for c in corners:
            c = list(c) + [0.0] * (4 - len(c))
            ws += self.v(*c)
        ws += [bits(normal[0]), bits(normal[1]), bits(normal[2]), bits(dist)]
        ws += self.v(*origin)
        self.op(OP_WAFER, i, 1 if digest else 0, *ws)

    def wafer_words(self, i, words, origin_words, digest):
        self.op(OP_WAFER, i, 1 if digest else 0, *(words + origin_words))

    def chunk(self, data, mis, name=None):
        k = self.chunks
        self.chunks += 1
        assert k < NCHUNK
        n = len(data)
        pad = data + bytes((-n) % 4)
        self.op(OP_CHUNK, k, mis, n,
                *struct.unpack("<%dI" % (len(pad) // 4), pad))
        if name:
            self.containers[name] = (k, data)
        self.first_vol[k] = self.nvols
        self.nvols += (len(groups(data)) + 4) // 5
        return k


def tables_section(sc):
    sc.tag("tables and constants")
    sc.op(OP_TABLES)
    sc.op(OP_CONSTS)


def rect_section(sc):
    sc.tag("rect: a unit box")
    sc.rect(0, 1, -1, 1, -1, 1, -1)
    sc.tag("rect: lopsided")
    sc.rect(1, 3.0, -0.5, 2.0, -7.0, 0.25, -0.125)
    sc.tag("rect: off the origin")
    sc.rect(2, 10.0, 2.0, 5.0, 4.0, -1.0, -3.0)
    sc.tag("rect: inverted on x")
    sc.rect(3, -1.0, 1.0, 1.0, -1.0, 1.0, -1.0)
    sc.tag("rect: inside out")
    sc.rect(0, -2.0, 2.0, -3.0, 3.0, -0.5, 0.5)
    sc.tag("rect: extents that do not divide evenly")
    sc.rect(1, 0.3, -0.1, 1.7, 0.1, 3.3, -2.9)
    sc.tag("rect: thin")
    sc.rect(2, 1.0, -1.0, 1.0, -1.0, 1e-3, -1e-3)
    sc.tag("rect: large and far away")
    sc.rect(3, 12345.5, 12000.25, -300.0, -4096.0, 9e3, 8.5e3)
    sc.tag("rect: the minimum bounds at -0")
    sc.rect(0, 1.0, -0.0, 2.0, -0.0, 3.0, -0.0)
    sc.tag("rect: the maximum bounds at -0")
    sc.rect(1, -0.0, -1.0, -0.0, -2.0, -0.0, -3.0)
    sc.tag("rect: the minimum bounds at +0")
    sc.rect(2, 1.0, 0.0, 2.0, 0.0, 3.0, 0.0)
    sc.tag("rect: flat, its z edges of no length")
    sc.rect(3, 1.0, -1.0, 2.0, -2.0, 0.5, 0.5)
    sc.tag("cube: the inline constructor")
    for i, s in enumerate((2.0, 0.3, 100.0, 1e-3)):
        sc.cube(i, s)
    sc.tag("cube: a negative size")
    sc.cube(0, -2.5)
    sc.tag("cube: an odd size")
    sc.cube(1, 77.77)
    sc.tag("cube: of no size, either side of 0")
    sc.cube(2, 0.0)
    sc.cube(3, -0.0)


def rect_destroy_section(sc):
    sc.tag("rect: the destructors")
    sc.rect(0, 1, -1, 1, -1, 1, -1)
    sc.op(OP_DESTROY, KIND_RECT, 0, 0)
    sc.rect(1, 2, -1, 1, -3, 1, -1)
    sc.op(OP_SETOBJ, KIND_RECT, 1, 77)
    sc.op(OP_DESTROY, KIND_RECT, 1, 1)
    sc.cube(2, 3.0)
    sc.op(OP_DESTROY, KIND_CUBE, 2, 2)
    sc.cube(3, 5.0)
    sc.op(OP_SETOBJ, KIND_RECT, 3, 91)
    sc.op(OP_DESTROY, KIND_CUBE, 3, 3)


def wafer_section(sc, rnd):
    sq = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    sc.tag("wafer: a unit square")
    sc.wafer(0, sq, (0.0, 0.0, 1.0), 0.0)
    sc.tag("wafer: the square wound the other way")
    sc.wafer(1, list(reversed(sq)), (0.0, 0.0, -1.0), 0.0)
    sc.tag("wafer: a triangle, corner 3 on corner 2")
    tri = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 3.0, 0.0),
           (0.0, 3.0, 0.0)]
    sc.wafer(2, tri, (0.0, 0.0, 1.0), 0.0)
    sc.tag("wafer: a tilted quad, off the origin")
    q = [(10.0, 20.0, 3.0), (14.0, 20.5, 3.25), (13.5, 26.0, 4.0),
         (9.75, 25.0, 3.5)]
    sc.wafer(3, q, (-0.0605, -0.0156, 0.998), 2.37,
             origin=(11.0, 22.0, 3.0, 0.0))

    sc.tag("wafer: corner 3 within, at and past 0.001 of corner 2")
    eps = fbits(bits(0.001))
    for axis in range(3):
        for dv in (0.0, fbits(bits(eps) - 1), eps, fbits(bits(eps) + 1),
                   -eps, -fbits(bits(eps) + 1), 0.002):
            c2 = [0.0, 3.0, 0.0]
            c3 = list(c2)
            c3[axis] += dv
            sc.wafer(axis, [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), tuple(c2),
                            tuple(c3)], (0.0, 0.0, 1.0), 0.0)
    sc.tag("wafer: corner 3 equal but for its fourth lane")
    sc.wafer(0, [(0.0, 0.0, 0.0, 9.0), (2.0, 0.0, 0.0, -4.0),
                 (0.0, 3.0, 0.0, 1.5), (0.0, 3.0, 0.0, 7.25)],
             (0.0, 0.0, 1.0), 0.0)
    sc.tag("wafer: junk in the fourth lanes, the origin's too")
    sc.wafer(1, [(1.0, 1.0, 5.0, 3.0), (3.0, 1.0, 5.0, -2.0),
                 (3.0, 4.0, 5.0, 11.0), (1.0, 4.0, 5.0, 0.5)],
             (0.0, 0.0, 1.0), 5.0, origin=(0.5, 0.5, 4.0, 6.0))
    sc.tag("wafer: -0 in the normal")
    sc.wafer(2, sq, (-0.0, -0.0, 1.0), -0.0)
    sc.wafer(3, sq, (0.0, -0.0, -1.0), 0.0, origin=(-0.0, -0.0, -0.0, -0.0))
    # Edge 0 of each is one of the rare vectors whose length squared rounds
    # differently summed as x + (y + z), by enough to move a truncated
    # direction lane. No track edge happens to be one.
    sc.tag("wafer: edges whose length squared shows its grouping")
    for i, e in enumerate(((0x3f4d32b3, 0xbf58c2a9, 0x40970e8f),
                           (0x402f0871, 0x3fcc56a1, 0xc096a087),
                           (0x4185673c, 0x4146ee5a, 0xc12a3951))):
        v = tuple(fbits(b) for b in e)
        n = (-4.0 * v[2], 0.0, 4.0 * v[0])
        ln = (n[0] * n[0] + n[2] * n[2]) ** 0.5
        sc.wafer(i, [(0.0, 0.0, 0.0), v, (v[0], v[1] + 4.0, v[2]),
                     (0.0, 4.0, 0.0)], (n[0] / ln, 0.0, n[2] / ln), 0.0)
    sc.tag("wafer: made-up quads and triangles")
    for n in range(24):
        cx, cy, cz = (rnd.uniform(-500, 500) for _ in range(3))
        corners = []
        for k in range(4):
            a = k * 1.5707963 + rnd.uniform(-0.4, 0.4)
            r = rnd.uniform(0.5, 8.0)
            corners.append((cx + r * __import__("math").cos(a),
                            cy + r * __import__("math").sin(a),
                            cz + rnd.uniform(-0.5, 0.5),
                            rnd.uniform(-2, 2)))
        if n % 3 == 0:
            corners[3] = corners[2]
        nx, ny = rnd.uniform(-0.2, 0.2), rnd.uniform(-0.2, 0.2)
        nz = (1.0 - nx * nx - ny * ny) ** 0.5
        org = ((round(cx), round(cy), round(cz), rnd.uniform(-1, 1))
               if n % 2 else (0.0, 0.0, 0.0, 0.0))
        sc.wafer(n % NWAFER, corners, (nx, ny, nz), rnd.uniform(-9, 9),
                 origin=org)


def wafer_destroy_section(sc):
    sc.tag("wafer: the destructor")
    sq = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    sc.op(OP_SETOBJ, KIND_WAFER, 0, 123)
    sc.wafer(0, sq, (0.0, 0.0, 1.0), 0.0)
    sc.op(OP_DESTROY, KIND_WAFER, 0, 2)
    sc.wafer(1, sq, (0.0, 0.0, 1.0), 0.0)
    sc.op(OP_DESTROY, KIND_WAFER, 1, 3)


def track_section(sc, polys, full=40):
    sc.tag("wafer: TRACKB12's polygons, %d of them" % len(polys))
    tris = 0
    for i, ws in enumerate(polys):
        if i % 5 == 4:
            # an origin near corner 0, as a body placed on the polygon
            # would have, with junk in its fourth lane
            x, y, z = (float(round(fbits(ws[k]))) for k in range(3))
            org = [bits(x), bits(y), bits(z), bits(0.5 * (i % 7))]
        else:
            org = [0, 0, 0, 0]
        sc.wafer_words(i % NWAFER, ws, org, digest=i >= full)
        if ws[8:12] == ws[12:16]:
            tris += 1
    return tris


def chunk_section(sc):
    """Every collision volume on the disc, loaded and looked up."""
    cars = sorted(p for p in CARS.glob("*/GEOMETRY.BIN"))
    loaded = []
    sc.tag("load: every car's volume")
    for p in cars:
        for off, data in containers(p):
            k = sc.chunk(data, off % 16, name=p.parent.name)
            sc.op(OP_LOAD, k)
            loaded.append(k)
    sc.tag("load: INGAMEB and TRACKB12")
    for p, name in ((INGAMEB, "INGAMEB"), (TRACKB12, "TRACKB12")):
        for off, data in containers(p):
            k = sc.chunk(data, off % 16, name=name)
            sc.op(OP_LOAD, k)
            loaded.append(k)
    sc.op(OP_LIST)

    diablo = sc.containers["DIABLO"][1]
    bus = sc.containers["BUS"][1]
    sc.tag("load: BUS's volume again at each misalignment")
    copies = []
    for mis in (4, 8, 12):
        k = sc.chunk(repack(bus, mis), mis)
        sc.op(OP_LOAD, k)
        copies.append(k)

    sc.tag("load: an empty container")
    k_empty = sc.chunk(struct.pack("<II", 0x80034020, 0), 0)
    sc.op(OP_LOAD, k_empty)
    sc.tag("load: the wrong top id")
    k_wrong = sc.chunk(struct.pack("<I", 0x80034021) + bus[4:], 0)
    sc.op(OP_LOAD, k_wrong)
    sc.op(OP_UNLOAD, k_wrong)
    sc.tag("load: a header chunk with another id")
    g = groups(bus)
    odd = bytearray(bus)
    struct.pack_into("<I", odd, g[0][0], 0x00034029)
    k_odd = sc.chunk(bytes(odd), 0)
    sc.op(OP_LOAD, k_odd)
    sc.tag("load: a volume with an Espresso object")
    esp = bytearray(bus)
    hdr = align16(g[0][0] + 8)
    struct.pack_into("<I", esp, hdr + 12, 0x1234)
    k_esp = sc.chunk(bytes(esp), 0)
    sc.op(OP_LOAD, k_esp)
    sc.tag("load: TRACKB12's volumes, 4 bytes along")
    k_b12 = sc.chunk(repack(sc.containers["TRACKB12"][1], 4), 4)
    sc.op(OP_LOAD, k_b12)
    # The disc has no -0 in any vertex; this one gives MoveCenterOfGravity
    # a lane where 0 - x and -x part.
    sc.tag("load: BUS's volume with vertex 0 at y -0")
    negz = bytearray(bus)
    struct.pack_into("<I", negz, align16(g[1][0] + 8) + 8, 0x80000000)
    k_negz = sc.chunk(bytes(negz), 0)
    sc.op(OP_LOAD, k_negz)

    # the header records' hashes, straight from the disc
    def hash_of(data, j=0):
        c = groups(data)[5 * j][0]
        return u32at(data, align16(c + 8) + 48)

    h_diablo = hash_of(diablo)
    h_bus = hash_of(bus)
    h_rocket = hash_of(sc.containers["INGAMEB"][1], 1)
    sc.tag("find: DIABLO_CV, no centre of gravity")
    sc.op(OP_FIND, h_diablo, 0, *sc.v(0.0, 0.0, 0.0))
    sc.tag("find: BUS_CV, listed seven times, moved on the first find")
    sc.op(OP_FIND, h_bus, 1, *sc.v(0.25, -0.5, 1.125, 3.0))
    sc.op(OP_FIND, h_bus, 1, *sc.v(9.0, 9.0, 9.0, 9.0))
    sc.op(OP_FIND, h_bus, 0, *sc.v(0.0, 0.0, 0.0))
    sc.tag("find: CS_Rocket with -0 and junk in the centre")
    sc.op(OP_FIND, h_rocket, 1, *sc.v(-0.0, 0.0, -0.0, -7.5))
    sc.tag("find: a name not listed")
    sc.op(OP_FIND, 0x12345678, 1, *sc.v(1.0, 2.0, 3.0))
    sc.op(OP_FIND, 0, 0, *sc.v(0.0, 0.0, 0.0))
    return dict(loaded=loaded, copies=copies, empty=k_empty, wrong=k_wrong,
                odd=k_odd, esp=k_esp, b12=k_b12, negz=k_negz)


def movecog_section(sc, ks):
    sc.tag("movecog: a car's volume, twice")
    # volumes are numbered in chunk order, one per car
    sc.op(OP_MOVECOG, 0, *sc.v(0.0, 0.3125, -1.75, 1.0))
    sc.op(OP_MOVECOG, 0, *sc.v(-0.1, 0.2, 0.0, 0.0))
    sc.op(OP_DUMP_VOL, 1)
    sc.tag("movecog: +0 in the centre, onto a vertex at -0")
    sc.op(OP_MOVECOG, sc.first_vol[ks["negz"]], *sc.v(0.5, 0.0, 0.25, 0.0))


def random_section(sc):
    sc.tag("randloc")
    for seed in (0x12345678, 1, 0xdeadbeef, 0x80000000):
        sc.op(OP_SEED, seed)
        for _ in range(3):
            sc.op(OP_RANDLOC)


def tests_section(sc, cubes=12, initvc=((5248, 3), (0, 2), (-1000000, 1),
                                         (0x7ffffffe, 2))):
    sc.tag("testcubes")
    for seed in [0x13579bdf, 0x2468ace0, 5, 0xffffffff, 0x00010000,
                 0x7fffffff][:cubes] + list(range(100, 100 + cubes - 6)):
        sc.op(OP_SEED, seed)
        sc.op(OP_TESTCUBES)
    sc.tag("initvc")
    for counter, n in initvc:
        sc.op(OP_SEED, 0x55555555)
        sc.op(OP_INITVC, counter, n)


def repeat_section(sc):
    sc.tag("repeat: DIABLO_CV against itself")
    # 0xea76529b's first pair of poses penetrates, so it is drawn again
    for seed, last in ((0x31415926, 0), (0x27182818, 2), (0x0badf00d, 5),
                       (0xea76529b, 0)):
        sc.op(OP_SEED, seed)
        sc.op(OP_REPEAT, last)


def teardown_section(sc, ks):
    sc.tag("unload: a car, the odd header, the Espresso volume")
    sc.op(OP_UNLOAD, ks["loaded"][3])
    sc.op(OP_UNLOAD, ks["odd"])
    sc.op(OP_UNLOAD, ks["esp"])
    sc.op(OP_UNLOAD, ks["empty"])
    sc.tag("unload: a misaligned copy")
    sc.op(OP_UNLOAD, ks["copies"][1])
    sc.tag("destroy: a listed volume")
    sc.op(OP_DESTROY, KIND_VOLUME, 2, 0)
    sc.tag("close globals: every volume still listed destroyed")
    sc.op(OP_CLOSE_GLOBALS)
    sc.tag("init globals, then a fresh load")
    sc.op(OP_INIT_GLOBALS)
    k = sc.chunk(sc.containers["INGAMEB"][1], 0)
    sc.op(OP_LOAD, k)
    h = u32at(sc.containers["INGAMEB"][1],
              align16(groups(sc.containers["INGAMEB"][1])[0][0] + 8) + 48)
    sc.op(OP_FIND, h, 1, *sc.v(0.5, 0.5, 0.5))
    sc.tag("init globals with a volume still listed")
    sc.op(OP_INIT_GLOBALS)
    sc.op(OP_FIND, h, 0, *sc.v(0.0, 0.0, 0.0))


def script(track=None, quick=False):
    rnd = random.Random(0x9017)
    sc = Script()
    sc.op(OP_BOOT)
    tables_section(sc)
    rect_section(sc)
    rect_destroy_section(sc)
    wafer_section(sc, rnd)
    wafer_destroy_section(sc)
    if track is None:
        track = b12_track_polygons(25 if quick else 1)
    polys = track
    sc.tris = track_section(sc, polys)
    sc.npolys = len(polys)
    ks = chunk_section(sc)
    movecog_section(sc, ks)
    random_section(sc)
    tests_section(sc)
    repeat_section(sc)
    teardown_section(sc, ks)
    return sc


# ----------------------------------------------------------------- model


class Stop(Exception):
    pass


class Model(object):
    def __init__(self, sc):
        self.sc = sc
        self.out = []
        e = self.e = me.Emu(ieee=True, eediv=True)
        e.stub_bware()
        self.fn = {k: e.addr_of(v) for k, v in SYM.items()}
        self.rects = [e.alloc(RECT_SIZE, 16) for _ in range(NRECT)]
        self.wafers = [e.alloc(WAFER_SIZE, 16) for _ in range(NWAFER)]
        # what the constructors leave alone shows as 0xa5 on both sides
        for p, n in ([(r, RECT_SIZE) for r in self.rects]
                     + [(w, WAFER_SIZE) for w in self.wafers]):
            e.write(p, b"\xa5" * n)
        self.tp = e.alloc(128, 16)
        self.org = e.alloc(16, 16)
        self.cog = e.alloc(16, 16)
        self.t = e.alloc(16, 16)
        self.m = e.alloc(64, 16)
        self.chunks = [None] * NCHUNK
        self.vols = []          # [addr, chunk, index, loaded]
        self.ctx = [0, 0]
        self.allocs = []
        self.digest = None
        self.ticks = 0
        self.stop_at = 0
        self.pending = None
        emit = self.emit

        def malloc(em):
            size, pool = s32(em.reg[4]), s32(em.reg[5])
            p = em.alloc(max(size, 16), 16)
            em.mem[p:p + max(size, 16)] = bytes(max(size, 16))
            if size == RECT_SIZE:
                emit("  malloc #%d rect pool %d" % (len(self.allocs), pool))
            else:
                emit("  malloc #%d %d bytes pool %d"
                     % (len(self.allocs), size, pool))
            self.allocs.append(p)
            return p

        def free(em):
            p = em.reg[4] & M32
            emit("  free %s" % self.name_poly(p))
            if p and p in self.allocs:
                self.allocs[self.allocs.index(p)] = None
            return 0

        def delete(em):
            emit("  esp delete %d" % (em.reg[4] & M32))

        def ticker(em):
            emit("  ticker")
            if self.stop_at > 0:
                self.ticks += 1
                if self.ticks == self.stop_at:
                    raise Stop()
            return 0

        e.stub("bMalloc__Fii", malloc)
        e.stub("bFree__FPv", free)
        e.stub("espDeleteObject__FUi", delete)
        e.stub("bGetTicker__Fv", ticker)

        def wit_ctor(em):
            w, p1, p2 = (em.reg[r] & M32 for r in (4, 5, 6))
            self.ctx = [p1 if p1 and not self.registered(p1) else 0,
                        p2 if (p2 and not self.registered(p2)
                               and p2 != p1) else 0]
            emit("  witness %s %s" % (self.name_poly(p1), self.name_poly(p2)))
            if self.ctx[0]:
                self.dump_poly("p1", self.ctx[0])
            if self.ctx[1]:
                self.dump_poly("p2", self.ctx[1])

        def vclip(em):
            w = em.reg[4] & M32
            m1, t1, m2, t2 = (em.reg[r] & M32 for r in (5, 6, 7, 8))
            emit("  vclip %s %s m1%s t1%s m2%s t2%s"
                 % (self.name_poly(em.u32(w + 12)),
                    self.name_poly(em.u32(w + 16)), self.mtext(m1),
                    self.ttext(t1), self.mtext(m2), self.ttext(t2)))
            self.pending = w

        def vclip_ret(em):
            w, self.pending = self.pending, None
            if w is None:
                return
            g = em.u32
            emit("  -> %d wit ss %d f1 %s f2 %s cp1 %08x %08x %08x "
                 "cp2 %08x %08x %08x dist %08x"
                 % (s32(em.reg[2]), s32(g(w)), self.name_feature(g(w + 4)),
                    self.name_feature(g(w + 8)), fx(g(w + 32)),
                    fx(g(w + 36)), fx(g(w + 40)), fx(g(w + 48)),
                    fx(g(w + 52)), fx(g(w + 56)), fx(g(w + 64))))

        def wit_dtor(em):
            emit("  ~witness %d" % s32(em.reg[5]))

        def poly_dtor(em):
            p = em.reg[4] & M32
            emit("  ~poly %s %d" % (self.name_poly(p), s32(em.reg[5])))
            # TestCubes's heap cube is seen nowhere else
            if p and p in self.allocs:
                self.dump_poly(self.name_poly(p), p)

        e.hook(self.fn["wit_ctor"], wit_ctor)
        e.hook(self.fn["vclip"], vclip)
        for a in VCLIP_RETURNS:
            e.hook(a, vclip_ret)
        e.hook(self.fn["wit_dtor"], wit_dtor)
        e.hook(self.fn["poly_dtor"], poly_dtor)

    # ---- output

    def emit(self, line):
        if self.digest is not None:
            self.digest[0] = zlib.crc32((line + NL).encode("latin1"),
                                        self.digest[0])
        else:
            self.out.append(line)

    # ---- naming

    def registered(self, p):
        return (p in self.rects or p in self.wafers
                or any(v[0] == p for v in self.vols))

    def vol_name(self, i):
        return "V%d.%d" % (self.vols[i][1], self.vols[i][2])

    def name_poly(self, a):
        if a == 0:
            return "null"
        if a == LIST_HEAD:
            return "head"
        if self.ctx[0] and a == self.ctx[0]:
            return "p1"
        if self.ctx[1] and a == self.ctx[1]:
            return "p2"
        if a in self.rects:
            return "r%d" % self.rects.index(a)
        if a in self.wafers:
            return "w%d" % self.wafers.index(a)
        for i, v in enumerate(self.vols):
            if v[0] == a:
                return self.vol_name(i)
        for i, p in enumerate(self.allocs):
            if p is not None and p == a:
                return "#%d" % i
        return "?"

    def search_list(self):
        l = [p for p in self.ctx if p]
        l += self.rects + self.wafers
        l += [v[0] for v in self.vols if v[3]]
        return l

    def in_array(self, a, base, count, size):
        if base == 0 or count <= 0 or a < base or a >= base + count * size:
            return None
        if (a - base) % size:
            return -1
        return (a - base) // size

    def name_feature(self, a, hint=None):
        if a == 0:
            return "null"
        e = self.e
        l = self.search_list()
        if hint is not None:
            l = [hint] + l
        for p in l:
            for k, (boff, moff) in enumerate(((32, 24), (36, 26), (40, 28))):
                idx = self.in_array(a, e.u32(p + boff), s16(e.u16(p + moff)),
                                    KIND_SIZE[k])
                if idx is not None:
                    if idx < 0:
                        return "%s.%s?" % (self.name_poly(p), "vef"[k])
                    return "%s.%s%d" % (self.name_poly(p), "vef"[k], idx)
        return "?"

    def name_planes(self, p, a):
        if a == 0:
            return "null"
        idx = self.in_array(a, self.e.u32(p + 44), s16(self.e.u16(p + 30)),
                            SIZE_PL)
        if idx is not None and idx >= 0:
            return "pl%d" % idx
        return "?"

    # ---- dumps

    def dump_poly(self, label, p):
        e, emit = self.e, self.emit
        num = [s16(e.u16(p + 16 + 2 * k)) for k in range(4)]
        mx = [s16(e.u16(p + 24 + 2 * k)) for k in range(4)]
        arr = [e.u32(p + 32 + 4 * k) for k in range(4)]
        stack = p in self.ctx
        emit("  poly %s num %d %d %d %d max %d %d %d %d dyn %d obj %d arr "
             "%s link %s %s"
             % tuple([label] + num + mx
                     + [s32(e.u32(p + 8)), e.u32(p + 12),
                        "".join("1" if a else "0" for a in arr),
                        "-" if stack else self.name_poly(e.u32(p)),
                        "-" if stack else self.name_poly(e.u32(p + 4))]))
        if arr[0]:
            for k in range(num[0]):
                a = arr[0] + k * SIZE_V
                emit("  v%d t%d n%d %s pos %08x %08x %08x"
                     % (k, s8(e.mem[a]), s8(e.mem[a + 1]),
                        self.name_planes(p, e.u32(a + 16)),
                        fx(e.u32(a + 4)), fx(e.u32(a + 8)),
                        fx(e.u32(a + 12))))
        if arr[1]:
            for k in range(num[1]):
                a = arr[1] + k * SIZE_E
                emit("  e%d t%d n%d %s dir %d %d %d"
                     % (k, s8(e.mem[a]), s8(e.mem[a + 1]),
                        self.name_planes(p, e.u32(a + 8)),
                        s16(e.u16(a + 2)), s16(e.u16(a + 4)),
                        s16(e.u16(a + 6))))
        if arr[2]:
            for k in range(num[2]):
                a = arr[2] + k * SIZE_F
                emit("  f%d t%d n%d %s plane %08x %08x %08x %08x"
                     % (k, s8(e.mem[a]), s8(e.mem[a + 1]),
                        self.name_planes(p, e.u32(a + 20)),
                        fx(e.u32(a + 4)), fx(e.u32(a + 8)),
                        fx(e.u32(a + 12)), fx(e.u32(a + 16))))
        if arr[3]:
            for k in range(num[3]):
                a = arr[3] + k * SIZE_PL
                emit("  pl%d %08x %08x %08x %08x nb %s"
                     % (k, fx(e.u32(a + 4)), fx(e.u32(a + 8)),
                        fx(e.u32(a + 12)), fx(e.u32(a + 16)),
                        self.name_feature(e.u32(a + 20), hint=p)))

    def dump_vol(self, i):
        e, p = self.e, self.vols[i][0]
        if not self.vols[i][3]:
            self.emit("  vol %s not loaded" % self.vol_name(i))
            return
        name = e.read(p + 52, 32).split(b"\0")[0].decode("latin1")
        self.emit("  vol %s hash %08x name %s cog %d dummy %s"
                  % (self.vol_name(i), e.u32(p + 48), name,
                     s32(e.u32(p + 84)),
                     " ".join("%02x" % b for b in e.read(p + 88, 8))))
        self.dump_poly(self.vol_name(i), p)

    def dump_list(self):
        e = self.e
        fwd, back = [], []
        p = e.u32(LIST_HEAD)
        while p != LIST_HEAD and len(fwd) < 200:
            fwd.append(self.name_poly(p))
            p = e.u32(p)
        p = e.u32(LIST_HEAD + 4)
        while p != LIST_HEAD and len(back) < 200:
            back.append(self.name_poly(p))
            p = e.u32(p + 4)
        self.emit("  list" + "".join(" " + n for n in fwd) + " |"
                  + "".join(" " + n for n in back))

    def mtext(self, a):
        return "".join(" %08x" % fx(self.e.u32(a + 4 * k)) for k in range(16))

    def ttext(self, a):
        return "".join(" %08x" % fx(self.e.u32(a + 4 * k)) for k in range(3))

    # ---- chunks

    def put_chunk(self, k, data, mis):
        e = self.e
        base = e.alloc(len(data) + 32, 16) + mis
        e.write(base, data)
        self.chunks[k] = base
        idx = 0
        for j, (o, cid, csize) in enumerate(groups(data)):
            if j % 5 == 0:
                self.vols.append([align16(base + o + 8), k, idx, False])
                idx += 1

    # ---- the run

    def call(self, name, *args):
        # A 32-bit value lives in a register sign-extended, and the image
        # compares whole registers: FindPipelinePolyhedron's bnel against a
        # hash from lw never matches a zero-extended one.
        return self.e.call(self.fn[name], *[s32(a) for a in args])

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
            self.ctx = [0, 0]
            if code == OP_TAG:
                emit("[%d]" % arg())
            elif code == OP_TABLES:
                emit("tables")
                for name, a, n in TABLES:
                    emit("  %s %s" % (name, " ".join(
                        "%d" % s32(e.u32(a + 4 * k)) for k in range(n))))
            elif code == OP_CONSTS:
                emit("consts eps %08x deg %08x halfpi %08x counter %d"
                     % (e.u32(GP - 27804), e.u32(GP - 27800),
                        e.u32(GP - 27796), s32(e.u32(TEST_COUNTER))))
            elif code == OP_RECT:
                k = arg()
                b = args(6)
                for j in range(6):
                    e.fpr[12 + j] = b[j]
                r = self.call("rect", self.rects[k]) & M32
                emit("rect r%d -> %s" % (k, self.name_poly(r)))
                self.dump_poly("r%d" % k, self.rects[k])
            elif code == OP_CUBE:
                k = arg()
                s = fbits(arg())
                hi = bits(f32(s * 0.5))
                lo = bits(f32(-s * 0.5))
                for j, v in enumerate((hi, lo, hi, lo, hi, lo)):
                    e.fpr[12 + j] = v
                r = self.call("rect", self.rects[k]) & M32
                emit("cube r%d -> %s" % (k, self.name_poly(r)))
                self.dump_poly("r%d" % k, self.rects[k])
            elif code == OP_WAFER:
                k, dig = arg(), arg()
                ws = args(20)
                org = args(4)
                for j in range(16):
                    e.put32(self.tp + 48 + 4 * j, ws[j])
                for j in range(4):
                    e.put32(self.tp + 112 + 4 * j, ws[16 + j])
                    e.put32(self.org + 4 * j, org[j])
                self.call("wafer", self.wafers[k], self.tp, self.org)
                if dig:
                    self.digest = [0]
                    self.dump_poly("w%d" % k, self.wafers[k])
                    c, self.digest = self.digest[0], None
                    emit("wafer w%d crc %08x" % (k, c))
                else:
                    emit("wafer w%d" % k)
                    self.dump_poly("w%d" % k, self.wafers[k])
            elif code == OP_DESTROY:
                kind, k, flags = arg(), arg(), s32(arg())
                if kind == KIND_RECT:
                    emit("destroy rect r%d %d" % (k, flags))
                    self.call("d_rect", self.rects[k], flags)
                    self.dump_poly("r%d" % k, self.rects[k])
                elif kind == KIND_CUBE:
                    emit("destroy cube r%d %d" % (k, flags))
                    self.call("d_cube", self.rects[k], flags)
                    self.dump_poly("r%d" % k, self.rects[k])
                elif kind == KIND_WAFER:
                    emit("destroy wafer w%d %d" % (k, flags))
                    self.call("d_wafer", self.wafers[k], flags)
                    self.dump_poly("w%d" % k, self.wafers[k])
                else:
                    emit("destroy volume %s %d" % (self.vol_name(k), flags))
                    self.call("d_pipe", self.vols[k][0], flags)
                    self.dump_vol(k)
            elif code == OP_CHUNK:
                k, mis, n = arg(), arg(), arg()
                ws = args((n + 3) // 4)
                data = struct.pack("<%dI" % len(ws), *ws)[:n]
                self.put_chunk(k, data, mis)
                emit("chunk %d mis %d" % (k, mis))
            elif code == OP_LOAD:
                k = arg()
                r = self.call("load", self.chunks[k])
                if r:
                    for v in self.vols:
                        if v[1] == k:
                            v[3] = True
                emit("load %d -> %d" % (k, r))
                self.dump_list()
                for j, v in enumerate(self.vols):
                    if v[1] == k:
                        self.dump_vol(j)
            elif code == OP_UNLOAD:
                k = arg()
                r = self.call("unload", self.chunks[k])
                emit("unload %d -> %d" % (k, r))
                self.dump_list()
                for j, v in enumerate(self.vols):
                    if v[1] == k:
                        self.dump_vol(j)
            elif code == OP_FIND:
                h, has = arg(), arg()
                cog = args(4)
                for j in range(4):
                    e.put32(self.cog + 4 * j, cog[j])
                p = self.call("find", h, self.cog if has else 0) & M32
                emit("find %08x %s -> %s" % (h, "cog" if has else "null",
                                             self.name_poly(p)))
                at = [j for j, v in enumerate(self.vols) if v[0] == p]
                if at and has:
                    self.dump_vol(at[-1])
            elif code == OP_MOVECOG:
                k = arg()
                cog = args(4)
                for j in range(4):
                    e.put32(self.cog + 4 * j, cog[j])
                self.call("movecog", self.vols[k][0], self.cog)
                emit("movecog %s" % self.vol_name(k))
                self.dump_vol(k)
            elif code == OP_LIST:
                emit("list")
                self.dump_list()
            elif code == OP_DUMP_VOL:
                k = arg()
                emit("vol %s" % self.vol_name(k))
                self.dump_vol(k)
            elif code == OP_INIT_GLOBALS:
                self.call("gctor")
                emit("init globals")
                self.dump_list()
            elif code == OP_CLOSE_GLOBALS:
                emit("close globals")
                self.call("gdtor")
                self.dump_list()
            elif code == OP_SEED:
                e.put32(DEFAULT_SEED, arg())
            elif code == OP_RANDLOC:
                e.write(self.t, bytes(16))
                e.write(self.m, bytes(64))
                self.call("randloc", self.t, self.m)
                emit("randloc t %s m%s seed %08x"
                     % (" ".join("%08x" % fx(e.u32(self.t + 4 * k))
                                 for k in range(4)),
                        self.mtext(self.m), e.u32(DEFAULT_SEED)))
            elif code == OP_TESTCUBES:
                emit("testcubes seed %08x" % e.u32(DEFAULT_SEED))
                self.stop_at = 0
                self.call("testcubes")
                emit("  seed %08x" % e.u32(DEFAULT_SEED))
            elif code == OP_INITVC:
                counter, n = s32(arg()), s32(arg())
                e.put32(TEST_COUNTER, counter)
                emit("initvc counter %d tests %d" % (counter, n))
                self.ticks = 0
                self.stop_at = 8 * n + 1
                sp = e.reg[29]
                try:
                    self.call("initvc")
                    sys.exit("InitVoronoiClip returned")
                except Stop:
                    pass
                e.reg[29] = sp
                self.stop_at = 0
                self.pending = None
                emit("  counter %d seed %08x" % (s32(e.u32(TEST_COUNTER)),
                                                 e.u32(DEFAULT_SEED)))
            elif code == OP_REPEAT:
                last = s32(arg())
                assert 0 <= last < 0x10000
                emit("repeat last %d seed %08x" % (last,
                                                   e.u32(DEFAULT_SEED)))
                e.put32(REPEAT_LUI[0], 0x3c020000)
                e.put32(REPEAT_ORI[0], 0x34630000 | last)
                try:
                    self.call("repeat")
                finally:
                    e.put32(REPEAT_LUI[0], REPEAT_LUI[1])
                    e.put32(REPEAT_ORI[0], REPEAT_ORI[1])
                emit("  seed %08x" % e.u32(DEFAULT_SEED))
            elif code == OP_BOOT:
                self.call("gctor")
                emit("boot")
                self.dump_list()
            elif code == OP_SETOBJ:
                kind, k, o = arg(), arg(), arg()
                slot = self.wafers[k] if kind == KIND_WAFER else self.rects[k]
                e.put32(slot + 12, o)
            else:
                raise ValueError("op %d" % code)
        return self.out


def model(sc):
    m = Model(sc)
    for a, v in (REPEAT_LUI, REPEAT_ORI):
        assert m.e.u32(a) == v, "%08x" % a
    lines = m.run()
    if m.e.eediv_pcs:
        sys.exit("the model divided by zero at %s -- the ports follow IEEE "
                 "there; keep the script clear of it"
                 % " ".join("%08x" % p for p in sorted(m.e.eediv_pcs)))
    return lines


# ---------------------------------------------------------------- running

HARNESS_TIMEOUT = 300
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
                print(line)
    return bad


def build(tmp):
    return hostbuild.build(tmp, SOURCES, name="polyhedra_test", flags=FLAGS)


# -------------------------------------------------------------- mutations
#
# (name, file, old, new). Each replaces the first match, so every pattern is
# spelled to match code and not a comment.


def _m(name, old, new, rel=PH):
    return (name, rel, old, new)


def _lines(*ls):
    return NL.join(ls)


MUTATIONS = [
    # ------------------------------------------------ the tables
    _m("rect-efaces", "{ 2, 10, 6, 11 }, { 1, 9, 5, 10 },",
       "{ 2, 10, 6, 11 }, { 1, 9, 10, 5 },"),
    _m("rect-evert", "{ 0, 1, 9 }, { 4, 5, 9 },", "{ 0, 1, 9 }, { 4, 9, 5 },"),
    _m("rect-fedges", "{ 2, 0 }, { 0, 4 }, { 0, 3 },",
       "{ 0, 2 }, { 0, 4 }, { 0, 3 },"),
    _m("rect-vedges", "{ 0, 4 }, { 0, 2 }, { 2, 6 },",
       "{ 4, 0 }, { 0, 2 }, { 2, 6 },"),
    _m("wafer-efaces", "{ 0, 1, 2, 3 }, { 0, 1, 2, 3 },",
       "{ 0, 1, 2, 3 }, { 0, 1, 3, 2 },"),
    _m("wafer-evert", "{ 0, 3 }, { 0, 1 }, { 1, 2 }, { 2, 3 },",
       "{ 3, 0 }, { 0, 1 }, { 1, 2 }, { 2, 3 },"),
    _m("wafer-fedges-0", "{ 0, 1 }, { 0, 1 }, { 0, 1 }, { 1, 0 },",
       "{ 1, 0 }, { 0, 1 }, { 0, 1 }, { 1, 0 },"),
    _m("wafer-fedges-3", "{ 0, 1 }, { 0, 1 }, { 0, 1 }, { 1, 0 },",
       "{ 0, 1 }, { 0, 1 }, { 0, 1 }, { 0, 1 },"),
    _m("wafer-vedges", "{ 0, 1 }, { 1, 2 }, { 2, 3 }, { 0, 3 },",
       "{ 0, 1 }, { 1, 2 }, { 2, 3 }, { 3, 0 },"),
    _m("tri-evert", "{ 0, 2 }, { 0, 1 }, { 1, 2 }, { 0, 0 },",
       "{ 2, 0 }, { 0, 1 }, { 1, 2 }, { 0, 0 },"),
    _m("tri-evert-pad-row", "{ 0, 2 }, { 0, 1 }, { 1, 2 }, { 0, 0 },",
       "{ 0, 2 }, { 0, 1 }, { 1, 2 }, { 0, 1 },"),
    _m("tri-vedges", "{ 0, 1 }, { 1, 2 }, { 0, 2 }, { 0, 0 },",
       "{ 0, 1 }, { 1, 2 }, { 2, 0 }, { 0, 0 },"),
    _m("list-static-next",
       _lines("VCPolyhedronNode PipelinePolyhedronList = {",
              "    (VCPolyhedron *)&PipelinePolyhedronList,"),
       _lines("VCPolyhedronNode PipelinePolyhedronList = {", "    NULL,")),
    _m("counter-init", "int32_t TestCounter = 5248;",
       "int32_t TestCounter = 5247;"),
    _m("vpos-y-from-z", "r.y = v->CompressedPosition[1];",
       "r.y = v->CompressedPosition[2];"),

    # ------------------------------------------------ Rect and Cube
    _m("rect-vx-bit", "v.x = (i & 1) ? xmin : xmax;",
       "v.x = (i & 2) ? xmin : xmax;"),
    _m("rect-vz-swapped", "v.z = (i & 4) ? zmin : zmax;",
       "v.z = (i & 4) ? zmax : zmin;"),
    _m("rect-vertex-pad",
       _lines("        v.pad = 0.0f;",
              "        pl = vcpoly_new_voronoi_planes(p, 3);"),
       _lines("        v.pad = 1.0f;",
              "        pl = vcpoly_new_voronoi_planes(p, 3);")),
    _m("rect-vertex-planes", "pl = vcpoly_new_voronoi_planes(p, 3);",
       "pl = vcpoly_new_voronoi_planes(p, 4);"),
    _m("rect-vertex-nb-order",
       "pl[k].Neighbor = &p->pEdges[RectEdgesNearVertices[i][k]].Feature;",
       "pl[k].Neighbor = &p->pEdges[RectEdgesNearVertices[i][2 - k]]"
       ".Feature;"),
    _m("rect-vertex-n", "vcpoly_new_vertex(p, &v, 3, pl);",
       "vcpoly_new_vertex(p, &v, 2, pl);"),
    _m("rect-normal-sign", "(&v.x)[i / 2] = (i & 1) ? -1.0f : 1.0f;",
       "(&v.x)[i / 2] = (i & 1) ? 1.0f : -1.0f;"),
    _m("rect-normal-axis", "(&v.x)[i / 2] =", "(&v.x)[i % 3] ="),
    _m("rect-d-xmax", "case 0: d = xmax;  break;",
       "case 0: d = -xmin;  break;"),
    _m("rect-d-xmin-zero-minus", "case 1: d = -xmin; break;",
       "case 1: d = 0.0f - xmin; break;"),
    _m("rect-d-ymin-sign", "case 3: d = -ymin; break;",
       "case 3: d = ymin; break;"),
    _m("rect-d-zmax-y", "case 4: d = zmax;  break;",
       "case 4: d = ymax;  break;"),
    _m("rect-d-zmin-zero-minus", "case 5: d = -zmin; break;",
       "case 5: d = 0.0f - zmin; break;"),
    _m("rect-face-planes",
       _lines("        pl = vcpoly_new_voronoi_planes(p, 4);",
              "        for (k = 0; k < 4; k++)"),
       _lines("        pl = vcpoly_new_voronoi_planes(p, 5);",
              "        for (k = 0; k < 4; k++)")),
    _m("rect-face-nb-order",
       "&p->pEdges[RectEdgesNearFaces[i][k]].Feature;",
       "&p->pEdges[RectEdgesNearFaces[i][3 - k]].Feature;"),
    _m("rect-face-d-neg", "vcpoly_new_face(p, &v, d, 4, pl);",
       "vcpoly_new_face(p, &v, -d, 4, pl);"),
    _m("rect-face-n", "vcpoly_new_face(p, &v, d, 4, pl);",
       "vcpoly_new_face(p, &v, d, 3, pl);"),
    _m("rect-edge-planes",
       _lines("        pl = vcpoly_new_voronoi_planes(p, 4);",
              "        for (k = 0; k < 2; k++) {",
              "            pl[2 + k].Neighbor ="),
       _lines("        pl = vcpoly_new_voronoi_planes(p, 5);",
              "        for (k = 0; k < 2; k++) {",
              "            pl[2 + k].Neighbor =")),
    _m("rect-edge-face-order",
       "&p->pFaces[RectFacesNearEdges[i][k]].Feature;",
       "&p->pFaces[RectFacesNearEdges[i][1 - k]].Feature;"),
    _m("rect-edge-vert-order",
       "&p->pVertices[RectVerticesNearEdges[i][k]].Feature;",
       "&p->pVertices[RectVerticesNearEdges[i][1 - k]].Feature;"),
    _m("rect-edge-face-slot",
       _lines("            pl[2 + k].Neighbor =",
              "                &p->pFaces[RectFacesNearEdges"),
       _lines("            pl[3 - k].Neighbor =",
              "                &p->pFaces[RectFacesNearEdges")),
    _m("rect-head-tail",
       _lines("        head = vertex_pos(pl[1].Neighbor);",
              "        tail = vertex_pos(pl[0].Neighbor);"),
       _lines("        head = vertex_pos(pl[0].Neighbor);",
              "        tail = vertex_pos(pl[1].Neighbor);")),
    _m("rect-edge-x-reversed", "v.x = head.x - tail.x;",
       "v.x = tail.x - head.x;"),
    _m("rect-extent-x", "extent = xmax - xmin;", "extent = xmin - xmax;"),
    _m("rect-extent-y", "extent = ymax - ymin;", "extent = xmax - xmin;"),
    _m("rect-extent-z", "extent = zmax - zmin;", "extent = ymax - ymin;"),
    _m("rect-axis-test", "if (v.x != 0.0f)", "if (v.y != 0.0f)"),
    _m("rect-no-axis-scaled",
       _lines("        else", "            goto store;"),
       _lines("        else", "            extent = zmax - zmin;")),
    _m("rect-scale-divides", "v.x = v.x * s;", "v.x = v.x / extent;"),
    _m("rect-scale-y-lane", "v.y = v.y * s;", "v.y = v.x * s;"),
    _m("rect-no-set-voronoi",
       _lines("    vcpoly_set_voronoi_planes(p);", "    return r;"),
       "    return r;"),
    _m("cube-arg-order", "return rectpoly_init(c, hi, lo, hi, lo, hi, lo);",
       "return rectpoly_init(c, lo, hi, hi, lo, hi, lo);"),
    _m("cube-hi", "float hi = size * 0.5f;", "float hi = size * 0.25f;"),
    _m("cube-lo-zero-minus", "float lo = -size * 0.5f;",
       "float lo = 0.0f - size * 0.5f;"),
    _m("rect-destroy-flags",
       _lines("void rectpoly_destroy(RectPolyhedron *r, int32_t flags)", "{",
              "    vcpoly_destroy(&r->Poly, flags);"),
       _lines("void rectpoly_destroy(RectPolyhedron *r, int32_t flags)", "{",
              "    vcpoly_destroy(&r->Poly, flags & 2);")),
    _m("cube-destroy-flags", "rectpoly_destroy(c, flags);",
       "rectpoly_destroy(c, 3);"),

    # ------------------------------------------------ Wafer
    _m("wafer-epsilon", "WAFER_TRIANGLE_EPSILON    0.001f",
       "WAFER_TRIANGLE_EPSILON    0.0011f", PHH),
    _m("wafer-bequal-index",
       "tri = bEqual3(&tp->Vertices[2], &tp->Vertices[3],",
       "tri = bEqual3(&tp->Vertices[1], &tp->Vertices[3],"),
    _m("wafer-nv", "nv = tri ? 3 : 4;", "nv = 4;"),
    _m("wafer-ne", "ne = tri ? 3 : 4;", "ne = 4;"),
    _m("wafer-pool", "2 * nv + 4 * ne + 8", "2 * nv + 4 * ne + 9"),
    _m("wafer-faces-max", "w->FaceArray, 2,", "w->FaceArray, 3,"),
    _m("wafer-vertex-planes", "pl = vcpoly_new_voronoi_planes(p, 2);",
       "pl = vcpoly_new_voronoi_planes(p, 3);"),
    _m("wafer-vertex-tritable",
       "int32_t e = tri ? TriWaferEdgesNearVertices[i][k]",
       "int32_t e = tri ? WaferEdgesNearVertices[i][k]"),
    _m("wafer-vertex-quadtable", ": WaferEdgesNearVertices[i][k];",
       ": TriWaferEdgesNearVertices[i][k];"),
    _m("wafer-vertex-nb-order", "pl[k].Neighbor = &p->pEdges[e].Feature;",
       "pl[1 - k].Neighbor = &p->pEdges[e].Feature;"),
    _m("wafer-origin-x", "v.x = tp->Vertices[i].x - origin->x;",
       "v.x = tp->Vertices[i].x;"),
    _m("wafer-origin-z", "v.z = tp->Vertices[i].z - origin->z;",
       "v.z = tp->Vertices[i].z - origin->y;"),
    _m("wafer-vertex-pad", "v.pad = tp->Vertices[i].pad - origin->pad;",
       "v.pad = 0.0f;"),
    _m("wafer-vertex-n", "vcpoly_new_vertex(p, &v, 2, pl);",
       "vcpoly_new_vertex(p, &v, 3, pl);"),
    _m("wafer-d-corner", "v.x = tp->Vertices[0].x - origin->x;",
       "v.x = tp->Vertices[1].x - origin->x;"),
    _m("wafer-d-origin", "v.z = tp->Vertices[0].z - origin->z;",
       "v.z = tp->Vertices[0].z;"),
    _m("wafer-d-regrouped",
       "d = (tp->Normal.x * v.x + tp->Normal.y * v.y) + tp->Normal.z * v.z;",
       "d = tp->Normal.x * v.x + (tp->Normal.y * v.y + tp->Normal.z * v.z);"),
    _m("wafer-d-planedist",
       "d = (tp->Normal.x * v.x + tp->Normal.y * v.y) + tp->Normal.z * v.z;",
       "d = tp->PlaneDistance;"),
    _m("wafer-face-planes",
       _lines("        pl = vcpoly_new_voronoi_planes(p, 4);",
              "        for (k = 0; k < nf; k++)"),
       _lines("        pl = vcpoly_new_voronoi_planes(p, nf);",
              "        for (k = 0; k < nf; k++)")),
    _m("wafer-nf", "int32_t nf = tri ? 3 : 4;", "int32_t nf = 4;"),
    _m("wafer-face-nb-order",
       "&p->pEdges[WaferEdgesNearFaces[i][k]].Feature;",
       "&p->pEdges[WaferEdgesNearFaces[i][nf - 1 - k]].Feature;"),
    _m("wafer-face-row", "WaferEdgesNearFaces[i][k]",
       "WaferEdgesNearFaces[0][k]"),
    _m("wafer-n0-lane", "n.y = tp->Normal.y;", "n.y = tp->Normal.z;"),
    _m("wafer-n0-pad", "n.pad = tp->PlaneDistance;", "n.pad = 0.0f;"),
    _m("wafer-n1-pad", "n.pad = 1.0f - tp->PlaneDistance;", "n.pad = 0.0f;"),
    _m("wafer-n1-negates", "n.x = 0.0f - tp->Normal.x;",
       "n.x = -tp->Normal.x;"),
    _m("wafer-n1-z-kept", "n.z = 0.0f - tp->Normal.z;", "n.z = tp->Normal.z;"),
    _m("wafer-d1-zero-minus", "i != 0 ? -d : d", "i != 0 ? 0.0f - d : d"),
    _m("wafer-face-d-swapped", "i != 0 ? -d : d", "i == 0 ? -d : d"),
    _m("wafer-face-n", "vcpoly_new_face(p, &n, i != 0 ? -d : d, nf, pl);",
       "vcpoly_new_face(p, &n, i != 0 ? -d : d, 4, pl);"),
    _m("wafer-edge-row-tri", "WaferFacesNearEdges[tri ? i + 1 : i][k]",
       "WaferFacesNearEdges[i][k]"),
    _m("wafer-edge-row-quad", "WaferFacesNearEdges[tri ? i + 1 : i][k]",
       "WaferFacesNearEdges[tri ? i + 1 : (i + 1) & 3][k]"),
    _m("wafer-edge-tritable",
       "int32_t c = tri ? TriWaferVerticesNearEdges[i][k]",
       "int32_t c = tri ? WaferVerticesNearEdges[i][k]"),
    _m("wafer-edge-quadtable", ": WaferVerticesNearEdges[i][k];",
       ": TriWaferVerticesNearEdges[i][k];"),
    _m("wafer-edge-face-slot", "pl[2 + k].Neighbor = &p->pFaces[f].Feature;",
       "pl[3 - k].Neighbor = &p->pFaces[f].Feature;"),
    _m("wafer-head-tail",
       _lines("            pl[k].Neighbor = &p->pVertices[c].Feature;",
              "        }",
              "        head = vertex_pos(pl[1].Neighbor);"),
       _lines("            pl[k].Neighbor = &p->pVertices[c].Feature;",
              "        }",
              "        head = vertex_pos(pl[0].Neighbor);")),
    _m("wafer-len2-regrouped", "len2 = (v.x * v.x + v.y * v.y) + v.z * v.z;",
       "len2 = v.x * v.x + (v.y * v.y + v.z * v.z);"),
    _m("wafer-q-no-zero", "q = 0.0f + 1.0f / sqrtf(len2);",
       "q = 1.0f / sqrtf(len2);"),
    _m("wafer-q-double", "q = 0.0f + 1.0f / sqrtf(len2);",
       "q = 0.0f + (float)(1.0 / sqrt((double)len2));"),
    _m("wafer-scale-divides", "v.x = v.x * q;", "v.x = v.x / sqrtf(len2);"),
    _m("wafer-y-unscaled", "v.y = v.y * q;", "v.y = v.y * 1.0f;"),
    _m("wafer-z-from-y", "v.z = v.z * q;", "v.z = v.y * q;"),
    _m("wafer-no-set-voronoi",
       _lines("    vcpoly_set_voronoi_planes(p);", "}", "",
              "void waferpoly_destroy"),
       _lines("}", "", "void waferpoly_destroy")),
    _m("wafer-destroy-flags", "vcpoly_destroy(&w->Poly, flags);",
       "vcpoly_destroy(&w->Poly, 3);"),

    # ------------------------------------------------ the loader
    _m("payload-align8",
       "return (uint8_t *)(((uintptr_t)chunk + 8 + 15) & ~(uintptr_t)15);",
       "return (uint8_t *)(((uintptr_t)chunk + 8 + 7) & ~(uintptr_t)7);"),
    _m("payload-unaligned",
       "return (uint8_t *)(((uintptr_t)chunk + 8 + 15) & ~(uintptr_t)15);",
       "return chunk + 8;"),
    _m("next-chunk-no-header", "return chunk + 8 + bchunk_u32(chunk + 4);",
       "return chunk + bchunk_u32(chunk + 4);"),
    _m("records-no-pad",
       "return (int32_t)((bchunk_u32(chunk + 4) - pad) / size);",
       "return (int32_t)(bchunk_u32(chunk + 4) / size);"),
    _m("loader-id", "if (bchunk_u32(chunk) != CHUNK_COLLISION_VOLUMES)",
       "if (bchunk_u32(chunk) == 0)"),
    _m("loader-header-unaligned",
       "PipelinePolyhedron *pp = (PipelinePolyhedron *)(void *)payload16(c);",
       "PipelinePolyhedron *pp = (PipelinePolyhedron *)(void *)(c + 8);"),
    _m("loader-prepends",
       _lines("        node(p)->prev = PipelinePolyhedronList.prev;",
              "        node(PipelinePolyhedronList.prev)->next = p;",
              "        PipelinePolyhedronList.prev = p;",
              "        node(p)->next = LIST_HEAD;"),
       _lines("        node(p)->next = PipelinePolyhedronList.next;",
              "        node(PipelinePolyhedronList.next)->prev = p;",
              "        PipelinePolyhedronList.next = p;",
              "        node(p)->prev = LIST_HEAD;")),
    _m("loader-old-tail", "node(PipelinePolyhedronList.prev)->next = p;",
       "PipelinePolyhedronList.next = p;"),
    _m("loader-tail-null", "node(p)->next = LIST_HEAD;",
       "node(p)->next = NULL;"),
    _m("loader-vertex-size", "records(cv, sizeof(VCVertex)),",
       "records(cv, sizeof(VCEdge)),"),
    _m("loader-edges-from-cf",
       "(VCEdge *)(void *)payload16(ce), records(ce, sizeof(VCEdge)),",
       "(VCEdge *)(void *)payload16(ce), records(cf, sizeof(VCEdge)),"),
    _m("loader-faces-at-cp", "(VCFace *)(void *)payload16(cf),",
       "(VCFace *)(void *)payload16(cp),"),
    _m("loader-planes-short", "records(cp, sizeof(VCVoronoiPlane)));",
       "records(cp, sizeof(VCVoronoiPlane)) - 1);"),
    _m("loader-no-set-voronoi",
       _lines("        vcpoly_set_voronoi_planes(p);",
              "        c = next_chunk(cp);"),
       "        c = next_chunk(cp);"),
    _m("loader-advance-from-cf", "c = next_chunk(cp);", "c = next_chunk(cf);"),
    _m("loader-return",
       _lines("    return 1;", "}", "", "int unloader_collision_volumes"),
       _lines("    return 2;", "}", "", "int unloader_collision_volumes")),

    # ------------------------------------------------ the unloader
    _m("unloader-id",
       _lines("    if (bchunk_u32(chunk) != CHUNK_COLLISION_VOLUMES)",
              "        return 0;",
              "    end = next_chunk(chunk);",
              "    for (c = chunk + 8; c < end; c = next_chunk(c)) {"),
       _lines("    if (0)",
              "        return 0;",
              "    end = next_chunk(chunk);",
              "    for (c = chunk + 8; c < end; c = next_chunk(c)) {")),
    _m("unloader-child-id", "if (bchunk_u32(c) != CHUNK_COLLISION_VOLUME)",
       "if (bchunk_u32(c) == 0)"),
    _m("unloader-no-next-unlink",
       _lines("        node(p->Link.prev)->next = p->Link.next;",
              "        node(p->Link.next)->prev = p->Link.prev;",
              "        vcpoly_memory_image_unload(p);"),
       _lines("        node(p->Link.next)->prev = p->Link.prev;",
              "        vcpoly_memory_image_unload(p);")),
    _m("unloader-no-prev-unlink",
       _lines("        node(p->Link.next)->prev = p->Link.prev;",
              "        vcpoly_memory_image_unload(p);"),
       "        vcpoly_memory_image_unload(p);"),
    _m("unloader-no-unload", "        vcpoly_memory_image_unload(p);",
       "        (void)0;"),
    _m("unloader-return",
       _lines("    return 1;", "}", "",
              "PipelinePolyhedron *find_pipeline_polyhedron"),
       _lines("    return 0;", "}", "",
              "PipelinePolyhedron *find_pipeline_polyhedron")),

    # ------------------------------------------------ find and move
    _m("find-hash", "if (pp->NameHash != name_hash)",
       "if (pp->NameHash == name_hash)"),
    _m("find-cog-null", "if (cog != NULL && pp->CenterOfGravityFixed == 0)",
       "if (pp->CenterOfGravityFixed == 0)"),
    _m("find-fixed", "if (cog != NULL && pp->CenterOfGravityFixed == 0)",
       "if (cog != NULL)"),
    _m("find-backwards",
       "for (p = PipelinePolyhedronList.next; p != LIST_HEAD;"
       " p = p->Link.next) {",
       "for (p = PipelinePolyhedronList.prev; p != LIST_HEAD;"
       " p = p->Link.prev) {"),
    _m("cog-sign", "d.x = 0.0f - cog->x;", "d.x = cog->x;"),
    _m("cog-y-negates", "d.y = 0.0f - cog->y;", "d.y = -cog->y;"),
    _m("cog-z-lane", "d.z = 0.0f - cog->z;", "d.z = 0.0f - cog->y;"),
    _m("cog-pad", "d.pad = 1.0f - cog->pad;", "d.pad = 0.0f;"),
    _m("cog-vertex-from-1", "for (i = 0; i < p->NumVertices; i++)",
       "for (i = 1; i < p->NumVertices; i++)"),
    _m("cog-face-from-1", "for (i = 0; i < p->NumFaces; i++)",
       "for (i = 1; i < p->NumFaces; i++)"),
    _m("cog-no-set-voronoi",
       _lines("    vcpoly_set_voronoi_planes(p);",
              "    pp->CenterOfGravityFixed = 1;"),
       "    pp->CenterOfGravityFixed = 1;"),
    _m("cog-fixed-2", "pp->CenterOfGravityFixed = 1;",
       "pp->CenterOfGravityFixed = 2;"),
    _m("pipe-destroy-flags",
       _lines("void pipelinepoly_destroy(PipelinePolyhedron *p,"
              " int32_t flags)", "{",
              "    vcpoly_destroy(&p->Poly, flags);"),
       _lines("void pipelinepoly_destroy(PipelinePolyhedron *p,"
              " int32_t flags)", "{",
              "    vcpoly_destroy(&p->Poly, 3);")),

    # ------------------------------------------------ the globals
    _m("gctor-no-next",
       _lines("    PipelinePolyhedronList.prev = LIST_HEAD;",
              "    PipelinePolyhedronList.next = LIST_HEAD;"),
       "    PipelinePolyhedronList.prev = LIST_HEAD;"),
    _m("gctor-no-prev",
       _lines("    PipelinePolyhedronList.prev = LIST_HEAD;",
              "    PipelinePolyhedronList.next = LIST_HEAD;"),
       "    PipelinePolyhedronList.next = LIST_HEAD;"),
    _m("gdtor-flags", "pipelinepoly_destroy((PipelinePolyhedron *)p, 3);",
       "pipelinepoly_destroy((PipelinePolyhedron *)p, 1);"),
    _m("gdtor-no-prev-unlink",
       _lines("        node(p->Link.next)->prev = p->Link.prev;",
              "        pipelinepoly_destroy"),
       "        pipelinepoly_destroy"),
    _m("gdtor-no-next-unlink",
       _lines("        node(p->Link.prev)->next = p->Link.next;",
              "        node(p->Link.next)->prev = p->Link.prev;",
              "        pipelinepoly_destroy"),
       _lines("        node(p->Link.next)->prev = p->Link.prev;",
              "        pipelinepoly_destroy")),

    # ------------------------------------------------ TestCubes
    _m("tc-s1-range", "s1 = bRandomF(100.0f, &bDefaultSeed);",
       "s1 = bRandomF(10.0f, &bDefaultSeed);"),
    _m("tc-size-order",
       _lines("    s1 = bRandomF(100.0f, &bDefaultSeed);",
              "    s2 = bRandomF(100.0f, &bDefaultSeed);"),
       _lines("    s2 = bRandomF(100.0f, &bDefaultSeed);",
              "    s1 = bRandomF(100.0f, &bDefaultSeed);")),
    _m("tc-a1-range",
       "a1 = bRandomF(360.0f, &bDefaultSeed) * POLY_DEG_TO_RAD;",
       "a1 = bRandomF(180.0f, &bDefaultSeed) * POLY_DEG_TO_RAD;"),
    _m("tc-deg", "POLY_DEG_TO_RAD           0.017453294f",
       "POLY_DEG_TO_RAD           0.0174533f", PHH),
    _m("tc-half-pi", "POLY_HALF_PI              1.5707965f",
       "POLY_HALF_PI              1.5707964f", PHH),
    _m("tc-cos-reflected", "cos1 = bSinF(a1 + POLY_HALF_PI);",
       "cos1 = bSinF(POLY_HALF_PI - a1);"),
    _m("tc-m1-cos", "m1.v0.x = cos1;", "m1.v0.x = sin1;"),
    _m("tc-m1-neg", "m1.v1.x = -sin1;", "m1.v1.x = sin1;"),
    _m("tc-m2-row", "m2.v1.z = sin2;", "m2.v0.z = sin2;"),
    _m("tc-m2-neg", "m2.v2.y = -sin2;", "m2.v2.y = sin2;"),
    _m("tc-t1-range", "t1.x = bRandomF(200.0f, &bDefaultSeed) - 100.0f;",
       "t1.x = bRandomF(100.0f, &bDefaultSeed) - 50.0f;"),
    _m("tc-t2z-sign", "t2.z = bRandomF(200.0f, &bDefaultSeed) - 100.0f;",
       "t2.z = 100.0f - bRandomF(200.0f, &bDefaultSeed);"),
    _m("tc-t1-order",
       _lines("    t1.y = bRandomF(200.0f, &bDefaultSeed) - 100.0f;",
              "    t1.z = bRandomF(200.0f, &bDefaultSeed) - 100.0f;"),
       _lines("    t1.z = bRandomF(200.0f, &bDefaultSeed) - 100.0f;",
              "    t1.y = bRandomF(200.0f, &bDefaultSeed) - 100.0f;")),
    _m("tc-first-ticker",
       _lines("    bGetTicker();", "    cubepoly_init(&c1, s1);"),
       "    cubepoly_init(&c1, s1);"),
    _m("tc-double-ticker",
       _lines("    bGetTicker();", "    bGetTicker();", "    heap ="),
       _lines("    bGetTicker();", "    heap =")),
    _m("tc-c1-size", "cubepoly_init(&c1, s1);", "cubepoly_init(&c1, s2);"),
    _m("tc-malloc-size", "bMalloc((int)sizeof(CubePolyhedron),",
       "bMalloc((int)sizeof(CubePolyhedron) + 16,"),
    _m("tc-malloc-pool", '"CubePolyhedron", 0, 16);',
       '"CubePolyhedron", 0, 0);'),
    _m("tc-heap-size", "cubepoly_init(heap, s2);",
       "cubepoly_init(heap, s1);"),
    _m("tc-heap-null",
       _lines("    if (heap != NULL)", "        cubepoly_destroy(heap, 3);"),
       "    cubepoly_destroy(heap, 3);"),
    _m("tc-heap-flags", "cubepoly_destroy(heap, 3);",
       "cubepoly_destroy(heap, 2);"),
    _m("tc-witness-order", "vcwitness_init(&w, &c1.Poly, &c2.Poly);",
       "vcwitness_init(&w, &c2.Poly, &c1.Poly);"),
    _m("tc-shift-axis", "t1.x = t1.x + 30.0f;", "t1.y = t1.y + 30.0f;"),
    _m("tc-shift-t2", "t1.x = t1.x + 30.0f;", "t2.x = t2.x + 30.0f;"),
    _m("tc-second-vclip",
       _lines("    t1.x = t1.x + 30.0f;",
              "    vcwitness_vclip(&w, &m1, &t1, &m2, &t2);"),
       "    t1.x = t1.x + 30.0f;"),
    _m("tc-last-ticker",
       _lines("    bGetTicker();", "    vcwitness_destroy(&w, 2);"),
       "    vcwitness_destroy(&w, 2);"),
    _m("tc-witness-flags", "vcwitness_destroy(&w, 2);",
       "vcwitness_destroy(&w, 0);"),
    _m("tc-destroy-order",
       _lines("    cubepoly_destroy(&c2, 2);", "    cubepoly_destroy(&c1, 2);"),
       _lines("    cubepoly_destroy(&c1, 2);",
              "    cubepoly_destroy(&c2, 2);")),
    _m("tc-c1-flags", "cubepoly_destroy(&c1, 2);",
       "cubepoly_destroy(&c1, 0);"),

    # ------------------------------------------------ InitVoronoiClip
    _m("ivc-seed", "(uint32_t)TestCounter + 1000000u",
       "(uint32_t)TestCounter + 1000001u"),
    _m("ivc-step", "TestCounter = (int32_t)((uint32_t)TestCounter + 1u);",
       "TestCounter = (int32_t)((uint32_t)TestCounter + 2u);"),

    # ------------------------------------------------ RandomLocation
    _m("rl-row-x-range", "r->x = bRandomF(1.0f, &bDefaultSeed);",
       "r->x = bRandomF(2.0f, &bDefaultSeed);"),
    _m("rl-row-w", "r->w = 0.0f;", "r->w = 1.0f;"),
    _m("rl-row-order",
       _lines("    random_row(&m->v0);", "    random_row(&m->v1);"),
       _lines("    random_row(&m->v1);", "    random_row(&m->v0);")),
    _m("rl-v3x", "m->v3.x = 0.0f;", "m->v3.x = 1.0f;"),
    _m("rl-v3w", "m->v3.w = 1.0f;", "m->v3.w = 0.0f;"),
    _m("rl-no-orthonormalise", "eOrthonormalizeMatrix(m, m);", "(void)m;"),
    _m("rl-t-offset", "t->x = bRandomF(50.0f, &bDefaultSeed) - 25.0f;",
       "t->x = bRandomF(50.0f, &bDefaultSeed) - 20.0f;"),
    _m("rl-t-pad", "t->pad = 1.0f;", "t->pad = 0.0f;"),

    # ------------------------------------------------ TestVClipRepeatability
    _m("rep-hash", 'bchunk_hash("DIABLO_CV")', 'bchunk_hash("DIABLO")'),
    _m("rep-reroll-status", "&m1, &t1, &m2, &t2) == 2) {",
       "&m1, &t1, &m2, &t2) == 1) {"),
    _m("rep-reroll-one",
       _lines("            random_location(&t1, &m1);",
              "            random_location(&t2, &m2);",
              "        }"),
       _lines("            random_location(&t1, &m1);",
              "        }")),
    _m("rep-random-order",
       _lines("            random_location(&t3, &m3);",
              "            random_location(&t4, &m4);"),
       _lines("            random_location(&t4, &m4);",
              "            random_location(&t3, &m3);")),
    _m("rep-first-vclip-dropped",
       "            vcwitness_vclip(&w2, &m3, &t3, &m4, &t4);",
       "            (void)0;"),
    _m("rep-second-args", "vcwitness_vclip(&w2, &m1, &t1, &m2, &t2);",
       "vcwitness_vclip(&w2, &m2, &t2, &m1, &t1);"),
    _m("rep-w2-flags", "vcwitness_destroy(&w2, 2);",
       "vcwitness_destroy(&w2, 3);"),
    _m("rep-inner-twice", "} while (again-- > 0);",
       "} while (again-- >= 0);"),
    _m("rep-w-flags",
       _lines("        vcwitness_destroy(&w, 2);",
              "    } while (!(last < runs));"),
       _lines("        vcwitness_destroy(&w, 0);",
              "    } while (!(last < runs));")),
    _m("rep-outer-le", "} while (!(last < runs));",
       "} while (!(last <= runs));"),
]

EQUIVALENT = {
    "rect-no-axis-scaled":
        "only an edge whose three differences are all zero gets there, and "
        "its direction is stored as int16s: scaled by 1/0 it is NaN on the "
        "host, which ee_trunc_w stores as 0, and 0 on the EE, which has no "
        "NaN -- the flat rect and the cubes of size 0 show both",
    "rect-vertex-pad":
        "NewVertex reads the position's three lanes, not its fourth",
    "wafer-vertex-pad":
        "NewVertex reads the position's three lanes, not its fourth",
    "wafer-n0-pad":
        "NewFace reads the normal's three lanes and takes its distance "
        "apart; the fourth lane the listing writes goes nowhere",
    "wafer-n1-pad":
        "NewFace reads the normal's three lanes and takes its distance "
        "apart; the fourth lane the listing writes goes nowhere",
    "wafer-face-row":
        "WaferEdgesNearFaces's two rows are the same, so which is read "
        "cannot show; a change to either row is caught by the table dump",
    "wafer-q-no-zero":
        "the 0 + only turns a -0 into +0, and 1/sqrt is never -0: "
        "sqrt(len2) is never -inf",
    "rl-row-w":
        "eOrthonormalizeMatrix reads only the first two rows' x, y and z, "
        "and writes all sixteen lanes; the stores are dead but for the "
        "draws, which advance the seed",
    "rl-v3x":
        "eOrthonormalizeMatrix never reads the last row and writes it "
        "whole",
    "rl-v3w":
        "eOrthonormalizeMatrix never reads the last row and writes it "
        "whole",
    "cog-pad":
        "MoveVertex and MoveFace read the offset's three lanes, not its "
        "fourth",
    "tc-heap-null":
        "bMalloc never answers NULL -- bWare asserts inside the bank "
        "allocator instead -- so the test is never false",
}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name

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
                    help="every 25th of TRACKB12's polygons, not all")
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
    statuses = {}
    for line in lines:
        if line.startswith("  -> "):
            st = line.split()[1]
            statuses[st] = statuses.get(st, 0) + 1
    vols = sum(1 for line in lines if line.startswith("  vol "))
    print("%d scenarios, %d ops, %d lines, %d differ; %d TRACKB12 polygons "
          "(%d triangles); %d volume dumps; vclip statuses %s"
          % (len(sc.tags), ops, len(harness), bad, sc.npolys, sc.tris, vols,
             " ".join("%s:%d" % kv for kv in sorted(statuses.items()))))
    sys.exit(1 if (bad or rc) else 0)


if __name__ == "__main__":
    main()
