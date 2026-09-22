#!/usr/bin/env python3
r"""Check the port's .SBK reader, three ways.

1. Field for field against an independent Python reader. `3DS Files/source/
   sndbank.c` and the reader below were both written from
   docs/formats/sound-bank.md rather than from each other; this runs both
   over every bank and diffs a line per patch, CRC of the audio included.

2. Against the disc. A cross-check between two readers of the *same* file
   only proves they agree -- it says nothing about whether audio_pack.py put
   the right audio in. So --audio decodes the DSPADPCM back to PCM16 in
   Python and compares it against the SPU ADPCM decoded straight out of the
   .MSB, and reports the SNR. That is the only step here that reaches back
   past the pack to the disc.

3. Against corruption. --mutate flips bytes in the header and the records and
   checks the C reader rejects the bank or clamps, rather than handing back a
   patch that points outside the file. A bank comes off an SD card.

Usage:
    python tools/sndbank_check.py <dir-of-SBK>
    python tools/sndbank_check.py <dir-of-SBK> --audio --sound extracted/SOUND
    python tools/sndbank_check.py <dir-of-SBK> --mutate
"""
import argparse
import array
import math
import random
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hostbuild                                        # noqa: E402
from audio_convert import read_bank, decode_adpcm, group, LOOP_FLAG   # noqa: E402
from bhash import bhash                                 # noqa: E402

SOURCES = ["tools/src/sndbank_test.c", "3DS Files/source/sndbank.c"]

MAGIC = 0x314B4253
HEADER_SIZE = 32
PATCH_SIZE = 128
LEAD_IN = 28

NL = chr(10)
CR = chr(13)


def crc(b):
    return zlib.crc32(bytes(b)) & 0xFFFFFFFF


# --------------------------------------------------------------- python reader

