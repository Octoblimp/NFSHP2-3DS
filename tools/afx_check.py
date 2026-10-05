#!/usr/bin/env python3
"""Cross-check 3DS Files/source/acidsys.c, the data half of the effect
system (AcidFXE.obj), against the retail image itself, run in mipsemu.

The model is the image. These run as shipped: the static constructor
(0x0012a220), afxInit (0x00126d70) and afxClose (0x00126e08), LoaderAcidFX
(0x00126e50) and UnloaderAcidFX (0x00126f60), afxUpdateTextures
(0x00127078), afxGetEmitterData (0x00127120), afxGetEmitter (0x00127198),
afxCopyEmitter (0x00127228), afxGetEmitters (0x001272e0) and
afxDeleteEmitters (0x00127368), both SetEmitterData (0x001273c0,
0x001273d8), AcidEffectSystem's constructor (0x00127418), AddAutoEmitter
(0x001274a0), RemoveAutoEmitter (0x00127688), KillAllActiveEffects
(0x001276a8), TriggerEmitter (0x00127700), UpdateInterestPoints
(0x001286a0) and DoTimeStep (0x00128718), and the deleting destructors of
AcidEmitter (0x00124e20 and its twin 0x0012a3f8), AcidActiveGroup
(0x0012a258) and AcidParticle (0x0012a348). Under them run bStringHash,
bStrNCpy, bMemSet, the node and list destructors, hermite_basis
(0x00126960) with fInvertMatrix and eMulMatrix, eRotateX, Y and Z,
eMulVector, bSin and bCos; eMathInit (0x0011b138) and eMathE's static
constructor (0x0011bf70) run once first, as the boot runs them. The
harness (tools/src/afx_test.c) runs the port over the same script, and
the two transcripts are diffed.

Stubs, the same on both sides: the three slot pools are fixed arenas that
hand out their lowest free slot, zeroed when the pool's flags have
ZERO_ALLOCATED_MEMORY and filled with 0xa5 when not, and print each call
(bNewSlotPool 0x00257c10, bDeleteSlotPool 0x00257c48, bOMalloc 0x00257c80,
bFree(pool, p) 0x00257ca0, and bMalloc(pool) 0x00257c60). bIsSlotPoolFull
(0x00257d10) is 1 when the script has said the pool fails or no slot is
free, and prints its answer. GetTextureInfo (0x001abf48) answers by a rule
on the hash: NULL, a texture of that name, or one whose NameHash is the
hash with its low bit flipped. bFree(void *) (0x00257850) is never
reached and stops the model if it is. eGetView (0x00107c90) gives three
views of the model's, each with a camera the script places or none (its
pCamera at 56, the camera's CurrentKey.Position at 64); bGetTicker
(0x00250f38) counts up by 0x1234567 a call and bGetTickerDifference
(0x00250f48) is half the count between. A car is 2 KB of the model's, of
which DoTimeStep reads only the velocity, at 112. CurrentGameFlowState
(gp-21420) is the script's.

Two of the listings read their stack before writing it. TriggerEmitter's
direction keeps the w of the last eMulVector, and before the first one
whatever its frame held at 204; DoTimeStep hands hermite_basis a matrix
whose columns 2 and 3 it never writes, at 0 of its frame. The model
zeroes both on each entry, and the port starts them at zero.

The records are the disc's: GLOBALB's 111 datas and 112 emitters and each
of the 30 tracks' packs, from extracted-retail. Each is put in a chunk as
its own side lays the struct out, with its links and any pointer that is
not zero set to the byte pattern ("pat"). A script names a record by its
buffer, chunk and index, D0.0.5 or E1.1.3.

afxGetEmitter's listing compares a name with an emitter's data's NameHash
without testing that there is a data, and reads address 8 for one with
none. Word 8 of the image is 0, and the hash a name lookup takes is not,
so the emitter is passed over, as the port does. afxCopyEmitter clears
184 bytes at address 8 when the pool gives it nothing, which the model
lets it do. A hash goes to the image sign-extended, as a 32-bit value
loaded from memory would be.

    python tools/afx_check.py
    python tools/afx_check.py --mutate [--only a,b]
    python tools/afx_check.py --dump out/afx
"""
import argparse
import math
import os
import random
import re
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
from bhash import bhash
from mipsemu import M32, f_to_bits, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/afx_test.c"
ACIDC = "3DS Files/source/acidsys.c"
ACIDFX = "3DS Files/source/acidfx.c"
SOURCES = [HARNESS, ACIDC, ACIDFX] + ["3DS Files/source/" + f for f in (
    "emath.c", "bmatrix.c", "bmath.c", "bmathtab.c",
    "bvector.c")]

HARNESS_TIMEOUT = 120

DISC = ROOT / "extracted-retail"
GLOBALB = DISC / "GLOBAL" / "GLOBALB.BUN"
TRACKS = DISC / "TRACKS"
RECORDS_NAME = "afx_records.bin"

# ================================================================ the image

GP = 0x003358f0
G_PP = GP - 23528                 # AcidParticleSlotPool
G_GP = GP - 23524                 # AcidActiveGroupSlotPool
G_EP = GP - 23520                 # AcidEmitterSlotPool
G_NUM = GP - 23516                # NumAcidEmitters
G_EDL = GP - 23512                # EmitterDataList
G_SEED = GP - 23504               # AcidRandomSeed
FE = 0x002ef5e0                   # FrameEffects
WE = 0x002ef640                   # WorldEffects
SYS_SIZE = 96

STATIC_INIT = 0x0012a220
AFX_INIT = 0x00126d70
AFX_CLOSE = 0x00126e08
LOADER = 0x00126e50
UNLOADER = 0x00126f60
UPDATE_TEX = 0x00127078
GET_DATA = 0x00127120
GET_EMITTER = 0x00127198
COPY = 0x00127228
GET_EMITTERS = 0x001272e0
DELETE_EMITTERS = 0x00127368
SET_DATA = 0x001273c0
SET_DATA_HASH = 0x001273d8
SYS_CTOR = 0x00127418
ADD_AUTO = 0x001274a0
REMOVE_AUTO = 0x00127688
KILL_ALL = 0x001276a8
EMITTER_DEL = 0x00124e20
EMITTER_DEL2 = 0x0012a3f8
GROUP_DEL = 0x0012a258
TRIGGER = 0x00127700
UPDATE_IP = 0x001286a0
DO_STEP = 0x00128718
TRIGGER_FRAME = 560               # the direction's w at 204 of the frame
STEP_FRAME = 304                  # the control matrix at 0 of the frame
EMATH_INIT = 0x0011b138
EMATH_CTOR = 0x0011bf70           # 0x002dc400 = (0, 0, 0, 1)
G_FLOW = GP - 21420               # CurrentGameFlowState

B_NEW_POOL = 0x00257c10
B_DEL_POOL = 0x00257c48
B_OMALLOC = 0x00257c80
B_FREE_SLOT = 0x00257ca0
B_FREE = 0x00257850
B_MALLOC = 0x00257c60
B_IS_FULL = 0x00257d10
GET_TEXTURE_INFO = 0x001abf48
E_GET_VIEW = 0x00107c90
B_TICKER = 0x00250f38
B_TICKER_DIFF = 0x00250f48

CALL_LIMIT = 4000000

# The model's memory, above the image.
POOLS = 0x01000000                # the fake SlotPools, 64 bytes each
POOL_FLAGS = 20
ARENA = (0x01010000, 0x01020000, 0x01030000)
SLOT = (32, 28, 192)
NSLOT = (1000, 400, 600)
POOL_NAMES = ("AcidParticleSlotPool", "AcidActiveGroupSlotPool",
              "AcidEmitterSlotPool")
POOL_SHORT = ("pp", "gp", "ep")
LISTS = 0x01080000                # the script's lists, 8 bytes each
NLIST = 8
TEXS = 0x01090000                 # the textures
TEX_SIZE = 164
TEX_NAMEHASH = 32
NTEX = 512
NTXM = 64
VIEWS = 0x010c0000                # view i at VIEWS + 0x100 * i
VIEW_CAMERA = 56
CAMS = 0x010c1000                 # its camera at CAMS + 0x200 * i
CAM_POSITION = 64
NVIEW = 3
CARS = 0x010c2000                 # car k at CARS + 0x800 * k
CAR_VELOCITY = 112
NCAR = 2
TICK = 0x1234567
BUFS = 0x01100000                 # buffer k at BUFS + k * BUF_STRIDE
BUF_STRIDE = 0x100000
NBUF = 8
NCH = 8

DATA_SIZE = 544
EMIT_SIZE = 192
PATB = 0xa5
PAT = 0xa5a5a5a5
SEED0 = 0x23985727

CH_DATAS = 0x35021
CH_EMITTERS = 0x35020

# carrenderinfo.c's kCarFxNames, the groups CarRenderInfo asks
# afxGetEmitters for.
CARFX_NAMES = (
    "CARFX_NONE", "CARFX_DRIVE_OVER", "CARFX_DRIVE_OVER2",
    "CARFX_SKID_SMOKE", "CARFX_TIRE_SPEW", "CARFX_BOTTOM_OUT",
    "CARFX_DAM_RADIATOR", "CARFX_DAM_ENGINE", "CARFX_BLOWN_TIRE",
    "CARFX_DRIVE_ON_FLAT_TIRE", "CARFX_NITRO", "CARFX_EXHAUST_SMOKE",
    "CARFX_BREAK_SIDE_MIRROR_LEFT", "CARFX_BREAK_SIDE_MIRROR_RIGHT",
    "CARFX_BREAK_LICENSE_PLATE_FRONT", "CARFX_BREAK_LICENSE_PLATE_RIGHT",
    "CARFX_BREAK_HEADLIGHT_LEFT", "CARFX_BREAK_HEADLIGHT_RIGHT",
    "CARFX_BREAK_BRAKELIGHT_LEFT", "CARFX_BREAK_BRAKELIGHT_RIGHT",
    "CARFX_BREAK_WINDSHIELD", "CARFX_BREAK_WINDOW_REAR",
    "CARFX_BREAK_WINDOW_LEFT_FRONT", "CARFX_BREAK_WINDOW_LEFT_REAR",
    "CARFX_BREAK_WINDOW_RIGHT_FRONT", "CARFX_BREAK_WINDOW_RIGHT_REAR",
)


def fb(v):
    if isinstance(v, int):
        return v & M32
    return f_to_bits(v)


def fx(w):
    """A float's bits, with every NaN the one "nan"."""
    w &= M32
    if (w & 0x7f800000) == 0x7f800000 and (w & 0x7fffff):
        return "nan"
    return "%08x" % w


def h(v):
    return "%08x" % fb(v)


def xorshift(x):
    x ^= (x << 17) & M32
    x ^= x >> 13
    x ^= (x << 5) & M32
    return x & M32


def unxorshift(y):
    """The seed whose xorshift is y."""
    x = y
    for _ in range(7):
        x = y ^ ((x << 5) & M32)
    y = x
    for _ in range(3):
        x = y ^ (x >> 13)
    y = x
    for _ in range(2):
        x = y ^ ((x << 17) & M32)
    return x


# ================================================================= the disc


def _cstr(b):
    return b.split(b"\0")[0].decode("latin-1")


def _walk(d, o, end, out):
    while o + 8 <= end:
        cid, size = struct.unpack_from("<II", d, o)
        out.append((cid, o))
        if cid & 0x80000000:
            _walk(d, o + 8, o + 8 + size, out)
        o += 8 + size


class Disc(object):
    """The Acid packs of GLOBALB and the 30 tracks, as one table of
    records: files[f] is (name, first data, datas, first emitter,
    emitters)."""

    def __init__(self):
        paths = [GLOBALB] + sorted(TRACKS.glob("TRACKB[1-6][1-6].BUN"))
        if not GLOBALB.exists() or len(paths) != 31:
            raise SystemExit("afx_check needs extracted-retail's GLOBALB "
                             "and its 30 TRACKB files")
        self.files, self.datas, self.emits = [], [], []
        for p in paths:
            d = p.read_bytes()
            chunks = []
            _walk(d, 0, len(d), chunks)
            got = {}
            for cid, o in chunks:
                if cid not in (CH_DATAS, CH_EMITTERS):
                    continue
                hd = (o + 23) & ~15
                ver, n = struct.unpack_from("<iI", d, hd + 8)
                assert ver == (4 if cid == CH_DATAS else 5), p
                size = DATA_SIZE if cid == CH_DATAS else EMIT_SIZE
                assert cid not in got, p
                got[cid] = [d[hd + 16 + size * i:hd + 16 + size * (i + 1)]
                            for i in range(n)]
            df, ef = len(self.datas), len(self.emits)
            self.datas += got[CH_DATAS]
            self.emits += got[CH_EMITTERS]
            self.files.append((p.stem, df, len(got[CH_DATAS]), ef,
                               len(got[CH_EMITTERS])))

    def index(self, name):
        return [f[0] for f in self.files].index(name)

    def records(self):
        return (struct.pack("<ii", len(self.datas), len(self.emits))
                + b"".join(self.datas) + b"".join(self.emits))

    def _w(self, r, off):
        return struct.unpack_from("<I", r, off)[0]

    def data_name(self, i):
        return self._w(self.datas[i], 8)

    def data_tex(self, i):
        return self._w(self.datas[i], 12)

    def data_group(self, i):
        return self._w(self.datas[i], 16)

    def data_group_str(self, i):
        return _cstr(self.datas[i][496:544])

    def emit_name(self, i):
        return self._w(self.emits[i], 8)

    def emit_data(self, i):
        return self._w(self.emits[i], 12)

    def file_datas(self, f):
        _, df, dn, _, _ = self.files[f]
        return range(df, df + dn)

    def file_emits(self, f):
        _, _, _, ef, en = self.files[f]
        return range(ef, ef + en)

    def group_of_emitter(self, i, files):
        """The group of the data emitter i names, among those files', or 0
        when none of them has it."""
        want = self.emit_data(i)
        for f in files:
            for j in self.file_datas(f):
                if self.data_name(j) == want:
                    return self.data_group(j)
        return 0


# ============================================================ the scenarios


def chunk(disc, k, f, kind, mis=0, ver=None, first=0, n=None):
    """A CH line for file f's datas (D) or emitters (E), all of them or n
    from the first."""
    _, df, dn, ef, en = disc.files[f]
    if kind == "D":
        return "CH %d 35021 %d %d %d D %d" % (
            k, 4 if ver is None else ver, dn if n is None else n, mis,
            df + first)
    return "CH %d 35020 %d %d %d E %d" % (
        k, 5 if ver is None else ver, en if n is None else n, mis,
        ef + first)


def load(disc, k, f, mis=0):
    return [chunk(disc, k, f, "D", mis), chunk(disc, k, f, "E", mis),
            "LA %d" % k]


def all_groups(disc):
    seen, out = set(), []
    names = [disc.data_group_str(i) for i in range(len(disc.datas))]
    for s in list(CARFX_NAMES) + ["FE_EMITTER"] + names:
        g = bhash(s)
        if g not in seen:
            seen.add(g)
            out.append(g)
    return out


def s_boot(rnd, disc):
    """The boot: GLOBALB, then a track; the lookups, every group the
    cars and the frontend ask for, the copies; then the unloads and the
    close."""
    t12 = disc.index("TRACKB12")
    out = ["S", "D", "I", "D"]
    out += load(disc, 0, 0) + ["D", "T", "D", "T", "D"]
    out += load(disc, 1, t12) + ["T", "D"]
    files = (0, t12)
    picks = (list(disc.file_datas(0))[::9] + list(disc.file_datas(t12))[::3])
    for i in picks:
        n, g = disc.data_name(i), disc.data_group(i)
        out += ["GD %08x 0 null" % n, "GD %08x %08x null" % (n, g),
                "GD %08x %08x null" % (n, g ^ 1), "GD 0 %08x null" % g,
                "GD 0 %08x r" % g, "GD 0 %08x r" % g, "GD 0 %08x r" % g]
    n0 = disc.data_name(picks[0])
    out += ["GD 0 0 null", "GD 0 0 EDL.3", "GD 12345678 0 null",
            "GD 0 12345678 null", "GD %08x 0 EDL.0" % n0,
            "GD %08x 0 EDL.40" % n0, "GD %08x 0 EDL.500" % n0,
            "GD %08x 0 D0.0.5" % disc.data_name(9),
            "GD 0 %08x D1.0.2" % disc.data_group(picks[-1])]
    for i in list(disc.file_emits(0))[::7] + list(disc.file_emits(t12))[::4]:
        n, dn = disc.emit_name(i), disc.emit_data(i)
        g = disc.group_of_emitter(i, files)
        out += ["GE %08x 0 null" % n, "GE %08x 0 null" % dn,
                "GE %08x 0 r" % dn, "GE %08x %08x null" % (n, g),
                "GE %08x %08x null" % (n, g ^ 1), "GE 0 %08x null" % g,
                "GE 0 %08x r" % g, "GE 0 %08x r" % g]
    out += ["GE 0 0 null", "GE 0 0 WE.auto.2", "GE 12345678 0 null",
            "GE 0 12345678 WE.auto.5", "GE 0 %08x WE.auto.60" % g,
            "GE 0 %08x E0.1.3" % disc.data_group(0),
            "GE 0 %08x WE.auto.999" % g]
    groups = all_groups(disc)
    for j in range(0, len(groups), NLIST):
        part = groups[j:j + NLIST]
        for k, g in enumerate(part):
            out += ["NL %d" % k, "GS %d %08x" % (k, g)]
        out += ["GS 0 %08x" % part[-1]]
        out += ["DL %d" % k for k in range(len(part))]
        out += ["DS %d" % k for k in range(len(part))]
    out += ["NL 0", "GS 0 %08x" % bhash("FE_EMITTER"), "D", "DS 0"]
    out += ["CP E0.1.0", "DE r", "CP E1.1.0", "CP WE.auto.0",
            "CP WE.auto.151", "ED r 3", "CP null", "CP WE.auto.152", "D"]
    out += ["SH E0.1.0 %08x" % disc.data_name(list(disc.file_datas(t12))[3]),
            "DE E0.1.0"]
    out += ["UA 1", "D", "T", "UA 0", "D", "C", "D", "I", "D"]
    return out


def s_tracks(rnd, disc, tracks):
    """GLOBALB, then each track in turn: loaded, looked through, copied
    from, and unloaded."""
    out = ["S", "I"] + load(disc, 0, 0) + ["T"]
    for f in tracks:
        files = (0, f)
        out += ["BR 1"] + load(disc, 1, f) + ["T", "D"]
        for i in disc.file_datas(f):
            out += ["GD %08x 0 null" % disc.data_name(i),
                    "GD 0 %08x null" % disc.data_group(i)]
        groups = []
        for i in disc.file_datas(f):
            if disc.data_group(i) not in groups:
                groups.append(disc.data_group(i))
        for j, g in enumerate(groups[:NLIST]):
            out += ["NL %d" % j, "GS %d %08x" % (j, g), "DL %d" % j]
        for i in rnd.sample(list(disc.file_emits(f)), 4):
            g = disc.group_of_emitter(i, files)
            out += ["GE %08x %08x null" % (disc.emit_name(i), g),
                    "GE %08x 0 null" % disc.emit_data(i)]
        out += ["DS %d" % j for j in range(min(len(groups), NLIST))]
        out += ["UA 1"]
    out += ["D", "UA 0", "C", "D"]
    return out


