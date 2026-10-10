#!/usr/bin/env python3
"""Cross-check 3DS Files/source/soundscape.c and choppersound.c against the
retail image, SLES_507.31.

**The model** is retail's own SoundScape.obj and ChopperSound.obj run in
retail_model.RetailEmu with the EE's divide, product and root (eediv,
eemul, eesqrt): SoundArea's Initialize, IsPointInArea and
AreCamerasInArea; ReverbArea's Initialize; LoopingAmbient's Initialize,
ComputeAzimuth, UpdateUsingArea, UpdateUsingSoundSphere, Update and Mute;
OneShotAmbient's Initialize, Play, Update and Mute; SoundScape's
WillSoundRight, FindGoodReverbArea, Update, Mute, SetReverbVolume,
IsInsideReverbArea, UpdateReverbAreas, UpdateLoopingAmbient and
UpdateOneShotAmbient; sound_scape's two jumps; SoundScapeIsInsideTunnel;
the chunk's loader and unloader; and the static constructor that builds
the one-shots' second samples. Then ChopperSound's constructor,
destructor, AdjustForTunnelVolume, Update, Mute, DeactivateSound,
ActivateSound, sound::CreateChopperSound and the envelope's static
constructor. eIsPointInPoly, bASin, smooth and bMemSet run in the image
too, as emath.c, bmath.c and the port's own smooth do in the harness
(tools/src/soundscape_test.c).

**The fakes**, the same on both sides, each printing what it is handed:
bSample's constructor (which gives retail's its table), Initialize,
SetCategory (kept), Play, Stop, Pause, Mute, SetAzimuth, SetVolume,
SetPitch, IsPlaying (playing from Play to Stop, or as the script says;
asked of no sample it is silent and says no, as the port asks it of
none), GetVolume (1 unless the script says) and Fade; the delete through
bSample's table (the port's bsample_delete); bOMalloc on bSample's slot
pool (the port's bsample_new); bSound's Region and Driver, and bRegion's
Sample (the script names those missing); the driver's
PlatSetEffectVolume and bEffect's SetMode and SetParameter (the port's
three seams); the sound's random float and int (the script's queues);
GetInGameSample; GetActiveCameras (the script's pair); Topology's
GetElevation (the script's queue); BaseCarSound's ScaleRoadNoise; and
Sound3d's constructor, Update (the script's volume, pitch and azimuth)
and destructor, and bMalloc for the chopper's.

ChopperSound's constructor leaves its sample unwritten with sound off;
both sides' fresh records have it 0.

**The script** dumps the effect-mode table and the chopper's table; loads
a chunk of the wrong type, an empty one and one made to reach every case
-- areas of one and several faces, sounds 0 to 2, sources inside, outside
and absent, fades of 0, of a fraction of a millisecond and below 0,
deviations of 0, 360 and others, an unknown child -- and dumps each
record; loads one whose last record has size 0 and its body past the
container's end; asks IsPointInArea inside, outside, on edges and corners; runs
AreCamerasInArea with each pair; ComputeAzimuth each way round, ahead,
behind and on the source; each LoopingAmbient's Update with the region or
sample missing, every fade and state, one and two cameras, the sphere's
volume in and out and with sound off; each OneShotAmbient's Update
through its first play, its repeats over time, the 360 pair, no repeat
and samples missing; the mutes; WillSoundRight, FindGoodReverbArea,
SetReverbVolume with one and two players, IsInsideReverbArea through each
search and over overlapping areas, UpdateReverbAreas' smoothing, its mode and parameters, and each
elevation case with one and two players; the tunnel test; the update
with and without a race; unloads and reloads. Then every distinct
retail track's chunk, loaded and dumped, and four walked through with a
camera at every area. Then the chopper: created, constructed with sound
on, off, playing and missing, destroyed over a changed table, the
tunnel's fade through every branch, updated in and out of it, muted,
deactivated and activated.

    python tools/soundscape_check.py
    python tools/soundscape_check.py --mutate [--only a,b]
    python tools/soundscape_check.py --dump out/soundscape
"""
import argparse
import glob
import math
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

HARNESS = "tools/src/soundscape_test.c"
SSC = "3DS Files/source/soundscape.c"
CHS = "3DS Files/source/choppersound.c"
SOURCES = [HARNESS, SSC, CHS, "3DS Files/source/emath.c",
           "3DS Files/source/bmath.c", "3DS Files/source/bmathtab.c",
           "3DS Files/source/bmatrix.c", "3DS Files/source/bvector.c",
           "3DS Files/source/vtable.c"]
HARNESS_TIMEOUT = 60
LIMIT = 2000000
TRACKS = ROOT / "extracted-retail" / "TRACKS"

GP = retail_model.RETAIL_GP
F = {
    "pia": 0x001cde20, "aca": 0x001cdf30,
    "lcaz": 0x001ce218, "lua": 0x001ce2d8, "lus": 0x001ce478,
    "lupd": 0x001ce6b0, "lmute": 0x001ce780,
    "oplay": 0x001ce7f8, "oupd": 0x001ce9e0, "omute": 0x001ceb20,
    "wsr": 0x001ceb40, "fgra": 0x001ceb88, "update": 0x001cebf0,
    "mute": 0x001cebf8, "ssupdate": 0x001cec00, "ssmute": 0x001cec38,
    "srv": 0x001ced40, "iira": 0x001ced88, "ura": 0x001cee60,
    "ula": 0x001cf478, "uoa": 0x001cf4e8, "tunnel": 0x001cf698,
    "load": 0x001cf6a8, "unload": 0x001cf838, "sinit": 0x001cfe98,
    "hctor": 0x00214d68, "hdtor": 0x00214df0, "hadj": 0x00214e08,
    "hupd": 0x00214f30, "hmute": 0x00215000, "hdeact": 0x00215028,
    "hact": 0x00215050, "hcreate": 0x00215098, "hsinit": 0x00215598,
}

SE, WTE, RC, TRACK = GP - 23056, GP - 19560, GP - 22216, GP - 21952
BSOUND, SLOTPOOL, PLAYERS = GP - 13696, GP - 13816, GP - 20928
NPC = 0x0031a8c8
DJL, NREV, CUR, RON, RAIN = (GP - 18088, GP - 18084, GP - 18080,
                             GP - 18076, GP - 18072)
RVOL, RTGT, RPAN = GP - 18068, GP - 18064, GP - 18060
RMODE, DMODE = GP - 18056, GP - 18052
DELAY, DDELAY, FB, DFB = GP - 18048, GP - 18044, GP - 18040, GP - 18036
LEVEL, DLEVEL, DEPTH, DDEPTH = (GP - 18032, GP - 18028, GP - 18024,
                                GP - 18020)
NLOOP, NSHOT = GP - 17996, GP - 18000
LOOP, SHOT, REV, MODETAB = 0x00314688, 0x00314e88, 0x00317c80, 0x00317c48
LOOP_SIZE, SHOT_SIZE, REV_SIZE = 64, 244, 124
L_AREA, O_AREA, R_AREA = 32, 228, 8
O_S360 = 40
SAMPLE_SIZE, SAMPLE_VT, CATEGORY = 188, 184, 132
CAR_SIZE, CAR_POS, CAR_TC, CAR_BCS = 2208, 96, 1312, 2132
CAM_POS, CAM_DIR = 64, 80
TRACK_REGION = 132
HELI_SIZE, HELI_POS = 912, 832
HS_SIZE = 48

