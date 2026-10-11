#!/usr/bin/env python3
"""Cross-check 3DS Files/source/eventtree.c, the career's event trees
(RE-6a), against the retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own code: EventTree.obj's constructor and
destructor, SetName, the events by number, SetEvents, CalcStatePointers,
the trees' state and reward lookups, the functions over every tree, the
loader and the unloader (0x001fd130 .. 0x001fffb0), EventGoal::Passed,
the four state classes and EventInfo (0x00200000 .. 0x002014e8), and the
two Ultimates' test (0x002026f8). The harness (tools/src/eventtree_test.c)
runs the port and prints the same lines.

**The data** is one file both sides load at a 16-byte boundary: the two
EventTree chunks of FRONTB.BUN as the disc has them, then trees made up
here -- every event type and a few that are none, numbers repeated and
missing, the Ultimate in both, names of every case, a name that is neither
tree's (first, and last), no name at all -- and a chunk of another type.

**The stubs**, logged and answered by the same rule on both sides: bMalloc
(each block numbered, M0 on), bFree, GetTextureInfo (the race-type icons;
a token back), GetTranslatedString ("S" and the id), Timer::PrintToString
("T" and the time) and bRandom (a queue, then an answer). Eggs 6 and 7,
bVersionE3, UnlockAllEvents and Fred's two states are memory both sides
read. The icons' hashes, which retail's static constructor makes, are
bStringHash's, run in the model.

**Compared** are the stubs' logs, every answer, the trees' fields, the
events' trees and states, and Fred's state bytes after each change.
Pointers print by what they point into (see the harness).

What the script keeps away from, as retail would read or write where the
port cannot: an event's state through a tree that has been deleted, a
place past GetFinishString's table of 16 (both sides print "skip"), a
tournament's negative count of opponents, and the disc's trees loaded
under bVersionE3, whose names fail before their events, which retail
then deals Fred's state to from a deleted tree.

    python tools/eventtree_check.py
    python tools/eventtree_check.py --mutate [--only a,b]
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
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/eventtree_test.c"
ET = "3DS Files/source/eventtree.c"
SOURCES = [HARNESS, ET]
HARNESS_TIMEOUT = 120
FRONTB = ROOT / "extracted-retail" / "FRONTEND" / "FRONTB.BUN"
REAL = (0xd97100, 0xd9aa50)             # the two EventTree chunks
DATA_FILES = [FRONTB]

# ================================================================ the image

GP = retail_model.RETAIL_GP
FRED = 0x002fc050
FRED_SPAN = 0x10000
CH_STATE, HP_STATE, ULT = 392, 648, 904
LIST = GP - 16712                       # the trees' bTList
G_WORD, G_CH, G_HP = GP - 16704, GP - 16700, GP - 16696
G_ALL = GP - 16720                      # UnlockAllEvents
G_E3 = GP - 23224                       # bVersionE3
EGG_TABLE = 0x0031d7f4
TEX_HASHES = 0x0031b8f0
WINDOW = 0x24000                        # an int16 index past an array: 4 * 32768
TREE_SIZE = 288
EV_SIZE = 188
PAD = 0x2000                            # zeros after the last chunk

ICONS = ("RACEICON", "TIMETRIALICON", "LAPKNOCKOUTICON", "RACEKNOCKOUTICON",
         "TOURNEYICON", "POINT2POINTICON")

S_MALLOC = 0x002577c0
S_FREE = 0x00257850
S_TEX = 0x001abf48
S_TR = 0x0021e560
S_TIMER = 0x001a3b98
S_RANDOM = 0x0025a488
F_HASH = 0x002534a8

F_CTOR = 0x001fd130
F_DTOR = 0x001fd250
F_SETNAME = 0x001fdef8
F_NUM = 0x001fdfe8
F_IDX = 0x001fe030
F_CALC = 0x001fe988
F_TRESET = 0x001feb50
F_TUNLOCK = 0x001febb0
F_CUR = 0x001fec10
F_SETEVENTS = 0x001fff60
F_PASSED = 0x001fffb0
TREE_FNS = {"carunl": 0x001ff360, "carrew": 0x001ff438,
            "findcar": 0x001ff500, "trkunl": 0x001ff5c8,
            "trkrew": 0x001ff6c8, "findtrk": 0x001ff7c0}
GL_FNS = {"carrew": 0x001ff8b8, "carunl": 0x001ff918,
          "numcars": 0x001ff978, "findcar": 0x001ff9d8,
          "findtrk": 0x001ffa38, "trkrew": 0x001ffaa8,
          "trkunl": 0x001ffb18, "lock": 0x001ffbb0, "unlock": 0x001ffbf8,
          "get": 0x001ffef8, "both": 0x002026f8}
F_LOADER = 0x001ffc40
F_UNLOADER = 0x001ffe80
EV_FNS = {"car": 0x00200878, "goal": 0x002008b8, "track": 0x002008f8,
          "reward": 0x00200938, "opp": 0x00200978, "obj": 0x002009b8,
          "earned": 0x002009d0, "rank": 0x00200d48, "tour": 0x00200d70,
          "ko": 0x00200d90, "time": 0x00200db0, "size": 0x00200de8,
          "finish": 0x00200e78, "last": 0x00200f98, "status": 0x002010b8,
          "ridx": 0x002012d8, "rcount": 0x00201350, "reset": 0x00201380,
          "unlock": 0x002013e0, "multi": 0x00201468, "setcar": 0x00201488,
          "getcar": 0x002014b8}
ST_FNS = {"rreset": 0x00200000, "runlock": 0x00200008,
          "rstatus": 0x00200018, "treset": 0x00200048,
          "tunlock": 0x00200050, "tstatus": 0x00200068,
          "kreset": 0x002000a8, "kunlock": 0x002000b8, "kidx": 0x002001a8,
          "krank": 0x00200220, "kseed": 0x002002c0, "knew": 0x002002c8,
          "kset": 0x002002f8, "kstatus": 0x002003f8,
          "ksetcar": 0x00200468, "kgetcar": 0x00200478,
          "kspos": 0x00200498, "kgpos": 0x00200598,
          "oreset": 0x00200638, "ounlock": 0x00200668, "oidx": 0x002006a0,
          "oracer": 0x00200710, "ouser": 0x00200768,
          "opoints": 0x00200788, "oseed": 0x00200798, "onew": 0x002007a0,
          "ostatus": 0x002007d0, "osetcar": 0x00200848,
          "ogetcar": 0x00200858}
LIMIT = 2000000


def s8(v):
    v &= 0xff
    return v - 256 if v >= 128 else v


# ================================================================== model

class Queue(object):
    def __init__(self):
        self.q, self.i, self.answer = [], 0, 0

    def fill(self, vals):
        self.q, self.i = vals[:64], 0

    def next(self):
        if self.i < len(self.q):
            r = self.q[self.i]
            self.i += 1
            return r
        return self.answer


class Model(object):
    def __init__(self, data):
        e = self.e = retail_model.RetailEmu(ieee=True)
        self.out = []

        def block(n):
            p = e.alloc(n, align=16)
            e.write(p, bytes(n))
            return p
        self.loose = block(TREE_SIZE)
        self.st = block(32)
        self.goal = block(16)
        self.leaf = block(16)
        self.outw = block(16)
        self.eggs = block(512)
        self.name = block(256)
        self.strs = [block(32) for _ in range(8)]
        self.kstr = 0
        block(0x10000)
        self.B = block(len(data) + PAD)
        e.write(self.B, data)
        self.ndata = len(data)
        self.blocks = {}
        self.ntex = 0
        e.put32(EGG_TABLE, self.eggs)
        e.put32(LIST, LIST)
        e.put32(LIST + 4, LIST)
        for i, n in enumerate(ICONS):
            e.write(self.name, n.encode() + b"\0")
            e.put32(TEX_HASHES + 4 * i,
                    e.call(F_HASH, self.name, limit=10000))
        self.randq = Queue()
        for addr, fn in ((S_MALLOC, self.s_malloc), (S_FREE, self.s_free),
                         (S_TEX, self.s_tex), (S_TR, self.s_tr),
                         (S_TIMER, self.s_timer),
                         (S_RANDOM, self.s_random)):
            e.stub(addr, fn)

    def emit(self, line):
        self.out.append(line)

    def cstr(self, a):
        e = self.e
        s = bytearray()
        while e.mem[a] != 0 and len(s) < 256:
            s.append(e.mem[a])
            a += 1
        return s.decode("latin-1")

    def P(self, a):
        a &= M32
        if a == 0:
            return "-"
        if a in self.blocks:
            return "M%d" % self.blocks[a]
        if a == self.loose:
            return "L"
        if FRED <= a < FRED + FRED_SPAN:
            return "F%d" % (a - FRED)
        if self.B - WINDOW <= a < self.B + self.ndata + WINDOW:
            return "B%d" % (a - self.B)
        return "?%x" % a

    def call(self, fn, *args):
        return self.e.call(fn, *args, limit=LIMIT)

    # ---- stubs

    def s_malloc(self, em):
        size = s32(em.reg[4])
        name = self.cstr(em.reg[5] & M32)
        line, pool = s32(em.reg[6]), s32(em.reg[7])
        p = em.alloc(size + 16, align=16)
        em.write(p, bytes(size + 16))
        n = len(self.blocks)
        self.blocks[p] = n
        if name == "bWare/inc/bWare.hpp":
            self.emit("  malloc %s %d %d %d -> M%d" % (name, line, pool,
                                                       size, n))
        else:
            self.emit("  malloc %s %d %d -> M%d" % (name, line, pool, n))
        return p

    def s_free(self, em):
        self.emit("  free %s" % self.P(em.reg[4]))
        return 0

    def s_tex(self, em):
        r = 0x0f000000 + 16 * self.ntex
        self.ntex += 1
        self.emit("  tex %08x %d %d -> %x" % (em.reg[4] & M32,
                                             s32(em.reg[5]), s32(em.reg[6]),
                                             r))
        return r

    def s_tr(self, em):
        i = s32(em.reg[4])
        self.emit("  tr %d" % i)
        p = self.strs[self.kstr & 7]
        self.kstr += 1
        em.write(p, ("S%d" % i).encode() + b"\0")
        return p

    def s_timer(self, em):
        t = s32(self.e.u32(em.reg[4] & M32))
        self.emit("  timer %d %d" % (t, s32(em.reg[6])))
        em.write(em.reg[5] & M32, ("T%d" % t).encode() + b"\0")
        return 0

    def s_random(self, em):
        r = s32(self.randq.next())
        self.emit("  random %d -> %d" % (s32(em.reg[4]), r))
        return r

    # ---- printing

    def globals(self):
        e = self.e
        self.emit("  globals ch %s hp %s w %s ult %s" % (
            self.P(e.u32(G_CH)), self.P(e.u32(G_HP)), self.P(e.u32(G_WORD)),
            self.P(e.u32(FRED + ULT))))

    def trees(self):
        e = self.e
        out, n = [], e.u32(LIST)
        while n != LIST:
            out.append(n)
            n = e.u32(n)
        return out

    def tree_at(self, k):
        return self.loose if k < 0 else self.trees()[k]

    def dump(self, t):
        e, P = self.e, self.P

        def u(o):
            return e.u32(t + o)
        name = self.cstr(u(12)) if u(12) else "-"
        self.emit("tree %s type %d name %s" % (P(t), s32(u(8)), name))
        self.emit("  name %s cam %s" % (P(u(12)), P(u(16))))
        self.emit("  cars %s %d tracks %s %d goals %s %d" % (
            P(u(20)), s32(u(24)), P(u(28)), s32(u(32)), P(u(36)),
            s32(u(40))))
        self.emit("  rewards %s %d opps %s %d" % (P(u(44)), s32(u(48)),
                                                  P(u(52)), s32(u(56))))
        self.emit("  events %s %d leaves %s state %d" % (
            P(u(60)), s32(u(68)), P(u(64)), s32(u(72))))
        self.emit("  polys %s %d line %s leaf %s cur %s" % (
            P(u(76)), s32(u(80)), P(u(84)), P(u(88)), P(u(92))))
        self.emit("  center %x %x %x" % (u(96), u(100), u(104)))
        self.emit("  lines %d pad %x %x %x" % (s32(u(112)), u(116), u(120),
                                               u(124)))
        self.emit("  num " + " ".join("%x" % u(128 + 4 * i)
                                      for i in range(16)))
        self.emit("  class " + " ".join("%x" % u(192 + 4 * i)
                                        for i in range(16)))
        self.emit("  tex " + " ".join("%x" % u(256 + 4 * i)
                                      for i in range(8)))

    def events(self, t):
        e = self.e
        n, p = s32(e.u32(t + 68)), e.u32(t + 60)
        for i in range(max(n, 0)):
            a = p + EV_SIZE * i
            self.emit("  ev %s #%d tree %s state %s" % (
                self.P(a), s8(e.u8(a + 40)), self.P(e.u32(a)),
                self.P(e.u32(a + 4))))

    def state_hex(self, s):
        return "-" if s == 0 else self.e.read(s, 16).hex()

    def fdump(self):
        e = self.e
        self.emit("fred %s %s ult %s" % (
            e.read(FRED + CH_STATE, 256).hex(),
            e.read(FRED + HP_STATE, 256).hex(), self.P(e.u32(FRED + ULT))))

    # ---- ops

    def op_ev(self, a):
        e, P = self.e, self.P
        o = a[1]
        ev = self.B + int(a[2], 0)
        i = (lambda j: s32(int(a[j], 0)))   # noqa: E731
        head = "ev %s %s" % (o, P(ev))
        fn = EV_FNS.get(o)
        if o in ("car", "goal", "track", "reward", "opp"):
            r = self.call(fn, ev, i(3))
            self.emit("%s %d -> %s" % (head, i(3), P(r)))
        elif o in ("obj", "rank", "tour", "ko", "time"):
            self.emit("%s -> %s" % (head, P(self.call(fn, ev))))
        elif o == "earned":
            self.emit("%s %d" % (head, i(3)))
            self.emit("  -> %d" % self.call(fn, ev, i(3)))
        elif o in ("size", "last", "ridx", "rcount", "multi"):
            self.emit("%s -> %d" % (head, self.call(fn, ev)))
        elif o == "finish":
            s = e.u32(ev + 4)
            if s8(e.u8(ev + 41)) in (0, 2) and s != 0 and e.u8(s) >= 16:
                self.emit("%s skip" % head)
            else:
                self.emit(head)
                r = self.call(fn, ev) & M32
                self.emit("  -> %s" % self.cstr(r))
        elif o == "status":
            self.emit("%s -> %d" % (head, self.call(fn, ev, 0)))
        elif o == "statusg":
            self.emit("%s -> %d" % (head,
                                    self.call(EV_FNS["status"], ev,
                                              self.goal)))
        elif o in ("reset", "unlock"):
            self.call(fn, ev)
            self.emit("%s | %s" % (head, self.state_hex(e.u32(ev + 4))))
        elif o == "setcar":
            self.call(fn, ev, i(3), i(4), i(5))
            self.emit("%s %d %d %d | %s" % (head, i(3), i(4), i(5),
                                            self.state_hex(e.u32(ev + 4))))
        elif o == "getcar":
            w = self.outw
            for k in range(3):
                e.put32(w + 4 * k, -99)
            self.call(fn, ev, w, w + 4, w + 8)
            self.emit("%s -> %d %d %d" % (head, s32(e.u32(w)),
                                          s32(e.u32(w + 4)),
                                          s32(e.u32(w + 8))))
        elif o == "put":
            s = e.u32(ev + 4)
            if s != 0:
                b = bytes.fromhex(a[3])[:16]
                e.write(s, b)
            self.emit("%s | %s" % (head, self.state_hex(s)))
        else:
            raise ValueError(o)

    def op_tr(self, a):
        e, P = self.e, self.P
        o = a[1]
        t = self.tree_at(int(a[2], 0))
        i = (lambda j: s32(int(a[j], 0)))   # noqa: E731
        head = "tr %s %s" % (o, P(t))
        if o == "num":
            self.emit("%s %d -> %s" % (head, i(3), P(self.call(F_NUM, t,
                                                             i(3)))))
        elif o == "idx":
            self.emit("%s %d -> %d" % (head, i(3), self.call(F_IDX, t,
                                                             i(3))))
        elif o in ("reset", "unlock"):
            self.emit(head)
            self.call(F_TRESET if o == "reset" else F_TUNLOCK, t)
        elif o == "cur":
            ev = self.B + i(3)
            e.put32(self.leaf, t)
            e.put32(self.leaf + 4, ev)
            e.put32(t + 88, self.leaf)
            self.call(F_CUR, t)
            self.emit("%s %s | %s" % (head, P(ev),
                                      self.state_hex(e.u32(ev + 4))))
            e.put32(t + 88, 0)
        elif o in ("carunl", "carrew"):
            self.emit("%s %d -> %d" % (head, i(3),
                                       self.call(TREE_FNS[o], t, i(3))))
        elif o == "findcar":
            self.emit("%s %d -> %s" % (head, i(3),
                                       P(self.call(TREE_FNS[o], t, i(3)))))
        elif o in ("trkunl", "trkrew"):
            self.emit("%s %d %d -> %d" % (
                head, i(3), i(4), self.call(TREE_FNS[o], t, i(3), i(4))))
        elif o == "findtrk":
            self.emit("%s %d %d -> %s" % (
                head, i(3), i(4), P(self.call(TREE_FNS[o], t, i(3), i(4)))))
        elif o == "calc":
            self.emit("%s F%d %d" % (head, i(3), i(4)))
            self.call(F_CALC, t, FRED + i(3), 256, i(4))
            self.emit("  state %d ult %s" % (s32(e.u32(t + 72)),
                                             P(e.u32(FRED + ULT))))
            self.events(t)
        elif o == "setname":
            self.emit("%s %s" % (head, a[3]))
            if a[3] == "-":
                p = 0
            else:
                e.write(self.name, a[3].encode() + b"\0")
                p = self.name
            self.emit("  -> %d" % self.call(F_SETNAME, t, p))
            nm = e.u32(t + 12)
            self.emit("  type %d name %s" % (s32(e.u32(t + 8)),
                                             self.cstr(nm) if nm else "-"))
            self.globals()
        elif o == "setevents":
            self.emit("%s B%d %d" % (head, i(3), i(4)))
            self.call(F_SETEVENTS, t, self.B + i(3), i(4))
            self.emit("  events %s %d cur %s" % (
                P(e.u32(t + 60)), s32(e.u32(t + 68)), P(e.u32(t + 92))))
            self.events(t)
        elif o == "passed":
            self.emit("%s -> %d" % (head, self.call(F_PASSED, self.goal, t)))
        else:
            raise ValueError(o)

    def op_gl(self, a):
        o = a[1]
        i = (lambda j: s32(int(a[j], 0)))   # noqa: E731
        fn = GL_FNS[o]
        if o in ("carrew", "carunl"):
            self.emit("gl %s %d -> %d" % (o, i(2), self.call(fn, i(2))))
        elif o == "findcar":
            self.emit("gl %s %d -> %s" % (o, i(2),
                                          self.P(self.call(fn, i(2)))))
        elif o == "findtrk":
            self.emit("gl %s %d %d -> %s" % (
                o, i(2), i(3), self.P(self.call(fn, i(2), i(3)))))
        elif o in ("trkrew", "trkunl"):
            self.emit("gl %s %d %d -> %d" % (o, i(2), i(3),
                                             self.call(fn, i(2), i(3))))
        elif o in ("numcars", "both"):
            self.emit("gl %s -> %d" % (o, self.call(fn)))
        elif o in ("lock", "unlock"):
            self.emit("gl %s" % o)
            self.call(fn)
        elif o == "get":
            self.e.write(self.name, a[2].encode() + b"\0")
            self.emit("gl get %s -> %s" % (a[2],
                                           self.P(self.call(fn, self.name))))
        else:
            raise ValueError(o)

    def op_state(self, a):
        e = self.e
        o = a[1]
        args = [s32(int(x, 0)) for x in a[2:]]
        while len(args) < 3:
            args.append(0)
        x, y, z = args[:3]
        st, g = self.st, self.goal
        fn = ST_FNS[o]
        line = "state %s" % o + "".join(" %s" % f for f in a[2:])
        if o in ("rreset", "treset", "kreset", "oreset"):
            self.call(fn, st)
        elif o in ("runlock", "tunlock"):
            self.call(fn, st, g)
        elif o in ("rstatus", "tstatus", "kstatus"):
            line += " -> %d" % self.call(fn, st, g)
        elif o == "kunlock" or o == "ounlock":
            self.call(fn, st, g, x)
        elif o in ("kidx", "ouser"):
            line += " -> %d" % self.call(fn, st)
        elif o in ("krank", "kgpos", "oidx", "oracer"):
            line += " -> %d" % self.call(fn, st, x)
        elif o in ("kset", "kspos"):
            self.call(fn, st, x, y)
        elif o in ("ksetcar", "osetcar"):
            self.call(fn, st, x, y, z)
        elif o in ("kgetcar", "ogetcar"):
            w = self.outw
            for k in range(3):
                e.put32(w + 4 * k, -99)
            self.call(fn, st, w, w + 4, w + 8)
            line += " -> %d %d %d" % (s32(e.u32(w)), s32(e.u32(w + 4)),
                                      s32(e.u32(w + 8)))
        elif o in ("kseed", "oseed"):
            line += " -> %d" % (self.call(fn, st) & M32)
        elif o in ("knew", "onew"):
            self.emit(line)
            line = ""
            self.call(fn, st)
        elif o == "opoints":
            line += " -> %d" % self.call(fn, x)
        elif o == "ostatus":
            line += " -> %d" % self.call(fn, st, g, x, y)
        else:
            raise ValueError(o)
        self.emit("%s | %s" % (line, e.read(st, 16).hex()))

    def run(self, a):
        e = self.e
        o = a[0]
        i = (lambda j: s32(int(a[j], 0)))   # noqa: E731
        if o == "e3":
            e.put32(G_E3, i(1))
        elif o == "all":
            e.put32(G_ALL, i(1))
        elif o == "egg":
            e.put32(self.eggs + 48 + 56 * i(1), i(2))
        elif o == "fredclr":
            e.write(FRED + CH_STATE, bytes(516))
        elif o == "fred":
            e.write(FRED + i(1), bytes.fromhex(a[2])[:512])
        elif o == "ult":
            e.put32(FRED + ULT, FRED + i(1) if i(1) else 0)
        elif o == "fdump":
            self.fdump()
        elif o == "goal":
            e.write(self.goal, struct.pack("<HHI", i(1) & 0xffff,
                                           i(2) & 0xffff, i(3) & M32))
        elif o == "st":
            b = bytes.fromhex(a[1]) if len(a) > 1 else b""
            e.write(self.st, (b + bytes(32))[:32])
        elif o == "randq":
            self.randq.fill([int(x, 0) & M32 for x in a[1:]])
        elif o == "rand":
            self.randq.answer = int(a[1], 0) & M32
        elif o == "glob":
            self.emit("glob")
            self.globals()
        elif o == "word":
            e.put32(G_WORD, self.tree_at(i(1)))
        elif o == "load":
            self.emit("load B%d" % i(1))
            self.emit("  -> %d" % self.call(F_LOADER, self.B + i(1)))
            self.globals()
        elif o == "unload":
            self.emit("unload B%d" % i(1))
            self.emit("  -> %d" % self.call(F_UNLOADER, self.B + i(1)))
            self.globals()
        elif o == "list":
            self.emit("list" + "".join(" " + self.P(t) for t in self.trees()))
        elif o == "dump":
            self.dump(self.tree_at(i(1)))
        elif o == "events":
            t = self.tree_at(i(1))
            self.emit("events %s" % self.P(t))
            self.events(t)
        elif o == "ctor":
            self.emit("ctor %s" % a[1])
            e.write(self.loose, bytes(TREE_SIZE))
            if a[1] == "-":
                p = 0
            else:
                e.write(self.name, a[1].encode() + b"\0")
                p = self.name
            self.call(F_CTOR, self.loose, p)
            self.dump(self.loose)
            self.globals()
        elif o == "dtor":
            self.emit("dtor %d" % i(1))
            self.call(F_DTOR, self.loose, i(1))
        elif o == "ev":
            self.op_ev(a)
        elif o == "tr":
            self.op_tr(a)
        elif o == "gl":
            self.op_gl(a)
        elif o == "state":
            self.op_state(a)
        else:
            raise ValueError(o)


def model(lines, data):
    m = Model(data)
    for ln in lines:
        m.run(ln.split("|"))
    return m.out


# ================================================================== the data

CHUNK = 0x80034a00
T_NAME, T_CARS, T_TRACKS, T_GOALS, T_REWARDS, T_EVENTS, T_OPPS = (
    1, 0x34a01, 0x34a02, 0x34a03, 0x34a04, 0x34a05, 0x34a06)


def child(t, payload):
    assert len(payload) % 4 == 0, hex(t)
    return struct.pack("<II", t, len(payload)) + payload


def name_payload(s):
    b = s.encode() + b"\0"
    return b + bytes(-len(b) % 4)


class Tree(object):
    """A tree made up: its tables, its events, and the order its children
    come in."""

    def __init__(self, rng, name, nevents=None, numbers=None, types=None,
                 order=None, ncars=None, ntracks=None, ngoals=None,
                 nrewards=None, nopps=None, extra=False):
        self.name = name
        r = rng
        self.ncars = r.randint(0, 12) if ncars is None else ncars
        self.ntracks = r.randint(0, 10) if ntracks is None else ntracks
        self.ngoals = r.randint(1, 12) if ngoals is None else ngoals
        self.nrewards = r.randint(0, 16) if nrewards is None else nrewards
        self.nopps = r.randint(0, 8) if nopps is None else nopps
        m = r.randint(0, 34) if nevents is None else nevents
        if numbers is None:
            numbers = list(range(1, 33))
            r.shuffle(numbers)
            numbers = (numbers * 2)[:m]
            for _ in range(r.randint(0, 3)):
                if numbers:
                    numbers[r.randrange(len(numbers))] = r.choice(
                        [0, 31, 32, 33, -1, 100] + numbers)
        self.numbers = numbers
        if types is None:
            types = [r.choice([-1, 0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 6, 7])
                     for _ in numbers]
        types = list(types)
        # Fred's 256 bytes: the 4- and 16-byte states, then the 1s.
        while sum(16 if t in (3, 4) else 4 if t in (1, 5, 6) else 1
                  for t in types) > 248:
            k = r.choice([j for j, t in enumerate(types) if t in (3, 4)])
            types[k] = 0
        self.types = types
        self.goals = []
        for _ in range(self.ngoals):
            gt = r.choice([1, 1, 2, 3])
            ge = r.choice(numbers + [r.randint(0, 40)]) if numbers else 1
            gd = (r.randint(0, 9) if gt != 2
                  else r.choice([0, 0x7fffffff, r.randint(1, 2000000)]))
            self.goals.append((gt, ge & 0xffff, gd))
        self.rewards = []
        for _ in range(self.nrewards):
            rt = r.choice([0, 0, 1, 1, 2])
            v1 = r.randint(0, 70) if rt != 1 else r.randint(0, 20)
            v2 = r.choice([0, 1, 1, 2, 9])
            rd = r.choice([r.randint(-2, 9), r.randint(0, 2000000),
                           0x7fffffff])
            self.rewards.append((rt, v1, v2, r.randint(0, 255), rd))
        self.events = [self.event(r, n, t) for n, t in zip(numbers, types)]
        kids = [T_NAME, T_CARS, T_TRACKS, T_GOALS, T_REWARDS, T_EVENTS,
                T_OPPS]
        if extra:
            kids.append(0x34a07)
        self.order = order if order is not None else kids

    def event(self, r, number, typ):
        e = bytearray(r.getrandbits(8) for _ in range(EV_SIZE))
        nm = ("Ev%d %s" % (number, "x" * r.randint(0, 20)))[:31]
        e[8:40] = (nm.encode() + bytes(32))[:32]
        e[40] = number & 0xff
        e[41] = typ & 0xff

        def count(table, lim, spill=2):
            if table == 0:
                return r.choice([0, 0, 0, r.randint(0, 3)])
            return r.randint(0, min(lim + spill, 127))

        def idx(table):
            return r.randint(0, max(table - 1, 0) + (r.random() < 0.1))
        nc = count(self.ncars, 20)
        nt = r.randint(0, 8) if typ == 4 else count(self.ntracks, 8)
        ng = r.choice([0, 0, 1, 1, 2, 3, r.randint(0, 8)])
        nr = 0 if self.nrewards == 0 else r.choice([0, 1, 1, 2, 3, 8])
        no = r.randint(0, 10) if typ in (3, 4) else count(self.nopps, 7)
        e[59], e[60], e[61], e[62], e[63] = nc, nt, ng, nr, no
        struct.pack_into("<h", e, 66, r.randint(0, self.ngoals - 1))
        # Every array's entries index its table, so that a count that runs
        # into the next array still reads the tree's data.
        for k in range(20):
            struct.pack_into("<h", e, 68 + 2 * k, idx(self.ncars))
        for k in range(8):
            struct.pack_into("<h", e, 108 + 2 * k, idx(self.ntracks))
        for k in range(8):
            struct.pack_into("<h", e, 124 + 2 * k,
                             r.randint(0, self.ngoals - 1))
        for k in range(8):
            struct.pack_into("<h", e, 140 + 2 * k,
                             r.randint(0, max(self.nrewards - 1, 0)))
        for k in range(7):
            struct.pack_into("<h", e, 156 + 2 * k, idx(self.nopps))
        return bytes(e)

    def chunk(self):
        kids = []
        for t in self.order:
            if t == T_NAME:
                if self.name is not None:
                    kids.append(child(T_NAME, name_payload(self.name)))
            elif t == T_CARS:
                kids.append(child(T_CARS, bytes(range(4 * self.ncars))))
            elif t == T_TRACKS:
                kids.append(child(T_TRACKS,
                                  bytes(range(4 * self.ntracks))[::-1]))
            elif t == T_GOALS:
                kids.append(child(T_GOALS, b"".join(
                    struct.pack("<HHI", gt, ge, gd)
                    for gt, ge, gd in self.goals)))
            elif t == T_REWARDS:
                kids.append(child(T_REWARDS, b"".join(
                    struct.pack("<BBBBi", *rw) for rw in self.rewards)))
            elif t == T_EVENTS:
                kids.append(child(T_EVENTS, b"".join(self.events)))
            elif t == T_OPPS:
                kids.append(child(T_OPPS, bytes(4 * self.nopps)))
            else:
                kids.append(child(t, b"\x55" * 12))
        body = b"".join(kids)
        return struct.pack("<II", CHUNK, len(body)) + body


def parse_tree(data, off):
    """The events of the chunk at `off`: (offset of the record, number,
    type, cars, tracks, goals, rewards, opponents)."""
    t, n = struct.unpack_from("<II", data, off)
    assert t == CHUNK
    p, end = off + 8, off + 8 + n
    events = []
    while p < end:
        ct, cn = struct.unpack_from("<II", data, p)
        if ct == T_EVENTS:
            for k in range(cn // EV_SIZE):
                a = p + 8 + EV_SIZE * k
                r = data[a:a + EV_SIZE]
                events.append((a, s8(r[40]), s8(r[41]), s8(r[59]),
                               s8(r[60]), s8(r[61]), s8(r[62]), s8(r[63])))
        p += 8 + cn
    return events


class Data(object):
    """The data file: the disc's two trees, then the made-up ones, each
    chunk at a 16-byte boundary, and what the script needs to know of
    them."""

    def __init__(self):
        raw = FRONTB.read_bytes()
        self.buf = bytearray(raw[REAL[0]:REAL[1]])
        self.ch = 0
        self.hp = struct.unpack_from("<I", self.buf, 4)[0] + 8
        self.chunks = {}
        rng = random.Random(0x6ea)
        self.trees = {}

        def add(key, tree):
            self.buf += bytes(-len(self.buf) % 16)
            self.chunks[key] = len(self.buf)
            self.trees[key] = tree
            self.buf += tree.chunk()
        add("A", Tree(rng, "Championship", nevents=34))
        add("B", Tree(rng, "Hot Pursuit", nevents=33))
        add("C", Tree(rng, "championship", nevents=12,
                      order=[T_EVENTS, T_GOALS, T_CARS, T_NAME, T_REWARDS,
                             T_TRACKS, T_OPPS], extra=True))
        add("D", Tree(rng, "HOT PURSUIT E3", nevents=10,
                      order=[T_OPPS, T_REWARDS, T_GOALS, T_EVENTS, T_NAME,
                             T_CARS, T_TRACKS]))
        add("E", Tree(rng, "Other", nevents=6,
                      order=[T_CARS, T_TRACKS, T_GOALS, T_REWARDS,
                             T_EVENTS, T_OPPS, T_NAME]))
        add("F", Tree(rng, "Hot Pursuit X", nevents=0,
                      order=[T_NAME, T_CARS, T_TRACKS]))
        add("G", Tree(rng, None, nevents=8))
        add("H", Tree(rng, "Championship E3", nevents=5,
                      numbers=[32, 31, 1, 2, 3], types=[3, 4, 0, 1, 6]))
        add("I", Tree(rng, "Hot Pursuit", nevents=0, ngoals=1,
                      nrewards=0, order=[T_NAME, T_GOALS]))
        # Cars 63 and 62 as rewards, the last NumCarsUnlocked counts, and
        # events of types past 6 that have rewards. Every event has both
        # rewards and no goals of its own; the one goal passes at a place
        # of 9 or better.
        j = Tree(rng, "Hot Pursuit", nevents=6, types=[0, 7, -1, 2, 0, 9],
                 ngoals=1, nrewards=2)
        j.goals = [(1, 1, 9)]
        j.rewards = [(0, 63, 0, 0, 9), (0, 62, 1, 0, 9)]
        evs = []
        for ev in j.events:
            b = bytearray(ev)
            b[61], b[62] = 0, 2
            struct.pack_into("<hh", b, 140, 0, 1)
            evs.append(bytes(b))
        j.events = evs
        add("J", j)
        # Another chunk's type, which both functions refuse.
        self.buf += bytes(-len(self.buf) % 16)
        self.chunks["X"] = len(self.buf)
        self.buf += struct.pack("<II", 0x80034b00, 8) + bytes(8)
        self.buf += bytes(-len(self.buf) % 16)
        self.loose = {}
        for k in ("A", "B"):
            # The made-up trees' events again, outside any chunk, for the
            # loose tree's SetEvents. Their state words are 0: the port's
            # are offsets from Fred, retail's addresses, so a made-up one
            # would print differently until CalcStatePointers sets it.
            self.loose[k] = len(self.buf)
            for ev in self.trees[k].events:
                self.buf += ev[:4] + bytes(4) + ev[8:]
        self.buf = bytes(self.buf)
        self.events = {"ch": parse_tree(self.buf, self.ch),
                       "hp": parse_tree(self.buf, self.hp)}
        for k, off in self.chunks.items():
            if k != "X":
                self.events[k] = parse_tree(self.buf, off)


# ================================================================ the script

def state_bytes(r, typ, goal=None):
    """A state for an event of type `typ`, as hex: untried, passed or
    failed, and in between."""
    b = bytearray(r.getrandbits(8) for _ in range(16))
    if typ in (1, 5, 6):
        v = r.choice([0, 0x7fffffff, r.randint(1, 2000000),
                      r.randint(400000, 1800000), -r.randint(1, 1000),
                      r.getrandbits(32)])
        struct.pack_into("<I", b, 0, v & M32)
    elif typ == 3:
        w = 0
        for k in range(8):
            w |= r.choice([0, 0, r.randint(1, 8), r.randint(0, 15)]) << (4 * k)
        if r.random() < 0.2:
            w = 0
        struct.pack_into("<I", b, 0, w)
    elif typ == 4:
        for k in range(8):
            b[k] = r.choice([0, r.randint(0, 40), r.randint(0, 255)])
        if r.random() < 0.2:
            b[0:8] = bytes(8)
    else:
        b[0] = r.choice([0, 0, 1, 1, 2, 3, 4, 8, 9, 15, 16, 200])
    return bytes(b).hex()


def fred_fill(r):
    return "fred|%d|%s" % (CH_STATE, bytes(
        r.choice([0, 0, 0, 1, 2, 3, r.getrandbits(8)])
        for _ in range(512)).hex())


def event_full(ev):
    """Every question one event answers."""
    off, num, typ, nc, nt, ng, nr, no = ev
    out = []
    for fn in ("size", "multi", "rcount", "ridx", "rank", "tour", "ko",
               "time", "obj", "status", "finish", "getcar"):
        out.append("ev|%s|%d" % (fn, off))
    for fn, n in (("car", nc), ("goal", ng), ("track", nt),
                  ("reward", nr), ("opp", no)):
        for i in sorted({-1, 0, 1, n - 1, n, n + 1}):
            out.append("ev|%s|%d|%d" % (fn, off, i))
    for i in range(-1, max(nr, 0) + 1):
        out.append("ev|earned|%d|%d" % (off, i))
    return out


def event_light(ev):
    off, num, typ, nc, nt, ng, nr, no = ev
    out = ["ev|status|%d" % off, "ev|finish|%d" % off,
           "ev|ridx|%d" % off]
    for i in range(max(nr, 0)):
        out.append("ev|earned|%d|%d" % (off, i))
    return out


def gl_sweep(cars=range(-1, 72), tracks=range(-1, 22), dirs=(0, 1, 2)):
    out = []
    for c in cars:
        out += ["gl|carrew|%d" % c, "gl|carunl|%d" % c, "gl|findcar|%d" % c]
    for t in tracks:
        for d in dirs:
            out += ["gl|trkrew|%d|%d" % (t, d), "gl|trkunl|%d|%d" % (t, d),
                    "gl|findtrk|%d|%d" % (t, d)]
    return out


def tree_sweep(k, nums=range(-1, 35), cars=range(0, 70, 3),
               tracks=range(0, 22, 2)):
    out = []
    for n in nums:
        out += ["tr|num|%d|%d" % (k, n), "tr|idx|%d|%d" % (k, n)]
    for c in cars:
        out += ["tr|carunl|%d|%d" % (k, c), "tr|carrew|%d|%d" % (k, c),
                "tr|findcar|%d|%d" % (k, c)]
    for t in tracks:
        for d in (0, 1):
            out += ["tr|trkunl|%d|%d|%d" % (k, t, d),
                    "tr|trkrew|%d|%d|%d" % (k, t, d),
                    "tr|findtrk|%d|%d|%d" % (k, t, d)]
    return out


def state_cases(r):
    """The state classes alone, on a scratch state and goal."""
    out = []
    for _ in range(500):
        st = bytes(r.getrandbits(8) for _ in range(16))
        if r.random() < 0.3:
            st = bytes([r.randint(0, 9)]) + st[1:]
        out.append("st|" + st.hex())
        gt = r.choice([1, 2, 3])
        out.append("goal|%d|%d|%d" % (gt, r.randint(0, 33), r.choice(
            [r.randint(0, 9), r.randint(0, 2000000), 0x7fffffff,
             0x80000000, r.getrandbits(32)])))
        for _ in range(4):
            o = r.choice(sorted(ST_FNS))
            if o in ("kunlock",):
                out.append("state|%s|%d" % (o, r.randint(-2, 10)))
            elif o == "ounlock":
                out.append("state|%s|%d" % (o, r.randint(-2, 12)))
            elif o in ("krank", "kgpos"):
                out.append("state|%s|%d" % (o, r.randint(-2, 9)))
            elif o in ("kset", "kspos"):
                out.append("state|%s|%d|%d" % (o, r.randint(-2, 9),
                                               r.randint(-3, 20)))
            elif o in ("ksetcar", "osetcar"):
                out.append("state|%s|%d|%d|%d" % (
                    o, r.randint(-70000, 70000), r.randint(-300, 300),
                    r.randint(-300, 300)))
            elif o == "oidx":
                out.append("state|%s|%d" % (o, r.randint(0, 10)))
            elif o == "oracer":
                out.append("state|%s|%d" % (o, r.randint(0, 7)))
            elif o == "opoints":
                out.append("state|%s|%d" % (o, r.randint(0, 15)))
            elif o == "ostatus":
                out.append("state|%s|%d|%d" % (o, r.randint(-1, 9),
                                               r.randint(0, 10)))
            elif o in ("knew", "onew"):
                out.append("randq|%d" % r.getrandbits(32))
                out.append("state|%s" % o)
            else:
                out.append("state|%s" % o)
    for pos in range(16):
        out.append("state|opoints|%d" % pos)
    # The tournament's points, every count of opponents, and ties.
    for opps in range(11):
        for pts in ("0a0604030201000000000000", "1e1208090603000000000000",
                    "0606060606060606", "3c241812060300000000", "01"):
            out.append("st|" + pts)
            out.append("state|oidx|%d" % opps)
            for races in (1, 2, 3, 4, 8):
                out.append("goal|1|1|%d" % r.randint(1, 4))
                out.append("state|ostatus|%d|%d" % (races, opps))
    for k in range(8):
        out.append("st|0606050506060505")
        out.append("state|oracer|%d" % k)
    # Each status at its goal's edge: the result the goal's nData, and one
    # either side.
    for v in (1, 5, 400000, 0x7ffffffe):
        for dv in (-1, 0, 1):
            out += ["st|" + struct.pack("<I", v).hex(),
                    "goal|2|1|%d" % (v + dv), "state|tstatus"]
    for v in (1, 3, 8, 15):
        for dv in (-1, 0, 1):
            out += ["goal|1|1|%d" % (v + dv),
                    "st|%02x" % v, "state|rstatus",
                    "st|" + struct.pack("<I", v).hex(), "state|kstatus"]
    return out


def loose_cases(d, r):
    """The constructor, SetName, SetEvents and CalcStatePointers on a tree
    of the script's, and the destructor."""
    out = []
    for e3 in (0, 1):
        out.append("e3|%d" % e3)
        for nm in ("-", "Championship", "Hot Pursuit", "hot pursuit",
                   "CHAMPIONSHIP", "Championship E3", "Hot Pursuit E3",
                   "hot pursuit e3", "Other", "", "Champion", "Hot Pursuits"):
            out += ["ctor|" + nm, "tr|setname|-1|Hot Pursuit",
                    "tr|setname|-1|" + nm, "dtor|0"]
    out.append("e3|0")
    a = d.trees["A"]
    out += ["ctor|Championship", "fredclr"]
    out.append("tr|setevents|-1|%d|%d" % (d.loose["A"], EV_SIZE * 34))
    for n in (-1, 0, 1, 5, 31, 32, 33):
        out += ["tr|num|-1|%d" % n, "tr|idx|-1|%d" % n]
    # No reset or unlock yet: the events have no state until
    # CalcStatePointers, and both write through it.
    for k in range(34):
        off = d.loose["A"] + EV_SIZE * k
        out += ["ev|size|%d" % off, "ev|multi|%d" % off,
                "ev|rcount|%d" % off, "ev|car|%d|0" % off,
                "ev|goal|%d|0" % off]
    # SetEvents' size: not a multiple, and 0. A negative one is a count of
    # millions to retail's divu, written far past the block on both sides.
    for size in (EV_SIZE * 34 + 100, EV_SIZE - 1, 0):
        out.append("tr|setevents|-1|%d|%d" % (d.loose["A"], size))
    out.append("tr|setevents|-1|%d|%d" % (d.loose["A"], EV_SIZE * 34))
    # Nine times more: the tree keeps the one handle.
    for _ in range(9):
        out.append("tr|setevents|-1|%d|%d" % (d.loose["A"], EV_SIZE * 34))
    for align in (4, 1, 2, 8, 16, 3, 32):
        for base, ult in ((CH_STATE, 0), (HP_STATE, 0), (CH_STATE, 700),
                          (HP_STATE, CH_STATE + 12)):
            out += ["fredclr", "ult|%d" % ult,
                    "tr|calc|-1|%d|%d" % (base, align)]
    # The loose tree has no goals, so an objective of 0 is NULL, which
    # UnlockState skips, and any other is pGoals + 8 * index, which the
    # unlocks never read. The status reads it: low memory to retail, a
    # fault here, so that is left to the disc's trees and the made-up ones.
    out += ["fredclr", "tr|calc|-1|%d|4" % CH_STATE]
    for k in range(34):
        off = d.loose["A"] + EV_SIZE * k
        out += ["ev|put|%d|%s" % (off, state_bytes(r, a.types[k]))]
    out += ["fdump", "tr|reset|-1", "fdump"]
    for k in range(34):
        off = d.loose["A"] + EV_SIZE * k
        out += ["ev|unlock|%d" % off]
    out += ["fdump", "tr|reset|-1", "tr|unlock|-1", "fdump"]
    for k in range(34):
        off = d.loose["A"] + EV_SIZE * k
        out += ["ev|reset|%d" % off]
    out += ["fdump"]
    for flags in (0, 2, 1, 3):
        out += ["ctor|Hot Pursuit", "dump|-1", "dtor|%d" % flags]
    out += ["unload|%d" % d.ch, "fredclr", "ult|0"]
    return out