CYCLES = (0.0, -0.0, 1.0, 2.5, 0x00000001, 0x007fffff, 0x80000001,
          0x7fc00000, 0x7f800000, 0xff800000, -3.0, 0x7f7fffff, 1e-30,
          0.016)
VARS = (0.0, 1.0, 0.5, 2.0, -1.0, 0x7fc00000, 0x7f800000, 0x00000003,
        1e30, 0.1)


def s_auto(rnd, disc):
    """AddAutoEmitter on every state, with and without a data, over
    cycles and variances at their edges, and seeds at theirs: emitters
    in a pack of version 6, which the loader passes over."""
    out = ["S", "I", "CH 0 35021 4 16 0 D 0", "L 0 0",
           "CH 0 35020 6 48 0 E 0", "L 0 1"]
    on = {}
    nxt = [0]

    def em(i):
        return "E0.1.%d" % i

    def case(state, data, rs, sysname, rc=0x3f800000, ec=0x40000000):
        i = nxt[0] % 48
        nxt[0] += 1
        lines = []
        if i in on:
            lines.append("RA %s %s" % (on.pop(i), em(i)))
        lines += ["PE %s st %d" % (em(i), state),
                  "PE %s d %s" % (em(i), data),
                  "PE %s rs %08x" % (em(i), rs),
                  "PE %s rc %s" % (em(i), h(rc)),
                  "PE %s ec %s" % (em(i), h(ec)),
                  "AA %s %s" % (sysname, em(i)), "DE %s" % em(i)]
        on[i] = sysname
        return lines

    def cyc(j, on_c, on_v, off_c, off_v):
        return ["PD D0.0.%d on %s" % (j, h(on_c)),
                "PD D0.0.%d onv %s" % (j, h(on_v)),
                "PD D0.0.%d off %s" % (j, h(off_c)),
                "PD D0.0.%d offv %s" % (j, h(off_v))]

    states = (0, 1, 2, 3, 4, 5, -1, 2147483647, -2147483648)
    # No data: DISABLED on the tail, whatever the state.
    for k, st in enumerate(states):
        out += case(st, "null", rnd.randrange(1, 1 << 32),
                    ("FE", "WE")[k & 1])
    # A data: each state, ON and OFF taking their own cycle.
    out += cyc(0, 1.5, 0.25, 4.0, 0.5)
    for k, st in enumerate(states):
        out += case(st, "D0.0.0", rnd.randrange(1, 1 << 32),
                    ("WE", "FE")[k & 1])
        out += case(st, "D0.0.0", 0, "FE")
    out += ["D"]
    # The cycles and the variances.
    j = 1
    for c in CYCLES:
        for v in rnd.sample(VARS, 5) + [0.0]:
            out += cyc(j, c, v, -2.0 if c == 2.5 else 3.5, 0.25)
            out += case(1, "D0.0.%d" % j, rnd.randrange(1, 1 << 32), "WE")
            out += cyc(j, 1.0, 0.75, c, v)
            out += case(0, "D0.0.%d" % j, rnd.randrange(1, 1 << 32), "FE")
            j = 1 + (j % 15)
    # AcidRandomSeed at the edges: a fraction that rounds to one, to zero,
    # and the seed that stays zero.
    out += cyc(5, 2.0, 0.5, 6.0, 1.0)
    for x in (0x7fffffff, 0xffffffff, 0x80000000, 0, 0x7fffffc0,
              0x7fffffbf, 0xffffffbf, 0x40000000, 1, 0x00ffffff,
              0x01000001):
        out += ["SEED %08x" % unxorshift(x)]
        out += case(1, "D0.0.5", 0, "WE")
        out += case(0, "D0.0.5", 0, "FE")
        out += case(3, "D0.0.5", 0, "WE")
    out += ["SEED 00000000"] + case(1, "D0.0.5", 0, "FE") + \
        case(0, "D0.0.5", 0, "WE")
    out += ["SEED %08x" % SEED0]
    # The emitter's own seed at the edges.
    for x in (0x7fffffff, 0xffffffc0, 0x80000000, 0x00000001, 0x7fffffbf,
              0xc0000000):
        out += case(1, "D0.0.5", unxorshift(x), "WE")
        out += case(0, "D0.0.5", unxorshift(x), "FE")
    for _ in range(30):
        out += ["SEED %08x" % rnd.randrange(1 << 32)]
        out += case(rnd.choice((0, 1, 1, 2, 3)), "D0.0.%d" % rnd.randrange(16),
                    rnd.choice((0, rnd.randrange(1 << 32))),
                    rnd.choice(("FE", "WE")))
    out += ["D"]
    for i in sorted(on):
        out += ["RA %s %s" % (on[i], em(i))]
    out += ["D"]
    return out


def s_versions(rnd, disc):
    """Every type and version the loaders see, counts of zero, and the
    header at each of the 16 offsets a chunk can sit at."""
    t12 = disc.index("TRACKB12")
    out = ["S", "I"]
    out += ["CH 0 80035000 4 3 0 D 0", "CH 0 80035010 5 3 4 E 0",
            "CH 0 35021 3 3 8 D 0", "CH 0 35021 5 3 12 D 3",
            "CH 0 35020 4 3 1 E 0", "CH 0 35020 6 3 2 E 3",
            "CH 0 35022 4 3 3 - 0", "CH 0 0 4 3 5 - 0"]
    out += ["LA 0", "D", "UA 0", "D"]
    out += ["CH 1 35021 -1 3 0 D 6", "CH 1 35020 -1 3 7 E 6",
            "CH 1 80035021 4 3 9 - 0", "CH 1 35021 4 0 10 D 0",
            "CH 1 35020 5 0 11 E 0", "CH 1 3502 4 3 13 - 0",
            "CH 1 135021 4 3 14 - 0", "CH 1 80035020 5 3 15 - 0"]
    out += ["LA 1", "D", "UA 1", "D"]
    out += ["CH 2 80035000 4 0 6 - 0", "CH 2 80035010 4 0 0 - 0",
            "CH 2 35021 0 2 0 D 0", "CH 2 35020 0 2 0 E 0",
            "CH 2 35021 2147483647 2 3 D 0", "CH 2 35020 -2147483648 2 3 E 0"]
    out += ["LA 2", "UA 2"]
    for mis in range(16):
        k = 3 + (mis % 5)
        out += ["BR %d" % k, chunk(disc, k, t12, "D", mis),
                chunk(disc, k, t12, "E", mis, first=2 * mis, n=2),
                "L %d 0" % k, "L %d 1" % k, "DE E%d.1.0" % k,
                "DE E%d.1.1" % k,
                "GD %08x 0 null" % disc.data_name(
                    list(disc.file_datas(t12))[mis])]
        out += ["D"] if mis % 4 == 0 else []
        out += ["U %d 1" % k, "U %d 0" % k]
    out += ["D"]
    return out


def s_copies(rnd, disc):
    """afxCopyEmitter with no pool, the pool failing, names at their
    length, no data; the deletes with every flag; the lists."""
    out = ["S", chunk(disc, 0, 0, "D"), chunk(disc, 0, 0, "E")]
    out += ["CP E0.1.0", "I", "LA 0"]
    out += ["CP E0.1.%d" % i for i in range(6)]
    out += ["ED r 3", "CP E0.1.6", "DE e5", "DE e0"]
    name = ("NEBULA_SELECT_CAR_" * 4)[:63]
    out += ["PE E0.1.7 nm %s" % name, "CP E0.1.7",
            "PE E0.1.8 nm %s" % name[:62], "CP E0.1.8",
            "PE E0.1.9 nm X", "CP E0.1.9", "PE E0.1.10 nmz 0", "CP E0.1.10"]
    out += ["PE E0.1.11 d null", "CP E0.1.11",
            "PE E0.1.12 d D0.0.40", "CP E0.1.12"]
    out += ["F ep 0", "CP E0.1.13", "CP E0.1.14", "F ep 2", "CP E0.1.13",
            "CP E0.1.14", "CP E0.1.15", "F ep -1", "CP E0.1.16"]
    for f in (0, 1, 2, 3, -1, -2, 5):
        out += ["CP E0.1.20", "ED r %d" % f, "CP E0.1.21", "ED2 r %d" % f]
    out += ["ED E0.1.30 0", "ED2 E0.1.31 1", "ED null 3", "ED2 null 1",
            "D"]
    out += ["NL 0", "GS 0 %08x" % bhash("GASPUMPA"),
            "GS 0 %08x" % bhash("GASPUMPA"), "DL 0", "DS 0", "DL 0", "DS 0"]
    out += ["NL 1", "F ep 3", "GS 1 %08x" % bhash("XETT_DEEPWATER_DRSL"),
            "F ep -1", "DL 1", "DS 1", "DL 1"]
    out += ["NL 2", "GS 2 0", "DL 2", "GS 2 12345678", "DL 2",
            "GS 2 %08x" % bhash("FE_EMITTER"), "DL 2"]
    out += ["F ep 0", "GS 2 %08x" % bhash("GASPUMPA"), "F ep -1", "DL 2"]
    out += ["CP E0.1.40", "AA FE r", "CP FE.auto.0", "DE r",
            "RA FE FE.auto.0", "ED r 3", "D"]
    out += ["DS 2", "D", "C", "D"]
    return out


def s_groups(rnd, disc):
    """Groups made as TriggerEmitter makes them, killed, deleted by hand,
    and left for the close."""
    t12 = disc.index("TRACKB12")
    out = ["S", "MG FE null 2", "K FE", "I"]
    out += load(disc, 0, 0) + load(disc, 1, t12)
    out += ["MG FE WE.auto.0 3", "MG FE WE.auto.1 0", "MG WE WE.auto.2 5",
            "MG WE null 1", "MG FE WE.auto.150 2", "D"]
    out += ["K FE", "D", "K FE"]
    out += ["F pp 2", "MG WE WE.auto.3 6", "F pp -1", "F gp 0",
            "MG WE WE.auto.4 2", "F gp -1", "D"]
    out += ["GX WE.act.0 0", "D", "GX WE.act.1 2", "GX WE.act.2 1",
            "GX null 1", "D", "K WE", "D"]
    out += ["MG FE WE.auto.9 40", "MG FE WE.auto.10 1", "K FE", "D"]
    out += ["MG FE WE.auto.5 4", "MG WE WE.auto.6 3", "MG WE WE.auto.7 0",
            "C", "D", "MG FE null 1", "K FE", "C", "D", "I", "D",
            "MG FE WE.auto.8 2", "D", "K FE", "D"]
    return out


def s_textures(rnd, disc):
    """afxUpdateTextures over every answer GetTextureInfo can give, and
    over textures changed under it."""
    out = ["S", "I", "CH 0 35021 4 40 0 D 0", "L 0 0"]
    seen = []
    for i in range(40):
        t = disc.data_tex(i)
        if t not in seen:
            seen.append(t)
    for k, t in enumerate(seen[:40]):
        out += ["TXM %08x %d" % (t, 1 if k < 2 else (t + k) % 3)]
    out += ["T", "D", "T", "D"]
    out += ["PD D0.0.0 th %08x" % (disc.data_tex(0) ^ 0x100), "T", "D",
            "PD D0.0.1 tex null", "PD D0.0.2 tex t0", "PD D0.0.3 tex t1",
            "PD D0.0.4 th %08x" % seen[1], "PD D0.0.4 tex t1",
            "PD D0.0.5 th %08x" % seen[0], "PD D0.0.5 tex t1",
            "T", "D", "PD D0.0.6 th 0", "T", "D", "T"]
    # The default rule (the hash mod 3) over GLOBALB's other datas.
    out += ["CH 0 35021 4 71 0 D 40", "L 0 1", "T", "D", "T", "D"]
    return out


def s_misc(rnd, disc):
    """Both SetEmitterData, the systems constructed again, the static
    constructor run twice, and track emitters loaded with no datas."""
    t12 = disc.index("TRACKB12")
    d3 = disc.data_name(3)
    out = ["S", "I", "CH 0 35021 4 10 0 D 0", "L 0 0",
           "CH 0 35020 6 10 0 E 0"]
    out += ["SD E0.1.0 D0.0.3", "DE E0.1.0", "SD E0.1.0 null", "DE E0.1.0",
            "SH E0.1.1 %08x" % d3, "DE E0.1.1", "SH E0.1.1 0",
            "SH E0.1.1 12345678", "DE E0.1.1", "SD null D0.0.1", "SH null 0",
            "PE E0.1.2 d null", "SH E0.1.2 0", "DE E0.1.2"]
    out += ["CT FE", "CT WE", "D", "S", "D"]
    # The track's emitters with nothing to name: DISABLED, no data, and
    # passed over by every lookup.
    out += ["BR 1", chunk(disc, 1, t12, "E"), "L 1 0", "D"]
    for i in list(disc.file_emits(t12))[:6]:
        g = disc.group_of_emitter(i, (t12,))
        out += ["GE %08x 0 null" % disc.emit_data(i),
                "GE %08x %08x null" % (disc.emit_name(i), g),
                "GE 0 %08x null" % g]
    out += [chunk(disc, 1, t12, "D"), "L 1 1", "T"]
    for i in list(disc.file_emits(t12))[:6]:
        g = disc.group_of_emitter(i, (t12,))
        out += ["GE %08x 0 null" % disc.emit_data(i), "GE 0 %08x null" % g]
    out += ["U 1 0", "U 1 1", "D"]
    return out


def s_edges(rnd, disc):
    """The lookups with both hashes zero, over a data whose group is
    zero; copies from pools that do not clear; and names with bytes after
    their terminator, which no string op reads."""
    n0 = disc.data_name(0)
    out = ["S", "I"] + load(disc, 0, 0)
    out += ["GD 0 0 null", "GE 0 0 null", "PD D0.0.0 gh 0", "GD 0 0 null",
            "GD 0 0 EDL.5", "GD %08x 0 null" % n0, "GD 0 0 r"]
    out += ["SD WE.auto.0 D0.0.0", "SD WE.auto.7 D0.0.0", "GE 0 0 null",
            "GE 0 0 WE.auto.0", "PE WE.auto.0 nh 12345678",
            "GE 12345678 0 null", "GE 12345678 0 WE.auto.3",
            "PE WE.auto.7 nh %08x" % n0, "GE %08x 0 null" % n0,
            "GE %08x 0 r" % n0, "GE 0 0 r"]
    out += ["PF ep d", "CP E0.1.0", "CP E0.1.1", "PF ep 0", "CP E0.1.2",
            "PF ep f", "CP E0.1.3", "PF pp 0", "PF gp f",
            "MG FE WE.auto.1 3", "D", "K FE", "D"]
    out += ["PE E0.1.4 nmg AB", "DE E0.1.4", "CP E0.1.4",
            "PE E0.1.5 nmg X", "CP E0.1.5",
            "PE E0.1.6 nmg %s" % ("Q" * 62), "CP E0.1.6",
            "PE E0.1.8 nmg %s" % ("R" * 61), "CP E0.1.8",
            "PF ep d", "PE E0.1.9 nmg Z", "CP E0.1.9", "CP r", "D"]
    return out


def s_fuzz(rnd, disc, n, track):
    """Any order of the ops over GLOBALB and a track. It knows what "r"
    holds, so that it never adds an emitter that is on a list, never
    names an emitter it deleted, and never unloads."""
    out = ["S", "I"] + load(disc, 0, 0) + load(disc, 1, track) + ["T"]
    files = (0, track)
    datas = list(disc.file_datas(0)) + list(disc.file_datas(track))
    emits = list(disc.file_emits(0)) + list(disc.file_emits(track))
    dnames = [disc.data_name(i) for i in datas]
    groups = sorted({disc.data_group(i) for i in datas})
    enames = [disc.emit_name(i) for i in emits]
    texs = sorted({disc.data_tex(i) for i in datas})
    count = {"FE": 0, "WE": len(emits)}
    lists = set()
    txm = 0
    r = ("null",)

    def pick(pool):
        return rnd.choice((0, rnd.choice(pool), rnd.choice(pool),
                           rnd.randrange(1 << 32)))

    def auto(sysname):
        return "%s.auto.%d" % (sysname, rnd.randrange(count[sysname] + 3))

    def emitter_ref():
        k = rnd.random()
        if k < 0.6 or count["FE"] == 0:
            return auto("WE")
        return auto("FE")

    for _ in range(n):
        k = rnd.random()
        if k < 0.11:
            after = rnd.choice(("null", "EDL.%d" % rnd.randrange(len(datas) + 4),
                                "r" if r[0] == "data" else "null"))
            out.append("GD %08x %08x %s" % (pick(dnames), pick(groups), after))
            r = ("data",)
        elif k < 0.22:
            after = rnd.choice(("null", auto("WE"),
                                "r" if r == ("linked", "WE") else "null"))
            out.append("GE %08x %08x %s" % (pick(enames + dnames),
                                            pick(groups), after))
            r = ("linked", "WE")
        elif k < 0.30:
            src = rnd.choice((emitter_ref(), emitter_ref(),
                              "r" if r[0] in ("free", "linked") else
                              emitter_ref()))
            out.append("CP %s" % src)
            r = ("free",)
        elif k < 0.37:
            if r[0] == "free":
                s = rnd.choice(("FE", "WE"))
                out.append("AA %s r" % s)
                count[s] += 1
                r = ("linked", s)
        elif k < 0.43:
            if r[0] == "linked" and rnd.random() < 0.3:
                out.append("RA %s r" % r[1])
                count[r[1]] = max(0, count[r[1]] - 1)
            else:
                s = "FE" if count["FE"] and rnd.random() < 0.6 else "WE"
                out.append("RA %s %s" % (s, auto(s)))
                count[s] = max(0, count[s] - 1)
            r = ("free",)
        elif k < 0.47:
            if r[0] == "free":
                out.append("%s r %d" % (rnd.choice(("ED", "ED2")),
                                        rnd.choice((0, 1, 2, 3, 3, -1))))
                r = ("dead",)
        elif k < 0.53:
            if r[0] == "free":
                f = rnd.choice(("st", "rs", "rc", "ec", "de", "nh", "dh", "d",
                                "nm", "nmg"))
                if f == "st":
                    v = "%d" % rnd.choice((0, 1, 2, 3, 4, -1))
                elif f in ("rs", "de", "nh", "dh"):
                    v = "%08x" % rnd.choice((0, rnd.randrange(1 << 32)))
                elif f in ("rc", "ec"):
                    v = h(rnd.uniform(-10, 10))
                elif f == "d":
                    v = rnd.choice(("null", "EDL.%d" % rnd.randrange(len(datas))))
                else:
                    v = "N%x" % rnd.randrange(1 << 40)
                out.append("PE r %s %s" % (f, v))
        elif k < 0.57:
            tgt = rnd.choice((emitter_ref(), "r" if r[0] == "free"
                              else emitter_ref()))
            if rnd.random() < 0.5:
                out.append("SD %s %s" % (tgt, rnd.choice((
                    "null", "EDL.%d" % rnd.randrange(len(datas) + 2)))))
            else:
                out.append("SH %s %08x" % (tgt, pick(dnames)))
        elif k < 0.70:
            j = rnd.randrange(NLIST)
            if j not in lists:
                out.append("NL %d" % j)
                lists.add(j)
            else:
                c = rnd.random()
                if c < 0.6:
                    out.append("GS %d %08x" % (j, rnd.choice(groups + [0])))
                elif c < 0.85:
                    out.append("DS %d" % j)
                else:
                    out.append("DL %d" % j)
        elif k < 0.77:
            s = rnd.choice(("FE", "WE"))
            e = rnd.choice(("null", emitter_ref(), emitter_ref()))
            out.append("MG %s %s %d" % (s, e, rnd.randrange(9)))
        elif k < 0.81:
            out.append("K %s" % rnd.choice(("FE", "WE")))
        elif k < 0.85:
            out.append("T")
        elif k < 0.87:
            if txm < 60:
                out.append("TXM %08x %d" % (rnd.choice(texs), rnd.randrange(3)))
                txm += 1
        elif k < 0.89:
            out.append("SEED %08x" % rnd.choice((0, rnd.randrange(1 << 32))))
        elif k < 0.95:
            out.append("DE %s" % rnd.choice((emitter_ref(), "r"
                                             if r[0] in ("free", "linked")
                                             else emitter_ref())))
        elif k < 0.96:
            out.append("D")
        elif k < 0.965:
            out.append("CT FE")
            count["FE"] = 0
            if r == ("linked", "FE"):
                r = ("dead",)
        else:
            out.append("GD 0 %08x null" % rnd.choice(groups))
            r = ("data",)
    out += ["D"]
    return out


