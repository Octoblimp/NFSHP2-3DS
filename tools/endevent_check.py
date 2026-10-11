#!/usr/bin/env python3
"""Cross-check 3DS Files/source/endevent.c -- the career's end-game
screens: Tourney Standings, the event's result (the Reward menu), Events
Unlocked and the two You're The Cop results -- against the retail image,
SLES_507.31.

**The model** is retail's own code run in retail_model.RetailEmu: the five
screens' constructors and destructors (the end game's base destructor
under them), the Reward menu's blurb id, its blurb and the player's place
(0x001de788, 0x001dead8, 0x001dea88), the tourney points' order and
bList::Sort under it, with FrontendDatabase::UseTheRaceEvent,
TransientStats::GetDriver, RacingCar::GetPlayer, DriverInfo::GetName,
CarTypeInfo::GetShortName, GetTheRightTrackLanguageID(int),
RenderTextIntoGroup(int, int, int) and SprintfAndHash with the real
bStringHash. bSPrintf and bVSPrintf format natively, so FlailerPrintf
runs and only FindFlailerObject and SetString under it are stubbed.

**The stubs** print what they are asked, on both sides: the end game's
base constructor, the Flailer calls, RenderTextIntoGroup(int, int, char
*), both GetTranslatedStrings, GetTrackInfo, GetTheRightTrackLanguageID,
SetTrackNameAndRaceNumber and 0x001dc500 (endresults_check.py checks
them), RaceEvent's GetStatus, AnyRewardEarned, RewardEarned,
StatusAdvanced, RacerIndexFromDriverNumber and GetTournamentState,
EventTournamentState's RacerRank, UserRank and GetPointsForFinishPos
(raceevent_check.py checks them), the events opened (fredevent_check.py),
the three speeches, the Reward screens' car count (endresults_check.py),
GetCarByDriverNumber, bMalloc and bFree. The colours are what the static
initialisers leave, as tools/endresults_check.py runs them. The harness
(tools/src/endevent_test.c) runs endevent.c with bprintf.c and blist.c.

**The script** makes Tourney Standings over each GameType and event
type, none to eight cars, no race, no state, ties, places and none,
players and drivers with and without names, each player number and the
speech's flag and status; asks the Reward menu's blurb id over every
event, race type and place, and its blurb for every id over each goal
and reward; makes the Reward menu over each speech and the car count;
Events Unlocked over each tree and count; and You're The Cop's results
over each finish, time left and points; then random ones of each.

    python tools/endevent_check.py
    python tools/endevent_check.py --mutate [--only a,b]
    python tools/endevent_check.py --dump out/endevent
"""
import argparse
import random
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/endevent_test.c"
EE = "3DS Files/source/endevent.c"
EH = "3DS Files/source/endevent.h"
SOURCES = [HARNESS, EE, "3DS Files/source/bprintf.c",
           "3DS Files/source/blist.c"]
HARNESS_TIMEOUT = 60

GP = retail_model.RETAIL_GP
FRED = 0x002fc050
FRED_SIZE = 0x10740
TS = FRED + 908
GAME_TYPE = FRED + 0x1072c
RP = 0x0031a898
TRE = 0x0031b600
TEO = TRE + 432
P_RACE = GP - 22272
TRACK_INFO = GP - 21952
CAR_TYPE_INFOS = GP - 20616
PBN = GP - 20936
PBI = GP - 20928
P_EGS = GP - 17628

F_TOURNEY, F_REWARD, F_UNLOCKED = 0x001dd5d0, 0x001def38, 0x001df180
F_BTC1, F_BTC2 = 0x001e0898, 0x001e0a10
F_LANG, F_FMT, F_RANK = 0x001de788, 0x001dead8, 0x001dea88

S_BASE = 0x001dd080
S_VIS, S_LANG, S_COLOR = 0x00144968, 0x001449a8, 0x001449e8
S_GVIS = 0x001454e8
S_FIND, S_SETSTR = 0x00143d50, 0x00140e20
S_RTIG = 0x00144ba0
S_TR, S_TRS = 0x0021e560, 0x0021e508
S_TRACKINFO, S_TRACKID = 0x00153420, 0x001dc580
S_TRACKRACE, S_PTIMER = 0x001dc5d8, 0x001dc500
S_STATUS, S_ANY, S_EARNED, S_ADV = (0x00202658, 0x00200ac8, 0x00200b30,
                                    0x00201db8)
S_RIDX, S_TSTATE = 0x00201558, 0x00201880
S_RANK, S_URANK, S_PTS = 0x00200710, 0x00200768, 0x00200788
S_OPENED = 0x001f7398
S_TSPEECH, S_EVSPEECH, S_RWSPEECH = 0x002073f0, 0x00206bc8, 0x00207450
S_SHOWCOUNT, S_CLEARCOUNT = 0x001de4a0, 0x001de550
S_CARBY = 0x0014d5d0
S_SCREEN_CONFIG = 0x0016ad88
B_MALLOC, B_FREE = 0x002577c0, 0x00257850

VTABLES = {0x002b9028: "TOURNEY", 0x002b9088: "REWARD",
           0x002b90b8: "UNLOCKED", 0x002b8f98: "BTC1", 0x002b8f68: "BTC2",
           0x002b9148: "BASE"}

MAX_TYPES = 64
NUM_CARS = 16
NUM_PLAYERS = 4
NUM_TRACKS = 8
PSTRIDE = 2576
TSTRIDE = 164
DSTRIDE = 32
CSTRIDE = 40

# The tr stub's formats, as the harness's kFormats.
FORMATS = {
    0xde2b0: "C1 %d", 0xde2b4: "C2 %d+%d", 0xde2b1: "C3 %d,%d,%d",
    0xde2b2: "U1 %d", 0xde2b5: "U2 %d+%d", 0xde2b3: "U3 %d,%d,%d",
    0xde4a4: "PASSED %d", 0xde4a5: "FAILED %d",
    0xe09c0: "LAPF %s/%s", 0xe09c1: "LAPU %s/%s", 0xe09c2: "TOTF %s/%s",
    0xe09c3: "TOTU %s/%s", 0xe09c4: "COPU %s", 0xe09c6: "LAPP %s",
    0xe09c7: "TOTP %s", 0xe30d0: "1U %s", 0xe30d1: "2U %s",
    0xe30d2: "3U %s", 0xe30d3: "PLF %s/%s", 0xe30d4: "PU %s",
}

# Every blurb id the Reward menu can ask for, and some it cannot.
REWARD_IDS = [0xe09c0, 0xe09c1, 0xe09c2, 0xe09c3, 0xe09c4, 0xe09c5,
              0xe09c6, 0xe09c7, 0xe30d0, 0xe30d1, 0xe30d2, 0xe30d3,
              0xe30d4, 0xe30d5, 0xe30d6, 0xe30da, 0xe30db, 0xe30dc,
              0xe30dd, 0xe32c4, 0xe32c5, 0xe32c6, 0, 0x12345]


def cx(v):
    """C's %#x: 0 has no 0x."""
    v &= M32
    return "%#x" % v if v else "0"


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


# ================================================================== script

H_TOURNEY = 0x3c1d2e4f
H_REWARD = 0x5a6b7c8d
H_UNLOCKED = 0x1e2f3a4b
H_BTC1 = 0x7d8e9fa0
H_BTC2 = 0x2b3c4d5e

NO_TIME = 0x7fffffff


def row(i, pos=1, unique=0, reason=0, rtime=0, best=0, pts=0, total=0,
        cop=0):
    return "row|%d|%d|%d|%d|%d|%d|%d|%d|%d" % (
        i, pos, unique, reason, rtime & M32, best & M32, pts & M32,
        total & M32, cop & M32)


def race(cars):
    cars = list(cars) + [-1] * (8 - len(cars))
    return "race|%d|%s" % (len([c for c in cars if c >= 0]),
                           "|".join(str(c) for c in cars))


def race_n(n, cars):
    cars = list(cars) + [-1] * (8 - len(cars))
    return "race|%d|%s" % (n, "|".join(str(c) for c in cars))


def st(bs):
    bs = list(bs) + [0] * (16 - len(bs))
    return "st|" + "|".join(str(b & 0xff) for b in bs)


def ranks(rs):
    """RacerRank's answers by racer index. They must differ: retail's sort
    never ends on a tie (see tourney_in_order)."""
    rs = list(rs)
    rs += [40 + i for i in range(16 - len(rs))]
    assert len(set(rs)) == 16, rs
    return "ranks|" + "|".join(str(r) for r in rs)


def screen(op, h, flags=1, extra=()):
    return ["%s|%#x" % (op, h)] + list(extra) + ["dtor|%d" % flags]


def world():
    """Eight drivers in eight cars: the first a player's."""
    s = ["player|0|0|ANDREW", "player|1|1|MARA", "player|2|2|THIRD",
         "player|3|3|FOURTH", "pbn|0|1", "pbi|0|1"]
    names = ["Ace", "Bea", "Cid", "Dot", "Eve", "Fox", "Gus", "Hal"]
    for i, nm in enumerate(names):
        s += ["char|%d|%s" % (i, nm)]
    s += ["drv|0|0|1|0", "car|0|0|5|0|0", "rc|0|0"]
    for i in range(1, 8):
        s += ["drv|%d|%d|0|%d" % (i, 99 + i, i),
              "car|%d|%d|%d|%d|-1" % (i, 99 + i, 10 + i, i),
              "rc|%d|%d" % (i, i)]
    s += ["byd|0|0", "byd|1|-1"]
    for i in range(8):
        s += ["res|%d|%d" % (i, i + 1)]
    return s