def real_cases(d, r):
    """The disc's two trees, loaded, through every question under one
    state after another."""
    ch, hp = d.events["ch"], d.events["hp"]
    both = ch + hp
    out = ["e3|0", "all|0", "egg|6|0", "egg|7|0", "fredclr",
           "load|%d" % d.ch, "load|%d" % d.hp, "list", "dump|0", "dump|1",
           "events|0", "events|1", "fdump"]
    out += ["gl|get|Championship", "gl|get|hot pursuit", "gl|get|Other",
            "gl|get|", "gl|get|Hot Pursuit E3"]
    for ev in both:
        out += event_full(ev)
    out += ["gl|both", "gl|numcars"]
    out += tree_sweep(0) + tree_sweep(1)
    out += gl_sweep()
    out += ["ev|last|%d" % ev[0] for ev in both[::7]]
    # Every event passed.
    out += ["gl|unlock", "fdump", "gl|both", "gl|numcars"]
    for ev in both:
        out += event_light(ev) + ["ev|getcar|%d" % ev[0]]
    out += ["ev|last|%d" % ev[0] for ev in both[::5]]
    out += gl_sweep(cars=range(0, 72, 2), tracks=range(0, 22, 3),
                    dirs=(0, 1))
    # All but one of 1 .. 31 passed, Hot Pursuit's Ultimate locked.
    for k in (0, 5, 30):
        for tree in (ch, hp):
            ev = tree[k]
            out += ["gl|unlock", "ev|reset|%d" % ev[0],
                    "ev|reset|%d" % hp[31][0], "ev|last|%d" % ev[0],
                    "ev|last|%d" % ch[31][0], "ev|status|%d" % hp[31][0],
                    "gl|both"]
    # Random states.
    for seed in range(6):
        out.append(fred_fill(r))
        for ev in both:
            if r.random() < 0.5:
                out.append("ev|put|%d|%s" % (ev[0], state_bytes(r, ev[2])))
        out.append("fdump")
        for ev in both:
            out += event_light(ev)
        out += ["gl|both", "gl|numcars"]
        out += ["ev|last|%d" % ev[0] for ev in r.sample(both, 4)]
        out += gl_sweep(cars=r.sample(range(0, 72), 12),
                        tracks=r.sample(range(0, 22), 4), dirs=(0, 1))
    # Event goals one by one: each of an event's goals passed alone.
    out += ["gl|lock", "fdump"]
    for ev in both:
        if ev[5] > 0:
            out += ["ev|status|%d" % ev[0]]
    out += ["gl|unlock"]
    for ev in both[::3]:
        out += ["ev|reset|%d" % ev[0]]
    for ev in both:
        out += ["ev|status|%d" % ev[0]]
    # The goals against one event, through statusg and Passed.
    for ev in both[::4]:
        for gt, gd in ((1, 1), (1, 3), (2, 900000), (3, 2), (1, 0)):
            out += ["goal|%d|%d|%d" % (gt, ev[1], gd),
                    "ev|statusg|%d" % ev[0], "tr|passed|0", "tr|passed|1"]
    # The eggs open the 31st events.
    for e6, e7 in ((1, 0), (0, 1), (1, 1), (5, 9)):
        out += ["egg|6|%d" % e6, "egg|7|%d" % e7, "gl|lock"]
        for ev in both:
            if ev[1] in (30, 31, 32):
                out += ["ev|status|%d" % ev[0], "ev|finish|%d" % ev[0]]
        out += ["gl|unlock"]
        for ev in both:
            if ev[1] in (31, 32):
                out += ["ev|status|%d" % ev[0]]
        out.append(fred_fill(r))
        for ev in both:
            if ev[1] in (31, 32):
                out += ["ev|status|%d" % ev[0]]
    out += ["egg|6|0", "egg|7|0"]
    # UnlockAllEvents.
    out += ["all|1", "fredclr"]
    for ev in both[::2]:
        out += ["ev|status|%d" % ev[0], "ev|finish|%d" % ev[0],
                "ev|earned|%d|0" % ev[0]]
    out += ["gl|numcars", "gl|both", "all|0"]
    # The selected car, the trees' state, the current node.
    for ev in both:
        out += ["ev|setcar|%d|%d|%d|%d" % (ev[0], r.randint(-5, 70),
                                          r.randint(-3, 10),
                                          r.randint(-3, 3)),
                "ev|getcar|%d" % ev[0]]
    out += ["tr|reset|0", "fdump", "tr|unlock|1", "fdump", "tr|unlock|0",
            "tr|reset|1", "fdump"]
    for ev in both[::3]:
        out += ["ev|reset|%d" % ev[0], "tr|cur|%d|%d" % (
            0 if ev in ch else 1, ev[0])]
    out += ["fdump"]
    return out


