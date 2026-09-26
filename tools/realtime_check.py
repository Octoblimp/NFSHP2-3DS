#!/usr/bin/env python3
"""Cross-check 3DS Files/source/realtime.c against the image's clock object.

The clock object is nine functions at 0x001992a0 .. 0x001995d8 and the
eighteen globals at 0x00323cc8 .. 0x00323d0c: the video mode, the real
clock MainLoop prepares from the ticker and advances once a frame, and the
world clock it prepares from World::GetTimestep and advances with it. The
image is the oracle. tools/mipsemu.py runs the nine functions out of
NFSHP2.ELF, the harness (tools/src/realtime_test.c) runs the port, both
walk the same script, and the two transcripts are diffed.

Every op prints the eighteen globals after it, read out of the image's own
.sdata on the model side, so the port's initial values are held to the
image's too. The joylog is the image's Joylog::GetData and AddData on one
side and joylog.c on the other, each over a repeat that logs every call and
answers from the script's feed, as in joystick_check.

What the listing says that is easy to get wrong, and which the script
reaches:

  * NTSC's ceiling is 0x3d4cccce, one ulp above the float nearest 0.05.
  * The real step's rounding error is what the *timer* loses, in whole
    ticks of 0.00025 s, against the clamped step, and not what the
    quantisation loses. It goes into the next frame's step after the
    1.0167 scale, not before it.
  * Replaying, the loop count's four bits are read out of the log and
    dropped, and the step is not clamped.
  * AdvanceRealTime counts at least one frame a call, by `movn`: a
    negative count is kept. AdvanceWorldTime takes no minimum at all, and
    returns early on a step of exactly 0 (or -0), with the prepare flag
    already set in the branch's delay slot.
  * ResetWorldTime leaves NeedToPrepareWorldTimestep alone.

    python tools/realtime_check.py
    python tools/realtime_check.py --mutate
    python tools/realtime_check.py --dump out/realtime
"""
import argparse
import difflib
import os
import random
import struct
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
    "tools/src/realtime_test.c",
    "3DS Files/source/realtime.c",
    "3DS Files/source/joylog.c",
    "3DS Files/source/timer.c",
]

RC = "3DS Files/source/realtime.c"

GP = 0x00328bf0
G_BASE = GP - 20264             # FrameCounter, the first of the eighteen
G_JL_REPLAYING = GP - 21256
G_JL_CAPTURING = GP - 21252
G_JL_REPEAT = GP - 21248
FAKE_REPEAT = 0x01E30100

NAMES = [
    "FrameCounter", "CurrentVideoMode", "RealTimer", "RealTime",
    "RealTimeFrames", "RealTimeElapsed", "RealTimeElapsedQuantized",
    "RealTimeElapsedFrame", "RealTimeElapsedError", "RealLoopCounter",
    "WorldTimer", "WorldTimeSeconds", "WorldTime", "WorldTimeFrames",
    "WorldTimeElapsed", "WorldTimeElapsedFrame", "WorldLoopCounter",
    "NeedToPrepareWorldTimestep",
]
IDX = {n: i for i, n in enumerate(NAMES)}

SYM = {
    "get_mode": "GetVideoMode__Fv",
    "set_mode": "SetVideoMode__F10VIDEO_MODE",
    "fromq": "GetRealTimeElapsedFromQuantized__Fi",
    "quant": "GetQuantizedRealTimeElapsed__Ff",
    "prep_real": "PrepareRealTimestep__Ff",
    "adv_real": "AdvanceRealTime__Fv",
    "reset_world": "ResetWorldTime__Fv",
    "prep_world": "PrepareWorldTimestep__Ff",
    "adv_world": "AdvanceWorldTime__Fv",
}

(OP_TAG, OP_SET_MODE, OP_GET_MODE, OP_FROMQ, OP_QUANT, OP_PREP_REAL,
 OP_ADV_REAL, OP_RESET_WORLD, OP_PREP_WORLD, OP_ADV_WORLD, OP_FLAGS,
 OP_FEED, OP_POKE, OP_DUMP) = range(1, 15)

bits = me.f_to_bits
fbits = me.fbits_to


def s32(x):
    x &= M32
    return x - (1 << 32) if x & 0x80000000 else x


def up(b):
    return (b + 1) & M32


def down(b):
    return (b - 1) & M32


# ---------------------------------------------------------------- the script


