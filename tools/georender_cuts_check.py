#!/usr/bin/env python3
"""Checks TASKS 46's cut to georender.c against the code it replaced.

georender.c draws through citro3d and does not build on the host, so the
function is cut out of it, as it is now, into a program with a test body
from tools/src:

- fog: georender_fog_fill, which leaves the fog's texture as it is, with
  no flush, when its fractions are the same to the bit as the last fill's,
  and works out each column's byte once. georender_fog_test.inc holds it
  to the fill it replaced over 300,000 fills of fractions that mostly
  repeat, as a race's do, and else change by a bit, a few or all, NaN,
  infinity, -0 and any bits among them, with the texture now and then
  made again or failing to be: what the GPU reads after each fill must be
  the old fill's bytes, and a fill must flush exactly when its fractions
  are new.

    python tools/georender_cuts_check.py            the check
    python tools/georender_cuts_check.py --mutate   and each MUTATIONS edit
                                                    must fail it

The mutations edit the text cut out, never georender.c.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "3DS Files/source/georender.c"
HDR = ROOT / "3DS Files/source/georender.h"
TESTS = ROOT / "tools/src"
TIMEOUT = 120

MUTATIONS = [
    ("fog", "skip-without-texture",
     "if (fog->filled && memcmp(fog->keep, keep, sizeof fog->keep) == 0)",
     "if (memcmp(fog->keep, keep, sizeof fog->keep) == 0)"),
    ("fog", "new-texture-kept-filled",
     "        fog->filled = false;\n",
     "        (void)0;\n"),
    ("fog", "last-step-not-compared",
     "memcmp(fog->keep, keep, sizeof fog->keep) == 0",
     "memcmp(fog->keep, keep, sizeof fog->keep - 4) == 0"),
    ("fog", "fractions-not-kept",
     "memcpy(fog->keep, keep, sizeof fog->keep);",
     "memcpy(fog->keep, keep, 0);"),
    ("fog", "never-filled",
     "fog->filled = true;",
     "fog->filled = false;"),
    ("fog", "no-flush",
     "GSPGPU_FlushDataCache(p, fog->tex.size);",
     "(void)p;"),
    ("fog", "half-flushed",
     "GSPGPU_FlushDataCache(p, fog->tex.size);",
     "GSPGPU_FlushDataCache(p, fog->tex.size / 2);"),
    ("fog", "column-past-last-step",
     "keep[k < GEO_FOG_STEPS ? k : GEO_FOG_STEPS]",
     "keep[k < GEO_FOG_STEPS ? k : GEO_FOG_STEPS - 1]"),
    ("fog", "clamp-high-late",
     "f > 1.0f ? 1.0f : f;\n        col[k]",
     "f > 1.5f ? 1.0f : f;\n        col[k]"),
    ("fog", "unrounded",
     "col[k] = (uint8_t)(f * 255.0f + 0.5f);",
     "col[k] = (uint8_t)(f * 255.0f);"),
    ("fog", "morton-y-bit-moved",
     "(m >> 1 & 2)\n",
     "(m >> 2 & 2)\n"),
    ("fog", "tile-short",
     "p[k * 64 + m] = col[k * 8 +",
     "p[k * 63 + m] = col[k * 8 +"),
]

PRELUDE = """\
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    void*    data;
    uint32_t size;
    uint16_t width, height;
} C3D_Tex;

enum { GPU_A8 = 8, GPU_LINEAR = 1, GPU_CLAMP_TO_EDGE = 2 };

static void* s_texData;
static bool  s_failInit;

static bool C3D_TexInit(C3D_Tex* t, uint16_t w, uint16_t h, int fmt)
{
    if (s_failInit || fmt != GPU_A8) {
        return false;
    }
    t->width  = w;
    t->height = h;
    t->size   = (uint32_t)w * h;
    t->data   = malloc(t->size);
    // What a new texture holds is not the fog's.
    memset(t->data, 0xa5, t->size);
    s_texData = t->data;
    return true;
}

static void C3D_TexSetFilter(C3D_Tex* t, int mag, int min)
{
    (void)t; (void)mag; (void)min;
}

static void C3D_TexSetWrap(C3D_Tex* t, int s, int u)
{
    (void)t; (void)s; (void)u;
}

void GSPGPU_FlushDataCache(const void* p, uint32_t n);
"""


def read(path):
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def func(src, name):
    m = re.search(r"^[a-z][^\n;]*\b" + name + r"\([^;{]*\)\n\{", src, re.M)
    if not m:
        sys.exit("georender.c: no %s" % name)
    i = m.end()
    depth = 1
    while depth:
        depth += src[i] == "{"
        depth -= src[i] == "}"
        i += 1
    return src[m.start():i] + "\n"


def block(src, start, end):
    a = src.index(start)
    return src[a:src.index(end, a) + len(end)] + "\n"


def define(hdr, name):
    m = re.search(r"^#define " + name + r"\b[^\n]*", hdr, re.M)
    if not m:
        sys.exit("georender.h: no %s" % name)
    return m.group(0) + "\n"


def fog_program(src, hdr):
    return "".join([
        PRELUDE,
        define(hdr, "GEO_FOG_STEPS"),
        define(hdr, "GEO_FOG_TEX_W"),
        block(hdr, "typedef struct {\n    C3D_Tex tex;", "} GeoFog;"),
        func(src, "georender_fog_fill"),
        read(TESTS / "georender_fog_test.inc"),
    ])


PROGRAMS = {"fog": fog_program}


def run(which, src, hdr, quiet=False):
    with tempfile.TemporaryDirectory() as tmp:
        gen = Path(tmp) / ("georender_%s_gen.c" % which)
        gen.write_bytes(PROGRAMS[which](src, hdr).encode("utf-8"))
        try:
            exe = hostbuild.build(tmp, [str(gen)],
                                  name="georender_%s_test" % which,
                                  quiet=quiet)
        except SystemExit:
            return 1, "did not compile"
        try:
            r = subprocess.run([str(exe)], capture_output=True, text=True,
                               timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return None, "hung"
    lines = r.stdout.strip().splitlines()
    if not quiet:
        for line in lines[:-1]:
            print("  " + line)
    return r.returncode, lines[-1] if lines else "(no output)"


def check(src, hdr):
    ok = True
    for which in PROGRAMS:
        rc, last = run(which, src, hdr)
        print("%s: %s" % (which, last))
        ok = ok and rc == 0 and last.endswith(" 0 differ")
    return ok


def mutate(src, hdr):
    caught = missing = 0
    for which, name, before, after in MUTATIONS:
        # The test body holds the old code, so a pattern is looked for in
        # georender.c, and its edit must reach the text cut out of it.
        edited = src.replace(before, after)
        if (src.count(before) != 1
                or PROGRAMS[which](edited, hdr) == PROGRAMS[which](src, hdr)):
            print("  %-24s PATTERN NOT FOUND" % name)
            missing += 1
            continue
        rc, last = run(which, edited, hdr, quiet=True)
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
    src, hdr = read(SRC), read(HDR)
    ok = check(src, hdr)
    if ok and args.mutate:
        ok = mutate(src, hdr)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
