#!/usr/bin/env python3
r"""Recover the filenames behind ZDIR.BIN's hashes and write docs/zdir_names.txt.

ZDIR.BIN stores only `bStringHash(uppercased path)` per entry, so the names
have to be reconstructed. Five sources, all of them verified by hashing the
candidate back to the directory entry (a name is only ever emitted on an
exact hash match -- nothing here is a guess):

1. `literals`  -- every ASCII string in NFSHP2.ELF, uppercased.
2. `templates` -- printf templates in the ELF expanded over their parameter
                  range (`TRACKS\TRACKB%d.BUN`, `NIS\%s.bin`, ...).
3. `embedded`  -- the authoring-machine build path most chunk files still
                  carry inside them (`..\Psx2\CD\CARS\BARCHETTA\DASHGEOM.BIN`);
                  everything after `\CD\` is the CD-relative path.
4. `ondisc`    -- files still present unpacked in `PS2 Files/` (the IOP
                  modules in `IRX243/`), matched by name.
5. `siblings`  -- once a name is known, its known-extension twins are tried
                  (`X.BIN` -> `X.LZC`, `X.MSB` -> `X.MSH`, `X.BIN` -> `X.CAM`),
                  which is what pairs every compressed file with its raw one.

`KNOWN` below holds the handful that none of the above reach and that were
instead brute-forced with `bhash.crack()` -- the sound banks, whose stems
(`ALPINE`, `DESERT`, `GREECE`, `PARKLAND`, `TROPICS`, `NEWE<car>`) appear
nowhere in the ELF because bSound builds them from data. They are listed
explicitly rather than re-cracked on every run, and each one is still
hash-checked here.

Usage:
    python tools/zdir_names.py                      # writes docs/zdir_names.txt
    python tools/zdir_names.py --elf ... --zdir ...
"""
import argparse
import csv
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bhash import bhash                      # noqa: E402
from lzdecompress import decompress          # noqa: E402

B = chr(92)
RECORD_SIZE = 12
SECTOR = 2048

# Extensions that come in twins; a match on one is retried on all the others.
EXT_GROUPS = [
    (".BIN", ".LZC", ".BUN", ".CAM"),
    (".MSB", ".MSH"),
    (".CTB", ".LTB"),
]

# Names brute-forced out of their hashes with bhash.crack(); see module docstring.
KNOWN = {
    "SOUND" + B + "ALPINE.MSB", "SOUND" + B + "ALPINE.MSH",
    "SOUND" + B + "DESERT.MSB", "SOUND" + B + "DESERT.MSH",
    "SOUND" + B + "GREECE.MSB", "SOUND" + B + "GREECE.MSH",
    "SOUND" + B + "PARKLAND.MSB", "SOUND" + B + "PARKLAND.MSH",
    "SOUND" + B + "TROPICS.MSB", "SOUND" + B + "TROPICS.MSH",
    "SOUND" + B + "COMMON.MSB", "SOUND" + B + "COMMON.MSH",
    "SOUND" + B + "FRONTEND.MSB", "SOUND" + B + "FRONTEND.MSH",
    "SOUND" + B + "INGAME.MSB", "SOUND" + B + "INGAME.MSH",
    "HOTCHUNK.TAG",
    # Authoring leftovers, not referenced by the ELF at all. Found by testing
    # a vocabulary against the hash rather than by brute force: the five .TXT
    # files are the art punch-lists that pair with MARKERS\MARKERS<nn>.BIN
    # (same nn set: 11, 12, 21, 22, 32), and KEY.TXT is the 130-byte
    # "x<128 hex digits>x" line that sits between IRX243\ and LANGUAGES\.
    "MARKERS" + B + "TRACK11.TXT", "MARKERS" + B + "TRACK12.TXT",
    "MARKERS" + B + "TRACK21.TXT", "MARKERS" + B + "TRACK22.TXT",
    "MARKERS" + B + "TRACK32.TXT",
    "KEY.TXT",
}
# Per-car engine sample banks: SOUND\NEWE<code>.MSB / .MSH
for _code in ("348 360 360D 911 993 BMW BMW2 BRU BXR CAM CSS CTR CVC DNF GTI "
              "MR2 NEO PANTERA PRW PRW02 SNU XKR").split():
    KNOWN.add("SOUND" + B + "NEWE" + _code + ".MSB")
    KNOWN.add("SOUND" + B + "NEWE" + _code + ".MSH")


