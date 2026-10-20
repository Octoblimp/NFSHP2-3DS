#!/usr/bin/env python3
"""Cross-check emodelanim.c's Render setup against the retail image, run in
mipsemu.

The model is the image: eModel::Render (0x0010dc80) runs as shipped, with
SetupRigidAnimation (0x0010dbd0), GetRigidAnimationTime (0x0010dae8),
eRigidAnimation::GetMatrixAtTime (0x001a7518), bMulMatrix (0x0025ae18) and
SetupVertexAnimation (0x0010db70) under it. Only DetermineVisibleStrips
(0x0010d390), the renderer's, is stubbed: it records the matrix and the
solid Render hands it and returns 0, so RenderStrips is never reached. The
harness (tools/src/emodelanim_test.c) runs emodelanim.c's
emodel_setup_animation, with bmatrix.c's bMulMatrix, and prints the same
lines.

The script builds the objects first, the same on both sides:

    A a frames scale trig   a rigid animation's header
    M a f w0..w15           its frame f's matrix
    L s a                   solid s's rigid animation (-1 for none)
    V v rate s0 s1 ..       vertex animator v, its frame rate and solids
    O m s                   model m's solid (-1 for none)
    X m w0..w15             the matrix model m is drawn in

and then runs:

    W t                     WorldTimeFrames
    S m start               model m's RigidAnimationStartTime
    B pos end               the frame malloc's buffer, as offsets into it
    R m                     eModel::Render's setup: the matrix it draws in
                            (the one passed, or the frame malloc's, by its
                            offset), its 16 words, the solid, the start
                            after, and the frame malloc's position and
                            failure count
    G a t                   GetMatrixAtTime alone

The animations are the shapes retail's have: 30 frames at scale 2 (the
bushes' shake), 41 (the wipers), 120 (the water wheel), 15 (the flag),
and a few at scales 1 and 3. The vertex animators are the flag's 15
solids at 30 a second, which share the first's rigid animation as the
loader leaves them, one of 4 at 7 and one of a single solid. Every start
form is run: 0, a set start inside and past its length, a looping one,
the flag's 0xc000 with a random low byte, and a clock behind the start;
and the frame malloc full, one byte short, and with room.

Checked against the image, not diffed: Render calls the two setups and
DetermineVisibleStrips where the checker expects, and the frame malloc's
words and WorldTimeFrames are the demo's moved to retail.

    python tools/emodelanim_check.py
    python tools/emodelanim_check.py --mutate [--only a,b]
    python tools/emodelanim_check.py --dump out/emodelanim
"""
import argparse
import math
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

HARNESS = "tools/src/emodelanim_test.c"
EMA = "3DS Files/source/emodelanim.c"
SOURCES = [HARNESS, EMA, "3DS Files/source/bmatrix.c"]
HARNESS_TIMEOUT = 30

# ================================================================ the image

GP = 0x003358f0
RENDER = 0x0010dc80             # Render__6eModelP8bMatrix4P13eLightContextUi
SETUP_RIGID = 0x0010dbd0        # SetupRigidAnimation__6eModelP8bMatrix4
SETUP_VERTEX = 0x0010db70       # SetupVertexAnimation__6eModel
VISIBLE = 0x0010d390            # DetermineVisibleStrips__6eModelPC8bMatrix4ii
RENDER_STRIPS = 0x0010dd58      # RenderStrips__6eModelP8bMatrix4P13eLight..
GET_MATRIX = 0x001a7518         # GetMatrixAtTime__15eRigidAnimationP8bMatrix4i
G_WTF = GP - 19564              # WorldTimeFrames
G_POS = GP - 19388              # CurrentBufferPos
G_END = GP - 19384              # CurrentBufferEnd
G_FAILED = GP - 19372           # FrameMallocFailed
G_AMOUNT = GP - 19368           # FrameMallocFailAmount
DEMO_WTF = 0x00323cfc
DEMO_POS = 0x00323da4
DEMO_END = 0x00323da8
DEMO_FAILED = 0x00323db4
DEMO_AMOUNT = 0x00323db8

