#!/usr/bin/env python3
"""Cross-check 3DS Files/source/fredevent.c, FrontendDatabase's event calls
(RE-6c-2), against the retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own code: GetEventTree (0x00185568),
DataEventSelectScreen's GetSelectedEvent, SetSelectedEvent and SetTreeType
(0x001f5d00 .. 0x001f5d50), FlushAvailableCars (0x00187928),
MakeEventCarsAvailable (0x00183d80), MaybeSetSelectedCarForMultiTrackEvent
(0x00184318), ContinueMultiTrackEvent (0x001843e8), RandomizeList
(0x00184578), PickRandomTracksForChallengeKnockout (0x001846a0),
SetupFakeRaceEventForChallengeKnockout (0x001849f0), and the list of the
events opened (0x001f72a8, 0x001f72b0, 0x001f7398, 0x001f7458), on Fred
(0x002fc050), TheRaceEvent (0x0031b600), the list after it (0x0031b7b0)
and TheRaceParameters (0x0031a898). Under them run EventTree.obj and
RaceEvent.obj (the loader, GetEventTree by name, GetEventNumber, IsLastOpen,
the selected car, EventKoState::Reset, ResetResults, GetStatus against a
goal, EventTree::SetRace), bWare's lists and strings. StartRace's event
word (0x001850e0) and SetupCarsForRace's opponent (0x00185a1c) are inline
in those two; the model writes their few instructions out over retail's
GetEventTree, GetEventNumber and IsLastOpen. The harness
(tools/src/fredevent_test.c) runs the port and prints the same lines.

**The data** is tools/eventtree_check.py's: the disc's two event trees
from FRONTB.BUN and the trees made up there; the stubs and tables of
tools/eventrace_check.py run under SetRace.

**The stubs**, logged and answered by the same rule on both sides:
GetTrackInfo (eventrace_check's 40 tracks, whose number, twin, point to
point and time of day the script sets), IsTrackUnlocked (a mask the script
sets, bit 2 x track + direction), bRandom (a queue, each answer held under
the range), FrontendPlayerInfo's SetCarAvailability, AssignCarOfType and
GetSelectedRideInfo (a ride the script sets), and StartRace. The list's
bMalloc'd nodes and array are made quietly and never freed: the port keeps
an array.

**Compared** are the stubs' logs and, after each call, what it changed:
both players' car statuses, both trees' states in Fred, TheRaceEvent from
aOldState on, its eight tracks, the select screen's four words and the
list of the events opened.

**What the script keeps away from**, where retail runs past what it owns
and the port stops (fredevent.c says where): a challenge knockout of more
than eight races, or of more races than the tracks on its list (retail
then takes the list's own head, on its stack); a knockout or tournament
without a state, whose selected car retail reads or writes at the bottom of
memory; ContinueMultiTrackEvent on any other event, whose car is retail's
stack's leftovers; StartRace's word on a number the tree does not have
(retail runs IsLastOpen on the bottom of memory); and a car record outside
the data. Both sides print "skip" or "none" for them.

    python tools/fredevent_check.py
    python tools/fredevent_check.py --mutate [--only a,b]
"""
import argparse
import os
import random
import struct
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eventrace_check as erc           # noqa: E402
import eventtree_check as etc           # noqa: E402
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import physicscar_check as pcc          # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/fredevent_test.c"
FE = "3DS Files/source/fredevent.c"
SOURCES = [HARNESS, FE, erc.ER, etc.ET, "3DS Files/source/raceevent.c",
           "3DS Files/source/raceparams.c", "3DS Files/source/bprintf.c"]
HARNESS_TIMEOUT = 120
DATA_FILES = etc.DATA_FILES

# ================================================================ the image

GP = erc.GP
TRE = erc.TRE                           # TheRaceEvent
OPENED = TRE + 432                      # the events opened
RP = erc.RP
FRED = etc.FRED
FRED_SIZE = 0x114e0
F_GAMETYPE = 0x1072c
F_CUREVENT = 0x10730
F_NPLAYERS = 0x10734
F_PLAYERS = 0x10738
F_SEL = 356
F_KO5 = 96 + 20                         # RaceKnockoutSetupData[5]
HIGHEST = GP - 21944                    # HighestTrackNumber
LISTNAME = 0x002b41a8                   # "tRandomlyPickableTrackInfo"
NTRACKS = erc.NTRACKS

S_MALLOC2 = 0x00257690                  # bMalloc(int, int)
S_VECDEL = 0x00114e90
S_NODEDTOR = 0x00187cd8
S_LISTDTOR = 0x00187c68
S_UNLOCKED = 0x0024b760
S_AVAIL = 0x001878e0
S_ASSIGN = 0x00187a68
S_START = 0x00184f68
S_RIDE = 0x00187af8

F_GETTREE = 0x00185568
F_GETSEL = 0x001f5d00
F_SETSEL = 0x001f5d28
F_SETTYPE = 0x001f5d50
F_FLUSH = 0x00187928
F_CARS = 0x00183d80
F_MAYBE = 0x00184318
F_CONT = 0x001843e8
F_PICK = 0x001846a0
F_FAKE = 0x001849f0
F_USETREE = 0x001841e8
F_LASTOPEN = 0x00200f98
F_OCLR = 0x001f72a8
F_OADD = 0x001f72b0
F_OPASSED = 0x001f7398
F_ONUM = 0x001f7458
F_NUM = etc.F_NUM
s8 = etc.s8


