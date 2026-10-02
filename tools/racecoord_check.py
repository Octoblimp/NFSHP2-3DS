#!/usr/bin/env python3
"""Cross-check 3DS Files/source/racecoord.c, RaceCoordinator's lifetime and
its message queue, against the retail image itself, run in mipsemu.

The model is the image. RaceCoordinator's constructor (0x00149738),
destructor (0x00149858), InitForRace (0x00149988), CleanupAfterRace
(0x00149b88), CleanupPlayers (0x00149d78), CleanupCars (0x0014a5f0),
ChangeState (0x00149520), SendMessage (0x00149650), PostMessage
(0x001496d8) and ExecuteQueuedMessages (0x00149578) run as shipped, and so
do SetAIDriverModesFromPlayers (0x001cd240), RaceParameters::
GetDriverInfoByDriverNumber (0x001edb40) and what runs under them:
GetDriverInfo, Race::GetRacingCar, Player::GetDrivingStyle,
RaceParameters::Print, World::FlushCollisions, RCQueuedMessage's and
bTList's destructors. The harness (tools/src/racecoord_test.c) runs the
port over the same script, and the two transcripts are diffed.

Everything else under them is a stub that prints its arguments: bMalloc,
the slot pool's four calls, __builtin_delete, bCountFreeMemory (which
answers the script's figure and prints nothing), FindResourceFile by name
and UnloadResourceFile, the PauseMenu's, the ReplayManager's, the Race's,
the World's, the Player's, the Car's, the Chopper's and EndGameScreens'
constructors and destructors as InitForRace and the cleanups call them,
Player::CleanupAfterRace, InitCars, InitPlayers, Race::Init,
SetupGhostCars, GetTrackInfo, DisableRenderEggs, collision_sound::Reset,
the speech manager's FlushQueue, CleanUpAutoReplay, KillAllActiveEffects,
jukebox::Stop and sound3d_oneshot::Reset. The two camera coordinators have
a fake vtable whose virtual destructor prints.

The World's constructor builds the scenario's world: its car table, its
CarList and its helicopter. The Player's constructor fills in the
scenario's DrivingStyle for its number and the tables, as Player's own
does, and InitPlayers the player's car. The ten entries of the state table
(0x002f0bf0) point at fake callbacks that print the message, the state
and the queue; a script reaction makes one of them answer a message once
with SendMessage, PostMessage, ChangeState or ExecuteQueuedMessages, run
in the image from inside the callback.

    python tools/racecoord_check.py
    python tools/racecoord_check.py --mutate [--only a,b]
    python tools/racecoord_check.py --dump out/racecoord
"""
import argparse
import os
import random
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import physicscar_check as pcc
import retail_model
from mipsemu import M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/racecoord_test.c"
RCC = "3DS Files/source/racecoord.c"
RCH = "3DS Files/source/racecoord.h"
RCE = "3DS Files/source/race.c"
SOURCES = [HARNESS, RCC, RCE]

HARNESS_TIMEOUT = 120

ARM_GCC = Path("C:/devkitPro/devkitARM/bin/arm-none-eabi-gcc.exe")
CTRU_INCLUDE = Path("C:/devkitPro/libctru/include")

# ================================================================ the image

GP = 0x003358f0
CHANGE_STATE = 0x00149520
EXECUTE = 0x00149578
SEND = 0x00149650
POST = 0x001496d8
CTOR = 0x00149738
DTOR = 0x00149858
INIT_FOR_RACE = 0x00149988
CLEANUP = 0x00149b88
CLEANUP_PLAYERS = 0x00149d78
CLEANUP_CARS = 0x0014a5f0
SET_AI_MODES = 0x001cd240
BY_NUMBER = 0x001edb40
STATE_TABLE = 0x002f0bf0

B_MALLOC = 0x002577c0
B_DELETE = 0x00114e98
B_COUNT_FREE = 0x00257988
B_LARGEST = 0x002579b0
NEW_POOL = 0x00257c10
DEL_POOL = 0x00257c48
O_MALLOC = 0x00257c80
POOL_FREE = 0x00257ca0
FIND_BY_NAME = 0x00199828
UNLOAD = 0x00199728
PAUSE_CTOR = 0x00170580
PAUSE_DTOR = 0x001705e0
PLAYER_CTOR = 0x001751d8
PLAYER_DTOR = 0x00175bf0
PLAYER_CLEANUP = 0x00181970
TRACK_INFO = 0x00153420
REPLAY_CTOR = 0x0013d448
REPLAY_DTOR = 0x0013d5c0
RACE_CTOR = 0x001475e8
RACE_DTOR = 0x001476e0
RACE_INIT = 0x00147960
GHOSTS = 0x001485e0
WORLD_CTOR = 0x0014cd28
WORLD_DTOR = 0x0014cf88
INIT_CARS = 0x0014a2c8
INIT_PLAYERS = 0x00149cb8
EGGS_OFF = 0x0024c000
COLL_RESET = 0x001e51c8
SPEECH_INST = 0x00209ef0
SPEECH_FLUSH = 0x0020a230
AUTOREPLAY_CLEANUP = 0x0014c148
KILL_EFFECTS = 0x001276a8
JB_STOP = 0x001aec90
ONESHOT_RESET = 0x00209208
ENDGAME_DTOR = 0x001dcda8
CAR_DTOR = 0x00130ee0
CHOPPER_DTOR = 0x001e7b80
WORLD_EFFECTS = 0x002ef640

G_RC = GP - 22216
G_POOL = GP - 22192
G_PAUSE = GP - 21064
G_REPLAY = GP - 22440
G_RACE = GP - 22272
G_WORLD = GP - 22120
G_BY_NUMBER = GP - 20936
G_BY_INDEX = GP - 20928
G_NUM = GP - 20920
G_SKIPFE = GP - 23220

RP = 0x0031a898
RP_TRACK = RP
RP_AIDEMO = RP + 24
RP_REPLAYDEMO = RP + 28
RP_NPLAYCARS = RP + 48
RP_NAICARS = RP + 52
RP_BEACOP = RP + 628
RP_DRV = RP + 772
RP_NDRV = RP + 776

PRERACE_NAME = 0x002af838

# RaceCoordinator
RC_STATE = 0
RC_LIST = 4
RC_EXEC = 12
RC_BYTES = 144
# Player
P_CAR = 4
P_NUMBER = 16
P_STYLE = 34
# World
W_HELI = 24
W_TOTAL = 28
W_AIPOS = 32
W_COPPOS = 36
W_TRAFFICPOS = 40
W_TABLE = 44
MAX_CARS = 14
# Car and RacingCar
C_RACINGCAR = 28
C_MODE = 988
RC_POS = 10

NOBJ = 64
OBJ_BYTES = 0x8000
APOOL = 0x01000000
MISC = APOOL + NOBJ * OBJ_BYTES
RCBUF = MISC
SLOTS = MISC + 0x1000
NSLOT = 64
DRIVERS = MISC + 0x2000
NDRV = 12
FLY = MISC + 0x3000
PRE = MISC + 0x3100
FAKE_VT = MISC + 0x3200
EG = MISC + 0x3300
HELI = MISC + 0x3400
FILE0 = MISC + 0x3500
POOL = MISC + 0x3600
TRACKINFO = MISC + 0x3700
SPEECH = MISC + 0x3800
STUBS = MISC + 0x4000
CARS = MISC + 0x10000
CAR_STRIDE = 0x1000
NCAR = 10
RCARS = MISC + 0x20000
RCAR_STRIDE = 0x100

PATTERN = 0xa5
NUM_RCSTATES = 10


def arm_layout_check():
    """RaceCoordinator in an ARM compile of racecoord.h, whose own
    assertion runs there. Returns 0 when it holds or devkitARM is not
    there."""
    if not ARM_GCC.exists():
        print("devkitARM not found; the ARM layout check is skipped")
        return 0
    lines = [
        "#include <stddef.h>",
        "#include \"racecoord.h\"",
        "_Static_assert(sizeof(struct RaceCoordinator) == 144, \"size\");",
        "_Static_assert(offsetof(struct RaceCoordinator, PostRaceWord140)"
        " == 140, \"w140\");",
        "_Static_assert(sizeof(RCQueuedMessage) == 16, \"msg\");",
    ]
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "racecoord_layout.c"
        src.write_text(NL.join(lines) + NL)
        r = subprocess.run(
            [str(ARM_GCC), "-fsyntax-only", "-march=armv6k", "-mtune=mpcore",
             "-mfloat-abi=hard", "-std=c11", "-I",
             str(ROOT / "3DS Files/source"), "-I", str(CTRU_INCLUDE),
             str(src)],
            capture_output=True, text=True)
    if r.returncode != 0:
        print("the ARM layout check failed:")
        print((r.stderr or r.stdout)[:3000])
        return 1
    print("ARM layout: RaceCoordinator is 144 bytes with retail's word at "
          "140, RCQueuedMessage 16")
    return 0


def fx(w):
    w &= M32
    if (w & 0x7f800000) == 0x7f800000 and (w & 0x7fffff):
        return "nan"
    return "%08x" % w


def obj_at(i):
    return APOOL + OBJ_BYTES * i


def car_at(k):
    return CARS + CAR_STRIDE * k


def rcar_at(k):
    return RCARS + RCAR_STRIDE * k


def driver_at(i):
    return DRIVERS + 24 * i


def slot_at(i):
    return SLOTS + 16 * i


# ============================================================ the scenarios

N_MSGS = 15


def msg_param(rnd, msg):
    """A parameter for `msg`: a state for RC_ACTIVATE, which indexes the
    table with it; anything for the rest."""
    if msg == 1:
        return rnd.randrange(NUM_RCSTATES)
    return rnd.choice((0, 0, 1, 3, 7, 9, -1, 100, 0x7fffffff))


