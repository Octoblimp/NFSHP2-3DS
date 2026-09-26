#!/usr/bin/env python3
"""Cross-check 3DS Files/source/worldstep.c against the image's World.obj.

What is checked: the clock, the pause and the time scale (SetTimeScale,
ResetTimeScale, SetWorldPaused, Begin- and EndPause, UpdateWorldPaused,
IsWorldPaused, GetTimestep); the car table (BuildCarTable, GetCarByNumber,
GetCarByDriverNumber, CarListCheckFlip, bTList<Car>::Sort, which is
bList::Sort, AddTrafficCar); the two Random overloads,
GetDATToClosestPlayer, FlushCollisions; the checksums (Calculate- and
VerifyDebugChecksums); and the step, DoTimestepMove, DoTimestepCollisions
and DoTimestep. World's GetDistanceToClosestPlayer, which the step calls,
runs from world.c. The image is the oracle. tools/mipsemu.py runs the
functions out of NFSHP2.ELF, the harness (tools/src/world_test.c) runs the
port, both walk the same script, and the two transcripts are diffed.

Everything the step calls outside World.obj is a stub on both sides that
logs, with the same simple semantics on both: the Car methods; the
collision system's (a witness's destroy and a collision's End unlink it,
TestForContact and MaybeCreateWitnesses append what the script queued
unless it is on the list already,
RemoveContacts unlinks every contact on a body, Break writes the pieces the
script queued); the replay's and the Joylog's data; CompareDistances, which
answers from a queue; bGetTicker, which does too; and the seams. The
image's bRandom, GetRealTimeElapsedFromQuantized, bGetTickerDifference,
IsReplayDemoMode, bList::Sort and ~bTList<Contact> run as themselves.

What the listing says that is easy to get wrong, and which the script
reaches:

  * GetTimestep reads pReplayManager twice; the wait's 0.3 cap is
    `min.s 0.3, max(x, 0)`, and the wait compares the ticker's
    milliseconds times 0.001.
  * The time scale's callback is cleared after it runs; the pause's too.
    The pause counts down by RealTimeElapsed, the time scale by the step.
  * The car table is players, AI racers, cops and super cops, traffic,
    each in list order; a car with no known type is left out.
  * DoTimestep thinks AI racers, traffic, players, cops, and reads the
    counts again after every car. A player with no player object gets
    9999999 in three lanes and its fourth left alone.
  * The shake test is evaluated before the loop and again before each
    car's rumble.
  * DoTimestepCollisions resolves at most 20 rounds and then destroys what
    is left; a witness is tested once for each piece it has on it.
  * VerifyDebugChecksums posts RC_SKIP_REPLAY only while replaying, only
    when not capturing, and only on a mismatch of the low byte.

    python tools/world_check.py
    python tools/world_check.py --mutate
    python tools/world_check.py --dump out/world
"""
import argparse
import difflib
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import mipsemu as me

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)
M32 = 0xFFFFFFFF

SOURCES = [
    "tools/src/world_test.c",
    "3DS Files/source/worldstep.c",
    "3DS Files/source/world.c",
    "3DS Files/source/blist.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
    "3DS Files/source/bticker.c",
    "3DS Files/source/realtime.c",
    "3DS Files/source/timer.c",
    "3DS Files/source/joylog.c",
    "3DS Files/source/replay.c",
    "3DS Files/source/p32.c",
    "3DS Files/source/player.c",
    "3DS Files/source/race.c",
    "3DS Files/source/vtable.c",
]

WS = "3DS Files/source/worldstep.c"
BL = "3DS Files/source/blist.c"

GP = 0x00328bf0
G_WORLD = GP - 22624                # pCurrentWorld
G_TWEAK = GP - 22620                # TweakerPauseWorld
G_RC = GP - 22720                   # pRaceCoordinator
G_RACE = GP - 22776                 # pCurrentRace
G_RM = GP - 23008                   # pReplayManager
G_JREPLAY = GP - 21256              # Joylog::ReplayingFlag
G_PLAYERS = GP - 21536              # PlayerPlayersByNumber
G_TIMER = GP - 20224                # WorldTimer
G_LOOP = GP - 20200                 # WorldLoopCounter
G_RTE = GP - 20244                  # RealTimeElapsed
G_RTEQ = GP - 20240                 # RealTimeElapsedQuantized
G_BODIES = GP - 18392               # CollisionBodyList
G_WITS = GP - 18352                 # CollisionBodyWitnessList
TPM = 0x00313768                    # TheTrackPathManager
FX = 0x002e7780                     # WorldEffects

NCAR, NB, NW, NK, NC = 14, 8, 8, 12, 4
DELTA = 8
FN_MOVE, FN_CB = 0x01F00000, 0x01F00010

FN = dict(
    build=0x0014ab08, bynum=0x0014acd8, bydrv=0x0014ada0, flip=0x0014adc8,
    scale=0x0014adf0, reset=0x0014ae08, pause=0x0014ae28, begin=0x0014ae38,
    end=0x0014ae40, updpause=0x0014ae48, ispaused=0x0014aeb0,
    timestep=0x0014aee8, move=0x0014b050, collide=0x0014b110,
    step=0x0014b480, csum=0x0014b9e0, verify=0x0014ba88, dat=0x0014bc18,
    randi=0x0014bc98, randf=0x0014bcc0, flush=0x0014bce0,
    traffic=0x0014bce8, sort=0x0014c030,
)

(OP_TAG, OP_CAR, OP_CARLIST, OP_PLAYER, OP_BUILD, OP_BYNUM, OP_BYDRV,
 OP_FLIP, OP_SORT, OP_TRAFFIC, OP_SCALE, OP_RESET, OP_PAUSE, OP_BEGIN,
 OP_END, OP_UPDPAUSE, OP_ISPAUSED, OP_TWEAK, OP_REALTIME, OP_REPLAY,
 OP_RGET, OP_JGET, OP_JFLAG, OP_TICKS, OP_TIMESTEP, OP_SEED, OP_RANDI,
 OP_RANDF, OP_DATS, OP_CMPQ, OP_DAT, OP_TIMER, OP_CHECKSUM, OP_VERIFY,
 OP_LOOP, OP_BODY, OP_BODYLIST, OP_MOVE, OP_WIT, OP_WITLIST, OP_CREATEQ,
 OP_CONTACT, OP_TESTQ, OP_BREAKQ, OP_COL, OP_COLLIST, OP_COLLIDE,
 OP_STATE, OP_RC, OP_PTRS, OP_STEP, OP_FLUSH, OP_PPOS,
 OP_DRAIN, OP_SHAKEFLIP) = range(1, 56)

bits = me.f_to_bits
NAN = 0x7FC00000
INF = 0x7F800000
NINF = 0xFF800000


def s32(x):
    x &= M32
    return x - (1 << 32) if x & 0x80000000 else x


def s16(x):
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


def fw(v):
    """A float operand: bits as given, or a Python float's."""
    return v if isinstance(v, int) else bits(v)


# ---------------------------------------------------------------- the script


class Script(object):
    def __init__(self):
        self.words = []
        self.tags = []

    def op(self, code, *args):
        self.words.append(code)
        self.words.extend(a & M32 for a in args)

    def tag(self, name):
        """A new scenario, with every queue emptied."""
        self.op(OP_TAG, len(self.tags))
        self.op(OP_DRAIN)
        self.tags.append(name)

    def car(self, k, typ, dn, pos=(0.0, 0.0, 0.0, 0.0), dat=0.0, csum=0,
            vfx=1):
        pos = list(pos) + [0.0] * (4 - len(pos))
        self.op(OP_CAR, k, typ, dn, *([fw(v) for v in pos]
                                      + [fw(dat), csum, vfx]))

    def carlist(self, ks):
        self.op(OP_CARLIST, len(ks), *ks)

    def bodylist(self, ks):
        self.op(OP_BODYLIST, len(ks), *ks)

    def witlist(self, ks):
        self.op(OP_WITLIST, len(ks), *ks)

    def collist(self, ks):
        self.op(OP_COLLIST, len(ks), *ks)

    def ticks(self, ts):
        self.op(OP_TICKS, len(ts), *ts)

    def breakq(self, bs):
        self.op(OP_BREAKQ, len(bs), *bs)

    def scale(self, s, t, cb, param):
        self.op(OP_SCALE, fw(s), fw(t), cb, param)

    def pause(self, t, cb, param):
        self.op(OP_PAUSE, fw(t), cb, param)

    def realtime(self, e, q):
        self.op(OP_REALTIME, fw(e), q)

    def ppos(self, i, v, dat):
        v = list(v) + [0.0] * (4 - len(v))
        self.op(OP_PPOS, i, *([fw(x) for x in v] + [fw(dat)]))

    def body(self, k, typ, dyn, act, strength=0.0):
        self.op(OP_BODY, k, typ & 0xFF, dyn & 0xFF, act & 0xFF, fw(strength))


FAR = 9999999.0
Q = 1.0 / 3600


def time_script(sc):
    sc.tag("the time scale and the pause")
    sc.op(OP_STATE)
    sc.scale(0.5, 2.0, 1, 7)
    sc.op(OP_RESET)
    sc.scale(0.25, 0.1, 0, 3)
    sc.pause(1.5, 1, 9)
    sc.op(OP_ISPAUSED)
    sc.op(OP_BEGIN)
    sc.op(OP_END)
    for e in (0.5, 0.5, 0.25, 0.25, 0.25, 0.25):
        sc.realtime(e, 0)
        sc.op(OP_UPDPAUSE)
        sc.op(OP_ISPAUSED)
    sc.op(OP_TWEAK, 1)
    sc.op(OP_ISPAUSED)
    sc.op(OP_TWEAK, 0)
    sc.pause(0.5, 0, 4)
    sc.realtime(0.5, 0)
    sc.op(OP_UPDPAUSE)                  # exactly to 0, and no callback
    sc.op(OP_ISPAUSED)
    for t in (-1.0, 0.0, -0.0, 1e-30, NAN, INF, 0.1):
        sc.pause(t, 1, 5)
        sc.op(OP_ISPAUSED)
        sc.realtime(0.1, 0)
        sc.op(OP_UPDPAUSE)
        sc.op(OP_ISPAUSED)
    sc.realtime(NAN, 0)
    sc.pause(1.0, 1, 6)
    sc.op(OP_UPDPAUSE)                  # 1 - NaN is not <= 0
    sc.realtime(-2.0, 0)
    sc.op(OP_UPDPAUSE)
    sc.op(OP_RESET)

    sc.tag("the timestep, no replay")
    sc.op(OP_REPLAY, 0, 0)
    for q in (0, 1, 60, 61, 120, 3600, -5, 0x7FFFFFFF):
        sc.realtime(q * Q, q)
        sc.op(OP_TIMESTEP)
    sc.scale(0.5, 0.05, 1, 11)
    for _ in range(5):
        sc.realtime(60 * Q, 60)
        sc.op(OP_TIMESTEP)
    sc.scale(2.0, 1.0 / 60, 1, 12)     # a timer the step takes to 0 or less
    sc.realtime(60 * Q, 60)
    sc.op(OP_TIMESTEP)
    sc.scale(3.0, 0.0, 1, 13)           # no timer: the scale stays
    sc.op(OP_TIMESTEP)
    sc.scale(3.0, -1.0, 1, 13)
    sc.op(OP_TIMESTEP)
    sc.scale(0.1, NAN, 0, 13)
    sc.op(OP_TIMESTEP)
    sc.scale(0.1, 0.02, 0, 14)          # runs out with no callback
    sc.op(OP_TIMESTEP)
    sc.op(OP_TIMESTEP)
    sc.op(OP_RESET)

    sc.tag("the timestep, capturing")
    sc.op(OP_REPLAY, 0, 1)
    for q in (60, 59, 0, 200):
        sc.realtime(q * Q, q)
        sc.op(OP_TIMESTEP)

    sc.tag("the timestep, replaying")
    sc.op(OP_REPLAY, 1, 1)
    sc.realtime(60 * Q, 60)
    for q, ts in ((60, []), (61, [1000, 1000, 2000, 400000, 800000]),
                  (90, [0, 294912 * 5, 294912 * 50]),
                  (1200, [0x10, 0x20, 0x30] + [0x10 + 294912 * k
                                               for k in range(1, 400, 37)]),
                  (30, []), (0, []), (61, [0xFFFFFF00, 0x00001000,
                                          0x40000000])):
        sc.op(OP_RGET, q)
        sc.ticks(ts)
        sc.op(OP_TIMESTEP)
    sc.realtime(1200 * Q, 1200)
    sc.op(OP_RGET, 60)
    sc.op(OP_TIMESTEP)                  # negative waste
    sc.op(OP_RGET, 60)
    sc.op(OP_TIMESTEP)
    sc.realtime(0.0, 0)
    sc.op(OP_RGET, 7200)
    sc.ticks([5, 5 + 294912 * 100])
    sc.op(OP_TIMESTEP)                  # capped at 0.3
    # 89,999,996 to 90,000,011 ticks are 0.3f to the bit: the spin stops on
    # reaching the wait, not on passing it.
    sc.op(OP_RGET, 7200)
    sc.ticks([7, 7 + 89999995, 7 + 90000000, 7 + 90000100])
    sc.op(OP_TIMESTEP)
    # A NaN clock: max.s keeps the NaN, min.s drops it, and the wait is 0.3.
    sc.realtime(NAN, 0)
    sc.op(OP_RGET, 60)
    sc.ticks([9, 9 + 294912 * 400])
    sc.op(OP_TIMESTEP)
    sc.realtime(0.0, 0)
    sc.op(OP_REPLAY, 1, 0)
    sc.scale(0.5, 1.0, 1, 21)
    for q in (30, 45, 600, 3600):
        sc.op(OP_RGET, q)
        sc.ticks([100, 100 + 294912 * 400])
        sc.op(OP_TIMESTEP)
    sc.op(OP_REPLAY, 0, 0)
    sc.op(OP_RESET)


