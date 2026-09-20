#!/usr/bin/env python3
"""Check the streaming texture reader against the whole-file one.

`3DS Files/source/texsrc.c` reads a texture pack off the card a texture at a
time instead of holding the file in memory, because CARS\\TEXTURES.BIN is
15,300,536 bytes and a single car uses about 400 KB of it. It does not decode
anything itself -- it stages the two ranges one texture needs and hands
texpack.c a TexPack that addresses the staging buffer -- so what is under
test here is the arithmetic streaming adds and nothing else: where the
0x30300004 payload begins in the file, the 128-byte round-up applied to it,
and which two ranges a texture needs.

That arithmetic is exactly the kind that produces a plausible-looking image
made of the wrong bytes, so the oracle is texpack.c itself, whole-file, which
tools/texpack_check.py has already checked against tools/texture_convert.py
pixel for pixel. Both harnesses print the same table; this diffs them.

    python tools/texsrc_check.py
    python tools/texsrc_check.py --file extracted/GLOBAL/HUDTEX.BIN
    python tools/texsrc_check.py --level 2
"""
import argparse
import difflib
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild

NL = chr(10)
CR = chr(13)
BS = chr(92)

STREAM_SOURCES = ["tools/src/texsrc_test.c",
                  "3DS Files/source/texsrc.c",
                  "3DS Files/source/texpack.c",
                  "3DS Files/source/bchunk.c"]

WHOLE_SOURCES = ["tools/src/texpack_test.c",
                 "3DS Files/source/texpack.c",
                 "3DS Files/source/bchunk.c"]

# Every pack the geometry and the UI actually read from, plus HUDTEX and
# DYNTEX because they are the two that are neither 4bpp nor square and so
# exercise the level arithmetic hardest.
DEFAULT_FILES = ["extracted/CARS/TEXTURES.BIN",
                 "extracted/GLOBAL/GLOBALB.BUN",
                 "extracted/GLOBAL/INGAMEB.BUN",
                 "extracted/GLOBAL/HUDTEX.BIN",
                 "extracted/GLOBAL/DYNTEX.BIN",
                 "extracted/FRONTEND/FRONTB.BUN"]

MAX_LINES = 200000


def short_name(path):
    cut = [i for i, ch in enumerate(path) if ch in ("/", BS)]
    if len(cut) >= 2:
        return path[cut[-2] + 1:]
    return path[cut[-1] + 1:] if cut else path


def run(exe, path, level, tmp, tag):
    """Run one harness on one file. stdout goes to a file, never a pipe.

    See the note in tools/geometry_check.py: draining a pipe from a child
    that will not stop deadlocks the parent, and the timeout cannot rescue it
    because killing a cygwin-built exe from Windows does not reliably close
    its handles.
    """
    out = os.path.join(tmp, tag + ".txt")
    with open(out, "wb") as fh:
        try:
            r = subprocess.run([str(exe), path, "0", "--level", str(level)],
                               stdout=fh, stderr=subprocess.PIPE, timeout=600)
        except subprocess.TimeoutExpired:
            sys.exit("%s did not finish within 600s on %s" % (tag, path))
    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", "replace")
        sys.exit("%s failed on %s (exit %d):%s%s"
                 % (tag, path, r.returncode, NL, err or "(nothing on stderr)"))
    with open(out, "r", encoding="utf-8", errors="replace", newline="") as fh:
        text = fh.read()
    lines = text.replace(CR + NL, NL).rstrip(NL).split(NL)
    if len(lines) > MAX_LINES:
        sys.exit("%s printed %d lines on %s, which is not a transcript"
                 % (tag, len(lines), path))
    return [ln for ln in lines if ln]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", action="append",
                    help="check only this file (repeatable)")
    ap.add_argument("--level", type=int, default=None,
                    help="one mip level to decode; default is 0 and 1")
    ap.add_argument("--show", type=int, default=12,
                    help="differing lines to print per file")
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root)

    files = args.file or [p for p in DEFAULT_FILES if os.path.exists(p)]
    if not files:
        sys.exit("no texture packs found under extracted/")

    with tempfile.TemporaryDirectory() as tmp:
        stream = hostbuild.build(tmp, STREAM_SOURCES, name="texsrc_test")
        whole = hostbuild.build(tmp, WHOLE_SOURCES, name="texpack_test")

        # Level 0 on its own leaves the mip prefix in texsrc_stage()
        # untested -- at level 0 it is zero -- so the default is two levels,
        # which is what makes a single run of this checker complete.
        levels = [args.level] if args.level is not None else [0, 1]

        total, differ = 0, 0
        for level in levels:
            for path in files:
                if not os.path.exists(path):
                    sys.exit("no such file: %s" % path)
                a = run(whole, path, level, tmp, "texpack_test")
                b = run(stream, path, level, tmp, "texsrc_test")
                total += len(a)
                bad = [ln for ln in difflib.unified_diff(a, b, lineterm="",
                                                         n=0)][2:]
                if bad:
                    differ += len(bad)
                    print("%s level %d: %d textures, %d differ"
                          % (short_name(path), level, len(a), len(bad)))
                    for ln in bad[:args.show]:
                        print("   ", ln)
                elif len(a) != len(b):
                    differ += 1
                    print("%s level %d: whole-file %d lines, streaming %d"
                          % (short_name(path), level, len(a), len(b)))

    print("%d packs, %d levels, %d textures, %d differ"
          % (len(files), len(levels), total, differ))
    return 1 if differ else 0


if __name__ == "__main__":
    sys.exit(main())