def synth_cases(d, r):
    """The made-up trees: loaded alone, beside the disc's, in every order
    of children, under every name, and gone again."""
    out = ["unload|%d" % d.ch, "fredclr", "ult|0", "e3|0"]
    out += ["load|%d" % d.chunks["X"], "unload|%d" % d.chunks["X"]]
    for k in ("A", "B"):
        out += ["load|%d" % d.chunks[k]]
    out += ["list", "dump|0", "dump|1", "events|0", "events|1", "fdump"]
    a, b = d.events["A"], d.events["B"]
    for ev in a + b:
        out += event_full(ev)
    out += tree_sweep(0, cars=range(0, 71), tracks=range(0, 21)) + \
        tree_sweep(1, cars=range(0, 71), tracks=range(0, 21))
    out += gl_sweep() + ["gl|numcars", "gl|both"]
    for seed in range(8):
        out.append(fred_fill(r))
        for ev in a + b:
            if r.random() < 0.6:
                out.append("ev|put|%d|%s" % (ev[0], state_bytes(r, ev[2])))
        out.append("fdump")
        for ev in a + b:
            out += event_light(ev)
        out += ["gl|numcars", "gl|both"]
        out += ["ev|last|%d" % ev[0] for ev in r.sample(a + b, 3)]
        out += gl_sweep(cars=r.sample(range(0, 72), 16),
                        tracks=r.sample(range(0, 22), 6), dirs=(0, 1, 2))
        for ev in r.sample(a + b, 10):
            out += ["ev|unlock|%d" % ev[0], "ev|status|%d" % ev[0]]
        out += ["tr|unlock|%d" % r.randint(0, 1), "fdump"]
    out += ["gl|lock", "fdump", "gl|unlock", "fdump"]
    for ev in a + b:
        out += ["ev|setcar|%d|%d|%d|%d" % (ev[0], r.randint(-5, 70),
                                          r.randint(-3, 10),
                                          r.randint(-3, 3)),
                "ev|getcar|%d" % ev[0]]
    # More trees: a second Championship, Hot Pursuit E3 (a failure without
    # bVersionE3), a failure last and first, a nameless one, the E3
    # Championship and an eventless Hot Pursuit.
    for k in ("C", "D", "E", "F", "G", "H", "I"):
        out += ["load|%d" % d.chunks[k], "list", "fdump"]
    out += ["gl|get|", "gl|get|championship", "gl|get|Other"]
    n = 5   # A, B, C, G, I stay
    for k in range(n):
        out += ["dump|%d" % k, "events|%d" % k]
    out += gl_sweep(cars=range(0, 72, 2), tracks=range(0, 22, 2),
                    dirs=(0, 1)) + ["gl|numcars"]
    for ev in d.events["C"] + d.events["G"]:
        out += event_light(ev)
    out += ["unload|%d" % d.ch, "list", "fdump"]
    # bVersionE3: D and H load, the plain names fail.
    out += ["e3|1", "fredclr", "ult|0"]
    for k in ("H", "D", "A", "C", "E", "F", "G"):
        out += ["load|%d" % d.chunks[k], "list"]
    out += ["fdump"]
    for k in range(3):
        out += ["dump|%d" % k, "events|%d" % k]
    h, dd = d.events["H"], d.events["D"]
    for ev in h + dd:
        out += event_full(ev)
    out += gl_sweep(cars=range(0, 72, 3), tracks=range(0, 22, 3),
                    dirs=(0, 1)) + ["gl|numcars", "gl|both"]
    out += ["unload|%d" % d.ch, "e3|0", "fredclr", "ult|0"]
    return out


