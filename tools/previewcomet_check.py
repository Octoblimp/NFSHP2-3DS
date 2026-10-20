#!/usr/bin/env python3
"""Cross-check 3DS Files/source/previewcomet.c, the Zone Preview's comet,
against the retail image itself, run in mipsemu.

The model is the image. PreviewComet's constructor (0x001614c8),
destructor (0x00161678), Enable (0x00161720), Disable (0x001617a0) and
Render (0x00161820) run as shipped, with Graph's constructor and GetValue,
Spline's constructor over an array, GetPoint, GetDerivative and
GetSecondDerivative (0x00189ad8), Evaluate and GetControlPoint, bStringHash,
bMemSet, the ePoly constructor, bIdentity and eIdentity under them. The
static initializer _GLOBAL_$I$ZonePreviewCometParams (0x00167208) runs once
over poisoned memory, and its four params blocks are printed word for word
against the port's C initializers. The harness
(tools/src/previewcomet_test.c) runs the port over the same script, and the
two transcripts are diffed.

Stubs, printing what they are given on both sides: bMalloc hands out
blocks from a patterned arena, and __builtin_vec_delete and
__builtin_delete print the block; afxGetEmitterData (0x00127120) answers
from a scripted group of datas, whatever the hashes; SetEmitterData
(0x001273c0) sets the data as retail's does; AcidEmitter's destructor
(0x00124e20) takes one off NumAcidEmitters (gp-23516); AddAutoEmitter
(0x001274a0) and RemoveAutoEmitter (0x00127688) name the system and the
emitter; GetTextureInfo (0x001abf48) answers a texture or NULL from the
script; ePoly::Render3D (0x0010ff88) prints the poly, the texture, the
matrix's place and its 16 floats, and the flags; the ePoly destructor does
nothing. The frame memory is CurrentBufferPos and CurrentBufferEnd
(gp-19388, gp-19384), with FrameMallocFailed and FrameMallocFailAmount
(gp-19372, gp-19368), over a buffer the script sizes. The model passes
Render a view of 0xdead0000, outside RAM, so a read of it would stop the
run: the harness passes NULL.

The script:

    I                       the four params blocks, word by word
    S k type n p...         spline k over n points, given with one guard
                            point before and two after (4 words each)
    P k w0 .. w51           params block k in retail's layout; w0 picks the
                            group name, 0 "ZONE_PREVIEW", 1 "SMOKE_PUFFS"
    G n                     the group has n emitter datas
    T on                    GetTextureInfo answers the texture, or NULL
    M n                     the frame memory: n bytes from its start
    C c s p                 comet c constructed over spline s with params p
                            (p < 0: the globals, -1 the Zone Preview's,
                            -2 .. -4 the driving line's)
    X c, E c, F c           destroyed (flags 2, as the mover), Enabled,
                            Disabled
    O c j st                emitter j's State set to st
    R c t                   Render at t (bits)

After each comet op the comet's record and every emitter's bytes past its
links print, then NumAcidEmitters and the frame memory's words.

Kept out of the script: nPreviewCometSegments 0 (the game's are 32 and 64,
and retail's divides by it would be the EE's FLT_MAX against the port's
infinity) and a head knee at x = 1 (the fade's divisor; the game's is 0.8).

    python tools/previewcomet_check.py
    python tools/previewcomet_check.py --mutate [--only a,b] [--jobs N]
    python tools/previewcomet_check.py --dump out/previewcomet
"""
import argparse
import math
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
from mipsemu import M32, f_to_bits, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/previewcomet_test.c"
PCC = "3DS Files/source/previewcomet.c"
SOURCES = [HARNESS, PCC] + ["3DS Files/source/" + f for f in (
    "spline.c", "graph.c", "epoly.c", "emath.c", "bmatrix.c", "bmath.c",
    "bmathtab.c", "bvector.c", "replay.c", "p32.c")]

HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = 0x003358f0
CTOR = 0x001614c8
DTOR = 0x00161678
ENABLE = 0x00161720
DISABLE = 0x001617a0
RENDER = 0x00161820
SINIT = 0x00167208
SECOND = 0x00189ad8               # Spline::GetSecondDerivative
SPL_CTOR = 0x00189238
GET_DATA = 0x00127120             # afxGetEmitterData
SET_DATA = 0x001273c0             # AcidEmitter::SetEmitterData
ADD_AUTO = 0x001274a0             # AcidEffectSystem::AddAutoEmitter
REMOVE_AUTO = 0x00127688          # AcidEffectSystem::RemoveAutoEmitter
EMITTER_DTOR = 0x00124e20         # _$_11AcidEmitter
GET_TEX = 0x001abf48              # GetTextureInfo(unsigned int, int, int)
BMALLOC = 0x002577c0
VEC_DELETE = 0x00114e90
DELETE = 0x00114e98
RENDER3D = 0x0010ff88             # ePoly::Render3D
POLY_DTOR = 0x00114db8
FRAME_FX = 0x002ef5e0             # FrameEffects
WORLD_FX = 0x002ef640             # WorldEffects
GLOBALS = 0x002fa9f0              # ZonePreviewCometParams, then the
GLOBAL_NAMES = ("ZonePreviewCometParams", "DrivingLineCometParamsEasy",
                "DrivingLineCometParamsMedium", "DrivingLineCometParamsHard")
DRIVING_TABLE = 0x002fad30        # VisibleDrivingLine's, by difficulty
CTOR_ENTRY = 0x0031eab0           # the initializer's __CTOR_LIST__ word

