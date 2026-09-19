#!/usr/bin/env python3
r"""Walk a bWare chunk file (.BIN / .BUN / .PSH / most of ZZDATA.BIN).

Format (recovered from `LoadChunks(bChunk *, int)` / `TraverseChunks()` in
NFSHP2.ELF, plus direct inspection -- see docs/formats/bchunk.md):

    struct bChunk { unsigned int Type; unsigned int Size; };

`Size` counts the payload only, NOT the 8-byte header, and is always a
multiple of 16 (the engine DMAs chunks straight to VU/GS memory, so every
chunk is quadword-aligned; short payloads are padded with 0x11 filler).

Bit 31 of `Type` marks a *container*: its payload is itself a sequence of
chunks. Everything else is leaf data owned by the matching `Loader*()`
function in the chunk-loader dispatch table.

Usage:
    python tools/bchunk_dump.py <file> [--max-depth N] [--limit N]
    python tools/bchunk_dump.py <file> --stats     # histogram of chunk types
"""
import argparse
import struct
import sys
from collections import Counter
from pathlib import Path

CONTAINER_BIT = 0x80000000

# Chunk type -> name. Everything above the rule is verified: it comes from
# LoaderTable in the ELF, where each Loader*() names itself in .symtab and
# guards on its own type constant -- regenerate with tools/chunk_loader_table.py.
# Below the rule are the SolidList sub-chunks, named from what they contain
# rather than from a loader (they are parsed inline by SolidList's own reader).
KNOWN = {
    0xb0300001: "TexturePack",
    0x80010200: "FlailerChunk",
    0x00030200: "FontInfo",
    0x80034000: "SolidList",
    0x80034008: "Animations",
    0x00034013: "PositionMarkers",
    0x80034015: "LightList",
    0x80034020: "CollisionVolumes",
    0x00034026: "Smokeables",
    0x00034030: "BodyDamage",
    0x80034100: "Scenery",
    0x00034121: "TrackRoutes",
    0x80034147: "TrackPath",
    0x00034200: "TrackGeometry",
    0x00034202: "Sun",
    0x00034250: "WeatherMan",
    0x00034301: "CharacterInfo",
    0x80034405: "Cameras",
    0x80034500: "Cops",
    0x00034600: "CarInfo",
    0x00034700: "PhysPredict",
    0x00034800: "HeliSheet",
    0x80034a00: "EventTree",
    0x00034b00: "DifficultyInfo",
    0x80035000: "AcidFX",
    0x80036000: "EventManager",
    0x00037010: "NisInfo",
    0x80038000: "SoundScape",
    0x00039000: "Language",
    0x00039100: "DemoModeReplay",
    # --- SolidList sub-chunks (inside 0x80034000) ---
    0x80034002: "Solid",
    0x00034003: "SolidHeader",
    0x00034004: "SolidVertexTable",
    0x00034005: "SolidGeometry",     # packed VU1 draw data
    0x00034006: "SolidTable6",
    0x0003401d: "SolidTable1d",
}


def walk(buf, off=0, end=None, depth=0, max_depth=8, out=None, stats=None,
         limit=None, count=None):
    if end is None:
        end = len(buf)
    if count is None:
        count = [0]
    while off + 8 <= end:
        ctype, csize = struct.unpack_from("<II", buf, off)
        if ctype == 0 and csize == 0:
            break
        body = off + 8
        cend = body + csize
        if csize < 0 or cend > end:
            if out is not None:
                out.append("%s@0x%08x BAD chunk type=0x%08x size=0x%x (past end)"
                           % ("  " * depth, off, ctype, csize))
            break
        if stats is not None:
            stats[ctype] += 1
        count[0] += 1
        if out is not None and (limit is None or count[0] <= limit):
            name = KNOWN.get(ctype, "")
            out.append("%s@0x%08x type=0x%08x size=%-9d %s%s"
                       % ("  " * depth, off, ctype, csize,
                          "[container] " if ctype & CONTAINER_BIT else "",
                          name))
        if (ctype & CONTAINER_BIT) and depth < max_depth:
            walk(buf, body, cend, depth + 1, max_depth, out, stats, limit, count)
        off = cend
    return count[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--max-depth", type=int, default=8)
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()

    buf = Path(a.file).read_bytes()
    out = [] if not a.stats else None
    stats = Counter()
    total = walk(buf, out=out, stats=stats, max_depth=a.max_depth, limit=a.limit)
    if out is not None:
        print("\n".join(out))
        if total > a.limit:
            print("... (%d chunks total, showing first %d)" % (total, a.limit))
    else:
        for ctype, n in stats.most_common():
            print("0x%08x  %6d  %s%s" % (ctype, n,
                                          "[container] " if ctype & CONTAINER_BIT else "",
                                          KNOWN.get(ctype, "")))
        print("total chunks:", total)


if __name__ == "__main__":
    main()
