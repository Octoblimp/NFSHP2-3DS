#!/usr/bin/env python3
"""Build and run tools/src/joyhid_test.c: the 3DS button map (joyhid.c)
through the ported joystick layer, one key and one stick at a time, onto
the events joyhid.h promises for configuration 30.

    python tools/joyhid_check.py
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild

SOURCES = ["tools/src/joyhid_test.c",
           "3DS Files/source/joyhid.c",
           "3DS Files/source/joyevent.c",
           "3DS Files/source/joypad.c",
           "3DS Files/source/joylog.c",
           "3DS Files/source/replay.c",
           "3DS Files/source/demodisc.c",
           "3DS Files/source/realtime.c",
           "3DS Files/source/scannertab.c",
           "3DS Files/source/joystick.c",
           "3DS Files/source/graph.c"]


def main():
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, "joyhid_test")
        r = subprocess.run([str(exe)], capture_output=True, text=True,
                           timeout=60)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
