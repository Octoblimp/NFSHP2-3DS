#!/usr/bin/env python3
r"""Decode a `LANGUAGES\FE_*.BIN` string table (`0x00039000`).

Every piece of UI text the game shows is in here. Flailer text objects
(`tools/flailer_dump.py`) carry a `LanguageID`, and the string baked into
the chunk next to it is only the authoring placeholder -- often stale.
`RenderFlailerText` calls `GetTranslatedString(LanguageID)` and draws *that*
instead whenever the ID is non-zero, so this table is the real UI copy.

The file is a single `bChunk` wrapping `LanguageDescription` (100 bytes,
straight out of `docs/mdebug_structs.txt`) followed by its three arrays:

    off     what
    0       bChunk {0x00039000, size}
    8       LanguageDescription
      +0      bNode Next/Prev            meaningless on disc
      +8      char FileName[64]          authoring path, e.g.
                                         `..\PSX2\CD\Languages\FE_ENGLISH.bin`
      +72     e_Languages LanguageEnum   l_EN=0 l_FR=1 l_DE=2 l_IT=3
                                         l_ES=4 l_SE=5 l_LONGEST_STRING=6
                                         l_ID_NUM=7
      +76     int NumHashEntries
      +80     int NumIDEntries
      +84     int TextTableSize
      +88     LanguageLookup *pHashEngTable  } absolute PS2 pointers, dead
      +92     LanguageLookup *pHashIDTable   } on disc -- the arrays simply
      +96     char *pTextTable               } follow the header in order
    108     LanguageLookup HashEngTable[NumHashEntries]
    ...     LanguageLookup HashIDTable[NumIDEntries]
    ...     char TextTable[TextTableSize]

`LanguageLookup` is `{int Hash; unsigned Offset;}`; `Offset` is a byte
offset into `TextTable`. Both tables point into the same string pool and
both are sorted ascending as **signed** ints, because
`LanguageManager::GetString` (`0x0020acd0`) binary-searches them with `slt`:

  * `HashIDTable` is keyed by the numeric `LanguageID` (10000..980002 here).
    This is the table `GetTranslatedString(id)` uses.
  * `HashEngTable` is keyed by `bStringHash()` of the *English* string, so
    code can translate a literal it already has without knowing its ID.

Gotcha: the last string in `TextTable` is **not** NUL-terminated -- the table
ends on its final byte -- so reads have to clamp at `TextTableSize`. The chunk
size itself is rounded up to a multiple of 4, so the file can carry up to 3
bytes of padding past `TextTableSize`.

Usage:
    python tools/language_dump.py FE_ENGLISH.BIN
    python tools/language_dump.py FE_ENGLISH.BIN --id 10023
    python tools/language_dump.py FE_ENGLISH.BIN --grep pursuit
    python tools/language_dump.py FE_*.BIN --csv strings.csv
"""
import argparse
import csv
import os
import struct
import sys
from pathlib import Path

LANGUAGE_CHUNK = 0x00039000
HEADER = 108  # 8-byte bChunk + 100-byte LanguageDescription

LANGUAGES = {-1: "NONE", 0: "EN", 1: "FR", 2: "DE", 3: "IT", 4: "ES",
             5: "SE", 6: "LONGEST_STRING", 7: "ID_NUM"}


class LanguageTable(object):
    """A parsed `FE_*.BIN`. `by_id[10023] == 'Hot Pursuit'`."""

    def __init__(self, data, path=None):
        self.path = path
        chunk_type, chunk_size = struct.unpack_from("<2I", data, 0)
        if chunk_type != LANGUAGE_CHUNK:
            raise ValueError("not a 0x%08x chunk (got 0x%08x)"
                             % (LANGUAGE_CHUNK, chunk_type))
        self.filename = data[16:80].split(b"\0")[0].decode("latin-1")
        (self.language, num_hash, num_id, text_size) = \
            struct.unpack_from("<i3I", data, 80)

        hash_off = HEADER
        id_off = hash_off + num_hash * 8
        self.text_off = id_off + num_id * 8
        self.text_size = text_size
        self.data = data

        # bChunk sizes are 4-aligned, so TextTableSize can fall up to 3
        # bytes short of the chunk's end; those bytes are padding.
        end = self.text_off + text_size
        if not end <= 8 + chunk_size <= end + 3:
            raise ValueError("size mismatch: tables end at %d, chunk says %d, "
                             "file is %d" % (end, 8 + chunk_size, len(data)))

        self.by_hash = {}
        for i in range(num_hash):
            h, o = struct.unpack_from("<iI", data, hash_off + i * 8)
            self.by_hash.setdefault(h & 0xFFFFFFFF, self.string_at(o))
        self.by_id = {}
        for i in range(num_id):
            k, o = struct.unpack_from("<iI", data, id_off + i * 8)
            self.by_id.setdefault(k, self.string_at(o))

    def string_at(self, offset):
        """Offset is relative to TextTable. The final string is unterminated."""
        start = self.text_off + offset
        limit = self.text_off + self.text_size
        end = self.data.find(b"\0", start, limit)
        if end < 0:
            end = limit
        return self.data[start:end].decode("latin-1")

    @property
    def language_name(self):
        return LANGUAGES.get(self.language, str(self.language))


def load(path):
    return LanguageTable(Path(path).read_bytes(), path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help=r"LANGUAGES\FE_*.BIN")
    ap.add_argument("--id", type=int, action="append",
                    help="print just this LanguageID (repeatable)")
    ap.add_argument("--grep", help="print only strings containing this")
    ap.add_argument("--csv", help="write id,<lang>,... across every file given")
    a = ap.parse_args()

    tables = []
    for path in a.files:
        try:
            tables.append(load(path))
        except (OSError, ValueError) as exc:
            print("%s: %s" % (path, exc), file=sys.stderr)
    if not tables:
        return 1

    if a.csv:
        ids = sorted(set().union(*[set(t.by_id) for t in tables]))
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["id"] + [t.language_name for t in tables])
            for i in ids:
                w.writerow([i] + [t.by_id.get(i, "") for t in tables])
        print("wrote %s -- %d ids x %d languages" % (a.csv, len(ids), len(tables)))
        return 0

    for t in tables:
        print("== %s -- %s, %d ids, %d hashes, %d bytes of text =="
              % (os.path.basename(t.path or "?"), t.language_name,
                 len(t.by_id), len(t.by_hash), t.text_size))
        if a.id:
            for i in a.id:
                print("%8d  %s" % (i, t.by_id.get(i, "<missing>")))
            continue
        for i in sorted(t.by_id):
            s = t.by_id[i]
            if a.grep and a.grep.lower() not in s.lower():
                continue
            print("%8d  %s" % (i, s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
