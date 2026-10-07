"""Cross-check 3DS Files/source/raceupdate.c and playerfinish.c against the
retail image's own code.

Race::Update is the race's step, which World::DoTimestep runs once a step:
the countdown's end, the race time, the ghost cars, the laps, a forced
finish, the leadership, a lap knockout's and a time trial's finishes, the
laps led, the finish and the lap speech. Race::FinishCar is how a car
finishes. The oracle is SLES_507.31 itself, run in tools/mipsemu.py:

- Race.obj's Update (0x00148a78), MonitorLeadership (0x00148320),
  MaybeSaveGhostCarData (0x001484f0), FinishCar (0x001485f0 and, by car,
  0x00149250), UpdateGhostCar (0x00148940), GetLeadingUnfinishedCar
  (0x00149160), GetFinisher (0x001491c0), GetNextFinishRank (0x00149208)
  and 0x001473f8, which projects a race time; SimulateRaceFinish
  (0x00148f68), through which the port's gRaceFinishCarFn is reached;
  Player::SetFinishedRacing (0x00176650);
- run as shipped under them: GetCountdownNumberToDisplay (0x001480c0),
  AreAllPlayersFinishedRacing (0x001490b0), RacingCar::GetPlayer
  (0x001475b8), the five boundary accessors (0x00147540 to 0x001475a0),
  AICarController's pull-over (0x001908d8), Timer::SetTime (0x00136dd0) and
  Round (0x001a3e28), bSin (0x0025a540) and SplitTimeSpeech (0x00207268,
  `jr ra`).

Stood in on both sides, each call printing a line, so both must ask the
same questions in the same order:
  RacingCar::UpdateLapCounts (0x00146fd0) and Race::SortRacingCarsBy-
    Leadership (0x00148218), which do nothing more; Race::SetRaceStage
    (0x00147ef0), which sets the stage;
  Car::SetControlMode (0x00131410): the mode, and for AI_CONTROL a new
    controller, b<car>, with ForceCurrentAction NONE and PullOverTimeout
    1e7, as the AIDriver SetControlMode builds;
  Car::BlinkBlinkPoof (0x001330e0);
  ReplayManager::RegisterInterestingEvent (0x0013e270): the value and the
    name;
  RaceEvent::RecordResults (0x00201598), LapFinishedSpeech (0x00207198),
    cSEDWedge::ClearEventQueue (0x00206190), TriggerFinishLineSound
    (0x001afb38), bWriteToFile (0x002549c8) and __builtin_delete
    (0x00114e98);
  GhostCarData::AddSample (0x001b46a0), the matrix and the time, and
    GetSample (0x001b43f0), answering the script's matrix and answer;
  Timer::PrintToString (0x001a3b98), silent: MaybeSaveGhostCarData prints
    into the stack for a print that is compiled out.

RacingCar::GetPlayer is the harness's copy of racerun.c's, which
racerun_check checks.

After each call the race, the eight racing cars, the cars' modes and
controllers, the players, the ghost's WorldObject and the two ghost data
times are dumped by field.

    python tools/raceupdate_check.py
    python tools/raceupdate_check.py --mutate [--only a,b] [--jobs N]
    python tools/raceupdate_check.py --dump PREFIX
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

HARNESS = "tools/src/raceupdate_test.c"
RUC = "3DS Files/source/raceupdate.c"
PFC = "3DS Files/source/playerfinish.c"
RSC = "3DS Files/source/racesplit.c"
AICCH = "3DS Files/source/aicarcontroller.h"
SOURCES = [HARNESS, RUC, PFC, RSC,
           "3DS Files/source/racefinish.c",
           "3DS Files/source/race.c",
           "3DS Files/source/timer.c",
           "3DS Files/source/bmem.c"]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = retail_model.RETAIL_GP

UPDATE = 0x00148a78
FINISH = 0x001485f0
FINISH_CAR = 0x00149250
PROJECT = 0x001473f8
MONITOR = 0x00148320
SAVE_GHOST = 0x001484f0
UPDATE_GHOST = 0x00148940
LEADING = 0x00149160
FINISHER = 0x001491c0
NEXT_RANK = 0x00149208
SIMULATE = 0x00148f68
SET_FINISHED = 0x00176650

UPDATE_LAP_COUNTS = 0x00146fd0
SET_RACE_STAGE = 0x00147ef0
SORT = 0x00148218
SET_CONTROL_MODE = 0x00131410
BLINK = 0x001330e0
REGISTER_EVENT = 0x0013e270
RECORD_RESULTS = 0x00201598
LAP_SPEECH = 0x00207198
CLEAR_QUEUE = 0x00206190
FINISH_SOUND = 0x001afb38
ADD_SAMPLE = 0x001b46a0
GET_SAMPLE = 0x001b43f0
WRITE_FILE = 0x002549c8
BDELETE = 0x00114e98
PRINT_TO_STRING = 0x001a3b98

THE_RACE_EVENT = 0x0031b600
RACE_PARAMS = 0x0031a898
RP_RACETYPE, RP_TT, RP_BEACOP = 32, 36, 628

CURRENT_RACE_GP = -22272
WORLD_TIMER_GP = -19576
WORLD_FRAMES_GP = -19564
NPLAYERS_GP = -20920
BYINDEX_GP = -20928
COPMGR_GP = -15620
REPLAY_GP = -22440
WEDGE_GP = -19016
PULLTO_GP = -18156

# The world, at retail's offsets.
R = 0x01E00000                      # the Race, 1716 bytes
R_SIZE = 1716
CARS = 0x01E01000                   # c0..c7, 0x400 apart
AICCS = 0x01E03000                  # a0..a7 then b0..b7, 0x400 apart
PLAYERS = 0x01E07000                # p0, p1, 0x100 apart
COPMGR = 0x01E07400
COPS = 0x01E07600                   # 0x20 apart
G1 = 0x01E07800                     # the ghost data captured
G2 = 0x01E07900                     # the ghost data replayed
WO = 0x01E07A00                     # its WorldObject
RM = 0x01E07B00                     # pReplayManager
WEDGE = 0x01E07C00
START = 0x01E07D00                  # ProjectRaceTime's start, for OP_PROJECT
WORLD_END = 0x01E08000

NCARS, NPLAYERS, NCOPS = 8, 2, 7

(OP_TAG, OP_RESET, OP_RACE, OP_RC, OP_CAR, OP_PLAYER, OP_GLOBAL,
 OP_SAMPLE, OP_UPDATE, OP_FINISH, OP_FINISH_CAR, OP_PROJECT, OP_MONITOR,
 OP_SAVE_GHOST, OP_UPDATE_GHOST, OP_LEADING, OP_FINISHER, OP_NEXT_RANK,
 OP_SIMULATE, OP_SET_FINISHED, OP_DUMP) = range(21)

ARGS = {OP_TAG: 1, OP_RESET: 0, OP_RACE: 2, OP_RC: 3, OP_CAR: 3,
        OP_PLAYER: 3, OP_GLOBAL: 2, OP_SAMPLE: 2, OP_UPDATE: 0,
        OP_FINISH: 4, OP_FINISH_CAR: 4, OP_PROJECT: 3, OP_MONITOR: 0,
        OP_SAVE_GHOST: 1, OP_UPDATE_GHOST: 0, OP_LEADING: 0, OP_FINISHER: 1,
        OP_NEXT_RANK: 0, OP_SIMULATE: 0, OP_SET_FINISHED: 1, OP_DUMP: 0}

(F_STAGE, F_GO, F_COUNTDOWN, F_START, F_RACETIME, F_BEST, F_NUM, F_NFIN,
 F_LAPS, F_FPOS, F_FPLAYER, F_STARTLINE, F_FINISHLINE, F_ORDER, F_CAPCAR,
 F_CAPDATA, F_REPDATA, F_WO) = range(18)

(R_CAR, R_LAPS, R_POS, R_PREV, R_ORDER, R_CROSSED, R_NEWLAP, R_LED,
 R_REASON, R_CLE, R_FLE, R_RACETIME) = range(12)
R_BCT, R_RUN, R_BEST = 20, 25, 30

C_PLAYER, C_RC, C_MODE, C_CTRL, C_FORCE, C_TIMEOUT, C_SPEED = range(7)
C_POS, C_BODY = 10, 20

PL_CAR, PL_NUMBER, PL_TFR, PL_FAL = range(4)

(G_TIMER, G_FRAMES, G_NPLAYERS, G_BYINDEX0, G_BYINDEX1, G_RACETYPE, G_TT,
 G_BEACOP, G_PULLTO, G_COPMGR, G_COPIDX, G_GETSAMPLE, G_G1_TIME,
 G_G1_SAMPLES, G_G2_TIME, G_G2_LAPS, G_WO_ENABLED) = range(17)
G_COP = 20

# The race's field offsets.
RACE_OFF = {F_STAGE: 0, F_GO: 4, F_COUNTDOWN: 8, F_START: 12,
            F_RACETIME: 16, F_BEST: 20, F_NUM: 24, F_NFIN: 28, F_LAPS: 1604,
            F_FPOS: 1608, F_FPLAYER: 1612}
TABLE, ORDER = 36, 1572
STARTLINE, FINISHLINE = 1618, 1619
REPDATA, WOPTR, CAPCAR, CAPDATA, FILENAME = 1656, 1660, 1664, 1668, 1672
RC_SIZE = 192

# The racing car's: (offset, bytes, signed).
RC_OFF = {R_LAPS: (9, 1), R_POS: (10, 1), R_PREV: (11, 1), R_ORDER: (12, 1),
          R_CROSSED: (13, 1), R_NEWLAP: (14, 1), R_LED: (16, 2),
          R_REASON: (18, 2), R_CLE: (20, 4), R_FLE: (32, 4),
          R_RACETIME: (180, 4)}

AI_CONTROL, REAL_CONTROL = 2, 1
STAGE_COUNTDOWN, STAGE_RACING = 3, 4
NOT_FINISHED, NORMAL, ARRESTED, KNOCKED_OUT, COP_WON, COP_LOST = range(6)
NO_TIME = 0x7fffffff

FILE_NAME = "host0:ghost.dat"


def fb(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def bf(b):
    return struct.unpack("<f", struct.pack("<I", b & M32))[0]


def f32(x):
    return bf(fb(x))


def fx(b):
    return "%08x" % (b & M32)


def s8(v):
    v &= 0xff
    return v - 256 if v & 0x80 else v


def s16(v):
    v &= 0xffff
    return v - 65536 if v & 0x8000 else v


class Fb(object):
    """A float argument given as its bits."""
    def __init__(self, bits):
        self.bits = bits & M32


def nextup(x, n=1):
    """x moved n ulps towards +inf (a float32)."""
    b = fb(f32(x))
    for _ in range(abs(n)):
        if n > 0:
            if b & 0x80000000:
                b = 0 if b == 0x80000000 else b - 1
            else:
                b += 1
        else:
            if b & 0x80000000:
                b += 1
            elif b == 0:
                b = 0x80000001
            else:
                b -= 1
    return bf(b)


class Script(object):
    def __init__(self):
        self.ops = []
        self.tags = []

    def op(self, code, *args):
        assert len(args) == ARGS[code], (code, args)
        out = []
        for a in args:
            if isinstance(a, Fb):
                out.append(a.bits)
            elif isinstance(a, float):
                out.append(fb(a))
            else:
                out.append(int(a))
        self.ops.append((code,) + tuple(out))

    def tag(self, s):
        self.tags.append(s)
        self.op(OP_TAG, len(self.tags) - 1)

    def encode(self):
        out = [len(self.tags)]
        for s in self.tags:
            b = s.encode("latin-1")
            out.append(len(b))
            out.extend(b)
        flat = []
        for o in self.ops:
            flat.extend(o)
        out.append(len(flat))
        out.extend(flat)
        return struct.pack("<%di" % len(out), *[s32(v & M32) for v in out])

    # ---- sugar -----------------------------------------------------------

    def race(self, f, v):
        self.op(OP_RACE, f, v)

    def order(self, i, j):
        self.op(OP_RACE, F_ORDER, (i << 4) | (j & 15))

    def rc(self, j, f, v):
        self.op(OP_RC, j, f, v)

    def car(self, i, f, v):
        self.op(OP_CAR, i, f, v)

    def player(self, i, f, v):
        self.op(OP_PLAYER, i, f, v)

    def glob(self, f, v):
        self.op(OP_GLOBAL, f, v)

    def pos(self, i, x, y, z, w=1.0):
        for k, v in enumerate((x, y, z, w)):
            self.car(i, C_POS + k, f32(v))


# ============================================================== the script

def field(sc, n=8, laps=3, players=1, start=40000, timer=None,
          start_line=0, finish_line=0, rnd=None):
    """A race of n cars at RACING, with the first `players` cars the
    players', strung out 100 m apart, in order, at 30-37 m/s."""
    sc.op(OP_RESET)
    sc.race(F_NUM, n)
    sc.race(F_LAPS, laps)
    sc.race(F_START, start)
    sc.race(F_STARTLINE, start_line)
    sc.race(F_FINISHLINE, finish_line)
    sc.race(F_STAGE, STAGE_RACING)
    sc.race(F_BEST, NO_TIME)
    for j in range(NCARS):
        sc.rc(j, R_POS, j + 1)
        sc.rc(j, R_PREV, j + 1)
        sc.rc(j, R_CLE, f32(1.0 + 0.125 * (NCARS - j)))
        for k in range(5):
            sc.rc(j, R_BEST + k, NO_TIME)
            sc.rc(j, R_BCT + k, start + 4000 * k + 37 * j)
            sc.rc(j, R_RUN + k, 60000 + 1000 * k + 11 * j)
        sc.pos(j, 100.0 * (NCARS - j), 3.0 * j, 0.5 + 0.25 * j)
        sc.car(j, C_SPEED, f32(30.0 + j))
        sc.car(j, C_MODE, REAL_CONTROL if j < players else AI_CONTROL)
        sc.car(j, C_FORCE, 11)
        sc.car(j, C_TIMEOUT, 1e7)
        for k in range(16):
            v = (1.0 if k % 5 == 0 else 0.0) if rnd is None \
                else f32(rnd.uniform(-2, 2))
            sc.car(j, C_BODY + k, f32(v + 0.001 * j))
    for p in range(players):
        sc.player(p, PL_CAR, p)
        sc.player(p, PL_NUMBER, p)
        sc.car(p, C_PLAYER, p)
        sc.glob(G_BYINDEX0 + p, p)
    sc.glob(G_NPLAYERS, players)
    sc.glob(G_TIMER, start + 200000 if timer is None else timer)
    sc.glob(G_FRAMES, 5000)


