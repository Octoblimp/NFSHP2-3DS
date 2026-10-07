"""Cross-check 3DS Files/source/cameracoord.c against the retail image's own
code.

CameraCoordinator.obj, in part: the coordinators' base and their list,
TheCameraLoader and the camera chunks it keeps, the CameraDataItems parser
and CountdownCameraCoordinator. The oracle is SLES_507.31 itself, run in
tools/mipsemu.py:

- the list's static constructor (0x0019c058) and CameraLoader's own
  (0x00199c80); LoaderCameras and UnloaderCameras (0x0019a398, 0x0019a3c0)
  and under them the loader's Loader and Unloader (0x00199cd8, 0x0019a010);
  FindRandomCameraShake (0x0019a1b8), FindCameraData (0x0019a280) and the
  NIS keeper (0x0019a3e8); CameraDataItems(char*) (0x0019b6b0);
- BaseCameraCoordinator's constructor (0x00199a98) and destructor
  (0x00199ad8), Disable (0x00199b48), Enable (0x00199b90),
  UpdateCameraCoordinators (0x00199bd0) and
  MarkCameraDataAsNeedingToBeReloaded (0x00199c40);
- CountdownCameraCoordinator's constructor (0x0019b130), destructor
  (0x0019b188) and Update (0x0019b1a0), and the two tables (0x002b52f8,
  0x002b5298) the destructor slots and Update are called through;
- run as shipped under them: bSPrintf, bStrICmp, bRandom over bDefaultSeed
  and bNode's destructor (0x00114e70).

Stood in on both sides, each call printing a line:
  Race::GetCountdownNumberToDisplay (0x001480c0), answering the script's
    number;
  BumperCameraMover's constructor (0x00158800), which prints its memory,
    view and car and what the parser set of its CameraDataItems, and gives
    the mover a test table;
  a test CameraMover table (vptr at +40) whose deleting destructor (8),
    Enable (96) and Disable (104) print, and a test coordinator table
    (FCVT) whose destructor (8) and Update (16) print;
  bMalloc (0x002577c0) and the frees (bFree 0x00257850, __builtin_delete
    0x00114e98): a block filled with 0xcd, named h0, h1, ...

The chunks are the retail disc's -- INGAMEB's pre-race, post-race and
shake chunks, TRACKB's highlights and fly-bys, the eight NIS .CAM files --
and built ones for the edges, all in one arena at the same offsets on both
sides. TheCameraLoader is dumped list by list, the coordinators field by
field.

    python tools/cameracoord_check.py
    python tools/cameracoord_check.py --mutate [--only a,b] [--jobs N]
    python tools/cameracoord_check.py --dump PREFIX
"""
import argparse
import os
import random
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import mutpar
import physicscar_check as pcc
import retail_model
from mipsemu import M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)
DISC = ROOT / "extracted-retail"

HARNESS = "tools/src/cameracoord_test.c"
CC = "3DS Files/source/cameracoord.c"
SOURCES = [HARNESS, CC,
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c",
           "3DS Files/source/bmem.c",
           "3DS Files/source/bprintf.c",
           "3DS Files/source/vtable.c"]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = retail_model.RETAIL_GP

SINIT = 0x0019c058
INITL = 0x00199c80
LOADER_CAMERAS = 0x0019a398
UNLOADER_CAMERAS = 0x0019a3c0
SHAKE = 0x0019a1b8
FIND = 0x0019a280
KEEP = 0x0019a3e8
PARSE = 0x0019b6b0
CC_CTOR = 0x00199a98
CC_DTOR = 0x00199ad8
CC_DISABLE = 0x00199b48
CC_ENABLE = 0x00199b90
CC_UPDATE_ALL = 0x00199bd0
CC_MARK = 0x00199c40
CD_CTOR = 0x0019b130
CD_DTOR = 0x0019b188
CD_UPDATE = 0x0019b1a0
BASE_VT = 0x002b52f8
CD_VT = 0x002b5298

COUNTDOWN = 0x001480c0
BUMPER = 0x00158800
BMALLOC = 0x002577c0
BFREE = 0x00257850
BDELETE = 0x00114e98

LOADER = 0x00310370                 # TheCameraLoader
LOADER_SIZE = 2596
LIST = GP - 19920                   # CameraCoordinatorList
RACE_GP = -22272                    # pCurrentRace
SEED_GP = -14472                    # bDefaultSeed

# The world.
ARENA = 0x01000000
ARENA_SIZE = 4 << 20
NEAR = 0x100000
KS = 0x01E00000                     # k0..k7, 0x100 apart
NK = 8
MOVERS = 0x01E01000                 # m0..m3
NMOVERS = 4
PLAYERS = 0x01E02000                # p0, p1: MyCar at +4
CARS = 0x01E03000                   # car0, car1
RACE = 0x01E04000
FMVT = 0x01E05000                   # the test mover table
FMVT_DTOR = 0x01E05800
FMVT_ENABLE = 0x01E05810
FMVT_DISABLE = 0x01E05820
CD = 0x01E06000                     # OP_PARSE's CameraDataItems
FCVT = 0x01e0b000                   # the test coordinator table
FCVT_DTOR = 0x01E0B800
FCVT_UPDATE = 0x01E0B810
SLACK = 16

(OP_TAG, OP_PUT, OP_JUNKL, OP_INITL, OP_SINIT, OP_LOAD, OP_UNLOAD,
 OP_DUMPL, OP_POKEL, OP_POKEP, OP_SEED, OP_SHAKE, OP_FIND, OP_KEEP,
 OP_PARSE, OP_CCNEW, OP_CDNEW, OP_CCDEL, OP_CCDELETE, OP_RAWDTOR,
 OP_DISABLE, OP_ENABLE, OP_MARK, OP_UPDATE, OP_CDUPDATE, OP_SETMOVER,
 OP_SETF, OP_CD, OP_JUNKK, OP_DUMPK) = range(30)

ARGS = {OP_TAG: 1, OP_JUNKL: 1, OP_INITL: 0, OP_SINIT: 0, OP_LOAD: 1,
        OP_UNLOAD: 1, OP_DUMPL: 0, OP_POKEL: 2, OP_POKEP: 3, OP_SEED: 1,
        OP_SHAKE: 1, OP_FIND: 1, OP_KEEP: 1, OP_PARSE: 2, OP_CCNEW: 2,
        OP_CDNEW: 3, OP_CCDEL: 2, OP_CCDELETE: 1, OP_RAWDTOR: 3,
        OP_DISABLE: 1, OP_ENABLE: 1, OP_MARK: 0, OP_UPDATE: 1,
        OP_CDUPDATE: 2, OP_SETMOVER: 2, OP_SETF: 3, OP_CD: 1, OP_JUNKK: 2,
        OP_DUMPK: 0}

# OP_POKEL's fields, OP_POKEP's lists and OP_SETF's fields.
(L_HL, L_FB, L_PRE, L_POST, L_NIS, L_PN0, L_PN1, L_SHAKES,
 L_SHAKEP) = range(9)
LIST_HL, LIST_FB, LIST_PRE, LIST_POST, LIST_NIS, LIST_PN0, LIST_PN1 = range(7)
F_DISABLED, F_VIEW, F_NEED, F_NUMBER, F_VPTR, F_PLAYER = range(6)

# TheCameraLoader: each list's count and its pointers, retail's offsets.
LISTS = (("hl", 0, 4, 512), ("fb", 2052, 2056, 32), ("pre", 2184, 2188, 32),
         ("post", 2316, 2320, 32), ("nis", 2448, 2452, 8),
         ("pn0", 2484, 2492, 8), ("pn1", 2488, 2524, 8))
POKEL_OFF = (0, 2052, 2184, 2316, 2448, 2484, 2488, 2556, 2560)
SHAKES_N, SHAKES_P, VORTEX, VORTEX_N = 2556, 2560, 2576, 2592

# The chunks.
HIGHLIGHTS, PRE_RACE, POST_RACE = 0x80034405, 0x80034410, 0x80034415
NIS, FLY_BY, SHAKES = 0x80034420, 0x80034425, 0x00034492
VORTEX_C, HIGHLIGHT_C, PRE_C, POST_C = 0x34440, 0x34450, 0x34460, 0x34470
NIS_C, FLY_BY_C = 0x34480, 0x34490

# The retail chunks: file, offset, type.
INGAMEB = ("GLOBAL/INGAMEB.BUN", ((0x1d8500, PRE_RACE),
                                  (0x1da280, POST_RACE),
                                  (0x1e2f80, SHAKES)))
TRACKS = (("TRACKB11.BUN", 0x874c80, 0x890880),
          ("TRACKB13.BUN", 0x933f80, 0x966600),
          ("TRACKB23.BUN", 0xa53e00, 0xa97980),
          ("TRACKB32.BUN", 0x6cad00, 0x715f80),
          ("TRACKB43.BUN", 0x993100, 0x9d8300),
          ("TRACKB63.BUN", 0x9d4b80, 0xa29780))
FLY_BYS = (("TRACKB12.BUN", 0x88db80), ("TRACKB21.BUN", 0x964100),
           ("TRACKB22.BUN", 0x99cf80), ("TRACKB31.BUN", 0x723980),
           ("TRACKB33.BUN", 0x7caf00), ("TRACKB41.BUN", 0x9fbe80),
           ("TRACKB42.BUN", 0x9a4680), ("TRACKB61.BUN", 0xa19c80),
           ("TRACKB62.BUN", 0xa4b480))
NIS_FILES = ("NIS_ARREST01.CAM", "NIS_ARREST02.CAM", "NIS_ARREST03.CAM",
             "NIS_TICKET01.CAM", "NIS_TICKET02.CAM", "NIS_TICKET03.CAM",
             "NIS_TICKET04.CAM", "NIS_TICKET06.CAM")