def reload_cases(d, r):
    """The disc's trees again: the Ultimate's state set beforehand, Hot
    Pursuit first, and loaded twice over."""
    out = []
    for first, ult in ((d.hp, 0), (d.ch, CH_STATE + 40), (d.hp, HP_STATE)):
        second = d.ch if first == d.hp else d.hp
        out += ["fredclr", "ult|%d" % ult, "load|%d" % first,
                "load|%d" % second, "list", "events|0", "events|1", "fdump",
                "gl|unlock", "gl|both", "fdump", "gl|numcars"]
        out += ["unload|%d" % first, "list"]
    # Twice over: the second pair takes the globals, the events point at
    # the second pair, and the first pair's state is the same bytes.
    out += ["fredclr", "ult|0", "load|%d" % d.ch, "load|%d" % d.hp,
            "load|%d" % d.ch, "load|%d" % d.hp, "list"]
    for k in range(4):
        out += ["dump|%d" % k, "events|%d" % k]
    out += ["gl|unlock", "fdump", "gl|numcars", "gl|both"]
    out += ["unload|%d" % d.ch, "list", "fredclr", "ult|0",
            "load|%d" % d.ch, "load|%d" % d.hp]
    return out


def random_runs(d, r):
    """Random questions in a random order over the disc's trees, as
    loaded by reload_cases."""
    both = d.events["ch"] + d.events["hp"]
    out = []
    for _ in range(1500):
        ev = r.choice(both)
        off = ev[0]
        k = r.random()
        if k < 0.25:
            out.append("ev|put|%d|%s" % (off, state_bytes(r, ev[2])))
        elif k < 0.45:
            out.append("ev|status|%d" % off)
        elif k < 0.55:
            out.append("ev|earned|%d|%d" % (off, r.randint(0, 2)))
        elif k < 0.62:
            out.append("ev|finish|%d" % off)
        elif k < 0.67:
            out.append("ev|%s|%d" % (r.choice(["reset", "unlock"]), off))
        elif k < 0.72:
            out.append("gl|%s|%d" % (r.choice(["carrew", "carunl",
                                                "findcar"]),
                                      r.randint(0, 70)))
        elif k < 0.77:
            out.append("gl|%s|%d|%d" % (r.choice(["trkrew", "trkunl",
                                                   "findtrk"]),
                                         r.randint(0, 21), r.randint(0, 1)))
        elif k < 0.80:
            out.append("ev|last|%d" % off)
        elif k < 0.83:
            out.append("gl|both")
        elif k < 0.86:
            out.append("egg|%d|%d" % (r.choice([6, 7]), r.randint(0, 1)))
        elif k < 0.88:
            out.append("all|%d" % (r.random() < 0.3))
        elif k < 0.92:
            out.append("goal|%d|%d|%d" % (r.randint(1, 3), ev[1],
                                          r.choice([1, 2, 3, 900000])))
            out.append("ev|statusg|%d" % off)
        elif k < 0.95:
            out.append("ev|ridx|%d" % off)
        elif k < 0.97:
            out.append("randq|%d" % r.getrandbits(32))
            out.append("state|%s" % r.choice(["knew", "onew"]))
        else:
            out.append("fdump")
    out += ["all|0", "egg|6|0", "egg|7|0", "gl|numcars"]
    return out


