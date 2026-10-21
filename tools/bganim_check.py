#!/usr/bin/env python3
"""Cross-check bganim.c, tGlobalBackgroundAnimation, against the retail
image, run in mipsemu.

The model is the image: the constructor (0x002495f0), the kept list's
Add (0x00249730), Remove (0x00249790), Count (0x002497b8), Nth
(0x002497f0) and Reset (0x00249828), Reset (0x00249888), ChangeScreenHash
(0x00249a40) and Tick (0x00249ae8) run as shipped, with RandomRange
(0x00249570), bRandom, bStringHash, SetCenter (0x0024aae0) and the
tCubic2D seek and GetVal under them. Only the Flailer is stubbed:
FindFlailerObject (0x00143d50) answers from the script's screens, and
SetAlpha (0x001411d8), SetCenterX (0x001408e8), SetCenterY (0x00140930)
and ChangeTexture (0x00141350) print what they were asked. The harness
(tools/src/bganim_test.c) runs bganim.c, with banim.c's splines and
bmath.c's bRandomI, and prints the same lines.

The script (see the harness for its ops) runs the kept list full, empty
and with duplicates; a screen with all three objects for 53 seconds at
30 frames a second, through the fade in, the drift, the fade out and the
next start; screens missing each object, none, and a NULL name; the
cross-fade's edges at 1, 49 and 50 seconds and a clock behind the start;
the parameter's wrap; a step long enough to land the spline; and random
mixes of all of it, on several seeds, with car logos kept.

Checked against the image, not diffed: FlailerScreenList's constructor
makes the 156-byte object; ChangeToScreen calls ChangeScreenHash with the
config's first Flailer hash after Activate and with 0 for a NULL name;
Tick calls Tick only in game flow state 3; and the constants' values.

    python tools/bganim_check.py
    python tools/bganim_check.py --mutate [--only a,b]
    python tools/bganim_check.py --dump out/bganim
"""
import argparse
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

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/bganim_test.c"
BGA = "3DS Files/source/bganim.c"
SOURCES = [HARNESS, BGA, "3DS Files/source/banim.c",
           "3DS Files/source/bmath.c", "3DS Files/source/bmathtab.c"]
HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = 0x003358f0
CTOR = 0x002495f0               # __26tGlobalBackgroundAnimation
KEEP_ADD = 0x00249730
KEEP_REMOVE = 0x00249790
KEEP_COUNT = 0x002497b8
KEEP_NTH = 0x002497f0
KEEP_RESET = 0x00249828
RESET = 0x00249888              # Reset__26tGlobalBackgroundAnimation
CHANGE = 0x00249a40             # ChangeScreenHash__26tGlobalBackground..i
TICK = 0x00249ae8               # Tick__26tGlobalBackgroundAnimation
FIND = 0x00143d50               # FindFlailerObject__FUiUi17FlailerObjectType
SET_ALPHA = 0x001411d8          # SetAlpha__18FlailerBitmapChunkii
SET_CX = 0x001408e8             # SetCenterX__18FlailerObjectChunkf
SET_CY = 0x00140930             # SetCenterY__18FlailerObjectChunkf
CHANGE_TEX = 0x00141350         # ChangeTexture__18FlailerBitmapChunki
G_TIMER = GP - 19608            # RealTimer
G_ELAPSED = GP - 19596          # RealTimeElapsed
G_SEED = GP - 14472             # bDefaultSeed

OBJ = 0x01000000                # the object, 156 bytes
FOBJ = 0x01001000               # the Flailer objects, 64 bytes each
MAX_SCREENS = 16
NAMES = ("GRID", "MASTER_BP_OBJECT", "FADING_BP_OBJECT")


def bhash(s):
    h = 0xffffffff
    for c in s.encode():
        h = (h * 33 + c) & 0xffffffff
    return h


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def s32(v):
    v &= 0xffffffff
    return v - (1 << 32) if v & 0x80000000 else v


# ================================================================ the script

