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
           "3DS Files/source/langtab.c", "3DS Files/source/portlang.c",
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
    port = {}
    for line in r.stdout.splitlines():
        if chr(9) not in line:
            continue
        k, v = line.split(chr(9), 1)
        if k.startswith("port "):
            port[int(k[5:])] = v
            continue
        out.setdefault(int(k), v)             # first hit wins, as the dict does
    return out, port, r.stderr.strip()


# The PS2's memory card, in each language's words; the port's SD Card text
# (portlang.c's kRetail) must leave none of it in the six languages.
CARD_WORDS = ("memory card", "minneskort (ps2)", "(ps2)")


def names_card(s):
    s = s.lower()
    return any(w in s for w in CARD_WORDS)


def check_port(t, py_text, port):
    """The port's own wording for the six languages: every disc string that
    names the PS2's card has one, none of them names it, and the build
    tables (LONGEST, ID_NUM) have none."""
    bad = []
    if t.language > 5:
        if port:
            bad.append("%d port strings in a build table" % len(port))
        return bad
    for k, v in sorted(py_text.items()):
        if names_card(v) and k not in port:
            bad.append("[%d] still names the card: %r" % (k, v))
    for k, h in sorted(port.items()):
        s = bytes.fromhex(h).decode("latin-1")
        if names_card(s):
            bad.append("[%d] the port's names the card: %r" % (k, s))
        if k not in py_text:
            bad.append("[%d] the port's is not on the disc" % k)
    return bad


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
            c, port, info = run_c(exe, path, args.english)
            t = ld.load(path)
            py = t.by_hash if args.english else t.by_id
            if args.english:
                py = {k - (1 << 32) if k >= 1 << 31 else k: v
                      for k, v in py.items()}
            text = py
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
            if not args.english:
                pbad = check_port(t, text, port)
                print("%-40s %d with the port's wording, %d wrong"
                      % ("", len(port), len(pbad)))
                for line in pbad[:args.max_report]:
                    print("  " + line)
                bad_total += len(pbad)
    return 1 if bad_total else 0


if __name__ == "__main__":
    sys.exit(main())