# CameraDataItems, 164 bytes: (offset, is a pointer), in the dump's order.
CD_FIELDS = ((0, 0), (4, 1), (8, 0), (12, 0), (16, 0), (20, 0), (24, 0),
             (28, 0), (32, 0), (36, 0), (40, 0), (44, 0), (48, 0), (52, 0),
             (56, 0), (60, 1), (64, 0), (68, 1), (72, 0), (76, 1), (80, 0),
             (84, 1), (88, 1), (92, 0), (96, 1), (100, 0), (104, 0),
             (108, 0), (112, 0), (116, 0), (120, 0), (124, 0), (128, 0),
             (132, 0), (136, 0), (140, 0), (144, 0), (148, 0), (152, 0),
             (156, 0), (160, 0))
# What only type 2 reads (FOVSplineSpeed), and only type 0 (the look
# offset, the enter and leave components, IsLeaveSet and the wipe).
CD_TYPE2_ONLY = (28,)
CD_TYPE0_ONLY = tuple(range(120, 160, 4))


def fb(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def fx(b):
    return "%08x" % (b & M32)


def u32s(b):
    b = bytes(b) + bytes(-len(b) % 4)
    return list(struct.unpack("<%dI" % (len(b) // 4), b))


def disc(path):
    return (DISC / path).read_bytes()


def chunk_at(d, off):
    size = struct.unpack_from("<I", d, off + 4)[0]
    return d[off:off + 8 + size]


def children(ch, base):
    """(type, header offset, size, payload offset) of each child of the
    container `ch` placed at arena offset `base`."""
    out = []
    end = 8 + struct.unpack_from("<I", ch, 4)[0]
    o = 8
    while o < end:
        t, s = struct.unpack_from("<II", ch, o)
        a = base + o
        out.append((t, a, s, (a + 23) & ~15))
        o += 8 + s
    return out


def build(base, cid, kids):
    """A container at arena offset `base`: each kid is (type, data), its
    data placed where the loader will look for it, or (type, raw, None),
    its bytes as they are."""
    body = bytearray()
    for k in kids:
        if len(k) == 3:
            t, raw, _ = k
            body += struct.pack("<II", t, len(raw)) + raw
            continue
        t, data = k
        hdr = base + 8 + len(body)
        pad = ((hdr + 23) & ~15) - (hdr + 8)
        body += struct.pack("<II", t, pad + len(data)) + bytes(pad) + data
    return struct.pack("<II", cid, len(body)) + bytes(body)


def cam(typ, name, words):
    """A camera's block: its type, its 32-byte name and the words after."""
    nb = name.encode("latin-1") if isinstance(name, str) else name
    nb = (nb + bytes(32))[:32]
    return struct.pack("<i", typ) + nb + struct.pack(
        "<%dI" % len(words), *[w & M32 for w in words])


# Where each type keeps its three or four counts among the words after the
# name: NumAreaVerts, NumAreaFaces, NumEyeVerts (and NumLookVerts).
COUNT_AT = {0: (20, 21, 22), 1: (9, 10, 11, 12), 2: (10, 11, 12, 13)}


def cam_words(rnd, typ, counts=None, n=48):
    words = [rnd.getrandbits(32) for _ in range(n)]
    for i, c in zip(COUNT_AT.get(typ, ()), counts or ()):
        words[i] = c & M32
    return words


# ================================================================ the script

class Script(object):
    def __init__(self):
        self.ops = []
        self.tags = []

    def op(self, code, *args):
        assert len(args) == ARGS[code], (code, args)
        self.ops.append((code,) + tuple(int(a) & M32 for a in args))

    def tag(self, s):
        self.tags.append(s)
        self.op(OP_TAG, len(self.tags) - 1)

    def put(self, off, data):
        data = bytes(data)
        assert 0 <= off and off + len(data) <= ARENA_SIZE, off
        self.ops.append((OP_PUT, off, len(data)) + tuple(u32s(data)))

    def find(self, name):
        self.tags.append(name)
        self.op(OP_FIND, len(self.tags) - 1)

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

    def load(self, off, data=None):
        if data is not None:
            self.put(off, data)
        self.op(OP_LOAD, off)

    def parse_all(self, ch, base, fills=(0xa5,)):
        for i, (t, a, s, p) in enumerate(children(ch, base)):
            if t != VORTEX_C:
                self.op(OP_PARSE, p, fills[i % len(fills)])

    def fresh(self, junk=0xa5):
        self.op(OP_JUNKL, junk)
        self.op(OP_INITL)

    def setf(self, k, f, v):
        self.op(OP_SETF, k, f, v)


def retail_scenarios(sc):
    if not DISC.exists():
        print("  (no %s -- the disc scenarios are skipped)" % DISC)
        return

    ing = disc(INGAMEB[0])
    pre = chunk_at(ing, 0x1d8500)
    post = chunk_at(ing, 0x1da280)
    shakes = chunk_at(ing, 0x1e2f80)

    sc.tag("ingameb")
    sc.fresh()
    sc.op(OP_DUMPL)
    sc.load(0x0000, pre)
    sc.load(0x8000, post)
    sc.load(0x20000, shakes)
    sc.op(OP_DUMPL)
    sc.parse_all(pre, 0x0000, (0xa5, 0x00))
    sc.parse_all(post, 0x8000, (0x00, 0x5c))
    for name in ("Cam_01", "cam_04", "CAM_11", "Cam_12", "Cam_0", "Cam_011",
                 "", "PreRace_01"):
        sc.find(name)
    # The shakes' banks, each seed a few draws on.
    sc.op(OP_SEED, 0x12345678)
    for bank in (0, 1, 2, 3, 4, 5, 6, -1, 1, 1, 2, 2, 3, 3):
        sc.op(OP_SHAKE, bank)
    for seed in (0, 1, 0x7fffffff, 0x80000000, 0xffffffff, 0xdeadbeef):
        sc.op(OP_SEED, seed)
        for bank in (1, 2, 3, 4):
            sc.op(OP_SHAKE, bank)
    sc.op(OP_UNLOAD, 0x8000)
    sc.op(OP_DUMPL)
    sc.op(OP_UNLOAD, 0x0000)
    sc.op(OP_UNLOAD, 0x20000)
    sc.op(OP_DUMPL)
    sc.op(OP_SHAKE, 1)

    for i, (name, hl_off, fb_off) in enumerate(TRACKS):
        d = disc("TRACKS/" + name)
        hl = chunk_at(d, hl_off)
        fly = chunk_at(d, fb_off)
        sc.tag("track %s" % name)
        sc.fresh(0x00 if i & 1 else 0xa5)
        sc.load(0x40000, hl)
        sc.load(0x30000, fly)
        sc.load(0x0000, pre)
        sc.load(0x8000, post)
        sc.op(OP_DUMPL)
        if i in (0, 5):
            sc.parse_all(hl, 0x40000, (0xa5, 0x00, 0x5c))
        else:
            kids = children(hl, 0x40000)
            for t, a, s, p in kids[:3] + kids[-2:]:
                sc.op(OP_PARSE, p, 0xa5)
        sc.parse_all(fly, 0x30000)
        names = []
        for t, a, s, p in children(hl, 0x40000):
            if t == HIGHLIGHT_C:
                off = p - 0x40000 + 4
                names.append(hl[off:off + 32].split(b"\0")[0].decode(
                    "latin-1"))
        for n in (names[0], names[-1], names[len(names) // 2].lower(),
                  "PRERACE_01", "Cam_03", "COUNTDOWN_3"):
            sc.find(n)
        sc.op(OP_UNLOAD, 0x40000)
        sc.op(OP_UNLOAD, 0x30000)
        sc.op(OP_DUMPL)

    sc.tag("fly-bys")
    sc.fresh()
    for name, off in FLY_BYS:
        fly = chunk_at(disc("TRACKS/" + name), off)
        sc.load(0x30000, fly)
        sc.parse_all(fly, 0x30000, (0x00,))
        sc.op(OP_DUMPL)

    # The NIS cameras: two players' worth kept, the rest appended, each
    # file unloaded against the players' lists.
    nis = [chunk_at(disc("NIS/" + n), 0) for n in NIS_FILES]
    offs = [0x100000 + 0x10000 * i for i in range(len(nis))]
    for i, c in enumerate(nis):
        sc.put(offs[i], c)
    sc.tag("nis")
    sc.fresh()
    sc.op(OP_LOAD, offs[0])
    sc.op(OP_DUMPL)
    sc.op(OP_KEEP, 0)
    sc.op(OP_LOAD, offs[1])
    sc.op(OP_KEEP, 1)
    sc.op(OP_DUMPL)
    sc.parse_all(nis[1], offs[1], (0xa5, 0x00))
    sc.op(OP_UNLOAD, offs[2])
    sc.op(OP_UNLOAD, offs[0])
    sc.op(OP_DUMPL)
    sc.op(OP_UNLOAD, offs[1])
    sc.op(OP_DUMPL)
    sc.op(OP_UNLOAD, offs[1])
    sc.op(OP_DUMPL)
    # Two files appended, kept by one player, then by the other with the
    # count put back: every camera in both lists.
    sc.tag("nis, both players")
    sc.fresh()
    sc.op(OP_LOAD, offs[2])
    sc.op(OP_LOAD, offs[3])
    sc.op(OP_DUMPL)
    sc.op(OP_KEEP, 0)
    sc.op(OP_POKEL, L_NIS, 6)
    sc.op(OP_KEEP, 1)
    sc.op(OP_DUMPL)
    sc.op(OP_UNLOAD, offs[3])
    sc.op(OP_DUMPL)
    sc.op(OP_UNLOAD, offs[2])
    sc.op(OP_DUMPL)
    # The other six, each kept by player 0 over the last.
    sc.tag("nis, each file")
    sc.fresh()
    for i in range(2, len(nis)):
        sc.op(OP_LOAD, offs[i])
        sc.op(OP_KEEP, i & 1)
        sc.op(OP_DUMPL)
        sc.op(OP_UNLOAD, offs[i])
        sc.op(OP_UNLOAD, offs[i - 1])
        sc.op(OP_DUMPL)


def built_scenarios(sc, rnd):
    # -- the loader: every type, empty and odd ------------------------------
    sc.tag("empty containers")
    sc.fresh()
    for i, t in enumerate((HIGHLIGHTS, PRE_RACE, POST_RACE, NIS, FLY_BY,
                           SHAKES)):
        sc.load(0x1000 * i, build(0x1000 * i, t, []))
    sc.op(OP_DUMPL)

    sc.tag("other chunks")
    sc.fresh()
    for i, t in enumerate((0, 0x80034400, 0x80034492, 0x00034405,
                           0x80034426, 0x34460, 0xffffffff, 0x80034421)):
        sc.load(0x1000 * i, build(0x1000 * i, t, [(PRE_C, b"\1" * 40)]))
        sc.op(OP_UNLOAD, 0x1000 * i)
    sc.op(OP_DUMPL)

    # Each list's container, with children of every type, at every
    # alignment; the counts set high first to show the reset (or, for the
    # NIS list, the append).
    sc.tag("mixed children")
    for align in (0, 4, 8, 12):
        sc.fresh(0x5c)
        for f in (L_HL, L_FB, L_PRE, L_POST, L_NIS):
            sc.op(OP_POKEL, f, 3)
        for i, t in enumerate((HIGHLIGHTS, FLY_BY, PRE_RACE, POST_RACE,
                               NIS)):
            base = 0x10000 * (i + 1) + align
            kids = []
            for k in range(9):
                kt = (VORTEX_C, HIGHLIGHT_C, PRE_C, POST_C, NIS_C, FLY_BY_C,
                      0x34441, HIGHLIGHT_C | 0x80000000, 0)[(k * 5 + i) % 9]
                if kt == VORTEX_C:
                    data = struct.pack("<4fi", 1.5 + k, -2.25, 1e-30, 7.0,
                                       100 + k)
                else:
                    data = cam(k % 3, "c%d_%d" % (i, k),
                               cam_words(rnd, k % 3, (1, 2, 3, 4)))
                kids.append((kt, data))
            sc.load(base, build(base, t, kids))
        sc.op(OP_DUMPL)
        for i in range(5):
            sc.op(OP_UNLOAD, 0x10000 * (i + 1) + align)
        sc.op(OP_DUMPL)

    # Raw children: no room after the header, odd sizes, a vortex that
    # runs into the next child, two vortices.
    sc.tag("raw children")
    for align in (0, 8):
        sc.fresh()
        base = 0x60000 + align
        kids = [(HIGHLIGHT_C, b"", None), (HIGHLIGHT_C, b"\7" * 3, None),
                (VORTEX_C, struct.pack("<4f", 9.0, 8.0, 7.0, 6.0), None),
                (HIGHLIGHT_C, b"\x11" * 13, None),
                (VORTEX_C, struct.pack("<5I", 0x3f800000, 0x40000000,
                                       0x40400000, 0x40800000, 0xffffffff)),
                (HIGHLIGHT_C, b"\x22" * 1, None)]
        sc.load(base, build(base, HIGHLIGHTS, kids))
        sc.op(OP_DUMPL)
        base2 = 0x70000 + align
        sc.load(base2, build(base2, PRE_RACE,
                             [(PRE_C, b"", None), (PRE_C, b"\x33" * 5, None),
                              (POST_C, b"", None), (PRE_C, b"\x44" * 24,
                                                    None),
                              (PRE_C, b"", None)]))
        sc.op(OP_DUMPL)

    # The shakes' chunk: payload and size / 560, unsigned.
    sc.tag("shake sizes")
    sc.fresh()
    for i, size in enumerate((0, 559, 560, 561, 1119, 1120, 5048, 56000,
                              0x7fffffff, 0x80000000, 0xfffffff0,
                              0xffffffff)):
        base = 0x80000 + 0x100 * i + (i & 3) * 4
        sc.put(base, struct.pack("<II", SHAKES, size))
        sc.op(OP_LOAD, base)
        sc.op(OP_DUMPL)
    sc.op(OP_UNLOAD, base)
    sc.op(OP_DUMPL)

    # The coordinators marked by each load that is one of the six.
    sc.tag("loads mark")
    sc.op(OP_SINIT)
    for k in range(3):
        sc.op(OP_JUNKK, k, 0)
        sc.op(OP_CCNEW, k, k + 1)
    sc.setf(1, F_NEED, 7)
    sc.op(OP_DUMPK)
    for i, t in enumerate((HIGHLIGHTS, PRE_RACE, 0x1234, POST_RACE, NIS,
                           FLY_BY, SHAKES, 0)):
        for k in range(3):
            sc.setf(k, F_NEED, 0)
        base = 0x90000 + 0x1000 * i
        sc.load(base, build(base, t, []))
        sc.op(OP_DUMPK)
        sc.op(OP_UNLOAD, base)
        sc.op(OP_DUMPK)
    sc.op(OP_MARK)
    sc.op(OP_DUMPK)

    # -- the NIS unloader's lists ------------------------------------------
    sc.tag("nis unload")
    base = 0xa0000
    nis_kids = [(NIS_C, cam(1, "n%d" % k, cam_words(rnd, 1))) for k in
                range(4)] + [(PRE_C, b"\0" * 32)]
    nis_ch = build(base, NIS, nis_kids)
    sc.put(base, nis_ch)
    pays = [p for t, a, s, p in children(nis_ch, base)]
    for case in range(12):
        sc.fresh()
        sc.op(OP_POKEL, L_PN0, (0, 3, 8, 2, -1, 8, 1, 5, 0, 4, 8, 8)[case])
        sc.op(OP_POKEL, L_PN1, (0, 2, 0, 8, 8, -5, 7, 5, 4, 0, 8, 8)[case])
        for lst in (LIST_PN0, LIST_PN1):
            for idx in range(8):
                pick = (case * 7 + idx * 3 + lst) % 7
                sc.op(OP_POKEP, lst, idx,
                      pays[pick] if pick < 5 else (-1 if pick == 5
                                                   else base + 4))
        sc.op(OP_DUMPL)
        sc.op(OP_UNLOAD, base)
        sc.op(OP_DUMPL)
    # One camera found, in either list.
    for lst, f in ((LIST_PN0, L_PN0), (LIST_PN1, L_PN1)):
        sc.fresh()
        sc.op(OP_POKEL, f, 1)
        sc.op(OP_POKEP, lst, 0, pays[2])
        sc.op(OP_UNLOAD, base)
        sc.op(OP_DUMPL)

    # -- the keeper ----------------------------------------------------------
    sc.tag("keep")
    sc.fresh()
    sc.load(base, nis_ch)
    sc.op(OP_KEEP, 1)
    sc.op(OP_DUMPL)
    sc.op(OP_POKEL, L_NIS, -3)
    for idx in range(8):
        sc.op(OP_POKEP, LIST_NIS, idx, (base + 0x40 * idx) if idx & 1 else -1)
    sc.op(OP_KEEP, 0)
    sc.op(OP_DUMPL)
    sc.op(OP_KEEP, 0)
    sc.op(OP_DUMPL)

    # -- the parser ----------------------------------------------------------
    sc.tag("parse")
    p0 = 0x200000
    for typ in (0, 1, 2, 3, -1, 4, 0x7fffffff, -0x80000000, 0x100, 0x101):
        for counts in ((0, 0, 0, 0), (1, 2, 3, 4), (5, 0, 7, 1),
                       (-1, -2, -3, -4), (0x7fff, 0x1000, 0x2000, 0x3000),
                       (-0x2000, 0x10, -0x10, 0x7fff)):
            for fill in (0xa5, 0x00):
                blk = cam(typ, "cam %d" % typ, cam_words(rnd, typ, counts))
                off = p0 + rnd.randrange(64) * 4
                sc.put(off, blk)
                sc.op(OP_PARSE, off, fill)
    # A name with no end inside its 32 bytes.
    blk = cam(1, b"N" * 32, cam_words(rnd, 1, (1, 1, 1, 1)))
    sc.put(p0, blk)
    sc.op(OP_PARSE, p0, 0x5c)

    # -- FindCameraData --------------------------------------------------------
    sc.tag("find")
    sc.fresh()
    names = (("Alpha", "beta", "COUNTDOWN_3", "z{", "dup"),
             ("dup", "Fly", "Alpha2"),
             ("Cam_01", "DUP", "countdown_2"),
             ("post", "countdown_1", "Z["))
    for i, (t, ct, nm) in enumerate(((HIGHLIGHTS, HIGHLIGHT_C, names[0]),
                                     (FLY_BY, FLY_BY_C, names[1]),
                                     (PRE_RACE, PRE_C, names[2]),
                                     (POST_RACE, POST_C, names[3]))):
        b = 0xb0000 + 0x4000 * i
        sc.load(b, build(b, t, [(ct, cam(k % 3, n, cam_words(rnd, k % 3)))
                                for k, n in enumerate(nm)]))
    long_name = b"LongName" * 4
    b = 0xc0000
    sc.load(b, build(b, NIS, [(NIS_C, cam(1, "nisonly", cam_words(rnd, 1)))]))
    sc.op(OP_DUMPL)
    for n in ("alpha", "ALPHA", "Alpha2", "Alph", "Alpha ", "dup", "Dup",
              "beta", "BETA", "fly", "cam_01", "countdown_1", "COUNTDOWN_2",
              "countdown_3", "COUNTDOWN_4", "Z{", "z[", "z{", "post", "",
              "nisonly", "?"):
        sc.find(n)
    # A list's count put to 0 or below hides it.
    for f, v in ((L_HL, 0), (L_FB, -1), (L_PRE, 0), (L_POST, -7)):
        sc.op(OP_POKEL, f, v)
        sc.find("dup")
        sc.find("post")
    # A name that does not end in its 32 bytes.
    sc.op(OP_POKEL, L_POST, 1)
    blk = cam(2, long_name, [0x4f4c47] + cam_words(rnd, 2)[1:])
    b = 0xc8000
    sc.put(b, blk)
    sc.op(OP_POKEP, LIST_POST, 0, b)
    sc.find(long_name.decode())
    sc.find(long_name.decode() + "GLO")
    sc.find(long_name.decode() + "G")

    # -- FindRandomCameraShake ---------------------------------------------------
    sc.tag("shakes")
    sc.fresh()
    banks = (1, 2, 1, 3, 0, -1, 2, 1, 5, 1, 0x7fffffff, 1)
    b = 0xd0000
    for i, bank in enumerate(banks):
        sc.put(b + 560 * i + 32, struct.pack("<i", bank))
    sc.op(OP_POKEL, L_SHAKEP, b)
    for n in (0, len(banks), 5, -1, 1):
        sc.op(OP_POKEL, L_SHAKES, n)
        for seed in (0, 0x12345678, 0xffffffff):
            sc.op(OP_SEED, seed)
            for bank in (0, 1, 2, 3, 4, 5, -1, 0x7fffffff, -0x80000000, 1, 1):
                sc.op(OP_SHAKE, bank)
    sc.op(OP_POKEL, L_SHAKES, len(banks))
    sc.op(OP_SEED, 0x2468ace)
    for _ in range(60):
        sc.op(OP_SHAKE, rnd.choice((1, 1, 2, 3, 5, 9)))


def coordinator_scenarios(sc, rnd):
    sc.tag("static")
    sc.op(OP_JUNKL, 0xa5)
    sc.op(OP_SINIT)
    sc.op(OP_DUMPL)
    sc.op(OP_DUMPK)

    # -- the base's constructor and destructor -------------------------------
    sc.tag("base")
    sc.op(OP_SINIT)
    for k in range(5):
        sc.op(OP_JUNKK, k, 0xa5 if k & 1 else 0x00)
        sc.op(OP_CCNEW, k, (0, 1, -1, 0x7fffffff, 5)[k])
    sc.op(OP_DUMPK)
    sc.op(OP_CCDEL, 2, 0)
    sc.op(OP_DUMPK)
    sc.op(OP_CCDEL, 0, 1)
    sc.op(OP_DUMPK)
    sc.op(OP_SETMOVER, 4, 2)
    sc.op(OP_CCDELETE, 4)
    sc.op(OP_DUMPK)
    sc.op(OP_SETMOVER, 1, 3)
    sc.op(OP_CCDEL, 1, 2)
    sc.op(OP_DUMPK)
    sc.op(OP_CCDEL, 3, 3)
    sc.op(OP_DUMPK)

    # Called directly with either destructor, flags 0 to 3.
    sc.tag("raw destructors")
    for which in (0, 1):
        for flags in (0, 1, 2, 3, -1):
            sc.op(OP_SINIT)
            sc.op(OP_JUNKK, 0, 0)
            sc.op(OP_JUNKK, 1, 0)
            sc.op(OP_CCNEW, 0, 4)
            sc.op(OP_CCNEW, 1, 5)
            sc.setf(0, F_VPTR, FCVT)
            sc.op(OP_SETMOVER, 0, -1 if flags & 2 else 0)
            sc.op(OP_RAWDTOR, 0, flags, which)
            sc.op(OP_DUMPK)

    # -- Disable and Enable ----------------------------------------------------
    sc.tag("disable, enable")
    sc.op(OP_SINIT)
    sc.op(OP_JUNKK, 0, 0)
    sc.op(OP_CCNEW, 0, 0)
    for mover in (-1, 1):
        sc.op(OP_SETMOVER, 0, mover)
        for v in (0, 1, 2, -1, 0x100):
            sc.setf(0, F_DISABLED, v)
            sc.op(OP_DISABLE, 0)
            sc.op(OP_DUMPK)
            sc.setf(0, F_DISABLED, v)
            sc.op(OP_ENABLE, 0)
            sc.op(OP_DUMPK)
        for o in (OP_DISABLE, OP_DISABLE, OP_ENABLE, OP_ENABLE, OP_DISABLE):
            sc.op(o, 0)
        sc.op(OP_DUMPK)

    # -- Update and Mark over the list -----------------------------------------
    sc.tag("update")
    sc.op(OP_SINIT)
    sc.op(OP_UPDATE, fb(1.0 / 30))
    sc.op(OP_MARK)
    for k in range(6):
        sc.op(OP_JUNKK, k, 0)
        sc.op(OP_CCNEW, k, 10 + k)
        sc.setf(k, F_VPTR, FCVT)
    sc.setf(2, F_DISABLED, 1)
    sc.setf(4, F_DISABLED, -1)
    for dt in (1.0 / 30, 0.0, -0.0, 1e30, -2.5):
        sc.op(OP_UPDATE, fb(dt))
    sc.op(OP_UPDATE, 0x7fc00001)
    sc.op(OP_MARK)
    sc.op(OP_DUMPK)
    sc.op(OP_CCDEL, 3, 1)               # the test table's: still listed
    sc.op(OP_CCDELETE, 5)
    sc.op(OP_RAWDTOR, 3, 0, 0)
    sc.op(OP_UPDATE, fb(0.5))
    sc.op(OP_DUMPK)

    # -- the countdown -------------------------------------------------------
    def countdown_cams(sc, b):
        """COUNTDOWN_3 to _0 of types 1, 0, 2 and 7, and a decoy."""
        kids = [(PRE_C, cam(1, "COUNTDOWN_3",
                            cam_words(rnd, 1, (2, 3, 4, 5)))),
                (PRE_C, cam(0, "countdown_2",
                            cam_words(rnd, 0, (1, 0, 6)))),
                (PRE_C, cam(2, "Countdown_1",
                            cam_words(rnd, 2, (0, 1, 2, 3)))),
                (PRE_C, cam(7, "COUNTDOWN_0", cam_words(rnd, 7))),
                (PRE_C, cam(1, "COUNTDOWN_-1x", cam_words(rnd, 1))),
                (PRE_C, cam(1, "COUNTDOWN_-2147483648",
                            cam_words(rnd, 1, (9, 9, 9, 9))))]
        sc.load(b, build(b, PRE_RACE, kids))

    # Retail's disc: no camera named COUNTDOWN_n, so no mover.
    sc.tag("countdown, retail")
    sc.fresh()
    sc.op(OP_SINIT)
    sc.op(OP_JUNKK, 0, 0xa5)
    sc.op(OP_CD, 3)
    sc.op(OP_CDNEW, 0, 0, 0)
    sc.op(OP_DUMPK)
    for n in (3, 3, 2, 1, 0, -1, -1, 5):
        sc.op(OP_CD, n)
        sc.op(OP_UPDATE, fb(1.0 / 30))
    sc.op(OP_DUMPK)
    sc.op(OP_CCDELETE, 0)
    sc.op(OP_DUMPK)

    sc.tag("countdown, cameras")
    sc.fresh(0x00)
    sc.op(OP_SINIT)
    countdown_cams(sc, 0xe0000)
    for k in (0, 1):
        sc.op(OP_JUNKK, k, 0)
    sc.op(OP_CD, 3)
    sc.op(OP_CDNEW, 0, 2, 1)
    sc.op(OP_CD, -1)
    sc.op(OP_CDNEW, 1, -3, 0)
    sc.op(OP_DUMPK)
    for n in (3, 2, 2, 1, 0, -1, 7, 3, -2147483648, 0x7fffffff, 1):
        sc.op(OP_CD, n)
        sc.op(OP_CDUPDATE, 0, fb(0.25))
        sc.op(OP_UPDATE, fb(1.0 / 60))
        sc.op(OP_DUMPK)
    sc.op(OP_SETMOVER, 1, 2)
    sc.setf(1, F_NUMBER, 99)
    sc.op(OP_CDUPDATE, 1, 0)
    sc.op(OP_DUMPK)
    sc.op(OP_SETMOVER, 1, 3)
    sc.setf(1, F_NUMBER, 1)
    sc.op(OP_CD, 1)
    sc.op(OP_CDUPDATE, 1, 0)
    sc.op(OP_DUMPK)
    sc.op(OP_DISABLE, 0)
    sc.op(OP_ENABLE, 0)
    sc.op(OP_CCDELETE, 0)
    sc.op(OP_CCDEL, 1, 0)
    sc.op(OP_DUMPK)

    # -- random rounds -----------------------------------------------------------
    sc.tag("random")
    sc.fresh(0x5c)
    sc.op(OP_SINIT)
    countdown_cams(sc, 0xe0000)
    listed = []                         # k on the list, in order
    kind = {}                           # k: "base", "cd" or "fake"
    for _ in range(600):
        r = rnd.random()
        free = [k for k in range(NK) if k not in listed]
        if r < 0.18 and free:
            k = rnd.choice(free)
            sc.op(OP_JUNKK, k, rnd.choice((0, 0xa5, 0x5c)))
            if rnd.random() < 0.5:
                sc.op(OP_CD, rnd.choice((3, 2, 1, 0, -1, 4)))
                sc.op(OP_CDNEW, k, rnd.randrange(-2, 4), rnd.randrange(2))
                kind[k] = "cd"
            else:
                sc.op(OP_CCNEW, k, rnd.randrange(-2, 4))
                if rnd.random() < 0.6:
                    sc.setf(k, F_VPTR, FCVT)
                    kind[k] = "fake"
                else:
                    sc.setf(k, F_DISABLED, rnd.choice((1, 2, -1)))
                    kind[k] = "base"
            listed.append(k)
        elif r < 0.3 and listed:
            k = rnd.choice(listed)
            if kind[k] == "fake":
                sc.op(OP_CCDEL, k, rnd.randrange(4))
                continue
            how = rnd.randrange(3)
            if how == 0:
                sc.op(OP_CCDEL, k, rnd.randrange(4))
            elif how == 1:
                sc.op(OP_CCDELETE, k)
            else:
                sc.op(OP_RAWDTOR, k, rnd.randrange(4), rnd.randrange(2))
            listed.remove(k)
        elif r < 0.4 and listed:
            sc.op(OP_SETMOVER, rnd.choice(listed), rnd.randrange(-1, 4))
        elif r < 0.5 and listed:
            k = rnd.choice(listed)
            if kind[k] == "base":
                sc.op(OP_DISABLE, k)
            else:
                sc.op(rnd.choice((OP_DISABLE, OP_ENABLE)), k)
        elif r < 0.6:
            sc.op(OP_CD, rnd.choice((3, 2, 1, 0, -1, 4, 3, 2)))
        elif r < 0.75:
            sc.op(OP_UPDATE, fb(rnd.choice((1.0 / 30, 1.0 / 60, 0.0))))
        elif r < 0.85 and listed:
            k = rnd.choice(listed)
            if kind[k] == "cd":
                sc.op(OP_CDUPDATE, k, fb(rnd.uniform(-1, 1)))
            elif kind[k] == "fake":
                sc.setf(k, F_DISABLED, rnd.choice((0, 1)))
        elif r < 0.9:
            sc.op(OP_MARK)
        elif r < 0.95 and listed:
            k = rnd.choice(listed)
            sc.setf(k, rnd.choice((F_VIEW, F_NEED)), rnd.randrange(-5, 6))
        else:
            sc.op(OP_DUMPK)
    sc.op(OP_DUMPK)
    sc.op(OP_DUMPL)


def script():
    sc = Script()
    rnd = random.Random(0xcc0de)
    coordinator_scenarios(sc, rnd)
    built_scenarios(sc, rnd)
    retail_scenarios(sc)
    return sc


# ================================================================ the model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        e.stub_bware()
        self.heap = []                  # (addr, label)
        self.junk = -1
        self.number = 0
        e.mem[ARENA:ARENA + ARENA_SIZE] = bytes(ARENA_SIZE)
        for base, n in ((KS, 0x1000), (MOVERS, 0x1000), (PLAYERS, 0x1000),
                        (CARS, 0x1000), (RACE, 0x100), (FMVT, 0x1000),
                        (CD, 0x1000), (FCVT, 0x1000)):
            e.mem[base:base + n] = bytes(n)
        for i in range(NMOVERS):
            e.put32(MOVERS + 0x100 * i + 40, FMVT)
        for i in range(2):
            e.put32(PLAYERS + 0x100 * i + 4, CARS + 0x100 * i)
        e.put32(GP + RACE_GP, RACE)
        for slot, fn in ((8, FMVT_DTOR), (96, FMVT_ENABLE),
                         (104, FMVT_DISABLE)):
            e.put32(FMVT + slot + 4, fn)
        e.put32(FCVT + 12, FCVT_DTOR)
        e.put32(FCVT + 20, FCVT_UPDATE)
        self.stubs()

    def emit(self, s):
        self.out.append(s)

    def w(self, a):
        return self.e.u32(a)

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        if self.junk >= 0 and a == self.junk * 0x01010101:
            return "junk"
        if ARENA - NEAR <= a < ARENA + ARENA_SIZE + NEAR:
            return "a%+d" % (a - ARENA)
        if a == LIST:
            return "list"
        for i in range(NK):
            if a == KS + 0x100 * i:
                return "k%d" % i
        for i in range(NMOVERS):
            if a == MOVERS + 0x100 * i:
                return "m%d" % i
        for i in range(2):
            if a == PLAYERS + 0x100 * i:
                return "p%d" % i
            if a == CARS + 0x100 * i:
                return "car%d" % i
        if a == RACE:
            return "race"
        for base, lab in self.heap:
            if a == base:
                return lab
        return "?"

    # ---- the stand-ins ---------------------------------------------------

    def stubs(self):
        e = self.e

        def arg(i):
            return e.reg[4 + i] & M32

        def cstr(p):
            end = e.mem.index(b"\0", p)
            return e.mem[p:end].decode("latin-1")

        def malloc(em):
            size = s32(arg(0))
            span = max(size, 0) + SLACK
            p = e.alloc(span, align=16)
            e.mem[p:p + span] = bytes([0xcd]) * span
            lab = "h%d" % len(self.heap)
            self.heap.append((p, lab))
            self.emit("  alloc %s size %d name %s flags %d pool %d"
                      % (lab, size, cstr(arg(1)), s32(arg(2)), s32(arg(3))))
            return p

        def free(em):
            self.emit("  free %s" % self.label(arg(0)))

        def countdown(em):
            self.emit("  countdown %s" % self.label(arg(0)))
            return s32(self.number)     # v0 as the EE has it, sign-extended

        def bumper(em):
            self.emit("  bumper %s view %d car %s"
                      % (self.label(arg(0)), s32(arg(1)),
                         self.label(arg(2))))
            self.dump_cd("  bumper cd", arg(3), read_only=True)
            e.put32(arg(0) + 40, FMVT)
            return arg(0)

        def mover_dtor(em):
            self.emit("  mover dtor %s" % self.label(arg(0)))
            if arg(1) & 1:
                self.emit("  free %s" % self.label(arg(0)))

        def mover_enable(em):
            self.emit("  mover enable %s" % self.label(arg(0)))

        def mover_disable(em):
            self.emit("  mover disable %s" % self.label(arg(0)))

        def fake_dtor(em):
            self.emit("  fake dtor %s %d" % (self.label(arg(0)), s32(arg(1))))

        def fake_update(em):
            self.emit("  fake update %s %s" % (self.label(arg(0)),
                                               fx(e.fpr[12])))

        e.stub(BMALLOC, malloc)
        e.stub(BFREE, free)
        e.stub(BDELETE, free)
        e.stub(COUNTDOWN, countdown)
        e.stub(BUMPER, bumper)
        e.stub(FMVT_DTOR, mover_dtor)
        e.stub(FMVT_ENABLE, mover_enable)
        e.stub(FMVT_DISABLE, mover_disable)
        e.stub(FCVT_DTOR, fake_dtor)
        e.stub(FCVT_UPDATE, fake_update)

    # ---- the dumps -------------------------------------------------------

    def dump_cd(self, head, a, read_only=False):
        w = self.w
        typ = s32(w(a))
        s = [head]
        for off, ptr in CD_FIELDS:
            if read_only:
                if off > 4 and not 0 <= typ <= 2:
                    break
                if off in CD_TYPE2_ONLY and typ != 2:
                    continue
                if off in CD_TYPE0_ONLY and typ != 0:
                    continue
            v = w(a + off)
            s.append(" " + (self.label(v) if ptr else "%08x" % v))
        self.emit("".join(s))

    def dump_loader(self):
        w = self.w
        self.emit("loader")
        for name, cnt, lst, n in LISTS:
            labs = [self.label(w(LOADER + lst + 4 * i)) for i in range(n)]
            s = "  %s %d:" % (name, s32(w(LOADER + cnt)))
            i = 0
            while i < n:
                j = i + 1
                while j < n and labs[j] == labs[i]:
                    j += 1
                s += " %s*%d" % (labs[i], j - i) if j - i > 1 else \
                    " %s" % labs[i]
                i = j
            self.emit(s)
        self.emit("  shakes %d %s vortex %s %d" % (
            s32(w(LOADER + SHAKES_N)), self.label(w(LOADER + SHAKES_P)),
            " ".join(fx(w(LOADER + VORTEX + 4 * i)) for i in range(4)),
            s32(w(LOADER + VORTEX_N))))

    def dump_coordinators(self):
        w = self.w
        fwd, n, g = [], w(LIST), 0
        while n != LIST and g < 64:
            fwd.append(self.label(n))
            n, g = w(n), g + 1
        back, n, g = [], w(LIST + 4), 0
        while n != LIST and g < 64:
            back.append(self.label(n))
            n, g = w(n + 4), g + 1
        self.emit("coordinators" + "".join(" " + x for x in fwd) + " /"
                  + "".join(" " + x for x in back))
        for i in range(NK):
            k = KS + 0x100 * i
            self.emit("  k%d %s %s %s %08x %08x %08x %08x %s %08x" % (
                i, self.label(w(k)), self.label(w(k + 4)),
                self.label(w(k + 8)), w(k + 12), w(k + 16), w(k + 20),
                w(k + 24), self.label(w(k + 28)), w(k + 32)))

    # ---- the run ---------------------------------------------------------

    def vcall(self, k, slot, *args):
        e = self.e
        vt = self.w(k + 24)
        delta = s32(e.u16(vt + slot) << 16) >> 16
        fn = self.w(vt + slot + 4)
        return e.call(fn, (k + delta) & M32, *args)

    def at(self, off):
        return 0 if s32(off) == -1 else ARENA + off

    # The ints the script hands a call go in sign-extended, as the EE's
    # registers hold them.
    def run(self, sc):
        e, w = self.e, self.w
        tags = sc.tags
        for o in sc.ops:
            code, a = o[0], o[1:]
            if code == OP_TAG:
                self.emit("[%s]" % tags[a[0]])
            elif code == OP_PUT:
                off, n = a[0], a[1]
                data = struct.pack("<%dI" % len(a[2:]), *a[2:])[:n]
                e.mem[ARENA + off:ARENA + off + n] = data
            elif code == OP_JUNKL:
                self.junk = a[0] & 0xff
                e.mem[LOADER:LOADER + LOADER_SIZE] = \
                    bytes([self.junk]) * LOADER_SIZE
            elif code == OP_INITL:
                self.emit("init")
                e.call(INITL, LOADER)
            elif code == OP_SINIT:
                self.emit("sinit")
                e.call(SINIT)
            elif code == OP_LOAD:
                self.emit("load %s" % self.label(self.at(a[0])))
                self.emit("load -> %d" % e.call(LOADER_CAMERAS,
                                                self.at(a[0])))
            elif code == OP_UNLOAD:
                self.emit("unload %s" % self.label(self.at(a[0])))
                self.emit("unload -> %d" % e.call(UNLOADER_CAMERAS,
                                                  self.at(a[0])))
            elif code == OP_DUMPL:
                self.dump_loader()
            elif code == OP_POKEL:
                f, v = a
                e.put32(LOADER + POKEL_OFF[f],
                        self.at(v) if f == L_SHAKEP else v)
            elif code == OP_POKEP:
                k, idx, off = a
                name, cnt, lst, n = LISTS[k]
                e.put32(LOADER + lst + 4 * idx, self.at(off))
            elif code == OP_SEED:
                e.put32(GP + SEED_GP, a[0])
            elif code == OP_SHAKE:
                self.emit("shake %d" % s32(a[0]))
                r = e.call(SHAKE, LOADER, s32(a[0]))
                self.emit("shake -> %s seed %08x" % (
                    self.label(r), w(GP + SEED_GP)))
            elif code == OP_FIND:
                name = tags[a[0]]
                self.emit("find '%s'" % name)
                b = name.encode("latin-1") + b"\0"
                p = CD + 0x400
                e.mem[p:p + len(b)] = b
                self.emit("find -> %s" % self.label(e.call(FIND, LOADER, p)))
            elif code == OP_KEEP:
                self.emit("keep %d" % s32(a[0]))
                e.call(KEEP, s32(a[0]))
            elif code == OP_PARSE:
                off, fill = a[0], a[1] & 0xff
                e.mem[CD:CD + 164] = bytes([fill]) * 164
                save, self.junk = self.junk, fill
                r = e.call(PARSE, CD, self.at(off))
                self.emit("parse %s -> %s" % (self.label(self.at(off)),
                                              "cd" if r & M32 == CD else "?"))
                self.dump_cd(" ", CD)
                self.junk = save
            elif code == OP_CCNEW:
                k, view = a
                self.emit("ccnew k%d %d" % (k, s32(view)))
                r = e.call(CC_CTOR, KS + 0x100 * k, s32(view))
                self.emit("ccnew -> %s" % self.label(r))
            elif code == OP_CDNEW:
                k, view, p = a
                self.emit("cdnew k%d %d p%d" % (k, s32(view), p))
                r = e.call(CD_CTOR, KS + 0x100 * k, s32(view),
                           PLAYERS + 0x100 * (p & 1))
                self.emit("cdnew -> %s" % self.label(r))
            elif code == OP_CCDEL:
                k, flags = a
                self.emit("ccdel k%d %d" % (k, s32(flags)))
                self.vcall(KS + 0x100 * k, 8, s32(flags))
            elif code == OP_CCDELETE:
                self.emit("ccdelete k%d" % a[0])
                self.vcall(KS + 0x100 * a[0], 8, 3)
            elif code == OP_RAWDTOR:
                k, flags, which = a
                self.emit("rawdtor k%d %d %d" % (k, s32(flags), which))
                e.call(CD_DTOR if which else CC_DTOR, KS + 0x100 * k,
                       s32(flags))
            elif code == OP_DISABLE:
                self.emit("disable k%d" % a[0])
                e.call(CC_DISABLE, KS + 0x100 * a[0])
            elif code == OP_ENABLE:
                self.emit("enable k%d" % a[0])
                e.call(CC_ENABLE, KS + 0x100 * a[0])
            elif code == OP_MARK:
                self.emit("mark")
                e.call(CC_MARK)
            elif code == OP_UPDATE:
                self.emit("update %08x" % a[0])
                e.fpr[12] = a[0]
                e.call(CC_UPDATE_ALL)
            elif code == OP_CDUPDATE:
                k, dt = a
                self.emit("cdupdate k%d %08x" % (k, dt))
                e.fpr[12] = dt
                e.call(CD_UPDATE, KS + 0x100 * k)
            elif code == OP_SETMOVER:
                k, m = a
                e.put32(KS + 0x100 * k + 8,
                        0 if s32(m) < 0 else MOVERS + 0x100 * (m % NMOVERS))
            elif code == OP_SETF:
                k, f, v = a
                c = KS + 0x100 * k
                if f == F_PLAYER:
                    e.put32(c + 28, PLAYERS + 0x100 * (v & 1))
                else:
                    e.put32(c + (12, 16, 20, 32, 24)[f], v)
            elif code == OP_CD:
                self.number = a[0]
            elif code == OP_JUNKK:
                k, b = a
                c = KS + 0x100 * k
                e.mem[c:c + 0x100] = bytes([b & 0xff]) * 0x100
            elif code == OP_DUMPK:
                self.dump_coordinators()
            else:
                raise ValueError("op %d" % code)
        return self.out


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc.encode().hex().splitlines()
                               + sc.tags, lambda s: Model().run(sc),
                               cut=MUTATIONS_HEADER)


# ================================================================ the build


def build_harness(tmp, name="cameracoord_test"):
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

def M(name, before, after):
    return (name, CC, before, after)


MUTATIONS = [
    # -- bStrICmp and the payload ----------------------------------------------
    M("ic-range", "if ((uint32_t)(v - 97) < 26u)",
      "if ((uint32_t)(v - 97) < 25u)"),
    M("ic-range-hi", "if ((uint32_t)(v - 97) < 26u)",
      "if ((uint32_t)(v - 97) < 27u)"),
    M("ic-mask", "v &= 0x5f;", "v &= 0x7f;"),
    M("ic-ret", "return ca - cb;", "return 0;"),
    M("pl-23", "((uintptr_t)chunk + 23)", "((uintptr_t)chunk + 24)"),
    M("pl-mask", "& ~(uintptr_t)15)", "& ~(uintptr_t)7)"),
    M("dm-free", "    m->vtbl->Destroy(m);\n    bFree(m);",
      "    m->vtbl->Destroy(m);"),
    M("dm-dtor", "    m->vtbl->Destroy(m);\n    bFree(m);", "    bFree(m);"),

    # -- CameraLoader's constructor ---------------------------------------------
    M("in-hl", "    cl->NumHighlightCameras = 0;\n    cl->NumPreRaceCameras = 0;",
      "    cl->NumPreRaceCameras = 0;"),
    M("in-pre", "    cl->NumPreRaceCameras = 0;\n    cl->NumFlyByCameras = 0;",
      "    cl->NumFlyByCameras = 0;"),
    M("in-fb", "    cl->NumFlyByCameras = 0;\n    cl->NumPostRaceCameras = 0;",
      "    cl->NumPostRaceCameras = 0;"),
    M("in-post", "    cl->NumPostRaceCameras = 0;\n    memset",
      "    memset"),
    M("in-pn", "memset(cl->NumPlayerNisCameras, 0, sizeof cl->NumPlayerNisCameras);",
      "cl->NumPlayerNisCameras[0] = 0;"),
    M("in-nis", "    cl->NumNisCameras = 0;\n    cl->VortexCount = 0;",
      "    cl->VortexCount = 0;"),
    M("in-vc", "    cl->VortexCount = 0;\n    cl->TuningVortex.x",
      "    cl->TuningVortex.x"),
    M("in-vx", "cl->TuningVortex.x = 0.0f;", "(void)0;"),
    M("in-vy", "cl->TuningVortex.y = 0.0f;", "(void)0;"),
    M("in-vz", "cl->TuningVortex.z = 0.0f;", "(void)0;"),
    M("in-shakes", "cl->TuningVortex.z = 0.0f;",
      "cl->TuningVortex.z = 0.0f;\n    cl->NumCameraShakes = 0;"),

    # -- Loader ---------------------------------------------------------------
    M("ll-type", "if (bchunk_u32(c) == type) {", "if (bchunk_u32(c) != type) {"),
    M("ll-step", "c += 8 + bchunk_u32(c + 4)) {\n        if (bchunk_u32(c) == type)",
      "c += 16 + bchunk_u32(c + 4)) {\n        if (bchunk_u32(c) == type)"),
    M("ll-end", "    uint8_t *end = chunk + 8 + bchunk_u32(chunk + 4);\n    uint8_t *c;",
      "    uint8_t *end = chunk + bchunk_u32(chunk + 4);\n    uint8_t *c;"),
    M("ll-pay", "list[*count] = payload(c);", "list[*count] = (char *)c + 8;"),
    M("ll-inc", "(*count)++;", "(*count) += 2;"),
    M("ld-hl-type", "if (type == CAMERA_CHUNK_HIGHLIGHTS) {\n        uint8_t *end",
      "if (type == CAMERA_CHUNK_PRE_RACE) {\n        uint8_t *end"),
    M("ld-hl-reset", "cl->NumHighlightCameras = 0;\n        for", "for"),
    M("ld-hl-step", "c += 8 + bchunk_u32(c + 4)) {\n            uint32_t t",
      "c += 12 + bchunk_u32(c + 4)) {\n            uint32_t t"),
    M("ld-vortex-type", "if (t == CAMERA_CHUNK_VORTEX) {",
      "if (t == CAMERA_CHUNK_FLY_BY_CAMERA) {"),
    M("ld-vortex-16", "memcpy(&cl->TuningVortex, v, 16);",
      "memcpy(&cl->TuningVortex, v, 12);"),
    M("ld-vortex-count", "memcpy(&cl->VortexCount, v + 16, 4);",
      "memcpy(&cl->VortexCount, v + 12, 4);"),
    M("ld-hl-child", "} else if (t == CAMERA_CHUNK_HIGHLIGHT) {", "} else {"),
    M("ld-hl-pay", "cl->HighlightCameraData[cl->NumHighlightCameras] =\n                    payload(c);",
      "cl->HighlightCameraData[cl->NumHighlightCameras] =\n                    (char *)c;"),
    M("ld-fb-reset", "cl->NumFlyByCameras = 0;\n        load_list", "load_list"),
    M("ld-fb-child", "load_list(chunk, CAMERA_CHUNK_FLY_BY_CAMERA,",
      "load_list(chunk, CAMERA_CHUNK_PRE_RACE_CAMERA,"),
    M("ld-pre-reset", "cl->NumPreRaceCameras = 0;\n        load_list", "load_list"),
    M("ld-pre-child", "load_list(chunk, CAMERA_CHUNK_PRE_RACE_CAMERA,",
      "load_list(chunk, CAMERA_CHUNK_POST_RACE_CAMERA,"),
    M("ld-post-reset", "cl->NumPostRaceCameras = 0;\n        load_list", "load_list"),
    M("ld-post-child", "load_list(chunk, CAMERA_CHUNK_POST_RACE_CAMERA,",
      "load_list(chunk, CAMERA_CHUNK_PRE_RACE_CAMERA,"),
    M("ld-nis-reset", "} else if (type == CAMERA_CHUNK_NIS) {\n        load_list",
      "} else if (type == CAMERA_CHUNK_NIS) {\n        cl->NumNisCameras = 0;\n        load_list"),
    M("ld-nis-child", "load_list(chunk, CAMERA_CHUNK_NIS_CAMERA,",
      "load_list(chunk, CAMERA_CHUNK_FLY_BY_CAMERA,"),
    M("ld-shake-type", "} else if (type == CAMERA_CHUNK_SHAKES) {\n        cl->Shakes",
      "} else if (type == CAMERA_CHUNK_VORTEX) {\n        cl->Shakes"),
    M("ld-shake-pay", "cl->Shakes = (CameraShake *)(void *)payload(chunk);",
      "cl->Shakes = (CameraShake *)(void *)(chunk + 8);"),
    M("ld-shake-div", "(int32_t)(bchunk_u32(chunk + 4) / CAMERA_SHAKE_SIZE)",
      "(int32_t)(bchunk_u32(chunk + 4) / 556u)"),
    M("ld-shake-signed", "(int32_t)(bchunk_u32(chunk + 4) / CAMERA_SHAKE_SIZE)",
      "((int32_t)bchunk_u32(chunk + 4) / (int32_t)CAMERA_SHAKE_SIZE)"),
    M("ld-mark", "    mark_camera_data_as_needing_to_be_reloaded();\n    return 1;",
      "    return 1;"),
    M("ld-ret", "    return 1;\n}\n\nint camera_loader_unload",
      "    return 2;\n}\n\nint camera_loader_unload"),
    M("ld-ret0", "        return 0;\n    }\n    mark_camera",
      "        return 1;\n    }\n    mark_camera"),

    # -- Unloader -------------------------------------------------------------
    M("ul-hl", "        cl->NumHighlightCameras = 0;\n    } else if",
      "        cl->NumHighlightCameras = 1;\n    } else if"),
    M("ul-fb", "        cl->NumFlyByCameras = 0;\n    } else if",
      "        cl->NumFlyByCameras = 1;\n    } else if"),
    M("ul-pre", "        cl->NumPreRaceCameras = 0;\n    } else if",
      "        cl->NumPreRaceCameras = 1;\n    } else if"),
    M("ul-post", "        cl->NumPostRaceCameras = 0;\n    } else if",
      "        cl->NumPostRaceCameras = 1;\n    } else if"),
    M("ul-vortex", "        cl->NumHighlightCameras = 0;\n    } else if",
      "        cl->NumHighlightCameras = 0;\n        cl->VortexCount = 0;\n    } else if"),
    M("ul-nis-type", "if (bchunk_u32(c) != CAMERA_CHUNK_NIS_CAMERA)",
      "if (bchunk_u32(c) == CAMERA_CHUNK_NIS)"),
    M("ul-nis-pay", "data = payload(c);", "data = (char *)c + 8;"),
    M("ul-nis-k", "for (k = 0; k < 2; k++) {", "for (k = 0; k < 1; k++) {"),
    M("ul-nis-i", "for (i = 0; i < cl->NumPlayerNisCameras[k]; i++) {",
      "for (i = 1; i < cl->NumPlayerNisCameras[k]; i++) {"),
    M("ul-nis-last", "last = k;", "last = 0;"),
    M("ul-nis-found", "found++;", "found += 2;"),
    M("ul-nis-gt", "if (found > 0)", "if (found > 1)"),
    M("ul-nis-sub", "cl->NumPlayerNisCameras[last] -= found;",
      "cl->NumPlayerNisCameras[last] = 0;"),
    M("ul-shakes", "        cl->NumCameraShakes = 0;\n    } else {",
      "        cl->NumCameraShakes = 1;\n    } else {"),
    M("ul-ret0", "        return 0;\n    }\n    return 1;",
      "        return 1;\n    }\n    return 1;"),
    M("ul-ret1", "    return 1;\n}\n\nCameraShake",
      "    return 2;\n}\n\nCameraShake"),
    M("wr-unload", "return camera_loader_unload(&TheCameraLoader, chunk);",
      "return camera_loader_load(&TheCameraLoader, chunk);"),

    # -- FindRandomCameraShake ----------------------------------------------------
    M("sh-bank0", "    if (bank == 0)\n        return NULL;\n", ""),
    M("sh-count", "if (cl->Shakes[i].BankNumber == bank)\n            n++;",
      "if (cl->Shakes[i].BankNumber != bank)\n            n++;"),
    M("sh-loop", "for (i = 0; i < cl->NumCameraShakes; i++)\n        if",
      "for (i = 1; i < cl->NumCameraShakes; i++)\n        if"),
    M("sh-n0", "    if (n == 0)\n        return NULL;\n    r = bRandomI",
      "    if (n == 0)\n        return cl->Shakes;\n    r = bRandomI"),
    M("sh-rand", "r = bRandomI(n, &bDefaultSeed);", "r = bRandomI(n + 1, &bDefaultSeed);"),
    M("sh-skip", "if (cl->Shakes[i].BankNumber != bank)\n            continue;",
      "if (cl->Shakes[i].BankNumber == bank)\n            continue;"),
    M("sh-r0", "if (r == 0)\n            return &cl->Shakes[i];",
      "if (r <= 1)\n            return &cl->Shakes[i];"),
    M("sh-dec", "        r--;", "        r -= 2;"),

    # -- FindCameraData ---------------------------------------------------------
    M("fd-lists", "for (list = 0; list < 4; list++) {", "for (list = 0; list < 3; list++) {"),
    M("fd-hl", "n = cl->NumHighlightCameras;\n            data = cl->HighlightCameraData;",
      "n = cl->NumFlyByCameras;\n            data = cl->FlyByCameraData;"),
    M("fd-cmp", "if (str_icmp(cd.Name, name) == 0)", "if (strcmp(cd.Name, name) == 0)"),
    M("fd-ret", "return data[i];", "return data[0];"),
    M("fd-i", "for (i = 0; i < n; i++) {\n            CameraDataItems cd;",
      "for (i = 1; i < n; i++) {\n            CameraDataItems cd;"),

    # -- the NIS keeper ---------------------------------------------------------
    M("kp-count", "cl->NumPlayerNisCameras[player] = cl->NumNisCameras;",
      "cl->NumPlayerNisCameras[player] = 0;"),
    M("kp-all", "for (i = 0; i < CAMERA_LOADER_NIS; i++)\n        cl->PlayerNisCameraData",
      "for (i = 0; i < 4; i++)\n        cl->PlayerNisCameraData"),
    M("kp-zero", "    cl->NumNisCameras = 0;\n}", "}"),

    # -- CameraDataItems --------------------------------------------------------
    M("pa-name", "    cd->Name = p;\n    p += 32;", "    p += 32;\n    cd->Name = p;"),
    M("pa-name32", "    p += 32;", "    p += 28;"),
    M("pa0-sx", "cd->SpringXVel = next_float(&p);\n        cd->SpringYVel = next_float(&p);",
      "cd->SpringYVel = next_float(&p);\n        cd->SpringXVel = next_float(&p);"),
    M("pa0-const", "cd->SpringConst = next_float(&p);", "(void)next_float(&p);"),
    M("pa0-lookz", "cd->LookOffsetZ = next_float(&p);", "(void)next_float(&p);"),
    M("pa0-leave", "cd->LeaveHorizComp = next_float(&p);", "(void)next_float(&p);"),
    M("pa0-isleave", "cd->IsLeaveSet = next_int(&p);", "(void)next_int(&p);"),
    M("pa0-eye", "cd->IsLeaveSet = next_int(&p);\n        cd->EyeSplineSpeed = next_float(&p);",
      "cd->IsLeaveSet = next_int(&p);\n        (void)next_float(&p);"),
    M("pa0-wipe", "cd->WipeDistance = next_float(&p);\n        cd->WipeAutoDisable = next_int(&p);",
      "cd->WipeAutoDisable = next_int(&p);\n        cd->WipeDistance = next_float(&p);"),
    M("pa0-back", "cd->Backwards = next_int(&p);\n        cd->ShakeBankNumber = next_int(&p);",
      "cd->ShakeBankNumber = next_int(&p);\n        cd->Backwards = next_int(&p);"),
    M("pa0-shake", "cd->ShakeBankNumber = next_int(&p);", "(void)next_int(&p);"),
    M("pa0-counts", "cd->NumAreaFaces = next_int(&p);\n        cd->NumEyeVerts = next_int(&p);\n        cd->WipeDistance",
      "cd->NumEyeVerts = next_int(&p);\n        cd->NumAreaFaces = next_int(&p);\n        cd->WipeDistance"),
    M("pa0-pad", "p += 8;\n        cd->LookVerts = NULL;", "p += 12;\n        cd->LookVerts = NULL;"),
    M("pa0-lv", "        cd->LookVerts = NULL;\n", ""),
    M("pa0-lss", "        cd->LookSplineSpeed = 0.0f;\n", ""),
    M("pa0-nlv", "        cd->NumLookVerts = 0;\n", ""),
    M("pa0-lll", "        cd->LockLookSpeedToCar = 0;\n", ""),
    M("pa0-fov", "        p += 512;\n        cd->EyeVerts = (bVector3 *)(void *)p;\n        p += cd->NumEyeVerts * 16;\n        cd->BankVerts = (bVector3 *)(void *)p;\n        p += cd->NumEyeVerts * 16;\n        cd->AreaFaces",
      "        p += 516;\n        cd->EyeVerts = (bVector3 *)(void *)p;\n        p += cd->NumEyeVerts * 16;\n        cd->BankVerts = (bVector3 *)(void *)p;\n        p += cd->NumEyeVerts * 16;\n        cd->AreaFaces"),
    M("pa0-bank", "p += cd->NumEyeVerts * 16;\n        cd->AreaFaces = p;",
      "p += cd->NumAreaFaces * 16;\n        cd->AreaFaces = p;"),
    M("pa0-faces", "p += cd->NumAreaFaces * 16;\n        cd->AreaVerts = (bVector2 *)(void *)p;\n    } else if",
      "p += cd->NumAreaFaces * 8;\n        cd->AreaVerts = (bVector2 *)(void *)p;\n    } else if"),
    M("pa1-types", "} else if (cd->Type == 1 || cd->Type == 2) {", "} else if (cd->Type == 1) {"),
    M("pa1-types3", "} else if (cd->Type == 1 || cd->Type == 2) {",
      "} else if (cd->Type >= 1 && cd->Type <= 3) {"),
    M("pa1-fovss", "if (cd->Type == 2)\n            cd->FOVSplineSpeed",
      "if (cd->Type >= 1)\n            cd->FOVSplineSpeed"),
    M("pa1-lss", "cd->LookSplineSpeed = next_float(&p);", "(void)next_float(&p);"),
    M("pa1-lll", "cd->LockLookSpeedToCar = next_int(&p);", "(void)next_int(&p);"),
    M("pa1-nlv", "cd->NumLookVerts = next_int(&p);", "(void)next_int(&p);"),
    M("pa1-near", "cd->NearClip = next_float(&p);\n        cd->FarClip = next_float(&p);\n        cd->Backwards = next_int(&p);\n        p += cd->Type",
      "cd->FarClip = next_float(&p);\n        cd->NearClip = next_float(&p);\n        cd->Backwards = next_int(&p);\n        p += cd->Type"),
    M("pa1-pad", "p += cd->Type == 1 ? 12 : 8;", "p += cd->Type == 1 ? 8 : 12;"),
    M("pa1-pad2", "p += cd->Type == 1 ? 12 : 8;", "p += 12;"),
    M("pa1-look", "cd->LookVerts = (bVector3 *)(void *)p;\n        p += cd->NumLookVerts * 16;",
      "cd->LookVerts = (bVector3 *)(void *)p;\n        p += cd->NumEyeVerts * 16;"),
    M("pa1-faces", "p += cd->NumAreaFaces * 16;\n        cd->AreaVerts = (bVector2 *)(void *)p;\n        cd->SpringXVel",
      "p += cd->NumAreaVerts * 16;\n        cd->AreaVerts = (bVector2 *)(void *)p;\n        cd->SpringXVel"),
    M("pa1-spring", "        cd->SpringXVel = 0.0f;\n", ""),
    M("pa1-const", "        cd->SpringConst = 0.0f;\n", ""),
    M("pa1-shake", "        cd->ShakeBankNumber = 0;\n", ""),
    M("pa-ret", "    return cd;\n}", "    return NULL;\n}"),

    # -- the list and the base --------------------------------------------------
    M("si-next", "    CameraCoordinatorList.next = &CameraCoordinatorList;\n", ""),
    M("si-loader", "    camera_loader_init(&TheCameraLoader);\n}", "}"),
    M("cc-tail", "    tail->next = &c->Node;\n", ""),
    M("cc-prev", "    CameraCoordinatorList.prev = &c->Node;\n", ""),
    M("cc-vt", "c->_vtable = BASECAMERACOORDINATOR_VTABLE;\n    c->ViewID",
      "c->_vtable = COUNTDOWNCAMERACOORDINATOR_VTABLE;\n    c->ViewID"),
    M("cc-view", "c->ViewID = viewID;", "c->ViewID = 0;"),
    M("cc-nprev", "c->Node.prev = tail;", "c->Node.prev = &CameraCoordinatorList;"),
    M("cc-nnext", "c->Node.next = &CameraCoordinatorList;", "c->Node.next = tail;"),
    M("cc-mover", "    c->pCameraMover = NULL;\n    c->NeedToReload",
      "    c->NeedToReload"),
    M("cc-need", "c->NeedToReloadCameraData = 0;", "c->NeedToReloadCameraData = 1;"),
    M("cc-dis", "    c->Disabled = 0;\n    return c;", "    return c;"),
    M("cc-ret", "    return c;\n}\n\nvoid camera_coordinator_destroy",
      "    return NULL;\n}\n\nvoid camera_coordinator_destroy"),
    M("cd-vt", "    c->_vtable = BASECAMERACOORDINATOR_VTABLE;\n    if (c->pCameraMover",
      "    if (c->pCameraMover"),
    M("cd-mover", "    if (c->pCameraMover != NULL)\n        delete_mover(c->pCameraMover);\n    c->Node",
      "    c->Node"),
    M("cd-clear", "        delete_mover(c->pCameraMover);\n    c->Node",
      "        delete_mover(c->pCameraMover);\n    c->pCameraMover = NULL;\n    c->Node"),
    M("cd-unlink1", "    c->Node.prev->next = c->Node.next;\n", ""),
    M("cd-unlink2", "    c->Node.next->prev = c->Node.prev;\n", ""),
    M("cd-free", "if (flags & 1)\n        bFree(c);", "if (flags & 2)\n        bFree(c);"),
    M("cdel-3", "((CoordinatorDtorFn)e->fn)(vt_this(b, e), 3);",
      "((CoordinatorDtorFn)e->fn)(vt_this(b, e), 1);"),
    M("di-guard", "    if (b->Disabled)\n        return;\n", ""),
    M("di-set", "b->Disabled = 1;", "b->Disabled = 2;"),
    M("di-mover", "b->pCameraMover->vtbl->Disable(b->pCameraMover);",
      "b->pCameraMover->vtbl->Enable(b->pCameraMover);"),
    M("en-guard", "    if (!b->Disabled)\n        return;\n", ""),
    M("en-set", "b->Disabled = 0;", "b->Disabled = 2;"),
    M("en-mover", "b->pCameraMover->vtbl->Enable(b->pCameraMover);",
      "b->pCameraMover->vtbl->Disable(b->pCameraMover);"),
    M("mk-1", "->NeedToReloadCameraData = 1;", "->NeedToReloadCameraData = 2;"),
    M("mk-first", "for (n = CameraCoordinatorList.next; n != &CameraCoordinatorList;\n         n = n->next)\n        ((Base",
      "for (n = CameraCoordinatorList.next->next; n != &CameraCoordinatorList;\n         n = n->next)\n        ((Base"),
    M("ua-dis", "if (!c->Disabled) {", "if (c->Disabled != 1) {"),
    M("ua-slot", "CAMERACOORDINATOR_VT_UPDATE);", "CAMERACOORDINATOR_VT_DTOR);"),
    M("ua-dt", "((CoordinatorUpdateFn)e->fn)(vt_this(c, e), dt);",
      "((CoordinatorUpdateFn)e->fn)(vt_this(c, e), 0.0f);"),

    # -- the countdown ------------------------------------------------------------
    M("ct-player", "    c->pPlayer = p;\n", ""),
    M("ct-vt", "c->Base._vtable = COUNTDOWNCAMERACOORDINATOR_VTABLE;\n    c->CurrentCountdownNumber = -1;",
      "c->Base._vtable = BASECAMERACOORDINATOR_VTABLE;\n    c->CurrentCountdownNumber = -1;"),
    M("ct-num", "c->CurrentCountdownNumber = -1;", "c->CurrentCountdownNumber = 0;"),
    M("ct-update", "    countdown_camera_coordinator_update(c, 0.0f);\n", ""),
    M("ct-ret", "    return c;\n}\n\nCountdownCameraCoordinator *countdown_camera_coordinator_construct",
      "    return NULL;\n}\n\nCountdownCameraCoordinator *countdown_camera_coordinator_construct"),
    M("ctd-flags", "camera_coordinator_destroy(&c->Base, flags);",
      "camera_coordinator_destroy(&c->Base, 0);"),
    M("cu-same", "    if (n == c->CurrentCountdownNumber)\n        return;\n", ""),
    M("cu-del", "        delete_mover(c->Base.pCameraMover);\n        c->Base.pCameraMover = NULL;",
      "        c->Base.pCameraMover = NULL;"),
    M("cu-clear", "        delete_mover(c->Base.pCameraMover);\n        c->Base.pCameraMover = NULL;",
      "        delete_mover(c->Base.pCameraMover);"),
    M("cu-fmt", '"COUNTDOWN_%d"', '"COUNTDOWN %d"'),
    M("cu-null", "if (data != NULL && gBumperCameraMoverFn != NULL) {",
      "if (gBumperCameraMoverFn != NULL) {"),
    M("cu-parse", "        camera_data_items_parse(&cd, data);\n", ""),
    M("cu-size", "bMalloc(1116,", "bMalloc(1112,"),
    M("cu-name", '"BumperCameraMover", 0, 16', '"BumperCamera", 0, 16'),
    M("cu-pool", '"BumperCameraMover", 0, 16', '"BumperCameraMover", 0, 0'),
    M("cu-flags", '"BumperCameraMover", 0, 16', '"BumperCameraMover", 1, 16'),
    M("cu-view", "mem, c->Base.ViewID, c->pPlayer->MyCar, &cd);",
      "mem, 0, c->pPlayer->MyCar, &cd);"),
    M("cu-car", "mem, c->Base.ViewID, c->pPlayer->MyCar, &cd);",
      "mem, c->Base.ViewID, (struct Car *)(void *)c->pPlayer, &cd);"),
    M("cu-keep", "    c->CurrentCountdownNumber = n;\n}", "}"),

    # -- the tables ---------------------------------------------------------------
    M("vt-base-dtor", "E(camera_coordinator_destroy),", "{ 0, 0, NULL },"),
    M("vt-cd-dtor", "E(countdown_camera_coordinator_destroy),", "{ 0, 0, NULL },"),
    M("vt-cd-update", "E(countdown_camera_coordinator_update),", "{ 0, 0, NULL },"),
]

EQUIVALENT = {
}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    base = model_cached(sc)
    opsdir = tempfile.TemporaryDirectory()
    ops = Path(opsdir.name) / "ops.bin"
    ops.write_bytes(sc.encode())
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, ops, out)
        took = time.monotonic() - t0
        got = out.read_text().splitlines()
        if diff(base, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "cameracoord_test",
        lambda exe, out: mutpar.run_exe([exe, ops], out, limit),
        base, diff, EQUIVALENT, jobs)
    opsdir.cleanup()
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

    sc = script()
    lines = model_cached(sc)
    with tempfile.TemporaryDirectory() as tmp:
        ops = Path(tmp) / "ops.bin"
        ops.write_bytes(sc.encode())
        exe = build_harness(tmp)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, ops, out)
        harness = out.read_text().splitlines()

    if args.dump:
        Path(args.dump + ".model.txt").write_text(NL.join(lines) + NL)
        Path(args.dump + ".harness.txt").write_text(NL.join(harness) + NL)

    bad = diff(lines, harness)
    print("%d ops, %d lines, %d differ"
          % (len(sc.ops), len(harness), bad))
    sys.exit(1 if (bad or rc) else 0)


if __name__ == "__main__":
    main()
