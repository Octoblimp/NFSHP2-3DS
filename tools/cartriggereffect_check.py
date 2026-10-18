#!/usr/bin/env python3
"""Cross-check 3DS Files/source/cartriggereffect.c, Car::TriggerEffect, and
terraineffect.c, TerrainEffectEmitters, against the retail image itself,
run in mipsemu (TASKS 60).

The model is the image. Retail's Car::TriggerEffect (0x0011e2b8),
TerrainEffectEmitters' constructor (0x00222248), deleting destructor
(0x002223b0) and TriggerEffect (0x00222438), and InitTerrainEffectEmitters
(0x00222530) and CloseTerrainEffectEmitters (0x00222570) run as shipped,
with the terrain table at 0x00318c00 as the disc has it, and under them
eMulMatrix (0x0011b248), bIdentity, bStringHash and ~bTList<AcidEmitter>
(0x00124bf0). The harness (tools/src/cartriggereffect_test.c) runs the
port over the same script, with the port's own table, eMulMatrix,
bIdentity and bchunk_hash, and the two transcripts are diffed.

Five calls are stubbed, on both sides, and print their arguments:
TriggerEmitter (0x00127700), with the emitter's LocalWorld and
InheritVelocity as the call finds them; afxGetEmitters (0x001272e0),
which puts 0 to 2 new emitters on the list's tail by the hash; the
AcidEmitter's deleting destructor (0x00124e20); bMalloc (0x002577c0), which
hands out a block of 0xab bytes; and __builtin_delete (0x00114e98). The Car,
its CarRenderInfo, the emitters, their datas and the emitter positions are
blobs at retail's offsets on the model side and the port's structs on the
harness side.

After each call a line gives a hash of every emitter's LocalWorld and
InheritVelocity, so what a call leaves behind is compared too: the copy
Car::TriggerEffect puts back keeps the last place in its fourth row.
A float prints as its bits.

    python tools/cartriggereffect_check.py
    python tools/cartriggereffect_check.py --mutate [--only a,b]
    python tools/cartriggereffect_check.py --dump out/cartriggereffect
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import physicscar_check as pcc
import retail_model
from mipsemu import M32, f_to_bits, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/cartriggereffect_test.c"
CTE = "3DS Files/source/cartriggereffect.c"
TEE_C = "3DS Files/source/terraineffect.c"
SOURCES = [HARNESS, CTE, TEE_C] + ["3DS Files/source/" + f for f in (
    "terraintypetab.c", "emath.c", "bmath.c", "bmathtab.c", "bmatrix.c",
    "bvector.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
TRIGGER_EFFECT = 0x0011e2b8
TEE_CTOR = 0x00222248
TEE_DTOR = 0x002223b0
TEE_TRIGGER = 0x00222438
TEE_INIT = 0x00222530
TEE_CLOSE = 0x00222570
TRIGGER_EMITTER = 0x00127700
AFX_GET_EMITTERS = 0x001272e0
EMITTER_DELETE = 0x00124e20
BMALLOC = 0x002577c0
BUILTIN_DELETE = 0x00114e98
BMATRIX_SINIT = 0x0025afa8
WORLD_EFFECTS = 0x002ef640
G_TEE = GP - 15816                # pTerrainEffectEmitters
TEE_SIZE = 1848

# The blobs.
CAR = 0x01000000
CAR_SIZE = 2200
RI = 0x01001000
RI_SIZE = 2352
EM = 0x01010000                   # emitter id i at EM + 0x100 * i
EM_STRIDE = 0x100
NUM_EM = 512
DATA = 0x01040000                 # data j at DATA + 0x400 * j
DATA_STRIDE = 0x400
NUM_DATA = 8
POS = 0x01050000                  # position p at POS + 16 * p
NUM_POS = 64
VELB = 0x01060000                 # the velocity a call is given
ATB = 0x01060010                  # the place a terrain trigger is given
TEE = 0x01100000                  # bMalloc's block

# Retail's Car and CarRenderInfo.
C_GEOM, C_POS, C_VEL, C_BODY = 80, 96, 112, 144
C_RI, C_VIEWBITS = 1200, 1296
RI_EMITTERS, RI_PLACES = 888, 1096
NUM_FX, NUM_PLACES = 26, 28
# AcidEmitter and AcidEmitterData.
E_DATA, E_LW, E_IV = 28, 48, 112
D_CARPOS = 88

NUM_CAR_EM = 17                   # ids 0..16 are the car's; afx's from 32
FIRST_AFX_EM = 32


def fb(v):
    if isinstance(v, int):
        return v & M32
    return f_to_bits(v)


def lw_init(i):
    """Emitter i's LocalWorld before anything places it: sixteen quarters,
    none of them in step, the fourth row not (0, 0, 0, 1)."""
    return [0.25 * ((i * 7 + k * 3) % 11) - 1.0 for k in range(16)]


IV_INIT = (5.0, 6.0, 7.0, 8.0)


def pos_init(p):
    """Position p's place on the car."""
    return (0.5 * p - 3.0, 0.25 * ((p * 5) % 7) + 0.5, -0.125 * p + 1.0)


