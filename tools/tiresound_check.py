#!/usr/bin/env python3
"""Cross-check 3DS Files/source/tiresound.c against the retail image,
SLES_507.31.

**The model** is retail's own CarSoundTires.obj run in
retail_model.RetailEmu with the EE's divide, product and root (eediv,
eemul, eesqrt): BaseTireSound's UpdateTireImpact, mute and destructor;
TerrainOneShot's Init, Mute, Update and destructor; PlayerTireSound's
constructor, destructor, Deactivate/ActivateSound, SetSamplePitch, the six
Calc functions, Mute, Update, UpdateSquall, UpdateLeaves, ResetThumperTime,
UpdateThumperTires, TriggerTireBlowOut and ScaleRoadNoise;
OpponentTireSound's Update, Mute, Deactivate/ActivateSound, UpdateSkids and
destructor; tire_sound's two factories (CreateAITire with the
OpponentTireSound constructor inline in it) and its two calls through slots
64 and 72; and the static constructor that sets ThumperAzimuthOffset -- the
virtual ones through the three vtables. Sound3d's constructor, destructor
and Activate and the smooth, min, max and clamp templates run in the image
too. The harness (tools/src/tiresound_test.c) runs tiresound.c's, through
the port's vtables, with copies of sound3d.c's three and terraintypetab.c's
table.

**The fakes**, the same on both sides, each printing what it is handed:
bSample's constructor, destructor, Initialize, SetCategory (which keeps the
category, as retail's does: UpdateTireImpact reads the bottom-out's back),
Play, Stop, Pause, SetAzimuth, SetVolume, SetPitch and IsPlaying (playing
from Play to Stop); bSound::Region (a region a name, made on demand, or
none), GetCategoryVolume (the script's) and Flush; bRegion::Sample and
GetInGameSample (a sample a name, none for those the script names); sound's
random float (the script's queue); the jukebox's saved volume (the
script's); bMalloc (0xa5-filled, its size checked against retail's
records) and __builtin_delete; and Sound3d's
UpdateCamRelativeDistAndVelocity.

**The script** dumps the tables; makes the player's tyres on each side and
an AI car's; runs them through the vtables -- Activate either way, Mute,
the camera, TriggerTireBlowOut, ScaleRoadNoise -- and through tire_sound's
two calls. It calls each Calc with the wheels on and off the ground, their
spin and slip either sign, at and past each threshold and cap, for each
side and one that is neither; lands each side's wheels, front and rear,
soft and hard, with the bottom-out's category kept or not and sound off;
inits, mutes and runs the one-shots with and without a sample and a delay;
runs the leaves on and off each kind; counts the thump down, slow and fast,
blown and not, either side, with the offset changed; and updates the
player's tyres frame by frame: inactive, on road, dirt and puddles, through
both one-shots, the skids, the squall, the burn-out and its bounds, the
road noise under the music and not, each switch off in turn. It runs the
AI's skids from road to dirt and back, ramping up and down, and updates,
mutes, deactivates and activates the AI's tyres; makes tyres with samples
missing, no region and sound off; and deletes each kind.

    python tools/tiresound_check.py
    python tools/tiresound_check.py --mutate [--only a,b]
    python tools/tiresound_check.py --dump out/tiresound
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

HARNESS = "tools/src/tiresound_test.c"
TSC = "3DS Files/source/tiresound.c"
TSH = "3DS Files/source/tiresound.h"
SOURCES = [HARNESS, TSC, "3DS Files/source/terraintypetab.c",
           "3DS Files/source/vtable.c"]
HARNESS_TIMEOUT = 30
LIMIT = 400000

GP = retail_model.RETAIL_GP
F = {
    "impact": 0x002125e0, "tosinit": 0x002127e0, "tosmute": 0x00212840,
    "tos": 0x00212860, "setpitch": 0x00212e98, "squallvp": 0x00212eb0,
    "skidvp": 0x00212f80, "nvol": 0x002131e0, "npitch": 0x002132a0,
    "svol": 0x00213338, "spitch": 0x00213440, "usq": 0x00213c30,
    "leaves": 0x00213dd8, "rtt": 0x00213f40, "thump": 0x00213f80,
    "mkplayer": 0x002141f8, "mkai": 0x00214250, "tbo": 0x00214338,
    "srn": 0x00214360, "sinit": 0x00214878, "skids": 0x00214ad8,
}

# What the vtables point at, by name.
FNAME = {
    0x00214a78: "base-dtor", 0x00208b28: "activate",
    0x002125a0: "base-mute", 0x00208c78: "camrel",
    0x00214a70: "base-tbo", 0x00214a68: "base-srn",
    0x00212cf0: "player-dtor", 0x002135a0: "player-update",
    0x002134d8: "player-mute", 0x00212e88: "player-deact",
    0x00212e90: "player-act", 0x00214a00: "player-tbo",
    0x002149f8: "player-srn", 0x002149a0: "ai-dtor",
    0x00214928: "ai-update", 0x002148e0: "ai-mute", 0x00214898: "ai-deact",
    0x00214890: "ai-act", 0x002a0550: "pure",
}
VT_BASE, VT_PLAYER, VT_AI = 0x002bc1e8, 0x002bc198, 0x002bc148
VT_TABLES = (("base", VT_BASE), ("player", VT_PLAYER), ("ai", VT_AI))
VT_ENTRIES = 10

SE, CSE, CDSE, RNE = GP - 23056, GP - 20456, GP - 20460, GP - 16248
DELAY, THOFF, WTE = GP - 16244, GP - 13344, GP - 19560
BSOUND, CTI = GP - 13696, GP - 21952

# Retail's records.
SIZES = {"PlayerTireSound": 2744, "kAITireSound": 804}
CAR_SIZE = 2304
TRACK_SIZE = 256
TRACK_REGION = 132
CATEGORY, CURVOL = 132, 24

# The tyres' samples, by the script's names.
P_SAMPLES = (
    ("tf", 36), ("bo", 224), ("mb", 464), ("ph", 668), ("lv", 864),
    ("rn", 1052), ("dn", 1240), ("rk", 1428), ("dk", 1616), ("sq", 1804),
    ("ds", 1992), ("bp", 2180), ("bu", 2368), ("bs", 2556),
)
A_SAMPLES = (("tf", 36), ("bo", 224), ("rk", 416), ("dk", 604))
ONE_SHOTS = {"mb": 452, "ph": 656}

# The retail Car's: State at 64.
C_POS, C_VELZ, C_ANG = 96, 120, 208
C_WAV, C_TOUCH, C_TERR, C_CROSS = 752, 848, 852, 868
C_SLIP, C_TRAC, C_VMAG, C_THR = 884, 916, 964, 972
C_BLOWN = 2125

# The dumps' fields: name, offset, type (as the harness's; p a pointer).
PFIELDS = (
    ("act", 0, "i"), ("dop", 4, "i"), ("svol", 8, "f"),
    ("spitch", 12, "f"), ("saz", 16, "H"), ("ft", 32, "H"),
    ("rt", 34, "H"), ("bocat", 224 + CATEGORY, "i"), ("car", 412, "p"),
    ("lrp", 416, "f"), ("csp", 420, "f"), ("csv", 424, "f"),
    ("mode", 428, "i"), ("side", 432, "i"), ("rns", 436, "f"),
    ("pts", 440, "i"), ("utt", 444, "f"), ("prev", 448, "i"),
    ("mbf", 452, "i"), ("mbon", 456, "i"), ("mbd", 460, "p"),
    ("mbside", 652, "i"), ("phf", 656, "i"), ("phon", 660, "i"),
    ("phd", 664, "p"), ("phside", 856, "i"), ("fls", 860, "i"),
)
AFIELDS = (
    ("act", 0, "i"), ("dop", 4, "i"), ("svol", 8, "f"),
    ("spitch", 12, "f"), ("saz", 16, "H"), ("ft", 32, "H"),
    ("rt", 34, "H"), ("bocat", 224 + CATEGORY, "i"), ("car", 412, "p"),
    ("prev", 792, "p"), ("csv", 796, "f"), ("tsv", 800, "f"),
)
PACK = {"i": "<i", "H": "<H", "f": "<I", "p": "<I"}


def fbits(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def fx(x):
    return "%08x" % fbits(x)


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True,
                                            eemul=True, eesqrt=True)
        e.stub_bware()
        self.allocs = []                # (address, tag)
        self.srcs = {}                  # (name, in-game) -> sample
        self.regs = {}                  # name -> region
        self.missing, self.nosrc = set(), set()
        self.noregion = 0
        self.playing = set()
        self.rf = []
        self.catvol = 0
        self.jbvol = fbits(1.0)
        self.cars, self.snds = {}, {}
        self.bsound = e.alloc(16)
        self.track = e.alloc(TRACK_SIZE, 16)
        e.mem[self.track:self.track + TRACK_SIZE] = b"\0" * TRACK_SIZE
        e.write(self.track + TRACK_REGION, b"T0\0")
        self.scratch = e.alloc(64, 16)
        e.put32(BSOUND, self.bsound)
        e.put32(CTI, self.track)
        e.put32(SE, 1)
        e.put32(CSE, 1)
        e.put32(CDSE, 1)
        e.put32(RNE, 1)
        e.put32(WTE, 0)
        e.put32(DELAY, 0)

        e.stub(0x00208c78, self.camrel)
        e.stub(0x00272ff0, self.b_ctor)
        e.stub(0x00273148, self.b_dtor)
        e.stub(0x00273210, self.b_init)
        e.stub(0x00273618, self.b_cat)
        e.stub(0x00274080, self.b_play)
        e.stub(0x00274618, self.b_stop)
        e.stub(0x00274488, self.b_pause)
        e.stub(0x00273e70, self.b_az)
        e.stub(0x00273d50, self.b_vol)
        e.stub(0x00273738, self.b_pitch)
        e.stub(0x00274410, self.b_isplaying)
        e.stub(0x00277a18, self.region)
        e.stub(0x00277dc0, self.catvolume)
        e.stub(0x002783b0, self.flush)
        e.stub(0x002719b8, self.rsample)
        e.stub(0x001ae280, self.ingame)
        e.stub(0x001af9c0, self.randf)
        e.stub(0x001ae028, self.saved_volume)
        e.stub(0x002577c0, self.malloc)
        e.stub(0x00114e98, self.delete)
        e.stub(0x00257850, self.delete)

        # The static constructor: ThumperAzimuthOffset.
        self.call("sinit")

    def emit(self, s):
        self.out.append(s)

    def cstr(self, a, n=64):
        b = bytearray()
        mem = self.e.mem
        while len(b) < n and mem[a]:
            b.append(mem[a])
            a += 1
        return b.decode("latin-1")

    # ---- names

    def name(self, a):
        a &= M32
        if a == 0:
            return "0"
        if a == DELAY & M32:
            return "delay"
        for i, (p, tag) in enumerate(self.allocs):
            if a == p:
                return "m%d" % i
            if tag == "PlayerTireSound":
                for nm, off in P_SAMPLES:
                    if a == p + off:
                        return "m%d.%s" % (i, nm)
            if tag == "kAITireSound":
                for nm, off in A_SAMPLES:
                    if a == p + off:
                        return "m%d.%s" % (i, nm)
        for (nm, ingame), p in self.srcs.items():
            if a == p:
                return ("src:" if ingame else "rs:") + nm
        for nm, p in self.regs.items():
            if a == p:
                return "reg:" + nm
        for k in sorted(self.cars):
            c = self.cars[k]
            if a == c:
                return "car%d" % k
            if a == c + C_POS:
                return "car%d.pos" % k
        return "?"

    # ---- Sound3d

    def camrel(self, em):
        self.emit("  camrel %s pos=%s" % (self.name(em.reg[4]),
                                          self.name(em.reg[5])))
        return 0

    # ---- bSample

    def b_ctor(self, em):
        s = em.reg[4] & M32
        self.emit("  bctor %s" % self.name(s))
        return s

    def b_dtor(self, em):
        self.emit("  bdtor %s" % self.name(em.reg[4]))
        return 0

    def b_init(self, em):
        self.emit("  binit %s from %s" % (self.name(em.reg[4]),
                                          self.name(em.reg[5])))
        return 0

    def b_cat(self, em):
        s = em.reg[4] & M32
        self.emit("  bcat %s %d" % (self.name(s), em.reg[5] & M32))
        self.e.put32(s + CATEGORY, em.reg[5] & M32)
        return 0

    def b_play(self, em):
        s = em.reg[4] & M32
        self.emit("  bplay %s %08x %08x %08x" % (
            self.name(s), em.fpr[12], em.fpr[13], em.fpr[14]))
        self.playing.add(s)
        return 0

    def b_stop(self, em):
        s = em.reg[4] & M32
        self.emit("  bstop %s" % self.name(s))
        self.playing.discard(s)
        return 0

    def b_pause(self, em):
        self.emit("  bpause %s %d" % (self.name(em.reg[4]),
                                      1 if em.reg[5] & 0xff else 0))
        return 0

    def b_az(self, em):
        self.emit("  baz %s %d" % (self.name(em.reg[4]), em.reg[5] & 0xffff))
        return 0

    def b_vol(self, em):
        self.emit("  bvol %s %08x" % (self.name(em.reg[4]), em.fpr[12]))
        return 0

    def b_pitch(self, em):
        self.emit("  bpitch %s %08x" % (self.name(em.reg[4]), em.fpr[12]))
        return 0

    def b_isplaying(self, em):
        s = em.reg[4] & M32
        v = 1 if s in self.playing else 0
        self.emit("  bisplaying %s %d" % (self.name(s), v))
        return v

    # ---- bSound, the regions and the game's samples

    def check_bsound(self, em, what):
        if em.reg[4] & M32 != self.bsound:
            self.emit("  %s: not bSound's" % what)

    def region(self, em):
        nm = self.cstr(em.reg[5] & M32)
        self.emit("  region %s" % nm)
        self.check_bsound(em, "region")
        if self.noregion:
            return 0
        if nm not in self.regs:
            self.regs[nm] = self.e.alloc(16)
        return self.regs[nm]

    def catvolume(self, em):
        self.emit("  catvol %d -> %08x" % (em.reg[5] & M32, self.catvol))
        self.check_bsound(em, "catvol")
        em.fpr[0] = self.catvol
        return 0

    def flush(self, em):
        self.emit("  flush %d" % (em.reg[5] & 0xff))
        self.check_bsound(em, "flush")
        return 0

    def src(self, nm, ingame):
        if (nm, ingame) not in self.srcs:
            self.srcs[(nm, ingame)] = self.e.alloc(188, 16)
        return self.srcs[(nm, ingame)]

    def rsample(self, em):
        nm = self.cstr(em.reg[5] & M32)
        self.emit("  rsample %s %s" % (self.name(em.reg[4]), nm))
        if nm in self.missing:
            return 0
        return self.src(nm, 0)

    def ingame(self, em):
        nm = self.cstr(em.reg[4] & M32)
        self.emit("  ingame %s" % nm)
        if nm in self.nosrc:
            return 0
        return self.src(nm, 1)

    def randf(self, em):
        v = self.rf.pop(0) if self.rf else 0
        self.emit("  randf %08x -> %08x" % (em.fpr[12], v))
        em.fpr[0] = v
        return 0

    def saved_volume(self, em):
        self.emit("  jbvol %d -> %08x" % (em.reg[4] & M32, self.jbvol))
        em.fpr[0] = self.jbvol
        return 0

    # ---- the heap

    def malloc(self, em):
        e = self.e
        size = s32(em.reg[4])
        tag = self.cstr(em.reg[5] & M32)
        p = e.alloc(size, 16)
        e.mem[p:p + size] = b"\xa5" * size
        self.allocs.append((p, tag))
        self.emit("  malloc %s %d %d size-%s -> m%d" % (
            tag, s32(em.reg[6]), s32(em.reg[7]),
            "ok" if SIZES.get(tag) == size else "BAD",
            len(self.allocs) - 1))
        return p

    def delete(self, em):
        self.emit("  delete %s" % self.name(em.reg[4]))
        return 0

    # ---- the dumps

    def field(self, a, t):
        v = struct.unpack_from(PACK[t], self.e.mem, a)[0]
        if t == "f":
            return "%08x" % v
        if t == "p":
            return self.name(v)
        return "%d" % v

    def dump(self, tag, k, fields):
        s = self.snds[k]
        line = "  %s %s vt=%08x" % (tag, self.name(s), self.e.u32(s + 28))
        for nm, off, t in fields:
            line += " %s=%s" % (nm, self.field(s + off, t))
        if tag == "pd":
            line += " delay=%08x" % self.e.u32(DELAY)
        self.emit(line)

    def dump_tables(self):
        e = self.e
        for label, vt in VT_TABLES:
            self.emit("  vt %s %d entries" % (label, VT_ENTRIES))
            for k in range(1, VT_ENTRIES):
                d = s16(e.u16(vt + 8 * k))
                fn = e.u32(vt + 8 * k + 4)
                self.emit("  vt %s %d %d %s" % (label, 8 * k, d,
                                                FNAME.get(fn, "?")))

    # ---- the cars

    def new_car(self, k):
        e = self.e
        c = self.cars[k] = e.alloc(CAR_SIZE, 16)
        e.mem[c:c + CAR_SIZE] = b"\xa5" * CAR_SIZE
        for j in range(4):
            e.put32(c + C_POS + 4 * j, 0)
        e.put32(c + C_VELZ, 0)
        e.put32(c + C_ANG, 0)
        e.put32(c + C_ANG + 4, 0)
        for i in range(4):
            e.mem[c + C_TOUCH + i] = 1
            e.put32(c + C_TERR + 4 * i, 0)
            e.put32(c + C_CROSS + 4 * i, 0)
            e.put32(c + C_SLIP + 8 * i, 0)
            e.put32(c + C_SLIP + 8 * i + 4, 0)
            e.put32(c + C_WAV + 4 * i, 0)
            e.put32(c + C_TRAC + 4 * i, 0)
        e.put32(c + C_VMAG, 0)
        e.put32(c + C_THR, 0)
        e.mem[c + C_BLOWN] = 0

    # ---- the ops

    def call(self, name, *args):
        return self.e.call(F[name], *args, limit=LIMIT)

    def sample_ref(self, k, w):
        s = self.snds[k]
        if w[0] == "a":
            for nm, off in A_SAMPLES:
                if w[1:] == nm:
                    return s + off
        for nm, off in P_SAMPLES:
            if w == nm:
                return s + off
        self.emit("  no sample %s" % w)
        return self.src("?", 0)

    def set_field(self, base, fields, nm, v):
        for fn, off, t in fields:
            if fn != nm:
                continue
            if t == "f":
                self.e.put32(base + off, int(v, 16))
            elif t == "p":
                self.emit("  pointer field %s" % nm)
            else:
                x = int(v, 0)
                size = struct.calcsize(PACK[t])
                struct.pack_into("<%s" % {2: "H", 4: "I"}[size],
                                 self.e.mem, base + off,
                                 x & ((1 << (8 * size)) - 1))
            return
        self.emit("  no field %s" % nm)

    def op(self, f):
        e = self.e

        def i(k):
            return int(f[k], 0) if k < len(f) else 0

        def fb(k):
            return int(f[k], 16) & M32 if k < len(f) else 0

        def snd(k):
            return self.snds[i(k)]

        def car(k):
            return self.cars[i(k)]

        o = f[0]
        if o == "tables":
            self.dump_tables()
        elif o == "se":
            e.put32(SE, i(1))
        elif o == "cse":
            e.put32(CSE, i(1))
        elif o == "cdse":
            e.put32(CDSE, i(1))
        elif o == "rne":
            e.put32(RNE, i(1))
        elif o == "wte":
            e.put32(WTE, fb(1))
        elif o == "delay":
            e.put32(DELAY, fb(1))
        elif o == "thoff":
            struct.pack_into("<H", e.mem, THOFF, i(1) & 0xffff)
        elif o == "catvol":
            self.catvol = fb(1)
        elif o == "jbvol":
            self.jbvol = fb(1)
        elif o == "rf":
            self.rf.append(fb(1))
        elif o == "missing":
            self.missing.add(f[1])
        elif o == "nosrc":
            self.nosrc.add(f[1])
        elif o == "unsrc":
            self.missing.clear()
            self.nosrc.clear()
        elif o == "noregion":
            self.noregion = i(1)
        elif o == "track":
            e.write(self.track + TRACK_REGION, f[1].encode() + b"\0")
        elif o == "car":
            self.new_car(i(1))
        elif o == "wheel":
            c, w = car(1), i(2)
            e.mem[c + C_TOUCH + w] = i(3) & 0xff
            e.put32(c + C_TERR + 4 * w, i(4))
            e.put32(c + C_CROSS + 4 * w, i(5))
            e.put32(c + C_SLIP + 8 * w, fb(6))
            e.put32(c + C_SLIP + 8 * w + 4, fb(7))
            e.put32(c + C_WAV + 4 * w, fb(8))
            e.put32(c + C_TRAC + 4 * w, fb(9))
        elif o == "cv":
            c = car(1)
            e.put32(c + C_VELZ, fb(2))
            e.put32(c + C_ANG, fb(3))
            e.put32(c + C_ANG + 4, fb(4))
            e.put32(c + C_VMAG, fb(5))
            e.put32(c + C_THR, fb(6))
        elif o == "blown":
            e.mem[car(1) + C_BLOWN] = i(2) & 0xff
        elif o == "mk":
            k = i(1)
            if f[2] == "player":
                self.snds[k] = self.call("mkplayer", self.cars[k],
                                         i(3)) & M32
            else:
                self.snds[k] = self.call("mkai", self.cars[k]) & M32
            self.emit("  -> %s" % self.name(self.snds[k]))
        elif o == "vc":
            self.vcall(f, i, fb)
        elif o == "tbo":
            self.call("tbo", snd(1))
        elif o == "srn":
            e.fpr[12] = fb(2)
            self.call("srn", snd(1))
        elif o == "impact":
            self.call("impact", snd(1), car(2), i(3))
        elif o == "tos":
            e.fpr[12] = fb(4)
            e.fpr[13] = fb(6)
            self.call("tos", snd(1) + ONE_SHOTS[f[2]], car(1), i(3),
                      i(5) & 0xffff)
        elif o == "tosmute":
            self.call("tosmute", snd(1) + ONE_SHOTS[f[2]], i(3))
        elif o == "tosinit":
            smp = self.src(f[3], 1) if f[3] != "0" else 0
            self.call("tosinit", snd(1) + ONE_SHOTS[f[2]], smp,
                      DELAY & M32 if i(5) else 0, i(4))
        elif o == "setpitch":
            e.fpr[12] = fb(3)
            self.call("setpitch", snd(1), self.sample_ref(i(1), f[2]))
        elif o in ("squallvp", "skidvp"):
            q = self.scratch
            e.put32(q, fb(2))
            e.put32(q + 4, fb(3))
            self.call(o, snd(1), q, q + 4)
            self.emit("  = %08x %08x" % (e.u32(q), e.u32(q + 4)))
        elif o in ("nvol", "npitch", "svol", "spitch"):
            self.call(o, snd(1))
            self.emit("  = %08x" % e.fpr[0])
        elif o == "usq":
            e.fpr[12] = fb(3)
            e.fpr[13] = fb(5)
            self.call("usq", snd(1), i(2), i(4) & 0xffff)
        elif o in ("leaves", "skids"):
            e.fpr[12] = fb(2)
            e.fpr[13] = fb(4)
            self.call(o, snd(1), i(3) & 0xffff)
        elif o in ("rtt", "thump"):
            self.call(o, snd(1))
        elif o == "bplaying":
            b = self.sample_ref(i(1), f[2])
            if i(3):
                self.playing.add(b)
            else:
                self.playing.discard(b)
        elif o == "bcv":
            e.put32(self.sample_ref(i(1), f[2]) + CURVOL, fb(3))
        elif o == "pset":
            self.set_field(snd(1), PFIELDS, f[2], f[3])
        elif o == "aset":
            self.set_field(snd(1), AFIELDS, f[2], f[3])
        elif o == "pd":
            self.dump("pd", i(1), PFIELDS)
        elif o == "ad":
            self.dump("ad", i(1), AFIELDS)
        else:
            self.emit("  unknown op %s" % o)

    def vcall(self, f, i, fb):
        """A call through the vtable, as the image makes one: the vptr at
        +28, the delta added to the Sound3d."""
        e = self.e
        slot = i(2)
        t = self.snds[i(1)]
        vt = e.u32(t + 28)
        delta = s16(e.u16(vt + slot))
        fn = e.u32(vt + slot + 4)
        this = (t + delta) & M32
        if slot in (8, 16, 32):
            e.call(fn, this, i(3), limit=LIMIT)
        elif slot == 24:
            e.fpr[12] = fb(3)
            e.fpr[13] = fb(5)
            e.call(fn, this, i(4) & 0xffff, limit=LIMIT)
        elif slot in (40, 48, 64):
            e.call(fn, this, limit=LIMIT)
        elif slot == 56:
            e.call(fn, this, self.cars[i(3)] + C_POS, limit=LIMIT)
        elif slot == 72:
            e.fpr[12] = fb(3)
            e.call(fn, this, limit=LIMIT)
        else:
            self.emit("  bad slot %d" % slot)

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

    def upd(k, vol, az, pitch):
        a("vc|%d|24|%s|%d|%s" % (k, fx(vol), az, fx(pitch)))

    def wheel(k, w, touch=1, terr=1, cross=1, sx=0.0, sy=0.0, wav=0.0,
              trac=0.0):
        a("wheel|%d|%d|%d|%d|%d|%s|%s|%s|%s" % (
            k, w, touch, terr, cross, fx(sx), fx(sy), fx(wav), fx(trac)))

    def wheels(k, *args, **kw):
        for w in range(4):
            wheel(k, w, *args, **kw)

    def cv(k, velz=0.0, angx=0.0, angy=0.0, vmag=0.0, thr=0.0):
        a("cv|%d|%s|%s|%s|%s|%s" % (k, fx(velz), fx(angx), fx(angy),
                                    fx(vmag), fx(thr)))

    def calcs(k):
        for o in ("nvol", "npitch", "svol", "spitch"):
            a("%s|%d" % (o, k))
        a("skidvp|%d|%s|%s" % (k, fx(7.0), fx(9.0)))

    # ---- the tables and the tyres
    a("tables")
    for k in range(6):
        a("car|%d" % k)
    a("mk|0|player|0")
    a("pd|0")
    a("mk|1|player|1")
    a("pd|1")
    a("mk|2|ai")
    a("ad|2")
    a("mk|3|player|-1")
    a("pd|3")

    # ---- the vtables' small ones
    for k in (0, 2):
        a("vc|%d|16|0" % k)
        a("vc|%d|16|0" % k)
        a("vc|%d|16|1" % k)
        a("vc|%d|16|1" % k)
        a("vc|%d|32|1" % k)
        a("vc|%d|32|0" % k)
        a("vc|%d|32|7" % k)
        a("vc|%d|56|%d" % (k, k))
        a("vc|%d|40" % k)
        a("vc|%d|48" % k)
        a("vc|%d|64" % k)
        a("vc|%d|72|%s" % (k, fx(0.5)))
        a("tbo|%d" % k)
        a("srn|%d|%s" % (k, fx(0.25)))
    a("pd|0")
    # The static calls on their own, each seen.
    a("pset|0|pts|0")
    a("tbo|0")
    a("pd|0")
    a("srn|0|%s" % fx(0.75))
    a("pd|0")
    a("srn|0|%s" % fx(0.25))
    a("ad|2")
    a("pset|0|pts|0")
    a("vc|2|16|1")
    a("ad|2")

    # ---- SetSamplePitch
    a("setpitch|0|rn|%s" % fx(1.3))
    a("setpitch|0|ds|%s" % fx(0.0))
    a("setpitch|0|lv|%s" % fx(-2.5))

    # ---- the Calc functions, on each side and none
    for k, side in ((0, 0), (1, 1), (3, -1), (3, 2)):
        a("pset|%d|side|%d" % (k, side))
        cv(k, vmag=0.0)
        wheels(k)
        calcs(k)
        # Spin either way, one wheel at a time off the ground.
        for w in range(4):
            wheel(k, w, wav=[50.0, -80.0, 120.0, -30.0][w],
                  trac=[0.9, -0.6, 0.3, 1.2][w],
                  sx=[0.3, -0.2, 2.0, -1.5][w], sy=[0.1, 0.25, -0.5, 1.0][w])
        cv(k, vmag=12.0)
        calcs(k)
        for w in range(4):
            wheel(k, w, touch=0, wav=60.0, trac=0.9, sx=1.0, sy=1.0)
            calcs(k)
            wheel(k, w, touch=[2, -1, 1, 3][w], wav=60.0, trac=0.9,
                  sx=1.0, sy=1.0)
        calcs(k)
        # The caps: noise volume past 1, squall volume past 1.
        wheels(k, wav=-400.0, trac=-3.0, sx=20.0, sy=-20.0)
        cv(k, vmag=-50.0)
        calcs(k)
        wheels(k, wav=115.0)
        a("nvol|%d" % k)
        # The pitch from a wheel spun backwards, and from one off the ground.
        for w in range(4):
            wheel(k, w, wav=[-150.0, -150.0, 20.0, 20.0][w])
        a("npitch|%d" % k)
        for w in range(4):
            wheel(k, w, touch=[1, 1, 0, 0][w],
                  wav=[10.0, 10.0, 90.0, 90.0][w])
        a("npitch|%d" % k)
        a("nvol|%d" % k)
        # One pair's traction past 0.7 and the other's not.
        for w in range(4):
            wheel(k, w, trac=[0.1, 1.2, 0.4, 0.1][w])
        cv(k, vmag=20.0)
        a("svol|%d" % k)
        # Speed either side of 11, traction either side of 0.7.
        for vm in (10.999, 11.0, -11.0, -10.5):
            cv(k, vmag=vm)
            a("svol|%d" % k)
        for tr in (0.7, 0.70001, 0.69999, -0.71):
            wheels(k, trac=tr)
            cv(k, vmag=20.0)
            a("svol|%d" % k)
        # Slip either side of 0.25, the mean either side of 0.01.
        for sl in (0.25, 0.2499, 0.26, 0.0141, 0.01, 0.5, 3.0):
            wheels(k, sx=sl, sy=0.0)
            a("skidvp|%d|%s|%s" % (k, fx(5.0), fx(5.0)))
            a("pd|%d" % k)
        wheels(k, sx=0.0)
        a("skidvp|%d|%s|%s" % (k, fx(5.0), fx(5.0)))
        a("pd|%d" % k)
        # One wheel of each pair slipping: the mean under 0.2.
        wheel(k, 0, sx=0.3)
        wheel(k, 2, sx=0.3)
        a("skidvp|%d|%s|%s" % (k, fx(5.0), fx(5.0)))
        a("pd|%d" % k)
        # The pitches inside their clamps, the lock let go between.
        for sl in (15.0, 16.5, 18.0, 19.5):
            wheels(k, sx=0.0)
            a("skidvp|%d|%s|%s" % (k, fx(5.0), fx(5.0)))
            wheels(k, sx=sl, sy=0.0)
            a("skidvp|%d|%s|%s" % (k, fx(5.0), fx(5.0)))
            a("pd|%d" % k)
        wheels(k, sx=30.0, sy=1.0)
        a("skidvp|%d|%s|%s" % (k, fx(5.0), fx(5.0)))
        wheels(k, sx=10.0, sy=1.0)
        a("skidvp|%d|%s|%s" % (k, fx(5.0), fx(5.0)))
        a("pd|%d" % k)
        # The squall's volume eased up and down, and held.
        for tr, vm in ((1.0, 20.0), (1.0, 20.0), (0.8, 20.0), (0.0, 5.0),
                       (0.9, 15.0), (0.9, 15.0), (0.71, 30.0), (0.0, 30.0)):
            wheels(k, trac=tr)
            cv(k, vmag=vm)
            a("squallvp|%d|%s|%s" % (k, fx(3.0), fx(4.0)))
            a("pd|%d" % k)
        for csv in (0.5, 0.0, 0.2):
            a("pset|%d|csv|%s" % (k, fx(csv)))
            a("squallvp|%d|%s|%s" % (k, fx(3.0), fx(4.0)))
    a("pset|0|side|0")
    a("pset|1|side|1")
    a("pset|3|side|-1")

    # ---- UpdateTireImpact: each side, landing front and rear
    for k, side in ((0, 0), (0, 1), (0, -1), (0, 2), (0, -2), (2, -1),
                    (2, 1), (2, 0)):
        wheels(k, touch=0)
        a("impact|%d|%d|%d" % (k, k, side))
        a("pd|%d" % k if k != 2 else "ad|2")
        cv(k, velz=-2.0, angx=0.5, angy=-0.25)
        for w in range(4):
            wheel(k, w, touch=[1, 2, -1, 3][w])
            a("rf|%s" % fx(0.3))
            a("impact|%d|%d|%d" % (k, k, side))
            a("pd|%d" % k if k != 2 else "ad|2")
            wheel(k, w, touch=0)
            a("impact|%d|%d|%d" % (k, k, side))
    # Soft, hard, past 1; the bottom-out's category kept or not.
    for k in (0, 2):
        for velz, angx, angy in ((-1.0, 0.0, 0.0), (-6.0, 0.0, 0.0),
                                 (-6.0, 0.1, 0.0), (6.0, 0.0, 0.0),
                                 (0.0, 2.25, 0.0), (0.0, 0.0, -2.26),
                                 (-20.0, 3.0, 4.0), (-3.0, 1.0, 1.0),
                                 (-5.6667, 0.0, 0.0),
                                 # 0.9 exactly, rounded or truncated.
                                 (-5.9983720779418945, 0.0006103515625,
                                  0.0)):
            cv(k, velz=velz, angx=angx, angy=angy)
            wheels(k, touch=0)
            a("impact|%d|%d|-1" % (k, k))
            wheels(k, touch=1)
            a("rf|%s" % fx(0.55))
            a("jbvol|%s" % fx(0.6))
            a("impact|%d|%d|-1" % (k, k))
    a("jbvol|%s" % fx(1.0))
    # Each switch off.
    for sw in ("se", "cse", "rne"):
        a("%s|0" % sw)
        cv(0, velz=-20.0)
        wheels(0, touch=0)
        a("impact|0|0|-1")
        wheels(0, touch=1)
        a("rf|%s" % fx(0.1))
        a("impact|0|0|-1")
        a("%s|1" % sw)
    # Already touching: nothing plays.
    a("pset|0|ft|1")
    a("pset|0|rt|1")
    a("impact|0|0|-1")
    a("pset|0|ft|0")
    a("pset|0|rt|5")
    a("impact|0|0|-1")
    a("pd|0")
    cv(0)
    cv(2)
    wheels(0)
    wheels(2)

    # ---- the one-shots
    a("pd|0")
    for which, terr in (("mb", 30), ("ph", 31)):
        a("delay|0")
        for w, cr in ((0, terr), (1, terr), (2, terr), (3, terr)):
            wheels(0, cross=1)
            a("tos|0|%s|%d|%s|%d|%s" % (which, terr, fx(0.6), 5000,
                                        fx(1.2)))
            wheel(0, w, cross=cr)
            a("tos|0|%s|%d|%s|%d|%s" % (which, terr, fx(0.6), 5000,
                                        fx(1.2)))
            a("pd|0")
            a("tos|0|%s|%d|%s|%d|%s" % (which, terr, fx(0.6), 65535,
                                        fx(1.2)))
            a("delay|0")
        # The other side.
        a("pset|0|%sside|1" % which)
        for w in range(4):
            wheels(0, cross=1)
            a("tos|0|%s|%d|%s|%d|%s" % (which, terr, fx(0.6), 1, fx(0.5)))
            wheel(0, w, cross=terr)
            a("tos|0|%s|%d|%s|%d|%s" % (which, terr, fx(0.6), 1, fx(0.5)))
            a("delay|0")
        a("pset|0|%sside|0" % which)
        # The delay running, and just out.
        wheels(0, cross=1)
        a("tos|0|%s|%d|%s|%d|%s" % (which, terr, fx(0.6), 1, fx(0.5)))
        wheels(0, cross=terr)
        for d in (0.1, 0.0, -0.1, 1e-30):
            a("delay|%s" % fx(d))
            a("pset|0|%son|0" % which)
            a("tos|0|%s|%d|%s|%d|%s" % (which, terr, fx(0.6), 1, fx(0.5)))
            a("pd|0")
        a("tosmute|0|%s|1" % which)
        a("tosmute|0|%s|0" % which)
        a("tosmute|0|%s|9" % which)
    # Without a sample, and without a delay.
    a("tosinit|0|mb|0|1|1")
    a("pd|0")
    a("tosmute|0|mb|1")
    wheels(0, cross=30)
    a("tos|0|mb|30|%s|1|%s" % (fx(0.6), fx(0.5)))
    a("tosinit|0|mb|MetalBump|1|0")
    a("pd|0")
    a("tos|0|mb|30|%s|1|%s" % (fx(0.6), fx(0.5)))
    a("pd|0")
    a("tos|0|mb|30|%s|1|%s" % (fx(0.6), fx(0.5)))
    wheels(0, cross=1)
    a("tos|0|mb|30|%s|1|%s" % (fx(0.6), fx(0.5)))
    wheels(0, cross=30)
    a("tos|0|mb|30|%s|1|%s" % (fx(0.6), fx(0.5)))
    a("pd|0")
    a("tosinit|0|mb|MetalBump|0|1")
    a("tosinit|3|ph|TireFlop|-1|1")
    a("pd|3")
    a("delay|0")
    wheels(0)

    # ---- the leaves
    for k in (0, 1, 3):
        for w in range(4):
            for terr in (23, 24, 27, 22):
                wheels(k, terr=1)
                wheel(k, w, terr=terr)
                a("leaves|%d|%s|%d|%s" % (k, fx(0.7), 40000, fx(1.1)))
                a("leaves|%d|%s|%d|%s" % (k, fx(0.4), 300, fx(0.9)))
        wheels(k, terr=1)
        a("leaves|%d|%s|%d|%s" % (k, fx(0.7), 40000, fx(1.1)))
    a("pset|0|fls|0")
    wheels(0, terr=23)
    a("leaves|0|%s|%d|%s" % (fx(0.7), 40000, fx(1.1)))
    a("pset|0|fls|1")
    wheels(0)

    # ---- the thump and the scrape
    for k in (0, 1, 3):
        a("pset|%d|svol|%s" % (k, fx(0.8)))
        a("pset|%d|spitch|%s" % (k, fx(1.1)))
        a("pset|%d|saz|%d" % (k, 3000 + k))
        a("rtt|%d" % k)
        a("pset|%d|prev|1" % k)
        a("blown|%d|1" % k)
        a("wte|%s" % fx(0.05))
        # The time out exactly.
        cv(k, vmag=10.0)
        a("pset|%d|utt|%s" % (k, fx(0.05)))
        a("thump|%d" % k)
        a("pd|%d" % k)
        for vm in (0.0, 2.9, 3.0, -3.0, 10.0, 20.0, 60.0, 54.3, 200.0,
                   -40.0):
            cv(k, vmag=vm)
            a("pset|%d|utt|%s" % (k, fx(0.04)))
            a("thump|%d" % k)
            a("pd|%d" % k)
            a("thump|%d" % k)
            a("pd|%d" % k)
        cv(k, vmag=20.0)
        a("pset|%d|utt|0" % k)
        # Each side's wheels off the ground in turn.
        for w in range(4):
            wheels(k, touch=1)
            wheel(k, w, touch=0)
            a("pset|%d|utt|0" % k)
            a("thump|%d" % k)
        for w in range(4):
            wheels(k, touch=0)
            wheel(k, w, touch=1)
            a("pset|%d|utt|0" % k)
            a("thump|%d" % k)
        wheels(k, touch=0)
        a("pset|%d|utt|0" % k)
        a("thump|%d" % k)
        wheels(k, touch=1)
        # The scrape's conditions, one at a time.
        a("pset|%d|ft|0" % k)
        a("pset|%d|rt|0" % k)
        a("thump|%d" % k)
        a("pset|%d|rt|1" % k)
        a("thump|%d" % k)
        a("pset|%d|ft|1" % k)
        a("pset|%d|rt|0" % k)
        a("thump|%d" % k)
        a("pset|%d|rt|1" % k)
        a("pset|%d|prev|0" % k)
        a("thump|%d" % k)
        a("pset|%d|prev|1" % k)
        a("thump|%d" % k)
        for n in (0, 255, 128, 127, 2):
            a("blown|%d|%d" % (k, n))
            a("thump|%d" % k)
        a("cdse|0")
        a("pset|%d|utt|0" % k)
        a("thump|%d" % k)
        a("cdse|1")
        for sw in ("se", "cse"):
            a("%s|0" % sw)
            a("pset|%d|utt|0" % k)
            a("thump|%d" % k)
            a("%s|1" % sw)
        a("thoff|40000")
        a("pset|%d|utt|0" % k)
        a("thump|%d" % k)
        a("thoff|0")
        a("pset|%d|utt|0" % k)
        a("thump|%d" % k)
        a("thoff|8192")
        a("bplaying|%d|bs|1" % k)
        a("rtt|%d" % k)
        a("rtt|%d" % k)
        a("blown|%d|0" % k)
        a("pd|%d" % k)
    cv(0)
    cv(1)
    cv(3)
    a("wte|0")

    # ---- UpdateSquall
    for k in (0, 1):
        for onroad in (1, 0, 5):
            for tr, vm, cvol in ((1.0, 20.0, 0.0), (1.0, 20.0, 0.3),
                                 (0.0, 5.0, 0.3), (0.9, 30.0, 0.9),
                                 (0.9, 30.0, 0.88)):
                wheels(k, trac=tr)
                cv(k, vmag=vm)
                a("bcv|%d|sq|%s" % (k, fx(cvol)))
                a("bcv|%d|ds|%s" % (k, fx(cvol)))
                a("usq|%d|%d|%s|%d|%s" % (k, onroad, fx(0.8), 1234,
                                          fx(1.1)))
                a("pd|%d" % k)
            a("usq|%d|%d|%s|%d|%s" % (k, onroad, fx(0.0), 1234, fx(1.1)))
        for sw in ("se", "cse"):
            wheels(k, trac=1.0)
            cv(k, vmag=20.0)
            a("bplaying|%d|ds|1" % k)
            a("%s|0" % sw)
            a("usq|%d|1|%s|%d|%s" % (k, fx(0.8), 1, fx(1.0)))
            a("%s|1" % sw)
        wheels(k)
        cv(k)

    # ---- Update: the player's, frame by frame
    a("pset|0|act|0")
    upd(0, 0.9, 100, 1.0)
    a("pset|0|act|1")
    for k in (0, 1, 3):
        a("wte|%s" % fx(1.0 / 30))
        a("delay|%s" % fx(0.1))
        for terr in ((1, 1, 1, 1), (2, 2, 2, 2), (1, 2, 1, 2), (2, 1, 2, 1),
                     (4, 4, 4, 4), (4, 2, 4, 2), (2, 4, 2, 4),
                     (1, 1, 4, 4), (1, 1, 1, 1), (4, 4, 2, 2),
                     (19, 19, 19, 19), (18, 18, 18, 18),
                     (1, 19, 18, 1), (19, 1, 1, 18), (1, 19, 1, 1),
                     (1, 1, 18, 1), (19, 1, 1, 1), (1, 1, 1, 18),
                     (1, 18, 19, 1), (18, 1, 1, 19), (30, 30, 30, 30),
                     (31, 2, 31, 2), (27, 23, 24, 1)):
            if terr[0] == 31:
                a("delay|0")
            for w in range(4):
                wheel(k, w, terr=terr[w], cross=terr[w], wav=90.0,
                      sx=[0.5, 1.5, 4.0, 3.5][w], sy=0.2, trac=0.95)
            cv(k, vmag=25.0, thr=0.5)
            upd(k, 0.9, 2000, 1.05)
            a("pd|%d" % k)
            upd(k, 0.9, 2100, 1.05)
        # Blown tyres thump on any terrain; 128 is -128, none.
        for n in (1, 128, 2, 0):
            a("blown|%d|%d" % (k, n))
            wheels(k, terr=1)
            cv(k, vmag=25.0)
            upd(k, 0.9, 2000, 1.05)
            a("pd|%d" % k)
        # One wheel landing: the flop only from the side's own wheels.
        cv(k, velz=-3.0, vmag=25.0)
        for w in range(4):
            wheels(k, touch=0)
            upd(k, 0.9, 2000, 1.05)
            wheel(k, w, touch=1)
            a("rf|%s" % fx(0.3))
            upd(k, 0.9, 2000, 1.05)
            a("pd|%d" % k)
        # The burn-out's bounds: the slip is the rear pair's mean and the
        # front pair's added.
        wheels(k)
        for thr, sl, vm in ((0.5, 4.0, 10.0), (0.2, 4.0, 10.0),
                            (0.21, 3.0, 10.0), (0.21, 3.01, 29.99),
                            (0.21, 3.01, 30.0), (1.0, 100.0, -5.0),
                            (1.0, 6.0, 0.0)):
            for w in range(4):
                wheel(k, w, sx=sl / 2, sy=0.0)
            cv(k, vmag=vm, thr=thr)
            upd(k, 0.8, 300, 1.0)
            upd(k, 0.8, 300, 1.0)
        for w in range(4):
            wheel(k, w, sx=[0.5, 1.0, 4.0, 2.5][w], sy=9.0)
        cv(k, vmag=1.0, thr=1.0)
        upd(k, 0.8, 300, 1.0)
        for w in range(4):
            wheel(k, w, sx=[3.0, 0.0, 0.0, 0.5][w], sy=9.0)
        upd(k, 0.8, 300, 1.0)
        for w in range(4):
            wheel(k, w, sx=[0.0, 0.0, 6.0, 0.1][w], sy=9.0)
        upd(k, 0.8, 300, 1.0)
        for w in range(4):
            wheel(k, w, sx=[2.0, 2.0, 0.0, 0.0][w], sy=9.0)
        upd(k, 0.8, 300, 1.0)
        # The skid's caps, on road and dirt.
        for terr in (1, 2):
            wheels(k, terr=terr, sx=40.0, sy=0.0)
            cv(k, vmag=25.0)
            upd(k, 0.5, 9, 1.0)
            upd(k, 3.0, 9, 1.0)
            wheels(k, terr=terr, sx=0.0, sy=0.0)
            upd(k, 3.0, 9, 1.0)
        # The road noise under the music, and with each switch off.
        wheels(k, terr=1, wav=200.0)
        a("bplaying|%d|rn|0" % k)
        a("catvol|%s" % fx(0.5))
        upd(k, 0.7, 444, 1.0)
        a("catvol|0")
        upd(k, 0.7, 444, 1.0)
        a("srn|%d|%s" % (k, fx(0.5)))
        upd(k, 0.7, 444, 1.0)
        wheels(k, terr=2, wav=200.0)
        upd(k, 0.7, 444, 1.2)
        upd(k, 0.7, 444, 1.2)
        wheels(k, terr=1, wav=200.0)
        a("srn|%d|%s" % (k, fx(1.0)))
        for sw in ("se", "cse", "rne"):
            a("%s|0" % sw)
            for terr in (1, 2, 1):
                wheels(k, terr=terr, wav=200.0, sx=40.0, trac=1.0)
                cv(k, vmag=25.0, thr=0.5)
                a("bplaying|%d|rn|0" % k)
                a("bplaying|%d|dn|0" % k)
                upd(k, 0.7, 444, 1.0)
            a("%s|1" % sw)
        wheels(k)
        cv(k)
        a("pd|%d" % k)
    a("delay|0")
    a("wte|0")

    # ---- the AI's skids
    for terrs in ((1, 1, 1, 1), (2, 2, 2, 2), (1, 2, 2, 2), (1, 1, 2, 2),
                  (2, 1, 1, 1)):
        for w in range(4):
            wheel(2, w, terr=terrs[w])
        for sl in (5.0, 10.0, 9.99, 12.0, 0.2, 40.0):
            wheel(2, 1, sx=sl, sy=0.0)
            cv(2, vmag=33.0)
            a("skids|2|%s|%d|%s" % (fx(0.9), 700, fx(1.0)))
            a("ad|2")
        for _ in range(4):
            wheel(2, 1, sx=0.0)
            a("skids|2|%s|%d|%s" % (fx(0.9), 700, fx(1.0)))
            a("ad|2")
    # Each wheel off the ground, the slip either way.
    for w in range(4):
        wheels(2, terr=1, sx=0.0)
        wheel(2, w, touch=0, sx=20.0)
        a("skids|2|%s|%d|%s" % (fx(0.9), 1, fx(1.0)))
        wheel(2, w, touch=1, sx=-15.0, sy=-15.0)
        a("skids|2|%s|%d|%s" % (fx(0.9), 1, fx(1.0)))
        a("ad|2")
    # The terrain changing under a playing skid.
    for terr in (1, 2, 1, 2):
        wheels(2, terr=terr, sx=40.0)
        cv(2, vmag=33.0)
        a("skids|2|%s|%d|%s" % (fx(0.9), 700, fx(1.0)))
        a("skids|2|%s|%d|%s" % (fx(0.9), 700, fx(1.0)))
        a("ad|2")
    for sw in ("se", "cse"):
        a("%s|0" % sw)
        wheels(2, sx=20.0)
        a("aset|2|csv|0")
        a("skids|2|%s|%d|%s" % (fx(0.9), 1, fx(1.0)))
        a("bplaying|2|ark|1")
        a("aset|2|csv|0")
        wheels(2, sx=0.0)
        a("skids|2|%s|%d|%s" % (fx(0.9), 1, fx(1.0)))
        a("%s|1" % sw)
    # Update through the vtable, inactive and not.
    a("vc|2|16|0")
    upd(2, 0.9, 5, 1.3)
    a("vc|2|16|1")
    wheels(2, touch=0)
    upd(2, 0.9, 5, 1.3)
    cv(2, velz=-3.0)
    for w in range(4):
        wheel(2, w, touch=1)
        upd(2, 0.9, 5, 1.3)
        a("ad|2")
        wheels(2, touch=0)
        upd(2, 0.9, 5, 1.3)
    wheels(2, terr=2, sx=30.0)
    cv(2, velz=-8.0, vmag=40.0)
    a("rf|%s" % fx(0.2))
    upd(2, 0.9, 5, 1.3)
    a("ad|2")
    upd(2, 0.4, 6, 0.7)
    a("ad|2")
    a("vc|2|40")
    a("vc|2|32|1")
    a("vc|2|32|0")
    wheels(2)
    cv(2)

    # ---- tyres with samples missing, no region and sound off
    a("nosrc|MetalBump")
    a("nosrc|TireFlop")
    a("missing|Leaves")
    a("track|Autumn")
    a("mk|4|player|1")
    a("pd|4")
    wheels(4, cross=30)
    upd(4, 0.9, 1, 1.0)
    a("vc|4|32|1")
    a("unsrc")
    a("noregion|1")
    a("se|0")
    a("mk|5|player|0")
    a("pd|5")
    a("mk|5|ai")
    a("ad|5")
    a("se|1")
    a("noregion|0")
    a("cse|0")
    a("mk|5|player|7")
    a("pd|5")
    a("cse|1")
    a("rne|0")
    a("mk|5|player|0")
    a("rne|1")
    a("nosrc|LongitudinalSkid")
    a("nosrc|BottomOut")
    a("mk|5|ai")
    a("ad|5")
    a("unsrc")

    # ---- the destructors
    a("vc|0|8|3")
    a("vc|2|8|3")
    a("vc|1|8|0")
    a("vc|3|8|1")
    a("vc|4|8|2")
    a("vc|5|8|1")
    return L


# ================================================================= build

def build_harness(tmp, name="tiresound_test"):
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


def _m(name, before, after, rel=TSC):
    return (name, rel, before, after)


MUTATIONS = [
    # The globals and the helpers.
    _m("g-thoff", "uint16_t ThumperAzimuthOffset = 8192;",
       "uint16_t ThumperAzimuthOffset = 8000;"),
    _m("g-delay", "float    PlayerTireSoundOneShotTimeDelay;",
       "float    PlayerTireSoundOneShotTimeDelay = 0.5f;"),
    _m("g-noise-pitch", "TireNoisePitchScale = 0.0065f;",
       "TireNoisePitchScale = 0.007f;"),
    _m("max-min", "    return b < a ? a : b;", "    return b < a ? b : a;"),
    _m("min-max", "    return a < b ? a : b;", "    return a < b ? b : a;"),
    _m("smooth-up", "    float up = a + step;", "    float up = a + step * 0.5f;"),
    _m("smooth-down", "    down = a - step;", "    down = a - step * 0.5f;"),
    _m("smooth-down-cmp", "    if (b < down)\n        return down;",
       "    if (b > down)\n        return down;"),
    _m("slip-y", "    return ee_sqrt(v->x * v->x + v->y * v->y);",
       "    return ee_sqrt(v->x * v->x + v->x * v->y);"),
    _m("slip-sqrt", "    return ee_sqrt(v->x * v->x + v->y * v->y);",
       "    return v->x * v->x + v->y * v->y;"),
    _m("blown-unsigned", "    return (int8_t)c->NumBlownTires;",
       "    return c->NumBlownTires;"),

    # BaseTireSound.
    _m("base-rear", "    s->RearTireTouching = 1;", "    s->RearTireTouching = 0;"),
    _m("base-front", "    s->FrontTireTouching = 1;", "    s->FrontTireTouching = 0;"),
    _m("base-tf-cat", "    bsample_set_category(&s->TireFlop, 1);",
       "    bsample_set_category(&s->TireFlop, 0);"),
    _m("base-bo-cat", "    bsample_set_category(&s->BottomOut, 1);",
       "    bsample_set_category(&s->BottomOut, 0);"),
    _m("base-tf-name", "sound_get_in_game_sample(sound_get(), \"TireFlop\")",
       "sound_get_in_game_sample(sound_get(), \"TireFlap\")"),
    _m("base-bo-name", "sound_get(), \"BottomOut\")", "sound_get(), \"BottomOat\")"),
    _m("base-dtor-order", "    bsample_destruct(&s->BottomOut);\n"
       "    bsample_destruct(&s->TireFlop);",
       "    bsample_destruct(&s->TireFlop);\n"
       "    bsample_destruct(&s->BottomOut);"),
    _m("base-dtor-flags", "    sound3d_destroy(&s->Sound, flags);",
       "    sound3d_destroy(&s->Sound, 0);"),
    _m("base-mute-tf", "    bsample_pause(&s->TireFlop, on != 0);",
       "    bsample_pause(&s->TireFlop, on == 0);"),
    _m("base-mute-bo", "    bsample_pause(&s->BottomOut, on != 0);",
       "    bsample_pause(&s->BottomOut, 0);"),

    # UpdateTireImpact.
    _m("imp-all-front", "        front = t[0] != 0 || t[1] != 0;",
       "        front = t[0] != 0 && t[1] != 0;"),
    _m("imp-all-front-1", "        front = t[0] != 0 || t[1] != 0;",
       "        front = t[0] != 0 || t[2] != 0;"),
    _m("imp-all-rear", "        rear = t[2] != 0 || t[3] != 0;",
       "        rear = t[2] != 0 && t[3] != 0;"),
    _m("imp-all-rear-3", "        rear = t[2] != 0 || t[3] != 0;",
       "        rear = t[2] != 0 || t[1] != 0;"),
    _m("imp-side0-front", "        front = t[1];\n        rear = t[3];",
       "        front = t[0];\n        rear = t[3];"),
    _m("imp-side0-rear", "        front = t[1];\n        rear = t[3];",
       "        front = t[1];\n        rear = t[2];"),
    _m("imp-side0-bool", "        front = t[1];\n        rear = t[3];",
       "        front = t[1] != 0;\n        rear = t[3];"),
    _m("imp-side1-front", "        front = t[0];\n        rear = t[2];",
       "        front = t[1];\n        rear = t[2];"),
    _m("imp-side1-rear", "        front = t[0];\n        rear = t[2];",
       "        front = t[0];\n        rear = t[3];"),
    _m("imp-side1-cond", "    } else if (side == 1) {\n        front = t[0];",
       "    } else if (side >= 1) {\n        front = t[0];"),
    _m("imp-side0-cond", "    } else if (side == 0) {\n        front = t[1];",
       "    } else if (side <= 0) {\n        front = t[1];"),
    _m("imp-front-touching", "    if ((front != 0 && s->FrontTireTouching == 0)",
       "    if ((front != 0 && s->FrontTireTouching != 0)"),
    _m("imp-rear-touching",
       "        || (rear != 0 && s->RearTireTouching == 0)) {",
       "        || (rear != 0 && s->RearTireTouching != 0)) {"),
    _m("imp-no-rear", "        || (rear != 0 && s->RearTireTouching == 0)) {",
       "        ) {"),
    _m("imp-velz-abs", "float impact = (fabsf(c->State.Velocity.z) * 0.3f",
       "float impact = (c->State.Velocity.z * 0.3f"),
    _m("imp-velz-k", "* 0.3f      // gp-27524", "* 0.35f      // gp-27524"),
    _m("imp-ang-k", "+ ee_sqrt(w->x * w->x + w->y * w->y) * 0.8f)",
       "+ ee_sqrt(w->x * w->x + w->y * w->y) * 0.85f)"),
    _m("imp-ang-y", "+ ee_sqrt(w->x * w->x + w->y * w->y) * 0.8f)",
       "+ ee_sqrt(w->x * w->x + w->x * w->y) * 0.8f)"),
    _m("imp-half", "                       * 0.5f;                                  // gp-27520",
       "                       * 0.6f;                                  // gp-27520"),
    _m("imp-flop-cap", "float flop = (1.0f < impact ? 1.0f : impact) * s->Sound.Volume;",
       "float flop = (0.9f < impact ? 1.0f : impact) * s->Sound.Volume;"),
    _m("imp-flop-vol", "float flop = (1.0f < impact ? 1.0f : impact) * s->Sound.Volume;",
       "float flop = (1.0f < impact ? 1.0f : impact);"),
    _m("imp-flop-se", "        if (SoundEnabled && CarSoundEnabled && RoadNoiseEnabled) {\n"
       "            bsample_play(&s->TireFlop",
       "        if (CarSoundEnabled && RoadNoiseEnabled) {\n"
       "            bsample_play(&s->TireFlop"),
    _m("imp-flop-cse", "        if (SoundEnabled && CarSoundEnabled && RoadNoiseEnabled) {\n"
       "            bsample_play(&s->TireFlop",
       "        if (SoundEnabled && RoadNoiseEnabled) {\n"
       "            bsample_play(&s->TireFlop"),
    _m("imp-flop-rne", "        if (SoundEnabled && CarSoundEnabled && RoadNoiseEnabled) {\n"
       "            bsample_play(&s->TireFlop",
       "        if (SoundEnabled && CarSoundEnabled) {\n"
       "            bsample_play(&s->TireFlop"),
    _m("imp-flop-az", "            bsample_set_azimuth(&s->TireFlop, s->Sound.Azimuth);\n", ""),
    _m("imp-flop-pitch", "            bsample_play(&s->TireFlop, flop, 0.0f, 0.0f);",
       "            bsample_play(&s->TireFlop, flop, 0.0f, 0.1f);"),
    _m("imp-bo-thresh", "        if (0.9f < impact && SoundEnabled",
       "        if (0.8f < impact && SoundEnabled"),
    _m("imp-bo-le", "        if (0.9f < impact && SoundEnabled",
       "        if (0.9f <= impact && SoundEnabled"),
    _m("imp-bo-se", "0.9f < impact && SoundEnabled", "0.9f < impact"),
    _m("imp-bo-cse", "SoundEnabled && CarSoundEnabled          // gp-27516",
       "SoundEnabled          // gp-27516"),
    _m("imp-bo-rne", "            && RoadNoiseEnabled) {\n            float pitch",
       "            ) {\n            float pitch"),
    _m("imp-bo-range", "sound_random_float(sound_get(), 0.7f)",
       "sound_random_float(sound_get(), 0.75f)"),
    _m("imp-bo-bias", "+ -0.4f;", "+ -0.45f;"),
    _m("imp-bo-cat", "            if (s->BottomOut.category == 0xffffffffu)",
       "            if (s->BottomOut.category != 0xffffffffu)"),
    _m("imp-bo-jb-cat", "jb_saved_volume(sound_get()->jb, 0)",
       "jb_saved_volume(sound_get()->jb, 1)"),
    _m("imp-bo-jb-none", "                impact *= jb_saved_volume(sound_get()->jb, 0);",
       "                jb_saved_volume(sound_get()->jb, 0);"),
    _m("imp-bo-vol", "bsample_play(&s->BottomOut, impact * s->Sound.Volume * 0.8f,",
       "bsample_play(&s->BottomOut, impact * 0.8f,"),
    _m("imp-bo-k", "bsample_play(&s->BottomOut, impact * s->Sound.Volume * 0.8f,",
       "bsample_play(&s->BottomOut, impact * s->Sound.Volume * 0.85f,"),
    _m("imp-bo-pitch", "                         0.0f, pitch);                                // gp-27504",
       "                         0.0f, pitch + 1.0f);                                // gp-27504"),
    _m("imp-bo-az", "            bsample_set_azimuth(&s->BottomOut, s->Sound.Azimuth);\n", ""),
    _m("imp-store-rear", "    s->RearTireTouching = (uint16_t)rear;",
       "    s->RearTireTouching = (uint16_t)front;"),
    _m("imp-store-front", "    s->FrontTireTouching = (uint16_t)front;",
       "    s->FrontTireTouching = (uint16_t)rear;"),
    _m("imp-store-bool", "    s->FrontTireTouching = (uint16_t)front;",
       "    s->FrontTireTouching = (uint16_t)(front != 0);"),

    # TerrainOneShot.
    _m("tos-init-null", "    if (sample == NULL) {\n        t->bFoundSample = 0;",
       "    if (sample == NULL) {\n        t->bFoundSample = 1;"),
    _m("tos-init-found", "    t->bFoundSample = 1;\n    t->pTimeDelay",
       "    t->bFoundSample = 2;\n    t->pTimeDelay"),
    _m("tos-init-delay", "    t->pTimeDelay = pTimeDelay;", "    t->pTimeDelay = NULL;"),
    _m("tos-init-side", "    t->Side = side;", "    t->Side = 0;"),
    _m("tos-init-on", "    t->bOnTerrainType = 0;\n    bsample_initialize_copy",
       "    t->bOnTerrainType = 1;\n    bsample_initialize_copy"),
    _m("tos-init-cat", "    bsample_set_category(&t->TerrainSample, 1);",
       "    bsample_set_category(&t->TerrainSample, 0);"),
    _m("tos-dtor-flags", "    if (flags & 1)\n        bFree(t);",
       "    if (flags & 2)\n        bFree(t);"),
    _m("tos-mute-found", "    if (t->bFoundSample)\n        bsample_pause",
       "    if (1)\n        bsample_pause"),
    _m("tos-mute-on", "        bsample_pause(&t->TerrainSample, on != 0);",
       "        bsample_pause(&t->TerrainSample, on == 1);"),
    _m("tos-found", "    if (!t->bFoundSample)\n        return;\n    if (c->State",
       "    if (0)\n        return;\n    if (c->State"),
    _m("tos-side-a", "CrossedWheelTerrain[t->Side == 0 ? 0 : 3] != terrain",
       "CrossedWheelTerrain[t->Side == 0 ? 0 : 2] != terrain"),
    _m("tos-side-a0", "CrossedWheelTerrain[t->Side == 0 ? 0 : 3] != terrain",
       "CrossedWheelTerrain[t->Side == 0 ? 1 : 3] != terrain"),
    _m("tos-side-b", "CrossedWheelTerrain[t->Side == 0 ? 1 : 2] != terrain",
       "CrossedWheelTerrain[t->Side == 0 ? 1 : 3] != terrain"),
    _m("tos-side-cond", "CrossedWheelTerrain[t->Side == 0 ? 0 : 3]",
       "CrossedWheelTerrain[t->Side == 1 ? 0 : 3]"),
    _m("tos-and", "!= terrain\n        && c->State.CrossedWheelTerrain",
       "!= terrain\n        || c->State.CrossedWheelTerrain"),
    _m("tos-off-reset", "        t->bOnTerrainType = 0;\n        return;",
       "        return;"),
    _m("tos-delay-gt", "delayed = t->pTimeDelay != NULL && 0.0f < *t->pTimeDelay;",
       "delayed = t->pTimeDelay != NULL && 0.0f <= *t->pTimeDelay;"),
    _m("tos-on", "    if (t->bOnTerrainType || delayed)", "    if (delayed)"),
    _m("tos-delayed", "    if (t->bOnTerrainType || delayed)",
       "    if (t->bOnTerrainType)"),
    _m("tos-play-vol", "bsample_play(&t->TerrainSample, volume, (float)azimuth, pitch - 1.0f);",
       "bsample_play(&t->TerrainSample, 1.0f, (float)azimuth, pitch - 1.0f);"),
    _m("tos-play-pan", "bsample_play(&t->TerrainSample, volume, (float)azimuth, pitch - 1.0f);",
       "bsample_play(&t->TerrainSample, volume, 0.0f, pitch - 1.0f);"),
    _m("tos-play-pitch", "bsample_play(&t->TerrainSample, volume, (float)azimuth, pitch - 1.0f);",
       "bsample_play(&t->TerrainSample, volume, (float)azimuth, pitch);"),
    _m("tos-set-on", "    t->bOnTerrainType = 1;\n    if (t->pTimeDelay",
       "    t->bOnTerrainType = 0;\n    if (t->pTimeDelay"),
    _m("tos-delay-set", "        *t->pTimeDelay = 0.3f;", "        *t->pTimeDelay = 0.25f;"),

    # PlayerTireSound's constructor and destructor.
    _m("pc-side", "    s->Side = side;\n    s->Mode = 0;",
       "    s->Side = 0;\n    s->Mode = 0;"),
    _m("pc-mode", "    s->Mode = 0;", "    s->Mode = 1;"),
    _m("pc-vt", "    s->Base.Sound._vtable = PLAYERTIRESOUND_VTABLE;\n"
       "    bsample_construct(&s->MetalBump",
       "    s->Base.Sound._vtable = OPPONENTTIRESOUND_VTABLE;\n"
       "    bsample_construct(&s->MetalBump"),
    _m("pc-mb-on", "    s->MetalBump.bOnTerrainType = 0;",
       "    s->MetalBump.bOnTerrainType = 1;"),
    _m("pc-mb-delay", "    s->MetalBump.pTimeDelay = NULL;",
       "    s->MetalBump.pTimeDelay = &PlayerTireSoundOneShotTimeDelay;"),
    _m("pc-ph-on", "    s->PotHole.bOnTerrainType = 0;",
       "    s->PotHole.bOnTerrainType = 1;"),
    _m("pc-ph-delay", "    s->PotHole.pTimeDelay = NULL;",
       "    s->PotHole.pTimeDelay = &PlayerTireSoundOneShotTimeDelay;"),
    _m("pc-ctor-order", "    bsample_construct(&s->LeavesNoise, 0);\n"
       "    bsample_construct(&s->RoadNoise, 0);",
       "    bsample_construct(&s->RoadNoise, 0);\n"
       "    bsample_construct(&s->LeavesNoise, 0);"),
    _m("pc-rn-name", "sound_get_in_game_sample(m, \"RoadNoise\")",
       "sound_get_in_game_sample(m, \"RoadNoize\")"),
    _m("pc-dn-name", "sound_get_in_game_sample(m, \"GravelNoise\")",
       "sound_get_in_game_sample(m, \"RoadNoise\")"),
    _m("pc-rk-name", "sound_get_in_game_sample(m, \"LongitudinalSkid\"));\n"
       "    bsample_set_category(&s->RoadSkid, 1);",
       "sound_get_in_game_sample(m, \"GravelSkid\"));\n"
       "    bsample_set_category(&s->RoadSkid, 1);"),
    _m("pc-ds-name", "sound_get_in_game_sample(m, \"GravelSkid\"));\n"
       "    bsample_set_category(&s->DirtSquall, 1);",
       "sound_get_in_game_sample(m, \"SquallSkid\"));\n"
       "    bsample_set_category(&s->DirtSquall, 1);"),
    _m("pc-bu-name", "sound_get_in_game_sample(m, \"TireFlat\")",
       "sound_get_in_game_sample(m, \"TireFlop\")"),
    _m("pc-rn-cat", "    bsample_set_category(&s->RoadNoise, 1);",
       "    bsample_set_category(&s->RoadNoise, 0);"),
    _m("pc-dn-cat", "    bsample_set_category(&s->DirtNoise, 1);",
       "    bsample_set_category(&s->DirtNoise, 0);"),
    _m("pc-rk-cat", "    bsample_set_category(&s->RoadSkid, 1);",
       "    bsample_set_category(&s->RoadSkid, 0);"),
    _m("pc-dk-cat", "    bsample_set_category(&s->DirtSkid, 1);",
       "    bsample_set_category(&s->DirtSkid, 0);"),
    _m("pc-sq-cat", "    bsample_set_category(&s->Squall, 1);",
       "    bsample_set_category(&s->Squall, 0);"),
    _m("pc-ds-cat", "    bsample_set_category(&s->DirtSquall, 1);",
       "    bsample_set_category(&s->DirtSquall, 0);"),
    _m("pc-bu-cat", "    bsample_set_category(&s->Busted, 1);",
       "    bsample_set_category(&s->Busted, 0);"),
    _m("pc-bs-cat", "    bsample_set_category(&s->BustedScrape, 1);",
       "    bsample_set_category(&s->BustedScrape, 0);"),
    _m("pc-bp-cat", "    bsample_set_category(&s->BurnOutPeel, 1);",
       "    bsample_set_category(&s->BurnOutPeel, 0);"),
    _m("pc-lv-cat", "bsample_set_category(&s->LeavesNoise, 1);",
       "bsample_set_category(&s->LeavesNoise, 0);"),
    _m("pc-bo-cat", "bsample_set_category(&s->Base.BottomOut, 0xffffffffu);",
       "bsample_set_category(&s->Base.BottomOut, 1);"),
    _m("pc-bo-cat-none", "    bsample_set_category(&s->Base.BottomOut, 0xffffffffu);\n",
       ""),
    _m("pc-region-name", "bsound_region(bsound_get(), CurrentTrackInfo->SoundRegion);",
       "bsound_region(bsound_get(), \"T0\");"),
    _m("pc-region-null", "    if (r != NULL) {\n        BSample *leaves",
       "    if (1) {\n        BSample *leaves"),
    _m("pc-leaves-name", "bregion_sample(r, \"Leaves\")", "bregion_sample(r, \"Leafs\")"),
    _m("pc-leaves-found", "            s->FoundLeavesSample = 1;",
       "            s->FoundLeavesSample = 2;"),
    _m("pc-leaves-none", "            s->FoundLeavesSample = 0;\n        }",
       "            s->FoundLeavesSample = 1;\n        }"),
    _m("pc-mb-name", "sound_get_in_game_sample(m, \"MetalBump\")",
       "sound_get_in_game_sample(m, \"MetalBomp\")"),
    _m("pc-mb-delay-arg", "                        &PlayerTireSoundOneShotTimeDelay, s->Side);\n"
       "    terrainoneshot_init(&s->PotHole",
       "                        NULL, s->Side);\n"
       "    terrainoneshot_init(&s->PotHole"),
    _m("pc-ph-name", "terrainoneshot_init(&s->PotHole, sound_get_in_game_sample(m, \"TireFlop\"),",
       "terrainoneshot_init(&s->PotHole, sound_get_in_game_sample(m, \"TireFlat\"),"),
    _m("pc-ph-side", "&PlayerTireSoundOneShotTimeDelay, s->Side);\n    if (SoundEnabled",
       "&PlayerTireSoundOneShotTimeDelay, 0);\n    if (SoundEnabled"),
    _m("pc-rn-se", "    if (SoundEnabled && CarSoundEnabled && RoadNoiseEnabled)\n"
       "        bsample_play(&s->RoadNoise, 0.0f, 0.0f, 0.0f);",
       "    if (CarSoundEnabled && RoadNoiseEnabled)\n"
       "        bsample_play(&s->RoadNoise, 0.0f, 0.0f, 0.0f);"),
    _m("pc-rn-cse", "    if (SoundEnabled && CarSoundEnabled && RoadNoiseEnabled)\n"
       "        bsample_play(&s->RoadNoise, 0.0f, 0.0f, 0.0f);",
       "    if (SoundEnabled && RoadNoiseEnabled)\n"
       "        bsample_play(&s->RoadNoise, 0.0f, 0.0f, 0.0f);"),
    _m("pc-rn-rne", "    if (SoundEnabled && CarSoundEnabled && RoadNoiseEnabled)\n"
       "        bsample_play(&s->RoadNoise, 0.0f, 0.0f, 0.0f);",
       "    if (SoundEnabled && CarSoundEnabled)\n"
       "        bsample_play(&s->RoadNoise, 0.0f, 0.0f, 0.0f);"),
    _m("pc-rn-vol", "bsample_play(&s->RoadNoise, 0.0f, 0.0f, 0.0f);",
       "bsample_play(&s->RoadNoise, 1.0f, 0.0f, 0.0f);"),
    _m("pc-prev", "    s->PrevShouldMakeRoadNoise = 1;",
       "    s->PrevShouldMakeRoadNoise = 0;"),
    _m("pc-reset", "    playertiresound_reset_thumper_time(s);\n"
       "    s->PlayThumperSounds = 0;", "    s->PlayThumperSounds = 0;"),
    _m("pc-pts", "    s->PlayThumperSounds = 0;", "    s->PlayThumperSounds = 1;"),
    _m("pc-csv", "    s->CurrSquallVolume = 0.0f;", "    s->CurrSquallVolume = 0.5f;"),
    _m("pc-lrp", "    s->LockedRearPitch = -1.0f;\n    s->RoadNoiseScale",
       "    s->LockedRearPitch = 0.0f;\n    s->RoadNoiseScale"),
    _m("pc-rns", "    s->RoadNoiseScale = 1.0f;", "    s->RoadNoiseScale = 0.5f;"),
    _m("pc-csp", "    s->CurrSquallPitch = 1.0f;", "    s->CurrSquallPitch = 0.5f;"),
    _m("pc-activate", "    sound3d_activate(&s->Base.Sound, 1);\n}\n\n"
       "void playertiresound_destroy",
       "    sound3d_activate(&s->Base.Sound, 0);\n}\n\n"
       "void playertiresound_destroy"),
    _m("pd-stop-rn", "    bsample_stop(&s->RoadNoise);\n    bsample_stop(&s->DirtNoise);",
       "    bsample_stop(&s->DirtNoise);"),
    _m("pd-stop-lv", "    bsample_stop(&s->LeavesNoise);\n    bsound_flush",
       "    bsound_flush"),
    _m("pd-flush", "    bsound_flush(bsound_get(), 1);", "    bsound_flush(bsound_get(), 0);"),
    _m("pd-flush-none", "    bsound_flush(bsound_get(), 1);\n", ""),
    _m("pd-order", "    bsample_destruct(&s->BustedScrape);\n"
       "    bsample_destruct(&s->Busted);",
       "    bsample_destruct(&s->Busted);\n"
       "    bsample_destruct(&s->BustedScrape);"),
    _m("pd-tos-order", "    terrainoneshot_destroy(&s->PotHole, 2);\n"
       "    terrainoneshot_destroy(&s->MetalBump, 2);",
       "    terrainoneshot_destroy(&s->MetalBump, 2);\n"
       "    terrainoneshot_destroy(&s->PotHole, 2);"),
    _m("pd-tos-flags", "terrainoneshot_destroy(&s->PotHole, 2);",
       "terrainoneshot_destroy(&s->PotHole, 3);"),
    _m("pd-base-flags", "    basetiresound_destroy(&s->Base, flags);\n}\n\n"
       "void playertiresound_deactivate_sound",
       "    basetiresound_destroy(&s->Base, 0);\n}\n\n"
       "void playertiresound_deactivate_sound"),
    _m("ssp", "    bsample_set_pitch(smp, pitch - 1.0f);",
       "    bsample_set_pitch(smp, pitch);"),

    # The Calc functions.
    _m("sqvp-down", "        float down = cur - 0.15f;", "        float down = cur - 0.1f;"),
    _m("sqvp-down-cmp", "        if (v < down)\n            v = down;",
       "        if (v > down)\n            v = down;"),
    _m("sqvp-up", "        float up = cur + 0.075f;", "        float up = cur + 0.08f;"),
    _m("sqvp-up-cmp", "        if (up < v)\n            v = up;",
       "        if (up > v)\n            v = up;"),
    _m("sqvp-store1", "        s->CurrSquallVolume = v;\n        *volume = v;\n    } else if",
       "        *volume = v;\n    } else if"),
    _m("sqvp-store2", "        s->CurrSquallVolume = v;\n        *volume = v;\n    } else {",
       "        *volume = v;\n    } else {"),
    _m("sqvp-else", "    } else {\n        *volume = cur;\n    }",
       "    } else {\n        *volume = 0.0f;\n    }"),
    _m("sqvp-pitch", "    *pitch = s->CurrSquallPitch;", "    *pitch = 1.0f;"),
    _m("sqvp-pitch-store",
       "    s->CurrSquallPitch = playertiresound_calc_tire_squall_pitch(s);",
       "    playertiresound_calc_tire_squall_pitch(s);"),
    _m("skvp-pitch-init", "    *pitch = 1.0f;\n    *volume = 0.0f;", "    *volume = 0.0f;"),
    _m("skvp-vol-init", "    *pitch = 1.0f;\n    *volume = 0.0f;", "    *pitch = 1.0f;"),
    _m("skvp-rear", "        i0 = 2;\n        i1 = 3;", "        i0 = 2;\n        i1 = 2;"),
    _m("skvp-rear-0", "        i0 = 2;\n        i1 = 3;", "        i0 = 3;\n        i1 = 3;"),
    _m("skvp-side", "    if (s->Side == 1) {\n        i0 = 2;",
       "    if (s->Side != 0) {\n        i0 = 2;"),
    _m("skvp-front", "    int32_t i0 = 0, i1 = 1;", "    int32_t i0 = 0, i1 = 0;"),
    _m("skvp-touch-a", "    if (c->State.WheelTouchingGround[i0])\n        a = slip_length(c, i0);",
       "    a = slip_length(c, i0);"),
    _m("skvp-touch-b", "    if (c->State.WheelTouchingGround[i1])\n        b = slip_length(c, i1);",
       "    b = slip_length(c, i1);"),
    _m("skvp-thresh-a", "    if (a < 0.25f)\n        a = 0.0f;",
       "    if (a < 0.2f)\n        a = 0.0f;"),
    _m("skvp-thresh-a-le", "    if (a < 0.25f)\n        a = 0.0f;",
       "    if (a <= 0.25f)\n        a = 0.0f;"),
    _m("skvp-thresh-b", "    if (b < 0.25f)\n        b = 0.0f;",
       "    if (b < 0.3f)\n        b = 0.0f;"),
    _m("skvp-b-reset", "    b = 0.0f;\n    if (c->State.WheelTouchingGround[i1])",
       "    b = a;\n    if (c->State.WheelTouchingGround[i1])"),
    _m("skvp-mean", "    t = (float)((double)(a + b) * 0.5);",
       "    t = (float)((double)(a + b) * 0.6);"),
    _m("skvp-min", "        if (t < 0.01f) {", "        if (t < 0.2f) {"),
    _m("skvp-lock-reset", "            s->LockedRearPitch = -1.0f;\n            return;",
       "            return;"),
    _m("skvp-rear-vol", "        *volume = t * 0.3f;", "        *volume = t * 0.35f;"),
    _m("skvp-lock-cmp", "        if (s->LockedRearPitch == -1.0f) {",
       "        if (s->LockedRearPitch != -1.0f) {"),
    _m("skvp-rear-k", "*pitch = *pitch * 0.06f * t;", "*pitch = *pitch * 0.065f * t;"),
    _m("skvp-rear-lo", "*pitch = clamp_f(*pitch, 1.0f, 1.2f);",
       "*pitch = clamp_f(*pitch, 0.9f, 1.2f);"),
    _m("skvp-rear-hi", "*pitch = clamp_f(*pitch, 1.0f, 1.2f);",
       "*pitch = clamp_f(*pitch, 1.0f, 1.25f);"),
    _m("skvp-lock-store", "            s->LockedRearPitch = *pitch;\n", ""),
    _m("skvp-locked", "            *pitch = s->LockedRearPitch;", "            *pitch = 1.0f;"),
    _m("skvp-front-vol", "        *volume = t * 0.4f;", "        *volume = t * 0.45f;"),
    _m("skvp-front-k", "*pitch = *pitch * 0.07f * t;", "*pitch = *pitch * 0.075f * t;"),
    _m("skvp-front-hi", "*pitch = clamp_f(*pitch, 1.0f, 1.25f);",
       "*pitch = clamp_f(*pitch, 1.0f, 1.3f);"),
    _m("nv-i0", "            a = fabsf(c->State.WheelAngularVelocity[i0]) * 0.0095f;",
       "            a = fabsf(c->State.WheelAngularVelocity[i1]) * 0.0095f;"),
    _m("nv-k", "            a = fabsf(c->State.WheelAngularVelocity[i0]) * 0.0095f;",
       "            a = fabsf(c->State.WheelAngularVelocity[i0]) * 0.01f;"),
    _m("nv-abs", "            a = fabsf(c->State.WheelAngularVelocity[i0]) * 0.0095f;",
       "            a = c->State.WheelAngularVelocity[i0] * 0.0095f;"),
    _m("nv-kb", "            b = fabsf(c->State.WheelAngularVelocity[i1]) * 0.0095f;",
       "            b = fabsf(c->State.WheelAngularVelocity[i1]) * 0.009f;"),
    _m("nv-touch", "        if (c->State.WheelTouchingGround[i0])\n"
       "            a = fabsf(c->State.WheelAngularVelocity[i0]) * 0.0095f;",
       "        if (1)\n"
       "            a = fabsf(c->State.WheelAngularVelocity[i0]) * 0.0095f;"),
    _m("nv-i0-side0", "        int32_t i0 = s->Side == 0 ? 1 : 0;\n"
       "        int32_t i1 = s->Side == 0 ? 2 : 3;\n\n"
       "        if (c->State.WheelTouchingGround[i0])\n"
       "            a = fabsf(c->State.WheelAngularVelocity[i0]) * 0.0095f;",
       "        int32_t i0 = s->Side == 0 ? 0 : 0;\n"
       "        int32_t i1 = s->Side == 0 ? 2 : 3;\n\n"
       "        if (c->State.WheelTouchingGround[i0])\n"
       "            a = fabsf(c->State.WheelAngularVelocity[i0]) * 0.0095f;"),
    _m("nv-i1-side1", "        int32_t i0 = s->Side == 0 ? 1 : 0;\n"
       "        int32_t i1 = s->Side == 0 ? 2 : 3;\n\n"
       "        if (c->State.WheelTouchingGround[i0])\n"
       "            a = fabsf(c->State.WheelAngularVelocity[i0]) * 0.0095f;",
       "        int32_t i0 = s->Side == 0 ? 1 : 0;\n"
       "        int32_t i1 = s->Side == 0 ? 2 : 2;\n\n"
       "        if (c->State.WheelTouchingGround[i0])\n"
       "            a = fabsf(c->State.WheelAngularVelocity[i0]) * 0.0095f;"),
    _m("nv-side-cond", "    if (s->Side == 0 || s->Side == 1) {\n"
       "        int32_t i0 = s->Side == 0 ? 1 : 0;\n"
       "        int32_t i1 = s->Side == 0 ? 2 : 3;\n\n"
       "        if (c->State.WheelTouchingGround[i0])\n"
       "            a = fabsf(c->State.WheelAngularVelocity[i0]) * 0.0095f;",
       "    if (1) {\n"
       "        int32_t i0 = s->Side == 0 ? 1 : 0;\n"
       "        int32_t i1 = s->Side == 0 ? 2 : 3;\n\n"
       "        if (c->State.WheelTouchingGround[i0])\n"
       "            a = fabsf(c->State.WheelAngularVelocity[i0]) * 0.0095f;"),
    _m("nv-mean", "    v = (a + b) * 0.5f;\n    if (1.0f < v)\n        v = 1.0f;\n"
       "    return v;\n}\n\nfloat playertiresound_calc_tire_noise_pitch",
       "    v = (a + b) * 0.6f;\n    if (1.0f < v)\n        v = 1.0f;\n"
       "    return v;\n}\n\nfloat playertiresound_calc_tire_noise_pitch"),
    _m("nv-cap", "    v = (a + b) * 0.5f;\n    if (1.0f < v)\n        v = 1.0f;\n"
       "    return v;\n}\n\nfloat playertiresound_calc_tire_noise_pitch",
       "    v = (a + b) * 0.5f;\n    if (1.2f < v)\n        v = 1.0f;\n"
       "    return v;\n}\n\nfloat playertiresound_calc_tire_noise_pitch"),
    _m("np-max", "    return TireNoisePitchScale * (b < a ? a : b)",
       "    return TireNoisePitchScale * (b < a ? b : a)"),
    _m("np-bias", "           + (s->Side == 0 ? 0.15f : 0.0f);             // gp-27452",
       "           + (s->Side == 0 ? 0.1f : 0.0f);             // gp-27452"),
    _m("np-bias-side", "           + (s->Side == 0 ? 0.15f : 0.0f);             // gp-27452",
       "           + (s->Side == 1 ? 0.15f : 0.0f);             // gp-27452"),
    _m("np-abs", "            a = fabsf(c->State.WheelAngularVelocity[i0]);",
       "            a = c->State.WheelAngularVelocity[i0];"),
    _m("np-i1", "            b = fabsf(c->State.WheelAngularVelocity[i1]);",
       "            b = fabsf(c->State.WheelAngularVelocity[i0]);"),
    _m("np-touch", "        if (c->State.WheelTouchingGround[i1])\n"
       "            b = fabsf(c->State.WheelAngularVelocity[i1]);",
       "        if (1)\n"
       "            b = fabsf(c->State.WheelAngularVelocity[i1]);"),
    _m("sv-speed", "    if (fabsf(c->State.VelocityMagnitude) < 11.0f)",
       "    if (fabsf(c->State.VelocityMagnitude) < 10.0f)"),
    _m("sv-speed-le", "    if (fabsf(c->State.VelocityMagnitude) < 11.0f)",
       "    if (fabsf(c->State.VelocityMagnitude) <= 11.0f)"),
    _m("sv-speed-abs", "    if (fabsf(c->State.VelocityMagnitude) < 11.0f)",
       "    if (c->State.VelocityMagnitude < 11.0f)"),
    _m("sv-side0", "    if (s->Side == 0) {\n        i1 = 3;",
       "    if (s->Side == 0) {\n        i1 = 2;"),
    _m("sv-side1", "        i0 = 1;\n        i1 = 2;", "        i0 = 1;\n        i1 = 3;"),
    _m("sv-side1-i0", "        i0 = 1;\n        i1 = 2;", "        i0 = 2;\n        i1 = 2;"),
    _m("sv-side-other", "    int32_t i0 = 0, i1 = 0;", "    int32_t i0 = 0, i1 = 1;"),
    _m("sv-abs", "        a = fabsf(c->State.WheelTractionUsage[i0]);",
       "        a = c->State.WheelTractionUsage[i0];"),
    _m("sv-touch-b", "    if (c->State.WheelTouchingGround[i1])\n"
       "        b = fabsf(c->State.WheelTractionUsage[i1]);",
       "    if (1)\n        b = fabsf(c->State.WheelTractionUsage[i1]);"),
    _m("sv-thresh", "    if (0.7f < m)", "    if (0.7f <= m)"),
    _m("sv-thresh-k", "    if (0.7f < m)", "    if (0.75f < m)"),
    _m("sv-k", "        v = m * 1.975f;", "        v = m * 2.0f;"),
    _m("sv-cap", "    if (1.0f < v)\n        v = 1.0f;\n    return v;\n}\n\n// Retail reads",
       "    if (1.1f < v)\n        v = 1.0f;\n    return v;\n}\n\n// Retail reads"),
    _m("sp-k", "    return s->pCar->State.VelocityMagnitude * 0.01015f  // gp-27440",
       "    return s->pCar->State.VelocityMagnitude * 0.0102f  // gp-27440"),
    _m("sp-bias", "           + (s->Side == 0 ? 0.15f : 0.0f);             // gp-27436",
       "           + (s->Side == 0 ? 0.2f : 0.0f);             // gp-27436"),
    _m("sp-bias-side", "           + (s->Side == 0 ? 0.15f : 0.0f);             // gp-27436",
       "           + (s->Side != 0 ? 0.15f : 0.0f);             // gp-27436"),

    # PlayerTireSound's Mute.
    _m("pm-base", "    basetiresound_mute(&s->Base, on);\n    bsample_pause(&s->RoadNoise",
       "    bsample_pause(&s->RoadNoise"),
    _m("pm-rn", "    bsample_pause(&s->RoadNoise, on != 0);",
       "    bsample_pause(&s->RoadNoise, on == 0);"),
    _m("pm-lv", "    bsample_pause(&s->LeavesNoise, on != 0);\n", ""),
    _m("pm-bs", "    bsample_pause(&s->BustedScrape, on != 0);",
       "    bsample_pause(&s->BustedScrape, 0);"),
    _m("pm-mb", "    terrainoneshot_mute(&s->MetalBump, on);",
       "    terrainoneshot_mute(&s->PotHole, on);"),
    _m("pm-ph-on", "    terrainoneshot_mute(&s->PotHole, on);",
       "    terrainoneshot_mute(&s->PotHole, 1);"),

    # PlayerTireSound's Update.
    _m("u-active", "    if (!s->Base.Sound.Activated)\n        return;\n    c = s->pCar;",
       "    c = s->pCar;"),
    _m("u-t0", "    t0 = terrain_info(c, s->Side != 1);",
       "    t0 = terrain_info(c, s->Side == 0);"),
    _m("u-t1", "    t1 = terrain_info(c, s->Side == 1 ? 3 : 2);",
       "    t1 = terrain_info(c, s->Side == 1 ? 2 : 3);"),
    _m("u-vol", "    s->Base.Sound.Volume = volume;\n    s->Base.Sound.Pitch = pitch;",
       "    s->Base.Sound.Pitch = pitch;"),
    _m("u-pitch", "    s->Base.Sound.Pitch = pitch;\n    s->Base.Sound.Azimuth = azimuth;\n"
       "    onRoad", "    s->Base.Sound.Azimuth = azimuth;\n    onRoad"),
    _m("u-az", "    s->Base.Sound.Azimuth = azimuth;\n    onRoad", "    onRoad"),
    _m("u-onroad-and", "    onRoad = t0->ShouldTireMakeRoadSound != 0\n             && t1->",
       "    onRoad = t0->ShouldTireMakeRoadSound != 0\n             || t1->"),
    _m("u-puddle0", "    if (t0->Type == TERRAIN_TYPE_PUDDLE || t1->Type == TERRAIN_TYPE_PUDDLE)",
       "    if (t1->Type == TERRAIN_TYPE_PUDDLE)"),
    _m("u-puddle1", "    if (t0->Type == TERRAIN_TYPE_PUDDLE || t1->Type == TERRAIN_TYPE_PUDDLE)",
       "    if (t0->Type == TERRAIN_TYPE_PUDDLE)"),
    _m("u-puddle-keep", "        onRoad = s->PrevShouldMakeRoadNoise;\n    else",
       "        onRoad = 1;\n    else"),
    _m("u-prev-store", "        s->PrevShouldMakeRoadNoise = onRoad;",
       "        (void)onRoad;"),
    _m("u-noise-vol", "    noise *= volume;", "    noise *= 1.0f;"),
    _m("u-leaves-args", "    playertiresound_update_leaves(s, noise, azimuth, pitch);",
       "    playertiresound_update_leaves(s, volume, azimuth, pitch);"),
    _m("u-delay-cmp", "    if (0.0f < PlayerTireSoundOneShotTimeDelay)\n"
       "        PlayerTireSoundOneShotTimeDelay -= WorldTimeElapsed;",
       "    if (1)\n        PlayerTireSoundOneShotTimeDelay -= WorldTimeElapsed;"),
    _m("u-delay-sub", "        PlayerTireSoundOneShotTimeDelay -= WorldTimeElapsed;",
       "        PlayerTireSoundOneShotTimeDelay -= WorldTimeElapsed * 0.5f;"),
    _m("u-mb-terr", "TERRAIN_TYPE_METAL_GRATE,", "TERRAIN_TYPE_POTHOLE,"),
    _m("u-mb-vol", "                          volume * 1.3f, azimuth, pitch);",
       "                          volume * 1.2f, azimuth, pitch);"),
    _m("u-ph-terr", "terrainoneshot_update(&s->PotHole, s->pCar, TERRAIN_TYPE_POTHOLE,",
       "terrainoneshot_update(&s->PotHole, s->pCar, TERRAIN_TYPE_METAL_GRATE,"),
    _m("u-ph-vol", "                          volume * 1.5f, azimuth,",
       "                          volume * 1.4f, azimuth,"),
    _m("u-ph-pitch", "                          pitch * 0.8f);",
       "                          pitch * 0.9f);"),
    _m("u-thump-cobble", "    thump = t0->Type == TERRAIN_TYPE_COBBLESTONE",
       "    thump = t1->Type == TERRAIN_TYPE_COBBLESTONE"),
    _m("u-thump-board", "            || t1->Type == TERRAIN_TYPE_BOARDWALK;",
       "            || t0->Type == TERRAIN_TYPE_BOARDWALK;"),
    _m("u-thump-blown", "    if (!(blown_tires(s->pCar) < 1))",
       "    if (blown_tires(s->pCar) > 1)"),
    _m("u-pts-store", "    s->PlayThumperSounds = thump;\n", ""),
    _m("u-thump-call", "    if (thump)\n        playertiresound_update_thumper_tires(s);\n"
       "    else\n        playertiresound_reset_thumper_time(s);",
       "    if (thump)\n        playertiresound_update_thumper_tires(s);"),
    _m("u-thump-always", "    if (thump)\n        playertiresound_update_thumper_tires(s);\n"
       "    else\n        playertiresound_reset_thumper_time(s);",
       "    playertiresound_update_thumper_tires(s);"),
    _m("u-impact-side", "    basetiresound_update_tire_impact(&s->Base, s->pCar, s->Side);",
       "    basetiresound_update_tire_impact(&s->Base, s->pCar, -1);"),
    _m("u-bias", "    bias = s->Side == 0 ? 0.15f : 0.0f;",
       "    bias = s->Side == 0 ? 0.1f : 0.0f;"),
    _m("u-bias-side", "    bias = s->Side == 0 ? 0.15f : 0.0f;",
       "    bias = s->Side == 1 ? 0.15f : 0.0f;"),
    _m("u-dirt-pitch", "        skidPitch = bias + 1.0f;", "        skidPitch = 1.0f;"),
    _m("u-dirt-pitch-none", "    if (!onRoad)\n        skidPitch = bias + 1.0f;\n", ""),
    _m("u-skid-vol", "    skid = clamp_f(skid * volume, 0.0f, onRoad ? 3.5f : 2.75f);",
       "    skid = clamp_f(skid, 0.0f, onRoad ? 3.5f : 2.75f);"),
    _m("u-skid-cap-road", "    skid = clamp_f(skid * volume, 0.0f, onRoad ? 3.5f : 2.75f);",
       "    skid = clamp_f(skid * volume, 0.0f, onRoad ? 3.0f : 2.75f);"),
    _m("u-skid-cap-dirt", "    skid = clamp_f(skid * volume, 0.0f, onRoad ? 3.5f : 2.75f);",
       "    skid = clamp_f(skid * volume, 0.0f, onRoad ? 3.5f : 2.5f);"),
    _m("u-skid-lo", "    skid = clamp_f(skid * volume, 0.0f, onRoad ? 3.5f : 2.75f);",
       "    skid = clamp_f(skid * volume, 0.1f, onRoad ? 3.5f : 2.75f);"),
    _m("u-skid-on", "    on = onRoad ? &s->RoadSkid : &s->DirtSkid;",
       "    on = &s->RoadSkid;"),
    _m("u-skid-off", "    off = onRoad ? &s->DirtSkid : &s->RoadSkid;",
       "    off = &s->DirtSkid;"),
    _m("u-skid-se", "    if (SoundEnabled && CarSoundEnabled) {\n"
       "        if (!bsample_is_playing(on) && 0.0f < skid)",
       "    if (CarSoundEnabled) {\n"
       "        if (!bsample_is_playing(on) && 0.0f < skid)"),
    _m("u-skid-cse", "    if (SoundEnabled && CarSoundEnabled) {\n"
       "        if (!bsample_is_playing(on) && 0.0f < skid)",
       "    if (SoundEnabled) {\n"
       "        if (!bsample_is_playing(on) && 0.0f < skid)"),
    _m("u-skid-play-cmp", "        if (!bsample_is_playing(on) && 0.0f < skid)",
       "        if (!bsample_is_playing(on) && 0.0f <= skid)"),
    _m("u-skid-play-pitch", "            bsample_play(on, skid, 0.0f, skidPitch - 1.0f);",
       "            bsample_play(on, skid, 0.0f, skidPitch);"),
    _m("u-skid-stop-cmp", "        if (bsample_is_playing(on) && skid <= 0.0f)",
       "        if (bsample_is_playing(on) && skid < 0.0f)"),
    _m("u-skid-off-stop", "    if (bsample_is_playing(off))\n        bsample_stop(off);\n"
       "    if (0.0f < skid) {", "    if (0.0f < skid) {"),
    _m("u-skid-set-cmp", "    if (0.0f < skid) {\n        bsample_set_volume(on, skid);",
       "    if (0.0f <= skid) {\n        bsample_set_volume(on, skid);"),
    _m("u-skid-set-pitch", "        bsample_set_pitch(on, skidPitch - 1.0f);",
       "        bsample_set_pitch(on, skidPitch);"),
    _m("u-skid-set-az", "        bsample_set_azimuth(on, azimuth);\n    } else {\n"
       "        bsample_stop(on);\n    }\n\n    playertiresound_update_squall",
       "    } else {\n        bsample_stop(on);\n    }\n\n"
       "    playertiresound_update_squall"),
    _m("u-skid-else-stop", "    } else {\n        bsample_stop(on);\n    }\n\n"
       "    playertiresound_update_squall",
       "    }\n\n    playertiresound_update_squall"),
    _m("u-squall-road", "    playertiresound_update_squall(s, onRoad, volume, azimuth, pitch);",
       "    playertiresound_update_squall(s, 1, volume, azimuth, pitch);"),
    _m("u-squall-vol", "    playertiresound_update_squall(s, onRoad, volume, azimuth, pitch);",
       "    playertiresound_update_squall(s, onRoad, 1.0f, azimuth, pitch);"),
    _m("u-bo-slip-rear", "c->State.WheelSlip[2].x\n"
       "                                            + c->State.WheelSlip[3].x",
       "c->State.WheelSlip[2].x\n"
       "                                            + c->State.WheelSlip[2].x"),
    _m("u-bo-slip-front", "(c->State.WheelSlip[0].x\n"
       "                              + c->State.WheelSlip[1].x)",
       "(c->State.WheelSlip[0].x\n"
       "                              + c->State.WheelSlip[0].x)"),
    _m("u-bo-slip-y", "c->State.WheelSlip[3].x)", "c->State.WheelSlip[3].y)"),
    _m("u-bo-slip-half", "                   + (double)(c->State.WheelSlip[0].x",
       "                   + 0.5 * (double)(c->State.WheelSlip[0].x"),
    _m("u-bo-onroad", "    if (onRoad && 0.2f < c->State.Throttle",
       "    if (0.2f < c->State.Throttle"),
    _m("u-bo-thr", "    if (onRoad && 0.2f < c->State.Throttle",
       "    if (onRoad && 0.25f < c->State.Throttle"),
    _m("u-bo-thr-le", "    if (onRoad && 0.2f < c->State.Throttle",
       "    if (onRoad && 0.2f <= c->State.Throttle"),
    _m("u-bo-slip", "&& 3.0f < slip     // gp-27420", "&& 3.5f < slip     // gp-27420"),
    _m("u-bo-slip-le", "&& 3.0f < slip     // gp-27420", "&& 3.0f <= slip     // gp-27420"),
    _m("u-bo-vmag", "        && c->State.VelocityMagnitude < 30.0f) {",
       "        && c->State.VelocityMagnitude < 31.0f) {"),
    _m("u-bo-vmag-le", "        && c->State.VelocityMagnitude < 30.0f) {",
       "        && c->State.VelocityMagnitude <= 30.0f) {"),
    _m("u-bo-se", "        if (SoundEnabled && CarSoundEnabled\n"
       "            && !bsample_is_playing(&s->BurnOutPeel))",
       "        if (CarSoundEnabled\n"
       "            && !bsample_is_playing(&s->BurnOutPeel))"),
    _m("u-bo-cse", "        if (SoundEnabled && CarSoundEnabled\n"
       "            && !bsample_is_playing(&s->BurnOutPeel))",
       "        if (SoundEnabled\n"
       "            && !bsample_is_playing(&s->BurnOutPeel))"),
    _m("u-bo-playing", "            && !bsample_is_playing(&s->BurnOutPeel))\n"
       "            bsample_play", ")\n            bsample_play"),
    _m("u-bo-play-pitch", "                         s->Side == 0 ? 0.15f : 0.0f);",
       "                         s->Side == 1 ? 0.15f : 0.0f);"),
    _m("u-bo-play-vol", "            bsample_play(&s->BurnOutPeel, 0.0f, 0.0f,",
       "            bsample_play(&s->BurnOutPeel, 1.0f, 0.0f,"),
    _m("u-bo-k", "            float v = slip * 0.0625f;",
       "            float v = slip * 0.06f;"),
    _m("u-bo-cap", "                               (3.0f < v ? 3.0f : v) * volume);",
       "                               (2.0f < v ? 2.0f : v) * volume);"),
    _m("u-bo-vol", "                               (3.0f < v ? 3.0f : v) * volume);",
       "                               (3.0f < v ? 3.0f : v));"),
    _m("u-bo-az", "        bsample_set_azimuth(&s->BurnOutPeel, azimuth);\n", ""),
    _m("u-bo-stop", "    } else if (bsample_is_playing(&s->BurnOutPeel)) {",
       "    } else if (0) {"),
    _m("u-rn-se", "        if (SoundEnabled && CarSoundEnabled && RoadNoiseEnabled\n"
       "            && !bsample_is_playing(&s->RoadNoise)",
       "        if (CarSoundEnabled && RoadNoiseEnabled\n"
       "            && !bsample_is_playing(&s->RoadNoise)"),
    _m("u-rn-cse", "        if (SoundEnabled && CarSoundEnabled && RoadNoiseEnabled\n"
       "            && !bsample_is_playing(&s->RoadNoise)",
       "        if (SoundEnabled && RoadNoiseEnabled\n"
       "            && !bsample_is_playing(&s->RoadNoise)"),
    _m("u-rn-rne", "        if (SoundEnabled && CarSoundEnabled && RoadNoiseEnabled\n"
       "            && !bsample_is_playing(&s->RoadNoise)",
       "        if (SoundEnabled && CarSoundEnabled\n"
       "            && !bsample_is_playing(&s->RoadNoise)"),
    _m("u-rn-playing", "            && !bsample_is_playing(&s->RoadNoise)\n            && bsound",
       "            && bsound"),
    _m("u-rn-catvol", "            && bsound_get_category_volume(bsound_get(), 4) == 0.0f)",
       "            && bsound_get_category_volume(bsound_get(), 4) != 0.0f)"),
    _m("u-rn-catvol-cat", "            && bsound_get_category_volume(bsound_get(), 4) == 0.0f)",
       "            && bsound_get_category_volume(bsound_get(), 3) == 0.0f)"),
    _m("u-rn-play-pan", "            bsample_play(&s->RoadNoise, 0.0f, (float)azimuth,",
       "            bsample_play(&s->RoadNoise, 0.0f, 0.0f,"),
    _m("u-rn-play-vol", "            bsample_play(&s->RoadNoise, 0.0f, (float)azimuth,",
       "            bsample_play(&s->RoadNoise, noise, (float)azimuth,"),
    _m("u-rn-play-pitch", "                         playertiresound_calc_tire_noise_pitch(s) - 1.0f);",
       "                         playertiresound_calc_tire_noise_pitch(s));"),
    _m("u-rn-vol", "        bsample_set_volume(&s->RoadNoise, noise * s->RoadNoiseScale);",
       "        bsample_set_volume(&s->RoadNoise, noise);"),
    _m("u-rn-az", "        bsample_set_azimuth(&s->RoadNoise, azimuth);\n", ""),
    _m("u-rn-pitch", "            s, &s->RoadNoise, playertiresound_calc_tire_noise_pitch(s));",
       "            s, &s->RoadNoise, 1.0f);"),
    _m("u-rn-dn-stop", "        if (bsample_is_playing(&s->DirtNoise))\n"
       "            bsample_stop(&s->DirtNoise);\n", ""),
    _m("u-dn-p", "        float p = pitch + bias;", "        float p = pitch;"),
    _m("u-dn-se", "        if (SoundEnabled && CarSoundEnabled && RoadNoiseEnabled\n"
       "            && !bsample_is_playing(&s->DirtNoise))",
       "        if (CarSoundEnabled && RoadNoiseEnabled\n"
       "            && !bsample_is_playing(&s->DirtNoise))"),
    _m("u-dn-cse", "        if (SoundEnabled && CarSoundEnabled && RoadNoiseEnabled\n"
       "            && !bsample_is_playing(&s->DirtNoise))",
       "        if (SoundEnabled && RoadNoiseEnabled\n"
       "            && !bsample_is_playing(&s->DirtNoise))"),
    _m("u-dn-rne", "        if (SoundEnabled && CarSoundEnabled && RoadNoiseEnabled\n"
       "            && !bsample_is_playing(&s->DirtNoise))",
       "        if (SoundEnabled && CarSoundEnabled\n"
       "            && !bsample_is_playing(&s->DirtNoise))"),
    _m("u-dn-play", "            bsample_play(&s->DirtNoise, noise, p - 1.0f, 0.0f);",
       "            bsample_play(&s->DirtNoise, noise, 0.0f, p - 1.0f);"),
    _m("u-dn-vol", "        bsample_set_volume(&s->DirtNoise, noise * s->RoadNoiseScale);",
       "        bsample_set_volume(&s->DirtNoise, noise);"),
    _m("u-dn-az", "        bsample_set_azimuth(&s->DirtNoise, azimuth);\n", ""),
    _m("u-dn-pitch", "        playertiresound_set_sample_pitch(s, &s->DirtNoise, p);",
       "        playertiresound_set_sample_pitch(s, &s->DirtNoise, pitch);"),
    _m("u-dn-rn-stop", "        if (bsample_is_playing(&s->RoadNoise))\n"
       "            bsample_stop(&s->RoadNoise);\n", ""),

    # UpdateSquall.
    _m("usq-on", "    BSample *on = onRoad ? &s->Squall : &s->DirtSquall;",
       "    BSample *on = onRoad ? &s->DirtSquall : &s->Squall;"),
    _m("usq-off", "    BSample *off = onRoad ? &s->DirtSquall : &s->Squall;",
       "    BSample *off = onRoad ? &s->Squall : &s->DirtSquall;"),
    _m("usq-off-se", "    if (SoundEnabled && bsample_is_playing(off))",
       "    if (bsample_is_playing(off))"),
    _m("usq-off-stop", "        bsample_stop(off);\n    playertiresound_calc",
       "        ;\n    playertiresound_calc"),
    _m("usq-vol", "    v = v * volume;", "    v = v * 0.5f;"),
    _m("usq-se", "    if (on != off && SoundEnabled && CarSoundEnabled) {",
       "    if (on != off && CarSoundEnabled) {"),
    _m("usq-cse", "    if (on != off && SoundEnabled && CarSoundEnabled) {",
       "    if (on != off && SoundEnabled) {"),
    _m("usq-play-cmp", "        if (!bsample_is_playing(on) && 0.0f < v)",
       "        if (!bsample_is_playing(on) && 0.0f <= v)"),
    _m("usq-play-pitch", "            bsample_play(on, v, 0.0f, p - 1.0f);",
       "            bsample_play(on, v, 0.0f, p);"),
    _m("usq-else", "        else if (bsample_is_playing(on) && v <= 0.0f)",
       "        if (bsample_is_playing(on) && v <= 0.0f)"),
    _m("usq-stop-cmp", "        else if (bsample_is_playing(on) && v <= 0.0f)",
       "        else if (bsample_is_playing(on) && v < 0.0f)"),
    _m("usq-set-cmp", "    if (0.0f < v) {\n        bsample_set_volume(on, smooth(",
       "    if (0.0f <= v) {\n        bsample_set_volume(on, smooth("),
    _m("usq-smooth-step", "smooth(on->currentVolume, v, 0.05f)",
       "smooth(on->currentVolume, v, 0.06f)"),
    _m("usq-smooth-cur", "smooth(on->currentVolume, v, 0.05f)",
       "smooth(0.0f, v, 0.05f)"),
    _m("usq-set-pitch", "        bsample_set_pitch(on, p - 1.0f);",
       "        bsample_set_pitch(on, p);"),
    _m("usq-az", "        bsample_set_azimuth(on, azimuth);\n    } else {\n"
       "        bsample_stop(on);\n    }\n}",
       "    } else {\n        bsample_stop(on);\n    }\n}"),
    _m("usq-else-stop", "    } else {\n        bsample_stop(on);\n    }\n}\n\n"
       "// The track's leaves", "    }\n}\n\n// The track's leaves"),

    # UpdateLeaves.
    _m("lv-found", "    if (!s->FoundLeavesSample)\n        return;\n", ""),
    _m("lv-a", "    a = s->pCar->State.WheelTerrain[s->Side == 0 ? 0 : 3];",
       "    a = s->pCar->State.WheelTerrain[s->Side == 0 ? 1 : 3];"),
    _m("lv-a-side", "    a = s->pCar->State.WheelTerrain[s->Side == 0 ? 0 : 3];",
       "    a = s->pCar->State.WheelTerrain[s->Side == 1 ? 0 : 3];"),
    _m("lv-b", "    b = s->pCar->State.WheelTerrain[s->Side == 0 ? 1 : 2];",
       "    b = s->pCar->State.WheelTerrain[s->Side == 0 ? 1 : 3];"),
    _m("lv-leaves", "    if (a == TERRAIN_TYPE_AUTUMN_LEAVES || b == TERRAIN_TYPE_AUTUMN_LEAVES\n",
       "    if (b == TERRAIN_TYPE_AUTUMN_LEAVES\n"),
    _m("lv-shoulder", "        || a == TERRAIN_TYPE_AUTUMN_LEAVES_SHOULDER\n", ""),
    _m("lv-autumn", "        || a == TERRAIN_TYPE_ROAD_AUTUMN || b == TERRAIN_TYPE_ROAD_AUTUMN) {",
       "        || a == TERRAIN_TYPE_ROAD_AUTUMN) {"),
    _m("lv-play-vol", "            bsample_play(&s->LeavesNoise, volume, (float)azimuth,",
       "            bsample_play(&s->LeavesNoise, 1.0f, (float)azimuth,"),
    _m("lv-play-pan", "            bsample_play(&s->LeavesNoise, volume, (float)azimuth,",
       "            bsample_play(&s->LeavesNoise, volume, 0.0f,"),
    _m("lv-play-pitch", "                         pitch - 1.0f);\n        } else {\n"
       "            bsample_set_volume(&s->LeavesNoise",
       "                         pitch);\n        } else {\n"
       "            bsample_set_volume(&s->LeavesNoise"),
    _m("lv-vol", "            bsample_set_volume(&s->LeavesNoise, volume);",
       "            bsample_set_volume(&s->LeavesNoise, 1.0f);"),
    _m("lv-az", "            bsample_set_azimuth(&s->LeavesNoise, azimuth);\n", ""),
    _m("lv-pitch", "            bsample_set_pitch(&s->LeavesNoise, pitch);",
       "            bsample_set_pitch(&s->LeavesNoise, pitch - 1.0f);"),
    _m("lv-stop", "    } else if (bsample_is_playing(&s->LeavesNoise)) {",
       "    } else if (0) {"),

    # The thump and the scrape.
    _m("rtt-time", "    s->UpdateThumperTime = 0.0f;\n    if (bsample_is_playing(&s->BustedScrape))",
       "    s->UpdateThumperTime = 0.5f;\n    if (bsample_is_playing(&s->BustedScrape))"),
    _m("rtt-stop", "    if (bsample_is_playing(&s->BustedScrape))\n"
       "        bsample_stop(&s->BustedScrape);\n}", "}"),
    _m("th-sub", "    s->UpdateThumperTime = s->UpdateThumperTime - WorldTimeElapsed;",
       "    s->UpdateThumperTime = s->UpdateThumperTime + WorldTimeElapsed;"),
    _m("th-le", "    if (s->UpdateThumperTime <= 0.0f) {",
       "    if (s->UpdateThumperTime < 0.0f) {"),
    _m("th-abs", "        float speed = fabsf(c->State.VelocityMagnitude);",
       "        float speed = c->State.VelocityMagnitude;"),
    _m("th-slow", "        if (speed < 3.0f) {", "        if (speed < 2.0f) {"),
    _m("th-slow-le", "        if (speed < 3.0f) {", "        if (speed <= 3.0f) {"),
    _m("th-slow-reset", "            playertiresound_reset_thumper_time(s);\n        } else {",
       "            ;\n        } else {"),
    _m("th-touch-a", "            if (t[s->Side != 1] != 0 || t[s->Side == 1 ? 3 : 2] != 0) {",
       "            if (t[s->Side == 0] != 0 || t[s->Side == 1 ? 3 : 2] != 0) {"),
    _m("th-touch-b", "            if (t[s->Side != 1] != 0 || t[s->Side == 1 ? 3 : 2] != 0) {",
       "            if (t[s->Side != 1] != 0 || t[s->Side == 1 ? 2 : 2] != 0) {"),
    _m("th-touch-or", "            if (t[s->Side != 1] != 0 || t[s->Side == 1 ? 3 : 2] != 0) {",
       "            if (t[s->Side != 1] != 0 && t[s->Side == 1 ? 3 : 2] != 0) {"),
    _m("th-off-side", "                uint16_t off = s->Side != 0",
       "                uint16_t off = s->Side == 1"),
    _m("th-off-neg", "                               ? (uint16_t)-ThumperAzimuthOffset",
       "                               ? ThumperAzimuthOffset"),
    _m("th-se", "                if (SoundEnabled && CarSoundEnabled && CarDamageSoundEnabled) {",
       "                if (CarSoundEnabled && CarDamageSoundEnabled) {"),
    _m("th-cse", "                if (SoundEnabled && CarSoundEnabled && CarDamageSoundEnabled) {",
       "                if (SoundEnabled && CarDamageSoundEnabled) {"),
    _m("th-cdse", "                if (SoundEnabled && CarSoundEnabled && CarDamageSoundEnabled) {",
       "                if (SoundEnabled && CarSoundEnabled) {"),
    _m("th-play-vol", "                    bsample_play(&s->Busted, s->Base.Sound.Volume, 0.0f,",
       "                    bsample_play(&s->Busted, 1.0f, 0.0f,"),
    _m("th-play-pitch", "                                 s->Base.Sound.Pitch - 1.0f);",
       "                                 s->Base.Sound.Pitch);"),
    _m("th-az", "(uint16_t)(off\n                                                   + s->Base.Sound.Azimuth));",
       "(uint16_t)(off));"),
    _m("th-k", "ee_div(1.9f, speed)", "ee_div(2.0f, speed)"),
    _m("th-min-cmp", "            if (s->UpdateThumperTime < 0.035f)",
       "            if (s->UpdateThumperTime < 0.03f)"),
    _m("th-min-set", "                s->UpdateThumperTime = 0.035f;",
       "                s->UpdateThumperTime = 0.03f;"),
    _m("th-scrape-blown", "    if (blown_tires(c) > 0 && s->PrevShouldMakeRoadNoise != 0",
       "    if (blown_tires(c) > 1 && s->PrevShouldMakeRoadNoise != 0"),
    _m("th-scrape-prev", "blown_tires(c) > 0 && s->PrevShouldMakeRoadNoise != 0",
       "blown_tires(c) > 0"),
    _m("th-scrape-front", "(s->Base.FrontTireTouching != 0 || s->Base.RearTireTouching != 0)",
       "(s->Base.RearTireTouching != 0)"),
    _m("th-scrape-rear", "(s->Base.FrontTireTouching != 0 || s->Base.RearTireTouching != 0)",
       "(s->Base.FrontTireTouching != 0)"),
    _m("th-scrape-vk", "                  * (c->State.VelocityMagnitude * 0.04f);",
       "                  * (c->State.VelocityMagnitude * 0.05f);"),
    _m("th-scrape-vvol", "        float v = s->Base.Sound.Volume\n", "        float v = 1.0f\n"),
    _m("th-scrape-pk", "                  * (c->State.VelocityMagnitude * 0.004f",
       "                  * (c->State.VelocityMagnitude * 0.005f"),
    _m("th-scrape-pb", "                     + 1.4f);", "                     + 1.5f);"),
    _m("th-scrape-ppitch", "        float p = s->Base.Sound.Pitch\n", "        float p = 1.0f\n"),
    _m("th-scrape-play-pitch", "            bsample_play(&s->BustedScrape, v, 0.0f, p - 1.0f);",
       "            bsample_play(&s->BustedScrape, v, 0.0f, p);"),
    _m("th-scrape-play-az", "            bsample_play(&s->BustedScrape, v, 0.0f, p - 1.0f);\n"
       "            bsample_set_azimuth(&s->BustedScrape, s->Base.Sound.Azimuth);",
       "            bsample_play(&s->BustedScrape, v, 0.0f, p - 1.0f);"),
    _m("th-scrape-vol", "            bsample_set_volume(&s->BustedScrape, v);",
       "            bsample_set_volume(&s->BustedScrape, 1.0f);"),
    _m("th-scrape-az2", "            bsample_set_volume(&s->BustedScrape, v);\n"
       "            bsample_set_azimuth(&s->BustedScrape, s->Base.Sound.Azimuth);",
       "            bsample_set_volume(&s->BustedScrape, v);"),
    _m("th-scrape-pitch", "            bsample_set_pitch(&s->BustedScrape, p - 1.0f);",
       "            bsample_set_pitch(&s->BustedScrape, p);"),
    _m("th-scrape-stop", "        stop = 1;\n    }", "        stop = 0;\n    }"),
    _m("th-stop-playing", "    if (stop && bsample_is_playing(&s->BustedScrape))",
       "    if (stop)"),
    _m("ptbo", "    s->PlayThumperSounds = 1;", "    s->PlayThumperSounds = 2;"),
    _m("psrn", "    s->RoadNoiseScale = f;", "    s->RoadNoiseScale = f * 0.5f;"),

    # OpponentTireSound.
    _m("oc-vt", "    s->Base.Sound._vtable = OPPONENTTIRESOUND_VTABLE;\n"
       "    bsample_construct(&s->RoadSkid, 0);",
       "    s->Base.Sound._vtable = PLAYERTIRESOUND_VTABLE;\n"
       "    bsample_construct(&s->RoadSkid, 0);"),
    _m("oc-order", "    bsample_construct(&s->RoadSkid, 0);\n"
       "    bsample_construct(&s->DirtSkid, 0);\n    s->pCar = c;",
       "    bsample_construct(&s->DirtSkid, 0);\n"
       "    bsample_construct(&s->RoadSkid, 0);\n    s->pCar = c;"),
    _m("oc-rk-name", "sound_get_in_game_sample(m, \"LongitudinalSkid\"));\n"
       "    bsample_set_category(&s->RoadSkid, 0);",
       "sound_get_in_game_sample(m, \"GravelSkid\"));\n"
       "    bsample_set_category(&s->RoadSkid, 0);"),
    _m("oc-rk-cat", "    bsample_set_category(&s->RoadSkid, 0);",
       "    bsample_set_category(&s->RoadSkid, 1);"),
    _m("oc-dk-cat", "    bsample_set_category(&s->DirtSkid, 0);",
       "    bsample_set_category(&s->DirtSkid, 1);"),
    _m("oc-prev", "    s->PrevSkid = &s->RoadSkid;", "    s->PrevSkid = &s->DirtSkid;"),
    _m("oc-tsv", "    s->TargetSkidVolume = 0.0f;\n    s->CurrSkidVolume = 0.0f;",
       "    s->TargetSkidVolume = 0.5f;\n    s->CurrSkidVolume = 0.0f;"),
    _m("oc-csv", "    s->TargetSkidVolume = 0.0f;\n    s->CurrSkidVolume = 0.0f;",
       "    s->TargetSkidVolume = 0.0f;\n    s->CurrSkidVolume = 0.5f;"),
    _m("oc-activate", "    sound3d_activate(&s->Base.Sound, 1);\n}\n\n"
       "void opponenttiresound_destroy",
       "    sound3d_activate(&s->Base.Sound, 0);\n}\n\n"
       "void opponenttiresound_destroy"),
    _m("oc-dtor-order", "    bsample_destruct(&s->DirtSkid);\n"
       "    bsample_destruct(&s->RoadSkid);\n    basetiresound_destroy",
       "    bsample_destruct(&s->RoadSkid);\n"
       "    bsample_destruct(&s->DirtSkid);\n    basetiresound_destroy"),
    _m("oc-dtor-flags", "    basetiresound_destroy(&s->Base, flags);\n}\n\n// The flop",
       "    basetiresound_destroy(&s->Base, 0);\n}\n\n// The flop"),
    _m("ou-active", "    if (!s->Base.Sound.Activated)\n        return;\n"
       "    s->Base.Sound.Volume = volume;",
       "    s->Base.Sound.Volume = volume;"),
    _m("ou-vol", "    s->Base.Sound.Volume = volume;\n    s->Base.Sound.Azimuth = azimuth;\n"
       "    opponenttiresound_update_skids",
       "    s->Base.Sound.Azimuth = azimuth;\n    opponenttiresound_update_skids"),
    _m("ou-az", "    s->Base.Sound.Azimuth = azimuth;\n    opponenttiresound_update_skids",
       "    opponenttiresound_update_skids"),
    _m("ou-pitch", "    s->Base.Sound.Azimuth = azimuth;\n    opponenttiresound_update_skids",
       "    s->Base.Sound.Azimuth = azimuth;\n    s->Base.Sound.Pitch = pitch;\n"
       "    opponenttiresound_update_skids"),
    _m("ou-skids-vol", "    opponenttiresound_update_skids(s, volume, azimuth, pitch);",
       "    opponenttiresound_update_skids(s, 1.0f, azimuth, pitch);"),
    _m("ou-k", "    s->Base.Sound.Volume = s->Base.Sound.Volume * 0.75f;",
       "    s->Base.Sound.Volume = s->Base.Sound.Volume * 0.7f;"),
    _m("ou-side", "    basetiresound_update_tire_impact(&s->Base, s->pCar, -1);",
       "    basetiresound_update_tire_impact(&s->Base, s->pCar, 1);"),
    _m("om-base", "    basetiresound_mute(&s->Base, on);\n    bsample_pause(&s->RoadSkid, on != 0);",
       "    bsample_pause(&s->RoadSkid, on != 0);"),
    _m("om-rk", "    bsample_pause(&s->RoadSkid, on != 0);\n"
       "    bsample_pause(&s->DirtSkid, on != 0);\n}",
       "    bsample_pause(&s->RoadSkid, on == 0);\n"
       "    bsample_pause(&s->DirtSkid, on != 0);\n}"),
    _m("om-dk", "    bsample_pause(&s->RoadSkid, on != 0);\n"
       "    bsample_pause(&s->DirtSkid, on != 0);\n}",
       "    bsample_pause(&s->RoadSkid, on != 0);\n}"),
    _m("od-rk", "    bsample_stop(&s->RoadSkid);\n    bsample_stop(&s->DirtSkid);\n"
       "    if (s->PrevSkid", "    bsample_stop(&s->DirtSkid);\n    if (s->PrevSkid"),
    _m("od-prev", "    if (s->PrevSkid != NULL)\n        bsample_stop(s->PrevSkid);\n", ""),

    # UpdateSkids.
    _m("sk-touch", "        if (c->State.WheelTouchingGround[i])\n"
       "            m = slip_length(c, i);", "        m = slip_length(c, i);"),
    _m("sk-worst", "        worst = max_f(worst, m);", "        worst = m;"),
    _m("sk-road", "            road++;", "            road += 2;"),
    _m("sk-dirt", "    dirt = road < 2;", "    dirt = road < 3;"),
    _m("sk-dirt-1", "    dirt = road < 2;", "    dirt = road < 1;"),
    _m("sk-p-k", "    p = c->State.VelocityMagnitude * 0.01015f + 0.3f;",
       "    p = c->State.VelocityMagnitude * 0.01f + 0.3f;"),
    _m("sk-p-b", "    p = c->State.VelocityMagnitude * 0.01015f + 0.3f;",
       "    p = c->State.VelocityMagnitude * 0.01015f + 0.35f;"),
    _m("sk-tsv-dirt", "    s->TargetSkidVolume = (dirt ? 3.5f : 5.0f) * volume;",
       "    s->TargetSkidVolume = (dirt ? 3.0f : 5.0f) * volume;"),
    _m("sk-tsv-road", "    s->TargetSkidVolume = (dirt ? 3.5f : 5.0f) * volume;",
       "    s->TargetSkidVolume = (dirt ? 3.5f : 4.5f) * volume;"),
    _m("sk-tsv-vol", "    s->TargetSkidVolume = (dirt ? 3.5f : 5.0f) * volume;",
       "    s->TargetSkidVolume = (dirt ? 3.5f : 5.0f);"),
    _m("sk-worst-thresh", "    if (worst < 10.0f)\n        s->TargetSkidVolume = 0.0f;",
       "    if (worst < 9.0f)\n        s->TargetSkidVolume = 0.0f;"),
    _m("sk-worst-le", "    if (worst < 10.0f)\n        s->TargetSkidVolume = 0.0f;",
       "    if (worst <= 10.0f)\n        s->TargetSkidVolume = 0.0f;"),
    _m("sk-smooth", "                               0.35f);",
       "                               0.4f);"),
    _m("sk-smp", "    smp = dirt ? &s->DirtSkid : &s->RoadSkid;",
       "    smp = dirt ? &s->RoadSkid : &s->DirtSkid;"),
    _m("sk-prev-cmp", "    if (s->PrevSkid != smp && bsample_is_playing(s->PrevSkid))",
       "    if (bsample_is_playing(s->PrevSkid))"),
    _m("sk-prev-stop", "        bsample_stop(s->PrevSkid);\n    if (SoundEnabled",
       "        ;\n    if (SoundEnabled"),
    _m("sk-se", "    if (SoundEnabled && CarSoundEnabled) {\n"
       "        if (!bsample_is_playing(smp)",
       "    if (CarSoundEnabled) {\n        if (!bsample_is_playing(smp)"),
    _m("sk-cse", "    if (SoundEnabled && CarSoundEnabled) {\n"
       "        if (!bsample_is_playing(smp)",
       "    if (SoundEnabled) {\n        if (!bsample_is_playing(smp)"),
    _m("sk-play-cmp", "        if (!bsample_is_playing(smp) && 0.0f < s->CurrSkidVolume)",
       "        if (!bsample_is_playing(smp) && 0.0f <= s->CurrSkidVolume)"),
    _m("sk-play-pitch", "            bsample_play(smp, s->CurrSkidVolume, 0.0f, p - 1.0f);",
       "            bsample_play(smp, s->CurrSkidVolume, 0.0f, p);"),
    _m("sk-stop-cmp", "        if (bsample_is_playing(smp) && s->CurrSkidVolume <= 0.0f)",
       "        if (bsample_is_playing(smp) && s->CurrSkidVolume < 0.0f)"),
    _m("sk-set-cmp", "    if (0.0f < s->CurrSkidVolume) {",
       "    if (0.0f <= s->CurrSkidVolume) {"),
    _m("sk-set-vol", "        bsample_set_volume(smp, s->CurrSkidVolume);",
       "        bsample_set_volume(smp, s->TargetSkidVolume);"),
    _m("sk-set-pitch", "        bsample_set_pitch(smp, p - 1.0f);",
       "        bsample_set_pitch(smp, p);"),
    _m("sk-set-az", "        bsample_set_azimuth(smp, azimuth);\n", ""),
    _m("sk-else-stop", "    } else {\n        bsample_stop(smp);\n    }", "    }"),
    _m("sk-prev-store", "    s->PrevSkid = smp;\n", ""),

    # The factories, the two calls and the tables.
    _m("mk-player-tag", "\"PlayerTireSound\",\n                                 0, 16);",
       "\"PlayerTireSound\",\n                                 1, 16);"),
    _m("mk-player-pool", "\"PlayerTireSound\",\n                                 0, 16);",
       "\"PlayerTireSound\",\n                                 0, 0);"),
    _m("mk-ai-tag", "\"kAITireSound\",", "\"AITireSound\","),
    _m("mk-ai-pool", "\"kAITireSound\",\n                                   0, 16);",
       "\"kAITireSound\",\n                                   0, 0);"),
    _m("mk-player-side", "    playertiresound_construct(s, c, side);",
       "    playertiresound_construct(s, c, 0);"),
    _m("tbo-slot", "vt_slot(tire->_vtable, TIRESOUND_VT_TRIGGER_BLOW_OUT)",
       "vt_slot(tire->_vtable, TIRESOUND_VT_SCALE_ROAD_NOISE)"),
    _m("srn-slot", "vt_slot(tire->_vtable, TIRESOUND_VT_SCALE_ROAD_NOISE)",
       "vt_slot(tire->_vtable, TIRESOUND_VT_TRIGGER_BLOW_OUT)"),
    _m("srn-f", "    ((VtScaleFn)e->fn)(vt_this(tire, e), f);",
       "    ((VtScaleFn)e->fn)(vt_this(tire, e), f * 0.5f);"),
    _m("h-tbo-slot", "#define TIRESOUND_VT_TRIGGER_BLOW_OUT 64",
       "#define TIRESOUND_VT_TRIGGER_BLOW_OUT 72", TSH),
    _m("h-player-vt", "#define PLAYERTIRESOUND_VTABLE   0x002bc198u",
       "#define PLAYERTIRESOUND_VTABLE   0x002bc199u", TSH),
    _m("vt-base-mute", "    E(basetiresound_mute),                              // 32",
       "    E(playertiresound_mute),                              // 32"),
    _m("vt-base-24", "    { 0, 0, NULL },                                     // 24  Update",
       "    E(playertiresound_update),                                     // 24  Update"),
    _m("vt-player-deact", "    E(playertiresound_deactivate_sound),                // 40",
       "    E(playertiresound_activate_sound),                // 40"),
    _m("vt-player-tbo", "    E(playertiresound_trigger_tire_blow_out),           // 64",
       "    E(basetiresound_trigger_tire_blow_out),           // 64"),
    _m("vt-player-srn", "    E(playertiresound_scale_road_noise),                // 72",
       "    E(basetiresound_scale_road_noise),                // 72"),
    _m("vt-ai-update", "    E(opponenttiresound_update),                        // 24",
       "    E(playertiresound_update),                        // 24"),
    _m("vt-ai-deact", "    E(opponenttiresound_deactivate_sound),              // 40",
       "    E(opponenttiresound_activate_sound),              // 40"),
    _m("vt-ai-tbo", "    E(basetiresound_trigger_tire_blow_out),             // 64  0x00214a70\n"
       "    E(basetiresound_scale_road_noise),                  // 72  0x00214a68\n};\n\n#undef E",
       "    E(basetiresound_scale_road_noise),             // 64  0x00214a70\n"
       "    E(basetiresound_scale_road_noise),                  // 72  0x00214a68\n};\n\n#undef E"),
    _m("vt-install", "    vt_install(OPPONENTTIRESOUND_VTABLE, opponenttiresound_vt,",
       "    vt_install(OPPONENTTIRESOUND_VTABLE, playertiresound_vt,"),
]

EQUIVALENT = {
    "sv-k": "past 0.7 the squall's volume is at least 1.38, so capped "
            "at 1 by either scale",
    "sv-cap": "the volume before the cap is 0 or at least 1.38, never in "
              "1 .. 1.1",
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
        todo, SOURCES, "tiresound_test",
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
        d.with_suffix(".model").write_text(NL.join(got) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(got, harness)
    print("%d ops, %d lines, %d differ" % (len(lines), len(harness), n))
    for lab, pcs in (("eediv", e.eediv_pcs), ("eemul", e.eemul_pcs),
                     ("eesqrt", e.eesqrt_pcs)):
        if pcs:
            print("%s at %s" % (lab, " ".join("%08x" % p
                                              for p in sorted(pcs))))
    sys.exit(1 if n or rc else 0)


if __name__ == "__main__":
    main()