def random_script(sc):
    sc.tag("random")
    for seed in (0, 1, 0x12345678, 0xFFFFFFFF, 0x1D872B41):
        sc.op(OP_SEED, seed)
        for r in (1, 2, 3, 10, 100, 0x7FFFFFFF, -1, -100, 0x80000000):
            sc.op(OP_RANDI, r)
        for f in (1.0, 0.5, 100.0, -3.0, 0.0, 1e30):
            sc.op(OP_RANDF, fw(f))

    sc.tag("the DAT to the nearer player")
    sc.op(OP_DATS, fw(10.0), fw(-20.0))
    for a, b in ((5.0, 6.0), (6.0, 5.0), (-5.0, 5.0), (5.0, -5.0),
                 (-7.0, -7.0), (0.0, -0.0), (-0.0, 0.0), (NAN, 1.0),
                 (1.0, NAN), (INF, 1e30), (NINF, -1e30), (1e-40, -1e-41)):
        sc.op(OP_CMPQ, fw(a))
        sc.op(OP_CMPQ, fw(b))
        sc.op(OP_DAT, fw(123.5))
    sc.op(OP_DAT, fw(-1.0))             # both from an empty queue


def cars_script(sc):
    sc.tag("the car table")
    types = [1, 3, 2, 4, 5, 3, 1, 2, 0, 4, 3, 6, 2, 3]
    for k in range(NCAR):
        sc.car(k, types[k], 100 + k, (float(k), 0.0, 0.0), 0.0, k * 3)
    sc.carlist([])
    sc.op(OP_BUILD)
    sc.carlist([0, 1, 2, 3, 4, 5, 6, 7])
    sc.op(OP_BUILD)
    sc.carlist([7, 6, 5, 4, 3, 2, 1, 0, 8, 9, 10, 11, 12, 13])
    sc.op(OP_BUILD)
    sc.carlist([3, 4, 9])
    sc.op(OP_BUILD)
    sc.carlist([1, 5, 10, 13])
    sc.op(OP_BUILD)
    sc.carlist([8, 11])
    sc.op(OP_BUILD)
    sc.carlist([13, 12, 10, 9, 7, 6, 5, 4, 3, 2, 1, 0])
    sc.op(OP_BUILD)
    for n in (100, 106, 113, 108, 111, 99, 0, -1, 114):
        sc.op(OP_BYNUM, n)
        sc.op(OP_BYDRV, n)
    sc.car(4, 5, 106, (4.0, 0.0, 0.0))  # two cars with 106: the first
    sc.op(OP_BYNUM, 106)
    sc.car(0, 1, -3 & 0xFFFF, (0.0, 0.0, 0.0))
    sc.op(OP_BYNUM, -3)
    sc.op(OP_BYNUM, 0xFFFD)

    sc.tag("flip and sort")
    for x0, x1 in ((0.0, 1.0), (1.0, 0.0), (1.0, 1.0), (-0.0, 0.0),
                   (NAN, 0.0), (0.0, NAN), (INF, INF)):
        sc.car(0, 1, 100, (x0, 5.0, 5.0))
        sc.car(1, 3, 101, (x1, -5.0, 5.0))
        sc.op(OP_FLIP, 0, 1)
    rnd = random.Random(260926)
    for n in (0, 1, 2, 3, 5, 8, 14):
        ks = list(range(NCAR))
        rnd.shuffle(ks)
        ks = ks[:n]
        for k in ks:
            sc.car(k, types[k], 100 + k,
                   (float(rnd.choice([rnd.randrange(-5, 5), 0, 1])),
                    rnd.uniform(-9, 9), 0.0))
        sc.carlist(ks)
        sc.op(OP_SORT)

    sc.tag("add a traffic car")
    sc.carlist([0, 1])
    sc.op(OP_PTRS, 1, 0, 0)
    sc.op(OP_TRAFFIC, 5, 0xFFFFFFFF)    # no car
    sc.op(OP_TRAFFIC, 6, 2)
    sc.op(OP_TRAFFIC, 7, 3)
    sc.carlist([])
    sc.op(OP_TRAFFIC, 8, 4)
    sc.op(OP_PTRS, 0, 0, 0)


def checksum_script(sc):
    sc.tag("the checksums")
    types = [1, 2, 2, 3, 4]
    for k in range(5):
        sc.car(k, types[k], 200 + k,
               (k * 1.5, -k * 2.5, 3.0 + k, 0.25 * k), 0.0,
               [0x1234, 0xFFFF, 0, 0xABCD, 0x7FFFFFFF][k])
    sc.carlist([4, 3, 2, 1, 0])
    sc.op(OP_BUILD)
    for t in (0, 1, 4000, 0xFFFFFFFF, 0x12345678):
        sc.op(OP_TIMER, t)
        sc.op(OP_CHECKSUM)
    sc.carlist([])
    sc.op(OP_BUILD)
    sc.op(OP_CHECKSUM)
    sc.carlist([0, 1, 2, 3, 4])
    sc.op(OP_BUILD)
    sc.car(3, 3, 203, (1.0, 2.0, 3.0, 4.0), 0.0, 0x80000000)
    sc.op(OP_CHECKSUM)

    for seed in (0, 0x55, 0x1FF):
        sc.op(OP_SEED, seed)
        for jr in (0, 1):
            sc.op(OP_JFLAG, jr)
            for rep, cap in ((0, 0), (0, 1), (1, 1), (1, 0)):
                sc.op(OP_REPLAY, rep, cap)
                sc.op(OP_JGET, 0xBEEF)
                sc.op(OP_VERIFY)
                # the byte the replay recorded: once right, once wrong
                sc.op(OP_RGET, 0)
                sc.op(OP_VERIFY)
    sc.op(OP_REPLAY, 1, 0)
    sc.op(OP_JFLAG, 0)
    for t in range(8):
        sc.op(OP_TIMER, 1000 + t * 37)
        for v in (0, 0x100, 0x1FF, 0xFFFFFF00, 0x55, 0xAA, 0x3C):
            sc.op(OP_RGET, v)
            sc.op(OP_VERIFY)
    # The right byte with junk above it: only the low eight bits are read.
    # (The loops above leave readings queued that nothing took.)
    b = debug_byte(1000, [0x1234, 0xFFFF, 0, 0x7FFFFFFF, 0x80000000], 0x1FF)
    sc.op(OP_DRAIN)
    sc.op(OP_TIMER, 1000)
    for v in (0x100 | b, 0xFFFFFF00 | b, 0x100 | (b ^ 1)):
        sc.op(OP_RGET, v)
        sc.op(OP_VERIFY)
    sc.op(OP_REPLAY, 0, 0)


def debug_byte(timer, csums, seed):
    """VerifyDebugChecksums' byte, for the cars in table order."""
    s = timer & M32
    for v in csums:
        s = (s * 33 + v) & M32
    c = ((s >> 16) + s) & 0xFFFF
    return ((c >> 8) + c + (seed & 0xFF)) & 0xFF


def bodies_script(sc):
    sc.tag("moving the bodies")
    for k in range(NB):
        sc.body(k, 0, k % 3 != 1, 1)
    sc.bodylist([])
    sc.op(OP_LOOP, 0)
    sc.op(OP_MOVE, fw(1.0 / 60))
    sc.bodylist([0, 1, 2, 3, 4, 5, 6, 7])
    for n in (0, 50, 51, 52, 115, 179, 0x7FFFFFFF, -77, -78, 100000, 99923,
              0x80000033, 0xFFFFFFB3):
        sc.op(OP_LOOP, n)
        sc.op(OP_MOVE, fw(1.0 / 60))
    sc.body(3, 0, 0x80, 0)
    sc.body(4, 1, 0xFF, 1)
    sc.bodylist([7, 3, 1, 4])
    sc.op(OP_MOVE, fw(-0.5))


def collide_script(sc):
    sc.tag("collisions, quiet")
    for k in range(NB):
        sc.body(k, 0, 1, 1)
    sc.bodylist([0, 1, 2, 3])
    sc.witlist([])
    sc.collist([])
    sc.op(OP_COLLIDE, fw(1.0 / 60))

    sc.tag("witnesses expire and are made")
    for k in range(NW):
        sc.op(OP_WIT, k, k % 4, (k + 1) % 4, k % 3 == 0)
    sc.witlist([0, 1, 2, 3, 4])
    sc.op(OP_CREATEQ, 5)
    sc.op(OP_CREATEQ, 0xFFFFFFFF)
    sc.op(OP_CREATEQ, 6)
    sc.body(1, 0, 1, 0)                 # dynamic but not active
    sc.body(2, 0, 0, 1)                 # active but not dynamic
    sc.op(OP_COLLIDE, fw(1.0 / 60))
    sc.body(1, 0, 1, 1)
    sc.body(2, 0, 1, 1)

    sc.tag("one contact")
    for k in range(NW):
        sc.op(OP_WIT, k, k % 4, (k + 1) % 4, 0)
    sc.witlist([0, 1, 2])
    sc.op(OP_CONTACT, 0, 0, 1)
    sc.op(OP_TESTQ, 0)
    sc.op(OP_COLLIDE, fw(1.0 / 60))

    sc.tag("contacts, earliest first, and their pieces tested again")
    sc.witlist([0, 1, 2, 3])
    sc.op(OP_CONTACT, 0, 0, 1)
    sc.op(OP_CONTACT, 1, 1, 2)
    sc.op(OP_CONTACT, 2, 2, 3)
    sc.op(OP_CONTACT, 3, 3, 0)
    sc.op(OP_CONTACT, 4, 1, 2)
    for k in (0, 0xFFFFFFFF, 1, 2):
        sc.op(OP_TESTQ, k)
    for k in (3, 0xFFFFFFFF, 4, 0xFFFFFFFF, 0xFFFFFFFF):
        sc.op(OP_TESTQ, k)
    sc.op(OP_COLLIDE, fw(1.0 / 60))

    sc.tag("static bodies keep their contacts")
    sc.body(4, 0, 0, 1)
    sc.body(5, 3, 0, 0)
    sc.op(OP_WIT, 0, 4, 5, 0)
    sc.witlist([0])
    sc.op(OP_CONTACT, 5, 4, 5)
    sc.op(OP_TESTQ, 5)
    sc.op(OP_COLLIDE, fw(1.0 / 60))     # twenty rounds, then destroyed
    sc.op(OP_CONTACT, 6, 5, 4)
    sc.op(OP_CONTACT, 7, 0, 1)
    sc.op(OP_TESTQ, 6)
    sc.op(OP_TESTQ, 7)
    sc.op(OP_COLLIDE, fw(1.0 / 60))

    sc.tag("a round that ends the list on the twentieth")
    sc.body(0, 0, 1, 1)
    sc.body(1, 0, 0, 0)
    sc.op(OP_WIT, 0, 0, 1, 0)
    sc.witlist([0])
    sc.op(OP_CONTACT, 0, 1, 1)
    sc.op(OP_CONTACT, 1, 0, 1)
    sc.op(OP_TESTQ, 0)
    sc.op(OP_COLLIDE, fw(1.0 / 60))
    for n in (18, 19, 20):
        sc.op(OP_TESTQ, 0)
        for _ in range(n):
            sc.op(OP_TESTQ, 0xFFFFFFFF)
        sc.op(OP_COLLIDE, fw(1.0 / 60))

    sc.tag("smokeables break")
    sc.body(0, 0, 1, 1)
    sc.body(1, 1, 1, 1, -1.0)           # broken
    sc.body(2, 1, 1, 1, -0.5)           # not broken
    sc.body(3, 1, 0, 0, -1.0)           # broken, and static
    sc.body(6, 1, 1, 1)
    sc.body(7, 0, 1, 1)
    sc.bodylist([0, 1, 2, 3, 6, 7])
    for k in range(NW):
        sc.op(OP_WIT, k, [0, 6, 7, 1, 2, 3, 6, 0][k],
              [1, 7, 6, 2, 3, 0, 0, 6][k], 0)
    sc.witlist([0, 1, 2, 3])
    sc.op(OP_CONTACT, 0, 0, 1)
    sc.op(OP_CONTACT, 1, 1, 2)
    sc.op(OP_CONTACT, 2, 3, 0)
    sc.op(OP_CONTACT, 3, 2, 3)
    sc.op(OP_TESTQ, 0)
    sc.op(OP_TESTQ, 3)
    sc.breakq([6, 7])
    sc.op(OP_CREATEQ, 4)
    sc.op(OP_CREATEQ, 0xFFFFFFFF)
    sc.op(OP_CREATEQ, 0xFFFFFFFF)
    sc.op(OP_CREATEQ, 5)
    for k in (1, 2, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF):
        sc.op(OP_TESTQ, k)
    sc.breakq([])
    sc.breakq([0, 6, 7])
    sc.op(OP_COLLIDE, fw(1.0 / 60))
    sc.op(OP_CREATEQ, 0xFFFFFFFF)
    sc.op(OP_CREATEQ, 0xFFFFFFFF)
    sc.body(1, 1, 1, 1, -1.0)
    sc.body(3, 1, 1, 1, -1.0)
    sc.witlist([3])
    sc.op(OP_CONTACT, 0, 1, 3)
    sc.op(OP_TESTQ, 0)
    sc.breakq([6])
    sc.breakq([7, 0])
    sc.op(OP_COLLIDE, fw(1.0 / 60))

    sc.tag("the collisions")
    for k in range(NB):
        sc.body(k, 0, 1, 1)
    sc.witlist([])
    for k in range(NC):
        sc.op(OP_COL, k, k % 2)
    sc.collist([0, 1, 2, 3])
    sc.op(OP_COLLIDE, fw(0.25))
    sc.op(OP_COL, 0, 0)
    sc.op(OP_COL, 2, 0xFFFFFFFF)
    sc.op(OP_COLLIDE, fw(-0.0))
    sc.op(OP_COLLIDE, fw(1.0 / 60))