def afx_count(h):
    """How many emitters afxGetEmitters gives a group, by its hash."""
    return (h >> 4) % 3


def afx_data(h):
    return h % NUM_DATA


def fnv(words):
    h = 0x811c9dc5
    for w in words:
        h = ((h ^ (w & M32)) * 16777619) & M32
    return h


# ============================================================ the scenarios

DATA_CARPOS = (3, 0, 27, 5, 1, 12, 0, 4)


def hexes(vals):
    return " ".join("%08x" % fb(v) for v in vals)


def state(geom, pos, vel, body):
    return "S " + hexes(list(geom) + list(pos) + list(vel) + list(body))


BODY0 = [0.0, 1.0, 0.0, 0.25,
         -1.0, 0.0, 0.0, -0.5,
         0.0, 0.0, 1.0, 0.125,
         7.0, 8.0, 9.0, 3.0]
BODY1 = [0.6, 0.8, 0.0, 0.0,
         -0.8, 0.6, 0.0, 0.0,
         0.0, 0.0, 1.0, 0.0,
         100.1, -250.3, 12.7, 1.0]
GEOM0 = (10.0, 20.0, 30.0, 40.0)
POS0 = (11.5, 21.25, 29.75, -2.0)
VEL0 = (3.0, -4.5, 0.75, 0.5)


def call(fx, scale, where=0, vel=None, ri=1, viewbits=0):
    """A Car::TriggerEffect: `vel` None passes NULL, else the four lanes
    of the velocity it is given."""
    f = ["C", "%d" % fx, "%08x" % fb(scale), "%08x" % (where & M32),
         "%d" % ri, "%08x" % (viewbits & M32)]
    if vel is None:
        f.append("0")
    else:
        f += ["1", hexes(vel)]
    return " ".join(f)


def tcall(fx, terrain, scale, at, vel):
    return "T %d %d %08x %s %s" % (fx, terrain, fb(scale), hexes(at),
                                   hexes(vel))