SCREENS = [
    (bhash("NEW_MAIN_MENU"), 7), (bhash("OPTIONS"), 6), (0x00000301, 2),
    (0x00000302, 4), (0x00000303, 1), (0x00000304, 0), (0x00012345, 7),
    (0x00000306, 5), (0x00000307, 3),
]
FULL = SCREENS[0][0]
FULL2 = SCREENS[6][0]
UNREGISTERED = 0xdeadbeef
LOGOS = [bhash("CARLOGO_" + n) for n in (
    "BMW_M5", "CORVETTE_Z06", "LAMBO_DIABLO", "MERC_CLK_GTR", "VIPER_GTS",
    "MCLAREN_F1", "FERRARI_550", "PORSCHE_911")]
BLUEPRINTS = [bhash("GRID_BLUEPRINT1"), bhash("GRID_BLUEPRINT2")]
DT30 = 1.0 / 30


def tick(ops, timer, dt, dump=True):
    timer += int(fbits_f(dt) * 4000.0)
    ops.append("T %d %08x" % (timer, fbits(dt)))
    if dump:
        ops.append("D")
    return timer


def fbits_f(f):
    return struct.unpack("<f", struct.pack("<f", f))[0]


def script():
    rng = random.Random(0xb9a)
    ops = ["O %08x %x" % s for s in SCREENS]
    # The parameter landing on its wrap exactly, with no objects yet.
    ops += ["S 12345678", "I", "D", "T 0 %08x" % fbits(6.283), "D", "N"]
    ops += ["n %d" % i for i in (-1, 0, 1, 2, 3, 8)]

    # The kept list.
    for h in LOGOS[:3]:
        ops += ["A %08x" % h, "D"]
    ops += ["A %08x" % LOGOS[0], "D", "X %08x" % LOGOS[1], "D",
            "A %08x" % LOGOS[1], "D", "X %08x" % BLUEPRINTS[0], "D",
            "A %08x" % BLUEPRINTS[0], "D"]
    for h in LOGOS:
        ops += ["A %08x" % h, "D", "N"]
    ops += ["n %d" % i for i in range(-2, 10)]
    ops += ["A 0", "D", "X 0", "D", "X %08x" % LOGOS[7], "D",
            "A %08x" % LOGOS[7], "D", "N", "K", "D", "N"]
    ops += ["n %d" % i for i in range(-1, 4)]

    # One screen's whole cycle at 30 frames a second, and the next start.
    timer = 4000
    ops += ["S 0badc0de", "C %08x %d" % (FULL, timer), "D"]
    for _ in range(1600):
        timer = tick(ops, timer, DT30)

    # The other screens, a NULL name and one that is not there, with
    # ticks between.
    for s, _mask in SCREENS + [(0, 0), (UNREGISTERED, 0)]:
        ops += ["C %08x %d" % (s, timer), "D"]
        for _ in range(4):
            timer = tick(ops, timer, 1.0 / 60)
        ops += ["R %d" % timer, "D"]
        for _ in range(2):
            timer = tick(ops, timer, 1.0 / 60)

    # The cross-fade's edges, on a fresh start.
    for edge in (0, 1, 3999, 4000, 4001, 8000, 196000 - 1, 196000, 196001,
                 198000, 199999, 200000, 200001, 260000, -1, -4000,
                 -0x7fffffff, 0x7fffffff):
        ops += ["S %08x" % rng.randrange(1 << 32),
                "C %08x %d" % (FULL2, 100000), "D",
                "T %d %08x" % (s32(100000 + edge), fbits(0.0)), "D",
                "T %d %08x" % (s32(100000 + edge), fbits(DT30)), "D"]

    # The parameter's wrap, and steps long enough to land the spline.
    ops += ["C %08x %d" % (FULL, 0), "D"]
    for el in (6.283, 6.2829995, 6.2830005, 7.0, 13.0, 1e-7, 0.0, 3.1415,
               3.1416, -1.0, -7.0, 100.0, 45.0, 0.5, 0.25, 2.0):
        ops += ["T %d %08x" % (rng.randrange(0, 199000), fbits(el)), "D"]

    # Car logos kept while screens change, on several seeds.
    for seed in (1, 0x12345678, 0xffffffff, 0x80000000, 0x2545f491):
        ops += ["S %08x" % seed, "K"]
        for h in rng.sample(LOGOS, rng.randrange(0, 8)):
            ops.append("A %08x" % h)
        ops += ["D", "C %08x %d" % (FULL, timer), "D"]
        for _ in range(30):
            timer = tick(ops, timer, rng.choice((DT30, 1.0 / 60, 0.1)))

    # Random mixes.
    for _ in range(600):
        r = rng.random()
        if r < 0.08:
            s = rng.choice([x[0] for x in SCREENS] + [0, UNREGISTERED])
            ops += ["C %08x %d" % (s, timer), "D"]
        elif r < 0.12:
            ops += ["R %d" % timer, "D"]
        elif r < 0.17:
            ops += ["A %08x" % rng.choice(LOGOS + BLUEPRINTS), "D"]
        elif r < 0.20:
            ops += ["X %08x" % rng.choice(LOGOS + BLUEPRINTS), "D"]
        elif r < 0.21:
            ops += ["K", "D"]
        elif r < 0.23:
            ops += ["S %08x" % rng.randrange(1 << 32)]
        elif r < 0.25:
            timer += rng.randrange(0, 220000)
            ops += ["T %d %08x" % (timer, fbits(rng.uniform(0, 3))), "D"]
        else:
            timer = tick(ops, timer, rng.choice((DT30, 1.0 / 60, 1.0 / 20,
                                                 rng.uniform(0, 0.2))))
    ops += ["N"] + ["n %d" % i for i in range(-1, 9)]
    return ops