def cop_world(sc, idx, cop_car):
    """The cop manager, with cop `idx` (in [0, 7)) on `cop_car` (-1 for
    none, -2 for no cop), or -1 for no player cop."""
    sc.glob(G_COPMGR, 1)
    sc.glob(G_COPIDX, idx)
    if 0 <= idx < NCOPS:
        sc.glob(G_COP + idx, cop_car)


def script():
    sc = Script()
    rnd = random.Random(0x11a2b)

    # -- the finders ------------------------------------------------------
    sc.tag("finders")
    for n in (0, 1, 3, 8):
        for orders in ((0,) * 8, (1, 0, 2, 0, 0, 3, 0, 0),
                       (2, 1, 3, 4, 5, 6, 7, 8), (0, -1, 1, 0, 2, 0, 0, 0),
                       (1, 1, 0, 0, 0, 0, 0, 0)):
            field(sc, n=n)
            for j, o in enumerate(orders):
                sc.rc(j, R_ORDER, o)
            for j, p in enumerate((3, 1, 2, 9, 0, -2, 1, 4)):
                sc.rc(j, R_POS, p)
            sc.op(OP_LEADING)
            for rank in (-1, 0, 1, 2, 3, 9, 256 + 1):
                sc.op(OP_FINISHER, rank)
            sc.op(OP_NEXT_RANK)
    # Order the cars in pRacingCars otherwise; the leader's ties.
    sc.tag("finders, the order")
    field(sc, n=6)
    for i, j in enumerate((5, 2, 7, 0, 1, 3, 4, 6)):
        sc.order(i, j)
    for j, p in enumerate((2, 2, 1, 5, 1, 3, 1, 9)):
        sc.rc(j, R_POS, p)
    sc.op(OP_LEADING)
    sc.rc(7, R_ORDER, 1)
    sc.op(OP_LEADING)
    sc.op(OP_FINISHER, 1)
    sc.op(OP_NEXT_RANK)
    sc.rc(2, R_POS, 7)          # past n + 1 = 7: not below it
    sc.rc(5, R_POS, 7)
    sc.rc(0, R_POS, 7)
    sc.rc(1, R_POS, 7)
    sc.rc(3, R_POS, 7)
    sc.rc(4, R_POS, 6)
    sc.op(OP_LEADING)
    sc.rc(4, R_POS, 7)
    sc.op(OP_LEADING)

    # -- ProjectRaceTime --------------------------------------------------
    sc.tag("project")
    for laps in (0, 1, 2, 3, -1, 7):
        for cle in (0.0, -0.0, 0.004, 0.75, 1.0, 2.5, -1.5, 1e30, 3.0):
            for done in (0, 1, -1):
                for dt in (0, 1, 4000, 123457, -5000):
                    field(sc, n=4, start_line=1, finish_line=3)
                    sc.rc(2, R_CLE, f32(cle))
                    sc.rc(2, R_LAPS, done)
                    sc.rc(2, R_BEST + 3, 0x1234)
                    sc.glob(G_TIMER, 90000 + dt)
                    sc.op(OP_PROJECT, 2, laps, 90000)
    # The fraction at its floor, an ulp either side; times that wrap.
    sc.tag("project, the floor")
    for cle in (nextup(0.01, -1), 0.01, nextup(0.01), nextup(0.02, -1),
                0.02, nextup(0.02)):
        for laps in (1, 2):
            field(sc, n=3)
            sc.rc(0, R_CLE, f32(cle))
            sc.glob(G_TIMER, 70000)
            sc.op(OP_PROJECT, 0, laps, 10000)
    for start, timer in ((0x7fff0000, 0x80001000), (0x80000000, 0x7fffffff),
                         (0xffffff00, 0x100), (5, 0x7fffffff)):
        field(sc, n=3)
        sc.rc(1, R_CLE, 0.5)
        sc.glob(G_TIMER, timer)
        sc.op(OP_PROJECT, 1, 3, start)
    # A best lap of 19.667 + 40k ticks: SetTime's + 0.5 takes it to 20,
    # which Round takes up.
    sc.tag("project, the half")
    for k in (0, 1, 1000):
        for ticks in (59 + 120 * k, 60 + 120 * k):
            field(sc, n=3, laps=3, start_line=1, finish_line=3)
            sc.rc(0, R_CLE, 3.0)
            sc.rc(0, R_BCT + 1, 50000)
            sc.glob(G_TIMER, 50000 + ticks)
            sc.op(OP_PROJECT, 0, 3, 40000)
    # Each boundary pair.
    sc.tag("project, the boundaries")
    for sl in range(5):
        for fl in range(5):
            field(sc, n=2, start_line=sl, finish_line=fl)
            sc.rc(1, R_CLE, 0.4)
            sc.op(OP_PROJECT, 1, 2, 30000)

    # -- FinishCar --------------------------------------------------------
    sc.tag("finish")
    for reason in range(6):
        for position in (-3, -1, 0, 1, 4, 127, 200):
            for laps_done in (0, 1):
                for player in (0, 1):
                    for blink in (0, 1):
                        field(sc, n=5, laps=2, players=1)
                        if player:
                            idx = 0
                        else:
                            idx = 3
                        sc.rc(idx, R_LAPS, 2 if laps_done else 1)
                        sc.rc(idx, R_CLE, 1.625)
                        sc.rc(1, R_ORDER, 1)
                        sc.rc(4, R_ORDER, 2)
                        sc.race(F_NFIN, 2)
                        sc.glob(G_TT, 0x00123456)
                        sc.op(OP_FINISH, idx, position, blink, reason)
    # The cop's times: the time trial's time at its edges.
    sc.tag("finish, the cop's times")
    for tt in (0, 1, 3999, 4000, 0x7fffffff, 0x80000000, 0xffffffff,
               123456789, 0x00800000, 0x01000001, 128140, 523620):
        for reason in (COP_WON, COP_LOST):
            field(sc, n=3, start=0x7ffffff0, timer=0x80000010 + tt % 77)
            sc.glob(G_TT, tt)
            sc.op(OP_FINISH, 1, -1, 0, reason)
    # The controller: the old timeout lower, equal, higher; the car not
    # AI-controlled; no player and a player under AI_CONTROL already.
    sc.tag("finish, the pull-over")
    for old in (1e7, 15.0, nextup(15.0), nextup(15.0, -1), 3.0, -1.0, 0.0):
        for to in (15.0, 2.0, -5.0):
            for mode in (AI_CONTROL, REAL_CONTROL, 3):
                field(sc, n=4, players=0)
                sc.car(2, C_MODE, mode)
                sc.car(2, C_TIMEOUT, f32(old))
                sc.car(2, C_FORCE, 9)
                sc.glob(G_PULLTO, f32(to))
                sc.op(OP_FINISH, 2, 0, 0, NORMAL)
    for mode in (AI_CONTROL, REAL_CONTROL):
        field(sc, n=4, players=2)
        sc.car(1, C_MODE, mode)
        sc.car(1, C_TIMEOUT, 4.0)
        sc.op(OP_FINISH, 1, 3, 1, ARRESTED)
    # A player's finish twice: the second leaves the time alone.
    sc.tag("finish, twice")
    field(sc, n=4, players=2, laps=2)
    sc.rc(1, R_LAPS, 2)
    sc.glob(G_FRAMES, 777)
    sc.op(OP_FINISH, 1, 0, 0, NORMAL)
    sc.glob(G_FRAMES, 999)
    sc.op(OP_FINISH, 1, 0, 0, NORMAL)
    # Each finish line, for the crossing time.
    sc.tag("finish, the finish line")
    for fl in range(5):
        field(sc, n=3, laps=1, finish_line=fl, players=0)
        sc.rc(2, R_LAPS, 1)
        sc.op(OP_FINISH, 2, 0, 0, NORMAL)
    # A car with no player whose pCar has none, and a car with no car.
    sc.tag("finish by car")
    for c in range(NCARS):
        for position in (0, -1, 2):
            field(sc, n=5, players=1)
            for i, j in enumerate((3, 0, 4, 1, 2, 5, 6, 7)):
                sc.order(i, j)
            sc.rc(c, R_POS, (c * 3) % 7 + 1)
            sc.op(OP_FINISH_CAR, c, position, c & 1, NORMAL + c % 5)
    # A car whose racing car is another's.
    field(sc, n=5, players=1)
    sc.car(6, C_RC, 2)
    sc.op(OP_FINISH_CAR, 6, 0, 0, NORMAL)

    # -- SimulateRaceFinish -----------------------------------------------
    sc.tag("simulate")
    for n in (0, 1, 4, 8):
        field(sc, n=n, players=2, laps=3)
        sc.rc(0, R_LAPS, 3)
        sc.rc(2, R_REASON, ARRESTED)
        sc.rc(2, R_ORDER, 1)
        sc.op(OP_SIMULATE)

    # -- Player::SetFinishedRacing ----------------------------------------
    sc.tag("set finished")
    for beacop in (0, 1):
        for laps in (2, 3):
            for others_done in (0, 1):
                for tfr in (0, 5):
                    field(sc, n=6, players=2, laps=3)
                    sc.rc(0, R_LAPS, laps)
                    sc.player(0, PL_TFR, tfr)
                    sc.player(1, PL_TFR, 1234 if others_done else 0)
                    sc.glob(G_BEACOP, beacop)
                    sc.glob(G_FRAMES, 31337)
                    # Cars round car 0 at 30 m, an ulp either side.
                    sc.pos(0, 10.0, 20.0, 1.0)
                    sc.pos(1, 10.0, 20.0, nextup(31.0, -1))
                    sc.pos(2, 40.0, 20.0, 1.0)
                    sc.pos(3, nextup(40.0, -1), 20.0, 1.0)
                    sc.pos(4, 10.0, 45.0, 20.0)
                    sc.pos(5, -9.0, 31.0, 4.0)
                    sc.op(OP_SET_FINISHED, 0)
    # No other player, one player, and the second player's own car.
    for np in (1, 2):
        field(sc, n=3, players=np, laps=1)
        sc.rc(np - 1, R_LAPS, 1)
        sc.op(OP_SET_FINISHED, np - 1)

    # -- MonitorLeadership ------------------------------------------------
    sc.tag("monitor")
    for pos, prev in ((1, 2), (2, 1), (3, 3), (1, 4), (4, 1), (0, 3),
                      (-2, 1), (5, 5), (2, 4), (3, 5)):
        for speed in (39.0, 40.0, nextup(40.0), 55.0):
            for other_speed in (speed - 7.0, nextup(speed - 7.0),
                                speed + 7.0, nextup(speed + 7.0, -1),
                                speed):
                field(sc, n=5, players=1)
                sc.rc(0, R_POS, pos)
                sc.rc(0, R_PREV, prev)
                sc.car(0, C_SPEED, f32(speed))
                other = prev - 1
                if other != 0:
                    sc.car(other, C_SPEED, f32(other_speed))
                    sc.pos(other, 600.0, 0.0, 0.5)
                    sc.pos(0, 600.0, 10.0, 2.5)
                sc.op(OP_MONITOR)
    # The distance at 25 m, an ulp either side, along each axis.
    sc.tag("monitor, the distance")
    for axis in range(3):
        for d in (nextup(25.0, -1), 25.0, nextup(25.0), 3.0, 30.0):
            field(sc, n=3, players=1)
            sc.rc(0, R_POS, 1)
            sc.rc(0, R_PREV, 2)
            sc.car(0, C_SPEED, 50.0)
            sc.car(1, C_SPEED, 48.0)
            sc.pos(1, 0.0, 0.0, 0.0, 7.0)
            xyz = [0.0, 0.0, 0.0]
            xyz[axis] = f32(d)
            sc.pos(0, xyz[0], xyz[1], xyz[2], -3.0)
            sc.op(OP_MONITOR)
    # Two players, one of them none, and none at all.
    sc.tag("monitor, the players")
    for np, nulls in ((2, ()), (2, (0,)), (2, (1,)), (0, ()), (1, ())):
        field(sc, n=4, players=2)
        sc.glob(G_NPLAYERS, np)
        for k in nulls:
            sc.glob(G_BYINDEX0 + k, -1)
        sc.rc(0, R_POS, 2)
        sc.rc(0, R_PREV, 1)
        sc.rc(1, R_POS, 1)
        sc.rc(1, R_PREV, 3)
        for c in range(4):
            sc.car(c, C_SPEED, 60.0 + c)
            sc.pos(c, 5.0 * c, 0.0, 0.0)
        sc.op(OP_MONITOR)
    # The order in pRacingCars, not the table's, gives the old place.
    field(sc, n=4, players=1)
    for i, j in enumerate((2, 3, 0, 1)):
        sc.order(i, j)
    sc.rc(0, R_POS, 1)
    sc.rc(0, R_PREV, 2)
    sc.car(0, C_SPEED, 50.0)
    sc.car(3, C_SPEED, 46.5)
    sc.pos(3, 800.0, 0.0, 0.0)
    sc.pos(0, 810.0, 0.0, 0.0)
    sc.op(OP_MONITOR)

    # -- the ghost cars ---------------------------------------------------
    sc.tag("save ghost")
    for cap in (0, 1, 2):
        for rep in (0, 1):
            for rep_laps in (2, 3):
                for t, best in ((5000, 6000), (6000, 6000), (7000, 6000),
                                (0x80000000, 5), (5, 0x80000000)):
                    for laps in (2, 3):
                        field(sc, n=4, players=1, laps=3)
                        sc.race(F_CAPCAR, (-1, 0, 1)[cap])
                        sc.race(F_CAPDATA, 1)
                        sc.race(F_REPDATA, rep)
                        sc.glob(G_G1_TIME, 0x5a5a)
                        sc.glob(G_G1_SAMPLES, 1000 - cap * 333)
                        sc.glob(G_G2_TIME, best)
                        sc.glob(G_G2_LAPS, rep_laps)
                        sc.rc(0, R_RACETIME, t)
                        sc.rc(0, R_LAPS, laps)
                        sc.op(OP_SAVE_GHOST, 0)
    # Through FinishCar: a player that has done its laps.
    sc.tag("save ghost, finishing")
    for samples in (0, 1, 1024):
        for cap in (0, 2):
            field(sc, n=3, players=1, laps=1)
            sc.race(F_CAPCAR, cap)
            sc.race(F_CAPDATA, 1)
            sc.glob(G_G1_SAMPLES, samples)
            sc.rc(cap, R_LAPS, 1)
            sc.op(OP_FINISH, cap, 0, 0, NORMAL)
    sc.tag("update ghost")
    for stage in (3, 4):
        for cap in (-1, 2):
            for rep in (0, 1):
                for t in (0, 1, 4000, 0x7fffffff, 0x7ffffffe, 0x80000000):
                    for answer in (0, 1, -1):
                        field(sc, n=3, players=1, rnd=rnd)
                        sc.race(F_STAGE, stage)
                        sc.race(F_CAPCAR, cap)
                        sc.race(F_CAPDATA, 1)
                        sc.race(F_REPDATA, rep)
                        sc.race(F_WO, 1)
                        sc.race(F_RACETIME, t)
                        sc.glob(G_WO_ENABLED, 7)
                        sc.glob(G_GETSAMPLE, answer)
                        for k in range(16):
                            sc.op(OP_SAMPLE, k, f32(rnd.uniform(-90, 90)))
                        sc.pos(2, f32(rnd.uniform(-500, 500)),
                               f32(rnd.uniform(-500, 500)),
                               f32(rnd.uniform(-5, 5)),
                               f32(rnd.uniform(-1, 1)))
                        sc.op(OP_UPDATE_GHOST)
    # Through Update.
    for stage in (3, 4):
        for rep in (0, 1):
            field(sc, n=3, players=1, rnd=rnd)
            sc.race(F_STAGE, stage)
            sc.race(F_CAPCAR, 1)
            sc.race(F_CAPDATA, 1)
            sc.race(F_REPDATA, rep)
            sc.race(F_WO, 1)
            sc.glob(G_GETSAMPLE, 1)
            for k in range(16):
                sc.op(OP_SAMPLE, k, f32(rnd.uniform(-90, 90)))
            sc.op(OP_UPDATE)

    # -- Update: the countdown --------------------------------------------
    sc.tag("update, the countdown")
    for beacop in (0, 1):
        for go, cd, frames in ((0, 0, 100), (0, 1000, 1000), (0, 1000, 1161),
                               (0, 1000, 1162), (0, 1000, 1163),
                               (0, 1000, 1180), (0, 1000, 1500),
                               (2000, 0, 2000), (2000, 0, 2060),
                               (2000, 0, 2061), (2000, 1000, 2010)):
            for stage in (2, 3, 4):
                field(sc, n=2, players=1)
                sc.race(F_STAGE, stage)
                sc.race(F_GO, go)
                sc.race(F_COUNTDOWN, cd)
                sc.glob(G_FRAMES, frames)
                sc.glob(G_BEACOP, beacop)
                sc.glob(G_TIMER, 41234 + frames)
                sc.op(OP_UPDATE)

    # -- Update: the best lap ---------------------------------------------
    sc.tag("update, the best lap")
    for best in (NO_TIME, 50000, 49999, 0, 0x80000000, 0xffffffff):
        for mine in (50000, 49999, 50001, 0x80000001, NO_TIME):
            for players in (0, 1, 2):
                field(sc, n=3, players=players)
                sc.race(F_BEST, best)
                sc.rc(0, R_BEST + 0, mine)
                sc.rc(1, R_BEST + 0, (mine - 3) & M32)
                sc.rc(2, R_BEST + 0, 1)
                sc.rc(1, R_REASON, NORMAL if mine & 1 else NOT_FINISHED)
                sc.op(OP_UPDATE)
    # The race time a tick either side of a hundredth.
    sc.tag("update, the race time")
    for dt in (0, 1, 19, 20, 21, 39, 40, 41, 4000, 0x7fffffff, -40, -41):
        field(sc, n=1, players=1, start=1000)
        sc.glob(G_TIMER, (1000 + dt) & M32)
        sc.op(OP_UPDATE)

    # -- Update: the forced finish ----------------------------------------
    sc.tag("update, forced")
    for fpos in (1, 3, 4, 5, -1):
        for fplayer in (0, 1, 2):
            for cops in ((None, None), (-1, None), (0, -2), (1, -1), (2, 0),
                         (2, 1), (6, 1), (3, 5)):
                field(sc, n=5, players=2)
                sc.race(F_FPOS, fpos)
                sc.race(F_FPLAYER, fplayer)
                sc.race(F_NFIN, 3)
                if cops[0] is not None:
                    cop_world(sc, cops[0], cops[1])
                sc.op(OP_UPDATE)
    # The player already finished, and its car not the first in order.
    for reason in (NOT_FINISHED, NORMAL):
        field(sc, n=4, players=2)
        for i, j in enumerate((3, 1, 2, 0)):
            sc.order(i, j)
        sc.rc(1, R_REASON, reason)
        sc.race(F_FPOS, 2)
        sc.race(F_FPLAYER, 1)
        sc.op(OP_UPDATE)
    # Two cars of the one player: only the first in order finishes.
    field(sc, n=5, players=1)
    sc.car(3, C_PLAYER, 0)
    sc.race(F_FPOS, 2)
    sc.race(F_FPLAYER, 0)
    sc.op(OP_UPDATE)

    # -- Update: lap knockout, time trial, laps led, the finish ------------
    sc.tag("update, knockout")
    for n in (2, 4, 6, 8):
        for crossed, laps, pos in ((1, 3, 1), (1, 2, 1), (0, 3, 1),
                                   (1, 1, 3), (1, 0, n), (1, -1, n + 1)):
            field(sc, n=n, players=1, laps=9)
            sc.glob(G_RACETYPE, 3)
            k = n // 2
            sc.rc(k - 1, R_CROSSED, crossed)
            sc.rc(k - 1, R_LAPS, laps + n - 4)
            sc.rc(k - 1, R_POS, pos)
            sc.rc(n - 1, R_REASON, KNOCKED_OUT)
            sc.op(OP_UPDATE)
    sc.tag("update, time trial")
    for tt in (60000, 59999, 60001, 0, 0x80000000, NO_TIME):
        for lap in (60000, 0, NO_TIME, 0x80000000, 1, 0xffffffff):
            for crossed in (0, 1):
                field(sc, n=3, players=1, laps=0, finish_line=2)
                sc.glob(G_RACETYPE, 2)
                sc.glob(G_TT, tt)
                sc.rc(0, R_CROSSED, crossed)
                sc.rc(0, R_RUN + 2, lap)
                sc.rc(1, R_CROSSED, 1)
                sc.rc(1, R_REASON, NORMAL)
                sc.rc(1, R_RUN + 2, 1)
                sc.op(OP_UPDATE)
    sc.tag("update, laps led and the finish")
    for laps_in_race in (0, 2):
        for case in range(6):
            field(sc, n=5, players=2, laps=laps_in_race)
            sc.rc(0, R_CROSSED, case & 1)
            sc.rc(0, R_POS, 1 if case < 4 else 2)
            sc.rc(0, R_LED, (0x7fff, 3, -1, 0, 5, 9)[case])
            sc.rc(0, R_LAPS, 2 if case in (1, 3, 5) else 1)
            sc.rc(1, R_LAPS, 2)
            sc.rc(1, R_CROSSED, 1)
            sc.rc(1, R_POS, 1)
            sc.rc(2, R_NEWLAP, 1)
            sc.rc(3, R_REASON, NORMAL)
            sc.rc(3, R_CROSSED, 1)
            sc.rc(3, R_POS, 1)
            sc.rc(3, R_LAPS, 2)
            sc.rc(4, R_LAPS, laps_in_race)
            sc.rc(4, R_CROSSED, case & 1)
            sc.op(OP_UPDATE)

    # -- a race, run --------------------------------------------------------
    sc.tag("a race")
    field(sc, n=8, players=2, laps=2, start=0)
    sc.race(F_STAGE, STAGE_COUNTDOWN)
    sc.race(F_GO, 100)
    sc.glob(G_FRAMES, 120)
    sc.glob(G_TIMER, 0)
    sc.op(OP_UPDATE)
    for step in range(60):
        timer = 400 + 7000 * step
        sc.glob(G_TIMER, timer)
        for j in range(NCARS):
            laps = min(2, (step * (9 + j)) // 140)
            sc.rc(j, R_LAPS, laps)
            sc.rc(j, R_CROSSED, 1 if (step * (9 + j)) % 140 < 9 + j else 0)
            sc.rc(j, R_CLE, f32(step * (9 + j) / 140.0))
            sc.rc(j, R_PREV, j + 1)
            sc.rc(j, R_POS, (j + step // 7) % NCARS + 1)
            sc.rc(j, R_BCT + 0, timer - 300 * j)
            sc.car(j, C_SPEED, f32(35.0 + 2 * j + step % 5))
        sc.op(OP_UPDATE)

    # -- random rounds ------------------------------------------------------
    sc.tag("random")
    for k in range(300):
        n = rnd.randint(0, 8)
        np = rnd.randint(0, 2)
        laps = rnd.choice((0, 1, 2, 3))
        field(sc, n=n, players=np, laps=laps,
              start=rnd.randrange(0, 1 << 32),
              timer=rnd.randrange(0, 1 << 32),
              start_line=rnd.randint(0, 4), finish_line=rnd.randint(0, 4),
              rnd=rnd)
        perm = list(range(NCARS))
        rnd.shuffle(perm)
        for i, j in enumerate(perm):
            sc.order(i, j)
        positions = list(range(1, n + 1))
        rnd.shuffle(positions)
        for j in range(NCARS):
            sc.rc(j, R_LAPS, rnd.randint(-1, 4))
            if j < n:
                sc.rc(perm[j], R_POS, positions[j])
                sc.rc(perm[j], R_PREV, rnd.choice(positions))
            sc.rc(j, R_ORDER, rnd.choice((0, 0, 0, 1, 2, 3)))
            sc.rc(j, R_CROSSED, rnd.randint(0, 1))
            sc.rc(j, R_NEWLAP, rnd.randint(0, 1))
            sc.rc(j, R_LED, rnd.randint(-2, 5))
            sc.rc(j, R_REASON, rnd.choice((0, 0, 0, 1, 3)))
            sc.rc(j, R_CLE, f32(rnd.uniform(-0.5, 4.0)))
            for b in range(5):
                sc.rc(j, R_BEST + b, rnd.choice((NO_TIME,
                                                 rnd.randrange(1 << 32))))
                sc.rc(j, R_RUN + b, rnd.choice((NO_TIME, 0,
                                                rnd.randrange(1 << 32))))
                sc.rc(j, R_BCT + b, rnd.randrange(1 << 32))
            sc.pos(j, f32(rnd.uniform(-60, 60)), f32(rnd.uniform(-60, 60)),
                   f32(rnd.uniform(-3, 3)))
            sc.car(j, C_SPEED, f32(rnd.uniform(0, 80)))
            sc.car(j, C_MODE, rnd.choice((1, 2, 2, 3)))
            sc.car(j, C_TIMEOUT, f32(rnd.uniform(-5, 30)))
        sc.race(F_STAGE, rnd.choice((2, 3, 4, 4)))
        sc.race(F_GO, rnd.choice((0, 0, rnd.randint(1, 9000))))
        sc.race(F_COUNTDOWN, rnd.choice((0, rnd.randint(1, 9000))))
        sc.race(F_BEST, rnd.choice((NO_TIME, rnd.randrange(1 << 32))))
        sc.race(F_NFIN, rnd.randint(0, 3))
        sc.glob(G_FRAMES, rnd.randint(0, 9500))
        sc.glob(G_RACETYPE, rnd.choice((1, 2, 3, 4)))
        sc.glob(G_TT, rnd.choice((NO_TIME, rnd.randrange(1 << 32))))
        sc.glob(G_BEACOP, rnd.randint(0, 1))
        sc.glob(G_PULLTO, f32(rnd.uniform(0, 20)))
        for p in range(np):
            sc.player(p, PL_TFR, rnd.choice((0, 0, 99)))
        if np and rnd.random() < 0.3:
            sc.race(F_FPOS, rnd.randint(-1, n + 1))
            sc.race(F_FPLAYER, rnd.randint(0, 1))
            if rnd.random() < 0.5:
                cop_world(sc, rnd.randint(-1, 6), rnd.randint(-2, 7))
        for _ in range(rnd.randint(1, 3)):
            sc.glob(G_TIMER, rnd.randrange(1 << 32))
            sc.op(OP_UPDATE)

    return sc


# ================================================================ the model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        self.sample = [0] * 16
        self.answer = 0
        self.stubs()
        self.reset()

    def emit(self, s):
        self.out.append(s)

    def w(self, a):
        return self.e.u32(a)

    # ---- addresses ---------------------------------------------------------

    def car_addr(self, i):
        return 0 if i == -1 else CARS + 0x400 * i

    def player_addr(self, i):
        return 0 if i == -1 else PLAYERS + 0x100 * i

    def rc_addr(self, j):
        return 0 if j == -1 else R + TABLE + RC_SIZE * j

    def aicc_addr(self, k, i):
        return AICCS + 0x400 * (8 * k + i)

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        names = {R: "race", R + 12: "race+12", R + 16: "race+16",
                 G1: "g1", G2: "g2", WO: "wo", RM: "rm", START: "start"}
        if a in names:
            return names[a]
        for i in range(NCARS):
            if a == self.car_addr(i):
                return "c%d" % i
            if a == self.rc_addr(i):
                return "r%d" % i
            for k in range(2):
                if a == self.aicc_addr(k, i):
                    return "%s%d" % ("ab"[k], i)
        for i in range(NPLAYERS):
            if a == self.player_addr(i):
                return "p%d" % i
        return "?"

    def matrix_str(self, a):
        return " ".join(fx(self.w(a + 4 * k)) for k in range(16))

    # ---- the stand-ins ---------------------------------------------------

    def stubs(self):
        e = self.e

        def arg(i):
            return e.reg[4 + i] & M32

        def cstr(p):
            end = e.mem.index(b"\0", p)
            return e.mem[p:end].decode("latin-1")

        def laps(em):
            self.emit("  laps %s" % self.label(arg(0)))

        def stage(em):
            self.emit("  stage %d" % s32(arg(1)))
            e.put32(arg(0), arg(1))

        def sort(em):
            self.emit("  sort %s" % self.label(arg(0)))

        def mode(em):
            c, m = arg(0), arg(1)
            self.emit("  mode %s %d" % (self.label(c), s32(m)))
            e.put32(c + 32, m)
            if m == AI_CONTROL:
                i = (c - CARS) // 0x400
                b = self.aicc_addr(1, i)
                e.put32(b + 528, 11)
                e.put32(b + 548, fb(1e7))
                e.put32(c + 40, b)

        def blink(em):
            self.emit("  blink %s" % self.label(arg(0)))

        def event(em):
            self.emit("  event %s %s %s" % (self.label(arg(0)),
                                            fx(e.fpr[12]), cstr(arg(1))))

        def record(em):
            assert arg(0) == THE_RACE_EVENT
            self.emit("  record %s %s %d" % (self.label(arg(1)),
                                             self.label(arg(2)),
                                             s32(arg(3))))

        def lap_speech(em):
            self.emit("  lapspeech %s %d" % (self.label(arg(0)),
                                             s32(arg(1))))

        def clear_queue(em):
            assert arg(0) == WEDGE
            self.emit("  clearqueue")

        def finish_sound(em):
            self.emit("  finishsound %s" % self.label(arg(0)))

        def add_sample(em):
            self.emit("  addsample %s t %s m %s" % (
                self.label(arg(0)), fx(self.w(arg(2))),
                self.matrix_str(arg(1))))

        def get_sample(em):
            self.emit("  getsample %s %s %s -> %d" % (
                self.label(arg(0)), self.label(arg(2)), fx(self.w(arg(2))),
                self.answer))
            for k in range(16):
                e.put32(arg(1) + 4 * k, self.sample[k])
            return self.answer

        def write_file(em):
            self.emit("  write %s %s %d" % (cstr(arg(0)), self.label(arg(1)),
                                            s32(arg(2))))

        def delete(em):
            self.emit("  delete %s" % self.label(arg(0)))

        def print_to_string(em):
            pass

        e.stub(UPDATE_LAP_COUNTS, laps)
        e.stub(SET_RACE_STAGE, stage)
        e.stub(SORT, sort)
        e.stub(SET_CONTROL_MODE, mode)
        e.stub(BLINK, blink)
        e.stub(REGISTER_EVENT, event)
        e.stub(RECORD_RESULTS, record)
        e.stub(LAP_SPEECH, lap_speech)
        e.stub(CLEAR_QUEUE, clear_queue)
        e.stub(FINISH_SOUND, finish_sound)
        e.stub(ADD_SAMPLE, add_sample)
        e.stub(GET_SAMPLE, get_sample)
        e.stub(WRITE_FILE, write_file)
        e.stub(BDELETE, delete)
        e.stub(PRINT_TO_STRING, print_to_string)

    # ---- the world -------------------------------------------------------

    def reset(self):
        e = self.e
        e.mem[R:WORLD_END] = bytes(WORLD_END - R)
        for i in range(NCARS):
            e.put32(R + ORDER + 4 * i, self.rc_addr(i))
            e.put32(self.rc_addr(i), self.car_addr(i))
            e.put32(self.car_addr(i) + 28, self.rc_addr(i))
            e.put32(self.car_addr(i) + 40, self.aicc_addr(0, i))
        name = FILE_NAME.encode("latin-1") + b"\0"
        e.write(R + FILENAME, name)
        for g in (WORLD_TIMER_GP, WORLD_FRAMES_GP, NPLAYERS_GP, BYINDEX_GP,
                  BYINDEX_GP + 4, COPMGR_GP):
            e.put32(GP + g, 0)
        for off in (RP_RACETYPE, RP_TT, RP_BEACOP):
            e.put32(RACE_PARAMS + off, 0)
        e.put32(GP + PULLTO_GP, fb(15.0))
        e.put32(GP + CURRENT_RACE_GP, R)
        e.put32(GP + REPLAY_GP, RM)
        e.put32(GP + WEDGE_GP, WEDGE)
        self.sample = [0] * 16
        self.answer = 0

    def poke_race(self, f, v):
        e = self.e
        if f in RACE_OFF:
            e.put32(R + RACE_OFF[f], v)
        elif f == F_STARTLINE:
            e.write(R + STARTLINE, bytes([v & 0xff]))
        elif f == F_FINISHLINE:
            e.write(R + FINISHLINE, bytes([v & 0xff]))
        elif f == F_ORDER:
            j = v & 15
            e.put32(R + ORDER + 4 * (v >> 4 & 7),
                    0 if j == 15 else self.rc_addr(j))
        elif f == F_CAPCAR:
            e.put32(R + CAPCAR, self.car_addr(s32(v)))
        elif f == F_CAPDATA:
            e.put32(R + CAPDATA, G1 if v else 0)
        elif f == F_REPDATA:
            e.put32(R + REPDATA, G2 if v else 0)
        elif f == F_WO:
            e.put32(R + WOPTR, WO if v else 0)
        else:
            raise ValueError("race field %d" % f)

    def poke_rc(self, j, f, v):
        e = self.e
        a = self.rc_addr(j)
        if R_BCT <= f < R_BCT + 5:
            e.put32(a + 36 + 4 * (f - R_BCT), v)
        elif R_RUN <= f < R_RUN + 5:
            e.put32(a + 56 + 4 * (f - R_RUN), v)
        elif R_BEST <= f < R_BEST + 5:
            e.put32(a + 96 + 4 * (f - R_BEST), v)
        elif f == R_CAR:
            e.put32(a, self.car_addr(s32(v)))
        elif f in RC_OFF:
            off, n = RC_OFF[f]
            e.write(a + off, struct.pack("<I", v & M32)[:n])
        else:
            raise ValueError("racing car field %d" % f)

    def poke_car(self, i, f, v):
        e = self.e
        c = self.car_addr(i)
        if C_POS <= f < C_POS + 4:
            e.put32(c + 96 + 4 * (f - C_POS), v)
        elif C_BODY <= f < C_BODY + 16:
            e.put32(c + 144 + 4 * (f - C_BODY), v)
        elif f == C_PLAYER:
            e.put32(c + 24, self.player_addr(s32(v)))
        elif f == C_RC:
            e.put32(c + 28, self.rc_addr(s32(v)))
        elif f == C_MODE:
            e.put32(c + 32, v)
        elif f == C_CTRL:
            e.put32(c + 40, 0 if s32(v) < 0 else self.aicc_addr(v & 1, i))
        elif f == C_FORCE:
            e.put32(self.aicc_addr(0, i) + 528, v)
        elif f == C_TIMEOUT:
            e.put32(self.aicc_addr(0, i) + 548, v)
        elif f == C_SPEED:
            e.put32(c + 964, v)
        else:
            raise ValueError("car field %d" % f)

    def poke_player(self, i, f, v):
        e = self.e
        p = self.player_addr(i)
        off = {PL_NUMBER: 16, PL_TFR: 80, PL_FAL: 84}
        if f == PL_CAR:
            e.put32(p + 4, self.car_addr(s32(v)))
        elif f in off:
            e.put32(p + off[f], v)
        else:
            raise ValueError("player field %d" % f)

    def poke_global(self, f, v):
        e = self.e
        if G_COP <= f < G_COP + NCOPS:
            k = f - G_COP
            if s32(v) == -2:
                e.put32(COPMGR + 16 + 4 * k, 0)
            else:
                e.put32(COPMGR + 16 + 4 * k, COPS + 0x20 * k)
                e.put32(COPS + 0x20 * k + 4, self.car_addr(s32(v)))
            return
        gps = {G_TIMER: WORLD_TIMER_GP, G_FRAMES: WORLD_FRAMES_GP,
               G_NPLAYERS: NPLAYERS_GP, G_PULLTO: PULLTO_GP}
        if f in gps:
            e.put32(GP + gps[f], v)
        elif f in (G_BYINDEX0, G_BYINDEX1):
            e.put32(GP + BYINDEX_GP + 4 * (f - G_BYINDEX0),
                    self.player_addr(s32(v)))
        elif f == G_RACETYPE:
            e.put32(RACE_PARAMS + RP_RACETYPE, v)
        elif f == G_TT:
            e.put32(RACE_PARAMS + RP_TT, v)
        elif f == G_BEACOP:
            e.put32(RACE_PARAMS + RP_BEACOP, v)
        elif f == G_COPMGR:
            e.put32(GP + COPMGR_GP, COPMGR if v else 0)
        elif f == G_COPIDX:
            e.put32(COPMGR + 12, v)
        elif f == G_GETSAMPLE:
            self.answer = s32(v)
        elif f == G_G1_TIME:
            e.put32(G1 + 4, v)
        elif f == G_G1_SAMPLES:
            e.put32(G1 + 16, v)
        elif f == G_G2_TIME:
            e.put32(G2 + 4, v)
        elif f == G_G2_LAPS:
            e.put32(G2 + 8, v)
        elif f == G_WO_ENABLED:
            e.put32(WO + 12, v)
        else:
            raise ValueError("global %d" % f)

    # ---- the dump --------------------------------------------------------

    def dump(self):
        e, w = self.e, self.w
        self.emit("race st %d go %d cd %d start %s time %s best %s n %d "
                  "fin %d laps %d fpos %d fpl %d cap %s capd %s"
                  % (s32(w(R)), s32(w(R + 4)), s32(w(R + 8)), fx(w(R + 12)),
                     fx(w(R + 16)), fx(w(R + 20)), s32(w(R + 24)),
                     s32(w(R + 28)), s32(w(R + 1604)), s32(w(R + 1608)),
                     s32(w(R + 1612)), self.label(w(R + CAPCAR)),
                     self.label(w(R + CAPDATA))))
        self.emit("order " + " ".join(self.label(w(R + ORDER + 4 * i))
                                      for i in range(NCARS)))
        for j in range(NCARS):
            a = self.rc_addr(j)
            self.emit("r%d car %s laps %d pos %d prev %d ord %d x %d nl %d "
                      "led %d why %d cle %s fle %s t %s best %s"
                      % (j, self.label(w(a)), s8(e.u8(a + 9)),
                         s8(e.u8(a + 10)), s8(e.u8(a + 11)),
                         s8(e.u8(a + 12)), s8(e.u8(a + 13)),
                         s8(e.u8(a + 14)), s16(e.u16(a + 16)),
                         s16(e.u16(a + 18)), fx(w(a + 20)), fx(w(a + 32)),
                         fx(w(a + 180)),
                         " ".join(fx(w(a + 96 + 4 * k)) for k in range(5))))
        for i in range(NCARS):
            c = self.car_addr(i)
            ctl = w(c + 40)
            if ctl:
                self.emit("c%d mode %d ctl %s force %d to %s"
                          % (i, s32(w(c + 32)), self.label(ctl),
                             s32(w(ctl + 528)), fx(w(ctl + 548))))
            else:
                self.emit("c%d mode %d ctl null" % (i, s32(w(c + 32))))
        for i in range(NPLAYERS):
            p = self.player_addr(i)
            self.emit("p%d tfr %s fal %d" % (i, fx(w(p + 80)),
                                             s32(w(p + 84))))
        self.emit("wo en %d m %s" % (s32(w(WO + 12)),
                                     self.matrix_str(WO + 32)))
        self.emit("g1 t %s g2 t %s" % (fx(w(G1 + 4)), fx(w(G2 + 4))))

    # ---- the run ---------------------------------------------------------

    def run(self, sc):
        e = self.e
        tags = sc.tags
        for o in sc.ops:
            code, a = o[0], o[1:]
            if code == OP_TAG:
                self.emit("[%s]" % tags[a[0]])
            elif code == OP_RESET:
                self.reset()
            elif code == OP_RACE:
                self.poke_race(a[0], a[1])
            elif code == OP_RC:
                self.poke_rc(a[0], a[1], a[2])
            elif code == OP_CAR:
                self.poke_car(a[0], a[1], a[2])
            elif code == OP_PLAYER:
                self.poke_player(a[0], a[1], a[2])
            elif code == OP_GLOBAL:
                self.poke_global(a[0], a[1])
            elif code == OP_SAMPLE:
                self.sample[a[0]] = a[1] & M32
            elif code == OP_UPDATE:
                self.emit("update")
                e.call(UPDATE, R)
                self.dump()
            elif code == OP_FINISH:
                i, pos, blink, why = (s32(x) for x in a)
                self.emit("finish %d %d %d %d" % (i, pos, blink, why))
                e.call(FINISH, R, i, pos, blink, why)
                self.dump()
            elif code == OP_FINISH_CAR:
                c, pos, blink, why = (s32(x) for x in a)
                self.emit("finishcar %s %d %d %d"
                          % (self.label(self.car_addr(c)), pos, blink, why))
                e.call(FINISH_CAR, R, self.car_addr(c), pos, blink, why)
                self.dump()
            elif code == OP_PROJECT:
                j, laps, start = s32(a[0]), s32(a[1]), a[2] & M32
                e.put32(START, start)
                self.emit("project %s %d %s" % (self.label(self.rc_addr(j)),
                                                laps, fx(start)))
                e.call(PROJECT, self.rc_addr(j), laps, START)
                self.dump()
            elif code == OP_MONITOR:
                self.emit("monitor")
                e.call(MONITOR, R)
                self.dump()
            elif code == OP_SAVE_GHOST:
                self.emit("saveghost %s" % self.label(self.rc_addr(a[0])))
                e.call(SAVE_GHOST, R, self.rc_addr(a[0]))
                self.dump()
            elif code == OP_UPDATE_GHOST:
                self.emit("updateghost")
                e.call(UPDATE_GHOST, R)
                self.dump()
            elif code == OP_LEADING:
                r = e.call(LEADING, R)
                self.emit("leading -> %s" % self.label(r))
            elif code == OP_FINISHER:
                r = e.call(FINISHER, R, a[0])
                self.emit("finisher %d -> %s" % (s32(a[0]), self.label(r)))
            elif code == OP_NEXT_RANK:
                r = e.call(NEXT_RANK, R)
                self.emit("nextrank -> %d" % r)
            elif code == OP_SIMULATE:
                self.emit("simulate")
                e.call(SIMULATE, R)
                self.dump()
            elif code == OP_SET_FINISHED:
                p = self.player_addr(s32(a[0]))
                self.emit("setfinished %s" % self.label(p))
                e.call(SET_FINISHED, p)
                self.dump()
            elif code == OP_DUMP:
                self.dump()
            else:
                raise ValueError("op %d" % code)
        return self.out


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc.encode().hex().splitlines()
                               + sc.tags, lambda s: Model().run(sc),
                               cut=MUTATIONS_HEADER)


# ================================================================ the build


def build_harness(tmp, name="raceupdate_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, ops_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(ops_path)], stdout=fh,
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


def M(name, before, after, path=RUC):
    return (name, path, before, after)


MUTATIONS = [
    # -- ProjectRaceTime --------------------------------------------------
    M("pr-floor", "if (done < RACE_ROUND_SECONDS)",
      "if (done < 0.02f)"),
    M("pr-floor-gone", "    if (done < RACE_ROUND_SECONDS)\n"
      "        done = RACE_ROUND_SECONDS;\n", ""),
    M("pr-n", "float n = (float)laps;", "float n = (float)(laps + 1);"),
    M("pr-signed",
      "s = (float)(int32_t)((uint32_t)WorldTimer - start->PackedTime)",
      "s = (float)((uint32_t)WorldTimer - start->PackedTime)"),
    M("pr-tick", "start->PackedTime)\n        * RACE_TICK_SECONDS;",
      "start->PackedTime)\n        * 0.0025f;"),
    M("pr-div", "timer_set_time(&t, s / done);", "timer_set_time(&t, s);"),
    M("pr-round", "    rc->RaceTime = t;\n"
      "    timer_round(&rc->RaceTime, RACE_ROUND_SECONDS);\n",
      "    rc->RaceTime = t;\n"),
    M("pr-done", "if (rc->NumLapsCompleted != 0 || laps <= 0)",
      "if (rc->NumLapsCompleted > 0 || laps <= 0)"),
    M("pr-laps0", "if (rc->NumLapsCompleted != 0 || laps <= 0)",
      "if (rc->NumLapsCompleted != 0 || laps < 0)"),
    M("pr-laps-gone", "if (rc->NumLapsCompleted != 0 || laps <= 0)",
      "if (rc->NumLapsCompleted != 0)"),
    M("pr-line", "racingcar_get_last_start_line_crossing_time(rc)",
      "racingcar_get_last_finish_line_crossing_time(rc)"),
    M("pr-best-done", "    s = s / done;\n    s = s / n;\n",
      "    s = s / n;\n"),
    M("pr-best-n", "    s = s / done;\n    s = s / n;\n",
      "    s = s / done;\n"),
    M("pr-best-half",
      "best->PackedTime = (uint32_t)ee_trunc_w(s * 4000.0f + 0.5f);",
      "best->PackedTime = (uint32_t)ee_trunc_w(s * 4000.0f);"),
    M("pr-best-which", "best = racingcar_get_last_best_lap_time(rc);",
      "best = racingcar_get_last_lap_time(rc);"),
    M("pr-best-round",
      "    timer_round(racingcar_get_last_best_lap_time(rc), "
      "RACE_ROUND_SECONDS);\n", ""),

    # -- MonitorLeadership ------------------------------------------------
    M("mo-players", "for (i = 0; i < PlayerNumPlayers; i++) {",
      "for (i = 0; i < 1 && i < PlayerNumPlayers; i++) {"),
    M("mo-null", "        if (p == NULL)\n            continue;\n"
      "        rc = p->MyCar->pRacingCar;",
      "        rc = p->MyCar->pRacingCar;"),
    M("mo-same", "        if (pos == prev)\n            continue;\n", ""),
    M("mo-prev-hi", "if (r->NumRacingCars < prev || prev < 1)",
      "if (r->NumRacingCars <= prev || prev < 1)"),
    M("mo-other", "other = r->pRacingCars[prev - 1]->pCar;",
      "other = r->pRacingCars[pos - 1]->pCar;"),
    M("mo-speed-who", "speed = mine->State.VelocityMagnitude;",
      "speed = other->State.VelocityMagnitude;"),
    M("mo-speed", "if (!(LEAD_MIN_SPEED < speed))",
      "if (!(LEAD_MIN_SPEED <= speed))"),
    M("mo-dist", "< LEAD_MAX_DISTANCE))", "<= LEAD_MAX_DISTANCE))"),
    M("mo-dist-z", "    return sqrtf((dx * dx + dy * dy) + dz * dz);",
      "    return sqrtf(dx * dx + dy * dy);"),
    M("mo-dist-y", "    return sqrtf((dx * dx + dy * dy) + dz * dz);",
      "    return sqrtf(dx * dx + dz * dz);"),
    M("mo-gain", "        if (pos < prev)\n", "        if (pos > prev)\n"),
    M("mo-gain-pos", "ee_div(4.0f, (float)pos) + 1.0f",
      "ee_div(4.0f, (float)prev) + 1.0f"),
    M("mo-gain-1", "ee_div(4.0f, (float)pos) + 1.0f",
      "ee_div(4.0f, (float)pos) + 2.0f"),
    M("mo-lose", "interesting(2.0f / (float)prev, \"LosePosition\");",
      "interesting(2.0f / (float)pos, \"LosePosition\");"),
    M("mo-close", "if (fabsf(speed - other_speed) < LEAD_CLOSE_SPEED)",
      "if (fabsf(speed - other_speed) <= LEAD_CLOSE_SPEED)"),
    M("mo-close-abs", "if (fabsf(speed - other_speed) < LEAD_CLOSE_SPEED)",
      "if (speed - other_speed < LEAD_CLOSE_SPEED)"),
    M("mo-close-val", "interesting(2.5f, \"ClosePass\");",
      "interesting(2.0f, \"ClosePass\");"),
    M("mo-replay", "RegisterInterestingEvent(pReplayManager, value, what);",
      "RegisterInterestingEvent(pReplayManager, value + 1.0f, what);"),

    # -- MaybeSaveGhostCarData ----------------------------------------------
    M("sg-car", "    if (rc->pCar != r->pCapturingGhostCar)\n        return;\n"
      "    d = r->pCapturingGhostCarData;",
      "    d = r->pCapturingGhostCarData;"),
    M("sg-time", "    d->RaceTime = rc->RaceTime;\n", ""),
    M("sg-norep", "        save = 1;\n", "        save = 0;\n"),
    M("sg-lt", "save = (int32_t)rc->RaceTime.PackedTime < "
      "(int32_t)best.PackedTime;",
      "save = (int32_t)rc->RaceTime.PackedTime <= "
      "(int32_t)best.PackedTime;"),
    M("sg-signed", "save = (int32_t)rc->RaceTime.PackedTime < "
      "(int32_t)best.PackedTime;",
      "save = rc->RaceTime.PackedTime < best.PackedTime;"),
    M("sg-rep-laps", "        if (r->pReplayingGhostCarData->NumLaps != "
      "r->NumLapsInRace)\n            save = 0;\n", ""),
    M("sg-laps", "    if (rc->NumLapsCompleted != r->NumLapsInRace)\n"
      "        save = 0;\n", ""),
    M("sg-size", "(GHOSTCAR_MAX_SAMPLES - d->NumSamples) * "
      "GHOSTCAR_SAMPLE_BYTES",
      "(GHOSTCAR_MAX_SAMPLES - d->NumSamples - 1) * "
      "GHOSTCAR_SAMPLE_BYTES"),
    M("sg-free", "    bFree(r->pCapturingGhostCarData);\n", ""),
    M("sg-nocar", "    r->pCapturingGhostCar = NULL;\n", ""),
    M("sg-nodata", "    r->pCapturingGhostCarData = NULL;\n", ""),

    # -- UpdateGhostCar ---------------------------------------------------
    M("ug-stage", "if (r->RaceStage == RACE_STAGE_RACING && "
      "r->pCapturingGhostCar != NULL) {",
      "if (r->pCapturingGhostCar != NULL) {"),
    M("ug-cap", "if (r->RaceStage == RACE_STAGE_RACING && "
      "r->pCapturingGhostCar != NULL) {",
      "if (r->RaceStage == RACE_STAGE_RACING) {"),
    M("ug-pos", "        memcpy(&m.v3, &c->State.Position, sizeof m.v3);\n",
      ""),
    M("ug-time", "        Timer t = r->RaceTime;\n",
      "        Timer t = r->StartTime;\n"),
    M("ug-rep", "if (r->pReplayingGhostCarData == NULL || "
      "!timer_is_valid(&r->RaceTime))",
      "if (!timer_is_valid(&r->RaceTime))"),
    M("ug-valid", "if (r->pReplayingGhostCarData == NULL || "
      "!timer_is_valid(&r->RaceTime))",
      "if (r->pReplayingGhostCarData == NULL)"),
    M("ug-drop", "m.v3.z = m.v3.z + GHOST_DROP;", "m.v3.z = m.v3.z;"),
    M("ug-drop-y", "m.v3.z = m.v3.z + GHOST_DROP;",
      "m.v3.y = m.v3.y + GHOST_DROP;"),
    M("ug-matrix", "        r->pReplayingGhostCarWorldObject->Matrix = m;\n",
      ""),
    M("ug-on", "r->pReplayingGhostCarWorldObject->Enabled = 1;",
      "r->pReplayingGhostCarWorldObject->Enabled = 2;"),
    M("ug-off", "        r->pReplayingGhostCarWorldObject->Enabled = 0;\n",
      ""),

    # -- FinishCar ----------------------------------------------------------
    M("fc-won", "if (reason == RACING_CAR_BE_THE_COP_WON) {",
      "if (reason == RACING_CAR_BE_THE_COP_LOST) {"),
    M("fc-won-start", "        rc->RaceTime.PackedTime =\n"
      "            (uint32_t)WorldTimer - r->StartTime.PackedTime;\n",
      "        rc->RaceTime.PackedTime =\n"
      "            (uint32_t)WorldTimer;\n"),
    M("fc-won-round", "        timer_round(&rc->RaceTime, RACE_ROUND_SECONDS);\n"
      "    } else if", "    } else if"),
    M("fc-lost", "} else if (reason == RACING_CAR_BE_THE_COP_LOST) {",
      "} else if (reason == RACING_CAR_ARRESTED) {"),
    M("fc-lost-signed",
      "(float)(int32_t)TheRaceParameters.TimeTrialTime.PackedTime",
      "(float)TheRaceParameters.TimeTrialTime.PackedTime"),
    M("fc-lost-add", "                  * RACE_TICK_SECONDS + "
      "RACE_ROUND_SECONDS;",
      "                  * RACE_TICK_SECONDS;"),
    M("fc-lost-half", "rc->RaceTime.PackedTime = (uint32_t)ee_trunc_w("
      "s * 4000.0f + 0.5f);",
      "rc->RaceTime.PackedTime = (uint32_t)ee_trunc_w(s * 4000.0f);"),
    M("fc-lost-round", "(uint32_t)ee_trunc_w(s * 4000.0f + 0.5f);\n"
      "        timer_round(&rc->RaceTime, RACE_ROUND_SECONDS);\n",
      "(uint32_t)ee_trunc_w(s * 4000.0f + 0.5f);\n"),
    M("fc-pos0", "    if (position == 0) {\n        if (rc->NumLapsCompleted",
      "    if (position == 1) {\n        if (rc->NumLapsCompleted"),
    M("fc-done", "        if (rc->NumLapsCompleted == r->NumLapsInRace) {",
      "        if (rc->NumLapsCompleted >= r->NumLapsInRace) {"),
    M("fc-done-rank", "            rc->FinishingOrder = (int8_t)"
      "race_get_next_finish_rank(r);\n"
      "            rc->RaceTime.PackedTime =",
      "            rc->RaceTime.PackedTime ="),
    M("fc-cross", "racingcar_get_last_finish_line_crossing_time(rc)"
      "->PackedTime\n"
      "                - r->StartTime.PackedTime;",
      "racingcar_get_last_finish_line_crossing_time(rc)->PackedTime;"),
    M("fc-save", "            if (p != NULL)\n"
      "                race_maybe_save_ghost_car_data(r, rc);",
      "            race_maybe_save_ghost_car_data(r, rc);"),
    M("fc-save-gone", "            if (p != NULL)\n"
      "                race_maybe_save_ghost_car_data(r, rc);\n", ""),
    M("fc-proj-rank", "            rc->FinishingOrder = (int8_t)"
      "race_get_next_finish_rank(r);\n"
      "            racingcar_project_race_time",
      "            racingcar_project_race_time"),
    M("fc-proj-laps", "racingcar_project_race_time(rc, r->NumLapsInRace,",
      "racingcar_project_race_time(rc, r->NumLapsInRace + 1,"),
    M("fc-proj-gone", "            racingcar_project_race_time(rc, "
      "r->NumLapsInRace,\n"
      "                                        &r->StartTime);\n", ""),
    M("fc-pos-gt", "} else if (position > 0) {", "} else if (position > 1) {"),
    M("fc-pos-neg", "} else if (position > 0) {", "} else {"),
    M("fc-reason", "    rc->FinishReason = (int16_t)reason;\n", ""),
    M("fc-fle", "    rc->FinishedLapNumberExact = "
      "rc->CurrentLapNumberExact;\n", ""),
    M("fc-nfin", "    r->NumRacingCarsFinished++;\n", ""),
    M("fc-record", "gRaceEventRecordResultsFn(r, rc, rc->FinishingOrder);",
      "gRaceEventRecordResultsFn(r, rc, position);"),
    M("fc-player", "        player_set_finished_racing(p);\n", ""),
    M("fc-mode", "        car_set_control_mode(car, AI_CONTROL);",
      "        car_set_control_mode(car, REAL_CONTROL);"),
    M("fc-ai", "    if (car->TheControlMode == AI_CONTROL)\n"
      "        aicarcontroller_force_pull_over(",
      "    if (car->TheControlMode != REAL_CONTROL)\n"
      "        aicarcontroller_force_pull_over("),
    M("fc-pullto", "            AIActionPullOverCrossFinishLineTimeout);",
      "            15.0f);"),
    M("fc-blink", "    if (blink)\n        car_blink_blink_poof(car);",
      "    if (!blink)\n        car_blink_blink_poof(car);"),
    M("fp-force", "c->ForceCurrentAction = AIACTION_PULL_OVER;",
      "c->ForceCurrentAction = AIACTION_PULL_OVER + 1;", AICCH),
    M("fp-max", "c->PullOverTimeout = timeout < old ? timeout : old;",
      "c->PullOverTimeout = timeout > old ? timeout : old;", AICCH),
    M("fp-new", "c->PullOverTimeout = timeout < old ? timeout : old;",
      "c->PullOverTimeout = timeout;", AICCH),
    M("rs-finish-line",
      "Timer *racingcar_get_last_finish_line_crossing_time("
      "struct RacingCar *rc)\n"
      "{\n    return boundary_timer(rc->BoundaryCrossingTimes,\n"
      "                          pCurrentRace->FinishLineBoundaryNumber);",
      "Timer *racingcar_get_last_finish_line_crossing_time("
      "struct RacingCar *rc)\n"
      "{\n    return boundary_timer(rc->BoundaryCrossingTimes,\n"
      "                          pCurrentRace->StartLineBoundaryNumber);",
      RSC),

    # -- FinishCar by car ------------------------------------------------
    M("fb-match", "        if (r->pRacingCars[i] != rc)\n"
      "            continue;\n", ""),
    M("fb-pos", "        if (position == 0)\n"
      "            position = rc->RacePosition;\n", ""),
    M("fb-last", "    for (i = 0; i < r->NumRacingCars; i++) {\n"
      "        if (r->pRacingCars[i] != rc)",
      "    for (i = 0; i < r->NumRacingCars - 1; i++) {\n"
      "        if (r->pRacingCars[i] != rc)"),

    # -- the finders --------------------------------------------------------
    M("lu-best", "int32_t best = r->NumRacingCars + 1;",
      "int32_t best = r->NumRacingCars;"),
    M("lu-order", "        if (rc->FinishingOrder != 0)\n            continue;\n"
      "        if (rc->RacePosition < best) {",
      "        if (rc->RacePosition < best) {"),
    M("lu-lt", "if (rc->RacePosition < best) {",
      "if (rc->RacePosition <= best) {"),
    M("lu-keep", "            best = rc->RacePosition;\n            lead = rc;",
      "            lead = rc;"),
    M("gf-rank", "if (r->pRacingCars[i]->FinishingOrder == rank)",
      "if (r->pRacingCars[i]->FinishingOrder >= rank)"),
    M("gf-loop", "    for (i = 0; i < r->NumRacingCars; i++) {\n"
      "        if (r->pRacingCars[i]->FinishingOrder == rank)",
      "    for (i = 0; i <= r->NumRacingCars; i++) {\n"
      "        if (r->pRacingCars[i]->FinishingOrder == rank)"),
    M("nr-start", "    int32_t rank = 1;\n", "    int32_t rank = 0;\n"),

    # -- the forced finish ------------------------------------------------
    M("ff-nfin", "    r->NumRacingCarsFinished = 0;\n", ""),
    M("ff-reason", "        if (rc->FinishReason != RACING_CAR_NOT_FINISHED)\n"
      "            continue;\n        p = racingcar_get_player(rc);",
      "        p = racingcar_get_player(rc);"),
    M("ff-number", "if (p == NULL || p->PlayerNumber != "
      "r->ForceRaceFinishPlayerNum)",
      "if (p == NULL)"),
    M("ff-cop", "        if (cop != NULL && cop->pMyCar != NULL\n"
      "            && cop->pMyCar->pPlayer == p) {",
      "        if (cop != NULL && cop->pMyCar != NULL) {"),
    M("ff-cop-car", "        if (cop != NULL && cop->pMyCar != NULL\n"
      "            && cop->pMyCar->pPlayer == p) {",
      "        if (cop != NULL\n"
      "            && cop->pMyCar->pPlayer == p) {"),
    M("ff-at", "            at = -1;\n", "            at = 0;\n"),
    M("ff-won", "why = pos < r->NumRacingCars ? RACING_CAR_BE_THE_COP_WON",
      "why = pos <= r->NumRacingCars ? RACING_CAR_BE_THE_COP_WON"),
    M("ff-blink", "race_finish_car(r, i, at, 0, why);",
      "race_finish_car(r, i, at, 1, why);"),
    M("ff-break", "        race_finish_car(r, i, at, 0, why);\n"
      "        break;\n",
      "        race_finish_car(r, i, at, 0, why);\n"),
    M("ff-pos", "    r->ForceRaceFinishPosition = 0;\n"
      "    r->ForceRaceFinishPlayerNum = 0;\n",
      "    r->ForceRaceFinishPlayerNum = 0;\n"),
    M("ff-player", "    r->ForceRaceFinishPosition = 0;\n"
      "    r->ForceRaceFinishPlayerNum = 0;\n",
      "    r->ForceRaceFinishPosition = 0;\n"),

    # -- the knockout and the time trial ----------------------------------
    M("ko-crossed", "        if (!rc->CrossedFinishLine\n"
      "            || rc->NumLapsCompleted + rc->RacePosition",
      "        if (0\n"
      "            || rc->NumLapsCompleted + rc->RacePosition"),
    M("ko-sum", "rc->NumLapsCompleted + rc->RacePosition != "
      "r->NumRacingCars)",
      "rc->NumLapsCompleted + rc->RacePosition != "
      "r->NumRacingCars + 1)"),
    M("ko-from", "for (j = i + 1; j < r->NumRacingCars; j++) {",
      "for (j = i; j < r->NumRacingCars; j++) {"),
    M("ko-reason", "            if (r->pRacingCars[j]->FinishReason == "
      "RACING_CAR_NOT_FINISHED)\n"
      "                race_finish_car(r, j, j + 1, 1, "
      "RACING_CAR_KNOCKED_OUT);",
      "                race_finish_car(r, j, j + 1, 1, "
      "RACING_CAR_KNOCKED_OUT);"),
    M("ko-pos", "race_finish_car(r, j, j + 1, 1, RACING_CAR_KNOCKED_OUT);",
      "race_finish_car(r, j, j, 1, RACING_CAR_KNOCKED_OUT);"),
    M("ko-blink", "race_finish_car(r, j, j + 1, 1, RACING_CAR_KNOCKED_OUT);",
      "race_finish_car(r, j, j + 1, 0, RACING_CAR_KNOCKED_OUT);"),
    M("tt-crossed", "        if (!rc->CrossedFinishLine\n"
      "            || rc->FinishReason != RACING_CAR_NOT_FINISHED)\n"
      "            continue;\n        limit",
      "        if (rc->FinishReason != RACING_CAR_NOT_FINISHED)\n"
      "            continue;\n        limit"),
    M("tt-reason", "        if (!rc->CrossedFinishLine\n"
      "            || rc->FinishReason != RACING_CAR_NOT_FINISHED)\n"
      "            continue;\n        limit",
      "        if (!rc->CrossedFinishLine)\n"
      "            continue;\n        limit"),
    M("tt-valid", "        if (!timer_is_valid("
      "racingcar_get_last_lap_time(rc)))\n"
      "            continue;\n", ""),
    M("tt-le", "if (!(limit < (int32_t)racingcar_get_last_lap_time(rc)"
      "->PackedTime))",
      "if (!(limit <= (int32_t)racingcar_get_last_lap_time(rc)"
      "->PackedTime))"),
    M("tt-signed", "if (!(limit < (int32_t)racingcar_get_last_lap_time(rc)"
      "->PackedTime))",
      "if (!((uint32_t)limit < racingcar_get_last_lap_time(rc)"
      "->PackedTime))"),
    M("tt-pos", "race_finish_car(r, i, 0, 0, RACING_CAR_NORMAL_COMPLETION);\n"
      "    }\n}\n\nvoid race_update",
      "race_finish_car(r, i, 1, 0, RACING_CAR_NORMAL_COMPLETION);\n"
      "    }\n}\n\nvoid race_update"),

    # -- Update -------------------------------------------------------------
    M("up-cd", "race_get_countdown_number_to_display(r) == 4)",
      "race_get_countdown_number_to_display(r) == 3)"),
    M("up-cd-stage", "    if (r->RaceStage == RACE_STAGE_COUNTDOWN\n"
      "        && ",
      "    if (1\n        && "),
    M("up-time-stage", "    if (r->RaceStage == RACE_STAGE_RACING) {\n"
      "        r->RaceTime",
      "    if (1) {\n        r->RaceTime"),
    M("up-time", "        r->RaceTime.PackedTime =\n"
      "            (uint32_t)WorldTimer - r->StartTime.PackedTime;\n",
      "        r->RaceTime.PackedTime =\n"
      "            (uint32_t)WorldTimer;\n"),
    M("up-time-round", "        timer_round(&r->RaceTime, "
      "RACE_ROUND_SECONDS);\n"
      "    }\n    race_update_ghost_car(r);",
      "    }\n    race_update_ghost_car(r);"),
    M("up-ghost", "    race_update_ghost_car(r);\n", ""),
    M("up-reason", "        if (rc->FinishReason != RACING_CAR_NOT_FINISHED)\n"
      "            continue;\n        racingcar_update_lap_counts(rc);",
      "        racingcar_update_lap_counts(rc);"),
    M("up-laps", "        racingcar_update_lap_counts(rc);\n", ""),
    M("up-best-player", "        if (rc->pCar->pPlayer != NULL\n"
      "            && ",
      "        if ("),
    M("up-best-signed", "            && (int32_t)"
      "racingcar_get_last_best_lap_time(rc)->PackedTime\n"
      "                   < (int32_t)r->BestLapTime.PackedTime)",
      "            && racingcar_get_last_best_lap_time(rc)->PackedTime\n"
      "                   < r->BestLapTime.PackedTime)"),
    M("up-best-copy", "            r->BestLapTime = "
      "*racingcar_get_last_best_lap_time(rc);\n",
      "            ;\n"),
    M("up-force", "    if (r->ForceRaceFinishPosition != 0)\n",
      "    if (r->ForceRaceFinishPosition > 0)\n"),
    M("up-sort", "    race_sort_racing_cars_by_leadership(r);\n", ""),
    M("up-monitor", "    race_monitor_leadership(r);\n", ""),
    M("up-ko", "if (TheRaceParameters.RaceType == RACE_TYPE_LAP_KNOCKOUT)",
      "if (TheRaceParameters.RaceType != RACE_TYPE_LAP_KNOCKOUT)"),
    M("up-tt", "if (TheRaceParameters.RaceType == RACE_TYPE_TIME_TRIAL)",
      "if (TheRaceParameters.RaceType != RACE_TYPE_TIME_TRIAL)"),
    M("led-reason", "        if (rc->FinishReason == RACING_CAR_NOT_FINISHED\n"
      "            && rc->CrossedFinishLine && rc->RacePosition == 1)",
      "        if (rc->CrossedFinishLine && rc->RacePosition == 1)"),
    M("led-crossed", "&& rc->CrossedFinishLine && rc->RacePosition == 1)",
      "&& rc->RacePosition == 1)"),
    M("led-pos", "&& rc->CrossedFinishLine && rc->RacePosition == 1)",
      "&& rc->CrossedFinishLine && rc->RacePosition == 2)"),
    M("led-inc", "rc->NumLapsLed = (int16_t)(rc->NumLapsLed + 1);",
      "rc->NumLapsLed = (int16_t)(rc->NumLapsLed + 2);"),
    M("fin-laps0", "    if (r->NumLapsInRace != 0) {\n", "    if (1) {\n"),
    M("fin-reason", "            if (rc->FinishReason == "
      "RACING_CAR_NOT_FINISHED\n"
      "                && rc->NumLapsCompleted == r->NumLapsInRace)",
      "            if (rc->NumLapsCompleted == r->NumLapsInRace)"),
    M("fin-eq", "                && rc->NumLapsCompleted == "
      "r->NumLapsInRace)",
      "                && rc->NumLapsCompleted >= r->NumLapsInRace)"),
    M("sp-reason", "        if (rc->FinishReason != RACING_CAR_NOT_FINISHED)\n"
      "            continue;\n        if (rc->CrossedFinishLine && gLap",
      "        if (rc->CrossedFinishLine && gLap"),
    M("sp-crossed", "if (rc->CrossedFinishLine && gLapFinishedSpeechFn != "
      "NULL)",
      "if (gLapFinishedSpeechFn != NULL)"),
    M("sp-laps", "gLapFinishedSpeechFn(rc->pCar, rc->NumLapsCompleted);",
      "gLapFinishedSpeechFn(rc->pCar, rc->NumLapsCompleted + 1);"),

    # -- Player::SetFinishedRacing ------------------------------------------
    M("pf-once", "    if (p->TimeFinishedRacing != 0)\n        return;\n", "",
      PFC),
    M("pf-frames", "p->TimeFinishedRacing = (uint32_t)WorldTimeFrames;",
      "p->TimeFinishedRacing = (uint32_t)WorldTimeFrames + 1;", PFC),
    M("pf-laps", "if (rc->NumLapsCompleted == pCurrentRace->NumLapsInRace) {",
      "if (rc->NumLapsCompleted >= pCurrentRace->NumLapsInRace) {", PFC),
    M("pf-cop", "if (TheRaceParameters.BeACop == 0 && pReplayManager != NULL)",
      "if (pReplayManager != NULL)", PFC),
    M("pf-near", "        if (distance(&car->State.Position, "
      "&other->State.Position)\n"
      "            < FINISH_NEAR)",
      "        if (distance(&car->State.Position, "
      "&other->State.Position)\n"
      "            <= FINISH_NEAR)", PFC),
    M("pf-near-z", "    return sqrtf((dx * dx + dy * dy) + dz * dz);",
      "    return sqrtf(dx * dx + dy * dy);", PFC),
    M("pf-loop", "    for (i = 0; i < r->NumRacingCars; i++) {",
      "    for (i = 1; i < r->NumRacingCars; i++) {", PFC),
    M("pf-self", "((float)cars_near(pCurrentRace, rc->pCar) - 1.0f) * 7.5f",
      "((float)cars_near(pCurrentRace, rc->pCar) - 0.0f) * 7.5f", PFC),
    M("pf-each", "((float)cars_near(pCurrentRace, rc->pCar) - 1.0f) * 7.5f",
      "((float)cars_near(pCurrentRace, rc->pCar) - 1.0f) * 7.0f", PFC),
    M("pf-base", "                    + 10.0f,", "                    + 9.0f,",
      PFC),
    M("pf-all", "        if (race_are_all_players_finished_racing("
      "pCurrentRace)\n"
      "            && gSpeechClearEventQueueFn != NULL)",
      "        if (gSpeechClearEventQueueFn != NULL)", PFC),
    M("pf-sound", "            gTriggerFinishLineSoundFn(p);\n",
      "            ;\n", PFC),
    M("pf-anim", "p->FinishAnimationLength = FINISH_ANIMATION_FRAMES;",
      "p->FinishAnimationLength = FINISH_ANIMATION_FRAMES - 1;", PFC),
    M("pf-anim-in", "    }\n    p->FinishAnimationLength = "
      "FINISH_ANIMATION_FRAMES;\n}",
      "        p->FinishAnimationLength = FINISH_ANIMATION_FRAMES;\n"
      "    }\n}", PFC),
]

# Mutations that cannot change what either side prints, and why.
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
    opsdir = tempfile.TemporaryDirectory()
    ops = Path(opsdir.name) / "ops.bin"
    ops.write_bytes(sc.encode())
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, ops, out)
        took = time.monotonic() - t0
        got = out.read_text().splitlines()
        if diff(base, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "raceupdate_test",
        lambda exe, out: mutpar.run_exe([exe, ops], out, limit),
        base, diff, EQUIVALENT, jobs)
    opsdir.cleanup()
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
        ops = Path(tmp) / "ops.bin"
        ops.write_bytes(sc.encode())
        exe = build_harness(tmp)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, ops, out)
        harness = out.read_text().splitlines()

    if args.dump:
        Path(args.dump + ".model.txt").write_text(NL.join(lines) + NL)
        Path(args.dump + ".harness.txt").write_text(NL.join(harness) + NL)

    bad = diff(lines, harness)
    print("%d ops, %d lines, %d differ"
          % (len(sc.ops), len(harness), bad))
    sys.exit(1 if (bad or rc) else 0)


if __name__ == "__main__":
    main()
