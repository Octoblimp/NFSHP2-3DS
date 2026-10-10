#!/usr/bin/env python3
"""Cross-check 3DS Files/source/collisionsound.c against the retail image,
SLES_507.31.

**The model** is retail's own CollisionSounds.obj run in
retail_model.RetailEmu with the EE's divide, product and root (eediv,
eemul, eesqrt): CollisionSounds' GetCollisionSoundType, Register,
LoadSampleTable, UnRegister, GetDistanceToCamera, the three Calc
functions, StartScraping, UpdateSample, Update and Mute; collision_sound's
four jumps, Reset, CreateSample, ReleaseSample, PlayFoilage,
PlayGenericSmokable, PlaySmokeable, PlayGlass, PlayBustRoadBlock,
PlayExplosion and PlayScrape; CollisionSample's Initialize and destructor
(every delete is through its table); and the static constructor that
points FreeSampleList at itself. bStrCat, bStrLen, bStringHash, memset and
bNode's destructor run in the image too. The harness
(tools/src/collisionsound_test.c) runs collisionsound.c's, through the
port's table.

**The fakes**, the same on both sides, each printing what it is handed:
bSample's constructor, destructor, Initialize, SetCategory (kept, as
retail's is), Play, Stop, Pause, SetAzimuth, SetVolume, SetPitch,
IsPlaying (playing from Play to Stop, or as the script says), GetVolume
(the script's, 1 by default) and Fade; bSound's GetCategoryVolume;
GetInGameSample (a sample a name, none for those the script names); the
sound's random float and IsSoundRegionLoadingComplete; Sound3d's
ComputeVolume and ComputeAzimuth (the script's queues); sound3d_oneshot's
Play on a sample and on a name (a fresh one-shot each, or none); the slot
pool's bNewSlotPool (its slot size checked), bOMalloc (a fresh 0xa5 slot
each), bFree and bDeleteSlotPool; eGetView (the script's cameras); and
Collision's GetTerrainType (the script's).

**The script** dumps the table and the image's globals; registers with
and without the pool and the hashes; updates without a world, before the
regions are in and once they are, with samples missing; asks for the
sound type on each terrain and through each impulse bound; measures the
distance to one camera and the nearer of two, either nearer, with each
count of players; takes the volume and scrape volume at and past 35 and
each cap; starts scrapes young and old, back in time, on each terrain,
with sound off and a sample missing; updates scrapes; creates samples
young, quiet, at the 0.2 bound, with sound off and a type missing;
releases samples and scrapes playing and not; runs Update's free list
through each of its tests and its collisions with and without samples;
mutes and unmutes with the libraries playing or missing; resets,
unregisters twice and registers again; and plays each one-shot with sound
on and off, each smokeable kind, each pump and a missing one-shot, and
dumps the envelopes.

    python tools/collisionsound_check.py
    python tools/collisionsound_check.py --mutate [--only a,b]
    python tools/collisionsound_check.py --dump out/collisionsound
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

HARNESS = "tools/src/collisionsound_test.c"
CSC = "3DS Files/source/collisionsound.c"
SOURCES = [HARNESS, CSC, "3DS Files/source/vtable.c"]
HARNESS_TIMEOUT = 30
LIMIT = 400000

GP = retail_model.RETAIL_GP
F = {
    "type": 0x001e4658, "reg": 0x001e4740, "load": 0x001e47a8,
    "unreg": 0x001e4a78, "dist": 0x001e4b58, "vol": 0x001e4c28,
    "svol": 0x001e4b08, "azc": 0x001e4cc0, "start": 0x001e4cc8,
    "usample": 0x001e4e00, "update": 0x001e4ea8, "mute": 0x001e5018,
    "csreg": 0x001e51a8, "csunreg": 0x001e51b0, "csupdate": 0x001e51b8,
    "csmute": 0x001e51c0, "reset": 0x001e51c8, "create": 0x001e5278,
    "release": 0x001e53b0, "foil": 0x001e5470, "generic": 0x001e5508,
    "smoke": 0x001e55a8, "glass": 0x001e5660, "bust": 0x001e5688,
    "boom": 0x001e56f0, "scrape": 0x001e57d0, "sinit": 0x001e5d98,
}
STRHASH = 0x002534a8

VT = 0x002b9410
VT_ENTRIES = 2
FNAME = {0x001e5db0: "dtor", 0x002a0550: "pure"}

SE, WORLD, WT, BSOUND = GP - 23056, GP - 22120, GP - 19576, GP - 13696
LOADED, MS, WS, GB = GP - 17236, GP - 17240, GP - 17244, GP - 17248
TABLE, GAS, PETROL = GP - 17264, GP - 17268, GP - 17272
FREE, POOL = GP - 17280, GP - 17288
NPC = 0x0031a8c8
LIBS = (("small", 0x0031a798), ("medium", 0x0031a7a8),
        ("hard", 0x0031a7b8), ("wood", 0x0031a788), ("foil", 0x0031a778))

# Retail's records.
SAMPLE_SIZE = 196
NODE = 188
SAMPLE_VT = 184
CATEGORY = 132
COLL_SIZE = 112
C_TIME, C_ICP, C_CCP, C_SPEED = 8, 16, 32, 48
C_TIM, C_SAMPLE, C_SCRAPE = 80, 88, 92
WORLD_LIST = 16
VIEW_CAMERA, CAM_POS = 56, 64
SHOT_SIZE, SHOT_SAMPLE, SHOT_ENV = 272, 40, 228
SMK_SIZE, SMK_HASH, SMK_TERRAIN = 208, 112, 192


def fbits(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


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
        self.slots, self.pools, self.shots = [], [], []
        self.srcs = {}                  # name -> sample
        self.nosrc = set()
        self.playing = set()
        self.vols = {}
        self.rf, self.cvq, self.azq = [], [], []
        self.rlc = 0
        self.catvol = 0
        self.noshot = 0
        self.colls, self.terrain, self.smks = {}, {}, {}
        self.bsound = e.alloc(16)
        self.world = e.alloc(64, 16)
        lst = self.world + WORLD_LIST
        e.put32(lst, lst)
        e.put32(lst + 4, lst)
        self.cams, self.views = [], []
        for i in range(3):
            c = e.alloc(448, 16)
            e.mem[c:c + 448] = b"\0" * 448
            v = e.alloc(128, 16)
            e.put32(v + VIEW_CAMERA, c)
            self.cams.append(c)
            self.views.append(v)
        self.pos = e.alloc(16, 16)
        e.mem[self.pos:self.pos + 16] = b"\0" * 16
        self.scratch = e.alloc(64, 16)
        e.put32(BSOUND, self.bsound)
        e.put32(SE, 1)
        e.put32(WORLD, 0)
        e.put32(WT, 0)
        e.put32(NPC, 1)

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
        e.stub(0x00273f58, self.b_getvol)
        e.stub(0x00274868, self.b_fade)
        e.stub(0x00277dc0, self.catvolume)
        e.stub(0x001ae280, self.ingame)
        e.stub(0x001af9c0, self.randf)
        e.stub(0x001af2e8, self.region_done)
        e.stub(0x00208df8, self.caz)
        e.stub(0x00208f70, self.cvol)
        e.stub(0x002093d8, self.oneshot)
        e.stub(0x00209388, self.oneshotn)
        e.stub(0x00257c10, self.newpool)
        e.stub(0x00257c48, self.delpool)
        e.stub(0x00257c80, self.omalloc)
        e.stub(0x00257ca0, self.pfree)
        e.stub(0x00107c90, self.eview)
        e.stub(0x0021ea88, self.terrain_of)
        e.stub(0x002577c0, self.unexpected("malloc"))
        e.stub(0x00114e98, self.unexpected("delete"))
        e.stub(0x00257850, self.unexpected("bfree"))

        # The static constructor: FreeSampleList at itself.
        self.call("sinit")

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
        if a == self.pos:
            return "pos"
        for i, p in enumerate(self.slots):
            if a == p:
                return "c%d" % i
        for nm, p in self.srcs.items():
            if a == p:
                return "src:" + nm
        for k in sorted(self.colls):
            c = self.colls[k]
            if a == c:
                return "k%d" % k
            if a == c + C_ICP:
                return "k%d.icp" % k
            if a == c + C_CCP:
                return "k%d.ccp" % k
        for i, p in enumerate(self.shots):
            if a == p:
                return "o%d" % i
            if a == p + SHOT_SAMPLE:
                return "o%d.s" % i
        for i, p in enumerate(self.pools):
            if a == p:
                return "pool%d" % i
        return "?"

    def sample_ref(self, w):
        if w[0] == "k":
            k, _, which = w[1:].partition(".")
            c = self.colls[int(k)]
            s = self.e.u32(c + (C_SAMPLE if which[1:2] == "a" else C_SCRAPE))
            if s:
                return s
        elif w[0] == "c" and w[1:].isdigit():
            i = int(w[1:])
            if i < len(self.slots):
                return self.slots[i]
        elif w.startswith("src:"):
            if w[4:] in self.srcs:
                return self.srcs[w[4:]]
        elif w[0] == "o":
            i = int(w[1:])
            if i < len(self.shots):
                return self.shots[i] + SHOT_SAMPLE
        self.emit("  no sample %s" % w)
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

    # ---- bSound and the sound module

    def catvolume(self, em):
        self.emit("  catvol %s %d -> %08x" % (self.name(em.reg[4]),
                                              em.reg[5] & M32, self.catvol))
        em.fpr[0] = self.catvol
        return 0

    def ingame(self, em):
        nm = self.cstr(em.reg[4] & M32)
        self.emit("  ingame %s" % nm)
        if nm in self.nosrc:
            return 0
        if nm not in self.srcs:
            self.srcs[nm] = self.e.alloc(188, 16)
        return self.srcs[nm]

    def randf(self, em):
        v = self.rf.pop(0) if self.rf else 0
        self.emit("  randf %08x -> %08x" % (em.fpr[12], v))
        em.fpr[0] = v
        return 0

    def region_done(self, em):
        self.emit("  rlc -> %d" % self.rlc)
        return self.rlc

    # ---- Sound3d

    def caz(self, em):
        v = (self.azq.pop(0) if self.azq else 0) & 0xffff
        self.emit("  caz %s -> %d" % (self.name(em.reg[4]), v))
        return v

    def cvol(self, em):
        v = self.cvq.pop(0) if self.cvq else 0
        self.emit("  cvol %s %08x -> %08x" % (self.name(em.reg[4]),
                                              em.fpr[12], v))
        em.fpr[0] = v
        return 0

    def new_shot(self):
        if self.noshot:
            return 0
        e = self.e
        s = e.alloc(SHOT_SIZE, 16)
        e.mem[s:s + SHOT_SIZE] = b"\xa5" * SHOT_SIZE
        for k in range(3):
            e.put32(s + SHOT_ENV + 4 * k, 0)
        e.put32(s + SHOT_SAMPLE + CATEGORY, 7)
        self.shots.append(s)
        return s

    def oneshot(self, em):
        smp, pos = em.reg[4] & M32, em.reg[5] & M32
        vol, pitch = em.fpr[12], em.fpr[13]
        s = self.new_shot()
        self.emit("  oneshot %s %s %08x %08x -> %s" % (
            self.name(smp), self.name(pos), vol, pitch, self.name(s)))
        return s

    def oneshotn(self, em):
        nm = self.cstr(em.reg[4] & M32)
        pos = em.reg[5] & M32
        vol, pitch = em.fpr[12], em.fpr[13]
        s = self.new_shot()
        self.emit("  oneshotn %s %s %08x %08x -> %s" % (
            nm, self.name(pos), vol, pitch, self.name(s)))
        return s

    # ---- the pool

    def newpool(self, em):
        p = self.e.alloc(16)
        self.pools.append(p)
        self.emit("  newpool %s %d %d size-%s -> %s" % (
            self.cstr(em.reg[6] & M32), s32(em.reg[5]), s32(em.reg[7]),
            "ok" if s32(em.reg[4]) == SAMPLE_SIZE else "BAD", self.name(p)))
        return p

    def delpool(self, em):
        self.emit("  delpool %s" % self.name(em.reg[4]))
        return 0

    def omalloc(self, em):
        e = self.e
        p = e.alloc(SAMPLE_SIZE, 16)
        e.mem[p:p + SAMPLE_SIZE] = b"\xa5" * SAMPLE_SIZE
        self.slots.append(p)
        self.emit("  omalloc %s -> %s" % (self.name(em.reg[4]),
                                          self.name(p)))
        return p

    def pfree(self, em):
        self.emit("  pfree %s %s" % (self.name(em.reg[4]),
                                     self.name(em.reg[5])))
        return 0

    # ---- the rest it calls

    def eview(self, em):
        i = s32(em.reg[4])
        self.emit("  view %d" % i)
        return self.views[i]

    def terrain_of(self, em):
        c = em.reg[4] & M32
        for k in sorted(self.colls):
            if self.colls[k] == c:
                self.emit("  terrain %s -> %d" % (self.name(c),
                                                  self.terrain[k]))
                return self.terrain[k]
        self.emit("  terrain %s -> ?" % self.name(c))
        return 0

    # ---- the dumps

    def dump_globals(self):
        e = self.e
        self.emit("  gd loaded=%d table=%d pool=%s petrol=%08x gas=%08x"
                  " ms=%s ws=%s gb=%s" % (
                      s32(e.u32(LOADED)), s32(e.u32(TABLE)),
                      self.name(e.u32(POOL)), e.u32(PETROL), e.u32(GAS),
                      self.name(e.u32(MS)), self.name(e.u32(WS)),
                      self.name(e.u32(GB))))
        for nm, a in LIBS:
            self.emit("  lib %s %s %s %s %d" % (
                nm, self.name(e.u32(a)), self.name(e.u32(a + 4)),
                self.name(e.u32(a + 8)), s32(e.u32(a + 12))))

    def node_name(self, n):
        if n == FREE & M32:
            return "head"
        return self.name(n - NODE)

    def dump_free(self):
        e = self.e
        head = FREE & M32
        fwd, back = [], []
        n = e.u32(head)
        while n != head and len(fwd) < 64:
            fwd.append(self.node_name(n))
            n = e.u32(n)
        n = e.u32(head + 4)
        while n != head and len(back) < 64:
            back.append(self.node_name(n))
            n = e.u32(n + 4)
        self.emit("  fl" + "".join(" " + x for x in fwd) + " |"
                  + "".join(" " + x for x in back))

    def dump_coll(self, k):
        c = self.colls[k]
        self.emit("  cd %s sample=%s scrape=%s" % (
            self.name(c), self.name(self.e.u32(c + C_SAMPLE)),
            self.name(self.e.u32(c + C_SCRAPE))))

    def dump_sample(self, w):
        s = self.sample_ref(w)
        if s:
            self.emit("  sd %s vt=%08x" % (self.name(s),
                                           self.e.u32(s + SAMPLE_VT)))

    def dump_shots(self):
        e = self.e
        for i, s in enumerate(self.shots):
            self.emit("  od o%d max=%08x cut=%08x coeff=%08x cat=%d" % (
                i, e.u32(s + SHOT_ENV), e.u32(s + SHOT_ENV + 4),
                e.u32(s + SHOT_ENV + 8),
                e.u32(s + SHOT_SAMPLE + CATEGORY)))

    def dump_tables(self):
        e = self.e
        self.emit("  vt %d entries" % VT_ENTRIES)
        for k in range(1, VT_ENTRIES):
            d = s16(e.u16(VT + 8 * k))
            fn = e.u32(VT + 8 * k + 4)
            self.emit("  vt %d %d %s" % (8 * k, d, FNAME.get(fn, "?")))

    # ---- the collisions

    def new_coll(self, k):
        e = self.e
        c = self.colls[k] = e.alloc(COLL_SIZE, 16)
        e.mem[c:c + COLL_SIZE] = b"\xa5" * COLL_SIZE
        e.put32(c + C_TIME, 0)
        e.mem[c + C_ICP:c + C_ICP + 16] = b"\0" * 16
        e.mem[c + C_CCP:c + C_CCP + 16] = b"\0" * 16
        e.put32(c + C_SPEED, 0)
        e.put32(c + C_TIM, 0)
        e.put32(c + C_SAMPLE, 0)
        e.put32(c + C_SCRAPE, 0)
        self.terrain[k] = 0
        lst = self.world + WORLD_LIST
        tail = e.u32(lst + 4)
        e.put32(c, lst)
        e.put32(c + 4, tail)
        if tail == lst:
            e.put32(lst, c)
        else:
            e.put32(tail, c)
        e.put32(lst + 4, c)

    def unlink_coll(self, k):
        e = self.e
        c = self.colls[k]
        nxt, prev = e.u32(c), e.u32(c + 4)
        e.put32(prev, nxt)
        e.put32(nxt + 4, prev)

    def set_vec(self, a, f):
        for j in range(3):
            self.e.put32(a + 4 * j, int(f[j], 16) & M32)

    # ---- the ops

    def call(self, name, *args):
        return self.e.call(F[name], *args, limit=LIMIT)

    def op(self, f):
        e = self.e

        def i(k):
            return int(f[k], 0) if k < len(f) else 0

        def fb(k):
            return int(f[k], 16) & M32 if k < len(f) else 0

        def coll(k):
            return self.colls[i(k)]

        o = f[0]
        if o == "tables":
            self.dump_tables()
        elif o == "se":
            e.put32(SE, i(1))
        elif o == "wt":
            e.put32(WT, i(1) & M32)
        elif o == "npc":
            e.put32(NPC, i(1))
        elif o == "world":
            e.put32(WORLD, self.world if i(1) else 0)
        elif o == "cam":
            self.set_vec(self.cams[i(1)] + CAM_POS, f[2:5])
        elif o == "coll":
            self.new_coll(i(1))
        elif o == "unlink":
            self.unlink_coll(i(1))
        elif o == "cset":
            c = coll(1)
            e.put32(c + C_TIME, i(2) & M32)
            e.put32(c + C_TIM, fb(3))
            e.put32(c + C_SPEED, fb(4))
            self.terrain[i(1)] = i(5)
        elif o == "cpos":
            c = coll(1)
            self.set_vec(c + (C_ICP if f[2][0] == "i" else C_CCP), f[3:6])
        elif o == "csample":
            e.put32(coll(1) + C_SAMPLE,
                    0 if f[2] == "0" else self.sample_ref(f[2]))
        elif o == "cscrape":
            e.put32(coll(1) + C_SCRAPE,
                    0 if f[2] == "0" else self.sample_ref(f[2]))
        elif o == "hash":
            e.put32(PETROL, fb(1))
            e.put32(GAS, fb(2))
        elif o == "tbl":
            e.put32(TABLE, i(1))
        elif o == "rf":
            self.rf.append(fb(1))
        elif o == "cv":
            self.cvq.append(fb(1))
        elif o == "az":
            self.azq.append(i(1))
        elif o == "rlc":
            self.rlc = i(1)
        elif o == "catvol":
            self.catvol = fb(1)
        elif o == "noshot":
            self.noshot = i(1)
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
        elif o == "smk":
            s = self.smks[i(1)] = e.alloc(SMK_SIZE, 16)
            e.mem[s:s + SMK_SIZE] = b"\xa5" * SMK_SIZE
            e.write(self.scratch, f[2].encode() + b"\0")
            e.put32(s + SMK_HASH, e.call(STRHASH, self.scratch,
                                         limit=LIMIT) & M32)
            e.put32(s + SMK_TERRAIN, i(3))
        elif o == "type":
            self.emit("  -> %s" % self.name(self.call("type", coll(1))))
        elif o in ("reg", "load", "unreg", "update", "csreg", "csunreg",
                   "csupdate", "reset"):
            self.call(o)
        elif o == "dist":
            self.set_vec(self.pos, f[1:4])
            self.call("dist", self.pos)
            self.emit("  = %08x" % e.fpr[0])
        elif o in ("vol", "svol"):
            self.call(o, coll(1))
            self.emit("  = %08x" % e.fpr[0])
        elif o == "azc":
            self.emit("  = %d" % self.call("azc", coll(1)))
        elif o == "screate":
            c = coll(1)
            e.put32(c + C_SAMPLE, self.call("create", c))
            self.emit("  -> %s" % self.name(e.u32(c + C_SAMPLE)))
        elif o in ("start", "usample", "release", "scrape"):
            self.call(o, coll(1))
        elif o in ("mute", "csmute"):
            self.call(o, i(1))
        elif o == "create":
            self.emit("  -> %s" % self.name(self.call("create", coll(1))))
        elif o in ("foil", "generic", "glass", "bust", "boom"):
            self.call(o, coll(1) + C_ICP)
        elif o == "smoke":
            self.call("smoke", coll(1) + C_ICP,
                      0 if i(2) < 0 else self.smks[i(2)])
        elif o == "gd":
            self.dump_globals()
        elif o == "cd":
            self.dump_coll(i(1))
        elif o == "fl":
            self.dump_free()
        elif o == "sd":
            self.dump_sample(f[1])
        elif o == "od":
            self.dump_shots()
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

def exact_impulse(target):
    """A float impulse whose (i * 1/30) * 0.65 is exactly `target`, or
    None."""
    third = f32(1.0 / 30.0)
    k = f32(0.65)
    want = f32(target)
    guess = f32(target / 0.65 * 30.0)
    b = fbits(guess)
    for d in range(-64, 65):
        x = struct.unpack("<f", struct.pack("<I", b + d))[0]
        if f32(f32(x * third) * k) == want:
            return x
    return None


def script():
    L = []
    a = L.append

    def cset(k, age=1000, imp=0.0, speed=0.0, terr=17, wt=100000):
        a("cset|%d|%d|%s|%s|%d" % (k, wt - age, fx(imp), fx(speed), terr))

    def coll(k, *args, **kw):
        a("coll|%d" % k)
        cset(k, *args, **kw)

    def vec(*v):
        return "|".join(fx(x) for x in v)

    def cpos(k, w, *v):
        a("cpos|%d|%s|%s" % (k, w, vec(*v)))

    def cam(i, *v):
        a("cam|%d|%s" % (i, vec(*v)))

    def rf(*v):
        for x in v:
            a("rf|%s" % fx(x))

    def cv(*v):
        for x in v:
            a("cv|%s" % fx(x))

    def az(*v):
        for x in v:
            a("az|%d" % x)

    # The table and the image's globals.
    a("tables")
    a("gd")
    a("fl")

    # Register: the pool and the hashes, then neither, then the hashes
    # again only when the petrol pump's is 0.
    a("reg")
    a("gd")
    a("reg")
    a("gd")
    a("hash|00000000|12345678")
    a("reg")
    a("gd")
    a("hash|11111111|22222222")
    a("reg")
    a("gd")
    a("csreg")
    a("gd")

    # Update with no world, before the regions are in, then with them in
    # and three samples missing.
    a("wt|100000")
    a("world|0")
    a("rlc|1")
    a("update")
    a("gd")
    a("world|1")
    a("rlc|0")
    a("update")
    a("gd")
    a("tbl|0")
    a("nosrc|CrashWood02")
    a("nosrc|CrashFoilage03")
    a("nosrc|CrashMetalScrape")
    a("rlc|1")
    a("update")
    a("gd")
    a("update")
    a("gd")
    a("reg")
    a("gd")
    a("update")
    a("gd")

    # Mute before anything plays, the missing samples skipped.
    a("bplaying|src:CrashWood01|1")
    a("bplaying|src:CrashFoilage02|1")
    a("mute|1")
    a("mute|0")
    a("bplaying|src:CrashWood01|0")
    a("bplaying|src:CrashFoilage02|0")

    # A missing wood crash: no type, no sample. A missing metal scrape: no
    # scrape.
    cam(1, 0.0, 0.0, 0.0)
    cam(2, 50.0, 0.0, 0.0)
    a("npc|1")
    coll(0, terr=15, imp=40.0)
    a("create|0")
    a("type|0")
    rf(0.25)
    a("create|0")
    a("type|0")
    cset(0, terr=17, imp=40.0, speed=3.0)
    a("start|0")
    a("cd|0")
    a("unlink|0")

    # The full table.
    a("unsrc")
    a("load")
    a("gd")

    # The sound type on each terrain and through each impulse bound.
    coll(1)
    a("unlink|1")
    for terr, imp in ((14, 0.0), (15, 50.0), (16, 0.0), (16, 50.0),
                      (17, 9.99), (17, 10.0), (17, 19.99), (17, 20.0),
                      (17, 29.9), (17, 30.0), (17, 100.0), (17, -5.0),
                      (17, -15.0), (13, 15.0), (18, 15.0), (28, 25.0),
                      (0, 0.0), (17, 0.0), (17, 0.0), (17, 0.0),
                      (17, 0.0), (15, 0.0), (15, 0.0), (15, 0.0)):
        cset(1, terr=terr, imp=imp)
        a("type|1")
    a("gd")
    a("load")
    a("gd")

    # The distance: one camera, then the nearer of two, either nearer,
    # with each count of players.
    cam(1, 1.0, 2.0, 3.0)
    cam(2, 10.0, -1.0, 0.5)
    for npc in (1, 2, 3, 0):
        a("npc|%d" % npc)
        a("dist|%s" % vec(4.0, 6.0, 15.0))
        a("dist|%s" % vec(9.0, -1.0, 0.5))
        a("dist|%s" % vec(5.5, 0.5, 1.75))
        a("dist|%s" % vec(1.0, 2.0, 3.0))
    a("npc|1")
    cam(1, 0.0, 0.0, 0.0)
    # Where (x*x + y*y) + z*z and x*x + (y*y + z*z) round apart.
    a("dist|%s" % vec(1.0, 2.6e-4, 2.6e-4))

    # The volumes, at and past 35 and each cap.
    for d, imp, speed in ((10.0, 15.0, 3.0), (34.9, 15.0, 6.0),
                          (35.0, 15.0, 6.0), (36.0, 15.0, 6.0),
                          (0.0, 15.0, 7.0), (10.0, 50.0, 12.0),
                          (10.0, 46.0, 6.5), (10.0, 46.2, 5.5),
                          (10.0, 0.0, 6.0), (10.0, -3.0, -6.0),
                          (3.0, 30.0, 0.0), (20.0, 45.0, 9.0)):
        cpos(1, "i", d, 0.0, 0.0)
        cset(1, imp=imp, speed=speed)
        a("vol|1")
        a("svol|1")
    cpos(1, "i", 0.0, 3.0, 4.0)
    a("vol|1")
    cpos(1, "i", 0.0, 0.0, 34.0)
    a("vol|1")
    a("azc|1")

    # StartScraping: too young, back in time, each terrain, sound off.
    coll(2)
    a("unlink|2")
    cpos(2, "i", 5.0, 0.0, 0.0)
    cpos(2, "c", 6.0, 1.0, 0.0)
    for age, terr, se in ((399, 17, 1), (400, 17, 1), (-1000, 17, 1),
                          (401, 14, 1), (401, 15, 1), (2000, 16, 1),
                          (2000, 17, 1), (2000, 18, 1), (2000, 17, 0),
                          (2000, 15, 0)):
        a("se|%d" % se)
        cset(2, age=age, terr=terr, imp=20.0, speed=4.0)
        a("cscrape|2|0")
        az(1234)
        rf(0.25)
        a("start|2")
        a("cd|2")
    a("se|1")
    a("sd|c0")

    # UpdateSample with and without a scrape.
    cset(2, imp=25.0, speed=5.0)
    cv(0.75)
    az(40000)
    a("usample|2")
    a("cscrape|2|0")
    a("usample|2")

    # CreateSample: too young, quiet, at the bound, far, sound off.
    coll(3)
    a("unlink|3")
    cpos(3, "i", 2.0, 0.0, 0.0)
    cpos(3, "c", 2.0, 2.0, 0.0)
    edge = exact_impulse(0.2)
    imps = [9.23, 9.24]
    if edge is not None:
        imps.append(edge)
    for age, imp, se in ((399, 40.0, 1), (-5, 40.0, 1), (401, 40.0, 1),
                         (1000, 5.0, 1), (1000, imps[0], 1),
                         (1000, imps[1], 1), (1000, imps[-1], 1),
                         (1000, 40.0, 0), (1000, 15.0, 1),
                         (1000, 100.0, 1)):
        a("se|%d" % se)
        cset(3, age=age, imp=imp, terr=17)
        rf(0.3)
        az(777)
        a("create|3")
    a("se|1")
    cpos(3, "i", 40.0, 0.0, 0.0)
    cset(3, imp=40.0)
    a("create|3")

    # ReleaseSample: each of Sample and Scrape playing, stopped or none.
    cpos(3, "i", 2.0, 0.0, 0.0)
    a("fl")
    combos = (("play", "none"), ("stop", "none"), ("none", "play"),
              ("none", "stop"), ("play", "play"), ("stop", "stop"),
              ("none", "none"), ("play", "stop"), ("stop", "play"))
    for n, (smp, scr) in enumerate(combos):
        k = 4 + n
        coll(k, terr=17, imp=40.0, speed=4.0)
        a("unlink|%d" % k)
        cpos(k, "i", 1.0, 0.0, 0.0)
        if smp != "none":
            rf(0.1)
            az(5)
            a("screate|%d" % k)
            if smp == "stop":
                a("bplaying|k%d.sa|0" % k)
        if scr != "none":
            rf(0.1)
            az(6)
            a("start|%d" % k)
            if scr == "stop":
                a("bplaying|k%d.sc|0" % k)
        a("cd|%d" % k)
        a("release|%d" % k)
        a("fl")

    # Update: the free list through each test -- playing at 1, at 0.05
    # and just past it, at 0 and stopped -- then the collisions: a scrape
    # kept up, a sample asked for (twice: once too quiet), and one that has
    # its sample.
    a("bgv|k6.sc|3d4ccccd")
    a("bgv|k8.sa|3d4cccce")
    a("bgv|k11.sa|00000000")
    a("bgv|k12.sc|3d4ccccc")
    a("bplaying|k8.sc|0")
    a("update")
    a("fl")
    coll(13, terr=17, imp=40.0, speed=4.0)
    coll(14, terr=15, imp=40.0, speed=4.0)
    coll(15, terr=17, imp=1.0, speed=4.0)
    rf(0.2)
    az(9)
    a("start|13")
    a("csample|14|k4.sa")
    cv(0.5)
    rf(0.4)
    az(11, 12)
    a("update")
    for k in (13, 14, 15):
        a("cd|%d" % k)
    cv(0.125)
    rf(0.45)
    az(21, 22)
    a("csupdate")
    a("fl")

    # Mute with collisions, the free list and the libraries playing.
    a("bplaying|src:CrashWood01|1")
    a("bplaying|src:CrashWood03|1")
    a("bplaying|src:CrashFoilage02|1")
    a("bplaying|src:CrashMetalSmall01|1")
    a("mute|1")
    a("mute|0")
    a("csmute|1")
    a("csmute|0")
    a("bplaying|src:CrashWood01|0")
    a("bplaying|src:CrashWood03|0")
    a("bplaying|src:CrashFoilage02|0")
    a("bplaying|src:CrashMetalSmall01|0")
    a("unlink|13")
    a("unlink|14")
    a("unlink|15")

    # Reset, UnRegister with two on the free list and with none, and
    # Register again.
    a("fl")
    a("reset")
    a("fl")
    a("reset")
    for k in (16, 17):
        coll(k, terr=15 + k - 16, imp=30.0, speed=5.0)
        a("unlink|%d" % k)
        cpos(k, "c", 1.0, 1.0, 1.0)
        rf(0.3)
        az(3)
        a("start|%d" % k)
        a("release|%d" % k)
    a("fl")
    a("unreg")
    a("gd")
    a("fl")
    a("unreg")
    a("gd")
    a("csunreg")
    a("reg")
    a("gd")

    # The one-shots.
    smoke_pos = 3
    for se in (0, 1):
        a("se|%d" % se)
        rf(0.2)
        a("foil|%d" % smoke_pos)
        rf(0.4)
        a("generic|%d" % smoke_pos)
        a("glass|%d" % smoke_pos)
        rf(0.1, 0.5)
        a("boom|%d" % smoke_pos)
    # The pumps' hashes 0, so no pump matches; then the real ones.
    a("smk|0|CS_PetrolPump|5")
    a("hash|00000000|00000000")
    rf(0.3)
    a("smoke|%d|0" % smoke_pos)
    a("reg")
    a("gd")
    a("smk|1|CS_GasPump|28")
    a("smk|2|CS_Hydrant|28")
    a("smk|3|CS_Mailbox|5")
    a("smk|4|CS_PetrolPump|28")
    for se in (1, 0):
        a("se|%d" % se)
        for j in (-1, 0, 1, 2, 3, 4):
            rf(0.05, 0.15, 0.25, 0.35)
            a("smoke|%d|%d" % (smoke_pos, j))
    a("se|1")
    a("catvol|3f000000")
    a("bust|%d" % smoke_pos)
    a("se|0")
    a("bust|%d" % smoke_pos)
    a("noshot|1")
    a("bust|%d" % smoke_pos)
    a("noshot|0")
    a("se|1")
    a("od")

    # PlayScrape: sound off, a scrape already, then none.
    coll(20, terr=16, imp=20.0, speed=2.0)
    a("unlink|20")
    a("se|0")
    a("scrape|20")
    a("cd|20")
    a("se|1")
    a("cscrape|20|c0")
    a("scrape|20")
    a("cd|20")
    a("cscrape|20|0")
    rf(0.33)
    az(4321)
    a("scrape|20")
    a("cd|20")
    a("gd")
    a("fl")
    return L


# ================================================================= build

def build_harness(tmp, name="collisionsound_test"):
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


def _m(name, before, after, rel=CSC):
    return (name, rel, before, after)


MUTATIONS = [
    # The globals and the helpers.
    _m("g-table", "int32_t    CollisionSampleTableLoaded = 1;",
       "int32_t    CollisionSampleTableLoaded = 0;"),
    _m("g-free-prev", "    &CollisionFreeSampleList, &CollisionFreeSampleList\n",
       "    &CollisionFreeSampleList, NULL\n"),
    _m("unlink-next", "    prev->next = next;\n    next->prev = prev;",
       "    next->prev = prev;"),
    _m("unlink-prev", "    prev->next = next;\n    next->prev = prev;",
       "    prev->next = next;"),
    _m("push-old-prev", "    old->prev = &s->Node;\n", ""),
    _m("push-node-prev", "    s->Node.prev = &CollisionFreeSampleList;",
       "    s->Node.prev = old;"),
    _m("push-node-next", "    s->Node.next = old;",
       "    s->Node.next = &CollisionFreeSampleList;"),
    _m("delete-flags", "((VtDestroyFn)e->fn)(vt_this(s, e), 3);",
       "((VtDestroyFn)e->fn)(vt_this(s, e), 2);"),
    _m("lib-mod", "(l->CurrSampleIndex + 1) % 3;",
       "(l->CurrSampleIndex + 1) % 2;"),
    _m("lib-old", "    return l->Samples[l->CurrSampleIndex];",
       "    return l->Samples[(l->CurrSampleIndex + 2) % 3];"),
    _m("lib-suffix", 'strcat(buf, "01");', 'strcat(buf, "1");'),
    _m("lib-digit", "buf[last] = (char)('1' + i);",
       "buf[last] = (char)('0' + i);"),
    _m("lib-cat", "bsample_set_category(l->Samples[i], 0);",
       "bsample_set_category(l->Samples[i], 1);"),
    _m("lib-reset", "    l->CurrSampleIndex = 0;\n}", "}"),
    _m("age-scale", "           * 0.00025f;                          // gp-28200",
       "           * 0.00026f;                          // gp-28200"),
    _m("age-unsigned",
       "(float)(int32_t)((uint32_t)WorldTimer - c->CollisionTime.PackedTime)",
       "(float)((uint32_t)WorldTimer - c->CollisionTime.PackedTime)"),
    _m("new-vt", "    s->_vtable = COLLISIONSAMPLE_VTABLE;\n    collisionsample_initialize",
       "    s->_vtable = 0;\n    collisionsample_initialize"),
    _m("dist-z", "return ee_sqrt((x * x + y * y) + z * z);",
       "return ee_sqrt((x * x + y * y) + z * y);"),
    _m("dist-y", "float y = cam->CurrentKey.Position.y - pos->y;",
       "float y = cam->CurrentKey.Position.y - pos->x;"),
    _m("dist-assoc", "return ee_sqrt((x * x + y * y) + z * z);",
       "return ee_sqrt(x * x + (y * y + z * z));"),

    # CollisionSample.
    _m("dtor-stop", "    bsample_stop(&s->Sample);\n    bsample_destruct", "    bsample_destruct"),
    _m("dtor-destruct", "    bsample_destruct(&s->Sample);\n    if (flags & 1)",
       "    if (flags & 1)"),
    _m("dtor-free", "        bSlotFree(CollisionSamplePool, s);", "        ;"),
    _m("init-src", "    bsample_initialize_copy(&s->Sample, src);",
       "    bsample_initialize_copy(&s->Sample, NULL);"),

    # GetCollisionSoundType.
    _m("type-wood-lo", "        && terrain >= TERRAIN_TYPE_WOOD_WALL)",
       "        && terrain > TERRAIN_TYPE_WOOD_WALL)"),
    _m("type-wood-hi", "    if (terrain < TERRAIN_TYPE_SOLID_WALL\n",
       "    if (terrain <= TERRAIN_TYPE_SOLID_WALL\n"),
    _m("type-scale", "                     * 3.0f);", "                     * 2.0f);"),
    _m("type-third", "idx = ee_trunc_w(c->TotalImpulseMagnitude * (1.0f / 30.0f)",
       "idx = ee_trunc_w(c->TotalImpulseMagnitude * (1.0f / 29.0f)"),
    _m("type-cap", "    if (idx >= 3)\n        idx = 2;", "    if (idx > 3)\n        idx = 2;"),
    _m("type-floor", "    else if (idx < 0)\n        idx = 0;",
       "    else if (idx < -1)\n        idx = 0;"),
    _m("type-round", "idx = ee_trunc_w(c->TotalImpulseMagnitude",
       "idx = ee_trunc_w(0.5f + c->TotalImpulseMagnitude"),
    _m("type-wood-lib", "        return library_next(&CollisionWoodSamples);\n    idx",
       "        return library_next(&CollisionFoilageSamples);\n    idx"),

    # Register, LoadSampleTable, UnRegister.
    _m("reg-loaded", "void collisionsounds_register(void)\n{\n    CollisionSoundRegionsLoaded = 0;\n",
       "void collisionsounds_register(void)\n{\n"),
    _m("reg-pool-test", "    if (CollisionSamplePool == NULL)\n        CollisionSamplePool = bNewSlotPool",
       "    if (1)\n        CollisionSamplePool = bNewSlotPool"),
    _m("reg-pool-count", "bNewSlotPool((int)sizeof(CollisionSample), 40,",
       "bNewSlotPool((int)sizeof(CollisionSample), 41,"),
    _m("reg-pool-name", '"CollisionSampleSounds", 16);', '"CollisionSampleSound", 16);'),
    _m("reg-pool-flags", '"CollisionSampleSounds", 16);', '"CollisionSampleSounds", 0);'),
    _m("reg-hash-test", "    if (CollisionPetrolPumpNameHash == 0) {",
       "    if (CollisionGasPumpNameHash == 0) {"),
    _m("reg-petrol-name", 'bchunk_hash("CS_PetrolPump")', 'bchunk_hash("CS_PetrolPumps")'),
    _m("reg-gas-name", 'bchunk_hash("CS_GasPump")', 'bchunk_hash("CS_GasPumps")'),
    _m("load-table", "    CollisionSampleTableLoaded = 1;\n", ""),
    _m("load-order",
       '    library_load(&CollisionMetalSamples[0], "CrashMetalSmall");\n'
       '    library_load(&CollisionMetalSamples[1], "CrashMetalMedium");\n',
       '    library_load(&CollisionMetalSamples[1], "CrashMetalMedium");\n'
       '    library_load(&CollisionMetalSamples[0], "CrashMetalSmall");\n'),
    _m("load-small-lib", 'library_load(&CollisionMetalSamples[0], "CrashMetalSmall");',
       'library_load(&CollisionMetalSamples[1], "CrashMetalSmall");'),
    _m("load-hard-name", '"CrashMetalHard");', '"CrashMetalHards");'),
    _m("load-foil-lib", 'library_load(&CollisionFoilageSamples, "CrashFoilage");',
       'library_load(&CollisionWoodSamples, "CrashFoilage");'),
    _m("load-ms-name", '"CrashMetalScrape");', '"CrashMetalScrap");'),
    _m("load-ms-cat", "    bsample_set_category(CollisionMetalScraping, 0);",
       "    bsample_set_category(CollisionMetalScraping, 1);"),
    _m("load-ws-cat", "    bsample_set_category(CollisionWoodScraping, 0);",
       "    bsample_set_category(CollisionWoodScraping, 1);"),
    _m("load-gb-cat", "    bsample_set_category(CollisionGlassBreaking, 0);",
       "    bsample_set_category(CollisionGlassBreaking, 1);"),
    _m("load-gb-name", '"CrashGlass01");', '"CrashGlass02");'),
    _m("unreg-loaded", "    CollisionSoundRegionsLoaded = 0;\n    delete_free_samples();",
       "    delete_free_samples();"),
    _m("unreg-free", "    CollisionSoundRegionsLoaded = 0;\n    delete_free_samples();",
       "    CollisionSoundRegionsLoaded = 0;"),
    _m("unreg-null", "        CollisionSamplePool = NULL;\n", ""),

    # The distance and the volumes.
    _m("dist-npc", "NumPlayerCars >= 2", "NumPlayerCars > 2"),
    _m("dist-min", "        if (d2 < d)", "        if (d2 > d)"),
    _m("dist-view2", "dist_to(pos, eGetView(2)->pCamera)", "dist_to(pos, eGetView(1)->pCamera)"),
    _m("dist-view1", "dist_to(pos, eGetView(1)->pCamera)", "dist_to(pos, eGetView(2)->pCamera)"),
    _m("vol-cut", "    if (!(d < 35.0f))", "    if (!(d <= 35.0f))"),
    _m("vol-k", "        * 0.65f;                                    // gp-28204",
       "        * 0.6f;                                    // gp-28204"),
    _m("vol-div", "    v = c->TotalImpulseMagnitude * (1.0f / 30.0f)  // gp-28208",
       "    v = c->TotalImpulseMagnitude / 30.0f  // gp-28208"),
    _m("vol-cap", "    if (1.0f < v)\n        v = 1.0f;\n    near",
       "    if (2.0f < v)\n        v = 2.0f;\n    near"),
    _m("vol-near-cap", "    if (1.0f < near)\n        near = 1.0f;\n", ""),
    _m("vol-near-num", "near = ee_div(35.0f, d);", "near = ee_div(34.0f, d);"),
    _m("vol-icp", "get_distance_to_camera(&c->InitialContactPoint)",
       "get_distance_to_camera(&c->CurrentContactPoint)"),
    _m("svol-k", "(c->CurrentScrapeSpeed * (1.0f / 6.0f))",
       "(c->CurrentScrapeSpeed * (1.0f / 5.0f))"),
    _m("svol-cap", "    if (1.0f < v)\n        v = 1.0f;\n    return v;", "    return v;"),
    _m("azc", "    (void)c;\n    return 0;", "    (void)c;\n    return 1;"),

    # StartScraping and UpdateSample.
    _m("start-age", "    if (collision_age(c) < 0.1f)                // gp-28196",
       "    if (collision_age(c) < 0.11f)                // gp-28196"),
    _m("start-wood-lo", "    if (terrain < TERRAIN_TYPE_WOOD_WALL)\n        src = NULL;",
       "    if (terrain <= TERRAIN_TYPE_WOOD_WALL)\n        src = NULL;"),
    _m("start-wood-hi", "    else if (terrain < TERRAIN_TYPE_SOLID_WALL)\n        src = CollisionWoodScraping;",
       "    else if (terrain <= TERRAIN_TYPE_SOLID_WALL)\n        src = CollisionWoodScraping;"),
    _m("start-solid", "    else if (terrain == TERRAIN_TYPE_SOLID_WALL)",
       "    else if (terrain >= TERRAIN_TYPE_SOLID_WALL)"),
    _m("start-wood-src", "        src = CollisionWoodScraping;", "        src = CollisionMetalScraping;"),
    _m("start-null", "    if (src == NULL)\n        return;\n    s = new_sample(src);",
       "    s = new_sample(src);"),
    _m("start-scrape-set", "    c->Scrape = s;\n", ""),
    _m("start-se", "    vol = collisionsounds_calc_collision_scrape_volume(c);\n    if (SoundEnabled) {",
       "    vol = collisionsounds_calc_collision_scrape_volume(c);\n    if (1) {"),
    _m("start-vol-in-se",
       "    vol = collisionsounds_calc_collision_scrape_volume(c);\n    if (SoundEnabled) {\n",
       "    vol = 0.0f;\n    if (SoundEnabled) {\n"
       "        vol = collisionsounds_calc_collision_scrape_volume(c);\n"),
    _m("start-k", "bsample_play(&s->Sample, vol * 1.9f, 0.0f, 0.0f);   // gp-28192",
       "bsample_play(&s->Sample, vol * 1.8f, 0.0f, 0.0f);   // gp-28192"),
    _m("start-pitch-range", "sound_random_float(sound_get(), 0.36f)  // gp-28188",
       "sound_random_float(sound_get(), 0.35f)  // gp-28188"),
    _m("start-pitch-off", "                          + -0.18f);                              // gp-28184",
       "                          + -0.17f);                              // gp-28184"),
    _m("start-az-ccp", "        bsample_set_azimuth(&s->Sample,\n"
       "                            sound3d_compute_azimuth(&c->CurrentContactPoint));\n"
       "        bsample_play(&s->Sample, vol * 1.9f",
       "        bsample_set_azimuth(&s->Sample,\n"
       "                            sound3d_compute_azimuth(&c->InitialContactPoint));\n"
       "        bsample_play(&s->Sample, vol * 1.9f"),
    _m("usample-cut", "sound3d_compute_volume(&c->CurrentContactPoint, 200.0f);",
       "sound3d_compute_volume(&c->CurrentContactPoint, 199.0f);"),
    _m("usample-k", "    vol = vol * 1.9f;                           // gp-28180",
       "    vol = vol * 1.8f;                           // gp-28180"),
    _m("usample-scrape", "    vol = vol * collisionsounds_calc_collision_scrape_volume(c);\n",
       ""),
    _m("usample-order", "    bsample_set_volume(&s->Sample, vol);\n    bsample_set_azimuth(&s->Sample, az);",
       "    bsample_set_azimuth(&s->Sample, az);\n    bsample_set_volume(&s->Sample, vol);"),
    _m("usample-null", "    if (s == NULL)\n        return;\n    vol = sound3d_compute_volume",
       "    vol = sound3d_compute_volume"),

    # Update and Mute.
    _m("update-world", "    if (pCurrentWorld == NULL)\n        return;\n    if (!CollisionSoundRegionsLoaded",
       "    if (!CollisionSoundRegionsLoaded"),
    _m("update-loaded", "    if (!CollisionSoundRegionsLoaded\n", "    if (1\n"),
    _m("update-set-loaded", "        CollisionSoundRegionsLoaded = 1;\n        collisionsounds_load_sample_table();",
       "        collisionsounds_load_sample_table();"),
    _m("update-vol", "|| bsample_get_volume(&s->Sample) <= 0.05f) {",
       "|| bsample_get_volume(&s->Sample) < 0.05f) {"),
    _m("update-playing", "        if (!bsample_is_playing(&s->Sample)\n",
       "        if (bsample_is_playing(&s->Sample)\n"),
    _m("update-scrape", "        if (c->Scrape != NULL)\n            collisionsounds_update_sample(c);",
       "        if (c->Scrape == NULL)\n            collisionsounds_update_sample(c);"),
    _m("update-create", "        if (c->Sample == NULL)\n            c->Sample = collision_sound_create_sample(c);",
       "        if (c->Sample != NULL)\n            c->Sample = collision_sound_create_sample(c);"),
    _m("update-store", "            c->Sample = collision_sound_create_sample(c);",
       "            collision_sound_create_sample(c);"),
    _m("update-coll-order",
       "        if (c->Scrape != NULL)\n            collisionsounds_update_sample(c);\n"
       "        if (c->Sample == NULL)\n            c->Sample = collision_sound_create_sample(c);",
       "        if (c->Sample == NULL)\n            c->Sample = collision_sound_create_sample(c);\n"
       "        if (c->Scrape != NULL)\n            collisionsounds_update_sample(c);"),
    _m("mute-ms", "    bsample_pause(CollisionMetalScraping, on != 0);",
       "    bsample_pause(CollisionMetalScraping, on == 0);"),
    _m("mute-ws", "    bsample_pause(CollisionWoodScraping, on != 0);\n", ""),
    _m("mute-coll-sample", "                bsample_pause(&c->Sample->Sample, on != 0);", "                ;"),
    _m("mute-coll-scrape", "                bsample_pause(&c->Scrape->Sample, on != 0);", "                ;"),
    _m("mute-free", "        bsample_pause(&NODE_SAMPLE(n)->Sample, on != 0);", "        ;"),
    _m("mute-wood-playing", "        BSample *s = CollisionWoodSamples.Samples[i];\n\n"
       "        if (s != NULL && bsample_is_playing(s))",
       "        BSample *s = CollisionWoodSamples.Samples[i];\n\n"
       "        if (s != NULL)"),
    _m("mute-foil", "        BSample *s = CollisionFoilageSamples.Samples[i];",
       "        BSample *s = CollisionWoodSamples.Samples[i];"),

    # collision_sound.
    _m("reset", "void collision_sound_reset(void)\n{\n    delete_free_samples();",
       "void collision_sound_reset(void)\n{\n    ;"),
    _m("cs-mute-arg", "void collision_sound_mute(int32_t on)\n{\n    collisionsounds_mute(on);",
       "void collision_sound_mute(int32_t on)\n{\n    collisionsounds_mute(!on);"),
    _m("create-age", "    if (collision_age(c) < 0.1f)                // gp-28168",
       "    if (collision_age(c) < 0.11f)                // gp-28168"),
    _m("create-type-null", "    if (src == NULL)\n        return NULL;\n    vol = ",
       "    vol = "),
    _m("create-bound", "    if (!(0.2f < vol))", "    if (!(0.2f <= vol))"),
    _m("create-se", "    s = new_sample(src);\n    if (SoundEnabled) {\n        float pitch",
       "    s = new_sample(src);\n    if (1) {\n        float pitch"),
    _m("create-pitch-range", "sound_random_float(sound_get(), 0.6f)  // gp-28160",
       "sound_random_float(sound_get(), 0.5f)  // gp-28160"),
    _m("create-pitch-off", "                     pitch - 1.0f);", "                     pitch - 0.5f);"),
    _m("create-k", "bsample_play(&s->Sample, vol * 1.9f, 0.0f,   // gp-28156",
       "bsample_play(&s->Sample, vol * 1.8f, 0.0f,   // gp-28156"),
    _m("create-order",
       "        bsample_play(&s->Sample, vol * 1.9f, 0.0f,   // gp-28156\n"
       "                     pitch - 1.0f);\n"
       "        bsample_set_azimuth(&s->Sample,\n"
       "                            sound3d_compute_azimuth(&c->CurrentContactPoint));\n",
       "        bsample_set_azimuth(&s->Sample,\n"
       "                            sound3d_compute_azimuth(&c->CurrentContactPoint));\n"
       "        bsample_play(&s->Sample, vol * 1.9f, 0.0f,   // gp-28156\n"
       "                     pitch - 1.0f);\n"),
    _m("release-playing", "        if (bsample_is_playing(&s->Sample))\n            push_free(s);",
       "        if (!bsample_is_playing(&s->Sample))\n            push_free(s);"),
    _m("release-scrape-playing", "    if (s != NULL && bsample_is_playing(&s->Sample)) {",
       "    if (s != NULL) {"),
    _m("release-fade-ms", "bsample_fade(&s->Sample, 0.0f, 50);", "bsample_fade(&s->Sample, 0.0f, 60);"),
    _m("release-fade-vol", "bsample_fade(&s->Sample, 0.0f, 50);", "bsample_fade(&s->Sample, 0.5f, 50);"),
    _m("release-scrape-push", "        bsample_fade(&s->Sample, 0.0f, 50);\n        push_free(s);",
       "        bsample_fade(&s->Sample, 0.0f, 50);"),
    _m("release-scrape-order", "    s = c->Scrape;\n    if (s != NULL && bsample_is_playing",
       "    s = c->Sample;\n    if (s != NULL && bsample_is_playing"),

    # The one-shots.
    _m("foil-se", "    if (!SoundEnabled)\n        return;\n    s = library_next(&CollisionFoilageSamples);",
       "    s = library_next(&CollisionFoilageSamples);"),
    _m("foil-lib", "    s = library_next(&CollisionFoilageSamples);",
       "    s = library_next(&CollisionWoodSamples);"),
    _m("foil-vol", "sound3d_oneshot_play(s, pos, 1.9f,                          // gp-28148",
       "sound3d_oneshot_play(s, pos, 1.8f,                          // gp-28148"),
    _m("foil-pitch", "// gp-28152\n                         + 0.5f);",
       "// gp-28152\n                         + 0.4f);"),
    _m("generic-se", "    if (!SoundEnabled)\n        return;\n    s = library_next(&CollisionWoodSamples);",
       "    s = library_next(&CollisionWoodSamples);"),
    _m("generic-lib", "    s = library_next(&CollisionWoodSamples);\n    sound3d_oneshot_play(s, pos, 2.5f,",
       "    s = library_next(&CollisionFoilageSamples);\n    sound3d_oneshot_play(s, pos, 2.5f,"),
    _m("generic-vol", "sound3d_oneshot_play(s, pos, 2.5f,", "sound3d_oneshot_play(s, pos, 2.4f,"),
    _m("generic-pitch", "// gp-28144\n                         + 0.5f);",
       "// gp-28144\n                         + 0.6f);"),
    _m("smoke-se", "    if (!SoundEnabled)\n        return;\n    if (info != NULL && info->TheTerrainType",
       "    if (info != NULL && info->TheTerrainType"),
    _m("smoke-plant", "info->TheTerrainType == TERRAIN_TYPE_PLANT", "info->TheTerrainType != TERRAIN_TYPE_PLANT"),
    _m("smoke-null", "    if (info == NULL)\n        return;\n    if (info->NameHash",
       "    if (info->NameHash"),
    _m("smoke-petrol", "    if (info->NameHash == CollisionPetrolPumpNameHash\n",
       "    if (0\n"),
    _m("smoke-gas", "        || info->NameHash == CollisionGasPumpNameHash) {",
       "        || 0) {"),
    _m("smoke-order",
       "        collision_sound_play_explosion(pos);\n"
       '        sound3d_oneshot_play_named(sound_get(), "PreviewZone", pos,\n'
       "                                   1.9f, 1.0f);             // gp-28140\n",
       '        sound3d_oneshot_play_named(sound_get(), "PreviewZone", pos,\n'
       "                                   1.9f, 1.0f);             // gp-28140\n"
       "        collision_sound_play_explosion(pos);\n"),
    _m("smoke-zone-name", 'sound_get(), "PreviewZone", pos,',
       'sound_get(), "PreviewZones", pos,'),
    _m("smoke-zone-pitch", "1.9f, 1.0f);             // gp-28140", "1.9f, 0.9f);             // gp-28140"),
    _m("glass-se", "    if (!SoundEnabled)\n        return;\n    sound3d_oneshot_play(CollisionGlassBreaking",
       "    sound3d_oneshot_play(CollisionGlassBreaking"),
    _m("glass-pitch", "// gp-28136\n                         1.0f);", "// gp-28136\n                         0.9f);"),
    _m("bust-catvol", "    bsound_get_category_volume(bsound_get(), 0);\n", ""),
    _m("bust-catvol-arg", "    bsound_get_category_volume(bsound_get(), 0);",
       "    bsound_get_category_volume(bsound_get(), 1);"),
    _m("bust-pitch", '"FinishLine", pos, 1.0f,\n                                   0.5f);',
       '"FinishLine", pos, 1.0f,\n                                   0.6f);'),
    _m("bust-null", "    if (s != NULL)\n        bsample_set_category(&s->Sample, 0xffffffffu);",
       "    bsample_set_category(&s->Sample, 0xffffffffu);"),
    _m("bust-cat", "0xffffffffu);", "0xfffffffeu);"),
    _m("boom-se", '    if (!SoundEnabled)\n        return;\n    s = sound3d_oneshot_play_named(sound_get(), "Bomb"',
       '    s = sound3d_oneshot_play_named(sound_get(), "Bomb"'),
    _m("boom-max", "    s->Envelope.MaxVolAtSource = 6.0f;\n    s->Envelope.Coeff = 1.0f / 300.0f;                      // gp-28128",
       "    s->Envelope.MaxVolAtSource = 5.0f;\n    s->Envelope.Coeff = 1.0f / 300.0f;                      // gp-28128"),
    _m("boom-coeff", "    s->Envelope.Coeff = 1.0f / 300.0f;                      // gp-28128",
       "    s->Envelope.Coeff = 1.0f / 200.0f;                      // gp-28128"),
    _m("boom-cut", "    s->Envelope.CutOffDistance = 300.0f;\n    s = sound3d",
       "    s->Envelope.CutOffDistance = 200.0f;\n    s = sound3d"),
    _m("boom2-max", "    s->Envelope.MaxVolAtSource = 6.0f;\n    s->Envelope.Coeff = 1.0f / 300.0f;\n",
       "    s->Envelope.MaxVolAtSource = 5.0f;\n    s->Envelope.Coeff = 1.0f / 300.0f;\n"),
    _m("boom2-coeff", "    s->Envelope.Coeff = 1.0f / 300.0f;\n    s->Envelope.CutOffDistance = 300.0f;\n}",
       "    s->Envelope.Coeff = 1.0f / 200.0f;\n    s->Envelope.CutOffDistance = 300.0f;\n}"),
    _m("boom2-cut", "    s->Envelope.CutOffDistance = 300.0f;\n}", "    s->Envelope.CutOffDistance = 200.0f;\n}"),
    _m("boom-name", '"Bomb", pos, 1.0f,\n                                   sound_random_float(sound_get(), 0.6f)\n'
       "                                   + 0.5f);                 // gp-28132",
       '"Bombs", pos, 1.0f,\n                                   sound_random_float(sound_get(), 0.6f)\n'
       "                                   + 0.5f);                 // gp-28132"),
    _m("boom-pitch", "+ 0.5f);                 // gp-28132", "+ 0.4f);                 // gp-28132"),
    _m("boom2-pitch", "+ 0.5f);                 // gp-28124", "+ 0.4f);                 // gp-28124"),
    _m("scrape-se", "    if (SoundEnabled && c->Scrape == NULL)", "    if (c->Scrape == NULL)"),
    _m("scrape-null", "    if (SoundEnabled && c->Scrape == NULL)", "    if (SoundEnabled)"),

    # The table.
    _m("vt-delta", "    { 0, 0, (VtFn)collisionsample_destroy },",
       "    { 4, 0, (VtFn)collisionsample_destroy },"),
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
        todo, SOURCES, "collisionsound_test",
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
