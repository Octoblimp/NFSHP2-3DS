#!/usr/bin/env python3
"""Cross-check 3DS Files/source/fredend.c, FrontendDatabase's end of a
race and the rewards it earns, against the retail image, SLES_507.31.

**The model** is retail's own code run in retail_model.RetailEmu:
TransientStatsElement::Construct, TransientStats' Construct and
GetDriver, FrontendDatabase's GetOptionsSetFromRace, FigureOutBonusPoints,
AwardPointsToPlayer, CheckForAbortion, RaceWasAborted, TheRaceIsLeaving,
TheRaceIsOver, TheRaceWasQuit and TheRaceWasRestarted (0x00186e08 ..
0x001878b0), and the rewards' NFSTaskParameters::CheckForCompletion,
GetTaskRewardList, GetPointsRewardList, CheckForTaskAndPointRewards,
TaskRewardsIsCarUnlocked, PointsRewardsIsCarUnlocked and IsCarUnlocked
(0x0024ab90 .. 0x0024b914). Under them run RacingCar's GetPlayer and
GetBestLapTime, Race::GetRacingCar, UseTheRaceEvent, bRandom on
bDefaultSeed, IsCarATaskReward, IsCarAPointsReward and the points
rewards' CheckForCompletion. The harness (tools/src/fredend_test.c) runs
fredend.c, nfsrewards.c and bmath.c.

**The stubs** print what they are asked, on both sides: tCopManager's
GetNumTickets, Player::GetFinishBonus, HighScoreTable's
MaybeRecordHighScore, SetAudioDataFromSound, RaceEvent's PostResults,
MaybeDiscardResults, CycleResults and the state kept (0x00201fb0), Race's
AreAllPlayersFinishedRacing, SimulateRaceFinish and NotifyTheRaceIsOver,
IsCarAnEventReward and EventTreeIsCarUnlocked. BodyDamage's
GetVisibleTotalDamage says nothing; CheckForCompletion drops what it
answers.

**Differences made equal by hand.** Retail's GetPlayer reads a NULL
player's New2540 from low memory, and CheckForCompletion a NULL car's
damage; the model keeps the image's low memory zero, as the port's NULL
tests read it. Retail's TransientStats::Construct has no bound: the
scripts keep a race to eight racing cars, the rows there are. A player's
number indexes Fred's two FrontendPlayers unchecked on both sides, so it
stays 0 or 1. The port's GetBestLapTime is the harness's here, without
racesplit.c's guard on the boundary; the scripts keep it under five.

**The script** builds two races of eight cars, two players and four car
types, and asks each function over every mix of what it reads: the rows
for player cars, AI cars, Be A Cop, the cop manager, the boundary and the
number of laps; the options for each game type and number of players;
the bonus for every field and place; the points, abortion, the race's
end, quit and restart for each kind of race; each task's tests one field
at a time, and the script's own task with each test on and off; the
reward lists over every state; the unlocked tests over every car and
game type; then random mixes.

    python tools/fredend_check.py
    python tools/fredend_check.py --mutate [--only a,b]
    python tools/fredend_check.py --dump out/fredend
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

HARNESS = "tools/src/fredend_test.c"
FE = "3DS Files/source/fredend.c"
FH = "3DS Files/source/fredend.h"
SOURCES = [HARNESS, FE, "3DS Files/source/nfsrewards.c",
           "3DS Files/source/bprintf.c", "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c"]
HARNESS_TIMEOUT = 120

GP = retail_model.RETAIL_GP
FRED = 0x002fc050
FED_SIZE = 0x114e0
RP = 0x0031a898
RP_SIZE = 788
NFS_TASKS = 0x0031cfc0
NFS_POINTS = 0x0031d1f0
P_CUR_RACE = GP - 22272
P_COP = GP - 15620
P_SEED = GP - 14472
P_NUM_PLAYERS = GP - 20920
P_BY_NUMBER = GP - 20936
P_BY_INDEX = GP - 20928

F_TSE = 0x00186e08
F_TS = 0x00186ff0
F_DRIVER = 0x00187080
F_OPTS = 0x001870d0
F_BONUS = 0x00187378
F_AWARD = 0x00187438
F_ABORT = 0x00187518
F_ABORTED = 0x00187560
F_LEAVING = 0x00187570
F_OVER = 0x001875a0
F_QUIT = 0x00187800
F_RESTARTED = 0x00187880
F_TCC = 0x0024ab90
F_TLIST = 0x0024ad90
F_PLIST = 0x0024aff8
F_CTPR = 0x0024b7b0
F_TUNL = 0x0024aed0
F_PUNL = 0x0024b120
F_UNL = 0x0024b208

S_TICKETS = 0x00228520
S_BONUS = 0x0017e2d0
S_RECORD = 0x00186af0
S_AUDIO = 0x001eef60
S_POST = 0x002018f8
S_DISCARD = 0x00201a80
S_CYCLE = 0x00201ac0
S_KEEP = 0x00201fb0
S_ALLFIN = 0x001490b0
S_SIMULATE = 0x00148f68
S_NOTIFY = 0x00148ff8
S_EVREWARD = 0x001ff8b8
S_EVUNLOCK = 0x001ff918
S_DAMAGE = 0x001b50c8

# FrontendDatabase.
F_STATS = 908
F_ROWS = F_STATS + 12
ROW = 100
F_HIGH_SCORES = 1720
F_TASK_STATES = 0x106b8
F_POINTS_STATES = 0x106e0
F_GAME_TYPE = 0x1072c
F_NUM_PLAYER_CARS = 0x10734
F_PLAYERS = 0x10738
FPI = 1744
FPI_POINTS = 1740
F_AUDIO = 148

# RaceParameters.
RP_LAPS, RP_NPC, RP_NAI, RP_DAMAGE = 44, 48, 52, 64
RP_MAX_COPS, RP_BEACOP, RP_DISPLAY, RP_STRENGTH = 604, 628, 748, 756

PLAYER_SIZE, CAR_SIZE, RC_SIZE, CTI_SIZE = 2600, 2200, 192, 1376
RACE_SIZE, COP_SIZE = 1700, 10500
NUM_CARS, NUM_CTI = 8, 4

TASKS = [
    # MinDamage, NumPlayers, GameType, NumOpponents, NumLaps, SkillLevel,
    # NumLapsToLead, Cops
    (0.0, 1, 3, -1, 4, 1, -1, -1),
    (0.0, 1, 3, -1, 8, 1, -1, -1),
    (-1.0, 1, 3, 3, 2, 1, 2, 1),
    (-1.0, 1, 3, 7, 2, 1, 2, 0),
    (-1.0, 1, 3, 3, 4, 1, 4, 1),
    (-1.0, 1, 3, 7, 4, 1, 4, 0),
    (-1.0, 1, 3, -1, 8, 1, 8, 0),
    (-1.0, 1, 4, -1, -1, 1, -1, 1),
    (-1.0, 1, 4, -1, -1, 1, -1, 0),
    (-1.0, 1, 5, -1, -1, 1, -1, 1),
]
POINTS = [50000, 100000, 150000, 200000, 250000, 300000, 400000, 500000,
          750000, 1000000, 1500000, 2000000, 2500000, 3000000, 3500000,
          4000000, 4500000, 5000000]


def fbits(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


NAN = 0x7fc00000


# ================================================================ the script

class World(object):
    """The script, and what it has set, so that one field of a racing car
    or a player can change by itself."""

    def __init__(self):
        self.L = []
        self.rcs = {}
        self.pls = {}
        self.races = {}
        self.ans = [5, 1000, 0, 0, 0]

    def op(self, *a):
        self.L.append("|".join(str(x) for x in a))

    def rc(self, i, **kw):
        d = self.rcs.setdefault(i, dict(car=i, pos=i + 1, fin=i + 1,
                                        laps=3, led=0, reason=0, time=0,
                                        top=fbits(40.0), avg=fbits(30.0)))
        d.update(kw)
        self.op("rc", i, d["car"], d["pos"], d["fin"], d["laps"], d["led"],
                d["reason"], d["time"], d["top"], d["avg"])

    def pl(self, i, **kw):
        d = self.pls.setdefault(i, dict(num=i, fin=1, score=0, n2540=1,
                                        car=i))
        d.update(kw)
        self.op("pl", i, d["num"], d["fin"], d["score"], d["n2540"],
                d["car"])

    def race(self, w, rcs, fin=None):
        old = self.races.get(w, (0, []))
        if fin is None:
            fin = old[0]
        self.races[w] = (fin, list(rcs))
        r = list(rcs) + [-1] * (8 - len(rcs))
        self.op("race", w, len(rcs), fin, *r)

    def answers(self, **kw):
        keys = ["tickets", "bonus", "allfin", "evr", "evu"]
        for k, v in kw.items():
            self.ans[keys.index(k)] = v
        self.op("ans", *self.ans)

    def fw(self, f, off, v, size=4):
        self.op("fw", f, off, size, v)

    def rw(self, off, v, size=4):
        self.op("rw", off, size, v)

    def gt(self, f, v):
        self.fw(f, F_GAME_TYPE, v)

    def npc(self, f, v):
        self.fw(f, F_NUM_PLAYER_CARS, v)

    def points(self, f, n, v):
        self.fw(f, F_PLAYERS + n * FPI + FPI_POINTS, v)

    def tstate(self, i, v, f=0):
        self.fw(f, F_TASK_STATES + 4 * i, v)

    def pstate(self, i, v, f=0):
        self.fw(f, F_POINTS_STATES + 4 * i, v)


def world():
    w = World()
    w.op("seed", 0x12345678)
    w.op("cop", 0, 0)
    w.answers()
    w.op("cur", 0)
    for i, lim in enumerate((50.0, 70.0, 1e30, 0.0)):
        w.op("cti", i, fbits(lim))
    w.pl(0, score=500)
    w.pl(1, score=300)
    for i in range(2):
        for off in range(48):
            w.op("ps", i, off, (i * 48 + off * 7 + 3) & 0xff)
    w.op("players", 2, 0, 1, 0, 1)
    for i in range(NUM_CARS):
        drv = (10 + i) if i != 7 else -3
        w.op("car", i, drv, i % NUM_CTI, i if i < 2 else -1, i)
    tops = [55.0, 66.5, 45.25, 80.0, 49.9, 120.0, -3.0, 0.0]
    for i in range(NUM_CARS):
        w.rc(i, pos=i + 1, fin=8 - i, laps=i + 1, led=i * 2 - 3,
             reason=(i * 3) % 5 - 1, time=0x1000 * (i + 1) + i,
             top=fbits(tops[i]), avg=fbits(tops[i] * 0.75))
        for k in range(11):
            w.op("rclap", i, k, 0x100 * (i + 1) + k * 17 + 1)
        for k in range(5):
            w.op("rcbest", i, k, 0x80 * (i + 1) + k * 31 + 5)
    w.race(0, range(8), fin=0)
    w.race(1, [2, 0, 1], fin=2)
    w.points(0, 0, 123456)
    w.points(0, 1, 654321)
    w.points(1, 0, 777)
    w.points(1, 1, 888)
    for k in range(8):
        w.rw(RP_DISPLAY + k, 0x11 * (k + 1), 1)
    w.rw(RP_DAMAGE, 1)
    return w


def rows(w):
    """TransientStatsElement::Construct over its readings."""
    for beacop in (0, 1):
        w.rw(RP_BEACOP, beacop)
        for cop in ((0, 0), (1, fbits(12.5)), (1, fbits(-7.25))):
            w.op("cop", *cop)
            for cur in (0, 1):
                w.op("cur", cur)
                for fin in range(5):
                    w.race(cur, w.races[cur][1], fin=fin)
                    for rc in range(NUM_CARS):
                        w.op("tse", rc % 2, rc, rc)
    w.op("cur", 0)
    w.race(1, w.races[1][1], fin=2)
    w.op("cop", 1, fbits(99.5))
    w.rw(RP_BEACOP, 1)
    # Who the first player is.
    for n0, n1 in ((1, 0), (0, 0), (1, 1), (0, 1)):
        w.pl(0, num=n0)
        w.pl(1, num=n1)
        for rc in (0, 1, 2):
            w.op("tse", 0, rc, rc)
            w.op("tse", 1, 7 - rc, rc)
    # The laps kept.
    for laps in (-128, -2, -1, 0, 1, 2, 9, 10, 11, 12, 100, 127):
        for rc in (0, 3):
            w.rc(rc, laps=laps)
            w.op("tse", 0, rc, rc)
    w.rc(0, laps=1)
    w.rc(3, laps=4)
    # The AI's top speed against each limit, and the seed's run.
    for top in (0.0, -0.0, 1.0, 49.0, 50.0, 51.0, 69.99, 70.0, 70.01,
                1e20, -1e20, 1e38):
        for rc in (2, 3, 4, 5):
            w.rc(rc, top=fbits(top))
            w.op("tse", 1, rc, rc)
    for seed in (0, 1, 0xffffffff, 0x80000000, 0x7fffffff, 0xdeadbeef):
        w.op("seed", seed)
        for k in range(6):
            w.op("tse", 0, 4, 2 + k % 6)
    # A limit of -0 and of NaN, against a top speed of 0.
    for lim in (fbits(-0.0), NAN, fbits(0.0)):
        w.op("cti", 3, lim)
        for top in (0.0, -0.0, 1.0):
            w.rc(3, top=fbits(top))
            w.op("tse", 0, 3, 3)
    w.rc(3, top=fbits(45.25))
    w.op("seed", 0x12345678)
    # A player car without a type: retail reads it only for the AI.
    w.op("car", 0, 10, -1, 0, 0)
    w.op("tse", 0, 0, 0)
    w.op("car", 0, 10, 0, 0, 0)
    # A car with no driver number but its own, and one with a negative.
    for drv in (0, -1, 32767, -32768, 255):
        w.op("car", 5, drv, 1, -1, 5)
        w.op("tse", 1, 5, 5)
    w.op("car", 5, 15, 1, -1, 5)
    w.pl(0, num=0)
    w.pl(1, num=1)
    w.rw(RP_BEACOP, 0)
    w.op("cop", 0, 0)


def tables(w):
    """TransientStats' Construct and GetDriver."""
    drivers = [-3, -1, 0, 9, 10, 11, 12, 13, 14, 15, 16, 17, 99]
    for f in (0, 1):
        for n in range(9):
            w.race(0, list(range(n)))
            w.op("ts", f)
            for d in drivers:
                w.op("drv", f, d)
        w.race(0, [7, 3, 0, 1, 5])
        w.op("ts", f)
        for d in drivers:
            w.op("drv", f, d)
    # Two cars with one number: the first row.
    w.op("car", 4, 11, 0, -1, 4)
    w.race(0, [0, 4, 1, 2])
    w.op("ts", 0)
    w.op("drv", 0, 11)
    w.op("car", 4, 14, 0, -1, 4)
    # A count the rows do not have.
    for n in (-1, 0, 3, 8):
        w.fw(0, F_STATS, n)
        for d in (10, 11, 17, -3):
            w.op("drv", 0, d)
    w.race(0, range(8))


