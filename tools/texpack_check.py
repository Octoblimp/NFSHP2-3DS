#!/usr/bin/env python3
r"""Check the 3DS C texture decoder against tools/texture_convert.py.

`3DS Files/source/texpack.c` is a port of texture_convert.py's decode path --
the mip chain, the CLUT, the PS2 alpha scale and both halves of the GS
swizzle. A port like that is easy to get 95% right and impossible to verify by
looking at two small renders, so this runs both over the same pack and
compares a CRC32 of every decoded image.

It builds tools/src/texpack_test.c for the host (cc/gcc/clang), runs it, runs
the Python decoder on the same file, and reports any texture where the two
disagree -- or where one produced an image and the other did not.

Usage:
    python tools/texpack_check.py extracted/CARS/TEXTURES.BIN
    python tools/texpack_check.py extracted/FRONTEND/FRONTB.BUN --pack 0
    python tools/texpack_check.py extracted/GLOBAL/HUDTEX.BIN --level 1
    python tools/texpack_check.py extracted-retail/TRACKS/TEX12LOCATION.BIN --chain

--chain compares the PICA200 mip chain texpack_upload_chain() builds from
--level instead: the disc's levels padded to powers of two, then 2x2 means
down to 8 texels, with a cut-out texture's alpha kept to its two values.

--chain --packed compares the chain as texpack_upload_chain() stores it: in
the smallest of RGBA8, RGB8, LA8 and L8 that holds the texels of the disc's
levels it takes (texpack_format), read back as the PICA200 reads that format.
Here the format comes from the decoded images: opaque is alpha 254 or 255,
gray is red, green and blue equal, and a format without alpha reads 255.
"""
import argparse
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hostbuild                                # noqa: E402
import texture_convert as tc                    # noqa: E402

SOURCES = ["tools/src/texpack_test.c",
           "3DS Files/source/texpack.c",
           "3DS Files/source/bchunk.c"]


def run_c(exe, path, pack, level, chain=False, packed=False):
    r = subprocess.run([str(exe), str(path), str(pack), "--level", str(level)]
                       + (["--chain"] if chain else [])
                       + (["--packed"] if packed else []),
                       capture_output=True, text=True)
    if r.returncode:
        sys.stderr.write(r.stderr)
        sys.exit("texpack_test failed")
    print(r.stderr.strip())
    out, scroll = {}, {}
    for line in r.stdout.splitlines():
        f = line.split()
        if f and f[0] == "scroll":
            scroll[int(f[1])] = tuple(f[2:])
        elif len(f) >= 9:
            # index -> (name, ScrollType, crc or 'skip')
            out[int(f[0])] = (f[2], f[-2], f[-1])
    return out, scroll


def pot8(n):
    p = 8
    while p < n:
        p <<= 1
    return p


def pad(img, w, h, cw, ch):
    """Spread a w x h RGBA image over cw x ch, repeating the last column/row."""
    out = bytearray(cw * ch * 4)
    for y in range(ch):
        sy = min(y, h - 1)
        for x in range(cw):
            s = (sy * w + min(x, w - 1)) * 4
            out[(y * cw + x) * 4:(y * cw + x) * 4 + 4] = img[s:s + 4]
    return out


def cutout_alpha(img):
    alphas = set(img[3::4]) - {0}
    return alphas.pop() if len(alphas) == 1 else 0


def half(img, cw, ch, cutout):
    """The 2x2 mean of a 2cw x 2ch image, alpha kept to {0, cutout}."""
    out = bytearray(cw * ch * 4)
    pw = 2 * cw
    for y in range(ch):
        for x in range(cw):
            for c in range(4):
                s = sum(img[((2 * y + dy) * pw + 2 * x + dx) * 4 + c]
                        for dy in (0, 1) for dx in (0, 1))
                v = (s + 2) >> 2
                if c == 3 and cutout:
                    v = cutout if s >= 2 * cutout else 0
                out[(y * cw + x) * 4 + c] = v
    return out


def chain_format(t, data, base, n, levels):
    """texpack_format(): the smallest exact format for the disc's levels
    base .. base + n - 1, from their decoded images."""
    opaque = gray = True
    for lv in range(base, min(base + n, levels)):
        d = tc.decode(t, data, level=lv)
        if not d:
            break
        img = d[2]
        if opaque and min(img[3::4]) < 254:
            opaque = False
        if gray and (img[0::4] != img[1::4] or img[1::4] != img[2::4]):
            gray = False
    if gray:
        return "L8" if opaque else "LA8"
    return "RGB8" if opaque else "RGBA8"


