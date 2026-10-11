#!/usr/bin/env python3
"""Cross-check 3DS Files/source/endtimes.c and highscore.c -- the best times
and lap times a finished race shows, and the records it sets -- against the
retail image, SLES_507.31.

**The model** is retail's own code run in retail_model.RetailEmu:
HighScoreTable::MaybeRecordHighScore with RacingCar::GetPlayer and
GetBestLapTime under it, FrontendDatabase's InsertPlayerName,
LookupPlayerNameFromTable, GetBestLapTimesTable and GetBestTotalTimesTable,
WhichPlayerSetLapTimeRecord and WhichPlayerSetTotalTimeRecord, the
BestLapTimes and BestTotalTimes constructors and destructors (the end
game's base destructor under them), and LapTimesDisplay's constructor,
destructor, HandleEvent and the Lap Times screens' callback, with
TransientStats::GetDriver, SprintfAndHash with the real bStringHash and
CarTypeInfo::GetShortName. bSPrintf and bVSPrintf format natively, so
FlailerPrintf runs and only FindFlailerObject and SetString under it are
stubbed.

**The stubs** print what they are asked, on both sides: the end game's
base constructor, the Flailer calls, both GetTranslatedStrings,
GetTheRightTrackLanguageID, 0x001dc500 (endresults_check.py checks its
text), HighScoreTable's GetTotalTimesIndex and GetLapTimesIndex
(fredrace_check.py checks them), the two record speeches, bMalloc and
bFree. The colours are what the static initialisers leave, as
tools/endresults_check.py runs them. The harness
(tools/src/endtimes_test.c) runs endtimes.c and highscore.c with
bprintf.c.

**The script** fills and searches the name table; records times into
every place, ties, a short race, signed times, each finish line boundary
and a full name table, with the neighbouring records shown; makes both
best-times screens over valid and unset rows, each player's records and
the speech's tests; and runs the Lap Times screens' callback over the
players, the drivers and their laps; then random ones of each.

    python tools/endtimes_check.py
    python tools/endtimes_check.py --mutate [--only a,b]
    python tools/endtimes_check.py --dump out/endtimes
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

HARNESS = "tools/src/endtimes_test.c"
ET = "3DS Files/source/endtimes.c"
HS = "3DS Files/source/highscore.c"
SOURCES = [HARNESS, ET, HS, "3DS Files/source/bprintf.c"]
HARNESS_TIMEOUT = 60

GP = retail_model.RETAIL_GP
FRED = 0x002fc050
FRED_SIZE = 0x10740
TS = FRED + 908
TABLES = FRED + 1720
LAP_TABLE = TABLES + 57600
NAMES = FRED + 0x100b8
RP = 0x0031a898
P_RACE = GP - 22272
TRACK_INFO = GP - 21952
CAR_TYPE_INFOS = GP - 20616
NUM_PLAYERS = GP - 20920
PBI = GP - 20928
P_EGS = GP - 17628
P_LTD = GP - 17472

F_MAYBE, F_INSERT, F_LOOKUP = 0x00186af0, 0x00186a50, 0x00186a20
F_BLT, F_BTT = 0x001ddc10, 0x001ddfd0
F_LTCB = 0x001e10f0

S_BASE = 0x001dd080
S_VIS, S_LANG, S_COLOR = 0x00144968, 0x001449a8, 0x001449e8
S_OPT = 0x00143ff0
S_FIND, S_SETSTR = 0x00143d50, 0x00140e20
S_TR, S_TRS = 0x0021e560, 0x0021e508
S_TRACKID = 0x001dc580
S_PTIMER = 0x001dc500
S_TIDX, S_LIDX = 0x00186938, 0x001869d0
S_LAPSPEECH, S_TIMESPEECH = 0x00207298, 0x00207330
S_SCREEN_CONFIG = 0x0016ad88
B_MALLOC, B_FREE = 0x002577c0, 0x00257850

VTABLES = {0x002b8ff8: "BLT", 0x002b8fc8: "BTT", 0x002b9148: "BASE"}

MAX_TYPES = 64
NUM_CARS = 8
NUM_PLAYERS_MAX = 4
PSTRIDE = 2576
NO = 0x7fffffff
NUM_TOTAL, NUM_LAP = 7200, 800


def cx(v):
    """C's %#x: 0 has no 0x."""
    v &= M32
    return "%#x" % v if v else "0"


# ================================================================== script

H_BLT = 0xb1a70001
H_BTT = 0xb7700002
H_LT1 = 0xc4881cbd
H_LT2 = 0xc4881cde

ACTIVATE, UNACTIVATE, BACK = 11, 12, 17


def rc(i, car, done, rtime, best=(0, 0, 0, 0, 0)):
    return "rc|%d|%d|%d|%d|%s" % (i, car, done, rtime & M32,
                                  "|".join(str(b & M32) for b in best))


def row(i, pos, unique, nlaps, laps=()):
    laps = list(laps) + [0] * (11 - len(laps))
    return "row|%d|%d|%d|%d|%s" % (i, pos, unique, nlaps,
                                   "|".join(str(t & M32) for t in laps))


def clear_names():
    return ["name|%d" % i for i in range(128)]


def names_script():
    s = ["names|4", "look|0", "look|127", "look|128", "look|1000",
         "look|32767"]
    s += ["ins|ANDREW", "ins|ANDREW", "ins|MARA", "ins|andrew", "names|4",
          "look|0", "look|1", "look|2"]
    # Eleven letters fit; twelve are cut to eleven, and so never match.
    s += ["ins|ABCDEFGHIJK", "ins|ABCDEFGHIJK", "ins|ABCDEFGHIJKL",
          "ins|ABCDEFGHIJKL", "ins|ABCDEFGHIJKLMNOP", "names|9"]
    # An empty name takes the first empty slot and leaves it empty.
    s += ["ins|", "ins|", "ins|Z", "names|10"]
    # A hole before the match: the hole wins.
    s += ["name|1", "ins|ABCDEFGHIJK", "ins|MARA", "names|10"]
    # A hole in a name: the slot is cleared before the copy.
    s += ["name|3|ZYXWVUTSRQPO", "hole|3", "names|4", "ins|AB", "names|4",
          "name|3|ZYXWVUTSRQPO", "hole|3", "ins|ABCDEFGHIJKLMN", "names|4"]
    # A full table.
    s += clear_names()
    for i in range(128):
        s += ["name|%d|N%d" % (i, i)]
    s += ["ins|N0", "ins|N127", "ins|N64", "ins|NEW", "look|127",
          "look|64"]
    s += ["name|100", "ins|NEW", "ins|NEW", "ins|N101", "look|100"]
    s += clear_names()
    return s