def s_car():
    out = ["D %d %d" % (j, cp) for j, cp in enumerate(DATA_CARPOS)]
    # The car's emitters: id, data.
    for i, d in enumerate((0, 1, 2, 3, 4, 5, 6, 7, 1, 2, 0, 3, 4, 5, 6, 7,
                           2)):
        out.append("E %d %d" % (i, d))
    # Where they come out: list, positions.
    out += ["W 0 16 17", "W 3 18 19 20", "W 5 21", "W 27 22 23",
            "W 1 24", "W 4 25 26", "W 6 27", "W 8 28 29", "W 9 30",
            "W 12 31", "W 12 31 32 33", "W 1 34", "W 0 16 17"]
    # The car's own lists: effect, emitters.
    out += ["L 6 0 1", "L 7 2", "L 3 3 4", "L 4 5", "L 8 6", "L 9 7",
            "L 1 8", "L 2 9", "L 5 10", "L 16 11", "L 10 12 13",
            "L 25 14", "L 11 15", "L 0 16"]
    out.append(state(GEOM0, POS0, VEL0, BODY0))
    out += [
        # The radiator: two emitters, at their datas' places.
        call(6, 1.0),
        call(6, 0.4, vel=(-1.0, 2.0, -3.0, 99.0)),
        call(6, 0.1, where=0x00030001),
        # Nothing: a scale of 0 either way, no effect, no render info, a
        # view bit.
        call(6, 0.0), call(6, -0.0), call(0, 1.0),
        call(6, 1.0, ri=0), call(6, 1.0, viewbits=1),
        call(6, 1.0, viewbits=0x80000000),
        # A NaN scale is not 0, and goes off with its sign turned.
        call(6, 0x7fc00001),
        # The wheels' effects: the wheel in the high half, from Position
        # for 1 to 8, from GeometryPosition past it.
        call(3, 1.0, where=0x00010001), call(3, 1.0, where=0x00020001),
        call(4, 0.5, where=0x00040003), call(8, 1.0, where=0x00080000),
        call(9, 1.0, where=0x00090000), call(8, 1.0, where=0x000c0000),
        call(8, 1.0, where=0x00050000), call(9, 0.25, where=0x00060007),
        call(4, 2.0, where=0x00090002, vel=(0.5, 0.25, 0.125, 1.0)),
        call(3, 1.0, where=0x001b0000),
        # Wheel 0 for a wheel's effect: the datas' places.
        call(3, 1.0, where=0x00000004), call(4, 1.0, where=0),
        # Not a wheel's effect: the high half is not read.
        call(1, 1.0, where=0x00070004), call(2, 0.75, where=0x00010000),
        call(5, 1.0, where=0x00030000), call(7, 1.0, where=0x00040000),
        call(10, 1.0, where=0x00020000),
        call(16, 1.0), call(20, 1.0), call(25, 0.5), call(11, 1.0),
    ]
    # The same again from elsewhere, with a turned body.
    out.append(state((-5.5, 0.0, 2.0, 7.0), (1.0, 2.0, 3.0, 4.0),
                     (0.0, 0.0, -1.0, 0.0), BODY1))
    out += [call(6, 1.0), call(3, 1.0, where=0x00010002),
            call(8, 1.0, where=0x00080000), call(16, 0.4),
            call(10, 1.0, vel=(1.5, 2.5, 3.5, 4.5))]
    # Places moved: the copy the last call put back keeps its fourth row.
    out += ["W 3 19", "W 0", call(6, 1.0), call(6, 1.0), "W 0 17 16",
            call(6, 0.4)]
    return out


def s_terrain():
    out = ["I", "I"]
    state1 = state((1.0, 2.0, 3.0, 0.0), (4.0, 5.0, 6.0, 0.0),
                   (7.0, 8.0, 9.0, 0.0), BODY0)
    out.append(state1)
    # The ground's effects come from the object's list for the terrain in
    # the low half.
    for fx in (1, 2, 3, 4, 5):
        for t in range(33):
            out.append(call(fx, 0.5, where=((t % 10) << 16) | t))
    out += [call(3, 1.0, where=0x00010001, vel=(0.0, 1.0, 0.0, 0.0)),
            call(6, 1.0), call(8, 1.0, where=0x00080000)]
    # Its own trigger: no test of the scale.
    for fx in range(7):
        for t in range(33):
            out.append(tcall(fx, t, 0.25 * ((fx + t) % 5),
                             (t * 1.5, -2.0 * fx, 0.1 * t, 9.0),
                             (fx - 3.0, t * 0.5, -1.0, 6.0)))
    out += [tcall(5, 1, -1.0, (0.0, 0.0, 0.0, 0.0), (1.0, 1.0, 1.0, 1.0)),
            tcall(6, 1, 0x7fc00001, (1.0, 2.0, 3.0, 4.0),
                  (4.0, 3.0, 2.0, 1.0))]
    # Closed: the car's lists again. Closed twice does nothing; made again,
    # new emitters.
    out += ["X", call(1, 1.0, where=1), call(3, 1.0, where=0x00010001),
            "X", "I", call(2, 1.0, where=2), "X"]
    # The destructor itself: with no free, then on NULL with and without.
    out += ["I", "Z 0", "Z 1", "Z 0", "I", "Z 1"]
    return out


