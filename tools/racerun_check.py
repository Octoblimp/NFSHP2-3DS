#!/usr/bin/env python3
"""Cross-check 3DS Files/source/racerun.c, Race::Init and the lap counting
under it, against the retail image itself, run in mipsemu.

The model is the image. RacingCar::Init (0x00146bb0), FakeStartline-
Crossing (0x00146e08), CheckBoundaryCrossing (0x00146e58), UpdateLapCounts
(0x00146fd0) and GetPlayer (0x001475b8), Race::Init (0x00147960),
AddRacingCars (0x00147dc0), AddRacingCar (0x00147e88), SetRaceStage
(0x00147ef0) and SortRacingCarsByLeadership (0x00148218) run as shipped,
and so do Timer::Round (0x001a3e28) and RoundSeconds (0x001a3d70), and
under them Race::GetLapNumberExact, TrackPathManager::
ComparePercentDistances and TimeAroundTrackTable's constructor with its
TrackPathCoordinate. The harness (tools/src/racerun_test.c) runs the port
over the same script, and the two transcripts are diffed.

Everything else is a stub that prints its arguments: bMalloc (which hands
back the table), Car::SetMovementMode, RealDriver::DisableStartLineState,
FrontendDatabase::TheRaceIsLeaving, TrackPathCoordinate::UpdatePosition
(racecore_check's hash, the ratio that over TrackLength as trackpath.c's
seam has it) and the drivers' GetDesiredSpeed, which sits at a made-up
address in a vtable the script owns, with the this-adjustment it sets.
bMemSet is native.

The script lays out the rest at retail's offsets: the Race, pCurrentRace
(gp-22272), the World (gp-22120) and its CarTable, twelve Cars with their
CarTypeInfos and drivers, the ReplayManager (gp-22440, which the image
reads unchecked), WorldTimer, WorldTimeFrames and WorldTimeElapsed,
TheRaceParameters' RaceType (+32), Point2Point (+40), NumPlayerCars (+48)
and BeACop (+628), TheTrackPathManager's TrackLength, and two TrackRoutes
on the racing list for the table. The Race, the Cars and their records are
filled with 0xa5 first, so a field the image leaves alone shows.

    python tools/racerun_check.py
    python tools/racerun_check.py --mutate [--only a,b]
    python tools/racerun_check.py --dump out/racerun
"""
import argparse
import math
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
import racecore_check as rcc
import retail_model
from mipsemu import M32, f_to_bits, fbits_to, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/racerun_test.c"
RRC = "3DS Files/source/racerun.c"
RRH = "3DS Files/source/racerun.h"
TMC = "3DS Files/source/timer.c"
SOURCES = [HARNESS, RRC, TMC,
           "3DS Files/source/racecore.c",
           "3DS Files/source/race.c",
           "3DS Files/source/trackroute.c",
           "3DS Files/source/trackpath.c",
           "3DS Files/source/quickspline.c",
           "3DS Files/source/vtable.c",
           "3DS Files/source/bmem.c",
           "3DS Files/source/bmatrix.c",
           "3DS Files/source/bvector.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c",
           "3DS Files/source/bchunk.c"]

HARNESS_TIMEOUT = 120

ARM_GCC = rcc.ARM_GCC
CTRU_INCLUDE = rcc.CTRU_INCLUDE

# ================================================================ the image

GP = 0x003358f0
RC_INIT = 0x00146bb0
FAKE = 0x00146e08
CHECK = 0x00146e58
UPDATE = 0x00146fd0
GET_PLAYER = 0x001475b8
RACE_INIT = 0x00147960
ADD_CARS = 0x00147dc0
ADD_CAR = 0x00147e88
SET_STAGE = 0x00147ef0
SORT = 0x00148218
ROUND = 0x001a3e28
ROUND_SECONDS = 0x001a3d70

B_MALLOC = 0x002577c0
SET_MOVEMENT = 0x00131618
DISABLE_SLS = 0x0013b360
RACE_LEAVING = 0x00187570
UPDATE_POS = rcc.UPDATE_POS
TPC_DTOR = rcc.TPC_DTOR
B_MEMSET = rcc.B_MEMSET

G_RACE = GP - 22272
G_WORLD = GP - 22120
G_REPLAY = GP - 22440
G_TIMER = GP - 19576
G_FRAMES = GP - 19564
G_ELAPSED = GP - 19560

RP = 0x0031a898
RP_RTYPE = RP + 32
RP_P2P = RP + 40
RP_NPC = RP + 48
RP_COP = RP + 628
TPM = 0x0031bc38            # TrackLength at 0
FDB = 0x002fc050
TATT_NAME = 0x002af480

RACE_BYTES = 1716
RC_BYTES = 192
TATT_BYTES = 2052

# Car, CarTypeInfo and CarDriver, at retail's offsets.
CAR_CTI, CAR_PLAYER, CAR_RC, CAR_MODE, CAR_DRV = 12, 24, 28, 32, 44
CAR_DIST, CAR_WHEELS, CAR_SPEED, CAR_BOOST = 940, 956, 960, 992
CAR_REND, CAR_RATIO = 1192, 2032
CTI_CLASS, CTI_SL = 230, 800
DRV_THR, DRV_BRK, DRV_EB, DRV_VT, DRV_SLS = 532, 536, 540, 556, 572
VT_DESIRED = 136

NCAR = 12
NROUTE = 2
MAX_POINTS = 6

MISC = 0x01000000
RACE = MISC
TATT = MISC + 0x1000
WORLD = MISC + 0x2000
REPLAY = MISC + 0x2100
INFO = MISC + 0x2200
TIMER = MISC + 0x2300
VTAB = MISC + 0x2400
PLAYERS = MISC + 0x2800
CTIS = MISC + 0x4000
DRVS = MISC + 0x8000
CARS = MISC + 0x10000
FN_DESIRED = MISC + 0x1ff00

PATTERN = 0xa5

# RacingCar's fields the script can set: offset and width.
RC_FIELDS = {"fo": (12, 1), "fle": (32, 4), "pos": (10, 1), "lap": (8, 1),
             "done": (9, 1), "cur": (4, 2), "high": (6, 2), "prev": (28, 4),
             "cle": (20, 4), "dcle": (24, 4), "bct0": (36, 4),
             "top": (184, 4)}
RACE_FIELDS = {"n": (24, 4), "nb": (1616, 2), "fin": (1619, 1),
               "bd0": (1620, 4), "bd1": (1624, 4), "bd2": (1628, 4),
               "bd3": (1632, 4), "bd4": (1636, 4), "rt": (16, 4),
               "st": (0, 4)}


def car_at(i):
    return CARS + 0x1000 * i


def cti_at(i):
    return CTIS + 0x400 * i


def drv_at(i):
    return DRVS + 0x400 * i


def rc_at(k):
    return RACE + 36 + RC_BYTES * k


def arm_layout_check():
    """BoundaryCrossingInfo in an ARM compile of racerun.h. Returns 0 when
    it holds or devkitARM is not there."""
    if not ARM_GCC.exists():
        print("devkitARM not found; the ARM layout check is skipped")
        return 0
    lines = [
        "#include <stddef.h>",
        "#include \"racerun.h\"",
        "_Static_assert(sizeof(BoundaryCrossingInfo) == 12, \"bci\");",
        "_Static_assert(offsetof(BoundaryCrossingInfo, CrossedBackwards)"
        " == 4, \"back\");",
        "_Static_assert(offsetof(BoundaryCrossingInfo, TimeSinceCrossing)"
        " == 8, \"since\");",
        "_Static_assert(sizeof(struct RacingCar) == 192, \"rc\");",
    ]
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "racerun_layout.c"
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
    print("ARM layout: BoundaryCrossingInfo is 12 bytes with "
          "TimeSinceCrossing at 8")
    return 0


fx = rcc.fx
sb = rcc.sb
sh = rcc.sh
h = rcc.h


def fb(x):
    return h(f_to_bits(x))


# ============================================================ the scenarios

ROUND_TIMES = (0, 1, 2, 19, 20, 21, 39, 40, 41, 59, 60, 61, 79, 80, 3999,
               4000, 4001, 4020, 0x7fffffff, 0x80000000, 0xffffffff,
               0x7ffffff0, 0x7fffff00, 0xfffffff0, 0x40000000, 123456789)
ROUND_FACTORS = (0.01, 0.01, 0.01, 0.1, 1.0, 0.001, 0.25, 0.5, 2.0, 0.03,
                 60.0, 0.015)


def s_round(rnd):
    """Timer::Round and RoundSeconds over the ends of the clock, the halves
    and random times, at a hundredth and at other steps."""
    out = []
    for case in range(400):
        if rnd.random() < 0.4:
            t = rnd.choice(ROUND_TIMES)
        elif rnd.random() < 0.5:
            t = rnd.randrange(0, 1 << 20)
        else:
            t = rnd.randrange(1 << 32)
        if rnd.random() < 0.8:
            f = rnd.choice(ROUND_FACTORS)
        else:
            f = rnd.uniform(0.001, 100.0)
        out.append("%s %d %s" % (rnd.choice(("TR", "TS")), t, fb(f)))
    return out


