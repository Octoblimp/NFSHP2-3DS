"""Cross-check 3DS Files/source/stomper.c, the render eggs, against the
retail image's own code.

The Stomper (stomper.h) pokes the globals a render egg names and puts them
back. The oracle is SLES_507.31 run in tools/mipsemu.py:

- _GLOBAL_$I$StomperRenderEggs (0x0024c048), run once, for the lists'
  floats;
- StompEntry's Set, Clear, SetAll and ClearAll (0x0024b918, 0x0024ba38,
  0x0024bb20, 0x0024bb78), on the eggs' lists and on a list of the
  script's own, every type and some that are none;
- InitStomper and CloseStomper (0x0024bbd0, 0x0024bc08), the constructor
  and destructor (0x0024bc30, 0x0024bc80), with bMalloc and
  __builtin_delete stubbed to log;
- the Stomper's Clear, Set, Suspend, Resume and ClearSet (0x0024bcd0,
  0x0024bd20, 0x0024bd78, 0x0024bdb0, 0x0024c3e8);
- the six render-egg calls (0x0024bdc0, 0x0024bf18, 0x0024bfc0,
  0x0024bfe0, 0x0024c000, 0x0024c030), on TheEasterEggs' Codes pointed
  at a table of the script's;
- WeatherManQuery (0x001a84f0) with the Heavy Fog egg's flag or the
  tweaker's set; the region walk under them is weather_check.py's.

RadialBlurOnOff(bool, int) (0x0010f1f8), the Motion Blur egg's function,
is stubbed on both sides to log and return its player changed, so that
what Clear hands back is seen to be what Set kept; radialblur_check.py
runs the real one.

Not run: eggs 1 to 7, the demo's, which nothing in the image sets (only
RandomRenderEgg, 0x0024bde0, which nothing calls) and which the port does
not have: their slots are an empty list. The facts hold the first values
of the stomped globals the harness does not link (carrender.c's and
eview.c's) to the image.

The points worth pinning:

**Set does not clear the egg set before,** and saves from the stack's
start, so a second Set overwrites the first's saves: a Clear then puts
back the second's.

**Suspend keeps nCurrent and Resume sets it again:** the per-frame pair
around the mirror and the HUD. With none set both do nothing.

**bEnabled is not read** by anything here: a disabled Stomper still sets.

    python tools/stomper_check.py
    python tools/stomper_check.py --mutate [--only a,b] [--jobs N]
    python tools/stomper_check.py --dump PREFIX
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
from mipsemu import M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)
SRC = "3DS Files/source/"

HARNESS = "tools/src/stomper_test.c"
SC = SRC + "stomper.c"
WMC = SRC + "weatherman.c"
SOURCES = [HARNESS, SC, WMC, SRC + "bmath.c", SRC + "bmathtab.c"]

HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = retail_model.RETAIL_GP
SINIT = 0x0024c048
E_SET = 0x0024b918
E_CLEAR = 0x0024ba38
E_SETALL = 0x0024bb20
E_CLEARALL = 0x0024bb78
INIT = 0x0024bbd0
CLOSE = 0x0024bc08
CTOR = 0x0024bc30
DTOR = 0x0024bc80
S_CLEAR = 0x0024bcd0
S_SET = 0x0024bd20
S_SUSPEND = 0x0024bd78
S_RESUME = 0x0024bdb0
S_CLEARSET = 0x0024c3e8
RESET_EGGS = 0x0024bdc0
FROM_CODES = 0x0024bf18
SUSPEND_EGGS = 0x0024bfc0
RESUME_EGGS = 0x0024bfe0
DISABLE_EGGS = 0x0024c000
ENABLE_EGGS = 0x0024c030
QUERY = 0x001a84f0
BMALLOC = 0x002577c0
DELETE = 0x00114e98
ONOFF = 0x0010f1f8
EIDENTITY = 0x0011b1b0          # eIdentity__FP8bMatrix4
CAR_RENDER_MATRIX = 0x002e0270

P_STOMPER = GP - 14932
CODES_PTR = 0x0031d7f4          # TheEasterEggs (0x0031d7e8) + 12
CODE = 56
WORLD_TIME_FRAMES = GP - 19564
TWEAK = GP - 19280              # Use, Fog, FogStart, R, G, B

# The stomped globals, in the dump's order.
TARGETS = ([CAR_RENDER_MATRIX + 4 * i for i in range(16)]   # CarRenderMatrix
           + [GP - 19244,                           # OverrideAnimatedDriverLOD
              GP - 23744,                           # ForceRenderDriver
              GP - 19408]                           # nBoneScale
           + [0x003110d0 + 4 * i for i in range(4)]  # vBoneScale
           + [GP - 24048,                           # ForceBlackAndWhite
              GP - 19256]                           # WeatherHeavyFog
           + [GP - 25060 + 4 * i for i in range(5)])  # EnvPassAlpha*
NTARGETS = len(TARGETS)

# The script's.
LIST = 0x01E00000
NLIST = 24
TGT = 0x01E00400
NTGT = 64
SAVE = 0x01E00800
NSAVE = 128
FI = 0x01E01000
FF = 0x01E01010
CODES = 0x01E02000
NCODES = 10
OBJ2 = 0x01E03000
Q = 0x01E04000
POS = 0x01E04040

INT8, INT16, INT32, FLOAT, FINT, FFLOAT, NESTED, END = range(8)


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


# ============================================================== the script

class Script(object):
    def __init__(self):
        self.lines = []

    def op(self, *a):
        self.lines.append(" ".join(str(x) for x in a))

    def tag(self, s):
        self.lines.append("T " + s)

    def junk(self, rnd, which=None):
        """Seeded words into the targets: small ints for the ints, floats
        for the floats, so that a restore is seen."""
        for i in (which if which is not None else range(NTARGETS)):
            if i < 16 or 19 <= i < 23:
                v = fbits(rnd.choice((-1.0, 1.0)) * rnd.uniform(0.01, 9.0))
            else:
                v = rnd.randrange(-50, 300) & M32
            self.op("P", i, "%x" % v)


def script():
    sc = Script()
    rnd = random.Random(0x5704)

    # -- before InitStomper: the wrappers do nothing ---------------------
    sc.tag("boot")
    sc.op("D")
    for c in ("RR", "SR", "RS", "DR", "ER", "EG"):
        sc.op(c)
    sc.op("O", 0, 1)
    sc.op("EG")
    sc.op("O", 0, 0)
    sc.op("D")

    sc.tag("init")
    sc.op("I")
    sc.op("D")
    sc.op("SF", "11")
    sc.op("D")

    # -- each egg on the first values, then on junk ----------------------
    for e in (8, 9, 10, 11, 12):
        sc.tag("egg %d" % e)
        sc.op("S", e)
        sc.op("D")
        sc.op("C")
        sc.op("D")
        sc.junk(rnd)
        sc.op("S", e)
        sc.op("D")
        # Changed while set: the clear puts back what the set kept.
        sc.junk(rnd, rnd.sample(range(NTARGETS), 6))
        sc.op("C")
        sc.op("D")
        sc.op("C")
        sc.op("D")

    # -- out of range: nothing ------------------------------------------
    sc.tag("range")
    for e in (0, 13, 14, -1, 0x7fffffff, -0x80000000):
        sc.op("S", e)
        sc.op("D")
        sc.op("CS", e)
        sc.op("D")

    # -- two sets without a clear ---------------------------------------
    sc.tag("set twice")
    sc.junk(rnd)
    sc.op("SF", "a0")
    sc.op("S", 8)
    sc.op("S", 11)
    sc.op("D")
    sc.op("C")
    sc.op("D")
    sc.op("S", 11)
    sc.op("S", 11)
    sc.op("D")
    sc.op("C")
    sc.op("D")
    sc.op("S", 12)
    sc.op("S", 9)
    sc.op("S", 10)
    sc.op("D")
    sc.op("C")
    sc.op("D")

    # -- suspend and resume ---------------------------------------------
    sc.tag("suspend")
    sc.op("SU")
    sc.op("D")
    sc.op("RE")
    sc.op("D")
    for e in (9, 8, 11):
        sc.op("S", e)
        sc.op("SU")
        sc.op("D")
        sc.junk(rnd, rnd.sample(range(NTARGETS), 4))
        sc.op("RE")
        sc.op("D")
        sc.op("SU")
        sc.op("SU")
        sc.op("D")
        sc.op("RE")
        sc.op("RE")
        sc.op("D")
        sc.op("SR")
        sc.op("RS")
        sc.op("D")
        sc.op("C")
        sc.op("D")

    sc.tag("clear set")
    for e in (10, 12, 12, 0, 8, 13, 11):
        sc.op("CS", e)
        sc.op("D")
    sc.op("RR")
    sc.op("D")

    # -- the codes -------------------------------------------------------
    sc.tag("codes")
    sets = ([[]] + [[n] for n in range(NCODES)]
            + [[1, 0], [2, 1], [3, 2], [4, 3], [8, 4], [8, 5], [5, 6, 7, 9],
               [9, 8], [4, 2], [0, 1, 2, 3, 4, 8]])
    for on in sets:
        for n in range(NCODES):
            sc.op("O", n, rnd.choice((1, 2, -1, 0x100)) if n in on else 0)
        sc.op("RR")
        sc.op("EG")
        sc.op("D")
    # A set egg is not cleared first: the codes' Set over another's.
    sc.op("O", 2, 1)
    sc.op("EG")
    sc.op("EG")
    sc.op("D")
    sc.op("RR")
    sc.op("D")
    for n in range(NCODES):
        sc.op("O", n, 0)

    # -- disable and enable ---------------------------------------------
    sc.tag("disable")
    sc.op("S", 10)
    sc.op("DR")
    sc.op("D")
    sc.op("O", 3, 1)
    sc.op("EG")
    sc.op("D")
    sc.op("SR")
    sc.op("RS")
    sc.op("D")
    sc.op("ER")
    sc.op("D")
    sc.op("DR")
    sc.op("ER")
    sc.op("ER")
    sc.op("D")
    sc.op("O", 3, 0)

    # -- no Stomper ------------------------------------------------------
    sc.tag("null")
    sc.op("S", 12)
    sc.op("N")
    for c in ("RR", "SR", "RS", "DR", "ER", "EG"):
        sc.op(c)
    sc.op("D")
    sc.op("NR")
    sc.op("D")
    sc.op("C")

    # -- the weather query -----------------------------------------------
    sc.tag("heavy fog")
    pos = ["%x" % fbits(v) for v in (10.0, 2.0, -5.0)]
    frames = (0, 1, 2, 59, 100, 1000, 1234, 12345, 54321, 108000, 1 << 20,
              (1 << 24) + 1, 0x7fffffff, -1, -77777)
    sc.op("S", 10)
    for fr in frames:
        sc.op("W", fr, *pos)
    sc.op("C")
    sc.op("TW", 1, "%x" % fbits(0.25), "%x" % fbits(-300.0), 50, 32, 7)
    sc.op("W", 777, *pos)
    sc.op("S", 10)
    sc.op("W", 777, *pos)
    sc.op("W", 31, "%x" % fbits(-1e6), "%x" % fbits(3.5), "%x" % fbits(0.0))
    sc.op("C")
    sc.op("TW", 1, "%x" % fbits(1.99), "%x" % fbits(-1000.0), 300, -5, 81)
    sc.op("W", 5, *pos)
    sc.op("P", 24, "%x" % 0x80000000)
    sc.op("W", 6, *pos)
    sc.op("P", 24, 0)
    sc.op("TW", 0, 0, 0, 0, 0, 0)
    sc.op("D")

    # -- the script's own lists -----------------------------------------
    sc.tag("entries")
    sc.op("LF", "21")
    # One of each type, set and cleared alone.
    singles = [(INT8, 3, 0x1234567f), (INT8, 0, 0xffffff80),
               (INT16, 6, 0x0000beef), (INT16, 10, 0xffff8001),
               (INT32, 12, 0xdeadbeef), (INT32, 60, 0x00000001),
               (FLOAT, 16, fbits(0.5)), (FLOAT, 20, fbits(-123.25)),
               (FINT, 0, 0x01234567), (FINT, 0, 0xfffffffe),
               (FFLOAT, 0, fbits(5.5)), (FFLOAT, 0, fbits(-0.001)),
               (END, 0, 0x55), (8, 0, 9), (0x7fffffff, 0, 1),
               (-1 & M32, 0, 2), (-8 & M32, 0, 3)]
    for k, (t, p, v) in enumerate(singles):
        sc.op("LE", k, s32(t), p, "%x" % v)
        sc.op("LE", k + 1, END, 0, 0)
        for off in (0, 4, 40):
            sc.op("L1", k, off)
            sc.op("L0", k, off)
        sc.op("LS", k, 8)
        sc.op("LC", k, 8)

    sc.tag("lists")
    sc.op("LF", "93")
    # 0..6 a list with a nested one at 10..13, which nests 16..17.
    ents = [(INT32, 0, 0x11111111), (INT8, 5, 0xaa), (NESTED, 10, 0),
            (FLOAT, 8, fbits(2.0)), (FINT, 0, 0x77), (INT16, 30, 0x4242),
            (END, 0, 0)]
    for k, (t, p, v) in enumerate(ents):
        sc.op("LE", k, t, p, "%x" % v)
    nest = [(INT32, 40, 0x22222222), (NESTED, 16, 0), (FFLOAT, 0,
            fbits(1.5)), (END, 0, 0)]
    for k, (t, p, v) in enumerate(nest):
        sc.op("LE", 10 + k, t, p, "%x" % v)
    for k, (t, p, v) in enumerate([(INT8, 63, 0x01), (END, 0, 0)]):
        sc.op("LE", 16 + k, t, p, "%x" % v)
    sc.op("LS", 0, 0)
    sc.op("LC", 0, 0)
    sc.op("LS", 0, 12)
    sc.op("LS", 2, 64)
    sc.op("LC", 2, 64)
    sc.op("LC", 0, 12)
    # One global twice: the first poke's value stays after the clear.
    for k, (t, p, v) in enumerate([(INT32, 24, 0x0000aaaa),
                                   (INT32, 24, 0x0000bbbb),
                                   (INT8, 25, 0xcc), (END, 0, 0)]):
        sc.op("LE", 20 + k, t, p, "%x" % v)
    sc.op("LS", 20, 0)
    sc.op("LC", 20, 0)
    # A type that is none in the middle: walked past, nothing kept.
    sc.op("LE", 3, 9, 0, 0)
    sc.op("LS", 0, 4)
    sc.op("LC", 0, 4)
    # An empty list, and a nest of an empty list.
    sc.op("LS", 6, 20)
    sc.op("LE", 5, NESTED, 6, 0)
    sc.op("LS", 5, 20)
    sc.op("LC", 5, 20)

    # -- a second Stomper, over junk -------------------------------------
    sc.tag("second")
    for flags in (0, 1, 2, 3):
        sc.op("K", "%x" % (0x30 + flags))
        sc.op("KC")
        sc.op("KX", flags)

    # -- a long run --------------------------------------------------------
    sc.tag("random")
    for i in range(160):
        r = rnd.random()
        if r < 0.25:
            sc.op("S", rnd.choice((8, 9, 10, 11, 12, 0, 13)))
        elif r < 0.4:
            sc.op("C")
        elif r < 0.5:
            sc.op("CS", rnd.choice((8, 9, 10, 11, 12)))
        elif r < 0.6:
            sc.op("SU")
        elif r < 0.7:
            sc.op("RE")
        elif r < 0.8:
            sc.junk(rnd, rnd.sample(range(NTARGETS), 3))
        elif r < 0.9:
            for n in range(NCODES):
                sc.op("O", n, int(rnd.random() < 0.2))
            sc.op("EG")
        else:
            sc.op(rnd.choice(("RR", "SR", "RS")))
        sc.op("D")

    # -- the end -----------------------------------------------------------
    sc.tag("close")
    sc.op("S", 11)
    sc.op("X")
    sc.op("D")
    sc.op("X")
    sc.op("D")
    sc.op("I")
    sc.op("D")
    sc.op("X")
    sc.op("D")
    return sc.lines


# ================================================================ the model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        e.stub_bware()
        # InitCarEffects (0x0011db90) makes CarRenderMatrix the identity;
        # the image's is zeros.
        e.call(EIDENTITY, CAR_RENDER_MATRIX)
        e.stub(BMALLOC, self.s_malloc)
        e.stub(DELETE, self.s_free)
        e.stub(ONOFF, self.s_radial)
        e.stub(FI, self.s_fi)
        e.stub(FF, self.s_ff)
        e.call(SINIT)
        e.put32(CODES_PTR, CODES)
        self.saved = 0

    def emit(self, s):
        self.out.append(s)

    def cstr(self, a):
        b = bytearray()
        while self.e.mem[a]:
            b.append(self.e.mem[a])
            a += 1
        return b.decode("latin-1")

    def label(self, p):
        e = self.e
        p &= M32
        st = e.u32(P_STOMPER)
        if p == 0:
            return "null"
        if p == st or (self.saved and p == self.saved):
            return "stomper"
        if (st and p == e.u32(st + 4)) or (
                self.saved and p == e.u32(self.saved + 4)):
            return "stack"
        if p == OBJ2:
            return "obj2"
        if p == e.u32(OBJ2 + 4):
            return "obj2stack"
        return "?"

    def s_malloc(self, e):
        r = e.reg
        size = s32(r[4])
        self.emit("  malloc %d %s %d %d" % (size, self.cstr(r[5] & M32),
                                          s32(r[6]), s32(r[7])))
        p = e.alloc(size)
        e.mem[p:p + size] = bytes(size)
        return p

    def s_free(self, e):
        self.emit("  free %s" % self.label(e.reg[4]))

    def s_radial(self, e):
        on, v = s32(e.reg[4]), e.reg[5] & M32
        self.emit("  radial %d %08x" % (on, v))
        return v ^ 0x5a5a0000 ^ (on & M32)

    def s_fi(self, e):
        st, v = s32(e.reg[4]), e.reg[5] & M32
        self.emit("  fi %d %08x" % (st, v))
        return v ^ 0x0f0f0f0f ^ (st & M32)

    def s_ff(self, e):
        st, b = s32(e.reg[4]), e.fpr[12] & M32
        self.emit("  ff %d %08x" % (st, b))
        e.fpr[0] = b ^ 0x00400000 ^ ((st << 1) & M32)
        return None

    def hex(self, tag, a, n):
        b = self.e.read(a, n)
        self.emit("  %s%s" % (tag, "".join(
            ("" if i & 3 else " ") + "%02x" % b[i] for i in range(n))))

    def dump(self):
        e = self.e
        st = e.u32(P_STOMPER)
        if st == 0:
            self.emit("stomper null")
        else:
            self.emit("stomper en %d cur %d stack %s"
                      % (s32(e.u32(st)), s32(e.u32(st + 8)),
                         self.label(e.u32(st + 4))))
            if e.u32(st + 4):
                self.hex("stack", e.u32(st + 4), 64)
        self.emit("  targets" + "".join(" %08x" % e.u32(a) for a in TARGETS))

    def dump_list(self):
        self.hex("tgt", TGT, NTGT)
        self.hex("save", SAVE, 96)

    def dump_obj2(self):
        e = self.e
        self.emit("obj2 en %d cur %d stack %s"
                  % (s32(e.u32(OBJ2)), s32(e.u32(OBJ2 + 8)),
                     self.label(e.u32(OBJ2 + 4))))

    def op(self, ln):
        e = self.e
        t = ln.split(" ")
        c = t[0]
        st = e.u32(P_STOMPER)
        if c == "T":
            self.emit("[%s]" % ln[2:])
            return
        if c == "D":
            self.dump()
        elif c == "I":
            self.emit("init")
            e.call(INIT)
        elif c == "X":
            self.emit("close")
            e.call(CLOSE)
        elif c == "S":
            self.emit("set %d" % int(t[1]))
            e.call(S_SET, st, int(t[1]))
        elif c == "C":
            self.emit("clear")
            e.call(S_CLEAR, st)
        elif c == "CS":
            self.emit("clear set %d" % int(t[1]))
            e.call(S_CLEARSET, st, int(t[1]))
        elif c == "SU":
            self.emit("suspend")
            e.call(S_SUSPEND, st)
        elif c == "RE":
            self.emit("resume")
            e.call(S_RESUME, st)
        elif c == "RR":
            self.emit("reset eggs")
            e.call(RESET_EGGS)
        elif c == "SR":
            self.emit("suspend eggs")
            e.call(SUSPEND_EGGS)
        elif c == "RS":
            self.emit("resume eggs")
            e.call(RESUME_EGGS)
        elif c == "DR":
            self.emit("disable eggs")
            e.call(DISABLE_EGGS)
        elif c == "ER":
            self.emit("enable eggs")
            e.call(ENABLE_EGGS)
        elif c == "EG":
            self.emit("eggs from codes")
            e.call(FROM_CODES)
        elif c == "O":
            e.put32(CODES + CODE * int(t[1]) + 48, int(t[2]))
        elif c == "P":
            e.put32(TARGETS[int(t[1])], int(t[2], 16))
        elif c == "SF":
            u = int(t[1], 16)
            p = e.u32(st + 4)
            e.mem[p:p + 1024] = bytes((u + 5 * i) & 0xff for i in range(1024))
        elif c == "N":
            self.saved = st
            e.put32(P_STOMPER, 0)
        elif c == "NR":
            e.put32(P_STOMPER, self.saved)
            self.saved = 0
        elif c == "TW":
            a = [int(t[1]), int(t[2], 16), int(t[3], 16), int(t[4]),
                 int(t[5]), int(t[6])]
            for i, v in enumerate(a):
                e.put32(TWEAK + 4 * i, v)
        elif c == "W":
            fr = int(t[1])
            e.put32(WORLD_TIME_FRAMES, fr)
            for i in range(6):
                e.put32(Q + 4 * i, 0xdead0000 + i)
            for i in range(3):
                e.put32(POS + 4 * i, int(t[2 + i], 16))
            e.put32(POS + 12, 0)
            e.call(QUERY, Q, POS, limit=100000)
            self.emit("query %d%s" % (fr, "".join(
                " %08x" % e.u32(Q + 4 * i) for i in range(6))))
        elif c == "LE":
            k, ty, p, v = int(t[1]), int(t[2]), int(t[3]), int(t[4], 16)
            if ty in (INT8, INT16, INT32, FLOAT):
                ptr = TGT + p
            elif ty == FINT:
                ptr = FI
            elif ty == FFLOAT:
                ptr = FF
            elif ty == NESTED:
                ptr = LIST + 12 * p
            else:
                ptr = 0
            e.write(LIST + 12 * k, struct.pack("<III", ty & M32, ptr, v))
        elif c == "LF":
            u = int(t[1], 16)
            e.write(TGT, bytes((u + 7 * i) & 0xff for i in range(NTGT)))
            e.write(SAVE, bytes((u * 3 + 13 * i + 1) & 0xff
                                for i in range(NSAVE)))
        elif c in ("L1", "L0", "LS", "LC"):
            k, off = int(t[1]), int(t[2])
            fn = {"L1": E_SET, "L0": E_CLEAR, "LS": E_SETALL,
                  "LC": E_CLEARALL}[c]
            r = e.call(fn, LIST + 12 * k, SAVE + off) & M32
            self.emit("%s %d %d -> %d" % (c, k, off, r - SAVE))
            self.dump_list()
        elif c == "K":
            u = int(t[1], 16)
            e.put32(OBJ2, 0x5a5a0000 | u)
            e.put32(OBJ2 + 4, 1)
            e.put32(OBJ2 + 8, 0x5a5a0200 | u)
            self.dump_obj2()
        elif c == "KC":
            r = e.call(CTOR, OBJ2)
            self.emit("construct -> %s" % self.label(r))
            self.dump_obj2()
        elif c == "KX":
            self.emit("destroy %d" % int(t[1]))
            e.call(DTOR, OBJ2, int(t[1]))
        else:
            raise SystemExit("bad op %r" % ln)

    def run(self, lines):
        for ln in lines:
            self.op(ln)
        return self.out


# ================================================================ the facts

def facts():
    """The first values of the stomped globals in the files the harness
    does not link, against the image's."""
    bad = []
    e = retail_model.RetailEmu(ieee=True)
    want = {
        "eview.c": [("ForceBlackAndWhite", GP - 24048),
                    ("EnvPassAlphaA", GP - 25060),
                    ("EnvPassAlphaB", GP - 25056),
                    ("EnvPassAlphaC", GP - 25052),
                    ("EnvPassAlphaD", GP - 25048),
                    ("EnvPassAlphaFix", GP - 25044)],
        "carrender.c": [("ForceRenderDriver", GP - 23744)],
    }
    for f, names in want.items():
        text = (ROOT / SRC / f).read_bytes().decode("latin-1")
        for name, a in names:
            m = re.search(r"^int32_t +%s *(= *(-?\d+))?;" % name, text, re.M)
            if m is None:
                bad.append("%s: no %s" % (f, name))
                continue
            v = int(m.group(2) or 0) & M32
            if v != e.u32(a):
                bad.append("%s: %s = %d, the image %d"
                           % (f, name, s32(v), s32(e.u32(a))))
    # CarRenderMatrix: what InitCarEffects's eIdentity makes it.
    e.call(EIDENTITY, CAR_RENDER_MATRIX)
    text = (ROOT / SRC / "carrender.c").read_bytes().decode("latin-1")
    m = re.search(r"bMatrix4 CarRenderMatrix = \{(.*?)\};", text, re.S)
    got = [float(x) for x in re.findall(r"-?\d+\.\d+", m.group(1))] if m \
        else []
    img = [struct.unpack("<f", struct.pack("<I", e.u32(CAR_RENDER_MATRIX
                                                   + 4 * i)))[0]
           for i in range(16)]
    if got != img:
        bad.append("carrender.c: CarRenderMatrix %r, the image %r"
                   % (got, img))
    return bad


