#!/usr/bin/env python3
"""Cross-check 3DS Files/source/playercop.c, Be A Cop's player cop (12m-1),
against the retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own code: tPlayerCop's Think (0x0022d5c8),
ChangeChaseTarget (0x0022d700) and SelectCarToChase (0x0022d898), and
tCopManager::BeACopToggleSirenAndLights (0x002289b8). The harness
(tools/src/playercop_test.c) runs the port and prints the same lines.

**The stubs**, logged and answered from the script on both sides:
Player::IsNisPlaying (each car's player's flag), Car::IsBlinking and
Car::IsCarInFront (each car's flags), tCopManager::RequestPursuit,
tPursuit's change of target (0x0022cb30, pursuitspeech_check.py's),
GetInGameSample (a sample or none), bSample::Play and the helicopter's
release (0x0022a310, pursuit_check.py's). The World's CopCarPos and car
table, the cars' places, racing cars, lights and siren, the manager's
pullovers and player cop, the pursuits and the helicopter's salvos are
memory both sides read.

**Compared** are the stubs' logs, the pick SelectCarToChase answers and,
after each call, the cop's two picks and their timers, and its car's
lights word and siren.

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
SOURCES = [HARNESS, PC]
HARNESS_TIMEOUT = 60

GP = retail_model.RETAIL_GP
G_WORLD = GP - 22120                    # pCurrentWorld
G_COPMGR = GP - 15620                   # pCopManager
G_ELAPSED = GP - 19560                  # WorldTimeElapsed
G_RACE = GP - 22272                     # pCurrentRace

F = {"think": 0x0022d5c8, "change": 0x0022d700, "select": 0x0022d898,
     "toggle": 0x002289b8}

S_NIS = 0x00176520
S_BLINK = 0x00133130
S_FRONT = 0x00133898
S_REQUEST = 0x00225078
S_RETARGET = 0x0022cb30
S_SAMPLE = 0x001ae280
S_PLAY = 0x00274080
S_RELEASE = 0x0022a310

NCARS, NCOPS, NP = 8, 3, 3
MGR_SIZE, CAR_SIZE, RC_SIZE, PURSUIT_SIZE, CHOPPER_SIZE = \
    10516, 2304, 192, 1600, 848
W_COPCARPOS, W_TABLE = 36, 44
C_PLAYER, C_RC, C_POS, C_LIGHTS, C_SIREN = 24, 28, 96, 2056, 2104
RC_FINISH = 18
M_PCI, M_COPS, M_PULL = 12, 16, 88
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
        self.race = block(16, "R")
        e.put32(G_RACE, self.race)
        self.cars = [block(CAR_SIZE, "A%d" % k) for k in range(NCARS)]
        self.rcs = [block(RC_SIZE, None) for k in range(NCARS)]
        self.players = [block(16, "P%d" % k) for k in range(NCARS)]
        self.cops = [block(64, "C%d" % k) for k in range(NCOPS)]
        self.ps = [block(PURSUIT_SIZE, "U%d" % k) for k in range(NP)]
        self.chopper = block(CHOPPER_SIZE, "H")
        self.sample = block(16, "S")
        for c, r in zip(self.cars, self.rcs):
            e.put32(c + C_RC, r)
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
                         (S_RELEASE, self.s_release)):
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
                e.put32(self.world + W_TABLE + 4 * j, self.cars[int(s)])
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
        elif o == "sample":
            self.sample_on = v(1)
        elif o == "request":
            self.request = v(1)
        elif o in F:
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


def base():
    out = [world(NCARS), "time|%s" % Fx(1.0 / 30), "race|4", "mgr|0",
           "sample|1", "request|1"]
    for k in range(NCARS):
        out.append(car(k, player=int(k == 0), x=10.0 * k, y=3.0 * k))
        out.append("pull|%d|0" % k)
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
            + toggle_cases() + random_runs(random.Random(0x12a1)))


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