MAX_ANIMS, MAX_FRAMES = 8, 200
ANIMS = 0x01000000              # 0x4000 each
SOLIDS = 0x01020000             # 192 each
VAS = 0x01024000                # 272 each
MODELS = 0x01025000             # 24 each
INPUTS = 0x01026000             # 64 each
FRAME = 0x01028000
FRAME_BYTES = 4096
OUT = 0x01030000                # GetMatrixAtTime's matrix
NUM_SOLIDS = 64


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def words(m):
    return " ".join("%08x" % w for w in m)


def rot(axis, a, t=(0.0, 0.0, 0.0)):
    """A row-vector rotation about x, y or z, with a translation row."""
    c, s = math.cos(a), math.sin(a)
    if axis == 0:
        r = ((1, 0, 0), (0, c, s), (0, -s, c))
    elif axis == 1:
        r = ((c, 0, -s), (0, 1, 0), (s, 0, c))
    else:
        r = ((c, s, 0), (-s, c, 0), (0, 0, 1))
    rows = [list(r[0]) + [0.0], list(r[1]) + [0.0], list(r[2]) + [0.0],
            list(t) + [1.0]]
    return [fbits(v) for row in rows for v in row]


# (frames, scale, trig): the bushes' shake, a wiper, the water wheel, the
# flag's, and three of other scales.
ANIM_SHAPES = [(30, 2, 1), (41, 2, 0), (120, 2, 0), (15, 2, 0), (7, 1, 0),
               (5, 3, 0), (61, 2, 0), (1, 1, 0)]


def objects(rng):
    ops = []
    for a, (nf, scale, trig) in enumerate(ANIM_SHAPES):
        ops.append("A %d %d %d %d" % (a, nf, scale, trig))
        axis = a % 3
        for f in range(nf):
            ang = 2 * math.pi * f / nf * rng.uniform(0.2, 1.0)
            t = (rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3),
                 rng.uniform(-0.3, 0.3))
            ops.append("M %d %d %s" % (a, f, words(rot(axis, ang, t))))
    # solids 0..7: one per animation; 8: none; 9..23 the flag (animation
    # 3 on each, as the loader shares it); 24..27 a 4-solid animator with
    # none; 28 a 1-solid animator with animation 1.
    for s in range(8):
        ops.append("L %d %d" % (s, s))
    ops.append("L 8 -1")
    for s in range(9, 24):
        ops.append("L %d 3" % s)
    for s in range(24, 28):
        ops.append("L %d -1" % s)
    ops.append("L 28 1")
    ops.append("V 0 30 " + " ".join(str(s) for s in range(9, 24)))
    ops.append("V 1 7 24 25 26 27")
    ops.append("V 2 30 28")
    # models: 0..7 the animations, 8 none, 9 the flag, 10 the 4-solid,
    # 11 the single, 12 no solid, 13 a flag frame's own solid.
    solids = list(range(8)) + [8, 9, 24, 28, -1, 17]
    for m, s in enumerate(solids):
        ops.append("O %d %d" % (m, s))
        mat = rot(rng.randrange(3), rng.uniform(-3, 3),
                  (rng.uniform(-500, 500), rng.uniform(-50, 50),
                   rng.uniform(-500, 500)))
        ops.append("X %d %s" % (m, words(mat)))
    return ops, len(solids)


def starts(rng, m):
    """Start times to try on model m."""
    out = [0x0000, 0xc000, 0xc000 | rng.randrange(256), 0x8000,
           0x8000 | rng.randrange(0x4000), 0xc000 | rng.randrange(0x4000),
           0x4000 | rng.randrange(0x4000), rng.randrange(0x10000)]
    return out