# ================================================================ the build


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


def build_flags():
    return list(hostbuild.FLAGS)


def build_harness(tmp, name="stomper_test"):
    return hostbuild.build(tmp, SOURCES, name=name, flags=build_flags())


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


def M(name, before, after, rel=SC):
    return (name, rel, before, after)


MUTATIONS = [
    # The lists.
    M("blur-player", "radialblur_on_off }, { .nData = 0 } },",
      "radialblur_on_off }, { .nData = 1 } },"),
    M("bw-value", "&ForceBlackAndWhite }, { .nData = 1 } },",
      "&ForceBlackAndWhite }, { .nData = 2 } },"),
    M("fog-value", "&WeatherHeavyFog }, { .nData = 1 } },",
      "&WeatherHeavyFog }, { .nData = 0 } },"),
    M("head-lod", "&OverrideAnimatedDriverLOD }, { .nData = 1 } },",
      "&OverrideAnimatedDriverLOD }, { .nData = 0 } },"),
    M("head-force", "&ForceRenderDriver },         { .nData = 1 } },",
      "&ForceRenderDriver },         { .nData = 0 } },"),
    M("head-bone", "{ .nData = 15 } },", "{ .nData = 14 } },"),
    M("head-scale", "&vBoneScale[1] },             { .fData = 5.5f } },",
      "&vBoneScale[1] },             { .fData = 5.0f } },"),
    M("head-scale-z", "&vBoneScale[2] },", "&vBoneScale[3] },"),
    M("head-type", "{ STOMP_INT32, { .pData = &nBoneScale },",
      "{ STOMP_INT16, { .pData = &nBoneScale },"),
    M("rc-x", "&CarRenderMatrix.v0.x }, { .fData = 0.5f } },",
      "&CarRenderMatrix.v0.x }, { .fData = 0.25f } },"),
    M("rc-y", "&CarRenderMatrix.v1.y },", "&CarRenderMatrix.v1.x },"),
    M("rc-z", "&CarRenderMatrix.v2.z },", "&CarRenderMatrix.v2.w },"),
    M("rc-head", "{ STOMP_NESTED, { .pNested = sBigHead },",
      "{ STOMP_END, { .pNested = sBigHead },"),
    M("chrome-a", "&EnvPassAlphaA },   { .nData = 2 } },",
      "&EnvPassAlphaA },   { .nData = 0 } },"),
    M("chrome-b", "&EnvPassAlphaB },   { .nData = 2 } },",
      "&EnvPassAlphaB },   { .nData = 1 } },"),
    M("chrome-c", "&EnvPassAlphaC },   { .nData = 1 } },",
      "&EnvPassAlphaC },   { .nData = 0 } },"),
    M("chrome-d", "&EnvPassAlphaD },   { .nData = 0 } },",
      "&EnvPassAlphaD },   { .nData = 1 } },"),
    M("chrome-fix", "{ .nData = 128 } },", "{ .nData = 64 } },"),
    M("table-blur", "    sRadialBlur," + NL + "    sBlackAndWhite,",
      "    sBlackAndWhite," + NL + "    sRadialBlur,"),
    M("table-fog", "    sHeavyFog," + NL + "    sCutiePetootie,",
      "    sCutiePetootie," + NL + "    sHeavyFog,"),
    M("table-chrome", "    sChrome," + NL + "};", "    sNotPorted," + NL + "};"),
    M("bone-first", "int32_t nBoneScale = -1;", "int32_t nBoneScale;"),

    # The entries.
    M("int8-save", "        memcpy(save, s->u.pData, 1);" + NL
      + "        memcpy(s->u.pData, &v, 1);",
      "        memcpy(save, s->u.pData, 4);" + NL
      + "        memcpy(s->u.pData, &v, 1);"),
    M("int8-poke", "memcpy(s->u.pData, &v, 1);", "memcpy(s->u.pData, &v, 2);"),
    M("int8-step", "memcpy(s->u.pData, &v, 1);" + NL + "        return save + 4;",
      "memcpy(s->u.pData, &v, 1);" + NL + "        return save + 1;"),
    M("int16-save", "        memcpy(save, s->u.pData, 2);" + NL
      + "        memcpy(s->u.pData, &v, 2);",
      "        memcpy(save, s->u.pData, 4);" + NL
      + "        memcpy(s->u.pData, &v, 2);"),
    M("int16-value", "uint16_t v = (uint16_t)s->v.nData;",
      "uint16_t v = (uint16_t)(s->v.nData >> 16);"),
    M("int32-save", "        memcpy(save, s->u.pData, 4);" + NL
      + "        memcpy(s->u.pData, &s->v.nData, 4);",
      "        memcpy(s->u.pData, &s->v.nData, 4);"),
    M("float-order", "        memcpy(save, s->u.pData, 4);" + NL
      + "        memcpy(s->u.pData, &s->v.fData, 4);",
      "        memcpy(s->u.pData, &s->v.fData, 4);" + NL
      + "        memcpy(save, s->u.pData, 4);"),
    M("fint-set", "int32_t v = s->u.pFuncInt(1, s->v.nData);",
      "int32_t v = s->u.pFuncInt(0, s->v.nData);"),
    M("fint-keep", "int32_t v = s->u.pFuncInt(1, s->v.nData);",
      "int32_t v = (s->u.pFuncInt(1, s->v.nData), s->v.nData);"),
    M("ffloat-set", "float f = s->u.pFuncFloat(1, s->v.fData);",
      "float f = s->u.pFuncFloat(1, 0.0f);"),
    M("nested-set", "return stompentry_set_all(s->u.pNested, save);",
      "return stompentry_set(s->u.pNested, save);"),
    M("set-default", "    default:" + NL + "        return save;" + NL + "    }"
      + NL + "}" + NL + NL + "uint8_t *stompentry_clear(",
      "    default:" + NL + "        return save + 4;" + NL + "    }"
      + NL + "}" + NL + NL + "uint8_t *stompentry_clear("),
    M("clear-int8", "        memcpy(s->u.pData, save, 1);" + NL
      + "        return save + 4;",
      "        memcpy(s->u.pData, save, 2);" + NL
      + "        return save + 4;"),
    M("clear-int16", "        memcpy(s->u.pData, save, 2);" + NL
      + "        return save + 4;",
      "        memcpy(s->u.pData, save, 4);" + NL
      + "        return save + 4;"),
    M("clear-int32-gone", "    case STOMP_INT32:" + NL + "    case STOMP_FLOAT:"
      + NL + "        memcpy(s->u.pData, save, 4);",
      "    case STOMP_INT32:" + NL + "    case STOMP_FLOAT:"
      + NL + "        (void)0;"),
    M("clear-fint", "        s->u.pFuncInt(0, v);",
      "        s->u.pFuncInt(1, v);"),
    M("clear-fint-value", "        memcpy(&v, save, 4);" + NL
      + "        s->u.pFuncInt(0, v);",
      "        memcpy(&v, save, 4);" + NL
      + "        s->u.pFuncInt(0, s->v.nData);"),
    M("clear-ffloat", "        s->u.pFuncFloat(0, f);",
      "        s->u.pFuncFloat(0, s->v.fData);"),
    M("clear-nested", "return stompentry_clear_all(s->u.pNested, save);",
      "return stompentry_set_all(s->u.pNested, save);"),
    M("clear-default", "    default:" + NL + "        return save;" + NL + "    }"
      + NL + "}" + NL + NL + "// Both walk",
      "    default:" + NL + "        return save + 4;" + NL + "    }"
      + NL + "}" + NL + NL + "// Both walk"),
    M("setall-end", "    for (; s->nType != STOMP_END; s++)" + NL
      + "        save = stompentry_set(s, save);",
      "    for (; s->nType < STOMP_END; s++)" + NL
      + "        save = stompentry_set(s, save);"),
    M("setall-keep", "        save = stompentry_set(s, save);",
      "        stompentry_set(s, save);"),
    M("clearall-keep", "        save = stompentry_clear(s, save);",
      "        stompentry_clear(s, save);"),
    M("clearall-skip", "    for (; s->nType != STOMP_END; s++)" + NL
      + "        save = stompentry_clear(s, save);",
      "    for (s++; s->nType != STOMP_END; s++)" + NL
      + "        save = stompentry_clear(s, save);"),

    # The Stomper.
    M("ctor-enabled", "s->bEnabled = 1;", "s->bEnabled = 0;"),
    M("ctor-size", "bMalloc(STOMPER_STACK_SIZE, ", "bMalloc(512, "),
    M("ctor-name", "\"Stomper Stack\", 0, 16", "\"Stomper\", 0, 16"),
    M("ctor-pool", "\"Stomper Stack\", 0, 16", "\"Stomper Stack\", 0, 0"),
    M("ctor-current", "    s->nCurrent = STOMPER_NONE;" + NL + "    return s;",
      "    s->nCurrent = 8;" + NL + "    return s;"),
    M("dtor-stack", "    bFree(s->pStack);" + NL + "    if (flags & 1)",
      "    if (flags & 1)"),
    M("dtor-flag", "if (flags & 1)", "if (flags & 2)"),
    M("clear-range", "if ((uint32_t)(s->nCurrent - 1) < STOMPER_NUM - 1)",
      "if ((uint32_t)(s->nCurrent - 1) < STOMPER_NUM - 2)"),
    M("clear-signed", "if ((uint32_t)(s->nCurrent - 1) < STOMPER_NUM - 1)",
      "if (s->nCurrent >= 0 && s->nCurrent < STOMPER_NUM)"),
    M("clear-keep", "    s->nCurrent = STOMPER_NONE;" + NL + "}",
      "}"),
    M("set-range", "if ((uint32_t)(e - 1) < STOMPER_NUM - 1) {",
      "if ((uint32_t)(e - 1) < STOMPER_NUM - 2) {"),
    M("set-zero", "if ((uint32_t)(e - 1) < STOMPER_NUM - 1) {",
      "if ((uint32_t)e < STOMPER_NUM - 1) {"),
    M("set-clears", "    if ((uint32_t)(e - 1) < STOMPER_NUM - 1) {" + NL
      + "        stompentry_set_all",
      "    if ((uint32_t)(e - 1) < STOMPER_NUM - 1) {" + NL
      + "        stomper_clear(s);" + NL + "        stompentry_set_all"),
    M("set-current", "        s->nCurrent = e;", "        s->nCurrent = 0;"),
    M("clear-set-order", "    stomper_clear(s);" + NL + "    stomper_set(s, e);",
      "    stomper_set(s, e);"),
    M("suspend-keep", "    stomper_clear(s);" + NL + "    s->nCurrent = e;",
      "    stomper_clear(s);"),
    M("resume", "stomper_set(s, s->nCurrent);",
      "stomper_set(s, STOMPER_NONE);"),
    M("init-name", "\"Stomper\", 0, 16));", "\"Stomper Stack\", 0, 16));"),
    M("close-flags", "stomper_destroy(pStomper, 3);",
      "stomper_destroy(pStomper, 2);"),
    M("close-null", "        stomper_destroy(pStomper, 3);" + NL
      + "    pStomper = NULL;",
      "        stomper_destroy(pStomper, 3);"),

    # The eggs.
    M("reset-gone", "    if (pStomper != NULL)" + NL
      + "        stomper_clear(pStomper);" + NL + "}" + NL + NL
      + "void SetRenderEggFromEasterEggs",
      "}" + NL + NL + "void SetRenderEggFromEasterEggs"),
    M("codes-0", "if (c[0].On)", "if (c[5].On)"),
    M("codes-0-egg", "stomper_set(pStomper, STOMPER_MOTION_BLUR);",
      "stomper_set(pStomper, STOMPER_HEAVY_FOG);"),
    M("codes-1", "else if (c[1].On)", "else if (c[0].On)"),
    M("codes-2", "else if (c[2].On)", "else if (c[6].On)"),
    M("codes-3-egg", "stomper_set(pStomper, STOMPER_RC_CAR);",
      "stomper_set(pStomper, STOMPER_CHROME);"),
    M("codes-4", "else if (c[4].On)", "else if (c[7].On)"),
    M("codes-4-egg", "    else if (c[4].On)" + NL
      + "        stomper_set(pStomper, STOMPER_BLACK_AND_WHITE);",
      "    else if (c[4].On)" + NL
      + "        stomper_set(pStomper, STOMPER_MOTION_BLUR);"),
    M("codes-8", "else if (c[8].On)", "else if (c[9].On)"),
    M("codes-order", "    if (c[0].On)" + NL
      + "        stomper_set(pStomper, STOMPER_MOTION_BLUR);" + NL
      + "    else if (c[1].On)" + NL
      + "        stomper_set(pStomper, STOMPER_BLACK_AND_WHITE);",
      "    if (c[1].On)" + NL
      + "        stomper_set(pStomper, STOMPER_BLACK_AND_WHITE);" + NL
      + "    else if (c[0].On)" + NL
      + "        stomper_set(pStomper, STOMPER_MOTION_BLUR);"),
    M("codes-null", "    if (pStomper == NULL)" + NL + "        return;" + NL
      + "    c = TheEasterEggs.Codes;",
      "    c = TheEasterEggs.Codes;"),
    M("suspend-eggs", "        stomper_suspend(pStomper);",
      "        stomper_clear(pStomper);"),
    M("resume-eggs", "        stomper_resume(pStomper);",
      "        stomper_set(pStomper, STOMPER_HEAVY_FOG);"),
    M("disable-clear", "        stomper_clear(s);" + NL
      + "        s->bEnabled = 0;",
      "        s->bEnabled = 0;"),
    M("disable-flag", "        s->bEnabled = 0;", "        s->bEnabled = 2;"),
    M("enable", "pStomper->bEnabled = 1;", "pStomper->bEnabled = 0;"),

    # WeatherManQuery's heavy fog.
    M("fog-test", "    if (WeatherHeavyFog) {", "    if (0) {", WMC),
    M("fog-fog", "q->Fog = 0.957753f;", "q->Fog = 0.957754f;", WMC),
    M("fog-colour", "q->FogColour = 0x00887062;", "q->FogColour = 0x00627088;",
      WMC),
    M("fog-s1", "bSinF((float)WorldTimeFrames * 0.02f);",
      "bSinF((float)WorldTimeFrames * 0.021f);", WMC),
    M("fog-s2", "bSinF((float)WorldTimeFrames * 0.001f);",
      "bSinF((float)WorldTimeFrames * 0.01f);", WMC),
    M("fog-start", "s1 * 200.0f + -1000.0f", "s1 * 200.0f + -999.0f", WMC),
    M("fog-terms", "s2 * 150.0f + s3 * 100.0f", "s3 * 150.0f + s2 * 100.0f",
      WMC),
    M("fog-order", "s1 * 200.0f + -1000.0f + s2 * 150.0f + s3 * 100.0f",
      "s1 * 200.0f + (-1000.0f + (s2 * 150.0f + s3 * 100.0f))", WMC),
    M("fog-return", "        q->FogStart  = s1 * 200.0f + -1000.0f"
      " + s2 * 150.0f + s3 * 100.0f;" + NL + "        return;",
      "        q->FogStart  = s1 * 200.0f + -1000.0f"
      " + s2 * 150.0f + s3 * 100.0f;", WMC),
    M("fog-clears", "        q->Fog = 0.957753f;",
      "        memset(q, 0, sizeof *q);" + NL
      + "        q->Fog = 0.957753f;", WMC),
]

EQUIVALENT = {
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
    scp.write_text(NL.join(sc) + NL)
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
        todo, SOURCES, "stomper_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs, flags=build_flags())
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

    bad = facts()
    for b in bad:
        print("fact: " + b)

    sc = script()
    lines = model_cached(sc)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = Path(tmp) / "script.txt"
        scp.write_text(NL.join(sc) + NL)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(lines, harness)
    print("%d ops, %d lines, %d differ, %d facts wrong"
          % (len(sc), len(harness), n, len(bad)))
    sys.exit(1 if (n or rc or bad) else 0)


if __name__ == "__main__":
    main()
