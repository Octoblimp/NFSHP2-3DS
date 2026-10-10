#!/usr/bin/env python3
"""Cross-check 3DS Files/source/sound3d.c against the retail image,
SLES_507.31.

**The model** is retail's own Sound3d.obj run in retail_model.RetailEmu
with the EE's divide, product and root (eediv, eemul, eesqrt): Sound3d's
constructor, destructor, Activate, GetDistToClosestCamera,
UpdateCamRelativeDistAndVelocity, Update, ComputeAzimuth, ComputeVolume,
AzimuthToPan, PanToAzimuth and GetAzimuth; Sound3dSample's two
constructors, destructor, new and delete, UpdateAt, Update, RemoveSample,
SetDeleteWhenDone, ActivateSound, DeactivateSound, SetPosition,
SetAzimuth, SetVolume, SetPitch and Mute; sound3d_oneshot's Init, Reset,
Close, Update, Mute, Play and the Play by name; and SoundScape's
GetActiveCameras -- on retail's own statics and its two vtables. bASin
and min run in the image too. The harness (tools/src/sound3d_test.c)
runs sound3d.c's, through the port's vtables.

**The fakes**, the same on both sides, each printing what it is handed:
bSample's constructor, destructor, Initialize (the copy), IsPlaying,
Play, Stop (which, with a voice, drops it, calls the sample's callback
and clears the pause, as bSample::Stop does), Pause (which sets the
paused flag with a voice), SetAzimuth, SetVolume and SetPitch; the slot
pool's new, delete, OMalloc (a fresh slot filled with 0xa5, named by the
order it was handed out) and free; __builtin_delete; eGetView (two
views, each with a camera the script places and points); GetInGameSample
(three names). A plain Sound3d the script makes can carry a probe vtable
whose pure slots print and whose UpdateCamRelativeDistAndVelocity prints
and runs Sound3d's, so Update is seen to call through the table.

**The script** prints the two vtables; asks for the active cameras with
each pair of players; measures the distance to one camera, two (and a
tie), none, and past the 9e9 the search starts from; steps the velocity
across the +-80 clamp and over frames of no time (+0, -0, a denormal);
updates with and without an envelope, inside, at and past its cut-off,
above full volume and with a coefficient past the quarter circle, with
the Doppler on and off; turns the azimuth round two headings, over the
camera, and with two players either side and tied; takes ComputeVolume
to its cut-off of 0; takes the azimuth to a pan and back across every
edge; activates and destroys; and runs every Sound3dSample method by
itself, then the one-shots: Init twice, Play with sound off and on, by
sample and by name (and a name with no sample), Update with one paused,
Mute, a sample ending (its callback deletes it), Reset, Close twice.
`d` and `sd` print a Sound3d and a Sound3dSample, `list` the one-shots'
list both ways, `pool` the pool.

Not run: ComputeAzimuth with three players (retail reads past its pair
of cameras), and a sum of two FLT_MAX products, which overflows to an
infinity in the model and the port alike and to FLT_MAX on the console.

    python tools/sound3d_check.py
    python tools/sound3d_check.py --mutate [--only a,b]
    python tools/sound3d_check.py --dump out/sound3d
"""
import argparse
import math
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                        # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/sound3d_test.c"
S3DC = "3DS Files/source/sound3d.c"
SOURCES = [HARNESS, S3DC, "3DS Files/source/vtable.c",
           "3DS Files/source/bmath.c", "3DS Files/source/bmathtab.c"]
HARNESS_TIMEOUT = 30
LIMIT = 200000

GP = retail_model.RETAIL_GP
F = {
    "ctor": 0x00208ae8, "activate": 0x00208b28, "dist": 0x00208b98,
    "camrel": 0x00208c78, "update": 0x00208cf0, "azimuth": 0x00208df8,
    "volume": 0x00208f70, "a2p": 0x00208fe0, "p2a": 0x00209070,
    "getaz": 0x00209150, "dtor": 0x002091a0,
    "oinit": 0x002091d0, "oreset": 0x00209208, "oclose": 0x00209268,
    "oupdate": 0x002092a0, "omute": 0x00209320, "oplayn": 0x00209388,
    "oplay": 0x002093d8,
    "sctor": 0x002094b0, "sctorat": 0x00209530, "sdtor": 0x002095d0,
    "snew": 0x00209670, "sfree": 0x00209690, "supdat": 0x002096a0,
    "supd": 0x002096f8, "remove": 0x002097a8, "sdwd": 0x002097e8,
    "sas": 0x00209dc0, "sds": 0x00209e18, "spos": 0x00209e38,
    "saz": 0x00209e48, "svol": 0x00209e60, "spitch": 0x00209e78,
    "smute": 0x00209e98, "cams": 0x001cf268,
}

# What the vtables point at, by name.
FNAME = {
    0x002091a0: "destroy", 0x00208b28: "activate", 0x002a0550: "pure",
    0x00208c78: "camrel", 0x002095d0: "sdestroy", 0x002096f8: "supdate",
    0x00209e98: "smute", 0x00209e18: "sdeactivate", 0x00209dc0: "sactivate",
    0x002096a0: "supdateat",
}
VT_S3D, VT_SAMPLE = 0x002bb2b0, 0x002bb358
REMOVE = 0x002097a8
PURE = 0x002a0550

SE = GP - 23056
NPLAYERS, PLAYERS = GP - 20920, GP - 20928
DT = GP - 19560
MPAZ = GP - 20464
POOL, LIST = GP - 16448, GP - 16456
CAMS = GP - 13368