def s_car(rnd, i, mode=None, player=None):
    """Car i's control, player, class and rendering, and its numbers."""
    if mode is None:
        mode = rnd.choice((0, 1, 1, 2, 2, 2, 3))
    if player is None:
        player = rnd.choice((0, 0, 1))
    out = ["CA %d %d %d %d %d" % (i, mode, player, rnd.randrange(11),
                                  rnd.choice((0, 0, 1, 5)))]
    out.append(s_numbers(rnd, i))
    out.append(s_driver(rnd, i))
    return out


SPEEDS = (0.0, -0.0, 1.0, 1.0000001, 0.99999994, -1.0, -30.0, 30.0, 80.0,
          999.0, 1000.0, 1001.0, 2000.0, -2000.0)


def rspeed(rnd):
    if rnd.random() < 0.3:
        return rnd.choice(SPEEDS)
    return rnd.uniform(-20.0, 90.0)


def s_numbers(rnd, i):
    wheels = rnd.choice((0, 2, 3, 3, 4, 4, 4, 5, -1))
    boost = rnd.choice((1.0, 1.0, 0.5, 0.0, 1.5, 2.0, rnd.uniform(0.0, 3.0)))
    dist = rnd.choice((0.0, 0.0, rnd.uniform(0.0, 50000.0)))
    sl = rnd.choice((0.0, 50.0, 120.0, 200.0, 1e9, -10.0,
                     rnd.uniform(20.0, 250.0)))
    return "CF %d %d %s %s %s %s %s" % (i, wheels, fb(rspeed(rnd)), fb(boost),
                                         fb(dist), fb(rnd.random()), fb(sl))


WANTS = (0.0, -0.0, -5.0, 10.0, 60.0, 500.0, 999.0, 1000.0, 1e6, -1e6)


def s_driver(rnd, i):
    if rnd.random() < 0.3:
        want = rnd.choice(WANTS)
    else:
        want = rnd.uniform(-10.0, 120.0)
    return "DV %d %s %s %s %d %s" % (
        i, fb(rnd.choice((0.0, 0.5, 1.0))), fb(rnd.choice((0.0, 0.25, 1.0))),
        fb(rnd.choice((0.0, 1.0))), rnd.choice((0, 0, 1, 2, 7)), fb(want))


BOUNDS = (0.0, -0.0, 5.0, 25.0, 33.0, 50.0, 66.0, 95.0, 99.99, 100.0)


def s_boundaries(rnd):
    nb = rnd.choice((1, 1, 2, 3, 4, 5, 5))
    if rnd.random() < 0.5:
        ds = [rnd.choice(BOUNDS) for _ in range(nb)]
    else:
        ds = sorted(rnd.uniform(-5.0, 105.0) for _ in range(nb))
    out = ["RS nb %d" % nb,
           "RS fin %d" % rnd.choice((0, 0, 0, nb - 1, nb - 1, -1,
                                     rnd.randrange(nb)))]
    for k in range(5):
        d = ds[k] if k < nb else rnd.choice((0.0, 50.0))
        out.append("RS bd%d %s" % (k, fb(d)))
    return out


PCTS = (0.0, -0.0, 25.0, -25.0, 25.000002, -25.000002, 24.999998, 50.0,
        -50.0, 100.0, 99.9, 0.1, -0.1, 75.0, 74.99999, 125.0)


def rpct(rnd):
    if rnd.random() < 0.4:
        return rnd.choice(PCTS)
    return rnd.uniform(-20.0, 120.0)


def s_check(rnd):
    """CheckBoundaryCrossing from everywhere to everywhere: both sides of
    the boundary, the 25 percent fence, the speed's 1 m/s floor and the
    track's length."""
    out = []
    for i in range(2):
        out += s_car(rnd, i)
        out.append("RI %d %d" % (i, i))
    for case in range(300):
        k = rnd.randrange(2)
        if rnd.random() < 0.2:
            out.append("S len %s" % fb(rnd.choice(
                (1.0, 1.0, 0.0, 100.0, 3000.0, 12345.6,
                 rnd.uniform(500.0, 20000.0)))))
        if rnd.random() < 0.3:
            out.append(s_numbers(rnd, k))
        out.append("RF %d prev %s" % (k, fb(rpct(rnd))))
        out.append("K %d %s %s" % (k, fb(rpct(rnd)), fb(rpct(rnd))))
    return out


def s_lap_globals(rnd):
    out = []
    if rnd.random() < 0.15:
        out.append("S replay %d" % rnd.choice((0, 0, 1, 2)))
    if rnd.random() < 0.15:
        out.append("S rtype %d" % rnd.choice((0, 1, 2, 2, 3, 5)))
    if rnd.random() < 0.1:
        out.append("S p2p %d" % rnd.choice((0, 1)))
    if rnd.random() < 0.1:
        out.append("S delta %d" % rnd.choice((0, 0, 8, -4, 16)))
    return out


def s_laps(rnd, steps):
    """A few cars driven round a track of boundaries for many laps, now and
    then backwards, through the replay's and the time trial's arms, with
    the timer, the race's time and the speeds moving."""
    out = s_boundaries(rnd)
    out.append("S len %s" % fb(rnd.choice((1.0, 3000.0,
                                           rnd.uniform(800.0, 9000.0)))))
    out.append("S rtype %d" % rnd.choice((0, 1, 2)))
    out.append("S p2p %d" % rnd.choice((0, 0, 1)))
    out.append("S timer %d" % rnd.choice((0, 0, 4000, rnd.randrange(1 << 24))))
    ncar = rnd.randrange(1, 4)
    ratio = []
    for i in range(ncar):
        out += s_car(rnd, i)
        ratio.append(rnd.random())
        out.append("CR %d %s" % (i, fb(ratio[i])))
        out.append("RI %d %d" % (i, i))
        if rnd.random() < 0.7:
            out.append("F %d" % i)
    timer = 0
    rt = 0
    for step in range(steps):
        out += s_lap_globals(rnd)
        timer = (timer + rnd.choice((0, 33, 66, 67, rnd.randrange(1, 400)))) \
            & M32
        out.append("S timer %d" % timer)
        out.append("S elapsed %s" % fb(rnd.choice(
            (1.0 / 60, 1.0 / 60, 1.0 / 30, 0.0, -0.01, 0.5))))
        if rnd.random() < 0.5:
            rt = (rt + rnd.randrange(0, 400)) & 0x7fffffff
            out.append("RS rt %d" % rt)
        elif rnd.random() < 0.05:
            out.append("RS rt %d" % rnd.choice((0, 0xffffff00, 0x7fffffff)))
        for i in range(ncar):
            if rnd.random() < 0.15:
                out.append(s_numbers(rnd, i))
            if rnd.random() < 0.05:
                out.append(s_driver(rnd, i))
            if rnd.random() < 0.05:
                out += s_car(rnd, i)[:1]
            r = rnd.random()
            if r < 0.08:
                ratio[i] = rnd.random()
            elif r < 0.2:
                ratio[i] -= rnd.uniform(0.0, 0.05)
            else:
                ratio[i] += rnd.uniform(0.0, 0.08)
            ratio[i] %= 1.0
            out.append("CR %d %s" % (i, fb(ratio[i])))
            out.append("U %d" % i)
        if rnd.random() < 0.03:
            out.append("F %d" % rnd.randrange(ncar))
        if rnd.random() < 0.03:
            out.append("P %d" % rnd.randrange(ncar))
    return out


def s_world(rnd, max_racing=8):
    """The World's counts: racing cars below CopCarPos, at most
    `max_racing` of them, traffic from TrafficCarPos to TotalNumCars."""
    ai = rnd.randrange(0, max_racing + 1)
    cop = rnd.randrange(ai, max_racing + 1)
    if rnd.random() < 0.15:
        ai, cop = cop, ai             # the second loop adds nothing
    racing = max(ai, cop)
    traffic = rnd.randrange(racing, NCAR + 1)
    total = rnd.randrange(traffic, NCAR + 1)
    if rnd.random() < 0.1:
        total = rnd.randrange(0, traffic + 1)     # no traffic at all
    out = ["W %d %d %d %d" % (total, ai, cop, traffic)]
    if rnd.random() < 0.4:
        perm = list(range(NCAR))
        rnd.shuffle(perm)
        for i, c in enumerate(perm):
            out.append("WT %d %d" % (i, c))
    return out, racing


def s_stage(rnd):
    """AddRacingCars over the World's counts, then SetRaceStage through
    every stage, the drivers' fields reset between, the clock moving."""
    out = []
    for case in range(12):
        w, racing = s_world(rnd)
        out += w
        for i in range(NCAR):
            out += s_car(rnd, i)
        out.append("RS n 0")
        if rnd.random() < 0.5:
            out.append("AC")
        else:
            for k in range(racing):
                out.append("A %d" % rnd.randrange(NCAR))
        for _ in range(rnd.randrange(2, 6)):
            out.append("S timer %d" % rnd.randrange(1 << 31))
            out.append("S frames %d" % rnd.randrange(1 << 20))
            if rnd.random() < 0.3:
                out.append("S p2p %d" % rnd.choice((0, 1)))
            for i in range(NCAR):
                if rnd.random() < 0.3:
                    out.append(s_driver(rnd, i))
            out.append("G %d" % rnd.choice((0, 1, 2, 3, 3, 4, 4, 4, 5, -1)))
    return out


