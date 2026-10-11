#!/usr/bin/env python3
"""Cross-check 3DS Files/source/playercop.c, Be A Cop's player cop (12m-1)
and the manager's BeACopThink (12m-2), against the retail image,
SLES_507.31, run in mipsemu.

**The model** is retail's own code: tPlayerCop's Think (0x0022d5c8),
ChangeChaseTarget (0x0022d700) and SelectCarToChase (0x0022d898),
tCopManager::BeACopToggleSirenAndLights (0x002289b8) and
tCopManager::BeACopThink (0x00227f30). The harness
(tools/src/playercop_test.c) runs the port and prints the same lines.

**The stubs**, logged and answered from the script on both sides:
Player::IsNisPlaying (each car's player's flag), Car::IsBlinking and
Car::IsCarInFront (each car's flags), tCopManager::RequestPursuit,
tPursuit's change of target (0x0022cb30, pursuitspeech_check.py's),
GetInGameSample (a sample or none), bSample::Play and the helicopter's
release (0x0022a310, pursuit_check.py's). For BeACopThink:
PlayBustedSpeech, FindLandmark (a landmark or none), the dispatch's Be On
Lookout, Race::FinishCar by car, the Be A Cop finish speech (0x00207648),
the manager's pursuit delete (0x00224560), CarDamage's wreck (0x001b5bc8)
and the controllers' ForceBoost, through a table. Timer::SetTime and
tCop::SetPursuit run as they are (the port's harness stores the pursuit).
The World's CopCarPos and car table, the cars' places, indexes, drivers'
types, racing cars, lights, siren and boost overrides, the manager's
pullovers, player cop, car damage, difficulty and Be A Cop fields, the
race's stage, clock and lap time, the race parameters' players, point to
point and laps, the pursuits and the helicopter's salvos are memory both
sides read.

**Compared** are the stubs' logs, the pick SelectCarToChase answers and,
after each call, the cop's two picks and their timers, and its car's
lights word and siren; after BeACopThink, the clock, the two said-once
flags, the cops' pursuits and every car's two boost overrides.

    python tools/playercop_check.py
    python tools/playercop_check.py --mutate [--only a,b]
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

NL = chr(10)

HARNESS = "tools/src/playercop_test.c"
PC = "3DS Files/source/playercop.c"
SOURCES = [HARNESS, PC, "3DS Files/source/vtable.c",
           "3DS Files/source/timer.c"]
HARNESS_TIMEOUT = 60

GP = retail_model.RETAIL_GP
G_WORLD = GP - 22120                    # pCurrentWorld
G_COPMGR = GP - 15620                   # pCopManager
G_ELAPSED = GP - 19560                  # WorldTimeElapsed
G_RACE = GP - 22272                     # pCurrentRace
G_SPEECH = GP - 15624                   # the cop speech manager
RP = 0x0031a898                         # TheRaceParameters

F = {"think": 0x0022d5c8, "change": 0x0022d700, "select": 0x0022d898,
     "toggle": 0x002289b8, "beacop": 0x00227f30}

S_NIS = 0x00176520
S_BLINK = 0x00133130
S_FRONT = 0x00133898
S_REQUEST = 0x00225078
S_RETARGET = 0x0022cb30
S_SAMPLE = 0x001ae280
S_PLAY = 0x00274080
S_RELEASE = 0x0022a310
S_BUSTED = 0x002077b8
S_LANDMARK = 0x00228a58
S_LOOKOUT = 0x0020b7a8
S_FINISH = 0x00149250
S_COPSPEECH = 0x00207648
S_DELETE = 0x00224560
S_WRECK = 0x001b5bc8

NCARS, NCOPS, NP = 8, 3, 3
MGR_SIZE, CAR_SIZE, RC_SIZE, PURSUIT_SIZE, CHOPPER_SIZE = \
    10516, 2304, 192, 1600, 848
W_COPCARPOS, W_TABLE = 36, 44
C_PLAYER, C_RC, C_POS, C_LIGHTS, C_SIREN = 24, 28, 96, 2056, 2104
RC_FINISH = 18
M_PCI, M_COPS, M_PULL = 12, 16, 88
C_INDEX, C_DRIVER, C_CTL, C_DAMAGE = 8, 20, 40, 2120
C_TRACTION, C_DBOOST = 1116, 1120
D_TYPE = 8
M_DAMAGE, M_DIFF, M_TIME, M_SAID, M_BUSTED, M_ARRESTS = \
    10420, 10476, 10480, 10484, 10488, 10496
R_TIME, R_TATT = 16, 1712
RP_P2P, RP_LAPS, RP_PLAYERS = 40, 44, 48
L_TYPE = 52
VT_BOOST, BOOST_DELTA = 96, 16
U_CHASED, U_CHOPPER = 16, 24
H_SALVOS = 828


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def Fx(f):
    return "0x%08x" % fbits(f)


# ================================================================== model

class Model(object):
    def __init__(self):
        e = self.e = retail_model.RetailEmu(ieee=True)
        self.out = []
        self.names = {}

        def block(n, nm):
            p = e.alloc(n, align=16)
            e.write(p, bytes(n))
            if nm:
                self.names[p] = nm
            return p
        self.m = block(MGR_SIZE, "M")
        e.put32(G_COPMGR, self.m)
        e.put32(self.m + M_PCI, M32)
        self.world = block(128, "W")
        e.put32(G_WORLD, self.world)
        self.race = block(1728, "R")
        e.put32(G_RACE, self.race)
        self.tatt = block(16, "T")
        e.put32(self.race + R_TATT, self.tatt)
        self.speech = block(16, "SM")
        e.put32(G_SPEECH, self.speech)
        self.landmark = block(64, "L")
        self.land_on = 0
        self.boost_fn = e.alloc(16, align=16)
        self.vt = block(128, None)
        struct.pack_into("<hhI", e.mem, self.vt + VT_BOOST, BOOST_DELTA, 0,
                         self.boost_fn)
        e.stub(self.boost_fn, self.s_boost)
        self.cars = [block(CAR_SIZE, "A%d" % k) for k in range(NCARS)]
        self.rcs = [block(RC_SIZE, None) for k in range(NCARS)]
        self.players = [block(16, "P%d" % k) for k in range(NCARS)]
        self.cops = [block(64, "C%d" % k) for k in range(NCOPS)]
        self.ps = [block(PURSUIT_SIZE, "U%d" % k) for k in range(NP)]
        self.chopper = block(CHOPPER_SIZE, "H")
        self.sample = block(16, "S")
        for c, r in zip(self.cars, self.rcs):
            e.put32(c + C_RC, r)
        self.drivers = [block(32, None) for k in range(NCARS)]
        self.ctls = [block(64, "K%d" % k) for k in range(NCARS)]
        self.damages = [block(16, "D%d" % k) for k in range(NCARS)]
        for k in range(NCARS):
            e.put32(self.cars[k] + C_DRIVER, self.drivers[k])
            e.put32(self.cars[k] + C_CTL, self.ctls[k])
            e.put32(self.ctls[k] + 8, self.vt)
            self.names[self.ctls[k] + BOOST_DELTA] = "K%d+%d" % (k,
                                                                 BOOST_DELTA)
        self.nis = [0] * NCARS
        self.blink = [0] * NCARS
        self.front = [0] * NCARS
        self.sample_on = 1
        self.request = 1
        for addr, fn in ((S_NIS, self.s_nis), (S_BLINK, self.s_blink),
                         (S_FRONT, self.s_front),
                         (S_REQUEST, self.s_request),
                         (S_RETARGET, self.s_retarget),
                         (S_SAMPLE, self.s_sample), (S_PLAY, self.s_play),
                         (S_RELEASE, self.s_release),
                         (S_BUSTED, self.s_busted),
                         (S_LANDMARK, self.s_landmark),
                         (S_LOOKOUT, self.s_lookout),
                         (S_FINISH, self.s_finish),
                         (S_COPSPEECH, self.s_copspeech),
                         (S_DELETE, self.s_delete),
                         (S_WRECK, self.s_wreck)):
            e.stub(addr, fn)

    def emit(self, line):
        self.out.append(line)

    def sym(self, v):
        v &= M32
        if v == 0:
            return "0"
        return self.names.get(v, "?")

    def car_index(self, v):
        v &= M32
        return self.cars.index(v) if v in self.cars else -1

    # ---- stubs

    def s_nis(self, em):
        p = em.reg[4] & M32
        r = self.nis[self.players.index(p)] if p in self.players else 0
        self.emit("  nis %s -> %d" % (self.sym(p), r))
        return r

    def s_blink(self, em):
        k = self.car_index(em.reg[4])
        r = self.blink[k] if k >= 0 else 0
        self.emit("  blink %s -> %d" % (self.sym(em.reg[4]), r))
        return r

    def s_front(self, em):
        k = self.car_index(em.reg[5])
        r = self.front[k] if k >= 0 else 0
        self.emit("  front %s %s %d -> %d" % (
            self.sym(em.reg[4]), self.sym(em.reg[5]), em.reg[6] & 0xffff, r))
        return r

    def s_request(self, em):
        self.emit("  request %s %s %s -> %d" % (
            self.sym(em.reg[4]), self.sym(em.reg[5]), self.sym(em.reg[6]),
            self.request))
        return self.request

    def s_retarget(self, em):
        self.emit("  retarget %s %s" % (self.sym(em.reg[4]),
                                        self.sym(em.reg[5])))

    def s_sample(self, em):
        a = em.reg[4] & M32
        name = bytearray()
        while self.e.mem[a] and len(name) < 64:
            name.append(self.e.mem[a])
            a += 1
        r = self.sample if self.sample_on else 0
        self.emit("  sample %s -> %s" % (name.decode("latin-1"),
                                         self.sym(r)))
        return r

    def s_play(self, em):
        self.emit("  play %s %08x %08x %08x" % (
            self.sym(em.reg[4]), em.fpr[12] & M32, em.fpr[13] & M32,
            em.fpr[14] & M32))
        return 0

    def s_release(self, em):
        self.emit("  release %s" % self.sym(em.reg[4]))

    def s_busted(self, em):
        self.emit("  busted")

    def s_copspeech(self, em):
        self.emit("  copspeech %d %d %d %d" % tuple(
            s32(em.reg[r]) for r in (4, 5, 6, 7)))

    def s_landmark(self, em):
        a = em.reg[4] & M32
        r = self.landmark if self.land_on else 0
        self.emit("  landmark %08x %08x -> %s" % (
            self.e.u32(a), self.e.u32(a + 4), self.sym(r)))
        return r

    def s_lookout(self, em):
        self.emit("  lookout %s %d" % (self.sym(em.reg[4]), s32(em.reg[5])))

    def s_finish(self, em):
        self.emit("  finish %s %s %d %d %d" % (
            self.sym(em.reg[4]), self.sym(em.reg[5]), s32(em.reg[6]),
            s32(em.reg[7]), s32(em.reg[8])))

    def s_delete(self, em):
        self.emit("  delete %s %s" % (self.sym(em.reg[4]),
                                      self.sym(em.reg[5])))

    def s_wreck(self, em):
        self.emit("  wreck %s" % self.sym(em.reg[4]))

    def s_boost(self, em):
        self.emit("  boost %s %08x" % (self.sym(em.reg[4]),
                                       em.fpr[12] & M32))

    # ---- dumps

    def cdump(self, j):
        e = self.e
        c = self.cops[j]
        car = e.u32(c + 4)
        self.emit("C%d picks %d %d timers %08x %08x lights %08x siren %d"
                  % (j, s32(e.u32(c + 32)), s32(e.u32(c + 36)),
                     e.u32(c + 40), e.u32(c + 44),
                     e.u32(car + C_LIGHTS) if car else 0,
                     s32(e.u32(car + C_SIREN)) if car else 0))

    def bdump(self):
        e = self.e
        m = self.m
        self.emit("beacop time %08x said %d busted %d pursuits %s %s %s" % (
            e.u32(m + M_TIME), s32(e.u32(m + M_SAID)),
            s32(e.u32(m + M_BUSTED)),
            *[self.sym(e.u32(c)) for c in self.cops]))
        for k, c in enumerate(self.cars):
            self.emit("A%d traction %08x damage %08x" % (
                k, e.u32(c + C_TRACTION), e.u32(c + C_DBOOST)))

    # ---- ops

    def run(self, a):
        e = self.e
        o = a[0]
        v = lambda j: int(a[j], 0) & M32        # noqa: E731
        if o == "car":
            # car|k|player|nis|x|y|z|finish|blink|front|lights|siren
            k = int(a[1])
            c = self.cars[k]
            e.put32(c + C_PLAYER, self.players[k] if v(2) else 0)
            self.nis[k] = v(3)
            for j in range(3):
                e.put32(c + C_POS + 4 * j, v(4 + j))
            e.write(self.rcs[k] + RC_FINISH, struct.pack("<H", v(7) & 0xffff))
            self.blink[k] = v(8)
            self.front[k] = v(9)
            e.put32(c + C_LIGHTS, v(10))
            e.put32(c + C_SIREN, v(11))
        elif o == "world":
            n = int(a[1])
            e.put32(self.world + W_COPCARPOS, n & M32)
            for j, s in enumerate(a[2:]):
                e.put32(self.world + W_TABLE + 4 * j,
                        self.cars[int(s)] if int(s) >= 0 else 0)
        elif o == "time":
            e.put32(G_ELAPSED, v(1))
        elif o == "pull":
            e.put32(self.m + M_PULL + 28 * int(a[1]) + 12, v(2))
        elif o == "cop":
            # cop|j|car|pursuit|pick0|pick1|timer0|timer1
            c = self.cops[int(a[1])]
            u = int(a[3])
            e.put32(c + 4, self.cars[int(a[2])])
            e.put32(c + 0, self.ps[u] if u >= 0 else 0)
            for j in range(4):
                e.put32(c + 32 + 4 * j, v(4 + j))
        elif o == "cpur":
            u = int(a[2])
            e.put32(self.cops[int(a[1])], self.ps[u] if u >= 0 else 0)
        elif o == "pur":
            # pur|k|chased|chopper|salvos
            p = self.ps[int(a[1])]
            ch = int(a[2])
            e.put32(p + U_CHASED, self.cars[ch] if ch >= 0 else 0)
            e.put32(p + U_CHOPPER, self.chopper if v(3) else 0)
            e.put32(self.chopper + H_SALVOS, v(4))
        elif o == "mgr":
            j = int(a[1])
            e.put32(self.m + M_PCI, M32 if j < 0 else 4)
            e.put32(self.m + M_COPS + 16, self.cops[j] if j >= 0 else 0)
        elif o == "race":
            e.put32(self.race, v(1))
        elif o == "cidx":
            # cidx|k|index|drivertype|damage|racingcar
            k = int(a[1])
            c = self.cars[k]
            e.write(c + C_INDEX, struct.pack("<H", v(2) & 0xffff))
            e.put32(self.drivers[k] + D_TYPE, v(3))
            e.put32(c + C_DAMAGE, self.damages[k] if v(4) else 0)
            e.put32(c + C_RC, self.rcs[k] if v(5) else 0)
        elif o == "boosts":
            c = self.cars[int(a[1])]
            e.put32(c + C_TRACTION, v(2))
            e.put32(c + C_DBOOST, v(3))
        elif o == "dmg":
            e.put32(self.m + M_DAMAGE + 4 * int(a[1]), v(2))
        elif o == "bac":
            for j, off in enumerate((M_DIFF, M_TIME, M_SAID, M_BUSTED,
                                     M_ARRESTS)):
                e.put32(self.m + off, v(1 + j))
        elif o == "rp":
            e.put32(RP + RP_PLAYERS, v(1))
            e.put32(RP + RP_P2P, v(2))
            e.put32(RP + RP_LAPS, v(3))
        elif o == "rtime":
            e.put32(self.race + R_TIME, v(1))
            e.put32(self.tatt, v(2))
        elif o == "land":
            self.land_on = v(1)
            e.put32(self.landmark + L_TYPE, v(2))
        elif o == "sample":
            self.sample_on = v(1)
        elif o == "request":
            self.request = v(1)
        elif o in F:
            if o == "beacop":
                e.call(F[o], self.m, limit=400000)
                self.bdump()
                return
            if o == "toggle":
                e.call(F[o], self.m, limit=200000)
                self.emit("toggle")
                for j in range(NCOPS):
                    self.cdump(j)
                return
            j = int(a[1])
            r = e.call(F[o], self.cops[j], limit=200000)
            if o == "select":
                self.emit("select C%d -> %s" % (j, self.sym(r)))
            self.emit("%s C%d" % (o, j))
            self.cdump(j)
        else:
            raise ValueError(o)


def model(lines):
    m = Model()
    for ln in lines:
        m.run(ln.split("|"))
    return m.out


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    return mutpar.model_cached(sc, model, cut=MUTATIONS_HEADER)


# ================================================================ the script

def car(k, player=1, nis=0, x=0.0, y=0.0, z=0.0, finish=0, blink=0,
        front=1, lights=0, siren=0):
    return "car|%d|%d|%d|%s|%s|%s|%d|%d|%d|%d|%d" % (
        k, player, nis, Fx(x), Fx(y), Fx(z), finish, blink, front, lights,
        siren)


def cop(j, carno=0, pursuit=-1, p0=-1, p1=-1, t0=0.0, t1=0.0):
    return "cop|%d|%d|%d|%d|%d|%s|%s" % (j, carno, pursuit, p0, p1,
                                         Fx(t0), Fx(t1))


def world(n, table=None):
    table = list(range(NCARS)) if table is None else table
    return "world|%d|%s" % (n, "|".join(str(t) for t in table))


def cidx(k, index=None, dtype=None, damage=0, rc=1):
    index = k if index is None else index
    dtype = (1 if k == 0 else 2) if dtype is None else dtype
    return "cidx|%d|%d|%d|%d|%d" % (k, index, dtype, damage, rc)


def bac(difficulty=0, t=100.0, said=0, busted=0, arrests=0):
    return "bac|%d|%s|%d|%d|%d" % (difficulty, Fx(t), said, busted, arrests)


def rtime(packed=4000, lap=0.0):
    return "rtime|%d|%s" % (packed, Fx(lap))


def base():
    out = [world(NCARS), "time|%s" % Fx(1.0 / 30), "race|4", "mgr|0",
           "sample|1", "request|1", "rp|1|0|3", bac(), rtime(0),
           "land|0|0"]
    for k in range(NCARS):
        out.append(car(k, player=int(k == 0), x=10.0 * k, y=3.0 * k))
        out.append("pull|%d|0" % k)
        out.append(cidx(k))
        out.append("boosts|%d|0|0" % k)
    for i in range(14):
        out.append("dmg|%d|0" % i)
    for j in range(NP):
        out.append("pur|%d|1|0|0" % j)
    out.append(cop(0))
    out.append(cop(1, carno=1))
    out.append(cop(2, carno=2))
    return out


def select_cases():
    out = []
    # Each distance and height boundary, ahead and not.
    for d in (0.0, 5.0, 19.99, 20.0, 20.01, 100.0, 174.99, 175.0, 175.01,
              400.0):
        for dz in (0.0, -19.99, 19.99, 20.0, -20.0, 25.0):
            for front in (0, 1):
                out += base() + [car(1, player=0, x=d * 0.6, y=d * 0.8, z=dz,
                                     front=front),
                                 world(2), "select|0"]
    # On the x axis the distance is the x itself: the floats either side
    # of 20 and 175.
    for d in (19.999998092651367, 20.0, 20.000001907348633,
              174.99998474121094, 175.0, 175.00001525878906):
        for front in (0, 1):
            out += base() + [car(1, player=0, x=d, y=0.0, front=front),
                             world(2), "select|0"]
    # The car skips: its own, blinking, finished (the short's sign).
    for finish in (0, 1, -1, 0x10000, 0x8000):
        for blink in (0, 1):
            out += base() + [car(2, player=0, x=30.0, finish=finish,
                                 blink=blink), world(3, [0, 2, 1]),
                             "select|0"]
    out += base() + [world(1), "select|0"]
    out += base() + [world(0), "select|0"]
    out += base() + [world(3, [1, 0, 0]), "select|0"]
    # Equal scores: the first wins; the previous picks' 0 and 5.
    for p0 in (-1, 1, 2, 3):
        for p1 in (-1, 1, 2, 3):
            out += base() + [car(1, player=0, x=50.0),
                             car(2, player=0, x=-50.0),
                             car(3, player=0, y=50.0, front=0),
                             cop(0, p0=p0, p1=p1, t0=3.0, t1=1.5),
                             world(4), "select|0", "select|0", "select|0"]
    # Every car in range: the rotation over many picks.
    for n in (2, 4, 8):
        out += base()
        for k in range(1, NCARS):
            out.append(car(k, player=0, x=12.0 * k, y=-7.0 * k + 3.0,
                           z=0.5 * k, front=k % 3 != 0))
        out += [world(n)] + ["select|0"] * 10
    return out


def think_cases():
    out = []
    for player in (0, 1):
        for nis in (0, 1):
            for t0, t1 in ((3.0, 0.5), (0.0, 0.0), (1.0 / 30, 0.02),
                           (-1.0, 5.0)):
                for dt in (0.0, 1.0 / 30, 0.5, -0.25):
                    out += base() + [car(0, player=player, nis=nis),
                                     cop(0, p0=2, p1=3, t0=t0, t1=t1),
                                     "time|%s" % Fx(dt), "think|0"]
    # The lights and the siren: a pursuit, a pullover, neither.
    for pursuit in (-1, 0):
        for pull in (-1, 0, 3, 7):
            for n in (0, 4, 8):
                for lights, siren in ((0, 0), (1, 3), (0x101, 4)):
                    out += base() + [car(0, lights=lights, siren=siren),
                                     cop(0, pursuit=pursuit), world(n)]
                    if pull >= 0:
                        out.append("pull|%d|1" % pull)
                    out.append("think|0")
    # The helicopter's salvos.
    for chop in (0, 1):
        for salvos in (0, 3, 4, 5, -1, 0x7fffffff):
            out += base() + ["pur|0|1|%d|%d" % (chop, salvos & M32),
                             cop(0, pursuit=0), "think|0"]
    return out


def change_cases():
    out = []
    for player in (0, 1):
        for nis in (0, 1):
            out += base() + [car(0, player=player, nis=nis),
                             car(1, player=0, x=40.0), "change|0"]
    # A pick: no pursuit, a pursuit of it, of another car.
    for chased in (-1, 1, 2):
        for sample in (0, 1):
            for request in (0, 1):
                out += base() + [car(1, player=0, x=40.0),
                                 "pur|0|%d|0|0" % chased, cop(0, pursuit=0),
                                 "sample|%d" % sample,
                                 "request|%d" % request, "change|0"]
        out += base() + [car(1, player=0, x=40.0), cop(0), "change|0"]
    # No pick: the lights' word, with and without a pursuit.
    for lights in (0, 1, 2, 0x100, 0x1000000, -1):
        for pursuit in (-1, 0):
            out += base() + [world(1), car(0, lights=lights & M32),
                             cop(0, pursuit=pursuit), "change|0",
                             "change|0"]
    return out


def toggle_cases():
    out = []
    for stage in (0, 1, 3, 4, 5, -1):
        for j in (-1, 0, 1):
            out += base() + ["race|%d" % (stage & M32), "mgr|%d" % j,
                             car(1, player=1), car(2, player=0, x=30.0),
                             "toggle"]
    return out


NAN = float("nan")


def beacop_cases():
    out = []
    # The fly-by and the pre-race: the stage, the players, the two flags,
    # the landmark, the clock from the lap; the race clock still at 0.
    for players in (1, 2, 0, 3):
        for stage in (0, 1, 2, 3, 4, 5):
            for said, busted in ((0, 0), (1, 0), (0, 1), (1, 1)):
                out += base() + ["rp|%d|0|3" % players, "race|%d" % stage,
                                 bac(t=42.0, said=said, busted=busted),
                                 rtime(0, 61.25),
                                 car(0, x=-229.6, y=732.5, z=-58.1),
                                 "land|1|7", "beacop"]
    for on, kind in ((0, 0), (0, 9), (1, 0), (1, 3), (1, -1)):
        out += base() + ["race|2", "land|%d|%d" % (on, kind),
                         car(0, x=12.5, y=-7.25), "beacop"]
    for p2p in (0, 1, 2, -1):
        for laps in (0, 1, 3, 8, -1, 0x7fffffff):
            for lap in (0.0, 61.25, 133.33333, -5.0, 3.0e38):
                out += base() + ["race|2", "rp|2|%d|%d" % (p2p, laps),
                                 rtime(0, lap), "beacop"]
    # The race clock: above 0 signed, or not.
    for packed in (0, 1, 2, 3, 4, 4000, 0x7fffffff, 0x80000000,
                   0xffffffff, 0xfffff000):
        for stage in (2, 4):
            out += base() + ["race|%d" % stage, bac(t=10.0), rtime(packed),
                             "beacop"]
    # The clock: the cop's racing car, finished or not, its player, the
    # pullovers (its own slot does not stop it), the time left.
    for rc in (0, 1):
        for finish in (0, 1, 2, 0xffff):
            for player in (0, 1):
                out += base() + [rtime(), cidx(0, rc=rc),
                                 car(0, player=player, finish=finish),
                                 bac(t=10.0), "beacop"]
    for index in (0, 5, 7, 9, 13):
        for pulls in ((), (0,), (5,), (7,), (0, 5), (3, 7), (index,)):
            out += base() + [rtime(), cidx(0, index=index), bac(t=10.0)]
            out += ["pull|%d|1" % k for k in pulls if k < NCARS]
            out.append("beacop")
    for t, dt in ((10.0, 1.0 / 30), (1.0 / 30, 1.0 / 30), (0.0, 0.0),
                  (0.0333, 1.0 / 30), (1e-7, 1.0 / 30), (-1.0, 0.0),
                  (5.0, 5.0), (5.0, 5.0000005), (5.0, 4.9999995),
                  (NAN, 1.0 / 30), (1.0, -1.0), (0.5, 0.25)):
        out += base() + [rtime(), bac(t=t, arrests=2),
                         "time|%s" % Fx(dt), "beacop", "beacop"]
    # The time-out: the chase deleted and let go, one or two players, the
    # speeder (CarTable[1]) finished or not, the arrests.
    for pursuit in (-1, 0):
        for players in (1, 2):
            for finish1 in (0, 1, 5, 0xffff):
                for arrests in (0, 3):
                    out += base() + [rtime(), "rp|%d|0|3" % players,
                                     cop(0, pursuit=pursuit),
                                     car(1, player=0, x=10.0, y=3.0,
                                         finish=finish1),
                                     bac(t=0.01, arrests=arrests), "beacop"]
    for table in ([3, 0, 1, 2, 4, 5, 6, 7], [0, 6, 1, 2, 3, 4, 5, 7]):
        out += base() + [rtime(), "rp|2|0|3", world(NCARS, table),
                         bac(t=0.01), "beacop"]
    # The wrecks: the damage at and about 1, each driver type, a player,
    # a CarDamage, the difficulty, the cop's own car.
    for dmg in (0.0, 0.99999994, 1.0, 1.0000001, 1.5, 80.0, 100.0, NAN,
                -5.0, float("inf")):
        for dtype in (0, 1, 2, 3, 4, 5):
            for player in (0, 1):
                out += base() + [rtime(), cidx(3, dtype=dtype),
                                 car(3, player=player, x=30.0, y=9.0),
                                 "dmg|3|%s" % Fx(dmg), "beacop"]
    for diff in (0, 1, 2):
        for damage in (0, 1):
            out += base() + [rtime(), bac(difficulty=diff),
                             cidx(2, damage=damage), cidx(5, dtype=1),
                             car(5, player=1, x=50.0, y=15.0),
                             cidx(6, dtype=4, damage=damage),
                             "dmg|2|%s" % Fx(2.0), "dmg|5|%s" % Fx(1.0),
                             "dmg|6|%s" % Fx(3.0), "beacop"]
    for dtype in (1, 2, 4):
        out += base() + [rtime(), cidx(0, dtype=dtype),
                         "dmg|0|%s" % Fx(2.0), "beacop"]
    # CarIndex apart from the table's place; CopCarPos short of a car.
    for n in (0, 1, 3, 4, 8):
        out += base() + [rtime(), cidx(3, index=11), cidx(4, index=3),
                         "dmg|3|%s" % Fx(4.0), "dmg|11|%s" % Fx(1.25),
                         world(n), "beacop"]
    # Two players: the cop (CarTable[0]) and the speeder (CarTable[1]),
    # each finished or not.
    for f0 in (0, 1, 5, 0xffff):
        for f1 in (0, 1, 5, 0xffff):
            for players in (1, 2):
                out += base() + [rtime(), "rp|%d|0|3" % players,
                                 car(0, finish=f0),
                                 car(1, player=1, x=10.0, y=3.0, finish=f1),
                                 bac(arrests=4), "beacop"]
    out += base() + [rtime(), "rp|2|0|3", world(NCARS, [2, 3, 0, 1, 4, 5,
                                                        6, 7]),
                     car(3, player=1, x=30.0, y=9.0, finish=1), "beacop"]
    return out


def beacop_runs(rng):
    """A Be A Cop race over time: the stages go by, the clock runs down,
    cars are wrecked and finish."""
    out = base() + [rtime(0, 70.0), "race|1", bac(t=0.0)]
    stage = 1
    packed = 0
    for _ in range(3000):
        r = rng.random()
        if r < 0.04 and stage < 4:
            stage += 1
            out.append("race|%d" % stage)
        elif r < 0.10:
            packed += rng.choice((0, 133, 4000))
            out.append(rtime(packed, rng.choice((70.0, 70.0, 45.5))))
        elif r < 0.14:
            out.append("rp|%d|%d|%d" % (rng.choice((1, 1, 2)),
                                        rng.randrange(2), rng.randrange(5)))
        elif r < 0.20:
            out.append("dmg|%d|%s" % (rng.randrange(14), Fx(rng.choice((
                0.0, 0.5, 1.0, 2.5, rng.uniform(0.0, 90.0))))))
        elif r < 0.24:
            k = rng.randrange(NCARS)
            out.append(cidx(k, index=rng.randrange(14),
                            dtype=rng.randrange(6),
                            damage=int(rng.random() < 0.3)))
        elif r < 0.30:
            k = rng.randrange(NCARS)
            out.append(car(k, player=int(rng.random() < 0.3),
                           x=rng.uniform(-200, 200), y=rng.uniform(-200, 200),
                           finish=rng.choice((0, 0, 0, 1, 5))))
        elif r < 0.33:
            out.append("pull|%d|%d" % (rng.randrange(NCARS),
                                       int(rng.random() < 0.3)))
        elif r < 0.36:
            out.append("time|%s" % Fx(rng.choice((1.0 / 30, 1.0 / 30, 0.0,
                                                  0.5, 2.0))))
        elif r < 0.39:
            out.append(bac(difficulty=rng.randrange(3),
                           t=rng.choice((0.5, 3.0, 30.0)),
                           said=rng.randrange(2), busted=rng.randrange(2),
                           arrests=rng.randrange(5)))
        elif r < 0.41:
            out.append("cpur|0|%d" % rng.choice((-1, 0)))
        elif r < 0.43:
            out.append("land|%d|%d" % (rng.randrange(2), rng.randrange(12)))
        else:
            out.append("beacop")
    return out


def random_runs(rng):
    """A race over time: the cars move, the horn picks and the cop thinks,
    with the picks and timers carried on."""
    out = base()
    out += [car(0, player=1, x=0.0, y=0.0)]
    for _ in range(4000):
        r = rng.random()
        if r < 0.25:
            k = rng.randrange(1, NCARS)
            out.append(car(k, player=int(rng.random() < 0.2),
                           nis=int(rng.random() < 0.1),
                           x=rng.uniform(-220, 220), y=rng.uniform(-220, 220),
                           z=rng.choice((0.0, 0.0, rng.uniform(-30, 30))),
                           finish=int(rng.random() < 0.1),
                           blink=int(rng.random() < 0.1),
                           front=int(rng.random() < 0.6),
                           lights=rng.choice((0, 0, 1, 2)),
                           siren=rng.randrange(5)))
        elif r < 0.30:
            out.append(car(0, player=int(rng.random() < 0.9),
                           nis=int(rng.random() < 0.1),
                           x=rng.uniform(-50, 50), y=rng.uniform(-50, 50),
                           lights=rng.choice((0, 1, 2)),
                           siren=rng.randrange(3)))
        elif r < 0.33:
            out.append(world(rng.randrange(NCARS + 1)))
        elif r < 0.37:
            out.append("time|%s" % Fx(rng.choice((1.0 / 30, 1.0 / 30, 0.0,
                                                  0.5, 1.7))))
        elif r < 0.40:
            out.append("pull|%d|%d" % (rng.randrange(NCARS),
                                       int(rng.random() < 0.3)))
        elif r < 0.43:
            out.append("pur|0|%d|%d|%d" % (rng.randrange(-1, NCARS),
                                           rng.randrange(2),
                                           rng.randrange(7)))
        elif r < 0.445:
            out.append("cpur|0|%d" % rng.choice((-1, -1, 0)))
        elif r < 0.46:
            out.append("sample|%d" % int(rng.random() < 0.8))
        elif r < 0.48:
            out.append("race|%d" % rng.choice((4, 4, 4, 3)))
        elif r < 0.62:
            out.append("think|0")
        elif r < 0.80:
            out.append("change|0")
        elif r < 0.90:
            out.append("toggle")
        else:
            out.append("select|0")
    return out


def script():
    return (select_cases() + think_cases() + change_cases()
            + toggle_cases() + random_runs(random.Random(0x12a1))
            + beacop_cases() + beacop_runs(random.Random(0x12a2)))


# ================================================================= running

def build_harness(tmp, name="playercop_test"):
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

P = PC

MUTATIONS = [
    # ---- Think
    ("th-player", P, "    if (car->pPlayer != NULL && !player_is_nis_playing"
     "(car->pPlayer))\n        for", "    if (!player_is_nis_playing"
     "(car->pPlayer))\n        for"),
    ("th-nis", P, "    if (car->pPlayer != NULL && !player_is_nis_playing"
     "(car->pPlayer))\n        for", "    if (car->pPlayer != NULL)\n"
     "        for"),
    ("th-one", P, "        for (i = 0; i < PICKS; i++) {",
     "        for (i = 0; i < 1; i++) {"),
    ("th-dt", P, "            c->fPrevSelectionTimer[i] -= WorldTimeElapsed;",
     "            c->fPrevSelectionTimer[i] -= WorldTimeElapsedFrame;"),
    ("th-le", P, "            if (c->fPrevSelectionTimer[i] <= 0.0f) {",
     "            if (c->fPrevSelectionTimer[i] < 0.0f) {"),
    ("th-zero", P, "                c->fPrevSelectionTimer[i] = 0.0f;\n", ""),
    ("th-drop", P, "                c->nPrevSelection[i] = -1;", ""),
    ("th-siren", P, "        car->TheSirenMode = SIREN_MODE_01;\n"
     "        set_cop_lights(car, 2);\n    } else",
     "        car->TheSirenMode = SIREN_MODE_02;\n"
     "        set_cop_lights(car, 2);\n    } else"),
    ("th-lights", P, "        car->TheSirenMode = SIREN_MODE_01;\n"
     "        set_cop_lights(car, 2);", "        car->TheSirenMode = "
     "SIREN_MODE_01;\n        set_cop_lights(car, 1);"),
    ("th-pull-siren", P, "        car->TheSirenMode = SIREN_MODE_NONE;",
     "        car->TheSirenMode = SIREN_MODE_01;"),
    ("th-pull-lights", P, "        car->TheSirenMode = SIREN_MODE_NONE;\n"
     "        set_cop_lights(car, 2);", "        car->TheSirenMode = "
     "SIREN_MODE_NONE;\n        set_cop_lights(car, 1);"),
    ("th-pull-off", P, "    } else if (any_pulled_over()) {",
     "    } else if (0) {"),
    ("th-pull-n", P, "    for (k = 0; k < n && k < COPMANAGER_NUM_PULLOVERS;"
     " k++)", "    for (k = 0; k < COPMANAGER_NUM_PULLOVERS; k++)"),
    ("th-pull-n1", P, "    for (k = 0; k < n && k < COPMANAGER_NUM_PULLOVERS;"
     " k++)", "    for (k = 0; k < n - 1 && k < COPMANAGER_NUM_PULLOVERS; "
     "k++)"),
    ("th-pull-field", P, "        if (pCopManager->CarPullovers[k].bActive "
     "!= 0)", "        if (pCopManager->CarPullovers[k].bPlayNIS != 0)"),
    ("th-salvos", P, "#define CHOPPER_SPENT       4",
     "#define CHOPPER_SPENT       5"),
    ("th-salvos-gt", P, "        && p->pChopper->TotalSalvos >= "
     "CHOPPER_SPENT)", "        && p->pChopper->TotalSalvos > "
     "CHOPPER_SPENT)"),
    ("th-release", P, "        tpursuit_release_chopper(p);\n}", "        ;\n}"),
    ("th-word", P, "    memset(car->_hole2025, 0, sizeof car->_hole2025);\n",
     ""),
    # ---- ChangeChaseTarget
    ("ch-player", P, "    if (car->pPlayer == NULL || player_is_nis_playing"
     "(car->pPlayer))\n        return;\n    pick",
     "    if (player_is_nis_playing(car->pPlayer))\n        return;\n    pick"),
    ("ch-nis", P, "    if (car->pPlayer == NULL || player_is_nis_playing"
     "(car->pPlayer))\n        return;\n    pick",
     "    if (car->pPlayer == NULL)\n        return;\n    pick"),
    ("ch-request", P, "(void)copmanager_request_pursuit(pCopManager, "
     "&c->Base, pick);", "(void)copmanager_request_pursuit(pCopManager, "
     "&c->Base, car);"),
    ("ch-same", P, "        if (p->pChasedCar != pick) {",
     "        if (p->pChasedCar == pick) {"),
    ("ch-retarget", P, "            tpursuit_change_chase_target(p, pick);",
     "            tpursuit_change_chase_target(p, car);"),
    ("ch-name", P, "\"BeACopRequestFailed\"", "\"BeACopRequestFail\""),
    ("ch-vol", P, "gSamplePlayFn(s, 1.0f, 0.0f, 0.0f);",
     "gSamplePlayFn(s, 0.5f, 0.0f, 0.0f);"),
    ("ch-null", P, "        if (s != NULL && gSamplePlayFn != NULL)",
     "        if (gSamplePlayFn != NULL)"),
    ("ch-chased", P, "    if (p != NULL)\n        return;\n    car =",
     "    if (0)\n        return;\n    car ="),
    ("ch-toggle", P, "    set_cop_lights(car, cop_lights_word(car) ? 0 : 1);",
     "    set_cop_lights(car, car->CopLights ? 0 : 1);"),
    ("ch-toggle-2", P, "    set_cop_lights(car, cop_lights_word(car) ? 0 : 1);",
     "    set_cop_lights(car, cop_lights_word(car) ? 0 : 2);"),
    ("ch-word-byte", P, "    return (p[0] | p[1] | p[2] | p[3]) != 0;",
     "    return (p[0] | p[1] | p[2]) != 0;"),
    # ---- SelectCarToChase
    ("se-mine", P, "        if (o == c->Base.pMyCar || car_is_blinking(o)",
     "        if (car_is_blinking(o)"),
    ("se-blink", P, "        if (o == c->Base.pMyCar || car_is_blinking(o)\n"
     "            || o->pRacingCar", "        if (o == c->Base.pMyCar\n"
     "            || o->pRacingCar"),
    ("se-finish", P, "            || o->pRacingCar->FinishReason != 0)",
     "            || o->pRacingCar->FinishReason > 0)"),
    ("se-finish-off", P, "            || o->pRacingCar->FinishReason != 0)",
     "            )"),
    ("se-dx", P, "        dx = mine->State.Position.x - o->State.Position.x;",
     "        dx = mine->State.Position.y - o->State.Position.x;"),
    ("se-dist", P, "        d = sqrtf(dx * dx + dy * dy);",
     "        d = sqrtf(dx * dx + dy * dy + 1e-3f);"),
    ("se-dz", P, "        dz = fabsf(mine->State.Position.z - "
     "o->State.Position.z);", "        dz = mine->State.Position.z - "
     "o->State.Position.z;"),
    ("se-near", P, "#define CHASE_NEAR          20.0f",
     "#define CHASE_NEAR          21.0f"),
    ("se-range", P, "#define CHASE_RANGE         175.0f",
     "#define CHASE_RANGE         176.0f"),
    ("se-score", P, "#define CHASE_SCORE         185.0f",
     "#define CHASE_SCORE         186.0f"),
    ("se-ahead", P, "#define CHASE_AHEAD         10000",
     "#define CHASE_AHEAD         8192"),
    ("se-dz-le", P, "        if (dz < CHASE_NEAR && d < CHASE_RANGE",
     "        if (dz <= CHASE_NEAR && d < CHASE_RANGE"),
    ("se-d-le", P, "        if (dz < CHASE_NEAR && d < CHASE_RANGE",
     "        if (dz < CHASE_NEAR && d <= CHASE_RANGE"),
    ("se-front-off", P, "\n            && car_is_car_in_front(mine, o, "
     "CHASE_AHEAD))", ")"),
    ("se-near-off", P, "        else if (d < CHASE_NEAR)\n", "        else "
     "if (0)\n"),
    ("se-near-le", P, "        else if (d < CHASE_NEAR)\n", "        else if "
     "(d <= CHASE_NEAR)\n"),
    ("se-was", P, "        score[was] = 0.0f;",
     "        score[was] = -1.0f;"),
    ("se-was-test", P, "    if (was >= 0 && was < n && -1.0f < score[was])",
     "    if (was >= 0 && was < n)"),
    ("se-before", P, "        score[before] = PICK_HOLD;",
     "        score[before] = -0.5f;"),
    ("se-before-test", P, "    if (before >= 0 && before < n && -1.0f < "
     "score[before])", "    if (before >= 0 && before < n)"),
    ("se-order", P, "    if (was >= 0 && was < n && -1.0f < score[was])\n"
     "        score[was] = 0.0f;\n    if (before >= 0 && before < n && -1.0f "
     "< score[before])\n        score[before] = PICK_HOLD;",
     "    if (before >= 0 && before < n && -1.0f < score[before])\n"
     "        score[before] = PICK_HOLD;\n    if (was >= 0 && was < n && "
     "-1.0f < score[was])\n        score[was] = 0.0f;"),
    ("se-tie", P, "        if (top < score[i]) {", "        if (top <= "
     "score[i]) {"),
    ("se-top", P, "    float   top = -1.0f;", "    float   top = 0.0f;"),
    ("se-p0", P, "    c->nPrevSelection[0] = best;\n",
     "    c->nPrevSelection[0] = was;\n"),
    ("se-p1", P, "    c->nPrevSelection[1] = was;\n",
     "    c->nPrevSelection[1] = best;\n"),
    ("se-t1", P, "    c->fPrevSelectionTimer[1] = c->fPrevSelectionTimer[0];\n",
     ""),
    ("se-t0", P, "#define PICK_HOLD           5.0f",
     "#define PICK_HOLD           4.0f"),
    # ---- the toggle
    ("tg-stage", P, "    if (pCurrentRace->RaceStage != RACE_STAGE_RACING)",
     "    if (pCurrentRace->RaceStage < RACE_STAGE_COUNTDOWN)"),
    ("tg-off", P, "        tplayercop_change_chase_target((tPlayerCop *)c);",
     "        tplayercop_think((tPlayerCop *)c);"),
    # ---- BeACopThink
    ("bt-flyby", P, "    if (pCurrentRace->RaceStage == RACE_STAGE_FLYBY\n",
     "    if (pCurrentRace->RaceStage == RACE_STAGE_NONE\n"),
    ("bt-flyby-players", P, "        && TheRaceParameters.NumPlayerCars == 2 "
     "&& m->New10488 == 0) {", "        && TheRaceParameters.NumPlayerCars "
     "!= 1 && m->New10488 == 0) {"),
    ("bt-busted-flag", P, "&& m->New10488 == 0) {", "&& 1) {"),
    ("bt-busted-once", P, "        m->New10488 = 1;\n", ""),
    ("bt-busted-call", P, "        play_busted_speech();\n", ""),
    ("bt-prerace", P, "    if (pCurrentRace->RaceStage == RACE_STAGE_PRERACE\n",
     "    if (pCurrentRace->RaceStage == RACE_STAGE_COUNTDOWN\n"),
    ("bt-said-test", P, "        && m->bBeACopAlreadySaidLookOutForSpeeders "
     "== 0) {", "        ) {"),
    ("bt-said", P, "        m->bBeACopAlreadySaidLookOutForSpeeders = 1;\n",
     ""),
    ("bt-land-pos", P, "copmgr_find_landmark((const bVector2 *)"
     "&car->State.Position);", "copmgr_find_landmark((const bVector2 *)"
     "&car->State.Position.y);"),
    ("bt-land-none", P, "lm != NULL ? lm->LandmarkType : 0);",
     "lm != NULL ? lm->LandmarkType : -1);"),
    ("bt-land-type", P, "lm != NULL ? lm->LandmarkType : 0);",
     "lm != NULL ? 0 : 0);"),
    ("bt-time-players", P, "        if (TheRaceParameters.NumPlayerCars == 2) "
     "{\n            float laps", "        if (TheRaceParameters.NumPlayerCars "
     "!= 1) {\n            float laps"),
    ("bt-p2p", P, "            float laps = TheRaceParameters.Point2Point != 0",
     "            float laps = TheRaceParameters.Point2Point == 1"),
    ("bt-p2p-one", P, "                         ? 1.0f : (float)"
     "TheRaceParameters.NumLapsInRace;", "                         ? 2.0f : "
     "(float)TheRaceParameters.NumLapsInRace;"),
    ("bt-laps", P, "                         ? 1.0f : (float)"
     "TheRaceParameters.NumLapsInRace;", "                         ? 1.0f : "
     "(float)TheRaceParameters.NumPlayerCars;"),
    ("bt-scale", P, "#define BEACOP_TIME_SCALE   1.5f",
     "#define BEACOP_TIME_SCALE   1.25f"),
    ("bt-lap", P, "->TotalTimeAroundTrack * laps * BEACOP_TIME_SCALE;",
     "->TotalTimeAroundTrack * BEACOP_TIME_SCALE;"),
    ("bt-zero", P, "    timer_set_time(&zero, 0.0f);",
     "    timer_set_time(&zero, 0.001f);"),
    ("bt-clock-le", P, "    if (!((int32_t)zero.PackedTime\n          < "
     "(int32_t)pCurrentRace", "    if (!((int32_t)zero.PackedTime\n          "
     "<= (int32_t)pCurrentRace"),
    ("bt-clock-unsigned", P, "    if (!((int32_t)zero.PackedTime\n          < "
     "(int32_t)pCurrentRace->RaceTime.PackedTime))", "    if (!(zero.PackedTime"
     "\n          < pCurrentRace->RaceTime.PackedTime))"),
    ("bt-rc-null", P, "    if (rc != NULL && rc->FinishReason == 0) {",
     "    if (rc->FinishReason == 0) {"),
    ("bt-rc-finish", P, "    if (rc != NULL && rc->FinishReason == 0) {",
     "    if (rc != NULL && rc->FinishReason <= 0) {"),
    ("bt-pull-own", P, "            if (m->CarPullovers[i].bActive != 0 && i "
     "!= car->CarIndex)", "            if (m->CarPullovers[i].bActive != 0)"),
    ("bt-pull-n", P, "        for (i = 0; i < COPMANAGER_NUM_PULLOVERS; i++)",
     "        for (i = 0; i < 7; i++)"),
    ("bt-pull-field", P, "            if (m->CarPullovers[i].bActive != 0 && i "
     "!= car->CarIndex)", "            if (m->CarPullovers[i].bPlayNIS != 0 "
     "&& i != car->CarIndex)"),
    ("bt-player", P, "        if (pl != NULL && pulled == 0) {",
     "        if (pulled == 0) {"),
    ("bt-pulled", P, "        if (pl != NULL && pulled == 0) {",
     "        if (pl != NULL) {"),
    ("bt-dt", P, "            m->fBeACopTime -= WorldTimeElapsed;",
     "            m->fBeACopTime -= WorldTimeElapsedFrame;"),
    ("bt-le", P, "            if (m->fBeACopTime <= 0.0f)",
     "            if (m->fBeACopTime < 0.0f)"),
    ("to-zero", P, "    m->fBeACopTime = 0.0f;\n    race_finish", "    "
     "race_finish"),
    ("to-pos", P, "    race_finish_car_by_car(pCurrentRace, car, -1, 0,",
     "    race_finish_car_by_car(pCurrentRace, car, 0, 0,"),
    ("to-reason", P, "car, -1, 0,\n                           "
     "RACING_CAR_BE_THE_COP_LOST);\n    be_a_cop", "car, -1, 0,\n"
     "                           RACING_CAR_BE_THE_COP_WON);\n    be_a_cop"),
    ("to-missed", P, "    be_a_cop_arrest_speech(TheRaceParameters."
     "NumPlayerCars, 1, 2,", "    be_a_cop_arrest_speech(TheRaceParameters."
     "NumPlayerCars, 0, 2,"),
    ("to-winner", P, "    be_a_cop_arrest_speech(TheRaceParameters."
     "NumPlayerCars, 1, 2,", "    be_a_cop_arrest_speech(TheRaceParameters."
     "NumPlayerCars, 1, 1,"),
    ("to-arrests", P, "    be_a_cop_arrest_speech(TheRaceParameters."
     "NumPlayerCars, 1, 2,\n                           m->"
     "nBeACopNumArrestsMade);", "    be_a_cop_arrest_speech(TheRaceParameters."
     "NumPlayerCars, 1, 2,\n                           m->"
     "nBeACopNumChopperAttacks);"),
    ("to-pursuit", P, "    if (cop->pMyPursuit != NULL) {", "    if (1) {"),
    ("to-delete", P, "        copmanager_delete_pursuit(m, cop->pMyPursuit);"
     "\n", ""),
    ("to-letgo", P, "        tcop_set_pursuit(cop, NULL);\n", ""),
    ("to-two", P, "    if (TheRaceParameters.NumPlayerCars == 2) {\n"
     "        Car *other", "    if (0) {\n        Car *other"),
    ("to-other", P, "        Car *other = pCurrentWorld->CarTable[1];",
     "        Car *other = pCurrentWorld->CarTable[2];"),
    ("to-other-done", P, "        if (other != NULL && other->pRacingCar->"
     "FinishReason == 0)", "        if (other != NULL)"),
    ("to-other-reason", P, "            race_finish_car_by_car(pCurrentRace, "
     "other, -1, 0,\n                                   "
     "RACING_CAR_BE_THE_COP_LOST);", "            race_finish_car_by_car("
     "pCurrentRace, other, -1, 0,\n                                   "
     "RACING_CAR_BE_THE_COP_WON);"),
    ("wr-threshold", P, "#define WRECKED             1.0f",
     "#define WRECKED             1.0000001f"),
    ("wr-lt", P, "        if (!(WRECKED <= *dmg))",
     "        if (!(WRECKED < *dmg))"),
    ("wr-nan", P, "        if (!(WRECKED <= *dmg))",
     "        if (*dmg < WRECKED)"),
    ("wr-index", P, "        float *dmg = &m->fCarDamage[c->CarIndex];",
     "        float *dmg = &m->fCarDamage[i];"),
    ("wr-n", P, "    for (i = 0; i < pCurrentWorld->CopCarPos; i++) {\n"
     "        Car   *c", "    for (i = 0; i <= pCurrentWorld->CopCarPos "
     "&& i < 8; i++) {\n        Car   *c"),
    ("wr-damage", P, "        if (c->pCarDamage != NULL) {", "        if (0) {"),
    ("wr-damage-arg", P, "            gCarDamageWreckFn(c->pCarDamage);",
     "            gCarDamageWreckFn(c);"),
    ("wr-type", P, "        if (c->MyDriver->TheDriverType == "
     "DRIVER_TYPE_AI_RACER) {\n            force_boost", "        if "
     "(c->MyDriver->TheDriverType == DRIVER_TYPE_COP) {\n            force_boost"),
    ("wr-boost0", P, "BeACopWreckBoost[3] = { 0.3f, 0.4f, 0.5f };",
     "BeACopWreckBoost[3] = { 0.25f, 0.4f, 0.5f };"),
    ("wr-boost1", P, "BeACopWreckBoost[3] = { 0.3f, 0.4f, 0.5f };",
     "BeACopWreckBoost[3] = { 0.3f, 0.45f, 0.5f };"),
    ("wr-boost2", P, "BeACopWreckBoost[3] = { 0.3f, 0.4f, 0.5f };",
     "BeACopWreckBoost[3] = { 0.3f, 0.4f, 0.6f };"),
    ("wr-difficulty", P, "                        BeACopWreckBoost[m->"
     "nDifficultyLevel]);", "                        BeACopWreckBoost[0]);"),
    ("wr-this", P, "    ((ForceBoostFn)e->fn)(vt_this(ctl, e), f);",
     "    ((ForceBoostFn)e->fn)(ctl, f);"),
    ("wr-player", P, "        } else if (c->pPlayer != NULL && c != car) {",
     "        } else if (c != car) {"),
    ("wr-mine", P, "        } else if (c->pPlayer != NULL && c != car) {",
     "        } else if (c->pPlayer != NULL) {"),
    ("wr-dboost", P, "#define WRECK_DAMAGE_BOOST  0.75f",
     "#define WRECK_DAMAGE_BOOST  0.8f"),
    ("wr-dboost-off", P, "            c->fDamageBoostOverride = "
     "WRECK_DAMAGE_BOOST;\n", ""),
    ("wr-traction", P, "#define WRECK_TRACTION      0.0125f",
     "#define WRECK_TRACTION      0.0126f"),
    ("wr-traction-1", P, "            c->fTractionBoostOverride = 1.0f - *dmg "
     "* WRECK_TRACTION;", "            c->fTractionBoostOverride = 0.9f - "
     "*dmg * WRECK_TRACTION;"),
    ("wr-traction-off", P, "            c->fTractionBoostOverride = 1.0f - "
     "*dmg * WRECK_TRACTION;\n", ""),
    ("end-two", P, "    if (TheRaceParameters.NumPlayerCars == 2) {\n"
     "        Car *first", "    if (1) {\n        Car *first"),
    ("end-first", P, "        if (first->pRacingCar->FinishReason == 0\n",
     "        if (1\n"),
    ("end-second", P, "            && second->pRacingCar->FinishReason != 0) {",
     "            && second->pRacingCar->FinishReason > 0) {"),
    ("end-first-index", P, "        Car *first = pCurrentWorld->CarTable[0];",
     "        Car *first = pCurrentWorld->CarTable[2];"),
    ("end-finish", P, "            race_finish_car_by_car(pCurrentRace, first, "
     "-1, 0,", "            race_finish_car_by_car(pCurrentRace, second, "
     "-1, 0,"),
    ("end-speech", P, "            be_a_cop_arrest_speech(TheRaceParameters."
     "NumPlayerCars, 0, 2,", "            be_a_cop_arrest_speech("
     "TheRaceParameters.NumPlayerCars, 1, 2,"),
]

EQUIVALENT = {
    "se-score": "a car that scores is closer than 175 m, so its 185 - d is "
                "above 10 either way, over the old picks' 0 and 5",
    "se-order": "the order tells only when the two old picks are one car, "
                "which scores above -1 either way and loses to any other",
}


def write_inputs(d):
    sc = script()
    scp = Path(d) / "script.txt"
    scp.write_bytes(encode(sc).encode("latin-1"))
    return model_cached(sc), scp


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    indir = tempfile.TemporaryDirectory()
    lines, scp = write_inputs(indir.name)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text().splitlines()
        if diff(lines, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)
    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "playercop_test",
        lambda exe, o: mutpar.run_exe([exe, scp], o, limit),
        lines, diff, EQUIVALENT, jobs)
    indir.cleanup()
    return mutpar.summarize(todo, only, EQUIVALENT, tally)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...")
    ap.add_argument("--jobs", type=int, metavar="N")
    ap.add_argument("--dump", metavar="PREFIX")
    args = ap.parse_args()
    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None,
                             args.jobs))
    with tempfile.TemporaryDirectory() as tmp:
        lines, scp = write_inputs(tmp)
        exe = build_harness(tmp)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text().splitlines()
    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)
    n = diff(lines, harness)
    print("%d lines, %d differ" % (len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
