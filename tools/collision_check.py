#!/usr/bin/env python3
"""Cross-check 3DS Files/source/collision.c against retail's Collision.obj.

Collision.obj is retail's 0x0021e5c8 .. 0x0021ec54: InitCollision and
CloseCollision, the constructor and destructor, AddImpulse, Update, End,
GetTerrainType and the four questions about who is in a collision, with the
inline bTNode destructor and operator delete. World's two
GetDistanceToClosestPlayer overloads (0x0014e3e8 and 0x0014e440), which the
constructor and AddImpulse call, come with them, from world.c. DoSnapshot is
the replay's and is not ported. The image is the oracle. tools/mipsemu.py
runs the functions out of retail's SLES_507.31 (retail_model.RetailEmu),
the harness (tools/src/collision_test.c) runs the port, both walk the same
script, and the two transcripts are diffed.

The check ran on the demo's NFSHP2.ELF until step 8m-4b. Retail made the
record 112 bytes, its last sixteen the direction of the last impulse near a
player, and changed InitCollision, the constructor and AddImpulse for it
and GetTerrainType for the 144-byte TerrainTypeInfo; so the port took
retail's and the check moved wholly onto the retail image, whose own
TerrainTypeInfoTable is the one terraintypetab.c carries.

The pool is the image's own bNewSlotPool, bOMalloc and bFree against
bslotpool.c, each handed a block the script owns; so a slot label (Cn) is
where the collision is, and the order a freed slot comes back in is checked
along with everything else. The stand-in bodies share one recording vtable,
whose GetVelocity and GetTerrainType take `this` eight bytes in, and the
sound, the particles and the witness's EndCollision are stubs that log.

What the listing says that is easy to get wrong, and which the script
reaches:

  * The constructor asks for a sample only with a point, and only within
    100 of a player in three dimensions; AddImpulse's effects are within 50
    on the ground plane, whatever the height.
  * Without a point the point's first three lanes are zeroed and the
    fourth is left as the slot had it. TotalImpulse's fourth lane is never
    zeroed, and AddImpulse adds all four.
  * The scrape's divide is 0 / 0-free but can be x / 0: ROAD's and
    terrain 31's scrape range is 50 to 50. Either way it clamps to 1.
  * Both velocity calls are on the first body, and both lengths are of the
    first answer, so the scrape always hands the particles body 1's.
  * The impact hands the particles a zero vector on the stack; its fourth
    lane is the stack's, which the transcript does not print.
  * Update subtracts unsigned and converts signed; its argument is unread.
  * GetTerrainType keeps the first body's terrain on a tie.
  * The direction is written only within 50 of a player, after the effects;
    a zero impulse divides the EE's way, FLT_MAX, and makes zeroes.

    python tools/collision_check.py
    python tools/collision_check.py --mutate
    python tools/collision_check.py --dump out/collision
"""
import argparse
import difflib
import math
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import mipsemu as me
import retail_model

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)
M32 = 0xFFFFFFFF

SOURCES = [
    "tools/src/collision_test.c",
    "3DS Files/source/collision.c",
    "3DS Files/source/world.c",
    "3DS Files/source/bslotpool.c",
    "3DS Files/source/vtable.c",
    "3DS Files/source/terraintypetab.c",
]

CC = "3DS Files/source/collision.c"
CH = "3DS Files/source/collision.h"
WC = "3DS Files/source/world.c"

GP = retail_model.RETAIL_GP
G_WORLD = GP - 22120                # pCurrentWorld
G_TIMER = GP - 19576                # WorldTimer
G_POOL = GP - 15880                 # CollisionSlotPool
G_LIFETIME = GP - 15884             # CollisionLifetime
G_TEE = GP - 15816                  # pTerrainEffectEmitters
HEADER = 48                         # a SlotPool's header on the console
REC = 112                           # retail's Collision

NB, NW, NCAR, NS, NPT = 4, 4, 2, 4, 4
NSLOT = 32
DELTA = 8
FN_VEL, FN_TT = 0x01F00000, 0x01F00010

SYM = dict(
    init="InitCollision__Fv",
    close="CloseCollision__Fv",
    ctor="__9CollisionP20CollisionBodyWitnessP8bVector3",
    dtor="_$_9Collision",
    omalloc="bOMalloc__FP8SlotPool",
    impulse="AddImpulse__9CollisionP8bVector3T1f",
    update="Update__9Collisionf",
    end="End__9Collision",
    tt="GetTerrainType__9Collision",
    two="IsTwoCarCollision__9Collision",
    cars="GetCollidingCars__9CollisionPP3CarT1",
    player="IsPlayerInvolved__9Collision",
    smoke="IsSmokeableInvolved__9Collision",
    dist2="GetDistanceToClosestPlayer__5WorldPC8bVector2",
    dist3="GetDistanceToClosestPlayer__5WorldPC8bVector3",
)

(OP_TAG, OP_INIT, OP_CLOSE, OP_NEW, OP_DESTROY, OP_IMPULSE, OP_UPDATE,
 OP_END, OP_TT, OP_TWO, OP_CARS, OP_PLAYER, OP_SMOKE, OP_BODY, OP_WITNESS,
 OP_BODYCAR, OP_CARPLAYER, OP_PLAYERS, OP_TIMER, OP_LIFETIME, OP_SAMPLE,
 OP_DUMP, OP_LIST, OP_POINT, OP_DIST3, OP_DIST2, OP_RAW) = range(1, 28)

bits = me.f_to_bits
NAN = 0x7FC00000
INF = 0x7F800000


def s32(x):
    x &= M32
    return x - (1 << 32) if x & 0x80000000 else x


def fw(v):
    """A float operand: bits as given, or a Python float's."""
    return v if isinstance(v, int) else bits(v)


# ---------------------------------------------------------------- the script


class Script(object):
    """The ops, and enough of the pool's bookkeeping to keep the script
    inside it: which handles are live (on the list), and how many slots are
    taken, counting the ones a destroy without flag 1 leaves behind. A raw
    collision (R0, R1) is not the pool's, so its destroy never has flag 1."""

    def __init__(self):
        self.words = []
        self.tags = []
        self.nhandles = 0
        self.live = []
        self.raws = {}                  # handle -> raw buffer
        self.taken = 0
        self.pool = False

    def op(self, code, *args):
        self.words.append(code)
        self.words.extend(a & M32 for a in args)

    def tag(self, name):
        self.op(OP_TAG, len(self.tags))
        self.tags.append(name)

    def init(self):
        assert not self.pool
        self.op(OP_INIT)
        self.pool = True
        self.taken = 0

    def close(self):
        for h in list(self.live):
            self.destroy(h, 2 if h in self.raws else 3)
        self.op(OP_CLOSE)
        self.pool = False

    def raw(self, k, w, p=None):
        assert k not in self.raws.values()
        self.op(OP_RAW, k, w, 0 if p is None else p + 1)
        h = self.nhandles
        self.nhandles += 1
        self.live.append(h)
        self.raws[h] = k
        return h

    def new(self, w, p=None):
        """p is a point index, or None for no point."""
        assert self.pool and self.taken < NSLOT
        self.op(OP_NEW, w, 0 if p is None else p + 1)
        h = self.nhandles
        self.nhandles += 1
        self.live.append(h)
        self.taken += 1
        return h

    def destroy(self, h, flags):
        assert h in self.live
        self.op(OP_DESTROY, h, flags)
        self.live.remove(h)
        if h in self.raws:
            assert not flags & 1
            del self.raws[h]
        elif flags & 1:
            self.taken -= 1

    def impulse(self, h, at, imp, scrape):
        at = list(at) + [0.0] * (4 - len(at))
        imp = list(imp) + [0.0] * (4 - len(imp))
        self.op(OP_IMPULSE, h, *[fw(v) for v in at + imp + [scrape]])

    def body(self, k, typ, tt, v=(0.0, 0.0, 0.0, 0.0)):
        v = list(v) + [0.0] * (4 - len(v))
        self.op(OP_BODY, k, typ & 0xFF, tt, *[fw(x) for x in v])

    def players(self, p0, p1):
        p0 = list(p0) + [0.0] * (4 - len(p0))
        p1 = list(p1) + [0.0] * (4 - len(p1))
        self.op(OP_PLAYERS, *[fw(x) for x in p0 + p1])

    def point(self, k, v):
        v = list(v) + [0.0] * (4 - len(v))
        self.op(OP_POINT, k, *[fw(x) for x in v])

    def dist3(self, v):
        v = list(v) + [0.0] * (4 - len(v))
        self.op(OP_DIST3, *[fw(x) for x in v])

    def dist2(self, x, y):
        self.op(OP_DIST2, fw(x), fw(y))


