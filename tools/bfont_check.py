#!/usr/bin/env python3
r"""Check the 3DS C font reader against tools/font_dump.py.

`3DS Files/source/bfont.c` reimplements the glyph lookup and the kerning
walk. The kerning one is the interesting half: mKerningTable is a pair index
into a shared array, not a byte offset, and getting that wrong still produces
plausible-looking numbers. So this diffs every glyph's metrics and its total
kerning against the Python reader, and then runs retail's own
Font::GetKerning (0x00140098) on the emulator for every pair of every glyph,
plus a few characters each glyph does not list, against the reader.

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


GET_KERNING = 0x00140098     # GetKerning__4FontiP8tTTGlyph, retail
FONT_KERN_PTR = 1040         # Font+1040, the kerning array


def retail_kerning(path):
    """(checked, bad) from retail's GetKerning against font_dump's."""
    import retail_model as rm
    e = rm.RetailEmu()
    checked, bad = 0, []
    for chunk in fd.find_fonts(Path(path).read_bytes()):
        f = fd.Font(chunk)
        if not f.num_kerning:
            continue
        table = chunk[f.kern_off:f.kern_off + f.num_kerning * fd.KERN_SIZE]
        e.reset_heap()
        font = e.alloc(2048)
        kern = e.alloc(len(table))
        glyph = e.alloc(fd.GLYPH_SIZE)
        e.write(kern, table)
        e.put32(font + FONT_KERN_PTR, kern)
        for i in range(f.num_glyphs):
            g = f.glyphs[i]
            e.write(glyph, chunk[f.glyph_off + i * fd.GLYPH_SIZE:
                                 f.glyph_off + (i + 1) * fd.GLYPH_SIZE])
            prevs = {0, 32, 65, 0x80, 0xff}
            for k in range(g["pairs"]):
                prevs.add(table[(g["first"] + k) * fd.KERN_SIZE])
            for prev in sorted(prevs):
                e.call(GET_KERNING, font, prev, glyph, limit=200000)
                got = fd.struct.unpack("<f", fd.struct.pack(
                    "<I", e.fpr[0] & 0xffffffff))[0]
                want = f.kerning(prev, g["id"])
                checked += 1
                if got != want:
                    bad.append((f.hash, g["id"], prev, got, want))
    return checked, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--max-report", type=int, default=10)
    ap.add_argument("--no-retail", action="store_true",
                    help="skip running retail's GetKerning")
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
            if args.no_retail:
                continue
            n, rbad = retail_kerning(path)
            print("%-34s retail GetKerning: %d pairs, %d differ"
                  % ("", n, len(rbad)))
            for h, gid, prev, got, want in rbad[:args.max_report]:
                print("  font %08x glyph %d prev %d: retail=%g py=%g"
                      % (h, gid, prev, got, want))
            bad_total += len(rbad)
    return 1 if bad_total else 0


if __name__ == "__main__":
    sys.exit(main())