def s_routes(rnd):
    out = []
    for r in range(NROUTE):
        n = rnd.choice((1, 2, 3, 4, MAX_POINTS, MAX_POINTS))
        out.append("RTP %d %d" % (r, n))
        for line in range(rcc.NLINE):
            if rnd.random() < 0.75:
                f = rnd.choice((1, 2, 3))
            else:
                f = rnd.choice((0, 4))
            out.append("RTL %d %d %d" % (r, line, f))
        x, y = rnd.uniform(-500, 500), rnd.uniform(-500, 500)
        for k in range(n):
            a = rnd.uniform(-math.pi, math.pi)
            step = rnd.choice((10.0, 40.0, 40.0))
            x += step * math.cos(a)
            y += step * math.sin(a)
            out.append("RTT %d %d %s %s %s %s %d %d"
                       % (r, k, fb(x), fb(y), fb(math.cos(a)),
                          fb(math.sin(a)), rnd.randrange(-32768, 32768),
                          rnd.randrange(1, 256)))
    order = list(range(NROUTE))
    rnd.shuffle(order)
    order = order[:rnd.choice((0, 1, 1, 2, 2, 2))]
    out.append("RTQ" + "".join(" %d" % r for r in order))
    return out


def s_init(rnd):
    """Race::Init over the World, the two-player cop's second car, the car
    classes and the racing routes the table is built from."""
    out = []
    for case in range(24):
        out += s_routes(rnd)
        out.append("S len %s" % fb(rnd.choice((1.0, 1.0, 2.0, 0.5))))
        out.append("S seed %d" % rnd.randrange(1 << 16))
        cop = rnd.choice((0, 1, 1))
        npc = rnd.choice((1, 2, 2, 3))
        out.append("S cop %d" % cop)
        out.append("S npc %d" % npc)
        need = 2 if (cop and npc == 2) else 1
        while True:
            w, racing = s_world(rnd)
            if racing >= need:
                break
        out += w
        for i in range(NCAR):
            out += s_car(rnd, i)
        out.append("RS n 0")
        out.append("I %d" % rnd.choice((0, 1, 2, 2, 3, 4)))
    return out


def s_sort(rnd):
    """The sort over every order of unfinished cars, ties and NaNs among
    them, and finished ones at distinct places."""
    out = []
    for case in range(60):
        n = rnd.choice((0, 1, 2, 3, 5, 8, 8))
        perm = list(range(8))
        rnd.shuffle(perm)
        out.append("RS n %d" % n)
        for i in range(8):
            out.append("RP %d %d" % (i, perm[i]))
        places = list(range(1, n + 1))
        rnd.shuffle(places)
        nfin = rnd.randrange(0, n + 1) if rnd.random() < 0.5 else 0
        for i in range(8):
            k = perm[i]
            fo = places[i] if i < nfin else 0
            out.append("RF %d fo %d" % (k, fo))
            r = rnd.random()
            if r < 0.15:
                v = h(0x7fc00000)
            elif r < 0.4:
                v = fb(rnd.choice((0.0, -0.0, 1.0, 2.5, -1.0)))
            else:
                v = fb(rnd.uniform(-1.0, 4.0))
            out.append("RF %d fle %s" % (k, v))
            out.append("RF %d pos %d" % (k, rnd.choice((0, 1, 3, 8, -1, 100))))
        out.append("O")
        if rnd.random() < 0.3:
            out.append("O")
    return out


def s_race(rnd, steps):
    """A race the way the game runs one: Init at the prerace, the
    countdown, the start, then every racing car counted each step and the
    field sorted."""
    out = []
    out += s_boundaries(rnd)
    out.append("S len %s" % fb(rnd.uniform(800.0, 9000.0)))
    w, racing = s_world(rnd)
    while racing < 2:
        w, racing = s_world(rnd)
    out += w
    ratio = []
    for i in range(NCAR):
        out += s_car(rnd, i, player=1 if i == 0 else 0)
        ratio.append(rnd.uniform(0.95, 1.0) if rnd.random() < 0.7
                     else rnd.random())
        out.append("CR %d %s" % (i, fb(ratio[i])))
    out.append("S timer 0")
    out.append("RS n 0")
    out.append("I 2")
    timer = frames = 0
    for stage in (3, 4):
        timer += rnd.randrange(4000, 12000)
        frames += rnd.randrange(60, 200)
        out.append("S timer %d" % timer)
        out.append("S frames %d" % frames)
        out.append("G %d" % stage)
    rt = 0
    for step in range(steps):
        out += s_lap_globals(rnd)
        timer += 67
        rt += 67
        out.append("S timer %d" % timer)
        out.append("RS rt %d" % rt)
        out.append("S elapsed %s" % fb(1.0 / 60))
        for k in range(racing):
            r = rnd.random()
            if r < 0.05:
                ratio[k] -= rnd.uniform(0.0, 0.02)
            else:
                ratio[k] += rnd.uniform(0.0, 0.03)
            ratio[k] %= 1.0
            if rnd.random() < 0.1:
                out.append(s_numbers(rnd, k).rsplit(" ", 2)[0]
                           + " %s %s" % (fb(ratio[k]), fb(150.0)))
            out.append("CR %d %s" % (k, fb(ratio[k])))
            out.append("U %d" % k)
        if rnd.random() < 0.3:
            out.append("O")
    return out


EDGE_WANTS = (1000.0, 1000.0001, 999.99994, 1500.0, 1e6, -5.0, -0.0, 0.0,
              60.0)
EDGE_FWDS = (2000.0, -2000.0, 1000.0, 1500.0, 30.0)
EDGE_TOPS = (0.0, -0.0, -100.0, -10.0, 30.0, 500.0, 1000.0, 2000.0)


def s_edges(rnd):
    """The corners the random scenarios rarely reach: a car that sat on a
    boundary exactly, a start time of 0x7fffffff, the finish line crossed
    into a lap below 0 or into lap 10, desired speeds at, past and below
    the 0 .. 1000 window against every TopSpeed, and finished cars below
    their places in the sort."""
    out = ["S replay 0", "S rtype 1", "S p2p 0", "S len %s" % fb(3000.0),
           "S timer 40000", "S elapsed %s" % fb(1.0 / 60), "RS rt 8000",
           "RS nb 1", "RS fin 0"]
    for k in range(5):
        out.append("RS bd%d %s" % (k, fb(50.0)))
    out += ["CA 0 1 0 3 0",
            "CF 0 4 %s %s %s %s %s" % (fb(30.0), fb(1.0), fb(1234.5),
                                       fb(0.49), fb(1e9)),
            "DV 0 0 0 0 0 %s" % fb(60.0),
            "RI 0 0"]

    # Sitting on the boundary: d0 is 0, which is neither side.
    for b in (50.0, 0.0, 25.0, 99.0, 100.0, 5.0):
        for d in (0.0, 0.5, 10.0, 24.0, -0.5, -10.0, 30.0):
            out.append("RF 0 prev %s" % fb(b))
            out.append("K 0 %s %s" % (fb(b + d), fb(b)))

    def cross(lap, high, bct0):
        # Over boundary 0, the finish line, at 49 -> 51 percent.
        return ["RF 0 lap %d" % lap, "RF 0 high %d" % high,
                "RF 0 bct0 %d" % bct0, "RF 0 prev %s" % fb(49.0),
                "CR 0 %s" % fb(0.51), "U 0"]

    for bct0 in (0x7fffffff, 0, 1000, 0x7ffffffe, 0x80000000):
        out += cross(-1, -1, bct0)
    for lap in (-3, -2, -1, 8, 9, 10, 11):
        out += cross(lap, -100, 1000)

    # TopSpeed, for a driver and for a player.
    for case in range(160):
        player = 1 if case % 4 == 3 else 0
        out.append("CA 0 1 %d 3 0" % player)
        out.append("CF 0 %d %s %s %s %s %s" % (
            rnd.choice((3, 4)), fb(rnd.choice(EDGE_FWDS)),
            fb(rnd.choice((1.0, 1.0, 0.5))), fb(1234.5), fb(0.51),
            fb(rnd.choice((1e9, 1e9, 5000.0, 2237.0)))))
        out.append("DV 0 0 0 0 0 %s" % fb(rnd.choice(EDGE_WANTS)))
        out.append("RF 0 top %s" % fb(rnd.choice(EDGE_TOPS)))
        out.append("U 0")

    # The sort with the finished cars anywhere in the order, below their
    # places too, which s_sort's (finished first) never puts them. The
    # orders stay distinct and within 1 .. n, or the sort would not end.
    for case in range(60):
        n = rnd.choice((2, 3, 5, 8, 8))
        perm = list(range(8))
        rnd.shuffle(perm)
        out.append("RS n %d" % n)
        for i in range(8):
            out.append("RP %d %d" % (i, perm[i]))
        nfin = rnd.randrange(1, n + 1)
        at = dict(zip(rnd.sample(range(n), nfin),
                      rnd.sample(range(1, n + 1), nfin)))
        for i in range(8):
            k = perm[i]
            out.append("RF %d fo %d" % (k, at.get(i, 0)))
            out.append("RF %d fle %s" % (k, fb(rnd.uniform(-1.0, 4.0))))
        out.append("O")
    return out


