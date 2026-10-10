#!/usr/bin/env python3
"""Cross-check bsnd.c's streams against the retail image, SLES_507.31,
and bsndstream.c's decoder against audio_convert.py's.

**The model** is retail's bSnd_VoicePlay (0x002611c0) run in
retail_model.RetailEmu: the "_STREAM" bank's mono path, the "_CHAIN"
queue, and PlayChain (0x00262848), which plays the queue when a
"_STREAM" part ends it; and 0x00263090, which asks a voice's stream
whether it is still going. bStrNCmp, bStrNCpy, bStrLen, memset,
GetPanFromAzimuth, GetAzimuthFromPan, GetVolumesFromPan (and the pan
table, from the image), SOUND_HzToSPU, SOUND_FindFreeMonoStream,
SOUND_FindFreeSPUChannels, GetAttack and GetRelease are the image's
own. The harness (tools/src/bsndstream_test.c) runs bsnd.c's
bsnd_voice_play_at and bsnd_stream_active on a 48-voice driver.

**The fakes.** Retail's IOP calls are stubs: CreateMultistreamFileInfo
(a stream's file and its start), SOUND_SetFileOffsetAndPlaySize (a
part of it), SOUND_PlayStream (the first file, the stream, the voice,
the two volumes and the SPU pitch; it keys the voice on, as
0x0026a920 does), SOUND_ChainStreams (the rest), and bSnd_Flush, at
which the model prints the stream it was handed: each part as the
file's path, its start, and the part's offset and size when it was
given one -- what the port's sink is handed. The SPU pitch is printed
as the Hz it comes back to. StopStream, SetChannelEffectOff,
StreamDisableKeyOn and the debug printf have no part in the port and
print nothing. SOUND_GetStreamInfo answers Active (byte 18) from the
model's stream: on from PlayStream until the script drains it. The
port's sink answers `playing` the same way for the channel its last
stream went to -- which is the one bsnd_stream_active asks for every
voice with a StreamChannel, as there is one mono stream.

**Not compared:** the "_STREAMS" bank (the stereo pair, which the port
plays on its own channel in jbstream.c, and answers BSND_NO_PATCH
for); "_MOVIE" as a "_STREAM" patch (the movies' sound, which the
port's movie player does itself); voices past 47, which retail writes
past its table for; and rates of 2^20 Hz and more, where retail's
HzToSPU overflows its 32-bit shift and the port's does not; and a
full queue, which a chain leaves when it finds no voice (its count
stays at 8): retail's next part goes past the queue, and PlayChain
copies nine entries into a frame of eight, where the port drops a
"_CHAIN" part and lets a "_STREAM" one take the eighth's place. So
the random runs free every voice each 15 ops. The port keeps no bank
and patch names on its voices, nor ProVolL/R.

**The decoder** check runs bss_decode over windows of retail's
SOUND/SPEECH/ENGLISHDAT.PCK and over made-up frames (every predictor,
the end flags 1 and 7), handed it in random runs of frames so the
history is carried across calls, and holds the PCM to
audio_convert.decode_adpcm's.

    python tools/bsndstream_check.py
    python tools/bsndstream_check.py --mutate [--only a,b]
    python tools/bsndstream_check.py --dump out/bsndstream
"""
import argparse
import array
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audio_convert                    # noqa: E402
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/bsndstream_test.c"
BSND = "3DS Files/source/bsnd.c"
BSS = "3DS Files/source/bsndstream.c"
SOURCES = [HARNESS, BSND, "3DS Files/source/sndbank.c",
           "3DS Files/source/bsndtab.c", BSS]
HARNESS_TIMEOUT = 60
LIMIT = 2000000
DAT = ROOT / "extracted-retail" / "SOUND" / "SPEECH" / "ENGLISHDAT.PCK"

GP = retail_model.RETAIL_GP
F_PLAY = 0x002611c0
F_ACTIVE = 0x00263090

VOICES = 0x00321580                 # SOUND_VOICE_INFO[48], 80 bytes each
LOCKS = 0x00322490                  # bSnd_LockChannels' table
KEYS = 0x00322a40                   # SOUND_SPUKeyStatus
LOAD_PATH = 0x00322710
QUEUE = 0x003353b8                  # the "_CHAIN" queue, 52 bytes each
CHAIN_N = GP - 14344
STEREO_N = GP - 14398
MONO_N = GP - 14399
FILES = GP - 14304                  # the file table, 272 bytes each
MODE = GP - 14364
NOKEYON = GP - 14286
NVOICE = 48
QMAX = 8


