#!/usr/bin/env python3
"""Cross-check 3DS Files/source/rain.c against the image, and check the
image's case that the rest of the rain and the storm is dead.

**The calls.** The model runs rain_Load, rain_Unload, rain_TimeStep and
rain_Render out of the image in mipsemu, and the harness
(tools/src/rain_test.c) runs rain.c's. Each call is handed a view filled
with a pattern, and dt as float bits across the range: zero, both signs,
the denormals, the infinities and a NaN. Each side prints whether the view
and the rest of its memory came through unchanged. The model compares all
32 MB, the saved registers s0-s8, gp, sp and ra, and f20-f31.

**The image.** Printed and checked against EXPECTED, not diffed against the
harness:
  - each entry point's words, and its instruction count when run;
  - SetStormType, GetStormType and GetStormTypeString, run for several
    types;
  - every reference, in the loaded sections, to Rain.obj's functions and
    globals, to the storm's, to the two weather queries and to
    SoundScape::UpdateWeather. A reference is a jal or j, a lui and
    addiu pair, or a lui with a load or store, with the lui forgotten
    once its register is written. It can also be a gp-relative access, or
    a word in a data section. SN's compiler forms addresses with addiu,
    not ori. The lui/ori pairs that land in StormInfo's 98,592 bytes are
    GS register constants (0x2c0400, 0x2c2000, ...), so ori is not
    counted.

What this shows is in rain.h. In short, the four entry points are
`jr ra ; nop`, and no path from live code reaches the RainSystem, the
RainSplashes or the storm. So the port has nothing of them to run.

The mutation pass mutates rain.c. Where the entry points are called
(the End and the Begin of the track flow, and World::DoTimestep) is
checked by trackflow_check and world_check, with mutations of their own.

    python tools/rain_check.py
    python tools/rain_check.py --mutate [--only a,b]
    python tools/rain_check.py --dump out/rain
"""
import argparse
import hashlib
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import mipsdis
import physicscar_check as pcc
from mipsemu import Emu

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/rain_test.c"
RAC = "3DS Files/source/rain.c"
SOURCES = [HARNESS, RAC]
HARNESS_TIMEOUT = 20

GP = 0x00328bf0
VIEW = 0x01000000

ENTRY = [("L", "rain_Load__Fv"), ("U", "rain_Unload__Fv"),
         ("T", "rain_TimeStep__Ff"), ("R", "rain_Render__FP5eView")]

# dt: zero, both signs, small and large, the denormals, the infinities and a
# NaN.
DTS = [0x00000000, 0x80000000, 0x3c888889, 0x3d088889, 0xbf800000,
       0x00000001, 0x807fffff, 0x7f7fffff, 0x7f800000, 0xff800000,
       0x7fc00000, 0x49742400]


def script():
    ops = ["L", "U", "L", "L", "U", "U"]
    ops += ["T %08x" % b for b in DTS]
    ops += ["R %d" % k for k in (0, 1, 2, 7, 255)]
    ops += ["N", "L", "T 3c888889", "R 3", "U", "R 4", "T 00000000", "L"]
    return ops


# ================================================================ the model

def fill(k, n=128):
    return bytes((k * 37 + i * 11 + 5) & 0xff for i in range(n))


SAVED = list(range(16, 24)) + [28, 29, 30, 31]


