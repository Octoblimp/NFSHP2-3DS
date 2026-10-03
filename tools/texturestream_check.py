#!/usr/bin/env python3
r"""Cross-check 3DS Files/source/texturestream.c, the streaming half of
retail's TexturePack, against the retail image itself, run in mipsemu.

The model is the image. LoadTextureTableFromFile (0x001ac608),
FindLoadedTextureData (0x001ac780), FindNotYetLoadedNeighbourTextureData
(0x001ac7d0), the list's order (0x001ac850, through bList::Sort),
AddLoadedTextureData (0x001ac880), RemoveLoadedTextureData (0x001aca30),
DeleteLoadedTextureData (0x001aca88), LoadTextureFromFile (0x001acaf8),
UnloadTextureFromFile (0x001acb68), LoadTexturesFromFile (0x001acc98),
UnloadTexturesFromFile (0x001acd90), ServiceLoadingTextures (0x001ace00),
ReadCallback (0x001acf28) and its bridge (0x001ad608),
UnloadAllTexturesFromFile (0x001acf98), GetLoadedSize (0x001ad008) and
~LoadedTextureData (0x001ad610) all run as shipped; so do what runs under
them: TexturePack's constructor and destructor, AttachTextureTable,
AssignTextureData, UnAssignTextureData, GetTexture, all of QueuedFile,
bList::Sort, bStrCpy, bStringHash, bSPrintf and bAddCodeineInventory. The
harness (tools/src/texturestream_test.c) runs the port -- texturestream.c
over texturepack.c, queuedfile.c and blist.c -- on the same script, and
the two transcripts are diffed.

Stubbed on both sides, each printing its arguments:

- bWare's file calls, over a fake file system: the disc's own files (FF)
  and packs built here (FS). bRead's bytes land at once; bReadAsync's
  callback is due a set number of bServiceFileSystem calls later (K).
- bMalloc and bFree: blocks from a fake heap, 128-aligned and filled with
  0xcd, labelled hN in order. A table's block is labelled by record, hN.i,
  on the image's 164-byte stride; the harness's records are the host's
  and it labels them the same.
- the slot pool, eWaitUntilRenderingDone, eFixUpTables, Joylog (whose
  GetData answers 0), and bMemCpy, natively.
- the callbacks: cb prints its parameter; cb2 prints, then loads the
  textures CH names with cb and 77, from inside ServiceLoadingTextures.

bFunkCallASync and bRemoveCodeineInventory are the debugger's channel and
are silent, as texturepack_check has them.

The packs are the disc's GLOBAL\HUDTEX.BIN, CARS\TEXTURES.BIN and
GLOBAL\DYNTEX.BIN, loaded and streamed as LoadGlobalChunks and CarLoader
have them, and packs built here: tables at the 128 KB edge and past it, a
file that stops before its blob, a table of a size no record divides,
names with no NUL, garbage in every field the table's copy keeps, and
placements laid out for the neighbour rule's 1 KB edges, merges of two,
contained ranges and the callback's empty range found as a neighbour.
After each op the transcript holds every pack, its ranges and loaded
textures, the queued reads and every back link.

    python tools/texturestream_check.py
    python tools/texturestream_check.py --mutate [--only a,b]
    python tools/texturestream_check.py --dump out/texturestream
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import physicscar_check as pcc
import retail_model
from mipsemu import M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)
BS = chr(92)

HARNESS = "tools/src/texturestream_test.c"
TS = "3DS Files/source/texturestream.c"
TP = "3DS Files/source/texturepack.c"
QF = "3DS Files/source/queuedfile.c"
SOURCES = [HARNESS, TS, TP, QF, "3DS Files/source/blist.c"]

HARNESS_TIMEOUT = 60

DATA = ROOT / "extracted-retail"

# ================================================================ the image

GP = 0x003358f0
TP_CTOR = 0x001ac0a8
TP_DTOR = 0x001ac178
LOAD_TABLE = 0x001ac608
FIND_LOADED = 0x001ac780
FIND_NEIGHBOUR = 0x001ac7d0
ADD_LTD = 0x001ac880
REMOVE_LTD = 0x001aca30
DELETE_LTD = 0x001aca88
LOAD_TEX = 0x001acaf8
UNLOAD_TEX = 0x001acb68
LOAD_TEXS = 0x001acc98
UNLOAD_TEXS = 0x001acd90
SERVICE_TEX = 0x001ace00
UNLOAD_ALL = 0x001acf98
LOADED_SIZE = 0x001ad008
TPCB = 0x001ad608

SERVICE_QF = 0x001ad850
INIT_QF = 0x001ada10
QF_SINIT = 0x001adc78

B_OPEN = 0x002544c0
B_CLOSE = 0x002544e8
B_SIZE_F = 0x00254550
B_SIZE_N = 0x00254568
B_SEEK = 0x00254830
B_READ_ASYNC = 0x002546e8
B_READ = 0x002547f0
B_SERVICE = 0x002539b8
JOY_GET = 0x00183358
JOY_ADD = 0x00183498
NEW_POOL = 0x00257c10
DEL_POOL = 0x00257c48
O_MALLOC = 0x00257c80
POOL_FREE = 0x00257ca0
B_MALLOC = 0x002577c0
B_FREE = 0x00257850
B_MEMCPY = 0x00250288
FIXUP = 0x00103e68
WAIT_RENDER = 0x00111dd8
FUNK = 0x0025d048
CODEINE_REMOVE = 0x0025d490

G_QPOOL = GP - 19120              # QueuedFileSlotPool
G_HANDLE = GP - 19116             # QueuedFile::CurrentHandle
G_READING = GP - 19112            # QueuedFileReadInProgress
G_QLIST = GP - 19104              # QueuedFileList
G_REPLAY = GP - 20668             # Joylog::ReplayingFlag
G_TPL = GP - 19144                # TexturePackList
G_DIRTY = 0x0032f788              # eDirtyTextures

SLOT_BASE = 0x01100000
SLOT_STRIDE = 128
NSLOT = 32
NAMEBUF = 0x01200200
HASHBUF = 0x01200400
CHBUF = 0x01200600
POOL_TOK = 0x01300000
FILE_TOK = 0x01300100
MAXFILES = 256
CB = 0x01320000
CB2 = 0x01320010
HEAP = 0x01400000
HEAP_END = HEAP + (12 << 20)
MAX_FS = 4000
LIMIT = 200000000

MAXPACK = 8
RECORD = 164
PACK_SIZE = 148
LTD_SIZE = 44

# TexturePack's fields.
P_NAME, P_FILE, P_HASH, P_INV, P_INFO, P_NUM = 8, 40, 104, 108, 112, 116
P_FREE, P_POS, P_LTD, P_CUR, P_NYL, P_POOL = 120, 124, 128, 136, 140, 144
# LoadedTextureData's.
L_LO, L_HI, L_N, L_POOL, L_BUF, L_DONE, L_BUSY, L_CB, L_PARAM = (
    8, 12, 16, 20, 24, 28, 32, 36, 40)
# TextureInfo's, as the disc has them.
T_PLACE = {"ip": 48, "pp": 52, "is": 56, "ps": 60}


# ================================================================ the files

HUD = "GLOBAL" + BS + "HUDTEX.BIN"
CARS = "CARS" + BS + "TEXTURES.BIN"
DYN = "GLOBAL" + BS + "DYNTEX.BIN"
DISC = {HUD: "GLOBAL/HUDTEX.BIN", CARS: "CARS/TEXTURES.BIN",
        DYN: "GLOBAL/DYNTEX.BIN"}


def FF(name):
    return "FF %s %s" % (name, DATA / DISC[name])


def FS(name, data):
    return "FS %s %s" % (name, data.hex())


def lcg_bytes(n, seed):
    out = bytearray(n)
    x = seed & M32
    for i in range(n):
        x = (x * 1103515245 + 12345) & M32
        out[i] = (x >> 16) & 0xff
    return bytes(out)


def rec(name, h, ip, isz, pp, psz, parent=0, wh=(64, 32), node=None,
        stk=0x5a5a0001, seed=1):
    """A disc record: garbage in every field but the ones named."""
    r = bytearray(lcg_bytes(RECORD, seed))
    nm = name.encode("latin-1")[:24]
    r[8:32] = nm + bytes(24 - len(nm))
    struct.pack_into("<IHH", r, 32, h, wh[0], wh[1])
    struct.pack_into("<iiiiI", r, 48, ip, pp, isz, psz, parent)
    if node is not None:
        struct.pack_into("<II", r, 0, node[0], node[1])
    struct.pack_into("<I", r, 156, stk)
    return bytes(r)


def chunk(cid, payload):
    return struct.pack("<II", cid, len(payload)) + payload


def pack_file(recs, data, hdr=84, extra=b"", blob=True):
    """A pack as the disc lays one out: the pack chunk, then its header,
    table and blob, the blob's payload padded so the data starts on 128."""
    head = chunk(0x33310001, lcg_bytes(hdr, 7))
    table = chunk(0x33310002, b"".join(recs) + extra)
    body = head + table
    if blob:
        at = 8 + len(body) + 8
        pad = ((at + 127) & ~127) - at
        body += chunk(0x33320002, bytes(pad) + data)
    return chunk(0xb3300000, body)