# ------------------------------------------------- TriggerEmitter, DoTimeStep

DT30 = h(1.0 / 30)
DTS = (1.0 / 30, 1.0 / 60, 0.1, 0.5, -0.25, -1.0, 0.0, -0.0, 2.0)

# What the scripts write into a data, at its retail offset: the bytes and
# the floats TriggerEmitter and DoTimeStep read, over values that keep the
# emission loop short (the rate stays at or above zero and below 300 a
# second).
DATA_MODS = (
    ("b", 24, (0, 1)),                          # SpreadAsDisc
    ("b", 25, (0, 1, 2, 3)),                    # ContactSheetW
    ("b", 26, (0, 1, 2, 3)),                    # ContactSheetH
    ("b", 27, (0, 10, 15, 30, 127, 200)),       # AnimFPS
    ("b", 28, (0, 1, 2)),                       # RandomStartFrame
    ("b", 29, (0, 1)),                          # RandomRotationDirection
    ("b", 30, (0, 1)),                          # MotionLive
    ("w", 48, (0.0, 0.5, 1.0, 5.0, 30.0, 200.0)),       # NumParticles
    ("w", 52, (0.0, 0.25, 0.5, 1.0)),
    ("w", 56, (0.05, 0.5, 2.0, 10.0, 33.0, 70.0)),      # Life
    ("w", 60, (0.0, 0.25, 0.7)),
    ("w", 64, (0.0, 1.0, 10.0, 275.0, 600.0)),          # Speed
    ("w", 68, (0.0, 0.5, 1.0)),
    ("w", 72, (0.0, 15.0, 360.0, 720.0)),               # InitialAngleRange
    ("w", 76, (0.0, 30.0, 180.0, 359.0, 720.0)),        # SpreadAngle
    ("w", 80, (0.0, 0.1, 0.5, 1.0, 1.5)),               # MotionInherit
    ("w", 84, (0.0, 0.3, 1.0)),
    ("w", 96, (0.0, 1.5, -3.0)),                        # VolumeCenter
    ("w", 100, (0.0, 1.5, -3.0)),
    ("w", 104, (0.0, 1.5, -3.0)),
    ("w", 112, (0.0, 2.0, 10.0)),                       # VolumeExtent
    ("w", 116, (0.0, 2.0, 10.0)),
    ("w", 120, (0.0, 2.0, 10.0)),
    ("w", 128, (50.0, 150.0, 5000.0, 0.0)),             # FarClip
    ("w", 132, (0.0, -10.0, 20.0, -0.05)),              # Gravity
    ("w", 136, (0.0, 0.02, 0.6, -0.05)),                # Drag
)


def pd(ref, kind, off, v):
    return "PD %s %s %d %s" % (ref, kind, off, "%02x" % v if kind == "b"
                               else h(v))


def data_mods(rnd, ref, n):
    out = []
    for kind, off, vals in rnd.sample(DATA_MODS, n):
        out.append(pd(ref, kind, off, rnd.choice(vals)))
    return out


def emit_pos(disc, i):
    return struct.unpack_from("<4f", disc.emits[i], 96)


def cam(v, x, y, z, w=1.0):
    return "CAM %d %s %s %s %s" % (v, h(x), h(y), h(z), h(w))


def cam_at(disc, v, i, dx=0.0):
    x, y, z, w = emit_pos(disc, i)
    return cam(v, x + dx, y, z, w)


def rot_rows(ref, a, b):
    """LocalWorld's rows 0 to 2: a turn of a about z, then b about x."""
    ca, sa, cb, sb = math.cos(a), math.sin(a), math.cos(b), math.sin(b)
    rows = ((ca, sa, 0.0, 0.0), (-sa * cb, ca * cb, sb, 0.0),
            (sa * sb, -ca * sb, cb, 0.0))
    return ["PE %s w %d %s" % (ref, 48 + 16 * r + 4 * c, h(rows[r][c]))
            for r in range(3) for c in range(4)]


def glob_data(disc, i):
    """The D0.0 name of GLOBALB emitter i's data."""
    want = disc.emit_data(i)
    for j in disc.file_datas(0):
        if disc.data_name(j) == want:
            return "D0.0.%d" % j
    raise SystemExit("emitter %d has no data in GLOBALB" % i)


def s_interest(rnd, disc):
    """UpdateInterestPoints with each view's camera there or not, into
    each system."""
    out = ["S", "UIP WE", "UIP FE"]
    out += [cam(0, 1.0, 2.0, 3.0, 4.0), "UIP WE", "D"]
    out += [cam(1, -5.0, 0.5, 1e9, -0.0), cam(2, 7.0, 0x7fc00000, 0.0, 1.0),
            "UIP FE", "UIP WE"]
    out += ["CAM 1 null", cam(0, 9.0, 9.0, 9.0, 9.0), "UIP FE",
            "CAM 0 null", "CAM 2 null", cam(1, 3.0, 2.0, 1.0, 0.0), "UIP FE",
            "CAM 1 null", "UIP WE", "D"]
    return out


def s_trigger(rnd, disc):
    """TriggerEmitter at its edges, on copies of GLOBALB's emitters: far
    and near, ON and not, bursts, the cycle's end, a countdown left over,
    the last group kept, made again for another car, and kept when the
    pool is full; DontEmit and the particles' pool running out. Then each
    of GLOBALB's emitters, its data changed, from one view or another."""
    out = ["S", "I"] + load(disc, 0, 0)
    d0 = glob_data(disc, 0)
    fc = struct.unpack_from("<f", disc.datas[int(d0.split(".")[2])], 128)[0]
    far = [cam(v, 1e4 * (v + 1), 0.0, 0.0) for v in range(3)]
    # e0 at the origin; each view at its FarClip, which is not near, and
    # just inside it.
    out += far + ["UIP WE"]
    out += ["CP E0.1.0", "PE r st 1", "PE r w 96 0", "PE r w 100 0",
            "PE r w 104 0", "TR WE r %s null" % DT30]
    for v in (1, 2, 0):
        out += [cam(v, fc, 0.0, 0.0), "UIP WE", "TR WE e0 %s null" % DT30,
                cam(v, 0.0, -fc * 0.999, 0.0), "UIP WE",
                "TR WE e0 %s null" % DT30, far[v], "UIP WE"]
    # Inside FarClip across x and y, past it with z.
    out += [cam(0, fc * 0.6, fc * 0.6, fc * 0.6), "UIP WE",
            "TR WE e0 %s null" % DT30, far[0], "UIP WE"]
    out += [cam(1, 0.5, 0.0, 0.0), "UIP WE", "TR WE e0 %s null" % DT30,
            "DP WE",
            "TR WE e0 %s null" % DT30, "TR WE e0 %s c0" % DT30,
            "TR WE e0 %s c0" % DT30, "DP WE", "D"]
    out += ["PE e0 st 0", "TR WE e0 %s null" % DT30,
            "TR WE e0 %s null" % h(-0.5), "DP WE"]
    for st in (2, 3, -1, 4):
        out += ["PE e0 st %d" % st, "TR WE e0 %s null" % DT30,
                "TR WE e0 %s c1" % h(-0.1)]
    out += ["PE e0 st 1", "PE e0 rc %s" % h(0.01),
            "TR WE e0 %s null" % h(0.1), "PE e0 rc %s" % h(5.0),
            "TR WE e0 %s null" % h(0.1), "PE e0 rc %s" % h(-1.0),
            "TR WE e0 %s null" % h(0.1), "PE e0 rc 0",
            "PE e0 ec %s" % h(2.0), "TR WE e0 %s null" % DT30,
            "PE e0 ec %s" % h(0.05), "TR WE e0 %s null" % h(0.2),
            "PE e0 ec %s" % h(-3.0), "TR WE e0 %s null" % h(0.2), "DP WE"]
    # DontEmit draws and keeps nothing, and its new group is freed.
    out += ["PE e0 ec 0", "PE e0 de 1", "TR WE e0 %s c1" % h(0.25),
            "DE e0", "PE e0 de 0", "TR WE e0 %s c1" % DT30, "DP WE"]
    # A full group pool: the last group, whoever's car it has; none.
    out += ["F gp 0", "TR WE e0 %s c0" % h(0.2), "F gp -1", "DP WE",
            "CP E0.1.1", "PE r st 1", "F gp 0", "TR WE r %s null" % h(0.5),
            "F gp -1", "DE r"]
    # The particles' pool running out half way.
    out += ["F pp 2", "TR WE e0 %s null" % h(-1.0), "F pp -1",
            "F pp 0", "TR WE e0 %s null" % h(-1.0), "F pp -1", "DP WE", "D"]
    out += ["K WE", "D"]
    # The odd steps.
    for dt in (0x7fc00000, 0xffc00000, 1e-30, -1e-30, 0x00000001):
        out += ["PE e0 ec 0", "PE e0 rc 0", "TR WE e0 %s null" % h(dt)]
    out += ["DP WE", "K WE"]
    # Each of GLOBALB's emitters.
    views = (1, 2, 0)
    for k, i in enumerate(disc.file_emits(0)):
        dref = glob_data(disc, i)
        v = views[k % 3]
        out += ["CP E0.1.%d" % i, "PE r st %d" % rnd.choice((1, 1, 1, 0))]
        if k % 4 == 1:
            out += data_mods(rnd, dref, rnd.randrange(1, 8))
        if k % 5 == 2:
            out += rot_rows("r", rnd.uniform(-3, 3), rnd.uniform(-1.5, 1.5))
        if k % 3 == 0:
            out += ["PE r w %d %s" % (112 + 4 * c, h(rnd.choice((0.0, 5.0,
                                                                 -20.0))))
                    for c in range(3)]
        out += ["CAM %d null" % u for u in views if u != v]
        out += [cam_at(disc, v, i, rnd.choice((0.0, 0.0, 30.0))), "UIP WE"]
        car = rnd.choice(("null", "c0", "c1"))
        for _ in range(rnd.randrange(1, 4)):
            out += ["TR WE r %s %s" % (h(rnd.choice(DTS)), car)]
        out += ["DP WE", "K WE", "ED r 3"]
    out += ["D"]
    return out


def s_step(rnd, disc):
    """DoTimeStep over a track's ON emitters, with the camera among them
    and then elsewhere; the frontend's bases made again from every data's
    keys; the ticker's difference."""
    t12 = disc.index("TRACKB12")
    em = list(disc.file_emits(t12))
    out = ["S", "I"] + load(disc, 0, 0) + load(disc, 1, t12) + ["T"]
    out += [cam_at(disc, 1, em[0])]
    for k in range(48):
        out.append("DT WE %s" % DT30)
        if k % 12 == 11:
            out += ["DP WE"]
    out += ["D", "CAM 1 null", cam_at(disc, 2, em[17], 20.0)]
    for dt in (1.0 / 60, 0.1, 0.5, 1.0 / 30, 2.0, 1.0 / 30, 0.0, 1.0 / 30):
        out += ["DT WE %s" % h(dt)]
    out += ["DP WE", "D"]
    # The frontend's state: each data's bases.
    out += ["FS 3", "DT FE %s" % DT30]
    out += ["DD EDL.%d" % j for j in range(0, 150, 7)]
    out += ["FS 2", "PD D0.0.4 w 144 %s" % h(0.5), "DT FE %s" % DT30,
            "DD EDL.4", "FS 3", "DT FE %s" % DT30, "DD EDL.4"]
    # Keys that are not a cubic's: two the same.
    out += ["PD D0.0.5 w 148 0", "DT FE %s" % DT30, "DD EDL.5", "FS 0",
            "DT WE %s" % DT30, "DP WE", "K WE", "DT WE %s" % DT30, "D"]
    return out


def s_physics(rnd, disc):
    """The particles' step: frames turning at each rate and sheet, drag
    and gravity, a car's motion, lives at their edges, and particles that
    do not move."""
    out = ["S", "I"] + load(disc, 0, 0)
    out += ["CV 0 %s %s %s" % (h(10.0), h(-2.0), h(5.0)),
            "CV 1 %s %s %s" % (h(-30.0), h(0.0), h(1.0))]
    cases = [
        [("b", 30, 1), ("w", 80, 0.5)],
        [("b", 30, 1), ("w", 80, 0.0)],
        [("b", 30, 1), ("w", 80, 1.0), ("w", 84, 0.3)],
        [("b", 27, 15), ("b", 25, 2), ("b", 26, 2), ("b", 28, 1)],
        [("b", 27, 30), ("b", 25, 3), ("b", 26, 1)],
        [("b", 27, 127), ("b", 25, 0), ("b", 26, 0)],
        [("b", 27, 200), ("b", 25, 1), ("b", 26, 3), ("b", 28, 1)],
        [("w", 132, -10.0), ("w", 136, 0.6)],
        [("w", 132, 20.0), ("w", 136, -0.05)],
        [("w", 64, 0.0), ("w", 68, 0.0), ("w", 132, 0.0), ("w", 80, 0.0)],
        [("w", 56, 33.0), ("w", 60, 0.0)],
        [("w", 56, 70.0), ("w", 60, 0.25)],
        [("w", 56, 0.05), ("w", 60, 0.7)],
        [("w", 56, 1.0 / 30), ("w", 60, 0.0)],
        [("w", 64, 600.0), ("w", 68, 1.0)],
        [("w", 64, 275.0), ("w", 76, 359.0), ("b", 24, 1)],
    ]
    emits = list(disc.file_emits(0))
    for k, mods in enumerate(cases):
        i = emits[(k * 7) % len(emits)]
        dref = glob_data(disc, i)
        out += [pd(dref, kind, off, v) for kind, off, v in mods]
        out += ["PD %s w 48 %s" % (dref, h(rnd.choice((5.0, 30.0)))),
                "PD %s w 128 %s" % (dref, h(5000.0))]
        out += ["CP E0.1.%d" % i, "PE r st 1", cam_at(disc, 1, i), "UIP WE"]
        car = ("c0", "null", "c1")[k % 3]
        out += ["TR WE r %s %s" % (h(0.5), car), "DP WE"]
        for s in range(12):
            out += ["DT WE %s" % h((1.0 / 30, 1.0 / 60, 0.1)[s % 3])]
            if s % 4 == 3:
                out += ["DP WE"]
        out += ["K WE", "ED r 3"]
    out += ["D"]
    return out


def s_cycles(rnd, disc):
    """The auto emitters' cycles: ON and OFF turning over, cycles of zero
    that never do, variances; and the walk stopping at the first emitter
    that is neither, after its own turn."""
    out = ["S", "I"] + load(disc, 0, 0) + [cam(0, 0.0, 0.0, 0.0)]
    cyc = ((0.1, 0.5, 0.2, 0.25), (0.0, 0.0, 0.3, 0.0), (0.05, 0.0, 0.0, 0.0),
           (1.0 / 30, 1.0, 1.0 / 30, 1.0), (0.5, 2.0, 0.07, 0.5))
    emits = list(disc.file_emits(0))
    for k, (on, onv, off, offv) in enumerate(cyc):
        i = emits[3 + 11 * k]
        dref = glob_data(disc, i)
        out += ["PD %s on %s" % (dref, h(on)), "PD %s onv %s" % (dref, h(onv)),
                "PD %s off %s" % (dref, h(off)),
                "PD %s offv %s" % (dref, h(offv)),
                "PD %s w 128 %s" % (dref, h(5000.0)),
                "PD %s w 48 %s" % (dref, h(10.0)),
                "PD %s w 56 %s" % (dref, h(0.2))]
        out += ["CP E0.1.%d" % i, "PE r st %d" % (k & 1), "PE r rs 0",
                "PE r w 96 0", "PE r w 100 0", "PE r w 104 0", "AA FE r"]
    out += ["D"]
    for s in range(40):
        out += ["DT FE %s" % h((1.0 / 30, 0.05, 1.0 / 60, 0.2)[s % 4])]
        if s % 10 == 9:
            out += ["D", "DP FE"]
    # The walk's stop.
    for st in (3, 2, -1, 5, 1):
        out += ["PE FE.auto.1 st %d" % st, "DT FE %s" % DT30,
                "DT FE %s" % h(0.3), "D"]
    out += ["PE FE.auto.0 st 4", "DT FE %s" % DT30, "D", "K FE", "D"]
    return out


def s_nebula(rnd, disc):
    """The car select's nebula, as the frontend runs it: a copy of
    XE_SelectCarNebula, ON in FrameEffects, the frontend's camera at it,
    and the frontend's state."""
    out = ["S", "I"] + load(disc, 0, 0)
    neb = [i for i in disc.file_emits(0)
           if _cstr(disc.emits[i][128:192]) == "XE_SelectCarNebula"]
    assert len(neb) == 1
    i = neb[0]
    out += ["CP E0.1.%d" % i, "PE r st 1", "AA FE r", "D",
            cam(0, 0.0, 0.5, 1.5), "FS 3"]
    for s in range(120):
        out += ["DT FE %s" % DT30]
        if s % 30 == 29:
            out += ["DP FE", "DD %s" % glob_data(disc, i)]
    out += ["D", "FS 0"]
    for s in range(30):
        out += ["DT FE %s" % h(1.0 / 60 if s & 1 else 0.05)]
    out += ["DP FE", "D"]
    return out