class Model(object):
    def __init__(self):
        self.e = Emu(ieee=True)
        self.icounts = {}

    def call(self, sym, *args, dt=None):
        e = self.e
        if dt is not None:
            e.fpr[12] = dt
        regs = [e.reg[i] for i in SAVED]
        fprs = list(e.fpr[20:32])
        h = hashlib.sha1(e.mem).digest()
        view = e.read(VIEW, 128)
        for i, v in enumerate(args):
            e.reg[4 + i] = v
        e.reg[31] = e.RETURN
        e.run(e.addr_of(sym), limit=64)
        self.icounts.setdefault(sym, set()).add(e.icount)
        e.reg[31] = regs[-1]
        if e.read(VIEW, 128) != view:
            return "view changed"
        if hashlib.sha1(e.mem).digest() != h:
            return "memory changed"
        if [e.reg[i] for i in SAVED] != regs or list(e.fpr[20:32]) != fprs:
            return "registers changed"
        return "kept"

    def run(self, ops):
        out = []
        for op in ops:
            self.e.write(VIEW, fill(0))
            if op == "L":
                out.append("L " + self.call("rain_Load__Fv"))
            elif op == "U":
                out.append("U " + self.call("rain_Unload__Fv"))
            elif op.startswith("T "):
                b = int(op[2:], 16)
                out.append("T %08x %s" % (b, self.call("rain_TimeStep__Ff", dt=b)))
            elif op.startswith("R "):
                k = int(op[2:])
                self.e.write(VIEW, fill(k))
                out.append("R %d %s" % (k, self.call("rain_Render__FP5eView", VIEW)))
            elif op == "N":
                out.append("N " + self.call("rain_Render__FP5eView", 0))
        return out


# ================================================================ the image

# Every reference the scan finds, as "target: kind from". Anything the scan
# finds that is not here, or that is here and not found, is a failure.
EXPECTED = """
rain_Load__Fv: jal EndGameFlowLoadingTrackSpecific__Fv+0x54
rain_Unload__Fv: jal BeginGameFlowUnloadingTrackSpecific__Fv+0xb4
rain_TimeStep__Ff: jal DoTimestep__5Worldf+0x500
Cache__10RainSplashP3Car: j Respawn__10RainSplashRC8bVector3fP3Car+0x100
Recalc__10RainSplashfP8bVector3: jal Render__10RainSplashP5eView+0x80
Render__10RainSplashP5eView: jal SplashLoop__10RainSystemP5eView+0xa8
Respawn__10RainSplashRC8bVector3fP3Car: jal SplashLoop__10RainSystemP5eView+0x88
RenderStorm__FP5eViewP9eDmaChain: jal RenderAllStorms__FP9eDmaChain+0x28
SetStormType__Fi: jal OnMenuItemScroll__14PauseDebugMenu13ScreenMessageP18ScreenCallbackData+0x184
GetStormType__Fv: jal __14PauseDebugMenuUi+0xfc
GetStormType__Fv: jal OnMenuItemScroll__14PauseDebugMenu13ScreenMessageP18ScreenCallbackData+0x164
GetStormType__Fv: jal OnMenuItemScroll__14PauseDebugMenu13ScreenMessageP18ScreenCallbackData+0x18c
GetStormType__Fv: jal OnMenuItemScroll__14PauseDebugMenu13ScreenMessageP18ScreenCallbackData+0x1c0
GetStormTypeString__Fi: jal __14PauseDebugMenuUi+0x104
GetStormTypeString__Fi: jal OnMenuItemScroll__14PauseDebugMenu13ScreenMessageP18ScreenCallbackData+0x194
GetWeatherQuery__5eView: jal UpdateStorm__FP5eView+0xa4
GetWeatherQuery__5eView: jal CreateFogPalette__FP5eViewPUi+0x64
WeatherManQuery__FP12WeatherQueryP8bVector3: jal GetWeatherQuery__5eView+0x40
WeatherManQuery__FP12WeatherQueryP8bVector3: jal UpdateWeather__10SoundScape+0x84
rain_pos: lui Update__10RainSystemP5eView+0x50
rain_default_texture: gp Render__10RainSplashP5eView+0x88
StormInfo: lui UpdateStorm__FP5eView+0x24
StormInfo: lui RenderStorm__FP5eViewP9eDmaChain+0x24
StormInfo: lui _GLOBAL_$I$FloatingVBlankTimeMin+0x440
StormInfo: word LumaQuant+0x18
StormInfo: word LumaQuant+0x44
StormInfo: word ascii_special+0x2c
RainStorm: lui UpdateStorm__FP5eView+0xc4
RainStorm: lui UpdateStorm__FP5eView+0x258
RainStorm: lui RenderStorm__FP5eViewP9eDmaChain+0x7c
"""
# The three words are table values that fall in StormInfo's range:
# LumaQuant's are the IPU's quantiser, and ascii_special's are character
# classes. Neither table holds pointers.