def script():
    return [s_car(), s_terrain()]


def encode(scenarios):
    lines = []
    for i, s in enumerate(scenarios):
        lines.append("B %d" % i)
        lines += s
    return NL.join(lines) + NL


# ================================================================ the model


class Model(object):
    def __init__(self):
        self.out = []
        self.next_em = FIRST_AFX_EM
        self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        e = self.e
        e.stub(TRIGGER_EMITTER, self.rec_trigger)
        e.stub(AFX_GET_EMITTERS, self.rec_afx)
        e.stub(EMITTER_DELETE, self.rec_delete)
        e.stub(BMALLOC, self.rec_malloc)
        e.stub(BUILTIN_DELETE, self.rec_free)
        e.call(BMATRIX_SINIT, limit=200000)
        e.write(CAR, bytes(CAR_SIZE))
        e.write(RI, bytes(RI_SIZE))
        e.write(EM, bytes(EM_STRIDE * NUM_EM))
        e.write(DATA, bytes(DATA_STRIDE * NUM_DATA))
        e.write(POS, bytes(16 * NUM_POS))
        e.write(VELB, bytes(32))
        e.put32(G_TEE, 0)
        for i in range(NUM_EM):
            self.init_emitter(i, 0)
        for p in range(NUM_POS):
            for k, v in enumerate(pos_init(p)):
                e.put32(POS + 16 * p + 4 + 4 * k, fb(v))
        self.reset_lists()

    def emit(self, s):
        self.out.append(s)

    def arg(self, i):
        return self.e.reg[(4, 5, 6, 7, 8)[i]] & M32

    def w(self, a):
        return self.e.u32(a)

    def cstr(self, a):
        s = bytearray()
        while True:
            b = self.e.u8(a + len(s))
            if b == 0:
                return s.decode("latin-1")
            s.append(b)

    def em_id(self, a):
        return (a - EM) // EM_STRIDE

    def label(self, a):
        a &= M32
        if a == 0:
            return "NULL"
        if a == CAR:
            return "car"
        if a == WORLD_EFFECTS:
            return "world"
        if a == TEE:
            return "tee"
        return "?%08x" % a

    def init_emitter(self, i, d):
        e = self.e
        a = EM + EM_STRIDE * i
        for k, v in enumerate(lw_init(i)):
            e.put32(a + E_LW + 4 * k, fb(v))
        for k, v in enumerate(IV_INIT):
            e.put32(a + E_IV + 4 * k, fb(v))
        e.put32(a + E_DATA, DATA + DATA_STRIDE * d)

    def reset_lists(self):
        for k in range(NUM_FX):
            a = RI + RI_EMITTERS + 8 * k
            self.e.put32(a, a)
            self.e.put32(a + 4, a)
        for k in range(NUM_PLACES):
            a = RI + RI_PLACES + 8 * k
            self.e.put32(a, a)
            self.e.put32(a + 4, a)

    def link_tail(self, lst, a):
        e = self.e
        prev = self.w(lst + 4)
        e.put32(a, lst)
        e.put32(a + 4, prev)
        e.put32(prev, a)
        e.put32(lst + 4, a)

    def emitters_hash(self):
        words = []
        for i in list(range(NUM_CAR_EM)) + list(range(FIRST_AFX_EM,
                                                      self.next_em)):
            a = EM + EM_STRIDE * i
            words += [self.w(a + E_LW + 4 * k) for k in range(16)]
            words += [self.w(a + E_IV + 4 * k) for k in range(4)]
        return fnv(words)

    # ---- the stand-ins ---------------------------------------------------

    def rec_trigger(self, em):
        a = self.arg(1)
        self.emit("trigger sys=%s e=%d step=%08x car=%s lw=%s iv=%s" % (
            self.label(self.arg(0)), self.em_id(a), self.e.fpr[12] & M32,
            self.label(self.arg(2)),
            " ".join("%08x" % self.w(a + E_LW + 4 * k) for k in range(16)),
            " ".join("%08x" % self.w(a + E_IV + 4 * k) for k in range(4))))

    def rec_afx(self, em):
        lst, h = self.arg(0), self.arg(1)
        idx = (lst - TEE) // 8
        n = afx_count(h)
        self.emit("afx list=%d,%d hash=%08x n=%d" % (idx // 33, idx % 33,
                                                     h, n))
        for _ in range(n):
            i = self.next_em
            self.next_em += 1
            self.init_emitter(i, afx_data(h))
            self.link_tail(lst, EM + EM_STRIDE * i)

    def rec_delete(self, em):
        self.emit("delete e=%d flags=%d" % (self.em_id(self.arg(0)),
                                            s32(self.arg(1))))

    def rec_malloc(self, em):
        size = s32(self.arg(0))
        self.emit("bMalloc size=%s name=%s flags=%d pool=%d" % (
            "tee" if size == TEE_SIZE else "%d" % size,
            self.cstr(self.arg(1)), s32(self.arg(2)), s32(self.arg(3))))
        self.e.write(TEE, b"\xab" * TEE_SIZE)
        return TEE

    def rec_free(self, em):
        self.emit("free p=%s" % self.label(self.arg(0)))

    # ---- the ops ---------------------------------------------------------

    def op(self, t):
        e = self.e
        if t[0] == "D":
            e.put32(DATA + DATA_STRIDE * int(t[1]) + D_CARPOS, int(t[2]))
        elif t[0] == "E":
            self.init_emitter(int(t[1]), int(t[2]))
        elif t[0] == "W":
            lst = RI + RI_PLACES + 8 * int(t[1])
            e.put32(lst, lst)
            e.put32(lst + 4, lst)
            for p in t[2:]:
                a = POS + 16 * int(p)
                tail = self.w(lst + 4)
                e.put32(a, lst)
                e.put32(tail, a)
                e.put32(lst + 4, a)
        elif t[0] == "L":
            lst = RI + RI_EMITTERS + 8 * int(t[1])
            e.put32(lst, lst)
            e.put32(lst + 4, lst)
            for i in t[2:]:
                self.link_tail(lst, EM + EM_STRIDE * int(i))
        elif t[0] == "S":
            v = [int(x, 16) for x in t[1:]]
            for k in range(4):
                e.put32(CAR + C_GEOM + 4 * k, v[k])
                e.put32(CAR + C_POS + 4 * k, v[4 + k])
                e.put32(CAR + C_VEL + 4 * k, v[8 + k])
            for k in range(16):
                e.put32(CAR + C_BODY + 4 * k, v[12 + k])
        elif t[0] == "C":
            fx, scale, where = int(t[1]), int(t[2], 16), int(t[3], 16)
            e.put32(CAR + C_RI, RI if int(t[4]) else 0)
            e.put32(CAR + C_VIEWBITS, int(t[5], 16))
            vel = 0
            if int(t[6]):
                vel = VELB
                for k in range(4):
                    e.put32(VELB + 4 * k, int(t[7 + k], 16))
            e.fpr[12] = scale
            e.call(TRIGGER_EFFECT, CAR, fx, where, vel, limit=2000000)
            self.emit("state %08x" % self.emitters_hash())
        elif t[0] == "T":
            fx, terr, scale = int(t[1]), int(t[2]), int(t[3], 16)
            for k in range(4):
                e.put32(ATB + 4 * k, int(t[4 + k], 16))
                e.put32(VELB + 4 * k, int(t[8 + k], 16))
            e.fpr[12] = scale
            e.call(TEE_TRIGGER, self.w(G_TEE), fx, terr, ATB, VELB,
                   limit=2000000)
            self.emit("state %08x" % self.emitters_hash())
        elif t[0] == "I":
            e.call(TEE_INIT, limit=20000000)
            self.emit("init tee=%s" % self.label(self.w(G_TEE)))
        elif t[0] == "X":
            e.call(TEE_CLOSE, limit=20000000)
            self.emit("close tee=%s" % self.label(self.w(G_TEE)))
        elif t[0] == "Z":
            e.call(TEE_DTOR, self.w(G_TEE), int(t[1]), limit=20000000)
            e.put32(G_TEE, 0)
            self.emit("destroyed")
        else:
            raise SystemExit("bad op %r" % (t,))

    def run(self, scenarios):
        for n, sc in enumerate(scenarios):
            self.emit("B %d" % n)
            for ln in sc:
                self.emit("> " + ln[:40])
                self.op(ln.split())
        return self.out


