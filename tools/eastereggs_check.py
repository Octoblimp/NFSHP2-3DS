"""Cross-check 3DS Files/source/eastereggs.c against the retail image's
own code.

TheEasterEggs (0x0031d7e8) is the main menu's code reader: retail-only
and unnamed, so every name is the port's. The oracle is SLES_507.31 run in
tools/mipsemu.py:

- the constructor (0x0024f420), Start (0x0024f488) and Stop (0x0024f610),
  with AddJoyHandler and RemoveJoyHandler stubbed to log;
- a press, through the handler Start registers (0x0024fa88, on to
  0x0024f748), and the ring's reset (0x0024f8f0);
- the clear of the codes not kept (0x0024f700) and of a group
  (0x0024f9f8);
- the lookups: by type and parameter (0x0024f9a0), a car's (0x0024f8f8),
  a track's (0x0024f930) and code n's On (0x0024fa70);
- the five small ones: 0x0024faa8, 0x0024fab8, 0x0024fac0, 0x0024fac8
  and 0x0024fad8.

The script runs both on the disc's table, which the port copies into
TheEasterEggCodes (eastereggs_check dumps the whole of it from each side),
and on a table of its own, poked code by code the same on both sides: two
codes with one sequence, groups, the types, no codes at all.

The points worth pinning:

**A full ring empties instead of taking the press.** Only a Count poked
to 8 or more gets there: the eighth press either matches, which empties
the ring, or drops the oldest, which leaves seven.

**Head is masked where it is used and when it moves,** so a Head poked
past 7 reads slot (Head + i) & 7 and steps to (Head + 1) & 7.

**The first code that matches wins,** and its group goes off before it
comes on, so a group of one stays on.

    python tools/eastereggs_check.py
    python tools/eastereggs_check.py --mutate [--only a,b] [--jobs N]
    python tools/eastereggs_check.py --dump PREFIX
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

HARNESS = "tools/src/eastereggs_test.c"
EC = "3DS Files/source/eastereggs.c"
EH = "3DS Files/source/eastereggs.h"
SOURCES = [HARNESS, EC]

HARNESS_TIMEOUT = 60

# ================================================================ the image

CTOR = 0x0024f420
START = 0x0024f488
STOP = 0x0024f610
CLRTMP = 0x0024f700
RESET = 0x0024f8f0
CAR = 0x0024f8f8
TRACK = 0x0024f930
ISON = 0x0024f9a0
CLRGRP = 0x0024f9f8
EGG = 0x0024fa70
HANDLER = 0x0024fa88
TAKE = 0x0024faa8
JUST = 0x0024fab8
ISACT = 0x0024fac0
ENABLE = 0x0024fac8
DISABLE = 0x0024fad8
ADDJOY = 0x00154140
REMJOY = 0x001541e8

TAB = 0x0031d828
NTAB = 78
CODE = 56
OBJ = 0x01E00000
OBJ_SIZE = 64
NOBJ = 2
CUST = 0x01E00400
NCUST = 16

L1, L2, R1, R2, DL, DR, SQ, TR = range(133, 141)
BUTTONS = list(range(133, 149))

# The object's fields as the script pokes them: 0 Active, 1 JustEntered,
# 2 LanguageID, 3 Codes (0 the disc's table, 1 the script's, 2 none),
# 4 NumCodes, 5..12 the ring, 13 Count, 14 Head, 15 the vtable.
FOFF = {0: 0, 1: 4, 2: 8, 3: 12, 4: 16, 13: 52, 14: 56, 15: 60}
for _i in range(8):
    FOFF[5 + _i] = 20 + 4 * _i


def disc_codes():
    """The 78 codes' eight presses, out of the ELF."""
    b = (ROOT / "PS2 Files" / "Full Game" / "SLES_507.31").read_bytes()
    phoff = struct.unpack_from("<I", b, 0x1c)[0]
    phnum = struct.unpack_from("<H", b, 0x2c)[0]
    phent = struct.unpack_from("<H", b, 0x2a)[0]
    for i in range(phnum):
        t, off, va, pa, fsz, msz = struct.unpack_from(
            "<6I", b, phoff + i * phent)
        if t == 1 and va <= TAB < va + fsz:
            base = off + TAB - va
            return [list(struct.unpack_from("<8i", b, base + CODE * n))
                    for n in range(NTAB)]
    raise SystemExit("no table at %08x" % TAB)


# ============================================================== the script