def spu_to_hz(spu):
    return (spu * 48000) >> 12


class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        e.write(VOICES, bytes(80 * NVOICE))
        for v in range(NVOICE):
            e.mem[VOICES + 80 * v + 2] = 0xff        # StreamChannel -1
        e.write(LOCKS, bytes(NVOICE))
        e.write(KEYS, bytes(NVOICE))
        e.write(LOAD_PATH, bytes(256))
        e.write(QUEUE, bytes(52 * QMAX))
        e.mem[CHAIN_N:CHAIN_N + 2] = b"\0\0"
        e.mem[STEREO_N] = 1
        e.mem[MONO_N] = 1
        e.mem[MODE] = 2                              # bSnd_SetStereo
        e.mem[NOKEYON] = 0
        files = e.alloc(272 * 16, 16)
        e.write(files, bytes(272 * 16))
        e.put32(FILES, files)
        self.files = {}                 # file id -> (path, start)
        self.offsets = {}               # file id -> (offset, size)
        self.pending = None             # PlayStream's, until the Flush
        self.chained = []
        self.active = set()             # the streams GetStreamInfo calls on

        e.stub(0x00269e10, lambda em: 0)             # bSnd_Low_Level_Printf
        e.stub(0x00268da0, self.create_file)
        e.stub(0x0026d788, self.set_offset)
        e.stub(0x0026b328, lambda em: 0)             # SOUND_StopStream
        e.stub(0x0026a798, self.play_stream)
        e.stub(0x0026d020, self.chain_streams)
        e.stub(0x0026cf00, lambda em: 0)             # SetChannelEffectOff
        e.stub(0x0025f0f0, self.flush)
        e.stub(0x0026e4a0, self.unexpected("StreamDisableKeyOn"))
        e.stub(0x0026dce0, self.unexpected("SetStreamParent"))
        e.stub(0x0026ddb0, self.unexpected("SetStreamChild"))
        e.stub(0x00266fb0, self.patch_id)
        e.stub(0x0026e5b0, self.stream_info)

    def emit(self, s):
        self.out.append(s)

    def cstr(self, a, n=300):
        b = bytearray()
        mem = self.e.mem
        while len(b) < n and mem[a]:
            b.append(mem[a])
            a += 1
        return b.decode("latin-1")

    def unexpected(self, what):
        def f(em):
            self.emit("  unexpected %s" % what)
            return 0
        return f

    # ---- the IOP's calls

    def create_file(self, em):
        fid = em.reg[4] & 0xffff
        self.files[fid] = (self.cstr(em.reg[5] & M32), em.reg[6] & M32)
        self.offsets.pop(fid, None)
        return 0

    def set_offset(self, em):
        fid = s32(em.reg[4])
        self.offsets[fid] = (em.reg[5] & M32, em.reg[6] & M32)
        return 0

    def play_stream(self, em):
        fid, stream, voice = (s32(em.reg[4]), s32(em.reg[5]),
                              s32(em.reg[6]))
        left, right, pitch = (em.reg[7] & 0xffff, em.reg[8] & 0xffff,
                              em.reg[9] & M32)
        self.pending = (fid, stream, voice, left, right, pitch)
        self.chained = []
        self.e.mem[KEYS + voice] = 3
        self.active.add(stream)
        return 0

    def chain_streams(self, em):
        n, info = s32(em.reg[5]), em.reg[6] & M32
        e = self.e
        self.chained = [(e.u16(info + 12 * i), e.u32(info + 12 * i + 4),
                         e.u32(info + 12 * i + 8)) for i in range(n)]
        return 0

    def part(self, fid, off=None, size=None):
        path, start = self.files.get(fid, ("?", 0))
        if off is None:
            off, size = self.offsets.get(fid, (start, 0))
        elif off == 0:
            off, size = start, 0
        return "    part '%s' %u %u" % (path, off, size)

    def flush(self, em):
        if self.pending is None:
            return 0
        fid, stream, voice, left, right, pitch = self.pending
        self.pending = None
        n = 1 + len(self.chained)
        self.emit("  stream %u hz=%u n=%u" % (voice, spu_to_hz(pitch), n))
        self.emit(self.part(fid))
        for cid, off, size in self.chained:
            self.emit(self.part(cid, off, size))
        self.emit("  mix %u %u %u" % (voice, left, right))
        return 0

    def patch_id(self, em):
        return 0xfffa

    def stream_info(self, em):
        stream, info = s32(em.reg[4]), em.reg[5] & M32
        self.e.mem[info + 18] = 1 if stream in self.active else 0
        return 0

    # ---- the dumps

    def dump(self):
        e = self.e
        self.emit("  chain n=%u" % e.u16(CHAIN_N))
        for i in range(QMAX):
            q = QUEUE + 52 * i
            name = self.cstr(q, 33)
            rate, vol = e.u16(q + 34), e.u16(q + 36)
            off, size = e.u32(q + 40), e.u32(q + 48)
            if not (name or rate or vol or off or size):
                continue
            self.emit("  q%u '%s' r=%u v=%u o=%u s=%u" % (i, name, rate, vol,
                                                         off, size))
        for v in range(NVOICE):
            a = VOICES + 80 * v
            pan = e.mem[a]
            pan = pan - 256 if pan & 0x80 else pan
            st = e.mem[a + 2]
            st = st - 256 if st & 0x80 else st
            f = (pan, e.mem[a + 1], st, e.mem[a + 3], e.u16(a + 4),
                 e.u32(a + 8), e.u16(a + 12), e.u16(a + 24), e.u16(a + 26),
                 e.u32(a + 28), e.mem[KEYS + v])
            if f == (0, 0, -1, 0, 0, 0, 0, 0, 0, 0, 0):
                continue
            self.emit("  v%u pan=%d loop=%u st=%d pa=%u ty=%u pitch=%u "
                      "vol=%u eff=%u az=%u adsr=%08x key=%u" % ((v,) + f))

    # ---- the ops

    def strs(self, *ss):
        out = []
        for s in ss:
            b = s.encode("latin-1") + b"\0"
            p = self.e.alloc(len(b) + 16, 16)
            self.e.write(p, b + bytes(16))
            out.append(p)
        return out

    def op(self, f):
        e = self.e
        o = f[0]
        if o == "path":
            b = (f[1] if len(f) > 1 else "").encode("latin-1")[:255]
            e.write(LOAD_PATH, b + bytes(256 - len(b)))
        elif o == "mode":
            e.mem[MODE] = int(f[1], 0) & 0xff
        elif o == "key":
            e.mem[KEYS + int(f[1], 0)] = int(f[2], 0) & 0xff
        elif o == "lock":
            e.mem[LOCKS + int(f[1], 0)] = int(f[2], 0) & 0xff
        elif o == "eff":
            e.write(VOICES + 80 * int(f[1], 0) + 24,
                    (int(f[2], 0) & 0xffff).to_bytes(2, "little"))
        elif o == "play":
            bank, patch = self.strs(f[1], f[2])
            n = [int(x, 0) for x in f[3:9]]
            r = e.call(F_PLAY, bank, patch, n[0], n[1] & 0xffff,
                       n[2] & 0xffff, n[3], n[4], n[5] & 0xffff,
                       limit=LIMIT)
            self.emit("  = %u" % (r & 0xffff))
        elif o == "active":
            r = e.call(F_ACTIVE, int(f[1], 0), limit=LIMIT)
            self.emit("  = %d" % (1 if r & 0xff else 0))
        elif o == "clear":
            e.write(KEYS, bytes(NVOICE))
            e.write(LOCKS, bytes(NVOICE))
        elif o == "drain":
            self.active.clear()
        elif o == "dump":
            self.dump()
        else:
            self.emit("  unknown op %s" % o)

    def run(self, lines):
        e = self.e
        for line in lines:
            self.emit("> " + line)
            sp = e.reg[29]
            self.op(line.split("|"))
            e.reg[29] = sp
        return self.out