def child_at(data, off, kind):
    """Where the payload of the chunk at `off`'s child `kind` starts."""
    n = struct.unpack_from("<I", data, off + 4)[0]
    p, end = off + 8, off + 8 + n
    while p < end:
        ct, cn = struct.unpack_from("<II", data, p)
        if ct == kind:
            return p + 8
        p += 8 + cn
    raise KeyError(kind)


def reward_data(data, chunk, ev, i):
    """The nData of event `ev`'s reward `i`, in the tree at `chunk`."""
    k = struct.unpack_from("<h", data, ev[0] + 140 + 2 * i)[0]
    return struct.unpack_from("<i", data,
                              child_at(data, chunk, T_REWARDS) + 8 * k + 4)[0]


def edge_cases(d, r):
    """Edges the rest misses, over the disc's trees as random_runs leaves
    them, then tree J alone and no trees at all."""
    ch, hp = d.events["ch"], d.events["hp"]
    out = ["all|0", "egg|6|0", "egg|7|0"]
    # 1 .. 31 all passed and the Ultimate untried: IsLastOpen on the
    # Ultimates themselves, which the loop never excuses.
    ults = [ev for ev in ch + hp if ev[1] == 32]
    out += ["gl|unlock", "ev|reset|%d" % ults[0][0]]
    for ev in ults:
        out += ["ev|status|%d" % ev[0], "ev|last|%d" % ev[0]]
    # A time's reward at its nData, and one either side.
    out.append("all|1")
    for chunk, evs in ((d.ch, ch), (d.hp, hp)):
        for ev in evs:
            if ev[2] not in (1, 5, 6):
                continue
            for i in range(ev[6]):
                v = reward_data(d.buf, chunk, ev, i)
                for dv in (-1, 0, 1):
                    out += ["ev|put|%d|%s" % (ev[0], struct.pack(
                        "<I", (v + dv) & M32).hex()),
                            "ev|earned|%d|%d" % (ev[0], i)]
    out.append("all|0")
    # The word at gp-16704, which only the unloader writes.
    out += ["word|1", "glob", "unload|%d" % d.ch]
    # Tree J: cars 63 and 62, and types past 6, under UnlockAllEvents.
    j = d.events["J"]
    out += ["fredclr", "ult|0", "load|%d" % d.chunks["J"], "list",
            "events|0", "gl|numcars", "gl|carunl|63", "gl|carunl|62",
            "gl|unlock", "fdump", "gl|numcars", "gl|carunl|63",
            "gl|carunl|62", "gl|carrew|63", "gl|findcar|63"]
    for ev in j:
        out += ["ev|status|%d" % ev[0], "ev|earned|%d|0" % ev[0],
                "ev|earned|%d|1" % ev[0]]
    out.append("all|1")
    for ev in j:
        out += ["ev|status|%d" % ev[0], "ev|earned|%d|0" % ev[0],
                "ev|earned|%d|1" % ev[0], "ev|finish|%d" % ev[0]]
    out += ["all|0", "unload|%d" % d.ch]
    # No trees: GetEventNumber on the NULL trees, past UnlockAllEvents.
    out += ["list", "all|1", "gl|both", "gl|numcars", "gl|get|Hot Pursuit",
            "all|0", "gl|numcars", "fredclr", "ult|0"]
    return out


def script(d):
    r = random.Random(0x6ea6)
    return (state_cases(r) + loose_cases(d, r) + real_cases(d, r)
            + synth_cases(d, r) + reload_cases(d, r) + random_runs(d, r)
            + edge_cases(d, r))


# ================================================================= running

