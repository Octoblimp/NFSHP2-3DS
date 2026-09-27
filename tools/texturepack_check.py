#!/usr/bin/env python3
"""Cross-check 3DS Files/source/texturepack.c -- LoaderTexturePack and
UnloaderTexturePack, slot 2 of the chunk tables, and TexturePack.obj's
in-memory half -- against the image itself, run in mipsemu.

The model is the image: the two loaders, TexturePack's constructor and
destructor, AttachTextureTable, AssignTextureData, UnAssignTextureData,
GetLoadedTexture, GetTexture, GetNthTexture, GetTextureInfo,
GetNthTextureInfo, TextureAnimPack's constructor, destructor and InitAnims,
UpdateTextureAnimations and GetTextureAnim all run as shipped, with
bStrCpy, bStringHash, bSPrintf and bAddCodeineInventory. The harness runs
the same op script on the port and prints the same lines.

**The seams.** eGetRenderTargetTextureInfo (`rt`, which hands out rt.0,
rt.1, ... for the hashes the script names) and ServiceQueuedFiles (`sqf`,
which ends the pack's streaming load after the calls the script asks for)
are stubbed at the same call on both sides, and both log them. bBreak is
counted. The debugger's channel (bFunkCallASync, bRemoveCodeineInventory) is
a no-op.

**The heap.** Both sides' bMalloc hands out a fresh block filled with 0xcd
and logs its name; bFree logs what it was given and frees nothing. A block
prints as a<k>, the k-th bMalloc.

**The layouts.** Every chunk is described op by op as the disc lays it out,
and the model builds exactly that. The host has 8-byte pointers, so the
harness rebuilds each record with the host's struct (see
texturepack_test.c), and places each pack so that its blob's payload has
the disc's address mod 128: that is what the loader rounds. A pointer prints
as what it points at: t<k>.<i> for record i of chunk k's table, d<k>+<off>
for chunk k's blob, from its payload, A<k>.<i> and E<k>.<i> for a flipbook
and a frame, h<k> for a header, a<k> for a block, TPL and TAPL for the two
lists; x<hex> for anything else.

Scenarios: every texture file on the disc, loaded in the game's order, each
of its textures and a few misses looked up, its flipbooks run, and all of it
unloaded; built packs for the guards, the name, the table's size, the
blob's rounding, the placements' ranges, image parents, duplicate names,
garbage in the runtime fields, the lookups' order, the default and the
render targets; the destructor's flags, its streaming load and its
LoadedTextureData; and built flipbooks for every version, missing frames,
the two clocks, TweakFPS and big frame counts.

    python tools/texturepack_check.py
    python tools/texturepack_check.py --mutate [--only a,b]
    python tools/texturepack_check.py --dump out/texturepack
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

HARNESS = "tools/src/texturepack_test.c"
TPC = "3DS Files/source/texturepack.c"
SOURCES = [HARNESS, TPC, "3DS Files/source/bmem.c"]

HARNESS_TIMEOUT = 600
EXTRACTED = ROOT / "extracted"

# The files, in the order the game has them loaded by a race on TRACKB12:
# the boot's, the race's, the track's; then the rest.
DISC_FILES = ["GLOBAL/GLOBALB.BUN", "GLOBAL/INGAMEB.BUN",
              "TRACKS/TEX12LOCATION.BIN", "TRACKS/TEX12TRACK.BIN",
              "GLOBAL/HUDTEX.BIN", "GLOBAL/DRIVTEX.BIN", "GLOBAL/DYNTEX.BIN",
              "CARS/TEXTURES.BIN", "FRONTEND/FRONTB.BUN",
              "FRONTEND/TSELECT.BIN"]

# ================================================================ the image

GP = 0x00328bf0
TPL, TAPL = GP - 19800, GP - 19792
TWEAK_FPS = GP - 19784
WORLD_FRAMES, REAL_FRAMES = GP - 20212, GP - 20248
DIRTY_TEXTURES = GP - 25512

PRE, POST = 1024, 4096 + 256        # the slack around each chunk
SLACK = 4096                        # a blob's label runs this far past it
MARGIN = 2                          # records a table's label runs before it
LTD_OFF = 112

PACK_ID, ANIM_ID = 0xb0300001, 0xb0300100
DEFAULT = 0x19006835

SYM = dict(
    load="LoaderTexturePack__FP6bChunk",
    unload="UnloaderTexturePack__FP6bChunk",
    gti="GetTextureInfo__FUii",
    gnti="GetNthTextureInfo__Fi",
    gta="GetTextureAnim__FUi",
    update="UpdateTextureAnimations__Fv",
    glt="GetLoadedTexture__11TexturePackUi",
    gt="GetTexture__11TexturePackUi",
    gnt="GetNthTexture__11TexturePacki",
    assign="AssignTextureData__11TexturePackPcii",
    unassign="UnAssignTextureData__11TexturePackii",
    attach="AttachTextureTable__11TexturePackP11TextureInfoi",
    destruct="_$_11TexturePack",
    maybe="MaybePrintUnusedTextures__Fv",
)

# ---- the ops -----------------------------------------------------------------

(OP_TAG, OP_NAME, OP_REC, OP_PACK, OP_ANIM, OP_ENTRY, OP_APACK, OP_RAW,
 OP_LOAD, OP_GTI, OP_GNTI, OP_GLT, OP_ASSIGN, OP_UNASSIGN, OP_ATTACH,
 OP_DESTRUCT, OP_POKE, OP_LTD, OP_RTSET, OP_UPDATE, OP_GTA, OP_DUMP,
 OP_RECS, OP_ANIMS, OP_HDRS, OP_RPOKE) = range(26)

ARGS = {OP_TAG: 1, OP_NAME: 4, OP_REC: 41, OP_PACK: 4, OP_ANIM: 13,
        OP_ENTRY: 4, OP_APACK: 6, OP_RAW: 2, OP_LOAD: 2, OP_GTI: 2,
        OP_GNTI: 1, OP_GLT: 3, OP_ASSIGN: 5, OP_UNASSIGN: 3, OP_ATTACH: 3,
        OP_DESTRUCT: 2, OP_POKE: 3, OP_LTD: 2, OP_RTSET: 1, OP_UPDATE: 3,
        OP_GTA: 1, OP_DUMP: 0, OP_RECS: 1, OP_ANIMS: 1, OP_HDRS: 0,
        OP_RPOKE: 4}


class Script(object):
    def __init__(self):
        self.ops = []
        self.tags = []
        self.nchunks = 0

    def op(self, code, *args):
        assert len(args) == ARGS[code], (code, args)
        self.ops.append((code,) + tuple(int(a) for a in args))

    def tag(self, s):
        self.tags.append(s)
        self.op(OP_TAG, len(self.tags) - 1)

    def words(self, code, data, n):
        data = bytes(data)
        assert len(data) == 4 * n, (code, len(data))
        self.op(code, *struct.unpack("<%dI" % n, data))

    # ---- chunks ----------------------------------------------------------

    def pack(self, name, recs, blob, mis=0, ptr=0, extra=0):
        """A 0xb0300001 chunk. `name` is the header's 16 bytes, `recs` the
        disc records, `blob` the blob's size; the chunk starts `mis` past a
        128-byte boundary."""
        nm = bytes(name)[:16]
        self.words(OP_NAME, nm + bytes(16 - len(nm)), 4)
        for r in recs:
            self.words(OP_REC, r, 41)
        self.op(OP_PACK, mis, ptr, extra, blob)
        k = self.nchunks
        self.nchunks += 1
        return k

    def anim_pack(self, anims, entries, version=1, ptr=0, pad=(0, 0),
                  aextra=0, eextra=0):
        for a in anims:
            self.words(OP_ANIM, a, 13)
        for e in entries:
            self.words(OP_ENTRY, e, 4)
        self.op(OP_APACK, version, ptr, pad[0], pad[1], aextra, eextra)
        k = self.nchunks
        self.nchunks += 1
        return k

    def raw(self, type_, size):
        self.op(OP_RAW, type_, size)
        k = self.nchunks
        self.nchunks += 1
        return k

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


# ================================================================ records


def bhash(s):
    h = 0xffffffff
    for c in s.encode("latin-1"):
        h = (h * 33 + c) & M32
    return h


def info_rec(name, img=0, isize=0, pal=0, psize=0, parent=0, hash_=None,
             garbage=0, order=0):
    """A disc TextureInfo. The runtime words are `garbage`."""
    r = bytearray(164)
    struct.pack_into("<II", r, 0, garbage, garbage ^ 1)
    nm = name.encode("latin-1")[:23]
    r[8:8 + len(nm)] = nm
    struct.pack_into("<I", r, 32, bhash(name) if hash_ is None else hash_)
    struct.pack_into("<HH", r, 36, 64, 32)
    r[40] = 8
    r[41] = order
    struct.pack_into("<iiiiIi", r, 48, img, pal, isize, psize, parent, isize)
    r[120] = garbage & 0xff
    for i, off in enumerate(range(136, 160, 4)):
        struct.pack_into("<I", r, off, garbage + i if garbage else 0)
    struct.pack_into("<HH", r, 160, garbage & 0xffff, garbage >> 16 & 0xffff)
    return bytes(r)


def anim_rec(name, nframes, fps, timebase=0, garbage=0, hash_=None):
    r = bytearray(52)
    nm = name.encode("latin-1")[:23]
    r[0:len(nm)] = nm
    struct.pack_into("<Iiii", r, 24, bhash(name) if hash_ is None else hash_,
                     nframes, fps, timebase)
    struct.pack_into("<III", r, 40, garbage, garbage ^ 3, garbage ^ 5)
    return bytes(r)


def entry_rec(name, garbage=0, hash_=None):
    return struct.pack("<IIII", bhash(name) if hash_ is None else hash_,
                       garbage, garbage ^ 1, garbage ^ 2)


# ================================================================ the disc


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def kids(b, o, end):
    out = []
    while o + 8 <= end:
        t, s = u32(b, o), u32(b, o + 4)
        if o + 8 + s > end:
            break
        out.append((o, t, s))
        o += 8 + s
    return out


def disc_chunks(sc, rel):
    """A file's top-level chunks through the script: the packs as they are,
    the rest bare. Returns [(chunk index, type)]."""
    b = (EXTRACTED / rel).read_bytes()
    out = []
    for (o, t, s) in kids(b, 0, len(b)):
        if t == PACK_ID:
            h, tb, db = kids(b, o + 8, o + 8 + s)
            recs = [b[tb[0] + 8 + 164 * i:tb[0] + 8 + 164 * (i + 1)]
                    for i in range(tb[2] // 164)]
            k = sc.pack(b[h[0] + 8:h[0] + 24], recs, db[2], mis=o % 128,
                        ptr=u32(b, h[0] + 24), extra=tb[2] % 164)
        elif t == ANIM_ID:
            h, ab, eb = kids(b, o + 8, o + 8 + s)
            anims = [b[ab[0] + 8 + 52 * i:ab[0] + 8 + 52 * (i + 1)]
                     for i in range(ab[2] // 52)]
            ents = [b[eb[0] + 8 + 16 * i:eb[0] + 8 + 16 * (i + 1)]
                    for i in range(eb[2] // 16)]
            k = sc.anim_pack(anims, ents, version=u32(b, h[0] + 8),
                             ptr=u32(b, h[0] + 12),
                             pad=(u32(b, h[0] + 16), u32(b, h[0] + 20)),
                             aextra=ab[2] % 52, eextra=eb[2] % 16)
        else:
            k = sc.raw(t, min(s, 64))
        out.append((k, t))
    return out


def disc_hashes(rel):
    b = (EXTRACTED / rel).read_bytes()
    out = []
    for (o, t, s) in kids(b, 0, len(b)):
        if t == PACK_ID:
            h, tb, db = kids(b, o + 8, o + 8 + s)
            out += [u32(b, tb[0] + 8 + 164 * i + 32)
                    for i in range(tb[2] // 164)]
    return out


def disc_anims(rel):
    b = (EXTRACTED / rel).read_bytes()
    out = []
    for (o, t, s) in kids(b, 0, len(b)):
        if t == ANIM_ID:
            h, ab, eb = kids(b, o + 8, o + 8 + s)
            out += [u32(b, ab[0] + 8 + 52 * i + 24)
                    for i in range(ab[2] // 52)]
    return out


# ================================================================ scenarios


def scenario_guards(sc):
    sc.tag("guards")
    near = [0, 1, PACK_ID, ANIM_ID, PACK_ID ^ 1, PACK_ID + 1, PACK_ID - 1,
            ANIM_ID + 1, ANIM_ID - 1, ANIM_ID ^ 0x100, PACK_ID & 0x7fffffff,
            ANIM_ID & 0x7fffffff, 0x30300002, 0x30300101, 0xb0310001,
            0xb0200001, 0xa0300001, 0xf0300001, 0xb0300000, 0xb0300101,
            0xb0300200, 0x80034000, 0x00034202, 0xffffffff]
    for t in near:
        if t in (PACK_ID, ANIM_ID):
            continue
        k = sc.raw(t, 40)
        sc.op(OP_LOAD, k, 0)
        sc.op(OP_LOAD, k, 1)


def scenario_basic(sc):
    """Two packs with a shared name, parents, ranges and flipbooks."""
    sc.tag("basic")
    recs = [
        info_rec("ROAD", img=0, isize=256, pal=256, psize=64),
        info_rec("ROAD_B", img=0, isize=256, pal=320, psize=64,
                 parent=bhash("ROAD")),
        info_rec("NOPAL", img=512, isize=128),
        info_rec("NOIMG", img=0, isize=0, pal=640, psize=64),
        info_rec("PARENT_MISSING", img=640, isize=64, parent=0x1234),
        info_rec("EDGE_LAST", img=1023, isize=1),
        info_rec("EDGE_PAST", img=1024, isize=1),
        info_rec("NEG", img=-1, isize=4, pal=-128, psize=4),
        info_rec("PAL_PAST", img=16, isize=4, pal=5000, psize=64),
        info_rec("SHARED", img=32, isize=16),
        info_rec("SHARED", img=48, isize=16),
        info_rec("SELFPARENT", img=64, isize=16, parent=bhash("SELFPARENT")),
        info_rec("HUGEPL", img=0x7ffffff8, isize=4, pal=0x7ffffffc, psize=4),
    ]
    # The payload is 100 past a boundary: 28 bytes of pad, and 1024 left.
    a = sc.pack(b"BASIC", recs, 1024 + 28, mis=0)
    recs2 = [
        info_rec("SHARED", img=0, isize=16),
        info_rec("OTHER", img=16, isize=16, pal=32, psize=16),
        info_rec("ROAD", img=48, isize=16),
    ]
    b = sc.pack(b"SECOND", recs2, 300, mis=64)
    sc.op(OP_LOAD, a, 0)
    sc.op(OP_RECS, a)
    sc.op(OP_DUMP)
    sc.op(OP_LOAD, b, 0)
    sc.op(OP_RECS, a)
    sc.op(OP_RECS, b)
    sc.op(OP_HDRS)
    sc.op(OP_DUMP)
    for name in ("ROAD", "SHARED", "ROAD", "OTHER", "NOPAL", "NOIMG",
                 "EDGE_LAST", "EDGE_PAST", "NEG", "PAL_PAST", "SHARED",
                 "ROAD_B", "SELFPARENT", "NOPE"):
        sc.op(OP_GTI, bhash(name), 0)
        sc.op(OP_DUMP)
    for n in range(-2, 18):
        sc.op(OP_GNTI, n)
    sc.op(OP_RECS, a)
    sc.op(OP_RECS, b)
    return a, b


def scenario_rounding(sc):
    """The blob's rounding: every misalignment, and blobs shorter than the
    pad."""
    sc.tag("rounding")
    ks = []
    for mis in range(0, 128, 4):
        recs = [info_rec("R%d_0" % mis, img=0, isize=8),
                info_rec("R%d_1" % mis, img=40, isize=8, pal=48, psize=8),
                info_rec("R%d_2" % mis, img=90, isize=8)]
        blob = (100 + mis * 3) % 211
        k = sc.pack(("RND%d" % mis).encode(), recs, blob, mis=mis,
                    extra=mis % 164)
        sc.op(OP_LOAD, k, 0)
        sc.op(OP_RECS, k)
        ks.append(k)
    sc.op(OP_DUMP)
    for k in reversed(ks):
        sc.op(OP_LOAD, k, 1)
    sc.op(OP_DUMP)


def scenario_names(sc):
    sc.tag("names")
    ks = []
    for nm in (b"", b"A", b"FIFTEEN_CHARS_X", b"SIXTEEN_CHARS_XY",
               b"\xe9\xff\x80LATIN"):
        k = sc.pack(nm, [info_rec("N" + str(len(nm)), img=0, isize=4)], 64)
        sc.op(OP_LOAD, k, 0)
        ks.append(k)
    sc.op(OP_DUMP)
    for k in ks:
        sc.op(OP_LOAD, k, 1)
    sc.op(OP_DUMP)


def scenario_tables(sc):
    """Sizes: no records, a record's worth less a byte, extra bytes."""
    sc.tag("tables")
    ks = []
    k = sc.pack(b"EMPTY", [], 0)
    ks.append(k)
    k = sc.pack(b"EMPTYEXTRA", [], 0, extra=163)
    ks.append(k)
    k = sc.pack(b"ONEPLUS", [info_rec("ONE", img=0, isize=4)], 8, extra=1)
    ks.append(k)
    k = sc.pack(b"BIGBLOB", [info_rec("BIG%d" % i, img=i * 1000, isize=10,
                                      pal=i * 1000 + 500, psize=4)
                             for i in range(40)], 40000, mis=12)
    ks.append(k)
    for k in ks:
        sc.op(OP_LOAD, k, 0)
        sc.op(OP_RECS, k)
    sc.op(OP_DUMP)
    sc.op(OP_GNTI, 0)
    sc.op(OP_GNTI, 1)
    sc.op(OP_GNTI, 40)
    sc.op(OP_GNTI, 41)
    for k in reversed(ks):
        sc.op(OP_LOAD, k, 1)
    sc.op(OP_DUMP)


