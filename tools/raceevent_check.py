#!/usr/bin/env python3
"""Cross-check 3DS Files/source/raceevent.c, RaceEvent (RE-6b), against the
retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own code: RaceEvent.obj's functions from
AnyRewardEarned (0x00200ac8) to UserWon (0x00200c38), GetStateSize
(0x00200e30), IsMultiTrack (0x00201478), and EventResult::Reset
(0x002014e8) to ResetState (0x00202698), on TheRaceEvent (0x0031b600),
TheRaceParameters (0x0031a898) with its driver table (0x0031abb0, retail's
DriverInfo: the rank at +0, the number +1, the start +4, the type +8) and
Fred (0x002fc050). Under them run retail's state classes (EventTree.obj,
ported in eventtree.c), RaceParameters' GetDriverInfoByDriverNumber,
EliminateDriver, RestoreEliminated and ResetStartPositions (raceparams.c),
and Fred's RaceWasAborted and UseTreeEvent. The harness
(tools/src/raceevent_test.c) runs the port and prints the same lines.

**The stubs**, logged and answered by the same rule on both sides:
Fred::CalculateStartingPositions (0x00185fe8), EventTrack::SetRace
(0x001fec20, the port's gEventTrackSetRaceOnFn), RacingCar::GetBestLapTime
(0x00147588, a time the script sets) and Timer::SetTime (0x00136dd0, which
stores the float's bits xor 0x01234567). bMemCpy is native.

**Compared** are the stubs' logs, each answer, and after each op the
event's aOldState, aSavedState, state and results, the race parameters'
start positions and counts, the 14 drivers' numbers, ranks and starts, and
the first player's settings in TheRaceParameters.

**What the script keeps away from**, where retail traps or reads outside
what it owns and the port is guarded instead (raceevent.c says where): a
racer index past 0..7 for RecordResults, reward indexes below 0 or counts
past 8, a tournament's places past 8, a knockout or tournament's `next`
with no tracks, a tournament with fewer than 0 or more than 7 opponents,
and Be A Cop's time with no cop manager. A NULL state reads the bottom of
memory in retail, zeros, and writes there; the model clears it after each
op, as the port reads zeros and does not write.

    python tools/raceevent_check.py
    python tools/raceevent_check.py --mutate [--only a,b]
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

HARNESS = "tools/src/raceevent_test.c"
RE = "3DS Files/source/raceevent.c"
ET = "3DS Files/source/eventtree.c"
RPC = "3DS Files/source/raceparams.c"
SOURCES = [HARNESS, RE, ET, RPC]
HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = retail_model.RETAIL_GP
RP = 0x0031a898                         # TheRaceParameters
DT = 0x0031abb0                         # its 14 DriverInfos, 24 bytes each
EVENT = 0x0031b600                      # TheRaceEvent
FRED = 0x002fc050
FRED_SPAN = 2048                        # where the script's states live
F_ABORTED, F_GAME, F_PLAYERS = 0x10728, 0x1072c, 0x10734
F_PS = 0x10738 + 1604                   # FrontendPlayers[0].mPlayerSettings
G_COPMGR = GP - 15620                   # pCopManager
CM_BEACOP = 10480                       # fBeACopTime
RP_FIELDS = {"type": (32, 4), "players": (48, 4), "ai": (52, 4),
             "sp0": (60, 1), "sp1": (61, 1), "cop": (628, 4),
             "ndrv": (776, 4)}
RP_TABLE, RP_PS = 772, 652
EV_FIELDS = {"number": 104, "type": 106, "class": 108, "cars": 110,
             "tracks": 112, "rewards": 114, "opp": 116, "players": 118}
EV_OLD, EV_SAVED, EV_LAST, EV_GOAL = 8, 24, 120, 124
EV_TRACKS, EV_REWARDS, EV_RESULTS = 212, 244, 336
CAR_NUMBER = 10                         # Car::DriverNumber
RC_CAR, RC_REASON, RC_TIME = 0, 18, 180  # RacingCar
NCARS = 4

S_CSP = 0x00185fe8
S_SETRACE = 0x001fec20
S_BEST = 0x00147588
S_SETTIME = 0x00136dd0
S_MEMCPY = 0x00250288

F = {"anyearned": 0x00200ac8, "earned": 0x00200b30, "won": 0x00200c38,
     "size": 0x00200e30, "multi": 0x00201478, "aborted": 0x002014f8,
     "resetres": 0x00201518, "r2d": 0x00201558, "d2r": 0x00201578,
     "record": 0x00201598, "rin": 0x00201668, "din": 0x00201698,
     "relim": 0x002016d0, "delim": 0x00201708, "lastp": 0x00201738,
     "firstp": 0x002017c8, "rankst": 0x00201858, "tourst": 0x00201880,
     "kost": 0x002018a0, "timest": 0x002018c0, "post": 0x002018f8,
     "save": 0x00201a80, "cycle": 0x00201ac0, "restart": 0x00201b38,
     "fell": 0x00201bd8, "adv": 0x00201db8, "keep": 0x00201fb0,
     "ridx": 0x00202010, "rcount": 0x00202088, "next": 0x002020b8,
     "csp": 0x002022c0, "another": 0x00202420, "statusof": 0x00202528,
     "statusgoal": 0x002025c8, "status": 0x00202658,
     "oldstatus": 0x00202678, "resetstate": 0x00202698}
LIMIT = 200000


def s8(v):
    v &= 0xff
    return v - 0x100 if v & 0x80 else v


# ================================================================== model

class Model(object):
    def __init__(self):
        e = self.e = retail_model.RetailEmu(ieee=True)
        self.out = []
        self.shown = None

        def block(n):
            p = e.alloc(n, align=16)
            e.write(p, bytes(n))
            return p
        self.cars = [block(16) for _ in range(NCARS)]
        self.rcs = [block(192) for _ in range(NCARS)]
        self.best = block(16)
        self.goal = block(16)
        self.cm = block(CM_BEACOP + 16)

        def memcpy(em):
            d, s, n = (em.reg[r] & M32 for r in (4, 5, 6))
            em.mem[d:d + n] = em.mem[s:s + n]
            return d
        for addr, fn in ((S_CSP, self.s_csp), (S_SETRACE, self.s_setrace),
                         (S_BEST, self.s_best), (S_SETTIME, self.s_settime),
                         (S_MEMCPY, memcpy)):
            e.stub(addr, fn)
        self.clear()

    def emit(self, line):
        self.out.append(line)

    def put8(self, a, v):
        self.e.write(a, bytes([v & 0xff]))

    def put16(self, a, v):
        self.e.write(a, struct.pack("<H", v & 0xffff))

    def clear(self):
        e = self.e
        e.write(EVENT, bytes(432))
        e.write(RP, bytes(788))
        e.put32(RP + RP_TABLE, DT)
        e.write(DT, bytes(24 * 14))
        e.write(FRED, bytes(FRED_SPAN))
        for f in (F_ABORTED, F_GAME, F_PLAYERS):
            e.put32(FRED + f, 0)
        e.write(FRED + F_PS, bytes(48))
        for c in self.cars:
            e.write(c, bytes(16))
        for r in self.rcs:
            e.write(r, bytes(192))
        e.put32(self.best, 0)
        e.put32(self.cm + CM_BEACOP, 0)
        e.put32(G_COPMGR, 0)

    # ---- stubs

    def s_csp(self, em):
        ok = "" if em.reg[4] & M32 == FRED else " ?fred"
        self.emit("  csp%s" % ok)
        return 0

    def s_setrace(self, em):
        k = s32((em.reg[4] & M32) - (EVENT + EV_TRACKS))
        ok = "" if em.reg[5] & M32 == RP else " ?rp"
        self.emit("  setrace %d%s" % (int(k / 4), ok))
        return 0

    def s_best(self, em):
        a = em.reg[4] & M32
        k = self.rcs.index(a) if a in self.rcs else -1
        self.emit("  bestlap R%d" % k)
        return self.best

    def s_settime(self, em):
        bits = em.fpr[12] & M32
        self.emit("  settime %08x" % bits)
        em.put32(em.reg[4] & M32, bits ^ 0x01234567)
        return 0

    # ---- the dump

    def state(self):
        return self.e.u32(EVENT + 4)

    def P(self, a):
        a &= M32
        if a == 0:
            return "-"
        if FRED <= a < FRED + 0x20000:
            return "F%d" % (a - FRED)
        return "?"

    def dump(self):
        e = self.e
        s = ["  = O" + e.read(EVENT + EV_OLD, 16).hex(),
             "V" + e.read(EVENT + EV_SAVED, 16).hex()]
        st = self.state()
        s.append("S" + (e.read(st, 16).hex() if st else "-"))
        s.append("R")
        for i in range(8):
            r = EVENT + EV_RESULTS + 12 * i
            s.append("%d/%d/%d" % (s32(e.u32(r)), s32(e.u32(r + 4)),
                                   s32(e.u32(r + 8))))
        s.append("P%d,%d N%d,%d D" % (
            s8(e.u8(RP + 60)), s8(e.u8(RP + 61)), s32(e.u32(RP + 48)),
            s32(e.u32(RP + 52))))
        for i in range(14):
            d = DT + 24 * i
            s.append("%d:%d:%d" % (s8(e.u8(d + 1)), s8(e.u8(d)),
                                   s8(e.u8(d + 4))))
        s.append("PS" + e.read(RP + RP_PS, 48).hex())
        line = " ".join(s)
        if line != self.shown:
            self.shown = line
            self.emit(line)

    # ---- ops

    def which(self, w):
        return {"s": self.state(), "o": EVENT + EV_OLD,
                "v": EVENT + EV_SAVED}.get(w[0], 0)

    def call(self, name, *args):
        return self.e.call(F[name], EVENT, *args, limit=LIMIT)

    def run(self, a):
        e = self.e
        o = a[0]
        v = lambda j: int(a[j], 0) & M32        # noqa: E731
        i = lambda j: s32(int(a[j], 0))         # noqa: E731
        if o == "clear":
            self.clear()
        elif o == "ev":
            self.put16(EVENT + EV_FIELDS[a[1]], v(2))
        elif o == "last":
            e.put32(EVENT + EV_LAST, v(1))
        elif o == "goal":
            e.write(EVENT + EV_GOAL, bytes.fromhex(a[1]))
        elif o == "reward":
            e.write(EVENT + EV_REWARDS + 8 * i(1), bytes.fromhex(a[2]))
        elif o == "result":
            r = EVENT + EV_RESULTS + 12 * i(1)
            e.put32(r, v(2))
            e.put32(r + 4, v(3))
            e.put32(r + 8, v(4))
        elif o == "old":
            e.write(EVENT + EV_OLD, bytes.fromhex(a[1]))
        elif o == "saved":
            e.write(EVENT + EV_SAVED, bytes.fromhex(a[1]))
        elif o == "state":
            e.put32(EVENT + 4, 0 if i(1) < 0 else FRED + i(1))
        elif o == "sbytes":
            if self.state():
                e.write(self.state(), bytes.fromhex(a[1]))
        elif o == "rp":
            off, n = RP_FIELDS[a[1]]
            if n == 1:
                self.put8(RP + off, v(2))
            else:
                e.put32(RP + off, v(2))
        elif o == "drv":
            d = DT + 24 * i(1)
            self.put8(d + 1, v(2))
            self.put8(d, v(3))
            self.put8(d + 4, v(4))
            e.put32(d + 8, v(5))
        elif o == "fred":
            f = {"game": F_GAME, "aborted": F_ABORTED,
                 "players": F_PLAYERS}[a[1]]
            e.put32(FRED + f, v(2))
        elif o == "ps":
            e.write(FRED + F_PS, bytes.fromhex(a[1]))
        elif o == "cm":
            e.put32(G_COPMGR, self.cm if i(1) else 0)
            if len(a) > 2:
                e.put32(self.cm + CM_BEACOP, v(2))
        elif o == "rc":
            k = i(1)
            c, r = self.cars[k], self.rcs[k]
            e.put32(r + RC_CAR, c)
            self.put16(c + CAR_NUMBER, v(2))
            self.put16(r + RC_REASON, v(3))
            e.put32(r + RC_TIME, v(4))
        elif o == "bestlap":
            e.put32(self.best, v(1))
        # ---- the calls
        elif o in ("size", "multi", "aborted", "lastp", "firstp", "fell",
                   "adv", "ridx", "rcount", "another", "status",
                   "oldstatus", "anyearned", "won"):
            self.emit("%s -> %d" % (o, self.call(o)))
        elif o in ("next", "csp"):
            r = self.call(o)
            self.emit("%s -> %d" % (o, r))
        elif o in ("resetres", "post", "save", "cycle", "restart", "keep",
                   "resetstate"):
            self.emit(o)
            self.call(o)
        elif o in ("r2d", "d2r", "rin", "din", "relim", "delim"):
            self.emit("%s %d -> %d" % (o, i(1), self.call(o, i(1))))
        elif o == "record":
            self.emit("record R%d %d" % (i(1), i(2)))
            self.call(o, 0, self.rcs[i(1)], i(2))
        elif o == "getst":
            self.emit("getst %s %s %s %s" % tuple(
                self.P(self.call(n)) for n in ("rankst", "tourst", "kost",
                                               "timest")))
        elif o == "statusof":
            self.emit("statusof %s -> %d" % (a[1],
                                             self.call(o, self.which(a[1]))))
        elif o == "statusgoal":
            e.write(self.goal, bytes.fromhex(a[1]))
            self.emit("statusgoal %s -> %d" % (a[1], self.call(o, self.goal)))
        elif o == "earned":
            self.emit("earned %d %s -> %d" % (
                i(1), a[2], self.call(o, i(1), self.which(a[2]))))
        else:
            raise ValueError(o)
        # The bottom of memory, which a NULL state reads and writes.
        e.write(0, bytes(64))
        self.dump()


def model(lines):
    m = Model()
    for ln in lines:
        m.run(ln.split("|"))
    return m.out


# ================================================================ the script

CALLS = ("size", "multi", "aborted", "lastp", "firstp", "fell", "adv",
         "ridx", "rcount", "another", "status", "oldstatus", "anyearned",
         "won", "getst", "statusof|s", "statusof|o", "statusof|v",
         "statusof|-")
MUTATORS = ("resetres", "post", "save", "cycle", "restart", "keep",
            "resetstate", "next", "csp")


def hx(b):
    return bytes(b).hex()


def word(v):
    return struct.pack("<I", v & M32)


def goal(typ=0, ev=0, data=0):
    return "goal|" + hx(struct.pack("<HHI", typ & 0xffff, ev & 0xffff,
                                    data & M32))


def reward(i, typ, v1, data):
    return "reward|%d|%s" % (i, hx(struct.pack("<BBBBi", typ, v1, 0, 0,
                                               data)))


def ko_word(ranks):
    w = 0
    for k, r in enumerate(ranks):
        w |= (r & 15) << (4 * k)
    return w


def ko_state(ranks, starts=(0,) * 8, seed=0):
    return word(ko_word(ranks)) + word(ko_word(starts)) + word(seed) \
        + bytes(4)


def setup(typ, tracks=3, opp=3, players=1, rewards=0, state=400,
          nai=3, npl=1, game=8):
    """A small field: `npl` players (0, 1) and `nai` AI (100 ..) in the
    driver table, the event of type `typ` on the state at Fred+`state`."""
    out = ["clear", "ev|type|%d" % typ, "ev|tracks|%d" % tracks,
           "ev|opp|%d" % opp, "ev|players|%d" % players,
           "ev|rewards|%d" % rewards, "ev|number|%d" % (typ + 5),
           "state|%d" % state, "fred|game|%d" % game,
           "fred|players|%d" % npl, "rp|players|%d" % npl,
           "rp|ai|%d" % nai, "rp|ndrv|%d" % (npl + nai)]
    k = 0
    for p in range(npl):
        out.append("drv|%d|%d|0|%d|1" % (k, p, nai + 1 + p))
        k += 1
    for j in range(nai):
        out.append("drv|%d|%d|0|%d|2" % (k, 100 + j, j + 1))
        k += 1
    return out


def type_sweep():
    """Every type, with each kind of state, through every read."""
    out = []
    states = {
        "rank": [bytes(16), bytes([3]) + bytes(15), bytes([1]) + bytes(15),
                 bytes([9]) + bytes(15)],
        "time": [bytes(16), word(0x7fffffff) + bytes(12),
                 word(12345) + bytes(12), word(99999) + bytes(12)],
        "ko": [bytes(16), ko_state([0, 4, 3, 0]), ko_state([2, 1, 3, 4]),
               ko_state([1, 0, 0, 0, 0, 0, 0, 2])],
        "tour": [bytes(16), bytes([20, 12, 8, 6, 0, 0, 0, 0]) + bytes(8),
                 bytes([6, 20, 12, 8, 0, 0, 0, 0]) + bytes(8),
                 bytes([30, 18, 12, 9, 6, 3, 0, 0]) + bytes(8)]}
    for typ in (-2, -1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 0x7fff):
        for kind, ss in sorted(states.items()):
            for k, sb in enumerate(ss):
                out += setup(typ, tracks=3, opp=3, rewards=3)
                out += [goal(1, 0, 2 if kind != "time" else 50000),
                        reward(0, 0, 40, 1), reward(1, 1, 3,
                                                    2 if kind != "time"
                                                    else 20000),
                        reward(2, 0, 41, 3 if kind != "time" else 99999)]
                out.append("sbytes|" + hx(sb))
                out.append("old|" + hx(ss[(k + 1) % len(ss)]))
                out.append("saved|" + hx(ss[(k + 2) % len(ss)]))
                out += list(CALLS)
                for g in ((0, 0, 0), (1, 2, 1), (2, 0, 3), (0, 0, 12345),
                          (3, 3, 0xffffffff)):
                    out.append("statusgoal|" + hx(struct.pack("<HHI", *g)))
                for r in range(4):
                    for w in ("-", "s", "o", "v"):
                        out.append("earned|%d|%s" % (r, w))
                out += ["keep", "cycle", "save", "resetstate"]
                out += list(CALLS)
        out += setup(typ, state=-1, rewards=2)
        out += [reward(0, 0, 1, 0), reward(1, 0, 1, 5)]
        out += list(CALLS) + ["earned|0|-", "earned|1|o", "post", "keep",
                              "cycle", "save", "resetstate", "restart"]
        out += list(CALLS)
    return out


def index_cases():
    out = setup(0, players=2)
    for p in (0, 1, 2, 3):
        out.append("ev|players|%d" % p)
        for n in (-5, 0, 1, 2, 3, 99, 100, 101, 105, 120):
            out.append("r2d|%d" % n)
        for i in range(-1, 10):
            out.append("d2r|%d" % i)
    return out


def record_cases():
    out = []
    for rtype in (0, 1, 2, 3, 4):
        for cop in (0, 1):
            out += setup(0, players=1)
            out += ["rp|type|%d" % rtype, "rp|cop|%d" % cop,
                    "cm|1|0x%08x" % struct.unpack("<I", struct.pack(
                        "<f", 61.25))[0],
                    "bestlap|4321"]
            for k, (num, players) in enumerate(((0, 1), (1, 2), (100, 1),
                                                (103, 1))):
                out += ["ev|players|%d" % players,
                        "rc|%d|%d|%d|%d" % (k, num, k + 2, 1000 * (k + 1)),
                        "record|%d|%d" % (k, 4 - k)]
            out += ["rc|0|106|1|77", "ev|players|1", "record|0|8"]
    return out


def place_cases():
    out = []
    for rtype in (0, 4):
        out += setup(3, nai=5, npl=2)
        out.append("rp|type|%d" % rtype)
        for pos in ((1, 2, 3, 4, 5, 6, 7, 0), (8, 7, 6, 5, 4, 3, 2, 1),
                    (0, 0, 0, 0, 0, 0, 0, 0), (3, 3, 1, 2, 0, 5, 4, 6),
                    (9, 8, 8, 9, 8, 8, 8, 8)):
            for k, p in enumerate(pos):
                out.append("result|%d|%d|%d|%d" % (k, p, 100 * k, k))
            out += ["lastp", "firstp"]
            for i in range(-1, 9):
                out += ["rin|%d" % i, "relim|%d" % i]
            for n in (0, 1, 2, 100, 101, 102, 104, 105, 99):
                out += ["din|%d" % n, "delim|%d" % n]
            out += ["sbytes|" + hx(ko_state([0, 2, 0, 5, 0, 0, 1, 0])),
                    "lastp", "firstp"]
            for i in range(-1, 9):
                out += ["rin|%d" % i, "relim|%d" % i]
            out += ["drv|1|1|3|0|1", "drv|3|101|2|0|2", "lastp", "firstp"]
            for i in range(-1, 9):
                out.append("rin|%d" % i)
    return out


def ko_flow(npl, nai, game=8, rtype=4):
    """A knockout run race by race: results, post, another, next."""
    out = setup(3, tracks=3, opp=nai + npl - 1, nai=nai, npl=npl,
                game=game, rewards=2)
    out += ["rp|type|%d" % rtype, goal(0, 0, 1), reward(0, 0, 40, 1),
            reward(1, 0, 41, 2), "ps|" + hx(range(48)),
            "fred|players|%d" % npl]
    rng = random.Random(npl * 31 + nai * 7 + game)
    for race in range(nai + npl + 1):
        out += ["save", "status", "oldstatus"]
        live = list(range(npl + nai))
        rng.shuffle(live)
        for k in range(8):
            out.append("result|%d|0|0|0" % k)
        for place, i in enumerate(live):
            out.append("result|%d|%d|%d|%d" % (i, place + 1, 900 + i, 0))
        out += ["post", "lastp", "firstp", "another", "fell", "adv",
                "ridx", "rcount", "won", "anyearned", "earned|0|-",
                "earned|1|-"]
        out += ["next", "getst"]
        for i in range(8):
            out.append("rin|%d" % i)
        out += ["cycle", "keep"]
    out += ["restart", "status", "oldstatus", "another", "next"]
    return out


def tour_flow(tracks, npl, nai):
    out = setup(4, tracks=tracks, opp=nai + npl - 1, nai=nai, npl=npl,
                rewards=3)
    out += [goal(0, 0, 2), reward(0, 0, 40, 1), reward(1, 1, 3, 2),
            reward(2, 0, 41, 3), "ps|" + hx(range(100, 148))]
    rng = random.Random(tracks * 13 + nai)
    for race in range(tracks + 1):
        out += ["save", "status"]
        order = list(range(npl + nai))
        rng.shuffle(order)
        for k in range(8):
            out.append("result|%d|0|0|0" % k)
        for place, i in enumerate(order):
            out.append("result|%d|%d|0|0" % (i, place + 1))
        out += ["post", "ridx", "rcount", "another", "fell", "adv", "won",
                "anyearned", "next", "csp", "cycle", "keep"]
    out += ["restart", "ridx", "another"]
    return out


def status_cases():
    """StatusFell, StatusAdvanced and KeepState over old and new states."""
    out = []
    groups = (
        (0, [bytes([v]) + bytes(15) for v in (0, 1, 2, 3, 5, 9)]),
        (2, [bytes([v]) + bytes(15) for v in (0, 1, 4)]),
        (1, [word(v) + bytes(12) for v in (0, 0x7fffffff, 100, 200,
                                           0x80000000)]),
        (5, [word(v) + bytes(12) for v in (0, 150, 300)]),
        (6, [word(v) + bytes(12) for v in (0x7fffffff, 150)]),
        (3, [ko_state(r) for r in ([0] * 8, [0, 3], [2, 1], [1, 2, 3],
                                   [4, 0, 2], [3, 1, 2])]),
        (4, [bytes(b) + bytes(8) for b in ([0] * 8,
                                           [10, 6, 4, 3, 0, 0, 0, 0],
                                           [6, 10, 4, 3, 0, 0, 0, 0],
                                           [20, 12, 8, 6, 0, 0, 0, 0],
                                           [12, 20, 8, 6, 0, 0, 0, 0],
                                           [8, 12, 20, 6, 0, 0, 0, 0],
                                           [6, 20, 12, 8, 0, 0, 0, 0])]))
    for typ, ss in groups:
        for game in (8, 3):
            out += setup(typ, tracks=2, opp=3, game=game, rewards=2)
            out += [goal(0, 0, 2 if typ not in (1, 5, 6) else 160),
                    reward(0, 0, 1, 1), reward(1, 0, 2, 3)]
            for a in ss:
                for b in ss:
                    out += ["old|" + hx(a), "sbytes|" + hx(b), "fell",
                            "adv", "status", "oldstatus", "won"]
            for a in ss:
                for b in ss:
                    out += ["old|" + hx(a), "sbytes|" + hx(b), "keep",
                            "sbytes|" + hx(b), "restart"]
    return out


def another_cases():
    """IsThereAnotherRace's count of players still in."""
    out = []
    for fp in (0, 1, 2, 3):
        for elim0 in (0, 3):
            for lastk in (0, 1, 2, 3):
                out += setup(3, nai=2, npl=2)
                out += ["fred|players|%d" % fp,
                        "drv|0|0|%d|3|1" % elim0]
                for k in range(4):
                    out.append("result|%d|%d|0|0" % (
                        k, 4 if k == lastk else k + 1 - (k > lastk)))
                out += ["lastp", "another", "rp|ai|0", "another",
                        "rp|ai|1", "another"]
    return out


