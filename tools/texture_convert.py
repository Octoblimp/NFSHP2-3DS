#!/usr/bin/env python3
r"""Decode bWare GS texture packs (chunk 0xb0300001) out of any HP2 asset file.

A texture pack is a container chunk holding three leaves:

    0x30300002  20 bytes   pack header -- a 16-byte name, then a version word
    0x30300003  n * 164    one TextureInfo record per texture
    0x30300004  blob       every texture's CLUT and pixel data, back to back

The 164-byte record is `TextureInfo` from docs/mdebug_structs.txt. The field
offsets used here were confirmed against `GetTex0__FP11TextureInfoUiUi`
(0x001094b8), which builds the GS TEX0 register straight out of the struct --
`+0x48` is TW, `+0x49` TH, `+0x4a` PSM, `+0x4b` CPSM, `+0x54` TBW -- and
against `AttachTextureDownloadPacket` (0x00108938), which DMAs the pixels to
GS memory with DPSM taken from `+0x4a` and TRXREG from `+0x24`/`+0x26`.

    +0x08  char[24]  name (NUL padded)
    +0x20  u32       bStringHash() of the name -- how the game looks textures up
    +0x24  u16       width
    +0x26  u16       height
    +0x28  u8        bits per pixel: 4, 8 or 32
    +0x29  u8        flags
    +0x2a  u16       palette entry count (16 or 256; 0 when 32bpp)
    +0x2c  u16       palette size in 256-byte GS blocks
    +0x2e  u16       pixel size in 256-byte GS blocks
    +0x30  u32       pixel data offset into the 0x30300004 blob
    +0x34  u32       palette offset into the same blob
    +0x38  u32       pixel data size            (includes the mip chain)
    +0x3c  u32       palette size
    +0x40  u32       name hash of the texture this one borrows its pixels from,
                     0 if it owns them -- palette-swapped variants (the four
                     driver bodies, the cop skins) share a single image
    +0x48  u8[4]     TW, TH, PSM, CPSM
    +0x54  u8        TBW

Palettes are RGBA8 with PS2 alpha (0x80 = opaque), stored linearly: the game
uploads them to the GS verbatim and only ever calls `RemapLinearIntoClut8()`
on palettes it builds at runtime (fog, focus, movie YUV), never on these.

Pixel data is pre-swizzled into the PS2's texture layout. The 8-bit layout is
confirmed -- the HUD speedometer dials come out with their "200 300 km/h"
legends readable. The 4-bit one is NOT confirmed; see docs/formats/texture-pack.md.
`--swizzle none` dumps either verbatim.

Mipmapped textures store the chain after the base level (data size is then
4/3 of width*height*bpp/8); only the base level is emitted.

Usage:
    python tools/texture_convert.py <file> --list
    python tools/texture_convert.py <file> <outdir>
    python tools/texture_convert.py <file> <outdir> --swizzle none
"""
import argparse
import struct
import sys
import zlib
from pathlib import Path

TEXTURE_PACK = 0xB0300001
PACK_HEADER = 0x30300002
PACK_INFO = 0x30300003
PACK_DATA = 0x30300004
RECORD_SIZE = 164

PSM_NAMES = {0x00: "PSMCT32", 0x13: "PSMT8", 0x14: "PSMT4"}


def find_packs(buf, off=0, end=None, depth=0):
    """Yield (offset, size) of every 0xb0300001 chunk, including nested ones."""
    if end is None:
        end = len(buf)
    while off + 8 <= end:
        ctype, csize = struct.unpack_from("<II", buf, off)
        if ctype == 0 and csize == 0:
            break
        cend = off + 8 + csize
        if cend > end:
            break
        if ctype == TEXTURE_PACK:
            yield off, csize
        elif ctype & 0x80000000 and depth < 8:
            # A .BUN bundle nests its packs inside other containers.
            for hit in find_packs(buf, off + 8, cend, depth + 1):
                yield hit
        off = cend