def options(w):
    """GetOptionsSetFromRace."""
    for np, bi in ((0, (-1, -1)), (1, (0, -1)), (1, (1, -1)), (2, (0, 1)),
                   (2, (1, 0))):
        w.op("players", np, 0, 1, bi[0], bi[1])
        for f in (0, 1):
            for gt in range(-1, 11):
                w.gt(f, gt)
                w.rw(RP_DAMAGE, (gt * 3 + np) % 4 - 1)
                w.op("opts", f)
            for k in range(8):
                w.rw(RP_DISPLAY + k, (0x23 * (k + np + f + 1)) & 0xff, 1)
            w.op("opts", f)
        for off in (0, 2, 7, 20, 31, 47):
            w.op("ps", 0, off, (off * 13 + np) & 0xff)
            w.op("ps", 1, off, (off * 29 + np) & 0xff)
        w.pl(0, num=1)
        w.pl(1, num=0)
        w.op("opts", 0)
        w.pl(0, num=0)
        w.pl(1, num=1)
        w.op("opts", 1)
    w.op("players", 2, 0, 1, 0, 1)
    w.gt(0, 0)
    w.gt(1, 0)


def bonus(w):
    """FigureOutBonusPoints, and AwardPointsToPlayer over it."""
    for beacop in (0, 1, -1):
        w.rw(RP_BEACOP, beacop)
        for n in range(10):
            # NumRacingCars by itself, past the eight cars too.
            w.L.append("race|0|%d|0|0|1|2|3|4|5|6|7" % n)
            places = range(-1, 10) if beacop == 0 else (1, 2)
            for place in places:
                w.rc(0, fin=place)
                w.op("bonus", 0, 0)
            w.rc(1, fin=1)
            w.op("bonus", 1, 1)
            w.op("bonus", 0, 2)
    w.rw(RP_BEACOP, 0)
    w.race(0, range(8), fin=0)
    for num in (1, 0):
        w.pl(0, num=num)
        for place in (1, 2, 3):
            w.rc(0, fin=place)
            w.op("bonus", 1, 0)
    # A racing car without a car.
    w.rc(6, car=-1)
    w.op("bonus", 0, 6)
    w.op("award", 0, 6)
    w.rc(6, car=6)
    w.rc(0, fin=1)
    for f in (0, 1):
        for beacop in (0, 1):
            w.rw(RP_BEACOP, beacop)
            for cop in ((0, 0), (1, fbits(0.0)), (1, fbits(12.7)),
                        (1, fbits(-5.5)), (1, fbits(3600.9)),
                        (1, fbits(2e7)), (1, fbits(0.99))):
                w.op("cop", *cop)
                for rc, fin in ((0, 1), (0, 4), (1, 2), (2, 1)):
                    w.rc(rc, fin=fin)
                    w.op("award", f, rc)
    w.rw(RP_BEACOP, 0)
    w.op("cop", 0, 0)
    for score in (0, -100, 0x7fff, 1000000):
        w.pl(0, score=score)
        w.op("award", 0, 0)
    w.pl(0, score=500)
    w.rc(0, fin=8)


def abortion(w):
    """CheckForAbortion and RaceWasAborted."""
    for bi0 in (-1, 0, 1):
        for bi1 in (-1, 0, 1):
            for f0, f1 in ((0, 0), (1, 0), (0, 7), (1, 7), (0x80000000, 1)):
                w.op("players", 2, 0, 1, bi0, bi1)
                w.pl(0, fin=f0)
                w.pl(1, fin=f1)
                for f in (0, 1):
                    w.fw(f, 0x10728, 5)
                    w.op("abort", f)
                    w.op("aborted", f)
    w.fw(1, 0x10728, -1)
    w.op("aborted", 1)
    w.pl(0, fin=1)
    w.pl(1, fin=1)
    w.op("players", 2, 0, 1, 0, 1)