class Script(object):
    def __init__(self):
        self.words = []
        self.tags = []

    def op(self, code, *args):
        self.words.append(code)
        self.words.extend(a & M32 for a in args)

    def tag(self, name):
        self.op(OP_TAG, len(self.tags))
        self.tags.append(name)

    def frame(self, dt):
        self.op(OP_PREP_REAL, bits(dt))
        self.op(OP_ADV_REAL)

    def poke_f(self, name, v):
        self.op(OP_POKE, IDX[name], bits(v))

    def poke(self, name, v):
        self.op(OP_POKE, IDX[name], v)

    def edge(self, b):
        """A real step of exactly `b` after the scale: 0 * 1.0167 is 0, so
        the error term alone is the step."""
        self.op(OP_POKE, IDX["RealTimeElapsedError"], b)
        self.op(OP_PREP_REAL, 0)
        self.op(OP_ADV_REAL)


# The windows, as the image holds them: gp-29840 .. gp-29828.
PAL_LO, PAL_HI = 0x3ca3d70a, 0x3d75c28f
NTSC_LO, NTSC_HI = 0x3c888889, 0x3d4cccce

STEPS = [0.0, 0.001, 0.0163, 0.0165, 1.0 / 60, 0.0167, 0.02, 1.0 / 30,
         0.0491, 0.0492, 0.05, 0.0591, 0.06, 0.1, 1.0, -0.01]


def window(sc, lo, hi):
    for b in (down(lo), lo, up(lo), down(hi), hi, up(hi), bits(0.05),
              bits(0.02), bits(0.06), bits(1.0 / 60)):
        sc.edge(b)


