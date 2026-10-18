#!/usr/bin/env python3
"""Cross-check 3DS Files/source/pausereplay.c, the pause pages' special
events, against the retail image, SLES_507.31 (TASKS 72h-1).

**The model** is retail's HandlePauseMenuReplaySpecialEvents (0x001703e0)
run in retail_model.RetailEmu, with retail's Player::SetDrivingStyle
(0x00181e48) under it. The harness (tools/src/pausereplay_test.c) runs
pausereplay.c.

**The stubs** print what they are asked, on both sides:
SetAIDriverModesFromPlayers (0x001cd240), CarDamage::RethinkDamage
(0x001b5a78), which can also take a car off the world's count, add one,
or clear pCurrentWorld, and RealDriver::SetManualTransmission
(0x0013b390).

**What is made equal by hand.** Retail reads through the players, cars
and world with no test, and the port skips what is NULL. The script
reaches only the NULLs whose reads land in low memory, which the model
zeroes before each state:

- a player with no car: retail's handling writes the car's DriverMode at
  988 and the port skips it; retail's transmission hands
  SetManualTransmission the word at 44, a NULL driver;
- a car with no driver: retail hands SetManualTransmission NULL, and the
  port does not call it. The model's stub prints nothing for NULL;
- a NULL car in the world's table: retail reads its CarDamage from 2120,
  which is 0;
- no world: retail reads a count of 0 from 28.

Player numbers off the table and NULL players are the port's alone, and
the script leaves them out.

**The script** sends every type from -2 to 9 over two states; each of the
seven events over their values' edges, bytes and words; the damage over
every car count, mask of CarDamages and NULL cars, with each of the
stub's moves; the transmission with and without a car and a driver; and
then random states and events.

    python tools/pausereplay_check.py
    python tools/pausereplay_check.py --mutate [--only a,b] [--jobs N]
    python tools/pausereplay_check.py --dump out/pausereplay
"""
import argparse
import os
import random
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

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/pausereplay_test.c"
PR = "3DS Files/source/pausereplay.c"
SOURCES = [HARNESS, PR]

GP = retail_model.RETAIL_GP
F_HANDLE = 0x001703e0           # HandlePauseMenuReplaySpecialEvents
S_AI = 0x001cd240               # SetAIDriverModesFromPlayers
S_RETHINK = 0x001b5a78          # CarDamage::RethinkDamage
S_MANUAL = 0x0013b390           # RealDriver::SetManualTransmission
PLAYERS = GP - 20936            # PlayersByNumber[2]
P_WORLD = GP - 22120            # pCurrentWorld
P_RACE = GP - 22272             # pCurrentRace
EASY = GP - 20120               # SuperEasyAI
RP = 0x0031a898                 # TheRaceParameters
RP_DAMAGE = RP + 64             # DamageEnabled
RP_MODE = RP + 596              # NFSRaceMode
RP_JUMP = RP + 754              # GlobalDisplaySettings.JumpCams
RP_ZONE = RP + 755              # GlobalDisplaySettings.ZoneCams

# Retail's offsets.
PL_CAR, PL_STYLE, PL_TRANS = 4, 34, 35
CAR_DRIVER, CAR_MODE, CAR_DAMAGE = 44, 988, 2120
W_COUNT, W_TABLE, W_MAX = 28, 44, 14
RACE_POS, RACE_PNUM = 1608, 1612

CARS = 8
CAR_SIZE = 2304
LOW = 4096                      # the low memory NULL reads land in

FIELDS = ("dmg mode jump zone easy fpos fpnum s0 t0 s1 t1 m0 m1 ncars "
          "dmgmask nullmask car0 car1 drv0 drv1 world stub").split()


# ---------------------------------------------------------------- the script

def base_state(**kw):
    st = dict(dmg=1, mode=0, jump=1, zone=1, easy=0, fpos=0, fpnum=0,
              s0=0, t0=0, s1=1, t1=1, m0=0, m1=1, ncars=8, dmgmask=0xff,
              nullmask=0, car0=1, car1=1, drv0=1, drv1=1, world=1, stub=0)
    for k, v in kw.items():
        assert k in st, k
        st[k] = v
    return st


