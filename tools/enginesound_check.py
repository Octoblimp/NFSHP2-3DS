#!/usr/bin/env python3
"""Cross-check 3DS Files/source/enginesound.c against the retail image,
SLES_507.31.

**The model** is retail's own CarSoundEngine.obj run in
retail_model.RetailEmu with the EE's divide, product and root (eediv,
eemul, eesqrt): VoiceAttr's Play, Stop, SetVolume, SetPitch and
SetAzimuth; PlayerEngineSound's constructor, destructor, Init, Mute,
Deactivate/ActivateSound, ResolveTables, RampThrottle,
UpdateGearShiftEffect, UpdateToRedLineRPM, UpdateNitroEffect,
UpdateEngineDucker, UpdateEngine, Update and Set; AIEngineSound's
constructor, destructor, Update, Mute, GetEngineSampleName,
ComputeRPMPitchShift, ComputeStartLineRPMPitchShift and
Deactivate/ActivateSound; engine_sound's two factories -- through the two
vtables. Sound3d's constructor, destructor and Activate, Average's
constructor, destructor, Record and Flush, bStrCpy, bStrCat and the
smooth, min, max and clamp templates run in the image too. The harness
(tools/src/enginesound_test.c) runs enginesound.c's, through the port's
vtables, with copies of sound3d.c's three and average.c itself.

**The two builds.** enginesound.c plays the player's engine as retail
does in mono unless ENGINESOUND_RETAIL_VOICES is 1 (enginesound.h). The
harness is built both ways: with it at 1 against the model as it is, the
audio mode the script's, and at 0 against the model in mono -- retail's
GetAudioMode answering 0 and its player count never 1, so it locks no
right voices, as the port's mono build does not. Mutations run on the
mono build, and those that survive it on the other.

**The fakes**, the same on both sides, each printing what it is handed:
bSample's constructor, destructor, Initialize, SetCategory, Play, Stop,
Pause, SetAzimuth, SetVolume, SetPitch, IsPlaying (playing from Play to
Stop) and LockVoice; bSound::Region (a region a name, made on demand),
Update and GetCategoryVolume (the script's); bRegion::Sample and
GetInGameSample (a sample a name, none for those the script names);
sound's random float (the script's queue) and audio mode (not printed);
bMalloc (0xa5-filled, its size checked against retail's records) and
__builtin_delete; the ticker, 7 a call; bGetFile, serving the disc's
SOUND/ENGINE.CTB and ENGINE.LTB; eGetView; IsReplayDemoMode;
DriveTrain::GetState, through the drive train's own vtable; and Sound3d's
UpdateCamRelativeDistAndVelocity.

**The script** dumps the tables; makes a player's engine and reads its
two tables; plays, stops and turns its voices; ramps the throttle up and
down past both snaps and the clamp; shifts with the clutch in each state,
the RPM at and over 1500 and TestRPM; scales to the red line in each gear,
the red line under and over the shift point, the top gear, the cap; runs
the nitro off, starting, holding, fading and stopping; ducks under the
music and lets go; runs UpdateEngine frame by frame through the right
voices' delay and its wrap, a patch disabled and missing, each crossfade's
ends, the Timbre beyond them, the volume's cap, mono's 1.3; updates
through the vtable from the car's camera in each audio mode, off-centre,
in each replay state and the demo, with TestRPM, inactive and with sound
off; calls Set with each POV, the replay's facing either way and wrapping,
the throttle's cut; mutes and unmutes, in the same mode and a new one;
resolves again; and makes engines with a patch missing, sound off, no
nitro loop and two players. It makes AI engines (a racer's and
traffic's), names them, runs the RPM's mean through a gear change and its
six frames, the start line's revs up and down with the dice either side
of 4, and updates each on the start line, in the race, below and over
75 km/h, playing and not, with sound off; mutes, deactivates and
activates them; and deletes each kind.

    python tools/enginesound_check.py
    python tools/enginesound_check.py --mutate [--only a,b]
    python tools/enginesound_check.py --dump out/enginesound
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

HARNESS = "tools/src/enginesound_test.c"
ESC = "3DS Files/source/enginesound.c"
ESH = "3DS Files/source/enginesound.h"
SOURCES = [HARNESS, ESC, "3DS Files/source/average.c",
           "3DS Files/source/replay.c", "3DS Files/source/p32.c",
           "3DS Files/source/vtable.c"]
RETAIL_VOICES = ["-DENGINESOUND_RETAIL_VOICES=1"]
SOUND_DIR = ROOT / "extracted-retail" / "SOUND"
TABLES = (SOUND_DIR / "ENGINE.CTB", SOUND_DIR / "ENGINE.LTB")
HARNESS_TIMEOUT = 30
LIMIT = 400000

GP = retail_model.RETAIL_GP
F = {
    "vplay": 0x0020fad0, "vstop": 0x0020fb78, "vvol": 0x0020fb98,
    "vpitch": 0x0020fc18, "vaz": 0x0020fc48, "init": 0x0020ffc0,
    "resolve": 0x002105d0, "ramp": 0x002106c8, "gear": 0x00210788,
    "redline": 0x00210880, "nitro": 0x00210950, "ducker": 0x00210b48,
    "ueng": 0x00210bf8, "set": 0x002116d8, "aname": 0x00211a90,
    "arpm": 0x00211b10, "astart": 0x00211c40, "mkplayer": 0x00211d90,
    "mkai": 0x00211de0,
}

# What the vtables point at, by name.
FNAME = {
    0x0020fe70: "player-dtor", 0x00208b28: "activate",
    0x00211390: "player-update", 0x00210410: "player-mute",
    0x00210400: "player-deact", 0x00210408: "player-act",
    0x00208c78: "camrel", 0x00212418: "ai-dtor", 0x002118a0: "ai-update",
    0x00211a80: "ai-mute", 0x00211d58: "ai-deact", 0x00211d60: "ai-act",
}
VT_PLAYER, VT_AI, VT_S3D = 0x002bbfc0, 0x002bbf80, 0x002bb2b0
VT_TABLES = (("player", VT_PLAYER), ("ai", VT_AI))
VT_ENTRIES = 8

SE, CSE, TESTRPM = GP - 23056, GP - 20456, GP - 18380
NPP, WTS, WTE = GP - 20920, GP - 19572, GP - 19560
BSOUND, PRC, PRACE = GP - 13696, GP - 22216, GP - 22272
CTI, LPES = GP - 20616, GP - 16268

# Retail's records.
SIZES = {"PlayerEngineSound": 7176, "AIEngineSound": 268,
         "..\\indep\\src\\table.cpp": 80}
CTI_SIZE = 1376
CAR_SIZE = 2304
MAXCAR = 8
MAXVIEW = 4
P_LEFT, P_RIGHT, VOICE = 504, 3704, 200
P_DELAY, P_DEFS, P_ES, ES = 6904, 6920, 6932, 20

# The dumps' fields: name, offset, type (as the harness's).
PFIELDS = (
    ("act", 0, "i"), ("dop", 4, "i"), ("svol", 8, "f"),
    ("spitch", 12, "f"), ("saz", 16, "H"), ("thr", 36, "i"),
    ("redoff", 40, "f"), ("topoff", 44, "f"), ("gsvs", 428, "f"),
    ("gsup", 432, "i"), ("brt", 436, "f"), ("bh", 440, "B"),
    ("vol", 444, "i"), ("ratio", 448, "i"), ("dopp", 452, "H"),
    ("azim", 454, "H"), ("sep", 456, "H"), ("timbre", 458, "b"),
    ("hp", 459, "b"), ("cl", 460, "h"), ("clt", 462, "h"),
    ("cur", 464, "h"), ("bend", 468, "i"), ("bass", 472, "i"),
    ("pov0", 476, "h"), ("pov1", 478, "h"), ("pov2", 480, "h"),
    ("pov3", 482, "h"), ("stereo", 484, "i"), ("bfb", 488, "i"),
    ("rpm", 492, "f"), ("dtime", 496, "f"), ("dscale", 500, "f"),
    ("mode", 7172, "i"),
)
AFIELDS = (
    ("act", 0, "i"), ("dop", 4, "i"), ("svol", 8, "f"),
    ("spitch", 12, "f"), ("saz", 16, "H"), ("base", 224, "f"),
    ("tgt", 228, "f"), ("curp", 232, "f"), ("slots", 236, "B"),
    ("slot", 237, "B"), ("n", 238, "B"), ("total", 240, "f"),
    ("mean", 244, "f"), ("gear", 252, "i"), ("frames", 256, "i"),
    ("srpm", 260, "f"), ("gvs", 264, "f"),
)
PACK = {"i": "<i", "h": "<h", "H": "<H", "b": "<b", "B": "<B", "f": "<I"}


def fbits(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def fx(x):
    return "%08x" % fbits(x)


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


class Model(object):
    def __init__(self, mono=False):
        self.mono = mono
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True,
                                            eemul=True, eesqrt=True)
        e.stub_bware()
        self.allocs = []                # (address, tag)
        self.srcs = {}                  # (name, in-game) -> sample
        self.regs = {}                  # name -> region
        self.files = []
        self.missing, self.nosrc = set(), set()
        self.playing = set()
        self.rf = []
        self.tick, self.step = 0, 7
        self.am = 0
        self.rdm = 0
        self.catvol = 0
        self.cars, self.types, self.players = {}, {}, {}
        self.dts, self.engines, self.infos, self.dtstates = {}, {}, {}, {}
        self.snds = {}
        self.bsound = e.alloc(16)
        self.rc = e.alloc(16, 16)
        e.mem[self.rc:self.rc + 16] = b"\0" * 16
        self.race = e.alloc(16, 16)
        e.mem[self.race:self.race + 16] = b"\0" * 16
        self.cti = e.alloc(CTI_SIZE * MAXCAR, 16)
        e.mem[self.cti:self.cti + CTI_SIZE * MAXCAR] = \
            b"\0" * (CTI_SIZE * MAXCAR)
        self.views = e.alloc(64 * MAXVIEW, 16)
        e.mem[self.views:self.views + 64 * MAXVIEW] = b"\0" * (64 * MAXVIEW)
        self.cams = e.alloc(128 * MAXVIEW, 16)
        e.mem[self.cams:self.cams + 128 * MAXVIEW] = b"\0" * (128 * MAXVIEW)
        self.scratch = e.alloc(64, 16)
        e.put32(BSOUND, self.bsound)
        e.put32(PRC, self.rc)
        e.put32(PRACE, 0)
        e.put32(CTI, self.cti)
        e.put32(SE, 1)
        e.put32(CSE, 1)
        e.put32(TESTRPM, fbits(100.0))
        e.put32(NPP, 2 if mono else 1)
        e.put32(WTS, 0)
        e.put32(WTE, 0)

        # The drive trains' vtable: GetState at slot 24.
        self.dtvt = e.alloc(64, 16)
        e.mem[self.dtvt:self.dtvt + 64] = b"\0" * 64
        a = e.alloc(16)
        e.stub(a, self.dt_state)
        e.put32(self.dtvt + 28, a)

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
        e.stub(0x00273388, self.b_lock)
        e.stub(0x00277a18, self.region)
        e.stub(0x002778f8, self.bsupdate)
        e.stub(0x00277dc0, self.catvolume)
        e.stub(0x002719b8, self.rsample)
        e.stub(0x001ae280, self.ingame)
        e.stub(0x001af9c0, self.randf)
        e.stub(0x001afa10, self.audio_mode)
        e.stub(0x002577c0, self.malloc)
        e.stub(0x00114e98, self.delete)
        e.stub(0x00257850, self.delete)
        e.stub(0x00250f38, self.ticker)
        e.stub(0x00250f48, self.tickdiff)
        e.stub(0x00254908, self.getfile)
        e.stub(0x00107c90, self.getview)
        e.stub(0x001369a8, self.replay_demo)

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
        for i, (p, tag) in enumerate(self.allocs):
            if a == p:
                return "m%d" % i
            if tag == "PlayerEngineSound":
                if a == p + 48:
                    return "m%d.ns" % i
                if a == p + 236:
                    return "m%d.nl" % i
                for j in range(16):
                    if a == p + P_LEFT + VOICE * j + 12:
                        return "m%d.l%d" % (i, j)
                    if a == p + P_RIGHT + VOICE * j + 12:
                        return "m%d.r%d" % (i, j)
            if tag == "AIEngineSound":
                if a == p + 36:
                    return "m%d.s" % i
                if a == p + 236:
                    return "m%d.avg" % i
        for (nm, ingame), p in self.srcs.items():
            if a == p:
                return ("src:" if ingame else "rs:") + nm
        for nm, p in self.regs.items():
            if a == p:
                return "reg:" + nm
        for i, p in enumerate(self.files):
            if a == p:
                return "f%d" % i
        for k in sorted(self.cars):
            c = self.cars[k]
            if a == c:
                return "car%d" % k
            if a == c + 96:
                return "car%d.pos" % k
        return "?"

    def vtname(self, v):
        return {VT_PLAYER: "player", VT_AI: "ai",
                VT_S3D: "s3d"}.get(v, "?")

    # ---- Sound3d and the drive train

    def camrel(self, em):
        self.emit("  camrel %s pos=%s" % (self.name(em.reg[4]),
                                          self.name(em.reg[5])))
        return 0

    def dt_state(self, em):
        d = em.reg[4] & M32
        for k, p in self.dts.items():
            if d == p:
                self.emit("  dtstate dt%d" % k)
                return self.dtstates[k]
        self.emit("  dtstate ?")
        return self.dtstates.get(0, 0)

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
        self.emit("  bcat %s %d" % (self.name(em.reg[4]), em.reg[5] & M32))
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

    def b_lock(self, em):
        self.emit("  block %s" % self.name(em.reg[4]))
        return 0

    # ---- bSound, the regions and the game's samples

    def check_bsound(self, em, what):
        if em.reg[4] & M32 != self.bsound:
            self.emit("  %s: not bSound's" % what)

    def region(self, em):
        nm = self.cstr(em.reg[5] & M32)
        self.emit("  region %s" % nm)
        self.check_bsound(em, "region")
        if nm not in self.regs:
            self.regs[nm] = self.e.alloc(16)
        return self.regs[nm]

    def bsupdate(self, em):
        self.emit("  bsupdate")
        self.check_bsound(em, "update")
        return 0

    def catvolume(self, em):
        self.emit("  catvol %d -> %08x" % (em.reg[5] & M32, self.catvol))
        self.check_bsound(em, "catvol")
        em.fpr[0] = self.catvol
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

    def audio_mode(self, em):
        return 0 if self.mono else self.am

    # ---- the heap and the rest

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

    def ticker(self, em):
        v = self.tick
        self.tick = (self.tick + self.step) & M32
        self.emit("  ticker -> %d" % v)
        return v

    def tickdiff(self, em):
        a, b = em.reg[4] & M32, em.reg[5] & M32
        d = fbits(float((b - a) & M32))
        self.emit("  tickdiff %d %d -> %08x" % (a, b, d))
        em.fpr[0] = d
        return 0

    def getfile(self, em):
        e = self.e
        nm = self.cstr(em.reg[4] & M32)
        base = nm.split("\\")[-1].upper()
        data = (SOUND_DIR / base).read_bytes()
        p = e.alloc(len(data), 16)
        e.write(p, data)
        self.files.append(p)
        self.emit("  getfile %s %s %d -> f%d" % (
            nm, "size" if em.reg[5] & M32 else "0", s32(em.reg[6]),
            len(self.files) - 1))
        return p

    def getview(self, em):
        v = s32(em.reg[4])
        self.emit("  view %d" % v)
        return self.views + 64 * v

    def replay_demo(self, em):
        self.emit("  rdm %s -> %d" % (
            "rc" if em.reg[4] & M32 == self.rc else "?", self.rdm))
        return self.rdm

    # ---- the dumps

    def field(self, a, t):
        v = struct.unpack_from(PACK[t], self.e.mem, a)[0]
        return "%08x" % v if t == "f" else "%d" % v

    def dump_player(self, k):
        e = self.e
        u = e.u32
        s = self.snds[k]
        line = "  pd %s vt=%s car=%s" % (self.name(s), self.vtname(u(s + 28)),
                                        self.name(u(s + 32)))
        for nm, off, t in PFIELDS:
            line += " %s=%s" % (nm, self.field(s + off, t))
        self.emit(line + " sync=%08x" % u(self.cars[k] + 980))
        for label, base in (("left", P_LEFT), ("right", P_RIGHT)):
            line = "  " + label
            for i in range(16):
                v = s + base + VOICE * i
                line += " %d/%d/%08x/%d" % (s16(e.u16(v)), s16(e.u16(v + 2)),
                                            u(v + 4), e.u16(v + 8))
            self.emit(line)
        self.emit("  delay" + "".join(
            " %s" % self.field(s + P_DELAY + i, "b") for i in range(16)))
        line = "  es"
        for i in range(12):
            q = s + P_ES + ES * i
            line += " %d/%d/%d/%s/%d/%08x" % (
                s32(u(q)), s16(e.u16(q + 4)), s16(e.u16(q + 6)),
                self.name(u(q + 8)), s32(u(q + 12)), u(q + 16))
        self.emit(line)
        self.emit("  defs %s %s" % (self.name(u(s + P_DEFS)),
                                    self.name(u(s + P_DEFS + 4))))

    def dump_ai(self, k):
        u = self.e.u32
        s = self.snds[k]
        line = "  ad %s vt=%s car=%s" % (self.name(s), self.vtname(u(s + 28)),
                                        self.name(u(s + 32)))
        for nm, off, t in AFIELDS:
            line += " %s=%s" % (nm, self.field(s + off, t))
        data = u(s + 248)
        self.emit(line + " data=%s" % self.name(data))
        self.emit("  avg" + "".join(" %08x" % u(data + 4 * i)
                                    for i in range(20)))

    def dump_tables(self):
        e = self.e
        for label, vt in VT_TABLES:
            self.emit("  vt %s %d entries" % (label, VT_ENTRIES))
            for k in range(1, VT_ENTRIES):
                d = s16(e.u16(vt + 8 * k))
                fn = e.u32(vt + 8 * k + 4)
                self.emit("  vt %s %d %d %s" % (label, 8 * k, d,
                                                FNAME.get(fn, "?")))

    def table(self, d, a):
        """Slot a's volumes: retail's ResolveTables has made the field an
        address; before it, it is an offset from the field."""
        f = d + 296 + 4 * a
        v = self.e.u32(f)
        if d <= v < d + 6504:
            return v
        return (f + s32(v)) & M32

    def dump_def(self, d):
        e = self.e
        self.emit("  def id=%08x ver=%d res=%d pn=%s" % (
            e.u32(d), s32(e.mem[d + 4] << 24) >> 24,
            s32(e.mem[d + 5] << 24) >> 24,
            ",".join("%d" % struct.unpack_from("<b", e.mem, d + 32 + a)[0]
                     for a in range(8))))
        for a in range(8):
            if struct.unpack_from("<b", e.mem, d + 32 + a)[0] < 0:
                self.emit("  vt%d -" % a)
                continue
            t = self.table(d, a)
            self.emit("  vt%d" % a + "".join(
                " %d" % struct.unpack_from("<b", e.mem, t + lvl)[0]
                for lvl in range(0, 441, 20)))

    # ---- the cars

    def new_car(self, k, usage, aieng, view, pov):
        e = self.e
        c = self.cars[k] = e.alloc(CAR_SIZE, 16)
        e.mem[c:c + CAR_SIZE] = b"\xa5" * CAR_SIZE
        m = e.alloc(256, 16)
        e.mem[m:m + 256] = b"\xa5" * 256
        d = self.dts[k] = e.alloc(256, 16)
        e.mem[d:d + 256] = b"\xa5" * 256
        t = self.types[k] = e.alloc(1400, 16)
        e.mem[t:t + 1400] = b"\0" * 1400
        e.write(t + 816, b"Car%d\0" % k)
        e.write(t + 854, b"P%d\0" % k)
        struct.pack_into("<H", e.mem, t + 852, aieng & 0xffff)
        ride = e.alloc(16, 16)
        e.mem[ride:ride + 16] = b"\0" * 16
        e.put32(ride, k)
        r = self.cti + CTI_SIZE * k
        e.mem[r:r + CTI_SIZE] = b"\0" * CTI_SIZE
        e.put32(r + 1336, usage)
        p = self.players[k] = e.alloc(160, 16)
        e.mem[p:p + 160] = b"\0" * 160
        e.put32(p + 24, view)
        e.mem[p + 36] = pov & 0xff
        g = self.engines[k] = e.alloc(128, 16)
        e.mem[g:g + 128] = b"\0" * 128
        ei = self.infos[k] = e.alloc(64, 16)
        e.mem[ei:ei + 64] = b"\0" * 64
        st = self.dtstates[k] = e.alloc(16, 16)
        e.mem[st:st + 16] = b"\0" * 16
        e.put32(g + 16, ei)
        e.put32(m + 68, d)
        e.put32(d + 8, self.dtvt)
        e.put32(d + 20, g)
        e.put32(d + 44, 2)
        e.put32(d + 48, 2)
        e.put32(d + 56, 3)
        e.put32(c + 12, t)
        e.put32(c + 16, ride)
        e.put32(c + 24, p)
        e.put32(c + 36, 1)
        e.put32(c + 48, m)
        for j in range(4):
            e.put32(c + 96 + 4 * j, 0)
        e.put32(c + 144, fbits(1.0))
        for j in range(1, 4):
            e.put32(c + 144 + 4 * j, 0)
        e.put32(c + 964, 0)
        e.put32(c + 968, 2)
        e.put32(c + 972, 0)
        e.put32(c + 976, fbits(1000.0))
        e.put32(c + 980, 0)

    # ---- the ops

    def call(self, name, *args):
        return self.e.call(F[name], *args, limit=LIMIT)

    def voice(self, k, side, i):
        base = P_RIGHT if side[0] == "r" else P_LEFT
        return self.snds[k] + base + VOICE * i

    def sample_ref(self, k, w):
        s = self.snds[k]
        if w == "ns":
            return s + 48
        if w == "nl":
            return s + 236
        if w == "s":
            return s + 36
        return self.voice(k, w, int(w[1:])) + 12

    def set_field(self, base, fields, nm, v):
        for fn, off, t in fields:
            if fn != nm:
                continue
            if t == "f":
                self.e.put32(base + off, int(v, 16))
            else:
                x = int(v, 0)
                size = struct.calcsize(PACK[t])
                struct.pack_into("<%s" % {1: "B", 2: "H", 4: "I"}[size],
                                 self.e.mem, base + off,
                                 x & ((1 << (8 * size)) - 1))
            return
        self.emit("  no field %s" % nm)

    def op(self, f):
        e = self.e
        u = e.u32

        def i(k):
            return int(f[k], 0) if k < len(f) else 0

        def fb(k):
            return int(f[k], 16) & M32 if k < len(f) else 0

        def snd(k):
            return self.snds[i(k)]

        def defn(k, d):
            return u(self.snds[k] + P_DEFS + 4 * d)

        o = f[0]
        if o == "tables":
            self.dump_tables()
        elif o == "se":
            e.put32(SE, i(1))
        elif o == "cse":
            e.put32(CSE, i(1))
        elif o == "npp":
            # Mono: never one player, so no right voice is locked.
            e.put32(NPP, 2 if self.mono and i(1) == 1 else i(1))
        elif o == "trpm":
            e.put32(TESTRPM, fb(1))
        elif o == "wts":
            e.put32(WTS, fb(1))
        elif o == "wte":
            e.put32(WTE, fb(1))
        elif o == "am":
            self.am = i(1)
        elif o == "rcs":
            e.put32(self.rc, i(1))
        elif o == "rdm":
            self.rdm = i(1)
        elif o == "race":
            if i(1) < 0:
                e.put32(PRACE, 0)
            else:
                e.put32(self.race, i(1))
                e.put32(PRACE, self.race)
        elif o == "catvol":
            self.catvol = fb(1)
        elif o == "rf":
            self.rf.append(fb(1))
        elif o == "tick":
            self.step = i(1)
        elif o == "missing":
            self.missing.add(f[1])
        elif o == "nosrc":
            self.nosrc.add(f[1])
        elif o == "car":
            self.new_car(i(1), i(2), i(3), i(4), i(5))
        elif o == "snd":
            t = self.types[i(1)]
            struct.pack_into("<h", e.mem, t + 862, i(2))
            for j in range(4):
                e.mem[t + 864 + j] = i(3 + j) & 0xff
            struct.pack_into("<h", e.mem, t + 868, i(7))
            struct.pack_into("<h", e.mem, t + 870, i(8))
            struct.pack_into("<h", e.mem, t + 944, i(9))
            struct.pack_into("<h", e.mem, t + 946, i(10))
        elif o == "det":
            t = self.types[i(1)]
            for j in range(12):
                struct.pack_into("<h", e.mem, t + 872 + 2 * j, i(2 + j))
        elif o == "vols":
            t = self.types[i(1)]
            for j in range(12):
                e.put32(t + 896 + 4 * j, fb(2 + j))
        elif o == "tinfo":
            t = self.types[i(1)]
            e.put32(t + 696, fb(2))
            e.put32(t + 648, i(3))
        elif o == "mode":
            e.put32(self.cars[i(1)] + 36, i(2))
        elif o == "st":
            c = self.cars[i(1)]
            e.put32(c + 964, fb(2))
            e.put32(c + 968, i(3))
            e.put32(c + 972, fb(4))
            e.put32(c + 976, fb(5))
        elif o == "pos":
            c = self.cars[i(1)]
            for j in range(3):
                e.put32(c + 96 + 4 * j, fb(2 + j))
        elif o == "bm":
            c = self.cars[i(1)]
            for j in range(3):
                e.put32(c + 144 + 4 * j, fb(2 + j))
        elif o == "dt":
            d = self.dts[i(1)]
            e.put32(d + 48, i(2))
            e.put32(d + 44, i(3))
            e.put32(d + 56, i(4))
            e.put32(self.dtstates[i(1)], fb(5))
        elif o == "shift":
            e.put32(self.dts[i(1)] + 76 + 4 * i(2), fb(3))
        elif o == "einfo":
            e.put32(self.infos[i(1)] + 4, fb(2))
            e.put32(self.infos[i(1)] + 8, fb(3))
        elif o == "nitro":
            e.put32(self.engines[i(1)] + 80, i(2))
            e.put32(self.engines[i(1)] + 84, fb(3))
        elif o == "cam":
            v = self.views + 64 * i(1)
            c = self.cams + 128 * i(1)
            e.put32(v + 56, c)
            for j in range(3):
                e.put32(c + 64 + 4 * j, fb(2 + j))
                e.put32(c + 80 + 4 * j, fb(5 + j))
        elif o == "view":
            e.put32(self.players[i(1)] + 24, i(2))
        elif o == "pov":
            e.mem[self.players[i(1)] + 36] = i(2) & 0xff
        elif o == "mk":
            k = i(1)
            fn = "mkplayer" if f[2] == "player" else "mkai"
            self.snds[k] = self.call(fn, self.cars[k]) & M32
            self.emit("  -> %s" % self.name(self.snds[k]))
        elif o == "lpes":
            self.emit("  last %s" % self.name(u(LPES)))
        elif o == "vc":
            self.vcall(f, i, fb)
        elif o == "ramp":
            self.call("ramp", snd(1))
        elif o == "gear":
            self.call("gear", snd(1))
        elif o == "redline":
            e.put32(self.scratch, fb(2))
            self.call("redline", snd(1), self.scratch)
            self.emit("  = %08x" % u(self.scratch))
        elif o == "nitroe":
            e.fpr[12] = fb(2)
            e.fpr[13] = fb(4)
            self.call("nitro", snd(1), i(3) & 0xffff)
        elif o == "ducker":
            self.call("ducker", snd(1))
        elif o == "ueng":
            self.call("ueng", snd(1))
        elif o == "setc":
            e.fpr[12] = fb(8)
            self.call("set", snd(1), i(2), i(3), i(4), i(5), i(6), i(7),
                      i(9))
        elif o == "resolve":
            self.call("resolve", snd(1))
        elif o == "init":
            self.call("init", snd(1))
        elif o == "vplay":
            q = self.scratch
            struct.pack_into("<hhIHH", e.mem, q, i(4), i(5), fb(6),
                             i(7) & 0xffff, i(8) & 0xffff)
            self.call("vplay", self.voice(i(1), f[2], i(3)), q)
        elif o == "vstop":
            self.call("vstop", self.voice(i(1), f[2], i(3)))
        elif o == "vvol":
            self.call("vvol", self.voice(i(1), f[2], i(3)), i(4))
        elif o == "vpitch":
            e.fpr[12] = fb(4)
            self.call("vpitch", self.voice(i(1), f[2], i(3)))
        elif o == "vaz":
            self.call("vaz", self.voice(i(1), f[2], i(3)), i(4) & 0xffff)
        elif o == "vset":
            v = self.voice(i(1), f[2], i(3))
            struct.pack_into("<hhIH", e.mem, v, i(4), i(5), fb(6),
                             i(7) & 0xffff)
        elif o == "pset":
            self.set_field(snd(1), PFIELDS, f[2], f[3])
        elif o == "aset":
            self.set_field(snd(1), AFIELDS, f[2], f[3])
        elif o == "delay":
            e.mem[snd(1) + P_DELAY + i(2)] = i(3) & 0xff
        elif o == "es":
            q = snd(1) + P_ES + ES * i(2)
            e.put32(q, i(3))
            struct.pack_into("<hh", e.mem, q + 4, i(4), i(5))
            e.put32(q + 12, i(6))
            e.put32(q + 16, fb(7))
        elif o == "pcar":
            e.put32(snd(1) + 32, self.cars[i(1)] if i(2) else 0)
        elif o == "tpatch":
            e.mem[defn(i(1), i(2)) + 32 + i(3)] = i(4) & 0xff
        elif o == "tres":
            e.mem[defn(i(1), i(2)) + 5] = i(3) & 0xff
        elif o == "tvol":
            d = defn(i(1), i(2))
            e.mem[self.table(d, i(3)) + i(4)] = i(5) & 0xff
        elif o == "tdump":
            self.dump_def(defn(i(1), i(2)))
        elif o == "bplaying":
            b = self.sample_ref(i(1), f[2])
            if i(3):
                self.playing.add(b)
            else:
                self.playing.discard(b)
        elif o == "cv":
            e.put32(snd(1) + 36 + 24, fb(2))
        elif o == "aname":
            self.emit("  -> %s" % self.cstr(self.call("aname", snd(1))
                                            & M32))
        elif o == "arpm":
            self.call("arpm", snd(1))
            self.emit("  = %08x" % e.fpr[0])
        elif o == "astart":
            self.call("astart", snd(1))
            self.emit("  = %08x" % e.fpr[0])
        elif o == "acar":
            e.put32(snd(1) + 32, self.cars[i(2)])
        elif o == "pd":
            self.dump_player(i(1))
        elif o == "ad":
            self.dump_ai(i(1))
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
        elif slot in (40, 48):
            e.call(fn, this, limit=LIMIT)
        elif slot == 56:
            e.call(fn, this, self.cars[i(3)] + 96, limit=LIMIT)
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


def model(lines, mono=False):
    m = Model(mono)
    out = m.run(lines)
    return out, m.e


# ================================================================ script

def script():
    L = []
    a = L.append

    def fl(*xs):
        return "|".join(fx(x) for x in xs)

    def upd(k, vol, az, pitch):
        a("vc|%d|24|%s|%d|%s" % (k, fx(vol), az, fx(pitch)))

    def st(k, vel, gear, thr, rpm):
        a("st|%d|%s|%d|%s" % (k, fx(vel), gear, fl(thr, rpm)))

    def player_type(k):
        a("snd|%d|100|20|40|-30|127|200|-100|300|150" % k)
        a("det|%d|0|5|-5|10|-10|15|-15|20|-20|25|-25|30" % k)
        a("vols|%d|%s" % (k, fl(1.0, 0.9, 0.8, 0.7, 1.1, 1.2, 0.6, 0.5,
                                 1.0, 0.95, 0.85, 0.75)))
        a("tinfo|%d|%s|5" % (k, fx(7000.0)))
        a("einfo|%d|%s" % (k, fl(6500.0, 7500.0)))
        for j, v in enumerate((0.0, 0.0, 5000.0, 5500.0, 6000.0, 6200.0,
                               6400.0, 7000.0, 6800.0)):
            a("shift|%d|%d|%s" % (k, j, fx(v)))

    a("tables")
    a("cam|0|%s" % fl(0.0, 0.0, 0.0, 0.0, 0.0, 1.0))
    a("cam|1|%s" % fl(3.0, 4.0, 0.0, 0.5, 0.0, 0.0))
    a("am|1")

    # ---- the player's engine
    a("car|0|0|1|0|0")
    player_type(0)
    a("mk|0|player")
    a("pd|0")
    a("lpes")
    a("tdump|0|0")
    a("tdump|0|1")

    # ---- VoiceAttr
    a("vplay|0|l|0|100|64|%s|1000|0" % fx(0.25))
    a("vplay|0|l|1|-5|64|%s|0|0" % fx(-0.5))
    a("se|0")
    a("vplay|0|r|2|50|64|%s|200|0" % fx(0.1))
    a("se|1")
    a("cse|0")
    a("vplay|0|r|3|50|64|%s|300|0" % fx(0.1))
    a("cse|1")
    a("vvol|0|l|0|100")
    a("vvol|0|l|0|50")
    a("vvol|0|l|0|50")
    a("vvol|0|l|0|80")
    a("vvol|0|l|0|300")
    a("vset|0|l|4|10|0|0|0")
    a("vvol|0|l|4|-30")
    a("vvol|0|l|4|0")
    a("vstop|0|l|4")
    a("vset|0|l|5|20|0|0|0")
    a("vstop|0|l|5")
    a("vstop|0|l|5")
    a("vpitch|0|l|0|%s" % fx(0.25))
    a("vpitch|0|l|0|%s" % fx(0.3))
    a("vpitch|0|l|0|%s" % fx(-0.0))
    a("vaz|0|l|0|1000")
    a("vaz|0|l|0|2000")
    a("vaz|0|l|0|65535")
    a("pd|0")

    # ---- RampThrottle
    for thr in (1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.25, 0.0, 0.0,
                0.0, 0.0, 0.0, 0.0, 1.5, 1.5):
        st(0, 0.0, 2, thr, 1000.0)
        a("ramp|0")
        a("pd|0")
    a("pset|0|thr|300")
    st(0, 0.0, 2, 1.0, 1000.0)
    a("ramp|0")
    a("pd|0")
    a("pset|0|thr|-20")
    st(0, 0.0, 2, -0.5, 1000.0)
    a("ramp|0")
    a("pd|0")
    a("pset|0|thr|-20")
    st(0, 0.0, 2, 0.0, 1000.0)
    a("ramp|0")
    a("pd|0")
    a("pset|0|thr|12")
    st(0, 0.0, 2, 0.0, 1000.0)
    a("ramp|0")
    a("pd|0")
    # Level with the pedal near either end, and down to just under 9.
    for cur, thr in ((254, 254.5 / 255.0), (5, 5.5 / 255.0), (9, 0.0)):
        a("pset|0|thr|%d" % cur)
        st(0, 0.0, 2, thr, 1000.0)
        a("ramp|0")
        a("pd|0")

    # ---- UpdateGearShiftEffect
    st(0, 10.0, 2, 1.0, 3000.0)
    a("dt|0|2|3|0|%s" % fx(0.7))
    a("gear|0")
    a("gear|0")
    a("pd|0")
    a("dt|0|3|3|2|%s" % fx(0.2))
    a("gear|0")
    a("gear|0")
    a("pd|0")
    a("dt|0|3|3|1|%s" % fx(0.2))
    a("gear|0")
    a("dt|0|3|3|3|%s" % fx(0.2))
    a("gear|0")
    a("pd|0")
    a("dt|0|4|3|0|%s" % fx(0.5))
    a("gear|0")
    a("pd|0")
    a("dt|0|3|4|0|%s" % fx(0.5))
    st(0, 10.0, 2, 1.0, 1500.0)
    a("gear|0")
    a("pd|0")
    st(0, 10.0, 2, 1.0, 1500.5)
    a("gear|0")
    a("pd|0")
    st(0, 10.0, 2, 1.0, 1000.0)
    a("trpm|" + fx(2000.0))
    a("gear|0")
    a("pd|0")
    a("trpm|" + fx(1000.0))
    st(0, 10.0, 2, 1.0, 3000.0)
    a("gear|0")
    a("pd|0")
    a("trpm|" + fx(100.0))
    a("mode|0|2")
    a("gear|0")
    a("mode|0|1")
    a("pcar|0|0")
    a("gear|0")
    a("pcar|0|1")
    a("dt|0|2|2|3|0")
    for _ in range(4):
        a("gear|0")
    a("pd|0")
    # The gears level, not shifting up, the clutch moving: no duck.
    a("pset|0|gsup|0")
    st(0, 10.0, 3, 1.0, 3000.0)
    a("dt|0|3|3|0|%s" % fx(0.5))
    a("gear|0")
    a("pd|0")

    # ---- UpdateToRedLineRPM
    for gear in (0, 1, 2, 3, 6, 7):
        a("dt|0|%d|%d|3|0" % (gear, gear))
        a("redline|0|" + fx(5000.0))
        a("pd|0")
    a("dt|0|4|4|3|0")
    for sgear in (5, 6, 7):
        st(0, 10.0, sgear, 1.0, 3000.0)
        a("redline|0|" + fx(5000.0))
    a("redline|0|" + fx(9000.0))
    a("redline|0|" + fx(-50.0))
    a("dt|0|7|7|3|0")
    a("redline|0|" + fx(9000.0))
    a("dt|0|3|3|3|0")
    a("mode|0|3")
    a("redline|0|" + fx(4321.0))
    a("pd|0")
    a("mode|0|1")
    a("dt|0|3|3|3|0")
    st(0, 10.0, 3, 0.0, 3000.0)

    # ---- UpdateNitroEffect
    a("nitro|0|0|0")
    a("nitroe|0|%s|1000|%s" % (fx(1.0), fx(1.0)))
    a("nitro|0|1|" + fx(10.0))
    a("wts|" + fx(10.0))
    a("nitroe|0|%s|1000|%s" % (fx(0.8), fx(1.1)))
    for t in (12.0, 13.2, 13.4, 14.0, 15.0):
        a("wts|" + fx(t))
        a("nitroe|0|%s|2000|%s" % (fx(0.8), fx(1.1)))
    a("mode|0|2")
    a("nitroe|0|%s|2000|%s" % (fx(0.8), fx(1.1)))
    a("mode|0|1")
    a("pcar|0|0")
    a("nitroe|0|%s|2000|%s" % (fx(0.8), fx(1.1)))
    a("pcar|0|1")
    a("nitro|0|0|0")
    a("nitroe|0|%s|2000|%s" % (fx(0.8), fx(1.1)))
    a("nitroe|0|%s|2000|%s" % (fx(0.8), fx(1.1)))
    a("wts|0")

    # ---- UpdateEngineDucker
    a("ducker|0")
    a("catvol|" + fx(0.05))
    a("ducker|0")
    a("catvol|" + fx(0.5))
    a("wte|" + fx(2.0))
    st(0, 10.0, 3, 0.2, 3000.0)
    a("pset|0|dscale|" + fx(0.9))
    a("pset|0|dtime|" + fx(3.0))
    a("ducker|0")
    a("pd|0")
    a("pset|0|dscale|" + fx(0.995))
    a("ducker|0")
    a("pd|0")
    for thr in (0.5, 0.75, 0.9, 1.0, 1.0):
        st(0, 10.0, 3, thr, 3000.0)
        a("ducker|0")
        a("pd|0")
    a("pset|0|dscale|" + fx(0.755))
    a("ducker|0")
    a("pd|0")
    st(0, 10.0, 3, 0.49, 3000.0)
    a("ducker|0")
    a("pd|0")
    # Four and a half seconds on: not yet.
    st(0, 10.0, 3, 0.6, 3000.0)
    a("pset|0|dscale|" + fx(0.9))
    a("pset|0|dtime|" + fx(2.5))
    a("ducker|0")
    a("pd|0")
    # The music over 0.05 and under 0.1.
    a("catvol|" + fx(0.07))
    st(0, 10.0, 3, 0.2, 3000.0)
    a("pset|0|dtime|" + fx(3.0))
    a("ducker|0")
    a("pd|0")
    a("wte|" + fx(1.0 / 30.0))
    a("catvol|0")

    # ---- UpdateEngine
    a("pset|0|vol|100")
    a("pset|0|ratio|64")
    a("pset|0|timbre|40")
    a("pset|0|clt|200")
    a("pset|0|azim|1000")
    a("pset|0|sep|8000")
    a("pset|0|stereo|1")
    a("pset|0|gsvs|" + fx(1.0))
    a("pset|0|dscale|" + fx(1.0))
    for _ in range(5):
        a("ueng|0")
        a("pd|0")
    a("pset|0|clt|30")
    a("ueng|0")
    a("pd|0")
    a("pset|0|clt|440")
    for _ in range(3):
        a("ueng|0")
    a("pd|0")
    a("pset|0|ratio|0")
    a("ueng|0")
    a("pd|0")
    a("pset|0|ratio|127")
    a("ueng|0")
    a("pd|0")
    a("pset|0|ratio|64")
    for tim in (127, 0, -20, -100, 100, -124, -128, 124, -10):
        a("pset|0|timbre|%d" % tim)
        a("ueng|0")
        a("pd|0")
    # Full volume and throttle, so the e/x crossfade's quiet end shows
    # on an "e" patch once the voices settle.
    a("tvol|0|1|0|440|127")
    a("pset|0|vol|127")
    a("pset|0|ratio|127")
    for tim in (124, -10):
        a("pset|0|timbre|%d" % tim)
        for _ in range(10):
            a("ueng|0")
        a("pd|0")
    a("pset|0|vol|100")
    a("pset|0|ratio|64")
    a("pset|0|timbre|40")
    # The throttle's crossfade at 124, both scales off 1.
    a("pset|0|ratio|124")
    a("pset|0|gsvs|" + fx(0.5))
    a("pset|0|dscale|" + fx(0.8))
    a("ueng|0")
    a("pd|0")
    a("pset|0|dscale|" + fx(1.0))
    # 128 after the boost, capped.
    a("tvol|0|1|0|300|127")
    a("pset|0|clt|300")
    a("pset|0|vol|105")
    a("pset|0|ratio|127")
    for _ in range(10):
        a("ueng|0")
    a("pd|0")
    # A table below 0: the shifts round down. A patch volume below 0
    # makes the result heard; the voices step 15 a frame, so settle.
    a("tvol|0|1|1|300|-50")
    a("pset|0|vol|100")
    a("pset|0|ratio|64")
    a("es|0|1|1|0|1|5|" + fx(-1.0))
    for _ in range(10):
        a("ueng|0")
    a("pd|0")
    a("pset|0|clt|200")
    # A disabled patch's right voice does not start.
    a("tvol|0|1|1|200|100")
    a("es|0|1|1|0|0|5|" + fx(1.0))
    a("bplaying|0|l1|1")
    a("bplaying|0|r1|0")
    a("delay|0|1|0")
    a("ueng|0")
    a("pd|0")
    a("es|0|1|1|0|1|5|" + fx(1.0))
    # In mono the delay counts on, past -128.
    a("tvol|0|1|2|200|100")
    a("bplaying|0|l2|1")
    a("pset|0|stereo|0")
    a("delay|0|2|-128")
    a("ueng|0")
    a("pd|0")
    a("pset|0|stereo|1")
    a("pset|0|vol|300")
    a("ueng|0")
    a("pd|0")
    a("pset|0|vol|100")
    a("pset|0|mode|0")
    a("ueng|0")
    a("pd|0")
    a("pset|0|mode|1")
    a("pset|0|clt|200")
    a("es|0|1|1|0|0|5|" + fx(1.0))
    a("es|0|7|-1|0|1|-15|" + fx(1.0))
    a("ueng|0")
    a("pd|0")
    a("bplaying|0|l1|0")
    a("ueng|0")
    a("bplaying|0|l1|1")
    a("bplaying|0|r1|1")
    a("ueng|0")
    a("pd|0")
    a("es|0|1|1|0|1|5|" + fx(-0.5))
    a("es|0|7|1|0|1|-15|" + fx(1.0))
    a("ueng|0")
    a("pd|0")
    a("pset|0|stereo|0")
    a("delay|0|2|-128")
    a("delay|0|8|1")
    a("ueng|0")
    a("pd|0")
    a("pset|0|stereo|1")
    a("delay|0|2|-128")
    for j in range(12):
        a("bplaying|0|r%d|0" % j)
    a("ueng|0")
    a("pd|0")
    a("tvol|0|1|0|200|0")
    a("tvol|0|0|1|200|127")
    a("tpatch|0|1|2|-1")
    a("ueng|0")
    a("pd|0")
    a("tdump|0|0")
    a("tdump|0|1")
    a("tpatch|0|1|2|2")
    a("tpatch|0|1|1|-1")
    a("resolve|0")
    a("pd|0")
    a("tpatch|0|1|1|1")
    a("tpatch|0|0|0|-1")
    a("tpatch|0|1|1|-1")
    a("resolve|0")
    a("pd|0")
    a("tpatch|0|0|0|6")
    a("tpatch|0|1|1|1")
    a("tres|0|0|0")
    a("tdump|0|0")
    a("tres|0|0|1")
    a("resolve|0")
    a("tdump|0|0")
    # Patch 0 in the slot the test reads.
    a("tpatch|0|1|1|0")
    a("resolve|0")
    a("pd|0")
    a("tpatch|0|1|1|1")
    a("resolve|0")
    a("pset|0|hp|5")
    a("ueng|0")
    a("pset|0|hp|16")
    for j in range(16):
        a("bplaying|0|l%d|0" % j)
        a("bplaying|0|r%d|0" % j)

    # ---- Set
    a("setc|0|100|200|255|0|65536|0|0|0")
    a("pd|0")
    a("setc|0|50|440|3|7|-16|5|0|1")
    a("pd|0")
    a("setc|0|50|10|100|0|0|0|%s|-1" % fx(0.5))
    a("pd|0")
    for facing in (-0.5, 2.0, -3.0, 0.0, 1.0, -1.0):
        a("setc|0|50|10|4|0|0|0|%s|-1" % fx(facing))
        a("pd|0")
    for pov in (2, 3):
        a("setc|0|50|10|4|0|0|0|0|%d" % pov)
        a("pd|0")
    a("setc|0|127|0|130|0|1048575|0|0|0")
    a("pd|0")

    # ---- Update, through the vtable
    a("catvol|" + fx(0.5))
    a("pos|0|%s" % fl(3.0, 4.0, 0.0))
    a("rcs|3")
    a("dt|0|3|3|3|0")
    st(0, 10.0, 3, 0.8, 4000.0)
    for _ in range(4):
        upd(0, 0.9, 0, 1.0)
        a("pd|0")
    a("am|2")
    upd(0, 0.9, 0, 1.0)
    a("pd|0")
    a("am|0")
    upd(0, 0.9, 0, 1.0)
    a("pd|0")
    a("am|1")
    upd(0, 0.9, 5000, 1.0)
    a("pd|0")
    upd(0, 0.5, 0, 1.25)
    a("pd|0")
    a("cam|0|%s" % fl(0.0, 0.0, 0.0, 0.5, 0.0, 0.0))
    a("bm|0|%s" % fl(1.0, 0.0, 0.0))
    for rcs in (4, 7, 5, 0, 1, 2, 6, 8, 9):
        a("rcs|%d" % rcs)
        upd(0, 0.9, 0, 1.0)
        a("pd|0")
    a("rcs|4")
    a("cam|0|%s" % fl(0.0, 0.0, 0.0, 0.5, 0.0, 0.5))
    a("bm|0|%s" % fl(0.6, 0.0, 0.8))
    upd(0, 0.9, 0, 1.0)
    a("pd|0")
    a("cam|0|%s" % fl(0.0, 0.0, 0.0, 0.5, 0.0, 0.0))
    a("bm|0|%s" % fl(1.0, 0.0, 0.0))
    a("rcs|3")
    a("rdm|1")
    a("bm|0|%s" % fl(-1.0, 0.0, 0.0))
    upd(0, 0.9, 0, 1.0)
    a("pd|0")
    a("rdm|0")
    a("bm|0|%s" % fl(1.0, 0.0, 0.0))
    a("view|0|1")
    upd(0, 0.9, 0, 1.0)
    a("view|0|0")
    for pov in (1, 2, 3):
        a("pov|0|%d" % pov)
        upd(0, 0.9, 0, 1.0)
        a("pd|0")
    a("pov|0|0")
    a("trpm|" + fx(6000.0))
    upd(0, 0.9, 0, 1.0)
    a("pd|0")
    a("trpm|" + fx(100.0))
    st(0, 30.0, 6, 1.0, 8000.0)
    a("dt|0|7|7|3|0")
    for _ in range(14):
        upd(0, 1.0, 0, 1.0)
    a("pd|0")
    st(0, 10.0, 3, 0.0, 1200.0)
    a("dt|0|3|3|3|0")
    for _ in range(3):
        upd(0, 1.0, 0, 0.75)
    a("pd|0")
    a("nitro|0|1|0")
    upd(0, 1.0, 3000, 1.0)
    upd(0, 1.0, 3000, 1.0)
    a("nitro|0|0|0")
    upd(0, 1.0, 0, 1.0)
    a("vc|0|16|0")
    a("pd|0")
    upd(0, 1.0, 0, 1.0)
    a("vc|0|16|1")
    a("pd|0")
    a("se|0")
    upd(0, 1.0, 0, 1.0)
    a("se|1")
    a("cse|0")
    upd(0, 1.0, 0, 1.0)
    a("cse|1")
    a("vc|0|40")
    a("vc|0|48")
    a("vc|0|56|0")
    a("catvol|0")

    # ---- Mute
    a("vc|0|32|1")
    a("pd|0")
    a("vc|0|32|0")
    a("pd|0")
    a("vc|0|32|7")
    a("am|2")
    a("vc|0|32|0")
    a("pd|0")
    a("pset|0|mode|1")
    a("am|0")
    a("vc|0|32|0")
    a("pd|0")
    a("am|1")
    a("vc|0|32|1")
    a("pd|0")

    # ---- Init again, and the other players' engines
    a("init|0")
    a("pd|0")
    a("se|0")
    a("init|0")
    a("se|1")

    a("car|3|0|1|0|0")
    player_type(3)
    a("missing|P3lxlo")
    a("mk|3|player")
    a("pd|3")
    a("lpes")

    a("car|4|0|1|0|0")
    player_type(4)
    a("se|0")
    a("mk|4|player")
    a("se|1")
    a("pd|4")

    a("car|5|0|1|0|0")
    player_type(5)
    a("nosrc|NitroLoop")
    a("missing|MenuWrong")
    a("tick|1")
    a("npp|2")
    a("am|2")
    a("mk|5|player")
    a("pd|5")
    a("npp|1")
    a("tick|7")
    a("am|1")

    # ---- AIEngineSound
    a("rf|" + fx(0.1))
    a("car|1|0|3|0|-1")
    a("mk|1|ai")
    a("ad|1")
    a("aname|1")
    a("rf|" + fx(0.4))
    a("car|2|2|5|0|-1")
    a("mk|2|ai")
    a("ad|2")
    a("aname|2")
    a("car|6|1|65535|0|-1")
    a("mk|6|ai")
    a("aname|6")
    a("acar|6|1")
    a("aname|6")

    # ComputeRPMPitchShift
    st(1, 10.0, 2, 0.0, 3000.0)
    for _ in range(8):
        a("arpm|1")
        a("ad|1")
    st(1, 10.0, 2, 0.0, 3500.0)
    for _ in range(3):
        a("arpm|1")
    a("ad|1")
    st(1, 10.0, 3, 0.0, 2500.0)
    a("arpm|1")
    a("ad|1")
    a("trpm|" + fx(4000.0))
    a("arpm|1")
    st(1, 10.0, 4, 0.0, 2500.0)
    a("arpm|1")
    a("ad|1")
    a("trpm|" + fx(100.0))
    a("aset|1|frames|5")
    a("arpm|1")
    a("ad|1")
    for _ in range(20):
        a("arpm|1")
    a("ad|1")
    # A jump of more than 5000 once the gear has settled.
    st(1, 10.0, 5, 0.0, 9500.0)
    a("arpm|1")
    a("aset|1|frames|6")
    a("arpm|1")
    a("ad|1")

    # ComputeStartLineRPMPitchShift
    a("rf|" + fx(50.0))
    a("astart|1")
    a("ad|1")
    a("rf|" + fx(4.0))
    a("astart|1")
    a("rf|" + fx(3.99))
    a("astart|1")
    a("ad|1")
    for _ in range(6):
        a("astart|1")
    a("ad|1")
    a("rf|" + fx(50.0))
    a("astart|1")
    a("rf|" + fx(1.0))
    a("astart|1")
    a("ad|1")
    for _ in range(4):
        a("rf|" + fx(60.0))
        a("astart|1")
    a("ad|1")
    for _ in range(12):
        a("rf|" + fx(60.0))
        a("astart|1")
    a("ad|1")
    a("aset|1|tgt|" + fx(-1.0))
    a("aset|1|curp|" + fx(0.9))
    a("rf|" + fx(60.0))
    a("astart|1")
    a("ad|1")
    # Level with the top: the dice are thrown again. Then rising to the
    # idle and reaching it.
    for tgt, cur in ((1.0, 1.0), (0.3, 0.2)):
        a("aset|1|tgt|" + fx(tgt))
        a("aset|1|curp|" + fx(cur))
        a("rf|" + fx(50.0))
        a("astart|1")
        a("ad|1")

    # Update
    a("race|2")
    st(1, 1.0, 2, 0.0, 3000.0)
    upd(1, 0.8, 1000, 1.0)
    a("ad|1")
    a("vc|1|16|1")
    a("ad|1")
    a("cv|1|" + fx(0.5))
    a("rf|" + fx(50.0))
    upd(1, 0.8, 1000, 1.0)
    a("ad|1")
    a("race|3")
    a("rf|" + fx(50.0))
    upd(1, 0.8, 1000, 1.0)
    for race in (0, 1, 4, -1):
        a("race|%d" % race)
        upd(1, 0.8, 1100, 1.0)
        a("ad|1")
    a("race|2")
    for vel in (2.235, 2.236, 2.25, 3.0, 20.8, 20.84, 21.0, 40.0):
        st(1, vel, 2, 0.0, 3000.0)
        a("cv|1|" + fx(0.5))
        a("rf|" + fx(50.0))
        upd(1, 0.8, 1200, 1.1)
        a("ad|1")
    # Exactly 5 mph.
    a("st|1|400f0c79|2|%s" % fl(0.0, 3000.0))
    a("cv|1|" + fx(0.5))
    a("rf|" + fx(50.0))
    upd(1, 0.8, 1200, 1.1)
    a("ad|1")
    a("bplaying|1|s|0")
    upd(1, 0.8, 1200, 1.1)
    a("bplaying|1|s|0")
    a("se|0")
    upd(1, 0.8, 1300, 1.1)
    a("se|1")
    a("cse|0")
    upd(1, 0.8, 1300, 1.1)
    a("cse|1")
    a("cv|1|" + fx(0.1))
    upd(1, 0.6, 1300, 1.1)
    a("race|-1")
    a("vc|1|32|1")
    a("vc|1|32|5")
    a("vc|1|32|0")
    a("vc|1|40")
    a("vc|1|48")
    a("se|0")
    a("vc|1|48")
    a("se|1")
    a("cse|0")
    a("vc|1|48")
    a("cse|1")
    a("vc|1|16|0")
    a("ad|1")
    upd(1, 0.8, 1000, 1.0)
    a("vc|1|56|1")
    a("vc|2|16|1")
    upd(2, 0.8, 1000, 1.0)
    a("ad|2")

    # ---- the destructors
    a("vc|1|8|3")
    a("vc|2|8|0")
    a("vc|6|8|3")
    a("vc|0|8|3")
    a("vc|3|8|0")
    a("vc|4|8|3")
    a("vc|5|8|3")
    a("lpes")
    return L


# ================================================================= build

def build_harness(tmp, retail_voices, name="enginesound_test"):
    flags = hostbuild.FLAGS + (RETAIL_VOICES if retail_voices else [])
    return hostbuild.build(tmp, SOURCES, name=name, flags=flags)


def run_harness(exe, sc_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(sc_path), str(SOUND_DIR)],
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


def model_cached(lines, mono):
    """model(lines, mono)'s transcript, or its last one when nothing it
    reads has changed. Nothing past the mutations' header is the
    model's."""
    return mutpar.model_cached(
        lines + ["#mono"] if mono else lines,
        lambda sc: model([x for x in sc if x != "#mono"], mono)[0],
        data=TABLES, cut=MUTATIONS_HEADER)


