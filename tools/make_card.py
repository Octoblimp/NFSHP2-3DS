#!/usr/bin/env python3
"""Copy the extracted disc to the SD card: the files the port reads, in the
layout gamedata.c looks for.

After the README's steps, zdir_extract.py --retail --decompress and
audio_pack.py, extracted-retail/ holds more than the game wants. This
copies it to <dest>/NFSHP2, leaving out:

- TRACKS/TRACKB*.LZC. --decompress also writes each one expanded, as
  TRACKB*.BUN, and bfile.c opens a .LZC before its .BUN. With the .LZC on
  the card a race would load the packed bundle and keep it in the heap
  (8.8 MB on track 11) besides the bundle it expands into.
- The sound banks' .MSH, .MSB and .RAW, which audio_pack.py's .SBK replace.
- What the game never opens: the entries the disc's directory has no name
  for (unknown/), the extractor's manifest.csv, KEY.TXT, NFS6.ICO, PAL.TAG
  (gameflow.c sets the PAL mode itself), MARKERS/, NIS/ and the
  REPLAY/MAY31 replays (the attract mode's are JUL23's).

That is the set the Azahar card was tested with, plus the EA logo in the
other five languages, which are the same MV30 movie as the English one.
A file already there with the same size and time is skipped, so a second
run is quick. Nothing on the card is deleted unless --prune is given, and
then only what isn't in the set: the game would load a leftover data file
(one from an earlier extraction, say) as if it were the disc's. SAVES/ is
never touched.

It stops before copying anything when extracted-retail/ came from the old
extractor that could put files under each other's names (see
zdir_extract.py), or when audio_pack.py didn't finish every bank.

Usage:
    python tools/make_card.py E:\\            (the SD card's root)
    python tools/make_card.py sd-card        (a folder to copy over later)
    python tools/make_card.py E:\\ --prune    (also delete leftovers)
"""
import argparse
import fnmatch
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from zdir_extract import misnamed  # noqa: E402

# Upper-case paths relative to extracted-retail/, '/' between parts.
LEAVE_OUT = [
    "TRACKS/TRACKB*.LZC",
    "*.MSH", "*.MSB", "*.RAW",
    "UNKNOWN/*", "MANIFEST.CSV", "KEY.TXT", "NFS6.ICO", "PAL.TAG",
    "MARKERS/*", "NIS/*", "REPLAY/MAY31/*",
]


def wanted(rel):
    up = rel.upper()
    return not any(fnmatch.fnmatchcase(up, g) for g in LEAVE_OUT)


def same(src, dst):
    if not dst.is_file():
        return False
    a, b = src.stat(), dst.stat()
    # FAT keeps a file's time to 2 seconds.
    return a.st_size == b.st_size and abs(a.st_mtime - b.st_mtime) <= 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dest", help="the SD card's root, or a folder; "
                                 "the files go into its NFSHP2 folder")
    ap.add_argument("--src", default=str(ROOT / "extracted-retail"))
    ap.add_argument("--prune", action="store_true",
                    help="delete the files in NFSHP2 that aren't in the set "
                         "(never SAVES)")
    a = ap.parse_args()

    src = Path(a.src)
    if not (src / "GLOBAL" / "GLOBALB.BUN").is_file():
        sys.exit("%s has no GLOBAL/GLOBALB.BUN: run zdir_extract.py "
                 "--retail --decompress first" % src)
    bad = misnamed(src / "manifest.csv")
    if bad:
        sys.exit("%s came from an older zdir_extract.py that put %d files "
                 "under the wrong names. Delete it, and the NFSHP2 folder on "
                 "the card (keep NFSHP2/SAVES), then do the README's steps "
                 "again." % (src, len(bad)))
    for msh in sorted((src / "SOUND").glob("*.MSH")):
        sbk = msh.with_suffix(".SBK")
        if not sbk.is_file() or sbk.stat().st_mtime < msh.stat().st_mtime:
            sys.exit("%s has no up-to-date %s: run audio_pack.py, and let it "
                     "finish, first" % (msh.parent, sbk.name))
    out = Path(a.dest) / "NFSHP2"

    files = sorted(p for p in src.rglob("*")
                   if p.is_file() and wanted(p.relative_to(src).as_posix()))
    keep = {p.relative_to(src).as_posix().upper() for p in files}
    extra = sorted(p for p in out.rglob("*")
                   if p.is_file() and p.relative_to(out).parts[0].upper() != "SAVES"
                   and p.relative_to(out).as_posix().upper() not in keep) \
        if out.is_dir() else []
    todo = [p for p in files if not same(p, out / p.relative_to(src))]
    need = sum(p.stat().st_size for p in todo)
    out.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(out).free
    if need > free:
        sys.exit("%s needs %.2f GB more and has %.2f GB free"
                 % (out, need / 1e9, free / 1e9))

    for i, p in enumerate(todo, 1):
        dst = out / p.relative_to(src)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
        print("[%d/%d] %s" % (i, len(todo), p.relative_to(src).as_posix()))
    for p in extra:
        if a.prune:
            p.unlink()
            print("deleted %s" % p.relative_to(out).as_posix())
    print("%s: %d files, %.2f GB (%d copied, %d already there)"
          % (out, len(files), sum(p.stat().st_size for p in files) / 1e9,
             len(todo), len(files) - len(todo)))
    if extra and not a.prune:
        print("%d files in %s aren't from %s, and the game may load them:"
              % (len(extra), out, src))
        for p in extra[:10]:
            print("    " + p.relative_to(out).as_posix())
        print("Run this again with --prune to delete them (SAVES is kept).")


if __name__ == "__main__":
    main()