def parse_pack(buf, off, size):
    name, info, data = "", b"", b""
    p, end = off + 8, off + 8 + size
    while p + 8 <= end:
        ctype, csize = struct.unpack_from("<II", buf, p)
        payload = buf[p + 8:p + 8 + csize]
        if ctype == PACK_HEADER:
            name = payload.split(b"\0")[0].decode("latin-1")
        elif ctype == PACK_INFO:
            info = payload
        elif ctype == PACK_DATA:
            data = payload
        p += 8 + csize
    return name, info, data


def textures(info):
    for r in range(0, len(info) - RECORD_SIZE + 1, RECORD_SIZE):
        t = {}
        t["name"] = info[r + 8:r + 0x20].split(b"\0")[0].decode("latin-1")
        (t["hash"],) = struct.unpack_from("<I", info, r + 0x20)
        t["width"], t["height"] = struct.unpack_from("<2H", info, r + 0x24)
        t["bpp"], t["flags"] = struct.unpack_from("<2B", info, r + 0x28)
        (t["palette_entries"],) = struct.unpack_from("<H", info, r + 0x2A)
        (t["data_offset"], t["palette_offset"], t["data_size"],
         t["palette_size"]) = struct.unpack_from("<4I", info, r + 0x30)
        (t["shares_with"],) = struct.unpack_from("<I", info, r + 0x40)
        t["tw"], t["th"], t["psm"], t["cpsm"] = struct.unpack_from("<4B", info, r + 0x48)
        (t["tbw"],) = struct.unpack_from("<B", info, r + 0x54)
        yield t


# --- PS2 texture swizzle -------------------------------------------------
#
# GS memory is organised in 8KB pages of 32 blocks of 4 columns, and an 8-bit
# texture laid into it ends up interleaved the way unswizzle_map8() undoes.
# Reading it as a bit permutation of the linear address makes the structure
# plain: bit0 <- y1, bit1 <- x3, bits 2..4 <- x0, x1, x2^y1^y2, then the rest
# of x, then y0, y2, y3, then the rest of y. The `x2^y1^y2` term is the GS's
# column swap; dropping it still leaves the image legible, but shifted in
# alternating 4-row bands -- the usual sign of getting this wrong.

_cache = {}


def unswizzle_map8(w, h):
    """dst linear index -> src byte offset, for PSMT8."""
    key = (8, w, h)
    if key not in _cache:
        m = [0] * (w * h)
        for y in range(h):
            band = (y & ~0xF) * w
            swap = (((y + 2) >> 2) & 1) * 4
            col = ((((y & ~3) >> 1) + (y & 1)) & 7) * w * 2 + ((y >> 1) & 1)
            row = y * w
            for x in range(w):
                m[row + x] = (band + (x & ~0xF) * 2 + col
                              + ((x + swap) & 7) * 4 + ((x >> 2) & 2))
        _cache[key] = m
    return _cache[key]


def unswizzle_map4(w, h):
    """dst linear index -> src *nibble* offset (byte * 2 + low/high), PSMT4.

    UNVERIFIED. This is the 8-bit layout scaled to nibbles: it produces a
    bijective mapping over exactly the right address range, but it does not
    reconstruct recognisable art, so the real PSMT4 column order must differ.
    Kept so the 4-bit path is at least deterministic and easy to correct;
    `--swizzle none` is the honest fallback until it is solved.
    """
    key = (4, w, h)
    if key not in _cache:
        m = [0] * (w * h)
        for y in range(h):
            band = (y & ~0xF) * (w >> 1)
            swap = (((y + 2) >> 2) & 1) * 4
            col = ((((y & ~3) >> 1) + (y & 1)) & 7) * w
            hi = (y >> 1) & 1
            row = y * w
            for x in range(w):
                byte = (band + col + (x >> 5) * 32
                        + ((x + swap) & 7) * 4 + ((x >> 3) & 3))
                m[row + x] = byte * 2 + hi
        _cache[key] = m
    return _cache[key]


def read_palette(pal):
    """PS2 RGBA8 -> RGBA8888. Alpha is 0..128, so it doubles into 0..255."""
    entries = len(pal) // 4
    out = bytearray(entries * 4)
    for i in range(entries):
        out[i * 4:i * 4 + 3] = pal[i * 4:i * 4 + 3]
        out[i * 4 + 3] = min(255, pal[i * 4 + 3] * 2)
    return out, entries