def leaving(w):
    """TheRaceIsLeaving and TheRaceWasRestarted."""
    for f in (0, 1):
        for gt in range(-2, 12):
            w.gt(f, gt)
            w.op("leaving", f)
            w.op("restarted", f)
    w.gt(0, 0)
    w.gt(1, 0)


def over(w):
    """TheRaceIsOver over its kinds of race."""
    fields = ([0, 1, 2, 3], [0, 2, 3], [1, 2], [2, 3], [0, 1], [1, 0, 5],
              [3, 1, 2, 0, 4, 5, 6, 7], [])
    for f in (0, 1):
        for gtf, gto in ((3, 3), (7, 7), (4, 4), (8, 8), (2, 2), (7, 3),
                         (3, 7), (9, 0)):
            w.gt(0, gtf)
            if f:
                w.gt(1, gto)
            for npc in (1, 0, 2):
                w.npc(f, npc)
                for field in fields:
                    w.race(0, field)
                    w.op("over", f)
    w.npc(1, 1)
    w.npc(0, 1)
    w.gt(0, 3)
    w.gt(1, 3)
    # Who is which player, and the better best lap.
    w.race(0, [0, 1, 2, 3])
    for n0, n1 in ((0, 1), (1, 0), (0, 0), (1, 1)):
        w.pl(0, num=n0)
        w.pl(1, num=n1)
        for b0, b1 in ((5, 9), (9, 5), (7, 7), (-5, 9), (9, -5),
                       (0x7fffffff, -1), (0, 0)):
            for fin in (0, 3):
                w.race(0, w.races[0][1], fin=fin)
                w.op("rcbest", 0, fin, b0)
                w.op("rcbest", 1, fin, b1)
                w.op("over", 0)
    w.pl(0, num=0)
    w.pl(1, num=1)
    # The other race and the current one apart.
    w.op("cur", 1)
    w.op("over", 0)
    w.op("cur", 0)
    # One player, with a task and points to earn.
    w.op("players", 1, 0, -1, 0, -1)
    setup_task(w, 2)
    w.points(0, 0, 49000)
    w.pl(0, score=600, n2540=1)
    for f in (0, 1):
        for gt in (3, 4, 2):
            w.gt(0, gt)
            w.gt(1, gt)
            for k in range(10):
                w.tstate(k, 0)
            for k in range(18):
                w.pstate(k, 0)
            w.op("over", f)
            w.op("over", f)
    w.points(0, 0, 123456)
    w.op("players", 2, 0, 1, 0, 1)
    w.gt(0, 0)
    w.gt(1, 0)


def quit_(w):
    """TheRaceWasQuit."""
    for f in (0, 1):
        for gt in (0, 3, 4, 7, 8, 9, 10):
            w.gt(f, gt)
            for allfin in (0, 1, -1):
                w.answers(allfin=allfin)
                for cur in (0, 1):
                    w.op("cur", cur)
                    w.pl(0, fin=cur)
                    w.op("quit", f)
    w.op("cur", 0)
    w.pl(0, fin=1)
    w.answers(allfin=0)
    w.gt(0, 0)
    w.gt(1, 0)


def setup_task(w, t, rc=0):
    """The race task t asks for, on racing car rc."""
    (mind, np_, gt, no, nl, sk, ltl, cops) = TASKS[t]
    w.rw(RP_NPC, np_)
    w.gt(0, gt)
    w.npc(0, 1)
    nai = no if no != -1 else 1
    w.rw(RP_NAI, nai)
    w.rw(RP_LAPS, nl if nl != -1 else 3)
    w.rw(RP_STRENGTH, sk)
    w.rc(rc, fin=1, led=ltl if ltl != -1 else 1)
    w.rw(RP_MAX_COPS, 3 if cops == 1 else 0)
    w.pl(0, n2540=1)


def tasks(w):
    """Each task's tests, one field at a time."""
    w.race(0, range(8))
    for t in range(10):
        setup_task(w, t)
        for k in range(-1, 10):
            w.op("tcc", k, 0)
        # Each field off and back.
        changes = [
            (lambda: w.rw(RP_NPC, 2), lambda: w.rw(RP_NPC, 1)),
            (lambda: w.rw(RP_NPC, 0), lambda: w.rw(RP_NPC, 1)),
            (lambda: w.gt(0, 2), lambda: w.gt(0, TASKS[t][2])),
            (lambda: w.gt(0, 7), lambda: w.gt(0, TASKS[t][2])),
            (lambda: w.gt(1, 4), lambda: w.gt(1, 0)),
            (lambda: w.npc(0, 2), lambda: w.npc(0, 1)),
            (lambda: w.npc(0, 0), lambda: w.npc(0, 1)),
            (lambda: w.rw(RP_NAI, 0), lambda: setup_task(w, t)),
            (lambda: w.rw(RP_NAI, 2), lambda: setup_task(w, t)),
            (lambda: w.rw(RP_NAI, 3), lambda: setup_task(w, t)),
            (lambda: w.rw(RP_NAI, 7), lambda: setup_task(w, t)),
            (lambda: w.rw(RP_LAPS, 2), lambda: setup_task(w, t)),
            (lambda: w.rw(RP_LAPS, 4), lambda: setup_task(w, t)),
            (lambda: w.rw(RP_LAPS, 8), lambda: setup_task(w, t)),
            (lambda: w.rw(RP_STRENGTH, 0), lambda: setup_task(w, t)),
            (lambda: w.rw(RP_STRENGTH, 2), lambda: setup_task(w, t)),
            (lambda: w.rc(0, led=0), lambda: setup_task(w, t)),
            (lambda: w.rc(0, led=4), lambda: setup_task(w, t)),
            (lambda: w.rc(0, led=-1), lambda: setup_task(w, t)),
            (lambda: w.rw(RP_MAX_COPS, 0), lambda: setup_task(w, t)),
            (lambda: w.rw(RP_MAX_COPS, 1), lambda: setup_task(w, t)),
            (lambda: w.rw(RP_MAX_COPS, -2), lambda: setup_task(w, t)),
            (lambda: w.rc(0, fin=2), lambda: setup_task(w, t)),
            (lambda: w.rc(0, fin=0), lambda: setup_task(w, t)),
            (lambda: w.pl(0, n2540=0), lambda: setup_task(w, t)),
            (lambda: w.pl(0, n2540=-1), lambda: setup_task(w, t)),
        ]
        for on, off in changes:
            on()
            w.op("tcc", t, 0)
            w.op("tcc", -1, 0)
            off()
        # The AI and a car with no car.
        w.op("tcc", t, 2)
        w.rc(6, car=-1)
        w.op("tcc", t, 6)
        w.rc(6, car=6)
        # A knockout's field.
        if TASKS[t][2] == 4:
            for npc_rp, nai in ((1, 1), (1, 2), (2, 0), (2, 1), (0, 2),
                                (0, 3)):
                for fnpc in (1, 2):
                    w.rw(RP_NPC, npc_rp)
                    w.rw(RP_NAI, nai)
                    w.npc(0, fnpc)
                    for fin in (1, 2):
                        w.rc(0, fin=fin)
                        w.op("tcc", t, 0)
            setup_task(w, t)


def custom(w):
    """The script's task, each test on and off."""
    setup_task(w, 2)
    base = [fbits(-1.0), -1, -1, -1, -1, -1, -1, -1]
    w.op("task", *base)
    w.op("tcc", -1, 0)
    w.op("tcc", -1, 2)
    values = [
        [fbits(0.0), fbits(5.0), NAN, fbits(-1.0001), fbits(-0.0)],
        [0, 1, 2],
        [2, 3, 4, 5, 7],
        [0, 1, 3, 7],
        [2, 3, 4],
        [0, 1, 2],
        [0, 1, 2, 4],
        [0, 1, 2],
    ]
    for k, vs in enumerate(values):
        for v in vs:
            t = list(base)
            t[k] = v
            w.op("task", *t)
            w.op("tcc", -1, 0)
            w.op("tcc", -1, 2)
            w.pl(0, n2540=0)
            w.op("tcc", -1, 0)
            w.pl(0, n2540=1)
    for gt in (4, 5, 3, 6, 7):
        t = list(base)
        t[2] = gt
        w.op("task", *t)
        w.gt(0, gt)
        for fnpc in (0, 1, 2):
            w.npc(0, fnpc)
            for npc_rp, nai in ((1, 1), (1, 2), (2, 0), (0, 3), (2, 1),
                                (0, 2)):
                w.rw(RP_NPC, npc_rp)
                w.rw(RP_NAI, nai)
                for fin in (1, 2, 0):
                    w.rc(0, fin=fin)
                    w.op("tcc", -1, 0)
    setup_task(w, 2)