CH_VT = 0x002bc2a8
CH_VT_ENTRIES = 8
SOUND3D_VT = 0x002bb2b0
FNAME = {0x00214df0: "dtor", 0x00208b28: "s3dactivate",
         0x00214f30: "update", 0x00215000: "mute", 0x00215028: "deact",
         0x00215050: "act", 0x00208c78: "camrel"}


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
        self.slots = []
        self.regions, self.rsamples, self.srcs = {}, {}, {}
        self.noreg, self.nosmp, self.nosrc = set(), set(), set()
        self.playing = set()
        self.vols = {}
        self.rf, self.ri, self.elev, self.s3dq = [], [], [], []
        self.chunks, self.chunk_addr = {}, {}
        self.helis, self.hss = [], []
        self.bsound = e.alloc(16)
        self.driver = e.alloc(16)
        self.pool = e.alloc(16)
        self.cams = []
        for i in range(3):
            c = e.alloc(448, 16)
            e.mem[c:c + 448] = b"\0" * 448
            self.cams.append(c)
        self.acams = e.alloc(16, 16)
        e.mem[self.acams:self.acams + 8] = b"\0" * 8
        self.cars, self.players, self.bcss = [], [], []
        for i in range(2):
            c = e.alloc(CAR_SIZE, 16)
            e.mem[c:c + CAR_SIZE] = b"\0" * CAR_SIZE
            self.cars.append(c)
            p = e.alloc(16, 16)
            e.mem[p:p + 16] = b"\0" * 16
            e.put32(p + 4, c)
            self.players.append(p)
            self.bcss.append(e.alloc(16, 16))
        self.track = e.alloc(256, 16)
        e.mem[self.track:self.track + 256] = b"\0" * 256
        self.rc = e.alloc(16)
        self.scratch = e.alloc(64, 16)
        # bSample's table: the delete at 8.
        self.delete_fn = e.alloc(16, 16)
        self.bvt = e.alloc(32, 16)
        e.mem[self.bvt:self.bvt + 32] = b"\0" * 32
        e.put32(self.bvt + 12, self.delete_fn)
        e.put32(BSOUND, self.bsound)
        e.put32(SLOTPOOL, self.pool)
        e.put32(SE, 1)
        e.put32(WTE, 0)
        e.put32(RC, 0)
        e.put32(TRACK, self.track)
        e.put32(PLAYERS, 0)
        e.put32(PLAYERS + 4, 0)
        e.put32(NPC, 1)

        e.stub(0x00272ff0, self.b_ctor)
        e.stub(0x00273210, self.b_init)
        e.stub(0x00273618, self.b_cat)
        e.stub(0x00274080, self.b_play)
        e.stub(0x00274618, self.b_stop)
        e.stub(0x00274488, self.b_pause)
        e.stub(0x002747a0, self.b_mute)
        e.stub(0x00273e70, self.b_az)
        e.stub(0x00273d50, self.b_vol)
        e.stub(0x00273738, self.b_pitch)
        e.stub(0x00274410, self.b_isplaying)
        e.stub(0x00273f58, self.b_getvol)
        e.stub(0x00274868, self.b_fade)
        e.stub(self.delete_fn, self.b_delete)
        e.stub(0x00257c80, self.omalloc)
        e.stub(0x00277a18, self.region)
        e.stub(0x002719b8, self.rsample)
        e.stub(0x00277980, self.drv)
        e.stub(0x0025d4f8, self.effvol)
        e.stub(0x002703e8, self.effmode)
        e.stub(0x002705c0, self.effparam)
        e.stub(0x001af9c0, self.randf)
        e.stub(0x001af9a0, self.randi)
        e.stub(0x001ae280, self.ingame)
        e.stub(0x001cf268, self.gac)
        e.stub(0x00152070, self.elevation)
        e.stub(0x0018d6e8, self.roadnoise)
        e.stub(0x00208ae8, self.s3d_ctor)
        e.stub(0x00208cf0, self.s3d_update)
        e.stub(0x002091a0, self.s3d_dtor)
        e.stub(0x002577c0, self.malloc)
        e.stub(0x00114e98, self.unexpected("delete"))
        e.stub(0x00257850, self.unexpected("bfree"))
        e.stub(0x00273148, self.unexpected("bdtor"))

        # The static constructors: the one-shots' second samples, and the
        # chopper's envelope.
        self.call("sinit")
        self.call("hsinit")

    def emit(self, s):
        self.out.append(s)

    def unexpected(self, what):
        def fn(em):
            self.emit("  %s?" % what)
            return 0
        return fn

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
        if a == self.bsound:
            return "bsound"
        if a == self.driver:
            return "drv"
        if a == self.pool:
            return "pool"
        for i, p in enumerate(self.slots):
            if a == p:
                return "s%d" % i
        for nm, p in self.regions.items():
            if a == p:
                return "reg:" + nm
        for nm, p in self.rsamples.items():
            if a == p:
                return "r:" + nm
        for nm, p in self.srcs.items():
            if a == p:
                return "src:" + nm
        if SHOT <= a < SHOT + 48 * SHOT_SIZE \
                and (a - SHOT) % SHOT_SIZE == O_S360:
            return "x%d.360" % ((a - SHOT) // SHOT_SIZE)
        for i, c in enumerate(self.cams):
            if a == c:
                return "cam%d" % i
        for i, c in enumerate(self.cars):
            if a == c:
                return "car%d" % i
            if a == c + CAR_TC:
                return "car%d.tc" % i
        for i, c in enumerate(self.bcss):
            if a == c:
                return "bcs%d" % i
        for i, c in enumerate(self.helis):
            if a == c:
                return "h%d" % i
            if a == c + HELI_POS:
                return "h%d.pos" % i
        for i, c in enumerate(self.hss):
            if a == c:
                return "hs%d" % i
        for k in sorted(self.chunk_addr):
            base = self.chunk_addr[k]
            if base <= a < base + len(self.chunks[k]):
                return "ch%d+%d" % (k, a - base)
        return "?"

    def sample_ref(self, w):
        if w == "0":
            return 0
        if w.startswith("r:"):
            if w[2:] in self.rsamples:
                return self.rsamples[w[2:]]
        elif w.startswith("src:"):
            if w[4:] in self.srcs:
                return self.srcs[w[4:]]
        elif w[0] == "s" and w[1:].isdigit():
            i = int(w[1:])
            if i < len(self.slots):
                return self.slots[i]
        elif w[0] == "x" and w.endswith(".360"):
            return SHOT + int(w[1:-4]) * SHOT_SIZE + O_S360
        self.emit("  no sample %s" % w)
        return 0

    # ---- bSample

    def b_ctor(self, em):
        s = em.reg[4] & M32
        self.emit("  bctor %s" % self.name(s))
        if s:
            self.e.put32(s + SAMPLE_VT, self.bvt)
        return s

    def b_init(self, em):
        self.emit("  binit %s from %s" % (self.name(em.reg[4]),
                                          self.name(em.reg[5])))
        return 0

    def b_cat(self, em):
        s = em.reg[4] & M32
        self.emit("  bcat %s %d" % (self.name(s), em.reg[5] & M32))
        if s:
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

    def b_mute(self, em):
        self.emit("  bmute %s %d" % (self.name(em.reg[4]),
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
        if not s:
            return 0
        v = 1 if s in self.playing else 0
        self.emit("  bisplaying %s %d" % (self.name(s), v))
        return v

    def b_getvol(self, em):
        s = em.reg[4] & M32
        v = self.vols.get(s, 0x3f800000)
        self.emit("  bgetvol %s -> %08x" % (self.name(s), v))
        em.fpr[0] = v
        return 0

    def b_fade(self, em):
        self.emit("  bfade %s %08x %d" % (self.name(em.reg[4]), em.fpr[12],
                                          em.reg[5] & M32))
        return 0

    def b_delete(self, em):
        flags = em.reg[5] & M32
        self.emit("  bdelete %s%s" % (self.name(em.reg[4]),
                                      "" if flags == 3
                                      else " flags=%d" % flags))
        return 0

    def omalloc(self, em):
        e = self.e
        p = e.alloc(SAMPLE_SIZE, 16)
        e.mem[p:p + SAMPLE_SIZE] = b"\xa5" * SAMPLE_SIZE
        self.slots.append(p)
        self.emit("  omalloc %s -> %s" % (self.name(em.reg[4]),
                                          self.name(p)))
        return p

    # ---- bSound, its regions and its driver

    def region(self, em):
        nm = self.cstr(em.reg[5] & M32)
        self.emit("  region %s %s" % (self.name(em.reg[4]), nm))
        if nm in self.noreg:
            return 0
        if nm not in self.regions:
            self.regions[nm] = self.e.alloc(16, 16)
        return self.regions[nm]

    def rsample(self, em):
        nm = self.cstr(em.reg[5] & M32)
        self.emit("  rsample %s %s" % (self.name(em.reg[4]), nm))
        if nm in self.nosmp:
            return 0
        if nm not in self.rsamples:
            s = self.e.alloc(SAMPLE_SIZE, 16)
            self.e.mem[s:s + SAMPLE_SIZE] = b"\0" * SAMPLE_SIZE
            self.rsamples[nm] = s
        return self.rsamples[nm]

    def drv(self, em):
        if em.reg[4] & M32 != self.bsound:
            self.emit("  driver: not bsound")
        return self.driver

    def effvol(self, em):
        if em.reg[4] & M32 != self.driver:
            self.emit("  effvol: not the driver")
        self.emit("  effvol %08x %d %08x %08x" % (
            em.reg[5] & M32, em.reg[6] & M32, em.fpr[12], em.fpr[13]))
        return 0

    def effmode(self, em):
        self.emit("  effmode %d" % (em.reg[4] & M32))
        return 0

    def effparam(self, em):
        self.emit("  effparam %d %d %08x" % (em.reg[4] & M32,
                                             em.reg[5] & M32, em.fpr[12]))
        return 0

    # ---- the sound module

    def randf(self, em):
        v = self.rf.pop(0) if self.rf else 0
        self.emit("  randf %08x -> %08x" % (em.fpr[12], v))
        em.fpr[0] = v
        return 0

    def randi(self, em):
        v = self.ri.pop(0) if self.ri else 0
        self.emit("  randi %d -> %d" % (s32(em.reg[4]), v))
        return v

    def ingame(self, em):
        nm = self.cstr(em.reg[4] & M32)
        self.emit("  ingame %s" % nm)
        if nm in self.nosrc:
            return 0
        if nm not in self.srcs:
            s = self.e.alloc(SAMPLE_SIZE, 16)
            self.e.mem[s:s + SAMPLE_SIZE] = b"\0" * SAMPLE_SIZE
            self.srcs[nm] = s
        return self.srcs[nm]

    # ---- the rest it calls

    def gac(self, em):
        self.emit("  gac")
        return self.acams

    def elevation(self, em):
        e = self.e
        p = em.reg[5] & M32
        v = self.elev.pop(0) if self.elev else 0
        self.emit("  elev %s %08x %08x %08x %s%s%s -> %08x" % (
            self.name(em.reg[4]), e.u32(p), e.u32(p + 4), e.u32(p + 8),
            "t" if em.reg[6] & M32 else "-", "n" if em.reg[7] & M32 else "-",
            "f" if em.reg[8] & M32 else "-", v))
        em.fpr[0] = v
        return 0

    def roadnoise(self, em):
        self.emit("  roadnoise %s %08x" % (self.name(em.reg[4]), em.fpr[12]))
        return 0

    def s3d_ctor(self, em):
        e = self.e
        s = em.reg[4] & M32
        self.emit("  s3dctor %s" % self.name(s))
        e.put32(s, 0)
        e.put32(s + 4, 1)
        e.put32(s + 8, 0x3f800000)
        e.put32(s + 12, 0x3f800000)
        e.put32(s + 16, 0)
        e.put32(s + 20, 0)
        e.put32(s + 24, 0)
        e.put32(s + 28, SOUND3D_VT)
        return s

    def s3d_update(self, em):
        e = self.e
        s, env = em.reg[4] & M32, em.reg[6] & M32
        self.emit("  s3dupd %s %s %08x %08x %08x" % (
            self.name(s), self.name(em.reg[5]), e.u32(env), e.u32(env + 4),
            e.u32(env + 8)))
        if self.s3dq:
            vol, pitch, az = self.s3dq.pop(0)
            e.put32(s + 8, vol)
            e.put32(s + 12, pitch)
            struct.pack_into("<H", e.mem, s + 16, az & 0xffff)
        return 0

    def s3d_dtor(self, em):
        self.emit("  s3ddtor %s %d" % (self.name(em.reg[4]),
                                       s32(em.reg[5])))
        return 0

    def malloc(self, em):
        e = self.e
        p = e.alloc(HS_SIZE, 16)
        e.mem[p:p + HS_SIZE] = b"\xa5" * HS_SIZE
        e.put32(p + 36, 0)
        self.hss.append(p)
        self.emit("  malloc size-%s %s %d %d -> %s" % (
            "ok" if s32(em.reg[4]) == HS_SIZE else "BAD",
            self.cstr(em.reg[5] & M32), s32(em.reg[6]), s32(em.reg[7]),
            self.name(p)))
        return p

    # ---- the dumps

    def dump_globals(self):
        e = self.e
        self.emit("  gd djl=%d nrev=%d cur=%d ron=%d rain=%s vol=%08x"
                  " tgt=%08x pan=%08x nloop=%d nshot=%d" % (
                      s32(e.u32(DJL)), s32(e.u32(NREV)), s32(e.u32(CUR)),
                      s32(e.u32(RON)), self.name(e.u32(RAIN)),
                      e.u32(RVOL), e.u32(RTGT), e.u32(RPAN),
                      s32(e.u32(NLOOP)), s32(e.u32(NSHOT))))
        self.emit("  gd mode=%d/%d delay=%08x/%08x fb=%08x/%08x"
                  " level=%08x/%08x depth=%08x/%08x" % (
                      s32(e.u32(RMODE)), s32(e.u32(DMODE)),
                      e.u32(DELAY), e.u32(DDELAY), e.u32(FB), e.u32(DFB),
                      e.u32(LEVEL), e.u32(DLEVEL), e.u32(DEPTH),
                      e.u32(DDEPTH)))

    def area_str(self, a):
        e = self.e
        return "area %d %s %d %s" % (s32(e.u32(a)), self.name(e.u32(a + 4)),
                                     s32(e.u32(a + 8)),
                                     self.name(e.u32(a + 12)))

    def dump_reverb(self, i):
        e = self.e
        r = REV + REV_SIZE * i
        n = s32(e.u32(r + 24))
        s = ["  rd %d %s reverb=%d %s sounds=%d" % (
            i, self.name(e.u32(r)), s32(e.u32(r + 4)),
            self.area_str(r + R_AREA), n)]
        for k in range(max(0, min(n, 8))):
            d = r + 28 + 12 * k
            s.append(" (%s %08x %08x)" % (self.name(e.u32(d)), e.u32(d + 4),
                                          e.u32(d + 8)))
        self.emit("".join(s))

    def dump_looping(self, i):
        e = self.e
        l = LOOP + LOOP_SIZE * i
        self.emit("  ld %d %s %s fade=%d/%d active=%d src=%d sphere=%d"
                  " sample=%s %s at=%08x,%08x coeff=%08x radius=%08x" % (
                      i, self.name(e.u32(l)), self.name(e.u32(l + 4)),
                      s32(e.u32(l + 8)), s32(e.u32(l + 12)),
                      s32(e.u32(l + 16)), s32(e.u32(l + 20)),
                      s32(e.u32(l + 24)), self.name(e.u32(l + 28)),
                      self.area_str(l + L_AREA), e.u32(l + 48),
                      e.u32(l + 52), e.u32(l + 56), e.u32(l + 60)))

    def dump_oneshot(self, i):
        e = self.e
        o = SHOT + SHOT_SIZE * i
        self.emit("  od %d %s %s repeat=%08x/%08x pitch=%08x/%08x az=%08x"
                  " active=%d time=%08x sample=%s %s cat360=%d" % (
                      i, self.name(e.u32(o)), self.name(e.u32(o + 4)),
                      e.u32(o + 8), e.u32(o + 12), e.u32(o + 16),
                      e.u32(o + 20), e.u32(o + 24), s32(e.u32(o + 28)),
                      e.u32(o + 32), self.name(e.u32(o + 36)),
                      self.area_str(o + O_AREA),
                      s32(e.u32(o + O_S360 + CATEGORY))))

    def dump_modes(self):
        e = self.e
        self.emit("  mt" + "".join(" %d" % e.u32(MODETAB + 4 * k)
                                   for k in range(13)))

    def dump_tables(self):
        e = self.e
        self.emit("  vt %d entries" % CH_VT_ENTRIES)
        for k in range(1, CH_VT_ENTRIES):
            d = s16(e.u16(CH_VT + 8 * k))
            fn = e.u32(CH_VT + 8 * k + 4)
            self.emit("  vt %d %d %s" % (8 * k, d, FNAME.get(fn, "?")))

    def dump_hs(self, i):
        e = self.e
        s = self.hss[i]
        self.emit("  hd %s act=%d dop=%d vol=%08x pitch=%08x az=%d vel=%08x"
                  " dist=%08x vt=%08x heli=%s sample=%s in=%d counter=%08x"
                  % (self.name(s), s32(e.u32(s)), s32(e.u32(s + 4)),
                     e.u32(s + 8), e.u32(s + 12), e.u16(s + 16),
                     e.u32(s + 20), e.u32(s + 24), e.u32(s + 28),
                     self.name(e.u32(s + 32)), self.name(e.u32(s + 36)),
                     s32(e.u32(s + 40)), e.u32(s + 44)))

    # ---- the ops

    def call(self, name, *args):
        return self.e.call(F[name], *args, limit=LIMIT)

    def area_of(self, kind, i):
        if kind == "r":
            return REV + REV_SIZE * i + R_AREA
        if kind == "l":
            return LOOP + LOOP_SIZE * i + L_AREA
        return SHOT + SHOT_SIZE * i + O_AREA

    def chunk_at(self, k):
        e = self.e
        if k not in self.chunk_addr:
            n = len(self.chunks[k])
            a = e.alloc(n + 16, 16)
            e.write(a, bytes(self.chunks[k]))
            self.chunk_addr[k] = a
        return self.chunk_addr[k]

    def car_ref(self, k):
        return 0 if k < 0 else self.cars[k]

    def op(self, f):
        e = self.e

        def i(k):
            return int(f[k], 0) if k < len(f) else 0

        def fb(k):
            return int(f[k], 16) & M32 if k < len(f) else 0

        o = f[0]
        if o == "tables":
            self.dump_tables()
        elif o == "mt":
            self.dump_modes()
        elif o == "se":
            e.put32(SE, i(1))
        elif o == "wte":
            e.put32(WTE, fb(1))
        elif o == "rc":
            e.put32(RC, self.rc if i(1) else 0)
        elif o == "npc":
            e.put32(NPC, i(1))
        elif o == "track":
            nm = f[1].encode("latin-1")[:31]
            e.write(self.track + TRACK_REGION, nm.ljust(32, b"\0"))
        elif o == "cam":
            c = self.cams[i(1)]
            for j in range(3):
                e.put32(c + CAM_POS + 4 * j, fb(2 + j))
            e.put32(c + CAM_DIR, fb(5))
            e.put32(c + CAM_DIR + 4, fb(6))
        elif o == "cams":
            for j in range(2):
                k = i(1 + j)
                e.put32(self.acams + 4 * j, 0 if k < 0 else self.cams[k])
        elif o == "player":
            e.put32(PLAYERS + 4 * i(1), self.players[i(1)] if i(2) else 0)
        elif o == "carpos":
            c = self.cars[i(1)]
            for j in range(3):
                e.put32(c + CAR_POS + 4 * j, fb(2 + j))
        elif o == "carsnd":
            c = self.cars[i(1)]
            e.put32(c + CAR_BCS, self.bcss[i(1)] if i(2) else 0)
        elif o == "elev":
            self.elev.append(fb(1))
        elif o == "rf":
            self.rf.append(fb(1))
        elif o == "ri":
            self.ri.append(i(1))
        elif o == "noreg":
            self.noreg.add(f[1])
        elif o == "unreg":
            self.noreg.clear()
        elif o == "nosmp":
            self.nosmp.add(f[1])
        elif o == "unsmp":
            self.nosmp.clear()
        elif o == "nosrc":
            self.nosrc.add(f[1])
        elif o == "unsrc":
            self.nosrc.clear()
        elif o == "bplaying":
            s = self.sample_ref(f[1])
            if i(2):
                self.playing.add(s)
            else:
                self.playing.discard(s)
        elif o == "bgv":
            self.vols[self.sample_ref(f[1])] = fb(2)
        elif o == "cnew":
            self.chunks[i(1)] = bytearray()
        elif o == "cb":
            self.chunks[i(1)] += bytes.fromhex(f[2])
        elif o == "load":
            self.emit("  = %d" % self.call("load", self.chunk_at(i(1))))
        elif o == "unload":
            self.emit("  = %d" % self.call("unload", self.chunk_at(i(1))))
        elif o == "cur":
            e.put32(CUR, i(1) & M32)
        elif o == "djl":
            e.put32(DJL, i(1))
        elif o == "ron":
            e.put32(RON, i(1))
        elif o == "rv":
            e.put32(RVOL, fb(1))
            e.put32(RTGT, fb(2))
            e.put32(RPAN, fb(3))
        elif o == "rain":
            e.put32(RAIN, self.sample_ref(f[1]))
        elif o == "desired":
            e.put32(DMODE, i(1))
            e.put32(DDELAY, fb(2))
            e.put32(DFB, fb(3))
            e.put32(DLEVEL, fb(4))
            e.put32(DDEPTH, fb(5))
        elif o == "pia":
            p = self.scratch
            e.put32(p, fb(3))
            e.put32(p + 4, fb(4))
            self.emit("  = %d" % self.call("pia", self.area_of(f[1], i(2)),
                                           p))
        elif o == "aca":
            cnt = self.scratch + 16
            e.put32(cnt, 0x5a5a5a5a)
            r = self.call("aca", self.area_of(f[1], i(2)), self.acams, cnt)
            self.emit("  = %d %s %s" % (s32(e.u32(cnt)),
                                        self.name(e.u32(r)),
                                        self.name(e.u32(r + 4))))
        elif o == "lcaz":
            r = self.call("lcaz", LOOP + LOOP_SIZE * i(1), self.cams[i(2)])
            self.emit("  = %d" % (r & 0xffff))
        elif o in ("lua", "lus", "lupd"):
            self.call(o, LOOP + LOOP_SIZE * i(1), self.acams)
        elif o == "lmute":
            self.call("lmute", LOOP + LOOP_SIZE * i(1), i(2))
        elif o == "oplay":
            self.call("oplay", SHOT + SHOT_SIZE * i(1))
        elif o == "oupd":
            self.call("oupd", SHOT + SHOT_SIZE * i(1), self.acams)
        elif o == "omute":
            self.call("omute", SHOT + SHOT_SIZE * i(1), i(2))
        elif o == "wsr":
            self.emit("  = %d" % self.call("wsr", i(1), self.car_ref(i(2))))
        elif o == "fgra":
            self.emit("  = %d" % self.call("fgra", self.car_ref(i(1))))
        elif o == "srv":
            e.fpr[12] = fb(1)
            self.call("srv", self.car_ref(i(2)))
        elif o == "iira":
            p = self.scratch + 32
            e.put32(p, self.car_ref(i(1)))
            e.put32(p + 4, self.car_ref(i(2)))
            r = self.call("iira", p)
            self.emit("  = %d cur=%d djl=%d" % (r, s32(e.u32(CUR)),
                                                s32(e.u32(DJL))))
        elif o in ("ura", "ula", "uoa", "update", "ssupdate"):
            self.call(o)
        elif o in ("mute", "ssmute"):
            self.call(o, i(1))
        elif o == "tunnel":
            self.emit("  = %d" % self.call("tunnel"))
        elif o == "gd":
            self.dump_globals()
        elif o == "rd":
            self.dump_reverb(i(1))
        elif o == "ld":
            self.dump_looping(i(1))
        elif o == "od":
            self.dump_oneshot(i(1))
        # ---- the chopper
        elif o == "heli":
            h = e.alloc(HELI_SIZE, 16)
            e.mem[h:h + HELI_SIZE] = b"\0" * HELI_SIZE
            self.helis.append(h)
        elif o == "hcreate":
            r = self.call("hcreate", self.helis[i(1)])
            self.emit("  -> %s" % self.name(r))
        elif o == "hctor":
            p = e.alloc(HS_SIZE, 16)
            e.mem[p:p + HS_SIZE] = b"\xa5" * HS_SIZE
            e.put32(p + 36, 0)
            self.hss.append(p)
            self.call("hctor", p, self.helis[i(1)])
        elif o == "hdtor":
            self.call("hdtor", self.hss[i(1)], i(2))
        elif o == "hset":
            s = self.hss[i(1)]
            e.put32(s, i(2))
            e.put32(s + 8, fb(3))
            e.put32(s + 12, fb(4))
            struct.pack_into("<H", e.mem, s + 16, i(5) & 0xffff)
        elif o == "hsamp":
            e.put32(self.hss[i(1)] + 36, self.sample_ref(f[2]))
        elif o == "hvt":
            e.put32(self.hss[i(1)] + 28, fb(2))
        elif o == "htun":
            s = self.hss[i(1)]
            e.put32(s + 40, i(2))
            e.put32(s + 44, fb(3))
        elif o == "hadj":
            p = self.scratch + 48
            e.put32(p, fb(2))
            self.call("hadj", self.hss[i(1)], p)
            self.emit("  = %08x" % e.u32(p))
        elif o == "s3d":
            self.s3dq.append((fb(1), fb(2), i(3)))
        elif o == "hupd":
            e.fpr[12] = 0x12345678
            e.fpr[13] = 0x9abcdef0
            self.call("hupd", self.hss[i(1)], 0x4321)
        elif o == "hmute":
            self.call("hmute", self.hss[i(1)], i(2))
        elif o in ("hdeact", "hact"):
            self.call(o, self.hss[i(1)])
        elif o == "hd":
            self.dump_hs(i(1))
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


# ================================================================ chunks

def name32(s):
    return s.encode("latin-1")[:31].ljust(32, b"\0")


def area_bytes(verts, faces):
    return (struct.pack("<i", len(verts))
            + b"".join(struct.pack("<2f", *v) for v in verts)
            + struct.pack("<i", len(faces))
            + b"".join(struct.pack("<3i", *t) for t in faces))


def child(t, payload):
    return struct.pack("<II", t, len(payload)) + payload


def reverb(nm, rev, verts, faces, sounds):
    return child(0x00038010, name32(nm) + struct.pack("<i", rev)
                 + area_bytes(verts, faces) + struct.pack("<i", len(sounds))
                 + b"".join(name32(s) + struct.pack("<2f", p, d)
                            for s, p, d in sounds))


def looping(nm, smp, fi, fo, hs, sx, sy, coeff, verts, faces):
    return child(0x00038020, name32(nm) + name32(smp)
                 + struct.pack("<2fi3f", fi, fo, hs, sx, sy, coeff)
                 + area_bytes(verts, faces))


def oneshot(nm, smp, rep, rdev, pitch, pdev, adev, verts, faces):
    return child(0x00038030, name32(nm) + name32(smp)
                 + struct.pack("<5f", rep, rdev, pitch, pdev, adev)
                 + area_bytes(verts, faces))


def container(children, t=0x80038000):
    body = b"".join(children)
    return struct.pack("<II", t, len(body)) + body


def sq(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], [(0, 1, 2), (0, 2, 3)]


def scene_chunk():
    tri = [(20.0, 0.0), (30.0, 0.0), (25.0, 10.0)], [(0, 1, 2)]
    pent = ([(150.0, 0.0), (170.0, 5.0), (175.0, 25.0), (160.0, 40.0),
             (145.0, 20.0)], [(0, 1, 2), (0, 2, 3), (0, 3, 4)])
    near = sq(0.0, 0.0, 100.0, 100.0)
    far = sq(200.0, 200.0, 300.0, 300.0)
    return container([
        reverb("Tunnel0", 1, *sq(0.0, 0.0, 10.0, 10.0),
               sounds=[("Drip", 5.0, 2.0)]),
        looping("Wind", "Wind", 1.5, 0.25, 0, 0.0, 0.0, 0.0, *near),
        oneshot("Bird", "Bird", 5.0, 2.0, 0.1, 0.2, 90.0, *near),
        child(0x00038040, b"\x01" * 12),
        looping("River", "Stream", 1.0, 1.0, 1, 50.0, 50.0, 0.01, *near),
        reverb("Tunnel1", 2, *tri, sounds=[]),
        oneshot("Thunder", "Thunder", 12.0, 0.0, 0.0, 0.0, 360.0, *near),
        looping("Crowd", "Crowd", 0.0, 0.0, 1, 500.0, 500.0, 0.002, *far),
        looping("Fire", "ForestFire", 0.0015, -0.5, 0, 250.0, 250.0, 0.0,
                *far),
        oneshot("Dog", "Dog", 0.0, 1.0, 0.5, 0.0, 0.0, *far),
        reverb("Overpass", 3, *sq(5.0, 5.0, 15.0, 15.0),
               sounds=[("Drip", 1.0, 0.5), ("Echo", 2.0, 1.0)]),
        looping("Hum", "Hum", 0.5, 0.5, 0, 0.0, 0.0, 0.0, *near),
        oneshot("Owl", "Owl", -1.0, 0.0, 0.0, 0.3, 360.0, *far),
        looping("Fountain", "Fountain", 0.2, 0.2, 1, 160.0, 20.0, 0.05,
                *pent),
        oneshot("Gull", "Gull", 3.0, 0.0, 0.0, 0.0, 360.0, *near),
        child(0x00038000, b""),
    ])


def track_chunks():
    """Every distinct retail SoundScape chunk, by the first track that has
    it."""
    seen, out = set(), []
    for path in sorted(glob.glob(str(TRACKS / "TRACKB*.BUN"))):
        b = open(path, "rb").read()
        found = []

        def walk(s, e):
            p = s
            while p + 8 <= e and not found:
                t, n = struct.unpack_from("<II", b, p)
                if t == 0x80038000:
                    found.append(b[p:p + 8 + n])
                    return
                if t & 0x80000000:
                    walk(p + 8, p + 8 + n)
                p += 8 + n
        walk(0, len(b))
        if found and found[0] not in seen:
            seen.add(found[0])
            out.append((os.path.basename(path)[:-4], found[0]))
    return out


def parse_chunk(c):
    """The records' counts and each area's first face's centre."""
    def area(p):
        nv, = struct.unpack_from("<i", c, p)
        verts = [struct.unpack_from("<2f", c, p + 4 + 8 * k)
                 for k in range(nv)]
        q = p + 4 + 8 * nv
        nf, = struct.unpack_from("<i", c, q)
        faces = [struct.unpack_from("<3i", c, q + 4 + 12 * k)
                 for k in range(nf)]
        if not faces:
            return None
        t = faces[0]
        return (sum(verts[j][0] for j in t) / 3.0,
                sum(verts[j][1] for j in t) / 3.0)

    rev, loop, shot = [], [], []
    p = 8
    while p < len(c):
        t, n = struct.unpack_from("<II", c, p)
        if t == 0x00038010:
            rev.append(area(p + 44))
        elif t == 0x00038020:
            loop.append(area(p + 96))
        elif t == 0x00038030:
            shot.append(area(p + 92))
        p += 8 + n
    return rev, loop, shot


# ================================================================ script

def script():
    L = []
    a = L.append

    def chunk(k, data):
        a("cnew|%d" % k)
        for o in range(0, len(data), 200):
            a("cb|%d|%s" % (k, data[o:o + 200].hex()))

    def cam(i, x, y, z=0.0, hx=1.0, hy=0.0):
        a("cam|%d|%s|%s|%s|%s|%s" % (i, fx(x), fx(y), fx(z), fx(hx), fx(hy)))

    def cams(i, j):
        a("cams|%d|%d" % (i, j))

    def carpos(i, x, y, z=0.0):
        a("carpos|%d|%s|%s|%s" % (i, fx(x), fx(y), fx(z)))

    def elev(*v):
        for x in v:
            a("elev|%s" % fx(x))

    def rf(*v):
        for x in v:
            a("rf|%s" % fx(x))

    def ri(*v):
        for x in v:
            a("ri|%d" % x)

    def dump_all(nr, nl, no):
        a("gd")
        for k in range(nr):
            a("rd|%d" % k)
        for k in range(nl):
            a("ld|%d" % k)
        for k in range(no):
            a("od|%d" % k)

    # The tables, the globals.
    a("tables")
    a("mt")
    a("gd")

    # A chunk of the wrong type neither loads nor unloads; an empty one
    # loads nothing.
    chunk(1, container([looping("X", "X", 0, 0, 0, 0, 0, 0,
                                *sq(0.0, 0.0, 1.0, 1.0))], t=0x80038001))
    chunk(2, container([]))
    a("cur|5")
    a("load|1")
    a("gd")
    a("unload|1")
    a("gd")
    a("load|2")
    a("gd")

    # The scene.
    chunk(0, scene_chunk())
    a("load|0")
    dump_all(3, 6, 5)
    a("track|SceneRegion")

    # IsPointInArea: inside, outside, corners and edges.
    for kind, k, pts in (
            ("r", 0, ((5, 5), (-1, 5), (0, 0), (10, 5), (5, 10), (10, 10),
                      (0, 5), (5, 0), (10.001, 5), (9.999, 9.999),
                      (5, 5.0001))),
            ("r", 1, ((25, 5), (25, 10), (20, 0), (22, 1), (30, 0),
                      (22.5, 5), (27.5, 5), (27.6, 5), (25, -0.001))),
            ("r", 2, ((12, 12), (4, 4), (15, 15))),
            ("l", 5, ((160, 20), (150, 0), (176, 25), (147, 20), (165, 38),
                      (172, 3))),
            ("o", 1, ((50, 50), (101, 50)))):
        for x, y in pts:
            a("pia|%s|%d|%s|%s" % (kind, k, fx(x), fx(y)))

    # AreCamerasInArea, each pair.
    cam(0, 5.0, 5.0)
    cam(1, 50.0, 50.0)
    cam(2, -5.0, -5.0)
    for i, j in ((0, 1), (-1, 0), (1, 0), (-1, -1), (2, 2), (0, 0), (2, 1),
                 (1, -1)):
        cams(i, j)
        a("aca|r|0")
        a("aca|l|0")

    # ComputeAzimuth on the crowd at (500, 500): each way round, ahead,
    # behind, unnormalised, on the source.
    for x, y, hx, hy in ((250, 250, 1, 0), (250, 250, 0, 1),
                         (250, 250, -1, 0), (250, 250, 0, -1),
                         (250, 250, 0.6, 0.8), (400, 500, 1, 0),
                         (600, 500, 1, 0), (500, 400, 0, 1),
                         (500, 600, 0, 1), (250, 250, 2, 0),
                         (499.9, 500, 1, 0), (500, 500, 1, 0),
                         (210, 290, 0.8, -0.6), (-1000, 3, 0.70710677,
                                                 0.70710677),
                         (500.5, 499.5, -0.6, 0.8)):
        cam(2, float(x), float(y), 7.0, float(hx), float(hy))
        a("lcaz|2|2")

    # LoopingAmbient: the region missing, then the sample.
    cams(-1, -1)
    a("noreg|SceneRegion")
    a("lupd|0")
    a("ld|0")
    a("unreg")
    a("nosmp|Hum")
    a("lupd|4")
    a("ld|4")
    cams(0, -1)
    a("lupd|4")
    a("ld|4")
    cams(-1, -1)

    # The wind: no source, fading in and out.
    a("lupd|0")
    a("ld|0")
    cams(0, -1)
    a("lupd|0")
    a("ld|0")
    a("lupd|0")
    cams(-1, -1)
    a("lupd|0")
    a("ld|0")
    a("lupd|0")
    a("bgv|s0|00000000")
    a("lupd|0")
    a("lupd|0")
    a("se|0")
    cams(-1, 0)
    a("lupd|0")
    a("ld|0")
    a("se|1")
    cams(-1, -1)
    a("lupd|0")

    # The crowd: a source outside its area, no fades.
    cam(0, 250.0, 250.0, 0.0, 1.0, 0.0)
    cam(1, 210.0, 290.0, 0.0, 0.0, 1.0)
    cams(0, -1)
    a("lupd|2")
    a("ld|2")
    a("lupd|2")
    cams(0, 1)
    a("lupd|2")
    cam(1, 290.0, 211.0, 0.0, 0.6, -0.8)
    a("lupd|2")
    cams(1, 0)
    a("lupd|2")
    cams(-1, -1)
    a("lupd|2")
    a("ld|2")
    a("se|0")
    cams(1, -1)
    a("lupd|2")
    a("se|1")
    cams(-1, -1)
    a("lupd|2")

    # The fire: a fade under a millisecond, and one below 0.
    cams(0, -1)
    a("lupd|3")
    a("ld|3")
    cams(-1, -1)
    a("lupd|3")
    a("ld|3")

    # The river's sphere.
    a("lupd|1")
    a("ld|1")
    for pts in (((60.0, 50.0),), ((60.0, 50.0),),
                ((60.0, 50.0), (50.0, 110.0)),
                ((60.0, 50.0), (50.0, 121.0)),
                ((50.0, 121.0), (0.0, 0.0)),
                ((0.001, 0.001), (99.0, 99.0)),
                ((30.0, 70.0), (49.0, 51.0)),
                ((150.0, 50.0),), ((150.0, 50.0),)):
        for k, (x, y) in enumerate(pts):
            cam(k, x, y, 3.0, 0.0, -1.0)
        cams(0, 1 if len(pts) > 1 else -1)
        a("lupd|1")
    cam(0, 55.0, 45.0, 0.0, 1.0, 0.0)
    cams(0, -1)
    a("se|0")
    a("lupd|1")
    a("se|1")
    a("lus|1")
    a("lua|1")
    a("lua|1")
    a("ld|1")
    cams(-1, -1)
    a("lus|1")

    # The fountain's sphere, over a pentagon.
    cam(0, 160.0, 20.0, 0.0, 0.0, 1.0)
    cam(1, 171.0, 24.0, 0.0, -1.0, 0.0)
    cams(0, 1)
    a("lupd|5")
    a("lupd|5")
    a("ld|5")

    # The mutes.
    for k, on in ((0, 1), (0, 0), (0, 2), (4, 1), (2, 1), (1, 0)):
        a("lmute|%d|%d" % (k, on))

    # OneShotAmbient. The bird: deviations of all three.
    cam(0, 5.0, 5.0, 0.0, 1.0, 0.0)
    cams(-1, -1)
    a("oupd|0")
    a("od|0")
    cams(0, -1)
    rf(0.05, 1.5)
    ri(12345)
    a("oupd|0")
    a("od|0")
    for t in (1.0, 2.5, 0.25, 0.5, 0.0, 3.0):
        a("wte|%s" % fx(t))
        rf(0.15, 0.5)
        ri(0x12345)
        a("oupd|0")
        a("od|0")
    cams(-1, -1)
    a("oupd|0")
    a("od|0")
    cams(0, 0)
    rf(0.01, 0.02)
    ri(65535)
    a("oupd|0")
    a("od|0")

    # The thunder: the 360 pair, no deviations.
    a("wte|%s" % fx(5.0))
    a("oupd|1")
    a("od|1")
    for k in range(3):
        a("oupd|1")
        a("od|1")
    a("wte|%s" % fx(4.0))
    for k in range(4):
        a("oupd|1")
        a("od|1")
    a("se|0")
    a("oplay|1")
    a("od|1")
    a("se|1")

    # The dog: no repeat. The owl's sample and the gull's region missing.
    cam(1, 250.0, 250.0, 0.0, 0.0, 1.0)
    cams(1, -1)
    a("oupd|2")
    a("od|2")
    a("oupd|2")
    a("od|2")
    a("nosmp|Owl")
    a("oupd|3")
    a("od|3")
    a("oplay|3")
    a("noreg|SceneRegion")
    a("oupd|4")
    a("od|4")
    a("unreg")
    a("unsmp")
    for k, on in ((0, 1), (0, 0), (1, 3), (3, 1), (4, 0)):
        a("omute|%d|%d" % (k, on))

    # The reverb areas: WillSoundRight, FindGoodReverbArea.
    carpos(0, 5.0, 5.0)
    carpos(1, 25.0, 5.0)
    for k, c in ((0, 0), (1, 0), (2, 0), (3, 0), (1, 1), (0, 1), (5, 1)):
        a("wsr|%d|%d" % (k, c))
    for x, y in ((5, 5), (12, 12), (7, 7), (50, 50), (25, 5), (10, 10)):
        carpos(0, float(x), float(y))
        a("fgra|0")
    chunk(3, container([reverb("R%d" % k, k, *sq(0.0, 0.0, 10.0, 10.0),
                                sounds=[]) for k in range(4)]))
    a("load|3")
    carpos(0, 5.0, 5.0)
    a("cur|2")
    a("djl|0")
    a("iira|0|1")
    a("gd")
    tail = reverb("Tail", 7, *sq(0.0, 0.0, 4.0, 4.0), sounds=[])
    chunk(4, container([reverb("Head", 6, *sq(0.0, 0.0, 2.0, 2.0),
                               sounds=[]),
                        struct.pack("<II", 0x00038010, 0)]) + tail[8:])
    a("load|4")
    a("gd")
    a("rd|0")
    a("rd|1")
    a("load|0")
    dump_all(4, 6, 5)
    carpos(0, 5.0, 5.0)
    a("wsr|3|0")
    a("wsr|2|0")

    # SetReverbVolume with one and two players.
    a("srv|%s|-1" % fx(0.5))
    a("gd")
    a("npc|2")
    a("carsnd|0|1")
    a("srv|%s|0" % fx(0.5))
    a("srv|%s|0" % fx(-1.0))
    a("carsnd|0|0")
    a("srv|%s|0" % fx(0.5))
    a("srv|%s|-1" % fx(0.5))
    a("gd")
    a("npc|1")
    a("srv|%s|0" % fx(0.25))
    a("gd")
    a("carsnd|0|1")
    a("srv|%s|0" % fx(0.75))
    a("gd")
    a("carsnd|0|0")

    # IsInsideReverbArea through each search.
    def iira(cur, djl, p0, p1, c0, c1):
        a("cur|%d" % cur)
        a("djl|%d" % djl)
        if p0 is not None:
            carpos(0, *p0)
        if p1 is not None:
            carpos(1, *p1)
        a("iira|%d|%d" % (c0, c1))

    iira(-1, 0, (5.0, 5.0), None, 0, -1)
    iira(0, 1, (5.0, 5.0), None, 0, -1)
    iira(0, 0, (5.0, 5.0), None, 0, -1)
    iira(0, 0, (12.0, 12.0), None, 0, -1)
    iira(0, 0, (5.0, 5.0), (25.0, 5.0), 0, 1)
    iira(0, 0, (5.0, 5.0), (6.0, 6.0), 0, 1)
    iira(-1, 0, (50.0, 50.0), (25.0, 5.0), 0, 1)
    iira(-1, 0, (50.0, 50.0), None, 0, -1)
    iira(-1, 0, (50.0, 50.0), (60.0, 60.0), 0, 1)
    iira(2, 0, (12.0, 12.0), (7.0, 7.0), 0, 1)
    iira(2, 0, (12.0, 12.0), (25.0, 5.0), 0, 1)
    iira(1, 0, (12.0, 12.0), (25.0, 5.0), 0, 1)
    iira(1, 1, (50.0, 50.0), (25.0, 5.0), 0, 1)

    # UpdateReverbAreas: the smoothing, with no players.
    for vol, tgt, pan in ((0.2, 0.85, 0.0), (0.85, 0.0, 0.25),
                          (0.5, 0.5, 0.0), (0.5, 0.52, 0.0),
                          (0.5, 0.46, 0.0), (0.0, 0.0, 0.0)):
        a("rv|%s|%s|%s" % (fx(vol), fx(tgt), fx(pan)))
        for k in range(3):
            a("ura")
        a("gd")
    a("rv|%s|%s|%s" % (fx(0.85), fx(0.0), fx(0.5)))
    for k in range(18):
        a("ura")
    a("gd")

    # The mode and the parameters, never set in retail.
    a("rv|0|%s|0" % fx(0.85))
    a("ron|1")
    a("desired|5|%s|%s|%s|%s" % (fx(0.5), fx(0.9), fx(0.7), fx(0.6)))
    a("ura")
    a("gd")
    a("ura")
    a("npc|2")
    a("desired|9|%s|%s|%s|%s" % (fx(0.5), fx(1.0), fx(0.7), fx(0.75)))
    a("ura")
    a("gd")
    a("npc|1")
    a("desired|12|%s|%s|%s|%s" % (fx(0.65), fx(1.0), fx(0.85), fx(0.75)))
    a("ura")
    a("desired|2|%s|%s|%s|%s" % (fx(0.65), fx(1.0), fx(0.85), fx(0.75)))
    a("ura")
    a("gd")

    # One player under each elevation.
    a("rv|0|0|%s" % fx(0.5))
    a("player|0|1")
    a("cur|-1")
    a("ron|0")
    carpos(0, 5.0, 5.0, 1.5)
    for here, top, under in ((1.0, 5.0, 3.0), (5.0, 5.0, 3.0),
                             (3.0, 5.0, 3.0), (5.0, 5.0, 5.0),
                             (5.0, 5.0, 6.0), (6.0, 5.0, 3.0),
                             (2.0, 2.0, 2.0), (2.0, 2.0, 1.0),
                             (2.0, 2.5, 1.0)):
        elev(here, top, under)
        a("ura")
        a("gd")
    carpos(0, 50.0, 50.0)
    a("ura")
    a("gd")
    a("ron|1")
    a("ura")
    a("gd")

    # Two players: the second's car under the elevation when it is the one
    # outside.
    a("npc|2")
    a("player|1|1")
    a("carsnd|0|1")
    a("carsnd|1|1")
    carpos(0, 5.0, 5.0, 1.0)
    carpos(1, 6.0, 6.0, 2.0)
    elev(1.0, 5.0, 3.0)
    a("ura")
    a("gd")
    carpos(1, 25.0, 5.0, 2.0)
    elev(5.0, 5.0, 3.0)
    a("ura")
    a("gd")
    carpos(0, 50.0, 50.0)
    elev(1.0, 9.0, 3.0)
    a("ura")
    a("gd")
    carpos(1, 70.0, 70.0)
    a("ura")
    a("gd")
    a("ron|1")
    a("ura")
    a("gd")
    a("carsnd|1|0")
    a("ron|1")
    a("ura")
    a("player|0|0")
    a("player|1|0")
    a("npc|1")
    a("carsnd|0|0")
    a("ura")
    a("gd")

    # The tunnel.
    for c in (-1, 0, 3, -2):
        a("cur|%d" % c)
        a("tunnel")

    # The whole update, without and with a race.
    a("cur|-1")
    a("rc|0")
    a("update")
    a("rc|1")
    cam(0, 5.0, 5.0, 0.0, 1.0, 0.0)
    cam(1, 250.0, 250.0, 0.0, 0.0, -1.0)
    cams(0, 1)
    a("player|0|1")
    carpos(0, 5.0, 5.0, 1.0)
    elev(1.0, 5.0, 3.0)
    rf(0.1, 0.2, 0.3, 0.4)
    ri(100, 200)
    a("wte|%s" % fx(1.0 / 30.0))
    a("update")
    dump_all(3, 6, 5)
    a("ssupdate")
    a("ula")
    a("uoa")

    # Mute with the rain playing, then not, then none.
    a("rain|r:Wind")
    a("bplaying|r:Wind|1")
    a("mute|1")
    a("gd")
    a("mute|0")
    a("bplaying|r:Wind|0")
    a("ssmute|1")
    a("rain|0")
    a("ssmute|0")
    a("mute|1")
    a("gd")

    # Unload with samples, then reload and unload with none.
    a("rain|r:Wind")
    a("cur|1")
    a("unload|0")
    dump_all(3, 6, 5)
    a("load|0")
    dump_all(3, 6, 5)
    a("unload|0")
    a("gd")
    a("load|0")
    cams(0, 1)
    a("update")
    a("unload|0")
    a("player|0|0")
    a("rc|0")

    # Every distinct retail track's chunk.
    tracks = track_chunks()
    walked = {"TRACKB12", "TRACKB21", "TRACKB43", "TRACKB63"}
    for n, (tn, data) in enumerate(tracks):
        k = 10 + n
        rev, loop, shot = parse_chunk(data)
        chunk(k, data)
        a("load|%d" % k)
        dump_all(len(rev), len(loop), len(shot))
        if tn not in walked:
            continue
        a("track|%s" % tn)
        a("rc|1")
        a("player|0|1")
        a("wte|%s" % fx(0.5))
        stops = [p for p in rev + loop + shot if p is not None]
        for j, (x, y) in enumerate(stops):
            ang = 0.7 * j
            cam(0, x, y, 1.0, math.cos(ang), math.sin(ang))
            cam(1, x + 40.0, y - 30.0, 1.0, -math.sin(ang), math.cos(ang))
            cams(0, 1 if j % 3 == 0 else -1)
            carpos(0, x, y, 1.0)
            elev(1.0, 1.0 + (j % 4), 1.0 - (j % 3))
            rf(0.05 * (j % 5), 0.3)
            ri(4096 * j)
            a("update")
            if j % 5 == 4:
                a("gd")
        cam(0, -99999.0, -99999.0)
        cams(0, -1)
        carpos(0, -99999.0, -99999.0)
        a("update")
        dump_all(len(rev), len(loop), len(shot))
        a("mute|1")
        a("mute|0")
        a("unload|%d" % k)
        a("gd")
        a("player|0|0")
        a("rc|0")

    # ---- the chopper
    a("heli")
    a("heli")
    a("wte|%s" % fx(0.25))
    a("cur|-1")
    a("hcreate|0")
    a("hd|0")
    a("bplaying|src:ChopperEngine|1")
    a("hctor|1")
    a("hd|1")
    a("se|0")
    a("hctor|0")
    a("hd|2")
    a("se|1")
    a("nosrc|ChopperEngine")
    a("hctor|1")
    a("hd|3")
    a("unsrc")
    a("hvt|1|12345678")
    a("hdtor|1|0")
    a("hd|1")
    a("hdtor|3|1")
    a("hd|3")

    # The tunnel's fade through every branch.
    def htun(k, inside, counter):
        a("htun|%d|%d|%s" % (k, inside, fx(counter)))

    def hadj(k, vol, cur, wte=None):
        if wte is not None:
            a("wte|%s" % fx(wte))
        a("cur|%d" % cur)
        a("hadj|%d|%s" % (k, fx(vol)))
        a("hd|%d" % k)

    htun(0, 0, 0.0)
    hadj(0, 0.8, -1)
    hadj(0, 0.8, 0)
    hadj(0, 0.8, 0, 0.25)
    hadj(0, 0.8, 0, 0.5)
    hadj(0, 0.8, 0, 0.5)
    hadj(0, 0.8, 0)
    hadj(0, 0.8, -1)
    for k in range(6):
        hadj(0, 0.8, -1, 0.25)
    htun(0, 1, 0.4)
    hadj(0, 0.8, -1)
    hadj(0, 0.8, -1, 0.1)
    htun(0, 1, 0.0)
    hadj(0, 0.8, 0)
    htun(0, 1, 0.0)
    hadj(0, -0.5, -1)
    htun(0, 1, 0.75)
    hadj(0, -0.5, 2)
    htun(0, 0, 0.5)
    hadj(0, 0.6, 7, 0.125)
    htun(0, 0, 0.0)
    a("cur|-1")

    # Update: sound off, not active, no sample; then played and set, in and
    # out of the tunnel.
    a("hset|0|1|%s|%s|0" % (fx(1.0), fx(1.0)))
    a("se|0")
    a("hupd|0")
    a("se|1")
    a("hset|0|0|%s|%s|0" % (fx(1.0), fx(1.0)))
    a("hupd|0")
    a("hset|2|1|%s|%s|0" % (fx(1.0), fx(1.0)))
    a("hupd|2")
    a("hset|0|1|%s|%s|0" % (fx(1.0), fx(1.0)))
    a("bplaying|src:ChopperEngine|0")
    for vol, pitch, az in ((0.7, 1.1, 1234), (0.65, 0.9, 65535),
                           (0.5, 1.0, 40000)):
        a("s3d|%s|%s|%d" % (fx(vol), fx(pitch), az))
        a("hupd|0")
        a("hd|0")
    a("cur|0")
    for k in range(6):
        a("s3d|%s|%s|%d" % (fx(0.9), fx(1.05), 100 * k))
        a("hupd|0")
        a("hd|0")
    a("cur|-1")
    a("bplaying|src:ChopperEngine|0")
    for k in range(5):
        a("s3d|%s|%s|%d" % (fx(0.9), fx(1.0), 32768))
        a("hupd|0")
        a("hd|0")

    # Mute, deactivate, activate.
    for k, on in ((0, 1), (0, 0), (0, 5), (2, 1)):
        a("hmute|%d|%d" % (k, on))
    a("hdeact|0")
    a("hact|0")
    a("hdeact|2")
    a("hact|2")
    a("se|0")
    a("hmute|0|1")
    a("hdeact|0")
    a("hact|0")
    a("se|1")
    a("hsamp|0|0")
    a("hmute|0|1")
    a("hdeact|0")
    a("hact|0")
    a("hupd|0")
    a("hd|0")
    return L


# ================================================================= build

def build_harness(tmp, name="soundscape_test"):
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


def _m(name, before, after, rel=SSC):
    return (name, rel, before, after)


def _c(name, before, after):
    return (name, CHS, before, after)


MUTATIONS = [
    # The globals and the helpers.
    _m("g-active", "SoundScapeCurrentlyActiveReverbArea = -1;  // gp-18080",
       "SoundScapeCurrentlyActiveReverbArea = 0;   // gp-18080"),
    _m("g-mode", "int32_t  ReverbMode = 2;", "int32_t  ReverbMode = 3;"),
    _m("g-dmode", "int32_t  DesiredReverbMode = 2;",
       "int32_t  DesiredReverbMode = 3;"),
    _m("g-delay", "float    ReverbDelay = 0.65f;",
       "float    ReverbDelay = 0.66f;"),
    _m("g-ddelay", "float    DesiredReverbDelay = 0.65f;",
       "float    DesiredReverbDelay = 0.66f;"),
    _m("g-feedback", "float    ReverbFeedback = 1.0f;",
       "float    ReverbFeedback = 0.9f;"),
    _m("g-dfeedback", "float    DesiredReverbFeedback = 1.0f;",
       "float    DesiredReverbFeedback = 0.9f;"),
    _m("g-level", "float    ReverbLevel = 0.85f;",
       "float    ReverbLevel = 0.86f;"),
    _m("g-dlevel", "float    DesiredReverbLevel = 0.85f;",
       "float    DesiredReverbLevel = 0.86f;"),
    _m("g-depth", "float    ReverbDepth = 0.75f;",
       "float    ReverbDepth = 0.76f;"),
    _m("g-ddepth", "float    DesiredReverbDepth = 0.75f;",
       "float    DesiredReverbDepth = 0.76f;"),
    _m("modetab-lo", "0, 1, 2, 3, 4, 5, 6, 7, 0x65",
       "0, 1, 2, 3, 3, 5, 6, 7, 0x65"),
    _m("modetab-hi", "0x65, 0x66, 0x67, 0x68, 0x69",
       "0x65, 0x66, 0x66, 0x68, 0x69"),
    _m("ambient-vol", "#define AMBIENT_VOLUME 0.84f",
       "#define AMBIENT_VOLUME 0.85f"),
    _m("max-flip", "return fs < ft ? ft : fs;", "return fs < ft ? fs : ft;"),
    _m("smooth-up", "    if (up < b)\n        return up;",
       "    if (up < b)\n        return b;"),
    _m("smooth-down", "down = a - step;", "down = a - step * 0.5f;"),
    _m("smooth-down-cmp", "    if (b < down)\n        return down;",
       "    if (down < b)\n        return down;"),
    _m("sphere-dx", "float dx = cam->CurrentKey.Position.x - l->SoundSource.x;",
       "float dx = cam->CurrentKey.Position.y - l->SoundSource.x;"),
    _m("sphere-dy", "float dy = cam->CurrentKey.Position.y - l->SoundSource.y;",
       "float dy = cam->CurrentKey.Position.y - l->SoundSource.x;"),
    _m("sphere-sum", "return ee_sqrt(dx * dx + dy * dy);",
       "return ee_sqrt(dx * dx + dx * dy);"),
    _m("region-null", "    if (CurrentTrackInfo == NULL)\n        return NULL;\n", ""),
    _m("effvol-voices", "gSoundScapeEffectVolumeFn(0xffffffffu, 1, volume, pan);",
       "gSoundScapeEffectVolumeFn(0xfffffffeu, 1, volume, pan);"),
    _m("effvol-on", "gSoundScapeEffectVolumeFn(0xffffffffu, 1, volume, pan);",
       "gSoundScapeEffectVolumeFn(0xffffffffu, 0, volume, pan);"),
    _m("effvol-pan", "gSoundScapeEffectVolumeFn(0xffffffffu, 1, volume, pan);",
       "gSoundScapeEffectVolumeFn(0xffffffffu, 1, volume, volume);"),
    _m("effparam-core", "gSoundScapeEffectParameterFn(which, 0, value);",
       "gSoundScapeEffectParameterFn(which, 1, value);"),

    # SoundArea.
    _m("sa-verts-off", "a->AreaVerts = (const bVector2 *)(p + 4);",
       "a->AreaVerts = (const bVector2 *)(p + 8);"),
    _m("sa-verts", "p += 4 + 8 * a->NumAreaVerts;", "p += 8 * a->NumAreaVerts;"),
    _m("sa-faces-off", "a->AreaFaces = (const int32_t *)(p + 4);",
       "a->AreaFaces = (const int32_t *)(p + 8);"),
    _m("sa-ret", "return p + 4 + 12 * a->NumAreaFaces;",
       "return p + 12 * a->NumAreaFaces;"),
    _m("pia-loop", "for (i = 0; i < a->NumAreaFaces; i++) {",
       "for (i = 1; i < a->NumAreaFaces; i++) {"),
    _m("pia-stride", "const int32_t *f = a->AreaFaces + 3 * i;",
       "const int32_t *f = a->AreaFaces + 2 * i;"),
    _m("pia-f2", "poly[2] = a->AreaVerts[f[2]];", "poly[2] = a->AreaVerts[f[1]];"),
    _m("pia-ret0", "            return 1;\n    }\n    return 0;",
       "            return 1;\n    }\n    return 1;"),
    _m("aca-count", "    *count = 0;\n", ""),
    _m("aca-two",
       "    for (i = 0; i < 2; i++) {\n        struct Camera *cam = cams[i];\n"
       "        bVector2 pos;",
       "    for (i = 0; i < 1; i++) {\n        struct Camera *cam = cams[i];\n"
       "        bVector2 pos;"),
    _m("aca-null", "        if (cam == NULL)\n            continue;\n", ""),
    _m("aca-y", "        pos.y = cam->CurrentKey.Position.y;\n"
       "        if (soundarea_is_point_in_area(a, &pos))",
       "        pos.y = cam->CurrentKey.Position.x;\n"
       "        if (soundarea_is_point_in_area(a, &pos))"),
    _m("aca-store", "CameraInsideArea[(*count)++] = cam;",
       "CameraInsideArea[0] = cam, (*count)++;"),

    # ReverbArea.
    _m("ra-name", "r->Name = (const char *)(c + 8);",
       "r->Name = (const char *)(c + 9);"),
    _m("ra-reverb", "r->Reverb = (int32_t)bchunk_u32(c + 40);",
       "r->Reverb = (int32_t)bchunk_u32(c + 44);"),
    _m("ra-area", "p = soundarea_initialize(&r->Area, c + 44);",
       "p = soundarea_initialize(&r->Area, c + 40);"),
    _m("ra-n", "r->NumSounds = (int32_t)bchunk_u32(p);",
       "r->NumSounds = (int32_t)bchunk_u32(p) & 1;"),
    _m("ra-sample", "r->Sounds[i].SampleName = (const char *)p;",
       "r->Sounds[i].SampleName = (const char *)p + 1;"),
    _m("ra-period", "r->Sounds[i].Period = bchunk_f32(p + 32);",
       "r->Sounds[i].Period = bchunk_f32(p + 36);"),
    _m("ra-error", "r->Sounds[i].PeriodError = bchunk_f32(p + 36);",
       "r->Sounds[i].PeriodError = bchunk_f32(p + 32);"),
    _m("ra-stride", "        p += 40;\n", "        p += 36;\n"),

    # LoopingAmbient's initialize.
    _m("la-srcx", "l->SoundSource.x = bchunk_f32(c + 84);",
       "l->SoundSource.x = bchunk_f32(c + 88);"),
    _m("la-srcy", "l->SoundSource.y = bchunk_f32(c + 88);",
       "l->SoundSource.y = bchunk_f32(c + 84);"),
    _m("la-fout", "ee_trunc_w(bchunk_f32(c + 76) * 1000.0f)",
       "ee_trunc_w(bchunk_f32(c + 72) * 1000.0f)"),
    _m("la-fin", "ee_trunc_w(bchunk_f32(c + 72) * 1000.0f)",
       "ee_trunc_w(bchunk_f32(c + 76) * 1000.0f)"),
    _m("la-ms", "ee_trunc_w(bchunk_f32(c + 76) * 1000.0f)",
       "ee_trunc_w(bchunk_f32(c + 76) * 100.0f)"),
    _m("la-has", "l->HasSoundSource = bchunk_u32(c + 80) != 0;",
       "l->HasSoundSource = bchunk_u32(c + 80) == 0;"),
    _m("la-active", "    l->IsActive = 0;\n    l->Sample = NULL;\n",
       "    l->Sample = NULL;\n"),
    _m("la-sample", "    l->Sample = NULL;\n    l->Name =", "    l->Name ="),
    _m("la-name", "l->Name = (const char *)(c + 8);",
       "l->Name = (const char *)(c + 9);"),
    _m("la-sname", "l->SampleName = (const char *)(c + 40);",
       "l->SampleName = (const char *)(c + 41);"),
    _m("la-coeff", "l->SoundSourceDistanceCoeff = bchunk_f32(c + 92);",
       "l->SoundSourceDistanceCoeff = bchunk_f32(c + 88);"),
    _m("la-area", "soundarea_initialize(&l->Area, c + 96);",
       "soundarea_initialize(&l->Area, c + 92);"),
    _m("la-sphere-reset", "    l->UseSoundSphere = 0;\n    l->SoundSphereRadius",
       "    l->SoundSphereRadius"),
    _m("la-radius-reset", "    l->SoundSphereRadius = 0.0f;\n", ""),
    _m("la-has-test", "    if (l->HasSoundSource\n        && soundarea_is_point_in_area",
       "    if (soundarea_is_point_in_area"),
    _m("la-in-test",
       "    if (l->HasSoundSource\n        && soundarea_is_point_in_area("
       "&l->Area, &l->SoundSource)) {",
       "    if (l->HasSoundSource) {"),
    _m("la-verts-loop", "for (i = 0; i < l->Area.NumAreaVerts; i++) {",
       "for (i = 0; i < l->Area.NumAreaVerts - 1; i++) {"),
    _m("la-dy", "float dy = l->SoundSource.y - v->y;",
       "float dy = l->SoundSource.y - v->x;"),
    _m("la-dx", "float dx = l->SoundSource.x - v->x;",
       "float dx = l->SoundSource.x - v->y;"),
    _m("la-max", "l->SoundSphereRadius = max_s(l->SoundSphereRadius, d);",
       "l->SoundSphereRadius = d;"),

    # ComputeAzimuth.
    _m("az-dy", "float dy = l->SoundSource.y - cam->CurrentKey.Position.y;",
       "float dy = l->SoundSource.y - cam->CurrentKey.Position.x;"),
    _m("az-dx", "float dx = l->SoundSource.x - cam->CurrentKey.Position.x;",
       "float dx = l->SoundSource.x - cam->CurrentKey.Position.y;"),
    _m("az-len", "float len = ee_sqrt(dx * dx + dy * dy);",
       "float len = ee_sqrt(dx * dx + dy * dx);"),
    _m("az-hy", "float hy = cam->CurrentKey.Direction.y;",
       "float hy = cam->CurrentKey.Direction.x;"),
    _m("az-ndx", "dx = ee_div(dx, len);", "dx = ee_div(dy, len);"),
    _m("az-ndy", "dy = ee_div(dy, len);", "dy = ee_div(dx, len);"),
    _m("az-16384", "r = (uint32_t)(16384 - bASin(dx * hx + dy * hy));",
       "r = (uint32_t)(16383 - bASin(dx * hx + dy * hy));"),
    _m("az-dot", "r = (uint32_t)(16384 - bASin(dx * hx + dy * hy));",
       "r = (uint32_t)(16384 - bASin(dx * hx - dy * hy));"),
    _m("az-side", "if (-dy * hx + dx * hy < 0.0f)",
       "if (-dy * hx + dx * hy > 0.0f)"),
    _m("az-cross", "if (-dy * hx + dx * hy < 0.0f)",
       "if (dy * hx + dx * hy < 0.0f)"),

    # UpdateUsingArea.
    _m("ua-count", "        if (count > 0) {\n            int32_t sum = 0;",
       "        if (count > 1) {\n            int32_t sum = 0;"),
    _m("ua-has", "            if (!l->HasSoundSource)\n                return;\n", ""),
    _m("ua-avg", "bsample_set_azimuth(l->Sample, (uint16_t)(sum / count));",
       "bsample_set_azimuth(l->Sample, (uint16_t)sum);"),
    _m("ua-fout0", "if (l->FadeOutDuration == 0)", "if (l->FadeOutDuration != 0)"),
    _m("ua-fout-vol", "bsample_fade(l->Sample, 0.0f,", "bsample_fade(l->Sample, 0.5f,"),
    _m("ua-fout-dur", "(uint32_t)l->FadeOutDuration);",
       "(uint32_t)l->FadeInDuration);"),
    _m("ua-deact", "            l->IsActive = 0;\n        }\n    } else if (count > 0) {",
       "        }\n    } else if (count > 0) {"),
    _m("ua-start", "        }\n    } else if (count > 0) {\n        if (l->FadeInDuration",
       "        }\n    } else if (count > 1) {\n        if (l->FadeInDuration"),
    _m("ua-fin0", "if (l->FadeInDuration == 0) {", "if (l->FadeInDuration != 0) {"),
    _m("ua-se1", "            if (SoundEnabled)\n                bsample_play(l->Sample, "
       "AMBIENT_VOLUME", "            if (1)\n                bsample_play(l->Sample, "
       "AMBIENT_VOLUME"),
    _m("ua-play-vol", "                bsample_play(l->Sample, AMBIENT_VOLUME, 0.0f, 0.0f);",
       "                bsample_play(l->Sample, 0.83f, 0.0f, 0.0f);"),
    _m("ua-se2", "        } else if (SoundEnabled) {\n            bsample_play(l->Sample, 0.0f",
       "        } else {\n            bsample_play(l->Sample, 0.0f"),
    _m("ua-fin-start", "bsample_play(l->Sample, 0.0f, 0.0f, 0.0f);",
       "bsample_play(l->Sample, 0.1f, 0.0f, 0.0f);"),
    _m("ua-fin-vol", "            bsample_fade(l->Sample, AMBIENT_VOLUME,",
       "            bsample_fade(l->Sample, 0.5f,"),
    _m("ua-fin-dur", "                         (uint32_t)l->FadeInDuration);",
       "                         (uint32_t)l->FadeOutDuration);"),
    _m("ua-act", "        l->IsActive = 1;\n    } else if (bsample_is_playing",
       "    } else if (bsample_is_playing"),
    _m("ua-idle-vol", "&& bsample_get_volume(l->Sample) == 0.0f) {",
       "&& bsample_get_volume(l->Sample) != 0.0f) {"),
    _m("ua-idle-and", "    } else if (bsample_is_playing(l->Sample)\n"
       "               && bsample_get_volume(l->Sample) == 0.0f) {",
       "    } else if (bsample_get_volume(l->Sample) == 0.0f) {"),

    # UpdateUsingSoundSphere.
    _m("us-two", "    for (i = 0; i < 2; i++) {\n        struct Camera *cam = cams[i];\n\n"
       "        if (cam != NULL",
       "    for (i = 0; i < 1; i++) {\n        struct Camera *cam = cams[i];\n\n"
       "        if (cam != NULL"),
    _m("us-null", "        if (cam != NULL\n            && sphere_distance",
       "        if (sphere_distance"),
    _m("us-in", "sphere_distance(l, cam) < l->SoundSphereRadius)",
       "sphere_distance(l, cam) > l->SoundSphereRadius)"),
    _m("us-n", "    if (n > 0) {", "    if (n > 1) {"),
    _m("us-dist", "dist += sphere_distance(l, CameraInsideSphere[i]);",
       "dist = sphere_distance(l, CameraInsideSphere[i]);"),
    _m("us-az", "az = (uint16_t)(sum / n);", "az = (uint16_t)sum;"),
    _m("us-davg", "dist = ee_div(dist, nf);", "dist = ee_div(dist, 1.0f);"),
    _m("us-coeff", "coeff = ee_div(1.0f, r);", "coeff = ee_div(2.0f, r);"),
    _m("us-out", "        if (r < dist) {", "        if (r < dist + dist) {"),
    _m("us-dc", "float dc = dist * coeff;", "float dc = dist;"),
    _m("us-vol", "volume = 1.0f - ee_sqrt((dist + dist) * coeff - dc * dc);",
       "volume = 1.0f - ee_sqrt((dist + dist) * coeff - dc);"),
    _m("us-dbl", "            volume = volume + volume;\n", ""),
    _m("us-set", "bsample_set_volume(l->Sample, volume);",
       "bsample_set_volume(l->Sample, 1.0f);"),
    _m("us-se", "        else if (SoundEnabled)\n            bsample_play(l->Sample, volume",
       "        else\n            bsample_play(l->Sample, volume"),
    _m("us-play-vol", "bsample_play(l->Sample, volume, 0.0f, 0.0f);",
       "bsample_play(l->Sample, 1.0f, 0.0f, 0.0f);"),
    _m("us-setaz", "        bsample_set_azimuth(l->Sample, az);\n    } else if",
       "        bsample_set_azimuth(l->Sample, 0);\n    } else if"),
    _m("us-stop", "    } else if (bsample_is_playing(l->Sample)) {\n"
       "        bsample_stop(l->Sample);",
       "    } else {\n        bsample_stop(l->Sample);"),

    # LoopingAmbient's Update and Mute.
    _m("lu-region", "        if (r != NULL) {\n            BSample *s",
       "        if (r == NULL) {\n            BSample *s"),
    _m("lu-smp", "            if (s != NULL) {\n                l->Sample = bsample_new(0);",
       "            if (s == NULL) {\n                l->Sample = bsample_new(0);"),
    _m("lu-copy", "                bsample_initialize_copy(l->Sample, s);\n", ""),
    _m("lu-cat", "                    bsample_set_category(l->Sample, 0);",
       "                    bsample_set_category(l->Sample, 1);"),
    _m("lu-ret", "        if (l->Sample == NULL)\n            return;\n    }\n"
       "    if (l->UseSoundSphere)",
       "    }\n    if (l->UseSoundSphere)"),
    _m("lu-sphere", "    if (l->UseSoundSphere)\n", "    if (!l->UseSoundSphere)\n"),
    _m("lmute", "    if (l->Sample != NULL)\n        bsample_pause(l->Sample, on);",
       "    if (l->Sample != NULL)\n        bsample_pause(l->Sample, 1);"),
    _m("lmute-null", "    if (l->Sample != NULL)\n        bsample_pause(l->Sample, on);",
       "    bsample_pause(l->Sample, on);"),

    # OneShotAmbient's initialize.
    _m("os-time", "    o->UpdateOneShotTime = 0.0f;\n    o->Name",
       "    o->UpdateOneShotTime = 1.0f;\n    o->Name"),
    _m("os-name", "o->Name = (const char *)(c + 8);",
       "o->Name = (const char *)(c + 9);"),
    _m("os-sname", "o->SampleName = (const char *)(c + 40);",
       "o->SampleName = (const char *)(c + 41);"),
    _m("os-repeat", "o->Repeat = bchunk_f32(c + 72);", "o->Repeat = bchunk_f32(c + 76);"),
    _m("os-active", "    o->IsActive = 0;\n    o->RepeatDeviation",
       "    o->RepeatDeviation"),
    _m("os-rdev", "o->RepeatDeviation = bchunk_f32(c + 76);",
       "o->RepeatDeviation = bchunk_f32(c + 72);"),
    _m("os-sample", "    o->Sample = NULL;\n    o->Pitch", "    o->Pitch"),
    _m("os-pitch", "o->Pitch = bchunk_f32(c + 80);", "o->Pitch = bchunk_f32(c + 84);"),
    _m("os-pdev", "o->PitchDeviation = bchunk_f32(c + 84);",
       "o->PitchDeviation = bchunk_f32(c + 80);"),
    _m("os-adev", "o->AzimuthDeviation = bchunk_f32(c + 88);",
       "o->AzimuthDeviation = bchunk_f32(c + 84);"),
    _m("os-area", "soundarea_initialize(&o->Area, c + 92);",
       "soundarea_initialize(&o->Area, c + 96);"),

    # OneShotAmbient's Play.
    _m("op-null", "    if (o->Sample == NULL)\n        return;\n    pitch = o->Pitch;",
       "    pitch = o->Pitch;"),
    _m("op-pdev", "    if (o->PitchDeviation != 0.0f) {",
       "    if (o->PitchDeviation == 0.0f) {"),
    _m("op-prand", "sound_random_float(sound_get(), o->PitchDeviation);",
       "sound_random_float(sound_get(), o->Pitch);"),
    _m("op-phalf", "pitch = (pitch - o->PitchDeviation * 0.5f) + r;",
       "pitch = (pitch - o->PitchDeviation * 0.25f) + r;"),
    _m("op-pr", "pitch = (pitch - o->PitchDeviation * 0.5f) + r;",
       "pitch = (pitch - o->PitchDeviation * 0.5f) - r;"),
    _m("op-360", "    if (o->AzimuthDeviation == 360.0f)\n        az = 16384;",
       "    if (o->AzimuthDeviation == 180.0f)\n        az = 16384;"),
    _m("op-16384", "        az = 16384;", "        az = 16383;"),
    _m("op-adev", "    else if (o->AzimuthDeviation != 0.0f)",
       "    else if (o->AzimuthDeviation == 0.0f)"),
    _m("op-arand", "sound_random_int(sound_get(), 0x10000);",
       "sound_random_int(sound_get(), 0x8000);"),
    _m("op-se", "    if (SoundEnabled) {\n        bsample_play(o->Sample",
       "    if (1) {\n        bsample_play(o->Sample"),
    _m("op-vol", "        bsample_play(o->Sample, AMBIENT_VOLUME, 0.0f, 0.0f);",
       "        bsample_play(o->Sample, 0.5f, 0.0f, 0.0f);"),
    _m("op-az", "        bsample_set_azimuth(o->Sample, az);",
       "        bsample_set_azimuth(o->Sample, 0);"),
    _m("op-pitch", "        bsample_set_pitch(o->Sample, pitch);",
       "        bsample_set_pitch(o->Sample, o->Pitch);"),
    _m("op-360b", "        if (o->AzimuthDeviation == 360.0f) {\n            bsample_play",
       "        if (o->AzimuthDeviation != 360.0f) {\n            bsample_play"),
    _m("op-360vol", "bsample_play(&o->Sample360Azimuth, AMBIENT_VOLUME, 0.0f, 0.0f);",
       "bsample_play(&o->Sample360Azimuth, 0.5f, 0.0f, 0.0f);"),
    _m("op-c000", "bsample_set_azimuth(&o->Sample360Azimuth, 0xc000);",
       "bsample_set_azimuth(&o->Sample360Azimuth, 0x4000);"),
    _m("op-360pitch", "bsample_set_pitch(&o->Sample360Azimuth, pitch);",
       "bsample_set_pitch(&o->Sample360Azimuth, o->Pitch);"),
    _m("op-rep", "    if (0.0f < o->Repeat) {\n        float t",
       "    if (0.0f > o->Repeat) {\n        float t"),
    _m("op-rdev", "        if (o->RepeatDeviation != 0.0f) {",
       "        if (o->RepeatDeviation == 0.0f) {"),
    _m("op-rrand", "sound_random_float(sound_get(), o->RepeatDeviation);",
       "sound_random_float(sound_get(), o->Repeat);"),
    _m("op-rhalf", "t = (t - o->RepeatDeviation * 0.5f) + r;",
       "t = (t - o->RepeatDeviation * 0.25f) + r;"),
    _m("op-store", "        o->UpdateOneShotTime = t;",
       "        o->UpdateOneShotTime = o->Repeat;"),

    # OneShotAmbient's Update and Mute.
    _m("ou-region", "        if (r == NULL)\n            return;\n        o->Sample",
       "        o->Sample"),
    _m("ou-name", "o->Sample = bregion_sample(r, o->SampleName);",
       "o->Sample = bregion_sample(r, o->Name);"),
    _m("ou-null", "        if (o->Sample == NULL)\n            return;\n"
       "        bsample_set_category(o->Sample, 0);",
       "        bsample_set_category(o->Sample, 0);"),
    _m("ou-cat", "        bsample_set_category(o->Sample, 0);",
       "        bsample_set_category(o->Sample, 1);"),
    _m("ou-360", "        if (o->AzimuthDeviation == 360.0f) {\n"
       "            bsample_initialize_copy",
       "        if (o->AzimuthDeviation != 360.0f) {\n"
       "            bsample_initialize_copy"),
    _m("ou-copy", "            bsample_initialize_copy(&o->Sample360Azimuth, o->Sample);\n",
       ""),
    _m("ou-cat360", "bsample_set_category(&o->Sample360Azimuth, 0);",
       "bsample_set_category(&o->Sample360Azimuth, 1);"),
    _m("ou-count", "        if (count <= 0) {", "        if (count < 0) {"),
    _m("ou-deact", "            o->IsActive = 0;\n        } else if (0.0f < o->Repeat) {",
       "        } else if (0.0f < o->Repeat) {"),
    _m("ou-rep", "        } else if (0.0f < o->Repeat) {",
       "        } else if (0.0f <= o->Repeat) {"),
    _m("ou-dec", "o->UpdateOneShotTime -= WorldTimeElapsed;",
       "o->UpdateOneShotTime += WorldTimeElapsed;"),
    _m("ou-lt", "if (o->UpdateOneShotTime < 0.0f)",
       "if (o->UpdateOneShotTime <= 0.0f)"),
    _m("ou-start", "    } else if (count > 0) {\n        oneshotambient_play(o);",
       "    } else if (count > 1) {\n        oneshotambient_play(o);"),
    _m("ou-act", "        oneshotambient_play(o);\n        o->IsActive = 1;",
       "        oneshotambient_play(o);"),
    _m("omute", "    if (o->Sample != NULL)\n        bsample_pause(o->Sample, on);",
       "    if (o->Sample != NULL)\n        bsample_pause(o->Sample, 1);"),
    _m("omute-null", "    if (o->Sample != NULL)\n        bsample_pause(o->Sample, on);",
       "    bsample_pause(o->Sample, on);"),
    _m("sinit-loop", "for (i = 0; i < SOUNDSCAPE_ONESHOT_AMBIENT; i++)",
       "for (i = 1; i < SOUNDSCAPE_ONESHOT_AMBIENT; i++)"),

    # WillSoundRight, FindGoodReverbArea, SetReverbVolume.
    _m("wsr-ge", "    if (i >= SoundScapeNumReverbAreas)",
       "    if (i > SoundScapeNumReverbAreas)"),
    _m("wsr-y", "    pos.y = car->State.Position.y;\n    return",
       "    pos.y = car->State.Position.x;\n    return"),
    _m("fgra-ret", "            return i;\n    return -1;",
       "            return i;\n    return 0;"),
    _m("fgra-loop", "    for (i = 0; i < SoundScapeNumReverbAreas; i++)",
       "    for (i = 1; i < SoundScapeNumReverbAreas; i++)"),
    _m("srv-two", "if (TheRaceParameters.NumPlayerCars < 2) {",
       "if (TheRaceParameters.NumPlayerCars < 1) {"),
    _m("srv-ret", "        SoundScapeTargetReverbVolume = v;\n        return;",
       "        SoundScapeTargetReverbVolume = v;"),
    _m("srv-car", "    if (car != NULL && car->pBaseCarSound != NULL)",
       "    if (car->pBaseCarSound != NULL)"),
    _m("srv-bcs", "    if (car != NULL && car->pBaseCarSound != NULL)",
       "    if (car != NULL)"),
    _m("srv-plus", "basecarsound_scale_road_noise(car->pBaseCarSound, v + 1.0f);",
       "basecarsound_scale_road_noise(car->pBaseCarSound, v);"),

    # IsInsideReverbArea.
    _m("iira-m1", "    if (SoundScapeCurrentlyActiveReverbArea == -1\n"
       "        || SoundScapeDataJustLoaded) {",
       "    if (SoundScapeDataJustLoaded) {"),
    _m("iira-djl", "    if (SoundScapeCurrentlyActiveReverbArea == -1\n"
       "        || SoundScapeDataJustLoaded) {",
       "    if (SoundScapeCurrentlyActiveReverbArea == -1) {"),
    _m("iira-clear", "        SoundScapeDataJustLoaded = 0;\n", ""),
    _m("iira-first", "    } else if (!soundscape_will_sound_right(\n"
       "                   SoundScapeCurrentlyActiveReverbArea, cars[0])) {\n"
       "        search = 1;\n", ""),
    _m("iira-c1null", "cars[1] != NULL\n               && !soundscape", "!soundscape"),
    _m("iira-second", "        search = 1;\n        second = 1;\n    }",
       "        search = 1;\n    }"),
    _m("iira-search2", "        search = 1;\n        second = 1;\n    }",
       "        second = 1;\n    }"),
    _m("iira-fallback", "        if (i == -1 && cars[1] != NULL) {",
       "        if (cars[1] != NULL) {"),
    _m("iira-fb-null", "        if (i == -1 && cars[1] != NULL) {",
       "        if (i == -1) {"),
    _m("iira-fb-second", "            second = 1;\n            i = soundscape",
       "            i = soundscape"),
    _m("iira-store", "        SoundScapeCurrentlyActiveReverbArea = i;\n", ""),
    _m("iira-ret", "    return second;", "    return 0;"),

    # UpdateReverbAreas.
    _m("ura-rate-lo", "float rate = 0.05f;", "float rate = 0.06f;"),
    _m("ura-rate-hi", "rate = 0.333f;", "rate = 0.334f;"),
    _m("ura-rate-cmp", "if (SoundScapeReverbVolume < SoundScapeTargetReverbVolume)",
       "if (SoundScapeReverbVolume > SoundScapeTargetReverbVolume)"),
    _m("ura-changed", "    if (v != SoundScapeReverbVolume) {", "    if (1) {"),
    _m("ura-store", "        SoundScapeReverbVolume = v;\n", ""),
    _m("ura-pan", "set_effect_volume(SoundScapeReverbVolume, SoundScapeReverbPan);",
       "set_effect_volume(SoundScapeReverbVolume, 0.0f);"),
    _m("ura-mode", "    if (DesiredReverbMode != ReverbMode) {", "    if (0) {"),
    _m("ura-mode-srv", "        soundscape_set_reverb_volume(0.0f, NULL);\n", ""),
    _m("ura-mode-srv-v", "soundscape_set_reverb_volume(0.0f, NULL);",
       "soundscape_set_reverb_volume(0.5f, NULL);"),
    _m("ura-mode-store", "        ReverbMode = DesiredReverbMode;\n", ""),
    _m("ura-modetab", "gSoundScapeEffectModeFn(ReverbModeTable[ReverbMode]);",
       "gSoundScapeEffectModeFn(ReverbMode);"),
    _m("ura-mode-off", "        SoundScapeReverbOn = 0;\n    }\n    if (DesiredReverbDelay",
       "    }\n    if (DesiredReverbDelay"),
    _m("ura-delay", "set_effect_parameter(1, DesiredReverbDelay);",
       "set_effect_parameter(5, DesiredReverbDelay);"),
    _m("ura-delay-store", "        ReverbDelay = DesiredReverbDelay;\n", ""),
    _m("ura-fb", "set_effect_parameter(2, DesiredReverbFeedback);",
       "set_effect_parameter(1, DesiredReverbFeedback);"),
    _m("ura-fb-store", "        ReverbFeedback = DesiredReverbFeedback;\n", ""),
    _m("ura-level", "set_effect_parameter(3, DesiredReverbLevel);",
       "set_effect_parameter(2, DesiredReverbLevel);"),
    _m("ura-level-store", "        ReverbLevel = DesiredReverbLevel;\n", ""),
    _m("ura-depth", "set_effect_parameter(4, DesiredReverbDepth);",
       "set_effect_parameter(3, DesiredReverbDepth);"),
    _m("ura-depth-store", "        ReverbDepth = DesiredReverbDepth;\n", ""),
    _m("ura-depth-cmp", "    if (DesiredReverbDepth != ReverbDepth) {", "    if (0) {"),
    _m("ura-any", "        if (p != NULL)\n            any = 1;", "        any = 1;"),
    _m("ura-noany", "    if (!any)\n        return;\n", ""),
    _m("ura-off-all", "            for (k = 0; k < 2; k++)", "            for (k = 0; k < 1; k++)"),
    _m("ura-off-v", "                    soundscape_set_reverb_volume(0.0f, cars[k]);",
       "                    soundscape_set_reverb_volume(0.5f, cars[k]);"),
    _m("ura-off-flag", "            SoundScapeReverbOn = 0;\n        }\n    } else {",
       "        }\n    } else {"),
    _m("ura-car", "        struct Car *car = cars[i];", "        struct Car *car = cars[0];"),
    _m("ura-99999", "pos.z = 99999.0f;", "pos.z = 9999.0f;"),
    _m("ura-2", "pos.z = top - 2.0f;", "pos.z = top - 1.0f;"),
    _m("ura-below", "below = here < top;", "below = here <= top;"),
    _m("ura-onunder", "onUnder = here <= under;", "onUnder = here < under;"),
    _m("ura-on-or", "            if (below || onUnder) {", "            if (below) {"),
    _m("ura-on-or2", "            if (below || onUnder) {", "            if (onUnder) {"),
    _m("ura-pan0", "                SoundScapeReverbPan = 0.0f;\n", ""),
    _m("ura-085", "soundscape_set_reverb_volume(0.85f, car);",
       "soundscape_set_reverb_volume(0.84f, car);"),
    _m("ura-on", "                SoundScapeReverbOn = 1;\n", ""),
    _m("ura-off-cond", "        } else if (!below && !onUnder) {",
       "        } else if (!below) {"),
    _m("ura-off-cond2", "        } else if (!below && !onUnder) {",
       "        } else if (!onUnder) {"),
    _m("ura-off-v2", "            soundscape_set_reverb_volume(0.0f, car);",
       "            soundscape_set_reverb_volume(0.5f, car);"),
    _m("ura-off-flag2", "            soundscape_set_reverb_volume(0.0f, car);\n"
       "            SoundScapeReverbOn = 0;",
       "            soundscape_set_reverb_volume(0.0f, car);"),

    # Update, Mute, the tunnel.
    _m("ula-loop", "    for (i = 0; i < SoundScapeNumLoopingAmbient; i++)\n"
       "        loopingambient_update(",
       "    for (i = 1; i < SoundScapeNumLoopingAmbient; i++)\n"
       "        loopingambient_update("),
    _m("uoa-loop", "    for (i = 0; i < SoundScapeNumOneShotAmbient; i++)\n"
       "        oneshotambient_update(",
       "    for (i = 1; i < SoundScapeNumOneShotAmbient; i++)\n"
       "        oneshotambient_update("),
    _m("update-rc", "    if (pRaceCoordinator == NULL)\n        return;\n", ""),
    _m("update-ura", "    soundscape_update_reverb_areas();\n", ""),
    _m("update-ula", "    soundscape_update_looping_ambient();\n", ""),
    _m("update-uoa", "    soundscape_update_one_shot_ambient();\n", ""),
    _m("mute-loop", "        loopingambient_mute(&SoundScapeLoopingAmbientArray[i], on);",
       "        loopingambient_mute(&SoundScapeLoopingAmbientArray[i], 0);"),
    _m("mute-os", "        oneshotambient_mute(&SoundScapeOneShotAmbientArray[i], on);",
       "        oneshotambient_mute(&SoundScapeOneShotAmbientArray[i], 0);"),
    _m("mute-rain-play",
       "    if (SoundScapeRain != NULL && bsample_is_playing(SoundScapeRain))",
       "    if (SoundScapeRain != NULL)"),
    _m("mute-rain-on", "bsample_mute(SoundScapeRain, on);",
       "bsample_mute(SoundScapeRain, 1);"),
    _m("mute-on", "    if (on) {\n        set_effect_volume(0.0f, 0.0f);",
       "    if (1) {\n        set_effect_volume(0.0f, 0.0f);"),
    _m("mute-effvol", "        set_effect_volume(0.0f, 0.0f);",
       "        set_effect_volume(0.5f, 0.0f);"),
    _m("mute-off", "        set_effect_volume(0.0f, 0.0f);\n        SoundScapeReverbOn = 0;\n",
       "        set_effect_volume(0.0f, 0.0f);\n"),
    _m("mute-area", "        SoundScapeReverbOn = 0;\n"
       "        SoundScapeCurrentlyActiveReverbArea = -1;\n    }",
       "        SoundScapeReverbOn = 0;\n    }"),
    _m("tunnel", "    return SoundScapeCurrentlyActiveReverbArea != -1;",
       "    return SoundScapeCurrentlyActiveReverbArea > 0;"),
    _m("ssupdate", "{\n    soundscape_update();\n}", "{\n}"),
    _m("ssmute", "    soundscape_mute(on);", "    soundscape_mute(!on);"),

    # The loader and the unloader.
    _m("load-type", "        return 0;\n    SoundScapeDataJustLoaded = 1;",
       "    SoundScapeDataJustLoaded = 1;"),
    _m("load-djl", "    SoundScapeDataJustLoaded = 1;\n", ""),
    _m("load-area", "    SoundScapeCurrentlyActiveReverbArea = -1;\n"
       "    SoundScapeNumReverbAreas = 0;\n    SoundScapeNumLoopingAmbient",
       "    SoundScapeNumReverbAreas = 0;\n    SoundScapeNumLoopingAmbient"),
    _m("load-nr", "    SoundScapeNumReverbAreas = 0;\n    SoundScapeNumLoopingAmbient = 0;\n",
       "    SoundScapeNumLoopingAmbient = 0;\n"),
    _m("load-nl", "    SoundScapeNumLoopingAmbient = 0;\n"
       "    SoundScapeNumOneShotAmbient = 0;\n    end",
       "    SoundScapeNumOneShotAmbient = 0;\n    end"),
    _m("load-no", "    SoundScapeNumOneShotAmbient = 0;\n    end", "    end"),
    _m("load-end", "end = chunk + 8 + bchunk_u32(chunk + 4);",
       "end = chunk + bchunk_u32(chunk + 4);"),
    _m("load-start", "for (c = chunk + 8; c < end;", "for (c = chunk + 16; c < end;"),
    _m("load-cap-r", "if (SoundScapeNumReverbAreas < SOUNDSCAPE_REVERB_AREAS)",
       "if (SoundScapeNumReverbAreas < 2)"),
    _m("load-cap-l", "if (SoundScapeNumLoopingAmbient < SOUNDSCAPE_LOOPING_AMBIENT)",
       "if (SoundScapeNumLoopingAmbient < 2)"),
    _m("load-cap-o", "if (SoundScapeNumOneShotAmbient < SOUNDSCAPE_ONESHOT_AMBIENT)",
       "if (SoundScapeNumOneShotAmbient < 2)"),
    _m("load-ret", "    return 1;\n}\n\nint unloader_sound_scape",
       "    return 0;\n}\n\nint unloader_sound_scape"),
    _m("unl-type", "        return 0;\n    SoundScapeCurrentlyActiveReverbArea = -1;\n"
       "    SoundScapeNumReverbAreas = 0;\n    SoundScapeNumOneShotAmbient",
       "    SoundScapeCurrentlyActiveReverbArea = -1;\n"
       "    SoundScapeNumReverbAreas = 0;\n    SoundScapeNumOneShotAmbient"),
    _m("unl-area", "    SoundScapeCurrentlyActiveReverbArea = -1;\n"
       "    SoundScapeNumReverbAreas = 0;\n    SoundScapeNumOneShotAmbient",
       "    SoundScapeNumReverbAreas = 0;\n    SoundScapeNumOneShotAmbient"),
    _m("unl-nr", "    SoundScapeNumReverbAreas = 0;\n    SoundScapeNumOneShotAmbient = 0;\n",
       "    SoundScapeNumOneShotAmbient = 0;\n"),
    _m("unl-no", "    SoundScapeNumOneShotAmbient = 0;\n    SoundScapeRain = NULL;",
       "    SoundScapeRain = NULL;"),
    _m("unl-rain", "    SoundScapeRain = NULL;\n", ""),
    _m("unl-null", "        if (l->Sample == NULL)\n            continue;\n"
       "        bsample_stop", "        bsample_stop"),
    _m("unl-stop", "        bsample_stop(l->Sample);\n        bsample_delete(l->Sample);",
       "        bsample_delete(l->Sample);"),
    _m("unl-delete", "        bsample_stop(l->Sample);\n        bsample_delete(l->Sample);",
       "        bsample_stop(l->Sample);"),
    _m("unl-nl", "    SoundScapeNumLoopingAmbient = 0;\n    return 1;", "    return 1;"),
    _m("unl-ret", "    SoundScapeNumLoopingAmbient = 0;\n    return 1;",
       "    SoundScapeNumLoopingAmbient = 0;\n    return 0;"),

    # ChopperSound.
    _c("c-env-near", "{ 5.0f, 200.0f, 0.005f }", "{ 6.0f, 200.0f, 0.005f }"),
    _c("c-env-far", "{ 5.0f, 200.0f, 0.005f }", "{ 5.0f, 201.0f, 0.005f }"),
    _c("c-env-coeff", "{ 5.0f, 200.0f, 0.005f }", "{ 5.0f, 200.0f, 0.006f }"),
    _c("c-max", "return fs < ft ? ft : fs;", "return fs < ft ? fs : ft;"),
    _c("c-ctor-s3d", "    sound3d_construct(&s->Sound);\n", ""),
    _c("c-ctor-chopper", "    s->pChopper = h;\n", ""),
    _c("c-ctor-vt", "    s->Sound._vtable = CHOPPERSOUND_VTABLE;\n    s->pChopperSample",
       "    s->pChopperSample"),
    _c("c-ctor-null", "    s->pChopperSample = NULL;\n", ""),
    _c("c-ctor-se", "    if (SoundEnabled) {\n        s->pChopperSample",
       "    if (1) {\n        s->pChopperSample"),
    _c("c-ctor-name", '"ChopperEngine"', '"ChopperEngin"'),
    _c("c-ctor-cat", "        bsample_set_category(s->pChopperSample, 0);",
       "        bsample_set_category(s->pChopperSample, 1);"),
    _c("c-ctor-playing", "        if (s->pChopperSample != NULL\n"
       "            && bsample_is_playing(s->pChopperSample))",
       "        if (s->pChopperSample != NULL)"),
    _c("c-ctor-stop", "            bsample_stop(s->pChopperSample);\n    }",
       "    }"),
    _c("c-ctor-tun", "    s->InSideTunnel = 0;\n", ""),
    _c("c-ctor-fade", "    s->TunnelFadeCounter = 0.0f;\n}",
       "    s->TunnelFadeCounter = 1.0f;\n}"),
    _c("c-dtor-vt", "    s->Sound._vtable = CHOPPERSOUND_VTABLE;\n    sound3d_destroy",
       "    sound3d_destroy"),
    _c("c-dtor-flags", "sound3d_destroy(&s->Sound, flags);",
       "sound3d_destroy(&s->Sound, 0);"),
    _c("c-adj-t", "    if (t) {", "    if (!t) {"),
    _c("c-adj-enter", "        if (!s->InSideTunnel) {", "        if (s->InSideTunnel) {"),
    _c("c-adj-enter-set", "            s->InSideTunnel = t;\n            s->TunnelFadeCounter",
       "            s->TunnelFadeCounter"),
    _c("c-adj-enter-1", "            s->InSideTunnel = t;\n"
       "            s->TunnelFadeCounter = 1.0f;",
       "            s->InSideTunnel = t;\n"
       "            s->TunnelFadeCounter = 0.5f;"),
    _c("c-adj-in-gt", "        } else if (0.0f < s->TunnelFadeCounter) {",
       "        } else if (0.0f <= s->TunnelFadeCounter) {"),
    _c("c-adj-in-dec", "            s->TunnelFadeCounter -= WorldTimeElapsed;",
       "            s->TunnelFadeCounter += WorldTimeElapsed;"),
    _c("c-adj-in-max", "*volume = max_s(*volume * s->TunnelFadeCounter, 0.0f);",
       "*volume = *volume * s->TunnelFadeCounter;"),
    _c("c-adj-in-mul", "*volume = max_s(*volume * s->TunnelFadeCounter, 0.0f);",
       "*volume = max_s(*volume, 0.0f);"),
    _c("c-adj-in-zero", "        } else {\n            *volume = 0.0f;\n        }",
       "        } else {\n        }"),
    _c("c-adj-leave", "    } else if (s->InSideTunnel) {",
       "    } else if (!s->InSideTunnel) {"),
    _c("c-adj-leave-le", "        if (s->TunnelFadeCounter <= 0.0f) {",
       "        if (s->TunnelFadeCounter < 0.0f) {"),
    _c("c-adj-leave-1", "            s->TunnelFadeCounter = 1.0f;\n            *volume = 0.0f;",
       "            s->TunnelFadeCounter = 0.5f;\n            *volume = 0.0f;"),
    _c("c-adj-leave-vol", "            s->TunnelFadeCounter = 1.0f;\n            *volume = 0.0f;",
       "            s->TunnelFadeCounter = 1.0f;"),
    _c("c-adj-leave-mul", "            *volume *= s->TunnelFadeCounter;\n", ""),
    _c("c-adj-leave-flip", "s->TunnelFadeCounter = 1.0f - s->TunnelFadeCounter;",
       "s->TunnelFadeCounter = 1.0f;"),
    _c("c-adj-leave-set", "        s->InSideTunnel = t;\n    } else if",
       "    } else if"),
    _c("c-adj-out-gt", "    } else if (0.0f < s->TunnelFadeCounter) {\n"
       "        s->TunnelFadeCounter -= WorldTimeElapsed;",
       "    } else if (0.0f <= s->TunnelFadeCounter) {\n"
       "        s->TunnelFadeCounter -= WorldTimeElapsed;"),
    _c("c-adj-out-dec", "        s->TunnelFadeCounter -= WorldTimeElapsed;\n"
       "        *volume *= 1.0f",
       "        s->TunnelFadeCounter += WorldTimeElapsed;\n"
       "        *volume *= 1.0f"),
    _c("c-adj-out-mul", "        *volume *= 1.0f - s->TunnelFadeCounter;",
       "        *volume *= s->TunnelFadeCounter;"),
    _c("c-upd-se", "if (!SoundEnabled || !s->Sound.Activated",
       "if (!s->Sound.Activated"),
    _c("c-upd-act", "|| !s->Sound.Activated || s->pChopperSample == NULL)",
       "|| s->pChopperSample == NULL)"),
    _c("c-upd-null", "|| !s->Sound.Activated || s->pChopperSample == NULL)",
       "|| !s->Sound.Activated)"),
    _c("c-upd-pos", "sound3d_update(&s->Sound, &s->pChopper->CurrentPos,",
       "sound3d_update(&s->Sound, (void *)&s->pChopper->CurrentPos.y,"),
    _c("c-upd-adj", "    choppersound_adjust_for_tunnel_volume(s, &s->Sound.Volume);\n",
       ""),
    _c("c-upd-playing", "    if (bsample_is_playing(s->pChopperSample)) {",
       "    if (!bsample_is_playing(s->pChopperSample)) {"),
    _c("c-upd-vol", "bsample_set_volume(s->pChopperSample, s->Sound.Volume);",
       "bsample_set_volume(s->pChopperSample, 1.0f);"),
    _c("c-upd-az", "bsample_set_azimuth(s->pChopperSample, s->Sound.Azimuth);",
       "bsample_set_azimuth(s->pChopperSample, 0);"),
    _c("c-upd-pitch", "bsample_set_pitch(s->pChopperSample, s->Sound.Pitch - 1.0f);",
       "bsample_set_pitch(s->pChopperSample, s->Sound.Pitch);"),
    _c("c-upd-play-vol", "    } else {\n        bsample_play(s->pChopperSample, s->Sound.Volume,",
       "    } else {\n        bsample_play(s->pChopperSample, 1.0f,"),
    _c("c-upd-play-az0", "    } else {\n        bsample_play(s->pChopperSample, s->Sound.Volume,\n"
       "                     (float)(int32_t)s->Sound.Azimuth,",
       "    } else {\n        bsample_play(s->pChopperSample, s->Sound.Volume,\n"
       "                     0.0f,"),
    _c("c-upd-play-az16", "    } else {\n        bsample_play(s->pChopperSample, s->Sound.Volume,\n"
       "                     (float)(int32_t)s->Sound.Azimuth,",
       "    } else {\n        bsample_play(s->pChopperSample, s->Sound.Volume,\n"
       "                     (float)(int16_t)s->Sound.Azimuth,"),
    _c("c-upd-play-pitch", "                     s->Sound.Pitch - 1.0f);\n    }\n}",
       "                     s->Sound.Pitch);\n    }\n}"),
    _c("c-mute-se", "{\n    if (SoundEnabled && s->pChopperSample != NULL)\n"
       "        bsample_pause", "{\n    if (s->pChopperSample != NULL)\n"
       "        bsample_pause"),
    _c("c-mute-null", "{\n    if (SoundEnabled && s->pChopperSample != NULL)\n"
       "        bsample_pause", "{\n    if (SoundEnabled)\n        bsample_pause"),
    _c("c-mute-on", "bsample_pause(s->pChopperSample, on != 0);",
       "bsample_pause(s->pChopperSample, on);"),
    _c("c-mute-on1", "bsample_pause(s->pChopperSample, on != 0);",
       "bsample_pause(s->pChopperSample, 1);"),
    _c("c-deact-se", "{\n    if (SoundEnabled && s->pChopperSample != NULL)\n"
       "        bsample_stop", "{\n    if (s->pChopperSample != NULL)\n"
       "        bsample_stop"),
    _c("c-deact-null", "{\n    if (SoundEnabled && s->pChopperSample != NULL)\n"
       "        bsample_stop", "{\n    if (SoundEnabled)\n        bsample_stop"),
    _c("c-act-se", "{\n    if (SoundEnabled && s->pChopperSample != NULL)\n"
       "        bsample_play", "{\n    if (s->pChopperSample != NULL)\n"
       "        bsample_play"),
    _c("c-act-null", "{\n    if (SoundEnabled && s->pChopperSample != NULL)\n"
       "        bsample_play", "{\n    if (SoundEnabled)\n        bsample_play"),
    _c("c-act-vol", "!= NULL)\n        bsample_play(s->pChopperSample, s->Sound.Volume,",
       "!= NULL)\n        bsample_play(s->pChopperSample, 1.0f,"),
    _c("c-act-az", "                     (float)(int32_t)s->Sound.Azimuth,\n"
       "                     s->Sound.Pitch - 1.0f);\n}\n\nSound3d",
       "                     (float)(int16_t)s->Sound.Azimuth,\n"
       "                     s->Sound.Pitch - 1.0f);\n}\n\nSound3d"),
    _c("c-act-pitch", "                     s->Sound.Pitch - 1.0f);\n}\n\nSound3d",
       "                     s->Sound.Pitch);\n}\n\nSound3d"),
    _c("c-create-size", "bMalloc((int)sizeof(ChopperSound),", "bMalloc(44,"),
    _c("c-create-align", '"ChopperSound", 0, 16);', '"ChopperSound", 0, 8);'),
    _c("c-create-flags", '"ChopperSound", 0, 16);', '"ChopperSound", 1, 16);'),
    _c("c-create-ctor", "    choppersound_construct(s, h);\n    return", "    return"),
    _c("c-vt-dtor", "    E(choppersound_destroy),", "    E(choppersound_mute),"),
    _c("c-vt-act", "    E(sound3d_activate),", "    E(choppersound_activate_sound),"),
    _c("c-vt-upd", "    E(choppersound_update),", "    E(sound3d_activate),"),
    _c("c-vt-mute", "    E(choppersound_mute),", "    E(choppersound_destroy),"),
    _c("c-vt-deact", "    E(choppersound_deactivate_sound),",
       "    E(choppersound_activate_sound),"),
    _c("c-vt-actsnd", "    E(choppersound_activate_sound),",
       "    E(choppersound_deactivate_sound),"),
    _c("c-vt-camrel", "    E(sound3d_update_cam_relative_dist_and_velocity),",
       "    E(sound3d_activate),"),
    _c("c-vt-count", "               CHOPPERSOUND_VT_ENTRIES);",
       "               CHOPPERSOUND_VT_ENTRIES - 1);"),
]

EQUIVALENT = {
    "region-null": "retail reads through CurrentTrackInfo with no test; the"
                   " port's guard is for a track never loaded, which retail"
                   " would fault on, so the check always has one",
    "iira-m1": "with no area active and nothing just loaded the mutant asks"
               " WillSoundRight about area -1, a read before the array that"
               " finds no faces; it says no and the search runs as before",
    "c-mute-on": "bsample_pause takes a bool, so a raw `on` converts to 1"
                 " just as `on != 0` does",
    "c-ctor-null": "both sides' fresh records have the sample 0 before the"
                   " constructor, so its NULL writes nothing new",
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
        todo, SOURCES, "soundscape_test",
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
