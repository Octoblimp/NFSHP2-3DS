#!/usr/bin/env python3
"""Cross-check 3DS Files/source/pursuitchopper.c, the helicopter's side
of a chase (12k-7), against the retail image, SLES_507.31, run in
mipsemu.

**The model** is retail's own code: tPursuit::UpdateChopper (0x00229678)
and IsChopperNearCar (0x0022bab8), and tCopManager's IsChopperAvailable
(0x00224ec0), RequestChopper (0x00224f00), BeACopRequestChopper
(0x002287d8) and BeACopRequestRoadBlock (0x002288c8). The harness
(tools/src/pursuitchopper_test.c) runs pursuitchopper.c and prints the
same lines.

**The stubs**, logged and answered by the same rule on both sides:
tPursuit::GetCopSpeaker (a scripted speaker), the speech manager's
raiseRotorRequest, raiseRotorConfirm and raiseDispatchHelicopterNA,
Chopper's AbortBombingRun, FollowThisCar and AttackCar, World::Random (a
scripted queue, then a scripted answer), GetInGameSample (the sample, or
none) and bSample::Play.

**Compared** are the stubs' logs and, after each call, the pursuit's
helicopter, timers, state and behaviours, the manager's bChopperBusy and
attacks, and each helicopter's TotalSalvos.

**The divergence**: the Be A Cop requests read the player cop's chase
through copmanager_get_player_cop, so no cop is no chase. Retail reads
the cop's first word with no test; Be A Cop always has its cop, and the
script never leaves it out.

    python tools/pursuitchopper_check.py
    python tools/pursuitchopper_check.py --mutate [--only a,b]
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

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/pursuitchopper_test.c"
PCH = "3DS Files/source/pursuitchopper.c"
SOURCES = [HARNESS, PCH]
HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = retail_model.RETAIL_GP
RP = 0x0031a898                         # TheRaceParameters
G_COPMGR = GP - 15620                   # pCopManager
G_SPEECH = GP - 15624                   # the speech manager
G_WORLD = GP - 22120                    # pCurrentWorld
G_DT = GP - 19560                       # WorldTimeElapsed

F_UPDATE = 0x00229678
F_NEAR = 0x0022bab8
F_AVAIL = 0x00224ec0
F_REQ = 0x00224f00
F_BACRC = 0x002287d8
F_BACRR = 0x002288c8

S_SPEAKER = 0x0022ab30
S_ROTORREQ = 0x0020af50
S_ROTORCONF = 0x0020afa0
S_HELINA = 0x0020b828
S_ABORT = 0x001eadf0
S_FOLLOW = 0x001e7f80
S_ATTACK = 0x001e8040
S_RANDOM = 0x0014e520
S_SAMPLE = 0x001ae280
S_PLAY = 0x00274080

RP_FIELDS = {"New624": 624, "BeACop": 628}
MGR_SIZE, WORLD_SIZE, PURSUIT_SIZE = 10516, 5936, 1600
CAR_SIZE, CHOPPER_SIZE, COP_SIZE = 2304, 976, 32
CAR_POS, CAR_BLOWN = 96, 2124
NP, NCARS, NH, NCOPS, RANDQ = 3, 3, 2, 3, 16

MFIELDS = {"nrb": 0, "pcidx": 12, "busy": 312, "beacopid": 10336,
           "super": 10348, "attacks": 10492}
# pursuit fields: chased car, roadblock, chopper, and the five words.
P_CHASED, P_RB, P_CHOPPER = 16, 20, 24
P_WORDS = (("timer", 1536), ("next", 1540), ("dir", 1548),
           ("state", 1580), ("flags", 1588))
H_CAR, H_TYPE, H_SALVOS, H_POS, H_N960 = 724, 804, 828, 832, 960


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def F(f):
    return "0x%08x" % fbits(f)


# ================================================================== model

class Model(object):
    def __init__(self):
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True,
                                            eesqrt=True)
        self.out = []
        self.names = {}

        def block(n, nm):
            p = e.alloc(n, align=16)
            e.write(p, bytes(n))
            self.names[p] = nm
            return p
        self.m = block(MGR_SIZE, "M")
        e.put32(G_COPMGR, self.m)
        self.world = block(WORLD_SIZE, "W")
        e.put32(G_WORLD, self.world)
        self.speech = block(16, "SP")
        e.put32(G_SPEECH, self.speech)
        self.rb = block(16, "RB")
        self.smp = block(16, "S")
        self.ps = [block(PURSUIT_SIZE, "U%d" % k) for k in range(NP)]
        self.cars = [block(CAR_SIZE, "A%d" % k) for k in range(NCARS)]
        self.hs = [block(CHOPPER_SIZE, "H%d" % k) for k in range(NH)]
        self.cops = [block(COP_SIZE, "C%d" % k) for k in range(NCOPS)]
        self.spk = 0
        self.randq, self.randqi, self.rand = [], 0, 0
        self.sample = 1
        for addr, fn in ((S_SPEAKER, self.s_speaker),
                         (S_ROTORREQ, self.s_rotorreq),
                         (S_ROTORCONF, self.s_rotorconf),
                         (S_HELINA, self.s_helina),
                         (S_ABORT, self.s_abort),
                         (S_FOLLOW, self.s_follow),
                         (S_ATTACK, self.s_attack),
                         (S_RANDOM, self.s_random),
                         (S_SAMPLE, self.s_sample),
                         (S_PLAY, self.s_play)):
            e.stub(addr, fn)

    def emit(self, line):
        self.out.append(line)

    def sym(self, v):
        v &= M32
        if v == 0:
            return "0"
        return self.names.get(v, "?")

    def mgr_ok(self, em):
        return "" if em.reg[4] & M32 == self.speech else " ?mgr"

    # ---- stubs

    def s_speaker(self, em):
        self.emit("  speaker %s -> %08x" % (self.sym(em.reg[4]), self.spk))
        return self.spk

    def s_rotorreq(self, em):
        self.emit("  speech rotor_request%s %08x %d" % (
            self.mgr_ok(em), em.reg[5] & M32, s32(em.reg[6])))

    def s_rotorconf(self, em):
        self.emit("  speech rotor_confirm%s" % self.mgr_ok(em))

    def s_helina(self, em):
        self.emit("  speech heli_na%s %08x" % (self.mgr_ok(em),
                                               em.reg[5] & M32))

    def s_abort(self, em):
        self.emit("  abort %s" % self.sym(em.reg[4]))

    def s_follow(self, em):
        self.emit("  follow %s %s" % (self.sym(em.reg[4]),
                                      self.sym(em.reg[5])))
        return 1

    def s_attack(self, em):
        self.emit("  attack %s %d" % (self.sym(em.reg[4]), s32(em.reg[5])))
        return 1

    def s_random(self, em):
        ok = "" if em.reg[4] & M32 == self.world else " ?w"
        if self.randqi < len(self.randq):
            r = self.randq[self.randqi]
            self.randqi += 1
        else:
            r = self.rand
        self.emit("  random%s %d -> %d" % (ok, s32(em.reg[5]), r))
        return r & M32

    def s_sample(self, em):
        b = self.e.read(em.reg[4] & M32, 32).split(b"\0")[0]
        r = self.smp if self.sample else 0
        self.emit("  sample %s -> %s" % (b.decode("latin-1"), self.sym(r)))
        return r

    def s_play(self, em):
        self.emit("  play %s %08x %08x %08x" % (
            self.sym(em.reg[4]), em.fpr[12] & M32, em.fpr[13] & M32,
            em.fpr[14] & M32))

    # ---- dumps

    def pdump(self, k):
        e = self.e
        p = self.ps[k]
        self.emit("U%d chopper %s %s" % (
            k, self.sym(e.u32(p + P_CHOPPER)),
            " ".join("%s %08x" % (n, e.u32(p + o)) for n, o in P_WORDS)))

    def mdump(self):
        e = self.e
        self.emit("M busy %d attacks %d salvos %s" % (
            s32(e.u32(self.m + 312)), s32(e.u32(self.m + 10492)),
            " ".join(str(s32(e.u32(h + H_SALVOS))) for h in self.hs)))

    # ---- ops

    def idx(self, lst, s):
        k = int(s, 0)
        return lst[k] if k >= 0 else 0

    def run(self, a):
        e = self.e
        o = a[0]
        v = lambda j: int(a[j], 0) & M32        # noqa: E731
        call = lambda f, *args: e.call(f, *args, limit=200000)  # noqa
        if o == "rp":
            e.put32(RP + RP_FIELDS[a[1]], v(2))
        elif o == "dt":
            e.put32(G_DT, v(1))
        elif o == "world":
            e.put32(self.world + 24, self.idx(self.hs, a[1]))
        elif o == "m":
            e.put32(self.m + MFIELDS[a[1]], v(2))
        elif o == "mcop":
            e.put32(self.m + 16 + 4 * int(a[1]), self.idx(self.cops, a[2]))
        elif o == "cop":
            e.put32(self.cops[int(a[1])], self.idx(self.ps, a[2]))
        elif o == "car":
            c = self.cars[int(a[1])]
            e.put32(c + CAR_POS, v(2))
            e.put32(c + CAR_POS + 4, v(3))
            e.write(c + CAR_BLOWN, bytes([v(4) & 0xff]))
        elif o == "h":
            h = self.hs[int(a[1])]
            e.put32(h + H_CAR, self.idx(self.cars, a[2]))
            e.put32(h + H_TYPE, v(3))
            e.put32(h + H_SALVOS, v(4))
            e.put32(h + H_POS, v(5))
            e.put32(h + H_POS + 4, v(6))
            e.put32(h + H_N960, v(7))
        elif o == "p":
            p = self.ps[int(a[1])]
            e.put32(p + P_CHASED, self.idx(self.cars, a[2]))
            e.put32(p + P_RB, self.rb if v(3) else 0)
            e.put32(p + P_CHOPPER, self.idx(self.hs, a[4]))
            for j, (n, off) in enumerate(P_WORDS):
                e.put32(p + off, v(5 + j))
        elif o == "spk":
            self.spk = v(1)
        elif o == "randq":
            self.randq = [s32(v(j)) for j in range(1, len(a))][:RANDQ]
            self.randqi = 0
        elif o == "rand":
            self.rand = s32(v(1))
        elif o == "sample":
            self.sample = v(1)
        elif o == "upd":
            k = int(a[1])
            call(F_UPDATE, self.ps[k])
            self.emit("upd U%d" % k)
            self.pdump(k)
            self.mdump()
        elif o == "avail":
            self.emit("avail -> %d" % call(F_AVAIL, self.m))
        elif o == "req":
            r = call(F_REQ, self.m)
            self.emit("req -> %s" % self.sym(r))
            self.mdump()
        elif o in ("bacrc", "bacrr"):
            call(F_BACRC if o == "bacrc" else F_BACRR, self.m)
            self.emit(o)
            for k in range(NP):
                self.pdump(k)
            self.mdump()
        elif o == "near":
            k = int(a[1])
            self.emit("near U%d -> %d" % (k, call(F_NEAR, self.ps[k])))
        else:
            raise ValueError(o)


def model(lines):
    m = Model()
    for ln in lines:
        m.run(ln.split("|"))
    return m.out


# ================================================================ the script

def pset(k, chased=0, rb=0, chopper=0, timer=0.0, nxt=12.0, d=0.0,
         state=0, flags=0):
    return "p|%d|%d|%d|%d|%s|%s|%s|%d|0x%x" % (
        k, chased, rb, chopper, F(timer), F(nxt), F(d), state, flags)


def hset(k, car=0, typ=1, salvos=3, x=0.0, y=0.0, n960=0):
    return "h|%d|%d|%d|%d|%s|%s|%d" % (k, car, typ, salvos, F(x), F(y),
                                       n960)


def base():
    return ["rp|New624|1", "rp|BeACop|0", "dt|%s" % F(0.033333335),
            "world|0", "m|busy|0", "m|attacks|0", "m|nrb|0",
            "m|pcidx|0", "mcop|0|0", "m|beacopid|0x7", "m|super|0",
            "cop|0|0", "car|0|%s|%s|0" % (F(10.0), F(20.0)),
            "car|1|%s|%s|0" % (F(-50.0), F(75.0)),
            hset(0), hset(1, car=1), "spk|0x3", "rand|0", "randq",
            "sample|1"]


def manager_cases():
    out = []
    # IsChopperAvailable and RequestChopper over every gate.
    for world in (-1, 0):
        for n624 in (0, 1):
            for n960 in (0, 1):
                for busy in (0, 1):
                    for beacop in (0, 1):
                        for attacks in (0, 1, 2, -1):
                            out += base() + [
                                "world|%d" % world, "rp|New624|%d" % n624,
                                hset(0, n960=n960), "m|busy|%d" % busy,
                                "rp|BeACop|%d" % beacop,
                                "m|attacks|%d" % attacks, "avail", "req"]
    # Be A Cop's requests.
    for which, flag in (("bacrc", 0x20), ("bacrr", 0x8)):
        for chase in (-1, 0, 1):
            for has in (0, 1):
                # 0x10 and 0x401: the bits the requests leave alone.
                for flags in (0, flag, 0x1e0 ^ flag, 0xffffffff, 0x10,
                              0x401):
                    for attacks, nrb in ((0, 0), (0, 1), (1, 0), (3, 3)):
                        for sample in (0, 1):
                            out += base() + [
                                "cop|0|%d" % chase,
                                pset(0, chopper=0 if has else -1,
                                     rb=has, flags=flags),
                                pset(1, chopper=-1, flags=0),
                                "m|attacks|%d" % attacks,
                                "m|nrb|%d" % nrb,
                                "sample|%d" % sample, which]
    # The player cop by its index.
    for pcidx in (0, 1, 2):
        out += base() + ["mcop|1|1", "mcop|2|2", "cop|1|1", "cop|2|-1",
                         pset(0, chopper=-1), pset(1, chopper=-1),
                         "m|pcidx|%d" % pcidx, "m|attacks|1", "m|nrb|1",
                         "bacrc", "bacrr"]
    return out


def request_cases():
    """UpdateChopper with no helicopter yet: the request's gates."""
    out = []
    for flags in (0, 0x20, 0x1e0, 0xffffffdf):
        for world in (-1, 0):
            for busy in (0, 1):
                for beacop in (0, 1):
                    for attacks in (0, 2):
                        for sup in (0.0, 0.001, -0.001, 0.0010001, -5.0):
                            out += base() + [
                                "world|%d" % world, "m|busy|%d" % busy,
                                "rp|BeACop|%d" % beacop,
                                "m|attacks|%d" % attacks,
                                "m|super|%s" % F(sup),
                                "spk|0x%x" % (attacks + 2),
                                pset(0, chopper=-1, flags=flags,
                                     timer=3.0), "upd|0"]
    # The egg's helicopter is left alone, whatever the state.
    for state in (0, 1, 2, 3):
        out += base() + [hset(0, n960=1),
                         pset(0, chopper=0, state=state, timer=-1.0,
                              d=-1.0, flags=0x1e0), "upd|0"]
    return out


