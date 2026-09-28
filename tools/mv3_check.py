#!/usr/bin/env python3
r"""Cross-check 3DS Files/source/mv3.c (the MV3 intra decoder) and
avimovie.c (the AVI streamer) against the retail image's own decoder, run
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
- ToImage32 on random planes at small sizes, both row orders, with every
  plane byte from 0 to 255 reached;
- whole frames of retail's movies through DecompressFrameShared, the boot
  movies' first, middle and last among them, compared as CRCs of the RGBA,
  the port's tiled texture read back into rows, and the port's count of
  IDCT outputs past the clamp table, which has to be 0.

The PS2 reads `Codec::OffsetClamp` without a bound. For the IDCT scenarios
the model fills 128 KB of memory below the table with 0 and 615 bytes
above it with 255, so an out-of-range value reads what the port saturates
to; the blocks are drawn so that no output reaches past those bytes (index
999, where IDCTImageData's timer store lands). Whole frames run with the
image's memory untouched.

The AVI half has no retail code to run -- `avimovie.c` is the port's -- so
it is held to this file's own reading of RIFF: every retail movie's header
and chunk list, and the player's pacing (which frames it decodes, which it
reads past, which audio chunks it hands on) over a schedule of clock times.

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

# The ones the map pairs, and the demo's twins.
DEMO_CODE = {
    CODEC_CTOR: 0x0021c9c8, CLAMP_INIT: 0x0021cce0,
    DCTIMAGE_CTOR: 0x0021ef90, BUILD_DECODE: 0x002217a8,
    INIT_IDCT: 0x0021f2b8, GETBITS: 0x00221728, INIT_DECOMP: 0x00221918,
    DECOMPRESS: 0x00221928, IDCT: 0x0021d918, IDCT1: 0x0021e508,
    IDCT4: 0x0021e560, IDCT_DATA: 0x0021f3d8, IDCT_ZERO: 0x0021f608,
    TO_IMAGE32: 0x00220ac0, MV3_CTOR: 0x002231a8, BEGIN: 0x002233d0,
    FRAME: 0x002234c8, MOVIE_UPDATE: 0x002224f8, HZ_TO_SPU: 0x002528b8,
}

GUARD_BELOW = 0x20000
GUARD_ABOVE = IDCT_TIMER - (CLAMP_TAB + 768)      # up to index 999
INDEX_MAX = 383 + GUARD_ABOVE


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
    return bad


def u32(v):
    return v & 0xffffffff


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


class FrameModel(object):
    """DecompressFrameShared on a fresh image, as the game calls it."""

    def __init__(self, w, h):
        e = self.e = retail_model.RetailEmu()
        e.stub_bware()
        e.call(CLAMP_INIT)
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
        e.put32(self.obj + CONVERT_TO_RGBA, 1)
        self.dst = e.alloc(w * h * 4)
        self.src, self.cap = 0, 0

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


def frame_list():
    """(movie, frame number) pairs: each boot movie's first, a middle and its
    last, and one of each other kind."""
    return [("EALOGO_EN", 0), ("EALOGO_EN", 179), ("BBGLOGO_EN", 391),
            ("NFSINTRO_EN", 1), ("NFSINTRO_EN", 1500), ("NFSINTRO_EN", 2424),
            ("EALOGO_FR", 60), ("REWARD_EN", 100)]


PACE_TIMES = ["0", "0", "0.01", "0.034", "0.05", "1", "1", "2.5", "2.51",
              "30", "30.2", "79.9", "80.8", "80.84", "81", "100"]
SYNTH_TIMES = ["0", "0.15", "0.25", "0.45", "1"]


def riff(tag, body):
    return tag + struct.pack("<I", len(body)) + body + (b"\0" if len(body) & 1 else b"")


def rlist(kind, *parts):
    return riff(b"LIST", kind + b"".join(parts))


def synth_avi(path):
    """What retail's files leave out: a stream that is neither video nor
    sound ahead of the sound, a negative biHeight, JUNK inside movi, `LIST
    rec ` groups, a tag that is a digit and then not, and a last chunk
    whose size runs one byte past movi. Its frames are EALOGO_EN's first
    four."""
    ea = Avi(str(ROOT / MOVIES / "EALOGO_EN.AVI"))
    vid = [ea.read(o, n) for t, s, o, n in ea.chunks() if s == ea.vs][:4]

    def strh(kind, scale, rate, length):
        return riff(b"strh", kind + bytes(16) + struct.pack(
            "<4I", scale, rate, 0, length) + bytes(20))
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
    if k == "yuv":
        return model.yuv(int(w[1]), int(w[2]), int(w[3]), bytes.fromhex(w[4]),
                         bytes.fromhex(w[5]), bytes.fromhex(w[6]))
    raise SystemExit("no model for %s" % k)


def survey():
    """Every retail movie's frames, and how many are the intra layout."""
    out = []
    for p in sorted(Path(ROOT / MOVIES).glob("*.AVI")):
        a = Avi(str(p))
        vid = [ch for ch in a.chunks() if ch[1] == a.vs]
        intra = sum(1 for ch in vid if a.read(ch[2] + 2, 2) == b"\0\0")
        snd = sum(n for t, s, o, n in a.chunks() if s == a.as_)
        out.append("  %-16s %4dx%-4d %5d frames, %5d intra, sound %d bytes, "
                   "%.3f pairs" % (p.stem, a.w, a.h, len(vid), intra, snd,
                                   snd / float(PAIR)))
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
    ("zig-inverse", MVC, "natural[i] = coef[kZig[i]];",
     "natural[kZig[i]] = coef[i];"),
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
    ("offset-clamp-low", MVC, "return i < 0 ? 0 : 255;",
     "return i < 0 ? 1 : 255;"),
    ("offset-clamp-high", MVC, "return i < 0 ? 0 : 255;",
     "return i < 0 ? 0 : 254;"),
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
    ("idct4-row-shortcut", MVC, "if (x1 == 0) {", "if (x1 == 0 && 0) {"),
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
     "k = block(k, type_of(types, blk++), ql, py + 8, w);\n                k = block(k, type_of(types, blk++), ql, py + 8 * w, w);",
     "k = block(k, type_of(types, blk++), ql, py + 8 * w, w);\n                k = block(k, type_of(types, blk++), ql, py + 8, w);"),
    ("frame-chroma-order", MVC,
     "k = block(k, type_of(types, blk++), qc, pu, cw);\n                k = block(k, type_of(types, blk++), qc, pv, cw);",
     "k = block(k, type_of(types, blk++), qc, pv, cw);\n                k = block(k, type_of(types, blk++), qc, pu, cw);"),
    ("frame-luma-table", MVC, "const int16_t* ql = m->quant[0];",
     "const int16_t* ql = m->quant[1];"),
    ("frame-chroma-table", MVC, "const int16_t* qc = m->quant[2];",
     "const int16_t* qc = m->quant[3];"),
    ("frame-row-step", MVC, "py += 15 * w;", "py += 14 * w;"),
    ("frame-chroma-row-step", MVC, "pu += 7 * cw;", "pu += 6 * cw;"),
    ("frame-count-bits", MVC, "uint32_t count = mv3_get_bits(&m->bits, 16);",
     "uint32_t count = mv3_get_bits(&m->bits, 15);"),
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
    ("pace-audio", AVC, "if (m->audio) m->audio(m->audioUser, m->file, &c);",
     "if (m->audio && m->decoded) m->audio(m->audioUser, m->file, &c);"),
    ("pace-done", AVC, "&& (uint32_t)m->shown + 1 >= m->info.frames;",
     "&& (uint32_t)m->shown >= m->info.frames;"),
    ("pace-duration", AVC,
     "return (double)m->info.frames * (double)m->info.scale / (double)m->info.rate;",
     "return (double)(m->info.frames - 1) * (double)m->info.scale / (double)m->info.rate;"),
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

# A shortcut IDCT4 takes when a column's or a row's second input is zero:
# the general formulas give x0 at all eight then, so each shortcut is the
# same arithmetic done faster.
EQUIVALENT = {"idct4-col-shortcut", "idct4-row-shortcut"}


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