def scenario_garbage(sc):
    """Records whose runtime words are not 0 on the way in: the lookup in
    AttachTextureTable finds a later record of the same pack by them."""
    sc.tag("garbage")
    recs = [info_rec("G0", img=0, isize=4, garbage=0xdead0010),
            info_rec("G1", img=8, isize=4, garbage=0xdead0020),
            info_rec("G0", img=16, isize=4, garbage=0xdead0030),
            info_rec("G2", img=24, isize=4, pal=28, psize=4,
                     garbage=0xdead0040),
            info_rec("G3", img=4000, isize=4, garbage=0xdead0050)]
    k = sc.pack(b"GARBAGE", recs, 128, ptr=0xdeadbeef)
    k2 = sc.pack(b"GARBAGE2", [info_rec("G2", img=0, isize=4,
                                        garbage=0xdead0060),
                               info_rec("G3", img=0, isize=4,
                                        garbage=0xdead0070)], 64)
    sc.op(OP_LOAD, k2, 0)
    sc.op(OP_LOAD, k, 0)
    sc.op(OP_RECS, k)
    sc.op(OP_RECS, k2)
    sc.op(OP_HDRS)
    sc.op(OP_DUMP)
    for name in ("G0", "G1", "G2", "G3", "G2"):
        sc.op(OP_GTI, bhash(name), 0)
    sc.op(OP_DUMP)
    sc.op(OP_LOAD, k, 1)
    sc.op(OP_LOAD, k2, 1)
    sc.op(OP_DUMP)
    sc.op(OP_RECS, k)


