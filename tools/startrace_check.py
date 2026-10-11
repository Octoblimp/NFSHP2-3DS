#!/usr/bin/env python3
"""Cross-check 3DS Files/source/startrace.c, the screens over the fly-by
before a race, against the retail image, SLES_507.31.

**The model** is retail's own PRERACE_STATS module run in
retail_model.RetailEmu: tStartRaceScreenManager's NeedToSee tests,
AddScreen, Enable and Disable, the three free functions on
TheStartRaceScreenManager (0x0031a3e0), RaceKnockoutInfoShouldBeDisplayed,
TournamentStandingsShouldBeDisplayed, PreRaceStats' BuildStats trio,
GetStatsForRacePosition, constructor, destructor, HandleEvent and
Callback, and PreRaceLetterboxCallback; and under them the track select's
GetTheRightTrackLanguageID and 0x001dc5d8, SprintfAndHash with the real
bStringHash, FrontendDatabase's UseTheRaceEvent and IsMultiTrack,
RaceEvent's RacerIndexFromDriverNumber and GetKoState,
RaceParameters::GetDriverInfo, DriverInfo::GetName and
CarTypeInfo::GetShortName. The colours are what the two files' static
initialisers (_GLOBAL_$I$pEndGameScreens and _GLOBAL_$I$PRERACE_STATS)
leave, run with FlailerScreenConfig's constructor stubbed. The harness
(tools/src/startrace_test.c) runs startrace.c.

**The stubs** print what they are asked, on both sides: ChangeToScreen,
RaceCoordinator::PostMessage, the four Flailer calls (FlailerPrintf
formats its line), both GetTranslatedStrings, GetCarByDriverNumber,
RaceEvent's GetRaceIndex, GetRaceCount and GetTournamentState, bMalloc and
__builtin_delete. bSPrintf formats natively. bMalloc's block starts as
0xcd bytes, so what the constructor leaves shows.

**The script** asks the tests over every game type, event type and
RaceParameters mix; enables the screens for each race kind, over a manager
with old screens in it; builds the grid for plain races, knockouts (game
type 4, and 8 and 9 on a knockout event) and tournaments, with players,
AI with and without a character, positions off the grid and doubled, both
track directions and a third, multi-track events whose race number runs
past the count, and missing strings; sends the grid and the letterbox
every message, BACK over each manager shape and SELECT from A and from
START with and without a coordinator; then random races.

    python tools/startrace_check.py
    python tools/startrace_check.py --mutate [--only a,b]
    python tools/startrace_check.py --dump out/startrace
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

HARNESS = "tools/src/startrace_test.c"
STR = "3DS Files/source/startrace.c"
FREDRACE_H = "3DS Files/source/fredrace.h"
SOURCES = [HARNESS, STR]
HARNESS_TIMEOUT = 60

GP = retail_model.RETAIL_GP
FRED = 0x002fc050
GAME_TYPE = FRED + 0x1072c
RP = 0x0031a898
RACE_EVENT = 0x0031b600
MGR = 0x0031a3e0
PINSTANCE = GP - 17428
P_CURRENT_RACE = GP - 22272
P_RACE_COORD = GP - 22216
CURRENT_TRACK = GP - 21952
CAR_TYPE_INFOS = GP - 20616
SCREEN_NAMES = [0, GP - 17444, GP - 17440, GP - 17436, GP - 17432]

F_NEED_OBJ, F_NEED_2P, F_NEED_STATS = 0x001e27b8, 0x001e27e8, 0x001e2810
F_ADD = 0x001e2848
F_KO, F_TOUR = 0x001e2920, 0x001e2980
F_GETPOS = 0x001e2d00
F_CALLBACK, F_LETTERBOX = 0x001e31d8, 0x001e3968
F_ENABLE, F_DISABLE, F_READY = 0x001e39b0, 0x001e39c0, 0x001e39d0
F_TRACK_NAME = 0x001dc5d8

S_CHANGE = 0x0014cc78
S_POST = 0x001496d8
S_VIS, S_LANG, S_COLOR, S_PRINTF = 0x00144968, 0x001449a8, 0x001449e8, \
    0x00143e70
S_TR, S_TRS = 0x0021e560, 0x0021e508
S_CAR = 0x0014d5d0
S_RACE_INDEX, S_RACE_COUNT, S_TOUR_STATE = 0x00202010, 0x00202088, \
    0x00201880
S_SPRINTF = 0x00251398
S_SCREEN_CONFIG = 0x0016ad88
B_MALLOC, B_DELETE = 0x002577c0, 0x00114e98
NOT_TRANSLATED = 0x002bc958

SCREEN_STATS = 0x89b2fc0f
SCREEN_LETTERBOX = 0xa3e1bc36
LANG_RACE_OF = 0x3a983

MAX_TYPES = 64


def cx(v):
    """C's %#x: 0 has no 0x."""
    v &= M32
    return "%#x" % v if v else "0"


# ================================================================== script

def stats(m, item=0, port=0, param=0x5a, noise=0x5b):
    return "stats|%d|%#x|%d|%d|%d" % (m, item, port, param, noise)


def letter(m, item=0, port=0, param=0x5a, noise=0x5b):
    return "letter|%d|%#x|%d|%d|%d" % (m, item, port, param, noise)


def drv(i, unique, start, typ, ride, char, elim=0):
    return "drv|%d|%d|%d|%d|%d|%d|%d" % (i, unique, start, typ, ride, char,
                                         elim)


def race(*d):
    return "race|%d|" % len(d) + "|".join(str(x) for x in d) if d \
        else "race|0"


def rp(direction=0, rtype=0, cars=1, obj=0, cop=0):
    return "rp|%d|%d|%d|%d|%d" % (direction, rtype, cars, obj, cop)


ACT = stats(11, SCREEN_STATS)
UNACT = stats(12, SCREEN_STATS)


def grid():
    """A grid's life: up, dumped, looked up, down."""
    s = [ACT, "dump"]
    s += ["getpos|%d" % p for p in (1, 4, 8, 9, 0, -1)]
    s += [UNACT, "dump"]
    return s