def r_msg(rnd):
    return rnd.choice((1, 2, 3, 3, 3, 0, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
                       14))


def s_reaction(rnd):
    kind = rnd.choice("SSPPCE")
    state = rnd.randrange(NUM_RCSTATES)
    msg = r_msg(rnd)
    if kind == "C":
        return "R %d %d C %d 0" % (state, msg, rnd.randrange(NUM_RCSTATES))
    if kind == "E":
        return "R %d %d E 0 0" % (state, msg)
    m2 = r_msg(rnd)
    return "R %d %d %s %d %d" % (state, msg, kind, m2, msg_param(rnd, m2))


class Gen(object):
    """A scenario's ops, kept inside what the image survives: players for
    the driving styles, a world for the cleanups to walk, slots for the
    queue and room for the reactions."""

    RANKS = (0, 0, 0, -1, -128, 1, 2, 127)
    POSITIONS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, -1, 127, -128)
    STYLES = (0, 1, 2, 3, -1, 127)

    def __init__(self, rnd):
        self.rnd = rnd
        self.ops = []
        self.nreact = 0

    def emit(self, s):
        self.ops.append(s)

    def reaction(self):
        # The harness keeps 32; the ones never matched stay.
        if self.nreact < 28:
            self.nreact += 1
            self.emit(s_reaction(self.rnd))

    def drivers(self, want0=False, want1=False):
        """The driver table, with the first driver numbered 0 (and 1) one
        that InitForRace makes a player of when asked."""
        rnd = self.rnd
        n = rnd.choice((0, 1, 2, 2, 3, 5, 8, 12))
        if want0 or want1:
            n = max(n, 2)
        tbl = [[rnd.choice(self.RANKS), rnd.randrange(-1, 12)]
               for _ in range(NDRV)]
        pos = list(range(n))
        rnd.shuffle(pos)
        for want, num, other in ((want0, 0, 5), (want1, 1, 6)):
            if not want:
                continue
            p = pos.pop()
            tbl[p] = [rnd.choice((0, 0, -1, -128)), num]
            for j in range(p):
                if tbl[j][1] == num:
                    tbl[j][1] = other
        self.emit("S ndrv %d" % n)
        for i, (rank, num) in enumerate(tbl):
            self.emit("D %d %d %d" % (i, rank, num))

    def world_template(self):
        rnd = self.rnd
        order = list(range(NCAR))
        rnd.shuffle(order)
        cop = rnd.randrange(0, NCAR + 1)
        ai = rnd.randrange(0, cop + 1)
        ntable = rnd.randrange(cop, NCAR + 1)
        traffic = rnd.randrange(cop, ntable + 1)
        self.emit("Wt %d %d %d%s" % (ai, cop, traffic, "".join(
            " %d" % order[i] for i in range(ntable))))
        lst = list(range(NCAR))
        rnd.shuffle(lst)
        self.emit("Wl" + "".join(" %d" % c
                                 for c in lst[:rnd.randrange(NCAR + 1)]))
        self.emit("Wh %d" % rnd.choice((0, 1, 1)))
        for k in range(NCAR):
            if rnd.random() < 0.8:
                self.emit("K %d %d" % (k, rnd.choice(self.POSITIONS)))

    def player_template(self, two):
        rnd = self.rnd
        cars = list(range(NCAR))
        rnd.shuffle(cars)
        for n in range(2):
            car = cars[n] if (two or rnd.random() < 0.9) else -1
            self.emit("Y %d %d %d" % (n, rnd.choice(self.STYLES), car))

    def race_params(self):
        """TheRaceParameters for an InitForRace that survives: with two
        player cars both players exist and have cars, and otherwise the
        first by index exists."""
        rnd = self.rnd
        two = rnd.random() < 0.4
        aidemo = 0 if two else rnd.choice((0, 0, 0, 1, 2))
        self.emit("S aidemo %d" % aidemo)
        self.emit("S replaydemo %d" % rnd.choice((0, 0, 0, 1)))
        self.emit("S skipfe %d" % rnd.choice((0, 0, 0, 1)))
        self.emit("S beacop %d" % rnd.choice((0, 0, 1, 2)))
        self.emit("S prerace %d" % rnd.choice((0, 1)))
        self.emit("S free %d" % rnd.choice((0x100000, 0x7cfff, 0x7d000,
                                            0, -1, 0x7d001, 0x7cffe)))
        self.emit("S naicars %d" % rnd.choice((7, 7, 0, 1, 2, 5, 8, 9, -1,
                                               -3)))
        self.emit("S track %d" % rnd.randrange(-1, 30))
        self.emit("S nplaycars %d" % (2 if two else rnd.choice((1, 1, 0,
                                                                3))))
        if two:
            self.drivers(True, True)
        elif aidemo:
            self.drivers(rnd.random() < 0.5, rnd.random() < 0.5)
        else:
            self.drivers(True, rnd.random() < 0.5)
        self.player_template(two)
        self.world_template()


def s_queue(rnd, n):
    """The queue on its own: ChangeState, SendMessage, PostMessage and
    ExecuteQueuedMessages, with RCExecutingMessage and the state set
    from the script and the callbacks answering."""
    g = Gen(rnd)
    g.emit("S ndrv 0")
    g.emit("S aidemo 1")
    g.emit("Y 0 1 -1")
    g.emit("Wt 0 0 0")
    g.emit("N")
    queued, ex = 0, 0
    for _ in range(n):
        k = rnd.random()
        if k < 0.25:
            for _ in range(rnd.randrange(1, 4)):
                g.reaction()
        if queued > 36:
            g.emit("S exec 0")
            g.emit("E")
            queued, ex = 0, 0
        elif k < 0.15:
            g.emit("T %d" % rnd.randrange(NUM_RCSTATES))
            queued = queued + 3 if ex else 0
        elif k < 0.45:
            m = r_msg(rnd)
            g.emit("M %d %d" % (m, msg_param(rnd, m)))
            queued = queued + 1 if ex else 0
        elif k < 0.7:
            m = r_msg(rnd)
            g.emit("P %d %d" % (m, msg_param(rnd, m)))
            queued += 1
        elif k < 0.8:
            g.emit("E")
            queued, ex = 0, 0
        elif k < 0.88:
            ex = rnd.choice((0, 1, 1, 2))
            g.emit("S exec %d" % ex)
        elif k < 0.95:
            g.emit("S state %d" % rnd.randrange(NUM_RCSTATES))
        else:
            g.emit("S exec 0")
            g.emit("E")
            queued, ex = 0, 0
    g.emit("S exec 0")
    g.emit("E")
    g.emit("X %d" % rnd.choice((0, 2)))
    return g.ops


def s_lifetime(rnd, n):
    """Constructions and destructions over every way InitForRace picks the
    first state, the drivers it makes players of, the free memory and the
    prerace animation; the coordinators and the end-game screens set
    before the destructor."""
    out = []
    for _ in range(n):
        g = Gen(rnd)
        g.race_params()
        for _ in range(rnd.randrange(0, 3)):
            g.reaction()
        g.emit("N")
        for _ in range(rnd.randrange(0, 3)):
            k = rnd.random()
            if k < 0.4:
                g.emit("T %d" % rnd.randrange(NUM_RCSTATES))
            elif k < 0.7:
                m = r_msg(rnd)
                g.emit("M %d %d" % (m, msg_param(rnd, m)))
            else:
                g.emit("S state %d" % rnd.choice((0, 0, 3, 7)))
        for f in ("fly", "pre", "eg"):
            if rnd.random() < 0.5:
                g.emit("S %s 1" % f)
        g.emit("X %d" % rnd.choice((0, 1, 2, 3, 3)))
        out.append(g.ops)
    return out


def s_cycles(rnd, n):
    """InitForRace and CleanupAfterRace again and again on one coordinator,
    and the cleanups one at a time. Nothing cleans up without a World, as
    retail never does: CleanupCars reads it unchecked."""
    out = []
    for _ in range(n):
        g = Gen(rnd)
        g.race_params()
        g.emit("N")
        alive = True
        for _ in range(rnd.randrange(2, 6)):
            k = rnd.random()
            if not alive:
                g.race_params()
                g.emit("G")
                alive = True
            elif k < 0.35:
                for f in ("fly", "pre", "eg"):
                    if rnd.random() < 0.4:
                        g.emit("S %s 1" % f)
                g.emit("U")
                alive = False
            elif k < 0.5:
                g.emit("CP")
            elif k < 0.6:
                g.emit("CC")
            elif k < 0.7:
                g.reaction()
            else:
                g.emit("T %d" % rnd.randrange(NUM_RCSTATES))
        if not alive:
            g.race_params()
            g.emit("G")
        g.emit("X %d" % rnd.choice((0, 2)))
        out.append(g.ops)
    return out


