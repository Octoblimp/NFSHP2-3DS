#!/usr/bin/env python3
"""Cross-check 3DS Files/source/carsound.c against the retail image,
SLES_507.31.

**The model** is retail's own CarSounds.obj run in retail_model.RetailEmu
with the EE's divide, product and root (eediv, eemul, eesqrt):
GetPOVVolume; BaseCarSound's constructor, destructor, Update,
UpdateSirenSound, GetHornSample, TriggerSplash, UpdateSplash, Mute,
TriggerTireBlowOut, ScaleRoadNoise, InSoundSphere, Start/StopHonkHorn,
IsHonking, Deactivate/ActivateSound and GetSplashSample;
BasePlayerCarSound's constructor, destructor, Update, Mute,
GetHornSample, GetEngineReflectionSample, CalcWindVolume, CalcWindPitch,
UpdateEngineReflection and UpdateDynamicBodyReflections;
BaseAICarSound's constructor, destructor and Update; MaybeInsertCarSound,
MaybeActivateCarSound, UpdateCarSounds, the three sound::Create*
and GetReverbTopologyCoordinate; HornSound3d's and SirenSound3d's
every method -- on retail's own statics, after its static constructor
(0x0018f0f8), and through its five vtables. Sound3d's constructor,
destructor and Activate, Car::UpdateSound, bStrCat, bScaleAdd and
bNormalize run in the image too. The harness (tools/src/carsound_test.c)
runs carsound.c's, through the port's vtables, with copies of sound3d.c's
three and car.c's one.

**The fakes**, the same on both sides, each printing what it is handed:
Sound3d's Update and UpdateCamRelativeDistAndVelocity (which leave the
script's volume, pitch, azimuth and distance, the distance per car sound
when `nd` gave one); bSample's constructor, destructor, Initialize,
SetCategory, Play, Stop, Pause, SetAzimuth, SetVolume, SetPitch and
IsPlaying (playing from Play to Stop); bSound::Region and
bRegion::Sample ("InGame" has the sirens, "Car0" its "P0Horn");
GetInGameSample (the splashes, "TirePop1", "Wind", the reflections and
"Horn01"/"02" but no "03"); sound's two random helpers, from the
script's queues; bMalloc (0xa5-filled, its size checked against retail's
and the port's records) and __builtin_delete; TopologyCoordinate's
constructor and destructor; the engine and tyre factories, whose sounds
carry a probe vtable that prints every slot; tire_sound's TriggerBlowOut
and ScaleRoadNoise; Player::ClearZoneSound; Car::WorldToCar (the world
point less the car's position); GetLocalCollisionBodies (the script's
first and last) and the collision bodies' GetPosition, GetVelocity and
GetTerrainType.

**The script** prints the tables and the statics; reads the POV volumes
for every POV and type; makes a player's sound alone and in split screen
(each driver's azimuth, a region with no horn, no tyres), an AI's, a
cop's and traffic's; updates each, activated and not, with the zone
sound held and left; runs the siren through its modes, a switch, a
silent frame, a switch due at exactly 0 and one onto a siren already
playing, a broken pitch up and down, UpdateMode on a siren already off
and with sound off, and the base sound going quiet; honks, stops and
tests with each switch off on its own; splashes inside and outside the ten-frame gap; mutes
and unmutes each kind; pops a tyre with each switch off; plays the
engine's reflections at and around 50 km/h and walks the collision
bodies past the car (a plant, one too far in z, one at 9, one too slow,
one crossing each way, one not crossing, the car's own, from the list's
head and from inside it; one passing at 50 km/h relative and one at the
float above; one over 9 only in the sums' own order; one slower than the
car in y with the car heading +y); fills and overfills the closest list
(one as far as an entry, which keeps its place), by hand and through
UpdateCarSounds with one and two players and no world; makes a third
cop, on the first siren again; and deletes each kind.

    python tools/carsound_check.py
    python tools/carsound_check.py --mutate [--only a,b]
    python tools/carsound_check.py --dump out/carsound
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

HARNESS = "tools/src/carsound_test.c"
CSC = "3DS Files/source/carsound.c"
SOURCES = [HARNESS, CSC, "3DS Files/source/vtable.c",
           "3DS Files/source/bvector.c", "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c"]
HARNESS_TIMEOUT = 30
LIMIT = 400000

GP = retail_model.RETAIL_GP
F = {
    "pov": 0x0018d0a8, "uss": 0x0018d3f8, "splash": 0x0018d488,
    "usplash": 0x0018d4a0, "blow": 0x0018d650, "road": 0x0018d6e8,
    "sphere": 0x0018d750, "honk": 0x0018d780, "stophonk": 0x0018d7c0,
    "ishonk": 0x0018d800, "splashs": 0x0018d950, "refls": 0x0018de00,
    "windv": 0x0018de68, "windp": 0x0018dea0, "uer": 0x0018deb0,
    "udbr": 0x0018e018, "ins": 0x0018e8b0, "actv": 0x0018e970,
    "ucs": 0x0018ea18, "mkplayer": 0x0018eb28, "mkai": 0x0018eb70,
    "mkcop": 0x0018ebb8, "trt": 0x0018ec00, "choose": 0x0018f190,
    "smode": 0x0018f300, "sbroken": 0x0018f520, "sbp": 0x0018f7a0,
    "sinit": 0x0018f0f8,
}

# What the vtables point at, by name.
FNAME = {
    0x0018d258: "base-dtor", 0x00208b28: "activate",
    0x0018d340: "base-update", 0x0018d550: "base-mute",
    0x0018d830: "base-deact", 0x0018d8d8: "base-act",
    0x00208c78: "camrel", 0x0018d480: "base-horn",
    0x0018db78: "player-dtor", 0x0018dbf0: "player-update",
    0x0018dd10: "player-mute", 0x0018dda0: "player-horn",
    0x0018e7e8: "ai-dtor", 0x0018e800: "ai-update",
    0x0018f2b0: "horn-dtor", 0x0018f218: "horn-update",
    0x0018f208: "horn-mute", 0x0018f188: "horn-deact",
    0x0018f160: "horn-act", 0x0018f710: "siren-dtor",
    0x0018f548: "siren-update", 0x0018f528: "siren-mute",
    0x0018f508: "siren-deact", 0x0018f4d0: "siren-act",
}
VT_BASE, VT_PLAYER, VT_AI = 0x002b4968, 0x002b4920, 0x002b48d8
VT_HORN, VT_SIREN, VT_S3D = 0x002b4898, 0x002b49b0, 0x002bb2b0
TABLES = (("base", VT_BASE, 9), ("player", VT_PLAYER, 9),
          ("ai", VT_AI, 9), ("horn", VT_HORN, 8), ("siren", VT_SIREN, 8))

SE = GP - 23056
CSE, CDSE, RNE = GP - 20456, GP - 20460, GP - 16248
MAX, NUM, CLOSEST = GP - 20400, GP - 20396, 0x003100c0
MPAZ, DT = GP - 20464, GP - 19560
PENV, AIENV = 0x00310070, 0x00310080
BSOUND = GP - 13696
PCW = GP - 22120
NPC = 0x0031a8c8
CBL = GP - 17792

# Retail's records.
SIZES = {"PlayerCarSound": 288, "AICarSound": 80, "HornSound3d": 224,
         "SirenSound": 616, "..\\indep\\src\\carsounds.cpp": 704}
SAMPLE = 188
CAR_SIZE = 2304
C_DRVNUM, C_TYPE, C_DRIVER, C_PLAYER, C_BODY = 10, 12, 20, 24, 52
C_POS, C_VEL, C_SIREN, C_SOUND = 96, 964, 2104, 2132

SRC_NAMES = ("Splash1", "Splash2", "Splash3", "TirePop1", "Wind",
             "Reflection01", "Reflection02", "Horn01", "Horn02",
             "CopSiren01", "CopSiren02", "CopSiren03", "P0Horn", "Zone")
REG_NAMES = ("InGame", "Car0", "Car1", "Car2")


def fbits(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def fx(x):
    return "%08x" % fbits(x)


def bitsf(v):
    return struct.unpack("<f", struct.pack("<I", v & M32))[0]


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def s8(v):
    v &= 0xff
    return v - 0x100 if v & 0x80 else v


class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True,
                                            eemul=True, eesqrt=True)
        e.stub_bware()
        self.allocs = []                # (address, tag)
        self.probes = []                # (address, kind) 0 engine, 1 tyre
        self.srcs = {}
        for nm in SRC_NAMES:
            self.srcs[nm] = e.alloc(SAMPLE, 16)
        self.regs = {}
        for nm in REG_NAMES:
            self.regs[nm] = e.alloc(16)
        self.bsound = e.alloc(16)
        self.cars, self.types, self.drivers, self.players = {}, {}, {}, {}
        self.snds = {}
        self.bodies, self.bodypos, self.bodyvel, self.bodyterrain = \
            {}, {}, {}, {}
        self.playing = set()
        self.ri, self.rf = [], []
        self.nu = (fbits(1.0), fbits(1.0), 0, 0)
        self.nd = {}                    # sound -> distance bits
        self.notires = 0
        self.loc = (0, 0)
        self.world = e.alloc(64)
        e.put32(self.world, self.world)
        e.put32(self.world + 4, self.world)
        e.put32(BSOUND, self.bsound)
        e.put32(SE, 1)
        e.put32(PCW, 0)
        e.put32(NPC, 0)
        e.put32(DT, 0)
        e.put32(CBL, CBL)
        e.put32(CBL + 4, CBL)
        e.call(F["sinit"], limit=LIMIT)

        # The probe: the engine's and the tyres' vtable.
        self.probe = e.alloc(64, 16)
        for slot, fn in ((8, self.p_destroy), (16, self.p_activate),
                         (24, self.p_update), (32, self.p_mute),
                         (40, self.p_deact), (48, self.p_actsound),
                         (56, self.p_camrel)):
            a = e.alloc(16)
            e.stub(a, fn)
            e.put32(self.probe + slot, 0)
            e.put32(self.probe + slot + 4, a)
        # The collision bodies' vtable.
        self.bodyvt = e.alloc(208, 16)
        e.mem[self.bodyvt:self.bodyvt + 208] = b"\0" * 208
        for slot, fn in ((24, self.b_position), (32, self.b_velocity),
                         (144, self.b_terrain)):
            a = e.alloc(16)
            e.stub(a, fn)
            e.put32(self.bodyvt + slot + 4, a)

        # bSample's own table (its vptr at 184): SirenSound3d's destructor
        # deletes its three through slot 8.
        self.bsvt = e.alloc(16, 16)
        e.put32(self.bsvt + 8, 0)
        e.put32(self.bsvt + 12, 0x00273148)

        e.stub(0x00208cf0, self.s3d_update)
        e.stub(0x00208c78, self.s3d_camrel)
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
        e.stub(0x002719b8, self.rsample)
        e.stub(0x001ae280, self.ingame)
        e.stub(0x001af9a0, self.randi)
        e.stub(0x001af9c0, self.randf)
        e.stub(0x002577c0, self.malloc)
        e.stub(0x00114e98, self.delete)
        e.stub(0x00151c28, self.tcctor)
        e.stub(0x00151c70, self.tcdtor)
        e.stub(0x00211d90, self.mk_player_engine)
        e.stub(0x00211de0, self.mk_ai_engine)
        e.stub(0x002141f8, self.mk_player_tire)
        e.stub(0x00214250, self.mk_ai_tire)
        e.stub(0x00214338, self.tire_blow)
        e.stub(0x00214360, self.tire_road)
        e.stub(0x00178470, self.clearzone)
        e.stub(0x001d7778, self.local)
        e.stub(0x0018f4a8, self.w2c)

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
        if a == CBL:
            return "L"
        if a == PENV:
            return "penv"
        if a == AIENV:
            return "aienv"
        for i, (p, tag) in enumerate(self.allocs):
            if a == p:
                return "m%d" % i
            if tag == "PlayerCarSound" and a == p + 96:
                return "m%d.wind" % i
            if tag == "HornSound3d" and a == p + 32:
                return "m%d.b" % i
            if tag == "SirenSound":
                for j in range(3):
                    if a == p + 32 + SAMPLE * j:
                        return "m%d.b%d" % (i, j)
        for i, (p, kind) in enumerate(self.probes):
            if a == p:
                return ("tire%d" if kind else "eng%d") % i
        for nm, p in self.srcs.items():
            if a == p:
                return "src:" + nm
        for nm, p in self.regs.items():
            if a == p:
                return "reg:" + nm
        for k in sorted(self.cars):
            c = self.cars[k]
            if a == c:
                return "car%d" % k
            if a == c + C_POS:
                return "car%d.pos" % k
            if a == self.players.get(k):
                return "p%d" % k
        for j, b in self.bodies.items():
            if a == b:
                return "b%d" % j
        return "?"

    def vtname(self, v):
        return {VT_BASE: "base", VT_PLAYER: "player", VT_AI: "ai",
                VT_HORN: "horn", VT_SIREN: "siren", VT_S3D: "s3d",
                self.probe: "probe"}.get(v, "?")

    # ---- Sound3d

    def dist_for(self, s):
        return self.nd.get(s & M32, self.nu[3])

    def s3d_update(self, em):
        s = em.reg[4] & M32
        self.emit("  s3dupd %s pos=%s env=%s" % (
            self.name(s), self.name(em.reg[5]), self.name(em.reg[6])))
        vol, pitch, az, _d = self.nu
        em.put32(s + 8, vol)
        em.put32(s + 12, pitch)
        em.mem[s + 16:s + 18] = struct.pack("<H", az & 0xffff)
        em.put32(s + 24, self.dist_for(s))
        return 0

    def s3d_camrel(self, em):
        s = em.reg[4] & M32
        self.emit("  camrel %s pos=%s" % (self.name(s),
                                          self.name(em.reg[5])))
        em.put32(s + 24, self.dist_for(s))
        return 0

    # ---- bSample

    def b_ctor(self, em):
        s = em.reg[4] & M32
        self.emit("  bctor %s" % self.name(s))
        em.put32(s + 184, self.bsvt)
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

    def region(self, em):
        nm = self.cstr(em.reg[5] & M32)
        self.emit("  region %s" % nm)
        if em.reg[4] & M32 != self.bsound:
            self.emit("  region: not bSound's")
        return self.regs.get(nm, 0)

    def rsample(self, em):
        r = em.reg[4] & M32
        nm = self.cstr(em.reg[5] & M32)
        self.emit("  rsample %s %s" % (self.name(r), nm))
        if r == self.regs["InGame"] and nm.startswith("CopSiren"):
            return self.srcs.get(nm, 0)
        if r == self.regs["Car0"] and nm == "P0Horn":
            return self.srcs[nm]
        return 0

    def ingame(self, em):
        nm = self.cstr(em.reg[4] & M32)
        self.emit("  ingame %s" % nm)
        if nm in ("P0Horn", "Zone") or nm.startswith("CopSiren"):
            return 0
        return self.srcs.get(nm, 0)

    def randi(self, em):
        v = self.ri.pop(0) if self.ri else 0
        self.emit("  randi %d -> %d" % (s32(em.reg[4]), v))
        return v

    def randf(self, em):
        v = self.rf.pop(0) if self.rf else 0
        self.emit("  randf %08x -> %08x" % (em.fpr[12], v))
        em.fpr[0] = v
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

    def tcctor(self, em):
        self.emit("  tcctor %s" % self.name(em.reg[4]))
        return em.reg[4] & M32

    def tcdtor(self, em):
        a = em.reg[4] & M32
        self.emit("  tcdtor %s" % self.name(a))
        if em.reg[5] & 1:
            self.emit("  delete %s" % self.name(a))
        return 0

    # ---- the car

    def w2c(self, em):
        c, out, pt = (em.reg[r] & M32 for r in (4, 5, 6))
        u = em.u32
        self.emit("  w2c %s %08x %08x" % (self.name(c), u(pt), u(pt + 4)))
        for j in (0, 4):
            em.put32(out + j, fbits(bitsf(u(pt + j)) - bitsf(u(c + C_POS + j))))
        return 0

    def clearzone(self, em):
        self.emit("  clearzone %s" % self.name(em.reg[4]))
        return 0

    # ---- the probes

    def p_destroy(self, em):
        self.emit("  pdestroy %s %d" % (self.name(em.reg[4]), s32(em.reg[5])))
        return 0

    def p_activate(self, em):
        s = em.reg[4] & M32
        on = s32(em.reg[5])
        self.emit("  pact %s %d" % (self.name(s), on))
        em.put32(s, on)
        return 0

    def p_update(self, em):
        self.emit("  pupd %s %08x %d %08x" % (
            self.name(em.reg[4]), em.fpr[12], em.reg[5] & 0xffff,
            em.fpr[13]))
        return 0

    def p_mute(self, em):
        self.emit("  pmute %s %d" % (self.name(em.reg[4]), s32(em.reg[5])))
        return 0

    def p_deact(self, em):
        self.emit("  pdeact %s" % self.name(em.reg[4]))
        return 0

    def p_actsound(self, em):
        self.emit("  pactsound %s" % self.name(em.reg[4]))
        return 0

    def p_camrel(self, em):
        self.emit("  pcamrel %s %s" % (self.name(em.reg[4]),
                                       self.name(em.reg[5])))
        return 0

    def new_probe(self, kind):
        e = self.e
        p = e.alloc(32, 16)
        e.mem[p:p + 32] = b"\xa5" * 32
        e.put32(p, 0)
        e.put32(p + 28, self.probe)
        self.probes.append((p, kind))
        return p

    def mk_player_engine(self, em):
        c = em.reg[4] & M32
        p = self.new_probe(0)
        self.emit("  mkeng player %s -> %s" % (self.name(c), self.name(p)))
        return p

    def mk_ai_engine(self, em):
        c = em.reg[4] & M32
        p = self.new_probe(0)
        self.emit("  mkeng ai %s -> %s" % (self.name(c), self.name(p)))
        return p

    def mk_player_tire(self, em):
        c = em.reg[4] & M32
        p = 0 if self.notires else self.new_probe(1)
        self.emit("  mktire player %s %d -> %s" % (
            self.name(c), s32(em.reg[5]), self.name(p)))
        return p

    def mk_ai_tire(self, em):
        c = em.reg[4] & M32
        p = 0 if self.notires else self.new_probe(1)
        self.emit("  mktire ai %s -> %s" % (self.name(c), self.name(p)))
        return p

    def tire_blow(self, em):
        self.emit("  tblow %s" % self.name(em.reg[4]))
        return 0

    def tire_road(self, em):
        self.emit("  troad %s %08x" % (self.name(em.reg[4]), em.fpr[12]))
        return 0

    # ---- the bodies

    def body_index(self, a):
        a &= M32
        for j, b in self.bodies.items():
            if a == b:
                return j
        raise RuntimeError("not a body: %08x" % a)

    def b_position(self, em):
        j = self.body_index(em.reg[4])
        self.emit("  bpos %s" % self.name(em.reg[4]))
        return self.bodypos[j]

    def b_velocity(self, em):
        j = self.body_index(em.reg[4])
        self.emit("  bvel %s" % self.name(em.reg[4]))
        return self.bodyvel[j]

    def b_terrain(self, em):
        j = self.body_index(em.reg[4])
        self.emit("  bterrain %s" % self.name(em.reg[4]))
        return self.bodyterrain[j]

    def local(self, em):
        self.emit("  local %s %08x" % (self.name(em.reg[4]), em.fpr[12]))
        em.put32(em.reg[5] & M32, self.loc[0])
        em.put32(em.reg[6] & M32, self.loc[1])
        return 0

    # ---- the dumps

    def dump3d(self, label, a):
        e = self.e
        u = e.u32
        self.emit("  %s %s vt=%s act=%d dop=%d vol=%08x pitch=%08x az=%d "
                  "vel=%08x dist=%08x" % (
                      label, self.name(a), self.vtname(u(a + 28)),
                      s32(u(a)), s32(u(a + 4)), u(a + 8), u(a + 12),
                      e.u16(a + 16), u(a + 20), u(a + 24)))

    def dump(self, k):
        e = self.e
        u = e.u32
        s = self.snds[k]
        n = self.name
        self.dump3d("snd", s)
        self.emit("  base car=%s sl=%d sr=%d slt=%d srt=%d horn=%s siren=%s "
                  "eng=%s pop=%s t0=%s t1=%s env=%s" % (
                      n(u(s + 32)), s32(u(s + 36)), s32(u(s + 40)),
                      s32(u(s + 44)), s32(u(s + 48)), n(u(s + 52)),
                      n(u(s + 56)), n(u(s + 60)), n(u(s + 64)),
                      n(u(s + 68)), n(u(s + 72)), n(u(s + 76))))
        if u(s + 28) == VT_PLAYER:
            self.emit("  player rev=%s rl=%d rr=%d chk=%d paz=%d" % (
                n(u(s + 80)), s32(u(s + 84)), s32(u(s + 88)),
                s32(u(s + 92)), e.u16(s + 284)))
        h = u(s + 52)
        if h:
            self.dump3d("horn", h)
            self.emit("  detune=%08x" % u(h + 220))
        r = u(s + 56)
        if r:
            self.dump3d("siren", r)
            self.emit("  cur=%d switch=%08x broken=%d target=%08x "
                      "curr=%08x" % (s32(u(r + 596)), u(r + 600),
                                     s32(u(r + 604)), u(r + 608),
                                     u(r + 612)))

    def dump_tables(self):
        e = self.e
        for label, vt, n in TABLES:
            self.emit("  vt %s %d entries" % (label, n))
            for k in range(1, n):
                d = s16(e.u16(vt + 8 * k))
                fn = e.u32(vt + 8 * k + 4)
                self.emit("  vt %s %d %d %s" % (label, 8 * k, d,
                                                FNAME.get(fn, "?")))

    # ---- the ops

    def call(self, name, *args):
        return self.e.call(F[name], *args, limit=LIMIT)

    def op(self, f):
        e = self.e
        u = e.u32

        def i(k):
            return int(f[k], 0) if k < len(f) else 0

        def fb(k):
            return int(f[k], 16) & M32 if k < len(f) else 0

        def snd(k):
            return self.snds[i(k)]

        def target(k):
            a = f[k]
            if a[0] == "h":
                return u(self.snds[int(a[1:])] + 52)
            if a[0] == "s":
                return u(self.snds[int(a[1:])] + 56)
            if a[0] == "e":
                return self.probes[int(a[1:])][0]
            return self.snds[int(a)]

        o = f[0]
        if o == "tables":
            self.dump_tables()
        elif o == "statics":
            self.emit("  statics mpaz=%d penv=%08x,%08x,%08x "
                      "aienv=%08x,%08x,%08x max=%d num=%d cse=%d cdse=%d "
                      "rne=%d" % (
                          e.u16(MPAZ), u(PENV), u(PENV + 4), u(PENV + 8),
                          u(AIENV), u(AIENV + 4), u(AIENV + 8),
                          s32(u(MAX)), s32(u(NUM)), s32(u(CSE)),
                          s32(u(CDSE)), s32(u(RNE))))
        elif o == "se":
            e.put32(SE, i(1))
        elif o == "cse":
            e.put32(CSE, i(1))
        elif o == "cdse":
            e.put32(CDSE, i(1))
        elif o == "rne":
            e.put32(RNE, i(1))
        elif o == "npc":
            e.put32(NPC, i(1))
        elif o == "dt":
            e.put32(DT, fb(1))
        elif o == "mpaz":
            e.mem[MPAZ:MPAZ + 2] = struct.pack("<H", i(1) & 0xffff)
        elif o == "ri":
            self.ri.append(i(1))
        elif o == "rf":
            self.rf.append(fb(1))
        elif o == "nu":
            self.nu = (fb(1), fb(2), i(3), fb(4))
        elif o == "nd":
            self.nd[self.snds[i(1)]] = fb(2)
        elif o == "setpov":
            e.mem[self.players[i(1)] + 36] = i(2) & 0xff
        elif o == "notires":
            self.notires = i(1)
        elif o == "car":
            k = i(1)
            c = e.alloc(CAR_SIZE, 16)
            e.mem[c:c + CAR_SIZE] = b"\xa5" * CAR_SIZE
            self.cars[k] = c
            t = self.types[k] = e.alloc(1400, 16)
            e.mem[t:t + 1400] = b"\0" * 1400
            e.write(t + 816, b"Car%d\0" % k)
            e.write(t + 854, b"P%d\0" % k)
            e.put32(t + 1336, i(3))
            d = self.drivers[k] = e.alloc(24, 16)
            e.mem[d:d + 24] = b"\0" * 24
            e.put32(d + 8, i(4))
            e.mem[c + C_DRVNUM:c + C_DRVNUM + 2] = struct.pack(
                "<h", i(2))
            e.put32(c + C_TYPE, t)
            e.put32(c + C_DRIVER, d)
            if i(5) >= 0:
                p = self.players[k] = e.alloc(160, 16)
                e.mem[p:p + 160] = b"\0" * 160
                e.mem[p + 36] = i(5) & 0xff
                e.put32(c + C_PLAYER, p)
            else:
                self.players.pop(k, None)
                e.put32(c + C_PLAYER, 0)
            e.put32(c + C_SOUND, 0)
            e.put32(c + C_SIREN, 0)
            for j in range(4):
                e.put32(c + C_POS + 4 * j, 0)
            e.put32(c + C_VEL, 0)
            e.put32(c + C_BODY, 0)
        elif o == "cpos":
            c = self.cars[i(1)]
            for j in range(3):
                e.put32(c + C_POS + 4 * j, fb(2 + j))
        elif o == "cvel":
            e.put32(self.cars[i(1)] + C_VEL, fb(2))
        elif o == "csiren":
            e.put32(self.cars[i(1)] + C_SIREN, i(2))
        elif o == "zone":
            p = self.players[i(1)]
            e.put32(p + 140, self.srcs["Zone"] if i(2) else 0)
            e.put32(p + 88, i(3))
        elif o == "world":
            prev = self.world
            for x in f[1:]:
                c = self.cars[int(x)]
                e.put32(prev, c)
                e.put32(c + 4, prev)
                prev = c
            e.put32(prev, self.world)
            e.put32(self.world + 4, prev)
            e.put32(PCW, self.world)
        elif o == "noworld":
            e.put32(PCW, 0)
        elif o == "mk":
            k = i(1)
            c = self.cars[k]
            fn = {"player": "mkplayer", "ai": "mkai"}.get(f[2], "mkcop")
            v = self.call(fn, c) & M32
            self.snds[k] = v
            e.put32(c + C_SOUND, v)
            self.emit("  -> %s" % self.name(v))
        elif o == "vc":
            self.vcall(f, target, i, fb)
        elif o == "s3":
            s = target(1)
            e.put32(s, i(2))
            e.put32(s + 8, fb(3))
            e.put32(s + 12, fb(4))
            e.mem[s + 16:s + 18] = struct.pack("<H", i(5) & 0xffff)
            e.put32(s + 24, fb(6))
        elif o == "pov":
            self.call("pov", self.cars[i(1)], i(2))
            self.emit("  = %08x" % e.fpr[0])
        elif o == "splash":
            self.call("splash", snd(1), i(2), i(3))
        elif o == "usplash":
            s = snd(1)
            e.fpr[12] = fb(3)
            if i(2):
                self.call("usplash", s, s + 40, s + 48)
            else:
                self.call("usplash", s, s + 36, s + 44)
        elif o == "settimer":
            s = snd(1)
            e.put32(s + 44, i(2))
            e.put32(s + 48, i(3))
        elif o == "uss":
            self.call("uss", snd(1))
        elif o == "blow":
            self.call("blow", snd(1))
        elif o == "road":
            e.fpr[12] = fb(2)
            self.call("road", snd(1))
        elif o == "sphere":
            self.emit("  = %d" % self.call("sphere", snd(1)))
        elif o == "honk":
            self.call("honk", snd(1))
        elif o == "stophonk":
            self.call("stophonk", snd(1))
        elif o == "ishonk":
            self.emit("  = %d" % self.call("ishonk", snd(1)))
        elif o == "splashs":
            self.emit("  -> %s" % self.name(self.call("splashs", i(1))))
        elif o == "refls":
            self.emit("  -> %s" % self.name(self.call("refls", snd(1),
                                                      i(2))))
        elif o == "windv":
            e.fpr[12] = fb(2)
            self.call("windv", snd(1))
            self.emit("  = %08x" % e.fpr[0])
        elif o == "windp":
            e.fpr[12] = fb(2)
            self.call("windp", snd(1))
            self.emit("  = %08x" % e.fpr[0])
        elif o == "uer":
            e.fpr[12] = fb(2)
            e.fpr[13] = fb(4)
            self.call("uer", snd(1), i(3))
        elif o == "udbr":
            self.call("udbr", snd(1))
        elif o == "refl":
            s = snd(1)
            e.put32(s + 84, i(2))
            e.put32(s + 88, i(3))
            e.put32(s + 92, i(4))
        elif o == "trt":
            self.emit("  -> %s" % self.name(self.call("trt", snd(1))))
        elif o == "ins":
            self.call("ins", snd(1))
        elif o == "actv":
            self.call("actv", snd(1))
        elif o == "ucs":
            self.call("ucs")
        elif o == "max":
            e.put32(MAX, i(1))
        elif o == "closest":
            self.emit("  closest max=%d num=%d%s" % (
                s32(u(MAX)), s32(u(NUM)),
                "".join(" " + self.name(u(CLOSEST + 4 * j))
                        for j in range(6))))
        elif o == "clearclosest":
            for j in range(6):
                e.put32(CLOSEST + 4 * j, 0)
            e.put32(NUM, 0)
        elif o == "choose":
            self.emit("  -> %s" % self.name(self.call("choose",
                                                      u(snd(1) + 52))))
        elif o == "detune":
            e.put32(u(snd(1) + 52) + 220, fb(2))
        elif o == "smode":
            self.call("smode", u(snd(1) + 56), i(2))
        elif o == "sbroken":
            self.call("sbroken", u(snd(1) + 56), i(2))
        elif o == "sbp":
            self.call("sbp", u(snd(1) + 56))
            self.emit("  = %08x" % e.fpr[0])
        elif o == "sset":
            r = u(snd(1) + 56)
            e.put32(r + 596, i(2))
            e.put32(r + 600, fb(3))
            e.put32(r + 608, fb(4))
            e.put32(r + 612, fb(5))
        elif o == "bplaying":
            b = u(snd(1) + 56) + 32 + SAMPLE * i(2)
            if i(3):
                self.playing.add(b)
            else:
                self.playing.discard(b)
        elif o == "body":
            j = i(1)
            if j not in self.bodies:
                self.bodies[j] = e.alloc(336, 16)
                e.mem[self.bodies[j]:self.bodies[j] + 336] = b"\xa5" * 336
                self.bodypos[j] = e.alloc(16, 16)
                self.bodyvel[j] = e.alloc(16, 16)
            b = self.bodies[j]
            e.put32(b + 80, self.bodyvt)
            for k in range(3):
                e.put32(self.bodypos[j] + 4 * k, fb(2 + k))
                e.put32(self.bodyvel[j] + 4 * k, fb(5 + k))
            e.put32(self.bodypos[j] + 12, 0)
            e.put32(self.bodyvel[j] + 12, 0)
            self.bodyterrain[j] = i(8)
        elif o == "cbody":
            e.put32(self.cars[i(1)] + C_BODY, self.bodies[i(2)])
        elif o == "link":
            prev = CBL
            for x in f[1:]:
                b = self.bodies[int(x)]
                e.put32(prev, b)
                e.put32(b + 4, prev)
                prev = b
            e.put32(prev, CBL)
            e.put32(CBL + 4, prev)
        elif o == "loc":
            self.loc = tuple(CBL if x == "L" else self.bodies[int(x)]
                             for x in f[1:3])
        elif o == "d":
            self.dump(i(1))
        else:
            self.emit("  unknown op %s" % o)

    def vcall(self, f, target, i, fb):
        """A call through the vtable, as the image makes one: the vptr at
        +28, the delta added to the Sound3d."""
        e = self.e
        slot = i(2)
        t = target(1)
        vt = e.u32(t + 28)
        delta = s16(e.u16(vt + slot))
        fn = e.u32(vt + slot + 4)
        this = (t + delta) & M32
        if slot in (8, 16, 32):
            e.call(fn, this, i(3), limit=LIMIT)
        elif slot == 24:
            e.fpr[12] = fb(3)
            e.fpr[13] = fb(5)
            e.call(fn, this, i(4), limit=LIMIT)
        elif slot in (40, 48):
            e.call(fn, this, limit=LIMIT)
        elif slot == 56:
            e.call(fn, this, self.cars[i(3)] + C_POS, limit=LIMIT)
        elif slot == 64:
            v = e.call(fn, this, limit=LIMIT)
            self.emit("  -> %s" % self.name(v))
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

# 13.888889f, the reflections' 50 km/h, and the float above it.
AT_50 = 13.88888931274414
OVER_50 = 13.888890266418457
# A body whose distance from the origin is 9.000001 summed as
# (x*x + y*y) + z*z, and 9 summed as x*x + (y*y + z*z).
NEAR_9 = (0.3540845811367035, 8.796019554138184, 1.8720792531967163)


def script():
    L = []
    a = L.append
    third = 1.0 / 30.0

    def nu(vol, pitch, az, dist):
        a("nu|%s|%s|%d|%s" % (fx(vol), fx(pitch), az, fx(dist)))

    def vc(t, slot, *args):
        a("vc|%s|%d%s" % (t, slot, "".join("|" + str(x) for x in args)))

    def upd(t, vol, az, pitch):
        vc(t, 24, fx(vol), az, fx(pitch))

    def body(j, pos, vel, terrain=0):
        a("body|%d|%s|%s|%d" % (j, "|".join(fx(x) for x in pos),
                                "|".join(fx(x) for x in vel), terrain))

    a("tables")
    a("statics")
    a("dt|" + fx(third))
    a("npc|1")
    nu(0.8, 1.1, 1234, 50.0)

    # ---- the cars: k, driver number, usage, driver type, POV (-1 none)
    a("car|0|0|0|1|0")          # the player
    a("car|1|1|0|2|-1")         # an AI racer
    a("car|2|2|1|4|-1")         # a cop
    a("car|3|3|2|3|-1")         # traffic
    a("car|4|4|1|5|-1")         # a super cop
    for k in (5, 6, 7):
        a("car|%d|%d|0|2|-1" % (k, k))
    a("car|8|1|0|1|1")          # split screen's second
    a("car|9|0|0|1|2")          # split screen's first, no horn of its own
    a("car|10|2|0|1|3")         # a third driver
    a("car|11|11|0|2|-1")       # no tyres
    a("car|12|0|0|1|0")         # a player with no tyres
    a("car|13|13|0|2|-1")

    # ---- GetPOVVolume
    for pov in range(4):
        a("setpov|0|%d" % pov)
        for t in range(5):
            a("pov|0|%d" % t)
    a("pov|0|-1")
    a("pov|0|7")
    a("setpov|0|0")
    for t in range(3):
        a("pov|1|%d" % t)

    # ---- the constructors
    a("mk|0|player")
    a("d|0")
    a("mk|1|ai")
    a("d|1")
    a("mk|2|cop")
    a("d|2")
    a("mk|3|ai")
    a("d|3")
    a("mk|4|cop")
    a("d|4")
    for k in (5, 6, 7, 13):
        a("mk|%d|ai" % k)
    a("npc|2")
    a("mk|8|player")
    a("d|8")
    a("mpaz|12345")
    a("mk|9|player")
    a("d|9")
    a("mk|10|player")
    a("d|10")
    a("mpaz|10922")
    a("npc|1")
    a("notires|1")
    a("mk|11|ai")
    a("d|11")
    a("mk|12|player")
    a("d|12")
    a("notires|0")
    a("statics")
    a("trt|0")
    a("trt|8")

    # ---- the samples
    for j in range(3):
        a("splashs|%d" % j)
    a("ri|2")
    a("splashs|-1")
    a("refls|0|0")
    a("refls|0|1")
    a("ri|1")
    a("refls|0|-1")
    for k in (1, 3, 5, 6):
        a("choose|%d" % k)
    a("vc|0|64")
    a("vc|9|64")
    a("vc|1|64")
    a("vc|2|64")

    # ---- the wind
    for pov in (0, 3):
        a("setpov|0|%d" % pov)
        for v in (0.0, 1.0, 37.5, 120.0):
            a("windv|0|" + fx(v))
            a("windp|0|" + fx(v))
    a("setpov|0|0")

    # ---- the player's Update
    a("cvel|0|" + fx(5.0))
    a("zone|0|0|0")
    upd(0, 1.0, 0, 1.0)
    a("d|0")
    upd(0, 0.5, 777, 1.25)
    a("d|0")
    a("zone|0|1|3")
    upd(0, 0.9, 0, 0.95)
    a("zone|0|1|0")
    upd(0, 0.9, 0, 0.95)
    a("zone|0|0|0")
    nu(0.6, 0.9, 40000, 10.0)
    upd(8, 1.0, 0, 1.0)
    a("d|8")
    upd(9, 1.0, 0, 1.0)
    upd(12, 1.0, 0, 1.0)
    a("setpov|0|2")
    upd(0, 1.0, 0, 1.0)
    a("setpov|0|0")

    # ---- the horn
    a("honk|0")
    a("ishonk|0")
    a("d|0")
    a("detune|0|" + fx(1.05))
    upd(0, 1.0, 0, 1.0)
    upd("h0", 0.7, 30000, 1.2)
    a("stophonk|0")
    a("ishonk|0")
    upd("h0", 0.7, 30000, 1.2)
    a("se|0")
    a("honk|0")
    a("ishonk|0")
    a("se|1")
    a("ishonk|0")
    a("cse|0")
    a("honk|0")
    a("ishonk|0")
    a("cse|1")
    a("ishonk|0")
    a("honk|1")
    a("se|0")
    a("ishonk|1")
    a("stophonk|1")
    a("se|1")
    a("ishonk|1")
    a("stophonk|1")
    a("ishonk|1")
    a("honk|1")
    a("cse|0")
    a("stophonk|1")
    a("ishonk|1")
    a("cse|1")
    a("ishonk|1")
    a("stophonk|1")
    a("se|0")
    vc("h1", 48)
    a("se|1")
    vc("h1", 48)
    vc("h1", 40)

    # ---- the AI's Update
    nu(0.8, 1.1, 1234, 50.0)
    upd(1, 1.0, 0, 1.0)
    a("d|1")
    vc(1, 16, 1)
    a("d|1")
    upd(1, 0.5, 4321, 1.5)
    a("d|1")
    # Not active, only: retail's AI Update does not test the tyre.
    upd(11, 1.0, 0, 1.0)
    vc(11, 16, 1)
    vc(1, 16, 0)
    a("d|1")
    vc(1, 56, 1)

    # ---- the siren
    a("uss|2")
    a("d|2")
    a("s3|2|1|%s|%s|500|%s" % (fx(0.9), fx(1.0), fx(20.0)))
    a("csiren|2|1")
    a("uss|2")
    a("d|2")
    a("uss|2")
    a("csiren|2|4")
    a("rf|" + fx(0.5))
    a("uss|2")
    a("d|2")
    a("uss|2")
    a("uss|2")
    a("csiren|2|2")
    a("uss|2")
    a("d|2")
    a("sset|2|2|%s|%s|%s" % (fx(0.01), fx(1.0), fx(1.0)))
    a("uss|2")
    a("d|2")
    a("bplaying|2|0|0")
    a("uss|2")
    a("se|0")
    a("bplaying|2|0|0")
    a("uss|2")
    a("se|1")
    a("sset|2|1|%s|%s|%s" % (fx(third), fx(1.0), fx(1.0)))
    a("uss|2")
    a("d|2")
    a("sset|2|1|%s|%s|%s" % (fx(0.0125), fx(1.0), fx(1.0)))
    a("bplaying|2|2|1")
    a("uss|2")
    a("d|2")
    a("csiren|2|0")
    a("uss|2")
    a("d|2")
    a("csiren|2|3")
    a("uss|2")
    a("s3|2|0|%s|%s|500|%s" % (fx(0.9), fx(1.0), fx(20.0)))
    a("uss|2")
    a("d|2")
    a("s3|2|1|0|%s|500|%s" % (fx(1.0), fx(20.0)))
    a("uss|2")
    a("d|2")
    a("s3|2|1|%s|%s|500|%s" % (fx(0.5), fx(1.0), fx(20.0)))
    a("smode|2|4")
    a("d|2")
    a("smode|2|1")
    a("d|2")
    a("smode|2|0")
    a("smode|2|0")
    a("sbroken|2|1")
    a("d|2")
    a("smode|2|0")
    a("d|2")
    a("se|0")
    a("smode|2|1")
    a("se|1")
    a("sset|2|1|%s|%s|%s" % (fx(17.0), fx(1.0), fx(1.0)))
    a("smode|2|0")
    a("d|2")
    a("smode|2|4")
    a("sset|2|0|%s|%s|%s" % (fx(17.0), fx(1.0), fx(1.0)))
    a("rf|" + fx(0.25))
    a("sbp|2")
    a("sbp|2")
    a("d|2")
    a("sset|2|0|%s|%s|%s" % (fx(17.0), fx(0.5), fx(0.52)))
    a("sbp|2")
    a("sbp|2")
    a("sset|2|0|%s|%s|%s" % (fx(17.0), fx(1.2), fx(1.18)))
    a("sbp|2")
    a("sbp|2")
    a("rf|" + fx(0.9))
    a("sbp|2")
    a("sset|2|0|%s|%s|%s" % (fx(17.0), fx(1.0), fx(0.5)))
    a("sbp|2")
    upd("s2", 0.8, 100, 1.1)
    a("sbroken|2|0")
    upd("s2", 0.8, 100, 1.1)
    upd("s2", 0.0, 100, 1.1)
    a("d|2")
    nu(0.8, 1.1, 1234, 50.0)
    a("s3|2|1|%s|%s|500|%s" % (fx(0.9), fx(1.0), fx(20.0)))
    a("csiren|2|1")
    upd(2, 1.0, 0, 1.0)
    a("d|2")
    a("csiren|4|3")
    upd(4, 1.0, 0, 1.0)
    vc(4, 16, 1)
    upd(4, 1.0, 0, 1.0)
    a("d|4")

    # ---- the splashes
    a("splash|1|0|2")
    a("splash|1|1|3")
    a("d|1")
    a("ri|1")
    a("usplash|1|0|" + fx(0.5))
    a("d|1")
    a("splash|1|0|1")
    a("usplash|1|0|" + fx(0.5))
    a("d|1")
    for _ in range(9):
        a("usplash|1|0|" + fx(0.5))
    a("splash|1|0|4")
    a("ri|2")
    a("usplash|1|0|" + fx(0.25))
    a("d|1")
    a("ri|0")
    a("usplash|1|1|" + fx(0.75))
    a("settimer|1|0|0")
    a("splash|1|1|2")
    a("se|0")
    a("usplash|1|1|" + fx(0.75))
    a("se|1")
    a("settimer|1|0|0")
    a("splash|1|1|2")
    a("cse|0")
    a("usplash|1|1|" + fx(0.75))
    a("cse|1")
    a("settimer|1|0|0")
    a("splash|1|1|2")
    a("rne|0")
    a("usplash|1|1|" + fx(0.75))
    a("rne|1")
    a("d|1")
    a("settimer|1|0|0")
    a("splash|1|0|1")
    a("splash|1|1|1")
    a("ri|0")
    a("ri|2")
    vc(1, 16, 1)
    upd(1, 1.0, 0, 1.0)
    a("d|1")

    # ---- Mute
    for k in (0, 1, 2, 11, 12):
        vc(k, 32, 1)
        vc(k, 32, 0)
    vc(0, 32, 2)
    a("zone|0|1|1")
    vc(0, 32, 1)
    a("zone|0|0|0")
    vc("h0", 32, 1)
    vc("s2", 32, 0)

    # ---- Deactivate and Activate
    vc(0, 40)
    vc(0, 48)
    vc(2, 40)
    vc(2, 48)
    vc(11, 40)
    vc(11, 48)
    vc(0, 16, 0)
    a("d|0")
    vc(0, 16, 1)
    a("d|0")

    # ---- the tyres
    a("blow|0")
    a("blow|1")
    a("blow|11")
    a("cdse|0")
    a("blow|0")
    a("cdse|1")
    a("cse|0")
    a("blow|0")
    a("cse|1")
    a("se|0")
    a("blow|0")
    a("se|1")
    a("road|0|" + fx(0.5))
    a("road|1|" + fx(2.0))
    a("road|12|" + fx(1.0))

    # ---- the sound sphere
    for d in (0.0, 129.99, 130.0, 130.01, 500.0):
        a("s3|1|0|%s|%s|0|%s" % (fx(1.0), fx(1.0), fx(d)))
        a("sphere|1")

    # ---- the engine's reflections
    a("cpos|0|0|0|0")
    body(0, (0.0, 0.0, 0.0), (20.0, 0.0, 0.0))        # the car's own
    body(1, (1.0, 1.0, 0.0), (-20.0, 0.0, 0.0), 28)   # a plant
    body(2, (5.0, 0.0, 8.0), (-20.0, 0.0, 0.0))       # too far, in z
    body(3, (2.0, 1.0, 0.0), (25.0, 0.0, 0.0))        # too slow
    body(4, (1.0, 3.0, 0.0), (-20.0, 0.0, 0.0))       # crossing ahead
    body(5, (-0.5, -2.0, 0.0), (40.0, 0.0, 0.0))      # crossing behind
    body(6, (3.0, 2.0, 0.0), (-20.0, 0.0, 0.0))       # not crossing
    body(7, (9.0, 0.0, 0.0), (-20.0, 0.0, 0.0))       # at 9
    body(8, (0.5, -4.0, 0.0), (-25.0, 0.0, 0.0))      # crossing, right
    body(9, (-2.0, 1.0, 0.0), (0.0, -30.0, 0.0))      # crossing heading +y
    a("cbody|0|0")
    a("link|1|2|0|3|4|5|6|7|8|9")
    a("loc|L|L")
    a("refl|0|0|0|0")
    a("udbr|0")
    a("d|0")
    a("refl|0|0|0|0")
    a("cpos|0|%s|0|0" % fx(2.0))
    a("udbr|0")
    a("d|0")
    a("refl|0|0|0|0")
    a("loc|3|6")
    a("udbr|0")
    a("d|0")
    a("loc|L|3")
    a("udbr|0")
    a("loc|8|L")
    a("udbr|0")
    a("cpos|0|0|0|0")
    a("loc|L|L")
    body(0, (0.0, 0.0, 0.0), (0.0, 20.0, 0.0))        # heading +y
    a("refl|0|0|0|0")
    a("udbr|0")
    a("d|0")
    body(0, (0.0, 0.0, 0.0), (20.0, 0.0, 0.0))

    # Passing the nose at 50 km/h relative, exactly and the float above it;
    # at a distance over 9 in the sums' order and not in another; slower
    # than the car in y, the car heading +y.
    for v in (AT_50, OVER_50):
        body(11, (0.2, 1.0, 0.0), (20.0 - v, 0.0, 0.0))
        a("link|0|11")
        a("refl|0|0|0|0")
        a("udbr|0")
        a("d|0")
    body(11, NEAR_9, (-20.0, 0.0, 0.0))
    a("refl|0|0|0|0")
    a("udbr|0")
    a("d|0")
    body(0, (0.0, 0.0, 0.0), (0.0, 20.0, 0.0))
    body(11, (1.0, 0.1, 0.0), (0.0, 15.0, 0.0))
    a("refl|0|0|0|0")
    a("udbr|0")
    a("d|0")
    body(0, (0.0, 0.0, 0.0), (20.0, 0.0, 0.0))
    a("link|1|2|0|3|4|5|6|7|8|9")

    for speed in (5.0, 13.88, 13.888889, 13.89, 25.0):
        a("cvel|0|" + fx(speed))
        a("refl|0|1|1|0")
        a("ri|1")
        a("ri|0")
        a("uer|0|%s|9|%s" % (fx(0.8), fx(1.1)))
        a("d|0")
    a("cvel|0|" + fx(25.0))
    a("refl|0|1|0|0")
    a("ri|1")
    a("uer|0|%s|0|%s" % (fx(1.0), fx(1.0)))
    a("refl|0|0|1|0")
    a("uer|0|%s|0|%s" % (fx(1.0), fx(1.0)))
    a("refl|0|0|0|0")
    a("uer|0|%s|0|%s" % (fx(1.0), fx(1.0)))
    a("d|0")
    a("se|0")
    a("refl|0|1|1|0")
    a("uer|0|%s|0|%s" % (fx(1.0), fx(1.0)))
    a("d|0")
    a("se|1")
    a("cse|0")
    a("refl|0|1|1|0")
    a("uer|0|%s|0|%s" % (fx(1.0), fx(1.0)))
    a("d|0")
    a("cse|1")
    upd(0, 1.0, 0, 1.0)
    a("d|0")
    a("cvel|0|" + fx(5.0))

    # ---- the closest
    a("clearclosest")
    a("max|3")
    for k, d in ((1, 50.0), (3, 200.0), (5, 20.0), (6, 100.0), (7, 10.0),
                 (2, 129.0), (4, 5.0), (11, 30.0), (13, 5.0)):
        a("s3|%d|0|%s|%s|0|%s" % (k, fx(1.0), fx(1.0), fx(d)))
    for k in (1, 3, 5, 6):
        a("ins|%d" % k)
        a("closest")
    for k in (7, 2, 4, 11, 13):
        a("ins|%d" % k)
        a("closest")
    for k in (1, 2, 3, 4, 5, 6, 7, 11, 13):
        a("actv|%d" % k)
    for k in (1, 7):
        a("d|%d" % k)
    a("max|6")
    a("clearclosest")
    for k in (1, 5, 6, 7, 2, 4, 11):
        a("ins|%d" % k)
    a("closest")
    for k in (1, 2, 4, 7):
        a("actv|%d" % k)

    a("noworld")
    a("ucs")
    a("closest")
    for k, d in ((1, 50.0), (2, 129.0), (3, 200.0), (4, 5.0), (5, 20.0),
                 (6, 100.0), (7, 10.0), (13, 30.0), (0, 1.0)):
        a("nd|%d|%s" % (k, fx(d)))
    a("world|0|1|2|3|4|5|6|7|13")
    a("npc|1")
    a("ucs")
    a("closest")
    a("ucs")
    a("closest")
    a("npc|2")
    a("ucs")
    a("closest")
    a("nd|7|" + fx(300.0))
    a("nd|4|" + fx(131.0))
    a("ucs")
    a("closest")
    a("npc|1")
    a("world")
    a("ucs")
    a("closest")
    a("world|1|0")
    a("ucs")
    a("closest")
    for k in (1, 2, 4, 7):
        a("d|%d" % k)
    a("noworld")

    # ---- a third cop, on the first siren again
    a("car|14|14|1|4|-1")
    a("mk|14|cop")
    a("d|14")

    # ---- the destructors
    vc("h3", 8, 0)
    vc(0, 8, 3)
    vc(1, 8, 3)
    vc(2, 8, 3)
    vc(3, 8, 0)
    vc(4, 8, 3)
    vc(8, 8, 3)
    vc(11, 8, 3)
    vc(12, 8, 0)
    vc(14, 8, 3)
    a("statics")
    return L


# ================================================================= build

def build_harness(tmp, name="carsound_test"):
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


def _m(name, before, after):
    return (name, CSC, before, after)


# The first two of a reflection's plays, up to the azimuth that tells them
# apart.
RL = ("bsample_play(smp, vol * volume, 0.0f, pit - 1.0f);\n"
      "                bsample_set_azimuth(smp, (uint16_t)-")
RR = ("bsample_play(smp, vol * volume, 0.0f, pit - 1.0f);\n"
      "                bsample_set_azimuth(smp, ReflectionAzimuth);")
SE_RL = ("if (SoundEnabled && CarSoundEnabled) {\n"
         "                smp = baseplayercarsound_get_engine_reflection_"
         "sample(s, -1);\n                " + RL)

MUTATIONS = [
    # ---- the globals and the tables
    _m("g-cse", "int32_t CarSoundEnabled = 1;", "int32_t CarSoundEnabled = 0;"),
    _m("g-cdse", "int32_t CarDamageSoundEnabled = 1;",
       "int32_t CarDamageSoundEnabled = 0;"),
    _m("g-rne", "int32_t RoadNoiseEnabled = 1;", "int32_t RoadNoiseEnabled = 0;"),
    _m("env-p-max", "    1.3f, 260.0f, 1.0f / 260.0f",
       "    1.25f, 260.0f, 1.0f / 260.0f"),
    _m("env-p-cut", "1.3f, 260.0f,", "1.3f, 250.0f,"),
    _m("env-p-coeff", "1.0f / 260.0f", "1.0f / 250.0f"),
    _m("env-ai-max", "    1.3f, 130.0f, 1.0f / 130.0f",
       "    1.25f, 130.0f, 1.0f / 130.0f"),
    _m("env-ai-cut", "1.3f, 130.0f,", "1.3f, 120.0f,"),
    _m("env-ai-coeff", "1.0f / 130.0f", "1.0f / 120.0f"),
    _m("g-max", "int32_t MaxActiveCarSounds = 3;",
       "int32_t MaxActiveCarSounds = 6;"),
    _m("pov-00", "{ 0.8f,  1.0f,  0.75f }", "{ 0.85f, 1.0f,  0.75f }"),
    _m("pov-01", "{ 0.8f,  1.0f,  0.75f }", "{ 0.8f,  1.1f,  0.75f }"),
    _m("pov-02", "{ 0.8f,  1.0f,  0.75f }", "{ 0.8f,  1.0f,  0.7f  }"),
    _m("pov-12", "{ 0.9f,  0.9f,  0.85f }", "{ 0.9f,  0.9f,  0.8f  }"),
    _m("pov-21", "{ 1.0f,  0.75f, 1.0f  }", "{ 1.0f,  0.7f,  1.0f  }"),
    _m("pov-30", "{ 1.25f, 0.4f,  0.9f  }", "{ 1.2f,  0.4f,  0.9f  }"),
    _m("refl-az", "ReflectionAzimuth = 16384;", "ReflectionAzimuth = 16000;"),
    _m("horn-counter", "static int32_t  HornCounter;",
       "static int32_t  HornCounter = 1;"),
    _m("siren-counter", "static int32_t  SirenCounter;",
       "static int32_t  SirenCounter = 1;"),

    # ---- smooth
    _m("smooth-up", "    if (up < b)\n        return up;",
       "    if (up < b)\n        return b;"),
    _m("smooth-down", "    if (b < down)\n        return down;",
       "    if (b < down)\n        return b;"),
    _m("smooth-step", "down = a - step;", "down = a - 2.0f * step;"),

    # ---- GetPOVVolume
    _m("pov-noplayer", "DriveCameraPOVIndex : 0;", "DriveCameraPOVIndex : 1;"),
    _m("pov-t0", "        return POVVolumeTable[pov][0];",
       "        return POVVolumeTable[pov][1];"),
    _m("pov-t1", "        return POVVolumeTable[pov][2];",
       "        return POVVolumeTable[pov][1];"),
    _m("pov-t2", "        return POVVolumeTable[pov][1];\n    }",
       "        return POVVolumeTable[pov][2];\n    }"),
    _m("pov-other", "    }\n    return 1.0f;\n}", "    }\n    return 0.0f;\n}"),

    # ---- the factories and the closest list
    _m("cp-size", "bMalloc(sizeof(BasePlayerCarSound),",
       "bMalloc(sizeof(BasePlayerCarSound) + 16,"),
    _m("cp-align", "\"PlayerCarSound\", 0, 16);", "\"PlayerCarSound\", 0, 8);"),
    _m("ca-size", "    BaseAICarSound *s = bMalloc(sizeof(BaseAICarSound), "
       "\"AICarSound\", 0, 16);\n\n    baseaicarsound_construct(s, c);\n"
       "    return &s->Base;\n}\n\n// The cop's",
       "    BaseAICarSound *s = bMalloc(sizeof(BaseAICarSound) + 16, "
       "\"AICarSound\", 0, 16);\n\n    baseaicarsound_construct(s, c);\n"
       "    return &s->Base;\n}\n\n// The cop's"),
    _m("cop-tag", "\"AICarSound\", 0, 16);\n\n    baseaicarsound_construct(s, c);"
       "\n    return &s->Base;\n}\n\nvoid carsound_delete",
       "\"AICopCarSound\", 0, 16);\n\n    baseaicarsound_construct(s, c);"
       "\n    return &s->Base;\n}\n\nvoid carsound_delete"),
    _m("delete-flags", "    s3d_destroy(s, flags);", "    s3d_destroy(s, 0);"),
    _m("rev-tc", "return ((BasePlayerCarSound *)s)->ReverbTopologyCoordinate;",
       "return NULL;"),
    _m("mi-sphere", "    if (!basecarsound_in_sound_sphere(s))\n        return;",
       "    if (0)\n        return;"),
    _m("mi-max1", "    for (i = 0; i < MaxActiveCarSounds; i++) {\n"
       "        if (ClosestCarSounds[i] == NULL) {",
       "    for (i = 0; i < MaxActiveCarSounds - 1; i++) {\n"
       "        if (ClosestCarSounds[i] == NULL) {"),
    _m("mi-num", "            NumClosestCarSounds++;",
       "            NumClosestCarSounds += 2;"),
    _m("mi-fill-break", "            NumClosestCarSounds++;\n            return;",
       "            NumClosestCarSounds++;\n            break;"),
    _m("mi-max2", "    for (i = 0; i < MaxActiveCarSounds; i++) {\n"
       "        if (s->Sound.SndToCameraDistance",
       "    for (i = 0; i < MaxActiveCarSounds - 1; i++) {\n"
       "        if (s->Sound.SndToCameraDistance"),
    _m("mi-cmp", "            < ClosestCarSounds[i]->Sound.SndToCameraDistance",
       "            <= ClosestCarSounds[i]->Sound.SndToCameraDistance"),
    _m("mi-replace-all", "            ClosestCarSounds[i] = s;\n            return;\n"
       "        }\n    }\n}",
       "            ClosestCarSounds[i] = s;\n        }\n    }\n}"),
    _m("ma-max", "    for (i = 0; i < MaxActiveCarSounds; i++) {\n"
       "        if (ClosestCarSounds[i] == s) {",
       "    for (i = 0; i < MaxActiveCarSounds - 1; i++) {\n"
       "        if (ClosestCarSounds[i] == s) {"),
    _m("ma-act", "    s3d_activate(s, found);", "    s3d_activate(s, !found);"),
    _m("ucs-world", "    if (pCurrentWorld == NULL)\n        return;\n"
       "    MaxActiveCarSounds", "    MaxActiveCarSounds"),
    _m("ucs-max", "NumPlayerCars > 1 ? 3 : 6;", "NumPlayerCars > 2 ? 3 : 6;"),
    _m("ucs-max3", "NumPlayerCars > 1 ? 3 : 6;", "NumPlayerCars > 1 ? 2 : 6;"),
    _m("ucs-max6", "NumPlayerCars > 1 ? 3 : 6;", "NumPlayerCars > 1 ? 3 : 5;"),
    _m("ucs-update", "        car_update_sound(c);", "        (void)c;"),
    _m("ucs-clear", "    for (i = 0; i < MaxActiveCarSounds; i++)\n"
       "        ClosestCarSounds[i] = NULL;",
       "    for (i = 0; i < 1; i++)\n        ClosestCarSounds[i] = NULL;"),
    _m("ucs-num", "    NumClosestCarSounds = 0;\n", ""),
    _m("ucs-ins-player", "        if (c->MyDriver->TheDriverType != "
       "DRIVER_TYPE_PLAYER\n            && c->pBaseCarSound != NULL)\n"
       "            carsound_maybe_insert",
       "        if (c->pBaseCarSound != NULL)\n            carsound_maybe_insert"),
    _m("ucs-act-player", "        if (c->MyDriver->TheDriverType != "
       "DRIVER_TYPE_PLAYER\n            && c->pBaseCarSound != NULL)\n"
       "            carsound_maybe_activate",
       "        if (c->pBaseCarSound != NULL)\n"
       "            carsound_maybe_activate"),

    # ---- BaseCarSound
    _m("bc-splashL", "    s->SplashLeft = 0;\n", "    s->SplashLeft = 1;\n"),
    _m("bc-splashR", "    s->SplashRight = 0;\n", "    s->SplashRight = 1;\n"),
    _m("bc-timerL", "    s->SplashLeftTimer = 0;\n", "    s->SplashLeftTimer = 1;\n"),
    _m("bc-timerR", "    s->SplashRightTimer = 0;\n",
       "    s->SplashRightTimer = 1;\n"),
    _m("bc-splash-n", "    for (i = 0; i < 3; i++)\n        bsample_set_category(",
       "    for (i = 0; i < 2; i++)\n        bsample_set_category("),
    _m("bc-splash-cat", "bsample_set_category(basecarsound_get_splash_sample(i), 0);",
       "bsample_set_category(basecarsound_get_splash_sample(i), 1);"),
    _m("bc-pop", "in_game_sample(\"TirePop1\");", "in_game_sample(\"TirePop2\");"),
    _m("bc-pop-cat", "    bsample_set_category(s->TireSoundBlowOut, 0);",
       "    bsample_set_category(s->TireSoundBlowOut, 1);"),
    _m("bc-cop", "UsageType == CAR_USAGE_TYPE_COP)",
       "UsageType != CAR_USAGE_TYPE_COP)"),
    _m("bc-siren-tag", "\"SirenSound\",\n", "\"SirenSound3d\",\n"),
    _m("bc-siren-null", "    } else {\n        s->SirenSound = NULL;\n    }\n}",
       "    }\n}"),
    _m("bd-horn", "        s3d_destroy(s->HornSound, 3);",
       "        s3d_destroy(s->HornSound, 0);"),
    _m("bd-engine", "        s3d_destroy(s->EngineSound, 3);",
       "        s3d_destroy(s->EngineSound, 0);"),
    _m("bd-siren", "        s3d_destroy(s->SirenSound, 3);",
       "        s3d_destroy(s->SirenSound, 0);"),
    _m("bd-tire0", "        s3d_destroy(s->TireSound[0], 3);",
       "        s3d_destroy(s->TireSound[0], 0);"),
    _m("bd-tire1", "        s3d_destroy(s->TireSound[1], 3);",
       "        s3d_destroy(s->TireSound[1], 0);"),
    _m("bd-flags", "    sound3d_destroy(&s->Sound, flags);\n}\n\n"
       "void basecarsound_update(",
       "    sound3d_destroy(&s->Sound, 0);\n}\n\nvoid basecarsound_update("),
    _m("bu-env", "&s->pCar->State.Position, s->pSoundEnvelope);",
       "&s->pCar->State.Position, &BaseAICarSoundEnvelope);"),
    _m("bu-vol", "    s->Sound.Volume *= volume;", "    s->Sound.Volume *= pitch;"),
    _m("bu-pitch", "    s->Sound.Pitch *= pitch;", "    s->Sound.Pitch *= volume;"),
    _m("bu-horn-az", "    s3d_update(s->HornSound, s->Sound.Volume, "
       "s->Sound.Azimuth,", "    s3d_update(s->HornSound, s->Sound.Volume, "
       "azimuth,"),
    _m("bu-siren", "    if (s->SirenSound != NULL)\n"
       "        basecarsound_update_siren_sound(s);",
       "    if (0)\n        basecarsound_update_siren_sound(s);"),
    _m("bu-splashL", "&s->SplashLeft,\n                               "
       "&s->SplashLeftTimer);",
       "&s->SplashLeft,\n                               "
       "&s->SplashRightTimer);"),
    _m("bu-splashR-vol", "basecarsound_update_splash(s, s->Sound.Volume, "
       "&s->SplashRight,", "basecarsound_update_splash(s, volume, "
       "&s->SplashRight,"),
    _m("us-act", "    if (s->Sound.Activated)\n        sirensound3d_update_mode",
       "    if (!s->Sound.Activated)\n        sirensound3d_update_mode"),
    _m("us-off", "    else if (siren->Sound.Activated)\n"
       "        s3d_activate(siren, 0);",
       "    else if (siren->Sound.Activated)\n        s3d_activate(siren, 1);"),
    _m("us-pitch", "    s3d_update(siren, s->Sound.Volume, s->Sound.Azimuth, "
       "s->Sound.Pitch);", "    s3d_update(siren, s->Sound.Volume, "
       "s->Sound.Azimuth, 1.0f);"),
    _m("bh-null", "    (void)s;\n    return NULL;\n}",
       "    return (BSample *)s;\n}"),
    _m("ts-side", "    if (right)\n        s->SplashRight = level;",
       "    if (!right)\n        s->SplashRight = level;"),
    _m("sp-dec", "    if (*timer != 0)\n        (*timer)--;",
       "    if (*timer > 1)\n        (*timer)--;"),
    _m("sp-none", "    if (*splash == 0)\n        return;",
       "    if (*splash < 0)\n        return;"),
    _m("sp-drop", "    if (*timer != 0) {\n        *splash = 0;\n        return;",
       "    if (*timer != 0) {\n        return;"),
    _m("sp-rne", "if (SoundEnabled && CarSoundEnabled && RoadNoiseEnabled)",
       "if (SoundEnabled && CarSoundEnabled)"),
    _m("sp-cse", "if (SoundEnabled && CarSoundEnabled && RoadNoiseEnabled)",
       "if (SoundEnabled && RoadNoiseEnabled)"),
    _m("sp-se", "if (SoundEnabled && CarSoundEnabled && RoadNoiseEnabled)",
       "if (CarSoundEnabled && RoadNoiseEnabled)"),
    _m("sp-sample", "bsample_play(basecarsound_get_splash_sample(-1),",
       "bsample_play(basecarsound_get_splash_sample(0),"),
    _m("sp-vol", "volume * (float)*splash, -1.0f, 0.0f);",
       "volume, -1.0f, 0.0f);"),
    _m("sp-pan", "(float)*splash, -1.0f, 0.0f);", "(float)*splash, 0.0f, 0.0f);"),
    _m("sp-timer", "    *timer = 10;", "    *timer = 9;"),
    _m("sp-clear", "    *timer = 10;\n    *splash = 0;", "    *timer = 10;"),
    _m("m-horn", "    s3d_mute(s->HornSound, on);", "    s3d_mute(s->HornSound, !on);"),
    _m("m-engine", "        s3d_mute(s->EngineSound, on);",
       "        s3d_mute(s->EngineSound, !on);"),
    _m("m-siren", "        s3d_mute(s->SirenSound, on);",
       "        s3d_mute(s->SirenSound, !on);"),
    _m("m-tires", "            s3d_mute(s->TireSound[i], on);",
       "            s3d_mute(s->TireSound[i], !on);"),
    _m("m-tires-n", "    for (i = 0; i < 2; i++)\n        if (s->TireSound[i] != NULL)\n"
       "            s3d_mute(", "    for (i = 0; i < 1; i++)\n"
       "        if (s->TireSound[i] != NULL)\n            s3d_mute("),
    _m("m-splash-n", "    for (i = 0; i < 3; i++)\n        bsample_pause(",
       "    for (i = 0; i < 2; i++)\n        bsample_pause("),
    _m("m-splash-on", "bsample_pause(basecarsound_get_splash_sample(i), on != 0);",
       "bsample_pause(basecarsound_get_splash_sample(i), on == 0);"),
    _m("bo-cdse", "if (SoundEnabled && CarSoundEnabled && CarDamageSoundEnabled)",
       "if (SoundEnabled && CarSoundEnabled)"),
    _m("bo-cse", "if (SoundEnabled && CarSoundEnabled && CarDamageSoundEnabled)",
       "if (SoundEnabled && CarDamageSoundEnabled)"),
    _m("bo-se", "if (SoundEnabled && CarSoundEnabled && CarDamageSoundEnabled)",
       "if (CarSoundEnabled && CarDamageSoundEnabled)"),
    _m("bo-az", "                     (float)s->Sound.Azimuth, s->Sound.Pitch);",
       "                     0.0f, s->Sound.Pitch);"),
    _m("bo-pitch", "(float)s->Sound.Azimuth, s->Sound.Pitch);",
       "(float)s->Sound.Azimuth, s->Sound.Pitch - 1.0f);"),
    _m("bo-tires", "        if (s->TireSound[i] != NULL && "
       "gTireSoundTriggerBlowOutFn != NULL)",
       "        if (i == 0 && s->TireSound[i] != NULL && "
       "gTireSoundTriggerBlowOutFn != NULL)"),
    _m("rn-f", "gTireSoundScaleRoadNoiseFn(s->TireSound[i], f);",
       "gTireSoundScaleRoadNoiseFn(s->TireSound[i], 1.0f);"),
    _m("rn-n", "        if (s->TireSound[i] != NULL && "
       "gTireSoundScaleRoadNoiseFn != NULL)",
       "        if (i == 1 && s->TireSound[i] != NULL && "
       "gTireSoundScaleRoadNoiseFn != NULL)"),
    _m("sphere-r", "SndToCameraDistance < 130.0f;", "SndToCameraDistance < 131.0f;"),
    _m("sphere-le", "SndToCameraDistance < 130.0f;",
       "SndToCameraDistance <= 130.0f;"),
    _m("honk-se", "    if (SoundEnabled && CarSoundEnabled)\n"
       "        s3d_activate(s->HornSound, 1);",
       "    if (CarSoundEnabled)\n        s3d_activate(s->HornSound, 1);"),
    _m("honk-cse", "    if (SoundEnabled && CarSoundEnabled)\n"
       "        s3d_activate(s->HornSound, 1);",
       "    if (SoundEnabled)\n        s3d_activate(s->HornSound, 1);"),
    _m("stophonk-test", "    if (SoundEnabled && CarSoundEnabled)\n"
       "        s3d_activate(s->HornSound, 0);",
       "    if (SoundEnabled)\n        s3d_activate(s->HornSound, 0);"),
    _m("ishonk-test", "    if (SoundEnabled && CarSoundEnabled)\n"
       "        return s->HornSound->Sound.Activated != 0;",
       "    if (SoundEnabled)\n"
       "        return s->HornSound->Sound.Activated != 0;"),
    _m("ishonk-off", "    return 0;\n}\n\n// The siren is left alone",
       "    return 1;\n}\n\n// The siren is left alone"),
    _m("da-horn", "    s3d_activate(s->HornSound, 0);\n"
       "    if (s->EngineSound != NULL)\n", "    if (s->EngineSound != NULL)\n"),
    _m("da-engine", "        s3d_activate(s->EngineSound, 0);",
       "        s3d_activate(s->EngineSound, 1);"),
    _m("da-tires", "            s3d_activate(s->TireSound[i], 0);",
       "            s3d_activate(s->TireSound[i], 1);"),
    _m("da-tires-n", "    for (i = 0; i < 2; i++)\n        if (s->TireSound[i] != NULL)\n"
       "            s3d_activate(s->TireSound[i], 0);",
       "    for (i = 0; i < 1; i++)\n        if (s->TireSound[i] != NULL)\n"
       "            s3d_activate(s->TireSound[i], 0);"),
    _m("ac-engine", "        s3d_activate(s->EngineSound, 1);",
       "        s3d_activate(s->EngineSound, 0);"),
    _m("ac-tires", "            s3d_activate(s->TireSound[i], 1);",
       "            s3d_activate(s->TireSound[i], 0);"),
    _m("ac-tires-n", "    for (i = 0; i < 2; i++)\n        if (s->TireSound[i] != NULL)\n"
       "            s3d_activate(s->TireSound[i], 1);",
       "    for (i = 0; i < 1; i++)\n        if (s->TireSound[i] != NULL)\n"
       "            s3d_activate(s->TireSound[i], 1);"),
    _m("ss-rand", "        i = sound_random_int(sound_get(), 3);",
       "        i = sound_random_int(sound_get(), 2);"),
    _m("ss-name", "    name[6] = (char)('1' + i);", "    name[6] = (char)('0' + i);"),

    # ---- BasePlayerCarSound
    _m("pc-vt", "    s->Base.Sound._vtable = BASEPLAYERCARSOUND_VTABLE;\n"
       "    bsample_construct(", "    s->Base.Sound._vtable = BASECARSOUND_VTABLE;\n"
       "    bsample_construct("),
    _m("pc-tc-line", "                 773, 16);", "                 774, 16);"),
    _m("pc-tc-init", "    topology_init(tc);\n", ""),
    _m("pc-rl", "    s->EngineReflectionLeft = 0;\n    s->EngineReflectionRight = 0;\n"
       "    s->ReverbTopologyCoordinate",
       "    s->EngineReflectionLeft = 1;\n    s->EngineReflectionRight = 0;\n"
       "    s->ReverbTopologyCoordinate"),
    _m("pc-rr", "    s->EngineReflectionRight = 0;\n    s->ReverbTopologyCoordinate",
       "    s->EngineReflectionRight = 1;\n    s->ReverbTopologyCoordinate"),
    _m("pc-chk", "    s->CheckForReflected = 1;\n    s->Base.pSoundEnvelope",
       "    s->CheckForReflected = 0;\n    s->Base.pSoundEnvelope"),
    _m("pc-env", "    s->Base.pSoundEnvelope = &BasePlayerCarSoundEnvelope;",
       "    s->Base.pSoundEnvelope = &BaseAICarSoundEnvelope;"),
    _m("pc-wind", "in_game_sample(\"Wind\"));", "in_game_sample(\"Wind1\"));"),
    _m("pc-wind-cat", "    bsample_set_category(&s->WindSample, 0);",
       "    bsample_set_category(&s->WindSample, 1);"),
    _m("pc-horn-tag", "\"HornSound3d\", 0, 16);\n"
       "    hs = baseplayercarsound_get_horn_sample(s);",
       "\"HornSound\", 0, 16);\n    hs = baseplayercarsound_get_horn_sample(s);"),
    _m("pc-horn-sample", "    hs = baseplayercarsound_get_horn_sample(s);",
       "    hs = NULL;"),
    _m("pc-engine", "? gCreatePlayerEngineFn(c) : NULL;",
       "? gCreateAIEngineFn(c) : NULL;"),
    _m("pc-tire0", "? gCreatePlayerTireFn(c, 0) : NULL;",
       "? gCreatePlayerTireFn(c, 1) : NULL;"),
    _m("pc-tire1-test", "    if (TheRaceParameters.NumPlayerCars == 1)\n",
       "    if (TheRaceParameters.NumPlayerCars >= 1)\n"),
    _m("pc-tire1", "? gCreatePlayerTireFn(c, 1) : NULL;",
       "? gCreatePlayerTireFn(c, 0) : NULL;"),
    _m("pc-az0", "    s->PlayerAzimuth = 0;\n", "    s->PlayerAzimuth = 1;\n"),
    _m("pc-az-test", "NumPlayerCars >= 2) {", "NumPlayerCars >= 3) {"),
    _m("pc-az-left", "s->PlayerAzimuth = (uint16_t)-CarSoundMultiPlayerAzimuth;",
       "s->PlayerAzimuth = CarSoundMultiPlayerAzimuth;"),
    _m("pc-az-d0", "        if (c->DriverNumber == 0)",
       "        if (c->DriverNumber == 2)"),
    _m("pc-az-d1", "        else if (c->DriverNumber == 1)",
       "        else if (c->DriverNumber == 2)"),
    _m("pc-activate", "    sound3d_activate(&s->Base.Sound, 1);\n}",
       "    sound3d_activate(&s->Base.Sound, 0);\n}"),
    _m("pd-stop", "    bsample_stop(&s->WindSample);\n    if", "    if"),
    _m("pd-tc-dtor", "        topology_destroy(s->ReverbTopologyCoordinate);\n",
       ""),
    _m("pd-tc-free", "        bFree(s->ReverbTopologyCoordinate);\n", ""),
    _m("pd-wind", "    bsample_destruct(&s->WindSample);\n", ""),
    _m("pd-flags", "    basecarsound_destroy(&s->Base, flags);\n}\n\n// 0x0018dbf0.",
       "    basecarsound_destroy(&s->Base, 0);\n}\n\n// 0x0018dbf0."),
    _m("pu-vol", "    basecarsound_update(b, volume, azimuth, pitch);",
       "    basecarsound_update(b, volume * 1.5f, azimuth, pitch);"),
    _m("pu-az", "    b->Sound.Azimuth = s->PlayerAzimuth;\n", ""),
    _m("pu-engine-pov", "engine = b->Sound.Volume * carsound_get_pov_volume(b->pCar, 0);",
       "engine = b->Sound.Volume * carsound_get_pov_volume(b->pCar, 2);"),
    _m("pu-tire-pov", "tires = b->Sound.Volume * carsound_get_pov_volume(b->pCar, 1);",
       "tires = b->Sound.Volume * carsound_get_pov_volume(b->pCar, 2);"),
    _m("pu-engine", "s3d_update(b->EngineSound, engine, b->Sound.Azimuth,",
       "s3d_update(b->EngineSound, tires, b->Sound.Azimuth,"),
    _m("pu-tires", "s3d_update(b->TireSound[i], tires, b->Sound.Azimuth,",
       "s3d_update(b->TireSound[i], engine, b->Sound.Azimuth,"),
    _m("pu-tires-n", "    for (i = 0; i < 2; i++)\n        if (b->TireSound[i] != NULL)\n"
       "            s3d_update(", "    for (i = 0; i < 1; i++)\n"
       "        if (b->TireSound[i] != NULL)\n            s3d_update("),
    _m("pu-refl", "    baseplayercarsound_update_engine_reflection(s, b->Sound.Volume,",
       "    baseplayercarsound_update_engine_reflection(s, volume,"),
    _m("pu-zone-sample", "if (p->pZoneSample != NULL && p->nZoneCurrent == 0)",
       "if (p->nZoneCurrent == 0)"),
    _m("pu-zone-current", "if (p->pZoneSample != NULL && p->nZoneCurrent == 0)",
       "if (p->pZoneSample != NULL)"),
    _m("pm-base", "    basecarsound_mute(&s->Base, on);\n", ""),
    _m("pm-wind", "    bsample_pause(&s->WindSample, on != 0);",
       "    bsample_pause(&s->WindSample, on == 0);"),
    _m("pm-refl0", "get_engine_reflection_sample(s, 0),\n",
       "get_engine_reflection_sample(s, 1),\n"),
    _m("pm-refl1", "    bsample_pause(baseplayercarsound_get_engine_reflection_sample"
       "(s, 1),\n                  on != 0);",
       "    bsample_pause(baseplayercarsound_get_engine_reflection_sample"
       "(s, 1),\n                  on == 0);"),
    _m("pm-zone", "bsample_pause((BSample *)p->pZoneSample, on != 0);",
       "bsample_pause((BSample *)p->pZoneSample, on == 0);"),
    _m("ph-prefix", "    strcpy(name, info->Prefix);",
       "    strcpy(name, info->BaseName);"),
    _m("ph-horn", "strcat(name, \"Horn\");", "strcat(name, \"Horn1\");"),
    _m("ph-region", "bsound_region(bsound_get(), info->BaseName), name);",
       "bsound_region(bsound_get(), \"InGame\"), name);"),
    _m("rs-rand", "        i = sound_random_int(sound_get(), 2);",
       "        i = sound_random_int(sound_get(), 3);"),
    _m("rs-name", "    name[11] = (char)('1' + i);", "    name[11] = (char)('0' + i);"),
    _m("wv-pov", "carsound_get_pov_volume(s->Base.pCar, 2) * f) * 0.012f;",
       "carsound_get_pov_volume(s->Base.pCar, 1) * f) * 0.012f;"),
    _m("wv-k", "* f) * 0.012f;", "* f) * 0.013f;"),
    _m("wv-order", "(carsound_get_pov_volume(s->Base.pCar, 2) * f) * 0.012f;",
       "carsound_get_pov_volume(s->Base.pCar, 2) * (f * 0.012f);"),
    _m("wp-k", "return f * 0.008f;", "return f * 0.009f;"),

    # ---- the reflections
    _m("er-test", "    if (s->EngineReflectionLeft || s->EngineReflectionRight) {",
       "    if (s->EngineReflectionLeft) {"),
    _m("er-vol", "float vol = speed * 0.03f;", "float vol = speed * 0.031f;"),
    _m("er-pit", "float pit = speed * 0.015f;", "float pit = speed * 0.016f;"),
    _m("er-l-se", SE_RL, SE_RL.replace("SoundEnabled && ", "", 1)),
    _m("er-l-cse", SE_RL, SE_RL.replace(" && CarSoundEnabled", "", 1)),
    _m("er-l-az", "bsample_set_azimuth(smp, (uint16_t)-ReflectionAzimuth);",
       "bsample_set_azimuth(smp, ReflectionAzimuth);"),
    _m("er-r-az", "                bsample_set_azimuth(smp, ReflectionAzimuth);",
       "                bsample_set_azimuth(smp, (uint16_t)-ReflectionAzimuth);"),
    _m("er-l-vol", RL, RL.replace("vol * volume", "vol", 1)),
    _m("er-l-pitch", RL, RL.replace("pit - 1.0f", "pit", 1)),
    _m("er-r-vol", RR, RR.replace("vol * volume", "volume", 1)),
    _m("er-r-pitch", RR, RR.replace("pit - 1.0f", "pit", 1)),
    _m("er-l-clear", "            s->EngineReflectionLeft = 0;\n", ""),
    _m("er-r-clear", "            s->EngineReflectionRight = 0;\n", ""),
    _m("er-thresh", "VelocityMagnitude < 13.888889f)",
       "VelocityMagnitude < 13.89f)"),
    _m("er-thresh-le", "VelocityMagnitude < 13.888889f)",
       "VelocityMagnitude <= 13.888889f)"),
    _m("er-chk", "        s->CheckForReflected = 1;\n    else",
       "        s->CheckForReflected = 0;\n    else"),
    _m("er-dbr", "    else\n        baseplayercarsound_update_dynamic_body_"
       "reflections(s);", ""),
    _m("db-radius", "(DynamicCollisionBody *)body, 9.0f, &first, &last);",
       "(DynamicCollisionBody *)body, 8.0f, &first, &last);"),
    _m("db-first", "for (o = first->Link.next; o != last;",
       "for (o = first; o != last;"),
    _m("db-self", "        if (o == body)\n            continue;\n", ""),
    _m("db-plant", "body_terrain(o) == TERRAIN_TYPE_PLANT)",
       "body_terrain(o) != TERRAIN_TYPE_PLANT)"),
    _m("db-dist", "        if (9.0f < dist)", "        if (8.0f < dist)"),
    _m("db-dist-le", "        if (9.0f < dist)", "        if (9.0f <= dist)"),
    _m("db-dist-order", "dist = ee_sqrt((dx * dx + dy * dy) + dz * dz);",
       "dist = ee_sqrt(dx * dx + (dy * dy + dz * dz));"),
    _m("db-dz", "dz = p->z - q->z;", "dz = 0.0f;"),
    _m("db-w2c", "                         (const bVector2 *)body_position(o));",
       "                         (const bVector2 *)body_position(body));"),
    _m("db-relx", "rel.x = w->x - v->x;", "rel.x = w->x + v->x;"),
    _m("db-rely", "rel.y = w->y - v->y;", "rel.y = w->y;"),
    _m("db-speed", "if (!(13.888889f < ee_sqrt(", "if (!(13.89f < ee_sqrt("),
    _m("db-speed-le", "if (!(13.888889f < ee_sqrt(", "if (!(13.888889f <= ee_sqrt("),
    _m("db-a-dt", "(const bVector2 *)v,\n                   WorldTimeElapsed);",
       "(const bVector2 *)v,\n                   0.0f);"),
    _m("db-b-dt", "(const bVector2 *)w,\n                   WorldTimeElapsed);",
       "(const bVector2 *)w,\n                   0.0f);"),
    _m("db-d", "d.x = b.x - a.x;\n        d.y = b.y - a.y;",
       "d.x = a.x - b.x;\n        d.y = a.y - b.y;"),
    _m("db-dy", "        d.y = b.y - a.y;", "        d.y = 0.0f;"),
    _m("db-nv", "bNormalize2(&nv, (const bVector2 *)body_velocity(body));",
       "bNormalize2(&nv, (const bVector2 *)body_velocity(o));"),
    _m("db-e", "        e.x = q->x - p->x;\n        e.y = q->y - p->y;",
       "        e.x = p->x - q->x;\n        e.y = p->y - q->y;"),
    _m("db-dotE", "dotE = e.x * nv.x + e.y * nv.y;", "dotE = e.x * nv.x;"),
    _m("db-dotD", "dotD = d.x * nv.x + d.y * nv.y;", "dotD = d.y * nv.y;"),
    _m("db-cross1", "if ((dotE < 0.0f && 0.0f < dotD) || ", "if ("),
    _m("db-cross2", " || (0.0f < dotE && dotD < 0.0f)) {", ") {"),
    _m("db-side", "            if (local.x < 0.0f)", "            if (0.0f < local.x)"),
    _m("db-side-y", "            if (local.x < 0.0f)", "            if (local.y < 0.0f)"),

    # ---- BaseAICarSound
    _m("ai-vt", "    s->Base.Sound._vtable = BASEAICARSOUND_VTABLE;\n"
       "    s->Base.pSoundEnvelope", "    s->Base.Sound._vtable = "
       "BASECARSOUND_VTABLE;\n    s->Base.pSoundEnvelope"),
    _m("ai-env", "    s->Base.pSoundEnvelope = &BaseAICarSoundEnvelope;",
       "    s->Base.pSoundEnvelope = &BasePlayerCarSoundEnvelope;"),
    _m("ai-engine", "? gCreateAIEngineFn(c) : NULL;",
       "? gCreatePlayerEngineFn(c) : NULL;"),
    _m("ai-horn-tag", "\"HornSound3d\", 0, 16);\n"
       "    hs = basecarsound_get_horn_sample(&s->Base);",
       "\"HornSound\", 0, 16);\n    hs = basecarsound_get_horn_sample(&s->Base);"),
    _m("ai-tire", "gCreateAITireFn != NULL ? gCreateAITireFn(c)",
       "gCreateAITireFn != NULL ? gCreatePlayerTireFn(c, 0)"),
    _m("ad-flags", "    s->Base.Sound._vtable = BASEAICARSOUND_VTABLE;\n"
       "    basecarsound_destroy(&s->Base, flags);",
       "    s->Base.Sound._vtable = BASEAICARSOUND_VTABLE;\n"
       "    basecarsound_destroy(&s->Base, 0);"),
    _m("au-act", "    if (!b->Sound.Activated) {", "    if (b->Sound.Activated) {"),
    _m("au-camrel-pos", "(vt_this(b, e), &b->pCar->State.Position);",
       "(vt_this(b, e), NULL);"),
    _m("au-ret", "(vt_this(b, e), &b->pCar->State.Position);\n        return;",
       "(vt_this(b, e), &b->pCar->State.Position);"),
    _m("au-vol", "basecarsound_update(b, volume * 1.5f, azimuth, pitch);",
       "basecarsound_update(b, volume * 1.25f, azimuth, pitch);"),
    _m("au-engine", "        s3d_update(b->EngineSound, b->Sound.Volume, "
       "b->Sound.Azimuth,", "        s3d_update(b->EngineSound, volume, "
       "b->Sound.Azimuth,"),
    _m("au-tire", "        s3d_update(b->TireSound[0], b->Sound.Volume, "
       "b->Sound.Azimuth,", "        s3d_update(b->TireSound[0], volume, "
       "b->Sound.Azimuth,"),

    # ---- HornSound3d
    _m("hc-vt", "    h->Sound._vtable = HORNSOUND3D_VTABLE;\n    bsample_construct",
       "    h->Sound._vtable = SIRENSOUND3D_VTABLE;\n    bsample_construct"),
    _m("hc-null", "    if (sample != NULL)\n", "    if (sample == NULL)\n"),
    _m("hc-cat", "    bsample_set_category(&h->HornSample, 0);",
       "    bsample_set_category(&h->HornSample, 1);"),
    _m("hc-detune", "    h->DetunePitch = 1.0f;", "    h->DetunePitch = 1.5f;"),
    _m("hd-sample", "    bsample_destruct(&h->HornSample);\n", ""),
    _m("hd-flags", "    sound3d_destroy(&h->Sound, flags);",
       "    sound3d_destroy(&h->Sound, 0);"),
    _m("ha-se", "    if (SoundEnabled)\n        bsample_play(&h->HornSample,",
       "    if (1)\n        bsample_play(&h->HornSample,"),
    _m("ha-args", "bsample_play(&h->HornSample, 0.0f, 0.0f, 0.0f);",
       "bsample_play(&h->HornSample, 1.0f, 0.0f, 0.0f);"),
    _m("hda", "    bsample_stop(&h->HornSample);",
       "    bsample_pause(&h->HornSample, 1);"),
    _m("hch-name", "name[5] = (char)('1' + (uint8_t)HornCounter);",
       "name[5] = (char)('0' + (uint8_t)HornCounter);"),
    _m("hch-mod", "HornCounter = (HornCounter + 1) % 3;",
       "HornCounter = (HornCounter + 1) % 4;"),
    _m("hm", "    bsample_pause(&h->HornSample, on != 0);",
       "    bsample_pause(&h->HornSample, on == 0);"),
    _m("hu-act", "    if (!h->Sound.Activated)\n        return;",
       "    if (0)\n        return;"),
    _m("hu-vol", "    bsample_set_volume(&h->HornSample, volume);",
       "    bsample_set_volume(&h->HornSample, volume * 0.5f);"),
    _m("hu-az", "    bsample_set_azimuth(&h->HornSample, azimuth);",
       "    bsample_set_azimuth(&h->HornSample, 0);"),
    _m("hu-pitch", "h->DetunePitch * pitch - 1.0f);", "h->DetunePitch * pitch);"),
    _m("hu-detune", "h->DetunePitch * pitch - 1.0f);", "pitch - 1.0f);"),

    # ---- SirenSound3d
    _m("sc-vt", "    s->Sound._vtable = SIRENSOUND3D_VTABLE;\n    for (i = 0; i < 3",
       "    s->Sound._vtable = HORNSOUND3D_VTABLE;\n    for (i = 0; i < 3"),
    _m("sc-n", "    for (i = 0; i < 3; i++)\n        bsample_construct(",
       "    for (i = 0; i < 2; i++)\n        bsample_construct("),
    _m("sc-switch", "    s->SwitchSirenTime = 17.0f;\n    for (i = 0; i < 3; i++) {",
       "    s->SwitchSirenTime = 16.0f;\n    for (i = 0; i < 3; i++) {"),
    _m("sc-name", "        name[9] = (char)('1' + i);",
       "        name[9] = (char)('0' + i);"),
    _m("sc-region", "r = bsound_region(bsound_get(), \"InGame\");",
       "r = bsound_region(bsound_get(), \"Car0\");"),
    _m("sc-cat", "        bsample_set_category(&s->SirenSampleTable[i], 0);",
       "        bsample_set_category(&s->SirenSampleTable[i], 1);"),
    _m("sc-counter", "    SirenCounter = (SirenCounter + 1) % 3;",
       "    SirenCounter = (SirenCounter + 1) % 4;"),
    _m("sc-counter-order", "    SirenCounter = (SirenCounter + 1) % 3;\n"
       "    s->CurrentSiren = SirenCounter;",
       "    s->CurrentSiren = SirenCounter;\n"
       "    SirenCounter = (SirenCounter + 1) % 3;"),
    _m("sc-curr", "    s->CurrBrokenSirenPitch = 1.0f;",
       "    s->CurrBrokenSirenPitch = 0.5f;"),
    _m("sc-broken", "    s->IsSirenBroken = 0;", "    s->IsSirenBroken = 1;"),
    _m("sc-target", "    s->BrokenSirenPitchTarget = 1.0f;",
       "    s->BrokenSirenPitchTarget = 0.5f;"),
    _m("sd-order", "for (i = 2; i >= 0; i--)", "for (i = 0; i < 3; i++)"),
    _m("sd-n", "for (i = 2; i >= 0; i--)", "for (i = 2; i >= 1; i--)"),
    _m("sd-flags", "    sound3d_destroy(&s->Sound, flags);\n}\n\n"
       "void sirensound3d_update_mode",
       "    sound3d_destroy(&s->Sound, 0);\n}\n\nvoid sirensound3d_update_mode"),
    _m("um-off", "    if (mode == SIREN_MODE_NONE && s->Sound.Activated)\n",
       "    if (0)\n"),
    _m("um-on", "    if (mode != SIREN_MODE_NONE && !s->Sound.Activated)\n",
       "    if (0)\n"),
    _m("um-broken", "s->IsSirenBroken = mode == SIREN_MODE_BROKEN;",
       "s->IsSirenBroken = mode != SIREN_MODE_NONE;"),
    _m("um-act", "    if (s->Sound.Activated)\n        s->IsSirenBroken",
       "    if (1)\n        s->IsSirenBroken"),
    _m("sa-se", "    if (SoundEnabled)\n        bsample_play(&s->SirenSampleTable",
       "    if (1)\n        bsample_play(&s->SirenSampleTable"),
    _m("sa-args", "bsample_play(&s->SirenSampleTable[s->CurrentSiren], 0.0f, 0.0f,",
       "bsample_play(&s->SirenSampleTable[s->CurrentSiren], 1.0f, 0.0f,"),
    _m("sda", "    bsample_stop(&s->SirenSampleTable[s->CurrentSiren]);\n}",
       "    bsample_stop(&s->SirenSampleTable[0]);\n}"),
    _m("sb", "    s->IsSirenBroken = on;", "    s->IsSirenBroken = !on;"),
    _m("sm", "    bsample_pause(&s->SirenSampleTable[s->CurrentSiren], on != 0);",
       "    bsample_pause(&s->SirenSampleTable[s->CurrentSiren], on == 0);"),
    _m("su-vol0", "    if (volume == 0.0f)\n", "    if (volume < 0.0f)\n"),
    _m("su-act", "    if (!s->Sound.Activated)\n        return;\n"
       "    s->SwitchSirenTime", "    if (0)\n        return;\n"
       "    s->SwitchSirenTime"),
    _m("su-dt", "    s->SwitchSirenTime -= WorldTimeElapsed;",
       "    s->SwitchSirenTime -= 2.0f * WorldTimeElapsed;"),
    _m("su-switch-le", "    if (s->SwitchSirenTime < 0.0f) {",
       "    if (s->SwitchSirenTime <= 0.0f) {"),
    _m("su-switch-stop", "    if (s->SwitchSirenTime < 0.0f) {\n"
       "        bsample_stop(&s->SirenSampleTable[s->CurrentSiren]);\n",
       "    if (s->SwitchSirenTime < 0.0f) {\n"),
    _m("su-switch-17", "        s->SwitchSirenTime = 17.0f;\n"
       "        s->CurrentSiren", "        s->SwitchSirenTime = 16.0f;\n"
       "        s->CurrentSiren"),
    _m("su-next", "s->CurrentSiren = (s->CurrentSiren + 1) % 3;",
       "s->CurrentSiren = (s->CurrentSiren + 1) % 2;"),
    _m("su-playing", "    if (bsample_is_playing(smp)) {",
       "    if (!bsample_is_playing(smp)) {"),
    _m("su-setvol", "        bsample_set_volume(smp, volume);",
       "        bsample_set_volume(smp, volume * 0.5f);"),
    _m("su-17b", "    } else {\n        s->SwitchSirenTime = 17.0f;",
       "    } else {\n        s->SwitchSirenTime = 16.0f;"),
    _m("su-play-se", "        if (SoundEnabled)\n            bsample_play(smp,",
       "        if (1)\n            bsample_play(smp,"),
    _m("su-play-vol", "bsample_play(smp, volume, 0.0f, 0.0f);",
       "bsample_play(smp, 0.0f, 0.0f, 0.0f);"),
    _m("su-broken", "    if (s->IsSirenBroken)\n        pitch *=",
       "    if (0)\n        pitch *="),
    _m("su-pitch", "SirenSampleTable[s->CurrentSiren], pitch - 1.0f);",
       "SirenSampleTable[s->CurrentSiren], pitch);"),
    _m("su-az", "SirenSampleTable[s->CurrentSiren], azimuth);",
       "SirenSampleTable[s->CurrentSiren], 0);"),
    _m("bp-eq", "    if (s->BrokenSirenPitchTarget == s->CurrBrokenSirenPitch)",
       "    if (s->BrokenSirenPitchTarget != s->CurrBrokenSirenPitch)"),
    _m("bp-range", "sound_random_float(sound_get(), 0.9f) + 0.1f;",
       "sound_random_float(sound_get(), 0.8f) + 0.1f;"),
    _m("bp-base", "sound_random_float(sound_get(), 0.9f) + 0.1f;",
       "sound_random_float(sound_get(), 0.9f) + 0.2f;"),
    _m("bp-step", "s->BrokenSirenPitchTarget, 0.03f);",
       "s->BrokenSirenPitchTarget, 0.04f);"),
    _m("bp-args", "smooth(s->CurrBrokenSirenPitch,\n"
       "                                     s->BrokenSirenPitchTarget, 0.03f);",
       "smooth(s->BrokenSirenPitchTarget,\n"
       "                                     s->CurrBrokenSirenPitch, 0.03f);"),

    # ---- the tables
    _m("vt-b-dtor", "E(basecarsound_destroy),         ",
       "E(baseaicarsound_destroy),       "),
    _m("vt-b-act", "E(sound3d_activate),                                "
       "// 16  0x00208b28", "E(sound3d_destroy), // 16  0x00208b28"),
    _m("vt-b-upd", "E(basecarsound_update),          ",
       "E(baseaicarsound_update),        "),
    _m("vt-b-mute", "E(basecarsound_mute),                               "
       "// 32  0x0018d550", "E(baseplayercarsound_mute), // 32  0x0018d550"),
    _m("vt-b-deact", "E(basecarsound_deactivate_sound),                   "
       "// 40  0x0018d830", "E(basecarsound_activate_sound), // 40"),
    _m("vt-b-actsnd", "E(basecarsound_activate_sound),                     "
       "// 48  0x0018d8d8", "E(basecarsound_deactivate_sound), // 48"),
    _m("vt-b-camrel", "E(sound3d_update_cam_relative_dist_and_velocity),   "
       "// 56  0x00208c78", "E(basecarsound_update), // 56"),
    _m("vt-b-horn", "E(basecarsound_get_horn_sample),                    "
       "// 64  0x0018d480", "E(baseplayercarsound_get_horn_sample), // 64"),
    _m("vt-p-dtor", "E(baseplayercarsound_destroy),", "E(basecarsound_destroy),"),
    _m("vt-p-upd", "E(baseplayercarsound_update),", "E(basecarsound_update),"),
    _m("vt-p-mute", "E(baseplayercarsound_mute),", "E(basecarsound_mute),"),
    _m("vt-p-horn", "E(baseplayercarsound_get_horn_sample),     ",
       "E(basecarsound_get_horn_sample),           "),
    _m("vt-a-dtor", "E(baseaicarsound_destroy),", "E(basecarsound_destroy),"),
    _m("vt-a-upd", "E(baseaicarsound_update),", "E(basecarsound_update),"),
    _m("vt-a-horn", "    E(basecarsound_get_horn_sample),                    "
       "// 64\n};\n\nstatic const VtEntry hornsound3d_vt",
       "    E(baseplayercarsound_get_horn_sample), // 64\n};\n\n"
       "static const VtEntry hornsound3d_vt"),
    _m("vt-h-dtor", "E(hornsound3d_destroy),", "E(sirensound3d_destroy),"),
    _m("vt-h-upd", "E(hornsound3d_update),", "E(sirensound3d_update),"),
    _m("vt-h-mute", "E(hornsound3d_mute),", "E(sirensound3d_mute),"),
    _m("vt-h-deact", "E(hornsound3d_deactivate_sound),",
       "E(hornsound3d_activate_sound),"),
    _m("vt-h-act", "E(hornsound3d_activate_sound),   ",
       "E(hornsound3d_deactivate_sound), "),
    _m("vt-s-dtor", "E(sirensound3d_destroy),", "E(hornsound3d_destroy),"),
    _m("vt-s-upd", "E(sirensound3d_update),", "E(hornsound3d_update),"),
    _m("vt-s-mute", "E(sirensound3d_mute),", "E(hornsound3d_mute),"),
    _m("vt-s-deact", "E(sirensound3d_deactivate_sound),",
       "E(sirensound3d_activate_sound),"),
    _m("vt-s-act", "E(sirensound3d_activate_sound),   ",
       "E(sirensound3d_deactivate_sound), "),
    _m("vt-s-camrel", "    E(sound3d_update_cam_relative_dist_and_velocity),   "
       "// 56\n};\n\n#undef E", "    E(sound3d_activate), // 56\n};\n\n#undef E"),
    _m("vt-install-ai", "vt_install(BASEAICARSOUND_VTABLE, baseaicarsound_vt, "
       "CARSOUND_VT_ENTRIES);", "vt_install(BASEAICARSOUND_VTABLE, "
       "baseaicarsound_vt, CARSOUND_VT_ENTRIES - 1);"),
]

EQUIVALENT = {}


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
    tally = mutpar.run_pass(
        todo, SOURCES, "carsound_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs)
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

    lines = script()
    got, e = model(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = write_script(tmp, lines)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(got) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(got, harness)
    print("%d ops, %d lines, %d differ" % (len(lines), len(harness), n))
    for label, pcs in (("eediv", e.eediv_pcs), ("eemul", e.eemul_pcs),
                       ("eesqrt", e.eesqrt_pcs)):
        if pcs:
            print("%s at %s" % (label, " ".join("%08x" % p
                                                for p in sorted(pcs))))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