def build_harness(tmp, name="eventtree_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, sc_path, data_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(sc_path), str(data_path)],
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


def write_inputs(tmp):
    d = Data()
    lines = script(d)
    sc = Path(tmp) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    dp = Path(tmp) / "data.bin"
    dp.write_bytes(d.buf)
    return d, lines, sc, dp


def model_cached(lines, buf):
    """model(lines, buf), or its last transcript when nothing it reads
    has changed (tools/mutpar.py)."""
    return mutpar.model_cached(lines, lambda s: model(s, buf),
                               data=DATA_FILES, cut=MUTATIONS_HEADER)


MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL

# ============================================================ the mutations

def _m(name, old, new, f=ET):
    return (name, f, old, new)


MUTATIONS = [
    # ---- bStrICmp, the handles
    _m("ic-26", "(uint32_t)(v - 97) < 26u", "(uint32_t)(v - 97) < 25u"),
    _m("ic-5f", "v &= 0x5f;", "v &= 0x7f;"),
    _m("th-same", "    for (i = 0; i < EVENT_TREE_HANDLES; i++)\n"
       "        if (sTrees[i] == t)\n            return i + 1;\n", ""),
    _m("th-free", "if (sTrees[i] == NULL) {", "if (sTrees[i] != t) {"),
    _m("rh-null", "            sTrees[i] = NULL;", "            ;"),
    _m("eit-8", "h - 1u < EVENT_TREE_HANDLES", "h - 1u <= EVENT_TREE_HANDLES"),
    _m("eis-0", "e->StateOffset != 0 ?", "e->StateOffset != 1 ?"),
    _m("ult-0", "Fred.pUltimateState != 0\n        ?",
       "Fred.pUltimateState != 1\n        ?"),
    _m("og-8", "8 * (intptr_t)e->nObjective", "4 * (intptr_t)e->nObjective"),
    _m("ea-s16", "    int16_t v;\n\n    memcpy(&v, (const uint8_t *)e",
       "    uint16_t v;\n\n    memcpy(&v, (const uint8_t *)e"),
    _m("ea-2", "offset + 2 * (size_t)i", "offset + 4 * (size_t)i"),
    # ---- the states
    _m("rs-r", "    s[0] = 0;\n}\n\nvoid rank_state_unlock",
       "    s[0] = 2;\n}\n\nvoid rank_state_unlock"),
    _m("rs-u", "    (void)goal;\n    s[0] = 1;", "    (void)goal;\n    s[0] = 2;"),
    _m("rs-s0", "    if (s[0] == 0)\n        return EVENT_UNTRIED;",
       "    if (s[0] == 1)\n        return EVENT_UNTRIED;"),
    _m("rs-lt", "return goal->nData < s[0] ?", "return goal->nData <= s[0] ?"),
    _m("ts-r", "    wr32(s, 0);\n}\n\nvoid time_state_unlock",
       "    wr32(s, 1);\n}\n\nvoid time_state_unlock"),
    _m("ts-u", "(int32_t)4000.5f", "(int32_t)4001.5f"),
    _m("ts-0", "if (t == 0 || t == 0x7fffffff)", "if (t == 0x7fffffff)"),
    _m("ts-7f", "if (t == 0 || t == 0x7fffffff)", "if (t == 0)"),
    _m("ts-lt", "return (int32_t)goal->nData < t ?",
       "return (int32_t)goal->nData <= t ?"),
    _m("ts-sg", "return (int32_t)goal->nData < t ?",
       "return goal->nData < (uint32_t)t ?"),
    _m("nb-15", "return (int32_t)((w >> (4 * i)) & 15u);",
       "return (int32_t)((w >> (4 * i)) & 7u);"),
    _m("sn-m", "(w & ~(15u << shift))", "(w & ~(7u << shift))"),
    _m("sn-v", "(((uint32_t)v & 15u) << shift)", "(((uint32_t)v & 7u) << shift)"),
    _m("ko-r4", "    wr32(s + 4, 0);\n    wr32(s, 0);", "    wr32(s, 0);"),
    _m("ko-r0", "    wr32(s + 4, 0);\n    wr32(s, 0);", "    wr32(s + 4, 0);"),
    _m("ko-u8", "for (i = 0; i < 8 && i < n; i++) {",
       "for (i = 0; i < 7 && i < n; i++) {"),
    _m("ko-un", "for (i = 0; i < 8 && i < n; i++) {",
       "for (i = 0; i < 8 && i <= n; i++) {"),
    _m("ko-u1", "w = set_nibble(w, i, i + 1);", "w = set_nibble(w, i, i);"),
    _m("ko-ri", "if (nibble(w, i) != 0)\n            n++;",
       "if (nibble(w, i) > 1)\n            n++;"),
    _m("ko-ri8", "for (i = 0; i < 8; i++)\n        if (nibble",
       "for (i = 0; i < 7; i++)\n        if (nibble"),
    _m("ko-gr7", "return (uint32_t)i < 8u ? nibble(rd32(s), i) : 0;",
       "return (uint32_t)i < 7u ? nibble(rd32(s), i) : 0;"),
    _m("ko-gr0", "return (uint32_t)i < 8u ? nibble(rd32(s), i) : 0;",
       "return (uint32_t)i < 8u ? nibble(rd32(s), i) : 1;"),
    _m("ko-sr7", "    if ((uint32_t)i < 8u)\n        wr32(s, set_nibble",
       "    if ((uint32_t)i < 7u)\n        wr32(s, set_nibble"),
    _m("ko-sp", "wr32(s + 4, set_nibble(rd32(s + 4), i, pos));",
       "wr32(s + 4, set_nibble(rd32(s), i, pos));"),
    _m("ko-sp7", "    if ((uint32_t)i < 8u)\n        wr32(s + 4,",
       "    if ((uint32_t)i < 7u)\n        wr32(s + 4,"),
    _m("ko-gp", "return (uint32_t)i < 8u ? nibble(rd32(s + 4), i) : 0;",
       "return (uint32_t)i < 8u ? nibble(rd32(s), i) : 0;"),
    _m("ko-gp7", "return (uint32_t)i < 8u ? nibble(rd32(s + 4), i) : 0;",
       "return (uint32_t)i < 7u ? nibble(rd32(s + 4), i) : 0;"),
    _m("ko-st0", "    if (ko_state_get_race_index(s) == 0)\n        return EVENT_UNTRIED;",
       "    if (ko_state_get_race_index(s) == 1)\n        return EVENT_UNTRIED;"),
    _m("ko-f0", "if (first == 0)\n        return EVENT_INPROGRESS;",
       "if (first == 0)\n        return EVENT_UNTRIED;"),
    _m("ko-lt", "return goal->nData < (uint32_t)first ?",
       "return goal->nData <= (uint32_t)first ?"),
    _m("sc-11", "s[11] = (uint8_t)dash;", "s[11] = (uint8_t)skin;"),
    _m("sc-10", "s[10] = (uint8_t)skin;", "s[10] = (uint8_t)dash;"),
    _m("sc-8", "memcpy(s + 8, &c, 2);", "memcpy(s + 8, &c, 1);"),
    _m("gc-c", "    int16_t c;\n\n    memcpy(&c, s + 8, 2);",
       "    uint16_t c;\n\n    memcpy(&c, s + 8, 2);"),
    _m("gc-s", "*skin = (int8_t)s[10];", "*skin = s[10];"),
    _m("gc-d", "*dash = (int8_t)s[11];", "*dash = s[11];"),
    _m("ko-seed", "uint32_t ko_state_get_seed(const uint8_t *s)\n{\n"
       "    return rd32(s + 12);", "uint32_t ko_state_get_seed(const uint8_t "
       "*s)\n{\n    return rd32(s + 8);"),
    _m("ko-ns", "void ko_state_new_seed(uint8_t *s)\n{\n    wr32(s + 12,",
       "void ko_state_new_seed(uint8_t *s)\n{\n    wr32(s + 8,"),
    _m("tr-r", "for (i = 7; i >= 0; i--)", "for (i = 7; i > 0; i--)"),
    _m("tr-u", "s[i] = (uint8_t)(races * kTournamentPoints[i]);",
       "s[i] = (uint8_t)(races + kTournamentPoints[i]);"),
    _m("tp-0", "{ 10, 6, 4, 3, 2, 1, 0, 0 }", "{ 9, 6, 4, 3, 2, 1, 0, 0 }"),
    _m("tp-5", "{ 10, 6, 4, 3, 2, 1, 0, 0 }", "{ 10, 6, 4, 3, 2, 2, 0, 0 }"),
    _m("tp-6", "{ 10, 6, 4, 3, 2, 1, 0, 0 }", "{ 10, 6, 4, 3, 2, 1, 1, 0 }"),
    _m("tp-7", "{ 10, 6, 4, 3, 2, 1, 0, 0 }", "{ 10, 6, 4, 3, 2, 1, 0, 1 }"),
    _m("tp-8", "return (uint32_t)pos < 8u ? kTournamentPoints[pos] : 0;",
       "return (uint32_t)pos < 7u ? kTournamentPoints[pos] : 0;"),
    _m("tp-past", "return (uint32_t)pos < 8u ? kTournamentPoints[pos] : 0;",
       "return (uint32_t)pos < 8u ? kTournamentPoints[pos] : 1;"),
    _m("tri-le", "for (i = 0; i <= opponents; i++)",
       "for (i = 0; i < opponents; i++)"),
    _m("tri-8", "for (i = 0; i < 8; i++)\n        sum += s[i];",
       "for (i = 0; i < 7; i++)\n        sum += s[i];"),
    _m("tri-0", "    if (each == 0)\n        return 0;\n", ""),
    _m("tri-div", "return sum / each;", "return sum / (each + 1);"),
    _m("rr-lt", "if (mine < s[j])\n            rank++;",
       "if (mine <= s[j])\n            rank++;"),
    _m("rr-eq", "else if (s[j] == mine && j < i)",
       "else if (s[j] == mine && j > i)"),
    _m("rr-1", "int32_t rank = 1;", "int32_t rank = 0;"),
    _m("ur-0", "return tournament_state_racer_rank(s, 0);",
       "return tournament_state_racer_rank(s, 1);"),
    _m("tst-0", "if (index == 0)\n        return EVENT_UNTRIED;",
       "if (index == 1)\n        return EVENT_UNTRIED;"),
    _m("tst-lt", "if (index < races)\n        return EVENT_INPROGRESS;",
       "if (index <= races)\n        return EVENT_INPROGRESS;"),
    _m("tst-g", "return goal->nData < (uint32_t)tournament_state_user_rank(s)",
       "return goal->nData <= (uint32_t)tournament_state_user_rank(s)"),
    _m("tr-seed", "uint32_t tournament_state_get_seed(const uint8_t *s)\n{\n"
       "    return rd32(s + 12);", "uint32_t tournament_state_get_seed(const "
       "uint8_t *s)\n{\n    return rd32(s + 8);"),
    _m("tr-ns", "void tournament_state_new_seed(uint8_t *s)\n{\n    wr32(s + 12,",
       "void tournament_state_new_seed(uint8_t *s)\n{\n    wr32(s + 8,"),
    # ---- EventInfo's arrays
    _m("gc-neg", "if (i < 0 || i >= e->nCars)", "if (i >= e->nCars)"),
    _m("gc-ge", "if (i < 0 || i >= e->nCars)", "if (i < 0 || i > e->nCars)"),
    _m("gc-4", "pCars + 4 * event_array(e, 68, i)",
       "pCars + 2 * event_array(e, 68, i)"),
    _m("gc-68", "event_array(e, 68, i)", "event_array(e, 70, i)"),
    _m("gg-neg", "if (i < 0 || i >= e->nGoals)", "if (i >= e->nGoals)"),
    _m("gg-ge", "if (i < 0 || i >= e->nGoals)", "if (i < 0 || i > e->nGoals)"),
    _m("gg-124", "event_array(e, 124, i)", "event_array(e, 126, i)"),
    _m("gt-neg", "if (i < 0 || i >= e->nTracks)", "if (i >= e->nTracks)"),
    _m("gt-ge", "if (i < 0 || i >= e->nTracks)", "if (i < 0 || i > e->nTracks)"),
    _m("gt-4", "pTracks + 4 * event_array(e, 108, i)",
       "pTracks + 2 * event_array(e, 108, i)"),
    _m("gt-108", "event_array(e, 108, i)", "event_array(e, 110, i)"),
    _m("gr-neg", "if (i < 0 || i >= e->nRewards)", "if (i >= e->nRewards)"),
    _m("gr-ge", "if (i < 0 || i >= e->nRewards)",
       "if (i < 0 || i > e->nRewards)"),
    _m("gr-140", "event_array(e, 140, i)", "event_array(e, 142, i)"),
    _m("go-neg", "if (i < 0 || i >= e->nOpponents)", "if (i >= e->nOpponents)"),
    _m("go-ge", "if (i < 0 || i >= e->nOpponents)",
       "if (i < 0 || i > e->nOpponents)"),
    _m("go-4", "pOpponents + 4 * event_array(e, 156, i)",
       "pOpponents + 2 * event_array(e, 156, i)"),
    _m("go-156", "event_array(e, 156, i)", "event_array(e, 158, i)"),
    _m("rk-lap", "if (e->nType == EVENT_RACE || e->nType == EVENT_LAP_KNOCKOUT)",
       "if (e->nType == EVENT_RACE)"),
    _m("tst-t", "return e->nType == EVENT_TOURNAMENT ? event_info_state(e)",
       "return e->nType == EVENT_RACE_KNOCKOUT ? event_info_state(e)"),
    _m("kst-t", "return e->nType == EVENT_RACE_KNOCKOUT ? event_info_state(e)",
       "return e->nType == EVENT_TOURNAMENT ? event_info_state(e)"),
    _m("tms-tt", "if (e->nType == EVENT_TIME_TRIAL\n        ||",
       "if (e->nType == EVENT_RACE\n        ||"),
    _m("tms-p2p", "(e->nType >= EVENT_POINT2POINT && e->nType <= EVENT_BE_A_COP)",
       "(e->nType > EVENT_POINT2POINT && e->nType <= EVENT_BE_A_COP)"),
    _m("tms-cop", "(e->nType >= EVENT_POINT2POINT && e->nType <= EVENT_BE_A_COP)",
       "(e->nType >= EVENT_POINT2POINT && e->nType < EVENT_BE_A_COP)"),
    # ---- RewardEarned, the state size, the finish string
    _m("re-null", "    if (r == NULL)\n        return 0;\n", ""),
    _m("re-st", "if (event_info_get_status(e, NULL) < EVENT_FAILED)\n"
       "        return 0;", "if (event_info_get_status(e, NULL) <= EVENT_FAILED)"
       "\n        return 0;"),
    _m("re-rk", "return !(r->nData < (int32_t)event_info_rank_state(e)[0]);",
       "return !(r->nData <= (int32_t)event_info_rank_state(e)[0]);"),
    _m("re-tm", "return !(r->nData < (int32_t)rd32(event_info_time_state(e)));",
       "return !(r->nData <= (int32_t)rd32(event_info_time_state(e)));"),
    _m("re-ko", "return !(r->nData < ko_state_get_rank(event_info_ko_state(e), 0));",
       "return !(r->nData <= ko_state_get_rank(event_info_ko_state(e), 0));"),
    _m("re-tr", "return !((uint32_t)r->nData < (uint32_t)tournament_state_user",
       "return !((uint32_t)r->nData <= (uint32_t)tournament_state_user"),
    _m("re-trs", "return !((uint32_t)r->nData < (uint32_t)tournament_state_user",
       "return !((int32_t)r->nData < (int32_t)tournament_state_user"),
    _m("re-def", "    default:\n        return 0;\n    }\n}\n\nint32_t "
       "event_info_get_state_size", "    default:\n        return 1;\n    }\n}"
       "\n\nint32_t event_info_get_state_size"),
    _m("re-lap", "    case EVENT_LAP_KNOCKOUT:\n        return !(r->nData",
       "        return !(r->nData"),
    _m("re-cop", "    case EVENT_BE_A_COP:\n        return !(r->nData",
       "        return !(r->nData"),
    _m("ss-4", "        return 4;\n    case EVENT_RACE_KNOCKOUT:",
       "        return 8;\n    case EVENT_RACE_KNOCKOUT:"),
    _m("ss-16", "        return 16;\n    default:\n        return 1;",
       "        return 12;\n    default:\n        return 1;"),
    _m("ss-1", "    default:\n        return 1;\n    }\n}\n\n// A place's",
       "    default:\n        return 2;\n    }\n}\n\n// A place's"),
    _m("ss-cop", "    case EVENT_BE_A_COP:\n        return 4;", "        return 4;"),
    _m("fp-16", "(uint32_t)place < 16u", "(uint32_t)place < 15u"),
    _m("fp-9", "(uint32_t)place < 16u", "(uint32_t)place < 9u"),
    _m("fp-null", "if (s == NULL)\n        s = \"\";", "if (s == NULL)\n        s = \"?\";"),
    _m("fs-t8", "61007, 61008, 0,", "61007, 61008, 61009,"),
    _m("fs-t0", "    61000, 61001,", "    61001, 61001,"),
    _m("fs-t62", "62000, 62001, 62002", "62001, 62001, 62002"),
    _m("fs-st", "if (event_info_get_status(e, NULL) < EVENT_FAILED) {",
       "if (event_info_get_status(e, NULL) <= EVENT_FAILED) {"),
    _m("fs-clr", "        sFinishString[0] = '\\0';\n        return sFinishString;",
       "        return sFinishString;"),
    _m("fs-rk", "finish_place(s[0]);", "finish_place(s[1]);"),
    _m("fs-ko", "finish_place(ko_state_get_rank(s, 0));",
       "finish_place(ko_state_get_rank(s, 1));"),
    _m("fs-tr", "finish_place(tournament_state_user_rank(s));",
       "finish_place(tournament_state_racer_rank(s, 1));"),
    _m("fs-tm", "timer_print_to_string(&t, sFinishString, 0,",
       "timer_print_to_string(&t, sFinishString, 1,"),
    _m("fs-lang", "? gCurrLanguageFn() : 0);", "? gCurrLanguageFn() + 1 : 0);"),
    _m("fs-lap", "    case EVENT_LAP_KNOCKOUT:\n        finish_place(s[0]);",
       "        finish_place(s[0]);"),
    _m("fs-cop", "    case EVENT_BE_A_COP:\n        t.PackedTime",
       "        t.PackedTime"),
    # ---- IsLastOpen, GetStatus
    _m("lo-31", "n <= 31; n++) {\n        EventInfo *hp = event_tree_get_event_"
       "number(gHotPursuitTree, n);\n        EventInfo *ch = event_tree_get_"
       "event_number(gChampionshipTree, n);", "n <= 30; n++) {\n        "
       "EventInfo *hp = event_tree_get_event_number(gHotPursuitTree, n);\n"
       "        EventInfo *ch = event_tree_get_event_number(gChampionshipTree, "
       "n);"),
    _m("lo-hpt", "|| mine != gHotPursuitTree))", "|| mine != gChampionshipTree))"),
    _m("lo-cht", "|| mine != gChampionshipTree))", "|| mine != gHotPursuitTree))"),
    _m("lo-hpn", "\n            && (n != e->nNumber || mine != gHotPursuitTree))",
       ")"),
    _m("lo-chn", "\n            && (n != e->nNumber || mine != gChampionshipTree))",
       ")"),
    _m("lo-ult", "NULL) > EVENT_LOCKED)\n        return 0;",
       "NULL) > EVENT_UNTRIED)\n        return 0;"),
    _m("lo-ret", "return event_info_get_status(e, NULL) != EVENT_PASSED;\n}",
       "return event_info_get_status(e, NULL) == EVENT_PASSED;\n}"),
    _m("gs-all", "    if (gUnlockAllEvents != 0)\n        return EVENT_PASSED;",
       "    if (gUnlockAllEvents != 0)\n        return EVENT_FAILED;"),
    _m("gs-31", "if (e->nNumber == 31) {", "if (e->nNumber == 30) {"),
    _m("gs-ch6", "egg = egg_is_on(6);", "egg = egg_is_on(7);"),
    _m("gs-hp7", "EVENT_TREE_HOT_PURSUIT && egg_is_on(7))",
       "EVENT_TREE_HOT_PURSUIT && egg_is_on(6))"),
    _m("gs-cht", "if (tree->nType == EVENT_TREE_CHAMPIONSHIP)\n            egg",
       "if (tree->nType == EVENT_TREE_HOT_PURSUIT)\n            egg"),
    _m("gs-hpt", "if (tree->nType == EVENT_TREE_HOT_PURSUIT && egg_is_on(7))",
       "if (tree->nType == EVENT_TREE_CHAMPIONSHIP && egg_is_on(7))"),
    _m("gs-ult", "if (e->nNumber == EVENT_ULTIMATE) {\n            int32_t n;",
       "if (e->nNumber == 31) {\n            int32_t n;"),
    _m("gs-31b", "            for (n = 1; n <= 31; n++) {\n                EventInfo",
       "            for (n = 1; n <= 30; n++) {\n                EventInfo"),
    _m("gs-hpe", "event_info_get_status(hp, NULL) != EVENT_PASSED)\n"
       "                    return egg != 0;", "event_info_get_status(hp, NULL)"
       " != EVENT_PASSED)\n                    return egg == 0;"),
    _m("gs-che", "event_info_get_status(ch, NULL) != EVENT_PASSED)\n"
       "                    return egg != 0;", "event_info_get_status(ch, NULL)"
       " != EVENT_PASSED)\n                    return egg == 0;"),
    _m("gs-hpp", "event_info_get_status(hp, NULL) != EVENT_PASSED)\n"
       "                    return", "event_info_get_status(hp, NULL) == "
       "EVENT_LOCKED)\n                    return"),
    _m("gs-ng", "} else if (e->nGoals > 0) {", "} else if (e->nGoals >= 0) {"),
    _m("gs-or", "passed |= event_goal_passed(", "passed = event_goal_passed("),
    _m("gs-np", "if (!passed)\n                return egg != 0;",
       "if (!passed)\n                return egg == 0;"),
    _m("gs-lap", "    case EVENT_LAP_KNOCKOUT:\n        status = rank_state",
       "        status = rank_state"),
    _m("gs-cop", "    case EVENT_BE_A_COP:\n        status = time_state",
       "        status = time_state"),
    _m("gs-trn", "tournament_state_get_status(s, goal, e->nTracks,",
       "tournament_state_get_status(s, goal, e->nOpponents,"),
    _m("gs-tro", "                                             e->nOpponents);",
       "                                             e->nTracks);"),
    _m("gs-def", "    default:\n        status = EVENT_UNTRIED;",
       "    default:\n        status = EVENT_LOCKED;"),
    _m("gs-egg", "return status != 0 ? status : EVENT_UNTRIED;", "return status;"),
    _m("gs-egg0", "    if (egg)\n        return status", "    if (!egg)\n        return status"),
    # ---- the rest of EventInfo
    _m("ri-ko", "    if (e->nType == EVENT_RACE_KNOCKOUT)\n        return ko_state_get_race_index(s);",
       "    if (e->nType == EVENT_RACE)\n        return ko_state_get_race_index(s);"),
    _m("ri-tr", "return tournament_state_get_race_index(s, e->nOpponents);",
       "return tournament_state_get_race_index(s, e->nTracks);"),
    _m("rc-ko", "        return e->nOpponents;\n    if (e->nType == EVENT_TOURNAMENT)",
       "        return e->nTracks;\n    if (e->nType == EVENT_TOURNAMENT)"),
    _m("rc-1", "        return e->nTracks;\n    return 1;",
       "        return e->nTracks;\n    return 0;"),
    _m("rst-lap", "    case EVENT_LAP_KNOCKOUT:\n        rank_state_reset(s);",
       "        rank_state_reset(s);"),
    _m("rst-cop", "    case EVENT_BE_A_COP:\n        time_state_reset(s);",
       "        time_state_reset(s);"),
    _m("rst-ko", "        ko_state_reset(s);", "        tournament_state_reset(s);"),
    _m("us-ko1", "ko_state_unlock(s, goal, e->nOpponents + 1);",
       "ko_state_unlock(s, goal, e->nOpponents);"),
    _m("us-tr", "tournament_state_unlock(s, goal, e->nTracks);",
       "tournament_state_unlock(s, goal, e->nOpponents);"),
    _m("us-lap", "    case EVENT_LAP_KNOCKOUT:\n        rank_state_unlock(s, goal);",
       "        rank_state_unlock(s, goal);"),
    _m("us-cop", "    case EVENT_BE_A_COP:\n        time_state_unlock(s, goal);",
       "        time_state_unlock(s, goal);"),
    _m("us-goal", "if (s == NULL || goal == NULL)\n        return;",
       "if (s == NULL)\n        return;"),
    _m("mt-3", "(uint32_t)(uint8_t)e->nType - 3u < 2u",
       "(uint32_t)(uint8_t)e->nType - 3u < 3u"),
    _m("mt-2", "(uint32_t)(uint8_t)e->nType - 3u < 2u",
       "(uint32_t)(uint8_t)e->nType - 2u < 2u"),
    _m("esc-ko", "if (e->nType == EVENT_RACE_KNOCKOUT)\n        ko_state_set_",
       "if (e->nType == EVENT_RACE)\n        ko_state_set_"),
    _m("esc-tr", "else if (e->nType == EVENT_TOURNAMENT)\n        tournament_state_set_",
       "else if (e->nType == EVENT_RACE)\n        tournament_state_set_"),
    _m("egc-ko", "if (e->nType == EVENT_RACE_KNOCKOUT)\n        ko_state_get_sel",
       "if (e->nType == EVENT_RACE)\n        ko_state_get_sel"),
    _m("egc-tr", "else if (e->nType == EVENT_TOURNAMENT)\n        tournament_state_get_sel",
       "else if (e->nType == EVENT_RACE)\n        tournament_state_get_sel"),
    _m("gp-ev", "event_tree_get_event_number(tree, g->nEvent);",
       "event_tree_get_event_number(tree, g->nEvent + 1);"),
    _m("gp-st", "event_info_get_status(e, g) == EVENT_PASSED;",
       "event_info_get_status(e, g) >= EVENT_FAILED;"),
    # ---- EventTree
    _m("ct-id", "m[i] = (i % 5 == 0) ? 1.0f : 0.0f;",
       "m[i] = (i % 4 == 0) ? 1.0f : 0.0f;"),
    _m("ct-show", "t->bShowLines = 1;", "t->bShowLines = 0;"),
    _m("ct-tex6", "for (i = 0; i < 6; i++) {\n        uint32_t hash",
       "for (i = 0; i < 5; i++) {\n        uint32_t hash"),
    _m("ct-tex1", "gGetTextureInfoFn(hash, 1, 0)", "gGetTextureInfoFn(hash, 0, 0)"),
    _m("ct-memset", "    memset(t, 0, sizeof *t);\n", ""),
    _m("ct-name", "    event_tree_set_name(t, name);\n", ""),
    _m("dt-free", "    if (t->pName != NULL)\n        bFree(t->pName);\n"
       "    release_handle(t);", "    release_handle(t);"),
    _m("dt-rel", "    release_handle(t);\n", ""),
    _m("dt-flag", "    if (flags & 1)\n        bFree(t);",
       "    if (flags & 2)\n        bFree(t);"),
    _m("sn-free", "    if (t->pName != NULL)\n        bFree(t->pName);\n"
       "    if (name == NULL) {", "    if (name == NULL) {"),
    _m("sn-null0", "        t->pName = NULL;\n        return 0;",
       "        t->pName = NULL;\n        return 1;"),
    _m("sn-len", "n = strlen(name) + 1;", "n = strlen(name) + 2;"),
    _m("sn-line", "\"bWare/inc/bWare.hpp\", 666, 16);",
       "\"bWare/inc/bWare.hpp\", 667, 16);"),
    _m("sn-hpe3", "bVersionE3 ? \"Hot Pursuit E3\" : \"Hot Pursuit\"",
       "bVersionE3 ? \"Hot Pursuit\" : \"Hot Pursuit E3\""),
    _m("sn-che3", "bVersionE3 ? \"Championship E3\" : \"Championship\"",
       "bVersionE3 ? \"Championship\" : \"Championship E3\""),
    _m("sn-hpg", "gHotPursuitTree = t;", "gChampionshipTree = t;"),
    _m("sn-chg", "gChampionshipTree = t;", "gHotPursuitTree = t;"),
    _m("sn-hpt", "        t->nType = EVENT_TREE_HOT_PURSUIT;\n        return 1;",
       "        t->nType = EVENT_TREE_CHAMPIONSHIP;\n        return 1;"),
    _m("sn-cht", "        t->nType = EVENT_TREE_CHAMPIONSHIP;\n        return 1;",
       "        t->nType = EVENT_TREE_HOT_PURSUIT;\n        return 1;"),
    _m("sn-hpr", "        t->nType = EVENT_TREE_HOT_PURSUIT;\n        return 1;",
       "        t->nType = EVENT_TREE_HOT_PURSUIT;\n        return 0;"),
    _m("sn-chr", "        t->nType = EVENT_TREE_CHAMPIONSHIP;\n        return 1;",
       "        t->nType = EVENT_TREE_CHAMPIONSHIP;\n        return 0;"),
    _m("sn-ret", "        return 1;\n    }\n    return 0;\n}\n\n// Retail reads",
       "        return 1;\n    }\n    return 1;\n}\n\n// Retail reads"),
    _m("gn-null", "    if (t == NULL)\n        return NULL;\n    for (i = 0; "
       "i < t->nEvents; i++)\n        if (t->pEvents[i].nNumber == n)",
       "    for (i = 0; i < t->nEvents; i++)\n        if (t->pEvents[i]"
       ".nNumber == n)"),
    _m("gn-lt", "for (i = 0; i < t->nEvents; i++)\n        if (t->pEvents[i].nNumber == n)",
       "for (i = 0; i < t->nEvents - 1; i++)\n        if (t->pEvents[i].nNumber == n)"),
    _m("gi-neg", "(int32_t)(e - t->pEvents) : -1;", "(int32_t)(e - t->pEvents) : 0;"),
    _m("se-cur", "t->pCurrentEvent = e;", "t->pCurrentEvent = NULL;"),
    _m("se-n", "    t->nEvents = n;\n    for", "    t->nEvents = n - 1;\n    for"),
    _m("se-h", "e[i].TreeHandle = handle;", "e[i].TreeHandle = handle + 1;"),
    _m("cs-ss0", "    (void)size;\n    t->nStateSize = 0;\n", "    (void)size;\n"),
    _m("cs-al", "if (event_info_get_state_size(e) < align)\n            continue;",
       "if (event_info_get_state_size(e) <= align)\n            continue;"),
    _m("cs-ge", "if (event_info_get_state_size(e) >= align)\n            continue;",
       "if (event_info_get_state_size(e) > align)\n            continue;"),
    _m("cs-u1", "            continue;\n        }\n        e->StateOffset = base + "
       "(uint32_t)t->nStateSize;\n        t->nStateSize = (",
       "        }\n        e->StateOffset = base + (uint32_t)t->nStateSize;\n"
       "        t->nStateSize = ("),
    _m("cs-u2", "            continue;\n        }\n        e->StateOffset = base + "
       "(uint32_t)t->nStateSize;\n        t->nStateSize +=",
       "        }\n        e->StateOffset = base + (uint32_t)t->nStateSize;\n"
       "        t->nStateSize +="),
    _m("cs-round", "(t->nStateSize + event_info_get_state_size(e) - 1\n",
       "(t->nStateSize + event_info_get_state_size(e)\n"),
    _m("cs-set1", "        if (e->nNumber == EVENT_ULTIMATE)\n            Fred."
       "pUltimateState = e->StateOffset;\n    }\n    for", "    }\n    for"),
    _m("cs-set2", "        t->nStateSize += event_info_get_state_size(e);\n"
       "        if (e->nNumber == EVENT_ULTIMATE)\n            Fred."
       "pUltimateState = e->StateOffset;", "        t->nStateSize += "
       "event_info_get_state_size(e);"),
    _m("cs-sz2", "t->nStateSize += event_info_get_state_size(e);",
       "t->nStateSize += 1;"),
    _m("cs-ul1", "        if (e->nNumber == EVENT_ULTIMATE && Fred.pUltimateState"
       " != 0) {\n            e->StateOffset = Fred.pUltimateState;\n"
       "            continue;\n        }\n        e->StateOffset = base + "
       "(uint32_t)t->nStateSize;\n        t->nStateSize = (",
       "        e->StateOffset = base + (uint32_t)t->nStateSize;\n"
       "        t->nStateSize = ("),
    _m("ucn", "event_info_unlock_state(t->pCurrentLeaf->pInfo);",
       "event_info_reset_state(t->pCurrentLeaf->pInfo);"),
    _m("fr-t", "if (r->nType == type && r->nValue1 == value",
       "if (r->nValue1 == value"),
    _m("fr-v1", "r->nValue1 == value", "r->nValue2 == value"),
    _m("fr-car", "(type == REWARD_CAR || r->nValue2 == direction)",
       "(r->nValue2 == direction)"),
    _m("fr-dir", "(type == REWARD_CAR || r->nValue2 == direction)",
       "(type == REWARD_CAR || 1)"),
    _m("fr-j", "                return j;", "                return j + 1;"),
    _m("fr-null", "    *event = NULL;\n    return -1;", "    return -1;"),
    _m("icu-0", "return i >= 0 ? event_info_reward_earned(e, i) : 0;",
       "return i >= 0 ? event_info_reward_earned(e, i) : 1;"),
    _m("itu-1", "return i >= 0 ? event_info_reward_earned(e, i) : 1;",
       "return i >= 0 ? event_info_reward_earned(e, i) : 0;"),
    # ---- over the trees
    _m("ice", "if (event_tree_car_is_a_reward(t, car))",
       "if (!event_tree_car_is_a_reward(t, car))"),
    _m("icu", "if (event_tree_is_car_unlocked(t, car))",
       "if (!event_tree_is_car_unlocked(t, car))"),
    _m("fec", "        if (e != NULL)\n            return e;\n    }\n    return "
       "NULL;\n}\n\nEventInfo *find_event_that_track", "        if (e == NULL)"
       "\n            return e;\n    }\n    return NULL;\n}\n\nEventInfo "
       "*find_event_that_track"),
    _m("fet", "        if (e != NULL)\n            return e;\n    }\n    return "
       "NULL;\n}\n\nint32_t is_track", "        if (e == NULL)\n            "
       "return e;\n    }\n    return NULL;\n}\n\nint32_t is_track"),
    _m("ita", "if (event_tree_track_is_a_reward(t, track, direction))\n"
       "            return 1;", "if (!event_tree_track_is_a_reward(t, track, "
       "direction))\n            return 1;"),
    _m("itu", "return event_tree_is_track_unlocked(t, track, direction) != 0;",
       "return event_tree_is_track_unlocked(t, track, direction) == 0;"),
    _m("itu-any", "direction) != 0;\n    return 1;", "direction) != 0;\n    return 0;"),
    _m("nc-64", "for (car = 0; car < 64; car++)", "for (car = 0; car < 63; car++)"),
    _m("nc-0", "for (car = 0; car < 64; car++)", "for (car = 1; car < 64; car++)"),
    _m("lock", "    FOR_EACH_TREE(t)\n        event_tree_reset_state(t);",
       "    FOR_EACH_TREE(t)\n        event_tree_unlock_state(t);"),
    _m("unlock", "    FOR_EACH_TREE(t)\n        event_tree_unlock_state(t);",
       "    FOR_EACH_TREE(t)\n        event_tree_reset_state(t);"),
    _m("bu-ch", "event_tree_get_event_number(gChampionshipTree,\n"
       "                                                EVENT_ULTIMATE);",
       "event_tree_get_event_number(gHotPursuitTree,\n"
       "                                                EVENT_ULTIMATE);"),
    _m("bu-st", "    if (status != EVENT_PASSED)\n        return 0;",
       "    if (status != EVENT_FAILED)\n        return 0;"),
    _m("bu-eq", "return event_info_get_status(hp, NULL) == status;",
       "return event_info_get_status(hp, NULL) != status;"),
    _m("ge-cmp", "t->pName != NULL ? t->pName : \"\") == 0)",
       "t->pName != NULL ? t->pName : \"\") != 0)"),
    _m("ge-empty", "t->pName != NULL ? t->pName : \"\")",
       "t->pName != NULL ? t->pName : \"-\")"),
    # ---- the loader and unloader
    _m("ld-chk", "        return 0;\n    t = (EventTree *)bMalloc(",
       "        return 1;\n    t = (EventTree *)bMalloc("),
    _m("ld-line", "eventtree.cpp\", 2186, 16);", "eventtree.cpp\", 2187, 16);"),
    _m("ld-link", "    t->Node.prev = gEventTrees.prev;\n    gEventTrees.prev->next"
       " = &t->Node;\n    gEventTrees.prev = &t->Node;\n    t->Node.next = "
       "&gEventTrees;", "    t->Node.next = gEventTrees.next;\n    "
       "gEventTrees.next->prev = &t->Node;\n    gEventTrees.next = &t->Node;\n"
       "    t->Node.prev = &gEventTrees;"),
    _m("ld-end", "c < chunk + 8 + bchunk_u32(chunk + 4);",
       "c < chunk + bchunk_u32(chunk + 4);"),
    _m("ld-name", "if (!event_tree_set_name(t, (const char *)data)) {",
       "if (event_tree_set_name(t, (const char *)data)) {"),
    _m("ld-d3", "                event_tree_destruct(t, 3);",
       "                event_tree_destruct(t, 2);"),
    _m("ld-c2", "t->nCars = (int32_t)(size >> 2);", "t->nCars = (int32_t)(size >> 3);"),
    _m("ld-t2", "t->nTracks = (int32_t)(size >> 2);",
       "t->nTracks = (int32_t)(size >> 3);"),
    _m("ld-g3", "t->nGoals = (int32_t)(size >> 3);", "t->nGoals = (int32_t)(size >> 2);"),
    _m("ld-r3", "t->nRewards = (int32_t)(size >> 3);",
       "t->nRewards = (int32_t)(size >> 2);"),
    _m("ld-o2", "t->nOpponents = (int32_t)(size >> 2);",
       "t->nOpponents = (int32_t)(size >> 3);"),
    _m("ld-k1", "        case 1:\n", "        case 2:\n"),
    _m("ld-k01", "case 0x00034a01u:", "case 0x00034a11u:"),
    _m("ld-k02", "case 0x00034a02u:", "case 0x00034a12u:"),
    _m("ld-k03", "case 0x00034a03u:", "case 0x00034a13u:"),
    _m("ld-k04", "case 0x00034a04u:", "case 0x00034a14u:"),
    _m("ld-k05", "case 0x00034a05u:", "case 0x00034a15u:"),
    _m("ld-k06", "case 0x00034a06u:", "case 0x00034a16u:"),
    _m("ld-chs", "event_tree_calc_state_pointers(t, Fred.ChampionshipState,",
       "event_tree_calc_state_pointers(t, Fred.HotPursuitState,"),
    _m("ld-hps", "event_tree_calc_state_pointers(t, Fred.HotPursuitState,",
       "event_tree_calc_state_pointers(t, Fred.ChampionshipState,"),
    _m("ld-al1", "EVENT_TREE_STATE_SIZE, 4);\n            else if",
       "EVENT_TREE_STATE_SIZE, 1);\n            else if"),
    _m("ld-al2", "EVENT_TREE_STATE_SIZE, 4);\n            break;",
       "EVENT_TREE_STATE_SIZE, 1);\n            break;"),
    _m("ld-cht", "            if (t->nType == EVENT_TREE_CHAMPIONSHIP)\n"
       "                event_tree_calc", "            if (t->nType == "
       "EVENT_TREE_HOT_PURSUIT)\n                event_tree_calc"),
    _m("ld-ret", "    }\n    return 1;\n}\n\nint unloader_event_tree",
       "    }\n    return 0;\n}\n\nint unloader_event_tree"),
    _m("ul-chk", "int unloader_event_tree(uint8_t *chunk)\n{\n    if (bchunk_u32"
       "(chunk) != EVENT_TREE_CHUNK)\n        return 0;", "int unloader_event_"
       "tree(uint8_t *chunk)\n{\n    if (bchunk_u32(chunk) != EVENT_TREE_CHUNK)"
       "\n        return 1;"),
    _m("ul-w", "    gEventTreeWord16704 = NULL;\n", ""),
    _m("ul-ch", "    gChampionshipTree = NULL;\n", ""),
    _m("ul-hp", "    gHotPursuitTree = NULL;\n", ""),
    _m("ul-d3", "        event_tree_destruct(t, 3);\n    }",
       "        event_tree_destruct(t, 2);\n    }"),
    _m("ul-ret", "        event_tree_destruct(t, 3);\n    }\n    return 1;",
       "        event_tree_destruct(t, 3);\n    }\n    return 0;"),
]

EQUIVALENT = {
    # The names bStrICmp compares are a tree's against "Hot Pursuit",
    # "Championship" and their E3s, and a question against the trees in
    # the list, which only those names load under: no Z on either side.
    "ic-26": "no name compared has a Z",
    # The handles are 1 .. 8, so h - 1 is never 8.
    "eit-8": "no handle is past 8",
    # The eighth place's points are 0, as past the table.
    "tp-8": "kTournamentPoints[7] is 0",
    # The sum runs from place 0, whose 10 points make it at least 10; only
    # a negative count of opponents, which retail traps on, leaves it 0.
    "tri-0": "a tournament's points per race are at least 10",
    # Places past the table print "skip" on both sides, and the
    # translator always answers, so the "" is never reached.
    "fp-null": "no place past the table, and the translator answers",
    # Every state's status is untried or more, never 0 (locked), so the
    # egg's `status != 0 ? status : EVENT_UNTRIED` is status.
    "gs-egg": "no state's status is locked",
    "gs-egg0": "no state's status is locked",
    # Both resets clear the state's first eight bytes.
    "rst-ko": "ko and tournament resets write the same bytes",
    # The harness clears the loose tree and its bMalloc's blocks as the
    # model's do: the memset finds zeros.
    "ct-memset": "the record is zeros before the constructor on both sides",
}


def _check_mutations():
    texts = {}
    for name, f, old, new in MUTATIONS:
        if f not in texts:
            texts[f] = (ROOT / f).read_text()
        n = texts[f].count(old)
        assert n == 1, "%s: %d matches" % (name, n)
        assert old != new, name
    names = [m[0] for m in MUTATIONS]
    assert len(names) == len(set(names)), "duplicate mutation names"


def mutate_pass(only=None, jobs=None):
    _check_mutations()
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    indir = tempfile.TemporaryDirectory()
    d, lines, scp, dp = write_inputs(indir.name)
    base_lines = model_cached(lines, d.buf)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, dp, out)
        took = time.monotonic() - t0
        got = out.read_text(encoding="latin-1").splitlines()
        if diff(base_lines, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "eventtree_test",
        lambda exe, out: mutpar.run_exe([exe, scp, dp], out, limit),
        base_lines, diff, EQUIVALENT, jobs)
    indir.cleanup()
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

    with tempfile.TemporaryDirectory() as tmp:
        d, lines, scp, dp = write_inputs(tmp)
        t0 = time.monotonic()
        got = model_cached(lines, d.buf)
        print("model: %.1f s" % (time.monotonic() - t0), flush=True)
        exe = build_harness(tmp)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, dp, out)
        harness = out.read_text(encoding="latin-1").splitlines()

    if args.dump:
        dd = Path(args.dump)
        dd.parent.mkdir(parents=True, exist_ok=True)
        dd.with_suffix(".model").write_text(NL.join(got) + NL)
        dd.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(got, harness)
    print("%d ops, %d lines, %d differ" % (len(lines), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
