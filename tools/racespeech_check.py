#!/usr/bin/env python3
"""Cross-check 3DS Files/source/racespeech.c, the race's own speech
(RE-5, 14-10c), and the speech conversions it uses in speechconv.c,
against the retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own code: RaceSpeech.obj from FlipCoinNoReplay
(0x00206900) to PlayerSingleP1OrP2 (0x00207840), with
RaceCoordinator::IsReplayDemoMode (0x001369a8), and Speech's
ConvertRewardCarType, the four event conversions, ConvertTrackNumber and
the unlocked track's (0x00223328 .. 0x00223480). The harness
(tools/src/racespeech_test.c) runs the port and prints the same lines.

**The stubs**, logged and answered by the same rule on both sides:
bRandom and RaceEvent::GetStatus (a queue, then an answer), the event's
won test at 0x00200c38 (the same), SPCH_AddEventV (each event and its
parameters), RacingCar::GetLastLapTime and GetBestLapTimesTable (the
time each answers, set by the script). TheRaceParameters, the race, the
coordinator, the cop manager's pullovers, the players, the cars and
their racing cars, the car types, Fred's game type and the event are
memory both sides read.

**Compared** are the stubs' logs, each answer, the two lap speeches'
four fields, and the players' HasHeardRaceOverSpeech and New2696 after
each call that sets them.

    python tools/racespeech_check.py
    python tools/racespeech_check.py --mutate [--only a,b]
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
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/racespeech_test.c"
RS = "3DS Files/source/racespeech.c"
SC = "3DS Files/source/speechconv.c"
SOURCES = [HARNESS, RS, SC]
HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = retail_model.RETAIL_GP
RP = 0x0031a898                         # TheRaceParameters
RP_FIELDS = {"Track": 0, "Dir": 12, "RaceType": 32, "Laps": 44,
             "Players": 48, "AI": 52, "EventTree": 600, "BeACop": 628}
EVENT = 0x0031b600                      # TheRaceEvent
EV_NUMBER, EV_WORD = 104, 120
FRED = 0x002fc050
FRED_GAMETYPE = FRED + 0x1072c
G_RACE = GP - 22272                     # pCurrentRace
G_RC = GP - 22216                       # pRaceCoordinator
G_COPMGR = GP - 15620                   # pCopManager
G_PPN = GP - 20936                      # PlayerPlayersByNumber[2]
G_CTI = GP - 20616                      # the car types, 1376 bytes each

F_FINISHED = 0x00206ab8
F_EVSPEECH = 0x00206bc8
F_LAP1 = 0x00206d98
F_LAP2 = 0x00206eb8
F_KO = 0x00207018
F_LAP = 0x00207198
F_LAPR = 0x00207298
F_TIMER = 0x00207330
F_TOUR = 0x002073f0
F_EVREWARD = 0x00207450
F_RCAR = 0x00207488
F_RTRACK = 0x00207550
F_POINTS = 0x002075b0
F_PULLOVER = 0x002075d8
F_ARREST = 0x00207648
F_BUSTED = 0x002077b8
CONV = {"reward": 0x00223328, "hpa": 0x00223358, "hpb": 0x00223378,
        "cha": 0x00223398, "chb": 0x002233b8, "track": 0x002233d8,
        "unlock": 0x00223480}

S_RANDOM = 0x0025a488
S_SPCH = 0x002919d0
S_STATUS = 0x00202658
S_WON = 0x00200c38
S_LASTLAP = 0x00147570
S_BEST = 0x00186dd0

NCARS, NCTI, QN = 4, 71, 16
PLAYER_SIZE, CAR_SIZE, RCAR_SIZE, CTI_SIZE = 2704, 32, 32, 1376
PL_CAR, PL_HEARD, PL_NEW = 4, 2692, 2696
CAR_INDEX, CAR_CTI, CAR_PLAYER, CAR_RC = 8, 12, 24, 28
RC_POS, RC_LAPX = 10, 20
CTI_HP, CTI_CLASS, CTI_USAGE = 228, 230, 1336
RACE_BEST, RACE_NCARS = 20, 24
CM_ARREST, CM_STRIDE = 108, 28
ROW_FINISH = 8


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def Fx(f):
    return "0x%08x" % fbits(f)


def Fn(f, ulps):
    """`f` moved `ulps` floats up (down for negative), as bits."""
    b = fbits(f)
    return "0x%08x" % ((b + ulps) & M32 if f >= 0 else (b - ulps) & M32)


# ================================================================== model

class Queue(object):
    def __init__(self):
        self.q, self.i, self.answer = [], 0, 0

    def fill(self, vals):
        self.q, self.i = vals[:QN], 0

    def next(self):
        if self.i < len(self.q):
            r = self.q[self.i]
            self.i += 1
            return r
        return self.answer


class Model(object):
    def __init__(self):
        e = self.e = retail_model.RetailEmu(ieee=True)
        self.out = []

        def block(n):
            p = e.alloc(n, align=16)
            e.write(p, bytes(n))
            return p
        self.race = block(32)
        self.rco = block(16)
        self.cm = block(88 + CM_STRIDE * 8)
        self.players = [block(PLAYER_SIZE) for _ in range(2)]
        self.cars = [block(CAR_SIZE) for _ in range(NCARS)]
        self.rcs = [block(RCAR_SIZE) for _ in range(NCARS)]
        self.cti = block(CTI_SIZE * NCTI)
        self.rows = [block(16) for _ in range(2)]
        self.reward = block(16)
        self.lastlap = block(16)
        self.best = block(48)
        self.d = block(16)
        e.put32(G_RACE, self.race)
        e.put32(G_CTI, self.cti + 2 * CTI_SIZE)
        self.randq, self.statusq, self.wonq = Queue(), Queue(), Queue()
        for addr, fn in ((S_RANDOM, self.s_random), (S_SPCH, self.s_spch),
                         (S_STATUS, self.s_status), (S_WON, self.s_won),
                         (S_LASTLAP, self.s_lastlap), (S_BEST, self.s_best)):
            e.stub(addr, fn)

    def emit(self, line):
        self.out.append(line)

    def put8(self, a, v):
        self.e.write(a, bytes([v & 0xff]))

    def put16(self, a, v):
        self.e.write(a, struct.pack("<H", v & 0xffff))

    def player_at(self, k):
        return 0 if k < 0 else self.players[k]

    def flags(self):
        e, p = self.e, self.players
        self.emit("  P0 %d %d P1 %d %d" % (
            s32(e.u32(p[0] + PL_HEARD)), s32(e.u32(p[0] + PL_NEW)),
            s32(e.u32(p[1] + PL_HEARD)), s32(e.u32(p[1] + PL_NEW))))

    # ---- stubs

    def s_random(self, em):
        r = s32(self.randq.next())
        self.emit("  random %d -> %d" % (s32(em.reg[4]), r))
        return r

    def s_spch(self, em):
        n = s32(em.reg[5])
        vals = "".join(" %d" % s32(em.reg[6 + j]) for j in range(n))
        self.emit("  spch %d %d%s" % (s32(em.reg[4]), n, vals))
        return 1

    def s_status(self, em):
        r = s32(self.statusq.next())
        ok = "" if em.reg[4] & M32 == EVENT else " ?ev"
        self.emit("  status%s -> %d" % (ok, r))
        return r

    def s_won(self, em):
        r = s32(self.wonq.next())
        ok = "" if em.reg[4] & M32 == EVENT else " ?ev"
        self.emit("  won%s -> %d" % (ok, r))
        return r

    def s_lastlap(self, em):
        a = em.reg[4] & M32
        k = self.rcs.index(a) if a in self.rcs else -1
        self.emit("  lastlap R%d -> %d" % (k, s32(self.e.u32(self.lastlap))))
        return self.lastlap

    def s_best(self, em):
        ok = "" if em.reg[4] & M32 == FRED else " ?fred"
        self.emit("  best%s %d %d %d -> %d" % (
            ok, s32(em.reg[5]), s32(em.reg[6]), s32(em.reg[7]),
            s32(self.e.u32(self.best))))
        return self.best

    # ---- ops

    def run(self, a):
        e = self.e
        o = a[0]
        v = lambda j: int(a[j], 0) & M32        # noqa: E731
        i = lambda j: s32(int(a[j], 0))         # noqa: E731
        qv = lambda: [v(j) for j in range(1, len(a))]   # noqa: E731
        if o == "rp":
            e.put32(RP + RP_FIELDS[a[1]], v(2))
        elif o == "race":
            e.put32(self.race + RACE_BEST, v(1))
            e.put32(self.race + RACE_NCARS, v(2))
        elif o == "rc":
            if i(1) < 0:
                e.put32(G_RC, 0)
            else:
                e.put32(self.rco, v(1))
                e.put32(G_RC, self.rco)
        elif o == "cm":
            e.put32(G_COPMGR, self.cm if i(1) else 0)
        elif o == "arrest":
            e.put32(self.cm + CM_ARREST + CM_STRIDE * i(1), v(2))
        elif o == "player":
            p = self.players[i(1)]
            e.put32(p + PL_CAR, 0 if i(2) < 0 else self.cars[i(2)])
            e.put32(p + PL_HEARD, v(3))
            e.put32(p + PL_NEW, v(4))
        elif o == "ppn":
            e.put32(G_PPN + 4 * i(1), self.player_at(i(2)))
        elif o == "car":
            k = i(1)
            c, r = self.cars[k], self.rcs[k]
            self.put16(c + CAR_INDEX, v(2))
            e.put32(c + CAR_CTI, self.cti + (i(3) + 2) * CTI_SIZE)
            e.put32(c + CAR_PLAYER, self.player_at(i(4)))
            e.put32(c + CAR_RC, r)
            self.put8(r + RC_POS, v(5))
            e.put32(r + RC_LAPX, v(6))
        elif o == "cti":
            t = self.cti + (i(1) + 2) * CTI_SIZE
            e.put32(t + CTI_USAGE, v(2))
            self.put8(t + CTI_HP, v(3))
            self.put8(t + CTI_CLASS, v(4))
        elif o == "gametype":
            e.put32(FRED_GAMETYPE, v(1))
        elif o == "event":
            self.put16(EVENT + EV_NUMBER, v(1))
            e.put32(EVENT + EV_WORD, v(2))
        elif o == "row":
            e.put32(self.rows[i(1)] + ROW_FINISH, v(2))
        elif o == "reward":
            e.write(self.reward, bytes([v(1) & 0xff, v(2) & 0xff,
                                        v(3) & 0xff]))
        elif o == "lastlap":
            e.put32(self.lastlap, v(1))
        elif o == "best":
            e.put32(self.best, v(1))
        elif o == "randq":
            self.randq.fill(qv())
        elif o == "rand":
            self.randq.answer = v(1)
        elif o == "statusq":
            self.statusq.fill(qv())
        elif o == "status":
            self.statusq.answer = v(1)
        elif o == "wonq":
            self.wonq.fill(qv())
        elif o == "won":
            self.wonq.answer = v(1)
        elif o == "conv":
            r = e.call(CONV.get(a[1], CONV["unlock"]), v(2), limit=200)
            self.emit("conv %s %d -> %d" % (a[1], i(2), r))
        elif o == "finished":
            self.emit("finished C%d %d" % (i(1), i(2)))
            e.call(F_FINISHED, self.cars[i(1)], v(2), limit=5000)
            self.flags()
        elif o == "lap":
            self.emit("lap C%d %d" % (i(1), i(2)))
            e.call(F_LAP, self.cars[i(1)], v(2), limit=5000)
            self.flags()
        elif o in ("lap1", "lap2"):
            e.write(self.d, bytes(16))
            e.call(F_LAP1 if o == "lap1" else F_LAP2, self.d,
                   self.cars[i(1)], v(2), limit=5000)
            self.emit("%s C%d %d -> %x %x %x %x" % (
                o, i(1), i(2), e.u32(self.d), e.u32(self.d + 4),
                e.u32(self.d + 8), e.u32(self.d + 12)))
        elif o == "ko":
            self.emit("ko P%d %d" % (i(1), i(2)))
            e.call(F_KO, self.player_at(i(1)), v(2), limit=5000)
            self.flags()
        elif o in ("lapr", "timer"):
            self.emit("%s %d %d W%d" % (o, i(1), i(2), i(3)))
            e.call(F_LAPR if o == "lapr" else F_TIMER, v(1), v(2),
                   self.rows[i(3)], limit=5000)
        elif o == "tour":
            self.emit("tour %d %d" % (i(1), i(2)))
            e.call(F_TOUR, v(1), v(2), limit=5000)
        elif o == "evspeech":
            self.emit("evspeech P%d W%d" % (i(1), i(2)))
            e.call(F_EVSPEECH, self.player_at(i(1)),
                   0 if i(2) < 0 else self.rows[i(2)], limit=5000)
            self.flags()
        elif o == "evreward":
            self.emit("evreward P%d %d %d" % (i(1), i(2), i(3)))
            e.call(F_EVREWARD, self.player_at(i(1)), v(2),
                   self.reward if i(3) else 0, limit=5000)
        elif o == "rcar":
            r = e.call(F_RCAR, v(1), limit=5000)
            self.emit("rcar %d -> %d" % (i(1), r))
        elif o == "rtrack":
            r = e.call(F_RTRACK, v(1), v(2), limit=5000)
            self.emit("rtrack %d %d -> %d" % (i(1), i(2), r))
        elif o == "points":
            self.emit("points %d" % i(1))
            e.call(F_POINTS, v(1), limit=5000)
        elif o == "pullover":
            self.emit("pullover")
            e.call(F_PULLOVER, limit=5000)
        elif o == "arrest4":
            self.emit("arrest4 %d %d %d %d" % (i(1), i(2), i(3), i(4)))
            e.call(F_ARREST, v(1), v(2), v(3), v(4), limit=5000)
        elif o == "busted":
            self.emit("busted")
            e.call(F_BUSTED, limit=5000)
        else:
            raise ValueError(o)


def model(lines):
    m = Model()
    for ln in lines:
        m.run(ln.split("|"))
    return m.out


# ================================================================ the script

def car(k, index=None, cti=0, player=-1, pos=1, lapx=0.0):
    lx = lapx if isinstance(lapx, str) else Fx(lapx)
    return "car|%d|%d|%d|%d|%d|%s" % (k, k if index is None else index, cti,
                                      player, pos, lx)


def base(players=1, ai=7, racetype=1, ncars=8):
    """A race of `ncars`, player one in car 0 and player two in car 1,
    the AI in cars 2 and 3, nothing busted, nothing heard."""
    out = ["rp|Track|11", "rp|Dir|0", "rp|RaceType|%d" % racetype,
           "rp|Laps|3", "rp|Players|%d" % players, "rp|AI|%d" % ai,
           "rp|EventTree|0", "rp|BeACop|0", "race|5000|%d" % ncars, "rc|1",
           "cm|1", "player|0|0|0|0", "player|1|1|0|0", "ppn|0|0", "ppn|1|1",
           "gametype|8", "event|1|0", "row|0|0", "row|1|0", "reward|0|0|0",
           "lastlap|5000", "best|6000", "randq", "rand|0", "statusq",
           "status|4", "wonq", "won|1"]
    for k in range(8):
        out.append("arrest|%d|0" % k)
    out += [car(0, cti=0, player=0, pos=1), car(1, cti=1, player=1, pos=2),
            car(2, cti=2, pos=3), car(3, cti=3, pos=4)]
    for t in range(4):
        out.append("cti|%d|0|0|%d" % (t, t))
    return out


def cti_all():
    return ["cti|%d|%d|%d|%d" % (t, t % 3 == 1, t % 5 == 2, t % 4)
            for t in range(-2, 69)]


def conv_cases():
    out = []
    for k in range(1, 21):
        out += ["conv|hpa|%d" % k, "conv|cha|%d" % k]
    for k in range(21, 35):
        out += ["conv|hpb|%d" % k, "conv|chb|%d" % k]
    for k in list(range(-3, 72)) + [0x7fffffff, -0x80000000, 100, 255, 66,
                                    67, 0x10000]:
        out += ["conv|reward|%d" % k, "conv|track|%d" % k,
                "conv|unlock|%d" % k]
    return out


RC_STATES = (-1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10)


def finished_cases():
    """RaceFinishedSpeech over WeDontWantToSayAnything's tests, Be A Cop,
    the busted car, the knockouts, every place of every field and the last
    place's coin."""
    out = []
    # The gate: players, cars, the coordinator's state, the race type.
    for players in (0, 1, 2, 3):
        for ncars in (1, 2, 3, 8):
            for st in RC_STATES:
                for rt in (0, 1, 2, 3, 4, 5, -1):
                    out += base(players=players, racetype=rt, ncars=ncars)
                    out += ["rc|%d" % st, car(0, cti=0, player=0, pos=1),
                            "finished|0|0", "finished|0|0"]
    # Be A Cop and HasHeard.
    for bac in (0, 1, -1):
        for heard in (0, 1, 2):
            out += base() + ["rp|BeACop|%d" % bac,
                             "player|0|0|%d|0" % heard, "finished|0|3"]
    # Busted: the manager, the car's index, the arrest.
    for cm in (0, 1):
        for idx in (0, 3, 7):
            for arr in (0, 1, -1, 2):
                out += base() + ["cm|%d" % cm, "arrest|%d|%d" % (idx, arr),
                                 car(0, index=idx, cti=0, player=0, pos=2),
                                 "finished|0|1"]
    # Every place, one and two players, each player's car, and the last
    # place's coin.
    for players in (1, 2):
        for ncars in (2, 3, 5, 8):
            for pos in range(1, 9):
                for k in (0, 1):
                    for r in (0, 1, 5):
                        out += base(players=players, ncars=ncars)
                        out += ["rand|%d" % r,
                                car(k, cti=k, player=k, pos=pos),
                                "finished|%d|0" % k]
    # Player one's car seen as player two's: PPN[0]'s car moved.
    for pos in (1, 2, 8):
        out += base(players=2, ncars=8) + ["player|0|2|0|0",
                                           car(0, cti=0, player=0, pos=pos),
                                           "finished|0|0"]
    return out