def lists(w):
    """The reward lists, and CheckForTaskAndPointRewards."""
    rnd = random.Random(40)
    for t in range(10):
        setup_task(w, t)
        for states in ([0] * 10, [1] * 10, None, None, None):
            if states is None:
                states = [rnd.choice((0, 0, 1, 2, -1)) for _ in range(10)]
            for k in range(10):
                w.tstate(k, states[k])
            w.op("tlist", 0)
            w.op("tlist", 2)
    for k in range(10):
        w.tstate(k, 0)
    pts_list = [-0x80000000, -1, 0, 49999, 50000, 50001, 149999, 150000,
                1000000, 2999999, 4999999, 5000000, 5000001, 0x7fffffff]
    for states in ([0] * 18, [1] * 18, None, None):
        if states is None:
            states = [rnd.choice((0, 0, 1, -1, 3)) for _ in range(18)]
        for k in range(18):
            w.pstate(k, states[k])
        for pts in pts_list:
            w.op("plist", pts)
    for k in range(18):
        w.pstate(k, 0)
    # CheckForTaskAndPointRewards.
    for np_, bn0 in ((1, 0), (0, 0), (1, -1), (2, 0), (-1, 0), (3, 1),
                     (1, 1)):
        w.op("players", np_, bn0, 1, 0, 1)
        for t in (2, 7, 9, 0, 4, 6):
            setup_task(w, t)
            for gt in (TASKS[t][2], 2):
                w.gt(0, gt)
                for pts in (0, 50000, 260000, 5000000):
                    w.points(0, 0, pts)
                    for k in range(10):
                        w.tstate(k, 0)
                    for k in range(18):
                        w.pstate(k, 0)
                    w.op("ctpr")
                    w.op("ctpr")
    # The car the first player drives.
    w.op("players", 1, 0, -1, 0, -1)
    setup_task(w, 2)
    w.pl(0, car=1)
    w.op("ctpr")
    w.rc(1, fin=1, led=2)
    for k in range(10):
        w.tstate(k, 0)
    w.op("ctpr")
    w.pl(0, car=0)
    w.op("players", 2, 0, 1, 0, 1)
    w.points(0, 0, 123456)


def unlocked(w):
    """The three unlocked tests."""
    rnd = random.Random(41)
    cars = list(range(-1, 52)) + [99, -100]
    for states in ("zero", "one", "rnd"):
        for k in range(10):
            w.tstate(k, {"zero": 0, "one": 1}.get(states)
                     if states != "rnd" else rnd.choice((0, 1, 2)))
        for k in range(18):
            w.pstate(k, {"zero": 0, "one": 1}.get(states)
                     if states != "rnd" else rnd.choice((0, 1, -1)))
        for evr, evu in ((0, 0), (0xffffffff, 0), (0xffffffff, 0xffffffff),
                         (0x5a5a5a5a, 0x33333333)):
            w.answers(evr=evr, evu=evu)
            for car in cars:
                for gt in (-1, 0, 3, 7, 8):
                    w.op("unl", car, gt)
            for car in cars:
                w.op("punl", car)
                for gt in (-1, 3, 7):
                    w.op("tunl", car, gt)
    w.answers(evr=0, evu=0)
    # Fred's states, not the second database's.
    for k in range(10):
        w.tstate(k, 1, f=1)
    for k in range(18):
        w.pstate(k, 1, f=1)
    for car in (16, 31, 15, 20):
        w.op("unl", car, 3)
        w.op("unl", car, 7)


def random_mix(rnd, n):
    w = World()
    L = w.L
    for _ in range(n):
        k = rnd.randrange(24)
        f = rnd.randrange(2)
        rc = rnd.randrange(8)
        if k == 0:
            w.gt(f, rnd.choice((-1, 0, 2, 3, 4, 5, 6, 7, 8, 9, 10)))
        elif k == 1:
            w.npc(f, rnd.choice((0, 1, 2)))
        elif k == 2:
            w.rw(rnd.choice((RP_LAPS, RP_NPC, RP_NAI, RP_DAMAGE, RP_MAX_COPS,
                             RP_BEACOP, RP_STRENGTH)),
                 rnd.choice((-1, 0, 1, 2, 3, 4, 7, 8)))
        elif k == 3:
            L.append("rc|%d|%d|%d|%d|%d|%d|%d|%d|%d|%d" % (
                rc, rc, rnd.randrange(-1, 9),
                rnd.randrange(-1, 9), rnd.randrange(-3, 13),
                rnd.randrange(-2, 9), rnd.randrange(-2, 5),
                rnd.randrange(0, 0x100000),
                fbits(rnd.uniform(-10, 200)), fbits(rnd.uniform(0, 150))))
        elif k == 4:
            m = rnd.randrange(0, 9)
            cs = rnd.sample(range(8), m)
            L.append("race|%d|%d|%d|%s" % (
                rnd.randrange(2), m, rnd.randrange(5),
                "|".join(str(c) for c in cs + [-1] * (8 - m))))
        elif k == 5:
            L.append("cur|%d" % rnd.randrange(2))
        elif k == 6:
            L.append("cop|%d|%d" % (rnd.randrange(2),
                                    fbits(rnd.uniform(-20, 500))))
        elif k == 7:
            np_ = rnd.randrange(0, 3)
            bi = [rnd.randrange(2), rnd.randrange(2)]
            L.append("players|%d|%d|%d|%d|%d" % (
                np_, rnd.randrange(-1, 2), rnd.randrange(-1, 2),
                bi[0], bi[1]))
        elif k == 8:
            L.append("pl|%d|%d|%d|%d|%d|%d" % (
                rnd.randrange(2), rnd.randrange(2), rnd.randrange(3),
                rnd.randrange(-100, 5000), rnd.randrange(2),
                rnd.randrange(2)))
        elif k == 9:
            w.tstate(rnd.randrange(10), rnd.randrange(-1, 3))
        elif k == 10:
            w.pstate(rnd.randrange(18), rnd.randrange(-1, 3))
        elif k == 11:
            w.points(f, rnd.randrange(2), rnd.randrange(-1000, 6000000))
        elif k == 12:
            L.append("rcbest|%d|%d|%d" % (rc, rnd.randrange(5),
                                          rnd.randrange(-50, 5000)))
        elif k == 13:
            L.append("tse|%d|%d|%d" % (f, rnd.randrange(8), rc))
        elif k == 14:
            L.append("ts|%d" % f)
            L.append("drv|%d|%d" % (f, rnd.choice((-3, 10, 11, 12, 15, 99))))
        elif k == 15:
            L.append("opts|%d" % f)
        elif k == 16:
            L.append("%s|%d|%d" % (rnd.choice(("bonus", "award")), f, rc))
        elif k == 17:
            L.append("%s|%d" % (rnd.choice(("abort", "aborted", "leaving",
                                            "restarted")), f))
        elif k == 18:
            L.append("over|%d" % f)
        elif k == 19:
            L.append("quit|%d" % f)
        elif k == 20:
            L.append("tcc|%d|%d" % (rnd.randrange(-1, 10), rc))
        elif k == 21:
            L.append(rnd.choice(("tlist|%d" % rc,
                                 "plist|%d" % rnd.randrange(-10, 6000000),
                                 "ctpr")))
        elif k == 22:
            L.append("unl|%d|%d" % (rnd.randrange(-1, 50),
                                    rnd.choice((-1, 3, 4, 7))))
        else:
            L.append("ans|%d|%d|%d|%d|%d" % (
                rnd.randrange(-3, 9), rnd.randrange(0, 5000),
                rnd.randrange(-1, 2), rnd.getrandbits(32),
                rnd.getrandbits(32)))
    return L


def script():
    w = world()
    rows(w)
    tables(w)
    options(w)
    bonus(w)
    abortion(w)
    leaving(w)
    over(w)
    quit_(w)
    tasks(w)
    custom(w)
    lists(w)
    unlocked(w)
    sc = w.L
    rnd = random.Random(2002)
    for _ in range(6):
        sc += random_mix(rnd, 400)
    return sc