# Ranges laid out for the neighbour rule: r0 and r2 share an image, r2's
# palette is 912 bytes past r0's, r1's image and palette are too far apart
# to merge, r3's image runs on from r1's and names r1 its parent, r4 has a
# 24-character name and no image, r5 no palette, r6's hash is 0.
RANGE_RECS = [
    rec("R0", 0x10000001, 0, 1024, 1024, 64, seed=11),
    rec("R1", 0x10000002, 4096, 2048, 8192, 64, seed=12,
        node=(0x01010101, 0x02020202)),
    rec("R2", 0x10000003, 0, 1024, 2000, 64, seed=13),
    rec("R3", 0x10000004, 6144, 1000, 9000, 64, parent=0x10000002,
        seed=14),
    rec("ABCDEFGHIJKLMNOPQRSTUVWX", 0x10000005, 0, 0, 10240, 1024,
        seed=15),
    rec("R5", 0x10000006, 11264, 512, 0, 0, seed=16),
    rec("ZERO", 0, 12032, 128, 0, 0, seed=17),
]
RANGE_DATA = lcg_bytes(12288, 99)
RANGE = pack_file(RANGE_RECS, RANGE_DATA)

SMALL = pack_file(RANGE_RECS[:2], lcg_bytes(9000, 5), hdr=0)
# One texture, its palette twice its image's size and far from it.
R7 = pack_file([rec("R7", 0x10000007, 12160, 32, 0, 64, seed=18)],
               RANGE_DATA)
# A table no record divides, and a parent that is not in the pack.
ODD = pack_file([rec("O0", 0x20000001, 0, 256, 256, 64, parent=0x77777777,
                     seed=21)], lcg_bytes(512, 6), extra=b"\x01" * 100)


def short_file():
    """Stops before its blob: the table is not attached."""
    f = pack_file(RANGE_RECS, b"", blob=False)
    return f[:-1]


def edge_file():
    """Ends where its blob would start: the table is attached."""
    return pack_file(RANGE_RECS, b"", blob=False)


def big_file(nrec):
    """A table of nrec records: past 128 KB, the read stops short of it."""
    recs = [rec("B%d" % i, 0x30000000 + i, 64 * i, 64, 0, 0, seed=i)
            for i in range(nrec)]
    return pack_file(recs, lcg_bytes(64 * nrec, 8))


# The records whose ends lie at exactly 128 KB: a header of hdr, n records.
def edge_128k():
    # blob = 16 + hdr + 8 + 164 n; the read keeps 0x20000.
    n = (0x20000 - 16 - 8 - 84) // RECORD
    recs = [rec("E%d" % i, 0x40000000 + i, 64 * i, 64, 0, 0, seed=i)
            for i in range(n)]
    tail = 0x20000 - (16 + 84 + 8 + RECORD * n)
    return pack_file(recs, lcg_bytes(64 * n, 9), extra=bytes(tail)), n


# ============================================================ the scenarios

# HUDTEX.BIN.
VIPER_TACH = "08a0f7f2"
T911_MPH = "d62ce62a"
T911_TACH = "9bcd41e5"
CL55_TACH = "dc4b842c"
CORVETTE_TACH = "8e125aea"
OVERLAY_911 = "45eb3d27"
GAUGE_KMH = "3749f927"
GAUGE_MPH = "374a020c"
# TEXTURES.BIN: the 911's set, and two records that name a parent.
CAR911 = ["0f3f2be2", "57319c10", "52f0d73e", "56dcaa0f", "a54cf73d",
          "969e424b", "8c859ad6", "8c859b3b", "1568fc4b", "c28885ed",
          "9bcd65d9", "cc12bece"]
CAR911_HP = ["d27d77f1", "167e02e6"]
TAXI02_SHADOW = "b28e646c"
# DYNTEX.BIN.
LOADING = "ab0e817d"
JOY31, JOY32 = "795d2733", "795d2734"

R = ["%08x" % (0x10000001 + i) for i in range(6)]


def L(k, cb, param, hashes, n=None):
    return "L %d %d %d %d %s" % (k, cb, param,
                                 len(hashes) if n is None else n,
                                 " ".join(hashes))


def U(k, hashes, n=None):
    return "U %d %d %s" % (k, len(hashes) if n is None else n,
                           " ".join(hashes))


def s_tables():
    big = big_file(800)
    edge, n128 = edge_128k()
    return [
        FF(HUD), FF(CARS), FF(DYN),
        "P 0 HudTextures", "T 0 " + HUD,
        "P 1 CarTextures", "T 1 " + CARS,
        "P 2 DynTextures", "T 2 " + DYN,
        "GS 0", "GS 1",
        # A file that is not there: the name is kept, nothing else.
        "P 3 Missing", "T 3 GLOBAL" + BS + "NOPE.BIN",
        FS("SMALL.BIN", SMALL), "P 4 Small", "T 4 SMALL.BIN",
        FS("SHORT.BIN", short_file()), "P 5 Short", "T 5 SHORT.BIN",
        # A second table into the same pack.
        FS("EDGE.BIN", edge_file()), "T 5 EDGE.BIN",
        FS("ODD.BIN", ODD), "P 6 Odd", "T 6 ODD.BIN",
        # The 128 KB the read keeps: a table that ends on it, and one past.
        FS("E128.BIN", edge), "P 7 Edge", "T 7 E128.BIN",
        "D 7",
        FS("BIG.BIN", big), "P 7 Big", "T 7 BIG.BIN",
        "D 4", "D 3", "D 0", "D 6", "D 2", "D 1", "D 5", "D 7",
    ]


def s_hud():
    return [
        FF(HUD),
        "P 0 HudTextures", "T 0 " + HUD,
        # Two textures end to end: one range.
        L(0, 0, 0, [VIPER_TACH, T911_MPH]),
        "W 0",
        # A shared image, and a callback once both are in.
        L(0, 1, 5, [T911_TACH, CL55_TACH, CORVETTE_TACH]),
        "K 2", "S 1", "S 1", "S 1", "W 0", "S 1",
        "GS 0",
        "FL 0 51200 16384", "FL 0 51199 16384", "FN 0 0 10",
        U(0, [CL55_TACH]),
        U(0, [T911_TACH, VIPER_TACH, "00000000", "12345678"]),
        "R 0 0 100", "R 0 99999999 1",
        # Two that share an image, loaded with a callback, then all of it
        # unloaded.
        "K 1", L(0, 1, 6, [GAUGE_KMH, GAUGE_MPH, OVERLAY_911]),
        "UA 0", "W 0", "GS 0", "S 2",
        L(0, 1, 7, [GAUGE_KMH]), "W 0",
        "D 0",
    ]


def s_car():
    return [
        FF(CARS),
        "P 1 CarTextures", "T 1 " + CARS,
        "K 3", L(1, 1, 3, CAR911),
        "S 1", "S 1", "S 1",
        # The destructor waits the read out, and the rest with it.
        "D 1",
        "K 1", "P 1 CarTextures", "T 1 " + CARS,
        # Parents, a zero hash and a miss.
        L(1, 0, 0, CAR911_HP + ["00000000", TAXI02_SHADOW]),
        L(1, 0, 0, ["12345678"]),
        "W 1",
        L(1, 0, 0, CAR911[8:10]),
        "UA 1", "GS 1", "W 1", "GS 1",
        U(1, CAR911_HP + [TAXI02_SHADOW]),
        "GS 1",
        "D 1",
    ]


def s_global():
    # LoadGlobalChunks' three packs.
    return [
        FF(DYN), FF(HUD),
        "P 2 DynTextures", "T 2 " + DYN,
        L(2, 0, 0, [LOADING]),
        "S 1",
        "P 0 HudTextures", "T 0 " + HUD,
        "W 2",
        L(2, 1, 1, [JOY31, JOY32]),
        "W 2",
        U(2, [JOY32]), U(2, [JOY31]),
        "D 2", "D 0",
    ]


def s_ranges():
    return [
        FS("RANGE.BIN", RANGE),
        "P 0 Ranges", "T 0 RANGE.BIN",
        # A single range and the rule's edges round it.
        "A 0 10000 1000",
        "FN 0 8900 75", "FN 0 8900 76", "FN 0 9000 1000", "FN 0 9000 1001",
        "FN 0 11000 5", "FN 0 10999 5", "FN 0 12024 5", "FN 0 12025 5",
        "FN 0 -5000 15000",
        "FL 0 10000 1000", "FL 0 9999 2", "FL 0 10999 1", "FL 0 10999 2",
        "FL 0 10000 0", "FL 0 10500 -100", "FL 0 11000 0",
        # Neighbours either side, at the edge and one past it.
        "A 0 8876 100", "A 0 12024 10", "A 0 6851 1000", "A 0 13059 5",
        "A 0 500 10",
        "GS 0",
        # Contained, and on an edge.
        "A 0 9000 100", "A 0 12034 0", "A 0 8876 0",
        # Grown into a second: the two become one.
        "A 0 2000 1000", "A 0 4000 100", "A 0 3010 10",
        "GS 0",
        "SV 0", "FN 0 9000 10", "FL 0 9000 10",
        "W 0", "GS 0",
        # Past the loaded one: a new range, not grown into it.
        "A 0 13064 10", "FN 0 13064 10",
        "SV 0", "W 0",
        # Wrapped past the top.
        "A 0 2147483000 1000", "FL 0 2147483000 1000",
        "FN 0 2147483000 1",
        "R 0 2147483000 1000",
        "UA 0", "GS 0",
        "D 0",
    ]