def lap_cases():
    """LapFinishedSpeech: the gate, the lap record, the knockout and the
    builders, through the said TypeA, and the builders on their own for
    all four fields."""
    out = []
    # The gate, with the car's player and without.
    for players in (0, 1, 2):
        for ncars in (1, 2, 8):
            for st in RC_STATES:
                for rt in (0, 1, 2, 3, 4, 5):
                    out += base(players=players, racetype=rt, ncars=ncars)
                    out += ["rc|%d" % st, "best|0x7fffffff", "lap|0|1",
                            car(2, cti=2, pos=3), "lap|2|1"]
    # The lap record: the last lap, the race's best and the track's.
    times = (0, 1, 4999, 5000, 5001, -1, 0x7fffffff, 0x80000000, 0x7ffffffe)
    for last in times:
        for rbest in (last, 5000, 0x7fffffff):
            for top in times:
                for cls in (0, 3):
                    out += base() + [
                        "lastlap|%d" % s32(last), "race|%d|8" % s32(rbest),
                        "best|%d" % s32(top), "rp|Track|%d" % (cls + 21),
                        "rp|Dir|%d" % (cls & 1), "cti|0|0|0|%d" % cls,
                        "lap|0|1"]
    # One player: every lap of races of 1 to 21, the AI or none, the coin.
    for laps_in in (1, 2, 3, 8, 20, 21):
        for ai in (0, 1, 7, -1):
            for lap in range(1, 21):
                if ai <= 0 and lap > 20:
                    continue
                for coin in ((0,), (1,), (0, 0), (0, 1), (1, 0)):
                    out += base(players=1, ai=ai)
                    out += ["rp|Laps|%d" % laps_in, "best|0x7fffffff",
                            "randq|" + "|".join(str(c) for c in coin),
                            "rand|1", car(0, cti=0, player=0,
                                          pos=1 + lap % 8),
                            "lap1|0|%d" % lap, "lap|0|%d" % lap]
    # Past lap 19 with the AI: the place without a coin.
    for lap in (19, 20, 21, 25):
        for pos in range(1, 9):
            for r in (0, 1):
                out += base(players=1, ai=3) + [
                    "rp|Laps|30", "randq|1", "rand|%d" % r,
                    car(0, cti=0, player=0, pos=pos), "lap1|0|%d" % lap]
    # Each place, each coin.
    for pos in range(1, 9):
        for coins in ((0, 0), (0, 1), (1, 1), (1, 0), (2, 0), (-1, 1)):
            out += base(players=1, ai=7) + [
                "rp|Laps|9", "randq|%d|%d" % coins, "rand|1",
                car(0, cti=0, player=0, pos=pos), "lap1|0|3"]
    # Two players with the AI: places, each car, each coin.
    for pos in range(1, 9):
        for k in (0, 1, 2):
            for coin in (0, 1):
                out += base(players=2, ai=4) + [
                    "rand|%d" % coin, car(k, cti=k, player=min(k, 1),
                                          pos=pos),
                    "lap2|%d|2" % k, "best|0x7fffffff", "lap|%d|2" % k]
    # Two players, no AI: the gap at each limit and either side.
    limits = (0.5, 0.3, 0.2, 0.1, 0.05, 0.01, -0.1, -0.2, -99999.0)
    gaps = []
    for g in limits:
        gaps += [Fx(g), Fn(g, 1), Fn(g, -1)]
    gaps += [Fx(0.0), Fx(-0.0), Fx(5.0), Fx(-200000.0), "0x7fc00000",
             "0x7f800000", "0xff800000", Fx(0.25), Fx(-0.15)]
    for g in gaps:
        for k in (0, 1, 2):
            for coin in (0, 1):
                for flip in (0, 1):
                    # The gap one - two: one at it and two at 0, or two at
                    # its negation and one at 0.
                    if flip:
                        neg = "0x%08x" % (int(g, 16) ^ 0x80000000)
                        c0, c1 = Fx(0.0), neg
                    else:
                        c0, c1 = g, Fx(0.0)
                    out += base(players=2, ai=0) + [
                        "rand|%d" % coin,
                        car(0, cti=0, player=0, pos=1, lapx=c0),
                        car(1, cti=1, player=1, pos=2, lapx=c1),
                        car(2, cti=2, pos=3, lapx=Fx(1.0)),
                        "lap2|%d|1" % k]
    # Real gaps: two cars' exact laps.
    rng = random.Random(0x14c)
    for _ in range(300):
        a, b = rng.uniform(0, 6), rng.uniform(0, 6)
        if rng.random() < 0.3:
            b = a + rng.choice((-1, 1)) * rng.choice(limits[:6])
        out += base(players=2, ai=0) + [
            "rand|%d" % rng.randrange(2),
            car(0, cti=0, player=0, pos=1, lapx=a),
            car(1, cti=1, player=1, pos=2, lapx=b),
            "lap2|%d|1" % rng.randrange(2), "best|0x7fffffff",
            "lap|%d|2" % rng.randrange(2)]
    return out


