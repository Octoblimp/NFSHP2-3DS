r"""Cross-check the ported bSnd driver against a second implementation.

`3DS Files/source/bsnd.c` is the port of the disc's voice layer. This file is
the same layer written again in Python, from `docs/formats/sound-driver.md` and
the disassembly it cites -- not from the C. Both are driven through the twelve
scenarios in `tools/src/bsnd_test.c`, both print the same transcript, and the
two are diffed line for line.

What that catches is the whole point: which voice an allocation picked, what
left and right volume each one ended up with, what rate survived the SPU pitch
round trip, which patch's bytes were handed to the mixer, and when a voice came
back. A driver can be wrong in every one of those ways without crashing, and
none of them is visible in a screenshot.

The pan table is read out of `PS2 Files/NFSHP2.ELF` here rather than out of the
generated `bsndtab.c`, so the table the port compiles in is checked too.

    python tools/bsnd_check.py out/SOUND
    python tools/bsnd_check.py out/SOUND --mutate

`--mutate` is the check on the checker: it breaks the C a line at a time --
a shift, a sentinel, a table index, a loop bound -- rebuilds, and insists every
break shows up as a diff. A mutation that survives is a hole in the scenarios,
not a harmless edit.
"""
import argparse
import math
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import mipsdis

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ["tools/src/bsnd_test.c", "3DS Files/source/bsnd.c",
           "3DS Files/source/sndbank.c", "3DS Files/source/bsndtab.c"]

NL = chr(10)
CR = chr(13)

PAN_TABLE_ADDR = 0x00317d00

# The port's sentinels (bsnd.h); the PS2 spells the first four as out-of-range
# values of the real argument -- 48, 0xffffffff, 0xffff, -128.
MAX_VOICES = 24
PS2_VOICES = 48
MAX_BANKS = 8
VOICE_ALLOC = 0xffff
RATE_PATCH = 0xffffffff
VOLUME_PATCH = 0xffff
PAN_PATCH = -128
PATCH_PAN = 0
NO_PATCH = 0xfffe
BAD_VOICE = 0xfffc
PATCH_NONE = 0xfffa
KEY_OFF, KEY_ON = 0, 3
MODE_MONO, MODE_STEREO, MODE_PROLOGIC = 1, 2, 3
ADSR_DEFAULT = 0x1a00000a


def bhash(s):
    """bStringHash, 0x0023b280: djb2 seeded with -1."""
    h = 0xffffffff
    for c in s.encode("latin-1"):
        h = (h * 33 + c) & 0xffffffff
    return h


def crc(b):
    return zlib.crc32(b) & 0xffffffff


def u16(x):
    return x & 0xffff


def s8(x):
    x &= 0xff
    return x - 256 if x >= 128 else x


def f32(x):
    """Round to single precision. The EE has no double; a model that used one
    would diverge from the C for a reason that is the model's, not the port's."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


# --------------------------------------------------------------- the .SBK bank

HEADER_SIZE = 32
PATCH_SIZE = 128
FLAG_LOOP = 0x01


class Patch(object):
    __slots__ = ("name", "hash", "samples", "off", "size", "rate", "volume",
                 "effect", "channels", "looping", "coefs", "data")


class Bank(object):
    """docs/formats/sound-bank.md, "The port's .SBK". Deliberately not the same
    code as tools/sndbank_check.py's reader: that one checks sndbank.c, this
    one only needs to hand the model the same patches the C driver sees."""

    def __init__(self, image):
        magic, ver, count, doff, dsize = struct.unpack_from("<4sIIII", image, 0)
        if magic != b"SBK1" or ver != 1:
            raise ValueError("not an .SBK")
        self.count = count
        self.patches = []
        for i in range(count):
            r = HEADER_SIZE + i * PATCH_SIZE
            p = Patch()
            p.name = image[r:r + 32].split(b"\0")[0].decode("latin-1")
            (p.hash, p.samples, p.off, p.size, p.rate, p.volume, p.effect,
             p.channels, flags) = struct.unpack_from("<IIIIHHHBB", image, r + 32)
            p.looping = bool(flags & FLAG_LOOP)
            p.coefs = [list(struct.unpack_from("<16h", image, r + 56 + c * 32))
                       for c in range(2)]
            p.data = image[doff + p.off:doff + p.off + p.size]
            self.patches.append(p)

    def channel(self, p, n):
        """One channel's frames. Channel-major: all of ch0, then all of ch1."""
        if n < 0 or n >= p.channels:
            return None
        per = p.size // p.channels
        return p.data[n * per:(n + 1) * per]


# ------------------------------------------------------------------- the model

class Voice(object):
    def __init__(self):
        self.clear()

    def clear(self):
        self.pan = 0
        self.loopChannel = 0
        self.streamChannel = -1
        self.paused = 0
        self.pitch = 0
        self.volume = 0
        self.effect = 0
        self.azimuth = 0
        self.type = 0
        self.adsr = 0
        self.volL = 0
        self.volR = 0
        self.patch = PATCH_NONE