def misc_cases():
    out = setup(4, tracks=2, opp=3, rewards=3)
    out += [goal(0, 0, 2), reward(0, 0, 1, -3), reward(1, 0, 1, 1),
            reward(2, 0, 1, 0x7fffffff),
            "sbytes|" + hx(bytes([20, 12, 8, 6]) + bytes(12))]
    for r in range(3):
        out += ["earned|%d|-" % r]
    out += ["anyearned", "won",
            "sbytes|" + hx(bytes([8, 12, 20, 6]) + bytes(12))]
    for r in range(3):
        out += ["earned|%d|-" % r]
    out += setup(0)
    out += ["fred|aborted|1", "result|0|3|50|1", "post", "aborted",
            "fred|aborted|0", "post", "aborted", "resetres"]
    for typ in (0, 1, 3, 4, 6):
        out += setup(typ, rewards=8)
        for r in range(8):
            out.append(reward(r, r & 1, r, (r * 37) % 11))
        out += ["sbytes|" + hx(word(5) + ko_state([1])[:12]), "anyearned",
                "won"]
        for r in range(9):
            out += ["earned|%d|-" % r, "earned|%d|o" % r]
        out += ["ev|rewards|0", "anyearned", "won", "earned|0|-"]
    # Positions past a byte or a nibble, outside a tournament.
    for typ in (0, 3):
        out += setup(typ)
        out += ["result|0|300|0|0", "result|1|19|0|0", "post",
                "result|0|17|0|0", "post"]
    return out