class Script(object):
    def __init__(self):
        self.lines = []

    def op(self, *a):
        self.lines.append(" ".join(str(x) for x in a))

    def tag(self, s):
        self.lines.append("T " + s)

    def press(self, k, ev, port=0, value=1, dump=True):
        self.op("B", k, port, ev, value)
        if dump:
            self.op("D", k)

    def presses(self, k, evs, dump=True):
        for ev in evs:
            self.press(k, ev, dump=dump)

    def junk(self, k, seed):
        for f in range(16):
            if f == 3:
                self.op("P", k, 3, 2)
            else:
                self.op("P", k, f, (0x5a000000 | seed << 8 | f))

    def cust(self, i, buttons, typ, param, group, lang, on, kept):
        for j, ev in enumerate(buttons):
            self.op("C", 1, i, j, ev)
        for j, v in enumerate((typ, param, group, lang, on, kept)):
            self.op("C", 1, i, 8 + j, v)


def script():
    sc = Script()
    rnd = random.Random(0xe66)
    codes = disc_codes()

    # -- the constructor --------------------------------------------------
    sc.tag("ctor")
    sc.junk(0, 1)
    sc.op("D", 0)
    sc.op("N", 0)
    sc.op("D", 0)
    sc.op("F", 0, NTAB)
    sc.op("JE", 0)
    sc.op("IA", 0)

    # A press before Start: the reader is off.
    sc.tag("before start")
    sc.press(0, L1)

    sc.tag("start")
    sc.op("P", 0, 1, 7)
    sc.op("P", 0, 2, 99)
    sc.op("P", 0, 13, 5)
    sc.op("S", 0)
    sc.op("D", 0)
    sc.op("IA", 0)

    # -- a code, press by press ------------------------------------------
    sc.tag("mclaren")
    sc.presses(0, codes[9])
    sc.op("JE", 0)
    sc.op("TK", 0)
    sc.op("JE", 0)
    sc.op("TK", 0)
    sc.op("D", 0)
    for car, cop in ((7, 0), (7, 1), (8, 0), (0, 0)):
        sc.op("CA", 0, car, cop)
    sc.op("I", 0, 1, 7)
    sc.op("I", 0, 2, 7)
    sc.op("E", 0, 9)
    sc.op("O", 0, NTAB)

    # Three stray presses first: the ring fills on the fifth of the code
    # and slides one at a time until the code is all in it.
    sc.tag("slide")
    sc.presses(0, [SQ, 141, TR] + codes[18])
    sc.op("TK", 0)
    sc.op("CA", 0, 23, 0)

    # A code with its last press wrong, then with its first wrong.
    sc.tag("one wrong")
    sc.op("CA", 0, 8, 0)
    sc.presses(0, codes[10][:7] + [SQ])
    sc.op("CA", 0, 8, 0)
    sc.op("R", 0)
    sc.presses(0, [L2] + codes[10][1:])
    sc.op("CA", 0, 8, 0)

    # A code's tail, then the whole of another: the ring keeps sliding.
    sc.tag("tail")
    sc.presses(0, codes[25][3:] + codes[40])
    sc.op("TK", 0)
    sc.op("O", 0, NTAB)

    # -- the groups -------------------------------------------------------
    sc.tag("group")
    for n in (0, 1, 2, 3, 4, 0, 8):
        sc.presses(0, codes[n], dump=False)
        sc.op("D", 0)
        sc.op("O", 0, NTAB)
        sc.op("TK", 0)
    sc.op("CG", 0, 1)
    sc.op("O", 0, NTAB)
    sc.op("CG", 0, 0)
    sc.op("O", 0, NTAB)
    for n in range(NTAB):
        sc.op("E", 0, n)

    # -- the cars and the tracks -----------------------------------------
    sc.tag("cars")
    for n in (46, 47, 48, 51, 52, 54):
        sc.presses(0, codes[n], dump=False)
        sc.op("TK", 0)
    for car in range(0, 50):
        sc.op("CA", 0, car, 0)
        sc.op("CA", 0, car, 1)

    sc.tag("tracks")
    for n in (55, 56, 60, 61, 69, 77):
        sc.presses(0, codes[n], dump=False)
        sc.op("TK", 0)
    for track in (11, 12, 13, 21, 22, 23, 31, 32, 33, 41, 42, 43, 61, 62,
                  63, 0, 5, 99):
        sc.op("TR", 0, track, 0)
        sc.op("TR", 0, track, 1)
    sc.op("TR", 0, 12, 7)
    sc.op("CA", 0, 33, -1)
    for typ in range(-1, 6):
        for param in (0, 4, 5, 11, 12, 33, 63):
            sc.op("I", 0, typ, param)

    # -- after a race ---------------------------------------------------
    sc.tag("clear temporary")
    sc.op("O", 0, NTAB)
    sc.op("CT", 0)
    sc.op("O", 0, NTAB)
    sc.op("D", 0)

    # -- the switch --------------------------------------------------------
    sc.tag("inactive")
    sc.presses(0, [L1, L2, R1])
    sc.op("DI", 0)
    sc.op("IA", 0)
    sc.presses(0, codes[6])
    sc.op("EN", 0)
    sc.op("IA", 0)
    sc.presses(0, codes[6])
    sc.op("TK", 0)
    sc.op("P", 0, 0, -3)
    sc.press(0, L2)
    sc.op("P", 0, 0, 1)

    # -- the ring, poked --------------------------------------------------
    sc.tag("full")
    sc.op("P", 0, 13, 8)
    sc.press(0, R2)
    sc.op("P", 0, 13, 9)
    sc.press(0, R2)
    sc.op("P", 0, 13, 0xffffffff)
    sc.press(0, R2)
    sc.op("P", 0, 13, 7)
    sc.press(0, R2)
    sc.op("P", 0, 13, 6)
    sc.press(0, R2)
    sc.press(0, R2)

    sc.tag("head")
    for head in (7, 13, 0x7fffffff, 0xfffffffe):
        sc.op("R", 0)
        sc.op("P", 0, 14, head)
        sc.op("D", 0)
        sc.presses(0, codes[7])
        sc.op("TK", 0)
        sc.op("P", 0, 14, head)
        sc.presses(0, [L1] * 9)
    # Seven in the ring, poked to a code but for its last: one press.
    sc.op("R", 0)
    sc.op("P", 0, 14, 3)
    for i in range(7):
        sc.op("P", 0, 5 + ((3 + i) & 7), codes[30][i])
    sc.op("P", 0, 13, 7)
    sc.press(0, codes[30][7])
    sc.op("TK", 0)
    # The same, one off.
    sc.op("P", 0, 14, 5)
    for i in range(7):
        sc.op("P", 0, 5 + ((5 + i) & 7), codes[30][i])
    sc.op("P", 0, 5 + ((5 + 3) & 7), SQ)
    sc.op("P", 0, 13, 7)
    sc.press(0, codes[30][7])

    # The ports and values are not read.
    sc.tag("ports")
    sc.op("R", 0)
    for i, ev in enumerate(codes[44]):
        sc.press(0, ev, port=i & 1, value=(i * 37) & 0xff, dump=False)
    sc.op("D", 0)
    sc.op("TK", 0)

    # -- the script's own table ------------------------------------------
    sc.tag("custom")
    seq = [L1, L2, R1, R2, DL, DR, SQ, TR]
    sc.cust(0, [R2] * 8, 0, 3, 2, 1000, 0, 0)
    sc.cust(1, seq, 1, 7, 2, 1001, 0, 1)
    sc.cust(2, seq, 2, 7, 0, 1002, 0, 1)       # the same presses: unreached
    sc.cust(3, [141, 142, 143, 144, 145, 146, 147, 148], 3, 5, 3, 1003, 1, 0)
    sc.cust(4, [TR, SQ, DR, DL, R2, R1, L2, L1], 4, 5, 3, 1004, 0, 1)
    sc.cust(5, [0] * 8, 0, 9, 0, 1005, 1, 1)
    sc.cust(6, [L1] * 8, 7, -2, -1, -5, 5, 2)
    for i in range(7, NCUST):
        sc.cust(i, [rnd.choice(BUTTONS) for _ in range(8)],
                rnd.randrange(5), rnd.randrange(10), rnd.randrange(3),
                2000 + i, rnd.randrange(2), rnd.randrange(2))
    sc.op("F", 1, NCUST)
    sc.op("P", 0, 3, 1)
    sc.op("P", 0, 4, 7)
    sc.op("R", 0)
    sc.op("D", 0)
    sc.presses(0, seq)
    sc.op("O", 1, NCUST)
    sc.op("TK", 0)
    sc.op("I", 0, 1, 7)
    sc.op("I", 0, 2, 7)
    sc.op("CA", 0, 7, 0)
    sc.op("CA", 0, 7, 1)
    sc.presses(0, [R2] * 8)
    sc.op("O", 1, NCUST)
    sc.presses(0, [141, 142, 143, 144, 145, 146, 147, 148])
    sc.op("O", 1, NCUST)
    sc.presses(0, [TR, SQ, DR, DL, R2, R1, L2, L1])
    sc.op("O", 1, NCUST)
    sc.op("TR", 0, 5, 0)
    sc.op("TR", 0, 5, 1)
    sc.presses(0, [L1] * 8)
    sc.op("O", 1, NCUST)
    sc.op("CG", 0, 3)
    sc.op("O", 1, NCUST)
    sc.op("CG", 0, -1)
    sc.op("O", 1, NCUST)
    sc.op("CT", 0)
    sc.op("O", 1, NCUST)
    for n in range(7):
        sc.op("E", 0, n)
    # Past NumCodes nothing is looked at.
    sc.op("P", 0, 4, 3)
    sc.cust(5, [L1] * 8, 0, 9, 0, 1005, 1, 1)
    sc.presses(0, [L1] * 8)
    sc.op("I", 0, 0, 9)
    sc.op("CT", 0)
    sc.op("CG", 0, 2)
    sc.op("O", 1, NCUST)
    sc.op("P", 0, 4, NCUST)
    sc.op("I", 0, 0, 9)
    sc.op("C", 1, 6, 12, 1)
    sc.op("CT", 0)
    sc.op("O", 1, NCUST)

    # No codes: every eighth press slides.
    sc.tag("no codes")
    sc.op("P", 0, 4, 0)
    sc.op("R", 0)
    sc.presses(0, [L1, L2, R1, R2, DL, DR, SQ, TR, L1, L2])
    sc.op("I", 0, 1, 7)
    sc.op("CT", 0)
    sc.op("CG", 0, 2)
    sc.op("O", 1, NCUST)

    # -- a long run of presses on the disc's table -----------------------
    sc.tag("random")
    sc.op("P", 0, 3, 0)
    sc.op("P", 0, 4, NTAB)
    sc.op("R", 0)
    for i in range(60):
        if rnd.random() < 0.3:
            n = rnd.randrange(NTAB)
            sc.presses(0, codes[n][:rnd.randrange(9)] or [TR], dump=False)
        else:
            sc.presses(0, [rnd.choice(BUTTONS)
                           for _ in range(rnd.randrange(1, 12))], dump=False)
        sc.op("D", 0)
        if rnd.random() < 0.3:
            sc.op("TK", 0)
    for n in rnd.sample(range(NTAB), 30):
        sc.presses(0, [rnd.choice(BUTTONS) for _ in range(rnd.randrange(4))]
                   + codes[n], dump=False)
        sc.op("D", 0)
    sc.op("O", 0, NTAB)

    # -- the end --------------------------------------------------------
    sc.tag("stop")
    sc.op("P", 0, 1, 5)
    sc.op("P", 0, 2, 77)
    sc.op("P", 0, 13, 3)
    sc.op("X", 0)
    sc.op("D", 0)
    sc.presses(0, codes[11])
    sc.op("JE", 0)

    # A second object, constructed over junk, on the same table.
    sc.tag("second")
    sc.junk(1, 2)
    sc.op("N", 1)
    sc.op("D", 1)
    sc.op("S", 1)
    sc.presses(1, codes[12])
    sc.op("TK", 1)
    sc.op("E", 1, 12)
    sc.op("E", 0, 12)
    sc.op("CT", 1)
    sc.op("O", 0, NTAB)
    sc.op("X", 1)
    sc.op("F", 0, NTAB)
    return sc.lines


