#!/usr/bin/env python3
"""Cross-check 3DS Files/source/bsound.c -- bSample, bRegion, bVoiceMgr
and bSound -- against the retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own library (0x002716f8-0x0027c730): the
constructors, Initialize, Play, Stop, Fade, Update, the voice manager,
LoadRegion and the pending regions, the category volumes. Its bSnd_*
calls land on a fake driver; the harness (tools/src/bsound_test.c) runs
bsound.c over the same fake, written again in C. Every driver call prints
a line, so the order and the arguments of the calls are compared as well
as what the library keeps.

**The fake driver** has N channels, each locked, busy (playing) or free,
a width and a volume; banks the script declares with their patches
(name, channels, pitch, volume), loaded when asked, or later ("lazy",
until the script says the bank has arrived); a stream's near-end flag per
channel. A play marks the channels busy; the script ends a voice
("end"), as the hardware would, and the voice manager's next update
finds it idle. LockChannels takes the highest free run, as bSnd's does.

**The labels**: pool samples S<slot>, samples on the script's own storage
(filled with 0xa5 first, to show what the constructor leaves) L<handle>,
regions R<slot>, voice records V<index>, callbacks A and B (a sample's)
and C (the client's).

**Compared**, after each op that can change anything: the bSound's
status, common region, pending region, path and category volumes; the
voice records; the regions and their samples; and every field of every
live sample, the floats as bits.

**The script**: the load and pending paths (a lazy bank, a load while one
is pending, a bank that fails, a region named "common", long names);
play, stop, pause, mute, fade and the updates that step it; voices that
end and are reclaimed, locked voices that are kept; a stream's near end
and the callbacks; the category volumes over playing samples; running
out of channels; CalcPitch over the whole range at both types, CalcPan,
CalcVolume and GetScaledVolume; unloading regions that are playing; then
random runs over all of it.

    python tools/bsound_check.py
    python tools/bsound_check.py --mutate [--only a,b]
"""
import argparse
import os
import random
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/bsound_test.c"
BSC = "3DS Files/source/bsound.c"
SOURCES = [HARNESS, BSC, "3DS Files/source/bslotpool.c",
           "3DS Files/source/bmem.c"]
HARNESS_TIMEOUT = 120

SND = 0x00336900                        # the bSound instance
VOICES = 0x00327c88                     # bVoiceMgr's 48 bVoices
NVOICE = 48
SAMPLE_SIZE = 188
CB = {"A": 0x01e00010, "B": 0x01e00020, "C": 0x01e00030}
CBNAME = {v: k for k, v in CB.items()}

# bSample
F_SAMPLE_NEW = 0x00275c88
F_SAMPLE_CTOR = 0x00273098
F_SAMPLE_DTOR = 0x00273148
F_INIT_COPY = 0x00273210
F_INIT_CB = 0x00273280
F_INIT = 0x002732c0
F_LOCKVOICE = 0x00273388
F_SETNAME = 0x00273498
F_SETBANK = 0x00273520
F_SETCAT = 0x00273618
F_SETPAN = 0x00273648
F_CALCPAN = 0x002736c8
F_SETPITCH = 0x00273738
F_CALCPITCH = 0x00273850
F_SETSCALE = 0x00273be8
F_SCALED = 0x00273c80
F_SETVOL = 0x00273d50
F_SETAZ = 0x00273e70
F_CALCVOL = 0x00273ed8
F_GETVOL = 0x00273f58
F_PLAYN = 0x00273ff8
F_PLAY = 0x00274080
F_ISPLAYING = 0x00274410
F_PAUSE = 0x00274488
F_STOP = 0x00274618
F_MUTE = 0x002747a0
F_FADE = 0x00274868
F_CHANNELS = 0x00274960
F_SUPDATE = 0x00274a98
F_SETCB = 0x00275e88
F_GETPITCH = 0x00275de0
# bRegion
F_REGION_SAMPLE = 0x002719b8
F_SVEC_SIZE = 0x0025d608
F_SVEC_AT = 0x0012f7f0
# bSound
F_SND_CTOR = 0x002776c0
F_SND_INIT = 0x00277820
F_SND_UPDATE = 0x002778f8
F_SND_COMMON = 0x002779e0
F_SND_REGION = 0x00277a18
F_SND_LOAD = 0x00277b00
F_SND_UNLOAD = 0x00277c00
F_SND_SETCAT = 0x00277cb0
F_SND_GETCAT = 0x00277dc0
F_SND_PATH = 0x00277e38
F_SND_STATUS = 0x00277ea0
F_SND_MODE = 0x00278190
F_RVEC_SIZE = 0x0027a1d0
F_RVEC_AT = 0x00279878

NO_OPS = (0x00250ac0, 0x00250af0, 0x00251150, 0x002511f8, 0x00251320,
          0x00278250, 0x0027ab20, 0x0027af90, 0x00266010, 0x0025e690)


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


# ============================================================= the driver

class Bank(object):
    def __init__(self, name, lazy, patches):
        self.name, self.lazy, self.loaded = name, lazy, False
        self.p = patches                # [(name, ch, pitch, vol)]