# ================================================================ the build


def build_harness(tmp, name="cartriggereffect_test"):
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


def M(name, before, after, rel=CTE):
    return (name, rel, before, after)


def T(name, before, after):
    return (name, TEE_C, before, after)


MUTATIONS = [
    # Car::TriggerEffect's gates.
    M("cte-no-ri-test", "if (ri == NULL || scale", "if (scale"),
    M("cte-no-scale-test", "|| scale == 0.0f ", ""),
    M("cte-no-none-test", "|| effect == CARFX_NONE", ""),
    M("cte-no-viewbits", NL + "        || c->TheOverrideRenderingPosition"
      ".OverrideViewBits != 0)", ")"),
    # Which list.
    M("cte-terrain-all", "(uint32_t)(effect - 1) < 5", "effect >= 1"),
    M("cte-terrain-four", "(uint32_t)(effect - 1) < 5",
      "(uint32_t)(effect - 1) < 4"),
    M("cte-terrain-signed", "(uint32_t)(effect - 1) < 5",
      "(effect - 1) < 5"),
    M("cte-terrain-same-effect", "->Lists[effect - 1][where & 0xffff]",
      "->Lists[effect][where & 0xffff]"),
    M("cte-terrain-mask-narrow", "[where & 0xffff]", "[where & 0x7]"),
    # The wheel.
    M("cte-wheel-skid-only", "(uint32_t)(effect - CARFX_SKID_SMOKE) < 2",
      "effect == CARFX_SKID_SMOKE"),
    M("cte-wheel-no-blown", "|| effect == CARFX_BLOWN_TIRE", ""),
    M("cte-wheel-no-flat", NL + "        || effect == CARFX_DRIVE_ON_FLAT_TIRE",
      ""),
    M("cte-wheel-every", "wheel = 0;" + NL + "    if (", "wheel = 0;" + NL
      + "    if (1 || "),
    M("cte-wheel-shift", "wheel = where >> 16;", "wheel = where >> 15;"),
    # The origin.
    M("cte-origin-from-0", "wheel >= 1 && wheel < 9", "wheel >= 0 && wheel < 9"),
    M("cte-origin-to-9", "wheel >= 1 && wheel < 9", "wheel >= 1 && wheel <= 9"),
    M("cte-origin-swapped", "? &c->State.Position" + NL
      + "                                     : &c->State.GeometryPosition",
      "? &c->State.GeometryPosition" + NL
      + "                                     : &c->State.Position"),
    M("cte-origin-w", "body.v3.w = 1.0f;", "body.v3.w = origin->pad;"),
    M("cte-origin-y-lane", "body.v3.y = origin->y;", "body.v3.y = origin->x;"),
    # The velocity.
    M("cte-vel-always-car", "if (vel == NULL)" + NL
      + "        vel = &c->State.Velocity;", "vel = &c->State.Velocity;"),
    M("cte-vel-w", "e->InheritVelocity.w = 0.0f;" + NL
      + "            acid_system_trigger_emitter(&WorldEffects, e, -scale, c);",
      "e->InheritVelocity.w = 1.0f;" + NL
      + "            acid_system_trigger_emitter(&WorldEffects, e, -scale, c);"),
    M("cte-vel-z", "e->InheritVelocity.z = vel->z;" + NL
      + "            e->InheritVelocity.w = 0.0f;" + NL
      + "            acid_system_trigger_emitter(&WorldEffects, e, -scale, c);",
      "e->InheritVelocity.z = vel->y;" + NL
      + "            e->InheritVelocity.w = 0.0f;" + NL
      + "            acid_system_trigger_emitter(&WorldEffects, e, -scale, c);"),
    # The places.
    M("cte-places-wheel-0", "places = wheel != 0", "places = wheel > 1"),
    M("cte-places-data-always", "? &ri->EmitterPositionList[wheel]",
      "? &ri->EmitterPositionList[e->EmitterData->CarPosition]"),
    M("cte-place-w", "saved.v3.w = 1.0f;", "saved.v3.w = 0.0f;"),
    M("cte-place-xy", "saved.v3.y = at->Y;", "saved.v3.y = at->X;"),
    M("cte-mul-order", "eMulMatrix(&world, &saved, &body);",
      "eMulMatrix(&world, &body, &saved);"),
    M("cte-fresh-copy", "            bMatrix4                  world;" + NL,
      "            bMatrix4                  world;" + NL
      + "            saved = e->LocalWorld;" + NL),
    M("cte-no-restore", "        e->LocalWorld = saved;" + NL, ""),
    M("cte-restore-untouched", "            saved.v3.x = at->X;" + NL
      + "            saved.v3.y = at->Y;" + NL
      + "            saved.v3.z = at->Z;" + NL
      + "            saved.v3.w = 1.0f;" + NL
      + "            eMulMatrix(&world, &saved, &body);",
      "            bMatrix4 placed = saved;" + NL
      + "            placed.v3.x = at->X;" + NL
      + "            placed.v3.y = at->Y;" + NL
      + "            placed.v3.z = at->Z;" + NL
      + "            placed.v3.w = 1.0f;" + NL
      + "            eMulMatrix(&world, &placed, &body);"),
    M("cte-step-positive", "acid_system_trigger_emitter(&WorldEffects, e, "
      "-scale, c);", "acid_system_trigger_emitter(&WorldEffects, e, "
      "scale, c);"),
    M("cte-no-car", "acid_system_trigger_emitter(&WorldEffects, e, "
      "-scale, c);", "acid_system_trigger_emitter(&WorldEffects, e, "
      "-scale, NULL);"),
    M("cte-first-emitter-only", "for (n = list->next; n != list; "
      "n = n->next) {", "for (n = list->next; n != list; n = list) {"),
    M("cte-first-place-only", "for (p = places->Head; p != (bSNode *)places;"
      " p = p->next) {", "for (p = places->Head; p != (bSNode *)places;"
      " p = (bSNode *)places) {"),

    # TerrainEffectEmitters.
    T("tee-group-order", "case 4: return info->BottomOutEmitterGroup;"
      + NL + "    case 5: return info->CollisionImpactEmitterGroup;",
      "case 5: return info->BottomOutEmitterGroup;"
      + NL + "    case 4: return info->CollisionImpactEmitterGroup;"),
    T("tee-group-scrape", "case 6: return info->CollisionScrapeEmitterGroup;",
      "case 6: return info->CollisionImpactEmitterGroup;"),
    T("tee-empty-name-taken", "if (name == NULL || name[0] == '\\0')",
      "if (name == NULL)"),
    T("tee-effect-major", "for (terrain = 0; terrain < NUM_TERRAIN_TYPES; "
      "terrain++) {" + NL + "        const TerrainTypeInfo",
      "for (terrain = NUM_TERRAIN_TYPES - 1; terrain >= 0; terrain--) {"
      + NL + "        const TerrainTypeInfo"),
    T("tee-hash-from", "bchunk_hash(name)", "bchunk_hash_from(name, 0)"),
    T("tee-lists-not-emptied", "            list->next = list;" + NL
      + "            list->prev = list;" + NL, "            list->next = list;"
      + NL),
    T("tee-dtor-first-first", "        while (list != &t->Lists[0][0]) {"
      + NL + "            bNode *n;" + NL + NL + "            list--;",
      "        bNode *first = list;" + NL
      + "        for (list = &t->Lists[0][0]; list != first; list++) {" + NL
      + "            bNode *n;" + NL),
    T("tee-dtor-null", "    if (t != NULL) {" + NL + "        bNode *list",
      "    if (1) {" + NL + "        bNode *list"),
    T("tee-dtor-flags", "acid_emitter_delete((AcidEmitter *)n, 3);",
      "acid_emitter_delete((AcidEmitter *)n, 1);"),
    T("tee-dtor-keeps", "    if ((flags & 1) != 0)" + NL + "        bFree(t);",
      "    (void)flags;"),
    T("tee-dtor-always-frees", "    if ((flags & 1) != 0)" + NL
      + "        bFree(t);", "    bFree(t);"),
    T("tee-trigger-empty-skip", "    if (list->next == list)" + NL
      + "        return;" + NL + "    bIdentity(&m);", "    bIdentity(&m);"),
    T("tee-trigger-at-w", "m.v3.w = 1.0f;", "m.v3.w = at->pad;"),
    T("tee-trigger-at-x", "m.v3.x = at->x;", "m.v3.x = at->y;"),
    T("tee-trigger-vel-w", "e->InheritVelocity.w = 0.0f;",
      "e->InheritVelocity.w = velocity->pad;"),
    T("tee-trigger-vel-y", "e->InheritVelocity.y = velocity->y;",
      "e->InheritVelocity.y = velocity->z;"),
    T("tee-trigger-step", "acid_system_trigger_emitter(&WorldEffects, e, "
      "-scale, NULL);", "acid_system_trigger_emitter(&WorldEffects, e, "
      "scale, NULL);"),
    T("tee-trigger-transposed", "bNode    *list = &t->Lists[effect][terrain];",
      "bNode    *list = &t->Lists[terrain % NUM_TERRAIN_EFFECTS][effect];"),
    T("tee-init-twice", "    if (pTerrainEffectEmitters == NULL)" + NL
      + "        pTerrainEffectEmitters", "        pTerrainEffectEmitters"),
    T("tee-init-pool", "0, 16));", "0, 0));"),
    T("tee-close-kept", "        pTerrainEffectEmitters = NULL;" + NL, ""),
    T("tee-close-flags", "(TerrainEffectEmitters *)pTerrainEffectEmitters, 3);",
      "(TerrainEffectEmitters *)pTerrainEffectEmitters, 2);"),
]

EQUIVALENT = {
    "cte-terrain-signed":
        "Read signed, effect - 1 < 5 differs from the unsigned test only "
        "for an effect below 1. CARFX_NONE has returned before it, and no "
        "caller passes a negative effect, which would index in front of "
        "the car's lists either way.",
    "tee-trigger-empty-skip":
        "Without the test, an empty list still fires nothing: the loop "
        "runs over the same list and stops at once. Only bIdentity of the "
        "stack matrix is skipped, which nothing reads.",
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
    triggers = sum(1 for ln in lines if ln.startswith("trigger "))
    print("%d scenarios, %d ops, %d lines, %d triggers, %d differ"
          % (len(sc), ops, len(harness), triggers, n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
