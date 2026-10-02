#!/usr/bin/env python3
r"""Cross-check 3DS Files/source/resource.c and queuedfile.c, retail's
ResourceFile and QueuedFile, against the retail image itself, run in
mipsemu.

The model is the image. ResourceFile's constructor (0x00199320),
AllocateMemory (0x00199408), destructor (0x00199458),
LoadResourceIfFileTransferFinished (0x001994f0), FileTransferCallback
(0x001995d0) and GetSize (0x001995e0); both LoadResourceFile (0x00199640,
0x001996f0); ChangeFilenameForHotChunking (0x00199720, 0x00199a60);
UnloadResourceFile (0x00199728); ServiceResourceLoading (0x00199788);
IsResourceLoadingComplete (0x00199818); both FindResourceFile
(0x00199828, 0x00199890); GetResourceFileSize (0x001998c8); the list's
static constructor and destructor (0x00199a48, 0x00199a38); and all of
QueuedFile, 0x001ad6d8 .. 0x001add40, run as shipped. So do what runs
under them: LZDecompress (0x001b41c8), bList::Sort, bStrCpy, bStrNCpy,
bStrCmp and the destructors. The harness (tools/src/resource_test.c) runs
the port, with lzc.c and blist.c, over the same script, and the two
transcripts are diffed.

Stubbed on both sides, each printing its arguments:

- bWare's file calls (bfile.h), over a fake file system of named byte
  strings. A read's bytes land at once; its callback is due a set number
  of bServiceFileSystem calls later (K), as the IOP's would be.
- bMalloc and bFree: blocks from a fake heap, 128-aligned and filled with
  0xcd, labelled hN in order.
- the slot pool, as carloader_check stubs it.
- LoadChunks and UnloadChunks, which print the CRC of the bytes they are
  given, and PostLoadFixup and eWaitUntilRenderingDone.
- Joylog's GetData, which answers what the script set (J), and AddData.
- the callbacks: cb prints, and cb2 prints and loads another file from
  inside ServiceResourceLoading (CH names it); qcb prints, and qcb2 prints
  and queues another read from inside ServiceQueuedFiles.

bRemoveCodeineInventory is stubbed silent: the port leaves it out
(resource.h).

The files are the disc's own GLOBAL\PRERACEANIM.LZC and
CARS\PARCELVAN\GEOMETRY.LZC, so the image's LZDecompress and lzc.c expand
the same real blocks, and small bundles made here: plain chunks, a stored
COMP block and an empty one. After each op the transcript holds the
globals, both lists and every back link.

    python tools/resource_check.py
    python tools/resource_check.py --mutate [--only a,b]
    python tools/resource_check.py --dump out/resource
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

HARNESS = "tools/src/resource_test.c"
RES = "3DS Files/source/resource.c"
QF = "3DS Files/source/queuedfile.c"
SOURCES = [HARNESS, RES, QF] + ["3DS Files/source/" + f for f in (
    "blist.c", "lzc.c")]

HARNESS_TIMEOUT = 120

DATA = ROOT / "extracted-retail"

# ================================================================ the image

GP = 0x003358f0
RES_CTOR = 0x00199320
LOAD_RES = 0x00199640
LOAD_RES6 = 0x001996f0
CHANGE_NAME = 0x00199720
UNLOAD_RES = 0x00199728
SERVICE_RES = 0x00199788
IS_COMPLETE = 0x00199818
FIND_NAME = 0x00199828
FIND_TYPE = 0x00199890
GET_SIZE = 0x001995e0
GET_RES_SIZE = 0x001998c8
RES_SDTOR = 0x00199a38
RES_SINIT = 0x00199a48
FTCB = 0x001995d0

SERVICE_QF = 0x001ad850
FIND_QF = 0x001ad9d8
INIT_QF = 0x001ada10
CLOSE_QF = 0x001ada40
ADD_QF = 0x001ada60
CHANGE_QF = 0x001adb08
ABORT_QF = 0x001adb48
QF_SDTOR = 0x001adc68
QF_SINIT = 0x001adc78
READ_DONE = 0x001adc90

B_OPEN = 0x002544c0
B_CLOSE = 0x002544e8
B_SIZE_F = 0x00254550
B_SIZE_N = 0x00254568
B_SEEK = 0x00254830
B_READ = 0x002546e8
B_SERVICE = 0x002539b8
JOY_GET = 0x00183358
JOY_ADD = 0x00183498
NEW_POOL = 0x00257c10
DEL_POOL = 0x00257c48
O_MALLOC = 0x00257c80
POOL_FREE = 0x00257ca0
B_MALLOC = 0x002577c0
B_FREE = 0x00257850
LOAD_CHUNKS = 0x00199280
UNLOAD_CHUNKS = 0x001992a8
FIXUP = 0x001992d0
WAIT_RENDER = 0x00111dd8
CODEINE = 0x0025d490
MEMCPY = 0x00296e14

G_HOT = GP - 19960                # HotChunkFilesNeedUpdating
G_RLIST = GP - 19952              # ResourceFileList
G_NUMRES = GP - 19944             # NumResourcesBeingLoaded
G_QPOOL = GP - 19120              # QueuedFileSlotPool
G_HANDLE = GP - 19116             # QueuedFile::CurrentHandle
G_READING = GP - 19112            # QueuedFileReadInProgress
G_QLIST = GP - 19104              # QueuedFileList
G_REPLAY = GP - 20668             # Joylog::ReplayingFlag

SLOT_BASE = 0x01100000
SLOT_STRIDE = 128
NSLOT = 32
NAMEBUF = 0x01200200
NAMEBUF2 = 0x01200300
COUNTBUF = 0x01200100
POOL_TOK = 0x01300000
FILE_TOK = 0x01300100
MAXFILES = 256
CB = 0x01320000
CB2 = 0x01320010
QCB = 0x01320020
QCB2 = 0x01320030
HEAP = 0x01400000
HEAP_END = 0x01d00000
MAX_FS = 400
LIMIT = 50000000

RES_FLAGS = 12
RES_NAME = 16
RES_HOT = 96


# ============================================================ the scenarios

def chunk(cid, payload):
    return struct.pack("<II", cid, len(payload)) + payload


BUNA = (chunk(0x1001, bytes(range(16))) + chunk(0x1002, b"\x11" * 40)
        + chunk(0x1001, b"\x22" * 8) + chunk(0, bytes(4)))
BUNB = chunk(0x2001, b"\x33" * 24) + chunk(0x1001, b"\x44" * 12)
COMP0 = b"COMP" + struct.pack("<HHII", 0x1001, 0, 0, 16)


def comp_stored(data):
    return b"COMP" + struct.pack("<HHII", 0x1001, 1, len(data),
                                 16 + len(data)) + data


def FS(name, data):
    return "FS %s %s" % (name, data.hex())


def disc(rel):
    return (DATA / rel).read_bytes()


PRERACE = "GLOBAL" + BS + "PRERACEANIM.LZC"
PARCEL = "CARS" + BS + "PARCELVAN" + BS + "GEOMETRY.LZC"
GBUNA = "GLOBAL" + BS + "BUNA.BUN"


def s_boot():
    return [
        "R", "RC", "S",
        "FN " + GBUNA, "FT 2",
        "GT 2 0 1", "GT 2 0 0",
        "FQ 1", "A 5", "P 5 1 1",
        "X", "I",
    ]


def s_raw():
    return [
        FS(GBUNA, BUNA),
        "L %s 2 0 1 7" % GBUNA,
        "RC",
        "R", "R", "RC",
        "GS 0 0 1", "GS 0 4097 1", "GS 0 4098 0", "GS 0 12345 1",
        "GT 2 0 1", "GT 2 4097 1", "GT 3 0 1", "GT 2 4097 0",
        "FN " + GBUNA, "FN GLOBAL" + BS + "BUNA", "FT 2", "FT 5",
        "U 0",
        "R", "RC",
        # Temporary memory, and freed after loading.
        "L %s 1 6 1 8" % GBUNA,
        "R", "R",
        "GS 1 0 1",
        "U 1",
        "L %s 1 2 0 0" % GBUNA, "R", "R", "GS 2 4097 1", "U 2",
        "L %s 1 1 1 -3" % GBUNA, "R", "R", "U 3",
        # Both at once: one file per call.
        "L %s 2 0 1 1" % GBUNA, "L %s 3 4 1 2" % GBUNA,
        "R", "R", "R", "R", "R",
        "GT 2 0 1", "GT 3 0 1",
        "U 5", "U 4",
    ]


def s_lz():
    return [
        FS(PRERACE, disc("GLOBAL/PRERACEANIM.LZC")),
        "L %s 2 8 1 1" % PRERACE,
        "N 0 GLOBAL" + BS + "PRERACEANIM.BUN",
        "FN " + PRERACE, "FN GLOBAL" + BS + "PRERACEANIM.BUN",
        "R", "R",
        "GS 0 0 1", "GS 0 %d 1" % 0x80034008, "GS 0 1 1",
        "GT 2 0 1",
        "U 0",
        "L %s 2 14 1 2" % PRERACE, "R", "R", "GS 1 0 1", "U 1",
        # A stored block, an empty one, and a block without the flag.
        FS("S.LZC", comp_stored(BUNA)),
        "L S.LZC 3 8 1 3", "R", "R", "GS 2 0 1", "GS 2 4097 1", "U 2",
        FS("Z.LZC", COMP0),
        "L Z.LZC 3 8 1 4", "R", "R", "GS 3 0 1", "U 3",
        "L S.LZC 3 0 1 5", "R", "R", "U 4",
        # The flag on a file that is no block.
        FS(GBUNA, BUNA),
        "L %s 3 8 1 6" % GBUNA, "R", "R", "GS 5 0 1", "U 5",
        # A car's geometry, as the car loader asks for one.
        FS(PARCEL, disc("CARS/PARCELVAN/GEOMETRY.LZC")),
        "L %s 5 8 0 0" % PARCEL, "R", "R",
        "GT 5 0 1", "GT 5 %d 1" % 0x34013, "GT 5 %d 1" % 0x80034000,
        "U 6",
    ]


def s_missing():
    return [
        # Not on the disc, and on it with nothing in it: no read.
        "L NOPE.BUN 2 0 1 1",
        "RC", "R", "RC",
        FS("GLOBAL" + BS + "INGAMEA.BUN", b""),
        "L GLOBAL" + BS + "INGAMEA.BUN 2 0 1 2", "R",
        "GS 1 0 1",
        "U 0", "U 1",
        # Gone before its read, and shorter than it was.
        FS("GONE.BUN", BUNA), "L GONE.BUN 2 0 1 3", "FD GONE.BUN",
        "R", "R", "R", "U 2",
        FS("SHORT.BUN", BUNA), "L SHORT.BUN 2 0 1 4",
        FS("SHORT.BUN", BUNA[:20]), "R", "R", "U 3",
        # A block whose read failed: the fill is no COMP.
        FS("GONE.LZC", comp_stored(BUNA)), "L GONE.LZC 2 8 1 5",
        "FD GONE.LZC", "R", "R", "U 4",
        # Unloaded while its read is still out.
        FS(GBUNA, BUNA), "K 3", "L %s 2 0 1 6" % GBUNA, "U 5",
        "K 1",
        # Compressed, and not on the disc: nothing to expand.
        "L NOPE.LZC 2 8 1 9", "R", "U 6",
    ]


def s_order():
    return [
        FS("A.BUN", BUNA), FS("B.BUN", BUNB), FS("C.BUN", BUNA[:24]),
        "K 2",
        "L A.BUN 2 0 1 1", "L B.BUN 2 0 1 2", "L C.BUN 3 0 1 3",
        "R", "R", "R", "R", "R", "R", "R", "R",
        "FN A.BUN", "FT 2", "FT 3",
        # A second A: the newest is found.
        "L A.BUN 2 0 1 4",
        "FN A.BUN", "FT 2",
        "R", "R", "R",
        # The middle one, and a type's newest after it goes.
        "U 1",
        "FN B.BUN", "FT 2", "GT 2 0 1", "GT 2 4097 1",
        # A callback that asks for another file, from inside the service.
        "CH C.BUN",
        "L B.BUN 3 0 2 5",
        "R", "R", "R", "R", "R", "R", "R", "R",
        "FN C.BUN", "GT 3 0 1",
        # Renamed: found by the new name, and the old one's twin by it.
        "N 0 C.BUN", "FN C.BUN", "FN A.BUN",
        "U 3", "U 0", "U 2",
        "Z",
        "R", "S",
    ]


def s_queue():
    big = bytes(range(256)) * 20
    return [
        FS("BIG.BIN", big),
        "Q BIG.BIN 0 5120 5120 1 11",
        "P 1 5 1000",
        "S", "S", "S", "S",
        FS("SMALL.BIN", b"hello world!" * 4),
        "Q SMALL.BIN 4 20 32 1 12",
        "P 2 1 1000000",
        "S", "S", "S", "S", "S", "S", "S", "S", "S", "S", "S", "S",
        "BQ 0 5120", "BQ 1 20",
        # Aborted waiting, reading, not queued, and between blocks.
        "Q BIG.BIN 0 100 128 1 13", "A 3",
        "Q BIG.BIN 0 100 128 1 14", "S", "A 4", "A 4", "S", "S",
        "A 99", "FQ 99", "P 99 1 1",
        "Q BIG.BIN 0 3000 3072 1 15", "P 5 5 1000", "S", "S", "A 5", "S",
        "FQ 5",
        # Past the end, not there, and nothing to read.
        "Q BIG.BIN 5000 200 256 1 16", "S", "S",
        "Q NONE.BIN 0 10 16 1 17", "S", "S",
        "Q BIG.BIN 0 0 16 1 18", "S", "S",
        # A completion that queues another read.
        "Q SMALL.BIN 0 8 16 2 19", "S", "S", "S", "S", "S",
        # The handle comes round to 1.
        "V handle 99999",
        "Q SMALL.BIN 0 4 16 1 20", "Q SMALL.BIN 4 4 16 1 21",
        "Q SMALL.BIN 8 4 16 0 0",
        "FQ 99999", "FQ 100000", "FQ 1",
        # Equal priorities keep their order; a lower one goes first.
        "P 100000 3 1000", "P 1 3 1000",
        "S", "S", "S", "S", "S", "S", "S",
        # A slower read, seen part way.
        "K 3", "Q SMALL.BIN 0 48 48 1 22", "S", "S", "S", "S", "K 1",
        "BQ 9 48",
        "Q SMALL.BIN 0 4 16 1 23", "Q BIG.BIN 0 4 16 1 24",
        "Z",
    ]


def s_queue2():
    big = bytes(range(256)) * 20
    return [
        FS("BIG.BIN", big), FS("X.BIN", b"0123456789abcdef"),
        # Blocks that run past the end part way.
        "Q BIG.BIN 4000 2000 2048 1 25", "P 1 5 1000",
        "S", "S", "S", "S", "S",
        # Aborted after its open failed: still called, with 1.
        "Q NONE.BIN 0 10 16 1 26", "S", "A 2", "S", "S",
        # An error by the recording while the read is out: waited for.
        "V replay 1", "K 3", "J 3", "Q X.BIN 0 10 16 1 27",
        "S", "S", "S", "K 1", "V replay 0",
        # No callback.
        "Q X.BIN 0 4 16 0 0", "S", "S", "L X.BIN 2 0 0 0", "R", "R", "R",
    ]


def s_joylog():
    return [
        FS("X.BIN", b"0123456789abcdef"),
        "Q X.BIN 0 10 16 1 1", "S", "S",
        "V replay 1",
        # The recording says still reading, then done.
        "J 1", "Q X.BIN 0 10 16 1 2", "S", "S", "J 2", "S",
        # Done by the recording while the read is out: waited for.
        "K 4", "J 2", "Q X.BIN 0 10 16 1 3", "S", "S", "K 1",
        # An error, whatever the read did.
        "J 3", "Q X.BIN 0 10 16 1 4", "S", "S",
        # Waiting, by the recording.
        "J 0", "Q X.BIN 0 10 16 1 5", "S", "S", "J 2", "S",
        # Done by the recording, done by the read already.
        "J 2", "Q X.BIN 0 10 16 1 6", "S", "S",
        "V replay 0",
        "Q X.BIN 0 10 16 1 7", "S", "S",
    ]


def s_hot():
    long = "L" * 90
    return [
        FS(GBUNA, BUNA),
        "L %s 2 0 1 1" % GBUNA, "R", "R", "H 0", "U 0",
        "L %s 2 4 1 2" % GBUNA, "R", "R", "H 1", "U 1",
        # The six-argument LoadResourceFile.
        "LH %s 2 1 0 1 3" % GBUNA, "LH %s 2 0 1 1 4" % GBUNA,
        "LH %s 2 0 0 0 5" % GBUNA, "LH %s 2 7 9 2 6" % GBUNA,
        "CH " + GBUNA,
        "R", "R", "R", "R", "R", "R", "R", "R", "R", "R",
        "GT 2 0 1",
        # A new name longer than the field: no terminator of its own.
        "N 2 " + long, "N 3 SHORT",
        "FN SHORT", "FN " + GBUNA,
        # The destructors, over files loaded, freed and still loading.
        "K 3", "L %s 2 0 1 7" % GBUNA, "R",
        "Z",
        # Counted as loading with nothing on the list.
        "V reading 0", "R", "RC",
        "C", "0",
    ]


def s_unload_wait():
    return [
        FS("W.BUN", BUNB), FS("V.BUN", BUNA),
        "K 3",
        "L W.BUN 2 0 1 1", "L V.BUN 2 0 1 2",
        # The second, while the first is still out: both load first.
        "U 1",
        "RC",
        "U 0",
        "RC", "R",
        # Not counted, so not looked at.
        "K 1", "L W.BUN 2 0 1 3", "V numres 0", "R", "R", "R", "RC",
    ]


def script():
    head = ["C", "0", "I"]
    return [head + s for s in (
        s_boot(), s_raw(), s_lz(), s_missing(), s_order(), s_queue(),
        s_queue2(), s_joylog(), s_hot(), s_unload_wait())]


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


class Model(object):
    def __init__(self):
        self.out = []
        self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        e = self.e
        self.reset()
        for a, fn in ((B_OPEN, self.s_open), (B_CLOSE, self.s_close),
                      (B_SIZE_F, self.s_size_f), (B_SIZE_N, self.s_size_n),
                      (B_SEEK, self.s_seek), (B_READ, self.s_read),
                      (B_SERVICE, self.s_service_fs),
                      (JOY_GET, self.s_joy_get), (JOY_ADD, self.s_joy_add),
                      (NEW_POOL, self.s_new_pool),
                      (DEL_POOL, self.s_del_pool),
                      (O_MALLOC, self.s_omalloc), (POOL_FREE, self.s_pfree),
                      (B_MALLOC, self.s_malloc), (B_FREE, self.s_free),
                      (LOAD_CHUNKS, self.s_load_chunks),
                      (UNLOAD_CHUNKS, self.s_unload_chunks),
                      (FIXUP, self.s_fixup), (WAIT_RENDER, self.s_wait),
                      (CODEINE, self.s_codeine), (MEMCPY, self.s_memcpy),
                      (CB, self.s_cb), (CB2, self.s_cb2), (QCB, self.s_qcb),
                      (QCB2, self.s_qcb2)):
            e.stub(a, fn)

    def reset(self):
        self.rfs = []
        self.qbufs = []
        self.fs = {}
        self.files = []
        self.reads = []
        self.latency = 1
        self.joy = 0
        self.chain = "CHAIN.BUN"
        self.used = [False] * NSLOT
        self.heap = []
        self.top = HEAP
        self.fs_calls = 0

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

    # ---- the labels ------------------------------------------------------

    def nm(self, a):
        a &= M32
        if a == 0:
            return "NULL"
        named = {POOL_TOK: "pool", G_RLIST: "RL", G_QLIST: "QL", CB: "cb",
                 CB2: "cb2", QCB: "qcb", QCB2: "qcb2", READ_DONE: "rdone",
                 FTCB: "ftcb"}
        if a in named:
            return named[a]
        if (SLOT_BASE <= a < SLOT_BASE + SLOT_STRIDE * NSLOT
                and (a - SLOT_BASE) % SLOT_STRIDE == 0):
            return "#%d" % ((a - SLOT_BASE) // SLOT_STRIDE)
        if FILE_TOK <= a < FILE_TOK + MAXFILES:
            return "f%d" % (a - FILE_TOK)
        for i, (base, size, _live) in enumerate(self.heap):
            if base <= a < base + max(size, 1):
                return "h%d" % i if a == base else "h%d+%d" % (i, a - base)
        return "?"

    def pm(self, a):
        """A parameter: a label when it is one, else the number."""
        n = self.nm(a)
        return "%d" % s32(a) if n == "?" else n

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

    def alloc(self, size):
        base = (self.top + 127) & ~127
        if base + size > HEAP_END:
            raise SystemExit("heap full")
        self.top = base + max(size, 1)
        self.heap.append([base, size, True])
        self.e.write(base, b"\xcd" * size)
        return base

    def s_malloc(self, em):
        size = s32(self.arg(0))
        a = self.alloc(size)
        self.emit("  malloc %d %s %d %d -> %s" % (
            size, esc(self.cstr(self.arg(1), 160)), s32(self.arg(2)),
            s32(self.arg(3)), self.nm(a)))
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
        return n

    def s_seek(self, em):
        f = self.file(self.arg(0))
        f[2] = s32(self.arg(1))
        self.emit("  seek %s %d %d" % (self.nm(self.arg(0)), f[2],
                                       s32(self.arg(2))))

    def s_read(self, em):
        fa, buf, n = self.arg(0), self.arg(1), s32(self.arg(2))
        cb, param = self.arg(3), self.arg(4)
        f = self.file(fa)
        self.emit("  read %s %s %d %s %s" % (self.nm(fa), self.nm(buf), n,
                                             self.nm(cb), self.pm(param)))
        if n > 0:
            self.e.write(buf, f[1][f[2]:f[2] + n])
            f[2] += n
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
        self.emit("  joyget %d %d -> %d" % (s32(self.arg(0)),
                                            s32(self.arg(1)), self.joy))
        return self.joy & M32

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

    def s_load_chunks(self, em):
        a, n = self.arg(0), s32(self.arg(1))
        self.emit("  loadchunks %s %d %s" % (self.nm(a), n, self.crc(a, n)))

    def s_unload_chunks(self, em):
        a, n = self.arg(0), s32(self.arg(1))
        self.emit("  unloadchunks %s %d %s" % (self.nm(a), n,
                                               self.crc(a, n)))

    def s_fixup(self, em):
        self.emit("  fixup")

    def s_wait(self, em):
        self.emit("  waitrender")

    def s_codeine(self, em):
        pass

    def s_memcpy(self, em):
        d, s, n = self.arg(0), self.arg(1), s32(self.arg(2))
        e = self.e
        e.mem[d:d + n] = e.mem[s:s + n]
        return d

    def s_cb(self, em):
        self.emit("  callback %s" % self.pm(self.arg(0)))

    def s_cb2(self, em):
        self.emit("  callback2 %s" % self.pm(self.arg(0)))
        self.e.write(NAMEBUF2, self.chain.encode("latin-1") + b"\0")
        rf = self.nested(LOAD_RES, NAMEBUF2, 3, 0, CB, 99)
        self.rfs.append(rf & M32)
        self.emit("  chained %s" % self.nm(rf))

    def s_qcb(self, em):
        self.emit("  qcallback %s %d" % (self.pm(self.arg(0)),
                                         s32(self.arg(1))))

    def s_qcb2(self, em):
        self.emit("  qcallback2 %s %d" % (self.pm(self.arg(0)),
                                          s32(self.arg(1))))
        buf = self.alloc(16)
        self.qbufs.append(buf)
        self.e.write(NAMEBUF2, b"SMALL.BIN\0")
        h = self.nested(ADD_QF, buf, NAMEBUF2, 2, 6, QCB, 77)
        self.emit("  queued %d %s" % (h, self.nm(buf)))

    # ---- the print -------------------------------------------------------

    def print_state(self):
        e = self.e
        self.emit("st n=%d hot=%d handle=%d reading=%d pool=%s replay=%d" % (
            s32(e.u32(G_NUMRES)), s32(e.u32(G_HOT)), s32(e.u32(G_HANDLE)),
            s32(e.u32(G_READING)), self.nm(e.u32(G_QPOOL)),
            s32(e.u32(G_REPLAY))))
        n, k = e.u32(G_RLIST), 0
        while n != G_RLIST and n != 0 and k < 64:
            self.emit(
                "rf %s type=%d flags=%d name=%s hot0=%02x xfer=%d done=%d "
                "cb=%s param=%s buf=%s size=%d hent=%s hnum=%d hno=%d inv=%d "
                "prev=%s" % (
                    self.nm(n), s32(e.u32(n + 8)), s32(e.u32(n + 12)),
                    esc(self.cstr(n + RES_NAME, 160)), e.u8(n + RES_HOT),
                    s32(e.u32(n + 176)), s32(e.u32(n + 180)),
                    self.nm(e.u32(n + 184)), self.pm(e.u32(n + 188)),
                    self.nm(e.u32(n + 192)), s32(e.u32(n + 196)),
                    self.nm(e.u32(n + 200)), s32(e.u32(n + 204)),
                    s32(e.u32(n + 208)), s32(e.u32(n + 212)),
                    self.nm(e.u32(n + 4))))
            n, k = e.u32(n), k + 1
        if n == 0:
            self.emit("rfs null")
        elif k == 64:
            self.emit("rfs loop")
        self.emit("rfs end prev=%s" % self.nm(e.u32(G_RLIST + 4)))
        n, k = e.u32(G_QLIST), 0
        while n != G_QLIST and n != 0 and k < 64:
            self.emit(
                "qf %s buf=%s name=%s pos=%d n=%d read=%d block=%d prio=%d "
                "cb=%s param=%s handle=%d status=%d abort=%d prev=%s" % (
                    self.nm(n), self.nm(e.u32(n + 8)),
                    esc(self.cstr(n + 12, 48)), s32(e.u32(n + 60)),
                    s32(e.u32(n + 64)), s32(e.u32(n + 68)),
                    s32(e.u32(n + 72)), s32(e.u32(n + 76)),
                    self.nm(e.u32(n + 80)), self.pm(e.u32(n + 84)),
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

    def cbsel(self, t, q=False):
        return ((0, QCB, QCB2) if q else (0, CB, CB2))[int(t)]

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
                    e.call(RES_SINIT, limit=LIMIT)
                    e.call(QF_SINIT, limit=LIMIT)
                elif op == "0":
                    for g, v in ((G_NUMRES, 0), (G_HOT, 0), (G_HANDLE, 1),
                                 (G_READING, 0), (G_REPLAY, 0)):
                        e.put32(g, v)
                elif op == "I":
                    e.call(INIT_QF, limit=LIMIT)
                elif op == "X":
                    e.call(CLOSE_QF, limit=LIMIT)
                elif op == "FS":
                    self.fs[t[1]] = bytes.fromhex(t[2]) if len(t) > 2 else b""
                    show = False
                elif op == "FD":
                    del self.fs[t[1]]
                    show = False
                elif op == "K":
                    self.latency = int(t[1])
                    show = False
                elif op == "J":
                    self.joy = int(t[1])
                    show = False
                elif op == "CH":
                    self.chain = t[1]
                    show = False
                elif op == "V":
                    g = {"replay": G_REPLAY, "handle": G_HANDLE, "reading": G_READING,
                         "numres": G_NUMRES}[t[1]]
                    e.put32(g, I(t[2]) & M32)
                elif op == "L":
                    self.put_name(t[1])
                    rf = e.call(LOAD_RES, NAMEBUF, int(t[2]), int(t[3]),
                                self.cbsel(t[4]), I(t[5]),
                                limit=LIMIT) & M32
                    self.rfs.append(rf)
                    self.emit("L -> %s" % self.nm(rf))
                elif op == "LH":
                    self.put_name(t[1])
                    rf = e.call(LOAD_RES6, NAMEBUF, int(t[2]), int(t[3]),
                                int(t[4]), self.cbsel(t[5]),
                                I(t[6]), limit=LIMIT) & M32
                    self.rfs.append(rf)
                    self.emit("LH -> %s" % self.nm(rf))
                elif op == "R":
                    self.emit("R -> %d" % e.call(SERVICE_RES, limit=LIMIT))
                elif op == "RC":
                    self.emit("RC -> %d" % e.call(IS_COMPLETE, limit=LIMIT))
                elif op == "U":
                    e.call(UNLOAD_RES, self.rfs[int(t[1])], limit=LIMIT)
                elif op == "N":
                    self.put_name(t[2])
                    e.call(CHANGE_NAME, self.rfs[int(t[1])], NAMEBUF,
                           limit=LIMIT)
                elif op == "FN":
                    self.put_name(t[1])
                    self.emit("FN -> %s" % self.nm(
                        e.call(FIND_NAME, NAMEBUF, limit=LIMIT)))
                    show = False
                elif op == "FT":
                    self.emit("FT -> %s" % self.nm(
                        e.call(FIND_TYPE, int(t[1]), limit=LIMIT)))
                    show = False
                elif op in ("GS", "GT"):
                    e.put32(COUNTBUF, 0xeeeeeeee)
                    cnt = COUNTBUF if int(t[3]) else 0
                    if op == "GS":
                        r = e.call(GET_SIZE, self.rfs[int(t[1])],
                                   I(t[2]), cnt, limit=LIMIT)
                    else:
                        r = e.call(GET_RES_SIZE, int(t[1]), I(t[2]),
                                   cnt, limit=LIMIT)
                    self.emit("%s -> %d %d" % (op, r, s32(e.u32(COUNTBUF))))
                    show = False
                elif op == "Q":
                    buf = self.alloc(int(t[4]))
                    self.qbufs.append(buf)
                    self.put_name(t[1])
                    h = e.call(ADD_QF, buf, NAMEBUF, int(t[2]), int(t[3]),
                               self.cbsel(t[5], True), I(t[6]),
                               limit=LIMIT)
                    self.emit("Q -> %d %s" % (h, self.nm(buf)))
                elif op == "P":
                    e.call(CHANGE_QF, int(t[1]), int(t[2]), int(t[3]),
                           limit=LIMIT)
                elif op == "A":
                    self.emit("A -> %d" % e.call(ABORT_QF, int(t[1]),
                                                 limit=LIMIT))
                elif op == "FQ":
                    self.emit("FQ -> %s" % self.nm(
                        e.call(FIND_QF, int(t[1]), limit=LIMIT)))
                    show = False
                elif op == "S":
                    e.call(SERVICE_QF, limit=LIMIT)
                elif op == "BQ":
                    self.emit("BQ -> %s" % self.crc(self.qbufs[int(t[1])],
                                                     int(t[2])))
                    show = False
                elif op == "H":
                    rf = self.rfs[int(t[1])]
                    hent = self.alloc(32)
                    e.put32(rf + 200, hent)
                    e.put32(rf + 204, 3)
                    e.put32(rf + 208, 5)
                    e.put32(rf + 212, 9)
                elif op == "Z":
                    e.call(RES_SDTOR, limit=LIMIT)
                    e.call(QF_SDTOR, limit=LIMIT)
                else:
                    raise SystemExit("bad op %r" % (t,))
                if show:
                    self.print_state()
        return self.out


# ================================================================ the build


def build_harness(tmp, name="resource_test"):
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


def M(name, before, after, rel=RES):
    return (name, rel, before, after)


MUTATIONS = [
    # ResourceFile's constructor and AllocateMemory.
    M("ctor_type", "    rf->Type = type;", "    rf->Type = flags;"),
    M("ctor_flags", "    rf->Flags = flags;", "    rf->Flags = flags & 7;"),
    M("ctor_name_cap", "copy_name(rf->Filename, sizeof rf->Filename, name);",
      "copy_name(rf->Filename, 8, name);"),
    M("ctor_cb", "    rf->Callback = cb;", "    rf->Callback = NULL;"),
    M("ctor_param", "    rf->CallbackParam = param;",
      "    rf->CallbackParam = param + 1;"),
    M("ctor_xfer0", "    rf->FileTransfersInProgress = 0;\n    rf->Loading",
      "    rf->Loading"),
    M("ctor_done0", "    rf->LoadingFinishedFlag = 0;\n", ""),
    M("ctor_hotno", "    rf->HotFileNumber = 0;", "    rf->HotFileNumber = 1;"),
    M("ctor_hent", "    rf->HotFileNumber = 0;\n    rf->pLoadedHotFileEntries = NULL;\n",
      "    rf->HotFileNumber = 0;\n"),
    M("ctor_hnum", "    rf->NumLoadedHotFileEntries = 0;\n    rf->Inv",
      "    rf->Inv"),
    M("ctor_inv", "    rf->InventoryHandle = 0;\n", ""),
    M("ctor_hot0", "    rf->HotFilename[0] = '\\0';\n", ""),
    M("ctor_clamp", "    if (rf->SizeofChunks < 0)",
      "    if (rf->SizeofChunks < -1)"),
    M("ctor_buf_null",
      "    rf->pFirstChunk = NULL;\n    if (rf->SizeofChunks != 0) {",
      "    if (rf->SizeofChunks != 0) {"),
    M("ctor_no_size", "    if (rf->SizeofChunks != 0) {\n        allocate_memory",
      "    if (rf->SizeofChunks > 16) {\n        allocate_memory"),
    M("ctor_top", "allocate_memory(rf, rf->Flags & RESOURCE_FILE_FLAG_LZCOMPRESSED);",
      "allocate_memory(rf, 0);"),
    M("ctor_xfer", "        rf->FileTransfersInProgress++;\n", ""),
    M("ctor_prio", "            RF_PRIORITY, RF_BLOCK_SIZE);",
      "            RF_PRIORITY + 1, RF_BLOCK_SIZE);"),
    M("ctor_block", "#define RF_BLOCK_SIZE     0x02000000",
      "#define RF_BLOCK_SIZE     0x00100000"),
    M("ctor_pos", "add_queued_file(rf->pFirstChunk, rf->Filename, 0,",
      "add_queued_file(rf->pFirstChunk, rf->Filename, 1,"),
    M("ctor_qparam", "                            (intptr_t)rf),",
      "                            (intptr_t)0),"),
    M("alloc_temp", "? 72 : 64;", "? 64 : 64;"),
    M("alloc_temp_bit", "(rf->Flags & RESOURCE_FILE_FLAG_USE_TEMPORARY_MEMORY) ? 72",
      "(rf->Flags & RESOURCE_FILE_FLAG_FREE_AFTER_LOADING) ? 72"),
    M("alloc_top", "        pool |= 8;", "        pool |= 0;"),
    M("alloc_name", "bMalloc(rf->SizeofChunks, rf->Filename, 0,",
      "bMalloc(rf->SizeofChunks, \"x\", 0,"),
    M("ftcb", "FileTransfersInProgress--;",
      "FileTransfersInProgress -= error + 1;"),
    # The destructor.
    M("dtor_wait", "        gEWaitUntilRenderingDoneFn();\n", "        ;\n"),
    M("dtor_hent_free", "        bFree(rf->pLoadedHotFileEntries);\n", ""),
    M("dtor_hnum", "        rf->NumLoadedHotFileEntries = 0;\n        rf->pLoaded",
      "        rf->pLoaded"),
    M("dtor_hot_count", "        HotChunkFilesNeedUpdating++;\n", ""),
    M("dtor_unload", "unload_chunks(rf->pFirstChunk, rf->SizeofChunks);",
      "unload_chunks(rf->pFirstChunk, 0);"),
    M("dtor_order",
      "        unload_chunks(rf->pFirstChunk, rf->SizeofChunks);\n"
      "        bFree(rf->pFirstChunk);\n",
      "        bFree(rf->pFirstChunk);\n"
      "        unload_chunks(rf->pFirstChunk, rf->SizeofChunks);\n"),
    M("dtor_fixup", "        post_load_fixup();\n    }\n    bFree(rf);",
      "    }\n    bFree(rf);"),
    M("dtor_free_rf", "    }\n    bFree(rf);\n}", "    }\n}"),
    # LoadResourceIfFileTransferFinished.
    M("lif_guard_xfer", "|| rf->FileTransfersInProgress != 0)",
      "|| rf->FileTransfersInProgress > 1)"),
    M("lif_guard_done", "if (rf->LoadingFinishedFlag || rf->FileTransfersInProgress",
      "if (rf->FileTransfersInProgress"),
    M("lz_flag", "    if (rf->Flags & RESOURCE_FILE_FLAG_LZCOMPRESSED) {",
      "    if (rf->Flags & RESOURCE_FILE_FLAG_FREE_AFTER_LOADING) {"),
    M("lz_magic", "if (packed != NULL && bchunk_u32(packed) == COMP_MAGIC)",
      "if (packed != NULL)"),
    M("lz_null", "if (packed != NULL && bchunk_u32(packed) == COMP_MAGIC)",
      "if (packed == NULL || bchunk_u32(packed) == COMP_MAGIC)"),
    M("lz_size_src", "(int32_t)bchunk_u32(packed + 8);",
      "(int32_t)bchunk_u32(packed + 12);"),
    M("lz_clear", "            rf->pFirstChunk = NULL;\n            rf->SizeofChunks",
      "            rf->SizeofChunks"),
    M("lz_zero", "            if (rf->SizeofChunks != 0) {\n                allocate_memory(rf, 0);",
      "            if (1) {\n                allocate_memory(rf, 0);"),
    M("lz_alloc_top", "                allocate_memory(rf, 0);",
      "                allocate_memory(rf, 1);"),
    M("lz_free_packed", "            bFree(packed);\n", ""),
    M("lc_args", "    load_chunks(rf->pFirstChunk, rf->SizeofChunks);",
      "    load_chunks(rf->pFirstChunk, rf->SizeofChunks - 4);"),
    M("fal_flag", "    if (rf->Flags & RESOURCE_FILE_FLAG_FREE_AFTER_LOADING) {\n        if",
      "    if (rf->Flags & RESOURCE_FILE_FLAG_USE_TEMPORARY_MEMORY) {\n        if"),
    M("fal_free", "        if (rf->pFirstChunk != NULL)\n            bFree(rf->pFirstChunk);\n",
      ""),
    M("fal_ptr", "        rf->pFirstChunk = NULL;\n        rf->SizeofChunks = 0;",
      "        rf->SizeofChunks = 0;"),
    M("fal_size", "        rf->SizeofChunks = 0;\n    }\n    post_load_fixup();",
      "    }\n    post_load_fixup();"),
    M("lif_fixup", "    post_load_fixup();\n    rf->LoadingFinishedFlag = 1;",
      "    rf->LoadingFinishedFlag = 1;"),
    M("lif_done", "    rf->LoadingFinishedFlag = 1;", "    rf->LoadingFinishedFlag = 2;"),
    # The list, the loads and the service.
    M("sinit", "    ResourceFileList.prev = &ResourceFileList;\n    ResourceFileList.next",
      "    ResourceFileList.next"),
    M("sdtor", "        unlink_file(rf);\n        delete_file(rf);\n",
      "        unlink_file(rf);\n"),
    M("load_count", "    NumResourcesBeingLoaded++;\n", ""),
    M("load_pool", "\"ResourceFile\", 0, 16)", "\"ResourceFile\", 0, 0)"),
    M("load_prev", "    rf->Node.prev = last;", "    rf->Node.prev = &ResourceFileList;"),
    M("load_head", "    last = ResourceFileList.prev;", "    last = &ResourceFileList;"),
    M("hot_flag", "    int32_t flags = hot_chunkable != 0;",
      "    int32_t flags = hot_chunkable;"),
    M("hot_keep", "    if (!keep)", "    if (keep)"),
    M("hot_bits", "        flags |= RESOURCE_FILE_FLAG_USE_TEMPORARY_MEMORY\n",
      "        flags |= 0\n"),
    M("rename_n", "b_strncpy(rf->Filename, name, 79);",
      "b_strncpy(rf->Filename, name, 80);"),
    M("rename_term", "    for (i = 0; i < n; i++) {\n        dst[i] = src[i];",
      "    for (i = 0; i < n && src[i] != '\\0'; i++) {\n        dst[i] = src[i];"),
    M("unload_wait", "    while (!rf->LoadingFinishedFlag)",
      "    if (!rf->LoadingFinishedFlag)"),
    M("unload_unlink", "    unlink_file(rf);\n    delete_file(rf);\n}",
      "    delete_file(rf);\n}"),
    M("srl_service", "    service_queued_files();\n    if (NumResourcesBeingLoaded == 0)",
      "    if (NumResourcesBeingLoaded == 0)"),
    M("srl_zero", "    if (NumResourcesBeingLoaded == 0)\n        return 0;\n", ""),
    M("srl_skip_done", "        if (rf->LoadingFinishedFlag)\n            continue;\n", ""),
    M("srl_wait_next",
      "            return NumResourcesBeingLoaded;\n        NumResourcesBeingLoaded--;",
      "            continue;\n        NumResourcesBeingLoaded--;"),
    M("srl_dec", "        NumResourcesBeingLoaded--;\n", ""),
    M("srl_cbnull", "        if (rf->Callback != NULL)\n            rf->Callback",
      "        if (1)\n            rf->Callback"),
    M("srl_cbparam", "rf->Callback(rf->CallbackParam);", "rf->Callback(0);"),
    M("srl_one", "        return NumResourcesBeingLoaded;\n    }\n    return 0;",
      "    }\n    return NumResourcesBeingLoaded;"),
    M("srl_end", "    }\n    return 0;\n}\n\nint32_t is_resource",
      "    }\n    return NumResourcesBeingLoaded;\n}\n\nint32_t is_resource"),
    M("rc", "    return NumResourcesBeingLoaded == 0;",
      "    return NumResourcesBeingLoaded != 0;"),
    M("fn_dir",
      "    for (n = ResourceFileList.prev; n != &ResourceFileList; n = n->prev) {\n"
      "        if (strcmp(",
      "    for (n = ResourceFileList.next; n != &ResourceFileList; n = n->next) {\n"
      "        if (strcmp("),
    M("fn_cmp", "strcmp(((ResourceFile *)n)->Filename, name) == 0",
      "strncmp(((ResourceFile *)n)->Filename, name, 4) == 0"),
    M("ft_dir",
      "    for (n = ResourceFileList.prev; n != &ResourceFileList; n = n->prev) {\n"
      "        if (((ResourceFile *)n)->Type == type)",
      "    for (n = ResourceFileList.next; n != &ResourceFileList; n = n->next) {\n"
      "        if (((ResourceFile *)n)->Type == type)"),
    M("ft_cmp", "        if (((ResourceFile *)n)->Type == type)",
      "        if (((ResourceFile *)n)->Type >= type)"),
    M("gs_id0", "            if (id == 0 || bchunk_u32(c) == id) {",
      "            if (bchunk_u32(c) == id) {"),
    M("gs_id", "            if (id == 0 || bchunk_u32(c) == id) {",
      "            if (id == 0 || bchunk_u32(c) == (id & 0xffff)) {"),
    M("gs_step", "            c += size + 8;", "            c += size + 16;"),
    M("gs_total", "                total += (int32_t)size;",
      "                total += (int32_t)size + 8;"),
    M("gs_n", "                n++;\n", ""),
    M("gs_count", "        *count = n;", "        *count = total;"),
    M("gs_count_null", "    if (count != NULL)\n        *count = n;", "    *count = n;"),
    M("gt_type", "        if (rf->Type != type)\n            continue;\n", ""),
    M("gt_count", "        chunks += k;", "        chunks = k;"),
    M("gt_total", "        total += resource_file_get_size(rf, id, &k);",
      "        total = resource_file_get_size(rf, id, &k);"),
    M("gt_id", "resource_file_get_size(rf, id, &k);",
      "resource_file_get_size(rf, 0, &k);"),
    M("gt_count_out", "        *count = chunks;", "        *count = total;"),
    # QueuedFile.
    M("qf_block", "#define QF_BLOCK_SIZE     0x00100000",
      "#define QF_BLOCK_SIZE     0x00080000", QF),
    M("qf_prio", "#define QF_PRIORITY       5", "#define QF_PRIORITY       6", QF),
    M("qf_handle_max", "#define QF_HANDLE_MAX     100000",
      "#define QF_HANDLE_MAX     99999", QF),
    M("qf_handle_wrap", "next > QF_HANDLE_MAX ? 1 : next;",
      "next > QF_HANDLE_MAX ? 0 : next;", QF),
    M("qf_handle_ge", "next > QF_HANDLE_MAX ? 1", "next >= QF_HANDLE_MAX ? 1", QF),
    M("qf_handle_init", "int32_t QueuedFile_CurrentHandle = 1;",
      "int32_t QueuedFile_CurrentHandle = 2;", QF),
    M("qf_status_bits", "#define QF_STATUS_BITS    4", "#define QF_STATUS_BITS    3", QF),
    M("qf_channel", "#define JOYLOG_CHANNEL_QUEUEDFILE_STATUS 5",
      "#define JOYLOG_CHANNEL_QUEUEDFILE_STATUS 4", QF),
    M("qctor_numread", "    qf->NumRead = 0;\n", "", QF),
    M("qctor_pos", "    qf->FilePos = pos;", "    qf->FilePos = 0;", QF),
    M("qctor_bytes", "    qf->NumBytes = num_bytes;", "    qf->NumBytes = num_bytes & ~3;",
      QF),
    M("qctor_name", "copy_name(qf->Filename, sizeof qf->Filename, name);",
      "copy_name(qf->Filename, 6, name);", QF),
    M("qctor_abort", "    qf->AbortFlag = 0;\n", "", QF),
    M("qctor_status", "    qf->Status = QF_WAITING;\n    return qf;",
      "    qf->Status = QF_READING;\n    return qf;", QF),
    M("qctor_cb", "    qf->Callback = cb;", "    qf->Callback = NULL;", QF),
    M("qctor_param", "    qf->CallbackParam = param;", "    qf->CallbackParam = 0;", QF),
    M("qctor_buf", "    qf->pBuf = buf;", "    qf->pBuf = (uint8_t *)buf + 1;", QF),
    M("rdcb", "->Status = QF_DONE;", "->Status = QF_ERROR;", QF),
    M("sort_strict",
      "    return !(((QueuedFile *)b)->Priority < ((QueuedFile *)a)->Priority);",
      "    return ((QueuedFile *)a)->Priority < ((QueuedFile *)b)->Priority;", QF),
    M("sort_dir",
      "    return !(((QueuedFile *)b)->Priority < ((QueuedFile *)a)->Priority);",
      "    return !(((QueuedFile *)a)->Priority < ((QueuedFile *)b)->Priority);",
      QF),
    M("br_null", "        qf->Status = QF_ERROR;\n        return;",
      "        qf->Status = QF_WAITING;\n        return;", QF),
    M("br_min", "    if (qf->BlockSize < n)", "    if (qf->BlockSize > n)", QF),
    M("br_size", "if (bFileSize(f) < qf->FilePos + qf->NumRead + n) {",
      "if (bFileSize(f) <= qf->FilePos + qf->NumRead + n) {", QF),
    M("br_size_noread", "if (bFileSize(f) < qf->FilePos + qf->NumRead + n) {",
      "if (bFileSize(f) < qf->FilePos + n) {", QF),
    M("br_size_err", "        qf->Status = QF_ERROR;\n    } else {",
      "        qf->Status = QF_DONE;\n    } else {", QF),
    M("br_reading", "        qf->Status = QF_READING;", "        qf->Status = QF_WAITING;", QF),
    M("br_seek", "bSeek(f, qf->FilePos + qf->NumRead, 0);",
      "bSeek(f, qf->FilePos, 0);", QF),
    M("br_buf", "(uint8_t *)qf->pBuf + qf->NumRead, n,", "qf->pBuf, n,", QF),
    M("br_numread", "        qf->NumRead += n;", "        qf->NumRead = n;", QF),
    M("br_close", "    }\n    bClose(f);\n}", "    }\n}", QF),
    M("br_close_err", "        qf->NumRead += n;\n    }\n    bClose(f);",
      "        qf->NumRead += n;\n        bClose(f);\n    }", QF),
    M("qsinit", "    QueuedFileList.prev = &QueuedFileList;\n    QueuedFileList.next",
      "    QueuedFileList.next", QF),
    M("qsdtor", "        unlink_file(qf);\n        delete_file(qf);\n    }\n}",
      "        unlink_file(qf);\n    }\n}", QF),
    M("init_pool", "bNewSlotPool(100, 16, \"QueuedFileSlotPool\", 16)",
      "bNewSlotPool(100, 16, \"QueuedFileSlotPool\", 0)", QF),
    M("close_pool", "        bDeleteSlotPool(QueuedFileSlotPool);", "        ;", QF),
    M("add_prev", "    qf->Node.prev = last;", "    qf->Node.prev = &QueuedFileList;", QF),
    M("add_ret", "    return qf->Handle;", "    return qf->Handle + 1;", QF),
    M("change_swap",
      "        qf->BlockSize = block_size;\n        qf->Priority = priority;",
      "        qf->BlockSize = priority;\n        qf->Priority = block_size;", QF),
    M("abort_none", "    if (qf == NULL)\n        return 1;",
      "    if (qf == NULL)\n        return 0;", QF),
    M("abort_wait", "    if (qf->Status == QF_WAITING) {",
      "    if (qf->Status != QF_READING) {", QF),
    M("abort_ret", "        delete_file(qf);\n        return 1;",
      "        delete_file(qf);\n        return 0;", QF),
    M("abort_flag", "    qf->AbortFlag = 1;\n    return 0;",
      "    qf->AbortFlag = 0;\n    return 0;", QF),
    M("find_cmp", "->Handle == handle)", "->Handle >= handle)", QF),
    M("sqf_fs", "    bServiceFileSystem();\n    if (QueuedFileReadInProgress) {",
      "    if (QueuedFileReadInProgress) {", QF),
    M("sqf_replay", "        if (Joylog_ReplayingFlag) {", "        if (0) {", QF),
    M("sqf_wait_cond",
      "if (status != QF_READING && qf->Status == QF_READING) {",
      "if (status == QF_DONE && qf->Status == QF_READING) {", QF),
    M("sqf_wait_own",
      "if (status != QF_READING && qf->Status == QF_READING) {",
      "if (status != QF_READING) {", QF),
    M("sqf_wait_loop",
      "                do\n                    bServiceFileSystem();\n"
      "                while (qf->Status == QF_READING);",
      "                bServiceFileSystem();", QF),
    M("sqf_record", "            Joylog_AddData(status, QF_STATUS_BITS,",
      "            Joylog_AddData(0, QF_STATUS_BITS,", QF),
    M("sqf_done_status", "            QueuedFileReadInProgress = 0;\n"
      "            qf->Status = QF_WAITING;\n",
      "            QueuedFileReadInProgress = 0;\n", QF),
    M("sqf_done_flag", "            QueuedFileReadInProgress = 0;\n"
      "            qf->Status = QF_WAITING;\n",
      "            qf->Status = QF_WAITING;\n", QF),
    M("sqf_abort", "            if (qf->AbortFlag) {", "            if (0) {", QF),
    M("sqf_abort_free", "            if (qf->AbortFlag) {\n                unlink_file(qf);\n"
      "                delete_file(qf);\n",
      "            if (qf->AbortFlag) {\n                unlink_file(qf);\n", QF),
    M("sqf_complete", "} else if (qf->NumRead == qf->NumBytes) {",
      "} else if (qf->NumRead != qf->NumBytes) {", QF),
    M("sqf_cbnull", "                if (qf->Callback != NULL)\n",
      "                if (1)\n", QF),
    M("sqf_cb0", "qf->Callback(qf->CallbackParam, 0);",
      "qf->Callback(qf->CallbackParam, 1);", QF),
    M("sqf_delete_first",
      "                unlink_file(qf);\n                if (qf->Callback != NULL)\n"
      "                    qf->Callback(qf->CallbackParam, 0);\n"
      "                delete_file(qf);\n",
      "                unlink_file(qf);\n                delete_file(qf);\n"
      "                if (qf->Callback != NULL)\n"
      "                    qf->Callback(qf->CallbackParam, 0);\n", QF),
    M("sqf_err", "        } else if (status == QF_ERROR) {",
      "        } else if (status == QF_WAITING) {", QF),
    M("sqf_err_cb", "qf->Callback(qf->CallbackParam, 1);",
      "qf->Callback(qf->CallbackParam, 0);", QF),
    M("sqf_err_flag", "            unlink_file(qf);\n            QueuedFileReadInProgress = 0;\n",
      "            unlink_file(qf);\n", QF),
    M("sqf_err_free", "                qf->Callback(qf->CallbackParam, 1);\n"
      "            delete_file(qf);\n",
      "                qf->Callback(qf->CallbackParam, 1);\n", QF),
    M("sqf_return", "        if (QueuedFileReadInProgress)\n            return;\n", "", QF),
    M("sqf_start_flag", "        QueuedFileReadInProgress = 1;\n", "", QF),
    M("sqf_sort", "        blist_sort(&QueuedFileList, sort_by_priority);\n", "", QF),
    M("sqf_empty", "    if (QueuedFileList.next != &QueuedFileList) {",
      "    if (QueuedFileList.next != &QueuedFileList\n"
      "        && QueuedFileList.next->next != &QueuedFileList) {", QF),
]

EQUIVALENT = {
    "lif_guard_done":
        "only ServiceResourceLoading calls it, and only for a file that is "
        "not loaded yet",
    "dtor_hnum":
        "the destructor frees the record straight after, and nothing reads "
        "a freed ResourceFile",
}


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