def s16(v):
    v &= 0xffff
    return v - 0x10000 if v >= 0x8000 else v


# ================================================================== model

class Model(erc.Model):
    def __init__(self, data):
        erc.Model.__init__(self, data)
        e = self.e

        def block(n):
            p = e.alloc(n, align=16)
            e.write(p, bytes(n))
            return p
        self.ride = block(16)
        self.outs = block(64)
        self.unl = bytes(64)
        self.own = {}
        for addr, fn in ((S_MALLOC2, self.s_quiet_alloc),
                         (S_VECDEL, self.s_nothing),
                         (S_NODEDTOR, self.s_nothing),
                         (S_LISTDTOR, self.s_nothing),
                         (S_UNLOCKED, self.s_unlocked),
                         (S_AVAIL, self.s_avail), (S_ASSIGN, self.s_assign),
                         (S_START, self.s_start), (S_RIDE, self.s_ride)):
            e.stub(addr, fn)

    def P(self, a):
        a &= M32
        if TRE <= a < TRE + 432:
            return "E%d" % (a - TRE)
        if OPENED <= a < OPENED + 52:
            return "O%d" % (a - OPENED)
        if a == self.ride:
            return "RIDE"
        if FRED <= a < FRED + FRED_SIZE:
            return "F%d" % (a - FRED)
        return erc.Model.P(self, a)

    # ---- stubs

    def s_malloc(self, em):
        if em.reg[5] & M32 == LISTNAME:
            return self.s_quiet(s32(em.reg[4]))
        return erc.Model.s_malloc(self, em)

    def s_quiet(self, size):
        p = self.e.alloc(max(size, 0) + 16, align=16)
        self.e.write(p, bytes(max(size, 0) + 16))
        return p

    def s_quiet_alloc(self, em):
        return self.s_quiet(s32(em.reg[4]))

    def s_nothing(self, em):
        return 0

    def s_random(self, em):
        n = s32(em.reg[4])
        q = self.randq.next() & M32
        r = q % n if n > 0 else s32(q)
        self.emit("  random %d -> %d" % (n, r))
        return r & M32

    def s_unlocked(self, em):
        t, d = s32(em.reg[4]), s32(em.reg[5])
        bit = (t & 0xff) * 2 + (d & 1)
        r = self.unl[bit >> 3] >> (bit & 7) & 1
        self.emit("  unlocked %d %d -> %d" % (t, d, r))
        return r

    def s_avail(self, em):
        self.emit("  avail %s %d %d %d %d" % (
            self.P(em.reg[4]), s32(em.reg[5]), s32(em.reg[6]),
            s32(em.reg[7]), s32(em.reg[8])))
        return 0

    def s_assign(self, em):
        self.emit("  assign %s %d %d %d %d" % (
            self.P(em.reg[4]), s32(em.reg[5]), s32(em.reg[6]),
            s32(em.reg[7]), s32(em.reg[8])))
        return 0

    def s_start(self, em):
        self.emit("  startrace %s" % self.P(em.reg[4]))
        return 0

    def s_ride(self, em):
        self.emit("  ride %s %d" % (self.P(em.reg[4]), s32(em.reg[5])))
        return self.ride

    # ---- printing

    def tre_dump(self):
        e, P = self.e, self.P
        self.emit("  ev %s %s %s" % (P(e.u32(TRE)), P(e.u32(TRE + 4)),
                                     e.read(TRE + 8, 424).hex()))

    def status_dump(self):
        e = self.e
        for p in range(2):
            base = FRED + F_PLAYERS + 1744 * p
            self.emit("  st%d %s" % (p, "".join(
                "%08x" % e.u32(base + 24 * i) for i in range(64))))

    def list_dump(self):
        self.emit("  list " + self.e.read(OPENED, 52).hex())

    def rec_print(self, rec):
        e = self.e
        s = self.P(rec)
        if rec and self.B <= rec and rec + 4 <= self.B + self.ndata:
            s += " " + e.read(rec, 4).hex()
        return s

    # ---- what both sides decide alike

    def selected(self):
        e = self.e
        t = self.call(F_GETTREE, FRED)
        if t == 0:
            return 0, 0
        sel = self.call(F_GETSEL, FRED + F_SEL, e.u32(t + 8))
        return t, self.call(F_NUM, t, sel)

    def stateless_multi(self, ev):
        e = self.e
        return (ev != 0 and s8(e.u8(ev + 41)) in (3, 4)
                and e.u32(ev + 4) == 0)

    def use_tree(self):
        return s32(self.e.u32(FRED + F_GAMETYPE)) in (8, 9)

    # ---- ops

    def run(self, a):
        e, P = self.e, self.P
        o = a[0]
        i = (lambda j: s32(int(a[j], 0)))   # noqa: E731
        if o == "tinfo":
            t = self.tinfo + 164 * (i(1) % NTRACKS)
            e.write(t + 65, bytes([i(2) & 0xff, i(3) & 0xff, i(4) & 0xff]))
            e.write(t + 68, struct.pack("<h", s16(i(5))))
        elif o == "unl":
            self.unl = (bytes.fromhex(a[1]) + bytes(64))[:64]
        elif o == "highest":
            e.put32(HIGHEST, i(1) & M32)
        elif o == "gt":
            e.put32(FRED + F_GAMETYPE, i(1) & M32)
        elif o == "ncur":
            e.put32(FRED + F_CUREVENT, i(1) & M32)
        elif o == "np":
            e.put32(FRED + F_NPLAYERS, i(1) & M32)
        elif o == "sel":
            for j in range(4):
                e.put32(FRED + F_SEL + 4 * j, i(1 + j) & M32)
        elif o == "ko5":
            e.put32(FRED + F_KO5, i(1) & M32)
        elif o == "ride":
            e.put32(self.ride, i(1) & M32)
            e.write(self.ride + 4, bytes([i(2) & 0xff, i(3) & 0xff,
                                          i(4) & 0xff]))
        elif o == "rpk":
            for off, j in ((0, 1), (4, 2), (8, 3), (12, 4), (44, 5),
                           (16, 6), (20, 7), (52, 8)):
                e.put32(RP + off, int(a[j], 0) & M32)
        elif o == "ctnull":
            e.put32(erc.CT_ARRAY, 0 if i(1) else self.ct)
        elif o == "pfill":
            for p in range(2):
                n = i(1) + p
                e.write(FRED + F_PLAYERS + 1744 * p,
                        bytes((n + 5 * k) & 0xff for k in range(1536)))
        elif o == "tree":
            self.emit("tree -> %s" % P(self.call(F_GETTREE, FRED)))
        elif o == "getsel":
            self.emit("getsel %d -> %d" % (
                i(1), s32(self.call(F_GETSEL, FRED + F_SEL, i(1) & M32))))
        elif o in ("setsel", "settype"):
            if o == "setsel":
                self.call(F_SETSEL, FRED + F_SEL, i(1) & M32, i(2) & M32)
            else:
                self.call(F_SETTYPE, FRED + F_SEL, i(1) & M32)
            self.emit("%s -> %s" % (o, " ".join(
                "%d" % s32(e.u32(FRED + F_SEL + 4 * j)) for j in range(4))))
        elif o == "flush":
            self.emit("flush %d" % i(1))
            self.call(F_FLUSH, FRED + F_PLAYERS + 1744 * (i(1) & 1))
            self.status_dump()
        elif o == "pad":
            e.write(self.B + self.ndata + i(1), bytes.fromhex(a[2])[:256])
        elif o == "ptab":
            t = self.tree_at(i(1))
            k = i(1) & 15
            if k not in self.own:
                self.own[k] = e.u32(t + 20)
            if i(2) == -2:
                e.put32(t + 20, self.own.pop(k))
            else:
                e.put32(t + 20, 0 if i(2) == -1
                        else self.B + self.ndata + i(2))
        elif o == "cars":
            t = self.tree_at(i(1))
            ev = self.B + i(2)
            line = "cars %s %s" % (P(t), P(ev))
            cars = e.u32(t + 20)
            for k in range(s8(e.u8(ev + 59))):
                idx = s16(e.u32(ev + 68 + 2 * k))
                rec = (cars + 4 * idx) & M32
                if (idx < 0 if cars == 0 else
                        rec < self.B
                        or rec + 4 > self.B + self.ndata + etc.PAD):
                    self.emit(line + " skip")
                    return
            self.emit(line)
            self.call(F_CARS, FRED, t, ev)
            self.status_dump()
        elif o == "maybe":
            t, ev = self.selected()
            if self.use_tree() and self.stateless_multi(ev):
                self.emit("maybe skip")
                return
            self.emit("maybe")
            self.call(F_MAYBE, FRED)
            self.emit("  states " + e.read(FRED + etc.CH_STATE, 512).hex())
        elif o == "cont":
            t, ev = self.selected()
            if self.use_tree() and (
                    t == 0 or ev == 0 or s8(e.u8(ev + 41)) not in (3, 4)
                    or self.stateless_multi(ev)):
                self.emit("cont skip")
                return
            self.emit("cont")
            self.call(F_CONT, FRED)
        elif o == "pick":
            self.emit("pick")
            self.call(F_PICK, FRED)
            self.emit("  tracks " + e.read(TRE + 212, 32).hex())
        elif o == "fake":
            self.emit("fake")
            self.call(F_FAKE, FRED)
            self.tre_dump()
        elif o == "word":
            # StartRace, 0x001850e0: the word 0, then IsLastOpen on the
            # tree's current event when there is a tree.
            t = self.call(F_GETTREE, FRED)
            w = 0
            if t != 0:
                ev = self.call(F_NUM, t, e.u32(FRED + F_CUREVENT))
                if ev == 0:
                    self.emit("word none")
                    return
                w = s32(self.call(F_LASTOPEN, ev))
            self.emit("word -> %d" % w)
        elif o == "opp":
            # SetupCarsForRace, 0x00185a1c: the tree's opponent table and
            # the current event's index `i` (an event the tree does not
            # have reads 0 at the bottom of memory).
            t = self.call(F_GETTREE, FRED)
            rec = 0
            if t != 0:
                ev = self.call(F_NUM, t, e.u32(FRED + F_CUREVENT))
                idx = s16(e.u32(ev + 156 + 2 * i(1))) if ev else 0
                po = e.u32(t + 52)
                rec = (po + 4 * idx) & M32 if po else 0
            self.emit("opp %d -> %s" % (i(1), self.rec_print(rec)))
        elif o == "oclr":
            self.emit("oclr")
            self.call(F_OCLR, OPENED)
            self.list_dump()
        elif o == "oadd":
            e.write(self.goal, struct.pack("<HHI", i(1) & 0xffff,
                                           i(2) & 0xffff, i(3) & M32))
            self.emit("oadd %d" % i(4))
            self.call(F_OADD, OPENED, self.goal, i(4) & M32)
            self.list_dump()
        elif o == "olist":
            e.write(OPENED, (bytes.fromhex(a[1]) + bytes(52))[:52])
        elif o == "opassed":
            for j in range(8):
                e.put32(self.outs + 4 * j, -99 & M32)
            n = s32(self.call(F_OPASSED, OPENED, self.outs, 8, TRE))
            self.emit("opassed -> %d %s" % (n, " ".join(
                "%d" % s32(e.u32(self.outs + 4 * j)) for j in range(8))))
        elif o == "onum":
            self.emit("onum -> %d" % s32(self.call(F_ONUM, OPENED, TRE)))
        elif o == "tredump":
            self.emit("tredump")
            self.tre_dump()
        else:
            erc.Model.run(self, a)