G_COUNT = GP - 23516              # NumAcidEmitters
G_FMPOS = GP - 19388              # CurrentBufferPos
G_FMEND = GP - 19384              # CurrentBufferEnd
G_FAILED = GP - 19372             # FrameMallocFailed
G_AMOUNT = GP - 19368             # FrameMallocFailAmount

PATTERN = 0xa5
COMETS = 0x01000000
COMET_STRIDE = 0x40
NCOMET = 3
SPL = 0x01001000
SPL_STRIDE = 0x40
NSPL = 8
PTS = 0x01010000
PTS_STRIDE = 0x1000
PRM = 0x01020000
PRM_STRIDE = 0x100
NPRM = 8
STRS = 0x01030000
GROUPS = ("ZONE_PREVIEW", "SMOKE_PUFFS")
DATAS = 0x01040000
DATA_SIZE = 544
NDATA = 8
TEX = 0x01050000
FM = 0x01060000
FM_SIZE = 0x1000
ARENA = 0x01100000
ARENA_SIZE = 0x40000
VIEW = 0xdead0000
EMITTER = 192


def fb(v):
    return f_to_bits(struct.unpack("<f", struct.pack("<f", v))[0])


def fx(w):
    """A float's bits, with every NaN the one "nan"."""
    w &= M32
    if (w & 0x7f800000) == 0x7f800000 and (w & 0x7fffff):
        return "nan"
    return "%08x" % w


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


# ================================================================ the script

def pt(x, y, z, w=0.0):
    return "%08x %08x %08x %08x" % (fb(x), fb(y), fb(z), fb(w))


def spline_op(k, typ, points, rng):
    guards = [(rng.uniform(-9, 9), rng.uniform(-9, 9), rng.uniform(-9, 9),
               rng.uniform(-1, 1)) for _ in range(3)]
    allp = [guards[0]] + list(points) + guards[1:]
    return "S %d %d %d %s" % (k, typ, len(points),
                              " ".join(pt(*p) for p in allp))


ZONE_WORDS = None


def params_words(nseg=32, dv=-15.0, tex=0x954c4637, width=1.5, height=0.0,
                 alt=0.0, lat=0.1, widths=None, heads=None, tails=None,
                 c0=(240.0, 200.0, 20.0, 255.0), c1=(180.0, 40.0, 0.0, 0.0),
                 group=0, pad=(0, 0, 0)):
    """52 words in retail's layout, the Zone Preview's unless told."""
    widths = widths if widths is not None else [
        (0.0, 0.2), (0.05, 0.7), (0.1, 1.0), (0.5, 1.0), (1.0, 0.5)]
    heads = heads if heads is not None else [
        (0.0, 0.05), (0.8, 0.95), (1.0, 0.95)]
    tails = tails if tails is not None else [
        (0.0, -0.04), (0.5, 0.47), (0.95, 0.9), (1.0, 0.95)]
    w = [group, nseg & M32, fb(dv), tex & M32, fb(width), fb(height),
         fb(alt), fb(lat)]
    for knees in (widths, heads, tails):
        n = knees[0] if isinstance(knees[0], int) else len(knees)
        pts = knees[1:] if isinstance(knees[0], int) else knees
        pts = list(pts) + [(0.0, 0.0)] * (5 - len(pts))
        w.append(n & M32)
        for x, y in pts[:5]:
            w += [fb(x), fb(y)]
    w += [p & M32 for p in pad]
    w += [fb(v) for v in c0] + [fb(v) for v in c1]
    assert len(w) == 52
    return w


def params_op(k, words):
    return "P %d %s" % (k, " ".join("%08x" % (x & M32) for x in words))


def renders(c, ts):
    return ["R %d %08x" % (c, fb(t)) for t in ts]


def road(rng, n, typ):
    pts = []
    x = y = 0.0
    a = rng.uniform(-3.1, 3.1)
    for _ in range(n):
        pts.append((x, y, rng.uniform(-3, 3), rng.uniform(-2, 2)))
        a += rng.uniform(-0.6, 0.6)
        d = rng.uniform(5, 40)
        x += d * math.cos(a)
        y += d * math.sin(a)
    return pts