def script():
    rng = random.Random(0x76a)
    ops, nmodels = objects(rng)
    for f in (0, 1, 2, 29, 30, 59, 60, 119, 120, 121, 239, 240, 241, 500):
        for a, (nf, scale, _trig) in enumerate(ANIM_SHAPES):
            if f // scale < 4 * nf:
                ops.append("G %d %d" % (a, f))
    for _ in range(60):
        a = rng.randrange(len(ANIM_SHAPES))
        ops.append("G %d %d" % (a, rng.randrange(0x4000)))
    clocks = [1, 2, 59, 60, 61, 255, 256, 0x3fff, 0x4000, 0x4001, 0x8000,
              0xc000, 0x12345, 0x7fffff00, -5, -0x4000]
    pos = 0
    for m in range(nmodels):
        for st in starts(rng, m):
            for wtf in rng.sample(clocks, 5) + [rng.randrange(1 << 20)]:
                ops.append("W %d" % wtf)
                ops.append("S %d %04x" % (m, st))
                ops.append("R %d" % m)
                pos += 64
                if pos > FRAME_BYTES - 256:
                    ops.append("B 0 %d" % FRAME_BYTES)
                    pos = 0
    # The clock running on: a set start runs out and is cleared; a looping
    # one wraps; the flag's solids come round.
    for m, s in ((0, 0), (1, 1), (3, 3), (9, 9), (10, 24), (13, 17)):
        ops.append("B 0 %d" % FRAME_BYTES)
        ops.append("O %d %d" % (m, s))
        ops.append("S %d %04x" % (m, 0x8000 | 100))
        for wtf in range(90, 400, 7):
            ops.append("W %d" % wtf)
            ops.append("R %d" % m)
    # The frame malloc: full, at the edge, and with room.
    for room in (0, 1, 63, 64, 65, 127, 128):
        ops.append("B %d %d" % (1024, 1024 + room))
        ops.append("W 1000")
        ops.append("S 2 c000")
        ops.append("R 2")
        ops.append("S 9 c0a5")
        ops.append("R 9")
        ops.append("O 9 9")
    return ops


def encode(ops):
    return NL.join(ops) + NL


class Model(object):
    def __init__(self):
        self.e = retail_model.emu(retail=True, ieee=True)
        self.seen = None
        self.calls = {}
        e = self.e
        e.stub(VISIBLE, self.visible)
        e.stub(RENDER_STRIPS, self.strips)
        e.put32(G_POS, FRAME)
        e.put32(G_END, FRAME + FRAME_BYTES)

    def visible(self, e):
        self.seen = (e.reg[5] & 0xffffffff, e.u32((e.reg[4] & 0xffffffff)
                                                  + 12))
        self.calls[VISIBLE] = self.calls.get(VISIBLE, 0) + 1
        return 0

    def strips(self, e):
        self.calls[RENDER_STRIPS] = self.calls.get(RENDER_STRIPS, 0) + 1
        return 0

    def solid_index(self, p):
        if p == 0:
            return -1
        k, r = divmod(p - SOLIDS, 192)
        return k if r == 0 and 0 <= k < NUM_SOLIDS else -2

    def run(self, ops):
        e = self.e
        out = []
        for op in ops:
            t = op.split()
            c = t[0]
            if c == "A":
                a = ANIMS + int(t[1]) * 0x4000
                e.write(a, struct.pack("<HBB", int(t[2]), int(t[4]),
                                       int(t[3])))
            elif c == "M":
                a = ANIMS + int(t[1]) * 0x4000 + 48 + int(t[2]) * 64
                e.write(a, struct.pack("<16I", *[int(w, 16) for w in t[3:]]))
            elif c == "L":
                s = SOLIDS + int(t[1]) * 192
                a = int(t[2])
                e.put32(s + 168, 0 if a < 0 else ANIMS + a * 0x4000)
            elif c == "V":
                v = VAS + int(t[1]) * 272
                ss = [int(x) for x in t[3:]]
                e.put32(v + 8, int(t[2]))
                e.put32(v + 12, len(ss))
                for i, s in enumerate(ss):
                    e.put32(v + 16 + 4 * i, SOLIDS + s * 192)
                    e.put32(SOLIDS + s * 192 + 44, v)
            elif c == "O":
                s = int(t[2])
                e.put32(MODELS + int(t[1]) * 24 + 12,
                        0 if s < 0 else SOLIDS + s * 192)
            elif c == "X":
                e.write(INPUTS + int(t[1]) * 64,
                        struct.pack("<16I", *[int(w, 16) for w in t[2:]]))
            elif c == "W":
                e.put32(G_WTF, int(t[1], 0))
            elif c == "S":
                e.write(MODELS + int(t[1]) * 24 + 22,
                        struct.pack("<H", int(t[2], 16)))
            elif c == "B":
                e.put32(G_POS, FRAME + int(t[1]))
                e.put32(G_END, FRAME + int(t[2]))
                e.put32(G_FAILED, 0)
                e.put32(G_AMOUNT, 0)
            elif c == "R":
                m = int(t[1])
                model = MODELS + m * 24
                inp = INPUTS + m * 64
                self.seen = None
                e.call(RENDER, model, inp, 0, 0)
                if self.seen is None:
                    out.append("R %d: none" % m)
                    continue
                mtx, solid = self.seen
                if mtx == inp:
                    where = "mtx=in"
                elif FRAME <= mtx < FRAME + FRAME_BYTES:
                    where = "mtx=f+%d" % (mtx - FRAME)
                else:
                    where = "mtx=?"
                w = struct.unpack("<16I", e.read(mtx, 64))
                st = struct.unpack("<H", e.read(model + 22, 2))[0]
                out.append("R %d: %s %s solid=%d start=%04x pos=%d fail=%d "
                           "amt=%d" % (
                               m, where, words(w),
                               self.solid_index(e.u32(model + 12)), st,
                               e.u32(G_POS) - FRAME,
                               struct.unpack("<i", e.read(G_FAILED, 4))[0],
                               e.u32(G_AMOUNT)))
            elif c == "G":
                a = ANIMS + int(t[1]) * 0x4000
                e.write(OUT, b"\xa5" * 64)
                e.call(GET_MATRIX, a, OUT, int(t[2]))
                w = struct.unpack("<16I", e.read(OUT, 64))
                out.append("G %s %s: %s" % (t[1], t[2], words(w)))
        return out


