#!/usr/bin/env python3
"""Cross-check MainLoop's frame profiler against the image (step 13b-2).

The profiler is three functions in SLES_507.31: CalculateFrameRate
(0x0012f090), the port's mainloop.c, and the two times it reads,
GetWaitForBufferSwapTime (0x00111f28) and GetVifTime (0x00111f40), the
port's edisplay.c. retail_model.RetailEmu runs them out of the image, with
the image's own bGetTickerDifference (0x00250f48); the harness
(tools/src/mainloop_test.c) runs the port. Both walk the same script and
the two transcripts are diffed.

The globals are MainLoopTiming's ten ticks (0x002f0058), the two times in
16.16 fixed milliseconds (gp-24456 and gp-24452), RealTimeFrames
(gp-19600), and the four numbers CalculateFrameRate keeps (gp-23248 ..
gp-23236). Its own static, last_realtime_frames (gp-13416), shows only in
when the four change, and the script steers it through RealTimeFrames.

What the listing says that is easy to get wrong, and which the script
reaches:

  * The CPU's time is the frame's, StartTime to LimitFrameRate, less the
    wait for the buffer swap. The GPU's is VifTime alone.
  * Each is floored at 0.1 ms (gp-32052) before 1000 is divided by it, so
    no rate is over 10000 and none is a division by 0.
  * The four are kept only when bit 3 of RealTimeFrames differs from the
    kept frame count's. The whole count is kept, not the bit.
  * The two times are `cvt.s.w` of a signed word, times 2^-16.
  * The ticks' difference is unsigned: a wrap is a short frame, and a
    frame that runs backwards is a long one.

Retail's loop over the World's cars when DoScreenPrintf (gp-23064) is set
is left out of the port (mainloop.h), and the script leaves the flag at 0.

    python tools/mainloop_check.py
    python tools/mainloop_check.py --mutate
    python tools/mainloop_check.py --dump out/mainloop
"""
import argparse
import os
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import mipsemu as me
import realtime_check as rc
import retail_model

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)
M32 = 0xFFFFFFFF

HARNESS = "tools/src/mainloop_test.c"
MC = "3DS Files/source/mainloop.c"
ED = "3DS Files/source/edisplay.c"
SOURCES = [
    HARNESS, MC, ED,
    "3DS Files/source/realtime.c",
    "3DS Files/source/joylog.c",
    "3DS Files/source/timer.c",
    "3DS Files/source/bticker.c",
]

GP = retail_model.RETAIL_GP
F_CALC = 0x0012f090             # CalculateFrameRate
F_WAIT = 0x00111f28             # GetWaitForBufferSwapTime
F_VIF = 0x00111f40              # GetVifTime
G_TIMING = 0x002f0058           # MainLoopTiming
G_WAIT = GP - 24456             # WaitBufferSwapTime
G_VIF = GP - 24452              # VifTime
G_FRAMES = GP - 19600           # RealTimeFrames
G_PREV = GP - 23248             # PreviousCpuFrameTime, the first of four
G_SCREEN_PRINTF = GP - 23064    # DoScreenPrintf

(OP_TAG, OP_SET_TICK, OP_SET_WAIT, OP_SET_VIF, OP_SET_FRAMES, OP_WAIT_TIME,
 OP_VIF_TIME, OP_CALC, OP_DUMP) = range(1, 10)

# The EE's Count rate, as bticker.h scales the 3DS's to it.
EE_HZ = 294912000
FIX_MS = 65536