def random_runs(rng, n=900):
    out = []
    for run in range(n):
        typ = rng.choice((-1, 0, 1, 2, 3, 3, 4, 4, 5, 6, 7))
        npl = rng.choice((0, 1, 1, 2))
        nai = rng.randint(0, 7 - npl)
        out += setup(typ, tracks=rng.randint(1, 8), opp=rng.randint(0, 7),
                     players=rng.randint(0, 3), rewards=rng.randint(0, 8),
                     state=rng.choice((400, 400, 400, -1)), nai=nai,
                     npl=npl, game=rng.choice((8, 9, 0, 3)))
        out += [goal(rng.randint(0, 3), rng.randint(0, 9),
                     rng.choice((rng.randint(0, 9),
                                 rng.randint(0, 0x30000)))),
                "rp|type|%d" % rng.choice((0, 1, 2, 3, 4, 4, 5)),
                "rp|cop|%d" % rng.randint(0, 1),
                "cm|1|0x%08x" % struct.unpack(
                    "<I", struct.pack("<f", rng.uniform(0, 500)))[0],
                "bestlap|%d" % rng.randint(0, 99999),
                "ps|" + hx(rng.getrandbits(8) for _ in range(48)),
                "last|%d" % rng.randint(0, 1),
                "fred|players|%d" % rng.choice((npl, npl, 0, 1, 2))]
        for r in range(8):
            out.append(reward(r, rng.randint(0, 2), rng.randint(0, 70),
                              rng.choice((rng.randint(0, 9),
                                          rng.randint(0, 0x30000),
                                          -rng.randint(1, 9)))))
        # Ranks and starts on the drivers, some put out.
        for k in range(npl + nai):
            if rng.random() < 0.2:
                out.append("drv|%d|%d|%d|%d|%d" % (
                    k, k if k < npl else 100 + k - npl, rng.randint(1, 8),
                    rng.randint(0, 9), 1 if k < npl else 2))
        for k in range(8):
            out.append("result|%d|%d|%d|%d" % (
                k, rng.randint(0, 8), rng.randint(0, 0x30000),
                rng.randint(0, 5)))

        def sb():
            kind = rng.randint(0, 4)
            if kind == 0:
                return bytes(16)
            if kind == 1:
                return word(rng.choice((0, 0x7fffffff, rng.randint(
                    0, 0x30000)))) + bytes(12)
            if kind == 2:
                return ko_state([rng.randint(0, 8) for _ in range(8)],
                                [rng.randint(0, 8) for _ in range(8)],
                                rng.getrandbits(32))
            if kind == 3:
                return bytes(rng.randint(0, 40) for _ in range(8)) \
                    + bytes(8)
            return bytes(rng.getrandbits(8) for _ in range(16))
        out += ["sbytes|" + hx(sb()), "old|" + hx(sb()),
                "saved|" + hx(sb())]
        for _ in range(rng.randint(4, 30)):
            c = rng.random()
            if c < 0.45:
                out.append(rng.choice(CALLS))
            elif c < 0.75:
                out.append(rng.choice(MUTATORS))
            elif c < 0.82:
                k = rng.randrange(NCARS)
                pl = rng.randint(0, 3)
                num = rng.choice([p for p in (0, 1) if p < 8]
                                 + [100 + j for j in range(8 - pl)])
                out += ["ev|players|%d" % pl,
                        "rc|%d|%d|%d|%d" % (k, num, rng.randint(0, 5),
                                            rng.randint(0, 99999)),
                        "record|%d|%d" % (k, rng.randint(0, 8))]
            elif c < 0.9:
                out.append("result|%d|%d|%d|%d" % (
                    rng.randrange(8), rng.randint(0, 8),
                    rng.randint(0, 99999), rng.randint(0, 5)))
            elif c < 0.95:
                out.append("sbytes|" + hx(sb()))
            else:
                w = rng.choice("-sov")
                out.append("earned|%d|%s" % (rng.randint(0, 8), w))
    return out