def scenario_default(sc):
    """Misses: the render targets, then the default, then bBreak."""
    sc.tag("default")
    sc.op(OP_GTI, 0x11111111, 0)
    sc.op(OP_GTI, 0x11111111, 1)
    sc.op(OP_GTI, DEFAULT, 0)
    sc.op(OP_GTI, DEFAULT, 1)
    sc.op(OP_DUMP)
    sc.op(OP_RTSET, 0x22222222)
    sc.op(OP_RTSET, DEFAULT)
    sc.op(OP_GTI, 0x22222222, 1)
    sc.op(OP_GTI, 0x22222222, 0)
    sc.op(OP_GTI, 0x11111111, 1)
    sc.op(OP_GTI, 0x11111111, 0)
    k = sc.pack(b"DEFAULTS", [info_rec("X", hash_=DEFAULT, img=0, isize=4),
                              info_rec("RT", hash_=0x22222222, img=4,
                                       isize=4)], 64)
    sc.op(OP_LOAD, k, 0)
    sc.op(OP_GTI, 0x11111111, 1)
    sc.op(OP_GTI, 0x22222222, 1)
    sc.op(OP_GTI, 0x33333333, 2)
    sc.op(OP_GTI, 0, 1)
    sc.op(OP_DUMP)
    sc.op(OP_LOAD, k, 1)
    sc.op(OP_DUMP)


def scenario_direct(sc, a, b):
    """The methods called directly on the basic packs (a<0> and a<1>)."""
    sc.tag("direct")
    for which in (0, 1):
        for name in ("ROAD", "SHARED", "NOIMG", "NOPE", "EDGE_PAST"):
            sc.op(OP_GLT, 0, which, bhash(name))
            sc.op(OP_GLT, 1, which, bhash(name))
    for n in (-1, 0, 1, 2, 3, 11, 12, 13):
        sc.op(OP_GLT, 2, 0, n)
        sc.op(OP_GLT, 2, 1, n)
    sc.op(OP_UNASSIGN, 0, 0, 300)
    sc.op(OP_RECS, a)
    sc.op(OP_DUMP)
    sc.op(OP_ASSIGN, 0, a, 200, 100, 200)
    sc.op(OP_RECS, a)
    sc.op(OP_UNASSIGN, 0, 256, 1)
    sc.op(OP_UNASSIGN, 0, 1023, -5)
    sc.op(OP_RECS, a)
    sc.op(OP_ASSIGN, 0, a, 0, 0x7ffffff0, 0x20)
    sc.op(OP_ASSIGN, 0, a, 8, -1, 2)
    sc.op(OP_RECS, a)
    sc.op(OP_UNASSIGN, 0, -0x7fffffff, 0x7fffffff)
    sc.op(OP_RECS, a)
    sc.op(OP_ASSIGN, 0, a, 100, 0, 1024)
    sc.op(OP_RECS, a)
    # Assigned alone, between two dumps: the flag is the assign's.
    sc.op(OP_DUMP)
    sc.op(OP_ASSIGN, 0, a, 0, 0, 1024)
    sc.op(OP_DUMP)
    # A record whose sizes went to 0 after it was given its pixels: the
    # unassign passes it by.
    sc.op(OP_RPOKE, a, 0, 0, 0)
    sc.op(OP_RPOKE, a, 0, 1, 0)
    sc.op(OP_UNASSIGN, 0, 0, 1024)
    sc.op(OP_RECS, a)
    sc.op(OP_RPOKE, a, 0, 0, 256)
    sc.op(OP_RPOKE, a, 0, 1, 64)
    sc.op(OP_ASSIGN, 0, a, 0, 0, 1024)
    sc.op(OP_RECS, a)
    # A table attached twice, then with fewer, none, and a negative count.
    sc.op(OP_ATTACH, 1, b, 3)
    sc.op(OP_RECS, b)
    sc.op(OP_ASSIGN, 1, b, 0, 0, 64)
    sc.op(OP_ATTACH, 1, b, 2)
    sc.op(OP_RECS, b)
    sc.op(OP_DUMP)
    sc.op(OP_GNTI, 13)
    sc.op(OP_GNTI, 14)
    sc.op(OP_ATTACH, 1, b, 0)
    sc.op(OP_GNTI, 12)
    sc.op(OP_GNTI, 13)
    sc.op(OP_ATTACH, 1, b, -2)
    sc.op(OP_DUMP)
    for n in (11, 12, 13, 14, 15):
        sc.op(OP_GNTI, n)
    sc.op(OP_ATTACH, 1, b, 3)
    sc.op(OP_ASSIGN, 1, b, 0, 0, 64)


def scenario_destruct(sc, a, b):
    sc.tag("destruct")
    # The second pack: with its table to free, and a streaming load to
    # wait out, and three LoadedTextureData.
    sc.op(OP_POKE, 1, 0, 1)
    sc.op(OP_POKE, 1, 1, 3)
    sc.op(OP_LTD, 1, 1)
    sc.op(OP_LTD, 1, 0)
    sc.op(OP_LTD, 1, 1)
    sc.op(OP_DUMP)
    sc.op(OP_DESTRUCT, 1, 2)
    sc.op(OP_DUMP)
    sc.op(OP_RECS, b)
    sc.op(OP_GTI, bhash("SHARED"), 0)
    sc.op(OP_GTI, bhash("OTHER"), 0)
    sc.op(OP_POKE, 0, 1, 1)
    sc.op(OP_LOAD, a, 1)
    sc.op(OP_DUMP)
    sc.op(OP_RECS, a)
    sc.op(OP_GTI, bhash("ROAD"), 0)
    sc.op(OP_GNTI, 0)
    # Loaded twice: the header keeps the second pack.
    sc.op(OP_LOAD, a, 0)
    sc.op(OP_LOAD, a, 0)
    sc.op(OP_HDRS)
    sc.op(OP_DUMP)
    sc.op(OP_GTI, bhash("ROAD"), 0)
    sc.op(OP_LOAD, a, 1)
    sc.op(OP_DUMP)
    sc.op(OP_GTI, bhash("ROAD"), 0)
    sc.op(OP_GNTI, 12)
    sc.op(OP_RECS, a)