CODE = ["rain_Load__Fv", "rain_Unload__Fv", "rain_TimeStep__Ff",
        "rain_Render__FP5eView",
        "__10RainSystem", "_$_10RainSystem", "Update__10RainSystemP5eView",
        "Render__10RainSystemP5eView", "SplashLoop__10RainSystemP5eView",
        "TweakSplashes__10RainSystem",
        "Cache__10RainSplashP3Car", "Recalc__10RainSplashfP8bVector3",
        "Render__10RainSplashP5eView", "Respawn__10RainSplashRC8bVector3fP3Car",
        "UpdateStorm__FP5eView", "RenderStorm__FP5eViewP9eDmaChain",
        "RenderAllStorms__FP9eDmaChain", "SetStormType__Fi",
        "GetStormType__Fv", "GetStormTypeString__Fi",
        "GetWeatherQuery__5eView", "WeatherManQuery__FP12WeatherQueryP8bVector3",
        "UpdateWeather__10SoundScape"]
DATA = ["rainSystems", "rain_active", "rain_pos", "rain_default_texture",
        "DrawStorm", "StormInfo", "RainStorm", "SnowStorm", "WaterSpray"]

# Opcodes that take a base register and a signed offset (addiu and the
# loads and stores).
BASED = {0x09, 0x1a, 0x1b, 0x1e, 0x1f, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25,
         0x26, 0x27, 0x28, 0x29, 0x2a, 0x2b, 0x2c, 0x2d, 0x2e, 0x31, 0x36,
         0x37, 0x39, 0x3e, 0x3f}


def references(elf):
    targets = []
    for n in CODE:
        a = elf.syms[n][0]
        targets.append((a, a + 1, n))
    for n in DATA:
        a, size = elf.syms[n]
        targets.append((a, a + max(size, 1), n))

    def hit(v):
        for lo, hi, n in targets:
            if lo <= v < hi:
                return n
        return None

    refs = []
    for s in elf.secs:
        if s["type"] == 8 or not s["addr"] or not (s["flags"] & 2):
            continue
        d = elf.data[s["off"]:s["off"] + s["size"]]
        code = s["flags"] & 4
        his, cur = {}, None
        for i in range(0, len(d) - 3, 4):
            addr = s["addr"] + i
            w = struct.unpack_from("<I", d, i)[0]
            if not code:
                n = hit(w)
                if n:
                    refs.append("%s: word %s" % (n, elf.label(addr)))
                continue
            lab = elf.label(addr)
            fn = lab.split("+")[0] if lab else None
            if fn != cur:
                cur, his = fn, {}
            op = w >> 26
            rs, rt = (w >> 21) & 31, (w >> 16) & 31
            imm = w & 0xffff
            simm = imm - 0x10000 if imm & 0x8000 else imm
            if op in (2, 3):
                n = hit((addr & 0xf0000000) | ((w & 0x03ffffff) << 2))
                if n:
                    refs.append("%s: %s %s" % (n, "jal" if op == 3 else "j", lab))
                continue
            if op == 0x0f:
                his[rt] = imm << 16
                continue
            if op in BASED:
                v, kind = None, None
                if rs == 28:
                    v, kind = (GP + simm) & 0xffffffff, "gp"
                elif rs in his:
                    v, kind = (his[rs] + simm) & 0xffffffff, "lui"
                n = hit(v) if v is not None else None
                if n:
                    refs.append("%s: %s %s" % (n, kind, lab))
            # Whatever this writes no longer holds a lui's value.
            if op in (0, 0x1c):
                his.pop((w >> 11) & 31, None)
            elif 0x08 <= op <= 0x0e or 0x18 <= op <= 0x1b or op in (0x1e, 0x37) \
                    or 0x20 <= op <= 0x27:
                his.pop(rt, None)
            elif (op == 0x11 and rs in (0, 1, 2)) or (op == 0x12 and rs in (1, 2)):
                his.pop(rt, None)
    return refs


