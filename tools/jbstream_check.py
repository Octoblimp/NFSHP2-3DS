#!/usr/bin/env python3
"""Holds jbstream.c's decoder to audio_convert.py's over the disc's tunes.

A jukebox tune is stereo SPU ADPCM in 0x8000-byte blocks, left then right,
and the stream reads it a pair of blocks at a time (jbstream.h). Decoding a
whole tune in Python takes minutes, so each check is a short tune made of
real pairs: the first two of a tune off the retail cartridge and its last,
which carries the end -- flag 1 in each channel, then 7. The history runs
across the joins in both decoders alike.

The C side runs the stream's own loop (tools/src/jbstream_test.c) at several
step sizes; the Python side decodes each channel's blocks end to end. They
must agree sample for sample, and stop at the same place.

  python tools/jbstream_check.py            # tunes 5 (the menu's), 12, 0
  python tools/jbstream_check.py --tune 7
"""
import argparse
import array
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio_convert                    # noqa: E402
import hostbuild                        # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RETAIL_JBC = ROOT / "extracted-retail" / "SOUND" / "JUKEBOXM.JBC"
SOURCES = ["tools/src/jbstream_test.c", "3DS Files/source/jbstream.c"]
BLOCK = 0x8000
PAIR = 2 * BLOCK
STEPS = (128, 7, 2048, 1)


def tunes(data):
    head = struct.unpack_from("<8I", data, 0)
    at, out = 32, []
    for _c in range(head[3]):
        n = struct.unpack_from("<I", data, at)[0]
        at += 64
        for _t in range(n):
            off, size, sync = struct.unpack_from("<3I", data, at)
            name = data[at + 12:at + 96].split(b"\0")[0].decode("latin-1")
            out.append((off, size, sync, name))
            at += 96
    return out


def sample(data, tune, pairs):
    """The tune's chosen pairs, one after another, as a stream of its own."""
    off, size, _sync, _name = tune
    base = off + 48
    return b"".join(data[base + p * PAIR:base + (p + 1) * PAIR]
                    for p in pairs)


def reference(stream):
    stream = stream[:len(stream) // PAIR * PAIR]     # a part pair is not read
    left =b"".join(stream[i:i + BLOCK] for i in range(0, len(stream), PAIR))
    right = b"".join(stream[i + BLOCK:i + PAIR]
                     for i in range(0, len(stream), PAIR))
    lpcm = audio_convert.decode_adpcm(left)[0]
    rpcm = audio_convert.decode_adpcm(right)[0]
    return lpcm, rpcm


def check(exe, tmp, label, stream, size):
    src = Path(tmp) / "tune.bin"
    src.write_bytes(stream)
    lref, rref = reference(stream)
    bad = 0
    for step in STEPS:
        pcm = Path(tmp) / "out.pcm"
        r = subprocess.run([str(exe), str(src), str(pcm), "0", str(size),
                            str(step)], capture_output=True, text=True,
                           timeout=120)
        if r.returncode:
            print("  %s step %d: harness exited %d %s" % (
                label, step, r.returncode, r.stderr[:500]))
            bad += 1
            continue
        got = array.array("h")
        got.frombytes(pcm.read_bytes())
        lgot, rgot = got[0::2], got[1::2]
        ok = lgot == lref and rgot == rref
        print("  %-28s step %4d: %s  %s" % (
            label, step, "same" if ok else "DIFFERS", r.stdout.strip()))
        if not ok:
            bad += 1
            n = min(len(lgot), len(lref))
            first = next((i for i in range(n)
                          if lgot[i] != lref[i] or rgot[i] != rref[i]), n)
            print("    %d/%d samples against %d/%d, first difference at %d"
                  % (len(lgot), len(rgot), len(lref), len(rref), first))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tune", type=int, action="append")
    args = ap.parse_args()
    data = RETAIL_JBC.read_bytes()
    all_tunes = tunes(data)
    picks = args.tune or [5, 12, 0]
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="jbstream_test")
        for i in picks:
            t = all_tunes[i]
            last = (t[1] - 48) // PAIR - 1
            stream = sample(data, t, [0, 1, last])
            # The index's size runs 48 bytes past the tune, as the sample
            # is asked for it.
            bad += check(exe, tmp, "%d %s" % (i, t[3][:20]), stream,
                         len(stream) + 48)
        # No end: the pairs run out, and a part pair is not read.
        t = all_tunes[picks[0]]
        stream = sample(data, t, [0, 1, 2])
        bad += check(exe, tmp, "no end, whole pairs", stream, len(stream))
        bad += check(exe, tmp, "no end, part pair", stream + stream[:1000],
                     len(stream) + 1000)
    print("%d differ" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
