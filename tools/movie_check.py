#!/usr/bin/env python3
r"""Check the 3DS C `.M3V` player against a second implementation in Python.

`3DS Files/source/movie.c` reads the format `tools/movie_bake.py` writes:
RGB565 already in the PICA200's 8x8 Morton tile order, a changed-tile bitmap
per frame, and an RLE16 stream whose runs cross tile boundaries. That is four
separate places to be subtly wrong, and three seconds of EA logo is not enough
footage to notice a wrong one by eye -- a stale tile in the corner of a black
field looks like nothing at all.

So this builds tools/src/movie_test.c for the host, runs it, decodes the same
file again here with an independent reader, and diffs a CRC32 of the whole
tile-order surface after every frame. It also checks the two agree on the
header, on where m3v_drive() lands after stepping at 60 fps, and on the PS2
path rewriting (`MOVIES\INTRO\EALOGO_EN.AVI` -> `MOVIES/INTRO/EALOGO_EN.M3V`).

    python tools/movie_check.py <file.M3V>
    python tools/movie_check.py <file.M3V> --png out/     # and look at it

The last form untiles each frame back to a PNG, because a cross-check proves
two implementations agree and not that either is right. The frames should be
the EA GAMES wordmark with the ring sweeping around it.
"""
import argparse
import os
import struct
import subprocess
import tempfile
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hostbuild                                # noqa: E402
import movie_bake as mb                         # noqa: E402

SOURCES = ["tools/src/movie_test.c", "3DS Files/source/movie.c"]


# -- the independent reader --------------------------------------------------

class Movie(object):
    def __init__(self, path):
        self.raw = open(path, "rb").read()
        if self.raw[:4] != mb.MAGIC:
            raise SystemExit("%s is not an .M3V" % path)
        (self.width, self.height, self.frames,
         self.fps) = struct.unpack_from("<4H", self.raw, 4)
        self.format, self.tile_bytes = struct.unpack_from("<2H", self.raw, 0x0C)
        (self.max_frame,
         self.table_off) = struct.unpack_from("<2I", self.raw, 0x10)
        (self.audio_off, self.audio_len,
         self.audio_rate) = struct.unpack_from("<3I", self.raw, 0x18)
        (self.audio_channels,
         self.audio_bits) = struct.unpack_from("<2H", self.raw, 0x24)
        self.num_tiles = (self.width // mb.TILE) * (self.height // mb.TILE)
        self.table = [struct.unpack_from("<2I", self.raw, self.table_off + i * 8)
                      for i in range(self.frames)]
        self.surface = [0] * (self.width * self.height)

    def duration(self):
        return float(self.frames) / float(self.fps)

    def apply(self, body):
        """Decode one payload into self.surface, the way m3v_apply() does."""
        kind = body[0]
        if kind == 0:
            changed, pos = range(self.num_tiles), 1
        elif kind == 1:
            n = (self.num_tiles + 7) // 8
            bitmap = body[1:1 + n]
            changed = [i for i in range(self.num_tiles)
                       if bitmap[i >> 3] & (1 << (i & 7))]
            pos = 1 + n
        else:
            raise SystemExit("bad frame kind %d" % kind)

        changed = list(changed)
        if changed:
            px, pos = mb.rle16_decode(body, len(changed) * mb.TILE_PIXELS, pos)
            for k, t in enumerate(changed):
                base = t * mb.TILE_PIXELS
                self.surface[base:base + mb.TILE_PIXELS] = \
                    px[k * mb.TILE_PIXELS:(k + 1) * mb.TILE_PIXELS]
        return len(changed)

    def next_frame(self, index):
        off, length = self.table[index]
        return self.apply(self.raw[off:off + length])

    def crc(self):
        buf = struct.pack("<%dH" % len(self.surface), *self.surface)
        return zlib.crc32(buf) & 0xFFFFFFFF


def baked_path(ps2, cap=128):
    """The Python mirror of m3v_baked_path()."""
    out = ps2.replace("\\", "/")
    if len(out) + 1 > cap:
        return None
    cut = out.rfind(".")
    if cut < 0 or cut < out.rfind("/"):
        cut = len(out)
    if cut + 5 > cap:
        return None
    return out[:cut] + ".M3V"


PATH_CASES = [
    "MOVIES\\INTRO\\EALOGO_EN.AVI",
    "MOVIES\\INTRO\\NFSINTRO_EN.AVI",
    "MOVIES\\ATTRACT\\ATTRACT1.avi",
    "NOEXTENSION",
    "MOVIES\\DIR.WITH.DOTS\\CLIP.AVI",
]


# -- the reference transcript ------------------------------------------------

def python_lines(path):
    m = Movie(path)
    out = ["movie %dx%d frames %d fps %d tiles %d maxframe %d"
           % (m.width, m.height, m.frames, m.fps, m.num_tiles, m.max_frame),
           "audio %d bytes %d Hz %d ch %d bit"
           % (m.audio_len, m.audio_rate, m.audio_channels, m.audio_bits),
           "duration %.4f" % m.duration()]
    for i in range(m.frames):
        m.next_frame(i)
        out.append("frame %d %08x" % (i, m.crc()))
    out.append("frames decoded %d" % m.frames)

    # m3v_drive at 60 fps: step until it says the movie is over.
    d = Movie(path)
    clock, nxt, steps, done = 0.0, 0, 0, False
    while not done and steps < 100000:
        clock += 1.0 / 60.0
        want = min(int(clock * d.fps) + 1, d.frames)
        while nxt < want:
            d.next_frame(nxt)
            nxt += 1
        done = nxt >= d.frames and clock >= d.duration()
        steps += 1
    out.append("drive steps %d frames %d done %d" % (steps, nxt, int(done)))
    out.append("drive crc %08x" % d.crc())

    for c in PATH_CASES:
        out.append("path %s -> %s" % (c, baked_path(c) or "FAIL"))
    out.append("path tiny -> %s" % (baked_path(PATH_CASES[0], 8) or "FAIL"))
    return out


# -- PNG output, for the eyeball half ----------------------------------------

def write_png(path, pixels565, w, h):
    rows = bytearray()
    for y in range(h):
        rows.append(0)
        for x in range(w):
            p = pixels565[y * w + x]
            r, g, b = (p >> 11) & 0x1F, (p >> 5) & 0x3F, p & 0x1F
            rows += bytes(((r << 3) | (r >> 2),
                           (g << 2) | (g >> 4),
                           (b << 3) | (b >> 2)))

    def chunk(tag, body):
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(bytes(rows), 9)))
        f.write(chunk(b"IEND", b""))