def chain(t, data, base, packed=False):
    """texpack_upload_chain()'s levels, concatenated, or None; with
    `packed`, (format, levels as the PICA200 reads them back)."""
    levels = min(7, max(1, t["levels"]))
    if base >= levels:
        return None
    pw = pot8(max(1, t["width"] >> base))
    ph = pot8(max(1, t["height"] >> base))
    n, side = 1, min(pw, ph)
    while side > 8 and n < 8:
        n, side = n + 1, side >> 1
    fmt = chain_format(t, data, base, n, levels) if packed else "RGBA8"
    out, prev, cut = bytearray(), None, 0
    for i in range(n):
        cw, ch = pw >> i, ph >> i
        img = None
        if base + i < levels:
            d = tc.decode(t, data, level=base + i)
            if d and d[0] <= cw and d[1] <= ch:
                img = pad(d[2], d[0], d[1], cw, ch)
        if img is None:
            if i == 0:
                return None
            img = half(prev, cw, ch, cut)
        if i == 0:
            cut = cutout_alpha(img)
        if fmt in ("RGB8", "L8"):
            # No alpha stored: the PICA200 reads 255, and the level below
            # is made from that.
            img = bytearray(img)
            img[3::4] = b"\xff" * (len(img) // 4)
        out += img
        prev = img
    return (fmt, out) if packed else out


def run_py(path, pack, level, use_chain=False, packed=False):
    buf = Path(path).read_bytes()
    packs = list(tc.find_packs(buf))
    if pack >= len(packs):
        sys.exit("no pack %d in %s (%d found)" % (pack, path, len(packs)))
    off, size = packs[pack]
    name, info, data = tc.parse_pack(buf, off, size)
    print("python pack '%s': %d textures" % (name, len(info) // tc.RECORD_SIZE))
    out, scroll = {}, {}
    for i, t in enumerate(tc.textures(info)):
        fmt = None
        if use_chain:
            img = chain(t, data, level, packed)
            if packed and img is not None:
                fmt, img = img
        else:
            got = tc.decode(t, data, level=level)
            img = got and got[2]
        crc = ("skip" if img is None
               else "%08x" % (zlib.crc32(img) & 0xFFFFFFFF))
        if fmt and img is not None:
            crc = "%s:%s" % (fmt, crc)
        out[i] = (t["name"], "%d" % t["scroll_type"], crc)
        if t["scroll_type"]:
            scroll[i] = scroll_fields(t)
    return out, scroll


# The sample times, and the line, that tools/src/scrollline.h prints. Keep the
# two lists identical -- the point of the samples is to catch a GetScroll
# (0x00100a60) that rounds where the original truncates, which a port that
# reads all four fields correctly still gets wrong.
SCROLL_TIMES = [0.0, 0.1, 1.0, 7.3, 100.0]


def scroll_fields(t):
    f = [t["name"], "%d" % t["scroll_type"]]
    f += ["%.6f" % x for x in (t["scroll_s"], t["scroll_t"], t["scroll_step"])]
    for time in SCROLL_TIMES:
        f += ["%.6f" % x for x in tc.scroll_uv(t, time)]
    return tuple(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--pack", type=int, default=0)
    ap.add_argument("--level", type=int, default=0)
    ap.add_argument("--chain", action="store_true")
    ap.add_argument("--packed", action="store_true")
    ap.add_argument("--max-report", type=int, default=20)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, 'texpack_test')
        c, cscroll = run_c(exe, args.file, args.pack, args.level, args.chain,
                           args.packed)

    p, pscroll = run_py(args.file, args.pack, args.level, args.chain,
                        args.packed)

    keys = sorted(set(c) | set(p))
    same = skipped = 0
    bad = []
    for k in keys:
        cv, pv = c.get(k), p.get(k)
        if cv is None or pv is None:
            bad.append((k, cv, pv))
        elif cv[1] != pv[1]:
            bad.append((k, cv, pv))
        elif cv[1] == "skip":
            skipped += 1
        else:
            same += 1

    print("\n%s %d: %d textures match, %d skipped by both, %d differ"
          % ("chain from level" if args.chain else "level", args.level,
             same, skipped, len(bad)))
    for k, cv, pv in bad[:args.max_report]:
        print("  [%d] %-24s C=%s  py=%s"
              % (k, (cv or pv)[0], cv[1:] if cv else "-",
                 pv[1:] if pv else "-"))
    if len(bad) > args.max_report:
        print("  ... and %d more" % (len(bad) - args.max_report))

    # The scroll transcript. A texture whose ScrollType one side reads as 0
    # is absent from that side's table, so a missing key is a difference too.
    sbad = [k for k in sorted(set(cscroll) | set(pscroll))
            if cscroll.get(k) != pscroll.get(k)]
    print("%d scrolling textures, %d differ"
          % (len(set(cscroll) | set(pscroll)), len(sbad)))
    for k in sbad[:args.max_report]:
        print("  [%d] C =%s" % (k, " ".join(cscroll.get(k, ("-",)))))
        print("      py=%s" % " ".join(pscroll.get(k, ("-",))))
    return 1 if bad or sbad else 0


if __name__ == "__main__":
    sys.exit(main())