def ko_cases():
    out = []
    for p in (-1, 0, 1):
        for heard in (0, 1, -1):
            for rt in (1, 3, 4, 0):
                for ncars in (1, 2, 3, 4, 8):
                    for adv in (0, 1, -1, 2):
                        out += base(racetype=rt, ncars=ncars) + [
                            "player|0|0|%d|0" % heard,
                            "player|1|1|%d|3" % heard,
                            "ko|%d|%d" % (p, adv), "ko|%d|%d" % (p, adv)]
    return out


def record_cases():
    """PostGameLapRecord and PostGameTimeRecord: the busted row, the event
    tree's race and its status, the place, the player, the coin."""
    out = []
    for fin in (0, 1, 2, 3, -1):
        for tree in (0, 1, -1):
            for status in (4, 0, 3, 5):
                for players in (1, 2, 0, 3):
                    for pl in (0, 1, 2, -1):
                        for place in (0, 1, 4):
                            for coin in (0, 1):
                                out += base(players=players) + [
                                    "row|1|%d" % fin, "rp|EventTree|%d" % tree,
                                    "status|%d" % status, "rand|%d" % coin,
                                    "lapr|%d|%d|1" % (pl, place),
                                    "timer|%d|%d|1" % (pl, place)]
    return out


def tour_cases():
    out = base()
    for b in (0, 1, -1, 2):
        for n in range(-1, 16):
            out.append("tour|%d|%d" % (b, n))
    return out


