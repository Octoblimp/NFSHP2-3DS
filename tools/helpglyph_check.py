#!/usr/bin/env python3
"""Build and run tools/src/helpglyph_test.c: the 3DS key each help
character draws as (helpglyph.c), held to joyhid.c's map in a race and to
main.c's frontend keys in the menus, and the cop's Blurb rewritten. Also
checks that `3DS Files/data/buttons3ds.bin` is the sheet
tools/buttons3ds_make.py draws.

    python tools/helpglyph_check.py
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buttons3ds_make
import hostbuild

SOURCES = ["tools/src/helpglyph_test.c",
           "3DS Files/source/helpglyph.c",
           "3DS Files/source/joyhid.c"]


def main():
    ok = True
    if buttons3ds_make.OUT.read_bytes() != buttons3ds_make.sheet().tobytes():
        print("FAIL %s is not what buttons3ds_make.py draws"
              % buttons3ds_make.OUT)
        ok = False
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, "helpglyph_test")
        r = subprocess.run([str(exe)], capture_output=True, text=True,
                           timeout=60)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return 0 if ok and r.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