def script():
    sc = Script()
    sc.tag("initial values")
    sc.op(OP_DUMP)

    sc.tag("video mode")
    sc.op(OP_GET_MODE)
    for m in (0, 1, 5, 1):
        sc.op(OP_SET_MODE, m)
        sc.op(OP_GET_MODE)

    sc.tag("quantised to seconds")
    for q in (0, 1, 60, 61, 180, 216, 255, -1, 3600, 0x7FFFFFFF,
              -0x80000000):
        sc.op(OP_FROMQ, q)

    sc.tag("seconds to quantised")
    for s in (0.0, -0.0, 1.0 / 7200, 1.0 / 3600, 1.5 / 3600, 1.0 / 60,
              0.016944444, 0.02, 0.05, 0.06, 0.1, 1.0, -0.001, -1.0,
              1e6, 596523.2, 1e9, -1e9, float("inf"), float("-inf")):
        sc.op(OP_QUANT, bits(s))

    sc.tag("ntsc, capturing, a sixtieth a frame")
    sc.op(OP_FLAGS, 0, 1, 1)
    for _ in range(30):
        sc.frame(1.0 / 60)

    sc.tag("ntsc, steps")
    for s in STEPS:
        sc.frame(s)

    sc.tag("ntsc, the window's edges")
    window(sc, NTSC_LO, NTSC_HI)

    sc.tag("mode 5 is not pal")
    sc.op(OP_SET_MODE, 5)
    sc.frame(0.001)
    sc.frame(0.2)
    sc.op(OP_SET_MODE, 1)

    sc.tag("pal, a fiftieth a frame")
    sc.op(OP_SET_MODE, 0)
    sc.poke_f("RealTimeElapsedError", 0.0)
    for _ in range(25):
        sc.frame(1.0 / 50)

    sc.tag("pal, steps")
    for s in STEPS:
        sc.frame(s)

    sc.tag("pal, the window's edges")
    window(sc, PAL_LO, PAL_HI)
    sc.op(OP_SET_MODE, 1)

    sc.tag("replaying")
    sc.op(OP_FLAGS, 1, 1, 1)
    for step, loop in ((61, 7), (0, 0), (255, 3), (-5, 15), (1000, 1),
                       (60, 2)):
        sc.op(OP_FEED, step)
        sc.op(OP_FEED, loop)
        sc.frame(0.03)
    sc.frame(0.03)                  # the feed is dry: both reads give 0
    sc.op(OP_FEED, 90)
    sc.frame(0.0)                   # 90, then a dry read

    sc.tag("replaying, no repeat")
    sc.op(OP_FLAGS, 1, 1, 0)
    sc.op(OP_FEED, 77)
    sc.frame(1.0 / 60)
    sc.op(OP_FLAGS, 1, 0, 1)
    sc.frame(1.0 / 60)              # the 77 is read now

    sc.tag("not capturing")
    sc.op(OP_FLAGS, 0, 0, 1)
    sc.frame(1.0 / 60)
    sc.op(OP_FLAGS, 0, 1, 0)
    sc.frame(1.0 / 60)
    sc.op(OP_FLAGS, 0, 1, 1)

    sc.tag("the loop count's four bits")
    for start in (0x7FFFFFFD, 0xFFFFFFFD, 0x12345678):
        sc.poke("RealLoopCounter", start)
        for _ in range(4):
            sc.frame(1.0 / 60)

    sc.tag("advancing the real clock")
    sc.poke_f("RealTimeElapsedFrame", 0.0)
    for el in (0.0, -0.0, 0.001, 1.0 / 60, 0.0166, 0.034, -1.0, -0.001,
               1e9, -1e9, 1e-30):
        sc.poke_f("RealTimeElapsed", el)
        sc.op(OP_ADV_REAL)
    sc.poke_f("RealTimeElapsedFrame", 0.0166)
    sc.poke_f("RealTimeElapsed", 0.0001)
    sc.op(OP_ADV_REAL)
    sc.poke("RealTimer", 0x7FFFFF00)
    sc.poke("RealTimeFrames", 0x7FFFFFFF)
    sc.poke_f("RealTimeElapsed", 0.05)
    sc.op(OP_ADV_REAL)
    sc.op(OP_ADV_REAL)
    sc.poke("RealTimer", 0xFFFFFF00)
    sc.poke("RealTimeFrames", 0xFFFFFFFF)
    sc.op(OP_ADV_REAL)
    sc.op(OP_ADV_REAL)

    sc.tag("the world clock before a reset")
    sc.op(OP_ADV_WORLD)
    sc.op(OP_PREP_WORLD, bits(1.0 / 60))
    sc.op(OP_ADV_WORLD)

    sc.tag("the world clock")
    sc.op(OP_PREP_WORLD, bits(0.02))
    sc.op(OP_RESET_WORLD)           # the prepare flag stays 0
    sc.op(OP_ADV_WORLD)             # and the step is gone
    for _ in range(20):
        sc.op(OP_PREP_WORLD, bits(1.0 / 60))
        sc.op(OP_ADV_WORLD)
    for s in (0.0, -0.0, 0.001, 0.001, 0.001, 0.001, 0.02, 0.05, 1.0,
              -0.01, -1.0, 1e9, 1e-30, 0.0166, 0.0001):
        sc.op(OP_PREP_WORLD, bits(s))
        sc.op(OP_ADV_WORLD)
    sc.op(OP_ADV_WORLD)             # unprepared: last frame's step was used

    sc.tag("the world clock, wrapping")
    sc.op(OP_RESET_WORLD)
    sc.poke("WorldTimer", 0x7FFFFF00)
    sc.op(OP_PREP_WORLD, bits(0.1))
    sc.op(OP_ADV_WORLD)
    sc.op(OP_PREP_WORLD, bits(0.1))
    sc.op(OP_ADV_WORLD)
    sc.poke("WorldTimeFrames", 0x7FFFFFFE)
    sc.poke("WorldLoopCounter", 0xFFFFFFFF)
    sc.op(OP_PREP_WORLD, bits(0.05))
    sc.op(OP_ADV_WORLD)
    sc.op(OP_RESET_WORLD)

    sc.tag("a random walk")
    rnd = random.Random(20260925)
    sc.op(OP_FLAGS, 0, 1, 1)
    for _ in range(600):
        k = rnd.random()
        if k < 0.35:
            dt = rnd.choice([1.0 / 60, 1.0 / 50, 1.0 / 30, 0.0,
                             rnd.uniform(0.0, 0.1), rnd.uniform(0.0, 0.03),
                             rnd.uniform(-0.01, 0.2)])
            sc.op(OP_PREP_REAL, bits(dt))
        elif k < 0.6:
            sc.op(OP_ADV_REAL)
        elif k < 0.7:
            sc.op(OP_PREP_WORLD, bits(rnd.choice(
                [0.0, 1.0 / 60, rnd.uniform(0.0, 0.1)])))
        elif k < 0.85:
            sc.op(OP_ADV_WORLD)
        elif k < 0.88:
            sc.op(OP_SET_MODE, rnd.choice([0, 1]))
        elif k < 0.90:
            sc.op(OP_RESET_WORLD)
        elif k < 0.95:
            r = rnd.random() < 0.4
            sc.op(OP_FLAGS, r, rnd.random() < 0.8, rnd.random() < 0.9)
            if r:
                for _ in range(rnd.randrange(4)):
                    sc.op(OP_FEED, rnd.randrange(-10, 300))
        else:
            sc.op(OP_FEED, rnd.randrange(0, 256))
    sc.op(OP_DUMP)
    return sc