def encode(ops):
    return NL.join(ops) + NL


# ================================================================ the model

class Model(object):
    def __init__(self):
        self.e = retail_model.emu(retail=True, ieee=True)
        self.out = []
        self.screens = []
        e = self.e
        e.stub(FIND, self.find)
        e.stub(SET_ALPHA, self.alpha)
        e.stub(SET_CX, self.cx)
        e.stub(SET_CY, self.cy)
        e.stub(CHANGE_TEX, self.tex)
        e.write(FOBJ, bytes(64 * 3 * MAX_SCREENS))

    def index(self, p):
        p &= 0xffffffff
        if p == 0:
            return -1
        k, r = divmod(p - FOBJ, 64)
        return k if r == 0 and 0 <= k < 3 * MAX_SCREENS else -2

    def find(self, e):
        screen = e.reg[4] & 0xffffffff
        obj = e.reg[5] & 0xffffffff
        typ = s32(e.reg[6])
        found = -1
        for s, (h, mask) in enumerate(self.screens):
            if h != screen or found >= 0:
                continue
            for k in range(3):
                if mask >> k & 1 and typ == 2 and bhash(NAMES[k]) == obj:
                    found = s * 3 + k
        self.out.append("find s=%08x o=%08x t=%d -> %d" % (
            screen, obj, typ, found))
        return 0 if found < 0 else FOBJ + 64 * found

    def alpha(self, e):
        self.out.append("alpha o=%d a=%d c=%d" % (
            self.index(e.reg[4]), s32(e.reg[5]), s32(e.reg[6])))

    def cx(self, e):
        self.out.append("cx o=%d %08x" % (self.index(e.reg[4]), e.fpr[12]))

    def cy(self, e):
        self.out.append("cy o=%d %08x" % (self.index(e.reg[4]), e.fpr[12]))

    def tex(self, e):
        self.out.append("tex o=%d %08x" % (self.index(e.reg[4]),
                                           e.reg[5] & 0xffffffff))

    def lane(self, a):
        w = struct.unpack("<11I", self.e.read(a, 44))
        st, fl = struct.unpack("<hh", self.e.read(a + 44, 4))
        return " [%s %d %d]" % (" ".join("%08x" % x for x in w), st, fl)

    def dump(self):
        e = self.e
        kept = struct.unpack("<8I", e.read(OBJ + 124, 32))
        self.out.append(
            "D h=%08x g=%d m=%d f=%d%s%s cf=%d gt=%d p=%08x k=%s seed=%08x"
            % (e.u32(OBJ), self.index(e.u32(OBJ + 4)),
               self.index(e.u32(OBJ + 8)), self.index(e.u32(OBJ + 12)),
               self.lane(OBJ + 16), self.lane(OBJ + 64),
               s32(e.u32(OBJ + 112)), s32(e.u32(OBJ + 116)),
               e.u32(OBJ + 120), ",".join("%08x" % k for k in kept),
               e.u32(G_SEED)))

    def run(self, ops):
        e = self.e
        for op in ops:
            t = op.split()
            c = t[0]
            if c == "O":
                if len(self.screens) < MAX_SCREENS:
                    self.screens.append((int(t[1], 16), int(t[2], 16)))
            elif c == "S":
                e.put32(G_SEED, int(t[1], 16))
            elif c == "I":
                # The port's memset: retail's bMalloc'd block is whatever
                # was there, and the fields it leaves are read only after
                # a seek has rebuilt them.
                e.write(OBJ, bytes(156))
                e.call(CTOR, OBJ)
            elif c == "C":
                # Hashes go in sign-extended, as the EE's 32-bit loads
                # leave them: the kept list compares whole registers.
                e.put32(G_TIMER, int(t[2]) & 0xffffffff)
                e.call(CHANGE, OBJ, s32(int(t[1], 16)))
            elif c == "R":
                e.put32(G_TIMER, int(t[1]) & 0xffffffff)
                e.call(RESET, OBJ)
            elif c == "T":
                e.put32(G_TIMER, int(t[1]) & 0xffffffff)
                e.put32(G_ELAPSED, int(t[2], 16))
                e.call(TICK, OBJ)
            elif c == "A":
                e.call(KEEP_ADD, OBJ, s32(int(t[1], 16)))
            elif c == "X":
                e.call(KEEP_REMOVE, OBJ, s32(int(t[1], 16)))
            elif c == "N":
                self.out.append("N %d" % e.call(KEEP_COUNT, OBJ))
            elif c == "n":
                i = int(t[1])
                v = e.call(KEEP_NTH, OBJ, i)
                self.out.append("n %d %08x" % (i, v & 0xffffffff))
            elif c == "K":
                e.call(KEEP_RESET, OBJ)
            elif c == "D":
                self.dump()
        return self.out


