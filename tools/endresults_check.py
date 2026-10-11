#!/usr/bin/env python3
"""Cross-check 3DS Files/source/endresults.c, the results a finished race
shows, against the retail image, SLES_507.31.

**The model** is retail's own code run in retail_model.RetailEmu:
RaceResultsScreen's constructor, Scroll, Tick and destructor, with
everything under them -- ShowPointsResults, tSlideshowStats (its column
tests, constructor, SetupDataset, SetAlphaScale, Tick, ChangeStats and
destructor), the points tally's constructor, Start, Tick, line and
destructor, the bTList destructors, EventTournamentState's
GetPointsForFinishPos, TransientStats::GetDriver, FrontendDatabase's
UseTreeEvent and UseTheRaceEvent, SprintfAndHash with the real
bStringHash, CarTypeInfo::GetShortName and DriverInfo::GetName; the Points
Rewards and Task Rewards constructors and destructors, the car count
(0x001de4a0) and its counts, GetNumPointsRewardsEarned, the tasks'
lookups, GetCarTypeForPointsReward and FormatPoints; and 0x001dc500 with
Timer::PrintToString. bSPrintf and bVSPrintf format natively, so
FlailerPrintf runs and only FindFlailerObject and SetString under it are
stubbed.

**The stubs** print what they are asked, on both sides: the end game's
base constructor, AtRoot and the four tests the screens ask
(ShouldSeeTourney, ShouldSeeRewardMenu, the GameType 6 test and
0x001dc5d8, the track's name), the Flailer calls, RenderTextIntoGroup,
both GetTranslatedStrings, GetCarByNumber, GetCarByDriverNumber,
IsCarUnlocked, the race event's 0x00200b30, the two speeches, bMalloc and
bFree. The colours are what the static initialisers leave, as
tools/startrace_check.py runs them. The harness
(tools/src/endresults_test.c) runs endresults.c with nfsrewards.c,
timer.c and bprintf.c.

**The script** asks the counts, tasks and timer text over their ranges;
makes the reward screens over every reward, both speech flags and both
string modes; and makes Race Results for one and two players, every
column's test, knockouts, arrests, tournaments, both units, a tree
event's title, every bonus place and GameType 6, then ticks it through
the slideshow's and the tally's fades, scrolls it both ways round, and
takes it down with each flag; then random races.

    python tools/endresults_check.py
    python tools/endresults_check.py --mutate [--only a,b]
    python tools/endresults_check.py --dump out/endresults
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

HARNESS = "tools/src/endresults_test.c"
ER = "3DS Files/source/endresults.c"
SOURCES = [HARNESS, ER, "3DS Files/source/nfsrewards.c",
           "3DS Files/source/timer.c", "3DS Files/source/bprintf.c"]
HARNESS_TIMEOUT = 60

GP = retail_model.RETAIL_GP
FRED = 0x002fc050
FRED_SIZE = 0x10740
TS = FRED + 908
UNITS = FRED + 333
PRS = FRED + 0x106e0
GAME_TYPE = FRED + 0x1072c
NUM_PLAYER_CARS = FRED + 0x10734
RP = 0x0031a898
RACE_EVENT = 0x0031b600
LANGUAGE = 0x0031c1c8
REAL_TIMER = GP - 19608
CAR_TYPE_INFOS = GP - 20616
P_EGS = GP - 17628

F_RR, F_PR, F_TR = 0x001dffe8, 0x001de568, 0x001de6a8
F_COUNT, F_CLEAR = 0x001de4a0, 0x001de550
F_NRE = 0x0024b1b0
F_TASK_LANG, F_TASK_REWARD, F_TASK_GAME = 0x0024af40, 0x0024af78, \
    0x0024afb0
F_AVAIL, F_USAGE, F_COP_AVAIL, F_COP = 0x001de3a8, 0x0024b348, \
    0x0024b380, 0x0024b430
F_PTIMER = 0x001dc500

S_BASE = 0x001dd080
S_ATROOT, S_NOT6, S_TOURNEY, S_RMENU = 0x001dcee8, 0x001dcac0, 0x001dc990, \
    0x001dc758
S_TNAME = 0x001dc5d8
S_VIS, S_LANG, S_COLOR = 0x00144968, 0x001449a8, 0x001449e8
S_OPT, S_CLROPT, S_ALPHA = 0x00143ff0, 0x00144030, 0x001448e8
S_GVIS, S_GALPHA = 0x001454e8, 0x00145560
S_TOPX, S_TOPY = 0x00144140, 0x00144168
S_FIND, S_SETSTR = 0x00143d50, 0x00140e20
S_RENDER = 0x00144ba0
S_TR, S_TRS = 0x0021e560, 0x0021e508
S_CARNUM, S_CAR = 0x0014d508, 0x0014d5d0
S_UNL = 0x0024b208
S_EARNED = 0x00200b30
S_CARSPEECH, S_PTSPEECH = 0x00207488, 0x002075b0
S_SCREEN_CONFIG = 0x0016ad88
B_MALLOC, B_FREE = 0x002577c0, 0x00257850
NOT_TRANSLATED = 0x002bc958

VTABLES = {0x002b9058: "RR", 0x002b9118: "PR", 0x002b90e8: "TR",
           0x002b9148: "BASE"}
FORMATS = {0x4bcea: "E%dR", 0xe7ef0: "P[%s]", 0xe7ef1: "L[%s]",
           0xea7f4: "C%d/%d", 0xea7f5: "K%d/%d"}

MAX_TYPES = 64
TICKS = 4000                      # RealTimer's a second


def cx(v):
    """C's %#x: 0 has no 0x."""
    v &= M32
    return "%#x" % v if v else "0"