def read_zdir(path):
    data = Path(path).read_bytes()
    entries = []
    for i in range(0, len(data), RECORD_SIZE):
        h, fad, size = struct.unpack_from("<III", data, i)
        entries.append(dict(index=i // RECORD_SIZE, hash=h, fad=fad, size=size))
    return entries


def elf_strings(elf_path):
    raw = Path(elf_path).read_bytes()
    return {m.group().decode("ascii")
            for m in re.finditer(rb"[\x20-\x7e]{2,120}", raw)}


def candidates_from_literals(strs):
    for s in strs:
        yield s.upper()
        if B in s:
            yield s.rsplit(B, 1)[1].upper()


def candidates_from_templates(strs):
    num = re.compile(r"%[0-9]*d")
    # `%s` arguments are not always bare identifiers -- `REPLAY\%s` is passed a
    # whole `MAY31\BLUESPIDERWILLIAM.BIN`, so path separators and dots count.
    tokens = {s.strip().upper() for s in strs
              if re.fullmatch(r"[A-Za-z0-9_." + B + B + r"]{1,40}", s.strip() or "?")}
    for s in strs:
        if "%" not in s:
            continue
        if num.search(s) and "%s" not in s:
            for n in range(0, 200):
                yield num.sub(str(n), s).upper()
        elif s.count("%s") == 1 and ("." in s or B in s):
            for t in tokens:
                v = s.replace("%s", t).upper()
                if len(v) <= 80:
                    yield v


def candidates_from_blobs(zdir_entries, zzdata_path):
    """Pull `..\\Psx2\\CD\\<path>` build strings back out of the payloads."""
    text = re.compile(rb"[\x20-\x7e]{6,140}")
    cdrel = re.compile("(?i)^.*?[" + B + B + "/]CD[" + B + B + "/](.+)$")
    with open(zzdata_path, "rb") as zz:
        for e in zdir_entries:
            if not e["size"]:
                continue
            zz.seek(e["fad"] * SECTOR)
            blob = zz.read(e["size"])
            blobs = [blob]
            if blob[:4] == b"COMP":
                try:
                    blobs.append(decompress(blob))
                except Exception:
                    pass
            for b in blobs:
                for m in text.finditer(b):
                    hit = cdrel.match(m.group().decode("latin-1"))
                    if hit:
                        yield hit.group(1).upper()


def candidates_from_disc(ps2_dir):
    root = Path(ps2_dir)
    for p in root.rglob("*"):
        if p.is_file():
            rel = p.relative_to(root).as_posix().replace("/", B).upper()
            yield rel


def siblings(name):
    for group in EXT_GROUPS:
        for ext in group:
            if name.upper().endswith(ext):
                stem = name[:-len(ext)]
                for other in group:
                    if other != ext:
                        yield stem + other
                return


def resolve(zdir, elf, zzdata, ps2_dir):
    entries = read_zdir(zdir)
    by_hash = {e["hash"]: e for e in entries}
    names = {}

    def offer(cand, source):
        h = bhash(cand)
        e = by_hash.get(h)
        if e is not None and e["index"] not in names:
            names[e["index"]] = (cand, source)
            return True
        return False

    strs = elf_strings(elf)
    for c in candidates_from_literals(strs):
        offer(c, "literal")
    for c in candidates_from_templates(strs):
        offer(c, "template")
    for c in candidates_from_disc(ps2_dir):
        offer(c, "ondisc")
    for c in KNOWN:
        offer(c, "cracked")
    for c in candidates_from_blobs(entries, zzdata):
        offer(c, "embedded")
    # sibling sweep, repeated until it stops finding anything new
    while True:
        before = len(names)
        for name, _ in list(names.values()):
            for s in siblings(name):
                offer(s, "sibling")
        if len(names) == before:
            break
    return entries, names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zdir", default="PS2 Files/ZDIR.BIN")
    ap.add_argument("--zzdata", default="PS2 Files/ZZDATA.BIN")
    ap.add_argument("--elf", default="PS2 Files/NFSHP2.ELF")
    ap.add_argument("--ps2-dir", default="PS2 Files")
    ap.add_argument("--out", default="docs/zdir_names.txt")
    a = ap.parse_args()

    entries, names = resolve(a.zdir, a.elf, a.zzdata, a.ps2_dir)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("# ZDIR.BIN entry -> filename, recovered by tools/zdir_names.py.\n"
                "# Every name here hashes back to its entry exactly; unnamed\n"
                "# entries are printed as '?'. Columns: index hash fad size source name\n")
        for e in entries:
            name, source = names.get(e["index"], ("?", "-"))
            f.write("%3d %08x %7d %10d %-9s %s\n"
                    % (e["index"], e["hash"], e["fad"], e["size"], source, name))
    print("named %d/%d entries -> %s" % (len(names), len(entries), out))


if __name__ == "__main__":
    main()