def model(lines):
    m = Model()
    out = m.run(lines)
    return out, m.e


# ================================================================ script

SPEECH = "SPEECH" + chr(92) + "ENGLISHDAT.PCK"


def script():
    L = []
    a = L.append

    def play(bank, patch, rate, vol, az, off, size, voice):
        a("play|%s|%s|%d|%d|%d|%d|%d|%d" % (bank, patch, rate, vol, az, off,
                                            size, voice))

    a("dump")
    a("path|cdrom0:" + chr(92) + "SOUND" + chr(92))
    a("active|0")
    a("eff|0|0x777")
    a("eff|5|0x1234")
    a("eff|9|1")

    # One part, the driver's choice of voice: the whole file past its
    # header, then a part of it, then a patch's rate, at each mode.
    play("_STREAM", SPEECH, 24257, 0x3fff, 0, 0, 0, 48)
    a("dump")
    a("active|0")
    a("active|1")
    play("_STREAM", SPEECH, 24000, 0x7fff, 0x4000, 4096, 8192, 48)
    a("dump")
    play("_STREAM", SPEECH, 0xffffffff, 1000, 0xc000, 48, 0, 5)
    a("dump")
    a("active|5")
    a("active|0")                       # an older stream's voice
    a("drain")
    a("active|5")
    a("active|0")
    for m in (0, 1, 3):
        a("mode|%d" % m)
        play("_STREAMX", "A.VAG", 11025, 0x2000, 0x2000, 0, 0, 7)
    a("mode|2")
    a("dump")

    # The voice it picks: the lowest free, past keyed and locked ones; and
    # none free.
    for v in range(4):
        a("key|%d|3" % v)
    a("lock|4|1")
    play("_STREAM", "B.VAG", 22050, 0x1234, 0x8000, 0, 0, 48)
    a("dump")
    for v in range(NVOICE):
        a("key|%d|4" % v)
    play("_STREAM", "C.VAG", 22050, 0x1234, 0, 0, 0, 48)
    a("dump")
    for v in range(NVOICE):
        a("key|%d|0" % v)
    a("lock|4|0")

    # The queue: parts but the last, then the last plays them all.
    play("_CHAIN", SPEECH, 24257, 0x3000, 0x1000, 1048, 952, 48)
    a("dump")
    play("_CHAIN", SPEECH, 24257, 0x3100, 0x1000, 9000, 1200, 48)
    play("_CHAIN", SPEECH, 24257, 0x3200, 0x1000, 20000, 640, 48)
    a("dump")
    play("_STREAM", SPEECH, 24257, 0x3300, 0x1000, 30048, 4000, 48)
    a("dump")
    a("active|0")
    a("drain")
    a("active|0")

    # The queue's first part with no offset; a whole chain of eight; a
    # ninth that empties it.
    play("_CHAIN", "D.VAG", 30000, 100, 0, 0, 500, 48)
    play("_CHAIN", "E.VAG", 31000, 200, 0, 0, 0, 48)
    play("_STREAM", "F.VAG", 32000, 300, 0, 0, 0, 3)
    a("dump")
    for i in range(7):
        play("_CHAIN", "P%d.VAG" % i, 20000 + i, 1000 + i, 0,
             48 * (i + 1), 16 * (i + 1), 48)
    play("_STREAM", "LAST.VAG", 99999, 0xffff, 0, 777, 888, 48)
    a("dump")
    for i in range(9):
        play("_CHAIN", "Q%d.VAG" % i, 0x12345 + i, 2000 + i, 0, i, i, 48)
        a("dump")

    # A chain with no voice to play on stays queued.
    play("_CHAIN", "R.VAG", 8000, 10, 0, 16, 16, 48)
    for v in range(NVOICE):
        a("key|%d|3" % v)
    play("_STREAM", "S.VAG", 8000, 10, 0, 32, 32, 48)
    a("dump")
    for v in range(NVOICE):
        a("key|%d|0" % v)
    play("_STREAM", "T.VAG", 8000, 10, 0, 64, 64, 9)
    a("dump")

    # Long names: the queue keeps 32 bytes, the path 255 in all.
    play("_CHAIN", "N" * 40, 1, 2, 0, 3, 4, 48)
    play("_STREAM", "M" * 40, 1, 2, 0, 3, 4, 48)
    a("dump")
    a("path|" + "p" * 150)
    play("_STREAM", "Z" * 31, 22050, 5, 0, 0, 0, 10)
    play("_CHAIN", "Y" * 31, 22050, 5, 0, 0, 0, 48)
    play("_STREAM", "X" * 31, 22050, 5, 0, 0, 0, 11)
    a("path|")
    play("_STREAM", "PLAIN.VAG", 22050, 5, 0, 0, 0, 12)

    # Not a stream: "_CHAINX" and the rest are patches, of which there
    # are none.
    play("_CHAINX", "G", 22050, 5, 0, 0, 0, 48)
    play("COMMON", "HORN", 22050, 5, 0, 0, 0, 48)
    play("_STREA", "H", 22050, 5, 0, 0, 0, 48)
    a("dump")

    # Random runs. Every voice is freed each 15 ops, so a chain always
    # finds one: on a full queue left by one that did not, retail writes
    # past the queue (see the docstring).
    rng = random.Random(0x2611c0)
    banks = ["_STREAM", "_STREAMX", "_CHAIN", "_CHAIN", "_CHAIN", "COMMON"]
    for i in range(400):
        if i % 15 == 0:
            a("clear")
        r = rng.random()
        if r < 0.55:
            off = rng.choice((0, 0, 48, 4096, 0x123450, rng.randrange(1 << 32)))
            size = rng.choice((0, 0, 16, 960, rng.randrange(1 << 32)))
            voice = 48 if rng.random() < 0.7 else rng.randrange(NVOICE)
            play(rng.choice(banks), rng.choice(("A", SPEECH, "K" * 35, "")),
                 rng.choice((0, 1, 22050, 24000, 48000, 65535, 65536,
                             0xfffff, 0xffffffff)),
                 rng.randrange(1 << 16), rng.randrange(1 << 16), off, size,
                 voice)
        elif r < 0.65:
            a("key|%d|%d" % (rng.randrange(NVOICE), rng.choice((0, 3, 4))))
        elif r < 0.70:
            a("lock|%d|%d" % (rng.randrange(NVOICE), rng.choice((0, 1))))
        elif r < 0.73:
            a("eff|%d|%d" % (rng.randrange(NVOICE), rng.randrange(1 << 16)))
        elif r < 0.80:
            a("active|%d" % rng.randrange(NVOICE))
        elif r < 0.85:
            a("drain")
        elif r < 0.88:
            a("mode|%d" % rng.randrange(4))
        else:
            a("dump")
    a("dump")
    return L