def timer_cases():
    """The states' run-out, and the abort."""
    out = []
    dts = (0.0, 0.033333335, 0.1, 0.5, -0.1)
    for state in (0, 1, 2, 3, 4, -1):
        for chopper in (-1, 0):
            if state in (2, 3) and chopper < 0:
                continue
            for timer in (0.0, 0.01, 0.0333, 0.2, -0.5, 10.0):
                for dt in dts:
                    for d in (0.0, -1.0, 1.0):
                        for beacop in (0, 1):
                            out += base() + [
                                "rp|BeACop|%d" % beacop, "dt|%s" % F(dt),
                                pset(0, chopper=chopper, state=state,
                                     timer=timer, d=d, nxt=12.0,
                                     flags=0), "upd|0"]
    # fChopperNextAttackTime's floor.
    for nxt in (12.0, 8.0, 8.000001, 7.9999995, 6.0, 4.0, 0.0, -3.0):
        out += base() + [pset(0, chopper=0, state=3, timer=-0.1, nxt=nxt),
                         "upd|0"]
    return out


def attack_cases():
    out = []
    for flags in (0, 0x40, 0x80, 0x100, 0xc0, 0x140, 0x180, 0x1c0, 0x1e0,
                  0xfffffe3f):
        for blown in (0, 1, 0x80, 0x0f):
            for typ in (0, 1, 2, 3):
                for rq in ((0, 0, 0), (1, 0, 0), (1, 1, 0), (1, 1, 1),
                           (0, 1, 1), (1, 0, 1)):
                    for same in (0, 1):
                        out += base() + [
                            "car|0|%s|%s|%d" % (F(1.0), F(2.0), blown),
                            hset(0, car=0 if same else 1, typ=typ),
                            "randq|%d|%d|%d" % rq, "rand|7",
                            pset(0, chopper=0, state=3, timer=-0.01,
                                 flags=flags), "upd|0"]
    return out