def _m(name, before, after, rel=ESC):
    return (name, rel, before, after)


MUTATIONS = [
    # The audio mode and the tables.
    _m("audio-mode-retail", "    return sound_get_audio_mode(sound_get());",
       "    return 1;"),
    _m("audio-mode-mono", "#else\n    return 0;\n#endif",
       "#else\n    return 1;\n#endif"),
    _m("crossfade-offset", "return (int8_t)CrossFadeImage[128 + i];",
       "return (int8_t)CrossFadeImage[127 + i];"),
    _m("crossfade-unsigned", "return (int8_t)CrossFadeImage[128 + i];",
       "return CrossFadeImage[128 + i];"),
    _m("crossfade-below", "    0x40, 0x00, 0x00, 0x00, 0x80, 0x00,",
       "    0x40, 0x00, 0x00, 0x00, 0x7f, 0x00,"),
    _m("crossfade-table", "0x00, 0x03, 0x07, 0x0a, 0x0d,",
       "0x00, 0x03, 0x07, 0x0b, 0x0d,"),
    _m("crossfade-above", "0x7f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, "
       "0x00, 0x01,", "0x7f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, "
       "0x00, 0x02,"),
    _m("gear-steps", "{ 12, 25, 50, 100, 200, 400 }",
       "{ 12, 25, 50, 100, 200, 401 }"),
    _m("gear-steps-first", "{ 12, 25, 50, 100, 200, 400 }",
       "{ 13, 25, 50, 100, 200, 400 }"),
    _m("gear-volumes", "0.8f, 0.6f, 0.4f, 0.4f, 0.4f, 0.8f",
       "0.8f, 0.6f, 0.4f, 0.4f, 0.4f, 0.7f"),
    _m("gear-volumes-first", "0.8f, 0.6f, 0.4f, 0.4f, 0.4f, 0.8f",
       "0.7f, 0.6f, 0.4f, 0.4f, 0.4f, 0.8f"),

    # The helpers.
    _m("smooth-up", "    float up = a + step;",
       "    float up = a + step * 0.5f;"),
    _m("smooth-down", "    down = a - step;\n    if (b < down)\n"
       "        return down;\n    return b;\n}\n\n// smooth<float> (0x002123b8)",
       "    down = a - step * 0.5f;\n    if (b < down)\n"
       "        return down;\n    return b;\n}\n\n// smooth<float> (0x002123b8)"),
    _m("smooth4-up", "    float up = a + up_step;",
       "    float up = a + down_step;"),
    _m("smooth4-down", "    down = a - down_step;", "    down = a - up_step;"),
    _m("smooth-s16-up", "    int32_t up = a + step;",
       "    int32_t up = a + step + 1;"),
    _m("smooth-s16-down", "        return (int16_t)down;",
       "        return (int16_t)(down + 1);"),
    _m("min-i", "    return a < b ? a : b;", "    return a < b ? b : a;"),
    _m("max-i", "    return b < a ? a : b;", "    return b < a ? b : a;"),
    _m("min-f", "    return b < a ? b : a;", "    return b < a ? a : b;"),
    _m("max-f", "    return a < b ? b : a;", "    return a < b ? a : b;"),
    _m("clamp-hi", "    return min_i(max_i(x, lo), hi);",
       "    return max_i(x, lo);"),
    _m("clamp-lo", "    return min_i(max_i(x, lo), hi);",
       "    return min_i(x, hi);"),
    _m("car-rpm-test", "    return TestRPM == 100.0f ? c->State.RPM : TestRPM;",
       "    return c->State.RPM;"),
    _m("vol-table", "    return (const int8_t *)&d->pvoltable[a] + d->pvoltable[a];",
       "    return (const int8_t *)d + d->pvoltable[a];"),

    # VoiceAttr.
    _m("play-negative", "    int16_t vol = o->vol < 0 ? 0 : o->vol;",
       "    int16_t vol = o->vol;"),
    _m("play-azim", "    v->azim = o->azimuth;", "    v->azim = 0;"),
    _m("play-pitch", "    v->pitch = o->pitch;", "    v->pitch = 0.0f;"),
    _m("play-bend", "    v->bend = o->bend;", "    v->bend = 0;"),
    _m("play-cse", "    if (SoundEnabled && CarSoundEnabled)\n"
       "        bsample_play(&v->sample,", "    if (SoundEnabled)\n"
       "        bsample_play(&v->sample,"),
    _m("play-se", "    if (SoundEnabled && CarSoundEnabled)\n"
       "        bsample_play(&v->sample,", "    if (CarSoundEnabled)\n"
       "        bsample_play(&v->sample,"),
    _m("play-scale", "(float)vol * (1.0f / 127.0f), 0.0f,",
       "(float)vol * (1.0f / 128.0f), 0.0f,"),
    _m("play-pan", "(float)vol * (1.0f / 127.0f), 0.0f,",
       "(float)vol * (1.0f / 127.0f), 1.0f,"),
    _m("play-pitch-arg", "                     o->pitch);",
       "                     1.0f);"),
    _m("play-azimuth-call", "    bsample_set_azimuth(&v->sample, v->azim);\n",
       ""),
    _m("stop-vol", "    if (v->vol != 0)\n        enginevoice_set_volume(v, 0);",
       "    if (v->vol > 1)\n        enginevoice_set_volume(v, 0);"),
    _m("stop-always", "        enginevoice_set_volume(v, 0);\n    else\n",
       "        enginevoice_set_volume(v, 0);\n"),
    _m("setvol-step", "    int16_t n = smooth_s16(v->vol, vol, 15);",
       "    int16_t n = smooth_s16(v->vol, vol, 16);"),
    _m("setvol-same", "    if (n == v->vol)\n        return;\n    if (n < 0)",
       "    if (n < 0)"),
    _m("setvol-floor", "        n = 0;\n    v->vol = n;",
       "        n = 1;\n    v->vol = n;"),
    _m("setvol-store", "        n = 0;\n    v->vol = n;", "        n = 0;"),
    _m("setvol-scale", "(float)n * (1.0f / 127.0f));",
       "(float)n * (1.0f / 128.0f));"),
    _m("setpitch-same", "    if (v->pitch == pitch)\n        return;\n", ""),
    _m("setpitch-store", "    v->pitch = pitch;\n    bsample_set_pitch",
       "    bsample_set_pitch"),
    _m("setaz-same", "    if (v->azim == a)\n        return;\n", ""),
    _m("setaz-store", "    v->azim = a;\n", ""),

    # PlayerEngineSound's constructor and destructor.
    _m("ctor-vtable", "    s->Sound._vtable = PLAYERENGINESOUND_VTABLE;\n"
       "    bsample_construct", "    s->Sound._vtable = AIENGINESOUND_VTABLE;\n"
       "    bsample_construct"),
    _m("ctor-nitro-start", "    bsample_construct(&s->NitroStartSample, 0);\n",
       ""),
    _m("ctor-left-vol", "        s->left[i].vol = 0;", "        s->left[i].vol = 1;"),
    _m("ctor-left-bend", "        s->left[i].bend = 0;",
       "        s->left[i].bend = 1;"),
    _m("ctor-left-azim", "        s->left[i].azim = 0;",
       "        s->left[i].azim = 1;"),
    _m("ctor-right-pitch", "        s->right[i].pitch = 0.0f;",
       "        s->right[i].pitch = 1.0f;"),
    _m("ctor-right-sample", "        bsample_construct(&s->right[i].sample, 0);\n",
       ""),
    _m("ctor-bnk", "        s->engineSample[i].bnkID = -1;",
       "        s->engineSample[i].bnkID = 0;"),
    _m("ctor-patchtype", "        s->engineSample[i].patchtype = 0;",
       "        s->engineSample[i].patchtype = 1;"),
    _m("ctor-enabled", "        s->engineSample[i].isEnabled = 1;",
       "        s->engineSample[i].isEnabled = 0;"),
    _m("ctor-sample", "        s->engineSample[i].sample = NULL;",
       "        s->engineSample[i].sample = &s->NitroStartSample;"),
    _m("ctor-detune", "        s->engineSample[i].detune = 0;",
       "        s->engineSample[i].detune = 1;"),
    _m("ctor-volume", "        s->engineSample[i].volume = 1.0f;",
       "        s->engineSample[i].volume = 0.5f;"),
    _m("ctor-throttle", "    s->pCar = c;\n    s->CurrThrottle = 0;",
       "    s->pCar = c;\n    s->CurrThrottle = 1;"),
    _m("ctor-rpm", "    s->CurrentRPM = car_rpm(c);", "    s->CurrentRPM = 0.0f;"),
    _m("ctor-shifting", "    s->GearShiftingUp = 0;\n    s->EngineBackfire",
       "    s->GearShiftingUp = 1;\n    s->EngineBackfire"),
    _m("ctor-backfire", "    s->EngineBackfireBuildup = 0;",
       "    s->EngineBackfireBuildup = 1;"),
    _m("ctor-blownrod", "    s->UpdateBlownRodTime = 0.0f;",
       "    s->UpdateBlownRodTime = 1.0f;"),
    _m("ctor-ducker-time", "    s->fEngineDuckerThrottleTime = 0.0f;\n"
       "    s->fEngineDuckerVolumeScale = 1.0f;",
       "    s->fEngineDuckerThrottleTime = 1.0f;\n"
       "    s->fEngineDuckerVolumeScale = 1.0f;"),
    _m("ctor-ducker-scale", "    s->fEngineDuckerVolumeScale = 1.0f;\n"
       "    s->GearShiftVolumeScale", "    s->fEngineDuckerVolumeScale = 0.5f;\n"
       "    s->GearShiftVolumeScale"),
    _m("ctor-gsvs", "    s->GearShiftVolumeScale = 1.0f;\n"
       "    playerenginesound_init(s);", "    s->GearShiftVolumeScale = 0.5f;\n"
       "    playerenginesound_init(s);"),
    _m("ctor-init", "    playerenginesound_init(s);\n    bsample_initialize",
       "    bsample_initialize"),
    _m("ctor-nitro-name", "                                                     "
       "\"NitroStart\"));", "                                                     "
       "\"NitroLoop\"));"),
    _m("ctor-nitro-cat", "    bsample_set_category(&s->NitroStartSample, 2);",
       "    bsample_set_category(&s->NitroStartSample, 3);"),
    _m("ctor-loop-cat", "    bsample_set_category(&s->NitroLoopSample, 2);",
       "    bsample_set_category(&s->NitroLoopSample, 3);"),
    _m("ctor-activate", "    sound3d_activate(&s->Sound, 1);\n", ""),
    _m("dtor-stop-right", "        bsample_stop(&s->right[i].sample);\n"
       "    }\n    for (i = 0; i < 2; i++) {", "    }\n    for (i = 0; i < 2; i++) {"),
    _m("dtor-stop-count", "    for (i = 0; i < ENGINESOUND_PATCHES; i++) {\n"
       "        bsample_stop(&s->left[i].sample);",
       "    for (i = 0; i < ENGINESOUND_VOICES; i++) {\n"
       "        bsample_stop(&s->left[i].sample);"),
    _m("dtor-free", "            bFree(s->definitions[i]);\n", ""),
    _m("dtor-free-null", "        if (s->definitions[i] != NULL) {",
       "        if (s->definitions[i] == NULL) {"),
    _m("dtor-right", "        bsample_destruct(&s->right[i].sample);\n", ""),
    _m("dtor-left", "        bsample_destruct(&s->left[i].sample);\n", ""),
    _m("dtor-loop", "    bsample_destruct(&s->NitroLoopSample);\n", ""),
    _m("dtor-start", "    bsample_destruct(&s->NitroStartSample);\n", ""),
    _m("dtor-flags", "    sound3d_destroy(&s->Sound, flags);\n}\n\n"
       "void playerenginesound_init", "    sound3d_destroy(&s->Sound, 0);\n}\n\n"
       "void playerenginesound_init"),

    # Init.
    _m("init-se", "    if (!SoundEnabled)\n        return;\n    // The menu's", "    // The menu's"),
    _m("init-menu-name", "\"MenuSelect\", \"MenuCancel\", \"MenuWrong\",",
       "\"MenuSelect\", \"MenuCancel\", \"MenuWrongs\","),
    _m("init-menu-count", "    for (i = 0; i < 6; i++)\n"
       "        bsample_stop(bregion_sample(r, menu[i]));",
       "    for (i = 0; i < 5; i++)\n"
       "        bsample_stop(bregion_sample(r, menu[i]));"),
    _m("init-region", "    r = bsound_region(bsound_get(), \"common\");",
       "    r = bsound_region(bsound_get(), \"commons\");"),
    _m("init-update", "        bsample_stop(bregion_sample(r, menu[i]));\n"
       "    bsound_update(bsound_get());\n", "        bsample_stop(bregion_sample(r, menu[i]));\n"),
    _m("init-wait", "    t = bGetTicker();\n"
       "    while (bGetTickerDifference(t, bGetTicker()) < 16.0f)\n        ;\n"
       "    bsound_update(bsound_get());\n\n", "    t = bGetTicker();\n"
       "    while (bGetTickerDifference(t, bGetTicker()) < 14.0f)\n        ;\n"
       "    bsound_update(bsound_get());\n\n"),
    _m("init-region-car", "    r = bsound_region(bsound_get(), si->BaseName);",
       "    r = bsound_region(bsound_get(), si->Prefix);"),
    _m("init-stereo", "    s->IsStereo = 1;\n    s->CurrAudioMode",
       "    s->IsStereo = 0;\n    s->CurrAudioMode"),
    _m("init-mode", "    s->CurrAudioMode = engine_audio_mode();\n"
       "    for (i = 0; i < 4; i++)", "    s->CurrAudioMode = 3;\n"
       "    for (i = 0; i < 4; i++)"),
    _m("init-pov", "        s->POVTimbre[i] = (int8_t)si->Timbre[i];",
       "        s->POVTimbre[i] = (int8_t)si->Timbre[3 - i];"),
    _m("init-pov-unsigned", "        s->POVTimbre[i] = (int8_t)si->Timbre[i];",
       "        s->POVTimbre[i] = (uint8_t)si->Timbre[i];"),
    _m("init-bend", "    s->BendRange = si->BendRange;",
       "    s->BendRange = si->BaseAdd;"),
    _m("init-bass", "    s->BassAdd = si->BaseAdd;",
       "    s->BassAdd = si->BendRange;"),
    _m("init-redoff", "    s->RedLineRPMOffset = (float)si->RedLineOffset;",
       "    s->RedLineRPMOffset = (float)si->TopGearOffset;"),
    _m("init-topoff", "    s->TopGearRPMOffset = (float)si->TopGearOffset;",
       "    s->TopGearRPMOffset = (float)si->RedLineOffset;"),
    _m("init-detune", "        es->detune = si->Detune[i];",
       "        es->detune = si->Detune[0];"),
    _m("init-volume", "        es->volume = si->Volume[i];",
       "        es->volume = si->Volume[0];"),
    _m("init-patchtype", "        es->patchtype = patches[i][1] == 'x';",
       "        es->patchtype = patches[i][0] == 'c';"),
    _m("init-patches-l", "\"lelo\", \"lemd\", \"lehi\", \"lxlo\",",
       "\"lemd\", \"lelo\", \"lehi\", \"lxlo\","),
    _m("init-patches-c", "\"ceid\", \"cemd\", \"cehi\", \"cxid\",",
       "\"ceid\", \"cemd\", \"cehi\", \"cxlo\","),
    _m("init-prefix", "        strcpy(name, si->Prefix);",
       "        strcpy(name, si->BaseName);"),
    _m("init-missing", "        if (smp == NULL)\n            return;",
       "        if (smp == NULL)\n            continue;"),
    _m("init-bnk", "        es->bnkID = 1;", "        es->bnkID = 2;"),
    _m("init-left-cat", "        bsample_set_category(&s->left[i].sample, 2);",
       "        bsample_set_category(&s->left[i].sample, 0);"),
    _m("init-right-cat", "        bsample_set_category(&s->right[i].sample, 2);",
       "        bsample_set_category(&s->right[i].sample, 0);"),
    _m("init-right-copy", "        bsample_initialize_copy(&s->right[i].sample, smp);\n",
       ""),
    _m("init-lock-count", "        if (i < 6) {", "        if (i < 5) {"),
    _m("init-lock-left", "            bsample_lock_voice(&s->left[i].sample);\n",
       ""),
    _m("init-lock-players", "            if (PlayerNumPlayers == 1)",
       "            if (PlayerNumPlayers >= 1)"),
    _m("init-lock-right", "                bsample_lock_voice(&s->right[i].sample);\n",
       ""),
    _m("init-pool", "        s->definitions[i] = (EngineDef *)bGetFile(tables[i], NULL, 16);",
       "        s->definitions[i] = (EngineDef *)bGetFile(tables[i], NULL, 0);"),
    _m("init-tables", r'"sound\\engine.ctb", "sound\\engine.ltb",',
       r'"sound\\engine.ltb", "sound\\engine.ctb",'),
    _m("init-resolve", "    playerenginesound_resolve_tables(s);\n}", "}"),

    # Mute and ResolveTables.
    _m("mute-on", "    if (on == 0 && engine_audio_mode() != s->CurrAudioMode) {",
       "    if (on == 0) {"),
    _m("mute-mode", "    if (on == 0 && engine_audio_mode() != s->CurrAudioMode) {",
       "    if (engine_audio_mode() != s->CurrAudioMode) {"),
    _m("mute-stop-count", "        for (i = 0; i < ENGINESOUND_PATCHES; i++) {\n"
       "            enginevoice_stop(&s->left[i]);",
       "        for (i = 0; i < 6; i++) {\n"
       "            enginevoice_stop(&s->left[i]);"),
    _m("mute-stop-right", "            enginevoice_stop(&s->right[i]);\n"
       "        }\n    } else {", "        }\n    } else {"),
    _m("mute-pause", "        pause = on != 0;", "        pause = on == 1;"),
    _m("mute-pause-right", "            bsample_pause(&s->right[i].sample, pause);\n",
       ""),
    _m("mute-nitro-start", "    bsample_pause(&s->NitroStartSample, pause);\n", ""),
    _m("mute-nitro-loop", "    bsample_pause(&s->NitroLoopSample, pause);",
       "    bsample_pause(&s->NitroLoopSample, !pause);"),
    _m("mute-store-mode", "    s->CurrAudioMode = engine_audio_mode();\n}", "}"),
    _m("resolve-flag", "            s->definitions[i]->resolved = 1;",
       "            s->definitions[i]->resolved = 2;"),
    _m("resolve-volume", "    s->Volume = 0;\n    s->ControllerLevel = 0;",
       "    s->Volume = 1;\n    s->ControllerLevel = 0;"),
    _m("resolve-level", "    s->ControllerLevel = 0;\n    s->HighestPatch = 0;",
       "    s->ControllerLevel = 1;\n    s->HighestPatch = 0;"),
    _m("resolve-highest", "    s->HighestPatch = 0;\n    for",
       "    s->HighestPatch = 1;\n    for"),
    _m("resolve-count", "    for (i = 0; i < 16; i++)\n        if (s->definitions",
       "    for (i = 0; i < 15; i++)\n        if (s->definitions"),
    _m("resolve-slot", "        if (s->definitions[i >= 8]->patchnum[i / 8] >= 0)",
       "        if (s->definitions[i >= 8]->patchnum[i % 8] >= 0)"),
    _m("resolve-sign", "        if (s->definitions[i >= 8]->patchnum[i / 8] >= 0)",
       "        if (s->definitions[i >= 8]->patchnum[i / 8] > 0)"),
    _m("resolve-def", "        if (s->definitions[i >= 8]->patchnum[i / 8] >= 0)",
       "        if (s->definitions[0]->patchnum[i / 8] >= 0)"),
    _m("resolve-plus", "            s->HighestPatch = (int8_t)(i + 1);",
       "            s->HighestPatch = (int8_t)i;"),

    # RampThrottle.
    _m("ramp-scale", "    int32_t t = ee_trunc_w(s->pCar->State.Throttle * 255.0f);",
       "    int32_t t = ee_trunc_w(s->pCar->State.Throttle * 256.0f);"),
    _m("ramp-up-cmp", "    if (cur < t) {", "    if (cur <= t) {"),
    _m("ramp-up", "        s->CurrThrottle = cur + (t - cur) / 2;",
       "        s->CurrThrottle = cur + (t - cur) / 4;"),
    _m("ramp-up-snap", "        if (s->CurrThrottle >= 254)",
       "        if (s->CurrThrottle >= 253)"),
    _m("ramp-up-to", "            s->CurrThrottle = 255;",
       "            s->CurrThrottle = 254;"),
    _m("ramp-down-cmp", "    } else if (t < cur) {", "    } else {"),
    _m("ramp-down", "        s->CurrThrottle = cur + (t - cur) / 8;",
       "        s->CurrThrottle = cur + (t - cur) / 4;"),
    _m("ramp-down-shift", "        s->CurrThrottle = cur + (t - cur) / 8;",
       "        s->CurrThrottle = cur + ((t - cur) >> 3);"),
    _m("ramp-down-snap", "        if (s->CurrThrottle < 9)",
       "        if (s->CurrThrottle < 8)"),
    _m("ramp-down-to", "            s->CurrThrottle = 0;\n    }",
       "            s->CurrThrottle = 1;\n    }"),
    _m("ramp-clamp-hi", "    s->CurrThrottle = clamp_i(s->CurrThrottle, 0, 255);",
       "    s->CurrThrottle = clamp_i(s->CurrThrottle, 0, 254);"),
    _m("ramp-clamp-lo", "    s->CurrThrottle = clamp_i(s->CurrThrottle, 0, 255);",
       "    s->CurrThrottle = clamp_i(s->CurrThrottle, 1, 255);"),

    # UpdateGearShiftEffect.
    _m("gear-target", "    float target = 1.0f;\n\n    if (c == NULL",
       "    float target = 0.9f;\n\n    if (c == NULL"),
    _m("gear-mode", "    if (c == NULL || c->TheMovementMode != PHYSICS_MOVEMENT)\n"
       "        return;\n    dt = car_drive_train(c);",
       "    if (c == NULL)\n        return;\n    dt = car_drive_train(c);"),
    _m("gear-up", "    if (dt->CurrentGear < dt->DesiredGear)\n"
       "        s->GearShiftingUp = 1;", "    if (dt->CurrentGear <= dt->DesiredGear)\n"
       "        s->GearShiftingUp = 1;"),
    _m("gear-down", "    else if (dt->DesiredGear < dt->CurrentGear)\n"
       "        s->GearShiftingUp = 0;", "    else\n        s->GearShiftingUp = 0;"),
    _m("gear-rpm", "    if (s->GearShiftingUp && 1500.0f < car_rpm(c)",
       "    if (s->GearShiftingUp && 1500.0f <= car_rpm(c)"),
    _m("gear-rpm-test", "    if (s->GearShiftingUp && 1500.0f < car_rpm(c)",
       "    if (s->GearShiftingUp && 1500.0f < c->State.RPM"),
    _m("gear-disengaging", "        && (dt->CurrentClutchState == CLUTCH_DISENGAGING",
       "        && (dt->CurrentClutchState == CLUTCH_ENGAGED"),
    _m("gear-engaging", "            || dt->CurrentClutchState == CLUTCH_ENGAGING))",
       "            || dt->CurrentClutchState == CLUTCH_ENGAGED))"),
    _m("gear-floor", "        target = max_f(0.4f, drivetrain_get_state(dt)->clutch);",
       "        target = max_f(0.5f, drivetrain_get_state(dt)->clutch);"),
    _m("gear-step", "    s->GearShiftVolumeScale = smooth(s->GearShiftVolumeScale, target, 0.2f);",
       "    s->GearShiftVolumeScale = smooth(s->GearShiftVolumeScale, target, 0.25f);"),

    # UpdateToRedLineRPM.
    _m("red-mode", "    if (c != NULL && c->TheMovementMode == PHYSICS_MOVEMENT) {\n"
       "        DriveTrain *dt", "    if (c != NULL) {\n        DriveTrain *dt"),
    _m("red-gear", "        if (gear >= 2) {", "        if (gear > 2) {"),
    _m("red-offset", "            float red = ei->RedLineRPM + s->RedLineRPMOffset;",
       "            float red = ei->RedLineRPM - s->RedLineRPMOffset;"),
    _m("red-shift-index", "            float shift = dt->ShiftUpRPM[gear + 1];",
       "            float shift = dt->ShiftUpRPM[gear];"),
    _m("red-under", "            if (red < shift)\n                shift = red;",
       "            if (shift < red)\n                shift = red;"),
    _m("red-ratio", "            ratio = ee_div(red, shift);",
       "            ratio = ee_div(shift, red);"),
    _m("red-top-gear", "            if (c->State.CurrentGear\n",
       "            if (dt->CurrentGear\n"),
    _m("red-top", "                == c->pCarTypeInfo->DriveTrain.NumGears + 1)",
       "                == c->pCarTypeInfo->DriveTrain.NumGears + 2)"),
    _m("red-top-add", "                r += s->TopGearRPMOffset;",
       "                r -= s->TopGearRPMOffset;"),
    _m("red-cap", "            r = min_f(r, ei->MaxRPM * ratio);",
       "            r = min_f(r, ei->MaxRPM);"),
    _m("red-sync", "    c->State.RedLineSyncRPM = r;\n", ""),
    _m("red-out", "    *rpm = r;\n}", "}"),

    # UpdateNitroEffect.
    _m("nitro-mode", "    if (c == NULL || c->TheMovementMode != PHYSICS_MOVEMENT)\n"
       "        return;\n    e = car_drive_train(c)->pEngine;",
       "    if (c == NULL)\n        return;\n    e = car_drive_train(c)->pEngine;"),
    _m("nitro-flag", "    if (e->NitroFlag) {", "    if (!e->NitroFlag) {"),
    _m("nitro-playing", "        if (!bsample_is_playing(&s->NitroLoopSample)) {",
       "        if (!bsample_is_playing(&s->NitroStartSample)) {"),
    _m("nitro-vol", "            float v = volume * 2.5f;",
       "            float v = volume * 2.0f;"),
    _m("nitro-pan", "            float a = (float)azimuth;",
       "            float a = 0.0f;"),
    _m("nitro-start", "            bsample_play(&s->NitroStartSample, v, a, 0.0f);\n",
       ""),
    _m("nitro-start-pitch", "            bsample_play(&s->NitroStartSample, v, a, 0.0f);",
       "            bsample_play(&s->NitroStartSample, v, a, pitch);"),
    _m("nitro-loop-pitch", "            bsample_play(&s->NitroLoopSample, v, a, pitch);",
       "            bsample_play(&s->NitroLoopSample, v, a, 0.0f);"),
    _m("nitro-rate", "            float f = (WorldTimeSeconds - e->NitroBoostTimer) * 0.25f;",
       "            float f = (WorldTimeSeconds - e->NitroBoostTimer) * 0.3f;"),
    _m("nitro-p", "            float p = f + 0.5f;", "            float p = f + 0.6f;"),
    _m("nitro-fade-at", "            if (0.8f < f)", "            if (0.9f < f)"),
    _m("nitro-fade", "                scale = 1.0f - (f - 0.8f) * 5.0f;",
       "                scale = 1.0f - (f - 0.8f) * 4.0f;"),
    _m("nitro-loop-vol", "            bsample_set_volume(&s->NitroLoopSample, volume * scale * 2.5f);",
       "            bsample_set_volume(&s->NitroLoopSample, volume * 2.5f);"),
    _m("nitro-loop-az", "            bsample_set_azimuth(&s->NitroLoopSample, azimuth);\n",
       ""),
    _m("nitro-loop-p", "            bsample_set_pitch(&s->NitroLoopSample, pitch * p);",
       "            bsample_set_pitch(&s->NitroLoopSample, pitch);"),
    _m("nitro-stop", "    } else if (bsample_is_playing(&s->NitroLoopSample)) {\n"
       "        bsample_stop(&s->NitroLoopSample);",
       "    } else {\n        bsample_stop(&s->NitroLoopSample);"),

    # UpdateEngineDucker.
    _m("ducker-cat", "    if (!(0.05f < bsound_get_category_volume(bsound_get(), 4)))",
       "    if (!(0.05f < bsound_get_category_volume(bsound_get(), 3)))"),
    _m("ducker-music", "    if (!(0.05f < bsound_get_category_volume(bsound_get(), 4)))",
       "    if (!(0.1f < bsound_get_category_volume(bsound_get(), 4)))"),
    _m("ducker-throttle", "    if (s->pCar->State.Throttle < 0.5f) {",
       "    if (s->pCar->State.Throttle <= 0.5f) {"),
    _m("ducker-reset", "        s->fEngineDuckerThrottleTime = 0.0f;\n"
       "        s->fEngineDuckerVolumeScale =", "        s->fEngineDuckerVolumeScale ="),
    _m("ducker-back", "            smooth(s->fEngineDuckerVolumeScale, 1.0f, 0.008f);",
       "            smooth(s->fEngineDuckerVolumeScale, 1.0f, 0.01f);"),
    _m("ducker-time", "        s->fEngineDuckerThrottleTime += WorldTimeElapsed;",
       "        s->fEngineDuckerThrottleTime = WorldTimeElapsed;"),
    _m("ducker-after", "        if (5.0f < s->fEngineDuckerThrottleTime)",
       "        if (4.0f < s->fEngineDuckerThrottleTime)"),
    _m("ducker-to", "                smooth(s->fEngineDuckerVolumeScale, 0.75f, 0.008f);",
       "                smooth(s->fEngineDuckerVolumeScale, 0.7f, 0.008f);"),
    _m("ducker-down-step", "                smooth(s->fEngineDuckerVolumeScale, 0.75f, 0.008f);",
       "                smooth(s->fEngineDuckerVolumeScale, 0.75f, 0.01f);"),

    # UpdateEngine.
    _m("ueng-gear", "    playerenginesound_update_gear_shift_effect(s);\n"
       "    s->CurrentLevel", "    s->CurrentLevel"),
    _m("ueng-level", "    s->CurrentLevel = s->ControllerLevel = s->ControllerLevelTarget;",
       "    s->CurrentLevel = s->ControllerLevelTarget;"),
    _m("ueng-count", "    for (i = 0; i < s->HighestPatch; i++) {",
       "    for (i = 0; i < s->HighestPatch - 1; i++) {"),
    _m("ueng-load", "        int32_t load = i >= 8;", "        int32_t load = i > 8;"),
    _m("ueng-patch", "        if (patch < 0)\n            continue;\n        es =",
       "        if (patch < 1)\n            continue;\n        es ="),
    _m("ueng-bnk", "        if (es->bnkID == -1)\n            continue;\n", ""),
    _m("ueng-b", "        b = (int8_t)ee_trunc_w((float)(lvl * 127) * (1.0f / 440.0f));",
       "        b = (int8_t)ee_trunc_w((float)(lvl * 127) * (1.0f / 441.0f));"),
    _m("ueng-detune", "        pitch = (float)(s->BassAdd + es->detune",
       "        pitch = (float)(s->BassAdd - es->detune"),
    _m("ueng-bend-mid", "                        + (((b - 64) * s->BendRange) >> 6))",
       "                        + (((b - 63) * s->BendRange) >> 6))"),
    _m("ueng-bend-shift", "                        + (((b - 64) * s->BendRange) >> 6))",
       "                        + (((b - 64) * s->BendRange) / 64))"),
    _m("ueng-cents", "                * (1.0f / 1200.0f);",
       "                * (1.0f / 1100.0f);"),
    _m("ueng-table", "        v = (vol_table(def, a)[lvl] * s->Volume) >> 7;",
       "        v = (vol_table(def, a)[lvl] * s->Volume) >> 6;"),
    _m("ueng-table-unsigned", "        v = (vol_table(def, a)[lvl] * s->Volume) >> 7;",
       "        v = ((uint8_t)vol_table(def, a)[lvl] * s->Volume) >> 7;"),
    _m("ueng-ratio", "        v = (v * cross_fade(load ? s->Ratio : 127 - s->Ratio)) >> 7;",
       "        v = (v * cross_fade(load ? 127 - s->Ratio : s->Ratio)) >> 7;"),
    _m("ueng-ratio-shift", "        v = (v * cross_fade(load ? s->Ratio : 127 - s->Ratio)) >> 7;",
       "        v = (v * cross_fade(load ? s->Ratio : 127 - s->Ratio)) / 128;"),
    _m("ueng-zero", "        if (v == 0) {", "        if (v <= 1) {"),
    _m("ueng-zero-playing", "            if (bsample_is_playing(&l->sample)) {\n"
       "                enginevoice_stop(l);", "            if (bsample_is_playing(&r->sample)) {\n"
       "                enginevoice_stop(l);"),
    _m("ueng-zero-right", "                enginevoice_stop(r);\n            }\n", "            }\n"),
    _m("ueng-boost", "        v = (v * 5) >> 2;", "        v = (v * 5) >> 3;"),
    _m("ueng-cap", "        if (v >= 128)\n            v = 127;",
       "        if (v >= 128)\n            v = 126;"),
    _m("ueng-cap-at", "        if (v >= 128)\n            v = 127;",
       "        if (v >= 129)\n            v = 127;"),
    _m("ueng-timbre", "        v = (v * cross_fade(es->patchtype ? s->Timbre : 127 - s->Timbre))",
       "        v = (v * cross_fade(es->patchtype ? 127 - s->Timbre : s->Timbre))"),
    _m("ueng-timbre-shift", "            >> 7;\n        f = ", "            / 128;\n        f = "),
    _m("ueng-gsvs", "        f = s->GearShiftVolumeScale * s->fEngineDuckerVolumeScale",
       "        f = s->fEngineDuckerVolumeScale"),
    _m("ueng-ducker", "        f = s->GearShiftVolumeScale * s->fEngineDuckerVolumeScale",
       "        f = s->GearShiftVolumeScale"),
    _m("ueng-es-volume", "            * es->volume;", "            * 1.0f;"),
    _m("ueng-mono", "        if (s->CurrAudioMode == 0)\n            f *= 1.3f;",
       "        if (s->CurrAudioMode == 1)\n            f *= 1.3f;"),
    _m("ueng-mono-gain", "        if (s->CurrAudioMode == 0)\n            f *= 1.3f;",
       "        if (s->CurrAudioMode == 0)\n            f *= 1.2f;"),
    _m("ueng-azr", "        azr = (uint16_t)(s->Azim + s->Seperation);",
       "        azr = (uint16_t)s->Azim;"),
    _m("ueng-azl", "        azl = (uint16_t)(s->Azim - s->Seperation);",
       "        azl = (uint16_t)(s->Azim + s->Seperation);"),
    _m("ueng-vol", "        vol = ee_trunc_w((float)v * f);",
       "        vol = v;"),
    _m("ueng-start", "        if (!bsample_is_playing(&l->sample)) {\n"
       "            s->delay[patch] = 2;", "        if (!bsample_is_playing(&r->sample)) {\n"
       "            s->delay[patch] = 2;"),
    _m("ueng-delay", "            s->delay[patch] = 2;", "            s->delay[patch] = 3;"),
    _m("ueng-l-vol", "            o.vol = (int16_t)vol;\n            o.bend = 64;\n"
       "            o.pitch = pitch;\n            o.azimuth = azl;",
       "            o.vol = 0;\n            o.bend = 64;\n"
       "            o.pitch = pitch;\n            o.azimuth = azl;"),
    _m("ueng-l-bend", "            o.bend = 64;\n            o.pitch = pitch;\n"
       "            o.azimuth = azl;", "            o.bend = 63;\n            o.pitch = pitch;\n"
       "            o.azimuth = azl;"),
    _m("ueng-l-pitch", "            o.pitch = pitch;\n            o.azimuth = azl;",
       "            o.pitch = 1.0f;\n            o.azimuth = azl;"),
    _m("ueng-l-az", "            o.azimuth = azl;", "            o.azimuth = azr;"),
    _m("ueng-l-enabled", "            if (es->isEnabled)\n"
       "                enginevoice_play(l, &o);", "            enginevoice_play(l, &o);"),
    _m("ueng-stereo", "        if (s->IsStereo && !bsample_is_playing(&r->sample)",
       "        if (!bsample_is_playing(&r->sample)"),
    _m("ueng-r-playing", "        if (s->IsStereo && !bsample_is_playing(&r->sample)",
       "        if (s->IsStereo"),
    _m("ueng-r-delay", "            && s->delay[patch] <= 0) {",
       "            && s->delay[patch] < 0) {"),
    _m("ueng-r-vol", "            o.vol = (int16_t)vol;\n            o.bend = 64;\n"
       "            o.pitch = pitch;\n            o.azimuth = azr;",
       "            o.vol = 0;\n            o.bend = 64;\n"
       "            o.pitch = pitch;\n            o.azimuth = azr;"),
    _m("ueng-r-pitch", "            o.pitch = pitch;\n            o.azimuth = azr;",
       "            o.pitch = 1.0f;\n            o.azimuth = azr;"),
    _m("ueng-r-az", "            o.azimuth = azr;", "            o.azimuth = azl;"),
    _m("ueng-r-enabled", "            if (es->isEnabled)\n"
       "                enginevoice_play(r, &o);", "            enginevoice_play(r, &o);"),
    _m("ueng-countdown", "            s->delay[patch] = (int8_t)(uint8_t)(s->delay[patch] - 1);",
       "            s->delay[patch] = (int8_t)(uint8_t)(s->delay[patch] - 2);"),
    _m("ueng-countdown-floor", "            s->delay[patch] = (int8_t)(uint8_t)(s->delay[patch] - 1);",
       "            s->delay[patch] = (int8_t)max_i(s->delay[patch] - 1, -128);"),
    _m("ueng-disabled-l", "        if (!es->isEnabled && bsample_is_playing(&l->sample))\n"
       "            enginevoice_stop(l);\n", ""),
    _m("ueng-disabled-r", "        if (!es->isEnabled && bsample_is_playing(&r->sample))\n"
       "            enginevoice_stop(r);\n", ""),
    _m("ueng-setvol-l", "        enginevoice_set_volume(l, (int16_t)(vol > -1 ? vol : 0));",
       "        enginevoice_set_volume(l, (int16_t)vol);"),
    _m("ueng-setvol-r", "        enginevoice_set_volume(r, (int16_t)(vol > -1 ? vol : 0));\n",
       ""),
    _m("ueng-setaz-l", "        enginevoice_set_azimuth(l, azl);",
       "        enginevoice_set_azimuth(l, azr);"),
    _m("ueng-setaz-r", "        enginevoice_set_azimuth(r, azr);\n", ""),
    _m("ueng-setpitch-l", "        enginevoice_set_pitch(l, pitch);\n", ""),
    _m("ueng-setpitch-r", "        enginevoice_set_pitch(r, pitch);\n", ""),

    # Update.
    _m("upd-active", "    if (!s->Sound.Activated || !SoundEnabled || !CarSoundEnabled)",
       "    if (!SoundEnabled || !CarSoundEnabled)"),
    _m("upd-se", "    if (!s->Sound.Activated || !SoundEnabled || !CarSoundEnabled)",
       "    if (!s->Sound.Activated || !CarSoundEnabled)"),
    _m("upd-cse", "    if (!s->Sound.Activated || !SoundEnabled || !CarSoundEnabled)",
       "    if (!s->Sound.Activated || !SoundEnabled)"),
    _m("upd-ramp", "    playerenginesound_ramp_throttle(s);\n    c = s->pCar;",
       "    c = s->pCar;"),
    _m("upd-view", "    cam = eGetView(c->pPlayer->ViewID)->pCamera;",
       "    cam = eGetView(0)->pCamera;"),
    _m("upd-idle", "    rpm = car_rpm(c) - (float)(uint16_t)cti->Sound.IdleOffset;",
       "    rpm = car_rpm(c) + (float)(uint16_t)cti->Sound.IdleOffset;"),
    _m("upd-idle-test", "    rpm = car_rpm(c) - (float)(uint16_t)cti->Sound.IdleOffset;",
       "    rpm = c->State.RPM - (float)(uint16_t)cti->Sound.IdleOffset;"),
    _m("upd-redline", "    playerenginesound_update_to_red_line_rpm(s, &rpm);\n", ""),
    _m("upd-smooth-up", "    s->CurrentRPM = smooth4(s->CurrentRPM, rpm, 270.0f, 650.0f);",
       "    s->CurrentRPM = smooth4(s->CurrentRPM, rpm, 280.0f, 650.0f);"),
    _m("upd-smooth-down", "    s->CurrentRPM = smooth4(s->CurrentRPM, rpm, 270.0f, 650.0f);",
       "    s->CurrentRPM = smooth4(s->CurrentRPM, rpm, 270.0f, 600.0f);"),
    _m("upd-ducker", "    playerenginesound_update_engine_ducker(s);\n", ""),
    _m("upd-nitro", "    playerenginesound_update_nitro_effect(s, volume, azimuth, pitch);\n",
       ""),
    _m("upd-nitro-az", "    playerenginesound_update_nitro_effect(s, volume, azimuth, pitch);",
       "    playerenginesound_update_nitro_effect(s, volume, 0, pitch);"),
    _m("upd-vol", "    vol = ee_trunc_w(volume * 127.0f);",
       "    vol = ee_trunc_w(volume * 128.0f);"),
    _m("upd-ratio-cap", "    ratio = min_i(440, ee_trunc_w(ee_div(s->CurrentRPM, cti->Engine.MaxRPM)",
       "    ratio = min_i(439, ee_trunc_w(ee_div(s->CurrentRPM, cti->Engine.MaxRPM)"),
    _m("upd-ratio", "                                  * 440.0f));",
       "                                  * 441.0f));"),
    _m("upd-dop", "    dop = ee_trunc_w(pitch * 65536.0f);",
       "    dop = ee_trunc_w(pitch * 32768.0f);"),
    _m("upd-thr", "    thr = s->CurrThrottle;", "    thr = 255;"),
    _m("upd-pov", "        pov = c->pPlayer->PlayerSettings.DriveCameraPOVIndex;",
       "        pov = 1;"),
    _m("upd-instant", "    if (st == RCSTATE_INSTANT_REPLAY || st == RCSTATE_POSTRACE",
       "    if (st == RCSTATE_POSTRACE"),
    _m("upd-postrace", "    if (st == RCSTATE_INSTANT_REPLAY || st == RCSTATE_POSTRACE",
       "    if (st == RCSTATE_INSTANT_REPLAY"),
    _m("upd-auto", "        || st == RCSTATE_AUTO_REPLAY\n", ""),
    _m("upd-demo", "        || racecoordinator_is_replay_demo_mode(pRaceCoordinator)) {",
       "        ) {"),
    _m("upd-facing-z", "        facing = (d->x * body->x + d->y * body->y) + d->z * body->z;",
       "        facing = d->x * body->x + d->y * body->y;"),
    _m("upd-facing-x", "        facing = (d->x * body->x + d->y * body->y) + d->z * body->z;",
       "        facing = (d->x * body->y + d->y * body->y) + d->z * body->z;"),
    _m("upd-facing-pov", "        pov = -1;", "        pov = 0;"),
    _m("upd-stereo-az", "    if ((float)azimuth == 0.0f && engine_audio_mode() == 1) {",
       "    if (engine_audio_mode() == 1) {"),
    _m("upd-stereo-1", "    if ((float)azimuth == 0.0f && engine_audio_mode() == 1) {",
       "    if ((float)azimuth == 0.0f && engine_audio_mode() == 3) {"),
    _m("upd-stereo-2", "    } else if ((float)azimuth == 0.0f && engine_audio_mode() == 2) {",
       "    } else if ((float)azimuth == 0.0f && engine_audio_mode() == 3) {"),
    _m("upd-sep-1", "        s->Seperation = 8000;", "        s->Seperation = 7000;"),
    _m("upd-azim-1", "        s->Seperation = 8000;\n        s->Azim = 0;",
       "        s->Seperation = 8000;\n        s->Azim = 1;"),
    _m("upd-stereo-flag-2", "        s->IsStereo = 1;\n        s->Seperation = 6000;",
       "        s->IsStereo = 0;\n        s->Seperation = 6000;"),
    _m("upd-sep-2", "        s->Seperation = 6000;", "        s->Seperation = 7000;"),
    _m("upd-mono-flag", "        s->IsStereo = 0;", "        s->IsStereo = 1;"),
    _m("upd-mono-az", "        s->Azim = azimuth;", "        s->Azim = 0;"),
    _m("upd-mono-sep", "        s->Seperation = 0;\n    }", "        s->Seperation = 1;\n    }"),
    _m("upd-set-thr", "    playerenginesound_set(s, vol, ratio, thr, dist2, dop, azimuth, facing,",
       "    playerenginesound_set(s, vol, ratio, 0, dist2, dop, azimuth, facing,"),
    _m("upd-set-ratio", "    playerenginesound_set(s, vol, ratio, thr, dist2, dop, azimuth, facing,",
       "    playerenginesound_set(s, vol, 0, thr, dist2, dop, azimuth, facing,"),
    _m("upd-set-dop", "    playerenginesound_set(s, vol, ratio, thr, dist2, dop, azimuth, facing,",
       "    playerenginesound_set(s, vol, ratio, thr, dist2, 0, azimuth, facing,"),
    _m("upd-set-facing", "    playerenginesound_set(s, vol, ratio, thr, dist2, dop, azimuth, facing,",
       "    playerenginesound_set(s, vol, ratio, thr, dist2, dop, azimuth, 0.0f,"),
    _m("upd-ueng", "    playerenginesound_update_engine(s);\n}", "}"),

    # Set.
    _m("set-level", "    s->ControllerLevelTarget = (int16_t)ratio;",
       "    s->ControllerLevelTarget = (int16_t)(ratio + 1);"),
    _m("set-doppler", "    s->Doppler = (uint16_t)(doppler >> 4);",
       "    s->Doppler = (uint16_t)(doppler >> 3);"),
    _m("set-ratio-cap", "    s->Ratio = min_i(127, throttle + (throttle >> 5));",
       "    s->Ratio = min_i(126, throttle + (throttle >> 5));"),
    _m("set-ratio", "    s->Ratio = min_i(127, throttle + (throttle >> 5));",
       "    s->Ratio = min_i(127, throttle + (throttle >> 4));"),
    _m("set-ratio-floor", "    if (s->Ratio < 4)\n        s->Ratio = 0;",
       "    if (s->Ratio < 3)\n        s->Ratio = 0;"),
    _m("set-ratio-zero", "    if (s->Ratio < 4)\n        s->Ratio = 0;",
       "    if (s->Ratio < 4)\n        s->Ratio = 1;"),
    _m("set-pov", "    if (pov == -1)", "    if (pov == 0)"),
    _m("set-facing-back", "        s->Timbre = (int8_t)ee_trunc_w((facing < 0.0f ? facing * 30.0f",
       "        s->Timbre = (int8_t)ee_trunc_w((facing < 0.0f ? facing * 40.0f"),
    _m("set-facing-front", "                                                      : facing * 60.0f)",
       "                                                      : facing * 50.0f)"),
    _m("set-facing-base", "                                       + 44.0f);",
       "                                       + 45.0f);"),
    _m("set-pov-timbre", "        s->Timbre = (int8_t)s->POVTimbre[pov];",
       "        s->Timbre = (int8_t)s->POVTimbre[0];"),
    _m("set-volume", "    s->Volume = volume;\n}", "    s->Volume = volume + 1;\n}"),

    # AIEngineSound.
    _m("ai-vtable", "    s->Sound._vtable = AIENGINESOUND_VTABLE;\n"
       "    bsample_construct(&s->EngineSample, 0);",
       "    s->Sound._vtable = PLAYERENGINESOUND_VTABLE;\n"
       "    bsample_construct(&s->EngineSample, 0);"),
    _m("ai-average", "    average_init(&s->RPMAverage, 20);",
       "    average_init(&s->RPMAverage, 19);"),
    _m("ai-car", "    s->pCar = c;\n    s->StartLineCurrPitch",
       "    s->pCar = NULL;\n    s->StartLineCurrPitch"),
    _m("ai-curp", "    s->StartLineCurrPitch = 0.0f;", "    s->StartLineCurrPitch = 0.5f;"),
    _m("ai-tgt", "    s->StartLineTargetPitch = -1.0f;", "    s->StartLineTargetPitch = -2.0f;"),
    _m("ai-gear", "    s->CurrGear = -1;", "    s->CurrGear = -2;"),
    _m("ai-frames", "    s->GearFrames = 10;", "    s->GearFrames = 6;"),
    _m("ai-srpm", "    s->SmoothRPM = 1000.0f;", "    s->SmoothRPM = 0.0f;"),
    _m("ai-gvs", "    s->GearVolumeScale = 1.0f;\n    s->EnginePitchBase",
       "    s->GearVolumeScale = 0.5f;\n    s->EnginePitchBase"),
    _m("ai-base-sign", "    s->EnginePitchBase = -sound_random_float(sound_get(), 0.4f);",
       "    s->EnginePitchBase = sound_random_float(sound_get(), 0.4f);"),
    _m("ai-base-range", "    s->EnginePitchBase = -sound_random_float(sound_get(), 0.4f);",
       "    s->EnginePitchBase = -sound_random_float(sound_get(), 0.5f);"),
    _m("ai-cat", "    bsample_set_category(&s->EngineSample, 0);",
       "    bsample_set_category(&s->EngineSample, 2);"),
    _m("ai-dtor-average", "    average_destroy(&s->RPMAverage, 2);",
       "    average_destroy(&s->RPMAverage, 3);"),
    _m("ai-dtor-sample", "    bsample_destruct(&s->EngineSample);\n    sound3d_destroy",
       "    sound3d_destroy"),
    _m("ai-dtor-flags", "    sound3d_destroy(&s->Sound, flags);\n}\n\n// Below",
       "    sound3d_destroy(&s->Sound, 0);\n}\n\n// Below"),
    _m("ai-upd-active", "    if (!s->Sound.Activated)\n        return;\n    if (pCurrentRace",
       "    if (pCurrentRace"),
    _m("ai-upd-race", "    if (pCurrentRace != NULL\n", "    if (pCurrentRace == NULL\n"),
    _m("ai-upd-prerace", "        && (race_get_race_stage(pCurrentRace) == RACE_STAGE_PRERACE",
       "        && (race_get_race_stage(pCurrentRace) == RACE_STAGE_FLYBY"),
    _m("ai-upd-countdown", "            || race_get_race_stage(pCurrentRace) == RACE_STAGE_COUNTDOWN))",
       "            || race_get_race_stage(pCurrentRace) == RACE_STAGE_RACING))"),
    _m("ai-upd-mph", "    if (!(s->pCar->State.VelocityMagnitude * 2.237f < 5.0f))",
       "    if (!(s->pCar->State.VelocityMagnitude * 2.236f < 5.0f))"),
    _m("ai-upd-mph-cmp", "    if (!(s->pCar->State.VelocityMagnitude * 2.237f < 5.0f))",
       "    if (!(s->pCar->State.VelocityMagnitude * 2.237f <= 5.0f))"),
    _m("ai-upd-rate", "    rate = 0.3f;", "    rate = 0.25f;"),
    _m("ai-upd-start-rate", "        rate = 0.075f;", "        rate = 0.08f;"),
    _m("ai-upd-start-p", "        p = aienginesound_compute_start_line_rpm_pitch_shift(s);",
       "        p = aienginesound_compute_rpm_pitch_shift(s);"),
    _m("ai-upd-p", "        p = aienginesound_compute_rpm_pitch_shift(s);\n        kph",
       "        p = 1.0f;\n        kph"),
    _m("ai-upd-kph", "        kph = s->pCar->State.VelocityMagnitude * 3.6f;",
       "        kph = s->pCar->State.VelocityMagnitude * 3.5f;"),
    _m("ai-upd-gvs", "        volume *= s->GearVolumeScale;\n", ""),
    _m("ai-upd-slow", "        if (kph < 75.0f)", "        if (kph < 70.0f)"),
    _m("ai-upd-slow-scale", "            volume *= kph * (1.0f / 75.0f) * 0.5f + 0.5f;",
       "            volume *= kph * (1.0f / 75.0f) * 0.4f + 0.5f;"),
    _m("ai-upd-slow-base", "            volume *= kph * (1.0f / 75.0f) * 0.5f + 0.5f;",
       "            volume *= kph * (1.0f / 75.0f) * 0.5f + 0.6f;"),
    _m("ai-upd-se", "        if (SoundEnabled && CarSoundEnabled)\n"
       "            bsample_play(&s->EngineSample, volume, 0.0f, 0.0f);",
       "        if (CarSoundEnabled)\n"
       "            bsample_play(&s->EngineSample, volume, 0.0f, 0.0f);"),
    _m("ai-upd-cse", "        if (SoundEnabled && CarSoundEnabled)\n"
       "            bsample_play(&s->EngineSample, volume, 0.0f, 0.0f);",
       "        if (SoundEnabled)\n"
       "            bsample_play(&s->EngineSample, volume, 0.0f, 0.0f);"),
    _m("ai-upd-play", "            bsample_play(&s->EngineSample, volume, 0.0f, 0.0f);",
       "            bsample_play(&s->EngineSample, volume, 0.0f, 1.0f);"),
    _m("ai-upd-smooth", "                           smooth(s->EngineSample.currentVolume, volume,\n"
       "                                  rate));", "                           volume);"),
    _m("ai-upd-pitch", "                      (s->EnginePitchBase + p * pitch) - 1.0f);",
       "                      (s->EnginePitchBase + p * pitch) - 0.9f);"),
    _m("ai-upd-pitch-mul", "                      (s->EnginePitchBase + p * pitch) - 1.0f);",
       "                      (s->EnginePitchBase + p + pitch) - 1.0f);"),
    _m("ai-upd-az", "    bsample_set_azimuth(&s->EngineSample, azimuth);\n", ""),
    _m("ai-mute", "    bsample_pause(&s->EngineSample, on != 0);",
       "    bsample_pause(&s->EngineSample, on == 1);"),
    _m("ai-name-usage", "    if (cartypeinfo_get(c->pRideInfo->Type)->UsageType != 2)",
       "    if (cartypeinfo_get(c->pRideInfo->Type)->UsageType != 1)"),
    _m("ai-name-ride", "    if (cartypeinfo_get(c->pRideInfo->Type)->UsageType != 2)",
       "    if (c->pCarTypeInfo->UsageType != 2)"),
    _m("ai-name-base", "    strcpy(name, \"AIEngine0\");", "    strcpy(name, \"AIEngine1\");"),
    _m("ai-name-add", "    name[8] = (char)(name[8] + n);",
       "    name[8] = (char)(name[8] + n + 1);"),
    _m("arpm-flush", "        average_flush(&s->RPMAverage, car_rpm(c));\n", ""),
    _m("arpm-flush-rpm", "        average_flush(&s->RPMAverage, car_rpm(c));",
       "        average_flush(&s->RPMAverage, c->State.RPM);"),
    _m("arpm-frames-reset", "        s->GearFrames = 0;", "        s->GearFrames = 1;"),
    _m("arpm-gear", "    s->CurrGear = c->State.CurrentGear;\n", ""),
    _m("arpm-record", "    average_record(&s->RPMAverage, car_rpm(c));",
       "    average_record(&s->RPMAverage, c->State.RPM);"),
    _m("arpm-frames", "    if (s->GearFrames < 6) {", "    if (s->GearFrames < 5) {"),
    _m("arpm-steps", "        step = (float)GearChangeSteps[s->GearFrames];",
       "        step = (float)GearChangeSteps[0];"),
    _m("arpm-volumes", "        scale = GearChangeVolumes[s->GearFrames];",
       "        scale = GearChangeVolumes[0];"),
    _m("arpm-step", "    float step = 5000.0f;", "    float step = 4000.0f;"),
    _m("arpm-scale", "    float scale = 1.0f;\n\n    if (c->State.CurrentGear",
       "    float scale = 0.9f;\n\n    if (c->State.CurrentGear"),
    _m("arpm-store-scale", "    s->GearVolumeScale = scale;\n", ""),
    _m("arpm-smooth", "    s->SmoothRPM = smooth(s->SmoothRPM, s->RPMAverage.fAverage, step);",
       "    s->SmoothRPM = smooth(s->SmoothRPM, car_rpm(c), step);"),
    _m("arpm-count", "    s->GearFrames++;\n", ""),
    _m("arpm-factor", "    return s->SmoothRPM * 0x1.a36e30p-13f;",
       "    return s->SmoothRPM * 0x1.a36e32p-13f;"),
    _m("astart-init", "    if (s->StartLineTargetPitch == -1.0f) {",
       "    if (s->StartLineTargetPitch == -2.0f) {"),
    _m("astart-init-tgt", "        s->StartLineTargetPitch = 0.3f;\n        s->StartLineCurrPitch = 0.3f;",
       "        s->StartLineTargetPitch = 0.31f;\n        s->StartLineCurrPitch = 0.3f;"),
    _m("astart-init-cur", "        s->StartLineCurrPitch = 0.3f;\n    }",
       "        s->StartLineCurrPitch = 0.5f;\n    }"),
    _m("astart-rising", "    if (s->StartLineCurrPitch < s->StartLineTargetPitch) {",
       "    if (s->StartLineCurrPitch <= s->StartLineTargetPitch) {"),
    _m("astart-up", "        step = 0.15f;", "        step = 0.2f;"),
    _m("astart-up-falling", "        falling = 0;", "        falling = 1;"),
    _m("astart-down", "        step = 0.08f;", "        step = 0.1f;"),
    _m("astart-down-falling", "        falling = 1;", "        falling = 0;"),
    _m("astart-reached", "    if (s->StartLineCurrPitch == s->StartLineTargetPitch || falling) {",
       "    if (s->StartLineCurrPitch == s->StartLineTargetPitch) {"),
    _m("astart-reached-falling", "    if (s->StartLineCurrPitch == s->StartLineTargetPitch || falling) {",
       "    if (falling) {"),
    _m("astart-idle", "        if ((s->StartLineCurrPitch == 0.3f || falling)",
       "        if ((s->StartLineCurrPitch == 0.3f)"),
    _m("astart-idle-only", "        if ((s->StartLineCurrPitch == 0.3f || falling)",
       "        if ((falling)"),
    _m("astart-dice", "            && sound_random_float(sound_get(), 100.0f) < 4.0f)",
       "            && sound_random_float(sound_get(), 100.0f) <= 4.0f)"),
    _m("astart-dice-range", "            && sound_random_float(sound_get(), 100.0f) < 4.0f)",
       "            && sound_random_float(sound_get(), 99.0f) < 4.0f)"),
    _m("astart-blip", "            s->StartLineTargetPitch = 1.0f;",
       "            s->StartLineTargetPitch = 0.9f;"),
    _m("astart-top", "        if (s->StartLineCurrPitch == 1.0f)",
       "        if (s->StartLineCurrPitch == 0.9f)"),
    _m("astart-back", "            s->StartLineTargetPitch = 0.3f;\n    }\n    return",
       "            s->StartLineTargetPitch = 0.4f;\n    }\n    return"),
    _m("ai-deact", "    bsample_stop(&s->EngineSample);\n}", "}"),
    _m("ai-act-se", "    if (SoundEnabled && CarSoundEnabled)\n"
       "        bsample_play(&s->EngineSample, 0.0f, 0.0f, 0.0f);",
       "    if (CarSoundEnabled)\n        bsample_play(&s->EngineSample, 0.0f, 0.0f, 0.0f);"),
    _m("ai-act-cse", "    if (SoundEnabled && CarSoundEnabled)\n"
       "        bsample_play(&s->EngineSample, 0.0f, 0.0f, 0.0f);",
       "    if (SoundEnabled)\n        bsample_play(&s->EngineSample, 0.0f, 0.0f, 0.0f);"),
    _m("ai-act-vol", "        bsample_play(&s->EngineSample, 0.0f, 0.0f, 0.0f);",
       "        bsample_play(&s->EngineSample, 1.0f, 0.0f, 0.0f);"),

    # The factories and the vtables.
    _m("mk-last", "    LastPlayerEngineSound = s;\n", ""),
    _m("mk-player-pool", "\"PlayerEngineSound\", 0, 16);",
       "\"PlayerEngineSound\", 0, 0);"),
    _m("mk-ai-flags", "\"AIEngineSound\", 0, 16);", "\"AIEngineSound\", 1, 16);"),
    _m("vt-player-mute", "    E(playerenginesound_mute),                          // 32",
       "    E(aienginesound_mute),                          // 32"),
    _m("vt-player-deact", "    E(playerenginesound_deactivate_sound),              // 40",
       "    E(playerenginesound_activate_sound),              // 40"),
    _m("vt-ai-deact", "    E(aienginesound_deactivate_sound),                  // 40",
       "    E(aienginesound_activate_sound),                  // 40"),
    _m("vt-ai-update", "    E(aienginesound_update),                            // 24",
       "    E(playerenginesound_update),                            // 24"),
    _m("h-voices", "#define ENGINESOUND_VOICES", "#define ENGINESOUND_VOICES 15 //",
       ESH),
]