def s_records():
    return [
        FS("RANGE.BIN", RANGE),
        "P 0 Ranges", "T 0 RANGE.BIN",
        # r0 and r2's image is one, and r2's palette r0's neighbour.
        "LT 0 0", "LT 0 2", "LT 0 1", "LT 0 3", "LT 0 4", "LT 0 5",
        "GS 0",
        "SV 0", "W 0",
        "UT 0 2", "UT 0 0", "UT 0 0",
        # No image, no palette, neither.
        "PR 0 1 is 0", "UT 0 1", "PR 0 1 ps 0", "LT 0 1",
        "PR 0 3 ps 0", "UT 0 3",
        "UA 0",
        "PR 0 1 is 2048", "PR 0 1 ps 64", "PR 0 1 ip 4000",
        "LT 0 1", "SV 0", "W 0",
        # A pool of its own, and the data elsewhere in the file: a range
        # keeps the pool it was made with.
        "A 0 7000 10", "PP 0 pool 16", "PP 0 pos 256", "LT 0 0", "SV 0",
        "W 0",
        U(0, R),
        # A zero hash is passed over, though a record has it.
        "LT 0 6", "SV 0", "W 0",
        L(0, 0, 0, ["00000000", R[5]]), U(0, ["00000000"]),
        "W 0", U(0, ["00000000", R[5]], n=1),
        "D 0",
        # A palette larger than its image, which lies alone: the image's
        # range is found by the image's own size.
        FS("R7.BIN", R7), "P 1 Seven", "T 1 R7.BIN",
        "LT 1 0", "SV 1", "W 1", "UT 1 0", "GS 1",
        "D 1",
    ]


def s_markers():
    return [
        FS("RANGE.BIN", RANGE),
        "P 0 Ranges", "T 0 RANGE.BIN",
        # Nothing to wait for: called at once.
        L(0, 1, 7, []),
        L(0, 1, 8, R[:2]),
        "W 0",
        L(0, 0, 0, []), L(0, 1, 9, [], n=-1), L(0, 0, 0, [R[3]], n=0),
        # From inside the service, a load of its own.
        "CH 0 %s %s" % (R[1], R[5]),
        L(0, 2, 5, [R[0]]),
        "W 0",
        L(0, 2, 6, [R[3]]), "W 0",
        # Held off by the count.
        "UA 0",
        L(0, 0, 0, [R[0]]), "A 0 6000 100", "PP 0 nyl 0", "W 0", "SV 0",
        "PP 0 nyl 3", "SV 0", "W 0",
        "UA 0",
        # The callback's range found as a neighbour: grown, and its
        # callback lost. A read in flight keeps the service off it.
        "A 0 20000 100", "SV 0",
        L(0, 1, 11, []),
        "A 0 1500 100", "A 0 900 100",
        "W 0",
        # The second neighbour the callback's: merged in, and lost.
        "UA 0",
        "A 0 30000 100", "SV 0",
        "A 0 1500 100", L(0, 1, 12, []), "A 0 900 100",
        "GS 0",
        "W 0",
        # Added after it: kept behind it, though it starts lower, and
        # called back before it is in.
        "A 0 40000 100", "SV 0", L(0, 1, 13, []), "A 0 2400 100",
        "GS 0",
        "W 0",
        # Below the callback's own start, which is 0: still behind it.
        "A 0 50000 100", "SV 0", L(0, 1, 14, []), "A 0 -1250 100",
        "GS 0",
        "W 0",
        # Two that start together keep the order they came in.
        "A 0 7000 100", "A 0 7000 200",
        "GS 0", "SV 0", "W 0",
        # Grown up to take a range: the grown range's start, not the new
        # one's, reaches the callback's range, which is merged in and lost.
        "UA 0",
        "A 0 60000 100", "SV 0", "A 0 500 100", L(0, 1, 15, []),
        "A 0 1500 100",
        "GS 0",
        "W 0",
        "UA 0",
        "D 0",
    ]


def s_remove():
    return [
        FS("RANGE.BIN", RANGE),
        "P 0 Ranges", "T 0 RANGE.BIN",
        "A 0 0 100", "A 0 0 50", "A 0 4096 100", "A 0 8000 10",
        "SV 0",
        # In flight: not deleted until it is in.
        "R 0 0 100", "R 0 0 100", "R 0 0 100",
        "W 0",
        "R 0 4096 100",
        "W 0", "R 0 8000 10",
        "A 0 0 100", "W 0", "R 0 0 100",
        # Deleted outright: loaded, waiting, and flagged either way.
        "A 0 0 100", "A 0 4096 100", "A 0 9000 10", "SV 0", "W 0",
        "DL 0 0", "DL 0 0",
        "A 0 2000 10", "PL 0 1 done 1", "DL 0 1",
        "A 0 5000 10", "PL 0 1 busy 1", "R 0 5000 10", "UA 0",
        "PL 0 0 busy 0", "PL 0 0 n 2", "R 0 5000 10", "R 0 5000 10",
        "A 0 5000 10", "PL 0 0 lo 4990", "PL 0 0 hi 5020", "FL 0 4995 5",
        "GS 0",
        # Emptied, with no callback: taken off as a callback's range is.
        "PL 0 0 hi 4990", "A 0 9000 10", "SV 0", "W 0",
        "D 0",
    ]


def s_failed():
    return [
        FS("F.BIN", RANGE),
        "P 0 Fails", "T 0 F.BIN",
        # The file gone before its read.
        L(0, 1, 1, [R[0]]),
        "FD F.BIN", "S 1", "S 1",
        # Past the end of the file.
        FS("F.BIN", RANGE),
        "PR 0 1 ip 999999", "LT 0 1", "SV 0", "W 0",
        # A pack whose file was never there.
        "P 1 Nowhere", "T 1 NOWHERE.BIN",
        "A 1 0 100", "SV 1", "K 4", "S 1", "S 1", "S 1", "S 1", "S 1",
        "A 1 100 100", "SV 1", "W 1",
        "UA 1", "UA 0",
        "D 1",
        # The destructor with a read in flight, and one waiting behind it.
        "K 2", "LT 0 0", "LT 0 1", "LT 0 3", "SV 0", "S 1",
        "D 0",
    ]


def script():
    head = ["C", "0", "I"]
    return [head + s for s in (
        s_tables(), s_hud(), s_car(), s_global(), s_ranges(), s_records(),
        s_markers(), s_remove(), s_failed())]


def encode(scenarios):
    lines = []
    for i, s in enumerate(scenarios):
        lines.append("B %d" % i)
        lines += s
    return NL.join(lines) + NL


def esc(raw):
    out = []
    for c in raw:
        out.append(chr(c) if 33 <= c <= 126 else "%%%02x" % c)
    return "".join(out)


# ================================================================ the model


def I(x):
    """An int argument as the EE holds one: 32 bits, sign-extended."""
    return s32(int(x) & M32)


class BigEmu(retail_model.RetailEmu):
    RAM = 64 << 20


