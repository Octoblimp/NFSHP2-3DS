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


def run_c(exe, path, pack, level):
    r = subprocess.run([str(exe), str(path), str(pack), "--level", str(level)],
                       capture_output=True, text=True)
    if r.returncode:
        sys.stderr.write(r.stderr)
        sys.exit("texpack_test failed")
    print(r.stderr.strip())
    out = {}
    for line in r.stdout.splitlines():
        f = line.split()
        if len(f) < 8:
            continue
        out[int(f[0])] = (f[2], f[-1])         # index -> (name, crc or 'skip')
    return out


def run_py(path, pack, level):
    buf = Path(path).read_bytes()
    packs = list(tc.find_packs(buf))
    if pack >= len(packs):
        sys.exit("no pack %d in %s (%d found)" % (pack, path, len(packs)))
    off, size = packs[pack]
    name, info, data = tc.parse_pack(buf, off, size)
    print("python pack '%s': %d textures" % (name, len(info) // tc.RECORD_SIZE))
    out = {}
    for i, t in enumerate(tc.textures(info)):
        got = tc.decode(t, data, level=level)
        if got is None:
            out[i] = (t["name"], "skip")
        else:
            out[i] = (t["name"], "%08x" % (zlib.crc32(got[2]) & 0xFFFFFFFF))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--pack", type=int, default=0)
    ap.add_argument("--level", type=int, default=0)
    ap.add_argument("--max-report", type=int, default=20)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, 'texpack_test')
        c = run_c(exe, args.file, args.pack, args.level)

    p = run_py(args.file, args.pack, args.level)

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

    print("\nlevel %d: %d textures match, %d skipped by both, %d differ"
          % (args.level, same, skipped, len(bad)))
    for k, cv, pv in bad[:args.max_report]:
        print("  [%d] %-24s C=%s  py=%s"
              % (k, (cv or pv)[0], cv[1] if cv else "-", pv[1] if pv else "-"))
    if len(bad) > args.max_report:
        print("  ... and %d more" % (len(bad) - args.max_report))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
