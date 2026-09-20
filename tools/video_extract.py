#!/usr/bin/env python3
r"""Decode a HP2 movie (`MOVIES\*.AVI`) into PNG frames and a WAV soundtrack.

The movies on this disc are **not** VP6/SCHl like NFSU2's. They are plain
RIFF/AVI holding EA's own `MV30` codec, and the decoder ships in the ELF as
`MV3Codec` + `DCTImage` + `Huffman`. Rather than transcribe ~2,000
instructions of fixed-point IDCT into Python and hope, this runs the shipped
decoder under `tools/mipsemu.py` and reads the pixels back out. It is slow
(~15 s per frame) but it is the game's own output, bit for bit.

The container
-------------
Standard RIFF/AVI. One video stream and, if present, one audio stream:

    LIST hdrl
        LIST strl   strh (fccType 'vids', fccHandler 'MV30') + strf (BITMAPINFOHEADER)
        LIST strl   strh (fccType 'auds')                    + strf (WAVEFORMATEX)
    LIST movi
        00db / 00dc   one compressed MV3 frame  ('db' = key, 'dc' = delta)
        01wb          audio, raw PCM

`EALOGO_EN.AVI`, the only movie on the disc, is 512x256 at 30 fps: one `00db`
keyframe, 89 `00dc` deltas, and a single 192 KB `01wb` blob of unsigned 8-bit
mono PCM at 65,470 Hz (exactly 3.0 s, matching the 90 frames).

The codec
---------
Documented in full in `docs/formats/mv3-video.md`. The short version, as the
decoder sees it:

    src[0]      s8   intra quality (IJG scale), 90 in this movie
    src[1]      s8   delta added to it for inter blocks, -4 here
    src[2]      u16  big-endian; zero picks the simple layout (a plain DCT
                     type array then the Huffman stream), non-zero the one
                     that also carries the skip bit-planes and the motion
                     vectors. The keyframe here is 0 and every delta 0x0100.
    src[4]      ...  pCompData

JPEG-like: 16x16 macroblocks, 4:2:0, six 8x8 blocks each (4 Y, 1 U, 1 V),
zigzag, AAN prescale, a Chen-Wang integer IDCT, signed exp-Golomb
coefficients through a 9-bit LUT, and per-macroblock copy/skip bit-planes
driving motion compensation off the previous frame. Frames are therefore
stateful: a delta can only be decoded after every frame before it.

`MV3Codec::ConvertImageToRGBA` (field +644) is set here so the codec does its
own BT.601 full-range YUV->RGB through its 768-byte clamp table, and the
output BITMAPINFOHEADER is given a *negative* `biHeight`, which is what tells
`ToImage32` to write the rows top-down instead of bottom-up.

Usage:
    python tools/video_extract.py extracted/MOVIES/INTRO/EALOGO_EN.AVI --list
    python tools/video_extract.py extracted/MOVIES/INTRO/EALOGO_EN.AVI out/
    python tools/video_extract.py extracted/MOVIES/INTRO/EALOGO_EN.AVI out/ --frames 6
    python tools/video_extract.py extracted/MOVIES/INTRO/EALOGO_EN.AVI out/ --audio-only
"""
import argparse
import os
import struct
import sys
import time
import wave
import zlib
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BI_SIZE = 40
MV3CODEC_SIZE = 648                 # sizeof(MV3Codec), from the .mdebug types
CONVERT_TO_RGBA = 644               # MV3Codec::ConvertImageToRGBA


# ---- RIFF/AVI ------------------------------------------------------------

def _chunks(buf, start, end):
    """Walk the RIFF chunks in buf[start:end], yielding
    (tag, list_form_or_None, body_offset, body_end)."""
    off = start
    while off + 8 <= end:
        tag = bytes(buf[off:off + 4])
        size = struct.unpack_from("<I", buf, off + 4)[0]
        body = off + 8
        stop = min(body + size, end)
        if tag in (b"LIST", b"RIFF"):
            yield tag, bytes(buf[body:body + 4]), body + 4, stop
        else:
            yield tag, None, body, stop
        off = body + size + (size & 1)      # chunks are word-aligned


def _strl(buf, start, end):
    """Parse one `strl` list into a stream dict."""
    st = {"strf": b""}
    for tag, _form, body, stop in _chunks(buf, start, end):
        if tag == b"strh":
            (st["type"], st["handler"], st["flags"], _pri, _lang, _init,
             st["scale"], st["rate"], st["start"], st["length"],
             _bufsz, _qual, st["sample_size"]) = struct.unpack_from(
                "<4s4sIHHIIIIIIII", buf, body)
        elif tag == b"strf":
            st["strf"] = bytes(buf[body:stop])
    if st.get("type") == b"vids" and len(st["strf"]) >= BI_SIZE:
        (_size, st["width"], st["height"], _planes, st["bits"],
         st["compression"]) = struct.unpack_from("<I2iHH4s", st["strf"], 0)
    elif st.get("type") == b"auds" and len(st["strf"]) >= 16:
        (st["format"], st["channels"], st["sample_rate"], _bps,
         st["block_align"], st["bits"]) = struct.unpack_from(
            "<HHIIHH", st["strf"], 0)
    return st