FAR = 9999999.0


def script():
    sc = Script()

    sc.tag("the distances")
    for p0, p1 in (((0.0, 0.0, 0.0), (100.0, 0.0, 0.0)),
                   ((3.0, 4.0, 12.0, 7.0), (-3.0, -4.0, -12.0, -7.0)),
                   ((FAR, FAR, FAR), (10.0, 20.0, 30.0)),
                   ((FAR, FAR, FAR), (FAR, FAR, FAR)),
                   ((1.5, -2.25, 1000.0), (1.5, -2.25, -1000.0))):
        sc.players(p0, p1)
        for q in ((0.0, 0.0, 0.0), (50.0, 0.0, 0.0), (49.0, 0.0, 0.0),
                  (51.0, 1.0, 0.0), (3.0, 4.0, 0.0), (0.0, 0.0, 12.0),
                  (1e20, 0.0, 0.0), (-1e-20, 3e-20, 0.0),
                  (1.5, -2.25, 0.0, 99.0), (123.456, -78.9, 0.001),
                  (10.0, 20.0, 30.0, -1.0), (INF, 0.0, 0.0),
                  (0.1, 0.2, 0.3)):
            sc.dist3(q)
            sc.dist2(q[0], q[1])
    rnd = random.Random(20260926)
    for _ in range(40):
        sc.players([rnd.uniform(-500, 500) for _ in range(4)],
                   [rnd.uniform(-500, 500) for _ in range(4)])
        for _ in range(4):
            q = [rnd.uniform(-600, 600) for _ in range(4)]
            sc.dist3(q)
            sc.dist2(q[0], q[1])

    sc.tag("the world and the first collision, with no point")
    sc.players((0.0, 0.0, 0.0), (FAR, FAR, FAR))
    sc.body(0, 0, 1, (10.0, 0.0, 0.0, 0.5))
    sc.body(1, 0, 17, (0.0, -20.0, 5.0, 0.25))
    sc.body(2, 1, 6, (3.0, 4.0, 0.0))
    sc.body(3, 2, 32, (-1.0, -1.0, -1.0, -1.0))
    for w, (b1, b2) in enumerate(((0, 1), (1, 0), (0, 2), (2, 3))):
        sc.op(OP_WITNESS, w, b1, b2)
    sc.op(OP_BODYCAR, 0, 0)
    sc.op(OP_BODYCAR, 1, 1)
    sc.op(OP_BODYCAR, 2, 1)
    sc.op(OP_BODYCAR, 3, 0xFFFFFFFF)
    sc.op(OP_TIMER, 1000)
    sc.init()
    sc.op(OP_LIST)
    h0 = sc.new(0)
    sc.op(OP_LIST)

    sc.tag("a point near a player asks for a sample")
    sc.point(0, (10.0, 0.0, 0.0, 3.0))
    sc.op(OP_SAMPLE, 1)
    sc.op(OP_TIMER, 2000)
    h1 = sc.new(1, 0)
    sc.op(OP_LIST)
    sc.op(OP_DUMP, h0)

    sc.tag("100 away is not near")
    sc.point(1, (100.0, 0.0, 0.0))
    sc.op(OP_SAMPLE, 2)
    h2 = sc.new(2, 1)
    sc.point(1, (0.0, 0.0, 99.99999))
    h3 = sc.new(3, 1)                   # and takes the queued S2
    sc.point(2, (0.0, 60.0, 80.0))      # exactly 100, in all three lanes
    h4 = sc.new(0, 2)
    sc.op(OP_SAMPLE, 0)
    sc.point(3, (0.0, 0.0, -5.0, -1.0))
    h5 = sc.new(1, 3)                   # asked for, and the sound has none
    sc.op(OP_LIST)

    sc.tag("destroying")
    sc.destroy(h2, 3)
    sc.op(OP_LIST)
    sc.op(OP_DUMP, h1)
    sc.op(OP_DUMP, h3)
    h6 = sc.new(2)                      # back into h2's slot
    sc.destroy(h1, 0)                   # off the list; the slot stays taken
    sc.op(OP_LIST)
    h7 = sc.new(3, 0)
    sc.destroy(h6, 2)
    sc.destroy(h7, 1)
    sc.op(OP_LIST)
    h8 = sc.new(0)
    h9 = sc.new(1)
    sc.destroy(h0, 3)
    sc.destroy(h9, 3)
    sc.op(OP_LIST)
    sc.destroy(h8, 3)
    sc.op(OP_LIST)

    sc.tag("on dirty memory")
    sc.op(OP_TIMER, 3000)
    r0 = sc.raw(0, 2)                   # no point: three lanes zeroed
    sc.point(0, (5.0, -5.0, 5.0, -2.0))
    sc.op(OP_SAMPLE, 3)
    r1 = sc.raw(1, 3, 0)
    sc.op(OP_LIST)
    sc.op(OP_TIMER, 3100)
    sc.impulse(r1, (5.0, 5.0, 0.0), (20.0, 0.0, 0.0, 1.0), 30.0)
    sc.impulse(r0, (500.0, 5.0, 0.0), (0.0, 0.0, 0.0), 0.0)
    sc.op(OP_UPDATE, r0, bits(1.0 / 60))
    sc.destroy(r0, 0)
    sc.op(OP_LIST)
    sc.point(1, (500.0, 0.0, 0.0, 4.0))
    r2 = sc.raw(0, 1, 1)                # a point, and no player near it
    sc.op(OP_LIST)
    sc.destroy(r1, 2)
    sc.destroy(r2, 0)
    sc.op(OP_LIST)

    sc.tag("impulses")
    sc.op(OP_TIMER, 5000)
    ha = sc.new(0)                      # B0 ROAD, B1 SOLID_WALL: road wins
    sc.op(OP_TIMER, 5040)
    sc.impulse(ha, (10.0, 10.0, 500.0, 1.0), (1.0, 2.0, 2.0, 0.5), 10.0)
    sc.impulse(ha, (10.0, 10.0, 0.0), (30.0, 40.0, 0.0, -1.0), 50.0)
    sc.impulse(ha, (10.0, 10.0, 0.0), (30.0, 40.0, 0.0), 50.5)
    sc.impulse(ha, (-20.0, 30.0, 0.0), (60.0, 80.0, 0.0), 200.0)
    sc.impulse(ha, (0.0, 49.99999, 0.0), (0.0, 0.0, 200.0), 60.0)
    sc.impulse(ha, (0.0, 50.0, 0.0), (0.0, 0.0, 200.0), 60.0)
    sc.impulse(ha, (30.0, 40.0, 0.0), (0.0, 0.0, 200.0), 60.0)
    sc.impulse(ha, (29.0, 40.0, 0.0), (0.0, -150.0, 0.0), 60.0)
    sc.impulse(ha, (1.0, 1.0, 1.0), (0.0, 0.0, 0.0, 9.0), -5.0)
    sc.impulse(ha, (1.0, 1.0, 1.0), (1e20, 0.0, 0.0), INF)
    sc.impulse(ha, (1.0, 1.0, 1.0), (1.0, 1.0, 1.0), NAN)
    hb = sc.new(3)                      # B2 GRASS, B3 terrain 32: grass
    for scrape in (10.0, 15.0, 15.001, 20.0, 32.5, 50.0, 80.0):
        sc.impulse(hb, (5.0, 5.0, 5.0), (10.0, 0.0, 0.0), scrape)
    for f in (14.0, 15.0, 15.5, 57.5, 100.0, 150.0):
        sc.impulse(hb, (5.0, 5.0, 5.0), (0.0, f, 0.0), 0.0)
    sc.op(OP_DUMP, hb)

    sc.tag("the terrains and their priorities")
    for t1, t2 in ((1, 17), (17, 1), (0, 1), (1, 0), (4, 6), (6, 4),
                   (2, 3), (3, 2), (30, 32), (32, 30), (15, 16), (16, 15),
                   (29, 9), (28, 20), (31, 32), (32, 31)):
        sc.body(0, 0, t1, (10.0, 0.0, 0.0, 0.5))
        sc.body(1, 0, t2, (0.0, -20.0, 5.0, 0.25))
        sc.op(OP_TT, ha)
    for t1, t2 in ((0, 0), (1, 1), (31, 31), (32, 32), (15, 15), (17, 17),
                   (6, 6), (2, 2)):
        sc.body(0, 0, t1, (10.0, 0.0, 0.0, 0.5))
        sc.body(1, 0, t2, (0.0, -20.0, 5.0, 0.25))
        for scrape, f in ((10.0, 0.0), (51.0, 0.0), (2.5, 12.0),
                          (16.0, 16.0), (35.0, 75.0), (120.0, 1000.0)):
            sc.impulse(ha, (2.0, 3.0, 4.0), (f, 0.0, 0.0), scrape)

    sc.tag("who is in it")
    hc = sc.new(0)
    sc.op(OP_CARPLAYER, 0, 0)
    sc.op(OP_CARPLAYER, 1, 0)
    for t1, t2 in ((0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (0, 2),
                   (0xFF, 0), (0, 0xFF), (1, 2), (2, 1), (2, 2), (3, 1)):
        sc.body(0, t1, 1)
        sc.body(1, t2, 1)
        for c0, c1 in ((0, 1), (0xFFFFFFFF, 1), (0, 0xFFFFFFFF),
                       (0xFFFFFFFF, 0xFFFFFFFF), (1, 1)):
            sc.op(OP_BODYCAR, 0, c0)
            sc.op(OP_BODYCAR, 1, c1)
            for p0, p1 in ((0, 0), (1, 0), (0, 1), (1, 1)):
                sc.op(OP_CARPLAYER, 0, p0)
                sc.op(OP_CARPLAYER, 1, p1)
                sc.op(OP_PLAYER, hc)
            sc.op(OP_CARS, hc)
        sc.op(OP_TWO, hc)
        sc.op(OP_SMOKE, hc)

    sc.tag("update")
    sc.op(OP_TIMER, 10000)
    hd = sc.new(1)
    for t in (10000, 10001, 11199, 11200, 11201, 9999, 20000,
              10000 + 0x7FFFFFFF, 10000 + 0x80000000, 10000 + 0xFFFFFFFF,
              0, 0xFFFFFFFF):
        sc.op(OP_TIMER, t)
        for dt in (0.0, 1.0 / 60, -1.0):
            sc.op(OP_UPDATE, hd, bits(dt))
    for life in (0.0, -0.0, -1.0, 0.00025, 0.0005, 1e9, INF, NAN, 0.3):
        sc.op(OP_LIFETIME, fw(life))
        for t in (10000, 10001, 10002, 9999, 11200, 0x7FFFFFFF):
            sc.op(OP_TIMER, t)
            sc.op(OP_UPDATE, hd, bits(1.0 / 60))
    sc.op(OP_TIMER, 10000)
    sc.impulse(hd, (500.0, 500.0, 0.0), (1.0, 0.0, 0.0), 0.0)
    sc.op(OP_TIMER, 11300)
    sc.op(OP_UPDATE, hd, bits(1.0 / 60))

    sc.tag("update, the tick's own rounding")
    # 0.00025 is 3983126f, a hair over a 4000th: five ticks make 3aa3d70b,
    # where a divide by 4000 makes 3aa3d70a. A lifetime just past 1200 and
    # 4000 ticks tells the tick from one a few ulps away.
    for age, life in ((5, 0x3AA3D70B), (5, 0x3AA3D70A), (9, 991130813),
                      (1199, 0x3E999AE9), (1200, 0x3E999AE9),
                      (1201, 0x3E999AE9), (4000, 0x3F800008),
                      (4001, 0x3F800008)):
        sc.op(OP_LIFETIME, life)
        sc.op(OP_TIMER, 10000 + age)
        sc.op(OP_UPDATE, hd, bits(1.0 / 60))
    sc.op(OP_LIFETIME, bits(0.3))

    sc.tag("end")
    for h in (ha, hb, hc, hd):
        sc.op(OP_END, h)

    sc.tag("close and again")
    sc.close()
    sc.op(OP_LIST)
    sc.init()
    he = sc.new(2)
    sc.op(OP_LIST)
    sc.destroy(he, 3)

    sc.tag("a full pool")
    hs = [sc.new(k % NW) for k in range(NSLOT)]
    sc.op(OP_LIST)
    for h in hs[::3]:
        sc.destroy(h, 3)
    sc.op(OP_LIST)
    for _ in range(len(hs[::3])):
        sc.new(1)
    sc.op(OP_LIST)
    sc.close()

    sc.tag("a random walk")
    rnd = random.Random(26092026)
    sc.init()
    timer = 50000
    sc.op(OP_TIMER, timer)
    for _ in range(1500):
        k = rnd.random()
        if k < 0.12 and sc.taken < NSLOT:
            p = rnd.choice([None, 0, 1, 2, 3])
            if p is not None:
                sc.point(p, [rnd.uniform(-150, 150) for _ in range(4)])
            if rnd.random() < 0.7:
                sc.op(OP_SAMPLE, rnd.randrange(NS + 1))
            sc.new(rnd.randrange(NW), p)
        elif k < 0.13:
            free = [r for r in (0, 1) if r not in sc.raws.values()]
            if free:
                p = rnd.choice([None, 0, 1, 2, 3])
                if p is not None:
                    sc.point(p, [rnd.uniform(-150, 150) for _ in range(4)])
                sc.raw(rnd.choice(free), rnd.randrange(NW), p)
        elif k < 0.18 and sc.live:
            h = rnd.choice(sc.live)
            sc.destroy(h, rnd.choice([0, 2] if h in sc.raws
                                     else [3, 3, 3, 1, 0, 2]))
        elif k < 0.45 and sc.live:
            h = rnd.choice(sc.live)
            at = [rnd.uniform(-80, 80) for _ in range(4)]
            imp = [rnd.choice([rnd.uniform(-10, 10), rnd.uniform(-150, 150),
                               0.0]) for _ in range(4)]
            scrape = rnd.choice([rnd.uniform(0, 120), rnd.uniform(-5, 5),
                                 50.0, 15.0, 2.0])
            sc.impulse(h, at, imp, scrape)
        elif k < 0.55 and sc.live:
            timer = (timer + rnd.choice([1, 17, 67, 400, 1199, 1200, 1201,
                                         5000])) & M32
            sc.op(OP_TIMER, timer)
            sc.op(OP_UPDATE, rnd.choice(sc.live), bits(1.0 / 60))
        elif k < 0.62 and sc.live:
            sc.op(rnd.choice([OP_TT, OP_TWO, OP_CARS, OP_PLAYER, OP_SMOKE,
                              OP_END, OP_DUMP]), rnd.choice(sc.live))
        elif k < 0.70:
            sc.body(rnd.randrange(NB), rnd.choice([0, 0, 1, 2, 0xFF]),
                    rnd.randrange(33),
                    [rnd.uniform(-50, 50) for _ in range(4)])
        elif k < 0.74:
            sc.op(OP_WITNESS, rnd.randrange(NW), rnd.randrange(NB),
                  rnd.randrange(NB))
        elif k < 0.77:
            sc.op(OP_BODYCAR, rnd.randrange(NB),
                  rnd.choice([0, 1, 0xFFFFFFFF]))
        elif k < 0.80:
            sc.op(OP_CARPLAYER, rnd.randrange(NCAR), rnd.randrange(2))
        elif k < 0.84:
            sc.players([rnd.uniform(-100, 100) for _ in range(4)],
                       rnd.choice([[FAR, FAR, FAR, 0.0],
                                   [rnd.uniform(-100, 100)
                                    for _ in range(4)]]))
        elif k < 0.86:
            sc.op(OP_LIFETIME, bits(rnd.choice([0.3, 0.1, 1.0, 0.3])))
        elif k < 0.88:
            sc.op(OP_LIST)
        elif k < 0.885:
            sc.close()
            sc.init()
    sc.op(OP_LIST)
    sc.close()
    return sc


# ================================================================ the model


class Model(object):
    def __init__(self, sc):
        self.sc = sc
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        e.stub_bware()
        self.fn = {k: e.addr_of(v) for k, v in SYM.items()}
        a = e.alloc
        self.world = a(512, 16)
        self.head = self.world + 16
        self.bodies = [a(512, 16) for _ in range(NB)]
        self.vt = a(26 * 8, 16)
        self.vel = a(16 * NB, 16)
        self.wit = [a(128, 16) for _ in range(NW)]
        self.cars = [a(64, 16) for _ in range(NCAR)]
        self.player = a(16, 16)
        self.samples = a(16 * NS, 16)
        self.tee = a(16, 16)
        self.pts = a(16 * NPT, 16)
        self.at = a(16, 16)
        self.imp = a(16, 16)
        self.outw = a(16, 16)
        self.vec = a(16, 16)
        self.raw = [a(REC, 16) for _ in range(2)]
        self.arena_n = HEADER + NSLOT * REC + 64
        self.arena = a(self.arena_n, 16)
        self.terrain = [0] * NB
        self.handles = []
        self.queue = []

        e.put32(self.head, self.head)
        e.put32(self.head + 4, self.head)
        e.put32(G_WORLD, self.world)
        e.put32(G_TEE, self.tee)
        e.put32(G_TIMER, 0)
        for b in self.bodies:
            e.put32(b + 80, self.vt)
        for slot, fn in ((32, FN_VEL), (144, FN_TT)):
            e.write(self.vt + slot, bytes([DELTA, 0, 0, 0]))
            e.put32(self.vt + slot + 4, fn)
        self.stubs()
        done = e.run_ctors(r"bNewSlotPool__FiiPCci$")
        assert len(done) == 1, done

    def emit(self, s):
        self.out.append(s)

    def cstr(self, p):
        end = self.e.mem.index(b"\0", p)
        return self.e.mem[p:end].decode("latin-1")

    def label(self, p):
        e = self.e
        p &= M32
        if p == 0:
            return "null"
        if p == 0xA5A5A5A5:
            return "dirty"
        for i, r in enumerate(self.raw):
            if p == r:
                return "R%d" % i
        if p == self.head:
            return "head"
        pool = e.u32(G_POOL)
        if pool:
            n, sz = e.u32(pool + 36), e.u32(pool + 40)
            d = p - (pool + HEADER)
            if 0 <= d < n * sz:
                if d % sz:
                    return "C%d+%d" % (d // sz, d % sz)
                return "C%d" % (d // sz)
        for i, w in enumerate(self.wit):
            if p == w:
                return "W%d" % i
        for i, b in enumerate(self.bodies):
            if p == b:
                return "B%d" % i
            if p == self.vel + 16 * i:
                return "B%d.v" % i
        for i, c in enumerate(self.cars):
            if p == c:
                return "CAR%d" % i
        for i in range(NS):
            if p == self.samples + 16 * i:
                return "S%d" % (i + 1)
        if p == self.tee:
            return "TEE"
        if p == self.at:
            return "at"
        if p == self.imp:
            return "imp"
        for i in range(NPT):
            if p == self.pts + 16 * i:
                return "P%d" % i
        if e.RAM - 0x110000 <= p < e.RAM:
            return "local"
        return "?%08x" % p

    def f32(self, a):
        return self.e.u32(a)

    def stubs(self):
        e = self.e

        def arg(i):
            return e.reg[4 + i] & M32

        def malloc(em):
            size, name = s32(arg(0)), self.cstr(arg(1))
            assert name == "CollisionSlotPool", name
            assert size <= self.arena_n, size
            e.mem[self.arena:self.arena + self.arena_n] = bytes(self.arena_n)
            self.emit("  pool alloc %s mp %d" % (name, s32(arg(3))))
            return self.arena

        def free(em):
            self.emit("  pool free %s" % ("CollisionSlotPool"
                                          if arg(0) == self.arena else "?"))
            return 0

        def printf(em):
            self.emit("  printf")
            return 0

        def brk(em):
            raise AssertionError("the script reaches bBreak")

        def create(em):
            s = self.queue.pop(0) if self.queue else 0
            p = self.samples + 16 * (s - 1) if s else 0
            self.emit("  create sample %s -> %s"
                      % (self.label(arg(0)), self.label(p)))
            return p

        def release(em):
            c = arg(0)
            self.emit("  release sample %s (%s)"
                      % (self.label(c), self.label(e.u32(c + 88))))
            return 0

        def scrape(em):
            self.emit("  play scrape %s" % self.label(arg(0)))
            return 0

        def trigger(em):
            at, v = arg(3), e.reg[8] & M32
            self.emit("  effect %s %d tt %d scale %08x at %s %08x %08x %08x"
                      " vel %s %08x %08x %08x"
                      % (self.label(arg(0)), s32(arg(1)), s32(arg(2)),
                         e.fpr[12] & M32, self.label(at), e.u32(at),
                         e.u32(at + 4), e.u32(at + 8), self.label(v),
                         e.u32(v), e.u32(v + 4), e.u32(v + 8)))
            return 0

        def end(em):
            self.emit("  end collision %s" % self.label(arg(0)))
            return 0

        def body_of(this):
            for i, b in enumerate(self.bodies):
                if this - DELTA == b:
                    return i
            raise AssertionError("a slot called on %08x" % this)

        def vel(em):
            k = body_of(arg(0))
            self.emit("  vel B%d" % k)
            return self.vel + 16 * k

        def tt(em):
            k = body_of(arg(0))
            self.emit("  tt B%d -> %d" % (k, self.terrain[k]))
            return self.terrain[k] & M32

        e.stub("bMalloc__FiPCcii", malloc)
        e.stub("bFree__FPv", free)
        e.stub("bPrintf__FPCce", printf)
        e.stub("bBreak__Fv", brk)
        e.stub("CreateSample__15collision_soundP9Collision", create)
        e.stub("ReleaseSample__15collision_soundP9Collision", release)
        e.stub("PlayScrape__15collision_soundP9Collision", scrape)
        e.stub("TriggerEffect__21TerrainEffectEmitters13TerrainEffect"
               "11TerrainTypefPC8bVector3T4", trigger)
        e.stub("EndCollision__20CollisionBodyWitness", end)
        e.stub(FN_VEL, vel)
        e.stub(FN_TT, tt)

    def v4(self, name, a):
        e = self.e
        return " %s %08x %08x %08x %08x" % (name, e.u32(a), e.u32(a + 4),
                                           e.u32(a + 8), e.u32(a + 12))

    def dump(self, c):
        e, L = self.e, self.label
        self.emit("  %s next %s prev %s ct %08x lct %08x"
                  % (L(c), L(e.u32(c)), L(e.u32(c + 4)), e.u32(c + 8),
                     e.u32(c + 12)))
        self.emit(" " + self.v4("init", c + 16) + self.v4("cur", c + 32)
                  + " speed %08x" % e.u32(c + 48))
        self.emit(" " + self.v4("imp", c + 64)
                  + " mag %08x wit %s sample %s scrape %s"
                  % (e.u32(c + 80), L(e.u32(c + 84)), L(e.u32(c + 88)),
                     L(e.u32(c + 92))))
        self.emit(" " + self.v4("dir", c + 96))

    def list(self):
        e, L = self.e, self.label
        fwd, back = [], []
        p, n = e.u32(self.head), 0
        while p != self.head and n < 40:
            fwd.append(L(p))
            p, n = e.u32(p), n + 1
        p, n = e.u32(self.head + 4), 0
        while p != self.head and n < 40:
            back.append(L(p))
            p, n = e.u32(p + 4), n + 1
        self.emit("  fwd" + "".join(" " + s for s in fwd))
        self.emit("  back" + "".join(" " + s for s in back))

    def put_vec(self, a, ws):
        for j, w in enumerate(ws):
            self.e.put32(a + 4 * j, w)

    def run(self):
        e, w, L = self.e, self.sc.words, self.label
        emit = self.emit
        i = 0

        def arg():
            nonlocal i
            i += 1
            return w[i - 1]

        def args(n):
            return [arg() for _ in range(n)]

        def call(name, *a):
            return e.call(self.fn[name], *a)

        while i < len(w):
            op = arg()
            if op == OP_TAG:
                emit("[%d]" % arg())
            elif op in (OP_INIT, OP_CLOSE):
                emit("init" if op == OP_INIT else "close")
                call("init" if op == OP_INIT else "close")
                pool = e.u32(G_POOL)
                emit("  pool made, %d slots" % s32(e.u32(pool + 36))
                     if pool else "  pool null")
            elif op == OP_RAW:
                k, wi, p = arg(), arg(), arg()
                emit("raw R%d W%d P%d" % (k, wi, p - 1))
                e.write(self.raw[k], b"\xa5" * REC)
                c = call("ctor", self.raw[k], self.wit[wi],
                         self.pts + 16 * (p - 1) if p else 0) & M32
                self.handles.append(c)
                emit("  -> %s" % L(c))
                self.dump(c)
            elif op == OP_NEW:
                wi, p = arg(), arg()
                emit("new W%d P%d" % (wi, p - 1))
                m = call("omalloc", e.u32(G_POOL)) & M32
                c = call("ctor", m, self.wit[wi],
                         self.pts + 16 * (p - 1) if p else 0) & M32
                self.handles.append(c)
                emit("  -> %s" % L(c))
                self.dump(c)
            elif op == OP_DESTROY:
                c, flags = self.handles[arg()], s32(arg())
                emit("destroy %s %d" % (L(c), flags))
                call("dtor", c, flags)
            elif op == OP_IMPULSE:
                c = self.handles[arg()]
                at, imp, sb = args(4), args(4), arg()
                self.put_vec(self.at, at)
                self.put_vec(self.imp, imp)
                emit("impulse %s at %08x %08x %08x %08x imp %08x %08x %08x"
                     " %08x scrape %08x" % tuple([L(c)] + at + imp + [sb]))
                e.fpr[12] = sb
                call("impulse", c, self.at, self.imp)
                self.dump(c)
            elif op == OP_UPDATE:
                c, dt = self.handles[arg()], arg()
                e.fpr[12] = dt
                r = call("update", c)
                emit("update %s %08x -> %d" % (L(c), dt, r))
            elif op == OP_END:
                c = self.handles[arg()]
                emit("end %s" % L(c))
                call("end", c)
            elif op == OP_TT:
                c = self.handles[arg()]
                emit("tt %s" % L(c))
                emit("  -> %d" % call("tt", c))
            elif op == OP_TWO:
                c = self.handles[arg()]
                emit("two %s -> %d" % (L(c), call("two", c)))
            elif op == OP_CARS:
                c = self.handles[arg()]
                e.put32(self.outw, self.tee)
                e.put32(self.outw + 4, self.tee)
                call("cars", c, self.outw, self.outw + 4)
                emit("cars %s -> %s %s" % (L(c), L(e.u32(self.outw)),
                                           L(e.u32(self.outw + 4))))
            elif op == OP_PLAYER:
                c = self.handles[arg()]
                emit("player %s -> %d" % (L(c), call("player", c)))
            elif op == OP_SMOKE:
                c = self.handles[arg()]
                emit("smoke %s -> %d" % (L(c), call("smoke", c)))
            elif op == OP_BODY:
                k, typ, tt = arg(), arg(), s32(arg())
                v = args(4)
                self.terrain[k] = tt
                self.put_vec(self.vel + 16 * k, v)
                e.mem[self.bodies[k] + 12] = typ & 0xFF
                emit("body B%d type %d tt %d"
                     % (k, typ - 256 if typ & 0x80 else typ, tt))
            elif op == OP_WITNESS:
                wi, b1, b2 = arg(), arg(), arg()
                e.put32(self.wit[wi] + 96, self.bodies[b1])
                e.put32(self.wit[wi] + 100, self.bodies[b2])
                emit("witness W%d B%d B%d" % (wi, b1, b2))
            elif op == OP_BODYCAR:
                k, car = arg(), s32(arg())
                e.put32(self.bodies[k] + 256,
                        self.cars[car] if car >= 0 else 0)
                emit("bodycar B%d %s" % (k, L(e.u32(self.bodies[k] + 256))))
            elif op == OP_CARPLAYER:
                k, on = arg(), arg()
                e.put32(self.cars[k] + 24, self.player if on else 0)
                emit("carplayer CAR%d %d" % (k, on))
            elif op == OP_PLAYERS:
                self.put_vec(self.world + 336, args(8))
                emit("players" + self.v4("p0", self.world + 336)
                     + self.v4("p1", self.world + 352))
            elif op == OP_TIMER:
                t = arg()
                e.put32(G_TIMER, t)
                emit("timer %08x" % t)
            elif op == OP_LIFETIME:
                b = arg()
                e.put32(G_LIFETIME, b)
                emit("lifetime %08x" % b)
            elif op == OP_SAMPLE:
                self.queue.append(arg())
            elif op == OP_DUMP:
                self.dump(self.handles[arg()])
            elif op == OP_LIST:
                emit("list")
                self.list()
            elif op == OP_POINT:
                k = arg()
                v = args(4)
                self.put_vec(self.pts + 16 * k, v)
                emit("point P%d" % k + self.v4("", self.pts + 16 * k))
            elif op == OP_DIST3:
                v = args(4)
                self.put_vec(self.vec, v)
                call("dist3", self.world, self.vec)
                emit("dist3 %08x %08x %08x -> %08x"
                     % (v[0], v[1], v[2], e.fpr[0] & M32))
            elif op == OP_DIST2:
                v = args(2)
                self.put_vec(self.vec, v)
                call("dist2", self.world, self.vec)
                emit("dist2 %08x %08x -> %08x" % (v[0], v[1],
                                                 e.fpr[0] & M32))
            else:
                raise SystemExit("op %d" % op)
        return self.out


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


def _m(name, old, new, rel=CC):
    MUTATIONS.append((name, rel, old, new))


# the globals and the literals
_m("lifetime", "CollisionLifetime = 0.3f;", "CollisionLifetime = 0.31f;")
_m("lifetime-near", "CollisionLifetime = 0.3f;",
   "CollisionLifetime = 0.29999998f;")
_m("sample-distance", "SAMPLE_DISTANCE   100.0f", "SAMPLE_DISTANCE   100.001f")
_m("sample-distance-near", "SAMPLE_DISTANCE   100.0f",
   "SAMPLE_DISTANCE   99.9999f")
_m("effect-distance", "EFFECT_DISTANCE    50.0f", "EFFECT_DISTANCE    50.001f")
_m("effect-distance-near", "EFFECT_DISTANCE    50.0f",
   "EFFECT_DISTANCE    49.9999f")
_m("tick", "TICK_SECONDS      0.00025f", "TICK_SECONDS      0.00026f")
_m("tick-near", "TICK_SECONDS      0.00025f", "TICK_SECONDS      0.00025001f")

# InitCollision and CloseCollision
_m("init-slots", "bNewSlotPool((int)sizeof(Collision), 32,",
   "bNewSlotPool((int)sizeof(Collision), 31,")
_m("init-slot-size", "bNewSlotPool((int)sizeof(Collision), 32,",
   "bNewSlotPool((int)sizeof(Collision) - 16, 32,")
_m("init-mp", "\"CollisionSlotPool\", 16);", "\"CollisionSlotPool\", 15);")
_m("init-name", "\"CollisionSlotPool\", 16);", "\"CollisionPool\", 16);")
_m("close-keeps-pointer", "    CollisionSlotPool = NULL;" + NL, "")
_m("close-no-delete", "    bDeleteSlotPool(CollisionSlotPool);" + NL, "")

# the constructor
_m("ctor-imp-x", "    c->TotalImpulse.x = 0.0f;" + NL, "")
_m("ctor-imp-y", "    c->TotalImpulse.y = 0.0f;" + NL, "")
_m("ctor-imp-z", "    c->TotalImpulse.z = 0.0f;" + NL, "")
_m("ctor-imp-pad", "    c->TotalImpulse.z = 0.0f;" + NL,
   "    c->TotalImpulse.z = 0.0f;" + NL + "    c->TotalImpulse.pad = 0.0f;"
   + NL)
_m("ctor-no-tail-link", "    last->Link.next = c;" + NL, "")
_m("ctor-no-tail", "    list->prev = c;" + NL, "")
_m("ctor-at-head", "    Collision *last = list->prev;",
   "    Collision *last = cnode(list);")
_m("ctor-no-witness", "    c->pWitness = w;" + NL, "")
_m("ctor-prev-head", "    c->Link.prev = last;", "    c->Link.prev = cnode(list);")
_m("ctor-no-next", "    c->Link.next = cnode(list);" + NL, "")
_m("ctor-no-mag", "    c->TotalImpulseMagnitude = 0.0f;" + NL, "")
_m("ctor-no-scrape", "    c->Scrape = NULL;" + NL, "")
_m("ctor-sample-null", "    c->Scrape = NULL;" + NL,
   "    c->Scrape = NULL;" + NL + "    c->Sample = NULL;" + NL)
_m("ctor-null-x", "        c->InitialContactPoint.x = 0.0f;" + NL, "")
_m("ctor-null-y", "        c->InitialContactPoint.y = 0.0f;" + NL, "")
_m("ctor-null-z", "        c->InitialContactPoint.z = 0.0f;" + NL, "")
_m("ctor-null-pad", "        c->InitialContactPoint.y = 0.0f;" + NL,
   "        c->InitialContactPoint.y = 0.0f;" + NL
   + "        c->InitialContactPoint.pad = 0.0f;" + NL)
_m("ctor-point-not-kept", "        c->InitialContactPoint = *pt;" + NL, "")
_m("ctor-point-three-lanes", "        c->InitialContactPoint = *pt;",
   "        c->InitialContactPoint.x = pt->x;"
   " c->InitialContactPoint.y = pt->y; c->InitialContactPoint.z = pt->z;")
_m("ctor-sample-le", "            < SAMPLE_DISTANCE)" + NL
   + "            c->Sample = create_sample(c);",
   "            <= SAMPLE_DISTANCE)" + NL
   + "            c->Sample = create_sample(c);")
_m("ctor-sample-2d", "        if (world_get_distance_to_closest_player(pCurrentWorld, pt)",
   "        if (world_get_distance_to_closest_player_2d(pCurrentWorld,"
   " (const bVector2 *)(const void *)pt)")
_m("ctor-sample-not-kept", "            c->Sample = create_sample(c);",
   "            (void)create_sample(c);")
_m("ctor-sample-always", "        if (world_get_distance_to_closest_player(pCurrentWorld, pt)"
   + NL + "            < SAMPLE_DISTANCE)" + NL,
   "        if (pt != NULL)" + NL)
_m("ctor-no-last-contact", "    c->LastContactTime.PackedTime = (uint32_t)WorldTimer;"
   + NL + "    c->CollisionTime", "    c->CollisionTime")
_m("ctor-no-time", "    c->CollisionTime.PackedTime = (uint32_t)WorldTimer;" + NL,
   "")
_m("ctor-times-zero", "    c->CollisionTime.PackedTime = (uint32_t)WorldTimer;",
   "    c->CollisionTime.PackedTime = 0;")
# retail's direction
_m("ctor-dir-x", "    c->ImpulseDirection.x = 0.0f;" + NL, "")
_m("ctor-dir-y", "    c->ImpulseDirection.y = 0.0f;" + NL, "")
_m("ctor-dir-z", "    c->ImpulseDirection.z = 0.0f;" + NL, "")
_m("ctor-dir-pad", "    c->ImpulseDirection.y = 0.0f;" + NL,
   "    c->ImpulseDirection.y = 0.0f;" + NL
   + "    c->ImpulseDirection.pad = 0.0f;" + NL)

# destroy and delete
_m("dtor-no-next", "    prev->Link.next = next;" + NL, "")
_m("dtor-no-prev", "    next->Link.prev = prev;" + NL, "")
_m("dtor-no-release", "    release_sample(c);" + NL, "")
_m("dtor-flag-2", "    if (flags & 1)" + NL + "        collision_delete(c);",
   "    if (flags & 2)" + NL + "        collision_delete(c);")
_m("dtor-always-delete", "    if (flags & 1)" + NL + "        collision_delete(c);",
   "    collision_delete(c);")
_m("dtor-never-delete", "    if (flags & 1)" + NL + "        collision_delete(c);",
   "    (void)flags;")
_m("delete-nothing", "    bSlotFree(CollisionSlotPool, p);", "    (void)p;")

# AddImpulse
_m("imp-x", "c->TotalImpulse.x = c->TotalImpulse.x + impulse->x;",
   "c->TotalImpulse.x = impulse->x;")
_m("imp-y", "c->TotalImpulse.y = c->TotalImpulse.y + impulse->y;",
   "c->TotalImpulse.y = c->TotalImpulse.y + impulse->x;")
_m("imp-z", "c->TotalImpulse.z = c->TotalImpulse.z + impulse->z;",
   "c->TotalImpulse.z = c->TotalImpulse.z - impulse->z;")
_m("imp-pad", "    c->TotalImpulse.pad = c->TotalImpulse.pad + impulse->pad;"
   + NL, "")
_m("imp-len-order", "    return (a->x * b->x + a->y * b->y) + a->z * b->z;",
   "    return a->x * b->x + (a->y * b->y + a->z * b->z);")
_m("imp-len-2d", "    len = sqrtf(dot3(impulse, impulse));",
   "    len = sqrtf(impulse->x * impulse->x + impulse->y * impulse->y);")
_m("imp-len-squared", "    len = sqrtf(dot3(impulse, impulse));",
   "    len = dot3(impulse, impulse);")
_m("imp-no-mag", "    c->TotalImpulseMagnitude = c->TotalImpulseMagnitude + len;",
   "    c->TotalImpulseMagnitude = len;")
_m("imp-no-stamp", "    c->LastContactTime.PackedTime = (uint32_t)WorldTimer;"
   + NL + "    c->CurrentContactPoint", "    c->CurrentContactPoint")
_m("imp-no-point", "    c->CurrentContactPoint = *at;" + NL, "")
_m("imp-no-speed", "    c->CurrentScrapeSpeed = scrape;" + NL, "")
_m("imp-ground-z", "    ground.y = at->y;", "    ground.y = at->z;")
_m("imp-ground-3d", "    if (world_get_distance_to_closest_player_2d(pCurrentWorld, &ground)",
   "    (void)ground;" + NL
   + "    if (world_get_distance_to_closest_player(pCurrentWorld, at)")
_m("imp-effect-le", "        < EFFECT_DISTANCE) {", "        <= EFFECT_DISTANCE) {")
_m("imp-scrape-le", "        if (info->CollisionScrapeMinSpeed < scrape) {",
   "        if (info->CollisionScrapeMinSpeed <= scrape) {")
_m("imp-scrape-max-test", "        if (info->CollisionScrapeMinSpeed < scrape) {",
   "        if (info->CollisionScrapeMaxSpeed < scrape) {")
_m("imp-scrape-lo", "            float lo = info->CollisionScrapeMinSpeed;",
   "            float lo = 0.0f;")
_m("imp-scrape-plain-div", "            s = ee_div(scrape - lo, info->CollisionScrapeMaxSpeed - lo);",
   "            s = (scrape - lo) / (info->CollisionScrapeMaxSpeed - lo);")
_m("imp-scrape-over-max", "            s = ee_div(scrape - lo, info->CollisionScrapeMaxSpeed - lo);",
   "            s = ee_div(scrape - lo, info->CollisionScrapeMaxSpeed);")
_m("imp-scrape-no-ceiling", "            s = min_s(1.0f, max_s(s, 0.0f));" + NL
   + NL + "            // The faster",
   "            s = max_s(s, 0.0f);" + NL + NL + "            // The faster")
_m("imp-scrape-no-floor", "            s = min_s(1.0f, max_s(s, 0.0f));" + NL
   + NL + "            // The faster",
   "            s = min_s(1.0f, s);" + NL + NL + "            // The faster")
_m("imp-v1-body2", "            v1 = get_velocity(c->pWitness->pBody1);",
   "            v1 = get_velocity(c->pWitness->pBody2);")
_m("imp-v2-body2", "            v2 = get_velocity(c->pWitness->pBody1);",
   "            v2 = get_velocity(c->pWitness->pBody2);")
_m("imp-one-call", "            v2 = get_velocity(c->pWitness->pBody1);",
   "            v2 = v1;")
_m("imp-l2-of-v2", "            l2 = sqrtf(dot3(v1, v1));",
   "            l2 = sqrtf(dot3(v2, v2));")
_m("imp-faster-flip", "            if (l2 < l1)", "            if (l1 < l2)")
_m("imp-v-v2", "            v = v1;" + NL, "            v = v2;" + NL)
_m("imp-scrape-effect", "trigger_effect(TERRAIN_EFFECT_COLLISION_SCRAPE, tt, s, at, v);",
   "trigger_effect(TERRAIN_EFFECT_COLLISION_IMPACT, tt, s, at, v);")
_m("imp-scrape-tt", "trigger_effect(TERRAIN_EFFECT_COLLISION_SCRAPE, tt, s, at, v);",
   "trigger_effect(TERRAIN_EFFECT_COLLISION_SCRAPE, 0, s, at, v);")
_m("imp-scrape-scale", "trigger_effect(TERRAIN_EFFECT_COLLISION_SCRAPE, tt, s, at, v);",
   "trigger_effect(TERRAIN_EFFECT_COLLISION_SCRAPE, tt, scrape, at, v);")
_m("imp-scrape-at", "trigger_effect(TERRAIN_EFFECT_COLLISION_SCRAPE, tt, s, at, v);",
   "trigger_effect(TERRAIN_EFFECT_COLLISION_SCRAPE, tt, s, &c->InitialContactPoint, v);")
_m("imp-scrape-vel", "trigger_effect(TERRAIN_EFFECT_COLLISION_SCRAPE, tt, s, at, v);",
   "trigger_effect(TERRAIN_EFFECT_COLLISION_SCRAPE, tt, s, at, impulse);")
_m("imp-no-play", "            play_scrape(c);" + NL, "")
_m("imp-play-first", "            trigger_effect(TERRAIN_EFFECT_COLLISION_SCRAPE, tt, s, at, v);"
   + NL + "            play_scrape(c);",
   "            play_scrape(c);" + NL
   + "            trigger_effect(TERRAIN_EFFECT_COLLISION_SCRAPE, tt, s, at, v);")
_m("imp-impact-le", "        if (info->CollisionImpactMinForce < len) {",
   "        if (info->CollisionImpactMinForce <= len) {")
_m("imp-impact-else", "        if (info->CollisionImpactMinForce < len) {",
   "        else if (info->CollisionImpactMinForce < len) {")
_m("imp-impact-scrape", "        if (info->CollisionImpactMinForce < len) {",
   "        if (info->CollisionImpactMinForce < scrape) {")
_m("imp-impact-lo", "            float lo = info->CollisionImpactMinForce;",
   "            float lo = info->CollisionScrapeMinSpeed;")
_m("imp-impact-over-max", "            s = (len - lo) / (info->CollisionImpactMaxForce - lo);",
   "            s = (len - lo) / info->CollisionImpactMaxForce;")
_m("imp-impact-no-ceiling", "            s = min_s(1.0f, max_s(s, 0.0f));" + NL
   + "            // Three", "            s = max_s(s, 0.0f);" + NL
   + "            // Three")
_m("imp-impact-no-floor", "            s = min_s(1.0f, max_s(s, 0.0f));" + NL
   + "            // Three", "            s = min_s(1.0f, s);" + NL
   + "            // Three")
_m("imp-zero-y", "            zero.y = 0.0f;", "            zero.y = 1.0f;")
_m("imp-impact-vel", "trigger_effect(TERRAIN_EFFECT_COLLISION_IMPACT, tt, s, at, &zero);",
   "trigger_effect(TERRAIN_EFFECT_COLLISION_IMPACT, tt, s, at, impulse);")
_m("imp-impact-effect", "trigger_effect(TERRAIN_EFFECT_COLLISION_IMPACT, tt, s, at, &zero);",
   "trigger_effect(TERRAIN_EFFECT_COLLISION_SCRAPE, tt, s, at, &zero);")
_m("imp-impact-scale", "trigger_effect(TERRAIN_EFFECT_COLLISION_IMPACT, tt, s, at, &zero);",
   "trigger_effect(TERRAIN_EFFECT_COLLISION_IMPACT, tt, len, at, &zero);")
_m("imp-emitters", "        gTerrainEffectTriggerFn(pTerrainEffectEmitters, effect, terrain,",
   "        gTerrainEffectTriggerFn(NULL, effect, terrain,")
# retail's direction
_m("dir-none", "        normalize4(&c->ImpulseDirection, impulse);" + NL, "")
_m("dir-always", "        normalize4(&c->ImpulseDirection, impulse);" + NL
   + "    }" + NL, "    }" + NL
   + "    normalize4(&c->ImpulseDirection, impulse);" + NL)
_m("dir-total", "        normalize4(&c->ImpulseDirection, impulse);",
   "        normalize4(&c->ImpulseDirection, &c->TotalImpulse);")
_m("dir-no-pad", "    out->pad = v->pad * inv;", "    out->pad = v->pad;")
_m("dir-pad-zero", "    out->pad = v->pad * inv;", "    out->pad = 0.0f;")
_m("dir-y-x", "    out->y = v->y * inv;", "    out->y = v->x * inv;")
_m("dir-len", "    float inv = 0.0f + ee_div(1.0f, sqrtf(dot3(v, v)));",
   "    float inv = 0.0f + ee_div(1.0f, dot3(v, v));")
_m("dir-ieee", "    float inv = 0.0f + ee_div(1.0f, sqrtf(dot3(v, v)));",
   "    float inv = 0.0f + 1.0f / sqrtf(dot3(v, v));")
_m("dir-len4", "    float inv = 0.0f + ee_div(1.0f, sqrtf(dot3(v, v)));",
   "    float inv = 0.0f + ee_div(1.0f, sqrtf(dot3(v, v) + v->pad * v->pad));")
_m("effect-scrape-const", "#define TERRAIN_EFFECT_COLLISION_SCRAPE 6",
   "#define TERRAIN_EFFECT_COLLISION_SCRAPE 7", CH)
_m("effect-impact-const", "#define TERRAIN_EFFECT_COLLISION_IMPACT 5",
   "#define TERRAIN_EFFECT_COLLISION_IMPACT 4", CH)

# Update, End
_m("upd-le", "    return (float)age * TICK_SECONDS < CollisionLifetime;",
   "    return (float)age * TICK_SECONDS <= CollisionLifetime;")
_m("upd-unsigned", "    return (float)age * TICK_SECONDS < CollisionLifetime;",
   "    return (float)(uint32_t)age * TICK_SECONDS < CollisionLifetime;")
_m("upd-from-birth", "                            - c->LastContactTime.PackedTime);",
   "                            - c->CollisionTime.PackedTime);")
_m("upd-divide", "    return (float)age * TICK_SECONDS < CollisionLifetime;",
   "    return (float)age / 4000.0f < CollisionLifetime;")
_m("upd-reads-dt", "    return (float)age * TICK_SECONDS < CollisionLifetime;",
   "    return (float)age * TICK_SECONDS < CollisionLifetime + dt;")
_m("end-nothing", "    cbwitness_end_collision(c->pWitness);", "    (void)c;")

# GetTerrainType
_m("tt-lt", "    if (TerrainTypeInfoTable[t2].CollisionPriority" + NL
   + "        <= TerrainTypeInfoTable[t1].CollisionPriority)",
   "    if (TerrainTypeInfoTable[t2].CollisionPriority" + NL
   + "        < TerrainTypeInfoTable[t1].CollisionPriority)")
_m("tt-flip", "    if (TerrainTypeInfoTable[t2].CollisionPriority" + NL
   + "        <= TerrainTypeInfoTable[t1].CollisionPriority)",
   "    if (TerrainTypeInfoTable[t1].CollisionPriority" + NL
   + "        <= TerrainTypeInfoTable[t2].CollisionPriority)")
_m("tt-order", "    int32_t t1 = get_terrain_type(c->pWitness->pBody1);" + NL
   + "    int32_t t2 = get_terrain_type(c->pWitness->pBody2);",
   "    int32_t t2 = get_terrain_type(c->pWitness->pBody2);" + NL
   + "    int32_t t1 = get_terrain_type(c->pWitness->pBody1);")
_m("tt-body1-twice", "    int32_t t2 = get_terrain_type(c->pWitness->pBody2);",
   "    int32_t t2 = get_terrain_type(c->pWitness->pBody1);")

# the questions
_m("two-first", "    if (w->pBody1->Type != CAR_COLLISION_BODY)" + NL
   + "        return 0;" + NL + "    return w->pBody2->Type == CAR_COLLISION_BODY;",
   "    return w->pBody2->Type == CAR_COLLISION_BODY;")
_m("two-second", "    return w->pBody2->Type == CAR_COLLISION_BODY;",
   "    return 1;")
_m("two-smokeable", "    if (w->pBody1->Type != CAR_COLLISION_BODY)",
   "    if (w->pBody1->Type == SMOKEABLE_COLLISION_BODY)")
_m("cars-no-clear1", "    *car1 = NULL;" + NL, "")
_m("cars-no-clear2", "    *car2 = NULL;" + NL, "")
_m("cars-test1", "    if (w->pBody1->Type == CAR_COLLISION_BODY)" + NL
   + "        *car1", "    if (w->pBody1->Type != SMOKEABLE_COLLISION_BODY)" + NL
   + "        *car1")
_m("cars-test2", "    if (w->pBody2->Type == CAR_COLLISION_BODY)" + NL
   + "        *car2", "    if (w->pBody1->Type == CAR_COLLISION_BODY)" + NL
   + "        *car2")
_m("cars-body1-twice",
   "        *car2 = ((CarCollisionBody *)(void *)w->pBody2)->pCar;",
   "        *car2 = ((CarCollisionBody *)(void *)w->pBody1)->pCar;")
_m("player-no-car1", "    if (car1 != NULL && car1->pPlayer != NULL)" + NL
   + "        return 1;" + NL, "")
_m("player-car1-any", "    if (car1 != NULL && car1->pPlayer != NULL)",
   "    if (car1 != NULL)")
_m("player-car2-any", "    return car2->pPlayer != NULL;", "    return 1;")
_m("player-car2-null", "    if (car2 == NULL)" + NL + "        return 0;",
   "    if (car2 == NULL)" + NL + "        return 1;")
_m("smoke-first", "    if (w->pBody1->Type == SMOKEABLE_COLLISION_BODY)" + NL
   + "        return 1;" + NL, "")
_m("smoke-second", "    return w->pBody2->Type == SMOKEABLE_COLLISION_BODY;",
   "    return 0;")
_m("smoke-car", "    return w->pBody2->Type == SMOKEABLE_COLLISION_BODY;",
   "    return w->pBody2->Type != CAR_COLLISION_BODY;")

# World's two distances
_m("w-min-swap", "    return min_s(d0, d1);" + NL + "}" + NL + NL + "float",
   "    return min_s(d1, d0);" + NL + "}" + NL + NL + "float", WC)
_m("w-max", "    return min_s(d0, d1);" + NL + "}" + NL + NL + "float",
   "    return d0 < d1 ? d1 : d0;" + NL + "}" + NL + NL + "float", WC)
_m("w-player0", "    float d1 = distance3(p, &w->PlayerPositions[1]);",
   "    float d1 = distance3(p, &w->PlayerPositions[0]);", WC)
_m("w-order", "    return sqrtf((dx * dx + dy * dy) + dz * dz);",
   "    return sqrtf(dx * dx + (dy * dy + dz * dz));", WC)
_m("w-no-z", "    return sqrtf((dx * dx + dy * dy) + dz * dz);",
   "    return sqrtf(dx * dx + dy * dy);", WC)
_m("w-no-root", "    return sqrtf((dx * dx + dy * dy) + dz * dz);",
   "    return (dx * dx + dy * dy) + dz * dz;", WC)
_m("w2-min-swap", "    float d1 = sqrtf(dx1 * dx1 + dy1 * dy1);" + NL + NL
   + "    return min_s(d0, d1);",
   "    float d1 = sqrtf(dx1 * dx1 + dy1 * dy1);" + NL + NL
   + "    return min_s(d1, d0);", WC)
_m("w2-y1", "    float dy1 = y - w->PlayerPositions[1].y;",
   "    float dy1 = y - w->PlayerPositions[0].y;", WC)
_m("w2-x0", "    float dx0 = x - w->PlayerPositions[0].x;",
   "    float dx0 = x - w->PlayerPositions[1].x;", WC)
_m("w2-z", "    float y = p->y;", "    float y = ((const float *)p)[2];", WC)
_m("w-min-strict", "    return ft < fs ? ft : fs;", "    return ft <= fs ? ft : fs;",
   WC)

EQUIVALENT = {
    "lifetime-near":
        "no whole number of ticks makes 0.29999998: 1199 of them make "
        "0.29975 and 1200 make 0.3's own float, so a lifetime anywhere "
        "between answers alike",
    "imp-scrape-plain-div":
        "the numerator is past the minimum and so above zero, and no "
        "terrain's scrape range is negative; the divide is x / 0 only on "
        "ROAD's and terrain 31's 50 to 50, where FLT_MAX and infinity both "
        "clamp to 1",
    "imp-scrape-no-floor":
        "the numerator is past the minimum and so above zero, and no "
        "terrain's scrape range is negative, so the quotient never is",
    "imp-impact-no-floor":
        "the numerator is past the minimum and so above zero, and every "
        "terrain's impact range is positive, so the quotient never is "
        "below zero",
    "imp-l2-of-v2":
        "both velocity calls are on body 1 and answer the same vector, so "
        "v2 is v1",
    "imp-faster-flip":
        "both lengths are of the same vector, so neither is below the other",
    "imp-v-v2":
        "both velocity calls are on body 1 and answer the same vector, so "
        "v1 and v2 are one pointer",
    "w-min-swap":
        "a distance is the root of a sum of squares: never NaN on values "
        "the EE can hold, never -0, and min.s is symmetric on every other "
        "pair",
    "w2-min-swap":
        "a distance is the root of a sum of squares: never NaN on values "
        "the EE can hold, never -0, and min.s is symmetric on every other "
        "pair",
    "w-min-strict":
        "on a tie the two distances are one value, and neither is ever -0",
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
        exe = hostbuild.build(tmp, SOURCES, name="collision_test")
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
                    exe = hostbuild.build(tmp, SOURCES, name="collision_test")
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
    # An entry whose mutant was caught is a wrong reason, not a spare one.
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
        exe = hostbuild.build(tmp, SOURCES, name="collision_test")
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
    effects = sum(1 for line in lines if line.startswith("  effect"))
    print("%d scenarios, %d ops, %d lines, %d differ; %d effects triggered"
          % (len(sc.tags), ops, len(harness), bad, effects))
    sys.exit(1 if (bad or rc) else 0)


if __name__ == "__main__":
    main()