def records_script():
    s = ["rp|7|0|3|1", "race|3|0", "tidx|450", "lidx|50",
         "fill|0|440|25|%d" % NO, "fill|1|40|25|%d" % NO,
         "hs|0|455|0x11111111|3|4", "hs|1|55|0x22222222|5|6",
         "hs|0|449|0x33333333|7|8", "hs|1|49|0x44444444|9|10"]
    for i in range(MAX_TYPES):
        s += ["ct|%d|%d|%d" % (i, i, i % 5)]
    s += ["player|0|0|ANDREW", "player|1|1|SECOND", "player|2|0|THIRD",
          "car|0|5|0", "car|1|12|1", "car|2|33|2", "car|3|40|-1"]
    look = ["tab|0|449|7", "tab|1|49|7", "names|4"]

    # Into an empty list, then each place, a tie and a time that beats
    # nothing.
    s += [rc(0, 0, 3, 720000, (160000, 1, 2, 3, 4)), "maybe|0"] + look
    for t, b in ((700000, 150000), (800000, 170000), (720000, 160000),
                 (650000, 140000), (900000, 190000), (710000, 155000),
                 (999999, 999999), (0x7ffffffe, 0x7ffffffe),
                 (NO, NO), (0x80000000, 0x80000000), (1, 1)):
        s += [rc(0, 0, 3, t, (b, 0, 0, 0, 0)), "maybe|0"] + look
    # The second player's car.
    s += [rc(1, 1, 3, 600000, (120000, 0, 0, 0, 0)), "maybe|1"] + look
    # One lap short: no total, but a lap.
    s += [rc(0, 0, 2, 100, (100, 0, 0, 0, 0)), "maybe|0"] + look
    s += [rc(0, 0, 4, 100, (100, 0, 0, 0, 0)), "maybe|0"]
    s += ["race|-1|0", rc(0, 0, -1, 99, (99, 0, 0, 0, 0)), "maybe|0"] + look
    # Each finish line boundary.
    for flb in range(5):
        s += ["race|3|%d" % flb, "fill|1|50|5|%d" % NO,
              rc(0, 0, 3, NO, (11 + flb, 22, 33, 44, 55)), "maybe|0",
              "tab|1|50|5"]
    s += ["race|3|0"]
    # An empty list of zeros: nothing beats 0.
    s += ["tidx|900", "lidx|100", "fill|0|900|5|0", "fill|1|100|5|0",
          rc(0, 0, 3, 5000, (500, 0, 0, 0, 0)), "maybe|0", "tab|0|900|5",
          "tab|1|100|5"]
    # Negative times.
    s += ["fill|0|900|5|%d" % 0xfffff000, rc(0, 0, 3, 0xffff0000,
                                              (0xfff00000, 0, 0, 0, 0)),
          "maybe|0", "tab|0|900|5", "tab|1|100|5"]
    # The tables' ends.
    s += ["tidx|7195", "lidx|795", "fill|0|7195|5|%d" % NO,
          "fill|1|795|5|%d" % NO, rc(0, 0, 3, 5000, (500, 0, 0, 0, 0))]
    for _ in range(6):
        s += ["maybe|0", "tab|0|7194|7", "tab|1|794|6"]
    s += ["tidx|0", "lidx|0", "fill|0|0|5|%d" % NO, "fill|1|0|5|%d" % NO,
          "maybe|0", "tab|0|0|6", "tab|1|0|6"]
    # A player with someone else's name, and a full name table.
    s += ["tidx|450", "lidx|50", "fill|0|450|5|%d" % NO,
          "fill|1|50|5|%d" % NO, rc(2, 2, 3, 300000, (90000, 0, 0, 0, 0)),
          "player|2|0|ANDREW", "maybe|2", "names|4"] + look
    for i in range(128):
        s += ["name|%d|F%d" % (i, i)]
    s += ["player|2|0|NOBODY", rc(2, 2, 3, 200000, (80000, 0, 0, 0, 0)),
          "maybe|2"] + look
    s += ["player|2|0|F77", rc(2, 2, 3, 100000, (70000, 0, 0, 0, 0)),
          "maybe|2"] + look
    s += clear_names() + ["player|2|0|THIRD"]
    # The car's class and the race's numbers reach the indexes.
    for cls_type, track, d, laps in ((12, 3, 1, 2), (40, 15, 0, 10),
                                     (33, 0, 2, 1), (5, 7, -1, 0)):
        s += ["car|0|%d|0" % cls_type, "rp|%d|%d|%d|1" % (track, d, laps),
              "maybe|0"]
    s += ["car|0|5|0", "rp|7|0|3|1"]
    return s