def tourney_script():
    s = world()
    s += ["gt|8", "ev|5|4|1|0|1|1", st([40, 35, 30, 25, 20, 15, 10, 5]),
          ranks(range(1, 17)), "egs|0|0|0", "status|0",
          race(range(8))]
    one = screen("tourney", H_TOURNEY)
    # Each GameType: only 4, 8 and 9 are an event's.
    for gt in (0, 1, 3, 4, 5, 7, 8, 9, 10, 11, -1):
        s += ["gt|%d" % gt, "egs|0|0|0"] + one
    s += ["gt|8"]
    # Each event type: only a tournament has standings.
    for t in (0, 1, 2, 3, 5, 6, 7, 4):
        s += ["ev|5|%d|1|0|1|1" % t, "egs|0|0|0"] + one
    # None to eight cars, and no race.
    for n in range(9):
        s += [race(range(n)), "egs|0|0|0"] + one
    s += [race([]), "egs|0|0|0"] + one
    s += ["race|-1", "egs|0|0|0"] + one
    s += [race(range(8))]
    # The cars in another order, and gaps in the list.
    s += [race([7, 6, 5, 4, 3, 2, 1, 0]), "egs|0|0|0"] + one
    s += [race_n(5, [2, 0, 4, 1, 3, 5, 6, 7]), "egs|0|0|0"] + one
    s += [race(range(8))]
    # The ranks by racer index (the player's 0, the rest 1 to 7):
    # reversed, shuffled, one apart, negative and past the eight.
    for rs in ([8, 7, 6, 5, 4, 3, 2, 1], [3, 1, 4, 8, 5, 7, 2, 6],
               [0, 2, 4, 6, 8, 10, 12, 14], [-1, 0, 1, 7, 255, -5, 8, 3],
               [2, 1, 3, 4, 5, 6, 7, 8], [1, 2, 3, 4, 5, 6, 8, 7]):
        s += [ranks(rs), "egs|0|0|0"] + one
    s += [ranks(range(1, 17))]
    # The state's points, high bytes too, and no state.
    s += [st([200, 0, 255, 128, 127, 1, 2, 3, 4]), "egs|0|0|0"] + one
    s += ["ev|5|4|1|0|1|0", "egs|0|0|0"] + one
    s += ["ev|5|4|1|0|1|1"]
    # Racer indexes from the event's initial players: the AI's from 2, 4
    # and 7 on, as many cars as keep them in the eight (0 would put one on
    # the player's index).
    for init in (2, 4, 7):
        s += ["ev|5|4|1|0|%d|1" % init, race(range(9 - init)),
              "egs|0|0|0"] + one
    s += ["ev|5|4|1|0|1|1", race(range(8))]
    # The places: none (DNF), each, and past the eight.
    for places in ([0] * 8, [1, 0, 2, 0, 3, 0, 4, 0],
                   [8, 7, 6, 5, 4, 3, 2, 1], [9, 12, 100, -1, 1, 1, 1, 1]):
        s += ["res|%d|%d" % (i, p) for i, p in enumerate(places)]
        s += ["egs|0|0|0"] + one
    s += ["res|%d|%d" % (i, i + 1) for i in range(8)]
    # The speech: its flag, and each status.
    for flag in (0, 1, 2, -1):
        for status in (0, 1, 2, 3, 4, 5):
            s += ["egs|0|0|%d" % flag, "status|%d" % status] + one
    s += ["status|0"]
    # The player's row lower down the points.
    s += [ranks([6, 1, 2, 3, 4, 5, 7, 8]), "egs|0|0|0"] + one
    s += [ranks(range(1, 17))]
    # Two players, and the other player numbers' colours.
    s += ["car|1|100|11|1|1", "egs|0|0|0"] + one
    for pn in (1, 2, 0):
        s += ["player|1|%d|MARA" % pn, "egs|0|0|0"] + one
    s += ["player|1|1|MARA", "car|1|100|11|1|-1"]
    # A player's driver in the world's car with a player (retail reads
    # through none), a long name, and an AI driver without a character.
    s += ["drv|1|1|1|1", "car|1|1|11|1|1", "byd|1|1", "egs|0|0|0"] + one
    s += ["player|1|1|ABCDEFGHIJK", "egs|0|0|0"] + one
    s += ["player|1|1|MARA", "drv|1|100|0|1", "car|1|100|11|1|-1",
          "byd|1|-1"]
    s += ["drv|2|101|0|-1", "char|3|", "egs|0|0|0"] + one
    s += ["drv|2|101|0|2", "char|3|Dot"]
    # A player's car with an AI driver.
    s += ["car|2|101|12|2|1", "egs|0|0|0"] + one
    s += ["car|2|101|12|2|-1"]
    # Each car type's name.
    for i, ct in enumerate((0, 1, 33, 63)):
        s += ["car|%d|%d|%d|%d|%d" % (i, 0 if i == 0 else 99 + i, ct, i,
                                      0 if i == 0 else -1)]
    s += ["egs|0|0|0"] + one
    s += ["car|0|0|5|0|0"]
    s += ["car|%d|%d|%d|%d|-1" % (i, 99 + i, 10 + i, i) for i in range(1, 4)]
    # The destructor's flags, and the vtable's other calls.
    s += ["egs|0|0|0", "tourney|%#x" % H_TOURNEY, "scroll|6", "scroll|7",
          "tick", "render", "dtor|0"]
    for f in (2, 3):
        s += screen("tourney", H_TOURNEY ^ f, f)
    return s


def reward_setup():
    return ["gt|8", "ev|5|0|1|0|1|1", "goal|1|3", "rew|0|0|7|0|0|0",
            "rp|0|0|0|0|0", "status|4", "any|0", "earned|0", "adv|0",
            "urank|1", "ts|2", row(0, 1, 0, 0, 0x123456, 0x23456),
            row(1, 2, 1), "egs|0|0|0", "cti|0"]


def lang_script():
    s = world() + reward_setup()
    # The trees' last events, the Ultimate and the bonus events.
    for num in (30, 32, 31, 29, 1):
        for gt in (8, 9, 4, 0):
            for status in (4, 3, 0):
                s += ["ev|%d|0|1|0|1|1" % num, "gt|%d" % gt,
                      "status|%d" % status, "lang"]
    s += ["gt|8", "ev|5|0|1|0|1|1"]
    # The race types: time trial, point to point and Be A Cop, each timed
    # or not.
    for rt in (0, 1, 2, 3):
        for ttt in (0, 1, 1000, NO_TIME, 0x80000000, 0xffffffff):
            for p2p in (0, 1):
                for cop in (0, 1):
                    for status in (4, 3):
                        for any_ in (0, 1):
                            s += ["rp|0|%d|%d|%d|%d" % (rt, ttt, p2p, cop),
                                  "status|%d" % status, "any|%d" % any_,
                                  "lang"]
    s += ["rp|0|0|0|0|0"]
    # The places, from the tournament's rank or the first player's row.
    for rank in range(-1, 7):
        for any_ in (0, 1):
            s += ["ev|5|4|1|0|1|1", "urank|%d" % rank, "any|%d" % any_,
                  "status|4", "lang", "rank"]
            s += ["ev|5|0|1|0|1|1", row(0, rank, 0), "lang", "rank"]
    s += ["ev|5|4|1|0|1|0", "urank|2", "lang", "rank"]
    s += ["ev|5|0|1|0|1|1", "ts|1", row(0, 3, 7), "lang", "rank", "ts|0",
          "rank", "ts|2", row(0, 1, 0, 0, 0x123456, 0x23456)]
    return s


def format_script():
    s = world() + reward_setup()
    for goal in ((1, 3), (2, 0x1a2b3c), (0, 5), (1, 0), (1, 9), (2, 0),
                 (3, 7)):
        for rew in ((0, 7, 0, 0), (0, 63, 1, 2), (1, 2, 0, 0),
                    (1, 7, 1, 0), (1, 9, 0, 0), (1, 0, 2, 0),
                    (2, 4, 5, 6), (255, 1, 1, 1)):
            s += ["goal|%d|%d" % goal, "rew|0|%d|%d|%d|%d|0" % rew]
            for i in REWARD_IDS:
                s += ["fmt|%#x" % i]
    s += ["goal|1|3", "rew|0|0|7|0|0|0"]
    # The places' names, by the place and the place needed.
    for place in range(0, 10):
        s += ["urank|%d" % place, "ev|5|4|1|0|1|1", "goal|1|%d" % place,
              "fmt|%#x" % 0xe30d3]
        s += ["ev|5|0|1|0|1|1", row(0, place, 0), "fmt|%#x" % 0xe30d3]
    # The first player's times: none, and set.
    s += ["ts|0", "fmt|%#x" % 0xe09c0, "fmt|%#x" % 0xe09c2,
          "fmt|%#x" % 0xe30d3, "ts|2",
          row(0, 2, 0, 0, NO_TIME, 0x80000000), "fmt|%#x" % 0xe09c0,
          "fmt|%#x" % 0xe09c2, row(0, 1, 0, 0, 0x123456, 0x23456)]
    # The nRewards count does not matter to the blurb.
    s += ["ev|5|0|0|0|1|1", "fmt|%#x" % 0xe09c1, "ev|5|0|1|0|1|1"]
    return s


def reward_screen_script():
    s = world() + reward_setup()
    one = screen("reward", H_REWARD)
    # The speech: each status, the Ultimate, the bonus event open last or
    # not, the rewards, the flag.
    for num, last in ((5, 0), (32, 0), (32, 1), (31, 0), (31, 1), (30, 0),
                      (1, 1)):
        for status in (4, 3, 0):
            for nrew in (1, 0, -1, 3):
                for any_ in (0, 1):
                    s += ["ev|%d|0|%d|%d|1|1" % (num, nrew, last),
                          "status|%d" % status, "any|%d" % any_,
                          "egs|0|0|0"] + one
    s += ["ev|5|0|1|0|1|1", "status|4"]
    for flag in (1, 2, -1):
        s += ["egs|0|%d|0" % flag] + one
    # No first player, no row.
    s += ["pbn|-1|1", "egs|0|0|0"] + one
    s += ["status|3", "egs|0|0|0"] + one
    s += ["ts|0", "egs|0|0|0"] + one
    s += ["pbn|0|1", "ts|2", "status|4"]
    # The car count: a car reward the race advanced and earned.
    for nrew in (1, 0, 2):
        for rtype in (0, 1, 2):
            for adv in (0, 1):
                for earned in (0, 1, 2):
                    s += ["ev|5|0|%d|0|1|1" % nrew,
                          "rew|0|%d|7|0|0|0" % rtype, "adv|%d" % adv,
                          "earned|%d" % earned, "egs|0|1|0"] + one
    s += ["ev|5|0|1|0|1|1", "rew|0|0|7|0|0|0", "adv|0", "earned|0"]
    # The title's number, and the blurb through each race type.
    for num in (1, 17, 31, 32, -3, 300):
        for status in (4, 3):
            s += ["ev|%d|0|1|1|1|1" % num, "status|%d" % status,
                  "egs|0|1|0"] + one
    s += ["ev|5|0|1|0|1|1", "status|4"]
    for rp in ("rp|0|2|1000|0|0", "rp|0|0|1000|1|0", "rp|0|0|0|0|1",
               "rp|0|0|0|0|0"):
        for any_ in (0, 1):
            s += [rp, "any|%d" % any_, "egs|0|1|0"] + one
    s += ["tourney|%#x" % H_REWARD, "dtor|1"]
    s += ["reward|%#x" % H_REWARD, "scroll|6", "tick", "render", "dtor|0"]
    s += screen("reward", H_REWARD, 3)
    return s