EDGES = (0, 1, 2, -1, 0x7f, 0x80, 0xff, 0x100, 0x1ff, -0x80, 0x12345678,
         -0x80000000, 0x7fffffff)


def script():
    ops = []

    def state(**kw):
        ops.append(("state", base_state(**kw)))

    def ev(t, a, b):
        ops.append(("ev", (t, a, b)))

    # Every type over two states.
    for st in (base_state(), base_state(dmg=0, mode=1, jump=0, zone=0,
                                        easy=1, s0=1, t0=2, ncars=3)):
        ops.append(("state", st))
        for t in range(-2, 10):
            ev(t, 1, 0)
            ev(t, 0, 1)

    # 0: the forced finish.
    state()
    for a in EDGES:
        ev(0, a, 3 - a)

    # 1: the handling, each player, with and without a car.
    for car in (1, 0):
        for p in (0, 1):
            state(**{"car%d" % p: car})
            for b in EDGES:
                ev(1, p, b)

    # 2: the damage over the counts, the masks and the stub's moves.
    state()
    for a in EDGES:
        ev(2, a, a ^ 5)
    for n in range(CARS + 1):
        for mask in (0, 0xff, 0x55, 0xaa, 0x01, 0x80):
            state(ncars=n, dmgmask=mask, dmg=n & 1)
            ev(2, (n + 1) & 1, 0)
    for nulls in (0x01, 0x81, 0xf0, 0xff):
        state(nullmask=nulls)
        ev(2, 1, 0)
    for stub in (1, 2, 3):
        for n in (0, 1, 2, 5, 7, 8):
            for mask in (0xff, 0x0f, 0xf0, 0x24):
                state(ncars=n, dmgmask=mask, stub=stub)
                ev(2, 0, 0)
                ev(2, 1, 0)
    state(world=0)
    ev(2, 0, 0)
    ev(2, 1, 0)

    # 3: the transmission, with and without a car and a driver.
    for car, drv in ((1, 1), (1, 0), (0, 1), (0, 0)):
        for p in (0, 1):
            state(**{"car%d" % p: car, "drv%d" % p: drv})
            for b in EDGES:
                ev(3, p, b)

    # 4, 5 and 6.
    for t in (4, 5, 6):
        state()
        for a in EDGES:
            ev(t, a, 0x5a)
            ev(t, a ^ 1, a)

    # Random states and events.
    rnd = random.Random(72081)
    for _ in range(300):
        st = base_state(
            dmg=rnd.choice((0, 1, rnd.getrandbits(8))),
            mode=rnd.choice((0, 1, 2, rnd.getrandbits(32))),
            jump=rnd.getrandbits(8), zone=rnd.getrandbits(8),
            easy=rnd.choice((0, 1, rnd.getrandbits(32))),
            fpos=rnd.randrange(-2, 9), fpnum=rnd.randrange(-2, 3),
            s0=rnd.getrandbits(8), t0=rnd.getrandbits(8),
            s1=rnd.getrandbits(8), t1=rnd.getrandbits(8),
            m0=rnd.randrange(-3, 4), m1=rnd.randrange(-3, 4),
            ncars=rnd.randrange(CARS + 1), dmgmask=rnd.getrandbits(8),
            nullmask=rnd.choice((0, 0, rnd.getrandbits(8))),
            car0=rnd.randrange(2), car1=rnd.randrange(2),
            drv0=rnd.randrange(2), drv1=rnd.randrange(2),
            world=rnd.choice((1, 1, 1, 0)), stub=rnd.randrange(4))
        ops.append(("state", st))
        for _ in range(rnd.randrange(1, 6)):
            t = rnd.choice((0, 1, 2, 3, 4, 5, 6, 6, 7, -1))
            a = rnd.randrange(2) if t in (1, 3) else rnd.choice(
                (rnd.randrange(-2, 3), rnd.getrandbits(32) - (1 << 31)))
            ev(t, a, rnd.choice((rnd.randrange(-3, 4),
                                 rnd.getrandbits(32) - (1 << 31))))
    return ops