def read_avi(path):
    """Return (streams, packets) for an AVI file. A packet is a dict with the
    stream number, the two-letter kind ('db'/'dc'/'wb'), and its payload."""
    buf = Path(path).read_bytes()
    if buf[:4] != b"RIFF" or buf[8:12] != b"AVI ":
        raise ValueError("%s is not a RIFF/AVI file" % path)
    top = 8 + struct.unpack_from("<I", buf, 4)[0]
    streams, packets = [], []
    for tag, form, body, stop in _chunks(buf, 12, min(top, len(buf))):
        if tag != b"LIST":
            continue
        if form == b"hdrl":
            for t2, f2, b2, e2 in _chunks(buf, body, stop):
                if t2 == b"LIST" and f2 == b"strl":
                    streams.append(_strl(buf, b2, e2))
        elif form == b"movi":
            for t2, _f2, b2, e2 in _chunks(buf, body, stop):
                if len(t2) == 4 and t2[:2].isdigit():
                    packets.append({"stream": int(t2[:2]),
                                    "kind": t2[2:].decode("ascii", "replace"),
                                    "offset": b2,
                                    "data": bytes(buf[b2:e2])})
    return streams, packets


def stream_of(streams, kind):
    for i, s in enumerate(streams):
        if s.get("type") == kind:
            return i, s
    return None, None


# ---- the shipped MV3 decoder, driven under the emulator -------------------

class Mv3Decoder(object):
    """`MV3Codec` out of NFSHP2.ELF, executed rather than reimplemented."""

    CTOR = "__8MV3Codec"
    BEGIN = "BeginDecompress__8MV3CodecP10BitmapInfoT1"
    FRAME = "DecompressFrameShared__8MV3CodecUiP16BitmapInfoHeaderPUcT2T3"
    END = "EndDecompress__8MV3Codec"

    def __init__(self, width, height, fourcc=b"MV30", elf=None):
        from mipsemu import Emu
        self.e = Emu(elf) if elf else Emu()
        self.e.stub_bware()
        # `Codec::OffsetClamp` is only ever written by a static initialiser,
        # and the boot code that would run it is not on this call path -- so
        # the YUV->RGB clamp table stays a null pointer unless we run them.
        self.e.run_ctors(r"_5Codec")

        self.w, self.h = width, abs(height)
        self.in_hdr = self.e.alloc(64)
        self.out_hdr = self.e.alloc(64)
        self._bih(self.in_hdr, self.w, self.h, 24, fourcc)
        # a negative biHeight is what asks ToImage32 for top-down rows
        self._bih(self.out_hdr, self.w, -self.h, 32, b"\0\0\0\0")

        self.obj = self.e.alloc(MV3CODEC_SIZE)
        self.e.call(self.CTOR, self.obj)
        if self.e.call(self.BEGIN, self.obj, self.in_hdr, self.out_hdr) != 0:
            raise RuntimeError("BeginDecompress rejected %dx%d %s"
                               % (self.w, self.h, fourcc))
        self.e.put32(self.obj + CONVERT_TO_RGBA, 1)

        self.dst = self.e.alloc(self.w * self.h * 4)
        self._src, self._src_cap = 0, 0
        self.instrs = 0

    def _bih(self, addr, w, h, bits, compression):
        self.e.write(addr, struct.pack("<I2i2H4sI2i2I", BI_SIZE, w, h, 1, bits,
                                       compression, abs(w * h) * bits // 8,
                                       0, 0, 0, 0))

    def decode(self, data):
        """Decode one compressed frame; returns w*h*4 top-down RGBA8888."""
        if len(data) > self._src_cap:
            self._src_cap = max(len(data), 64 << 10)
            self._src = self.e.alloc(self._src_cap)
        self.e.write(self._src, data)
        self.e.call(self.FRAME, self.obj, 0, self.in_hdr, self._src,
                    self.out_hdr, self.dst)
        self.instrs = self.e.icount
        return self.e.read(self.dst, self.w * self.h * 4)

    def close(self):
        self.e.call(self.END, self.obj)


# ---- output --------------------------------------------------------------

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