def event_cases():
    """The event's result: the player and row, the status, the won test,
    the first time, each event number of each game type, the word."""
    out = []
    for p in (-1, 0, 1):
        for row in (-1, 0):
            for status in (4, 0, 5):
                for won in (0, 1, 2):
                    out += base() + ["status|%d" % status, "won|%d" % won,
                                     "evspeech|%d|%d" % (p, row)]
    for gt in (8, 9, 3, 0):
        for n in range(1, 35):
            for new in (0, 1, 5):
                for word in (0, 1, -1):
                    out += base() + [
                        "gametype|%d" % gt, "event|%d|%d" % (n, word),
                        "player|0|0|0|%d" % new, "evspeech|0|0",
                        "evspeech|0|0"]
    # The queues: the status then the won test, call after call.
    out += base() + ["statusq|4|0|4|4|3", "status|4", "wonq|1|0|1|0",
                     "won|1", "event|21|1", "gametype|9"]
    out += ["evspeech|0|0"] * 6 + ["evspeech|1|1"] * 2
    return out


def reward_cases():
    out = []
    # Each car type by its usage and high performance.
    for usage in (0, 1, 2, -1):
        for hp in (0, 1, -1):
            out += base()
            for t in range(-2, 69):
                out += ["cti|%d|%d|%d|0" % (t, usage, hp), "rcar|%d" % t]
    # Each track and direction.
    out += base()
    for t in list(range(-2, 72)) + [0x7fffffff, -0x80000000, 255]:
        for d in (0, 1, 2, 255, -1):
            out.append("rtrack|%d|%d" % (t, d))
    # The event's reward: the won flag, none, a car, a track.
    for won in (0, 1, -1, 2):
        for has in (0, 1):
            for b0 in (0, 1, 255):
                for b1 in (0, 7, 21, 22, 34, 66, 11, 36, 63, 68):
                    for b2 in (0, 1, 2):
                        for p in (-1, 0):
                            out += base() + [
                                "cti|%d|%d|%d|0" % (b1, b1 % 3 == 0,
                                                    b1 % 2),
                                "reward|%d|%d|%d" % (b0, b1, b2),
                                "evreward|%d|%d|%d" % (p, won, has)]
    for b1 in range(0, 256, 5):
        out += base() + ["reward|1|%d|1" % b1, "evreward|0|1|1"]
    return out


def misc_cases():
    out = base()
    for b in (0, 1, -1, 2):
        out.append("points|%d" % b)
    for st in RC_STATES:
        out.append("rc|%d" % st)
        out += ["pullover", "busted"]
        for players in (0, 1, 2, 3):
            for missed in (0, 1, -1):
                for winner in (0, 1, 2, 3):
                    for arrests in (-1, 0, 1, 2, 3, 4):
                        out.append("arrest4|%d|%d|%d|%d" % (
                            players, missed, winner, arrests))
    return out


def random_runs(rng):
    """Races over time: the cars' places and laps, the players, the
    coordinator and the queues changing, and every call."""
    out = base() + cti_all()
    for _ in range(4000):
        r = rng.random()
        if r < 0.10:
            k = rng.randrange(NCARS)
            out.append(car(k, index=rng.randrange(8), cti=rng.randrange(-2, 69),
                           player=rng.randrange(2) if k < 2 else -1,
                           pos=rng.randrange(1, 9),
                           lapx=rng.uniform(0, 8)))
        elif r < 0.14:
            out.append("rp|%s|%d" % rng.choice((
                ("RaceType", rng.randrange(6)), ("Players", rng.randrange(3)),
                ("AI", rng.randrange(-1, 8)), ("Laps", rng.randrange(1, 21)),
                ("BeACop", rng.randrange(2)), ("EventTree", rng.randrange(2)),
                ("Track", rng.randrange(70)), ("Dir", rng.randrange(2)))))
        elif r < 0.16:
            out.append("race|%d|%d" % (rng.choice((5000, 4000, 0x7fffffff)),
                                       rng.randrange(1, 9)))
        elif r < 0.18:
            out.append("rc|%d" % rng.choice(RC_STATES))
        elif r < 0.20:
            out.append("player|%d|%d|%d|%d" % (
                rng.randrange(2), rng.randrange(NCARS),
                rng.choice((0, 0, 1)), rng.choice((0, 1))))
        elif r < 0.22:
            out.append("arrest|%d|%d" % (rng.randrange(8),
                                         rng.random() < 0.2))
        elif r < 0.25:
            out.append("randq|" + "|".join(
                str(rng.randrange(2)) for _ in range(rng.randrange(1, 5))))
        elif r < 0.27:
            out.append("lastlap|%d" % rng.choice((4000, 5000, 6000)))
        elif r < 0.29:
            out.append("best|%d" % rng.choice((4500, 5000, 0x7fffffff, 0)))
        elif r < 0.31:
            out.append("status|%d" % rng.choice((4, 4, 0)))
        elif r < 0.33:
            out.append("event|%d|%d" % (rng.randrange(1, 35),
                                        rng.randrange(2)))
        elif r < 0.34:
            out.append("gametype|%d" % rng.choice((8, 9)))
        else:
            k = rng.randrange(NCARS)
            pl = rng.randrange(2)
            out.append(rng.choice((
                "finished|%d|0" % rng.randrange(2),
                "lap|%d|%d" % (k, rng.randrange(1, 20)),
                "ko|%d|%d" % (pl, rng.randrange(2)),
                "lapr|%d|%d|%d" % (pl, rng.randrange(5), rng.randrange(2)),
                "timer|%d|%d|%d" % (pl, rng.randrange(5), rng.randrange(2)),
                "tour|%d|%d" % (rng.randrange(2), rng.randrange(8)),
                "evspeech|%d|%d" % (pl, rng.randrange(2)),
                "rcar|%d" % rng.randrange(-2, 69),
                "rtrack|%d|%d" % (rng.randrange(70), rng.randrange(2)),
                "pullover",
                "arrest4|%d|%d|%d|%d" % (rng.randrange(1, 3),
                                         rng.randrange(2), rng.randrange(3),
                                         rng.randrange(4)))))
    return out