def to_s32(v):
    return s32(v & M32)


def write_script(tmp, ops):
    lines = []
    for kind, v in ops:
        if kind == "state":
            lines.append("state " + " ".join(str(to_s32(v[f]))
                                             for f in FIELDS))
        else:
            lines.append("ev %d %d %d" % tuple(to_s32(x) for x in v))
    path = Path(tmp) / "script.txt"
    path.write_text(NL.join(lines) + NL)
    return path


# ================================================================ the model

class Model(object):
    def __init__(self):
        e = self.e = retail_model.RetailEmu()
        self.out = []
        self.players = self.zalloc(2 * 256)
        self.cars = self.zalloc(CARS * CAR_SIZE)
        self.damage = self.zalloc(CARS * 16)
        self.drivers = self.zalloc(2 * 16)
        self.world = self.zalloc(128)
        self.race = self.zalloc(2048)
        self.event = self.zalloc(16)
        self.stub = 0
        for i in range(2):
            e.put32(PLAYERS + 4 * i, self.players + 256 * i)
        e.put32(P_RACE, self.race)
        e.stub(S_AI, self.ai)
        e.stub(S_RETHINK, self.rethink)
        e.stub(S_MANUAL, self.manual)

    def zalloc(self, n):
        p = self.e.alloc(n, 16)
        self.e.write(p, bytes(n))
        return p

    def put8(self, a, v):
        self.e.write(a, bytes([v & 0xff]))

    def car(self, k):
        return self.cars + CAR_SIZE * k

    # ---- the stubs

    def ai(self, e):
        self.out.append("  ai modes")

    def rethink(self, e):
        d = e.reg[4] & M32
        off = d - self.damage
        k = off // 16 if 0 <= off < CARS * 16 and off % 16 == 0 else CARS
        self.out.append("  rethink D%d" % k)
        n = s32(e.u32(self.world + W_COUNT))
        if self.stub == 1:
            e.put32(self.world + W_COUNT, n - 1)
        elif self.stub == 2 and n < CARS:
            e.put32(self.world + W_COUNT, n + 1)
        elif self.stub == 3:
            e.put32(P_WORLD, 0)

    def manual(self, e):
        d, m = e.reg[4] & M32, s32(e.reg[5])
        if d == 0:
            return                      # the port does not call it
        i = 0 if d == self.drivers else 1 if d == self.drivers + 16 else 9
        self.out.append("  manual R%d %d" % (i, m))

    # ---- the ops

    def dump(self):
        e = self.e
        self.out.append(
            "  dmg %d mode %d jump %02x zone %02x easy %d force %d %d"
            % (s32(e.u32(RP_DAMAGE)), s32(e.u32(RP_MODE)), e.u8(RP_JUMP),
               e.u8(RP_ZONE), s32(e.u32(EASY)),
               s32(e.u32(self.race + RACE_POS)),
               s32(e.u32(self.race + RACE_PNUM))))
        for i in range(2):
            p = self.players + 256 * i
            self.out.append("  p%d style %02x trans %02x car %d" % (
                i, e.u8(p + PL_STYLE), e.u8(p + PL_TRANS),
                s32(e.u32(self.car(i) + CAR_MODE))))
        self.out.append("  world %s cars %d" % (
            "W" if e.u32(P_WORLD) else "NULL",
            s32(e.u32(self.world + W_COUNT))))

    def state(self, st):
        e = self.e
        e.write(0, bytes(LOW))
        e.put32(RP_DAMAGE, st["dmg"])
        e.put32(RP_MODE, st["mode"])
        self.put8(RP_JUMP, st["jump"])
        self.put8(RP_ZONE, st["zone"])
        e.put32(EASY, st["easy"])
        e.put32(self.race + RACE_POS, st["fpos"])
        e.put32(self.race + RACE_PNUM, st["fpnum"])
        for i in range(2):
            p = self.players + 256 * i
            self.put8(p + PL_STYLE, st["s%d" % i])
            self.put8(p + PL_TRANS, st["t%d" % i])
            e.put32(self.car(i) + CAR_MODE, st["m%d" % i])
            e.put32(p + PL_CAR, self.car(i) if st["car%d" % i] else 0)
            e.put32(self.car(i) + CAR_DRIVER,
                    self.drivers + 16 * i if st["drv%d" % i] else 0)
        e.put32(self.world + W_COUNT, st["ncars"])
        for k in range(W_MAX):
            live = k < CARS and not (st["nullmask"] >> k) & 1
            e.put32(self.world + W_TABLE + 4 * k, self.car(k) if live else 0)
            if k < CARS:
                e.put32(self.car(k) + CAR_DAMAGE,
                        self.damage + 16 * k
                        if (st["dmgmask"] >> k) & 1 else 0)
        e.put32(P_WORLD, self.world if st["world"] else 0)
        self.stub = st["stub"]
        self.out.append("state")
        self.dump()

    def ev(self, t, a, b):
        e = self.e
        for i, v in enumerate((t, 0, a, b)):
            e.put32(self.event + 4 * i, v)
        self.out.append("ev %d %d %d" % (to_s32(t), to_s32(a), to_s32(b)))
        r = e.call(F_HANDLE, self.event)
        self.out.append("  ret %d" % r)
        self.dump()

    def run(self, ops):
        for kind, v in ops:
            if kind == "state":
                self.state(v)
            else:
                self.ev(*v)
        self.out.append("faults 0")
        return self.out


