#!/usr/bin/env python3
"""Cross-check 3DS Files/source/fillerspeech.c, the chase's filler speech
(14-10b), against the retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own code: TryFillerSpeech (0x002315d0),
SayFillerSpeech (0x00231760), the nine filler classes' GetBank,
IsAppropriate, GetWeight and Speak (0x00231820 .. 0x00231d70) through
their vtables, tPursuit's IsCopNearChasedCar (0x0022bb28) and the
reckless test (0x0022bbb0). _GLOBAL_$I$FillerSpeechBanks (0x002317b0)
runs first to put the vtables in the objects that FillerSpeechBanks
(0x0031c658) points at. The harness (tools/src/fillerspeech_test.c) runs
the port and prints the same lines.

**The stubs**, logged and answered by the same rule on both sides:
tPursuit's IsChopperNearCar, GetSecondaryCopSpeaker, GetSpeedMPHOrKPH and
bRandom (each a queue, then an answer), GetCopSpeaker (a queue, then a
counter) and the nine raise functions. The race's traffic and Be A Cop,
the cars, the cops and the chases are memory both sides read.

**Compared** are the stubs' logs, IsCopNearChasedCar's answer, and
TryFillerSpeech's answer and the cookie after each call.

    python tools/fillerspeech_check.py
    python tools/fillerspeech_check.py --mutate [--only a,b]
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

HARNESS = "tools/src/fillerspeech_test.c"
FS = "3DS Files/source/fillerspeech.c"
SOURCES = [HARNESS, FS]
HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = retail_model.RETAIL_GP
RP = 0x0031a898                         # TheRaceParameters
RP_FIELDS = {"BeACop": 628, "Traffic": 16}
G_SPEECH = GP - 15624                   # the speech manager

F_TRY = 0x002315d0
F_SAY = 0x00231760
F_NEAR = 0x0022bb28
F_INIT = 0x002317b0                     # _GLOBAL_$I$FillerSpeechBanks

S_CHOPPER = 0x0022bab8
S_SPEAKER = 0x0022ab30
S_SECONDARY = 0x0022ab70
S_SPEED = 0x0022a220
S_RANDOM = 0x0025a488

# The raises: the address, the harness's name and the arguments after the
# manager, i an int register in turn and f a float one.
RAISES = (
    (0x0020afa8, "rotor_location", "i"),
    (0x0020afe8, "rotor_chatter", "i"),
    (0x0020b078, "rotor_traffic", ""),
    (0x0020ab80, "subject_location", "iii"),
    (0x0020ad40, "tactic_divert", "i"),
    (0x0020ad80, "tactic_cutoff", "i"),
    (0x0020b5d8, "current_speed", "if"),
    (0x0020adc0, "update_reckless", "ii"),
    (0x0020acf0, "tactic_hit", "ii"),
)

PURSUIT_SIZE, COP_SIZE, CAR_SIZE = 1600, 64, 2304
NP, NCOPS, NCARS, QN = 3, 4, 5, 16
P_CHASED, P_COPS, P_NCOPS, P_LM, P_FLAGS = 16, 28, 1476, 1504, 1588
COP_CAR = 4
CAR_POS, CAR_FWD, CAR_VELMAG = 96, 960, 964

# The banks in FillerSpeechBanks's order, and their weights.
BANKS = (1, 2, 4, 8, 32, 64, 128, 256, 16)
WEIGHTS = (4, 4, 4, 2, 2, 2, 2, 2, 5)


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def Fx(f):
    return "0x%08x" % fbits(f)


def Fn(f, ulps):
    """`f` moved `ulps` floats up (down for negative), as bits."""
    b = fbits(f)
    return "0x%08x" % ((b + ulps) & M32 if f >= 0 else (b - ulps) & M32)


# ================================================================== model

class Queue(object):
    def __init__(self):
        self.q, self.i, self.answer = [], 0, 0

    def fill(self, vals):
        self.q, self.i = vals[:QN], 0

    def next(self):
        if self.i < len(self.q):
            r = self.q[self.i]
            self.i += 1
            return r
        return self.answer


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
        self.speech = block(16, "SP")
        e.put32(G_SPEECH, self.speech)
        self.ps = [block(PURSUIT_SIZE, "U%d" % k) for k in range(NP)]
        self.cops = [block(COP_SIZE, None) for _ in range(NCOPS)]
        self.cars = [block(CAR_SIZE, None) for _ in range(NCARS)]
        self.cookie = block(16, None)
        self.chopq, self.spkq, self.secq = Queue(), Queue(), Queue()
        self.speedq, self.randq = Queue(), Queue()
        for addr, fn in ((S_CHOPPER, self.s_chopper),
                         (S_SPEAKER, self.s_speaker),
                         (S_SECONDARY, self.s_secondary),
                         (S_SPEED, self.s_speed),
                         (S_RANDOM, self.s_random)):
            e.stub(addr, fn)
        for addr, nm, args in RAISES:
            e.stub(addr, self.raiser(nm, args))
        e.call(F_INIT, limit=1000)

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

    def raiser(self, nm, args):
        def fn(em):
            ir, fr, vals = 5, 12, []
            for k in args:
                if k == "i":
                    vals.append("%d" % s32(em.reg[ir]))
                    ir += 1
                else:
                    vals.append("%08x" % (em.fpr[fr] & M32))
                    fr += 1
            self.emit("  %s%s%s" % (nm, self.mgr_ok(em),
                                    "".join(" " + v for v in vals)))
        return fn

    def s_chopper(self, em):
        r = s32(self.chopq.next())
        self.emit("  chopper %s -> %d" % (self.sym(em.reg[4]), r))
        return r

    def s_speaker(self, em):
        q = self.spkq
        if q.i < len(q.q):
            r = q.q[q.i]
            q.i += 1
        else:
            r = q.answer
            q.answer = (q.answer + 1) & M32
        self.emit("  speaker %s -> %08x" % (self.sym(em.reg[4]), r))
        return s32(r)

    def s_secondary(self, em):
        r = self.secq.next()
        self.emit("  secondary %s -> %08x" % (self.sym(em.reg[4]), r))
        return s32(r)

    def s_speed(self, em):
        r = self.speedq.next()
        self.emit("  speed %s -> %08x" % (self.sym(em.reg[4]), r))
        em.fpr[0] = r

    def s_random(self, em):
        r = s32(self.randq.next())
        self.emit("  random %d -> %d" % (s32(em.reg[4]), r))
        return r

    # ---- ops

    def run(self, a):
        e = self.e
        o = a[0]
        v = lambda j: int(a[j], 0) & M32        # noqa: E731
        qv = lambda: [v(j) for j in range(1, len(a))]   # noqa: E731
        if o == "rp":
            e.put32(RP + RP_FIELDS[a[1]], v(2))
        elif o == "car":
            c = self.cars[int(a[1])]
            for j in range(3):
                e.put32(c + CAR_POS + 4 * j, v(2 + j))
            e.put32(c + CAR_FWD, v(5))
            e.put32(c + CAR_VELMAG, v(6))
        elif o == "cop":
            e.put32(self.cops[int(a[1])] + COP_CAR, self.cars[int(a[2])])
        elif o == "p":
            p = self.ps[int(a[1])]
            e.put32(p + P_CHASED, self.cars[int(a[2])])
            e.put32(p + P_NCOPS, v(3))
            for j in range(2):
                k = int(a[4 + j], 0)
                e.put32(p + P_COPS + 4 * j, self.cops[k] if k >= 0 else 0)
            e.put32(p + P_LM, v(6))
            e.put32(p + P_FLAGS, v(7))
        elif o == "chopq":
            self.chopq.fill(qv())
        elif o == "chop":
            self.chopq.answer = v(1)
        elif o == "spkq":
            self.spkq.fill(qv())
        elif o == "spk":
            self.spkq.answer = v(1)
        elif o == "secq":
            self.secq.fill(qv())
        elif o == "sec":
            self.secq.answer = v(1)
        elif o == "speedq":
            self.speedq.fill(qv())
        elif o == "speed":
            self.speedq.answer = v(1)
        elif o == "randq":
            self.randq.fill(qv())
        elif o == "rand":
            self.randq.answer = v(1)
        elif o == "cookie":
            e.put32(self.cookie, v(1))
        elif o == "near":
            k = int(a[1])
            e.fpr[12] = v(2)
            r = e.call(F_NEAR, self.ps[k], limit=20000)
            self.emit("near U%d %08x -> %d" % (k, v(2), r))
        elif o == "try":
            k = int(a[1])
            r = e.call(F_TRY, self.ps[k], self.cookie, limit=200000)
            self.emit("try U%d -> %d cookie %08x"
                      % (k, r, e.u32(self.cookie)))
        elif o == "say":
            k = int(a[1])
            e.call(F_SAY, self.ps[k], self.cookie, limit=400000)
            self.emit("say U%d cookie %08x" % (k, e.u32(self.cookie)))
        else:
            raise ValueError(o)


def model(lines):
    m = Model()
    for ln in lines:
        m.run(ln.split("|"))
    return m.out


# ================================================================ the script

def car(k, x=0.0, y=0.0, z=0.0, fwd=0.0, vel=0.0):
    f = lambda t: t if isinstance(t, str) else Fx(t)   # noqa: E731
    return "car|%d|%s|%s|%s|%s|%s" % (k, f(x), f(y), f(z), f(fwd), f(vel))


def pset(k, chased=0, ncops=1, c0=0, c1=-1, lm=0, flags=0):
    return "p|%d|%d|%d|%d|%d|%d|0x%x" % (k, chased, ncops, c0, c1, lm,
                                         flags & M32)


NONE = 5                                # COP_SPEAKER_NONE


def base():
    out = ["rp|BeACop|0", "rp|Traffic|%s" % Fx(0.5), "cookie|0",
           "chopq", "chop|0", "spkq", "spk|0x10", "secq", "sec|%d" % NONE,
           "speedq", "speed|%s" % Fx(80.0), "randq", "rand|0"]
    # The chased car at the origin; the cops' cars 1 .. 4 out along x.
    out.append(car(0, 0.0, 0.0, 0.0, 20.0, 20.0))
    for k in range(1, NCARS):
        out.append(car(k, 10.0 * k, 0.0, 0.0))
    for k in range(NCOPS):
        out.append("cop|%d|%d" % (k, k + 1))
    for k in range(NP):
        out.append(pset(k, ncops=0, c0=-1))
    return out


def near_cases(rng):
    """IsCopNearChasedCar: the cops, NULL or not, by count, and the
    distance against the bound to the float."""
    out = base()
    for ncops in (-1, 0, 1, 2, 0x80000000):
        for c0 in (-1, 0, 1):
            for c1 in (-1, 2, 0):
                out.append(pset(0, ncops=ncops, c0=c0, c1=c1))
                for d in (5.0, 10.0, 10.000001, 15.0, 20.0, 25.0, 30.0,
                          30.000002, 0.0, -1.0):
                    out.append("near|0|%s" % Fx(d))
    # Each axis, and the bound at and either side of the distance.
    out += [pset(0, ncops=2, c0=0, c1=1)]
    for ax in range(3):
        for dist in (3.0, 65.0, 40.0, 0.1):
            pos = [0.0, 0.0, 0.0]
            pos[ax] = dist
            out.append(car(1, *pos))
            out.append(car(2, 1000.0, 0.0, 0.0))
            for d in (Fx(dist), Fn(dist, 1), Fn(dist, -1), Fn(dist, 2)):
                out.append("near|0|%s" % d)
    # The order of the sum: (x*x + y*y) + z*z, then the root.
    for _ in range(600):
        p = [rng.uniform(-80, 80) for _ in range(3)]
        q = [rng.uniform(-80, 80) for _ in range(3)]
        out.append(car(0, *q, fwd=0.0, vel=0.0))
        out.append(car(rng.choice((1, 2)), *p))
        dx, dy, dz = [struct.unpack("<f", struct.pack("<f", a - b))[0]
                      for a, b in zip(p, q)]
        d = ((dx * dx + dy * dy) + dz * dz) ** 0.5
        for u in (-1, 0, 1):
            out.append("near|0|%s" % Fn(d, u))
    # Big and small: the sum's rounding, infinity and NaN.
    for x in (1e19, 1e-20, 3e38, float("inf")):
        out += [car(0, 0.0, 0.0, 0.0), car(1, x, x, -x),
                "near|0|%s" % Fx(1e30), "near|0|%s" % Fx(float("inf")),
                "near|0|0x7fc00000"]
    out += [car(1, "0x7fc00000", 0.0, 0.0), "near|0|%s" % Fx(1e30)]
    return out


def mask(i):
    """A cookie with every bank but the i-th said."""
    return 0x1ff & ~BANKS[i]


def class_cases():
    """Each class on its own: the cookie with the others' banks, so that
    only its test runs, over the inputs its test reads."""
    out = []
    near65 = (64.9, 65.0, Fn(65.0, -1), 70.0)
    for i in range(9):
        for chop in (0, 1, 2, -1):
            for lm in (0, 5, -1):
                for c0x in near65:
                    for ncops in (0, 1, 2, -1):
                        out += base() + [
                            "cookie|0x%x" % mask(i), "chop|%d" % chop,
                            car(1, c0x, 0.0, 0.0), "car|2|%s|0|0|0|0"
                            % Fx(39.0),
                            pset(0, ncops=ncops, c0=0, lm=lm, flags=4),
                            "try|0"]
    # The traffic.
    for traffic in (0.5, 0.9, Fn(0.9, 1), Fn(0.9, -1), 1.0, "0x7fc00000",
                    -1.0):
        for chop in (0, 1):
            t = traffic if isinstance(traffic, str) else Fx(traffic)
            out += base() + ["cookie|0x%x" % mask(1), "chop|%d" % chop,
                             "rp|Traffic|%s" % t, pset(0), "try|0"]
    # The chased car's forward speed and its speed.
    for fwd in (30.0, Fn(30.0, 1), Fn(30.0, -1), -40.0, 100.0,
                "0x7fc00000"):
        out += base() + ["cookie|0x%x" % mask(2), "chop|1",
                         car(0, 0.0, 0.0, 0.0, fwd=fwd), pset(0), "try|0"]
    for vel in ("0x420f0c79", "0x420f0c78", "0x420f0c7a", 0.0, 50.0,
                "0x7fc00000", -36.0):
        for c0x in (5.0, 70.0):
            out += base() + ["cookie|0x%x" % mask(6),
                             car(0, 0.0, 0.0, 0.0, fwd=1.0, vel=vel),
                             car(1, c0x, 0.0, 0.0), pset(0, ncops=1, c0=0),
                             "try|0"]
    # Be A Cop.
    for beacop in (0, 1, -1, 2):
        for i in (4, 8):
            out += base() + ["cookie|0x%x" % mask(i), "rp|BeACop|%d" % beacop,
                             "sec|1", car(1, 5.0, 0.0, 0.0),
                             pset(0, ncops=1, c0=0, flags=4), "try|0"]
    # The speed past 100.
    for sp in (100.0, Fn(100.0, 1), Fn(100.0, -1), 250.0, -150.0,
               "0x7fc00000", "0xff800000"):
        s = sp if isinstance(sp, str) else Fx(sp)
        out += base() + ["cookie|0x%x" % mask(5), "speedq|%s|%s" % (
            s, Fx(123.0)), car(1, 5.0, 0.0, 0.0), pset(0, ncops=1, c0=0),
            "try|0"]
    # The tactic hit: the flag, the speakers and 40.
    for flags in (0, 4, 0xfffffffb, 0xffffffff, 8, 0x14):
        for secq in ([NONE], [4, 4], [4, 0x10], [0x10, 0x10], [6, 7],
                     [NONE, 0x10], [0xffffffff, 0x10], [0, 0]):
            for c0x in (39.0, 40.0, Fn(40.0, -1), 50.0):
                out += base() + [
                    "cookie|0x%x" % mask(8),
                    "secq|" + "|".join(str(x) for x in secq), "sec|3",
                    car(1, c0x, 0.0, 0.0),
                    pset(0, ncops=1, c0=0, flags=flags), "try|0"]
    # The tactic: divert or cutoff by the draw.
    for r in (0, 1, -1, 2):
        out += base() + ["cookie|0x%x" % mask(4), "randq|0|%d" % r,
                         car(1, 5.0, 0.0, 0.0), pset(0, ncops=1, c0=0),
                         "try|0"]
    return out


def pick_cases():
    """Every class appropriate, and the draw over the weights: each value
    from below 0 to past the total, with some banks said."""
    out = []
    for cookie in (0, 0x1, 0x10, 0x18, 0x101, 0x1fe, 0xfffffe00, 0x80000000,
                   0x0f0, 0x1ef):
        total = sum(w for b, w in zip(BANKS, WEIGHTS) if not b & cookie)
        for r in list(range(-2, total + 3)) + [0x7fffffff, -0x80000000]:
            out += base() + [
                "cookie|0x%x" % cookie, "chop|1", "rp|Traffic|%s" % Fx(1.0),
                car(0, 0.0, 0.0, 0.0, fwd=40.0, vel=40.0),
                car(1, 5.0, 0.0, 0.0), "speed|%s" % Fx(120.0),
                "secq|4|4|4", "sec|3", "randq|%d|1" % r,
                pset(0, ncops=1, c0=0, lm=7, flags=4), "try|0"]
    return out


def say_cases():
    """SayFillerSpeech: something to say, nothing to say until the cookie
    empties, and nothing at all."""
    out = []
    for cookie in (0, 0x1ff, 0x1fe, 0xffffffff, 0x200, 0x100):
        for chop in (0, 1):
            for c0x in (5.0, 100.0):
                for r in (0, 3, 11, 100):
                    out += base() + [
                        "cookie|0x%x" % cookie, "chop|%d" % chop,
                        car(1, c0x, 0.0, 0.0), "rand|%d" % r,
                        pset(0, ncops=1, c0=0, lm=2), "say|0"]
    return out


def random_runs(rng):
    """Chases over time: the filler said on three chases with the cookie
    carried from one call to the next, and the world changing."""
    out = base()
    for k in range(NP):
        out.append(pset(k, chased=rng.randrange(NCARS), ncops=1, c0=k))
    for _ in range(4000):
        r = rng.random()
        if r < 0.10:
            out.append(car(rng.randrange(NCARS),
                           *[rng.uniform(-90, 90) for _ in range(3)],
                           fwd=rng.uniform(-10, 60), vel=rng.uniform(0, 60)))
        elif r < 0.13:
            out.append("cop|%d|%d" % (rng.randrange(NCOPS),
                                      rng.randrange(NCARS)))
        elif r < 0.18:
            out.append(pset(rng.randrange(NP), chased=rng.randrange(NCARS),
                            ncops=rng.choice((0, 1, 2, 2)),
                            c0=rng.randrange(-1, NCOPS),
                            c1=rng.randrange(-1, NCOPS),
                            lm=rng.choice((0, 0, 3, 9)),
                            flags=rng.choice((0, 4, 4, 0x1c))))
        elif r < 0.21:
            out.append("chopq|" + "|".join(
                str(rng.randrange(2)) for _ in range(rng.randrange(1, 6))))
        elif r < 0.23:
            out.append("chop|%d" % rng.randrange(2))
        elif r < 0.26:
            out.append("secq|" + "|".join(
                str(rng.choice((NONE, 0, 1, 2, 3, 0x10, 0x11)))
                for _ in range(rng.randrange(1, 6))))
        elif r < 0.28:
            out.append("sec|%d" % rng.choice((NONE, 1, 2)))
        elif r < 0.30:
            out.append("spk|%d" % rng.choice((0, 1, 2, 0x10)))
        elif r < 0.33:
            out.append("randq|" + "|".join(
                str(rng.randrange(30)) for _ in range(rng.randrange(1, 5))))
        elif r < 0.35:
            out.append("rand|%d" % rng.randrange(30))
        elif r < 0.37:
            out.append("speedq|" + "|".join(
                Fx(rng.uniform(60, 160)) for _ in range(2)))
        elif r < 0.39:
            out.append("rp|Traffic|%s" % Fx(rng.choice((0.5, 0.9, 1.0,
                                                         1.5))))
        elif r < 0.41:
            out.append("rp|BeACop|%d" % (rng.random() < 0.3))
        elif r < 0.43:
            out.append("cookie|0x%x" % rng.choice((0, 0x1ff, rng.randrange(
                0x200))))
        elif r < 0.47:
            out.append("near|%d|%s" % (rng.randrange(NP),
                                       Fx(rng.uniform(0, 120))))
        else:
            out.append("%s|%d" % (rng.choice(("say", "say", "try")),
                                  rng.randrange(NP)))
    return out


def script():
    return (near_cases(random.Random(0x14b)) + class_cases()
            + pick_cases() + say_cases()
            + random_runs(random.Random(0x14b0)))


# ================================================================= running

def build_harness(tmp, name="fillerspeech_test"):
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

S = FS


def _table_mutations():
    """Each row of kFillerBanks: its bank moved up a bit, its weight one
    either way, its test and its speech swapped with the next row's, and
    the row swapped with the next."""
    rows = [ln for ln in (ROOT / FS).read_text().splitlines()
            if ln.startswith("    {") and ln.rstrip().endswith("},")]
    cells = [[c.strip() for c in ln.strip()[1:-2].split(",")] for ln in rows]

    def row(c):
        return "    { %3s, %s, %-20s %-22s }," % (c[0], c[1], c[2] + ",",
                                                   c[3])
    assert [row(c) for c in cells] == rows, "kFillerBanks's layout moved"
    out = []
    for k, c in enumerate(cells):
        b = int(c[0])
        out.append(("tb-bank%d" % k, S, rows[k],
                    row([str(b << 1)] + c[1:])))
        for d, nm in ((1, "up"), (-1, "dn")):
            out.append(("tb-w%s%d" % (nm, k), S, rows[k],
                        row([c[0], str(int(c[1]) + d)] + c[2:])))
        if k + 1 == len(cells):
            continue
        n = cells[k + 1]
        both = rows[k] + NL + rows[k + 1]
        out.append(("tb-ok%d" % k, S, both, row(c[:2] + [n[2], c[3]]) + NL
                    + row(n[:2] + [c[2], n[3]])))
        if c[3] != n[3]:
            out.append(("tb-say%d" % k, S, both, row(c[:3] + [n[3]]) + NL
                        + row(n[:3] + [c[3]])))
        out.append(("tb-swap%d" % k, S, both, rows[k + 1] + NL + rows[k]))
    return out


MUTATIONS = _table_mutations() + [
    # ---- IsCopNearChasedCar
    ("nr-le", S, "+ dz * dz) < dist)", "+ dz * dz) <= dist)"),
    ("nr-sqrt", S, "sqrtf((dx * dx + dy * dy) + dz * dz) < dist",
     "((dx * dx + dy * dy) + dz * dz) < dist"),
    ("nr-assoc", S, "(dx * dx + dy * dy) + dz * dz",
     "dx * dx + (dy * dy + dz * dz)"),
    ("nr-noz", S, "(dx * dx + dy * dy) + dz * dz", "(dx * dx + dy * dy)"),
    ("nr-zy", S, "dz = a->z - b->z;", "dz = a->y - b->y;"),
    ("nr-yx", S, "dy = a->y - b->y;", "dy = a->x - b->x;"),
    ("nr-null", S, "            continue;\n        a = &c->pMyCar",
     "            break;\n        a = &c->pMyCar"),
    ("nr-bound", S, "i < p->nNumCops; i++", "i + 1 < p->nNumCops; i++"),
    ("nr-ret0", S, "            return 1;\n    }\n    return 0;",
     "            return 0;\n    }\n    return 0;"),
    ("nr-end1", S, "            return 1;\n    }\n    return 0;",
     "            return 1;\n    }\n    return 1;"),
    ("nr-chased", S, "b = &p->pChasedCar->State.Position;",
     "b = &p->Cops[0]->pMyCar->State.Position;"),
    # ---- the reckless test and the cops' 65
    ("rk-lt", S, "35.76218032836914f <= ", "35.76218032836914f < "),
    ("rk-val", S, "35.76218032836914f <= ", "35.762176513671875f <= "),
    ("rk-fwd", S, "<= p->pChasedCar->State.VelocityMagnitude",
     "<= p->pChasedCar->State.ForwardSpeed"),
    ("cc-66", S, "chased_car(p, 65.0f)", "chased_car(p, 66.0f)"),
    ("cc-64", S, "chased_car(p, 65.0f)", "chased_car(p, 64.0f)"),
    # ---- the helicopter's
    ("cm-ok1", S, "static int32_t chopper_misc_ok(const tPursuit *p)\n{\n"
     "    return tpursuit_is_chopper_near_car(p);",
     "static int32_t chopper_misc_ok(const tPursuit *p)\n{\n"
     "    return 1;"),
    ("cm-le", S, "30.0f < p->pChasedCar", "30.0f <= p->pChasedCar"),
    ("cm-31", S, "30.0f < p->pChasedCar", "31.0f < p->pChasedCar"),
    ("cm-vel", S, "p->pChasedCar->State.ForwardSpeed);",
     "p->pChasedCar->State.VelocityMagnitude);"),
    ("tr-le", S, "0.9f < TheRaceParameters", "0.9f <= TheRaceParameters"),
    ("tr-val", S, "0.9f < TheRaceParameters", "0.8f < TheRaceParameters"),
    ("tr-drop", S, "    return tpursuit_is_chopper_near_car(p)\n"
     "           && 0.9f < TheRaceParameters.TrafficDensity;",
     "    return tpursuit_is_chopper_near_car(p);"),
    ("tr-chop", S, "    return tpursuit_is_chopper_near_car(p)\n"
     "           && 0.9f < TheRaceParameters.TrafficDensity;",
     "    return 0.9f < TheRaceParameters.TrafficDensity;"),
    ("cl-lm", S, "    return tpursuit_is_chopper_near_car(p) && "
     "p->CurrentLandmark != 0;", "    return tpursuit_is_chopper_near_car"
     "(p);"),
    ("cl-chop", S, "    return tpursuit_is_chopper_near_car(p) && "
     "p->CurrentLandmark != 0;", "    return p->CurrentLandmark != 0;"),
    ("cl-loc", S, "speechmgr_get_instance(),\n"
     "                                   p->CurrentLandmark);",
     "speechmgr_get_instance(),\n                                   0);"),
    # ---- the cops'
    ("co-lm", S, "return cop_close(p) && p->CurrentLandmark != 0;",
     "return cop_close(p);"),
    ("co-loc", S, "p->CurrentLandmark, 0);", "0, 0);"),
    ("co-b", S, "p->CurrentLandmark, 0);", "p->CurrentLandmark, 1);"),
    ("co-spk", S, "                                                    "
     "speaker,\n", "                                                    "
     "0,\n"),
    ("ct-bac", S, "return cop_close(p) && TheRaceParameters.BeACop == 0;",
     "return cop_close(p);"),
    ("ct-close", S, "return cop_close(p) && TheRaceParameters.BeACop == 0;",
     "return TheRaceParameters.BeACop == 0;"),
    ("ct-swap", S, "if (bRandomI(2, bViewSeed) == 0)",
     "if (bRandomI(2, bViewSeed) != 0)"),
    ("ct-range", S, "if (bRandomI(2, bViewSeed) == 0)",
     "if (bRandomI(3, bViewSeed) == 0)"),
    ("cs-le", S, "100.0f < tpursuit_get_speed_mph_or_kph(p)",
     "100.0f <= tpursuit_get_speed_mph_or_kph(p)"),
    ("cs-val", S, "100.0f < tpursuit_get_speed_mph_or_kph(p)",
     "99.0f < tpursuit_get_speed_mph_or_kph(p)"),
    ("cs-close", S, "return cop_close(p) && 100.0f <",
     "return 1 && 100.0f <"),
    ("cs-order", S, "    uint32_t speaker = tpursuit_get_cop_speaker(p);\n\n"
     "    speechmgr_raise_current_speed(speechmgr_get_instance(), speaker,\n"
     "                                  tpursuit_get_speed_mph_or_kph(p));",
     "    float speed = tpursuit_get_speed_mph_or_kph(p);\n"
     "    uint32_t speaker = tpursuit_get_cop_speaker(p);\n\n"
     "    speechmgr_raise_current_speed(speechmgr_get_instance(), speaker,\n"
     "                                  speed);"),
    ("cr-drop", S, "return cop_close(p) && chased_car_reckless(p);",
     "return cop_close(p);"),
    ("cr-close", S, "return cop_close(p) && chased_car_reckless(p);",
     "return chased_car_reckless(p);"),
    ("cr-b", S, "tpursuit_get_cop_speaker(p), 0);",
     "tpursuit_get_cop_speaker(p), 1);"),
    ("cd-close", S, "static int32_t cop_direction_ok(const tPursuit *p)\n{\n"
     "    return cop_close(p);", "static int32_t cop_direction_ok(const "
     "tPursuit *p)\n{\n    return 1;"),
    # ---- the tactic hit
    ("th-flag", S, "(p->BehaviourFlags & 4u) == 0",
     "(p->BehaviourFlags & 8u) == 0"),
    ("th-noflag", S, "    if ((p->BehaviourFlags & 4u) == 0)\n"
     "        return 0;\n", ""),
    ("th-bac", S, "    if (TheRaceParameters.BeACop != 0)\n"
     "        return 0;\n    if (tpursuit_get_secondary",
     "    if (tpursuit_get_secondary"),
    ("th-none", S, "== COP_SPEAKER_NONE)", "== 4u)"),
    ("th-nonone", S, "    if (tpursuit_get_secondary_cop_speaker(p) == "
     "COP_SPEAKER_NONE)\n        return 0;\n", ""),
    ("th-same", S, "    if (speaker == tpursuit_get_secondary_cop_speaker"
     "(p))\n        return 0;\n", ""),
    ("th-order", S, "    speaker = tpursuit_get_cop_speaker(p);\n"
     "    if (speaker == tpursuit_get_secondary_cop_speaker(p))",
     "    speaker = tpursuit_get_secondary_cop_speaker(p);\n"
     "    if (speaker == tpursuit_get_cop_speaker(p))"),
    ("th-41", S, "chased_car(p, 40.0f)", "chased_car(p, 41.0f)"),
    ("th-ret1", S, "    return tpursuit_is_cop_near_chased_car(p, 40.0f);",
     "    return 1;"),
    ("th-say-order", S, "    uint32_t speaker = tpursuit_get_cop_speaker(p);"
     "\n\n    speechmgr_raise_tactic_hit(speechmgr_get_instance(), speaker,\n"
     "                               tpursuit_get_secondary_cop_speaker(p));",
     "    uint32_t target = tpursuit_get_secondary_cop_speaker(p);\n\n"
     "    speechmgr_raise_tactic_hit(speechmgr_get_instance(),\n"
     "                               tpursuit_get_cop_speaker(p), target);"),
    ("th-say-args", S, "    uint32_t speaker = tpursuit_get_cop_speaker(p);"
     "\n\n    speechmgr_raise_tactic_hit(speechmgr_get_instance(), speaker,\n"
     "                               tpursuit_get_secondary_cop_speaker(p));",
     "    uint32_t speaker = tpursuit_get_cop_speaker(p);\n"
     "    uint32_t target = tpursuit_get_secondary_cop_speaker(p);\n\n"
     "    speechmgr_raise_tactic_hit(speechmgr_get_instance(), target,\n"
     "                               speaker);"),
    # ---- TryFillerSpeech
    ("ty-nine", S, "for (i = 0; i < 9u; i++)", "for (i = 0; i < 8u; i++)"),
    ("ty-nomask", S, "        if ((f->bank & *cookie) != 0)\n"
     "            continue;\n", ""),
    ("ty-eqmask", S, "if ((f->bank & *cookie) != 0)",
     "if (f->bank == *cookie)"),
    ("ty-noapp", S, "        if (!f->appropriate(p))\n"
     "            continue;\n", ""),
    ("ty-total1", S, "total += f->weight;", "total += 1;"),
    ("ty-ret0", S, "    if (total == 0)\n        return 0;",
     "    if (total == 0)\n        return 1;"),
    ("ty-range", S, "bRandomI((int32_t)total, ", "bRandomI((int32_t)total - 1, "),
    ("ty-sum1", S, "    sum = 0;", "    sum = 1;"),
    ("ty-le", S, "if (r < sum) {", "if (r <= sum) {"),
    ("ty-signed", S, "if (r < sum) {", "if ((int32_t)r < (int32_t)sum) {"),
    ("ty-or", S, "*cookie |= cand[i]->bank;", "*cookie = cand[i]->bank;"),
    ("ty-noor", S, "            *cookie |= cand[i]->bank;\n", ""),
    ("ty-nobreak", S, "            break;\n        }\n    }\n    return 1;",
     "        }\n    }\n    return 1;"),
    ("ty-end0", S, "            break;\n        }\n    }\n    return 1;",
     "            break;\n        }\n    }\n    return 0;"),
    # ---- SayFillerSpeech
    ("sy-not", S, "    if (try_filler_speech(p, cookie))\n        return;",
     "    if (!try_filler_speech(p, cookie))\n        return;"),
    ("sy-keep", S, "    *cookie = 0;\n    try_filler_speech", "    "
     "try_filler_speech"),
    ("sy-one", S, "    *cookie = 0;\n    try_filler_speech",
     "    *cookie = 1;\n    try_filler_speech"),
    ("sy-once", S, "    *cookie = 0;\n    try_filler_speech(p, cookie);\n",
     "    *cookie = 0;\n"),
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
        todo, SOURCES, "fillerspeech_test",
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