def unlocked_script():
    s = world() + reward_setup()
    one = screen("unlocked", H_UNLOCKED)
    for gt in (8, 9, 4, 0, 10):
        for n in range(5):
            for flag in (0, 1):
                s += ["gt|%d" % gt,
                      "opened|%d|%d|%d|%d|%d" % (n, 3, 17, 25, 9),
                      "egs|%d|0|0" % flag] + one
    s += ["gt|8", "opened|2|0|31|-4|1000", "egs|0|0|0"] + one
    s += ["pbi|-1|1", "egs|0|0|0"] + one
    s += ["ts|0", "egs|0|0|0"] + one
    s += ["pbi|0|1", "ts|2", "status|3", "egs|-1|0|0"] + one
    s += ["unlocked|%#x" % H_UNLOCKED, "scroll|7", "tick", "render",
          "dtor|2"]
    return s


def btc_script():
    s = world() + reward_setup()
    one1 = screen("btc1", H_BTC1)
    one2 = screen("btc2", H_BTC2)
    # The track's name, each direction, and no track.
    for t in (0, 3, 7, -1):
        for d in (0, 1, 2, -1):
            s += ["cti|%d" % t, "rp|%d|0|0|0|1" % d] + one1 + one2
    s += ["cti|0", "rp|0|0|0|0|1"]
    # 1P: each finish, the time left and the points.
    for reason in range(7):
        for cop in (0.0, 12.75, 59.999, -3.5, 0.5, 1e5, 3e7, 3e9, -3e9):
            for pts, total in ((0, 0), (1500, 22000), (-200, 7),
                               (0x7fffff00, 0x7fffffff)):
                s += [row(0, 1, 0, reason, 0, 0, pts, total, fbits(cop))]
                s += one1
    s += ["ts|0"] + one1 + ["ts|2"]
    # 2P: each pair of finishes.
    for a in range(7):
        for b in range(7):
            s += [row(0, 1, 0, a, 0, 0, 100 * a + b, 0),
                  row(1, 2, 1, b, 0, 0, -b, 0)] + one2
    s += ["ts|1"] + one2 + ["ts|0"] + one2 + ["ts|2"]
    s += [row(0, 1, 7, 4), row(1, 2, 0, 5, 0, 0, 33)] + one2
    s += ["btc1|%#x" % H_BTC1, "scroll|6", "tick", "render", "dtor|0",
          "btc2|%#x" % H_BTC2, "scroll|6", "tick", "render", "dtor|3"]
    return s


def random_script(rnd, n):
    s = world() + reward_setup()
    for _ in range(n):
        gt = rnd.choice((8, 8, 9, 9, 4, 0))
        # The AI's racer indexes start at init; their cars stop at 7.
        init = rnd.randint(1, 3)
        cars = range(9 - init)
        order = rnd.sample(cars, len(cars))
        nrc = rnd.randint(0, len(cars))
        s += ["gt|%d" % gt,
              "ev|%d|%d|%d|%d|%d|%d" % (
                  rnd.choice((1, 5, 30, 31, 32, rnd.randint(1, 32))),
                  rnd.choice((4, 4, 0, 1, 2, 3)), rnd.randint(0, 3),
                  rnd.randint(0, 1), init, rnd.choice((1, 1, 0))),
              st([rnd.randint(0, 255) for _ in range(16)]),
              ranks(rnd.sample(range(-3, 30), 16)),
              race_n(nrc, order),
              "status|%d" % rnd.choice((4, 3, 0, 1)),
              "any|%d" % rnd.randint(0, 1),
              "earned|%d" % rnd.randint(0, 1),
              "adv|%d" % rnd.randint(0, 1),
              "urank|%d" % rnd.randint(0, 9),
              "goal|%d|%d" % (rnd.choice((0, 1, 2)), rnd.randint(0, 9)),
              "rew|0|%d|%d|%d|0|0" % (rnd.choice((0, 1, 2)),
                                      rnd.randint(0, 9), rnd.randint(0, 2)),
              "rp|%d|%d|%d|%d|%d" % (rnd.randint(0, 2), rnd.randint(0, 3),
                                     rnd.choice((0, 1000, NO_TIME)),
                                     rnd.randint(0, 1), rnd.randint(0, 1)),
              "opened|%d|%d|%d|%d|%d" % (rnd.randint(0, 4),
                                         rnd.randint(1, 32),
                                         rnd.randint(1, 32),
                                         rnd.randint(1, 32),
                                         rnd.randint(1, 32)),
              "cti|%d" % rnd.choice((0, 1, 2, -1)),
              "egs|%d|%d|%d" % (rnd.randint(0, 1), rnd.randint(0, 1),
                                rnd.randint(0, 1))]
        for i in range(8):
            s += ["res|%d|%d" % (i, rnd.randint(0, 9))]
        nrows = rnd.randint(0, 3)
        uniques = rnd.sample((0, 1, 5), nrows)
        s += ["ts|%d" % nrows]
        for i in range(nrows):
            s += [row(i, rnd.randint(0, 9), uniques[i], rnd.randint(0, 6),
                      rnd.getrandbits(32), rnd.getrandbits(32),
                      rnd.randint(-500, 5000), rnd.randint(0, 99999),
                      fbits(rnd.uniform(-10, 120)))]
        s += ["lang", "rank"]
        for op, h in (("tourney", H_TOURNEY), ("reward", H_REWARD),
                      ("unlocked", H_UNLOCKED), ("btc1", H_BTC1),
                      ("btc2", H_BTC2)):
            if rnd.random() < 0.6:
                s += ["%s|%#x" % (op, h ^ rnd.getrandbits(8)),
                      "dtor|%d" % rnd.randint(0, 3)]
    return s


def script():
    s = tourney_script() + lang_script() + format_script()
    s += reward_screen_script() + unlocked_script() + btc_script()
    s += random_script(random.Random(0xe6d), 150)
    return s