# ================================================================ the model


class Model(object):
    def __init__(self, sc):
        self.sc = sc
        self.out = []
        self.feed = []
        e = self.e = me.Emu(ieee=True)
        self.fn = {k: e.addr_of(v) for k, v in SYM.items()}
        emit = self.out.append

        def rep_remove(em):
            v = self.feed.pop(0) if self.feed else 0
            emit("  jl get bits %d ch %d -> %d%s"
                 % (s32(em.reg[5]), s32(em.reg[6]), v,
                    "" if em.reg[4] & M32 == FAKE_REPEAT else " rep?"))
            return v & M32

        def rep_add(em):
            emit("  jl add %d bits %d ch %d%s"
                 % (s32(em.reg[5]), s32(em.reg[6]), s32(em.reg[7]),
                    "" if em.reg[4] & M32 == FAKE_REPEAT else " rep?"))

        e.stub("RemoveData__7bRepeatii", rep_remove)
        e.stub("AddData__7bRepeatiii", rep_add)
        # The fake repeat never runs out, as in joystick_check: RemoveData's
        # end test wants word 36 below word 32 and word 40 clear, AddData's
        # wants word 8 below 8 * word 20 - 68.
        e.put32(FAKE_REPEAT + 32, 1000)
        e.put32(FAKE_REPEAT + 20, 1000)

    def dump(self):
        g = [self.e.u32(G_BASE + 4 * i) for i in range(18)]
        self.out.append("  real  " + " ".join("%08x" % w for w in g[:10]))
        self.out.append("  world " + " ".join("%08x" % w for w in g[10:]))

    def call_f(self, fn, b):
        self.e.fpr[12] = b & M32
        return self.e.call(self.fn[fn])

    def run(self):
        e, w, out = self.e, self.sc.words, self.out
        i = 0

        def arg():
            nonlocal i
            i += 1
            return w[i - 1]

        while i < len(w):
            op = arg()
            if op == OP_TAG:
                out.append("[%d]" % arg())
            elif op == OP_SET_MODE:
                m = s32(arg())
                out.append("set mode %d -> %d"
                           % (m, e.call(self.fn["set_mode"], m)))
            elif op == OP_GET_MODE:
                out.append("get mode -> %d" % e.call(self.fn["get_mode"]))
            elif op == OP_FROMQ:
                q = s32(arg())
                e.call(self.fn["fromq"], q)
                out.append("fromq %d -> %08x" % (q, e.fpr[0] & M32))
            elif op == OP_QUANT:
                b = arg()
                out.append("quant %08x -> %d" % (b, self.call_f("quant", b)))
            elif op == OP_PREP_REAL:
                b = arg()
                out.append("prep real %08x" % b)
                self.call_f("prep_real", b)
                self.dump()
            elif op == OP_ADV_REAL:
                out.append("adv real")
                e.call(self.fn["adv_real"])
                self.dump()
            elif op == OP_RESET_WORLD:
                out.append("reset world")
                e.call(self.fn["reset_world"])
                self.dump()
            elif op == OP_PREP_WORLD:
                b = arg()
                out.append("prep world %08x" % b)
                self.call_f("prep_world", b)
                self.dump()
            elif op == OP_ADV_WORLD:
                out.append("adv world")
                e.call(self.fn["adv_world"])
                self.dump()
            elif op == OP_FLAGS:
                r, c, p = s32(arg()), s32(arg()), s32(arg())
                e.put32(G_JL_REPLAYING, r)
                e.put32(G_JL_CAPTURING, c)
                e.put32(G_JL_REPEAT, FAKE_REPEAT if p else 0)
                out.append("flags %d %d %d" % (r, c, p))
            elif op == OP_FEED:
                self.feed.append(s32(arg()))
            elif op == OP_POKE:
                k, v = arg(), arg()
                e.put32(G_BASE + 4 * k, v)
                out.append("poke %d %08x" % (k, v))
            elif op == OP_DUMP:
                self.dump()
            else:
                raise SystemExit("op %d" % op)
        return out


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