# ================================================================ the model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu()
        e.stub(ADDJOY, self.s_add)
        e.stub(REMJOY, self.s_remove)

    def emit(self, s):
        self.out.append(s)

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        for k in range(NOBJ):
            if a == OBJ + OBJ_SIZE * k:
                return "e%d" % k
        if a == TAB:
            return "tab"
        if a == CUST:
            return "cust"
        return "?"

    def s_add(self, em):
        r = em.reg
        self.emit("  add %d %d %s %s"
                  % (s32(r[4]), s32(r[5]),
                     "handler" if (r[6] & M32) == HANDLER else "?",
                     self.label(r[7])))

    def s_remove(self, em):
        self.emit("  remove %d %d" % (s32(em.reg[4]), s32(em.reg[5])))

    def table(self, t):
        return CUST if t else TAB

    def dump(self, k):
        e = self.e
        p = OBJ + OBJ_SIZE * k
        w = [e.u32(p + 4 * i) for i in range(16)]
        self.emit("e%d act %d just %d lang %d codes %s n %d count %d head %d "
                  "vptr %08x ring %s"
                  % (k, s32(w[0]), s32(w[1]), s32(w[2]), self.label(w[3]),
                     w[4], w[13], w[14], w[15],
                     " ".join("%d" % s32(x) for x in w[5:13])))

    def dump_on(self, t, n):
        b = self.table(t)
        self.emit("on %s %s" % ("cust" if t else "tab", ",".join(
            "%d" % s32(self.e.u32(b + CODE * i + 48)) for i in range(n))))

    def dump_codes(self, t, n):
        b = self.table(t)
        for i in range(n):
            w = [s32(self.e.u32(b + CODE * i + 4 * j)) for j in range(14)]
            self.emit("code %s %d %s | %s"
                      % ("cust" if t else "tab", i,
                         " ".join("%d" % x for x in w[:8]),
                         " ".join("%d" % x for x in w[8:])))

    def op(self, ln):
        e = self.e
        t = ln.split(" ")
        c = t[0]
        if c == "T":
            self.emit("[%s]" % ln[2:])
            return
        a = [int(x, 0) for x in t[1:]]
        obj = OBJ + OBJ_SIZE * a[0] if a else 0
        if c == "N":
            r = e.call(CTOR, obj)
            self.emit("ctor e%d -> %s" % (a[0], self.label(r)))
        elif c == "S":
            self.emit("start e%d" % a[0])
            e.call(START, obj)
        elif c == "X":
            self.emit("stop e%d" % a[0])
            e.call(STOP, obj)
        elif c == "B":
            self.emit("press e%d %d %d %d" % tuple(a[:4]))
            e.call(HANDLER, a[1], a[2], a[3], obj)
        elif c == "R":
            self.emit("reset e%d" % a[0])
            e.call(RESET, obj)
        elif c == "D":
            self.dump(a[0])
        elif c == "O":
            self.dump_on(a[0], a[1])
        elif c == "F":
            self.dump_codes(a[0], a[1])
        elif c == "P":
            v = a[2]
            if a[1] == 3:
                v = {0: TAB, 1: CUST}.get(v, 0)
            e.put32(obj + FOFF[a[1]], v)
        elif c == "C":
            e.put32(self.table(a[0]) + CODE * a[1] + 4 * a[2], a[3])
        elif c == "CT":
            self.emit("clear temporary e%d" % a[0])
            e.call(CLRTMP, obj)
        elif c == "CG":
            self.emit("clear group e%d %d" % (a[0], a[1]))
            e.call(CLRGRP, obj, a[1])
        elif c == "I":
            r = e.call(ISON, obj, a[1], a[2])
            self.emit("is_on e%d %d %d -> %d" % (a[0], a[1], a[2], r))
        elif c == "CA":
            r = e.call(CAR, obj, a[1], a[2])
            self.emit("car e%d %d %d -> %d" % (a[0], a[1], a[2], r))
        elif c == "TR":
            r = e.call(TRACK, obj, a[1], a[2])
            self.emit("track e%d %d %d -> %d" % (a[0], a[1], a[2], r))
        elif c == "E":
            r = e.call(EGG, obj, a[1])
            self.emit("egg e%d %d -> %d" % (a[0], a[1], r))
        elif c == "TK":
            r = e.call(TAKE, obj)
            self.emit("take e%d -> %d" % (a[0], r))
        elif c == "JE":
            r = e.call(JUST, obj)
            self.emit("just e%d -> %d" % (a[0], r))
        elif c == "IA":
            r = e.call(ISACT, obj)
            self.emit("active e%d -> %d" % (a[0], r))
        elif c == "EN":
            self.emit("enable e%d" % a[0])
            e.call(ENABLE, obj)
        elif c == "DI":
            self.emit("disable e%d" % a[0])
            e.call(DISABLE, obj)
        else:
            raise SystemExit("bad op %r" % ln)

    def run(self, lines):
        for ln in lines:
            self.op(ln)
        return self.out


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