def model(ops):
    return Model().run(ops)


# ---------------------------------------------------------------- running

diff = pcc.diff


def run_harness(exe, script, out, timeout=120):
    return mutpar.run_exe([exe, script], out, timeout)


# -------------------------------------------------------------- mutations
#
# (name, file, old, new). Each replaces the first match, so every pattern
# is spelled to match code and not a comment.

def M(name, before, after):
    return (name, PR, before, after)


MUTATIONS = [
    # -- the players
    M("players-1", "n >= 0 && n < 2", "n >= 0 && n < 1"),
    M("players-other", "PlayerPlayersByNumber[n]",
      "PlayerPlayersByNumber[n ^ 1]"),
    # -- 0, the forced finish
    M("finish-swap", "ForceRaceFinishPlayerNum = e->B",
      "ForceRaceFinishPlayerNum = e->A"),
    M("finish-pos", "ForceRaceFinishPosition = e->A",
      "ForceRaceFinishPosition = e->B"),
    M("finish-ret", "            pCurrentRace->ForceRaceFinishPosition = e->A;"
      "\n        }\n        return 1;",
      "            pCurrentRace->ForceRaceFinishPosition = e->A;\n        }\n"
      "        return 0;"),
    # -- 1, the handling
    M("hand-player", "    case PAUSE_EVENT_HANDLING:\n        p = player_by_number(e->A);",
      "    case PAUSE_EVENT_HANDLING:\n        p = player_by_number(e->B);"),
    M("hand-car", "p->MyCar->State.DriverMode = e->B;",
      "p->MyCar->State.DriverMode = e->A;"),
    M("hand-no-car", "                p->MyCar->State.DriverMode = e->B;\n", "                ;\n"),
    M("hand-style", "p->PlayerSettings.DrivingStyle = (int8_t)e->B;",
      "p->PlayerSettings.DrivingStyle = (int8_t)e->A;"),
    M("hand-no-style", "            p->PlayerSettings.DrivingStyle = (int8_t)e->B;",
      "            (void)0;"),
    M("hand-mode", "TheRaceParameters.NFSRaceMode = e->B;",
      "TheRaceParameters.NFSRaceMode = e->A;"),
    M("hand-mode-byte", "TheRaceParameters.NFSRaceMode = e->B;",
      "TheRaceParameters.NFSRaceMode = (int8_t)e->B;"),
    M("hand-no-ai", "        set_ai_driver_modes_from_players();\n", ""),
    M("hand-ret", "        set_ai_driver_modes_from_players();\n        return 1;",
      "        set_ai_driver_modes_from_players();\n        return 0;"),
    # -- 2, the damage
    M("dmg-raw", "DamageEnabled = e->A != 0;", "DamageEnabled = e->A;"),
    M("dmg-not", "DamageEnabled = e->A != 0;", "DamageEnabled = e->A == 0;"),
    M("dmg-b", "DamageEnabled = e->A != 0;", "DamageEnabled = e->B != 0;"),
    M("dmg-bit", "DamageEnabled = e->A != 0;", "DamageEnabled = e->A & 1;"),
    M("dmg-count-le", "i < pCurrentWorld->TotalNumCars;",
      "i <= pCurrentWorld->TotalNumCars;"),
    M("dmg-count-once",
      "        for (i = 0; pCurrentWorld != NULL && i < pCurrentWorld->TotalNumCars;",
      "        int32_t n0 = pCurrentWorld != NULL ? pCurrentWorld->TotalNumCars"
      " : 0;\n        for (i = 0; pCurrentWorld != NULL && i < n0;"),
    M("dmg-world-once",
      "        for (i = 0; pCurrentWorld != NULL && i < pCurrentWorld->TotalNumCars;",
      "        World *w0 = pCurrentWorld;\n"
      "        for (i = 0; w0 != NULL && i < w0->TotalNumCars;"),
    M("dmg-from-1", "for (i = 0; pCurrentWorld", "for (i = 1; pCurrentWorld"),
    M("dmg-no-test", "if (c != NULL && c->pCarDamage != NULL)",
      "if (c != NULL)"),
    M("dmg-skip-0", "if (c != NULL && c->pCarDamage != NULL)",
      "if (c != NULL && c->pCarDamage != NULL && i > 0)"),
    M("dmg-no-call", "                cardamage_rethink_damage(c->pCarDamage);",
      "                ;"),
    M("dmg-ret", "                cardamage_rethink_damage(c->pCarDamage);\n"
      "        }\n        return 1;",
      "                cardamage_rethink_damage(c->pCarDamage);\n"
      "        }\n        return 0;"),
    # -- 3, the transmission
    M("trans-player", "    case PAUSE_EVENT_TRANSMISSION:\n        p = player_by_number(e->A);",
      "    case PAUSE_EVENT_TRANSMISSION:\n        p = player_by_number(e->B);"),
    M("trans-type", "TransmissionType = (int8_t)e->B;",
      "TransmissionType = (int8_t)e->A;"),
    M("trans-style", "p->PlayerSettings.TransmissionType = (int8_t)e->B;",
      "p->PlayerSettings.DrivingStyle = (int8_t)e->B;"),
    M("trans-no-type", "        p->PlayerSettings.TransmissionType = (int8_t)e->B;\n", ""),
    M("trans-manual", "(RealDriver *)p->MyCar->pCarDriver, e->B);",
      "(RealDriver *)p->MyCar->pCarDriver, e->A);"),
    M("trans-no-manual", "            realdriver_set_manual_transmission(\n"
      "                (RealDriver *)p->MyCar->pCarDriver, e->B);",
      "            ;"),
    M("trans-ret", "                (RealDriver *)p->MyCar->pCarDriver, e->B);\n"
      "        return 1;",
      "                (RealDriver *)p->MyCar->pCarDriver, e->B);\n"
      "        return 0;"),
    # -- 4, 5 and 6
    M("jump-zone", "GlobalDisplaySettings.JumpCams = (int8_t)e->A;",
      "GlobalDisplaySettings.ZoneCams = (int8_t)e->A;"),
    M("jump-b", "GlobalDisplaySettings.JumpCams = (int8_t)e->A;",
      "GlobalDisplaySettings.JumpCams = (int8_t)e->B;"),
    M("jump-bool", "GlobalDisplaySettings.JumpCams = (int8_t)e->A;",
      "GlobalDisplaySettings.JumpCams = e->A != 0;"),
    M("zone-jump", "GlobalDisplaySettings.ZoneCams = (int8_t)e->A;",
      "GlobalDisplaySettings.JumpCams = (int8_t)e->A;"),
    M("zone-bool", "GlobalDisplaySettings.ZoneCams = (int8_t)e->A;",
      "GlobalDisplaySettings.ZoneCams = e->A != 0;"),
    M("easy-b", "SuperEasyAI = e->A;", "SuperEasyAI = e->B;"),
    M("easy-bool", "SuperEasyAI = e->A;", "SuperEasyAI = e->A != 0;"),
    M("easy-ret", "        SuperEasyAI = e->A;\n        return 1;",
      "        SuperEasyAI = e->A;\n        return 0;"),
    M("default-ret", "    default:\n        return 0;",
      "    default:\n        return 1;"),
    # -- the numbers
    M("num-handling", "#define PAUSE_EVENT_HANDLING      1",
      "#define PAUSE_EVENT_HANDLING      7"),
    M("num-easy", "#define PAUSE_EVENT_SUPER_EASY_AI 6",
      "#define PAUSE_EVENT_SUPER_EASY_AI 7"),
]

