#!/usr/bin/env python3
r"""Bake a decoded MV3 movie into the `.M3V` sequence the 3DS port plays.

There is exactly one movie on the disc -- `MOVIES\INTRO\EALOGO_EN.AVI`, 512x256,
30 fps, 90 frames -- and decoding it costs about 5 million emulated PS2
instructions per frame (`tools/video_extract.py`, and see
`docs/formats/mv3-video.md`). Porting that decoder to the 3DS to replay three
seconds of EA logo would be the wrong trade, so the port pre-decodes instead:
`video_extract.py` writes 90 PNGs, this writes the single file the console
streams.

    python tools/video_extract.py extracted/MOVIES/INTRO/EALOGO_EN.AVI out/
    python tools/movie_bake.py out/EALOGO_EN <data>/MOVIES/INTRO/EALOGO_EN.M3V

What comes out is already in the GPU's layout -- RGB565 in 8x8 Morton tiles,
the same arrangement `texpack_upload` builds by hand -- so playback is an RLE
expansion straight into `C3D_Tex::data` with no per-pixel work.

Two things do the compressing, and both exploit the same fact, that this is a
logo on a black field:

* **Tile skipping.** A delta frame carries a bitmap of which 8x8 tiles differ
  from the frame before, and data for those only.
* **RLE16.** A u16 control word per run: bit 15 set means repeat the next
  pixel `(ctrl & 0x7fff) + 1` times, clear means `ctrl + 1` literal pixels
  follow. Runs cross tile boundaries, so a black region costs nothing extra
  for being split up.

The format, all little-endian:

    0x00  char[4]  "M3V1"
    0x04  u16      width, u16 height, u16 frames, u16 fps
    0x0c  u16      format (0 = RGB565 / 3DS Morton tiles)
    0x0e  u16      bytes per tile (128)
    0x10  u32      largest frame payload, so the player sizes one buffer
    0x14  u32      frame table offset
    0x18  u32      audio offset, u32 audio length, u32 sample rate
    0x24  u16      channels, u16 bits per sample
    0x28  u32[2]   reserved, zero
    0x30           frame table: `frames` x { u32 offset, u32 length }
                   frame payloads
                   audio: raw PCM exactly as the AVI stored it

    frame payload:  u8 kind (0 = full, 1 = delta)
                    if delta: u8[(tiles + 7) / 8] changed-tile bitmap, LSB first
                    RLE16 over the changed tiles' pixels, in tile order

A full frame is the first one; every later one is a delta, which makes the
movie play-through-only. That is all the title sequence ever does with it.
"""

import argparse
import os
import struct
import sys
import zlib

MAGIC = b"M3V1"
HEADER_SIZE = 0x30
FMT_RGB565_TILED = 0
TILE = 8
TILE_PIXELS = TILE * TILE


# -- PNG reading, stdlib only ------------------------------------------------