def fb(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def bf(u):
    return struct.unpack("<f", struct.pack("<I", u & M32))[0]


# ================================================================== script

def row(i, pos, unique, reason=0, rtime=0, lap=0, pts=0, total=0, bonus=0,
        tickets=0, top=0.0, avg=0.0):
    return "row|%d|%d|%d|%d|%d|%d|%d|%d|%d|%d|%#x|%#x" % (
        i, pos, unique, reason, rtime & M32, lap & M32, pts, total, bonus,
        tickets, fb(top), fb(avg))


def rp(rtype=0, p2p=0, laps=2, cops=0, new784=0):
    return "rp|%d|%d|%d|%d|%d" % (rtype, p2p, laps, cops, new784)


H_RR = 0x5ec0a11e
H_PR = 0x0e5a1234
H_TR = 0x7a5c0009


def grid8():
    """Eight drivers: 0 the player, 1 the second player, the rest AI, and
    cars 0..7 driven by them."""
    s = ["chr|0|Hunter", "chr|1|Mara", "chr|2|Rook", "chr|3|Vega",
         "chr|4|Dax", "chr|5|Lola", "chr|6|Kai", "chr|7|Nix",
         "drv|0|0|1|12|-1", "drv|1|1|1|33|-1", "drv|2|100|0|5|1",
         "drv|3|101|0|7|-1", "drv|4|102|2|40|2", "drv|5|103|0|63|3",
         "drv|6|104|0|0|4", "drv|7|105|0|21|5",
         "player|0|0|ANDREW", "player|1|1|SECOND"]
    for d in range(8):
        s.append("car|%d|%d" % (10 + d, d))
    return s + ["car|0|0", "car|1|1"]


def rows_plain(n, base=720000):
    """n rows in place order, each a second behind: the player's car 0
    first, then cars 11 on. A one-player race needs the player's row, as
    retail shows its list head as a tally line without it."""
    s = ["ts|%d|0|0" % n]
    for i in range(n):
        s.append(row(i, i + 1, 10 + i if i else 0, 0,
                     base + 4000 * i + 37 * i,
                     160000 + 900 * i, 1000 * (8 - i), 25000 + 7 * i,
                     0, i, 61.5 + i, 44.25 - i))
    return s


def full_tick_cycle(t0):
    """The slideshow's and the tally's fades from t0, through two cycles."""
    s = []
    for dt in (0, 10000, 20000, 20001, 21000, 21999, 22000, 22001, 23000,
               23999, 24000, 24001, 30000, 44000, 44001, 46000, 46001,
               47999, 48000):
        s += ["time|%d" % (t0 + dt), "tick"]
    s += ["dump"]
    return s


def script():
    s = ["lang|0", "time|1000", "game|2", "units|0", "np|1", rp(),
         "ev|3|0", "egs|1|0|0", "not6|1", "tourney|0", "rmenu|0", "trs|0"]

    # The timer's text.
    for lang in (0, 1, 2, 3, 4, 5):
        s += ["lang|%d" % lang]
        for v in (0, 0x7fffffff, 1, 39, 4000, 40001, 239999, 240000,
                  2400000, 14400000, 0x7ffffffe, -4000, -240000, 0x80000000):
            for fl in (0, 1, 2, 3):
                s += ["ptimer|%d|%d" % (v & M32, fl)]
    s += ["lang|0"]

    # GetNumPointsRewardsEarned, over Fred's states.
    s += ["nre"]
    for i in (0, 3, 17, 5, 9):
        s += ["prs|%d|1" % i, "nre"]
    for i in range(18):
        s += ["prs|%d|0" % i]
    s += ["nre"]
    for i in range(18):
        s += ["prs|%d|%d" % (i, i % 3), "nre"]

    # The tasks.
    for t in range(-2, 14):
        s += ["task|%d" % t]
    s += ["task|100", "task|-100"]

    # The counts: the usage types, the locks, the unlocked answers, the
    # race event's rewards.
    for i in range(MAX_TYPES):
        s += ["ct|%d|%d|%d|%d" % (i, (0, 1, 2, 0, 1, 3)[i % 6],
                                  (0, 1, 2, 1, 2)[i % 5],
                                  (0, 1, 2, 1, 2, 2, 1)[i % 7])]
    s += ["avail"]
    for i in range(0, MAX_TYPES, 5):
        s += ["unl|%d|-1|1" % i]
    for i in range(1, MAX_TYPES, 7):
        s += ["unl|%d|7|1" % i]
    s += ["avail", rp(new784=3), "avail"]
    s += ["ev|2|4", "rew|0|0|1", "rew|1|1|1", "rew|2|0|0", "rew|3|0|1"]
    for g in (2, 4, 8, 9, 10, 3):
        for rm in (0, 1):
            s += ["game|%d" % g, "rmenu|%d" % rm, "avail"]
    s += ["ev|2|-1", "game|4", "avail", "ev|2|0", "avail", "ev|2|4",
          "game|2", "rmenu|0"]
    for cop in (0, 1, 2, -1):
        s += ["count|%#x|%d" % (H_PR, cop)]
    s += ["clear|%#x" % H_PR, "miss|0xea7f4", "count|0x55|0",
          "count|0x55|1"]

    # The Points Rewards screen over every reward, the earned count at 18
    # and short of it, both speech flags.
    s += grid8()
    for i in range(18):
        s += ["prs|%d|1" % i]
    for r in range(18):
        for z0 in (0, 1):
            s += ["ts|0|%d|0" % r, "egs|1|%d|0" % z0, "pr|%#x" % H_PR,
                  "dump", "scroll|6", "tick", "render", "dtor|%d" % (r & 3)]
    s += ["trs|1", "ts|0|4|0", "egs|0|0|0", "pr|%#x" % H_PR, "dump",
          "dtor|1", "prs|17|0", "pr|%#x" % H_PR, "dtor|0", "prs|11|0",
          "prs|16|0", "pr|%#x" % H_PR, "dtor|1", "trs|0"]

    # The Task Rewards screen over every task.
    for t in list(range(-1, 13)) + [99]:
        for z1 in (0, 1):
            s += ["ts|0|0|%d" % t, "egs|1|0|%d" % z1, "tr|%#x" % H_TR,
                  "dump", "scroll|7", "tick", "dtor|%d" % (t & 3)]
    s += ["trs|1", "ts|0|0|3", "egs|0|1|0", "tr|%#x" % H_TR, "dtor|1",
          "trs|0"]

    # Race Results: one player, eight cars.
    s += ["egs|1|0|0", "np|1", "game|2", rp(0, 0, 3, 0)]
    s += rows_plain(8)
    s += ["rr|%#x" % H_RR, "dump"]
    s += full_tick_cycle(1000)
    for m in (6, 6, 7, 7, 7, 7, 7, 7, 7, 6, 8, 1, 18, 0):
        s += ["scroll|%d" % m, "dump"]
    s += ["time|200000", "tick", "dump", "dtor|1"]

    # Each column's test: tourney, cops, point to point, one lap.
    for tour, cops, p2p, laps in ((1, 0, 0, 3), (0, 2, 0, 3), (1, 1, 1, 3),
                                  (0, 0, 0, 1), (1, 3, 1, 1), (0, -1, 0, 0),
                                  (1, 0, 2, 5)):
        s += ["tourney|%d" % tour, rp(0, p2p, laps, cops), "rr|%#x" % H_RR,
              "dump", "scroll|7", "scroll|6", "scroll|6", "dtor|0"]
    s += ["tourney|0"]

    # Units, a knockout, arrests, places off the table.
    s += ["units|1", rp(3, 0, 2, 1), "tourney|1"]
    s += rows_plain(6)
    s += [row(2, 3, 12, 2, 800000, 0, 600, 600),
          row(4, 0, 14, 2, 0x7fffffff, 0x7fffffff, 0, 0),
          row(5, 9, 15, 1, 0, 0, 0, 0)]
    s += ["rr|%#x" % H_RR, "dump", "dtor|3", "units|-1", rp(0, 0, 2, 1),
          "rr|%#x" % H_RR, "dump"]
    for m in (7, 7, 7, 7, 7, 7):
        s += ["scroll|%d" % m]
    s += ["dtor|0", "units|0", "tourney|0"]
    # The winner arrested, unset times, a row slower than the winner.
    s += rows_plain(4)
    s += [row(0, 1, 0, 2, 900000), row(1, 2, 11, 0, 0x7fffffff, 0),
          row(2, 3, 12, 0, 0, 0x7fffffff), row(3, 4, 13, 0, 100)]
    s += ["rr|%#x" % H_RR, "dump", "dtor|1"]

    # The title: a tree event's number.
    for g, num in ((8, 3), (9, -2), (4, 7), (8, 300)):
        s += ["game|%d" % g, "ev|%d|0" % num, "rr|%#x" % H_RR, "dtor|1"]
    s += ["game|2", "miss|0x4bcea", "game|8", "rr|%#x" % H_RR, "dtor|1",
          "game|2"]

    # The tally: each bonus place, none, and the line's turns.
    s += rows_plain(8)
    for place, bonus in ((1, 500), (2, 300), (3, 100), (4, 50), (0, 25),
                         (-1, 10), (1, 0), (9, -5)):
        s += [row(0, place, 0, 0, 720000, 160000, 1500, 34567, bonus),
              "car|0|0", "rr|%#x" % H_RR, "dump"]
        s += full_tick_cycle(1000)
        s += ["dtor|1"]
    # The player's row elsewhere, with a total in the millions.
    s += [row(3, 4, 0, 0, 730000, 160000, 2500, 1234567, 75), "car|0|0"]
    s += ["rr|%#x" % H_RR, "dump", "time|50000", "tick", "dump", "dtor|1"]
    # The speech flag set before.
    s += ["egs|0|1|0", "rr|%#x" % H_RR, "dump", "dtor|1", "egs|1|0|0"]
    # GameType 6's, no panel.
    s += ["not6|0", "rr|%#x" % H_RR, "dump", "dtor|1", "not6|1"]

    # Two players: each one's row, either missing.
    s += ["np|2"] + rows_plain(5)
    s += [row(1, 2, 1, 0, 724000, 0, 800, 9000), "car|1|1"]
    s += ["rr|%#x" % H_RR, "dump", "dtor|1"]
    s += [row(1, 2, 11, 0, 724000), "rr|%#x" % H_RR, "dtor|1"]
    s += [row(0, 1, 10, 0, 720000), row(1, 2, 1, 0, 724000, 0, 800, 9000),
          "rr|%#x" % H_RR, "dtor|1"]
    s += [row(1, 2, 11, 0, 724000), "rr|%#x" % H_RR, "dump", "dtor|1"]
    for np in (0, 3, -1):
        s += ["np|%d" % np, "rr|%#x" % H_RR, "dump", "dtor|1"]
    s += ["np|1"] + rows_plain(8)
    s += [row(0, 1, 0, 0, 720000, 160000, 1500, 34567, 500), "car|0|0"]

    # Fewer rows: 1, then none but the player's.
    for n in (1, 2, 7):
        s += ["ts|%d|0|0" % n, "rr|%#x" % H_RR, "dump", "dtor|1"]
    s += ["ts|8|0|0", "trs|1", "lang|2", "rr|%#x" % H_RR, "dump",
          "dtor|1", "trs|0", "lang|0"]

    # The first tick past 5.5 seconds: Refresh as the constructor left it.
    s += ["time|5000", "rr|%#x" % H_RR, "time|27000", "tick", "dump",
          "time|28000", "tick", "dump", "time|29001", "tick", "dump",
          "scroll|7", "time|50000", "tick", "dump", "dtor|1"]
    # RealTimer wrapping.
    s += ["time|%d" % (0x7fffffff - 1000), "rr|%#x" % H_RR,
          "time|%d" % (-0x80000000 + 21000 - 1001), "tick", "dump",
          "time|%d" % (-0x80000000 + 22000 - 1001), "tick", "dump",
          "dtor|1"]

    s += random_races(random.Random(0xe0d5), 150)
    return s


def random_races(rnd, n):
    s = []
    for _ in range(n):
        nrows = rnd.randint(0, 8)
        np = rnd.choice((1, 1, 1, 2, 2, 0))
        s += ["game|%d" % rnd.choice((2, 3, 4, 6, 7, 8, 9)),
              "units|%d" % rnd.randint(0, 1),
              "np|%d" % np,
              rp(rnd.choice((0, 0, 3, 4)), rnd.randint(0, 1),
                 rnd.choice((0, 1, 2, 3)), rnd.choice((0, 0, 1, 4)),
                 rnd.randint(0, 2)),
              "ev|%d|%d" % (rnd.randint(0, 9), rnd.randint(0, 3)),
              "tourney|%d" % rnd.randint(0, 1),
              "not6|%d" % rnd.choice((1, 1, 0)),
              "egs|%d|%d|%d" % (rnd.randint(0, 1), rnd.choice((0, 0, 1)),
                                rnd.randint(0, 1)),
              "ts|%d|%d|%d" % (nrows, rnd.randint(0, 17),
                               rnd.randint(-1, 11)),
              "trs|%d" % rnd.randint(0, 1),
              "lang|%d" % rnd.randint(0, 5)]
        uniques = rnd.sample(range(10, 18), nrows)
        # The players' rows, so that GetDriver finds them; 0 always, when
        # a player has the tally.
        if nrows:
            uniques[rnd.randrange(nrows)] = 0
            if np == 2 and nrows > 1 and rnd.random() < 0.8:
                k = rnd.randrange(nrows)
                if uniques[k] != 0:
                    uniques[k] = 1
        elif np == 1:
            s += ["np|0"]
        places = list(range(1, nrows + 1))
        if rnd.random() < 0.3:
            rnd.shuffle(places)
        t = rnd.randint(200000, 900000)
        for i in range(nrows):
            reason = rnd.choice((0, 0, 0, 1, 2))
            rtime = rnd.choice((t + rnd.randint(0, 80000), t, 0,
                                0x7fffffff, t - rnd.randint(0, 4000)))
            lap = rnd.choice((rnd.randint(40000, 200000), 0, 0x7fffffff))
            s += [row(i, places[i], uniques[i], reason, rtime, lap,
                      rnd.randint(0, 3000), rnd.randint(0, 2000000),
                      rnd.choice((0, 0, 100, 300, 500)), rnd.randint(0, 6),
                      rnd.uniform(0, 120), rnd.uniform(0, 90))]
            if i == 0:
                t = rtime if rtime not in (0, 0x7fffffff) else t
            s += ["car|%d|%d" % (uniques[i], rnd.randint(0, 7))]
        s += ["car|0|0", "car|1|1"]
        t0 = rnd.randint(-0x80000000, 0x7fffffff - 200000)
        s += ["time|%d" % t0, "rr|%#x" % rnd.getrandbits(32), "dump"]
        for _ in range(rnd.randint(0, 6)):
            if rnd.random() < 0.3:
                s += ["scroll|%d" % rnd.choice((6, 7, 6, 7, 1, 18))]
            else:
                t0 += rnd.choice((1, 999, 4000, 20000, 20001, 21000, 22000,
                                  22001, 23000, 24000, 30000))
                if t0 > 0x7fffffff:
                    t0 -= 1 << 32
                s += ["time|%d" % t0, "tick"]
        s += ["dump", "dtor|%d" % rnd.randint(0, 3)]
        if rnd.random() < 0.15:
            s += ["pr|%#x" % H_PR, "dtor|1"]
        if rnd.random() < 0.15:
            s += ["tr|%#x" % H_TR, "dtor|1"]
    return s


# =================================================================== model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        e.stub_bware()
        e.stub(S_SCREEN_CONFIG, lambda em: em.reg[4] & M32)
        e.run_ctors(r"\$(pEndGameScreens|PRERACE_STATS)$")

        self.ctinfo = e.alloc(MAX_TYPES * 1376)
        self.specs = e.alloc(MAX_TYPES * 32)
        self.drivers = e.alloc(16 * 24)
        self.chars = e.alloc(8 * 48)
        self.cars = e.alloc(16 * 32)
        self.pcars = e.alloc(8 * 32)
        self.players = e.alloc(8 * 64)
        self.egs = e.alloc(72)
        self.fake = e.alloc(64)
        self.buf = e.alloc(64)
        for blk, n in ((self.ctinfo, MAX_TYPES * 1376),
                       (self.drivers, 16 * 24), (self.chars, 8 * 48),
                       (self.cars, 16 * 32), (self.pcars, 8 * 32),
                       (self.players, 8 * 64), (self.egs, 72)):
            e.write(blk, bytes(n))
        for i in range(MAX_TYPES):
            e.put32(self.ctinfo + i * 1376 + 1368, self.specs + i * 32)
            e.put32(self.specs + i * 32 + 20, 0x40000 + i)
        for i in range(8):
            e.put32(self.pcars + 32 * i + 24, self.players + 64 * i)
        e.put32(CAR_TYPE_INFOS, self.ctinfo)
        e.put32(P_EGS, self.egs)
        e.write(FRED, bytes(FRED_SIZE))
        e.write(RP, bytes(800))
        e.write(RACE_EVENT, bytes(400))
        e.put32(LANGUAGE, 0)
        e.put32(REAL_TIMER, 0)

        self.car_slots = {}
        self.player_unique = []
        self.unl = {}
        self.earned = {}
        self.at_root = self.not6 = self.tourney = self.rmenu = 0
        self.missing = set()
        self.trs_mode = 0
        self.strings = {}
        self.blocks = []
        self.screen = 0
        self.find = (0, 0)

        for a, fn in ((S_BASE, self.base), (S_ATROOT, self.ret("  atroot",
                                                                "at_root")),
                      (S_NOT6, self.ret("  not6", "not6")),
                      (S_TOURNEY, self.ret("  tourney", "tourney")),
                      (S_RMENU, self.ret("  rmenu", "rmenu")),
                      (S_TNAME, self.tname),
                      (S_VIS, self.say3("vis")), (S_LANG, self.lang),
                      (S_COLOR, self.color),
                      (S_OPT, self.say3("opt")),
                      (S_CLROPT, self.say3("clropt")),
                      (S_ALPHA, self.say3("alpha")),
                      (S_GVIS, self.say3("gvis")),
                      (S_GALPHA, self.say3("galpha")),
                      (S_TOPX, self.top("topx", 12.5)),
                      (S_TOPY, self.top("topy", -7.25)),
                      (S_FIND, self.find_obj), (S_SETSTR, self.set_string),
                      (S_RENDER, self.render),
                      (S_TR, self.tr), (S_TRS, self.trs),
                      (S_CARNUM, self.carnum), (S_CAR, self.car),
                      (S_UNL, self.unlocked), (S_EARNED, self.earned_stub),
                      (S_CARSPEECH, self.say1("carspeech")),
                      (S_PTSPEECH, self.say1("ptspeech")),
                      (B_MALLOC, self.malloc), (B_FREE, self.free)):
            e.stub(a, fn)

    def emit(self, s):
        self.out.append(s)

    def cstr(self, a, n=256):
        b = bytearray()
        mem = self.e.mem
        while len(b) < n and mem[a]:
            b.append(mem[a])
            a += 1
        return b.decode("latin-1")

    def string(self, s):
        """A NUL-terminated copy of s in emulated memory, made once."""
        a = self.strings.get(s)
        if a is None:
            raw = s.encode("latin-1") + b"\0"
            a = self.e.alloc(len(raw))
            self.e.write(a, raw)
            self.strings[s] = a
        return a

    def put_name(self, a, name, size):
        raw = name.encode("latin-1")[:size - 1]
        self.e.write(a, raw + bytes(size - len(raw)))

    def block_add(self, a):
        self.blocks.append(a)
        return len(self.blocks) - 1

    def ptr_name(self, p, head):
        if p == head:
            return "head"
        for i in range(len(self.blocks) - 1, -1, -1):
            if self.blocks[i] == p:
                return "#%d" % i
        return "%08x" % p

    # ---- the stubs

    def base(self, em):
        r = em.reg
        a = r[4] & M32
        self.emit("  base %08x" % (r[5] & M32))
        self.e.put32(a, r[5] & M32)
        self.e.put32(a + 4, 0x002b9148)
        return a

    def ret(self, line, attr):
        def stub(em):
            self.emit(line)
            return getattr(self, attr) & M32
        return stub

    def tname(self, em):
        r = em.reg
        self.emit("  tname %08x %08x %08x %d" % (r[4] & M32, r[5] & M32,
                                                 r[6] & M32, s32(r[7])))
        return 0

    def say3(self, word):
        def stub(em):
            r = em.reg
            self.emit("  %s %08x %08x %d" % (word, r[4] & M32, r[5] & M32,
                                             s32(r[6])))
            return 0
        return stub

    def say1(self, word):
        def stub(em):
            self.emit("  %s %d" % (word, s32(em.reg[4])))
            return 0
        return stub

    def lang(self, em):
        r = em.reg
        self.emit("  lang %08x %08x %s" % (r[4] & M32, r[5] & M32,
                                           cx(r[6])))
        return 0

    def color(self, em):
        r = em.reg
        a = r[6] & M32
        self.emit("  color %08x %08x %08x %08x %08x %08x" % (
            (r[4] & M32, r[5] & M32)
            + tuple(self.e.u32(a + 4 * i) for i in range(4))))
        return 0

    def top(self, word, v):
        def stub(em):
            r = em.reg
            self.emit("  %s %08x %08x" % (word, r[4] & M32, r[5] & M32))
            em.fpr[0] = fb(v)
            return 0
        return stub

    def find_obj(self, em):
        r = em.reg
        self.find = (r[4] & M32, r[5] & M32)
        return self.fake

    def set_string(self, em):
        text = self.cstr(em.reg[5] & M32, 4096)
        self.emit("  printf %08x %08x [%s]" % (self.find + (text[:127],)))
        return 0

    def render(self, em):
        r = em.reg
        self.emit("  render %08x %08x [%s]" % (r[4] & M32, r[5] & M32,
                                               self.cstr(r[6] & M32)))
        return 0

    def tr(self, em):
        i = s32(em.reg[4])
        self.emit("  tr %s" % cx(i))
        if (i & M32) in self.missing:
            return NOT_TRANSLATED
        if i in FORMATS:
            return self.string(FORMATS[i])
        return self.string("T%x" % (i & M32))

    def trs(self, em):
        a = em.reg[4] & M32
        t = self.cstr(a)
        self.emit("  trs %s" % t)
        if self.trs_mode == 0:
            return a
        return self.string("X" + t)

    def carnum(self, em):
        n = s32(em.reg[5])
        self.emit("  carnum %d" % n)
        k = self.car_slots.get(n)
        return 0 if k is None else self.cars + 32 * k

    def car(self, em):
        n = s32(em.reg[4])
        self.emit("  car %d" % n)
        if n in self.player_unique:
            return self.pcars + 32 * self.player_unique.index(n)
        return 0

    def unlocked(self, em):
        c, g = s32(em.reg[4]), s32(em.reg[5])
        self.emit("  unl %d %d" % (c, g))
        return self.unl.get((c, g), 0) & M32

    def earned_stub(self, em):
        i = s32(em.reg[5])
        self.emit("  earned %d %d" % (i, s32(em.reg[6])))
        return self.earned.get(i & 15, 0) & M32

    def malloc(self, em):
        r = em.reg
        size = s32(r[4])
        a = self.e.alloc(size)
        self.e.write(a, b"\xcd" * size)
        self.emit("  malloc %s %d %d %d #%d" % (
            self.cstr(r[5] & M32), size, s32(r[6]), s32(r[7]),
            self.block_add(a)))
        return a

    def free(self, em):
        self.emit("  free %s" % self.ptr_name(em.reg[4] & M32, None))
        return 0

    # ---- ops

    def dump(self):
        g = self.e.u32
        self.emit("  egs %d %d" % (s32(g(self.egs + 24)),
                                   s32(g(self.egs + 28))))
        o = self.screen
        if not o:
            self.emit("  screen none")
            return
        vt = VTABLES.get(g(o + 4), "?")
        self.emit("  screen %s %08x" % (vt, g(o)))
        if vt != "RR":
            return
        ss = o + 8
        self.emit("  ss %08x cur %s anim %d refresh %08x" % (
            g(ss), self.ptr_name(g(ss + 20), ss + 4), s32(g(ss + 12)),
            g(ss + 16)))
        n = g(ss + 4)
        while n != ss + 4:
            line = "  col %s %s" % (self.ptr_name(n, None), cx(g(n + 8)))
            for k in range(8):
                line += " %08x/%d" % (g(n + 12 + 8 * k),
                                      s32(g(n + 16 + 8 * k)))
            self.emit(line)
            n = g(n)
        p = o + 32
        self.emit("  pts %08x timer %d cur %s tl %08x %08x" % (
            g(p), s32(g(p + 4)), self.ptr_name(g(p + 16), p + 8),
            g(p + 20), g(p + 24)))
        n = g(p + 8)
        while n != p + 8:
            self.emit("  line %s %s %d" % (self.ptr_name(n, None),
                                           cx(g(n + 8)), s32(g(n + 12))))
            n = g(n)

    def new_screen(self, fn, size, h):
        e = self.e
        a = e.alloc(size)
        e.write(a, b"\xcd" * size)
        self.block_add(a)
        e.call(fn, a, h, limit=5000000)
        self.screen = a

    def vcall(self, slot, *args):
        e = self.e
        fn = e.u32(e.u32(self.screen + 4) + slot)
        e.call(fn, self.screen, *args, limit=5000000)

    def op(self, a):
        e = self.e
        o = a[0]
        if o == "chr":
            self.put_name(self.chars + 48 * int(a[1]) + 4, a[2], 32)
            return
        if o == "player":
            u = int(a[1], 0)
            if u not in self.player_unique:
                self.player_unique.append(u)
            k = self.player_unique.index(u)
            e.put32(self.players + 64 * k + 16, int(a[2], 0) & M32)
            self.put_name(self.players + 64 * k + 52, a[3], 12)
            return
        n = [0] + [int(x, 0) for x in a[1:]]
        if o == "lang":
            e.put32(LANGUAGE, n[1] & M32)
        elif o == "time":
            e.put32(REAL_TIMER, n[1] & M32)
        elif o == "game":
            e.put32(GAME_TYPE, n[1] & M32)
        elif o == "units":
            e.write(UNITS, struct.pack("<b", n[1]))
        elif o == "np":
            e.put32(NUM_PLAYER_CARS, n[1] & M32)
        elif o == "rp":
            for off, v in zip((32, 40, 44, 604, 784), n[1:6]):
                e.put32(RP + off, v & M32)
        elif o == "ev":
            e.write(RACE_EVENT + 104, struct.pack("<h", n[1]))
            e.write(RACE_EVENT + 114, struct.pack("<h", n[2]))
        elif o == "rew":
            e.write(RACE_EVENT + 244 + 8 * n[1], bytes([n[2] & 0xff]))
            self.earned[n[1]] = n[3]
        elif o == "ts":
            e.put32(TS, n[1] & M32)
            e.put32(TS + 4, n[2] & M32)
            e.put32(TS + 8, n[3] & M32)
        elif o == "row":
            r = TS + 12 + 100 * n[1]
            for off, v in zip((0, 4, 8, 12, 16, 20, 24, 28, 32, 40, 44),
                              n[2:13]):
                e.put32(r + off, v & M32)
        elif o == "drv":
            d = self.drivers + 24 * n[1]
            e.write(d + 1, struct.pack("<b", n[2]))
            e.put32(d + 8, n[3] & M32)
            e.put32(d + 12, n[4] & M32)
            e.put32(d + 20, 0 if n[5] < 0 else self.chars + 48 * n[5])
        elif o == "car":
            k = self.car_slots.get(n[1])
            if k is None:
                k = max(list(self.car_slots.values()) + [-1]) + 1
                self.car_slots[n[1]] = k
            if n[2] < 0:
                del self.car_slots[n[1]]
            else:
                e.put32(self.cars + 32 * k + 20, self.drivers + 24 * n[2])
        elif o == "ct":
            c = self.ctinfo + 1376 * n[1]
            e.put32(c + 1336, n[2] & M32)
            e.put32(c + 1340, n[3] & M32)
            e.put32(c + 1344, n[4] & M32)
        elif o == "unl":
            self.unl[(n[1], n[2])] = n[3]
        elif o == "prs":
            e.put32(PRS + 4 * n[1], n[2] & M32)
        elif o == "egs":
            self.at_root = n[1]
            e.put32(self.egs + 24, n[2] & M32)
            e.put32(self.egs + 28, n[3] & M32)
        elif o == "not6":
            self.not6 = n[1]
        elif o == "tourney":
            self.tourney = n[1]
        elif o == "rmenu":
            self.rmenu = n[1]
        elif o == "miss":
            self.missing.add(n[1] & M32)
        elif o == "trs":
            self.trs_mode = n[1]
        elif o == "rr":
            self.new_screen(F_RR, 60, n[1] & M32)
        elif o == "pr":
            self.new_screen(F_PR, 8, n[1] & M32)
        elif o == "tr":
            self.new_screen(F_TR, 8, n[1] & M32)
        elif o == "scroll":
            self.vcall(12, n[1] & M32, 0)
        elif o == "tick":
            self.vcall(28, 18, 0)
        elif o == "render":
            self.vcall(36, 19, 0)
        elif o == "dtor":
            self.vcall(44, n[1] & M32)
            self.dump()
            self.screen = 0
        elif o == "dump":
            self.dump()
        elif o == "count":
            e.call(F_COUNT, n[1] & M32, n[2] & M32, limit=5000000)
        elif o == "clear":
            e.call(F_CLEAR, n[1] & M32, limit=200000)
        elif o == "nre":
            self.emit("  nre %d" % s32(e.call(F_NRE)))
        elif o == "task":
            t = n[1] & M32
            self.emit("  task %s %d %d" % (
                cx(e.call(F_TASK_LANG, t)), s32(e.call(F_TASK_REWARD, t)),
                s32(e.call(F_TASK_GAME, t))))
        elif o == "avail":
            vals = [e.call(F_AVAIL, limit=5000000),
                    e.call(F_USAGE, 0, limit=200000),
                    e.call(F_USAGE, 1, limit=200000),
                    e.call(F_COP_AVAIL, limit=5000000),
                    e.call(F_COP, limit=200000)]
            self.emit("  avail %d %d %d %d %d" % tuple(s32(v) for v in vals))
        elif o == "ptimer":
            e.call(F_PTIMER, self.buf, n[1] & M32, n[2] & M32,
                   limit=2000000)
            self.emit("  ptimer [%s]" % self.cstr(self.buf))
        else:
            raise ValueError(o)

    def run(self, lines):
        e = self.e
        for line in lines:
            self.emit("> " + line)
            sp = e.reg[29]
            self.op(line.split("|"))
            e.reg[29] = sp
        return self.out


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


# ================================================================= build

def build_harness(tmp, name="endresults_test"):
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


def M(name, before, after, rel=ER):
    return (name, rel, before, after)


MUTATIONS = [
    # The seams' fallbacks and the helpers.
    M("tr-null", 'return s != NULL ? s : "NOT TRANSLATED PROPERLY";',
      'return s != NULL ? s : "NOT TRANSLATED";'),
    M("trs-null", "return t != NULL ? t : s;", 'return t != NULL ? t : "";'),
    M("name-null", '        return "";\n    return d->pCharacterInfo',
      '        return "?";\n    return d->pCharacterInfo'),
    M("hash-n", "    snprintf(buf, sizeof buf, fmt, (int)n);",
      "    snprintf(buf, sizeof buf, fmt, (int)n + 1);"),
    M("ticks", "#define TICKS_TO_SECONDS 0.00025f",
      "#define TICKS_TO_SECONDS 0.000251f"),
    M("ticks-wrap",
      "(float)(int32_t)((uint32_t)RealTimer - (uint32_t)stamp)",
      "(float)((int64_t)RealTimer - (int64_t)stamp)"),
    M("free-order", "        bNode *n = list->next;",
      "        bNode *n = list->prev;"),
    M("timer-lang", "timer_print_to_string(&t, buf, flags, language());",
      "timer_print_to_string(&t, buf, flags, 0);"),

    # The counts.
    M("nre-count", "            n++;\n    return n;\n}\n\nstatic const",
      "            n = i + 1;\n    return n;\n}\n\nstatic const"),
    M("nre-state", "            != 0)\n            n++;",
      "            == 1)\n            n++;"),
    M("task-num", "if (NFSTasks[i].TaskNumber == task)",
      "if (NFSTasks[i].TaskNumber == task + 1)"),
    M("task-lang-none", "t->EndOfRaceUnlocked : 0;",
      "t->EndOfRaceUnlocked : -1;"),
    M("task-reward-none", "t->Reward : -1;", "t->Reward : 0;"),
    M("task-game-none", "t->UnlockedInGameType : -1;",
      "t->UnlockedInGameType : 0;"),
    M("usage-skip", "        if (ct->UsageType != usage)\n            continue;",
      "        if (ct->UsageType == usage)\n            continue;"),
    M("usage-game", "if (is_car_unlocked(i, -1))",
      "if (is_car_unlocked(i, 0))"),
    M("usage-lock",
      "        else if (lock == 0)\n            n++;\n    }\n    return n;\n}\n\n"
      "int32_t end_reward_num_available_cars",
      "        else if (lock != 1)\n            n++;\n    }\n    return n;\n}\n\n"
      "int32_t end_reward_num_available_cars"),
    M("usage-order",
      "        if (is_car_unlocked(i, -1))\n            n++;\n"
      "        else if (lock == 0)",
      "        if (lock == 0)\n            n++;\n"
      "        else if (is_car_unlocked(i, -1))"),
    M("avail-new784", "int32_t n = TheRaceParameters.New784;",
      "int32_t n = 0;"),
    M("avail-event",
      "    if (fred_use_the_race_event(&Fred))\n        for (i = 0;",
      "    if (fred_use_tree_event(&Fred))\n        for (i = 0;"),
    M("avail-type", "if (race_event_reward_type(i) == 0",
      "if (race_event_reward_type(i) != 0"),
    M("avail-order",
      "&& endgame_should_see_reward_menu()\n"
      "                && race_event_reward_earned(i))",
      "&& race_event_reward_earned(i)\n"
      "                && endgame_should_see_reward_menu())"),
    M("avail-sum", "return cars + cops + n;", "return cars + n;"),
    M("usage-count", "if (cartypeinfo_get(i)->UsageType == usage)",
      "if (cartypeinfo_get(i)->UsageType != usage)"),
    M("cop-usage", "if (ct->UsageType != 1)", "if (ct->UsageType != 0)"),
    M("cop-lock1", "if (lock == 1 && is_car_unlocked",
      "if (lock != 0 && is_car_unlocked"),
    M("cop-game", "is_car_unlocked(i, GAME_TYPE_BE_THE_COP)",
      "is_car_unlocked(i, -1)"),
    M("cop-lock0",
      "        else if (lock == 0)\n            n++;\n    }\n    return n;\n}\n\n"
      "int32_t end_reward_num_cop_cars(void)",
      "        else if (lock == 2)\n            n++;\n    }\n    return n;\n}\n\n"
      "int32_t end_reward_num_cop_cars(void)"),
    M("cop-cars", "return end_reward_num_cars_of_usage(1);",
      "return end_reward_num_cars_of_usage(0);"),
    M("count-of", "        of += end_reward_num_cars_of_usage(1);\n", ""),
    M("count-id", "        id = END_REWARD_LANG_COUNT;\n",
      "        id = END_REWARD_LANG_COUNT_COP;\n"),
    M("count-args", "get_translated_string(id), (int)have,\n"
      "               (int)of);",
      "get_translated_string(id), (int)of,\n"
      "               (int)have);"),
    M("count-cop-have", "have = end_reward_num_cop_cars_available();",
      "have = end_reward_num_cop_cars();"),
    M("clear-text", 'END_REWARD_GROUP_COUNT, "");',
      'END_REWARD_GROUP_COUNT, " ");'),

    # The reward screens.
    M("pr-vt", "    m->vt = &kPointsRewardsVTable;",
      "    m->vt = &kTaskRewardsVTable;"),
    M("pr-last",
      "if (nfs_get_num_points_rewards_earned() != NFS_NUM_POINTS_REWARDS)",
      "if (nfs_get_num_points_rewards_earned() != NFS_NUM_POINTS_REWARDS - 1)"),
    M("pr-name", "    b_snprintf(buf, sizeof buf, fmt,\n"
      "               get_translated_string_by_name(\n"
      "                   car_type_info_get_short_name(ct)));",
      "    b_snprintf(buf, sizeof buf, fmt,\n"
      "                   car_type_info_get_short_name(ct));"),
    M("pr-said", "if (POINTS_SPEECH_SAID(s) == 0)",
      "if (POINTS_SPEECH_SAID(s) != 0)"),
    M("pr-set", "        POINTS_SPEECH_SAID(s) = 1;\n    }\n    render",
      "        POINTS_SPEECH_SAID(s) = 2;\n    }\n    render"),
    M("pr-speech", "reward_car_speech(car);", "reward_car_speech(car + 1);"),
    M("pr-title", "END_REWARD_LANG_POINTS_TITLE);",
      "END_REWARD_LANG_TASK_TITLE);"),
    M("pr-count", "    end_reward_show_car_count(m->ScreenHash, 0);",
      "    end_reward_show_car_count(m->ScreenHash, 1);"),
    M("tr-vt", "    m->vt = &kTaskRewardsVTable;",
      "    m->vt = &kPointsRewardsVTable;"),
    M("tr-cop", "(task) == GAME_TYPE_BE_THE_COP;",
      "(task) != GAME_TYPE_BE_THE_COP;"),
    M("tr-blurb", 'b_snprintf(buf, sizeof buf, "%s", get_translated_string(id));',
      'b_snprintf(buf, 4, "%s", get_translated_string(id));'),
    M("tr-said", "if (TASK_SPEECH_SAID(s) == 0)",
      "if (TASK_SPEECH_SAID(s) != 0)"),
    M("tr-speech", "reward_car_speech(nfs_get_reward_for_task(task));",
      "reward_car_speech(task);"),
    M("tr-set", "        TASK_SPEECH_SAID(s) = 1;",
      "        TASK_SPEECH_SAID(s) = 2;"),
    M("tr-count", "end_reward_show_car_count(m->ScreenHash, cop);",
      "end_reward_show_car_count(m->ScreenHash, 0);"),

    # The slideshow's columns.
    M("pts-table", "    10, 6, 4, 3, 2, 1, 0, 0,", "    10, 6, 4, 3, 2, 1, 1, 0,"),
    M("pts-out", "    if (i < 0 || i >= RACE_RESULTS_ROWS)\n        return 0;",
      "    if (i < 0 || i >= RACE_RESULTS_ROWS)\n        return 1;"),
    M("pts-place", "get_points_for_finish_pos(ts->Stats[i].FinishPosition - 1);",
      "get_points_for_finish_pos(ts->Stats[i].FinishPosition);"),
    M("rows-clamp", "return n < RACE_RESULTS_ROWS ? n : RACE_RESULTS_ROWS;",
      "return n < 7 ? n : 7;"),
    M("ko-type", "TheRaceParameters.RaceType == RACE_TYPE_KNOCKOUT;",
      "TheRaceParameters.RaceType == 4;"),
    M("ko-first", "if (knockout && i != 0) {", "if (knockout) {"),
    M("ko-arrest", "if (knockout && i != 0) {",
      "if (knockout && i != 0 && e->FinishReason != 2) {"),
    M("arrest", "} else if (e->FinishReason == FINISH_REASON_ARRESTED) {",
      "} else if (e->FinishReason == 1) {"),
    M("winner-type", "            d->Type = STATS_DATA_TIMER;\n"
      "            d->Value.Time = e->RaceTime;",
      "            d->Type = STATS_DATA_TIMER_BEHIND;\n"
      "            d->Value.Time = e->RaceTime;"),
    M("gap", "e->RaceTime.PackedTime - winner;",
      "winner - e->RaceTime.PackedTime;"),
    M("winner-row", "uint32_t winner = ts->Stats[0].RaceTime.PackedTime;",
      "uint32_t winner = ts->Stats[1].RaceTime.PackedTime;"),
    M("tourney", "    if (endgame_should_see_tourney()) {",
      "    if (!endgame_should_see_tourney()) {"),
    M("cops-0", "if (rp->nMaxCops > 0) {", "if (rp->nMaxCops >= 0) {"),
    M("cops-1", "if (rp->nMaxCops > 0) {", "if (rp->nMaxCops > 1) {"),
    M("tickets", "c->Data[i].Value.Int = ts->Stats[i].NumTickets;",
      "c->Data[i].Value.Int = ts->Stats[i].FinishPosition;"),
    M("lap-p2p", "if (rp->Point2Point == 0 && rp->NumLapsInRace != 1) {",
      "if (rp->NumLapsInRace != 1) {"),
    M("lap-laps", "if (rp->Point2Point == 0 && rp->NumLapsInRace != 1) {",
      "if (rp->Point2Point == 0 && rp->NumLapsInRace > 1) {"),
    M("lap-type", "            c->Data[i].Type = STATS_DATA_TIMER;\n"
      "            c->Data[i].Value.Time = ts->Stats[i].BestLapTime;",
      "            c->Data[i].Type = STATS_DATA_TIMER_BEHIND;\n"
      "            c->Data[i].Value.Time = ts->Stats[i].BestLapTime;"),
    M("avg", "ts->Stats[i].AverageSpeed * speed_scale();",
      "ts->Stats[i].TopSpeed * speed_scale();"),
    M("units", "Units == 0 ? MPS_TO_MPH : MPS_TO_KPH;",
      "Units == 1 ? MPS_TO_KPH : MPS_TO_MPH;"),
    M("mph", "#define MPS_TO_MPH 2.237f", "#define MPS_TO_MPH 2.2369f"),
    M("kph", "#define MPS_TO_KPH 3.6f", "#define MPS_TO_KPH 3.59f"),
    M("ss-hash", "    s->ScreenHash = hash;\n    s->Columns.next",
      "    s->ScreenHash = hash + 1;\n    s->Columns.next"),
    M("ss-first", "s->CurrentColumn = (tStatsColumn *)s->Columns.next;",
      "s->CurrentColumn = (tStatsColumn *)s->Columns.prev;"),
    M("ss-clock", "    s->AnimTimer = RealTimer;\n"
      "    slideshow_stats_setup_dataset(s, s->CurrentColumn);",
      "    s->AnimTimer = RealTimer + 1;\n"
      "    slideshow_stats_setup_dataset(s, s->CurrentColumn);"),

    # The slideshow's dataset and fades.
    M("alpha-full", "ee_trunc_w(f * FULL_ALPHA)", "ee_trunc_w(f * 127.0f)"),
    M("alpha-rows", "    for (k = 1; k <= RACE_RESULTS_ROWS; k++) {\n"
      '        uint32_t h = sprintf_and_hash("BEHIND_%d", k);\n\n'
      "        flailer_set_alpha",
      "    for (k = 1; k < RACE_RESULTS_ROWS; k++) {\n"
      '        uint32_t h = sprintf_and_hash("BEHIND_%d", k);\n\n'
      "        flailer_set_alpha"),
    M("ds-int", 'flailer_printf(hash, h, "%d", (int)d->Value.Int);',
      'flailer_printf(hash, h, "%2d", (int)d->Value.Int);'),
    M("ds-float", '"%3.f", (double)d->Value.Float);',
      '"%4.f", (double)d->Value.Float);'),
    M("ds-lang-clr",
      "flailer_clear_text_format_option(hash, h, TEXT_RIGHT_ALIGN);",
      "flailer_set_text_format_option(hash, h, TEXT_RIGHT_ALIGN);"),
    M("ds-timer-valid", "if (timer_is_valid(&d->Value.Time)) {",
      "if (d->Value.Time.PackedTime != TIMER_UNSET) {"),
    M("ds-timer-flags", "end_game_print_timer(buf, d->Value.Time, 0);",
      "end_game_print_timer(buf, d->Value.Time, TIMER_PRINT_SIGN);"),
    M("ds-behind-unset", "if (d->Value.Time.PackedTime != TIMER_UNSET) {",
      "if (timer_is_valid(&d->Value.Time)) {"),
    M("ds-behind-flags",
      "end_game_print_timer(buf, d->Value.Time, TIMER_PRINT_MINUS);",
      "end_game_print_timer(buf, d->Value.Time, 0);"),
    M("ds-title", "RACE_RESULTS_OBJ_STAT_TITLE,", "RACE_RESULTS_OBJ_TITLE,"),
    M("ds-rows", "const tStatsDatum *d = &s->CurrentColumn->Data[k - 1];",
      "const tStatsDatum *d = &s->CurrentColumn->Data[k & 7];"),
    M("next-wrap", "    if (n == &s->Columns)\n        n = s->Columns.next;\n"
      "    return (tStatsColumn *)n;",
      "    if (n == &s->Columns)\n        n = s->Columns.prev;\n"
      "    return (tStatsColumn *)n;"),
    M("tick-show", "if (!(SHOW_SECONDS < t)) {", "if (t < SHOW_SECONDS) {"),
    M("show-sec", "#define SHOW_SECONDS  5.0f", "#define SHOW_SECONDS  4.9f"),
    M("swap-sec", "#define SWAP_SECONDS  5.5f", "#define SWAP_SECONDS  5.4f"),
    M("cycle-sec", "#define CYCLE_SECONDS 6.0f", "#define CYCLE_SECONDS 6.1f"),
    M("tick-out", "slideshow_stats_set_alpha_scale(s, 1.0f - (out + out));",
      "slideshow_stats_set_alpha_scale(s, 1.0f - out);"),
    M("tick-in", "slideshow_stats_set_alpha_scale(s, in + in);",
      "slideshow_stats_set_alpha_scale(s, in);"),
    M("tick-refresh", "            s->Refresh = 1;", "            s->Refresh = 0;"),
    M("tick-refresh-test", "        if (s->Refresh == 0) {", "        if (1) {"),
    M("tick-restart", "    } else {\n        s->AnimTimer = RealTimer;\n    }",
      "    } else {\n        s->AnimTimer = RealTimer - 1;\n    }"),
    M("tick-shown-refresh", "        s->Refresh = 0;\n"
      "        slideshow_stats_set_alpha_scale(s, 1.0f);",
      "        slideshow_stats_set_alpha_scale(s, 1.0f);"),
    M("left-wrap", "        n = n->prev;\n        if (n == &s->Columns)\n"
      "            n = n->prev;",
      "        n = n->prev;\n        if (n == &s->Columns)\n"
      "            n = n->next;"),
    M("change-refresh", "    slideshow_stats_setup_dataset(s, (tStatsColumn *)n);\n"
      "    s->Refresh = 0;",
      "    slideshow_stats_setup_dataset(s, (tStatsColumn *)n);\n"
      "    s->Refresh = 1;"),
    M("change-clock", "    s->Refresh = 0;\n    s->AnimTimer = RealTimer;\n}",
      "    s->Refresh = 0;\n}"),
    M("scroll-left", "        slideshow_stats_change_stats(&s->Stats, -1);",
      "        slideshow_stats_change_stats(&s->Stats, 1);"),
    M("scroll-msg", "if (msg == BMSG_MENUITEM_PAD_LEFT)",
      "if (msg == BMSG_MENUITEM_PAD_RIGHT)"),

    # The tally.
    M("pts-lang", "nfs_format_points(buf, (int)sizeof buf, points, language());",
      "nfs_format_points(buf, (int)sizeof buf, points, 0);"),
    M("tally-clock", "    p->Timer = RealTimer;\n    p->TopLeftX",
      "    p->Timer = 0;\n    p->TopLeftX"),
    M("tally-tl", "    p->TopLeftX = flailer_get_top_left_x(p->ScreenHash,\n"
      "                                         RACE_RESULTS_OBJ_POINTS_LABEL);",
      "    p->TopLeftX = flailer_get_top_left_x(p->ScreenHash,\n"
      "                                         RACE_RESULTS_OBJ_POINTS);"),
    M("line-label", "                            (uint32_t)p->Current->Label);",
      "                            (uint32_t)p->Current->Points);"),
    M("line-clock", "p->Current->Points);\n    p->Timer = RealTimer;",
      "p->Current->Points);"),
    M("tally-lines", "if (count_lines(p) < 2)", "if (count_lines(p) < 3)"),
    M("tally-swap", "    if (SWAP_SECONDS < t) {\n        bNode *n",
      "    if (CYCLE_SECONDS < t) {\n        bNode *n"),
    M("tally-wrap", "        if (n == &p->Lines)\n            n = p->Lines.next;",
      "        if (n == &p->Lines)\n            n = p->Lines.prev;"),
    M("tally-full", "ee_trunc_w(FULL_ALPHA));", "ee_trunc_w(127.0f));"),
    M("tally-out", "ee_trunc_w((1.0f - (out + out))",
      "ee_trunc_w((1.0f - out)"),
    M("bonus-1", "    case 1: return RR_LANG_1ST_BONUS;",
      "    case 1: return RR_LANG_2ND_BONUS;"),
    M("bonus-3", "    case 3: return RR_LANG_3RD_BONUS;",
      "    case 4: return RR_LANG_3RD_BONUS;"),
    M("bonus-none", "    return RR_LANG_NO_BONUS;", "    return 0;"),
    M("sp-6", "    if (!endgame_is_not_game_type_6()) {",
      "    if (endgame_is_not_game_type_6()) {"),
    M("sp-gvis", "        flailer_set_group_visibility(hash, RACE_RESULTS_GROUP_TALLY,\n"
      "                                     FLAILER_OBJECT_INVISIBLE);",
      "        flailer_set_group_visibility(hash, RACE_RESULTS_GROUP_TALLY,\n"
      "                                     FLAILER_OBJECT_VISIBLE);"),
    M("sp-flag", "    if (egs != NULL)\n        POINTS_SPEECH_SAID(egs) = 1;\n",
      ""),
    M("sp-np1", "    if (np == 1) {", "    if (np != 2) {"),
    M("sp-total", "print_points(hash, RACE_RESULTS_OBJ_TOTAL, r->PointsTotal);",
      "print_points(hash, RACE_RESULTS_OBJ_TOTAL, r->PointsThisRace);"),
    M("sp-bonus", "if (r->FinishBonus != 0)", "if (r->FinishBonus > 0)"),
    M("sp-sum", "r->FinishBonus + r->PointsThisRace);", "r->PointsThisRace);"),
    M("sp-np2", "    } else if (np == 2) {", "    } else if (np >= 2) {"),
    M("sp-r1", "transient_stats_get_driver(ts, 1);",
      "transient_stats_get_driver(ts, 0);"),
    M("sp-p2", "print_points(hash, RACE_RESULTS_OBJ_TOTAL, r1->PointsThisRace);",
      "print_points(hash, RACE_RESULTS_OBJ_TOTAL, r1->PointsTotal);"),
    M("sp-p1-vis", "RACE_RESULTS_OBJ_POINTS_LABEL,\n"
      "                                   FLAILER_OBJECT_VISIBLE);",
      "RACE_RESULTS_OBJ_POINTS_LABEL,\n"
      "                                   FLAILER_OBJECT_INVISIBLE);"),
    M("sp-p2-hide", "            flailer_set_visibility(hash, RACE_RESULTS_OBJ_TOTAL,\n"
      "                                   FLAILER_OBJECT_INVISIBLE);",
      "            flailer_set_visibility(hash, RACE_RESULTS_OBJ_TOTAL,\n"
      "                                   FLAILER_OBJECT_VISIBLE);"),

    # The screen.
    M("row-vis", "    flailer_set_visibility(hash, pos, FLAILER_OBJECT_VISIBLE);",
      "    flailer_set_visibility(hash, pos, FLAILER_OBJECT_INVISIBLE);"),
    M("row-pos", 'flailer_printf(hash, pos, "%2d", (int)row->FinishPosition);',
      'flailer_printf(hash, pos, "%d", (int)row->FinishPosition);'),
    M("row-colour", "color = &PlayerTextColors[p->PlayerNumber];",
      "color = &PlayerTextColors[0];"),
    M("row-player-name",
      'flailer_printf(hash, name, "%s", p->PlayerSettings.PlayerName);',
      'flailer_printf(hash, name, "%s", driver_info_get_name(d));'),
    M("row-behind-colour", "    flailer_set_object_color(hash, behind, color);\n",
      ""),
    M("row-align", "    flailer_set_text_format_option(hash, time, TEXT_RIGHT_ALIGN);\n}",
      "    flailer_set_text_format_option(hash, type, TEXT_RIGHT_ALIGN);\n}"),
    M("row-ct", "ct = cartypeinfo_get(d->CurrentRideInfo.Type);",
      "ct = cartypeinfo_get(d->CurrentRideInfo.Type + 1);"),
    M("hide-behind",
      "    flailer_set_visibility(hash, behind, FLAILER_OBJECT_INVISIBLE);\n",
      ""),
    M("rr-vt", "    s->Base.vt = &kRaceResultsVTable;\n", ""),
    M("rr-tname", "RACE_RESULTS_OBJ_RACE_NUMBER, 0);",
      "RACE_RESULTS_OBJ_RACE_NUMBER, 1);"),
    M("rr-title", "    if (fred_use_tree_event(&Fred))\n"
      "        flailer_printf(",
      "    if (fred_use_the_race_event(&Fred))\n"
      "        flailer_printf("),
    M("rr-number", "(int)TheRaceEvent.nNumber);",
      "(int)TheRaceEvent.nRewards);"),
    M("rr-row-k", "        show_row(s, &ts->Stats[i], i + 1);",
      "        show_row(s, &ts->Stats[i], i);"),
    M("rr-hide-from", "for (k = n + 1; k <= RACE_RESULTS_ROWS; k++)",
      "for (k = n + 2; k <= RACE_RESULTS_ROWS; k++)"),
    M("rr-hide-to", "for (k = n + 1; k <= RACE_RESULTS_ROWS; k++)",
      "for (k = n + 1; k < RACE_RESULTS_ROWS; k++)"),
    M("rr-prev", "egs == NULL || endgame_screens_at_root(egs)",
      "egs != NULL && !endgame_screens_at_root(egs)"),
    M("dtor-flags", "    points_results_destroy(&s->Points, 2);",
      "    points_results_destroy(&s->Points, 3);"),
    M("dtor-order", "    points_results_destroy(&s->Points, 2);\n"
      "    slideshow_stats_destroy(&s->Stats, 2);",
      "    slideshow_stats_destroy(&s->Stats, 2);\n"
      "    points_results_destroy(&s->Points, 2);"),
]

EQUIVALENT = {
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
        todo, SOURCES, "endresults_test",
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