def script():
    s = []
    s += ["chr|0|Hunter", "chr|1|Mara", "chr|2|Rook", "chr|3|Vega",
          "chr|4|Dax", "chr|5|Lola", "chr|6|Kai", "chr|7|Nix",
          "player|0|0|ANDREW", "player|1|1|SECOND", "pset|0|PSONE",
          "pset|1|PSTWO", "track|0x3a000|0x3a001", "rc|1"]
    s += ["dump", "ready", "need", "kod"]

    # The tests over every game type and event type.
    for g in range(-1, 12):
        s += ["game|%d" % g]
        for ev in (0, 2, 3, 4, 5, -3):
            s += ["event|%d|2" % ev, "kod"]
        s += ["need"]
    # NeedToSee over RaceParameters.
    for cop in (0, 1, 5):
        for cars in (0, 1, 2, 3):
            for obj in (0, 1, 7):
                s += [rp(0, 0, cars, obj, cop)]
                for g in (6, 3):
                    s += ["game|%d" % g, "need"]

    # Enable for each race kind.
    for g, r in ((2, rp()), (2, rp(obj=1)), (7, rp(cars=1, cop=1)),
                 (7, rp(cars=2, cop=1)), (7, rp(cars=3, cop=1)),
                 (7, rp(cars=2, obj=1, cop=1)), (6, rp()), (6, rp(obj=1)),
                 (6, rp(cars=0, cop=1)), (3, rp(obj=-1))):
        s += ["game|%d" % g, r, "enable", "dump", "ready", "disable",
              "dump"]
    # Over a manager with old screens: 2 and 3 stay, the count and the
    # current go back.
    s += ["mgr|4|3|1|2|3|4", "game|2", rp(), "enable", "dump", "ready"]
    s += ["mgr|3|2|4|4|1|2", "game|6", rp(), "enable", "dump", "ready"]
    s += ["mgr|2|1|2|1|0|0", "ready", "mgr|2|0|2|1|0|0", "ready",
          "mgr|0|-1|0|0|0|0", "ready", "mgr|1|0|1|0|0|0", "ready"]
    # AddScreen to four and past it.
    s += ["mgr|0|0|0|0|0|0"]
    for k in (2, 1, 3, 4, 1):
        s += ["add|%d" % k, "dump"]
    s += ["mgr|3|1|4|4|4|0", "add|2", "dump", "add|3", "dump",
          "mgr|7|0|1|1|1|1", "add|2", "dump"]

    # A plain race: a player, AI with and without a character, a cop.
    s += ["game|2", rp(0, 0, 1, 0, 0), "event|0|1", "trs|0",
          drv(0, 0, 3, 1, 12, -1), drv(1, 100, 1, 0, 5, 1),
          drv(2, 101, 2, 0, 7, -1), drv(3, 102, 4, 2, 40, 2),
          drv(4, 103, 5, 0, 63, 3), drv(5, 104, 6, 0, 0, 4),
          race(0, 1, 2, 3, 4, 5)]
    s += grid()
    # Reversed, a third direction, and both strings through the X.
    s += [rp(1), "trs|1"] + grid()
    s += [rp(2), "trs|0"] + grid()
    # Two players, eight cars.
    s += [rp(0, 0, 2), drv(6, 1, 7, 1, 33, 5), drv(7, 105, 8, 0, 21, 6),
          race(0, 1, 2, 3, 4, 5, 6, 7)] + grid()
    # Positions off the grid and doubled; nobody at 1.
    s += [drv(1, 100, 0, 0, 5, 1), drv(2, 101, 9, 0, 7, -1),
          drv(3, 102, 4, 2, 40, 2), drv(4, 103, -1, 0, 63, 3),
          race(1, 2, 3, 4, 5)] + grid()
    s += [race()] + grid()
    s += [race(5)] + grid()
    # A missing car name and a missing "Race of".
    s += ["miss|0x40000", drv(5, 104, 2, 0, 0, 4),
          drv(1, 100, 1, 0, 9, 7), race(1, 5)] + grid()

    # Multi-track: game type 4 runs off the event. RaceType 4 and 5 are
    # multi-track, the race's number plus 1 held to the count.
    s += [drv(1, 100, 1, 0, 5, 1), drv(2, 101, 2, 0, 7, -1),
          drv(0, 0, 3, 1, 12, -1), race(0, 1, 2), "ndrv|0"]
    for g, rt, idx, cnt in ((4, 4, 0, 3), (4, 5, 2, 3), (4, 4, 3, 3),
                            (4, 4, 5, 2), (4, 6, 0, 3), (4, 3, 0, 3),
                            (2, 4, 0, 3), (8, 4, 1, 4), (9, 5, -2, 4),
                            (8, 3, 0, 4), (7, 4, 0, 4), (10, 4, 0, 4)):
        s += ["game|%d" % g, rp(0, rt), "ridx|%d" % idx,
              "rcount|%d" % cnt, ACT, "dump", UNACT]
    s += ["game|4", rp(0, 4), "ridx|0", "rcount|3", "miss|0x3a983", ACT,
          UNACT]
    for add in (0, 1, 5, -3):
        for rt in (4, 0):
            s += [rp(1, rt), "ridx|1", "rcount|2",
                  "tname|0x1234|0x55|0x66|%d" % add]

    # The knockout: the race's cars racing, then the ones out, in red at
    # the place they went out in. A player out has its PlayerSettings'
    # name.
    s += ["game|4", rp(0, 0, 2), "event|0|2", "ridx|0", "rcount|1",
          drv(0, 0, 2, 1, 12, -1), drv(1, 100, 1, 0, 5, 1),
          drv(2, 101, 3, 0, 7, -1), drv(3, 1, 0, 1, 33, -1, 6),
          drv(4, 102, 0, 0, 40, 2, 5), drv(5, 103, 0, 0, 41, -1, 4),
          drv(6, 104, 0, 0, 42, 3, -2), drv(7, 105, 0, 2, 43, 4, 7),
          "ndrv|8", race(0, 1, 2)]
    s += grid()
    for g, ev in ((8, 3), (9, 3), (8, 4), (4, 4), (9, 2)):
        s += ["game|%d" % g, "event|%d|2" % ev, "tour|9|8|7|6|5|4|3|2|1"]
        s += grid()
    # The tournament: each racer's points by RacerIndexFromDriverNumber.
    s += ["game|8", "event|4|2", "ndrv|0",
          "tour|10|20|30|40|50|60|70|80|90|100|110|120|130|140|150|200|255",
          drv(0, 0, 1, 1, 12, -1), drv(1, 100, 2, 0, 5, 1),
          drv(2, 101, 3, 0, 7, -1), drv(3, 1, 4, 1, 33, 2),
          drv(4, 105, 5, 0, 40, 3), drv(5, 7, 6, 0, 41, 4),
          race(0, 1, 2, 3, 4, 5)]
    s += grid()
    s += ["event|4|0"] + grid()
    s += ["game|9", "event|4|3", rp(1, 5, 2), "ridx|2", "rcount|5"]
    s += grid()

    # Previous: shown with a screen before the grid.
    for r in (rp(obj=1), rp(cars=2, cop=1), rp(cars=1, cop=1),
              rp(cars=3, cop=1, obj=1)):
        s += ["game|2", "event|0|1", r, ACT, UNACT]

    # Messages with the grid up and without.
    s += ["game|2", rp(), race(0, 1, 2), ACT]
    for m in (2, 3, 4, 5, 6, 7, 8, 9, 10, 13, 14, 15, 16, 18, 19, 20, 0):
        s += [stats(m, 0x1111)]
    for param in (0, 5, 6, 7, 8, -1):
        s += [stats(1, 0x2222, 0, param)]
    s += ["rc|0", stats(1, 0x2222, 1, 0), stats(1, 0x2222, 1, 7), "rc|1"]
    # BACK over each manager shape.
    for mgr in ("mgr|2|1|2|1|0|0", "mgr|2|0|2|1|0|0", "mgr|1|0|1|0|0|0",
                "mgr|3|2|2|3|1|0", "mgr|2|1|1|1|0|0", "mgr|4|3|0|2|3|1",
                "mgr|2|1|0|1|0|0", "mgr|4|2|4|4|1|3"):
        s += [mgr, stats(17, 0x3333, 0, 9, 9), "dump"]
    s += [UNACT, "dump"]
    s += [stats(8), stats(17), stats(1), stats(12), "dump"]
    # Up twice, another screen's hash, then down.
    s += [stats(11, 0xdeadbeef), stats(11, SCREEN_STATS), "dump", UNACT,
          UNACT, "dump", stats(11, 0xdeadbeef), "dump", UNACT]

    # The letterbox.
    for m in (0, 1, 2, 4, 6, 7, 8, 9, 10, 11, 12, 13, 17, 18, 19):
        for param in (0, 7):
            s += [letter(m, SCREEN_LETTERBOX, 0, param)]
    s += ["rc|0", letter(1), letter(17), letter(8), "rc|1"]

    s += random_races(random.Random(0x5717), 120)
    return s


def random_races(rnd, n):
    s = []
    for _ in range(n):
        g = rnd.choice((0, 1, 2, 3, 4, 4, 5, 6, 7, 8, 8, 9, 9, 10))
        ev = rnd.choice((0, 2, 3, 3, 4, 4, 5))
        s += ["game|%d" % g, "event|%d|%d" % (ev, rnd.randint(0, 4)),
              rp(rnd.randint(0, 2), rnd.choice((0, 3, 4, 5, 6)),
                 rnd.randint(0, 3), rnd.choice((0, 0, 1)),
                 rnd.choice((0, 0, 0, 1))),
              "ridx|%d" % rnd.randint(-1, 6), "rcount|%d" % rnd.randint(0, 6),
              "trs|%d" % rnd.randint(0, 1)]
        ko = g == 4 or (g in (8, 9) and ev == 3)
        cars = rnd.randint(0, 8)
        drivers = []
        for i in range(16):
            typ = rnd.choice((0, 0, 0, 1, 2))
            if typ == 1:
                unique = rnd.randint(0, 1)
            else:
                unique = rnd.choice((rnd.randint(0, 31),
                                     rnd.randint(100, 115)))
            drivers.append([i, unique, rnd.randint(-1, 9), typ,
                            rnd.randint(0, MAX_TYPES - 1),
                            rnd.randint(-1, 7), 0])
        nd = rnd.randint(0, 16)
        room = 8 - cars
        for d in drivers[:nd]:
            if rnd.random() < 0.35:
                d[6] = rnd.randint(-3, 9)
                if d[6] > 0:
                    if ko and room <= 0:
                        d[6] = 0
                    else:
                        room -= 1
        s += [drv(*d) for d in drivers]
        s += ["ndrv|%d" % nd,
              race(*rnd.sample(range(16), cars)),
              "tour|" + "|".join(str(rnd.randint(0, 255)) for _ in range(24))]
        s += [ACT, "dump", "getpos|%d" % rnd.randint(0, 9)]
        for _ in range(rnd.randint(0, 3)):
            s += [stats(rnd.choice((1, 8, 9, 17, 6)), 0x4444, 0,
                        rnd.choice((0, 7, 5)))]
        s += [UNACT]
        if rnd.random() < 0.3:
            s += ["enable", "dump", "ready", "disable"]
    return s