# =================================================================== model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        e.stub_bware()
        e.stub(S_SCREEN_CONFIG, lambda em: em.reg[4] & M32)
        e.run_ctors(r"\$(pEndGameScreens|PRERACE_STATS)$")

        sizes = (("ctinfo", MAX_TYPES * 1376), ("specs", MAX_TYPES * 32),
                 ("cars", NUM_CARS * 64), ("rides", NUM_CARS * 16),
                 ("drivers", NUM_CARS * DSTRIDE), ("chars", 8 * CSTRIDE),
                 ("rcs", NUM_CARS * 192),
                 ("players", NUM_PLAYERS * PSTRIDE), ("race", 1700),
                 ("tracks", NUM_TRACKS * TSTRIDE), ("egs", 72),
                 ("state", 16), ("dummy", 64), ("buf", 512))
        for name, n in sizes:
            a = e.alloc(n)
            e.write(a, bytes(n))
            setattr(self, name, a)
        for i in range(MAX_TYPES):
            e.put32(self.ctinfo + i * 1376 + 1368, self.specs + i * 32)
            e.put32(self.specs + i * 32 + 20, 0x40000 + i)
        for i in range(NUM_CARS):
            e.put32(self.cars + 64 * i + 16, self.rides + 16 * i)
        e.put32(CAR_TYPE_INFOS, self.ctinfo)
        e.put32(P_EGS, self.egs)
        e.put32(P_RACE, self.race)
        e.put32(TRACK_INFO, self.tracks)
        for a in (PBN, PBN + 4, PBI, PBI + 4):
            e.put32(a, 0)
        e.write(FRED, bytes(FRED_SIZE))
        e.write(RP, bytes(800))
        e.write(TRE, bytes(432))

        self.status = self.any = self.earned = self.adv = 0
        self.ranks = [0] * 16
        self.urank = 0
        self.opened = (0, [0, 0, 0, 0])
        self.carby = [-1, -1]
        self.blocks = []
        self.screen = 0
        self.find = (0, 0)

        for a, fn in ((S_BASE, self.base),
                      (S_VIS, self.say3("vis")), (S_GVIS, self.say3("gvis")),
                      (S_LANG, self.lang), (S_COLOR, self.color),
                      (S_FIND, self.find_obj), (S_SETSTR, self.set_string),
                      (S_RTIG, self.rtig),
                      (S_TR, self.tr), (S_TRS, self.trs),
                      (S_TRACKINFO, self.trackinfo),
                      (S_TRACKID, self.trackid),
                      (S_TRACKRACE, self.trackrace), (S_PTIMER, self.ptimer),
                      (S_STATUS, self.ask("status", "status")),
                      (S_ANY, self.ask("any", "any")),
                      (S_EARNED, self.earned_stub),
                      (S_ADV, self.ask("adv", "adv")),
                      (S_RIDX, self.ridx), (S_TSTATE, self.tstate),
                      (S_RANK, self.rank), (S_URANK, self.urank_stub),
                      (S_PTS, self.pts), (S_OPENED, self.opened_stub),
                      (S_TSPEECH, self.tspeech),
                      (S_EVSPEECH, self.evspeech),
                      (S_RWSPEECH, self.rwspeech),
                      (S_SHOWCOUNT, self.showcount),
                      (S_CLEARCOUNT, self.clearcount),
                      (S_CARBY, self.carby_stub),
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

    def row_name(self, p):
        if p == 0:
            return "none"
        return "r%d" % ((p - (TS + 12)) // 100)

    def player(self, i):
        return self.players + PSTRIDE * i

    def player_name(self, p):
        if p == 0:
            return "none"
        return "p%d" % ((p - self.players) // PSTRIDE)

    def state_name(self, p):
        return "st" if p == self.state else "none" if p == 0 else "?"

    def tre_name(self, p):
        return "tre" if p == TRE else "?"

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
        return self.dummy

    def set_string(self, em):
        text = self.cstr(em.reg[5] & M32, 4096)
        self.emit("  printf %08x %08x [%s]" % (self.find + (text[:127],)))
        return 0

    def rtig(self, em):
        r = em.reg
        text = self.cstr(r[6] & M32, 4096)
        self.emit("  rtig %08x %08x [%s]" % (r[4] & M32, r[5] & M32,
                                             text[:200]))
        return 0

    def tr(self, em):
        i = s32(em.reg[4])
        self.emit("  tr %s" % cx(i))
        text = FORMATS.get(i & M32, "T%x" % (i & M32))
        raw = text.encode("latin-1") + b"\0"
        a = self.e.alloc(len(raw))
        self.e.write(a, raw)
        return a

    def trs(self, em):
        a = em.reg[4] & M32
        self.emit("  trs %s" % self.cstr(a))
        return a

    def trackinfo(self, em):
        i = s32(em.reg[4])
        self.emit("  trackinfo %d" % i)
        return self.tracks + TSTRIDE * i if 0 <= i < NUM_TRACKS else 0

    def trackid(self, em):
        r = em.reg
        a = r[4] & M32
        d = s32(r[5])
        if a == 0:
            return 0
        k = (a - self.tracks) // TSTRIDE
        self.emit("  trackid t%d %d" % (k, d))
        return (0x4a000 + k * 16 + d) & M32

    def trackrace(self, em):
        r = em.reg
        self.emit("  trackrace %08x %08x %08x %d" % (
            r[4] & M32, r[5] & M32, r[6] & M32, s32(r[7])))
        return 0

    def ptimer(self, em):
        r = em.reg
        t = r[5] & M32
        self.emit("  ptimer %08x %d" % (t, s32(r[6])))
        self.e.write(r[4] & M32, ("P%x" % t).encode("latin-1") + b"\0")
        return 0

    def ask(self, word, attr):
        def stub(em):
            self.emit("  %s %s" % (word, self.tre_name(em.reg[4] & M32)))
            return getattr(self, attr) & M32
        return stub

    def earned_stub(self, em):
        r = em.reg
        self.emit("  earned %s %d %s" % (self.tre_name(r[4] & M32),
                                         s32(r[5]),
                                         "none" if (r[6] & M32) == 0
                                         else "?"))
        return self.earned & M32

    def ridx(self, em):
        n = s32(em.reg[5])
        self.emit("  ridx %d" % n)
        init = struct.unpack("<h", bytes(self.e.mem[TRE + 118:TRE + 120]))[0]
        return (n if n < 100 else init + n - 100) & M32

    def tstate(self, em):
        self.emit("  tstate")
        return self.e.u32(TRE + 4)

    def rank(self, em):
        r = em.reg
        i = s32(r[5])
        self.emit("  rank %s %d" % (self.state_name(r[4] & M32), i))
        return self.ranks[i & 15] & M32

    def urank_stub(self, em):
        self.emit("  urank %s" % self.state_name(em.reg[4] & M32))
        return self.urank & M32

    def pts(self, em):
        p = s32(em.reg[4])
        self.emit("  pts %d" % p)
        return (100 + p) & M32

    def opened_stub(self, em):
        r = em.reg
        self.emit("  opened %s %d %s" % (
            "teo" if (r[4] & M32) == TEO else "?", s32(r[6]),
            self.tre_name(r[7] & M32)))
        n, lst = self.opened
        out = r[5] & M32
        for i in range(min(max(n, 0), 4)):
            self.e.put32(out + 4 * i, lst[i] & M32)
        return n & M32

    def tspeech(self, em):
        r = em.reg
        self.emit("  tspeech %d %d" % (s32(r[4]), s32(r[5])))
        return 0

    def evspeech(self, em):
        r = em.reg
        self.emit("  evspeech %s %s" % (self.player_name(r[4] & M32),
                                        self.row_name(r[5] & M32)))
        return 0

    def rwspeech(self, em):
        r = em.reg
        rw = r[6] & M32
        self.emit("  rwspeech %s %d %s" % (
            self.player_name(r[4] & M32), s32(r[5]),
            "none" if rw == 0 else "r0" if rw == TRE + 244 else "?"))
        return 0

    def showcount(self, em):
        r = em.reg
        self.emit("  showcount %08x %d" % (r[4] & M32, s32(r[5])))
        return 0

    def clearcount(self, em):
        self.emit("  clearcount %08x" % (em.reg[4] & M32))
        return 0

    def carby_stub(self, em):
        n = s32(em.reg[4])
        self.emit("  carby %d" % n)
        if n < 0 or n > 1 or self.carby[n] < 0:
            return 0
        return self.cars + 64 * self.carby[n]

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
        self.emit("  egs %d %d %d" % (s32(g(self.egs + 32)),
                                      s32(g(self.egs + 36)),
                                      s32(g(self.egs + 48))))
        o = self.screen
        if not o:
            self.emit("  screen none")
            return
        self.emit("  screen %s %08x" % (VTABLES.get(g(o + 4), "?"), g(o)))

    def new_screen(self, fn, h):
        e = self.e
        a = e.alloc(8)
        e.write(a, b"\xcd" * 8)
        self.block_add(a)
        e.call(fn, a, h, 0, limit=5000000)
        self.screen = a

    def vcall(self, slot, *args):
        e = self.e
        fn = e.u32(e.u32(self.screen + 4) + slot)
        e.call(fn, self.screen, *args, limit=5000000)

    def put_text(self, a, text, size):
        raw = text.encode("latin-1")[:size]
        self.e.write(a, raw + bytes(size - len(raw)))

    def put16(self, a, v):
        self.e.write(a, struct.pack("<H", v & 0xffff))

    def op(self, a):
        e = self.e
        o = a[0]
        if o == "player":
            p = self.player(int(a[1], 0))
            e.put32(p + 16, int(a[2], 0) & M32)
            self.put_text(p + 52, a[3][:11] if len(a) > 3 else "", 12)
            return
        if o == "char":
            self.put_text(self.chars + CSTRIDE * int(a[1], 0) + 4,
                          a[2][:31] if len(a) > 2 else "", 32)
            return
        n = [0] + [int(x, 0) for x in a[1:]]
        if o == "gt":
            e.put32(GAME_TYPE, n[1] & M32)
        elif o == "ev":
            self.put16(TRE + 104, n[1])
            self.put16(TRE + 106, n[2])
            self.put16(TRE + 114, n[3])
            e.put32(TRE + 120, n[4] & M32)
            self.put16(TRE + 118, n[5])
            e.put32(TRE + 4, self.state if n[6] else 0)
        elif o == "goal":
            self.put16(TRE + 124, n[1])
            e.put32(TRE + 128, n[2] & M32)
        elif o == "rew":
            r = TRE + 244 + 8 * n[1]
            e.write(r, bytes(x & 0xff for x in n[2:6]))
            e.put32(r + 4, n[6] & M32)
        elif o == "res":
            e.put32(TRE + 336 + 12 * n[1], n[2] & M32)
        elif o == "st":
            e.write(self.state, bytes(x & 0xff for x in n[1:17]))
        elif o == "rp":
            for off, v in zip((12, 32, 36, 40, 628), n[1:6]):
                e.put32(RP + off, v & M32)
        elif o in ("status", "any", "earned", "adv"):
            setattr(self, o, n[1])
        elif o == "ranks":
            self.ranks = n[1:17]
        elif o == "urank":
            self.urank = n[1]
        elif o == "opened":
            self.opened = (n[1], n[2:6])
        elif o == "ts":
            e.put32(TS, n[1] & M32)
        elif o == "row":
            r = TS + 12 + 100 * n[1]
            for off, v in zip((0, 4, 8, 12, 16, 20, 24, 48), n[2:10]):
                e.put32(r + off, v & M32)
        elif o == "drv":
            d = self.drivers + DSTRIDE * n[1]
            e.write(d + 1, struct.pack("<b", n[2]))
            e.put32(d + 8, n[3] & M32)
            e.put32(d + 20, 0 if n[4] < 0 else self.chars + CSTRIDE * n[4])
        elif o == "car":
            c = self.cars + 64 * n[1]
            e.write(c + 10, struct.pack("<h", n[2]))
            e.put32(self.rides + 16 * n[1], n[3] & M32)
            e.put32(c + 20, 0 if n[4] < 0 else self.drivers + DSTRIDE * n[4])
            e.put32(c + 24, 0 if n[5] < 0 else self.player(n[5]))
        elif o == "rc":
            e.put32(self.rcs + 192 * n[1],
                    0 if n[2] < 0 else self.cars + 64 * n[2])
        elif o == "race":
            if n[1] < 0:
                e.put32(P_RACE, 0)
            else:
                e.put32(P_RACE, self.race)
                e.put32(self.race + 24, n[1] & M32)
                for i in range(8):
                    k = n[2 + i]
                    e.put32(self.race + 1572 + 4 * i,
                            0 if k < 0 else self.rcs + 192 * k)
        elif o == "byd":
            self.carby[n[1]] = n[2]
        elif o in ("pbn", "pbi"):
            base = PBN if o == "pbn" else PBI
            e.put32(base, 0 if n[1] < 0 else self.player(n[1]))
            e.put32(base + 4, 0 if n[2] < 0 else self.player(n[2]))
        elif o == "cti":
            e.put32(TRACK_INFO, 0 if n[1] < 0
                    else self.tracks + TSTRIDE * n[1])
        elif o == "egs":
            e.put32(self.egs + 32, n[1] & M32)
            e.put32(self.egs + 36, n[2] & M32)
            e.put32(self.egs + 48, n[3] & M32)
        elif o in ("tourney", "reward", "unlocked", "btc1", "btc2"):
            fn = {"tourney": F_TOURNEY, "reward": F_REWARD,
                  "unlocked": F_UNLOCKED, "btc1": F_BTC1,
                  "btc2": F_BTC2}[o]
            self.new_screen(fn, n[1] & M32)
            self.dump()
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
        elif o == "lang":
            v = e.call(F_LANG, self.dummy, limit=5000000)
            self.emit("  langid %s" % cx(v))
        elif o == "rank":
            v = e.call(F_RANK, self.dummy, 0, limit=5000000)
            self.emit("  userrank %d" % s32(v))
        elif o == "fmt":
            e.write(self.buf, bytes(512))
            e.call(F_FMT, self.dummy, self.buf, n[1] & M32, limit=5000000)
            self.emit("  fmt [%s]" % self.cstr(self.buf, 255))
        else:
            raise ValueError(o)

    def run(self, lines):
        e = self.e
        for line in lines:
            self.emit("> " + line)
            sp = e.reg[29]
            # What retail leaves unwritten on the stack reads as zeros, as
            # the port's empty buffers do.
            e.write((sp - 0x4000) & M32, bytes(0x4000))
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

def build_harness(tmp, name="endevent_test"):
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


def M(name, before, after, rel=EE):
    return (name, rel, before, after)


MUTATIONS = [
    # ---- the constants
    M("h-rows", "#define TOURNEY_ROWS                 8",
      "#define TOURNEY_ROWS                 7", EH),
    M("h-passed", "#define END_EVENT_LANG_PASSED        0xde4a4",
      "#define END_EVENT_LANG_PASSED        0xde4a6", EH),
    M("h-failed", "#define END_EVENT_LANG_FAILED        0xde4a5",
      "#define END_EVENT_LANG_FAILED        0xde4a7", EH),
    M("h-unlocked", "#define END_EVENT_LANG_UNLOCKED      0xde2b6",
      "#define END_EVENT_LANG_UNLOCKED      0xde2b7", EH),
    M("h-g-tb", "#define BTC_GROUP_TIME_BONUS         0x8564c282u",
      "#define BTC_GROUP_TIME_BONUS         0x8564c283u", EH),
    M("h-o-tl", "#define BTC_OBJ_TIME_LEFT            0x761c6807u",
      "#define BTC_OBJ_TIME_LEFT            0x761c6808u", EH),
    M("h-o-tb", "#define BTC_OBJ_TIME_BONUS           0xc8f86ae5u",
      "#define BTC_OBJ_TIME_BONUS           0xc8f86ae6u", EH),
    M("h-o-pts", "#define BTC_OBJ_POINTS               0xd49e65d2u",
      "#define BTC_OBJ_POINTS               0xd49e65d3u", EH),
    M("h-o-earned", "#define BTC_OBJ_POINTS_EARNED        0x98fcdd99u",
      "#define BTC_OBJ_POINTS_EARNED        0x98fcdd9au", EH),
    M("h-o-total", "#define BTC_OBJ_POINTS_TOTAL         0xb8b4361bu",
      "#define BTC_OBJ_POINTS_TOTAL         0xb8b4361cu", EH),
    M("h-g-p1", "#define BTC_GROUP_P1_BLURB           0xfe6b3c76u",
      "#define BTC_GROUP_P1_BLURB           0xfe6b3c77u", EH),
    M("h-g-p2", "#define BTC_GROUP_P2_BLURB           0x4b657937u",
      "#define BTC_GROUP_P2_BLURB           0x4b657938u", EH),
    M("h-o-p1", "#define BTC_OBJ_P1_POINTS            0x89e0e2dbu",
      "#define BTC_OBJ_P1_POINTS            0x89e0e2ddu", EH),
    M("h-o-p2", "#define BTC_OBJ_P2_POINTS            0x89e0e2dcu",
      "#define BTC_OBJ_P2_POINTS            0x89e0e2deu", EH),
    M("h-bonus", "#define BTC_TIME_BONUS_PER_SECOND    100",
      "#define BTC_TIME_BONUS_PER_SECOND    10", EH),
    M("c-pool", "#define END_EVENT_POOL 16", "#define END_EVENT_POOL 15"),
    M("c-flag-eu", "#define EVENTS_UNLOCKED_SPEECH_SAID(s) ((s)->Zeroed[2])",
      "#define EVENTS_UNLOCKED_SPEECH_SAID(s) ((s)->Zeroed[1])"),
    M("c-flag-rw", "#define EVENT_REWARD_SPEECH_SAID(s)    ((s)->Zeroed[3])",
      "#define EVENT_REWARD_SPEECH_SAID(s)    ((s)->Zeroed[4])"),
    M("c-flag-ts", "#define TOURNEY_SPEECH_SAID(s)         ((s)->Zeroed[6])",
      "#define TOURNEY_SPEECH_SAID(s)         ((s)->Zeroed[5])"),
    M("c-gt-ch", "#define GAME_TYPE_CHAMPIONSHIP   8",
      "#define GAME_TYPE_CHAMPIONSHIP   7"),
    M("c-gt-ur", "#define GAME_TYPE_ULTIMATE_RACER 9",
      "#define GAME_TYPE_ULTIMATE_RACER 10"),
    M("c-tt", "#define RACE_TYPE_TIME_TRIAL 2", "#define RACE_TYPE_TIME_TRIAL 3"),
    M("c-notime", "#define NO_TIME 0x7fffffffu", "#define NO_TIME 0x7ffffffeu"),
    M("c-goal-place", "#define GOAL_PLACE 1", "#define GOAL_PLACE 0"),
    M("c-goal-time", "#define GOAL_TIME  2", "#define GOAL_TIME  3"),
    M("c-last", "#define EVENT_TREE_LAST  30", "#define EVENT_TREE_LAST  29"),
    M("c-bonus", "#define EVENT_TREE_BONUS 31", "#define EVENT_TREE_BONUS 33"),
    M("c-completed", "#define BTC_REASON_COMPLETED 1",
      "#define BTC_REASON_COMPLETED 2"),
    M("c-won", "#define BTC_REASON_WON       4", "#define BTC_REASON_WON       3"),
    M("c-lost", "#define BTC_REASON_LOST      5",
      "#define BTC_REASON_LOST      6"),
] + [
    M("c-" + name, "#define %-22s 0x%x" % (name, v),
      "#define %-22s 0x%x" % (name, v + 0x100))
    for name, v in (("LANG_LAP_FAILED", 0xe09c0), ("LANG_LAP_UNLOCKED", 0xe09c1),
                    ("LANG_TOTAL_FAILED", 0xe09c2),
                    ("LANG_TOTAL_UNLOCKED", 0xe09c3),
                    ("LANG_COP_UNLOCKED", 0xe09c4), ("LANG_COP_FAILED", 0xe09c5),
                    ("LANG_LAP_PASSED", 0xe09c6), ("LANG_TOTAL_PASSED", 0xe09c7),
                    ("LANG_FIRST_UNLOCKED", 0xe30d0),
                    ("LANG_SECOND_UNLOCKED", 0xe30d1),
                    ("LANG_THIRD_UNLOCKED", 0xe30d2),
                    ("LANG_PLACE_FAILED", 0xe30d3),
                    ("LANG_PASSED_UNLOCKED", 0xe30d4),
                    ("LANG_CHAMPION", 0xe30d5), ("LANG_ROAD_RACER", 0xe30d6),
                    ("LANG_FIRST", 0xe30da), ("LANG_SECOND", 0xe30db),
                    ("LANG_THIRD", 0xe30dc), ("LANG_PASSED", 0xe30dd),
                    ("LANG_HP_CHAMPION", 0xe32c4), ("LANG_BONUS_ULTIMATE", 0xe32c6),
                    ("LANG_TRACK", 0xe09bf), ("LANG_BTC_COP_WON", 0xecd1c),
                    ("LANG_BTC_SPEEDER_LOST", 0xecd1f),
                    ("LANG_BTC_COP_LOST", 0xecd1d),
                    ("LANG_BTC_SPEEDER_WON", 0xecd1e),
                    ("LANG_BTC_COP_TIME_UP", 0xecd25),
                    ("LANG_BTC_SPEEDER_TIME_UP", 0xecd26))
] + [
    M("c-LANG_BONUS_CHAMPIONSHIP", "#define LANG_BONUS_CHAMPIONSHIP 0xe32c5",
      "#define LANG_BONUS_CHAMPIONSHIP 0xe33c5"),
    M("c-place-tab", "0xee48, 0xee49, 0xee4a,", "0xee48, 0xee59, 0xee4a,"),
    M("c-place-0", "    0xee48, 0xee49", "    0xee47, 0xee49"),
    M("c-ch-tab", "0, 0xde2b0, 0xde2b4, 0xde2b1,", "0, 0xde2b0, 0xde2b1, 0xde2b4,"),
    M("c-ch-1", "0, 0xde2b0, 0xde2b4", "0, 0xde2b8, 0xde2b4"),
    M("c-ur-tab", "0, 0xde2b2, 0xde2b5, 0xde2b3,", "0, 0xde2b2, 0xde2b3, 0xde2b5,"),
    M("c-ur-1", "0, 0xde2b2, 0xde2b5", "0, 0xde2b9, 0xde2b5"),
    # ---- the seams
    M("s-trs", "return t != NULL ? t : s;", "return t != NULL ? t : \"\";"),
    M("s-short", "get_translated_string(ct->pCarSpecs->FullName);",
      "get_translated_string(ct->pCarSpecs->FullName + 1);"),
    M("s-noname", "    if (d->pCharacterInfo == NULL)\n        return \"\";",
      "    if (d->pCharacterInfo == NULL)\n        return \"?\";"),
    M("s-name", "return d->pCharacterInfo->CharacterName;",
      "return d->pCharacterInfo->CharacterName + 1;"),
    M("s-hash", "return bchunk_hash(buf);", "return bchunk_hash(fmt);"),
    M("s-rid", "render_text_into_group(screen, group, get_translated_string(id));",
      "render_text_into_group(screen, group, get_translated_string(id + 1));"),
    M("s-track-null", "get_the_right_track_language_id(t, dir) : 0;",
      "get_the_right_track_language_id(t, dir) : 1;"),
    M("s-norow", "return e != NULL ? e : &kNoRow;",
      "return e != NULL ? e : &Fred.TransientStatsTable.Stats[1];"),
    M("s-pc-1", "return n == 0 || n == 1 ? &PlayerTextColors[n]",
      "return n == 0 ? &PlayerTextColors[n]"),
    M("s-pc-def", ": &DefaultTextColor;\n}", ": &PlayerTextColors[0];\n}"),
    # ---- the destructors
    M("d-ts", "m->vt = &kTourneyStandingsVTable;\n    endgame_menus_base_destroy(m, flags);",
      "m->vt = &kTourneyStandingsVTable;\n    endgame_menus_base_destroy(m, flags & 2);"),
    M("d-rw", "m->vt = &kEventRewardVTable;\n    endgame_menus_base_destroy(m, flags);",
      "m->vt = &kEventRewardVTable;\n    endgame_menus_base_destroy(m, flags & 2);"),
    M("d-eu", "m->vt = &kEventsUnlockedVTable;\n    endgame_menus_base_destroy(m, flags);",
      "m->vt = &kEventsUnlockedVTable;\n    endgame_menus_base_destroy(m, flags & 2);"),
    M("d-b1", "m->vt = &kBTCResults1PVTable;\n    endgame_menus_base_destroy(m, flags);",
      "m->vt = &kBTCResults1PVTable;\n    endgame_menus_base_destroy(m, flags & 2);"),
    M("d-b2", "m->vt = &kBTCResults2PVTable;\n    endgame_menus_base_destroy(m, flags);",
      "m->vt = &kBTCResults2PVTable;\n    endgame_menus_base_destroy(m, flags & 2);"),
    # ---- the tourney standings
    M("t-order", "<= ((const TourneyPoints *)(void *)b)->Rank;",
      ">= ((const TourneyPoints *)(void *)b)->Rank;"),
    M("t-strict", "<= ((const TourneyPoints *)(void *)b)->Rank;",
      "< ((const TourneyPoints *)(void *)b)->Rank;"),
    M("t-pos", "\"POS_%d\"", "\"POS%d\""),
    M("t-name", "\"NAME_%d\"", "\"NAME%d\""),
    M("t-type", "\"TYPE_%d\"", "\"TYPE%d\""),
    M("t-race", "\"RACE_%d\"", "\"RACE%d\""),
    M("t-total", "\"TOTAL_%d\"", "\"TOTAL%d\""),
    M("t-vis-pos", "flailer_set_visibility(hash, r->Pos, v);",
      "flailer_set_visibility(hash, r->Name, v);"),
    M("t-vis-total", "flailer_set_visibility(hash, r->Total, v);",
      "flailer_set_visibility(hash, r->Race, v);"),
    M("t-place-i", "return i >= 0 && i < 8 ? TheRaceEvent.aResults[i].nPosition",
      "return i >= 0 && i < 8 ? TheRaceEvent.aResults[i ^ 1].nPosition"),
    M("t-row-n", "    tourney_row(&r, k + 1);\n    if (k >= pCurrentRace",
      "    tourney_row(&r, k);\n    if (k >= pCurrentRace"),
    M("t-row-vis", "tourney_row_visibility(hash, &r, FLAILER_OBJECT_VISIBLE);",
      "tourney_row_visibility(hash, &r, FLAILER_OBJECT_INVISIBLE);"),
    M("t-ride", "ct = cartypeinfo_get(car->pRideInfo->Type);",
      "ct = cartypeinfo_get(car->pRideInfo->Type + 1);"),
    M("t-place", "place = event_place(d->UniqueDriverNumber);",
      "place = event_place(d->UniqueDriverNumber + 1);"),
    M("t-player", "if (d->TheDriverType == DRIVER_TYPE_PLAYER) {",
      "if (d->TheDriverType != DRIVER_TYPE_PLAYER) {"),
    M("t-carby", "world_get_car_by_driver_number(d->UniqueDriverNumber);",
      "world_get_car_by_driver_number(0);"),
    M("t-pname", "? pc->pPlayer->PlayerSettings.PlayerName : \"\");",
      "? pc->pPlayer->PlayerSettings.PlayerName + 1 : \"\");"),
    M("t-ainame", "flailer_printf(hash, r.Name, \"%s\", driver_info_get_name(d));",
      "flailer_printf(hash, r.Type, \"%s\", driver_info_get_name(d));"),
    M("t-posfmt", "flailer_printf(hash, r.Pos, \"%2d\", (int)(k + 1));",
      "flailer_printf(hash, r.Pos, \"%d\", (int)(k + 1));"),
    M("t-posk", "flailer_printf(hash, r.Pos, \"%2d\", (int)(k + 1));",
      "flailer_printf(hash, r.Pos, \"%2d\", (int)k);"),
    M("t-typename", "car_type_info_get_short_name(ct)));",
      "car_type_info_get_short_name(cartypeinfo_get(0))));"),
    M("t-dnf", "    if (place != 0)\n        flailer_printf(hash, r.Race",
      "    if (place > 0)\n        flailer_printf(hash, r.Race"),
    M("t-pts", "tournament_state_points_for_finish_pos(\n                           place - 1)",
      "tournament_state_points_for_finish_pos(\n                           place)"),
    M("t-dnf-text", "r.Race, \"DNF\");", "r.Race, \"DNF \");"),
    M("t-total-pts", "\"%d\", (int)tp->Points);", "\"%d\", (int)tp->Rank);"),
    M("t-getplayer", "p = racingcar_get_player(tp->Car);", "p = NULL;"),
    M("t-color", "color = player_color(p->PlayerNumber);",
      "color = player_color(0);"),
    M("t-said", "if (TOURNEY_SPEECH_SAID(s) == 0) {",
      "if (TOURNEY_SPEECH_SAID(s) != 0) {"),
    M("t-said-set", "TOURNEY_SPEECH_SAID(s) = 1;", "TOURNEY_SPEECH_SAID(s) = 2;"),
    M("t-said-null", "s = pEndGameScreens;\n        if (s != NULL) {",
      "s = NULL;\n        if (s != NULL) {"),
    M("t-tsp-f", "tournament_race_speech(st == EVENT_FAILED",
      "tournament_race_speech(st == EVENT_INPROGRESS"),
    M("t-tsp-p", "|| st == EVENT_PASSED, k);", "|| st == EVENT_UNTRIED, k);"),
    M("t-tsp-k", "|| st == EVENT_PASSED, k);", "|| st == EVENT_PASSED, k + 1);"),
    M("t-col-pos", "flailer_set_object_color(hash, r.Pos, color);",
      "flailer_set_object_color(hash, r.Pos, &DefaultTextColor);"),
    M("t-col-name", "flailer_set_object_color(hash, r.Name, color);",
      "flailer_set_object_color(hash, r.Pos, color);"),
    M("t-col-type", "flailer_set_object_color(hash, r.Type, color);",
      "flailer_set_object_color(hash, r.Name, color);"),
    M("t-col-race", "flailer_set_object_color(hash, r.Race, color);",
      "flailer_set_object_color(hash, r.Type, color);"),
    M("t-col-total", "flailer_set_object_color(hash, r.Total, color);",
      "flailer_set_object_color(hash, r.Race, color);"),
    M("t-n-cap", "? r->NumRacingCars : RACE_MAX_RACING_CARS;",
      "? r->NumRacingCars : RACE_MAX_RACING_CARS - 1;"),
    M("t-ridx", "rc->pCar->DriverNumber);", "rc->pCar->DriverNumber + 1);"),
    M("t-st-pts", "points = st[idx];", "points = st[idx + 1];"),
    M("t-st-rank", "rank = tournament_state_racer_rank(st, idx);",
      "rank = tournament_state_racer_rank(st, idx + 1);"),
    M("t-malloc", "\"TourneyPoints\", 0, END_EVENT_POOL",
      "\"TourneyPoint\", 0, END_EVENT_POOL"),
    M("t-tp-pts", "tp->Points = points;", "tp->Points = rank;"),
    M("t-tp-rank", "tp->Rank = rank;", "tp->Rank = points;"),
    M("t-tp-car", "tp->Car = rc;", "tp->Car = r->pRacingCars[0];"),
    M("t-vt", "m->vt = &kTourneyStandingsVTable;\n    set_track",
      "m->vt = &kEventRewardVTable;\n    set_track"),
    M("t-track", "RACE_RESULTS_OBJ_RACE_NUMBER, 0);",
      "RACE_RESULTS_OBJ_RACE_NUMBER, 1);"),
    M("t-use", "if (!fred_use_the_race_event(&Fred)",
      "if (fred_use_the_race_event(&Fred)"),
    M("t-ev-type", "|| TheRaceEvent.nType != EVENT_TOURNAMENT)",
      "|| TheRaceEvent.nType != EVENT_TOURNAMENT + 1)"),
    M("t-sort", "blist_sort(&list, tourney_in_order);", "(void)0;"),
    M("t-fill", "for (; k < TOURNEY_ROWS; k++) {",
      "for (; k < TOURNEY_ROWS - 1; k++) {"),
    M("t-fill-n", "        tourney_row(&r, k + 1);\n        tourney_row_visibility",
      "        tourney_row(&r, k);\n        tourney_row_visibility"),
    M("t-fill-vis", "tourney_row_visibility(m->ScreenHash, &r, FLAILER_OBJECT_INVISIBLE);",
      "tourney_row_visibility(m->ScreenHash, &r, FLAILER_OBJECT_VISIBLE);"),
    M("t-free", "        bFree(node);", "        (void)node;"),
    # ---- the player's place and the blurb's id
    M("u-type", "if (ev->nType == EVENT_TOURNAMENT) {\n        const uint8_t *s",
      "if (ev->nType != EVENT_TOURNAMENT) {\n        const uint8_t *s"),
    M("u-row", "return driver_row(driver)->FinishPosition;",
      "return driver_row(driver + 1)->FinishPosition;"),
    M("u-field", "return driver_row(driver)->FinishPosition;",
      "return driver_row(driver)->FinishReason;"),
    M("b-none", "    return 0;\n}\n\nint32_t event_reward_lang_id",
      "    return 1;\n}\n\nint32_t event_reward_lang_id"),
    M("l-passed", "int32_t passed = raceevent_get_status(ev) == EVENT_PASSED;",
      "int32_t passed = raceevent_get_status(ev) != EVENT_FAILED;"),
    M("l-timed0", "int32_t timed = t != 0 && t != NO_TIME;",
      "int32_t timed = t != 1 && t != NO_TIME;"),
    M("l-earned", "int32_t earned = raceevent_any_reward_earned(ev);\n"
      "    int32_t passed",
      "int32_t earned = !raceevent_any_reward_earned(ev);\n"
      "    int32_t passed"),
    M("l-last", "if (ev->nNumber == EVENT_TREE_LAST && passed)",
      "if (ev->nNumber == EVENT_TREE_LAST && !passed)"),
    M("l-ult", "if (ev->nNumber == EVENT_ULTIMATE && passed)",
      "if (ev->nNumber == EVENT_ULTIMATE && !passed)"),
    M("l-bonus", "if (ev->nNumber == EVENT_TREE_BONUS && passed)",
      "if (ev->nNumber == EVENT_TREE_BONUS && !passed)"),
    M("l-champ", "return by_tree(LANG_CHAMPION, LANG_ROAD_RACER);",
      "return by_tree(LANG_ROAD_RACER, LANG_CHAMPION);"),
    M("l-bonus-tree",
      "return by_tree(LANG_BONUS_CHAMPIONSHIP, LANG_BONUS_ULTIMATE);",
      "return by_tree(LANG_BONUS_ULTIMATE, LANG_BONUS_CHAMPIONSHIP);"),
    M("l-tt", "if (rp->RaceType == RACE_TYPE_TIME_TRIAL && timed",
      "if (rp->RaceType != RACE_TYPE_TIME_TRIAL && timed"),
    M("l-tt-timed", "RACE_TYPE_TIME_TRIAL && timed && rp->BeACop == 0) {",
      "RACE_TYPE_TIME_TRIAL && rp->BeACop == 0) {"),
    M("l-tt-cop", "RACE_TYPE_TIME_TRIAL && timed && rp->BeACop == 0) {",
      "RACE_TYPE_TIME_TRIAL && timed && rp->BeACop != 0) {"),
    M("l-lapf", "return LANG_LAP_FAILED;", "return LANG_TOTAL_FAILED;"),
    M("l-lapu", "return earned ? LANG_LAP_UNLOCKED : LANG_LAP_PASSED;",
      "return earned ? LANG_LAP_PASSED : LANG_LAP_UNLOCKED;"),
    M("l-p2p", "if (rp->Point2Point != 0 && timed",
      "if (rp->Point2Point == 0 && timed"),
    M("l-p2p-timed", "if (rp->Point2Point != 0 && timed",
      "if (rp->Point2Point != 0 && 1"),
    M("l-p2p-cop", "timed && rp->BeACop == 0\n",
      "timed && rp->BeACop != 0\n"),
    M("l-totf", "return LANG_TOTAL_FAILED;", "return LANG_LAP_FAILED;"),
    M("l-totu", "return earned ? LANG_TOTAL_UNLOCKED : LANG_TOTAL_PASSED;",
      "return earned ? LANG_TOTAL_PASSED : LANG_TOTAL_UNLOCKED;"),
    M("l-cop", "if (rp->BeACop != 0)\n        return passed",
      "if (rp->BeACop == 0)\n        return passed"),
    M("l-cop-pass", "return passed ? LANG_COP_UNLOCKED : LANG_COP_FAILED;",
      "return passed ? LANG_COP_FAILED : LANG_COP_UNLOCKED;"),
    M("l-plf", "if (!passed)\n        return LANG_PLACE_FAILED;",
      "if (passed)\n        return LANG_PLACE_FAILED;"),
    M("l-case1", "    case 1:\n        return earned ? LANG_FIRST_UNLOCKED",
      "    case 4:\n        return earned ? LANG_FIRST_UNLOCKED"),
    M("l-1", "return earned ? LANG_FIRST_UNLOCKED : LANG_FIRST;",
      "return earned ? LANG_FIRST : LANG_FIRST_UNLOCKED;"),
    M("l-case2", "    case 2:\n        return earned ? LANG_SECOND_UNLOCKED",
      "    case 5:\n        return earned ? LANG_SECOND_UNLOCKED"),
    M("l-2", "return earned ? LANG_SECOND_UNLOCKED : LANG_SECOND;",
      "return earned ? LANG_SECOND : LANG_SECOND_UNLOCKED;"),
    M("l-case3", "    case 3:\n        return earned ? LANG_THIRD_UNLOCKED",
      "    case 6:\n        return earned ? LANG_THIRD_UNLOCKED"),
    M("l-3", "return earned ? LANG_THIRD_UNLOCKED : LANG_THIRD;",
      "return earned ? LANG_THIRD : LANG_THIRD_UNLOCKED;"),
    M("l-def", "return earned ? LANG_PASSED_UNLOCKED : LANG_PASSED;",
      "return earned ? LANG_PASSED : LANG_PASSED_UNLOCKED;"),
    # ---- the blurb
    M("f-first", "const EventReward *rw = &ev->aRewards[0];",
      "const EventReward *rw = &ev->aRewards[1];"),
    M("f-best", "end_game_print_timer(best, row->BestLapTime, 0);",
      "end_game_print_timer(best, row->RaceTime, 0);"),
    M("f-goal", "if (ev->Objective.nType == GOAL_TIME) {",
      "if (ev->Objective.nType != GOAL_TIME) {"),
    M("f-target", "t.PackedTime = ev->Objective.nData;",
      "t.PackedTime = ev->Objective.nData + 1;"),
    M("f-target-empty", "memset(target, 0, sizeof target);",
      "strcpy(target, \"-\");"),
    M("f-total", "end_game_print_timer(total, row->RaceTime, 0);",
      "end_game_print_timer(total, row->RaceTime, 1);"),
    M("f-place", "place_name(event_reward_user_rank(0))",
      "place_name(event_reward_user_rank(0) + 1)"),
    M("f-place-size", "b_snprintf(place, sizeof place, \"%s\",",
      "b_snprintf(place, sizeof place - 12, \"%s\","),
    M("f-needed", "ev->Objective.nType == GOAL_PLACE",
      "ev->Objective.nType != GOAL_PLACE"),
    M("f-needed-data", "? (int32_t)ev->Objective.nData : 0)));",
      "? (int32_t)ev->Objective.nData : 1)));"),
    M("f-rw-car", "if (rw->nType == REWARD_CAR) {", "if (rw->nType != REWARD_CAR) {"),
    M("f-rw-cv", "cartypeinfo_get(rw->nValue1))));",
      "cartypeinfo_get(rw->nValue2))));"),
    M("f-rw-track", "} else if (rw->nType == REWARD_TRACK) {",
      "} else if (rw->nType == REWARD_TRACK + 1) {"),
    M("f-rw-tv", "track_get_info(rw->nValue1), rw->nValue2));",
      "track_get_info(rw->nValue2), rw->nValue1));"),
    M("f-rw-fmt", "\"%s %s\", name, track);", "\"%s%s\", name, track);"),
    M("f-rw-clear", "    reward[0] = 0;\n", "    strcpy(reward, \"-\");\n"),
    M("f-lapf", "fmt, best, target);", "fmt, target, best);"),
    M("f-lapu", "fmt, best, reward);", "fmt, reward, best);"),
    M("f-totf", "fmt, total, target);", "fmt, target, total);"),
    M("f-totu", "fmt, total, reward);", "fmt, best, reward);"),
    M("f-reward", "b_snprintf(out, 256, fmt, reward);",
      "b_snprintf(out, 256, fmt, best);"),
    M("f-lapp", "fmt, best);", "fmt, total);"),
    M("f-totp", "fmt, total);", "fmt, best);"),
    M("f-plf", "fmt, place, needed);", "fmt, needed, place);"),
    M("f-def", "        b_snprintf(out, 256, fmt);",
      "        b_snprintf(out, 256, \"%s\", \"-\");"),
    M("f-case-cop", "    case LANG_COP_UNLOCKED:\n    case LANG_FIRST_UNLOCKED:",
      "    case LANG_FIRST_UNLOCKED:"),
    M("f-case-pu", "    case LANG_PASSED_UNLOCKED:\n        b_snprintf",
      "        b_snprintf"),
    # ---- the reward screen
    M("r-st", "if (raceevent_get_status(ev) != EVENT_PASSED\n",
      "if (raceevent_get_status(ev) == EVENT_PASSED\n"),
    M("r-ult", "|| ev->nNumber == EVENT_ULTIMATE\n",
      "|| ev->nNumber != EVENT_ULTIMATE\n"),
    M("r-bonus", "(ev->nNumber == EVENT_TREE_BONUS && ev->bIsLastOpen == 0))",
      "(ev->nNumber == EVENT_TREE_BONUS && ev->bIsLastOpen != 0))"),
    M("r-player", "struct Player *p = PlayerPlayersByNumber[0];",
      "struct Player *p = PlayerPlayersByIndex[0];"),
    M("r-row", "race_event_speech(p, transient_stats_get_driver(\n"
      "                                 &Fred.TransientStatsTable, 0));",
      "race_event_speech(p, transient_stats_get_driver(\n"
      "                                 &Fred.TransientStatsTable, 1));"),
    M("r-won", "race_event_reward_speech(p, earned,",
      "race_event_reward_speech(p, !earned,"),
    M("r-rw", "ev->nRewards > 0\n                                     ?",
      "ev->nRewards > 1\n                                     ?"),
    M("r-vt", "m->vt = &kEventRewardVTable;\n    earned",
      "m->vt = &kEventsUnlockedVTable;\n    earned"),
    M("r-any", "earned = raceevent_any_reward_earned(ev);\n    s =",
      "earned = 1;\n    (void)raceevent_any_reward_earned(ev);\n    s ="),
    M("r-said", "if (EVENT_REWARD_SPEECH_SAID(s) == 0)",
      "if (EVENT_REWARD_SPEECH_SAID(s) != 0)"),
    M("r-said-set", "EVENT_REWARD_SPEECH_SAID(s) = 1;",
      "EVENT_REWARD_SPEECH_SAID(s) = 0;"),
    M("r-grp", "END_REWARD_GROUP_BLURB, buf);\n    flailer_printf",
      "END_REWARD_GROUP_BLURB + 1, buf);\n    flailer_printf"),
    M("r-title", "? END_EVENT_LANG_PASSED : END_EVENT_LANG_FAILED),",
      "? END_EVENT_LANG_FAILED : END_EVENT_LANG_PASSED),"),
    M("r-title-obj", "flailer_printf(m->ScreenHash, END_REWARD_OBJ_TITLE,",
      "flailer_printf(m->ScreenHash, END_REWARD_OBJ_TITLE + 1,"),
    M("r-title-st", "raceevent_get_status(ev) == EVENT_PASSED\n"
      "                           ? END_EVENT_LANG_PASSED",
      "raceevent_get_status(ev) != EVENT_PASSED\n"
      "                           ? END_EVENT_LANG_PASSED"),
    M("r-num", "(int)ev->nNumber);", "(int)ev->nNumber + 1);"),
    M("r-cnt-n", "if (ev->nRewards > 0 && ev->aRewards[0].nType == REWARD_CAR",
      "if (ev->nRewards > 1 && ev->aRewards[0].nType == REWARD_CAR"),
    M("r-cnt-car", "ev->aRewards[0].nType == REWARD_CAR\n",
      "ev->aRewards[0].nType != REWARD_CAR\n"),
    M("r-cnt-adv", "&& raceevent_status_advanced(ev)\n",
      "&& !raceevent_status_advanced(ev)\n"),
    M("r-cnt-earned", "raceevent_reward_earned(ev, 0, NULL))",
      "raceevent_reward_earned(ev, 1, NULL))"),
    M("r-cnt-cop", "end_reward_show_car_count(m->ScreenHash, 0);",
      "end_reward_show_car_count(m->ScreenHash, 1);"),
    M("r-clear", "    else\n        end_reward_clear_car_count(m->ScreenHash);",
      "    else\n        (void)0;"),
    # ---- events unlocked
    M("e-vt", "m->vt = &kEventsUnlockedVTable;\n    memset",
      "m->vt = &kBTCResults1PVTable;\n    memset"),
    M("e-status", "    (void)raceevent_get_status(&TheRaceEvent);\n", "\n"),
    M("e-max", "out, 8, &TheRaceEvent);", "out, 7, &TheRaceEvent);"),
    M("e-ch", "if (Fred.GameType == GAME_TYPE_CHAMPIONSHIP) {\n        if (n > 3)",
      "if (Fred.GameType == GAME_TYPE_CHAMPIONSHIP + 2) {\n        if (n > 3)"),
    M("e-cap-ch", "if (n > 3)\n            n = 3;\n        id = n >= 0 ? kChampionshipUnlocked",
      "if (n > 2)\n            n = 2;\n        id = n >= 0 ? kChampionshipUnlocked"),
    M("e-ur", "} else if (Fred.GameType == GAME_TYPE_ULTIMATE_RACER) {",
      "} else if (Fred.GameType == GAME_TYPE_ULTIMATE_RACER + 2) {"),
    M("e-cap-ur", "if (n > 3)\n            n = 3;\n        id = n >= 0 ? kUltimateRacerUnlocked",
      "if (n > 4)\n            n = 4;\n        id = n >= 0 ? kUltimateRacerUnlocked"),
    M("e-ft1", "(int)out[0]);\n        // fall through",
      "(int)out[0]);\n        break;"),
    M("e-c3", "(int)out[1], (int)out[2]);\n        break;",
      "(int)out[2], (int)out[1]);\n        break;"),
    M("e-c1", "    case 1:\n        b_snprintf(buf",
      "    case 4:\n        b_snprintf(buf"),
    M("e-buf", "    buf[0] = 0;\n    (void)raceevent", "    strcpy(buf, \"-\");\n    (void)raceevent"),
    M("e-grp", "END_REWARD_GROUP_BLURB, buf);\n    flailer_set_language_id",
      "END_REWARD_GROUP_BLURB + 1, buf);\n    flailer_set_language_id"),
    M("e-title", "flailer_set_language_id(m->ScreenHash, END_REWARD_OBJ_TITLE,",
      "flailer_set_language_id(m->ScreenHash, END_REWARD_OBJ_TITLE + 1,"),
    M("e-said", "if (s != NULL && EVENTS_UNLOCKED_SPEECH_SAID(s) == 0) {",
      "if (s != NULL && EVENTS_UNLOCKED_SPEECH_SAID(s) != 0) {"),
    M("e-said-set", "EVENTS_UNLOCKED_SPEECH_SAID(s) = 1;",
      "EVENTS_UNLOCKED_SPEECH_SAID(s) = 2;"),
    M("e-player", "race_event_speech(PlayerPlayersByIndex[0],",
      "race_event_speech(PlayerPlayersByNumber[0],"),
    M("e-row", "&Fred.TransientStatsTable, 0));\n        EVENTS_UNLOCKED",
      "&Fred.TransientStatsTable, 1));\n        EVENTS_UNLOCKED"),
    M("e-clear", "    }\n    end_reward_clear_car_count(m->ScreenHash);\n    return m;",
      "    }\n    return m;"),
    # ---- You're The Cop
    M("y-dir", "TheRaceParameters.TrackDirection));",
      "TheRaceParameters.TrackDirection + 1));"),
    M("y-obj", "flailer_set_language_id(hash, RACE_RESULTS_OBJ_TRACK_NAME,",
      "flailer_set_language_id(hash, RACE_RESULTS_OBJ_RACE_NUMBER,"),
    M("y-track", "CurrentTrackInfo,\n", "track_get_info(0),\n"),
    M("y1-vt", "m->vt = &kBTCResults1PVTable;\n    show",
      "m->vt = &kBTCResults2PVTable;\n    show"),
    M("y1-row", "    row = driver_row(0);", "    row = driver_row(1);"),
    M("y1-won", "if (row->FinishReason == BTC_REASON_WON) {",
      "if (row->FinishReason >= BTC_REASON_WON) {"),
    M("y1-gvis", "FLAILER_OBJECT_VISIBLE);\n        flailer_printf(m->ScreenHash, BTC_OBJ_TIME_LEFT",
      "FLAILER_OBJECT_INVISIBLE);\n        flailer_printf(m->ScreenHash, BTC_OBJ_TIME_LEFT"),
    M("y1-left", "(int)ee_trunc_w(row->BeACopTime));",
      "(int)ee_trunc_w(row->BeACopTime + 0.5f));"),
    M("y1-left-cvt", "(int)ee_trunc_w(row->BeACopTime));",
      "(int)(row->BeACopTime > 0 ? row->BeACopTime : 0));"),
    M("y1-bonus", "bonus = (int32_t)((uint32_t)ee_trunc_w(row->BeACopTime)",
      "bonus = (int32_t)((uint32_t)ee_trunc_w(row->BeACopTime + 1.0f)"),
    M("y1-bonus-p", "BTC_OBJ_TIME_BONUS, \"%d\", (int)bonus);",
      "BTC_OBJ_TIME_BONUS, \"%d\", (int)bonus / 2);"),
    M("y1-ginv", "FLAILER_OBJECT_INVISIBLE);\n    }\n    flailer_printf",
      "FLAILER_OBJECT_VISIBLE);\n    }\n    flailer_printf"),
    M("y1-pts", "(int)row->PointsThisRace);\n    flailer_printf(m->ScreenHash, BTC_OBJ_POINTS_EARNED",
      "(int)row->PointsTotal);\n    flailer_printf(m->ScreenHash, BTC_OBJ_POINTS_EARNED"),
    M("y1-earned", "+ (uint32_t)bonus));", "- (uint32_t)bonus));"),
    M("y1-total", "(int)row->PointsTotal);\n    return m;",
      "(int)row->PointsThisRace);\n    return m;"),
    M("y2-vt", "m->vt = &kBTCResults2PVTable;\n    h =",
      "m->vt = &kBTCResults1PVTable;\n    h ="),
    M("y2-a", "    a = driver_row(0);", "    a = driver_row(5);"),
    M("y2-b", "    b = driver_row(1);", "    b = driver_row(0);"),
    M("y2-won", "if (a->FinishReason == BTC_REASON_WON\n",
      "if (a->FinishReason != BTC_REASON_WON\n"),
    M("y2-won-b", "&& b->FinishReason == BTC_REASON_LOST) {",
      "&& b->FinishReason != BTC_REASON_WON) {"),
    M("y2-cw", "BTC_GROUP_P1_BLURB, LANG_BTC_COP_WON);",
      "BTC_GROUP_P2_BLURB, LANG_BTC_COP_WON);"),
    M("y2-sl", "BTC_GROUP_P2_BLURB, LANG_BTC_SPEEDER_LOST);",
      "BTC_GROUP_P2_BLURB, LANG_BTC_SPEEDER_WON);"),
    M("y2-lost", "} else if (a->FinishReason == BTC_REASON_LOST) {",
      "} else if (a->FinishReason == BTC_REASON_COMPLETED) {"),
    M("y2-comp", "if (b->FinishReason == BTC_REASON_COMPLETED\n",
      "if (b->FinishReason == BTC_REASON_COMPLETED + 1\n"),
    M("y2-bwon", "|| b->FinishReason == BTC_REASON_WON) {",
      "|| b->FinishReason == BTC_REASON_LOST) {"),
    M("y2-cl", "BTC_GROUP_P1_BLURB, LANG_BTC_COP_LOST);",
      "BTC_GROUP_P1_BLURB, LANG_BTC_COP_TIME_UP);"),
    M("y2-sw", "LANG_BTC_SPEEDER_WON);", "LANG_BTC_SPEEDER_TIME_UP);"),
    M("y2-blost", "} else if (b->FinishReason == BTC_REASON_LOST) {",
      "} else if (b->FinishReason == BTC_REASON_WON) {"),
    M("y2-tu1", "BTC_GROUP_P1_BLURB,\n                                 LANG_BTC_COP_TIME_UP);",
      "BTC_GROUP_P2_BLURB,\n                                 LANG_BTC_COP_TIME_UP);"),
    M("y2-tu2", "BTC_GROUP_P2_BLURB,\n                                 LANG_BTC_SPEEDER_TIME_UP);",
      "BTC_GROUP_P1_BLURB,\n                                 LANG_BTC_SPEEDER_TIME_UP);"),
    M("y2-p1", "BTC_OBJ_P1_POINTS, \"%d\", (int)a->PointsThisRace);",
      "BTC_OBJ_P1_POINTS, \"%d\", (int)b->PointsThisRace);"),
    M("y2-p2", "BTC_OBJ_P2_POINTS, \"%d\", (int)b->PointsThisRace);",
      "BTC_OBJ_P2_POINTS, \"%d\", (int)a->PointsTotal);"),
]

# Mutations that cannot change what the script sees, and why.
EQUIVALENT = {
    "t-strict": "only a tie tells < from <=, and on a tie retail's sort "
                "never ends, so the script has none",
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
        todo, SOURCES, "endevent_test",
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