def image_facts(m):
    """What the port takes from the image without running it."""
    e = m.e
    out = []

    def jal_at(a, target):
        return e.u32(a) == 0x0c000000 | (target >> 2)

    def word(a, w):
        return e.u32(a) == w

    out.append((word(0x0016c348, 0x2404009c)
                and jal_at(0x0016c364, 0x002577c0)
                and jal_at(0x0016c36c, CTOR) and word(0x0016c374, 0xae2201c8),
                "FlailerScreenList's constructor: bMalloc(156), the "
                "constructor, stored at +456"))
    out.append((jal_at(0x0016c548, 0x0016b068)
                and word(0x0016c550, 0x8e020010)
                and jal_at(0x0016c558, CHANGE)
                and word(0x0016c55c, 0x8c450014),
                "ChangeToScreen: Activate, then ChangeScreenHash with the "
                "config's +20, FlailerHashes[0]"))
    out.append((word(0x0016c520, 0x12800011)
                and jal_at(0x0016c56c, CHANGE)
                and word(0x0016c570, 0x0000282d),
                "ChangeToScreen: a NULL name gives ChangeScreenHash(0)"))
    out.append((word(0x0016c534, 0x1200000f),
                "ChangeToScreen: a name not found makes no call"))
    out.append((jal_at(0x0016cd24, 0x0016be20)
                and word(0x0016cd2c, 0x8f82ac54)
                and word(0x0016cd30, 0x38420003)
                and jal_at(0x0016cd3c, TICK),
                "FlailerScreenList::Tick: after the song monitor, Tick in "
                "game flow state 3 (gp-21420)"))
    for off, bits, name in ((15004, 0x3f800000, "CrossFadeTime 1.0"),
                            (14996, 0x42480000, "GridSplineDuration 50.0"),
                            (26476, 0x40c90e56, "the wrap 6.283"),
                            (26472, 0x3983126f, "RealTimer's tick 0.00025"),
                            (26480, 0x38d1b717, "RandomRange's 0.0001")):
        out.append((e.u32(GP - off) == bits,
                    "gp-%d is %s (%08x)" % (off, name, e.u32(GP - off))))
    for a, s in ((0x002befb0, "GRID_BLUEPRINT1"),
                 (0x002befc0, "GRID_BLUEPRINT2"),
                 (0x002befd0, "MASTER_BP_OBJECT"),
                 (0x002befe8, "FADING_BP_OBJECT"), (0x00331e60, "GRID")):
        got = e.read(a, len(s) + 1)
        out.append((got == s.encode() + b"\0", "%08x is %s" % (a, s)))
    return out