def near_cases(rng):
    out = []
    for state in (0, 1, 2, 3):
        for chopper in (-1, 0):
            for x, y in ((10.0, 20.0), (210.0, 20.0), (10.0, 220.0),
                         (10.0, 219.99998), (10.0, 220.00002),
                         (151.42136, 161.42136), (-190.0, 20.0)):
                out += base() + [hset(0, x=x, y=y),
                                 pset(0, chopper=chopper, state=state),
                                 "near|0"]
    for _ in range(200):
        x, y = rng.uniform(-400, 400), rng.uniform(-400, 400)
        out += [hset(0, x=x, y=y), "car|0|%s|%s|0" % (
            F(rng.uniform(-300, 300)), F(rng.uniform(-300, 300))),
            pset(0, chopper=0, state=3), "near|0"]
    return out


def chase_runs(rng):
    """Chases over time: a request, the flight, the attacks and the
    car's tyres and the helicopter's car changing on the way."""
    out = []
    for run in range(40):
        beacop = rng.randrange(2)
        out += base() + ["rp|BeACop|%d" % beacop,
                         "m|attacks|%d" % rng.randrange(4),
                         "m|busy|%d" % (rng.random() < 0.15),
                         "m|super|%s" % F(rng.choice((0.0, 2.0, -0.0005))),
                         hset(0, car=rng.choice((0, 1, -1)),
                              typ=rng.randrange(5)),
                         pset(0, chased=0, chopper=-1,
                              flags=rng.choice((0x20, 0x1e0, 0x60, 0xa0,
                                                0x120, 0)),
                              nxt=rng.choice((12.0, 9.0, 7.0)))]
        for step in range(rng.randrange(60, 200)):
            if rng.random() < 0.05:
                out.append("car|0|%s|%s|%d" % (
                    F(1.0), F(2.0), rng.choice((0, 0, 1, 0x80))))
            if rng.random() < 0.05:
                out.append(hset(0, car=rng.choice((0, 0, 1, -1)),
                                typ=rng.randrange(5)))
            if rng.random() < 0.1:
                out.append("randq|" + "|".join(
                    str(rng.randrange(2)) for _ in range(3)))
            out.append("dt|%s" % F(rng.choice((0.033333335, 0.1, 0.5,
                                               2.0))))
            out.append("upd|0")
    return out


