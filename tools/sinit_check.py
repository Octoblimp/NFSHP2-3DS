#!/usr/bin/env python3
"""Cross-check 3DS Files/source/sinit.c against the image's __CTOR_LIST__.

The PS2 build runs every static constructor before main() does anything:
main+0x14 calls __main, which passes bCallFunctions the range after the
count word at __CTOR_LIST__ (0x00314f78), and bCallFunctions walks it
forwards. The port has no .ctors for the ones it has brought over, so
sinit_run() calls them by hand, one line each:

    car_static_init();          // [14]  0x001347c0 _GLOBAL_$I$fDraftFalloff

This holds every line to the image:

  * the symbol is a `_GLOBAL_$I$` and sits at the address given;
  * the address is the list entry at the index given;
  * the indices strictly increase, so the calls run in the list's order;
  * the function's own source names the same address, so the line and the
    port it calls cannot drift apart;
  * every `*_static_init` defined anywhere in 3DS Files/source is called
    exactly once -- a ported initialiser nothing runs is the bug this file
    exists to stop -- and main.c calls sinit_run() exactly once.

Nothing here is compiled; the ARM build compiles sinit.c with the rest.

    python tools/sinit_check.py
    python tools/sinit_check.py --mutate
"""
import argparse
import os
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bmath_check

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "3DS Files" / "source"
ELF = bmath_check.ELF

LINE = re.compile(r"^\s+(\w+)\(\);\s+//\s+\[(\d+)\]\s+(0x[0-9a-f]{8})\s+(\S+)\s*$")
DEF = re.compile(r"^void\s+(\w+_static_init)\s*\(\s*void\s*\)\s*$", re.M)

# The one ported static constructor that is not a *_static_init: the slot
# pool manager, whose port predates the naming.
EXTRA = {"bSlotPoolManagerInit": "bslotpool.c"}


def ctor_list():
    base = ELF.syms["__CTOR_LIST__"][0]
    n = struct.unpack("<I", ELF.read(base, 4))[0]
    return [struct.unpack("<I", ELF.read(base + 4 + 4 * i, 4))[0]
            for i in range(n)]


def sources():
    out = {}
    for p in sorted(SRC.glob("*.[ch]")):
        out[p.name] = p.read_bytes().decode("utf-8", "replace")
    return out


def check(sinit_text, main_text, src):
    errs = []
    ctors = ctor_list()
    # The list's own count word is 109, and __main is what reads it.
    if len(ctors) != 109:
        errs.append("__CTOR_LIST__ holds %d entries, not 109" % len(ctors))

    calls = []
    for ln in sinit_text.splitlines():
        m = LINE.match(ln)
        if m:
            calls.append((m.group(1), int(m.group(2)), int(m.group(3), 16),
                          m.group(4)))
    if not calls:
        errs.append("no calls found in sinit.c")

    last = 0
    for fn, idx, addr, sym in calls:
        if not sym.startswith("_GLOBAL_$I$"):
            errs.append("%s: %s is not a static constructor" % (fn, sym))
        if sym not in ELF.syms or ELF.syms[sym][0] != addr:
            errs.append("%s: %s is not at 0x%08x" % (fn, sym, addr))
        # The index as printed is 1-based past the count word, which is
        # how the doc and HANDOFF cite it: entry 1 is the first function.
        if not 1 <= idx <= len(ctors) or ctors[idx - 1] != addr:
            errs.append("%s: __CTOR_LIST__[%d] is not 0x%08x" % (fn, idx, addr))
        if idx <= last:
            errs.append("%s: index %d does not follow %d" % (fn, idx, last))
        last = idx

        # The function's own file, and its header, must name the address.
        home = EXTRA.get(fn)
        if home is None:
            homes = [n for n, t in src.items() if n.endswith(".c")
                     and re.search(r"^void\s+%s\s*\(" % fn, t, re.M)]
            home = homes[0] if len(homes) == 1 else None
        if home is None:
            errs.append("%s: not defined exactly once" % fn)
            continue
        pair = [home, home[:-2] + ".h"]
        tag = "0x%08x" % addr
        if not any(tag in src.get(n, "") for n in pair):
            errs.append("%s: neither %s names %s" % (fn, " nor ".join(pair),
                                                     tag))

    called = [c[0] for c in calls]
    defined = set()
    for n, t in src.items():
        if n.endswith(".c") and n != "sinit.c":
            defined.update(DEF.findall(t))
    defined.update(EXTRA)
    for fn in sorted(defined):
        k = called.count(fn)
        if k != 1:
            errs.append("%s is called %d times from sinit_run" % (fn, k))
    for fn in called:
        if fn not in defined:
            errs.append("%s is called but is not a static initialiser" % fn)

    # Code only: a call commented out is not a call.
    code = re.sub(r"/\*.*?\*/", "", main_text, flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)
    k = len(re.findall(r"\bsinit_run\(\);", code))
    if k != 1:
        errs.append("main.c calls sinit_run %d times" % k)
    return calls, errs