def script():
    return (type_sweep() + index_cases() + record_cases() + place_cases()
            + ko_flow(1, 3) + ko_flow(1, 7) + ko_flow(2, 2) + ko_flow(1, 1)
            + ko_flow(1, 3, game=3) + ko_flow(1, 5, rtype=0)
            + tour_flow(3, 1, 3) + tour_flow(4, 1, 7) + tour_flow(1, 2, 2)
            + status_cases() + another_cases() + misc_cases()
            + random_runs(random.Random(0x6b2)))


# ================================================================= running

def build_harness(tmp, name="raceevent_test"):
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


def write_inputs(d):
    lines = script()
    sc = Path(d) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    return lines, sc


# ============================================================= mutations

def _m(name, old, new, f=RE):
    return (name, f, old, new)


KOFELL = ("    case GROUP_KO:\n        if (!fred_use_tree_event(&Fred))\n"
          "            return 0;\n        if ((s = raceevent_get_ko_state(ev))"
          " == NULL)\n            return 0;\n        o = ko_state_get_rank("
          "ev->aOldState, 0);\n        n = ko_state_get_rank(s, 0);\n"
          "        if (o == 0)\n")
KOADV = KOFELL.replace("        if (o == 0)\n", "        if (n == 0)\n")
NRKO = ("        k = raceevent_get_last_place(ev);\n"
        "        race_parameters_eliminate_driver(\n"
        "            rp, raceevent_driver_number_from_racer_index(ev, k),\n"
        "            ev->aResults[k].nPosition);\n"
        "        raceevent_calc_starting_positions(ev);\n")
