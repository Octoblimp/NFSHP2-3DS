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
    +0x52  TextureImageInfo[7]   per mip level, from the .mdebug type info:
                     {u16 TextureBasePointerOffset, u8 TextureBufferWidth,
                      s8 Is32BitSwizzelled} -- so +0x54 is level 0's TBW and
                     +0x55 is level 0's Is32BitSwizzelled
    +0x6e  s8        NumMipMapLevels -- levels after the base, so 0 means one

Palettes are RGBA8 with PS2 alpha (0x80 = opaque), stored linearly: the game
uploads them to the GS verbatim and only ever calls `RemapLinearIntoClut8()`
on palettes it builds at runtime (fog, focus, movie YUV), never on these.

Whether the pixels are swizzled is decided by that +0x55 flag -- bWare calls
it `Is32BitSwizzelled`, which says what it is outright -- and
`FillVramWithTextures` (0x001081f8) reads it at 0x0010850c:

    flag == 0   upload with DPSM = PSM at the real size -- plain raster data
    flag == 1   upload with DPSM = PSMCT32 at (width/2, height/2) for 8bpp or
                (width/2, height/4) for 4bpp, and DBW = TBW/2 -- the file holds
                a 32-bit image that the GS re-reads as PSMT8/PSMT4, i.e. the
                pixels are pre-swizzled into GS page/block/column order

So the "PS2 texture swizzle" here is not a property of the format but of the
individual texture, and both readings are needed. See
docs/formats/texture-pack.md for the layout the swizzled case unpicks.

Mipmapped textures store the chain after the base level (data size is then
4/3 of width*height*bpp/8); only the base level is emitted.

The sibling container 0xb0300100 is the TextureAnimPack: the flipbook
animations, in the same three-leaf shape (0x30300101 header, 0x30300102 a
table of 52-byte TextureAnim records, 0x30300103 one flat run of 16-byte
TextureAnimEntry records). An animation owns the next NumFrames entries, and
the runtime plays it by rotating the frames' pixel/CLUT pointers among their
TextureInfo records rather than re-uploading anything. `--anims` lists them;
a conversion run writes an anims.csv beside the PNGs.

Usage:
    python tools/texture_convert.py <file> --list
    python tools/texture_convert.py <file> --anims
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

# The TextureAnimPack sibling container, same three-leaf shape.
ANIM_PACK = 0xB0300100
ANIM_HEADER = 0x30300101
ANIM_INFO = 0x30300102
ANIM_ENTRIES = 0x30300103
ANIM_SIZE = 52
ANIM_ENTRY_SIZE = 16

PSM_NAMES = {0x00: "PSMCT32", 0x13: "PSMT8", 0x14: "PSMT4"}


def find_packs(buf, off=0, end=None, depth=0, want=TEXTURE_PACK):
    """Yield (offset, size) of every `want` chunk, including nested ones."""
    if end is None:
        end = len(buf)
    while off + 8 <= end:
        ctype, csize = struct.unpack_from("<II", buf, off)
        if ctype == 0 and csize == 0:
            break
        cend = off + 8 + csize
        if cend > end:
            break
        if ctype == want:
            yield off, csize
        elif ctype & 0x80000000 and depth < 8:
            # A .BUN bundle nests its packs inside other containers.
            for hit in find_packs(buf, off + 8, cend, depth + 1, want):
                yield hit
        off = cend


def align_up(x, n):
    return (x + n - 1) & ~(n - 1)


def parse_pack(buf, off, size):
    """Return (name, info, data) for one 0xb0300001 texture pack.

    `data` is what ImagePlacement and PalettePlacement are relative to, and
    that is not the 0x30300004 payload: LoaderTexturePack (0x00100830)
    rounds the payload address up to a 128-byte boundary first --

        001008a8  addiu  s2,v0,143      ; v0 + 8 (the payload) + 135
        001008b0  and    s2,s2,a3       ; a3 = -128

    -- and the packer pads the gap with 0x11 bytes. The bundle is loaded at
    a 128-byte-aligned address, so the file offset aligns the same way.
    Miss this and every texture is shifted by up to 127 bytes, which reads
    as a horizontal roll of the image.
    """
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
            data = buf[align_up(p + 8, 128):p + 8 + csize]
        p += 8 + csize
    return name, info, data


