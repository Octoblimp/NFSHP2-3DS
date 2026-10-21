#!/usr/bin/env python3
"""Checks three of TASKS 46's cuts to trackview.c against the code they
replaced.

trackview.c draws through citro3d and does not build on the host, so the
functions are cut out of it, as they are now, into a program with a test
body from tools/src:

- sun: read_sun_rect, which reads a sun rect's depths back with each
  column's and row's place worked out once a rect (tiled_x, tiled_y), and
  what it calls. trackview_sun_test.inc holds it to the loop it replaced,
  a target_to_screen, floor and clamp a pixel, over 400,000 rects on
  random targets, aspects and buffers, and the split tiled_index to the
  whole one over and past the screen.
- tex: tex_bucket and find_texture, which find a texture's entry through
  open-addressed buckets, with load_texture's append and forget_all's
  emptying. trackview_tex_test.inc holds find_texture to the scan from the
  front it replaced over 4 million lookups, with the list filled to its
  end and emptied again.
- sort: sort_deferred, which sorts the held-back entries' indices and
  then moves each entry once, where qsort moved the 88-byte entries.
  trackview_sort_test.inc holds it to qsort of the entries with
  compare_deferred over 40,000 lists, NaN depths among them.

    python tools/trackview_cuts_check.py            the check
    python tools/trackview_cuts_check.py --mutate   and each MUTATIONS edit
                                                    must fail it

The mutations edit the text cut out, never trackview.c.
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
SRC = ROOT / "3DS Files/source/trackview.c"
HDR = ROOT / "3DS Files/source/trackview.h"
TESTS = ROOT / "tools/src"
TIMEOUT = 120

MUTATIONS = [
    ("sun", "col-past-target-read",
     "if (px < 0 || px >= q->targetW) {",
     "if (px < 0 || px > q->targetW) {"),
    ("sun", "row-off-target-read",
     "if (py < 0 || py >= q->targetH) {",
     "if (py < 0) {"),
    ("sun", "col-clamp-past-screen",
     "ix > 399 ? 399 : ix",
     "ix > 400 ? 400 : ix"),
    ("sun", "row-rounded",
     "(int)floorf(sy)",
     "(int)floorf(sy + 0.5f)"),
    ("sun", "row-no-half-pixel",
     "(float)py + 0.5f",
     "(float)py"),
    ("sun", "tile-rows-of-16",
     "(240u / 8u) * 64u",
     "(240u / 8u) * 32u"),
    ("sun", "morton-y-bit-moved",
     "((bx & 2u) << 1)",
     "((bx & 2u) << 2)"),
    ("sun", "off-target-word",
     "uint32_t z = 0xffffffu;",
     "uint32_t z = 0xfffffeu;"),
    ("tex", "entry-before",
     "return &v->texture[k];",
     "return &v->texture[k ? k - 1 : k];"),
    ("tex", "reset-keeps-buckets",
     "memset(v->texBucket, 0, sizeof v->texBucket);",
     "memset(v->texBucket, 0, 0);"),
    ("tex", "bucket-holds-index",
     "v->texBucket[b] = (uint16_t)v->numTextures;",
     "v->texBucket[b] = (uint16_t)(v->numTextures - 1);"),
    ("tex", "info-not-compared",
     "k < v->numTextures && v->texture[k].info == info",
     "k < v->numTextures"),
    ("tex", "append-elsewhere",
     "for (b = tex_bucket(info); v->texBucket[b] != 0;",
     "for (b = tex_bucket(info) ^ 1; v->texBucket[b] != 0;"),
    ("tex", "find-wraps-short",
     "h = (h + 1) & (TRACKVIEW_TEX_BUCKETS - 1)",
     "h = (h + 1) & (TRACKVIEW_TEX_BUCKETS / 2 - 1)"),
    # The sort's. Two edits were found equivalent and left out: the
    # indices started at 1 (every sort leaves order[] as 0, 1, 2, ...,
    # each place marked once its entry is in, so order[0] is 0), and
    # order[i] < i taken as placed (a cycle through an earlier place
    # was moved, and i marked, from that place).
    ("sort", "compares-itself",
     "&s_sortBase[*(const uint16_t*)pb]);",
     "&s_sortBase[*(const uint16_t*)pa]);"),
    ("sort", "last-left-out",
     "qsort(order, (size_t)n,",
     "qsort(order, (size_t)(n ? n - 1 : 0),"),
    ("sort", "held-from-its-source",
     "held = v->deferred[i];",
     "held = v->deferred[order[i]];"),
    ("sort", "moved-backwards",
     "v->deferred[j] = v->deferred[k];",
     "v->deferred[k] = v->deferred[j];"),
    ("sort", "cycle-not-marked",
     "            order[j]       = (uint16_t)j;\n        }",
     "        }"),
    ("sort", "held-not-put-back",
     "v->deferred[j] = held;",
     "v->deferred[j] = v->deferred[i];"),
]


def read(path):
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def func(src, name):
    m = re.search(r"^static [^\n;]*\b" + name + r"\([^;{]*\)\n\{", src, re.M)
    if not m:
        sys.exit("trackview.c: no %s" % name)
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
        sys.exit("trackview.h: no %s" % name)
    return m.group(0) + "\n"


def sun_program(src, hdr):
    return "".join([
        "#include <math.h>\n#include <stdint.h>\n#include <stdio.h>\n"
        "#include <stdlib.h>\n#include <string.h>\n",
        "#define SUN_ZBUFFER_SIZE 32\n",
        # The GS's Z range, player 1's in a race: PSMZ24's (eview.h).
        "typedef struct { float ZMin, ZMax, ZMin1, ZMax1, ZMin2, ZMax2; }"
        " eZRange;\n"
        "static const eZRange s_psmz24 = {\n"
        "    2.0000038146972656f, 4.0f, 2.0000152587890625f, 4.00390625f,\n"
        "    4.5f, 7.5f };\n"
        "static const eZRange* s_zRange = &s_psmz24;\n",
        block(src, "typedef struct {\n    uint32_t* dst;", "} SunRect;"),
        func(src, "target_to_screen"),
        func(src, "tiled_x"), func(src, "tiled_y"), func(src, "tiled_index"),
        func(src, "gs_z_of_depth"), func(src, "gs_z24"), func(src, "gs_z"),
        block(src, "static int32_t s_sunCol[",
              "s_sunRow[SUN_ZBUFFER_SIZE * SUN_ZBUFFER_SIZE];"),
        func(src, "read_sun_rect"),
        read(TESTS / "trackview_sun_test.inc"),
    ])


def tex_program(src, hdr):
    # load_texture's "if (!t) { ... }", which makes an entry, and
    # forget_all's line that empties the buckets.
    lt = func(src, "load_texture")
    a = lt.index("    if (!t) {\n")
    i = lt.index("{", a) + 1
    depth = 1
    while depth:
        depth += lt[i] == "{"
        depth -= lt[i] == "}"
        i += 1
    m = re.search(r"\n(    memset\(v->texBucket[^\n]*)\n",
                  func(src, "forget_all"))
    if not m:
        sys.exit("trackview.c: forget_all does not empty texBucket")
    return "".join([
        "#include <stdbool.h>\n#include <stdint.h>\n#include <stdio.h>\n"
        "#include <stdlib.h>\n#include <string.h>\n",
        define(hdr, "TRACKVIEW_MAX_TEXTURES"),
        define(hdr, "TRACKVIEW_TEX_BUCKET_BITS"),
        define(hdr, "TRACKVIEW_TEX_BUCKETS"),
        "typedef struct { uint32_t a[13]; } TextureInfo;\n"
        "typedef struct { const TextureInfo* info; int valid; } TrackTex;\n"
        "typedef struct {\n    TrackTex* texture;\n    int numTextures;\n"
        "    uint16_t texBucket[TRACKVIEW_TEX_BUCKETS];\n} TrackView;\n",
        func(src, "tex_bucket"),
        func(src, "find_texture"),
        "static TrackTex* append(TrackView* v, const TextureInfo* info)\n"
        "{\n    TrackTex* t = NULL;\n\n" + lt[a:i] + "\n"
        "    memset(t, 0, sizeof *t);\n    t->info = info;\n"
        "    return t;\n}\n",
        "static void reset(TrackView* v)\n{\n    v->numTextures = 0;\n"
        + m.group(1) + "\n}\n",
        read(TESTS / "trackview_tex_test.inc"),
    ])


def sort_program(src, hdr):
    return "".join([
        "#include <math.h>\n#include <stdbool.h>\n#include <stdint.h>\n"
        "#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n",
        define(hdr, "TRACKVIEW_MAX_DEFERRED"),
        "typedef union { float m[16]; } C3D_Mtx;\n",
        block(hdr, "typedef struct {\n    C3D_Mtx     modelView;",
              "} TrackDeferred;"),
        "typedef struct {\n"
        "    TrackDeferred deferred[TRACKVIEW_MAX_DEFERRED];\n"
        "    int numDeferred;\n} TrackView;\n",
        func(src, "compare_deferred"),
        block(src, "static const TrackDeferred* s_sortBase;", ";"),
        func(src, "compare_deferred_at"),
        func(src, "sort_deferred"),
        read(TESTS / "trackview_sort_test.inc"),
    ])


PROGRAMS = {"sun": sun_program, "tex": tex_program, "sort": sort_program}


def run(which, src, hdr, quiet=False):
    with tempfile.TemporaryDirectory() as tmp:
        gen = Path(tmp) / ("trackview_%s_gen.c" % which)
        gen.write_bytes(PROGRAMS[which](src, hdr).encode("utf-8"))
        try:
            exe = hostbuild.build(tmp, [str(gen)],
                                  name="trackview_%s_test" % which,
                                  quiet=quiet)
        except SystemExit:
            return 1, "did not compile"
        try:
            r = subprocess.run([str(exe)], capture_output=True, text=True,
                               timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return None, "hung"
    lines = r.stdout.strip().splitlines()
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
        # The test bodies hold the old code, so a pattern is looked for in
        # trackview.c, and its edit must reach the text cut out of it.
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