def best_screens_script():
    s = ["rp|7|1|3|1", "race|3|0", "tidx|450", "lidx|50", "ts|0",
         "egs|0|0", "first|0", "rc|0|0|3|0|0|0|0|0|0",
         "car|0|5|0", "car|1|12|1", "player|0|0|ANDREW",
         "player|1|1|SECOND", "player|2|2|THIRD", "pbi|0|-1|1",
         "name|0|ANDREW", "name|1|SECOND", "name|2|MARA", "name|3|ABCDEFGHIJKL"]
    table = [(700000, 0, 5), (710000, 2, 12), (0, 1, 33), (NO, 3, 40),
             (800000, 3, 63)]
    for k, (t, n, c) in enumerate(table):
        s += ["hs|0|%d|%d|%d|%d" % (450 + k, t, n, c),
              "hs|1|%d|%d|%d|%d" % (50 + k, t // 4, n, c)]
    s += ["ts|3", row(0, 2, 0, 3, (0, 1, 2, 3)), row(1, 1, 1, 3),
          row(2, 3, 100, 3)]
    # No records this race.
    for op in ("blt", "btt"):
        h = H_BLT if op == "blt" else H_BTT
        s += ["%s|%#x" % (op, h), "dump", "scroll|6", "scroll|7", "tick",
              "render", "dtor|1"]
    # Each place, each player.
    s += ["egs|0|0"]
    for place in range(5):
        for who in (0, 1):
            s += ["pbi|0|1|2", "recp|%d|%d|%d" % (who, 50 + place,
                                                  450 + place),
                  "recp|%d|-1|-1" % (1 - who), "egs|0|0",
                  "blt|%#x" % H_BLT, "dump", "dtor|%d" % (place & 3),
                  "btt|%#x" % H_BTT, "dump", "dtor|%d" % (who + 1)]
    # Both players' records; the first row is the speech's.
    s += ["recp|0|52|453", "recp|1|50|451", "egs|0|0", "blt|%#x" % H_BLT,
          "dtor|1", "btt|%#x" % H_BTT, "dtor|1"]
    # The flags set before.
    s += ["egs|1|0", "blt|%#x" % H_BLT, "dtor|1", "btt|%#x" % H_BTT,
          "dtor|1", "egs|0|1", "blt|%#x" % H_BLT, "dtor|1",
          "btt|%#x" % H_BTT, "dtor|1", "egs|5|-1", "blt|%#x" % H_BLT,
          "dtor|1", "btt|%#x" % H_BTT, "dtor|1"]
    # The finish place: 4 and over says nothing, and 9 caps it.
    s += ["recp|0|50|450", "recp|1|-1|-1"]
    for pos in (1, 3, 4, 5, 9, 12, 0, -3):
        s += [row(0, pos, 0, 3), "egs|0|0", "blt|%#x" % H_BLT, "dtor|1",
              "btt|%#x" % H_BTT, "dtor|1"]
    # The speech's row: driver 1 for player 1, else driver 0.
    s += [row(0, 1, 0, 3), "recp|0|-1|-1", "recp|1|51|451"]
    for rows in ((row(0, 1, 7, 3), row(1, 2, 1, 3)),
                 (row(0, 1, 0, 3), row(1, 2, 1, 3)),
                 (row(0, 2, 1, 3), row(1, 1, 0, 3))):
        s += list(rows) + ["egs|0|0", "blt|%#x" % H_BLT, "dtor|1",
                           "btt|%#x" % H_BTT, "dtor|1"]
    # Player 0's record with no row for driver 0: no speech.
    s += ["recp|0|50|450", "recp|1|-1|-1", "ts|3", row(0, 1, 5, 3),
          row(1, 2, 0, 3), "egs|0|0", "ts|1", "blt|%#x" % H_BLT,
          "dtor|1", "btt|%#x" % H_BTT, "dtor|1", "ts|3", row(0, 2, 0, 3),
          row(1, 1, 1, 3)]
    # PlayerNumber 2: the default colour, and the speech's row is driver
    # 0's while where it finished is driver 2's. Without driver 0 there
    # is no speech.
    s += ["pbi|2|1|2", "recp|2|51|452", "recp|0|-1|-1", "recp|1|-1|-1",
          "ts|3", row(2, 2, 2, 3)]
    for rows in ((row(0, 3, 0, 3),), (row(0, 3, 7, 3),)):
        s += list(rows) + ["egs|0|0", "blt|%#x" % H_BLT, "dtor|1",
                           "btt|%#x" % H_BTT, "dtor|1"]
    s += [row(0, 2, 0, 3), row(2, 3, 100, 3), "recp|2|-1|-1",
          "recp|0|50|450", "recp|1|51|451"]
    # One player looked at of two, and none.
    s += ["pbi|0|1|1",
          "recp|1|50|450", "blt|%#x" % H_BLT, "dtor|1", "btt|%#x" % H_BTT,
          "dtor|1", "pbi|0|1|0", "blt|%#x" % H_BLT, "dtor|1",
          "pbi|0|1|2"]
    # The class, the track and the direction reach the tables.
    for cls_type, track, d, laps in ((12, 3, 0, 2), (40, 15, 1, 10),
                                     (33, 0, 2, 1)):
        s += ["car|0|%d|0" % cls_type, "rp|%d|%d|%d|1" % (track, d, laps),
              "blt|%#x" % H_BLT, "dtor|0", "btt|%#x" % H_BTT, "dtor|0"]
    s += ["car|0|5|0", "rp|7|1|3|1"]
    return s


def lap_times_script():
    s = ["rp|7|0|3|1", "ts|0", "pbi|-1|-1|0",
         "player|0|0|ANDREW", "player|1|1|SECOND"]
    seq = ["ltcb|%d|%#x|5" % (ACTIVATE, H_LT1), "ltcb|18|0|5",
           "ltcb|%d|0|5" % BACK, "ltcb|6|0|-2",
           "ltcb|%d|0|5" % UNACTIVATE]
    # No player, then each.
    s += seq
    s += ["pbi|0|-1|1"] + seq
    s += ["pbi|-1|1|1"] + seq
    s += ["rp|7|0|3|2", "pbi|0|-1|2"] + seq
    s += ["pbi|0|1|2"] + seq
    s += ["rp|7|0|3|3"] + seq + ["rp|7|0|3|0"] + seq
    s += ["rp|7|0|3|1"]
    # The drivers' laps.
    lapsA = [0, 160000, 150000, 170000, 150000, 0, 0x7fffffff, 140001,
             0, 0, 0]
    lapsB = [0, 150000, 0, 0x80000000, 165000, 165000, 0, 0, 0, 1, 2]
    for np, rows in ((1, [row(0, 1, 0, 4, lapsA)]),
                     (2, [row(0, 1, 0, 4, lapsA), row(1, 2, 1, 9, lapsB)]),
                     (2, [row(0, 1, 7, 4, lapsA), row(1, 2, 1, 6, lapsB)]),
                     (2, [row(0, 1, 1, 11, lapsB), row(1, 2, 0, 2, lapsA)]),
                     (1, [row(0, 1, 0, 0, [0] * 11)]),
                     (1, [row(0, 1, 0, -1, lapsA)]),
                     (1, [row(0, 1, 0, 9, [0] + [NO] * 10)]),
                     (2, [row(0, 1, 0, 3, [0, 5, 5, 5]),
                          row(1, 1, 1, 12, [0, 7, 6, 6, 6])])):
        s += ["rp|7|0|3|%d" % np, "pbi|0|1|%d" % np,
              "ts|%d" % len(rows)] + rows + seq
    s += ["ts|0", "pbi|0|1|2"] + seq
    # UNACTIVATE with none up, and twice.
    s += ["ltcb|%d|0|1" % UNACTIVATE, "ltcb|%d|%#x|1" % (ACTIVATE, H_LT2),
          "ltcb|%d|0|1" % UNACTIVATE, "ltcb|%d|0|1" % UNACTIVATE]
    return s


def random_script(rnd, n):
    s = []
    names = ["ANDREW", "MARA", "ROOK", "VEGA", "DAX", "LOLA", "KAI", "NIX",
             "ABCDEFGHIJK", "ABCDEFGHIJKL"]
    for i in range(6):
        s += ["name|%d|%s" % (i, rnd.choice(names))]
    for _ in range(n):
        tidx = rnd.randrange(0, NUM_TOTAL - 5)
        lidx = rnd.randrange(0, NUM_LAP - 5)
        s += ["tidx|%d" % tidx, "lidx|%d" % lidx]
        for tb, at in ((0, tidx), (1, lidx)):
            for k in range(5):
                t = rnd.choice((NO, NO, 0, rnd.randint(1, 900000),
                                rnd.randint(1, 900000),
                                rnd.randint(-5, 5) & M32))
                s += ["hs|%d|%d|%d|%d|%d" % (tb, at + k, t,
                                             rnd.randint(0, 127),
                                             rnd.randrange(MAX_TYPES))]
        np = rnd.randint(1, 2)
        s += ["rp|%d|%d|%d|%d" % (rnd.randint(0, 20), rnd.randint(0, 1),
                                   rnd.randint(1, 10), np),
              "race|%d|%d" % (rnd.randint(1, 5), rnd.randint(0, 4)),
              "player|0|0|%s" % rnd.choice(names),
              "player|1|1|%s" % rnd.choice(names),
              "car|0|%d|0" % rnd.randrange(MAX_TYPES),
              "car|1|%d|1" % rnd.randrange(MAX_TYPES),
              "pbi|0|1|%d" % np, "first|0"]
        for c in range(np):
            best = [rnd.choice((NO, rnd.randint(1, 300000), 0))
                    for _ in range(5)]
            s += [rc(c, c, rnd.randint(0, 6),
                     rnd.choice((NO, rnd.randint(1, 900000), 0)), best),
                  "maybe|%d" % c, "tab|0|%d|5" % tidx, "tab|1|%d|5" % lidx]
        nrows = rnd.randint(0, 3)
        uniques = rnd.sample((0, 1, 5, 9), nrows)
        s += ["ts|%d" % nrows]
        for i in range(nrows):
            laps = [rnd.choice((0, NO, rnd.randint(1, 200000),
                                rnd.randint(1, 200000)))
                    for _ in range(11)]
            s += [row(i, rnd.randint(-1, 10), uniques[i],
                      rnd.randint(-1, 11), laps)]
        # A player with no row has no speech row either: retail reads
        # where they finished through GetDriver's NULL, and the port does
        # not, but neither says anything.
        s += ["egs|%d|%d" % (rnd.choice((0, 0, 1)), rnd.choice((0, 0, 1))),
              "blt|%#x" % rnd.getrandbits(32), "dtor|%d" % rnd.randint(0, 3),
              "btt|%#x" % rnd.getrandbits(32), "dtor|%d" % rnd.randint(0, 3),
              "rp|%d|%d|3|%d" % (rnd.randint(0, 20), rnd.randint(0, 1),
                                 rnd.randint(1, 2)),
              "pbi|%d|%d|%d" % (rnd.choice((0, 0, -1)), rnd.choice((1, 1, -1)),
                                np),
              "ltcb|%d|%#x|3" % (ACTIVATE, rnd.getrandbits(32)),
              "ltcb|%d|0|3" % rnd.choice((BACK, 18, 6)),
              "ltcb|%d|0|3" % UNACTIVATE]
    return s


def script():
    s = names_script() + records_script() + best_screens_script()
    s += lap_times_script()
    s += random_script(random.Random(0xe0d7), 120)
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
        self.cars = e.alloc(NUM_CARS * 64)
        self.rcs = e.alloc(NUM_CARS * 192)
        self.players = e.alloc(NUM_PLAYERS_MAX * PSTRIDE)
        self.race = e.alloc(1700)
        self.track = e.alloc(176)
        self.egs = e.alloc(72)
        self.fake = e.alloc(64)
        self.data = e.alloc(16)
        self.namebuf = e.alloc(32)
        for blk, n in ((self.ctinfo, MAX_TYPES * 1376),
                       (self.cars, NUM_CARS * 64), (self.rcs, NUM_CARS * 192),
                       (self.players, NUM_PLAYERS_MAX * PSTRIDE),
                       (self.race, 1700), (self.track, 176),
                       (self.egs, 72)):
            e.write(blk, bytes(n))
        for i in range(MAX_TYPES):
            e.put32(self.ctinfo + i * 1376 + 1368, self.specs + i * 32)
            e.put32(self.specs + i * 32 + 20, 0x40000 + i)
        e.put32(CAR_TYPE_INFOS, self.ctinfo)
        e.put32(P_EGS, self.egs)
        e.put32(P_RACE, self.race)
        e.put32(TRACK_INFO, self.track)
        e.put32(NUM_PLAYERS, 0)
        e.put32(PBI, 0)
        e.put32(PBI + 4, 0)
        e.put32(P_LTD, 0)
        e.write(FRED, bytes(FRED_SIZE))
        e.write(RP, bytes(800))

        self.tidx = self.lidx = 0
        self.blocks = []
        self.screen = 0
        self.find = (0, 0)

        for a, fn in ((S_BASE, self.base),
                      (S_VIS, self.say3("vis")), (S_LANG, self.lang),
                      (S_COLOR, self.color), (S_OPT, self.say3("opt")),
                      (S_FIND, self.find_obj), (S_SETSTR, self.set_string),
                      (S_TR, self.tr), (S_TRS, self.trs),
                      (S_TRACKID, self.trackid), (S_PTIMER, self.ptimer),
                      (S_TIDX, self.total_index), (S_LIDX, self.lap_index),
                      (S_LAPSPEECH, self.speech("lapspeech")),
                      (S_TIMESPEECH, self.speech("timespeech")),
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

    def block_add(self, a):
        self.blocks.append(a)
        return len(self.blocks) - 1

    def ptr_name(self, p):
        if p == 0:
            return "none"
        for i in range(len(self.blocks) - 1, -1, -1):
            if self.blocks[i] == p:
                return "#%d" % i
        return "%08x" % p

    def rec_name(self, p):
        if p == 0:
            return "none"
        d = p - TABLES
        if 0 <= d < 64000 and d % 8 == 0:
            d //= 8
            return "t%d" % d if d < NUM_TOTAL else "l%d" % (d - NUM_TOTAL)
        return "?"

    def row_name(self, p):
        if p == 0:
            return "none"
        return "r%d" % ((p - (TS + 12)) // 100)

    def player(self, i):
        return self.players + PSTRIDE * i

    # ---- the stubs

    def base(self, em):
        r = em.reg
        a = r[4] & M32
        self.emit("  base %08x" % (r[5] & M32))
        self.e.put32(a, r[5] & M32)
        self.e.put32(a + 4, 0x002b9148)
        return a

    def say3(self, word):
        def stub(em):
            r = em.reg
            self.emit("  %s %08x %08x %d" % (word, r[4] & M32, r[5] & M32,
                                             s32(r[6])))
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

    def find_obj(self, em):
        r = em.reg
        self.find = (r[4] & M32, r[5] & M32)
        return self.fake

    def set_string(self, em):
        text = self.cstr(em.reg[5] & M32, 4096)
        self.emit("  printf %08x %08x [%s]" % (self.find + (text[:127],)))
        return 0

    def tr(self, em):
        i = s32(em.reg[4])
        self.emit("  tr %s" % cx(i))
        a = self.e.alloc(32)
        raw = ("T%x" % (i & M32)).encode("latin-1") + b"\0"
        self.e.write(a, raw)
        return a

    def trs(self, em):
        a = em.reg[4] & M32
        self.emit("  trs %s" % self.cstr(a))
        return a

    def trackid(self, em):
        r = em.reg
        d = s32(r[5])
        self.emit("  trackid %s %d" % ("ti" if (r[4] & M32) == self.track
                                       else "?", d))
        return (0x4a000 + d) & M32

    def ptimer(self, em):
        r = em.reg
        t = r[5] & M32
        self.emit("  ptimer %08x %d" % (t, s32(r[6])))
        self.e.write(r[4] & M32, ("P%x" % t).encode("latin-1") + b"\0")
        return 0

    def total_index(self, em):
        r = em.reg
        self.emit("  tidx %d %d %d %d" % (s32(r[5]), s32(r[6]), s32(r[7]),
                                          s32(r[8])))
        return self.tidx & M32

    def lap_index(self, em):
        r = em.reg
        self.emit("  lidx %d %d %d" % (s32(r[5]), s32(r[6]), s32(r[7])))
        return self.lidx & M32

    def speech(self, word):
        def stub(em):
            r = em.reg
            self.emit("  %s %d %d %s" % (word, s32(r[4]), s32(r[5]),
                                         self.row_name(r[6] & M32)))
            return 0
        return stub

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
        self.emit("  free %s" % self.ptr_name(em.reg[4] & M32))
        return 0

    # ---- ops

    def dump(self):
        g = self.e.u32
        self.emit("  egs %d %d" % (s32(g(self.egs + 52)),
                                   s32(g(self.egs + 56))))
        o = self.screen
        if not o:
            self.emit("  screen none")
            return
        self.emit("  screen %s %08x" % (VTABLES.get(g(o + 4), "?"), g(o)))

    def dump_records(self):
        g = self.e.u32
        for i in range(NUM_PLAYERS_MAX):
            p = self.player(i)
            self.emit("  rec %d %s %s" % (i, self.rec_name(g(p + 2552)),
                                          self.rec_name(g(p + 2556))))

    def new_screen(self, fn, h):
        e = self.e
        a = e.alloc(8)
        e.write(a, b"\xcd" * 8)
        self.block_add(a)
        e.call(fn, a, h, limit=5000000)
        self.screen = a

    def vcall(self, slot, *args):
        e = self.e
        fn = e.u32(e.u32(self.screen + 4) + slot)
        e.call(fn, self.screen, *args, limit=5000000)

    def entry(self, tb, i):
        return (LAP_TABLE if tb else TABLES) + 8 * i

    def put_text(self, a, text, size):
        raw = text.encode("latin-1")[:size]
        self.e.write(a, raw + bytes(size - len(raw)))

    def op(self, a):
        e = self.e
        o = a[0]
        if o == "player":
            p = self.player(int(a[1], 0))
            e.put32(p + 16, int(a[2], 0) & M32)
            self.put_text(p + 52, a[3][:11] if len(a) > 3 else "", 12)
            return
        if o == "name":
            self.put_text(NAMES + 12 * int(a[1], 0),
                          a[2] if len(a) > 2 else "", 12)
            return
        if o == "hole":
            e.mem[NAMES + 12 * int(a[1], 0)] = 0
            return
        if o == "ins":
            self.put_text(self.namebuf, a[1][:31] if len(a) > 1 else "", 32)
            self.emit("  ins %d" % s32(e.call(F_INSERT, FRED, self.namebuf,
                                              limit=5000000)))
            return
        n = [0] + [int(x, 0) for x in a[1:]]
        if o == "rp":
            for off, v in zip((0, 12, 44, 48), n[1:5]):
                e.put32(RP + off, v & M32)
        elif o == "race":
            e.put32(self.race + 1604, n[1] & M32)
            e.write(self.race + 1619, struct.pack("<b", n[2]))
        elif o == "first":
            e.put32(self.race + 1572,
                    0 if n[1] < 0 else self.rcs + 192 * n[1])
        elif o == "ct":
            c = self.ctinfo + 1376 * n[1]
            e.put32(c + 1332, n[2] & M32)
            e.write(c + 230, struct.pack("<b", n[3]))
        elif o == "car":
            c = self.cars + 64 * n[1]
            e.put32(c + 12, self.ctinfo + 1376 * n[2])
            e.put32(c + 24, 0 if n[3] < 0 else self.player(n[3]))
        elif o == "rc":
            r = self.rcs + 192 * n[1]
            e.put32(r, 0 if n[2] < 0 else self.cars + 64 * n[2])
            e.write(r + 9, struct.pack("<b", n[3]))
            e.put32(r + 180, n[4] & M32)
            for k in range(5):
                e.put32(r + 96 + 4 * k, n[5 + k] & M32)
        elif o == "pbi":
            e.put32(PBI, 0 if n[1] < 0 else self.player(n[1]))
            e.put32(PBI + 4, 0 if n[2] < 0 else self.player(n[2]))
            e.put32(NUM_PLAYERS, n[3] & M32)
        elif o == "recp":
            p = self.player(n[1])
            e.put32(p + 2552, 0 if n[2] < 0 else self.entry(1, n[2]))
            e.put32(p + 2556, 0 if n[3] < 0 else self.entry(0, n[3]))
        elif o == "tidx":
            self.tidx = n[1]
        elif o == "lidx":
            self.lidx = n[1]
        elif o == "hs":
            a = self.entry(n[1], n[2])
            e.put32(a, n[3] & M32)
            e.write(a + 4, struct.pack("<hh", n[4], n[5]))
        elif o == "fill":
            for k in range(n[3]):
                a = self.entry(n[1], n[2] + k)
                e.put32(a, n[4] & M32)
                e.put32(a + 4, 0)
        elif o == "look":
            v = e.call(F_LOOKUP, FRED, n[1] & M32) & M32
            if v == 0:
                self.emit("  look none")
            else:
                self.emit("  look %d [%s]" % ((v - NAMES) // 12,
                                              self.cstr(v, 12)))
        elif o == "tab":
            base = LAP_TABLE if n[1] else TABLES
            for k in range(n[3]):
                a = base + 8 * (n[2] + k)
                ni, ct = struct.unpack("<hh", bytes(e.mem[a + 4:a + 8]))
                self.emit("  tab %d %d %08x %d %d" % (n[1], n[2] + k,
                                                      e.u32(a), ni, ct))
        elif o == "names":
            for i in range(n[1]):
                a = NAMES + 12 * i
                self.emit("  name %d %s" % (i, " ".join(
                    "%02x" % b for b in e.mem[a:a + 12])))
        elif o == "maybe":
            v = e.call(F_MAYBE, TABLES, self.race, self.rcs + 192 * n[1],
                       limit=5000000)
            self.emit("  maybe %d" % s32(v))
            self.dump_records()
        elif o == "ts":
            e.put32(TS, n[1] & M32)
        elif o == "row":
            r = TS + 12 + 100 * n[1]
            e.put32(r, n[2] & M32)
            e.put32(r + 4, n[3] & M32)
            e.put32(r + 96, n[4] & M32)
            for k in range(11):
                e.put32(r + 52 + 4 * k, n[5 + k] & M32)
        elif o == "egs":
            e.put32(self.egs + 52, n[1] & M32)
            e.put32(self.egs + 56, n[2] & M32)
        elif o == "blt":
            self.new_screen(F_BLT, n[1] & M32)
        elif o == "btt":
            self.new_screen(F_BTT, n[1] & M32)
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
        elif o == "ltcb":
            d = self.data
            e.put32(d, n[2] & M32)
            e.put32(d + 4, 0)
            e.put32(d + 8, 0)
            e.put32(d + 12, n[3] & M32)
            e.call(F_LTCB, n[1] & M32, d, limit=5000000)
            inst = e.u32(P_LTD)
            noise = s32(e.u32(d + 12))
            if inst == 0:
                self.emit("  ltd none noise %d" % noise)
            else:
                self.emit("  ltd %s %08x noise %d" % (
                    self.ptr_name(inst), e.u32(inst), noise))
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

def build_harness(tmp, name="endtimes_test"):
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


def M(name, before, after, rel=ET):
    return (name, rel, before, after)


MUTATIONS = [
    # The names.
    M("look-hi", "if (i < 0 || i >= HIGH_SCORE_NUM_NAMES)",
      "if (i < 0 || i > HIGH_SCORE_NUM_NAMES)", HS),
    M("look-size", "return (const char *)&f->HighScoreNameTable["
      "HIGH_SCORE_NAME_SIZE * i];",
      "return (const char *)&f->HighScoreNameTable["
      "HIGH_SCORE_NAME_SIZE * i + 1];", HS),
    M("ins-empty", "if (slot[0] == 0) {", "if (slot[1] == 0) {", HS),
    M("ins-memset", "            memset(slot, 0, HIGH_SCORE_NAME_SIZE);\n", "",
      HS),
    M("ins-11", "memcpy(slot, name, HIGH_SCORE_NAME_SIZE - 1);",
      "memcpy(slot, name, HIGH_SCORE_NAME_SIZE);", HS),
    M("ins-match", "if (strcmp(name, (const char *)slot) == 0)",
      "if (strncmp(name, (const char *)slot, 4) == 0)", HS),
    M("ins-full", "    }\n    return -1;\n}\n\n// ------------------------------"
      "------------------------------- the tables",
      "    }\n    return 0;\n}\n\n// ------------------------------"
      "------------------------------- the tables", HS),

    # The records.
    M("total-range", "return i >= 0 && i <= FRED_NUM_TOTAL_TIMES",
      "return i >= 0 && i < FRED_NUM_TOTAL_TIMES", HS),
    M("lap-range", "return i >= 0 && i <= FRED_NUM_LAP_TIMES",
      "return i >= 0 && i < FRED_NUM_LAP_TIMES", HS),
    M("place-signed",
      "if ((int32_t)time.PackedTime < (int32_t)e[i].Time.PackedTime)",
      "if (time.PackedTime < e[i].Time.PackedTime)", HS),
    M("place-strict",
      "if ((int32_t)time.PackedTime < (int32_t)e[i].Time.PackedTime)",
      "if ((int32_t)time.PackedTime <= (int32_t)e[i].Time.PackedTime)", HS),
    M("place-count", "    for (i = 0; i < HIGH_SCORE_RECORDS; i++)\n"
      "        if ((int32_t)",
      "    for (i = 0; i < HIGH_SCORE_RECORDS - 1; i++)\n"
      "        if ((int32_t)", HS),
    M("room-count", "(size_t)(HIGH_SCORE_RECORDS - 1 - k)",
      "(size_t)(HIGH_SCORE_RECORDS - 1)", HS),
    M("room-none", "    memmove(&e[k + 1], &e[k],",
      "    if (0) memmove(&e[k + 1], &e[k],", HS),
    M("fill-type", "e->CarType = (int16_t)car->pCarTypeInfo->Type;",
      "e->CarType = (int16_t)car->pCarTypeInfo->CarClass;", HS),
    M("fill-name0", "e->NameIndex = (int16_t)(n > -1 ? n : 0);",
      "e->NameIndex = (int16_t)(n > -1 ? n : -1);", HS),
    M("maybe-zero-total", "        p->BestTotalRecordData = NULL;\n", "", HS),
    M("maybe-zero-lap", "        p->BestLapRecordData = NULL;\n", "", HS),
    M("maybe-laps", "if (rc->NumLapsCompleted == r->NumLapsInRace && i >= 0)",
      "if (rc->NumLapsCompleted >= r->NumLapsInRace && i >= 0)", HS),
    M("maybe-race-laps",
      "if (rc->NumLapsCompleted == r->NumLapsInRace && i >= 0)",
      "if (rc->NumLapsCompleted == rp->NumLapsInRace && i >= 0)", HS),
    M("maybe-place", "            placed = k;", "            placed = k + 1;",
      HS),
    M("maybe-ret", "return placed & 0xff;", "return placed;", HS),
    M("maybe-time", "e[k].Time = rc->RaceTime;",
      "e[k].Time.PackedTime = rc->RaceTime.PackedTime + 1;", HS),
    M("maybe-best", "e[k].Time = best;", "e[k].Time = rc->RaceTime;", HS),
    M("maybe-cls", "int32_t cls = car->pCarTypeInfo->CarClass;",
      "int32_t cls = car->pCarTypeInfo->Type;", HS),
    M("maybe-dir", "int32_t dir = rp->TrackDirection;",
      "int32_t dir = rp->TrackNumber;", HS),
    M("maybe-total-laps", "i = total_index(track, cls, dir, rp->NumLapsInRace);",
      "i = total_index(track, cls, dir, r->NumLapsInRace);", HS),
    M("maybe-lap-ptr", "p->BestLapRecordData = &e[k];",
      "p->BestLapRecordData = &e[0];", HS),
    M("maybe-total-ptr", "p->BestTotalRecordData = &e[k];",
      "p->BestTotalRecordData = &e[0];", HS),

    # The best times' rows.
    M("hash-n", "    snprintf(buf, sizeof buf, fmt, (int)n);",
      "    snprintf(buf, sizeof buf, fmt, (int)n + 1);"),
    M("is-time-0", "return t.PackedTime != 0 && t.PackedTime",
      "return t.PackedTime != 1 && t.PackedTime"),
    M("is-time-no", "t.PackedTime != HIGH_SCORE_NO_TIME;",
      "t.PackedTime != 0x7ffffffe;"),
    M("which-n", "int32_t n = PlayerNumPlayers < 2 ? PlayerNumPlayers : 2;",
      "int32_t n = 2;"),
    M("which-lap", "if ((lap ? p->BestLapRecordData : p->BestTotalRecordData)",
      "if ((lap ? p->BestTotalRecordData : p->BestLapRecordData)"),
    M("which-num", "            return p->PlayerNumber;",
      "            return i;"),
    M("row-pos", 'flailer_printf(hash, pos, "%2d", (int)k);',
      'flailer_printf(hash, pos, "%d", (int)k);'),
    M("row-type", "cartypeinfo_get(e->CarType)",
      "cartypeinfo_get(e->NameIndex)"),
    M("row-name", "fred_lookup_player_name_from_table(&Fred, e->NameIndex);",
      "fred_lookup_player_name_from_table(&Fred, e->CarType);"),
    M("row-trs", "    flailer_printf(hash, type, \"%s\",\n"
      "                   get_translated_string_by_name(\n"
      "                       car_type_info_get_short_name(\n"
      "                           cartypeinfo_get(e->CarType))));",
      "    flailer_printf(hash, type, \"%s\",\n"
      "                       car_type_info_get_short_name(\n"
      "                           cartypeinfo_get(e->CarType)));"),
    M("row-timer", "end_game_print_timer(buf, e->Time, 0);",
      "end_game_print_timer(buf, e->Time, 1);"),
    M("row-opt", "flailer_set_text_format_option(hash, time, TEXT_RIGHT_ALIGN);",
      "flailer_set_text_format_option(hash, pos, TEXT_RIGHT_ALIGN);"),
    M("row-default", "const bVector4 *color = &DefaultTextColor;",
      "const bVector4 *color = &PlayerTextColors[1];"),
    M("color-pl", "if (pl == 0 || pl == 1)", "if (pl == 0)"),
    M("speech-first", "        if (rs->Player == -1) {", "        if (1) {"),
    M("speech-place", "rs->Place = k - 1;", "rs->Place = k;"),
    M("speech-row", "rs->Row = transient_stats_get_driver(ts, pl == 1);",
      "rs->Row = transient_stats_get_driver(ts, pl);"),
    M("speech-finish", "rs->Finish = d->FinishPosition;",
      "rs->Finish = d->FinishPosition + 1;"),
    M("speech-cap", "#define NO_FINISH_POSITION  9",
      "#define NO_FINISH_POSITION  3"),
    M("speech-limit", "#define SPEECH_FINISH_LIMIT 4",
      "#define SPEECH_FINISH_LIMIT 5"),
    M("speech-null-row", "            && rs.Finish < SPEECH_FINISH_LIMIT && rs.Row != NULL)\n"
      "            post_game_record(gPostGameLapRecordFn",
      "            && rs.Finish < SPEECH_FINISH_LIMIT)\n"
      "            post_game_record(gPostGameLapRecordFn"),
    M("lap-said", "if (LAP_RECORD_SPEECH_SAID(s) == 0",
      "if (LAP_RECORD_SPEECH_SAID(s) != 0"),
    M("lap-set", "        LAP_RECORD_SPEECH_SAID(s) = 1;",
      "        LAP_RECORD_SPEECH_SAID(s) = 2;"),
    M("lap-flag", "#define LAP_RECORD_SPEECH_SAID(s)  ((s)->Zeroed[7])",
      "#define LAP_RECORD_SPEECH_SAID(s)  ((s)->Zeroed[6])"),
    M("time-said", "if (TIME_RECORD_SPEECH_SAID(s) == 0",
      "if (TIME_RECORD_SPEECH_SAID(s) != 0"),
    M("time-set", "        TIME_RECORD_SPEECH_SAID(s) = 1;",
      "        TIME_RECORD_SPEECH_SAID(s) = 2;"),
    M("time-flag", "#define TIME_RECORD_SPEECH_SAID(s) ((s)->Zeroed[8])",
      "#define TIME_RECORD_SPEECH_SAID(s) ((s)->Zeroed[7])"),
    M("speech-fn", "post_game_record(gPostGameTimeRecordFn",
      "post_game_record(gPostGameLapRecordFn"),
    M("speech-args", "post_game_record(gPostGameLapRecordFn, rs.Player, rs.Place,",
      "post_game_record(gPostGameLapRecordFn, rs.Place, rs.Player,"),

    # The best times' screens.
    M("blt-vt", "    endgame_menus_base_construct(m, hash);\n"
      "    m->vt = &kBestLapTimesVTable;",
      "    endgame_menus_base_construct(m, hash);\n"
      "    m->vt = &kBestTotalTimesVTable;"),
    M("btt-vt", "    endgame_menus_base_construct(m, hash);\n"
      "    m->vt = &kBestTotalTimesVTable;",
      "    endgame_menus_base_construct(m, hash);\n"
      "    m->vt = &kBestLapTimesVTable;"),
    M("blt-order", "                                              rp->TrackDirection);\n"
      "    show_track_name(m->ScreenHash);\n",
      "                                              rp->TrackDirection);\n"),
    M("btt-order", "    ct = first_car_type();\n    show_track_name(m->ScreenHash);\n"
      "    if (ct != NULL)\n        table = fred_get_best_total_times_table",
      "    ct = first_car_type();\n"
      "    if (ct != NULL)\n        table = fred_get_best_total_times_table"),
    M("track-dir", "                                TheRaceParameters.TrackDirection));",
      "                                TheRaceParameters.TrackNumber));"),
    M("track-obj", "flailer_set_language_id(hash, RACE_RESULTS_OBJ_TRACK_NAME,",
      "flailer_set_language_id(hash, RACE_RESULTS_OBJ_TRACK_NAME + 1,"),
    M("blt-cls", "                                              ct->CarClass,\n"
      "                                              rp->TrackDirection);",
      "                                              ct->Type,\n"
      "                                              rp->TrackDirection);"),
    M("btt-laps", "                                                rp->NumLapsInRace);",
      "                                                rp->NumPlayerCars);"),
    M("blt-lap", "show_records(m, table, which_player_set_lap_time_record, 1);",
      "show_records(m, table, which_player_set_lap_time_record, 0);"),
    M("btt-which", "show_records(m, table, which_player_set_total_time_record, 0);",
      "show_records(m, table, which_player_set_lap_time_record, 0);"),
    M("rows", "    for (i = 0; i < BEST_TIMES_ROWS; i++)\n        show_record",
      "    for (i = 0; i < BEST_TIMES_ROWS - 1; i++)\n        show_record"),

    # The lap times.
    M("best-lap-zero", "if (t != 0 && t < best) {", "if (t < best) {"),
    M("best-lap-strict", "if (t != 0 && t < best) {",
      "if (t != 0 && t <= best) {"),
    M("best-lap-start", "#define NO_BEST_LAP 99999999",
      "#define NO_BEST_LAP 140000"),
    M("best-lap-range", "    for (i = 0; i < LAP_TIMES_ROWS; i++) {\n"
      "        int32_t t",
      "    for (i = 0; i < LAP_TIMES_ROWS + 1; i++) {\n"
      "        int32_t t"),
    M("best-lap-index", "int32_t t = (int32_t)e->LapTimes[i + 1].PackedTime;",
      "int32_t t = (int32_t)e->LapTimes[i].PackedTime;"),
    M("lap-color", "best ? &kLapRecordColor : &DefaultTextColor",
      "best ? &DefaultTextColor : &kLapRecordColor"),
    M("lap-color-value", "kLapRecordColor = { 134.0f, 96.0f, 48.0f, 128.0f };",
      "kLapRecordColor = { 134.0f, 96.0f, 48.0f, 127.0f };"),
    M("lap-time", "    t = e->LapTimes[k];", "    t = e->LapTimes[k - 1];"),
    M("lap-opt", "        flailer_set_text_format_option(hash, obj, TEXT_RIGHT_ALIGN);",
      "        flailer_set_text_format_option(hash, obj, 0);"),
    M("lap-vis-order",
      "    flailer_set_object_color(hash, obj,\n"
      "                             best ? &kLapRecordColor : &DefaultTextColor);\n"
      "    flailer_set_visibility(hash, obj, FLAILER_OBJECT_VISIBLE);\n",
      "    flailer_set_visibility(hash, obj, FLAILER_OBJECT_VISIBLE);\n"
      "    flailer_set_object_color(hash, obj,\n"
      "                             best ? &kLapRecordColor : &DefaultTextColor);\n"),
    M("lt-n", "    n = na > nb ? na : nb;", "    n = na;"),
    M("lt-swap", "        a = b;\n        b = NULL;", "        a = b;"),
    M("lt-np", "    if (np == 2) {", "    if (np >= 2) {"),
    M("lt-p1", "        p = PlayerPlayersByIndex[1];\n        if (p == NULL)\n"
      "            return d;\n    }\n    show_player_name",
      "        return d;\n    }\n    show_player_name"),
    M("lt-p2-null", "        p = PlayerPlayersByIndex[1];\n        if (p == NULL)\n"
      "            return d;\n        show_player_name",
      "        p = PlayerPlayersByIndex[1];\n        if (p == NULL)\n"
      "            p = PlayerPlayersByIndex[0];\n        show_player_name"),
    M("lt-name-obj", "show_player_name(hash, LAP_TIMES_OBJ_P2_NAME, p);",
      "show_player_name(hash, LAP_TIMES_OBJ_P1_NAME, p);"),
    M("lt-name-fmt", 'b_snprintf(buf, sizeof buf, "%s", p->PlayerSettings.PlayerName);',
      'b_snprintf(buf, 6, "%s", p->PlayerSettings.PlayerName);'),
    M("lt-lapname", "        if (i < n) {", "        if (i <= n) {"),
    M("lt-hide", "            flailer_set_visibility(hash, p2, FLAILER_OBJECT_INVISIBLE);\n"
      "        }\n    }", "        }\n    }"),
    M("lt-k", 'flailer_printf(hash, lap, "%d", (int)k);',
      'flailer_printf(hash, lap, "%d", (int)i);'),
    M("lt-drivers", "    b = transient_stats_get_driver(ts, 1);",
      "    b = transient_stats_get_driver(ts, 2);"),
    M("ltd-noise", "if (msg != BMSG_SCREEN_BACK_BUTTON)",
      "if (msg == BMSG_SCREEN_BACK_BUTTON)"),
    M("ltd-pool", "#define END_TIMES_POOL 16", "#define END_TIMES_POOL 15"),
    M("ltd-unact", "        pLapTimesDisplay = NULL;\n    } else {",
      "    } else {"),
    M("ltd-hash", "lap_times_display_construct(d, data->itemHash)",
      "lap_times_display_construct(d, data->itemHash + 1)"),
    M("ltd-free", "    if (flags & 1)\n        bFree(d);",
      "    if (flags & 4)\n        bFree(d);"),
]

# Mutations that cannot change what the script sees, and why.
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
        todo, SOURCES, "endtimes_test",
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
        rc_ = run_harness(exe, scp, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(lines, harness)
    print("%d ops, %d lines, %d differ" % (len(sc), len(harness), n))
    sys.exit(1 if (n or rc_) else 0)


if __name__ == "__main__":
    main()