def scenario_flipbooks(sc):
    sc.tag("flipbooks")
    frames = ["F%d" % i for i in range(6)]
    recs = [info_rec(f, img=16 * i, isize=16, pal=512 + 16 * i, psize=16)
            for i, f in enumerate(frames)]
    recs += [info_rec("NOPALF", img=200, isize=16),
             info_rec("UNLOADED", img=5000, isize=16)]
    k = sc.pack(b"FLIPTEX", recs, 1024)
    sc.op(OP_LOAD, k, 0)
    anims = [anim_rec("FLIP", 4, 15, 0, garbage=0xdead0100),
             anim_rec("REAL", 2, 30, 1),
             anim_rec("MISSING", 3, 10, 0),
             anim_rec("ONE", 1, 60, 0),
             anim_rec("TB2", 3, 7, 2),
             anim_rec("NOPAL", 2, 5, 1),
             anim_rec("NEGF", -2, 5, 0)]
    ents = [entry_rec("F0", 0xdead0200), entry_rec("F1"), entry_rec("F2"),
            entry_rec("F3"),
            entry_rec("F4"), entry_rec("F5"),
            entry_rec("F0"), entry_rec("UNLOADED"), entry_rec("F1"),
            entry_rec("F2"),
            entry_rec("F3"), entry_rec("F4"), entry_rec("F5"),
            entry_rec("NOPALF"), entry_rec("F0")]
    f = sc.anim_pack(anims, ents, aextra=51, eextra=15)
    sc.op(OP_LOAD, f, 0)
    sc.op(OP_ANIMS, f)
    sc.op(OP_HDRS)
    sc.op(OP_DUMP)
    for world, real, tweak in ((1, 1, 0), (2, 1, 0), (4, 4, 0), (5, 4, 0),
                               (16, 8, 0), (17, 9, 0), (60, 60, 0),
                               (61, 61, 0), (100, 3, 0), (100, 3, 7),
                               (101, 3, 7), (1000, 2000, 0),
                               (123457, 987654, 0), (1 << 24, 1 << 25, 0),
                               ((1 << 24) + 3, (1 << 25) + 5, 0),
                               (0x7fffffff, 0x7fffffff, 0),
                               (0x7fffffff, 0x7fffffff, 1), (0, 0, 0),
                               # Where fps * t rounds one way in float and
                               # the other in double.
                               (135520873, 253228485, 13),
                               (253228485, 135520873, 7),
                               (3, 3, -1)):
        sc.op(OP_UPDATE, world, real, tweak)
        sc.op(OP_ANIMS, f)
        sc.op(OP_RECS, k)
    for name in ("FLIP", "REAL", "NOPAL", "NONE"):
        sc.op(OP_GTA, bhash(name))
    # Versions other than 1, and garbage in their pointers.
    g = sc.anim_pack([anim_rec("V0", 1, 1)], [entry_rec("F0")], version=0,
                     ptr=0xdead0300)
    h = sc.anim_pack([anim_rec("V2", 1, 1)], [entry_rec("F0")], version=2,
                     ptr=0xdead0400, pad=(0xdead0500, 7))
    e = sc.anim_pack([], [], pad=(1, 2))
    z = sc.anim_pack([anim_rec("ZERO", 0, 5), anim_rec("AFTERZERO", 1, 5)],
                     [entry_rec("F5")])
    for c in (g, h, e, z):
        sc.op(OP_LOAD, c, 0)
    sc.op(OP_HDRS)
    sc.op(OP_ANIMS, z)
    sc.op(OP_DUMP)
    for name in ("V0", "V2", "ZERO", "AFTERZERO"):
        sc.op(OP_GTA, bhash(name))
    sc.op(OP_LOAD, z, 1)
    sc.op(OP_LOAD, g, 1)
    sc.op(OP_LOAD, h, 1)
    sc.op(OP_LOAD, e, 1)
    sc.op(OP_DUMP)
    sc.op(OP_UPDATE, 7, 7, 0)
    sc.op(OP_ANIMS, f)
    # The textures unloaded under the flipbook: it keeps pointing at them.
    sc.op(OP_LOAD, k, 1)
    sc.op(OP_UPDATE, 8, 8, 0)
    sc.op(OP_ANIMS, f)
    sc.op(OP_RECS, k)
    sc.op(OP_LOAD, f, 1)
    sc.op(OP_DUMP)
    sc.op(OP_GTA, bhash("FLIP"))
    # Unloaded without ever being loaded: a version the loader skips with
    # garbage where its pointer goes, and a pack whose pointer is 0.
    u = sc.anim_pack([anim_rec("U2", 1, 1)], [entry_rec("F0")], version=2,
                     ptr=0xdead0600)
    v = sc.pack(b"NEVER", [info_rec("NEVER", img=0, isize=4)], 64)
    sc.op(OP_LOAD, u, 1)
    sc.op(OP_LOAD, v, 1)
    sc.op(OP_HDRS)
    sc.op(OP_DUMP)


def scenario_disc(sc):
    sc.tag("disc")
    loaded = []
    kinds = []
    hashes = []
    anims = []
    for rel in DISC_FILES:
        sc.tag("disc " + rel)
        for k, t in disc_chunks(sc, rel):
            sc.op(OP_LOAD, k, 0)
            loaded.append(k)
            kinds.append((k, t))
            if t == PACK_ID:
                sc.op(OP_RECS, k)
            elif t == ANIM_ID:
                sc.op(OP_ANIMS, k)
        hashes += disc_hashes(rel)
        anims += disc_anims(rel)
        sc.op(OP_DUMP)
    sc.tag("disc lookups")
    for h in hashes:
        sc.op(OP_GTI, h, 0)
    for h in (0x12345678, 0, 0xffffffff):
        sc.op(OP_GTI, h, 1)
    for n in (0, 1, 500, 1000, len(hashes) - 1, len(hashes)):
        sc.op(OP_GNTI, n)
    sc.op(OP_DUMP)
    for h in anims + [0x12345678]:
        sc.op(OP_GTA, h)
    sc.tag("disc flipbooks")
    anim_chunks = [k for k, t in kinds if t == ANIM_ID]
    for world, real in ((1, 1), (2, 3), (5, 8), (13, 21), (600, 601),
                        (36000, 36011)):
        sc.op(OP_UPDATE, world, real, 0)
        for k in anim_chunks:
            sc.op(OP_ANIMS, k)
    for k, t in kinds:
        if t == PACK_ID:
            sc.op(OP_RECS, k)
    sc.op(OP_HDRS)
    sc.tag("disc unload")
    for k in reversed(loaded):
        sc.op(OP_LOAD, k, 1)
    sc.op(OP_DUMP)


def script():
    sc = Script()
    scenario_guards(sc)
    a, b = scenario_basic(sc)
    scenario_direct(sc, a, b)
    scenario_destruct(sc, a, b)
    scenario_rounding(sc)
    scenario_names(sc)
    scenario_tables(sc)
    scenario_garbage(sc)
    scenario_default(sc)
    scenario_flipbooks(sc)
    scenario_disc(sc)
    return sc


# ================================================================ the model


class BigEmu(Emu):
    RAM = 128 << 20