RST = ("    race_parameters_restore_eliminated(&TheRaceParameters);\n"
       "    race_parameters_reset_start_positions(&TheRaceParameters);\n")

MUTATIONS = [
    # ---- the type groups and the helpers
    _m("grp-lapko", "    case EVENT_LAP_KNOCKOUT:\n        return GROUP_RANK;",
       "        return GROUP_RANK;\n    case EVENT_LAP_KNOCKOUT:"),
    _m("grp-p2p", "    case EVENT_POINT2POINT:\n", ""),
    _m("grp-cop", "    case EVENT_BE_A_COP:\n", ""),
    _m("grp-tt", "    case EVENT_TIME_TRIAL:\n", ""),
    _m("grp-def", "        return GROUP_NONE;", "        return GROUP_RANK;"),
    _m("grp-ko", "        return GROUP_KO;", "        return GROUP_TOURNAMENT;"),
    _m("nostate", "static const uint8_t kNoState[16];",
       "static const uint8_t kNoState[16] = { 1, 1, 1, 1 };"),
    _m("ts-zero", "return t != 0 && t != 0x7fffffff;",
       "return t != 0x7fffffff;"),
    _m("ts-max", "return t != 0 && t != 0x7fffffff;", "return t != 0;"),
    _m("rw-bound", "if (i >= ev->nRewards || i < 0 || i >= 8)",
       "if (i > ev->nRewards || i < 0 || i >= 8)"),
    _m("ss-time", "        return 4;", "        return 16;"),
    _m("ss-16", "        return 16;\n    default:\n        return 1;",
       "        return 8;\n    default:\n        return 1;"),
    _m("ss-def", "        return 16;\n    default:\n        return 1;",
       "        return 16;\n    default:\n        return 4;"),
    _m("mt-3", "- 3) < 2u", "- 3) < 3u"),
    _m("mt-signed", "(uint32_t)((uint16_t)ev->nType - 3) < 2u",
       "(ev->nType - 3) < 2"),
    _m("ab-0", "return fred_race_was_aborted(&Fred);", "return 0;"),
    _m("rr-7", "for (i = 0; i < 8; i++)\n        memset(&ev->aResults[i]",
       "for (i = 0; i < 7; i++)\n        memset(&ev->aResults[i]"),
    # ---- the indexes
    _m("ri-lt", "return n < 100 ? n", "return n <= 100 ? n"),
    _m("ri-off", "ev->nInitialPlayers + n - 100",
       "ev->nInitialPlayers + n - 99"),
    _m("dn-lt", "return i < ev->nInitialPlayers ? i",
       "return i <= ev->nInitialPlayers ? i"),
    _m("dn-off", "i - (ev->nInitialPlayers - 100)",
       "i - (ev->nInitialPlayers - 101)"),
    # ---- RecordResults
    _m("rec-tt", "TheRaceParameters.RaceType == RACE_TYPE_TIME_TRIAL",
       "TheRaceParameters.RaceType != RACE_TYPE_TIME_TRIAL"),
    _m("rec-cop", "if (TheRaceParameters.BeACop)\n        timer_set_time",
       "if (!TheRaceParameters.BeACop)\n        timer_set_time"),
    _m("rec-pos", "ev->aResults[idx].nPosition = pos;",
       "ev->aResults[idx].nPosition = pos + 1;"),
    _m("rec-reason", "ev->aResults[idx].nFinishReason = reason;",
       "ev->aResults[idx].nFinishReason = 0;"),
    _m("rec-time", "ev->aResults[idx].Time = t;",
       "ev->aResults[idx].Time = rc->RaceTime;"),
    _m("rec-bound", "if ((uint32_t)idx < 8u) {", "if ((uint32_t)idx < 7u) {"),
    _m("rec-idx", "        ev, rc->pCar->DriverNumber);",
       "        ev, rc->pCar->DriverNumber + 1);"),
    # ---- in the race, put out
    _m("din-rank", "return d != NULL && d->EliminatedRank == 0;",
       "return d != NULL;"),
    _m("din-null", "return d != NULL && d->EliminatedRank == 0;",
       "return d == NULL || d->EliminatedRank == 0;"),
    _m("rin-map", "    return raceevent_driver_in_the_race(\n"
       "        ev, raceevent_driver_number_from_racer_index(ev, i));",
       "    return raceevent_driver_in_the_race(ev, i);"),
    _m("re-type", "if (TheRaceParameters.RaceType != RACE_TYPE_RACE_KNOCKOUT)",
       "if (TheRaceParameters.RaceType != RACE_TYPE_TIME_TRIAL)"),
    _m("re-rank", "return ko_state_get_rank(rd(ev->pState), i) != 0;",
       "return ko_state_get_rank(rd(ev->pState), i) > 1;"),
    _m("de-map", "    return raceevent_racer_eliminated(\n"
       "        ev, raceevent_racer_index_from_driver_number(ev, n));",
       "    return raceevent_racer_eliminated(ev, n);"),
    _m("lp-lt", "if (best < ev->aResults[i].nPosition) {",
       "if (best <= ev->aResults[i].nPosition) {"),
    _m("lp-in", "            continue;\n        if (best <",
       "            {}\n        if (best <"),
    _m("fp-lt", "if (ev->aResults[i].nPosition < best) {",
       "if (ev->aResults[i].nPosition <= best) {"),
    _m("fp-8", "int32_t i, best = 8, at = 0;", "int32_t i, best = 9, at = 0;"),
    _m("fp-in", "            continue;\n        if (ev->aResults[i].nPosition <",
       "            {}\n        if (ev->aResults[i].nPosition <"),
    _m("gs-rank", "return group(ev) == GROUP_RANK ? ev->pState : NULL;",
       "return group(ev) == GROUP_TIME ? ev->pState : NULL;"),
    _m("gs-tour", "return group(ev) == GROUP_TOURNAMENT ? ev->pState : NULL;",
       "return group(ev) == GROUP_KO ? ev->pState : NULL;"),
    _m("gs-ko", "return group(ev) == GROUP_KO ? ev->pState : NULL;",
       "return group(ev) != GROUP_KO ? ev->pState : NULL;"),
    _m("gs-time", "return group(ev) == GROUP_TIME ? ev->pState : NULL;",
       "return group(ev) == GROUP_RANK ? ev->pState : NULL;"),
    # ---- PostResults
    _m("pr-abort", "if (raceevent_race_was_aborted(ev))\n        return;",
       "if (0)\n        return;"),
    _m("pr-rank", "s[0] = (uint8_t)r[0].nPosition;",
       "s[0] = (uint8_t)r[1].nPosition;"),
    _m("pr-time", "memcpy(s, &r[0].Time.PackedTime, 4);",
       "memcpy(s, &r[1].Time.PackedTime, 4);"),
    _m("pr-ko-last", "        k = raceevent_get_last_place(ev);\n"
       "        ko_state_set_rank(s, k, r[k].nPosition);",
       "        k = raceevent_get_first_place(ev);\n"
       "        ko_state_set_rank(s, k, r[k].nPosition);"),
    _m("pr-ko-3", "            < 3) {", "            < 2) {"),
    _m("pr-ko-first", "            k = raceevent_get_first_place(ev);",
       "            k = raceevent_get_last_place(ev);"),
    _m("pr-ko-start", "ko_state_set_start_position(s, i, r[i].nPosition);",
       "ko_state_set_start_position(s, i, r[0].nPosition);"),
    _m("pr-ko-pos", "        ko_state_set_rank(s, k, r[k].nPosition);\n"
       "        if (",
       "        ko_state_set_rank(s, k, r[k].nPosition + 1);\n        if ("),
    _m("pr-tour-pos", "                                            r[i].nPosition - 1));",
       "                                            r[i].nPosition));"),
    _m("pr-tour-8", "        for (i = 0; i < 8; i++) {\n            if (r[i]",
       "        for (i = 0; i < 7; i++) {\n            if (r[i]"),
    _m("pr-tour-add", "s[i] = (uint8_t)(s[i] + tournament",
       "s[i] = (uint8_t)(tournament"),
    # ---- the state copies
    _m("sv-size", "    memcpy(ev->aSavedState, rd(ev->pState),\n"
       "           (size_t)raceevent_get_state_size(ev));",
       "    memcpy(ev->aSavedState, rd(ev->pState), 16);"),
    _m("sv-old", "    memcpy(ev->aSavedState, rd(ev->pState),",
       "    memcpy(ev->aOldState, rd(ev->pState),"),
    _m("cy-multi", "    if (!raceevent_is_multi_track(ev)\n"
       "        || !raceevent_is_there_another_race(ev))",
       "    if (!raceevent_is_multi_track(ev))"),
    _m("cy-put", "    put_state(ev, ev->aSavedState);\n}", "}"),
    _m("cy-old", "        memcpy(ev->aOldState, rd(ev->pState),\n"
       "               (size_t)raceevent_get_state_size(ev));\n"
       "    put_state",
       "        memcpy(ev->aSavedState, rd(ev->pState),\n"
       "               (size_t)raceevent_get_state_size(ev));\n"
       "    put_state"),
    _m("ks-fell", "if (raceevent_status_fell(ev))\n        put_state",
       "if (!raceevent_status_fell(ev))\n        put_state"),
    # ---- Restart
    _m("rs-another", "if (!raceevent_is_there_another_race(ev) && "
       "!raceevent_status_fell(ev))", "if (!raceevent_status_fell(ev))"),
    _m("rs-fell", "if (!raceevent_is_there_another_race(ev) && "
       "!raceevent_status_fell(ev))",
       "if (!raceevent_is_there_another_race(ev))"),
    _m("rs-reset", "    raceevent_reset_state(ev);\n"
       "    raceevent_reset_results(ev);", "    raceevent_reset_results(ev);"),
    _m("rs-results", "    raceevent_reset_state(ev);\n"
       "    raceevent_reset_results(ev);", "    raceevent_reset_state(ev);"),
    _m("rs-restore", RST, RST.split("\n")[1] + "\n"),
    _m("rs-startpos", RST, RST.split("\n")[0] + "\n"),
    _m("rs-order", RST, RST.split("\n")[1] + "\n" + RST.split("\n")[0] + "\n"),
    _m("rs-csp", "    fred_calculate_starting_positions(&Fred);\n", ""),
    _m("rs-track", "gEventTrackSetRaceOnFn(&ev->aTracks[0], &TheRaceParameters);",
       "gEventTrackSetRaceOnFn(&ev->aTracks[1], &TheRaceParameters);"),
    # ---- StatusFell
    _m("sf-lt", "    if (cur < old)\n        return old != EVENT_FAILED;",
       "    if (cur <= old)\n        return old != EVENT_FAILED;"),
    _m("sf-failed", "return old != EVENT_FAILED;", "return old != EVENT_PASSED;"),
    _m("sf-ne", "    if (old != cur)\n        return 0;",
       "    if (old != cur)\n        return 1;"),
    _m("sf-rank-o0", "        o = ev->aOldState[0];\n        if (o == 0)\n"
       "            return 0;", "        o = ev->aOldState[0];\n"
       "        if (o == 0)\n            return 1;"),
    _m("sf-rank-n0", "        n = s[0];\n        if (n == 0)\n            return 1;",
       "        n = s[0];\n        if (n == 0)\n            return 0;"),
    _m("sf-rank-lt", "        return o < n;\n    case GROUP_TIME:",
       "        return o <= n;\n    case GROUP_TIME:"),
    _m("sf-time-o", "        o = rd32(ev->aOldState);\n        if (!time_set(o))\n"
       "            return 0;", "        o = rd32(ev->aOldState);\n"
       "        if (!time_set(o))\n            return 1;"),
    _m("sf-time-n", "        n = rd32(s);\n        if (!time_set(n))\n"
       "            return 1;", "        n = rd32(s);\n"
       "        if (!time_set(n))\n            return 0;"),
    _m("sf-time-lt", "        return o < n;\n    case GROUP_KO:",
       "        return o <= n;\n    case GROUP_KO:"),
    _m("sf-ko-tree", KOFELL, KOFELL.replace("!fred_use_tree_event", "0 && "
                                            "!fred_use_tree_event")),
    _m("sf-ko-o0", "        if (o == 0)\n            return n != 0;",
       "        if (o == 0)\n            return n == 0;"),
    _m("sf-ko-n0", "        if (n == 0)\n            return 0;\n"
       "        return o < n;", "        if (n == 0)\n            return 1;\n"
       "        return o < n;"),
    _m("sf-ko-lt", "        return o < n;\n    case GROUP_TOURNAMENT:",
       "        return o <= n;\n    case GROUP_TOURNAMENT:"),
    _m("sf-tour-2", "        if (old < 2)\n            return 0;",
       "        if (old < 3)\n            return 0;"),
    _m("sf-tour-lt", "               < (uint32_t)tournament_state_user_rank(s);",
       "               <= (uint32_t)tournament_state_user_rank(s);"),
    _m("sf-tour-sign", "        return (uint32_t)tournament_state_user_rank("
       "ev->aOldState)\n               < (uint32_t)",
       "        return (uint32_t)tournament_state_user_rank("
       "ev->aOldState) + 1\n               < (uint32_t)"),
    # ---- StatusAdvanced
    _m("sa-ne", "    if (old != cur)\n        return old < cur;",
       "    if (old != cur)\n        return old > cur;"),
    _m("sa-rank-n0", "        n = s[0];\n        if (n == 0)\n            return 0;",
       "        n = s[0];\n        if (n == 0)\n            return 1;"),
    _m("sa-rank-o0", "        o = ev->aOldState[0];\n        if (o == 0)\n"
       "            return 1;", "        o = ev->aOldState[0];\n"
       "        if (o == 0)\n            return 0;"),
    _m("sa-rank-lt", "        return n < o;\n    case GROUP_TIME:",
       "        return n <= o;\n    case GROUP_TIME:"),
    _m("sa-time-n", "        n = rd32(s);\n        if (!time_set(n))\n"
       "            return 0;", "        n = rd32(s);\n"
       "        if (!time_set(n))\n            return 1;"),
    _m("sa-time-o", "        o = rd32(ev->aOldState);\n        if (!time_set(o))\n"
       "            return 1;", "        o = rd32(ev->aOldState);\n"
       "        if (!time_set(o))\n            return 0;"),
    _m("sa-time-lt", "        return n < o;\n    case GROUP_KO:",
       "        return n <= o;\n    case GROUP_KO:"),
    _m("sa-ko-tree", KOADV, KOADV.replace("!fred_use_tree_event", "0 && "
                                          "!fred_use_tree_event")),
    _m("sa-ko-n0", "        if (n == 0)\n            return o != 0;",
       "        if (n == 0)\n            return o == 0;"),
    _m("sa-ko-o0", "        if (o == 0)\n            return 0;\n"
       "        return n < o;", "        if (o == 0)\n            return 1;\n"
       "        return n < o;"),
    _m("sa-ko-lt", "        return n < o;\n    case GROUP_TOURNAMENT:",
       "        return n <= o;\n    case GROUP_TOURNAMENT:"),
    _m("sa-tour-3", "        if (cur < 3)\n            return 0;",
       "        if (cur < 4)\n            return 0;"),
    _m("sa-tour-2", "        if (old < 2)\n            return 1;",
       "        if (old < 2)\n            return 0;"),
    _m("sa-tour-lt", "        return (uint32_t)tournament_state_user_rank(s)\n"
       "               < (uint32_t)", "        return (uint32_t)"
       "tournament_state_user_rank(s)\n               <= (uint32_t)"),
    # ---- the race index and count
    _m("ri-ko", "    if (ev->nType == EVENT_RACE_KNOCKOUT)\n"
       "        return ev->pState != NULL ? ko_state_get_race_index",
       "    if (ev->nType == EVENT_LAP_KNOCKOUT)\n"
       "        return ev->pState != NULL ? ko_state_get_race_index"),
    _m("ri-tour", "    if (ev->nType == EVENT_TOURNAMENT)\n"
       "        return ev->pState != NULL\n",
       "    if (ev->nType == EVENT_POINT2POINT)\n"
       "        return ev->pState != NULL\n"),
    _m("ri-tour-opp", "                                                     "
       "ev->nOpponents)", "                                                  "
       "   ev->nTracks)"),
    _m("rc-ko", "    if (ev->nType == EVENT_RACE_KNOCKOUT)\n"
       "        return ev->nOpponents;", "    if (ev->nType == "
       "EVENT_RACE_KNOCKOUT)\n        return ev->nTracks;"),
    _m("rc-tour", "        return ev->nTracks;\n    return 1;",
       "        return ev->nOpponents;\n    return 1;"),
    _m("rc-1", "        return ev->nTracks;\n    return 1;",
       "        return ev->nTracks;\n    return 0;"),
    _m("nt-mod", "k = idx % ev->nTracks;", "k = (idx + 1) % ev->nTracks;"),
    _m("nt-idx", "int32_t idx = raceevent_get_race_index(ev), k;",
       "int32_t idx = 0, k;"),
    # ---- SetupNextRace
    _m("nr-another", "    if (!raceevent_is_there_another_race(ev))\n"
       "        return 0;\n    rp->PlayerSettings",
       "    if (0)\n        return 0;\n    rp->PlayerSettings"),
    _m("nr-ps", "    rp->PlayerSettings[0] = Fred.FrontendPlayers[0]"
       ".mPlayerSettings;\n", ""),
    _m("nr-elim-pos", NRKO, NRKO.replace("nPosition);", "nPosition + 1);")),
    _m("nr-elim-map", NRKO, NRKO.replace(
        "raceevent_driver_number_from_racer_index(ev, k),", "k,")),
    _m("nr-elim-k", NRKO, NRKO.replace("get_last_place", "get_first_place")),
    _m("nr-ko-csp", NRKO, NRKO.replace(
        "        raceevent_calc_starting_positions(ev);\n", "")),
    _m("nr-ko-order", NRKO, "        raceevent_calc_starting_positions(ev);\n"
       + NRKO.replace("        raceevent_calc_starting_positions(ev);\n",
                      "")),
    _m("nr-ko-track", NRKO + "        set_next_track(ev);\n", NRKO),
    _m("nr-tour-csp", "        raceevent_calc_starting_positions(ev);\n"
       "        set_next_track(ev);\n    }\n    return 1;",
       "        set_next_track(ev);\n    }\n    return 1;"),
    _m("nr-tour-track", "        raceevent_calc_starting_positions(ev);\n"
       "        set_next_track(ev);\n    }\n    return 1;",
       "        raceevent_calc_starting_positions(ev);\n    }\n    return 1;"),
    _m("nr-ret", "        set_next_track(ev);\n    }\n    return 1;",
       "        set_next_track(ev);\n    }\n    return 2;"),
    # ---- CalcStartingPositions
    _m("cs-ko-0", "        if (raceevent_get_race_index(ev) == 0)\n"
       "            return 0;\n        rp->PlayerStartPosition[0] = "
       "(int8_t)ev->aResults[0]",
       "        rp->PlayerStartPosition[0] = (int8_t)ev->aResults[0]"),
    _m("cs-ko-p0", "rp->PlayerStartPosition[0] = (int8_t)ev->aResults[0]"
       ".nPosition;", "rp->PlayerStartPosition[0] = (int8_t)ev->aResults[1]"
       ".nPosition;"),
    _m("cs-ko-p1", "rp->PlayerStartPosition[1] = (int8_t)ev->aResults[1]"
       ".nPosition;", "rp->PlayerStartPosition[1] = (int8_t)ev->aResults[0]"
       ".nPosition;"),
    _m("cs-ko-elim", "            if (d != NULL && d->EliminatedRank == 0)\n"
       "                d->StartingPosition = (int8_t)ev->aResults",
       "            if (d != NULL)\n"
       "                d->StartingPosition = (int8_t)ev->aResults"),
    _m("cs-ko-pos", "d->StartingPosition = (int8_t)ev->aResults[i].nPosition;",
       "d->StartingPosition = (int8_t)ev->aResults[0].nPosition;"),
    _m("cs-tour-0", "        if (raceevent_get_race_index(ev) == 0)\n"
       "            return 0;\n        ts = ", "        ts = "),
    _m("cs-tour-user", "rp->PlayerStartPosition[0] = (int8_t)"
       "tournament_state_user_rank(ts);", "rp->PlayerStartPosition[0] = "
       "(int8_t)tournament_state_racer_rank(ts, 1);"),
    _m("cs-tour-elim", "            if (d != NULL && d->EliminatedRank == 0)\n"
       "                d->StartingPosition =\n",
       "            if (d != NULL)\n                d->StartingPosition =\n"),
    _m("cs-tour-rank", "(int8_t)tournament_state_racer_rank(ts, i);",
       "(int8_t)tournament_state_racer_rank(ts, 0);"),
    _m("cs-tour-map", "        for (i = 0; i < 8; i++) {\n"
       "            d = race_parameters_find_driver(\n"
       "                rp, raceevent_driver_number_from_racer_index(ev, i));"
       "\n            if (d != NULL && d->EliminatedRank == 0)\n"
       "                d->StartingPosition =\n",
       "        for (i = 0; i < 8; i++) {\n"
       "            d = race_parameters_find_driver(rp, i);"
       "\n            if (d != NULL && d->EliminatedRank == 0)\n"
       "                d->StartingPosition =\n"),
    _m("cs-ret", "        return 1;\n    }\n    return 0;\n}\n\n"
       "int32_t raceevent_is_there_another_race",
       "        return 1;\n    }\n    return 2;\n}\n\n"
       "int32_t raceevent_is_there_another_race"),
    # ---- IsThereAnotherRace
    _m("an-loop", "for (i = 0; i < Fred.NumPlayerCars; i++) {",
       "for (i = 0; i <= Fred.NumPlayerCars; i++) {"),
    _m("an-u1", "ev, raceevent_get_last_place(ev)) <= 1u)",
       "ev, raceevent_get_last_place(ev)) < 1u)"),
    _m("an-n", "        if (n <= 0)\n            return 0;",
       "        if (n < 0)\n            return 0;"),
    _m("an-3", "               >= 3;\n    }", "               >= 2;\n    }"),
    _m("an-tour", "        return raceevent_get_race_index(ev) + 1\n"
       "               <= raceevent_get_race_count(ev);",
       "        return raceevent_get_race_index(ev) + 1\n"
       "               < raceevent_get_race_count(ev);"),
    # ---- the statuses
    _m("so-tour-args", "        return tournament_state_get_status(s, "
       "&ev->Objective, ev->nTracks,\n"
       "                                           ev->nOpponents);",
       "        return tournament_state_get_status(s, "
       "&ev->Objective, ev->nOpponents,\n"
       "                                           ev->nTracks);"),
    _m("so-ko", "        return ko_state_get_status(s, &ev->Objective);",
       "        return rank_state_get_status(s, &ev->Objective);"),
    _m("so-time", "        return time_state_get_status(s, &ev->Objective);",
       "        return rank_state_get_status(s, &ev->Objective);"),
    _m("so-def", "        return EVENT_UNTRIED;\n    }\n}\n\n"
       "int32_t raceevent_get_status_goal",
       "        return EVENT_INPROGRESS;\n    }\n}\n\n"
       "int32_t raceevent_get_status_goal"),
    _m("sg-rank", "        return rank_state_get_status(s, goal);",
       "        return rank_state_get_status(s, &ev->Objective);"),
    _m("sg-time", "        return time_state_get_status(s, goal);",
       "        return time_state_get_status(s, &ev->Objective);"),
    _m("sg-ko", "        return ko_state_get_status(s, goal);",
       "        return ko_state_get_status(s, &ev->Objective);"),
    _m("sg-tour", "        return tournament_state_get_status(s, goal, "
       "ev->nTracks,", "        return tournament_state_get_status(s, "
       "&ev->Objective, ev->nTracks,"),
    _m("sg-def", "        return EVENT_UNTRIED;\n    }\n}\n\n"
       "int32_t raceevent_get_status(const",
       "        return EVENT_INPROGRESS;\n    }\n}\n\n"
       "int32_t raceevent_get_status(const"),
    _m("st-old", "return raceevent_get_status_of(ev, ev->aOldState);",
       "return raceevent_get_status_of(ev, ev->aSavedState);"),
    _m("st-cur", "return raceevent_get_status_of(ev, ev->pState);\n}",
       "return raceevent_get_status_of(ev, ev->aOldState);\n}"),
    _m("rst-rank", "        rank_state_reset(ev->pState);",
       "        time_state_reset(ev->pState);"),
    _m("rst-time", "        time_state_reset(ev->pState);",
       "        rank_state_reset(ev->pState);"),
    _m("rst-ko", "        ko_state_reset(ev->pState);",
       "        rank_state_reset(ev->pState);"),
    _m("rst-tour", "        tournament_state_reset(ev->pState);",
       "        ko_state_reset(ev->pState);"),
    # ---- the rewards
    _m("er-state", "const uint8_t *s = state != NULL ? state : ev->pState;",
       "const uint8_t *s = ev->pState;"),
    _m("er-status", "if (raceevent_get_status_of(ev, s) < EVENT_FAILED)",
       "if (raceevent_get_status_of(ev, s) < EVENT_INPROGRESS)"),
    _m("er-rank", "return !(r->nData < (int32_t)s[0]);",
       "return !(r->nData <= (int32_t)s[0]);"),
    _m("er-time", "return !(r->nData < rd32(s));",
       "return !(r->nData <= rd32(s));"),
    _m("er-ko", "return !(r->nData < ko_state_get_rank(s, 0));",
       "return !(r->nData <= ko_state_get_rank(s, 0));"),
    _m("er-tour", "        return !((uint32_t)r->nData\n"
       "                 < (uint32_t)", "        return !((uint32_t)"
       "r->nData\n                 <= (uint32_t)"),
    _m("er-tour-sign", "        return !((uint32_t)r->nData\n"
       "                 < (uint32_t)", "        return !(r->nData\n"
       "                 < (int32_t)"),
    _m("er-def", "                 < (uint32_t)tournament_state_user_rank(s))"
       ";\n    default:\n        return 0;",
       "                 < (uint32_t)tournament_state_user_rank(s))"
       ";\n    default:\n        return 1;"),
    _m("ae-loop", "for (i = 0; i < ev->nRewards; i++) {\n"
       "        if (raceevent_reward_earned",
       "for (i = 1; i < ev->nRewards; i++) {\n"
       "        if (raceevent_reward_earned"),
    _m("ae-state", "if (raceevent_reward_earned(ev, i, NULL))",
       "if (raceevent_reward_earned(ev, i, ev->aOldState))"),
    _m("uw-status", "if (raceevent_get_status_of(ev, ev->pState) < "
       "EVENT_FAILED)", "if (raceevent_get_status_of(ev, ev->pState) < "
       "EVENT_PASSED)"),
    _m("uw-rank", "        return s[0] == 1;", "        return s[0] <= 1;"),
    _m("uw-time", "if (ev->aRewards[i].nData < t)",
       "if (ev->aRewards[i].nData <= t)"),
    _m("uw-time-loop", "for (i = 0; i < ev->nRewards && i < 8; i++) {",
       "for (i = 1; i < ev->nRewards && i < 8; i++) {"),
    _m("uw-ko", "        return ko_state_get_rank(s, 0) == 1;",
       "        return ko_state_get_rank(s, 0) <= 1;"),
    _m("uw-tour", "        return tournament_state_user_rank(s) == 1;",
       "        return tournament_state_user_rank(s) == 2;"),
    _m("uw-def", "        return tournament_state_user_rank(s) == 1;\n"
       "    default:\n        return 0;",
       "        return tournament_state_user_rank(s) == 1;\n"
       "    default:\n        return 1;"),
    # ---- raceparams.c's ResetStartPositions, new with RE-6b
    _m("rsp-1", "rp->PlayerStartPosition[0] = (int8_t)(rp->NumAICars + 1);",
       "rp->PlayerStartPosition[0] = (int8_t)(rp->NumAICars + 2);", RPC),
    _m("rsp-2", "rp->PlayerStartPosition[1] = (int8_t)(rp->NumAICars + 2);",
       "rp->PlayerStartPosition[1] = (int8_t)(rp->NumAICars + 1);", RPC),
    _m("rsp-range", "d->StartingPosition = n >= 0 && n < 2 ? "
       "rp->PlayerStartPosition[n]", "d->StartingPosition = n >= 0 && n < 1 ? "
       "rp->PlayerStartPosition[n]", RPC),
    _m("rsp-else", "                                              : 0;",
       "                                              : d->StartingPosition;",
       RPC),
]

