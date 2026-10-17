"""Cross-check 3DS Files/source/aidriver.c against the retail image's own
code.

AIDriver is the controller of a racer the AI drives: retail's
AIDriver.obj, 0x0012ffc8 to 0x001308a0. The oracle is SLES_507.31 itself,
run in tools/mipsemu.py:

- the constructor (0x0012ffc8), and through _vt$8AIDriver (0x002ae328) the
  destructor (0x00130090), Think (0x00130188), GetRouteNumbersToUse
  (0x00130890) and ChooseNewAction (0x00130238); ShouldWeAvoidThisCar
  (0x001307b0) called directly;
- run as shipped under them: AIDriver.obj's DrivingChoice::Clear
  (0x00130920) and ~DrivingChoice (0x00130930), Average's constructor,
  destructor and Record (0x0018fbf0, 0x0018fc68, 0x0018fcb8) and
  Timer::CountDown (0x001a3cf0).

Stood in on both sides, each call printing a line, so both must ask the
same questions in the same order:
  AICarController's constructor (0x00190140), which sets the car and
    AICarController's vptr and nothing else; its destructor (0x001903a0)
    and Think (0x00191148); MaybeHonkAndOrBlinkHeadlights (0x00192fa8);
    GetAmountOutOfBounds (0x001907b8, the table's slot 64), answering the
    script's amount;
  PsychoDriver's constructor (0x00139760), which gives the driver a test
    table (FDVT) whose destructor (8) prints;
  Car::SetFrictionBoost (0x001315f8);
  World::Random(float) (0x0014e548): the world and the range, answering the
    script's queue, then 0;
  bMalloc (0x002577c0) and the frees (bFree 0x00257850, __builtin_delete
    0x00114e98): a block filled with 0xcd, named h0, h1, ... (the port's
    PsychoDriver and Average records print as the console's 624 and 16);
  bOMalloc (0x00257c80), the port's aiaction_new: the pool, answering a0,
    a1, ...;
  the seven CalculateScores the cascade asks (GetUnstuck 0x001c8c30,
    AvoidRoadBlock 0x001c9718, IJustGotHit 0x001c9d20, AvoidCars
    0x001c6cf8, AccidentRecovery 0x001ca2a8, Pass 0x001c79d8, JustDrive
    0x001c7458): each prints what its out parameters hold on the way in,
    writes the script's answers into those the script's mask names, and
    answers the script's score;
  the nine actions' constructors ChooseNewAction makes (JustDrive
    0x001c73c0, Draft 0x001c7690, PullOver 0x001c8298, GetUnstuck
    0x001c8b30, AccidentRecovery 0x001ca1f0, AvoidRoadBlock 0x001c9668,
    IJustGotHit 0x001c9c68, AvoidCars 0x001c6ba0, Pass 0x001c78f8): each
    prints its arguments and answers its memory.

DrivingChoice::Clear is the harness's copy of drivingchoice.c's (which
drivingchoice_check.py checks), as drivingchoice.c needs most of the AI.

The record is dumped by field; the table slot by slot as retail's
addresses; and the globals the image keeps by value.

    python tools/aidriver_check.py
    python tools/aidriver_check.py --mutate [--only a,b] [--jobs N]
    python tools/aidriver_check.py --dump PREFIX
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

HARNESS = "tools/src/aidriver_test.c"
ADC = "3DS Files/source/aidriver.c"
SOURCES = [HARNESS, ADC,
           "3DS Files/source/average.c",
           "3DS Files/source/timer.c",
           "3DS Files/source/difficultyinfo.c",
           "3DS Files/source/bmem.c",
           "3DS Files/source/replay.c", "3DS Files/source/p32.c",
           "3DS Files/source/vtable.c"]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = retail_model.RETAIL_GP

CTOR = 0x0012ffc8
DTOR = 0x00130090
SHOULD_AVOID = 0x001307b0
AIDRIVER_VT = 0x002ae328

AICC_CTOR = 0x00190140
AICC_DTOR = 0x001903a0
AICC_THINK = 0x00191148
AICC_VT = 0x002b4d90
MAYBE_HONK = 0x00192fa8
OUT_OF_BOUNDS = 0x001907b8
PSYCHO_CTOR = 0x00139760
FRICTION = 0x001315f8
RANDOM_F = 0x0014e548
BMALLOC = 0x002577c0
BOMALLOC = 0x00257c80
BFREE = 0x00257850
BDELETE = 0x00114e98

# The CalculateScores, in the cascade's order, and the constructors.
SCORES = (("unstuck", 0x001c8c30), ("roadblock", 0x001c9718),
          ("hit", 0x001c9d20), ("avoid", 0x001c6cf8),
          ("recovery", 0x001ca2a8), ("pass", 0x001c79d8),
          ("drive", 0x001c7458))
NEWS = (("drive", 0x001c73c0), ("draft", 0x001c7690),
        ("pullover", 0x001c8298), ("unstuck", 0x001c8b30),
        ("recovery", 0x001ca1f0), ("roadblock", 0x001c9668),
        ("hit", 0x001c9c68), ("avoid", 0x001c6ba0), ("pass", 0x001c78f8))
S_UNSTUCK, S_ROADBLOCK, S_HIT, S_AVOID, S_RECOVERY, S_PASS, S_DRIVE = range(7)

TRACK_LENGTH = 0x0031bc38
DIFFICULTY = 0x002f0080
DIFFICULTY_SIZE = 992

WORLD_TIMER_GP = -19576
CURRENT_WORLD_GP = -22120
SLOT_POOL_GP = -18288
JUST_DRIVE_SCORE_GP = -18272
FRICTION_GP = -23008
# The scores (gp-18268 up), the lifetimes (gp-18228 up) and the three
# pull-over timeouts, in aidriver.h's order.
SCORE_GPS = tuple(range(-18268, -18228, 4))
LIFETIME_GPS = tuple(range(-18228, -18188, 4))
TIMEOUT_GPS = (-18160, -18156, -18152)

# The world: retail's offsets.
D = 0x01E00000                      # the AIDriver, 736 bytes
D_SIZE = 736
CAR = 0x01E01000                    # MyDriver 20, pRacingCar 28
DRV = 0x01E02000                    # SkillLevel 3
RC = 0x01E02100                     # dCurrentLapNumberExact 24
WORLD = 0x01E02200
LIST = 0x01E02300
LOC = 0x01E02400
CUR = 0x01E02500                    # an action: Type 588, Score 592
OLD = 0x01E02800
RB = 0x01E02900
CARS = 0x01E03000                   # c0..c7, 0x100 apart
NCARS = 8
POOL = 0x01E04000
SLOTS = 0x01E05000                  # a0, a1, ..., 0x100 apart
NSLOTS = 64
SCR = 0x01E09000                    # the out slot, the route numbers
FDVT = 0x01E0A000                   # the test driver table
FDVT_DTOR = 0x01E0A800              # its destructor
SLACK = 16

INFO = D + 12
OFF_CAR, OFF_DRIVER, OFF_VT = 0, 4, 8
OFF_CHOICE = 492
OFF_LOC, OFF_LIST = 504, 512
OFF_ACTION, OFF_LAST, OFF_POT = 532, 544, 548
OFF_NOTAVOID, OFF_NOTAVOID_T, OFF_PROGRESS_T, OFF_AVG = 720, 724, 728, 732
DRIVER_VT_OFF = 556

(OP_TAG, OP_JUNK, OP_NEW, OP_DEL, OP_NULL, OP_THINK, OP_ROUTES, OP_AVOID,
 OP_CHOOSE, OP_SET, OP_CUR, OP_POKE, OP_DIFF, OP_DUMP, OP_STATIC,
 OP_RAWDEL) = range(16)

ARGS = {OP_TAG: 1, OP_JUNK: 1, OP_NEW: 0, OP_DEL: 1, OP_NULL: 1,
        OP_THINK: 1, OP_ROUTES: 0, OP_AVOID: 2, OP_CHOOSE: 1, OP_SET: 2,
        OP_CUR: 3, OP_POKE: 2, OP_DIFF: 2, OP_DUMP: 0, OP_STATIC: 0,
        OP_RAWDEL: 1}

# OP_SET's keys: what the stand-ins answer. K_SCORE + i is the i'th
# CalculateScore's score.
(K_RANDOM, K_RCLEAR, K_OOB, K_MASK, K_RB, K_HIT, K_AVOIDCAR, K_SECS,
 K_OKAY, K_USED, K_ACH_TYPE, K_ACH_CAR, K_ACH_EXTRA, K_PASSCAR, K_PCH_TYPE,
 K_PCH_CAR, K_PCH_EXTRA, K_AMOUNT) = range(18)
K_SCORE = 18
K_COUNT = K_SCORE + 7

# K_MASK's bits: which outs the CalculateScores write.
W_RB, W_HIT, W_AVOIDCAR, W_SECS, W_OKAY, W_USED, W_ACH, W_PASSCAR, W_PCH, \
    W_AMOUNT = (1 << k for k in range(10))
W_ALL = (1 << 10) - 1

# OP_POKE's fields.
(P_TIMER, P_LAST, P_POT, P_NOTAVOID, P_NOTAVOID_T, P_PROGRESS_T,
 P_TRACKLEN, P_LAPRATE, P_SKILL, P_AVG_SAMPLES, P_AVG_AVERAGE, P_AVG_SLOT,
 P_LIST, P_LOC, P_JDSCORE) = range(15)

# A car argument: -1 none, 0..7 cN, 8 my own car.
NO_CAR, MY_CAR = -1, NCARS

# OP_NULL's fields.
N_DRIVER, N_AVG = 0, 1

# The retail functions the table holds, as the harness names them.
TICK = 0.000250000012


def fb(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def bf(b):
    return struct.unpack("<f", struct.pack("<I", b & M32))[0]


def f32(x):
    return bf(fb(x))


def fx(b):
    return "%08x" % (b & M32)


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


def secs_of(ticks):
    """Seconds as the image reckons a tick count."""
    return f32(f32(float(s32(ticks & M32))) * f32(TICK))


def first_ticks_over(limit, inclusive):
    """The fewest ticks whose seconds reach `limit` (`<=`) or pass it."""
    n = int(limit / TICK) - 4
    while not (limit <= secs_of(n) if inclusive else limit < secs_of(n)):
        n += 1
    return n


NOT_AVOID_TICKS = first_ticks_over(1.0, True)       # 4000
UNSTUCK_TICKS = first_ticks_over(6.0, False)        # 24000


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

    def set(self, key, v):
        self.op(OP_SET, key, v if isinstance(v, (int, Fb)) else float(v))

    def poke(self, f, v):
        if f in (P_POT, P_TRACKLEN, P_LAPRATE, P_AVG_AVERAGE):
            self.op(OP_POKE, f, v if isinstance(v, Fb) else float(v))
        else:
            self.op(OP_POKE, f, int(v))

    def randoms(self, *vals):
        self.set(K_RCLEAR, 0)
        for v in vals:
            self.set(K_RANDOM, v if isinstance(v, Fb) else f32(v))

    def scores(self, *vals):
        assert len(vals) == 7
        for i, v in enumerate(vals):
            self.set(K_SCORE + i, v)

    def fresh(self, junk=0xa5):
        self.op(OP_JUNK, junk)
        self.op(OP_NEW)


# ============================================================== the script

# CollisionAvoidanceChance by skill, -13 to 21: what OP_DIFF writes.
def chance_of(skill):
    if skill == 0:
        return 0.5
    return f32(0.05 + 0.027 * (skill + 13))


SKILLS = range(-13, 22)

# The image's scores, in the cascade's order, for the gates.
CASCADE = ((S_UNSTUCK, 7, 500), (S_ROADBLOCK, 8, 600), (S_HIT, 9, 400),
           (S_AVOID, 1, 400), (S_RECOVERY, 10, 500), (S_PASS, 0, 300),
           (S_DRIVE, None, None))


def all_scores(sc, v):
    sc.scores(*([v] * 7))


def script():
    sc = Script()
    rnd = random.Random(0xa1d)

    sc.tag("static")
    sc.op(OP_STATIC)

    for k in SKILLS:
        sc.op(OP_DIFF, 380 + 28 * k, chance_of(k))
    sc.poke(P_JDSCORE, 150)
    sc.set(K_MASK, W_ALL)

    # -- the constructor and the destructor -----------------------------------
    for flags in (0, 1, 2, 3):
        sc.tag("new, del %d" % flags)
        sc.fresh(0xa5 if flags != 2 else 0x00)
        sc.op(OP_DUMP)
        sc.op(OP_DEL, flags)
        sc.op(OP_DUMP)
    for nulls in ((N_DRIVER,), (N_AVG,), (N_DRIVER, N_AVG)):
        sc.tag("del with no %s" % (nulls,))
        sc.fresh(0x5c)
        for n in nulls:
            sc.op(OP_NULL, n)
        sc.op(OP_DEL, 1)
        sc.op(OP_DUMP)

    # Called directly, with AICarController's vptr: the destructor's own.
    sc.tag("del with another vptr")
    sc.fresh()
    sc.op(OP_RAWDEL, 1)
    sc.op(OP_DUMP)

    sc.tag("routes")
    sc.fresh()
    sc.op(OP_ROUTES)

    # -- Think ----------------------------------------------------------------
    sc.tag("think, as built")
    sc.fresh()
    sc.poke(P_TRACKLEN, 4123.5)
    sc.poke(P_LAPRATE, -0.0125)
    for dt in (1.0 / 30.0, 1.4, nextup(1.5 - 1.0 / 30.0 - 1.4, -1), 0.0,
               0.000125, 0.1, 1.5, 1.5):
        sc.op(OP_THINK, f32(dt))
        sc.op(OP_DUMP)

    # The timer a tick either side of the step, at several sizes.
    sc.tag("think, timer edges")
    for ticks in (1, 2, 3, 6000, 6001, 100000, 0x40000000):
        for dticks in (ticks - 1, ticks, ticks + 1):
            if dticks < 0:
                continue
            sc.fresh()
            sc.poke(P_PROGRESS_T, ticks)
            sc.poke(P_LAPRATE, f32(0.01 * (ticks % 7 + 1)))
            sc.poke(P_TRACKLEN, 3000.0)
            sc.op(OP_THINK, f32((dticks + 0.5) / 4000.0))
            sc.op(OP_DUMP)

    sc.tag("think, odd timers")
    for ticks in (0, 0x7fffffff, 0x80000000, 0xffffffff, 0x7ffffffe, 5):
        for dt in (0.0, 1.0 / 30.0, -1.0, -0.0, 1e10, -1e10, 600000.0):
            sc.fresh()
            sc.poke(P_PROGRESS_T, ticks)
            sc.poke(P_LAPRATE, 0.03)
            sc.poke(P_TRACKLEN, 2500.0)
            sc.op(OP_THINK, f32(dt))
            sc.op(OP_DUMP)

    sc.tag("think, the lap rate")
    for rate in (0.0, -0.0, 1.0, -1.0, 1e-30, -3.5e5, nextup(0.0)):
        for tl in (0.0, 5000.0, -1.0):
            sc.fresh()
            sc.poke(P_PROGRESS_T, 1)
            sc.poke(P_LAPRATE, rate)
            sc.poke(P_TRACKLEN, tl)
            sc.op(OP_THINK, 0.001)
            sc.op(OP_DUMP)

    # Round the ring twice: the Average full, and its oldest sample out.
    sc.tag("think, the ring")
    sc.fresh()
    sc.poke(P_TRACKLEN, 6200.0)
    for k in range(13):
        sc.poke(P_LAPRATE, f32(rnd.uniform(-0.05, 0.05)))
        sc.op(OP_THINK, 1.5)
        sc.op(OP_DUMP)

    # -- ShouldWeAvoidThisCar -------------------------------------------------
    # The car not to avoid forgotten at a second, a tick either side, and
    # times that wrap.
    sc.tag("avoid, the second")
    n1 = NOT_AVOID_TICKS
    for dt in (n1 - 1, n1, n1 + 1, 0, -1, -n1, 0x7fffffff, -0x80000000,
               0x80000000 + n1, 100000):
        for car in (0, 1):
            sc.fresh()
            sc.poke(P_SKILL, 3)
            sc.poke(P_NOTAVOID, 0)
            sc.poke(P_NOTAVOID_T, 0x10000)
            sc.poke(P_TIMER, (0x10000 + dt) & M32)
            sc.randoms(0.0)
            sc.op(OP_AVOID, car, 0.0)
            sc.op(OP_DUMP)

    # No car: the car not to avoid none, or one.
    sc.tag("avoid, no car")
    for notavoid in (NO_CAR, 2):
        for draw in (0.0, 0.99):
            sc.fresh()
            sc.poke(P_SKILL, 1)
            sc.poke(P_NOTAVOID, notavoid)
            sc.poke(P_NOTAVOID_T, 5000)
            sc.poke(P_TIMER, 5000 + 100)
            sc.randoms(draw)
            sc.op(OP_AVOID, NO_CAR, -1.0)
            sc.op(OP_DUMP)

    # Every skill, the draw at its chance and an ulp either side; -2 reads
    # 0's.
    sc.tag("avoid, the skills")
    for skill in SKILLS:
        c = chance_of(skill if skill != -2 else 0)
        for r in (nextup(c, -1), c, nextup(c), 0.0, 1.0):
            sc.fresh()
            sc.poke(P_SKILL, skill)
            sc.poke(P_NOTAVOID, 5)
            sc.poke(P_NOTAVOID_T, 100)
            sc.poke(P_TIMER, 200)
            sc.randoms(r)
            sc.op(OP_AVOID, 6, f32(rnd.uniform(-5, 5)))
            sc.op(OP_DUMP)

    # Two calls in turn: decided against, then left alone, then forgotten.
    sc.tag("avoid, in turn")
    sc.fresh()
    sc.poke(P_SKILL, 4)
    sc.poke(P_NOTAVOID, NO_CAR)
    for timer, car, r in ((1000, 3, 0.99), (1500, 3, 0.0), (1500, 4, 0.99),
                          (4999, 4, 0.0), (5000, 4, 0.0), (6000, 3, 0.99),
                          (6000, MY_CAR, 0.0)):
        sc.poke(P_TIMER, timer)
        sc.randoms(r)
        sc.op(OP_AVOID, car, 0.0)
        sc.op(OP_DUMP)

    # -- ChooseNewAction: forced --------------------------------------------------
    sc.tag("forced")
    for typ in (-2, -1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 0x7fffffff,
                -0x80000000):
        for listp in ((1, 1), (0, 0)) if typ in (6, 3) else ((1, 1),):
            sc.fresh()
            sc.poke(P_POT, 7.25)
            sc.poke(P_LIST, listp[0])
            sc.poke(P_LOC, listp[1])
            sc.op(OP_CUR, 1, 5, 9999)
            sc.op(OP_CHOOSE, typ)
            sc.op(OP_DUMP)

    # -- ChooseNewAction: the cascade -----------------------------------------
    def cascade_world(sc, last_ticks=UNSTUCK_TICKS + 10, oob=0.0):
        sc.fresh()
        sc.poke(P_LIST, 1)
        sc.poke(P_LOC, 1)
        sc.poke(P_SKILL, 2)
        sc.poke(P_NOTAVOID, NO_CAR)
        sc.poke(P_LAST, 100)
        sc.poke(P_TIMER, 100 + last_ticks)
        sc.set(K_OOB, oob)
        sc.set(K_MASK, W_ALL)
        sc.set(K_RB, 1)
        sc.set(K_HIT, 2)
        sc.set(K_AVOIDCAR, 3)
        sc.set(K_SECS, 2.75)
        sc.set(K_OKAY, 0)
        sc.set(K_USED, 1)
        sc.set(K_ACH_TYPE, 2)
        sc.set(K_ACH_CAR, 4)
        sc.set(K_ACH_EXTRA, 1)
        sc.set(K_PASSCAR, 5)
        sc.set(K_PCH_TYPE, 1)
        sc.set(K_PCH_CAR, 6)
        sc.set(K_PCH_EXTRA, 0)
        sc.set(K_AMOUNT, -3.5)
        sc.randoms(0.0, 0.0)

    # Each action alone, with no current action.
    sc.tag("cascade, each alone")
    for i in range(7):
        for s in (0, 1, 777, -1):
            cascade_world(sc)
            vals = [-1] * 7
            vals[i] = s
            sc.scores(*vals)
            sc.op(OP_CUR, 0, 0, 0)
            sc.op(OP_CHOOSE, 11)
            sc.op(OP_DUMP)

    # The first that scores 0 or more wins.
    sc.tag("cascade, the order")
    for first in range(7):
        cascade_world(sc)
        sc.scores(*[(-5 if i < first else 10 + i) for i in range(7)])
        sc.op(OP_CUR, 0, 0, 0)
        sc.op(OP_CHOOSE, 11)
        sc.op(OP_DUMP)

    # The current action: each type, a score either side of each global.
    # With every score below 0 but JustDrive's, each gate shows as its
    # CalculateScore asked or not; with every score 3, the first open gate
    # wins.
    sc.tag("cascade, the current action")
    for typ in range(-1, 13):
        for score in (-1, 299, 300, 301, 399, 400, 401, 499, 500, 501, 599,
                      600, 601, 0x7fffffff, -0x80000000):
            for scores in ((-1,) * 6 + (3,), (3,) * 7):
                cascade_world(sc)
                sc.scores(*scores)
                sc.op(OP_CUR, 1, typ, score)
                sc.op(OP_CHOOSE, 11)
                sc.op(OP_DUMP)
    # Every action skipped but JustDrive, which scores below 0: nothing.
    for s in (-1, -0x80000000, 0):
        cascade_world(sc)
        all_scores(sc, s)
        sc.op(OP_CUR, 1, 4, 1000)
        sc.op(OP_CHOOSE, 11)
        sc.op(OP_DUMP)

    # GetUnstuck's six seconds since the last other action.
    sc.tag("cascade, six seconds")
    n6 = UNSTUCK_TICKS
    for ticks in (n6 - 1, n6, n6 + 1, 0, -1, -n6, 0x7fffffff, -0x80000000,
                  0x80000000 + n6):
        cascade_world(sc, last_ticks=ticks)
        all_scores(sc, 1)
        sc.op(OP_CUR, 0, 0, 0)
        sc.op(OP_CHOOSE, 11)
        sc.op(OP_DUMP)

    # GetUnstuck's minimum lifetime: off the road, the Average full and
    # low.
    sc.tag("cascade, very stuck")
    for oob in (0.0, -0.0, nextup(0.0), -1.0, 2.5):
        for samples in (4, 5, 6, 0):
            for avg in (nextup(0.2, -1), f32(0.2), nextup(0.2), -1.0, 0.0):
                cascade_world(sc, oob=oob)
                sc.poke(P_AVG_SAMPLES, samples)
                sc.poke(P_AVG_AVERAGE, f32(avg))
                vals = [-1] * 7
                vals[S_UNSTUCK] = 42
                sc.scores(*vals)
                sc.op(OP_CUR, 0, 0, 0)
                sc.op(OP_CHOOSE, 11)
                sc.op(OP_DUMP)

    # AvoidCars: the bool as the seconds, each way to the unsigned
    # conversion; and ShouldWeAvoid's answer.
    sc.tag("cascade, avoid cars")
    for okay in (0, 1, 2, 0x7fffffff, 0x80000000, 0x80000001, 0xffffffff,
                 0xfffffffe, 0x01000001):
        for draw in (0.0, 0.99):
            cascade_world(sc)
            sc.set(K_OKAY, okay)
            sc.set(K_USED, okay ^ 0x5a)
            sc.randoms(draw, draw)
            sc.scores(-1, -1, -1, 7, -1, 8, 9)
            sc.op(OP_CUR, 0, 0, 0)
            sc.op(OP_CHOOSE, 11)
            sc.op(OP_DUMP)

    # What the CalculateScores leave unwritten: the starting values.
    sc.tag("cascade, outs left alone")
    for mask in (0, W_ACH, W_PCH, W_ACH | W_PCH, W_ALL & ~W_ACH,
                 W_ALL & ~W_PCH, W_ALL & ~(W_OKAY | W_SECS | W_USED),
                 W_ALL & ~(W_AVOIDCAR | W_PASSCAR | W_HIT | W_RB)):
        for scores in ((-1, -1, -1, 7, -1, 8, 9), (-1, -1, -1, 7, -1, -1, 9),
                       (-1, 0, -1, -1, -1, -1, -1), (-1, -1, 0, -1, -1, -1, -1),
                       (-1, -1, -1, -1, -1, 3, -1)):
            for draws in ((0.99, 0.0), (0.0, 0.0), (0.99, 0.99)):
                cascade_world(sc)
                sc.set(K_MASK, mask)
                sc.randoms(*draws)
                sc.scores(*scores)
                sc.op(OP_CUR, 0, 0, 0)
                sc.op(OP_CHOOSE, 11)
                sc.op(OP_DUMP)

    # Pass and AvoidCars name the car not to avoid; the hit car's honk
    # with no list.
    sc.tag("cascade, cars")
    for notavoid in (3, 5, NO_CAR):
        for listp in (0, 1):
            cascade_world(sc)
            sc.poke(P_NOTAVOID, notavoid)
            sc.poke(P_NOTAVOID_T, 100 + UNSTUCK_TICKS)
            sc.poke(P_LIST, listp)
            sc.randoms(0.0, 0.0)
            sc.scores(-1, -1, -1, 7, -1, 8, 9)
            sc.op(OP_CUR, 0, 0, 0)
            sc.op(OP_CHOOSE, 11)
            sc.op(OP_DUMP)
    for car in (NO_CAR, 7, MY_CAR):
        cascade_world(sc)
        sc.set(K_HIT, car)
        sc.poke(P_LIST, car & 1)
        sc.scores(-1, -1, 4, -1, -1, -1, -1)
        sc.op(OP_CUR, 0, 0, 0)
        sc.op(OP_CHOOSE, 11)
        sc.op(OP_DUMP)

    # A run of thinks and choices on one driver, the way the game has it.
    sc.tag("cascade, in turn")
    cascade_world(sc)
    timer = 100 + UNSTUCK_TICKS
    for k in range(60):
        timer += rnd.choice((133, 1000, 4000, 3999, 24000, 7))
        sc.poke(P_TIMER, timer)
        sc.poke(P_LAPRATE, f32(rnd.uniform(-0.02, 0.02)))
        sc.op(OP_THINK, f32(rnd.choice((1.0 / 30.0, 1.5, 0.25))))
        sc.set(K_OOB, f32(rnd.choice((0.0, 1.5, -2.0))))
        sc.set(K_AVOIDCAR, rnd.randrange(-1, NCARS + 1))
        sc.set(K_PASSCAR, rnd.randrange(-1, NCARS + 1))
        sc.randoms(f32(rnd.random()), f32(rnd.random()))
        sc.scores(*[rnd.choice((-1, -1, 0, rnd.randrange(1000)))
                    for _ in range(7)])
        if rnd.random() < 0.5:
            sc.op(OP_CUR, 0, 0, 0)
        else:
            sc.op(OP_CUR, 1, rnd.randrange(12),
                  rnd.choice((300, 400, 500, 600, rnd.randrange(-5, 900))))
        sc.op(OP_CHOOSE, rnd.choice((11, 11, 11, 11, rnd.randrange(-1, 13))))
        sc.op(OP_DUMP)

    # Random rounds over everything.
    sc.tag("cascade, random")
    for k in range(400):
        cascade_world(sc, last_ticks=rnd.choice(
            (UNSTUCK_TICKS - 1, UNSTUCK_TICKS, rnd.randrange(0, 80000))),
            oob=f32(rnd.choice((0.0, rnd.uniform(-3, 3)))))
        sc.poke(P_SKILL, rnd.choice((-2, 0, 5, rnd.randrange(-13, 22))))
        sc.poke(P_NOTAVOID, rnd.choice((NO_CAR, 3, 5, rnd.randrange(NCARS))))
        sc.poke(P_NOTAVOID_T, rnd.randrange(0, 30000))
        sc.poke(P_AVG_SAMPLES, rnd.choice((5, 5, 4, rnd.randrange(256))))
        sc.poke(P_AVG_AVERAGE, f32(rnd.choice((0.1, 0.3, rnd.uniform(-1, 1)))))
        sc.poke(P_POT, f32(rnd.uniform(-10, 10)))
        sc.poke(P_LIST, rnd.randrange(2))
        sc.poke(P_LOC, rnd.randrange(2))
        sc.set(K_MASK, rnd.choice((W_ALL, W_ALL, rnd.randrange(1 << 10))))
        for key in (K_RB, K_HIT, K_AVOIDCAR, K_ACH_CAR, K_PASSCAR, K_PCH_CAR):
            sc.set(key, rnd.randrange(-1, NCARS + 1))
        sc.set(K_SECS, f32(rnd.uniform(-5, 5)))
        sc.set(K_OKAY, rnd.choice((0, 1, rnd.randrange(1 << 32))))
        sc.set(K_USED, rnd.choice((0, 1, rnd.randrange(1 << 32))))
        sc.set(K_ACH_TYPE, rnd.randrange(-1, 5))
        sc.set(K_PCH_TYPE, rnd.randrange(-1, 5))
        sc.set(K_ACH_EXTRA, rnd.randrange(3))
        sc.set(K_PCH_EXTRA, rnd.randrange(3))
        sc.set(K_AMOUNT, f32(rnd.uniform(-9, 9)))
        sc.randoms(*[f32(rnd.random()) for _ in range(rnd.randrange(3))])
        sc.scores(*[rnd.choice((-1, -1, 0, rnd.randrange(-3, 1000)))
                    for _ in range(7)])
        if rnd.random() < 0.4:
            sc.op(OP_CUR, 0, 0, 0)
        else:
            sc.op(OP_CUR, 1, rnd.randrange(-1, 13),
                  rnd.choice((299, 300, 301, 399, 400, 401, 499, 500, 501,
                              599, 600, 601, rnd.randrange(-5, 900))))
        sc.op(OP_CHOOSE, rnd.choice((11, 11, 11, 11, 11, rnd.randrange(-1, 13))))
        sc.op(OP_DUMP)

    sc.tag("globals")
    sc.op(OP_STATIC)
    return sc


# ================================================================ the model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        e.stub_bware()
        self.heap = []                  # (addr, span, label)
        self.nslots = 0
        self.vals = dict.fromkeys(range(K_COUNT), 0)
        self.queue = []
        for base, n in ((D, 0x1000), (CAR, 0x1000), (DRV, 0x2000),
                        (CARS, 0x1000), (POOL, 0x1000),
                        (SLOTS, NSLOTS * 0x100), (SCR, 0x1000),
                        (FDVT, 0x1000)):
            e.mem[base:base + n] = bytes(n)
        e.put32(CAR + 20, DRV)
        e.put32(CAR + 28, RC)
        e.put32(GP + CURRENT_WORLD_GP, WORLD)
        e.put32(GP + SLOT_POOL_GP, POOL)
        e.put32(FDVT + 12, FDVT_DTOR)
        self.stubs()

    def emit(self, s):
        self.out.append(s)

    def w(self, a):
        return self.e.u32(a)

    def car_addr(self, i):
        if i == NO_CAR:
            return 0
        if i == MY_CAR:
            return CAR
        return CARS + 0x100 * i

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        names = {D: "d", INFO: "info", CAR: "car", WORLD: "world",
                 LIST: "list", LOC: "loc", CUR: "cur", OLD: "old", RB: "rb",
                 POOL: "pool"}
        if a in names:
            return names[a]
        if CARS <= a < CARS + 0x100 * NCARS and (a - CARS) % 0x100 == 0:
            return "c%d" % ((a - CARS) // 0x100)
        if SLOTS <= a < SLOTS + 0x100 * NSLOTS and (a - SLOTS) % 0x100 == 0:
            return "a%d" % ((a - SLOTS) // 0x100)
        for base, span, name in self.heap:
            if base <= a < base + span:
                return name if a == base else "%s+%d" % (name, a - base)
        return "?"

    # ---- the stand-ins ---------------------------------------------------

    def stubs(self):
        e = self.e

        def arg(i):
            return e.reg[4 + i] & M32

        def cstr(p):
            end = e.mem.index(b"\0", p)
            return e.mem[p:end].decode("latin-1")

        def malloc(em):
            size = s32(arg(0))
            name = cstr(arg(1))
            span = max(size, 0) + SLACK
            p = e.alloc(span, align=16)
            e.mem[p:p + span] = bytes([0xcd]) * span
            lab = "h%d" % len(self.heap)
            self.heap.append((p, span, lab))
            self.emit("  alloc %s size %d name %s flags %d pool %d"
                      % (lab, size, name, s32(arg(2)), s32(arg(3))))
            return p

        def free(em):
            self.emit("  free %s" % self.label(arg(0)))

        def omalloc(em):
            p = SLOTS + 0x100 * self.nslots
            self.nslots += 1
            self.emit("  oalloc %s -> %s" % (self.label(arg(0)),
                                             self.label(p)))
            return p

        def aicc_ctor(em):
            t = arg(0)
            self.emit("  aicc init %s %s" % (self.label(t),
                                             self.label(arg(1))))
            e.put32(t + OFF_CAR, arg(1))
            e.put32(t + OFF_VT, AICC_VT)
            return t

        def aicc_dtor(em):
            self.emit("  aicc dtor %s %d" % (self.label(arg(0)),
                                             s32(arg(1))))

        def aicc_think(em):
            self.emit("  aicc think %s %s" % (self.label(arg(0)),
                                              fx(e.fpr[12])))

        def honk(em):
            self.emit("  honk %s %s %s" % (self.label(arg(0)),
                                           self.label(arg(1)),
                                           self.label(arg(2))))

        def oob(em):
            self.emit("  oob %s -> %s" % (self.label(arg(0)),
                                          fx(self.vals[K_OOB])))
            e.fpr[0] = self.vals[K_OOB]

        def psycho(em):
            t = arg(0)
            self.emit("  psycho init %s %s" % (self.label(t),
                                               self.label(arg(1))))
            e.put32(t + DRIVER_VT_OFF, FDVT)
            return t

        def driver_dtor(em):
            self.emit("  driver dtor %s %d" % (self.label(arg(0)),
                                               s32(arg(1))))

        def friction(em):
            self.emit("  friction %s %s" % (self.label(arg(0)),
                                            fx(e.fpr[12])))

        def random_f(em):
            r = self.queue.pop(0) if self.queue else 0
            self.emit("  random %s %s -> %s" % (self.label(arg(0)),
                                                fx(e.fpr[12]), fx(r)))
            e.fpr[0] = r

        e.stub(BMALLOC, malloc)
        e.stub(BFREE, free)
        e.stub(BDELETE, free)
        e.stub(BOMALLOC, omalloc)
        e.stub(AICC_CTOR, aicc_ctor)
        e.stub(AICC_DTOR, aicc_dtor)
        e.stub(AICC_THINK, aicc_think)
        e.stub(MAYBE_HONK, honk)
        e.stub(OUT_OF_BOUNDS, oob)
        e.stub(PSYCHO_CTOR, psycho)
        e.stub(FDVT_DTOR, driver_dtor)
        e.stub(FRICTION, friction)
        e.stub(RANDOM_F, random_f)
        for i, (name, addr) in enumerate(SCORES):
            e.stub(addr, self.score_stub(i, name))
        for name, addr in NEWS:
            e.stub(addr, self.new_stub(name))

    def choice_str(self, p):
        return "%d %s %d" % (s32(self.w(p)), self.label(self.w(p + 4)),
                             s32(self.w(p + 8)))

    def score_stub(self, i, name):
        e, v = self.e, self.vals

        def put_car(p, key):
            e.put32(p, self.car_addr(s32(v[key])))

        def put_choice(p, base):
            e.put32(p, v[base])
            e.put32(p + 4, self.car_addr(s32(v[base + 1])))
            e.put32(p + 8, v[base + 2])

        def stub(em):
            a = [e.reg[4 + k] & M32 for k in range(6)]
            mask = v[K_MASK]
            s = "  score %s %s" % (name, self.label(a[0]))
            if i == S_ROADBLOCK:
                s += " rb %s" % self.label(self.w(a[1]))
            elif i == S_HIT:
                s += " car %s" % self.label(self.w(a[1]))
            elif i == S_AVOID:
                s += " car %s choice %s secs %s okay %d used %d" % (
                    self.label(self.w(a[1])), self.choice_str(a[2]),
                    fx(self.w(a[3])), s32(self.w(a[4])), s32(self.w(a[5])))
            elif i == S_PASS:
                s += " car %s choice %s amount %s" % (
                    self.label(self.w(a[1])), self.choice_str(a[2]),
                    fx(self.w(a[3])))
            r = s32(v[K_SCORE + i])
            self.emit(s + " -> %d" % r)
            if i == S_ROADBLOCK and mask & W_RB:
                e.put32(a[1], RB if s32(v[K_RB]) >= 0 else 0)
            elif i == S_HIT and mask & W_HIT:
                put_car(a[1], K_HIT)
            elif i == S_AVOID:
                if mask & W_AVOIDCAR:
                    put_car(a[1], K_AVOIDCAR)
                if mask & W_ACH:
                    put_choice(a[2], K_ACH_TYPE)
                if mask & W_SECS:
                    e.put32(a[3], v[K_SECS])
                if mask & W_OKAY:
                    e.put32(a[4], v[K_OKAY])
                if mask & W_USED:
                    e.put32(a[5], v[K_USED])
            elif i == S_PASS:
                if mask & W_PASSCAR:
                    put_car(a[1], K_PASSCAR)
                if mask & W_PCH:
                    put_choice(a[2], K_PCH_TYPE)
                if mask & W_AMOUNT:
                    e.put32(a[3], v[K_AMOUNT])
            return r
        return stub

    def new_stub(self, name):
        e = self.e

        def stub(em):
            a = [e.reg[4 + k] & M32 for k in range(5)]
            s = "  new %s %s %d %s" % (name, self.label(a[0]), s32(a[1]),
                                       fx(e.fpr[12]))
            if name == "unstuck":
                s += " %s" % fx(e.fpr[13])
            elif name == "roadblock":
                s += " %s" % self.label(a[2])
            elif name == "hit":
                s += " %s" % self.label(a[2])
            elif name == "avoid":
                s += " %s %s %d %d" % (self.label(a[2]), fx(e.fpr[13]),
                                       s32(a[3]), s32(a[4]))
            elif name == "pass":
                s += " %s %s" % (self.label(a[2]), fx(e.fpr[13]))
            elif name == "pullover":
                s += " %s %s %s" % (fx(e.fpr[13]), self.label(a[2]),
                                    self.label(a[3]))
            self.emit(s)
            return a[0]
        return stub

    # ---- the dump --------------------------------------------------------

    def vtname(self, v):
        return {AIDRIVER_VT: "aidriver", AICC_VT: "aicc"}.get(v, "%08x" % v)

    def dump(self):
        w = self.w
        self.emit("d vt %s car %s drv %s act %s skip %s skipt %08x prog %08x "
                  "avg %s"
                  % (self.vtname(w(D + OFF_VT)), self.label(w(D + OFF_CAR)),
                     self.label(w(D + OFF_DRIVER)),
                     self.label(w(D + OFF_ACTION)),
                     self.label(w(D + OFF_NOTAVOID)),
                     w(D + OFF_NOTAVOID_T), w(D + OFF_PROGRESS_T),
                     self.label(w(D + OFF_AVG))))
        self.emit("d last %08x pot %s choice %s"
                  % (w(D + OFF_LAST), fx(w(D + OFF_POT)),
                     self.choice_str(D + OFF_CHOICE)))
        a = w(D + OFF_AVG)
        if self.label(a) not in ("null", "?"):
            e = self.e
            n = e.u8(a)
            self.emit("  avg %d %d %d %s %s %s" % (
                n, e.u8(a + 1), e.u8(a + 2), fx(w(a + 4)), fx(w(a + 8)),
                " ".join(fx(w(w(a + 12) + 4 * k)) for k in range(n))))

    def static(self):
        w = self.w
        self.emit("g scores %s" % " ".join(
            "%d" % s32(w(GP + g)) for g in SCORE_GPS))
        self.emit("g lifetimes %s" % " ".join(
            fx(w(GP + g)) for g in LIFETIME_GPS))
        self.emit("g timeouts %s friction %s" % (
            " ".join(fx(w(GP + g)) for g in TIMEOUT_GPS),
            fx(w(GP + FRICTION_GP))))
        for k in range(17):
            fn = w(AIDRIVER_VT + 8 * k + 4)
            self.emit("vt %d %d %08x" % (k, s32(self.e.u16(AIDRIVER_VT + 8 * k)
                                               << 16) >> 16, fn))

    # ---- the run ---------------------------------------------------------

    def vcall(self, slot, *args):
        e = self.e
        vt = self.w(D + OFF_VT)
        delta = s32(e.u16(vt + slot) << 16) >> 16
        fn = self.w(vt + slot + 4)
        return e.call(fn, (D + delta) & M32, *args)

    def run(self, sc):
        e, w = self.e, self.w
        tags = sc.tags
        for o in sc.ops:
            code, a = o[0], o[1:]
            if code == OP_TAG:
                self.emit("[%s]" % tags[a[0]])
            elif code == OP_JUNK:
                e.mem[D:D + D_SIZE] = bytes([a[0] & 0xff]) * D_SIZE
            elif code == OP_NEW:
                self.nslots = 0             # each driver's actions from a0
                self.emit("new")
                r = e.call(CTOR, D, CAR)
                self.emit("new -> %s" % self.label(r))
            elif code == OP_DEL:
                self.emit("del %d" % a[0])
                self.vcall(8, a[0])
            elif code == OP_NULL:
                e.put32(D + (OFF_DRIVER, OFF_AVG)[a[0]], 0)
            elif code == OP_THINK:
                self.emit("think %s" % fx(a[0]))
                e.fpr[12] = a[0]
                self.vcall(32)
            elif code == OP_ROUTES:
                e.put32(SCR, 0x5a5a5a5a)
                e.put32(SCR + 4, 0x5a5a5a5a)
                self.vcall(112, SCR, SCR + 4)
                self.emit("routes -> %d %d" % (s32(w(SCR)), s32(w(SCR + 4))))
            elif code == OP_AVOID:
                self.emit("avoid %s %s" % (self.label(self.car_addr(a[0])),
                                           fx(a[1])))
                e.fpr[12] = a[1]
                r = e.call(SHOULD_AVOID, D, self.car_addr(a[0]))
                self.emit("avoid -> %d" % r)
            elif code == OP_CHOOSE:
                e.put32(SCR, OLD)
                self.emit("choose %d" % s32(a[0]))
                self.vcall(120, SCR, a[0])
                self.emit("choose -> %s" % self.label(w(SCR)))
            elif code == OP_SET:
                if a[0] == K_RANDOM:
                    self.queue.append(a[1] & M32)
                elif a[0] == K_RCLEAR:
                    self.queue = []
                else:
                    self.vals[a[0]] = a[1] & M32
            elif code == OP_CUR:
                if a[0]:
                    e.put32(CUR + 588, a[1])
                    e.put32(CUR + 592, a[2])
                    e.put32(D + OFF_ACTION, CUR)
                else:
                    e.put32(D + OFF_ACTION, 0)
            elif code == OP_POKE:
                self.poke(a[0], a[1])
            elif code == OP_DIFF:
                e.put32(DIFFICULTY + a[0], a[1])
            elif code == OP_DUMP:
                self.dump()
            elif code == OP_STATIC:
                self.static()
            elif code == OP_RAWDEL:
                e.put32(D + OFF_VT, AICC_VT)
                self.emit("rawdel %d" % a[0])
                e.call(DTOR, D, a[0])
            else:
                raise ValueError("op %d" % code)
        return self.out

    def poke(self, f, v):
        e, w = self.e, self.w
        if f == P_TIMER:
            e.put32(GP + WORLD_TIMER_GP, v)
        elif f == P_LAST:
            e.put32(D + OFF_LAST, v)
        elif f == P_POT:
            e.put32(D + OFF_POT, v)
        elif f == P_NOTAVOID:
            e.put32(D + OFF_NOTAVOID, self.car_addr(s32(v)))
        elif f == P_NOTAVOID_T:
            e.put32(D + OFF_NOTAVOID_T, v)
        elif f == P_PROGRESS_T:
            e.put32(D + OFF_PROGRESS_T, v)
        elif f == P_TRACKLEN:
            e.put32(TRACK_LENGTH, v)
        elif f == P_LAPRATE:
            e.put32(RC + 24, v)
        elif f == P_SKILL:
            e.write(DRV + 3, bytes([v & 0xff]))
        elif f in (P_AVG_SAMPLES, P_AVG_SLOT):
            e.write(w(D + OFF_AVG) + (2 if f == P_AVG_SAMPLES else 1),
                    bytes([v & 0xff]))
        elif f == P_AVG_AVERAGE:
            e.put32(w(D + OFF_AVG) + 8, v)
        elif f == P_LIST:
            e.put32(D + OFF_LIST, LIST if v else 0)
        elif f == P_LOC:
            e.put32(D + OFF_LOC, LOC if v else 0)
        elif f == P_JDSCORE:
            e.put32(GP + JUST_DRIVE_SCORE_GP, v)
        else:
            raise ValueError("poke %d" % f)


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc.encode().hex().splitlines()
                               + sc.tags, lambda s: Model().run(sc),
                               cut=MUTATIONS_HEADER)


# ================================================================ the build


def build_harness(tmp, name="aidriver_test"):
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

def M(name, before, after):
    return (name, ADC, before, after)


MUTATIONS = [
    # -- the globals ------------------------------------------------------------
    M("g-draft", "AIActionDraftScore = 200;", "AIActionDraftScore = 201;"),
    M("g-pass", "AIActionPassScore = 300;", "AIActionPassScore = 301;"),
    M("g-nudge", "AIActionNudgeCarScore = 300;",
      "AIActionNudgeCarScore = 301;"),
    M("g-block", "AIActionBlockScore = 400;", "AIActionBlockScore = 401;"),
    M("g-avoid", "AIActionAvoidCarsScore = 400;",
      "AIActionAvoidCarsScore = 401;"),
    M("g-hit", "AIActionIJustGotHitScore = 400;",
      "AIActionIJustGotHitScore = 401;"),
    M("g-unstuck", "AIActionGetUnstuckScore = 500;",
      "AIActionGetUnstuckScore = 501;"),
    M("g-recovery", "AIActionAccidentRecoveryScore = 500;",
      "AIActionAccidentRecoveryScore = 501;"),
    M("g-pullover", "AIActionPullOverScore = 600;",
      "AIActionPullOverScore = 601;"),
    M("g-roadblock", "AIActionAvoidRoadBlockScore = 600;",
      "AIActionAvoidRoadBlockScore = 601;"),
    M("g-l-pass", "AIActionPassLifetime = 5.0f;", "AIActionPassLifetime = 4.0f;"),
    M("g-l-draft", "float AIActionDraftLifetime;",
      "float AIActionDraftLifetime = 1.0f;"),
    M("g-l-nudge", "AIActionNudgeCarLifetime = 5.0f;",
      "AIActionNudgeCarLifetime = 4.0f;"),
    M("g-l-drive", "float AIActionJustDriveLifetime;",
      "float AIActionJustDriveLifetime = 1.0f;"),
    M("g-l-block", "AIActionBlockLifetime = 5.0f;",
      "AIActionBlockLifetime = 4.0f;"),
    M("g-l-unstuck", "AIActionGetUnstuckLifetime = 5.0f;",
      "AIActionGetUnstuckLifetime = 4.0f;"),
    M("g-l-pullover", "float AIActionPullOverLifetime;",
      "float AIActionPullOverLifetime = 1.0f;"),
    M("g-l-avoid", "float AIActionAvoidCarsLifetime;",
      "float AIActionAvoidCarsLifetime = 1.0f;"),
    M("g-l-hit", "float AIActionIJustGotHitLifetime;",
      "float AIActionIJustGotHitLifetime = 1.0f;"),
    M("g-l-recovery", "float AIActionAccidentRecoveryLifetime;",
      "float AIActionAccidentRecoveryLifetime = 1.0f;"),
    M("g-t-traffic", "AIActionPullOverTrafficCarTimeout = -999.0f;",
      "AIActionPullOverTrafficCarTimeout = -998.0f;"),
    M("g-t-finish", "AIActionPullOverCrossFinishLineTimeout = 15.0f;",
      "AIActionPullOverCrossFinishLineTimeout = 16.0f;"),
    M("g-t-cops", "AIActionPullOverStoppedByCopsTimeout = 3.0f;",
      "AIActionPullOverStoppedByCopsTimeout = 4.0f;"),
    M("g-friction", "AIDriverFrictionBoost = 1.0f;",
      "AIDriverFrictionBoost = 1.5f;"),

    # -- the constants ----------------------------------------------------------
    M("k-progress", "AID_PROGRESS_SECONDS 1.5f", "AID_PROGRESS_SECONDS 1.25f"),
    M("k-notavoid", "AID_NOT_AVOID_SECONDS 1.0f",
      "AID_NOT_AVOID_SECONDS 1.0001f"),
    M("k-unstuck", "AID_UNSTUCK_WAIT      6.0f", "AID_UNSTUCK_WAIT      6.0003f"),
    M("k-tick", "AID_TICKS_TO_SECONDS 0.000250000012f",
      "AID_TICKS_TO_SECONDS 0.00026f"),
    M("k-progress-low", "AID_VERY_STUCK_PROGRESS 0.200000003f",
      "AID_VERY_STUCK_PROGRESS 0.21f"),
    M("k-very-stuck", "AID_VERY_STUCK_LIFETIME 1.60000002f",
      "AID_VERY_STUCK_LIFETIME 1.7f"),
    M("k-no-lifetime", "AID_NO_LIFETIME (-1.0f)", "AID_NO_LIFETIME (-2.0f)"),
    M("k-pot", "AID_PULL_OVER_TIMEOUT 10000000.0f",
      "AID_PULL_OVER_TIMEOUT 1000000.0f"),
    M("k-careful", "AID_CAREFUL_SKILL (-2)", "AID_CAREFUL_SKILL (-3)"),
    M("k-slots", "AID_PROGRESS_SLOTS 5", "AID_PROGRESS_SLOTS 6"),
    M("k-pool", "AID_POOL           CAR_MEMORY_POOL", "AID_POOL           0"),

    # -- the helpers ------------------------------------------------------------
    M("ss-signed", "(float)(int32_t)((uint32_t)WorldTimer - t->PackedTime)",
      "(float)((uint32_t)WorldTimer - t->PackedTime)"),
    M("ss-order", "(uint32_t)WorldTimer - t->PackedTime",
      "t->PackedTime - (uint32_t)WorldTimer"),
    M("cac-clamp", "+ (ptrdiff_t)sizeof(SkillLevelEntry) * skill",
      "+ (ptrdiff_t)sizeof(SkillLevelEntry) * (skill < 0 ? 0 : skill)"),
    M("cac-field", "+ offsetof(SkillLevelEntry, CollisionAvoidanceChance));",
      "+ offsetof(SkillLevelEntry, CollisionAvoidanceChance) + 4);"),

    # -- the constructor --------------------------------------------------------
    M("ni-zero724", "    aicarcontroller_init(&d->Base, car);\n"
      "    // The two Timers' constructors.\n"
      "    d->StartTimeForPurposefullyNotAvoidingCar.PackedTime = 0;\n",
      "    aicarcontroller_init(&d->Base, car);\n"
      "    // The two Timers' constructors.\n"),
    M("ni-zero728", "    d->VeryStuckProgressTimer.PackedTime = 0;\n"
      "    d->Base.Base._vtable = AIDRIVER_VTABLE;\n",
      "    d->Base.Base._vtable = AIDRIVER_VTABLE;\n"),
    M("ni-vt", "    d->Base.Base._vtable = AIDRIVER_VTABLE;\n    pd =",
      "    pd ="),
    M("ni-size", "bMalloc((int)sizeof(PsychoDriver), \"PsychoDriver\"",
      "bMalloc((int)sizeof(PsychoDriver) + 4, \"PsychoDriver\""),
    M("ni-name", "\"PsychoDriver\",\n", "\"Psycho Driver\",\n"),
    M("ni-flags", "\"PsychoDriver\",\n                                 0, AID_POOL",
      "\"PsychoDriver\",\n                                 1, AID_POOL"),
    M("ni-pd-car", "pd = psychodriver_init(pd, car);",
      "pd = psychodriver_init(pd, NULL);"),
    M("ni-action", "    d->Base.CurrentAction = NULL;\n", ""),
    M("ni-notavoid", "    d->CarToPurposefullyNotAvoid = NULL;\n"
      "    d->StartTimeForPurposefullyNotAvoidingCar.PackedTime = 0;\n"
      "    d->Base.Base.Driver",
      "    d->StartTimeForPurposefullyNotAvoidingCar.PackedTime = 0;\n"
      "    d->Base.Base.Driver"),
    M("ni-zero724b", "    d->CarToPurposefullyNotAvoid = NULL;\n"
      "    d->StartTimeForPurposefullyNotAvoidingCar.PackedTime = 0;\n",
      "    d->CarToPurposefullyNotAvoid = NULL;\n"),
    M("ni-zero724-both",
      "    d->StartTimeForPurposefullyNotAvoidingCar.PackedTime = 0;\n"
      "    d->VeryStuckProgressTimer.PackedTime = 0;\n"
      "    d->Base.Base._vtable = AIDRIVER_VTABLE;\n"
      "    pd = (PsychoDriver *)bMalloc((int)sizeof(PsychoDriver), \"PsychoDriver\",\n"
      "                                 0, AID_POOL);\n"
      "    pd = psychodriver_init(pd, car);\n"
      "    d->Base.CurrentAction = NULL;\n"
      "    d->CarToPurposefullyNotAvoid = NULL;\n"
      "    d->StartTimeForPurposefullyNotAvoidingCar.PackedTime = 0;\n",
      "    d->VeryStuckProgressTimer.PackedTime = 0;\n"
      "    d->Base.Base._vtable = AIDRIVER_VTABLE;\n"
      "    pd = (PsychoDriver *)bMalloc((int)sizeof(PsychoDriver), \"PsychoDriver\",\n"
      "                                 0, AID_POOL);\n"
      "    pd = psychodriver_init(pd, car);\n"
      "    d->Base.CurrentAction = NULL;\n"
      "    d->CarToPurposefullyNotAvoid = NULL;\n"),
    M("ni-driver", "d->Base.Base.Driver = &pd->Base;",
      "d->Base.Base.Driver = NULL;"),
    M("ni-avg-size", "bMalloc((int)sizeof(Average),",
      "bMalloc((int)sizeof(Average) + 4,"),
    M("ni-avg-name", "\"Very Stuck Progress Average\"", "\"Very Stuck Average\""),
    M("ni-avg-pool", "\"Very Stuck Progress Average\", 0, AID_POOL",
      "\"Very Stuck Progress Average\", 0, 0"),
    M("ni-avg", "d->pVeryStuckProgress = average_init(a, AID_PROGRESS_SLOTS);",
      "d->pVeryStuckProgress = average_init(a, AID_PROGRESS_SLOTS - 1);"),
    M("ni-timer", "    timer_set_time(&d->VeryStuckProgressTimer, "
      "AID_PROGRESS_SECONDS);\n    car_set", "    car_set"),
    M("ni-friction", "    car_set_friction_boost(car, AIDriverFrictionBoost);\n"
      "    return d;", "    return d;"),

    # -- the destructor ---------------------------------------------------------
    M("dd-vt", "    d->Base.Base._vtable = AIDRIVER_VTABLE;\n    drv =",
      "    drv ="),
    M("dd-drv-null", "    if (drv != NULL) {\n        const VtEntry",
      "    if (1) {\n        const VtEntry"),
    M("dd-drv-flags", "((DriverDtorFn)e->fn)(vt_this(drv, e), 3);",
      "((DriverDtorFn)e->fn)(vt_this(drv, e), 1);"),
    M("dd-avg-null", "    if (d->pVeryStuckProgress != NULL)\n",
      "    if (1)\n"),
    M("dd-avg-flags", "average_destroy(d->pVeryStuckProgress, 3);",
      "average_destroy(d->pVeryStuckProgress, 2);"),
    M("dd-flags", "aicarcontroller_destroy(&d->Base, flags);",
      "aicarcontroller_destroy(&d->Base, 0);"),
    M("dd-order", "    if (d->pVeryStuckProgress != NULL)\n"
      "        average_destroy(d->pVeryStuckProgress, 3);\n"
      "    aicarcontroller_destroy(&d->Base, flags);",
      "    aicarcontroller_destroy(&d->Base, flags);\n"
      "    if (d->pVeryStuckProgress != NULL)\n"
      "        average_destroy(d->pVeryStuckProgress, 3);"),

    # -- Think ------------------------------------------------------------------
    M("th-friction", "    car_set_friction_boost(d->Base.Base.pCar, "
      "AIDriverFrictionBoost);\n    if", "    if"),
    M("th-valid", "if (timer_is_valid(&d->VeryStuckProgressTimer)\n"
      "        && !timer_count_down",
      "if (!timer_count_down"),
    M("th-not", "&& !timer_count_down(&d->VeryStuckProgressTimer, dt)",
      "&& timer_count_down(&d->VeryStuckProgressTimer, dt)"),
    M("th-dt", "timer_count_down(&d->VeryStuckProgressTimer, dt)",
      "timer_count_down(&d->VeryStuckProgressTimer, dt * 0.5f)"),
    M("th-reset", "        timer_set_time(&d->VeryStuckProgressTimer, "
      "AID_PROGRESS_SECONDS);\n        average_record",
      "        timer_set_time(&d->VeryStuckProgressTimer, 1.0f);\n"
      "        average_record"),
    M("th-abs", "* fabsf(car->pRacingCar->dCurrentLapNumberExact)",
      "* car->pRacingCar->dCurrentLapNumberExact"),
    M("th-length", "TheTrackPathManager.TrackLength\n",
      "1.0f\n"),
    M("th-order", "    // A `j`, not through the table.\n"
      "    aicarcontroller_think(&d->Base, dt);\n}",
      "}"),
    M("th-dt-pass", "aicarcontroller_think(&d->Base, dt);",
      "aicarcontroller_think(&d->Base, 0.0f);"),

    # -- GetRouteNumbersToUse ---------------------------------------------------
    M("rn-first", "*first = 0;", "*first = 1;"),
    M("rn-last", "*last = 49;", "*last = 50;"),

    # -- ShouldWeAvoidThisCar ---------------------------------------------------
    M("sw-le", "if (AID_NOT_AVOID_SECONDS\n        <= seconds_since",
      "if (AID_NOT_AVOID_SECONDS\n        < seconds_since"),
    M("sw-forget", "        <= seconds_since(&d->StartTimeForPurposefullyNotAvoidingCar))\n"
      "        d->CarToPurposefullyNotAvoid = NULL;\n",
      "        <= seconds_since(&d->StartTimeForPurposefullyNotAvoidingCar))\n"
      "        ;\n"),
    M("sw-same", "if (car == d->CarToPurposefullyNotAvoid)\n        return 0;",
      "if (car != NULL && car == d->CarToPurposefullyNotAvoid)\n"
      "        return 0;"),
    M("sw-same-ret", "if (car == d->CarToPurposefullyNotAvoid)\n        return 0;",
      "if (car == d->CarToPurposefullyNotAvoid)\n        return 1;"),
    M("sw-range", "world_random_f(pCurrentWorld, 1.0f)",
      "world_random_f(pCurrentWorld, 2.0f)"),
    M("sw-world", "world_random_f(pCurrentWorld, 1.0f)",
      "world_random_f(NULL, 1.0f)"),
    M("sw-careful", "if (skill == AID_CAREFUL_SKILL)\n        skill = 0;",
      "if (skill < 0)\n        skill = 0;"),
    M("sw-careful-to", "if (skill == AID_CAREFUL_SKILL)\n        skill = 0;",
      "if (skill == AID_CAREFUL_SKILL)\n        skill = 1;"),
    M("sw-lt", "if (r < collision_avoidance_chance(skill))",
      "if (r <= collision_avoidance_chance(skill))"),
    M("sw-yes", "        return 1;\n    d->CarToPurposefullyNotAvoid = car;",
      "        return 0;\n    d->CarToPurposefullyNotAvoid = car;"),
    M("sw-remember", "    d->CarToPurposefullyNotAvoid = car;\n", ""),
    M("sw-stamp", "    d->StartTimeForPurposefullyNotAvoidingCar.PackedTime =\n"
      "        (uint32_t)WorldTimer;\n", ""),
    M("sw-stamp-plus", "        (uint32_t)WorldTimer;\n    return 0;",
      "        (uint32_t)WorldTimer + 1;\n    return 0;"),
    M("sw-no", "        (uint32_t)WorldTimer;\n    return 0;",
      "        (uint32_t)WorldTimer;\n    return 1;"),

    # -- the forced actions -----------------------------------------------------
    M("f-none", "if (type != AIACTION_NONE) {", "if (type < AIACTION_NONE) {"),
    M("f-draft-case", "    case AIACTION_DRAFT:\n", "    case AIACTION_BLOCK:\n"),
    M("f-draft-score", "AIActionDraftScore, AIActionDraftLifetime)",
      "AIActionPassScore, AIActionDraftLifetime)"),
    M("f-draft-life", "AIActionDraftScore, AIActionDraftLifetime)",
      "AIActionDraftScore, AIActionPassLifetime)"),
    M("f-drive-case", "    case AIACTION_JUST_DRIVE:\n",
      "    case AIACTION_NUDGE_CAR:\n"),
    M("f-drive-score", "                                 AIActionJustDriveScore,\n",
      "                                 AIActionDraftScore,\n"),
    M("f-drive-life", "                                 AIActionJustDriveLifetime)",
      "                                 AIActionPassLifetime)"),
    M("f-po-case", "    case AIACTION_PULL_OVER: {", "    case AIACTION_AVOID_ROADBLOCK: {"),
    M("f-po-timeout", "new_pull_over(d, d->Base.PullOverTimeout);",
      "new_pull_over(d, AIActionPullOverStoppedByCopsTimeout);"),
    M("f-po-reset", "        d->Base.PullOverTimeout = AID_PULL_OVER_TIMEOUT;\n", ""),
    M("f-po-order", "        AIAction *a = new_pull_over(d, d->Base.PullOverTimeout);\n\n"
      "        d->Base.PullOverTimeout = AID_PULL_OVER_TIMEOUT;\n",
      "        AIAction *a;\n\n"
      "        d->Base.PullOverTimeout = AID_PULL_OVER_TIMEOUT;\n"
      "        a = new_pull_over(d, d->Base.PullOverTimeout);\n"),
    M("f-un-case", "    case AIACTION_GET_UNSTUCK:\n",
      "    case AIACTION_I_JUST_GOT_HIT:\n"),
    M("f-un-life", "                               AIActionGetUnstuckLifetime, "
      "AID_NO_LIFETIME);",
      "                               AID_NO_LIFETIME, AID_NO_LIFETIME);"),
    M("f-un-min", "                               AIActionGetUnstuckLifetime, "
      "AID_NO_LIFETIME);",
      "                               AIActionGetUnstuckLifetime, 0.0f);"),
    M("f-un-score", "        return new_get_unstuck(AIActionGetUnstuckScore,",
      "        return new_get_unstuck(AIActionPullOverScore,"),
    M("f-rec-case", "    case AIACTION_ACCIDENT_RECOVERY:\n        return",
      "    case AIACTION_NONE + 1:\n        return"),
    M("f-rec-score", "                   AIActionAccidentRecoveryScore,\n"
      "                   AIActionAccidentRecoveryLifetime)",
      "                   AIActionPullOverScore,\n"
      "                   AIActionAccidentRecoveryLifetime)"),
    M("f-rec-life", "                   AIActionAccidentRecoveryScore,\n"
      "                   AIActionAccidentRecoveryLifetime)",
      "                   AIActionAccidentRecoveryScore,\n"
      "                   AIActionPassLifetime)"),
    M("f-default", "return new_pull_over(d, AIActionPullOverStoppedByCopsTimeout);",
      "return new_pull_over(d, AIActionPullOverCrossFinishLineTimeout);"),
    M("po-score", "                            AIActionPullOverScore, "
      "AIActionPullOverLifetime,",
      "                            AIActionAccidentRecoveryScore, "
      "AIActionPullOverLifetime,"),
    M("po-life", "                            AIActionPullOverScore, "
      "AIActionPullOverLifetime,",
      "                            AIActionPullOverScore, "
      "AIActionPassLifetime,"),
    M("po-list", "pullOverTimeout, d->Base.CurrentNearbyCarList,",
      "pullOverTimeout, NULL,"),
    M("po-loc", "                            d->Base.CurrentDrivingLocation)",
      "                            NULL)"),

    # -- the cascade's gates ----------------------------------------------------
    M("wt-type", "return type != curType && !(score < curScore);",
      "return !(score < curScore);"),
    M("wt-le", "return type != curType && !(score < curScore);",
      "return type != curType && !(score <= curScore);"),
    M("wt-score", "return type != curType && !(score < curScore);",
      "return type != curType;"),
    M("cur-score", "    int32_t curScore = -1;\n", "    int32_t curScore = 0;\n"),
    M("cur-type", "    AIActionType curType = AIACTION_NONE;\n",
      "    AIActionType curType = (AIActionType)-1;\n"),
    M("cur-read", "        curScore = c->CurrentAction->Score;\n",
      "        curScore = c->CurrentAction->Type;\n"),
    M("cur-read-type", "        curType = c->CurrentAction->Type;\n",
      "        curType = (AIActionType)c->CurrentAction->Score;\n"),
    M("ini-okay", "    okay = 1;\n", "    okay = 0;\n"),
    M("ini-avoid", "    avoidCar = NULL;\n", "    avoidCar = d->Base.Base.pCar;\n"),
    M("ini-pass", "    passCar = NULL;\n", "    passCar = d->Base.Base.pCar;\n"),
    M("ini-hit", "    hitCar = NULL;\n", "    hitCar = d->Base.Base.pCar;\n"),
    M("ini-used", "    used = 0;\n", "    used = 1;\n"),
    M("ini-secs", "    secs = 0.0f;\n", "    secs = 1.0f;\n"),
    M("ini-amount", "    amount = 0.0f;\n", "    amount = 1.0f;\n"),
    M("ini-rb", "    rb = NULL;\n", "    rb = (const tRoadBlock *)(void *)d;\n"),
    M("ini-clear", "    drivingchoice_clear(&choice);\n",
      "    memset(&choice, 0x5a, sizeof choice);\n"),

    # -- GetUnstuck -------------------------------------------------------------
    M("un-type", "if (worth_trying(AIACTION_GET_UNSTUCK, AIActionGetUnstuckScore,",
      "if (worth_trying(AIACTION_PASS, AIActionGetUnstuckScore,"),
    M("un-gscore", "if (worth_trying(AIACTION_GET_UNSTUCK, AIActionGetUnstuckScore,",
      "if (worth_trying(AIACTION_GET_UNSTUCK, AIActionPullOverScore,"),
    M("un-wait", "        && AID_UNSTUCK_WAIT\n               < seconds_since",
      "        && AID_UNSTUCK_WAIT\n               <= seconds_since"),
    M("un-wait-gone", "        && AID_UNSTUCK_WAIT\n"
      "               < seconds_since(&c->LastTimeNonGetUnstuckActionWasCalled)) {",
      ") {"),
    M("un-ge", "        s = aigetunstuck_calculate_score(info);\n        if (s >= 0) {",
      "        s = aigetunstuck_calculate_score(info);\n        if (s > 0) {"),
    M("un-life", "            *out = new_get_unstuck(s, AIActionGetUnstuckLifetime,",
      "            *out = new_get_unstuck(s, AID_NO_LIFETIME,"),
    M("un-min", "                                   minLifetime);",
      "                                   AID_NO_LIFETIME);"),
    M("un-stamp", "            c->LastTimeNonGetUnstuckActionWasCalled.PackedTime =\n"
      "                (uint32_t)WorldTimer;\n", ""),
    M("ml-oob", "if (!(0.0f < ((OutOfBoundsFn)e->fn)(vt_this(b, e))))",
      "if (!(0.0f <= ((OutOfBoundsFn)e->fn)(vt_this(b, e))))"),
    M("ml-slot", "CARCONTROLLER_VT_GET_AMOUNT_OUT_OF_BOUNDS);",
      "CARCONTROLLER_VT_FIND_WHERE_I_AM);"),
    M("ml-full", "if (a->nSamples == a->nSlots && a->fAverage",
      "if (a->nSamples >= a->nSlots && a->fAverage"),
    M("ml-full-gone", "if (a->nSamples == a->nSlots && a->fAverage",
      "if (a->fAverage"),
    M("ml-lt", "a->fAverage < AID_VERY_STUCK_PROGRESS)",
      "a->fAverage <= AID_VERY_STUCK_PROGRESS)"),
    M("ml-yes", "        return AID_VERY_STUCK_LIFETIME;\n",
      "        return AID_NO_LIFETIME;\n"),

    # -- AvoidRoadBlock and IJustGotHit -----------------------------------------
    M("rb-type", "if (worth_trying(AIACTION_AVOID_ROADBLOCK, AIActionAvoidRoadBlockScore,",
      "if (worth_trying(AIACTION_GET_UNSTUCK, AIActionAvoidRoadBlockScore,"),
    M("rb-gscore", "if (worth_trying(AIACTION_AVOID_ROADBLOCK, AIActionAvoidRoadBlockScore,",
      "if (worth_trying(AIACTION_AVOID_ROADBLOCK, AIActionPassScore,"),
    M("rb-ge", "        s = aiavoidroadblock_calculate_score(info, &rb);\n"
      "        if (s >= 0) {",
      "        s = aiavoidroadblock_calculate_score(info, &rb);\n"
      "        if (s > 0) {"),
    M("rb-life", "                       AID_NO_LIFETIME, rb)->Base;",
      "                       AIActionPassLifetime, rb)->Base;"),
    M("rb-arg", "                       AID_NO_LIFETIME, rb)->Base;",
      "                       AID_NO_LIFETIME, NULL)->Base;"),
    M("hit-type", "if (worth_trying(AIACTION_I_JUST_GOT_HIT, AIActionIJustGotHitScore,",
      "if (worth_trying(AIACTION_AVOID_CARS, AIActionIJustGotHitScore,"),
    M("hit-gscore", "if (worth_trying(AIACTION_I_JUST_GOT_HIT, AIActionIJustGotHitScore,",
      "if (worth_trying(AIACTION_I_JUST_GOT_HIT, AIActionPassScore,"),
    M("hit-ge", "        s = aijustgothit_calculate_score(info, &hitCar);\n"
      "        if (s >= 0) {",
      "        s = aijustgothit_calculate_score(info, &hitCar);\n"
      "        if (s > 0) {"),
    M("hit-honk", "            aicarcontroller_maybe_honk_and_or_blink_headlights(\n"
      "                c, hitCar, c->CurrentNearbyCarList);\n"
      "            *out = &aijustgothit_init", "            *out = &aijustgothit_init"),
    M("hit-honk-list", "                c, hitCar, c->CurrentNearbyCarList);",
      "                c, hitCar, NULL);"),
    M("hit-life", "                                      s, AID_NO_LIFETIME, hitCar)",
      "                                      s, AIActionPassLifetime, hitCar)"),
    M("hit-arg", "                                      s, AID_NO_LIFETIME, hitCar)",
      "                                      s, AID_NO_LIFETIME, NULL)"),

    # -- AvoidCars --------------------------------------------------------------
    M("av-type", "if (worth_trying(AIACTION_AVOID_CARS, AIActionAvoidCarsScore,",
      "if (worth_trying(AIACTION_PASS, AIActionAvoidCarsScore,"),
    M("av-gscore", "if (worth_trying(AIACTION_AVOID_CARS, AIActionAvoidCarsScore,",
      "if (worth_trying(AIACTION_AVOID_CARS, AIActionPullOverScore,"),
    M("av-ge", "                                        &okay, &used);\n"
      "        if (s >= 0) {",
      "                                        &okay, &used);\n"
      "        if (s > 0) {"),
    M("av-honk", "            aicarcontroller_maybe_honk_and_or_blink_headlights(\n"
      "                c, avoidCar, c->CurrentNearbyCarList);\n", ""),
    M("av-honk-car", "                c, avoidCar, c->CurrentNearbyCarList);",
      "                c, passCar, c->CurrentNearbyCarList);"),
    M("av-should", "if (aidriver_should_we_avoid_this_car(d, avoidCar, secs)) {",
      "if (1) {"),
    M("av-should-car", "if (aidriver_should_we_avoid_this_car(d, avoidCar, secs)) {",
      "if (aidriver_should_we_avoid_this_car(d, passCar, secs)) {"),
    M("av-choice", "                info->MyDrivingChoice = choice;\n"
      "                // Retail's", "                // Retail's"),
    M("av-unsigned", "(float)(uint32_t)okay, used, 0)",
      "(float)okay, used, 0)"),
    M("av-secs", "(float)(uint32_t)okay, used, 0)", "secs, used, 0)"),
    M("av-okay", "(float)(uint32_t)okay, used, 0)",
      "(float)(uint32_t)okay, okay, 0)"),
    M("av-used", "(float)(uint32_t)okay, used, 0)",
      "(float)(uint32_t)okay, used, used)"),
    M("av-life", "                           AIActionAvoidCarsLifetime, avoidCar,",
      "                           AIActionPassLifetime, avoidCar,"),
    M("av-car", "                           AIActionAvoidCarsLifetime, avoidCar,",
      "                           AIActionAvoidCarsLifetime, NULL,"),

    # -- AccidentRecovery, Pass and JustDrive -----------------------------------
    M("ar-type", "if (worth_trying(AIACTION_ACCIDENT_RECOVERY,",
      "if (worth_trying(AIACTION_I_JUST_GOT_HIT,"),
    M("ar-gscore", "                     AIActionAccidentRecoveryScore, curType, "
      "curScore)) {",
      "                     AIActionPullOverScore, curType, curScore)) {"),
    M("ar-ge", "        s = aiaccidentrecovery_calculate_score(info);\n"
      "        if (s >= 0) {",
      "        s = aiaccidentrecovery_calculate_score(info);\n"
      "        if (s > 0) {"),
    M("ar-life", "                       AID_NO_LIFETIME)->Base;\n"
      "            return;\n        }\n    }\n\n    if (worth_trying(AIACTION_PASS",
      "                       AIActionPassLifetime)->Base;\n"
      "            return;\n        }\n    }\n\n    if (worth_trying(AIACTION_PASS"),
    M("pa-type", "if (worth_trying(AIACTION_PASS, AIActionPassScore,",
      "if (worth_trying(AIACTION_DRAFT, AIActionPassScore,"),
    M("pa-gscore", "if (worth_trying(AIACTION_PASS, AIActionPassScore,",
      "if (worth_trying(AIACTION_PASS, AIActionDraftScore,"),
    M("pa-ge", "        if (s >= 0\n            && aidriver_should",
      "        if (s > 0\n            && aidriver_should"),
    M("pa-order", "        if (s >= 0\n            && aidriver_should_we_avoid_this_car"
      "(d, passCar,\n                                                 AID_NO_LIFETIME)) {",
      "        if (aidriver_should_we_avoid_this_car(d, passCar, AID_NO_LIFETIME)\n"
      "            && s >= 0) {"),
    M("pa-should-car", "            && aidriver_should_we_avoid_this_car(d, passCar,",
      "            && aidriver_should_we_avoid_this_car(d, avoidCar,"),
    M("pa-secs", "            && aidriver_should_we_avoid_this_car(d, passCar,\n"
      "                                                 AID_NO_LIFETIME)) {",
      "            && aidriver_should_we_avoid_this_car(d, passCar,\n"
      "                                                 0.0f)) {"),
    M("pa-choice", "            info->MyDrivingChoice = choice;\n"
      "            *out = &aipass_init", "            *out = &aipass_init"),
    M("pa-life", "                                AIActionPassLifetime, passCar, amount)",
      "                                AIActionAvoidCarsLifetime, passCar, amount)"),
    M("pa-car", "                                AIActionPassLifetime, passCar, amount)",
      "                                AIActionPassLifetime, avoidCar, amount)"),
    M("pa-amount", "                                AIActionPassLifetime, passCar, amount)",
      "                                AIActionPassLifetime, passCar, 0.0f)"),
    M("jd-ge", "    s = aijustdrive_calculate_score(info);\n    if (s >= 0)",
      "    s = aijustdrive_calculate_score(info);\n    if (s > 0)"),
    M("jd-life", "        *out = &aijustdrive_init((AIActionJustDrive *)aiaction_new(), s,\n"
      "                                 AID_NO_LIFETIME)->Base;",
      "        *out = &aijustdrive_init((AIActionJustDrive *)aiaction_new(), s,\n"
      "                                 AIActionJustDriveLifetime)->Base;"),

    # -- the table --------------------------------------------------------------
    M("vt-dtor", "E(aidriver_destroy),", "E(aicarcontroller_destroy),"),
    M("vt-debug", "E(aicarcontroller_debug_display),", "{ 0, 0, NULL },"),
    M("vt-snap", "E(aidriver_do_snapshot),",
      "E(aicarcontroller_do_snapshot),"),
    M("vt-think", "E(aidriver_think),", "E(aicarcontroller_think),"),
    M("vt-oob", "E(aicarcontroller_get_amount_out_of_bounds),",
      "E(aicarcontroller_find_where_i_am),"),
    M("vt-routes", "E(aidriver_get_route_numbers_to_use),", "{ 0, 0, NULL },"),
    M("vt-choose", "E(aidriver_choose_new_action),", "{ 0, 0, NULL },"),
    M("vt-gen", "E(aicarcontroller_generate_points_to_fulfill_action),",
      "{ 0, 0, NULL },"),
]

EQUIVALENT = {
    "ni-zero724": "the constructor zeroes StartTimeForPurposefullyNotAvoidingCar "
                  "again before anything reads it",
    "ni-zero724b": "the constructor's first zeroing has left "
                   "StartTimeForPurposefullyNotAvoidingCar 0 "
                   "(ni-zero724-both drops the two)",
    "ni-zero728": "timer_set_time sets VeryStuckProgressTimer before anything "
                  "reads it",
    "cur-score": "every score global is over 0, so no gate's score is below "
                 "either",
    "cur-type": "no action the cascade tries has type -1 or 11",
    "un-wait": "no whole number of ticks is 6 s exactly: 23999 are 5.99975 "
               "and 24000 6.0000005",
    "pa-secs": "ShouldWeAvoidThisCar does not read its seconds",
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
        todo, SOURCES, "aidriver_test",
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
