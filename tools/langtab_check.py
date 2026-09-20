#!/usr/bin/env python3
r"""Check the 3DS C language-table reader against tools/language_dump.py.

`3DS Files/source/langtab.c` reimplements LanguageManager::GetString -- a
signed binary search over a table whose last string has no terminator. Both
of those are easy to get subtly wrong, so this runs the C reader and the
Python one over the same file and diffs every string.

Usage:
    python tools/langtab_check.py extracted/LANGUAGES/FE_ENGLISH.BIN
    python tools/langtab_check.py extracted/LANGUAGES/*.BIN
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hostbuild                                # noqa: E402
import language_dump as ld                      # noqa: E402

SOURCES = ["tools/src/langtab_test.c",
           "3DS Files/source/langtab.c",
           "3DS Files/source/bchunk.c"]


def as_hex(s):
    return s.encode("latin-1", "replace").hex()


def run_c(exe, path, english):
    cmd = [str(exe), str(path)] + (["--english"] if english else [])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.stderr.write(r.stderr)
        sys.exit("langtab_test failed on %s" % path)
    out = {}
    for line in r.stdout.splitlines():
        if chr(9) not in line:
            continue
        k, v = line.split(chr(9), 1)
        out.setdefault(int(k), v)             # first hit wins, as the dict does
    return out, r.stderr.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--english", action="store_true",
                    help="check the English-hash table instead of the IDs")
    ap.add_argument("--max-report", type=int, default=10)
    args = ap.parse_args()

    bad_total = 0
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, "langtab_test")
        for path in args.files:
            c, info = run_c(exe, path, args.english)
            t = ld.load(path)
            py = t.by_hash if args.english else t.by_id
            if args.english:
                py = {k - (1 << 32) if k >= 1 << 31 else k: v
                      for k, v in py.items()}
            py = {k: as_hex(v) for k, v in py.items()}

            bad = [k for k in sorted(set(c) | set(py))
                   if c.get(k) != py.get(k)]
            print("%-40s %s -> %d entries, %d differ"
                  % (Path(path).name, info, len(py), len(bad)))
            for k in bad[:args.max_report]:
                print("  [%d] C=%r py=%r" % (k, c.get(k), py.get(k)))
            if len(bad) > args.max_report:
                print("  ... and %d more" % (len(bad) - args.max_report))
            bad_total += len(bad)
    return 1 if bad_total else 0


if __name__ == "__main__":
    sys.exit(main())