EQUIVALENT = {
    # Each of these branches is reached only when the old and new statuses
    # are equal, and the state it tests cannot give an equal status: a
    # rank, time or knockout state that has a result is FAILED or PASSED,
    # one with none UNTRIED or IN PROGRESS. Retail has the same dead arms.
    "sf-rank-n0": "an old place and no new one never have equal statuses",
    "sf-time-n": "an old time and no new one never have equal statuses",
    "sf-ko-n0": "an old rank and no new one never have equal statuses",
    "sa-rank-o0": "a new place and no old one never have equal statuses",
    "sa-time-o": "a new time and no old one never have equal statuses",
    "sa-ko-o0": "a new rank and no old one never have equal statuses",
    "sa-tour-2": "old equals cur, which is 3 or more by then",
    # The default arms after a status of FAILED or better: a type outside
    # the four groups is always UNTRIED.
    "er-def": "a type outside the groups never passes the status test",
    "uw-def": "a type outside the groups never passes the status test",
    # FAILED or better means a place, or a first rank, that is not 0.
    "uw-rank": "a FAILED or PASSED rank state's place is never 0",
    "uw-ko": "a FAILED or PASSED knockout's first rank is never 0",
    # Both resets zero bytes 0 to 7 and nothing else.
    "rst-tour": "EventKoState::Reset and the tournament's clear the same bytes",
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
    lines, scp = write_inputs(indir.name)
    base_lines = model(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text(encoding="latin-1").splitlines()
        if diff(base_lines, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "raceevent_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
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
        lines, scp = write_inputs(tmp)
        got = model(lines)
        exe = build_harness(tmp)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text(encoding="latin-1").splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(got) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(got, harness)
    print("%d ops, %d lines, %d differ" % (len(lines), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
