#!/usr/bin/env python3
r"""Check the 3DS C font reader against tools/font_dump.py.

`3DS Files/source/bfont.c` reimplements the glyph lookup and the kerning
walk. The kerning one is the interesting half: mKerningTable is a pair index
into a shared array, not a byte offset, and getting that wrong still produces
plausible-looking numbers. So this diffs every glyph's metrics and its total
kerning against the Python reader.

Usage:
    python tools/bfont_check.py extracted/GLOBAL/GLOBALB.BUN
    python tools/bfont_check.py extracted/GLOBAL/*.BUN extracted/FRONTEND/*.BUN
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import font_dump as fd                          # noqa: E402
import hostbuild                                # noqa: E402

SOURCES = ["tools/src/bfont_test.c",
           "3DS Files/source/bfont.c",
           "3DS Files/source/bchunk.c"]


def num(x):
    return "%g" % x


def py_lines(path):
    out = []
    for chunk in fd.find_fonts(Path(path).read_bytes()):
        f = fd.Font(chunk)
        out.append("font %08x %d %d %s"
                   % (f.hash, f.num_glyphs, f.num_kerning, num(f.height)))
        for i in range(f.num_glyphs):
            gid = fd.struct.unpack_from("<H", chunk,
                                        f.glyph_off + i * fd.GLYPH_SIZE)[0]
            g = f.glyphs[f.by_id[gid]]
            total = sum(f.kerning(gid, ch) for ch in range(256))
            out.append("g %d %d %s %s %s %s %s %s %s"
                       % (g["id"], g["pairs"], num(g["x"]), num(g["y"]),
                          num(g["width"]), num(g["height"]), num(g["advance"]),
                          num(g["offset"]), num(total)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--max-report", type=int, default=10)
    args = ap.parse_args()

    bad_total = 0
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, "bfont_test")
        for path in args.files:
            r = subprocess.run([str(exe), str(path)], capture_output=True,
                               text=True)
            if r.returncode:
                sys.stderr.write(r.stderr)
                sys.exit("bfont_test failed on %s" % path)
            c = r.stdout.split(chr(10))
            c = [x for x in c if x.strip()]
            p = py_lines(path)
            bad = [(i, c[i] if i < len(c) else None, p[i] if i < len(p) else None)
                   for i in range(max(len(c), len(p)))
                   if (c[i] if i < len(c) else None)
                   != (p[i] if i < len(p) else None)]
            print("%-34s %d fonts, %d lines, %d differ"
                  % (Path(path).name,
                     sum(1 for x in p if x.startswith("font ")), len(p),
                     len(bad)))
            for i, cv, pv in bad[:args.max_report]:
                print("  [%d] C=%r py=%r" % (i, cv, pv))
            if len(bad) > args.max_report:
                print("  ... and %d more" % (len(bad) - args.max_report))
            bad_total += len(bad)
    return 1 if bad_total else 0


if __name__ == "__main__":
    sys.exit(main())