def script():
    return (cti_all() + conv_cases() + finished_cases() + lap_cases()
            + ko_cases()
            + record_cases() + tour_cases() + event_cases() + reward_cases()
            + misc_cases() + random_runs(random.Random(0x14c0)))


# ================================================================= running

def build_harness(tmp, name="racespeech_test"):
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

S = RS
C = SC

TABLE_RX = re.compile(r"static const uint32_t (\w+)\[\d+\] = \{\n(.*?)\n\};",
                      re.S)
NUM_RX = re.compile(r"\b(0x[0-9a-fA-F]+|\d+)\b")
# speechconv.c's tables that this slice added; kCarTypeDescription is
# pursuit speech's (pursuitspeech_check.py).
SC_TABLES = ("kRewardCarType", "kHotPursuitEventA", "kHotPursuitEventB",
             "kChampionshipEventA", "kChampionshipEventB")


def _table_mutations(path, tag, names=None):
    """Each entry of each table, alone: 0 made 1, anything else shifted
    up a bit."""
    src = (ROOT / path).read_text()
    out = []
    for m in TABLE_RX.finditer(src):
        name = m.group(1)
        if names is not None and name not in names:
            continue
        block = m.group(0)
        start = m.start(2) - m.start(0)
        j, pos = 0, start
        for ln in m.group(2).split(NL):
            code = ln.split("//")[0]
            for t in NUM_RX.finditer(code):
                s, e = pos + t.start(), pos + t.end()
                v = int(t.group(1), 0)
                nv = "0x%x" % (v << 1 if v else 1)
                out.append(("%s-%s%d" % (tag, name[1:], j), path, block,
                            block[:s] + nv + block[e:]))
                j += 1
            pos += len(ln) + 1
    return out


def _gap_mutations():
    old = ("    0.5f, 0.3f, 0.2f, 0.1f, 0.05f, 0.01f, -0.1f, -0.2f, "
           "-99999.0f,")
    vals = old.strip().rstrip(",").split(", ")
    nudged = ("0.50001f", "0.30001f", "0.20001f", "0.10001f", "0.05001f",
              "0.01001f", "-0.09999f", "-0.19999f", "-99998.0f")
    out = []
    for k in range(len(vals)):
        nv = list(vals)
        nv[k] = nudged[k]
        out.append(("gl-%d" % k, S, old, "    " + ", ".join(nv) + ","))
    return out


def _switch_mutations():
    """Each case line of the two track switches: its bits shifted, and
    each of its two tracks dropped."""
    src = (ROOT / SC).read_text()
    out = []
    for fn, tag in (("track_number", "tn"), ("unlock_track", "ut")):
        m = re.search(r"int32_t speech_convert_%s\(int32_t track\)\n\{\n"
                      r".*?\n\}\n" % fn, src, re.S)
        block = m.group(0)
        for c in re.finditer(r"    case (\d+): case (\d+): return "
                             r"(0x[0-9a-f]+);", block):
            a, b, v = c.group(1), c.group(2), c.group(3)
            ln = c.group(0)
            for nm, nl in (
                    ("v", "    case %s: case %s: return 0x%x;"
                     % (a, b, int(v, 16) << 1)),
                    ("a", "    case %s: return %s;" % (b, v)),
                    ("b", "    case %s: return %s;" % (a, v))):
                out.append(("%s-%s%s" % (tag, nm, a), SC, block,
                            block.replace(ln, nl)))
    return out


SP = ("static uint32_t single_p1_or_p2(const struct Car *car, uint32_t "
      "single,\n                                uint32_t one, uint32_t "
      "two)\n{\n    if (TheRaceParameters.NumPlayerCars != 2)\n"
      "        return single;\n    return car == PlayerPlayersByNumber[0]"
      "->MyCar ? one : two;")
SPT = ("                                             const uint32_t *two)"
       "\n{\n    if (TheRaceParameters.NumPlayerCars != 2)\n        return "
       "single;\n    return car == PlayerPlayersByNumber[0]->MyCar ? one : "
       "two;")
PSP = ("    if (TheRaceParameters.NumPlayerCars != 2)\n        return single;"
       "\n    return player == 0 ? one : two;")
LR = ("    int32_t t = (int32_t)racingcar_get_last_lap_time(car->pRacingCar)"
      "\n                    ->PackedTime;\n    const FredHighScore *best = "
      "fred_get_best_lap_times_table(\n        &Fred, TheRaceParameters."
      "TrackNumber, car->pCarTypeInfo->CarClass,\n        "
      "TheRaceParameters.TrackDirection);\n")
LR2 = ("    const FredHighScore *best = fred_get_best_lap_times_table(\n"
       "        &Fred, TheRaceParameters.TrackNumber, car->pCarTypeInfo->"
       "CarClass,\n        TheRaceParameters.TrackDirection);\n    int32_t "
       "t = (int32_t)racingcar_get_last_lap_time(car->pRacingCar)\n"
       "                    ->PackedTime;\n")


def _m(name, old, new, f=S):
    return (name, f, old, new)