def step_script(sc):
    sc.tag("the step")
    types = [1, 1, 2, 2, 2, 4, 5, 3, 3, 3]
    for k in range(10):
        sc.car(k, types[k], 300 + k,
               (10.0 * k - 40.0, 3.0 * k, -1.0, 0.5 * k), 5.0 * k,
               0x100 + k, k % 3 != 0)
    sc.carlist([9, 0, 5, 2, 7, 1, 3, 6, 8, 4])
    sc.op(OP_BUILD)
    sc.op(OP_PLAYER, 0, 0)
    sc.op(OP_PLAYER, 1, 1)
    sc.op(OP_REPLAY, 0, 0)
    sc.op(OP_JFLAG, 0)
    sc.op(OP_RC, 3)
    sc.op(OP_PTRS, 0, 0, 0)
    for k in range(NB):
        sc.body(k, 0, k < 4, 1)
    sc.bodylist([0, 1, 4, 5])
    sc.witlist([])
    sc.collist([])
    sc.op(OP_LOOP, 51)
    sc.op(OP_STEP, fw(1.0 / 60))
    sc.op(OP_PTRS, 1, 1, 1)
    sc.op(OP_STEP, fw(1.0 / 30))
    for state in (4, 5, 7, 9, 0, 6, 8, 1, 2):
        sc.op(OP_RC, state)
        sc.op(OP_STEP, fw(0.01))
    for flip in (7, 4, 5, 9, 3, 8):
        sc.op(OP_RC, 3)
        sc.op(OP_SHAKEFLIP, flip)
        sc.op(OP_STEP, fw(0.01))
    sc.op(OP_SHAKEFLIP, 0xFFFFFFFF)

    sc.tag("a player with no car, and one far away")
    sc.op(OP_RC, 3)
    sc.ppos(0, (1.0, 2.0, 3.0, 4.0), 5.0)
    sc.ppos(1, (6.0, 7.0, 8.0, 9.0), 10.0)
    sc.op(OP_PLAYER, 1, 0xFFFFFFFF)
    sc.op(OP_STEP, fw(1.0 / 60))
    sc.op(OP_PLAYER, 0, 0xFFFFFFFF)
    sc.op(OP_STEP, fw(1.0 / 60))
    sc.op(OP_PLAYER, 0, 7)
    sc.op(OP_PLAYER, 1, 1)
    for x in (99.0, 150.0):
        sc.car(7, 3, 307, (x, 0.0, 0.0), 0.0, 0, 1)
        sc.car(8, 3, 308, (0.0, 0.0, -x), 0.0, 0, 1)
        sc.op(OP_STEP, fw(1.0 / 60))
    # One player at the origin and none beside it: the distances are x to
    # the bit, so the 100 and the 150 are met exactly.
    sc.car(0, 1, 300, (0.0, 0.0, 0.0, 0.0), 0.0, 0x100, 0)
    sc.op(OP_PLAYER, 0, 0)
    sc.op(OP_PLAYER, 1, 0xFFFFFFFF)
    for x in (99.0, 99.99999, 100.0, 149.99998, 150.0, 151.0):
        sc.car(7, 3, 307, (x, 0.0, 0.0), 0.0, 0, 1)
        sc.car(8, 3, 308, (0.0, 0.0, -x), 0.0, 0, 1)
        sc.op(OP_STEP, fw(1.0 / 60))

    sc.tag("the step with collisions")
    sc.bodylist([0, 1, 2, 3])
    sc.op(OP_WIT, 0, 0, 1, 0)
    sc.op(OP_WIT, 1, 2, 3, 1)
    sc.witlist([0, 1])
    sc.op(OP_CONTACT, 0, 0, 1)
    sc.op(OP_TESTQ, 0)
    sc.op(OP_COL, 0, 0)
    sc.op(OP_COL, 1, 1)
    sc.collist([1, 0])
    sc.op(OP_REPLAY, 1, 0)
    sc.op(OP_RGET, 0x42)
    sc.op(OP_STEP, fw(1.0 / 60))
    sc.op(OP_REPLAY, 0, 1)
    sc.op(OP_STEP, fw(1.0 / 60))
    sc.op(OP_REPLAY, 0, 0)

    sc.tag("few cars, all of one kind")
    for kinds in ([1], [2], [3], [4], [5], [0], [1, 1], [3, 3, 3], []):
        ks = list(range(len(kinds)))
        for k, t in zip(ks, kinds):
            sc.car(k, t, 400 + k, (float(k), 0.0, 0.0), 0.0, k)
        sc.carlist(ks)
        sc.op(OP_BUILD)
        sc.op(OP_PLAYER, 0, 0 if ks else 0xFFFFFFFF)
        sc.op(OP_PLAYER, 1, 0xFFFFFFFF)
        sc.op(OP_STEP, fw(1.0 / 60))


def walk_script(sc):
    sc.tag("a random walk")
    rnd = random.Random(26092026)
    types = [1, 2, 3, 4, 5, 3, 1, 2, 0, 4, 3, 2, 3, 3]
    for k in range(NCAR):
        sc.car(k, types[k], 500 + k, (rnd.uniform(-50, 50), 0.0, 0.0))
    onlist = [0, 1, 2, 3, 4, 5]
    sc.carlist(onlist)
    sc.op(OP_BUILD)
    sc.op(OP_PLAYER, 0, 0)
    sc.op(OP_PLAYER, 1, 6)
    for k in range(NB):
        sc.body(k, 0, 1, 1)
    sc.bodylist(list(range(NB)))
    sc.witlist([])
    sc.collist([])
    witnesses = set()
    for _ in range(900):
        r = rnd.random()
        if r < 0.10:
            k = rnd.randrange(NCAR)
            sc.car(k, rnd.choice([1, 2, 3, 4, 5, 0]), 500 + rnd.randrange(20),
                   [rnd.choice([rnd.uniform(-200, 200), 0.0, 1.0])
                    for _ in range(4)], rnd.uniform(-100, 100),
                   rnd.getrandbits(32), rnd.randrange(2))
        elif r < 0.14:
            ks = list(range(NCAR))
            rnd.shuffle(ks)
            onlist = ks[:rnd.randrange(NCAR + 1)]
            sc.carlist(onlist)
        elif r < 0.20:
            sc.op(OP_BUILD)
        elif r < 0.23:
            sc.op(OP_PLAYER, rnd.randrange(2),
                  rnd.choice([0xFFFFFFFF] + list(range(NCAR))))
        elif r < 0.30:
            sc.scale(rnd.choice([0.5, 1.0, 2.0, 0.1]),
                     rnd.choice([0.0, 0.02, 0.1, 1.0]), rnd.randrange(2),
                     rnd.randrange(100))
        elif r < 0.34:
            sc.pause(rnd.choice([0.0, 0.02, 0.1, 1.0]), rnd.randrange(2),
                     rnd.randrange(100))
        elif r < 0.38:
            sc.op(OP_UPDPAUSE)
        elif r < 0.40:
            sc.op(OP_ISPAUSED)
        elif r < 0.45:
            q = rnd.choice([0, 60, 61, 59, 120, 30])
            sc.realtime(q * Q + rnd.choice([0.0, 0.001, -0.001]), q)
        elif r < 0.50:
            rep, cap = rnd.randrange(2), rnd.randrange(2)
            sc.op(OP_REPLAY, rep, cap)
            sc.op(OP_RGET, rnd.choice([60, 61, 0, 90]))
            sc.ticks([0, 294912 * 100])
            sc.op(OP_TIMESTEP)
        elif r < 0.53:
            sc.op(OP_RANDI, rnd.choice([1, 7, 1000, -3]))
            sc.op(OP_RANDF, fw(rnd.choice([1.0, 2.5, -4.0])))
        elif r < 0.56:
            sc.op(OP_CMPQ, fw(rnd.uniform(-9, 9)))
            sc.op(OP_CMPQ, fw(rnd.uniform(-9, 9)))
            sc.op(OP_DAT, fw(rnd.uniform(-9, 9)))
        elif r < 0.59:
            sc.op(OP_TIMER, rnd.getrandbits(32))
            sc.op(OP_RGET, rnd.getrandbits(8))
            sc.op(OP_REPLAY, rnd.randrange(2), rnd.randrange(2))
            sc.op(OP_JFLAG, rnd.randrange(2))
            sc.op(OP_VERIFY)
        elif r < 0.64:
            k = rnd.randrange(NB)
            typ = rnd.choice([0, 0, 1, 3])
            sc.body(k, typ, rnd.choice([1, 1, 0]), rnd.choice([1, 1, 0]),
                    rnd.choice([-1.0, 0.5]) if typ == 1 else 0.0)
        elif r < 0.67:
            ks = list(range(NB))
            rnd.shuffle(ks)
            sc.bodylist(ks[:rnd.randrange(NB + 1)])
        elif r < 0.71:
            k = rnd.randrange(NW)
            sc.op(OP_WIT, k, rnd.randrange(NB), rnd.randrange(NB),
                  int(rnd.random() < 0.2))
        elif r < 0.73:
            ks = list(range(NW))
            rnd.shuffle(ks)
            sc.witlist(ks[:rnd.randrange(NW + 1)])
        elif r < 0.80:
            for _ in range(rnd.randrange(4)):
                k = rnd.randrange(NK)
                sc.op(OP_CONTACT, k, rnd.randrange(NB), rnd.randrange(NB))
                sc.op(OP_TESTQ, rnd.choice([k, 0xFFFFFFFF]))
            if rnd.random() < 0.3:
                sc.breakq([rnd.randrange(NB)
                           for _ in range(rnd.randrange(3))])
        elif r < 0.83:
            k = rnd.randrange(NC)
            sc.op(OP_COL, k, rnd.randrange(2))
            ks = list(range(NC))
            rnd.shuffle(ks)
            sc.collist(ks[:rnd.randrange(NC + 1)])
        elif r < 0.88:
            sc.op(OP_LOOP, rnd.choice([51, 50, 179, rnd.getrandbits(32)]))
            sc.op(OP_RC, rnd.choice([3, 3, 3, 4, 5, 7, 9]))
            if rnd.random() < 0.3:
                sc.op(OP_SHAKEFLIP, rnd.choice([0xFFFFFFFF, 3, 7, 9]))
            sc.op(OP_PTRS, rnd.randrange(2), rnd.randrange(2),
                  rnd.randrange(2))
            sc.op(OP_STEP, fw(rnd.choice([1.0 / 60, 1.0 / 30, 0.0])))
        elif r < 0.92:
            sc.op(OP_COLLIDE, fw(1.0 / 60))
        elif r < 0.94:
            sc.op(OP_MOVE, fw(1.0 / 60))
        elif r < 0.96:
            sc.op(OP_SORT)
        elif r < 0.98:
            sc.op(OP_BYNUM, 500 + rnd.randrange(20))
        else:
            sc.op(OP_STATE)
    sc.op(OP_REPLAY, 0, 0)


