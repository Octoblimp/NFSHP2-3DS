#!/usr/bin/env python3
"""Cross-check 3DS Files/source/bchunkload.c, esolid.c and emodel.c -- the
table of 31 chunk loaders with the two walks that hand a file's chunks to
them, LoaderSolidList and its unloader, eFixUpTables, and eModel.obj's
list half -- against the image itself, run in mipsemu.

The model is the image: TraverseChunks, TraverseChunksBackwards,
LoadChunks, UnloadChunks, PostLoadFixup and HotChunksPostLoadFixup, the
image's own LoaderTable and UnloaderTable, LoaderSolidList,
UnloaderSolidList, eSolid's FixStripEntryTable, FixTextureTable and
FixLightMaterialTable, eFixUpTables, eFindSolid, and eModel's Init, UnInit,
ReconnectSolid, ReconnectTextureTable, ApplyReplacementTextureTable,
ReconnectAllModels and deleting destructor all run as shipped. The harness
runs the same op script on the port and prints the same lines.

**The seams.** What the port leaves to a function pointer the model stubs
at the same call, and both sides log it: GetTextureInfo (`gti`, which hands
out ti#0, ti#1, ... or NULL by a rule on the hash), elGetLightMaterial
(`glm`, lm#0, ...), FixStripSTs, CalcAutoK, ReconnectAllAnimations,
eLightUpdateTextures, afxUpdateTextures, FlailerPostLoadFixup and
EmptyFernFlatteners. bBreak is counted. The debugger channel
(bFunkCallASync, bRemoveCodeineInventory) is a no-op.

**The pools.** The model's bOMalloc hands out a fresh 272-byte animator
filled with 0xcd and its two `__dl__`s count what goes back; the harness
prints the port's slot pools' counts. An animator prints as va(<its first
solid>), which is the same on both sides whatever address it has.

**The layouts.** Every buffer is described op by op as the disc lays it
out, and the model builds exactly that. The host has 8-byte pointers, so
the harness rebuilds each solid-container record with the host's struct and
gives each padded child the host's pad (see loadertable_test.c). A pointer
prints as the record it points into -- s12 for solid 12, se/sd/tt/tr/lf/
ra/lm/hd for its strips, strip data, texture table, animation tree,
labelled frames, rigid animation, light materials and list header -- with
an offset in disc bytes, or as bN.cK for buffer N's K-th top-level chunk.
A disc list keeps its file offset mod 16, so every pad is the file's.

**The claims.** Every type on the disc, the guards' other constants, and
their neighbours, through each of the 62 slots. The model runs each image
loader with every other function stubbed to stop it: a loader that
returns nonzero, or gets as far as calling anything, takes the chunk. The
harness calls the port's loader on a bare chunk -- except where the image
takes the type in a slot whose object is ported, whose loader would load
it: there it prints `take` from CLAIMS below, and CLAIMS is what the model
checks. The unloaders in those slots, but Scenery's and TexturePack's, are
called, on a chunk of size 0 and a payload of 0xa5s that a loader would
fault on. An unported slot must also hand the chunk it takes to
gUnportedLoaderFn, once, with its slot and table.

Scenarios: the claims; the walks over a probe table, both ways, over
ranges, with a chunk nobody takes and the walk after it, with two takers
and with short tables; LoadChunks and UnloadChunks through the tables with
probes in them, and over TRACKB12's 497 top-level chunks claimed as the
image claims them; every solid list on the disc through the real tables,
loaded, fixed up and unloaded, with models on TRACKB12's names; slot 14's
and slot 29's chunks through the tables at each misalignment; built
lists for vertex animation (with more than 64 frames), duplicate names,
external rigid animations, labelled frames, every pad and odd sizes;
eFixUpTables under all 16 flag settings; and eModel's calls.

    python tools/loadertable_check.py
    python tools/loadertable_check.py --mutate [--only a,b]
    python tools/loadertable_check.py --dump out/loadertable
"""
import argparse
import bisect
import os
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

HARNESS = "tools/src/loadertable_test.c"
BCL = "3DS Files/source/bchunkload.c"
BCH = "3DS Files/source/bchunkload.h"
ESC = "3DS Files/source/esolid.c"
ESH = "3DS Files/source/esolid.h"
EMC = "3DS Files/source/emodel.c"
SOURCES = [HARNESS, BCL, ESC, EMC] + ["3DS Files/source/" + f for f in (
    "scenery.c", "emath.c", "bmath.c", "bmathtab.c", "bmatrix.c",
    "bvector.c", "race.c", "track.c", "terraintype.c", "cartrack.c",
    "carstate.c", "terraintypetab.c", "bslotpool.c", "bticker.c", "p32.c",
    "bchunk.c", "trackpath.c", "quickspline.c", "bmem.c", "trackroute.c",
    "polyhedra.c", "vclip.c", "espresso.c", "difficultyinfo.c",
    "texturepack.c", "sun.c", "weatherman.c")]

HARNESS_TIMEOUT = 600
EXTRACTED = ROOT / "extracted"
TRACKB12 = EXTRACTED / "TRACKS" / "TRACKB12.BUN"

# ================================================================ the image

GP = 0x00328bf0
LOADERS, UNLOADERS = 0x003081d0, 0x00308250
NSLOTS = 31
SOLIDLIST = GP - 25712
MODELLIST = GP - 25704
FLAGS = [GP - 25520, GP - 25516, GP - 25512, GP - 25508]
TI_PTRS = [GP - 25672 + 4 * i for i in range(8)]
# Slot 14's state: SunInfo and SunPosition.
SUN_INFO = GP - 24144
SUN_POS = 0x002dfdf0
SUN_CHUNK = 0x00034202
# Slot 29's state: WeatherRegionLists and WeatherRegionInactiveList, which
# the static constructor links to themselves.
WEATHER_CHUNK = 0x00034250
WEATHER_LISTS = [0x00308fe0 + 8 * i for i in range(4)] + [0x00323df8]
WEATHER_NAMES = ["W0", "W1", "W2", "W3", "Wi"]
WEATHER_CTOR = 0x0019ebd8
VA_POOL = GP - 25720

PROBE_BASE = 0x0F000000             # stub addresses, never fetched
TI_BASE = 0x10000000                # handed out, never read
LM_BASE = 0x11000000
NTI, NLM = 1 << 20, 1 << 18

SYM = dict(
    traverse="TraverseChunks__FP6bChunkT0PPFP6bChunk_ii",
    backwards="TraverseChunksBackwards__FP6bChunkT0PPFP6bChunk_ii",
    load="LoadChunks__FP6bChunki",
    unload="UnloadChunks__FP6bChunki",
    fixup="PostLoadFixup__Fv",
    hot="HotChunksPostLoadFixup__Fv",
    efix="eFixUpTables__Fv",
    lsl="LoaderSolidList__FP6bChunk",
    usl="UnloaderSolidList__FP6bChunk",
    find="eFindSolid__FUi",
    minit="Init__6eModelUi",
    muninit="UnInit__6eModel",
    mdelete="_$_6eModel",
    mrecon="ReconnectSolid__6eModel",
    mrtt="ReconnectTextureTable__6eModel",
    mapply="ApplyReplacementTextureTable__6eModel",
    mall="ReconnectAllModels__Fv",
)

# The thunks' own loaders, whose guard is the thunk's, and the topology
# tree's, which TrackGeometry's hands every type it does not know.
ALLOW = ("Loader__12TopologyTreeP6bChunk", "Unloader__12TopologyTreeP6bChunk",
         "Loader__12CameraLoaderP6bChunk", "Unloader__12CameraLoaderP6bChunk",
         "Loader__16TrackPathManagerP6bChunk",
         "Unloader__16TrackPathManagerP6bChunk",
         "Loader__15LanguageManagerP6bChunk",
         "Unloader__15LanguageManagerP6bChunk",
         "Loader__14DemoModeReplayP6bChunk",
         "Unloader__14DemoModeReplayP6bChunk")

# What each slot takes, in both tables (bchunkload.c's table).
CLAIMS = {
    0: [0x00000000],
    1: [0x00034130, 0x00034131, 0x00034132, 0x00034133, 0x00034146,
        0x00034200, 0x00034201],
    2: [0xb0300001, 0xb0300100],
    3: [0x00015010, 0x00030200],
    4: [0x80034000],
    5: [0x80034015, 0x80034019, 0x0003401c, 0x0003401e],
    6: [0x80035000, 0x80035010, 0x00035020, 0x00035021],
    7: [0x80036000],
    8: [0x00034013],
    9: [0x80034020],
    10: [0x80010200],
    11: [0x80034100, 0x00034106],
    12: [0x80034008],
    13: [0x80034405, 0x80034410, 0x80034415, 0x80034420, 0x80034425,
         0x00034492],
    14: [0x00034202],
    15: [0x80034500],
    16: [0x00034600, 0x00034601],
    17: [0x00034030],
    18: [0x00034121, 0x00034122],
    19: [0x80034147],
    20: [0x00034700],
    21: [0x00037010],
    22: [0x80038000],
    23: [0x00034300, 0x00034301],
    24: [0x00034800],
    25: [0x80034a00],
    26: [0x00034b00],
    27: [0x00039000],
    28: [0x00034026, 0x00034027],
    29: [0x00034250],
    30: [0x00039100, 0x00039101, 0x00039102],
}
TAKER = {t: k for k, ts in CLAIMS.items() for t in ts}
PORTED = {0, 1, 2, 4, 9, 11, 14, 18, 19, 26, 29}

# ---- the ops -----------------------------------------------------------------

(OP_TAG, OP_BUF, OP_LEAF, OP_BULK, OP_OPEN, OP_CLOSE, OP_BUFEND,
 OP_CLAIMS, OP_CLAIM, OP_SWAP, OP_TRAVERSE, OP_LOAD, OP_CALL, OP_FIXUP,
 OP_SET, OP_DUMP, OP_MNEW, OP_MINIT, OP_MUNINIT, OP_MDELETE, OP_MRECON,
 OP_MRTT, OP_MAPPLY, OP_MALL, OP_MPOKE, OP_MDUMP, OP_REPL, OP_RENT,
 OP_FIND, OP_MATRIX) = range(30)

