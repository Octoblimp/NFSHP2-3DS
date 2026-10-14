#!/usr/bin/env python3
"""Cross-check 3DS Files/source/careffects.c, Car::TriggerCarTerrainEffects,
against the retail image itself, run in mipsemu.

The model is the image. Retail's TriggerCarTerrainEffects (0x00133920) runs
as shipped, with the terrain table at 0x00318c00 as the disc has it, and
under it Car::TurnWipersOnForDuration (0x00133528), bMulMatrix
(0x0025aed0), CarDamage's item level (0x00124d38) and
BodyDamage::GetVisibleTotalDamage (0x001b50c8). The harness
(tools/src/careffects_test.c) runs the port over the same script, and the
two transcripts are diffed.

Four calls are stubbed, on both sides, and print their arguments: the
car's TriggerEffect (0x0011e2b8), the sound's TriggerSplash (0x0018d488),
the replay's RegisterInterestingEvent (0x0013e270) and the topology's
GetElevation (0x00152070), which answers the terrain the case names. The
Car, its CarDamage, the mover, the engine, the player, the sound and the
replay manager are blobs at retail's offsets on the model side and the
port's structs on the harness side.

A case sets every field the method reads -- the speed, the wheels, the
skid counts, the ground, the damage, the nitro, the flat tires, the wipers
and the two clocks -- and prints what it leaves in the car: the skid
counts, the wipers and InDeepWaterRegistered, which carries from case to
case unless the case sets it. A float prints as its bits.

    python tools/careffects_check.py
    python tools/careffects_check.py --mutate [--only a,b]
    python tools/careffects_check.py --dump out/careffects
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import physicscar_check as pcc
import retail_model
from mipsemu import M32, f_to_bits, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/careffects_test.c"
CFX = "3DS Files/source/careffects.c"
SOURCES = [HARNESS, CFX] + ["3DS Files/source/" + f for f in (
    "car.c", "carstate.c", "cardamage.c", "estripdata.c",
    "terraintypetab.c", "bvector.c",
    "bmath.c", "bmathtab.c", "bmatrix.c", "emath.c", "vtable.c", "world.c",
    "graph.c", "table.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
TCTE = 0x00133920
TRIGGER_EFFECT = 0x0011e2b8
TRIGGER_SPLASH = 0x0018d488
REGISTER_EVENT = 0x0013e270
GET_ELEVATION = 0x00152070
BMATRIX_SINIT = 0x0025afa8        # writes the (0, 0, 0, 1) bMulMatrix adds

G_FRAMES = GP - 19564             # WorldTimeFrames
G_LOOP = GP - 19552               # WorldLoopCounter
G_REPLAY = GP - 22440             # pReplayManager
G_DAMAGE = 0x0031a8d8             # TheRaceParameters.DamageEnabled
TT_TABLE, TT_STRIDE = 0x00318c00, 144
TT_DO_MIN, TT_DO_MAX = 64, 68     # TerrainTypeInfo.DriveOver{Min,Max}Speed

# The blobs.
CAR = 0x01000000
CAR_SIZE = 2200
MOVER = 0x01001000                # the PhysicsCar, under PHYSICS_MOVEMENT
ENGINE = 0x01001100
CDMG = 0x01002000
CD_SIZE = 212
PLAYER = 0x01003000
PLAYER_SIZE = 20                  # only ever tested for NULL
SND = 0x01003100
RM = 0x01003200

# Retail's Car.
C_PLAYER, C_MOVE, C_MOVER, C_STATE = 24, 36, 48, 64
C_TC = 1312                       # TheTopologyCoordinate
C_NITRO = 2064                    # NitroEffectFlag
C_WON, C_WOFF, C_WSTATE = 2108, 2112, 2116
C_DAMAGE = 2120
C_BLOWN, C_NBLOWN = 2124, 2125
C_SOUND = 2132
C_NTS = 2168                      # NumTimesSkidding
C_DEEPREG = 2196                  # InDeepWaterRegistered
# Its CarState.
CS_POS, CS_VEL, CS_WM = 32, 48, 176
CS_BO, CS_TOUCH, CS_TERR, CS_SLIP = 752, 784, 788, 820
CS_VMAG = 900
# The rest.
PC_ENGINE, EN_NITRO = 64, 80      # PhysicsCar.pEngine, Engine.NitroFlag
CD_ITEMS = 204                    # CarDamage.BreakableCarItemDamageAmounts
CD_TOTAL = 8 + 40                 # TheBodyDamage.CompressedTotalDamage


def fb(v):
    if isinstance(v, int):
        return v & M32
    return f_to_bits(v)


# ============================================================ the scenarios

FX_FRAMES = 5000                  # WorldTimeFrames, unless a case says
FX_LOOP = 1                       # WorldLoopCounter: a step the replay hears
FX_POS = (12.0, -7.0, 1.5, 0.25)  # the state's Position
FX_VEL = (3.0, -4.5, 0.75, 0.5)   # and Velocity, all four lanes
FX_WIPERS0 = (0, 0, 0)            # WiperState, WiperOnTime, WiperOffTime


def fx_matrix(i):
    """Wheel i's matrix: sixteen eighths, none of them in step, and a w
    column that is not (0, 0, 0, 1), so the spew point's fourth lane has
    something to carry."""
    return [0.125 * ((r * 5 + c * 3 + i * 7) % 13) - 0.75
            for r in range(4) for c in range(4)]


def fx(dist=100.0, vmag=20.0, touch=(1, 1, 1, 1), terr=(1, 1, 1, 1),
       slip=((0.0, 0.0),) * 4, nts=(0, 0, 0, 0), ground=1, bo=(0.0,) * 4,
       dmg=None, player=False, nitro=0, move=0, engine=0, blown=(0, 0),
       snd=True, wipers=FX_WIPERS0, patch=None, now=FX_FRAMES,
       loop=FX_LOOP, reg=-1):
    """A case, as an F line. `dmg` is None for no CarDamage, else (items
    word, total damage halfword, DamageEnabled). `engine` is the physics
    car's NitroFlag, read only under move 1. `patch` is terrain 4's
    drive-over (min, max) for the case, put back after. `reg` is
    InDeepWaterRegistered going in, or -1 to keep what the last case
    left."""
    f = ["F", "%08x" % fb(dist), "%08x" % fb(vmag)]
    f += ["%d" % t for t in touch]
    f += ["%d" % t for t in terr]
    for x, y in slip:
        f += ["%08x" % fb(x), "%08x" % fb(y)]
    f += ["%d" % n for n in nts]
    f.append("%d" % ground)
    f += ["%08x" % fb(b) for b in bo]
    if dmg is None:
        f += ["0", "00000000", "0", "0"]
    else:
        items, total, en = dmg
        f += ["1", "%08x" % (items & M32), "%d" % total, "%d" % en]
    f += ["%d" % int(player), "%d" % nitro, "%d" % move, "%d" % engine,
          "%d" % blown[0], "%d" % blown[1], "%d" % int(snd)]
    f += ["%d" % s32(w & M32) for w in wipers]
    f += ["%d" % s32(now & M32), "%d" % s32(loop & M32), "%d" % reg]
    if patch:
        f += ["1", "%08x" % fb(patch[0]), "%08x" % fb(patch[1])]
    else:
        f += ["0", "00000000", "00000000"]
    return " ".join(f)


def s_setup():
    out = ["S pos " + " ".join("%08x" % fb(v) for v in FX_POS),
           "S vel " + " ".join("%08x" % fb(v) for v in FX_VEL)]
    for i in range(4):
        out.append("S wm %d " % i + " ".join("%08x" % fb(v)
                                               for v in fx_matrix(i)))
    return out


# Retail's terrains, as terraintypetab.c has them. 1 ROAD: skid smoke
# 5..40, spew 2..200, drive-over 20..100 mph and no second, bottom-out
# 1..2. 2 DIRT: no first drive-over group, the second 35..100, skid 5..20,
# spew 1.5..10, bottom-out 1..2. 4 PUDDLE and 5 DEEP_WATER: drive-over
# 3..30, the second 35..100, skid 5..20, spew 1..100, bottom-out 0.6..3
# with no group. 20 MUD_PUDDLE: drive-over 50..150. 0 NONE: no groups,
# bottom-out 50..100. 8 SNOW: no groups. 15 WOOD_WALL: skid 20..20 with no
# group. 31 POTHOLE: drive-over 20..100, skid 5..20, spew 2..200, no
# bottom-out group. A wheel's slip is (x, y); the smoke reads its length,
# the spew its x.
def s_terrain():
    return [
        # No wheel down: nothing, and the skid counts are left as they were.
        fx(touch=(0, 0, 0, 0), terr=(1, 2, 3, 4), nts=(5, 6, 7, 8),
           slip=((30.0, 40.0),) * 4, dist=30.0),
        # Too far for smoke: every count cleared. The ground still runs.
        fx(dist=150.0, slip=((50.0, 1.0),) * 4, nts=(9, 9, 9, 9)),
        # The count ladder, a length of 50 on the road, past its maximum.
        fx(slip=((30.0, 40.0),) * 4, nts=(0, 1, 18, 19)),
        fx(slip=((30.0, -40.0),) * 4, nts=(58, 59, 118, 119)),
        fx(slip=((-300.0, 0.0), (0.0, 300.0), (30.0, 40.0), (1.0, 7.0)),
           nts=(254, 255, 200, 0)),
        # Inside the road's window, so the ladder's fractions show.
        fx(slip=((12.0, 16.0),) * 4, nts=(1, 18, 58, 118)),
        fx(slip=((12.0, 16.0),) * 4, nts=(19, 59, 119, 200)),
        # A length exactly at the minimum clears; no smoke group counts but
        # shows nothing; dirt's window is narrower.
        fx(terr=(1, 0, 8, 2), slip=((5.0, 0.0), (60.0, 0.0), (25.0, 0.0),
                                    (0.0, -10.0)), nts=(7, 3, 4, 30)),
        fx(terr=(31, 31, 31, 31), slip=((3.0, 4.0), (4.0, 3.0),
                                        (-3.0, -4.0), (0.0, 5.000001)),
           nts=(40, 40, 40, 40)),
        # WOOD_WALL's 20..20 counts above 20 and shows nothing.
        fx(terr=(15, 15, 1, 15), slip=((25.0, 0.0), (20.0, 0.0),
                                       (25.0, 0.0), (0.0, 30.0)),
           nts=(3, 4, 5, 6)),
        # Tire spew: the rear two only, under 40, at the turned slip.
        fx(dist=20.0, terr=(2, 2, 2, 2), ground=2, vmag=30.0,
           slip=((8.0, 0.5), (8.0, -0.5), (4.0, 1.25), (20.0, -2.0))),
        fx(dist=39.5, terr=(1, 1, 31, 1), ground=1, vmag=7.5,
           slip=((100.0, 0.0), (0.0, 0.0), (150.0, -20.0), (2.5, 0.25)),
           nts=(2, 2, 2, 2)),
        fx(dist=40.0, slip=((0.0, 0.0), (0.0, 0.0), (100.0, 0.0),
                            (100.0, 0.0))),
        fx(dist=10.0, terr=(1, 1, 0, 8),
           slip=((0.0, 0.0),) * 2 + ((50.0, 0.0),) * 2),
        fx(dist=10.0, slip=((0.0, 0.0), (0.0, 0.0), (-50.0, 0.0),
                            (2.0, 9.0))),
        # Two wheels down: no ground.
        fx(dist=10.0, touch=(1, 1, 0, 0), slip=((10.0, 0.0),) * 4,
           nts=(3,) * 4, bo=(2.0,) * 4),
        # A byte of 0x80 is a wheel down.
        fx(dist=10.0, touch=(0x80, 0, 0x80, 0x80), terr=(2, 2, 2, 2),
           ground=2, vmag=40.0, slip=((3.0, 0.0),) * 4, nts=(2, 2, 2, 2)),
        # The splash. Wheel 0 in a puddle: left, 1.
        fx(dist=50.0, vmag=12.0, terr=(4, 1, 1, 1), ground=4),
        # Wheel 1 in deep water: right, 3.
        fx(dist=50.0, vmag=30.0, terr=(1, 5, 1, 1), ground=5),
        # A mud puddle and a puddle behind: right, 1. Both drive-overs, the
        # first cut back.
        fx(dist=59.0, vmag=44.7, terr=(1, 1, 20, 4), ground=4),
        # Wheel 3 in deep water: left, 3, and no sound to tell.
        fx(dist=50.0, vmag=15.0, terr=(1, 1, 1, 5), snd=False),
        # At 60, and at 10 m/s: no splash.
        fx(dist=60.0, vmag=20.0, terr=(4, 4, 4, 4), ground=4),
        fx(dist=50.0, vmag=10.0, terr=(4, 4, 4, 4), ground=4),
        # A wet wheel up is not wet; near names are not wet either.
        fx(dist=50.0, touch=(0, 1, 1, 1), terr=(4, 1, 1, 1)),
        fx(dist=50.0, terr=(3, 6, 19, 21), ground=3),
        # The wipers already running, or a window already open.
        fx(dist=50.0, terr=(5, 1, 1, 1), wipers=(1, 0, 0)),
        fx(dist=50.0, terr=(1, 1, 4, 1), wipers=(0, FX_FRAMES + 100,
                                                  FX_FRAMES + 300)),
        fx(dist=50.0, terr=(1, 4, 1, 1), wipers=(0, FX_FRAMES - 500,
                                                  FX_FRAMES - 100), now=77),
        # The drive-over pair with the first window moved: its minimum
        # equal to the second's, and then above it, so the second gives way.
        fx(vmag=25.37, ground=4, patch=(35.0, 59.0)),
        fx(vmag=44.7, ground=4, patch=(50.0, 90.0)),
        fx(vmag=25.37, ground=4, patch=(34.0, 59.0)),
        # Bottom-out: the road's; a puddle's, which has no group; no
        # terrain's.
        fx(bo=(0.1, 0.7, 0.3, 0.45)),
        fx(ground=4, bo=(1.0, 1.0, 1.0, 1.0), vmag=0.5),
        fx(ground=0, bo=(20.0, 20.0, 20.0, 5.0)),
        # Three down is enough, and the fourth wheel's bottom-out still
        # counts.
        fx(touch=(1, 1, 1, 0), bo=(0.25, 0.25, 0.25, 0.625), vmag=12.0),
        fx(ground=2, vmag=100.0),
        fx(ground=1, vmag=5.0),
        fx(ground=31, vmag=20.0, bo=(0.5, 0.5, 0.5, 0.5)),
        # Snow's drive-over window with no group; and the second drive-over
        # alone, the first's window moved above the speed.
        fx(ground=8),
        fx(ground=4, vmag=30.0, patch=(100.0, 200.0)),
        # The nitro: the flag, and a player's physics car on nitro.
        fx(nitro=1),
        fx(player=True),
        fx(move=1, player=True, engine=1),
        fx(move=1, player=True, engine=0),
        fx(move=1, player=False, engine=1),
        fx(move=1, player=True, engine=1, nitro=1),
        fx(move=1, player=True, engine=7, nitro=0),
        fx(move=2, player=True, engine=1),
        # The flat tires.
        fx(blown=(0x05, 0)),
        fx(blown=(0x05, 2), touch=(1, 1, 0, 1), vmag=5.0),
        fx(blown=(0x0f, 4), vmag=1.0),
        fx(blown=(0x0f, 4), vmag=40.0),
        fx(blown=(0x80, 0x80), vmag=9.0),
        fx(blown=(0xf8, 1), vmag=9.0),
    ]


# The replay's water events: a player's splash above 30 m/s on a step
# where (WorldLoopCounter + 3) & 3 is 0.
DEEP = dict(dist=50.0, vmag=35.0, terr=(1, 5, 1, 1), ground=5, player=True)
SHALLOW = dict(dist=50.0, vmag=35.0, terr=(4, 1, 1, 1), ground=4,
               player=True)


def w(base, **kw):
    d = dict(base)
    d.update(kw)
    return fx(**d)


def s_water():
    return [
        # Deep water: once, and then not while the car stays in it.
        w(DEEP, reg=0),
        w(DEEP),
        w(DEEP, loop=5),
        # Not on this step, and not at 30 m/s; just above it, it is.
        w(DEEP, reg=0, loop=2),
        w(DEEP, loop=3),
        w(DEEP, loop=4),
        w(DEEP, vmag=30.0),
        w(DEEP, vmag=30.000002),
        # Out of the deep water: shallow every time, and the flag cleared.
        w(SHALLOW),
        w(SHALLOW),
        w(SHALLOW, terr=(1, 1, 20, 1)),
        w(SHALLOW, terr=(1, 1, 1, 4), reg=1, loop=2),
        # A splash under 30: none, though the sound splashes.
        w(SHALLOW, vmag=20.0),
        w(DEEP, vmag=20.0, reg=0),
        # No player: none, and the flag kept while deep.
        w(DEEP, player=False, vmag=40.0, reg=0),
        w(DEEP, player=False, vmag=40.0, reg=1),
        # No splash: at 60, or at 10 m/s. Deep keeps the flag; out of it,
        # the flag clears anyway.
        w(DEEP, dist=60.0, vmag=40.0, reg=0),
        w(DEEP, dist=60.0, vmag=40.0, reg=1),
        w(DEEP, vmag=10.0, reg=1),
        w(SHALLOW, dist=60.0, reg=1),
        fx(dist=50.0, vmag=40.0, player=True, reg=1),
        # A deep wheel up is not deep.
        w(DEEP, touch=(1, 0, 1, 1), reg=1),
        # Deep and shallow at once is deep.
        w(DEEP, terr=(4, 1, 1, 5), reg=0),
        w(DEEP, terr=(4, 1, 20, 5)),
        # No sound: the replay still hears.
        w(DEEP, snd=False, reg=0),
        w(SHALLOW, snd=False),
        # The counter's word: -3 and 0x7ffffffd step onto a multiple of
        # four, -1 and 0 do not.
        w(DEEP, loop=-3, reg=0),
        w(SHALLOW, loop=0x7ffffffd),
        w(SHALLOW, loop=-1),
        w(SHALLOW, loop=0),
        w(SHALLOW, loop=0x7ffffffe),
        w(SHALLOW, loop=-7),
    ]


# The damage. Visible damage is the halfword over 4096; engine smoke above
# 0.9 (between 3686 and 3687), radiator steam above 0.65 (between 2662
# and 2663) when item 14's two bits are 3.
RAD = 3 << 28


def s_damage():
    return [
        fx(dmg=(RAD, 3687, 1)),
        fx(dmg=(RAD, 3686, 1)),
        fx(dmg=(RAD, 2663, 1)),
        fx(dmg=(RAD, 2662, 1)),
        fx(dmg=(0, 3687, 1)),
        fx(dmg=(0, 3686, 1)),
        fx(dmg=(2 << 28, 3000, 1)),
        fx(dmg=(1 << 28, 3000, 1)),
        fx(dmg=(RAD, 4096, 0)),
        fx(dmg=(RAD, 65535, 0)),
        fx(dmg=(0xcfffffff, 3000, 1)),
        fx(dmg=(0xffffffff, 3000, 1)),
        fx(dmg=(3 << 26, 3000, 1)),
        fx(dmg=(3 << 30, 3000, 1)),
        fx(dmg=(0, 65535, 1)),
        fx(dmg=(RAD, 65535, 1)),
        fx(dmg=(0, 0, 1)),
        fx(dmg=(RAD, 0, 1)),
    ]


def script():
    return [s_setup() + s_terrain(), s_water(), s_damage()]


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
        self.ground = 0
        self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        e = self.e
        e.stub(TRIGGER_EFFECT, self.rec_effect)
        e.stub(TRIGGER_SPLASH, self.rec_splash)
        e.stub(REGISTER_EVENT, self.rec_event)
        e.stub(GET_ELEVATION, self.rec_elev)
        # The emulator runs no static constructors; bMatrix's writes the
        # (0, 0, 0, 1) bMulMatrix starts its sum from.
        e.call(BMATRIX_SINIT, limit=200000)
        e.write(CAR, bytes(CAR_SIZE))
        e.write(MOVER, bytes(0x100))
        e.write(ENGINE, bytes(0x100))
        e.write(CDMG, bytes(CD_SIZE))
        e.write(PLAYER, bytes(PLAYER_SIZE))
        e.write(SND, bytes(16))
        e.write(RM, bytes(16))
        e.put32(MOVER + PC_ENGINE, ENGINE)
        e.put32(CAR + C_MOVER, MOVER)
        e.put32(G_REPLAY, RM)
        self.labels = {0: "NULL", CAR: "car", CAR + C_TC: "car.tc",
                       CAR + C_STATE + CS_POS: "pos", SND: "snd", RM: "rm"}

    def emit(self, s):
        self.out.append(s)

    def arg(self, i):
        return self.e.reg[(4, 5, 6, 7, 8)[i]] & M32

    def w(self, a):
        return self.e.u32(a)

    def label(self, a):
        return self.labels.get(a & M32, "?")

    def cstr(self, a):
        s = bytearray()
        while True:
            b = self.e.u8(a + len(s))
            if b == 0:
                return s.decode("latin-1")
            s.append(b)

    # ---- the stand-ins ---------------------------------------------------

    def rec_effect(self, em):
        pos = self.arg(3)
        s = "effect car=%s fx=%d scale=%08x where=%08x" % (
            self.label(self.arg(0)), s32(self.arg(1)),
            self.e.fpr[12] & M32, self.arg(2))
        if pos:
            s += " at=" + " ".join("%08x" % self.w(pos + 4 * k)
                                   for k in range(4))
        else:
            s += " at=NULL"
        self.emit(s)

    def rec_splash(self, em):
        self.emit("splash snd=%s right=%d level=%d" % (
            self.label(self.arg(0)), s32(self.arg(1)), s32(self.arg(2))))

    def rec_event(self, em):
        self.emit("interesting rm=%s value=%08x what=%s" % (
            self.label(self.arg(0)), self.e.fpr[12] & M32,
            self.cstr(self.arg(1))))

    def rec_elev(self, em):
        tout = self.arg(2)
        self.emit("elev tc=%s pos=%s tout=%s nout=%s found=%s" % (
            self.label(self.arg(0)), self.label(self.arg(1)),
            "yes" if tout else "NULL", self.label(self.arg(3)),
            self.label(self.arg(4))))
        if tout:
            self.e.put32(tout, self.ground & M32)
        self.e.fpr[0] = 0
        return 0

    # ---- the ops ---------------------------------------------------------

    def op_state(self, t):
        e = self.e
        cs = CAR + C_STATE
        if t[1] in ("pos", "vel"):
            at = cs + (CS_POS if t[1] == "pos" else CS_VEL)
            for k in range(4):
                e.put32(at + 4 * k, int(t[2 + k], 16))
        elif t[1] == "wm":
            i = int(t[2])
            for k in range(16):
                e.put32(cs + CS_WM + 64 * i + 4 * k, int(t[3 + k], 16))
        else:
            raise SystemExit("bad state %r" % (t,))

    def op_fx(self, t):
        e = self.e
        cs = CAR + C_STATE
        vals = iter(t[1:])

        def x():
            return int(next(vals), 16) & M32

        def i():
            return int(next(vals), 0) & M32

        dist = x()
        e.put32(cs + CS_VMAG, x())
        for k in range(4):
            e.write(cs + CS_TOUCH + k, bytes([i() & 0xff]))
        for k in range(4):
            e.put32(cs + CS_TERR + 4 * k, i())
        for k in range(4):
            e.put32(cs + CS_SLIP + 8 * k, x())
            e.put32(cs + CS_SLIP + 8 * k + 4, x())
        for k in range(4):
            e.write(CAR + C_NTS + k, bytes([i() & 0xff]))
        self.ground = i()
        for k in range(4):
            e.put32(cs + CS_BO + 4 * k, x())
        hasdmg, items, total, enabled = i(), x(), i(), i()
        if hasdmg:
            e.put32(CDMG + CD_ITEMS, items)
            e.write(CDMG + CD_TOTAL, struct.pack("<H", total & 0xffff))
            e.put32(CAR + C_DAMAGE, CDMG)
        else:
            e.put32(CAR + C_DAMAGE, 0)
        e.put32(G_DAMAGE, enabled)
        e.put32(CAR + C_PLAYER, PLAYER if i() else 0)
        e.put32(CAR + C_NITRO, i())
        e.put32(CAR + C_MOVE, i())
        e.put32(ENGINE + EN_NITRO, i())
        e.write(CAR + C_BLOWN, bytes([i() & 0xff]))
        e.write(CAR + C_NBLOWN, bytes([i() & 0xff]))
        e.put32(CAR + C_SOUND, SND if i() else 0)
        e.put32(CAR + C_WSTATE, i())
        e.put32(CAR + C_WON, i())
        e.put32(CAR + C_WOFF, i())
        e.put32(G_FRAMES, i())
        e.put32(G_LOOP, i())
        reg = s32(i())
        if reg >= 0:
            e.put32(CAR + C_DEEPREG, reg)
        patch, pmin, pmax = i(), x(), x()
        do4 = TT_TABLE + 4 * TT_STRIDE
        window0 = (self.w(do4 + TT_DO_MIN), self.w(do4 + TT_DO_MAX))
        if patch:
            e.put32(do4 + TT_DO_MIN, pmin)
            e.put32(do4 + TT_DO_MAX, pmax)

        e.fpr[12] = dist
        e.call(TCTE, CAR, limit=200000)

        e.put32(do4 + TT_DO_MIN, window0[0])
        e.put32(do4 + TT_DO_MAX, window0[1])
        self.emit("fx nts=%s wipers=%d %d %d reg=%d" % (
            " ".join("%d" % e.u8(CAR + C_NTS + k) for k in range(4)),
            s32(self.w(CAR + C_WON)), s32(self.w(CAR + C_WOFF)),
            s32(self.w(CAR + C_WSTATE)), s32(self.w(CAR + C_DEEPREG))))

    def run(self, scenarios):
        for n, sc in enumerate(scenarios):
            self.emit("B %d" % n)
            for ln in sc:
                self.emit("> " + ln[:40])
                t = ln.split()
                if t[0] == "S":
                    self.op_state(t)
                elif t[0] == "F":
                    self.op_fx(t)
                else:
                    raise SystemExit("bad op %r" % (t,))
        return self.out


# ================================================================ the build


def build_harness(tmp, name="careffects_test"):
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


def M(name, before, after, rel=CFX):
    return (name, rel, before, after)


MUTATIONS = [
    # -- the constants
    M("fx-mph", "CAR_MPH_PER_MPS         2.237f",
      "CAR_MPH_PER_MPS         2.236f"),
    M("fx-flat-min", "CAR_FLAT_TIRE_MIN_MPH   4.470272541f",
      "CAR_FLAT_TIRE_MIN_MPH   4.5f"),
    M("fx-flat-slope", "CAR_FLAT_TIRE_PER_MPH   0.04474f",
      "CAR_FLAT_TIRE_PER_MPH   0.045f"),
    M("fx-smoke-damage-demo", "CAR_ENGINE_SMOKE_DAMAGE    0.9f",
      "CAR_ENGINE_SMOKE_DAMAGE    0.8f"),
    M("fx-smoke-damage-up", "CAR_ENGINE_SMOKE_DAMAGE    0.9f",
      "CAR_ENGINE_SMOKE_DAMAGE    0.9002f"),
    M("fx-steam-damage", "CAR_RADIATOR_STEAM_DAMAGE  0.65f",
      "CAR_RADIATOR_STEAM_DAMAGE  0.6502f"),
    M("fx-steam-damage-down", "CAR_RADIATOR_STEAM_DAMAGE  0.65f",
      "CAR_RADIATOR_STEAM_DAMAGE  0.6498f"),
    M("fx-radiator-broken", "CAR_RADIATOR_BROKEN        3",
      "CAR_RADIATOR_BROKEN        2"),
    M("fx-water-speed", "CAR_WATER_EVENT_SPEED    30.0f",
      "CAR_WATER_EVENT_SPEED    31.0f"),
    M("fx-deep-interest", "CAR_DEEP_WATER_INTEREST  10.0f",
      "CAR_DEEP_WATER_INTEREST  10.5f"),
    M("fx-shallow-interest", "CAR_SHALLOW_WATER_INTEREST 1.25f",
      "CAR_SHALLOW_WATER_INTEREST 1.5f"),
    M("fx-skid-range", "CAR_SKID_SMOKE_RANGE    150.0f",
      "CAR_SKID_SMOKE_RANGE    160.0f"),
    M("fx-spew-range", "CAR_TIRE_SPEW_RANGE      40.0f",
      "CAR_TIRE_SPEW_RANGE      45.0f"),
    M("fx-splash-range", "CAR_SPLASH_RANGE         60.0f",
      "CAR_SPLASH_RANGE         65.0f"),
    M("fx-splash-speed", "CAR_SPLASH_MIN_SPEED     10.0f",
      "CAR_SPLASH_MIN_SPEED      9.0f"),
    M("fx-wipers-on", "CAR_SPLASH_WIPERS_ON     60",
      "CAR_SPLASH_WIPERS_ON     61"),
    M("fx-wipers-off", "CAR_SPLASH_WIPERS_OFF   180",
      "CAR_SPLASH_WIPERS_OFF   300"),
    M("fx-where0", "CAR_WHEEL_WHERE0        0x50000",
      "CAR_WHEEL_WHERE0        0x40000"),
    M("fx-where-step", "CAR_WHEEL_WHERE_STEP    0x10000",
      "CAR_WHEEL_WHERE_STEP    0x20000"),
    M("fx-clamp-no-cap", "    return (x < 1.0f) ? x : 1.0f;",
      "    return x;"),
    M("fx-clamp-no-floor", "    return (x < 0.0f) ? 0.0f : x;",
      "    return x;"),
    M("fx-group-null-only", "    return name != NULL && name[0] != '\\0';",
      "    return name != NULL;"),
    # -- the wheels
    M("fx-three-wheels",
      "for (i = 0; i < 4; i++, where += CAR_WHEEL_WHERE_STEP)",
      "for (i = 0; i < 3; i++, where += CAR_WHEEL_WHERE_STEP)"),
    M("fx-wheel-up-counts",
      "        if (st->WheelTouchingGround[i] == 0)" + NL
      + "            continue;" + NL + "        down++;",
      "        down++;"),
    M("fx-no-count", "        down++;" + NL, ""),
    M("fx-ground-two", "    if (down >= 3) {", "    if (down >= 2) {"),
    M("fx-ground-four", "    if (down >= 3) {", "    if (down >= 4) {"),
    M("fx-wet-no-puddle",
      "if (terrain == TERRAIN_TYPE_PUDDLE || terrain == TERRAIN_TYPE_DEEP_WATER",
      "if (terrain == TERRAIN_TYPE_DEEP_WATER"),
    M("fx-wet-no-deep",
      "terrain == TERRAIN_TYPE_PUDDLE || terrain == TERRAIN_TYPE_DEEP_WATER",
      "terrain == TERRAIN_TYPE_PUDDLE"),
    M("fx-wet-no-mud",
      NL + "            || terrain == TERRAIN_TYPE_MUD_PUDDLE)", ")"),
    M("fx-wet-one-bit", "            wet |= 1 << i;", "            wet |= 1;"),
    M("fx-deep-puddle", "deep |= terrain == TERRAIN_TYPE_DEEP_WATER;",
      "deep |= terrain == TERRAIN_TYPE_PUDDLE;"),
    M("fx-deep-mud", "deep |= terrain == TERRAIN_TYPE_DEEP_WATER;",
      "deep |= terrain != TERRAIN_TYPE_PUDDLE;"),
    M("fx-mag-x-only", "sqrtf(slip->x * slip->x + slip->y * slip->y)",
      "sqrtf(slip->x * slip->x)"),
    M("fx-mag-squared", "sqrtf(slip->x * slip->x + slip->y * slip->y)",
      "(slip->x * slip->x + slip->y * slip->y)"),
    # -- the smoke
    M("fx-skid-range-le", "if (distance < CAR_SKID_SMOKE_RANGE",
      "if (distance <= CAR_SKID_SMOKE_RANGE"),
    M("fx-skid-min-le", "&& ti->SkidSmokeMinSpeed < mag)",
      "&& ti->SkidSmokeMinSpeed <= mag)"),
    M("fx-skid-kept", "        } else {" + NL
      + "            c->NumTimesSkidding[i] = 0;" + NL,
      "        } else {" + NL),
    M("fx-skid-step-2", "c->NumTimesSkidding[i] + 1;",
      "c->NumTimesSkidding[i] + 2;"),
    M("fx-skid-signed", "int32_t n = c->NumTimesSkidding[i] + 1;",
      "int32_t n = (int8_t)c->NumTimesSkidding[i] + 1;"),
    M("fx-skid-cap-256", "            if (n > 255)", "            if (n > 256)"),
    M("fx-skid-unstored",
      "            c->NumTimesSkidding[i] = (uint8_t)n;" + NL, ""),
    M("fx-skid-any-group",
      "            if (has_group(ti->SkidSmokeEmitterGroup)) {",
      "            {"),
    M("fx-skid-from-max", "s = (mag - ti->SkidSmokeMinSpeed)",
      "s = (mag - ti->SkidSmokeMaxSpeed)"),
    M("fx-skid-span", "/ (ti->SkidSmokeMaxSpeed - ti->SkidSmokeMinSpeed);",
      "/ ti->SkidSmokeMaxSpeed;"),
    M("fx-skid-first-shows", "                if (n < 2)",
      "                if (n < 1)"),
    M("fx-skid-20-le", "                else if (n < 20)",
      "                else if (n <= 20)"),
    M("fx-skid-60-le", "                else if (n < 60)",
      "                else if (n <= 60)"),
    M("fx-skid-120-le", "                else if (n < 120)",
      "                else if (n <= 120)"),
    M("fx-skid-quarter", "s = s * 0.25f;", "s = s * 0.3f;"),
    M("fx-skid-half", "s = s * 0.5f;", "s = s * 0.6f;"),
    M("fx-skid-three-quarters", "s = s * 0.75f;", "s = s * 0.7f;"),
    M("fx-skid-zero-shows", "                if (0.0f < s)" + NL
      + "                    effect(c, CARFX_SKID_SMOKE",
      "                effect(c, CARFX_SKID_SMOKE"),
    M("fx-skid-code", "effect(c, CARFX_SKID_SMOKE, s,",
      "effect(c, CARFX_TIRE_SPEW, s,"),
    M("fx-skid-where", "CARFX_SKID_SMOKE, s, where + terrain, NULL);",
      "CARFX_SKID_SMOKE, s, where, NULL);"),
    # -- the spew
    M("fx-spew-range-le", "if (!(distance < CAR_TIRE_SPEW_RANGE)",
      "if (!(distance <= CAR_TIRE_SPEW_RANGE)"),
    M("fx-spew-from-1", "|| i < 2", "|| i < 1"),
    M("fx-spew-from-3", "|| i < 2", "|| i < 3"),
    M("fx-spew-by-mag", "!(ti->TireSpewMinSpeed < slip->x)",
      "!(ti->TireSpewMinSpeed < mag)"),
    M("fx-spew-min-le", "!(ti->TireSpewMinSpeed < slip->x)",
      "!(ti->TireSpewMinSpeed <= slip->x)"),
    M("fx-spew-any-group",
      NL + "            || !has_group(ti->TireSpewEmitterGroup))", ")"),
    M("fx-spew-span", "/ (ti->TireSpewMaxSpeed - ti->TireSpewMinSpeed));",
      "/ (ti->TireSpewMaxSpeed));"),
    M("fx-spew-y-dropped", "            v.y = slip->y;",
      "            v.y = 0.0f;"),
    M("fx-spew-z-one", "            v.z = 0.0f;", "            v.z = 1.0f;"),
    M("fx-spew-pad-ignored", "            v.pad = 0.0f;",
      "            v.pad = 5.0f;"),
    M("fx-spew-wheel-0", "&st->WheelMatrix[i]", "&st->WheelMatrix[0]"),
    M("fx-spew-no-z", "            p.z = p.z + st->Velocity.z;" + NL, ""),
    M("fx-spew-no-pad",
      "            p.pad = p.pad + st->Velocity.pad;" + NL, ""),
    M("fx-spew-no-point", "where + terrain, &p);",
      "where + terrain, NULL);"),
    # -- the ground
    M("fx-ground-geometry", "&c->TheTopologyCoordinate, &st->Position,",
      "&c->TheTopologyCoordinate, &st->GeometryPosition,"),
    M("fx-ground-wheel-terrain",
      "        ti = &TerrainTypeInfoTable[terrain];" + NL
      + "        if (ti->DriveOverEmitterGroup",
      "        if (ti->DriveOverEmitterGroup"),
    M("fx-ground-road",
      "        ti = &TerrainTypeInfoTable[terrain];" + NL
      + "        if (ti->DriveOverEmitterGroup",
      "        ti = &TerrainTypeInfoTable[1];" + NL
      + "        if (ti->DriveOverEmitterGroup"),
    M("fx-do-any-group", "        if (ti->DriveOverEmitterGroup[0] != '\\0')",
      "        if (1)"),
    M("fx-do2-any-group",
      "        if (ti->DriveOver2EmitterGroup[0] != '\\0')", "        if (1)"),
    M("fx-do-from-max", "clamp01((mph - ti->DriveOverMinSpeed)",
      "clamp01((mph - ti->DriveOverMaxSpeed)"),
    M("fx-do2-first-window", "clamp01((mph - ti->DriveOver2MinSpeed)",
      "clamp01((mph - ti->DriveOverMinSpeed)"),
    M("fx-do-any-first", "        if (0.0f < drive + drive2) {",
      "        if (0.0f < drive) {"),
    M("fx-do-over-half", "float over = (drive + drive2) - 1.0f;",
      "float over = (drive + drive2) - 0.5f;"),
    M("fx-do-cut-once", "drive = max0(drive - (over + over));",
      "drive = max0(drive - over);"),
    M("fx-do2-cut-once", "drive2 = max0(drive2 - (over + over));",
      "drive2 = max0(drive2 - over);"),
    M("fx-do-order-le",
      "if (ti->DriveOverMinSpeed < ti->DriveOver2MinSpeed)",
      "if (ti->DriveOverMinSpeed <= ti->DriveOver2MinSpeed)"),
    M("fx-do-order-inverted",
      "if (ti->DriveOverMinSpeed < ti->DriveOver2MinSpeed)",
      "if (ti->DriveOver2MinSpeed < ti->DriveOverMinSpeed)"),
    M("fx-do-zero-shows", "            if (0.0f < drive)" + NL
      + "                effect(c, CARFX_DRIVE_OVER,",
      "                effect(c, CARFX_DRIVE_OVER,"),
    M("fx-do2-zero-shows", "            if (0.0f < drive2)" + NL
      + "                effect(c, CARFX_DRIVE_OVER2,",
      "                effect(c, CARFX_DRIVE_OVER2,"),
    M("fx-do-code", "effect(c, CARFX_DRIVE_OVER, drive,",
      "effect(c, CARFX_DRIVE_OVER2, drive,"),
    M("fx-do-where", "CARFX_DRIVE_OVER, drive, terrain, NULL);",
      "CARFX_DRIVE_OVER, drive, 0, NULL);"),
    M("fx-bo-three", "        for (i = 0; i < 4; i++)" + NL
      + "            sum = sum", "        for (i = 0; i < 3; i++)" + NL
      + "            sum = sum"),
    M("fx-bo-from-max", "clamp01((sum - ti->BottomOutMinImpact)",
      "clamp01((sum - ti->BottomOutMaxImpact)"),
    M("fx-bo-needs-group", "        if (0.0f < s)" + NL
      + "            effect(c, CARFX_BOTTOM_OUT",
      "        if (0.0f < s && has_group(ti->BottomOutEmitterGroup))" + NL
      + "            effect(c, CARFX_BOTTOM_OUT"),
    M("fx-bo-zero-shows", "        if (0.0f < s)" + NL
      + "            effect(c, CARFX_BOTTOM_OUT",
      "            effect(c, CARFX_BOTTOM_OUT"),
    # -- the splash
    M("fx-splash-range-le", "if (distance < CAR_SPLASH_RANGE",
      "if (distance <= CAR_SPLASH_RANGE"),
    M("fx-splash-two-wet", "&& wet > 0", "&& wet > 1"),
    M("fx-splash-speed-le", "&& CAR_SPLASH_MIN_SPEED < st->VelocityMagnitude",
      "&& CAR_SPLASH_MIN_SPEED <= st->VelocityMagnitude"),
    M("fx-wipers-swapped",
      "WorldTimeFrames + CAR_SPLASH_WIPERS_ON," + NL
      + "                                        WorldTimeFrames + "
      "CAR_SPLASH_WIPERS_OFF);",
      "WorldTimeFrames + CAR_SPLASH_WIPERS_OFF," + NL
      + "                                        WorldTimeFrames + "
      "CAR_SPLASH_WIPERS_ON);"),
    M("fx-wipers-now", "WorldTimeFrames + CAR_SPLASH_WIPERS_ON,",
      "CAR_SPLASH_WIPERS_ON,"),
    M("fx-splash-no-sound-test",
      "if (c->pBaseCarSound != NULL && gBaseCarSoundTriggerSplashFn != NULL)",
      "if (gBaseCarSoundTriggerSplashFn != NULL)"),
    M("fx-splash-left-front", "(wet & 6) != 0", "(wet & 3) != 0"),
    M("fx-splash-wheel-1", "(wet & 6) != 0", "(wet & 2) != 0"),
    M("fx-splash-levels", "deep ? 3 : 1", "deep ? 1 : 3"),
    # -- the replay's water events
    M("fx-event-any-car",
      "c->pPlayer != NULL && (((uint32_t)WorldLoopCounter",
      "(((uint32_t)WorldLoopCounter"),
    M("fx-event-every-step",
      "(((uint32_t)WorldLoopCounter + 3u) & 3u) == 0", "1"),
    M("fx-event-no-offset", "WorldLoopCounter + 3u)",
      "WorldLoopCounter + 0u)"),
    M("fx-event-mask-7", "+ 3u) & 3u) == 0", "+ 3u) & 7u) == 0"),
    M("fx-event-speed-le", "&& CAR_WATER_EVENT_SPEED < st->VelocityMagnitude",
      "&& CAR_WATER_EVENT_SPEED <= st->VelocityMagnitude"),
    M("fx-event-no-speed",
      NL + "            && CAR_WATER_EVENT_SPEED < st->VelocityMagnitude)",
      ")"),
    M("fx-event-deep-swapped", "            if (!deep) {",
      "            if (deep) {"),
    M("fx-event-deep-always",
      "} else if (c->InDeepWaterRegistered == 0) {", "} else {"),
    M("fx-event-no-register",
      "                c->InDeepWaterRegistered = 1;" + NL, ""),
    M("fx-event-deep-value", "interesting(CAR_DEEP_WATER_INTEREST, ",
      "interesting(CAR_SHALLOW_WATER_INTEREST, "),
    M("fx-event-names", "WATER_INTEREST, \"InShallowWater\");",
      "WATER_INTEREST, \"InDeepWater\");"),
    M("fx-event-reset-always",
      "    if (!deep)" + NL + "        c->InDeepWaterRegistered = 0;",
      "    c->InDeepWaterRegistered = 0;"),
    M("fx-event-no-reset",
      "    if (!deep)" + NL + "        c->InDeepWaterRegistered = 0;" + NL,
      ""),
    M("fx-event-reset-inside",
      "        }" + NL + "    }" + NL + "    if (!deep)" + NL
      + "        c->InDeepWaterRegistered = 0;",
      "        }" + NL + "        if (!deep)" + NL
      + "            c->InDeepWaterRegistered = 0;" + NL + "    }"),
    # -- the damage
    M("fx-item-one-bit", "    return (amounts >> (2 * item)) & 3;",
      "    return (amounts >> (2 * item)) & 1;"),
    M("fx-item-shift", "    return (amounts >> (2 * item)) & 3;",
      "    return (amounts >> item) & 3;"),
    M("fx-radiator-item-13",
      "BREAKABLE_CAR_ITEM_RADIATOR) == CAR_RADIATOR_BROKEN",
      "13) == CAR_RADIATOR_BROKEN"),
    M("fx-radiator-any-level",
      "BREAKABLE_CAR_ITEM_RADIATOR) == CAR_RADIATOR_BROKEN",
      "BREAKABLE_CAR_ITEM_RADIATOR) != 0"),
    M("fx-radiator-code", "effect(c, CARFX_DAM_RADIATOR,",
      "effect(c, CARFX_DAM_ENGINE,"),
    M("fx-engine-code", "effect(c, CARFX_DAM_ENGINE, 1.0f",
      "effect(c, CARFX_DAM_RADIATOR, 1.0f"),
    M("fx-damage-no-test", "    if (c->pCarDamage != NULL) {", "    {"),
    M("fx-damage-no-else", "        else if (item_level(",
      "        if (item_level("),
    M("fx-radiator-no-damage-test",
      NL + "                 && CAR_RADIATOR_STEAM_DAMAGE" + NL
      + "                    < bodydamage_get_visible_total_damage("
      "&d->TheBodyDamage))", ")"),
    M("fx-smoke-by-steam", "        if (CAR_ENGINE_SMOKE_DAMAGE" + NL,
      "        if (CAR_RADIATOR_STEAM_DAMAGE" + NL),
    # -- the nitro, the flat tires
    M("fx-nitro-any-player",
      "        if (c->pPlayer != NULL && c->TheMovementMode == PHYSICS_MOVEMENT)",
      "        if (c->TheMovementMode == PHYSICS_MOVEMENT)"),
    M("fx-nitro-any-mode",
      "        if (c->pPlayer != NULL && c->TheMovementMode == PHYSICS_MOVEMENT)",
      "        if (c->pPlayer != NULL)"),
    M("fx-nitro-is-one", "->pEngine->NitroFlag" + NL
      + "                     != 0;", "->pEngine->NitroFlag" + NL
      + "                     == 1;"),
    M("fx-nitro-flag-only", "if (c->NitroEffectFlag != 0 || engine != 0)",
      "if (c->NitroEffectFlag != 0)"),
    M("fx-nitro-engine-only", "if (c->NitroEffectFlag != 0 || engine != 0)",
      "if (engine != 0)"),
    M("fx-flat-by-bits", "    if ((int8_t)c->NumBlownTires != 0) {",
      "    if (c->BlownTireBits != 0) {"),
    M("fx-flat-three", "        for (i = 0; i < 4; i++) {" + NL
      + "            if (st->WheelTouchingGround[i] == 0)",
      "        for (i = 0; i < 3; i++) {" + NL
      + "            if (st->WheelTouchingGround[i] == 0)"),
    M("fx-flat-up-counts", "        for (i = 0; i < 4; i++) {" + NL
      + "            if (st->WheelTouchingGround[i] == 0)" + NL
      + "                continue;" + NL,
      "        for (i = 0; i < 4; i++) {" + NL),
    M("fx-flat-any-tire",
      "            if ((((int8_t)c->BlownTireBits >> i) & 1) == 0)" + NL
      + "                continue;" + NL, ""),
    M("fx-flat-code", "effect(c, CARFX_DRIVE_ON_FLAT_TIRE,",
      "effect(c, CARFX_BLOWN_TIRE,"),
    M("fx-flat-unclamped", "clamp01((st->VelocityMagnitude",
      "((st->VelocityMagnitude"),
    M("fx-flat-no-floor",
      NL + "                            - CAR_FLAT_TIRE_MIN_MPH)", ")"),
    M("fx-flat-where", "CAR_WHEEL_WHERE0 + i * CAR_WHEEL_WHERE_STEP, NULL);",
      "CAR_WHEEL_WHERE0, NULL);"),
]

EQUIVALENT = {
    "fx-spew-pad-ignored":
        "bMulMatrixVec3 forces the vector's w to 1 before the multiply, as "
        "the image's bMulMatrix does through the stack, so the pad the "
        "port writes -- and the word the image leaves unwritten -- is "
        "never read.",
    "fx-spew-by-mag":
        "The spew's scale is (slip.x - min) / (max - min), at most 0 when "
        "slip.x is at most the minimum, and only a scale above 0 goes off. "
        "The slip's length is never below its x, so the gate only differs "
        "where the scale is already 0.",
    "fx-spew-min-le":
        "At slip.x equal to the minimum the scale is exactly 0, and only a "
        "scale above 0 goes off, so the gate's < and <= agree.",
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
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if text.count(probe) != 1:
            missing.append(name)
            print("  %-36s PATTERN %s" % (
                name, "NOT FOUND" if not text.count(probe) else "NOT UNIQUE"))
            continue
        new = text.replace(probe, repl, 1)
        try:
            hostbuild.write_source(path, new)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = build_harness(tmp)
                except SystemExit:
                    print("  %-36s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, scp, out)
                if rc == pcc.HARNESS_HUNG:
                    print("  %-36s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-36s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-36s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-36s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-36s SURVIVED" % name)
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
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
