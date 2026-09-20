#!/usr/bin/env python3
r"""Build a `3DS Files/source` module for the host, so it can be tested.

The modules under `3DS Files/source` that only parse data -- bchunk, texpack,
bfont, langtab -- are deliberately free of <3ds.h>, so the same code that will
run on the handheld can be compiled here and checked against the Python tools
that cracked the formats. This is the compile half of that; the harnesses live
in tools/src/ and the checkers next to this file.

On this machine the only host compiler is the one inside devkitPro's msys2,
and it finds its own /usr/include only when it runs in that environment --
invoked from Git Bash it cannot even locate stdio.h. So: try `cc` directly,
then retry through the msys2 login shell, which is what tools/build_cia.ps1
does for `make` and for the same underlying reason.
"""
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "3DS Files" / "source"
BS = chr(92)
NL = chr(10)

MSYS_BASH = Path("C:/devkitPro/msys2/usr/bin/bash.exe")
FLAGS = ["-O2", "-std=c11", "-Wall", "-Wextra"]


def msys(path):
    """A Windows path as msys2 spells it: C:@foo -> /c/foo (@ = backslash)."""
    p = str(path).replace(BS, "/")
    if len(p) > 1 and p[1] == ":":
        p = "/" + p[0].lower() + p[2:]
    return p


def quote(path):
    return "'" + msys(path).replace("'", "'" + BS + "''") + "'"


def build(tmp, sources, name="hosttest", flags=None):
    """Compile `sources` into `tmp`, returning the executable's path."""
    flags = list(flags or FLAGS)
    srcs = [Path(s) if Path(s).is_absolute() else (ROOT / s) for s in sources]
    for s in srcs:
        if not s.exists():
            sys.exit("no such source: %s" % s)
    exe = Path(tmp) / (name + (".exe" if os.name == "nt" else ""))
    direct_err = ""

    cc = (os.environ.get("CC") or shutil.which("cc") or shutil.which("gcc")
          or shutil.which("clang"))
    if cc:
        cmd = ([cc] + flags + ["-I", str(SRC), "-o", str(exe)]
               + [str(x) for x in srcs])
        # devkitPro's msys2 gcc takes its TMPDIR from the Windows environment
        # and then resolves it against the msys root, where it does not exist,
        # so cc1 cannot write its .s.
        env = dict(os.environ)
        env.setdefault("TMPDIR", "/tmp")
        r = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if r.returncode == 0:
            if r.stderr.strip():
                print("compiler warnings:" + NL + r.stderr.rstrip())
            return exe
        direct_err = r.stdout + r.stderr

    if MSYS_BASH.exists():
        script = Path(tmp) / "build.sh"
        body = ("set -e" + NL + "gcc %s -I %s -o %s %s" + NL) % (
            " ".join(flags), quote(SRC), quote(exe),
            " ".join(quote(x) for x in srcs))
        with io.open(script, "w", encoding="utf-8", newline=NL) as fh:
            fh.write(body)
        r = subprocess.run([str(MSYS_BASH), "-l", msys(script)],
                           capture_output=True, text=True)
        if r.returncode == 0:
            if r.stderr.strip():
                print("compiler warnings:" + NL + r.stderr.rstrip())
            return exe
        sys.stderr.write(r.stdout + r.stderr)
        sys.exit("compile failed (msys2 bash)")

    if not cc:
        sys.exit("no host C compiler found (set CC)")
    sys.stderr.write(direct_err)
    sys.exit("compile failed")