def script():
    sc = Script()
    time_script(sc)
    random_script(sc)
    cars_script(sc)
    checksum_script(sc)
    bodies_script(sc)
    collide_script(sc)
    step_script(sc)
    walk_script(sc)
    return sc


# ================================================================ the model


class Model(object):
    def __init__(self, sc):
        self.sc = sc
        self.out = []
        e = self.e = me.Emu(ieee=True, eediv=True)
        e.stub_bware()
        # The real bGetTickerDifference: the wait's arithmetic is the
        # point.
        del e.stubs[e.addr_of("bGetTickerDifference__FUiUi")]
        a = e.alloc
        self.world = a(6000, 16)
        self.cars = [a(2048, 16) for _ in range(NCAR)]
        self.dis = [a(32, 16) for _ in range(NCAR)]
        self.players = [a(16, 16) for _ in range(2)]
        self.bodies = [a(512, 16) for _ in range(NB)]
        self.wits = [a(128, 16) for _ in range(NW)]
        self.contacts = [a(64, 16) for _ in range(NK)]
        self.cols = [a(96, 16) for _ in range(NC)]
        self.vt = a(26 * 8, 16)
        self.rm = a(128, 16)
        self.rc = a(16, 16)
        self.race = a(16, 16)
        self.tele = a(96, 16)
        self.heli = a(64, 16)
        self.carhead = self.world
        self.colhead = self.world + 16

        self.createq, self.testq, self.breakq = [], [], []
        self.rgetq, self.jgetq, self.cmpq, self.tickq = [], [], [], []
        self.last_tick = 0
        self.update = [0] * NC
        self.expired = [0] * NW
        self.csum = [0] * NCAR
        self.vfx = [0] * NCAR

        # AICarList too: BuildCarTable walks it to its end.
        for h in (self.carhead, self.world + 8, self.colhead, G_BODIES,
                  G_WITS):
            e.put32(h, h)
            e.put32(h + 4, h)
        e.put32(G_WORLD, self.world)
        e.put32(G_RM, self.rm)
        e.put32(G_RC, self.rc)
        e.put32(self.world + 388, bits(1.0))
        for k in range(NCAR):
            e.put32(self.cars[k] + 20, self.dis[k])
        for b in self.bodies:
            e.put32(b + 80, self.vt)
        e.write(self.vt + 64, bytes([DELTA, 0, 0, 0]))
        e.put32(self.vt + 68, FN_MOVE)
        self.stubs()

    def emit(self, s):
        self.out.append(s)

    def label(self, p):
        e = self.e
        p &= M32
        if p == 0:
            return "null"
        names = [(self.carhead, "cars"), (self.colhead, "collisions"),
                 (G_BODIES, "bodies"), (G_WITS, "witnesses"), (TPM, "TPM"),
                 (FX, "FX"), (self.rm, "RM"), (self.rc, "RC"),
                 (self.race, "RACE"), (self.tele, "TT"), (self.heli, "HELI"),
                 (FN_CB, "CB")]
        for q, n in names:
            if p == q:
                return n
        for pre, tab in (("CAR", self.cars), ("DI", self.dis),
                         ("P", self.players), ("B", self.bodies),
                         ("W", self.wits), ("K", self.contacts),
                         ("C", self.cols)):
            for i, q in enumerate(tab):
                if p == q:
                    return "%s%d" % (pre, i)
        if e.RAM - 0x110000 <= p < e.RAM:
            return "local"
        return "?%08x" % p

    def stubs(self):
        e, L = self.e, self.label

        def arg(i):
            return e.reg[4 + i] & M32

        def f12():
            return e.fpr[12] & M32

        def simple(name, fmt):
            def fn(em):
                if fmt == "c":
                    self.emit("  %s %s" % (name, L(arg(0))))
                elif fmt == "cf":
                    self.emit("  %s %s %08x" % (name, L(arg(0)), f12()))
                elif fmt == "f":
                    self.emit("  %s %08x" % (name, f12()))
                else:
                    self.emit("  %s" % name)
                return None
            return fn

        for addr, name, fmt in (
                (0x00130180, "think", "cf"), (0x001301d0, "drive", "cf"),
                (0x001303a8, "begin", "cf"), (0x00130480, "finish", "cf"),
                (0x00132a10, "wheels", "c"), (0x00131a58, "events", "c"),
                (0x00132740, "rumble", "c"),
                (0x00131db8, "terrain", "cf"), (0x00130ff0, "engine", "c"),
                (0x0020e6f8, "teleport", "cf"), (0x002139d0, "copthink", "f"),
                (0x001dcfa8, "fly", "cf"), (0x001a3990, "particles", ""),
                (0x00125fe8, "fxcheck", "c"), (0x00127250, "fxstep", "cf"),
                (0x001b0700, "emevents", ""), (0x0017aa00, "gamestate", ""),
                (0x00128c08, "rain", "f"), (0x001cf428, "ferns", ""),
                (0x001ab6e8, "tweakdamage", ""),
                (0x001bbcd8, "routeeditor", ""), (0x00146410, "race", "c"),
                (0x0020bc40, "farsmoke", ""), (0x001cc7a0, "printall", ""),
                (0x001ca760, "resolve", "c")):
            e.stub(addr, simple(name, fmt))

        # MaybeCameraShake can move the race on: DoTimestep asks again
        # before the rumble.
        def shake(em):
            self.emit("  shake %s" % L(arg(0)))
            if self.shakeflip >= 0:
                e.put32(self.rc, self.shakeflip)

        e.stub(0x001329e8, shake)

        def vfx(em):
            k = self.cars.index(arg(0))
            self.emit("  vfx %s -> %d" % (L(arg(0)), self.vfx[k]))
            return self.vfx[k]

        def checksum(em):
            k = self.cars.index(arg(0))
            self.emit("  checksum %s -> %08x" % (L(arg(0)), self.csum[k]))
            return self.csum[k]

        def place(em):
            k = self.placeq.pop(0)
            p = self.cars[k] if k >= 0 else 0
            self.emit("  place %s %s -> %s" % (L(arg(0)), L(arg(1)), L(p)))
            return p

        def post(em):
            self.emit("  post %s %d %d" % (L(arg(0)), s32(arg(1)),
                                           s32(arg(2))))

        def jget(em):
            v = self.jgetq.pop(0) if self.jgetq else 0
            self.emit("  jget %d %d -> %08x" % (s32(arg(0)), s32(arg(1)), v))
            return v

        def jadd(em):
            self.emit("  jadd %08x %d %d" % (arg(0), s32(arg(1)),
                                             s32(arg(2))))

        def rget(em):
            v = self.rgetq.pop(0) if self.rgetq else 0
            self.emit("  rget %s %d %d -> %08x" % (L(arg(0)), s32(arg(1)),
                                                   s32(arg(2)), v))
            return v

        def radd(em):
            self.emit("  radd %s %08x %d %d" % (L(arg(0)), arg(1),
                                                s32(arg(2)), s32(arg(3))))

        def compare(em):
            v = self.cmpq.pop(0) if self.cmpq else 0
            self.emit("  compare %s %08x %08x -> %08x"
                      % (L(arg(0)), e.fpr[12] & M32, e.fpr[13] & M32, v))
            e.fpr[0] = v

        def ticker(em):
            if self.tickq:
                v = self.tickq.pop(0)
            else:
                v = (self.last_tick + 0x40000000) & M32
            self.last_tick = v
            self.emit("  ticker -> %08x" % v)
            return v

        def callback(em):
            self.emit("  callback %d" % s32(arg(0)))

        def body_of(this):
            for i, b in enumerate(self.bodies):
                if this - DELTA == b:
                    return i
            raise AssertionError("a slot called on %08x" % this)

        def move(em):
            self.emit("  move B%d %08x" % (body_of(arg(0)), f12()))

        def unlink(p):
            nx, pv = e.u32(p), e.u32(p + 4)
            e.put32(pv, nx)
            e.put32(nx + 4, pv)

        # A destroyed node is freed in the game: its links are poisoned so a
        # loop that reads them afterwards crashes the harness.
        def kill(p):
            unlink(p)
            e.put32(p, 0)
            e.put32(p + 4, 0)

        def on(head, p):
            q, n = e.u32(head), 0
            while q != head and n < 64:
                if q == p:
                    return True
                q, n = e.u32(q), n + 1
            return False

        def append(head, p):
            tail = e.u32(head + 4)
            e.put32(tail, p)
            e.put32(p + 4, tail)
            e.put32(p, head)
            e.put32(head + 4, p)

        def expired(em):
            k = self.wits.index(arg(0))
            self.emit("  expired %s -> %d" % (L(arg(0)), self.expired[k]))
            return self.expired[k]

        def wdestroy(em):
            self.emit("  destroy witness %s %d" % (L(arg(0)), s32(arg(1))))
            kill(arg(0))

        def create(em):
            k = self.createq.pop(0) if self.createq else -1
            w = self.wits[k] if k >= 0 else 0
            if w and on(G_WITS, w):
                w = 0
            self.emit("  create %s -> %s" % (L(arg(0)), L(w)))
            if w:
                append(G_WITS, w)

        def test(em):
            k = self.testq.pop(0) if self.testq else -1
            c = self.contacts[k] if k >= 0 else 0
            if c and on(arg(1), c):
                c = 0
            self.emit("  test %s %s -> %s" % (L(arg(0)), L(arg(1)), L(c)))
            if c:
                append(arg(1), c)

        def remove(em):
            head, b = arg(0), arg(1)
            gone = []
            p = e.u32(head)
            while p != head:
                nx = e.u32(p)
                if e.u32(p + 12) == b or e.u32(p + 16) == b:
                    unlink(p)
                    gone.append(L(p))
                p = nx
            self.emit("  remove %s %s:%s" % (L(head), L(b),
                                             "".join(" " + g for g in gone)))

        def brk(em):
            ks = self.breakq.pop(0) if self.breakq else []
            for i, k in enumerate(ks):
                e.put32(arg(1) + 4 * i, self.bodies[k])
            self.emit("  break %s ->%s" % (L(arg(0)),
                                           "".join(" B%d" % k for k in ks)))
            return len(ks)

        def cdestroy(em):
            self.emit("  destroy contact %s %d" % (L(arg(0)), s32(arg(1))))

        def update(em):
            k = self.cols.index(arg(0))
            self.emit("  update %s %08x -> %d" % (L(arg(0)), f12(),
                                                  s32(self.update[k])))
            return self.update[k]

        def end(em):
            self.emit("  end %s" % L(arg(0)))
            kill(arg(0))

        e.stub(0x00134130, vfx)
        e.stub(0x00130ee0, checksum)
        e.stub(0x0020e7f8, place)
        e.stub(0x00147110, post)
        e.stub(0x0017b920, jget)
        e.stub(0x0017ba60, jadd)
        e.stub(0x0013cac0, rget)
        e.stub(0x0013cb58, radd)
        e.stub(0x001f5b70, compare)
        e.stub("bGetTicker__Fv", ticker)
        e.stub(FN_CB, callback)
        e.stub(FN_MOVE, move)
        e.stub(0x001cbf18, expired)
        e.stub(0x001cba18, wdestroy)
        e.stub(0x001cd130, create)
        e.stub(0x001cc058, test)
        e.stub(0x001ca1c8, remove)
        e.stub(0x0020d8f8, brk)
        e.stub(0x0014c188, cdestroy)
        e.stub(0x0020b668, update)
        e.stub(0x0020b6a8, end)
        self.placeq = []
        self.shakeflip = -1

    # ------------------------------------------------------------ dumps

    def walk(self, head, name):
        e, L = self.e, self.label
        fwd, back = [], []
        p, n = e.u32(head), 0
        while p != head and n < 40:
            fwd.append(L(p))
            p, n = e.u32(p), n + 1
        p, n = e.u32(head + 4), 0
        while p != head and n < 40:
            back.append(L(p))
            p, n = e.u32(p + 4), n + 1
        self.emit("  %s fwd%s back%s" % (name, "".join(" " + s for s in fwd),
                                        "".join(" " + s for s in back)))

    def state(self):
        e, L, w = self.e, self.label, self.world
        self.emit("  state pause %08x waste %08x scale %08x timer %08x cb %s"
                  " param %d seed %08x"
                  % (e.u32(w + 380), e.u32(w + 384), e.u32(w + 388),
                     e.u32(w + 392), L(e.u32(w + 396)), s32(e.u32(w + 400)),
                     e.u32(w + 376)))
        self.emit("  players" + "".join(
            " %08x" % e.u32(w + 336 + 4 * j) for j in range(8))
            + " dat %08x %08x" % (e.u32(w + 368), e.u32(w + 372)))

    def table(self):
        e, L, w = self.e, self.label, self.world
        n = s32(e.u32(w + 28))
        self.emit("  table n %d ai %d cop %d traffic %d:%s" % (
            n, s32(e.u32(w + 32)), s32(e.u32(w + 36)), s32(e.u32(w + 40)),
            "".join(" " + L(e.u32(w + 44 + 4 * i))
                    for i in range(min(max(n, 0), NCAR)))))
        self.emit("  index" + "".join(" %d" % s16(e.u16(c + 8))
                                      for c in self.cars))

    def postable(self):
        e, w = self.e, self.world
        n = s32(e.u32(w + 28))
        for i in range(min(max(n, 0), NCAR)):
            self.emit("  pos %d" % i + "".join(
                " %08x" % e.u32(w + 112 + 16 * i + 4 * j) for j in range(4)))

    def link(self, head, objs, ks):
        e = self.e
        e.put32(head, head)
        e.put32(head + 4, head)
        for k in ks:
            p = objs[k]
            tail = e.u32(head + 4)
            e.put32(tail, p)
            e.put32(p + 4, tail)
            e.put32(p, head)
            e.put32(head + 4, p)

    # ------------------------------------------------------------ the run

    def run(self):
        e, w, L = self.e, self.sc.words, self.label
        emit, W = self.emit, self.world
        i = 0

        def arg():
            nonlocal i
            i += 1
            return w[i - 1]

        def args(n):
            return [arg() for _ in range(n)]

        def call(name, *a, **kw):
            return e.call(FN[name], *a, **kw)

        def cb(v):
            return FN_CB if v else 0

        while i < len(w):
            op = arg()
            if op == OP_TAG:
                emit("[%d]" % arg())
            elif op == OP_CAR:
                k, typ, dn = arg(), arg(), arg()
                pos, dat, csum, vfx = args(4), arg(), arg(), arg()
                c = self.cars[k]
                e.put32(self.dis[k] + 4, typ)
                e.mem[c + 10] = dn & 0xFF
                e.mem[c + 11] = (dn >> 8) & 0xFF
                for j in range(4):
                    e.put32(c + 96 + 4 * j, pos[j])
                e.put32(c + 1860, dat)
                self.csum[k] = csum
                self.vfx[k] = vfx
                emit("car CAR%d" % k)
            elif op == OP_CARLIST:
                ks = args(arg())
                self.link(self.carhead, self.cars, ks)
                emit("carlist")
                self.walk(self.carhead, "cars")
            elif op == OP_PLAYER:
                j, k = arg(), s32(arg())
                if k < 0:
                    e.put32(G_PLAYERS + 4 * j, 0)
                else:
                    e.put32(G_PLAYERS + 4 * j, self.players[j])
                    e.put32(self.players[j] + 4, self.cars[k])
                emit("player %d %d" % (j, k))
            elif op == OP_BUILD:
                emit("build")
                call("build", W)
                self.table()
            elif op == OP_BYNUM:
                n = s32(arg())
                emit("bynum %d -> %s" % (n, L(call("bynum", W, n))))
            elif op == OP_BYDRV:
                n = s32(arg())
                emit("bydrv %d -> %s" % (n, L(call("bydrv", n))))
            elif op == OP_FLIP:
                a, b = arg(), arg()
                emit("flip CAR%d CAR%d -> %d"
                     % (a, b, call("flip", self.cars[a], self.cars[b])))
            elif op == OP_SORT:
                emit("sort")
                call("sort", self.carhead, FN_FLIP)
                self.walk(self.carhead, "cars")
            elif op == OP_TRAFFIC:
                d, k = arg(), s32(arg())
                emit("traffic DI%d" % d)
                self.placeq.append(k)
                call("traffic", W, self.dis[d])
                self.walk(self.carhead, "cars")
            elif op == OP_SCALE:
                s, t, c, p = arg(), arg(), arg(), arg()
                e.fpr[12], e.fpr[13] = s, t
                emit("scale")
                call("scale", W, cb(c), p)
                self.state()
            elif op == OP_RESET:
                emit("reset")
                call("reset", W)
                self.state()
            elif op == OP_PAUSE:
                t, c, p = arg(), arg(), arg()
                e.fpr[12] = t
                emit("pause")
                call("pause", W, cb(c), p)
                self.state()
            elif op in (OP_BEGIN, OP_END):
                emit("begin" if op == OP_BEGIN else "end")
                call("begin" if op == OP_BEGIN else "end", W)
                self.state()
            elif op == OP_UPDPAUSE:
                emit("updpause")
                call("updpause", W)
                self.state()
            elif op == OP_ISPAUSED:
                emit("ispaused -> %d" % call("ispaused", W))
            elif op == OP_TWEAK:
                v = arg()
                e.put32(G_TWEAK, v)
                emit("tweak %d" % s32(v))
            elif op == OP_REALTIME:
                f, q = arg(), arg()
                e.put32(G_RTE, f)
                e.put32(G_RTEQ, q)
                emit("realtime %08x %d" % (f, s32(q)))
            elif op == OP_REPLAY:
                r, c = arg(), arg()
                e.put32(self.rm, r)
                e.put32(self.rm + 4, c)
                emit("replay %d %d" % (r, c))
            elif op == OP_DRAIN:
                self.rgetq, self.jgetq, self.cmpq, self.tickq = [], [], [], []
                self.createq, self.testq, self.breakq = [], [], []
                self.placeq = []
                self.shakeflip = -1
            elif op == OP_SHAKEFLIP:
                self.shakeflip = s32(arg())
                emit("shakeflip %d" % self.shakeflip)
            elif op == OP_RGET:
                self.rgetq.append(arg())
            elif op == OP_JGET:
                self.jgetq.append(arg())
            elif op == OP_JFLAG:
                v = arg()
                e.put32(G_JREPLAY, v)
                emit("jflag %d" % v)
            elif op == OP_TICKS:
                self.tickq.extend(args(arg()))
            elif op == OP_TIMESTEP:
                emit("timestep")
                call("timestep", W, limit=20000000)
                emit("  -> %08x" % (e.fpr[0] & M32))
                self.state()
            elif op == OP_SEED:
                v = arg()
                e.put32(W + 376, v)
                emit("seed %08x" % v)
            elif op == OP_RANDI:
                r = s32(arg())
                v = call("randi", W, r)
                emit("randi %d -> %d seed %08x" % (r, v, e.u32(W + 376)))
            elif op == OP_RANDF:
                f = arg()
                e.fpr[12] = f
                call("randf", W)
                emit("randf %08x -> %08x seed %08x"
                     % (f, e.fpr[0] & M32, e.u32(W + 376)))
            elif op == OP_DATS:
                d0, d1 = arg(), arg()
                e.put32(W + 368, d0)
                e.put32(W + 372, d1)
                emit("dats %08x %08x" % (d0, d1))
            elif op == OP_CMPQ:
                self.cmpq.append(arg())
            elif op == OP_DAT:
                d = arg()
                e.fpr[12] = d
                emit("dat %08x" % d)
                call("dat", W)
                emit("  -> %08x" % (e.fpr[0] & M32))
            elif op == OP_TIMER:
                t = arg()
                e.put32(G_TIMER, t)
                emit("timer %08x" % t)
            elif op == OP_CHECKSUM:
                emit("checksum")
                v = call("csum", W)
                emit("  -> %08x" % (v & M32))
                self.postable()
            elif op == OP_VERIFY:
                emit("verify")
                call("verify", W)
            elif op == OP_LOOP:
                n = arg()
                e.put32(G_LOOP, n)
                emit("loop %08x" % n)
            elif op == OP_BODY:
                k, typ, dyn, act, st = arg(), arg(), arg(), arg(), arg()
                b = self.bodies[k]
                e.mem[b + 12] = typ
                e.mem[b + 13] = dyn
                e.mem[b + 19] = act
                e.put32(b + 280, st)
                emit("body B%d" % k)
            elif op == OP_BODYLIST:
                ks = args(arg())
                self.link(G_BODIES, self.bodies, ks)
                emit("bodylist")
                self.walk(G_BODIES, "bodies")
            elif op == OP_MOVE:
                dt = arg()
                e.fpr[12] = dt
                emit("move %08x" % dt)
                call("move", W)
            elif op == OP_WIT:
                k, b1, b2, ex = arg(), arg(), arg(), arg()
                e.put32(self.wits[k] + 96, self.bodies[b1])
                e.put32(self.wits[k] + 100, self.bodies[b2])
                self.expired[k] = ex
                emit("wit W%d" % k)
            elif op == OP_WITLIST:
                ks = args(arg())
                self.link(G_WITS, self.wits, ks)
                emit("witlist")
                self.walk(G_WITS, "witnesses")
            elif op == OP_CREATEQ:
                self.createq.append(s32(arg()))
            elif op == OP_CONTACT:
                k, b1, b2 = arg(), arg(), arg()
                e.put32(self.contacts[k] + 12, self.bodies[b1])
                e.put32(self.contacts[k] + 16, self.bodies[b2])
                emit("contact K%d" % k)
            elif op == OP_TESTQ:
                self.testq.append(s32(arg()))
            elif op == OP_BREAKQ:
                self.breakq.append(args(arg()))
            elif op == OP_COL:
                k, u = arg(), arg()
                self.update[k] = u
                emit("col C%d" % k)
            elif op == OP_COLLIST:
                ks = args(arg())
                self.link(self.colhead, self.cols, ks)
                emit("collist")
                self.walk(self.colhead, "collisions")
            elif op == OP_COLLIDE:
                dt = arg()
                e.fpr[12] = dt
                emit("collide %08x" % dt)
                call("collide", W)
                self.walk(G_WITS, "witnesses")
                self.walk(self.colhead, "collisions")
            elif op == OP_STATE:
                emit("state")
                self.state()
            elif op == OP_RC:
                v = arg()
                e.put32(self.rc, v)
                emit("rc %d" % v)
            elif op == OP_PTRS:
                t, h, r = arg(), arg(), arg()
                e.put32(W + 404, self.tele if t else 0)
                e.put32(W + 24, self.heli if h else 0)
                e.put32(G_RACE, self.race if r else 0)
                emit("ptrs %d %d %d" % (t, h, r))
            elif op == OP_STEP:
                dt = arg()
                e.fpr[12] = dt
                emit("step %08x" % dt)
                call("step", W)
                self.state()
                self.walk(self.carhead, "cars")
                self.walk(G_WITS, "witnesses")
                self.walk(self.colhead, "collisions")
                self.postable()
            elif op == OP_FLUSH:
                emit("flush")
                call("flush", W)
            elif op == OP_PPOS:
                j = arg()
                v, dat = args(4), arg()
                for n in range(4):
                    e.put32(W + 336 + 16 * j + 4 * n, v[n])
                e.put32(W + 368 + 4 * j, dat)
                emit("ppos %d" % j)
            else:
                raise SystemExit("op %d" % op)
        return self.out