class Model(object):
    def __init__(self, sc):
        self.sc = sc
        self.out = []
        e = self.e = BigEmu(ieee=True)
        self.fn = {k: e.addr_of(v) for k, v in SYM.items()}
        for head in (TPL, TAPL):
            e.put32(head, head)
            e.put32(head + 4, head)
        self.regions = []       # sorted by lo: (lo, base, size, name,
        self.starts = []        #   stride, end_ok, alloc)
        self.chunks = []        # per chunk: dict
        self.allocs = []        # (p, size)
        self.ltds = []
        self.bufs = []
        self.rts = []
        self.rt_infos = e.alloc(164 * 16, 64)
        self.add_region(self.rt_infos, 164 * 16, "rt", 164)
        self.breaks = 0
        self.service = [None, 0]
        self.name = None
        self.recs = []
        self.anims = []
        self.ents = []
        self.stubs()

    def emit(self, s):
        self.out.append(s)

    # ---- the labels ------------------------------------------------------

    def add_region(self, base, size, name, stride=0, end_ok=False,
                   margin=0, alloc=False):
        lo = base - margin
        i = bisect.bisect_right(self.starts, lo)
        self.starts.insert(i, lo)
        self.regions.insert(i, (lo, base, size, name, stride, end_ok, alloc))

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        if a == TPL:
            return "TPL"
        if a == TAPL:
            return "TAPL"
        i = bisect.bisect_right(self.starts, a) - 1
        back = 0
        while i >= 0 and back < 4:
            lo, base, size, name, stride, end_ok, alloc = self.regions[i]
            if a < base + size or (a == base + size and end_ok):
                off = a - base
                if stride:
                    idx, rem = off // stride, off % stride
                    if rem == 0:
                        return "%s.%d" % (name, idx)
                    return "%s.%d+%d" % (name, idx, rem)
                if off == 0:
                    return name
                if alloc and off == LTD_OFF:
                    return name + ".ltd"
                return "%s+%d" % (name, off)
            i -= 1
            back += 1
        return "x%08x" % a

    # ---- the stubs -------------------------------------------------------

    def cstr(self, a, n=64):
        b = bytearray()
        while len(b) < n and self.e.mem[a]:
            b.append(self.e.mem[a])
            a += 1
        return b.decode("latin-1")

    def stubs(self):
        e = self.e

        def arg(i):
            return e.reg[4 + i] & M32

        def malloc(em):
            size, name = s32(arg(0)), self.cstr(arg(1))
            p = e.alloc(size + 16, 16)
            e.mem[p:p + size] = b"\xcd" * size
            k = len(self.allocs)
            self.allocs.append(p)
            self.add_region(p, size, "a%d" % k, alloc=True)
            self.emit("  malloc %s a%d" % (name, k))
            return p

        def free(em):
            self.emit("  free %s" % self.label(arg(0)))
            return 0

        def brk(em):
            self.breaks += 1

        def rt(em):
            h = arg(0)
            r = (self.rt_infos + 164 * self.rts.index(h)
                 if h in self.rts else 0)
            self.emit("  rt %08x %s" % (h, self.label(r)))
            return r

        def sqf(em):
            p, n = self.service
            self.service[1] = n - 1
            self.emit("  sqf %d" % (n - 1))
            if n - 1 <= 0 and p is not None:
                e.put32(p + 120, 0)
            return 0

        e.stub("bMalloc__FiPCcii", malloc)
        e.stub("bFree__FPv", free)
        e.stub("bBreak__Fv", brk)
        e.stub("eGetRenderTargetTextureInfo__Fi", rt)
        e.stub("ServiceQueuedFiles__Fv", sqf)
        e.stub("bFunkCallASync__FPCcUcPCvl", lambda em: 0)
        e.stub("bRemoveCodeineInventory__Fi", lambda em: 0)

    def call(self, name, *args):
        # The EE keeps a 32-bit value sign-extended in its register.
        return self.e.call(self.fn[name], *[s32(v & M32) for v in args],
                           limit=2000000000)

    # ---- the chunks ------------------------------------------------------

    def place(self, total, mis):
        raw = self.e.alloc(PRE + total + POST, 128)
        return raw + PRE + mis

    def build_pack(self, mis, ptr, extra, blob):
        e = self.e
        k = len(self.chunks)
        recs = self.recs
        tsize = 164 * len(recs) + extra
        total = 8 + 28 + 8 + tsize + 8 + blob
        c = self.place(total, mis)
        e.write(c, struct.pack("<II", PACK_ID, total - 8))
        e.write(c + 8, struct.pack("<II", 0x30300002, 20) + self.name
                + struct.pack("<I", ptr))
        t = c + 36
        e.write(t, struct.pack("<II", 0x30300003, tsize))
        e.write(t + 8, b"".join(recs) + b"\x77" * extra)
        d = t + 8 + tsize
        e.write(d, struct.pack("<II", 0x30300004, blob))
        self.add_region(c + 16, 20, "h%d" % k)
        self.add_region(t + 8, 164 * len(recs), "t%d" % k, 164, True,
                        MARGIN * 164)
        self.add_region(d + 8, blob + SLACK, "d%d" % k, 0, True)
        self.chunks.append(dict(kind="pack", p=c, t=t + 8, n=len(recs),
                                d=d + 8))
        self.recs = []

    def build_anim(self, version, ptr, pad0, pad1, aextra, eextra):
        e = self.e
        k = len(self.chunks)
        asize = 52 * len(self.anims) + aextra
        esize = 16 * len(self.ents) + eextra
        total = 8 + 24 + 8 + asize + 8 + esize
        c = self.place(total, 0)
        e.write(c, struct.pack("<II", ANIM_ID, total - 8))
        e.write(c + 8, struct.pack("<IIiIII", 0x30300101, 16, version, ptr,
                                   pad0, pad1))
        a = c + 32
        e.write(a, struct.pack("<II", 0x30300102, asize))
        e.write(a + 8, b"".join(self.anims) + b"\x66" * aextra)
        en = a + 8 + asize
        e.write(en, struct.pack("<II", 0x30300103, esize))
        e.write(en + 8, b"".join(self.ents) + b"\x55" * eextra)
        self.add_region(c + 16, 16, "h%d" % k)
        self.add_region(a + 8, 52 * len(self.anims), "A%d" % k, 52, True)
        self.add_region(en + 8, 16 * len(self.ents), "E%d" % k, 16, True)
        self.chunks.append(dict(kind="anim", p=c, a=a + 8,
                                na=len(self.anims), e=en + 8,
                                ne=len(self.ents)))
        self.anims = []
        self.ents = []

    def build_raw(self, t, size):
        c = self.place(8 + size, 0)
        self.e.write(c, struct.pack("<II", t, size) + b"\xa5" * size)
        self.chunks.append(dict(kind="raw", p=c))

    # ---- the dumps -------------------------------------------------------

    def walk(self, head):
        e = self.e
        out = []
        n = e.u32(head)
        while n != head and len(out) < 10000:
            out.append(n)
            n = e.u32(n)
        return out

    def dump(self):
        e, L = self.e, self.label
        packs = self.walk(TPL)
        self.emit("  packs%s tail %s" % ("".join(" " + L(p) for p in packs),
                                           L(e.u32(TPL + 4))))
        for p in packs:
            ltd = self.walk(p + LTD_OFF)
            self.emit("  pack %s prev %s name %s hash %08x inv %08x info %s "
                      "num %d free %d pos %d cur %s nyl %d pool %d ltd %s"
                      % (L(p), L(e.u32(p + 4)),
                         self.cstr(p + 8, 32).encode("latin-1").hex() or "-",
                         e.u32(p + 88), e.u32(p + 92), L(e.u32(p + 96)),
                         s32(e.u32(p + 100)), s32(e.u32(p + 104)),
                         s32(e.u32(p + 108)), L(e.u32(p + 120)),
                         s32(e.u32(p + 124)), s32(e.u32(p + 128)),
                         " ".join(L(n) for n in ltd) or "-"))
        aps = self.walk(TAPL)
        self.emit("  apacks%s tail %s" % ("".join(" " + L(p) for p in aps),
                                            L(e.u32(TAPL + 4))))
        for p in aps:
            self.emit("  apack %s prev %s anims %s ents %s na %d ne %d"
                      % (L(p), L(e.u32(p + 4)), L(e.u32(p + 8)),
                         L(e.u32(p + 12)), s32(e.u32(p + 16)),
                         s32(e.u32(p + 20))))
        # Cleared, so the next dump shows whether anything set it again.
        self.emit("  dirty %d breaks %d" % (s32(e.u32(DIRTY_TEXTURES)),
                                             self.breaks))
        e.put32(DIRTY_TEXTURES, 0)

    def dump_recs(self, k):
        e, L = self.e, self.label
        c = self.chunks[k]
        for i in range(c["n"]):
            r = c["t"] + 164 * i
            self.emit("  t%d.%d %08x %s %s used %d pack %s parent %s img %s "
                      "pal %s act %s stk %s vram %d %d"
                      % (k, i, e.u32(r + 32), L(e.u32(r)), L(e.u32(r + 4)),
                         e.mem[r + 120], L(e.u32(r + 136)),
                         L(e.u32(r + 140)), L(e.u32(r + 144)),
                         L(e.u32(r + 148)), L(e.u32(r + 152)),
                         L(e.u32(r + 156)), e.u16(r + 160), e.u16(r + 162)))

    def dump_anims(self, k):
        e, L = self.e, self.label
        c = self.chunks[k]
        for i in range(c["na"]):
            a = c["a"] + 52 * i
            self.emit("  A%d.%d %08x nf %d fps %d tb %d tab %s valid %d "
                      "cur %d" % (k, i, e.u32(a + 24), s32(e.u32(a + 28)),
                                  s32(e.u32(a + 32)), s32(e.u32(a + 36)),
                                  L(e.u32(a + 40)), s32(e.u32(a + 44)),
                                  s32(e.u32(a + 48))))
        for i in range(c["ne"]):
            en = c["e"] + 16 * i
            self.emit("  E%d.%d %08x ti %s img %s pal %s"
                      % (k, i, e.u32(en), L(e.u32(en + 4)),
                         L(e.u32(en + 8)), L(e.u32(en + 12))))

    def dump_hdrs(self):
        e, L = self.e, self.label
        for k, c in enumerate(self.chunks):
            if c["kind"] == "pack":
                self.emit("  h%d %s" % (k, L(e.u32(c["p"] + 32))))
            elif c["kind"] == "anim":
                self.emit("  h%d v%d %s %08x %08x"
                          % (k, s32(e.u32(c["p"] + 16)),
                             L(e.u32(c["p"] + 20)), e.u32(c["p"] + 24),
                             e.u32(c["p"] + 28)))

    # ---- the run ---------------------------------------------------------

    def run(self):
        e, sc = self.e, self.sc
        for o in sc.ops:
            code, a = o[0], o[1:]
            if code == OP_TAG:
                self.emit("[%s]" % sc.tags[a[0]])
            elif code == OP_NAME:
                self.name = struct.pack("<4I", *[w & M32 for w in a])
            elif code == OP_REC:
                self.recs.append(struct.pack("<41I", *[w & M32 for w in a]))
            elif code == OP_PACK:
                self.build_pack(*a)
            elif code == OP_ANIM:
                self.anims.append(struct.pack("<13I",
                                              *[w & M32 for w in a]))
            elif code == OP_ENTRY:
                self.ents.append(struct.pack("<4I", *[w & M32 for w in a]))
            elif code == OP_APACK:
                self.build_anim(*a)
            elif code == OP_RAW:
                self.build_raw(a[0] & M32, a[1])
            elif code == OP_LOAD:
                r = self.call("unload" if a[1] else "load",
                              self.chunks[a[0]]["p"])
                self.emit("  %s c%d ret %d" % ("unload" if a[1] else "load",
                                               a[0], r))
            elif code == OP_GTI:
                r = self.call("gti", a[0] & M32, a[1])
                self.emit("  gti %08x %d %s" % (a[0] & M32, a[1],
                                                self.label(r)))
            elif code == OP_GNTI:
                r = self.call("gnti", a[0])
                self.emit("  gnti %d %s" % (a[0], self.label(r)))
            elif code == OP_GLT:
                name = ("glt", "gt", "gnt")[a[0]]
                r = self.call(name, self.allocs[a[1]], a[2] & M32)
                self.emit("  %s a%d %08x %s" % (name, a[1], a[2] & M32,
                                                self.label(r)))
            elif code == OP_ASSIGN:
                c = self.chunks[a[1]]
                self.call("assign", self.allocs[a[0]], c["d"] + a[2], a[3],
                          a[4])
            elif code == OP_UNASSIGN:
                self.call("unassign", self.allocs[a[0]], a[1], a[2])
            elif code == OP_ATTACH:
                self.call("attach", self.allocs[a[0]],
                          self.chunks[a[1]]["t"], a[2])
            elif code == OP_DESTRUCT:
                p = self.allocs[a[0]]
                self.service[0] = p
                self.call("destruct", p, a[1])
                self.emit("  destruct a%d %d info %s"
                          % (a[0], a[1], self.label(e.u32(p + 96))))
            elif code == OP_POKE:
                p = self.allocs[a[0]]
                if a[1] == 0:
                    e.put32(p + 104, a[2])
                else:
                    e.put32(p + 120, 0x1234 if a[2] else 0)
                    self.service = [p, a[2]]
            elif code == OP_LTD:
                p = self.allocs[a[0]]
                n = e.alloc(44, 16)
                k = len(self.ltds)
                self.ltds.append(n)
                self.add_region(n, 44, "L%d" % k)
                e.mem[n:n + 44] = bytes(44)
                if a[1]:
                    b = e.alloc(16, 16)
                    self.add_region(b, 16, "B%d" % len(self.bufs))
                    self.bufs.append(b)
                    e.put32(n + 24, b)
                head = p + LTD_OFF
                last = e.u32(head + 4)
                e.put32(last, n)
                e.put32(head + 4, n)
                e.put32(n + 4, last)
                e.put32(n, head)
            elif code == OP_RTSET:
                self.rts.append(a[0] & M32)
            elif code == OP_UPDATE:
                e.put32(WORLD_FRAMES, a[0])
                e.put32(REAL_FRAMES, a[1])
                e.put32(TWEAK_FPS, a[2])
                self.call("update")
                self.emit("  update %d %d %d" % tuple(a))
            elif code == OP_GTA:
                r = self.call("gta", a[0] & M32)
                self.emit("  gta %08x %s" % (a[0] & M32, self.label(r)))
            elif code == OP_DUMP:
                self.dump()
            elif code == OP_RECS:
                self.dump_recs(a[0])
            elif code == OP_ANIMS:
                self.dump_anims(a[0])
            elif code == OP_RPOKE:
                r = self.chunks[a[0]]["t"] + 164 * a[1]
                e.put32(r + (56 if a[2] == 0 else 60), a[3])
            elif code == OP_HDRS:
                self.dump_hdrs()
            else:
                raise ValueError("op %d" % code)
        self.call("maybe")
        return self.out