def s_modes(rnd, n):
    """SetAIDriverModesFromPlayers on its own over positions, styles and
    the AI count, with one player car and two, and without a World or a
    Race."""
    out = []
    for _ in range(n):
        g = Gen(rnd)
        two = rnd.random() < 0.6
        g.emit("S nplaycars %d" % (2 if two else 1))
        g.drivers(True, two or rnd.random() < 0.5)
        g.player_template(True)
        g.world_template()
        g.emit("N")
        for _ in range(rnd.randrange(3, 12)):
            k = rnd.random()
            if k < 0.35:
                g.emit("K %d %d" % (rnd.randrange(NCAR),
                                    rnd.choice(Gen.POSITIONS)))
            elif k < 0.5:
                g.emit("Q %d %d" % (rnd.randrange(2),
                                    rnd.choice(Gen.STYLES)))
            elif k < 0.65:
                g.emit("S naicars %d" % rnd.choice(
                    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, -1, -2, -7)))
            elif k < 0.7 and two:
                g.emit("S nplaycars %d" % rnd.choice((1, 2, 2, 0, 3)))
            g.emit("A")
        k = rnd.random()
        if k < 0.3:
            # No World or no Race: SetAIDriverModesFromPlayers returns
            # before it reads a style or a position, so new ones must not
            # show. Nothing may clean up without the World.
            gone = "world" if k < 0.15 else "race"
            g.emit("S %s 0" % gone)
            for i in range(2):
                g.emit("Q %d %d" % (i, rnd.choice((4, 5, 6))))
            for c in range(NCAR):
                g.emit("K %d %d" % (c, rnd.choice((0, 9, -1))))
            g.emit("S naicars %d" % rnd.choice((0, 3, 11)))
            g.emit("A")
            if gone == "race":
                g.emit("X 0")
        else:
            g.emit("X 0")
        out.append(g.ops)
    return out


def s_drivers(rnd, n):
    """GetDriverInfoByDriverNumber over driver tables with repeats, gaps
    and every count: the first match wins, and nothing past the count is
    read."""
    out = []
    nums = (0, 1, 2, 3, 4, 5, -1)
    for _ in range(n):
        ops = []
        nd = rnd.choice((0, 1, 2, 3, 6, 11, 12))
        ops.append("S ndrv %d" % nd)
        for i in range(NDRV):
            ops.append("D %d %d %d" % (i, rnd.choice((0, 1, -1)),
                                       rnd.choice(nums + (127, -128))))
        for _ in range(10):
            ops.append("F %d" % rnd.choice(nums + (127, -128, 128, 255,
                                                   -129)))
        out.append(ops)
    return out


def s_edges(rnd):
    """The thresholds and boundaries one at a time."""
    out = []
    base = ["S ndrv 2", "D 0 0 0", "D 1 0 1", "Y 0 1 0", "Y 1 2 1",
            "Wt 2 6 6 0 1 2 3 4 5", "Wl 0 1 2 3", "Wh 1"]
    for free in (0x7cffe, 0x7cfff, 0x7d000, 0x7d001):
        out.append(base + ["S prerace 1", "S free %d" % free, "N", "X 0"])
    for rank in (-1, 0, 1):
        for aidemo in (0, 1):
            out.append(["S ndrv 2", "D 0 %d 0" % rank, "D 1 %d 1" % rank,
                        "S aidemo %d" % aidemo, "Y 0 1 0", "Y 1 2 1",
                        "Wt 0 0 0", "N", "X 0"])
    # The middle of the AI field against each player's position.
    for na in (6, 7):
        for pa in (2, 3, 4, 5):
            for pb in (2, 3, 4, 5):
                ops = base + ["S nplaycars 2", "S naicars %d" % na,
                              "K 0 %d" % pa, "K 1 %d" % pb]
                for k in range(2, 6):
                    ops.append("K %d %d" % (k, k + 1))
                ops += ["N", "X 0"]
                out.append(ops)
    # A message answered by a message, answered by a change of state.
    out.append(base + ["N", "R 3 4 S 5 1", "R 3 5 C 7 0", "R 7 3 P 9 9",
                       "R 7 1 E 0 0", "M 4 0", "E", "X 0"])
    out.append(base + ["N", "S exec 1", "M 3 0", "M 4 1", "P 5 2",
                       "S exec 0", "M 6 3", "X 0"])
    return out


def script():
    rnd = random.Random(0x8e7c0de1)
    sc = []
    for n in (20, 40, 80, 120):
        sc.append(s_queue(rnd, n))
    sc += s_lifetime(rnd, 60)
    sc += s_cycles(rnd, 25)
    sc += s_modes(rnd, 30)
    sc += s_drivers(rnd, 12)
    sc += s_edges(rnd)
    return sc


def encode(scenarios):
    lines = []
    for i, s in enumerate(scenarios):
        lines.append("B %d" % i)
        lines += s
    return NL.join(lines) + NL


# ================================================================ the model