FN_FLIP = FN["flip"]


def model(sc):
    return Model(sc).run()


# ---------------------------------------------------------------- running

HARNESS_TIMEOUT = 60
HARNESS_HUNG = -9999


def write_script(sc, path):
    Path(path).write_text(" ".join("%x" % x for x in sc.words) + NL)


def run_harness(exe, script_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(script_path)], stdout=fh,
                               stderr=subprocess.PIPE, text=True,
                               timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("harness hung, killed after %d s" % HARNESS_TIMEOUT)
        return HARNESS_HUNG
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
    return r.returncode


def diff(model_lines, harness_lines, quiet=False):
    bad = 0
    for line in difflib.unified_diff(model_lines, harness_lines,
                                     "model", "harness", lineterm="", n=1):
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith(("+", "-")):
            bad += 1
            if not quiet and bad <= 40:
                print(line)
    return bad


# -------------------------------------------------------------- mutations
#
# (name, file, old, new). Each replaces the first match, so every pattern is
# spelled to match code and not a comment.

MUTATIONS = []


def _m(name, old, new, rel=WS):
    MUTATIONS.append((name, rel, old, new))


# the clock and the pause
_m("scale drops param", "w->TimeScaleCallbackParam = param;\n    w->fTimeScale",
   "w->TimeScaleCallbackParam = 0;\n    w->fTimeScale")