def image_facts(m):
    """What the port takes from the image without running it."""
    e = m.e
    rmap = retail_model.retail_map()
    out = []

    def jal_at(a, target):
        return e.u32(a) == 0x0c000000 | (target >> 2)

    out.append((jal_at(0x0010dcc8, SETUP_RIGID),
                "Render calls SetupRigidAnimation at 0010dcc8"))
    out.append((jal_at(0x0010dce4, SETUP_VERTEX),
                "Render calls SetupVertexAnimation at 0010dce4"))
    out.append((jal_at(0x0010dd00, VISIBLE) and jal_at(0x0010dd18, VISIBLE),
                "Render calls DetermineVisibleStrips at 0010dd00 and "
                "0010dd18"))
    out.append((jal_at(0x0010dd34, RENDER_STRIPS),
                "Render calls RenderStrips at 0010dd34"))
    out.append((jal_at(0x0010dc3c, GET_MATRIX),
                "SetupRigidAnimation calls GetMatrixAtTime at 0010dc3c"))
    for name, demo, ret in (("WorldTimeFrames", DEMO_WTF, G_WTF),
                            ("CurrentBufferPos", DEMO_POS, G_POS),
                            ("CurrentBufferEnd", DEMO_END, G_END),
                            ("FrameMallocFailed", DEMO_FAILED, G_FAILED),
                            ("FrameMallocFailAmount", DEMO_AMOUNT,
                             G_AMOUNT)):
        try:
            r = rmap.data(demo)
        except Exception as ex:     # noqa: BLE001
            r = None
            name += " (%s)" % ex
        out.append((r == ret, "%s: demo %08x -> retail %s, gp%+d" % (
            name, demo, "%08x" % r if r is not None else "none", ret - GP)))
    return out


def model(ops):
    m = Model()
    lines = m.run(ops)
    return m, lines


# ============================================================== the harness