# =================================================================== model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        e.stub_bware()
        e.stub(S_SCREEN_CONFIG, lambda em: em.reg[4] & M32)
        e.run_ctors(r"\$(pEndGameScreens|PRERACE_STATS)$")
        self.screen_ptr = [0] + [e.u32(a) for a in SCREEN_NAMES[1:]]

        self.race = e.alloc(2048)
        self.rcars = e.alloc(8 * 16)
        self.cars = e.alloc(8 * 32)
        self.drivers = e.alloc(16 * 24)
        self.chars = e.alloc(8 * 48)
        self.track = e.alloc(128)
        self.ctinfo = e.alloc(MAX_TYPES * 1376)
        self.specs = e.alloc(MAX_TYPES * 32)
        self.pcars = e.alloc(8 * 32)
        self.players = e.alloc(8 * 64)
        self.rc = e.alloc(16)
        self.tour = e.alloc(32)
        self.data = e.alloc(16)
        for blk, n in ((self.race, 2048), (self.drivers, 16 * 24),
                       (self.chars, 8 * 48), (self.players, 8 * 64),
                       (self.tour, 32)):
            e.write(blk, bytes(n))
        for i in range(MAX_TYPES):
            e.put32(self.ctinfo + i * 1376 + 1368, self.specs + i * 32)
            e.put32(self.specs + i * 32 + 20, 0x40000 + i)
        for i in range(8):
            e.put32(self.race + 1572 + 4 * i, self.rcars + 16 * i)
            e.put32(self.rcars + 16 * i, self.cars + 32 * i)
            e.put32(self.pcars + 32 * i + 24, self.players + 64 * i)
        e.put32(P_CURRENT_RACE, self.race)
        e.put32(P_RACE_COORD, self.rc)
        e.put32(CURRENT_TRACK, self.track)
        e.put32(CAR_TYPE_INFOS, self.ctinfo)
        e.put32(PINSTANCE, 0)
        e.write(MGR, bytes(24))
        e.put32(GAME_TYPE, 0)
        for off in (12, 32, 48, 80, 628, 776):
            e.put32(RP + off, 0)
        e.put32(RP + 772, self.drivers)
        for i in range(2):
            e.write(RP + 652 + 48 * i + 20, bytes(12))
        e.write(RACE_EVENT + 106, bytes(2))
        e.write(RACE_EVENT + 118, bytes(2))

        self.player_unique = []
        self.race_index = self.race_count = 0
        self.missing = set()
        self.trs_mode = 0
        self.strings = {}
        self.last_malloc = 0

        for a, fn in ((S_CHANGE, self.change), (S_POST, self.post),
                      (S_VIS, self.vis), (S_LANG, self.lang),
                      (S_COLOR, self.color), (S_PRINTF, self.printf),
                      (S_TR, self.tr), (S_TRS, self.trs), (S_CAR, self.car),
                      (S_RACE_INDEX, self.say_ret("  raceidx", "race_index")),
                      (S_RACE_COUNT, self.say_ret("  racecount",
                                                  "race_count")),
                      (S_TOUR_STATE, self.tour_state),
                      (S_SPRINTF, self.sprintf),
                      (B_MALLOC, self.malloc), (B_DELETE, self.delete)):
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

    def format(self, fmt, args):
        out = []
        i = k = 0
        while i < len(fmt):
            c = fmt[i]
            if c != "%":
                out.append(c)
                i += 1
                continue
            j = i + 1
            width = ""
            while fmt[j].isdigit():
                width += fmt[j]
                j += 1
            conv = fmt[j]
            if conv == "d":
                v = str(s32(args[k]))
                k += 1
            elif conv == "s":
                v = self.cstr(args[k] & M32)
                k += 1
            elif conv == "%":
                v = "%"
            else:
                raise ValueError(fmt)
            out.append(v.rjust(int(width)) if width else v)
            i = j + 1
        return "".join(out)

    # ---- the stubs

    def change(self, em):
        a = em.reg[4] & M32
        self.emit("  change %s %d" % (self.cstr(a) if a else "NULL",
                                      s32(em.reg[5])))
        return 0

    def post(self, em):
        r = em.reg
        self.emit("  post %d %d %d" % (1 if r[4] & M32 else 0, s32(r[5]),
                                       s32(r[6])))
        return 0

    def vis(self, em):
        r = em.reg
        self.emit("  vis %08x %08x %d" % (r[4] & M32, r[5] & M32,
                                          s32(r[6])))
        return 0

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

    def printf(self, em):
        r = em.reg
        text = self.format(self.cstr(r[6] & M32), [r[7], r[8], r[9], r[10]])
        self.emit("  printf %08x %08x [%s]" % (r[4] & M32, r[5] & M32,
                                               text[:127]))
        return len(text)

    def sprintf(self, em):
        r = em.reg
        text = self.format(self.cstr(r[5] & M32), [r[6], r[7], r[8]])
        raw = text.encode("latin-1") + b"\0"
        self.e.write(r[4] & M32, raw)
        return len(text)

    def tr(self, em):
        i = s32(em.reg[4])
        self.emit("  tr %s" % cx(i))
        if i & M32 in self.missing:
            return NOT_TRANSLATED
        if i == LANG_RACE_OF:
            return self.string("R%d/%d")
        return self.string("T%x" % (i & M32))

    def trs(self, em):
        a = em.reg[4] & M32
        t = self.cstr(a)
        self.emit("  trs %s" % t)
        if self.trs_mode == 0:
            return a
        return self.string("X" + t)

    def car(self, em):
        n = s32(em.reg[4])
        self.emit("  car %d" % n)
        if n in self.player_unique:
            return self.pcars + 32 * self.player_unique.index(n)
        return 0

    def say_ret(self, line, attr):
        def stub(em):
            self.emit(line)
            return getattr(self, attr) & M32
        return stub

    def tour_state(self, em):
        self.emit("  tourstate")
        return self.tour

    def malloc(self, em):
        r = em.reg
        size = s32(r[4])
        a = self.e.alloc(size)
        self.e.write(a, b"\xcd" * size)
        self.emit("  malloc %s %d %d %d" % (self.cstr(r[5] & M32), size,
                                            s32(r[6]), s32(r[7])))
        self.last_malloc = a
        return a

    def delete(self, em):
        a = em.reg[4] & M32
        self.emit("  free %d" % (1 if a and a == self.last_malloc else 0))
        if a == self.last_malloc:
            self.last_malloc = 0
        return 0

    # ---- ops

    def dump(self):
        g = self.e.u32
        names = []
        for i in range(4):
            p = g(MGR + 4 * i)
            names.append(self.cstr(p) if p else "NULL")
        self.emit("  mgr %d %d [%s] [%s] [%s] [%s]" % (
            (s32(g(MGR + 16)), s32(g(MGR + 20))) + tuple(names)))
        b = g(PINSTANCE)
        if not b:
            self.emit("  inst 0")
            return
        self.emit("  inst 1 %08x" % g(b))
        for i in range(8):
            ln = b + 16 + 48 * i
            p = g(ln + 4)
            self.emit("  line %d %d [%s] %d %s %d %08x %08x %08x %08x" % (
                (i, s32(g(ln)), self.cstr(p) if p else "NULL",
                 s32(g(ln + 8)), cx(g(ln + 12)), s32(g(ln + 16)))
                + tuple(g(ln + 32 + 4 * k) for k in range(4))))

    def callback(self, fn, n):
        e = self.e
        d = self.data
        for i in range(4):
            e.put32(d + 4 * i, n[2 + i] & M32)
        e.call(fn, n[1], d, limit=2000000)
        self.emit("  data %d %d" % (s32(e.u32(d + 8)), s32(e.u32(d + 12))))

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
        if o == "pset":
            self.put_name(RP + 652 + 48 * int(a[1]) + 20, a[2], 12)
            return
        n = [int(x, 0) for x in a[1:]]
        n = [0] + n
        if o == "rp":
            for off, v in zip((12, 32, 48, 80, 628), n[1:6]):
                e.put32(RP + off, v & M32)
        elif o == "game":
            e.put32(GAME_TYPE, n[1] & M32)
        elif o == "event":
            e.write(RACE_EVENT + 106, struct.pack("<h", n[1]))
            e.write(RACE_EVENT + 118, struct.pack("<h", n[2]))
        elif o == "track":
            e.put32(self.track + 72, n[1] & M32)
            e.put32(self.track + 76, n[2] & M32)
        elif o == "ridx":
            self.race_index = n[1]
        elif o == "rcount":
            self.race_count = n[1]
        elif o == "tour":
            raw = bytes(v & 0xff for v in n[1:])
            e.write(self.tour, raw + bytes(32 - len(raw)))
        elif o == "miss":
            self.missing.add(n[1] & M32)
        elif o == "trs":
            self.trs_mode = n[1]
        elif o == "rc":
            e.put32(P_RACE_COORD, self.rc if n[1] else 0)
        elif o == "drv":
            d = self.drivers + 24 * n[1]
            e.write(d, struct.pack("<bb", n[7], n[2]))
            e.write(d + 4, struct.pack("<b", n[3]))
            e.put32(d + 8, n[4] & M32)
            e.put32(d + 12, n[5] & M32)
            e.put32(d + 20, 0 if n[6] < 0 else self.chars + 48 * n[6])
        elif o == "ndrv":
            e.put32(RP + 776, n[1] & M32)
        elif o == "race":
            e.put32(self.race + 24, n[1] & M32)
            for i, dn in enumerate(n[2:]):
                e.put32(self.cars + 32 * i + 20, self.drivers + 24 * dn)
        elif o == "mgr":
            e.put32(MGR + 16, n[1] & M32)
            e.put32(MGR + 20, n[2] & M32)
            for i in range(4):
                e.put32(MGR + 4 * i, self.screen_ptr[n[3 + i]])
        elif o == "add":
            e.call(F_ADD, MGR, self.screen_ptr[n[1]])
        elif o == "enable":
            e.call(F_ENABLE, limit=200000)
        elif o == "disable":
            e.call(F_DISABLE, limit=200000)
        elif o == "ready":
            self.emit("  ready %d" % e.call(F_READY))
        elif o == "need":
            self.emit("  need %d %d %d" % tuple(
                e.call(f, MGR) for f in (F_NEED_OBJ, F_NEED_2P,
                                         F_NEED_STATS)))
        elif o == "kod":
            self.emit("  kod %d %d" % (e.call(F_KO), e.call(F_TOUR)))
        elif o == "tname":
            e.call(F_TRACK_NAME, n[1], n[2], n[3], n[4], limit=200000)
        elif o == "getpos":
            b = e.u32(PINSTANCE)
            v = e.call(F_GETPOS, b, n[1]) & M32
            self.emit("  getpos %d" % (-1 if v == 0
                                       else (v - b - 16) // 48))
        elif o == "stats":
            self.callback(F_CALLBACK, n)
        elif o == "letter":
            self.callback(F_LETTERBOX, n)
        elif o == "dump":
            self.dump()
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

def build_harness(tmp, name="startrace_test"):
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


def M(name, before, after, rel=STR):
    return (name, rel, before, after)


MUTATIONS = [
    # The names, which Enable stores and BACK compares.
    M("name-stats", '"Pre Race Stats";', '"Pre Race Stat";'),
    M("name-blurb", '"Pre Race Blurb";', '"Pre Race Blurp";'),
    M("name-2p", '"Pre Race 2P Be A Cop";', '"Pre Race 2P Be a Cop";'),
    M("name-letter", '"Pre Race Letterbox";', '"Pre Race letterbox";'),

    # The colours.
    M("col-p0", "{ 134.0f, 96.0f, 48.0f, 128.0f },",
      "{ 134.0f, 96.0f, 47.0f, 128.0f },"),
    M("col-p1", "{ 0.0f, 128.0f, 0.0f, 128.0f },",
      "{ 0.0f, 127.0f, 0.0f, 128.0f },"),
    M("col-def", "DefaultTextColor = { 128.0f, 128.0f, 128.0f, 128.0f };",
      "DefaultTextColor = { 128.0f, 128.0f, 127.0f, 128.0f };"),
    M("col-ko", "PreRaceKnockoutColor = { 128.0f, 0.0f, 0.0f, 128.0f };",
      "PreRaceKnockoutColor = { 128.0f, 0.0f, 0.0f, 127.0f };"),

    # The helpers.
    M("ch-push", "gChangeToScreenFn(name, push);",
      "gChangeToScreenFn(name, 1);"),
    M("tr-none", 'return s != NULL ? s : "NOT TRANSLATED PROPERLY";',
      'return s != NULL ? s : "";'),
    M("trs-none", "return t != NULL ? t : s;", 'return t != NULL ? t : "";'),
    M("short-name", "get_translated_string(ct->pCarSpecs->FullName);",
      "get_translated_string(ct->pCarSpecs->FullName + 1);"),
    M("name-nochar", "if (d->pCharacterInfo == NULL)" + NL
      + '        return "";',
      "if (d->pCharacterInfo == NULL)" + NL + '        return "?";'),
    M("hash-n", "snprintf(buf, sizeof buf, fmt, (int)n);",
      "snprintf(buf, sizeof buf, fmt, (int)n + 1);"),
    M("rcount", "gRaceEventGetRaceCountFn() : 0;",
      "gRaceEventGetRaceCountFn() + 1 : 0;"),
    M("ridx", "gRaceEventGetRaceIndexFn() : 0;",
      "gRaceEventGetRaceIndexFn() + 1 : 0;"),
    M("rifdn-lt", "if (n < 100)" + NL + "        return n;",
      "if (n <= 100)" + NL + "        return n;"),
    M("rifdn-off", "return TheRaceEvent.nInitialPlayers + n - 100;",
      "return TheRaceEvent.nInitialPlayers + n - 101;"),
    M("rifdn-np", "return TheRaceEvent.nInitialPlayers + n - 100;",
      "return n - 100;"),

    # The NeedToSee tests.
    M("obj-cop", "    if (TheRaceParameters.BeACop)" + NL
      + "        return TheRaceParameters.NumPlayerCars == 1;",
      "    if (!TheRaceParameters.BeACop)" + NL
      + "        return TheRaceParameters.NumPlayerCars == 1;"),
    M("obj-one", "return TheRaceParameters.NumPlayerCars == 1;",
      "return TheRaceParameters.NumPlayerCars >= 1;"),
    M("obj-has", "return TheRaceParameters.HasObjective;",
      "return TheRaceParameters.HasObjective != 0;"),
    M("obj-has0", "return TheRaceParameters.HasObjective;", "return 0;"),
    M("2p-cop", "    if (!TheRaceParameters.BeACop)" + NL
      + "        return 0;", "    if (0)" + NL + "        return 0;"),
    M("2p-two", "NumPlayerCars == 2;", "NumPlayerCars >= 2;"),
    M("stats-cop", "    if (TheRaceParameters.BeACop)" + NL
      + "        return 0;" + NL + "    return Fred.GameType",
      "    if (0)" + NL + "        return 0;" + NL + "    return Fred.GameType"),
    M("stats-free", "return Fred.GameType != FRED_CHALLENGE_GAME_FREE_RUN;",
      "return Fred.GameType != FRED_CHALLENGE_GAME_FREE_RUN + 1;"),

    # AddScreen.
    M("add-max", "if (m->NumScreens < STARTRACE_MAX_SCREENS)",
      "if (m->NumScreens <= STARTRACE_MAX_SCREENS)"),
    M("add-max3", "if (m->NumScreens < STARTRACE_MAX_SCREENS)",
      "if (m->NumScreens < STARTRACE_MAX_SCREENS - 1)"),
    M("add-inc", "m->Screens[m->NumScreens++] = name;",
      "m->Screens[m->NumScreens] = name;"),

    # Enable.
    M("en-num", "    m->NumScreens = 0;" + NL + "    m->CurrentScreen = 0;",
      "    m->CurrentScreen = 0;"),
    M("en-cur", "    m->CurrentScreen = 0;" + NL + "    m->Screens[0] = NULL;",
      "    m->Screens[0] = NULL;"),
    M("en-s0", "    m->Screens[0] = NULL;" + NL, ""),
    M("en-s1", "    m->Screens[1] = NULL;" + NL, ""),
    M("en-s2", "    m->Screens[1] = NULL;" + NL,
      "    m->Screens[1] = NULL;" + NL + "    m->Screens[2] = NULL;" + NL),
    M("en-obj", "start_race_add_screen(m, kPreRaceBlurbScreen);",
      "start_race_add_screen(m, kPreRaceStatsScreen);"),
    M("en-2p", "start_race_add_screen(m, kPreRace2PBeACopScreen);",
      "start_race_add_screen(m, kPreRaceBlurbScreen);"),
    M("en-stats", "    if (start_race_need_to_see_pre_race_stats(m))" + NL
      + "        start_race_add_screen(m, kPreRaceStatsScreen);" + NL, ""),
    M("en-order", "    if (start_race_need_to_see_objective(m))" + NL
      + "        start_race_add_screen(m, kPreRaceBlurbScreen);" + NL
      + "    if (start_race_need_to_see_2p_be_a_cop(m))" + NL
      + "        start_race_add_screen(m, kPreRace2PBeACopScreen);" + NL
      + "    if (start_race_need_to_see_pre_race_stats(m))" + NL
      + "        start_race_add_screen(m, kPreRaceStatsScreen);" + NL,
      "    if (start_race_need_to_see_pre_race_stats(m))" + NL
      + "        start_race_add_screen(m, kPreRaceStatsScreen);" + NL
      + "    if (start_race_need_to_see_objective(m))" + NL
      + "        start_race_add_screen(m, kPreRaceBlurbScreen);" + NL
      + "    if (start_race_need_to_see_2p_be_a_cop(m))" + NL
      + "        start_race_add_screen(m, kPreRace2PBeACopScreen);" + NL),
    M("en-zero", "if (m->NumScreens == 0)", "if (m->NumScreens <= 1)"),
    M("en-letter", "start_race_add_screen(m, kPreRaceLetterboxScreen);",
      "start_race_add_screen(m, kPreRaceStatsScreen);"),
    M("en-push", "change_to_screen(m->Screens[m->CurrentScreen], 1);",
      "change_to_screen(m->Screens[m->CurrentScreen], 0);"),
    M("en-last", "change_to_screen(m->Screens[m->CurrentScreen], 1);",
      "change_to_screen(m->Screens[m->NumScreens - 1], 1);"),

    # Disable and the ready test.
    M("dis-push", "change_to_screen(NULL, 0);", "change_to_screen(NULL, 1);"),
    M("dis-gone", "    change_to_screen(NULL, 0);" + NL, ""),
    M("dis-name", "change_to_screen(NULL, 0);",
      "change_to_screen(kPreRaceStatsScreen, 0);"),
    M("ready-off", "return m->CurrentScreen == m->NumScreens - 1;",
      "return m->CurrentScreen == m->NumScreens;"),
    M("ready-ge", "return m->CurrentScreen == m->NumScreens - 1;",
      "return m->CurrentScreen >= m->NumScreens - 1;"),

    # The track's name.
    M("lang-fwd", "return t->TrackLanguageID;",
      "return t->ReverseTrackLanguageID;"),
    M("lang-rev", "return t->ReverseTrackLanguageID;" + NL + "    return 0;",
      "return t->TrackLanguageID;" + NL + "    return 0;"),
    M("lang-other", "    return 0;" + NL + "}" + NL + NL
      + "void set_track_name", "    return t->TrackLanguageID;" + NL + "}"
      + NL + NL + "void set_track_name"),
    M("lang-dir", "if (dir == TRACK_DIRECTION_BACKWARD)",
      "if (dir != TRACK_DIRECTION_FORWARD)"),
    M("tn-obj", "flailer_set_language_id(screen, trackObj,",
      "flailer_set_language_id(screen, raceObj,"),
    M("tn-dir", "TheRaceParameters.TrackDirection));",
      "TRACK_DIRECTION_FORWARD));"),
    M("tn-use", "if (fred_use_the_race_event(&Fred) && fred_is_multi_track(&Fred)) {",
      "if (fred_is_multi_track(&Fred)) {"),
    M("tn-multi", "if (fred_use_the_race_event(&Fred) && fred_is_multi_track(&Fred)) {",
      "if (fred_use_the_race_event(&Fred)) {"),
    M("tn-add", "race_event_get_race_index() + add;",
      "race_event_get_race_index();"),
    M("tn-clamp", "if (count < race)", "if (count > race)"),
    M("tn-clamp-gone", "        if (count < race)" + NL
      + "            race = count;" + NL, ""),
    M("tn-lang", "get_translated_string(STARTRACE_LANG_RACE_OF),",
      "get_translated_string(STARTRACE_LANG_RACE_OF + 1),"),
    M("tn-args", "(int)race, (int)count);", "(int)count, (int)race);"),
    M("tn-obj2", "flailer_printf(screen, raceObj,",
      "flailer_printf(screen, trackObj,"),
    M("tn-vis", "flailer_set_visibility(screen, raceObj, FLAILER_OBJECT_VISIBLE);",
      "flailer_set_visibility(screen, raceObj, FLAILER_OBJECT_INVISIBLE);"),
    M("tn-invis", "flailer_set_visibility(screen, raceObj, FLAILER_OBJECT_INVISIBLE);",
      "flailer_set_visibility(screen, raceObj, FLAILER_OBJECT_VISIBLE);"),
    M("mt-lo", "return t < 6 && t >= 4;", "return t < 6 && t >= 3;",
      FREDRACE_H),
    M("mt-hi", "return t < 6 && t >= 4;", "return t < 7 && t >= 4;",
      FREDRACE_H),

    # The knockout's and the tournament's tests.
    M("ko-type", "if (t == FRED_CHALLENGE_GAME_KNOCKOUT)",
      "if (t == FRED_CHALLENGE_GAME_KNOCKOUT + 1)"),
    M("ko-ult", "    if (t != FRED_ULTIMATE_GAME && t != FRED_HOTPURSUIT_GAME)"
      + NL + "        return 0;" + NL
      + "    return TheRaceEvent.nType == RACE_EVENT_KNOCKOUT;",
      "    if (t != FRED_HOTPURSUIT_GAME)" + NL + "        return 0;" + NL
      + "    return TheRaceEvent.nType == RACE_EVENT_KNOCKOUT;"),
    M("ko-hp", "    if (t != FRED_ULTIMATE_GAME && t != FRED_HOTPURSUIT_GAME)"
      + NL + "        return 0;" + NL
      + "    return TheRaceEvent.nType == RACE_EVENT_KNOCKOUT;",
      "    if (t != FRED_ULTIMATE_GAME)" + NL + "        return 0;" + NL
      + "    return TheRaceEvent.nType == RACE_EVENT_KNOCKOUT;"),
    M("ko-ev", "return TheRaceEvent.nType == RACE_EVENT_KNOCKOUT;",
      "return TheRaceEvent.nType >= RACE_EVENT_KNOCKOUT;"),
    M("tour-ult", "    if (t != FRED_ULTIMATE_GAME && t != FRED_HOTPURSUIT_GAME)"
      + NL + "        return 0;" + NL
      + "    return TheRaceEvent.nType == RACE_EVENT_TOURNAMENT;",
      "    if (t != FRED_HOTPURSUIT_GAME)" + NL + "        return 0;" + NL
      + "    return TheRaceEvent.nType == RACE_EVENT_TOURNAMENT;"),
    M("tour-hp", "    if (t != FRED_ULTIMATE_GAME && t != FRED_HOTPURSUIT_GAME)"
      + NL + "        return 0;" + NL
      + "    return TheRaceEvent.nType == RACE_EVENT_TOURNAMENT;",
      "    if (t != FRED_ULTIMATE_GAME)" + NL + "        return 0;" + NL
      + "    return TheRaceEvent.nType == RACE_EVENT_TOURNAMENT;"),
    M("tour-ev", "return TheRaceEvent.nType == RACE_EVENT_TOURNAMENT;",
      "return TheRaceEvent.nType >= RACE_EVENT_TOURNAMENT;"),
    M("tour-ko", "#define FRED_CHALLENGE_GAME_KNOCKOUT  4",
      "#define FRED_CHALLENGE_GAME_KNOCKOUT  5"),

    # BuildStatsDefault.
    M("bd-eight", "i < n && i < PRERACE_STATS_LINES;",
      "i < n && i < PRERACE_STATS_LINES - 1;"),
    M("bd-player", "if (d->TheDriverType == DRIVER_TYPE_PLAYER) {",
      "if (d->TheDriverType != DRIVER_TYPE_PLAYER) {"),
    M("bd-did", "world_get_car_by_driver_number(d->UniqueDriverNumber)",
      "world_get_car_by_driver_number(d->StartingPosition)"),
    M("bd-pname", "line->CharacterName = p->PlayerSettings.PlayerName;",
      "line->CharacterName = driver_info_get_name(d);"),
    M("bd-pcol", "line->Color = PlayerTextColors[p->PlayerNumber];",
      "line->Color = PlayerTextColors[0];"),
    M("bd-pcol2", "line->Color = PlayerTextColors[p->PlayerNumber];",
      "line->Color = DefaultTextColor;"),
    M("bd-aicol", "            line->Color = DefaultTextColor;",
      "            line->Color = PlayerTextColors[1];"),
    M("bd-ainame", "            line->CharacterName = driver_info_get_name(d);",
      '            line->CharacterName = "";'),
    M("bd-pos", "line->StartPosition = d->StartingPosition;",
      "line->StartPosition = i + 1;"),
    M("bd-car", "        line->CarTypeNumber = d->CurrentRideInfo.Type;" + NL
      + "        line->KOStatus = 0;",
      "        line->CarTypeNumber = 0;" + NL + "        line->KOStatus = 0;"),
    M("bd-ko", "        line->KOStatus = 0;" + NL + "        line->Points = 0;"
      + NL + "        count++;",
      "        line->Points = 0;" + NL + "        count++;"),
    M("bd-pts", "        line->Points = 0;" + NL + "        count++;",
      "        count++;"),
    M("bd-count", "        count++;" + NL, ""),

    # BuildStatsTournament.
    M("bt-loop", "for (i = 0; i < pCurrentRace->NumRacingCars; i++) {" + NL
      + "        const DriverInfo *d = pCurrentRace->pRacingCars[i]->pCar->MyDriver;"
      + NL + "        int32_t r",
      "for (i = 1; i < pCurrentRace->NumRacingCars; i++) {" + NL
      + "        const DriverInfo *d = pCurrentRace->pRacingCars[i]->pCar->MyDriver;"
      + NL + "        int32_t r"),
    M("bt-count", "for (i = 0; i < pCurrentRace->NumRacingCars; i++) {" + NL
      + "        const DriverInfo *d = pCurrentRace->pRacingCars[i]->pCar->MyDriver;"
      + NL + "        int32_t r",
      "for (i = 0; i < pCurrentRace->NumRacingCars && i < 4; i++) {" + NL
      + "        const DriverInfo *d = pCurrentRace->pRacingCars[i]->pCar->MyDriver;"
      + NL + "        int32_t r"),
    M("bt-who", "race_event_racer_index_from_driver_number(" + NL
      + "            d->UniqueDriverNumber);",
      "race_event_racer_index_from_driver_number(" + NL
      + "            d->StartingPosition);"),
    M("bt-ridx", "state != NULL ? state[r] : 0;",
      "state != NULL ? state[r + 1] : 0;"),
    M("bt-signed", "state != NULL ? state[r] : 0;",
      "state != NULL ? (int8_t)state[r] : 0;"),
    M("bt-line", "s->StatsLines[i].Points = state",
      "s->StatsLines[0].Points = state"),
    M("bt-default", "    pre_race_stats_build_stats_default(s);" + NL
      + "    state =", "    state ="),

    # BuildStatsRaceKnockout.
    M("bk-racing", "s->StatsLines[i].KOStatus = STARTRACE_LANG_KO_RACING;",
      "s->StatsLines[i].KOStatus = STARTRACE_LANG_KO_ELIMINATED;"),
    M("bk-n", "    for (i = 0; i < n; i++)" + NL,
      "    for (i = 1; i < n; i++)" + NL),
    M("bk-n8", "    for (i = 0; i < n; i++)" + NL,
      "    for (i = 0; i < PRERACE_STATS_LINES; i++)" + NL),
    M("bk-from", "for (i = 0; i < TheRaceParameters.NumDriverInfo; i++) {",
      "for (i = 1; i < TheRaceParameters.NumDriverInfo; i++) {"),
    M("bk-to", "for (i = 0; i < TheRaceParameters.NumDriverInfo; i++) {",
      "for (i = 0; i < TheRaceParameters.NumDriverInfo - 1; i++) {"),
    M("bk-elim", "if (d->EliminatedRank <= 0)", "if (d->EliminatedRank < 0)"),
    M("bk-elim1", "if (d->EliminatedRank <= 0)", "if (d->EliminatedRank <= 1)"),
    M("bk-next", "line = &s->StatsLines[n++];", "line = &s->StatsLines[n];"),
    M("bk-car", "        line->CarTypeNumber = d->CurrentRideInfo.Type;" + NL
      + "        line->CharacterName = driver_info_get_name(d);",
      "        line->CharacterName = driver_info_get_name(d);"),
    M("bk-name", "        line->CharacterName = driver_info_get_name(d);" + NL
      + "        if (d->TheDriverType",
      '        line->CharacterName = "";' + NL + "        if (d->TheDriverType"),
    M("bk-player", "if (d->TheDriverType == DRIVER_TYPE_PLAYER)" + NL
      + "            line->CharacterName = TheRaceParameters",
      "if (d->TheDriverType != DRIVER_TYPE_PLAYER)" + NL
      + "            line->CharacterName = TheRaceParameters"),
    M("bk-pset", ".PlayerSettings[d->UniqueDriverNumber].PlayerName;",
      ".PlayerSettings[0].PlayerName;"),
    M("bk-color", "line->Color = PreRaceKnockoutColor;",
      "line->Color = DefaultTextColor;"),
    M("bk-status", "line->KOStatus = STARTRACE_LANG_KO_ELIMINATED;",
      "line->KOStatus = STARTRACE_LANG_KO_RACING;"),
    M("bk-pts", "        line->Points = 0;" + NL
      + "        line->StartPosition = d->EliminatedRank;",
      "        line->StartPosition = d->EliminatedRank;"),
    M("bk-pos", "line->StartPosition = d->EliminatedRank;",
      "line->StartPosition = d->StartingPosition;"),

    # GetStatsForRacePosition.
    M("gp-to", "    for (i = 0; i < PRERACE_STATS_LINES; i++)" + NL
      + "        if (s->StatsLines[i].StartPosition == pos)",
      "    for (i = 0; i < PRERACE_STATS_LINES - 1; i++)" + NL
      + "        if (s->StatsLines[i].StartPosition == pos)"),
    M("gp-from", "    for (i = 0; i < PRERACE_STATS_LINES; i++)" + NL
      + "        if (s->StatsLines[i].StartPosition == pos)",
      "    for (i = 1; i < PRERACE_STATS_LINES; i++)" + NL
      + "        if (s->StatsLines[i].StartPosition == pos)"),
    M("gp-last", "    for (i = 0; i < PRERACE_STATS_LINES; i++)" + NL
      + "        if (s->StatsLines[i].StartPosition == pos)" + NL
      + "            return &s->StatsLines[i];" + NL + "    return NULL;",
      "    PreRaceStatsLine *hit = NULL;" + NL + NL
      + "    for (i = 0; i < PRERACE_STATS_LINES; i++)" + NL
      + "        if (s->StatsLines[i].StartPosition == pos)" + NL
      + "            hit = &s->StatsLines[i];" + NL + "    return hit;"),
    M("gp-none", "            return &s->StatsLines[i];" + NL
      + "    return NULL;",
      "            return &s->StatsLines[i];" + NL
      + "    return &s->StatsLines[0];"),

    # The constructor.
    M("c-hash", "s->ScreenHash = screen;", "s->ScreenHash = screen + 1;"),
    M("c-tn", "set_track_name_and_race_number(screen, STARTRACE_OBJ_TRACK_NAME,",
      "set_track_name_and_race_number(screen, STARTRACE_OBJ_RACE_OF,"),
    M("c-tn-add", "STARTRACE_OBJ_RACE_OF, 1);", "STARTRACE_OBJ_RACE_OF, 0);"),
    M("c-memset", "    memset(s->StatsLines, 0, sizeof s->StatsLines);" + NL, ""),
    M("c-memset-n", "memset(s->StatsLines, 0, sizeof s->StatsLines);",
      "memset(s->StatsLines, 0, sizeof s->StatsLines - 48);"),
    M("c-ko-vis", "                               FLAILER_OBJECT_VISIBLE);" + NL
      + "        flailer_set_language_id(s->ScreenHash, STARTRACE_OBJ_STATUS_HEAD,"
      + NL + "                                STARTRACE_LANG_KO_HEAD);",
      "                               FLAILER_OBJECT_INVISIBLE);" + NL
      + "        flailer_set_language_id(s->ScreenHash, STARTRACE_OBJ_STATUS_HEAD,"
      + NL + "                                STARTRACE_LANG_KO_HEAD);"),
    M("c-ko-head", "STARTRACE_LANG_KO_HEAD);", "STARTRACE_LANG_TOURNEY_HEAD);"),
    M("c-ko-build", "pre_race_stats_build_stats_race_knockout(s);",
      "pre_race_stats_build_stats_default(s);"),
    M("c-tour-vis", "                               FLAILER_OBJECT_VISIBLE);" + NL
      + "        flailer_set_language_id(s->ScreenHash, STARTRACE_OBJ_STATUS_HEAD,"
      + NL + "                                STARTRACE_LANG_TOURNEY_HEAD);",
      "                               FLAILER_OBJECT_INVISIBLE);" + NL
      + "        flailer_set_language_id(s->ScreenHash, STARTRACE_OBJ_STATUS_HEAD,"
      + NL + "                                STARTRACE_LANG_TOURNEY_HEAD);"),
    M("c-tour-head", "STARTRACE_LANG_TOURNEY_HEAD);", "STARTRACE_LANG_KO_HEAD);"),
    M("c-tour-build", "pre_race_stats_build_stats_tournament(s);",
      "pre_race_stats_build_stats_default(s);"),
    M("c-def-vis", "FLAILER_OBJECT_INVISIBLE);" + NL
      + "        pre_race_stats_build_stats_default(s);",
      "FLAILER_OBJECT_VISIBLE);" + NL
      + "        pre_race_stats_build_stats_default(s);"),
    M("c-loop-to", "for (i = 1; i <= PRERACE_STATS_LINES; i++) {",
      "for (i = 1; i < PRERACE_STATS_LINES; i++) {"),
    M("c-loop-from", "for (i = 1; i <= PRERACE_STATS_LINES; i++) {",
      "for (i = 0; i <= PRERACE_STATS_LINES; i++) {"),
    M("c-pos-fmt", '"POS_%d"', '"POS%d"'),
    M("c-name-fmt", '"NAME_%d"', '"NAME%d"'),
    M("c-type-fmt", '"TYPE_%d"', '"TYPE%d"'),
    M("c-status-fmt", '"STATUS_%d"', '"STATUS%d"'),
    M("c-getpos", "            s, i);", "            s, i + 1);"),
    M("c-car", "cartypeinfo_get(line->CarTypeNumber);", "cartypeinfo_get(0);"),
    M("c-on-pos", "            flailer_set_visibility(s->ScreenHash, pos," + NL
      + "                                   FLAILER_OBJECT_VISIBLE);",
      "            flailer_set_visibility(s->ScreenHash, pos," + NL
      + "                                   FLAILER_OBJECT_INVISIBLE);"),
    M("c-on-name", "            flailer_set_visibility(s->ScreenHash, name," + NL
      + "                                   FLAILER_OBJECT_VISIBLE);",
      "            flailer_set_visibility(s->ScreenHash, name," + NL
      + "                                   FLAILER_OBJECT_INVISIBLE);"),
    M("c-on-type", "            flailer_set_visibility(s->ScreenHash, type," + NL
      + "                                   FLAILER_OBJECT_VISIBLE);",
      "            flailer_set_visibility(s->ScreenHash, type," + NL
      + "                                   FLAILER_OBJECT_INVISIBLE);"),
    M("c-pos-print", '"%2d",', '"%d",'),
    M("c-name-print",
      'flailer_printf(s->ScreenHash, name, "%s", line->CharacterName);',
      'flailer_printf(s->ScreenHash, type, "%s", line->CharacterName);'),
    M("c-type-trs", "get_translated_string_by_name(" + NL
      + "                               car_type_info_get_short_name(ct))",
      "car_type_info_get_short_name(ct)"),
    M("c-ko-st-vis", "            if (ko) {" + NL
      + "                flailer_set_visibility(s->ScreenHash, status," + NL
      + "                                       FLAILER_OBJECT_VISIBLE);",
      "            if (ko) {" + NL
      + "                flailer_set_visibility(s->ScreenHash, status," + NL
      + "                                       FLAILER_OBJECT_INVISIBLE);"),
    M("c-ko-st", "(uint32_t)line->KOStatus);", "(uint32_t)line->Points);"),
    M("c-tour-st-vis", "            } else if (tour) {" + NL
      + "                flailer_set_visibility(s->ScreenHash, status," + NL
      + "                                       FLAILER_OBJECT_VISIBLE);",
      "            } else if (tour) {" + NL
      + "                flailer_set_visibility(s->ScreenHash, status," + NL
      + "                                       FLAILER_OBJECT_INVISIBLE);"),
    M("c-tour-st", "(int)line->Points);", "(int)line->KOStatus);"),
    M("c-def-st", "            } else {" + NL
      + "                flailer_set_visibility(s->ScreenHash, status," + NL
      + "                                       FLAILER_OBJECT_INVISIBLE);",
      "            } else {" + NL
      + "                flailer_set_visibility(s->ScreenHash, status," + NL
      + "                                       FLAILER_OBJECT_VISIBLE);"),
    M("c-col-pos", "flailer_set_object_color(s->ScreenHash, pos, &line->Color);",
      "flailer_set_object_color(s->ScreenHash, name, &line->Color);"),
    M("c-col-name", "flailer_set_object_color(s->ScreenHash, name, &line->Color);",
      "flailer_set_object_color(s->ScreenHash, pos, &line->Color);"),
    M("c-col-type", "flailer_set_object_color(s->ScreenHash, type, &line->Color);",
      "flailer_set_object_color(s->ScreenHash, status, &line->Color);"),
    M("c-col-status",
      "flailer_set_object_color(s->ScreenHash, status, &line->Color);",
      "flailer_set_object_color(s->ScreenHash, type, &line->Color);"),
    M("c-col-val",
      "flailer_set_object_color(s->ScreenHash, status, &line->Color);",
      "flailer_set_object_color(s->ScreenHash, status, &DefaultTextColor);"),
    M("c-off-pos", "            flailer_set_visibility(s->ScreenHash, pos," + NL
      + "                                   FLAILER_OBJECT_INVISIBLE);",
      "            flailer_set_visibility(s->ScreenHash, pos," + NL
      + "                                   FLAILER_OBJECT_VISIBLE);"),
    M("c-off-name", "            flailer_set_visibility(s->ScreenHash, name," + NL
      + "                                   FLAILER_OBJECT_INVISIBLE);",
      "            flailer_set_visibility(s->ScreenHash, name," + NL
      + "                                   FLAILER_OBJECT_VISIBLE);"),
    M("c-off-type", "            flailer_set_visibility(s->ScreenHash, type," + NL
      + "                                   FLAILER_OBJECT_INVISIBLE);",
      "            flailer_set_visibility(s->ScreenHash, type," + NL
      + "                                   FLAILER_OBJECT_VISIBLE);"),
    M("c-off-status", "            flailer_set_visibility(s->ScreenHash, status," + NL
      + "                                   FLAILER_OBJECT_INVISIBLE);",
      "            flailer_set_visibility(s->ScreenHash, status," + NL
      + "                                   FLAILER_OBJECT_VISIBLE);"),
    M("c-prev-obj", "if (start_race_need_to_see_objective(&TheStartRaceScreenManager)",
      "if (0"),
    M("c-prev-2p", "|| start_race_need_to_see_2p_be_a_cop(&TheStartRaceScreenManager))",
      "|| 0)"),
    M("c-prev-vis", "STARTRACE_OBJ_PREVIOUS," + NL
      + "                               FLAILER_OBJECT_VISIBLE);",
      "STARTRACE_OBJ_PREVIOUS," + NL
      + "                               FLAILER_OBJECT_INVISIBLE);"),
    M("c-prev-invis", "STARTRACE_OBJ_PREVIOUS," + NL
      + "                               FLAILER_OBJECT_INVISIBLE);",
      "STARTRACE_OBJ_PREVIOUS," + NL
      + "                               FLAILER_OBJECT_VISIBLE);"),
    M("c-next", "STARTRACE_OBJ_NEXT," + NL
      + "                           FLAILER_OBJECT_VISIBLE);",
      "STARTRACE_OBJ_NEXT," + NL
      + "                           FLAILER_OBJECT_INVISIBLE);"),
    M("c-ret", "    return s;" + NL + "}" + NL + NL
      + "void pre_race_stats_destroy",
      "    return NULL;" + NL + "}" + NL + NL + "void pre_race_stats_destroy"),

    # The destructor.
    M("d-free", "if (flags & 1)" + NL + "        bFree(s);",
      "if (flags & 4)" + NL + "        bFree(s);"),

    # HandleEvent.
    M("he-up", "if (msg == BMSG_MENUITEM_PAD_UP || msg == BMSG_MENUITEM_PAD_DOWN) {",
      "if (msg == BMSG_MENUITEM_PAD_LEFT || msg == BMSG_MENUITEM_PAD_DOWN) {"),
    M("he-down", "if (msg == BMSG_MENUITEM_PAD_UP || msg == BMSG_MENUITEM_PAD_DOWN) {",
      "if (msg == BMSG_MENUITEM_PAD_UP || msg == BMSG_MENUITEM_PAD_RIGHT) {"),
    M("he-noise", "        data->noise = 0;" + NL
      + "    } else if (msg == BMSG_SCREEN_BACK_BUTTON) {" + NL
      + "        const char *was;",
      "        data->noise = 1;" + NL
      + "    } else if (msg == BMSG_SCREEN_BACK_BUTTON) {" + NL
      + "        const char *was;"),
    M("he-back-msg", "    } else if (msg == BMSG_SCREEN_BACK_BUTTON) {" + NL
      + "        const char *was;",
      "    } else if (msg == BMSG_SCREEN_SELECT_BUTTON) {" + NL
      + "        const char *was;"),
    M("he-back-param", "        data->param = 0;" + NL + "        was = m->Screens",
      "        was = m->Screens"),
    M("he-back-dec", "if (m->CurrentScreen > 0)", "if (m->CurrentScreen > 1)"),
    M("he-back-ge", "if (m->CurrentScreen > 0)", "if (m->CurrentScreen >= 0)"),
    M("he-back-same", "if (m->Screens[m->CurrentScreen] == was)",
      "if (m->Screens[m->CurrentScreen] != was)"),
    M("he-back-noise", "            data->noise = 0;" + NL + "        else" + NL
      + "            change_to_screen(m->Screens[m->CurrentScreen], 0);",
      "            data->noise = 1;" + NL + "        else" + NL
      + "            change_to_screen(m->Screens[m->CurrentScreen], 0);"),
    M("he-back-push", "change_to_screen(m->Screens[m->CurrentScreen], 0);",
      "change_to_screen(m->Screens[m->CurrentScreen], 1);"),
    M("he-sel-msg", "    } else if (msg == BMSG_MENUITEM_SELECT) {" + NL
      + "        if (data->param",
      "    } else if (msg == BMSG_SCREEN_START_BUTTON) {" + NL
      + "        if (data->param"),
    M("he-sel-start", "if (data->param == JOY_EVENT_START)",
      "if (data->param != JOY_EVENT_START)"),
    M("he-start-id", "#define JOY_EVENT_START 7", "#define JOY_EVENT_START 6"),
    M("he-sel-noise", "            data->noise = 0;" + NL + "        else" + NL
      + "            racecoordinator_post_message",
      "            data->noise = 1;" + NL + "        else" + NL
      + "            racecoordinator_post_message"),
    M("he-sel-skip", "            racecoordinator_post_message(pRaceCoordinator, RC_SKIP, 0);"
      + NL + "    }" + NL + "}",
      "            racecoordinator_post_message(pRaceCoordinator, RC_SKIP + 1, 0);"
      + NL + "    }" + NL + "}"),
    M("he-sel-param", "            racecoordinator_post_message(pRaceCoordinator, RC_SKIP, 0);"
      + NL + "    }" + NL + "}",
      "            racecoordinator_post_message(pRaceCoordinator, RC_SKIP, 1);"
      + NL + "    }" + NL + "}"),

    # The grid's callback.
    M("cb-act", "if (msg == BMSG_SCREEN_ACTIVATE) {",
      "if (msg == BMSG_MENUITEM_ACTIVATE) {"),
    M("cb-size", "bMalloc(sizeof(PreRaceStats),", "bMalloc(sizeof(PreRaceStats) + 16,"),
    M("cb-tag", '"PreRaceStats", 0, 16);', '"PreRaceStat", 0, 16);'),
    M("cb-flags", '"PreRaceStats", 0, 16);', '"PreRaceStats", 1, 16);'),
    M("cb-pool", '"PreRaceStats", 0, 16);', '"PreRaceStats", 0, 0);'),
    M("cb-hash", "pre_race_stats_construct(mem, data->itemHash);",
      "pre_race_stats_construct(mem, STARTRACE_SCREEN_STATS);"),
    M("cb-unact", "} else if (msg == BMSG_SCREEN_UNACTIVATE) {",
      "} else if (msg == BMSG_MENUITEM_UNACTIVATE) {"),
    M("cb-null", "if (PreRaceStatsInstance != NULL)" + NL
      + "            pre_race_stats_destroy(PreRaceStatsInstance, 3);",
      "if (PreRaceStatsInstance == NULL)" + NL
      + "            pre_race_stats_destroy(PreRaceStatsInstance, 3);"),
    M("cb-del", "pre_race_stats_destroy(PreRaceStatsInstance, 3);",
      "pre_race_stats_destroy(PreRaceStatsInstance, 2);"),
    M("cb-clear", "        PreRaceStatsInstance = NULL;" + NL + "    } else {",
      "    } else {"),
    M("cb-else", "pre_race_stats_handle_event(PreRaceStatsInstance, msg, data);",
      "(void)0;"),

    # The letterbox.
    M("lb-sel", "    if (msg == BMSG_MENUITEM_SELECT) {" + NL
      + "        if (pRaceCoordinator != NULL)",
      "    if (msg == BMSG_SCREEN_START_BUTTON) {" + NL
      + "        if (pRaceCoordinator != NULL)"),
    M("lb-rc", "        if (pRaceCoordinator != NULL)" + NL
      + "            racecoordinator_post_message",
      "        if (1)" + NL + "            racecoordinator_post_message"),
    M("lb-skip", "            racecoordinator_post_message(pRaceCoordinator, RC_SKIP, 0);"
      + NL + "    } else if (msg == BMSG_SCREEN_BACK_BUTTON) {",
      "            racecoordinator_post_message(pRaceCoordinator, RC_SKIP + 1, 0);"
      + NL + "    } else if (msg == BMSG_SCREEN_BACK_BUTTON) {"),
    M("lb-back-msg", "    } else if (msg == BMSG_SCREEN_BACK_BUTTON) {" + NL
      + "        data->noise = 0;" + NL + "        data->param = 0;",
      "    } else if (msg == BMSG_SCREEN_SELECT_BUTTON) {" + NL
      + "        data->noise = 0;" + NL + "        data->param = 0;"),
    M("lb-back-noise", "        data->noise = 0;" + NL + "        data->param = 0;",
      "        data->noise = 1;" + NL + "        data->param = 0;"),
    M("lb-back-param", "        data->noise = 0;" + NL + "        data->param = 0;",
      "        data->noise = 0;"),
    M("lb-up", "    } else if (msg == BMSG_MENUITEM_PAD_UP" + NL,
      "    } else if (msg == BMSG_MENUITEM_PAD_LEFT" + NL),
    M("lb-down", "               || msg == BMSG_MENUITEM_PAD_DOWN) {",
      "               || msg == BMSG_MENUITEM_PAD_RIGHT) {"),
    M("lb-noise", "               || msg == BMSG_MENUITEM_PAD_DOWN) {" + NL
      + "        data->noise = 0;",
      "               || msg == BMSG_MENUITEM_PAD_DOWN) {" + NL
      + "        data->noise = 1;"),
]

EQUIVALENT = {
    # Enable always adds a screen (the letterbox when it wants none of the
    # other three), so Screens[0] is always written again.
    "en-s0": "Enable always adds a screen, so Screens[0] is rewritten",
    # BuildStats is only called from the constructor, after its memset, so
    # the lines' KOStatus and Points are already 0.
    "bd-ko": "the constructor's memset has KOStatus at 0",
    "bd-pts": "the constructor's memset has Points at 0",
    "bk-pts": "the constructor's memset has Points at 0",
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
        todo, SOURCES, "startrace_test",
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