class Model(object):
    def __init__(self):
        self.e = e = retail_model.RetailEmu(ieee=True)
        self.out = []
        e.stub_bware()
        e.stub(0x002577c0, lambda e: e.alloc(s32(e.reg[4]), 16))
        e.stub(0x00257850, lambda e: 0)
        for a in NO_OPS:
            e.stub(a, lambda e: 0)
        e.stub(0x00250f38, lambda e: 0)
        self.n = 24
        self.lock = [0] * NVOICE
        self.busy = [0] * NVOICE
        self.width = [0] * NVOICE
        self.near = [0] * NVOICE
        self.vol = [0] * NVOICE
        self.banks = []
        self.pools = {}                 # base -> [size, n, free list]
        self.spool = self.rpool = None
        self.h = {}                     # handle -> address
        self.local = {}
        self.frm = {}
        self.strbuf = [e.alloc(512, 16) for _ in range(4)]
        self.pname = e.alloc(64, 16)
        self.install()

    def emit(self, line):
        self.out.append(line)

    # -- memory helpers
    def cstr(self, a, n=4096):
        e = self.e
        a &= M32
        b = bytearray()
        while len(b) < n:
            c = e.mem[a + len(b)]
            if c == 0:
                break
            b.append(c)
        return b.decode("latin-1")

    def strs(self, *ss):
        out = []
        for i, s in enumerate(ss):
            b = s.encode("latin-1") + b"\0"
            self.e.write(self.strbuf[i], b)
            out.append(self.strbuf[i])
        return out

    def fbank(self, name):
        for b in self.banks:
            if b.name == name:
                return b
        return None

    def fpatch(self, bank, patch):
        b = self.fbank(bank)
        if b is None or not b.loaded:
            return None
        for p in b.p:
            if p[0] == patch:
                return p
        return None

    # -- the stubs
    def install(self):
        e = self.e
        R = lambda i: e.reg[4 + i] & M32        # noqa: E731
        S = lambda a: self.cstr(a)               # noqa: E731

        def sc(v):
            v &= 0xff
            return v - 256 if v & 0x80 else v

        def patchid(e):
            bank, patch = S(R(0)), S(R(1))
            b = self.fbank(bank)
            r = 0xfffa
            if b is not None and b.loaded:
                for i, p in enumerate(b.p):
                    if p[0] == patch:
                        r = 0x100 * self.banks.index(b) + i
                        break
            self.emit("  snd patchid %s %s -> %04x" % (bank, patch, r))
            return r

        def lock(e):
            count = R(0) & 0xffff
            r = 0xfffc
            if count:
                first = self.n - count
                while first >= 0:
                    if not any(self.lock[c] or self.busy[c]
                               for c in range(first, first + count)):
                        for c in range(first, first + count):
                            self.lock[c] = 1
                        r = first
                        break
                    first -= 1
            self.emit("  snd lock %u -> %d" % (count, r))
            return r

        def unlock(e):
            first, count = R(0) & 0xffff, R(1) & 0xffff
            for c in range(first, first + count):
                if c < self.n:
                    self.lock[c] = 0
            self.emit("  snd unlock %u %u" % (first, count))

        def pan(e):
            self.emit("  snd pan %u %d" % (R(0) & 0xffff, sc(R(1))))

        def pitch(e):
            self.emit("  snd pitch %u %u" % (R(0) & 0xffff, R(1)))

        def setvol(e):
            v, vol = R(0) & 0xffff, R(1) & 0xffff
            if v < self.n:
                self.vol[v] = vol
            self.emit("  snd vol %u %u" % (v, vol))

        def getvol(e):
            v = R(0) & 0xffff
            r = self.vol[v] if v < self.n else 0
            self.emit("  snd getvol %u -> %u" % (v, r))
            return r

        def az(e):
            self.emit("  snd az %u %u" % (R(0) & 0xffff, R(1) & 0xffff))

        def play_at(e, vreg):
            bank, patch = S(R(0)), S(R(1))
            rate, vol, pn = R(2), R(3) & 0xffff, sc(R(4))
            v = R(vreg) & 0xffff
            self.emit("  snd play %s %s %u %u %d %u" % (bank, patch, rate,
                                                       vol, pn, v))
            p = self.fpatch(bank, patch)
            if p is not None and v < self.n:
                self.width[v] = p[1]
                for c in range(v, min(v + p[1], self.n)):
                    self.busy[c] = 1
                self.vol[v] = vol
                return v
            return 0xfffe

        def play(e):
            return play_at(e, 5)

        def play_offset(e):
            # (bank, patch, rate, volume, pan, offset, size, voice): the
            # two words the master overload passes on, which the port's
            # driver has no use for, so the line is the plain one's.
            return play_at(e, 7)

        def stop(e):
            v = R(0) & 0xffff
            self.emit("  snd stop %u" % v)
            if v < self.n:
                for c in range(v, min(v + self.width[v], self.n)):
                    self.busy[c] = 0

        def pause(e):
            self.emit("  snd pause %u" % (R(0) & 0xffff))

        def resume(e):
            self.emit("  snd resume %u" % (R(0) & 0xffff))

        def busy(e):
            v = R(0) & 0xffff
            r = self.busy[v] if v < self.n else 0
            self.emit("  snd busy %u -> %d" % (v, r))
            return r

        def near(e):
            v = R(0) & 0xffff
            r = self.near[v] if v < self.n else 0
            self.emit("  snd near %u -> %d" % (v, r))
            return r

        def ppitch(e):
            bank, patch = S(R(0)), S(R(1))
            p = self.fpatch(bank, patch)
            r = p[2] if p else 0
            self.emit("  snd ppitch %s %s -> %u" % (bank, patch, r))
            return r

        def pvol(e):
            bank, patch = S(R(0)), S(R(1))
            p = self.fpatch(bank, patch)
            r = p[3] if p else 0
            self.emit("  snd pvol %s %s -> %u" % (bank, patch, r))
            return r

        def pch(e):
            bank, patch = S(R(0)), S(R(1))
            p = self.fpatch(bank, patch)
            r = p[1] if p else 0
            self.emit("  snd pch %s %s -> %u" % (bank, patch, r))
            return r

        def ploop(e):
            self.emit("  snd ploop")
            return 0

        def banknum(e):
            name = S(R(0))
            b = self.fbank(name)
            r = self.banks.index(b) if b is not None and b.loaded else 0xffff
            self.emit("  snd banknum %s -> %u" % (name, r))
            return r

        def npatch(e):
            bank = R(0) & 0xffff
            r = (len(self.banks[bank].p)
                 if bank < len(self.banks) and self.banks[bank].loaded else 0)
            self.emit("  snd npatch %u -> %u" % (bank, r))
            return r

        def pname(e):
            bank, k = R(0) & 0xffff, R(1) & 0xffff
            if (bank < len(self.banks) and self.banks[bank].loaded
                    and k < len(self.banks[bank].p)):
                nm = self.banks[bank].p[k][0]
                e.write(self.pname, nm.encode("latin-1") + b"\0")
                self.emit("  snd pname %u %u -> %s" % (bank, k, nm))
                return self.pname
            self.emit("  snd pname %u %u -> 0" % (bank, k))
            return 0

        def bankload(e):
            name = S(R(0))
            b = self.fbank(name)
            if b is not None and not b.lazy:
                b.loaded = True
            self.emit("  snd bankload %s -> %d" % (name, b is not None))
            return 0xffff if b is None else self.banks.index(b)

        def isloaded(e):
            name = S(R(0))
            b = self.fbank(name)
            r = int(b is not None and b.loaded)
            self.emit("  snd isloaded %s -> %d" % (name, r))
            return r

        def unload(e):
            name = S(R(0))
            b = self.fbank(name)
            if b is not None:
                b.loaded = False
            self.emit("  snd unload %s" % name)
            return 1

        def update(e):
            self.emit("  snd update")
            return 1

        def flush(e):
            self.emit("  snd flush")

        def path(e):
            self.emit("  snd path %s" % S(R(0)))

        def mode(m):
            def f(e):
                self.emit("  snd mode %u" % m)
            return f

        def new_pool(e):
            size, n, name = s32(e.reg[4]), s32(e.reg[5]), S(R(2))
            base = e.alloc(48 + size * n, 16)
            self.pools[base] = [size, n, list(range(n))]
            if name == "bSoundSamples":
                self.spool = base
            elif name == "bSoundRegions":
                self.rpool = base
            else:
                raise ValueError("pool %r" % name)
            return base

        def omalloc(e):
            base = R(0)
            size, n, free = self.pools[base]
            if not free:
                return 0
            i = free.pop(0)
            p = base + 48 + i * size
            e.write(p, bytes(size))
            return p

        def pfree(e):
            base, p = R(0), R(1)
            if p == 0:
                return 0
            size, n, free = self.pools[base]
            free.insert(0, (p - base - 48) // size)
            return 0

        def cb(name):
            def f(e):
                ev, what, data = R(0), R(1), R(2)
                lb = self.rlabel(what) if ev == 2 else self.slabel(what)
                self.emit("  cb %s ev=%u what=%s data=%08x" % (name, ev, lb,
                                                              data))
            return f

        for a, f in ((0x00266fb0, patchid), (0x002638a0, lock),
                     (0x002639a0, unlock), (0x00263b58, pan),
                     (0x00263a38, pitch), (0x00264038, setvol),
                     (0x00264790, getvol), (0x00263f40, az),
                     (0x00260c40, play), (0x00260ce8, play_offset),
                     (0x00263710, busy), (0x00263240, pause),
                     (0x00263330, resume), (0x00263438, stop),
                     (0x00263090, near), (0x00264f58, ppitch),
                     (0x00265088, pvol), (0x002652b0, pch),
                     (0x00265360, ploop), (0x00260b38, banknum),
                     (0x00264cf8, npatch), (0x00264e10, pname),
                     (0x00260418, unload), (0x0025f720, bankload),
                     (0x00260a80, isloaded), (0x0025f418, update),
                     (0x0025f0f0, flush), (0x0025f510, path),
                     (0x0025f158, mode(1)), (0x0025f248, mode(2)),
                     (0x0025f330, mode(3)), (0x00257c10, new_pool),
                     (0x00257c80, omalloc), (0x00257ca0, pfree)):
            e.stub(a, f)
        for k, a in CB.items():
            e.stub(a, cb(k))

    # -- labels
    def slabel(self, p):
        p &= M32
        if p == 0:
            return "0"
        for h in sorted(self.h):
            if self.local.get(h) and self.h[h] == p:
                return "L%d" % h
        if self.spool is not None:
            off = p - self.spool - 48
            if 0 <= off < 255 * SAMPLE_SIZE and off % SAMPLE_SIZE == 0:
                return "S%d" % (off // SAMPLE_SIZE)
        return "?"

    def rlabel(self, p):
        p &= M32
        if p == 0:
            return "0"
        if self.rpool is not None:
            size = self.pools[self.rpool][0]
            off = p - self.rpool - 48
            if 0 <= off < 32 * size and off % size == 0:
                return "R%d" % (off // size)
        return "?"

    def vlabel(self, p):
        p &= M32
        if p == 0:
            return "0"
        off = p - VOICES
        if 0 <= off < NVOICE * 8 and off % 8 == 0:
            return "V%d" % (off // 8)
        return "?"

    # -- the dump
    def fixed(self, a, n):
        b = bytes(self.e.mem[a:a + n])
        z = b.find(b"\0")
        return (b if z < 0 else b[:z]).decode("latin-1")

    def regions(self):
        e = self.e
        out = []
        for i in range(e.call(F_RVEC_SIZE, SND + 344)):
            out.append(e.u32(e.call(F_RVEC_AT, SND + 344, i) & M32))
        return out

    def rsamples(self, r):
        e = self.e
        out = []
        for i in range(e.call(F_SVEC_SIZE, r + 40)):
            out.append(e.u32(e.call(F_SVEC_AT, r + 40, i) & M32))
        return out

    def dump_sample(self, p):
        e = self.e
        u = e.u32
        sc = e.mem[p + 136]
        cbv = u(p + 48)
        self.emit("  %s v=%s r=%08x ne=%d f8=%d off=%u sz=%u cv=%08x sc=%08x "
                  "ft=%08x fa=%08x pn=%08x pt=%08x cb=%s cd=%08x n='%s' "
                  "b='%s' vm=%04x mu=%d pa=%d ca=%u ty=%d lk=%d lp=%d id=%04x"
                  % (self.slabel(p), self.vlabel(u(p + 12)), u(p),
                     s32(u(p + 4)), s32(u(p + 8)), u(p + 16), u(p + 20),
                     u(p + 24), u(p + 28), u(p + 32), u(p + 36), u(p + 40),
                     u(p + 44),
                     "0" if cbv == 0 else CBNAME.get(cbv, "?"), u(p + 52),
                     self.fixed(p + 56, 32), self.fixed(p + 88, 32),
                     e.u16(p + 120), s32(u(p + 124)), s32(u(p + 128)),
                     u(p + 132), sc - 256 if sc & 0x80 else sc,
                     s32(u(p + 140)), s32(u(p + 144)), e.u16(p + 148)))

    def dump(self):
        e = self.e
        u = e.u32
        self.emit("  snd st=%d com=%s pend=%d '%s' path='%s'"
                  % (s32(u(SND + 8)), self.rlabel(u(SND + 4)),
                     s32(u(SND + 340)), self.fixed(SND + 84, 255),
                     self.fixed(SND + 392, 64)))
        self.emit("  cat" + "".join(" %08x" % u(SND + 12 + 4 * i)
                                     for i in range(16)))
        vo = []
        for i in range(NVOICE):
            idv, smp = e.u16(VOICES + 8 * i), u(VOICES + 8 * i + 4)
            if smp or idv:
                vo.append(" %d:%u:%s" % (i, idv, self.slabel(smp)))
        self.emit("  vo" + "".join(vo))
        seen = set()
        for r in self.regions():
            parts = []
            for s in self.rsamples(r):
                lb = self.slabel(s)
                parts.append(" " + lb)
                if lb[0] == "S":
                    seen.add(int(lb[1:]))
            self.emit("  region %s '%s'%s" % (self.rlabel(r),
                                              self.fixed(r, 33),
                                              "".join(parts)))
        for h in sorted(self.h):
            p = self.h[h]
            if not p:
                continue
            if self.local.get(h):
                self.dump_sample(p)
            else:
                lb = self.slabel(p)
                if lb[0] == "S":
                    seen.add(int(lb[1:]))
        for i in sorted(seen):
            self.dump_sample(self.spool + 48 + i * SAMPLE_SIZE)

    # -- the ops
    def setf(self, *vals):
        for i, v in enumerate(vals):
            self.e.fpr[12 + i] = int(v, 0) & M32

    def region(self, name):
        (p,) = self.strs(name)
        return self.e.call(F_SND_REGION, SND, p) & M32

    def run(self, a):
        e = self.e
        o = a[0]
        if o == "voices":
            self.n = int(a[1])
            return False
        if o == "bank":
            pats = []
            for spec in a[3:]:
                f = spec.split(":")
                pats.append((f[0], int(f[1], 0), int(f[2], 0) & M32,
                             int(f[3], 0) & 0xffff))
            self.banks.append(Bank(a[1], int(a[2]), pats[:8]))
            return False
        if o == "arrive":
            b = self.fbank(a[1])
            if b is not None:
                b.loaded = True
            self.emit("arrive %s" % a[1])
            return True
        if o == "end":
            self.busy[int(a[1])] = 0
            self.emit("end %s" % a[1])
            return True
        if o == "near":
            self.near[int(a[1])] = int(a[2])
            self.emit("near %s %s" % (a[1], a[2]))
            return False
        if o == "chvol":
            self.vol = [int(a[1], 0) & 0xffff] * NVOICE
            self.emit("chvol %s" % a[1])
            return False
        if o == "boot":
            self.emit("boot %s %s" % (a[1], a[2]))
            e.call(F_SND_CTOR, SND)
            e.call(F_SND_INIT, SND, CB.get(a[1], 0), int(a[2], 0), 0, 0, 0,
                   0, 0)
            return True
        if o == "load":
            self.emit("load %s" % a[1])
            (p,) = self.strs(a[1])
            self.emit("  -> %d" % e.call(F_SND_LOAD, SND, p))
            return True
        if o == "update":
            self.emit("update")
            e.call(F_SND_UPDATE, SND)
            return True
        if o == "unload":
            self.emit("unload %s" % a[1])
            if self.region(a[1]):
                for k in list(self.h):
                    if not self.local.get(k) and self.frm.get(k) == a[1]:
                        self.h[k] = 0
            # With no regions, retail's erase can take the count below 0,
            # after which GetRegion runs on past every fragment and never
            # returns. The port leaves an empty vector alone, which is
            # retail's call not made.
            if e.call(F_RVEC_SIZE, SND + 344) != 0:
                (p,) = self.strs(a[1])
                e.call(F_SND_UNLOAD, SND, p)
            return True
        if o == "region":
            self.emit("region %s -> %s" % (a[1], self.rlabel(self.region(a[1]))))
            return False
        if o == "common":
            self.emit("common -> %s" % self.rlabel(e.call(F_SND_COMMON, SND)))
            return False
        if o == "catvol":
            self.emit("catvol %s %s" % (a[1], a[2]))
            self.setf(a[2])
            e.call(F_SND_SETCAT, SND, int(a[1], 0))
            return True
        if o == "getcatvol":
            e.call(F_SND_GETCAT, SND, int(a[1], 0))
            self.emit("getcatvol %s -> %08x" % (a[1], e.fpr[0] & M32))
            return False
        if o == "mode":
            self.emit("mode %s" % a[1])
            e.call(F_SND_MODE, SND, int(a[1]))
            return True
        if o == "path":
            self.emit("path %s" % a[1])
            (p,) = self.strs(a[1])
            e.call(F_SND_PATH, SND, p)
            return True
        if o == "status":
            self.emit("status -> %d" % e.call(F_SND_STATUS, SND))
            return False

        h = int(a[1])
        s = self.h.get(h, 0)
        if o == "new":
            p = e.call(F_SAMPLE_NEW, SAMPLE_SIZE, 0, 0) & M32
            if p:
                e.call(F_SAMPLE_CTOR, p, int(a[2]))
            self.h[h], self.local[h], self.frm[h] = p, False, ""
            self.emit("new %d %s -> %s" % (h, a[2], self.slabel(p)))
            return True
        if o == "local":
            p = e.alloc(SAMPLE_SIZE + 4, 16)
            e.write(p, b"\xa5" * SAMPLE_SIZE)
            self.h[h], self.local[h], self.frm[h] = p, True, ""
            e.call(F_SAMPLE_CTOR, p, int(a[2]))
            self.emit("local %d %s" % (h, a[2]))
            return True
        if o in ("get", "at"):
            r = self.region(a[2])
            if o == "get":
                q = self.strs(a[2], a[3])[1]
                p = e.call(F_REGION_SAMPLE, r, q) & M32 if r else 0
            else:
                i = int(a[3])
                ss = self.rsamples(r) if r else []
                p = ss[i] if i < len(ss) else 0
            self.h[h], self.local[h], self.frm[h] = p, False, a[2]
            if o == "get":
                self.emit("get %d %s %s -> %s" % (h, a[2], a[3],
                                                  self.slabel(p)))
            else:
                self.emit("at %d %s %d -> %s" % (h, a[2], int(a[3]),
                                                 self.slabel(p)))
            return False
        self.emit(" ".join([o, self.slabel(s)] + a[2:]))
        if not s:
            return False
        if o == "delete":
            e.call(F_SAMPLE_DTOR, s, 2 if self.local.get(h) else 3)
            self.h[h] = 0
            return True
        if o == "init":
            e.call(F_INIT, s, *self.strs(a[2], a[3]))
            return True
        if o == "initcopy":
            e.call(F_INIT_COPY, s, self.h.get(int(a[2]), 0))
            return True
        if o in ("initcb", "setcb"):
            e.call(F_INIT_CB if o == "initcb" else F_SETCB, s,
                   CB.get(a[2], 0), int(a[3], 0))
            return True
        if o in ("setname", "setbank"):
            e.call(F_SETNAME if o == "setname" else F_SETBANK, s,
                   *self.strs(a[2]))
            return True
        if o == "setrate":
            e.put32(s, int(a[2], 0))
            return True
        if o == "lockvoice":
            e.call(F_LOCKVOICE, s)
            return True
        if o == "play":
            self.setf(a[2], a[3], a[4])
            self.emit("  -> %s" % self.vlabel(e.call(F_PLAY, s)))
            return True
        if o == "playn":
            (p,) = self.strs(a[2])
            self.emit("  -> %s" % self.vlabel(
                e.call(F_PLAYN, s, p, int(a[3], 0), int(a[4], 0))))
            return True
        if o == "stop":
            e.call(F_STOP, s)
            return True
        if o in ("pause", "mute"):
            e.call(F_PAUSE if o == "pause" else F_MUTE, s,
                   1 if int(a[2]) else 0)
            return True
        if o == "fade":
            self.setf(a[2])
            e.call(F_FADE, s, int(a[3], 0))
            return True
        if o in ("setvol", "setscale", "setpan"):
            self.setf(a[2])
            e.call({"setvol": F_SETVOL, "setscale": F_SETSCALE,
                    "setpan": F_SETPAN}[o], s)
            return True
        if o == "setpitch":
            self.setf(a[2])
            self.emit("  -> %d" % e.call(F_SETPITCH, s))
            return True
        if o == "setaz":
            e.call(F_SETAZ, s, int(a[2], 0))
            return True
        if o == "cat":
            e.call(F_SETCAT, s, int(a[2], 0))
            return True
        if o == "supdate":
            e.call(F_SUPDATE, s)
            return True
        if o == "calcpitch":
            self.setf(a[2])
            self.emit("  -> %u" % (e.call(F_CALCPITCH, s) & M32))
            return False
        if o == "calcvol":
            self.setf(a[2])
            self.emit("  -> %u" % (e.call(F_CALCVOL, s) & 0xffff))
            return False
        if o == "calcpan":
            self.setf(a[2])
            v = e.call(F_CALCPAN, s) & 0xff
            self.emit("  -> %d" % (v - 256 if v & 0x80 else v))
            return False
        if o in ("scaled", "getvol", "getpitch"):
            e.call({"scaled": F_SCALED, "getvol": F_GETVOL,
                    "getpitch": F_GETPITCH}[o], s)
            self.emit("  -> %08x" % (e.fpr[0] & M32))
            return False
        if o == "isplaying":
            self.emit("  -> %d" % (1 if e.call(F_ISPLAYING, s) else 0))
            return False
        if o == "channels":
            self.emit("  -> %u" % (e.call(F_CHANNELS, s) & M32))
            return False
        if o == "find":
            r = self.region(a[2])
            q = self.strs(a[2], a[3])[1]
            p = e.call(F_REGION_SAMPLE, r, q) & M32 if r else 0
            self.emit("  -> %s" % self.slabel(p))
            return False
        raise ValueError(o)


def model(lines):
    m = Model()
    for ln in lines:
        if ln and m.run(ln.split("|")):
            m.dump()
    return m.out


# ============================================================== the script

def F(x):
    return "0x%08x" % fbits(x)


VOLS = [0.0, 1.0, 0.5, 0.25, 0.75, 0.1, 0.999, 1.5, 2.0, -0.5, 0.3333]
PANS = [0.0, 0.5, -0.5, 0.25, -0.25, 0.1, -0.1, 0.7, -0.9, 0.49]
PITCHES = [0.0, 1.0, -1.0, 0.5, -0.5, 2.0, -2.0, 2.5, -2.5, 3.0, -3.0,
           6.9, -6.9, 7.0, -7.0, 8.0, -9.0, 1.99, -1.99, 0.01, 4.25, -5.75]

BANKS = [
    ("common", 0, [("HORN", 1, 22050, 16000), ("SIREN", 1, 32000, 12000),
                   ("BEEP", 1, 11025, 8000)]),
    ("CARS", 0, [("ENG_LO", 1, 22050, 16383), ("ENG_HI", 1, 44100, 9000),
                 ("SKID", 2, 22050, 14000), ("CRASH", 1, 16000, 30000),
                 ("Wind", 1, 8000, 5000)]),
    ("SPEECH", 1, [("COP1", 1, 22050, 16383), ("COP2", 2, 24000, 15000)]),
    ("_STREAM", 0, [("MUSIC", 1, 48000, 16383)]),
    ("_STREAMS", 0, [("AMB", 2, 32000, 12000)]),
    ("A_VERY_LONG_REGION_NAME_FOR_THE_CHECK_X", 0,
     [("LONGPATCH_NAME_THAT_RUNS_PAST_32_BYTES", 1, 22050, 10000),
      ("P2", 1, 22050, 10000)]),
    ("WORLD", 1, [("BIRD", 1, 11025, 6000), ("WATER", 2, 22050, 7000),
                  ("FIRE", 1, 22050, 8000)]),
]


class Script(object):
    def __init__(self):
        self.lines = []

    def op(self, *a):
        self.lines.append("|".join(str(x) for x in a))

    def banks(self, voices=24):
        self.op("voices", voices)
        for name, lazy, pats in BANKS:
            self.op("bank", name, lazy,
                    *("%s:%d:%d:%d" % p for p in pats))

    def boot(self, cb="C", data="0x00c0ffee"):
        self.op("boot", cb, data)


def basic_cases(sc):
    sc.banks(voices=8)
    sc.op("status")
    sc.op("update")                     # before Initialize: nothing
    sc.boot()
    sc.op("status")
    sc.op("mode", 0)
    sc.op("mode", 1)
    sc.op("mode", 2)
    sc.op("mode", 3)
    sc.op("mode", -1)
    sc.op("path", "cdrom0:\\AUDIO\\")
    sc.op("path", "x" * 70)
    sc.op("path", "host0:SOUND/")
    for c in (0, 1, 15, 16, 17, 255):
        sc.op("getcatvol", c)
    sc.op("load", "common")
    sc.op("load", "CARS")               # one already pending
    sc.op("update")
    sc.op("common")
    sc.op("region", "common")
    sc.op("region", "COMMON")
    sc.op("load", "CARS")
    sc.op("update")
    sc.op("load", "BADBANK")
    sc.op("update")
    sc.op("load", "SPEECH")             # lazy: stays pending
    sc.op("update")
    sc.op("update")
    sc.op("load", "WORLD")
    sc.op("arrive", "SPEECH")
    sc.op("update")
    sc.op("load", "A_VERY_LONG_REGION_NAME_FOR_THE_CHECK_X")
    sc.op("update")
    sc.op("region", "A_VERY_LONG_REGION_NAME_FOR_THE_CHECK_X")
    sc.op("region", "A_VERY_LONG_REGION_NAME_FOR_THE_CHECK_")
    sc.op("region", "A_VERY_LONG_REGION_NAME_FOR_THE_CHECK")
    sc.op("region", "A_VERY_LONG_REGION_NAME_FOR_THE_CHEC")
    sc.op("region", "A_VERY_LONG_REGION_NAME_FOR_THE_")
    sc.op("load", "_STREAM")
    sc.op("update")
    sc.op("load", "_STREAMS")
    sc.op("update")
    sc.op("load", "CARS")               # a second region of the same bank
    sc.op("update")

    sc.op("get", 0, "common", "HORN")
    sc.op("get", 1, "common", "siren")
    sc.op("get", 2, "CARS", "eng_lo")
    sc.op("get", 3, "CARS", "SKID")
    sc.op("get", 4, "CARS", "NOPE")
    sc.op("get", 5, "SPEECH", "COP2")
    sc.op("get", 6, "_STREAM", "MUSIC")
    sc.op("get", 7, "_STREAMS", "AMB")
    sc.op("at", 8, "A_VERY_LONG_REGION_NAME_FOR_THE_CHECK_X", 0)
    sc.op("at", 9, "CARS", 4)
    sc.op("find", 0, "CARS", "wind")
    sc.op("find", 0, "CARS", "WIND ")
    sc.op("find", 0, "NOREGION", "X")
    for h in range(10):
        sc.op("channels", h)
        sc.op("scaled", h)
        sc.op("isplaying", h)

    # play and its paths
    sc.op("play", 0, F(1.0), F(0.0), F(0.0))
    sc.op("play", 0, F(0.5), F(0.25), F(1.0))   # replays on its voice
    sc.op("isplaying", 0)
    sc.op("getvol", 0)
    sc.op("getpitch", 0)
    sc.op("setvol", 0, F(0.3))
    sc.op("setpan", 0, F(-0.4))
    sc.op("setpitch", 0, F(-1.5))
    sc.op("setaz", 0, 270)
    sc.op("setscale", 0, F(0.5))
    sc.op("pause", 0, 1)
    sc.op("pause", 0, 1)
    sc.op("pause", 0, 0)
    sc.op("mute", 0, 1)
    sc.op("mute", 0, 1)
    sc.op("getvol", 0)
    sc.op("mute", 0, 0)
    sc.op("pause", 0, 1)
    sc.op("end", 7)                     # no update between: Play finds
    sc.op("play", 0, F(1.0), F(0.0), F(0.0))    # its voice, paused
    sc.op("play", 3, F(1.0), F(0.5), F(-2.0))   # two channels
    sc.op("play", 6, F(0.8), F(0.0), F(0.0))    # a stream
    sc.op("play", 7, F(0.8), F(0.0), F(0.0))
    sc.op("play", 4, F(1.0), F(0.0), F(0.0))    # no sample
    sc.op("play", 2, F(1.0), F(0.0), F(0.0))
    sc.op("play", 1, F(1.0), F(0.0), F(0.0))
    sc.op("play", 5, F(1.0), F(0.0), F(0.0))    # out of channels
    sc.op("update")
    sc.op("end", 7)
    sc.op("update")
    sc.op("stop", 0)
    sc.op("stop", 0)
    sc.op("update")
    sc.op("play", 5, F(1.0), F(0.0), F(0.0))
    sc.op("catvol", 0, F(0.5))
    sc.op("cat", 2, 3)
    sc.op("catvol", 3, F(0.25))
    sc.op("catvol", 16, F(0.25))
    sc.op("getcatvol", 3)
    sc.op("setvol", 2, F(1.0))
    sc.op("scaled", 2)

    # fades
    sc.op("fade", 2, F(0.0), 20)
    sc.op("fade", 2, F(1.0), 33)
    for _ in range(4):
        sc.op("update")
    sc.op("fade", 2, F(0.1), 100)
    for _ in range(8):
        sc.op("update")
    sc.op("fade", 1, F(1.0), 1000)
    sc.op("supdate", 1)
    sc.op("fade", 9, F(1.0), 500)               # no voice

    # the near end of a stream, and the callbacks
    sc.op("setcb", 6, "A", "0x1234")
    sc.op("near", 4, 1)
    sc.op("update")
    sc.op("fade", 6, F(0.2), 200)
    sc.op("update")
    sc.op("update")
    sc.op("near", 4, 0)
    sc.op("stop", 6)
    sc.op("update")

    # locked voices
    sc.op("lockvoice", 1)
    sc.op("end", 0)
    sc.op("end", 1)
    sc.op("update")
    sc.op("play", 1, F(1.0), F(0.0), F(3.0))
    sc.op("stop", 1)
    sc.op("update")
    sc.op("play", 1, F(1.0), F(0.0), F(3.0))
    sc.op("end", 1)
    sc.op("update")

    # new, local, initialisation
    sc.op("new", 20, 0)
    sc.op("new", 21, 1)
    sc.op("local", 22, 0)
    sc.op("local", 23, 1)
    sc.op("init", 20, "HORN", "common")
    sc.op("init", 21, "MUSIC", "_STREAM")
    sc.op("init", 22, "_MOVIE", "common")
    sc.op("init", 23, "X", "_MOVIE")
    sc.op("setrate", 21, 30000)
    sc.op("setrate", 23, 44100)
    for h in (20, 21, 22, 23):
        sc.op("channels", h)
        sc.op("scaled", h)
        for p in PITCHES:
            sc.op("calcpitch", h, F(p))
    sc.op("setname", 20, "N" * 40)
    sc.op("setbank", 20, "_FOO")
    sc.op("channels", 20)
    sc.op("setbank", 20, "B" * 31)
    sc.op("setbank", 20, "common")
    sc.op("setname", 20, "SIREN")
    sc.op("initcopy", 22, 2)
    sc.op("initcb", 23, "B", "0xdeadbeef")
    sc.op("initcopy", 21, 22)
    sc.op("play", 20, F(1.0), F(0.0), F(0.0))
    sc.op("playn", 22, "ENG_HI", 100, 2000)
    sc.op("playn", 23, "MUSIC", 0, 0)
    sc.op("update")
    sc.op("delete", 20)
    sc.op("delete", 22)
    sc.op("new", 24, 0)
    sc.op("delete", 21)
    sc.op("delete", 23)
    sc.op("new", 25, 2)
    sc.op("new", 26, -1)
    sc.op("delete", 24)

    # unloading what is playing
    sc.op("play", 2, F(1.0), F(0.0), F(0.0))
    sc.op("unload", "CARS")
    sc.op("update")
    sc.op("unload", "NOREGION")
    sc.op("unload", "common")
    sc.op("common")
    sc.op("load", "common")
    sc.op("update")
    sc.op("common")
    sc.op("unload", "CARS")
    sc.op("load", "CARS")
    sc.op("update")

    # two voices locked where there are none: both have 0xfffc, and the
    # second takes the first's record from it
    sc.op("new", 30, 0)
    sc.op("init", 30, "HORN", "common")
    sc.op("new", 31, 0)
    sc.op("init", 31, "BEEP", "common")
    sc.op("voices", 0)
    sc.op("lockvoice", 30)
    sc.op("lockvoice", 31)
    sc.op("voices", 24)
    sc.op("delete", 31)
    sc.op("delete", 30)

    # GetVolume at volumes where a multiply by the rounded reciprocal and
    # a division by 16383 part
    sc.op("new", 35, 0)
    sc.op("init", 35, "HORN", "common")
    sc.op("play", 35, F(1.0), F(0.0), F(0.0))
    for v in (1025, 1029, 4097, 9001, 12289, 16383, 65535):
        sc.op("chvol", v)
        sc.op("getvol", 35)
    sc.op("delete", 35)

    # A region name past 32 characters is cut to 32, and its samples are
    # the cut name's bank's: the 35-character bank's region has the
    # 32-character bank's patches. The lookup by patch folds 'z' too.
    sc.op("bank", "B" * 32, 0, "FIZZ:1:22050:9000", "PX:1:11025:8000")
    sc.op("bank", "B" * 35, 0, "FIZZ:1:44100:7000")
    sc.op("load", "B" * 32)
    sc.op("update")
    sc.op("load", "B" * 35)
    sc.op("update")
    sc.op("get", 32, "B" * 32, "fizz")
    sc.op("get", 33, "B" * 32, "FIZz")
    sc.op("at", 34, "B" * 32, 1)
    sc.op("unload", "B" * 35)
    sc.op("unload", "B" * 32)
    sc.op("unload", "B" * 32)


def region_cases(sc):
    """More than 16 regions, so a second fragment, which an erase crosses;
    and erases of no region with room past the count and without."""
    sc.banks(voices=24)
    sc.boot("C", "0x5eed")
    sc.op("arrive", "WORLD")
    sc.op("arrive", "SPEECH")
    for b in ["common"] + ["CARS"] * 15 + ["WORLD", "_STREAM", "_STREAMS",
                                          "SPEECH"]:
        sc.op("load", b)
        sc.op("update")
    sc.op("region", "common")
    sc.op("unload", "_STREAMS")         # in the second fragment
    sc.op("region", "common")
    sc.op("common")
    sc.op("unload", "NOREGION")
    sc.op("unload", "NOREGION")
    sc.op("load", "_STREAMS")
    sc.op("update")
    sc.op("unload", "NOREGION")
    sc.op("unload", "CARS")
    sc.op("unload", "_STREAMS")


def calc_cases(sc, rng):
    sc.banks(voices=24)
    sc.boot("0", "0")
    sc.op("load", "CARS")
    sc.op("update")
    sc.op("get", 0, "CARS", "ENG_LO")
    sc.op("get", 1, "CARS", "ENG_HI")
    sc.op("local", 2, 1)
    sc.op("init", 2, "X", "CARS")
    sc.op("setrate", 2, 12345)
    sc.op("local", 3, 1)
    sc.op("setrate", 3, 0xfffffff0)
    xs = [i / 64.0 for i in range(-600, 601)]
    xs += [rng.uniform(-12, 12) for _ in range(300)]
    xs += [1e9, -1e9, 1e-30, -1e-30, 2.0 - 1e-7, -2.0 + 1e-7, 7.0 - 1e-6]
    # past +-127 the whole part wraps in its byte before the range test
    xs += [256.5, 256.25, -256.5, 512.75, 263.5, 300.0, 130.0, -129.5]
    for h in (0, 1, 2, 3):
        for x in xs[::(1 if h == 0 else 3)]:
            sc.op("calcpitch", h, F(x))
    ps = [i / 128.0 for i in range(-160, 161)] + [rng.uniform(-3, 3)
                                                   for _ in range(60)]
    ps += [1e9, -1e9]
    for x in ps:
        sc.op("calcpan", 0, F(x))
    vs = [i / 64.0 for i in range(-20, 150)] + [rng.uniform(-1, 4)
                                                 for _ in range(60)]
    vs += [1e9, -1e9]
    for h in (0, 1, 2):
        for x in vs:
            sc.op("calcvol", h, F(x))
    for c in range(16):
        sc.op("catvol", c, F(rng.choice(VOLS)))
    for h in (0, 1, 2):
        for c in (0, 3, 15, 16, 200):
            sc.op("cat", h, c)
            for s in (1.0, 0.5, 0.0, 1.25):
                sc.op("setscale", h, F(s))
                sc.op("scaled", h)
                sc.op("calcvol", h, F(0.7))


def random_cases(sc, rng, runs=30, steps=120):
    names = {"common": ["HORN", "SIREN", "BEEP"],
             "CARS": ["ENG_LO", "ENG_HI", "SKID", "CRASH", "Wind"],
             "SPEECH": ["COP1", "COP2"], "_STREAM": ["MUSIC"],
             "_STREAMS": ["AMB"], "WORLD": ["BIRD", "WATER", "FIRE"]}
    for run in range(runs):
        sc.banks(voices=rng.choice((4, 6, 8, 12, 24, 48)))
        sc.boot(rng.choice(("C", "0")), "0x%x" % rng.randrange(1 << 32))
        loaded = []
        handles = set()
        for step in range(steps):
            r = rng.random()
            if r < 0.08:
                b = rng.choice(list(names) + ["BADX"])
                sc.op("load", b)
                if rng.random() < 0.5:
                    sc.op("update")
                if b not in loaded:
                    loaded.append(b)
            elif r < 0.10:
                sc.op("arrive", rng.choice(("SPEECH", "WORLD")))
            elif r < 0.13 and loaded:
                b = rng.choice(loaded)
                sc.op("unload", b)
                if rng.random() < 0.3:
                    loaded.remove(b)
            elif r < 0.25:
                sc.op("update")
            elif r < 0.33 and loaded:
                b = rng.choice(loaded)
                h = rng.randrange(12)
                if b in names and rng.random() < 0.8:
                    sc.op("get", h, b, rng.choice(names[b]))
                else:
                    sc.op("at", h, b, rng.randrange(6))
                handles.add(h)
            elif r < 0.36:
                h = 12 + rng.randrange(6)
                sc.op(rng.choice(("new", "local")), h, rng.choice((0, 1)))
                b = rng.choice(list(names))
                sc.op("init", h, rng.choice(names[b]), b)
                if rng.random() < 0.3:
                    sc.op("setcb", h, rng.choice("AB"), "0x%x" % h)
                handles.add(h)
            elif r < 0.38:
                sc.op("end", rng.randrange(48))
            elif r < 0.40:
                sc.op("near", rng.randrange(48), rng.choice((0, 1)))
            elif r < 0.42:
                sc.op("catvol", rng.randrange(18), F(rng.choice(VOLS)))
            elif handles:
                h = rng.choice(sorted(handles))
                k = rng.random()
                if k < 0.30:
                    sc.op("play", h, F(rng.choice(VOLS)),
                          F(rng.choice(PANS)), F(rng.choice(PITCHES)))
                elif k < 0.38:
                    sc.op("stop", h)
                elif k < 0.45:
                    sc.op("fade", h, F(rng.choice(VOLS)),
                          rng.choice((0, 16, 33, 50, 100, 500, 2000)))
                elif k < 0.50:
                    sc.op("setvol", h, F(rng.choice(VOLS)))
                elif k < 0.54:
                    sc.op("setpan", h, F(rng.choice(PANS)))
                elif k < 0.58:
                    sc.op("setpitch", h, F(rng.choice(PITCHES)))
                elif k < 0.62:
                    sc.op("pause", h, rng.choice((0, 1)))
                elif k < 0.66:
                    sc.op("mute", h, rng.choice((0, 1)))
                elif k < 0.69:
                    sc.op("lockvoice", h)
                elif k < 0.72:
                    sc.op("setscale", h, F(rng.choice(VOLS)))
                elif k < 0.75:
                    sc.op("cat", h, rng.randrange(17))
                elif k < 0.78:
                    sc.op("supdate", h)
                elif k < 0.81:
                    sc.op("setaz", h, rng.randrange(360))
                elif k < 0.84:
                    sc.op("isplaying", h)
                elif k < 0.87:
                    sc.op("getvol", h)
                elif k < 0.90:
                    sc.op("setcb", h, rng.choice("AB0"), "0x%x" % h)
                elif k < 0.93 and h >= 12:
                    sc.op("delete", h)
                    handles.discard(h)
                elif k < 0.96:
                    sc.op("playn", h, rng.choice(["HORN", "ENG_HI", "MUSIC",
                                                  "NOPE"]),
                          rng.randrange(100), rng.randrange(1000))
                else:
                    sc.op("pause", h, 1)
        for b in loaded:
            sc.op("unload", b)
        sc.op("update")
        # a new run starts the bSound again: these are separate processes
        sc.op("__end__")


def script_runs():
    """Each run is a separate process in both the harness and the model:
    bSound is a singleton, and its pools are made once."""
    runs = []
    sc = Script()
    basic_cases(sc)
    runs.append(sc.lines)
    sc = Script()
    calc_cases(sc, random.Random(0x27850))
    runs.append(sc.lines)
    sc = Script()
    region_cases(sc)
    runs.append(sc.lines)
    sc = Script()
    random_cases(sc, random.Random(0x2776c0))
    cur = []
    for ln in sc.lines:
        if ln == "__end__":
            runs.append(cur)
            cur = []
        else:
            cur.append(ln)
    return runs


# ================================================================ running

def build_harness(tmp, name="bsound_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, sc_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(sc_path)], stdout=fh,
                               stderr=subprocess.PIPE, text=True,
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


def write_inputs(d):
    runs = script_runs()
    paths = []
    for i, lines in enumerate(runs):
        p = Path(d) / ("script%02d.txt" % i)
        p.write_bytes((NL.join(lines) + NL).encode("latin-1"))
        paths.append(p)
    return runs, paths


def model_all(runs):
    out = []
    for i, lines in enumerate(runs):
        out.append("== run %d" % i)
        out += model(lines)
    return out


def harness_all(exe, paths, tmp):
    out, rc = [], 0
    for i, p in enumerate(paths):
        o = Path(tmp) / ("harness%02d.txt" % i)
        r = run_harness(exe, p, o)
        rc = rc or r
        out.append("== run %d" % i)
        out += o.read_text(encoding="latin-1").splitlines()
    return out, rc


# ============================================================= mutations

P = BSC
MUTATIONS = [
    # -- the vectors -----------------------------------------------------------
    ("vec push doubles", P,
     "vec_grow_to(v, v->capacity * 2 > 1 ? v->capacity * 2 : 1);",
     "vec_grow_to(v, v->capacity + 1);"),
    ("vec find whole capacity", P,
     "    for (i = 0; i < v->capacity; i++)\n        if (v->items[i] == p)",
     "    for (i = 0; i < v->count; i++)\n        if (v->items[i] == p)"),
    ("vec erase past count", P,
     "    if (i < 0 || i >= v->capacity || v->count <= 0)",
     "    if (i < 0 || i >= v->count || v->count <= 0)"),
    ("vec erase empty", P,
     "    if (i < 0 || i >= v->capacity || v->count <= 0)",
     "    if (i < 0 || i >= v->capacity)"),
    ("vec erase last slot", P,
     "    for (k = i; k < v->capacity - 1; k++)",
     "    for (k = i; k < v->count - 1; k++)"),
    ("vec erase from index", P,
     "    for (k = i; k < v->capacity - 1; k++)",
     "    for (k = i + 1; k < v->capacity - 1; k++)"),
    ("regions reserve 16", P,
     "    vec_grow_to(&s->regions, 16);",
     "    vec_grow_to(&s->regions, 4);"),
    ("unload erases NULL", P,
     "    vec_erase(&s->regions, r);\n    if (r != NULL)\n        bregion_delete(r);",
     "    if (r == NULL)\n        return;\n    vec_erase(&s->regions, r);\n"
     "    bregion_delete(r);"),

    # -- bVoiceMgr ---------------------------------------------------------
    ("voice held id taken over", P,
     "        if (v->sample != NULL && v->id == id) {",
     "        if (0) {"),
    ("voice held id released", P,
     "            bsample_release_voice(v->sample);\n            v->id = id;",
     "            v->id = id;"),
    ("voice update locked kept", P,
     "            if (!s->voiceLock || s->voiceLockPlaying)",
     "            if (!s->voiceLock)"),
    ("voice update locked playing", P,
     "            if (!s->voiceLock || s->voiceLockPlaying)",
     "            if (s->voiceLockPlaying)"),
    ("voice update samples", P,
     "        }\n        bsample_update(s);\n    }",
     "        }\n    }"),

    # -- bSound --------------------------------------------------------------
    ("categories start full", P,
     "        s->categoryVolume[i] = 1.0f;",
     "        s->categoryVolume[i] = 0.5f;"),
    ("client data", P,
     "        s->client(event, what, s->clientData);",
     "        s->client(event, what, NULL);"),
    ("pending one slot", P,
     "    if (s->pendingCount > 0)\n        return 0;",
     "    if (s->pendingCount > 1)\n        return 0;"),
    ("bank load before pending", P,
     "    if (!bsnd_bank_load(s->driver, name))\n        return 0;\n"
     "    if (s->pendingCount > 0)\n        return 0;",
     "    if (s->pendingCount > 0)\n        return 0;\n"
     "    if (!bsnd_bank_load(s->driver, name))\n        return 0;"),
    ("pending waits for bank", P,
     "        if (!bsnd_bank_loaded(s->driver, s->pending[i]))\n"
     "            continue;\n", ""),
    ("common remembered", P,
     "            s->common = r;", "            (void)0;"),
    ("pending cleared", P,
     "        s->pending[s->pendingCount][0] = '\\0';", ""),
    ("pending name bound", P,
     "    strncpy(slot, name, sizeof(s->pending[0]) - 1);",
     "    strncpy(slot, name, 32);"),
    ("region loaded notified", P,
     "        notify_client(BSOUND_REGION_LOADED, r);\n", ""),
    ("region lookup exact", P,
     "        if (strcmp(bregion_name(r), name) == 0)\n            return r;",
     "        if (str_icmp(bregion_name(r), name) == 0)\n            return r;"),
    ("category bound", P,
     "    if (category >= 16)\n        return;",
     "    if (category >= 15)\n        return;"),
    ("category refresh volume", P,
     "            bsample_set_volume(smp, bsample_get_pitch(smp));",
     "            bsample_set_volume(smp, 1.0f);"),
    ("category refresh matching", P,
     "        if (smp != NULL && bsample_get_category(smp) == category)",
     "        if (smp != NULL)"),
    ("category default", P,
     "        return s->categoryVolume[category];\n    return 1.0f;",
     "        return s->categoryVolume[category];\n    return 0.0f;"),
    ("path 63", P,
     "    b_strncpy(s->path, path, 63);",
     "    b_strncpy(s->path, path, 62);"),
    ("mode stereo", P,
     "    case 1: bsnd_set_mode(s->driver, BSND_MODE_STEREO); break;",
     "    case 1: bsnd_set_mode(s->driver, BSND_MODE_PROLOGIC); break;"),
    ("mode other", P,
     "    default: break;\n    }\n}",
     "    default: bsnd_set_mode(s->driver, BSND_MODE_MONO); break;\n    }\n}"),
    ("update status gate", P,
     "    if (s->status != 1)\n        return;\n    // bSnd_DriverUpdate",
     "    // bSnd_DriverUpdate"),

    # -- bRegion -------------------------------------------------------------
    ("region name 32", P,
     "        b_strncpy(r->name, name, 32);",
     "        b_strncpy(r->name, name, 31);"),
    ("region samples' bank", P,
     "        bsample_initialize(s, patch != NULL ? patch : \"\", "
     "bregion_name(r));",
     "        bsample_initialize(s, patch != NULL ? patch : \"\", name);"),
    ("region delete front", P,
     "        BSample* s = (BSample*)r->samples.items[0];",
     "        BSample* s = (BSample*)r->samples.items[r->samples.count - 1];"),
    ("region delete unloads bank", P,
     "    bsnd_bank_unload(drv(), bregion_name(r));\n", ""),
    ("region sample any case", P,
     "        if (str_icmp(bsample_get_name(s), name) == 0)\n            return s;",
     "        if (strcmp(bsample_get_name(s), name) == 0)\n            return s;"),
    ("upper folds", P,
     "        v &= 0x5f;", "        v &= 0x7f;"),
    ("upper range", P,
     "    if ((uint32_t)(v - 97) < 26u)", "    if ((uint32_t)(v - 97) < 25u)"),

    # -- bSample: making and naming -----------------------------------------
    ("construct scale", P,
     "    s->scaleVolume = 1.0f;\n    s->currentVolume",
     "    s->scaleVolume = 0.5f;\n    s->currentVolume"),
    ("construct volume", P,
     "    s->currentVolume = 1.0f;\n    s->currentPan",
     "    s->currentVolume = 0.0f;\n    s->currentPan"),
    ("construct id", P,
     "    s->sampleId = VOICE_NONE;\n    s->field8",
     "    s->sampleId = 0;\n    s->field8"),
    ("destruct unlocks", P,
     "    s->voiceLock = 0;\n    bsample_stop(s);\n}",
     "    bsample_stop(s);\n}"),
    ("initialize _MOVIE", P,
     "    if (strcmp(\"_MOVIE\", name) != 0)\n", ""),
    ("initialize copy bank", P,
     "    bsample_set_bank_name(s, bsample_get_bank_name(other));\n", ""),
    ("lock voice locks", P,
     "    s->voiceLock = 1;\n    ch = ",
     "    s->voiceLock = 0;\n    ch = "),
    ("lock voice channels", P,
     "    ch = bsnd_lock_channels(drv(), (uint16_t)bsample_get_channels(s));\n"
     "    s->voice = voice_mgr_get_voice(ch, s);\n}",
     "    ch = bsnd_lock_channels(drv(), 1);\n"
     "    s->voice = voice_mgr_get_voice(ch, s);\n}"),
    ("name 31", P,
     "    b_strncpy(s->name, name, 31);", "    b_strncpy(s->name, name, 30);"),
    ("bank name 31", P,
     "    b_strncpy(s->bankName, bank, 31);",
     "    b_strncpy(s->bankName, bank, 30);"),

    # -- bSample: pan, pitch, volume ------------------------------------------
    ("pan stored", P,
     "    s->currentPan = pan;\n}", "}"),
    ("pan scale", P,
     "    return (int8_t)ee_trunc_w(pan * 255.0f);",
     "    return (int8_t)ee_trunc_w(pan * 127.0f);"),
    ("pitch stored", P,
     "    s->currentPitch = pitch;\n    return", "    return"),
    ("pitch no voice", P,
     "(int32_t)s->voice->id : 9999;", "(int32_t)s->voice->id : 0;"),
    ("pitch semis in a byte", P,
     "    int8_t semi = (int8_t)ee_trunc_w(pitch);",
     "    int32_t semi = ee_trunc_w(pitch);"),
    ("pitch rate for a type", P,
     "        base = s->rate;", "        base = 22050;"),
    ("pitch clamp test", P,
     "    if (abs((int32_t)semi) >= PITCH_OCTAVES - 1) {",
     "    if (abs((int32_t)semi) > PITCH_OCTAVES - 1) {"),
    ("pitch clamp high", P,
     "        if ((float)(PITCH_OCTAVES - 1) < pitch)\n"
     "            pitch = (float)(PITCH_OCTAVES - 1);",
     "        if ((float)(PITCH_OCTAVES - 1) < pitch)\n"
     "            pitch = (float)(PITCH_OCTAVES - 2);"),
    ("pitch clamp low", P,
     "            pitch = (float)-(PITCH_OCTAVES - 1);\n        semi",
     "            pitch = (float)-(PITCH_OCTAVES - 2);\n        semi"),
    ("pitch clamp semis", P,
     "        semi = (int8_t)ee_trunc_w(pitch);\n    }",
     "    }"),
    ("pitch fine range", P,
     "    if (-2.0f <= pitch && pitch <= 2.0f) {",
     "    if (-2.0f < pitch && pitch < 2.0f) {"),
    ("pitch fine step high", P,
     "* 64.0f) + 1]", "* 64.0f)]"),
    ("pitch table end", P,
     "16207, 16384,     0,\n};", "16207, 16384, 16384,\n};"),
    ("pitch rising slope", P,
     "        if (semi > 0)\n", "        if (semi >= 0)\n"),
    ("pitch falling slope", P,
     "                  + kOctave[semi + PITCH_OCTAVES - 1] * frac;",
     "                  + kOctave[semi + PITCH_OCTAVES] * frac;"),
    ("scale stored", P,
     "    s->scaleVolume = scale;\n    if", "    if"),
    ("scaled full for a type", P,
     "    uint16_t vol = 16383;\n    float cat;",
     "    uint16_t vol = 16384;\n    float cat;"),
    ("volume reciprocal", P,
     "#define VOLUME_RECIPROCAL 0x1.0004p-14f",
     "#define VOLUME_RECIPROCAL 0x1p-14f"),
    ("volume kept without voice", P,
     "    if (s->voice != NULL) {\n        uint16_t v;\n\n"
     "        s->currentVolume = volume;",
     "    s->currentVolume = volume;\n    if (s->voice != NULL) {\n"
     "        uint16_t v;\n"),
    ("volume rounds", P,
     "    return (uint16_t)ee_trunc_w(v * VOLUME_SCALE);",
     "    return (uint16_t)ee_trunc_w(v * VOLUME_SCALE + 0.5f);"),
    ("get volume divides", P,
     "             * VOLUME_RECIPROCAL;\n    return 0.0f;",
     "             / VOLUME_SCALE;\n    return 0.0f;"),
    ("azimuth passed", P,
     "        bsnd_set_voice_azimuth(drv(), s->voice->id, azimuth);",
     "        bsnd_set_voice_azimuth(drv(), s->voice->id, 0);"),

    # -- bSample: playing -----------------------------------------------------
    ("play named volume", P,
     "    return bsample_play(s, s->currentVolume, 0.0f, 0.0f);",
     "    return bsample_play(s, 1.0f, 0.0f, 0.0f);"),
    ("play named offset", P,
     "    s->offset = offset;\n", ""),
    ("play stops busy", P,
     "        if (bsnd_channel_busy(d, s->voice->id))\n"
     "            bsample_stop(s);\n    }",
     "    }"),
    ("play no channels", P,
     "        if (bsample_get_channels(s) == 0)\n            return NULL;\n",
     ""),
    ("play lock fails", P,
     "        if (ch == BSND_BAD_VOICE)\n            return NULL;",
     "        if (ch == BSND_NO_PATCH)\n            return NULL;"),
    ("play marks playing", P,
     "    s->voiceLockPlaying = 1;\n    s->paused = 0;",
     "    s->paused = 0;"),
    ("play unpauses", P,
     "    s->voiceLockPlaying = 1;\n    s->paused = 0;",
     "    s->voiceLockPlaying = 1;"),
    ("play stores volume", P,
     "    s->currentVolume = volume;\n    s->currentPan = pan;",
     "    s->currentPan = pan;"),
    ("pause needs busy", P,
     "    if (pause) {\n        if (bsnd_channel_busy(d, s->voice->id)) {",
     "    if (pause) {\n        if (1) {"),
    ("resume clears flag", P,
     "            bsnd_voice_resume(d, s->voice->id);\n"
     "            s->paused = pause;",
     "            bsnd_voice_resume(d, s->voice->id);"),
    ("stop keeps locked", P,
     "    if (!bsample_is_voice_locked(s)) {", "    if (1) {"),
    ("stop clears playing", P,
     "    s->voiceLockPlaying = 0;\n    bsnd_voice_stop",
     "    bsnd_voice_stop"),
    ("stop tells client", P,
     "    notify_client(BSOUND_SAMPLE_STOPPED, s);\n", ""),
    ("stop calls back", P,
     "    if (s->callback != NULL)\n"
     "        s->callback(BSOUND_SAMPLE_STOPPED, s, s->callbackData);\n", ""),
    ("stop unpauses", P,
     "    s->paused = 0;\n}\n\nvoid bsample_mute", "}\n\nvoid bsample_mute"),
    ("mute same state", P,
     "    if (s->voice == NULL || s->muted == (int32_t)mute)",
     "    if (s->voice == NULL)"),
    ("mute saves volume", P,
     "        s->volumeBeforeMuting = bsnd_get_voice_volume(d, s->voice->id);",
     "        s->volumeBeforeMuting = 16383;"),
    ("fade threshold", P,
     "    if (ms < 33) {", "    if (ms < 34) {"),
    ("fade immediate scaled", P,
     "        bsample_set_volume(s, bsample_get_scaled_volume(s) * volume);",
     "        bsample_set_volume(s, volume);"),
    ("fade target scaled", P,
     "        s->fadeTarget = volume * bsample_get_scaled_volume(s);",
     "        s->fadeTarget = volume;"),
    ("fade steps", P,
     "#define FADE_STEPS_PER_MS 0x1.eb6bf6p-5f",
     "#define FADE_STEPS_PER_MS 0x1.eb851ep-5f"),
    ("channels streams", P,
     "        if (strncmp(s->bankName, \"_STREAMS\", 8) == 0)\n"
     "            return 2;",
     "        if (strncmp(s->bankName, \"_STREAMS\", 8) == 0)\n"
     "            return 1;"),
    ("channels movie", P,
     "        if (strncmp(s->bankName, \"_MOVIE\", 7) == 0)\n            return 2;",
     "        if (strncmp(s->bankName, \"_MOVIE\", 7) == 0)\n            return 1;"),
    ("channels other stream", P,
     "        return 0;\n    }\n    return bsnd_get_patch_channels",
     "        return 1;\n    }\n    return bsnd_get_patch_channels"),
    ("update needs fade", P,
     "    if (s->voice == NULL || s->fadeAdjust == 0.0f)\n        return;",
     "    if (s->voice == NULL)\n        return;"),
    ("update stops falling", P,
     "        if (v < s->fadeTarget) {", "        if (v < s->fadeTarget - 0.01f) {"),
    ("update stops rising", P,
     "        if (s->fadeTarget < v) {", "        if (s->fadeTarget + 0.01f < v) {"),
    ("update ends fade", P,
     "            v = s->fadeTarget;\n            s->fadeAdjust = 0.0f;\n"
     "        }\n    } else {",
     "            v = s->fadeTarget;\n        }\n    } else {"),
    ("near end once", P,
     "        s->nearEndNotified = 1;\n", ""),
    ("near end needs callback", P,
     "    if (s->voice != NULL && !s->nearEndNotified && s->callback != NULL\n",
     "    if (s->voice != NULL && !s->nearEndNotified\n"),
    ("near end tells client", P,
     "        notify_client(BSOUND_SAMPLE_NEAR_END, s);\n", ""),
    ("get pitch is volume", P,
     "    return s->currentVolume;\n}\n\nvoid bsample_set_callback",
     "    return s->currentPitch;\n}\n\nvoid bsample_set_callback"),
]

EQUIVALENT = {
    # A slot past the count is read only by find, and only through whether
    # one of them is NULL: there is one exactly while the vector has not
    # been full since it last grew, its top slot never written -- which
    # leaving the slot at the count alone does not change.
    "vec erase last slot":
        "slots past the count matter only as 'is one NULL', which this "
        "does not change",
    # Play is the only way onto a record but LockVoice, and sets the flag;
    # Stop clears it and, without the lock, gives the record back. So a
    # record's unlocked sample with the flag clear has no voice of its own
    # (an orphaned record's, after a lock moved it), and its Stop returns
    # at once.
    "voice update locked playing":
        "an unlocked sample with the flag clear has no voice, and Stop on "
        "it does nothing",
}


def run_all_exe(paths, limit):
    def f(exe, out):
        texts = []
        for i, p in enumerate(paths):
            o = Path(str(out) + ".%02d" % i)
            r = mutpar.run_exe([exe, p], o, limit)
            if r != 0:
                return r
            texts.append("== run %d" % i)
            texts += o.read_text(encoding="latin-1").splitlines()
        Path(out).write_text(NL.join(texts) + NL, encoding="latin-1")
        return 0
    return f


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    indir = tempfile.TemporaryDirectory()
    runs, paths = write_inputs(indir.name)
    base_lines = model_all(runs)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        t0 = time.monotonic()
        got, rc = harness_all(exe, paths, tmp)
        took = time.monotonic() - t0
        if diff(base_lines, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(todo, SOURCES, "bsound_test",
                            run_all_exe(paths, limit), base_lines, diff,
                            EQUIVALENT, jobs)
    indir.cleanup()
    return mutpar.summarize(todo, only, EQUIVALENT, tally)


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

    with tempfile.TemporaryDirectory() as tmp:
        runs, paths = write_inputs(tmp)
        got = model_all(runs)
        exe = build_harness(tmp)
        harness, rc = harness_all(exe, paths, tmp)

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(got) + NL,
                                           encoding="latin-1")
        d.with_suffix(".harness").write_text(NL.join(harness) + NL,
                                             encoding="latin-1")

    n = diff(got, harness)
    print("%d runs, %d ops, %d lines, %d differ"
          % (len(runs), sum(len(r) for r in runs), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