def script():
    rng = random.Random(0xc0e7)
    ops = ["I"]
    # The splines: a hilly road (EXTRAPOLATE), an S (CLAMP), a ring (LOOP),
    # a type the end parameter knows nothing of, one point five times, a
    # climb straight up, and a sharp one.
    ops.append(spline_op(0, 2, [(20.0 * i, 0.4 * i * i, 2.0 * math.sin(i),
                                 0.25 * i) for i in range(10)], rng))
    ops.append(spline_op(1, 0, [(0, 0, 0), (30, 10, 1), (60, -10, 2),
                                (90, 10, 1), (120, -5, 0), (150, 0, -1)],
                         rng))
    ops.append(spline_op(2, 1, [(50 * math.cos(i * math.pi / 4),
                                 50 * math.sin(i * math.pi / 4), 0.5 * i, 1)
                                for i in range(8)], rng))
    ops.append(spline_op(3, 3, [(10 * i, 5 * (i & 1), 0, 0) for i in range(5)],
                         rng))
    ops.append(spline_op(4, 2, [(7.0, -3.0, 1.5, 0)] * 5, rng))
    ops.append(spline_op(5, 2, [(4.0, 4.0, 10.0 * i, 0) for i in range(5)],
                         rng))
    ops.append(spline_op(6, 0, [(0, 0, 0), (10, 0, 0), (10, 10, 3),
                                (-5, 12, 1)], rng))
    # The params: the Zone Preview's at 4 segments, lifted; none; one, in
    # colours past a byte; unsorted knees and short graphs.
    ops.append(params_op(0, params_words(nseg=4, alt=0.5, height=0.25,
                                         lat=2.0)))
    ops.append(params_op(1, params_words(nseg=-1, group=1)))
    ops.append(params_op(2, params_words(
        nseg=1, dv=0.37, c0=(300.0, -5.0, 1000.5, 256.75),
        c1=(-300.0, 255.9, 0.4, -1.0), tex=0x1fb22c32)))
    ops.append(params_op(3, params_words(
        nseg=3, dv=2.5, widths=[0, (0.0, 0.6)], heads=[1, (0.3, 0.2)],
        tails=[(0.0, 1.0), (1.0, 0.4), (0.5, -0.2)], lat=-0.7,
        height=-0.5, alt=1.0, pad=(1, 2, 3))))
    ops += ["M %d" % FM_SIZE, "G 3", "T 1"]

    # The Zone Preview's own comet, through a run.
    ops.append("C 0 0 -1")
    ops += renders(0, [0.0, 0.3, 0.79999, 0.8])
    ops += ["O 0 0 1", "O 0 1 2", "O 0 2 3"] + renders(0, [0.5])
    ops += ["O 0 0 1", "O 0 2 1"] + renders(0, [0.95, 1.0, 1.1])
    ops += ["F 0", "F 0", "E 0", "E 0", "F 0"]
    ops += ["M 64"] + renders(0, [0.5]) + ["M 65"] + renders(0, [0.5])
    ops += ["M %d" % FM_SIZE, "X 0"]
    ops += ["C 0 0 -1", "X 0"]
    # No emitters, the driving line's 64 segments.
    ops += ["G 0", "C 1 1 -2"] + renders(1, [0.5]) + ["E 1", "F 1", "X 1"]
    # No texture, one segment.
    ops += ["T 0", "G 1", "C 2 2 2"] + renders(2, [0.0, 0.4, 0.9]) + ["X 2"]
    ops += ["T 1", "G 2", "C 0 3 1"] + renders(0, [0.5]) + ["X 0"]
    ops += ["C 0 4 0"] + renders(0, [0.3]) + ["X 0"]
    ops += ["C 0 5 0"] + renders(0, [0.3]) + ["X 0"]
    ops += ["G 4", "C 1 6 3"] + renders(1, [0.0, 0.2, 0.85]) + ["X 1"]
    ops += ["C 2 2 0"] + renders(2, [0.1, 0.6]) + ["X 2"]
    ops += ["C 0 1 -3", "C 1 2 -4"] + renders(0, [0.25]) + renders(1, [0.9])
    ops += ["X 1", "X 0"]

    # Random cases: a spline, a params block, a group and a texture, then
    # renders through a run with the emitters poked between.
    for case in range(40):
        typ = rng.choice((0, 1, 2, 2, 2, 3))
        n = rng.randint(4, 12)
        ops.append(spline_op(7, typ, road(rng, n, typ), rng))
        k = 4 + case % 4

        def knees():
            m = rng.randint(1, 5)
            xs = sorted(rng.uniform(0, 1) for _ in range(m))
            if rng.random() < 0.15:
                rng.shuffle(xs)
            pts = [(x, rng.uniform(-0.2, 1.2)) for x in xs]
            if rng.random() < 0.2:
                return [rng.randint(0, 5)] + pts
            return pts

        heads = knees()
        hs = heads[1:] if isinstance(heads[0], int) else heads
        hs = list(hs) + [(0.0, 0.0)] * (5 - len(hs))
        if hs[1][0] >= 0.99:
            hs[1] = (rng.uniform(0, 0.98), hs[1][1])
        if isinstance(heads[0], int):
            heads = [heads[0]] + hs
        else:
            heads = [len([p for p in heads])] + hs
        c0 = tuple(rng.choice((rng.uniform(0, 255), rng.uniform(-50, 400)))
                   for _ in range(4))
        c1 = tuple(rng.choice((rng.uniform(0, 255), rng.uniform(-50, 400)))
                   for _ in range(4))
        ops.append(params_op(k, params_words(
            nseg=rng.choice((1, 2, 3, 5, 8, rng.randint(1, 20))),
            dv=rng.uniform(-20, 20), tex=rng.getrandbits(32),
            width=rng.uniform(-1, 4), height=rng.uniform(-2, 2),
            alt=rng.uniform(-3, 3), lat=rng.uniform(-3, 3),
            widths=knees(), heads=heads, tails=knees(), c0=c0, c1=c1,
            group=rng.randint(0, 1))))
        ndatas = rng.randint(0, 4)
        ops += ["G %d" % ndatas, "T %d" % (rng.random() < 0.85)]
        c = case % NCOMET
        ops.append("C %d 7 %d" % (c, k))
        ts = sorted(rng.uniform(0, 1.1) for _ in range(rng.randint(2, 5)))
        for t in ts:
            r = rng.random()
            if r < 0.15 and ndatas:
                ops.append("O %d 0 %d" % (c, rng.choice((0, 1, 2, 3))))
            elif r < 0.25:
                ops.append(rng.choice(("E %d", "F %d")) % c)
            elif r < 0.3:
                ops.append("M %d" % rng.choice((0, 63, 64, 65, 80)))
            ops += renders(c, [t])
            if r < 0.3:
                ops.append("M %d" % FM_SIZE)
        ops.append("X %d" % c)
    return ops


def encode(ops):
    return NL.join(ops) + NL


# ================================================================ the model