def script():
    return (manager_cases() + request_cases() + timer_cases()
            + attack_cases() + near_cases(random.Random(0x7a))
            + chase_runs(random.Random(0x7b)))


# ================================================================= running

def build_harness(tmp, name="pursuitchopper_test"):
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


def write_inputs(d):
    lines = script()
    sc = Path(d) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    return lines, sc


# ============================================================= mutations

P = PCH
MUTATIONS = [
    # ---- IsChopperAvailable
    ("av_world", P, "    if (h == NULL || TheRaceParameters.New624 == 0 "
     "|| h->New960 != 0)", "    if (TheRaceParameters.New624 == 0 "
     "|| h->New960 != 0)"),
    ("av_624", P, "TheRaceParameters.New624 == 0 || h->New960 != 0)",
     "TheRaceParameters.New624 != 0 || h->New960 != 0)"),
    ("av_960", P, "|| h->New960 != 0)\n        return 0;",
     "|| h->New960 == 0)\n        return 0;"),
    ("av_busy", P, "    return m->bChopperBusy == 0;",
     "    return m->bChopperBusy != 0;"),
    ("av_one", P, "    return m->bChopperBusy == 0;", "    return 1;"),
    # ---- RequestChopper
    ("rq_world", P, "    if (h == NULL || TheRaceParameters.New624 == 0 "
     "|| m->bChopperBusy != 0)", "    if (TheRaceParameters.New624 == 0 "
     "|| m->bChopperBusy != 0)"),
    ("rq_624", P, "TheRaceParameters.New624 == 0 || m->bChopperBusy != 0)",
     "TheRaceParameters.New624 != 0 || m->bChopperBusy != 0)"),
    ("rq_busy", P, "|| m->bChopperBusy != 0)\n        return NULL;",
     ")\n        return NULL;"),
    ("rq_beacop", P, "    if (TheRaceParameters.BeACop != 0 "
     "&& m->nBeACopNumChopperAttacks == 0)\n        return NULL;",
     "    if (m->nBeACopNumChopperAttacks == 0)\n        return NULL;"),
    ("rq_beacop_not", P, "    if (TheRaceParameters.BeACop != 0 "
     "&& m->nBeACopNumChopperAttacks == 0)",
     "    if (TheRaceParameters.BeACop == 0 "
     "&& m->nBeACopNumChopperAttacks == 0)"),
    ("rq_attacks", P, "&& m->nBeACopNumChopperAttacks == 0)\n        "
     "return NULL;", "&& m->nBeACopNumChopperAttacks < 0)\n        "
     "return NULL;"),
    ("rq_set_busy", P, "    m->bChopperBusy = 1;\n", ""),
    ("rq_dec_test", P, "    if (m->nBeACopNumChopperAttacks != 0)\n"
     "        m->nBeACopNumChopperAttacks--;",
     "    if (m->nBeACopNumChopperAttacks > 0)\n"
     "        m->nBeACopNumChopperAttacks--;"),
    ("rq_dec_beacop", P, "    if (m->nBeACopNumChopperAttacks != 0)\n"
     "        m->nBeACopNumChopperAttacks--;",
     "    if (TheRaceParameters.BeACop != 0)\n"
     "        m->nBeACopNumChopperAttacks--;"),
    ("rq_no_dec", P, "        m->nBeACopNumChopperAttacks--;\n", ""),
    # ---- the samples and the player cop
    ("ps_volume", P, "gSamplePlayFn(s, 1.0f, 0.0f, 0.0f);",
     "gSamplePlayFn(s, 0.5f, 0.0f, 0.0f);"),
    ("ps_null", P, "    if (s != NULL && gSamplePlayFn != NULL)",
     "    if (gSamplePlayFn != NULL)"),
    ("pc_ptr", P, "    return c != NULL ? c->pMyPursuit : NULL;",
     "    return NULL;"),
    # ---- BeACopRequestChopper
    ("bc_none", P, "    if (p != NULL && p->pChopper == NULL\n"
     "        && (p->BehaviourFlags & BEHAVE_CHOPPER) == 0) {",
     "    if (p != NULL\n"
     "        && (p->BehaviourFlags & BEHAVE_CHOPPER) == 0) {"),
    ("bc_flag", P, "        && (p->BehaviourFlags & BEHAVE_CHOPPER) == 0) {",
     "        && (p->BehaviourFlags & BEHAVE_ROCKET) == 0) {"),
    ("bc_flag_not", P,
     "        && (p->BehaviourFlags & BEHAVE_CHOPPER) == 0) {",
     "        && (p->BehaviourFlags & BEHAVE_CHOPPER) != 0) {"),
    ("bc_set", P, "        p->BehaviourFlags |= BEHAVE_BEACOP_CHOPPER;",
     "        p->BehaviourFlags |= BEHAVE_CHOPPER;"),
    ("bc_set_eq", P, "        p->BehaviourFlags |= BEHAVE_BEACOP_CHOPPER;",
     "        p->BehaviourFlags = BEHAVE_BEACOP_CHOPPER;"),
    ("bc_count", P, "        if (m->nBeACopNumChopperAttacks != 0)\n"
     "            name = \"BeACopRequestOk\";",
     "        if (m->nBeACopNumChopperAttacks > 1)\n"
     "            name = \"BeACopRequestOk\";"),
    ("bc_count_rb", P, "        if (m->nBeACopNumChopperAttacks != 0)\n"
     "            name = \"BeACopRequestOk\";",
     "        if (m->nBeACopNumRoadBlocks != 0)\n"
     "            name = \"BeACopRequestOk\";"),
    # ---- BeACopRequestRoadBlock
    ("br_none", P, "    if (p != NULL && p->pRoadBlock == NULL\n",
     "    if (p != NULL\n"),
    ("br_flag", P, "        && (p->BehaviourFlags & BEHAVE_ROAD_BLOCK) == 0) {",
     "        && (p->BehaviourFlags & BEHAVE_BEACOP_ROAD) == 0) {"),
    ("br_set", P, "        p->BehaviourFlags |= BEHAVE_BEACOP_ROAD;",
     "        p->BehaviourFlags |= BEHAVE_ROAD_BLOCK;"),
    ("br_count", P, "        if (m->nBeACopNumRoadBlocks != 0)\n",
     "        if (m->nBeACopNumRoadBlocks == 0)\n"),
    ("br_count_ch", P, "        if (m->nBeACopNumRoadBlocks != 0)\n",
     "        if (m->nBeACopNumChopperAttacks != 0)\n"),
    # ---- the attack
    ("pa_spike_flag", P, "    if ((flags & BEHAVE_SPIKE_BELT) != 0 && whole",
     "    if ((flags & BEHAVE_ROCKET) != 0 && whole"),
    ("pa_spike_whole", P, "    if ((flags & BEHAVE_SPIKE_BELT) != 0 && whole",
     "    if ((flags & BEHAVE_SPIKE_BELT) != 0"),
    ("pa_spike_rand", P, "        && world_random_i(pCurrentWorld, 2) == 0)\n"
     "        return CHOPATTACK_SPIKE_BELT;",
     "        && world_random_i(pCurrentWorld, 2) != 0)\n"
     "        return CHOPATTACK_SPIKE_BELT;"),
    ("pa_spike_type", P, "        return CHOPATTACK_SPIKE_BELT;",
     "        return CHOPATTACK_4;"),
    ("pa_rocket_last", P, "    if (p->pChopper->BombRunType != "
     "CHOPATTACK_ROCKET\n", "    if (p->pChopper->BombRunType == "
     "CHOPATTACK_ROCKET\n"),
    ("pa_rocket_last_off", P, "    if (p->pChopper->BombRunType != "
     "CHOPATTACK_ROCKET\n        && (flags", "    if (1\n        && (flags"),
    ("pa_rocket_flag", P, "        && (flags & BEHAVE_ROCKET) != 0 && whole",
     "        && (flags & BEHAVE_SPIKE_BELT) != 0 && whole"),
    ("pa_rocket_whole", P, "        && (flags & BEHAVE_ROCKET) != 0 && whole",
     "        && (flags & BEHAVE_ROCKET) != 0"),
    ("pa_rocket_rand", P, "        && world_random_i(pCurrentWorld, 2) == 0)\n"
     "        return CHOPATTACK_ROCKET;",
     "        && world_random_i(pCurrentWorld, 2) != 0)\n"
     "        return CHOPATTACK_ROCKET;"),
    ("pa_rocket_type", P, "        return CHOPATTACK_ROCKET;",
     "        return CHOPATTACK_SMOKE_BOMB_1;"),
    ("pa_sb2_flag", P, "    if ((flags & BEHAVE_SMOKE_BOMB_2) != 0)",
     "    if ((flags & BEHAVE_SMOKE_BOMB_2) == 0)"),
    ("pa_sb2_rand", P, "        return world_random_i(pCurrentWorld, 2) != 0\n",
     "        return world_random_i(pCurrentWorld, 2) == 0\n"),
    ("pa_sb2_range", P, "        return world_random_i(pCurrentWorld, 2) != 0\n",
     "        return world_random_i(pCurrentWorld, 3) != 0\n"),
    ("pa_sb2_type", P, "            ? CHOPATTACK_SMOKE_BOMB_2 : "
     "CHOPATTACK_SMOKE_BOMB_1;", "            ? CHOPATTACK_SMOKE_BOMB_1 : "
     "CHOPATTACK_SMOKE_BOMB_1;"),
    ("pa_default", P, "    return CHOPATTACK_SMOKE_BOMB_1;\n}",
     "    return CHOPATTACK_SMOKE_BOMB_2;\n}"),
    ("pa_whole_u8", P, "    int32_t  whole = (int8_t)p->pChasedCar->"
     "BlownTireBits == 0;", "    int32_t  whole = (p->pChasedCar->"
     "BlownTireBits & 0x7f) == 0;"),
    ("pa_rand_world", P, "    if ((flags & BEHAVE_SPIKE_BELT) != 0 && whole\n"
     "        && world_random_i(pCurrentWorld, 2) == 0)",
     "    if ((flags & BEHAVE_SPIKE_BELT) != 0 && whole\n"
     "        && world_random_i(NULL, 2) == 0)"),
    # ---- UpdateChopper: the egg and the request
    ("up_egg", P, "        if (p->pChopper->New960 != 0)\n            return;",
     "        if (p->pChopper->New960 == 0)\n            return;"),
    ("up_egg_off", P, "        if (p->pChopper->New960 != 0)\n            "
     "return;\n", ""),
    ("up_req_flag", P, "    } else if ((p->BehaviourFlags & BEHAVE_CHOPPER) "
     "!= 0\n", "    } else if ((p->BehaviourFlags & BEHAVE_SMOKE_BOMB_2) "
     "!= 0\n"),
    ("up_req_avail", P, "               && tcopmanager_is_chopper_available"
     "(pCopManager)) {", "               ) {"),
    ("up_sup_le", P, "fabsf(pCopManager->fSupervisorTimer) <= "
     "SUPERVISOR_NEAR;", "fabsf(pCopManager->fSupervisorTimer) < "
     "SUPERVISOR_NEAR;"),
    ("up_sup_abs", P, "fabsf(pCopManager->fSupervisorTimer) <= "
     "SUPERVISOR_NEAR;", "pCopManager->fSupervisorTimer <= "
     "SUPERVISOR_NEAR;"),
    ("up_sup_val", P, "#define SUPERVISOR_NEAR        0.001f",
     "#define SUPERVISOR_NEAR        0.0011f"),
    ("up_spk", P, "            gSpeechRaiseRotorRequestFn(spk, sup);",
     "            gSpeechRaiseRotorRequestFn(spk + 1, sup);"),
    ("up_no_rotor", P, "            gSpeechRaiseRotorRequestFn(spk, sup);\n",
     ""),
    ("up_req_state", P, "        p->ChopperState = ECS_CHOPPER_REQUESTED;\n"
     "        p->fChopperAttackTimer = REQUEST_TIME;",
     "        p->ChopperState = ECS_CHOPPER_INFLIGHT;\n"
     "        p->fChopperAttackTimer = REQUEST_TIME;"),
    ("up_req_time", P, "#define REQUEST_TIME           10.0f",
     "#define REQUEST_TIME           9.0f"),
    ("up_req_timer", P, "        p->ChopperState = ECS_CHOPPER_REQUESTED;\n"
     "        p->fChopperAttackTimer = REQUEST_TIME;\n",
     "        p->ChopperState = ECS_CHOPPER_REQUESTED;\n"),
    ("up_req_call", P, "        p->pChopper = tcopmanager_request_chopper"
     "(pCopManager);", "        p->pChopper = pCurrentWorld->Helicopter;"),
    ("up_salvos", P, "            p->pChopper->TotalSalvos = 0;",
     "            p->pChopper->TotalSalvos = 1;"),
    ("up_salvos_off", P, "        if (p->pChopper != NULL)\n"
     "            p->pChopper->TotalSalvos = 0;\n", ""),
    ("up_beacop", P, "        if (TheRaceParameters.BeACop != 0)\n"
     "            p->BehaviourFlags &= ~BEHAVE_CHOPPER;",
     "        if (TheRaceParameters.BeACop == 0)\n"
     "            p->BehaviourFlags &= ~BEHAVE_CHOPPER;"),
    ("up_beacop_bits", P, "            p->BehaviourFlags &= ~BEHAVE_CHOPPER;",
     "            p->BehaviourFlags &= ~BEHAVE_BEACOP_CHOPPER;"),
    # ---- the abort
    ("up_none", P, "    if (p->ChopperState == ECS_NO_CHOPPER)\n        return;",
     "    if (p->ChopperState == ECS_CHOPPER_ATTACKING)\n        return;"),
    ("up_none_off", P, "    if (p->ChopperState == ECS_NO_CHOPPER)\n"
     "        return;\n", ""),
    ("ab_dir", P, "    if (p->fChaseDirection == -1.0f\n",
     "    if (p->fChaseDirection != -1.0f\n"),
    ("ab_dir_le", P, "    if (p->fChaseDirection == -1.0f\n",
     "    if (p->fChaseDirection <= 0.0f\n"),
    ("ab_req", P, "        && p->ChopperState != ECS_CHOPPER_REQUESTED) {",
     "        && p->ChopperState != ECS_CHOPPER_INFLIGHT) {"),
    ("ab_call", P, "        chopper_abort_bombing_run(p->pChopper);\n", ""),
    ("ab_state", P, "        chopper_abort_bombing_run(p->pChopper);\n"
     "        p->ChopperState = ECS_CHOPPER_INFLIGHT;",
     "        chopper_abort_bombing_run(p->pChopper);\n"
     "        p->ChopperState = ECS_CHOPPER_ATTACKING;"),
    ("ab_timer", P, "        p->ChopperState = ECS_CHOPPER_INFLIGHT;\n"
     "        p->fChopperAttackTimer = REQUEST_TIME;\n    }",
     "        p->ChopperState = ECS_CHOPPER_INFLIGHT;\n    }"),
    # ---- the timer
    ("tm_sub", P, "    p->fChopperAttackTimer -= WorldTimeElapsed;",
     "    p->fChopperAttackTimer += WorldTimeElapsed;"),
    ("tm_off", P, "    p->fChopperAttackTimer -= WorldTimeElapsed;\n", ""),
    ("tm_lt", P, "    if (!(p->fChopperAttackTimer < 0.0f))",
     "    if (!(p->fChopperAttackTimer <= 0.0f))"),
    ("tm_ge", P, "    if (!(p->fChopperAttackTimer < 0.0f))",
     "    if (p->fChopperAttackTimer > 0.0f)"),
    # ---- REQUESTED
    ("rs_has", P, "    case ECS_CHOPPER_REQUESTED:\n        if (p->pChopper "
     "!= NULL) {", "    case ECS_CHOPPER_REQUESTED:\n        if (p->pChopper "
     "== NULL) {"),
    ("rs_confirm", P, "                gSpeechRaiseRotorConfirmFn();\n", ""),
    ("rs_state", P, "            p->ChopperState = ECS_CHOPPER_INFLIGHT;\n"
     "            p->fChopperAttackTimer = CONFIRM_TIME;",
     "            p->ChopperState = ECS_CHOPPER_ATTACKING;\n"
     "            p->fChopperAttackTimer = CONFIRM_TIME;"),
    ("rs_time", P, "#define CONFIRM_TIME           5.0f",
     "#define CONFIRM_TIME           4.0f"),
    ("rs_beacop", P, "        } else if (TheRaceParameters.BeACop != 0) {",
     "        } else if (TheRaceParameters.BeACop == 0) {"),
    ("rs_beacop_off", P, "        } else if (TheRaceParameters.BeACop != 0) {",
     "        } else {"),
    ("rs_na", P, "gSpeechRaiseDispatchHelicopterNAFn(pCopManager->BeACopId);",
     "gSpeechRaiseDispatchHelicopterNAFn(0);"),
    ("rs_na_off", P, "            if (gSpeechRaiseDispatchHelicopterNAFn "
     "!= NULL)\n                gSpeechRaiseDispatchHelicopterNAFn"
     "(pCopManager->BeACopId);\n", ""),
    ("rs_none", P, "            p->ChopperState = ECS_NO_CHOPPER;\n", ""),
    # ---- INFLIGHT
    ("if_time", P, "#define ATTACK_TIME            15.0f",
     "#define ATTACK_TIME            14.0f"),
    ("if_timer", P, "        p->fChopperAttackTimer = ATTACK_TIME;\n", ""),
    ("if_state", P, "        p->ChopperState = ECS_CHOPPER_ATTACKING;\n"
     "        chopper_follow_this_car", "        p->ChopperState = "
     "ECS_CHOPPER_INFLIGHT;\n        chopper_follow_this_car"),
    ("if_follow", P, "        p->ChopperState = ECS_CHOPPER_ATTACKING;\n"
     "        chopper_follow_this_car(p->pChopper, p->pChasedCar);",
     "        p->ChopperState = ECS_CHOPPER_ATTACKING;"),
    ("if_break", P, "        chopper_follow_this_car(p->pChopper, "
     "p->pChasedCar);\n        break;\n    case ECS_CHOPPER_ATTACKING",
     "        chopper_follow_this_car(p->pChopper, "
     "p->pChasedCar);\n    case ECS_CHOPPER_ATTACKING"),
    # ---- ATTACKING
    ("at_timer", P, "        p->fChopperAttackTimer = next;",
     "        p->fChopperAttackTimer = next - NEXT_ATTACK_STEP;"),
    ("at_step", P, "#define NEXT_ATTACK_STEP       2.0f",
     "#define NEXT_ATTACK_STEP       1.0f"),
    ("at_next_off", P, "        p->fChopperNextAttackTime = next - "
     "NEXT_ATTACK_STEP;\n", ""),
    ("at_min", P, "#define NEXT_ATTACK_MIN        6.0f",
     "#define NEXT_ATTACK_MIN        5.0f"),
    ("at_min_le", P, "        if (p->fChopperNextAttackTime < "
     "NEXT_ATTACK_MIN)", "        if (p->fChopperNextAttackTime <= "
     "NEXT_ATTACK_MIN + 0.5f)"),
    ("at_min_off", P, "            p->fChopperNextAttackTime = "
     "NEXT_ATTACK_MIN;\n", ""),
    ("at_car", P, "        if (p->pChopper->CurrentCar != p->pChasedCar)",
     "        if (p->pChopper->CurrentCar == p->pChasedCar)"),
    ("at_follow_car", P, "            chopper_follow_this_car(p->pChopper, "
     "p->pChasedCar);\n        else", "            chopper_follow_this_car("
     "p->pChopper, NULL);\n        else"),
    ("at_attack", P, "            chopper_attack_car(p->pChopper, type);",
     "            chopper_attack_car(p->pChopper, CHOPATTACK_SMOKE_BOMB_1);"),
    ("at_order", P, "        type = pick_attack(p);\n"
     "        if (p->pChopper->CurrentCar != p->pChasedCar)\n"
     "            chopper_follow_this_car(p->pChopper, p->pChasedCar);\n"
     "        else\n            chopper_attack_car(p->pChopper, type);",
     "        if (p->pChopper->CurrentCar != p->pChasedCar)\n"
     "            chopper_follow_this_car(p->pChopper, p->pChasedCar);\n"
     "        else\n            chopper_attack_car(p->pChopper, "
     "pick_attack(p));"),
    # ---- IsChopperNearCar
    ("nr_state", P, "    if (p->ChopperState != ECS_CHOPPER_ATTACKING || "
     "h == NULL)", "    if (p->ChopperState == ECS_NO_CHOPPER || h == NULL)"),
    ("nr_null", P, "    if (p->ChopperState != ECS_CHOPPER_ATTACKING || "
     "h == NULL)", "    if (p->ChopperState != ECS_CHOPPER_ATTACKING)"),
    ("nr_dy", P, "    dy = h->CurrentPos.y - car->State.Position.y;",
     "    dy = h->CurrentPos.y - car->State.Position.x;"),
    ("nr_dx", P, "    dx = h->CurrentPos.x - car->State.Position.x;",
     "    dx = car->State.Position.x;"),
    ("nr_le", P, "    return sqrtf(dx * dx + dy * dy) < NEAR_CAR;",
     "    return sqrtf(dx * dx + dy * dy) <= NEAR_CAR;"),
    ("nr_val", P, "#define NEAR_CAR               200.0f",
     "#define NEAR_CAR               150.0f"),
    ("nr_sq", P, "    return sqrtf(dx * dx + dy * dy) < NEAR_CAR;",
     "    return dx * dx + dy * dy < NEAR_CAR;"),
]

EQUIVALENT = {
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    indir = tempfile.TemporaryDirectory()
    lines, scp = write_inputs(indir.name)
    base_lines = model(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text(encoding="latin-1").splitlines()
        if diff(base_lines, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "pursuitchopper_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base_lines, diff, EQUIVALENT, jobs)
    indir.cleanup()
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

    with tempfile.TemporaryDirectory() as tmp:
        lines, scp = write_inputs(tmp)
        got = model(lines)
        exe = build_harness(tmp)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text(encoding="latin-1").splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(got) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(got, harness)
    print("%d ops, %d lines, %d differ" % (len(lines), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
