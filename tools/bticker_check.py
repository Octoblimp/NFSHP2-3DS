#!/usr/bin/env python3
"""Checks bGetTicker's scaling against the division it replaced.

On the 3DS, bGetTicker (3DS Files/source/bticker.c) turns the ARM11's
system tick into the EE's: t * 294912000 / 268111856, rounded down, in 32
bits. TASKS 46 took its two 64-bit divisions out -- the ARM11 has no
divide -- for a multiply by the reciprocal and one correction. This builds
bticker.c on the host with tools/src/bticker_test.c, which runs the new
function and the old division side by side over 106 million ticks, and
expects none to differ.

    python tools/bticker_check.py            the check
    python tools/bticker_check.py --mutate   and each MUTATIONS edit of
                                             bticker.c must fail it
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild

ROOT = Path(__file__).resolve().parent.parent
SRC = "3DS Files/source/bticker.c"
SOURCES = ["tools/src/bticker_test.c", SRC]
TIMEOUT = 600

MUTATIONS = [
    ("no-correction",
     "    if (*r >= BTICKER_3DS_HZ) {",
     "    if (0) {"),
    ("correction-only-above",
     "    if (*r >= BTICKER_3DS_HZ) {",
     "    if (*r > BTICKER_3DS_HZ) {"),
    ("reciprocal-rounded-up",
     "mul_high(n, UINT64_MAX / BTICKER_3DS_HZ)",
     "mul_high(n, UINT64_MAX / BTICKER_3DS_HZ + 1)"),
    ("mid-carry-dropped",
     " + (hl >> 32) + (mid >> 32);",
     " + (hl >> 32);"),
    ("mid-takes-all-of-lh",
     "(ll >> 32) + (uint32_t)lh",
     "(ll >> 32) + lh"),
    ("remainder-dropped",
     "+ div_3ds_hz(r * BTICKER_RATE_HZ, &unused)",
     "+ 0"),
]


def run(exe):
    try:
        r = subprocess.run([str(exe)], capture_output=True, text=True,
                           timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, "hung"
    lines = r.stdout.strip().splitlines()
    return r.returncode, lines[-1] if lines else "(no output)"


def check():
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="bticker_test")
        rc, last = run(exe)
    print(last)
    return rc == 0 and last.endswith(" 0 differ")


def mutate():
    path = ROOT / SRC
    text = path.read_text(encoding="utf-8", newline="")
    caught = missing = 0
    for name, before, after in MUTATIONS:
        if text.count(before) != 1:
            print("  %-24s PATTERN NOT FOUND" % name)
            missing += 1
            continue
        try:
            hostbuild.write_source(path, text.replace(before, after))
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = hostbuild.build(tmp, SOURCES, name="bticker_test",
                                          quiet=True)
                except SystemExit:
                    print("  %-24s did not compile (caught)" % name)
                    caught += 1
                    continue
                rc, last = run(exe)
        finally:
            hostbuild.write_source(path, text)
        if rc != 0:
            print("  %-24s caught: %s" % (name, last))
            caught += 1
        else:
            print("  %-24s SURVIVED: %s" % (name, last))
    print("%d mutations, %d caught, %d not found"
          % (len(MUTATIONS), caught, missing))
    return caught == len(MUTATIONS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    args = ap.parse_args()
    ok = check()
    if ok and args.mutate:
        ok = mutate()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