# The numbers are pausereplay.h's; mutpar's snapshot holds the headers.
HEADER = "3DS Files/source/pausereplay.h"
MUTATIONS = [(n, HEADER if b.startswith("#define") else f, b, a)
             for n, f, b, a in MUTATIONS]

EQUIVALENT = {}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    ops = script()
    with tempfile.TemporaryDirectory() as data:
        sp = write_script(data, ops)
        with tempfile.TemporaryDirectory() as tmp:
            exe = hostbuild.build(tmp, SOURCES, name="pausereplay_test")
            out = Path(tmp) / "base.txt"
            t0 = time.monotonic()
            rc = run_harness(exe, sp, out)
            took = time.monotonic() - t0
            base = out.read_text(encoding="latin-1").splitlines()
            if rc != 0 or diff(model(ops), base, quiet=True):
                print("base already differs -- fix that before mutating")
                return 1
            print("base: %d lines, 0 differ" % len(base), flush=True)
        limit = mutpar.timeout_for(took)
        tally = mutpar.run_pass(
            todo, SOURCES, "pausereplay_test",
            lambda exe, out: run_harness(exe, sp, out, limit),
            base, diff, EQUIVALENT, jobs)
    return mutpar.summarize(todo, only, EQUIVALENT, tally)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--jobs", type=int, metavar="N",
                    help="with --mutate, mutants at once (default %d)"
                    % mutpar.JOBS)
    ap.add_argument("--dump", metavar="DIR")
    args = ap.parse_args()
    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None,
                             args.jobs))
    ops = script()
    want = model(ops)
    with tempfile.TemporaryDirectory() as data:
        sp = write_script(data, ops)
        with tempfile.TemporaryDirectory() as tmp:
            exe = hostbuild.build(tmp, SOURCES, name="pausereplay_test")
            out = Path(tmp) / "out.txt"
            rc = run_harness(exe, sp, out)
            got = out.read_text(encoding="latin-1").splitlines()
    if args.dump:
        d = Path(args.dump)
        d.mkdir(parents=True, exist_ok=True)
        (d / "model.txt").write_text(NL.join(want) + NL)
        (d / "harness.txt").write_text(NL.join(got) + NL)
    n = diff(want, got)
    evs = sum(1 for k, _v in ops if k == "ev")
    print("pausereplay: %d ops, %d events, %d lines, %d differ%s"
          % (len(ops), evs, len(want), n, "" if rc == 0 else ", exit %d" % rc))
    sys.exit(1 if n or rc else 0)


if __name__ == "__main__":
    main()