ARGS = {OP_TAG: 1, OP_BUF: 1, OP_BULK: 2, OP_OPEN: 1, OP_CLOSE: 0,
        OP_BUFEND: 0, OP_CLAIMS: 0, OP_CLAIM: 3, OP_SWAP: 1,
        OP_TRAVERSE: 4, OP_LOAD: 2, OP_CALL: 2, OP_FIXUP: 1, OP_SET: 2,
        OP_DUMP: 0, OP_MNEW: 1, OP_MINIT: 2, OP_MUNINIT: 1, OP_MDELETE: 2,
        OP_MRECON: 1, OP_MRTT: 1, OP_MAPPLY: 1, OP_MALL: 0, OP_MPOKE: 3,
        OP_MDUMP: 1, OP_REPL: 2, OP_RENT: 8, OP_FIND: 1, OP_MATRIX: 4}

K_S, K_SE, K_SD, K_TT, K_TR, K_LF, K_RA, K_LM, K_HD = range(9)
KIND = ["s", "se", "sd", "tt", "tr", "lf", "ra", "lm", "hd"]
# child type -> (kind, padded, entry size)
CHILD = {0x00034003: (K_S, True, 192), 0x00034004: (K_SE, True, 64),
         0x00034005: (K_SD, True, 1), 0x00034006: (K_TT, False, 8),
         0x00034007: (K_TR, True, 1), 0x00034011: (K_LF, False, 1),
         0x00034012: (K_RA, True, 112), 0x0003401d: (K_LM, True, 8)}
BULK_TYPES = (0x00034005, 0x00034007)

SOLID_LIST, SOLID_CONTAINER, SOLID_HEADER = 0x80034000, 0x80034002, 0x00034001


def pad16(off):
    return (16 - off % 16) % 16