def model(ops):
    m = Model()
    lines = m.run(ops)
    return m, lines


# ============================================================== the harness

def build_harness(tmp, name="bganim_test"):
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

MUTATIONS = [
    ("keep-add-no-remove", BGA,
     "    bganim_keep_remove(a, hash);\n    for", "    for"),
    ("keep-add-last-slot", BGA,
     "    for (int i = 0; i < 8; i++) {\n        if (a->kept[i] == 0) {",
     "    for (int i = 7; i >= 0; i--) {\n        if (a->kept[i] == 0) {"),
    ("keep-add-overwrites-last", BGA,
     "            a->kept[i] = hash;\n            return;\n        }\n    }\n}",
     "            a->kept[i] = hash;\n            return;\n        }\n    }\n"
     "    a->kept[7] = hash;\n}"),
    ("keep-remove-first-only", BGA,
     "        if (a->kept[i] == hash) a->kept[i] = 0;",
     "        if (a->kept[i] == hash) { a->kept[i] = 0; break; }"),
    ("keep-count-all", BGA,
     "        if (a->kept[i] != 0) n++;", "        n++;"),
    ("keep-nth-counts-empties", BGA,
     "        if (a->kept[i] == 0) continue;\n", ""),
    ("keep-nth-one-based", BGA,
     "        if (n == 0) return a->kept[i];",
     "        if (n == 1) return a->kept[i];"),
    ("keep-nth-wraps", BGA,
     "        n--;\n    }\n    return 0;",
     "        n--;\n    }\n    return a->kept[0];"),
    ("keep-reset-one-blueprint", BGA,
     '    bganim_keep_add(a, bchunk_hash("GRID_BLUEPRINT2"));\n', ""),
    ("keep-reset-no-clear", BGA,
     "    memset(a->kept, 0, sizeof(a->kept));\n    bganim_keep_add",
     "    bganim_keep_add"),
    ("random-range-demo-start", BGA,
     "randomRange(160.0f, 165.0f)", "randomRange(180.0f, 200.0f)"),
    ("random-range-order", BGA,
     "        float    x0 = randomRange(160.0f, 165.0f);\n"
     "        float    y  = randomRange(180.0f, 300.0f);",
     "        float    y  = randomRange(180.0f, 300.0f);\n"
     "        float    x0 = randomRange(160.0f, 165.0f);"),
    ("random-range-end", BGA,
     "randomRange(300.0f, 400.0f)", "randomRange(300.0f, 380.0f)"),
    ("random-range-scale", BGA,
     "bRandomI(10000, bViewSeed) * 0.0001f)",
     "bRandomI(10001, bViewSeed) * 0.0001f)"),
    ("reset-master-shown", BGA,
     "        flailerbitmap_set_alpha(BITMAP(a->master), 0, "
     "FLAILER_ALL_CORNERS);\n", ""),
    ("reset-no-snap", BGA,
     "        bspline2d_set_val_desired(&a->spline, &v);\n"
     "        snapToDesired(&a->spline);\n",
     "        bspline2d_set_val_desired(&a->spline, &v);\n"),
    ("reset-y-aimed-too", BGA,
     "        v.x = x1;\n", "        v.x = x1;\n        v.y = x1;\n"),
    ("reset-demo-duration", BGA,
     "        a->spline.x.duration = GRID_SPLINE_DURATION;\n"
     "        a->spline.y.duration = GRID_SPLINE_DURATION;\n"
     "        flailerbitmap_change_texture(",
     "        a->spline.x.duration = 20.0f;\n"
     "        a->spline.y.duration = 20.0f;\n"
     "        flailerbitmap_change_texture("),
    ("reset-first-texture", BGA,
     "bganim_keep_nth(a, bRandomI(bganim_keep_count(a), bViewSeed))",
     "bganim_keep_nth(a, 0)"),
    ("reset-timer-inside", BGA,
     "    }\n    a->crossFadeTimer = realTimer;\n}",
     "        a->crossFadeTimer = realTimer;\n    }\n}"),
    ("reset-either-object", BGA,
     "    if (a->fading && a->master) {", "    if (a->fading) {"),
    ("snap-dval-kept", BGA,
     "    s->x.dval  = s->x.dvalDesired;\n", ""),
    ("change-zero-keeps-objects", BGA,
     "        a->fading = NULL;\n        a->grid   = NULL;\n"
     "        a->master = NULL;\n", ""),
    ("change-no-reset", BGA,
     "    bganim_reset(a, realTimer);\n    a->gridTimer = realTimer;",
     "    a->gridTimer = realTimer;"),
    ("change-no-grid-timer", BGA,
     "    bganim_reset(a, realTimer);\n    a->gridTimer = realTimer;",
     "    bganim_reset(a, realTimer);"),
    ("change-grid-any-type", BGA,
     '    a->grid   = flailer_find_object(screen, bchunk_hash("GRID"),\n'
     "                                    FLAILER_TYPE_BITMAP);",
     '    a->grid   = flailer_find_object(screen, bchunk_hash("GRID"), 0);'),
    ("change-objects-swapped", BGA,
     'bchunk_hash("MASTER_BP_OBJECT")', 'bchunk_hash("FADING_BP_OBJECT")'),
    ("tick-wrap-strict", BGA,
     "    if (ANIM_PARAM_WRAP <= p)", "    if (ANIM_PARAM_WRAP < p)"),
    ("tick-wrap-to-zero", BGA,
     "a->animParam = p - ANIM_PARAM_WRAP;", "a->animParam = 0.0f;"),
    ("tick-param-after-check", BGA,
     "    p            = a->animParam + realElapsed;\n"
     "    a->animParam = p;\n"
     "    if (ANIM_PARAM_WRAP <= p) a->animParam = p - ANIM_PARAM_WRAP;\n"
     "\n    if (!a->master || !a->fading) return;\n",
     "    if (!a->master || !a->fading) return;\n"
     "    p            = a->animParam + realElapsed;\n"
     "    a->animParam = p;\n"
     "    if (ANIM_PARAM_WRAP <= p) a->animParam = p - ANIM_PARAM_WRAP;\n"),
    ("tick-fading-only", BGA,
     "    if (!a->master || !a->fading) return;",
     "    if (!a->fading) return;"),
    ("tick-timer-unsigned", BGA,
     "    t = (float)(int32_t)((uint32_t)realTimer - "
     "(uint32_t)a->crossFadeTimer)",
     "    t = (float)((uint32_t)realTimer - (uint32_t)a->crossFadeTimer)"),
    ("tick-fade-in-to-255", BGA,
     "(int32_t)(t / CROSS_FADE_TIME * 128.0f)",
     "(int32_t)(t / CROSS_FADE_TIME * 255.0f)"),
    ("tick-fade-in-inclusive", BGA,
     "    if (t < CROSS_FADE_TIME)\n", "    if (t <= CROSS_FADE_TIME)\n"),
    ("tick-fade-in-rounded", BGA,
     "(int32_t)(t / CROSS_FADE_TIME * 128.0f)",
     "(int32_t)(t / CROSS_FADE_TIME * 128.0f + 0.5f)"),
    ("tick-seek-inclusive", BGA,
     "    if (t < GRID_SPLINE_DURATION) {",
     "    if (t <= GRID_SPLINE_DURATION) {"),
    ("tick-seek-fixed-step", BGA,
     "        bspline2d_seek(&a->spline, realElapsed);",
     "        bspline2d_seek(&a->spline, 1.0f / 30.0f);"),
    ("tick-centre-swapped", BGA,
     "        setCenter(a->fading, v.x, v.y);",
     "        setCenter(a->fading, v.y, v.x);"),
    ("tick-fade-out-wide", BGA,
     "    const float last = GRID_SPLINE_DURATION - 1.0f;",
     "    const float last = GRID_SPLINE_DURATION - 2.0f;"),
    ("tick-fade-out-inclusive", BGA,
     "    if (last < t && t < GRID_SPLINE_DURATION)\n",
     "    if (last <= t && t < GRID_SPLINE_DURATION)\n"),
    ("tick-fade-out-form", BGA,
     "(int32_t)((1.0f - (t - last)) * 128.0f)",
     "(int32_t)((GRID_SPLINE_DURATION - t) * 128.0f)"),
    ("tick-reset-inclusive", BGA,
     "    if (GRID_SPLINE_DURATION < t) bganim_reset",
     "    if (GRID_SPLINE_DURATION <= t) bganim_reset"),
    ("set-center-y-first", BGA,
     "    flailerobject_set_center_x(o, x);\n"
     "    flailerobject_set_center_y(o, y);",
     "    flailerobject_set_center_y(o, y);\n"
     "    flailerobject_set_center_x(o, x);"),
    ("init-demo-centre", BGA,
     "kCentre = { 320.0f, 240.0f }", "kCentre = { 320.0f, 224.0f }"),
    ("init-no-snap", BGA,
     "    bspline2d_set_val_desired(&a->spline, &kCentre);\n"
     "    snapToDesired(&a->spline);\n",
     "    bspline2d_set_val_desired(&a->spline, &kCentre);\n"),
    ("init-no-keep-reset", BGA,
     "    a->animParam = 0.0f;\n    bganim_keep_reset(a);",
     "    a->animParam = 0.0f;"),
]

