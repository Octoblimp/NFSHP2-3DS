#!/usr/bin/env python3
r"""Cross-check 3DS Files/source/mv3.c (the MV3 decoder) and avimovie.c (the AVI streamer) against the retail image's own decoder, run
in mipsemu.

The model is the image: each piece of DCTImage, Huffman and MV3Codec runs
as shipped, called at its retail address, and prints what it made. The
harness (tools/src/mv3_test.c) runs mv3.c on the same inputs and prints the
same lines.

Scenarios cover:
- BuildDecodeTab's 512 entries;
- InitIDCTTables at every kind of quality pair: the IJG curve's both
  halves, 50 and 49, 1 and 100 and past them, and bytes whose sign bit is
  set, since the codec reads each as an s8;
- GetBits at every width, 0 and 32 among them, across refills;
- Decompress over random streams, which reach every magnitude class, the
  escape's sign both ways and both zero-run lengths, with counts from 0 to
  4000 and the zeros a run writes past the count;
- IDCT (the path retail's mode word 2 selects), IDCT1, IDCT4, IDCTZero and
  IDCTImageData's scan, on random blocks at real dequant tables: sparse
  and dense, a lone DC, a lone column or row, and DCs that clamp at both
  ends;
- IDCTAdd, IDCTAdd1, IDCTAdd4 and IDCTAddImageData, the same blocks added
  to what is there: zeros, 0xff and noise, so the sums clamp both ways;
- CopyPreviousFrameBlock at four sizes and six kinds of vector, from
  inside the frame to past the allocation's either end, with odd and
  negative vectors for chroma's rounding;
- ToImage32 on random planes at small sizes, both row orders, with every
  plane byte from 0 to 255 reached;
- whole frames of retail's movies through DecompressFrameShared, the boot
  movies' first, middle and last among them, compared as CRCs of the RGBA,
  the port's tiled texture read back into rows, and the port's count of
  IDCT outputs past the clamp table, which has to be 0;
- inter sequences decoded in order from a new codec, compared plane by
  plane as CRCs: four synthetic movies, which this file encodes with the
  image's own prefix code and scan (every kind of macroblock: coded, copied
  with a residual, copied without, and frames all of one kind, at four
  sizes and ten quality pairs, the layout word's either byte set), then two
  runs of MAINMENU_MOVIE, its first frames and a run across two keyframes.

The PS2 reads `Codec::OffsetClamp` without a bound. For the IDCT scenarios
the model fills 128 KB of memory below the table with 0 and 615 bytes
above it with 255, so an out-of-range value reads what the port saturates
to; the blocks are drawn so that no output reaches past those bytes (index
999, where IDCTImageData's timer store lands). The adds index the table at
the pixel plus the value, which the blocks keep inside the same bytes.
The copy reads the previous allocation from wherever the vector points;
the model surrounds it with 64 KB of zeros each side, what the port reads
past its own. Whole frames and sequences run with the image's memory
untouched: the encoder keeps every add inside the table and every vector
inside the allocation.

The AVI half has no retail code to run -- `avimovie.c` is the port's -- so
it is held to this file's own reading of RIFF: every retail movie's header
and chunk list, and the boot movies' pacing (which frames it decodes, which
it reads past, which audio chunks it hands on) over a schedule of clock
times. The menus' pacing, avimovie_step, is the image's: MoviePlayer::Update
runs as shipped, on a player whose ring buffer is the movie's chunks and
whose decoder only counts, and the port answers each call as it does --
over a synthetic inter movie called at 50 Hz and slower, the synthetic AVI
for its sound chunks, and MAINMENU_MOVIE to its end and past it, with a
stretch left out so it falls behind and catches up.

The sound has none either: the IOP fed it to the SPU. It is held to
audio_convert.py's SPU decoder, the one sndbank_check holds the sound banks
to, over this file's reading of the layout (a left block of 0x8000 bytes,
then a right, each channel's history running on across its blocks): two
boot movies' whole streams chunk by chunk as the player reads them, and
random streams -- every predictor and shift, clamps both ways, a partial
pair at the end -- pushed in sizes from a byte to three pairs and pulled in
sizes from none to a whole block. The rate is the image's: the immediate
MoviePlayer::Update stores, through SOUND_HzToSPU's arithmetic.

    python tools/mv3_check.py
    python tools/mv3_check.py --mutate [--only a,b]
    python tools/mv3_check.py --dump out/mv3
"""
import argparse
import array
import os
import random
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audio_convert
import hostbuild
import mipsdis
import physicscar_check as pcc
import retail_model

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/mv3_test.c"
MVC = "3DS Files/source/mv3.c"
MVH = "3DS Files/source/mv3.h"
AVC = "3DS Files/source/avimovie.c"
AVH = "3DS Files/source/avimovie.h"
# bsnd for its Hz/SPU round trip, and what bsnd.c links against.
SOURCES = [HARNESS, MVC, AVC, "3DS Files/source/bsnd.c",
           "3DS Files/source/sndbank.c", "3DS Files/source/bsndtab.c"]
MOVIES = "extracted-retail/MOVIES/INTRO"

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
CODEC_CTOR = 0x00231e10          # Codec::Codec
CLAMP_INIT = 0x00232128          # _GLOBAL_$I$_5Codec$Clamp
DCTIMAGE_CTOR = 0x002343d8
BUILD_DECODE = 0x002372a8
INIT_IDCT = 0x00234718
GETBITS = 0x00237228
INIT_DECOMP = 0x00237418
DECOMPRESS = 0x00237428
IDCT = 0x00232d60
IDCT1 = 0x00233950
IDCT4 = 0x002339a8
IDCT_DATA = 0x00234838
IDCT_ZERO = 0x00234a68
TO_IMAGE32 = 0x002363a8
MV3_CTOR = 0x00238e28
BEGIN = 0x00239050
FRAME = 0x00239148
# The inter path.
IDCT_ADD = 0x00233c20
IDCT_ADD1 = 0x00233fa0
IDCT_ADD4 = 0x00234090
IDCT_ADD_DATA = 0x00234aa0
SWAP_PREV = 0x00236638
# CopyPreviousFrameBlock. The map leaves it unplaced (the demo's is
# 0x002210e0), so it is held to ToImage's one call to it instead.
COPY_PREV = 0x00236950
COPY_PREV_CALL = 0x00235480
DCT = 40                         # MV3Codec's DCTImage

DECODE_TAB = 0x00334be8
CLAMP_TAB = 0x0031c6a0           # Clamp - 256: 768 bytes
IDCT_MODE = GP - 15420           # 2: the scalar IDCT
IDCT_TIMER = 0x0031cc08          # IDCTImageData's bGetTicker store

MV3CODEC_SIZE = 652              # the demo's 648 and one more int
CONVERT_TO_RGBA = 648

# The movie's sound: MoviePlayer::Update, where it stores the stream's rate,
# and SOUND_HzToSPU, which every rate goes through to the SPU.
MOVIE_UPDATE = 0x002380a8
MOVIE_RATE_AT = 0x002381b0
HZ_TO_SPU = 0x0026d258
HZ_TO_SPU_BODY = ["sll v0,v1,12", "ori v1,zero,0xbb80", "divu v0,v1"]

# What Update calls on a silent movie. The ring buffer and the decoder are
# stubbed; fptoui runs.
READ_DATA = 0x002395d8           # RingBuffer::ReadData
VIDEO_MODE = 0x001a3390          # GetVideoMode: 0 is PAL, 50 vblanks a second
GET_FRAME = 0x00239a58           # RingBuffer::GetFrame
RELEASE_FRAME = 0x00239b48       # RingBuffer::ReleaseFrame
DECOMPRESS_EX = 0x00239118       # MV3Codec::DecompressFrameEx
FILE_NAME = 0x002545e8           # bFileGetFilename: the 20 s stall's report
VBLANKS = GP - 25252             # eVBlankCounter
MOVIE_PLAYER_SIZE = 1092

# The ones the map pairs, and the demo's twins.
DEMO_CODE = {
    CODEC_CTOR: 0x0021c9c8, CLAMP_INIT: 0x0021cce0,
    DCTIMAGE_CTOR: 0x0021ef90, BUILD_DECODE: 0x002217a8,
    INIT_IDCT: 0x0021f2b8, GETBITS: 0x00221728, INIT_DECOMP: 0x00221918,
    DECOMPRESS: 0x00221928, IDCT: 0x0021d918, IDCT1: 0x0021e508,
    IDCT4: 0x0021e560, IDCT_DATA: 0x0021f3d8, IDCT_ZERO: 0x0021f608,
    TO_IMAGE32: 0x00220ac0, MV3_CTOR: 0x002231a8, BEGIN: 0x002233d0,
    FRAME: 0x002234c8, MOVIE_UPDATE: 0x002224f8, HZ_TO_SPU: 0x002528b8,
    IDCT_ADD: 0x0021e7d8, IDCT_ADD1: 0x0021eb58, IDCT_ADD4: 0x0021ec48,
    IDCT_ADD_DATA: 0x0021f640, SWAP_PREV: 0x00220d50,
    READ_DATA: 0x00223950, VIDEO_MODE: 0x001992a0, GET_FRAME: 0x00223dc0,
    RELEASE_FRAME: 0x00223eb0, DECOMPRESS_EX: 0x00223498,
    FILE_NAME: 0x0023c3d0,
}

GUARD_BELOW = 0x20000
GUARD_ABOVE = IDCT_TIMER - (CLAMP_TAB + 768)      # up to index 999
INDEX_MAX = 383 + GUARD_ABOVE
# The IDCTAdds index Clamp, 128 below OffsetClamp, by the byte already
# there plus the output: the largest output the guard holds over 255.
ADD_INDEX_MAX = INDEX_MAX + 128 - 255

COPY_SIZES = [(16, 16), (64, 48), (48, 80), (256, 32)]


def check_map():
    rmap = retail_model.retail_map()
    bad = []
    for r, d in sorted(DEMO_CODE.items()):
        try:
            got = rmap.code(d)
        except retail_model.MipsError:
            got = None
        if got != r:
            bad.append("demo %08x maps to %s, not %08x"
                       % (d, "none" if got is None else "%08x" % got, r))
    elf = mipsdis.Elf(str(retail_model.RETAIL))
    w = struct.unpack("<I", elf.read(COPY_PREV_CALL, 4))[0]
    if w != 0x0c000000 | (COPY_PREV >> 2):
        bad.append("ToImage's %08x is %s, not jal %08x" % (
            COPY_PREV_CALL, mipsdis.decode(w, COPY_PREV_CALL, elf)[0], COPY_PREV))
    return bad


def u32(v):
    return v & 0xffffffff


