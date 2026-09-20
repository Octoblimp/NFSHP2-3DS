#!/usr/bin/env python3
r"""bWare fonts -- chunk 0x00015010, the glyph metrics behind every UI string.

A font is a header, a glyph table and a kerning table, all inside one chunk;
its artwork is a texture of the same name in a texture pack in the same
bundle, and mPosX/mPosY/mWidth/mHeight are pixel rectangles into that sheet.
Layout and provenance: docs/formats/bchunk.md.

    tTTFontHeader   28 bytes   hash, counts, and two offsets
    tTTGlyph        32 bytes   id, pairs, sheet rect, advance, offset, index
    tTTKerningPair   8 bytes   { u32 mGlyph; f32 mXOffset; }

mKerningTable in a glyph is a pair *index*, not a byte offset: runs are laid
out in glyph order and each glyph's value is the running total of the pairs
before it.

Usage:
    python tools/font_dump.py extracted/GLOBAL/GLOBALB.BUN
    python tools/font_dump.py extracted/GLOBAL/GLOBALB.BUN --glyphs
    python tools/font_dump.py extracted/FRONTEND/FRONTB.BUN --measure "LAP 1"
"""
import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import texture_convert as tc                    # noqa: E402

FONT_CHUNK = 0x00015010
HEADER_SIZE = 28          # from the chunk header, so 20 bytes of payload
GLYPH_SIZE = 32
KERN_SIZE = 8


class Font(object):
    """One 0x00015010 chunk. `chunk` is the 8-byte header plus payload."""

    def __init__(self, chunk):
        self.chunk = chunk
        (self.hash, self.num_glyphs, self.num_kerning,
         glyph_off, kern_off) = struct.unpack_from("<5I", chunk, 8)
        self.glyph_off = glyph_off
        self.kern_off = kern_off
        self.glyphs = [self._glyph(i) for i in range(self.num_glyphs)]
        self.by_id = {}
        for i, g in enumerate(self.glyphs):
            self.by_id.setdefault(g["id"], i)
        self.height = max([g["height"] for g in self.glyphs] or [0.0])

    def _glyph(self, i):
        o = self.glyph_off + i * GLYPH_SIZE
        (gid, pairs) = struct.unpack_from("<2H", self.chunk, o)
        (px, py, w, h, adv, voff) = struct.unpack_from("<6f", self.chunk, o + 4)
        first = struct.unpack_from("<I", self.chunk, o + 28)[0]
        return dict(id=gid, pairs=pairs, x=px, y=py, width=w, height=h,
                    advance=adv, offset=voff, first=first)

    def kerning(self, prev, ch):
        """mXOffset to add before drawing `ch` when it follows `prev`."""
        i = self.by_id.get(prev)
        if i is None:
            return 0.0
        g = self.glyphs[i]
        if not g["pairs"] or g["first"] + g["pairs"] > self.num_kerning:
            return 0.0
        base = self.kern_off + g["first"] * KERN_SIZE
        for k in range(g["pairs"]):
            who, amount = struct.unpack_from("<If", self.chunk,
                                             base + k * KERN_SIZE)
            if who == ch:
                return amount
        return 0.0

    def measure(self, text):
        """Font::GetScaledWidth()'s sum, before the object's ScaleX."""
        total = 0.0
        prev = None
        for ch in text:
            c = ord(ch)
            if c not in self.by_id:
                prev = None
                continue
            if prev is not None:
                total += self.kerning(prev, c)
            total += self.glyphs[self.by_id[c]]["advance"]
            prev = c
        return total

    def accounts_for_chunk(self):
        """Header + both tables should be the whole chunk."""
        size = struct.unpack_from("<I", self.chunk, 4)[0] + 8
        want = (HEADER_SIZE + self.num_glyphs * GLYPH_SIZE
                + self.num_kerning * KERN_SIZE)
        return want <= size <= want + 3

    def runs_are_consecutive(self):
        """Every glyph's mKerningTable is the running pair total before it."""
        running = 0
        for g in self.glyphs:
            if g["pairs"] and g["first"] != running:
                return False
            running += g["pairs"]
        return True


def find_fonts(buf):
    """Every 0x00015010 chunk in `buf`, wherever it is nested."""
    out = []

    def walk(off, end):
        while off + 8 <= end:
            ctype, size = struct.unpack_from("<2I", buf, off)
            if ctype == 0 and size == 0:
                off += 8
                continue
            if off + 8 + size > end:
                return
            if ctype == FONT_CHUNK:
                out.append(buf[off:off + 8 + size])
            elif ctype & 0x80000000:
                walk(off + 8, off + 8 + size)
            off += 8 + size

    walk(0, len(buf))
    return out


def texture_names(buf):
    """hash -> name for every texture in `buf`, which is where fonts get theirs."""
    names = {}
    for off, size in tc.find_packs(buf):
        _, info, _ = tc.parse_pack(buf, off, size)
        for t in tc.textures(info):
            names.setdefault(t["hash"], t["name"])
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="a .BUN or .BIN holding fonts")
    ap.add_argument("--glyphs", action="store_true", help="dump every glyph")
    ap.add_argument("--kerning", action="store_true", help="dump every pair")
    ap.add_argument("--measure", help="print this string's width in each font")
    args = ap.parse_args()

    for path in args.files:
        buf = Path(path).read_bytes()
        fonts = find_fonts(buf)
        names = texture_names(buf)
        print("%s: %d font chunk(s)" % (path, len(fonts)))
        for chunk in fonts:
            f = Font(chunk)
            name = names.get(f.hash, "?")
            print("  %-22s %08x  glyphs=%-4d pairs=%-4d height=%-6.1f "
                  "size=%d %s%s"
                  % (name, f.hash, f.num_glyphs, f.num_kerning, f.height,
                     len(chunk),
                     "" if f.accounts_for_chunk() else "SIZE-MISMATCH ",
                     "" if f.runs_are_consecutive() else "RUNS-NOT-CONSECUTIVE"))
            claimed = sum(g["pairs"] for g in f.glyphs)
            if claimed != f.num_kerning:
                print("      %d of %d pairs are referenced by a glyph"
                      % (claimed, f.num_kerning))
            if args.measure:
                print("      width(%r) = %.2f px"
                      % (args.measure, f.measure(args.measure)))
            if args.glyphs:
                for i, g in enumerate(f.glyphs):
                    ch = chr(g["id"]) if 32 <= g["id"] < 127 else "."
                    print("      [%3d] %3d '%s' pairs=%-3d first=%-4d "
                          "rect=(%g,%g,%g,%g) adv=%g off=%g"
                          % (i, g["id"], ch, g["pairs"], g["first"],
                             g["x"], g["y"], g["width"], g["height"],
                             g["advance"], g["offset"]))
            if args.kerning:
                for i, g in enumerate(f.glyphs):
                    for k in range(g["pairs"]):
                        who, amount = struct.unpack_from(
                            "<If", chunk,
                            f.kern_off + (g["first"] + k) * KERN_SIZE)
                        print("      '%s' + '%s' %+g"
                              % (chr(g["id"]), chr(who) if who < 127 else who,
                                 amount))


if __name__ == "__main__":
    main()