def parse_anim_pack(buf, off, size):
    version, anims, entries = None, b"", b""
    p, end = off + 8, off + 8 + size
    while p + 8 <= end:
        ctype, csize = struct.unpack_from("<II", buf, p)
        payload = buf[p + 8:p + 8 + csize]
        if ctype == ANIM_HEADER and csize >= 4:
            version = struct.unpack_from("<I", payload, 0)[0]
        elif ctype == ANIM_INFO:
            anims = payload
        elif ctype == ANIM_ENTRIES:
            entries = payload
        p += 8 + csize
    return version, anims, entries


def animations(anims, entries):
    """Yield one dict per `TextureAnim` (52 bytes).

    The entry table is one flat run of 16-byte `TextureAnimEntry` records,
    `NumFrames` of them per animation in table order: the pack constructor
    (`0x001a1650`) hands each animation a pointer into it and advances by
    `NumFrames * 16`, so the split is implied rather than stored.
    """
    cursor = 0
    for r in range(0, len(anims) - ANIM_SIZE + 1, ANIM_SIZE):
        rec = anims[r:r + ANIM_SIZE]
        a = {"name": rec[:24].split(b"\0")[0].decode("latin-1")}
        a["hash"], a["frames"], a["fps"], a["timebase"] =             struct.unpack_from("<Iiii", rec, 24)
        a["frame_hashes"] = [
            struct.unpack_from("<I", entries, (cursor + i) * ANIM_ENTRY_SIZE)[0]
            for i in range(max(0, a["frames"]))
            if (cursor + i + 1) * ANIM_ENTRY_SIZE <= len(entries)]
        cursor += max(0, a["frames"])
        yield a


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
        # +0x52 is TextureImageInfo[7], one per mip level; +0x54/+0x55 are
        # level 0's TextureBufferWidth and Is32BitSwizzelled.
        (t["tbw"], t["is32bit_swizzled"]) = struct.unpack_from("<Bb", info, r + 0x54)
        (t["levels"],) = struct.unpack_from("<b", info, r + 0x6E)
        t["levels"] += 1                       # NumMipMapLevels excludes the base
        t["image_infos"] = [
            struct.unpack_from("<HBb", info, r + 0x52 + i * 4)
            for i in range(min(7, max(1, t["levels"])))]
        # The UV animation: ScrollType at +0x79, then the two speeds and the
        # time step. TextureInfo::GetScroll (0x00100a60) turns them into the
        # offset added to U and V; see docs/formats/texture-pack.md.
        (t["scroll_type"],) = struct.unpack_from("<b", info, r + 0x79)
        (t["scroll_s"], t["scroll_t"],
         t["scroll_step"]) = struct.unpack_from("<3f", info, r + 0x7C)
        yield t