def alloc_layout(w, h):
    """Init's allocation: Y, U and V each in `area` bytes, the Y plane's
    size rounded up to 128, then a vector's four bytes per macroblock."""
    area = (w * h + 127) & ~127
    return area, 3 * area + (w // 16) * (h // 16) * 4


def lcg_bytes(n, seed):
    """The harness's lcg_fill: a 32-bit LCG's bits 16..23."""
    out = bytearray(n)
    s = seed & 0xffffffff
    for i in range(n):
        s = (s * 1103515245 + 12345) & 0xffffffff
        out[i] = (s >> 16) & 255
    return bytes(out)


def tdiv2(v):
    """C's v / 2, toward zero."""
    return -((-v) // 2) if v < 0 else v // 2


def copy_reads(w, h, x, y, dx, dy):
    """The offsets into the previous allocation that CopyPreviousFrameBlock
    reads for macroblock (x, y) at vector (dx, dy), row by row: 16 of 16
    luma bytes, then 8 of 8 in U and in V."""
    area, _ = alloc_layout(w, h)
    cw = w // 2
    sx, sy = x + dx, y + dy
    c = tdiv2(sy) * cw + tdiv2(sx)
    rows = [(sy * w + sx + r * w, 16) for r in range(16)]
    rows += [(area + c + r * cw, 8) for r in range(8)]
    rows += [(2 * area + c + r * cw, 8) for r in range(8)]
    return rows


def copy_misses(w, h, x, y, dx, dy):
    """How many of those bytes fall outside the allocation."""
    _, size = alloc_layout(w, h)
    return sum(1 for off, n in copy_reads(w, h, x, y, dx, dy)
               for i in range(off, off + n) if not 0 <= i < size)


COPY_GUARD = 0x10000


class Model(object):
    """Retail's decoder pieces, one emulator for the unit scenarios."""

    def __init__(self):
        e = self.e = retail_model.RetailEmu()
        e.stub_bware()
        if e.u32(IDCT_MODE) != 2:
            raise SystemExit("retail's IDCT mode word is %d, not 2"
                             % e.u32(IDCT_MODE))
        e.call(CLAMP_INIT)
        self.codec = e.alloc(64)
        e.call(CODEC_CTOR, self.codec)
        self.dct = e.alloc(640)
        e.call(DCTIMAGE_CTOR, self.dct)
        self.huff = e.alloc(64)
        e.call(BUILD_DECODE, self.huff)
        # The encoder's prefix code and scan, out of the image, before the
        # guard covers the scan.
        self.prefix = struct.unpack("<12I", e.read(PREFIX_TAB, 48))
        self.scan = list(struct.unpack("<64i", e.read(SCAN, 256)))
        # The guard: after the constructors, which read the scan that sits
        # right after the table.
        e.write(CLAMP_TAB - GUARD_BELOW, bytes(GUARD_BELOW))
        e.write(CLAMP_TAB + 768, b"\xff" * GUARD_ABOVE)
        self.buf = e.alloc(1 << 17)
        self.out = e.alloc((4096 + 80) * 2)
        self.qbuf = e.alloc(128)
        self.cbuf = e.alloc(128)
        self.dst = e.alloc(1 << 16)
        self.img = e.alloc(640)
        self.planes = e.alloc(3 << 14)
        self.copy_cap = 0

    def table(self):
        t = self.e.read(DECODE_TAB, 1024)
        return ["table %d %s" % (i, t[i * 128:(i + 1) * 128].hex())
                for i in range(8)]

    def quant(self, q, d):
        e = self.e
        e.call(INIT_IDCT, self.dct, q, d)
        out = []
        for t in range(4):
            v = struct.unpack("<64h", e.read(self.dct + 92 + 128 * t, 128))
            out.append("quant %d %d %d %s" % (q, d, t, " ".join(map(str, v))))
        return out

    def _load(self, data):
        self.e.write(self.buf, data + bytes(4096))
        self.e.call(INIT_DECOMP, self.huff, self.buf)

    def _state(self):
        e = self.e
        return "| %08x %d %d" % (e.u32(self.huff), e.u32(self.huff + 4),
                                 u32(e.u32(self.huff + 20) - self.buf))

    def bits(self, data, ns):
        self._load(data)
        vals = ["%08x" % u32(self.e.call(GETBITS, self.huff, n)) for n in ns]
        return ["bits %s %s" % (" ".join(vals), self._state())]

    def decomp(self, data, count):
        e = self.e
        self._load(data)
        e.write(self.out, b"\x55\x55" * (count + 72))
        e.call(DECOMPRESS, self.huff, self.out, count)
        v = struct.unpack("<%dh" % (count + 72), e.read(self.out, 2 * (count + 72)))
        return ["huff %d %s %s" % (count, " ".join(map(str, v)), self._state())]

    def idct(self, kind, q, c):
        e = self.e
        e.write(self.qbuf, struct.pack("<64h", *q))
        e.write(self.cbuf, struct.pack("<64h", *c))
        e.write(self.dst, b"\x5a" * 128)
        if kind == 0:
            e.call(IDCT_ZERO, self.dct, self.dst, 16)
        elif kind == 1:
            e.call(IDCT1, self.dct, self.cbuf, self.qbuf, self.dst, 16)
        elif kind == 2:
            e.call(IDCT4, self.dct, self.cbuf, self.qbuf, self.dst, 16)
        elif kind == 3:
            e.call(IDCT, self.dct, self.cbuf, self.qbuf, self.dst, 16)
        else:
            e.call(IDCT_DATA, self.dct, self.dst, 16, self.cbuf, self.qbuf)
        return ["idct %d %s" % (kind, e.read(self.dst, 128).hex())]

    def idctadd(self, kind, dst, q, c):
        e = self.e
        e.write(self.qbuf, struct.pack("<64h", *q))
        e.write(self.cbuf, struct.pack("<64h", *c))
        e.write(self.dst, dst)
        if kind == 1:
            e.call(IDCT_ADD1, self.dct, self.cbuf, self.qbuf, self.dst, 16)
        elif kind == 2:
            e.call(IDCT_ADD4, self.dct, self.cbuf, self.qbuf, self.dst, 16)
        elif kind == 3:
            e.call(IDCT_ADD, self.dct, self.cbuf, self.qbuf, self.dst, 16)
        else:
            e.call(IDCT_ADD_DATA, self.dct, self.dst, 16, self.cbuf, self.qbuf)
        return ["idctadd %d %s" % (kind, e.read(self.dst, 128).hex())]

    def copy(self, w, h, seed, x, y, dx, dy):
        """CopyPreviousFrameBlock on two allocations laid out as Init lays
        them, the previous one inside COPY_GUARD bytes of zeros each side:
        what the port reads outside its allocation."""
        e = self.e
        area, size = alloc_layout(w, h)
        cw = w // 2
        for off, n in copy_reads(w, h, x, y, dx, dy):
            if off < -COPY_GUARD or off + n > size + COPY_GUARD:
                raise SystemExit("copy %d %d %d %d %d %d reads past the guard"
                                 % (w, h, x, y, dx, dy))
        if size > self.copy_cap:
            self.copy_cap = size
            self.copy_prev = e.alloc(size + 2 * COPY_GUARD) + COPY_GUARD
            self.copy_cur = e.alloc(size)
            self.copy_img = e.alloc(640)
        prev, cur, img = self.copy_prev, self.copy_cur, self.copy_img
        e.write(prev - COPY_GUARD, bytes(COPY_GUARD) + lcg_bytes(size, seed)
                + bytes(COPY_GUARD))
        e.write(cur, lcg_bytes(size, seed + 1))
        e.write(cur + 3 * area, struct.pack("<2h", dx, dy))
        for off, v in ((4, cur), (8, cur + area), (12, cur + 2 * area),
                       (28, cur + 3 * area), (44, prev), (48, prev + area),
                       (52, prev + 2 * area), (68, w), (72, h)):
            e.put32(img + off, v)
        py = cur + y * w + x
        pu = cur + area + (y // 2) * cw + x // 2
        pv = pu + area
        e.call(COPY_PREV, img, x, y, py, pu, pv, 0)
        out = "".join(e.read(py + r * w, 16).hex() for r in range(16))
        out += " " + "".join(e.read(pu + r * cw, 8).hex() for r in range(8))
        out += " " + "".join(e.read(pv + r * cw, 8).hex() for r in range(8))
        return ["copy %s misses %d" % (out, copy_misses(w, h, x, y, dx, dy))]

    def yuv(self, w, h, flip, y, u, v):
        e = self.e
        yp, up, vp = self.planes, self.planes + (1 << 14), self.planes + (2 << 14)
        e.write(yp, y)
        e.write(up, u)
        e.write(vp, v)
        e.put32(self.img + 4, yp)
        e.put32(self.img + 8, up)
        e.put32(self.img + 12, vp)
        e.put32(self.img + 68, w)
        e.put32(self.img + 72, h)
        e.call(TO_IMAGE32, self.img, self.dst, flip)
        rgba = e.read(self.dst, w * h * 4)
        out = ["yuv %d %d %d %s" % (w, h, flip, rgba.hex())]
        if flip:
            out.append("tiled %d %d %s" % (w, h, rgba.hex()))
        return out


_FRAME_EMU = None


def frame_emu():
    """The emulator every FrameModel shares; each model's objects are new
    allocations, which the bump heap hands out zeroed, so a codec starts as
    it would on a fresh image. BeginDecompress calls BuildDecodeTable, 12.7
    million instructions (15 s) that write only the 1024 bytes at
    DECODE_TAB, the same bytes every time (the table scenario checks them):
    built once here, a later call only checks they are still there."""
    global _FRAME_EMU
    if _FRAME_EMU is None:
        e = _FRAME_EMU = retail_model.RetailEmu()
        e.stub_bware()
        e.call(CLAMP_INIT)
        e.call(BUILD_DECODE, 0)
        built = e.read(DECODE_TAB, 1024)

        def rebuild(e_):
            if e_.read(DECODE_TAB, 1024) != built:
                raise SystemExit("the decode table changed after it was built")
        e.stub(BUILD_DECODE, rebuild)
    return _FRAME_EMU


class FrameModel(object):
    """DecompressFrameShared on a new codec, as the game calls it."""

    def __init__(self, w, h, convert=True):
        e = self.e = frame_emu()
        self.w, self.h = w, h
        self.in_hdr = e.alloc(64)
        self.out_hdr = e.alloc(64)
        self._bih(self.in_hdr, w, h, 24, b"MV30")
        # a negative biHeight is what asks ToImage32 for top-down rows
        self._bih(self.out_hdr, w, -h, 32, b"\0\0\0\0")
        self.obj = e.alloc(MV3CODEC_SIZE + 64)
        e.call(MV3_CTOR, self.obj)
        if e.call(BEGIN, self.obj, self.in_hdr, self.out_hdr) != 0:
            raise SystemExit("BeginDecompress rejected %dx%d" % (w, h))
        # Without the conversion ToImage only decodes, which a sequence
        # compared plane by plane does not need; it costs most of a frame.
        e.put32(self.obj + CONVERT_TO_RGBA, 1 if convert else 0)
        self.dst = e.alloc(w * h * 4)
        self.src, self.cap = 0, 0

    def planes(self):
        """The frame just decoded: ToImage ends with SwapPrevBuffer, so it
        is pPrevY, pPrevU and pPrevV now (DCTImage +44, +48, +52)."""
        e, n = self.e, self.w * self.h
        d = self.obj + DCT
        return (e.read(e.u32(d + 44), n), e.read(e.u32(d + 48), n // 4),
                e.read(e.u32(d + 52), n // 4))

    def _bih(self, addr, w, h, bits, comp):
        self.e.write(addr, struct.pack("<I2i2H4sI2i2I", 40, w, h, 1, bits,
                                       comp, abs(w * h) * bits // 8, 0, 0, 0, 0))

    def decode(self, data):
        e = self.e
        if len(data) + 256 > self.cap:
            self.cap = max(len(data) + 256, 1 << 17)
            self.src = e.alloc(self.cap)
        e.write(self.src, data + bytes(256))
        e.call(FRAME, self.obj, 0, self.in_hdr, self.src, self.out_hdr, self.dst)
        return e.read(self.dst, self.w * self.h * 4)


# ================================================================ the AVIs


def rd32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def tagstr(t):
    return "".join(chr(c) if 32 < c < 127 else "." for c in t)


class Avi(object):
    """RIFF read this file's own way: the header fields the player keeps,
    and movi's chunks in order."""

    def __init__(self, path):
        self.path = path
        f = self.f = open(path, "rb")
        h = f.read(12)
        if h[:4] != b"RIFF" or h[8:12] != b"AVI ":
            raise SystemExit("%s is not an AVI" % path)
        end = 8 + rd32(h, 4)
        self.vs = self.as_ = -1
        self.scale = self.rate = self.frames = 0
        self.w = self.h = self.bh = 0
        self.codec = b"\0\0\0\0"
        self.afmt = self.ach = self.abits = self.arate = 0
        self.movi = None
        off = 12
        while off + 12 <= end:
            f.seek(off)
            h = f.read(12)
            tag, size, kind = h[:4], rd32(h, 4), h[8:12]
            if tag == b"LIST" and kind == b"hdrl":
                self._hdrl(off + 12, off + 8 + size)
            elif tag == b"LIST" and kind == b"movi":
                self.movi = (off + 12, off + 8 + size)
                break
            off += 8 + size + (size & 1)

    def _hdrl(self, off, end):
        n = 0
        while off + 12 <= end:
            self.f.seek(off)
            h = self.f.read(12)
            size = rd32(h, 4)
            if h[:4] == b"LIST" and h[8:12] == b"strl":
                self._strl(off + 12, off + 8 + size, n)
                n += 1
            off += 8 + size + (size & 1)

    def _strl(self, off, end, n):
        typ = None
        while off + 8 <= end:
            self.f.seek(off)
            h = self.f.read(8)
            tag, size = h[:4], rd32(h, 4)
            body = self.f.read(size)
            if tag == b"strh" and size >= 36:
                typ = body[:4]
                if typ == b"vids" and self.vs < 0:
                    self.vs = n
                    self.scale, self.rate = rd32(body, 20), rd32(body, 24)
                    self.frames = rd32(body, 32)
                elif typ == b"auds" and self.as_ < 0:
                    self.as_ = n
            elif tag == b"strf":
                if typ == b"vids" and self.vs == n and size >= 20:
                    self.w = rd32(body, 4)
                    self.bh = struct.unpack_from("<i", body, 8)[0]
                    self.h = abs(self.bh)
                    self.codec = body[16:20]
                elif typ == b"auds" and self.as_ == n and size >= 16:
                    self.afmt, self.ach, self.arate = struct.unpack_from(
                        "<HHI", body, 0)
                    self.abits = struct.unpack_from("<H", body, 14)[0]
            off += 8 + size + (size & 1)

    def chunks(self):
        """(tag, stream, payload offset, size), in movi's order."""
        pos, end = self.movi
        out = []
        while pos + 8 <= end:
            self.f.seek(pos)
            h = self.f.read(8)
            tag, size = h[:4], rd32(h, 4)
            if tag == b"LIST":
                pos += 12
                continue
            if size > end - (pos + 8):
                break
            item = (tag, pos + 8, size)
            pos += 8 + size + (size & 1)
            if tag == b"JUNK":
                continue
            out.append(item)
        self.end = pos
        return [(t, stream_of(t), o, s) for t, o, s in out]

    def header_line(self):
        return "avi %d %d %d %s %d %d %d | %d %d %d %d | %d %d %d %d" % (
            self.w, self.h, self.bh, tagstr(self.codec), self.scale,
            self.rate, self.frames, self.afmt, self.ach, self.abits,
            self.arate, self.vs, self.as_, self.movi[0], self.movi[1])

    def read(self, off, n):
        self.f.seek(off)
        return self.f.read(n)


def stream_of(tag):
    if not (48 <= tag[0] <= 57 and 48 <= tag[1] <= 57):
        return -1
    return (tag[0] - 48) * 10 + (tag[1] - 48)


def avi_lines(avi):
    ch = avi.chunks()
    out = [avi.header_line()]
    out += ["c %s %d %d %d" % (tagstr(t), s, o, n) for t, s, o, n in ch]
    out.append("avi end %d" % avi.end)
    return out


def frame_at(avi, t):
    if t <= 0.0:
        return 0
    f = t * float(avi.rate) / float(avi.scale)
    return 0xffffffff if f >= 4294967295.0 else int(f)


def pace_lines(avi, times):
    """avimovie_advance, as this file reads its contract."""
    ch = avi.chunks()
    out = ["pace %.6f" % (avi.frames * float(avi.scale) / float(avi.rate))]
    i = 0
    nxt, shown, decoded, skipped, ended = 0, -1, 0, 0, 0
    for ts in times:
        t = float(ts)
        target = frame_at(avi, t)
        if avi.frames and target >= avi.frames:
            target = avi.frames - 1
        changed = 0
        while not ended and (shown < 0 or shown < target):
            if i == len(ch):
                ended = 1
                break
            tag, s, off, n = ch[i]
            i += 1
            if s == avi.as_:
                out.append("a %d %d" % (off, n))
                continue
            if s != avi.vs:
                continue
            if nxt < target:
                nxt += 1
                skipped += 1
                continue
            shown = nxt
            nxt += 1
            decoded += 1
            changed = 1
        done = 1 if ended or (avi.frames and shown >= 0
                              and shown + 1 >= avi.frames) else 0
        out.append("t %s %d %d %d %d %d %d %d 0 %d" % (
            ts, frame_at(avi, t), changed, shown, decoded, skipped, nxt,
            ended, done))
    return out


def f32(v):
    return struct.unpack("<f", struct.pack("<f", v))[0]


def step_lines(model, avi, ds):
    """MoviePlayer::Update, retail's, on a player InitFile has just opened
    `avi` in, called at each of `ds`: vblanks since the first call, on a
    PAL TV. The ring buffer is `avi`'s chunks, GetFrame reading on to the
    next video one, and the decoder only counts; the clock, the test and
    the end run as shipped. The sound chunks GetFrame passes are listed
    where the port hands them on -- retail's ring buffer sends its sound
    elsewhere, and the menus' movies have none."""
    e = model.e
    ch = avi.chunks()
    p = e.alloc(MOVIE_PLAYER_SIZE)
    frame = e.alloc(64)
    eof = e.alloc(16)
    # What InitFile leaves: +8 the rate over the scale, as a double made
    # single, and +4 one over it; +24, the next Update is the first; +28
    # the file; the stream read to its end and the buffer empty (+108 and
    # +64, +68), so GetFrame's 0 is the end; +272 the strh's length.
    fps = f32(float(avi.rate) / float(avi.scale))
    e.write(p + 4, struct.pack("<2f", f32(1.0 / fps), fps))
    e.put32(p + 24, 1)
    e.put32(p + 28, 1)
    e.put32(p + 108, eof)
    e.put32(p + 272, avi.frames)
    st = {"i": 0, "decoded": 0}
    out = []

    def get_frame(_e):
        while st["i"] < len(ch) and ch[st["i"]][1] != avi.vs:
            _, s, off, n = ch[st["i"]]
            if s == avi.as_:
                out.append("a %d %d" % (off, n))
            st["i"] += 1
        if st["i"] == len(ch):
            return 0
        e.put32(frame + 16, ch[st["i"]][3])
        e.put32(frame + 32, 1)
        return frame

    def release(_e):
        st["i"] += 1

    def decompress(_e):
        st["decoded"] += 1

    def stall(_e):
        raise SystemExit("Update reported a stall")

    stubs = ((READ_DATA, lambda _e: None), (VIDEO_MODE, lambda _e: 0),
             (GET_FRAME, get_frame), (RELEASE_FRAME, release),
             (DECOMPRESS_EX, decompress), (FILE_NAME, stall))
    for a, fn in stubs:
        e.stub(a, fn)
    try:
        for d in ds:
            e.put32(VBLANKS, STEP_V0 + d)
            before = st["decoded"]
            r = e.call(MOVIE_UPDATE, p, 1, limit=100000)
            n = e.u32(p + 12)
            out.append("s %d %d %d %d %d" % (
                d, r, int(st["decoded"] != before),
                n - 1 if e.u32(p + 1088) else -1, n))
    finally:
        for a, _ in stubs:
            e.stubs.pop(a, None)
    return out


# ================================================================ the sound

BLOCK = 0x8000
PAIR = 2 * BLOCK
BLOCK_FRAMES = BLOCK // 16
WANT_MAX = BLOCK_FRAMES          # the harness asks for at most a block


def asm(w, a):
    return " ".join(mipsdis.decode(w, a)[0].split())


def rate_lines(model):
    """The rate as the image has it: Update's immediate, and HzToSPU's
    (hz << 12) / 48000, with the SPU's own way back."""
    e = model.e
    ins = asm(e.u32(MOVIE_RATE_AT), MOVIE_RATE_AT)
    if not ins.startswith("ori v0,zero,0x"):
        raise SystemExit("%08x is %s, not the rate's ori" % (MOVIE_RATE_AT, ins))
    body = [asm(e.u32(HZ_TO_SPU + 0x18 + 4 * i), HZ_TO_SPU + 0x18 + 4 * i)
            for i in range(3)]
    if body != HZ_TO_SPU_BODY:
        raise SystemExit("SOUND_HzToSPU at %08x is %s" % (HZ_TO_SPU, body))
    hz = int(ins.split(",")[-1], 16)
    spu = (hz << 12) // 48000
    return ["rate %d %d %d" % (hz, spu, (spu * 48000) >> 12)]


def sound_lines(pushes, pulls):
    """avisound, as this file reads the stream: whole pairs only, and each
    channel's blocks one SPU stream for audio_convert to decode."""
    blob = b"".join(pushes)
    pairs = len(blob) // PAIR
    left = b"".join(blob[i * PAIR:i * PAIR + BLOCK] for i in range(pairs))
    right = b"".join(blob[i * PAIR + BLOCK:(i + 1) * PAIR] for i in range(pairs))
    lpcm = audio_convert.decode_adpcm(left)[0]
    rpcm = audio_convert.decode_adpcm(right)[0]
    if len(lpcm) != len(rpcm) or len(lpcm) != pairs * BLOCK_FRAMES * 28:
        raise SystemExit("a sound stream with an end flag in it")
    pcm = array.array("h", bytes(4 * len(lpcm)))
    pcm[0::2] = lpcm
    pcm[1::2] = rpcm
    if sys.byteorder != "little":
        pcm.byteswap()
    out = []
    pushed = frames = k = 0
    for c in pushes:
        pushed += len(c)
        got = 0
        held = pushed - (frames // BLOCK_FRAMES) * PAIR
        before = (held // PAIR) * BLOCK_FRAMES - frames % BLOCK_FRAMES             if held >= PAIR else 0
        while True:
            held = pushed - (frames // BLOCK_FRAMES) * PAIR
            ready = (held // PAIR) * BLOCK_FRAMES - frames % BLOCK_FRAMES \
                if held >= PAIR else 0
            if not ready:
                break
            want = min(pulls[k % len(pulls)], WANT_MAX)
            k += 1
            n = min(want, ready)
            frames += n
            got += n * 28
        held = pushed - (frames // BLOCK_FRAMES) * PAIR
        out.append("s %d %d %d %d %d" % (pushed, before, held,
                                          frames % BLOCK_FRAMES, got))
    crc = zlib.crc32(pcm[:2 * 28 * frames].tobytes()) & 0xffffffff
    held = pushed - (frames // BLOCK_FRAMES) * PAIR
    out.append("snd end %d %d %d %d %08x" % (pushed, held, frames % BLOCK_FRAMES,
                                              28 * frames, crc))
    return out


def movie_pushes(avi):
    """The sound chunks the player hands on reading to the last frame: all
    of them up to the last video chunk, and none after."""
    out, vids = [], 0
    for tag, s, off, n in avi.chunks():
        if s == avi.as_:
            out.append(avi.read(off, n))
        elif s == avi.vs:
            vids += 1
            if avi.frames and vids >= avi.frames:
                break
    return out


def synth_sound(rng, pairs, extra):
    """A random stream: every predictor (5 and up are the SPU's 0) and
    every shift, a run of loud frames at shift 0 that clamps, and no flags."""
    out = bytearray()
    for i in range((pairs * PAIR + extra + 15) // 16):
        head = rng.randrange(256)
        if i % 7 == 3:
            head = (head & 0x70) | rng.choice([0, 0, 1])
        fr = bytes([head, 0]) + bytes(rng.randrange(256) for _ in range(14))
        if i % 11 == 5:
            fr = bytes([0x40 | rng.randrange(2), 0]) + bytes([0x77] * 14)
        if i % 13 == 6:
            fr = bytes([0x30, 0]) + bytes([0x88] * 14)
        out += fr
    return bytes(out[:pairs * PAIR + extra])


PUSH_SIZES = [1, 7, 16, 1820, 1821, 65535, 65536, 65537, 3, 191145, 15, 17]
PULL_SIZES = [1, 7, 256, 2048, 3000, 0, 2047, 5, 28, 1024]


def sound_scenarios(rng, tmpdir):
    """(command, model lines) for the random streams."""
    out = []
    specs = [(3, 1000, PUSH_SIZES, PULL_SIZES), (2, 0, [2 * PAIR], [2048]),
             (1, PAIR - 1, [PAIR - 1, 1, PAIR], [256]),
             (0, 5000, [700], [1, 2048]), (0, 0, [1], [1]),
             (4, 16, [PAIR * 4 + 16], [2048, 1])]
    for i, (pairs, extra, pushes, pulls) in enumerate(specs):
        data = synth_sound(rng, pairs, extra)
        p = Path(tmpdir) / ("snd%d.raw" % i)
        p.write_bytes(data)
        chunks, at, k = [], 0, 0
        while at < len(data):
            n = min(pushes[k % len(pushes)], len(data) - at)
            chunks.append(data[at:at + n])
            at += n
            k += 1
        out.append(("snd %s %s / %s" % (p, " ".join(map(str, pushes)),
                                        " ".join(map(str, pulls))),
                    sound_lines(chunks, pulls)))
    return out


# Whole movies, as the player pulls (a wave at a time) and at odd sizes.
MOVIE_SOUNDS = [("EALOGO_EN", [256]), ("BBGLOGO_EN", [1, 300, 2048, 17])]


# ================================================================ the scenarios

# 59 is the one quality whose prescale lands on a rounding tie (luma entry
# 61: 64 * 3552 is 2048 past a multiple of 4096), so it is here both as a
# quality and as quality + delta. Deltas from 128 up are how a frame's s8
# byte arrives, unsigned.
QUANT_PAIRS = [
    (93, -4), (90, -4), (50, 0), (49, 1), (50, -1), (1, 0), (100, 0),
    (101, 0), (0, 0), (-1, 0), (127, 127), (-128, -128), (200, 0),
    (100, 27), (1, -5), (25, 25), (75, -30), (99, 1), (2, 0), (10, 90),
    (255, 4), (60, -60), (33, 0), (66, 0), (59, 0), (60, -1),
    (93, 252), (50, 200), (10, 128), (70, 255),
]


def scenario_lines(rng):
    """The unit scenarios, as commands."""
    cmds = ["table"]
    for q, d in QUANT_PAIRS:
        cmds.append("quant %d %d" % (q, d))
    for q in range(1, 101, 7):
        cmds.append("quant %d %d" % (q, rng.randint(-20, 20)))

    # GetBits: every width, the refill's edges.
    for k in range(40):
        data = bytes(rng.randrange(256) for _ in range(64))
        ns = [rng.choice(range(0, 26)) for _ in range(rng.randint(1, 30))]
        if k < 4:
            ns = [[0, 32, 1, 31][k]] + ns
        cmds.append("bits %s %s" % (data.hex(), " ".join(map(str, ns))))
    cmds.append("bits %s %s" % (bytes(range(64)).hex(),
                                " ".join(str(n) for n in range(26))))

    # Decompress: random streams, biased toward each kind of symbol.
    for k in range(60):
        count = [0, 1, 2, 7, 64, 384, 1000, 4000][k] if k < 8 \
            else rng.randint(1, 1500)
        bias = k % 4
        data = bytearray()
        for _ in range(count * 3 + 64):
            b = rng.randrange(256)
            if bias == 1:
                b |= 0xf0                # the long prefixes and the escape
            elif bias == 2:
                b &= 0x3f                # zero runs and small classes
            data.append(b)
        cmds.append("huff %s %d" % (bytes(data).hex(), count))

    # The IDCTs, at real tables, each block bounded inside the guard.
    for k in range(400):
        kind = [3, 4, 2, 1, 0][k % 5] if k < 350 else 3
        while True:
            q = QTABLES[rng.choice(sorted(QTABLES))]
            c = block(rng, kind, k)
            if bound(q, c) < INDEX_MAX - 128:
                break
        cmds.append("idct %d %s %s" % (kind, " ".join(map(str, q)),
                                       " ".join(map(str, c))))

    # The IDCTAdds, onto blocks of black, of white and of noise.
    for k in range(240):
        kind = [3, 4, 2, 1][k % 4]
        while True:
            q = QTABLES[rng.choice(sorted(QTABLES))]
            c = block(rng, kind, k)
            if bound(q, c) < ADD_INDEX_MAX - 128:
                break
        fill = k % 6
        dst = bytes(128) if fill == 0 else b"\xff" * 128 if fill == 1 else \
            bytes(rng.randrange(256) for _ in range(128))
        cmds.append("idctadd %d %s %s %s" % (kind, dst.hex(), " ".join(map(str, q)),
                                             " ".join(map(str, c))))

    # CopyPreviousFrameBlock: at corners, edges and inside; no vector, odd
    # ones both ways (chroma halves toward zero), far ones into the next
    # rows and into U, V and the vectors, and some out of the allocation at
    # either end, which the port reads as 0.
    for k in range(48):
        w, h = COPY_SIZES[k % len(COPY_SIZES)]
        x = rng.choice([0, w - 16, rng.randrange(w // 16) * 16])
        y = rng.choice([0, h - 16, rng.randrange(h // 16) * 16])
        r = k % 6
        if r == 0:
            dx, dy = 0, 0
        elif r == 1:
            dx, dy = rng.choice([-3, -1, 1, 3]), rng.choice([-5, -1, 1, 5])
        elif r == 2:
            dx, dy = rng.randint(-w, w), rng.randint(-h, h)
        elif r == 3:
            dx, dy = rng.randint(-2 * w, 2 * w), rng.randint(0, 3 * h)
        elif r == 4:
            dx, dy = rng.randint(-20, 20), rng.randint(-40, -17) - y
        else:
            dx, dy = rng.randint(-20, 20), rng.randint(3 * h, 3 * h + 40) - y
        cmds.append("copy %d %d %d %d %d %d %d" % (
            w, h, rng.randrange(1 << 32), x, y, dx, dy))

    # ToImage32.
    for k in range(24):
        w, h = rng.choice([(2, 2), (4, 2), (8, 4), (16, 8), (6, 10), (32, 16),
                           (2, 16), (24, 6)])
        flip = k & 1
        y = bytes(rng.randrange(256) for _ in range(w * h))
        u = bytes(rng.randrange(256) for _ in range(w * h // 4))
        v = bytes(rng.randrange(256) for _ in range(w * h // 4))
        if k < 2:
            y = bytes([0, 255] * (w * h // 2))
            u = bytes([0] * (w * h // 4))
            v = bytes([255] * (w * h // 4))
        cmds.append("yuv %d %d %d %s %s %s" % (w, h, flip, y.hex(), u.hex(),
                                                v.hex()))
    return cmds


# The dequant tables the IDCT scenarios draw from, as retail builds them.
QTABLES = {}


def fill_qtables(model):
    for q in [93, 90, 70, 100, 50, 20]:
        lines = model.quant(q, -4)
        for t, ln in enumerate(lines):
            QTABLES[(q, t)] = [int(x) for x in ln.split()[4:]]


def bound(q, c):
    """Past the largest |index - 384| any output can reach. The AAN
    constants' gains through both passes multiply to under 10 for any one
    coefficient, so ten times the sum of |c q| over 32 bounds each pixel."""
    return (10 * sum(abs(q[i] * c[i]) for i in range(64)) + 64) >> 5


def block(rng, kind, k):
    """A block that stays inside the guard, of several shapes."""
    while True:
        c = [0] * 64
        shape = k % 7
        if shape == 0:                    # sparse
            for _ in range(rng.randint(1, 6)):
                c[rng.randrange(64)] = rng.randint(-40, 40)
        elif shape == 1:                  # dense and small
            c = [rng.randint(-3, 3) for _ in range(64)]
        elif shape == 2:                  # a lone DC, anywhere in range
            c[0] = rng.randint(-2000, 2000)
        elif shape == 3:                  # a column
            for r in range(8):
                c[r * 8] = rng.randint(-30, 30)
        elif shape == 4:                  # a row
            for i in range(8):
                c[i] = rng.randint(-30, 30)
        elif shape == 5:                  # the 2x2
            for i in (0, 1, 8, 9, 2, 3):
                c[i] = rng.randint(-60, 60)
        else:                             # DC past both ends
            c[0] = rng.choice([-1, 1]) * rng.randint(200, 3000)
            c[1] = rng.randint(-5, 5)
        if kind == 2:
            # IDCT4's four: the stream's first four, 0 1 / 2 3.
            c = [c[0], c[1], c[8], c[9]] + [0] * 60
        return c


# ============================================================ the encoder
#
# Retail's decoder takes about ten seconds a 256x384 frame in mipsemu, so
# most of the inter path is checked on small synthetic movies. This encoder
# writes the inter layout as DecompressFrameShared and ToImage read it:
# every kind of macroblock and block, DC predictors that run across copied
# macroblocks, rows with nothing coded, and vectors that leave their plane.
# No vector leaves the allocation, where the PS2 reads whatever memory is
# there, and no IDCT output leaves the clamp table: retail's own movies do
# neither, and the harness counts both.

PREFIX_TAB = 0x002bdc48          # 12 x length << 16 | code
SCAN = CLAMP_TAB + 768           # 0x0031c9a0, 64 ints


class BitWriter(object):
    """MSB first, as Huffman reads."""

    def __init__(self):
        self.parts = []

    def put(self, v, n):
        if n:
            self.parts.append(format(v & ((1 << n) - 1), "0%db" % n))

    def data(self):
        s = "".join(self.parts)
        s += "0" * (-len(s) % 8)
        return int(s, 2).to_bytes(len(s) // 8, "big") if s else b""


def put_values(bw, prefix, vals, overshoot=0):
    """Decompress's input for `vals`. A nonzero value is its class's prefix,
    a sign bit and the magnitude's bits under its implied top one; the
    escape classes read the same bits. A run of zeros is class 0's prefix, a
    flag and the length. A run that ends `vals` is written `overshoot`
    longer, as Decompress writes a run whole."""
    zl, zc = prefix[0] >> 16, prefix[0] & 0xffff
    i = 0
    while i < len(vals):
        v = vals[i]
        if v:
            a = abs(v)
            k = a.bit_length()
            if k > 11:
                raise SystemExit("the encoder has no class for %d" % v)
            bw.put(prefix[k] & 0xffff, prefix[k] >> 16)
            bw.put(1 if v < 0 else 0, 1)
            bw.put(a - (1 << (k - 1)), k - 1)
            i += 1
            continue
        j = i
        while j < len(vals) and not vals[j] and j - i < 72:
            j += 1
        run = j - i
        if j == len(vals):
            run = min(72, run + overshoot)
        bw.put(zc, zl)
        if run >= 9:
            bw.put(1, 1)
            bw.put(run - 9, 6)
        else:
            bw.put(0, 1)
            bw.put(run - 1, 3)
        i = j


def block_bound(t, q, c, scan):
    """bound() for a block of type t, its coefficients in the stream's
    order."""
    if t == 1:
        s = abs(c[0] * q[0])
    elif t == 2:
        s = sum(abs(c[i] * q[j]) for i, j in enumerate((0, 1, 8, 9)))
    else:
        s = sum(abs(q[i] * c[scan[i]]) for i in range(64))
    return (10 * s + 64) >> 5


def synth_block(rng, t, q, limit, scan):
    """Type t's coefficients, DC first, halved until no output can pass
    `limit`: so the big ones land just inside it, and clamp."""
    if t == 0:
        return []
    if t == 1:
        c = [rng.randint(-400, 400)]
    elif t == 2:
        c = [rng.randint(-400, 400)] + [rng.choice([0, rng.randint(-60, 60)])
                                        for _ in range(3)]
    else:
        c = [0] * 64
        if rng.random() < 0.2:
            c = [rng.randint(-2, 2) for _ in range(64)]
        else:
            for _ in range(rng.randint(0, 12)):
                c[rng.randrange(1, rng.choice([4, 12, 64]))] = rng.randint(-80, 80)
        c[0] = rng.randint(-400, 400)
    while block_bound(t, q, c, scan) >= limit:
        c = [int(v / 2) for v in c]
    return c


def synth_vector(rng, w, h, x, y):
    """A vector for macroblock (x, y) that reads inside the allocation:
    mostly near, some out of the plane sideways (into the next row), some
    into U, V and the vectors."""
    while True:
        r = rng.random()
        if r < 0.45:
            dx, dy = rng.randint(-6, 6), rng.randint(-6, 6)
        elif r < 0.75:
            dx, dy = rng.randint(-w, w), rng.randint(-h // 2, h // 2)
        else:
            dx, dy = rng.randint(-2 * w, 2 * w), rng.randint(-h, 3 * h)
        if copy_misses(w, h, x, y, dx, dy) == 0:
            return [dx, dy]


def synth_frame(rng, w, h, kind, q, d, layout, tables, prefix, scan):
    """One frame. `kind` is "I" for intra; for inter, "P" mixes every kind of
    macroblock, "S" copies them all with no residual, "C" copies them all
    with one, and "Q" codes them all."""
    mbw, mbh = w // 16, h // 16
    nmb = mbw * mbh
    intra = kind == "I"
    pick = {"I": ["intra"], "Q": ["intra"], "S": ["skip"], "C": ["copy"],
            "P": ["intra", "copy", "copy", "skip"]}[kind]
    modes = [rng.choice(pick) for _ in range(nmb)]
    transp = bytearray((nmb + 3) // 4)
    vects = []
    for i, mo in enumerate(modes):
        if mo != "intra":
            transp[i >> 2] |= 1 << (i & 3)
            vects += synth_vector(rng, w, h, (i % mbw) * 16, (i // mbw) * 16)
        # The no-residual bit only counts on a copied macroblock.
        if mo == "skip" or (mo == "intra" and rng.random() < 0.3):
            transp[i >> 2] |= 16 << (i & 3)
    types = []
    bw = BitWriter()
    if not intra:
        put_values(bw, prefix, vects)
    for row in range(mbh):
        vals, coded, pred = [], 0, [0, 0, 0]
        for mo in modes[row * mbw:(row + 1) * mbw]:
            if mo == "skip":
                continue
            coded += 1
            add = mo == "copy"
            for n in range(6):
                ch = 0 if n < 4 else n - 3
                qt = tables[(1 if add else 0) + (2 if n >= 4 else 0)]
                t = rng.choice([0, 1, 2, 3, 3])
                types.append(t)
                c = synth_block(rng, t, qt, 250 if add else 380, scan)
                if c:
                    # the stream holds the DC less its channel's predictor
                    c[0], pred[ch] = c[0] - pred[ch], c[0]
                vals += c
        bw.put(len(vals), 16)
        if not intra:
            bw.put(coded, 8)
        room = mbw * 384 - len(vals)
        put_values(bw, prefix, vals,
                   rng.choice([0, 0, 5, 40]) if room >= 72 else 0)
    tb = bytearray((len(types) + 3) // 4)
    for i, t in enumerate(types):
        tb[i >> 2] |= t << ((i & 3) * 2)
    hdr = bytes([q & 255, d & 255]) + struct.pack(">H", 0 if intra else layout)
    if intra:
        comp = struct.pack("<h", len(tb)) + tb
    else:
        comp = struct.pack("<hh", len(tb), len(vects) // 2) + transp + tb
    return hdr + comp + bw.data()


# (w, h, frames): each frame's kind, as synth_frame takes it.
SYNTH_SEQS = [
    (64, 48, "IPPPPPPIPP"),
    (16, 16, "IPSCQPPPP"),
    (128, 32, "IPPPPPSP"),
    (48, 80, "IPPCPPQP"),
]
SYNTH_QUALITY = [(90, -4), (93, -4), (50, 10), (20, 5), (100, -60), (70, -6),
                 (60, 0), (1, 99), (-5, 0), (127, -128)]
SYNTH_LAYOUTS = [0x0100, 0x0100, 0x0001, 0xffff, 0x8000]


def synth_seqs(model, rng, tmpdir):
    """The synthetic movies, each written as an AVI: (path, frames)."""
    out = []
    for k, (w, h, kinds) in enumerate(SYNTH_SEQS):
        frames = []
        for kind in kinds:
            q, d = rng.choice(SYNTH_QUALITY)
            tables = [[int(x) for x in ln.split()[4:]]
                      for ln in model.quant(q, d)]
            frames.append(synth_frame(rng, w, h, kind, q, d,
                                      rng.choice(SYNTH_LAYOUTS), tables,
                                      model.prefix, model.scan))
        p = Path(tmpdir) / ("seq%d.avi" % k)
        video_avi(p, w, h, frames)
        out.append((str(p), len(frames)))
    return out


def seq_lines(path, n, skip=0):
    """A movie's frames `skip` .. `skip + n - 1` through retail's decoder in
    order, from a fresh codec: each one's planes as CRCs."""
    a = Avi(path)
    vid = [ch for ch in a.chunks() if ch[1] == a.vs][skip:skip + n]
    fm = FrameModel(a.w, a.h, convert=False)
    out = []
    for i, (_, _, off, size) in enumerate(vid):
        fm.decode(a.read(off, size))
        y, u, v = fm.planes()
        out.append("seq %d 0 %08x %08x %08x misses 0 0" % (
            i, zlib.crc32(y) & 0xffffffff, zlib.crc32(u) & 0xffffffff,
            zlib.crc32(v) & 0xffffffff))
    out.append("seq end %d" % len(vid))
    return out


# Retail's own inter frames: MAINMENU's first, and a run from 473 that
# holds two keyframes, one frame apart.
REAL_SEQS = [("MAINMENU_MOVIE", 6, 0), ("MAINMENU_MOVIE", 6, 473)]
MENU_MOVIES = "extracted-retail/MOVIES"


def frame_list():
    """(movie, frame number) pairs: each boot movie's first, a middle and its
    last, and one of each other kind."""
    return [("EALOGO_EN", 0), ("EALOGO_EN", 179), ("BBGLOGO_EN", 391),
            ("NFSINTRO_EN", 1), ("NFSINTRO_EN", 1500), ("NFSINTRO_EN", 2424),
            ("EALOGO_FR", 60), ("REWARD_EN", 100)]


PACE_TIMES = ["0", "0", "0.01", "0.034", "0.05", "1", "1", "2.5", "2.51",
              "30", "30.2", "79.9", "80.8", "80.84", "81", "100"]
SYNTH_TIMES = ["0", "0.15", "0.25", "0.45", "1"]

# Update's times, in vblanks from the first call, which is at STEP_V0. None
# is on a frame's boundary, a multiple of 5 at 30 or 10 fps: retail's
# single-precision t / duration can land a hair under the integer there,
# where the port's double lands on it, and the two take the frame a vblank
# apart.
STEP_V0 = 1234
STEP_SEQ = [0, 0, 1, 2, 3, 4, 6, 7, 8, 9, 11, 12, 13, 14, 16, 17, 18, 19,
            21, 22]
STEP_SLOW = [0, 8, 16, 23, 31, 39, 46, 47, 48, 49, 51]
STEP_SYNTH = [0, 1, 2, 3, 4, 6, 7, 8, 9, 11, 12, 13, 14, 16, 17, 18, 19,
              21, 22, 23, 24, 26, 27]
STEP_MENU = [0] + [d for d in range(1, 1531) if d % 5 and not 700 < d < 760]


def riff(tag, body):
    return tag + struct.pack("<I", len(body)) + body + (b"\0" if len(body) & 1 else b"")


def rlist(kind, *parts):
    return riff(b"LIST", kind + b"".join(parts))


def strh(kind, scale, rate, length):
    return riff(b"strh", kind + bytes(16) + struct.pack(
        "<4I", scale, rate, 0, length) + bytes(20))


def video_avi(path, w, h, frames):
    """An AVI of one video stream, as the menu movies are: no sound."""
    bih = struct.pack("<I2i2H4sI2i2I", 40, w, h, 1, 24, b"MV30", w * h * 3,
                      0, 0, 0, 0)
    hdrl = rlist(b"hdrl", riff(b"avih", bytes(56)),
                 rlist(b"strl", strh(b"vids", 1, 30, len(frames)),
                       riff(b"strf", bih)))
    movi = b"".join(riff(b"00db", f) for f in frames)
    Path(path).write_bytes(riff(b"RIFF", b"AVI " + hdrl + rlist(b"movi", movi)))


def synth_avi(path):
    """What retail's files leave out: a stream that is neither video nor
    sound ahead of the sound, a negative biHeight, JUNK inside movi, `LIST
    rec ` groups, a tag that is a digit and then not, and a last chunk
    whose size runs one byte past movi. Its frames are EALOGO_EN's first
    four."""
    ea = Avi(str(ROOT / MOVIES / "EALOGO_EN.AVI"))
    vid = [ea.read(o, n) for t, s, o, n in ea.chunks() if s == ea.vs][:4]
    bih = struct.pack("<I2i2H4sI2i2I", 40, 512, -256, 1, 24, b"MV30",
                      512 * 256 * 3, 0, 0, 0, 0)
    wav = struct.pack("<HHIIHH", 1, 1, 22050, 22050, 1, 8)
    hdrl = rlist(b"hdrl", riff(b"avih", bytes(56)),
                 rlist(b"strl", strh(b"vids", 1, 10, 5), riff(b"strf", bih)),
                 rlist(b"strl", strh(b"txts", 1, 1, 1), riff(b"strf", bytes(4))),
                 rlist(b"strl", strh(b"auds", 1, 22050, 11), riff(b"strf", wav)))
    movi = (riff(b"JUNK", bytes(5))
            + rlist(b"rec ", riff(b"02wb", b"\x80\x81\x82"), riff(b"00db", vid[0]))
            + riff(b"01tx", b"x") + riff(b"0_zz", b"")
            + riff(b"00db", vid[1])
            + rlist(b"rec ", riff(b"00db", vid[2]), riff(b"02wb", bytes(7)))
            + riff(b"00db", vid[3])
            + b"00db" + struct.pack("<I", 17) + bytes(16))
    body = b"AVI " + hdrl + riff(b"JUNK", bytes(3)) + rlist(b"movi", movi)
    Path(path).write_bytes(riff(b"RIFF", body))


_SYNTH_DIR = None


def synth_path():
    """The synthetic AVI, in a directory of its own for the run. The harness
    splits its commands at spaces, so the path must have none."""
    global _SYNTH_DIR
    if _SYNTH_DIR is None:
        _SYNTH_DIR = tempfile.TemporaryDirectory(prefix="mv3_")
    p = Path(_SYNTH_DIR.name) / "synth.avi"
    if " " in str(p):
        raise SystemExit("the temp directory %s has a space in it" % p.parent)
    if not p.exists():
        synth_avi(p)
    return str(p)


def build_all(model_needed=True):
    rng = random.Random(0x4d563330)
    t0 = time.time()
    model = Model()
    fill_qtables(model)
    cmds = scenario_lines(rng)
    lines = []
    for c in cmds:
        lines += run_model(model, c)
    t1 = time.time()

    avis = {}
    frames = []
    for name, idx in frame_list():
        path = "%s/%s.AVI" % (MOVIES, name)
        if name not in avis:
            avis[name] = Avi(str(ROOT / path))
        a = avis[name]
        vid = [ch for ch in a.chunks() if ch[1] == a.vs]
        _, _, off, n = vid[idx]
        frames.append((name, idx, path, off, n, a.w, a.h))
        cmds.append("frame %s %d %d %d %d" % (path, off, n, a.w, a.h))
    fm = {}
    for name, idx, path, off, n, w, h in frames:
        key = (w, h)
        if key not in fm:
            fm[key] = FrameModel(w, h)
        rgba = fm[key].decode(avis[name].read(off, n))
        crc = zlib.crc32(rgba) & 0xffffffff
        lines.append("frame 0 %08x %08x misses 0" % (crc, crc))

    # The inter path, over whole sequences decoded in order: the synthetic
    # movies, then retail's own.
    seqs = synth_seqs(model, random.Random(0x50524556),
                      Path(synth_path()).parent)
    for path, n in seqs:
        cmds.append("seq %s %d" % (path, n))
        lines += seq_lines(path, n)
    for name, n, skip in REAL_SEQS:
        rel = "%s/%s.AVI" % (MENU_MOVIES, name)
        cmds.append("seq %s %d %d" % (rel, n, skip))
        lines += seq_lines(str(ROOT / rel), n, skip)
    t2 = time.time()

    for p in sorted(Path(ROOT / MOVIES).glob("*.AVI")):
        rel = "%s/%s" % (MOVIES, p.name)
        cmds.append("avi %s" % rel)
        lines += avi_lines(Avi(str(p)))
    for name in ("EALOGO_EN", "NFSINTRO_EN", "BBGLOGO_EN"):
        rel = "%s/%s.AVI" % (MOVIES, name)
        cmds.append("pace %s %s" % (rel, " ".join(PACE_TIMES)))
        lines += pace_lines(Avi(str(ROOT / rel)), PACE_TIMES)
    sp = synth_path()
    cmds.append("avi %s" % sp)
    lines += avi_lines(Avi(sp))
    cmds.append("pace %s %s" % (sp, " ".join(SYNTH_TIMES)))
    lines += pace_lines(Avi(sp), SYNTH_TIMES)
    menu = "%s/MAINMENU_MOVIE.AVI" % MENU_MOVIES
    for path, ds in ((seqs[0][0], STEP_SEQ), (seqs[0][0], STEP_SLOW),
                     (sp, STEP_SYNTH), (menu, STEP_MENU)):
        cmds.append("step %s %s" % (path, " ".join(map(str, ds))))
        lines += step_lines(model, Avi(str(ROOT / path)), ds)

    cmds.append("rate")
    lines += rate_lines(model)
    for name, pulls in MOVIE_SOUNDS:
        rel = "%s/%s.AVI" % (MOVIES, name)
        cmds.append("movsnd %s / %s" % (rel, " ".join(map(str, pulls))))
        lines += sound_lines(movie_pushes(Avi(str(ROOT / rel))), pulls)
    cmds.append("movsnd %s / 256" % sp)
    lines += sound_lines(movie_pushes(Avi(sp)), [256])
    for c, ls in sound_scenarios(random.Random(0x53505541), Path(sp).parent):
        cmds.append(c)
        lines += ls
    return cmds, lines, (t1 - t0, time.time() - t1, len(frames))


def run_model(model, cmd):
    w = cmd.split()
    k = w[0]
    if k == "table":
        return model.table()
    if k == "quant":
        return model.quant(int(w[1]), int(w[2]))
    if k == "bits":
        return model.bits(bytes.fromhex(w[1]), [int(x) for x in w[2:]])
    if k == "huff":
        return model.decomp(bytes.fromhex(w[1]), int(w[2]))
    if k == "idct":
        v = [int(x) for x in w[2:]]
        return model.idct(int(w[1]), v[:64], v[64:])
    if k == "idctadd":
        v = [int(x) for x in w[3:]]
        return model.idctadd(int(w[1]), bytes.fromhex(w[2]), v[:64], v[64:])
    if k == "copy":
        return model.copy(*[int(x) for x in w[1:]])
    if k == "yuv":
        return model.yuv(int(w[1]), int(w[2]), int(w[3]), bytes.fromhex(w[4]),
                         bytes.fromhex(w[5]), bytes.fromhex(w[6]))
    raise SystemExit("no model for %s" % k)


def survey():
    """Every retail movie's frames, and how many are the intra layout: the
    boot movies, then the menus'."""
    out = []
    paths = (sorted(Path(ROOT / MOVIES).glob("*.AVI"))
             + sorted(Path(ROOT / MENU_MOVIES).glob("*.AVI")))
    for p in paths:
        a = Avi(str(p))
        vid = [ch for ch in a.chunks() if ch[1] == a.vs]
        intra = sum(1 for ch in vid if a.read(ch[2] + 2, 2) == b"\0\0")
        snd = sum(n for t, s, o, n in a.chunks() if s == a.as_)
        out.append("  %-24s %4dx%-4d %5d frames at %.4f fps, %5d intra, "
                   "sound %d bytes, %.3f pairs"
                   % (p.stem, a.w, a.h, len(vid), a.rate / float(a.scale),
                      intra, snd, snd / float(PAIR)))
    return out


# ================================================================ the build


def build_harness(tmp, name="mv3_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, sc_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(sc_path)], stdout=fh,
                               stderr=subprocess.PIPE, text=True,
                               timeout=HARNESS_TIMEOUT, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        print("harness hung, killed after %d s" % HARNESS_TIMEOUT)
        return pcc.HARNESS_HUNG
    if r.returncode != 0:
        print("harness exited %d" % r.returncode)
        if r.stderr:
            print(r.stderr[:2000])
    return r.returncode


diff = pcc.diff

# ============================================================ the mutations

MUTATIONS = [
    # the tables
    ("zig-entry", MVC, "0, 1, 5, 6, 14, 15, 27, 28,",
     "0, 1, 5, 6, 14, 15, 28, 27,"),
    ("zig-inverse", MVC, "natural[i] = coef[kZig[i]];\n    mv3_idct(natural",
     "natural[kZig[i]] = coef[i];\n    mv3_idct(natural"),
    ("advance-64", MVC, "{ 0, 1, 4, 64 }", "{ 0, 1, 4, 63 }"),
    ("luma-quant-entry", MVC, "12, 12, 15, 19, 25, 34, 40, 48,",
     "12, 12, 15, 19, 25, 34, 40, 49,"),
    ("chroma-quant-entry", MVC, "24, 26, 56, 99,", "24, 26, 57, 99,"),
    ("aan-entry", MVC, "16384, 22725, 21407, 19266, 16384, 12873, 8867, 4520,\n"
     "    22725,", "16384, 22725, 21407, 19266, 16384, 12873, 8867, 4521,\n"
     "    22725,"),
    ("prefix-entry", MVC, "0x5001e,", "0x5001f,"),
    ("clamp-identity", MVC, "kClampTab[256 + i] = (uint8_t)i;",
     "kClampTab[256 + i] = (uint8_t)(i ^ (i == 200));"),
    # No class's prefix and bits come to exactly 10, so the edge is tested
    # from below: the 9-bit class 5 is the longest that fits the table.
    ("decode-escape-edge", MVC, "if (k + len >= 10) {", "if (k + len >= 9) {"),
    ("decode-sign-split", MVC, "else if (j < half / 2)",
     "else if (j <= half / 2)"),
    ("decode-magnitude", MVC, "value = (j & mask) + (1 << (k - 1));",
     "value = (j & mask) + (1 << k);"),
    ("decode-escape-byte", MVC, "value == -128 ? k - 1 : bits",
     "value == -128 ? k : bits"),
    ("offset-clamp-bias", MVC, "int32_t i = (int32_t)v + 384;",
     "int32_t i = (int32_t)v + 383;"),
    ("offset-clamp-low", MVC,
     "(int32_t)v + 384;\n    if ((uint32_t)i < 768u) return kClampTab[i];\n"
     "    mv3_clamp_misses++;\n    return i < 0 ? 0 : 255;",
     "(int32_t)v + 384;\n    if ((uint32_t)i < 768u) return kClampTab[i];\n"
     "    mv3_clamp_misses++;\n    return i < 0 ? 1 : 255;"),
    ("offset-clamp-high", MVC,
     "(int32_t)v + 384;\n    if ((uint32_t)i < 768u) return kClampTab[i];\n"
     "    mv3_clamp_misses++;\n    return i < 0 ? 0 : 255;",
     "(int32_t)v + 384;\n    if ((uint32_t)i < 768u) return kClampTab[i];\n"
     "    mv3_clamp_misses++;\n    return i < 0 ? 0 : 254;"),
    # the dequant tables
    ("quality-floor", MVC, "if (q < 1) q = 1;", "if (q < 2) q = 2;"),
    ("quality-ceiling", MVC, "if (q > 100) q = 100;", "if (q > 99) q = 99;"),
    ("quality-knee", MVC, "q < 50 ? 5000 / q", "q < 40 ? 5000 / q"),
    ("scale-round", MVC, "(uint32_t)scale) + 50;", "(uint32_t)scale) + 49;"),
    ("scale-zero", MVC, "if (v <= 0) v = 1;", "if (v < 0) v = 1;"),
    ("prescale-round", MVC, "* (uint32_t)kAan[i] + 2048, 12);",
     "* (uint32_t)kAan[i] + 2047, 12);"),
    ("quality-s8", MVC, "int q = (int8_t)quality,", "int q = quality,"),
    ("delta-s8", MVC, "qd = q + (int8_t)delta", "qd = q + delta"),
    ("table-order", MVC, "generate(qd, kLumaQuant,   m->quant[1]);",
     "generate(q, kLumaQuant,   m->quant[1]);"),
    # the entropy layer
    ("refill-25", MVC, "while (b->count < 25) {", "while (b->count < 24) {"),
    ("refill-shift", MVC, "byte << ((24 - b->count) & 31)",
     "byte << ((23 - b->count) & 31)"),
    ("take-count", MVC, "    b->count -= n;\n    return v;",
     "    b->count -= n + (n == 7);\n    return v;"),
    ("escape-prefix", MVC, "unsigned len = kPrefix[kk + 1] >> 16;",
     "unsigned len = kPrefix[kk] >> 16;"),
    ("escape-sign", MVC, "sign ? 0u - mag : mag", "sign ? mag : 0u - mag"),
    ("escape-top-bit", MVC, "+ (1u << (kk & 31));", "+ (1u << (kk & 31)) * 0;"),
    ("escape-sign-first", MVC,
     "            sign = take(b, 1);\n            mag = (b->accum >> ((0u - kk) & 31)) + (1u << (kk & 31));\n            b->accum <<= kk & 31;\n            b->count -= kk;\n",
     "            mag = (b->accum >> ((0u - kk) & 31)) + (1u << (kk & 31));\n            b->accum <<= kk & 31;\n            b->count -= kk;\n            sign = take(b, 1);\n"),
    ("literal-consume", MVC, "            b->count -= e[0];\n        } else {",
     "            b->count -= e[0] - (e[0] == 3);\n        } else {"),
    ("run-prefix", MVC, "b->accum <<= 2;\n            b->count -= 2;",
     "b->accum <<= 3;\n            b->count -= 3;"),
    ("run-long", MVC, "run = take(b, 6) + 9;", "run = take(b, 6) + 8;"),
    ("run-short", MVC, "run = take(b, 3) + 1;", "run = take(b, 3) + 2;"),
    ("run-flag", MVC, "if (take(b, 1))\n                run", "if (!take(b, 1))\n                run"),
    # the IDCTs
    ("aan-362", MVC, "uint32_t t12 = SRA((x2 - x6) * 362u, 8) - t13;",
     "uint32_t t12 = SRA((x2 - x6) * 363u, 8) - t13;"),
    ("aan-362-odd", MVC, "uint32_t d11 = SRA((z11 - z13) * 362u, 8);",
     "uint32_t d11 = SRA((z11 - z13) * 361u, 8);"),
    ("aan-473", MVC, "SRA((z10 + z12) * 473u, 8);", "SRA((z10 + z12) * 472u, 8);"),
    ("aan-277", MVC, "SRA(z12 * 277u, 8) - z5;", "SRA(z12 * 278u, 8) - z5;"),
    ("aan-669", MVC, "(uint32_t)-669, 8)", "(uint32_t)-668, 8)"),
    ("aan-o3-o4", MVC, "o4 = e3 + d4; o3 = e3 - d4;", "o3 = e3 + d4; o4 = e3 - d4;"),
    ("aan-sra-logical", MVC, "#define SRA(x, n) ((uint32_t)((int32_t)(x) >> (n)))",
     "#define SRA(x, n) ((uint32_t)(x) >> (n))"),
    ("idct-transpose", MVC,
     "x[r] = (uint32_t)coef[r * 8 + i] * (uint32_t)q[r * 8 + i];",
     "x[r] = (uint32_t)coef[i * 8 + r] * (uint32_t)q[i * 8 + r];"),
    ("idct-descale", MVC, "dst[c] = offset_clamp(SRA(o[c], 5));",
     "dst[c] = offset_clamp(SRA(o[c], 4));"),
    ("idct1-descale", MVC, "(uint32_t)coef[0] * (uint32_t)q[0], 5));",
     "(uint32_t)coef[0] * (uint32_t)q[0], 4));"),
    ("idct4-row-q", MVC, "x1 = (uint32_t)coef[i + 2] * (uint32_t)q[i + 8];",
     "x1 = (uint32_t)coef[i + 2] * (uint32_t)q[i + 2];"),
    ("idct4-col-d4", MVC,
     "            uint32_t d4  = SRA(x1 * 277u, 8) - z5 + d5;\n            ws[0 * 8 + i]",
     "            uint32_t d4  = SRA(x1 * 277u, 8) - z5 - d5;\n            ws[0 * 8 + i]"),
    ("idct4-col-order", MVC, "ws[4 * 8 + i] = x0 + d4;  ws[3 * 8 + i] = x0 - d4;",
     "ws[3 * 8 + i] = x0 + d4;  ws[4 * 8 + i] = x0 - d4;"),
    ("idct4-row-order", MVC,
     "dst[3] = offset_clamp(SRA(x0 - d4, 5));\n            dst[4] = offset_clamp(SRA(x0 + d4, 5));",
     "dst[3] = offset_clamp(SRA(x0 + d4, 5));\n            dst[4] = offset_clamp(SRA(x0 - d4, 5));"),
    ("idct4-col-shortcut", MVC, "if (coef[i + 2] == 0) {",
     "if (coef[i + 2] == 0 && 0) {"),
    ("idct4-row-shortcut", MVC, "if (x1 == 0) {\n            memset(",
     "if (x1 == 0 && 0) {\n            memset("),
    ("idct-zero-grey", MVC, "memset(dst, 0x80, 8);", "memset(dst, 0x7f, 8);"),
    # the frame
    ("frame-quality-bytes", MVC, "mv3_init_idct_tables(m, frame[0], frame[1]);",
     "mv3_init_idct_tables(m, frame[1], frame[0]);"),
    ("frame-types-order", MVC, "(types[i >> 2] >> ((i & 3) * 2)) & 3",
     "(types[i >> 2] >> ((3 - (i & 3)) * 2)) & 3"),
    ("frame-dc-v", MVC, "n < 4 ? &dcY : n == 4 ? &dcU : &dcV;",
     "n < 4 ? &dcY : &dcU;"),
    ("frame-dc-row", MVC, "int16_t dcY = 0, dcU = 0, dcV = 0;",
     "static int16_t dcY = 0, dcU = 0, dcV = 0;"),
    ("frame-dc-type0", MVC, "if (!kAdvance[t]) continue;",
     "if (!kAdvance[t] && 0) continue;"),
    ("frame-luma-order", MVC,
     "k = block(k, type_of(types, tcap, blk++), ql, py + 8, w);\n"
     "                    k = block(k, type_of(types, tcap, blk++), ql, py + 8 * w, w);",
     "k = block(k, type_of(types, tcap, blk++), ql, py + 8 * w, w);\n"
     "                    k = block(k, type_of(types, tcap, blk++), ql, py + 8, w);"),
    ("frame-chroma-order", MVC,
     "k = block(k, type_of(types, tcap, blk++), qc, pu, cw);\n"
     "                    k = block(k, type_of(types, tcap, blk++), qc, pv, cw);",
     "k = block(k, type_of(types, tcap, blk++), qc, pv, cw);\n"
     "                    k = block(k, type_of(types, tcap, blk++), qc, pu, cw);"),
    ("frame-luma-table", MVC, "const int16_t* ql = m->quant[0];",
     "const int16_t* ql = m->quant[1];"),
    ("frame-chroma-table", MVC, "const int16_t* qc = m->quant[2];",
     "const int16_t* qc = m->quant[3];"),
    ("frame-row-step", MVC, "py += 15 * w;", "py += 14 * w;"),
    ("frame-chroma-row-step", MVC, "pu += 7 * cw;", "pu += 6 * cw;"),
    ("frame-count-bits", MVC, "uint32_t count = mv3_get_bits(&m->bits, 16);",
     "uint32_t count = mv3_get_bits(&m->bits, 15);"),
    # the adds
    ("add-clamp-bias", MVC, "int32_t i = (int32_t)(d + v) + 256;",
     "int32_t i = (int32_t)(d + v) + 255;"),
    ("add-clamp-low", MVC,
     "(int32_t)(d + v) + 256;\n    if ((uint32_t)i < 768u) return kClampTab[i];\n"
     "    mv3_clamp_misses++;\n    return i < 0 ? 0 : 255;",
     "(int32_t)(d + v) + 256;\n    if ((uint32_t)i < 768u) return kClampTab[i];\n"
     "    mv3_clamp_misses++;\n    return i < 0 ? 1 : 255;"),
    ("add-clamp-high", MVC,
     "(int32_t)(d + v) + 256;\n    if ((uint32_t)i < 768u) return kClampTab[i];\n"
     "    mv3_clamp_misses++;\n    return i < 0 ? 0 : 255;",
     "(int32_t)(d + v) + 256;\n    if ((uint32_t)i < 768u) return kClampTab[i];\n"
     "    mv3_clamp_misses++;\n    return i < 0 ? 0 : 254;"),
    ("add-descale", MVC, "dst[c] = add_clamp(dst[c], SRA(o[c], 5));",
     "dst[c] = add_clamp(dst[c], SRA(o[c], 4));"),
    ("add-zig-inverse", MVC, "natural[i] = coef[kZig[i]];\n    mv3_idct_add(natural",
     "natural[kZig[i]] = coef[i];\n    mv3_idct_add(natural"),
    ("add1-descale", MVC, "uint32_t v = SRA((uint32_t)coef[0] * (uint32_t)q[0], 5);",
     "uint32_t v = SRA((uint32_t)coef[0] * (uint32_t)q[0], 4);"),
    ("add4-dc-descale", MVC, "uint32_t v = SRA(x0, 5);", "uint32_t v = SRA(x0, 4);"),
    ("add4-row-order", MVC,
     "dst[3] = add_clamp(dst[3], SRA(x0 - d4, 5));\n            dst[4] = add_clamp(dst[4], SRA(x0 + d4, 5));",
     "dst[3] = add_clamp(dst[3], SRA(x0 + d4, 5));\n            dst[4] = add_clamp(dst[4], SRA(x0 - d4, 5));"),
    ("add4-row-shortcut", MVC,
     "        if (x1 == 0) {\n            uint32_t v = SRA(x0, 5);",
     "        if (x1 == 0 && 0) {\n            uint32_t v = SRA(x0, 5);"),
    ("add-type0", MVC, "    case 0: break;\n    case 1: mv3_idct1_add",
     "    case 0: mv3_idct1_add(c, q, dst, stride); break;\n    case 1: mv3_idct1_add"),
    ("add-type1", MVC, "case 1: mv3_idct1_add(c, q, dst, stride); break;",
     "case 1: mv3_idct_add_zigzag(c, q, dst, stride); break;"),
    ("add-type2", MVC, "case 2: mv3_idct4_add(c, q, dst, stride); break;",
     "case 2: mv3_idct_add_zigzag(c, q, dst, stride); break;"),
    # the motion copy
    ("copy-vector-order", MVC,
     "int sx = x + m->vects[idx * 2], sy = y + m->vects[idx * 2 + 1];",
     "int sx = x + m->vects[idx * 2 + 1], sy = y + m->vects[idx * 2];"),
    ("copy-chroma-round-x", MVC, "* cw + sx / 2;", "* cw + (sx >> 1);"),
    ("copy-chroma-round-y", MVC, "(ptrdiff_t)(sy / 2) * cw", "(ptrdiff_t)(sy >> 1) * cw"),
    ("copy-from-current", MVC, "memcpy(dst, m->prevPlanes + off, (size_t)n);",
     "memcpy(dst, m->planes + off, (size_t)n);"),
    ("copy-v-plane", MVC, "copy_rows(m, 2 * (ptrdiff_t)m->area + c, cw, dv, 8);",
     "copy_rows(m, (ptrdiff_t)m->area + c, cw, dv, 8);"),
    ("copy-miss-fill", MVC, "dst[i] = 0;\n                mv3_copy_misses++;",
     "dst[i] = 1;\n                mv3_copy_misses++;"),
    ("copy-alloc-size", MVC, "ptrdiff_t size = (ptrdiff_t)m->allocSize;",
     "ptrdiff_t size = 3 * (ptrdiff_t)m->area;"),
    # the inter frame
    ("inter-flag", MVC, "intra = frame[2] == 0 && frame[3] == 0;",
     "intra = frame[2] == 0;"),
    ("inter-swap", MVC, "    swap_prev(m);\n    if (!intra) memcpy",
     "    if (!intra) memcpy"),
    ("inter-head", MVC, "head = intra ? 2 : 4 + transp;", "head = intra ? 2 : 4;"),
    ("inter-vects-count", MVC, "m->vects, (uint32_t)vects * 2);",
     "m->vects, (uint32_t)vects);"),
    ("inter-coded-bits", MVC, "(uint32_t)m->mbw : mv3_get_bits(&m->bits, 8);",
     "(uint32_t)m->mbw : mv3_get_bits(&m->bits, 7);"),
    ("inter-coded-dc", MVC, "for (mb = 0; mb < (int)coded; mb++) {",
     "for (mb = 0; mb + 1 < (int)coded; mb++) {"),
    ("transp-copy-bit", MVC, "if (bits & 1) {", "if (bits & 2) {"),
    ("transp-shift", MVC, "m->transp[mbi >> 2] >> (mbi & 3);",
     "m->transp[mbi >> 2] >> ((mbi & 3) * 2);"),
    ("transp-index", MVC, "m->transp[mbi >> 2] >> (mbi & 3);",
     "m->transp[mbi >> 3] >> (mbi & 3);"),
    ("transp-residual-bit", MVC, "if (!(bits & 16)) {", "if (!(bits & 32)) {"),
    ("inter-luma-table", MVC, "const int16_t* ql = m->quant[1];",
     "const int16_t* ql = m->quant[0];"),
    ("inter-chroma-table", MVC, "const int16_t* qc = m->quant[3];",
     "const int16_t* qc = m->quant[2];"),
    ("inter-vec-residual", MVC,
     "pv, (int)vec++);\n                    if (!(bits & 16)) {",
     "pv, (int)vec);\n                    if (!(bits & 16)) {\n                        vec++;"),
    ("inter-vec-every-mb", MVC, "pv, (int)vec++);", "pv, (int)mbi);"),
    ("inter-luma-order", MVC,
     "k = block_add(k, type_of(types, tcap, blk++), ql, py + 8, w);\n"
     "                        k = block_add(k, type_of(types, tcap, blk++), ql, py + 8 * w, w);",
     "k = block_add(k, type_of(types, tcap, blk++), ql, py + 8 * w, w);\n"
     "                        k = block_add(k, type_of(types, tcap, blk++), ql, py + 8, w);"),
    ("inter-chroma-order", MVC,
     "k = block_add(k, type_of(types, tcap, blk++), qc, pu, cw);\n"
     "                        k = block_add(k, type_of(types, tcap, blk++), qc, pv, cw);",
     "k = block_add(k, type_of(types, tcap, blk++), qc, pv, cw);\n"
     "                        k = block_add(k, type_of(types, tcap, blk++), qc, pu, cw);"),
    # YUV -> RGB
    ("yuv-div-bias", MVC, "(x > -1 ? x : x + 255) >> 8", "(x > -1 ? x : x + 256) >> 8"),
    ("yuv-div-floor", MVC, "(x > -1 ? x : x + 255) >> 8", "x >> 8"),
    ("yuv-359", MVC, "c.r = div256(cr * 359);", "c.r = div256(cr * 358);"),
    ("yuv-88", MVC, "cb * -88 - cr * 183", "cb * -87 - cr * 183"),
    ("yuv-183", MVC, "cb * -88 - cr * 183", "cb * -88 - cr * 182"),
    ("yuv-454", MVC, "c.b = div256(cb * 454);", "c.b = div256(cb * 453);"),
    ("yuv-uv-swap", MVC, "int32_t cr = (int32_t)v - 128, cb = (int32_t)u - 128;",
     "int32_t cr = (int32_t)u - 128, cb = (int32_t)v - 128;"),
    ("yuv-alpha", MVC, "ds[i][3] = 255;", "ds[i][3] = 254;"),
    ("yuv-flip", MVC, "int stride = flip ? -4 * w : 4 * w;",
     "int stride = 4 * w;"),
    ("yuv-quad", MVC, "py + w + x, py + w + x + 1 };", "py + w + x + 1, py + w + x };"),
    ("tiled-bottom", MVC, "const uint8_t* bot = top - w;",
     "const uint8_t* bot = top - w * (y == 2 ? 0 : 1);"),
    ("tiled-chroma-row", MVC, "size_t crow = (size_t)cw * ((h - 2 - y) / 2);",
     "size_t crow = (size_t)cw * ((h - y) / 2 - (y == 0));"),
    ("tiled-texel-order", MVC,
     "return (uint32_t)CLAMP[y + c.r] << 24 | (uint32_t)CLAMP[y + c.g] << 16",
     "return (uint32_t)CLAMP[y + c.g] << 24 | (uint32_t)CLAMP[y + c.r] << 16"),
    ("tiled-morton", MVC, "(x & 2) << 1 | (y & 2) << 2\n         | (x & 4) << 2",
     "(x & 2) << 2 | (y & 2) << 1\n         | (x & 4) << 2"),
    # the container
    ("avi-stream-digits", AVC, "return a * 10 + b;", "return b * 10 + a;"),
    ("avi-stream-range", AVC, "if (a < 0 || a > 9 || b < 0 || b > 9) return -1;",
     "if (a < 0 || a > 9 || b < 0) return -1;"),
    ("avi-list-step", AVC, "*pos += 12;\n            continue;",
     "*pos += 8;\n            continue;"),
    ("avi-pad", AVC, "*pos += 8 + size + (size & 1);\n        if (tag",
     "*pos += 8 + size;\n        if (tag"),
    ("avi-junk", AVC, "if (tag == AVI_TAG('J', 'U', 'N', 'K')) continue;",
     "if (tag == AVI_TAG('J', 'U', 'N', 'X')) continue;"),
    ("avi-oversize", AVC, "if (size > info->moviEnd - (*pos + 8)) return false;",
     "if (size > info->moviEnd - (*pos + 8) + 8) return false;"),
    ("avi-scale", AVC, "o->scale  = rd32(strh + 20);", "o->scale  = rd32(strh + 24);"),
    ("avi-frames", AVC, "o->frames = rd32(strh + 32);", "o->frames = rd32(strh + 28);"),
    ("avi-height-abs", AVC, "o->bmpHeight < 0 ? -o->bmpHeight", "o->bmpHeight < 0 ? 0"),
    ("avi-audio-bits", AVC, "o->audioBits     = rd16(b + 14);",
     "o->audioBits     = rd16(b + 12);"),
    ("avi-first-audio", AVC,
     "} else if (type == AVI_TAG('a', 'u', 'd', 's') && o->audioStream < 0) {",
     "} else if (type != AVI_TAG('v', 'i', 'd', 's') && o->audioStream < 0) {"),
    ("avi-strl-count", AVC, "parse_strl(f, sub + 12, sub + 8 + ss, streams++, o);",
     "parse_strl(f, sub + 12, sub + 8 + ss, streams, o);"),
    ("avi-movi-start", AVC, "o->moviStart = off + 12;", "o->moviStart = off + 8;"),
    # the pacing
    ("pace-floor", AVC, "0xffffffffu : (uint32_t)f;", "0xffffffffu : (uint32_t)(f + 0.5);"),
    ("pace-clamp", AVC, "target >= m->info.frames) target", "target > m->info.frames) target"),
    ("pace-skip", AVC, "if (m->nextFrame < target) {", "if (m->nextFrame + 1 < target) {"),
    ("pace-first", AVC, "(m->shown < 0 || (uint32_t)m->shown < target)",
     "((uint32_t)m->shown < target)"),
    ("pace-audio", AVC, "if (m->audio) m->audio(m->audioUser, m->file, &c);"
     "\n            continue;\n        }\n        if (s != m->info.videoStream) continue;"
     "\n        if (m->nextFrame < target) {",
     "if (m->audio && m->decoded) m->audio(m->audioUser, m->file, &c);"
     "\n            continue;\n        }\n        if (s != m->info.videoStream) continue;"
     "\n        if (m->nextFrame < target) {"),
    ("pace-done", AVC, "&& (uint32_t)m->shown + 1 >= m->info.frames;",
     "&& (uint32_t)m->shown >= m->info.frames;"),
    ("pace-duration", AVC,
     "return (double)m->info.frames * (double)m->info.scale / (double)m->info.rate;",
     "return (double)(m->info.frames - 1) * (double)m->info.scale / (double)m->info.rate;"),
    # the menus' pacing
    ("step-due", AVC, "if (m->shown >= 0 && m->decoded >= target) return 1;",
     "if (m->shown >= 0 && m->decoded > target) return 1;"),
    ("step-first", AVC, "if (m->shown >= 0 && m->decoded >= target) return 1;",
     "if (m->decoded >= target) return 1;"),
    ("step-catch-up", AVC, "if (changed) *changed = true;\n        return 1;",
     "if (changed) *changed = true;\n        if (m->decoded >= target) return 1;"),
    ("step-skip", AVC, "if (!decode_chunk(m, &c)) return 0;",
     "if (m->decoded + 1 < target) { m->nextFrame++; m->decoded++; continue; }"
     "\n        if (!decode_chunk(m, &c)) return 0;"),
    ("step-end", AVC, "m->ended = true;\n            return 0;",
     "m->ended = true;\n            return 1;"),
    ("step-audio", AVC, "if (m->audio) m->audio(m->audioUser, m->file, &c);"
     "\n            continue;\n        }\n        if (s != m->info.videoStream) continue;"
     "\n        if (!decode_chunk", "continue;\n        }"
     "\n        if (s != m->info.videoStream) continue;\n        if (!decode_chunk"),
    ("step-changed", AVC, "if (changed) *changed = true;",
     "if (changed) *changed = m->decoded > 1;"),
    ("step-count", AVC, "m->decoded++;\n        if (changed)",
     "if (changed)"),
    ("step-shown", AVC, "m->shown = (int32_t)m->nextFrame++;\n        m->decoded++;\n        if (changed)",
     "m->shown = (int32_t)++m->nextFrame;\n        m->decoded++;\n        if (changed)"),
    # the sound: the decoder
    ("snd-filter-1", AVC, "{ 60, 0 }", "{ 61, 0 }"),
    ("snd-filter-2", AVC, "{ 115, -52 }", "{ 115, -51 }"),
    ("snd-filter-3", AVC, "{ 98, -55 }", "{ 98, -56 }"),
    ("snd-filter-4", AVC, "{ 122, -60 }", "{ 122, -61 }"),
    ("snd-pred-clamp", AVC, "if (pred > 4) pred = 0;", "if (pred > 4) pred = 4;"),
    ("snd-round", AVC, "f1 * h2 + 32) >> 6);", "f1 * h2 + 31) >> 6);"),
    ("snd-nibble-order", AVC, ">> ((k & 1) * 4)) & 15) << 12);",
     ">> ((~k & 1) * 4)) & 15) << 12);"),
    ("snd-sign", AVC, "int32_t v = (int16_t)(uint16_t)(", "int32_t v = (int32_t)(uint16_t)("),
    ("snd-clamp-hi", AVC, "if (v > 32767) v = 32767;", "if (v > 32766) v = 32766;"),
    ("snd-clamp-lo", AVC, "if (v < -32768) v = -32768;", "if (v < -32767) v = -32767;"),
    ("snd-hist-order", AVC, "h2 = h1;\n        h1 = v;", "h1 = v;\n        h2 = h1;"),
    ("snd-hist-save", AVC, "hist[1] = h2;", "hist[1] = h1;"),
    # the layout
    ("snd-block", AVH, "#define AVISOUND_BLOCK   0x8000", "#define AVISOUND_BLOCK   0x4000"),
    ("snd-right-block", AVC, "spu_frame(l + AVISOUND_BLOCK, s->hist[1], out + 1);",
     "spu_frame(l + AVISOUND_BLOCK - 16, s->hist[1], out + 1);"),
    ("snd-right-hist", AVC, "spu_frame(l + AVISOUND_BLOCK, s->hist[1], out + 1);",
     "spu_frame(l + AVISOUND_BLOCK, s->hist[0], out + 1);"),
    ("snd-left-slot", AVC, "spu_frame(l, s->hist[0], out);",
     "spu_frame(l, s->hist[0], out + 1);"),
    ("snd-stride", AVC, "out[2 * k] = (int16_t)v;", "out[k] = (int16_t)v;"),
    # the stream
    ("snd-ready", AVC, "return pairs ? pairs * AVISOUND_FRAMES - s->frame : 0;",
     "return pairs ? pairs * AVISOUND_FRAMES - s->frame - (pairs > 1) : 0;"),
    ("snd-ready-partial", AVC, "uint32_t pairs = s->len / AVISOUND_PAIR;",
     "uint32_t pairs = (s->len + AVISOUND_BLOCK) / AVISOUND_PAIR;"),
    ("snd-pull-limit", AVC, "while (done < frames && s->len >= AVISOUND_PAIR) {",
     "while (done + 1 < frames && s->len >= AVISOUND_PAIR) {"),
    ("snd-pull-count", AVC, "return done * AVISOUND_SAMPLES;",
     "return done * (AVISOUND_SAMPLES / 2);"),
    ("snd-pair-end", AVC, "if (++s->frame == AVISOUND_FRAMES) {",
     "if (++s->frame == AVISOUND_FRAMES - 1) {"),
    ("snd-pair-drop", AVC, "memmove(s->buf, s->buf + AVISOUND_PAIR, s->len);",
     "memmove(s->buf, s->buf + AVISOUND_PAIR, s->len / 2);"),
    ("snd-pair-hist", AVC, "            s->frame = 0;\n",
     "            s->frame = 0;\n            s->hist[1][0] = 0;\n"),
    ("snd-push-count", AVC, "    s->len += n;\n    s->pushed += n;",
     "    s->len += n;\n    s->pushed += n - (n > 1);"),
    ("snd-read-count", AVC, "    s->len += c->size;\n    s->pushed += c->size;",
     "    s->len += c->size;\n    s->pushed += c->size + 1;"),
    # the rate
    ("snd-rate", AVH, "#define AVISOUND_RATE    0xaa66", "#define AVISOUND_RATE    0xac44"),
    ("snd-rate-trip", AVC, "return bsnd_spu_to_hz(bsnd_hz_to_spu(AVISOUND_RATE));",
     "return AVISOUND_RATE;"),
]

# A shortcut IDCT4 and IDCTAdd4 take when a column's or a row's second
# input is zero: the general formulas give x0 at all eight then, so each
# shortcut is the same arithmetic done faster.
EQUIVALENT = {"idct4-col-shortcut", "idct4-row-shortcut", "add4-row-shortcut"}


def mutate_pass(cmds, base, only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    caught, survived, missing, equivalent = 0, [], [], []
    scdir = tempfile.TemporaryDirectory()
    scp = Path(scdir.name) / "scenarios.txt"
    scp.write_text(NL.join(cmds) + NL)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, scp, out)
        if diff(base, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for m in todo:
        name, rel, before, after = m
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if text.count(probe) != 1:
            missing.append(name)
            print("  %-44s PATTERN %s" % (
                name, "NOT FOUND" if not text.count(probe) else "NOT UNIQUE"))
            continue
        new = text.replace(probe, repl, 1)
        try:
            hostbuild.write_source(path, new)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = build_harness(tmp)
                except SystemExit:
                    print("  %-44s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, scp, out)
                if rc == pcc.HARNESS_HUNG:
                    print("  %-44s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-44s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-44s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-44s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-44s SURVIVED" % name)
                    survived.append(name)
        finally:
            try:
                hostbuild.write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))
    scdir.cleanup()

    real = [m for m in todo if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    ran = {m[0] for m in todo}
    stale = [n for n in EQUIVALENT
             if n not in equivalent and n not in missing
             and (n in ran or only is None)]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally above is over %d of %d"
              % (len(missing), len(real), len(todo)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
    for name in holes:
        print("  unexplained: %s" % name)
    for name in stale:
        print("  listed as equivalent but %s: %s"
              % ("caught" if name in ran else "names no mutation", name))
    return 1 if (holes or missing or stale) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--dump", metavar="PREFIX")
    ap.add_argument("--survey", action="store_true",
                    help="print every retail movie's frame counts and stop")
    args = ap.parse_args()

    if args.survey:
        print(NL.join(survey()))
        return
    bad = check_map()
    if bad:
        print(NL.join(bad))
        sys.exit(1)

    cmds, lines, (tu, tf, nf) = build_all()
    if args.mutate:
        sys.exit(mutate_pass(cmds, lines,
                             args.only.split(",") if args.only else None))

    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = Path(tmp) / "scenarios.txt"
        scp.write_text(NL.join(cmds) + NL)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)
        d.with_suffix(".cmds").write_text(NL.join(cmds) + NL)

    n = diff(lines, harness)
    print("%d scenarios, %d frames, %d lines, %d differ (model %.0f s + %.0f s)"
          % (len(cmds), nf, len(harness), n, tu, tf))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