def decode(t, data, swizzle=True):
    """Return (width, height, RGBA bytes) for one texture, or None if unsupported."""
    w, h, bpp = t["width"], t["height"], t["bpp"]
    if w == 0 or h == 0:
        return None
    px = data[t["data_offset"]:t["data_offset"] + t["data_size"]]
    pal = data[t["palette_offset"]:t["palette_offset"] + t["palette_size"]]

    if bpp == 32:
        if len(px) < w * h * 4:
            return None
        out = bytearray(w * h * 4)
        for i in range(0, w * h * 4, 4):
            out[i:i + 3] = px[i:i + 3]
            out[i + 3] = min(255, px[i + 3] * 2)
        return w, h, bytes(out)

    if bpp not in (4, 8) or not pal:
        return None
    rgba, entries = read_palette(pal)

    # The block geometry only closes on 16x16 (8-bit) / 32x16 (4-bit)
    # boundaries. Anything smaller -- HUD pips, 8x8 lens flares -- fits inside
    # one block and is stored linearly, so fall back rather than reading off
    # the end of the buffer.
    if bpp == 8:
        if len(px) < w * h:
            return None
        src = range(w * h)
        if swizzle and w % 16 == 0 and h % 16 == 0:
            src = unswizzle_map8(w, h)
        idx = [px[a] for a in src]
    else:
        if len(px) * 2 < w * h:
            return None
        src = range(w * h)
        if swizzle and w % 32 == 0 and h % 16 == 0:
            src = unswizzle_map4(w, h)
        idx = [(px[a >> 1] >> ((a & 1) * 4)) & 0xF for a in src]

    out = bytearray(w * h * 4)
    for i, v in enumerate(idx):
        if v >= entries:
            v = 0
        out[i * 4:i * 4 + 4] = rgba[v * 4:v * 4 + 4]
    return w, h, bytes(out)


def write_png(path, w, h, rgba):
    raw = bytearray()
    stride = w * 4
    for y in range(h):
        raw.append(0)                       # per-scanline filter type 0 (None)
        raw += rgba[y * stride:(y + 1) * stride]

    def chunk(tag, payload):
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    Path(path).write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b""))


def safe_name(t):
    name = t["name"] or ("%08x" % t["hash"])
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("out_dir", nargs="?")
    ap.add_argument("--list", action="store_true", help="print the table, convert nothing")
    ap.add_argument("--swizzle", choices=("ps2", "none"), default="ps2")
    a = ap.parse_args()
    if not a.list and not a.out_dir:
        ap.error("give an output directory, or --list")

    buf = Path(a.file).read_bytes()
    packs = list(find_packs(buf))
    if not packs:
        raise SystemExit("no 0xb0300001 texture pack in %s" % a.file)

    written = skipped = 0
    for off, size in packs:
        pack_name, info, data = parse_pack(buf, off, size)
        if a.list:
            print("== pack %r @0x%x: %d textures, %d bytes of pixel data =="
                  % (pack_name, off, len(info) // RECORD_SIZE, len(data)))
            print("%-26s %5s %5s %4s %-8s %9s %8s %s"
                  % ("name", "w", "h", "bpp", "psm", "data", "palette", "shares"))
        for t in textures(info):
            if a.list:
                print("%-26s %5d %5d %4d %-8s %9d %8d %s"
                      % (t["name"], t["width"], t["height"], t["bpp"],
                         PSM_NAMES.get(t["psm"], "0x%02x" % t["psm"]),
                         t["data_size"], t["palette_size"],
                         "%08x" % t["shares_with"] if t["shares_with"] else ""))
                continue
            got = decode(t, data, a.swizzle == "ps2")
            if got is None:
                print("skipped %s (%dx%d %dbpp)"
                      % (t["name"], t["width"], t["height"], t["bpp"]), file=sys.stderr)
                skipped += 1
                continue
            d = Path(a.out_dir) / (pack_name or "pack")
            d.mkdir(parents=True, exist_ok=True)
            write_png(d / (safe_name(t) + ".png"), *got)
            written += 1
    if not a.list:
        print("wrote %d PNGs (%d skipped) to %s" % (written, skipped, a.out_dir))


if __name__ == "__main__":
    main()