HAND = [
    # ---- FlipCoinNoReplay and the player pickers
    _m("fc-ne", "bRandomI(2, bViewSeed) == 0", "bRandomI(2, bViewSeed) != 0"),
    _m("fc-3", "bRandomI(2, bViewSeed)", "bRandomI(3, bViewSeed)"),
    _m("sp-n1", SP, SP.replace("!= 2", "!= 1")),
    _m("sp-swap", SP, SP.replace("? one : two", "? two : one")),
    _m("sp-ppn1", SP, SP.replace("ByNumber[0]", "ByNumber[1]")),
    _m("spt-n1", SPT, SPT.replace("!= 2", "!= 1")),
    _m("spt-swap", SPT, SPT.replace("? one : two", "? two : one")),
    _m("spt-ppn1", SPT, SPT.replace("ByNumber[0]", "ByNumber[1]")),
    _m("psp-n1", PSP, PSP.replace("!= 2", "!= 1")),
    _m("psp-swap", PSP, PSP.replace("? one : two", "? two : one")),
    _m("psp-1", PSP, PSP.replace("player == 0", "player == 1")),
    # ---- the replays
    _m("rp-null1", "    if (rc == NULL)\n        return 0;\n    s = rc",
       "    if (rc == NULL)\n        return 1;\n    s = rc"),
    _m("rp-no4", "if (s == RCSTATE_INSTANT_REPLAY || ", "if ("),
    _m("rp-no7", "s == RCSTATE_POSTRACE\n", "s == RCSTATE_INSTANT_REPLAY\n"),
    _m("rp-no5", "|| s == RCSTATE_AUTO_REPLAY)",
       "|| s == RCSTATE_INSTANT_REPLAY)"),
    _m("rp-demo", "return racecoordinator_is_replay_demo_mode(rc) != 0;",
       "return 0;"),
    # ---- WeDontWantToSayAnything
    _m("wd-player", "if (car->pPlayer == NULL || ", "if ("),
    _m("wd-np", "TheRaceParameters.NumPlayerCars == 0\n        || ", ""),
    _m("wd-cars3", "pCurrentRace->NumRacingCars < 2)",
       "pCurrentRace->NumRacingCars < 3)"),
    _m("wd-cars1", "pCurrentRace->NumRacingCars < 2)",
       "pCurrentRace->NumRacingCars < 1)"),
    _m("wd-replay", "    if (replaying())\n        return 1;\n    if "
       "(TheRaceParameters.RaceType", "    if (TheRaceParameters.RaceType"),
    _m("wd-tt", "    if (TheRaceParameters.RaceType == RACE_TYPE_TIME_TRIAL)"
       "\n        return 1;\n", ""),
    _m("wd-demo-null", "    if (rc != NULL\n        && (uint32_t)",
       "    if ((uint32_t)"),
    _m("wd-demo1", "RCSTATE_AI_DEMO_MODE) < 2u)", "RCSTATE_AI_DEMO_MODE) < 1u)"),
    _m("wd-demo3", "RCSTATE_AI_DEMO_MODE) < 2u)", "RCSTATE_AI_DEMO_MODE) < 3u)"),
    _m("wd-none", "return TheRaceParameters.RaceType == RACE_TYPE_NONE;",
       "return 0;"),
    _m("wd-none-ne", "return TheRaceParameters.RaceType == RACE_TYPE_NONE;",
       "return TheRaceParameters.RaceType != RACE_TYPE_NONE;"),
    # ---- BustedByCops, both
    _m("rb-3", "row->FinishReason == 2;", "row->FinishReason == 3;"),
    _m("bc-null", "return pCopManager != NULL\n           && ", "return "),
    _m("bc-pos", ".bArrest != 0;", ".bArrest > 0;"),
    _m("bc-idx", "CarPullovers[car->CarIndex]", "CarPullovers[0]"),
    # ---- SpecialLastPlaceSpeech
    _m("sl-2", "if (pCurrentRace->NumRacingCars == 2) {",
       "if (pCurrentRace->NumRacingCars == 3) {"),
    _m("sl-b2", "single_p1_or_p2(car, 0x08, 0x10, 0x20)",
       "single_p1_or_p2(car, 0x08, 0x20, 0x10)"),
    _m("sl-coin", "        if (flip_coin())\n            return 0;\n        b =",
       "        if (!flip_coin())\n            return 0;\n        b ="),
    _m("sl-b1", "single_p1_or_p2(car, 0x01, 0x02, 0x04)",
       "single_p1_or_p2(car, 0x01, 0x04, 0x02)"),
    _m("sl-ev", "spch_add_event_v(165, 2, 0, b);",
       "spch_add_event_v(165, 2, b, 0);"),
    _m("sl-ret", "    spch_add_event_v(165, 2, 0, b);\n    return 1;",
       "    spch_add_event_v(165, 2, 0, b);\n    return 0;"),
    # ---- RaceFinishedSpeech
    _m("rf-heard", "    if (car->pPlayer->HasHeardRaceOverSpeech != 0)\n"
       "        return;\n", ""),
    _m("rf-bac", "if (TheRaceParameters.BeACop == 0 && ", "if ("),
    _m("rf-busted", "spch_add_event_v(168, 1, 512);",
       "spch_add_event_v(168, 1, 64);"),
    _m("rf-ko1", "- RACE_TYPE_LAP_KNOCKOUT) >= 2u)",
       "- RACE_TYPE_LAP_KNOCKOUT) >= 1u)"),
    _m("rf-ko3", "- RACE_TYPE_LAP_KNOCKOUT) >= 2u)",
       "- RACE_TYPE_LAP_KNOCKOUT) >= 3u)"),
    _m("rf-last", "if (pos != pCurrentRace->NumRacingCars\n",
       "if (pos != 8\n"),
    _m("rf-special", "|| !special_last_place_speech(car)) {",
       "|| special_last_place_speech(car)) {"),
    _m("rf-idx", "at(t, 8, pos - 1)", "at(t, 8, pos)"),
    _m("rf-tab", "single_p1_or_p2_table(car, kFinishSingle, kFinishOne,\n"
       "                                          kFinishTwo);",
       "single_p1_or_p2_table(car, kFinishSingle, kFinishTwo,\n"
       "                                          kFinishOne);"),
    _m("rf-set", "    car->pPlayer->HasHeardRaceOverSpeech = 1;\n}", "}"),
    # ---- the event's result
    _m("ev-null", "if (p == NULL || row == NULL)", "if (p == NULL)"),
    _m("ev-status", "if (race_event_status() != RACE_EVENT_PLACED) {",
       "if (race_event_status() != 3) {"),
    _m("ev-fail", "spch_add_event_v(168, 1, 64);",
       "spch_add_event_v(168, 1, 1024);"),
    _m("ev-won", "gRaceEventUserWonFn() == 0)", "gRaceEventUserWonFn() != 1)"),
    _m("ev-first", "first = p->New2696 == 0;", "first = p->New2696 != 0;"),
    _m("ev-noset", "    if (first)\n        p->New2696 = 1;\n", ""),
    _m("ev-hp", "hp = Fred.GameType == 9;", "hp = Fred.GameType == 8;"),
    _m("ev-19", "if ((uint32_t)(n - 1) < 20u)", "if ((uint32_t)(n - 1) < 19u)"),
    _m("ev-21", "if ((uint32_t)(n - 1) < 20u)", "if ((uint32_t)(n - 1) < 21u)"),
    _m("ev-hpa", "a = hp ? speech_convert_hp_event_a(n)\n"
       "               : speech_convert_championship_event_a(n);",
       "a = hp ? speech_convert_championship_event_a(n)\n"
       "               : speech_convert_hp_event_a(n);"),
    _m("ev-hpb", "b = hp ? speech_convert_hp_event_b(n)\n"
       "               : speech_convert_championship_event_b(n);",
       "b = hp ? speech_convert_championship_event_b(n)\n"
       "               : speech_convert_hp_event_b(n);"),
    _m("ev-none", "if (a == 0 && b == 0) {", "if (a == 0 || b == 0) {"),
    _m("ev-1024", "spch_add_event_v(168, 1, 1024);",
       "spch_add_event_v(168, 1, 64);"),
    _m("ev-word", "word = TheRaceEvent.bIsLastOpen != 0;",
       "word = TheRaceEvent.bIsLastOpen;"),
    _m("ev-2048", "if (b == 2048)", "if (b == 1024)"),
    _m("ev-2048ev", "spch_add_event_v(216, 4, first, a, 2048, word);",
       "spch_add_event_v(217, 4, first, a, 2048, word);"),
    _m("ev-217", "hp ? 216 : 217", "hp ? 217 : 216"),
    _m("ev-args", "4, first, a, b, word);", "4, first, b, a, word);"),
    # ---- OnePlayerLapSpeech
    _m("l1-last", "if (laps == TheRaceParameters.NumLapsInRace - 1) {",
       "if (laps == TheRaceParameters.NumLapsInRace) {"),
    _m("l1-1024", "d->TypeD = 1024;", "d->TypeA = 1024;"),
    _m("l1-21", "|| laps >= 20)", "|| laps >= 21)"),
    _m("l1-19", "|| laps >= 20)", "|| laps >= 19)"),
    _m("l1-and", "(flip_coin() || laps >= 20)", "(flip_coin() && laps >= 20)"),
    _m("l1-ai", "TheRaceParameters.NumAICars > 0)",
       "TheRaceParameters.NumAICars >= 0)"),
    _m("l1-p1", "if (pos == 1)", "if (pos == 2)"),
    _m("l1-c1", "d->TypeD = flip_coin() ? 1 : 512;",
       "d->TypeD = flip_coin() ? 512 : 1;"),
    _m("l1-p8", "else if (pos == 8)", "else if (pos == 7)"),
    _m("l1-c8", "d->TypeD = flip_coin() ? 128 : 256;",
       "d->TypeD = flip_coin() ? 256 : 128;"),
    _m("l1-place", "at(kLapPlace, 6, pos - 2)", "at(kLapPlace, 6, pos - 1)"),
    _m("l1-start", "at(kLapStart, 20, laps - 1)", "at(kLapStart, 20, laps)"),
    _m("l1-ret", "            d->TypeD = at(kLapPlace, 6, pos - 2);\n"
       "        return;\n", "            d->TypeD = at(kLapPlace, 6, pos - 2);\n"),
    # ---- TwoPlayerLapSpeech
    _m("l2-ai", "if (TheRaceParameters.NumAICars == 0) {",
       "if (TheRaceParameters.NumAICars == 1) {"),
    _m("l2-sub", "gap = one->pRacingCar->CurrentLapNumberExact\n"
       "              - two->pRacingCar->CurrentLapNumberExact;",
       "gap = two->pRacingCar->CurrentLapNumberExact\n"
       "              - one->pRacingCar->CurrentLapNumberExact;"),
    _m("l2-neg", "        if (!is_one)\n            gap = -gap;\n", ""),
    _m("l2-tab", "kGapEither : is_one ? kGapOne : kGapTwo;",
       "kGapEither : is_one ? kGapTwo : kGapOne;"),
    _m("l2-tab2", "flip_coin() ? kGapEither : is_one ? kGapOne",
       "flip_coin() ? kGapOne : is_one ? kGapEither"),
    _m("l2-lt", "if (kGapLimit[i] <= gap) {", "if (kGapLimit[i] < gap) {"),
    _m("l2-8", "for (i = 0; i < 9; i++)", "for (i = 0; i < 8; i++)"),
    _m("l2-i1", "for (i = 0; i < 9; i++)", "for (i = 1; i < 9; i++)"),
    _m("l2-place", "kPlaceEither : is_one ? kPlaceOne : kPlaceTwo;",
       "kPlaceEither : is_one ? kPlaceTwo : kPlaceOne;"),
    _m("l2-place2", "flip_coin() ? kPlaceEither : is_one ? kPlaceOne",
       "flip_coin() ? kPlaceOne : is_one ? kPlaceEither"),
    _m("l2-pos", "at(t, 8, car->pRacingCar->RacePosition - 1)",
       "at(t, 8, car->pRacingCar->RacePosition)"),
    _m("l2-isone", "int32_t is_one = car == one;", "int32_t is_one = car != two;"),
    # ---- MaybeDoKnockoutRaceOverSpeech
    _m("ko-heard", "if (p == NULL || p->HasHeardRaceOverSpeech != 0)",
       "if (p == NULL)"),
    _m("ko-type", "RaceType == RACE_TYPE_LAP_KNOCKOUT\n        || ",
       "RaceType == 4\n        || "),
    _m("ko-lt2", "|| pCurrentRace->NumRacingCars < 3)",
       "|| pCurrentRace->NumRacingCars < 2)"),
    _m("ko-lt4", "|| pCurrentRace->NumRacingCars < 3)",
       "|| pCurrentRace->NumRacingCars < 4)"),
    _m("ko-a1", "spch_add_event_v(169, 2, advances ? 0 : 1, 0);",
       "spch_add_event_v(169, 2, advances ? 1 : 0, 0);"),
    _m("ko-a2", "spch_add_event_v(169, 2, 1, advances ? 1 : 0);",
       "spch_add_event_v(169, 2, 1, advances ? 0 : 1);"),
    _m("ko-a2b", "spch_add_event_v(169, 2, 1, advances ? 1 : 0);",
       "spch_add_event_v(169, 2, 0, advances ? 1 : 0);"),
    _m("ko-set", "    p->HasHeardRaceOverSpeech = 1;\n}\n\n// LapRecord",
       "}\n\n// LapRecord"),
    # ---- LapRecordSpeech
    _m("lr-ne", "    if (t != (int32_t)pCurrentRace->BestLapTime.PackedTime)\n"
       "        return 0;\n", ""),
    _m("lr-gt", "if (t >= top ||", "if (t > top ||"),
    _m("lr-un", "if (t >= top ||", "if ((uint32_t)t >= (uint32_t)top ||"),
    _m("lr-0", "top == 0 || ", ""),
    _m("lr-nt", " || top == HIGH_SCORE_NO_TIME)", ")"),
    _m("lr-dir", "CarClass,\n        TheRaceParameters.TrackDirection);",
       "CarClass,\n        TheRaceParameters.TrackNumber);"),
    _m("lr-class", "car->pCarTypeInfo->CarClass,",
       "car->pCarTypeInfo->HighPerformance,"),
    _m("lr-order", LR, LR2),
    _m("lr-164", "spch_add_event_v(164, 0);", "spch_add_event_v(163, 0);"),
    _m("lr-ret", "    spch_add_event_v(164, 0);\n    return 1;",
       "    spch_add_event_v(164, 0);\n    return 0;"),
    # ---- LapFinishedSpeech
    _m("lf-wd", "if (we_dont_want_to_say_anything(car) || lap_record_speech"
       "(car))", "if (lap_record_speech(car))"),
    _m("lf-rec", "if (we_dont_want_to_say_anything(car) || lap_record_speech"
       "(car))", "if (we_dont_want_to_say_anything(car))"),
    _m("lf-2", "if (TheRaceParameters.NumPlayerCars == 2)\n        two_player",
       "if (TheRaceParameters.NumPlayerCars == 1)\n        two_player"),
    _m("lf-typ", "spch_add_event_v(160, 1, d.TypeA);",
       "spch_add_event_v(160, 1, d.TypeD);"),
    # ---- the records
    _m("tt-flag", "player_single_p1_or_p2(player, 64, 128, 256)",
       "player_single_p1_or_p2(player, 64, 256, 128)"),
    _m("rw-bust", "    if (row_busted_by_cops(row))\n        return 0;\n", ""),
    _m("rw-tree", "return TheRaceParameters.EventTreeRace == 0\n"
       "           || race_event_status()", "return race_event_status()"),
    _m("rw-status", "\n           || race_event_status() == RACE_EVENT_PLACED;",
       ";"),
    _m("pl-place", "    if (place != 0)\n        a = get_top_time_flag(player);"
       "\n    else\n", "    if (place == 0)\n        a = get_top_time_flag("
       "player);\n    else\n"),
    _m("pl-vals", "(player, 512, 1024, 2048)", "(player, 512, 2048, 1024)"),
    _m("pl-ev", "    spch_add_event_v(166, 1, a);\n}\n\nvoid post_game_time",
       "    spch_add_event_v(165, 1, a);\n}\n\nvoid post_game_time"),
    _m("pt-place", "    if (place != 0)\n        a = get_top_time_flag(player);"
       "\n    else if", "    if (place == 0)\n        a = get_top_time_flag("
       "player);\n    else if"),
    _m("pt-coin", "else if (flip_coin())", "else if (!flip_coin())"),
    _m("pt-v1", "(player, 1, 2, 4)", "(player, 1, 4, 2)"),
    _m("pt-v2", "(player, 8, 16, 32)", "(player, 8, 32, 16)"),
    _m("pt-ev", "    spch_add_event_v(166, 1, a);\n}\n\nvoid tournament",
       "    spch_add_event_v(165, 1, a);\n}\n\nvoid tournament"),
    # ---- TournamentRaceSpeech
    _m("tr-b", "    if (b)\n        spch_add_event_v(165, 2, at(",
       "    if (!b)\n        spch_add_event_v(165, 2, at("),
    _m("tr-n", "at(kTournamentPlace, 8, n)", "at(kTournamentPlace, 8, n - 1)"),
    _m("tr-7", "at(kTournamentPlace, 8, n)", "at(kTournamentPlace, 7, n)"),
    _m("tr-n0", "else if (n == 0)", "else if (n == 1)"),
    _m("tr-ev", "spch_add_event_v(167, 1, 16384);",
       "spch_add_event_v(167, 1, 8192);"),
    _m("at-zero", "? t[i] : 0;", "? t[i] : 1;"),
    # ---- the rewards
    _m("er-won", "if (!won || reward == NULL)", "if (reward == NULL)"),
    _m("er-null", "if (!won || reward == NULL)", "if (!won)"),
    _m("er-b0", "if (reward[0] == 0)", "if (reward[0] == 1)"),
    _m("er-car", "reward_car_speech(reward[1]);", "reward_car_speech(reward[2]);"),
    _m("er-tr", "reward_track_speech(reward[1], reward[2]);",
       "reward_track_speech(reward[2], reward[1]);"),
    _m("rc-cop", "if (cti->UsageType == CAR_USAGE_TYPE_COP) {",
       "if (cti->UsageType == 2) {"),
    _m("rc-150", "ev = 150;", "ev = 149;"),
    _m("rc-hp", "} else if (cti->HighPerformance != 0) {",
       "} else if (cti->HighPerformance > 0) {"),
    _m("rc-128", "if (v == 128) {", "if (v == 64) {"),
    _m("rc-204", "spch_add_event_v(204, 1, 1);", "spch_add_event_v(204, 1, v);"),
    _m("rc-204r", "            spch_add_event_v(204, 1, 1);\n"
       "            return 1;", "            spch_add_event_v(204, 1, 1);\n"
       "            return 0;"),
    _m("rc-149", "ev = 149;", "ev = 147;"),
    _m("rc-147", "ev = 147;", "ev = 148;"),
    _m("rc-v0", "    if (v == 0)\n        return 0;\n    spch_add_event_v(ev",
       "    spch_add_event_v(ev"),
    _m("rc-ret", "    spch_add_event_v(ev, 1, v);\n    return 1;",
       "    spch_add_event_v(ev, 1, v);\n    return 0;"),
    _m("rc-conv", "speech_convert_reward_car_type(carType)",
       "speech_convert_car_type(carType)"),
    _m("rt-dir", "direction == 1 ? 2 : 1", "direction == 1 ? 1 : 2"),
    _m("rt-dir0", "direction == 1 ? 2 : 1", "direction != 0 ? 2 : 1"),
    _m("rt-v0", "    if (v == 0)\n        return 0;\n    spch_add_event_v(151",
       "    spch_add_event_v(151"),
    _m("rt-conv", "speech_convert_unlock_track(track);",
       "speech_convert_track_number(track);"),
    _m("rt-ret", "    spch_add_event_v(151, 2, v, direction == 1 ? 2 : 1);\n"
       "    return 1;", "    spch_add_event_v(151, 2, v, direction == 1 ? "
       "2 : 1);\n    return 0;"),
    # ---- the rest
    _m("pts-b", "    if (bonus)\n", "    if (!bonus)\n"),
    _m("po-not", "    if (!replaying())\n        spch_add_event_v(206, 0);",
       "    if (replaying())\n        spch_add_event_v(206, 0);"),
    _m("ar-rep", "    if (replaying())\n        return;\n    if (players == 2)",
       "    if (players == 2)"),
    _m("ar-2", "if (players == 2) {", "if (players == 1) {"),
    _m("ar-m", "        if (missed)\n            v = 512;",
       "        if (!missed)\n            v = 512;"),
    _m("ar-w", "v = winner == 2 ? 0x8000 : 0x20000;",
       "v = winner == 1 ? 0x8000 : 0x20000;"),
    _m("ar-wv", "v = winner == 2 ? 0x8000 : 0x20000;",
       "v = winner == 2 ? 0x20000 : 0x8000;"),
    _m("ar-m1", "} else if (!missed) {", "} else if (missed) {"),
    _m("ar-1024", "v = 1024;", "v = 512;"),
    _m("ar-c0", "case 0:  v = 2048;", "case 0:  v = 4096;"),
    _m("ar-c1", "case 1:  v = 4096;", "case 3:  v = 4096;"),
    _m("ar-c2", "case 2:  v = 8192;", "case 3:  v = 8192;"),
    _m("ar-def", "default: v = 512;", "default: v = 1024;"),
    _m("ar-ev", "spch_add_event_v(213, 1, v);", "spch_add_event_v(212, 1, v);"),
    _m("bu-ev", "spch_add_event_v(214, 1, 1);", "spch_add_event_v(214, 1, 2);"),
    # ---- the event conversions' bounds
    _m("eb-lt", "    if (i < 0 || i >= n)\n        return 0;",
       "    if (i < 0 || i > n)\n        return 0;", C),
    _m("eb-a1", "event_bits(kHotPursuitEventA, 20, number - 1)",
       "event_bits(kHotPursuitEventA, 20, number)", C),
    _m("eb-b21", "event_bits(kHotPursuitEventB, 14, number - 21)",
       "event_bits(kHotPursuitEventB, 14, number - 20)", C),
    _m("eb-ca1", "event_bits(kChampionshipEventA, 20, number - 1)",
       "event_bits(kChampionshipEventA, 20, number)", C),
    _m("eb-cb21", "event_bits(kChampionshipEventB, 14, number - 21)",
       "event_bits(kChampionshipEventB, 14, number - 20)", C),
    _m("rw-67", "    if (carType < 0 || carType >= 67)\n        return 0;\n"
       "    return (int32_t)kRewardCarType",
       "    if (carType < 0 || carType >= 66)\n        return 0;\n"
       "    return (int32_t)kRewardCarType", C),
    _m("rw-neg", "    if (carType < 0 || carType >= 67)\n        return 0;\n"
       "    return (int32_t)kRewardCarType",
       "    if (carType < -1 || carType >= 67)\n        return 0;\n"
       "    return (int32_t)kRewardCarType", C),
]

MUTATIONS = (_table_mutations(S, "rt") + _gap_mutations()
             + _table_mutations(C, "ct", SC_TABLES) + _switch_mutations()
             + HAND)


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


EQUIVALENT = {
    # The replay demo, state 9, is said nothing by replaying()'s
    # IsReplayDemoMode before the demos' range is read, so only state 8
    # reaches that test.
    "wd-demo1": "state 9 never reaches the demos' range",
    # event_bits's bound is the port's: retail reads past each table, so
    # the script keeps to the numbers that read inside them, 1 to 20 and
    # 21 to 34, and the bound is never met.
    "eb-lt": "the event tables' bound is never met in retail's range",
    # Car type 66's entry is 0, as the bound answers.
    "rw-67": "kRewardCarType[66] is 0",
    # Type -1 reads the word before kRewardCarType: kCarTypeDescription's
    # last, 0 in this build, as the bound answers.
    "rw-neg": "the word before kRewardCarType is 0",
}


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
        todo, SOURCES, "racespeech_test",
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