EQUIVALENT = {
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
    caught, survived, missing, equal = 0, [], [], []
    left = todo
    for retail_voices in (False, True):
        label = "retail voices" if retail_voices else "mono"
        base = model_cached(lines, not retail_voices)
        flags = hostbuild.FLAGS + (RETAIL_VOICES if retail_voices else [])
        with tempfile.TemporaryDirectory() as tmp:
            exe = build_harness(tmp, retail_voices)
            out = Path(tmp) / "base.txt"
            t0 = time.monotonic()
            run_harness(exe, scp, out)
            took = time.monotonic() - t0
            got = out.read_text(encoding="latin-1").splitlines()
            if diff(base, got, quiet=True):
                print("%s base already differs -- fix that before "
                      "mutating" % label)
                return 1
            print("%s base: %d lines, 0 differ" % (label, len(got)),
                  flush=True)
        if not left:
            break
        limit = mutpar.timeout_for(took)
        c, s, m, q = mutpar.run_pass(
            left, SOURCES, "enginesound_test",
            lambda exe, out: mutpar.run_exe([exe, scp, SOUND_DIR], out,
                                            limit),
            base, diff, EQUIVALENT, jobs, flags)
        caught += c
        missing += m
        survived, equal = s, q
        # What the mono build missed runs again on retail's voices.
        left = [x for x in left if x[0] in s or x[0] in q]
    indir.cleanup()
    return mutpar.summarize(todo, only, EQUIVALENT,
                            (caught, survived, missing, equal))


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
    bad = 0
    for retail_voices in (True, False):
        label = "retail voices" if retail_voices else "mono"
        got, e = model(lines, not retail_voices)
        with tempfile.TemporaryDirectory() as tmp:
            exe = build_harness(tmp, retail_voices)
            scp = write_script(tmp, lines)
            out = Path(tmp) / "harness.txt"
            rc = run_harness(exe, scp, out)
            harness = out.read_text(encoding="latin-1").splitlines()

        if args.dump:
            d = Path(args.dump + ("" if retail_voices else "-mono"))
            d.parent.mkdir(parents=True, exist_ok=True)
            d.with_suffix(".model").write_text(NL.join(got) + NL)
            d.with_suffix(".harness").write_text(NL.join(harness) + NL)

        n = diff(got, harness)
        print("%s: %d ops, %d lines, %d differ" % (label, len(lines),
                                                   len(harness), n))
        for lab, pcs in (("eediv", e.eediv_pcs), ("eemul", e.eemul_pcs),
                         ("eesqrt", e.eesqrt_pcs)):
            if pcs:
                print("%s at %s" % (lab, " ".join("%08x" % p
                                                  for p in sorted(pcs))))
        bad |= bool(n or rc)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