def model(lines, data):
    m = Model(data)
    for ln in lines:
        m.run(ln.split("|"))
    return m.out


# ================================================================ the script

def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def tinfo_cases(r):
    """The 40 tracks: their numbers, twins, point to point and time of
    day, mostly a track's own, sometimes another's or out of range."""
    out, nums = [], []
    for k in range(NTRACKS):
        num = r.choice([k, k, k, r.randint(0, 45), r.randint(-128, 127)])
        same = r.choice([k, num, r.randint(0, 45), r.randint(-128, 127)])
        p2p = r.choice([0, 0, 1, -1, 2])
        tod = r.choice([0, 1, 2, 3, r.randint(-5, 9), r.randint(-40000,
                                                                40000)])
        out.append("tinfo|%d|%d|%d|%d|%d" % (k, num, same, p2p, tod))
        nums.append((num, same))
    return out, nums


def unl_mask(r, density):
    return bytes(sum(1 << b for b in range(8) if r.random() < density)
                 for _ in range(64))


def listed(nums, mask, highest):
    """The tracks on PickRandomTracks' list: (number, direction)."""
    out = []
    for k in range(0, min(highest, NTRACKS - 1) + 1):
        num, same = nums[k]
        for d in (0, 1):
            bit = (same & 0xff) * 2 + d
            if mask[bit >> 3] >> (bit & 7) & 1:
                out.append((num, d))
    return out