_m("scale stores timer", "w->fTimeScale = scale;", "w->fTimeScale = timer;")
_m("scale timer is scale", "w->fTimeScaleTimer = timer;",
   "w->fTimeScaleTimer = scale;")
_m("scale drops callback",
   "w->TimeScaleCallback = callback;\n}\n\nvoid world_reset_time_scale",
   "w->TimeScaleCallback = NULL;\n}\n\nvoid world_reset_time_scale")
_m("reset keeps param", "    w->TimeScaleCallbackParam = 0;\n    w->fTimeScale = 1.0f;",
   "    w->fTimeScale = 1.0f;")
_m("reset scale half", "w->fTimeScale = 1.0f;\n    w->fTimeScaleTimer = 0.0f;",
   "w->fTimeScale = 0.5f;\n    w->fTimeScaleTimer = 0.0f;")
_m("reset keeps timer", "    w->fTimeScaleTimer = 0.0f;\n    w->fTimeToRemainPaused = 0.0f;",
   "    w->fTimeToRemainPaused = 0.0f;")
_m("reset keeps pause",
   "    w->fTimeToRemainPaused = 0.0f;\n    w->TimeScaleCallback = NULL;\n}",
   "    w->TimeScaleCallback = NULL;\n}")
_m("reset keeps callback", "    w->TimeScaleCallback = NULL;\n}\n\nvoid world_set_world_paused",
   "}\n\nvoid world_set_world_paused")
_m("pause drops param",
   "w->TimeScaleCallbackParam = param;\n    w->fTimeToRemainPaused",
   "w->TimeScaleCallbackParam = 0;\n    w->fTimeToRemainPaused")
_m("pause drops seconds", "w->fTimeToRemainPaused = seconds;",
   "w->fTimeToRemainPaused = 0.0f;")
_m("pause drops callback",
   "w->TimeScaleCallback = callback;\n}\n\nvoid world_begin_pause",
   "}\n\nvoid world_begin_pause")
_m("updpause runs at 0", "if (!(0.0f < t))", "if (!(0.0f <= t))")
_m("updpause adds", "t = t - RealTimeElapsed;", "t = t + RealTimeElapsed;")
_m("updpause ends below 0", "if (!(t <= 0.0f))", "if (!(t < 0.0f))")
_m("updpause keeps negative",
   "    w->fTimeToRemainPaused = 0.0f;\n    if (w->TimeScaleCallback",
   "    if (w->TimeScaleCallback")
_m("updpause keeps param",
   "        w->TimeScaleCallbackParam = 0;\n        w->TimeScaleCallback = NULL;\n    }\n}",
   "        w->TimeScaleCallback = NULL;\n    }\n}")
_m("updpause keeps callback",
   "        w->TimeScaleCallbackParam = 0;\n        w->TimeScaleCallback = NULL;\n    }\n}",
   "        w->TimeScaleCallbackParam = 0;\n    }\n}")
_m("ispaused at 0", "return 0.0f < w->fTimeToRemainPaused",
   "return 0.0f <= w->fTimeToRemainPaused")
_m("ispaused tweak inverted", "TweakerPauseWorld != 0;",
   "TweakerPauseWorld == 0;")
_m("ispaused and", "w->fTimeToRemainPaused || TweakerPauseWorld",
   "w->fTimeToRemainPaused && TweakerPauseWorld")

# the timestep
_m("step reads when capturing",
   "if (rm->ReplayingFlag) {\n        q = ReplayManager_GetData",
   "if (rm->CapturingFlag) {\n        q = ReplayManager_GetData")
_m("step reads channel 2", "q = ReplayManager_GetData(rm, 8, 1);",
   "q = ReplayManager_GetData(rm, 8, 2);")
_m("step reads 16 bits", "q = ReplayManager_GetData(rm, 8, 1);",
   "q = ReplayManager_GetData(rm, 16, 1);")
_m("step q plus one", "q = RealTimeElapsedQuantized;",
   "q = RealTimeElapsedQuantized + 1;")
_m("step always records",
   "if (rm->CapturingFlag)\n            ReplayManager_AddData(rm, q, 8, 1);",
   "ReplayManager_AddData(rm, q, 8, 1);")
_m("step records channel 2", "ReplayManager_AddData(rm, q, 8, 1);",
   "ReplayManager_AddData(rm, q, 8, 2);")
_m("step waits always", "if (pReplayManager->ReplayingFlag) {",
   "if (1) {")
_m("step waits never", "if (pReplayManager->ReplayingFlag) {",
   "if (0) {")
_m("waste max for min", "float waste = min_s(MAX_TIME_TO_WASTE,",
   "float waste = max_s(MAX_TIME_TO_WASTE,")
_m("waste min for max", "max_s((real - RealTimeElapsed)",
   "min_s((real - RealTimeElapsed)")
_m("waste min swapped",
   "min_s(MAX_TIME_TO_WASTE,\n                            max_s((real - RealTimeElapsed)\n"
   "                                  + w->PreviousTimeToWaste, 0.0f));",
   "min_s(max_s((real - RealTimeElapsed)\n"
   "                                  + w->PreviousTimeToWaste, 0.0f),"
   " MAX_TIME_TO_WASTE);")
_m("waste max swapped",
   "max_s((real - RealTimeElapsed)\n"
   "                                  + w->PreviousTimeToWaste, 0.0f)",
   "max_s(0.0f, (real - RealTimeElapsed)\n"
   "                                  + w->PreviousTimeToWaste)")
_m("waste backwards", "(real - RealTimeElapsed)", "(RealTimeElapsed - real)")
_m("waste minus previous", "+ w->PreviousTimeToWaste, 0.0f)",
   "- w->PreviousTimeToWaste, 0.0f)")
_m("waste not kept", "w->PreviousTimeToWaste = waste;",
   "w->PreviousTimeToWaste = 0.0f;")
_m("waste at 0", "if (0.0f < waste) {", "if (0.0f <= waste) {")
_m("waste spin <=", "* TICKS_TO_SECONDS < waste)", "* TICKS_TO_SECONDS <= waste)")
_m("waste cap", "#define MAX_TIME_TO_WASTE 0.3f", "#define MAX_TIME_TO_WASTE 0.25f")
_m("ticks to seconds", "#define TICKS_TO_SECONDS  0.001f",
   "#define TICKS_TO_SECONDS  0.002f")
_m("ticker difference swapped", "bGetTickerDifference(start, bGetTicker())",
   "bGetTickerDifference(bGetTicker(), start)")
_m("scaletimer at 0", "if (0.0f < w->fTimeScaleTimer) {",
   "if (0.0f <= w->fTimeScaleTimer) {")
_m("scaletimer adds", "float t = w->fTimeScaleTimer - real;",
   "float t = w->fTimeScaleTimer + real;")
_m("scaletimer ends below 0",
   "w->fTimeScaleTimer = t;\n        if (t <= 0.0f) {",
   "w->fTimeScaleTimer = t;\n        if (t < 0.0f) {")
_m("scaletimer keeps negative",
   "            w->fTimeScaleTimer = 0.0f;\n            w->fTimeScale = 1.0f;",
   "            w->fTimeScale = 1.0f;")
_m("scaletimer keeps scale",
   "            w->fTimeScale = 1.0f;\n            if (w->TimeScaleCallback",
   "            if (w->TimeScaleCallback")
_m("scaletimer keeps callback",
   "                w->TimeScaleCallback = NULL;\n                w->TimeScaleCallbackParam = 0;",
   "                w->TimeScaleCallbackParam = 0;")
_m("scaletimer keeps param",
   "                w->TimeScaleCallback = NULL;\n                w->TimeScaleCallbackParam = 0;",
   "                w->TimeScaleCallback = NULL;")
_m("scaletimer param first",
   "w->TimeScaleCallback(w->TimeScaleCallbackParam);\n                w->TimeScaleCallback = NULL;",
   "w->TimeScaleCallback(0);\n                w->TimeScaleCallback = NULL;")
_m("step unscaled", "return real * w->fTimeScale;", "return real;")

# the small things
_m("randi range", "bRandomI(range, &w->WorldRandomSeed)",
   "bRandomI(range + 1, &w->WorldRandomSeed)")
_m("randf range", "bRandomF(f, &w->WorldRandomSeed)",
   "bRandomF(f * 2.0f, &w->WorldRandomSeed)")
_m("dat second is first", "w->PlayerDATs[1], dat);", "w->PlayerDATs[0], dat);")
_m("dat args swapped", "w->PlayerDATs[0], dat);", "dat, w->PlayerDATs[0]);")
_m("dat tie to 0", "fabsf(d0) < fabsf(d1) ? d0 : d1", "fabsf(d0) <= fabsf(d1) ? d0 : d1")
_m("dat signed", "fabsf(d0) < fabsf(d1) ? d0 : d1", "d0 < d1 ? d0 : d1")

# the car table
_m("table not zeroed", "    w->TotalNumCars = 0;\n    w->AICarPos = 0;",
   "    w->AICarPos = 0;")
_m("table players are ai", "if (car_type(c) == DRIVER_TYPE_PLAYER)",
   "if (car_type(c) == DRIVER_TYPE_AI_RACER)")
_m("table ai are players", "if (car_type(c) == DRIVER_TYPE_AI_RACER)",
   "if (car_type(c) == DRIVER_TYPE_PLAYER)")
_m("table aipos unset", "    w->AICarPos = w->TotalNumCars;\n", "")
_m("table coppos unset", "    w->CopCarPos = w->TotalNumCars;\n", "")
_m("table trafficpos unset", "    w->TrafficCarPos = w->TotalNumCars;\n", "")
_m("table no super cops", "|| car_type(c) == DRIVER_TYPE_SUPER_COP)",
   "|| car_type(c) == DRIVER_TYPE_COP)")
_m("table no plain cops", "if (car_type(c) == DRIVER_TYPE_COP\n",
   "if (car_type(c) == DRIVER_TYPE_SUPER_COP\n")
_m("table typeless are traffic",
   "if (car_type(c) == DRIVER_TYPE_TRAFFIC_CAR)",
   "if (car_type(c) == DRIVER_TYPE_TRAFFIC_CAR || car_type(c) == 0)")
_m("table traffic before cops",
   "        if (car_type(c) == DRIVER_TYPE_COP\n"
   "            || car_type(c) == DRIVER_TYPE_SUPER_COP)",
   "        if (car_type(c) == DRIVER_TYPE_TRAFFIC_CAR)")
_m("table index plus one", "CarIndex = (int16_t)i;", "CarIndex = (int16_t)(i + 1);")
_m("table index short",
   "for (i = 0; i < w->TotalNumCars; i++)\n        w->CarTable[i]->CarIndex",
   "for (i = 0; i < w->TotalNumCars - 1; i++)\n        w->CarTable[i]->CarIndex")
_m("table total late", "    w->CarTable[w->TotalNumCars] = c;\n    w->TotalNumCars++;",
   "    w->CarTable[w->TotalNumCars] = c;\n    w->TotalNumCars += 2;")
_m("bynum inverted", "if (w->CarTable[i]->DriverNumber == n)",
   "if (w->CarTable[i]->DriverNumber != n)")
_m("bynum short",
   "for (i = 0; i < w->TotalNumCars; i++)\n        if (w->CarTable[i]->DriverNumber",
   "for (i = 0; i < w->TotalNumCars - 1; i++)\n        if (w->CarTable[i]->DriverNumber")