# ================================================================ the model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        # Low memory as a NULL player's or car's reads find it.
        e.write(0, bytes(4096))
        e.write(FRED, bytes(FED_SIZE))
        e.write(RP, bytes(RP_SIZE))
        self.fed2 = e.alloc(FED_SIZE, 64)
        e.write(self.fed2, bytes(FED_SIZE))
        self.feds = [FRED, self.fed2]

        def blocks(n, size):
            out = []
            for _ in range(n):
                a = e.alloc(size, 64)
                e.write(a, bytes(size))
                out.append(a)
            return out
        self.players = blocks(2, PLAYER_SIZE)
        self.cars = blocks(NUM_CARS, CAR_SIZE)
        self.rcs = blocks(NUM_CARS, RC_SIZE)
        self.ctis = blocks(NUM_CTI, CTI_SIZE)
        self.races = blocks(2, RACE_SIZE)
        self.cop = blocks(1, COP_SIZE)[0]
        self.task = blocks(1, 64)[0]
        self.list = blocks(1, 128)[0]
        self.n = blocks(1, 16)[0]

        e.put32(P_CUR_RACE, self.races[0])
        e.put32(P_COP, 0)
        e.put32(P_SEED, 0x12345678)
        e.put32(P_NUM_PLAYERS, 0)
        for k in range(2):
            e.put32(P_BY_NUMBER + 4 * k, 0)
            e.put32(P_BY_INDEX + 4 * k, 0)

        self.prev = [bytearray(FED_SIZE), bytearray(FED_SIZE)]
        self.prev_rp = bytearray(RP_SIZE)
        self.prev_seed = 0x12345678
        self.ans = [0, 0, 0, 0, 0]

        for a, fn in ((S_TICKETS, self.tickets), (S_BONUS, self.bonus),
                      (S_RECORD, self.record), (S_AUDIO, self.audio),
                      (S_POST, self.say("post results")),
                      (S_DISCARD, self.say("discard results")),
                      (S_CYCLE, self.say("cycle results")),
                      (S_KEEP, self.say("keep state")),
                      (S_ALLFIN, self.allfin),
                      (S_SIMULATE, self.race_say("simulate")),
                      (S_NOTIFY, self.race_say("notify")),
                      (S_EVREWARD, self.ev(3, "evreward")),
                      (S_EVUNLOCK, self.ev(4, "evunlock")),
                      (S_DAMAGE, self.silent)):
            e.stub(a, fn)

    def emit(self, s):
        self.out.append(s)

    def arg(self, i):
        return self.e.reg[4 + i] & M32

    def sarg(self, i):
        return s32(self.e.reg[4 + i])

    # ---- the blocks

    @staticmethod
    def index(p, blocks):
        for i, a in enumerate(blocks):
            if p == a:
                return i
        return -1

    @staticmethod
    def at(i, blocks):
        return 0 if i < 0 else blocks[i]

    # ---- the stubs

    def silent(self, e):
        pass

    def tickets(self, e):
        c = self.index(self.arg(1), self.cars)
        self.emit("tickets %d car %d" % (int(self.arg(0) == self.cop), c))
        return s32(self.ans[0] + c)

    def bonus(self, e):
        place = self.sarg(1)
        self.emit("finish bonus %d place %d"
                  % (self.index(self.arg(0), self.players), place))
        return s32(self.ans[1] + place * 100)

    def record(self, e):
        t = self.arg(0)
        f = self.index(t - F_HIGH_SCORES, self.feds)
        self.emit("record %d race %d rc %d"
                  % (f, self.index(self.arg(1), self.races),
                     self.index(self.arg(2), self.rcs)))

    def audio(self, e):
        f = self.index(self.arg(0) - F_AUDIO, self.feds)
        self.emit("audio %d %d" % (f, self.sarg(1)))

    def say(self, what):
        def fn(e):
            self.emit(what)
        return fn

    def allfin(self, e):
        self.emit("allfin %d" % self.index(self.arg(0), self.races))
        return s32(self.ans[2])

    def race_say(self, what):
        def fn(e):
            self.emit("%s %d" % (what, self.index(self.arg(0), self.races)))
        return fn

    def ev(self, k, what):
        def fn(e):
            car = self.sarg(0)
            self.emit("%s %d" % (what, car))
            return (self.ans[k] >> (car & 31)) & 1
        return fn

    # ---- the dump

    def dump_rows(self, name, base, prev, lo, hi):
        now = self.e.read(base + lo, hi - lo)
        if now == bytes(prev[lo:hi]):
            return
        for off in range(lo, hi, 32):
            n = min(32, hi - off)
            a = now[off - lo:off - lo + n]
            if a == bytes(prev[off:off + n]):
                continue
            self.emit("  %s %05x:%s" % (name, off,
                                        "".join(" %02x" % b for b in a)))
        prev[lo:hi] = now

    def dump(self):
        for i, name in enumerate(("fred", "fed2")):
            self.dump_rows(name, self.feds[i], self.prev[i], 0, 1720)
            self.dump_rows(name, self.feds[i], self.prev[i], F_TASK_STATES,
                           FED_SIZE)
        self.dump_rows("rp", RP, self.prev_rp, 0, RP_SIZE)
        seed = self.e.u32(P_SEED)
        if seed != self.prev_seed:
            self.emit("  seed %08x" % seed)
            self.prev_seed = seed

    def row(self, p, f):
        if p == 0:
            self.emit("  row none")
            return
        base = self.feds[f] + F_ROWS
        self.emit("  row %d of %d" % (f, (p - base) // ROW))

    # ---- the ops

    def put(self, a, size, v):
        self.e.write(a, struct.pack("<I", v & M32)[:size])

    def op(self, a):
        e = self.e
        o = a[0]
        v = [int(x, 0) for x in a[1:]]
        call = e.call
        if o == "fw":
            self.put(self.feds[v[0] != 0] + v[1], v[2], v[3])
        elif o == "rw":
            self.put(RP + v[0], v[1], v[2])
        elif o == "pl":
            p = self.players[v[0]]
            e.put32(p + 16, v[1])
            e.put32(p + 80, v[2])
            e.put32(p + 1524, v[3])
            e.put32(p + 2540, v[4])
            e.put32(p + 4, self.at(v[5], self.cars))
        elif o == "ps":
            e.mem[self.players[v[0]] + 32 + v[1]] = v[2] & 0xff
        elif o == "players":
            e.put32(P_NUM_PLAYERS, v[0])
            e.put32(P_BY_NUMBER, self.at(v[1], self.players))
            e.put32(P_BY_NUMBER + 4, self.at(v[2], self.players))
            e.put32(P_BY_INDEX, self.at(v[3], self.players))
            e.put32(P_BY_INDEX + 4, self.at(v[4], self.players))
        elif o == "car":
            c = self.cars[v[0]]
            self.put(c + 10, 2, v[1])
            e.put32(c + 12, self.at(v[2], self.ctis))
            e.put32(c + 24, self.at(v[3], self.players))
            e.put32(c + 28, self.at(v[4], self.rcs))
        elif o == "cti":
            e.put32(self.ctis[v[0]] + 800, v[1])
        elif o == "rc":
            r = self.rcs[v[0]]
            e.put32(r, self.at(v[1], self.cars))
            self.put(r + 10, 1, v[2])
            self.put(r + 12, 1, v[3])
            self.put(r + 9, 1, v[4])
            self.put(r + 16, 2, v[5])
            self.put(r + 18, 2, v[6])
            e.put32(r + 180, v[7])
            e.put32(r + 184, v[8])
            e.put32(r + 188, v[9])
        elif o == "rclap":
            e.put32(self.rcs[v[0]] + 136 + 4 * v[1], v[2])
        elif o == "rcbest":
            e.put32(self.rcs[v[0]] + 96 + 4 * v[1], v[2])
        elif o == "race":
            r = self.races[v[0]]
            e.put32(r + 24, v[1])
            self.put(r + 1619, 1, v[2])
            for i in range(8):
                e.put32(r + 1572 + 4 * i, self.at(v[3 + i], self.rcs))
        elif o == "cur":
            e.put32(P_CUR_RACE, self.races[v[0]])
        elif o == "cop":
            e.put32(P_COP, self.cop if v[0] else 0)
            e.put32(self.cop + 10480, v[1])
        elif o == "seed":
            e.put32(P_SEED, v[0])
        elif o == "ans":
            self.ans = v[:5]
        elif o == "task":
            e.put32(self.task + 4, v[0])
            for k in range(7):
                e.put32(self.task + 8 + 4 * k, v[1 + k])
        elif o == "tse":
            call(F_TSE, self.feds[v[0]] + F_ROWS + ROW * v[1],
                 self.at(v[2], self.rcs))
        elif o == "ts":
            call(F_TS, self.feds[v[0]] + F_STATS, self.races[0])
        elif o == "drv":
            p = call(F_DRIVER, self.feds[v[0]] + F_STATS, v[1]) & M32
            self.row(p, v[0])
        elif o == "opts":
            call(F_OPTS, self.feds[v[0]])
        elif o == "bonus":
            self.emit("  = %d" % call(F_BONUS, self.feds[v[0]],
                                      self.races[0],
                                      self.at(v[1], self.rcs)))
        elif o == "award":
            call(F_AWARD, self.feds[v[0]], self.races[0],
                 self.at(v[1], self.rcs))
        elif o == "abort":
            call(F_ABORT, self.feds[v[0]])
        elif o == "aborted":
            self.emit("  = %d" % call(F_ABORTED, self.feds[v[0]]))
        elif o == "leaving":
            call(F_LEAVING, self.feds[v[0]])
        elif o == "over":
            call(F_OVER, self.feds[v[0]], self.races[0])
        elif o == "quit":
            call(F_QUIT, self.feds[v[0]])
        elif o == "restarted":
            call(F_RESTARTED, self.feds[v[0]])
        elif o == "tcc":
            t = self.task if v[0] < 0 else NFS_TASKS + 56 * v[0]
            self.emit("  = %d" % call(F_TCC, t, self.at(v[1], self.rcs)))
        elif o == "tlist":
            e.put32(self.n, -7)
            r = call(F_TLIST, self.list, self.n, self.at(v[0], self.rcs))
            n = s32(e.u32(self.n))
            got = [(e.u32(self.list + 4 * k) - NFS_TASKS) // 56
                   for k in range(n)]
            self.emit("  = %d (%d):%s" % (r, n,
                                          "".join(" %d" % g for g in got)))
        elif o == "plist":
            e.put32(self.n, -7)
            r = call(F_PLIST, self.list, self.n, v[0])
            n = s32(e.u32(self.n))
            got = [(e.u32(self.list + 4 * k) - NFS_POINTS) // 12
                   for k in range(n)]
            self.emit("  = %d (%d):%s" % (r, n,
                                          "".join(" %d" % g for g in got)))
        elif o == "ctpr":
            call(F_CTPR, self.races[0])
        elif o == "tunl":
            self.emit("  = %d" % call(F_TUNL, v[0], v[1]))
        elif o == "punl":
            self.emit("  = %d" % call(F_PUNL, v[0]))
        elif o == "unl":
            self.emit("  = %d" % call(F_UNL, v[0], v[1]))
        else:
            self.emit("  ? %s" % o)

    def run(self, lines):
        e = self.e
        for line in lines:
            self.emit("> " + line)
            sp = e.reg[29]
            self.op(line.split("|"))
            e.reg[29] = sp
            self.dump()
        return self.out


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


# ================================================================= build

def build_harness(tmp, name="fredend_test"):
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


def encode(lines):
    return NL.join(lines) + NL


# ============================================================ the mutations


def M(name, before, after, rel=FE):
    return (name, rel, before, after)


MUTATIONS = [
    # TransientStatsElement::Construct.
    M("tse-pos", "e->FinishPosition = rc->RacePosition;",
      "e->FinishPosition = rc->FinishingOrder;"),
    M("tse-drv", "e->UniqueDriveNumber = rc->pCar->DriverNumber;",
      "e->UniqueDriveNumber = (uint16_t)rc->pCar->DriverNumber;"),
    M("tse-reason", "e->FinishReason = rc->FinishReason;",
      "e->FinishReason = (uint16_t)rc->FinishReason;"),
    M("tse-time", "e->RaceTime = rc->RaceTime;",
      "e->RaceTime = rc->LapTimes[1];"),
    M("tse-best", "e->BestLapTime = *racingcar_get_last_best_lap_time(rc);",
      "e->BestLapTime = rc->BestRunningTimes[0];"),
    M("tse-top", "e->TopSpeed = rc->TopSpeed;",
      "e->TopSpeed = rc->AverageSpeed;"),
    M("tse-avg", "e->AverageSpeed = rc->AverageSpeed;",
      "e->AverageSpeed = rc->TopSpeed;"),
    M("tse-ai", "    if (p == NULL) {" + NL + "        float r = bRandomF",
      "    if (p != NULL) {" + NL + "        float r = bRandomF"),
    M("tse-rand", "bRandomF(1.0f, &bDefaultSeed)",
      "bRandomF(2.0f, &bDefaultSeed)"),
    M("tse-cut", "#define AI_TOP_SPEED_CUT 0.05f",
      "#define AI_TOP_SPEED_CUT 0.5f"),
    M("tse-cut-form", "top = top - top * (r * AI_TOP_SPEED_CUT);",
      "top = top * (1.0f - r * AI_TOP_SPEED_CUT);"),
    M("tse-min-le", "e->TopSpeed = lim < top ? lim : top;",
      "e->TopSpeed = lim <= top ? lim : top;"),
    M("tse-max", "e->TopSpeed = lim < top ? lim : top;",
      "e->TopSpeed = lim > top ? lim : top;"),
    M("tse-no-limit", "e->TopSpeed = lim < top ? lim : top;",
      "(void)lim;"),
    M("tse-cop-time", "e->BeACopTime = 0.0f;" + NL + "    if (pCopManager",
      "e->BeACopTime = 1.0f;" + NL + "    if (pCopManager"),
    M("tse-tickets", "copmanager_get_num_tickets(pCopManager, rc->pCar);",
      "copmanager_get_num_tickets(pCopManager, rc->pCar) + 1;"),
    M("tse-no-tickets", "    } else" + NL + "        e->NumTickets = 0;",
      "    } else" + NL + "        e->NumTickets = -1;"),
    M("tse-beacop-num",
      "if (TheRaceParameters.BeACop && p != NULL && p->PlayerNumber == 0)",
      "if (TheRaceParameters.BeACop && p != NULL)"),
    M("tse-beacop",
      "if (TheRaceParameters.BeACop && p != NULL && p->PlayerNumber == 0)",
      "if (p != NULL && p->PlayerNumber == 0)"),
    M("tse-points", "e->PointsThisRace = p->TotalScore;",
      "e->PointsThisRace = p->TotalScore + 1;"),
    M("tse-total", "Fred.FrontendPlayers[p->PlayerNumber].AccumulatedPoints;",
      "Fred.FrontendPlayers[0].AccumulatedPoints;"),
    M("tse-mode", "e->HandlingMode = p->PlayerSettings.DrivingStyle;",
      "e->HandlingMode = p->PlayerSettings.TransmissionType;"),
    M("tse-ai-points", "e->PointsThisRace = 0;",
      "e->PointsThisRace = 1;"),
    M("tse-ai-mode", "e->HandlingMode = -1;", "e->HandlingMode = 0;"),
    M("tse-ai-total", "e->PointsTotal = 0;", "e->PointsTotal = 1;"),
    M("tse-ai-bonus", "e->FinishBonus = 0;", "e->FinishBonus = 2;"),
    M("tse-clear", "for (i = 0; i < 11; i++)", "for (i = 0; i < 10; i++)"),
    M("tse-num-laps", "e->NumLapTimes = rc->NumLapsCompleted;",
      "e->NumLapTimes = (uint8_t)rc->NumLapsCompleted;"),
    M("tse-lap-bound", "i <= e->NumLapTimes && i < 11",
      "i <= e->NumLapTimes && i < 10"),
    M("tse-lap-from", "for (i = 1; i <= e->NumLapTimes",
      "for (i = 0; i <= e->NumLapTimes"),
    M("tse-lap-lt", "i <= e->NumLapTimes && i < 11",
      "i < e->NumLapTimes && i < 11"),

    # TransientStats.
    M("ts-zero", "ts->NumStats = 0;", "ts->NumStats = 1;"),
    M("ts-loop", "for (i = 0; i < r->NumRacingCars; i++) {" + NL
      + "        transient_stats_element_construct",
      "for (i = 0; i < r->NumRacingCars - 1; i++) {" + NL
      + "        transient_stats_element_construct"),
    M("ts-row", "&ts->Stats[i], r->pRacingCars[i]",
      "&ts->Stats[i], r->pRacingCars[0]"),
    M("ts-count", "        ts->NumStats++;" + NL, ""),
    M("drv-loop", "for (i = 0; i < ts->NumStats; i++)",
      "for (i = 0; i < ts->NumStats - 1; i++)"),
    M("drv-row", "return &ts->Stats[i];", "return &ts->Stats[0];"),
    M("drv-none", "            return &ts->Stats[i];" + NL
      + "    return NULL;",
      "            return &ts->Stats[i];" + NL + "    return ts->Stats;"),

    # GetOptionsSetFromRace.
    M("opts-loop", "for (i = 0; i < PlayerNumPlayers; i++) {" + NL
      + "        struct Player *p = PlayerPlayersByIndex[i];" + NL + NL
      + "        f->",
      "for (i = 0; i < PlayerNumPlayers && i < 1; i++) {" + NL
      + "        struct Player *p = PlayerPlayersByIndex[i];" + NL + NL
      + "        f->"),
    M("opts-by", "        struct Player *p = PlayerPlayersByIndex[i];" + NL
      + NL + "        f->",
      "        struct Player *p = PlayerPlayersByNumber[i];" + NL
      + NL + "        f->"),
    M("opts-fpi", "f->FrontendPlayers[p->PlayerNumber].mPlayerSettings =",
      "f->FrontendPlayers[0].mPlayerSettings ="),
    M("opts-rp", "TheRaceParameters.PlayerSettings[p->PlayerNumber] = ",
      "TheRaceParameters.PlayerSettings[0] = "),
    M("opts-case", "    case 3:" + NL + "        f->SingleRaceSetupData",
      "    case 2:" + NL + "        f->SingleRaceSetupData"),
    M("opts-sr", "f->SingleRaceSetupData[6] =", "f->SingleRaceSetupData[5] ="),
    M("opts-rk", "f->RaceKnockoutSetupData[6] =",
      "f->RaceKnockoutSetupData[5] ="),
    M("opts-lk", "f->LapKnockoutSetupData[5] =",
      "f->LapKnockoutSetupData[4] ="),
    M("opts-fr", "f->FreeRunSetupData[2] =", "f->FreeRunSetupData[1] ="),
    M("opts-btc", "f->BeTheCopSetupData[4] =", "f->BeTheCopSetupData[3] ="),
    M("opts-fall", "f->RaceKnockoutSetupData[6] = "
      "TheRaceParameters.DamageEnabled;" + NL + "        break;",
      "f->RaceKnockoutSetupData[6] = TheRaceParameters.DamageEnabled;"),
    M("opts-display", "Fred.DisplayOptionsData = ",
      "f->DisplayOptionsData = "),
    M("opts-audio-arg", "gSetAudioDataFromSoundFn(f->AudioOptionsScreenData, 0);",
      "gSetAudioDataFromSoundFn(f->AudioOptionsScreenData, 1);"),
    M("opts-audio-fred",
      "gSetAudioDataFromSoundFn(f->AudioOptionsScreenData, 0);",
      "gSetAudioDataFromSoundFn(Fred.AudioOptionsScreenData, 0);"),

    # FigureOutBonusPoints.
    M("bonus-beacop", "    if (TheRaceParameters.BeACop)" + NL
      + "        return 0;",
      "    if (0)" + NL + "        return 0;"),
    M("bonus-num", "if (p == NULL || p->PlayerNumber != 0)",
      "if (p == NULL || p->PlayerNumber > 1)"),
    M("bonus-n1", "    if (n == 1)" + NL + "        earns = 0;",
      "    if (n == 1)" + NL + "        earns = 1;"),
    M("bonus-n2", "earns = place == 1;", "earns = place <= 1;"),
    M("bonus-n3", "earns = (uint32_t)(place - 1) <= 1;",
      "earns = place - 1 <= 1;"),
    M("bonus-n3-two", "earns = (uint32_t)(place - 1) <= 1;",
      "earns = (uint32_t)(place - 1) <= 2;"),
    M("bonus-more", "    else" + NL + "        earns = 1;",
      "    else" + NL + "        earns = place > 0;"),
    M("bonus-place", "place = rc->FinishingOrder;",
      "place = rc->RacePosition;"),
    M("bonus-n", "n = r->NumRacingCars;", "n = pCurrentRace->NumRacingCars;"),
    M("bonus-ret", "return player_get_finish_bonus(p, place);",
      "return player_get_finish_bonus(p, place + 1);"),

    # AwardPointsToPlayer.
    M("award-trunc", "cop = ee_trunc_w(t) * 100;",
      "cop = (int32_t)(t * 100.0f);"),
    M("award-ten", "cop = ee_trunc_w(t) * 100;", "cop = ee_trunc_w(t) * 10;"),
    M("award-beacop", "    if (TheRaceParameters.BeACop) {" + NL
      + "        float t = 0.0f;",
      "    if (1) {" + NL + "        float t = 0.0f;"),
    M("award-cop", "        if (pCopManager != NULL)" + NL
      + "            t = pCopManager->fBeACopTime;",
      "        if (0)" + NL + "            t = pCopManager->fBeACopTime;"),
    M("award-score", "fpi->AccumulatedPoints += p->TotalScore;",
      "fpi->AccumulatedPoints = p->TotalScore;"),
    M("award-no-cop", "fred_figure_out_bonus_points(f, r, rc) + cop;",
      "fred_figure_out_bonus_points(f, r, rc);"),
    M("award-fred", "fpi = &f->FrontendPlayers[p->PlayerNumber];",
      "fpi = &Fred.FrontendPlayers[p->PlayerNumber];"),
    M("award-first", "fpi = &f->FrontendPlayers[p->PlayerNumber];",
      "fpi = &f->FrontendPlayers[0];"),

    # Abortion, leaving, restarting.
    M("abort-clear", "f->bRaceWasAborted = 0;", "(void)0;"),
    M("abort-loop", "for (i = 0; i < 2; i++) {", "for (i = 0; i < 1; i++) {"),
    M("abort-by", "        struct Player *p = PlayerPlayersByIndex[i];" + NL
      + NL + "        if (p != NULL",
      "        struct Player *p = PlayerPlayersByNumber[i];" + NL
      + NL + "        if (p != NULL"),
    M("abort-time", "p->TimeFinishedRacing == 0",
      "(int32_t)p->TimeFinishedRacing <= 0"),
    M("abort-set", "f->bRaceWasAborted = 1;", "f->bRaceWasAborted = 2;"),
    M("aborted", "return f->bRaceWasAborted;",
      "return f->bRaceWasAborted != 0;"),
    M("leaving-test", "if (fred_use_the_race_event(f) && "
      "gRaceEventMaybeDiscardResultsFn != NULL)",
      "if (gRaceEventMaybeDiscardResultsFn != NULL)"),
    M("leaving-call", "        gRaceEventMaybeDiscardResultsFn();",
      "        gRaceEventCycleResultsFn();"),
    M("restarted-test", "if (fred_use_the_race_event(f) && "
      "gRaceEventCycleResultsFn != NULL)",
      "if (gRaceEventCycleResultsFn != NULL)"),

    # TheRaceIsOver.
    M("over-opts", "    fred_get_options_set_from_race(f);" + NL
      + "    for (i = 0;", "    for (i = 0;"),
    M("over-loop", "for (i = 0; i < r->NumRacingCars; i++) {" + NL
      + "        struct RacingCar *rc = r->pRacingCars[i];",
      "for (i = 0; i < r->NumRacingCars - 1; i++) {" + NL
      + "        struct RacingCar *rc = r->pRacingCars[i];"),
    M("over-gt", "if (Fred.GameType != GAME_TYPE_BE_A_COP) {",
      "if (f->GameType != GAME_TYPE_BE_A_COP) {"),
    M("over-gt-six", "if (Fred.GameType != GAME_TYPE_BE_A_COP) {",
      "if (Fred.GameType != 6) {"),
    M("over-p0", "            if (p->PlayerNumber == 0)" + NL
      + "                p0 = p;",
      "            if (p->PlayerNumber != 1)" + NL
      + "                p0 = p;"),
    M("over-p1", "                p1 = p;", "                p1 = p0;"),
    M("over-npc", "if (f->NumPlayerCars == 1)",
      "if (Fred.NumPlayerCars == 1)"),
    M("over-npc-ge", "if (f->NumPlayerCars == 1)",
      "if (f->NumPlayerCars >= 1)"),
    M("over-one", "if (p0 != NULL && p1 == NULL)", "if (p0 != NULL)"),
    M("over-only-p1", "maybe_record(f, r, race_get_racing_car(r, p1->MyCar));",
      "(void)0;"),
    M("over-cmp-le", "if (t0 < t1) {", "if (t0 <= t1) {"),
    M("over-cmp-unsigned", "if (t0 < t1) {",
      "if ((uint32_t)t0 < (uint32_t)t1) {"),
    M("over-order", "            maybe_record(f, r, rc0);" + NL
      + "            maybe_record(f, r, rc1);" + NL + "        } else",
      "            maybe_record(f, r, rc1);" + NL
      + "            maybe_record(f, r, rc0);" + NL + "        } else"),
    M("over-else-order", "            maybe_record(f, r, rc1);" + NL
      + "            maybe_record(f, r, rc0);" + NL + "        }" + NL
      + "    }",
      "            maybe_record(f, r, rc0);" + NL
      + "            maybe_record(f, r, rc1);" + NL + "        }" + NL
      + "    }"),
    M("over-ts", "transient_stats_construct(&f->TransientStatsTable, r);",
      "transient_stats_construct(&Fred.TransientStatsTable, r);"),
    M("over-post", "    if (fred_use_the_race_event(f) && "
      "gRaceEventPostResultsFn != NULL)",
      "    if (gRaceEventPostResultsFn != NULL)"),
    M("over-rewards", "    nfs_check_for_task_and_point_rewards(r);" + NL,
      ""),
    M("over-table", "gHighScoreMaybeRecordFn(&f->ChallengeHighScores, r, rc);",
      "gHighScoreMaybeRecordFn(&Fred.ChallengeHighScores, r, rc);"),
    M("over-race", "gHighScoreMaybeRecordFn(&f->ChallengeHighScores, r, rc);",
      "gHighScoreMaybeRecordFn(&f->ChallengeHighScores, pCurrentRace, rc);"),

    # TheRaceWasQuit.
    M("quit-abort", "    fred_check_for_abortion(f);" + NL, ""),
    M("quit-opts", "    fred_check_for_abortion(f);" + NL
      + "    fred_get_options_set_from_race(f);",
      "    fred_check_for_abortion(f);"),
    M("quit-event", "    if (!fred_use_the_race_event(f))" + NL
      + "        return;",
      "    if (0)" + NL + "        return;"),
    M("quit-allfin", "if (race_are_all_players_finished_racing(pCurrentRace))",
      "if (!race_are_all_players_finished_racing(pCurrentRace))"),
    M("quit-simulate", "        race_simulate_race_finish(pCurrentRace);" + NL,
      ""),
    M("quit-notify", "        race_notify_the_race_is_over(pCurrentRace);"
      + NL, ""),
    M("quit-order", "        race_simulate_race_finish(pCurrentRace);" + NL
      + "        race_notify_the_race_is_over(pCurrentRace);",
      "        race_notify_the_race_is_over(pCurrentRace);" + NL
      + "        race_simulate_race_finish(pCurrentRace);"),
    M("quit-post", "    if (gRaceEventPostResultsFn != NULL)" + NL
      + "        gRaceEventPostResultsFn();" + NL
      + "    if (gRaceEventKeepStateFn",
      "    if (gRaceEventKeepStateFn"),
    M("quit-keep", "        gRaceEventKeepStateFn();",
      "        gRaceEventCycleResultsFn();"),

    # NFSTaskParameters::CheckForCompletion.
    M("tcc-min", "if (t->MinDamage != -1.0f && ",
      "if (t->MinDamage > -1.0f && "),
    M("tcc-min-player", "(p == NULL || p->New2540 == 0)",
      "(p != NULL && p->New2540 == 0)"),
    M("tcc-new2540", "(p == NULL || p->New2540 == 0)",
      "(p == NULL || p->New2540 <= 0)"),
    M("tcc-np-any", "if (t->NumPlayers != -1 && rp->NumPlayerCars",
      "if (rp->NumPlayerCars"),
    M("tcc-np", "rp->NumPlayerCars != t->NumPlayers",
      "rp->NumPlayerCars > t->NumPlayers"),
    M("tcc-gt-any", "    if (t->GameType != -1) {", "    {"),
    M("tcc-gt", "if (gt != t->GameType)", "if (gt < t->GameType)"),
    M("tcc-gt4", "if (gt == 4 && Fred.NumPlayerCars == 1) {",
      "if (gt == 4) {"),
    M("tcc-gt4-npc", "if (gt == 4 && Fred.NumPlayerCars == 1) {",
      "if (gt == 4 && rp->NumPlayerCars == 1) {"),
    M("tcc-field", "if (rp->NumPlayerCars + rp->NumAICars >= 3)",
      "if (rp->NumPlayerCars + rp->NumAICars > 3)"),
    M("tcc-field-ai", "if (rp->NumPlayerCars + rp->NumAICars >= 3)",
      "if (rp->NumAICars >= 2)"),
    M("tcc-gt4-win", "            if (rc->FinishingOrder != 1)",
      "            if (rc->FinishingOrder > 1)"),
    M("tcc-gt5", "if (gt == 5 && rc->FinishingOrder != 1)",
      "if (gt == 5 && rc->FinishingOrder > 1)"),
    M("tcc-gt5-ge", "if (gt == 5 && rc->FinishingOrder != 1)",
      "if (gt >= 5 && rc->FinishingOrder != 1)"),
    M("tcc-opp-any", "if (t->NumOpponents != -1 && rp->NumAICars",
      "if (rp->NumAICars"),
    M("tcc-opp", "rp->NumAICars != t->NumOpponents",
      "rp->NumAICars < t->NumOpponents"),
    M("tcc-laps-any", "if (t->NumLaps != -1 && rp->NumLapsInRace",
      "if (rp->NumLapsInRace"),
    M("tcc-laps", "rp->NumLapsInRace != t->NumLaps",
      "rp->NumLapsInRace < t->NumLaps"),
    M("tcc-skill-any", "if (t->SkillLevel != -1 && rp->OpponentStrength",
      "if (rp->OpponentStrength"),
    M("tcc-skill", "rp->OpponentStrength != t->SkillLevel",
      "rp->OpponentStrength < t->SkillLevel"),
    M("tcc-led-any", "if (t->NumLapsToLead != -1 && led",
      "if (led"),
    M("tcc-led", "led != t->NumLapsToLead", "led < t->NumLapsToLead"),
    M("tcc-led-src", "int32_t led = rc->NumLapsLed;",
      "int32_t led = rc->NumLapsCompleted;"),
    M("tcc-cops-any", "if (t->Cops != -1 && cops", "if (cops"),
    M("tcc-cops", "cops != t->Cops", "cops < t->Cops"),
    M("tcc-cops-src", "int32_t cops = rp->nMaxCops > 0;",
      "int32_t cops = rp->nMaxCops >= 0;"),

    # The reward lists.
    M("tlist-state", "if (Fred.TaskRewardStates[t->IndexIntoFredTaskState] "
      "!= 0)", "if (Fred.TaskRewardStates[t->IndexIntoFredTaskState] > 0)"),
    M("tlist-n", "    *n = 0;" + NL + "    for (i = 0; i < NFS_NUM_TASKS",
      "    for (i = 0; i < NFS_NUM_TASKS"),
    M("tlist-loop", "for (i = 0; i < NFS_NUM_TASKS; i++) {" + NL
      + "        const NFSTaskParameters *t = &NFSTasks[i];" + NL + NL
      + "        if (!nfs_task",
      "for (i = 1; i < NFS_NUM_TASKS; i++) {" + NL
      + "        const NFSTaskParameters *t = &NFSTasks[i];" + NL + NL
      + "        if (!nfs_task"),
    M("tlist-ret", "    return *n;" + NL + "}" + NL + NL
      + "int32_t nfs_get_points_reward_list",
      "    return *n > 0;" + NL + "}" + NL + NL
      + "int32_t nfs_get_points_reward_list"),
    M("plist-state", "if (Fred.PointsRewardStates[pr->IndexIntoFred] != 0)",
      "if (Fred.PointsRewardStates[pr->IndexIntoFred] > 0)"),
    M("plist-loop", "for (i = 0; i < NFS_NUM_POINTS_REWARDS; i++) {" + NL
      + "        const NFSPointsRewards *pr = &NFSPointsRewardsArray[i];"
      + NL + NL + "        if (!nfs_points",
      "for (i = 0; i < NFS_NUM_POINTS_REWARDS - 1; i++) {" + NL
      + "        const NFSPointsRewards *pr = &NFSPointsRewardsArray[i];"
      + NL + NL + "        if (!nfs_points"),
    M("plist-cmp", "return !(points < p->RequiredPoints);",
      "return points > p->RequiredPoints;", rel=FH),

    # CheckForTaskAndPointRewards.
    M("ctpr-pword", "ts->PointsRewardEarned = -1;",
      "ts->PointsRewardEarned = 0;"),
    M("ctpr-tword", "ts->TaskRewardEarned = -1;",
      "ts->TaskRewardEarned = 0;"),
    M("ctpr-np", "if (!(PlayerNumPlayers < 2) ||",
      "if (!(PlayerNumPlayers == 1) ||"),
    M("ctpr-rc", "race_get_racing_car(r, PlayerPlayersByNumber[0]->MyCar);",
      "race_get_racing_car(r, PlayerPlayersByIndex[0]->MyCar);"),
    M("ctpr-gt", "if (Fred.GameType != 2) {", "if (Fred.GameType != 3) {"),
    M("ctpr-tstate", "Fred.TaskRewardStates[tasks[i]->IndexIntoFredTaskState]"
      " = 1;", "Fred.TaskRewardStates[tasks[i]->IndexIntoFredTaskState]"
      " = 2;"),
    M("ctpr-tnum", "ts->TaskRewardEarned = tasks[i]->TaskNumber;",
      "ts->TaskRewardEarned = tasks[i]->IndexIntoFredTaskState;"),
    M("ctpr-tfirst", "ts->TaskRewardEarned = tasks[i]->TaskNumber;",
      "if (i == 0)" + NL + "            ts->TaskRewardEarned = "
      "tasks[i]->TaskNumber;"),
    M("ctpr-pts", "Fred.FrontendPlayers[0].AccumulatedPoints);",
      "Fred.FrontendPlayers[1].AccumulatedPoints);"),
    M("ctpr-pstate", "Fred.PointsRewardStates[points[i]->IndexIntoFred] = 1;",
      "Fred.PointsRewardStates[points[i]->IndexIntoFred] = 2;"),
    M("ctpr-pnum", "ts->PointsRewardEarned = points[i]->IndexIntoFred;",
      "ts->PointsRewardEarned = points[i]->Reward;"),
    M("ctpr-pfirst", "ts->PointsRewardEarned = points[i]->IndexIntoFred;",
      "if (i == 0)" + NL + "            ts->PointsRewardEarned = "
      "points[i]->IndexIntoFred;"),

    # The unlocked tests.
    M("tunl-gt", "if (t->UnlockedInGameType != -1 && "
      "gameType != t->UnlockedInGameType)",
      "if (gameType != t->UnlockedInGameType)"),
    M("tunl-reward", "        if (t->Reward != carType)",
      "        if (t->Reward > carType)"),
    M("tunl-state", "return Fred.TaskRewardStates[t->IndexIntoFredTaskState]"
      " != 0;", "return Fred.TaskRewardStates[t->IndexIntoFredTaskState];"),
    M("tunl-none", "    return 0;" + NL + "}" + NL + NL
      + "int32_t nfs_points_rewards_is_car_unlocked",
      "    return 1;" + NL + "}" + NL + NL
      + "int32_t nfs_points_rewards_is_car_unlocked"),
    M("punl-state", "return Fred.PointsRewardStates[pr->IndexIntoFred] != 0;",
      "return Fred.PointsRewardStates[pr->IndexIntoFred];"),
    M("punl-reward", "        if (pr->Reward == carType)",
      "        if (pr->Reward >= carType)"),
    M("unl-task", "        return nfs_task_rewards_is_car_unlocked(carType, "
      "gameType);", "        return 1;"),
    M("unl-cop", "    if (gameType == GAME_TYPE_BE_A_COP)" + NL
      + "        return 0;",
      "    if (gameType == GAME_TYPE_BE_A_COP)" + NL + "        return 1;"),
    M("unl-cop-gt", "    if (gameType == GAME_TYPE_BE_A_COP)" + NL
      + "        return 0;",
      "    if (gameType == 8)" + NL + "        return 0;"),
    M("unl-ev", "gIsCarAnEventRewardFn != NULL && gIsCarAnEventRewardFn(carType)",
      "gIsCarAnEventRewardFn != NULL && !gIsCarAnEventRewardFn(carType)"),
    M("unl-ev-unlock", "? gEventTreeIsCarUnlockedFn(carType) : 0;",
      "? 1 : 0;"),
    M("unl-points", "        return nfs_points_rewards_is_car_unlocked(carType);"
      + NL + "    return 0;",
      "        return 1;" + NL + "    return 0;"),
    M("unl-end", "        return nfs_points_rewards_is_car_unlocked(carType);"
      + NL + "    return 0;",
      "        return nfs_points_rewards_is_car_unlocked(carType);" + NL
      + "    return 1;"),
]

EQUIVALENT = {
    "over-p0": "a player's number is 0 or 1 -- Player's constructor gives "
               "it, and both sides index Fred's two FrontendPlayers with "
               "it unchecked -- so != 1 is == 0",
}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name


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
        todo, SOURCES, "fredend_test",
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

    n = diff(lines, harness)
    print("%d ops, %d lines, %d differ" % (len(sc), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