def model(sc):
    return Model(sc).run()


# ================================================================ the build


def build_harness(tmp, name="texturepack_test"):
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
    # The loader.
    ("load_round_64", TPC,
     "(((uintptr_t)payload + 127u)\n                                    & ~(uintptr_t)127u)",
     "(((uintptr_t)payload + 63u)\n                                    & ~(uintptr_t)63u)"),
    ("load_no_round", TPC,
     "(((uintptr_t)payload + 127u)\n                                    & ~(uintptr_t)127u)",
     "((uintptr_t)payload)"),
    ("load_size_whole", TPC,
     "(int32_t)bchunk_u32(blob + 4)\n                       - (int32_t)(data - payload)",
     "(int32_t)bchunk_u32(blob + 4)"),
    ("load_num_ceil", TPC,
     "(int32_t)(bchunk_u32(table + 4)\n                                / (uint32_t)sizeof(TextureInfo))",
     "(int32_t)((bchunk_u32(table + 4) + (uint32_t)sizeof(TextureInfo) - 1)\n                                / (uint32_t)sizeof(TextureInfo))"),
    ("load_no_header_ptr", TPC, "        h->pTexturePack = p;\n", ""),
    ("load_assign_pos1", TPC,
     "texturepack_assign_texture_data(p, data, 0, size);",
     "texturepack_assign_texture_data(p, data, 1, size);"),
    ("load_anim_any_version", TPC, "        if (h->Version == 1) {",
     "        if (h->Version != 0) {"),
    ("load_anim_keep_ptr", TPC,
     "        } else {\n            h->pTextureAnimPack = NULL;\n        }", "        }"),
    ("load_anim_no_init", TPC, "            textureanimpack_init_anims(p);\n",
     ""),
    ("load_anim_ret0", TPC,
     "            textureanimpack_init_anims(p);\n        } else {\n            h->pTextureAnimPack = NULL;\n        }\n        return 1;",
     "            textureanimpack_init_anims(p);\n        } else {\n            h->pTextureAnimPack = NULL;\n        }\n        return 0;"),
    ("load_other_ret1", TPC, "        return 1;\n    }\n    return 0;\n}\n\nint unloader",
     "        return 1;\n    }\n    return 1;\n}\n\nint unloader"),
    ("unload_any_version", TPC,
     "        if (h->Version == 1 && h->pTextureAnimPack != NULL)",
     "        if (h->pTextureAnimPack != NULL)"),
    ("unload_pack_flags1", TPC, "texturepack_destruct(h->pTexturePack, 3);",
     "texturepack_destruct(h->pTexturePack, 2);"),
    ("unload_anim_flags2", TPC,
     "textureanimpack_destruct(h->pTextureAnimPack, 3);",
     "textureanimpack_destruct(h->pTextureAnimPack, 2);"),
    ("unload_pack_ret0", TPC,
     "            texturepack_destruct(h->pTexturePack, 3);\n        return 1;",
     "            texturepack_destruct(h->pTexturePack, 3);\n        return 0;"),
    ("unload_clears_ptr", TPC,
     "            texturepack_destruct(h->pTexturePack, 3);\n",
     "            texturepack_destruct(h->pTexturePack, 3);\n        h->pTexturePack = NULL;\n"),
    # The constructor and destructor.
    ("ctor_name_15", TPC, "i < (int)sizeof p->Name - 1; i++)",
     "i < 15; i++)"),
    ("ctor_pool_0", TPC, "    p->MemoryPool = 64;", "    p->MemoryPool = 0;"),
    ("ctor_no_nyl", TPC, "    p->NumNotYetLoadedTextureDatas = 0;\n", ""),
    ("ctor_link_head", TPC,
     "    link_tail(&TexturePackList, &p->Node);",
     "    p->Node.next = TexturePackList.next;\n    p->Node.prev = &TexturePackList;\n    TexturePackList.next->prev = &p->Node;\n    TexturePackList.next = &p->Node;"),
    ("ctor_inv_format", TPC, '"TexturePack,%s"', '"TexturePack%s"'),
    ("ctor_hash_of_given", TPC, "    p->NameHash = bchunk_hash(p->Name);",
     "    p->NameHash = bchunk_hash(name);"),
    ("dtor_no_wait", TPC,
     "    while (p->CurrentLoadingTextureData != NULL\n           && gServiceQueuedFilesFn != NULL)\n        gServiceQueuedFilesFn();\n",
     ""),
    ("dtor_wait_once", TPC,
     "    while (p->CurrentLoadingTextureData != NULL\n           && gServiceQueuedFilesFn != NULL)",
     "    if (p->CurrentLoadingTextureData != NULL\n           && gServiceQueuedFilesFn != NULL)"),
    ("dtor_keep_info", TPC,
     "        bFree(p->pTextureInfo);\n        p->pTextureInfo = NULL;",
     "        bFree(p->pTextureInfo);"),
    ("dtor_always_free_info", TPC, "    if (p->pTextureInfoNeedsToBeFreed) {",
     "    if (1) {"),
    ("dtor_no_ltd", TPC,
     "        loadedtexturedata_destruct((LoadedTextureData *)(void *)n, 3);",
     ""),
    ("dtor_ltd_keep_buf", TPC,
     "    if (d->Buf != NULL)\n        bFree(d->Buf);\n", ""),
    ("dtor_ltd_flags2", TPC,
     "        loadedtexturedata_destruct((LoadedTextureData *)(void *)n, 3);",
     "        loadedtexturedata_destruct((LoadedTextureData *)(void *)n, 2);"),
    ("dtor_free_flag2", TPC, "    if (flags & 1)\n        bFree(p);\n}\n\nvoid texturepack_attach",
     "    if (flags & 2)\n        bFree(p);\n}\n\nvoid texturepack_attach"),
    ("dtor_no_unlink", TPC,
     "    list_unlink(&p->Node);\n    // bRemoveCodeineInventory", "    // bRemoveCodeineInventory"),
    # AttachTextureTable.
    ("attach_no_lookup", TPC, "        (void)GetTextureInfo(t->NameHash, 0);\n",
     ""),
    ("attach_lookup_default", TPC, "(void)GetTextureInfo(t->NameHash, 0);",
     "(void)GetTextureInfo(t->NameHash, 1);"),
    ("attach_self_null", TPC, "            t->pImageParent = t;",
     "            t->pImageParent = NULL;"),
    ("attach_parent_global", TPC,
     "t->pImageParent = texturepack_get_texture(p, t->ImageParentHash);",
     "t->pImageParent = GetTextureInfo(t->ImageParentHash, 0);"),
    ("attach_keep_image", TPC, "        t->ImageData = NULL;\n", ""),
    ("attach_keep_palette", TPC, "        t->PaletteData = NULL;\n", ""),
    ("attach_keep_active", TPC, "        t->pActiveTexture = NULL;\n", ""),
    ("attach_clear_stacked", TPC, "        t->pActiveTexture = NULL;\n",
     "        t->pActiveTexture = NULL;\n        t->pStackedActiveTexture = NULL;\n"),
    ("attach_keep_vram", TPC,
     "        t->PaletteVramAddress = 0;\n        t->ImageVramAddress = 0;\n", ""),
    ("attach_no_dirty", TPC, "    }\n    eDirtyTextures = 1;\n}\n\nvoid texturepack_assign",
     "    }\n}\n\nvoid texturepack_assign"),
    ("attach_num_after", TPC,
     "    p->pTextureInfo = table;\n    p->NumTextures = num;\n    for (n = num; n > 0; n--, t++) {",
     "    p->pTextureInfo = table;\n    p->NumTextures = 0;\n    for (n = num; n > 0; n--, t++) {"),
    # AssignTextureData and UnAssignTextureData.
    ("assign_gt_pos", TPC,
     "        if (t->ImageSize != 0 && t->ImagePlacement >= pos\n            && t->ImagePlacement < end)\n            t->ImageData = data",
     "        if (t->ImageSize != 0 && t->ImagePlacement > pos\n            && t->ImagePlacement < end)\n            t->ImageData = data"),
    ("assign_le_end", TPC,
     "            && t->ImagePlacement < end)\n            t->ImageData = data",
     "            && t->ImagePlacement <= end)\n            t->ImageData = data"),
    ("assign_no_size", TPC,
     "        if (t->ImageSize != 0 && t->ImagePlacement >= pos\n            && t->ImagePlacement < end)\n            t->ImageData = data",
     "        if (t->ImagePlacement >= pos\n            && t->ImagePlacement < end)\n            t->ImageData = data"),
    ("assign_no_palsize", TPC,
     "        if (t->PaletteSize != 0 && t->PalettePlacement >= pos\n            && t->PalettePlacement < end)\n            t->PaletteData = data",
     "        if (t->PalettePlacement >= pos\n            && t->PalettePlacement < end)\n            t->PaletteData = data"),
    ("assign_pal_from_image", TPC,
     "            t->PaletteData = data + (t->PalettePlacement - pos);",
     "            t->PaletteData = data + (t->ImagePlacement - pos);"),
    ("assign_no_offset", TPC,
     "            t->ImageData = data + (t->ImagePlacement - pos);",
     "            t->ImageData = data + t->ImagePlacement;"),
    ("assign_no_dirty", TPC,
     "            t->PaletteData = data + (t->PalettePlacement - pos);\n    }\n    eDirtyTextures = 1;",
     "            t->PaletteData = data + (t->PalettePlacement - pos);\n    }"),
    ("unassign_gt_pos", TPC,
     "        if (t->ImageSize != 0 && t->ImagePlacement >= pos\n            && t->ImagePlacement < end)\n            t->ImageData = NULL;",
     "        if (t->ImageSize != 0 && t->ImagePlacement > pos\n            && t->ImagePlacement < end)\n            t->ImageData = NULL;"),
    ("unassign_le_end", TPC,
     "            && t->ImagePlacement < end)\n            t->ImageData = NULL;",
     "            && t->ImagePlacement <= end)\n            t->ImageData = NULL;"),
    ("unassign_no_palette", TPC,
     "            && t->PalettePlacement < end)\n            t->PaletteData = NULL;",
     "            && t->PalettePlacement < end)\n            ;"),
    ("unassign_no_size", TPC,
     "        if (t->ImageSize != 0 && t->ImagePlacement >= pos\n            && t->ImagePlacement < end)\n            t->ImageData = NULL;",
     "        if (t->ImagePlacement >= pos\n            && t->ImagePlacement < end)\n            t->ImageData = NULL;"),
    ("unassign_no_dirty", TPC,
     "            t->PaletteData = NULL;\n    }\n    eDirtyTextures = 1;",
     "            t->PaletteData = NULL;\n    }"),
    ("assign_end_nowrap", TPC,
     "                                     int32_t pos, int32_t size)\n{\n    int32_t end = add32(pos, size);",
     "                                     int32_t pos, int32_t size)\n{\n    int32_t end = (int32_t)((int64_t)pos + size > 0x7fffffff ? 0x7fffffff : pos + size);"),
    # The per-pack lookups.
    ("glt_no_palette_check", TPC,
     "        if (t->NameHash == hash && t->ImageData != NULL\n            && (t->PaletteSize == 0 || t->PaletteData != NULL))",
     "        if (t->NameHash == hash && t->ImageData != NULL)"),
    ("glt_no_image_check", TPC,
     "        if (t->NameHash == hash && t->ImageData != NULL\n",
     "        if (t->NameHash == hash\n"),
    ("glt_palette_always", TPC,
     "            && (t->PaletteSize == 0 || t->PaletteData != NULL))",
     "            && t->PaletteData != NULL)"),
    ("gt_last", TPC,
     "    for (i = 0; i < p->NumTextures; i++) {\n        if (p->pTextureInfo[i].NameHash == hash)",
     "    for (i = p->NumTextures - 1; i >= 0; i--) {\n        if (p->pTextureInfo[i].NameHash == hash)"),
    ("glt_last", TPC,
     "    for (i = 0; i < p->NumTextures; i++) {\n        TextureInfo *t = &p->pTextureInfo[i];\n\n        if (t->NameHash == hash && t->ImageData != NULL",
     "    for (i = p->NumTextures - 1; i >= 0; i--) {\n        TextureInfo *t = &p->pTextureInfo[i];\n\n        if (t->NameHash == hash && t->ImageData != NULL"),
    ("gnt_le", TPC, "    if (n < p->NumTextures)\n        return &p->pTextureInfo[n];",
     "    if (n <= p->NumTextures)\n        return &p->pTextureInfo[n];"),
    ("gnt_nonneg", TPC,
     "    if (n < p->NumTextures)\n        return &p->pTextureInfo[n];",
     "    if (n >= 0 && n < p->NumTextures)\n        return &p->pTextureInfo[n];"),
    # GetTextureInfo and GetNthTextureInfo.
    ("gti_no_front", TPC,
     "            list_unlink(n);\n            n->next = TexturePackList.next;\n            TexturePackList.next->prev = n;\n            TexturePackList.next = n;\n            n->prev = &TexturePackList;\n",
     ""),
    ("gti_to_back", TPC,
     "            list_unlink(n);\n            n->next = TexturePackList.next;\n            TexturePackList.next->prev = n;\n            TexturePackList.next = n;\n            n->prev = &TexturePackList;\n",
     "            list_unlink(n);\n            link_tail(&TexturePackList, n);\n"),
    ("gti_no_used", TPC, "            t->UsedFlag = 1;\n", ""),
    ("gti_no_rt", TPC,
     "    t = gERenderTargetTextureInfoFn != NULL\n        ? gERenderTargetTextureInfoFn(hash) : NULL;",
     "    t = NULL;"),
    ("gti_rt_after_default", TPC,
     "    if (t != NULL)\n        return t;\n    if (!use_default)\n        return NULL;\n    t = GetTextureInfo(DEFAULT_TEXTURE_HASH, 0);",
     "    if (t != NULL && !use_default)\n        return t;\n    if (!use_default)\n        return NULL;\n    t = GetTextureInfo(DEFAULT_TEXTURE_HASH, 0);"),
    ("gti_ignore_default", TPC, "    if (!use_default)\n        return NULL;\n",
     ""),
    ("gti_default_hash", TPC, "#define DEFAULT_TEXTURE_HASH    0x19006835u",
     "#define DEFAULT_TEXTURE_HASH    0x19006836u"),
    ("gti_no_break", TPC, "    texturepack_breaks++;\n", ""),
    ("gnti_no_subtract", TPC, "        n -= p->NumTextures;\n", ""),
    ("gnti_le", TPC,
     "        if (n < p->NumTextures)\n            return texturepack_get_nth_texture(p, n);",
     "        if (n <= p->NumTextures)\n            return texturepack_get_nth_texture(p, n);"),
    # TextureAnimPack.
    ("apack_no_step", TPC, "        e += anims[i].NumFrames;\n", ""),
    ("apack_link_head", TPC,
     "    link_tail(&TextureAnimPackList, &p->Node);",
     "    p->Node.next = TextureAnimPackList.next;\n    p->Node.prev = &TextureAnimPackList;\n    TextureAnimPackList.next->prev = &p->Node;\n    TextureAnimPackList.next = &p->Node;"),
    ("apack_swap_counts", TPC,
     "    p->NumTextureAnimEntries = num_entries;",
     "    p->NumTextureAnimEntries = num_anims;"),
    ("apack_dtor_no_unlink", TPC,
     "    list_unlink(&p->Node);\n    if (flags & 1)\n        bFree(p);\n}\n\nvoid textureanimpack_init",
     "    if (flags & 1)\n        bFree(p);\n}\n\nvoid textureanimpack_init"),
    ("init_valid_stays", TPC, "                valid = 0;\n", ""),
    ("init_no_frame_reset", TPC, "        a->CurrentFrame = 0;\n", ""),
    ("init_keep_on_miss", TPC,
     "                valid = 0;\n                e->pTextureInfo = NULL;\n                e->OriginalImageData = NULL;\n                e->OriginalPaletteData = NULL;",
     "                valid = 0;"),
    ("init_default", TPC,
     "            TextureInfo *t = GetTextureInfo(e->NameHash, 0);",
     "            TextureInfo *t = GetTextureInfo(e->NameHash, 1);"),
    ("init_pal_from_image", TPC,
     "                e->OriginalPaletteData = t->PaletteData;",
     "                e->OriginalPaletteData = t->ImageData;"),
    # UpdateTextureAnimations.
    ("upd_clock_swap", TPC, "            t = a->TimeBase == 1 ? real : world;",
     "            t = a->TimeBase == 1 ? world : real;"),
    ("upd_timebase_nonzero", TPC,
     "            t = a->TimeBase == 1 ? real : world;",
     "            t = a->TimeBase != 0 ? real : world;"),
    ("upd_no_tweak", TPC,
     "            fps = tweak != 0 ? tweak : a->FramesPerSecond;",
     "            fps = a->FramesPerSecond;"),
    ("upd_tweak_scale", TPC,
     "            fps = tweak != 0 ? tweak : a->FramesPerSecond;",
     "            fps = tweak != 0 ? tweak * a->FramesPerSecond : a->FramesPerSecond;"),
    ("upd_round", TPC, "frame = rem32(ee_trunc_w((float)fps * t), n);",
     "frame = rem32(ee_trunc_w((float)fps * t + 0.5f), n);"),
    ("upd_double", TPC, "frame = rem32(ee_trunc_w((float)fps * t), n);",
     "frame = rem32((int32_t)((double)fps * (double)t), n);"),
    ("upd_spf_exact", TPC, "#define SECONDS_PER_FRAME       0x1.111112p-6f",
     "#define SECONDS_PER_FRAME       (1.0f / 60.0f)"),
    ("upd_divide", TPC,
     "    float world = (float)WorldTimeFrames * SECONDS_PER_FRAME;",
     "    float world = (float)WorldTimeFrames / 60.0f;"),
    ("upd_always", TPC,
     "            if (frame == a->CurrentFrame)\n                continue;\n", ""),
    ("upd_no_store", TPC, "            a->CurrentFrame = frame;\n", ""),
    ("upd_backwards", TPC,
     "&a->TextureAnimTable[rem32(add32(k, frame), n)];",
     "&a->TextureAnimTable[rem32(add32(k, n - frame), n)];"),
    ("upd_no_palette", TPC,
     "                dst->PaletteData = src->OriginalPaletteData;\n", ""),
    ("upd_ignore_valid", TPC,
     "            if (!a->Valid)\n                continue;\n",
     "            if (!a->Valid && a->TextureAnimTable[0].pTextureInfo == NULL)\n                continue;\n"),
    ("upd_unsigned_rem", TPC, "frame = rem32(ee_trunc_w((float)fps * t), n);",
     "frame = (int32_t)((uint32_t)ee_trunc_w((float)fps * t) % (uint32_t)n);"),
    ("gta_last", TPC,
     "            if (p->TextureAnimTable[i].NameHash == hash)\n                return &p->TextureAnimTable[i];",
     "            if (p->TextureAnimTable[i].NameHash == hash\n                && i == p->NumTextureAnims - 1)\n                return &p->TextureAnimTable[i];"),
    ("gta_first_pack_only", TPC,
     "                return &p->TextureAnimTable[i];\n        }\n    }\n    return NULL;",
     "                return &p->TextureAnimTable[i];\n        }\n        break;\n    }\n    return NULL;"),
]

# Mutations that survive because they change nothing the image can tell.
EQUIVALENT = {
    # The hash of the name as given, not of the copy: the same string, for
    # no name the loader is given runs past the copy's 31 characters.
    "ctor_hash_of_given",
    # 1.0f / 60.0f is 0x3c888889, the image's constant, to the bit.
    "upd_spf_exact",
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    base = model(sc)
    caught, survived, missing, equivalent = 0, [], [], []
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