MUTATIONS = [
    # the initial values
    ("rt-init-mode", RC, "CurrentVideoMode           = MODE_NTSC;",
     "CurrentVideoMode           = MODE_PAL;"),
    ("rt-init-realtimer", RC, "int32_t RealTimer;", "int32_t RealTimer = 4000;"),
    ("rt-init-realtime", RC, "RealTime                   = 1;",
     "RealTime                   = 0;"),
    ("rt-init-realframes", RC, "RealTimeFrames             = 1;",
     "RealTimeFrames             = 0;"),
    ("rt-init-frames", RC, "int32_t FrameCounter;",
     "int32_t FrameCounter = 1;"),
    ("rt-init-elapsed", RC, "float   RealTimeElapsed;",
     "float   RealTimeElapsed = 1.0f / 60.0f;"),
    ("rt-init-quantized", RC, "int32_t RealTimeElapsedQuantized;",
     "int32_t RealTimeElapsedQuantized = 60;"),
    ("rt-init-elapsed-frame", RC, "float   RealTimeElapsedFrame;",
     "float   RealTimeElapsedFrame = 1.0f / 120.0f;"),
    ("rt-init-error", RC, "float   RealTimeElapsedError;",
     "float   RealTimeElapsedError = 1.0f / 3600.0f;"),
    ("rt-init-realloop", RC, "int32_t RealLoopCounter;",
     "int32_t RealLoopCounter = 100000;"),
    ("rt-init-wtimer", RC, "int32_t WorldTimer;",
     "int32_t WorldTimer = 4000;"),
    ("rt-init-wseconds", RC, "WorldTimeSeconds           = 1.0f;",
     "WorldTimeSeconds           = 0.0f;"),
    ("rt-init-wtime", RC, "WorldTime                  = 1;",
     "WorldTime                  = 0;"),
    ("rt-init-wframes", RC, "WorldTimeFrames            = 1;",
     "WorldTimeFrames            = 0;"),
    ("rt-init-welapsed", RC, "float   WorldTimeElapsed;",
     "float   WorldTimeElapsed = 1.0f / 60.0f;"),
    ("rt-init-welapsed-frame", RC, "float   WorldTimeElapsedFrame;",
     "float   WorldTimeElapsedFrame = 1.0f / 120.0f;"),
    ("rt-init-wloop", RC, "WorldLoopCounter           = 100000;",
     "WorldLoopCounter           = 0;"),
    ("rt-init-need", RC, "NeedToPrepareWorldTimestep = 1;",
     "NeedToPrepareWorldTimestep = 0;"),

    # the constants
    ("rt-quantum", RC, "REALTIME_QUANTUM          0.000277777785f",
     "REALTIME_QUANTUM          0.00027777f"),
    ("rt-quanta", RC, "REALTIME_QUANTA_PER_SEC   3600.0f",
     "REALTIME_QUANTA_PER_SEC   3601.0f"),
    ("rt-scale", RC, "REALTIME_TICKER_SCALE     1.0167f",
     "REALTIME_TICKER_SCALE     1.0f"),
    ("rt-scale-near", RC, "REALTIME_TICKER_SCALE     1.0167f",
     "REALTIME_TICKER_SCALE     1.0166f"),
    ("rt-pal-min", RC, "REALTIME_PAL_MIN          0.02f",
     "REALTIME_PAL_MIN          0.0166666675f"),
    ("rt-pal-max", RC, "REALTIME_PAL_MAX          0.06f",
     "REALTIME_PAL_MAX          0.05f"),
    ("rt-ntsc-min", RC, "REALTIME_NTSC_MIN         0.0166666675f",
     "REALTIME_NTSC_MIN         0.02f"),
    ("rt-ntsc-max-ulp", RC, "REALTIME_NTSC_MAX         0.050000004f",
     "REALTIME_NTSC_MAX         0.05f"),
    ("rt-frames-per-sec", RC, "REALTIME_FRAMES_PER_SEC   60.0f",
     "REALTIME_FRAMES_PER_SEC   50.0f"),
    ("rt-secs-per-frame", RC, "REALTIME_SECS_PER_FRAME   0.0166666675f",
     "REALTIME_SECS_PER_FRAME   0.0166666f"),
    ("rt-secs-per-tick", RC, "REALTIME_SECS_PER_TICK    0.000250000012f",
     "REALTIME_SECS_PER_TICK    0.000249999f"),
    ("rt-step-bits", RC, "REALTIME_LOG_STEP_BITS    8",
     "REALTIME_LOG_STEP_BITS    7"),
    ("rt-step-channel", RC, "REALTIME_LOG_STEP_CHANNEL 2",
     "REALTIME_LOG_STEP_CHANNEL 3"),
    ("rt-loop-bits", RC, "REALTIME_LOG_LOOP_BITS    4",
     "REALTIME_LOG_LOOP_BITS    5"),
    ("rt-loop-channel", RC, "REALTIME_LOG_LOOP_CHANNEL 4",
     "REALTIME_LOG_LOOP_CHANNEL 3"),

    # the video mode
    ("vm-get-constant", RC, "    return CurrentVideoMode;",
     "    return MODE_NTSC;"),
    ("vm-set-returns-new", RC, "    return old;", "    return mode;"),
    ("vm-set-no-store", RC, "    CurrentVideoMode = mode;" + NL, ""),

    # the quantisation
    ("q-no-round", RC, "REALTIME_QUANTA_PER_SEC + 0.5f)",
     "REALTIME_QUANTA_PER_SEC)"),
    ("q-round-up", RC, "REALTIME_QUANTA_PER_SEC + 0.5f)",
     "REALTIME_QUANTA_PER_SEC + 1.0f)"),
    ("q-plain-cast", RC, "return ee_trunc_w(seconds * REALTIME_QUANTA_PER_SEC",
     "return (int32_t)(seconds * REALTIME_QUANTA_PER_SEC"),
    ("q-from-divides", RC, "return (float)q * REALTIME_QUANTUM;",
     "return (float)q / REALTIME_QUANTA_PER_SEC;"),

    # PrepareRealTimestep
    ("pr-loop-mask", RC, "RealLoopCounter & 15;", "RealLoopCounter & 7;"),
    ("pr-replay-inverted", RC, "if (Joylog_ReplayingFlag != 0) {",
     "if (Joylog_ReplayingFlag == 0) {"),
    ("pr-replay-no-discard", RC,
     "        (void)Joylog_GetData(REALTIME_LOG_LOOP_BITS, "
     "REALTIME_LOG_LOOP_CHANNEL);" + NL, ""),
    ("pr-replay-second-read", RC,
     "        q = Joylog_GetData(REALTIME_LOG_STEP_BITS, "
     "REALTIME_LOG_STEP_CHANNEL);" + NL
     + "        (void)Joylog_GetData(",
     "        (void)Joylog_GetData(REALTIME_LOG_STEP_BITS, "
     "REALTIME_LOG_STEP_CHANNEL);" + NL
     + "        q = Joylog_GetData("),
    ("pr-no-error", RC, "REALTIME_TICKER_SCALE + RealTimeElapsedError;",
     "REALTIME_TICKER_SCALE;"),
    ("pr-error-before-scale", RC,
     "seconds = seconds * REALTIME_TICKER_SCALE + RealTimeElapsedError;",
     "seconds = (seconds + RealTimeElapsedError) * REALTIME_TICKER_SCALE;"),
    ("pr-mode-inverted", RC, "if (GetVideoMode() == MODE_PAL) {",
     "if (GetVideoMode() != MODE_PAL) {"),
    ("pr-mode-ntsc-test", RC, "if (GetVideoMode() == MODE_PAL) {",
     "if (GetVideoMode() != MODE_NTSC) {"),
    ("pr-no-floor", RC,
     "        if (seconds < lo)" + NL + "            seconds = lo;" + NL, ""),
    ("pr-no-ceiling", RC,
     "        if (hi < seconds)" + NL + "            seconds = hi;" + NL, ""),
    ("pr-floor-swapped", RC, "            seconds = lo;",
     "            seconds = hi;"),
    ("pr-timer-from-seconds", RC,
     "timer_set_time(&t, GetRealTimeElapsedFromQuantized(q));",
     "timer_set_time(&t, seconds);"),
    ("pr-error-from-quantum", RC,
     "RealTimeElapsedError = seconds - (float)(int32_t)t.PackedTime" + NL
     + "                                         * REALTIME_SECS_PER_TICK;",
     "RealTimeElapsedError = seconds - GetRealTimeElapsedFromQuantized(q);"),
    ("pr-error-unsigned", RC, "seconds - (float)(int32_t)t.PackedTime",
     "seconds - (float)t.PackedTime"),
    ("pr-add-step-zero", RC, "Joylog_AddData(q, REALTIME_LOG_STEP_BITS",
     "Joylog_AddData(0, REALTIME_LOG_STEP_BITS"),
    ("pr-add-loop-whole", RC, "Joylog_AddData(loop, REALTIME_LOG_LOOP_BITS",
     "Joylog_AddData(RealLoopCounter, REALTIME_LOG_LOOP_BITS"),
    ("pr-no-add-loop", RC,
     "        Joylog_AddData(loop, REALTIME_LOG_LOOP_BITS, "
     "REALTIME_LOG_LOOP_CHANNEL);" + NL, "        (void)loop;" + NL),
    ("pr-quantised-kept", RC, "    RealTimeElapsedQuantized = q;" + NL, ""),
    ("pr-elapsed-seconds", RC,
     "    RealTimeElapsed = GetRealTimeElapsedFromQuantized(q);",
     "    RealTimeElapsed = seconds;"),

    # AdvanceRealTime
    ("ar-no-carry", RC, "float acc = RealTimeElapsedFrame + RealTimeElapsed;",
     "float acc = RealTimeElapsed;"),
    ("ar-no-minimum", RC, "(uint32_t)(n != 0 ? n : 1)", "(uint32_t)n"),
    ("ar-positive-minimum", RC, "(uint32_t)(n != 0 ? n : 1)",
     "(uint32_t)(n > 0 ? n : 1)"),
    ("ar-time-kept", RC, "    RealTime = RealTimeFrames;" + NL, ""),
    ("ar-remainder-minimum", RC,
     "RealTimeElapsedFrame = acc - (float)n *",
     "RealTimeElapsedFrame = acc - (float)(n != 0 ? n : 1) *"),
    ("ar-no-remainder", RC,
     "RealTimeElapsedFrame = acc - (float)n * REALTIME_SECS_PER_FRAME;",
     "RealTimeElapsedFrame = 0.0f;"),
    ("ar-timer-from-acc", RC, "timer_set_time(&t, RealTimeElapsed);",
     "timer_set_time(&t, acc);"),
    ("ar-timer-kept", RC,
     "    RealTimer = (int32_t)((uint32_t)RealTimer + t.PackedTime);" + NL,
     "    (void)t;" + NL),
    ("ar-no-loop", RC,
     "    RealLoopCounter = (int32_t)((uint32_t)RealLoopCounter + 1u);" + NL,
     ""),

    # ResetWorldTime
    ("rw-ticks", RC, "ee_trunc_w(4000.0f)", "ee_trunc_w(4001.0f)"),
    ("rw-frames", RC, "    WorldTimeFrames = 1;" + NL,
     "    WorldTimeFrames = 0;" + NL),
    ("rw-time", RC, "    WorldTime = 1;" + NL, "    WorldTime = 0;" + NL),
    ("rw-elapsed-kept", RC,
     "    WorldTimeElapsed = 0.0f;" + NL + "    WorldTimeElapsedFrame = 0.0f;",
     "    WorldTimeElapsedFrame = 0.0f;"),
    ("rw-frame-kept", RC, "    WorldTimeElapsedFrame = 0.0f;" + NL, ""),
    ("rw-loop-kept", RC, "    WorldLoopCounter = 0;" + NL, ""),
    ("rw-seconds-kept", RC,
     "    WorldTimeSeconds = (float)ticks * REALTIME_SECS_PER_TICK;" + NL, ""),
    ("rw-seconds-one", RC,
     "    WorldTimeSeconds = (float)ticks * REALTIME_SECS_PER_TICK;",
     "    WorldTimeSeconds = 1.0f;"),
    ("rw-sets-need", RC, "    WorldLoopCounter = 0;" + NL,
     "    WorldLoopCounter = 0;" + NL + "    NeedToPrepareWorldTimestep = 1;"
     + NL),

    # PrepareWorldTimestep
    ("pw-no-store", RC, "    WorldTimeElapsed = seconds;" + NL, ""),
    ("pw-need-set", RC, "    NeedToPrepareWorldTimestep = 0;",
     "    NeedToPrepareWorldTimestep = 1;"),

    # AdvanceWorldTime
    ("aw-flag-after-test", RC,
     "    NeedToPrepareWorldTimestep = 1;" + NL
     + "    if (WorldTimeElapsed == 0.0f)" + NL + "        return;" + NL,
     "    if (WorldTimeElapsed == 0.0f)" + NL + "        return;" + NL
     + "    NeedToPrepareWorldTimestep = 1;" + NL),
    ("aw-no-flag", RC,
     "    NeedToPrepareWorldTimestep = 1;" + NL
     + "    if (WorldTimeElapsed == 0.0f)",
     "    if (WorldTimeElapsed == 0.0f)"),
    ("aw-no-early-return", RC,
     "    if (WorldTimeElapsed == 0.0f)" + NL + "        return;" + NL, ""),
    ("aw-positive-test", RC, "    if (WorldTimeElapsed == 0.0f)",
     "    if (WorldTimeElapsed <= 0.0f)"),
    ("aw-minimum", RC, "(uint32_t)WorldTimeFrames + (uint32_t)n",
     "(uint32_t)WorldTimeFrames + (uint32_t)(n != 0 ? n : 1)"),
    ("aw-no-carry", RC, "acc = WorldTimeElapsedFrame + WorldTimeElapsed;",
     "acc = WorldTimeElapsed;"),
    ("aw-time-kept", RC, "    WorldTime = WorldTimeFrames;" + NL, ""),
    ("aw-no-remainder", RC,
     "WorldTimeElapsedFrame = acc - (float)n * REALTIME_SECS_PER_FRAME;",
     "WorldTimeElapsedFrame = acc;"),
    ("aw-timer-from-acc", RC, "timer_set_time(&t, WorldTimeElapsed);",
     "timer_set_time(&t, acc);"),
    ("aw-timer-kept", RC,
     "    WorldTimer = (int32_t)((uint32_t)WorldTimer + t.PackedTime);" + NL,
     ""),
    ("aw-step-kept", RC,
     "    WorldTimeElapsed = 0.0f;" + NL + "    WorldLoopCounter",
     "    WorldLoopCounter"),
    ("aw-no-loop", RC,
     "    WorldLoopCounter = (int32_t)((uint32_t)WorldLoopCounter + 1u);" + NL,
     ""),
    ("aw-seconds-step", RC,
     "WorldTimeSeconds = (float)WorldTimer * REALTIME_SECS_PER_TICK;" + NL
     + "}",
     "WorldTimeSeconds = (float)t.PackedTime * REALTIME_SECS_PER_TICK;" + NL
     + "}"),
    ("aw-seconds-unsigned", RC,
     "WorldTimeSeconds = (float)WorldTimer * REALTIME_SECS_PER_TICK;" + NL
     + "}",
     "WorldTimeSeconds = (float)(uint32_t)WorldTimer * "
     "REALTIME_SECS_PER_TICK;" + NL + "}"),
]