def f32(x):
    """Round to single precision. The EE's FPU has no double, and so neither
    does the 3DS port's texpack_scroll_axis(), so every intermediate here is
    rounded the same way -- otherwise the two agree to six decimals by luck
    rather than by construction."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


def scroll_uv(t, time):
    """TextureInfo::GetScroll (0x00100a60), for both axes: (du, dv)."""
    def one(speed):
        if not t["scroll_type"]:
            return 0.0
        u = f32(time)
        if t["scroll_type"] == 2:
            # A zero step would divide by zero on the PS2; none on the disc
            # does, and texpack_scroll_axis() guards it the same way.
            u = f32(float(int(f32(u / t["scroll_step"]))))                 if t["scroll_step"] else 0.0
        f = f32(u * speed)
        return f32(f - float(int(f)))
    return one(t["scroll_s"]), one(t["scroll_t"])


def mip_chain(t):
    """Yield (level, width, height, offset, nbytes) for a texture's mip chain.

    The levels sit one after another in the pack's data blob, base first,
    each halving both dimensions. Checked across the archive: the sum matches
    the record's own `0x38` byte count on all 1,755 textures that own their
    pixels, at every level count from 1 to 7.
    """
    off = 0
    for level in range(max(1, t["levels"])):
        w = max(1, t["width"] >> level)
        h = max(1, t["height"] >> level)
        n = w * h * t["bpp"] // 8
        yield level, w, h, off, n
        off += n


# --- PS2 texture swizzle -------------------------------------------------
#
# A flagged texture is uploaded as PSMCT32 and read back as PSMT8/PSMT4, so
# the file holds a 32-bit raster `width/2` texels wide -- half as many rows
# again for 8bpp, a quarter for 4bpp -- and the job is to work out where the
# GS finds texel (x, y) inside it.
#
# GS memory is pages of 32 blocks of 4 columns, and each format tiles them
# differently: a PSMCT32 page is 64x32 texels of 8x8 blocks, a PSMT8 page is
# 128x64 of 16x16, a PSMT4 page is 128x128 of 32x16. Pages therefore line up
# exactly, and so does the 8x4 block grid inside a PSMT8 page. A PSMT4 page's
# block grid is 4x8, the *transpose* of PSMCT32's -- which is the one thing
# that makes 4-bit differ in shape from 8-bit rather than just in scale.
#
# Inside a block, the source bits land like this (cx, cy are the coordinates
# within the block, `col` = cy >> 2 the column, `swap` the GS column swizzle):
#
#     8bpp                            4bpp
#     cx0, cx1, cx2^swap -> host x    cx0, cx1, cx2^swap -> host x
#     cx3                -> byte 1    cx3, cx4           -> nibble 1, 2
#     cy0                -> host y    cy0                -> host y
#     cy1                -> byte 0    cy1                -> nibble 0
#
# so one host 32-bit word holds the 4bpp texels (x, x+8, x+16, x+24) of two
# rows 2 apart. Dropping the `swap` term leaves the image recognisable but
# torn into alternating 4-row bands -- the useful failure signature.

_cache = {}


def unswizzle_map8(w, h):
    """dst linear index -> src byte offset, for PSMT8."""
    key = (8, w, h)
    if key not in _cache:
        m = [0] * (w * h)
        for y in range(h):
            page_y, py = y >> 6, y & 63
            block_y, cy = py >> 4, py & 15
            col = cy >> 2
            swap = ((cy >> 1) & 1) ^ (col & 1)
            base = (page_y * 64 * w + block_y * 16 * w + col * 4 * w
                    + (cy & 1) * 2 * w + ((cy >> 1) & 1))
            for x in range(w):
                page_x, px = x >> 7, x & 127
                block_x, cx = px >> 4, px & 15
                m[y * w + x] = (base + page_x * 256 + block_x * 32
                                + ((cx >> 3) & 1) * 2
                                + (cx & 1) * 4 + ((cx >> 1) & 1) * 8
                                + (((cx >> 2) & 1) ^ swap) * 16)
        _cache[key] = m
    return _cache[key]


def unswizzle_map4(w, h):
    """dst linear index -> src *nibble* offset (byte * 2 + low/high), PSMT4."""
    key = (4, w, h)
    if key not in _cache:
        m = [0] * (w * h)
        for y in range(h):
            page_y, py = y >> 7, y & 127
            block_y, cy = py >> 4, py & 15
            col = cy >> 2
            swap = ((cy >> 1) & 1) ^ (col & 1)
            base = (page_y * 128 * w + col * 8 * w + (cy & 1) * 4 * w
                    + block_y * 64 + ((cy >> 1) & 1))
            for x in range(w):
                page_x, px = x >> 7, x & 127
                block_x, cx = px >> 5, px & 31
                m[y * w + x] = (base + page_x * 512 + block_x * 32 * w
                                + ((cx >> 3) & 1) * 2 + ((cx >> 4) & 1) * 4
                                + (cx & 1) * 8 + ((cx >> 1) & 1) * 16
                                + (((cx >> 2) & 1) ^ swap) * 32)
        _cache[key] = m
    return _cache[key]


def geometry_closes(w, h, bpp):
    """Can the swizzle be undone in closed form at this size?

    The host raster has to be a whole number of PSMCT32 pages wide (64 texels,
    so 128 of ours) and a whole number of blocks tall. Every flagged texture
    in the build satisfies this; nothing else is expected to reach it.
    """
    return w % 128 == 0 and h % (64 if bpp == 8 else 128) == 0


# A PSMT8 CLUT is stored in GS CSM1 order, so entries 8..15 and 16..23 of
# every group of 32 are the other way round. bWare names the permutation
# itself: `RemapLinearIntoClut8__FPUiT0` (0x00118878) is the routine that puts
# a palette the engine *built* into that order, and all it does is swap those
# two quadword pairs --
#
#   0011889c  lq  v0,64(t2)   ; entries 16..19
#   001188b8  sq  v0,32(t3)   ; ... stored where 8..11 would be
#   00118894  lq  t0,32(t2)   ; entries 8..11
#   001188c0  sq  t0,64(t3)   ; ... stored where 16..19 would be
#
# eight times over 32 entries a pass. Pack CLUTs are uploaded raw, never
# through that routine, so they are already in CSM1 order and the host has to
# undo it. The permutation is an involution, so the same table does both.
#
# A PSMT4 CLUT is linear: its CSM1 region is 8x2 words, with nothing to
# exchange. The two sizes are told apart by `bpp`, not by the entry count --
# `TUNNELROADSIDEB` carries a 32-entry PSMT8 CLUT and needs the swap inside
# that one group just as much (its grey ramp runs 1..7 then 16..23, with
# 9..15 left white).


def clut_order(entries, bpp):
    """Stored index for each logical palette index."""
    if bpp != 8:
        return range(entries)
    out = []
    for i in range(entries):
        j = i ^ 0x18 if (i & 0x18) in (0x08, 0x10) else i
        out.append(j if j < entries else i)
    return out


def read_palette(pal, bpp=8):
    """PS2 RGBA8 -> RGBA8888. Alpha is 0..128, so it doubles into 0..255."""
    entries = len(pal) // 4
    out = bytearray(entries * 4)
    for i, s in enumerate(clut_order(entries, bpp)):
        out[i * 4:i * 4 + 3] = pal[s * 4:s * 4 + 3]
        out[i * 4 + 3] = min(255, pal[s * 4 + 3] * 2)
    return out, entries


def decode(t, data, swizzle="auto", level=0):
    """Return (width, height, RGBA bytes) for one mip level, or None.

    `level` 0 is the base image. Each level carries its own
    `Is32BitSwizzelled` flag in the `0x52` array, so a chain can be swizzled
    at some sizes and raster at others.
    """
    bpp = t["bpp"]
    for lvl, lw, lh, loff, lsize in mip_chain(t):
        if lvl == level:
            w, h, base, size = lw, lh, t["data_offset"] + loff, lsize
            break
    else:
        return None
    if w == 0 or h == 0 or size == 0:
        return None
    px = data[base:base + size]
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
    rgba, entries = read_palette(pal, bpp)

    # Only the textures flagged at +0x55 are swizzled; the rest are plain
    # raster. `all` forces the unswizzle anyway, for checking a hunch.
    infos = t.get("image_infos") or []
    flag = infos[level][2] if level < len(infos) else t["is32bit_swizzled"]
    unswizzle = swizzle == "all" or (swizzle == "auto" and flag == 1)
    unswizzle = unswizzle and geometry_closes(w, h, bpp)

    if bpp == 8:
        if len(px) < w * h:
            return None
        src = unswizzle_map8(w, h) if unswizzle else range(w * h)
        idx = [px[a] for a in src]
    else:
        if len(px) * 2 < w * h:
            return None
        src = unswizzle_map4(w, h) if unswizzle else range(w * h)
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
    ap.add_argument("--anims", action="store_true",
                    help="print the 0xb0300100 TextureAnimPack table, convert nothing")
    ap.add_argument("--scroll", action="store_true",
                    help="print the UV-scrolling textures (ScrollType != 0), "
                         "convert nothing")
    ap.add_argument("--mips", action="store_true",
                    help="also write every mip level below the base, as "
                         "<name>.mip<N>.png")
    ap.add_argument("--swizzle", choices=("auto", "none", "all"), default="auto",
                    help="auto: unswizzle exactly the textures flagged at +0x55 "
                         "(the default, and what the game does); none: dump the "
                         "data as stored; all: unswizzle every paletted texture")
    a = ap.parse_args()
    if not a.list and not a.anims and not a.scroll and not a.out_dir:
        ap.error("give an output directory, or --list, --anims or --scroll")

    buf = Path(a.file).read_bytes()
    packs = list(find_packs(buf))
    anim_packs = list(find_packs(buf, want=ANIM_PACK))
    if not packs and not anim_packs:
        raise SystemExit("no 0xb0300001 texture pack in %s" % a.file)

    # Animations reference their frames by name hash, so build the reverse map
    # from every texture table in the file before anything else.
    by_hash = {}
    for off, size in packs:
        _pname, info, _data = parse_pack(buf, off, size)
        for t in textures(info):
            by_hash.setdefault(t["hash"], t["name"])

    if a.anims:
        if not anim_packs:
            print("no 0xb0300100 anim pack in %s" % a.file)
            return
        for off, size in anim_packs:
            version, anims, entries = parse_anim_pack(buf, off, size)
            rows = list(animations(anims, entries))
            print("== anim pack @0x%x: version %s, %d animations, %d frames =="
                  % (off, version, len(rows), len(entries) // ANIM_ENTRY_SIZE))
            for an in rows:
                print("%-26s %08x  %2d frames  %3d fps  timebase %d"
                      % (an["name"], an["hash"], an["frames"], an["fps"],
                         an["timebase"]))
                for i, h in enumerate(an["frame_hashes"]):
                    print("    %2d  %08x  %s"
                          % (i, h, by_hash.get(h, "<not in this file>")))
        return

    if a.scroll:
        for off, size in packs:
            pack_name, info, _data = parse_pack(buf, off, size)
            rows = [t for t in textures(info) if t["scroll_type"]]
            print("== pack %r @0x%x: %d of %d textures scroll =="
                  % (pack_name, off, len(rows), len(info) // RECORD_SIZE))
            for t in rows:
                print("%-26s type %d  S %+.6f  T %+.6f  step %g"
                      % (t["name"], t["scroll_type"], t["scroll_s"],
                         t["scroll_t"], t["scroll_step"]))
        return

    written = skipped = 0
    for off, size in packs:
        pack_name, info, data = parse_pack(buf, off, size)
        if a.list:
            print("== pack %r @0x%x: %d textures, %d bytes of pixel data =="
                  % (pack_name, off, len(info) // RECORD_SIZE, len(data)))
            print("%-26s %5s %5s %4s %-8s %9s %8s %4s %3s %s"
                  % ("name", "w", "h", "bpp", "psm", "data", "palette",
                     "swiz", "mip", "shares"))
        for t in textures(info):
            if a.list:
                print("%-26s %5d %5d %4d %-8s %9d %8d %4s %3d %s"
                      % (t["name"], t["width"], t["height"], t["bpp"],
                         PSM_NAMES.get(t["psm"], "0x%02x" % t["psm"]),
                         t["data_size"], t["palette_size"],
                         "yes" if t["is32bit_swizzled"] == 1 else "no", t["levels"],
                         "%08x" % t["shares_with"] if t["shares_with"] else ""))
                continue
            got = decode(t, data, a.swizzle)
            if got is None:
                print("skipped %s (%dx%d %dbpp)"
                      % (t["name"], t["width"], t["height"], t["bpp"]), file=sys.stderr)
                skipped += 1
                continue
            d = Path(a.out_dir) / (pack_name or "pack")
            d.mkdir(parents=True, exist_ok=True)
            write_png(d / (safe_name(t) + ".png"), *got)
            written += 1
            if a.mips and not t["shares_with"]:
                for level in range(1, t["levels"]):
                    sub = decode(t, data, a.swizzle, level)
                    if sub is None:
                        continue
                    write_png(d / ("%s.mip%d.png" % (safe_name(t), level)), *sub)
                    written += 1
    if a.list:
        return

    # One row per frame, in play order, so the sequence can be rebuilt from
    # the PNGs without re-reading the chunk.
    rows = [("animation", "hash", "frames", "fps", "timebase",
             "frame", "texture", "file")]
    for off, size in anim_packs:
        _version, anims, entries = parse_anim_pack(buf, off, size)
        for an in animations(anims, entries):
            for i, h in enumerate(an["frame_hashes"]):
                name = by_hash.get(h, "")
                rows.append((an["name"], "%08x" % an["hash"], an["frames"],
                             an["fps"], an["timebase"], i, name,
                             (name + ".png") if name else ""))
    if len(rows) > 1:
        out = Path(a.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "anims.csv", "w", encoding="utf-8", newline="\n") as f:
            for row in rows:
                f.write(",".join(str(c) for c in row) + "\n")
    print("wrote %d PNGs (%d skipped) and %d animation frames to %s"
          % (written, skipped, len(rows) - 1, a.out_dir))


if __name__ == "__main__":
    main()
