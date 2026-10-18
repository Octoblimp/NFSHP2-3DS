#!/usr/bin/env python3
"""Checks the replay bar's retouch (`3DS Files/source/replaybar.c`), the
port's own: the five PS2 buttons of REPLAYBOTTOM_NEW drawn as the 3DS keys
the replay hears (TASKS 72g-5).

A model here does what replaybar.h promises, independently: each key's
columns wiped on the grey band's rows with its bare column's texel, then
its icon from the sheet laid over them, blended by the icon's alpha and
rounded to nearest, the bar's alpha kept. tools/src/replaybar_test.c runs
replaybar_retouch on the same inputs, and both print each row's CRC-32:

  - the disc's texture, decoded from extracted-retail/GLOBAL/INGAMEB.BUN,
    with the port's sheet (`3DS Files/data/buttons3ds.bin`);
  - random images with that sheet, and with random sheets whose alphas
    are 0, 255 or anything, so every column and row of the wipe and every
    blend shows;
  - what it must refuse, changing nothing: a texture of any other size, no
    image, no sheet, or a sheet a byte short.

    python tools/replaybar_check.py
    python tools/replaybar_check.py --mutate [--only a,b]
"""
import argparse
import os
import random
import struct
import sys
import tempfile
import time
import zlib
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import physicscar_check as pcc          # noqa: E402
import texture_convert as tc            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

HARNESS = "tools/src/replaybar_test.c"
RB = "3DS Files/source/replaybar.c"
SOURCES = [HARNESS, RB]
BUNDLE = ROOT / "extracted-retail" / "GLOBAL" / "INGAMEB.BUN"
SHEET = ROOT / "3DS Files" / "data" / "buttons3ds.bin"

W, H = 640, 88
TEX_HASH = 0xba7fcb6a                   # bStringHash("REPLAYBOTTOM_NEW")
SHEET_N, CELL_W, CELL_H, COLS = 128, 26, 28, 4
SHEET_SIZE = SHEET_N * SHEET_N * 4
BAND = range(29, 61)                    # the grey band's rows
CELL_TOP = 30
# Each key: wiped columns x0..x1, the bare column, the icon, the cell's
# left edge (replaybar.c's kKeys).
KEYS = [(14, 41, 8, 4, 15),             # L1 -> L
        (105, 133, 100, 1, 106),        # Square -> B
        (151, 179, 145, 0, 152),        # Cross -> A
        (194, 223, 188, 2, 196),        # Triangle -> X
        (239, 267, 232, 3, 240)]        # Circle -> Y


# ================================================================= model