MUTATIONS = [
    ("swap-first-two",
     lambda s: s.replace(
         "    car_static_init();          // [14]  0x001347c0 _GLOBAL_$I$fDraftFalloff\r\n"
         "    rigidbody_static_init();    // [41]  0x00193d20 _GLOBAL_$I$__9RigidBodyP13RigidBodyInfo\r\n",
         "    rigidbody_static_init();    // [41]  0x00193d20 _GLOBAL_$I$__9RigidBodyP13RigidBodyInfo\r\n"
         "    car_static_init();          // [14]  0x001347c0 _GLOBAL_$I$fDraftFalloff\r\n"), None),
    ("drop-wheel",
     lambda s: s.replace(
         "    wheel_static_init();        // [44]  0x0019b558 _GLOBAL_$I$SliderPositionsX\r\n", ""),
     None),
    ("index-off-by-one",
     lambda s: s.replace("// [87]  0x0020ab48", "// [88]  0x0020ab48"), None),
    ("manager-is-the-dtor",
     lambda s: s.replace("// [103] 0x00240080 _GLOBAL_$I$bNewSlotPool__FiiPCci",
                         "// [103] 0x00240070 _GLOBAL_$D$bNewSlotPool__FiiPCci"),
     None),
    ("car-called-twice",
     lambda s: s.replace(
         "    bSlotPoolManagerInit();",
         "    car_static_init();          // [104] 0x001347c0 _GLOBAL_$I$fDraftFalloff\r\n"
         "    bSlotPoolManagerInit();"), None),
    ("main-never-runs-it", None,
     lambda m: m.replace("    sinit_run();", "    /* sinit_run(); */")),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    args = ap.parse_args()

    src = sources()
    sinit = src["sinit.c"]
    main_c = src["main.c"]

    calls, errs = check(sinit, main_c, src)
    for fn, idx, addr, sym in calls:
        print("  [%3d] 0x%08x %-26s %s" % (idx, addr, fn, sym))
    for e in errs:
        print("  " + e)
    print("%d calls, %d problems" % (len(calls), len(errs)))
    if errs:
        sys.exit(1)

    if args.mutate:
        caught = 0
        for name, fs, fm in MUTATIONS:
            s2 = fs(sinit) if fs else sinit
            m2 = fm(main_c) if fm else main_c
            if s2 == sinit and m2 == main_c:
                print("  %-22s PATTERN NOT FOUND" % name)
                continue
            _, e2 = check(s2, m2, dict(src, **{"sinit.c": s2, "main.c": m2}))
            if e2:
                caught += 1
                print("  %-22s caught: %s" % (name, e2[0]))
            else:
                print("  %-22s SURVIVED" % name)
        print("%d mutations, %d caught" % (len(MUTATIONS), caught))
        sys.exit(0 if caught == len(MUTATIONS) else 1)


if __name__ == "__main__":
    main()
