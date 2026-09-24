"""Cross-check 3DS Files/source/average.c against the image's own code.

Average, PidError and Linear are the three small filters out of table.cpp
(0x00187550 .. 0x00187918). RealController keeps an Average of eight; the
AI driver, the psycho driver (three PidErrors), the AI car controller, the
belt mover, the AI engine sound and the player's joystick port keep more.

The oracle is the image itself, run in tools/mipsemu.py:

- Average's constructor, destructor, Record, Reset and Flush;
- PidError's destructor, Record and Reset;
- Linear's Init and GetValue.

PidError's constructor is inline at every call site. The model does what
PsychoDriver's copies do (0x001376cc..0x001376f8): the two Average
constructors, then a zero into each error.

The points worth pinning:

**Record adds before it subtracts.** `fTotal + v` is stored, then the
oldest sample comes off: two roundings, and a total at 2^24 tells them
apart from `fTotal + (v - old)`.

**Reset leaves a ring that divides wrong.** The count goes to zero while
the total counts every slot, so the next Record divides a full ring's sum
by one. PidError::Reset, the only caller, passes the current error after
zeroing it, so it only ever resets to zero.

**The divides are the EE's.** A ring of no slots never counts a sample and
divides by zero every Record. PidError's derivative divides by the time
step, and Linear by the run. All three are `ee_div`, and the model is
`Emu(eediv=True)`.

    python tools/average_check.py
    python tools/average_check.py --mutate [--only a,b]
    python tools/average_check.py --dump PREFIX
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
from mipsemu import Emu, M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/average_test.c"
AC = "3DS Files/source/average.c"
AH = "3DS Files/source/average.h"
SOURCES = [HARNESS, AC, "3DS Files/source/bmem.c"]

HARNESS_TIMEOUT = 60

# ================================================================ the image

NAVG, NPID = 8, 4
AVG = 0x01E00000                    # NAVG * 24
PID = 0x01E00400                    # NPID * 56
LIN = 0x01E00800                    # one Linear
SLACK = 16
MAX_DUMP = 64

SYM = dict(
    ctor="__7Averagei",
    dtor="_$_7Average",
    record="Record__7Averagef",
    reset="Reset__7Averagef",
    flush="Flush__7Averagef",
    pdtor="_$_8PidError",
    precord="Record__8PidErrorff",
    preset="Reset__8PidErrorf",
    linit="Init__6Linearffff",
    lget="GetValue__6Linearf",
)

(OP_TAG, OP_NEW, OP_DEL, OP_REC, OP_RESET, OP_FLUSH, OP_POKE, OP_DPOKE,
 OP_DUMP, OP_PNEW, OP_PDEL, OP_PREC, OP_PRESET, OP_PDUMP, OP_LINIT,
 OP_LGET, OP_JUNK, OP_PJUNK) = range(18)

ARGS = {OP_TAG: 1, OP_NEW: 2, OP_DEL: 2, OP_REC: 2, OP_RESET: 2,
        OP_FLUSH: 2, OP_POKE: 3, OP_DPOKE: 3, OP_DUMP: 1, OP_PNEW: 3,
        OP_PDEL: 2, OP_PREC: 3, OP_PRESET: 2, OP_PDUMP: 1, OP_LINIT: 4,
        OP_LGET: 1, OP_JUNK: 1, OP_PJUNK: 1}

F_SLOTS, F_CUR, F_N, F_TOTAL, F_AVG = range(5)
FOFF = {F_SLOTS: 0, F_CUR: 4, F_N: 8, F_TOTAL: 12, F_AVG: 16}


def fb(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def bf(b):
    return struct.unpack("<f", struct.pack("<I", b & M32))[0]


def f32(x):
    return bf(fb(x))


class F(object):
    """A float argument given as its bits."""
    def __init__(self, bits):
        self.bits = bits & M32


class Script(object):
    def __init__(self):
        self.ops = []
        self.tags = []

    def op(self, code, *args):
        assert len(args) == ARGS[code], (code, args)
        out = []
        for a in args:
            if isinstance(a, F):
                out.append(a.bits)
            elif isinstance(a, float):
                out.append(fb(a))
            else:
                out.append(int(a))
        self.ops.append((code,) + tuple(out))

    def tag(self, s):
        self.tags.append(s)
        self.op(OP_TAG, len(self.tags) - 1)

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

    def rec(self, slot, v, dump=True):
        self.op(OP_REC, slot, float(v))
        if dump:
            self.op(OP_DUMP, slot)

    def prec(self, slot, err, dt, dump=True):
        self.op(OP_PREC, slot, float(err), float(dt))
        if dump:
            self.op(OP_PDUMP, slot)


# ============================================================== the script

def script():
    sc = Script()
    rnd = random.Random(0xa7e5)

    # -- the ring --------------------------------------------------------
    sc.tag("ring")
    sc.op(OP_JUNK, 0)
    sc.op(OP_NEW, 0, 8)
    sc.op(OP_DUMP, 0)
    for v in (1.1, 2.7, -3.3, 0.25, 100.5, -7.75, 3.0e-3, 12.0, 5.5, -0.1,
              9.9, 1.0e6, -2.5, 0.0, 4.4, 8.8, -1.0e-6, 33.3, 2.0, 7.0):
        sc.rec(0, v)

    # The constructor over junk, on its own.
    sc.tag("junk")
    sc.op(OP_JUNK, 1)
    sc.op(OP_NEW, 1, 5)
    sc.op(OP_DUMP, 1)
    for v in (3.5, -1.25, 6.0):
        sc.rec(1, v)

    # -- small rings -----------------------------------------------------
    sc.tag("one slot")
    sc.op(OP_JUNK, 2)
    sc.op(OP_NEW, 2, 1)
    for v in (4.0, -9.5, 0.3, 1.0e-3):
        sc.rec(2, v)

    # No slots: the count never moves off zero, so every Record divides by
    # zero -- the EE's FLT_MAX, with the XOR of the signs, 0/0 included.
    # The sample goes into the slack word, 0xcd junk on both sides.
    sc.tag("no slots")
    sc.op(OP_JUNK, 3)
    sc.op(OP_NEW, 3, 0)
    sc.op(OP_DUMP, 3)
    for v in (0.0, 2.0, -5.0, 5.0, -0.0):
        sc.rec(3, v)
    sc.op(OP_RESET, 3, 1.5)
    sc.op(OP_DUMP, 3)
    sc.op(OP_FLUSH, 3, -2.25)
    sc.op(OP_DUMP, 3)

    # -- Reset and Flush -------------------------------------------------
    sc.tag("reset")
    sc.op(OP_JUNK, 4)
    sc.op(OP_NEW, 4, 6)
    for v in (1.0, 2.0, 3.0):
        sc.rec(4, v, dump=False)
    sc.op(OP_DUMP, 4)
    sc.op(OP_RESET, 4, 2.5)
    sc.op(OP_DUMP, 4)
    for v in (10.0, -4.0, 0.5):
        sc.rec(4, v)
    sc.op(OP_RESET, 4, 0.0)
    sc.op(OP_DUMP, 4)
    sc.rec(4, 7.0)
    sc.op(OP_RESET, 4, -0.0)
    sc.op(OP_DUMP, 4)
    sc.op(OP_RESET, 4, 0.1)
    sc.op(OP_DUMP, 4)

    sc.tag("flush")
    sc.op(OP_FLUSH, 4, 3.25)
    sc.op(OP_DUMP, 4)
    for v in (1.0, -8.0):
        sc.rec(4, v)
    sc.op(OP_FLUSH, 4, 0.1)
    sc.op(OP_DUMP, 4)
    sc.rec(4, 0.7)
    # Flush and Reset both leave the slot index where it was.
    sc.op(OP_POKE, 4, F_CUR, 4)
    sc.op(OP_FLUSH, 4, -1.5)
    sc.op(OP_DUMP, 4)
    sc.op(OP_POKE, 4, F_CUR, 3)
    sc.op(OP_POKE, 4, F_AVG, fb(77.0))
    sc.op(OP_RESET, 4, 9.0)
    sc.op(OP_DUMP, 4)

    # -- the arithmetic's order -----------------------------------------
    # At 2^24, (total + v) - old and total + (v - old) are different
    # floats.
    sc.tag("order")
    sc.op(OP_JUNK, 5)
    sc.op(OP_NEW, 5, 4)
    sc.op(OP_POKE, 5, F_TOTAL, fb(16777216.0))
    sc.op(OP_DPOKE, 5, 0, fb(1.0))
    sc.rec(5, 1.0)
    sc.op(OP_POKE, 5, F_TOTAL, fb(16777216.0))
    sc.op(OP_DPOKE, 5, 1, fb(3.0))
    sc.rec(5, 1.0)
    sc.op(OP_POKE, 5, F_TOTAL, fb(-16777216.0))
    sc.op(OP_DPOKE, 5, 2, fb(-1.0))
    sc.rec(5, -1.0)

    # -- the counters, poked --------------------------------------------
    sc.tag("counters")
    # More samples than slots: no increment, and the divide is by the
    # poked count.
    sc.op(OP_POKE, 5, F_N, 10)
    sc.rec(5, 2.0)
    # Exactly full.
    sc.op(OP_POKE, 5, F_N, 4)
    sc.rec(5, 2.0)
    # One short.
    sc.op(OP_POKE, 5, F_N, 3)
    sc.rec(5, 2.0)
    # The slot index at the last slot, at the count, and past it into the
    # slack: each wraps back to zero after its store.
    for cur in (3, 4, 6):
        sc.op(OP_POKE, 5, F_CUR, cur)
        sc.rec(5, 0.5)
    # Negative samples: still below the slot count, so it counts up.
    sc.op(OP_POKE, 5, F_N, -3)
    sc.rec(5, 1.0)
    sc.rec(5, 1.0)
    # A shrunk ring: the index beyond the new count wraps.
    sc.op(OP_POKE, 5, F_SLOTS, 2)
    sc.op(OP_POKE, 5, F_CUR, 1)
    sc.rec(5, 6.0)
    sc.rec(5, 6.0)
    sc.rec(5, 6.0)

    # -- a long ring ------------------------------------------------------
    sc.tag("long")
    sc.op(OP_JUNK, 6)
    sc.op(OP_NEW, 6, 40)
    for i in range(130):
        sc.rec(6, f32(rnd.uniform(-500.0, 500.0)), dump=(i % 13 == 12))
    sc.op(OP_DUMP, 6)

    # -- the destructor ---------------------------------------------------
    sc.tag("delete")
    sc.op(OP_DEL, 0, 0)
    sc.op(OP_DEL, 1, 1)
    sc.op(OP_DEL, 2, 3)
    sc.op(OP_DEL, 3, 2)
    sc.op(OP_NEW, 7, 3)
    sc.op(OP_DEL, 7, 1)

    # -- PidError ---------------------------------------------------------
    sc.tag("pid")
    sc.op(OP_PJUNK, 0)
    sc.op(OP_PNEW, 0, 15, 5)
    sc.op(OP_PDUMP, 0)
    dt = f32(1.0 / 30.0)
    for err in (0.5, 0.75, 0.6, -0.2, -0.9, 0.0, 1.3, 1.25, 0.4, -0.05):
        sc.prec(0, err, dt)
    sc.prec(0, 2.0, 0.0)
    sc.prec(0, 2.0, 0.0)
    sc.prec(0, -1.0, 0.0)
    sc.prec(0, 0.3, -0.5)
    sc.op(OP_PRESET, 0, 0.7)
    sc.op(OP_PDUMP, 0)
    sc.prec(0, 0.9, dt)
    sc.prec(0, -0.4, 0.02)
    sc.op(OP_PRESET, 0, -3.0)
    sc.op(OP_PDUMP, 0)

    sc.tag("pid small")
    sc.op(OP_PJUNK, 1)
    sc.op(OP_PNEW, 1, 6, 3)
    for i in range(20):
        sc.prec(1, f32(rnd.uniform(-2.0, 2.0)), f32(rnd.uniform(0.01, 0.1)),
                dump=(i % 4 == 3))
    sc.op(OP_PDUMP, 1)
    sc.op(OP_PJUNK, 2)
    sc.op(OP_PNEW, 2, 1, 2)
    sc.prec(2, 1.0, 0.5)
    sc.prec(2, 3.0, 0.25)

    sc.tag("pid delete")
    sc.op(OP_PDEL, 0, 0)
    sc.op(OP_PDEL, 1, 1)
    sc.op(OP_PDEL, 2, 3)

    # -- Linear -----------------------------------------------------------
    sc.tag("linear")
    for pts in ((0.0, 1.0, 10.0, 21.0), (1.0, 5.0, 3.0, -1.0),
                (-2.5, 0.3, 7.25, 0.9), (4.0, 2.0, 4.0, 6.0),
                (4.0, 2.0, 4.0, 2.0), (4.0, -2.0, 4.0, 6.0),
                (0.1, 0.2, 0.3, 0.4), (1.0e6, 3.0, 1.0e6 + 64.0, 5.0)):
        sc.op(OP_LINIT, *[float(v) for v in pts])
        for x in (0.0, 1.0, -3.0, 0.1, 17.5, 1.0e6):
            sc.op(OP_LGET, float(x))
    for i in range(12):
        sc.op(OP_LINIT, *[f32(rnd.uniform(-100.0, 100.0)) for _ in range(4)])
        sc.op(OP_LGET, f32(rnd.uniform(-100.0, 100.0)))
    return sc


# ================================================================ the model

class Model(object):
    def __init__(self, sc):
        self.sc = sc
        self.out = []
        e = self.e = Emu(ieee=True, eediv=True)
        e.stub_bware()
        self.fn = {k: e.addr_of(v) for k, v in SYM.items()}
        self.heap = []                  # (addr, span, label)
        self.stubs()

    def emit(self, s):
        self.out.append(s)

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        for i in range(NAVG):
            if a == AVG + 24 * i:
                return "a%d" % i
        for i in range(NPID):
            if a == PID + 56 * i:
                return "p%d" % i
            if a == PID + 56 * i + 24:
                return "p%d.d" % i
        for base, span, name in self.heap:
            if base <= a < base + span:
                return name if a == base else "%s+%d" % (name, a - base)
        return "?"

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
            self.heap.append((p, span, lab))
            self.emit("  alloc %s size %d name %s flags %d pool %d"
                      % (lab, size, cstr(arg(1)), s32(arg(2)), s32(arg(3))))
            return p

        def free(em):
            self.emit("  free %s" % self.label(arg(0)))

        e.stub("bMalloc__FiPCcii", malloc)
        e.stub("__builtin_delete", free)
        e.stub("bFree__FPv", free)

    def dump(self, name, a):
        e = self.e
        n = s32(e.u32(a))
        self.emit("%s slots %d cur %d n %d total %08x avg %08x data %s"
                  % (name, n, s32(e.u32(a + 4)), s32(e.u32(a + 8)),
                     e.u32(a + 12), e.u32(a + 16),
                     self.label(e.u32(a + 20))))
        k = min(n + 1, MAX_DUMP)
        d = e.u32(a + 20)
        for i in range(0, k, 8):
            self.emit("  d%d %s" % (i, " ".join(
                "%08x" % e.u32(d + 4 * j) for j in range(i, min(i + 8, k)))))

    def junk(self, a, seed):
        e = self.e
        u = 0x7f000000 | seed
        e.put32(a, 0x1111 + seed)
        e.put32(a + 4, 0x2222 + seed)
        e.put32(a + 8, 0x3333 + seed)
        e.put32(a + 12, u)
        e.put32(a + 16, u ^ 0x00400000)
        e.put32(a + 20, 0)

    def run(self):
        e, fn = self.e, self.fn
        tags = self.sc.tags
        for o in self.sc.ops:
            code, a = o[0], o[1:]
            if code == OP_TAG:
                self.emit("[%s]" % tags[a[0]])
            elif code == OP_NEW:
                r = e.call(fn["ctor"], AVG + 24 * a[0], a[1])
                self.emit("new a%d %d -> %s" % (a[0], s32(a[1]),
                                                self.label(r)))
            elif code == OP_DEL:
                self.emit("del a%d %d" % (a[0], a[1]))
                e.call(fn["dtor"], AVG + 24 * a[0], a[1])
            elif code in (OP_REC, OP_RESET, OP_FLUSH):
                name = {OP_REC: "rec", OP_RESET: "reset",
                        OP_FLUSH: "flush"}[code]
                self.emit("%s a%d %08x" % (name, a[0], a[1]))
                e.fpr[12] = a[1]
                e.call(fn[{OP_REC: "record", OP_RESET: "reset",
                           OP_FLUSH: "flush"}[code]], AVG + 24 * a[0])
            elif code == OP_POKE:
                e.put32(AVG + 24 * a[0] + FOFF[a[1]], a[2])
            elif code == OP_DPOKE:
                d = e.u32(AVG + 24 * a[0] + 20)
                e.put32(d + 4 * a[1], a[2])
            elif code == OP_DUMP:
                p = AVG + 24 * a[0]
                self.dump("a%d" % a[0], p)
                # GetValue and GetTotal are inline: the loads.
                self.emit("value %08x total %08x"
                          % (e.u32(p + 16), e.u32(p + 12)))
            elif code == OP_PNEW:
                # Inline: PsychoDriver's copy, 0x001376cc..0x001376f8.
                p = PID + 56 * a[0]
                e.call(fn["ctor"], p, a[1])
                e.call(fn["ctor"], p + 24, a[2])
                e.put32(p + 48, 0)
                e.put32(p + 52, 0)
                self.emit("pnew p%d %d %d -> %s"
                          % (a[0], s32(a[1]), s32(a[2]), self.label(p)))
            elif code == OP_PDEL:
                self.emit("pdel p%d %d" % (a[0], a[1]))
                e.call(fn["pdtor"], PID + 56 * a[0], a[1])
            elif code == OP_PREC:
                self.emit("prec p%d %08x %08x" % (a[0], a[1], a[2]))
                e.fpr[12] = a[1]
                e.fpr[13] = a[2]
                e.call(fn["precord"], PID + 56 * a[0])
            elif code == OP_PRESET:
                self.emit("preset p%d %08x" % (a[0], a[1]))
                e.fpr[12] = a[1]
                e.call(fn["preset"], PID + 56 * a[0])
            elif code == OP_PDUMP:
                p = PID + 56 * a[0]
                self.emit("p%d err %08x prev %08x"
                          % (a[0], e.u32(p + 48), e.u32(p + 52)))
                self.dump("p%d.i" % a[0], p)
                self.dump("p%d.d" % a[0], p + 24)
            elif code == OP_LINIT:
                for k in range(4):
                    e.fpr[12 + k] = a[k]
                e.call(fn["linit"], LIN)
                self.emit("linit %08x %08x %08x %08x -> m %08x b %08x"
                          % (a[0], a[1], a[2], a[3], e.u32(LIN),
                             e.u32(LIN + 4)))
            elif code == OP_LGET:
                e.fpr[12] = a[0]
                e.call(fn["lget"], LIN)
                self.emit("lget %08x -> %08x" % (a[0], e.fpr[0] & M32))
            elif code == OP_JUNK:
                self.junk(AVG + 24 * a[0], a[0])
            elif code == OP_PJUNK:
                p = PID + 56 * a[0]
                u = 0x7e000000 | a[0]
                self.junk(p, 16 + a[0])
                self.junk(p + 24, 32 + a[0])
                e.put32(p + 48, u)
                e.put32(p + 52, u ^ 0x00200000)
            else:
                raise ValueError("op %d" % code)
        return self.out


def model(sc):
    return Model(sc).run()


# ================================================================ the build


def build_harness(tmp, name="average_test"):
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
    # -- the constructor ----------------------------------------------------
    ("ctor-cur", AC, "    a->nCurrentSlot = 0;\n    a->nSamples     = 0;\n",
     "    a->nSamples     = 0;\n"),
    ("ctor-samples", AC, "    a->nSamples     = 0;\n", ""),
    ("ctor-total", AC, "    a->fTotal       = 0.0f;\n", ""),
    ("ctor-average", AC, "    a->fAverage     = 0.0f;\n", ""),
    ("ctor-slots", AC, "    a->nSlots       = slots;",
     "    a->nSlots       = slots + 1;"),
    ("ctor-size", AC, "(uint32_t)slots << 2", "(uint32_t)slots << 3"),
    ("ctor-name", AC, '"..\\\\indep\\\\src\\\\table.cpp"',
     '"..\\\\indep\\\\src\\\\average.cpp"'),
    ("ctor-line", AC, "table.cpp\", 120, 16", "table.cpp\", 121, 16"),
    ("ctor-pool", AC, "table.cpp\", 120, 16", "table.cpp\", 120, 0"),
    ("ctor-clear", AC, "    memset(a->pData, 0, (size_t)(uint32_t)size);\n",
     ""),
    ("ctor-return", AC, "    a->pData = bMalloc(size, \"..\\\\indep\\\\src\\\\table.cpp\", 120, 16);\n    memset(a->pData, 0, (size_t)(uint32_t)size);\n    return a;",
     "    a->pData = bMalloc(size, \"..\\\\indep\\\\src\\\\table.cpp\", 120, 16);\n    memset(a->pData, 0, (size_t)(uint32_t)size);\n    return NULL;"),

    # -- the destructor -----------------------------------------------------
    ("dtor-data", AC, "    bFree(a->pData);\n    if (flags & 1)\n        bFree(a);",
     "    if (flags & 1)\n        bFree(a);"),
    ("dtor-flag", AC, "    bFree(a->pData);\n    if (flags & 1)",
     "    bFree(a->pData);\n    if (flags & 2)"),

    # -- Record -------------------------------------------------------------
    ("rec-count-test", AC, "    if (n < slots) {", "    if (n <= slots) {"),
    ("rec-count-store", AC, "        a->nSamples = n;\n", ""),
    ("rec-count-step", AC, "        n = n + 1;", "        n = n + 2;"),
    ("rec-add", AC, "    a->fTotal = a->fTotal + v;", "    a->fTotal = a->fTotal;"),
    ("rec-order", AC,
     "    a->fTotal = a->fTotal + v;\n    cur  = a->nCurrentSlot;\n    slot = &a->pData[cur];\n    a->nCurrentSlot = cur + 1;\n    a->fTotal = a->fTotal - *slot;",
     "    cur  = a->nCurrentSlot;\n    slot = &a->pData[cur];\n    a->nCurrentSlot = cur + 1;\n    a->fTotal = a->fTotal + (v - *slot);"),
    ("rec-sub", AC, "    a->fTotal = a->fTotal - *slot;", ""),
    ("rec-store", AC, "    *slot = v;\n", ""),
    ("rec-step", AC, "    a->nCurrentSlot = cur + 1;",
     "    a->nCurrentSlot = cur;"),
    ("rec-divisor", AC, "ee_div(a->fTotal, (float)n)",
     "ee_div(a->fTotal, (float)slots)"),
    ("rec-plain-div", AC, "ee_div(a->fTotal, (float)n)",
     "(a->fTotal / (float)n)"),
    ("rec-wrap-test", AC, "    if (!(cur + 1 < slots))",
     "    if (!(cur < slots))"),
    ("rec-wrap-le", AC, "    if (!(cur + 1 < slots))",
     "    if (!(cur + 1 <= slots))"),
    ("rec-wrap-store", AC,
     "    if (!(cur + 1 < slots))\n        a->nCurrentSlot = 0;\n", ""),
    ("rec-slots-late", AC, "    int32_t slots = a->nSlots;\n    int32_t n     = a->nSamples;",
     "    int32_t slots = a->nSamples;\n    int32_t n     = a->nSamples;"),

    # -- Reset --------------------------------------------------------------
    ("reset-fill", AC,
     "    for (i = 0; i < a->nSlots; i++)\n        a->pData[i] = v;\n    // The count",
     "    for (i = 1; i < a->nSlots; i++)\n        a->pData[i] = v;\n    // The count"),
    ("reset-count", AC, "    a->nSamples = 0;\n    a->fTotal   = v * (float)a->nSlots;",
     "    a->nSamples = a->nSlots;\n    a->fTotal   = v * (float)a->nSlots;"),
    ("reset-total", AC,
     "    a->nSamples = 0;\n    a->fTotal   = v * (float)a->nSlots;",
     "    a->nSamples = 0;\n    a->fTotal   = 0.0f;"),
    ("reset-average", AC,
     "    a->nSamples = 0;\n    a->fTotal   = v * (float)a->nSlots;",
     "    a->nSamples = 0;\n    a->fAverage = v;\n    a->fTotal   = v * (float)a->nSlots;"),
    ("reset-cur", AC,
     "    a->nSamples = 0;\n    a->fTotal   = v * (float)a->nSlots;",
     "    a->nSamples = 0;\n    a->nCurrentSlot = 0;\n    a->fTotal   = v * (float)a->nSlots;"),

    # -- Flush --------------------------------------------------------------
    ("flush-fill", AC,
     "    for (i = 0; i < a->nSlots; i++)\n        a->pData[i] = v;\n    a->fAverage = v;",
     "    for (i = 0; i < a->nSlots - 1; i++)\n        a->pData[i] = v;\n    a->fAverage = v;"),
    ("flush-average", AC, "    a->fAverage = v;\n    a->nSamples = a->nSlots;",
     "    a->nSamples = a->nSlots;"),
    ("flush-count", AC, "    a->nSamples = a->nSlots;\n",
     "    a->nSamples = 0;\n"),
    ("flush-total", AC,
     "    a->nSamples = a->nSlots;\n    a->fTotal   = v * (float)a->nSlots;",
     "    a->nSamples = a->nSlots;\n    a->fTotal   = v;"),
    ("flush-cur", AC,
     "    a->nSamples = a->nSlots;\n    a->fTotal   = v * (float)a->nSlots;",
     "    a->nSamples = a->nSlots;\n    a->nCurrentSlot = 0;\n    a->fTotal   = v * (float)a->nSlots;"),

    # -- the getters --------------------------------------------------------
    ("get-value", AC, "    return a->fAverage;", "    return a->fTotal;"),
    ("get-total", AC, "    return a->fTotal;\n}\n\n// ----",
     "    return a->fAverage;\n}\n\n// ----"),

    # -- PidError -----------------------------------------------------------
    ("pinit-integral", AC, "    average_init(&p->aIntegral, integralSlots);",
     "    average_init(&p->aIntegral, derivativeSlots);"),
    ("pinit-derivative", AC,
     "    average_init(&p->aDerivative, derivativeSlots);",
     "    average_init(&p->aDerivative, integralSlots);"),
    ("pinit-err", AC, "    p->fCurrentError  = 0.0f;\n    p->fPreviousError = 0.0f;\n    return p;",
     "    p->fPreviousError = 0.0f;\n    return p;"),
    ("pinit-prev", AC, "    p->fCurrentError  = 0.0f;\n    p->fPreviousError = 0.0f;\n    return p;",
     "    p->fCurrentError  = 0.0f;\n    return p;"),
    ("pdtor-order", AC,
     "    average_destroy(&p->aDerivative, 2);\n    average_destroy(&p->aIntegral, 2);",
     "    average_destroy(&p->aIntegral, 2);\n    average_destroy(&p->aDerivative, 2);"),
    ("pdtor-member-flags", AC, "    average_destroy(&p->aIntegral, 2);",
     "    average_destroy(&p->aIntegral, 3);"),
    ("pdtor-self", AC, "    average_destroy(&p->aIntegral, 2);\n    if (flags & 1)",
     "    average_destroy(&p->aIntegral, 2);\n    if (flags & 2)"),
    ("prec-err", AC, "    p->fCurrentError  = err;\n", ""),
    ("prec-delta", AC, "    delta             = err - prev;",
     "    delta             = prev - err;"),
    ("prec-prev", AC, "    p->fPreviousError = prev;\n", ""),
    ("prec-trapezoid", AC, "dt * (prev + delta * 0.5f)", "dt * (err - delta * 0.5f)"),
    ("prec-half", AC, "dt * (prev + delta * 0.5f)", "dt * (prev + delta * 0.25f)"),
    ("prec-dt", AC, "dt * (prev + delta * 0.5f)", "(prev + delta * 0.5f)"),
    ("prec-deriv", AC, "ee_div(delta, dt)", "ee_div(err, dt)"),
    ("prec-deriv-div", AC, "ee_div(delta, dt)", "(delta / dt)"),
    ("prec-swap", AC,
     "    average_record(&p->aIntegral, dt * (prev + delta * 0.5f));\n    average_record(&p->aDerivative, ee_div(delta, dt));",
     "    average_record(&p->aDerivative, dt * (prev + delta * 0.5f));\n    average_record(&p->aIntegral, ee_div(delta, dt));"),
    ("preset-err", AC, "    p->fCurrentError  = 0.0f;\n    p->fPreviousError = err;",
     "    p->fCurrentError  = err;\n    p->fPreviousError = err;"),
    ("preset-prev", AC, "    p->fPreviousError = err;\n    zero",
     "    p->fPreviousError = 0.0f;\n    zero"),
    ("preset-value", AC, "    average_reset(&p->aIntegral, zero);",
     "    average_reset(&p->aIntegral, err);"),
    ("preset-derivative", AC, "    average_reset(&p->aDerivative, zero);\n",
     ""),

    # -- Linear -------------------------------------------------------------
    ("linit-rise", AC, "ee_div(y2 - y1, x2 - x1)", "ee_div(y1 - y2, x2 - x1)"),
    ("linit-run", AC, "ee_div(y2 - y1, x2 - x1)", "ee_div(y2 - y1, x1 - x2)"),
    ("linit-plain-div", AC, "ee_div(y2 - y1, x2 - x1)", "((y2 - y1) / (x2 - x1))"),
    ("linit-b", AC, "    l->b = y1 - m * x1;", "    l->b = y2 - m * x2;"),
    ("lget", AC, "    return l->m * x + l->b;", "    return l->m * (x + l->b);"),
]

EQUIVALENT = {}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name


def mutate_pass(only=None):
    sc = script()
    base = model(sc)
    caught = 0
    survived = []
    missing = []
    equivalent = []
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only is not None:
        unknown = sorted(set(only) - {m[0] for m in MUTATIONS})
        if unknown:
            sys.exit("no such mutation: " + " ".join(unknown))

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

    for name, rel, before, after in todo:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if probe not in text:
            missing.append(name)
            print("  %-28s PATTERN NOT FOUND" % name)
            continue
        try:
            hostbuild.write_source(path, text.replace(probe, repl, 1))
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = build_harness(tmp)
                except SystemExit:
                    print("  %-28s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, ops, out)
                if rc == pcc.HARNESS_HUNG:
                    print("  %-28s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-28s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-28s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-28s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-28s SURVIVED" % name)
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
    if missing:
        print("%d PATTERN NOT FOUND -- the tally above is over %d of %d"
              % (len(missing), len(real), len(todo)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
    for name in holes:
        print("  unexplained: %s" % name)
    return 1 if (holes or missing) else 0


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