def select_cases(r):
    out = []
    for d in ((0, 1, 1, 0), (1, 5, 7, 0), (2, 3, 4, 9), (-1, 8, 9, 1),
              (0, -7, 33, 2), (1, 0, 0, 0)):
        out.append("sel|%d|%d|%d|%d" % d)
        for t in (-1, 0, 1, 2, 3, 7, 0x7fffffff, -0x80000000):
            out.append("getsel|%d" % t)
        for t, n in ((0, 5), (1, 6), (2, 7), (-1, 8), (0, -3), (9, 32)):
            out.append("setsel|%d|%d" % (t, n))
    for t in (0, 1, 2, -1, 1, 0, 5):
        out.append("settype|%d" % t)
        out.append("setsel|%d|%d" % (r.randint(-2, 3), r.randint(-5, 40)))
        out += ["getsel|0", "getsel|1"]
    for n in (0, 77, 200):
        out += ["pfill|%d" % n, "flush|0", "flush|1"]
    return out


def tree_cases():
    out = []
    for e3 in (0, 1):
        out.append("e3|%d" % e3)
        for gt in (-1, 0, 4, 7, 8, 9, 10, 0x10008):
            out += ["gt|%d" % gt, "tree"]
    return out


def opened_cases(r):
    out = ["oclr", "onum", "opassed"]
    for k in range(6):
        out.append("oadd|%d|%d|%d|%d" % (
            r.choice([0, 1, 2, 3, 7]), r.randint(0, 40),
            r.choice([r.randint(0, 9), r.randint(0, 2000000)]),
            r.choice([32, r.randint(-2, 33)])))
    return out + ["onum", "opassed", "oclr", "onum"]


def goal_list(r, evs, nums_only=False):
    """A list of the events opened: up to four goals, most of them on the
    events of the tree being raced."""
    n = r.randint(0, 4)
    b = bytearray()
    for _ in range(4):
        ev = r.choice(evs)
        gt = r.choice([1, 1, 2, 3, r.randint(0, 9)])
        gd = (r.randint(0, 9) if gt != 2
              else r.choice([0, 0x7fffffff, r.randint(1, 2000000)]))
        b += struct.pack("<HHIi", gt, ev[1] & 0xffff, gd,
                         r.choice([32, ev[1], r.randint(0, 33)]))
    b += struct.pack("<i", n)
    return "olist|" + b.hex()