def write_wav(path, st, pcm):
    """Write the movie's audio out as-is. AVI 8-bit PCM is unsigned and so is
    WAV's, and 16-bit is signed little-endian in both, so no conversion."""
    bits = st.get("bits") or 8
    w = wave.open(str(path), "wb")
    try:
        w.setnchannels(st.get("channels") or 1)
        w.setsampwidth(max(1, bits // 8))
        w.setframerate(st.get("sample_rate") or 22050)
        w.writeframes(pcm)
    finally:
        w.close()


def fps_of(st):
    return (st.get("rate") or 0) / float(st.get("scale") or 1)


# ---- driver --------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("avi", help=r"path to a MOVIES\*.AVI")
    ap.add_argument("out_dir", nargs="?")
    ap.add_argument("--list", action="store_true",
                    help="print the stream and frame tables only, decoding nothing")
    ap.add_argument("--frames", type=int, metavar="N",
                    help="stop after N video frames (deltas need every frame "
                         "before them, so this can only cut from the end)")
    ap.add_argument("--audio-only", action="store_true",
                    help="write the soundtrack and skip the ~15 s/frame decode")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--raw", action="store_true",
                    help="also write each frame's compressed bytes next to its PNG")
    ap.add_argument("--elf", help="path to NFSHP2.ELF (default: the one in PS2 Files/)")
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args()
    if not a.list and not a.out_dir:
        ap.error("give an output directory, or --list")

    streams, packets = read_avi(a.avi)
    vidx, vid = stream_of(streams, b"vids")
    aidx, aud = stream_of(streams, b"auds")
    if vid is None:
        raise SystemExit("%s has no video stream" % a.avi)
    video = [p for p in packets if p["stream"] == vidx and p["kind"] != "wb"]
    audio = b"".join(p["data"] for p in packets
                     if aud is not None and p["stream"] == aidx)
    stem = Path(a.avi).stem

    if a.list:
        print("== %s ==" % stem)
        print("video  stream %d  %dx%d  %s  %.2f fps  %d frames"
              % (vidx, vid["width"], vid["height"],
                 vid["compression"].decode("ascii", "replace"),
                 fps_of(vid), len(video)))
        if aud is not None:
            print("audio  stream %d  %d ch  %d Hz  %d-bit  format 0x%04x  %d bytes"
                  % (aidx, aud["channels"], aud["sample_rate"], aud["bits"],
                     aud["format"], len(audio)))
        print()
        print("%-5s %-4s %-6s %9s %8s %5s %5s %s"
              % ("#", "tag", "type", "offset", "bytes", "qual", "dq", "flags"))
        for i, p in enumerate(video):
            d = p["data"]
            print("%-5d %02d%s %-6s %9d %8d %5d %5d %04x"
                  % (i, p["stream"], p["kind"],
                     "key" if p["kind"] == "db" else "delta",
                     p["offset"], len(d),
                     struct.unpack_from("b", d, 0)[0],
                     struct.unpack_from("b", d, 1)[0],
                     struct.unpack_from(">H", d, 2)[0]))
        return

    out = Path(a.out_dir) / stem
    out.mkdir(parents=True, exist_ok=True)

    if audio and not a.no_audio:
        write_wav(out / (stem + ".wav"), aud, audio)
        if not a.quiet:
            secs = len(audio) / float((aud["sample_rate"] or 1)
                                      * max(1, aud["bits"] // 8)
                                      * (aud["channels"] or 1))
            print("wrote %s.wav  %d bytes, %.2f s" % (stem, len(audio), secs))
    if a.audio_only:
        return

    want = len(video) if a.frames is None else min(a.frames, len(video))
    w, h = vid["width"], abs(vid["height"])
    dec = Mv3Decoder(w, h, vid["compression"], elf=a.elf)
    manifest = [("index", "tag", "type", "offset", "compressed_bytes",
                 "quality", "inter_delta", "instructions", "seconds", "file")]

    for i, p in enumerate(video[:want]):
        t0 = time.time()
        rgba = dec.decode(p["data"])
        dt = time.time() - t0
        name = "%s_%04d.png" % (stem, i)
        write_png(out / name, w, h, rgba)
        if a.raw:
            (out / ("%s_%04d.mv3" % (stem, i))).write_bytes(p["data"])
        manifest.append((i, "%02d%s" % (p["stream"], p["kind"]),
                         "key" if p["kind"] == "db" else "delta",
                         p["offset"], len(p["data"]),
                         struct.unpack_from("b", p["data"], 0)[0],
                         struct.unpack_from("b", p["data"], 1)[0],
                         dec.instrs, "%.1f" % dt, name))
        if not a.quiet:
            sys.stderr.write("\rframe %d/%d  %.1f s  %.1fM instrs   "
                             % (i + 1, want, dt, dec.instrs / 1e6))
            sys.stderr.flush()
    dec.close()
    if not a.quiet:
        sys.stderr.write("\r" + " " * 48 + "\r")

    with open(out / "frames.csv", "w", encoding="utf-8", newline="\n") as f:
        for row in manifest:
            f.write(",".join(str(c) for c in row) + "\n")
    print("wrote %d PNGs (%dx%d, %.2f fps) to %s"
          % (want, w, h, fps_of(vid), out))


if __name__ == "__main__":
    main()