def s_fx_fuzz(rnd, disc, n, track):
    """TriggerEmitter and DoTimeStep in any order, with the data and the
    emitters changed under them, cameras moved and cars driven. It never
    gives an emitter on a list a NULL data, never adds one twice, and
    keeps each emission's rate in bounds."""
    out = ["S", "I"] + load(disc, 0, 0) + load(disc, 1, track) + ["T"]
    datas = ["D0.0.%d" % j for j in disc.file_datas(0)]
    datas += ["D1.0.%d" % j for j in range(disc.files[track][2])]
    gl = list(disc.file_emits(0))
    tr = list(disc.file_emits(track))
    count = {"FE": 0, "WE": len(gl) + len(tr)}
    copies = []
    free = []
    r_free = False

    def auto(s):
        return "%s.auto.%d" % (s, rnd.randrange(max(1, count[s])))

    def emitter():
        k = rnd.random()
        if copies and k < 0.4:
            return rnd.choice(copies)
        if count["FE"] and k < 0.6:
            return auto("FE")
        return auto("WE")

    for _ in range(n):
        k = rnd.random()
        if k < 0.08:
            i = rnd.choice(gl + tr)
            out += ["CP %s" % ("E0.1.%d" % (i - gl[0]) if i in gl
                               else "E1.1.%d" % (i - tr[0]))]
            r_free = True
        elif k < 0.13:
            if r_free:
                s = rnd.choice(("FE", "WE"))
                out += ["PE r st %d" % rnd.choice((0, 1, 1, 2, 3)),
                        "AA %s r" % s]
                count[s] += 1
                r_free = False
        elif k < 0.33:
            s = rnd.choice(("FE", "WE"))
            e = "r" if r_free and rnd.random() < 0.5 else emitter()
            out += ["TR %s %s %s %s" % (s, e, h(rnd.choice(DTS)),
                                        rnd.choice(("null", "c0", "c1")))]
        elif k < 0.50:
            dt = rnd.choice((1.0 / 30, 1.0 / 30, 1.0 / 60, 0.1, 0.0, 0.5))
            out += ["DT %s %s" % (rnd.choice(("FE", "WE")), h(dt))]
        elif k < 0.60:
            e = "r" if r_free and rnd.random() < 0.5 else emitter()
            f = rnd.choice(("st", "rc", "ec", "rs", "de", "pos", "iv", "rot"))
            if f == "st":
                out += ["PE %s st %d" % (e, rnd.choice((0, 1, 1, 2, 3, -1)))]
            elif f in ("rc", "ec"):
                out += ["PE %s %s %s" % (e, f, h(rnd.choice(
                    (0.0, 0.01, 0.5, 3.0, -1.0))))]
            elif f in ("rs", "de"):
                out += ["PE %s %s %08x" % (e, f, rnd.choice(
                    (0, 1, rnd.randrange(1 << 32))))]
            elif f == "pos":
                out += ["PE %s w %d %s" % (e, 96 + 4 * c, h(rnd.uniform(
                    -50, 50))) for c in range(3)]
            elif f == "iv":
                out += ["PE %s w %d %s" % (e, 112 + 4 * c, h(rnd.uniform(
                    -30, 30))) for c in range(3)]
            else:
                out += rot_rows(e, rnd.uniform(-3, 3), rnd.uniform(-1.5, 1.5))
        elif k < 0.70:
            out += data_mods(rnd, rnd.choice(datas), rnd.randrange(1, 4))
        elif k < 0.73:
            d = rnd.choice(datas)
            out += ["PD %s %s %s" % (d, f, h(rnd.choice((0.0, 0.05, 0.5, 2.0))))
                    for f in ("on", "off")]
        elif k < 0.80:
            v = rnd.randrange(3)
            if rnd.random() < 0.2:
                out += ["CAM %d null" % v]
            elif rnd.random() < 0.5:
                out += [cam(v, rnd.uniform(-50, 50), rnd.uniform(-50, 50),
                            rnd.uniform(-5, 5))]
            else:
                out += [cam_at(disc, v, rnd.choice(gl + tr),
                               rnd.uniform(-20, 20))]
        elif k < 0.83:
            out += ["CV %d %s %s %s" % (rnd.randrange(2), h(rnd.uniform(-40, 40)),
                                         h(rnd.uniform(-40, 40)),
                                         h(rnd.uniform(-5, 5)))]
        elif k < 0.85:
            out += ["FS %d" % rnd.choice((0, 0, 0, 3, 1))]
        elif k < 0.87:
            out += ["UIP %s" % rnd.choice(("FE", "WE"))]
        elif k < 0.89:
            out += ["K %s" % rnd.choice(("FE", "WE"))]
        elif k < 0.96:
            out += ["DP %s" % rnd.choice(("FE", "WE"))]
        elif k < 0.98:
            out += ["DD %s" % rnd.choice(datas)]
        else:
            out += ["D"]
        if r_free and out[-1].startswith("CP"):
            copies.append("e%d" % len(copies))
    out += ["FS 0", "DP FE", "DP WE", "D"]
    return out


def script(disc):
    rnd = random.Random(0xac1dfe)
    sc = [s_boot(rnd, disc)]
    tracks = list(range(1, len(disc.files)))
    for i in range(0, len(tracks), 6):
        sc.append(s_tracks(rnd, disc, tracks[i:i + 6]))
    sc += [s_auto(rnd, disc), s_versions(rnd, disc), s_copies(rnd, disc),
           s_groups(rnd, disc), s_textures(rnd, disc), s_misc(rnd, disc),
           s_edges(rnd, disc)]
    for n, t in ((400, "TRACKB12"), (1200, "TRACKB24"), (2500, "TRACKB61")):
        sc.append(s_fuzz(rnd, disc, n, disc.index(t)))
    # TriggerEmitter and DoTimeStep, on a generator of their own so that
    # the scenarios above stay as they were.
    rnd = random.Random(0xac1d5b)
    sc += [s_interest(rnd, disc), s_trigger(rnd, disc), s_step(rnd, disc),
           s_physics(rnd, disc), s_cycles(rnd, disc), s_nebula(rnd, disc)]
    for n, t in ((600, "TRACKB12"), (1500, "TRACKB33")):
        sc.append(s_fx_fuzz(rnd, disc, n, disc.index(t)))
    return sc


def encode(scenarios):
    lines = []
    for i, s in enumerate(scenarios):
        lines.append("B %d" % i)
        lines += s
    return NL.join(lines) + NL


# ================================================================ the model


class Buf(object):
    def __init__(self, k):
        self.base = BUFS + BUF_STRIDE * k
        self.reset()

    def reset(self):
        self.at = self.base
        self.ch, self.kind, self.nrec, self.rec0 = [], [], [], []

    @property
    def n(self):
        return len(self.ch)


def pool_at(i):
    return POOLS + 64 * i