SAMPLE_SIZE = 272
SRC_NAMES = {"glass": 0, "bush": 1, "boom": 2}


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
        self.objs = []                  # plain Sound3d records
        self.samples = []               # Sound3dSample slots, by order
        self.srcs = [e.alloc(192) for _ in range(4)]
        self.players = [e.alloc(16), e.alloc(16)]
        self.cams = {1: e.alloc(464), 2: e.alloc(464)}
        self.views = {1: e.alloc(128), 2: e.alloc(128)}
        for v in (1, 2):
            e.put32(self.views[v] + 56, self.cams[v])
        self.pool = e.alloc(16)
        self.vec = e.alloc(16, 16)
        self.env = e.alloc(16, 16)
        self.text = e.alloc(64)
        e.put32(SE, 1)
        e.put32(NPLAYERS, 0)
        e.put32(PLAYERS, 0)
        e.put32(PLAYERS + 4, 0)
        e.put32(DT, 0)
        e.mem[MPAZ:MPAZ + 2] = b"\0\0"
        e.put32(POOL, 0)
        # _GLOBAL_$I$, 0x00209da8: the one-shots' list, empty.
        e.call(0x00209da8, limit=LIMIT)

        # The probe: a derived class for a plain Sound3d.
        self.probe = e.alloc(64)
        fns = {}
        for name, fn in (("update", self.p_update), ("mute", self.p_mute),
                         ("deact", self.p_deact),
                         ("actsound", self.p_actsound),
                         ("camrel", self.p_camrel)):
            a = e.alloc(16)
            e.stub(a, fn)
            fns[name] = a
        for slot, fn in ((16, F["activate"]), (24, fns["update"]),
                         (32, fns["mute"]), (40, fns["deact"]),
                         (48, fns["actsound"]), (56, fns["camrel"])):
            e.mem[self.probe + slot:self.probe + slot + 4] = b"\0" * 4
            e.put32(self.probe + slot + 4, fn)

        e.stub(0x00272ff0, self.b_ctor)
        e.stub(0x00273148, self.b_dtor)
        e.stub(0x00273210, self.b_init)
        e.stub(0x00274410, self.b_isplaying)
        e.stub(0x00274080, self.b_play)
        e.stub(0x00274618, self.b_stop)
        e.stub(0x00274488, self.b_pause)
        e.stub(0x00273e70, self.b_az)
        e.stub(0x00273d50, self.b_vol)
        e.stub(0x00273738, self.b_pitch)
        e.stub(0x00257c10, self.newpool)
        e.stub(0x00257c48, self.delpool)
        e.stub(0x00257c80, self.omalloc)
        e.stub(0x00257ca0, self.slotfree)
        e.stub(0x00114e98, self.delete)
        e.stub(0x00107c90, self.getview)
        e.stub(0x001ae280, self.getsample)
        e.stub(PURE, self.pure)

    def emit(self, s):
        self.out.append(s)

    def cstr(self, a, n=64):
        b = bytearray()
        mem = self.e.mem
        while len(b) < n and mem[a]:
            b.append(mem[a])
            a += 1
        return b.decode("latin-1")

    def nested(self, fn, *args):
        """Call into the image from inside a stub, and put back what the
        stub's caller had."""
        e = self.e
        kept = (list(e.reg), list(e.fpr), e.hi, e.lo, e.hi1, e.lo1, e.sa,
                e.fcc, e.limit, e.icount)
        try:
            e.call(fn, *args, limit=LIMIT)
        finally:
            e.reg[:] = kept[0]
            e.fpr[:] = kept[1]
            (e.hi, e.lo, e.hi1, e.lo1, e.sa, e.fcc, e.limit,
             e.icount) = kept[2:]

    # ---- names

    def name(self, a):
        a &= M32
        if a == 0:
            return "0"
        if a == LIST:
            return "L"
        for i, o in enumerate(self.objs):
            if a == o:
                return "o%d" % i
        for i, s in enumerate(self.samples):
            if a == s:
                return "s%d" % i
            if a == s + 8:
                return "s%d.3d" % i
            if a == s + 40:
                return "s%d.b" % i
        for i, s in enumerate(self.srcs):
            if a == s:
                return "src%d" % i
        return "?"

    def cname(self, a):
        if a == 0:
            return "0"
        for v, c in self.cams.items():
            if a == c:
                return "c%d" % v
        return "?"

    def pname(self, a):
        if a == 0:
            return "0"
        return "pool" if a == self.pool else "?"

    def vtname(self, v):
        return {VT_S3D: "s3d", VT_SAMPLE: "sample",
                self.probe: "probe"}.get(v, "?")

    def cbname(self, a):
        if a == 0:
            return "0"
        return "remove" if a == REMOVE else "?"

    # ---- the fakes

    def b_ctor(self, em):
        s = em.reg[4] & M32
        self.emit("  bctor %s 0" % self.name(s))
        em.put32(s + 12, 0)
        em.put32(s + 48, 0)
        em.put32(s + 128, 0)
        return s

    def b_dtor(self, em):
        self.emit("  bdtor %s" % self.name(em.reg[4]))
        return 0

    def b_init(self, em):
        self.emit("  binit %s from %s" % (self.name(em.reg[4]),
                                          self.name(em.reg[5])))
        return 0

    def b_isplaying(self, em):
        s = em.reg[4] & M32
        v = 1 if em.u32(s + 12) else 0
        self.emit("  bisplaying %s %d" % (self.name(s), v))
        return v

    def b_play(self, em):
        s = em.reg[4] & M32
        self.emit("  bplay %s %08x %08x %08x" % (
            self.name(s), em.fpr[12], em.fpr[13], em.fpr[14]))
        em.put32(s + 12, 1)
        return 1

    def stop(self, s):
        e = self.e
        self.emit("  bstop %s" % self.name(s))
        if not e.u32(s + 12):
            return
        e.put32(s + 12, 0)
        cb = e.u32(s + 48)
        if cb:
            self.nested(cb, 8, s, e.u32(s + 52))
        e.put32(s + 128, 0)

    def b_stop(self, em):
        self.stop(em.reg[4] & M32)
        return 0

    def b_pause(self, em):
        s = em.reg[4] & M32
        on = em.reg[5] & 0xff
        self.emit("  bpause %s %d" % (self.name(s), on))
        if em.u32(s + 12):
            em.put32(s + 128, on)
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

    def newpool(self, em):
        r = em.reg
        self.emit("  newpool %d %s %d size-ok=%d" % (
            s32(r[5]), self.cstr(r[6] & M32), s32(r[7]),
            1 if s32(r[4]) == SAMPLE_SIZE else 0))
        return self.pool

    def delpool(self, em):
        self.emit("  delpool %s" % self.pname(em.reg[4] & M32))
        return 0

    def omalloc(self, em):
        e = self.e
        s = e.alloc(SAMPLE_SIZE, 16)
        e.mem[s:s + SAMPLE_SIZE] = b"\xa5" * SAMPLE_SIZE
        self.samples.append(s)
        self.emit("  omalloc %s -> s%d" % (self.pname(em.reg[4] & M32),
                                           len(self.samples) - 1))
        return s

    def slotfree(self, em):
        self.emit("  slotfree %s %s" % (self.pname(em.reg[4] & M32),
                                        self.name(em.reg[5])))
        return 0

    def delete(self, em):
        self.emit("  delete %s" % self.name(em.reg[4]))
        return 0

    def getview(self, em):
        v = s32(em.reg[4])
        self.emit("  view %d" % v)
        return self.views.get(v, 0)

    def getsample(self, em):
        name = self.cstr(em.reg[4] & M32)
        self.emit("  getsample %s" % name)
        k = SRC_NAMES.get(name)
        return 0 if k is None else self.srcs[k]

    def pure(self, em):
        raise RuntimeError("__pure_virtual reached")

    # ---- the probe

    def p_update(self, em):
        self.emit("  p-update %s %08x %d %08x" % (
            self.name(em.reg[4]), em.fpr[12], em.reg[5] & 0xffff,
            em.fpr[13]))
        return 0

    def p_mute(self, em):
        self.emit("  p-mute %s %d" % (self.name(em.reg[4]), s32(em.reg[5])))
        return 0

    def p_deact(self, em):
        self.emit("  p-deactivate %s" % self.name(em.reg[4]))
        return 0

    def p_actsound(self, em):
        self.emit("  p-activatesound %s" % self.name(em.reg[4]))
        return 0

    def p_camrel(self, em):
        self.emit("  p-camrel %s" % self.name(em.reg[4]))
        self.nested(F["camrel"], em.reg[4] & M32, em.reg[5] & M32)
        return 0

    # ---- the dumps

    def dump3d(self, a, label):
        e = self.e
        u = e.u32
        self.emit("  3d %s act=%d dop=%d vol=%08x pitch=%08x az=%d pad=%04x "
                  "vel=%08x dist=%08x vt=%s" % (
                      label, s32(u(a)), s32(u(a + 4)), u(a + 8), u(a + 12),
                      e.u16(a + 16), e.u16(a + 18), u(a + 20), u(a + 24),
                      self.vtname(u(a + 28))))

    def dump_sample(self, s):
        u = self.e.u32
        b = s + 40
        self.emit("  sample %s next=%s prev=%s env=%08x,%08x,%08x dwd=%08x "
                  "pid=%08x pos=%08x,%08x,%08x,%08x voice=%d cb=%s data=%s "
                  "paused=%d" % (
                      self.name(s), self.name(u(s)), self.name(u(s + 4)),
                      u(s + 228), u(s + 232), u(s + 236), u(s + 240),
                      u(s + 244), u(s + 256), u(s + 260), u(s + 264),
                      u(s + 268), 1 if u(b + 12) else 0,
                      self.cbname(u(b + 48)), self.name(u(b + 52)),
                      s32(u(b + 128))))
        self.dump3d(s + 8, "%s.3d" % self.name(s))

    def dump_list(self):
        u = self.e.u32
        parts = []
        for link in (0, 4):
            got = []
            a = u(LIST + link)
            while a != LIST and len(got) < 40:
                nm = self.name(a)
                got.append(nm)
                if not nm.startswith("s") or "." in nm:
                    break
                a = u(a + link)
            parts.append("".join(" " + g for g in got))
        self.emit("  list%s /%s" % (parts[0], parts[1]))

    def dump_tables(self):
        e = self.e
        for label, vt, n in (("s3d", VT_S3D, 8), ("sample", VT_SAMPLE, 9)):
            for k in range(1, n):
                d = s16(e.u16(vt + 8 * k))
                fn = e.u32(vt + 8 * k + 4)
                ds = "0" if d == 0 else "sub" if d == -8 else str(d)
                self.emit("  vt %s %d %s %s" % (label, 8 * k, ds,
                                                FNAME.get(fn, "?")))

    # ---- the ops

    def call(self, name, *args):
        return self.e.call(F[name], *args, limit=LIMIT)

    def op(self, f):
        e = self.e

        def i(k):
            return int(f[k], 0) if k < len(f) else 0

        def fb(k):
            return int(f[k], 16) & M32 if k < len(f) else 0

        def vec(k, at=None):
            a = self.vec if at is None else at
            for j in range(4):
                e.put32(a + 4 * j, fb(k + j))
            return a

        def obj(k):
            a = f[k]
            if a[0] == "o":
                return self.objs[int(a[1:])]
            if a[0] == "s":
                return self.samples[int(a[1:])] + 8
            return 0

        def smp(k):
            a = f[k]
            return self.samples[int(a[1:])] if a[0] == "s" else 0

        def src(k):
            a = f[k]
            return self.srcs[int(a[3:])] if a.startswith("src") else 0

        o = f[0]
        if o == "se":
            e.put32(SE, i(1))
        elif o == "np":
            e.put32(NPLAYERS, i(1))
        elif o == "pl":
            e.put32(PLAYERS + 4 * i(1), self.players[i(1)] if i(2) else 0)
        elif o == "dt":
            e.put32(DT, fb(1))
        elif o == "mpaz":
            e.mem[MPAZ:MPAZ + 2] = struct.pack("<H", i(1) & 0xffff)
        elif o == "cam":
            c = self.cams[i(1)]
            for j in range(3):
                e.put32(c + 64 + 4 * j, fb(2 + j))
                e.put32(c + 80 + 4 * j, fb(5 + j))
        elif o == "cams":
            self.call("cams")
            self.emit("  cams %s %s" % (self.cname(e.u32(CAMS)),
                                        self.cname(e.u32(CAMS + 4))))
        elif o == "new":
            a = e.alloc(32, 16)
            e.mem[a:a + 32] = b"\xa5" * 32
            self.objs.append(a)
            self.emit("  o%d" % (len(self.objs) - 1))
        elif o == "ctor":
            self.call("ctor", obj(1))
        elif o == "dtor":
            self.call("dtor", obj(1), i(2))
        elif o == "probe":
            e.put32(obj(1) + 28, self.probe)
        elif o == "dop":
            e.put32(obj(1) + 4, i(2))
        elif o == "act":
            self.call("activate", obj(1), i(2))
        elif o == "dist":
            self.call("dist", vec(1))
            self.emit("  = %08x" % e.fpr[0])
        elif o == "camrel":
            self.call("camrel", obj(1), vec(2))
        elif o == "upd":
            env = 0
            if f[6] != "~":
                env = self.env
                for j in range(3):
                    e.put32(env + 4 * j, fb(6 + j))
            self.call("update", obj(1), vec(2), env)
        elif o == "az":
            v = self.call("azimuth", vec(1))
            self.emit("  = %d" % (v & 0xffff))
        elif o == "cvol":
            e.fpr[12] = fb(5)
            self.call("volume", vec(1))
            self.emit("  = %08x" % e.fpr[0])
        elif o == "a2p":
            self.call("a2p", i(1))
            self.emit("  = %08x" % e.fpr[0])
        elif o == "p2a":
            e.fpr[12] = fb(1)
            v = self.call("p2a")
            self.emit("  = %d" % (v & 0xffff))
        elif o == "getaz":
            self.call("getaz", obj(1))
            self.emit("  = %08x" % e.fpr[0])
        elif o == "d":
            self.dump3d(obj(1), f[1])
        elif o == "snew":
            v = self.call("snew")
            self.emit("  -> %s" % self.name(v))
        elif o == "sctor":
            self.call("sctor", smp(1))
        elif o == "sctorat":
            e.fpr[12] = fb(6)
            self.call("sctorat", smp(1), vec(2))
        elif o == "vc":
            self.vcall(f, obj, smp, i, fb, vec)
        elif o == "sdwd":
            self.call("sdwd", smp(1), i(2))
        elif o == "sas":
            self.call("sas", smp(1))
        elif o == "sds":
            self.call("sds", smp(1))
        elif o == "spos":
            self.call("spos", smp(1), vec(2))
        elif o == "saz":
            self.call("saz", smp(1), i(2))
        elif o == "svol":
            e.fpr[12] = fb(2)
            self.call("svol", smp(1))
        elif o == "spitch":
            e.fpr[12] = fb(2)
            self.call("spitch", smp(1))
        elif o == "smute":
            self.call("smute", smp(1), i(2))
        elif o == "sfree":
            self.call("sfree", smp(1))
        elif o == "supd":
            e.fpr[12] = fb(2)
            e.fpr[13] = fb(4)
            self.call("supd", smp(1), i(3))
        elif o == "supdat":
            e.fpr[12] = fb(6)
            e.fpr[13] = fb(8)
            self.call("supdat", smp(1), vec(2), i(7))
        elif o == "voice":
            e.put32(smp(1) + 40 + 12, 1 if i(2) else 0)
        elif o == "pause":
            e.put32(smp(1) + 40 + 128, i(2))
        elif o == "end":
            self.stop(smp(1) + 40)
        elif o == "remove":
            s = smp(2)
            self.call("remove", i(1), s + 40 if s else 0, s)
        elif o == "sd":
            self.dump_sample(smp(1))
        elif o == "list":
            self.dump_list()
        elif o == "oinit":
            self.call("oinit")
        elif o == "oreset":
            self.call("oreset")
        elif o == "oclose":
            self.call("oclose")
        elif o == "oupd":
            self.call("oupdate")
        elif o == "omute":
            self.call("omute", i(1))
        elif o == "oplay":
            e.fpr[12] = fb(6)
            e.fpr[13] = fb(7)
            v = self.call("oplay", src(1), vec(2))
            self.emit("  -> %s" % self.name(v))
        elif o == "oplayn":
            e.write(self.text, f[1].encode("latin-1") + b"\0")
            e.fpr[12] = fb(6)
            e.fpr[13] = fb(7)
            v = self.call("oplayn", self.text, vec(2))
            self.emit("  -> %s" % self.name(v))
        elif o == "pool":
            self.emit("  pool %s" % self.pname(e.u32(POOL)))
        elif o == "tables":
            self.dump_tables()
        else:
            self.emit("  unknown op %s" % o)

    def vcall(self, f, obj, smp, i, fb, vec):
        """A call through the vtable, as the image makes one: the vptr at
        +28 of the Sound3d, the delta added to the Sound3d -- or, for slot
        64, Sound3dSample's own, to the Sound3dSample."""
        e = self.e
        slot = i(2)
        t = obj(1)
        base = smp(1) if slot == 64 else t
        vt = e.u32(t + 28)
        delta = s16(e.u16(vt + slot))
        fn = e.u32(vt + slot + 4)
        this = (base + delta) & M32
        if slot in (8, 16, 32):
            e.call(fn, this, i(3), limit=LIMIT)
        elif slot == 24:
            e.fpr[12] = fb(3)
            e.fpr[13] = fb(5)
            e.call(fn, this, i(4), limit=LIMIT)
        elif slot in (40, 48):
            e.call(fn, this, limit=LIMIT)
        elif slot == 56:
            e.call(fn, this, vec(3), limit=LIMIT)
        elif slot == 64:
            e.fpr[12] = fb(7)
            e.fpr[13] = fb(9)
            e.call(fn, this, vec(3), i(8), limit=LIMIT)
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

