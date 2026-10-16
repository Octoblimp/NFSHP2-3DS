#!/usr/bin/env python3
"""Build and run tools/src/helpmenu_test.c: retail's tHelpMenu as
helpmenu.c has it -- SplitHelp, the summon and dismiss, the slide and its
screen, the override and the screens' lines.

    python tools/helpmenu_check.py
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild

SOURCES = ["tools/src/helpmenu_test.c",
           "3DS Files/source/helpmenu.c",
           "3DS Files/source/banim.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c"]


def main():
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, "helpmenu_test")
        r = subprocess.run([str(exe)], capture_output=True, text=True,
                           timeout=60)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