def build_harness(tmp, name="eastereggs_test"):
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


def M(name, before, after, rel=EC):
    return (name, rel, before, after)


MUTATIONS = [
    # The table.
    M("tab-button", "{ { TR, L1, TR, L1, R1, DL, R1, DL }, T_CAR, 7,",
      "{ { TR, L1, TR, L1, R1, DL, R1, DR }, T_CAR, 7,"),
    M("tab-none", "{ { NO, NO, NO, NO, NO, NO, NO, NO }",
      "{ { L1, NO, NO, NO, NO, NO, NO, NO }"),
    M("tab-type", "T_COP_CAR, 33, 0, 990007", "T_CAR, 33, 0, 990007"),
    M("tab-param", "T_TRACK, 12, 0, 50010", "T_TRACK, 13, 0, 50010"),
    M("tab-group", "T_EGG, 8, 0, 990125", "T_EGG, 8, 1, 990125"),
    M("tab-lang", "41104, 0, 1 }", "41105, 0, 1 }"),
    M("tab-on", "990121, 0, 0 }", "990121, 1, 0 }"),
    M("tab-kept", "990123, 0, 1 }", "990123, 0, 0 }"),

    # The constructor.
    M("ctor-vptr", "e->vptr        = EASTEREGGS_VTABLE;",
      "e->vptr        = EASTEREGGS_VTABLE + 4;"),
    M("ctor-codes", "e->Codes       = TheEasterEggCodes;",
      "e->Codes       = TheEasterEggCodes + 1;"),
    M("ctor-num", "e->NumCodes    = EASTEREGGS_NUM_CODES;",
      "e->NumCodes    = EASTEREGGS_NUM_CODES - 1;"),
    M("ctor-active", "e->Active      = 0;" + NL + "    e->JustEntered = 0;"
      + NL + "    e->LanguageID  = 0;" + NL + "    e->Count",
      "e->Active      = 1;" + NL + "    e->JustEntered = 0;"
      + NL + "    e->LanguageID  = 0;" + NL + "    e->Count"),
    M("ctor-just", "e->JustEntered = 0;" + NL + "    e->LanguageID  = 0;"
      + NL + "    e->Count       = 0;",
      "e->JustEntered = 1;" + NL + "    e->LanguageID  = 0;"
      + NL + "    e->Count       = 0;"),
    M("ctor-lang", "e->LanguageID  = 0;" + NL + "    e->Count       = 0;",
      "e->LanguageID  = 1;" + NL + "    e->Count       = 0;"),
    M("ctor-count", "e->Count       = 0;" + NL + "    e->Head        = 0;",
      "e->Count       = 1;" + NL + "    e->Head        = 0;"),
    M("ctor-head", "e->Head        = 0;" + NL + "    return e;",
      "e->Head        = 1;" + NL + "    return e;"),
    M("ctor-return", "    return e;" + NL + "}",
      "    return e + 1;" + NL + "}"),

    # Start and Stop.
    M("start-first", "for (ev = JOY_EVENT_CHEAT_L1; ev <= JOY_EVENT_CHEAT_CIRCLE;"
      " ev++)" + NL + "        AddJoyHandler",
      "for (ev = JOY_EVENT_CHEAT_L2; ev <= JOY_EVENT_CHEAT_CIRCLE;"
      " ev++)" + NL + "        AddJoyHandler"),
    M("start-last", "ev <= JOY_EVENT_CHEAT_CIRCLE; ev++)" + NL
      + "        AddJoyHandler",
      "ev < JOY_EVENT_CHEAT_CIRCLE; ev++)" + NL + "        AddJoyHandler"),
    M("start-port", "AddJoyHandler(0, ev,", "AddJoyHandler(1, ev,"),
    M("start-obj", "eastereggs_joy_handler, e);",
      "eastereggs_joy_handler, e + 1);"),
    M("start-just", "    e->JustEntered = 0;" + NL + "    e->LanguageID  = 0;"
      + NL + "    e->Active      = 1;",
      "    e->LanguageID  = 0;" + NL + "    e->Active      = 1;"),
    M("start-lang", "    e->LanguageID  = 0;" + NL + "    e->Active      = 1;",
      "    e->Active      = 1;"),
    M("start-active", "e->Active      = 1;" + NL + "    eastereggs_reset(e);",
      "e->Active      = 2;" + NL + "    eastereggs_reset(e);"),
    M("start-reset", "e->Active      = 1;" + NL + "    eastereggs_reset(e);",
      "e->Active      = 1;"),
    M("stop-first", "for (ev = JOY_EVENT_CHEAT_L1; ev <= JOY_EVENT_CHEAT_CIRCLE;"
      " ev++)" + NL + "        RemoveJoyHandler",
      "for (ev = JOY_EVENT_CHEAT_L2; ev <= JOY_EVENT_CHEAT_CIRCLE;"
      " ev++)" + NL + "        RemoveJoyHandler"),
    M("stop-last", "ev <= JOY_EVENT_CHEAT_CIRCLE; ev++)" + NL
      + "        RemoveJoyHandler",
      "ev < JOY_EVENT_CHEAT_CIRCLE; ev++)" + NL + "        RemoveJoyHandler"),
    M("stop-port", "RemoveJoyHandler(0, ev);", "RemoveJoyHandler(1, ev);"),
    M("stop-active", "RemoveJoyHandler(0, ev);" + NL + "    e->Active      = 0;",
      "RemoveJoyHandler(0, ev);" + NL + "    e->Active      = 1;"),
    M("stop-just", "    e->JustEntered = 0;" + NL + "    e->LanguageID  = 0;"
      + NL + "    eastereggs_reset(e);",
      "    e->LanguageID  = 0;" + NL + "    eastereggs_reset(e);"),
    M("stop-lang", "    e->LanguageID  = 0;" + NL + "    eastereggs_reset(e);",
      "    eastereggs_reset(e);"),
    M("stop-reset", "e->LanguageID  = 0;" + NL + "    eastereggs_reset(e);"
      + NL + "}",
      "e->LanguageID  = 0;" + NL + "}"),
    M("reset", "    e->Count = 0;", "    e->Count = 1;"),

    # A press.
    M("press-active", "if (!e->Active)" + NL + "        return;",
      "if (e->Active != 1)" + NL + "        return;"),
    M("press-active-gone", "if (!e->Active)" + NL + "        return;",
      "if (0)" + NL + "        return;"),
    M("press-full", "if (n >= EASTEREGGS_CODE_LENGTH) {",
      "if (n > EASTEREGGS_CODE_LENGTH) {"),
    M("press-full-signed", "if (n >= EASTEREGGS_CODE_LENGTH) {",
      "if ((int32_t)n >= EASTEREGGS_CODE_LENGTH) {"),
    M("press-full-reset", "if (n >= EASTEREGGS_CODE_LENGTH) {" + NL
      + "        eastereggs_reset(e);" + NL,
      "if (n >= EASTEREGGS_CODE_LENGTH) {" + NL),
    M("press-full-on", "        eastereggs_reset(e);" + NL + "        return;"
      + NL + "    }",
      "        eastereggs_reset(e);" + NL + "    }"),
    M("press-slot", "e->Ring[(head + n) & 7] = ev;", "e->Ring[n & 7] = ev;"),
    M("press-slot-next", "e->Ring[(head + n) & 7] = ev;",
      "e->Ring[(head + n + 1) & 7] = ev;"),
    M("press-count", "e->Count = n + 1;", "e->Count = n + 2;"),
    M("press-eighth", "if (n + 1 != EASTEREGGS_CODE_LENGTH)",
      "if (n + 1 != EASTEREGGS_CODE_LENGTH - 1)"),
    M("match-init", "matched = 0;" + NL + "    for (i = 0;",
      "matched = 1;" + NL + "    for (i = 0;"),
    M("match-first", "for (i = 0; i < e->NumCodes; i++) {" + NL
      + "        EasterEggCode *c = &e->Codes[i];" + NL + NL
      + "        matched = 1;",
      "for (i = 1; i < e->NumCodes; i++) {" + NL
      + "        EasterEggCode *c = &e->Codes[i];" + NL + NL
      + "        matched = 1;"),
    M("match-last", "i < e->NumCodes; i++) {" + NL
      + "        EasterEggCode *c = &e->Codes[i];" + NL + NL
      + "        matched = 1;",
      "i + 1 < e->NumCodes; i++) {" + NL
      + "        EasterEggCode *c = &e->Codes[i];" + NL + NL
      + "        matched = 1;"),
    M("match-j-first", "for (j = 0; j < EASTEREGGS_CODE_LENGTH; j++) {",
      "for (j = 1; j < EASTEREGGS_CODE_LENGTH; j++) {"),
    M("match-j-last", "for (j = 0; j < EASTEREGGS_CODE_LENGTH; j++) {",
      "for (j = 0; j < EASTEREGGS_CODE_LENGTH - 1; j++) {"),
    M("match-ring", "c->Buttons[j] != e->Ring[(head + j) & 7]",
      "c->Buttons[j] != e->Ring[j & 7]"),
    M("match-ring-order", "c->Buttons[j] != e->Ring[(head + j) & 7]",
      "c->Buttons[7 - j] != e->Ring[(head + j) & 7]"),
    M("match-order", "eastereggs_clear_group(e, c->Group);" + NL
      + "            c->On = 1;",
      "c->On = 1;" + NL
      + "            eastereggs_clear_group(e, c->Group);"),
    M("match-group-gone", "            eastereggs_clear_group(e, c->Group);"
      + NL, ""),
    M("match-on", "c->On = 1;", "c->On = 2;"),
    M("match-just", "e->JustEntered = 1;", "e->JustEntered = 0;"),
    M("match-lang", "e->LanguageID  = c->LanguageID;",
      "e->LanguageID  = c->Param;"),
    M("match-reset", "e->LanguageID  = c->LanguageID;" + NL
      + "            eastereggs_reset(e);",
      "e->LanguageID  = c->LanguageID;"),
    M("match-break", "eastereggs_reset(e);" + NL + "            break;",
      "eastereggs_reset(e);"),
    M("slide-gone", "if (!matched) {", "if (0) {"),
    M("slide-head", "e->Head  = (e->Head + 1) & 7;", "e->Head  = e->Head + 1;"),
    M("slide-head-back", "e->Head  = (e->Head + 1) & 7;",
      "e->Head  = (e->Head - 1) & 7;"),
    M("slide-count", "e->Count = e->Count - 1;", "e->Count = 0;"),
    M("handler-obj", "eastereggs_on_button((EasterEggs *)obj, port, ev, value);",
      "eastereggs_on_button(&TheEasterEggs, port, ev, value);"),

    # The clears.
    M("temp-kept", "if (e->Codes[i].Kept == 0)", "if (e->Codes[i].Kept != 1)"),
    M("temp-on", "if (e->Codes[i].Kept == 0)" + NL
      + "            e->Codes[i].On = 0;",
      "if (e->Codes[i].Kept == 0)" + NL
      + "            e->Codes[i].On = 2;"),
    M("temp-last", "i < e->NumCodes; i++)" + NL
      + "        if (e->Codes[i].Kept",
      "i + 1 < e->NumCodes; i++)" + NL
      + "        if (e->Codes[i].Kept"),
    M("group-zero", "if (group == 0)" + NL + "        return;",
      "if (0)" + NL + "        return;"),
    M("group-cmp", "if (e->Codes[i].Group == group)",
      "if (e->Codes[i].Group != group)"),
    M("group-on", "if (e->Codes[i].Group == group)" + NL
      + "            e->Codes[i].On = 0;",
      "if (e->Codes[i].Group == group)" + NL
      + "            e->Codes[i].On = 2;"),
    M("group-last", "i < e->NumCodes; i++)" + NL
      + "        if (e->Codes[i].Group",
      "i + 1 < e->NumCodes; i++)" + NL
      + "        if (e->Codes[i].Group"),

    # The lookups.
    M("ison-type", "if (c->Type == type && c->Param == param)",
      "if (c->Param == param)"),
    M("ison-param", "if (c->Type == type && c->Param == param)",
      "if (c->Type == type)"),
    M("ison-on", "return c->On;", "return 1;"),
    M("ison-none", "    }" + NL + "    return 0;" + NL + "}",
      "    }" + NL + "    return 1;" + NL + "}"),
    M("ison-last", "i < e->NumCodes; i++) {" + NL
      + "        const EasterEggCode *c",
      "i + 1 < e->NumCodes; i++) {" + NL
      + "        const EasterEggCode *c"),
    M("car-swap", "cop ? EASTEREGG_TYPE_COP_CAR" + NL
      + "                                   : EASTEREGG_TYPE_CAR",
      "cop ? EASTEREGG_TYPE_CAR" + NL
      + "                                   : EASTEREGG_TYPE_COP_CAR"),
    M("track-swap", "backward ? EASTEREGG_TYPE_TRACK_BACK" + NL
      + "                                        : EASTEREGG_TYPE_TRACK",
      "backward ? EASTEREGG_TYPE_TRACK" + NL
      + "                                        : EASTEREGG_TYPE_TRACK_BACK"),
    M("egg", "return e->Codes[n].On;", "return e->Codes[n].Kept;"),
    M("take-clear", "e->JustEntered = 0;" + NL + "    return e->LanguageID;",
      "return e->LanguageID;"),
    M("take-ret", "    return e->LanguageID;", "    return e->JustEntered;"),
    M("just", "return e->JustEntered;" + NL + "}" + NL + NL
      + "int32_t eastereggs_is_active",
      "return e->Active;" + NL + "}" + NL + NL
      + "int32_t eastereggs_is_active"),
    M("active", "return e->Active;", "return e->JustEntered;"),
    M("enable", "    e->Active = 1;", "    e->Active = 2;"),
    M("disable", "    e->Active = 0;", "    e->Active = 2;"),
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
        todo, SOURCES, "eastereggs_test",
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
    print("%d ops, %d lines, %d differ" % (len(sc), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