# ================================================================= build

def build_harness(tmp, name="bsndstream_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, sc_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(sc_path)],
                               stdout=fh, stderr=subprocess.PIPE, text=True,
                               timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("harness hung, killed after %d s" % HARNESS_TIMEOUT)
        return pcc.HARNESS_HUNG
    if r.returncode != 0:
        print("harness exited %d" % r.returncode)
        if r.stderr:
            print(r.stderr[:2000])
    return r.returncode


diff = pcc.diff


def write_script(d, lines):
    sc = Path(d) / "script.txt"
    sc.write_text(NL.join(lines) + NL, encoding="latin-1")
    return sc


# =============================================================== decoder

def frame_inputs():
    """(name, bytes): windows of the DAT, and made-up frames."""
    rng = random.Random(0x24257)
    out = []
    if DAT.exists():
        size = DAT.stat().st_size
        with open(DAT, "rb") as fh:
            for k in range(48):
                off = (rng.randrange(48, size - 70000) // 16) * 16
                fh.seek(off)
                out.append(("dat@%d" % off, fh.read(rng.choice(
                    (16, 32, 4096, 65536)))))
    for k in range(64):
        n = rng.randrange(1, 400)
        b = bytearray(rng.randrange(256) for _ in range(16 * n))
        for i in range(n):
            b[16 * i + 1] = 0
            if rng.random() < 0.3:
                b[16 * i] = (rng.randrange(5) << 4) | rng.randrange(13)
        if k % 4 == 1:
            b[16 * rng.randrange(n) + 1] = 1
        elif k % 4 == 2:
            b[16 * rng.randrange(n) + 1] = 7
        elif k % 4 == 3:
            b[16 * rng.randrange(n) + 1] = rng.choice((2, 3, 4, 6))
        out.append(("made%d" % k, bytes(b)))
    return out


def decode_check(exe, tmp):
    """Each input through bss_decode in random runs, against
    decode_adpcm. Returns the inputs that differ."""
    bad = 0
    rng = random.Random(0xb55)
    for name, data in frame_inputs():
        src = Path(tmp) / "in.bin"
        dst = Path(tmp) / "out.pcm"
        src.write_bytes(data)
        r = subprocess.run([str(exe), "--decode", str(src), str(dst),
                            str(rng.randrange(1 << 31))],
                           capture_output=True, timeout=HARNESS_TIMEOUT)
        want = audio_convert.decode_adpcm(data)[0]
        got = array.array("h")
        if r.returncode == 0:
            got.frombytes(dst.read_bytes())
        if r.returncode != 0 or got != want:
            bad += 1
            if bad <= 5:
                print("decode %s: %d samples, want %d" % (name, len(got),
                                                          len(want)))
    return bad


# ============================================================= mutations

MUTATIONS_HEADER = "# " + "=" * 61 + " mutations" + NL


def _m(name, before, after, rel=BSND):
    return (name, rel, before, after)


MUTATIONS = [
    # The "_STREAM" path.
    _m("stream-bank-len", 'strncmp(bank, "_STREAM", 7) == 0)',
       'strncmp(bank, "_STREAM", 8) == 0)'),
    _m("stream-chain-test", "    if (d->chainCount != 0) {\n        BsndChainPart* c",
       "    if (d->chainCount > 1) {\n        BsndChainPart* c"),
    _m("stream-append-name", "        b_strncpy(c->name, patch, 32);\n        c->name[32] = '\\0';\n        c->offset = offset;\n        c->rate",
       "        b_strncpy(c->name, patch, 31);\n        c->name[32] = '\\0';\n        c->offset = offset;\n        c->rate"),
    _m("stream-append-offset", "        c->offset = offset;\n        c->rate = (uint16_t)rate;\n        c->size = size;",
       "        c->offset = size;\n        c->rate = (uint16_t)rate;\n        c->size = size;"),
    _m("stream-append-rate", "        c->offset = offset;\n        c->rate = (uint16_t)rate;\n        c->size = size;",
       "        c->offset = offset;\n        c->rate = (uint16_t)(rate >> 1);\n        c->size = size;"),
    _m("stream-append-volume", "        c->volume = volume;\n        d->chainCount++;",
       "        c->volume = volume >> 1;\n        d->chainCount++;"),
    _m("stream-append-count", "        d->chainCount++;\n        return play_chain(d, voice);",
       "        return play_chain(d, voice);"),
    _m("stream-rate-patch", "    if (rate == BSND_RATE_PATCH) rate = 22050;",
       "    if (rate == BSND_RATE_PATCH) rate = 22000;"),
    _m("stream-stereo", "    if (bank[7] == 'S') return BSND_NO_PATCH;",
       "    if (bank[6] == 'S') return BSND_NO_PATCH;"),
    _m("stream-alloc-range", "        int got = bsnd_find_free_channels(d, 0, d->voices - 1, 1);\n        if (got < 0) return BSND_NO_PATCH;               // 0x002614dc",
       "        int got = bsnd_find_free_channels(d, d->voices - 1, 0, 1);\n        if (got < 0) return BSND_NO_PATCH;               // 0x002614dc"),
    _m("stream-alloc-fail", "        if (got < 0) return BSND_NO_PATCH;               // 0x002614dc",
       "        if (got < 0) return BSND_BAD_VOICE;              // 0x002614dc"),
    _m("stream-pan", "    stream_voice(d, voice, rate, volume, pan);",
       "    stream_voice(d, voice, rate, volume, 0);"),
    _m("stream-effect", "    d->voice[voice].effectVolume = 0;\n", ""),
    _m("stream-offset", "    if (offset != 0) {                                   // 0x00261a28",
       "    if (size != 0) {                                     // 0x00261a28"),
    _m("stream-header", "        part.offset = BSND_VAG_HEADER;\n        part.size = 0;\n    }\n    stream_start",
       "        part.offset = 0;\n        part.size = 0;\n    }\n    stream_start"),
    _m("stream-size", "        part.offset = offset;\n        part.size = size;",
       "        part.offset = offset;\n        part.size = 0;"),

    # The "_CHAIN" queue.
    _m("chain-bank", 'strncmp(bank, "_CHAIN", 16) == 0)',
       'strncmp(bank, "_CHAIN", 6) == 0)'),
    _m("chain-name", "            b_strncpy(c->name, patch, 32);\n            c->name[32] = '\\0';\n            c->offset = offset;\n            c->size",
       "            b_strncpy(c->name, patch, 31);\n            c->name[32] = '\\0';\n            c->offset = offset;\n            c->size"),
    _m("chain-term", "            c->name[32] = '\\0';\n            c->offset = offset;\n            c->size = size;",
       "            c->name[31] = '\\0';\n            c->offset = offset;\n            c->size = size;"),
    _m("chain-size", "            c->size = size;\n            c->rate = (uint16_t)rate;\n            c->volume = volume;\n        }",
       "            c->size = offset;\n            c->rate = (uint16_t)rate;\n            c->volume = volume;\n        }"),
    _m("chain-rate", "            c->size = size;\n            c->rate = (uint16_t)rate;",
       "            c->size = size;\n            c->rate = (uint16_t)volume;"),
    _m("chain-volume", "            c->volume = volume;\n        }\n        if (++",
       "            c->volume = 0;\n        }\n        if (++"),
    _m("chain-max", "        if (++d->chainCount >= BSND_CHAIN_MAX) d->chainCount = 0;",
       "        if (++d->chainCount > BSND_CHAIN_MAX) d->chainCount = 0;"),
    _m("chain-ret", "        if (++d->chainCount >= BSND_CHAIN_MAX) d->chainCount = 0;\n        return voice;",
       "        if (++d->chainCount >= BSND_CHAIN_MAX) d->chainCount = 0;\n        return 0;"),

    # PlayChain.
    _m("play-rate", "    uint16_t rate = d->chain[0].rate, volume = d->chain[0].volume;",
       "    uint16_t rate = d->chain[0].volume, volume = d->chain[0].rate;"),
    _m("play-last", "    uint16_t rate = d->chain[0].rate, volume = d->chain[0].volume;",
       "    uint16_t rate = d->chain[d->chainCount - 1].rate, volume = d->chain[0].volume;"),
    _m("play-alloc-fail", "        if (got < 0) return BSND_NO_PATCH;               // 0x00262a5c",
       "        if (got < 0) { d->chainCount = 0; return BSND_NO_PATCH; }"),
    _m("play-header", "            parts[i].offset = BSND_VAG_HEADER;\n            parts[i].size = 0;",
       "            parts[i].offset = 0;\n            parts[i].size = 0;"),
    _m("play-header-size", "            parts[i].offset = BSND_VAG_HEADER;\n            parts[i].size = 0;",
       "            parts[i].offset = BSND_VAG_HEADER;\n            parts[i].size = c->size;"),
    _m("play-part-size", "            parts[i].offset = c->offset;\n            parts[i].size = c->size;",
       "            parts[i].offset = c->offset;\n            parts[i].size = 0;"),
    _m("play-count", "    unsigned i, n = d->chainCount;", "    unsigned i, n = d->chainCount - 1;"),
    _m("play-pan", "    stream_voice(d, voice, rate, volume, 0);\n    stream_start(d, voice, parts, n, rate, volume);",
       "    stream_voice(d, voice, rate, volume, 1);\n    stream_start(d, voice, parts, n, rate, volume);"),
    _m("play-reset", "    d->chainCount = 0;                                   // 0x00262f8c\n", ""),

    # The voice and the start.
    _m("voice-pitch", "    v->pitch = rate;                // the rate asked for, unconverted",
       "    v->pitch = bsnd_spu_to_hz(bsnd_hz_to_spu(rate));"),
    _m("voice-volume", "    v->volume = volume;\n    v->pan = pan;\n    v->adsr",
       "    v->volume = volume | 1;\n    v->pan = pan;\n    v->adsr"),
    _m("voice-adsr", "    v->adsr = 0x1a00000au;\n    v->type = BSND_TYPE_STREAM;",
       "    v->adsr = 0x1a00000bu;\n    v->type = BSND_TYPE_STREAM;"),
    _m("voice-type", "    v->type = BSND_TYPE_STREAM;\n", "    v->type = 4;\n"),
    _m("voice-loop", "    v->loopChannel = 0;\n    v->streamChannel = BSND_MONO_STREAM;",
       "    v->loopChannel = 0x10;\n    v->streamChannel = BSND_MONO_STREAM;"),
    _m("voice-stream", "    v->streamChannel = BSND_MONO_STREAM;\n", "    v->streamChannel = 3;\n"),
    _m("voice-az", "    v->azimuth = bsnd_azimuth_from_pan(pan);\n    v->patch",
       "    v->azimuth = 0;\n    v->patch"),
    _m("start-pan", "    bsnd_volumes_from_pan(d, &l, &r, volume, 0);",
       "    bsnd_volumes_from_pan(d, &l, &r, volume, d->voice[ch].pan);"),
    _m("start-key", "    d->key[ch] = BSND_KEY_ON;\n    d->streamVoice = (int16_t)ch;\n",
       "    d->streamVoice = (int16_t)ch;\n"),
    _m("start-rate", "                        bsnd_spu_to_hz(bsnd_hz_to_spu(rate)));",
       "                        rate);"),
    _m("path-join", "    b_strncpy(out + n, name, 255 - n);",
       "    b_strncpy(out + n, name, 254 - n);"),
    _m("path-strncpy", "        dst[i] = src[i];\n        if (src[i] == '\\0') break;",
       "        if (src[i] == '\\0') break;\n        dst[i] = src[i];"),

    # bsnd_stream_active.
    _m("active-stream", "    if (voice >= d->voices || d->voice[voice].streamChannel < 0) return false;",
       "    if (voice >= d->voices) return false;"),
    _m("active-voice", "        && d->sink->playing(d->sink->user, (unsigned)d->streamVoice);",
       "        && d->sink->playing(d->sink->user, voice);"),
    _m("start-voice", "    d->streamVoice = (int16_t)ch;\n", ""),

    # The decoder.
    _m("dec-flag7", "        if (f[1] == 7) {\n            d->ended = true;\n            break;",
       "        if (f[1] == 6) {\n            d->ended = true;\n            break;", BSS),
    _m("dec-flag1", "        if (f[1] == 1) {\n            d->ended = true;\n        }",
       "        if (f[1] == 3) {\n            d->ended = true;\n        }", BSS),
    _m("dec-pred", "        if (pred > 4) {", "        if (pred > 3) {", BSS),
    _m("dec-round", "            v = (v >> shift) + ((f0 * h1 + f1 * h2 + 32) >> 6);",
       "            v = (v >> shift) + ((f0 * h1 + f1 * h2) >> 6);", BSS),
    _m("dec-clamp", "            if (v > 32767) {\n                v = 32767;",
       "            if (v > 32766) {\n                v = 32766;", BSS),
    _m("dec-nibble", "            int32_t v = (int16_t)(uint16_t)(((f[2 + k / 2] >> ((k & 1) * 4))",
       "            int32_t v = (int16_t)(uint16_t)(((f[2 + k / 2] >> ((~k & 1) * 4))", BSS),
    _m("dec-hist", "        d->hist[0] = h1;\n        d->hist[1] = h2;",
       "        d->hist[0] = h1;\n        d->hist[1] = h1;", BSS),
    _m("dec-filter", "{ 0, 0 }, { 60, 0 }, { 115, -52 }, { 98, -55 }, { 122, -60 },",
       "{ 0, 0 }, { 60, 0 }, { 115, -52 }, { 98, -55 }, { 122, -61 },", BSS),
]

EQUIVALENT = {
    # Once "_STREAM" has matched, bank[6] is always 'M': the mutant only
    # lets "_STREAMS" through as mono, and "_STREAMS" is not compared.
    "stream-stereo":
        "after the _STREAM match bank[6] is always M; only _STREAMS "
        "goes through, and it is not compared",
    # The port's load path holds 159 bytes and a name 32: the join never
    # reaches 254.
    "path-join":
        "the load path holds 159 bytes and a name 32: 191 < 254",
}


def run_all(scp, tmp_limit):
    def f(exe, out):
        rc = mutpar.run_exe([exe, scp], out, tmp_limit)
        if rc == 0:
            with tempfile.TemporaryDirectory() as d:
                if decode_check(exe, d):
                    with open(out, "a") as fh:
                        fh.write("decoder differs" + NL)
        return rc
    return f


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    indir = tempfile.TemporaryDirectory()
    lines = script()
    scp = write_script(indir.name, lines)
    base = model(lines)[0]
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text(encoding="latin-1").splitlines()
        if diff(base, got, quiet=True) or decode_check(exe, tmp):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)
    limit = mutpar.timeout_for(took * 20)
    result = mutpar.run_pass(todo, SOURCES, "bsndstream_test",
                             run_all(scp, limit), base, diff, EQUIVALENT,
                             jobs)
    indir.cleanup()
    return mutpar.summarize(todo, only, EQUIVALENT, result)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--jobs", type=int, metavar="N",
                    help="with --mutate, mutants at once (default %d)"
                    % mutpar.JOBS)
    ap.add_argument("--dump", metavar="PREFIX")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None,
                             args.jobs))

    lines = script()
    got, e = model(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = write_script(tmp, lines)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text(encoding="latin-1").splitlines()
        nin = len(frame_inputs())
        bad = decode_check(exe, tmp)

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(got) + NL,
                                           encoding="latin-1")
        d.with_suffix(".harness").write_text(NL.join(harness) + NL,
                                             encoding="latin-1")

    n = diff(got, harness)
    print("%d ops, %d lines, %d differ; decoder: %d inputs, %d differ%s" % (
        len(lines), len(harness), n, nin, bad,
        "" if DAT.exists() else " (no ENGLISHDAT.PCK: made-up frames only)"))
    sys.exit(1 if n or rc or bad else 0)


if __name__ == "__main__":
    main()