class Model(object):
    def __init__(self):
        self.out = []
        self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        e = self.e
        e.stub(BMALLOC, self.s_malloc)
        e.stub(VEC_DELETE, self.s_free)
        e.stub(DELETE, self.s_free)
        e.stub(GET_DATA, self.s_get_data)
        e.stub(SET_DATA, self.s_set_data)
        e.stub(ADD_AUTO, self.s_add)
        e.stub(REMOVE_AUTO, self.s_remove)
        e.stub(EMITTER_DTOR, self.s_emitter_dtor)
        e.stub(GET_TEX, self.s_get_tex)
        e.stub(RENDER3D, self.s_render3d)
        e.stub(POLY_DTOR, lambda em: None)
        # The static initializer, over poison.
        e.write(GLOBALS, bytes([PATTERN]) * (208 * 4))
        e.call(SINIT)
        self.fill(COMETS, COMET_STRIDE * NCOMET)
        self.fill(ARENA, ARENA_SIZE)
        self.fill(SPL, SPL_STRIDE * NSPL)
        self.fill(PRM, PRM_STRIDE * NPRM)
        for i, g in enumerate(GROUPS):
            e.write(STRS + 32 * i, g.encode() + b"\0")
        e.put32(G_FMPOS, FM)
        e.put32(G_FMEND, FM + FM_SIZE)
        self.heap = ARENA
        self.blocks = []
        self.ndatas = 0
        self.tex_on = 1
        self.names = {TEX: "tex", FRAME_FX: "frame", WORLD_FX: "world"}
        for i in range(NDATA):
            self.names[DATAS + DATA_SIZE * i] = "d%d" % i
        for i in range(NSPL):
            self.names[SPL + SPL_STRIDE * i] = "s%d" % i
        for k in range(-4, NPRM):
            base, tag = self.params_at(k)
            self.names[base] = tag
            for off in (36, 80, 124):
                self.names[base + off] = "%s+%d" % (tag, off)

    def params_at(self, k):
        if k < 0:
            return GLOBALS + 208 * (-k - 1), "g%d" % -k
        return PRM + PRM_STRIDE * k, "p%d" % k

    def emit(self, s):
        self.out.append(s)

    def fill(self, a, n):
        self.e.write(a, bytes([PATTERN]) * n)

    def w(self, a):
        return self.e.u32(a)

    def cstr(self, a):
        s = bytearray()
        a &= M32
        while self.e.mem[a] and len(s) < 200:
            s.append(self.e.mem[a])
            a += 1
        return s.decode("latin-1")

    def name(self, a):
        a &= M32
        if a == 0:
            return "null"
        for i in range(len(self.blocks) - 1, -1, -1):
            b = self.blocks[i]
            if a == b:
                return "m%d" % i
            off = a - b - 16
            if off >= 0 and off % EMITTER == 0 and off // EMITTER < 64:
                return "m%d[%d]" % (i, off // EMITTER)
        if a in self.names:
            return self.names[a]
        if FM <= a < FM + FM_SIZE:
            return "fm+%d" % (a - FM)
        return "?"

    # ---- the stubs -------------------------------------------------------

    def s_malloc(self, em):
        size, flags, pool = s32(em.reg[4]), s32(em.reg[6]), s32(em.reg[7])
        p = (self.heap + 15) & ~15
        self.heap = p + size
        self.emit("  malloc %d %s %d %d -> m%d"
                  % (size, self.cstr(em.reg[5]), flags, pool,
                     len(self.blocks)))
        self.blocks.append(p)
        return p

    def s_free(self, em):
        self.emit("  free %s" % self.name(em.reg[4]))

    def s_get_data(self, em):
        after = em.reg[6] & M32
        if after == 0:
            d = DATAS if self.ndatas > 0 else 0
        else:
            i = (after - DATAS) // DATA_SIZE + 1
            d = DATAS + DATA_SIZE * i if i < self.ndatas else 0
        self.emit("  getdata %08x %08x %s -> %s"
                  % (em.reg[4] & M32, em.reg[5] & M32, self.name(after),
                     self.name(d)))
        return d

    def s_set_data(self, em):
        e, d = em.reg[4] & M32, em.reg[5] & M32
        self.emit("  setdata %s %s" % (self.name(e), self.name(d)))
        if d == 0:
            return 0
        self.e.put32(e + 28, d)
        return 1

    def s_add(self, em):
        self.emit("  add %s %s" % (self.name(em.reg[4]), self.name(em.reg[5])))

    def s_remove(self, em):
        self.emit("  remove %s %s"
                  % (self.name(em.reg[4]), self.name(em.reg[5])))

    def s_emitter_dtor(self, em):
        self.emit("  emitter dtor %s %d"
                  % (self.name(em.reg[4]), s32(em.reg[5])))
        self.e.put32(G_COUNT, (self.w(G_COUNT) - 1) & M32)

    def s_get_tex(self, em):
        t = TEX if self.tex_on else 0
        self.emit("  gettex %08x %d %d -> %s"
                  % (em.reg[4] & M32, s32(em.reg[5]), s32(em.reg[6]),
                     self.name(t)))
        return t

    def s_render3d(self, em):
        p, t, m = em.reg[4] & M32, em.reg[5] & M32, em.reg[6] & M32
        w = self.w
        self.emit("  draw %s %s %d" % (self.name(t), self.name(m),
                                      s32(em.reg[7])))
        for i in range(4):
            self.emit("    v " + " ".join(fx(w(p + 16 + 16 * i + 4 * k))
                                          for k in range(4)))
        for i in range(4):
            self.emit("    uv " + " ".join(fx(w(p + 80 + 12 * i + 4 * k))
                                           for k in range(3)))
        for i in range(4):
            self.emit("    c %02x %02x %02x %02x"
                      % tuple(self.e.read(p + 128 + 4 * i, 4)))
        b = self.e.read(p + 144, 9)
        self.emit("    a %s %d" % (" ".join("%d" % x for x in b),
                                   w(p + 156) != 0))
        self.emit("    m " + " ".join(fx(w(m + 4 * k)) for k in range(16)))

    # ---- the dumps -------------------------------------------------------

    def dump_params(self, k):
        base, tag = self.params_at(k)
        self.emit("  %s \"%s\" %s" % (
            tag, self.cstr(self.w(base)),
            " ".join("%08x" % self.w(base + 4 * i) for i in range(1, 52))))

    def dump_comet(self, ci):
        c = COMETS + COMET_STRIDE * ci
        w = self.w
        n = s32(w(c + 12))
        self.emit("  comet %d spl %s prm %s em %s n %d on %d tex %s"
                  % (ci, self.name(w(c)), self.name(w(c + 4)),
                     self.name(w(c + 8)), n, s32(w(c + 16)),
                     self.name(w(c + 20))))
        self.emit("  graphs %s %d %s %d %s %d"
                  % (self.name(w(c + 24)), s32(w(c + 28)),
                     self.name(w(c + 32)), s32(w(c + 36)),
                     self.name(w(c + 40)), s32(w(c + 44))))
        em = w(c + 8)
        if em == 0:
            return
        for j in range(n):
            e = em + EMITTER * j
            self.emit("  e%d %08x %08x %d %s %s %s %s %08x %08x %08x"
                      % (j, w(e + 8), w(e + 12), s32(w(e + 16)),
                         fx(w(e + 20)), fx(w(e + 24)), self.name(w(e + 28)),
                         self.name(w(e + 32)), w(e + 36), w(e + 40),
                         w(e + 44)))
            self.emit("    lw " + " ".join(fx(w(e + 48 + 4 * k))
                                           for k in range(16)))
            self.emit("    iv %s name %s"
                      % (" ".join(fx(w(e + 112 + 4 * k)) for k in range(4)),
                         " ".join("%08x" % w(e + 128 + 4 * k)
                                  for k in range(16))))

    def dump_globals(self):
        w = self.w
        self.emit("  g count %d fm %d failed %d amount %d"
                  % (s32(w(G_COUNT)), w(G_FMPOS) - FM, s32(w(G_FAILED)),
                     w(G_AMOUNT)))

    def after(self, ci):
        self.dump_comet(ci)
        self.dump_globals()

    # ---- the script ------------------------------------------------------

    def run(self, ops):
        e = self.e
        for op in ops:
            t = op.split()
            o = t[0]
            if o == "I":
                self.emit("I")
                for k in (-1, -2, -3, -4):
                    self.dump_params(k)
            elif o == "S":
                k, typ, n = int(t[1]), int(t[2]), int(t[3])
                words = [int(x, 16) for x in t[4:]]
                base = PTS + PTS_STRIDE * k
                for i, x in enumerate(words):
                    e.put32(base + 4 * i, x)
                e.call(SPL_CTOR, SPL + SPL_STRIDE * k, typ, n, base + 16, 0)
                self.emit("S %d %d %d" % (k, typ, n))
            elif o == "P":
                k = int(t[1])
                words = [int(x, 16) for x in t[2:]]
                base = PRM + PRM_STRIDE * k
                e.put32(base, STRS + 32 * (words[0] & 1))
                for i in range(1, 52):
                    e.put32(base + 4 * i, words[i])
                self.emit("P %d" % k)
                self.dump_params(k)
            elif o == "G":
                self.ndatas = int(t[1])
                self.emit("G %d" % self.ndatas)
            elif o == "T":
                self.tex_on = int(t[1])
                self.emit("T %d" % self.tex_on)
            elif o == "M":
                n = int(t[1])
                e.put32(G_FMPOS, FM)
                e.put32(G_FMEND, FM + n)
                self.emit("M %d" % n)
                self.dump_globals()
            elif o == "C":
                ci, k, p = int(t[1]), int(t[2]), int(t[3])
                self.emit("C %d %d %d" % (ci, k, p))
                c = COMETS + COMET_STRIDE * ci
                self.fill(c, 48)
                e.call(CTOR, c, SPL + SPL_STRIDE * k, self.params_at(p)[0])
                self.after(ci)
            elif o in ("X", "E", "F"):
                ci = int(t[1])
                self.emit("%s %d" % (o, ci))
                c = COMETS + COMET_STRIDE * ci
                if o == "X":
                    e.call(DTOR, c, 2)
                else:
                    e.call(ENABLE if o == "E" else DISABLE, c)
                self.after(ci)
            elif o == "O":
                ci, j, st = int(t[1]), int(t[2]), int(t[3])
                c = COMETS + COMET_STRIDE * ci
                e.put32(self.w(c + 8) + EMITTER * j + 16, st & M32)
                self.emit("O %d %d %d" % (ci, j, st))
            elif o == "R":
                ci, tb = int(t[1]), int(t[2], 16)
                self.emit("R %d %08x" % (ci, tb))
                e.fpr[12] = tb
                e.call(RENDER, COMETS + COMET_STRIDE * ci, VIEW)
                self.after(ci)
        return self.out


def image_facts():
    """What the port takes from the image without running it."""
    e = retail_model.RetailEmu(ieee=True)
    out = []
    jal = lambda t: 0x0c000000 | (t >> 2)
    j_ = lambda t: 0x08000000 | (t >> 2)
    want = {
        CTOR: {0x001620ac, 0x00174f30},
        DTOR: {0x0016369c, 0x0017504c},
        ENABLE: {0x00161630, 0x00163998, 0x00183208},
        DISABLE: {0x00161690, 0x001639b0, 0x00183200},
        RENDER: {0x001637b8, 0x001750ec},
        SECOND: {0x00161a34},
    }
    got = {k: set() for k in want}
    for a in range(0x00100000, 0x002a0000, 4):
        w = e.u32(a)
        for k in want:
            if w == jal(k) or w == j_(k):
                got[k].add(a)
    for k in sorted(want):
        out.append((got[k] == want[k], "%08x called from %s" % (
            k, " ".join("%08x" % a for a in sorted(got[k])))))
    # The mover hands the constructor ZonePreviewCometParams:
    # lui a2,0x0030 ; addiu a2,a2,-22032.
    out.append((e.u32(0x00162094) == 0x3c060030
                and e.u32(0x0016209c) == 0x24c6a9f0,
                "the mover's params: %08x %08x"
                % (e.u32(0x00162094), e.u32(0x0016209c))))
    # VisibleDrivingLine's table of the other three, by difficulty.
    tab = [e.u32(DRIVING_TABLE + 4 * i) for i in range(3)]
    out.append((tab == [GLOBALS + 208, GLOBALS + 416, GLOBALS + 624],
                "the driving line's params table: %s"
                % " ".join("%08x" % x for x in tab)))
    # Enable's and Disable's system: lui s2,0x002f ; addiu a0,s2,-2592.
    for a in (0x00161750, 0x001617d0):
        ok = (e.u32(a) == 0x3c12002f and e.u32(a + 16) == 0x2644f5e0)
        out.append((ok, "the system at %08x: %08x %08x, FrameEffects"
                    % (a, e.u32(a), e.u32(a + 16))))
    # NumAcidEmitters, gp-23516, in the constructor's inline.
    out.append((e.u32(0x001615c0) == 0x8f82a424
                and e.u32(0x001615cc) == 0xaf82a424,
                "the emitter count: %08x %08x"
                % (e.u32(0x001615c0), e.u32(0x001615cc))))
    # The frame memory's words, gp-19388 .. gp-19368, in Render.
    out.append((e.u32(0x00161820) == 0x8f86b444
                and e.u32(0x00161828) == 0x8f82b448
                and e.u32(0x0016188c) == 0xaf82b454
                and e.u32(0x0016189c) == 0xaf83b458,
                "Render's frame memory words"))
    # The allocation's name.
    s = e.read(0x002b1fa8, 21)
    out.append((s == b"ZonePreview Emitters\0", "new[]'s name %r" % s))
    # The initializer is a constructor the boot runs.
    out.append((e.u32(CTOR_ENTRY) == SINIT,
                "__CTOR_LIST__ word at %08x: %08x"
                % (CTOR_ENTRY, e.u32(CTOR_ENTRY))))
    return out


# ================================================================ the build


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


def build_harness(tmp, name="previewcomet_test"):
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

def M(name, before, after, rel=PCC):
    return (name, rel, before, after)


MUTATIONS = [
    # The params.
    M("g-zone-seg", "\"ZONE_PREVIEW\", 32,", "\"ZONE_PREVIEW\", 31,"),
    M("g-zone-tex", "0x954c4637u", "0x954c4636u"),
    M("g-zone-tail", "{ 0.5f, 0.47f }", "{ 0.5f, 0.48f }"),
    M("g-zone-c0", "{ 240.0f, 200.0f, 20.0f, 255.0f }",
      "{ 240.0f, 200.0f, 21.0f, 255.0f }"),
    M("g-easy-c0", "{ 50.0f, 160.0f, 0.0f, 255.0f }",
      "{ 50.0f, 161.0f, 0.0f, 255.0f }"),
    M("g-medium-c1", "{ 80.0f, 80.0f, 0.0f, 0.0f }",
      "{ 80.0f, 80.0f, 0.0f, 1.0f }"),
    M("g-hard-c1", "{ 0.0f, 0.0f, 80.0f, 0.0f }",
      "{ 0.0f, 0.0f, 81.0f, 0.0f }"),
    # The constructor.
    M("i-width", "params->nPreviewCometWidths);",
      "params->nPreviewCometHeads);"),
    M("i-head", "graph_init(&c->Head, params->vPreviewCometHead,",
      "graph_init(&c->Head, params->vPreviewCometWidth,"),
    M("i-tail", "params->nPreviewCometTails);",
      "params->nPreviewCometTails - 1);"),
    M("i-look", "c->pLookSpline = look;", "c->pLookSpline = look + 1;"),
    M("i-count-hash",
      "0, bchunk_hash(c->pParams->EmitterGroupName), d)) != NULL)" + NL
      + "        c->nEmitters++;",
      "0, bchunk_hash(\"ZONE_PREVIEW\"), d)) != NULL)" + NL
      + "        c->nEmitters++;"),
    M("i-count", "        c->nEmitters++;", "        c->nEmitters = 1;"),
    M("i-n0", "if (n != 0) {", "if (n > 1) {"),
    M("i-size", "+ n * (int32_t)sizeof(AcidEmitter),",
      "+ (n + 1) * (int32_t)sizeof(AcidEmitter),"),
    M("i-pool", "\"ZonePreview Emitters\", 0, 16);",
      "\"ZonePreview Emitters\", 0, 0);"),
    M("i-name", "\"ZonePreview Emitters\", 0, 16);",
      "\"ZonePreview Emitter\", 0, 16);"),
    M("i-cookie", "*(int32_t *)(void *)block = n;",
      "*(int32_t *)(void *)block = n + 1;"),
    M("i-memset", "memset(&e[i].NameHash, 0,", "memset(&e[i].State, 0,"),
    # 8, not 4: the host's AcidEmitter has 4 bytes of padding after Name
    # (two 8-byte links and pointers, the vectors 4-aligned), 216 bytes.
    M("i-memset-len", "sizeof e[i] - offsetof(AcidEmitter, NameHash));",
      "sizeof e[i] - offsetof(AcidEmitter, NameHash) - 8);"),
    M("i-numacid", "            NumAcidEmitters++;" + NL, ""),
    M("i-walk", "i = 0;" + NL + "        d = NULL;",
      "i = 1;" + NL + "        d = NULL;"),
    M("i-on", "c->pEmitters[i].State = ACID_ON;",
      "c->pEmitters[i].State = ACID_OFF;"),
    M("i-enabled", "c->Enabled = 0;" + NL + "    preview_comet_enable(c);",
      "c->Enabled = 1;" + NL + "    preview_comet_enable(c);"),
    M("i-tex", "c->pParams->nPreviewCometTexture, 1, 0);",
      "c->pParams->nPreviewCometTexture, 0, 0);"),
    # The destructor.
    M("x-disable", "    preview_comet_disable(c);" + NL
      + "    if (c->pEmitters != NULL) {",
      "    if (c->pEmitters != NULL) {"),
    M("x-null", "if (c->pEmitters != NULL) {",
      "if (c->pEmitters != NULL && c->nEmitters > 1) {"),
    M("x-order", "while (e != c->pEmitters) {" + NL
      + "            e--;" + NL
      + "            acid_emitter_delete(e, 0);",
      "for (e = c->pEmitters; e != c->pEmitters + *(int32_t *)(void *)"
      "block; e++) {" + NL
      + "            acid_emitter_delete(e, 0);"),
    M("x-flags", "acid_emitter_delete(e, 0);", "acid_emitter_delete(e, 1);"),
    M("x-free", "bFree(block);", "bFree(c->pEmitters);"),
    # Enable and Disable.
    M("e-guard", "    if (c->Enabled != 0)" + NL + "        return;" + NL, ""),
    M("e-count", "for (i = 0; i < c->nEmitters; i++)" + NL
      + "        acid_system_add_auto_emitter",
      "for (i = 0; i < c->nEmitters - 1; i++)" + NL
      + "        acid_system_add_auto_emitter"),
    M("e-system", "acid_system_add_auto_emitter(&FrameEffects,",
      "acid_system_add_auto_emitter(&WorldEffects,"),
    M("e-flag", "    c->Enabled = 1;" + NL + "}", "    c->Enabled = 2;" + NL + "}"),
    M("f-guard", "    if (c->Enabled == 0)" + NL + "        return;" + NL, ""),
    M("f-start", "for (i = 0; i < c->nEmitters; i++)" + NL
      + "        acid_system_remove_auto_emitter",
      "for (i = 1; i < c->nEmitters; i++)" + NL
      + "        acid_system_remove_auto_emitter"),
    M("f-system", "acid_system_remove_auto_emitter(&FrameEffects,",
      "acid_system_remove_auto_emitter(&WorldEffects,"),
    M("f-flag", "    c->Enabled = 0;" + NL + "}", "    c->Enabled = -1;" + NL + "}"),
    # Render: the frame memory and the run's values.
    M("r-fm", "eframe_malloc(64);", "eframe_malloc(48);"),
    M("r-fm-null", "    if (local_world == NULL)" + NL + "        return;" + NL,
      ""),
    M("r-ident", "    bIdentity(local_world);" + NL, ""),
    M("r-up", "axis.z = 1.0f;", "axis.z = -1.0f;"),
    M("r-ab", "a = 0;" + NL + "    b = 1;", "a = 1;" + NL + "    b = 0;"),
    M("r-head", "head = graph_get_value(&c->Head, t);",
      "head = graph_get_value(&c->Width, t);"),
    M("r-tail", "tail = graph_get_value(&c->Tail, t);",
      "tail = graph_get_value(&c->Head, t);"),
    M("r-step", "step = (tail - head) /", "step = (head - tail) /"),
    M("r-scroll", "scroll = t * c->pParams->fPreviewCometTextureDV;",
      "scroll = t + c->pParams->fPreviewCometTextureDV;"),
    M("r-floor", "if (scroll < base)", "if (scroll <= base)"),
    M("r-floor-1", "base = base - 1.0f;" + NL + "    scroll = scroll - base;",
      "base = base - 0.0f;" + NL + "    scroll = scroll - base;"),
    # Render: the loop and its points.
    M("r-loop-end", "i <= c->pParams->nPreviewCometSegments; i += 2)",
      "i < c->pParams->nPreviewCometSegments; i += 2)"),
    M("r-loop-step", "i += 2)", "i++)"),
    M("r-end-loop", "return (float)s->NumControlPoints;",
      "return (float)(s->NumControlPoints - 1);"),
    M("r-end-clamp",
      "if (s->Type == SPLINE_CLAMP || s->Type == SPLINE_EXTRAPOLATE)",
      "if (s->Type == SPLINE_EXTRAPOLATE)"),
    M("r-end-other", "    return 0.0f;" + NL + "}", "    return 1.0f;" + NL + "}"),
    M("r-u", "(head + step * fi);", "(head + step * (fi + 1.0f));"),
    M("r-alt", "p.z = p.z + pp->fPreviewCometAltitude;",
      "p.z = p.z + pp->fPreviewCometLineHeight;"),
    # Render: the frame.
    M("r-norm-along", "        normalize4(&along);" + NL, ""),
    M("r-cross1", "cross3(&side, &axis, &along);",
      "cross3(&side, &along, &axis);"),
    M("r-norm-side", "cross3(&side, &axis, &along);" + NL
      + "        normalize4(&side);",
      "cross3(&side, &axis, &along);"),
    M("r-lat", "dot3(&pull, &side);", "dot3(&pull, &along);"),
    M("r-up-z", "up.z = side.z * k + axis.z;", "up.z = side.z * k;"),
    M("r-cross2", "cross3(&side, &up, &along);",
      "cross3(&side, &along, &up);"),
    M("r-cross3", "cross3(&up, &along, &side);",
      "cross3(&up, &side, &along);"),
    M("r-norm-up", "        normalize4(&up);" + NL, ""),
    # Render: the emitters.
    M("r-first", "if (i == 0) {", "if (i <= 2) {"),
    M("r-row-side", "m.v0.x = side.x;", "m.v0.x = up.x;"),
    M("r-row-up", "m.v1.z = up.z;", "m.v1.z = along.z;"),
    M("r-row-p", "m.v3.z = p.z;", "m.v3.z = p.z + 1.0f;"),
    M("r-state", "if (e->State != ACID_ON)", "if (e->State == ACID_OFF)"),
    M("r-head1", "if (t < c->pParams->vPreviewCometHead[1].x)",
      "if (t <= c->pParams->vPreviewCometHead[1].x)"),
    M("r-off", "e->State = ACID_OFF;", "e->State = ACID_ON;"),
    # Render: the corners.
    M("r-s", "fi = fi / (float)pp->nPreviewCometSegments;",
      "fi = fi / (float)(pp->nPreviewCometSegments + 1);"),
    M("r-width", "w = graph_get_value(&c->Width, fi);",
      "w = graph_get_value(&c->Width, rest);"),
    M("r-half", "(w * 0.5f)", "(w * 0.25f)"),
    M("r-lw", "pp->fPreviewCometLineWidth * (w",
      "pp->fPreviewCometAltitude * (w"),
    M("r-plus-z", "poly.Vertices[a].z = (p.z + side.z) + "
      "pp->fPreviewCometLineHeight;",
      "poly.Vertices[a].z = (p.z + side.z);"),
    M("r-minus-y", "poly.Vertices[b].y = p.y - side.y;",
      "poly.Vertices[b].y = p.y + side.y;"),
    M("r-minus-z", "poly.Vertices[b].z = (p.z - side.z)",
      "poly.Vertices[b].z = (p.z + side.z)"),
    M("r-v", "v = scroll + fi;", "v = scroll - fi;"),
    M("r-vb", "poly.UVs[b][1] = v;", "poly.UVs[b][0] = v;"),
    # Render: the fade and the colours.
    M("r-fade-cmp", "if (0.0f <= d)", "if (0.0f < d)"),
    M("r-fade", "fade = 1.0f - d / (1.0f - pp->vPreviewCometHead[1].x);",
      "fade = 1.0f - d;"),
    M("r-col-r", "fi * pp->vPreviewCometColour1.x);",
      "fi * pp->vPreviewCometColour1.y);"),
    M("r-col-g", "rest * pp->vPreviewCometColour0.y +",
      "fi * pp->vPreviewCometColour0.y +"),
    M("r-col-b", "fi * pp->vPreviewCometColour1.z);",
      "fi * pp->vPreviewCometColour0.z);"),
    M("r-col-a", "            fade * (rest", "            1.0f * (rest"),
    M("r-col-copy", "poly.Colours[b][2] = poly.Colours[a][2];",
      "poly.Colours[b][2] = poly.Colours[a][1];"),
    M("r-col-alpha", "poly.Colours[b][3] = poly.Colours[a][3];", ""),
    # Render: the draw.
    M("r-draw", "if (i > 0 && gEPolyRender3DFn != NULL)",
      "if (i >= 0 && gEPolyRender3DFn != NULL)"),
    M("r-draw-flags", "local_world, 0);", "local_world, 1);"),
    M("r-swap", "a ^= 3;" + NL + "        b ^= 3;",
      "a ^= 1;" + NL + "        b ^= 1;"),
    # Spline::GetSecondDerivative.
    M("d2-floor", "base = base - 1.0f;" + NL + "    u = t - base;",
      "base = base - 0.0f;" + NL + "    u = t - base;"),
    M("d2-c0", "c0 = (u * -6.0f + 4.0f) * 0.5f;",
      "c0 = (u * -6.0f + 4.0f) * 0.25f;"),
    M("d2-c1", "c1 = (u * 18.0f - 10.0f) * 0.5f;",
      "c1 = (u * 18.0f - 9.0f) * 0.5f;"),
    M("d2-c2", "c2 = (u * -18.0f + 8.0f) * 0.5f;",
      "c2 = (u * -18.0f + 9.0f) * 0.5f;"),
    M("d2-c3", "c3 = (u * 6.0f - 2.0f) * 0.5f;",
      "c3 = (u * 5.0f - 2.0f) * 0.5f;"),
    M("d2-eval", "spline_evaluate(s, o, base, c0, c1, c2, c3);",
      "spline_evaluate(s, o, base, c1, c0, c2, c3);"),
]

EQUIVALENT = {
    "r-cross1": "the first side only enters as k * side with k = lat * "
                "(pull . side), so turned round it gives the same up to the "
                "bit (IEEE's a - b is -(b - a)); its w lane, along's in place "
                "of up's, reaches no output",
    "r-fade-cmp": "at t exactly the head's second knee d is 0 and the fade "
                  "1 - 0 / (1 - x) is 1, the value it starts with",
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    base = model_cached(sc)
    scdir = tempfile.TemporaryDirectory()
    scp = Path(scdir.name) / "script.txt"
    scp.write_text(encode(sc))
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text().splitlines()
        if diff(base, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "previewcomet_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs)
    scdir.cleanup()
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
    facts = image_facts()
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