def dump_pngs(path, out_dir, every):
    m = Movie(path)
    os.makedirs(out_dir, exist_ok=True)
    n = 0
    for i in range(m.frames):
        m.next_frame(i)
        if i % every:
            continue
        flat = mb.untile_rgb565(
            [m.surface[t * mb.TILE_PIXELS:(t + 1) * mb.TILE_PIXELS]
             for t in range(m.num_tiles)], m.width, m.height)
        write_png(os.path.join(out_dir, "frame%04d.png" % i),
                  flat, m.width, m.height)
        n += 1
    print("wrote %d PNGs to %s" % (n, out_dir))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("movie", help="a .M3V from tools/movie_bake.py")
    ap.add_argument("--png", metavar="DIR",
                    help="also untile frames back to PNGs here")
    ap.add_argument("--every", type=int, default=1,
                    help="with --png, write every Nth frame")
    ap.add_argument("--dump", action="store_true",
                    help="print the transcript instead of diffing")
    args = ap.parse_args()

    ref = python_lines(args.movie)
    if args.dump:
        print("\n".join(ref))
        return

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, "movie_test")
        r = subprocess.run([str(exe), args.movie], capture_output=True,
                           text=True)
    if r.returncode:
        sys.stderr.write(r.stderr)
        sys.exit("movie_test failed")
    got = [x for x in r.stdout.splitlines() if x.strip()]

    differ = 0
    for i in range(max(len(got), len(ref))):
        a = got[i] if i < len(got) else "<missing>"
        b = ref[i] if i < len(ref) else "<missing>"
        if a != b:
            differ += 1
            if differ <= 20:
                print("line %d:\n  C      %s\n  python %s" % (i + 1, a, b))

    if args.png:
        dump_pngs(args.movie, args.png, max(1, args.every))

    print("%d lines, %d differ" % (max(len(got), len(ref)), differ))
    sys.exit(1 if differ else 0)


if __name__ == "__main__":
    main()