def event_cases(d, r, k, gt, evs):
    """Every question of the tree `k`'s events, as game type `gt`."""
    out = ["gt|%d" % gt]
    out.append("ctnull|0")
    for ev in evs:
        out += ["pfill|%d" % r.randint(0, 255), "cars|%d|%d" % (k, ev[0])]
    out += ["ctnull|1"] + ["cars|%d|%d" % (k, ev[0]) for ev in evs[:12]]
    out.append("ctnull|0")
    for n in [ev[1] for ev in evs] + [0, 33, -1, 100]:
        out += ["ncur|%d" % n, "word"]
        out += ["opp|%d" % j for j in range(7)]
    for ev in evs:
        num = ev[1]
        other = r.choice([x[1] for x in evs] + [0, 33])
        # The event chosen in a tree of type 1, then of type 0.
        for d1, d2 in ((num, other), (other, num)):
            out.append("sel|%d|%d|%d|0" % (r.randint(0, 1), d1, d2))
            out.append("ride|%d|%d|%d|%d" % (
                r.choice([r.randint(0, 63), r.randint(-5, 300)]),
                r.randint(-3, 3), r.choice([-1, 0, 3, r.randint(-128, 127)]),
                r.choice([0, 1, 2, -1])))
            out += ["maybe", "cont"]
    # The rest of each event's flow: SetRace, then the list of the events
    # it opens, judged as the state moves.
    for ev in evs:
        out += ["rpfill|%d" % r.randint(0, 255),
                "evfill|%d" % r.randint(0, 255),
                "randq|%d" % r.getrandbits(32),
                "set|%d|%d" % (k, ev[0]), goal_list(r, evs), "onum",
                "opassed"]
        for _ in range(2):
            out += ["ev|put|%d|%s" % (ev[0], etc.state_bytes(r, ev[2])),
                    "onum", "opassed"]
    return out


def ko_cases(r, nums, rounds):
    """Challenge knockouts: the tracks, the unlock mask and the race, with
    never more races than tracks on the list or eight."""
    out = []
    for _ in range(rounds):
        highest = r.choice([39, 39, 45, 10, 3, 0, -1])
        mask = unl_mask(r, r.choice([0.02, 0.1, 0.5, 0.9, 1.0]))
        lst = listed(nums, mask, highest)
        if r.random() < 0.6 and lst:
            tn, td = r.choice(lst)
            td = td if r.random() < 0.8 else r.choice([0, 1, 2])
        else:
            tn, td = r.choice([r.randint(0, 45), 50, 200, -1]), \
                r.randint(0, 2)
        found = any(x[0] == ((tn & 0xff) ^ 0x80) - 0x80 and x[1] == td
                    and -128 <= tn <= 127 for x in lst)
        room = len(lst) + (0 if found else 1)
        np = r.choice([1, 1, 2])
        most = min(8, room)
        races = r.randint(min(0, most), most)
        nai = races - np + 1
        out += ["highest|%d" % highest, "unl|" + mask.hex(),
                "np|%d" % np, "ko5|%d" % r.choice([0, 0, 0, 1, 2, -1]),
                "rpk|%d|%d|%d|%d|%d|%d|%d|%d" % (
                    tn, r.randint(-3, 5), r.randint(-3, 5), td,
                    r.randint(-2, 16),
                    fbits(r.choice([0.0, 0.25, 0.5, 1.0, 1.27, -0.5,
                                    r.uniform(0, 1.3)])),
                    fbits(r.choice([0.0, 0.25, 0.5, 1.0, 1.28, -0.5,
                                    r.uniform(0, 1.3)])), nai),
                "evfill|%d" % r.randint(0, 255),
                "|".join(["randq"] + ["%d" % r.getrandbits(32)
                                      for _ in range(r.randint(0, 64))]),
                "rand|%d" % r.getrandbits(32), "fake"]
    return out


def script(d):
    r = random.Random(0x6ec2)
    out = select_cases(r) + tree_cases() + opened_cases(r)
    tl, nums = tinfo_cases(r)
    out += tl
    ch, hp = d.events["ch"], d.events["hp"]
    out += ["e3|0", "all|0", "fredclr", "ult|0", "load|%d" % d.ch,
            "load|%d" % d.hp] + tree_cases() + ["e3|0"]
    out += event_cases(d, r, 0, 8, ch) + event_cases(d, r, 1, 9, hp)
    for seed in range(3):
        out.append(etc.fred_fill(r))
        for ev in r.sample(ch + hp, 24):
            out.append("ev|put|%d|%s" % (ev[0], etc.state_bytes(r, ev[2])))
        out += event_cases(d, r, 0, 8, ch) + event_cases(d, r, 1, 9, hp)
    out += ["all|1"] + event_cases(d, r, 1, 9, hp[:6]) + ["all|0"]
    # The cars of a made-up table after the data (types and their bytes
    # 0 or not), and of none, with and without CarTypeInfoArray.
    recs = bytearray()
    for _ in range(64):
        recs += bytes([r.getrandbits(8), r.choice([0, r.getrandbits(8)]),
                       r.choice([0, 0, r.getrandbits(8)]), r.getrandbits(8)])
    out.append("pad|0|" + recs.hex())
    for k, tree in ((0, ch), (1, hp)):
        for tab in (0, -1):
            out.append("ptab|%d|%d" % (k, tab))
            for ct in (0, 1):
                out.append("ctnull|%d" % ct)
                out += ["cars|%d|%d" % (k, ev[0]) for ev in tree]
        out.append("ptab|%d|-2" % k)
    out += ["ctnull|0", "pad|0|" + bytes(256).hex()]
    # StartRace's word on the last event open: all but one of 1 .. 31
    # passed, Hot Pursuit's Ultimate locked or not.
    for k in (0, 5, 30):
        for tree, gt in ((ch, 8), (hp, 9)):
            ev = tree[k]
            out += ["gl|unlock", "ev|reset|%d" % ev[0], "gt|%d" % gt]
            for n in (ev[1], tree[k ^ 1][1]):
                out += ["ncur|%d" % n, "word"]
            out += ["ev|reset|%d" % hp[31][0]]
            for g in (gt, 17 - gt):
                for n in (ev[1], tree[k ^ 1][1], 32):
                    out += ["gt|%d" % g, "ncur|%d" % n, "word"]
    # A game of another type in the trees' presence.
    for gt in (0, 4, 7):
        out += ["gt|%d" % gt, "word", "opp|0", "maybe", "cont"]
    out += ko_cases(r, nums, 300)
    out += ["unload|%d" % d.ch, "fredclr", "ult|0"]
    # The made-up trees, E3 and not.
    for e3, keys in ((0, ("A", "B")), (1, ("H", "D"))):
        out += ["e3|%d" % e3, "fredclr", "ult|0"]
        out += ["load|%d" % d.chunks[k] for k in keys]
        out += tree_cases() + ["e3|%d" % e3]
        for k, key in enumerate(keys):
            out += event_cases(d, r, k, 8 + k, d.events[key])
            out.append(etc.fred_fill(r))
            out += event_cases(d, r, k, 8 + k, d.events[key])
        out += ["unload|%d" % d.chunks[k] for k in keys]
    out += ["e3|0", "fredclr", "ult|0", "gt|0"]
    out += ko_cases(r, nums, 100)
    return out