def v4(x, y, z, w=0.0):
    return "%s|%s|%s|%s" % (fx(x), fx(y), fx(z), fx(w))


def script():
    L = []
    a = L.append
    third = 1.0 / 30.0

    a("tables")
    a("se|1")
    a("np|1")
    a("dt|" + fx(third))
    a("cam|1|%s|%s|%s|%s|%s|%s" % tuple(fx(x) for x in (0, 0, 0, 1, 0, 0)))
    a("cam|2|%s|%s|%s|%s|%s|%s" % tuple(fx(x) for x in (100, 0, 0, 0, 1, 0)))

    # ---- the active cameras
    for p0, p1 in ((0, 0), (1, 0), (0, 1), (1, 1)):
        a("pl|0|%d" % p0)
        a("pl|1|%d" % p1)
        a("cams")

    # ---- the distance to the closest
    a("pl|0|1")
    a("pl|1|0")
    # The last four round differently summed as x*x + (y*y + z*z).
    for p in ((3, 4, 0), (3, 4, 12), (-3, -4, 12, 7), (0, 0, 0),
              (-184.56, 115.22, -179.64), (-78.28, -297.76, 198.03),
              (230.43, 84.94, 41.82), (-86.75, 11.46, 159.15)):
        a("dist|" + v4(*p))
    a("pl|1|1")
    for p in ((90, 0, 0), (10, 0, 0), (50, 0, 0), (50, 30, -20),
              (-1000, 5, 5), (1.1, 2.2, 3.3), (77.7, -0.3, 1e-3),
              (49.99, 1.5, -2.25), (50.01, 1.5, -2.25), (-0.7, 13.13, 4.4)):
        a("dist|" + v4(*p))
    a("pl|0|0")
    a("dist|" + v4(0, 0, 0))
    a("dist|" + v4(100, 0, 0))
    a("pl|1|0")
    a("dist|" + v4(3, 4, 0))
    a("dist|" + v4(-7, 2, 1))
    # Past the 9e9 the search starts from, and on it: the fallback asks
    # view 1 again.
    a("pl|0|1")
    for far in (1e10, 9e9):
        a("cam|1|%s|%s|%s|%s|%s|%s" % tuple(fx(x)
                                            for x in (far, 0, 0, 1, 0, 0)))
        a("dist|" + v4(0, 0, 0))
    a("cam|1|%s|%s|%s|%s|%s|%s" % tuple(fx(x) for x in (0, 0, 0, 1, 0, 0)))

    # ---- construct, the probe, the velocity
    a("new")                                    # o0
    a("d|o0")
    a("ctor|o0")
    a("d|o0")
    a("probe|o0")
    a("dt|" + fx(0.5))
    for x in (10, 60, 20, 60, 99.9, 99.9):
        a("camrel|o0|" + v4(x, 0, 0))
        a("d|o0")
    for dt in (0.0, -0.0, 1e-40, -1e-40):
        a("dt|" + fx(0.5))
        a("camrel|o0|" + v4(40, 0, 0))
        a("d|o0")
        a("dt|" + fx(dt))
        a("camrel|o0|" + v4(50, 0, 0))
        a("d|o0")
        a("camrel|o0|" + v4(50, 0, 0))
        a("d|o0")
    a("dt|" + fx(third))
    a("camrel|o0|" + v4(52, 0, 0))
    a("d|o0")

    # ---- Update
    env = "|".join(fx(x) for x in (1.0, 200.0, 0.005))
    for p in ((30, 0, 0), (30, 40, 0), (30, 40, 0), (-30, 40, 7)):
        a("upd|o0|%s|~" % v4(*p))
        a("d|o0")
        a("upd|o0|%s|%s" % (v4(*p), env))
        a("d|o0")
    for maxv, cut, coeff, p in (
            (1.0, 50.0, 0.02, (30, 40, 0)),      # at the cut-off
            (1.0, 50.0, 0.01, (30, 40, 0)),
            (1.0, 49.0, 1 / 49.0, (30, 40, 0)),  # past it
            (2.0, 200.0, 0.005, (1, 0, 0)),      # above full volume
            (0.5, 200.0, 0.005, (100, 0, 0)),
            (1.0, 200.0, 0.05, (50, 0, 0)),      # past the quarter circle
            (1.0, 200.0, 0.05, (39.9, 0, 0)),
            (3.0, 0.0, 0.0, (0, 0, 0))):
        a("upd|o0|%s|%s" % (v4(*p), "|".join(fx(x) for x in (maxv, cut,
                                                             coeff))))
        a("d|o0")
    a("dop|o0|0")
    a("upd|o0|%s|~" % v4(10, 10, 0))
    a("d|o0")
    a("dop|o0|1")
    a("upd|o0|%s|~" % v4(10, 10, 0))
    a("d|o0")
    a("getaz|o0")

    # ---- the azimuth, one player
    a("np|1")
    a("pl|0|1")
    for d in ((1, 0, 0), (0.6, 0.8, 0), (-0.28, 0.96, 0.1)):
        a("cam|1|%s|%s|%s|%s|%s|%s" % tuple(fx(x) for x in (5, -3, 2) + d))
        for k in range(24):
            t = k * math.pi / 12
            for r in (10.0, 0.25):
                a("az|" + v4(5 + r * math.cos(t), -3 + r * math.sin(t),
                             2 + k))
    a("cam|1|%s|%s|%s|%s|%s|%s" % tuple(fx(x) for x in (0, 0, 0, 1, 0, 0)))
    for p in ((10, 0, 0), (0, 10, 0), (0, -10, 0), (-10, 0, 0), (0, 0, 5),
              (-0.0, -0.0, 5), (-0.0, 0, 0), (1e-30, 0, 0), (0, -1e-30, 0)):
        a("az|" + v4(*p))

    # ---- the azimuth, two players
    a("np|2")
    a("pl|0|1")
    a("pl|1|1")
    a("cam|2|%s|%s|%s|%s|%s|%s" % tuple(fx(x) for x in (100, 0, 0, 0, 1, 0)))
    for mpaz in (5000, 0, 40000, 65535):
        a("mpaz|%d" % mpaz)
        for p in ((10, 0, 0), (90, 0, 0), (50, 0, 0), (50, 0, 99),
                  (49.9, 30, 0), (50.1, -30, 0)):
            a("az|" + v4(*p))
    a("cam|1|%s|%s|%s|%s|%s|%s" % tuple(fx(x) for x in (1e5, 0, 0, 1, 0, 0)))
    a("cam|2|%s|%s|%s|%s|%s|%s" % tuple(fx(x) for x in (-1e5, 0, 0, 1, 0, 0)))
    a("az|" + v4(0, 0, 0))
    a("az|" + v4(5e4, 0, 0))
    a("mpaz|1234")
    a("cam|1|%s|%s|%s|%s|%s|%s" % tuple(fx(x) for x in (0, 0, 0, 1, 0, 0)))
    a("cam|2|%s|%s|%s|%s|%s|%s" % tuple(fx(x)
                                        for x in (60, 80, 500, 0, 1, 0)))
    for p in ((30, 40, 0), (31, 40, 0), (29, 40, 0), (60, 0, 0),
              (0, 80, 0), (45, 70, -500), (55, 5, 900), (-20, 75, 0)):
        a("az|" + v4(*p))
    a("mpaz|0")
    a("np|1")
    a("pl|1|0")
    a("cam|1|%s|%s|%s|%s|%s|%s" % tuple(fx(x) for x in (0, 0, 0, 1, 0, 0)))
    a("cam|2|%s|%s|%s|%s|%s|%s" % tuple(fx(x) for x in (100, 0, 0, 0, 1, 0)))

    # ---- ComputeVolume
    for p, cut in (((30, 40, 0), 100.0), ((30, 40, 0), 50.0),
                   ((30, 40, 0), 49.9), ((0, 0, 0), 0.0), ((1, 0, 0), 0.0),
                   ((0, 0, 0), -0.0), ((1, 0, 0), -5.0), ((0, 0, 0), 1e-40),
                   ((3, 4, 0), 5.0), ((1, 1, 1), 1e30), ((7, 0, 0), 14.0)):
        a("cvol|%s|%s" % (v4(*p), fx(cut)))
    for k in range(12):
        a("cvol|%s|%s" % (v4(k * 7.3, k * 1.1, -k * 0.5), fx(90.0)))

    # ---- the pan and back
    edges = {0, 1, 2, 8191, 8192, 16381, 16382, 16383, 16384, 16385, 24576,
             32766, 32767, 32768, 32769, 32770, 40000, 49150, 49151, 49152,
             49153, 49154, 65533, 65534, 65535}
    for n in sorted(edges | set(range(0, 65536, 97))):
        a("a2p|%d" % n)
    pans = [-0.5, -0.25, -1e-9, -0.0, 0.0, 1e-9, 0.25, 0.5, 0.6, -0.6, 1.0,
            -1.0, 2.0, -2.0, 1e10, -1e10, 0.49999, -0.49999, 0.000030517578,
            -0.000030517578]
    pans += [k / 64.0 - 1.0 for k in range(129)]
    for p in pans:
        a("p2a|" + fx(p))

    # ---- Activate and the destructor
    a("new")                                    # o1
    a("ctor|o1")
    a("probe|o1")
    for on in (1, 1, 0, 0, 2, 5, 0, 1):
        a("act|o1|%d" % on)
        a("d|o1")
    for flags in (0, 1, 2, 3):
        a("probe|o1")
        a("dtor|o1|%d" % flags)
        a("d|o1")
    a("new")                                    # o2
    a("ctor|o2")
    a("vc|o2|56|" + v4(6, 8, 0))
    a("d|o2")

    # ---- Sound3dSample by itself
    a("pool")
    a("oinit")
    a("pool")
    a("oinit")
    a("pool")
    a("list")
    a("snew")                                   # s0
    a("sctor|s0")
    a("sd|s0")
    a("list")
    a("snew")                                   # s1
    a("sctorat|s1|%s|%s" % (v4(1, 2, 3, 4), fx(0.5)))
    a("sd|s1")
    a("list")
    a("sas|s0")
    a("sas|s0")
    a("sd|s0")
    a("se|0")
    a("sas|s1")
    a("se|1")
    a("sds|s0")
    a("sds|s0")
    a("spos|s0|" + v4(5, 6, 7, 8))
    for az in (1234, 65535, 0):
        a("saz|s0|%d" % az)
        a("sd|s0")
    a("svol|s0|" + fx(0.25))
    a("spitch|s0|" + fx(1.5))
    a("spitch|s0|" + fx(0.0))
    a("sd|s0")
    for on in (1, 7, 0):
        a("smute|s0|%d" % on)
    a("voice|s0|1")
    a("smute|s0|1")
    a("sd|s0")
    a("smute|s0|0")
    a("sdwd|s0|1")
    a("sd|s0")
    a("sdwd|s0|0")
    a("sd|s0")
    a("sdwd|s0|3")
    a("sd|s0")
    a("voice|s0|0")

    # Update and UpdateAt
    a("cam|1|%s|%s|%s|%s|%s|%s" % tuple(fx(x) for x in (0, 0, 0, 0.6, 0.8,
                                                         0)))
    a("supd|s0|%s|0|%s" % (fx(1.0), fx(1.0)))
    a("sd|s0")
    a("vc|s0|16|1")
    for vol, az, pitch in ((1.0, 0, 1.0), (0.5, 777, 2.0), (1.0, 3, 0.5)):
        a("supd|s0|%s|%d|%s" % (fx(vol), az, fx(pitch)))
        a("sd|s0")
    a("spos|s0|" + v4(300, 0, 0))
    a("supd|s0|%s|0|%s" % (fx(1.0), fx(1.0)))
    a("sd|s0")
    a("se|0")
    a("supd|s0|%s|0|%s" % (fx(1.0), fx(1.0)))
    a("se|1")
    a("supd|s0|%s|0|%s" % (fx(0.0), fx(1.0)))   # the stop deletes it
    a("sd|s0")
    a("list")
    a("supdat|s1|%s|%s|5|%s" % (v4(9, 9, 9, 1), fx(0.8), fx(1.2)))
    a("sd|s1")
    a("vc|s1|16|1")
    a("supdat|s1|%s|%s|100|%s" % (v4(9, 9, 9, 1), fx(0.8), fx(1.2)))
    a("sd|s1")
    a("vc|s1|64|%s|%s|7|%s" % (v4(-20, 5, 0, 2), fx(0.3), fx(0.9)))
    a("sd|s1")
    a("se|0")
    a("supdat|s1|%s|%s|100|%s" % (v4(1, 1, 1, 1), fx(0.8), fx(1.2)))
    a("supd|s1|%s|0|%s" % (fx(0.0), fx(1.0)))   # no callback: kept
    a("se|1")
    a("voice|s1|1")
    a("supd|s1|%s|0|%s" % (fx(-0.5), fx(1.0)))
    a("supd|s1|%s|0|%s" % (fx(-0.0), fx(1.0)))
    a("voice|s1|0")
    a("se|1")
    a("sd|s1")
    a("vc|s1|56|" + v4(3, 4, 0))
    a("vc|s1|24|%s|9|%s" % (fx(1.0), fx(1.0)))
    a("vc|s1|32|1")
    a("vc|s1|40")
    a("vc|s1|48")
    a("vc|s1|48")
    a("vc|s1|32|1")
    a("sd|s1")
    a("vc|s1|32|0")
    a("getaz|s1")

    # RemoveSample, and the destructor
    a("remove|8|0")
    a("remove|7|s1")
    a("remove|9|s1")
    a("snew")                                   # s2
    a("sctor|s2")
    a("list")
    a("remove|8|s2")
    a("list")
    a("snew")                                   # s3
    a("sctor|s3")
    a("vc|s3|16|1")
    a("sd|s3")
    a("supdat|s3|%s|%s|0|%s" % (v4(4, 3, 0, 5), fx(1.0), fx(1.0)))
    a("sd|s3")
    a("vc|s3|8|0")
    a("sd|s3")
    a("list")
    a("sfree|s3")
    a("vc|s1|8|2")
    a("list")

    # ---- the one-shots
    a("se|0")
    a("oplay|src0|%s|%s|%s" % (v4(10, 0, 0), fx(1.0), fx(1.0)))
    a("oplayn|glass|%s|%s|%s" % (v4(10, 0, 0), fx(1.0), fx(1.0)))
    a("se|1")
    a("dt|" + fx(third))
    a("oplay|src0|%s|%s|%s" % (v4(10, 0, 0, 3), fx(0.9), fx(1.1)))   # s4
    a("sd|s4")
    a("oplayn|glass|%s|%s|%s" % (v4(-40, 30, 2), fx(1.0), fx(1.0)))  # s5
    a("oplayn|nothing|%s|%s|%s" % (v4(0, 200, 0), fx(2.0), fx(0.5)))  # s6
    a("oplay|src2|%s|%s|%s" % (v4(0, 0, 0), fx(0.0), fx(1.0)))     # s7
    a("oplayn|boom|%s|%s|%s" % (v4(130, 30, 0), fx(1.0), fx(1.0)))  # s8
    a("list")
    for k in (4, 5, 6, 7, 8):
        a("sd|s%d" % k)
    a("pause|s5|1")
    a("oupd")
    a("pause|s5|0")
    a("np|2")
    a("pl|1|1")
    a("mpaz|3000")
    a("oupd")
    a("np|1")
    a("pl|1|0")
    a("mpaz|0")
    a("omute|1")
    a("sd|s4")
    a("omute|0")
    a("end|s5")
    a("list")
    a("end|s5")
    a("oupd")
    a("sd|s4")
    a("oreset")
    a("list")
    a("pool")
    a("oplay|src1|%s|%s|%s" % (v4(1, 1, 1), fx(1.0), fx(1.0)))   # s9
    a("oclose")
    a("list")
    a("pool")
    a("oclose")
    a("pool")
    a("oinit")
    a("pool")
    a("oplay|src1|%s|%s|%s" % (v4(1, 1, 1), fx(1.0), fx(1.0)))   # s10
    a("oreset")
    a("oupd")
    a("omute|1")
    a("list")
    return L