class Model(object):
    def __init__(self):
        self.out = []
        self.e = retail_model.RetailEmu(ieee=True)
        e = self.e
        self.nstub = 0
        for a, fn in ((B_MALLOC, self.s_malloc), (B_DELETE, self.s_delete),
                      (B_COUNT_FREE, self.s_count_free),
                      (B_LARGEST, lambda _e: 0),
                      (NEW_POOL, self.s_newpool), (DEL_POOL, self.s_delpool),
                      (O_MALLOC, self.s_omalloc), (POOL_FREE, self.s_free),
                      (FIND_BY_NAME, self.s_find), (UNLOAD, self.s_unload),
                      (PAUSE_CTOR, self.s_pause),
                      (PAUSE_DTOR, self.s_del("pausemenu-del")),
                      (PLAYER_CTOR, self.s_player),
                      (PLAYER_DTOR, self.s_player_del),
                      (PLAYER_CLEANUP, self.s_named("player-cleanup")),
                      (TRACK_INFO, self.s_trackinfo),
                      (REPLAY_CTOR, self.s_ctor("replaymgr")),
                      (REPLAY_DTOR, self.s_del("replaymgr-del")),
                      (RACE_CTOR, self.s_ctor("race")),
                      (RACE_DTOR, self.s_del("race-del")),
                      (RACE_INIT, self.s_race_init),
                      (GHOSTS, self.s_named("ghosts")),
                      (WORLD_CTOR, self.s_world),
                      (WORLD_DTOR, self.s_del("world-del")),
                      (INIT_CARS, self.s_named("initcars")),
                      (INIT_PLAYERS, self.s_init_players),
                      (EGGS_OFF, self.s_say("eggsoff")),
                      (COLL_RESET, self.s_say("collsnd")),
                      (SPEECH_INST, lambda _e: SPEECH),
                      (SPEECH_FLUSH, self.s_speech),
                      (AUTOREPLAY_CLEANUP, self.s_named("autoreplay-cleanup")),
                      (KILL_EFFECTS, self.s_kill),
                      (JB_STOP, self.s_say("jbstop")),
                      (ONESHOT_RESET, self.s_say("oneshot-reset")),
                      (ENDGAME_DTOR, self.s_del("endgame-del")),
                      (CAR_DTOR, self.s_del("cardel")),
                      (CHOPPER_DTOR, self.s_del("heli-del"))):
            e.stub(a, fn)
        # RaceParameters::Print is empty, and FlushCollisions too: both run.
        assert e.u32(0x001edf88) == 0x03e00008
        assert e.u32(0x0014e578) == 0x03e00008
        # The state table: ten pointers to members, this-delta 0, index -1.
        self.state_fn = []
        for s in range(NUM_RCSTATES):
            d, idx = struct.unpack_from("<hh", e.mem, STATE_TABLE + 8 * s)
            assert d == 0 and idx == -1
            a = self.fake(self.cb(s))
            e.put32(STATE_TABLE + 8 * s + 4, a)
        # The camera coordinators' vtable: the virtual destructor at +8.
        e.write(FAKE_VT, bytes(32))
        e.write(FAKE_VT + 8, struct.pack("<hh", 0, 0))
        e.put32(FAKE_VT + 12, self.fake(self.v_ccdel))
        for o in (FLY, PRE):
            e.write(o, bytes(32))
            e.put32(o + 24, FAKE_VT)

        self.names = {0: "null", RCBUF: "rc", FLY: "fly", PRE: "pre",
                      EG: "eg", HELI: "h0", FILE0: "f0", POOL: "pool",
                      TRACKINFO: "ti"}
        for i in range(NOBJ):
            self.names[obj_at(i)] = "a%d" % i
        for i in range(NSLOT):
            self.names[slot_at(i)] = "m%d" % i
        for i in range(NDRV):
            self.names[driver_at(i)] = "d%d" % i
        for k in range(NCAR):
            self.names[car_at(k)] = "c%d" % k
            self.names[rcar_at(k)] = "r%d" % k

    def fake(self, fn):
        a = STUBS + 8 * self.nstub
        self.nstub += 1
        self.e.stub(a, fn)
        return a

    def emit(self, s):
        self.out.append(s)

    def name(self, a):
        return self.names.get(a & M32, "s")

    def arg(self, i):
        return self.e.reg[(4, 5, 6, 7, 8, 9, 10, 11)[i]] & M32

    def w(self, a):
        return self.e.u32(a)

    def sb(self, a):
        v = self.e.mem[a]
        return v - 256 if v > 127 else v

    def fill(self, a, n, byte=PATTERN):
        self.e.write(a, bytes([byte]) * n)

    def cstr(self, a):
        b = bytearray()
        while self.e.mem[a]:
            b.append(self.e.mem[a])
            a += 1
        return b.decode("latin-1")

    def nested(self, fn, *args):
        """Call into the image from inside a stub, and put back what the
        stub's caller had."""
        e = self.e
        kept = (list(e.reg), list(e.fpr), e.hi, e.lo, e.hi1, e.lo1, e.sa,
                e.fcc, e.limit, e.icount)
        try:
            e.call(fn, *args, limit=2000000)
        finally:
            e.reg[:] = kept[0]
            e.fpr[:] = kept[1]
            (e.hi, e.lo, e.hi1, e.lo1, e.sa, e.fcc, e.limit,
             e.icount) = kept[2:]

    # ---- the stubs -------------------------------------------------------

    def s_say(self, what):
        def f(e):
            self.emit("  " + what)
        return f

    def s_named(self, what):
        def f(e):
            self.emit("  %s %s" % (what, self.name(self.arg(0))))
        return f

    def s_ctor(self, what):
        def f(e):
            self.emit("  %s %s" % (what, self.name(self.arg(0))))
            return self.arg(0)
        return f

    def s_del(self, what):
        def f(e):
            self.emit("  %s %s %d" % (what, self.name(self.arg(0)),
                                      s32(self.arg(1))))
        return f

    def s_malloc(self, e):
        name = self.cstr(self.arg(1))
        if self.nobj >= NOBJ:
            raise SystemExit("arena full")
        a = obj_at(self.nobj)
        self.nobj += 1
        self.fill(a, OBJ_BYTES)
        self.emit("  malloc %d %s %d %d -> %s"
                  % (s32(self.arg(0)), name, s32(self.arg(2)),
                     s32(self.arg(3)), self.name(a)))
        return a

    def s_delete(self, e):
        self.emit("  delete %s" % self.name(self.arg(0)))

    def s_count_free(self, e):
        return self.free

    def s_newpool(self, e):
        self.emit("  newpool %d %d %s %d -> pool"
                  % (s32(self.arg(0)), s32(self.arg(1)),
                     self.cstr(self.arg(2)), s32(self.arg(3))))
        return POOL

    def s_delpool(self, e):
        self.emit("  delpool %s" % self.name(self.arg(0)))

    def s_omalloc(self, e):
        for i in range(NSLOT):
            if not self.slot_used[i]:
                self.slot_used[i] = True
                self.fill(slot_at(i), 16)
                self.emit("  omalloc %s -> m%d" % (self.name(self.arg(0)),
                                                   i))
                return slot_at(i)
        raise SystemExit("slots full")

    def s_free(self, e):
        p = self.arg(1)
        self.emit("  free %s %s ex=%d" % (self.name(self.arg(0)),
                                          self.name(p),
                                          s32(self.w(RCBUF + RC_EXEC))))
        if SLOTS <= p < SLOTS + 16 * NSLOT and (p - SLOTS) % 16 == 0:
            self.slot_used[(p - SLOTS) // 16] = False

    def s_find(self, e):
        f = FILE0 if self.prerace else 0
        self.emit("  find %s -> %s" % (self.cstr(self.arg(0)), self.name(f)))
        return f

    def s_unload(self, e):
        self.emit("  unload %s" % self.name(self.arg(0)))
        self.prerace = 0

    def s_pause(self, e):
        self.emit("  pausemenu %s" % self.name(self.arg(0)))
        return self.arg(0)

    def s_player(self, e):
        p, port, number = self.arg(0), s32(self.arg(1)), s32(self.arg(2))
        self.emit("  player %s %d %d" % (self.name(p), port, number))
        n = s32(self.w(G_NUM))
        if n < 2:
            e.put32(G_BY_INDEX + 4 * n, p)
        e.put32(G_NUM, (n + 1) & M32)
        e.put32(p + P_NUMBER, number & M32)
        e.put32(p + P_CAR, 0)
        if 0 <= number < 2:
            e.mem[p + P_STYLE] = self.t_style[number] & 0xff
            e.put32(G_BY_NUMBER + 4 * number, p)
        return p

    def s_player_del(self, e):
        p = self.arg(0)
        self.emit("  player-del %s %d" % (self.name(p), s32(self.arg(1))))
        n = s32(self.w(G_NUM)) - 1
        e.put32(G_NUM, n & M32)
        if 0 <= n < 2:
            e.put32(G_BY_INDEX + 4 * n, 0)
        number = s32(self.w(p + P_NUMBER))
        if 0 <= number < 2:
            e.put32(G_BY_NUMBER + 4 * number, 0)

    def s_init_players(self, e):
        self.emit("  initplayers %s" % self.name(self.arg(0)))
        n = s32(self.w(G_NUM))
        for i in range(min(n, 2)):
            p = self.w(G_BY_INDEX + 4 * i)
            if p:
                number = s32(self.w(p + P_NUMBER))
                if 0 <= number < 2:
                    c = self.t_car[number]
                    e.put32(p + P_CAR, car_at(c) if c >= 0 else 0)

    def s_trackinfo(self, e):
        self.emit("  trackinfo %d" % s32(self.arg(0)))
        return TRACKINFO

    def s_race_init(self, e):
        self.emit("  raceinit %s %d" % (self.name(self.arg(0)),
                                        s32(self.arg(1))))

    def s_world(self, e):
        w = self.arg(0)
        self.emit("  world %s" % self.name(w))
        for off in (0, 8, 16):
            e.put32(w + off, w + off)
            e.put32(w + off + 4, w + off)
        e.put32(w + W_HELI, HELI if self.t_heli else 0)
        e.put32(w + W_TOTAL, len(self.t_table))
        e.put32(w + W_AIPOS, self.t_ai)
        e.put32(w + W_COPPOS, self.t_cop)
        e.put32(w + W_TRAFFICPOS, self.t_traffic)
        for i in range(MAX_CARS):
            c = self.t_table[i] if i < len(self.t_table) else -1
            e.put32(w + W_TABLE + 4 * i, car_at(c) if c >= 0 else 0)
        for k in self.t_list:
            c = car_at(k)
            tail = self.w(w + 4)
            e.put32(c + 4, tail)
            e.put32(c, w)
            e.put32(tail, c)
            e.put32(w + 4, c)
        e.put32(G_WORLD, w)
        return w

    def s_speech(self, e):
        self.emit("  speech" if self.arg(0) == SPEECH else "  speech other")

    def s_kill(self, e):
        self.emit("  effects-kill" if self.arg(0) == WORLD_EFFECTS
                  else "  effects-kill other")

    def v_ccdel(self, e):
        self.emit("  ccdel %s %d" % (self.name(self.arg(0)),
                                     s32(self.arg(1))))

    def cb(self, state):
        def f(e):
            rc, msg, param = self.arg(0), s32(self.arg(1)), s32(self.arg(2))
            w = self.w
            self.emit("  cb %d %d %d this=%s st=%d ex=%d rc=%s bp=%d cd=%d "
                      "port=%d demo=%s cm=%s eye=%s w140=%d q=%s"
                      % (state, msg, param, self.name(rc),
                         s32(w(rc + RC_STATE)), s32(w(rc + RC_EXEC)),
                         self.name(w(G_RC)), s32(w(rc + 24)),
                         s32(w(rc + 16)), s32(w(rc + 20)),
                         self.name(w(rc + 28)), self.name(w(rc + 52)),
                         self.name(w(rc + 112)), s32(w(rc + 140)),
                         self.queue(rc)))
            self.respond(state, rc, msg)
            return 1
        return f

    def respond(self, state, rc, msg):
        for i, r in enumerate(self.react):
            if r[0] == state and r[1] == msg:
                del self.react[i]
                kind, a, b = r[2], r[3], r[4]
                if kind == "S":
                    self.nested(SEND, rc, a, b)
                elif kind == "P":
                    self.nested(POST, rc, a, b)
                elif kind == "C":
                    self.nested(CHANGE_STATE, rc, a)
                elif kind == "E":
                    self.nested(EXECUTE, rc)
                return

    # ---- the state -------------------------------------------------------

    def queue(self, rc):
        w = self.w
        lst = rc + RC_LIST
        fwd = []
        p = w(lst)
        while p != lst and len(fwd) < 80:
            fwd.append(" %s:%d/%d" % (self.name(p), s32(w(p + 8)),
                                      s32(w(p + 12))))
            p = w(p)
        back = []
        p = w(lst + 4)
        while p != lst and len(back) < 80:
            back.append(" " + self.name(p))
            p = w(p + 4)
        return "".join(fwd) + " |" + "".join(back)

    def reset(self):
        e = self.e
        self.nobj = 0
        self.rc_made = False
        self.fill(RCBUF, RC_BYTES)
        self.slot_used = [False] * NSLOT
        self.fill(DRIVERS, 24 * NDRV)
        for k in range(NCAR):
            self.fill(car_at(k), CAR_STRIDE)
            self.fill(rcar_at(k), RCAR_STRIDE)
            e.put32(car_at(k) + C_RACINGCAR, rcar_at(k))
        e.put32(RP_DRV, DRIVERS)
        e.put32(RP_NDRV, 0)
        e.put32(RP_TRACK, 1)
        e.put32(RP_AIDEMO, 0)
        e.put32(RP_REPLAYDEMO, 0)
        e.put32(RP_BEACOP, 0)
        e.put32(RP_NPLAYCARS, 1)
        e.put32(RP_NAICARS, 7)
        e.put32(G_SKIPFE, 0)
        self.free = 0x100000
        self.prerace = 0
        for g in (G_RC, G_RACE, G_WORLD, G_REPLAY, G_PAUSE, G_POOL, G_NUM):
            e.put32(g, 0)
        for i in range(2):
            e.put32(G_BY_INDEX + 4 * i, 0)
            e.put32(G_BY_NUMBER + 4 * i, 0)
        self.t_style = [0, 0]
        self.t_car = [-1, -1]
        self.t_ai = self.t_cop = self.t_traffic = 0
        self.t_table = []
        self.t_list = []
        self.t_heli = 0
        self.react = []

    def set_global(self, f, v):
        e = self.e
        regs = {"aidemo": RP_AIDEMO, "replaydemo": RP_REPLAYDEMO,
                "beacop": RP_BEACOP, "nplaycars": RP_NPLAYCARS,
                "naicars": RP_NAICARS, "ndrv": RP_NDRV, "track": RP_TRACK,
                "skipfe": G_SKIPFE, "state": RCBUF + RC_STATE,
                "exec": RCBUF + RC_EXEC}
        if f in regs:
            e.put32(regs[f], v & M32)
        elif f == "free":
            self.free = s32(v)
        elif f == "prerace":
            self.prerace = v
        elif f in ("fly", "pre", "eg"):
            off = {"fly": 32, "pre": 36, "eg": 40}[f]
            obj = {"fly": FLY, "pre": PRE, "eg": EG}[f]
            e.put32(RCBUF + off, obj if v else 0)
        elif f == "world":
            e.put32(G_WORLD, 0)
        elif f == "race":
            e.put32(G_RACE, 0)
        else:
            raise SystemExit("bad global %s" % f)

    # ---- the dump --------------------------------------------------------

    def dump(self):
        w, nm = self.w, self.name
        rc = RCBUF
        if self.rc_made:
            self.emit("  rc st=%d ex=%d cd=%d port=%d bp=%d demo=%s fly=%s "
                      "pre=%s eg=%s rs=%s nr=%d cm=%s cdp=%s ip=%s"
                      % (s32(w(rc)), s32(w(rc + 12)), s32(w(rc + 16)),
                         s32(w(rc + 20)), s32(w(rc + 24)), nm(w(rc + 28)),
                         nm(w(rc + 32)), nm(w(rc + 36)), nm(w(rc + 40)),
                         nm(w(rc + 44)), s32(w(rc + 48)), nm(w(rc + 52)),
                         nm(w(rc + 56)), nm(w(rc + 60))))
            self.emit("  rcv " + " | ".join(
                " ".join(fx(w(rc + base + 4 * k)) for k in range(4))
                for base in (64, 80, 96)))
            self.emit("  rc3 eye=%s bank=%s fov=%s hl=%s hl2=%s view=%d "
                      "route=%s w140=%d"
                      % (nm(w(rc + 112)), nm(w(rc + 116)), nm(w(rc + 120)),
                         nm(w(rc + 124)), nm(w(rc + 128)), s32(w(rc + 132)),
                         nm(w(rc + 136)), s32(w(rc + 140))))
            self.emit("  q" + self.queue(rc))
        self.emit("  g rc=%s race=%s world=%s rm=%s pm=%s pool=%s np=%d "
                  "idx=%s,%s num=%s,%s"
                  % (nm(w(G_RC)), nm(w(G_RACE)), nm(w(G_WORLD)),
                     nm(w(G_REPLAY)), nm(w(G_PAUSE)), nm(w(G_POOL)),
                     s32(w(G_NUM)), nm(w(G_BY_INDEX)),
                     nm(w(G_BY_INDEX + 4)), nm(w(G_BY_NUMBER)),
                     nm(w(G_BY_NUMBER + 4))))
        for i in range(2):
            p = w(G_BY_INDEX + 4 * i)
            if p:
                self.emit("  p%d %s num=%d style=%d car=%s"
                          % (i, nm(p), s32(w(p + P_NUMBER)),
                             self.sb(p + P_STYLE), nm(w(p + P_CAR))))
        self.emit("  modes" + "".join(" %d" % s32(w(car_at(k) + C_MODE))
                                      for k in range(NCAR)))
        wd = w(G_WORLD)
        if wd:
            fwd = []
            p = w(wd)
            while p != wd and len(fwd) < 32:
                fwd.append(" " + nm(p))
                p = w(p)
            back = []
            p = w(wd + 4)
            while p != wd and len(back) < 32:
                back.append(" " + nm(p))
                p = w(p + 4)
            self.emit("  w heli=%s list%s |%s" % (nm(w(wd + W_HELI)),
                                                  "".join(fwd),
                                                  "".join(back)))

    # ---- the ops ---------------------------------------------------------

    def call(self, fn, *args):
        e = self.e
        sp = e.reg[29] & M32
        e.write(sp - 0x4000, bytes(0x4000))
        e.call(fn, *args, limit=2000000)

    def op(self, t):
        e = self.e
        c = t[0]
        if c == "S":
            self.set_global(t[1], int(t[2], 0))
            return
        if c == "R":
            self.react.append((int(t[1]), int(t[2]), t[3], int(t[4], 0),
                               int(t[5], 0)))
            return
        n = [int(x, 0) for x in t[1:]]
        if c == "D":
            d = driver_at(n[0])
            e.mem[d] = n[1] & 0xff
            e.mem[d + 1] = n[2] & 0xff
            return
        if c == "Y":
            self.t_style[n[0]] = n[1]
            self.t_car[n[0]] = n[2]
            return
        if c == "Q":
            p = self.w(G_BY_NUMBER + 4 * n[0])
            if p:
                e.mem[p + P_STYLE] = n[1] & 0xff
            return
        if c == "K":
            e.mem[rcar_at(n[0]) + RC_POS] = n[1] & 0xff
            return
        if c == "Wt":
            self.t_ai, self.t_cop, self.t_traffic = n[0], n[1], n[2]
            self.t_table = n[3:]
            return
        if c == "Wl":
            self.t_list = n
            return
        if c == "Wh":
            self.t_heli = n[0]
            return
        if c == "N":
            self.fill(RCBUF, RC_BYTES)
            self.rc_made = True
            self.call(CTOR, RCBUF)
        elif c == "X":
            self.call(DTOR, RCBUF, n[0])
        elif c == "G":
            self.call(INIT_FOR_RACE, RCBUF)
        elif c == "U":
            self.call(CLEANUP, RCBUF)
        elif c == "CP":
            self.call(CLEANUP_PLAYERS, RCBUF)
        elif c == "CC":
            self.call(CLEANUP_CARS, RCBUF)
        elif c == "T":
            self.call(CHANGE_STATE, RCBUF, n[0])
        elif c == "M":
            self.call(SEND, RCBUF, n[0], n[1])
        elif c == "P":
            self.call(POST, RCBUF, n[0], n[1])
        elif c == "E":
            self.call(EXECUTE, RCBUF)
        elif c == "A":
            self.call(SET_AI_MODES)
        elif c == "F":
            # Arguments go in sign-extended, as the EE's 64-bit compares
            # want them; so do the stubs' answers.
            r = e.call(BY_NUMBER, RP, n[0], limit=2000000) & M32
            self.emit("  driver %d -> %s" % (n[0], self.name(r)))
        else:
            raise SystemExit("bad op %r" % (t,))
        self.dump()

    def run(self, scenarios):
        for i, sc in enumerate(scenarios):
            self.emit("B %d" % i)
            self.reset()
            for ln in sc:
                self.emit("> " + ln[:40])
                self.op(ln.split())
        return self.out


# ================================================================ the build


def build_harness(tmp, name="racecoord_test"):
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


# ============================================================ the mutations


def M(name, rel, before, after=None):
    return (name, rel, before, after)


MUTATIONS = [
    # The queue.
    M("execute: no executing flag", RCC,
      "        rc->RCExecutingMessage = 1;\n", ""),
    M("execute: flag cleared after the delete", RCC,
      "        rc->RCExecutingMessage = 0;\n        rc_message_delete(m);\n",
      "        rc_message_delete(m);\n        rc->RCExecutingMessage = 0;\n"),
    M("execute: flag left set", RCC,
      "        rc->RCExecutingMessage = 0;\n        rc_message_delete(m);\n",
      "        rc_message_delete(m);\n"),
    M("execute: TICK activates", RCC,
      "        if (m->Msg == RC_ACTIVATE)\n",
      "        if (m->Msg == RC_TICK)\n"),
    M("execute: state from the message after the call", RCC,
      [("        if (m->Msg == RC_ACTIVATE)\n"
        "            rc->CurrentRCState = m->Param;\n", ""),
       ("        if (m->Msg == RC_UNACTIVATE)\n",
        "        if (m->Msg == RC_ACTIVATE)\n"
        "            rc->CurrentRCState = m->Param;\n"
        "        if (m->Msg == RC_UNACTIVATE)\n")]),
    M("execute: UNACTIVATE leaves the state", RCC,
      "        if (m->Msg == RC_UNACTIVATE)\n"
      "            rc->CurrentRCState = RCSTATE_NONE;\n", ""),
    M("execute: UNACTIVATE clears before the call", RCC,
      [("        if (m->Msg == RC_UNACTIVATE)\n"
        "            rc->CurrentRCState = RCSTATE_NONE;\n", ""),
       ("        if (m->Msg == RC_ACTIVATE)\n",
        "        if (m->Msg == RC_UNACTIVATE)\n"
        "            rc->CurrentRCState = RCSTATE_NONE;\n"
        "        if (m->Msg == RC_ACTIVATE)\n")]),
    M("execute: deleted before the call", RCC,
      [("        rc_message_delete(m);\n        n = list->next;\n",
        "        n = list->next;\n"),
       ("        if (cb != NULL)\n",
        "        rc_message_delete(m);\n        if (cb != NULL)\n")]),
    M("execute: next from the old link", RCC,
      "        n = list->next;\n    }\n", "        n = n->next;\n    }\n"),
    M("execute: not unlinked forward", RCC,
      "        n->prev->next = n->next;\n", ""),
    M("execute: not unlinked back", RCC,
      "        n->next->prev = n->prev;\n", ""),
    M("execute: callback takes the state as the message", RCC,
      "            cb(rc, m->Msg, m->Param);\n",
      "            cb(rc, (RCMessage)rc->CurrentRCState, m->Param);\n"),
    M("append: at the head", RCC,
      "    tail->next = &m->Node;\n    list->prev = &m->Node;\n"
      "    m->Node.next = list;\n    m->Msg = msg;\n    m->Node.prev = tail;\n",
      "    (void)tail;\n    m->Node.next = list->next;\n"
      "    list->next->prev = &m->Node;\n    list->next = &m->Node;\n"
      "    m->Msg = msg;\n    m->Node.prev = list;\n"),
    M("append: tail not linked back", RCC,
      "    m->Node.prev = tail;\n", "    m->Node.prev = list;\n"),
    M("append: list's prev left", RCC,
      "    list->prev = &m->Node;\n", ""),
    M("append: parameter dropped", RCC,
      "    m->Param = param;\n", "    m->Param = 0;\n"),
    M("send: always executes", RCC,
      "    if (!rc->RCExecutingMessage)\n        racecoordinator_execute",
      "    if (1)\n        racecoordinator_execute"),
    M("send: never executes", RCC,
      "    if (!rc->RCExecutingMessage)\n        racecoordinator_execute",
      "    if (0)\n        racecoordinator_execute"),
    M("post: executes", RCC,
      "    rc_message_append(rc, msg, param);\n}\n",
      "    rc_message_append(rc, msg, param);\n"
      "    if (!rc->RCExecutingMessage)\n"
      "        racecoordinator_execute_queued_messages(rc);\n}\n"),
    M("change: UNACTIVATE carries the new state", RCC,
      "RC_UNACTIVATE, rc->CurrentRCState);",
      "RC_UNACTIVATE, state);"),
    M("change: ACTIVATE first", RCC,
      "    racecoordinator_send_message(rc, RC_UNACTIVATE, rc->CurrentRCState);\n"
      "    racecoordinator_send_message(rc, RC_ACTIVATE, state);\n",
      "    racecoordinator_send_message(rc, RC_ACTIVATE, state);\n"
      "    racecoordinator_send_message(rc, RC_UNACTIVATE, rc->CurrentRCState);\n"),
    M("change: no TICK", RCC,
      "    racecoordinator_send_message(rc, RC_TICK, 0);\n", ""),
    M("change: TICK carries the state", RCC,
      "    racecoordinator_send_message(rc, RC_TICK, 0);\n",
      "    racecoordinator_send_message(rc, RC_TICK, state);\n"),

    # The constructor.
    M("ctor: executing flag not cleared", RCC,
      "    rc->RCExecutingMessage = 0;\n    rc->RCQueuedMessageList.next",
      "    rc->RCQueuedMessageList.next"),
    M("ctor: state not cleared", RCC,
      "    rc->CurrentRCState = RCSTATE_NONE;\n    rc->BeforePause",
      "    rc->BeforePause"),
    M("ctor: before-pause state not cleared", RCC,
      "    rc->BeforePauseRCState = RCSTATE_NONE;\n", ""),
    M("ctor: countdown not cleared", RCC,
      "    rc->DisplayingCountdownNumber = 0;\n", ""),
    M("ctor: free threshold inclusive", RCC,
      "gBCountFreeMemoryFn(RC_POOL) < RC_PRERACE_MIN_FREE",
      "gBCountFreeMemoryFn(RC_POOL) <= RC_PRERACE_MIN_FREE"),
    M("ctor: free threshold one lower", RCC,
      "#define RC_PRERACE_MIN_FREE 0x7d000",
      "#define RC_PRERACE_MIN_FREE 0x7cfff"),
    M("ctor: free compared unsigned", RCC,
      "gBCountFreeMemoryFn(RC_POOL) < RC_PRERACE_MIN_FREE",
      "(unsigned)gBCountFreeMemoryFn(RC_POOL) < RC_PRERACE_MIN_FREE"),
    M("ctor: animation found, not unloaded", RCC,
      "            gUnloadResourceFileFn(f);\n", "            (void)f;\n"),
    M("ctor: eight slots become sixteen", RCC,
      "#define RC_QUEUE_SLOTS 8", "#define RC_QUEUE_SLOTS 16"),
    M("ctor: pool 15", RCC, "#define RC_POOL 16", "#define RC_POOL 15"),
    M("ctor: demo coordinator not cleared", RCC,
      "    rc->pDemoCameraCoordinator = NULL;\n", ""),
    M("ctor: flyby coordinator not cleared", RCC,
      "    rc->pFlyByCameraCoordinator = NULL;\n    rc->pPreRace",
      "    rc->pPreRace"),
    M("ctor: prerace coordinator not cleared", RCC,
      "    rc->pPreRaceCameraCoordinator = NULL;\n    rc->pEndGame",
      "    rc->pEndGame"),
    M("ctor: end-game screens not cleared", RCC,
      "    rc->pEndGameScreens = NULL;\n    rc->pReplayScreen",
      "    rc->pReplayScreen"),
    M("ctor: replay screen not cleared", RCC,
      "    rc->pReplayScreen = NULL;\n", ""),
    M("ctor: no pause menu", RCC,
      "        ThePauseMenu = gPauseMenuCtorFn(mem);\n",
      "        (void)gPauseMenuCtorFn(mem);\n"),
    M("ctor: port 0", RCC,
      "    rc->PausedJoystickPort = -1;\n", "    rc->PausedJoystickPort = 0;\n"),
    M("ctor: port set after InitForRace", RCC,
      [("    rc->PausedJoystickPort = -1;\n", ""),
       ("    racecoordinator_init_for_race(rc);\n    rc->mpCameraMover",
        "    racecoordinator_init_for_race(rc);\n"
        "    rc->PausedJoystickPort = -1;\n    rc->mpCameraMover")]),
    M("ctor: camera mover cleared before InitForRace", RCC,
      [("    rc->mpCameraMover = NULL;\n", ""),
       ("    rc->PausedJoystickPort = -1;\n",
        "    rc->PausedJoystickPort = -1;\n    rc->mpCameraMover = NULL;\n")]),
    M("ctor: camera mover not cleared", RCC,
      "    rc->mpCameraMover = NULL;\n", ""),
    M("ctor: CD not cleared", RCC, "    rc->mpCD = NULL;\n", ""),
    M("ctor: FOV table not cleared", RCC, "    rc->mpFOVtable = NULL;\n", ""),
    M("ctor: route not cleared", RCC, "    rc->mpRoute = NULL;\n", ""),
    M("ctor: bank verts not cleared", RCC, "    rc->mpBankVerts = NULL;\n", ""),
    M("ctor: eye verts not cleared", RCC, "    rc->mpEyeVerts = NULL;\n", ""),
    M("ctor: word 140 not cleared", RCC, "    rc->PostRaceWord140 = 0;\n", ""),

    # The destructor.
    M("dtor: always changes state", RCC,
      "    if (rc->CurrentRCState != RCSTATE_NONE)\n",
      "    if (1)\n"),
    M("dtor: never changes state", RCC,
      "    if (rc->CurrentRCState != RCSTATE_NONE)\n",
      "    if (0)\n"),
    M("dtor: no cleanup", RCC,
      "    racecoordinator_cleanup_after_race(rc);\n    if (gRCCleanUp",
      "    if (gRCCleanUp"),
    M("dtor: autoreplay cleaned first", RCC,
      "    racecoordinator_cleanup_after_race(rc);\n"
      "    if (gRCCleanUpAutoReplayFn != NULL)\n"
      "        gRCCleanUpAutoReplayFn(rc);\n",
      "    if (gRCCleanUpAutoReplayFn != NULL)\n"
      "        gRCCleanUpAutoReplayFn(rc);\n"
      "    racecoordinator_cleanup_after_race(rc);\n"),
    M("dtor: pause menu kept", RCC,
      "    ThePauseMenu = NULL;\n    bDeleteSlotPool",
      "    bDeleteSlotPool"),
    M("dtor: pause menu flags 1", RCC,
      "        gPauseMenuDestroyFn(ThePauseMenu, 3);",
      "        gPauseMenuDestroyFn(ThePauseMenu, 1);"),
    M("dtor: pool kept", RCC,
      "    bDeleteSlotPool(RCQueuedMessageSlotPool);\n", ""),
    M("dtor: freed on flag 2", RCC, "    if (flags & 1)\n        bFree(rc);",
      "    if (flags & 2)\n        bFree(rc);"),
    M("dtor: always freed", RCC, "    if (flags & 1)\n        bFree(rc);",
      "    bFree(rc);"),
    M("dtor: list not emptied", RCC,
      "    rc->RCQueuedMessageList.next = &rc->RCQueuedMessageList;\n"
      "    rc->RCQueuedMessageList.prev = &rc->RCQueuedMessageList;\n"
      "    if (flags & 1)\n",
      "    if (flags & 1)\n"),

    # InitForRace.
    M("init: player 1 from a rank under 0", RCC,
      "    if ((d != NULL && d->EliminatedRank <= 0) || RaceParametersAIDemoMode) {",
      "    if ((d != NULL && d->EliminatedRank < 0) || RaceParametersAIDemoMode) {"),
    M("init: player 1 needs both", RCC,
      "    if ((d != NULL && d->EliminatedRank <= 0) || RaceParametersAIDemoMode) {",
      "    if ((d != NULL && d->EliminatedRank <= 0) && RaceParametersAIDemoMode) {"),
    M("init: player 1 without the demo", RCC,
      "    if ((d != NULL && d->EliminatedRank <= 0) || RaceParametersAIDemoMode) {",
      "    if (d != NULL && d->EliminatedRank <= 0) {"),
    M("init: player 1 numbered 1", RCC,
      "        player_init((struct Player *)mem, 0, 0);",
      "        player_init((struct Player *)mem, 0, 1);"),
    M("init: player 1 on port 1", RCC,
      "        player_init((struct Player *)mem, 0, 0);",
      "        player_init((struct Player *)mem, 1, 0);"),
    M("init: player 2 from a rank under 0", RCC,
      "    d = race_parameters_get_driver_info_by_driver_number(1);\n"
      "    if (d != NULL && d->EliminatedRank <= 0) {",
      "    d = race_parameters_get_driver_info_by_driver_number(1);\n"
      "    if (d != NULL && d->EliminatedRank < 0) {"),
    M("init: player 2 in the demo", RCC,
      "    d = race_parameters_get_driver_info_by_driver_number(1);\n"
      "    if (d != NULL && d->EliminatedRank <= 0) {",
      "    d = race_parameters_get_driver_info_by_driver_number(1);\n"
      "    if ((d != NULL && d->EliminatedRank <= 0) || RaceParametersAIDemoMode) {"),
    M("init: player 2 on port 0", RCC,
      "        player_init((struct Player *)mem, 1, 1);",
      "        player_init((struct Player *)mem, 0, 1);"),
    M("init: player 2 named Player1", RCC,
      "\"Player2\"", "\"Player1\""),
    M("init: track 0", RCC,
      "    (void)track_get_info(RaceParametersTrackNumber);",
      "    (void)track_get_info(0);"),
    M("init: race before the replay manager", RCC,
      [("    mem = bMalloc((int)sizeof(Race), \"Race\", 0, RC_POOL);\n"
        "    pCurrentRace = race_construct((Race *)mem);\n", ""),
       ("    if (gReplayManagerCtorFn != NULL) {\n",
        "    mem = bMalloc((int)sizeof(Race), \"Race\", 0, RC_POOL);\n"
        "    pCurrentRace = race_construct((Race *)mem);\n"
        "    if (gReplayManagerCtorFn != NULL) {\n")]),
    M("init: replay manager not kept", RCC,
      "        pReplayManager = gReplayManagerCtorFn(mem);",
      "        (void)gReplayManagerCtorFn(mem);"),
    M("init: players before cars", RCC,
      "    racecoordinator_init_cars(rc);\n    racecoordinator_init_players(rc);\n",
      "    racecoordinator_init_players(rc);\n    racecoordinator_init_cars(rc);\n"),
    M("init: AI demo state is the replay demo's", RCC,
      "        state = RCSTATE_AI_DEMO_MODE;",
      "        state = RCSTATE_REPLAY_DEMO_MODE;"),
    M("init: AI demo leaves the eggs", RCC,
      "            gDisableRenderEggsFn();\n", "            ;\n"),
    M("init: AI demo stage countdown", RCC,
      "        stage = RACE_STAGE_RACING;\n    } else if (RaceParametersReplayDemoMode) {",
      "        stage = RACE_STAGE_COUNTDOWN;\n    } else if (RaceParametersReplayDemoMode) {"),
    M("init: replay demo state is the AI demo's", RCC,
      "        state = RCSTATE_REPLAY_DEMO_MODE;\n        stage",
      "        state = RCSTATE_AI_DEMO_MODE;\n        stage"),
    M("init: replay demo stage flyby", RCC,
      "        state = RCSTATE_REPLAY_DEMO_MODE;\n        stage = RACE_STAGE_RACING;",
      "        state = RCSTATE_REPLAY_DEMO_MODE;\n        stage = RACE_STAGE_FLYBY;"),
    M("init: skip-FE ignored", RCC,
      "    } else if (gPlayerCamSkipFE != NULL && *gPlayerCamSkipFE) {",
      "    } else if (0) {"),
    M("init: skip-FE stage countdown", RCC,
      "        state = RCSTATE_RACE_IN_PROGRESS;\n        stage = RACE_STAGE_RACING;",
      "        state = RCSTATE_RACE_IN_PROGRESS;\n        stage = RACE_STAGE_COUNTDOWN;"),
    M("init: skip-FE goes to the flyby", RCC,
      "        state = RCSTATE_RACE_IN_PROGRESS;\n        stage = RACE_STAGE_RACING;",
      "        state = RCSTATE_CAMERA_FLYBY;\n        stage = RACE_STAGE_RACING;"),
    M("init: Be A Cop needs the animation", RCC,
      "    } else if (RaceParametersBeACop || find_prerace_anim() != NULL) {",
      "    } else if (RaceParametersBeACop && find_prerace_anim() != NULL) {"),
    M("init: Be A Cop ignored", RCC,
      "    } else if (RaceParametersBeACop || find_prerace_anim() != NULL) {",
      "    } else if (find_prerace_anim() != NULL) {"),
    M("init: animation looked for first", RCC,
      "    } else if (RaceParametersBeACop || find_prerace_anim() != NULL) {",
      "    } else if (find_prerace_anim() != NULL || RaceParametersBeACop) {"),
    M("init: flyby state in progress", RCC,
      "        state = RCSTATE_CAMERA_FLYBY;\n        stage = RACE_STAGE_FLYBY;",
      "        state = RCSTATE_RACE_IN_PROGRESS;\n        stage = RACE_STAGE_FLYBY;"),
    M("init: flyby stage countdown", RCC,
      "        state = RCSTATE_CAMERA_FLYBY;\n        stage = RACE_STAGE_FLYBY;",
      "        state = RCSTATE_CAMERA_FLYBY;\n        stage = RACE_STAGE_COUNTDOWN;"),
    M("init: plain start racing", RCC,
      "        state = RCSTATE_RACE_IN_PROGRESS;\n        stage = RACE_STAGE_COUNTDOWN;\n    }",
      "        state = RCSTATE_RACE_IN_PROGRESS;\n        stage = RACE_STAGE_RACING;\n    }"),
    M("init: no ghosts", RCC,
      "    race_setup_ghost_cars(pCurrentRace);\n", ""),
    M("init: no AI modes", RCC,
      "    set_ai_driver_modes_from_players();\n    if (gCollision",
      "    if (gCollision"),
    M("init: speech before the collision sounds", RCC,
      "    if (gCollisionSoundResetFn != NULL)\n"
      "        gCollisionSoundResetFn();\n"
      "    if (gSpeechFlushQueueFn != NULL)\n"
      "        gSpeechFlushQueueFn();\n",
      "    if (gSpeechFlushQueueFn != NULL)\n"
      "        gSpeechFlushQueueFn();\n"
      "    if (gCollisionSoundResetFn != NULL)\n"
      "        gCollisionSoundResetFn();\n"),
    M("init: coordinator set after the change", RCC,
      "    pRaceCoordinator = rc;\n    racecoordinator_change_state(rc, state);\n",
      "    racecoordinator_change_state(rc, state);\n    pRaceCoordinator = rc;\n"),

    # CleanupAfterRace and the cleanups.
    M("cleanup: flyby deleted first", RCC,
      [("    if (rc->pPreRaceCameraCoordinator != NULL) {\n"
        "        if (gCameraCoordinatorDeleteFn != NULL)\n"
        "            gCameraCoordinatorDeleteFn(rc->pPreRaceCameraCoordinator);\n"
        "        rc->pPreRaceCameraCoordinator = NULL;\n    }\n", ""),
       ("        rc->pFlyByCameraCoordinator = NULL;\n    }\n",
        "        rc->pFlyByCameraCoordinator = NULL;\n    }\n"
        "    if (rc->pPreRaceCameraCoordinator != NULL) {\n"
        "        if (gCameraCoordinatorDeleteFn != NULL)\n"
        "            gCameraCoordinatorDeleteFn(rc->pPreRaceCameraCoordinator);\n"
        "        rc->pPreRaceCameraCoordinator = NULL;\n    }\n")]),
    M("cleanup: prerace kept", RCC,
      "        rc->pPreRaceCameraCoordinator = NULL;\n    }\n", "    }\n"),
    M("cleanup: flyby kept", RCC,
      "        rc->pFlyByCameraCoordinator = NULL;\n    }\n", "    }\n"),
    M("cleanup: cars before players", RCC,
      "    racecoordinator_cleanup_players(rc);\n    racecoordinator_cleanup_cars(rc);\n",
      "    racecoordinator_cleanup_cars(rc);\n    racecoordinator_cleanup_players(rc);\n"),
    M("cleanup: effects killed after the race", RCC,
      [("    if (gKillAllActiveEffectsFn != NULL)\n"
        "        gKillAllActiveEffectsFn();\n", ""),
       ("    pCurrentRace = NULL;\n",
        "    pCurrentRace = NULL;\n"
        "    if (gKillAllActiveEffectsFn != NULL)\n"
        "        gKillAllActiveEffectsFn();\n")]),
    M("cleanup: race flags 1", RCC, "        race_destroy(pCurrentRace, 3);",
      "        race_destroy(pCurrentRace, 1);"),
    M("cleanup: race kept", RCC, "    pCurrentRace = NULL;\n", ""),
    M("cleanup: world before the race", RCC,
      "    if (pCurrentRace != NULL)\n        race_destroy(pCurrentRace, 3);\n"
      "    pCurrentRace = NULL;\n"
      "    if (pCurrentWorld != NULL)\n        world_destroy(pCurrentWorld, 3);\n"
      "    pCurrentWorld = NULL;\n",
      "    if (pCurrentWorld != NULL)\n        world_destroy(pCurrentWorld, 3);\n"
      "    pCurrentWorld = NULL;\n"
      "    if (pCurrentRace != NULL)\n        race_destroy(pCurrentRace, 3);\n"
      "    pCurrentRace = NULL;\n"),
    M("cleanup: world flags 1", RCC, "        world_destroy(pCurrentWorld, 3);",
      "        world_destroy(pCurrentWorld, 1);"),
    M("cleanup: world kept", RCC, "    pCurrentWorld = NULL;\n", ""),
    M("cleanup: oneshots before the jukebox", RCC,
      "    if (gJukeboxStopFn != NULL)\n        gJukeboxStopFn();\n"
      "    if (gSound3dOneshotResetFn != NULL)\n        gSound3dOneshotResetFn();\n",
      "    if (gSound3dOneshotResetFn != NULL)\n        gSound3dOneshotResetFn();\n"
      "    if (gJukeboxStopFn != NULL)\n        gJukeboxStopFn();\n"),
    M("cleanup: replay manager kept", RCC, "    pReplayManager = NULL;\n", ""),
    M("cleanup: replay manager after the screens", RCC,
      [("    if (pReplayManager != NULL && gReplayManagerDestroyFn != NULL)\n"
        "        gReplayManagerDestroyFn(pReplayManager, 3);\n"
        "    pReplayManager = NULL;\n", ""),
       ("        rc->pEndGameScreens = NULL;\n    }\n",
        "        rc->pEndGameScreens = NULL;\n    }\n"
        "    if (pReplayManager != NULL && gReplayManagerDestroyFn != NULL)\n"
        "        gReplayManagerDestroyFn(pReplayManager, 3);\n"
        "    pReplayManager = NULL;\n")]),
    M("cleanup: screens kept", RCC,
      "        rc->pEndGameScreens = NULL;\n    }\n", "    }\n"),
    M("cleanup: screens flags 1", RCC,
      "            gEndGameScreensDestroyFn(rc->pEndGameScreens, 3);",
      "            gEndGameScreensDestroyFn(rc->pEndGameScreens, 1);"),
    M("cleanup: players first to last", RCC,
      "            struct Player *p = PlayerPlayersByIndex[n - 1];",
      "            struct Player *p = PlayerPlayersByIndex[PlayerNumPlayers - n];"),
    M("cleanup: players flags 1", RCC, "                player_destroy(p, 3);",
      "                player_destroy(p, 1);"),
    M("cleanup: only the last player", RCC,
      "                player_destroy(p, 3);\n                n = PlayerNumPlayers;",
      "                player_destroy(p, 3);\n                n = 0;"),
    M("players: only the first", RCC,
      "    for (i = 0; i < PlayerNumPlayers; i++)\n        player_cleanup",
      "    for (i = 0; i < 1 && i < PlayerNumPlayers; i++)\n        player_cleanup"),
    M("players: last to first", RCC,
      "        player_cleanup_after_race(PlayerPlayersByIndex[i]);",
      "        player_cleanup_after_race(PlayerPlayersByIndex[PlayerNumPlayers - 1 - i]);"),
    M("cars: flags 1", RCC, "        car_destruct(c, 3);", "        car_destruct(c, 1);"),
    M("cars: last first", RCC,
      "        Car *c = (Car *)w->CarList.next;",
      "        Car *c = (Car *)w->CarList.prev;"),
    M("cars: helicopter kept", RCC,
      "        pCurrentWorld->Helicopter = NULL;\n", ""),
    M("cars: helicopter flags 1", RCC,
      "            gChopperDestroyFn(w->Helicopter, 3);",
      "            gChopperDestroyFn(w->Helicopter, 1);"),
    M("cars: helicopter left alone", RCC,
      "            gChopperDestroyFn(w->Helicopter, 3);\n", "            ;\n"),

    # The drivers.
    M("driver: last match wins", RCC,
      [("    int32_t i;\n\n    for (i = 0; i < RaceParametersNumDriverInfo",
        "    int32_t i;\n    struct DriverInfo *last = NULL;\n\n"
        "    for (i = 0; i < RaceParametersNumDriverInfo"),
       ("            return &RaceParametersDriverInfo[i];\n    }\n    return NULL;",
        "            last = &RaceParametersDriverInfo[i];\n    }\n    return last;")]),
    M("driver: one past the count", RCC,
      "    for (i = 0; i < RaceParametersNumDriverInfo; i++) {\n        if (race_parameters_get_driver_info(i)",
      "    for (i = 0; i <= RaceParametersNumDriverInfo; i++) {\n        if (race_parameters_get_driver_info(i)"),
    M("driver: matched on the rank", RCC,
      "        if (race_parameters_get_driver_info(i)->UniqueDriverNumber == number)",
      "        if (race_parameters_get_driver_info(i)->EliminatedRank == number)"),
    M("driver: number compared unsigned", RCC,
      "        if (race_parameters_get_driver_info(i)->UniqueDriverNumber == number)",
      "        if ((uint8_t)race_parameters_get_driver_info(i)->UniqueDriverNumber == number)"),
    M("driver: the next one returned", RCC,
      "            return &RaceParametersDriverInfo[i];",
      "            return &RaceParametersDriverInfo[i + 1];"),

    # The AI driving styles.
    M("modes: no Race check", RCC,
      "    if (pCurrentWorld == NULL || pCurrentRace == NULL)\n",
      "    if (pCurrentWorld == NULL)\n"),
    M("modes: two cars from three", RCC,
      "    if (RaceParametersNumPlayerCars == 2) {",
      "    if (RaceParametersNumPlayerCars >= 2) {"),
    M("modes: swapped on a tie", RCC,
      "        if (posB < posA) {", "        if (posB <= posA) {"),
    M("modes: never swapped", RCC,
      "        if (posB < posA) {", "        if (0) {"),
    M("modes: half by shift", RCC,
      "        half = RaceParametersNumAICars / 2;",
      "        half = RaceParametersNumAICars >> 1;"),
    M("modes: half not moved for A", RCC,
      "        if (!(half < posA))\n            half++;\n", ""),
    M("modes: half not moved for B", RCC,
      "        if (!(half < posB))\n            half++;\n", ""),
    M("modes: A moves it when behind", RCC,
      "        if (!(half < posA))", "        if (!(half <= posA))"),
    M("modes: B moves it when behind", RCC,
      "        if (!(half < posB))", "        if (!(half <= posB))"),
    M("modes: trailer at the middle", RCC,
      "            if (half < race_get_racing_car(pCurrentRace, c)->RacePosition)",
      "            if (half <= race_get_racing_car(pCurrentRace, c)->RacePosition)"),
    M("modes: leader and trailer swapped", RCC,
      "                c->State.DriverMode = trailer;\n            else\n"
      "                c->State.DriverMode = leader;",
      "                c->State.DriverMode = leader;\n            else\n"
      "                c->State.DriverMode = trailer;"),
    M("modes: two-car loop from the table's start", RCC,
      "            Car *c = w->CarTable[w->AICarPos + i];",
      "            Car *c = w->CarTable[i];"),
    M("modes: two-car loop one short", RCC,
      "        for (i = 0; i < w->CopCarPos - w->AICarPos; i++) {",
      "        for (i = 0; i < w->CopCarPos - w->AICarPos - 1; i++) {"),
    M("modes: one-car loop to the traffic", RCC,
      "        for (i = 0; i < w->CopCarPos - w->AICarPos; i++)\n            w->CarTable",
      "        for (i = 0; i < w->TrafficCarPos - w->AICarPos; i++)\n            w->CarTable"),
    M("modes: one car takes the last player", RCC,
      "        int32_t style = PlayerPlayersByIndex[0]->PlayerSettings.DrivingStyle;",
      "        int32_t style = PlayerPlayersByIndex[PlayerNumPlayers - 1]->PlayerSettings.DrivingStyle;"),
    M("modes: one-car loop from the table's start", RCC,
      "            w->CarTable[w->AICarPos + i]->State.DriverMode = style;",
      "            w->CarTable[i]->State.DriverMode = style;"),
]

# Mutants that cannot change what either side computes, each with why.
EQUIVALENT = {
    "dtor: list not emptied":
        "retail's ~bTList frees what is left on the list into the pool the "
        "destructor has just deleted, so no scenario leaves a message there "
        "at the destructor; with the list already empty, emptying it again "
        "changes nothing",
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    hostbuild.recover()
    m = Model()
    sc = script()
    base = m.run(sc)
    caught, survived, missing, equivalent = 0, [], [], []
    scdir = tempfile.TemporaryDirectory()
    scp = Path(scdir.name) / "scenarios.txt"
    scp.write_text(encode(sc))
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, scp, out)
        if diff(base, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for mut in todo:
        name, rel, before, after = mut
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        edits = before if isinstance(before, list) else [(before, after)]
        new, bad = text, None
        for b, a in edits:
            probe = b.replace(NL, "\r\n") if crlf else b
            repl = a.replace(NL, "\r\n") if crlf else a
            if new.count(probe) != 1:
                bad = "NOT FOUND" if not new.count(probe) else "NOT UNIQUE"
                break
            new = new.replace(probe, repl, 1)
        if bad:
            missing.append(name)
            print("  %-44s PATTERN %s" % (name, bad))
            continue
        try:
            hostbuild.write_source(path, new)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = build_harness(tmp)
                except SystemExit:
                    print("  %-44s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, scp, out)
                if rc == pcc.HARNESS_HUNG:
                    print("  %-44s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-44s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-44s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-44s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-44s SURVIVED" % name)
                    survived.append(name)
        finally:
            try:
                hostbuild.write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))
    scdir.cleanup()

    real = [m for m in todo if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    ran = {m[0] for m in todo}
    stale = [n for n in EQUIVALENT
             if n not in equivalent and n not in missing
             and (n in ran or only is None)]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally above is over %d of %d"
              % (len(missing), len(real), len(todo)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
    for name in holes:
        print("  unexplained: %s" % name)
    for name in stale:
        print("  listed as equivalent but %s: %s"
              % ("caught" if name in ran else "names no mutation", name))
    return 1 if (holes or missing or stale) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--dump", metavar="PREFIX")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None))

    layout = arm_layout_check()
    m = Model()
    sc = script()
    lines = m.run(sc)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = Path(tmp) / "scenarios.txt"
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
    ops = sum(len(s) for s in sc)
    print("%d scenarios, %d ops, %d lines, %d differ"
          % (len(sc), ops, len(harness), n))
    sys.exit(1 if (n or rc or layout) else 0)


if __name__ == "__main__":
    main()
