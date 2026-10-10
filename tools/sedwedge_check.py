#!/usr/bin/env python3
"""Cross-check 3DS Files/source/sedwedge.c against the retail image,
SLES_507.31.

**The model** is retail's own sedwedge.cpp run in retail_model.RetailEmu:
cSEDWedge's LoadDataFile, AddSentencePart, constructor, Initialize, Fade,
Mute, Cleanup, GetEventPending, QueueSentenceEvent, PlaySentence,
StopSentence, ClearEventQueue and Update (0x002056f0 .. 0x002062b4), its
callbacks S_TimerGetTick, S_SentencePartRequest and S_SampleCallback,
bSegment's constructor, Initialize, Cleanup, GetOffset and GetSize
(0x002761d0 .. 0x00276564), and Sound.obj's LoadLocalizedSpeechFiles
and UnLoadLocalizedSpeechFiles (0x001ae4d8, 0x001ae5e8). The harness
(tools/src/sedwedge_test.c) runs sedwedge.c's.

**The fakes**, the same on both sides, each printing what it is handed:
bFile's Open, FileSize, Read, Close and GetFile over a few made-up
files (a BAN of three banks, an EVENTS.EVT, each language's), any of
them missing when the script says; bMalloc and the frees, which name
each block; bSPrintf, silent; the speech library's calls (SPCH_Play
hands the script's clips to the request callback, one at a time;
CheckEventQueue, ResolveData and AddBank answer from the script); the
chain sample's making, SetCategory, the callback's Initialize, Pause,
Stop (which raises the callback's event 8 once one is set), Play,
SetVolume and AddToChain; and bSound's SetPath. bSound's GetStatus says
1 and its Printf is silent. SoundEnabled, the speech's flag and
RealTimeFrames are the script's.

**The script** constructs over a filled record; asks everything of a
wedge that is not loaded; initializes with the events missing, with
ResolveData failing and then in full, twice, and over each language and
past them, with the sound and the speech off; adds clips in and out of
the banks' range, by hand and through SPCH_Play, up to ten, with sizes
under the header's; updates with nothing pending, pending, playing,
stopped, paused and muted, at several clocks; plays, stops, clears,
fades and mutes in each state; raises the sample's events 4 and 8;
cleans a segment up by hand and asks the rule callbacks; and cleans up
and unloads.

**The port's own paths**, where retail would stop or crash, are the
model's by hand: a missing BAN ends Initialize after the game number and
the slot (retail's bGetFile asserts), and a full pool ends it after the
banks (PortStop; retail constructs on what the pool answers). bGetFile
answering nothing, over a stale bank count, is retail's own.

    python tools/sedwedge_check.py
    python tools/sedwedge_check.py --mutate [--only a,b]
    python tools/sedwedge_check.py --dump out/sedwedge
"""
import argparse
import os
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
BS = chr(92)

HARNESS = "tools/src/sedwedge_test.c"
SWC = "3DS Files/source/sedwedge.c"
SOURCES = [HARNESS, SWC]
HARNESS_TIMEOUT = 30
LIMIT = 2000000

GP = retail_model.RETAIL_GP
F = {
    "loaddata": 0x002056f0, "part": 0x002057d8, "ctor": 0x00205888,
    "tick": 0x00205a00, "req": 0x00205a28, "samplecb": 0x00205a58,
    "init": 0x00205ae8, "fade": 0x00205da8, "mute": 0x00205e00,
    "cleanup": 0x00205e58, "pending": 0x00205f48, "queue": 0x00205f90,
    "play": 0x00205fd8, "stop": 0x00206140, "clear": 0x00206190,
    "update": 0x002061e8, "load": 0x001ae4d8, "unload": 0x001ae5e8,
}
FNAMES = {
    0x00205998: "abort", 0x002059d0: "print", 0x00205a00: "tick",
    0x00205a18: "test", 0x00205a20: "set", 0x00205a28: "req",
    0x00205a58: "samplecb", 0x00205ae0: "evlog",
}

SOUNDENABLED, SPEECHON = GP - 23056, GP - 16552
FRAMES, BSOUNDP, POOLP = GP - 19600, GP - 13696, GP - 13816
SOUNDWEDGE = GP - 19016

SIZE = 2180
SEG_SIZE = 276
SAMPLE_SIZE = 188
EVLOG = 124

EVENTS = "Sound" + BS + "Speech" + BS + "Events.evt"
LANGS = ["English", "French", "German", "Italian", "Spanish"]


def speech(name, kind):
    return "Sound" + BS + "Speech" + BS + name + kind + ".pck"


def ban_bytes(nbanks, base):
    """A BAN file: `nbanks` 16-byte entries (the first's word 0 the count),
    each bank's offset in the file, 0, and its base in the DAT file; then
    the banks, 64 bytes each."""
    b = bytearray()
    for i in range(nbanks):
        w0 = nbanks if i == 0 else 0x5a5a0000 + i
        b += struct.pack("<4I", w0, 16 * nbanks + 64 * i, 0,
                         base + 0x1000 * i * i)
    for i in range(nbanks):
        b += bytes((i * 7 + k) & 0xff for k in range(64))
    return bytes(b)


def files():
    f = {EVENTS: bytes(range(40)) * 3}
    for i, lang in enumerate(LANGS):
        f[speech(lang, "BAN")] = ban_bytes(3 + (i % 3), 0x100 * (i + 1))
        f[speech(lang, "DAT")] = b"\0" * 64
    return f