def image_facts(model):
    """The image's side, as (ok, line) pairs."""
    e = model.e
    elf = e.elf
    out = []
    for _k, sym in ENTRY:
        a = elf.syms[sym][0]
        words = struct.unpack("<2I", elf.read(a, 8))
        counts = sorted(model.icounts.get(sym, ()))
        ok = words == (0x03e00008, 0) and counts == [1]
        out.append((ok, "%s: %08x %08x, %s instructions run" % (
            sym, words[0], words[1], ",".join(map(str, counts)))))

    # The storm's three accessors.
    a = elf.syms["SetStormType__Fi"][0]
    words = struct.unpack("<2I", elf.read(a, 8))
    out.append((words == (0x03e00008, 0),
                "SetStormType__Fi: %08x %08x" % words))
    for t in (-1, 0, 1, 2, 3, 99):
        v = e.call("GetStormType__Fv")
        s = e.call("GetStormTypeString__Fi", t & 0xffffffff)
        text = e.read(s & 0xffffffff, 8).split(b"\0")[0].decode("latin-1")
        out.append((v == 0 and text == "None",
                    "type %d: GetStormType %d, GetStormTypeString %08x %r"
                    % (t, v, s & 0xffffffff, text)))

    found = references(elf)
    want = [l for l in EXPECTED.strip().split(NL)]
    for l in found:
        out.append((l in want, "ref " + l))
    for l in want:
        if l not in found:
            out.append((False, "ref MISSING " + l))
    return out


def model(ops):
    m = Model()
    lines = m.run(ops)
    return m, lines


# ============================================================== the harness

def build_harness(tmp, name="rain_test"):
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


def encode(ops):
    return NL.join(ops) + NL


diff = pcc.diff

# ============================================================ the mutations

MUTATIONS = [
    ("render-writes-view", RAC,
     "void rain_Render(struct eView *view)\n{\n    (void)view;",
     "void rain_Render(struct eView *view)\n{\n    if (view)\n"
     "        ((unsigned char *)view)[5] ^= 1;"),
    ("render-clears-view", RAC,
     "void rain_Render(struct eView *view)\n{\n    (void)view;",
     "void rain_Render(struct eView *view)\n{\n    if (view)\n"
     "        ((unsigned char *)view)[127] = 0;"),
    ("render-crashes-on-null", RAC,
     "void rain_Render(struct eView *view)\n{\n    (void)view;",
     "void rain_Render(struct eView *view)\n{\n"
     "    ((volatile unsigned char *)view)[0] = ((unsigned char *)view)[0];"),
    ("render-renders-nothing-loops", RAC,
     "void rain_Render(struct eView *view)\n{\n    (void)view;",
     "void rain_Render(struct eView *view)\n{\n"
     "    while (view && ((volatile unsigned char *)view)[0] != 0x42)\n"
     "        ;"),
    ("timestep-loops-on-nan", RAC,
     "void rain_TimeStep(float dt)\n{\n    (void)dt;",
     "void rain_TimeStep(float dt)\n{\n    while (dt != dt)\n        ;"),
]

# Mutations that survive because they change nothing the image can tell.
EQUIVALENT = set()


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    _m, base = model(sc)
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
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if text.count(probe) != 1:
            missing.append(name)
            print("  %-44s PATTERN %s" % (
                name, "NOT FOUND" if not text.count(probe) else "NOT UNIQUE"))
            continue
        new = text.replace(probe, repl, 1)
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
    m, lines = model(sc)
    facts = image_facts(m)
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
        d.with_suffix(".image").write_text(
            NL.join(("   " if ok else "BAD") + " " + l for ok, l in facts) + NL)

    bad = [l for ok, l in facts if not ok]
    for l in bad:
        print("image: " + l)
    refs = sum(1 for _ok, l in facts if l.startswith("ref "))
    n = diff(lines, harness)
    print("image: %d facts, %d references, %d wrong" % (len(facts), refs, len(bad)))
    print("%d calls, %d lines, %d differ" % (len(sc), len(harness), n))
    sys.exit(1 if (n or rc or bad) else 0)


if __name__ == "__main__":
    main()