class Model(object):
    def __init__(self):
        self.out = []
        self.disc = {}
        self.e = BigEmu(ieee=True, eediv=True)
        e = self.e
        self.reset()
        for a, fn in ((B_OPEN, self.s_open), (B_CLOSE, self.s_close),
                      (B_SIZE_F, self.s_size_f), (B_SIZE_N, self.s_size_n),
                      (B_SEEK, self.s_seek),
                      (B_READ_ASYNC, self.s_read_async),
                      (B_READ, self.s_read),
                      (B_SERVICE, self.s_service_fs),
                      (JOY_GET, self.s_joy_get), (JOY_ADD, self.s_joy_add),
                      (NEW_POOL, self.s_new_pool),
                      (DEL_POOL, self.s_del_pool),
                      (O_MALLOC, self.s_omalloc), (POOL_FREE, self.s_pfree),
                      (B_MALLOC, self.s_malloc), (B_FREE, self.s_free),
                      (B_MEMCPY, self.s_memcpy),
                      (FIXUP, self.s_fixup), (WAIT_RENDER, self.s_wait),
                      (FUNK, self.s_silent),
                      (CODEINE_REMOVE, self.s_silent),
                      (CB, self.s_cb), (CB2, self.s_cb2)):
            e.stub(a, fn)

    def reset(self):
        self.fs = {}
        self.files = []
        self.reads = []
        self.latency = 1
        self.used = [False] * NSLOT
        self.heap = []
        self.top = HEAP
        self.fs_calls = 0
        self.packs = [None] * MAXPACK
        self.ch = (0, 0)

    def emit(self, s):
        self.out.append(s)

    def cstr(self, a, cap=4096):
        e = self.e
        s = bytearray()
        while len(s) < cap:
            b = e.u8(a + len(s))
            if b == 0:
                break
            s.append(b)
        return bytes(s)

    def arg(self, i):
        return self.e.reg[4 + i] & M32

    def u16(self, a):
        return struct.unpack_from("<H", self.e.mem, a)[0]

    # ---- the labels ------------------------------------------------------

    def nm(self, a):
        a &= M32
        if a == 0:
            return "NULL"
        named = {POOL_TOK: "pool", G_QLIST: "QL", G_TPL: "TPL"}
        if a in named:
            return named[a]
        for k, p in enumerate(self.packs):
            if p is not None and a == p + P_LTD:
                return "pk%d.ltd" % k
        if (SLOT_BASE <= a < SLOT_BASE + SLOT_STRIDE * NSLOT
                and (a - SLOT_BASE) % SLOT_STRIDE == 0):
            return "#%d" % ((a - SLOT_BASE) // SLOT_STRIDE)
        if FILE_TOK <= a < FILE_TOK + MAXFILES:
            return "f%d" % (a - FILE_TOK)
        for i, (base, size, _live, table) in enumerate(self.heap):
            if base <= a < base + max(size, 1):
                off = a - base
                if table:
                    r, off = divmod(off, RECORD)
                    return "h%d.%d" % (i, r) + ("+?" if off else "")
                return "h%d" % i if off == 0 else "h%d+%d" % (i, off)
        return "?"

    def pm(self, a):
        """A parameter: a label when it is one, else the number."""
        n = self.nm(a)
        return "%d" % s32(a) if n == "?" else n

    def cbnm(self, a):
        return {0: "NULL", CB: "cb", CB2: "cb2"}.get(a & M32, "?")

    # ---- nested calls ----------------------------------------------------

    def nested(self, fn, *args):
        e = self.e
        kept = (list(e.reg), list(e.fpr), e.hi, e.lo, e.hi1, e.lo1, e.sa,
                e.fcc, e.limit, e.icount)
        try:
            r = e.call(fn, *args, limit=LIMIT)
        finally:
            e.reg[:] = kept[0]
            e.fpr[:] = kept[1]
            (e.hi, e.lo, e.hi1, e.lo1, e.sa, e.fcc, e.limit,
             e.icount) = kept[2:]
        return r

    # ---- the heap --------------------------------------------------------

    def alloc(self, size, table=False):
        base = (self.top + 127) & ~127
        span = size if size > 0 else 1
        if base + span > HEAP_END:
            raise SystemExit("heap full")
        self.top = base + span
        self.heap.append([base, size, True, table])
        if size > 0:
            self.e.write(base, b"\xcd" * size)
        return base

    def s_malloc(self, em):
        size = s32(self.arg(0))
        name = self.cstr(self.arg(1), 160)
        table = name not in (b"TextureTable", b"LoadedTextureData")
        a = self.alloc(size, table)
        self.emit("  malloc %d %s %d %d -> %s" % (
            size, esc(name), s32(self.arg(2)), s32(self.arg(3)),
            self.nm(a)))
        return a

    def s_free(self, em):
        a = self.arg(0)
        for blk in self.heap:
            if blk[0] == a:
                self.emit("  free %s%s" % (self.nm(a),
                                           "" if blk[2] else " again"))
                blk[2] = False
                return
        self.emit("  free %s" % self.nm(a))

    # ---- the file system -------------------------------------------------

    def s_open(self, em):
        name = self.cstr(self.arg(0)).decode("latin-1")
        if name not in self.fs or len(self.files) >= MAXFILES:
            self.emit("  open %s -> NULL" % esc(name.encode("latin-1")))
            return 0
        self.files.append([name, self.fs[name], 0])
        a = FILE_TOK + len(self.files) - 1
        self.emit("  open %s -> %s" % (esc(name.encode("latin-1")),
                                       self.nm(a)))
        return a

    def file(self, a):
        return self.files[(a & M32) - FILE_TOK]

    def s_close(self, em):
        self.emit("  close %s" % self.nm(self.arg(0)))

    def s_size_f(self, em):
        n = len(self.file(self.arg(0))[1])
        self.emit("  size %s -> %d" % (self.nm(self.arg(0)), n))
        return n

    def s_size_n(self, em):
        name = self.cstr(self.arg(0)).decode("latin-1")
        n = len(self.fs[name]) if name in self.fs else -1
        self.emit("  sizename %s -> %d" % (esc(name.encode("latin-1")), n))
        return n & M32

    def s_seek(self, em):
        f = self.file(self.arg(0))
        f[2] = s32(self.arg(1))
        self.emit("  seek %s %d %d" % (self.nm(self.arg(0)), f[2],
                                       s32(self.arg(2))))

    def read_bytes(self, f, buf, n):
        if n > 0:
            if f[2] >= 0:
                self.e.write(buf, f[1][f[2]:f[2] + n])
            f[2] += n

    def s_read(self, em):
        fa, buf, n = self.arg(0), self.arg(1), s32(self.arg(2))
        f = self.file(fa)
        got = f[1][f[2]:f[2] + n] if n > 0 and f[2] >= 0 else b""
        self.emit("  readsync %s %s %d %s" % (
            self.nm(fa), self.nm(buf), n,
            "%08x" % (zlib.crc32(got) & M32) if got else "-"))
        self.read_bytes(f, buf, n)

    def s_read_async(self, em):
        fa, buf, n = self.arg(0), self.arg(1), s32(self.arg(2))
        cb, param = self.arg(3), self.arg(4)
        f = self.file(fa)
        self.emit("  read %s %s %d %s %s" % (self.nm(fa), self.nm(buf), n,
                                             "rdone" if cb else "NULL",
                                             self.pm(param)))
        self.read_bytes(f, buf, n)
        self.reads.append([self.latency, fa, cb, param])

    def s_service_fs(self, em):
        self.emit("  servicefs")
        self.fs_calls += 1
        if self.fs_calls > MAX_FS:
            self.emit("fs spin")
            raise SystemExit("bServiceFileSystem spins")
        for r in self.reads:
            r[0] -= 1
        due = [r for r in self.reads if r[0] <= 0]
        self.reads = [r for r in self.reads if r[0] > 0]
        for _, fa, cb, param in due:
            self.emit("  readdone %s" % self.nm(fa))
            self.nested(cb, fa, param)

    # ---- the rest of the stubs -------------------------------------------

    def s_joy_get(self, em):
        self.emit("  joyget %d %d -> 0" % (s32(self.arg(0)),
                                          s32(self.arg(1))))
        return 0

    def s_joy_add(self, em):
        self.emit("  joyadd %d %d %d" % (s32(self.arg(0)), s32(self.arg(1)),
                                         s32(self.arg(2))))

    def s_new_pool(self, em):
        self.emit("  newpool %d %d %s %d" % (
            s32(self.arg(0)), s32(self.arg(1)),
            self.cstr(self.arg(2)).decode("latin-1"), s32(self.arg(3))))
        return POOL_TOK

    def s_del_pool(self, em):
        self.emit("  delpool %s" % self.nm(self.arg(0)))

    def s_omalloc(self, em):
        for i in range(NSLOT):
            if not self.used[i]:
                self.used[i] = True
                a = SLOT_BASE + SLOT_STRIDE * i
                self.e.write(a, b"\xcd" * SLOT_STRIDE)
                self.emit("  omalloc %s -> #%d" % (self.nm(self.arg(0)), i))
                return a
        raise SystemExit("slots full")

    def s_pfree(self, em):
        a = self.arg(1)
        self.emit("  pfree %s %s" % (self.nm(self.arg(0)), self.nm(a)))
        if SLOT_BASE <= a < SLOT_BASE + SLOT_STRIDE * NSLOT:
            self.used[(a - SLOT_BASE) // SLOT_STRIDE] = False

    def crc(self, a, n):
        if a == 0 or n <= 0:
            return "-"
        return "%08x" % (zlib.crc32(bytes(self.e.mem[a:a + n])) & M32)

    def s_memcpy(self, em):
        d, s, n = self.arg(0), self.arg(1), s32(self.arg(2))
        e = self.e
        if n > 0:
            e.mem[d:d + n] = e.mem[s:s + n]
        return d

    def s_fixup(self, em):
        self.emit("  fixup")

    def s_wait(self, em):
        self.emit("  waitrender")

    def s_silent(self, em):
        return 0

    def s_cb(self, em):
        self.emit("  callback %s" % self.pm(self.arg(0)))

    def s_cb2(self, em):
        self.emit("  callback2 %s" % self.pm(self.arg(0)))
        k, n = self.ch
        self.nested(LOAD_TEXS, self.packs[k], CHBUF, n, CB, 77)
        self.emit("  chained")

    # ---- the print -------------------------------------------------------

    def print_records(self, p):
        e = self.e
        info, num = e.u32(p + P_INFO), s32(e.u32(p + P_NUM))
        for i in range(num):
            t = info + RECORD * i
            self.emit(
                "  rec %d %s name=%s hash=%08x wh=%d,%d img=%d+%d pal=%d+%d "
                "parent=%s pack=%s node=%08x,%08x stk=%08x vram=%d,%d "
                "crc=%s" % (
                    i, self.nm(t), esc(self.cstr(t + 8, 24)), e.u32(t + 32),
                    self.u16(t + 36), self.u16(t + 38), s32(e.u32(t + 48)),
                    s32(e.u32(t + 56)), s32(e.u32(t + 52)),
                    s32(e.u32(t + 60)), self.nm(e.u32(t + 140)),
                    self.nm(e.u32(t + 136)), e.u32(t), e.u32(t + 4),
                    e.u32(t + 156), self.u16(t + 160), self.u16(t + 162),
                    self.crc(t + 8, 128)))

    def print_pack(self, k):
        e = self.e
        p = self.packs[k]
        head = p + P_LTD
        self.emit(
            "pk%d %s name=%s file=%s hash=%08x inv=%08x info=%s num=%d "
            "free=%d pos=%d cur=%s nyl=%d pool=%d prev=%s lprev=%s" % (
                k, self.nm(p), esc(self.cstr(p + P_NAME, 32)),
                esc(self.cstr(p + P_FILE, 64)), e.u32(p + P_HASH),
                e.u32(p + P_INV), self.nm(e.u32(p + P_INFO)),
                s32(e.u32(p + P_NUM)), s32(e.u32(p + P_FREE)),
                s32(e.u32(p + P_POS)), self.nm(e.u32(p + P_CUR)),
                s32(e.u32(p + P_NYL)), s32(e.u32(p + P_POOL)),
                self.nm(e.u32(p + 4)), self.nm(e.u32(head + 4))))
        n, c = e.u32(head), 0
        while n != head and n != 0 and c < 256:
            lo, hi = s32(e.u32(n + L_LO)), s32(e.u32(n + L_HI))
            ln = s32(hi - lo)
            done = s32(e.u32(n + L_DONE))
            buf = e.u32(n + L_BUF)
            self.emit(
                "  ltd %s lo=%d hi=%d n=%d pool=%d buf=%s done=%d busy=%d "
                "cb=%s param=%s prev=%s data=%s" % (
                    self.nm(n), lo, hi, s32(e.u32(n + L_N)),
                    s32(e.u32(n + L_POOL)), self.nm(buf), done,
                    s32(e.u32(n + L_BUSY)), self.cbnm(e.u32(n + L_CB)),
                    self.pm(e.u32(n + L_PARAM)), self.nm(e.u32(n + 4)),
                    self.crc(buf, ln) if done and 0 < ln < (1 << 22)
                    else "-"))
            n, c = e.u32(n), c + 1
        if n == 0:
            self.emit("  ltds null")
        elif c == 256:
            self.emit("  ltds loop")
        info, num = e.u32(p + P_INFO), s32(e.u32(p + P_NUM))
        for i in range(num):
            t = info + RECORD * i
            img, pal = e.u32(t + 144), e.u32(t + 148)
            if img or pal:
                self.emit("  tex %d img=%s pal=%s" % (i, self.nm(img),
                                                     self.nm(pal)))

    def print_state(self):
        e = self.e
        for k in range(MAXPACK):
            if self.packs[k] is not None:
                self.print_pack(k)
        self.emit("st dirty=%d handle=%d reading=%d pool=%s tpl=%s,%s" % (
            s32(e.u32(G_DIRTY)), s32(e.u32(G_HANDLE)),
            s32(e.u32(G_READING)), self.nm(e.u32(G_QPOOL)),
            self.nm(e.u32(G_TPL)), self.nm(e.u32(G_TPL + 4))))
        e.put32(G_DIRTY, 0)
        n, k = e.u32(G_QLIST), 0
        while n != G_QLIST and n != 0 and k < 64:
            self.emit(
                "qf %s buf=%s name=%s pos=%d n=%d read=%d block=%d prio=%d "
                "cb=%s param=%s handle=%d status=%d abort=%d prev=%s" % (
                    self.nm(n), self.nm(e.u32(n + 8)),
                    esc(self.cstr(n + 12, 48)), s32(e.u32(n + 60)),
                    s32(e.u32(n + 64)), s32(e.u32(n + 68)),
                    s32(e.u32(n + 72)), s32(e.u32(n + 76)),
                    "tpcb" if e.u32(n + 80) else "NULL",
                    self.pm(e.u32(n + 84)),
                    s32(e.u32(n + 88)), s32(e.u32(n + 92)),
                    s32(e.u32(n + 96)), self.nm(e.u32(n + 4))))
            n, k = e.u32(n), k + 1
        if n == 0:
            self.emit("qfs null")
        elif k == 64:
            self.emit("qfs loop")
        self.emit("qfs end prev=%s" % self.nm(e.u32(G_QLIST + 4)))

    # ---- the ops ---------------------------------------------------------

    def put_name(self, s):
        self.e.write(NAMEBUF, s.encode("latin-1") + b"\0")

    def put_hashes(self, at, hs):
        for i, h in enumerate(hs):
            self.e.put32(at + 4 * i, int(h, 16))
        return len(hs)

    def pk(self, k):
        p = self.packs[int(k)]
        if p is None:
            raise SystemExit("no pack %s" % k)
        return p

    def range_at(self, p, j):
        e = self.e
        head = p + P_LTD
        n = e.u32(head)
        while j > 0 and n != head:
            n, j = e.u32(n), j - 1
        if n == head:
            raise SystemExit("no range")
        return n

    def call(self, fn, *args):
        return self.e.call(fn, *args, limit=LIMIT)

    def run(self, scenarios):
        e = self.e
        for n, sc in enumerate(scenarios):
            self.emit("B %d" % n)
            self.reset()
            for ln in sc:
                self.emit("> " + ln[:48])
                t = ln.split()
                op = t[0]
                self.fs_calls = 0
                show = True
                if op == "C":
                    self.call(QF_SINIT)
                    e.put32(G_TPL, G_TPL)
                    e.put32(G_TPL + 4, G_TPL)
                elif op == "0":
                    for g, v in ((G_HANDLE, 1), (G_READING, 0),
                                 (G_REPLAY, 0), (G_DIRTY, 0)):
                        e.put32(g, v)
                elif op == "I":
                    self.call(INIT_QF)
                elif op == "FS":
                    self.fs[t[1]] = bytes.fromhex(t[2]) if len(t) > 2 else b""
                    show = False
                elif op == "FF":
                    name, path = ln.split(None, 2)[1:]
                    if path not in self.disc:
                        self.disc[path] = Path(path).read_bytes()
                    self.fs[name] = self.disc[path]
                    show = False
                elif op == "FD":
                    del self.fs[t[1]]
                    show = False
                elif op == "K":
                    self.latency = int(t[1])
                    show = False
                elif op == "CH":
                    self.ch = (int(t[1]), self.put_hashes(CHBUF, t[2:]))
                    show = False
                elif op == "P":
                    k = int(t[1])
                    p = self.alloc(PACK_SIZE)
                    self.emit("  pack %d -> %s" % (k, self.nm(p)))
                    self.put_name(t[2])
                    self.call(TP_CTOR, p, NAMEBUF, 0)
                    self.packs[k] = p
                elif op == "T":
                    p = self.pk(t[1])
                    self.put_name(t[2])
                    self.call(LOAD_TABLE, p, NAMEBUF)
                    self.print_records(p)
                elif op == "L":
                    p = self.pk(t[1])
                    self.put_hashes(HASHBUF, t[5:])
                    self.call(LOAD_TEXS, p, HASHBUF, I(t[4]),
                              (0, CB, CB2)[int(t[2])], I(t[3]))
                elif op == "U":
                    p = self.pk(t[1])
                    self.put_hashes(HASHBUF, t[3:])
                    self.call(UNLOAD_TEXS, p, HASHBUF, I(t[2]))
                elif op == "A":
                    self.call(ADD_LTD, self.pk(t[1]), I(t[2]), I(t[3]))
                elif op == "R":
                    self.emit("R -> %d" % self.call(
                        REMOVE_LTD, self.pk(t[1]), I(t[2]), I(t[3])))
                elif op in ("FL", "FN"):
                    fn = FIND_LOADED if op == "FL" else FIND_NEIGHBOUR
                    self.emit("%s -> %s" % (op, self.nm(self.call(
                        fn, self.pk(t[1]), I(t[2]), I(t[3])))))
                    show = False
                elif op in ("LT", "UT"):
                    p = self.pk(t[1])
                    rec_at = e.u32(p + P_INFO) + RECORD * int(t[2])
                    self.call(LOAD_TEX if op == "LT" else UNLOAD_TEX, p,
                              rec_at)
                elif op == "DL":
                    p = self.pk(t[1])
                    self.call(DELETE_LTD, p, self.range_at(p, int(t[2])))
                elif op == "SV":
                    self.call(SERVICE_TEX, self.pk(t[1]))
                elif op == "S":
                    for _ in range(int(t[1])):
                        self.call(SERVICE_QF)
                elif op == "W":
                    p, m = self.pk(t[1]), 0
                    while e.u32(p + P_CUR) != 0 and m < 2000:
                        self.call(SERVICE_QF)
                        m += 1
                    self.emit("W -> %d" % m)
                elif op == "UA":
                    self.call(UNLOAD_ALL, self.pk(t[1]))
                elif op == "GS":
                    self.emit("GS -> %d" % self.call(LOADED_SIZE,
                                                     self.pk(t[1])))
                    show = False
                elif op == "D":
                    self.call(TP_DTOR, self.pk(t[1]), 3)
                    self.packs[int(t[1])] = None
                elif op == "PR":
                    p = self.pk(t[1])
                    at = e.u32(p + P_INFO) + RECORD * int(t[2])
                    e.put32(at + T_PLACE[t[3]], I(t[4]) & M32)
                elif op == "PP":
                    p = self.pk(t[1])
                    off = {"pos": P_POS, "pool": P_POOL, "nyl": P_NYL}[t[2]]
                    e.put32(p + off, I(t[3]) & M32)
                elif op == "PL":
                    d = self.range_at(self.pk(t[1]), int(t[2]))
                    off = {"lo": L_LO, "hi": L_HI, "n": L_N, "busy": L_BUSY,
                           "done": L_DONE}[t[3]]
                    e.put32(d + off, I(t[4]) & M32)
                else:
                    raise SystemExit("bad op %r" % (t,))
                if show:
                    self.print_state()
        return self.out


# ================================================================ the build


def build_harness(tmp, name="texturestream_test"):
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


# ============================================================ the mutations


def M(name, before, after, rel=TS):
    return (name, rel, before, after)


MUTATIONS = [
    # The list helpers.
    M("tail_prev", "    n->prev = last;\n    n->next = list;",
      "    n->prev = list;\n    n->next = list;"),
    M("tail_last", "    last->next = n;\n    list->prev = n;", "    list->prev = n;"),
    M("unlink_back", "    n->next->prev = n->prev;\n}", "}"),
    M("add32", "return (int32_t)((uint32_t)a + (uint32_t)b);",
      "return (int32_t)((uint32_t)a | (uint32_t)b);"),
    M("sub32", "return (int32_t)((uint32_t)a - (uint32_t)b);",
      "return (int32_t)((uint32_t)a - (uint32_t)b - 1);"),
    # LoadTextureTableFromFile.
    M("tt_name_cap", "i < (int32_t)sizeof p->Filename - 1; i++)",
      "i < 8; i++)"),
    M("tt_name_term", "    p->Filename[i] = 0;\n    f = bOpen", "    f = bOpen"),
    M("tt_null", "    if (f == NULL)\n        return;\n    n = bFileSize(f);",
      "    n = bFileSize(f);"),
    M("tt_max_lo", "#define TABLE_READ_MAX  0x20000", "#define TABLE_READ_MAX  0x1ff80"),
    M("tt_max_hi", "#define TABLE_READ_MAX  0x20000", "#define TABLE_READ_MAX  0x20080"),
    M("tt_pool", "\"TextureTable\", 0, 72);", "\"TextureTable\", 0, 64);"),
    M("tt_close", "    bClose(f);\n    // The pack chunk", "    // The pack chunk"),
    M("tt_tab", "tab = 16 + bchunk_u32(buf + 12);", "tab = 8 + bchunk_u32(buf + 12);"),
    M("tt_blob", "blob = tab + 8 + bchunk_u32(buf + tab + 4);",
      "blob = tab + bchunk_u32(buf + tab + 4);"),
    M("tt_cmp", "    if ((uint32_t)n >= blob) {", "    if ((uint32_t)n > blob) {"),
    M("tt_payload", "uintptr_t data = (uintptr_t)buf + blob + 8;",
      "uintptr_t data = (uintptr_t)buf + blob;"),
    M("tt_round", "((data + 127) & ~(uintptr_t)127)", "((data + 63) & ~(uintptr_t)63)"),
    M("tt_num", "bchunk_u32(buf + tab + 4) / DISC_RECORD);",
      "bchunk_u32(buf + tab + 4) / DISC_RECORD + 1);"),
    M("tt_table_name", "                                       p->Name, 0, 16);",
      "                                       \"TextureTable\", 0, 16);"),
    M("tt_table_pool", "                                       p->Name, 0, 16);",
      "                                       p->Name, 0, 0);"),
    M("tt_stride", "buf + tab + 8 + DISC_RECORD * i);", "buf + tab + 8 + 160 * i);"),
    M("tt_first", "buf + tab + 8 + DISC_RECORD * i);", "buf + tab + DISC_RECORD * i);"),
    M("tt_attach_num", "texturepack_attach_texture_table(p, table, num);",
      "texturepack_attach_texture_table(p, table, num - 1);"),
    M("tt_free_flag", "    p->pTextureInfoNeedsToBeFreed = 1;",
      "    p->pTextureInfoNeedsToBeFreed = 0;"),
    M("tt_free_buf", "    }\n    bFree(buf);\n}", "    }\n}"),
    M("rec_next", "t->Node.next = (bNode *)(uintptr_t)bchunk_u32(d);",
      "t->Node.next = (bNode *)(uintptr_t)bchunk_u32(d + 4);"),
    M("rec_prev", "t->Node.prev = (bNode *)(uintptr_t)bchunk_u32(d + 4);",
      "t->Node.prev = (bNode *)(uintptr_t)bchunk_u32(d);"),
    M("rec_body", "d + 8, 128);", "d + 8, 124);"),
    M("rec_stacked", "(void *)(uintptr_t)bchunk_u32(d + 156);",
      "(void *)(uintptr_t)bchunk_u32(d + 152);"),
    # FindLoadedTextureData.
    M("fl_lo", "        if (d->LowPos <= pos && end <= d->HighPos)",
      "        if (d->LowPos < pos && end <= d->HighPos)"),
    M("fl_hi", "        if (d->LowPos <= pos && end <= d->HighPos)",
      "        if (d->LowPos <= pos && end < d->HighPos)"),
    M("fl_end", "        if (d->LowPos <= pos && end <= d->HighPos)",
      "        if (d->LowPos <= pos && pos <= d->HighPos)"),
    # FindNotYetLoadedNeighbourTextureData.
    M("fn_buf", "        if (d->Buf != NULL)\n            continue;\n        // Ends",
      "        // Ends"),
    M("fn_gap_lo", "#define NEIGHBOUR_GAP   1024", "#define NEIGHBOUR_GAP   1023"),
    M("fn_gap_hi", "#define NEIGHBOUR_GAP   1024", "#define NEIGHBOUR_GAP   1025"),
    M("fn_before_ge", "if (end >= add32(d->LowPos, -NEIGHBOUR_GAP) && end <= d->LowPos)",
      "if (end > add32(d->LowPos, -NEIGHBOUR_GAP) && end <= d->LowPos)"),
    M("fn_before_le", "if (end >= add32(d->LowPos, -NEIGHBOUR_GAP) && end <= d->LowPos)",
      "if (end >= add32(d->LowPos, -NEIGHBOUR_GAP) && end < d->LowPos)"),
    M("fn_after_le", "if (pos <= add32(d->HighPos, NEIGHBOUR_GAP) && pos >= d->HighPos)",
      "if (pos < add32(d->HighPos, NEIGHBOUR_GAP) && pos >= d->HighPos)"),
    M("fn_after_ge", "if (pos <= add32(d->HighPos, NEIGHBOUR_GAP) && pos >= d->HighPos)",
      "if (pos <= add32(d->HighPos, NEIGHBOUR_GAP) && pos > d->HighPos)"),
    M("fn_after_off",
      "        if (pos <= add32(d->HighPos, NEIGHBOUR_GAP) && pos >= d->HighPos)\n"
      "            return d;\n", ""),
    M("fn_before_off",
      "        if (end >= add32(d->LowPos, -NEIGHBOUR_GAP) && end <= d->LowPos)\n"
      "            return d;\n", ""),
    # The list's order.
    M("io_cb_a", "    if (ltd(a)->Callback != NULL || ltd(b)->Callback != NULL)",
      "    if (ltd(b)->Callback != NULL)"),
    M("io_cb_b", "    if (ltd(a)->Callback != NULL || ltd(b)->Callback != NULL)",
      "    if (ltd(a)->Callback != NULL)"),
    M("io_strict", "    return ltd(a)->LowPos <= ltd(b)->LowPos;",
      "    return ltd(a)->LowPos < ltd(b)->LowPos;"),
    M("io_dir", "    return ltd(a)->LowPos <= ltd(b)->LowPos;",
      "    return ltd(a)->LowPos >= ltd(b)->LowPos;"),
    # AddLoadedTextureData.
    M("add_found_n", "        d->NumAssignments++;\n        return;\n    }", "        return;\n    }"),
    M("add_grow_lo", "        if (pos < d->LowPos)\n            d->LowPos = pos;",
      "        if (pos > d->LowPos)\n            d->LowPos = pos;"),
    M("add_grow_hi", "        if (d->HighPos < end)\n            d->HighPos = end;",
      "        if (d->HighPos > end)\n            d->HighPos = end;"),
    M("add_grow_n", "        d->NumAssignments++;\n        // Grown", "        // Grown"),
    M("add_m_args", "            p, d->LowPos, sub32(d->HighPos, d->LowPos));",
      "            p, pos, size);"),
    M("add_m_none", "        if (m == NULL)\n            return;", "        if (m != NULL)\n            return;"),
    M("add_m_lo", "        if (m->LowPos < d->LowPos)", "        if (m->LowPos > d->LowPos)"),
    M("add_m_hi", "        if (d->HighPos < m->HighPos)", "        if (d->HighPos > m->HighPos)"),
    M("add_m_n", "        d->NumAssignments += m->NumAssignments;",
      "        d->NumAssignments++;"),
    M("add_m_unlink", "        list_unlink(&m->Node);\n        loadedtexturedata_destruct(m, 3);",
      "        loadedtexturedata_destruct(m, 3);"),
    M("add_m_free", "        loadedtexturedata_destruct(m, 3);\n        p->Num",
      "        p->Num"),
    M("add_m_nyl", "        p->NumNotYetLoadedTextureDatas--;\n        return;\n    }\n    // A new",
      "        return;\n    }\n    // A new"),
    M("add_new_pool", "\"LoadedTextureData\", 0,\n                                     16);",
      "\"LoadedTextureData\", 0,\n                                     0);"),
    M("add_new_hi", "    d->HighPos = end;\n    d->MemoryPool", "    d->HighPos = pos;\n    d->MemoryPool"),
    M("add_new_mempool", "    d->MemoryPool = p->MemoryPool;\n    d->NumAssignments = 1;",
      "    d->MemoryPool = 64;\n    d->NumAssignments = 1;"),
    M("add_new_n", "    d->NumAssignments = 1;", "    d->NumAssignments = 2;"),
    M("add_new_lo", "    d->LowPos = pos;\n    d->LoadingCompleted", "    d->LowPos = end;\n    d->LoadingCompleted"),
    M("add_new_done", "    d->LoadingCompleted = 0;\n    d->LoadingInProgress = 0;\n    link_tail",
      "    d->LoadingInProgress = 0;\n    link_tail"),
    M("add_new_busy", "    d->LoadingCompleted = 0;\n    d->LoadingInProgress = 0;\n    link_tail",
      "    d->LoadingCompleted = 0;\n    link_tail"),
    M("add_new_nyl", "    p->NumNotYetLoadedTextureDatas++;\n    d->Buf = NULL;",
      "    d->Buf = NULL;"),
    M("add_new_buf", "    d->Buf = NULL;\n    d->Callback = NULL;\n    blist_sort",
      "    d->Callback = NULL;\n    blist_sort"),
    M("add_new_cb", "    d->Callback = NULL;\n    blist_sort", "    blist_sort"),
    M("add_sort", "    blist_sort(&p->LoadedTextureDataList, in_order);\n", ""),
    # RemoveLoadedTextureData.
    M("rm_none", "    if (d == NULL)\n        return 0;", "    if (d == NULL)\n        return 1;"),
    M("rm_found", "        texturepack_delete_loaded_texture_data(p, d);\n    return 1;",
      "        texturepack_delete_loaded_texture_data(p, d);\n    return 0;"),
    M("rm_dec", "    if (--d->NumAssignments == 0 && !d->LoadingInProgress)",
      "    if (d->NumAssignments - 1 == 0 && !d->LoadingInProgress)"),
    M("rm_busy", "    if (--d->NumAssignments == 0 && !d->LoadingInProgress)",
      "    if (--d->NumAssignments == 0)"),
    M("rm_zero", "    if (--d->NumAssignments == 0 && !d->LoadingInProgress)",
      "    if (--d->NumAssignments <= 1 && !d->LoadingInProgress)"),
    # DeleteLoadedTextureData.
    M("dl_done", "    if (d->LoadingCompleted)\n        texturepack_unassign",
      "    if (!d->LoadingCompleted)\n        texturepack_unassign"),
    M("dl_size", "                                          sub32(d->HighPos, d->LowPos));\n    else",
      "                                          d->HighPos);\n    else"),
    M("dl_pos", "        texturepack_unassign_texture_data(p, d->LowPos,",
      "        texturepack_unassign_texture_data(p, 0,"),
    M("dl_nyl", "    else\n        p->NumNotYetLoadedTextureDatas--;", "    else\n        ;"),
    M("dl_wait", "        gEWaitUntilRenderingDoneFn();\n    list_unlink(&d->Node);",
      "        ;\n    list_unlink(&d->Node);"),
    M("dl_unlink", "    list_unlink(&d->Node);\n    loadedtexturedata_destruct(d, 3);\n}",
      "    loadedtexturedata_destruct(d, 3);\n}"),
    M("dl_free", "    list_unlink(&d->Node);\n    loadedtexturedata_destruct(d, 3);\n}",
      "    list_unlink(&d->Node);\n    loadedtexturedata_destruct(d, 2);\n}"),
    # LoadTextureFromFile and UnloadTextureFromFile.
    M("lt_img", "    if (t->ImageSize != 0)\n        texturepack_add",
      "    if (1)\n        texturepack_add"),
    M("lt_img_size", "texturepack_add_loaded_texture_data(p, t->ImagePlacement,\n"
      "                                            t->ImageSize);",
      "texturepack_add_loaded_texture_data(p, t->ImagePlacement,\n"
      "                                            t->PaletteSize);"),
    M("lt_pal", "    if (t->PaletteSize != 0)\n        texturepack_add",
      "    if (1)\n        texturepack_add"),
    M("lt_pal_pos", "texturepack_add_loaded_texture_data(p, t->PalettePlacement,",
      "texturepack_add_loaded_texture_data(p, t->ImagePlacement,"),
    M("ut_img", "    if (t->ImageSize != 0)\n        texturepack_remove",
      "    if (1)\n        texturepack_remove"),
    M("ut_img_size", "texturepack_remove_loaded_texture_data(p, t->ImagePlacement,\n"
      "                                               t->ImageSize);",
      "texturepack_remove_loaded_texture_data(p, t->ImagePlacement,\n"
      "                                               t->PaletteSize);"),
    M("ut_pal", "    if (t->PaletteSize != 0)\n        texturepack_remove",
      "    if (1)\n        texturepack_remove"),
    M("ut_pal_pos", "texturepack_remove_loaded_texture_data(p, t->PalettePlacement,",
      "texturepack_remove_loaded_texture_data(p, t->ImagePlacement,"),
    # LoadTexturesFromFile.
    M("lts_zero", "        TextureInfo *t = *hashes != 0 ? texturepack_get_texture(p, *hashes)\n"
      "                                      : NULL;\n\n        if (t != NULL)\n"
      "            texturepack_load_texture_from_file",
      "        TextureInfo *t = texturepack_get_texture(p, *hashes);\n\n"
      "        if (t != NULL)\n            texturepack_load_texture_from_file"),
    M("lts_miss", "        if (t != NULL)\n            texturepack_load_texture_from_file(p, t);",
      "        texturepack_load_texture_from_file(p, t);"),
    M("lts_count", "    for (; n > 0; n--, hashes++) {\n        TextureInfo *t = *hashes != 0 ? texturepack_get_texture(p, *hashes)\n"
      "                                      : NULL;\n\n        if (t != NULL)\n"
      "            texturepack_load_texture_from_file",
      "    for (; n > 1; n--, hashes++) {\n        TextureInfo *t = *hashes != 0 ? texturepack_get_texture(p, *hashes)\n"
      "                                      : NULL;\n\n        if (t != NULL)\n"
      "            texturepack_load_texture_from_file"),
    M("lts_cb", "    if (cb != NULL) {\n        // An empty range", "    if (1) {\n        // An empty range"),
    M("lts_pool", "        d = (LoadedTextureData *)bMalloc((int)sizeof *d, \"LoadedTextureData\",\n"
      "                                         0, 16);",
      "        d = (LoadedTextureData *)bMalloc((int)sizeof *d, \"LoadedTextureData\",\n"
      "                                         0, 64);"),
    M("lts_param", "        d->CallbackParam = param;", "        d->CallbackParam = 0;"),
    M("lts_mempool", "        d->MemoryPool = p->MemoryPool;\n        d->LowPos = 0;",
      "        d->MemoryPool = 16;\n        d->LowPos = 0;"),
    M("lts_lo", "        d->LowPos = 0;\n        d->HighPos = 0;", "        d->LowPos = 1;\n        d->HighPos = 0;"),
    M("lts_hi", "        d->HighPos = 0;\n        d->NumAssignments = 0;",
      "        d->NumAssignments = 0;"),
    M("lts_n", "        d->NumAssignments = 0;\n        d->LoadingCompleted = 0;",
      "        d->NumAssignments = 1;\n        d->LoadingCompleted = 0;"),
    M("lts_done", "        d->LoadingCompleted = 0;\n        d->LoadingInProgress = 0;\n        link_tail",
      "        d->LoadingInProgress = 0;\n        link_tail"),
    M("lts_busy", "        d->LoadingCompleted = 0;\n        d->LoadingInProgress = 0;\n        link_tail",
      "        d->LoadingCompleted = 0;\n        link_tail"),
    M("lts_nyl", "        p->NumNotYetLoadedTextureDatas++;\n        d->Callback = cb;",
      "        d->Callback = cb;"),
    M("lts_cbset", "        d->Callback = cb;", "        d->Callback = NULL;"),
    M("lts_buf", "        d->Callback = cb;\n        d->Buf = NULL;", "        d->Callback = cb;"),
    M("lts_service", "    texturepack_service_loading_textures(p);\n}\n\nvoid texturepack_unload_textures",
      "}\n\nvoid texturepack_unload_textures"),
    # UnloadTexturesFromFile.
    M("uts_zero", "        TextureInfo *t = *hashes != 0 ? texturepack_get_texture(p, *hashes)\n"
      "                                      : NULL;\n\n        if (t != NULL)\n"
      "            texturepack_unload_texture_from_file",
      "        TextureInfo *t = texturepack_get_texture(p, *hashes);\n\n"
      "        if (t != NULL)\n            texturepack_unload_texture_from_file"),
    M("uts_miss", "        if (t != NULL)\n            texturepack_unload_texture_from_file(p, t);",
      "        texturepack_unload_texture_from_file(p, t);"),
    M("uts_count", "    for (; n > 0; n--, hashes++) {\n        TextureInfo *t = *hashes != 0 ? texturepack_get_texture(p, *hashes)\n"
      "                                      : NULL;\n\n        if (t != NULL)\n"
      "            texturepack_unload_texture_from_file",
      "    for (; n > 1; n--, hashes++) {\n        TextureInfo *t = *hashes != 0 ? texturepack_get_texture(p, *hashes)\n"
      "                                      : NULL;\n\n        if (t != NULL)\n"
      "            texturepack_unload_texture_from_file"),
    # ServiceLoadingTextures.
    M("sv_cur", "    if (p->CurrentLoadingTextureData != NULL)\n        return;\n    waiting",
      "    waiting"),
    M("sv_zero", "    if (waiting == 0)\n        return;\n", ""),
    M("sv_buf", "        if (d->Buf != NULL)\n            continue;\n        if (d->HighPos == d->LowPos) {",
      "        if (d->HighPos == d->LowPos) {"),
    M("sv_empty", "        if (d->HighPos == d->LowPos) {", "        if (0) {"),
    M("sv_mk_unlink", "            list_unlink(n);\n            p->Num", "            p->Num"),
    M("sv_mk_nyl", "            p->NumNotYetLoadedTextureDatas = waiting + 1;",
      "            p->NumNotYetLoadedTextureDatas = waiting - 1;"),
    M("sv_mk_cbnull", "            if (d->Callback != NULL)\n                d->Callback",
      "            if (1)\n                d->Callback"),
    M("sv_mk_param", "                d->Callback(d->CallbackParam);",
      "                d->Callback(0);"),
    M("sv_mk_free", "            loadedtexturedata_destruct(d, 3);\n            texturepack_service",
      "            texturepack_service"),
    M("sv_mk_again", "            texturepack_service_loading_textures(p);\n            return;",
      "            return;"),
    M("sv_mk_order", "            if (d->Callback != NULL)\n                d->Callback(d->CallbackParam);\n"
      "            loadedtexturedata_destruct(d, 3);\n",
      "            {\n                LoadedTextureDataCallback cb = d->Callback;\n"
      "                intptr_t prm = d->CallbackParam;\n\n"
      "                loadedtexturedata_destruct(d, 3);\n"
      "                if (cb != NULL)\n                    cb(prm);\n            }\n"),
    M("sv_busy", "        d->LoadingInProgress = 1;", "        d->LoadingInProgress = 0;"),
    M("sv_curset", "        p->CurrentLoadingTextureData = d;\n", ""),
    M("sv_nyl", "        p->NumNotYetLoadedTextureDatas--;\n        d->Buf", "        d->Buf"),
    M("sv_pool", "\"LoadedTextureData\", 0, d->MemoryPool);",
      "\"LoadedTextureData\", 0, p->MemoryPool);"),
    M("sv_size", "        d->Buf = (uint8_t *)bMalloc(sub32(d->HighPos, d->LowPos),",
      "        d->Buf = (uint8_t *)bMalloc(d->HighPos,"),
    M("sv_name", "        add_queued_file(d->Buf, p->Filename,", "        add_queued_file(d->Buf, p->Name,"),
    M("sv_pos", "                        add32(p->TextureDataFilePos, d->LowPos),",
      "                        d->LowPos,"),
    M("sv_n", "                        sub32(d->HighPos, d->LowPos), read_callback,",
      "                        d->HighPos, read_callback,"),
    M("sv_one", "                        (intptr_t)p);\n        return;\n    }",
      "                        (intptr_t)p);\n    }"),
    # ReadCallback.
    M("rc_cur", "    p->CurrentLoadingTextureData = NULL;\n    texturepack_assign",
      "    texturepack_assign"),
    M("rc_pos", "    texturepack_assign_texture_data(p, d->Buf, d->LowPos,",
      "    texturepack_assign_texture_data(p, d->Buf, 0,"),
    M("rc_size", "                                    sub32(d->HighPos, d->LowPos));\n    d->LoadingInProgress = 0;",
      "                                    d->HighPos);\n    d->LoadingInProgress = 0;"),
    M("rc_busy", "    d->LoadingInProgress = 0;\n    d->LoadingCompleted = 1;",
      "    d->LoadingCompleted = 1;"),
    M("rc_done", "    d->LoadingCompleted = 1;", "    d->LoadingCompleted = 0;"),
    M("rc_fixup", "    efix_up_tables();\n", ""),
    M("rc_delete", "    if (d->NumAssignments == 0)\n        texturepack_delete",
      "    if (0)\n        texturepack_delete"),
    M("rc_service", "        texturepack_delete_loaded_texture_data(p, d);\n"
      "    texturepack_service_loading_textures(p);\n}",
      "        texturepack_delete_loaded_texture_data(p, d);\n}"),
    # UnloadAllTexturesFromFile and GetLoadedSize.
    M("ua_n", "        ltd(n)->NumAssignments = 0;\n", ""),
    M("ua_busy", "        if (!ltd(n)->LoadingInProgress)\n            texturepack_delete",
      "        if (1)\n            texturepack_delete"),
    M("ua_nyl", "    p->NumNotYetLoadedTextureDatas = 0;\n}", "}"),
    M("gs_sum", "        size = add32(size, sub32(ltd(n)->HighPos, ltd(n)->LowPos));",
      "        size = sub32(ltd(n)->HighPos, ltd(n)->LowPos);"),
    M("gs_lo", "        size = add32(size, sub32(ltd(n)->HighPos, ltd(n)->LowPos));",
      "        size = add32(size, ltd(n)->HighPos);"),
    # ~LoadedTextureData and ~TexturePack's wait, in texturepack.c.
    M("ltdd_buf", "    if (d->Buf != NULL)\n        bFree(d->Buf);\n    if (flags & 1)",
      "    if (flags & 1)", TP),
    M("dtor_wait", "    while (p->CurrentLoadingTextureData != NULL\n           && gServiceQueuedFilesFn",
      "    if (p->CurrentLoadingTextureData != NULL\n           && gServiceQueuedFilesFn", TP),
]

EQUIVALENT = {}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    hostbuild.recover()
    m = Model()
    sc = script()
    base = m.run(sc)
    caught, survived, missing, equivalent = 0, [], [], []
    scdir = tempfile.TemporaryDirectory()
    scp = Path(scdir.name) / "scenarios.txt"
    scp.write_text(encode(sc))
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, scp, out)
        if diff(base, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for mut in todo:
        name, rel, before, after = mut
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if text.count(probe) != 1:
            missing.append(name)
            print("  %-36s PATTERN %s" % (
                name, "NOT FOUND" if not text.count(probe) else "NOT UNIQUE"))
            continue
        new = text.replace(probe, repl, 1)
        try:
            hostbuild.write_source(path, new)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = build_harness(tmp)
                except SystemExit:
                    print("  %-36s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, scp, out)
                if rc == pcc.HARNESS_HUNG:
                    print("  %-36s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-36s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-36s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-36s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-36s SURVIVED" % name)
                    survived.append(name)
        finally:
            try:
                hostbuild.write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))
    scdir.cleanup()

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

    m = Model()
    sc = script()
    lines = m.run(sc)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = Path(tmp) / "scenarios.txt"
        scp.write_text(encode(sc))
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(lines, harness)
    ops = sum(len(s) for s in sc)
    print("%d scenarios, %d ops, %d lines, %d differ"
          % (len(sc), ops, len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