# ================================================================= build

def build_harness(tmp, name="sound3d_test"):
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

def _m(name, before, after):
    return (name, S3DC, before, after)


LINK = ("    bNode *first = Sound3dOneshotList.next;\n\n"
        "    Sound3dOneshotList.next = &s->Node;\n"
        "    first->prev = &s->Node;\n"
        "    s->Node.prev = &Sound3dOneshotList;\n"
        "    s->Node.next = first;\n")
LINK_TAIL = ("    bNode *first = Sound3dOneshotList.prev;\n\n"
             "    Sound3dOneshotList.prev = &s->Node;\n"
             "    first->next = &s->Node;\n"
             "    s->Node.next = &Sound3dOneshotList;\n"
             "    s->Node.prev = first;\n")
CTOR_AT = ("    sound3d_construct(&s->Sound);\n"
           "    s->Sound._vtable = SOUND3DSAMPLE_VTABLE;\n"
           "    bsample_construct(&s->Sample, 0);\n"
           "    s->Envelope.MaxVolAtSource = maxVol;\n")
CTOR = ("    s->Sound._vtable = SOUND3DSAMPLE_VTABLE;\n"
        "    bsample_construct(&s->Sample, 0);\n"
        "    link_first(s);\n")
OU_LOOP = ("    for (n = Sound3dOneshotList.next; n != &Sound3dOneshotList; "
           "n = n->next) {\n        Sound3dSample *s = (Sound3dSample *)n;\n\n"
           "        if (!s->Sample.paused) {\n")