def retouch(img, w, h, sheet, size):
    """replaybar_retouch, in place on bytearray `img` (or None): 1 or 0."""
    if (img is None or w != W or h != H or sheet is None
            or size < SHEET_SIZE):
        return 0
    for x0, x1, bare, icon, cx in KEYS:
        for y in BAND:
            s = (y * w + bare) * 4
            texel = img[s:s + 4]
            for x in range(x0, x1 + 1):
                d = (y * w + x) * 4
                img[d:d + 4] = texel
        ix, iy = (icon % COLS) * CELL_W, (icon // COLS) * CELL_H
        for y in range(CELL_H):
            for x in range(CELL_W):
                s = ((iy + y) * SHEET_N + ix + x) * 4
                a = sheet[s + 3]
                d = ((CELL_TOP + y) * w + cx + x) * 4
                for c in range(3):
                    img[d + c] = (sheet[s + c] * a + img[d + c] * (255 - a)
                                  + 127) // 255
    return 1


def rows(img, w, h):
    return ["row %d %08x" % (y, zlib.crc32(bytes(img[y * w * 4:
                                                     (y + 1) * w * 4])))
            for y in range(h)]


# ================================================================ inputs

def disc_bar():
    """REPLAYBOTTOM_NEW's texels as RGBA8 rows, texture_convert's decode."""
    buf = BUNDLE.read_bytes()
    off = 0
    while off + 8 <= len(buf):
        ctype, csize = struct.unpack_from("<II", buf, off)
        if ctype == tc.TEXTURE_PACK:
            _, info, data = tc.parse_pack(buf, off, csize)
            for t in tc.textures(info):
                if t["hash"] == TEX_HASH:
                    w, h, rgba = tc.decode(t, data)
                    if (w, h) != (W, H):
                        sys.exit("REPLAYBOTTOM_NEW is %dx%d" % (w, h))
                    return bytes(rgba)
        off += 8 + csize
    sys.exit("no REPLAYBOTTOM_NEW in %s" % BUNDLE)


def random_sheet(rng):
    out = bytearray(rng.randbytes(SHEET_SIZE))
    for i in range(3, SHEET_SIZE, 4):
        k = rng.random()
        out[i] = 0 if k < 0.3 else 255 if k < 0.6 else out[i]
    return bytes(out)


def cases(tmp):
    """(w, h, image bytes or None, sheet bytes or None, sheet size)."""
    rng = random.Random(7250)
    bar = disc_bar()
    sheet = SHEET.read_bytes()
    if len(sheet) != SHEET_SIZE:
        sys.exit("%s is %d bytes" % (SHEET, len(sheet)))
    out = [(W, H, bar, sheet, SHEET_SIZE)]
    for _ in range(4):
        out.append((W, H, rng.randbytes(W * H * 4), sheet, SHEET_SIZE))
    for _ in range(4):
        out.append((W, H, rng.randbytes(W * H * 4), random_sheet(rng),
                    SHEET_SIZE))
    big = random_sheet(rng) + rng.randbytes(100)
    out.append((W, H, rng.randbytes(W * H * 4), big, len(big)))
    # Refused, changing nothing.
    for w, h in ((W - 1, H), (W + 1, H), (W, H - 1), (W, H + 1), (H, W)):
        out.append((w, h, rng.randbytes(w * h * 4), sheet, SHEET_SIZE))
    out.append((W, H, None, sheet, SHEET_SIZE))
    out.append((W, H, bar, None, SHEET_SIZE))
    out.append((W, H, bar, sheet[:-1], SHEET_SIZE - 1))
    return out


def write_script(tmp, todo):
    lines = []
    for n, (w, h, img, sheet, size) in enumerate(todo):
        ip = sp = "-"
        if img is not None:
            ip = str(Path(tmp) / ("img%d.bin" % n))
            Path(ip).write_bytes(img)
        if sheet is not None:
            sp = str(Path(tmp) / ("sheet%d.bin" % n))
            Path(sp).write_bytes(sheet)
        lines.append("case %d %d %s %s %d" % (w, h, ip, sp, size))
    script = Path(tmp) / "script.txt"
    script.write_text("\n".join(lines) + "\n")
    return script


def model(todo):
    out = []
    for n, (w, h, img, sheet, size) in enumerate(todo):
        im = bytearray(img) if img is not None else None
        out.append("case %d ret %d" % (n, retouch(im, w, h, sheet, size)))
        if im is not None:
            out += rows(im, w, h)
    out.append("faults 0")
    return out


diff = pcc.diff


# ============================================================= mutations

def M(name, before, after):
    return (name, RB, before, after)


MUTATIONS = [
    # -- the refusals
    M("w-greater", "w != REPLAYBAR_TEX_W", "w > REPLAYBAR_TEX_W"),
    M("w-less", "w != REPLAYBAR_TEX_W", "w < REPLAYBAR_TEX_W"),
    M("h-greater", "h != REPLAYBAR_TEX_H", "h > REPLAYBAR_TEX_H"),
    M("h-less", "h != REPLAYBAR_TEX_H", "h < REPLAYBAR_TEX_H"),
    M("no-image-test", "if (rgba == NULL || w", "if (w"),
    M("no-sheet-test", "        || sheet == NULL\n", "\n"),
    M("sheet-le", "|| sheetSize < (size_t)", "|| sheetSize <= (size_t)"),
    M("sheet-bytes", "HELPGLYPH_SHEET * HELPGLYPH_SHEET * 4)",
      "HELPGLYPH_SHEET * HELPGLYPH_SHEET * 4 - 1)"),
    M("return-0", "    return 1;\n}", "    return 0;\n}"),
    # -- the band and the cells
    M("band-top", "#define BAND_TOP    29", "#define BAND_TOP    30"),
    M("band-bottom", "#define BAND_BOTTOM 60", "#define BAND_BOTTOM 59"),
    M("cell-top", "#define CELL_TOP    30", "#define CELL_TOP    31"),
    M("band-lt", "y <= BAND_BOTTOM", "y < BAND_BOTTOM"),
    M("cols-lt", "x <= kKeys[k].x1", "x < kKeys[k].x1"),
    M("keys-less", "k < REPLAYBAR_KEYS", "k < REPLAYBAR_KEYS - 1"),
    M("cell-h", "y < HELPGLYPH_CELL_H; y++", "y < HELPGLYPH_CELL_H - 1; y++"),
    M("cell-w", "x < HELPGLYPH_CELL_W; x++", "x < HELPGLYPH_CELL_W - 1; x++"),
    # -- the table
    M("l-x0", "{  14,  41,   8,", "{  15,  41,   8,"),
    M("l-x1", "{  14,  41,   8,", "{  14,  40,   8,"),
    M("l-bare", "{  14,  41,   8,", "{  14,  41,   9,"),
    M("l-icon", "HELPGLYPH_3DS_L,  15 }", "HELPGLYPH_3DS_R,  15 }"),
    M("l-cell", "HELPGLYPH_3DS_L,  15 }", "HELPGLYPH_3DS_L,  16 }"),
    M("b-x0", "{ 105, 133, 100,", "{ 106, 133, 100,"),
    M("b-bare", "{ 105, 133, 100,", "{ 105, 133, 101,"),
    M("b-icon", "HELPGLYPH_3DS_B, 106 }", "HELPGLYPH_3DS_X, 106 }"),
    M("a-x1", "{ 151, 179, 145,", "{ 151, 178, 145,"),
    M("a-cell", "HELPGLYPH_3DS_A, 152 }", "HELPGLYPH_3DS_A, 151 }"),
    M("x-bare", "{ 194, 223, 188,", "{ 194, 223, 187,"),
    M("x-icon", "HELPGLYPH_3DS_X, 196 }", "HELPGLYPH_3DS_B, 196 }"),
    M("y-x0", "{ 239, 267, 232,", "{ 240, 267, 232,"),
    M("y-cell", "HELPGLYPH_3DS_Y, 240 }", "HELPGLYPH_3DS_Y, 241 }"),
    # -- the wipe
    M("wipe-row", "rgba + ((size_t)y * w + kKeys[k].bare) * 4",
      "rgba + ((size_t)(y + 1) * w + kKeys[k].bare) * 4"),
    M("wipe-r", "                d[0] = s[0];\n", ""),
    M("wipe-a", "                d[3] = s[3];\n", ""),
    M("wipe-swap", "                d[1] = s[1];\n                d[2] = s[2];",
      "                d[1] = s[2];\n                d[2] = s[1];"),
    # -- the icon
    M("icon-col", "(uint32_t)(kKeys[k].icon % HELPGLYPH_COLS)",
      "(uint32_t)(kKeys[k].icon / HELPGLYPH_COLS)"),
    M("icon-row", "(uint32_t)(kKeys[k].icon / HELPGLYPH_COLS)\n",
      "(uint32_t)(kKeys[k].icon % HELPGLYPH_COLS)\n"),
    M("icon-cell-w", "                      * HELPGLYPH_CELL_W;",
      "                      * HELPGLYPH_CELL_H;"),
    M("icon-cell-h", "                      * HELPGLYPH_CELL_H;\n        uint32_t x",
      "                      * HELPGLYPH_CELL_W;\n        uint32_t x"),
    M("sheet-stride", "(size_t)(iy + y) * HELPGLYPH_SHEET + ix + x",
      "(size_t)(iy + y) * HELPGLYPH_CELL_W * HELPGLYPH_COLS + ix + x"),
    M("dest-row", "rgba + ((size_t)(CELL_TOP + y) * w",
      "rgba + ((size_t)(CELL_TOP + y + 1) * w"),
    M("alpha-chan", "uint32_t a = s[3];", "uint32_t a = s[2];"),
    M("skip-255", "if (a == 0)\n                    continue;",
      "if (a == 0 || a == 255)\n                    continue;"),
    M("skip-none", "if (a == 0)\n                    continue;",
      "if (0)\n                    continue;"),
    M("blend-alpha", "for (c = 0; c < 3; c++)", "for (c = 0; c < 4; c++)"),
    M("blend-two", "for (c = 0; c < 3; c++)", "for (c = 0; c < 2; c++)"),
    M("round-128", "+ 127u)", "+ 128u)"),
    M("round-0", "+ 127u)", "+ 0u)"),
    M("inverse-256", "(255u - a)", "(256u - a)"),
    M("divide-256", "/ 255u);", "/ 256u);"),
]

EQUIVALENT = {
    "skip-none":
        "Blending a texel of alpha 0 gives (d * 255 + 127) / 255, which is "
        "d for every byte, so the test only saves the work.",
}


def run_harness(exe, script, out, timeout=120):
    return mutpar.run_exe([exe, script], out, timeout)


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    with tempfile.TemporaryDirectory() as data:
        script = write_script(data, cases(data))
        with tempfile.TemporaryDirectory() as tmp:
            exe = hostbuild.build(tmp, SOURCES, name="replaybar_test")
            out = Path(tmp) / "base.txt"
            t0 = time.monotonic()
            rc = run_harness(exe, script, out)
            took = time.monotonic() - t0
            base = out.read_text(encoding="latin-1").splitlines()
            if rc != 0 or "faults 0" not in base:
                print("base already fails -- fix that before mutating")
                return 1
            print("base: %d lines, 0 faults" % len(base), flush=True)
        limit = mutpar.timeout_for(took)
        tally = mutpar.run_pass(
            todo, SOURCES, "replaybar_test",
            lambda exe, out: run_harness(exe, script, out, limit),
            base, diff, EQUIVALENT, jobs)
    return mutpar.summarize(todo, only, EQUIVALENT, tally)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--jobs", type=int, metavar="N",
                    help="with --mutate, mutants at once (default %d)"
                    % mutpar.JOBS)
    args = ap.parse_args()
    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None,
                             args.jobs))
    with tempfile.TemporaryDirectory() as data:
        todo = cases(data)
        script = write_script(data, todo)
        want = model(todo)
        with tempfile.TemporaryDirectory() as tmp:
            exe = hostbuild.build(tmp, SOURCES, name="replaybar_test")
            out = Path(tmp) / "out.txt"
            rc = run_harness(exe, script, out)
            got = out.read_text(encoding="latin-1").splitlines()
    n = diff(want, got)
    print("replaybar: %d cases, %d lines, %d differ%s"
          % (len(todo), len(want), n, "" if rc == 0 else ", exit %d" % rc))
    sys.exit(1 if n or rc else 0)


if __name__ == "__main__":
    main()