class Slot(object):
    def __init__(self, bank, hash_, first):
        self.bank = bank
        self.hash = hash_
        self.first = first
        self.count = bank.count


class Driver(object):
    def __init__(self, out, table, voices=MAX_VOICES):
        self.out = out                  # the transcript, and the sink's recorder
        self.table = table
        self.voices = voices if 0 < voices <= PS2_VOICES else MAX_VOICES
        self.mode = MODE_STEREO         # bSnd_Initialize ends with SetStereo
        self.patchCount = 0
        self.voice = [Voice() for _ in range(PS2_VOICES)]
        self.key = [KEY_OFF] * PS2_VOICES
        self.lock = [0] * PS2_VOICES
        self.slots = [None] * MAX_BANKS
        # The harness's sink: how many ticks of audio each channel has left,
        # and whether it loops (and so never runs out).
        self.left = [0] * PS2_VOICES
        self.loop = [0] * PS2_VOICES

    # -- units ---------------------------------------------------------------

    @staticmethod
    def hz_to_spu(hz):
        return ((hz << 12) // 48000) & 0xffffffff

    @staticmethod
    def spu_to_hz(spu):
        return ((spu * 48000) >> 12) & 0xffffffff

    @staticmethod
    def trunc14(x):
        # The EE's sra of a product the caller has already biased.
        return (x + 16383 if x < 0 else x) >> 14

    @classmethod
    def pan_from_azimuth(cls, az):
        # GetPanFromAzimuth, 0x0024f688: four quadrants onto +-127.
        if az <= 0x4000:
            v = cls.trunc14(az * 127)
        elif az > 0xbfff:
            v = cls.trunc14((0x10000 - az) * -127)
        elif az >= 0x8000:                       # (int16_t)az < 0
            v = cls.trunc14((az - 0x8000) * -127)
        else:
            v = cls.trunc14((0x8000 - az) * 127)
        return s8(v)

    @staticmethod
    def azimuth_from_pan(pan):
        # GetAzimuthFromPan, 0x0024f7e0: float32 of 16384/127, both multiplies
        # mul.s, the store a truncating cvt.w.s.
        k = f32(129.00787353515625)
        if pan >= 0:
            v = f32(f32(pan) * k)
        else:
            v = f32(65536.0 - f32(f32(pan) * f32(-k)))
        return u16(int(v))

    def volumes_from_pan(self, volume, pan):
        # GetVolumesFromPan, 0x0024d928. The clamp is the port's -- the ROM
        # reads table[-1] -- and is written up in the driver doc.
        if self.mode < MODE_STEREO:
            pan = 0
        if pan < -127:
            pan = -127
        idx = pan + 127
        return (u16((volume * self.table[idx]) >> 14),
                u16((volume * self.table[254 - idx]) >> 14))

    def find_free_channels(self, first, last, count):
        # SOUND_FindFreeSPUChannels, 0x002520c0.
        if first >= self.voices:
            return -2
        if last >= self.voices:
            return -3
        step = -1 if last < first else 1
        run = 0
        i = first
        while i != last + step:
            if self.lock[i] == 0 and self.key[i] == KEY_OFF:
                run += 1
                if run == count:
                    return i + 1 - count if step > 0 else i
            else:
                run = 0
            i += step
        return -1

    # -- the sink ------------------------------------------------------------

    def sink_start(self, ch, data, samples, coefs, rate, looping):
        cb = struct.pack("<16h", *coefs)
        self.out("  start ch=%u bytes=%u samples=%u rate=%u loop=%d "
                 "data=%08x coef=%08x"
                 % (ch, len(data), samples, rate, 1 if looping else 0,
                    crc(data), crc(cb)))
        self.left[ch] = 3
        self.loop[ch] = 1 if looping else 0

    def sink_stop(self, ch):
        self.out("  stop ch=%u" % ch)
        self.left[ch] = 0
        self.loop[ch] = 0

    def sink_mix(self, ch, l, r):
        self.out("  mix ch=%u l=%u r=%u" % (ch, l, r))

    def sink_rate(self, ch, hz):
        self.out("  rate ch=%u hz=%u" % (ch, hz))

    def sink_pause(self, ch, paused):
        self.out("  pause ch=%u %d" % (ch, 1 if paused else 0))

    def sink_playing(self, ch):
        return self.loop[ch] != 0 or self.left[ch] > 0

    # -- banks ---------------------------------------------------------------

    def slot_of(self, name):
        h = bhash(name)
        for i, s in enumerate(self.slots):
            if s is not None and s.hash == h:
                return i
        return -1

    def bank_loaded(self, name):
        return self.slot_of(name) >= 0

    def bank_register(self, name, image):
        if self.slot_of(name) >= 0:
            return True                          # already loaded, as bSnd does
        for i in range(MAX_BANKS):
            if self.slots[i] is None:
                break
        else:
            return False
        try:
            bank = Bank(image)
        except ValueError:
            return False
        # StartPatch/EndPatch: ids are flat across every loaded bank.
        self.slots[i] = Slot(bank, bhash(name), self.patchCount)
        self.patchCount = u16(self.patchCount + bank.count)
        return True

    def bank_unload(self, name):
        i = self.slot_of(name)
        if i < 0:
            return False
        s = self.slots[i]
        for v in range(self.voices):
            p = self.voice[v].patch
            if p != PATCH_NONE and s.first <= p < s.first + s.count:
                self.voice_stop(v)
        self.slots[i] = None
        # Ids are not compacted and patchCount is not lowered.
        return True

    def slot_for_patch(self, pid):
        for s in self.slots:
            if s is not None and s.first <= pid < u16(s.first + s.count):
                return s
        return None

    def patch_id(self, bank, patch):
        # bSnd_GetPatchID, 0x0024d730: the first record whose name hashes to
        # this one, which is how a bank with two "SelectFinal"s plays the first.
        i = self.slot_of(bank) if bank else -1
        if i < 0 or patch is None:
            return PATCH_NONE
        s = self.slots[i]
        h = bhash(patch)
        for k, p in enumerate(s.bank.patches):
            if p.hash == h:
                return u16(s.first + k)
        return PATCH_NONE

    def patch_get(self, pid):
        s = self.slot_for_patch(pid)
        if s is None:
            return None
        return s.bank.patches[pid - s.first], s.bank

    def patch_channels(self, pid):
        got = self.patch_get(pid)
        return got[0].channels if got else 0

    # -- voices --------------------------------------------------------------

    def voice_play(self, bank, patch, rate, volume, azimuth, voice):
        # bSnd_VoicePlay, 0x00247f00, normal path.
        pan = self.pan_from_azimuth(azimuth)     # 0x00247fac, before anything

        pid = self.patch_id(bank, patch)
        if pid == PATCH_NONE:
            return NO_PATCH                      # 0x00248d2c
        got = self.patch_get(pid)
        if got is None:
            return NO_PATCH
        p, bnk = got
        channels = p.channels

        if voice == VOICE_ALLOC:
            n = self.find_free_channels(0, self.voices - 1, channels)
            if n < 0:
                return NO_PATCH
            voice = n
        if voice + channels > self.voices:
            return BAD_VOICE                     # 0x00248e08, widened

        if rate == RATE_PATCH:
            rate = p.rate
        if volume == VOLUME_PATCH:
            volume = p.volume
        rate = self.spu_to_hz(self.hz_to_spu(rate))
        adsr = ADSR_DEFAULT                      # every disc record's ADSR is 0

        for n in range(channels):
            v = self.voice[voice + n]
            if channels == 2:
                chanPan = -127 if n == 0 else 127
            else:
                chanPan = PATCH_PAN if pan == PAN_PATCH else pan
            l, r = self.volumes_from_pan(volume, chanPan)

            v.pan = chanPan
            v.loopChannel = (1 if p.looping else 0) | ((channels - 1) << 4)
            v.streamChannel = -1
            v.paused = 0
            v.pitch = rate
            v.volume = volume
            v.effect = p.effect
            v.azimuth = azimuth
            v.type = 4 if azimuth else (1 if p.looping else 0) + 1
            v.adsr = adsr
            v.volL = l
            v.volR = r
            v.patch = pid

            data = bnk.channel(p, n)
            if data is not None:
                self.key[voice + n] = KEY_ON
                self.sink_start(voice + n, data, p.samples, p.coefs[n], rate,
                                p.looping)
            self.sink_mix(voice + n, l, r)
        return voice

    def voice_play_pan(self, bank, patch, rate, volume, pan, voice):
        return self.voice_play(bank, patch, rate, volume,
                               self.azimuth_from_pan(pan), voice)

    def voice_width(self, voice):
        if voice >= self.voices:
            return 0
        w = (self.voice[voice].loopChannel >> 4) + 1
        if voice + w > self.voices:
            w = self.voices - voice
        return w

    def voice_stop(self, voice):
        for n in range(self.voice_width(voice)):
            ch = voice + n
            self.sink_stop(ch)
            self.key[ch] = KEY_OFF
            self.voice[ch].clear()

    def voice_pause(self, voice, paused):
        for n in range(self.voice_width(voice)):
            self.voice[voice + n].paused = 1 if paused else 0
            self.sink_pause(voice + n, paused)

    def voice_paused(self, voice):
        return voice < self.voices and self.voice[voice].paused != 0

    def channel_busy(self, voice):
        return voice < self.voices and self.key[voice] != KEY_OFF

    def set_voice_volume(self, voice, volume):
        if self.mode == MODE_PROLOGIC:
            return
        for n in range(self.voice_width(voice)):
            v = self.voice[voice + n]
            if v.streamChannel != -1:
                continue
            l, r = self.volumes_from_pan(volume, v.pan)
            v.volume, v.volL, v.volR = volume, l, r
            self.sink_mix(voice + n, l, r)

    def set_voice_pan(self, voice, pan):
        for n in range(self.voice_width(voice)):
            v = self.voice[voice + n]
            if v.streamChannel != -1:
                continue
            l, r = self.volumes_from_pan(v.volume, pan)
            v.pan, v.volL, v.volR = pan, l, r
            self.sink_mix(voice + n, l, r)

    def set_voice_volume_pan(self, voice, volume, pan):
        for n in range(self.voice_width(voice)):
            v = self.voice[voice + n]
            if v.streamChannel != -1:
                continue
            l, r = self.volumes_from_pan(volume, pan)
            v.volume, v.pan, v.volL, v.volR = volume, pan, l, r
            self.sink_mix(voice + n, l, r)

    def set_voice_pitch(self, voice, hz):
        played = self.spu_to_hz(self.hz_to_spu(hz))
        for n in range(self.voice_width(voice)):
            self.voice[voice + n].pitch = played
            self.sink_rate(voice + n, played)

    def get_voice_volume(self, voice):
        return self.voice[voice].volume if voice < self.voices else 0

    def get_voice_pan(self, voice):
        return self.voice[voice].pan if voice < self.voices else 0

    def get_voice_pitch(self, voice):
        return self.voice[voice].pitch if voice < self.voices else 0

    def lock_channels(self, first, count, locked):
        n = 0
        while n < count and first + n < self.voices:
            self.lock[first + n] = 1 if locked else 0
            n += 1

    def update(self):
        for i in range(self.voices):
            if self.key[i] == KEY_OFF:
                continue
            if self.voice[i].paused:
                continue
            if self.sink_playing(i):
                continue
            self.sink_stop(i)
            self.key[i] = KEY_OFF
            self.voice[i].clear()

    # -- transcript helpers --------------------------------------------------

    def tick(self):
        for i in range(PS2_VOICES):
            if not self.loop[i] and self.left[i] > 0:
                self.left[i] -= 1
        self.out("  tick")
        self.update()

    def dump(self):
        for i in range(self.voices):
            v = self.voice[i]
            if v.patch == PATCH_NONE and self.key[i] == KEY_OFF and self.lock[i] == 0:
                continue
            self.out("  v%02u pan=%d lc=%02x pitch=%u vol=%u fx=%u az=%u ty=%u "
                     "adsr=%08x l=%u r=%u patch=%u paused=%u key=%u lock=%d"
                     % (i, v.pan, v.loopChannel, v.pitch, v.volume, v.effect,
                        v.azimuth, v.type, v.adsr, v.volL, v.volR, v.patch,
                        v.paused, self.key[i], self.lock[i]))

    def play(self, bank, patch, rate, vol, az, voice):
        r = self.voice_play(bank, patch, rate, vol, az, voice)
        self.out("play %s/%s rate=%u vol=%u az=%u voice=%u -> %u"
                 % (bank, patch, rate, vol, az, voice, r))
        self.dump()

    def play_pan(self, bank, patch, rate, vol, pan, voice):
        r = self.voice_play_pan(bank, patch, rate, vol, pan, voice)
        self.out("playpan %s/%s rate=%u vol=%u pan=%d voice=%u -> %u az=%04x"
                 % (bank, patch, rate, vol, pan, voice, r,
                    self.azimuth_from_pan(pan)))
        self.dump()


# ---------------------------------------------------------------- the scenarios

def transcript(common, frontend, table):
    """The twelve scenarios of tools/src/bsnd_test.c, in the same order with
    the same arguments. Keep the two in step: a scenario added there has to be
    added here, and the diff will say so loudly if it is not."""
    lines = []
    out = lines.append

    def scenario(n, name):
        out("== %d %s" % (n, name))

    # 1. The units, before any state exists to confuse them.
    scenario(1, "units")
    for hz in (0, 1, 8000, 11025, 16000, 22050, 24000, 32000, 44100, 48000,
               48001, 96000, 4000000):
        spu = Driver.hz_to_spu(hz)
        out("  hz %u -> spu %u -> hz %u" % (hz, spu, Driver.spu_to_hz(spu)))
    for az in range(0, 0x10000, 0x400):
        out("  az %04x -> pan %d" % (az, Driver.pan_from_azimuth(az)))
    for az in (0x3fff, 0x4000, 0x4001, 0x7fff, 0x8000, 0x8001, 0xbfff, 0xc000,
               0xc001, 0xfffe, 0xffff):
        out("  az %04x -> pan %d" % (az, Driver.pan_from_azimuth(az)))
    for pan in range(-128, 128):
        az = Driver.azimuth_from_pan(pan)
        out("  pan %+04d -> az %04x -> pan %d"
            % (pan, az, Driver.pan_from_azimuth(az)))

    # 2. The pan table, end to end, at five volumes, in all three modes.
    scenario(2, "pan table")
    d = Driver(out, table)
    for mode in (MODE_MONO, MODE_STEREO, MODE_PROLOGIC):
        d.mode = mode
        for vol in range(0, 0x8000, 0x1fff):
            for pan in range(-128, 128):
                l, r = d.volumes_from_pan(vol, pan)
                out("  m%d v%05d p%+04d -> %u %u" % (mode, vol, pan, l, r))

    # 3. The allocator, with holes punched in it by hand.
    scenario(3, "allocator")
    for width in (MAX_VOICES, PS2_VOICES):
        d = Driver(out, table, width)
        out("  width %u" % width)
        for count in range(4):
            out("   empty count=%u -> %d"
                % (count, d.find_free_channels(0, width - 1, count)))
        for i in range(0, width, 2):
            d.key[i] = KEY_ON
        out("   evens busy 1 -> %d  2 -> %d"
            % (d.find_free_channels(0, width - 1, 1),
               d.find_free_channels(0, width - 1, 2)))
        d.key[width // 2] = KEY_OFF
        out("   one pair 2 -> %d  reversed -> %d"
            % (d.find_free_channels(0, width - 1, 2),
               d.find_free_channels(width - 1, 0, 2)))
        d.lock_channels(width // 2, 2, True)
        out("   locked 2 -> %d" % d.find_free_channels(0, width - 1, 2))
        d.lock_channels(width // 2, 2, False)
        out("   unlocked 2 -> %d" % d.find_free_channels(0, width - 1, 2))
        out("   bad first -> %d  bad last -> %d"
            % (d.find_free_channels(width, width - 1, 1),
               d.find_free_channels(0, width, 1)))
        out("   sub 3..9 2 -> %d  single 7..7 1 -> %d"
            % (d.find_free_channels(3, 9, 2), d.find_free_channels(7, 7, 1)))

    # 4. Banks: load, look up, unload, and the misses in between.
    scenario(4, "banks")
    d = Driver(out, table)
    out("  loaded COMMON=%d" % (1 if d.bank_loaded("COMMON") else 0))
    out("  register COMMON=%d" % (1 if d.bank_register("COMMON", common) else 0))
    out("  register COMMON again=%d"
        % (1 if d.bank_register("COMMON", common) else 0))
    out("  register FRONTEND=%d"
        % (1 if d.bank_register("FRONTEND", frontend) else 0))
    out("  patchCount=%u" % d.patchCount)
    for name in ("MenuSelect", "MenuUpDown", "MenuLeftRight", "MenuCancel",
                 "MenuStart", "MenuWrong", "MenuAdjustVolume", "NoSuchPatch",
                 "menuselect"):
        pid = d.patch_id("COMMON", name)
        out("  id COMMON/%s = %u ch=%u" % (name, pid, d.patch_channels(pid)))
    out("  id NOPE/MenuSelect = %u" % d.patch_id("NOPE", "MenuSelect"))
    out("  id FRONTEND/HelpLoop = %u ch=%u"
        % (d.patch_id("FRONTEND", "HelpLoop"),
           d.patch_channels(d.patch_id("FRONTEND", "HelpLoop"))))
    out("  id FRONTEND/RewardEnter = %u ch=%u"
        % (d.patch_id("FRONTEND", "RewardEnter"),
           d.patch_channels(d.patch_id("FRONTEND", "RewardEnter"))))

    # 5. Playing: the defaults, then each override in turn.
    scenario(5, "play defaults")
    d.play("COMMON", "MenuSelect", RATE_PATCH, VOLUME_PATCH, 0, VOICE_ALLOC)
    d.play("COMMON", "MenuUpDown", 8000, 0x4000, 0, VOICE_ALLOC)
    d.play_pan("FRONTEND", "RewardEnter", RATE_PATCH, VOLUME_PATCH, -64, VOICE_ALLOC)
    d.play("FRONTEND", "RewardEnter", RATE_PATCH, VOLUME_PATCH, 0x2000, VOICE_ALLOC)
    d.play_pan("FRONTEND", "RewardExit", RATE_PATCH, VOLUME_PATCH, 127, VOICE_ALLOC)
    d.play_pan("FRONTEND", "RewardExit", RATE_PATCH, VOLUME_PATCH, -127, VOICE_ALLOC)
    d.play_pan("FRONTEND", "RewardExit", RATE_PATCH, VOLUME_PATCH, PAN_PATCH,
               VOICE_ALLOC)
    d.play("COMMON", "NoSuchPatch", RATE_PATCH, VOLUME_PATCH, 0, VOICE_ALLOC)
    d.play("NOPE", "MenuSelect", RATE_PATCH, VOLUME_PATCH, 0, VOICE_ALLOC)

    # 6. Explicit voices, including the two that must be refused.
    scenario(6, "explicit voices")
    d = Driver(out, table)
    d.bank_register("COMMON", common)
    d.bank_register("FRONTEND", frontend)
    d.play("COMMON", "MenuSelect", RATE_PATCH, VOLUME_PATCH, 0, 10)
    d.play("FRONTEND", "RewardEnter", RATE_PATCH, VOLUME_PATCH, 0, MAX_VOICES - 1)
    d.play("COMMON", "MenuSelect", RATE_PATCH, VOLUME_PATCH, 0, MAX_VOICES - 1)
    d.play("COMMON", "MenuSelect", RATE_PATCH, VOLUME_PATCH, 0, MAX_VOICES)

    # 7. Exhaustion: twelve stereo patches fill 24 channels.
    scenario(7, "exhaustion")
    d = Driver(out, table)
    d.bank_register("COMMON", common)
    for _ in range(14):
        d.play("COMMON", "MenuSelect", RATE_PATCH, VOLUME_PATCH, 0, VOICE_ALLOC)
    out("busy:" + "".join(" %d" % (1 if d.channel_busy(i) else 0)
                          for i in range(d.voices)))
    d.voice_stop(6)
    d.dump()
    d.play("COMMON", "MenuSelect", RATE_PATCH, VOLUME_PATCH, 0, VOICE_ALLOC)

    # 8. Setters on a live voice, both channels of a stereo pair at once.
    scenario(8, "setters")
    d = Driver(out, table)
    d.bank_register("COMMON", common)
    d.bank_register("FRONTEND", frontend)
    d.play("COMMON", "MenuSelect", RATE_PATCH, VOLUME_PATCH, 0, VOICE_ALLOC)
    d.play("FRONTEND", "RewardEnter", RATE_PATCH, VOLUME_PATCH, 0, VOICE_ALLOC)
    for mode in (MODE_MONO, MODE_STEREO, MODE_PROLOGIC):
        d.mode = mode
        out("mode %d" % mode)
        d.set_voice_volume(0, 0x2000)
        d.set_voice_pan(0, 64)
        d.set_voice_volume_pan(0, 0x7fff, -32)
        d.set_voice_pitch(0, 11025)
        d.set_voice_volume(2, 0x1000)
        d.set_voice_pan(2, -100)
        d.set_voice_pitch(2, 44100)
        out("  get v0 vol=%u pan=%d pitch=%u | v2 vol=%u pan=%d pitch=%u"
            % (d.get_voice_volume(0), d.get_voice_pan(0), d.get_voice_pitch(0),
               d.get_voice_volume(2), d.get_voice_pan(2), d.get_voice_pitch(2)))
        d.dump()
    d.mode = MODE_STEREO
    d.set_voice_volume(MAX_VOICES, 0x100)
    d.set_voice_pan(0xffff, 0)
    d.voice_stop(MAX_VOICES + 5)
    out("  out of range v=%u pan=%d pitch=%u busy=%d paused=%d"
        % (d.get_voice_volume(MAX_VOICES), d.get_voice_pan(MAX_VOICES),
           d.get_voice_pitch(MAX_VOICES),
           1 if d.channel_busy(MAX_VOICES) else 0,
           1 if d.voice_paused(MAX_VOICES) else 0))
    d.dump()

    # 9. Pause and resume, and what an update does to a paused voice.
    scenario(9, "pause")
    d = Driver(out, table)
    d.bank_register("COMMON", common)
    d.play("COMMON", "MenuSelect", RATE_PATCH, VOLUME_PATCH, 0, VOICE_ALLOC)
    d.voice_pause(0, True)
    out("  paused=%d busy=%d" % (1 if d.voice_paused(0) else 0,
                                 1 if d.channel_busy(0) else 0))
    for _ in range(4):
        d.tick()
    d.dump()
    d.voice_pause(0, False)
    out("  paused=%d" % (1 if d.voice_paused(0) else 0))
    for _ in range(4):
        d.tick()
    d.dump()

    # 10. Retirement: a one-shot gives its voices back, a loop does not.
    scenario(10, "retirement")
    d = Driver(out, table)
    d.bank_register("FRONTEND", frontend)
    d.play("FRONTEND", "HelpLoop", RATE_PATCH, VOLUME_PATCH, 0, VOICE_ALLOC)
    d.play("FRONTEND", "RewardEnter", RATE_PATCH, VOLUME_PATCH, 0, VOICE_ALLOC)
    for _ in range(5):
        d.tick()
        d.dump()
    d.play("FRONTEND", "RewardExit", RATE_PATCH, VOLUME_PATCH, 0, VOICE_ALLOC)

    # 11. Unloading a bank stops what it was playing and leaves the rest.
    scenario(11, "unload")
    d = Driver(out, table)
    d.bank_register("COMMON", common)
    d.bank_register("FRONTEND", frontend)
    d.play("COMMON", "MenuSelect", RATE_PATCH, VOLUME_PATCH, 0, VOICE_ALLOC)
    d.play("FRONTEND", "HelpLoop", RATE_PATCH, VOLUME_PATCH, 0, VOICE_ALLOC)
    d.play("COMMON", "MenuWrong", RATE_PATCH, VOLUME_PATCH, 0, VOICE_ALLOC)
    out("unload FRONTEND=%d" % (1 if d.bank_unload("FRONTEND") else 0))
    d.dump()
    out("  patchCount=%u loaded COMMON=%d FRONTEND=%d"
        % (d.patchCount, 1 if d.bank_loaded("COMMON") else 0,
           1 if d.bank_loaded("FRONTEND") else 0))
    out("unload FRONTEND again=%d" % (1 if d.bank_unload("FRONTEND") else 0))
    out("  id FRONTEND/HelpLoop = %u" % d.patch_id("FRONTEND", "HelpLoop"))
    ok = d.bank_register("FRONTEND", frontend)
    out("  re-register FRONTEND=%d patchCount=%u" % (1 if ok else 0, d.patchCount))
    out("  id FRONTEND/HelpLoop = %u" % d.patch_id("FRONTEND", "HelpLoop"))
    d.dump()

    # 12. Every patch in both banks, played once on its own driver.
    scenario(12, "every patch")
    for name, image in (("COMMON", common), ("FRONTEND", frontend)):
        d = Driver(out, table)
        d.bank_register(name, image)
        for pid in range(d.patchCount):
            got = d.patch_get(pid)
            if got is None:
                out("  id %u reject" % pid)
                continue
            p = got[0]
            out("  patch %u %s ch=%u rate=%u vol=%u loop=%d"
                % (pid, p.name, p.channels, p.rate, p.volume,
                   1 if p.looping else 0))
            d.play(name, p.name, RATE_PATCH, VOLUME_PATCH, 0, 0)
            d.voice_stop(0)

    return lines


# ----------------------------------------------------------------------- driver

# A mutation can turn a loop into one with no exit. With no deadline here
# that mutant runs until something kills it and stalls the whole pass; the
# harness itself runs in well under a second.
HARNESS_TIMEOUT = 60


def run_c(exe, sbk_dir):
    try:
        r = subprocess.run([str(exe), str(sbk_dir)], capture_output=True,
                           timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        sys.exit("bsnd_test hung, killed after %d s" % HARNESS_TIMEOUT)
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode("latin-1"))
        sys.exit("bsnd_test failed (exit %d)" % r.returncode)
    lines = r.stdout.decode("latin-1").split(NL)[:-1]
    # One trailing CR per line, from the C runtime's text mode -- not every CR
    # in the line, which is the mistake sndbank_check.py started out making.
    return [ln[:-1] if ln.endswith(CR) else ln for ln in lines]


def diff(c, py, limit=25):
    n = max(len(c), len(py))
    bad = 0
    for i in range(n):
        x = c[i] if i < len(c) else "<missing>"
        y = py[i] if i < len(py) else "<missing>"
        if x != y:
            bad += 1
            if bad <= limit:
                print("  %d" % (i + 1))
                print("    C  %s" % x)
                print("    py %s" % y)
    return n, bad


# Each mutation is a single edit to bsnd.c that changes what a correct driver
# does. If the transcript does not notice one, the scenarios are not covering
# that line and the entry stays here until they do.
#
# Two earlier entries were dropped for being equivalent mutants rather than
# gaps, which is worth recording so nobody puts them back:
#
#   `if (azimuth <= 0x4000)` -> `<` is identical on all 65536 azimuths. The
#   first quadrant computes az * 127 and the last computes (0x8000 - az) * 127,
#   and at az == 0x4000 those are the same number, so the boundary can sit on
#   either side of the compare.
#
#   `const float k` -> `const double k` is identical on all 256 pans. The
#   constant is exactly representable as a float, and every product of it with
#   a pan fits a double exactly, so the double path rounds once at the
#   assignment to `f` and lands where the all-float path lands. Since pan is an
#   int8_t, all 256 inputs are swept in scenario 1 -- the mutation is not
#   untested, it is unobservable.
MUTATIONS = [
    ("hz_to_spu shift", "((uint64_t)hz << 12) / 48000u", "((uint64_t)hz << 11) / 48000u"),
    ("spu_to_hz shift", "((uint64_t)spu * 48000u) >> 12", "((uint64_t)spu * 48000u) >> 11"),
    ("trunc14 bias", "(x < 0 ? x + 16383 : x) >> 14", "x >> 14"),
    ("pan quadrant", "if (azimuth > 0xbfff)", "if (azimuth > 0xbffe)"),
    ("pan scale", "trunc14(az * 127)", "trunc14(az * 126)"),
    ("azimuth constant", "129.00787353515625f", "129.0f"),
    ("azimuth rounds", "return (uint16_t)(int32_t)f;", "return (uint16_t)(int32_t)(f + 0.5f);"),
    ("volume shift", ">> 14);\n    *right", ">> 15);\n    *right"),
    ("right table index", "bsnd_pan_table[254 - idx]", "bsnd_pan_table[253 - idx]"),
    ("mono collapse", "if (d->mode < BSND_MODE_STEREO) pan = 0;", ""),
    ("alloc run reset", "        } else {\n            run = 0;", "        } else {\n            run = run;"),
    ("alloc start", "return (step > 0) ? i + 1 - (int)count : i;", "return i;"),
    ("alloc lock", "if (d->lock[i] == 0 && d->key[i] == BSND_KEY_OFF)", "if (d->key[i] == BSND_KEY_OFF)"),
    ("alloc first bound", "if (first >= d->voices) return -2;", "if (first > d->voices) return -2;"),
    ("stereo hard pan", "chanPan = (n == 0) ? -127 : 127;", "chanPan = (n == 0) ? -100 : 100;"),
    ("patch rate default", "if (rate == BSND_RATE_PATCH) rate = p.rate;", ""),
    ("pitch round trip", "rate = bsnd_spu_to_hz(bsnd_hz_to_spu(rate));", ""),
    ("adsr default", "adsr = 0x1a00000au;", "adsr = 0x1a00000bu;"),
    ("type from azimuth", "v->type = azimuth ? 4u", "v->type = azimuth ? 5u"),
    ("loopChannel nibble", "<< 4));", "<< 5));"),
    ("explicit voice bound", "if ((unsigned)voice + channels > d->voices)", "if ((unsigned)voice > d->voices)"),
    ("voice width", "(d->voice[voice].loopChannel >> 4) + 1u", "1u"),
    ("update skips paused", "if (d->voice[i].paused) continue;", ""),
    ("unload stops voices", "bsnd_voice_stop(d, (uint16_t)v);", "(void)v;"),
    ("flat patch ids", "s->first = d->patchCount;", "s->first = 0;"),
]


# The write, its OneDrive retry, and the journal that lets a killed pass be
# recovered from are all hostbuild's.
write_source = hostbuild.write_source


def mutate_pass(sbk_dir, c_lines, py_lines, table):
    src = ROOT / "3DS Files" / "source" / "bsnd.c"
    # newline="" so the file's own line endings survive the round trip, and
    # the patterns are translated to match rather than the file to match the
    # patterns -- a universal-newlines read here would rewrite the source to
    # LF on every write, and a bare-newline pattern would miss a CRLF file
    # silently the other way round.
    original = src.read_text(encoding="utf-8", newline="")
    crlf = (chr(13) + NL) in original
    survived = []
    try:
        for name, old, new in MUTATIONS:
            if crlf:
                old = old.replace(NL, chr(13) + NL)
                new = new.replace(NL, chr(13) + NL)
            if old not in original:
                survived.append("%s (pattern gone: %r)" % (name, old))
                continue
            write_source(src, original.replace(old, new, 1))
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = hostbuild.build(tmp, SOURCES, name="bsnd_test")
                except SystemExit:
                    print("  %-24s did not compile (counts as caught)" % name)
                    continue
                try:
                    got = run_c(exe, sbk_dir)
                except SystemExit:
                    print("  %-24s crashed the harness (caught)" % name)
                    continue
            _, bad = diff(got, py_lines, limit=0)
            if bad:
                print("  %-24s caught, %d lines" % (name, bad))
            else:
                print("  %-24s SURVIVED" % name)
                survived.append(name)
    finally:
        try:
            write_source(src, original)
        except OSError:
            sys.exit("could not restore %s -- it still holds a "
                     "mutation. Put the original line back before "
                     "trusting anything printed above." % src)
    return survived


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sbk_dir", help="a directory holding COMMON.SBK and FRONTEND.SBK")
    ap.add_argument("--mutate", action="store_true",
                    help="also break bsnd.c a line at a time and check the "
                         "transcript notices")
    a = ap.parse_args()

    sbk = Path(a.sbk_dir)
    common = sbk / "COMMON.SBK"
    frontend = sbk / "FRONTEND.SBK"
    for p in (common, frontend):
        if not p.exists():
            sys.exit("no %s -- run tools/audio_pack.py first" % p)

    # Straight out of the ELF, so the generated bsndtab.c is under test too.
    table = list(struct.unpack("<256H", mipsdis.Elf().read(PAN_TABLE_ADDR, 512)))
    for i in range(225):
        if table[i] != int(16383 * math.cos(i * math.pi / 512.0)):
            sys.exit("the ELF read is wrong: pan table entry %d is %d" % (i, table[i]))

    py = transcript(common.read_bytes(), frontend.read_bytes(), table)

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="bsnd_test")
        c = run_c(exe, sbk)

    lines, bad = diff(c, py)
    print("%d lines, %d differ" % (lines, bad))
    rc = 1 if bad else 0

    if a.mutate:
        if bad:
            sys.exit("not mutating: the unmutated port already differs")
        print("mutations:")
        survived = mutate_pass(sbk, c, py, table)
        print("%d mutations, %d survived" % (len(MUTATIONS), len(survived)))
        for s in survived:
            print("  survived: %s" % s)
        rc = 1 if survived else 0

    return rc


if __name__ == "__main__":
    sys.exit(main())
