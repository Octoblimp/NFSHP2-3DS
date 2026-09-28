#!/usr/bin/env python3
"""Cross-check 3DS Files/source/carinit.c (Car's constructor and destructor,
CloseRenderInfo and CarReflectEventHandler) against the retail image itself,
run in mipsemu.

The model is the image: Car::Car (0x00130a48), Car::~Car (0x00130ee0),
CloseRenderInfo (0x0011e280) and CarReflectEventHandler (0x00130a28) run as
shipped, and so do CarController's constructor and TrackPathCoordinate's
destructor. Every other callee is stubbed. Each stub prints its name and
its arguments, then the car: every field the constructor or the
destructor stores, and the holes between them, in retail's order. The
harness links carinit.c with the real carcontroller.c, cardriver.c,
espresso.c and vtable.c, and the same stubs on the port's side, and prints
the same lines. The stubs that move the car do the same on both sides:

    CarState's ctor    fills Position, sets Angle and CurrentGear
    PutFlatOnTrack     moves the car, and sets CurrentGear, DispGear,
                       OldSpeed and pRenderInfo, which the constructor
                       must then overwrite
    InitRenderInfo     by the scenario: pRenderInfo, pCarDamage or the
                       position, which the constructor must then read
    CarDamage's and CarCollisionBody's ctors
                       return their memory, or by the scenario another
                       pointer, which is the one the car must keep

Every buffer the car or a stub hands out starts as 0xa5s, so a store the
image does not make shows as a field the port changed.

The console's start vector is a quadword on the stack with x, y and z
zeroed and w left as the stack had it; vOldVel and vOldAngVel take that w,
and so do vOldPos and State.Position when no position is given. The port
zeroes it. Those lanes print as `*` on both sides.

Scenarios cover:
- every driver number the sound test separates, and every usage type, on
  and off SoundEnabled, and outside the three;
- car types either side of zero, each with its own usage;
- a position and none, with NaN and -0 lanes; the distance below zero,
  -0, NaN either sign, and both infinities;
- an angle with bits above the sixteen `andi` keeps;
- WorldTimer across its range, where the half ForceBuzzTime adds decides;
- a CarDamage and a collision body at another address than their memory,
  and InitRenderInfo setting the render info, the damage, or moving the car;
- the destructor over each pointer present and absent, with this-deltas,
  and flags with and without bit 0;
- the event reflected to a car and to none.

    python tools/carinit_check.py
    python tools/carinit_check.py --mutate [--only a,b]
    python tools/carinit_check.py --dump out/carinit
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

HARNESS = "tools/src/carinit_test.c"
CIC = "3DS Files/source/carinit.c"
CIH = "3DS Files/source/carinit.h"
CCC = "3DS Files/source/carcontroller.c"
CDC = "3DS Files/source/cardriver.c"
ESC = "3DS Files/source/espresso.c"
SOURCES = [HARNESS, CIC, CCC, CDC, ESC, "3DS Files/source/vtable.c"]

HARNESS_TIMEOUT = 60

# ================================================================ the image

# Retail's, read off its code.
GP = 0x003358f0
CTOR = 0x00130a48
DTOR = 0x00130ee0
CLOSE_RI = 0x0011e280
REFLECT = 0x00130a28
CC_CTOR = 0x001c0090                 # run
TPC_DTOR = 0x00208748                # run
CARSTATE = 0x001c01a8
TOPO = 0x00151c28
TOPO_DTOR = 0x00151c70
TPC = 0x002086b8
TPC_RESET = 0x00208838
TPC_NEAR = 0x00208848
SND_PLAYER = 0x0018eb28
SND_AI = 0x0018eb70
SND_COP = 0x0018ebb8
BMALLOC = 0x002577c0
BOMALLOC = 0x00257c80
BDELETE = 0x00114e98
DT_CTOR = 0x0021b918
DT_CLEAR = 0x0021bbb0
DMG_CTOR = 0x001b54b0
DMG_PARTS = 0x001b5598               # retail only
DMG_DTOR = 0x001b5538
CCB_CTOR = 0x001d7e48
ESP_SET = 0x0025c5a8
ESP_DEL = 0x0025b900
PUT_FLAT = 0x00132910
INIT_RI = 0x0011dc80
RI_DTOR = 0x0011fac0
EM_ADD = 0x001ba2d0
EM_REMOVE = 0x001ba3a8
STOP_BLINK = 0x00133128
BMEMSET = 0x00250340
EVENT_HANDLER = 0x00133918

CTI_ARRAY = GP - 20616               # CarTypeInfos
SOUND_ENABLED = GP - 23056
NM_POOL = GP - 22796                 # NullMoverSlotPool
CCB_POOL = GP - 17708                # CarCollisionBodySlotPool
WORLD_TIMER = GP - 19576
TICK_SECONDS = GP - 32016            # 1/4000

# The ones the map pairs, and the demo's twins.
DEMO_CODE = {
    CTOR: 0x0012f240, DTOR: 0x0012f660, CLOSE_RI: 0x0011e2f0,
    REFLECT: 0x0012f220, CC_CTOR: 0x001b6068, TPC_DTOR: 0x001f5d20,
    CARSTATE: 0x001b6170, TOPO: 0x0014f030, TOPO_DTOR: 0x0014f068,
    TPC: 0x001f5c90, SND_PLAYER: 0x001865b0, SND_AI: 0x001865f8,
    SND_COP: 0x00186640, BMALLOC: 0x0023f0b8, BOMALLOC: 0x0023f578,
    BDELETE: 0x00114ab8, DT_CTOR: 0x002086f8, DT_CLEAR: 0x00208980,
    DMG_CTOR: 0x001ab8c8, DMG_DTOR: 0x001ab928, CCB_CTOR: 0x001cd750,
    ESP_SET: 0x00243e68, ESP_DEL: 0x002431c0, PUT_FLAT: 0x00130e90,
    INIT_RI: 0x0011dce8, RI_DTOR: 0x0011f868, EM_ADD: 0x001b04b0,
    EM_REMOVE: 0x001b0588, STOP_BLINK: 0x00131638, BMEMSET: 0x00238140,
    EVENT_HANDLER: 0x00131db0,
}
DEMO_DATA = {
    CTI_ARRAY: 0x00323930, SOUND_ENABLED: 0x00322fa4, NM_POOL: 0x003230a4,
    WORLD_TIMER: 0x00323cf0, TICK_SECONDS: 0x00320e90,
}
# The vtables, by the port's names; the demo's addresses are the port's ids.
DEMO_VT = {"CarController": 0x0029a6e0, "NullController": 0x00292350,
           "CarDriver": 0x002924a8, "NullDriver": 0x00292400,
           "NullMover": 0x002923c0}

# The harness's world, and the model's.
CAR = 0x01100000
CAR_SIZE = 2200
DI = 0x01101000
DI_SIZE = 24
POS = 0x01101100
CTIS = 0x01110000
CTI_SIZE = 1376
NCTI = 8
CTI0 = 2                             # CTIS + 2 * 1376 is type 0
HEAP = 0x01200000
HEAP_SLOT = 0x1000
NHEAP = 8
SND = 0x01300000
DMG_ALT = 0x01300100
CCB_ALT = 0x01300400
RI = 0x01300800
POOL_NM = 0x01300900
POOL_CCB = 0x01300a00
EVT = 0x01300b00
OBJS = [("ctlobj", 0x01310000, 256), ("movobj", 0x01310100, 256),
        ("ccbobj", 0x01310200, 1024), ("dmgobj", 0x01310600, 256),
        ("riobj", 0x01310700, 64), ("cafobj", 0x01310800, 64),
        ("sndobj", 0x01310900, 64)]
OBJ = {n: a for n, a, _ in OBJS}
VT_CTL, VT_MOV, VT_CCB, VT_SND = 0x01320000, 0x01320040, 0x01320080, \
    0x013200c0
FN_CTL, FN_MOV, FN_CCB, FN_SND = 0x01330000, 0x01330010, 0x01330020, \
    0x01330030

PATTERN = 0xa5
STACK_FILL = 0x77

NAN = 0x7fc00000
NNAN = 0xffc00000
INF = 0x7f800000
NINF = 0xff800000
NZERO = 0x80000000


def fbits(f):
    if isinstance(f, int):
        return f & M32
    return struct.unpack("<I", struct.pack("<f", f))[0]


def bitsf(b):
    return struct.unpack("<f", struct.pack("<I", b & M32))[0]


# The car, in retail's order: (offset, kind). `vp` is a vector whose w is
# the stack's when no position is given, `vm` one whose w always is; `|`
# separates the groups.
FIELDS = (
    [(8, "h"), (10, "h")] + [(o, "p") for o in (12, 16, 20, 24, 28)]
    + [(32, "w"), (36, "w")] + [(o, "p") for o in (40, 44, 48, 52)]
    + [(56, "w"), (60, "w"), (0, "|"),
       (96, "vp"), (932, "h"), (968, "w"), (0, "|")]
    + [(o, "w") for o in range(1104, 1136, 4)] + [(0, "|"),
       (1136, "vp"), (1152, "vm"), (1168, "vm"), (0, "|"),
       (1184, "w"), (1188, "w"), (1192, "w"), (1196, "w"), (1200, "p"),
       (1204, "p"), (1208, "w"), (1212, "w"), (0, "|")]
    + [(o, "w") for o in range(1296, 1312, 4)] + [(0, "|")]
    + [(o, "w") for o in range(2056, 2120, 4)] + [(0, "|"),
       (2120, "p"), (2124, "w"), (2128, "w"), (2132, "p")]
    + [(o, "w") for o in range(2136, 2176, 4)]
    + [(2176, "p"), (2180, "p"), (2184, "w"), (2188, "w"), (2192, "w"),
       (2196, "w")])


# ============================================================ the scenarios


class Ctor(object):
    def __init__(self, dn=2, type=0, usage=None, sound=1,
                 pos=(10.0, 20.0, 30.0, 1.0), angle=0x4000, dist=-1.0,
                 timer=0, dret=0, cret=0, ri=0):
        self.dn, self.type = dn, type
        self.usage = list(usage) if usage is not None else [0] * NCTI
        self.sound, self.pos, self.angle = sound, pos, angle
        self.dist, self.timer = fbits(dist), timer
        self.dret, self.cret, self.ri = dret, cret, ri

    def line(self):
        pos = self.pos if self.pos is not None else (0, 0, 0, 0)
        v = ([self.dn, self.type] + self.usage
             + [self.sound, 1 if self.pos is not None else 0]
             + [fbits(p) for p in pos]
             + [self.angle, self.dist, self.timer, self.dret, self.cret,
                self.ri])
        return "C " + " ".join("%x" % (x & M32) for x in v)


class Dtor(object):
    def __init__(self, mask=0, flags=3, deltas=(0, 0, 0)):
        self.mask, self.flags, self.deltas = mask, flags, deltas

    def line(self):
        v = [self.mask >> i & 1 for i in range(7)] + [self.flags] + list(
            self.deltas)
        return "D " + " ".join("%x" % (x & M32) for x in v)


class Event(object):
    def __init__(self, car):
        self.car = car

    def line(self):
        return "E %x" % self.car


def buzz(t):
    """ForceBuzzTime as the image computes it, in float32, rounded."""
    f = bitsf(fbits(float(s32(t))))
    f = bitsf(fbits(f * bitsf(0x3983126f)))
    f = bitsf(fbits(f * 4000.0))
    return f


def script():
    rnd = random.Random(0xca5)
    sc = [Ctor(), Ctor(pos=None)]
    # The sound: players by number, the rest by usage.
    for dn in (0, 1, 2, 3, -1, 127, -128, 0x7f, 0x80, 0x101):
        sc.append(Ctor(dn=dn))
    for usage in (0, 1, 2, 3, -1, 0x7fffffff, 0x80000000, 4):
        for sound in (1, 0, -1, 2):
            u = [0] * NCTI
            u[CTI0] = usage
            sc.append(Ctor(dn=4, usage=u, sound=sound))
        for dn in (0, 1):
            u = [0] * NCTI
            u[CTI0] = usage
            sc.append(Ctor(dn=dn, usage=u))
    # The type, each with its own usage.
    table = [2, 1, 0, 1, 2, 3, 0, 1]
    for t in range(-CTI0, NCTI - CTI0):
        sc.append(Ctor(dn=9, type=t, usage=table))
        sc.append(Ctor(dn=1, type=t, usage=table, sound=0))
    # The position and the distance.
    dists = (-1.0, NZERO, 0.0, 1e-30, -1e-30, 250.0, NAN, NNAN, INF, NINF,
             1e30, -1e30, 0x00000001, 0x80000001)
    for d in dists:
        sc.append(Ctor(dist=d))
        sc.append(Ctor(pos=None, dist=d))
    for pos in ((NAN, NZERO, 1.0, NNAN), (NZERO, NZERO, NZERO, NZERO),
                (-1e30, 1e-30, INF, 0x12345678), (5.5, -7.25, 0.125, NAN)):
        for d in (-2.0, 3.0):
            sc.append(Ctor(pos=pos, dist=d))
    # The angle, and what `andi` drops.
    for a in (0, 1, 0x7fff, 0x8000, 0xffff, 0x12345678, 0xffffffff,
              0x10000):
        sc.append(Ctor(angle=a))
    # The clock, and ForceBuzzTime's half.
    timers = [0, 1, -1, 2, 3999, 4000, 4001, -4000, 12345678, 16777216,
              16777217, 16777219, 0x7fffffff, 0x80000000, (1 << 30) + 1,
              -(1 << 30) - 1, 0x7fffff80, 0x7fffffbf, -0x7fffffbf]
    found = 0
    while found < 24:
        t = rnd.choice((rnd.randrange(1, 1 << 12), rnd.randrange(1, 1 << 20),
                        rnd.randrange(1, 1 << 24), rnd.randrange(1, 1 << 31)))
        if rnd.random() < 0.3:
            t = -t
        b = buzz(t)
        # Where adding the half changes the truncation.
        if int(b) != int(bitsf(fbits(b + 0.5))):
            timers.append(t)
            found += 1
    for t in timers:
        sc.append(Ctor(timer=t))
    # The two returns the car keeps, and InitRenderInfo's side effects.
    for dret, cret in ((1, 0), (0, 1), (1, 1)):
        sc.append(Ctor(dret=dret, cret=cret))
    for ri in (1, 2, 3, 4):
        for usage in (0, 2):
            u = [0] * NCTI
            u[CTI0] = usage
            sc.append(Ctor(ri=ri, usage=u, dret=ri & 1))
    # A mix.
    for _ in range(24):
        u = [rnd.choice((0, 1, 2, 3, -1)) for _ in range(NCTI)]
        pos = None if rnd.random() < 0.3 else tuple(
            rnd.uniform(-1e4, 1e4) for _ in range(4))
        sc.append(Ctor(dn=rnd.randrange(-128, 128),
                       type=rnd.randrange(-CTI0, NCTI - CTI0), usage=u,
                       sound=rnd.choice((0, 1, 1, 1)), pos=pos,
                       angle=rnd.randrange(0, 1 << 32),
                       dist=rnd.choice((-1.0, rnd.uniform(-500, 500))),
                       timer=rnd.randrange(-(1 << 31), 1 << 31),
                       dret=rnd.randrange(2), cret=rnd.randrange(2),
                       ri=rnd.randrange(5)))

    # The destructor.
    for flags in (0, 1, 2, 3, -1, -2, 0x10001):
        sc.append(Dtor(0, flags))
        sc.append(Dtor(0x7f, flags))
    for i in range(7):
        sc.append(Dtor(1 << i, 2))
        sc.append(Dtor(0x7f ^ (1 << i), 1))
    for deltas in ((8, 0, 16), (16, 4, 80), (100, 200, 300)):
        sc.append(Dtor(0x7f, 3, deltas))
    for _ in range(16):
        sc.append(Dtor(rnd.randrange(128), rnd.randrange(-4, 8),
                       tuple(rnd.randrange(0, 33) * 4 for _ in range(3))))

    sc.append(Event(1))
    sc.append(Event(0))
    return sc


# ================================================================ the model


class Model(object):
    def __init__(self):
        self.out = []
        self.e = retail_model.RetailEmu(ieee=True)
        e = self.e
        for r, d in DEMO_CODE.items():
            assert e.map.by_demo[d][2] == r, (hex(d), hex(r))
        for r, d in DEMO_DATA.items():
            assert e.data(d) == r, (hex(d), hex(r))
        assert e.u32(TICK_SECONDS) == 0x3983126f
        self.vt = {e.data(a): n for n, a in DEMO_VT.items()}
        stubs = {
            CARSTATE: self.carstate, TOPO: self.topo,
            TOPO_DTOR: self.topo_dtor, TPC: self.tpc,
            TPC_RESET: self.tpc_reset, TPC_NEAR: self.tpc_near,
            SND_PLAYER: self.sound("CreatePlayerCarSound"),
            SND_AI: self.sound("CreateAICarSound"),
            SND_COP: self.sound("CreateAICopCarSound"),
            BMALLOC: self.bmalloc, BOMALLOC: self.bomalloc,
            BDELETE: self.bdelete, DT_CTOR: self.dt_ctor,
            DT_CLEAR: self.dt_clear, DMG_CTOR: self.dmg_ctor,
            DMG_PARTS: self.dmg_parts, DMG_DTOR: self.dtor("~CarDamage"),
            CCB_CTOR: self.ccb_ctor, ESP_SET: self.esp_set,
            ESP_DEL: self.esp_del, PUT_FLAT: self.put_flat,
            INIT_RI: self.init_ri, RI_DTOR: self.dtor("~CarRenderInfo"),
            EM_ADD: self.em_add, EM_REMOVE: self.em_remove,
            STOP_BLINK: self.stop_blink, BMEMSET: self.bmemset,
            EVENT_HANDLER: self.event_handler,
            FN_CTL: self.dtor("~ctl"), FN_MOV: self.dtor("~mover"),
            FN_CCB: self.dtor("~ccb"), FN_SND: self.dtor("~BaseCarSound"),
        }
        for a, fn in stubs.items():
            e.stub(a, fn)
        e.put32(CTI_ARRAY, CTIS + CTI0 * CTI_SIZE)
        e.put32(NM_POOL, POOL_NM)
        e.put32(CCB_POOL, POOL_CCB)

    def emit(self, s):
        self.out.append(s)

    def arg(self, i):
        return self.e.reg[4 + i] & M32

    def cstr(self, a):
        b = bytearray()
        while self.e.u8(a + len(b)) != 0:
            b.append(self.e.u8(a + len(b)))
        return b.decode("latin-1")

    def label(self, a):
        a &= M32
        names = {0: "null", 0xa5a5a5a5: "a5", CAR: "car", CAR + 64: "state",
                 CAR + 1312: "topo", CAR + 2016: "tpc", DI: "di",
                 DI + 12: "ride", SND: "snd", DMG_ALT: "dmg'",
                 CCB_ALT: "ccb'", RI: "ri", REFLECT: "CarReflectEventHandler",
                 EVT: "evt", POOL_NM: "NullMoverSlotPool",
                 POOL_CCB: "CarCollisionBodySlotPool"}
        if a in names:
            return names[a]
        if HEAP <= a < HEAP + NHEAP * HEAP_SLOT and a % HEAP_SLOT == 0:
            return "h%d" % ((a - HEAP) // HEAP_SLOT)
        if CTIS <= a < CTIS + NCTI * CTI_SIZE and (a - CTIS) % CTI_SIZE == 0:
            return "cti%d" % ((a - CTIS) // CTI_SIZE - CTI0)
        for n, base, size in OBJS:
            if base <= a < base + size:
                return n if a == base else "%s+%d" % (n, a - base)
        return "?%08x" % a

    def vtname(self, a):
        if a in self.vt:
            return self.vt[a]
        if a == 0xa5a5a5a5:
            return "a5"
        return "%08x" % a

    # ---- the dump ----------------------------------------------------------

    def dump(self):
        e = self.e
        out = ["  ="]
        for off, kind in FIELDS:
            a = CAR + off
            if kind == "|":
                out.append("|")
            elif kind == "h":
                out.append("%04x" % e.u16(a))
            elif kind == "w":
                out.append("%08x" % e.u32(a))
            elif kind == "p":
                out.append(self.label(e.u32(a)))
            else:
                mask = kind == "vm" or (kind == "vp" and self.pos_null)
                out.extend("%08x" % e.u32(a + 4 * i) for i in range(3))
                out.append("*" if mask else "%08x" % e.u32(a + 12))
        self.emit(" ".join(out))

    def say(self, s):
        self.emit("  " + s)
        self.dump()

    # ---- the stubs ---------------------------------------------------------

    def carstate(self, em):
        s, topo, info = self.arg(0), self.arg(1), self.arg(2)
        self.say("CarState %s %s %s" % (self.label(s), self.label(topo),
                                        self.label(info)))
        for i in range(4):
            em.put32(s + 32 + 4 * i, 0x11111111)
        em.mem[s + 868:s + 870] = struct.pack("<H", 0x1234)
        em.put32(s + 904, 0x55)

    def topo(self, em):
        self.say("TopologyCoordinate %s" % self.label(self.arg(0)))

    def topo_dtor(self, em):
        self.say("~TopologyCoordinate %s" % self.label(self.arg(0)))

    def tpc(self, em):
        self.say("TrackPathCoordinate %s" % self.label(self.arg(0)))

    def tpc_reset(self, em):
        c, p = self.arg(0), self.arg(1)
        self.say("ResetPosition %s %08x %08x" % (self.label(c), em.u32(p),
                                                 em.u32(p + 4)))

    def tpc_near(self, em):
        c, p = self.arg(0), self.arg(1)
        self.say("ResetPositionNear %s %08x %08x %08x" % (
            self.label(c), em.u32(p), em.u32(p + 4), em.fpr[12] & M32))

    def sound(self, name):
        def fn(em):
            self.say("%s %s" % (name, self.label(self.arg(0))))
            return SND
        return fn

    def heap_next(self):
        if self.nheap >= NHEAP:
            raise SystemExit("model heap exhausted")
        a = HEAP + HEAP_SLOT * self.nheap
        self.nheap += 1
        self.e.write(a, bytes([PATTERN]) * HEAP_SLOT)
        return a

    def bmalloc(self, em):
        size, name = s32(self.arg(0)), self.cstr(self.arg(1))
        flags, pool = s32(self.arg(2)), s32(self.arg(3))
        a = self.heap_next()
        self.say("bMalloc %d %s %d %d -> %s" % (size, name, flags, pool,
                                                self.label(a)))
        return a

    def bomalloc(self, em):
        pool = self.arg(0)
        a = self.heap_next()
        self.say("bOMalloc %s -> %s" % (self.label(pool), self.label(a)))
        return a

    def bdelete(self, em):
        self.say("bFree %s" % self.label(self.arg(0)))

    def dt_ctor(self, em):
        self.say("DriveTarget %s" % self.label(self.arg(0)))
        return self.arg(0)

    def dt_clear(self, em):
        self.say("DriveTarget::Clear %s %s %08x" % (
            self.label(self.arg(0)), self.label(self.arg(1)),
            em.fpr[12] & M32))

    def dmg_ctor(self, em):
        mem, car = self.arg(0), self.arg(1)
        self.say("CarDamage %s %s" % (self.label(mem), self.label(car)))
        return DMG_ALT if self.sc.dret else mem

    def dmg_parts(self, em):
        self.say("CarDamage::parts %s" % self.label(self.arg(0)))

    def dtor(self, name):
        def fn(em):
            self.say("%s %s %d" % (name, self.label(self.arg(0)),
                                   s32(self.arg(1))))
        return fn

    def ccb_ctor(self, em):
        mem, car = self.arg(0), self.arg(1)
        self.say("CarCollisionBody %s %s" % (self.label(mem),
                                             self.label(car)))
        return CCB_ALT if self.sc.cret else mem

    def esp_set(self, em):
        self.say("espSetAttributeInt %08x %s %d" % (
            self.arg(0), self.cstr(self.arg(1)), s32(self.arg(2))))

    def esp_del(self, em):
        self.say("espDeleteObject %s" % self.label(self.arg(0)))

    def put_flat(self, em):
        c = self.arg(0)
        self.say("PutFlatOnTrack %s" % self.label(c))
        em.put32(c + 96, fbits(12.5))
        em.put32(c + 100, fbits(-3.25))
        em.put32(c + 968, 7)
        em.put32(c + 1104, 9)
        em.put32(c + 1184, fbits(3.0))
        em.put32(c + 1200, RI)

    def init_ri(self, em):
        c, ride = self.arg(0), self.arg(1)
        self.say("InitRenderInfo %s %s" % (self.label(c), self.label(ride)))
        k = self.sc.ri
        if k in (1, 2):
            em.put32(c + 1200, RI)
        if k == 2:
            em.put32(c + 2120, 0)
        if k == 3:
            em.put32(c + 2120, DMG_ALT)
        if k == 4:
            em.put32(c + 96, fbits(1.5))
            em.put32(c + 100, fbits(2.5))

    def em_add(self, em):
        self.say("emAddHandler %s %08x" % (self.label(self.arg(0)),
                                           self.arg(1)))
        return 1

    def em_remove(self, em):
        self.say("emRemoveHandler %s" % self.label(self.arg(0)))

    def stop_blink(self, em):
        self.say("StopBlinking %s" % self.label(self.arg(0)))

    def bmemset(self, em):
        a, v, n = self.arg(0), self.arg(1), s32(self.arg(2))
        em.mem[a:a + n] = bytes([v & 0xff]) * n
        return a

    def event_handler(self, em):
        self.say("EventHandler %s %s" % (self.label(self.arg(0)),
                                         self.label(self.arg(1))))

    # ---- the runs ----------------------------------------------------------

    def fill_car(self):
        self.e.write(CAR, bytes([PATTERN]) * CAR_SIZE)
        sp = self.e.reg[29] & M32
        self.e.write(sp - 4096, bytes([STACK_FILL]) * 4096)

    def ctor(self, n, sc):
        e = self.e
        self.fill_car()
        for i in range(NCTI):
            a = CTIS + CTI_SIZE * i
            e.write(a, bytes([PATTERN]) * CTI_SIZE)
            e.put32(a + 1336, sc.usage[i])
        e.put32(SOUND_ENABLED, sc.sound)
        e.write(DI, bytes([0x5a]) * DI_SIZE)
        e.mem[DI + 1] = sc.dn & 0xff
        e.put32(DI + 12, sc.type)
        pos = 0
        if sc.pos is not None:
            pos = POS
            for i, p in enumerate(sc.pos):
                e.put32(POS + 4 * i, fbits(p))
        e.put32(WORLD_TIMER, sc.timer)
        self.pos_null = sc.pos is None
        self.nheap = 0

        self.emit("C %d" % n)
        e.fpr[12] = sc.dist
        ret = e.call(CTOR, CAR, DI, pos, sc.angle & M32, limit=200000)
        self.emit("  ret %s" % self.label(ret))
        self.dump()
        ctl, drv, mov = e.u32(CAR + 40), e.u32(CAR + 44), e.u32(CAR + 48)
        self.emit("  ctl %s %s %s" % (self.label(e.u32(ctl)),
                                      self.label(e.u32(ctl + 4)),
                                      self.vtname(e.u32(ctl + 8))))
        self.emit("  drv %04x %s %s" % (
            e.u16(drv + 528),
            " ".join("%08x" % e.u32(drv + o)
                     for o in (532, 536, 540, 544, 548, 552)),
            self.vtname(e.u32(drv + 556))))
        self.emit("  mover %s %s %s" % (self.label(e.u32(mov)),
                                        self.vtname(e.u32(mov + 4)),
                                        self.label(e.u32(mov + 8))))

    def fake(self, name, vt_off, vt, fn, delta):
        e = self.e
        base = OBJ[name]
        size = dict((n, s) for n, _, s in OBJS)[name]
        e.write(base, bytes([PATTERN]) * size)
        e.put32(base + vt_off, vt)
        e.write(vt, bytes(16))
        e.mem[vt + 8:vt + 10] = struct.pack("<h", delta)
        e.put32(vt + 12, fn)
        return base

    def dtor_run(self, n, sc):
        e = self.e
        self.fill_car()
        self.pos_null = False
        dctl, dmov, dccb = sc.deltas
        ptrs = [self.fake("ctlobj", 8, VT_CTL, FN_CTL, dctl),
                self.fake("movobj", 4, VT_MOV, FN_MOV, dmov),
                self.fake("ccbobj", 80, VT_CCB, FN_CCB, dccb),
                OBJ["dmgobj"], OBJ["riobj"], OBJ["cafobj"],
                self.fake("sndobj", 28, VT_SND, FN_SND, 0)]
        for i, off in enumerate((40, 48, 52, 2120, 1200, 2176, 2132)):
            e.put32(CAR + off, ptrs[i] if sc.mask >> i & 1 else 0)
        self.emit("D %d" % n)
        e.call(DTOR, CAR, sc.flags & M32, limit=200000)
        self.emit("  end")
        self.dump()

    def event(self, n, sc):
        e = self.e
        self.fill_car()
        self.pos_null = False
        e.write(EVT, bytes([PATTERN]) * 36)
        e.put32(EVT + 20, CAR if sc.car else 0)
        self.emit("E %d" % n)
        e.call(REFLECT, EVT, limit=10000)
        self.emit("  end")

    def run(self, scenarios):
        for n, sc in enumerate(scenarios):
            self.sc = sc
            if isinstance(sc, Ctor):
                self.ctor(n, sc)
            elif isinstance(sc, Dtor):
                self.dtor_run(n, sc)
            else:
                self.event(n, sc)
        return self.out


def model(scenarios):
    return Model().run(scenarios)


# ================================================================ the build


def build_harness(tmp, name="carinit_test"):
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


def encode(scenarios):
    return NL.join(s.line() for s in scenarios) + NL


diff = pcc.diff

# ============================================================ the mutations

MUTATIONS = [
    # ---- the constructor, carinit.c
    ("ctor_orp_blinking", CIC, "orp->BlinkingViewBits = 0;",
     "orp->BlinkingViewBits = 1;"),
    ("ctor_orp_visible", CIC, "0xffffffffu;", "0xfffffffeu;"),
    ("ctor_orp_override", CIC, "orp->OverrideViewBits = 0;",
     "orp->OverrideViewBits = 1;"),
    ("ctor_no_topology_init", CIC,
     "    topology_init(&c->TheTopologyCoordinate);\n", ""),
    ("ctor_no_trackpath_init", CIC,
     "    trackpath_coord_init(&c->TheTrackPathCoordinate);\n", ""),
    ("ctor_start_x", CIC, "at.x = 0.0f;", "at.x = 1.0f;"),
    ("ctor_start_y", CIC, "at.y = 0.0f;", "at.y = 1.0f;"),
    ("ctor_start_z", CIC, "at.z = 0.0f;", "at.z = 1.0f;"),
    ("ctor_start_w", CIC, "at.pad = 0.0f;", "at.pad = 1.0f;"),
    ("ctor_start_time_early", CIC,
     "c->HeadlightsAndHornStartTime = 0;", "c->HeadlightsAndHornStartTime = 1;"),
    ("ctor_rumble", CIC, "c->fBlownTireControllerRumbleTimer = 0.0f;",
     "c->fBlownTireControllerRumbleTimer = 1.0f;"),
    ("ctor_blink_timer", CIC, "c->BlinkTimer = 0;", "c->BlinkTimer = 1;"),
    ("ctor_buzz_early", CIC, "c->ForceBuzzTime = 0;", "c->ForceBuzzTime = 1;"),
    ("ctor_no_old_pos", CIC,
     "    c->vOldPos = at;                                    // 1136\n", ""),
    ("ctor_no_old_vel", CIC, "    c->vOldVel = at;", "   "),
    ("ctor_no_old_ang_vel", CIC, "    c->vOldAngVel = at;", "   "),
    ("ctor_no_pos_old_pos", CIC, "        c->vOldPos = *pos;\n", ""),
    ("ctor_pos_ignored", CIC, "        at = *pos;\n", ""),
    ("ctor_dist_le", CIC, "if (dist < 0.0f)", "if (dist <= 0.0f)"),
    ("ctor_dist_not_ge", CIC, "if (dist < 0.0f)", "if (!(dist >= 0.0f))"),
    ("ctor_dist_sign", CIC, "if (dist < 0.0f)",
     "if (dist < 0.0f || (dist == 0.0f && 1.0f / dist < 0.0f))"),
    ("ctor_reset_swap", CIC, "if (dist < 0.0f)", "if (!(dist < 0.0f))"),
    ("ctor_near_dist", CIC, "(const bVector2 *)&at, dist);",
     "(const bVector2 *)&at, -dist);"),
    ("ctor_no_position", CIC, "    c->State.Position = at;", "   "),
    ("ctor_angle", CIC, "c->State.Angle = angle;",
     "c->State.Angle = (uint16_t)(angle + 1);"),
    ("ctor_no_angle", CIC, "    c->State.Angle = angle;", "   "),
    ("ctor_blown_bits", CIC, "c->BlownTireBits = 0;", "c->BlownTireBits = 1;"),
    ("ctor_num_blown", CIC, "c->NumBlownTires = 0;", "c->NumBlownTires = 1;"),
    ("ctor_friction", CIC, "c->FrictionBoost = 1.0f;",
     "c->FrictionBoost = 0.0f;"),
    ("ctor_draft", CIC, "c->DraftFactor = 0.0f;", "c->DraftFactor = 1.0f;"),
    ("ctor_my_driver", CIC, "c->MyDriver = driver;", "c->MyDriver = NULL;"),
    ("ctor_traction", CIC, "c->fTractionBoostOverride = 0.0f;",
     "c->fTractionBoostOverride = 1.0f;"),
    ("ctor_damage_override", CIC, "c->fDamageBoostOverride = 0.0f;",
     "c->fDamageBoostOverride = 1.0f;"),
    ("ctor_ride_info", CIC, "c->pRideInfo = &driver->CurrentRideInfo;",
     "c->pRideInfo = (RideInfo *)driver;"),
    ("ctor_car_index", CIC, "c->CarIndex = 0;", "c->CarIndex = 1;"),
    ("ctor_dn_unsigned", CIC, "c->DriverNumber = driver->UniqueDriverNumber;",
     "c->DriverNumber = (uint8_t)driver->UniqueDriverNumber;"),
    ("ctor_player", CIC, "c->pPlayer = NULL;", "c->pPlayer = (Player *)c;"),
    ("ctor_racing_car", CIC, "c->pRacingCar = NULL;",
     "c->pRacingCar = (RacingCar *)c;"),
    ("ctor_cti_first", CIC, "cartypeinfo_get(driver->CurrentRideInfo.Type));",
     "cartypeinfo_get(driver->CurrentRideInfo.Type + 1));"),
    ("ctor_cti_second", CIC,
     "cartypeinfo_get(driver->CurrentRideInfo.Type);  // 12",
     "cartypeinfo_get(driver->CurrentRideInfo.Type + 1);  // 12"),
    ("ctor_no_sound_null", CIC,
     "    c->pBaseCarSound = NULL;                            // 2132\n", ""),
    ("ctor_sound_positive", CIC, "if (SoundEnabled != 0) {",
     "if (SoundEnabled > 0) {"),
    ("ctor_sound_always", CIC, "if (SoundEnabled != 0) {", "if (1) {"),
    ("ctor_player_dn0", CIC,
     "c->DriverNumber == 0 || c->DriverNumber == 1",
     "c->DriverNumber == 0"),
    ("ctor_player_dn_le1", CIC,
     "c->DriverNumber == 0 || c->DriverNumber == 1",
     "c->DriverNumber <= 1"),
    ("ctor_player_fn", CIC, "create = gCreatePlayerCarSoundFn;",
     "create = gCreateAICarSoundFn;"),
    ("ctor_cop_fn", CIC, "create = gCreateAICopCarSoundFn;",
     "create = gCreateAICarSoundFn;"),
    ("ctor_cop_usage", CIC, "UsageType == CAR_USAGE_TYPE_COP)",
     "UsageType == CAR_USAGE_TYPE_TRAFFIC)"),
    ("ctor_ai_no_traffic", CIC,
     "\n                 || c->pCarTypeInfo->UsageType == CAR_USAGE_TYPE_TRAFFIC)",
     ")"),
    ("ctor_ai_any_usage", CIC,
     "else if (c->pCarTypeInfo->UsageType == CAR_USAGE_TYPE_RACING\n"
     "                 || c->pCarTypeInfo->UsageType == CAR_USAGE_TYPE_TRAFFIC)",
     "else"),
    ("ctor_ai_fn", CIC, "            create = gCreateAICarSoundFn;",
     "            create = gCreateAICopCarSoundFn;"),
    ("ctor_sound_discarded", CIC, "c->pBaseCarSound = create(c);",
     "create(c);"),
    ("ctor_controller", CIC, "c->pCarController = &ctrl->Base;",
     "c->pCarController = &ctrl->Base; c->pCarController->pCar = NULL;"),
    ("ctor_driver", CIC, "c->pCarDriver = ctrl->Base.Driver;",
     "c->pCarDriver = (CarDriver *)bMalloc(560, \"x\", 0, 0);"),
    ("ctor_mover_state", CIC, "m->pState = &c->State;", "m->pState = NULL;"),
    ("ctor_mover_vtable", CIC, "m->Mover._vtable = NULLMOVER_VTABLE;",
     "m->Mover._vtable = CARMOVER_VTABLE;"),
    ("ctor_no_mover", CIC, "    c->pCarMover = &m->Mover;", "   "),
    ("ctor_animated_driver", CIC, "    c->pAnimatedDriver = NULL;", "   "),
    ("ctor_no_damage_null", CIC,
     "    c->pCarDamage = NULL;                               // 2120\n", ""),
    ("ctor_damage_usage", CIC,
     "UsageType != CAR_USAGE_TYPE_TRAFFIC", "UsageType != CAR_USAGE_TYPE_COP"),
    ("ctor_damage_size", CIH, "#define CARDAMAGE_SIZE 228",
     "#define CARDAMAGE_SIZE 224"),
    ("ctor_damage_name", CIC, "\"CarDamage\", 0,", "\"CarDamag\", 0,"),
    ("ctor_damage_flags", CIC, "\"CarDamage\", 0,", "\"CarDamage\", 1,"),
    ("ctor_damage_pool", CIC, "\"CarDamage\", 0, CAR_MEMORY_POOL)",
     "\"CarDamage\", 0, 0)"),
    ("ctor_damage_discarded", CIC, "c->pCarDamage = gCarDamageCtorFn(",
     "(void)gCarDamageCtorFn("),
    ("ctor_damage_car", CIC,
     "bMalloc(CARDAMAGE_SIZE, \"CarDamage\", 0, CAR_MEMORY_POOL), c);",
     "bMalloc(CARDAMAGE_SIZE, \"CarDamage\", 0, CAR_MEMORY_POOL), NULL);"),
    ("ctor_control_mode", CIC, "c->TheControlMode = eNO_CONTROL;",
     "c->TheControlMode = 1;"),
    ("ctor_movement_mode", CIC, "c->TheMovementMode = eNO_MOVEMENT;",
     "c->TheMovementMode = 1;"),
    ("ctor_body_discarded", CIC,
     "b = carcollisionbody_init((CarCollisionBody *)carcollisionbody_new(), c);",
     "b = (CarCollisionBody *)carcollisionbody_new();\n"
     "    carcollisionbody_init(b, c);"),
    ("ctor_body_car", CIC,
     "carcollisionbody_new(), c);", "carcollisionbody_new(), NULL);"),
    ("ctor_trail", CIC, "    c->pLastCarTrailObj = NULL;", "   "),
    ("ctor_caffeine", CIC, "    c->pCaffeineObj = NULL;", "   "),
    ("ctor_leave_trails", CIC, "c->LeaveCarTrails = 0;",
     "c->LeaveCarTrails = 1;"),
    ("ctor_body_late", CIC,
     "    c->pDynamicCollisionBody = b;                       // 52\n"
     "    esp_set_attribute_int(0, \"CarNumber\", c->DriverNumber);\n",
     "    esp_set_attribute_int(0, \"CarNumber\", c->DriverNumber);\n"
     "    c->pDynamicCollisionBody = b;                       // 52\n"),
    ("ctor_esp_obj", CIC, "esp_set_attribute_int(0,", "esp_set_attribute_int(1,"),
    ("ctor_esp_name", CIC, "\"CarNumber\"", "\"CarNumbr\""),
    ("ctor_esp_value", CIC, "\"CarNumber\", c->DriverNumber);",
     "\"CarNumber\", c->CarIndex);"),
    ("ctor_gear_early", CIC,
     "    car_put_flat_on_track(c);\n    c->State.CurrentGear = 2;",
     "    c->State.CurrentGear = 2;\n    car_put_flat_on_track(c);"),
    ("ctor_gear", CIC, "c->State.CurrentGear = 2;", "c->State.CurrentGear = 3;"),
    ("ctor_disp_gear", CIC, "c->DispGear = 1;", "c->DispGear = 2;"),
    ("ctor_old_speed", CIC, "c->OldSpeed = 0.0f;", "c->OldSpeed = 1.0f;"),
    ("ctor_no_render_info_null", CIC,
     "    c->pRenderInfo = NULL;                              // 1200\n", ""),
    ("ctor_no_init_render_info", CIC,
     "        gCarInitRenderInfoFn(c, c->pRideInfo);", "        ;"),
    ("ctor_parts_early", CIC,
     "    if (gCarInitRenderInfoFn != NULL)\n"
     "        gCarInitRenderInfoFn(c, c->pRideInfo);\n",
     "    if (c->pCarDamage != NULL && gCarDamageFindItemPartsFn != NULL)\n"
     "        gCarDamageFindItemPartsFn(c->pCarDamage);\n"
     "    if (gCarInitRenderInfoFn != NULL)\n"
     "        gCarInitRenderInfoFn(c, c->pRideInfo);\n"
     "    if (0)\n"),
    ("ctor_parts_cached", CIC, [
        ("    if (gCarInitRenderInfoFn != NULL)\n"
         "        gCarInitRenderInfoFn(c, c->pRideInfo);\n",
         "    m = (NullMover *)c->pCarDamage;\n"
         "    if (gCarInitRenderInfoFn != NULL)\n"
         "        gCarInitRenderInfoFn(c, c->pRideInfo);\n"),
        ("    if (c->pCarDamage != NULL) {\n"
         "        if (gCarDamageFindItemPartsFn == NULL)",
         "    if (m != NULL) {\n"
         "        if (gCarDamageFindItemPartsFn == NULL)"),
        ("        gCarDamageFindItemPartsFn(c->pCarDamage);",
         "        gCarDamageFindItemPartsFn((CarDamage *)m);")], None),
    ("ctor_no_parts", CIC, "        gCarDamageFindItemPartsFn(c->pCarDamage);",
     "        ;"),
    ("ctor_rendering", CIC, "c->RenderingEnabled = 1;",
     "c->RenderingEnabled = 0;"),
    ("ctor_driver_rendering", CIC, "c->DriverRenderingEnabled = 1;",
     "c->DriverRenderingEnabled = 0;"),
    ("ctor_reset_me", CIC, "c->ResetMe = 0;", "c->ResetMe = 1;"),
    ("ctor_just_reset", CIC, "c->JustResetFrames = 0;",
     "c->JustResetFrames = 1;"),
    ("ctor_trough_before_render_info", CIC, [
        ("    if (gCarInitRenderInfoFn != NULL)\n"
         "        gCarInitRenderInfoFn(c, c->pRideInfo);\n",
         "    at = c->State.Position;\n"
         "    if (gCarInitRenderInfoFn != NULL)\n"
         "        gCarInitRenderInfoFn(c, c->pRideInfo);\n"),
        ("c->LastInTroughPosition.x = c->State.Position.x;",
         "c->LastInTroughPosition.x = at.x;"),
        ("c->LastInTroughPosition.y = c->State.Position.y;",
         "c->LastInTroughPosition.y = at.y;")], None),
    ("ctor_trough_start", CIC, [
        ("c->LastInTroughPosition.x = c->State.Position.x;",
         "c->LastInTroughPosition.x = at.x;"),
        ("c->LastInTroughPosition.y = c->State.Position.y;",
         "c->LastInTroughPosition.y = at.y;")], None),
    ("ctor_trough_y", CIC,
     "c->LastInTroughPosition.y = c->State.Position.y;",
     "c->LastInTroughPosition.y = c->State.Position.x;"),
    ("ctor_no_em_add", CIC,
     "    if (gEmAddHandlerFn != NULL)\n"
     "        gEmAddHandlerFn(car_reflect_event_handler, CAR_EVENT_MASK);\n",
     ""),
    ("ctor_trough_late", CIC, [
        ("    c->LastInTroughPosition.x = c->State.Position.x;    // 2152\n"
         "    c->LastInTroughPosition.y = c->State.Position.y;    // 2156\n",
         ""),
        ("        gEmAddHandlerFn(car_reflect_event_handler, CAR_EVENT_MASK);\n",
         "        gEmAddHandlerFn(car_reflect_event_handler, CAR_EVENT_MASK);\n"
         "    c->LastInTroughPosition.x = c->State.Position.x;\n"
         "    c->LastInTroughPosition.y = c->State.Position.y;\n")], None),
    ("ctor_event_mask", CIH, "#define CAR_EVENT_MASK 0x10000u",
     "#define CAR_EVENT_MASK 0x8000u"),
    ("ctor_event_handler", CIC,
     "gEmAddHandlerFn(car_reflect_event_handler,",
     "gEmAddHandlerFn((EmHandlerFn)car_event_handler,"),
    ("ctor_wiper_on", CIC, "c->WiperOnTime = 0;", "c->WiperOnTime = 1;"),
    ("ctor_wiper_off", CIC, "c->WiperOffTime = 0;", "c->WiperOffTime = 1;"),
    ("ctor_wiper_state", CIC, "c->WiperState = 0;", "c->WiperState = 1;"),
    ("ctor_siren", CIC, "c->TheSirenMode = 0;", "c->TheSirenMode = 1;"),
    ("ctor_cop_lights", CIC, "c->CopLights = 0;", "c->CopLights = 1;"),
    ("ctor_cop_lights_byte", CIC,
     "    memset(c->_hole1881, 0, sizeof c->_hole1881);\n", ""),
    ("ctor_headlights_state", CIC, "c->HeadlightsState = 0;",
     "c->HeadlightsState = 1;"),
    ("ctor_force_headlights", CIC, "c->ForceHeadlightsOn = 0;",
     "c->ForceHeadlightsOn = 1;"),
    ("ctor_want_blink", CIC, "c->WantToBlinkHeadlights = 0;",
     "c->WantToBlinkHeadlights = 1;"),
    ("ctor_want_honk", CIC, "c->WantToHonkHorn = 0;",
     "c->WantToHonkHorn = 1;"),
    ("ctor_want_two", CIC, "c->WantTwoHonksAndOrBlinks = 0;",
     "c->WantTwoHonksAndOrBlinks = 1;"),
    ("ctor_signal", CIC, "c->SignalLightState = SIGNAL_LIGHT_ALL_OFF;",
     "c->SignalLightState = SIGNAL_LIGHT_ALL_ON;"),
    ("ctor_start_time", CIC, "c->HeadlightsAndHornStartTime = WorldTimer;",
     "c->HeadlightsAndHornStartTime = 0;"),
    ("ctor_off", CIC, "c->HeadlightsAndHornOffDuration = -1.0f;",
     "c->HeadlightsAndHornOffDuration = 1.0f;"),
    ("ctor_on", CIC, "c->HeadlightsAndHornOnDuration = -1.0f;",
     "c->HeadlightsAndHornOnDuration = 1.0f;"),
    ("ctor_second_on", CIC, "c->HeadlightsAndHornSecondOnDuration = -1.0f;",
     "c->HeadlightsAndHornSecondOnDuration = 1.0f;"),
    ("ctor_no_stop_blinking", CIC, "    car_stop_blinking(c);\n", ""),
    ("ctor_stop_blinking_early", CIC, [
        ("    car_stop_blinking(c);\n", ""),
        ("    c->HeadlightsAndHornStartTime = WorldTimer;",
         "    car_stop_blinking(c);\n"
         "    c->HeadlightsAndHornStartTime = WorldTimer;")], None),
    ("ctor_track_map", CIC, "c->bVisibleOnTrackMap = 1;",
     "c->bVisibleOnTrackMap = 0;"),
    ("ctor_air_time", CIC, "c->AirTimeSwitch = 0.0f;",
     "c->AirTimeSwitch = 1.0f;"),
    ("ctor_poofed", CIC, "c->bPoofed = 0;", "c->bPoofed = 1;"),
    ("ctor_blink_duration", CIC, "c->BlinkDuration = 2.0f;",
     "c->BlinkDuration = 1.0f;"),
    ("ctor_buzz_no_half", CIC, "4000.0f\n                                  + 0.5f);",
     "4000.0f);"),
    ("ctor_buzz_unscaled", CIC, "(float)WorldTimer * 0.00025f * 4000.0f",
     "(float)WorldTimer"),
    ("ctor_buzz_double", CIC, "(float)WorldTimer * 0.00025f * 4000.0f\n"
     "                                  + 0.5f);",
     "(float)((double)WorldTimer * 0.00025 * 4000.0 + 0.5));"),
    ("ctor_buzz_cast", CIC, "c->ForceBuzzTime = ee_trunc_w(",
     "c->ForceBuzzTime = (int32_t)("),
    ("ctor_buzz_floor", CIC, "c->ForceBuzzTime = ee_trunc_w(",
     "c->ForceBuzzTime = ee_trunc_w(-0.5f + "),
    ("ctor_skidding", CIC,
     "memset(c->NumTimesSkidding, 0, sizeof c->NumTimesSkidding);",
     "memset(c->NumTimesSkidding, 0, 3);"),
    ("ctor_road_bump", CIC, "c->RoadBumpBits = 0;", "c->RoadBumpBits = 1;"),
    ("ctor_nitro_effect", CIC, "c->NitroEffectFlag = 0;",
     "c->NitroEffectFlag = 1;"),
    ("ctor_deep_water", CIC, "c->InDeepWaterRegistered = 0;",
     "c->InDeepWaterRegistered = 1;"),
    ("ctor_return", CIC, "    return c;\n}", "    return (Car *)driver;\n}"),

    # ---- the null controller, carcontroller.c
    ("ncc_controller_name", CCC, "\"NullController\", 0,",
     "\"NullControler\", 0,"),
    ("ncc_controller_pool", CCC, "\"NullController\", 0, CAR_MEMORY_POOL",
     "\"NullController\", 0, 0"),
    ("ncc_driver_name", CCC, "\"NullDriver\", 0,", "\"NullDrive\", 0,"),
    ("ncc_driver_flags", CCC, "\"NullDriver\", 0,", "\"NullDriver\", 1,"),
    ("ncc_driver_pool", CCC,
     "\"NullDriver\", 0,\n                                CAR_MEMORY_POOL);",
     "\"NullDriver\", 0,\n                                0);"),
    ("ncc_controller_vtable", CCC,
     "ctrl->Base._vtable = NULLCONTROLLER_VTABLE;",
     "ctrl->Base._vtable = CARCONTROLLER_VTABLE;"),
    ("ncc_driver_vtable", CCC, "drv->Base._vtable = NULLDRIVER_VTABLE;",
     "drv->Base._vtable = CARDRIVER_VTABLE;"),
    ("ncc_no_driver_link", CCC, "    ctrl->Base.Driver = &drv->Base;\n", ""),
    ("ncc_no_driver_init", CCC, "    cardriver_init(&drv->Base);\n", ""),

    # ---- espresso.c
    ("esp_set_value", ESC, "gEspSetAttributeIntFn(obj, name, value);",
     "gEspSetAttributeIntFn(obj, name, 0);"),
    ("esp_set_skipped", ESC,
     "    if (gEspSetAttributeIntFn != NULL)\n"
     "        gEspSetAttributeIntFn(obj, name, value);\n",
     "    (void)obj;\n    (void)name;\n    (void)value;\n"),

    # ---- the destructor
    ("dtor_no_controller", CIC,
     "    if (c->pCarController != NULL)\n        virtual_delete(",
     "    if (0)\n        virtual_delete("),
    ("dtor_no_mover", CIC,
     "    if (c->pCarMover != NULL)\n        virtual_delete(",
     "    if (0)\n        virtual_delete("),
    ("dtor_no_body", CIC,
     "    if (c->pDynamicCollisionBody != NULL)\n        virtual_delete(",
     "    if (0)\n        virtual_delete("),
    ("dtor_delete_flags", CIC, "((DtorFn)e->fn)(vt_this(obj, e), 3);",
     "((DtorFn)e->fn)(vt_this(obj, e), 1);"),
    ("dtor_delete_this", CIC, "((DtorFn)e->fn)(vt_this(obj, e), 3);",
     "((DtorFn)e->fn)(obj, 3);"),
    ("dtor_mover_first", CIC,
     "    if (c->pCarController != NULL)\n"
     "        virtual_delete(c->pCarController, c->pCarController->_vtable,\n"
     "                       CARCONTROLLER_VT_DTOR);\n"
     "    if (c->pCarMover != NULL)\n"
     "        virtual_delete(c->pCarMover, c->pCarMover->_vtable,\n"
     "                       CARMOVER_VT_DTOR);\n",
     "    if (c->pCarMover != NULL)\n"
     "        virtual_delete(c->pCarMover, c->pCarMover->_vtable,\n"
     "                       CARMOVER_VT_DTOR);\n"
     "    if (c->pCarController != NULL)\n"
     "        virtual_delete(c->pCarController, c->pCarController->_vtable,\n"
     "                       CARCONTROLLER_VT_DTOR);\n"),
    ("dtor_no_damage", CIC, "    if (c->pCarDamage != NULL) {\n        if (gCarDamageDestroyFn",
     "    if (0) {\n        if (gCarDamageDestroyFn"),
    ("dtor_damage_flags", CIC, "gCarDamageDestroyFn(c->pCarDamage, 3);",
     "gCarDamageDestroyFn(c->pCarDamage, 1);"),
    ("dtor_damage_kept", CIC,
     "        c->pCarDamage = NULL;\n    }\n    car_close_render_info(c);",
     "    }\n    car_close_render_info(c);"),
    ("dtor_no_close_render_info", CIC,
     "    }\n    car_close_render_info(c);\n", "    }\n"),
    ("dtor_render_info_first", CIC,
     "    if (c->pCarDamage != NULL) {\n        if (gCarDamageDestroyFn",
     "    car_close_render_info(c);\n"
     "    if (c->pCarDamage != NULL) {\n        if (gCarDamageDestroyFn"),
    ("dtor_caffeine_always", CIC,
     "    if (c->pCaffeineObj != NULL)\n        esp_delete_object",
     "    if (1)\n        esp_delete_object"),
    ("dtor_no_caffeine", CIC,
     "    if (c->pCaffeineObj != NULL)\n        esp_delete_object",
     "    if (0)\n        esp_delete_object"),
    ("dtor_no_sound", CIC, "    if (c->pBaseCarSound != NULL) {",
     "    if (0) {"),
    ("dtor_sound_flags", CIC, "gBaseCarSoundDestroyFn(c->pBaseCarSound, 3);",
     "gBaseCarSoundDestroyFn(c->pBaseCarSound, 2);"),
    ("dtor_sound_before_caffeine", CIC,
     "    if (c->pCaffeineObj != NULL)\n"
     "        esp_delete_object(c->pCaffeineObj);\n",
     "    if (c->pBaseCarSound != NULL && gBaseCarSoundDestroyFn != NULL)\n"
     "        gBaseCarSoundDestroyFn(c->pBaseCarSound, 3);\n"
     "    if (c->pCaffeineObj != NULL)\n"
     "        esp_delete_object(c->pCaffeineObj);\n"
     "    if (0)\n"),
    ("dtor_no_em_remove", CIC,
     "        gEmRemoveHandlerFn(car_reflect_event_handler);", "        ;"),
    ("dtor_em_remove_fn", CIC,
     "        gEmRemoveHandlerFn(car_reflect_event_handler);",
     "        gEmRemoveHandlerFn((EmHandlerFn)car_event_handler);"),
    ("dtor_no_topology", CIC,
     "    topology_destroy(&c->TheTopologyCoordinate);\n", ""),
    ("dtor_topology_first", CIC,
     "    if (gEmRemoveHandlerFn != NULL)\n"
     "        gEmRemoveHandlerFn(car_reflect_event_handler);\n",
     "    topology_destroy(&c->TheTopologyCoordinate);\n"
     "    if (gEmRemoveHandlerFn != NULL)\n"
     "        gEmRemoveHandlerFn(car_reflect_event_handler);\n"
     "    if (0)\n"),
    ("dtor_flags_any", CIC, "    if (flags & 1)\n        bFree(c);",
     "    if (flags)\n        bFree(c);"),
    ("dtor_flags_eq", CIC, "    if (flags & 1)\n        bFree(c);",
     "    if (flags == 1)\n        bFree(c);"),
    ("dtor_flags_bit1", CIC, "    if (flags & 1)\n        bFree(c);",
     "    if (flags & 2)\n        bFree(c);"),
    ("dtor_no_free", CIC, "    if (flags & 1)\n        bFree(c);",
     "    if (0)\n        bFree(c);"),

    # ---- the helpers
    ("close_no_destroy", CIC, "        gCarRenderInfoDestroyFn(c->pRenderInfo, 3);",
     "        ;"),
    ("close_flags", CIC, "gCarRenderInfoDestroyFn(c->pRenderInfo, 3);",
     "gCarRenderInfoDestroyFn(c->pRenderInfo, 1);"),
    ("close_kept", CIC, "    }\n    c->pRenderInfo = NULL;\n}", "    }\n}"),
    ("reflect_no_check", CIC, "    if (e->CarPtr != NULL)\n        car_event_handler",
     "    if (1)\n        car_event_handler"),
    ("reflect_event", CIC, "car_event_handler(e->CarPtr, e);",
     "car_event_handler(e->CarPtr, NULL);"),
]

# Mutations that survive because they change nothing the image can tell.
EQUIVALENT = {
    # The start's w goes only to the lanes the console takes from the
    # stack, vOldVel's and vOldAngVel's always, vOldPos's and
    # State.Position's with no position given; both sides print those `*`.
    "ctor_start_w",
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    base = model(sc)
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

    for m in todo:
        name, rel, before, after = m
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

    sc = script()
    lines = model(sc)
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
    print("%d scenarios, %d lines, %d differ" % (len(sc), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
