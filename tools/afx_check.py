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
(0x001274a0), RemoveAutoEmitter (0x00127688) and KillAllActiveEffects
(0x001276a8), and the deleting destructors of AcidEmitter (0x00124e20 and
its twin 0x0012a3f8) and AcidActiveGroup (0x0012a258). Under them run
bStringHash, bStrNCpy, bMemSet and the node and list destructors. The
harness (tools/src/afx_test.c) runs the port over the same script, and
the two transcripts are diffed.

Stubs, the same on both sides: the three slot pools are fixed arenas that
hand out their lowest free slot, zeroed when the pool's flags have
ZERO_ALLOCATED_MEMORY and filled with 0xa5 when not, and print each call
(bNewSlotPool 0x00257c10, bDeleteSlotPool 0x00257c48, bOMalloc 0x00257c80,
bFree(pool, p) 0x00257ca0). GetTextureInfo (0x001abf48) answers by a rule
on the hash: NULL, a texture of that name, or one whose NameHash is the
hash with its low bit flipped. bFree(void *) (0x00257850) is never
reached and stops the model if it is.

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
SOURCES = [HARNESS, ACIDC]

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

B_NEW_POOL = 0x00257c10
B_DEL_POOL = 0x00257c48
B_OMALLOC = 0x00257c80
B_FREE_SLOT = 0x00257ca0
B_FREE = 0x00257850
GET_TEXTURE_INFO = 0x001abf48

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
        e.stub(GET_TEXTURE_INFO, self.st_gti)
        for i, nm in enumerate(POOL_NAMES):
            a = 0x002b0000 + (-11480, -11456, -11432)[i]
            assert self.cstr(a) == nm, nm
        self.bufs = [Buf(k) for k in range(NBUF)]
        self.used = [bytearray(n) for n in NSLOT]
        self.fail_after = [-1] * 3
        self.reg = 0
        self.tex_hash = []
        self.txm = []

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

    def omalloc(self, p):
        i = self.pool_index(p)
        if i < 0:
            self.emit("  omalloc %s -> null" % ("null" if p == 0 else "?"))
            return 0
        if self.fail_after[i] == 0:
            self.emit("  omalloc %s -> null" % POOL_SHORT[i])
            return 0
        k = self.used[i].find(0)
        if k < 0:
            self.emit("  omalloc %s -> full" % POOL_SHORT[i])
            return 0
        if self.fail_after[i] > 0:
            self.fail_after[i] -= 1
        self.used[i][k] = 1
        a = ARENA[i] + SLOT[i] * k
        zero = self.w(p + POOL_FLAGS) & 2
        self.fill(a, SLOT[i], 0 if zero else PATB)
        self.emit("  omalloc %s -> %s" % (POOL_SHORT[i], self.nm(a)))
        return a

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

    def set_field_e(self, e, f, v):
        if f == "st":
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

    def set_field_d(self, d, f, v):
        offs = {"on": 32, "onv": 36, "off": 40, "offv": 44, "nh": 8,
                "gh": 16, "th": 12}
        if f in offs:
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
                self.set_field_e(e, t[2], t[3])
            return
        if c == "PD":
            d = self.ref(t[1])
            if d == 0:
                self.emit("  (none)")
            else:
                self.set_field_d(d, t[2], t[3])
            return
        if c == "SEED":
            self.put(G_SEED, int(t[1], 16))
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


def M(name, before, after, rel=ACIDC):
    return (name, rel, before, after)


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
      "        bSlotFree(AcidActiveGroupSlotPool, p);"),
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
      "    if (1) {\n        AcidRandomSeed"),
    M("aa-seed-never", "    if (e->RandomSeed == 0) {\n        AcidRandomSeed",
      "    if (0) {\n        AcidRandomSeed"),
    M("aa-seed-no-step", "        AcidRandomSeed = acid_xorshift(AcidRandomSeed);\n", ""),
    M("aa-seed-scale", "                                             * 2147483648.0f);",
      "                                             * 2147483520.0f);"),
    M("aa-seed-trunc", "e->RandomSeed = (uint32_t)ee_trunc_w(acid_unit(AcidRandomSeed)\n"
      "                                             * 2147483648.0f);",
      "e->RandomSeed = (uint32_t)(acid_unit(AcidRandomSeed)\n"
      "                                             * 2147483648.0f);"),
    M("aa-seed-raw", "e->RandomSeed = (uint32_t)ee_trunc_w(acid_unit(AcidRandomSeed)\n"
      "                                             * 2147483648.0f);",
      "e->RandomSeed = AcidRandomSeed;"),
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
      "            var = d->OffCycleVariance;"),
    M("aa-off-cycle", "            cycle = d->OffCycle;", "            cycle = d->OnCycle;"),
    M("aa-off-var", "            var = d->OffCycleVariance;\n        }",
      "            var = d->OnCycleVariance;\n        }"),
    M("aa-zero", "        if (cycle != 0.0f) {", "        if (cycle > 0.0f) {"),
    M("aa-zero-always", "        if (cycle != 0.0f) {", "        if (1) {"),
    M("aa-w", "            float w = var * cycle;", "            float w = var;"),
    M("aa-no-step", "            e->RandomSeed = acid_xorshift(e->RandomSeed);\n", ""),
    M("aa-sub", "            cycle = cycle - w;\n", ""),
    M("aa-add", "            cycle = cycle + acid_unit(e->RandomSeed) * w;",
      "            cycle = cycle + acid_unit(e->RandomSeed) * var;"),
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
    M("aa-no-rc", "        e->RemainingCycleTime = cycle;\n", ""),
    M("aa-no-ec", "        e->EmissionCountdown = 0.0f;\n", ""),
    M("aa-ec-cycle", "        e->EmissionCountdown = 0.0f;\n",
      "        e->EmissionCountdown = cycle;\n"),
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