bits = me.f_to_bits


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

    def frame(self, start, ms, wait_ms, gpu_ms, frames, end_field=9):
        """One of MainLoop's frames: StartTime, the ticks between at even
        steps, the end tick `ms` later, the two times, the frame count, and
        CalculateFrameRate. Returns the end tick."""
        cycles = int(ms * EE_HZ / 1000.0)
        for i in range(10):
            self.op(OP_SET_TICK, i, start + cycles * i // 9)
        if end_field != 9:
            # Only LimitFrameRate is read: another field off the frame's
            # end catches a port reading the wrong one.
            self.op(OP_SET_TICK, end_field, start + cycles * 3)
        self.op(OP_SET_WAIT, int(wait_ms * FIX_MS))
        self.op(OP_SET_VIF, int(gpu_ms * FIX_MS))
        self.op(OP_SET_FRAMES, frames)
        self.op(OP_CALC)
        return (start + cycles) & M32


def script():
    sc = Script()
    sc.tag("initial values")
    sc.op(OP_DUMP)

    sc.tag("the two times")
    for v in (0, 1, -1, 2, 6553, 6554, 65535, 65536, 65537,
              int(33.3 * FIX_MS), int(16.7 * FIX_MS), 1000 * FIX_MS,
              0x00FFFFFF, 0x01000001, 0x01000003, 0x7FFFFFFF, 0x7FFFFFC1,
              -0x80000000, -0x7FFFFFC1, -65536, -6554, 0x12345678):
        sc.op(OP_SET_WAIT, v)
        sc.op(OP_WAIT_TIME)
        sc.op(OP_SET_VIF, v ^ 0x40)
        sc.op(OP_VIF_TIME)
        sc.op(OP_VIF_TIME)

    sc.tag("30 frames a second, kept every fourth")
    t, frames = 0x10000000, 0
    for i in range(40):
        frames += 2
        t = sc.frame(t, 33.3 + (i % 5) * 0.1, 4.0 + i % 3, 21.5 + i * 0.25,
                     frames)

    sc.tag("20 frames a second, gpu bound")
    for i in range(40):
        frames += 3
        t = sc.frame(t, 50.0, 18.0 + i * 0.2, 47.5, frames)

    sc.tag("60 frames a second, one sixtieth a frame")
    for i in range(40):
        frames += 1
        t = sc.frame(t, 16.7, 0.5, 9.0 + (i & 7), frames)

    sc.tag("the floors")
    for ms, wait, gpu in ((5.0, 5.0, 0.0),        # all wait: cpu 0
                          (5.0, 6.0, -1.0),       # cpu below 0
                          (0.0, 0.0, 0.09),
                          (0.1, 0.0, 0.1),
                          (0.11, 0.0, 0.11),
                          (1.0, 0.95, 6553.0 / FIX_MS),
                          (1.0, 0.9, 6554.0 / FIX_MS),
                          (16.7, 16.6, 0.1001),
                          (16.7, -100.0, 30000.0),
                          (16.7, 0.0, -30000.0)):
        frames += 8                 # bit 3 flips each time
        t = sc.frame(t, ms, wait, gpu, frames)

    sc.tag("the frame count's bit 3")
    for f in (frames, frames + 1, frames + 7, frames ^ 8, (frames ^ 8) + 1,
              frames, frames | 0xFFFFFFF0, 0x80000008, 0x80000000,
              0x7FFFFFF7, 0x7FFFFFFF, 0, 8, 16, 24, 24, 0xFFFFFFFF):
        t = sc.frame(t, 30.0 + (f & 3), 2.0, 20.0 + (f & 7), f)

    sc.tag("the end tick is LimitFrameRate's")
    for i in range(10):
        frames += 8
        t = sc.frame(t, 25.0 + i, 1.0, 10.0, frames, end_field=i % 9)

    sc.tag("across the counter's wrap")
    t = 0xFFF00000
    for i in range(12):
        frames += 8
        t = sc.frame(t, 33.3, 3.0, 20.0, frames)

    sc.tag("a long frame and a backwards one")
    for start, end in ((0x10000000, 0x10000000 + EE_HZ),
                       (0x10000000, 0x10000000 + EE_HZ * 14),
                       (0x10000000, 0x10000000 + EE_HZ * 15),
                       (0x10000000, 0x10000000),
                       (0x10000000, 0x0FFFFC18),
                       (0x10000000, 0x90000000),
                       (0x10000000, 0x90000001),
                       (0x10000000, 0x8FFFFFFF)):
        sc.op(OP_SET_TICK, 0, start)
        sc.op(OP_SET_TICK, 9, end & M32)
        sc.op(OP_SET_WAIT, FIX_MS)
        sc.op(OP_SET_VIF, 2 * FIX_MS)
        frames += 8
        sc.op(OP_SET_FRAMES, frames)
        sc.op(OP_CALC)

    sc.tag("a random walk")
    rnd = random.Random(20261004)
    for _ in range(400):
        k = rnd.random()
        if k < 0.15:
            sc.op(OP_SET_TICK, rnd.randrange(10), rnd.getrandbits(32))
        elif k < 0.3:
            sc.op(OP_SET_WAIT, rnd.choice([
                rnd.randrange(0, 40 * FIX_MS), rnd.getrandbits(32),
                rnd.randrange(-FIX_MS, FIX_MS)]))
        elif k < 0.45:
            sc.op(OP_SET_VIF, rnd.choice([
                rnd.randrange(0, 60 * FIX_MS), rnd.getrandbits(32),
                rnd.randrange(-FIX_MS, FIX_MS)]))
        elif k < 0.6:
            sc.op(OP_SET_FRAMES, rnd.choice([
                rnd.getrandbits(32), frames + rnd.randrange(0, 20)]))
        elif k < 0.65:
            sc.op(OP_WAIT_TIME)
        elif k < 0.7:
            sc.op(OP_VIF_TIME)
        elif k < 0.95:
            t = sc.frame(t, rnd.uniform(0.0, 80.0), rnd.uniform(-1.0, 40.0),
                         rnd.uniform(-1.0, 60.0),
                         frames + rnd.randrange(0, 20))
        else:
            sc.op(OP_CALC)
    sc.op(OP_DUMP)
    return sc


# ================================================================ the model


class Model(object):
    def __init__(self, sc):
        self.sc = sc
        self.out = []
        self.e = retail_model.RetailEmu(ieee=True)
        assert self.e.u32(G_SCREEN_PRINTF) == 0

    def dump(self):
        e = self.e
        prev = [e.u32(G_PREV + 4 * i) for i in range(4)]
        self.out.append("  prev  " + " ".join("%08x" % w for w in prev))
        self.out.append("  ticks " + " ".join(
            "%08x" % e.u32(G_TIMING + 4 * i) for i in range(10)))
        self.out.append("  wait %08x vif %08x frames %08x"
                        % (e.u32(G_WAIT), e.u32(G_VIF), e.u32(G_FRAMES)))

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
            elif op == OP_SET_TICK:
                k, v = arg(), arg()
                e.put32(G_TIMING + 4 * k, v)
                out.append("tick %d %08x" % (k, v))
            elif op == OP_SET_WAIT:
                v = arg()
                e.put32(G_WAIT, v)
                out.append("wait %08x" % v)
            elif op == OP_SET_VIF:
                v = arg()
                e.put32(G_VIF, v)
                out.append("vif %08x" % v)
            elif op == OP_SET_FRAMES:
                v = arg()
                e.put32(G_FRAMES, v)
                out.append("frames %08x" % v)
            elif op == OP_WAIT_TIME:
                e.call(F_WAIT)
                out.append("wait time -> %08x" % (e.fpr[0] & M32))
            elif op == OP_VIF_TIME:
                e.call(F_VIF)
                out.append("vif time -> %08x" % (e.fpr[0] & M32))
            elif op == OP_CALC:
                out.append("calc")
                e.call(F_CALC)
                self.dump()
            elif op == OP_DUMP:
                self.dump()
            else:
                raise SystemExit("op %d" % op)
        return out


def model(sc):
    return Model(sc).run()


# ---------------------------------------------------------------- running

HARNESS_HUNG = rc.HARNESS_HUNG
write_script = rc.write_script
run_harness = rc.run_harness
diff = rc.diff
write_source = hostbuild.write_source


# -------------------------------------------------------------- mutations
#
# (name, file, old, new). Each replaces the first match, so every pattern is
# spelled to match code and not a comment.

MUTATIONS = [
    # the constants
    ("cf-floor", MC, "MAINLOOP_MIN_FRAME_MS   0.1f",
     "MAINLOOP_MIN_FRAME_MS   0.2f"),
    ("cf-floor-near", MC, "MAINLOOP_MIN_FRAME_MS   0.1f",
     "MAINLOOP_MIN_FRAME_MS   0.1001f"),
    ("cf-thousand", MC, "MAINLOOP_MS_PER_SEC     1000.0f",
     "MAINLOOP_MS_PER_SEC     999.0f"),
    ("cf-bit-4", MC, "MAINLOOP_KEEP_BIT       8", "MAINLOOP_KEEP_BIT       4"),
    ("cf-bit-16", MC, "MAINLOOP_KEEP_BIT       8",
     "MAINLOOP_KEEP_BIT       16"),

    # the initial values
    ("init-cpu-time", MC, "float PreviousCpuFrameTime;",
     "float PreviousCpuFrameTime = 1.0f;"),
    ("init-gpu-time", MC, "float PreviousGpuFrameTime;",
     "float PreviousGpuFrameTime = 1.0f;"),
    ("init-cpu-rate", MC, "float PreviousCpuFrameRate;",
     "float PreviousCpuFrameRate = 60.0f;"),
    ("init-gpu-rate", MC, "float PreviousGpuFrameRate;",
     "float PreviousGpuFrameRate = 60.0f;"),
    ("init-last", MC, "static int32_t last_realtime_frames;",
     "static int32_t last_realtime_frames = 8;"),
    ("init-wait", ED, "int32_t WaitBufferSwapTime;",
     "int32_t WaitBufferSwapTime = 1;"),
    ("init-vif", ED, "int32_t VifTime;", "int32_t VifTime = 1;"),

    # the CPU's time
    ("cf-no-wait", MC, "MainLoopTiming.LimitFrameRate) - wait;",
     "MainLoopTiming.LimitFrameRate);"),
    ("cf-wait-added", MC, "MainLoopTiming.LimitFrameRate) - wait;",
     "MainLoopTiming.LimitFrameRate) + wait;"),
    ("cf-ticks-swapped", MC,
     "bGetTickerDifference(MainLoopTiming.StartTime," + NL
     + "                                     MainLoopTiming.LimitFrameRate)",
     "bGetTickerDifference(MainLoopTiming.LimitFrameRate," + NL
     + "                                     MainLoopTiming.StartTime)"),
    ("cf-end-field", MC, "                                     "
     "MainLoopTiming.LimitFrameRate)",
     "                                     MainLoopTiming.ServiceFileSystem)"),
    ("cf-start-field", MC, "bGetTickerDifference(MainLoopTiming.StartTime,",
     "bGetTickerDifference(MainLoopTiming.ServiceGameFlow,"),
    ("cf-wait-is-vif", MC, "float wait = GetWaitForBufferSwapTime();",
     "float wait = GetVifTime();"),
    ("cf-gpu-is-wait", MC, "float gpu = GetVifTime();",
     "float gpu = GetWaitForBufferSwapTime();"),
    ("cf-signed-difference", MC,
     "float cpu = bGetTickerDifference(MainLoopTiming.StartTime," + NL
     + "                                     MainLoopTiming.LimitFrameRate)",
     "float cpu = (float)(int32_t)(MainLoopTiming.LimitFrameRate" + NL
     + "                                     - MainLoopTiming.StartTime)"
     + " / 300000.0f"),

    # the floors and the rates
    ("cf-no-cpu-floor", MC,
     "    if (cpu < MAINLOOP_MIN_FRAME_MS)" + NL
     + "        cpu = MAINLOOP_MIN_FRAME_MS;" + NL, ""),
    ("cf-no-gpu-floor", MC,
     "    if (gpu < MAINLOOP_MIN_FRAME_MS)" + NL
     + "        gpu = MAINLOOP_MIN_FRAME_MS;" + NL, ""),
    ("cf-cpu-rate-unfloored", MC,
     "    if (cpu < MAINLOOP_MIN_FRAME_MS)" + NL
     + "        cpu = MAINLOOP_MIN_FRAME_MS;" + NL
     + "    cpuRate = MAINLOOP_MS_PER_SEC / cpu;" + NL,
     "    cpuRate = MAINLOOP_MS_PER_SEC / cpu;" + NL
     + "    if (cpu < MAINLOOP_MIN_FRAME_MS)" + NL
     + "        cpu = MAINLOOP_MIN_FRAME_MS;" + NL),
    ("cf-gpu-rate-unfloored", MC,
     "    if (gpu < MAINLOOP_MIN_FRAME_MS)" + NL
     + "        gpu = MAINLOOP_MIN_FRAME_MS;" + NL
     + "    gpuRate = MAINLOOP_MS_PER_SEC / gpu;" + NL,
     "    gpuRate = MAINLOOP_MS_PER_SEC / gpu;" + NL
     + "    if (gpu < MAINLOOP_MIN_FRAME_MS)" + NL
     + "        gpu = MAINLOOP_MIN_FRAME_MS;" + NL),
    ("cf-floor-zero", MC, "    if (cpu < MAINLOOP_MIN_FRAME_MS)",
     "    if (cpu < 0.0f)"),
    ("cf-gpu-floor-cpu", MC, "        gpu = MAINLOOP_MIN_FRAME_MS;",
     "        gpu = cpu;"),
    ("cf-rate-gpu-from-cpu", MC, "gpuRate = MAINLOOP_MS_PER_SEC / gpu;",
     "gpuRate = MAINLOOP_MS_PER_SEC / cpu;"),

    # what is kept, and when
    ("cf-keep-inverted", MC,
     "        != (last_realtime_frames & MAINLOOP_KEEP_BIT)) {",
     "        == (last_realtime_frames & MAINLOOP_KEEP_BIT)) {"),
    ("cf-keep-always", MC,
     "    if ((RealTimeFrames & MAINLOOP_KEEP_BIT)" + NL
     + "        != (last_realtime_frames & MAINLOOP_KEEP_BIT)) {",
     "    if (1) {"),
    ("cf-keep-whole", MC,
     "    if ((RealTimeFrames & MAINLOOP_KEEP_BIT)" + NL
     + "        != (last_realtime_frames & MAINLOOP_KEEP_BIT)) {",
     "    if (RealTimeFrames != last_realtime_frames) {"),
    ("cf-last-kept", MC,
     "        last_realtime_frames = RealTimeFrames;" + NL, ""),
    ("cf-last-plus-one", MC,
     "        last_realtime_frames = RealTimeFrames;",
     "        last_realtime_frames = RealTimeFrames + 1;"),
    ("cf-no-cpu-time", MC, "        PreviousCpuFrameTime = cpu;" + NL, ""),
    ("cf-no-gpu-time", MC, "        PreviousGpuFrameTime = gpu;" + NL, ""),
    ("cf-no-cpu-rate", MC, "        PreviousCpuFrameRate = cpuRate;" + NL,
     ""),
    ("cf-no-gpu-rate", MC, "        PreviousGpuFrameRate = gpuRate;" + NL,
     ""),
    ("cf-times-swapped", MC,
     "        PreviousCpuFrameTime = cpu;" + NL
     + "        PreviousGpuFrameTime = gpu;",
     "        PreviousCpuFrameTime = gpu;" + NL
     + "        PreviousGpuFrameTime = cpu;"),
    ("cf-rates-swapped", MC,
     "        PreviousCpuFrameRate = cpuRate;" + NL
     + "        PreviousGpuFrameRate = gpuRate;",
     "        PreviousCpuFrameRate = gpuRate;" + NL
     + "        PreviousGpuFrameRate = cpuRate;"),
    ("cf-time-is-wait", MC, "        PreviousCpuFrameTime = cpu;",
     "        PreviousCpuFrameTime = cpu + wait;"),

    # the two times
    ("et-wait-scale", ED, "#define EDISPLAY_FIX_MS  (1.0f / 65536.0f)",
     "#define EDISPLAY_FIX_MS  (1.0f / 65535.0f)"),
    ("et-wait-thousandths", ED,
     "return (float)WaitBufferSwapTime * EDISPLAY_FIX_MS;",
     "return (float)WaitBufferSwapTime * 0.001f;"),
    ("et-wait-unsigned", ED, "return (float)WaitBufferSwapTime",
     "return (float)(uint32_t)WaitBufferSwapTime"),
    ("et-wait-reads-vif", ED, "return (float)WaitBufferSwapTime",
     "return (float)VifTime"),
    ("et-vif-unsigned", ED, "return (float)VifTime",
     "return (float)(uint32_t)VifTime"),
    ("et-vif-reads-wait", ED, "return (float)VifTime",
     "return (float)WaitBufferSwapTime"),
    ("et-vif-shift", ED, "return (float)VifTime * EDISPLAY_FIX_MS;",
     "return (float)(VifTime >> 16);"),
]

EQUIVALENT = {}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name


def mutate_pass(sc):
    base_model = model(sc)
    survived, missing, equivalent, caught = [], [], [], 0

    with tempfile.TemporaryDirectory() as tmp:
        sp = Path(tmp) / "script.txt"
        write_script(sc, sp)
        exe = hostbuild.build(tmp, SOURCES, name="mainloop_test")
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
                    exe = hostbuild.build(tmp, SOURCES, name="mainloop_test")
                except SystemExit:
                    print("  %-26s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rcode = run_harness(exe, sp, out)
                if rcode == HARNESS_HUNG:
                    print("  %-26s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rcode != 0:
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
        exe = hostbuild.build(tmp, SOURCES, name="mainloop_test")
        out = Path(tmp) / "harness.txt"
        rcode = run_harness(exe, sp, out)
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
    sys.exit(1 if (bad or rcode) else 0)


if __name__ == "__main__":
    main()