_m("bynum last match",
   "    int32_t i;\n\n    for (i = 0; i < w->TotalNumCars; i++)\n"
   "        if (w->CarTable[i]->DriverNumber == n)\n            return w->CarTable[i];\n    return NULL;",
   "    int32_t i;\n    Car *c = NULL;\n\n    for (i = 0; i < w->TotalNumCars; i++)\n"
   "        if (w->CarTable[i]->DriverNumber == n)\n            c = w->CarTable[i];\n    return c;")
_m("bydrv off by one", "world_get_car_by_number(pCurrentWorld, n)",
   "world_get_car_by_number(pCurrentWorld, n + 1)")
_m("flip strict", "return a->State.Position.x <= b->State.Position.x;",
   "return a->State.Position.x < b->State.Position.x;")
_m("flip on z", "return a->State.Position.x <= b->State.Position.x;",
   "return a->State.Position.z <= b->State.Position.z;")
_m("sort adapter swapped",
   "world_car_list_check_flip((const Car *)(void *)a,\n"
   "                                     (const Car *)(void *)b);",
   "world_car_list_check_flip((const Car *)(void *)b,\n"
   "                                     (const Car *)(void *)a);")
_m("traffic no null test", "    if (c == NULL)\n        return;\n    tail", "    tail")
_m("traffic no teleporter", "gTrafficTeleporterPlaceNewCarFn(w->Teleporter, info)",
   "gTrafficTeleporterPlaceNewCarFn(NULL, info)")
_m("traffic head not moved", "    w->CarList.prev = c;\n", "")
_m("traffic prev not set", "    c->Link.prev = &tail->Link;\n", "")
_m("traffic at the front",
   "    tail = w->CarList.prev;\n    tail->Link.next = &c->Link;\n"
   "    w->CarList.prev = c;\n    c->Link.next = (CarNode *)(void *)&w->CarList;\n"
   "    c->Link.prev = &tail->Link;",
   "    tail = w->CarList.next;\n    c->Link.next = &tail->Link;\n"
   "    c->Link.prev = (CarNode *)(void *)&w->CarList;\n"
   "    tail->Link.prev = &c->Link;\n    w->CarList.next = c;")

# the checksums
_m("csum from 0", "uint32_t s = (uint32_t)WorldTimer;", "uint32_t s = 0u;")
_m("csum times 31", "s = s * 33u + v;", "s = s * 31u + v;")
_m("csum xor", "s = s * 33u + v;", "s = (s * 33u) ^ v;")
_m("csum fold 15", "return (uint16_t)((s >> 16) + s);",
   "return (uint16_t)((s >> 15) + s);")
_m("csum fold xor", "return (uint16_t)((s >> 16) + s);",
   "return (uint16_t)((s >> 16) ^ s);")
_m("csum no fold", "return (uint16_t)((s >> 16) + s);", "return (uint16_t)s;")
_m("csum positions kept", "        w->CarPositionTable[i] = c->State.Position;\n", "")
_m("csum short",
   "for (i = 0; i < w->TotalNumCars; i++) {\n        Car *c = w->CarTable[i];\n        uint32_t v",
   "for (i = 0; i < w->TotalNumCars - 1; i++) {\n        Car *c = w->CarTable[i];\n        uint32_t v")
_m("verify joylog inverted", "if (Joylog_ReplayingFlag)\n",
   "if (!Joylog_ReplayingFlag)\n")
_m("verify jget channel", "(void)Joylog_GetData(16, 3);", "(void)Joylog_GetData(16, 2);")
_m("verify jadd bits", "Joylog_AddData((int32_t)c, 16, 3);",
   "Joylog_AddData((int32_t)c, 8, 3);")
_m("verify byte shift 7", "b = ((c >> 8) + c", "b = ((c >> 7) + c")
_m("verify byte no c", "b = ((c >> 8) + c + (w->WorldRandomSeed",
   "b = ((c >> 8) + (w->WorldRandomSeed")
_m("verify seed 7f", "(w->WorldRandomSeed & 0xffu)) & 0xffu;",
   "(w->WorldRandomSeed & 0x7fu)) & 0xffu;")
_m("verify byte wide", "(w->WorldRandomSeed & 0xffu)) & 0xffu;",
   "(w->WorldRandomSeed & 0xffu)) & 0x1ffu;")
_m("verify capture falls on",
   "        ReplayManager_AddData(rm, (int32_t)b, 8, 2);\n        return;\n",
   "        ReplayManager_AddData(rm, (int32_t)b, 8, 2);\n")
_m("verify capture channel", "ReplayManager_AddData(rm, (int32_t)b, 8, 2);",
   "ReplayManager_AddData(rm, (int32_t)b, 8, 1);")
_m("verify reads when idle", "    if (!rm->ReplayingFlag)\n        return;\n", "")
_m("verify rget channel", "ReplayManager_GetData(rm, 8, 2) & 0xffu",
   "ReplayManager_GetData(rm, 8, 1) & 0xffu")
_m("verify rget unmasked",
   "if (((uint32_t)ReplayManager_GetData(rm, 8, 2) & 0xffu) == b)",
   "if ((uint32_t)ReplayManager_GetData(rm, 8, 2) == b)")
_m("verify match inverted", "& 0xffu) == b)", "& 0xffu) != b)")
_m("verify post param", "RC_SKIP_REPLAY, 0);", "RC_SKIP_REPLAY, 1);")
_m("verify posts 12", "gRaceCoordinatorPostMessageFn(pRaceCoordinator, RC_SKIP_REPLAY",
   "gRaceCoordinatorPostMessageFn(pRaceCoordinator, RC_SKIP_REPLAY + 1")

# the move
_m("move schedule 78", "+ 77u) & 127u) == 0", "+ 78u) & 127u) == 0")
_m("move schedule 63", "+ 77u) & 127u) == 0", "+ 77u) & 63u) == 0")
_m("move schedule inverted", "+ 77u) & 127u) == 0", "+ 77u) & 127u) != 0")
_m("move static too", "        if (!b->Dynamic)\n            continue;\n", "")
_m("move this undeltaed", "((MoveFn)e->fn)(vt_this(moving[i], e), dt);",
   "((MoveFn)e->fn)(moving[i], dt);")
_m("move dt doubled", "((MoveFn)e->fn)(vt_this(moving[i], e), dt);",
   "((MoveFn)e->fn)(vt_this(moving[i], e), dt * 2.0f);")
_m("move short", "for (i = 0; i < n; i++) {\n        const VtEntry",
   "for (i = 0; i < n - 1; i++) {\n        const VtEntry")
_m("move backwards", "for (i = 0; i < n; i++) {\n        const VtEntry *e = vt_slot(moving[i]->_vtable, COLLISIONBODY_VT_MOVE);\n\n        ((MoveFn)e->fn)(vt_this(moving[i], e), dt);",
   "for (i = n - 1; i >= 0; i--) {\n        const VtEntry *e = vt_slot(moving[i]->_vtable, COLLISIONBODY_VT_MOVE);\n\n        ((MoveFn)e->fn)(vt_this(moving[i], e), dt);")
_m("move slot 65", "COLLISIONBODY_VT_MOVE);", "COLLISIONBODY_VT_MOVE + 1);")

# the collisions
_m("collide no printall", "    collisionbody_maybe_print_all();\n", "")
_m("collide expiry inverted", "if (cbwitness_has_expired(wit))",
   "if (!cbwitness_has_expired(wit))")
_m("collide destroy flags", "cbwitness_destroy(wit, 3);", "cbwitness_destroy(wit, 1);")
_m("collide next read late",
   "wit = next) {\n        next = wit->Link.next;\n        if (cbwitness_has_expired(wit))\n            cbwitness_destroy(wit, 3);\n    }",
   "wit = next) {\n        if (cbwitness_has_expired(wit))\n            cbwitness_destroy(wit, 3);\n        next = wit->Link.next;\n    }")
_m("collide create or",
   "        if (b->Dynamic && b->ActiveCollisionDetection)\n            dynamiccollisionbody_maybe_create_witnesses(\n                (DynamicCollisionBody *)(void *)b);",
   "        if (b->Dynamic || b->ActiveCollisionDetection)\n            dynamiccollisionbody_maybe_create_witnesses(\n                (DynamicCollisionBody *)(void *)b);")
_m("collide create inactive",
   "        if (b->Dynamic && b->ActiveCollisionDetection)\n            dynamiccollisionbody_maybe_create_witnesses(\n                (DynamicCollisionBody *)(void *)b);",
   "        if (b->Dynamic)\n            dynamiccollisionbody_maybe_create_witnesses(\n                (DynamicCollisionBody *)(void *)b);")
_m("collide no first tests", "        cbwitness_test_for_contact(wit, &list);\n\n    // Earliest",
   "        (void)wit;\n\n    // Earliest")
_m("collide no resolve", "        contact_resolve(c);\n", "")
_m("collide b1 static removed", "if (b1->Dynamic)\n", "if (!b1->Dynamic)\n")
_m("collide b2 static removed", "if (b2->Dynamic)\n", "if (!b2->Dynamic)\n")
_m("collide b2 removes b1", "contact_remove_contacts(&list, b2);",
   "contact_remove_contacts(&list, b1);")
_m("collide pieces swapped",
   "n = add_piece(b1, pieces, 0);\n        n = add_piece(b2, pieces, n);",
   "n = add_piece(b2, pieces, 0);\n        n = add_piece(b1, pieces, n);")
_m("collide b2 overwrites", "n = add_piece(b2, pieces, n);",
   "n = add_piece(b2, pieces, 0);")
_m("collide never breaks", "    if (is_broken_smokeable(b))\n",
   "    if (0 && is_broken_smokeable(b))\n")
_m("broken any type", "return b->Type == SMOKEABLE_COLLISION_BODY\n",
   "return b->Type != SMOKEABLE_COLLISION_BODY\n")
_m("broken below 0", "->BreakingStrength == -1.0f;", "->BreakingStrength < 0.0f;")
_m("broken not -1", "->BreakingStrength == -1.0f;", "->BreakingStrength != -1.0f;")
_m("piece inactive", "    if (b->Dynamic && b->ActiveCollisionDetection) {\n",
   "    if (b->Dynamic) {\n")
_m("piece static", "    if (b->Dynamic && b->ActiveCollisionDetection) {\n",
   "    if (b->ActiveCollisionDetection) {\n")
_m("break writes at 0", "&pieces[n]);", "&pieces[0]);")
_m("break drops n", "    return n + k;\n", "    return k;\n")
_m("break keeps the smokeable", "        return break_smokeable(b, pieces, n);\n",
   "        n = break_smokeable(b, pieces, n);\n")
_m("pieces create short",
   "for (i = 0; i < n; i++)\n            dynamiccollisionbody_maybe_create_witnesses(",
   "for (i = 0; i < n - 1; i++)\n            dynamiccollisionbody_maybe_create_witnesses(")
_m("retest and", "if (wit->pBody1 == pieces[i] || wit->pBody2 == pieces[i])",
   "if (wit->pBody1 == pieces[i] && wit->pBody2 == pieces[i])")
_m("retest body1 only", "if (wit->pBody1 == pieces[i] || wit->pBody2 == pieces[i])",
   "if (wit->pBody1 == pieces[i])")
_m("retest once per witness",
   "                    cbwitness_test_for_contact(wit, &list);\n\n        round++;",
   "                    { cbwitness_test_for_contact(wit, &list); break; }\n\n        round++;")
_m("rounds 21", "if (round >= WORLD_MAX_CONTACT_ROUNDS)",
   "if (round > WORLD_MAX_CONTACT_ROUNDS)")
_m("rounds 19", "if (round >= WORLD_MAX_CONTACT_ROUNDS)", "if (round >= 19)")
_m("leftovers kept", "if (round == WORLD_MAX_CONTACT_ROUNDS) {", "if (0) {")
_m("leftovers flags", "contact_destroy(c, 3);", "contact_destroy(c, 1);")
_m("update inverted", "if (!collision_update(col, dt))", "if (collision_update(col, dt))")
_m("update dt 0", "if (!collision_update(col, dt))", "if (!collision_update(col, 0.0f))")
_m("update next read late",
   "col = next_col) {\n        next_col = col->Link.next;\n        if (!collision_update(col, dt))\n            collision_end(col);\n    }",
   "col = next_col) {\n        if (!collision_update(col, dt))\n            collision_end(col);\n        next_col = col->Link.next;\n    }")

# the step
_m("step no verify", "    world_verify_debug_checksums(w);\n\n    for (i = 0;",
   "\n    for (i = 0;")