def fbits(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


class PortStop(Exception):
    """Where the port stops and retail goes on into what would crash."""


class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        e.stub_bware()
        self.files = files()
        self.missing = set()
        self.handles = {}               # address -> name
        self.nfiles = 0
        self.blocks = []                # (address, size, name)
        self.check, self.resolve, self.handleq = [], [], []
        self.nexthandle = 0
        self.parts = []
        self.reqfn = 0
        self.cb = self.cbdata = 0
        self.nullget = self.nochain = False
        self.w = e.alloc(SIZE + 64, 16)
        self.e.mem[self.w:self.w + SIZE] = b"\0" * SIZE
        self.chain = e.alloc(SAMPLE_SIZE + 64, 16)
        self.vecs = e.alloc(16, 16)
        self.bsound = e.alloc(16, 16)
        self.slot = e.alloc(16, 16)
        self.reqbuf = e.alloc(32, 16)
        self.strs = e.alloc(16384, 16)
        e.put32(SOUNDENABLED, 1)
        e.put32(SPEECHON, 1)
        e.put32(FRAMES, 0)
        e.put32(BSOUNDP, self.bsound)
        e.put32(SOUNDWEDGE, 0)

        e.stub(0x002544c0, self.b_open)
        e.stub(0x002544e8, self.b_close)
        e.stub(0x00254550, self.b_filesize)
        e.stub(0x002547f0, self.b_read)
        e.stub(0x00254908, self.b_getfile)
        e.stub(0x002577c0, self.b_malloc)
        e.stub(0x00257850, self.b_free)
        e.stub(0x00114e98, self.b_free)
        e.stub(0x00251398, self.b_sprintf)
        e.stub(0x002512a8, self.say("vprintf"))
        e.stub(0x00277ea0, lambda em: 1)            # bSound::GetStatus
        e.stub(0x00278250, lambda em: 0)            # bSound::Printf
        e.stub(0x00250ac0, self.say("assert"))
        e.stub(0x00290920, self.spch_rate)
        e.stub(0x00290a68, self.spch_init)
        e.stub(0x00290bd8, self.spch_memsize)
        e.stub(0x00290be0, self.spch_bankmem)
        e.stub(0x002908c8, self.spch_vecs)
        e.stub(0x00294648, self.spch_evlog)
        e.stub(0x002909a0, self.spch_rules)
        e.stub(0x002908a8, self.spch_resolve)
        e.stub(0x00292678, self.spch_datinfo)
        e.stub(0x002910e8, self.spch_addbank)
        e.stub(0x00291f08, self.say("spch_clear"))
        e.stub(0x00291fc0, self.spch_check)
        e.stub(0x00292490, self.spch_choose)
        e.stub(0x002923e0, self.spch_play)
        e.stub(0x00290b48, self.say("spch_deinit"))
        e.stub(0x00257c80, self.new_chain)          # bOMalloc
        e.stub(0x00273098, lambda em: em.reg[4] & M32)  # bSample(char)
        e.stub(0x00273520, lambda em: 0)            # SetBankName
        e.stub(0x00273498, lambda em: 0)            # SetName
        e.stub(0x00273388, lambda em: 0)            # LockVoice
        e.stub(0x00273618, self.b_cat)
        e.stub(0x00273280, self.b_callback)
        e.stub(0x00274488, self.b_pause)
        e.stub(0x00274618, self.b_stop)
        e.stub(0x00273360, lambda em: 0)            # bSample::Cleanup
        e.stub(0x00274080, self.b_play)
        e.stub(0x00273d50, self.b_volume)
        e.stub(0x00206760, self.b_chain)
        e.stub(0x00277e38, self.b_setpath)

    def emit(self, s):
        self.out.append(s)

    def say(self, text):
        def stub(em):
            self.emit("  " + text)
            return 0
        return stub

    def cstr(self, a, n=256):
        b = bytearray()
        mem = self.e.mem
        while len(b) < n and mem[a]:
            b.append(mem[a])
            a += 1
        return b.decode("latin-1")

    def put_str(self, s):
        a = self.strs
        self.e.write(a, s.encode("latin-1") + b"\0")
        self.strs += (len(s) + 16) & ~15
        return a

    def name(self, a):
        a &= M32
        if a == 0:
            return "0"
        if a == self.w:
            return "wedge"
        if a == self.w + EVLOG:
            return "wedge.evlog"
        if a == self.chain:
            return "chain"
        if a == self.vecs:
            return "vecs"
        if a == self.bsound:
            return "bsound"
        if a == self.slot:
            return "slot"
        if a in self.handles:
            return self.handles[a]
        if a in FNAMES:
            return FNAMES[a]
        for p, n, nm in self.blocks:
            if p <= a < p + max(n, 1):
                return nm if a == p else "%s+%d" % (nm, a - p)
        return "?"

    def nested(self, fn, *args):
        e = self.e
        kept = (list(e.reg), list(e.fpr), e.hi, e.lo, e.hi1, e.lo1, e.sa,
                e.fcc, e.limit, e.icount)
        try:
            v = e.call(fn, *args, limit=LIMIT)
        finally:
            e.reg[:] = kept[0]
            e.fpr[:] = kept[1]
            (e.hi, e.lo, e.hi1, e.lo1, e.sa, e.fcc, e.limit,
             e.icount) = kept[2:]
        return v

    def block(self, size):
        p = self.e.alloc(max(size, 4) + 16, 16)
        self.e.mem[p:p + size] = b"\xa5" * size
        nm = "blk%d" % (len(self.blocks) + 1)
        self.blocks.append((p, size, nm))
        return p, nm

    # ---- bFile, bMem

    def b_open(self, em):
        nm = self.cstr(em.reg[4] & M32)
        if nm in self.missing or nm not in self.files:
            h, hn = 0, "0"
        else:
            self.nfiles += 1
            h = self.e.alloc(16, 16)
            hn = "f%d" % self.nfiles
            self.handles[h] = hn
            self.hfile = getattr(self, "hfile", {})
            self.hfile[h] = nm
        self.emit("  bopen %s -> %s" % (nm, hn))
        return h

    def b_close(self, em):
        self.emit("  bclose %s" % self.name(em.reg[4]))
        return 0

    def b_filesize(self, em):
        h = em.reg[4] & M32
        n = len(self.files[self.hfile[h]])
        self.emit("  bfilesize %s -> %d" % (self.name(h), n))
        return n

    def b_read(self, em):
        h, buf, n = em.reg[4] & M32, em.reg[5] & M32, s32(em.reg[6])
        data = self.files[self.hfile[h]][:n]
        self.e.write(buf, data)
        self.emit("  bread %s %s %d" % (self.name(h), self.name(buf), n))
        return 0

    def b_getfile(self, em):
        nm = self.cstr(em.reg[4] & M32)
        if self.nullget:
            self.nullget = False
            self.emit("  bgetfile %s %s %d -> 0" % (
                nm, self.name(em.reg[5]), s32(em.reg[6])))
            return 0
        data = self.files[nm]
        p, bn = self.block(len(data))
        self.e.write(p, data)
        self.emit("  bgetfile %s %s %d -> %s" % (
            nm, self.name(em.reg[5]), s32(em.reg[6]), bn))
        return p

    def b_malloc(self, em):
        n = s32(em.reg[4])
        p, bn = self.block(n)
        self.emit("  bmalloc %d %d %d -> %s" % (n, s32(em.reg[6]),
                                               s32(em.reg[7]), bn))
        return p

    def b_free(self, em):
        self.emit("  bfree %s" % self.name(em.reg[4]))
        return 0

    def b_sprintf(self, em):
        fmt = self.cstr(em.reg[5] & M32)
        s = fmt.replace("%s", self.cstr(em.reg[6] & M32))
        self.e.write(em.reg[4] & M32, s.encode("latin-1") + b"\0")
        return len(s)

    # ---- the speech library

    def spch_rate(self, em):
        self.emit("  spch_rate %d %d %d" % (s32(em.reg[4]), s32(em.reg[5]),
                                            s32(em.reg[6])))
        return 4410

    def spch_init(self, em):
        self.reqfn = em.reg[4] & M32
        self.emit("  spch_init %s %d %d" % (self.name(em.reg[4]),
                                            s32(em.reg[5]), s32(em.reg[6])))
        return 1

    def spch_memsize(self, em):
        n = s32(em.reg[4])
        self.emit("  spch_memsize %d" % n)
        return 4 * n

    def spch_bankmem(self, em):
        self.emit("  spch_bankmem %d %s" % (s32(em.reg[4]),
                                            self.name(em.reg[5])))
        return 0

    def spch_vecs(self, em):
        self.emit("  spch_vecs")
        return self.vecs

    def spch_evlog(self, em):
        self.emit("  spch_evlog %s %d %s" % (
            self.name(em.reg[4]), s32(em.reg[5]), self.name(em.reg[6])))
        return 1

    def spch_rules(self, em):
        self.emit("  spch_rules %s %s" % (self.name(em.reg[4]),
                                          self.name(em.reg[5])))
        return 0

    def spch_resolve(self, em):
        v = self.resolve.pop(0) if self.resolve else 1
        self.emit("  spch_resolve %s -> %d" % (self.name(em.reg[4]), v))
        return v

    def spch_datinfo(self, em):
        self.emit("  spch_datinfo %s" % self.name(em.reg[4]))
        self.e.put32(em.reg[5] & M32, 7)
        self.e.put32(em.reg[6] & M32, 9)
        return 0

    def spch_addbank(self, em):
        if self.handleq:
            v = self.handleq.pop(0)
        else:
            v = self.nexthandle
            self.nexthandle += 1
        self.emit("  spch_addbank %s -> %d" % (self.name(em.reg[4]), v))
        return v

    def spch_check(self, em):
        v = self.check.pop(0) if self.check else 0
        self.emit("  spch_check %d -> %d" % (s32(em.reg[4]), v))
        return v

    def spch_choose(self, em):
        self.emit("  spch_choose %d" % s32(em.reg[4]))
        return 1

    def spch_play(self, em):
        ch = s32(em.reg[4])
        parts, self.parts = self.parts, []
        self.emit("  spch_play %d (%d)" % (ch, len(parts)))
        for bank, off, size in parts:
            self.request(bank, off, size)
        return len(parts)

    def request(self, bank, off, size):
        e = self.e
        r = self.reqbuf
        e.write(r, struct.pack("<7I", bank & M32, off & M32, size & M32,
                               0x1234, 0, 5, 6))
        self.nested(self.reqfn, r)

    # ---- bSample, bSound

    def new_chain(self, em):
        self.emit("  newchain %s" % ("pool" if (em.reg[4] & M32)
                                     == self.e.u32(POOLP) else "?"))
        if self.nochain:
            # The pool is full: retail constructs on what it answers; the
            # port's Initialize stops there (PortStop, op "init").
            self.nochain = False
            raise PortStop()
        self.e.mem[self.chain:self.chain + SAMPLE_SIZE] = b"\0" * SAMPLE_SIZE
        self.cb = self.cbdata = 0
        return self.chain

    def b_cat(self, em):
        self.emit("  bcat %s %d" % (self.name(em.reg[4]), em.reg[5] & M32))
        return 0

    def b_callback(self, em):
        self.cb, self.cbdata = em.reg[5] & M32, em.reg[6] & M32
        self.emit("  bcallback %s %s %s" % (self.name(em.reg[4]),
                                            self.name(self.cb),
                                            self.name(self.cbdata)))
        return 0

    def b_pause(self, em):
        self.emit("  bpause %s %d" % (self.name(em.reg[4]),
                                      1 if em.reg[5] & 0xff else 0))
        return 0

    def b_stop(self, em):
        s = em.reg[4] & M32
        self.emit("  bstop %s" % self.name(s))
        if s and self.cb:
            self.nested(self.cb, 8, s, self.cbdata)
        return 0

    def b_play(self, em):
        self.emit("  bplay %s %08x %08x %08x" % (
            self.name(em.reg[4]), em.fpr[12], em.fpr[13], em.fpr[14]))
        return 0

    def b_volume(self, em):
        self.emit("  bvol %s %08x" % (self.name(em.reg[4]), em.fpr[12]))
        return 0

    def b_chain(self, em):
        self.emit("  addtochain %s %s %08x %08x %d" % (
            self.name(em.reg[4]), self.cstr(em.reg[5] & M32, 32),
            em.reg[6] & M32, em.reg[7] & M32, 1 if em.reg[8] & 0xff else 0))
        return 0

    def b_setpath(self, em):
        self.emit("  setpath %s %s" % (self.name(em.reg[4]),
                                       self.cstr(em.reg[5] & M32)))
        return 0

    # ---- the dumps

    def dump(self):
        e, w = self.e, self.w
        self.emit(
            "  nd init=%d bank=%s sb=%s count=%d game=%d mem=%s evt=%s "
            "dat=%s name=%s vecs=%s segs=%d sample=%s slot=%s status=%d "
            "pause=%d" % (
                s32(e.u32(w)), self.name(e.u32(w + 4)),
                self.name(e.u32(w + 8)), s32(e.u32(w + 12)),
                s32(e.u32(w + 16)), self.name(e.u32(w + 20)),
                self.name(e.u32(w + 24)), self.name(e.u32(w + 28)),
                self.cstr(w + 32, 31), self.name(e.u32(w + 64)),
                s32(e.u32(w + 108)), self.name(e.u32(w + 112)),
                self.name(e.u32(w + 116)), s32(e.u32(w + 120)),
                s32(e.u32(w + 2172))))
        if e.u32(w + 64) == self.vecs:
            self.emit("  vecs %s %s %s" % tuple(
                self.name(e.u32(self.vecs + 4 * k)) for k in range(3)))
        if e.u32(w + 112) == self.chain:
            self.emit("  rate %d" % e.u32(self.chain))

    def dump_segs(self):
        e, w = self.e, self.w
        for i in range(10):
            p = e.u32(w + 68 + 4 * i)
            nm = self.name(p)
            if nm.startswith("blk") and "+" not in nm:
                self.emit("  seg%d %s %s init=%d off=%08x size=%08x %d %d" % (
                    i, nm, self.cstr(p, 255), s32(e.u32(p + 256)),
                    e.u32(p + 260), e.u32(p + 264), e.u32(p + 268),
                    e.u32(p + 272)))
            else:
                self.emit("  seg%d %s" % (i, nm))

    def dump_bank(self):
        e, w = self.e, self.w
        sb = e.u32(w + 8)
        n = s32(e.u32(w + 12))
        if not sb or not self.name(sb).startswith("blk"):
            self.emit("  bank none")
            return
        for i in range(min(n, 8)):
            self.emit("  bank%d %s" % (i, " ".join(
                "%08x" % e.u32(sb + 16 * i + 4 * k) for k in range(4))))

    # ---- the ops

    def call(self, fn, *args):
        return self.e.call(F[fn], *args, limit=LIMIT)

    def call_at(self, addr, *args):
        return self.e.call(addr, *args, limit=LIMIT)

    def op(self, f):
        e, w = self.e, self.w

        def i(k):
            return int(f[k], 0) if k < len(f) else 0

        o = f[0]
        if o == "fill":
            e.mem[w:w + SIZE] = b"\xa5" * SIZE
        elif o == "ctor":
            self.call("ctor", w)
        elif o == "create":
            # InitializeSoundDriver's 0x001ae754: bMalloc(2180, its file,
            # 388, 16), the constructor, then gp-19016. The size is the
            # record's, which on the host is not the PS2's.
            self.emit("  bmalloc wedge 388 16")
            e.put32(SOUNDWEDGE, w)
            self.call("ctor", w)
        elif o == "nd":
            self.dump()
        elif o == "segs":
            self.dump_segs()
        elif o == "bank":
            self.dump_bank()
        elif o == "init":
            ban = f[4].replace("/", BS)
            names = [self.put_str(x.replace("/", BS)) for x in f[1:5]]
            if ban in self.missing or ban not in self.files:
                # The port's: a missing BAN stops Initialize before its
                # bGetFile, which would stop the game (retail asserts),
                # after the game number and the slot.
                e.put32(w + 16, 0)
                e.put32(w + 116, self.slot)
                e.put32(w, 0)
                v = 0
            else:
                try:
                    v = self.call("init", w, *(names + [self.slot]))
                except PortStop:
                    e.put32(w, 0)
                    v = 0
            self.emit("  = %d" % v)
        elif o == "load":
            self.call("load", i(1) & M32)
        elif o == "unload":
            self.call("unload")
        elif o == "loaddata":
            out = e.alloc(16, 16)
            e.put32(out, 0)
            v = self.call("loaddata", w, self.put_str(f[1].replace("/", BS)),
                          out)
            self.emit("  = %d %s" % (v, self.name(e.u32(out))))
        elif o == "part":
            self.call("part", w, i(1) & M32, i(2) & M32, i(3) & M32)
        elif o == "req":
            self.request(i(1), i(2), i(3))
        elif o in ("cleanup", "clear", "update"):
            v = self.call(o, w)
            if o == "clear":
                self.emit("  = %d" % v)
        elif o == "fade":
            e.fpr[12] = fbits(float(f[1]))
            self.call("fade", w)
        elif o == "mute":
            self.call("mute", w, i(1))
        elif o in ("pending", "queue", "stop"):
            self.emit("  = %d" % self.call(o, w, i(1)))
        elif o == "play":
            e.fpr[12] = fbits(float(f[2]) if len(f) > 2 else 1.0)
            self.emit("  = %d" % self.call("play", w, i(1)))
        elif o == "tick":
            self.emit("  tick %d" % self.call("tick"))
        elif o == "cb":
            self.nested(F["samplecb"], i(1), self.chain, w)
        elif o == "poke":
            off = {"init": 0, "segs": 108, "status": 120, "pause": 2172,
                   "count": 12}[f[1]]
            e.put32(w + off, i(2) & M32)
        elif o == "sound":
            e.put32(SOUNDENABLED, i(1) & M32)
        elif o == "speech":
            e.put32(SPEECHON, i(1) & M32)
        elif o == "frames":
            e.put32(FRAMES, i(1) & M32)
        elif o == "missing":
            self.missing.add(f[1].replace("/", BS))
        elif o == "present":
            self.missing.discard(f[1].replace("/", BS))
        elif o == "check":
            self.check.append(i(1))
        elif o == "resolve":
            self.resolve.append(i(1))
        elif o == "handle":
            self.handleq.append(i(1))
        elif o == "spchpart":
            self.parts.append((i(1), i(2), i(3)))
        elif o == "segclean":
            self.call_at(0x00276470, e.u32(w + 68 + 4 * i(1)))
        elif o == "rule":
            v = self.nested(0x00205a18, 0, i(1), i(2), i(3))
            self.nested(0x00205a20, 0, i(1), i(2), i(3))
            self.emit("  rule %d" % v)
        elif o == "nullget":
            self.nullget = True
        elif o == "nochain":
            self.nochain = True
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

def script():
    L = []
    a = L.append
    EN = ["Sound/Speech/Events.evt", "Sound/Speech/EnglishHDR.pck",
          "Sound/Speech/EnglishDAT.pck", "Sound/Speech/EnglishBAN.pck"]
    EVT = "Sound/Speech/Events.evt"

    def init(names=EN):
        a("init|" + "|".join(names))

    # The constructor over a filled record.
    a("fill")
    a("nd")
    a("ctor")
    a("nd")

    # Nothing loaded: each answers 0 and does nothing.
    a("pending|0")
    a("queue|0")
    a("play|0")
    a("stop|0")
    a("clear")
    a("update")
    a("cleanup")
    a("mute|1")
    a("nd")
    a("mute|0")
    a("fade|0.5")
    a("poke|status|2")
    a("sound|0")
    a("fade|0.25")
    a("sound|1")
    a("poke|status|1")
    a("nd")

    # Loaded with the events missing, then ResolveData failing.
    a("missing|" + EVT)
    init()
    a("nd")
    a("present|" + EVT)
    a("resolve|0")
    a("ctor")
    init()
    a("nd")
    a("cleanup")
    a("nd")

    # The port's: the BAN missing; the chain's pool full; bGetFile with no
    # memory over a stale bank count.
    a("ctor")
    a("missing|Sound/Speech/EnglishBAN.pck")
    a("poke|status|2")
    init()
    a("nd")
    a("present|Sound/Speech/EnglishBAN.pck")
    a("nochain")
    init()
    a("nd")
    a("bank")
    a("cleanup")
    a("nd")
    a("ctor")
    a("poke|count|5")
    a("nullget")
    init()
    a("nd")
    a("bank")
    a("part|0|0x10|0x20")
    a("nd")
    a("cleanup")
    a("nd")

    # In full, the DAT missing and the banks' handles made up.
    a("ctor")
    a("missing|Sound/Speech/EnglishDAT.pck")
    a("handle|-1")
    init()
    a("nd")
    a("bank")
    a("segs")
    a("present|Sound/Speech/EnglishDAT.pck")
    a("cleanup")
    a("nd")
    a("segs")
    init()
    a("nd")
    a("bank")
    a("segs")

    # The clock.
    a("tick")
    a("frames|90")
    a("update")
    a("tick")
    a("frames|7")
    a("update")
    a("tick")
    a("frames|123457")
    a("update")
    a("tick")
    a("frames|-61")
    a("update")
    a("tick")
    # Where a sixtieth times a thousand, or a division by 60, would round
    # to the millisecond under retail's.
    a("frames|15")
    a("update")
    a("tick")
    a("frames|489")
    a("update")
    a("tick")
    a("frames|10")

    # Nothing pending, then pending with no clips, then with two.
    a("update")
    a("check|1")
    a("update")
    a("nd")
    a("check|1")
    a("spchpart|0|0x100|0x400")
    a("spchpart|2|0x40|0x1000")
    a("update")
    a("nd")
    a("segs")

    # Playing: the update waits; the sample stops; then idle again.
    a("check|1")
    a("update")
    a("nd")
    a("cb|8")
    a("nd")
    a("update")
    a("nd")

    # The sample's event 4, with the sound and the speech on and off.
    a("cb|4")
    a("speech|0")
    a("cb|4")
    a("speech|1")
    a("sound|0")
    a("cb|4")
    a("sound|1")
    a("cb|5")
    a("cb|0")
    a("nd")

    # Clips by hand: in range, out of it, the size under the header's and
    # the offset wrapping.
    a("part|-1|0x10|0x200")
    a("part|3|0x10|0x200")
    a("part|7|0x10|0x200")
    a("part|1|0x10|0x200")
    a("part|2|0xfffffff0|0x20")
    a("req|0|0x30|0x31")
    a("req|3|0x30|0x31")
    a("req|-5|0x30|0x31")
    a("nd")
    a("segs")
    a("play|4|0.5")
    a("nd")
    a("segs")

    # Playing: mute, the update while paused, unmute, fade.
    a("mute|1")
    a("nd")
    a("frames|600")
    a("update")
    a("tick")
    a("mute|0")
    a("update")
    a("tick")
    a("fade|0.5")
    a("nd")
    a("fade|0.5")

    # Stopped (32) and the rest, through Fade, Mute, Play, Stop, Clear.
    a("poke|status|32")
    a("mute|1")
    a("mute|0")
    a("fade|1.0")
    a("nd")
    a("poke|status|32")
    a("sound|0")
    a("fade|1.0")
    a("sound|1")
    a("nd")
    a("play|0")
    a("nd")
    a("poke|status|8")
    a("mute|1")
    a("nd")
    a("mute|0")
    a("check|1")
    a("update")
    a("nd")
    a("poke|status|5")
    a("check|1")
    a("update")
    a("nd")
    a("stop|0")
    a("nd")
    a("clear")
    a("nd")
    a("poke|status|2")
    a("clear")
    a("nd")
    a("poke|status|32")
    a("clear")
    a("nd")

    # Ten clips, one sentence.
    for k in range(10):
        a("spchpart|%d|0x%x|0x%x" % (k % 3, 0x100 * k, 0x80 + 0x10 * k))
    a("check|1")
    a("update")
    a("nd")
    a("segs")
    a("cb|8")
    a("update")
    a("nd")

    # bSegment's Cleanup by hand, on one played already.
    a("segclean|3")
    a("segs")

    # The rule callbacks: none passes.
    a("rule|0|0|0")
    a("rule|5|-1|7")

    # Pending and Queue by hand.
    a("check|5")
    a("pending|3")
    a("check|0")
    a("pending|3")
    a("check|-1")
    a("pending|0")
    a("spchpart|1|0x8|0x60")
    a("queue|6")
    a("nd")
    a("play|6")
    a("nd")
    a("poke|segs|0")

    # The initialized flag: 0 and some other value.
    a("poke|init|0")
    a("update")
    a("pending|0")
    a("poke|init|7")
    a("poke|status|32")
    a("frames|1234")
    a("update")
    a("tick")
    a("nd")
    a("spchpart|1|0x8|0x60")
    a("queue|0")
    a("play|0")
    a("pending|0")
    a("stop|0")
    a("clear")
    a("cleanup")
    a("nd")
    a("poke|init|1")
    a("queue|0")
    a("nd")
    a("poke|segs|0")

    # LoadDataFile by hand.
    a("loaddata|" + EVT)
    a("loaddata|Sound/Speech/Nothing.evt")

    # Initialize again over a loaded wedge, muted: the chain is kept and
    # the mute let go.
    a("mute|1")
    init()
    a("nd")
    a("cleanup")
    a("nd")
    a("mute|0")
    a("update")
    a("nd")

    # The constructor zeroes the clock.
    a("frames|90")
    init()
    a("update")
    a("tick")
    a("ctor")
    a("tick")

    # Sound.obj's: each language, past them, the sound and speech off.
    a("poke|status|5")
    a("poke|pause|1")
    a("poke|init|1")
    a("create")
    a("nd")
    for lang in range(7):
        a("load|%d" % lang)
        a("nd")
        a("bank")
        a("unload")
        a("nd")
    a("load|-1")
    a("nd")
    a("speech|0")
    a("load|1")
    a("nd")
    a("speech|1")
    a("sound|0")
    a("load|2")
    a("nd")
    a("sound|1")
    a("load|2")
    a("sound|0")
    a("unload")
    a("nd")
    a("sound|1")
    a("unload")
    a("nd")
    a("unload")
    return L


# ================================================================= build

def build_harness(tmp, name="sedwedge_test"):
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
    sc.write_text(NL.join(lines) + NL)
    return sc


# ============================================================= mutations

MUTATIONS_HEADER = "# " + "=" * 61 + " mutations" + NL


def model_cached(lines):
    """model(lines)'s transcript, or its last one when nothing it reads
    has changed. Nothing past the mutations' header is the model's."""
    return mutpar.model_cached(lines, lambda sc: model(sc)[0],
                               cut=MUTATIONS_HEADER)


def _m(name, before, after, rel=SWC):
    return (name, rel, before, after)


_PLAY_TEST = ("    if (w->status == SEDWEDGE_PLAYING || w->status == SEDWEDGE_STOPPED) {\n"
              "        bsample_stop(w->sentenceSample);\n        w->status")
_FADE_TEST = ("    if (w->status == SEDWEDGE_PLAYING || w->status == SEDWEDGE_STOPPED) {\n"
              "        bsample_stop(w->sentenceSample);\n        // bSample")
_MUTE_TEST = ("    if (w->status == SEDWEDGE_PLAYING || w->status == SEDWEDGE_STOPPED)\n"
              "        bsample_pause")

MUTATIONS = [
    # bSegment.
    _m("seg-ctor-init", "line 19).\n    s->initialized = 0;",
       "line 19).\n    s->initialized = 1;"),
    _m("seg-ctor-off", "line 19).\n    s->initialized = 0;\n    s->offset = 0;",
       "line 19).\n    s->initialized = 0;\n    s->offset = 4;"),
    _m("seg-ctor-name",
       'strcpy(s->name, "<Not Initialized>");\n}\n\nvoid bsegment_initialize',
       'strcpy(s->name, "<Not initialized>");\n}\n\nvoid bsegment_initialize'),
    _m("seg-init-n", "b_strncpy(s->name, name, 255);",
       "b_strncpy(s->name, name, 3);"),
    _m("seg-init-flag", "    s->initialized = 1;\n    s->offset = offset;",
       "    s->initialized = 0;\n    s->offset = offset;"),
    _m("seg-init-off", "    s->offset = offset;", "    s->offset = offset + 1;"),
    _m("seg-init-size", "    s->size = size;", "    s->size = size + 1;"),
    _m("seg-init-268", "    s->size = size;\n    s->field268 = 0;",
       "    s->size = size;\n    s->field268 = 1;"),
    _m("seg-init-flags", "    s->flags = flags;", "    s->flags = 1;"),
    _m("seg-clean-init",
       "void bsegment_cleanup(BSegment *s)\n{\n    s->initialized = 0;",
       "void bsegment_cleanup(BSegment *s)\n{\n    s->initialized = 1;"),
    _m("seg-clean-name",
       'strcpy(s->name, "<Not Initialized>");\n}\n\nuint32_t',
       'strcpy(s->name, "<Not initialized>");\n}\n\nuint32_t'),
    _m("seg-get-off", "    return s->offset;", "    return s->size;"),
    _m("seg-get-size", "    return s->size;", "    return s->offset;"),

    # The library's calls.
    _m("tick-round", "return (uint32_t)(int32_t)gClockMs;",
       "return (uint32_t)(int32_t)(gClockMs + 0.5f);"),
    _m("tick-unsigned", "return (uint32_t)(int32_t)gClockMs;",
       "return (uint32_t)gClockMs;"),
    _m("rule-test", "    return 0;\n}\n\n// S_SetSentenceRule",
       "    return 1;\n}\n\n// S_SetSentenceRule"),
    _m("req-bank", "(gInstance, r->bank, (uint32_t)r->offset,",
       "(gInstance, r->bank + 1, (uint32_t)r->offset,"),
    _m("req-size", "                               (uint32_t)r->size);",
       "                               (uint32_t)r->offset);"),
    _m("cb-ev4", "if (event == BSOUND_SAMPLE_STREAM_ACTIVE) {",
       "if (event == 2) {"),
    _m("cb-sound", "if (SoundEnabled && sound_get()->speechEnabled)",
       "if (sound_get()->speechEnabled)"),
    _m("cb-speech", "if (SoundEnabled && sound_get()->speechEnabled)",
       "if (SoundEnabled)"),
    _m("cb-play-vol", "bsample_play((BSample *)sample, 1.0f, 0.0f, 0.0f);",
       "bsample_play((BSample *)sample, 0.5f, 0.0f, 0.0f);"),
    _m("cb-vol", "bsample_set_volume((BSample *)sample, 1.0f);",
       "bsample_set_volume((BSample *)sample, 0.5f);"),
    _m("cb-vol-in", "        bsample_set_volume((BSample *)sample, 1.0f);",
       "        if (SoundEnabled)\n"
       "            bsample_set_volume((BSample *)sample, 1.0f);"),
    _m("cb-ev8", "} else if (event == BSOUND_SAMPLE_STOPPED) {",
       "} else if (event == 16) {"),
    _m("cb-status", "((SedWedge *)data)->status = SEDWEDGE_STOPPED;",
       "((SedWedge *)data)->status = SEDWEDGE_IDLE;"),

    # The constructor.
    _m("ctor-status", "    w->status = SEDWEDGE_IDLE;\n    w->pauseState = 0;",
       "    w->status = 0;\n    w->pauseState = 0;"),
    _m("ctor-pause", "    w->pauseState = 0;\n    w->bankCount = 0;",
       "    w->pauseState = 1;\n    w->bankCount = 0;"),
    _m("ctor-count", "    w->bankCount = 0;\n    gClockMs = 0.0f;",
       "    w->bankCount = 3;\n    gClockMs = 0.0f;"),
    _m("ctor-clock", "    gClockMs = 0.0f;\n    w->bankMem = NULL;",
       "    w->bankMem = NULL;"),
    _m("ctor-bankmem", "    w->bankMem = NULL;\n    w->extVecs = NULL;",
       "    w->extVecs = NULL;"),
    _m("ctor-vecs", "    w->extVecs = NULL;\n    w->eventData = NULL;",
       "    w->eventData = NULL;"),
    _m("ctor-events", "    w->eventData = NULL;\n    gInstance = w;",
       "    gInstance = w;"),
    _m("ctor-inst", "    gInstance = w;\n    w->sentenceSample = NULL;",
       "    w->sentenceSample = NULL;"),
    _m("ctor-sample", "    w->sentenceSample = NULL;\n    w->initialized = 0;",
       "    w->initialized = 0;"),
    _m("ctor-init", "    w->initialized = 0;\n    w->dataPackFile = NULL;\n}",
       "    w->dataPackFile = NULL;\n}"),
    _m("ctor-dpf", "    w->dataPackFile = NULL;\n}\n\nint32_t sedwedge_load_data_file",
       "}\n\nint32_t sedwedge_load_data_file"),

    # LoadDataFile.
    _m("ldf-null", "    if (f == NULL)\n        return 0;\n    size",
       "    if (f == NULL)\n        return 1;\n    size"),
    _m("ldf-size", "*out = bMalloc(size, kFile, 92, 16);",
       "*out = bMalloc(size + 1, kFile, 92, 16);"),
    _m("ldf-line", "kFile, 92, 16);", "kFile, 93, 16);"),
    _m("ldf-align", "kFile, 92, 16);", "kFile, 92, 32);"),
    _m("ldf-read", "bRead(f, *out, size);", "bRead(f, *out, size - 1);"),
    _m("ldf-close", "    bClose(f);\n    return 1;", "    return 1;"),
    _m("ldf-ret", "    bClose(f);\n    return 1;", "    bClose(f);\n    return 0;"),

    # AddSentencePart.
    _m("asp-neg", "    if (bank < 0 || bank >= w->bankCount)",
       "    if (bank < -1 || bank >= w->bankCount)"),
    _m("asp-ge", "bank >= w->bankCount)", "bank > w->bankCount)"),
    _m("asp-ten", "if (w->segmentCount >= SEDWEDGE_SEGMENTS)",
       "if (w->segmentCount >= 9)"),
    _m("asp-base", "rd32(w->speechBank + bank * 16 + 12) + offset;",
       "rd32(w->speechBank + bank * 16 + 8) + offset;"),
    _m("asp-stride", "rd32(w->speechBank + bank * 16 + 12) + offset;",
       "rd32(w->speechBank + bank * 12 + 12) + offset;"),
    _m("asp-off", "rd32(w->speechBank + bank * 16 + 12) + offset;",
       "rd32(w->speechBank + bank * 16 + 12);"),
    _m("asp-name", '"Segment", at, size, 0);', '"Segmen", at, size, 0);'),
    _m("asp-size", '"Segment", at, size, 0);', '"Segment", at, size + 48, 0);'),
    _m("asp-flags", '"Segment", at, size, 0);', '"Segment", at, size, 1);'),
    _m("asp-count", "    w->segmentCount++;\n}", "}"),

    # Initialize.
    _m("init-game", "    w->gameNumber = 0;\n    w->slot = slot;",
       "    w->gameNumber = 1;\n    w->slot = slot;"),
    _m("init-slot", "    w->slot = slot;\n", "    w->slot = NULL;\n"),
    _m("init-ban-guard", "    if (bFileSizeName(ban) < 0) {",
       "    if (bFileSizeName(ban) < -1) {"),
    _m("init-gf-pool", "bGetFile(ban, NULL, 16);", "bGetFile(ban, NULL, 0);"),
    _m("init-gf-name", "bGetFile(ban, NULL, 16);", "bGetFile(dat, NULL, 16);"),
    _m("init-count0", "    w->bankCount = 0;\n    w->speechBank = w->bankFile;",
       "    w->speechBank = w->bankFile;"),
    _m("init-sb", "    w->speechBank = w->bankFile;\n    if", "    if"),
    _m("init-count", "w->bankCount = (int32_t)rd32(w->bankFile);",
       "w->bankCount = (int32_t)rd32(w->bankFile + 4);"),
    _m("init-open", "w->dataPackFile = bOpen(dat);",
       "w->dataPackFile = bOpen(ban);"),
    _m("init-open-gone", "    w->dataPackFile = bOpen(dat);\n", ""),
    _m("init-name", "b_strncpy(w->dataPackFileName, dat, 31);",
       "b_strncpy(w->dataPackFileName, ban, 31);"),
    _m("init-name-n", "b_strncpy(w->dataPackFileName, dat, 31);",
       "b_strncpy(w->dataPackFileName, dat, 8);"),
    _m("init-rate", "spch_get_sample_data_rate(22050, 16, 1)",
       "spch_get_sample_data_rate(24000, 16, 1)"),
    _m("init-rate-bits", "spch_get_sample_data_rate(22050, 16, 1)",
       "spch_get_sample_data_rate(22050, 8, 1)"),
    _m("init-rate-ch", "spch_get_sample_data_rate(22050, 16, 1)",
       "spch_get_sample_data_rate(22050, 16, 2)"),
    _m("init-req", "spch_init(sedwedge_sentence_part_request, w->gameNumber,",
       "spch_init(NULL, w->gameNumber,"),
    _m("init-req-game", "spch_init(sedwedge_sentence_part_request, w->gameNumber,",
       "spch_init(sedwedge_sentence_part_request, 1,"),
    _m("init-bm-n", "spch_get_bank_ptr_mem_size(SEDWEDGE_BANK_PTRS)",
       "spch_get_bank_ptr_mem_size(1000)"),
    _m("init-bm-line", "kFile, 423, 16);", "kFile, 424, 16);"),
    _m("init-bm-init", "spch_init_bank_mem(SEDWEDGE_BANK_PTRS, w->bankMem);",
       "spch_init_bank_mem(1000, w->bankMem);"),
    _m("init-abort", "v->abort = sedwedge_abort_message;", "v->abort = NULL;"),
    _m("init-print", "v->print = sedwedge_debug_print;", "v->print = NULL;"),
    _m("init-tick", "v->gettick = sedwedge_timer_get_tick;",
       "v->gettick = NULL;"),
    _m("init-vecs", "    w->extVecs = v;\n", ""),
    _m("init-evlog-buf", "spch_init_evlog(w->evLogBuffer, SEDWEDGE_EVLOG_SIZE,",
       "spch_init_evlog(w->evLogBuffer + 4, SEDWEDGE_EVLOG_SIZE,"),
    _m("init-evlog-n", "spch_init_evlog(w->evLogBuffer, SEDWEDGE_EVLOG_SIZE,",
       "spch_init_evlog(w->evLogBuffer, 1024,"),
    _m("init-evlog-fn", "SEDWEDGE_EVLOG_SIZE, sedwedge_write_evlog);",
       "SEDWEDGE_EVLOG_SIZE, NULL);"),
    _m("init-rules", "spch_init_rule_callbacks(sedwedge_test_sentence_rule,\n"
       "                             sedwedge_set_sentence_rule);",
       "spch_init_rule_callbacks(sedwedge_set_sentence_rule,\n"
       "                             sedwedge_test_sentence_rule);"),
    _m("init-ldf", "if (!sedwedge_load_data_file(w, events, &w->eventData)",
       "if (!sedwedge_load_data_file(w, ban, &w->eventData)"),
    _m("init-resolve", "        || !spch_resolve_data(w->eventData)) {",
       "        ) {"),
    _m("init-fail-flag",
       "        || !spch_resolve_data(w->eventData)) {\n        w->initialized = 0;",
       "        || !spch_resolve_data(w->eventData)) {\n        w->initialized = 1;"),
    _m("init-fail-ret",
       "        w->initialized = 0;\n        return 0;\n    }\n    spch_get_event_dat_info",
       "        w->initialized = 0;\n        return 1;\n    }\n    spch_get_event_dat_info"),
    _m("init-datinfo", "    spch_get_event_dat_info(w->eventData, &a, &b);\n", ""),
    _m("init-bank-i0", "    for (i = 0; i < w->bankCount; i++) {",
       "    for (i = 1; i < w->bankCount; i++) {"),
    _m("init-bank-off", "rd32(w->speechBank + i * 16 + 4));",
       "rd32(w->speechBank + i * 16 + 8));"),
    _m("init-bank-base", "spch_add_bank(w->bankFile + rd32(",
       "spch_add_bank(w->bankFile + 16 + rd32("),
    _m("init-handle", "wr32(w->speechBank + i * 16, (uint32_t)h);",
       "wr32(w->speechBank + i * 16 + 4, (uint32_t)h);"),
    _m("init-chain-keep", "    if (w->sentenceSample == NULL) {\n        w->sentenceSample",
       "    if (1) {\n        w->sentenceSample"),
    _m("init-chain-null", "        if (w->sentenceSample == NULL) {\n            w->initialized = 0;",
       "        if (w->sentenceSample == NULL) {\n            w->initialized = 1;"),
    _m("init-rate24", "bsample_set_rate(w->sentenceSample, 24000);",
       "bsample_set_rate(w->sentenceSample, 22050);"),
    _m("init-seg-n", "    for (i = 0; i < SEDWEDGE_SEGMENTS; i++) {\n        BSegment",
       "    for (i = 0; i < 9; i++) {\n        BSegment"),
    _m("init-seg-line", "kFile, 496, 16);", "kFile, 497, 16);"),
    _m("init-seg-size", "bMalloc((int)sizeof(BSegment), kFile",
       "bMalloc((int)sizeof(BSegment) - 4, kFile"),
    _m("init-seg-ctor", "        bsegment_construct(s);\n", ""),
    _m("init-segcount", "    w->segmentCount = 0;\n    spch_clear_event_queue();",
       "    spch_clear_event_queue();"),
    _m("init-clear2", "    spch_clear_event_queue();\n    spch_clear_event_queue();\n",
       "    spch_clear_event_queue();\n"),
    _m("init-mute", "    sedwedge_mute(w, false);\n", ""),
    _m("init-mute-on", "sedwedge_mute(w, false);", "sedwedge_mute(w, true);"),
    _m("init-ok", "    w->initialized = 1;\n    return 1;\n}",
       "    w->initialized = 2;\n    return 1;\n}"),
    _m("init-ok-ret", "    w->initialized = 1;\n    return 1;\n}",
       "    w->initialized = 1;\n    return 0;\n}"),

    # Fade and Mute.
    _m("fade-sound", "    (void)fade;\n    if (!SoundEnabled)",
       "    (void)fade;\n    if (0)"),
    _m("fade-2", _FADE_TEST, _FADE_TEST.replace(
        "w->status == SEDWEDGE_PLAYING ||", "w->status == SEDWEDGE_IDLE ||")),
    _m("fade-32", _FADE_TEST, _FADE_TEST.replace(
        "w->status == SEDWEDGE_STOPPED)", "w->status == SEDWEDGE_PAUSED)")),
    _m("fade-stop", "        bsample_stop(w->sentenceSample);\n        // bSample",
       "        // bSample"),
    _m("fade-idle", "does nothing.\n        w->status = SEDWEDGE_IDLE;",
       "does nothing.\n        w->status = SEDWEDGE_STOPPED;"),
    _m("mute-2", _MUTE_TEST, _MUTE_TEST.replace(
        "w->status == SEDWEDGE_PLAYING ||", "w->status == SEDWEDGE_IDLE ||")),
    _m("mute-32", _MUTE_TEST, _MUTE_TEST.replace(
        "w->status == SEDWEDGE_STOPPED)", "w->status == SEDWEDGE_PAUSED)")),
    _m("mute-on", "bsample_pause(w->sentenceSample, on);",
       "bsample_pause(w->sentenceSample, !on);"),
    _m("mute-state", "    w->pauseState = on;", "    w->pauseState = 0;"),

    # Cleanup.
    _m("cl-guard", "    if (w->initialized != 1)\n        return;\n    spch_deinit();",
       "    if (w->initialized == 0)\n        return;\n    spch_deinit();"),
    _m("cl-deinit", "    spch_deinit();\n", ""),
    _m("cl-dpf-close", "        bClose(w->dataPackFile);\n", ""),
    _m("cl-dpf-null", "        w->dataPackFile = NULL;\n    }\n    if (w->bankFile",
       "    }\n    if (w->bankFile"),
    _m("cl-bf-free", "        bFree(w->bankFile);\n", ""),
    _m("cl-bf-null", "        w->bankFile = NULL;\n        w->speechBank",
       "        w->speechBank"),
    _m("cl-sb-null", "        w->speechBank = NULL;\n        w->bankCount = 0;\n    }",
       "        w->bankCount = 0;\n    }"),
    _m("cl-count", "        w->speechBank = NULL;\n        w->bankCount = 0;\n    }",
       "        w->speechBank = NULL;\n    }"),
    _m("cl-ev-free", "        bFree(w->eventData);\n", ""),
    _m("cl-ev-null", "        w->eventData = NULL;\n    }\n    if (w->bankMem",
       "    }\n    if (w->bankMem"),
    _m("cl-bm-free", "        bFree(w->bankMem);\n", ""),
    _m("cl-bm-null", "        w->bankMem = NULL;\n    }\n    // The chain",
       "    }\n    // The chain"),
    _m("cl-stop", "    if (w->sentenceSample != NULL)\n        bsample_stop(w->sentenceSample);\n",
       ""),
    _m("cl-seg-free", "            bFree(w->segment[i]);\n", ""),
    _m("cl-seg-null", "            w->segment[i] = NULL;\n", ""),
    _m("cl-seg-n", "    for (i = 0; i < SEDWEDGE_SEGMENTS; i++) {\n        if (w->segment[i]",
       "    for (i = 0; i < 9; i++) {\n        if (w->segment[i]"),
    _m("cl-init", "    w->initialized = 0;\n}\n\nint32_t sedwedge_get_event_pending",
       "}\n\nint32_t sedwedge_get_event_pending"),

    # GetEventPending and QueueSentenceEvent.
    _m("gep-guard", "    if (w->initialized != 1)\n        return 0;\n    return spch_check",
       "    if (w->initialized == 0)\n        return 0;\n    return spch_check"),
    _m("gep-ch", "spch_check_event_queue(channel)", "spch_check_event_queue(0)"),
    _m("gep-bool", "spch_check_event_queue(channel) != 0 ? 1 : 0;",
       "spch_check_event_queue(channel);"),
    _m("q-guard", "    if (w->initialized != 1)\n        return 0;\n    spch_choose",
       "    if (w->initialized == 0)\n        return 0;\n    spch_choose"),
    _m("q-choose", "    spch_choose(channel);\n", ""),
    _m("q-play", "    spch_play(channel);\n", ""),
    _m("q-ch", "    spch_choose(channel);\n", "    spch_choose(0);\n"),
    _m("q-ret", "    spch_play(channel);\n    return 1;",
       "    spch_play(channel);\n    return 0;"),

    # PlaySentence.
    _m("pl-guard", "    (void)volume;\n    if (w->initialized != 1)",
       "    (void)volume;\n    if (w->initialized == 0)"),
    _m("pl-2", _PLAY_TEST, _PLAY_TEST.replace(
        "w->status == SEDWEDGE_PLAYING ||", "w->status == SEDWEDGE_IDLE ||")),
    _m("pl-32", _PLAY_TEST, _PLAY_TEST.replace(
        "w->status == SEDWEDGE_STOPPED)", "w->status == SEDWEDGE_PAUSED)")),
    _m("pl-stop", "        bsample_stop(w->sentenceSample);\n        w->status = SEDWEDGE_IDLE;\n    }\n    if (w->segmentCount",
       "        w->status = SEDWEDGE_IDLE;\n    }\n    if (w->segmentCount"),
    _m("pl-idle", "        w->status = SEDWEDGE_IDLE;\n    }\n    if (w->segmentCount",
       "    }\n    if (w->segmentCount"),
    _m("pl-count", "    if (w->segmentCount != 0) {", "    if (1) {"),
    _m("pl-cat", "bsample_set_category(w->sentenceSample, 6);",
       "bsample_set_category(w->sentenceSample, 5);"),
    _m("pl-cb", "sedwedge_sample_callback, w);", "sedwedge_sample_callback, NULL);"),
    _m("pl-path", 'bsound_set_path(bsound_get(), "");',
       'bsound_set_path(bsound_get(), "x");'),
    _m("pl-path-gone", '        bsound_set_path(bsound_get(), "");\n', ""),
    _m("pl-n", "        n = w->segmentCount;\n", "        n = w->segmentCount - 1;\n"),
    _m("pl-i0", "        for (i = 0; i < n; i++) {\n            uint32_t offset",
       "        for (i = 1; i < n; i++) {\n            uint32_t offset"),
    _m("pl-off48", "bsegment_get_offset(w->segment[i]) + 48;",
       "bsegment_get_offset(w->segment[i]) + 32;"),
    _m("pl-size48", "bsegment_get_size(w->segment[i]) - 48;",
       "bsegment_get_size(w->segment[i]) - 32;"),
    _m("pl-name", "bsample_chain_add(w->sentenceSample, w->dataPackFileName,",
       'bsample_chain_add(w->sentenceSample, "x",'),
    _m("pl-last", "offset, size, i == n - 1);", "offset, size, i == n);"),
    _m("pl-last0", "offset, size, i == n - 1);", "offset, size, i == 0);"),
    _m("pl-restore",
       "        bsound_set_path(bsound_get(), sound_get_path(sound_get()));\n", ""),
    _m("pl-seg0", "        w->segmentCount = 0;\n        w->status = SEDWEDGE_PLAYING;",
       "        w->status = SEDWEDGE_PLAYING;"),
    _m("pl-status", "        w->status = SEDWEDGE_PLAYING;\n    }\n    return 1;",
       "        w->status = SEDWEDGE_STOPPED;\n    }\n    return 1;"),
    _m("pl-ret", "        w->status = SEDWEDGE_PLAYING;\n    }\n    return 1;",
       "        w->status = SEDWEDGE_PLAYING;\n    }\n    return 0;"),

    # StopSentence and ClearEventQueue.
    _m("st-guard", "    (void)channel;\n    if (w->initialized != 1)\n        return 0;\n    bsample_stop",
       "    (void)channel;\n    if (w->initialized == 0)\n        return 0;\n    bsample_stop"),
    _m("st-stop", "    bsample_stop(w->sentenceSample);\n    w->status = SEDWEDGE_IDLE;\n    return 1;",
       "    w->status = SEDWEDGE_IDLE;\n    return 1;"),
    _m("st-idle", "    bsample_stop(w->sentenceSample);\n    w->status = SEDWEDGE_IDLE;\n    return 1;",
       "    bsample_stop(w->sentenceSample);\n    return 1;"),
    _m("st-ret", "    w->status = SEDWEDGE_IDLE;\n    return 1;\n}\n\nint32_t sedwedge_clear",
       "    w->status = SEDWEDGE_IDLE;\n    return 0;\n}\n\nint32_t sedwedge_clear"),
    _m("clr-guard", "    if (w->initialized != 1)\n        return 0;\n    spch_clear_event_queue();",
       "    if (w->initialized == 0)\n        return 0;\n    spch_clear_event_queue();"),
    _m("clr-clear", "        return 0;\n    spch_clear_event_queue();\n    if (w->status",
       "        return 0;\n    if (w->status"),
    _m("clr-test", "    if (w->status != SEDWEDGE_IDLE)\n        sedwedge_stop_sentence(w, 0);",
       "    if (w->status == SEDWEDGE_PLAYING)\n        sedwedge_stop_sentence(w, 0);"),
    _m("clr-ret", "        sedwedge_stop_sentence(w, 0);\n    return 1;",
       "        sedwedge_stop_sentence(w, 0);\n    return 0;"),

    # Update.
    _m("up-init", "    if (w->initialized == 0 || w->pauseState != 0)",
       "    if (w->pauseState != 0)"),
    _m("up-init1", "    if (w->initialized == 0 || w->pauseState != 0)",
       "    if (w->initialized != 1 || w->pauseState != 0)"),
    _m("up-pause", "    if (w->initialized == 0 || w->pauseState != 0)",
       "    if (w->initialized == 0)"),
    _m("up-clock", "(float)RealTimeFrames * (1.0f / 60.0f) * 1000.0f;",
       "(float)RealTimeFrames * (1000.0f / 60.0f);"),
    _m("up-clock-div", "(float)RealTimeFrames * (1.0f / 60.0f) * 1000.0f;",
       "(float)RealTimeFrames / 60.0f * 1000.0f;"),
    _m("up-clock-k", "(float)RealTimeFrames * (1.0f / 60.0f) * 1000.0f;",
       "(float)RealTimeFrames * (1.0f / 50.0f) * 1000.0f;"),
    _m("up-32", "    if (w->status == SEDWEDGE_STOPPED)\n        w->status = SEDWEDGE_IDLE;",
       "    if (w->status == SEDWEDGE_PLAYING)\n        w->status = SEDWEDGE_IDLE;"),
    _m("up-32-set", "    if (w->status == SEDWEDGE_STOPPED)\n        w->status = SEDWEDGE_IDLE;",
       "    if (w->status == SEDWEDGE_STOPPED)\n        w->status = 0;"),
    _m("up-idle", "    if (w->status != SEDWEDGE_IDLE && w->status != SEDWEDGE_PAUSED)",
       "    if (w->status != SEDWEDGE_IDLE)"),
    _m("up-8", "    if (w->status != SEDWEDGE_IDLE && w->status != SEDWEDGE_PAUSED)",
       "    if (w->status != SEDWEDGE_PAUSED)"),
    _m("up-ch", "    if (sedwedge_get_event_pending(w, 0)) {",
       "    if (sedwedge_get_event_pending(w, 1)) {"),
    _m("up-queue", "        sedwedge_queue_sentence_event(w, 0);\n", ""),
    _m("up-play", "        sedwedge_play_sentence(w, 0, 1.0f);\n", ""),

    # Sound.obj's.
    _m("cr-size", 'bMalloc((int)sizeof(SedWedge), "Sound.cpp", 388, 16);',
       'bMalloc((int)sizeof(SedWedge) - 4, "Sound.cpp", 388, 16);'),
    _m("cr-line", '"Sound.cpp", 388, 16);', '"Sound.cpp", 389, 16);'),
    _m("cr-ctor", "    sedwedge_construct(w);\n    gSoundSedWedge = w;",
       "    gSoundSedWedge = w;"),
    _m("cr-store", "    gSoundSedWedge = w;\n    return w;", "    return w;"),
    _m("ld-sound", "    if (!SoundEnabled || (uint32_t)lang >= 6)",
       "    if ((uint32_t)lang >= 6)"),
    _m("ld-lang", "    if (!SoundEnabled || (uint32_t)lang >= 6)",
       "    if (!SoundEnabled || (uint32_t)lang >= 5)"),
    _m("ld-sign", "    if (!SoundEnabled || (uint32_t)lang >= 6)",
       "    if (!SoundEnabled || lang > 6)"),
    _m("ld-en2", '"Italian", "Spanish", "English",',
       '"Italian", "Spanish", "Spanish",'),
    _m("ld-fr", '"English", "French", "German",', '"English", "German", "German",'),
    _m("ld-it", '"Italian", "Spanish", "English",', '"Spanish", "Spanish", "English",'),
    _m("ld-ban", r'"Sound\\Speech\\%sBAN.pck"', r'"Sound\\Speech\\%sBAM.pck"'),
    _m("ld-dat", r'"Sound\\Speech\\%sDAT.pck"', r'"Sound\\Speech\\%sDAX.pck"'),
    _m("ld-evt", r'"Sound\\Speech\\Events.evt"', r'"Sound\\Speech\\Events.ev"'),
    _m("ld-speech", "    if (sound_get()->speechEnabled && gSoundSedWedge != NULL)",
       "    if (gSoundSedWedge != NULL)"),
    _m("ul-sound", "    if (SoundEnabled && gSoundSedWedge != NULL)",
       "    if (gSoundSedWedge != NULL)"),
]

EQUIVALENT = {
    "tick-unsigned":
        "the host converts a float to uint32_t through int64, so a negative "
        "clock comes out as (int32_t) gives it; on the 3DS it would be 0. "
        "The clock is never negative in the game, and the cast is retail's "
        "cvt.w.s",
    "cr-size":
        "create's size is the host's sizeof(SedWedge), which is not the "
        "PS2's 2180 (8-byte pointers, and no vtable); the harness does not "
        "print it, and sedwedge.h's layout check holds the 3DS offsets",
}


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
    base = model_cached(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text(encoding="latin-1").splitlines()
        if diff(base, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)
    limit = mutpar.timeout_for(took)
    result = mutpar.run_pass(
        todo, SOURCES, "sedwedge_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs)
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

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(got) + NL,
                                           encoding="latin-1")
        d.with_suffix(".harness").write_text(NL.join(harness) + NL,
                                             encoding="latin-1")

    n = diff(got, harness)
    print("%d ops, %d lines, %d differ" % (len(lines), len(harness), n))
    sys.exit(1 if n or rc else 0)


if __name__ == "__main__":
    main()
