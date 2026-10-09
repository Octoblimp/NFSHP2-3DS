#!/usr/bin/env python3
"""Cross-check 3DS Files/source/nisinfo.c and nismanager.c, the NIS table
and the NisManager's state (12l-2), against the retail image, SLES_507.31,
run in mipsemu.

**The model** is retail's own code: LoaderNisInfo (0x001b3358) and
UnloaderNisInfo (0x001b33a0); GetNumNisInfo (0x001b3490), GetNisInfo(int)
(0x001b3608) and GetNisInfo(int, NisType) (0x001b3638); NisManager's
constructor (0x001b0fe0, with InitSoundEvents and bStrCpy as they are),
destructor (0x001b1110, through bTNode's and bNode's), Start (0x001b1318,
with its load check at 0x001b16e0), Stop (0x001b1388), AllowDebugLooping
(0x001b13e8), Unload (0x001b1658) and EnsureNisIsLoaded (0x001b16a0). The
harness (tools/src/nis_test.c) runs the port's files and prints the same
lines.

**The stubs**, logged on both sides: Load (0x001b1568; it sets
LoadingNisNumber to what the script says, or leaves it), SetupCarsBeforeNIS,
StartAnimating, StopAnimating, RestoreCarsAfterNIS, UnloadResourceFile,
ServiceResourceLoading (which clears the named manager's LoadingNisNumber on
the script's call, and every manager's at the 64th), eModel's destructor and
bFree. The port reaches them through its seams, but for eModel's destructor
and bFree, which the harness defines.

**Compared** are the lookups' answers and, after each other call,
NisManagerList, the table and its count, and both managers whole: every
field, the render info and the four props' words -- the ones the
constructor leaves as the memory was included, over memory filled first.

**The divergences**: Start reads the NIS's NumFrames untested; the port
plays for no time without a table, which the script never asks of either.
EnsureNisIsLoaded with the service unbound stops waiting in the port; the
harness binds it.

    python tools/nis_check.py
    python tools/nis_check.py --mutate [--only a,b]
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

HARNESS = "tools/src/nis_test.c"
NI = "3DS Files/source/nisinfo.c"
NMC = "3DS Files/source/nismanager.c"
NIH = "3DS Files/source/nisinfo.h"
SOURCES = [HARNESS, NI, NMC]
HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = retail_model.RETAIL_GP
G_TABLE = GP - 18844                    # NisInfoTable
G_NUM = GP - 18848                      # NumNisInfos
G_LIST = GP - 18840                     # NisManager::NisManagerList
G_WTF = GP - 19564                      # WorldTimeFrames

F_LOADER = 0x001b3358
F_UNLOADER = 0x001b33a0
F_NUM = 0x001b3490
F_GET = 0x001b3608
F_GETT = 0x001b3638
F_CTOR = 0x001b0fe0
F_DTOR = 0x001b1110
F_START = 0x001b1318
F_STOP = 0x001b1388
F_ADL = 0x001b13e8
F_UNLOAD = 0x001b1658
F_ENSURE = 0x001b16a0

S_LOAD = 0x001b1568
S_SETUP = 0x001b2718
S_ANIM_ON = 0x001b2840
S_ANIM_OFF = 0x001b2a70
S_RESTORE = 0x001b27c0
S_URF = 0x00199728
S_SVC = 0x00199788
S_EMDTOR = 0x00114cf0
S_FREE = 0x00257850

NM, NREC, MGR_SIZE = 2, 12, 320
CHUNK_ID = 0x00037010

# The disc's table (GLOBALB.BUN, 0x37010 at 0x9fe80): type, NisNumber,
# NumFrames, NumCameras.
DISC = [(2, 0, 121, 2), (2, 1, 154, 3), (2, 2, 149, 3), (1, 3, 141, 3),
        (1, 4, 141, 2), (1, 5, 141, 3), (1, 6, 141, 3), (1, 7, 141, 3)]

FIELDS = {"lded": 12, "ling": 16, "ld": 20, "play": 68, "st": 72,
          "et": 76, "nis": 80, "cam": 84, "anim": 96, "nrf": 24,
          "crf": 28, "pc": 88, "oc": 92}
PTR_FIELDS = ("nrf", "crf", "pc", "oc")


# ================================================================== model

class Model(object):
    def __init__(self):
        e = self.e = retail_model.RetailEmu(ieee=True)
        self.out = []

        def block(n, align=16):
            p = e.alloc(n, align=align)
            e.write(p, bytes(n))
            return p
        self.ms = [block(MGR_SIZE) for _ in range(NM)]
        self.cars = [block(16) for _ in range(2)]
        self.rfs = [block(16) for _ in range(2)]
        self.chunk = block(8 + 160 * NREC + 16)
        self.namebuf = block(64)
        self.names = {G_LIST: "L"}
        for k, m in enumerate(self.ms):
            self.names[m] = "M%d" % k
            for i in range(2):
                self.names[m + 224 + 24 * i] = "M%d.pc%d" % (k, i)
                self.names[m + 272 + 24 * i] = "M%d.oc%d" % (k, i)
        for i in range(2):
            self.names[self.cars[i]] = "A%d" % i
            self.names[self.rfs[i]] = "R%d" % i
        for i in range(NREC):
            self.names[self.chunk + 8 + 160 * i] = "I%d" % i
        for addr, fn in ((S_LOAD, self.s_load), (S_SETUP, self.s_setup),
                         (S_ANIM_ON, self.s_anim_on),
                         (S_ANIM_OFF, self.s_anim_off),
                         (S_RESTORE, self.s_restore), (S_URF, self.s_urf),
                         (S_SVC, self.s_svc), (S_EMDTOR, self.s_emdtor),
                         (S_FREE, self.s_free)):
            e.stub(addr, fn)
        self.reset()

    def emit(self, line):
        self.out.append(line)

    def sym(self, v):
        v &= M32
        if v == 0:
            return "0"
        return self.names.get(v, "?")

    def reset(self):
        e = self.e
        e.put32(G_TABLE, 0)
        e.put32(G_NUM, 0)
        e.put32(G_LIST, G_LIST)
        e.put32(G_LIST + 4, G_LIST)
        e.put32(G_WTF, 0)
        for m in self.ms:
            e.write(m, bytes(MGR_SIZE))
        e.write(self.chunk, bytes(8 + 160 * NREC))
        self.svc_at = 1
        self.svc_n = 0
        self.svc_target = None
        self.load_sets = -2

    # ---- stubs

    def s_load(self, em):
        m = em.reg[4] & M32
        self.emit("  load %s %d" % (self.sym(m), s32(em.reg[5])))
        if self.load_sets != -2:
            self.e.put32(m + 16, self.load_sets & M32)

    def s_setup(self, em):
        self.emit("  setup %s" % self.sym(em.reg[4]))

    def s_anim_on(self, em):
        self.emit("  anim_on %s" % self.sym(em.reg[4]))

    def s_anim_off(self, em):
        self.emit("  anim_off %s" % self.sym(em.reg[4]))

    def s_restore(self, em):
        self.emit("  restore %s" % self.sym(em.reg[4]))

    def s_urf(self, em):
        self.emit("  unload_rf %s" % self.sym(em.reg[4]))

    def s_svc(self, em):
        self.svc_n += 1
        self.emit("  svc %d" % self.svc_n)
        if self.svc_n == self.svc_at and self.svc_target is not None:
            self.e.put32(self.svc_target + 16, M32)
        if self.svc_n >= 64:
            for m in self.ms:
                self.e.put32(m + 16, M32)
        return 0

    def s_emdtor(self, em):
        self.emit("  emodel_dtor %s %d" % (self.sym(em.reg[4]),
                                           s32(em.reg[5])))

    def s_free(self, em):
        self.emit("  free %s" % self.sym(em.reg[4]))

    # ---- dumps

    def name_at(self, p):
        e = self.e
        out = []
        for i in range(32):
            c = e.u8(p + i)
            if c == 0:
                break
            if c < 0x20 or c > 0x7e or c in (0x27, 0x5c):
                out.append("\\x%02x" % c)
            else:
                out.append(chr(c))
        return "".join(out)

    def mi(self, p):
        e = self.e
        return " %s %08x %08x %08x %08x %s" % (
            self.sym(e.u32(p)), e.u32(p + 16), e.u32(p + 20), e.u32(p + 24),
            e.u32(p + 28), self.sym(e.u32(p + 32)))

    def prop(self, p):
        e = self.e
        r = struct.unpack("<h", bytes(e.read(p + 22, 2)))[0]
        return " %08x %s %s %d %d" % (e.u32(p + 8), self.sym(e.u32(p + 12)),
                                      self.sym(e.u32(p + 16)), e.u8(p + 20),
                                      r)

    def dump(self):
        e = self.e
        self.emit("L next %s prev %s" % (self.sym(e.u32(G_LIST)),
                                         self.sym(e.u32(G_LIST + 4))))
        t = e.u32(G_TABLE)
        self.emit("T %s n %d" % ("0" if t == 0 else
                                 "C+8" if t == self.chunk + 8 else "?",
                                 s32(e.u32(G_NUM))))
        for k, m in enumerate(self.ms):
            w = lambda o: s32(e.u32(m + o))     # noqa: E731
            self.emit("M%d n %s p %s psf %08x lded %d ling %d ld %d nrf %s "
                      "crf %s num %d name '%s'" % (
                          k, self.sym(e.u32(m)), self.sym(e.u32(m + 4)),
                          e.u32(m + 8), w(12), w(16), w(20),
                          self.sym(e.u32(m + 24)), self.sym(e.u32(m + 28)),
                          w(32), self.name_at(m + 36)))
            self.emit("M%d play %d st %d et %d nis %d cam %d pc %s oc %s "
                      "anim %d views %d omm %d pmm %d" % (
                          k, w(68), w(72), w(76), w(80), w(84),
                          self.sym(e.u32(m + 88)), self.sym(e.u32(m + 92)),
                          w(96), w(100), w(104), w(108)))
            self.emit("M%d ri %d %08x%s%s" % (k, w(112), e.u32(m + 116),
                                              self.mi(m + 128),
                                              self.mi(m + 176)))
            self.emit("M%d props%s" % (k, "".join(
                self.prop(m + 224 + 24 * i) for i in range(4))))

    # ---- ops

    def named(self, s):
        if s == "0":
            return 0
        if s[0] == "A":
            return self.cars[int(s[1:])]
        if s[0] == "R":
            return self.rfs[int(s[1:])]
        if s[0] == "M":
            return self.ms[int(s[1:])]
        if s == "L":
            return G_LIST
        if s == "?":
            return 0xa5a5a5a5
        raise ValueError(s)

    def run(self, a):
        e = self.e
        o = a[0]
        v = lambda j: int(a[j], 0) & M32        # noqa: E731
        # An int argument sits sign-extended in its register.
        sv = lambda j: s32(v(j))                # noqa: E731
        call = lambda f, *args: e.call(f, *args, limit=200000)  # noqa
        if o == "reset":
            self.reset()
            return
        if o == "rec":
            p = self.chunk + 8 + 160 * int(a[1])
            e.write(p, bytes(160))
            e.write(p, ("NIS_%02d" % int(a[1])).encode())
            for j, off in enumerate((32, 40, 44, 48)):
                e.put32(p + off, v(2 + j))
            return
        if o == "hdr":
            e.put32(self.chunk, v(1))
            e.put32(self.chunk + 4, v(2))
            return
        if o == "wtf":
            e.put32(G_WTF, v(1))
            return
        if o == "fill":
            e.write(self.ms[int(a[1])], bytes([v(2) & 0xff]) * MGR_SIZE)
            return
        if o == "set":
            m = self.ms[int(a[1])]
            f = a[2]
            e.put32(m + FIELDS[f], self.named(a[3]) if f in PTR_FIELDS
                    else v(3))
            return
        if o == "svc":
            self.svc_at = int(a[1], 0)
            self.svc_n = 0
            self.svc_target = self.ms[int(a[2])]
            return
        if o == "ldv":
            self.load_sets = s32(v(1))
            return

        if o == "loader":
            self.emit("loader -> %d" % call(F_LOADER, self.chunk))
        elif o == "unloader":
            self.emit("unloader -> %d" % call(F_UNLOADER, self.chunk))
        elif o == "num":
            self.emit("num %d -> %d" % (int(a[1], 0), call(F_NUM, sv(1))))
            return
        elif o == "get":
            self.emit("get %d -> %s" % (int(a[1], 0),
                                        self.sym(call(F_GET, sv(1)))))
            return
        elif o == "gett":
            self.emit("gett %d %d -> %s" % (int(a[1], 0), int(a[2], 0),
                                            self.sym(call(F_GETT, sv(1),
                                                          sv(2)))))
            return
        elif o == "ctor":
            name = a[2].encode()
            e.write(self.namebuf, name + b"\0")
            self.emit("ctor M%s '%s' %d" % (a[1], a[2], int(a[3], 0)))
            r = call(F_CTOR, self.ms[int(a[1])], self.namebuf, sv(3))
            self.emit("  -> %s" % self.sym(r))
        elif o == "dtor":
            self.emit("dtor M%s %d" % (a[1], int(a[2], 0)))
            call(F_DTOR, self.ms[int(a[1])], sv(2))
        elif o == "start":
            self.emit("start M%s %d %d %s %s" % (a[1], int(a[2], 0),
                                                 int(a[3], 0), a[4], a[5]))
            call(F_START, self.ms[int(a[1])], sv(2), sv(3), self.named(a[4]),
                 self.named(a[5]))
        elif o == "stop":
            self.emit("stop M%s" % a[1])
            call(F_STOP, self.ms[int(a[1])])
        elif o == "unload":
            self.emit("unload M%s" % a[1])
            call(F_UNLOAD, self.ms[int(a[1])])
        elif o == "ensure":
            self.emit("ensure M%s" % a[1])
            call(F_ENSURE, self.ms[int(a[1])])
        elif o == "adl":
            self.emit("adl M%s -> %d" % (a[1], call(F_ADL,
                                                    self.ms[int(a[1])])))
            return
        elif o == "isp":
            # Retail's callers read the word in place.
            self.emit("isp M%s -> %d" % (
                a[1], s32(e.u32(self.ms[int(a[1])] + 68))))
            return
        else:
            raise ValueError(o)
        self.dump()


def model(lines):
    m = Model()
    for ln in lines:
        m.run(ln.split("|"))
    return m.out


# ================================================================ the script

def table(recs, size=None, cid=CHUNK_ID):
    """The records and the header, then the loader."""
    out = ["rec|%d|%d|%d|%d|%d" % ((i,) + tuple(r)) for i, r in
           enumerate(recs)]
    out.append("hdr|0x%x|%d" % (cid, 160 * len(recs) if size is None
                                else size))
    out.append("loader")
    return out


def queries(n, types=(-1, 0, 1, 2, 3)):
    out = []
    for t in types:
        out.append("num|%d" % t)
    for i in range(-1, n + 2):
        out.append("get|%d" % i)
    for t in types:
        for i in range(-1, n + 2):
            out.append("gett|%d|%d" % (i, t))
    return out


def lookup_cases(rng):
    out = []
    # No table: everything 0.
    out += ["reset"] + queries(3)
    # The disc's table, and its unloading.
    out += ["reset"] + table(DISC) + queries(len(DISC))
    out += ["hdr|0x%x|1280" % CHUNK_ID, "unloader"] + queries(3)
    # The loader's guard and the count's rounding.
    for cid in (CHUNK_ID, CHUNK_ID + 1, CHUNK_ID - 1, 0x80037010,
                0x00034700, 0):
        for size in (0, 1, 159, 160, 161, 319, 320, 479, 480, 1280, 1919):
            out += ["reset"] + table(DISC, size=size, cid=cid)
            out += ["num|1", "num|2", "get|0", "get|2", "get|7", "get|8"]
    # The unloader's guard leaves the table.
    for cid in (CHUNK_ID + 1, 0x80037010, 0):
        out += ["reset"] + table(DISC) + ["hdr|0x%x|1280" % cid, "unloader",
                                          "num|1"]
    # A table that is there with no records.
    out += ["reset"] + table(DISC, size=100) + queries(2)
    # Shapes at random.
    for _ in range(80):
        n = rng.randrange(0, NREC + 1)
        recs = [(rng.choice((0, 1, 1, 2, 2, 3, -1)), rng.randrange(-2, 12),
                 rng.randrange(-5, 300), rng.randrange(0, 5))
                for _ in range(n)]
        out += ["reset"] + table(recs) + queries(n)
    return out


def ctor_cases():
    out = []
    names = ("Player0", "Player1", "", "P", "x" * 31, "Player9 with gap")
    for fill in (0, 0xa5, 0xff):
        for name in names:
            for num in (0, 1, -1, 7):
                out += ["reset", "fill|0|%d" % fill, "fill|1|%d" % fill,
                        "ctor|0|%s|%d" % (name, num)]
    # Both, in turn, onto the list's tail.
    out += ["reset", "fill|0|0xa5", "fill|1|0x5a", "ctor|1|Player0|0",
            "ctor|0|Player1|1"]
    return out


def two():
    return ["reset", "fill|0|0xa5", "fill|1|0xa5", "ctor|0|Player1|1",
            "ctor|1|Player0|0"]


def dtor_cases():
    out = []
    for who in (0, 1):
        for flags in (0, 1, 2, 3):
            for lded in (-1, 0, 5):
                for ling in (-1, 0, 4):
                    for at in (1, 3):
                        out += two() + ["set|%d|lded|%d" % (who, lded),
                                        "set|%d|ling|%d" % (who, ling),
                                        "set|%d|nrf|R0" % who,
                                        "set|%d|crf|R1" % who,
                                        "svc|%d|%d" % (at, who),
                                        "dtor|%d|%d" % (who, flags)]
    # Both, either order; and one alone.
    for first in (0, 1):
        out += two() + ["dtor|%d|3" % first, "dtor|%d|3" % (1 - first)]
    out += ["reset", "ctor|0|Player1|1", "dtor|0|3"]
    return out


def start_cases(rng):
    out = []
    recs = DISC + [(1, 8, 0x7fffffff, 3), (2, 9, -1, 2), (1, 10, 0, 1),
                   (2, 11, -0x40000000, 2)]
    for nis in range(NREC):
        for wtf in (0, 1, 1000, 0x7fffffff, -5):
            for lded in (-1, nis, 3):
                out += two() + table(recs, size=1280) + [
                    "wtf|%d" % wtf, "set|0|lded|%d" % lded,
                    "start|0|%d|%d|A0|A1" % (nis, nis % 3)]
    # The load: what Load leaves in LoadingNisNumber, and the wait.
    for ldv in (-2, -1, 0, 6):
        for at in (1, 2, 5):
            for cars in (("A0", "A1"), ("A1", "0"), ("0", "0")):
                out += two() + table(DISC) + [
                    "wtf|77", "ldv|%d" % ldv, "svc|%d|1" % at,
                    "start|1|6|-1|%s|%s" % cars]
    # Started twice; the other manager left alone.
    out += two() + table(DISC) + ["wtf|10", "start|0|4|1|A0|A1", "wtf|20",
                                  "start|0|5|2|A1|A0", "start|1|0|0|A0|A1"]
    return out


def stop_cases():
    out = []
    for play in (0, 1, 2, -1):
        for nis in (-1, 3):
            out += two() + ["set|0|play|%d" % play, "set|0|nis|%d" % nis,
                            "set|0|cam|2", "set|0|st|5", "set|0|et|300",
                            "set|0|pc|A0", "set|0|oc|A1", "stop|0"]
    out += two() + table(DISC) + ["start|1|2|1|A0|A1", "stop|1", "stop|1"]
    return out


def unload_cases():
    out = []
    for lded in (-1, 0, 7, -5):
        for ling in (-1, 3):
            for rf in (("R0", "R1"), ("0", "R0"), ("R1", "0")):
                out += two() + ["set|1|lded|%d" % lded,
                                "set|1|ling|%d" % ling,
                                "set|1|nrf|%s" % rf[0],
                                "set|1|crf|%s" % rf[1], "svc|2|1",
                                "unload|1"]
    for ling in (-1, 0, 1, 9, -9):
        for at in (1, 2, 4):
            out += two() + ["set|0|ling|%d" % ling, "svc|%d|0" % at,
                            "ensure|0"]
    for k in (0, 1):
        out += two() + ["adl|%d" % k, "set|%d|play|1" % k, "isp|%d" % k,
                        "set|%d|play|0" % k, "isp|%d" % k]
    return out


def sequences(rng):
    """A NIS's life: started, run out and stopped, unloaded; the two
    managers in turn."""
    out = []
    for run in range(60):
        out += two() + table(DISC)
        wtf = rng.randrange(0, 5000)
        for step in range(rng.randrange(8, 30)):
            k = rng.randrange(2)
            r = rng.random()
            if r < 0.3:
                out += ["wtf|%d" % wtf, "ldv|%d" % rng.choice((-2, -1, 3)),
                        "svc|%d|%d" % (rng.randrange(1, 4), k),
                        "set|%d|lded|%d" % (k, rng.choice((-1, 2, 4))),
                        "start|%d|%d|%d|%s|%s" % (
                            k, rng.randrange(8), rng.randrange(3),
                            rng.choice(("A0", "A1", "0")),
                            rng.choice(("A0", "A1", "0")))]
            elif r < 0.55:
                out.append("stop|%d" % k)
            elif r < 0.7:
                out += ["svc|%d|%d" % (rng.randrange(1, 4), k),
                        "set|%d|nrf|R%d" % (k, rng.randrange(2)),
                        "unload|%d" % k]
            elif r < 0.8:
                out += ["isp|%d" % k, "adl|%d" % k]
            else:
                wtf += rng.randrange(1, 400)
                out.append("wtf|%d" % wtf)
        out.append("dtor|%d|%d" % (rng.randrange(2), rng.randrange(4)))
    return out


def script():
    return (lookup_cases(random.Random(0xa1)) + ctor_cases() + dtor_cases()
            + start_cases(random.Random(0xa2)) + stop_cases()
            + unload_cases() + sequences(random.Random(0xa3)))


# ================================================================= running

def build_harness(tmp, name="nis_test"):
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
    lines = script()
    sc = Path(d) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    return lines, sc


# ============================================================= mutations

MUTATIONS = [
    # ---- the table
    ("l_id", NIH, "#define NIS_INFO_CHUNK_ID 0x00037010u",
     "#define NIS_INFO_CHUNK_ID 0x00037011u"),
    ("l_guard", NI, "    if (bchunk_u32(chunk) != NIS_INFO_CHUNK_ID)\n"
     "        return 0;\n    NisInfoTable = (NisInfo *)",
     "    NisInfoTable = (NisInfo *)"),
    ("l_at", NI, "(NisInfo *)(void *)(chunk + 8);",
     "(NisInfo *)(void *)(chunk + 4);"),
    ("l_size", NI, "bchunk_u32(chunk + 4) / 160u", "bchunk_u32(chunk) / 160u"),
    ("l_div", NI, "/ 160u);", "/ 161u);"),
    ("l_ret", NI, "/ 160u);\n    return 1;", "/ 160u);\n    return 0;"),
    ("u_guard", NI, "        return 0;\n    NisInfoTable = NULL;",
     "        return 1;\n    NisInfoTable = NULL;"),
    ("u_table", NI, "    NisInfoTable = NULL;\n    NumNisInfos = 0;",
     "    NumNisInfos = 0;"),
    ("u_count", NI, "    NisInfoTable = NULL;\n    NumNisInfos = 0;",
     "    NisInfoTable = NULL;"),
    ("n_null", NI, "    if (NisInfoTable == NULL)\n        return 0;\n"
     "    for (i = 0; i < NumNisInfos; i++)\n        if",
     "    for (i = 0; i < NumNisInfos; i++)\n        if"),
    ("n_type", NI, "        if (NisInfoTable[i].Type == type)\n            n++;",
     "        if (NisInfoTable[i].Type != type)\n            n++;"),
    ("n_bound", NI, "    for (i = 0; i < NumNisInfos; i++)\n        if (Nis",
     "    for (i = 0; i <= NumNisInfos; i++)\n        if (Nis"),
    ("g_null", NI, "    if (NisInfoTable == NULL || n >= NumNisInfos)",
     "    if (n >= NumNisInfos)"),
    ("g_bound", NI, "|| n >= NumNisInfos)", "|| n > NumNisInfos)"),
    ("g_neg", NI, "|| n >= NumNisInfos)", "|| (uint32_t)n >= (uint32_t)NumNisInfos)"),
    ("t_type", NI, "        if (NisInfoTable[i].Type != type)\n            continue;",
     "        if (NisInfoTable[i].Type == type)\n            continue;"),
    ("t_zero", NI, "        if (n == 0)\n            return &NisInfoTable[i];",
     "        if (n == 1)\n            return &NisInfoTable[i];"),
    ("t_dec", NI, "            return &NisInfoTable[i];\n        n--;",
     "            return &NisInfoTable[i];"),
    ("t_null", NI, "    if (NisInfoTable == NULL)\n        return NULL;\n"
     "    for (i = 0; i < NumNisInfos; i++) {",
     "    if (NisInfoTable == NULL)\n        return NisInfoTable + 1;\n"
     "    for (i = 0; i < NumNisInfos; i++) {"),
    # ---- the constructor
    ("c_frames", NMC, "    m->NisRendInfo.NumFrames = 0;\n", ""),
    ("c_ox", NMC, "    mi->Offset.x = 0.0f;\n", ""),
    ("c_oz", NMC, "    mi->Offset.z = 0.0f;\n", ""),
    ("c_opad", NMC, "    mi->Offset.pad = 0.0f;\n", ""),
    ("c_anim", NMC, "    mi->pAnimation = NULL;\n", ""),
    ("c_stole", NMC, "    mi->pCarWeStoleAnimationFrom = NULL;\n", ""),
    ("c_other_mi", NMC,
     "    clear_model_info(&m->NisRendInfo.OtherModelInfo);\n", ""),
    ("c_hash", NMC, "    e->NameHash = 0;\n", ""),
    ("c_solid", NMC, "    e->Solid = NULL;\n", ""),
    ("c_props_n", NMC, "    for (i = 0; i < 2; i++)\n        clear_prop(&m->Other",
     "    for (i = 0; i < 1; i++)\n        clear_prop(&m->Other"),
    ("c_pprops", NMC, "        clear_prop(&m->PlayerCharProps[i]);\n", ""),
    ("c_nrf", NMC, "    m->NisResourceFile = NULL;\n", ""),
    ("c_lded", NMC, "    m->LoadedNisNumber = -1;\n    m->LoadingNisNumber",
     "    m->LoadedNisNumber = 0;\n    m->LoadingNisNumber"),
    ("c_ling", NMC, "    m->LoadingNisNumber = -1;", "    m->LoadingNisNumber = 0;"),
    ("c_ld", NMC, "    m->LoadNisNumber = -1;", "    m->LoadNisNumber = 0;"),
    ("c_crf", NMC, "    m->CamResourceFile = NULL;\n", ""),
    ("c_num", NMC, "    m->PlayerNumber = number;", "    m->PlayerNumber = 0;"),
    ("c_name", NMC, "    strcpy(m->Name, name);\n", ""),
    ("c_nis", NMC, "    m->NisNumber = -1;\n\n    // AddTail.",
     "    m->NisNumber = 0;\n\n    // AddTail."),
    ("c_tail_next", NMC, "    m->Node.next = &NisManagerList;\n", ""),
    ("c_tail_prev", NMC, "    m->Node.prev = NisManagerList.prev;\n", ""),
    ("c_tail_link", NMC, "    NisManagerList.prev->next = &m->Node;\n", ""),
    ("c_tail_head", NMC, "    NisManagerList.prev = &m->Node;\n", ""),
    ("c_head", NMC, "    m->Node.next = &NisManagerList;\n"
     "    m->Node.prev = NisManagerList.prev;\n"
     "    NisManagerList.prev->next = &m->Node;\n"
     "    NisManagerList.prev = &m->Node;\n",
     "    m->Node.prev = &NisManagerList;\n"
     "    m->Node.next = NisManagerList.next;\n"
     "    NisManagerList.next->prev = &m->Node;\n"
     "    NisManagerList.next = &m->Node;\n"),
    ("c_st", NMC, "    m->StartTime = 0;\n    m->EndTime = 0;\n    m->PlayerCar",
     "    m->EndTime = 0;\n    m->PlayerCar"),
    ("c_et", NMC, "    m->StartTime = 0;\n    m->EndTime = 0;\n    m->PlayerCar",
     "    m->StartTime = 0;\n    m->PlayerCar"),
    ("c_pc", NMC, "    m->PlayerCar = NULL;\n    m->OtherCar = NULL;\n    m->Playing",
     "    m->OtherCar = NULL;\n    m->Playing"),
    ("c_oc", NMC, "    m->PlayerCar = NULL;\n    m->OtherCar = NULL;\n    m->Playing",
     "    m->PlayerCar = NULL;\n    m->Playing"),
    ("c_play", NMC, "    m->Playing = 0;\n    m->Animating", "    m->Animating"),
    ("c_animating", NMC, "    m->Animating = 0;\n", ""),
    ("c_cam", NMC, "    m->CamNumber = 0;\n", ""),
    ("c_views", NMC, "    m->ViewsWatchingNis = 0;\n", ""),
    ("c_omm", NMC, "    m->OtherCarMovementModeBeforeNIS = 0;\n", ""),
    ("c_pmm", NMC, "    m->PlayerCarMovementModeBeforeNIS = 0;\n", ""),
    ("c_ret", NMC, "    return m;\n}\n\nvoid nismanager_destruct",
     "    return NULL;\n}\n\nvoid nismanager_destruct"),
    # ---- the destructor
    ("d_anim", NMC, "    if (gNisStopAnimatingFn != NULL)\n"
     "        gNisStopAnimatingFn(m);\n    nismanager_ensure",
     "    nismanager_ensure"),
    ("d_ensure", NMC, "    nismanager_ensure_nis_is_loaded(m);\n"
     "    if (m->LoadedNisNumber >= 0)\n        nismanager_unload(m);",
     "    if (m->LoadedNisNumber >= 0)\n        nismanager_unload(m);"),
    ("d_loaded", NMC, "    if (m->LoadedNisNumber >= 0)\n        nismanager_unload",
     "    if (m->LoadedNisNumber > 0)\n        nismanager_unload"),
    ("d_unlink_p", NMC, "    m->Node.prev->next = m->Node.next;\n", ""),
    ("d_unlink_n", NMC, "    m->Node.next->prev = m->Node.prev;\n", ""),
    ("d_order", NMC, "    for (i = 1; i >= 0; i--)\n        emodel_delete(&m->Other",
     "    for (i = 0; i <= 1; i++)\n        emodel_delete(&m->Other"),
    ("d_flags", NMC, "        emodel_delete(&m->PlayerCharProps[i], 0);",
     "        emodel_delete(&m->PlayerCharProps[i], 1);"),
    ("d_props_swap", NMC, "        emodel_delete(&m->OtherCharProps[i], 0);\n"
     "    for (i = 1; i >= 0; i--)\n        emodel_delete(&m->PlayerCharProps[i], 0);",
     "        emodel_delete(&m->PlayerCharProps[i], 0);\n"
     "    for (i = 1; i >= 0; i--)\n        emodel_delete(&m->OtherCharProps[i], 0);"),
    ("d_free", NMC, "    if (flags & 1)\n        bFree(m);", "    if (flags & 2)\n        bFree(m);"),
    # ---- Start
    ("s_st", NMC, "    m->StartTime = WorldTimeFrames;", "    m->StartTime = 0;"),
    ("s_cam", NMC, "    m->CamNumber = camera;", "    m->CamNumber = nis;"),
    ("s_play", NMC, "    m->Playing = 1;\n    m->NisNumber", "    m->NisNumber"),
    ("s_nis", NMC, "    m->NisNumber = nis;\n    m->PlayerCar",
     "    m->NisNumber = camera;\n    m->PlayerCar"),
    ("s_pc", NMC, "    m->PlayerCar = player;\n    m->OtherCar = other;",
     "    m->PlayerCar = other;\n    m->OtherCar = other;"),
    ("s_oc", NMC, "    m->PlayerCar = player;\n    m->OtherCar = other;",
     "    m->PlayerCar = player;\n    m->OtherCar = player;"),
    ("s_twice", NMC, "((uint32_t)frames << 1)", "((uint32_t)frames)"),
    ("s_wrap", NMC, "    m->EndTime = (int32_t)((uint32_t)WorldTimeFrames\n"
     "                           + ((uint32_t)frames << 1));",
     "    m->EndTime = (int32_t)((int64_t)WorldTimeFrames + 2 * (int64_t)frames > 0x7fffffff ? 0x7fffffff : WorldTimeFrames + 2 * frames);"),
    ("s_frames", NMC, "NisInfoTable[nis].NumFrames : 0;",
     "NisInfoTable[nis].NumCameras : 0;"),
    ("s_loaded", NMC, "    if (m->LoadedNisNumber != m->NisNumber) {",
     "    if (m->LoadedNisNumber == m->NisNumber) {"),
    ("s_load_arg", NMC, "            gNisManagerLoadFn(m, m->NisNumber);",
     "            gNisManagerLoadFn(m, m->CamNumber);"),
    ("s_ensure", NMC, "            gNisManagerLoadFn(m, m->NisNumber);\n"
     "        nismanager_ensure_nis_is_loaded(m);\n",
     "            gNisManagerLoadFn(m, m->NisNumber);\n"),
    ("s_setup", NMC, "        gNisSetupCarsBeforeNisFn(m);\n", "        ;\n"),
    ("s_anim", NMC, "        gNisStartAnimatingFn(m);\n", "        ;\n"),
    # ---- Stop
    ("x_guard", NMC, "    if (m->Playing == 0)\n        return;\n    if (gNisStop",
     "    if (gNisStop"),
    ("x_anim", NMC, "        gNisStopAnimatingFn(m);\n    if (gNisRestore",
     "        ;\n    if (gNisRestore"),
    ("x_restore", NMC, "        gNisRestoreCarsAfterNisFn(m);\n", "        ;\n"),
    ("x_oc", NMC, "    m->OtherCar = NULL;\n    m->CamNumber = -1;",
     "    m->CamNumber = -1;"),
    ("x_cam", NMC, "    m->CamNumber = -1;\n    m->Playing = 0;",
     "    m->CamNumber = 0;\n    m->Playing = 0;"),
    ("x_play", NMC, "    m->CamNumber = -1;\n    m->Playing = 0;",
     "    m->CamNumber = -1;"),
    ("x_st", NMC, "    m->Playing = 0;\n    m->StartTime = 0;\n    m->EndTime = 0;\n"
     "    m->NisNumber = -1;",
     "    m->Playing = 0;\n    m->EndTime = 0;\n    m->NisNumber = -1;"),
    ("x_et", NMC, "    m->StartTime = 0;\n    m->EndTime = 0;\n    m->NisNumber = -1;",
     "    m->StartTime = 0;\n    m->NisNumber = -1;"),
    ("x_nis", NMC, "    m->EndTime = 0;\n    m->NisNumber = -1;\n    m->PlayerCar",
     "    m->EndTime = 0;\n    m->NisNumber = 0;\n    m->PlayerCar"),
    ("x_pc", NMC, "    m->NisNumber = -1;\n    m->PlayerCar = NULL;\n}",
     "    m->NisNumber = -1;\n}"),
    # ---- the rest
    ("a_one", NMC, "    (void)m;\n    return 0;", "    (void)m;\n    return 1;"),
    ("i_play", NMC, "    return m->Playing;", "    return m->Animating;"),
    ("un_ensure", NMC, "    nismanager_ensure_nis_is_loaded(m);\n"
     "    if (m->LoadedNisNumber < 0)\n        return;",
     "    if (m->LoadedNisNumber < 0)\n        return;"),
    ("un_guard", NMC, "    if (m->LoadedNisNumber < 0)\n        return;",
     "    if (m->LoadedNisNumber <= 0)\n        return;"),
    ("un_nrf", NMC, "        gNisUnloadResourceFileFn(m->NisResourceFile);\n", ""),
    ("un_crf", NMC, "        gNisUnloadResourceFileFn(m->CamResourceFile);\n", ""),
    ("un_order", NMC, "        gNisUnloadResourceFileFn(m->NisResourceFile);\n"
     "        gNisUnloadResourceFileFn(m->CamResourceFile);\n",
     "        gNisUnloadResourceFileFn(m->CamResourceFile);\n"
     "        gNisUnloadResourceFileFn(m->NisResourceFile);\n"),
    ("un_mark", NMC, "    m->LoadedNisNumber = -1;\n}", "}"),
    ("e_test", NMC, "    while (m->LoadingNisNumber >= 0) {",
     "    while (m->LoadingNisNumber > 0) {"),
    ("e_once", NMC, "        gNisServiceResourceLoadingFn();\n    }",
     "        gNisServiceResourceLoadingFn();\n        break;\n    }"),
]
EQUIVALENT = {
    "n_null":
        "NumNisInfos is 0 whenever NisInfoTable is NULL -- the loader sets "
        "both and the unloader clears both -- so the loop does not run",
}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    indir = tempfile.TemporaryDirectory()
    lines, scp = write_inputs(indir.name)
    base_lines = model(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text(encoding="latin-1").splitlines()
        if diff(base_lines, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "nis_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base_lines, diff, EQUIVALENT, jobs)
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
        lines, scp = write_inputs(tmp)
        got = model(lines)
        exe = build_harness(tmp)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text(encoding="latin-1").splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(got) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(got, harness)
    print("%d ops, %d lines, %d differ" % (len(lines), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
