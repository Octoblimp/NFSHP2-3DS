#!/usr/bin/env python3
r"""Extract every asset out of ZZDATA.BIN using the ZDIR.BIN directory.

Format reference: docs/formats/zdir-archive.md. In short, ZDIR.BIN is a flat
array of the 12-byte `DirectoryEntry` struct (`Hash`, `Fad`, `Size`) taken
from docs/mdebug_structs.txt; `Fad` is a CD sector index, so an entry's byte
range in ZZDATA.BIN is `[Fad * 2048, Fad * 2048 + Size)`.

Filenames are not stored -- only `bStringHash()` of the uppercased path --
so they are recovered separately by tools/zdir_names.py into
docs/zdir_names.txt, which this script reads to lay the output out as the
original directory tree. Entries whose name is still unrecovered fall back to
`unknown/<index>_<hash>.bin`.

Usage:
    python tools/zdir_extract.py "PS2 Files/ZDIR.BIN" "PS2 Files/ZZDATA.BIN" out/
    python tools/zdir_extract.py ... out/ --decompress   # also expand .LZC
    python tools/zdir_extract.py --retail --only "TRACKS\*B12*" --decompress

--retail reads the retail disc in `PS2 Files/Full Game/` with
docs/zdir_names_retail.txt, into extracted-retail/. The retail disc is
3 GB and the tree sits under OneDrive, so --only (a glob on the recovered
name, any number of them) takes what a check needs rather than all of it.
The manifest always lists every entry; out_file is empty for one not taken.
"""
import argparse
import fnmatch
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lzdecompress import decompress  # noqa: E402

SECTOR = 2048
RECORD_SIZE = 12
DEFAULT_NAMES = Path(__file__).resolve().parent.parent / "docs" / "zdir_names.txt"


def read_entries(zdir_path):
    data = Path(zdir_path).read_bytes()
    if len(data) % RECORD_SIZE != 0:
        raise SystemExit("ZDIR.BIN size %d is not a multiple of %d"
                         % (len(data), RECORD_SIZE))
    entries = []
    for i in range(0, len(data), RECORD_SIZE):
        h, fad, size = struct.unpack_from("<III", data, i)
        entries.append(dict(index=i // RECORD_SIZE, hash=h, fad=fad, size=size,
                            offset=fad * SECTOR))
    return entries


def read_names(path):
    """index -> recovered path, from docs/zdir_names.txt ('?' means unknown)."""
    names = {}
    p = Path(path)
    if not p.exists():
        return names
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 5)
        if len(parts) == 6 and parts[5] != "?":
            names[int(parts[0])] = parts[5]
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("zdir", nargs="?")
    ap.add_argument("zzdata", nargs="?")
    ap.add_argument("out_dir", nargs="?")
    ap.add_argument("--names", default=str(DEFAULT_NAMES))
    ap.add_argument("--decompress", action="store_true",
                    help="also write the expanded payload of every COMP/.LZC entry")
    ap.add_argument("--only", action="append", default=[],
                    help="extract only names matching this glob")
    ap.add_argument("--retail", action="store_true",
                    help="the retail disc, into extracted-retail/")
    a = ap.parse_args()
    if a.retail:
        root = Path(__file__).resolve().parent.parent
        game = root / "PS2 Files" / "Full Game"
        a.zdir = a.zdir or str(game / "ZDIR.BIN")
        a.zzdata = a.zzdata or str(game / "ZZDATA.BIN")
        a.out_dir = a.out_dir or str(root / "extracted-retail")
        if a.names == str(DEFAULT_NAMES):
            a.names = str(root / "docs" / "zdir_names_retail.txt")
    if not (a.zdir and a.zzdata and a.out_dir):
        ap.error("zdir, zzdata and out_dir are needed without --retail")
    only = [g.upper().replace("/", chr(92)) for g in a.only]

    entries = read_entries(a.zdir)
    names = read_names(a.names)
    out_dir = Path(a.out_dir)
    zzdata_size = Path(a.zzdata).stat().st_size
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.csv"

    written = skipped = expanded = 0
    with open(a.zzdata, "rb") as zz, \
            open(manifest_path, "w", encoding="utf-8", newline="\n") as manifest:
        manifest.write("index,hash_hex,fad,size,offset,name,out_file\n")
        for e in entries:
            end = e["offset"] + e["size"]
            if end > zzdata_size:
                print("WARNING: entry %d exceeds ZZDATA.BIN bounds "
                      "(offset=%d size=%d, file=%d)"
                      % (e["index"], e["offset"], e["size"], zzdata_size),
                      file=sys.stderr)
                skipped += 1
                continue
            name = names.get(e["index"])
            if only and not any(fnmatch.fnmatchcase((name or "?").upper(), g)
                                for g in only):
                manifest.write("%d,%08x,%d,%d,%d,%s,\n"
                               % (e["index"], e["hash"], e["fad"], e["size"],
                                  e["offset"], name or ""))
                continue
            zz.seek(e["offset"])
            blob = zz.read(e["size"])

            if name:
                rel = Path(name.replace(chr(92), "/"))
            else:
                rel = Path("unknown") / ("%03d_%08x.bin" % (e["index"], e["hash"]))
            dest = out_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(blob)
            written += 1

            if a.decompress and blob[:4] == b"COMP":
                try:
                    dest.with_suffix(dest.suffix + ".raw").write_bytes(decompress(blob))
                    expanded += 1
                except ValueError as exc:
                    print("WARNING: entry %d: %s" % (e["index"], exc), file=sys.stderr)

            manifest.write("%d,%08x,%d,%d,%d,%s,%s\n"
                           % (e["index"], e["hash"], e["fad"], e["size"],
                              e["offset"], name or "", rel.as_posix()))

    print("Extracted %d entries (%d named, %d skipped, %d decompressed) to %s"
          % (written, sum(1 for e in entries if e["index"] in names),
             skipped, expanded, out_dir))
    print("manifest:", manifest_path)


if __name__ == "__main__":
    main()