OM_LOOP = ("    for (n = Sound3dOneshotList.next; n != &Sound3dOneshotList; "
           "n = n->next) {\n        Sound3dSample *s = (Sound3dSample *)n;\n"
           "        const VtEntry *e = vt_slot(s->Sound._vtable, "
           "SOUND3D_VT_MUTE);\n")
CAMREL = ("    ((VtCamRelativeFn)e->fn)(vt_this(s, e), pos);\n"
          "    if (s->DopplerIsActive)\n"
          "        s->Pitch = 1.0f - s->SndToCameraVelocity / SpeedOfSound;\n")

MUTATIONS = [
    # GetActiveCameras
    _m("gac-index", "PlayerPlayersByIndex[i] != NULL",
       "PlayerPlayersByIndex[1 - i] != NULL"),
    _m("gac-view", "eGetView(i + 1)->pCamera : NULL",
       "eGetView(1)->pCamera : NULL"),
    _m("gac-null", "->pCamera : NULL;\n", "->pCamera : ActiveCameras[i];\n"),
    _m("gac-count", "for (i = 0; i < 2; i++)\n        ActiveCameras",
       "for (i = 0; i < 1; i++)\n        ActiveCameras"),
    # the constructor and destructor
    _m("ctor-vt", "    s->_vtable = SOUND3D_VTABLE;\n    s->DopplerIsActive = 1;",
       "    s->_vtable = SOUND3DSAMPLE_VTABLE;\n    s->DopplerIsActive = 1;"),
    _m("ctor-dop", "s->DopplerIsActive = 1;", "s->DopplerIsActive = 0;"),
    _m("ctor-pitch", "    s->Pitch = 1.0f;\n    s->Activated = 0;",
       "    s->Pitch = 0.0f;\n    s->Activated = 0;"),
    _m("ctor-act", "    s->Activated = 0;\n    s->Volume = 1.0f;",
       "    s->Activated = 1;\n    s->Volume = 1.0f;"),
    _m("ctor-vol", "    s->Volume = 1.0f;\n    s->Azimuth = 0;",
       "    s->Volume = 0.5f;\n    s->Azimuth = 0;"),
    _m("ctor-az", "    s->Azimuth = 0;\n    s->SndToCameraVelocity = 0.0f;",
       "    s->SndToCameraVelocity = 0.0f;"),
    _m("ctor-vel", "    s->SndToCameraVelocity = 0.0f;\n"
                   "    s->SndToCameraDistance = 0.0f;\n}",
       "    s->SndToCameraDistance = 0.0f;\n}"),
    _m("ctor-dist", "    s->SndToCameraVelocity = 0.0f;\n"
                    "    s->SndToCameraDistance = 0.0f;\n}",
       "    s->SndToCameraVelocity = 0.0f;\n}"),
    _m("dtor-vt", "    s->_vtable = SOUND3D_VTABLE;\n    if (flags & 1)",
       "    if (flags & 1)"),
    _m("dtor-flag", "    if (flags & 1)\n        bFree(s);",
       "    if (flags)\n        bFree(s);"),
    _m("dtor-bit", "    if (flags & 1)\n        bFree(s);",
       "    if (flags & 2)\n        bFree(s);"),
    # Activate
    _m("act-off-slot", "e = vt_slot(s->_vtable, SOUND3D_VT_DEACTIVATE);",
       "e = vt_slot(s->_vtable, SOUND3D_VT_ACTIVATESOUND);"),
    _m("act-on-slot", "e = vt_slot(s->_vtable, SOUND3D_VT_ACTIVATESOUND);",
       "e = vt_slot(s->_vtable, SOUND3D_VT_DEACTIVATE);"),
    _m("act-test", "} else if (!s->Activated) {", "} else {"),
    _m("act-off-test", "    if (!on) {\n", "    if (!on && s->Activated) {\n"),
    _m("act-bool", "    s->Activated = on;\n", "    s->Activated = on != 0;\n"),
    _m("act-store", "    s->Activated = on;\n", ""),
    # the distance
    _m("dsq-z", "return (x * x + y * y) + z * z;", "return x * x + y * y;"),
    _m("dsq-order", "return (x * x + y * y) + z * z;",
       "return x * x + (y * y + z * z);"),
    _m("gd-start", "float best = 9e9f;                          // gp-27656",
       "float best = 1e9f;                          // gp-27656"),
    _m("gd-null", "if (cams[i] != NULL) {", "if (cams[i] != NULL && i == 0) {"),
    _m("gd-min", "best = best < d ? best : d;", "best = d;"),
    _m("gd-max", "best = best < d ? best : d;", "best = best < d ? d : best;"),
    _m("gd-sqrt", "float d = sqrtf(dist_sq(pos, &cams[i]->CurrentKey.Position));",
       "float d = dist_sq(pos, &cams[i]->CurrentKey.Position);"),
    _m("gd-fallback", "if (best == 9e9f)", "if (0)"),
    _m("gd-fb-view", "&eGetView(1)->pCamera->CurrentKey.Position));",
       "&eGetView(2)->pCamera->CurrentKey.Position));"),
    _m("gd-fb-sqrt", "best = sqrtf(dist_sq(pos,", "best = (dist_sq(pos,"),
    # the velocity
    _m("cr-sub", "ee_div(d - s->SndToCameraDistance, WorldTimeElapsed)",
       "ee_div(s->SndToCameraDistance - d, WorldTimeElapsed)"),
    _m("cr-div", "ee_div(d - s->SndToCameraDistance, WorldTimeElapsed)",
       "(d - s->SndToCameraDistance) / WorldTimeElapsed"),
    _m("cr-hi", "if (v < 80.0f && -80.0f < v)", "if (v <= 80.0f && -80.0f < v)"),
    _m("cr-lo", "if (v < 80.0f && -80.0f < v)", "if (v < 80.0f && -80.0f <= v)"),
    _m("cr-noclamp", "if (v < 80.0f && -80.0f < v)", "if (1)"),
    _m("cr-dist", "    s->SndToCameraDistance = d;\n}", "}"),
    _m("cr-dist-in", "if (v < 80.0f && -80.0f < v)\n"
                     "        s->SndToCameraVelocity = v;\n"
                     "    s->SndToCameraDistance = d;",
       "if (v < 80.0f && -80.0f < v) {\n"
       "        s->SndToCameraVelocity = v;\n"
       "        s->SndToCameraDistance = d;\n    }"),
    # Update
    _m("up-direct", "    ((VtCamRelativeFn)e->fn)(vt_this(s, e), pos);\n",
       "    (void)e;\n    sound3d_update_cam_relative_dist_and_velocity(s, pos);\n"),
    _m("up-order", CAMREL,
       "    if (s->DopplerIsActive)\n"
       "        s->Pitch = 1.0f - s->SndToCameraVelocity / SpeedOfSound;\n"
       "    ((VtCamRelativeFn)e->fn)(vt_this(s, e), pos);\n"),
    _m("up-dop-test", "    if (s->DopplerIsActive)\n        s->Pitch",
       "    if (1)\n        s->Pitch"),
    _m("up-dop-sign", "s->Pitch = 1.0f - s->SndToCameraVelocity / SpeedOfSound;",
       "s->Pitch = 1.0f + s->SndToCameraVelocity / SpeedOfSound;"),
    _m("up-dop-sos", "s->Pitch = 1.0f - s->SndToCameraVelocity / SpeedOfSound;",
       "s->Pitch = 1.0f - s->SndToCameraVelocity / 340.0f;"),
    _m("up-env", "    if (env != NULL) {\n", "    if (0) {\n"),
    _m("up-cut", "if (env->CutOffDistance < d) {", "if (env->CutOffDistance <= d) {"),
    _m("up-cut-vol", "            vol = 0.0f;\n", "            vol = 0.5f;\n"),
    _m("up-r", "float r = d * env->Coeff;", "float r = d;"),
    _m("up-2d", "(1.0f - ee_sqrt((d + d) * env->Coeff - r * r))",
       "(1.0f - ee_sqrt(d * env->Coeff - r * r))"),
    _m("up-sqrt", "(1.0f - ee_sqrt((d + d) * env->Coeff - r * r))",
       "(1.0f - sqrtf((d + d) * env->Coeff - r * r))"),
    _m("up-max", "vol = env->MaxVolAtSource\n", "vol = 1.0f\n"),
    _m("up-clamp", "s->Volume = 1.0f < vol ? 1.0f : vol;", "s->Volume = vol;"),
    _m("up-clamp-lo", "s->Volume = 1.0f < vol ? 1.0f : vol;",
       "s->Volume = 1.0f < vol ? 1.0f : vol < 0.0f ? 0.0f : vol;"),
    _m("up-noenv", "        s->Volume = 1.0f;\n    }",
       "        s->Volume = 0.5f;\n    }"),
    _m("up-az", "s->Azimuth = sound3d_compute_azimuth(pos);", "s->Azimuth = 0;"),
    # ComputeAzimuth
    _m("az-np", "if (PlayerNumPlayers >= 2) {", "if (PlayerNumPlayers > 2) {"),
    _m("az-np1", "if (PlayerNumPlayers >= 2) {", "if (PlayerNumPlayers >= 1) {"),
    _m("az-best", "float best = 9e9f;                      // gp-27648",
       "float best = 1e9f;                      // gp-27648"),
    _m("az-closest", "int32_t i, closest = -1;", "int32_t i, closest = 0;"),
    _m("az-strict", "if (dsq < best) {", "if (dsq <= best) {"),
    _m("az-cy", "cy = c->y - pos->y;", "cy = c->z - pos->z;"),
    _m("az-cx", "float cx = c->x - pos->x,", "float cx = c->y - pos->x,"),
    _m("az-dsq", "float dsq = cx * cx + cy * cy;", "float dsq = cx * cx;"),
    _m("az-ret", "if (closest != 0)\n", "if (closest == 1)\n"),
    _m("az-neg", "return (uint16_t)-CarSoundMultiPlayerAzimuth;",
       "return CarSoundMultiPlayerAzimuth;"),
    _m("az-view", "cam = eGetView(1)->pCamera;", "cam = eGetView(2)->pCamera;"),
    _m("az-y", "y = pos->y - cam->CurrentKey.Position.y;",
       "y = cam->CurrentKey.Position.y - pos->y;"),
    _m("az-x", "x = pos->x - cam->CurrentKey.Position.x;",
       "x = cam->CurrentKey.Position.x - pos->x;"),
    _m("az-len", "len = sqrtf(x * x + y * y);", "len = x * x + y * y;"),
    _m("az-divx", "x = ee_div(x, len);", "x = x / len;"),
    _m("az-divy", "y = ee_div(y, len);", "y = y / len;"),
    _m("az-dot", "bASin(x * dirX + y * dirY)", "bASin(x * dirY + y * dirX)"),
    _m("az-16384", "(uint16_t)(16384 - bASin(", "(uint16_t)(16383 - bASin("),
    _m("az-cross", "if (-y * dirX + x * dirY < 0.0f)",
       "if (y * dirX - x * dirY < 0.0f)"),
    _m("az-flip", "az = (uint16_t)-az;", "az = (uint16_t)(65535 - az);"),
    # ComputeVolume
    _m("cv-div", "float c = ee_div(1.0f, cutOff);", "float c = 1.0f / cutOff;"),
    _m("cv-test", "    if (cutOff < d)\n        return 0.0f;\n    r = d * c;",
       "    if (cutOff <= d)\n        return 0.0f;\n    r = d * c;"),
    _m("cv-r", "    r = d * c;\n", "    r = d;\n"),
    _m("cv-2d", "return 1.0f - sqrtf((d + d) * c - r * r);",
       "return 1.0f - sqrtf(d * c - r * r);"),
    _m("cv-sign", "return 1.0f - sqrtf((d + d) * c - r * r);",
       "return 1.0f + sqrtf((d + d) * c - r * r);"),
    # AzimuthToPan and PanToAzimuth
    _m("a2p-mod", "(a % 16383u)", "(a % 16384u)"),
    _m("a2p-scale", "6.10351562e-05f", "6.1e-05f"),
    _m("a2p-r1", "if (a < 16383u)", "if (a <= 16383u)"),
    _m("a2p-r2", "else if (a - 16383u < 16385u)", "else if (a - 16383u <= 16385u)"),
    _m("a2p-r3", "& 0xffffu) < 16385u)", "& 0xffffu) < 16384u)"),
    _m("a2p-b2", "pan = 1.0f - f;", "pan = f;"),
    _m("a2p-b3", "pan = -f;", "pan = f;"),
    _m("a2p-b4", "pan = f - 1.0f;", "pan = 1.0f - f;"),
    _m("a2p-half", "return pan * 0.5f;", "return pan;"),
    _m("p2a-neg", "if (pan < 0.0f) {", "if (pan <= 0.0f) {"),
    _m("p2a-half", "float t = pan + 0.5f;", "float t = pan + 0.25f;"),
    _m("p2a-off", "+ 49152.0f)", "+ 49151.0f)"),
    _m("p2a-scale-n", "(t + t) * 16383.0f", "(t + t) * 16384.0f"),
    _m("p2a-scale-p", "(pan + pan) * 16383.0f", "(pan + pan) * 16384.0f"),
    _m("p2a-trunc", "return (uint16_t)ee_trunc_w((pan + pan) * 16383.0f);",
       "return (uint16_t)(int32_t)((pan + pan) * 16383.0f);"),
    _m("getaz", "return (float)(int32_t)s->Azimuth;",
       "return (float)(int16_t)s->Azimuth;"),
    # Sound3dSample: the list and the constructors
    _m("lf-tail", LINK, LINK_TAIL),
    _m("lf-prev", "    first->prev = &s->Node;\n", ""),
    _m("sc-vt", CTOR, "    bsample_construct(&s->Sample, 0);\n"
                      "    link_first(s);\n"),
    _m("sc-bctor", CTOR, "    s->Sound._vtable = SOUND3DSAMPLE_VTABLE;\n"
                         "    link_first(s);\n"),
    _m("sc-type", CTOR, "    s->Sound._vtable = SOUND3DSAMPLE_VTABLE;\n"
                        "    bsample_construct(&s->Sample, 1);\n"
                        "    link_first(s);\n"),
    _m("sc-link", CTOR, "    s->Sound._vtable = SOUND3DSAMPLE_VTABLE;\n"
                        "    bsample_construct(&s->Sample, 0);\n"),
    _m("sc-max", "s->Envelope.MaxVolAtSource = 1.0f;",
       "s->Envelope.MaxVolAtSource = 0.5f;"),
    _m("sc-cut", "s->Envelope.CutOffDistance = 200.0f;",
       "s->Envelope.CutOffDistance = 135.0f;"),
    _m("sc-coeff", "s->Envelope.Coeff = 0.005f;", "s->Envelope.Coeff = 0.0051f;"),
    _m("sc-pid", "s->PositionIsDefined = 0;", "s->PositionIsDefined = 1;"),
    _m("sca-3d", CTOR_AT, CTOR_AT.replace("    sound3d_construct(&s->Sound);\n",
                                          "")),
    _m("sca-vt", CTOR_AT, CTOR_AT.replace(
        "    s->Sound._vtable = SOUND3DSAMPLE_VTABLE;\n", "")),
    _m("sca-bctor", CTOR_AT, CTOR_AT.replace(
        "    bsample_construct(&s->Sample, 0);\n", "")),
    _m("sca-max", "s->Envelope.MaxVolAtSource = maxVol;",
       "s->Envelope.MaxVolAtSource = 1.0f;"),
    _m("sca-cut", "s->Envelope.CutOffDistance = 135.0f;",
       "s->Envelope.CutOffDistance = 200.0f;"),
    _m("sca-coeff", "s->Envelope.Coeff = 1.0f / 135.0f;",
       "s->Envelope.Coeff = 0.0074f;"),
    _m("sca-pos", "    s->Position = *pos;\n    link_first(s);\n",
       "    link_first(s);\n"),
    _m("sca-pos-pad", "    s->Position = *pos;\n    link_first(s);\n",
       "    s->Position.x = pos->x;\n    s->Position.y = pos->y;\n"
       "    s->Position.z = pos->z;\n    link_first(s);\n"),
    _m("sca-link", "    s->Position = *pos;\n    link_first(s);\n",
       "    s->Position = *pos;\n"),
    _m("sca-pid", "    link_first(s);\n    s->PositionIsDefined = 1;\n}",
       "    link_first(s);\n}"),
    # the destructor, new and delete
    _m("sd-stop", "    bsample_stop(&s->Sample);\n    s->Node.prev->next",
       "    s->Node.prev->next"),
    _m("sd-unlink1", "    s->Node.prev->next = s->Node.next;\n", ""),
    _m("sd-unlink2", "    s->Node.next->prev = s->Node.prev;\n", ""),
    _m("sd-bdtor", "    bsample_destruct(&s->Sample);\n", ""),
    _m("sd-3d", "    sound3d_destroy(&s->Sound, 0);\n", ""),
    _m("sd-3d-flags", "sound3d_destroy(&s->Sound, 0);",
       "sound3d_destroy(&s->Sound, 1);"),
    _m("sd-free", "    if (flags & 1)\n        sound3d_sample_free(s);",
       "    if (flags & 2)\n        sound3d_sample_free(s);"),
    _m("sfree", "bSlotFree(Sound3dSampleSlotPool, s);", "bSlotFree(NULL, s);"),
    _m("del-flags", "(vt_this(&s->Sound, e), 3);", "(vt_this(&s->Sound, e), 2);"),
    # UpdateAt and Update
    _m("ua-se", "if (!SoundEnabled || !s->Sound.Activated)\n",
       "if (!s->Sound.Activated)\n"),
    _m("ua-act", "if (!SoundEnabled || !s->Sound.Activated)\n",
       "if (!SoundEnabled)\n"),
    _m("ua-pos", "    s->Position = *pos;\n    s->PositionIsDefined = 1;\n",
       "    s->PositionIsDefined = 1;\n"),
    _m("ua-pid", "    s->Position = *pos;\n    s->PositionIsDefined = 1;\n",
       "    s->Position = *pos;\n"),
    _m("ua-args", "volume, azimuth, pitch);\n}", "pitch, azimuth, volume);\n}"),
    _m("su-se", "if (SoundEnabled && s->Sound.Activated) {",
       "if (s->Sound.Activated) {"),
    _m("su-act", "if (SoundEnabled && s->Sound.Activated) {",
       "if (SoundEnabled) {"),
    _m("su-env", "sound3d_update(&s->Sound, &s->Position, &s->Envelope);",
       "sound3d_update(&s->Sound, &s->Position, NULL);"),
    _m("su-vol", "sound3d_sample_set_volume(s, s->Sound.Volume * volume);",
       "sound3d_sample_set_volume(s, s->Sound.Volume);"),
    _m("su-pitch", "sound3d_sample_set_pitch(s, s->Sound.Pitch * pitch);",
       "sound3d_sample_set_pitch(s, s->Sound.Pitch);"),
    _m("su-az", "bsample_set_azimuth(&s->Sample, s->Sound.Azimuth);",
       "bsample_set_azimuth(&s->Sample, azimuth);"),
    _m("su-stop-le", "    if (volume == 0.0f)\n", "    if (volume <= 0.0f)\n"),
    _m("su-stop-in", "        bsample_set_azimuth(&s->Sample, s->Sound.Azimuth);\n"
                     "    }\n    if (volume == 0.0f)\n"
                     "        bsample_stop(&s->Sample);\n",
       "        bsample_set_azimuth(&s->Sample, s->Sound.Azimuth);\n"
       "        if (volume == 0.0f)\n"
       "            bsample_stop(&s->Sample);\n    }\n"),
    # RemoveSample and SetDeleteWhenDone
    _m("rm-ev", "if (event == BSOUND_SAMPLE_STOPPED && data != NULL)",
       "if (data != NULL)"),
    _m("rm-data", "if (event == BSOUND_SAMPLE_STOPPED && data != NULL)",
       "if (event == BSOUND_SAMPLE_STOPPED)"),
    _m("dwd-test", "    if (on) {\n        s->Sample.callbackData = s;",
       "    if (on == 1) {\n        s->Sample.callbackData = s;"),
    _m("dwd-data", "s->Sample.callbackData = s;", "s->Sample.callbackData = NULL;"),
    _m("dwd-cb", "s->Sample.callback = sound3d_remove_sample;",
       "s->Sample.callback = NULL;"),
    _m("dwd-off-data", "        s->Sample.callbackData = NULL;\n"
                       "        s->Sample.callback = NULL;\n",
       "        s->Sample.callback = NULL;\n"),
    _m("dwd-off-cb", "        s->Sample.callbackData = NULL;\n"
                     "        s->Sample.callback = NULL;\n",
       "        s->Sample.callbackData = NULL;\n"),
    # the small methods
    _m("as-se", "if (SoundEnabled && !bsample_is_playing(&s->Sample))",
       "if (!bsample_is_playing(&s->Sample))"),
    _m("as-playing", "if (SoundEnabled && !bsample_is_playing(&s->Sample))",
       "if (SoundEnabled)"),
    _m("as-args", "bsample_play(&s->Sample, 0.0f, 0.0f, 0.0f);",
       "bsample_play(&s->Sample, 1.0f, 0.0f, 0.0f);"),
    _m("ds", "    bsample_stop(&s->Sample);\n}\n\nvoid sound3d_sample_set_position",
       "}\n\nvoid sound3d_sample_set_position"),
    _m("spos", "    s->Position = *pos;\n}", "    s->Position.x = pos->x;\n}"),
    _m("saz-field", "    s->Sound.Azimuth = azimuth;\n", ""),
    _m("saz-b", "    bsample_set_azimuth(&s->Sample, azimuth);\n}",
       "    bsample_set_azimuth(&s->Sample, 0);\n}"),
    _m("svol-field", "    s->Sound.Volume = volume;\n", ""),
    _m("svol-b", "bsample_set_volume(&s->Sample, volume);",
       "bsample_set_volume(&s->Sample, volume * 0.5f);"),
    _m("spitch-field", "    s->Sound.Pitch = pitch;\n",
       "    s->Sound.Pitch = pitch - 1.0f;\n"),
    _m("spitch-b", "bsample_set_pitch(&s->Sample, pitch - 1.0f);",
       "bsample_set_pitch(&s->Sample, pitch);"),
    _m("smute", "bsample_pause(&s->Sample, on != 0);",
       "bsample_pause(&s->Sample, on == 1);"),
    # sound3d_oneshot
    _m("oi-test", "    if (Sound3dSampleSlotPool == NULL)\n", "    if (1)\n"),
    _m("oi-size", "bNewSlotPool((int)sizeof(Sound3dSample), 30,",
       "bNewSlotPool((int)sizeof(Sound3d), 30,"),
    _m("oi-count", "bNewSlotPool((int)sizeof(Sound3dSample), 30,",
       "bNewSlotPool((int)sizeof(Sound3dSample), 32,"),
    _m("oi-name", "\"Sound3dSampleSlotPool\", 16);", "\"Sound3dSamplePool\", 16);"),
    _m("oi-flags", "\"Sound3dSampleSlotPool\", 16);",
       "\"Sound3dSampleSlotPool\", 0);"),
    _m("or-dwd", "        sound3d_sample_set_delete_when_done(\n"
                 "            (Sound3dSample *)Sound3dOneshotList.next, 0);\n", ""),
    _m("or-loop", "    while (Sound3dOneshotList.next != &Sound3dOneshotList) {",
       "    if (Sound3dOneshotList.next != &Sound3dOneshotList) {"),
    _m("oc-reset", "    sound3d_oneshot_reset();\n    if (Sound3dSampleSlotPool",
       "    if (Sound3dSampleSlotPool"),
    _m("oc-test", "    if (Sound3dSampleSlotPool != NULL) {\n", "    if (1) {\n"),
    _m("oc-null", "        Sound3dSampleSlotPool = NULL;\n", ""),
    _m("ou-paused", "        if (!s->Sample.paused) {", "        if (1) {"),
    _m("ou-args", "(vt_this(&s->Sound, e), 1.0f, 0, 1.0f);",
       "(vt_this(&s->Sound, e), 1.0f, 0, 0.5f);"),
    _m("ou-first", OU_LOOP, OU_LOOP.replace("n = Sound3dOneshotList.next;",
                                            "n = Sound3dOneshotList.next->next;")),
    _m("om-arg", "((VtMuteFn)e->fn)(vt_this(&s->Sound, e), on);",
       "((VtMuteFn)e->fn)(vt_this(&s->Sound, e), 1);"),
    _m("om-first", OM_LOOP, OM_LOOP.replace("n = Sound3dOneshotList.next;",
                                            "n = Sound3dOneshotList.next->next;")),
    _m("op-se", "    if (!SoundEnabled)\n        return NULL;\n", ""),
    _m("op-vol", "sound3d_sample_construct_at(s, pos, volume);",
       "sound3d_sample_construct_at(s, pos, 1.0f);"),
    _m("op-init", "    bsample_initialize_copy(&s->Sample, sample);\n", ""),
    _m("op-dop", "    s->Sound.DopplerIsActive = 0;\n", ""),
    _m("op-act", "((VtActivateFn)e->fn)(vt_this(&s->Sound, e), 1);",
       "((VtActivateFn)e->fn)(vt_this(&s->Sound, e), 0);"),
    _m("op-dwd", "    sound3d_sample_set_delete_when_done(s, 1);\n"
                 "    e = vt_slot",
       "    sound3d_sample_set_delete_when_done(s, 0);\n    e = vt_slot"),
    _m("op-dwd-late", "    sound3d_sample_set_delete_when_done(s, 1);\n"
                      "    e = vt_slot(s->Sound._vtable, SOUND3DSAMPLE_VT_UPDATE_AT);\n"
                      "    ((VtUpdateAtFn)e->fn)(vt_this(s, e), pos, volume, 0, pitch);\n",
       "    e = vt_slot(s->Sound._vtable, SOUND3DSAMPLE_VT_UPDATE_AT);\n"
       "    ((VtUpdateAtFn)e->fn)(vt_this(s, e), pos, volume, 0, pitch);\n"
       "    sound3d_sample_set_delete_when_done(s, 1);\n"),
    _m("op-upd-vol", "(vt_this(s, e), pos, volume, 0, pitch);",
       "(vt_this(s, e), pos, 1.0f, 0, pitch);"),
    _m("op-upd-pitch", "(vt_this(s, e), pos, volume, 0, pitch);",
       "(vt_this(s, e), pos, volume, 0, 1.0f);"),
    _m("op-upd", "    ((VtUpdateAtFn)e->fn)(vt_this(s, e), pos, volume, 0, pitch);\n",
       ""),
    _m("op-ret", "    return s;\n}", "    return NULL;\n}"),
    _m("pn-name", "sound_get_in_game_sample(m, name)",
       "sound_get_in_game_sample(m, \"glass\")"),
    _m("pn-args", "pos,\n                                volume, pitch);",
       "pos,\n                                pitch, volume);"),
    # the tables
    _m("vt-s3d-camrel",
       "    E(0, sound3d_update_cam_relative_dist_and_velocity), // 56 0x00208c78\n"
       "};\n\n// _vt$13Sound3dSample",
       "    { 0, 0, NULL },\n};\n\n// _vt$13Sound3dSample"),
    _m("vt-s3d-destroy", "    E(0, sound3d_destroy),",
       "    E(0, sound3d_activate),"),
    _m("vt-sdestroy", "E(SUB, sound3d_sample_destroy),",
       "E(0, sound3d_sample_destroy),"),
    _m("vt-sactivate-d", "    E(0, sound3d_activate),                             "
                         "// 16  0x00208b28\n    E(SUB, sound3d_sample_update),",
       "    E(SUB, sound3d_activate),                             "
       "// 16  0x00208b28\n    E(SUB, sound3d_sample_update),"),
    _m("vt-supdate", "E(SUB, sound3d_sample_update),",
       "E(0, sound3d_sample_update),"),
    _m("vt-smute", "E(SUB, sound3d_sample_mute),", "E(0, sound3d_sample_mute),"),
    _m("vt-sdeact", "E(SUB, sound3d_sample_deactivate_sound),",
       "E(SUB, sound3d_sample_activate_sound),"),
    _m("vt-sact", "E(SUB, sound3d_sample_activate_sound),",
       "E(SUB, sound3d_sample_deactivate_sound),"),
    _m("vt-ua", "E(0, sound3d_sample_update_at),",
       "E(SUB, sound3d_sample_update_at),"),
]