class Model(object):
    def __init__(self, disc):
        self.disc = disc
        self.out = []
        self.e = retail_model.RetailEmu(ieee=True)
        e = self.e
        assert e._top_of_image() <= POOLS
        assert e.u32(8) == 0
        e.stub(B_NEW_POOL, self.st_new_pool)
        e.stub(B_DEL_POOL, self.st_del_pool)
        e.stub(B_OMALLOC, lambda em: self.omalloc(self.arg(0)))
        e.stub(B_FREE_SLOT, self.st_free)
        e.stub(B_FREE, self.st_bfree)
        e.stub(B_MALLOC, lambda em: self.omalloc(self.arg(0), "malloc"))
        e.stub(B_IS_FULL, self.st_is_full)
        e.stub(GET_TEXTURE_INFO, self.st_gti)
        e.stub(E_GET_VIEW, self.st_get_view)
        e.stub(B_TICKER, self.st_ticker)
        e.stub(B_TICKER_DIFF, self.st_ticker_diff)
        e.hook(TRIGGER, lambda em: em.put32(
            (em.reg[29] - TRIGGER_FRAME + 204) & M32, 0))
        e.hook(DO_STEP, lambda em: em.write(
            (em.reg[29] - STEP_FRAME) & M32, bytes(64)))
        e.call(EMATH_INIT, limit=10000)
        e.call(EMATH_CTOR, limit=1000)
        for i, nm in enumerate(POOL_NAMES):
            a = 0x002b0000 + (-11480, -11456, -11432)[i]
            assert self.cstr(a) == nm, nm
        self.bufs = [Buf(k) for k in range(NBUF)]
        self.used = [bytearray(n) for n in NSLOT]
        self.fail_after = [-1] * 3
        self.reg = 0
        self.tex_hash = []
        self.txm = []
        self.ticker = 0

    def emit(self, s):
        self.out.append(s)

    def w(self, a):
        return self.e.u32(a)

    def put(self, a, v):
        self.e.put32(a, v)

    def fill(self, a, n, b=PATB):
        self.e.write(a, bytes([b]) * n)

    def arg(self, i):
        return self.e.reg[4 + i] & M32

    def cstr(self, a):
        mem = self.e.mem
        return bytes(mem[a:mem.index(0, a)]).decode("latin-1")

    def call(self, fn, *args):
        return self.e.call(fn, *[s32(x) for x in args], limit=CALL_LIMIT)

    # ---- the pools and the textures --------------------------------------

    def pool_index(self, p):
        for i in range(3):
            if p == pool_at(i):
                return i
        return -1

    def st_new_pool(self, em):
        size, num, mp = s32(self.arg(0)), s32(self.arg(1)), s32(self.arg(3))
        name = self.cstr(self.arg(2))
        if name not in POOL_NAMES:
            self.emit("  newpool ? %s" % name)
            return 0
        i = POOL_NAMES.index(name)
        self.emit("  newpool %d %d %s %d" % (
            SLOT[i] if size == SLOT[i] else -size, num, name, mp))
        self.put(pool_at(i) + POOL_FLAGS, 15)
        self.used[i] = bytearray(NSLOT[i])
        self.fail_after[i] = -1
        return pool_at(i)

    def pool_name(self, p):
        i = self.pool_index(p)
        return "null" if p == 0 else POOL_SHORT[i] if i >= 0 else "?"

    def st_del_pool(self, em):
        self.emit("  delpool %s" % self.pool_name(self.arg(0)))

    def omalloc(self, p, what="omalloc"):
        i = self.pool_index(p)
        if i < 0:
            self.emit("  %s %s -> null" % (what, "null" if p == 0 else "?"))
            return 0
        if self.fail_after[i] == 0:
            self.emit("  %s %s -> null" % (what, POOL_SHORT[i]))
            return 0
        k = self.used[i].find(0)
        if k < 0:
            self.emit("  %s %s -> full" % (what, POOL_SHORT[i]))
            return 0
        if self.fail_after[i] > 0:
            self.fail_after[i] -= 1
        self.used[i][k] = 1
        a = ARENA[i] + SLOT[i] * k
        zero = self.w(p + POOL_FLAGS) & 2
        self.fill(a, SLOT[i], 0 if zero else PATB)
        self.emit("  %s %s -> %s" % (what, POOL_SHORT[i], self.nm(a)))
        return a

    def st_is_full(self, em):
        p = self.arg(0)
        i = self.pool_index(p)
        if i < 0:
            self.emit("  full? %s -> 1" % ("null" if p == 0 else "?"))
            return 1
        r = 1 if self.fail_after[i] == 0 or self.used[i].find(0) < 0 else 0
        self.emit("  full? %s -> %d" % (POOL_SHORT[i], r))
        return r

    def st_get_view(self, em):
        v = s32(self.arg(0))
        if not 0 <= v < NVIEW:
            raise SystemExit("view %d" % v)
        return VIEWS + 0x100 * v

    def st_ticker(self, em):
        self.ticker = (self.ticker + TICK) & M32
        return self.ticker

    def st_ticker_diff(self, em):
        d = (self.arg(1) - self.arg(0)) & M32
        self.e.fpr[0] = fb(struct.unpack("<f", struct.pack("<f", float(d)))[0]
                           * 0.5)

    def st_free(self, em):
        p, slot = self.arg(0), self.arg(1)
        i = self.pool_index(p)
        self.emit("  free %s %s" % (self.pool_name(p), self.nm(slot)))
        if i >= 0:
            off = slot - ARENA[i]
            if 0 <= off < SLOT[i] * NSLOT[i] and off % SLOT[i] == 0:
                self.used[i][off // SLOT[i]] = 0

    def st_bfree(self, em):
        raise SystemExit("bFree(void *) reached, from 0x%08x"
                         % (self.e.reg[31] & M32))

    def tex_mode(self, hh):
        for th, mode in self.txm:
            if th == hh:
                return mode
        return hh % 3

    def st_gti(self, em):
        hh, ud, iu = self.arg(0), s32(self.arg(1)), s32(self.arg(2))
        mode = self.tex_mode(hh)
        if mode == 0:
            self.emit("  gti %08x %d %d -> null" % (hh, ud, iu))
            return 0
        if hh in self.tex_hash:
            i = self.tex_hash.index(hh)
        else:
            if len(self.tex_hash) == NTEX:
                raise SystemExit("textures full")
            i = len(self.tex_hash)
            self.tex_hash.append(hh)
        a = TEXS + TEX_SIZE * i
        self.put(a + TEX_NAMEHASH, hh ^ 1 if mode == 2 else hh)
        self.emit("  gti %08x %d %d -> %s" % (hh, ud, iu, self.nm(a)))
        return a

    # ---- names -----------------------------------------------------------

    def nm(self, a):
        a &= M32
        if a == 0:
            return "null"
        if a == PAT:
            return "pat"
        fixed = {FE: "FE.act", FE + 8: "FE.auto", WE: "WE.act",
                 WE + 8: "WE.auto", G_EDL: "EDL"}
        if a in fixed:
            return fixed[a]
        for k in range(NCAR):
            if a == CARS + 0x800 * k:
                return "c%d" % k
        if LISTS <= a < LISTS + 8 * NLIST and (a - LISTS) % 8 == 0:
            return "L%d" % ((a - LISTS) // 8)
        if TEXS <= a < TEXS + TEX_SIZE * len(self.tex_hash) \
                and (a - TEXS) % TEX_SIZE == 0:
            return "t%d" % ((a - TEXS) // TEX_SIZE)
        for i in range(3):
            off = a - ARENA[i]
            if 0 <= off < SLOT[i] * NSLOT[i]:
                if off % SLOT[i] == 0:
                    return "%s%d" % ("pge"[i], off // SLOT[i])
                if i == 1 and off % SLOT[i] == 20:
                    return "g%d.pl" % (off // SLOT[i])
                return "?"
        for k, b in enumerate(self.bufs):
            for c in range(b.n):
                if b.kind[c] == 0:
                    continue
                sz = DATA_SIZE if b.kind[c] == 1 else EMIT_SIZE
                off = a - b.rec0[c]
                if 0 <= off < sz * b.nrec[c] and off % sz == 0:
                    return "%s%d.%d.%d" % ("DE"[b.kind[c] - 1], k, c,
                                           off // sz)
        return "?"

    def nth(self, lst, i):
        n = self.w(lst)
        while n != lst and 0 < i < 100000:
            n = self.w(n)
            i -= 1
        return 0 if n == lst else n

    @staticmethod
    def atoi(s):
        m = re.match(r"\s*([+-]?\d+)", s)
        return int(m.group(1)) if m else 0

    def ref(self, t):
        if t == "null":
            return 0
        if t == "r":
            return self.reg
        if t == "FE":
            return FE
        if t == "WE":
            return WE
        if t[0] in "DE":
            m = re.match(r"([+-]?\d+)\.([+-]?\d+)\.([+-]?\d+)", t[1:])
            if m:
                k, c, i = (int(x) for x in m.groups())
                b = self.bufs[k]
                if c >= b.n or i >= b.nrec[c]:
                    return 0
                return b.rec0[c] + (DATA_SIZE if t[0] == "D"
                                    else EMIT_SIZE) * i
        if t[0] in "egp" and t[1:2].isdigit():
            p = "pge".index(t[0])
            return ARENA[p] + SLOT[p] * self.atoi(t[1:])
        if t[0] == "t" and t[1:2].isdigit():
            return TEXS + TEX_SIZE * self.atoi(t[1:])
        if t[0] == "c" and t[1:2].isdigit():
            return CARS + 0x800 * self.atoi(t[1:])
        dot = t.rfind(".")
        if dot < 0:
            if t[0] == "L":
                return LISTS + 8 * self.atoi(t[1:])
            raise SystemExit("bad ref %s" % t)
        head, i = t[:dot][:15], self.atoi(t[dot + 1:])
        if head == "EDL":
            return self.nth(G_EDL, i)
        if head[0] == "L":
            return self.nth(LISTS + 8 * self.atoi(head[1:]), i)
        s = FE if head.startswith("FE") else WE
        return self.nth(s if head[3:] == "act" else s + 8, i)

    # ---- the dumps -------------------------------------------------------

    def walk_count(self, lst):
        n, c = self.w(lst), 0
        while n != lst and c < 5000:
            n = self.w(n)
            c += 1
        return c

    def broken(self, n):
        return self.w(self.w(n) + 4) != n

    def pemit_short(self, e):
        w = self.w
        return " %s[st %d rc %s ec %s rs %08x d %s lag %s de %08x]" % (
            self.nm(e), s32(w(e + 16)), fx(w(e + 20)), fx(w(e + 24)),
            w(e + 36), self.nm(w(e + 28)), self.nm(w(e + 32)), w(e + 40))

    def pemit_full(self, e):
        w = self.w
        s = (" %s{nh %08x dh %08x st %d rc %s ec %s d %s lag %s rs %08x"
             " de %08x p2 %08x w" % (
                 self.nm(e), w(e + 8), w(e + 12), s32(w(e + 16)),
                 fx(w(e + 20)), fx(w(e + 24)), self.nm(w(e + 28)),
                 self.nm(w(e + 32)), w(e + 36), w(e + 40), w(e + 44)))
        s += "".join(" " + fx(w(e + 48 + 4 * i)) for i in range(16))
        s += " iv %s %s %s %s n '" % tuple(fx(w(e + 112 + 4 * i))
                                           for i in range(4))
        raw = bytes(self.e.mem[e + 128:e + 192])
        name = raw.split(b"\0")[0]
        s += "".join(chr(b) if 0x20 <= b < 0x7f else "." for b in name)
        s += "'"
        tail = raw[len(name) + 1:]
        if any(tail):
            s += " +" + tail.hex()
        return s + "}"

    def ptail(self, lst, last):
        return " !p" if self.w(lst + 4) != last else ""

    def pemitters(self, tag, lst, full):
        parts = ["  %s %d:" % (tag, self.walk_count(lst))]
        n, c, last = self.w(lst), 0, lst
        while n != lst and c < 5000:
            parts.append(self.pemit_full(n) if full else self.pemit_short(n))
            if self.broken(n):
                parts.append("!")
            last = n
            n = self.w(n)
            c += 1
        parts.append(self.ptail(lst, last))
        self.emit("".join(parts))

    def pgroups(self, tag, lst):
        w = self.w
        parts = ["  %s %d:" % (tag, self.walk_count(lst))]
        g, c, last = w(lst), 0, lst
        while g != lst and c < 5000:
            parts.append(" %s{d %s e %s c %s:" % (
                self.nm(g), self.nm(w(g + 8)), self.nm(w(g + 12)),
                self.nm(w(g + 16))))
            pl = g + 20
            p, k, plast = w(pl), 0, pl
            while p != pl and k < 5000:
                parts.append(" %s%s" % (self.nm(p),
                                        "!" if self.broken(p) else ""))
                plast = p
                p = w(p)
                k += 1
            parts.append(self.ptail(pl, plast))
            parts.append("}%s" % ("!" if self.broken(g) else ""))
            last = g
            g = w(g)
            c += 1
        parts.append(self.ptail(lst, last))
        self.emit("".join(parts))

    def psystem(self, tag, s):
        w, u8 = self.w, self.e.u8
        self.pgroups("%s act" % tag, s)
        self.pemitters("%s auto" % tag, s + 8, False)
        self.emit("  %s w cur %s sel %d b %s n %d nv %d rt %s ut %s ip %s" % (
            tag, self.nm(w(s + 64)), s32(w(s + 68)),
            " ".join("%02x" % u8(s + 72 + i) for i in range(6)),
            s32(w(s + 80)), s32(w(s + 84)), fx(w(s + 88)), fx(w(s + 92)),
            " ".join(fx(w(s + 16 + 4 * i)) for i in range(12))))

    def pip(self, tag, s):
        self.emit("  %s ip %s" % (tag, " ".join(fx(self.w(s + 16 + 4 * i))
                                                for i in range(12))))

    def pparticles(self, tag, s):
        w, mem = self.w, self.e.mem
        g, c = w(s), 0
        while g != s and c < 5000:
            parts = ["  %s %s d %s e %s c %s:" % (
                tag, self.nm(g), self.nm(w(g + 8)), self.nm(w(g + 12)),
                self.nm(w(g + 16)))]
            pl = g + 20
            p, k = w(pl), 0
            while p != pl and k < 5000:
                life, ang, spd, inh, pad = struct.unpack_from("<HHHBB", mem,
                                                              p + 8)
                vx, vy, vz, fr = struct.unpack_from("<BBBB", mem, p + 28)
                parts.append(
                    " %s[%04x %04x %04x %02x %02x %s %s %s %02x %02x %02x %02x]"
                    % (self.nm(p), life, ang, spd, inh, pad, fx(w(p + 16)),
                       fx(w(p + 20)), fx(w(p + 24)), vx, vy, vz, fr))
                p = w(p)
                k += 1
            self.emit("".join(parts))
            g = w(g)
            c += 1

    def pbases(self, d):
        self.emit("  cb %s xb %s" % (
            " ".join(fx(self.w(d + 256 + 4 * i)) for i in range(16)),
            " ".join(fx(self.w(d + 320 + 4 * i)) for i in range(16))))

    def pool_str(self, p):
        if p == 0:
            return "null"
        i = self.pool_index(p)
        if i < 0:
            return "?"
        return "%s:%x" % (POOL_SHORT[i], self.w(p + POOL_FLAGS))

    def pglobals(self):
        w = self.w
        self.emit("  pools %s %s %s n %d seed %08x" % (
            self.pool_str(w(G_PP)), self.pool_str(w(G_GP)),
            self.pool_str(w(G_EP)), s32(w(G_NUM)), w(G_SEED)))
        parts = ["  edl %d:" % self.walk_count(G_EDL)]
        n, c, last = w(G_EDL), 0, G_EDL
        while n != G_EDL and c < 5000:
            parts.append(" %s/%s%s" % (self.nm(n), self.nm(w(n + 20)),
                                       "!" if self.broken(n) else ""))
            last = n
            n = w(n)
            c += 1
        parts.append(self.ptail(G_EDL, last))
        self.emit("".join(parts))

    def pshort(self):
        w, wc = self.w, self.walk_count
        self.emit("  s n %d seed %08x edl %d FE %d/%d/%d WE %d/%d/%d" % (
            s32(w(G_NUM)), w(G_SEED), wc(G_EDL), wc(FE), wc(FE + 8),
            s32(w(FE + 80)), wc(WE), wc(WE + 8), s32(w(WE + 80))))

    def dump_all(self):
        self.pglobals()
        self.psystem("FE", FE)
        self.psystem("WE", WE)
        for i in range(NLIST):
            if self.w(LISTS + 8 * i) == 0:
                continue
            self.pemitters("L%d" % i, LISTS + 8 * i, True)

    # ---- the chunks ------------------------------------------------------

    def put_data(self, a, r):
        m = bytearray([PATB]) * DATA_SIZE
        m[8:20] = r[8:20]
        m[20:24] = struct.pack("<I", PAT if any(r[20:24]) else 0)
        m[24:544] = r[24:544]
        self.e.write(a, bytes(m))

    def put_emitter(self, a, r):
        m = bytearray([PATB]) * EMIT_SIZE
        m[8:28] = r[8:28]
        m[28:32] = struct.pack("<I", PAT if any(r[28:32]) else 0)
        m[32:36] = struct.pack("<I", PAT if any(r[32:36]) else 0)
        m[36:192] = r[36:192]
        self.e.write(a, bytes(m))

    def op_chunk(self, t):
        k, typ, ver, hn = int(t[1], 0), int(t[2], 16), int(t[3], 0), int(t[4], 0)
        mis, kind, first = int(t[5], 0), t[6], int(t[7], 0)
        assert 0 <= mis < 16
        b = self.bufs[k]
        assert b.n < NCH, "too many chunks on buffer %d" % k
        c = b.at
        while (c & 15) != mis:
            c += 1
        self.e.write(c, bytes(64))
        self.put(c, typ)
        hd = (c + 23) & ~15
        self.e.write(c + 8, bytes(hd - c - 8 + 16))
        self.put(hd + 8, ver)
        self.put(hd + 12, hn)
        kd = 1 if kind[0] == "D" else 2 if kind[0] == "E" else 0
        b.ch.append(c)
        b.rec0.append(hd + 16)
        b.kind.append(kd)
        b.nrec.append(hn if kd else 0)
        end = hd + 16
        if kd:
            recs = self.disc.datas if kd == 1 else self.disc.emits
            assert first + hn <= len(recs)
            for i in range(hn):
                if kd == 1:
                    self.put_data(end, recs[first + i])
                    end += DATA_SIZE
                else:
                    self.put_emitter(end, recs[first + i])
                    end += EMIT_SIZE
        assert end < b.base + BUF_STRIDE
        self.put(c + 4, end - c - 8)
        b.at = end

    # ---- the ops ---------------------------------------------------------

    def reset(self):
        e = self.e
        self.fill(FE, SYS_SIZE)
        self.fill(WE, SYS_SIZE)
        self.put(G_EDL, PAT)
        self.put(G_EDL + 4, PAT)
        for a in (G_PP, G_GP, G_EP, G_NUM):
            self.put(a, 0)
        self.put(G_SEED, SEED0)
        for i in range(3):
            self.put(pool_at(i) + POOL_FLAGS, 15)
            self.used[i] = bytearray(NSLOT[i])
            self.fill(ARENA[i], SLOT[i] * NSLOT[i])
            self.fail_after[i] = -1
        for b in self.bufs:
            b.reset()
        e.write(LISTS, bytes(8 * NLIST))
        self.reg = 0
        self.tex_hash = []
        self.txm = []
        e.write(VIEWS, bytes(0x100 * NVIEW))
        e.write(CAMS, bytes(0x200 * NVIEW))
        e.write(CARS, bytes(0x800 * NCAR))
        self.ticker = 0
        self.put(G_FLOW, 0)

    def sys_tok(self, t):
        return FE if t == "FE" else WE

    def add_tail(self, lst, n):
        tail = self.w(lst + 4)
        self.put(tail, n)
        self.put(lst + 4, n)
        self.put(n, lst)
        self.put(n + 4, tail)

    def add_head(self, lst, n):
        head = self.w(lst)
        self.put(lst, n)
        self.put(head + 4, n)
        self.put(n, head)
        self.put(n + 4, lst)

    def make_group(self, t):
        s, e, np = self.sys_tok(t[1]), self.ref(t[2]), int(t[3], 0)
        g = self.omalloc(self.w(G_GP))
        if g == 0:
            return
        self.put(g + 8, self.w(e + 28) if e else 0)
        self.put(g + 12, e)
        self.put(g + 16, 0)
        pl = g + 20
        self.put(pl, pl)
        self.put(pl + 4, pl)
        for _ in range(np):
            p = self.omalloc(self.w(G_PP))
            if p == 0:
                break
            self.add_tail(pl, p)
        self.add_head(s, g)

    def set_tail(self, a, first_off, f, args):
        off, v = int(args[0], 0), int(args[1], 16)
        if off < first_off:
            raise SystemExit("offset %d before the tail" % off)
        if f == "w":
            self.put(a + off, v)
        else:
            self.e.write(a + off, bytes([v & 0xff]))

    def set_field_e(self, e, f, args):
        v = args[0]
        if f in ("w", "b"):
            self.set_tail(e, 36, f, args)
        elif f == "st":
            self.put(e + 16, int(v, 0))
        elif f in ("rc", "ec", "rs", "de", "nh", "dh"):
            off = {"rc": 20, "ec": 24, "rs": 36, "de": 40, "nh": 8,
                   "dh": 12}[f]
            self.put(e + off, int(v, 16))
        elif f == "d":
            self.put(e + 28, self.ref(v))
        elif f == "nm":
            s = v.encode("latin-1")[:64]
            self.e.write(e + 128, s + bytes(64 - len(s)))
        elif f == "nmz":
            self.e.write(e + 128, bytes(64))
        elif f == "nmg":
            s = v.encode("latin-1")[:62]
            self.e.write(e + 128, s + bytes(1) + b"G" * (63 - len(s)))
        else:
            raise SystemExit("bad field %s" % f)

    def set_field_d(self, d, f, args):
        v = args[0]
        offs = {"on": 32, "onv": 36, "off": 40, "offv": 44, "nh": 8,
                "gh": 16, "th": 12}
        if f in ("w", "b"):
            self.set_tail(d, 24, f, args)
        elif f in offs:
            self.put(d + offs[f], int(v, 16))
        elif f == "tex":
            self.put(d + 20, self.ref(v))
        else:
            raise SystemExit("bad field %s" % f)

    def op(self, t):
        c = t[0]
        if c == "D":
            self.dump_all()
            return
        if c == "DL":
            k = int(t[1], 0)
            self.pemitters("L%d" % k, LISTS + 8 * k, True)
            return
        if c == "DE":
            e = self.ref(t[1])
            self.emit("  (none)" if e == 0 else " " + self.pemit_full(e))
            return
        if c == "BR":
            self.bufs[int(t[1], 0)].reset()
            return
        if c == "CH":
            self.op_chunk(t)
            return
        if c == "PE":
            e = self.ref(t[1])
            if e == 0:
                self.emit("  (none)")
            else:
                self.set_field_e(e, t[2], t[3:])
            return
        if c == "PD":
            d = self.ref(t[1])
            if d == 0:
                self.emit("  (none)")
            else:
                self.set_field_d(d, t[2], t[3:])
            return
        if c == "SEED":
            self.put(G_SEED, int(t[1], 16))
            return
        if c == "CAM":
            v = int(t[1], 0)
            if t[2] == "null":
                self.put(VIEWS + 0x100 * v + VIEW_CAMERA, 0)
            else:
                cam = CAMS + 0x200 * v
                for i in range(4):
                    self.put(cam + CAM_POSITION + 4 * i, int(t[2 + i], 16))
                self.put(VIEWS + 0x100 * v + VIEW_CAMERA, cam)
            return
        if c == "CV":
            car = CARS + 0x800 * int(t[1], 0)
            for i in range(3):
                self.put(car + CAR_VELOCITY + 4 * i, int(t[2 + i], 16))
            return
        if c == "FS":
            self.put(G_FLOW, int(t[1], 0))
            return
        if c == "DP":
            s = self.sys_tok(t[1])
            self.pparticles("FE" if s == FE else "WE", s)
            return
        if c == "DD":
            d = self.ref(t[1])
            if d == 0:
                self.emit("  (none)")
            else:
                self.pbases(d)
            return
        if c == "F":
            self.fail_after[POOL_SHORT.index(t[1])] = int(t[2], 0)
            return
        if c == "PF":
            self.put(pool_at(POOL_SHORT.index(t[1])) + POOL_FLAGS,
                     int(t[2], 16))
            return
        if c == "S":
            self.call(STATIC_INIT)
        elif c == "I":
            self.call(AFX_INIT)
        elif c == "C":
            self.call(AFX_CLOSE)
        elif c in ("L", "U"):
            b = self.bufs[int(t[1], 0)]
            ch = b.ch[int(t[2], 0)]
            self.emit("  -> %d" % self.call(LOADER if c == "L" else UNLOADER,
                                           ch))
        elif c == "LA":
            for ch in self.bufs[int(t[1], 0)].ch:
                self.emit("  -> %d" % self.call(LOADER, ch))
        elif c == "UA":
            for ch in reversed(self.bufs[int(t[1], 0)].ch):
                self.emit("  -> %d" % self.call(UNLOADER, ch))
        elif c == "T":
            self.call(UPDATE_TEX)
        elif c == "TXM":
            assert len(self.txm) < NTXM
            self.txm.append((int(t[1], 16), int(t[2], 0)))
        elif c in ("GD", "GE"):
            assert self.w(8) == 0
            self.reg = self.call(GET_DATA if c == "GD" else GET_EMITTER,
                                 int(t[1], 16), int(t[2], 16),
                                 self.ref(t[3])) & M32
            self.emit("  -> %s" % self.nm(self.reg))
        elif c == "CP":
            e = self.ref(t[1])
            if e == 0:
                self.reg = 0
                self.emit("  (none)")
            else:
                self.reg = self.call(COPY, e) & M32
                self.emit("  ->" + (self.pemit_full(self.reg) if self.reg
                                    else " null"))
        elif c == "NL":
            a = LISTS + 8 * int(t[1], 0)
            self.put(a, a)
            self.put(a + 4, a)
        elif c == "GS":
            self.call(GET_EMITTERS, LISTS + 8 * int(t[1], 0), int(t[2], 16))
        elif c == "DS":
            self.call(DELETE_EMITTERS, LISTS + 8 * int(t[1], 0))
        elif c in ("SD", "SH"):
            e = self.ref(t[1])
            if e == 0:
                self.emit("  (none)")
            elif c == "SD":
                self.emit("  -> %d" % self.call(SET_DATA, e, self.ref(t[2])))
            else:
                self.emit("  -> %d" % self.call(SET_DATA_HASH, e,
                                               int(t[2], 16)))
        elif c in ("AA", "RA"):
            s, e = self.sys_tok(t[1]), self.ref(t[2])
            if c == "RA":
                self.reg = e
            if e == 0:
                self.emit("  (none)")
            else:
                self.call(ADD_AUTO if c == "AA" else REMOVE_AUTO, s, e)
        elif c == "K":
            self.call(KILL_ALL, self.sys_tok(t[1]))
        elif c == "MG":
            self.make_group(t)
        elif c in ("ED", "ED2"):
            e, f = self.ref(t[1]), int(t[2], 0)
            if e == 0:
                self.emit("  (none)")
            else:
                self.call(EMITTER_DEL if c == "ED" else EMITTER_DEL2, e, f)
        elif c == "GX":
            g, f = self.ref(t[1]), int(t[2], 0)
            if g == 0:
                self.emit("  (none)")
            else:
                self.call(GROUP_DEL, g, f)
        elif c == "UIP":
            s = self.sys_tok(t[1])
            self.call(UPDATE_IP, s)
            self.pip("FE" if s == FE else "WE", s)
        elif c == "TR":
            s, em, car = self.sys_tok(t[1]), self.ref(t[2]), self.ref(t[4])
            if em == 0:
                self.emit("  (none)")
            else:
                self.e.fpr[12] = int(t[3], 16)
                self.call(TRIGGER, s, em, car)
                self.emit("  em" + self.pemit_short(em))
        elif c == "DT":
            s = self.sys_tok(t[1])
            self.e.fpr[12] = int(t[2], 16)
            self.call(DO_STEP, s)
            self.emit("  ut %s" % fx(self.w(s + 92)))
        elif c == "CT":
            s = self.sys_tok(t[1])
            self.fill(s, SYS_SIZE)
            self.call(SYS_CTOR, s)
            self.psystem("FE" if s == FE else "WE", s)
        else:
            raise SystemExit("bad op %r" % (t,))
        self.pshort()

    def run(self, scenarios):
        for i, sc in enumerate(scenarios):
            self.emit("B %d" % i)
            self.reset()
            for ln in sc:
                self.emit("> " + ln[:40])
                self.op(ln.split())
        return self.out


# ================================================================ the build


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc, disc, records):
    """Model(disc).run(sc), or its last transcript when nothing it reads
    has changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc, lambda s: Model(disc).run(s),
                               data=[records], cut=MUTATIONS_HEADER)


def build_harness(tmp, name="afx_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, sc_path, rec_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(sc_path), str(rec_path)],
                               stdout=fh, stderr=subprocess.PIPE, text=True,
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


def write_inputs(d, disc, sc):
    scp = Path(d) / "scenarios.txt"
    scp.write_bytes(encode(sc).encode("latin-1"))
    rec = Path(d) / RECORDS_NAME
    rec.write_bytes(disc.records())
    return scp, rec


# ============================================================ the mutations


def M(name, before, after, rel=ACIDC, pre=""):
    return (name, rel, pre + before, pre + after)


MUTATIONS = [
    # the list helpers
    M("tail-no-prev", "    n->next = list;\n    n->prev = tail;\n}",
      "    n->next = list;\n}"),
    M("tail-swap", "    n->next = list;\n    n->prev = tail;",
      "    n->next = tail;\n    n->prev = list;"),
    M("tail-no-list-prev", "    tail->next = n;\n    list->prev = n;\n",
      "    tail->next = n;\n"),
    M("head-no-head-prev", "    list->next = n;\n    head->prev = n;\n",
      "    list->next = n;\n"),
    M("head-swap", "    n->next = head;\n    n->prev = list;",
      "    n->next = list;\n    n->prev = head;"),
    M("unlink-no-next", "    prev->next = next;\n    next->prev = prev;",
      "    next->prev = prev;"),
    M("unlink-no-prev", "    prev->next = next;\n    next->prev = prev;",
      "    prev->next = next;"),
    # the xorshift and the fraction
    M("xs-17", "x ^= x << 17;", "x ^= x << 16;"),
    M("xs-13", "x ^= x >> 13;", "x ^= x >> 12;"),
    M("xs-5", "x ^= x << 5;", "x ^= x << 6;"),
    M("xs-order", "    x ^= x << 17;\n    x ^= x >> 13;",
      "    x ^= x >> 13;\n    x ^= x << 17;"),
    M("unit-mask", "(x & 0x7fffffffu)", "(x & 0x3fffffffu)"),
    M("unit-scale", "* 0x1p-31f;", "* 0x1p-32f;"),
    M("unit-unsigned", "return (float)(int32_t)(x & 0x7fffffffu)",
      "return (float)x"),
    # bStrNCpy and the header
    M("strncpy-short", "    for (i = 0; i < n; i++) {\n        dst[i]",
      "    for (i = 0; i < n - 1; i++) {\n        dst[i]"),
    M("strncpy-no-stop", "        if (src[i] == '\\0')\n            break;\n",
      ""),
    M("header-24", "+ 23u) & ~(uintptr_t)15u", "+ 24u) & ~(uintptr_t)15u"),
    M("header-22", "+ 23u) & ~(uintptr_t)15u", "+ 22u) & ~(uintptr_t)15u"),
    M("header-mask", "+ 23u) & ~(uintptr_t)15u", "+ 23u) & ~(uintptr_t)7u"),
    # the static constructor
    M("sinit-no-prev", "    EmitterDataList.prev = &EmitterDataList;\n"
      "    EmitterDataList.next = &EmitterDataList;\n    acid_system",
      "    EmitterDataList.next = &EmitterDataList;\n    acid_system"),
    M("sinit-no-fe", "    acid_system_construct(&FrameEffects);\n"
      "    acid_system_construct(&WorldEffects);\n}",
      "    acid_system_construct(&WorldEffects);\n}"),
    M("sinit-no-we", "    acid_system_construct(&FrameEffects);\n"
      "    acid_system_construct(&WorldEffects);\n}",
      "    acid_system_construct(&FrameEffects);\n}"),
    # afxInit and afxClose
    M("init-pp-size", "bNewSlotPool((int)sizeof(AcidParticle), 1000,",
      "bNewSlotPool((int)sizeof(AcidParticle) + 4, 1000,"),
    M("init-pp-count", "sizeof(AcidParticle), 1000,",
      "sizeof(AcidParticle), 999,"),
    M("init-gp-count", "sizeof(AcidActiveGroup), 400,",
      "sizeof(AcidActiveGroup), 401,"),
    M("init-ep-count", "sizeof(AcidEmitter), 600,", "sizeof(AcidEmitter), 60,"),
    M("init-pp-name", "\"AcidParticleSlotPool\", 16);",
      "\"AcidParticlePool\", 16);"),
    M("init-ep-mem", "\"AcidEmitterSlotPool\", 16);",
      "\"AcidEmitterSlotPool\", 0);"),
    M("init-gp-mem", "\"AcidActiveGroupSlotPool\", 16);",
      "\"AcidActiveGroupSlotPool\", 15);"),
    M("init-pp-overflow",
      "    AcidParticleSlotPool->flags &= ~BSP_OVERFLOW_IF_FULL;\n", ""),
    M("init-pp-zero",
      "    AcidParticleSlotPool->flags &= ~BSP_ZERO_ALLOCATED_MEMORY;\n", ""),
    M("init-gp-overflow",
      "    AcidActiveGroupSlotPool->flags &= ~BSP_OVERFLOW_IF_FULL;\n", ""),
    M("init-gp-zero",
      "    AcidActiveGroupSlotPool->flags &= ~BSP_ZERO_ALLOCATED_MEMORY;\n", ""),
    M("init-ep-zero",
      "    AcidActiveGroupSlotPool->flags &= ~BSP_ZERO_ALLOCATED_MEMORY;\n",
      "    AcidActiveGroupSlotPool->flags &= ~BSP_ZERO_ALLOCATED_MEMORY;\n"
      "    AcidEmitterSlotPool->flags &= ~BSP_ZERO_ALLOCATED_MEMORY;\n"),
    M("close-no-fe", "    acid_system_kill_all_active_effects(&FrameEffects);\n"
      "    acid_system_kill_all_active_effects(&WorldEffects);\n"
      "    bDeleteSlotPool",
      "    acid_system_kill_all_active_effects(&WorldEffects);\n"
      "    bDeleteSlotPool"),
    M("close-no-we", "    acid_system_kill_all_active_effects(&WorldEffects);\n"
      "    bDeleteSlotPool",
      "    bDeleteSlotPool"),
    M("close-order", "    acid_system_kill_all_active_effects(&FrameEffects);\n"
      "    acid_system_kill_all_active_effects(&WorldEffects);\n"
      "    bDeleteSlotPool",
      "    acid_system_kill_all_active_effects(&WorldEffects);\n"
      "    acid_system_kill_all_active_effects(&FrameEffects);\n"
      "    bDeleteSlotPool"),
    M("close-no-del-pp", "    bDeleteSlotPool(AcidParticleSlotPool);\n", ""),
    M("close-no-del-gp", "    bDeleteSlotPool(AcidActiveGroupSlotPool);\n", ""),
    M("close-del-ep", "    bDeleteSlotPool(AcidActiveGroupSlotPool);\n",
      "    bDeleteSlotPool(AcidActiveGroupSlotPool);\n"
      "    bDeleteSlotPool(AcidEmitterSlotPool);\n"),
    M("close-keep-pp", "    AcidParticleSlotPool = NULL;\n", ""),
    M("close-keep-gp", "    AcidActiveGroupSlotPool = NULL;\n", ""),
    M("close-null-ep", "    AcidActiveGroupSlotPool = NULL;\n",
      "    AcidActiveGroupSlotPool = NULL;\n    AcidEmitterSlotPool = NULL;\n"),
    # LoaderAcidFX
    M("load-a", "int loader_acid_fx(uint8_t *chunk)\n{\n"
      "    uint32_t type = bchunk_u32(chunk);\n    uint8_t *h;\n"
      "    uint32_t n;\n\n    if (type == ACID_CHUNK_A || type == ACID_CHUNK_B)",
      "int loader_acid_fx(uint8_t *chunk)\n{\n"
      "    uint32_t type = bchunk_u32(chunk);\n    uint8_t *h;\n"
      "    uint32_t n;\n\n    if (type == ACID_CHUNK_B)"),
    M("load-b", "int loader_acid_fx(uint8_t *chunk)\n{\n"
      "    uint32_t type = bchunk_u32(chunk);\n    uint8_t *h;\n"
      "    uint32_t n;\n\n    if (type == ACID_CHUNK_A || type == ACID_CHUNK_B)",
      "int loader_acid_fx(uint8_t *chunk)\n{\n"
      "    uint32_t type = bchunk_u32(chunk);\n    uint8_t *h;\n"
      "    uint32_t n;\n\n    if (type == ACID_CHUNK_A)"),
    M("load-ab-ret", "    if (type == ACID_CHUNK_A || type == ACID_CHUNK_B)\n"
      "        return 1;\n    if (type == ACID_CHUNK_DATAS) {\n"
      "        AcidEmitterData *d;\n\n        h = pack_header(chunk);\n"
      "        if (*(int32_t *)(h + 8) != ACID_DATAS_VERSION)\n"
      "            return 1;\n        n = *(uint32_t *)(h + 12);\n"
      "        d = (AcidEmitterData *)(h + 16);\n"
      "        for (; n != 0; n--, d++)\n"
      "            afx_add_emitter_data(d);",
      "    if (type == ACID_CHUNK_A || type == ACID_CHUNK_B)\n"
      "        return 0;\n    if (type == ACID_CHUNK_DATAS) {\n"
      "        AcidEmitterData *d;\n\n        h = pack_header(chunk);\n"
      "        if (*(int32_t *)(h + 8) != ACID_DATAS_VERSION)\n"
      "            return 1;\n        n = *(uint32_t *)(h + 12);\n"
      "        d = (AcidEmitterData *)(h + 16);\n"
      "        for (; n != 0; n--, d++)\n"
      "            afx_add_emitter_data(d);"),
    M("load-data-ver", "            return 1;\n        n = *(uint32_t *)(h + 12);\n"
      "        d = (AcidEmitterData *)(h + 16);\n"
      "        for (; n != 0; n--, d++)\n            afx_add_emitter_data(d);",
      "            return 0;\n        n = *(uint32_t *)(h + 12);\n"
      "        d = (AcidEmitterData *)(h + 16);\n"
      "        for (; n != 0; n--, d++)\n            afx_add_emitter_data(d);"),
    M("load-data-ver-off", "        if (*(int32_t *)(h + 8) != ACID_DATAS_VERSION)\n"
      "            return 1;\n        n = *(uint32_t *)(h + 12);\n"
      "        d = (AcidEmitterData *)(h + 16);\n"
      "        for (; n != 0; n--, d++)\n            afx_add_emitter_data(d);",
      "        if (*(int32_t *)(h + 4) != ACID_DATAS_VERSION)\n"
      "            return 1;\n        n = *(uint32_t *)(h + 12);\n"
      "        d = (AcidEmitterData *)(h + 16);\n"
      "        for (; n != 0; n--, d++)\n            afx_add_emitter_data(d);"),
    M("load-data-count", "        d = (AcidEmitterData *)(h + 16);\n"
      "        for (; n != 0; n--, d++)\n            afx_add_emitter_data(d);",
      "        d = (AcidEmitterData *)(h + 16);\n"
      "        for (n--; n != 0; n--, d++)\n            afx_add_emitter_data(d);"),
    M("load-data-first", "        d = (AcidEmitterData *)(h + 16);\n"
      "        for (; n != 0; n--, d++)\n            afx_add_emitter_data(d);",
      "        d = (AcidEmitterData *)(h + 16);\n"
      "        for (d++; n != 0; n--, d++)\n            afx_add_emitter_data(d);"),
    M("load-data-ret", "            afx_add_emitter_data(d);\n        return 1;",
      "            afx_add_emitter_data(d);\n        return 0;"),
    M("load-data-type", "    if (type == ACID_CHUNK_DATAS) {\n"
      "        AcidEmitterData *d;\n\n        h = pack_header(chunk);\n"
      "        if (*(int32_t *)(h + 8) != ACID_DATAS_VERSION)\n"
      "            return 1;\n        n = *(uint32_t *)(h + 12);\n"
      "        d = (AcidEmitterData *)(h + 16);\n"
      "        for (; n != 0; n--, d++)\n            afx_add_emitter_data(d);",
      "    if (type == ACID_CHUNK_EMITTERS + 2) {\n"
      "        AcidEmitterData *d;\n\n        h = pack_header(chunk);\n"
      "        if (*(int32_t *)(h + 8) != ACID_DATAS_VERSION)\n"
      "            return 1;\n        n = *(uint32_t *)(h + 12);\n"
      "        d = (AcidEmitterData *)(h + 16);\n"
      "        for (; n != 0; n--, d++)\n            afx_add_emitter_data(d);"),
    M("load-emit-ver", "        if (*(int32_t *)(h + 8) != ACID_EMITTERS_VERSION)\n"
      "            return 1;\n        n = *(uint32_t *)(h + 12);\n"
      "        e = (AcidEmitter *)(h + 16);\n        for (; n != 0; n--, e++) {",
      "        if (*(int32_t *)(h + 8) < ACID_EMITTERS_VERSION)\n"
      "            return 1;\n        n = *(uint32_t *)(h + 12);\n"
      "        e = (AcidEmitter *)(h + 16);\n        for (; n != 0; n--, e++) {"),
    M("load-emit-count", "        e = (AcidEmitter *)(h + 16);\n"
      "        for (; n != 0; n--, e++) {",
      "        e = (AcidEmitter *)(h + 16);\n"
      "        for (n++; n != 0; n--, e++) {"),
    M("load-emit-hash", "acid_emitter_set_emitter_data_hash(e, e->EmitterDataNameHash);",
      "acid_emitter_set_emitter_data_hash(e, e->NameHash);"),
    M("load-emit-no-data", "            acid_emitter_set_emitter_data_hash(e, e->EmitterDataNameHash);\n", ""),
    M("load-emit-fe", "            acid_system_add_auto_emitter(&WorldEffects, e);",
      "            acid_system_add_auto_emitter(&FrameEffects, e);"),
    M("load-emit-order", "            acid_emitter_set_emitter_data_hash(e, e->EmitterDataNameHash);\n"
      "            acid_system_add_auto_emitter(&WorldEffects, e);",
      "            acid_system_add_auto_emitter(&WorldEffects, e);\n"
      "            acid_emitter_set_emitter_data_hash(e, e->EmitterDataNameHash);"),
    M("load-emit-ret", "            acid_system_add_auto_emitter(&WorldEffects, e);\n"
      "        }\n        return 1;",
      "            acid_system_add_auto_emitter(&WorldEffects, e);\n"
      "        }\n        return 0;"),
    M("load-other", "            acid_system_add_auto_emitter(&WorldEffects, e);\n"
      "        }\n        return 1;\n    }\n    return 0;",
      "            acid_system_add_auto_emitter(&WorldEffects, e);\n"
      "        }\n        return 1;\n    }\n    return 1;"),
    # UnloaderAcidFX
    M("unload-ab", "int unloader_acid_fx(uint8_t *chunk)\n{\n"
      "    uint32_t type = bchunk_u32(chunk);\n    uint8_t *h;\n"
      "    uint32_t n;\n\n    if (type == ACID_CHUNK_A || type == ACID_CHUNK_B)\n"
      "        return 1;",
      "int unloader_acid_fx(uint8_t *chunk)\n{\n"
      "    uint32_t type = bchunk_u32(chunk);\n    uint8_t *h;\n"
      "    uint32_t n;\n\n    if (type == ACID_CHUNK_A)\n"
      "        return 1;"),
    M("unload-data-none", "            afx_remove_emitter_data(d);\n", ""),
    M("unload-data-ver", "            return 1;\n        n = *(uint32_t *)(h + 12);\n"
      "        d = (AcidEmitterData *)(h + 16);\n"
      "        for (; n != 0; n--, d++)\n            afx_remove_emitter_data(d);",
      "            return 2;\n        n = *(uint32_t *)(h + 12);\n"
      "        d = (AcidEmitterData *)(h + 16);\n"
      "        for (; n != 0; n--, d++)\n            afx_remove_emitter_data(d);"),
    M("unload-data-ret", "            afx_remove_emitter_data(d);\n        return 1;",
      "            afx_remove_emitter_data(d);\n        return 0;"),
    M("unload-emit-fe", "            acid_system_remove_auto_emitter(&WorldEffects, e);",
      "            acid_system_remove_auto_emitter(&FrameEffects, e);"),
    M("unload-emit-ver", "        if (*(int32_t *)(h + 8) != ACID_EMITTERS_VERSION)\n"
      "            return 1;\n        n = *(uint32_t *)(h + 12);\n"
      "        e = (AcidEmitter *)(h + 16);\n        for (; n != 0; n--, e++)\n"
      "            acid_system_remove_auto_emitter",
      "        if (*(int32_t *)(h + 8) != ACID_EMITTERS_VERSION)\n"
      "            return 0;\n        n = *(uint32_t *)(h + 12);\n"
      "        e = (AcidEmitter *)(h + 16);\n        for (; n != 0; n--, e++)\n"
      "            acid_system_remove_auto_emitter"),
    M("unload-emit-ret", "            acid_system_remove_auto_emitter(&WorldEffects, e);\n"
      "        return 1;\n    }\n    return 0;",
      "            acid_system_remove_auto_emitter(&WorldEffects, e);\n"
      "        return 0;\n    }\n    return 0;"),
    M("unload-other", "            acid_system_remove_auto_emitter(&WorldEffects, e);\n"
      "        return 1;\n    }\n    return 0;",
      "            acid_system_remove_auto_emitter(&WorldEffects, e);\n"
      "        return 1;\n    }\n    return 1;"),
    # afxUpdateTextures
    M("tex-null-only", "if (t == NULL || t->NameHash != d->TextureNameHash)",
      "if (t == NULL)"),
    M("tex-always", "if (t == NULL || t->NameHash != d->TextureNameHash)",
      "if (1)"),
    M("tex-hash-eq", "if (t == NULL || t->NameHash != d->TextureNameHash)",
      "if (t == NULL || t->NameHash != d->NameHash)"),
    M("tex-args", "GetTextureInfo(d->TextureNameHash, 0, 0);",
      "GetTextureInfo(d->TextureNameHash, 1, 0);"),
    M("tex-args2", "GetTextureInfo(d->TextureNameHash, 0, 0);",
      "GetTextureInfo(d->TextureNameHash, 0, 1);"),
    M("tex-keep-null", "            d->Texture = GetTextureInfo(d->TextureNameHash, 0, 0);",
      "            { void *x = GetTextureInfo(d->TextureNameHash, 0, 0);"
      " if (x) d->Texture = x; }"),
    # the data list
    M("add-data-head", "    add_tail(&EmitterDataList, &d->Node);",
      "    add_head(&EmitterDataList, &d->Node);"),
    M("remove-data-none", "    unlink_node(&d->Node);\n}\n\nAcidEmitterData",
      "    (void)d;\n}\n\nAcidEmitterData"),
    # afxGetEmitterData
    M("gd-both-zero", "    if (name_hash == 0 && group_hash == 0)\n        return NULL;\n"
      "    n = after != NULL ? after->Node.next : EmitterDataList.next;",
      "    n = after != NULL ? after->Node.next : EmitterDataList.next;"),
    M("gd-after-self", "n = after != NULL ? after->Node.next : EmitterDataList.next;",
      "n = after != NULL ? &after->Node : EmitterDataList.next;"),
    M("gd-after-ignored", "n = after != NULL ? after->Node.next : EmitterDataList.next;",
      "n = EmitterDataList.next;"),
    M("gd-group-only", "            if (d->GroupNameHash == group_hash)\n"
      "                return d;", "            if (d->NameHash == group_hash)\n"
      "                return d;"),
    M("gd-name-only", "            if (d->NameHash == name_hash)\n"
      "                return d;\n        } else if (d->NameHash == name_hash\n",
      "            if (d->GroupNameHash == name_hash)\n"
      "                return d;\n        } else if (d->NameHash == name_hash\n"),
    M("gd-both-name", "        } else if (d->NameHash == name_hash\n"
      "                   && d->GroupNameHash == group_hash) {",
      "        } else if (d->NameHash == name_hash) {"),
    M("gd-both-group", "        } else if (d->NameHash == name_hash\n"
      "                   && d->GroupNameHash == group_hash) {",
      "        } else if (d->GroupNameHash == group_hash) {"),
    # afxGetEmitter
    M("ge-fe", "    bNode *list = &WorldEffects.AutoEmitterList;",
      "    bNode *list = &FrameEffects.AutoEmitterList;"),
    M("ge-both-zero", "    if (name_hash == 0 && group_hash == 0)\n        return NULL;\n"
      "    n = after != NULL ? after->Node.next : list->next;",
      "    n = after != NULL ? after->Node.next : list->next;"),
    M("ge-after-ignored", "n = after != NULL ? after->Node.next : list->next;",
      "n = list->next;"),
    M("ge-name-own", "                if (d != NULL && d->NameHash == name_hash)",
      "                if (d != NULL && e->NameHash == name_hash)"),
    M("ge-name-group", "                if (d != NULL && d->NameHash == name_hash)\n"
      "                    return e;\n                continue;",
      "                if (d != NULL && d->NameHash == name_hash)\n"
      "                    return e;"),
    M("ge-name-data", "            if (e->NameHash != name_hash)\n                continue;",
      "            if (d == NULL || d->NameHash != name_hash)\n                continue;"),
    M("ge-name-skip", "            if (e->NameHash != name_hash)\n                continue;\n",
      ""),
    M("ge-group", "        if (d != NULL && d->GroupNameHash == group_hash)\n"
      "            return e;\n    }\n    return NULL;\n}\n\nAcidEmitter *afx_copy",
      "        if (d != NULL && d->NameHash == group_hash)\n"
      "            return e;\n    }\n    return NULL;\n}\n\nAcidEmitter *afx_copy"),
    # afxCopyEmitter
    M("cp-no-memset", "    if (e != NULL)\n        memset(&e->NameHash, 0, sizeof *e - offsetof(AcidEmitter, NameHash));\n",
      ""),
    M("cp-count-inside", "    NumAcidEmitters++;\n    if (e == NULL)\n        return NULL;",
      "    if (e == NULL)\n        return NULL;\n    NumAcidEmitters++;"),
    M("cp-count-twice", "    NumAcidEmitters++;\n    if (e == NULL)\n        return NULL;",
      "    NumAcidEmitters += 2;\n    if (e == NULL)\n        return NULL;"),
    M("cp-hash-own", "    e->NameHash = bchunk_hash(src->Name);",
      "    e->NameHash = src->NameHash;"),
    M("cp-no-hash", "    e->NameHash = bchunk_hash(src->Name);\n", ""),
    M("cp-name-62", "    b_strncpy(e->Name, src->Name, 63);",
      "    b_strncpy(e->Name, src->Name, 62);"),
    M("cp-name-64", "    b_strncpy(e->Name, src->Name, 63);",
      "    b_strncpy(e->Name, src->Name, 64);"),
    M("cp-no-name", "    b_strncpy(e->Name, src->Name, 63);\n", ""),
    M("cp-no-term", "    e->Name[63] = '\\0';\n", ""),
    M("cp-no-data", "    acid_emitter_set_emitter_data(e, src->EmitterData);\n", ""),
    M("cp-no-world", "    e->LocalWorld = src->LocalWorld;\n", ""),
    M("cp-state", "    e->LocalWorld = src->LocalWorld;\n",
      "    e->LocalWorld = src->LocalWorld;\n    e->State = src->State;\n"),
    M("cp-seed", "    e->LocalWorld = src->LocalWorld;\n",
      "    e->LocalWorld = src->LocalWorld;\n    e->RandomSeed = src->RandomSeed;\n"),
    M("cp-dh", "    e->LocalWorld = src->LocalWorld;\n",
      "    e->LocalWorld = src->LocalWorld;\n"
      "    e->EmitterDataNameHash = src->EmitterDataNameHash;\n"),
    # afxGetEmitters and afxDeleteEmitters
    M("gs-head", "            add_tail(list, &c->Node);",
      "            add_head(list, &c->Node);"),
    M("gs-group", "while ((e = afx_get_emitter(0, group_hash, e)) != NULL) {",
      "while ((e = afx_get_emitter(group_hash, 0, e)) != NULL) {"),
    M("gs-first-only", "            add_tail(list, &c->Node);\n    }\n}",
      "            add_tail(list, &c->Node);\n        break;\n    }\n}"),
    M("ds-flags", "        acid_emitter_delete((AcidEmitter *)n, 3);",
      "        acid_emitter_delete((AcidEmitter *)n, 2);"),
    M("ds-no-delete", "        acid_emitter_delete((AcidEmitter *)n, 3);\n", ""),
    # SetEmitterData
    M("sd-null", "    if (d == NULL)\n        return 0;\n    e->EmitterData = d;",
      "    e->EmitterData = d;\n    if (d == NULL)\n        return 0;"),
    M("sd-ret", "    e->EmitterData = d;\n    return 1;",
      "    e->EmitterData = d;\n    return 2;"),
    M("sd-null-ret", "    if (d == NULL)\n        return 0;\n    e->EmitterData = d;",
      "    if (d == NULL)\n        return -1;\n    e->EmitterData = d;"),
    M("sh-group", "afx_get_emitter_data(hash, 0, NULL));",
      "afx_get_emitter_data(0, hash, NULL));"),
    # the deletes
    M("ed-no-count", "    NumAcidEmitters--;\n    if (flags & 1)\n"
      "        bSlotFree(AcidEmitterSlotPool, e);",
      "    if (flags & 1)\n        bSlotFree(AcidEmitterSlotPool, e);"),
    M("ed-flag-2", "    if (flags & 1)\n        bSlotFree(AcidEmitterSlotPool, e);",
      "    if (flags & 2)\n        bSlotFree(AcidEmitterSlotPool, e);"),
    M("ed-flag-any", "    if (flags & 1)\n        bSlotFree(AcidEmitterSlotPool, e);",
      "    if (flags)\n        bSlotFree(AcidEmitterSlotPool, e);"),
    M("gx-no-emitter", "    g->Emitter = NULL;\n", ""),
    M("gx-no-data", "    g->EmitterData = NULL;\n", ""),
    M("gx-no-particles", "        unlink_node(p);\n        bSlotFree(AcidParticleSlotPool, p);",
      "        unlink_node(p);"),
    M("gx-particle-pool", "        bSlotFree(AcidParticleSlotPool, p);",
      "        bSlotFree(AcidActiveGroupSlotPool, p);",
      pre="        unlink_node(p);\n"),
    M("gx-flag", "    if (flags & 1)\n        bSlotFree(AcidActiveGroupSlotPool, g);",
      "    if (flags & 2)\n        bSlotFree(AcidActiveGroupSlotPool, g);"),
    M("gx-pool", "        bSlotFree(AcidActiveGroupSlotPool, g);",
      "        bSlotFree(AcidParticleSlotPool, g);"),
    # the system's constructor
    M("ct-no-act-next", "    s->ActiveGroupList.next = &s->ActiveGroupList;\n", ""),
    M("ct-no-auto-prev", "    s->AutoEmitterList.prev = &s->AutoEmitterList;\n", ""),
    M("ct-cur", "    s->CurrentEmitter = NULL;\n", ""),
    M("ct-sel", "    s->SelectEmitterIndex = 0;\n", ""),
    M("ct-debug", "    s->DebugStats = 0;\n", ""),
    M("ct-cems", "    s->CreateEmitterMaxScript = 0;\n", ""),
    M("ct-pad", "    s->pad = 0;\n", ""),
    M("ct-pel", "    s->PrintEmitterList = 0;\n", ""),
    M("ct-pne", "    s->PrintNearbyEmitters = 0;\n", ""),
    M("ct-osc", "    s->OnlyShowCurrentEmitter = 0;\n", ""),
    M("ct-num", "    s->NumAutoEmitters = 0;\n", ""),
    M("ct-nvp", "    s->NumVisibleParticles = 0;\n", ""),
    M("ct-rt", "    s->RenderTime = 0.0f;\n", ""),
    M("ct-ut", "    s->UpdateTime = 0.0f;\n", ""),
    M("ct-ip", "    s->UpdateTime = 0.0f;\n",
      "    s->UpdateTime = 0.0f;\n    s->InterestPoints[0].x = 0.0f;\n"),
    # AddAutoEmitter
    M("aa-seed-always", "    if (e->RandomSeed == 0) {\n        AcidRandomSeed",
      "    if (1) {\n        AcidRandomSeed",
      pre="{\n"),
    M("aa-seed-never", "    if (e->RandomSeed == 0) {\n        AcidRandomSeed",
      "    if (0) {\n        AcidRandomSeed",
      pre="{\n"),
    M("aa-seed-no-step", "        AcidRandomSeed = acid_xorshift(AcidRandomSeed);\n", "",
      pre="{\n    if (e->RandomSeed == 0) {\n"),
    M("aa-seed-scale", "                                             * 2147483648.0f);",
      "                                             * 2147483520.0f);",
      pre="{\n    if (e->RandomSeed == 0) {\n        AcidRandomSeed = acid_xorshift(AcidRandomSeed);\n        e->RandomSeed = (uint32_t)ee_trunc_w(acid_unit(AcidRandomSeed)\n"),
    M("aa-seed-trunc", "e->RandomSeed = (uint32_t)ee_trunc_w(acid_unit(AcidRandomSeed)\n"
      "                                             * 2147483648.0f);",
      "e->RandomSeed = (uint32_t)(acid_unit(AcidRandomSeed)\n"
      "                                             * 2147483648.0f);",
      pre="{\n    if (e->RandomSeed == 0) {\n        AcidRandomSeed = acid_xorshift(AcidRandomSeed);\n        "),
    M("aa-seed-raw", "e->RandomSeed = (uint32_t)ee_trunc_w(acid_unit(AcidRandomSeed)\n"
      "                                             * 2147483648.0f);",
      "e->RandomSeed = AcidRandomSeed;",
      pre="{\n    if (e->RandomSeed == 0) {\n        AcidRandomSeed = acid_xorshift(AcidRandomSeed);\n        "),
    M("aa-null-data", "    if (e->EmitterData == NULL || e->State == ACID_DISABLED) {",
      "    if (e->State == ACID_DISABLED) {"),
    M("aa-disabled", "    if (e->EmitterData == NULL || e->State == ACID_DISABLED) {",
      "    if (e->EmitterData == NULL) {"),
    M("aa-disabled-keep", "        e->State = ACID_DISABLED;\n        add_tail(&s->AutoEmitterList, &e->Node);\n"
      "    } else if",
      "        add_tail(&s->AutoEmitterList, &e->Node);\n    } else if"),
    M("aa-disabled-head", "        e->State = ACID_DISABLED;\n        add_tail(&s->AutoEmitterList, &e->Node);\n"
      "    } else if",
      "        e->State = ACID_DISABLED;\n        add_head(&s->AutoEmitterList, &e->Node);\n"
      "    } else if"),
    M("aa-unsigned", "} else if ((uint32_t)e->State < 2) {",
      "} else if (e->State < 2) {"),
    M("aa-two", "} else if ((uint32_t)e->State < 2) {",
      "} else if ((uint32_t)e->State < 1) {"),
    M("aa-on-off", "        if (e->State != ACID_OFF) {\n            cycle = d->OnCycle;",
      "        if (e->State == ACID_OFF) {\n            cycle = d->OnCycle;"),
    M("aa-on-var", "            var = d->OnCycleVariance;",
      "            var = d->OffCycleVariance;",
      pre="            cycle = d->OnCycle;\n"),
    M("aa-off-cycle", "            cycle = d->OffCycle;", "            cycle = d->OnCycle;",
      pre="        } else {\n"),
    M("aa-off-var", "            var = d->OffCycleVariance;\n        }",
      "            var = d->OnCycleVariance;\n        }"),
    M("aa-zero", "        if (cycle != 0.0f) {", "        if (cycle > 0.0f) {",
      pre="        }\n"),
    M("aa-zero-always", "        if (cycle != 0.0f) {", "        if (1) {",
      pre="        }\n"),
    M("aa-w", "            float w = var * cycle;", "            float w = var;",
      pre="        if (cycle != 0.0f) {\n"),
    M("aa-no-step", "            e->RandomSeed = acid_xorshift(e->RandomSeed);\n", "",
      pre="\n"),
    M("aa-sub", "            cycle = cycle - w;\n", "",
      pre="            e->RandomSeed = acid_xorshift(e->RandomSeed);\n"),
    M("aa-add", "            cycle = cycle + acid_unit(e->RandomSeed) * w;",
      "            cycle = cycle + acid_unit(e->RandomSeed) * var;",
      pre="            cycle = cycle - w;\n"),
    M("aa-double", "            cycle = cycle - w;\n"
      "            cycle = cycle + acid_unit(e->RandomSeed) * w;",
      "            cycle = (float)((double)cycle - (double)w\n"
      "                            + (double)acid_unit(e->RandomSeed)"
      " * (double)w);"),
    M("aa-unit-old", "            e->RandomSeed = acid_xorshift(e->RandomSeed);\n"
      "            cycle = cycle - w;\n"
      "            cycle = cycle + acid_unit(e->RandomSeed) * w;",
      "            cycle = cycle - w;\n"
      "            cycle = cycle + acid_unit(e->RandomSeed) * w;\n"
      "            e->RandomSeed = acid_xorshift(e->RandomSeed);"),
    M("aa-on-tail", "        add_head(&s->AutoEmitterList, &e->Node);\n"
      "        e->RemainingCycleTime = cycle;",
      "        add_tail(&s->AutoEmitterList, &e->Node);\n"
      "        e->RemainingCycleTime = cycle;"),
    M("aa-no-rc", "        e->RemainingCycleTime = cycle;\n", "",
      pre="        add_head(&s->AutoEmitterList, &e->Node);\n"),
    M("aa-no-ec", "        e->EmissionCountdown = 0.0f;\n", "",
      pre="        e->RemainingCycleTime = cycle;\n"),
    M("aa-ec-cycle", "        e->EmissionCountdown = 0.0f;\n",
      "        e->EmissionCountdown = cycle;\n",
      pre="        e->RemainingCycleTime = cycle;\n"),
    M("aa-library", "        if (e->State != ACID_LIBRARY)\n            e->State = ACID_DISABLED;",
      "        e->State = ACID_DISABLED;"),
    M("aa-other-keep", "        if (e->State != ACID_LIBRARY)\n            e->State = ACID_DISABLED;",
      "        (void)0;"),
    M("aa-other-head", "            e->State = ACID_DISABLED;\n"
      "        add_tail(&s->AutoEmitterList, &e->Node);\n    }\n    s->NumAutoEmitters++;",
      "            e->State = ACID_DISABLED;\n"
      "        add_head(&s->AutoEmitterList, &e->Node);\n    }\n    s->NumAutoEmitters++;"),
    M("aa-no-count", "    }\n    s->NumAutoEmitters++;\n}", "    }\n}"),
    M("aa-count-on-only", "        e->EmissionCountdown = 0.0f;\n    } else {",
      "        e->EmissionCountdown = 0.0f;\n        s->NumAutoEmitters--;\n"
      "    } else {"),
    # RemoveAutoEmitter and KillAllActiveEffects
    M("ra-no-count", "    unlink_node(&e->Node);\n    s->NumAutoEmitters--;",
      "    unlink_node(&e->Node);"),
    M("ra-no-unlink", "    unlink_node(&e->Node);\n    s->NumAutoEmitters--;",
      "    s->NumAutoEmitters--;"),
    M("kill-flags", "        acid_active_group_delete((AcidActiveGroup *)g, 3);",
      "        acid_active_group_delete((AcidActiveGroup *)g, 2);"),
    M("kill-no-unlink", "        unlink_node(g);\n        acid_active_group_delete",
      "        s->ActiveGroupList.next = g->next;\n        acid_active_group_delete"),
    # the draws
    M("next-no-step", "    *seed = acid_xorshift(*seed);\n    return acid_unit(*seed);",
      "    return acid_unit(acid_xorshift(*seed));"),
    M("bam-360", "* 65536.0f) / 360);", "* 65536.0f) / 359);"),
    M("bam-scale", "* 65536.0f) / 360);", "* 65535.0f) / 360);"),
    M("bam-half", "ee_trunc_w((u * full - half)", "ee_trunc_w((u * full + half)"),
    # UpdateInterestPoints
    M("uip-order", "        EVIEW_ID_PLAYER1, EVIEW_ID_PLAYER2, EVIEW_ID_FRONTEND",
      "        EVIEW_ID_PLAYER2, EVIEW_ID_PLAYER1, EVIEW_ID_FRONTEND"),
    M("uip-12", "                   sizeof s->InterestPoints[i]);",
      "                   12);"),
    M("uip-target", "&c->CurrentKey.Position,", "&c->CurrentKey.Target,"),
    # TriggerEmitter: the gates
    M("tr-ip-2", "    for (i = 0; i < 3; i++) {\n        float dx = e->LocalWorld.v3.x",
      "    for (i = 0; i < 2; i++) {\n        float dx = e->LocalWorld.v3.x"),
    M("tr-farclip-le", "sqrtf(dx * dx + dy * dy + dz * dz) < d->FarClip",
      "sqrtf(dx * dx + dy * dy + dz * dz) <= d->FarClip"),
    M("tr-dist-2d", "sqrtf(dx * dx + dy * dy + dz * dz) < d->FarClip",
      "sqrtf(dx * dx + dy * dy) < d->FarClip"),
    M("tr-seed-far", "    if (e->RandomSeed == 0) {\n"
      "        AcidRandomSeed = acid_xorshift(AcidRandomSeed);\n"
      "        e->RandomSeed = (uint32_t)ee_trunc_w(acid_unit(AcidRandomSeed)\n"
      "                                             * 2147483648.0f);\n    }\n"
      "    if (!close_enough)\n        return;\n",
      "    if (!close_enough)\n        return;\n"
      "    if (e->RandomSeed == 0) {\n"
      "        AcidRandomSeed = acid_xorshift(AcidRandomSeed);\n"
      "        e->RandomSeed = (uint32_t)ee_trunc_w(acid_unit(AcidRandomSeed)\n"
      "                                             * 2147483648.0f);\n    }\n"),
    M("tr-on-gate", "    if (e->State != ACID_ON && !(time_step < 0.0f))\n        return;",
      "    if (e->State != ACID_ON)\n        return;"),
    M("tr-gate-le", "    if (e->State != ACID_ON && !(time_step < 0.0f))",
      "    if (e->State != ACID_ON && !(time_step <= 0.0f))"),
    M("tr-rc-zero", "if (e->RemainingCycleTime != 0.0f && e->RemainingCycleTime < ets)",
      "if (e->RemainingCycleTime < ets)"),
    M("tr-burst-sign", "        ets = -time_step;\n    }", "        ets = time_step;\n    }"),
    M("tr-ec-le", "    if (ec < ets) {\n        g = e->LastActiveGroup;",
      "    if (ec <= ets) {\n        g = e->LastActiveGroup;"),
    # the group
    M("tr-lag-emitter", "(g == NULL || g->Emitter != e || g->pCar != car)",
      "(g == NULL || g->pCar != car)"),
    M("tr-lag-car", "(g == NULL || g->Emitter != e || g->pCar != car)",
      "(g == NULL || g->Emitter != e)"),
    M("tr-full-ignored", "            && !bIsSlotPoolFull(AcidActiveGroupSlotPool)) {",
      "            ) {"),
    M("tr-group-head", "            add_tail(&s->ActiveGroupList, &g->Node);",
      "            add_head(&s->ActiveGroupList, &g->Node);"),
    M("tr-no-lag", "            e->LastActiveGroup = g;\n", ""),
    M("tr-group-car", "            g->pCar = car;\n", "            g->pCar = NULL;\n"),
    # the constants
    M("tr-angle-scale", "d->InitialAngleRange * 182.04445f;",
      "d->InitialAngleRange * 182.0f;"),
    M("tr-angle-half", "float angle = -angle_range * 0.5f;",
      "float angle = angle_range * 0.5f;"),
    M("tr-npv", "float npv = d->NumParticlesVariance * d->NumParticles;",
      "float npv = d->NumParticlesVariance;"),
    M("tr-spv", "float spv = d->SpeedVariance * d->Speed;",
      "float spv = d->SpeedVariance;"),
    M("tr-miv", "float miv = d->MotionInheritVariance * d->MotionInherit;",
      "float miv = d->MotionInheritVariance;"),
    M("tr-lv", "float lv = d->LifeVariance * d->Life;", "float lv = d->LifeVariance;"),
    M("tr-half", "half = full * 0.5f;", "half = full * 0.25f;"),
    M("tr-np", "float np = d->NumParticles - npv;", "float np = d->NumParticles;"),
    M("tr-speed", "float speed = d->Speed - spv;", "float speed = d->Speed;"),
    M("tr-life", "float life = d->Life - lv;", "float life = d->Life;"),
    M("tr-mi", "float mi = d->MotionInherit - miv;", "float mi = d->MotionInherit;"),
    M("tr-start-frame", "            if (d->RandomStartFrame)\n                num_anim_frames",
      "            if (0)\n                num_anim_frames"),
    M("tr-frames-w", "                    << ((int8_t)d->ContactSheetH & 31));\n            pdir.w",
      "                    << ((int8_t)d->ContactSheetW & 31));\n            pdir.w"),
    # the loop and the direction
    M("tr-loop-lt", "            while (ec <= ets) {", "            while (ec < ets) {"),
    M("tr-disc-off", "                if (d->SpreadAsDisc) {", "                if (0) {"),
    M("tr-spin-range", "spread_bam(acid_next(&seed), 360.0f,\n"
      "                                               180.0f);",
      "spread_bam(acid_next(&seed), 360.0f,\n"
      "                                               90.0f);"),
    M("tr-disc-order",
      "                    uint16_t yaw = spread_bam(acid_next(&seed), full, half);\n"
      "                    uint16_t spin = spread_bam(acid_next(&seed), 360.0f,\n"
      "                                               180.0f);",
      "                    uint16_t spin = spread_bam(acid_next(&seed), 360.0f,\n"
      "                                               180.0f);\n"
      "                    uint16_t yaw = spread_bam(acid_next(&seed), full, half);"),
    M("tr-disc-cos-sin", "                    pdir.x = bCosBam(spin);\n"
      "                    pdir.y = bSinBam(spin);",
      "                    pdir.x = bSinBam(spin);\n"
      "                    pdir.y = bCosBam(spin);"),
    M("tr-disc-z", "                    pdir.z = 0.0f;\n", "                    pdir.z = 1.0f;\n"),
    M("tr-disc-rot", "eRotateY(&rot, &eMathIdentityMatrix, yaw);",
      "eRotateX(&rot, &eMathIdentityMatrix, yaw);"),
    M("tr-disc-no-orient", "                    eMulVector4(&pdir, &local_orientation, &pdir);\n", ""),
    M("tr-xyz-order", "                    eRotateX(&rot, &eMathIdentityMatrix, ax);\n"
      "                    eRotateY(&rot, &rot, ay);",
      "                    eRotateY(&rot, &eMathIdentityMatrix, ay);\n"
      "                    eRotateX(&rot, &rot, ax);"),
    M("tr-no-z", "                    eRotateZ(&rot, &rot, az);\n", ""),
    M("tr-axis-v2", "eMulVector4(&pdir, &rot, &local_world.v2);",
      "eMulVector4(&pdir, &rot, &local_world.v1);"),
    # the place, the frame, life, angle and speed
    M("tr-vol-x", "+ (u * d->VolumeExtent.x - d->VolumeExtent.x * 0.5f);",
      "+ (u * d->VolumeExtent.x);"),
    M("tr-vol-y-center", "                ppos.y = d->VolumeCenter.y\n",
      "                ppos.y = d->VolumeCenter.x\n"),
    M("tr-ppos-w", "                ppos.w = 1.0f;\n", "                ppos.w = 0.0f;\n"),
    M("tr-ppos-world", "eMulVector4(&ppos, &local_world, &ppos);",
      "eMulVector4(&ppos, &local_orientation, &ppos);"),
    M("tr-frame-draw", "anim_frame = (uint32_t)ee_trunc_w(acid_next(&seed)",
      "anim_frame = (uint32_t)ee_trunc_w(acid_unit(seed)"),
    M("tr-life-var", "plife = life + acid_next(&seed) * lv;",
      "plife = life + acid_next(&seed) * life;"),
    M("tr-angle-var", "fangle = angle + acid_next(&seed) * angle_range;",
      "fangle = angle + acid_next(&seed) * angle;"),
    M("tr-speed-var", "pspeed = speed + acid_next(&seed) * spv;",
      "pspeed = speed + acid_next(&seed) * speed;"),
    M("tr-draw-order", "                plife = life + acid_next(&seed) * lv;\n"
      "                fangle = angle + acid_next(&seed) * angle_range;",
      "                fangle = angle + acid_next(&seed) * angle_range;\n"
      "                plife = life + acid_next(&seed) * lv;"),
    # the inherited motion
    M("tr-mi-always", "                if (mi != 0.0f) {", "                if (1) {"),
    M("tr-inherit-hi", "                    if (!(inherit < 1.0f))\n"
      "                        inherit = 1.0f;\n", ""),
    M("tr-motionlive", "                    if (!d->MotionLive) {", "                    if (1) {"),
    M("tr-vel-iv", "+ inherit * e->InheritVelocity.x;", "+ e->InheritVelocity.x;"),
    M("tr-vel-y", "float vy = pspeed * pdir.y\n", "float vy = pspeed * pdir.x\n"),
    M("tr-len", "float len2 = vx * vx + vy * vy + vz * vz;",
      "float len2 = vx * vx + vy * vy;"),
    M("tr-pspeed-keep", "                        pspeed = sqrtf(len2);\n", ""),
    M("tr-q", "                        q = 1.0f / sqrtf(len2);",
      "                        q = 1.0f / len2;"),
    # the particle
    M("tr-angle-mask", "& 0xfffeu;", "& 0xffffu;"),
    M("tr-rrd", "                pangle |= seed & 1u;", "                pangle |= 1u;"),
    M("tr-rrd-always", "                if (d->RandomRotationDirection)\n"
      "                    pangle |= seed & 1u;", "                pangle |= seed & 1u;"),
    M("tr-cap-60", "                if (60.0f < plife)\n                    plife = 60.0f;",
      "                if (32.0f < plife)\n                    plife = 32.0f;"),
    M("tr-dontemit", "                if (e->DontEmit == 0\n", "                if (1\n"),
    M("tr-pp-full", "                    && !bIsSlotPoolFull(AcidParticleSlotPool)) {",
      "                    ) {"),
    M("tr-sp-clamp", "                    if (!(sp < 65535.0f))           // gp-32100\n"
      "                        sp = 65535.0f;\n", ""),
    M("tr-sp-scale", "float sp = pspeed * 128.0f;", "float sp = pspeed * 127.0f;"),
    M("tr-vz-127", "p->VZ = (int8_t)ee_trunc_w(pdir.z * 127.0f);",
      "p->VZ = (int8_t)ee_trunc_w(pdir.z * 128.0f);"),
    M("tr-vx-y", "p->VX = (int8_t)ee_trunc_w(pdir.x * 127.0f);",
      "p->VX = (int8_t)ee_trunc_w(pdir.y * 127.0f);"),
    M("tr-inherit-255", "p->Inherit = (uint8_t)ee_trunc_w(inherit * 255.0f);",
      "p->Inherit = (uint8_t)ee_trunc_w(inherit * 256.0f);"),
    M("tr-life-1024", "p->Life = (uint16_t)ee_trunc_w(plife * 1024.0f);",
      "p->Life = (uint16_t)ee_trunc_w(plife * 1000.0f);"),
    M("tr-xyz", "                    p->Y = py;\n", "                    p->Y = px;\n"),
    M("tr-particle-head", "                    add_tail(&g->ParticleList, &p->Node);",
      "                    add_head(&g->ParticleList, &p->Node);"),
    # the countdown
    M("tr-ec-rate", "ec = 1.0f / (np + acid_next(&seed) * npv);", "ec = 1.0f / np;"),
    M("tr-ec-240", "                if (240.0f < ec)\n                    ec = 240.0f;",
      "                if (120.0f < ec)\n                    ec = 120.0f;"),
    M("tr-seed-store", "            e->RandomSeed = seed;\n", ""),
    M("tr-empty-keep", "            if (g->ParticleList.next == &g->ParticleList) {\n"
      "                unlink_node(&g->Node);\n"
      "                acid_active_group_delete(g, 3);\n            }\n        }\n    }",
      "        }\n    }"),
    M("tr-ec-burst", "    e->EmissionCountdown = 0.0f <= time_step ? ec - ets : 0.0f;",
      "    e->EmissionCountdown = ec - ets;"),
    M("tr-ec-final", "    e->EmissionCountdown = 0.0f <= time_step ? ec - ets : 0.0f;",
      "    e->EmissionCountdown = 0.0f <= time_step ? ec : 0.0f;"),
    # DoTimeStep: the auto emitters
    M("dt-lifestep", "int32_t lifestep = ee_trunc_w(dt * 1024.0f);",
      "int32_t lifestep = ee_trunc_w(dt * 1000.0f);"),
    M("dt-no-uip", "    acid_system_update_interest_points(s);\n"
      "    for (n = s->AutoEmitterList.next",
      "    for (n = s->AutoEmitterList.next"),
    M("dt-trigger-dt", "acid_system_trigger_emitter(s, e, dt, NULL);",
      "acid_system_trigger_emitter(s, e, -dt, NULL);"),
    M("dt-found-off", "        else if (st != ACID_OFF)\n            found = 1;",
      "        else\n            found = 1;"),
    M("dt-no-break", "        if (found)\n            break;\n", ""),
    M("dt-rct-zero", "        if (rct != 0.0f && (uint32_t)st < 2) {",
      "        if ((uint32_t)st < 2) {"),
    M("dt-rct-signed", "        if (rct != 0.0f && (uint32_t)st < 2) {",
      "        if (rct != 0.0f && st < 2) {"),
    M("dt-rct-le", "            if (!(rct <= 0.0f)) {", "            if (!(rct < 0.0f)) {"),
    M("dt-off-on-var", "                    var = d->OnCycleVariance;\n"
      "                    st = ACID_ON;",
      "                    var = d->OffCycleVariance;\n"
      "                    st = ACID_ON;"),
    M("dt-off-cycle", "                    cycle = d->OnCycle;\n                } else {",
      "                    cycle = d->OffCycle;\n                } else {"),
    M("dt-on-cycle", "                    cycle = d->OffCycle;\n                }",
      "                    cycle = d->OnCycle;\n                }"),
    M("dt-flip-st", "                    st = ACID_OFF;\n", "                    st = ACID_ON;\n"),
    M("dt-cycle-zero", "                if (cycle != 0.0f) {\n"
      "                    float w = var * cycle;",
      "                if (1) {\n                    float w = var * cycle;"),
    M("dt-no-overrun", "                    cycle = cycle + rct;\n", ""),
    M("dt-no-seed", "                    e->RandomSeed = acid_xorshift(e->RandomSeed);\n"
      "                    cycle = cycle - w;", "                    cycle = cycle - w;"),
    M("dt-ec-keep", "                e->EmissionCountdown = 0.0f;\n            }\n"
      "        }\n        if (found)", "            }\n        }\n        if (found)"),
    # the frontend's bases
    M("dt-flow-2", "gAcidGameFlowStateFn() == 3", "gAcidGameFlowStateFn() == 2"),
    M("dt-key-third", "float k0 = d->KeyPositions.x * 0.33333334f;",
      "float k0 = d->KeyPositions.x * 0.3333f;"),
    M("dt-k-order", "hermite_basis(&d->ColourBasis, &d->ColourMatrix, k0, k1, k2, k3);",
      "hermite_basis(&d->ColourBasis, &d->ColourMatrix, k0, k2, k1, k3);"),
    M("dt-size-w", "            ctrl.v3.x = d->Size.w;", "            ctrl.v3.x = d->Size.z;"),
    M("dt-ra-scale", "ctrl.v0.y = d->RelativeAngle.x * 182.04445f;",
      "ctrl.v0.y = d->RelativeAngle.x * 182.0f;"),
    M("dt-ra-row", "            ctrl.v1.y = d->RelativeAngle.y * 182.04445f;",
      "            ctrl.v1.y = d->RelativeAngle.x * 182.04445f;"),
    M("dt-ctrl-col", "            ctrl.v2.x = d->Size.z;", "            ctrl.v2.z = d->Size.z;"),
    M("dt-ctrl-garbage", "        memset(&ctrl, 0, sizeof ctrl);\n",
      "        memset(&ctrl, 0xa5, sizeof ctrl);\n"),
    M("dt-colour-ctrl", "hermite_basis(&d->ColourBasis, &d->ColourMatrix,",
      "hermite_basis(&d->ColourBasis, &ctrl,"),
    # the particles
    M("dt-mask", "<< ((int8_t)d->ContactSheetH & 31)) - 1u);",
      "<< ((int8_t)d->ContactSheetH & 31)) - 0u);"),
    M("dt-fps-1000", "fpsd = ee_trunc_w(1.0f / (float)(int8_t)d->AnimFPS * 1024.0f);",
      "fpsd = ee_trunc_w(1.0f / (float)(int8_t)d->AnimFPS * 1000.0f);"),
    M("dt-fps-unsigned", "fpsd = ee_trunc_w(1.0f / (float)(int8_t)d->AnimFPS",
      "fpsd = ee_trunc_w(1.0f / (float)d->AnimFPS"),
    M("dt-cv-yz", "            cvz = dt * c->State.Velocity.z;\n"
      "            cvy = dt * c->State.Velocity.y;",
      "            cvz = dt * c->State.Velocity.y;\n"
      "            cvy = dt * c->State.Velocity.z;"),
    M("dt-life-signed", "            int32_t old = (int16_t)p->Life;",
      "            int32_t old = p->Life;"),
    M("dt-die-lt", "            if (nl <= 0) {", "            if (nl < 0) {"),
    M("dt-frame-step", "((int32_t)frame + old / fpsd\n"
      "                                            - nl / fpsd)",
      "((int32_t)frame + 1)"),
    M("dt-frame-nomask", " - nl / fpsd) & (uint32_t)mask;", " - nl / fpsd);"),
    M("dt-spd-127", "* 0.0078125f * (1.0f / 127.0f);", "* 0.0078125f * (1.0f / 128.0f);"),
    M("dt-inh-255", "inh = (float)p->Inherit * (1.0f / 255.0f);",
      "inh = (float)p->Inherit * (1.0f / 256.0f);"),
    M("dt-sign-flip", "            sx = vx < 0.0f ? 1.0f : -1.0f;",
      "            sx = vx < 0.0f ? -1.0f : 1.0f;"),
    M("dt-grav", "vz = vz + (grav + sz * vz * (vz * drag)) * dt;",
      "vz = vz + (sz * vz * (vz * drag)) * dt;"),
    M("dt-drag-x", "vx = vx + sx * drag * (vx * vx) * dt;",
      "vx = vx + sx * drag * vx * dt;"),
    M("dt-pos-dt", "            z += vz * dt;", "            z += vz;"),
    M("dt-ml-pos", "                x += cvx * inh;", "                x += cvx;"),
    M("dt-len", "len = sqrtf(vx * vx + vy * vy + vz * vz);",
      "len = sqrtf(vx * vx + vy * vy);"),
    M("dt-speed-128", "p->Speed = (uint16_t)ee_trunc_w(len * 128.0f);",
      "p->Speed = (uint16_t)ee_trunc_w(len * 127.0f);"),
    M("dt-no-frame", "            p->Frame = (uint8_t)frame;\n", ""),
    M("dt-no-life", "            p->Life = (uint16_t)nl;\n", ""),
    M("dt-vz-store", "p->VZ = (int8_t)ee_trunc_w(vz * inv * 127.0f);",
      "p->VZ = (int8_t)ee_trunc_w(vy * inv * 127.0f);"),
    M("dt-free-empty", "        if (g->ParticleList.next == &g->ParticleList) {\n"
      "            unlink_node(&g->Node);\n"
      "            acid_active_group_delete(g, 3);\n        }\n    }\n    s->UpdateTime",
      "    }\n    s->UpdateTime"),
    M("dt-ut-order", "s->UpdateTime = bGetTickerDifference(start, bGetTicker());",
      "s->UpdateTime = bGetTickerDifference(bGetTicker(), start);"),
    M("dt-ut-no-start", "s->UpdateTime = bGetTickerDifference(start, bGetTicker());",
      "s->UpdateTime = bGetTickerDifference(0, bGetTicker());"),
    M("dt-particle-flags", "acid_particle_delete(p, 3);", "acid_particle_delete(p, 2);"),
    # hermite_basis
    M("herm-h", "{  2.0f, -2.0f,  1.0f,  1.0f },", "{  2.0f, -2.0f,  1.0f,  0.0f },",
      rel=ACIDFX),
    M("herm-m", "{ 3.0f, 2.0f, 1.0f, 0.0f }", "{ 3.0f, 2.0f, 1.0f, 1.0f }",
      rel=ACIDFX),
    M("herm-cube", "t.v2.x = k2 * k2 * k2;", "t.v2.x = k2 * k2;", rel=ACIDFX),
    M("herm-w", "t.v3.w = 1.0f;", "t.v3.w = 0.0f;", rel=ACIDFX),
    M("herm-order", "eMulMatrix(&a, &kM, &inv);", "eMulMatrix(&a, &inv, &kM);",
      rel=ACIDFX),
    M("herm-ctrl", "eMulMatrix(o, &b, ctrl);", "eMulMatrix(o, ctrl, &b);",
      rel=ACIDFX),
]

EQUIVALENT = {
    "cp-name-64": "bStrNCpy's 64th byte goes to Name[63], which the next "
                  "line clears",
    "cp-no-term": "the clear before it has zeroed Name[63], and bStrNCpy's "
                  "63 bytes stop short of it",
    "aa-disabled": "a State of 2 with a data reaches the last branch, which "
                   "sets it to 2 again and adds it to the tail",
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    disc = Disc()
    sc = script(disc)
    inputs = tempfile.TemporaryDirectory()
    scp, rec = write_inputs(inputs.name, disc, sc)
    base = model_cached(sc, disc, rec)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, rec, out)
        took = time.monotonic() - t0
        got = out.read_text(encoding="latin-1").splitlines()
        if diff(base, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "afx_test",
        lambda exe, out: mutpar.run_exe([exe, scp, rec], out, limit),
        base, diff, EQUIVALENT, jobs)
    inputs.cleanup()
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

    disc = Disc()
    sc = script(disc)
    with tempfile.TemporaryDirectory() as tmp:
        scp, rec = write_inputs(tmp, disc, sc)
        lines = model_cached(sc, disc, rec)
        exe = build_harness(tmp)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, rec, out)
        harness = out.read_text(encoding="latin-1").splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL,
                                           encoding="latin-1")
        d.with_suffix(".harness").write_text(NL.join(harness) + NL,
                                             encoding="latin-1")

    n = diff(lines, harness)
    ops = sum(len(s) for s in sc)
    print("%d scenarios, %d ops, %d lines, %d differ"
          % (len(sc), ops, len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