def read_png(path):
    """Return (width, height, RGBA bytes). Handles what video_extract writes."""
    raw = open(path, "rb").read()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("%s is not a PNG" % path)
    pos, idat, w, h, depth, color = 8, [], None, None, None, None
    while pos + 8 <= len(raw):
        (length,) = struct.unpack_from(">I", raw, pos)
        ctype = raw[pos + 4:pos + 8]
        body = raw[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            w, h, depth, color = struct.unpack_from(">IIBB", body, 0)
        elif ctype == b"IDAT":
            idat.append(body)
        elif ctype == b"IEND":
            break
        pos += 12 + length
    if depth != 8 or color not in (2, 6):
        raise ValueError("%s: only 8-bit RGB/RGBA PNGs are handled" % path)

    src = zlib.decompress(b"".join(idat))
    nch = 3 if color == 2 else 4
    stride = w * nch
    out = bytearray(w * h * 4)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        f = src[p]
        p += 1
        line = bytearray(src[p:p + stride])
        p += stride
        if f == 1:
            for x in range(nch, stride):
                line[x] = (line[x] + line[x - nch]) & 0xFF
        elif f == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 0xFF
        elif f == 3:
            for x in range(stride):
                a = line[x - nch] if x >= nch else 0
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 0xFF
        elif f == 4:
            for x in range(stride):
                a = line[x - nch] if x >= nch else 0
                b = prev[x]
                c = prev[x - nch] if x >= nch else 0
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 0xFF
        elif f != 0:
            raise ValueError("%s: bad PNG filter %d" % (path, f))
        prev = line
        base = y * w * 4
        if nch == 4:
            out[base:base + w * 4] = line
        else:
            for x in range(w):
                out[base + x * 4:base + x * 4 + 3] = line[x * 3:x * 3 + 3]
                out[base + x * 4 + 3] = 255
    return w, h, bytes(out)


# -- RGBA -> RGB565 in the PICA200's tile order ------------------------------

def morton8(x, y):
    return ((x & 1) | ((y & 1) << 1)
            | ((x & 2) << 1) | ((y & 2) << 2)
            | ((x & 4) << 2) | ((y & 4) << 3))


_MORTON = [morton8(x, y) for y in range(TILE) for x in range(TILE)]


def tile_pixels(rgba, w, h):
    """Return one list of u16 per 8x8 tile, tiles in raster order.

    This is `texpack_upload`'s layout (`3DS Files/source/texpack.c`) at 16 bpp:
    tile = (y >> 3) * (w >> 3) + (x >> 3), Morton order inside the tile.
    """
    tiles_x, tiles_y = w // TILE, h // TILE
    out = []
    for ty in range(tiles_y):
        for tx in range(tiles_x):
            px = [0] * TILE_PIXELS
            for sy in range(TILE):
                row = ((ty * TILE + sy) * w + tx * TILE) * 4
                for sx in range(TILE):
                    s = row + sx * 4
                    px[_MORTON[sy * TILE + sx]] = (
                        ((rgba[s] >> 3) << 11)
                        | ((rgba[s + 1] >> 2) << 5)
                        | (rgba[s + 2] >> 3))
            out.append(px)
    return out


def untile_rgb565(tiles, w, h):
    """The inverse, for tools that want to look at a baked frame."""
    tiles_x = w // TILE
    out = [0] * (w * h)
    for i, px in enumerate(tiles):
        tx, ty = i % tiles_x, i // tiles_x
        for sy in range(TILE):
            for sx in range(TILE):
                out[(ty * TILE + sy) * w + tx * TILE + sx] = \
                    px[_MORTON[sy * TILE + sx]]
    return out


# -- RLE16 -------------------------------------------------------------------

MAX_RUN = 0x8000


def rle16_encode(pixels):
    """Encode a flat pixel list. Mirrored by m3v_expand() in movie.c."""
    out = bytearray()
    n = len(pixels)
    i = 0
    while i < n:
        j = i + 1
        while j < n and pixels[j] == pixels[i] and j - i < MAX_RUN:
            j += 1
        if j - i >= 3:
            out += struct.pack("<HH", 0x8000 | (j - i - 1), pixels[i])
            i = j
            continue
        # A literal run ends where a repeat of 3 starts paying for itself.
        j = i
        while j < n and j - i < MAX_RUN:
            if j + 2 < n and pixels[j] == pixels[j + 1] == pixels[j + 2]:
                break
            j += 1
        if j == i:
            j = i + 1
        out += struct.pack("<H", j - i - 1)
        out += struct.pack("<%dH" % (j - i), *pixels[i:j])
        i = j
    return bytes(out)


def rle16_decode(data, count, pos=0):
    """The reference decoder, used by tools/movie_check.py."""
    out = []
    while len(out) < count:
        (ctrl,) = struct.unpack_from("<H", data, pos)
        pos += 2
        if ctrl & 0x8000:
            (px,) = struct.unpack_from("<H", data, pos)
            pos += 2
            out.extend([px] * ((ctrl & 0x7FFF) + 1))
        else:
            n = ctrl + 1
            out.extend(struct.unpack_from("<%dH" % n, data, pos))
            pos += n * 2
    if len(out) != count:
        raise ValueError("RLE overran: %d for %d" % (len(out), count))
    return out, pos


# -- the baker ---------------------------------------------------------------

def wav_payload(path):
    """(pcm, rate, channels, bits) out of the WAV video_extract writes."""
    raw = open(path, "rb").read()
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError("%s is not a WAV" % path)
    pos, fmt, data = 12, None, b""
    while pos + 8 <= len(raw):
        cid = raw[pos:pos + 4]
        (size,) = struct.unpack_from("<I", raw, pos + 4)
        body = raw[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = struct.unpack_from("<HHIIHH", body, 0)
        elif cid == b"data":
            data = body
        pos += 8 + size + (size & 1)
    if not fmt:
        raise ValueError("%s has no fmt chunk" % path)
    return data, fmt[2], fmt[1], fmt[5]


def frame_payload(tiles, prev):
    """(bytes, changed tile count). `prev` is None for the first frame."""
    if prev is None:
        body = bytearray([0])
        body += rle16_encode([px for t in tiles for px in t])
        return bytes(body), len(tiles)

    changed = [i for i, t in enumerate(tiles) if t != prev[i]]
    bitmap = bytearray((len(tiles) + 7) // 8)
    for i in changed:
        bitmap[i >> 3] |= 1 << (i & 7)
    body = bytearray([1])
    body += bitmap
    flat = [px for i in changed for px in tiles[i]]
    if flat:
        body += rle16_encode(flat)
    return bytes(body), len(changed)


def bake(frames, wav, out_path, fps, quiet=False):
    payloads, prev, total_changed = [], None, 0
    w = h = None
    for n, path in enumerate(frames):
        fw, fh, rgba = read_png(path)
        if w is None:
            w, h = fw, fh
            if w % TILE or h % TILE:
                raise SystemExit("frame size %dx%d is not a multiple of 8"
                                 % (w, h))
        elif (fw, fh) != (w, h):
            raise SystemExit("%s is %dx%d, expected %dx%d"
                             % (path, fw, fh, w, h))
        tiles = tile_pixels(rgba, w, h)
        body, changed = frame_payload(tiles, prev)
        payloads.append(body)
        total_changed += changed
        prev = tiles
        if not quiet:
            sys.stderr.write("\r  frame %d/%d  %5d tiles  %7d bytes"
                             % (n + 1, len(frames), changed, len(body)))
            sys.stderr.flush()
    if not quiet:
        sys.stderr.write("\n")

    pcm, rate, channels, bits = wav_payload(wav) if wav else (b"", 0, 0, 0)

    table_off = HEADER_SIZE
    data_off = table_off + len(payloads) * 8
    offsets, cursor = [], data_off
    for body in payloads:
        offsets.append(cursor)
        cursor += len(body)
    audio_off = cursor if pcm else 0

    head = bytearray(HEADER_SIZE)
    head[0:4] = MAGIC
    struct.pack_into("<4H", head, 4, w, h, len(payloads), fps)
    struct.pack_into("<2H", head, 0x0C, FMT_RGB565_TILED, TILE_PIXELS * 2)
    struct.pack_into("<2I", head, 0x10, max(len(b) for b in payloads),
                     table_off)
    struct.pack_into("<3I", head, 0x18, audio_off, len(pcm), rate)
    struct.pack_into("<2H", head, 0x24, channels, bits)

    with open(out_path, "wb") as f:
        f.write(head)
        for off, body in zip(offsets, payloads):
            f.write(struct.pack("<2I", off, len(body)))
        for body in payloads:
            f.write(body)
        if pcm:
            f.write(pcm)

    size = os.path.getsize(out_path)
    raw = w * h * 2 * len(payloads)
    if not quiet:
        print("%s  %dx%d  %d frames @ %d fps  %.2f MB"
              % (out_path, w, h, len(payloads), fps, size / 1048576.0))
        print("  %.1f%% of raw RGB565 (%.2f MB), %.1f%% of tiles touched"
              % (100.0 * size / raw, raw / 1048576.0,
                 100.0 * total_changed / (len(payloads) * (w // 8) * (h // 8))))
        if pcm:
            print("  audio %d bytes, %d Hz, %d ch, %d bit"
                  % (len(pcm), rate, channels, bits))
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames_dir",
                    help="a directory of <name>_NNNN.png written by "
                         "tools/video_extract.py")
    ap.add_argument("out", nargs="?", help="the .M3V to write")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    names = sorted(f for f in os.listdir(args.frames_dir)
                   if f.lower().endswith(".png"))
    if not names:
        raise SystemExit("no PNGs in %s" % args.frames_dir)
    frames = [os.path.join(args.frames_dir, f) for f in names]

    wav = None
    if not args.no_audio:
        wavs = [f for f in os.listdir(args.frames_dir)
                if f.lower().endswith(".wav")]
        if wavs:
            wav = os.path.join(args.frames_dir, wavs[0])

    out = args.out or os.path.join(
        args.frames_dir, names[0].rsplit("_", 1)[0] + ".M3V")
    bake(frames, wav, out, args.fps, args.quiet)


if __name__ == "__main__":
    main()