# ================================================================= running

def build_harness(tmp, name="fredevent_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


run_harness = etc.run_harness
diff = pcc.diff


def write_inputs(tmp):
    d = etc.Data()
    lines = script(d)
    sc = Path(tmp) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    dp = Path(tmp) / "data.bin"
    dp.write_bytes(d.buf)
    return d, lines, sc, dp


def model_cached(lines, buf):
    return mutpar.model_cached(lines, lambda s: model(s, buf),
                               data=DATA_FILES, cut=MUTATIONS_HEADER)


MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL

# ============================================================ the mutations

def _m(name, old, new, f=FE):
    return (name, f, old, new)


MUTATIONS = [
    # ---- the tree and the select screen
    _m("gt-8", "if (f->GameType == 8)", "if (f->GameType == 7)"),
    _m("gt-9", "if (f->GameType == 9)", "if (f->GameType == 10)"),
    _m("gt-che3", "bVersionE3 != 0 ? \"Championship E3\"",
       "bVersionE3 == 0 ? \"Championship E3\""),
    _m("gt-hpe3", "bVersionE3 != 0 ? \"Hot Pursuit E3\"",
       "bVersionE3 == 0 ? \"Hot Pursuit E3\""),
    _m("gt-chname", ": \"Championship\");", ": \"Championship \");"),
    _m("gs-0", "if (type == 0)\n        return d[2];",
       "if (type == 0)\n        return d[1];"),
    _m("gs-1", "if (type == 1)\n        return d[1];",
       "if (type == 1)\n        return d[2];"),
    _m("gs-def", "    return 1;\n}\n\nvoid data_event_select_set",
       "    return 0;\n}\n\nvoid data_event_select_set"),
    _m("ss-0", "if (d[0] == 0)\n        d[2] = n;",
       "if (d[0] == 0)\n        d[1] = n;"),
    _m("ss-1", "else if (d[0] == 1)\n        d[1] = n;",
       "else if (d[0] >= 1)\n        d[1] = n;"),
    _m("ss-type", "(void)type;\n    if (d[0] == 0)",
       "(void)type;\n    if (type == 0)"),
    _m("st-set", "d[0] = type;", "d[1] = type;"),
    _m("se-type", "                                                t->nType));",
       "                                                0));"),
    # ---- the cars
    _m("fl-st", "p->aCarStatus[i].nStatus = CAR_STATUS_HIDDEN;",
       "p->aCarStatus[i].nStatus = CAR_STATUS_AVAILABLE;"),
    _m("fl-n", "for (i = 0; i < FRED_NUM_CAR_TYPES; i++)",
       "for (i = 0; i < FRED_NUM_CAR_TYPES - 1; i++)"),
    _m("mc-p", "for (p = 0; p < 2; p++)\n        fpi_flush_available_cars",
       "for (p = 0; p < 1; p++)\n        fpi_flush_available_cars"),
    _m("mc-n", "for (i = 0; i < e->nCars; i++) {",
       "for (i = 0; i < e->nCars - 1; i++) {"),
    _m("mc-idx", "+ 2 * i);\n        const uint8_t *rec;",
       "+ 2 * i + 2);\n        const uint8_t *rec;"),
    _m("mc-null0", "if (idx == 0)\n                continue;",
       "if (idx != 0)\n                continue;"),
    _m("mc-rec", "rec = tree->pCars + 4 * idx;",
       "rec = tree->pCars + 4 * idx + 4;"),
    _m("mc-ct", "if (CarTypeInfoArray == NULL && rec[2] == 0)",
       "if (CarTypeInfoArray != NULL && rec[2] == 0)"),
    _m("mc-ct2", "if (CarTypeInfoArray == NULL && rec[2] == 0)",
       "if (CarTypeInfoArray == NULL && rec[1] == 0)"),
    _m("mc-skin", "skin = (int32_t)(w >> 24 & 0xf);",
       "skin = (int32_t)(w >> 24 & 0x7);"),
    _m("mc-skin0", "if (skin == 0)\n            skin = -1;",
       "if (skin == 0)\n            skin = 0;"),
    _m("mc-dash", "dash = (int32_t)(w >> 30 & 1);",
       "dash = (int32_t)(w >> 31 & 1);"),
    _m("mc-st", "CAR_STATUS_AVAILABLE, rec[2], skin,",
       "CAR_STATUS_HIDDEN, rec[2], skin,"),
    _m("mc-type", "CAR_STATUS_AVAILABLE, rec[2], skin,",
       "CAR_STATUS_AVAILABLE, rec[3], skin,"),
    _m("mc-p2", "for (p = 0; p < 2; p++)\n            fpi_set_car_availability",
       "for (p = 0; p < 1; p++)\n            fpi_set_car_availability"),
    _m("my-use", "if (!fred_use_tree_event(f))\n        return;\n    ride =",
       "if (fred_use_tree_event(f))\n        return;\n    ride ="),
    _m("my-player", "fpi_get_selected_ride_info(&f->FrontendPlayers[0], ",
       "fpi_get_selected_ride_info(&f->FrontendPlayers[1], "),
    _m("my-gt", "&f->FrontendPlayers[0], Fred.GameType);",
       "&f->FrontendPlayers[0], 0);"),
    _m("my-type", "event_info_set_selected_car(e, ride->Type, ",
       "event_info_set_selected_car(e, ride->Type + 1, "),
    _m("my-skin", "ride->SkinNumber,", "ride->InstanceIndex,"),
    _m("my-dash", "ride->HasDash != 0);", "ride->HasDash == 0);"),
    _m("ct-use", "if (!fred_use_tree_event(f))\n        return;\n    e =",
       "if (fred_use_tree_event(f))\n        return;\n    e ="),
    _m("ct-p", "fpi_assign_car_of_type(&f->FrontendPlayers[0], ",
       "fpi_assign_car_of_type(&f->FrontendPlayers[1], "),
    _m("ct-gt", "Fred.GameType, car,", "f->nCurrentEvent, car,"),
    _m("ct-args", "(uint32_t)skin, dash);", "(uint32_t)dash, skin);"),
    _m("ct-start", "    fred_start_race(f);\n", ""),
    # ---- the challenge knockout's tracks
    _m("rz-n", "int32_t j = bRandomI(n, &bDefaultSeed);",
       "int32_t j = bRandomI(n + 1, &bDefaultSeed);"),
    _m("rz-k", "for (k = 0; k < n; k++) {\n        int32_t j",
       "for (k = 1; k < n; k++) {\n        int32_t j"),
    _m("rz-swap", "        a[j] = t;\n", ""),
    _m("pw-tn", "t->b[0] = (uint8_t)ti->TrackNumber;",
       "t->b[0] = (uint8_t)ti->SameAsTrackNumber;"),
    _m("pw-keep", "w = rd32(t->b);", "w = t->b[0];"),
    _m("pw-w", "(uint32_t)(rp->TrackWeather & 3) << 10;",
       "(uint32_t)(rp->TrackWeather & 1) << 10;"),
    _m("pw-tod", "(uint32_t)(ti->TimeOfDay & 3) << 12;",
       "(uint32_t)(rp->TrackTimeOfDay & 3) << 12;"),
    _m("pw-dir", "(uint32_t)(pt->Direction & 1) << 9;",
       "(uint32_t)(rp->TrackDirection & 1) << 9;"),
    _m("pw-dens", "ee_mul(rp->TrafficDensity, 100.0f)) & 0x7f)",
       "ee_mul(rp->TrafficDensity, 100.0f)) & 0x3f)"),
    _m("pw-dens2", "ee_mul(rp->TrafficDensity, 100.0f)",
       "ee_mul(rp->TrafficDensity, 99.0f)"),
    _m("pw-onc", "ee_mul(rp->TrafficOncoming, 100.0f)) << 25;",
       "ee_mul(rp->TrafficOncoming, 100.0f)) << 24;"),
    _m("pw-p2p", "(ti->Point2Point != 0 ? 0x4000u : 0x8000u)",
       "(ti->Point2Point > 0 ? 0x4000u : 0x8000u)"),
    _m("pw-laps", "0x4000u : 0x8000u", "0x4000u : 0xc000u"),
    _m("pk-hi", "for (i = 0; i <= HighestTrackNumber; i++) {",
       "for (i = 0; i < HighestTrackNumber; i++) {"),
    _m("pk-same", "is_track_unlocked(ti->SameAsTrackNumber, dir)",
       "is_track_unlocked(ti->TrackNumber, dir)"),
    _m("pk-dir", "for (dir = 0; dir < 2; dir++) {",
       "for (dir = 0; dir < 1; dir++) {"),
    _m("pk-ftn", "if (pickable[k].Info->TrackNumber == rp->TrackNumber",
       "if (pickable[k].Info->SameAsTrackNumber == rp->TrackNumber"),
    _m("pk-fdir", "&& pickable[k].Direction == rp->TrackDirection)",
       "&& pickable[k].Direction != rp->TrackDirection)"),
    _m("pk-move", "memmove(&pickable[1], &pickable[0], (size_t)k * sizeof",
       "memmove(&pickable[1], &pickable[0], (size_t)0 * sizeof"),
    _m("pk-front", "pickable[0] = t;", "pickable[k] = t;"),
    _m("pk-insn", "        n++;\n    }\n", "    }\n"),
    _m("pk-insdir", "pickable[0].Direction = rp->TrackDirection;",
       "pickable[0].Direction = 0;"),
    _m("pk-insinfo", "pickable[0].Info = track_get_info(rp->TrackNumber);",
       "pickable[0].Info = track_get_info(rp->TrackNumber + 1);"),
    _m("pk-sn", "for (s = 0; s < ev->nTracks && s < n; s++)",
       "for (s = 0; s < ev->nTracks - 1 && s < n; s++)"),
    _m("pk-sn2", "for (s = 0; s < ev->nTracks && s < n; s++)",
       "for (s = 0; s < ev->nTracks && s < n - 1; s++)"),
    # ---- the challenge knockout's event
    _m("fk-np", "int32_t players = f->NumPlayerCars;",
       "int32_t players = 1;"),
    _m("fk-races", "+ (uint32_t)players - 1u);",
       "+ (uint32_t)players - 0u);"),
    _m("fk-state", "ev->pState = ev->aOldState;",
       "ev->pState = ev->aOldState + 4;"),
    _m("fk-reset", "    ko_state_reset(ev->aOldState);\n", ""),
    _m("fk-name", "\"Challenge Race Knockout\"", "\"Challenge Race Knockouts\""),
    _m("fk-obj", "ev->Objective.nData = 3;", "ev->Objective.nData = 4;"),
    _m("fk-type", "ev->nType = EVENT_RACE_KNOCKOUT;",
       "ev->nType = EVENT_TOURNAMENT;"),
    _m("fk-init", "ev->nInitialPlayers = (int16_t)players;",
       "ev->nInitialPlayers = (int16_t)races;"),
    _m("fk-otype", "ev->Objective.nType = 1;", "ev->Objective.nType = 2;"),
    _m("fk-opp", "ev->nOpponents = races;", "ev->nOpponents = races - 1;"),
    _m("fk-tr", "ev->nTracks = races;", "ev->nTracks = races - 1;"),
    _m("fk-num", "ev->nNumber = 0;", "ev->nNumber = 1;"),
    _m("fk-class", "ev->nClass = 0;", "ev->nClass = 1;"),
    _m("fk-cars", "ev->nCars = 0;", "ev->nCars = 1;"),
    _m("fk-rew", "ev->nRewards = 0;", "ev->nRewards = 1;"),
    _m("fk-oev", "ev->Objective.nEvent = 0;", "ev->Objective.nEvent = 1;"),
    _m("fk-mode", "mode = Fred.RaceKnockoutSetupData[5];",
       "mode = Fred.RaceKnockoutSetupData[4];"),
    _m("fk-m0", "if (mode == 0) {", "if (mode <= 0) {"),
    _m("fk-m1", "} else if (mode == 1) {", "} else if (mode >= 1) {"),
    _m("fk-t8", "for (t = 0; t < ev->nTracks && t < 8; t++)",
       "for (t = 0; t < ev->nTracks - 1 && t < 8; t++)"),
    _m("fk-res", "    raceevent_reset_results(ev);\n", ""),
    # ---- the race's word and opponent
    _m("wd-ncur", "e = event_tree_get_event_number(t, f->nCurrentEvent);\n"
       "    // Retail asks", "e = event_tree_get_event_number(t, "
       "f->nCurrentEvent + 1);\n    // Retail asks"),
    _m("op-ncur", "e = event_tree_get_event_number(t, f->nCurrentEvent);\n"
       "    // A number", "e = event_tree_get_event_number(t, "
       "f->nCurrentEvent + 1);\n    // A number"),
    _m("op-idx0", "int32_t idx = 0;", "int32_t idx = 1;"),
    _m("op-i", "+ 2 * i);\n    if (t->pOpponents",
       "+ 2 * i + 2);\n    if (t->pOpponents"),
    _m("op-4", "return t->pOpponents + 4 * idx;",
       "return t->pOpponents + 2 * idx;"),
    # ---- the events opened
    _m("oc-clr", "l->nCount = 0;", "l->nCount = 1;"),
    _m("oa-4", "if (l->nCount < 4) {", "if (l->nCount <= 4) {"),
    _m("oa-n", "l->aEvents[l->nCount].nEvent = n;",
       "l->aEvents[l->nCount].nEvent = n + 1;"),
    _m("oa-g", "        l->aEvents[l->nCount].Goal = *g;\n", ""),
    _m("oa-inc", "l->nCount++;", "l->nCount += 2;"),
    _m("opa-n", "for (i = 0; i < l->nCount && i < 4; i++)",
       "for (i = 0; i < l->nCount - 1 && i < 4; i++)"),
    _m("opa-4", "for (i = 0; i < l->nCount && i < 4; i++)",
       "for (i = 0; i < l->nCount && i < 3; i++)"),
    _m("opa-st", "            == EVENT_PASSED)", "            != EVENT_PASSED)"),
    _m("opa-out", "out[n++] = l->aEvents[i].nEvent;", "out[n++] = i;"),
]

EQUIVALENT = {
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
        todo, SOURCES, "fredevent_test",
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