EQUIVALENT = {}


def mutate_pass(only):
    todo = MUTATIONS
    if only is not None:
        todo = [m for m in MUTATIONS if m[0] in only]
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    lines = script()
    base, _ = model(lines)
    caught, survived, missing, equivalent = 0, [], [], []
    indir = tempfile.TemporaryDirectory()
    scp = write_script(indir.name, lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, scp, out)
        if diff(base, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for m in todo:
        name, rel, before, after = m
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if text.count(probe) != 1:
            missing.append(name)
            print("  %-44s PATTERN %s" % (
                name, "NOT FOUND" if not text.count(probe) else "NOT UNIQUE"))
            continue
        new = text.replace(probe, repl, 1)
        try:
            hostbuild.write_source(path, new)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = build_harness(tmp)
                except SystemExit:
                    print("  %-44s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, scp, out)
                if rc == pcc.HARNESS_HUNG:
                    print("  %-44s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-44s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-44s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-44s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-44s SURVIVED" % name)
                    survived.append(name)
        finally:
            try:
                hostbuild.write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))
    indir.cleanup()

    real = [m for m in todo if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    ran = {m[0] for m in todo}
    stale = [n for n in EQUIVALENT
             if n not in equivalent and n not in missing
             and (n in ran or only is None)]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally above is over %d of %d"
              % (len(missing), len(real), len(todo)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
    for name in holes:
        print("  unexplained: %s" % name)
    for name in stale:
        print("  listed as equivalent but %s: %s"
              % ("caught" if name in ran else "names no mutation", name))
    return 1 if (holes or missing or stale) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--dump", metavar="PREFIX")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None))

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