# Mutations that survive because they change nothing the image can tell.
# keep-remove-first-only: a hash is never in the list twice, since Add
# takes it out before it stores it and Reset starts from an empty list.
# tick-seek-inclusive, tick-fade-out-inclusive, tick-reset-inclusive: t is
# never exactly 49 or 50. It is a float32 product of the whole ticks and
# 0.00025f, which rises with the ticks and steps from 48.99975 at 195999 to
# 49.0000038 at 196000, and from 49.99975 at 199999 to 50.0000038 at
# 200000.
# tick-fade-out-form: for t in (49, 50), t - 49 and 50 - t are exact
# (Sterbenz), and so is 1 - (t - 49), a multiple of t's 2^-18 below 1: the
# two forms give the same float.
EQUIVALENT = {"keep-remove-first-only", "tick-seek-inclusive",
              "tick-fade-out-inclusive", "tick-reset-inclusive",
              "tick-fade-out-form"}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    _m, base = model(sc)
    caught, survived, missing, equivalent = 0, [], [], []
    scdir = tempfile.TemporaryDirectory()
    scp = Path(scdir.name) / "script.txt"
    scp.write_text(encode(sc))
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, scp, out)
        if diff(base, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for m in todo:
        name, rel, before, after = m
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if text.count(probe) != 1:
            missing.append(name)
            print("  %-44s PATTERN %s" % (
                name, "NOT FOUND" if not text.count(probe) else "NOT UNIQUE"))
            continue
        new = text.replace(probe, repl, 1)
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
                rc = run_harness(exe, scp, out)
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

    sc = script()
    m, lines = model(sc)
    facts = image_facts(m)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = Path(tmp) / "script.txt"
        scp.write_text(encode(sc))
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)
        d.with_suffix(".image").write_text(
            NL.join(("   " if ok else "BAD") + " " + l for ok, l in facts) + NL)

    bad = [l for ok, l in facts if not ok]
    for l in bad:
        print("image: " + l)
    n = diff(lines, harness)
    print("image: %d facts, %d wrong" % (len(facts), len(bad)))
    print("%d steps, %d lines, %d differ" % (len(sc), len(harness), n))
    sys.exit(1 if (n or rc or bad) else 0)


if __name__ == "__main__":
    main()