class Script(object):
    def __init__(self):
        self.ops = []
        self.tags = []

    def op(self, code, *args):
        assert len(args) == ARGS[code], (code, args)
        self.ops.append((code,) + tuple(int(a) for a in args))

    def tag(self, s):
        self.tags.append(s)
        self.op(OP_TAG, len(self.tags) - 1)

    def leaf(self, type_, data):
        data = bytes(data)
        n = len(data)
        padded = data + bytes(-n % 4)
        ws = struct.unpack("<%dI" % (len(padded) // 4), padded)
        self.ops.append((OP_LEAF, type_, n, len(ws)) + ws)

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


class Buf(object):
    """A buffer as the disc lays it out, op by op. `off` is where the next
    chunk goes, from the buffer's start; the start is `mis` mod 16."""

    def __init__(self, sc, mis=0):
        self.sc = sc
        self.mis = mis
        self.off = 0
        self.ntop = 0
        self.depth = 0
        sc.op(OP_BUF, mis)

    def _top(self):
        if self.depth == 0:
            self.ntop += 1

    def pad(self):
        """The pad the next leaf's payload gets."""
        return pad16(self.mis + self.off + 8)

    def leaf(self, type_, data):
        self._top()
        self.sc.leaf(type_, data)
        self.off += 8 + len(data)

    def bulk(self, type_, n):
        self._top()
        self.sc.op(OP_BULK, type_, n)
        self.off += 8 + n

    def padded(self, type_, record, extra=0):
        """A leaf whose record sits past the filler the tools put there."""
        self.leaf(type_, b"\x11" * self.pad() + bytes(record) + bytes(extra))

    def padded_bulk(self, type_, n):
        self.bulk(type_, self.pad() + n)

    def open(self, type_):
        self._top()
        self.sc.op(OP_OPEN, type_)
        self.off += 8
        self.depth += 1

    def close(self):
        self.sc.op(OP_CLOSE)
        self.depth -= 1

    def align(self, want):
        """A padding chunk, so the next chunk starts at `want` mod 16."""
        k = (want - self.mis - self.off - 8) % 16
        if (self.mis + self.off) % 16 != want % 16:
            self.bulk(0, k)

    def end(self):
        assert self.depth == 0
        self.sc.op(OP_BUFEND)
        return self.ntop


# ================================================================ records


def solid_rec(name, flags=0, nstrips=0, ext=0, nlm=0, ntex=0, va=0,
              garbage=0):
    """A disc eSolid. The pointer words are 0 unless `garbage`."""
    r = bytearray(192)
    struct.pack_into("<II", r, 0, garbage, garbage)
    struct.pack_into("<II", r, 8, name, 1)
    r[16:24] = b"solid\0\0\0"
    struct.pack_into("<II", r, 40, ext, va)
    struct.pack_into("<HHhhhh", r, 48, flags, 0, nstrips, 3, 4, 4)
    struct.pack_into("<I", r, 60, 0xdead)
    for off in (164, 168, 176, 180, 184, 188):
        struct.pack_into("<I", r, off, garbage)
    struct.pack_into("<hh", r, 172, ntex, nlm)
    struct.pack_into("<i", r, 160, -7)
    return bytes(r)


def strips_rec(offsets):
    out = bytearray()
    for i, o in enumerate(offsets):
        e = bytearray(64)
        struct.pack_into("<iHHIHH", e, 0, i, 32768, 32768, o, 2, 0)
        out += e
    return bytes(out)


def table_rec(hashes):
    return b"".join(struct.pack("<II", h, 0) for h in hashes)


def rigid_rec(name, trig=0):
    r = bytearray(112)
    struct.pack_into("<HBBII", r, 0, 5, trig, 1, name, 0)
    return bytes(r)


def header_rec(name):
    b = name.encode("latin-1")[:47]
    return b + bytes(48 - len(b)) + struct.pack("<I", 0x5a5a5a5a)


class Solid(object):
    """One container: the eSolid and the children after it, in order."""

    def __init__(self, name, flags=0, strips=(), tex=(), lm=None, ext=0,
                 rigid=None, frames=None, tree=None, data=None, extra=(),
                 order=None, nlm=None):
        self.name = name
        self.flags = flags
        self.strips = list(strips)
        self.tex = list(tex)
        self.lm = lm
        self.ext = ext
        self.rigid = rigid
        self.frames = frames
        self.tree = tree
        self.data = data if data is not None else 64 * max(1, len(strips))
        self.extra = list(extra)
        self.order = order
        self.nlm = nlm

    def emit(self, b):
        nlm = self.nlm if self.nlm is not None else len(self.lm or [])
        b.open(SOLID_CONTAINER)
        b.padded(0x00034003, solid_rec(self.name, self.flags,
                                       len(self.strips), self.ext, nlm,
                                       len(self.tex)))
        kids = self.order or ["se", "sd", "tt", "lm", "ra", "lf", "tr", "x"]
        for k in kids:
            if k == "se" and self.strips:
                b.padded(0x00034004, strips_rec(self.strips))
            elif k == "sd":
                b.padded_bulk(0x00034005, self.data)
            elif k == "tt":
                b.leaf(0x00034006, table_rec(self.tex))
            elif k == "lm" and self.lm is not None:
                b.padded(0x0003401d, table_rec(self.lm))
            elif k == "ra" and self.rigid is not None:
                b.padded(0x00034012, rigid_rec(*self.rigid))
            elif k == "lf" and self.frames is not None:
                b.leaf(0x00034011, bytes(self.frames))
            elif k == "tr" and self.tree is not None:
                b.padded_bulk(0x00034007, self.tree)
            elif k == "x":
                for t, d in self.extra:
                    b.leaf(t, d)
        b.close()


def solid_list(b, name, solids):
    b.open(SOLID_LIST)
    b.leaf(SOLID_HEADER, header_rec(name))
    for s in solids:
        s.emit(b)
    b.close()


# ================================================================ the disc


def disc_files():
    """Every extracted bundle, sorted, as (relative name, bytes)."""
    out = []
    if not EXTRACTED.is_dir():
        return out
    for dp, dn, fn in sorted(os.walk(EXTRACTED)):
        dn.sort()
        for f in sorted(fn):
            if not f.upper().endswith((".BIN", ".BUN")) or "unknown" in dp:
                continue
            p = Path(dp) / f
            out.append((p.relative_to(EXTRACTED).as_posix(), p.read_bytes()))
    return out


def top_chunks(d):
    pos = 0
    while pos + 8 <= len(d):
        t, s = struct.unpack_from("<II", d, pos)
        if pos + 8 + s > len(d):
            break
        yield t, pos, s
        pos += 8 + s


def emit_disc_list(b, d, pos, size):
    """A solid list from the file, as it is, but the bulk sent as sizes."""
    b.align(pos % 16)
    b.open(SOLID_LIST)
    c, end = pos + 8, pos + 8 + size
    while c < end:
        t, s = struct.unpack_from("<II", d, c)
        if t == SOLID_CONTAINER:
            b.open(t)
            g, ge = c + 8, c + 8 + s
            while g < ge:
                gt, gs = struct.unpack_from("<II", d, g)
                if gt in BULK_TYPES:
                    b.bulk(gt, gs)
                else:
                    b.leaf(gt, d[g + 8:g + 8 + gs])
                g += 8 + gs
            b.close()
        else:
            b.leaf(t, d[c + 8:c + 8 + s])
        c += 8 + s
    b.close()


# ================================================================ the script


def near(types):
    out = set(types)
    for t in types:
        for u in (t ^ 0x80000000, (t + 1) & M32, (t - 1) & M32, t ^ 0x100):
            out.add(u)
    return sorted(out)


def universe(files):
    ts = set(TAKER)
    for _, d in files:
        for t, _, _ in top_chunks(d):
            ts.add(t)
    ts |= {0x00000001, 0x00034001, 0x00034002, 0x80034002, 0x00034003,
           0x00034000, 0xffffffff}
    return near(sorted(ts))


def scenario_matrix(sc, files):
    sc.tag("claims")
    for table in (0, 1):
        for t in universe(files):
            for slot in range(NSLOTS):
                mode = 0
                if TAKER.get(t) != slot or slot == 0:
                    pass
                elif slot == 4:
                    mode = 2
                elif slot in PORTED:
                    # Scenery's unloader unlinks what its loader linked,
                    # and TexturePack's destroys the pack its header names,
                    # so neither is called on a chunk that was never loaded.
                    mode = 3 if table and slot not in (2, 11) else 1
                sc.op(OP_MATRIX, table, slot, t, mode)


def probe_buf(sc, types, mis=0, sizes=None):
    b = Buf(sc, mis)
    for i, t in enumerate(types):
        b.bulk(t, sizes[i] if sizes else 4 * (i % 5))
    return b.end()


def claim(sc, slot, t, ret=1):
    sc.op(OP_CLAIM, slot, t, ret)


def walks(sc, n, num=NSLOTS, ranges=None):
    for first, last in ranges or [(0, n)]:
        sc.op(OP_TRAVERSE, 0, first, last, num)
        sc.op(OP_TRAVERSE, 1, first, last, num)


def scenario_walks(sc):
    A, B, C, D, E, F, G, H = (0x1000 + i for i in range(8))
    sc.tag("walk: one taker each")
    sc.op(OP_CLAIMS)
    claim(sc, 0, 0)
    claim(sc, 3, A)
    claim(sc, 3, B)
    claim(sc, 1, C)
    claim(sc, 30, D)
    claim(sc, 2, F, 2)
    claim(sc, 5, G, -1)
    claim(sc, 17, H, 0x10000)
    ts = [A, A, B, C, A, 0, D, 0, D, C, F, G, G, H, 0, A]
    n = probe_buf(sc, ts, mis=4)
    walks(sc, n)
    walks(sc, n, ranges=[(0, 0), (3, 3), (0, 1), (5, 6), (2, 9), (9, n)])

    sc.tag("walk: nobody takes one")
    # After a chunk nobody takes, the walk is one past the slot it started
    # the chunk on, and the count is not reset: each chunk has one try.
    ts = [A, E, A, B, C, A, E, C, A, A, D, E, E, D, 0, A]
    n = probe_buf(sc, ts)
    walks(sc, n)
    ts = [C, E, B, A, A, C, C]
    n = probe_buf(sc, ts, mis=12)
    walks(sc, n)
    ts = [E, E, E]
    n = probe_buf(sc, ts)
    walks(sc, n)
    ts = [E]
    n = probe_buf(sc, ts)
    walks(sc, n)

    sc.tag("walk: two takers")
    sc.op(OP_CLAIMS)
    claim(sc, 2, A)
    claim(sc, 7, A)
    claim(sc, 7, B)
    claim(sc, 29, C)
    claim(sc, 0, C)
    claim(sc, 1, D)
    ts = [A, B, A, C, D, A, C, B, C, A]
    n = probe_buf(sc, ts, mis=8)
    walks(sc, n)

    sc.tag("walk: short tables")
    sc.op(OP_CLAIMS)
    claim(sc, 0, A)
    claim(sc, 1, B)
    claim(sc, 2, C)
    claim(sc, 6, D)
    ts = [A, B, C, D, B, A, E, C, B, A, D, A]
    n = probe_buf(sc, ts)
    for num in (1, 2, 3, 7):
        walks(sc, n, num=num)

    sc.tag("walk: through LoadChunks")
    sc.op(OP_SWAP, 1)
    sc.op(OP_CLAIMS)
    claim(sc, 0, 0)
    claim(sc, 4, A)
    claim(sc, 30, B)
    claim(sc, 12, C)
    ts = [A, 0, B, C, E, A, B, 0]
    probe_buf(sc, ts, mis=4)
    for dir_ in (0, 1):
        for mode in (0, 1, 2):
            sc.op(OP_LOAD, dir_, mode)
    sc.op(OP_SWAP, 0)


def scenario_trackb12_walk(sc):
    if not TRACKB12.is_file():
        return
    d = TRACKB12.read_bytes()
    sc.tag("TRACKB12: the walks, claimed as the image claims")
    sc.op(OP_CLAIMS)
    for t, k in sorted(TAKER.items()):
        claim(sc, k, t)
    sc.op(OP_SWAP, 1)
    b = Buf(sc, 0)
    for t, pos, s in top_chunks(d):
        b.bulk(t, s)
    b.end()
    sc.op(OP_LOAD, 0, 0)
    sc.op(OP_LOAD, 1, 0)
    sc.op(OP_SWAP, 0)


def scenario_disc_lists(sc, files):
    names = {}
    for rel, d in files:
        lists = [(pos, s) for t, pos, s in top_chunks(d) if t == SOLID_LIST]
        if not lists:
            continue
        sc.tag("disc: " + rel)
        if rel == "TRACKS/TRACKB12.BUN":
            # Models on some of the track's names, one missing, one twice.
            # Most of the track's lists are a header alone.
            hs = []
            full = [(pos, s) for pos, s in lists if s > 60]
            for pos, s in full:
                c = pos + 8
                c += 8 + struct.unpack_from("<I", d, c + 4)[0]
                g = c + 8
                off = g + 8 + pad16(g + 8)
                hs.append(struct.unpack_from("<I", d, off + 8)[0])
            hs += [0x12345678, hs[0]]
            for i, h in enumerate(hs):
                sc.op(OP_MNEW, 100 + i)
                sc.op(OP_MINIT, 100 + i, h)
            names["b12"] = len(hs)
        b = Buf(sc, lists[0][0] % 16)
        for pos, s in lists:
            emit_disc_list(b, d, pos, s)
        b.end()
        sc.op(OP_LOAD, 0, 0)
        sc.op(OP_FIXUP, 1)
        sc.op(OP_DUMP)
        sc.op(OP_LOAD, 1, 0)
        sc.op(OP_FIXUP, 1)
        sc.op(OP_DUMP)
        if rel == "TRACKS/TRACKB12.BUN":
            for i in range(names["b12"]):
                sc.op(OP_MDELETE, 100 + i, 3)
            sc.op(OP_DUMP)


def scenario_sun(sc, files):
    """Slot 14 through both tables: TRACKB12's own SunChunkInfoE behind the
    filler its place needs, at each misalignment; the disc's payload as it
    is, whose filler is wrong away from the disc's place; and the record at
    version 1. The dump shows SunInfo and SunPosition, so an unloader that
    loads again leaves them set."""
    d = dict(files).get("TRACKS/TRACKB12.BUN")
    if d is None:
        return
    suns = [(pos, s) for t, pos, s in top_chunks(d) if t == SUN_CHUNK]
    if not suns:
        return
    pos, size = suns[0]
    data = d[pos + 8:pos + 8 + size]
    k = pad16(pos + 8)
    rec = data[k:k + 244]
    bad = struct.pack("<I", 1) + rec[4:]
    for mis in (0, 4, 8, 12):
        sc.tag("sun: through the tables, misaligned %d" % mis)
        b = Buf(sc, mis)
        b.padded(SUN_CHUNK, rec)
        b.end()
        sc.op(OP_LOAD, 0, 0)
        sc.op(OP_DUMP)
        sc.op(OP_LOAD, 1, 0)
        sc.op(OP_DUMP)
    sc.tag("sun: the disc's payload, then version 1")
    b = Buf(sc, (pos + 4) % 16)
    b.leaf(SUN_CHUNK, data)
    b.padded(SUN_CHUNK, bad)
    b.end()
    sc.op(OP_LOAD, 0, 0)
    sc.op(OP_DUMP)
    sc.op(OP_LOAD, 1, 0)
    sc.op(OP_DUMP)


def scenario_weather(sc):
    """Slot 29 through both tables, at each misalignment: a pack of one fog
    region, then one of another version, whose regions are not read. The
    host's WeatherRegion is 136 bytes, with its Type at 88, so the one
    region has its type at both offsets, and the pack ends with it. The
    dump shows the lists' heads, so a loader that links nothing, or an
    unloader that links again, shows."""
    for mis in (0, 4, 8, 12):
        sc.tag("weather: through the tables, misaligned %d" % mis)
        rec = bytearray(16 + 136)
        struct.pack_into("<ii", rec, 8, 2, 1)
        struct.pack_into("<i", rec, 16 + 80, 1)
        struct.pack_into("<i", rec, 16 + 88, 1)
        other = bytearray(16)
        struct.pack_into("<ii", other, 8, 1, 3)
        b = Buf(sc, mis)
        b.padded(WEATHER_CHUNK, rec)
        b.padded(WEATHER_CHUNK, other)
        b.end()
        sc.op(OP_LOAD, 0, 0)
        sc.op(OP_DUMP)
        sc.op(OP_LOAD, 1, 0)
        sc.op(OP_DUMP)


X, Y, Z, W, Q, V = 0xaaaa0001, 0xbbbb0002, 0xcccc0003, 0xdddd0004, \
    0xeeee0005, 0xffff0006


def scenario_vertex(sc):
    sc.tag("vertex animation: two lists")
    b = Buf(sc, 0)
    solid_list(b, "anim_a.bin", [
        Solid(X, 0x10, strips=[0, 16], tex=[0x100, 0x101], rigid=(X, 0)),
        Solid(X, 0x10, strips=[0], tex=[0x102]),
        Solid(X, 0x10, tex=[0x103], rigid=(X + 1, 1)),
        Solid(Y, 0, tex=[0x104, 0x105, 0x106], lm=[0x200, 0x201]),
        Solid(Y, 0x04, tex=[0x107]),
        Solid(W, 0, ext=X, tex=[]),
        Solid(W + 1, 0, ext=0x9999, rigid=(W + 1, 0)),
        Solid(W + 2, 0, ext=W + 1),
    ])
    solid_list(b, "anim_b.bin", [
        Solid(X, 0x10, tex=[0x108]),
        Solid(Z, 0x10, tex=[0x109], rigid=(Z, 0)),
        Solid(Z, 0x10),
        Solid(Y, 0),
    ])
    b.end()
    for i, h in enumerate((X, Y, Z, W, 0x4242)):
        sc.op(OP_MNEW, i)
        sc.op(OP_MINIT, i, h)
    sc.op(OP_DUMP)
    sc.op(OP_CALL, 0, 0)
    sc.op(OP_DUMP)
    sc.op(OP_CALL, 0, 1)
    sc.op(OP_DUMP)
    sc.op(OP_FIXUP, 0)
    sc.op(OP_DUMP)
    sc.op(OP_CALL, 1, 1)
    sc.op(OP_DUMP)
    sc.op(OP_FIXUP, 0)
    sc.op(OP_DUMP)
    sc.op(OP_CALL, 1, 0)
    sc.op(OP_FIXUP, 0)
    sc.op(OP_DUMP)

    sc.tag("vertex animation: through the tables")
    b = Buf(sc, 4)
    b.bulk(0, 4)
    solid_list(b, "t1.bin", [Solid(V, 0x10, tex=[0x400]),
                             Solid(V, 0x10, tex=[0x401])])
    b.bulk(0, 0)
    solid_list(b, "t2.bin", [Solid(V, 0x10), Solid(V + 1, 0)])
    solid_list(b, "t3.bin", [Solid(V + 1, 0)])
    # Last: the walk skips every chunk after one nobody takes until one is
    # taken at the first try, and unloading a list that was skipped would
    # unlink solids that were never linked.
    b.bulk(0x00000001, 12)
    b.end()
    sc.op(OP_LOAD, 0, 0)
    sc.op(OP_FIXUP, 2)
    sc.op(OP_DUMP)
    sc.op(OP_LOAD, 1, 0)
    sc.op(OP_FIXUP, 1)
    sc.op(OP_DUMP)
    for i in range(5):
        sc.op(OP_MDELETE, i, 3)
    sc.op(OP_DUMP)


def scenario_layout(sc):
    for mis in (0, 4, 8, 12):
        sc.tag("layout: misaligned %d" % mis)
        b = Buf(sc, mis)
        sols = []
        for k in range(6):
            sols.append(Solid(0x5000 + k, 0,
                              strips=[16 * j + k for j in range(k + 1)],
                              tex=[0x500 + j for j in range(k)],
                              lm=[0x600 + j for j in range(k % 3)],
                              # Odd k: one short of a node more once the
                              # filler is counted in.
                              tree=96 * k + (92 if k % 2 else k * 20 % 96),
                              data=100 + 36 * k,
                              extra=[(0x00034099, b"\x01" * (4 * k)),
                                     (0x00034013, b"")]))
        # Children in another order: the table before the strips, the
        # labelled frames after their animation, the strip data first.
        sols.append(Solid(0x5100, 0, strips=[], tex=[0x700], data=0,
                          order=["sd", "tt", "se", "x"]))
        sols.append(Solid(0x5101, 0, strips=[8, 0x40], tex=[0x701, 0x702],
                          rigid=(0x5101, 0), frames=b"\x07" * 12,
                          order=["tt", "ra", "lf", "se", "sd", "tr"]))
        sols.append(Solid(0x5102, 0, tex=[0x703], lm=[], nlm=0,
                          extra=[(0x00034006, table_rec([0x704, 0x705])
                                  + b"\x00" * 4)]))
        sols.append(Solid(0x5103, 0, tex=[], tree=40))
        # After an animation the frames' payload is 16-aligned on the host
        # as well as off it; a leaf of one word between them is not.
        sols.append(Solid(0x5104, 0, tex=[0x706], rigid=(0x5104, 1),
                          frames=b"\x05" * 20,
                          extra=[(0x00034099, b"\x02" * 4)],
                          order=["ra", "x", "lf", "tt"]))
        solid_list(b, "layout%d.bin" % mis, sols)
        solid_list(b, "empty%d.bin" % mis, [])
        b.bulk(0x00034003, 8)
        b.end()
        sc.op(OP_CALL, 0, 0)
        sc.op(OP_CALL, 0, 1)
        sc.op(OP_CALL, 0, 2)
        sc.op(OP_CALL, 1, 2)
        sc.op(OP_DUMP)
        sc.op(OP_CALL, 1, 1)
        sc.op(OP_CALL, 1, 0)
        sc.op(OP_DUMP)

    sc.tag("layout: duplicates and finds")
    b = Buf(sc, 0)
    solid_list(b, "dups.bin", [Solid(0x6000, 0, tex=[1]),
                               Solid(0x6001, 0x0100, tex=[2]),
                               Solid(0x6000, 0x0004, tex=[3]),
                               Solid(0x6000, 0, tex=[4]),
                               Solid(0x6003, 0x10, tex=[5]),
                               Solid(0x6003, 0x12, tex=[7]),
                               Solid(0, 0, tex=[6])])
    b.end()
    sc.op(OP_CALL, 0, 0)
    sc.op(OP_DUMP)
    for h in (0x6000, 0x6001, 0, 0x6002, 0x6003):
        sc.op(OP_FIND, h)
    sc.op(OP_CALL, 1, 0)
    sc.op(OP_DUMP)


def scenario_fixup(sc):
    b = Buf(sc, 0)
    solid_list(b, "fix.bin", [Solid(0x7000, 0, strips=[0], tex=[0x800, 0x801],
                                    rigid=(0x7000, 0)),
                              Solid(0x7001, 0, tex=[0x802], lm=[0x803]),
                              Solid(0x7002, 0, tex=[])])
    b.end()
    sc.tag("fixup: setup")
    sc.op(OP_CALL, 0, 0)
    for i, h in enumerate((0x7000, 0x7001, 0x7003)):
        sc.op(OP_MNEW, 10 + i)
        sc.op(OP_MINIT, 10 + i, h)
    sc.op(OP_REPL, 10, 2)
    sc.op(OP_RENT, 10, 0, 0x801, 0x900, 0x03020100, 0x07060504,
          0x0b0a0908, 0x0f0e0d0c)
    sc.op(OP_RENT, 10, 1, 0x8ff, 0x901, -1, -1, -1, -1)
    sc.op(OP_MPOKE, 10, 2, 10)
    sc.op(OP_MPOKE, 10, 3, 2)
    sc.op(OP_MPOKE, 10, 4, 5)
    sc.op(OP_DUMP)
    for f in range(16):
        sc.tag("fixup: flags %d%d%d%d" % (f >> 3 & 1, f >> 2 & 1, f >> 1 & 1,
                                          f & 1))
        for var in range(4):
            sc.op(OP_SET, var, (f >> (3 - var)) & 1)
        sc.op(OP_FIXUP, 0)
        sc.op(OP_DUMP)
    sc.tag("fixup: nonzero flags")
    for var, v in ((1, 2), (2, -1), (3, 0x100)):
        sc.op(OP_SET, var, v)
        sc.op(OP_FIXUP, 0)
        sc.op(OP_DUMP)
    sc.op(OP_SET, 0, 7)
    sc.op(OP_SET, 2, 1)
    sc.op(OP_FIXUP, 1)
    sc.op(OP_DUMP)
    sc.op(OP_SET, 0, 0)
    sc.op(OP_FIXUP, 2)
    sc.op(OP_DUMP)
    # UnInit while the solid is still there, with a start time to clear.
    sc.tag("fixup: uninit")
    sc.op(OP_MUNINIT, 10)
    sc.op(OP_MDUMP, 10)
    sc.op(OP_CALL, 1, 0)
    sc.op(OP_FIXUP, 0)
    sc.op(OP_DUMP)
    for i in range(3):
        sc.op(OP_MDELETE, 10 + i, 1)
    sc.op(OP_DUMP)


def scenario_frames(sc):
    # Past 64 frames a solid joins its animator without being in its
    # table, so unloading the list would free the animator once for each
    # frame past 64: the list stays, and nothing dumps after it.
    sc.tag("vertex animation: 66 frames")
    b = Buf(sc, 8)
    solid_list(b, "frames.bin", [Solid(Q, 0x10 | (i & 3), tex=[0x300 + i])
                                 for i in range(66)])
    b.end()
    sc.op(OP_CALL, 0, 0)
    sc.op(OP_DUMP)


def scenario_models(sc):
    b = Buf(sc, 4)
    solid_list(b, "models.bin", [
        Solid(0x8000, 0, tex=[0xa0, 0xa1, 0xa2, 0xa1], rigid=(0x8000, 0)),
        Solid(0x8001, 0, tex=[0xb0], rigid=(0x8001, 3)),
        Solid(0x8002, 0, tex=[]),
        Solid(0x8003, 0, tex=[0xc0, 0xc1]),
    ])
    b.end()
    sc.tag("models: before their solids")
    for i, h in enumerate((0x8000, 0x8001, 0x8002, 0, 0x8003, 0x8004)):
        sc.op(OP_MNEW, 20 + i)
        sc.op(OP_MINIT, 20 + i, h)
    sc.op(OP_DUMP)
    sc.op(OP_MDUMP, 23)
    sc.tag("models: the solids come")
    sc.op(OP_CALL, 0, 0)
    for i in range(6):
        sc.op(OP_MRECON, 20 + i)
    sc.op(OP_DUMP)
    sc.op(OP_MDUMP, 23)

    sc.tag("models: reconnect keeps what has not changed")
    sc.op(OP_MPOKE, 20, 5, 77)
    sc.op(OP_MPOKE, 21, 5, -3)
    sc.op(OP_MRECON, 20)
    sc.op(OP_MRECON, 21)
    sc.op(OP_MDUMP, 20)
    sc.op(OP_MDUMP, 21)
    sc.op(OP_MPOKE, 20, 1, -1)
    sc.op(OP_MRECON, 20)
    sc.op(OP_MDUMP, 20)
    sc.op(OP_MPOKE, 22, 0, 0x8000)
    sc.op(OP_MPOKE, 22, 5, 9)
    sc.op(OP_MRECON, 22)
    sc.op(OP_MDUMP, 22)
    sc.op(OP_MPOKE, 22, 0, 0x8009)
    sc.op(OP_MPOKE, 22, 5, 9)
    sc.op(OP_MRECON, 22)
    sc.op(OP_MDUMP, 22)
    sc.op(OP_MPOKE, 22, 0, 0)
    sc.op(OP_MPOKE, 22, 1, 0)
    sc.op(OP_MRECON, 22)
    sc.op(OP_MDUMP, 22)

    sc.tag("models: replacement textures")
    sc.op(OP_REPL, 0, 5)
    sc.op(OP_RENT, 0, 0, 0xa1, 0xd0, -1, -1, 0x7f000000, 0x11223344)
    sc.op(OP_RENT, 0, 1, 0xa9, 0xd1, 0, 0, 0, 0)
    sc.op(OP_RENT, 0, 2, 0xa0, 0xd2, 0x01010101, 0x02020202, 0x03030303,
          0x04040404)
    sc.op(OP_RENT, 0, 3, 0xa1, 0xd3, 0, -1, 0, -1)
    sc.op(OP_RENT, 0, 4, 0xa2, 0xd4, 0x05050505, 0, 0, 0)
    sc.op(OP_MPOKE, 20, 1, -1)
    sc.op(OP_MRECON, 20)
    sc.op(OP_MPOKE, 20, 2, 0)
    for inst in (3, 0, 15, 7):
        for n in (4, 5):
            sc.op(OP_MPOKE, 20, 4, inst)
            sc.op(OP_MPOKE, 20, 3, n)
            sc.op(OP_MRTT, 20)
            sc.op(OP_MDUMP, 20)
            sc.op(OP_DUMP)
    sc.op(OP_RENT, 0, 0, 0xa1, 0xd0, 0x02020202, 0x02020202, 0x02020202,
          0x02020202)
    sc.op(OP_MAPPLY, 20)
    sc.op(OP_DUMP)
    sc.op(OP_RENT, 0, 1, 0xa9, 0xd1, 0x03030303, 0x03030303, 0x03030303,
          0x03030303)
    sc.op(OP_MAPPLY, 20)
    sc.op(OP_DUMP)
    for n in (0, 0xc8, 0x80, 1):
        sc.op(OP_MPOKE, 20, 3, n)
        sc.op(OP_MRTT, 20)
        sc.op(OP_MAPPLY, 20)
        sc.op(OP_MDUMP, 20)
    sc.tag("models: replacements without a solid")
    sc.op(OP_REPL, 1, 2)
    sc.op(OP_RENT, 1, 0, 0xa1, 0xe0, 0x01010101, 0x01010101, 0x01010101,
          0x01010101)
    sc.op(OP_RENT, 1, 1, 0xa0, 0xe3, 0, 0, 0, 0)
    sc.op(OP_MPOKE, 25, 2, 1)
    sc.op(OP_MPOKE, 25, 3, 2)
    sc.op(OP_MPOKE, 25, 4, 2)
    sc.op(OP_MRTT, 25)
    sc.op(OP_MAPPLY, 25)
    sc.op(OP_MDUMP, 25)
    sc.tag("models: all of them")
    sc.op(OP_MPOKE, 21, 2, 1)
    sc.op(OP_MPOKE, 21, 3, 2)
    sc.op(OP_MPOKE, 21, 4, 9)
    sc.op(OP_MALL)
    sc.op(OP_DUMP)
    sc.op(OP_CALL, 1, 0)
    sc.op(OP_MALL)
    sc.op(OP_DUMP)

    sc.tag("models: off the list")
    sc.op(OP_MUNINIT, 23)
    sc.op(OP_MDUMP, 23)
    sc.op(OP_MUNINIT, 21)
    sc.op(OP_MDUMP, 21)
    sc.op(OP_DUMP)
    sc.op(OP_MDELETE, 22, 0)
    sc.op(OP_MDELETE, 24, 2)
    sc.op(OP_DUMP)
    sc.op(OP_MDELETE, 20, 1)
    sc.op(OP_MDELETE, 25, 3)
    sc.op(OP_MDELETE, 21, 3)
    sc.op(OP_MDELETE, 23, 1)
    sc.op(OP_DUMP)
    sc.op(OP_MNEW, 30)
    sc.op(OP_MINIT, 30, 0)
    sc.op(OP_MDUMP, 30)
    sc.op(OP_MDELETE, 30, 1)
    sc.op(OP_DUMP)


def script(files=None):
    if files is None:
        files = disc_files()
    sc = Script()
    sc.tag("start")
    for var in range(4):
        sc.op(OP_SET, var, 0)
    sc.op(OP_DUMP)
    scenario_walks(sc)
    scenario_vertex(sc)
    scenario_layout(sc)
    scenario_fixup(sc)
    scenario_models(sc)
    scenario_disc_lists(sc, files)
    scenario_sun(sc, files)
    scenario_weather(sc)
    scenario_frames(sc)
    scenario_trackb12_walk(sc)
    scenario_matrix(sc, files)
    return sc


# ================================================================ the model


class Past(Exception):
    pass


class Model(object):
    def __init__(self, sc, files):
        self.sc = sc
        self.files = files
        self.out = []
        e = self.e = Emu(ieee=True)
        e.stub_bware()
        e.call(WEATHER_CTOR, limit=1000)
        self.fn = {k: e.addr_of(v) for k, v in SYM.items()}
        self.recs = []          # sorted (start, size, kind, idx)
        self.rec_starts = []
        self.tops = []
        self.top_starts = []
        self.bufs = []          # (p, len, [chunk addresses])
        self.cur = None
        self.solid_by_idx = {}
        self.kind_count = [0] * len(KIND)
        self.models = {}
        self.repl = {}
        self.vas = set()
        self.nti = self.nlm = 0
        self.va_count = 0
        self.model_count = 0
        self.breaks = self.breaks_seen = 0
        self.claims = {}
        self.saved = None
        self.m = None
        for head in (SOLIDLIST, MODELLIST):
            e.put32(head, head)
            e.put32(head + 4, head)
        self.probe_table = e.alloc(4 * NSLOTS, 16)
        for k in range(NSLOTS):
            e.put32(self.probe_table + 4 * k, PROBE_BASE + 8 * k)
            e.stubs[PROBE_BASE + 8 * k] = self._probe(k)
        self.stubs()

    def emit(self, s):
        self.out.append(s)

    # ---- the labels ------------------------------------------------------

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        i = bisect.bisect_right(self.rec_starts, a) - 1
        if i >= 0:
            p, size, kind, idx = self.recs[i]
            if a < p + size or (size == 0 and a == p):
                if a == p:
                    return "%s%d" % (KIND[kind], idx)
                return "%s%d+%d" % (KIND[kind], idx, a - p)
        i = bisect.bisect_right(self.top_starts, a) - 1
        if i >= 0:
            p, size, buf, idx = self.tops[i]
            if a < p + size or (size == 0 and a == p):
                if a == p:
                    return "b%d.c%d" % (buf, idx)
                return "b%d.c%d+%d" % (buf, idx, a - p)
        for i in range(len(self.bufs) - 1, -1, -1):
            if a == self.bufs[i][0] + self.bufs[i][1]:
                return "b%d.end" % i
        if a == SOLIDLIST:
            return "SL"
        if a == MODELLIST:
            return "ML"
        if a in WEATHER_LISTS:
            return WEATHER_NAMES[WEATHER_LISTS.index(a)]
        for i in sorted(self.models, reverse=True):
            if a == self.models[i]:
                return "m%d" % i
        for i in sorted(self.repl, reverse=True):
            p, n = self.repl[i]
            if p <= a < p + 28 * n:
                return "r%d" % i if a == p else "r%d+%d" % (i, a - p)
        if TI_BASE <= a < TI_BASE + NTI:
            return "ti#%d" % (a - TI_BASE)
        if LM_BASE <= a < LM_BASE + NLM:
            return "lm#%d" % (a - LM_BASE)
        if a in self.vas:
            return "va(%s)" % self.label(self.e.u32(a + 16))
        return "?"

    def add_rec(self, p, size, kind):
        r = (p, size, kind, self.kind_count[kind])
        if kind == K_S:
            self.solid_by_idx[self.kind_count[kind]] = p
        self.kind_count[kind] += 1
        i = bisect.bisect_right(self.rec_starts, p)
        self.rec_starts.insert(i, p)
        self.recs.insert(i, r)

    # ---- the stubs -------------------------------------------------------

    def stubs(self):
        e = self.e

        def arg(i):
            return e.reg[4 + i] & M32

        def gti(em):
            h, use = arg(0), s32(arg(1))
            if h == 0 or h % 7 == 3 or (not use and h % 3 == 0):
                r = 0
            else:
                r = TI_BASE + self.nti
                self.nti += 1
            self.emit("  gti %08x %d %s" % (h, use, self.label(r)))
            return r

        def glm(em):
            h = arg(0)
            if h % 5 != 2:
                r = LM_BASE + self.nlm
                self.nlm += 1
            else:
                r = 0
            self.emit("  glm %08x %s" % (h, self.label(r)))
            return r

        def log(what, with_arg=False):
            def f(em):
                if with_arg:
                    self.emit("  %s %s" % (what, self.label(arg(0))))
                else:
                    self.emit("  " + what)
                return 0
            return f

        def brk(em):
            self.breaks += 1

        def omalloc(em):
            p = e.alloc(272, 16)
            e.mem[p:p + 272] = b"\xcd" * 272
            self.vas.add(p)
            self.va_count += 1
            return p

        def va_free(em):
            self.va_count -= 1

        def model_free(em):
            self.model_count -= 1

        e.stub("GetTextureInfo__FUii", gti)
        e.stub("elGetLightMaterial__FUi", glm)
        e.stub("FixStripSTs__6eSolid", log("fixsts", True))
        e.stub("CalcAutoK__6eSolid", log("autok", True))
        e.stub("ReconnectAllAnimations__Fv", log("rcanim"))
        e.stub("eLightUpdateTextures__Fv", log("lightupd"))
        e.stub("afxUpdateTextures__Fv", log("afxupd"))
        e.stub("FlailerPostLoadFixup__Fv", log("flailfix"))
        e.stub("EmptyFernFlatteners__Fv", log("fern"))
        e.stub("bBreak__Fv", brk)
        e.stub("bFunkCallASync__FPCcUcPCvl", lambda em: 0)
        e.stub("bRemoveCodeineInventory__Fi", lambda em: 0)
        e.stub("bOMalloc__FP8SlotPool", omalloc)
        e.stub("__dl__15eVertexAnimatorPv", va_free)
        e.stub("__dl__6eModelPv", model_free)

    def _probe(self, k):
        def f(em):
            c = self.e.reg[4] & M32
            self.emit("  try %d %s" % (k, self.label(c)))
            return self.claims.get((k, self.e.u32(c)), 0) & M32
        return f

    # ---- the buffers -----------------------------------------------------

    def buf_begin(self, mis):
        self.stage = bytearray()
        self.mis = mis
        self.stack = []
        self.top_off = []
        self.pend = []

    def begin_chunk(self):
        if not self.stack:
            self.top_off.append(len(self.stage))

    def leaf(self, t, data):
        parent = self.stack[-1][1] if self.stack else 0
        self.begin_chunk()
        pay = len(self.stage) + 8
        n = len(data)
        if parent == SOLID_CONTAINER and t in CHILD:
            kind, padded, esz = CHILD[t]
            dp = pad16(self.mis + pay) if padded else 0
            content = n - dp
            if kind in (K_S, K_RA):
                size = esz
            else:
                size = content // esz * esz
            self.pend.append((pay + dp, size, kind))
        elif parent == SOLID_LIST and t == SOLID_HEADER:
            self.pend.append((pay, n, K_HD))
        self.stage += struct.pack("<II", t, n) + bytes(data)

    def buf_end(self):
        e = self.e
        n = len(self.stage)
        raw = e.alloc(n + 64, 16)
        p = raw + self.mis
        e.mem[p:p + n] = self.stage
        e.mem[p + n:p + n + 32] = bytes(32)
        bi = len(self.bufs)
        chunks = [p + o for o in self.top_off]
        for i, o in enumerate(self.top_off):
            end = self.top_off[i + 1] if i + 1 < len(self.top_off) else n
            r = (p + o, end - o, bi, i)
            j = bisect.bisect_right(self.top_starts, p + o)
            self.top_starts.insert(j, p + o)
            self.tops.insert(j, r)
        for off, size, kind in self.pend:
            self.add_rec(p + off, size, kind)
        self.bufs.append((p, n, chunks))
        self.cur = self.bufs[-1]

    def chunk_ptr(self, i):
        p, n, chunks = self.cur
        return p + n if i == len(chunks) else chunks[i]

    # ---- the matrix ------------------------------------------------------

    def matrix_emu(self):
        if self.m is not None:
            return self.m
        m = Emu(ieee=True)
        allow = {m.addr_of(s) for s in ALLOW}

        def stop(em):
            raise Past()

        base = {}
        for name, (a, size) in m.elf.syms.items():
            if size > 0 and 0x00100000 <= a < 0x0028e0d0 and a not in allow:
                base[a] = stop
        m.stubs = base
        self.m = m
        self.samples = {}
        for _, d in self.files:
            for t, pos, s in top_chunks(d):
                if t not in self.samples or s < len(self.samples[t]) - 8:
                    self.samples[t] = d[pos:pos + 8 + s]
        return m

    def matrix(self, table, slot, t, mode):
        m = self.matrix_emu()
        fn = m.u32((UNLOADERS if table else LOADERS) + 4 * slot)
        if mode == 2:
            data = (struct.pack("<IIII", SOLID_LIST, 60, SOLID_HEADER, 52)
                    + header_rec("matrix"))
        else:
            data = self.samples.get(t, struct.pack("<II", t, 0))
        saved = m.stubs.pop(fn, None)
        m.reset_heap()
        p = m.alloc(len(data) + 256, 16)
        m.mem[p:p + len(data) + 256] = data + bytes(256)
        m.reg[29] = m.RAM - 0x10000
        try:
            r = "take" if m.call(fn, p, limit=200000) else "no"
        except Past:
            r = "take"
        except Exception:
            # Three loaders get past their guard and then walk the chunk
            # with nothing stubbed to stop them: Smokeables' loader and
            # Language's unloader loop, and TrackGeometry's unloader
            # writes through a pointer the chunk has not had fixed. That is
            # a take where CLAIMS has one, and a fault anywhere else.
            r = "take" if TAKER.get(t) == slot else "fault"
        finally:
            if saved is not None:
                m.stubs[fn] = saved
        self.emit("  m %d %d %08x %s" % (table, slot, t, r))

    # ---- the dumps -------------------------------------------------------

    def is_rec(self, a, kind):
        i = bisect.bisect_left(self.rec_starts, a)
        return (i < len(self.recs) and self.recs[i][0] == a
                and self.recs[i][2] == kind)

    def s16(self, a):
        v = self.e.u16(a)
        return v - 0x10000 if v & 0x8000 else v

    def s8(self, a):
        v = self.e.u8(a)
        return v - 0x100 if v & 0x80 else v

    def dump_solid(self, s):
        e, L = self.e, self.label
        u = e.u32
        nstrips = self.s16(s + 52)
        ntex = self.s16(s + 172)
        nlm = self.s16(s + 174)
        self.emit("  %s name %08x flags %04x strips %d szdata %d data %s se %s"
                  " tt %d:%s lm %d:%s"
                  % (L(s), u(s + 8), e.u16(s + 48), nstrips, u(s + 60),
                     L(u(s + 180)), L(u(s + 176)), ntex, L(u(s + 184)), nlm,
                     L(u(s + 188))))
        line = ("   tree %d:%s rigid %s va %s ext %08x"
                % (s32(u(s + 160)), L(u(s + 164)), L(u(s + 168)),
                   L(u(s + 44)), u(s + 40)))
        ra = u(s + 168)
        if self.is_rec(ra, K_RA):
            line += " lf %s trig %d" % (L(u(ra + 8)), e.u8(ra + 2))
        self.emit(line)
        tt = u(s + 184)
        if self.is_rec(tt, K_TT):
            self.emit("   tt" + "".join(
                " %08x=%s" % (u(tt + 8 * i), L(u(tt + 8 * i + 4)))
                for i in range(ntex)))
        lm = u(s + 188)
        if self.is_rec(lm, K_LM):
            self.emit("   lmt" + "".join(
                " %08x=%s" % (u(lm + 8 * i), L(u(lm + 8 * i + 4)))
                for i in range(nlm)))
        se = u(s + 176)
        if self.is_rec(se, K_SE):
            d = u(s + 180)
            sz = u(s + 60)
            parts = []
            for i in range(nstrips):
                x = u(se + 64 * i + 8)
                if self.is_rec(d, K_SD) and d <= x < d + sz:
                    parts.append(" +%x" % (x - d))
                else:
                    parts.append(" " + L(x))
            self.emit("   sd" + "".join(parts))

    def dump_model(self, m):
        e, L = self.e, self.label
        u = e.u32
        n = self.s8(m + 20)
        self.emit("  %s name %08x solid %s repl %s n %d inst %d start %d"
                  " next %s prev %s"
                  % (L(m), u(m + 8), L(u(m + 12)), L(u(m + 16)), n,
                     self.s8(m + 21), self.s16(m + 22), L(u(m)),
                     L(u(m + 4))))
        rt = u(m + 16)
        for i in sorted(self.repl):
            p, cnt = self.repl[i]
            if p != rt:
                continue
            for k in range(min(n, cnt)):
                r = p + 28 * k
                self.emit("   r%d[%d] %08x %08x %s idx %s"
                          % (i, k, u(r), u(r + 4), L(u(r + 8)),
                             " ".join(str(self.s8(r + 12 + j))
                                      for j in range(16))))
            break

    def walk_list(self, head, name):
        u = self.e.u32
        nodes = []
        n = u(head)
        while n != head and len(nodes) < 40000:
            nodes.append(n)
            n = u(n)
        self.emit("  %s %d%s:%s" % (name, len(nodes),
                                    "+" if len(nodes) == 40000 else "",
                                    "".join(" " + self.label(x)
                                            for x in nodes)))
        ok = True
        n = u(head + 4)
        for x in reversed(nodes):
            if n != x:
                ok = False
                break
            n = u(n + 4)
        if ok and n != head:
            ok = False
        self.emit("  %s prev %s" % (name, "ok" if ok else "broken"))
        return nodes

    def dump(self):
        e, L = self.e, self.label
        self.emit("  flags dis %d solids %d tex %d anim %d"
                  % tuple(s32(e.u32(a)) for a in FLAGS))
        self.emit("  ti " + " ".join(L(e.u32(a)) for a in TI_PTRS))
        self.emit("  sun %s pos %08x %08x %08x"
                  % ((L(e.u32(SUN_INFO)),)
                     + tuple(e.u32(SUN_POS + 4 * k) for k in range(3))))
        self.emit("  weather " + " ".join(
            "%s/%s" % (L(e.u32(h)), L(e.u32(h + 4))) for h in WEATHER_LISTS))
        seen = []
        for s in self.walk_list(SOLIDLIST, "solids"):
            self.dump_solid(s)
            va = e.u32(s + 44)
            if va in self.vas and va not in seen and len(seen) < 64:
                seen.append(va)
                n = s32(e.u32(va + 12))
                self.emit("  %s rate %d n %d:%s"
                          % (L(va), s32(e.u32(va + 8)), n,
                             "".join(" " + L(e.u32(va + 16 + 4 * i))
                                     for i in range(min(n, 64)))))
        for m in self.walk_list(MODELLIST, "models"):
            self.dump_model(m)
        self.emit("  pools va %d model %d" % (self.va_count, self.model_count))

    # ---- the run ---------------------------------------------------------

    def call(self, name, *args):
        return self.e.call(self.fn[name], *args, limit=400000000)

    def run(self):
        e, sc = self.e, self.sc
        for o in sc.ops:
            code, a = o[0], o[1:]
            if code == OP_TAG:
                self.emit("[%s]" % sc.tags[a[0]])
            elif code == OP_BUF:
                self.buf_begin(a[0])
            elif code == OP_LEAF:
                t, n, nw = a[0], a[1], a[2]
                raw = struct.pack("<%dI" % nw, *[w & M32 for w in a[3:]])
                self.leaf(t & M32, raw[:n])
            elif code == OP_BULK:
                self.leaf(a[0] & M32, bytes(a[1]))
            elif code == OP_OPEN:
                self.begin_chunk()
                self.stack.append((len(self.stage), a[0] & M32))
                self.stage += struct.pack("<II", a[0] & M32, 0)
            elif code == OP_CLOSE:
                off, _ = self.stack.pop()
                struct.pack_into("<I", self.stage, off + 4,
                                 len(self.stage) - off - 8)
            elif code == OP_BUFEND:
                self.buf_end()
            elif code == OP_CLAIMS:
                self.claims = {}
            elif code == OP_CLAIM:
                self.claims[(a[0], a[1] & M32)] = a[2]
            elif code == OP_SWAP:
                if a[0]:
                    self.saved = [e.u32(LOADERS + 4 * k)
                                  for k in range(NSLOTS)] + \
                                 [e.u32(UNLOADERS + 4 * k)
                                  for k in range(NSLOTS)]
                    for k in range(NSLOTS):
                        e.put32(LOADERS + 4 * k, PROBE_BASE + 8 * k)
                        e.put32(UNLOADERS + 4 * k, PROBE_BASE + 8 * k)
                else:
                    for k in range(NSLOTS):
                        e.put32(LOADERS + 4 * k, self.saved[k])
                        e.put32(UNLOADERS + 4 * k, self.saved[NSLOTS + k])
            elif code == OP_TRAVERSE:
                dir_, first, last, num = a
                self.call("backwards" if dir_ else "traverse",
                          self.chunk_ptr(first), self.chunk_ptr(last),
                          self.probe_table, num)
                self.emit("  breaks %d" % (self.breaks - self.breaks_seen))
                self.breaks_seen = self.breaks
            elif code == OP_LOAD:
                dir_, mode = a
                p, n, _ = self.cur
                self.call("unload" if dir_ else "load",
                          0 if mode == 1 else p, 0 if mode == 2 else n)
                self.emit("  breaks %d" % (self.breaks - self.breaks_seen))
                self.breaks_seen = self.breaks
            elif code == OP_CALL:
                c = self.chunk_ptr(a[1])
                r = self.call("usl" if a[0] else "lsl", c)
                if e.u32(c) == SOLID_LIST:
                    self.emit("  ret %d inv %08x" % (r, e.u32(c + 64)))
                else:
                    self.emit("  ret %d" % r)
            elif code == OP_FIXUP:
                self.call(("efix", "fixup", "hot")[a[0]])
            elif code == OP_SET:
                e.put32(FLAGS[a[0]], a[1])
            elif code == OP_DUMP:
                self.dump()
            elif code == OP_MNEW:
                p = e.alloc(24, 16)
                e.mem[p:p + 24] = b"\xcd" * 24
                self.models[a[0]] = p
                self.model_count += 1
            elif code == OP_MINIT:
                self.call("minit", self.models[a[0]], a[1])
            elif code == OP_MUNINIT:
                self.call("muninit", self.models[a[0]])
            elif code == OP_MDELETE:
                self.call("mdelete", self.models[a[0]], a[1])
            elif code == OP_MRECON:
                self.call("mrecon", self.models[a[0]])
            elif code == OP_MRTT:
                self.call("mrtt", self.models[a[0]])
            elif code == OP_MAPPLY:
                self.call("mapply", self.models[a[0]])
            elif code == OP_MALL:
                self.call("mall")
            elif code == OP_MPOKE:
                m, field, v = self.models[a[0]], a[1], a[2]
                if field == 0:
                    e.put32(m + 8, v)
                elif field == 1:
                    e.put32(m + 12, 0 if v < 0 else self.solid_by_idx[v])
                elif field == 2:
                    e.put32(m + 16, 0 if v < 0 else self.repl[v][0])
                elif field == 3:
                    e.mem[m + 20] = v & 0xff
                elif field == 4:
                    e.mem[m + 21] = v & 0xff
                else:
                    struct.pack_into("<h", e.mem, m + 22, v)
            elif code == OP_MDUMP:
                self.dump_model(self.models[a[0]])
            elif code == OP_REPL:
                p = e.alloc(28 * a[1] + 4, 16)
                e.mem[p:p + 28 * a[1]] = bytes(28 * a[1])
                self.repl[a[0]] = (p, a[1])
            elif code == OP_RENT:
                p = self.repl[a[0]][0] + 28 * a[1]
                struct.pack_into("<III4I", e.mem, p, a[2] & M32, a[3] & M32,
                                 0, *[w & M32 for w in a[4:8]])
            elif code == OP_FIND:
                r = self.call("find", a[0] & M32)
                self.emit("  find %08x %s" % (a[0] & M32, self.label(r)))
            elif code == OP_MATRIX:
                self.matrix(a[0], a[1], a[2] & M32, a[3])
            else:
                raise ValueError("op %d" % code)
        return self.out


def model(sc, files=None):
    return Model(sc, files if files is not None else disc_files()).run()


# ================================================================ the build


def build_harness(tmp, name="loadertable_test"):
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
    # ---- bchunkload.c: the tables
    ("null-takes-all", BCL, "return bchunk_u32(chunk) == 0;", "return 1;"),
    ("take-no-seam", BCL, "gUnportedLoaderFn(slot, unload, c);", ";"),
    ("take-skips-first", BCL, "for (i = 0; i < n; i++) {",
     "for (i = 1; i < n; i++) {"),
    ("unported-unload-flag", BCL, "slot, 1, c);", "slot, 0, c);"),
    ("slot-6-is-7", BCL, "    LoaderAcidFX,", "    LoaderEventManager,"),
    ("unloader-14-loads", BCL, "    unloader_sun,", "    loader_sun,"),
    ("unloader-29-loads", BCL, "    unloader_weather_man,",
     "    loader_weather_man,"),
    ("loader-29-unloads", BCL, "    loader_weather_man,",
     "    unloader_weather_man,"),
    ("weather-type", "3DS Files/source/weatherman.h",
     "#define WEATHER_CHUNK_ID      0x00034250u",
     "#define WEATHER_CHUNK_ID      0x00034251u"),
    ("sun-type", "3DS Files/source/sun.h",
     "#define SUN_CHUNK_ID      0x00034202u",
     "#define SUN_CHUNK_ID      0x00034203u"),
    ("cops-slot", BCL, "UNPORTED(LoaderCops, UnloaderCops, 15,",
     "UNPORTED(LoaderCops, UnloaderCops, 16,"),
    ("slot-19-unloader-is-loader", BCL, "    UnloaderTrackPath,",
     "    loader_track_path,"),
    # ---- bchunkload.c: the walks
    ("misses-not-reset", BCL,
     "            c = next_chunk(c);\n            misses = 0;",
     "            c = next_chunk(c);"),
    ("misses-reset-on-skip", BCL,
     "                bbreak();\n                c = next_chunk(c);",
     "                bbreak();\n                c = next_chunk(c);\n"
     "                misses = 0;"),
    ("misses-ge", BCL, "if (misses > num) {", "if (misses >= num) {"),
    ("slot-reset-on-take", BCL,
     "            c = next_chunk(c);\n            misses = 0;",
     "            c = next_chunk(c);\n            misses = 0;\n"
     "            slot = 0;"),
    ("wrap-early", BCL, "            if (slot == num)\n                slot = 0;",
     "            if (slot == num - 1)\n                slot = 0;"),
    ("back-skips-0", BCL, "for (slot = 0; slot < num; slot++) {",
     "for (slot = 1; slot < num; slot++) {"),
    ("back-no-break", BCL, "        if (slot == num)\n            bbreak();",
     ""),
    ("back-tries-all", BCL,
     "            if (table[slot](c))\n                break;",
     "            (void)table[slot](c);"),
    ("load-null", BCL,
     "    if (chunks == NULL || size == 0)\n        return;\n"
     "    traverse_chunks(",
     "    if (size == 0)\n        return;\n    traverse_chunks("),
    ("load-size0", BCL,
     "    if (chunks == NULL || size == 0)\n        return;\n"
     "    traverse_chunks(",
     "    if (chunks == NULL)\n        return;\n    traverse_chunks("),
    ("load-30", BCL, "LoaderTable, BCHUNK_NUM_LOADERS);",
     "LoaderTable, BCHUNK_NUM_LOADERS - 1);"),
    ("unload-loaders", BCL,
     "traverse_chunks_backwards(chunks, chunks + size, UnloaderTable,",
     "traverse_chunks_backwards(chunks, chunks + size, LoaderTable,"),
    ("unload-forwards", BCL,
     "traverse_chunks_backwards(chunks, chunks + size, UnloaderTable,",
     "traverse_chunks(chunks, chunks + size, UnloaderTable,"),
    ("fixup-no-efix", BCL, "    efix_up_tables();\n", ""),
    ("fixup-order", BCL,
     "    if (gELightUpdateTexturesFn != NULL)\n"
     "        gELightUpdateTexturesFn();\n"
     "    if (gAfxUpdateTexturesFn != NULL)\n"
     "        gAfxUpdateTexturesFn();",
     "    if (gAfxUpdateTexturesFn != NULL)\n"
     "        gAfxUpdateTexturesFn();\n"
     "    if (gELightUpdateTexturesFn != NULL)\n"
     "        gELightUpdateTexturesFn();"),
    ("fixup-no-flailer", BCL, "        gFlailerPostLoadFixupFn();", ";"),
    ("hot-no-fern", BCL, "        gEmptyFernFlattenersFn();", ";"),
    # ---- esolid.c: LoaderSolidList
    ("list-guard", ESC,
     "    if (bchunk_u32(chunk) != SOLID_LIST_ID)\n        return 0;\n"
     "    end = next_chunk(chunk);\n    header",
     "    if (bchunk_u32(chunk) != SOLID_LIST_ID + 1)\n        return 0;\n"
     "    end = next_chunk(chunk);\n    header"),
    ("inventory-name", ESC, '"SolidList,%s"', '"SolidList.%s"'),
    ("header-offset", ESC, "(eSolidListHeader *)(void *)(chunk + 16);",
     "(eSolidListHeader *)(void *)(chunk + 20);"),
    ("strips-unaligned", ESC, "s->StripEntryTable = p;",
     "s->StripEntryTable = payload;"),
    ("tt-aligned", ESC, "s->pTextureTable = payload;",
     "s->pTextureTable = p;"),
    ("tt-count-rounds-up", ESC,
     "(int16_t)(size / sizeof(eTextureTable));",
     "(int16_t)((size + sizeof(eTextureTable) - 1)\n"
     "                                          / sizeof(eTextureTable));"),
    ("lm-unaligned", ESC, "s->LightMaterialTable = p;",
     "s->LightMaterialTable = payload;"),
    ("sd-size-with-pad", ESC,
     "uint32_t n = size - (uint32_t)(p - payload);", "uint32_t n = size;"),
    ("sd-unaligned", ESC, "            s->StripEntryDataStart = p;",
     "            s->StripEntryDataStart = payload;"),
    ("strips-fixed-to-payload", ESC,
     "esolid_fix_strip_entry_table(s, p, (int32_t)n, NULL);",
     "esolid_fix_strip_entry_table(s, payload, (int32_t)n, NULL);"),
    ("tree-unaligned", ESC, "s->pAnimationTreeNodes = p;",
     "s->pAnimationTreeNodes = payload;"),
    ("tree-count-with-pad", ESC,
     "(size - (uint32_t)(p - payload)) / EANIMATIONTREENODE_SIZE);",
     "size / EANIMATIONTREENODE_SIZE);"),
    ("rigid-unaligned", ESC, "s->pRigidAnimation = p;",
     "s->pRigidAnimation = payload;"),
    ("frames-aligned", ESC,
     "->pLabelledFrames =\n                payload;",
     "->pLabelledFrames =\n                p;"),
    ("frames-ignored", ESC,
     "} else if (type == LABELLED_FRAMES_ID) {",
     "} else if (type == LABELLED_FRAMES_ID + 0x100) {"),
    ("vertex-flag", ESC, "#define SOLID_VERTEX_ANIMATED   0x0010u",
     "#define SOLID_VERTEX_ANIMATED   0x0020u"),
    ("duplicate-flag", ESC, "#define SOLID_DUPLICATE_NAME    0x0002u",
     "#define SOLID_DUPLICATE_NAME    0x0004u"),
    ("duplicate-first-unflagged", ESC,
     "                e->Flags |= SOLID_DUPLICATE_NAME;\n", ""),
    ("ext-rigid-ignored", ESC,
     "if (s->ExternalRigidAnimationNameHash != 0) {", "if (0) {"),
    ("ext-rigid-miss-clears", ESC,
     "            if (e != NULL)\n"
     "                s->pRigidAnimation = e->pRigidAnimation;",
     "            s->pRigidAnimation = e != NULL ? e->pRigidAnimation : NULL;"),
    ("frame-rate", ESC, "va->FrameRate = 30;", "va->FrameRate = 60;"),
    ("frames-cap-65", ESC,
     "if (va->NumSolids < EVERTEXANIMATOR_MAX_SOLIDS) {",
     "if (va->NumSolids < EVERTEXANIMATOR_MAX_SOLIDS - 1) {"),
    ("frames-keep-rigid", ESC,
     "                s->pVertexAnimator = e->pVertexAnimator;\n"
     "                s->pRigidAnimation = e->pRigidAnimation;",
     "                s->pVertexAnimator = e->pVertexAnimator;"),
    ("first-frame-not-in-table", ESC, "                va->NumSolids = 1;",
     "                va->NumSolids = 0;"),
    ("list-at-head", ESC,
     "        last = SolidList.prev;\n"
     "        last->next = &s->Node;\n"
     "        SolidList.prev = &s->Node;\n"
     "        s->Node.next = &SolidList;\n"
     "        s->Node.prev = last;",
     "        last = SolidList.next;\n"
     "        last->prev = &s->Node;\n"
     "        SolidList.next = &s->Node;\n"
     "        s->Node.prev = &SolidList;\n"
     "        s->Node.next = last;"),
    ("load-not-dirty", ESC,
     "        eDirtySolids = 1;\n        last = SolidList.prev;",
     "        last = SolidList.prev;"),
    ("tt-no-default", ESC,
     "t->pTextureInfo = get_texture_info(t->NameHash, 1);",
     "t->pTextureInfo = get_texture_info(t->NameHash, 0);"),
    ("lm-not-looked-up", ESC,
     "e->LightMaterial = get_light_material(e->NameHash);",
     "e->LightMaterial = NULL;"),
    ("lm-one-short", ESC,
     "    int n = s->NumLightMaterials;\n\n    for (; n > 0; n--, e++)",
     "    int n = s->NumLightMaterials;\n\n    for (; n > 1; n--, e++)"),
    ("strip-base", ESC, "+ (uintptr_t)data\n", "+ (uintptr_t)data + 16\n"),
    # ---- esolid.c: UnloaderSolidList
    ("unload-guard", ESC,
     "    if (bchunk_u32(chunk) != SOLID_LIST_ID)\n        return 0;\n"
     "    end = next_chunk(chunk);\n    c = next_chunk(chunk + 8);",
     "    if (bchunk_u32(chunk) != SOLID_LIST_ID)\n        return 1;\n"
     "    end = next_chunk(chunk);\n    c = next_chunk(chunk + 8);"),
    ("unload-frames-kept", ESC,
     "                    va->SolidTable[i]->pVertexAnimator = NULL;", ";"),
    ("unload-count-kept", ESC,
     "                va->NumSolids = 0;\n"
     "                evertexanimator_delete(va, 3);",
     "                evertexanimator_delete(va, 3);"),
    ("unload-not-freed", ESC, "evertexanimator_delete(va, 3);",
     "evertexanimator_delete(va, 2);"),
    ("unload-not-dirty", ESC, "        eDirtySolids = 1;\n    }\n    return 1;",
     "    }\n    return 1;"),
    ("unload-header-as-container", ESC,
     "    c = next_chunk(chunk + 8);\n    // bRemove",
     "    c = chunk + 8;\n    // bRemove"),
    ("unload-not-unlinked", ESC,
     "            s->Node.prev->next = s->Node.next;\n"
     "            s->Node.next->prev = s->Node.prev;\n", ""),
    # ---- esolid.c: eFixUpTables
    ("efix-not-disabled", ESC,
     "    if (eDisableFixUpTables)\n        return;\n", ""),
    ("efix-textures-ignored", ESC, "if (eDirtySolids || eDirtyTextures) {",
     "if (eDirtySolids) {"),
    ("efix-no-refix", ESC,
     "                esolid_fix_texture_table(s);\n"
     "                if (gFixStripSTsFn != NULL)",
     "                if (gFixStripSTsFn != NULL)"),
    ("efix-no-autok", ESC, "                    gCalcAutoKFn(s);", ";"),
    ("efix-no-models", ESC,
     "        emodel_reconnect_all_models();\n"
     "        if (gReconnectAllAnimationsFn != NULL)",
     "        if (gReconnectAllAnimationsFn != NULL)"),
    ("efix-mask-default", ESC, "get_texture_info(0xcf29d0dfu, 0);",
     "get_texture_info(0xcf29d0dfu, 1);"),
    ("efix-blur-shadow", ESC,
     "pTextureInfoShadowMap1 = get_texture_info(0xbad886d4u, 0);\n"
     "        pTextureInfoRadialBlur = get_texture_info(0xab9a6e21u, 0);",
     "pTextureInfoShadowMap1 = get_texture_info(0xab9a6e21u, 0);\n"
     "        pTextureInfoRadialBlur = get_texture_info(0xbad886d4u, 0);"),
    ("efix-anim-kept", ESC,
     "        eDirtyTextures = 0;\n        eDirtyAnimations = 0;\n",
     "        eDirtyTextures = 0;\n"),
    ("efix-anim-branch-kept", ESC,
     "            gReconnectAllAnimationsFn();\n        eDirtyAnimations = 0;\n"
     "    }",
     "            gReconnectAllAnimationsFn();\n    }"),
    ("efix-anim-branch-gone", ESC, "    if (eDirtyAnimations) {",
     "    if (0) {"),
    # ---- emodel.c
    ("find-skips-first", EMC, "for (n = SolidList.next; n != &SolidList;",
     "for (n = SolidList.next->next; n != &SolidList;"),
    ("recon-always", EMC,
     "    if (solid == m->Solid)\n        return;\n", ""),
    ("recon-start-kept-on-null", EMC,
     "    m->RigidAnimationStartTime = 0;\n    if (solid == NULL)\n"
     "        return;\n",
     "    if (solid == NULL)\n        return;\n"
     "    m->RigidAnimationStartTime = 0;\n"),
    ("recon-trigger-byte", EMC, "solid->pRigidAnimation[2] != 0",
     "solid->pRigidAnimation[3] != 0"),
    ("recon-start", EMC, "(int16_t)0xc000;", "(int16_t)0x8000;"),
    ("rtt-no-default", EMC, "get_texture_info(r->NewNameHash, 1);",
     "get_texture_info(r->NewNameHash, 0);"),
    ("rtt-slot-kept", EMC, "        *slot = -1;\n", ""),
    ("rtt-last-match", EMC,
     "                *slot = (int8_t)k;\n                break;",
     "                *slot = (int8_t)k;"),
    ("rtt-stops-at-null", EMC,
     "        if (s == NULL)\n            continue;",
     "        if (s == NULL)\n            break;"),
    ("rtt-instance-masked", EMC,
     "&r->ReplaceIndex[(int8_t)m->ReplacementTextureInstanceIndex];",
     "&r->ReplaceIndex[m->ReplacementTextureInstanceIndex & 7];"),
    ("rtt-count-unsigned", EMC,
     "    for (i = 0; i < (int8_t)m->NumReplacementTextures; i++) {\n"
     "        eReplacementTextureTable *r =",
     "    for (i = 0; i < (int)m->NumReplacementTextures; i++) {\n"
     "        eReplacementTextureTable *r ="),
    ("rtt-no-apply", EMC,
     "    }\n    emodel_apply_replacement_texture_table(m);\n}",
     "    }\n}"),
    ("apply-zero-skipped", EMC, "        if (k >= 0)", "        if (k > 0)"),
    ("apply-instance-0", EMC,
     "int k = r[i].ReplaceIndex[(int8_t)m->ReplacementTextureInstanceIndex];",
     "int k = r[i].ReplaceIndex[0];"),
    ("all-fixsts-null", EMC,
     "if (m->Solid != NULL && gFixStripSTsFn != NULL)",
     "if (gFixStripSTsFn != NULL)"),
    ("all-order", EMC,
     "        emodel_reconnect_solid(m);\n"
     "        emodel_reconnect_texture_table(m);",
     "        emodel_reconnect_texture_table(m);\n"
     "        emodel_reconnect_solid(m);"),
    ("init-repl-kept", EMC,
     "    m->NameHash = name_hash;\n    m->pReplacementTextureTable = NULL;\n",
     "    m->NameHash = name_hash;\n"),
    ("init-count-kept", EMC,
     "    m->pReplacementTextureTable = NULL;\n"
     "    m->NumReplacementTextures = 0;\n    m->RigidAnimationStartTime = 0;\n"
     "    if (name_hash == 0)",
     "    m->pReplacementTextureTable = NULL;\n"
     "    m->RigidAnimationStartTime = 0;\n    if (name_hash == 0)"),
    ("init-start-kept", EMC,
     "    m->RigidAnimationStartTime = 0;\n    if (name_hash == 0)",
     "    if (name_hash == 0)"),
    ("init-links-zero", EMC,
     "    if (name_hash == 0)\n        return;\n    emodel_reconnect_solid(m);",
     "    emodel_reconnect_solid(m);"),
    ("init-no-reconnect", EMC,
     "        return;\n    emodel_reconnect_solid(m);\n    last",
     "        return;\n    last"),
    ("init-at-head", EMC,
     "    last = ModelList.prev;\n    last->next = &m->Node;\n"
     "    ModelList.prev = &m->Node;\n    m->Node.next = &ModelList;\n"
     "    m->Node.prev = last;",
     "    last = ModelList.next;\n    last->prev = &m->Node;\n"
     "    ModelList.next = &m->Node;\n    m->Node.prev = &ModelList;\n"
     "    m->Node.next = last;"),
    ("uninit-unguarded", EMC,
     "    if (m->NameHash == 0)\n        return;\n    prev",
     "    prev"),
    ("uninit-count-kept", EMC,
     "    m->NumReplacementTextures = 0;\n    prev->next = next;",
     "    prev->next = next;"),
    ("uninit-solid-kept", EMC, "    m->Solid = NULL;\n    m->NameHash = 0;",
     "    m->NameHash = 0;"),
    ("uninit-repl-kept", EMC,
     "    m->NameHash = 0;\n    m->pReplacementTextureTable = NULL;",
     "    m->NameHash = 0;"),
    ("uninit-start-kept", EMC,
     "    m->RigidAnimationStartTime = 0;\n}\n\nvoid emodel_delete",
     "}\n\nvoid emodel_delete"),
    ("delete-flag", EMC, "    if (flags & 1)\n        bSlotFree(eModelSlotPool, m);",
     "    if (flags & 2)\n        bSlotFree(eModelSlotPool, m);"),
    ("delete-no-uninit", EMC, "    emodel_uninit(m);\n    // ~bTNode",
     "    // ~bTNode"),
]

EQUIVALENT = {
    "load-size0":
        "a walk from the start to the start takes nothing, so the size's "
        "own test only saves the call",
    "unload-count-kept":
        "the animator is freed straight after, and nothing reads it again: "
        "every solid in its table has let go of it, and the frames past 64 "
        "that have not are in a list the script never unloads",
}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name


def mutate_pass(only=None):
    files = disc_files()
    sc = script(files)
    base = model(sc, files)
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

    files = disc_files()
    sc = script(files)
    lines = model(sc, files)
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