_m("step players not copied", "            w->PlayerPositions[i] = car->State.Position;\n", "")
_m("step player xyz only", "            w->PlayerPositions[i] = car->State.Position;\n",
   "            w->PlayerPositions[i].x = car->State.Position.x;\n"
   "            w->PlayerPositions[i].y = car->State.Position.y;\n"
   "            w->PlayerPositions[i].z = car->State.Position.z;\n")
_m("step dat not copied",
   "            w->PlayerDATs[i] = car->TheTrackPathCoordinate.DistanceAroundTrack;\n", "")
_m("step no player y", "            w->PlayerPositions[i].y = NO_PLAYER;\n", "")
_m("step no player dat", "            w->PlayerDATs[i] = NO_PLAYER;\n", "")
_m("step no player pad", "            w->PlayerPositions[i].z = NO_PLAYER;\n",
   "            w->PlayerPositions[i].z = NO_PLAYER;\n"
   "            w->PlayerPositions[i].pad = NO_PLAYER;\n")
_m("step no player value", "#define NO_PLAYER         9999999.0f",
   "#define NO_PLAYER         999999.0f")
_m("step teleporter null", "if (w->Teleporter != NULL && gTrafficTeleporterDoTimestepFn",
   "if (gTrafficTeleporterDoTimestepFn")
_m("step copthink first",
   "    if (w->Teleporter != NULL && gTrafficTeleporterDoTimestepFn != NULL)\n"
   "        gTrafficTeleporterDoTimestepFn(w->Teleporter, dt);\n"
   "    if (gGlobalCopThinkFn != NULL)\n        gGlobalCopThinkFn(dt);\n",
   "    if (gGlobalCopThinkFn != NULL)\n        gGlobalCopThinkFn(dt);\n"
   "    if (w->Teleporter != NULL && gTrafficTeleporterDoTimestepFn != NULL)\n"
   "        gTrafficTeleporterDoTimestepFn(w->Teleporter, dt);\n")
_m("step think traffic first",
   "    for (i = 0; i < w->CopCarPos - w->AICarPos; i++)\n"
   "        car_think(w->CarTable[w->AICarPos + i], dt);\n"
   "    for (i = 0; i < w->TotalNumCars - w->TrafficCarPos; i++)\n"
   "        car_think(w->CarTable[w->TrafficCarPos + i], dt);\n",
   "    for (i = 0; i < w->TotalNumCars - w->TrafficCarPos; i++)\n"
   "        car_think(w->CarTable[w->TrafficCarPos + i], dt);\n"
   "    for (i = 0; i < w->CopCarPos - w->AICarPos; i++)\n"
   "        car_think(w->CarTable[w->AICarPos + i], dt);\n")
_m("step think no players",
   "    for (i = 0; i < w->AICarPos; i++)\n        car_think(w->CarTable[i], dt);\n",
   "")
_m("step think ai short", "i < w->CopCarPos - w->AICarPos; i++)",
   "i < w->CopCarPos - w->AICarPos - 1; i++)")
_m("step think traffic short", "i < w->TotalNumCars - w->TrafficCarPos; i++)",
   "i < w->TotalNumCars - w->TrafficCarPos - 1; i++)")
_m("step think cops to the end", "i < w->TrafficCarPos - w->CopCarPos; i++)",
   "i < w->TotalNumCars - w->CopCarPos; i++)")
_m("step think players short",
   "for (i = 0; i < w->AICarPos; i++)\n        car_think(",
   "for (i = 1; i < w->AICarPos; i++)\n        car_think(")
_m("step think dt 0", "car_think(w->CarTable[i], dt);", "car_think(w->CarTable[i], 0.0f);")
_m("step wheels for all",
   "for (i = 0; i < w->AICarPos; i++)\n        if (gCarDoWheelForcesFn",
   "for (i = 0; i < w->TotalNumCars; i++)\n        if (gCarDoWheelForcesFn")
_m("step drive dt 0", "car_drive(w->CarTable[i], dt);", "car_drive(w->CarTable[i], 0.0f);")
_m("step drive players only",
   "for (i = 0; i < w->TotalNumCars; i++)\n        car_drive(",
   "for (i = 0; i < w->AICarPos; i++)\n        car_drive(")
_m("step fly null", "if (w->Helicopter != NULL && gChopperFlyFn",
   "if (gChopperFlyFn")
_m("step no begin", "        car_begin_movement(w->CarTable[i], dt);\n",
   "        (void)0;\n")
_m("step collide first",
   "    world_do_timestep_move(w, dt);\n    world_do_timestep_collisions(w, dt);\n",
   "    world_do_timestep_collisions(w, dt);\n    world_do_timestep_move(w, dt);\n")
_m("step finish dt half", "gCarFinishMovementFn(w->CarTable[i], dt);",
   "gCarFinishMovementFn(w->CarTable[i], dt * 0.5f);")
_m("step events 150", "                < 100.0f\n", "                < 150.0f\n")
_m("step events <=", "                < 100.0f\n", "                <= 100.0f\n")
_m("step shakes inverted", "    if (!no_shakes()) {\n", "    if (no_shakes()) {\n")
_m("step rumble not retested", "if (!no_shakes() && gCarMaybeRumbleFn",
   "if (gCarMaybeRumbleFn")
_m("step shakes for all",
   "for (i = 0; i < w->AICarPos; i++) {\n            Car *car = w->CarTable[i];\n\n            if (gCarMaybeCameraShakeFn",
   "for (i = 0; i < w->TotalNumCars; i++) {\n            Car *car = w->CarTable[i];\n\n            if (gCarMaybeCameraShakeFn")
_m("shakes in instant replay", "return s == RCSTATE_INSTANT_REPLAY || s == RCSTATE_POSTRACE",
   "return s == RCSTATE_POSTRACE")
_m("shakes after the race", "|| s == RCSTATE_POSTRACE\n", "\n")
_m("shakes in auto replay", "        || s == RCSTATE_AUTO_REPLAY\n", "")
_m("shakes in demo", "        || racecoordinator_is_replay_demo_mode(pRaceCoordinator);",
   ";")
_m("shakes stopped in pause", "|| s == RCSTATE_POSTRACE\n",
   "|| s == RCSTATE_POSTRACE || s == RCSTATE_PAUSE\n")
_m("step fx dt 0", "gWorldEffectsDoTimeStepFn(dt);", "gWorldEffectsDoTimeStepFn(0.0f);")
_m("step fx order",
   "    if (gWorldEffectsTweakerCheckFn != NULL)\n        gWorldEffectsTweakerCheckFn();\n"
   "    if (gWorldEffectsDoTimeStepFn != NULL)\n        gWorldEffectsDoTimeStepFn(dt);\n",
   "    if (gWorldEffectsDoTimeStepFn != NULL)\n        gWorldEffectsDoTimeStepFn(dt);\n"
   "    if (gWorldEffectsTweakerCheckFn != NULL)\n        gWorldEffectsTweakerCheckFn();\n")
_m("step terrain 100", "if (d < 150.0f && car_should", "if (d < 100.0f && car_should")
_m("step terrain <=", "if (d < 150.0f && car_should", "if (d <= 150.0f && car_should")
_m("step terrain or", "if (d < 150.0f && car_should", "if (d < 150.0f || car_should")
_m("step terrain unasked", "if (d < 150.0f && car_should_visual_effects_be_generated(car))",
   "if (d < 150.0f)")
_m("step terrain d 0", "car_trigger_car_terrain_effects(car, d);",
   "car_trigger_car_terrain_effects(car, 0.0f);")
_m("step no engine", "        car_fake_engine_task(w->CarTable[i]);\n", "        (void)0;\n")
_m("step no sort", "    blist_sort((bNode *)(void *)&w->CarList, car_list_in_order);\n", "")
_m("step rain dt 0", "gRainTimeStepFn(dt);", "gRainTimeStepFn(0.0f);")
_m("step race null", "if (pCurrentRace != NULL && gRaceUpdateFn", "if (gRaceUpdateFn")
_m("step gamestate before events",
   "    if (gEmProcessAllEventsFn != NULL)\n        gEmProcessAllEventsFn();\n"
   "    blist_sort((bNode *)(void *)&w->CarList, car_list_in_order);\n"
   "    if (gUpdatePlayersGameStateFn != NULL)\n        gUpdatePlayersGameStateFn();\n",
   "    if (gUpdatePlayersGameStateFn != NULL)\n        gUpdatePlayersGameStateFn();\n"
   "    if (gEmProcessAllEventsFn != NULL)\n        gEmProcessAllEventsFn();\n"
   "    blist_sort((bNode *)(void *)&w->CarList, car_list_in_order);\n")
_m("step ferns after damage",
   "    if (gServiceFernFlattenersFn != NULL)\n        gServiceFernFlattenersFn();\n"
   "    if (gServiceTweakerDamageFn != NULL)\n        gServiceTweakerDamageFn();\n",
   "    if (gServiceTweakerDamageFn != NULL)\n        gServiceTweakerDamageFn();\n"
   "    if (gServiceFernFlattenersFn != NULL)\n        gServiceFernFlattenersFn();\n")

# bList::Sort
_m("sort inverted", "if (in_order(a, b)) {", "if (in_order(b, a)) {", rel=BL)
_m("sort one pass", "} while (moved != 0);", "} while (0);", rel=BL)
_m("sort a prev kept", "                a->prev = b;\n", "", rel=BL)
_m("sort b prev kept", "                b->prev = p;\n", "", rel=BL)
_m("sort p next kept", "                p->next = b;\n", "", rel=BL)
_m("sort b next kept", "                b->next->prev = b->prev;\n", "", rel=BL)
_m("sort one node", "if (a == list || (b = a->next) == list)",
   "if (a == list || (b = a->next) == list || b->next == list)", rel=BL)


EQUIVALENT = {
}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name

write_source = hostbuild.write_source


def mutate_pass(sc):
    base_model = model(sc)
    survived, missing, equivalent, caught = [], [], [], 0

    with tempfile.TemporaryDirectory() as tmp:
        sp = Path(tmp) / "script.txt"
        write_script(sc, sp)
        exe = hostbuild.build(tmp, SOURCES, name="world_test")
        out = Path(tmp) / "base.txt"
        run_harness(exe, sp, out)
        if diff(base_model, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for name, rel, before, after in MUTATIONS:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = (chr(13) + NL) in text
        probe = before.replace(NL, chr(13) + NL) if crlf else before
        repl = after.replace(NL, chr(13) + NL) if crlf else after

        if probe not in text:
            missing.append(name)
            print("  %-30s PATTERN NOT FOUND" % name)
            continue
        try:
            write_source(path, text.replace(probe, repl, 1))
            with tempfile.TemporaryDirectory() as tmp:
                sp = Path(tmp) / "script.txt"
                write_script(sc, sp)
                try:
                    exe = hostbuild.build(tmp, SOURCES, name="world_test")
                except SystemExit:
                    print("  %-30s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, sp, out)
                if rc == HARNESS_HUNG:
                    print("  %-30s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-30s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base_model, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-30s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-30s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-30s SURVIVED" % name)
                    survived.append(name)
        finally:
            try:
                write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))

    real = [m for m in MUTATIONS if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    stale = [n for n in EQUIVALENT
             if n not in equivalent and n not in missing]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally below is over %d of %d"
              % (len(missing), len(real), len(MUTATIONS)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
    for name in holes:
        print("  unexplained: %s" % name)
    for name in stale:
        ran = any(m[0] == name for m in MUTATIONS)
        print("  listed as equivalent but %s: %s"
              % ("caught" if ran else "names no mutation", name))
    return 1 if (holes or missing or stale) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--dump", metavar="DIR")
    args = ap.parse_args()

    sc = script()
    if args.mutate:
        sys.exit(mutate_pass(sc))

    lines = model(sc)
    with tempfile.TemporaryDirectory() as tmp:
        sp = Path(tmp) / "script.txt"
        write_script(sc, sp)
        exe = hostbuild.build(tmp, SOURCES, name="world_test")
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, sp, out)
        harness = out.read_text().splitlines()

        if args.dump:
            d = Path(args.dump)
            d.mkdir(parents=True, exist_ok=True)
            (d / "model.txt").write_text(NL.join(lines) + NL)
            (d / "harness.txt").write_text(NL.join(harness) + NL)

    bad = diff(lines, harness)
    ops = sum(1 for line in lines if not line.startswith(("  ", "[")))
    steps = sum(1 for line in lines if line.startswith("step "))
    print("%d scenarios, %d ops, %d lines, %d differ; %d steps"
          % (len(sc.tags), ops, len(harness), bad, steps))
    sys.exit(1 if (bad or rc) else 0)


if __name__ == "__main__":
    main()