def script():
    rnd = random.Random(0x8d2b6e41)
    sc = [s_round(rnd), s_check(rnd)]
    for n in (60, 120, 120, 200, 200, 300):
        sc.append(s_laps(rnd, n))
    sc += [s_stage(rnd), s_init(rnd), s_sort(rnd)]
    for n in (150, 250):
        sc.append(s_race(rnd, n))
    sc.append(s_edges(rnd))
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
        for a, fn in ((B_MALLOC, self.s_malloc),
                      (SET_MOVEMENT, self.s_movement),
                      (DISABLE_SLS, self.s_disable),
                      (RACE_LEAVING, self.s_leaving),
                      (UPDATE_POS, self.s_update),
                      (B_MEMSET, self.s_memset),
                      (FN_DESIRED, self.s_desired)):
            e.stub(a, fn)
        # TrackPathCoordinate's destructor runs: with flag 2 it returns.
        assert e.u32(TPC_DTOR) == 0x30a50001

        self.names = {0: "null", RACE: "R", TATT: "T", FDB: "fdb"}
        for k in range(8):
            self.names[rc_at(k)] = "rc%d" % k
        for i in range(NCAR):
            self.names[car_at(i)] = "c%d" % i
            self.names[drv_at(i)] = "d%d" % i
            self.names[PLAYERS + 16 * i] = "p%d" % i

    def emit(self, s):
        self.out.append(s)

    def name(self, a):
        return self.names.get(a & M32, "?")

    def arg(self, i):
        return self.e.reg[(4, 5, 6, 7, 8, 9, 10, 11)[i]] & M32

    def w(self, a):
        return self.e.u32(a)

    def fill(self, a, n, byte=PATTERN):
        self.e.write(a, bytes([byte]) * n)

    def cstr(self, a):
        b = bytearray()
        while self.e.mem[a]:
            b.append(self.e.mem[a])
            a += 1
        return b.decode("latin-1")

    def put(self, a, width, v):
        if width == 1:
            self.e.mem[a] = v & 0xff
        elif width == 2:
            self.e.write(a, struct.pack("<H", v & 0xffff))
        else:
            self.e.put32(a, v & M32)

    # ---- the stubs -------------------------------------------------------

    def s_malloc(self, e):
        self.emit("  malloc %d %s %d %d"
                  % (s32(self.arg(0)), self.cstr(self.arg(1)),
                     s32(self.arg(2)), s32(self.arg(3))))
        return TATT

    def s_movement(self, e):
        self.emit("  move %s %d" % (self.name(self.arg(0)), s32(self.arg(1))))

    def s_disable(self, e):
        self.emit("  dsls %s" % self.name(self.arg(0)))

    def s_leaving(self, e):
        self.emit("  leaving %s %s" % (self.name(self.arg(0)),
                                       self.name(self.arg(1))))

    def s_update(self, e):
        c, pos = self.arg(0), self.arg(1)
        x, y = self.w(pos), self.w(pos + 4)
        if self.umode:
            r = rcc.unitf(x, y, 3, self.seed)
        else:
            r = rcc.mixf(x, y, 3, self.seed)
        self.emit("  upd %s %s -> %s" % (fx(x), fx(y), fx(r)))
        ln = fbits_to(self.w(TPM))
        ratio = f_to_bits(fbits_to(r) / ln) if ln != 0.0 else 0
        e.put32(c, x)
        e.put32(c + 4, y)
        e.put32(c + 16, ratio)
        e.put32(c + 20, r)

    def s_memset(self, e):
        a, v, n = self.arg(0), self.arg(1), s32(self.arg(2))
        e.mem[a:a + n] = bytes([v & 0xff]) * n
        return a

    def s_desired(self, e):
        this = self.arg(0)
        who, want = "?", 0
        for i in range(NCAR):
            if this == (drv_at(i) + self.delta) & M32:
                who, want = "d%d" % i, self.want[i]
        self.emit("  want %s -> %s" % (who, fx(want)))
        e.fpr[0] = want

    # ---- the state -------------------------------------------------------

    def set_vtable(self):
        e = self.e
        e.write(VTAB, bytes(168))
        e.write(VTAB + VT_DESIRED, struct.pack("<h", self.delta))
        e.put32(VTAB + VT_DESIRED + 4, FN_DESIRED)

    def reset(self):
        e = self.e
        self.fill(RACE, RACE_BYTES)
        self.put(RACE + 24, 4, 0)
        self.put(RACE + 1616, 2, 0)
        self.put(RACE + 1618, 1, 0)
        self.put(RACE + 1619, 1, 0)
        e.write(RACE + 1620, bytes(20))
        self.fill(TATT, TATT_BYTES)
        e.write(WORLD, bytes(0x100))
        for i in range(NCAR):
            e.put32(WORLD + 44 + 4 * i, car_at(i))
        e.write(REPLAY, bytes(64))
        e.put32(G_RACE, RACE)
        e.put32(G_WORLD, WORLD)
        e.put32(G_REPLAY, REPLAY)
        e.put32(G_TIMER, 0)
        e.put32(G_FRAMES, 0)
        e.put32(G_ELAPSED, 0)
        e.put32(RP_RTYPE, 0)
        e.put32(RP_P2P, 0)
        e.put32(RP_NPC, 1)
        e.put32(RP_COP, 0)
        e.put32(TPM, f_to_bits(1.0))
        self.delta = 0
        self.set_vtable()
        self.want = [0] * NCAR
        for i in range(NCAR):
            c, t, d = car_at(i), cti_at(i), drv_at(i)
            self.fill(c, 0x1000)
            self.fill(t, 0x400)
            self.fill(d, 0x400)
            e.put32(c + CAR_CTI, t)
            e.put32(c + CAR_DRV, d)
            e.put32(c + CAR_PLAYER, 0)
            e.put32(c + CAR_MODE, 0)
            e.mem[c + CAR_REND] = 0
            for off in (CAR_WHEELS, CAR_SPEED, CAR_DIST, CAR_RATIO):
                e.put32(c + off, 0)
            e.put32(c + CAR_BOOST, f_to_bits(1.0))
            e.mem[t + CTI_CLASS] = 0
            e.put32(t + CTI_SL, 0)
            e.put32(d + DRV_VT, VTAB)
            for off in (DRV_THR, DRV_BRK, DRV_EB, DRV_SLS):
                e.put32(d + off, 0)
        for r in range(NROUTE):
            e.write(rcc.route_at(r), bytes(rcc.ROUTE_POINTS))
        self.link_routes([])
        self.seed = 0
        self.umode = 1

    def link_routes(self, order):
        e = self.e
        ring = [rcc.ROUTE_MGR] + [rcc.route_at(r) for r in order]
        for i, a in enumerate(ring):
            e.put32(a, ring[(i + 1) % len(ring)])
            e.put32(a + 4, ring[i - 1])
        e.put32(rcc.ROUTE_MGR + 8, rcc.ROUTE_MGR + 8)
        e.put32(rcc.ROUTE_MGR + 12, rcc.ROUTE_MGR + 8)

    def set_global(self, f, v):
        e = self.e
        regs = {"timer": G_TIMER, "frames": G_FRAMES, "elapsed": G_ELAPSED,
                "replay": REPLAY, "rtype": RP_RTYPE, "p2p": RP_P2P,
                "npc": RP_NPC, "cop": RP_COP, "len": TPM}
        if f in regs:
            e.put32(regs[f], v & M32)
        elif f == "delta":
            self.delta = s32(v)
            self.set_vtable()
        elif f == "seed":
            self.seed = v & M32
        elif f == "umode":
            self.umode = v
        else:
            raise SystemExit("bad global %s" % f)

    # ---- the dumps -------------------------------------------------------

    def dump_head(self):
        w = self.w
        r = RACE
        self.emit("  race st %d go %d cd %d t %08x n %d tatt %s"
                  % (s32(w(r)), s32(w(r + 4)), s32(w(r + 8)), w(r + 12),
                     s32(w(r + 24)), self.name(w(r + 1712))))
        self.emit("  cars" + "".join(" " + self.name(w(r + 1572 + 4 * i))
                                     for i in range(8)))

    def dump_rc(self, k):
        w, m = self.w, self.e.mem
        c = rc_at(k)

        def h16(o):
            return sh(m[c + o] | (m[c + o + 1] << 8))
        self.emit("  rc%d %s %d %d %s %d %d %s %s %s %s"
                  % (k, self.name(w(c)), h16(4), h16(6),
                     " ".join("%d" % sb(m[c + o]) for o in range(8, 16)),
                     h16(16), h16(18), fx(w(c + 20)), fx(w(c + 24)),
                     fx(w(c + 28)), fx(w(c + 32))))
        self.emit("  rc%d t %s | %s | %x %s %s"
                  % (k, " ".join("%x" % w(c + 36 + 4 * j)
                                 for j in range(25)),
                     " ".join("%x" % w(c + 136 + 4 * j) for j in range(11)),
                     w(c + 180), fx(w(c + 184)), fx(w(c + 188))))

    def dump_cars(self):
        w, m = self.w, self.e.mem
        for i in range(NCAR):
            c, d = car_at(i), drv_at(i)
            self.emit("  c%d rc %s rend %d thr %s brk %s eb %s sls %d"
                      % (i, self.name(w(c + CAR_RC)), sb(m[c + CAR_REND]),
                         fx(w(d + DRV_THR)), fx(w(d + DRV_BRK)),
                         fx(w(d + DRV_EB)), s32(w(d + DRV_SLS))))

    def dump_race(self):
        self.dump_head()
        for k in range(8):
            self.dump_rc(k)
        self.dump_cars()

    def dump_tatt(self):
        w = self.w
        self.emit("  tatt total %s" % fx(w(TATT)))
        for i in range(0, 256, 8):
            self.emit("  t%03d" % i + "".join(
                " %s:%s" % (fx(w(TATT + 4 + 8 * k)), fx(w(TATT + 8 + 8 * k)))
                for k in range(i, i + 8)))

    # ---- the ops ---------------------------------------------------------

    def call(self, fn, *args, **kw):
        e = self.e
        sp = e.reg[29] & M32
        e.write(sp - 0x4000, bytes(0x4000))
        for i, v in kw.get("f", {}).items():
            e.fpr[i] = v & M32
        return e.call(fn, *args, limit=4000000)

    def point(self, r, k, n):
        e = self.e
        p = rcc.point_at(r, k)
        for i in range(4):
            e.put32(p + (0, 4, 12, 16)[i], n[i] & M32)
        for line in range(rcc.NLINE):
            e.write(p + 48 + 2 * line,
                    struct.pack("<H", (n[4] + 37 * line) & 0xffff))
            e.mem[p + 90 + line] = (n[5] + 13 * line) & 0xff

    def op(self, t):
        e = self.e
        c = t[0]
        if c == "S":
            self.set_global(t[1], int(t[2], 0))
            return
        if c == "RS":
            off, width = RACE_FIELDS[t[1]]
            self.put(RACE + off, width, int(t[2], 0))
            return
        if c == "RF":
            off, width = RC_FIELDS[t[2]]
            self.put(rc_at(int(t[1])) + off, width, int(t[3], 0))
            return
        n = [int(x, 0) for x in t[1:]]
        if c == "W":
            for i, off in enumerate((28, 32, 36, 40)):
                e.put32(WORLD + off, n[i] & M32)
        elif c == "WT":
            e.put32(WORLD + 44 + 4 * n[0], car_at(n[1]))
        elif c == "CA":
            car = car_at(n[0])
            e.put32(car + CAR_MODE, n[1] & M32)
            e.put32(car + CAR_PLAYER, PLAYERS + 16 * n[0] if n[2] else 0)
            e.mem[cti_at(n[0]) + CTI_CLASS] = n[3] & 0xff
            e.mem[car + CAR_REND] = n[4] & 0xff
        elif c == "CF":
            car = car_at(n[0])
            e.put32(car + CAR_WHEELS, n[1] & M32)
            e.put32(car + CAR_SPEED, n[2])
            e.put32(car + CAR_BOOST, n[3])
            e.put32(car + CAR_DIST, n[4])
            e.put32(car + CAR_RATIO, n[5])
            e.put32(cti_at(n[0]) + CTI_SL, n[6])
        elif c == "CR":
            e.put32(car_at(n[0]) + CAR_RATIO, n[1])
        elif c == "DV":
            d = drv_at(n[0])
            e.put32(d + DRV_THR, n[1])
            e.put32(d + DRV_BRK, n[2])
            e.put32(d + DRV_EB, n[3])
            e.put32(d + DRV_SLS, n[4] & M32)
            self.want[n[0]] = n[5]
        elif c == "RP":
            e.put32(RACE + 1572 + 4 * n[0], rc_at(n[1]))
        elif c == "RI":
            self.call(RC_INIT, rc_at(n[0]), car_at(n[1]))
            self.dump_rc(n[0])
            self.emit("  c%d rc %s" % (n[1], self.name(self.w(car_at(n[1])
                                                            + CAR_RC))))
        elif c == "F":
            self.call(FAKE, rc_at(n[0]))
            self.dump_rc(n[0])
        elif c == "K":
            self.fill(INFO, 12)
            v = self.call(CHECK, rc_at(n[0]), INFO, f={12: n[1], 13: n[2]})
            self.emit("  -> %d %d %d %x" % (v, s32(self.w(INFO)),
                                            s32(self.w(INFO + 4)),
                                            self.w(INFO + 8)))
        elif c == "U":
            self.call(UPDATE, rc_at(n[0]))
            self.dump_rc(n[0])
        elif c == "P":
            v = self.call(GET_PLAYER, rc_at(n[0]))
            self.emit("  -> %s" % self.name(v))
        elif c == "I":
            self.call(RACE_INIT, RACE, n[0] & M32)
            self.dump_race()
            self.dump_tatt()
        elif c == "AC":
            self.call(ADD_CARS, RACE)
            self.dump_race()
        elif c == "A":
            self.call(ADD_CAR, RACE, car_at(n[0]))
            self.dump_race()
        elif c == "G":
            self.call(SET_STAGE, RACE, n[0] & M32)
            self.dump_race()
        elif c == "O":
            self.call(SORT, RACE)
            self.dump_head()
            for k in range(8):
                self.dump_rc(k)
        elif c == "TR":
            e.put32(TIMER, n[0] & M32)
            self.call(ROUND, TIMER, f={12: n[1]})
            self.emit("  -> %08x" % self.w(TIMER))
        elif c == "TS":
            e.put32(TIMER, n[0] & M32)
            self.call(ROUND_SECONDS, TIMER, f={12: n[1]})
            self.emit("  -> %s" % fx(e.fpr[0]))
        elif c == "RTP":
            e.put32(rcc.route_at(n[0]) + 16, n[1] & M32)
        elif c == "RTL":
            e.put32(rcc.route_at(n[0]) + 40 + 48 * n[1], n[2] & M32)
        elif c == "RTT":
            self.point(n[0], n[1], n[2:])
        elif c == "RTQ":
            self.link_routes(n)
        else:
            raise SystemExit("bad op %r" % (t,))

    def run(self, scenarios):
        for i, sc in enumerate(scenarios):
            self.emit("B %d" % i)
            self.reset()
            for ln in sc:
                self.emit("> " + ln[:40])
                self.op(ln.split())
        return self.out