def py_read(buf):
    """An .SBK -> the same lines sndbank_test.c prints, or None if rejected."""
    if len(buf) < HEADER_SIZE:
        return None
    magic, ver, count, dataOff, dataSize, bhash_ = struct.unpack_from("<6I", buf, 0)
    if magic != MAGIC or ver != 1:
        return None
    if HEADER_SIZE + count * PATCH_SIZE > dataOff:
        return None
    if dataOff + dataSize > len(buf):
        return None
    name = buf[24:32].split(b"\0")[0].decode("latin-1")

    lines = ["bank %s %08x %u %u" % (name, bhash_, count, dataSize)]

    def rec_at(i):
        r = buf[HEADER_SIZE + i * PATCH_SIZE: HEADER_SIZE + (i + 1) * PATCH_SIZE]
        h, samples, off, dsize = struct.unpack_from("<4I", r, 0x20)
        ch = r[0x36]
        ok = (ch in (1, 2) and off + dsize <= dataSize and dsize % ch == 0
              and (dsize // ch) // 8 == (samples + 13) // 14)
        return r, h, samples, off, dsize, ch, ok

    for i in range(count):
        r, h, samples, off, dsize, ch, ok = rec_at(i)
        if not ok:
            lines.append("patch %u reject" % i)
            continue
        pname = r[0:32].split(b"\0")[0].decode("latin-1")
        rate, vol, fx = struct.unpack_from("<3H", r, 0x30)
        flags = r[0x37]
        # Only the channels the patch actually has are read; the rest of the
        # coefficient block stays zero, the way sndbank_get() leaves it.
        # Mutating those unused bytes must change nothing, and a reference
        # that read them would report that it did.
        coefs = list(struct.unpack_from("<32h", r, 0x38))
        for k in range(ch * 16, 32):
            coefs[k] = 0
        pcm = buf[dataOff + off: dataOff + off + dsize]
        lines.append("patch %u %08x %s %u %u %u %u %u %u %u %u %08x %08x"
                     % (i, h, pname, ch, rate, vol, fx, flags & 1, samples,
                        off, dsize, crc(struct.pack("<32h", *coefs)), crc(pcm)))

        # sndbank_find() takes the FIRST record with this hash and then has to
        # pass sndbank_get(); a duplicate name, or a broken record in front of
        # a good one, has to come out the same on both sides.
        hit = 0
        for k in range(count):
            _, h2, _, off2, _, _, ok2 = rec_at(k)
            if h2 == h:
                hit = 1 if (ok2 and off2 == off) else 0
                break
        per = dsize // ch
        lines.append("find %u %d %u %08x %u %08x"
                     % (i, hit, per, crc(pcm[:per]),
                        per if ch == 2 else 0,
                        crc(pcm[per:]) if ch == 2 else 0))
    return lines


# A mutation can turn a loop into one with no exit. With no deadline here
# that mutant runs until something kills it and stalls the whole pass; the
# harness itself runs in well under a second.
HARNESS_TIMEOUT = 60


def run_c(exe, path):
    # Bytes, not text. A mutated record's name is arbitrary bytes, and letting
    # Python decode the pipe with the console codepage would turn a 0x80 into
    # a euro sign on this machine and a replacement character on another --
    # a diff that is the checker's, not the reader's. latin-1 is the identity.
    try:
        r = subprocess.run([str(exe), str(path)], capture_output=True,
                           timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        sys.exit("sndbank_test hung, killed after %d s" % HARNESS_TIMEOUT)
    if r.returncode not in (0, 1):
        sys.stderr.write(r.stderr.decode("latin-1"))
        sys.exit("sndbank_test failed on %s" % path)
    # Split on newlines only: str.splitlines() also breaks on form feed and
    # vertical tab, and a mutated name byte can be either of those. Then drop
    # the ONE carriage return the C runtime adds ahead of each newline in text
    # mode -- not every CR in the line, because a mutated name byte can be 0x0d
    # too, and stripping that made the reader look like it had lost a character
    # the python model still had.
    lines = r.stdout.decode("latin-1").split(NL)[:-1]
    return [ln[:-1] if ln.endswith(CR) else ln for ln in lines]


def show(line):
    """A line with the unprintable bytes spelled out, for the console."""
    return "".join(c if 32 <= ord(c) < 127 else ".%02x." % ord(c) for c in line)


# ------------------------------------------------- DSPADPCM back to PCM, in python

def dsp_decode(data, coefs, samples):
    """Nintendo DSPADPCM -> PCM16. 14 samples in an 8-byte frame: one header
    byte (scale in the low nibble, coefficient pair in the high) and seven
    data bytes of two 4-bit deltas each, high nibble first."""
    out = array.array("h")
    h1 = h2 = 0
    for i in range(0, len(data), 8):
        head = data[i]
        scale = 1 << (head & 0x0F)
        c = (head >> 4) & 0x07
        f0, f1 = coefs[c * 2], coefs[c * 2 + 1]
        for j in range(7):
            byte = data[i + 1 + j]
            for nib in (byte >> 4, byte & 0x0F):
                if nib > 7:
                    nib -= 16
                s = (nib * scale * 2048 + f0 * h1 + f1 * h2 + 1024) >> 11
                s = 32767 if s > 32767 else (-32768 if s < -32768 else s)
                h2, h1 = h1, s
                out.append(s)
            if len(out) >= samples:
                break
        if len(out) >= samples:
            break
    return out[:samples]


def snr(ref, got):
    n = min(len(ref), len(got))
    se = sig = 0.0
    for i in range(n):
        d = float(ref[i]) - float(got[i])
        se += d * d
        sig += float(ref[i]) * float(ref[i])
    if sig == 0.0:
        return 99.0 if se == 0.0 else -99.0
    return 10.0 * math.log10(sig / se) if se > 0.0 else 99.0


def check_audio(sbk_dir, sound_dir, limit):
    """Decode each .SBK patch back and compare it to the disc's own audio."""
    worst = (999.0, "")
    n = bad = 0
    for msh in sorted(Path(sound_dir).glob("*.MSH")):
        sbk = Path(sbk_dir) / (msh.stem + ".SBK")
        if not sbk.exists():
            print("  no %s" % sbk.name)
            continue
        buf = sbk.read_bytes()
        count, dataOff = struct.unpack_from("<I", buf, 8)[0], struct.unpack_from("<I", buf, 12)[0]
        groups = list(group(read_bank(msh)))
        if len(groups) != count:
            print("  %s: %d patches in the pack, %d in the bank" % (msh.stem, count, len(groups)))
            bad += 1
            continue
        for i, (members, channels) in enumerate(groups):
            if limit and n >= limit:
                return worst, n, bad
            r = buf[HEADER_SIZE + i * PATCH_SIZE: HEADER_SIZE + (i + 1) * PATCH_SIZE]
            h, samples, off, dsize = struct.unpack_from("<4I", r, 0x20)
            ch = r[0x36]
            looping = r[0x37] & 1
            coefs = struct.unpack_from("<32h", r, 0x38)
            if ch != channels or h != bhash(members[0]["name"]):
                print("  %s/%s: pack says %dch %08x, bank says %dch %08x"
                      % (msh.stem, members[0]["name"], ch, h, channels,
                         bhash(members[0]["name"])))
                bad += 1
                continue
            per = dsize // ch
            for c, m in enumerate(members):
                ref, _, _ = decode_adpcm(m["data"])
                if looping:
                    ref = ref[LEAD_IN:]
                got = dsp_decode(buf[dataOff + off + c * per: dataOff + off + (c + 1) * per],
                                 coefs[c * 16:(c + 1) * 16], samples)
                s = snr(ref[:samples], got)
                n += 1
                if s < worst[0]:
                    worst = (s, "%s/%s ch%d" % (msh.stem, members[0]["name"], c))
                if s < 15.0:
                    print("  %s/%s ch%d: only %.1f dB" % (msh.stem, members[0]["name"], c, s))
                    bad += 1
    return worst, n, bad


# ------------------------------------------------------------------- mutation

def check_mutations(exe, paths, rounds, seed=1):
    """Flip bytes in the header and the record table and make sure the C
    reader and the Python one agree about what is still readable. A pack that
    quietly returns a patch pointing past the blob is the failure that would
    reach the DSP as a wall of noise, so agreeing on `reject` matters as much
    as agreeing on a CRC."""
    # Round-robin over every bank rather than hammering one, so the
    # two-channel path in COMMON is fuzzed as hard as the mono ones.
    srcs = [bytearray(Path(p).read_bytes()) for p in paths]
    rnd = random.Random(seed)
    disagree = rejected = 0
    with tempfile.TemporaryDirectory() as tmp:
        m = Path(tmp) / "m.SBK"
        for r in range(rounds):
            buf = srcs[r % len(srcs)]
            count = struct.unpack_from("<I", buf, 8)[0]
            top = min(len(buf), HEADER_SIZE + count * PATCH_SIZE)
            b = bytearray(buf)
            for _ in range(rnd.randint(1, 3)):
                b[rnd.randrange(top)] ^= 1 << rnd.randrange(8)
            m.write_bytes(b)
            c = run_c(exe, m)
            p = py_read(bytes(b))
            p = ["reject"] if p is None else p
            if c != p:
                disagree += 1
                if disagree <= 3:
                    for a, e in zip(c, p):
                        if a != e:
                            print("    C  %s" % show(a))
                            print("    py %s" % show(e))
                            break
            if c[:1] == ["reject"] or any(l.endswith("reject") for l in c):
                rejected += 1
    return disagree, rejected


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sbk_dir", help="a directory of .SBK files")
    ap.add_argument("--audio", action="store_true",
                    help="decode the DSPADPCM back and compare it to the disc")
    ap.add_argument("--sound", default="extracted/SOUND",
                    help="where the disc's .MSH/.MSB live (for --audio)")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop --audio after this many channels")
    ap.add_argument("--mutate", type=int, nargs="?", const=2000, default=0,
                    metavar="N", help="also flip bytes in one bank N times")
    a = ap.parse_args()

    banks = sorted(Path(a.sbk_dir).glob("*.SBK"))
    if not banks:
        sys.exit("no .SBK under %s" % a.sbk_dir)

    rc = 0
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="sndbank_test")
        lines = differ = 0
        for b in banks:
            c = run_c(exe, b)
            p = py_read(b.read_bytes())
            p = ["reject"] if p is None else p
            lines += max(len(c), len(p))
            for i in range(max(len(c), len(p))):
                x = c[i] if i < len(c) else "<missing>"
                y = p[i] if i < len(p) else "<missing>"
                if x != y:
                    differ += 1
                    if differ <= 10:
                        print("%s line %d:" % (b.name, i))
                        print("  C  %s" % show(x))
                        print("  py %s" % show(y))
        print("%d banks, %d lines, %d differ" % (len(banks), lines, differ))
        rc |= 1 if differ else 0

        if a.mutate:
            d, rej = check_mutations(exe, banks, a.mutate)
            print("%d mutations over %d banks, %d rejected, %d disagree"
                  % (a.mutate, len(banks), rej, d))
            rc |= 1 if d else 0

    if a.audio:
        worst, n, bad = check_audio(a.sbk_dir, a.sound, a.limit)
        print("%d channels decoded back, worst SNR %.2f dB (%s), %d bad"
              % (n, worst[0], worst[1], bad))
        rc |= 1 if bad else 0
    return rc


if __name__ == "__main__":
    sys.exit(main())