def build_harness(tmp, name="emodelanim_test"):
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
    ("matrix-frame-unscaled", EMA,
     "    int32_t frame = time / (int32_t)(int8_t)a->FrameRateScale\n"
     "                    % (int32_t)(int16_t)a->NumFrames;",
     "    int32_t frame = time % (int32_t)(int16_t)a->NumFrames;"),
    ("matrix-frame-no-wrap", EMA,
     "    int32_t frame = time / (int32_t)(int8_t)a->FrameRateScale\n"
     "                    % (int32_t)(int16_t)a->NumFrames;",
     "    int32_t frame = time / (int32_t)(int8_t)a->FrameRateScale;\n"
     "    if (frame >= (int16_t)a->NumFrames) frame = a->NumFrames - 1;"),
    ("matrix-next-frame", EMA,
     "(a->Matricies + frame * 64)", "(a->Matricies + (frame + 1) * 64)"),
    ("rigid-done-keeps-start", EMA,
     "    if (t < 0) {\n        m->RigidAnimationStartTime = 0;\n",
     "    if (t < 0) {\n"),
    ("rigid-done-still-draws", EMA,
     "    if (t < 0) {\n        m->RigidAnimationStartTime = 0;\n"
     "        return matrix;\n    }",
     "    if (t < 0) {\n        m->RigidAnimationStartTime = 0;\n"
     "        t = 0;\n    }"),
    ("rigid-mul-order", EMA,
     "    bMulMatrix(out, matrix, out);", "    bMulMatrix(out, out, matrix);"),
    ("rigid-no-mul", EMA,
     "    bMulMatrix(out, matrix, out);\n", "\n"),
    ("rigid-own-buffer", EMA,
     "    out = (bMatrix4 *)eframe_malloc(64);",
     "    static bMatrix4 own;\n    out = &own;"),
    ("rigid-malloc-48", EMA,
     "    out = (bMatrix4 *)eframe_malloc(64);",
     "    out = (bMatrix4 *)eframe_malloc(48);"),
    ("vertex-start-all-bits", EMA,
     "    uint32_t start = (uint16_t)m->RigidAnimationStartTime & 0x3fffu;",
     "    uint32_t start = (uint16_t)m->RigidAnimationStartTime;"),
    ("vertex-rate-30", EMA,
     "                           * (uint32_t)va->FrameRate) / 60;",
     "                           * 30u) / 60;"),
    ("vertex-unsigned-divide", EMA,
     "    int32_t  t = (int32_t)(((uint32_t)WorldTimeFrames - start)\n"
     "                           * (uint32_t)va->FrameRate) / 60;",
     "    int32_t  t = (int32_t)((((uint32_t)WorldTimeFrames - start)\n"
     "                           * (uint32_t)va->FrameRate) / 60u);"),
    ("vertex-one-mod", EMA,
     "    uint32_t k = (uint32_t)(t % va->NumSolids) % (uint32_t)va->NumSolids;",
     "    uint32_t k = (uint32_t)t % (uint32_t)va->NumSolids;"),
    ("vertex-signed-index", EMA,
     "    uint32_t k = (uint32_t)(t % va->NumSolids) % (uint32_t)va->NumSolids;",
     "    int32_t  k = t % va->NumSolids;\n    if (k < 0) k += va->NumSolids;"),
    ("setup-no-start-check", EMA,
     "    if (s->pRigidAnimation != NULL && (uint16_t)m->RigidAnimationStartTime != 0)",
     "    if (s->pRigidAnimation != NULL)"),
    ("setup-no-vertex", EMA,
     "    if (((const eSolid *)m->Solid)->pVertexAnimator != NULL)\n"
     "        emodel_setup_vertex_animation(m);\n", ""),
    ("setup-vertex-first", EMA,
     "    if (s->pRigidAnimation != NULL && (uint16_t)m->RigidAnimationStartTime != 0)\n"
     "        matrix = emodel_setup_rigid_animation(m, matrix);\n"
     "    if (((const eSolid *)m->Solid)->pVertexAnimator != NULL)\n"
     "        emodel_setup_vertex_animation(m);\n",
     "    if (((const eSolid *)m->Solid)->pVertexAnimator != NULL)\n"
     "        emodel_setup_vertex_animation(m);\n"
     "    if (((const eSolid *)m->Solid)->pRigidAnimation != NULL\n"
     "        && (uint16_t)m->RigidAnimationStartTime != 0)\n"
     "        matrix = emodel_setup_rigid_animation(m, matrix);\n"),
    ("time-loop-bit", EMA,
     "    if ((start & 0x4000u) != 0)\n        return t % len;",
     "    if ((start & 0x8000u) != 0)\n        return t % len;"),
]

# Mutations that survive because they change nothing the image can tell.
# setup-no-start-check: with a start of 0, SetupRigidAnimation's
# GetRigidAnimationTime answers -1, so it clears the start that is already
# 0 and hands back the same matrix. Render's check only saves the call.
EQUIVALENT = {"setup-no-start-check"}


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
    counts = m.calls
    print("image: %d facts, %d wrong" % (len(facts), len(bad)))
    print("Render reached DetermineVisibleStrips %d times, RenderStrips %d"
          % (counts.get(VISIBLE, 0), counts.get(RENDER_STRIPS, 0)))
    print("%d steps, %d lines, %d differ" % (len(sc), len(harness), n))
    sys.exit(1 if (n or rc or bad) else 0)


if __name__ == "__main__":
    main()