# ================================================================ the build


def build_harness(tmp, name="racerun_test"):
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
    # ---- RacingCar::Init
    M("init_no_link", RRC, "    car->pRacingCar = rc;" + NL, ""),
    M("init_position", RRC,
      "    rc->RacePosition = 0;", "    rc->RacePosition = 1;"),
    M("init_prev_position", RRC,
      "    rc->PreviousRacePosition = 0;", "    rc->PreviousRacePosition = 1;"),
    M("init_finishing", RRC,
      "    rc->FinishingOrder = 0;", "    rc->FinishingOrder = 1;"),
    M("init_finished_exact", RRC,
      "    rc->FinishedLapNumberExact = 0.0f;",
      "    rc->FinishedLapNumberExact = 1.0f;"),
    M("init_reason", RRC,
      "    rc->FinishReason = 0;", "    rc->FinishReason = 1;"),
    M("init_prev_dist_scale", RRC,
      """        car->TheTrackPathCoordinate.RatioAroundTrack * 100.0f;
    for""",
      """        car->TheTrackPathCoordinate.RatioAroundTrack * 10.0f;
    for"""),
    M("init_bct", RRC,
      "        rc->BoundaryCrossingTimes[i].PackedTime = 0;",
      "        rc->BoundaryCrossingTimes[i].PackedTime = 1;"),
    M("init_running", RRC,
      "        rc->RunningTimes[i].PackedTime = 0;",
      "        rc->RunningTimes[i].PackedTime = 1;"),
    M("init_prev_running", RRC,
      "        rc->PreviousRunningTimes[i].PackedTime = 0;",
      "        rc->PreviousRunningTimes[i].PackedTime = 1;"),
    M("init_best", RRC,
      "        rc->BestRunningTimes[i].PackedTime = TIMER_UNSET;",
      "        rc->BestRunningTimes[i].PackedTime = 0;"),
    M("init_prev_best", RRC,
      "        rc->PreviousBestRunningTimes[i].PackedTime = TIMER_UNSET;",
      "        rc->PreviousBestRunningTimes[i].PackedTime = 0;"),
    M("init_four_boundaries", RRC,
      """    for (i = 0; i < RACE_MAX_BOUNDARIES; i++) {
        rc->BoundaryCrossingTimes""",
      """    for (i = 0; i < RACE_MAX_BOUNDARIES - 1; i++) {
        rc->BoundaryCrossingTimes"""),
    M("init_lap_times_short", RRC,
      """    for (i = 0; i < RACE_MAX_LAP_TIMES; i++)
        rc->LapTimes""",
      """    for (i = 0; i < RACE_MAX_LAP_TIMES - 1; i++)
        rc->LapTimes"""),
    M("init_race_time", RRC,
      "    rc->RaceTime.PackedTime = 0;", "    rc->RaceTime.PackedTime = 1;"),
    M("init_top", RRC,
      "    rc->TopSpeed = 0.0f;", "    rc->TopSpeed = 1.0f;"),
    M("init_average", RRC,
      "    rc->AverageSpeed = 0.0f;", "    rc->AverageSpeed = 1.0f;"),
    M("init_laps_done", RRC,
      "    rc->NumLapsCompleted = 0;", "    rc->NumLapsCompleted = -1;"),
    M("init_lap", RRC,
      "    rc->CurrentLapNumber = -1;", "    rc->CurrentLapNumber = 0;"),
    M("init_highest", RRC,
      "    rc->HighestBoundaryRegion = -1;",
      "    rc->HighestBoundaryRegion = 0;"),
    M("init_current_region", RRC,
      "    rc->CurrentBoundaryRegion = -1;",
      "    rc->CurrentBoundaryRegion = 0;"),
    M("init_no_update", RRC,
      """    racingcar_update_lap_counts(rc);
    rc->NumLapsLed = 0;""",
      """    rc->NumLapsLed = 0;"""),
    M("init_laps_led", RRC,
      "    rc->NumLapsLed = 0;", "    rc->NumLapsLed = 1;"),

    # ---- FakeStartlineCrossing
    M("fake_no_stamp", RRC,
      "rc->BoundaryCrossingTimes[0].PackedTime = (uint32_t)WorldTimer;",
      "rc->BoundaryCrossingTimes[0].PackedTime = 0;"),
    M("fake_no_round", RRC,
      "    timer_round(&rc->BoundaryCrossingTimes[0], 0.01f);" + NL, ""),
    M("fake_round_tenth", RRC,
      "    timer_round(&rc->BoundaryCrossingTimes[0], 0.01f);",
      "    timer_round(&rc->BoundaryCrossingTimes[0], 0.1f);"),
    M("fake_highest", RRC,
      """    rc->HighestBoundaryRegion = 0;
    if (RaceParametersPoint2Point""",
      """    rc->HighestBoundaryRegion = -1;
    if (RaceParametersPoint2Point"""),
    M("fake_p2p_always", RRC,
      "    if (RaceParametersPoint2Point != 0) {", "    if (1) {"),
    M("fake_p2p_never", RRC,
      "    if (RaceParametersPoint2Point != 0) {", "    if (0) {"),
    M("fake_p2p_no_region", RRC,
      """        rc->CurrentBoundaryRegion = 0;
        rc->CurrentLapNumber = 0;""",
      """        rc->CurrentLapNumber = 0;"""),
    M("fake_p2p_no_lap", RRC,
      """        rc->CurrentBoundaryRegion = 0;
        rc->CurrentLapNumber = 0;""",
      """        rc->CurrentBoundaryRegion = 0;"""),

    # ---- CheckBoundaryCrossing
    M("check_args_swapped", RRC,
      """    float d1 = trackpath_compare_percent_distances(&TheTrackPathManager,
                                                   pct, b);""",
      """    float d1 = trackpath_compare_percent_distances(&TheTrackPathManager,
                                                   b, pct);"""),
    M("check_d0_from_pct", RRC,
      "&TheTrackPathManager, rc->PreviousDistanceAroundTrack, b);",
      "&TheTrackPathManager, pct, b);"),
    M("check_no_zero_forwards", RRC,
      """    info->CrossedForwards = 0;
    info->CrossedBackwards = 0;
    info->TimeSinceCrossing""",
      """    info->CrossedBackwards = 0;
    info->TimeSinceCrossing"""),
    M("check_no_zero_backwards", RRC,
      """    info->CrossedForwards = 0;
    info->CrossedBackwards = 0;
    info->TimeSinceCrossing""",
      """    info->CrossedForwards = 0;
    info->TimeSinceCrossing"""),
    M("check_no_zero_time", RRC,
      """    info->TimeSinceCrossing.PackedTime = 0;
    past""",
      """    past"""),
    M("check_no_length", RRC,
      "past = d1 * TheTrackPathManager.TrackLength * 0.01f;",
      "past = d1 * 0.01f;"),
    M("check_past_d0", RRC,
      "past = d1 * TheTrackPathManager", "past = d0 * TheTrackPathManager"),
    M("check_fence_le", RRC,
      "if (25.0f < fabsf(d1))", "if (25.0f <= fabsf(d1))"),
    M("check_fence_d0", RRC,
      "if (25.0f < fabsf(d1))", "if (25.0f < fabsf(d0))"),
    M("check_fence_20", RRC,
      "if (25.0f < fabsf(d1))", "if (20.0f < fabsf(d1))"),
    M("check_fence_signed", RRC,
      "if (25.0f < fabsf(d1))", "if (25.0f < d1)"),
    M("check_fwd_strict", RRC,
      "if (d0 < 0.0f && 0.0f <= d1) {", "if (d0 < 0.0f && 0.0f < d1) {"),
    M("check_fwd_d0_le", RRC,
      "if (d0 < 0.0f && 0.0f <= d1) {", "if (d0 <= 0.0f && 0.0f <= d1) {"),
    M("check_bwd_strict", RRC,
      "} else if (0.0f <= d0 && d1 < 0.0f) {",
      "} else if (0.0f < d0 && d1 < 0.0f) {"),
    M("check_bwd_le", RRC,
      "} else if (0.0f <= d0 && d1 < 0.0f) {",
      "} else if (0.0f <= d0 && d1 <= 0.0f) {"),
    M("check_no_backwards", RRC,
      """        info->CrossedForwards = 0;
        info->CrossedBackwards = 1;""",
      """        info->CrossedForwards = 0;
        return 0;"""),
    M("check_speed_floor_0", RRC,
      "    if (1.0f < speed)", "    if (0.0f < speed)"),
    M("check_speed_floor_le", RRC,
      "    if (1.0f < speed)", "    if (1.0f <= speed)"),
    M("check_ticks_no_half", RRC,
      "ago * 4000.0f + 0.5f", "ago * 4000.0f"),
    M("check_ticks_scale", RRC,
      "ago * 4000.0f + 0.5f", "ago * 1000.0f + 0.5f"),

    # ---- UpdateLapCounts: the boundaries
    M("ulc_no_clear_finish", RRC,
      """    rc->CrossedFinishLine = 0;
    rc->CompletedNewLap = 0;""",
      """    rc->CompletedNewLap = 0;"""),
    M("ulc_no_clear_new", RRC,
      """    rc->CompletedNewLap = 0;
    pct""",
      """    pct"""),
    M("ulc_pct_scale", RRC,
      "    pct = rc->pCar->TheTrackPathCoordinate.RatioAroundTrack * 100.0f;",
      "    pct = rc->pCar->TheTrackPathCoordinate.RatioAroundTrack * 10.0f;"),
    M("ulc_boundaries_short", RRC,
      "    for (i = 0; i < pCurrentRace->NumBoundaries; i++) {",
      "    for (i = 0; i < pCurrentRace->NumBoundaries - 1; i++) {"),
    M("ulc_boundary_first", RRC,
      "rc, &info, pct, pCurrentRace->BoundaryDistances[i]))",
      "rc, &info, pct, pCurrentRace->BoundaryDistances[0]))"),
    M("ulc_bwd_no_lap", RRC,
      "                rc->CurrentLapNumber = (int8_t)(rc->CurrentLapNumber - 1);"
      + NL, ""),
    M("ulc_bwd_any_boundary", RRC,
      """            if (i == pCurrentRace->FinishLineBoundaryNumber)
                rc->CurrentLapNumber = (int8_t)(rc->CurrentLapNumber - 1);""",
      """            rc->CurrentLapNumber = (int8_t)(rc->CurrentLapNumber - 1);"""),
    M("ulc_fwd_any_boundary", RRC,
      """        if (i == pCurrentRace->FinishLineBoundaryNumber) {
            int8_t lap""",
      """        if (1) {
            int8_t lap"""),
    M("ulc_laps_le", RRC,
      "            if (rc->NumLapsCompleted < lap) {",
      "            if (rc->NumLapsCompleted <= lap) {"),
    M("ulc_no_crossed_finish", RRC,
      "                rc->CrossedFinishLine = 1;" + NL, ""),
    M("ulc_no_laps_done", RRC,
      "                rc->NumLapsCompleted = lap;" + NL, ""),
    M("ulc_region_stride", RRC,
      "rc->CurrentLapNumber * 5 + i", "rc->CurrentLapNumber * 4 + i"),
    M("ulc_highest_le", RRC,
      "        if (!(rc->HighestBoundaryRegion < region))",
      "        if (!(rc->HighestBoundaryRegion <= region))"),
    M("ulc_no_completed", RRC,
      "        rc->CompletedNewLap = 1;" + NL, ""),
    M("ulc_no_highest", RRC,
      "        rc->HighestBoundaryRegion = region;" + NL, ""),
    M("ulc_time_plus", RRC,
      "(uint32_t)WorldTimer - info.TimeSinceCrossing.PackedTime",
      "(uint32_t)WorldTimer + info.TimeSinceCrossing.PackedTime"),
    M("ulc_no_round", RRC,
      """        timer_round(&t, 0.01f);

        if (!replaying()) {""",
      """
        if (!replaying()) {"""),
    M("ulc_round_tenth", RRC,
      """        timer_round(&t, 0.01f);

        if (!replaying()) {""",
      """        timer_round(&t, 0.1f);

        if (!replaying()) {"""),
    M("ulc_replay_inverted", RRC,
      """        if (!replaying()) {
            if (timer_is_set""",
      """        if (replaying()) {
            if (timer_is_set"""),
    M("set_zero_only", RRC,
      "    return t->PackedTime != 0 && t->PackedTime != TIMER_UNSET;",
      "    return t->PackedTime != 0;"),
    M("set_unset_only", RRC,
      "    return t->PackedTime != 0 && t->PackedTime != TIMER_UNSET;",
      "    return t->PackedTime != TIMER_UNSET;"),
    M("ulc_no_prev_running", RRC,
      "                rc->PreviousRunningTimes[i] = rc->RunningTimes[i];" + NL,
      ""),
    M("ulc_running_from_i", RRC,
      """                    t.PackedTime - rc->BoundaryCrossingTimes[0].PackedTime;
                rc->PreviousBest""",
      """                    t.PackedTime - rc->BoundaryCrossingTimes[i].PackedTime;
                rc->PreviousBest"""),
    M("ulc_no_prev_best", RRC,
      "                rc->PreviousBestRunningTimes[i] = rc->BestRunningTimes[i];"
      + NL, ""),
    M("ulc_best_unsigned", RRC,
      """                if ((int32_t)rc->RunningTimes[i].PackedTime
                    < (int32_t)rc->BestRunningTimes[i].PackedTime)""",
      """                if (rc->RunningTimes[i].PackedTime
                    < rc->BestRunningTimes[i].PackedTime)"""),
    M("ulc_best_always", RRC,
      """                if ((int32_t)rc->RunningTimes[i].PackedTime
                    < (int32_t)rc->BestRunningTimes[i].PackedTime)""",
      """                if (1)"""),
    M("ulc_lap_any_boundary", RRC,
      """                if (i == pCurrentRace->FinishLineBoundaryNumber
                    && (uint8_t)rc->CurrentLapNumber < RACE_MAX_LAP_TIMES)""",
      """                if ((uint8_t)rc->CurrentLapNumber < RACE_MAX_LAP_TIMES)"""),
    M("ulc_lap_signed", RRC,
      "&& (uint8_t)rc->CurrentLapNumber < RACE_MAX_LAP_TIMES)",
      "&& rc->CurrentLapNumber < RACE_MAX_LAP_TIMES)"),
    M("ulc_lap_ten", RRC,
      "&& (uint8_t)rc->CurrentLapNumber < RACE_MAX_LAP_TIMES)",
      "&& (uint8_t)rc->CurrentLapNumber < RACE_MAX_LAP_TIMES - 1)"),
    M("ulc_lap_running_best", RRC,
      "rc->LapTimes[rc->CurrentLapNumber] = rc->RunningTimes[i];",
      "rc->LapTimes[rc->CurrentLapNumber] = rc->BestRunningTimes[i];"),
    M("ulc_no_bct", RRC,
      """            rc->BoundaryCrossingTimes[i] = t;
        } else if""",
      """        } else if"""),
    M("ulc_replay_any_type", RRC,
      "} else if (RaceParametersRaceType == RACE_TYPE_TIME_TRIAL",
      "} else if (RaceParametersRaceType != RACE_TYPE_NONE"),
    M("ulc_replay_any_boundary", RRC,
      """                   && i == pCurrentRace->FinishLineBoundaryNumber) {
            if (timer_is_set""",
      """                   && 1) {
            if (timer_is_set"""),
    M("ulc_replay_no_running", RRC,
      """            if (timer_is_set(&rc->BoundaryCrossingTimes[0]))
                rc->RunningTimes[i].PackedTime =
                    t.PackedTime - rc->BoundaryCrossingTimes[0].PackedTime;
            rc->BoundaryCrossingTimes[i] = t;
        }""",
      """            rc->BoundaryCrossingTimes[i] = t;
        }"""),
    M("ulc_replay_no_bct", RRC,
      """            rc->BoundaryCrossingTimes[i] = t;
        }
    }""",
      """        }
    }"""),

    # ---- UpdateLapCounts: the speeds and the exact lap
    M("ulc_speeds_in_replay", RRC,
      """    if (!replaying()) {
        float rt;""",
      """    if (1) {
        float rt;"""),
    M("ulc_wheels_2", RRC,
      "nWheelsTouchingGround >= 3", "nWheelsTouchingGround >= 2"),
    M("ulc_wheels_4", RRC,
      "nWheelsTouchingGround >= 3", "nWheelsTouchingGround >= 4"),
    M("ulc_player_inverted", RRC,
      "if (racingcar_get_player(rc) != NULL) {",
      "if (racingcar_get_player(rc) == NULL) {"),
    M("ulc_player_abs", RRC,
      "s = max_s(top, rc->pCar->State.ForwardSpeed);",
      "s = max_s(top, fabsf(rc->pCar->State.ForwardSpeed));"),
    M("ulc_boost_unfloored", RRC,
      "want = want / max_s(1.0f, car->State.BoostFactor);",
      "want = want / car->State.BoostFactor;"),
    M("ulc_boost_ignored", RRC,
      "want = want / max_s(1.0f, car->State.BoostFactor);", "(void)0;"),
    M("ulc_speed_signed", RRC,
      "want = min_s(want, fabsf(car->State.ForwardSpeed));",
      "want = min_s(want, car->State.ForwardSpeed);"),
    M("ulc_no_speed_cap", RRC,
      "want = min_s(want, fabsf(car->State.ForwardSpeed));", "(void)0;"),
    M("ulc_no_limiter", RRC,
      """                want = min_s(want, car->pCarTypeInfo->Control.SpeedLimiter
                                   * RACE_MPH_TO_MPS);""",
      """                (void)0;"""),
    M("ulc_limiter_kph", RRC,
      "* RACE_MPH_TO_MPS);", "* 0.2777778f);"),
    M("ulc_negative_kept", RRC,
      """                if (s < 0.0f)
                    s = top;
                else if""",
      """                if (0)
                    s = top;
                else if"""),
    M("ulc_cap_ge", RRC,
      "                else if (1000.0f < s)", "                else if (1000.0f <= s)"),
    M("ulc_no_cap", RRC,
      "                else if (1000.0f < s)", "                else if (0)"),
    M("ulc_top_always", RRC,
      "            if (!(s == top))", "            if (1)"),
    M("ulc_average_no_guard", RRC,
      "        if (0.0f < rt)", "        if (rt != 0.0f)"),
    M("ulc_average_unsigned", RRC,
      "rt = (float)(int32_t)pCurrentRace->RaceTime.PackedTime * 0.00025f;",
      "rt = (float)pCurrentRace->RaceTime.PackedTime * 0.00025f;"),
    M("ulc_average_per_tick", RRC,
      "rt = (float)(int32_t)pCurrentRace->RaceTime.PackedTime * 0.00025f;",
      "rt = (float)(int32_t)pCurrentRace->RaceTime.PackedTime;"),
    M("ulc_average_own_time", RRC,
      "rt = (float)(int32_t)pCurrentRace->RaceTime.PackedTime * 0.00025f;",
      "rt = (float)(int32_t)rc->RaceTime.PackedTime * 0.00025f;"),
    M("ulc_exact_no_lap", RRC,
      """    rc->CurrentLapNumberExact = (float)rc->CurrentLapNumber
                              + race_get_lap_number_exact(pCurrentRace, pct);""",
      """    rc->CurrentLapNumberExact = race_get_lap_number_exact(pCurrentRace,
                                                          pct);"""),
    M("ulc_exact_prev", RRC,
      "+ race_get_lap_number_exact(pCurrentRace, pct);",
      "+ race_get_lap_number_exact(pCurrentRace,"
      " rc->PreviousDistanceAroundTrack);"),
    M("ulc_no_finished", RRC,
      "    rc->FinishedLapNumberExact = rc->CurrentLapNumberExact;" + NL, ""),
    M("ulc_rate_guard_le", RRC,
      "    if (0.0f < WorldTimeElapsed)", "    if (0.0f <= WorldTimeElapsed)"),
    M("ulc_rate_third", RRC,
      "rc->dCurrentLapNumberExact * 0.333f",
      "rc->dCurrentLapNumberExact * 0.334f"),
    M("ulc_rate_two_thirds", RRC,
      "/ WorldTimeElapsed * 0.667f", "/ WorldTimeElapsed * 0.666f"),
    M("ulc_rate_reversed", RRC,
      "(rc->CurrentLapNumberExact - old)", "(old - rc->CurrentLapNumberExact)"),
    M("ulc_rate_old_after", RRC,
      """    old = rc->CurrentLapNumberExact;
    rc->CurrentLapNumberExact = (float)rc->CurrentLapNumber
                              + race_get_lap_number_exact(pCurrentRace, pct);""",
      """    rc->CurrentLapNumberExact = (float)rc->CurrentLapNumber
                              + race_get_lap_number_exact(pCurrentRace, pct);
    old = rc->CurrentLapNumberExact;"""),
    M("ulc_no_prev", RRC,
      """    rc->PreviousDistanceAroundTrack = pct;
}""", "}"),

    # ---- GetPlayer
    M("player_always_null", RRC,
      """    if (rc->pCar == NULL)
        return NULL;
    return rc->pCar->pPlayer;""",
      """    (void)rc;
    return NULL;"""),

    # ---- Race::Init
    M("rinit_second_on_cop", RRC,
      "if (RaceParametersBeACop != 0 && RaceParametersNumPlayerCars == 2)",
      "if (RaceParametersBeACop != 0)"),
    M("rinit_second_on_two", RRC,
      "if (RaceParametersBeACop != 0 && RaceParametersNumPlayerCars == 2)",
      "if (RaceParametersNumPlayerCars == 2)"),
    M("rinit_second_never", RRC,
      "if (RaceParametersBeACop != 0 && RaceParametersNumPlayerCars == 2)",
      "if (0)"),
    M("rinit_no_stage", RRC,
      """    race_set_race_stage(r, stage);
    if (RaceParametersBeACop""",
      """    if (RaceParametersBeACop"""),
    M("rinit_stage_first", RRC,
      """    race_add_racing_cars(r);
    race_set_race_stage(r, stage);""",
      """    race_set_race_stage(r, stage);
    race_add_racing_cars(r);"""),
    M("rinit_class_next", RRC,
      "    car_class = car->pCarTypeInfo->CarClass;",
      "    car_class = car->pCarTypeInfo->CarClass + 1;"),
    M("rinit_pool", RRC,
      "\"TimeAroundTrackTable\", 0, 16),", "\"TimeAroundTrackTable\", 0, 0),"),
    M("rinit_no_store", RRC,
      "    r->pTimeAroundTrackTable = tatt_construct(", "    (void)tatt_construct("),

    # ---- AddRacingCars and AddRacingCar
    M("addcars_first_short", RRC,
      "    for (i = 0; i < pCurrentWorld->AICarPos; i++)",
      "    for (i = 0; i < pCurrentWorld->AICarPos - 1; i++)"),
    M("addcars_second_from_zero", RRC,
      "            r, pCurrentWorld->CarTable[pCurrentWorld->AICarPos + i]);",
      "            r, pCurrentWorld->CarTable[i]);"),
    M("addcars_second_to_cop", RRC,
      "i < pCurrentWorld->CopCarPos - pCurrentWorld->AICarPos; i++)",
      "i < pCurrentWorld->CopCarPos - pCurrentWorld->AICarPos - 1; i++)"),
    M("addcars_one_sort", RRC,
      """    race_sort_racing_cars_by_leadership(r);
    race_sort_racing_cars_by_leadership(r);
}""",
      """    race_sort_racing_cars_by_leadership(r);
}"""),
    M("addcar_no_count", RRC, "    r->NumRacingCars = n + 1;" + NL, ""),
    M("addcar_first_slot", RRC,
      "    r->pRacingCars[n] = &r->RacingCarTable[n];",
      "    r->pRacingCars[n] = &r->RacingCarTable[0];"),

    # ---- SetRaceStage
    M("stage_no_store", RRC,
      """    r->RaceStage = stage;
    if (stage == RACE_STAGE_RACING && gRaceIsLeavingFn""",
      """    if (stage == RACE_STAGE_RACING && gRaceIsLeavingFn"""),
    M("stage_leaving_always", RRC,
      "    if (stage == RACE_STAGE_RACING && gRaceIsLeavingFn != NULL)",
      "    if (gRaceIsLeavingFn != NULL)"),
    M("stage_real_inverted", RRC,
      """                realdriver_disable_start_line_state(d);
            else
                d->StartLineState = 1;""",
      """                d->StartLineState = 1;
            else
                realdriver_disable_start_line_state(d);"""),
    M("stage_line_state_two", RRC,
      "                d->StartLineState = 1;", "                d->StartLineState = 2;"),
    M("stage_ai_not_real", RRC,
      "    } else if (car->TheControlMode == AI_CONTROL) {",
      "    } else if (car->TheControlMode != REAL_CONTROL) {"),
    M("stage_ai_always", RRC,
      """            if (r->RaceStage == RACE_STAGE_RACING) {
                d->EBrake = 0.0f;""",
      """            if (1) {
                d->EBrake = 0.0f;"""),
    M("stage_no_ebrake", RRC, "                d->EBrake = 0.0f;" + NL, ""),
    M("stage_throttle_half", RRC,
      "                d->Throttle = 1.0f;", "                d->Throttle = 0.5f;"),
    M("stage_no_brake", RRC, "                d->Brake = 0.0f;" + NL, ""),
    M("stage_fake_always", RRC,
      """        if (stage == RACE_STAGE_RACING)
            racingcar_fake_startline_crossing(rc);""",
      """        racingcar_fake_startline_crossing(rc);"""),
    M("stage_countdown_go", RRC,
      """        r->StartGoTimeFrames = 0;
        r->StartCountdownTimeFrames = WorldTimeFrames;""",
      """        r->StartCountdownTimeFrames = WorldTimeFrames;"""),
    M("stage_countdown_frames", RRC,
      """        r->StartCountdownTimeFrames = WorldTimeFrames;
    } else if""",
      """        r->StartCountdownTimeFrames = 0;
    } else if"""),
    M("stage_start_stamp", RRC,
      "        r->StartTime.PackedTime = (uint32_t)WorldTimer;",
      "        r->StartTime.PackedTime = 0;"),
    M("stage_start_no_round", RRC,
      "        timer_round(&r->StartTime, 0.01f);" + NL, ""),
    M("stage_start_countdown", RRC,
      """        r->StartCountdownTimeFrames = 0;
        r->StartGoTimeFrames = WorldTimeFrames;""",
      """        r->StartGoTimeFrames = WorldTimeFrames;"""),
    M("stage_start_go", RRC,
      """        r->StartGoTimeFrames = WorldTimeFrames;
    }""",
      """        r->StartGoTimeFrames = 0;
    }"""),
    M("stage_traffic_racing_only", RRC,
      "    if ((uint32_t)(stage - RACE_STAGE_COUNTDOWN) < 2u) {",
      "    if (stage == RACE_STAGE_RACING) {"),
    M("stage_traffic_signed", RRC,
      "    if ((uint32_t)(stage - RACE_STAGE_COUNTDOWN) < 2u) {",
      "    if (stage - RACE_STAGE_COUNTDOWN < 2) {"),
    M("stage_traffic_from_zero", RRC,
      "pCurrentWorld->CarTable[pCurrentWorld->TrafficCarPos + i];",
      "pCurrentWorld->CarTable[i];"),
    M("stage_traffic_count", RRC,
      "n = pCurrentWorld->TotalNumCars - pCurrentWorld->TrafficCarPos;",
      "n = pCurrentWorld->TotalNumCars - pCurrentWorld->TrafficCarPos - 1;"),
    M("stage_no_render", RRC, "            c->RenderingEnabled = 1;" + NL, ""),
    M("stage_movement_mode", RRC,
      "car_set_movement_mode(c, TRAFFIC_MOVEMENT);",
      "car_set_movement_mode(c, (MovementMode)1);"),

    # ---- SortRacingCarsByLeadership
    M("sort_order_le", RRC,
      "swap = i + 1 < a->FinishingOrder;", "swap = i + 2 < a->FinishingOrder;"),
    M("sort_below_order", RRC,
      "swap = b->FinishingOrder < i + 2;", "swap = b->FinishingOrder < i + 1;"),
    M("sort_below_unfinished", RRC,
      """            else if (b->FinishingOrder != 0)
                swap = b->FinishingOrder < i + 2;
            else""",
      """            else"""),
    M("sort_reversed", RRC,
      "swap = a->FinishedLapNumberExact < b->FinishedLapNumberExact;",
      "swap = b->FinishedLapNumberExact < a->FinishedLapNumberExact;"),
    M("sort_one_pass", RRC, "    } while (swaps != 0);", "    } while (0);"),
    M("sort_last_short", RRC,
      "    int32_t last = r->NumRacingCars - 1;",
      "    int32_t last = r->NumRacingCars - 2;"),
    M("sort_position_from_zero", RRC,
      "        rc->RacePosition = (int8_t)(i + 1);",
      "        rc->RacePosition = (int8_t)i;"),
    M("sort_previous_new", RRC,
      "        rc->PreviousRacePosition = prev;",
      "        rc->PreviousRacePosition = rc->RacePosition;"),

    # ---- Timer::RoundSeconds and Round
    M("round_unsigned", TMC,
      "    float q = (float)(int32_t)t->PackedTime * 0.00025f / f;",
      "    float q = (float)t->PackedTime * 0.00025f / f;"),
    M("round_no_floor", TMC,
      """    if (q < fl)
        fl = fl - 1.0f;
""", ""),
    M("round_half_strict", TMC,
      "    if (0.5f <= q - fl)", "    if (0.5f < q - fl)"),
    M("round_no_half", TMC,
      """    if (0.5f <= q - fl)
        fl = fl + 1.0f;
""", ""),
    M("round_no_ceil", TMC,
      """    if (c < x)
        c = c + 1.0f;
""", ""),
    M("round_ceil_le", TMC, "    if (c < x)", "    if (c <= x)"),
    M("round_ceil_cast", TMC,
      "    c = (float)ee_trunc_w(x);", "    c = (float)(int32_t)x;"),
    M("round_reciprocal", TMC,
      "* 0.00025f / f;", "* 0.00025f * (1.0f / f);"),
    M("round_back_divide", TMC,
      "    return c * 0.00025f;", "    return c / 4000.0f;"),
    M("round_x_order", TMC,
      "    x = fl * f * 4000.0f;", "    x = fl * (f * 4000.0f);"),
    M("round_no_nearest", TMC,
      """* 4000.0f
                                         + 0.5f);""",
      """* 4000.0f);"""),
    M("round_cast", TMC,
      "(uint32_t)ee_trunc_w(timer_round_seconds(t, f) * 4000.0f",
      "(uint32_t)(int32_t)(timer_round_seconds(t, f) * 4000.0f"),
]

# Mutants that cannot change what either side computes, each with why.
EQUIVALENT = {
    # UpdateLapCounts, run last, sets FinishedLapNumberExact to the exact
    # lap whatever was there.
    "init_finished_exact",
    # s is TopSpeed itself (max.s keeps its first operand unless the second
    # is larger, and the window falls back to it) or something larger, so
    # when s == TopSpeed the store would write back the same bits, -0 and
    # NaN included.
    "ulc_top_always",
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