EQUIVALENT = {
    "pr-error-unsigned":
        "the timer holds the quantised step of a clamped one, 60 to 216 "
        "ticks of 1/3600 s and so 66 to 240 of 1/4000 s, never a word with "
        "its top bit set; the replay path, which takes any step, does not "
        "compute the error",
    "rw-seconds-one":
        "(float)4000 * 0x3983126f is 1.000000048, which rounds to 1.0f, so "
        "the product is the constant",
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
        exe = hostbuild.build(tmp, SOURCES, name="realtime_test")
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
            print("  %-26s PATTERN NOT FOUND" % name)
            continue
        try:
            write_source(path, text.replace(probe, repl, 1))
            with tempfile.TemporaryDirectory() as tmp:
                sp = Path(tmp) / "script.txt"
                write_script(sc, sp)
                try:
                    exe = hostbuild.build(tmp, SOURCES, name="realtime_test")
                except SystemExit:
                    print("  %-26s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, sp, out)
                if rc == HARNESS_HUNG:
                    print("  %-26s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-26s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base_model, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-26s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-26s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-26s SURVIVED" % name)
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
        exe = hostbuild.build(tmp, SOURCES, name="realtime_test")
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
    print("%d scenarios, %d ops, %d lines, %d differ"
          % (len(sc.tags), ops, len(harness), bad))
    sys.exit(1 if (bad or rc) else 0)


if __name__ == "__main__":
    main()
