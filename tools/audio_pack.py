#!/usr/bin/env python3
"""Build the port's 3DS sound banks from the disc's SOUND/*.MSH + .MSB pairs.

The PS2 kept its samples as SPU ADPCM in SPU RAM and let the SPU2 decode
them; the 3DS has its own DSP, which reads Nintendo DSPADPCM and nothing
else. Both are 4 bits a sample, so this is a transcode at the same size
rather than a re-encode at a worse one -- the disc's 6.6 MB of .MSB comes
out as 6.6 MB of .SBK. Decoding to PCM16 instead would have cost 23 MB and
the ARM11 cycles to mix it.

The path is SPU ADPCM -> PCM16 (audio_convert.py's decoder, which is the
disc format written up in docs/formats/sound-bank.md) -> DSPADPCM
(tools/src/dspenc.c, shipped built as tools/bin/dspenc.exe). It is lossy
once, in the second step; --report prints the per-patch SNR so that loss
is a number rather than a hope.

Stereo pairs are joined the way the engine sees them: the 30 records with
LoopChannel bit 4 set repeat the previous record's name and are its right
channel, so they become one two-channel patch under one name, which is
what bSnd_GetPatchChannels() returns 2 for.

Looping patches lose their lead-in. Every one of the disc's 334 looping
patches loops from sample 28 to its end -- the SPU convention of a silent
first frame with the loop-start flag on the second -- so dropping those 28
samples makes the whole buffer the loop body, which is the only shape ndsp
can loop without a second queued waveBuf.

Format: docs/formats/sound-bank.md, section "The port's .SBK".

Usage:
    python tools/audio_pack.py extracted/SOUND <data>/SOUND
    python tools/audio_pack.py extracted/SOUND/COMMON.MSH out/ --report

The output goes next to the .MSH/.MSB it was built from, inside the data
directory gamedata.c resolves -- the same arrangement movie_bake.py uses for
.M3V. Nothing on the disc is overwritten; .SBK is a new extension.
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from audio_convert import read_bank, decode_adpcm, group, LOOP_FLAG   # noqa: E402
from bhash import bhash                                               # noqa: E402

MAGIC = 0x314B4253          # 'SBK1' little-endian
VERSION = 1
HEADER_SIZE = 32
PATCH_SIZE = 128
FRAME_SAMPLES = 14          # DSPADPCM: 14 samples in 8 bytes
LEAD_IN = 28                # the SPU lead-in frame every looping patch carries

DSPENC = HERE / "bin" / ("dspenc.exe" if os.name == "nt" else "dspenc")


def encode_dspadpcm(tracks, rate, tmpdir, verify=False):
    """PCM16 channels -> (coefs per channel, ADPCM bytes per channel, snr).

    dspenc pads its last block out with silence, which would put a gap in
    the middle of a loop, so the block is sized to hold the whole patch in
    one. Every patch here is a whole number of 28-sample SPU frames and 14
    divides 28, so in practice that padding is zero samples wide.
    """
    n = len(tracks[0])
    ch = len(tracks)
    wav = Path(tmpdir) / "p.wav"
    out = Path(tmpdir) / "p.dspm"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        if ch == 2:
            lb, rb = tracks[0].tobytes(), tracks[1].tobytes()
            il = bytearray(n * 4)
            il[0::4] = lb[0::2]
            il[1::4] = lb[1::2]
            il[2::4] = rb[0::2]
            il[3::4] = rb[1::2]
            w.writeframes(bytes(il))
        else:
            w.writeframes(tracks[0].tobytes())

    frames = max((n + FRAME_SAMPLES - 1) // FRAME_SAMPLES, 1)
    cmd = [str(DSPENC), str(wav), "-o", str(out), "--block", str(frames)]
    if verify:
        cmd.append("--verify")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("dspenc failed: " + r.stderr.strip())
    snr = [float(l.rsplit("=", 1)[1].split()[0])
           for l in r.stderr.splitlines() if "round-trip SNR" in l]

    d = out.read_bytes()
    magic, ver, _, dch, dframes, _, blocks, off = struct.unpack_from("<4s7I", d, 0)
    if magic != b"DSPM" or ver != 1 or blocks != 1 or dch != ch or dframes != n:
        raise SystemExit("dspenc wrote an unexpected container: %r"
                         % ((magic, ver, blocks, dch, dframes, n),))
    coefs = [struct.unpack_from("<16h", d, 0x28 + c * 32) for c in range(ch)]
    per = frames * 8
    data = [d[off + c * per: off + (c + 1) * per] for c in range(ch)]
    return coefs, data, snr


def build_bank(msh, tmpdir, verify=False):
    """One .MSH/.MSB pair -> (bank name, .SBK bytes, per-patch report rows)."""
    name = Path(msh).stem
    recs, blob, report = [], bytearray(), []

    for members, channels in group(read_bank(msh)):
        head = members[0]
        looping = bool(head["loop_channel"] & LOOP_FLAG)
        # Pan and ADSR are 0 in all 469 records on the disc, so .SBK leaves
        # them out and the port substitutes BSND_PATCH_PAN and the driver's
        # own 0x1a00000a default. A bank that broke that would play centred
        # and with the wrong envelope and nothing would say so, so say so
        # here instead.
        for m in members:
            if m["pan"] or m.get("adsr", 0):
                raise SystemExit(
                    "%s/%s carries Pan=%d ADSR=%08x; .SBK has nowhere to put "
                    "them -- see docs/formats/sound-driver.md"
                    % (Path(msh).stem, m["name"], m["pan"], m.get("adsr", 0)))
        tracks = []
        for m in members:
            pcm, _, _ = decode_adpcm(m["data"])
            tracks.append(pcm[LEAD_IN:] if looping else pcm)
        n = min(len(t) for t in tracks)
        tracks = [t[:n] for t in tracks]
        if n == 0:
            report.append((head["name"], channels, 0, []))
            continue

        coefs, data, snr = encode_dspadpcm(tracks, head["pitch"], tmpdir, verify)
        per = len(data[0])
        rec = bytearray(PATCH_SIZE)
        rec[0:32] = head["name"].encode("latin-1", "replace")[:31].ljust(32, b"\0")
        struct.pack_into("<4I", rec, 0x20, bhash(head["name"]), n,
                         len(blob), per * channels)
        struct.pack_into("<3H2B", rec, 0x30, head["pitch"], head["volume"],
                         head["effect_volume"], channels, 1 if looping else 0)
        for c in range(channels):
            struct.pack_into("<16h", rec, 0x38 + c * 32, *coefs[c])
        recs.append(bytes(rec))
        for c in range(channels):
            blob += data[c]
        report.append((head["name"], channels, n, snr))

    data_off = HEADER_SIZE + PATCH_SIZE * len(recs)
    out = bytearray(data_off)
    struct.pack_into("<6I", out, 0, MAGIC, VERSION, len(recs), data_off,
                     len(blob), bhash(name))
    out[0x18:0x20] = name.encode("latin-1", "replace")[:7].ljust(8, b"\0")
    for i, r in enumerate(recs):
        out[HEADER_SIZE + i * PATCH_SIZE: HEADER_SIZE + (i + 1) * PATCH_SIZE] = r
    return name, bytes(out) + bytes(blob), report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="a SOUND/ directory, or one .MSH inside it")
    ap.add_argument("out_dir")
    ap.add_argument("--report", action="store_true",
                    help="run dspenc --verify and print the per-patch SNR")
    a = ap.parse_args()

    src = Path(a.src)
    mshs = sorted(src.glob("*.MSH")) if src.is_dir() else [src]
    if not mshs:
        sys.exit("no .MSH under %s" % src)
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    total_p = total_b = 0
    worst = (999.0, "")
    with tempfile.TemporaryDirectory() as tmp:
        for msh in mshs:
            name, blob, report = build_bank(msh, tmp, a.report)
            (out_dir / (name + ".SBK")).write_bytes(blob)
            total_p += len(report)
            total_b += len(blob)
            if a.report:
                for pname, ch, n, snr in report:
                    for c, s in enumerate(snr):
                        if s < worst[0]:
                            worst = (s, "%s/%s ch%d" % (name, pname, c))
                    print("  %-10s %-24s %dch %7d  %s"
                          % (name, pname, ch, n,
                             " ".join("%.1f dB" % s for s in snr)))
            print("%-12s %3d patches, %8.1f KB"
                  % (name, len(report), len(blob) / 1024.0))
    print("%d banks, %d patches, %.2f MB" % (len(mshs), total_p, total_b / 1048576.0))
    if a.report:
        print("worst round-trip SNR: %.2f dB (%s)" % worst)


if __name__ == "__main__":
    main()
