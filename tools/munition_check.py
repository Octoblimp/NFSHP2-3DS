#!/usr/bin/env python3
"""Check munition.c against the retail image's munitions, line by line.

The helicopter's armament (TASKS 39, 12k-6): Rocket, SmokeBomb and
DroppedSpikes over Munition and DroppedBomb, which are Smokeables; the
explosions' MunitionEffectsHandler; InitMunitions and CloseMunitions. The
model runs the retail MIPS (0x001be4b8 .. 0x001bfe98) in mipsemu over the
smokeable checker's model, which stubs what a smokeable calls; this one
adds the munitions' pools, the effects handler's bMalloc, and stubs for
what the munitions call beyond the smokeables:

    hmalloc      bMalloc (0x002577c0), the handler; 8 bytes, named MEH%d
    bfree        __builtin_delete (0x00114e98)
    explosion    PlayExplosion (0x001e56f0)
    nearest      GetNearestRoutePoint (0x001cb7a0), answers from `near`
    spikes       tCopManager::AddSpikeStrip (0x002276d0)
    wreck        CarDamage's wreck (0x001b5bc8)
    ebrake       RealDriver::ForceEBrakeStop (0x0013b558)
    zone         Player::RequestZone (0x00177c88), returns 1
    normalize    bNormalize (0x00258958): x + len, y - len, z / 2, w left
    scaleadd     bScaleAdd (0x002589d8): x from a plus s, y from b less s
    atan         bATan (0x0025a890), from `atan` or the bits of x and y
    relangle     MakeRelativeAngle (0x00231478)
    roty, rotz   eRotateY / eRotateZ (0x0011b950, 0x0011ba18): one cell
                 of the matrix moved by the BAM
    dynbackup    DynamicCollisionBody::Backup (0x001d7660)
    physmode,    the cars' bodies' table, slots 112 and 128
    carimpulse

tools/src/munition_test.c runs the same script on the port (with
smokeable.c and smokeableinfo.c) and prints the same lines. The script
covers the module's init and close, the creators, the three classes'
constructors, launches, Moves (a SmokeBomb's collisions with cars, the
spikes deployed, a rocket backed up, turning within and past its limit,
climbing within and past it), the warhead on each kind of car, the spike
belt's branches, the effects handler, and the destructors.

    python tools/munition_check.py
    python tools/munition_check.py --model-only
    python tools/munition_check.py --mutate [--only a,b]
    python tools/munition_check.py --dump out/munition
"""
import argparse
import os
import struct
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mutpar                           # noqa: E402
import smokeable_check as sc            # noqa: E402
from mipsemu import M32, s32            # noqa: E402

NL = chr(10)
HARNESS = "tools/src/munition_test.c"
MUN = "3DS Files/source/munition.c"
SOURCES = [HARNESS, sc.SMOKE, sc.SINFO, "3DS Files/source/vtable.c",
           "3DS Files/source/bprintf.c", MUN]
NAME = "munition_test"

# The Collision the smokeable checker makes: Sample at 88 needs its size.
sc.COL_SIZE = 112

GP = sc.GP
G_RKP = GP - 18440                      # RocketSlotPool
G_SBP = GP - 18436                      # SmokeBombSlotPool
G_DSP = GP - 18432                      # DroppedSpikesSlotPool
G_RKE = GP - 18424                      # RocketEmitters
G_SBE = GP - 18416                      # SmokeBombEmitters
G_DSE = GP - 18408                      # DroppedSpikesEmitters
G_HANDLER = GP - 18384                  # TheMunitionEffectsHandler
G_GLARE = GP - 23568                    # bStartGlare
G_COPMGR = GP - 15620                   # pCopManager

F_INITMUN = 0x001be638
F_CLOSEMUN = 0x001be680
F_MDTOR = 0x001be710
F_EXPLODE = 0x001be778
F_FLAT = 0x001bea70
F_DBDTOR = 0x001beb20
F_SBCTOR = 0x001beb90
F_DSCTOR = 0x001bee88
F_BELT = 0x001bf188
F_RKCTOR = 0x001bf340
F_RLAUNCH = 0x001bf528
F_EFFTICK = 0x001bfa38
F_ADDEFF = 0x001bfad0
F_RKNEW = 0x001bfd70
F_DSNEW = 0x001bfdf0
F_SBNEW = 0x001bfe70
F_BLAUNCH = 0x001bfe90
C_ROCKET = 0x001be4b8
C_SMOKEBOMB = 0x001be538
C_SPIKES = 0x001be5b8

PARAMS = {"sb": 0x003143d8, "ds": 0x003143f8, "rk": 0x00314418}

S_HMALLOC = 0x002577c0
S_BDELETE = 0x00114e98
S_EXPLOSION = 0x001e56f0
S_NEAREST = 0x001cb7a0
S_SPIKES = 0x002276d0
S_WRECK = 0x001b5bc8
S_EBRAKE = 0x0013b558
S_ZONE = 0x00177c88
S_NORMALIZE = 0x00258958
S_SCALEADD = 0x002589d8
S_ATAN = 0x0025a890
S_RELANGLE = 0x00231478
S_ROTY = 0x0011b950
S_ROTZ = 0x0011ba18
S_DYNBACKUP = 0x001d7660

# The tables: (tag, main, system).
VTABLES = (("mun", 0x002b7120, 0x002b7100), ("db", 0x002b7020, 0x002b7000),
           ("sb", 0x002b6f20, 0x002b6f00), ("ds", 0x002b6e20, 0x002b6e00),
           ("rk", 0x002b6d20, 0x002b6d00))

# Munition: BackupDone at 1136; DroppedSpikes' DeploySpikes and Rocket's
# Target at 1152, Rocket's Yaw at 1156.
SIZES = {"RK": 1168, "SB": 1152, "DS": 1168}
CAR_SIZE, TP_SIZE, WORLD_SIZE = 2200, 112, 256


def fbits(f):
    return sc.fbits(f)


def bitsf(u):
    return sc.bitsf(u)


def f32(x):
    return bitsf(fbits(x))


def mun_names():
    n = sc.retail_names()
    n[0x001bed20] = "OnLifetimeEnd__9SmokeBomb"
    n[0x001bf078] = "OnLifetimeEnd__13DroppedSpikes"
    n[0x001bf4d0] = "OnLifetimeEnd__6Rocket"
    return n


# ================================================================== model

class Model(sc.Model):
    def __init__(self):
        sc.Model.__init__(self)
        e = self.e
        self.nearq, self.atanq = [], []
        self.ncars = 0
        self.saved_handler = 0

        def tok(n, size=16):
            p = e.alloc(size, align=16)
            e.write(p, bytes(size))
            self.name(p, n)
            return p

        for a in (G_RKP, G_SBP, G_DSP, G_HANDLER, G_GLARE):
            e.put32(a, 0)
        for a, n in ((G_RKE, "RKE"), (G_SBE, "SBE"), (G_DSE, "DSE")):
            e.put32(a, a)
            e.put32(a + 4, a)
            self.name(a, n)
        self.rkp, self.sbp, self.dsp = tok("RKP"), tok("SBP"), tok("DSP")
        self.cm, self.smp = tok("CM"), tok("SMP")
        e.put32(G_COPMGR, self.cm)
        self.mworld = self.block(WORLD_SIZE, fill=0)
        self.name(self.mworld, "W")
        e.put32(sc.G_WORLD, self.mworld)
        # The cars' bodies' table: SetToPhysicsMode and ApplyImpulse.
        self.carvt = self.block(8 * 17, fill=0)
        for slot, fn in ((112, self.s_physmode), (128, self.s_carimpulse)):
            t = tok("CARVT%d" % slot)
            e.stub(t, fn)
            e.put32(self.carvt + slot + 4, t)
        for a, fn in ((S_HMALLOC, self.s_hmalloc),
                      (S_BDELETE, self.s_bdelete),
                      (S_EXPLOSION, self.s_explosion),
                      (S_NEAREST, self.s_nearest),
                      (S_SPIKES, self.s_spikes), (S_WRECK, self.s_wreck),
                      (S_EBRAKE, self.s_ebrake), (S_ZONE, self.s_zone),
                      (S_NORMALIZE, self.s_normalize),
                      (S_SCALEADD, self.s_scaleadd), (S_ATAN, self.s_atan),
                      (S_RELANGLE, self.s_relangle), (S_ROTY, self.s_roty),
                      (S_ROTZ, self.s_rotz),
                      (S_DYNBACKUP, self.s_dynbackup)):
            e.stub(a, fn)

    # ---- the pools

    def s_newpool(self, em):
        n = self.cstr(em.reg[6] & M32)
        t = {"RocketSlotPool": self.rkp, "SmokeBombSlotPool": self.sbp,
             "DroppedSpikesSlotPool": self.dsp}.get(n)
        if t is None:
            return sc.Model.s_newpool(self, em)
        self.emit("  newpool %d %d %s %d" % (s32(em.reg[4]), s32(em.reg[5]),
                                            n, s32(em.reg[7])))
        return t

    def s_omalloc(self, em):
        pool = em.reg[4] & M32
        pfx = {self.rkp: "RK", self.sbp: "SB", self.dsp: "DS"}.get(pool)
        if pfx is None:
            return sc.Model.s_omalloc(self, em)
        p = self.block(SIZES[pfx])
        n = self.next_name(pfx)
        self.name(p, n)
        for off, sfx in ((256, "sys"), (304, "tc"), (1008, "wo"),
                         (1040, "m"), (1104, "al"), (1112, "dl")):
            self.name(p + off, "%s.%s" % (n, sfx))
        self.emit("  omalloc %s -> %s" % (self.sym(pool), self.sym(p)))
        return p

    def s_hmalloc(self, em):
        p = self.block(16)
        self.name(p, self.next_name("MEH"))
        self.emit("  hmalloc %d %s %d %d -> %s" % (
            s32(em.reg[4]), self.cstr(em.reg[5] & M32), s32(em.reg[6]),
            s32(em.reg[7]), self.sym(p)))
        return p

    def s_bdelete(self, em):
        self.emit("  bfree %s" % self.sym(em.reg[4]))

    # ---- the munitions' stubs

    def s_dynbackup(self, em):
        self.emit("  dynbackup %s %08x" % (self.sym(em.reg[4]),
                                           em.fpr[12] & M32))

    def s_explosion(self, em):
        self.emit("  explosion%s" % self.words(em.reg[4] & M32, 3))

    def s_nearest(self, em):
        e = self.e
        info, pos = em.reg[4] & M32, em.reg[5] & M32
        r, pt = self.nearq.pop(0) if self.nearq else (0, 0)
        self.emit("  nearest %s%s %d %d %08x -> %d %s" % (
            self.sym(pos), self.words(pos, 2), s32(em.reg[6]),
            s32(em.reg[7]), em.fpr[12] & M32, r, self.sym(pt)))
        if r:
            e.put32(info, self.xp)
            e.put32(info + 4, pt)
        return r

    def s_normalize(self, em):
        e = self.e
        o, v = em.reg[4] & M32, em.reg[5] & M32
        ln = em.fpr[12] & M32
        x, y, z = (bitsf(e.u32(v + 4 * i)) for i in range(3))
        self.emit("  normalize %s%s %08x" % (self.sym(v), self.words(v, 4),
                                            ln))
        e.put32(o, fbits(x + bitsf(ln)))
        e.put32(o + 4, fbits(y - bitsf(ln)))
        e.put32(o + 8, fbits(z * 0.5))

    def s_scaleadd(self, em):
        e = self.e
        o, a, b = (em.reg[r] & M32 for r in (4, 5, 6))
        s = em.fpr[12] & M32
        x = fbits(bitsf(e.u32(a)) + bitsf(s))
        y = fbits(bitsf(e.u32(b + 4)) - bitsf(s))
        self.emit("  scaleadd %s%s%s %08x" % (self.sym(a), self.words(a, 2),
                                             self.words(b, 2), s))
        e.put32(o, x)
        e.put32(o + 4, y)

    def s_atan(self, em):
        x, y = em.fpr[12] & M32, em.fpr[13] & M32
        if self.atanq:
            v = self.atanq.pop(0)
        else:
            v = ((x >> 7) ^ (y >> 3)) & 0xffff
        self.emit("  atan %08x %08x -> %d" % (x, y, v))
        return v

    def s_relangle(self, em):
        deg = em.fpr[12] & M32
        d = bitsf(deg)
        while 180.0 < d:
            d = f32(d - 360.0)
        while d < -180.0:
            d = f32(d + 360.0)
        self.emit("  relangle %08x -> %08x" % (deg, fbits(d)))
        em.fpr[0] = fbits(d)

    def rotate(self, em, n, k, sign):
        e = self.e
        o, m = em.reg[4] & M32, em.reg[5] & M32
        bam = em.reg[6] & 0xffff
        r = [e.u32(m + 4 * i) for i in range(16)]
        self.emit("  %s %s%s %d" % (n, self.sym(m), self.words(m, 16), bam))
        r[k] = fbits(bitsf(r[k]) + sign * float(bam))
        for i in range(16):
            e.put32(o + 4 * i, r[i])

    def s_roty(self, em):
        self.rotate(em, "roty", 2, 1.0)

    def s_rotz(self, em):
        self.rotate(em, "rotz", 4, -1.0)

    def s_wreck(self, em):
        self.emit("  wreck %s" % self.sym(em.reg[4]))

    def s_ebrake(self, em):
        self.emit("  ebrake %s %08x" % (self.sym(em.reg[4]),
                                        em.fpr[12] & M32))

    def s_zone(self, em):
        self.emit("  zone %s %d %d %d %d" % (
            self.sym(em.reg[4]), s32(em.reg[5]), s32(em.reg[6]),
            s32(em.reg[7]), s32(em.reg[8])))
        return 1

    def s_spikes(self, em):
        self.emit("  spikes %s%s%s %d %08x" % (
            self.sym(em.reg[4]), self.words(em.reg[5] & M32, 2),
            self.words(em.reg[6] & M32, 2), s32(em.reg[7]),
            em.fpr[12] & M32))

    def s_physmode(self, em):
        self.emit("  physmode %s %s" % (self.sym(em.reg[4]),
                                        self.sym(em.reg[5])))

    def s_carimpulse(self, em):
        self.emit("  carimpulse %s%s%s" % (self.sym(em.reg[4]),
                                           self.words(em.reg[5] & M32, 4),
                                           self.words(em.reg[6] & M32, 3)))

    # ---- the cars

    def set_car(self, c, k, a):
        e = self.e
        e.put32(c + 32, int(a[0], 0))
        e.put32(c + 36, int(a[1], 0))
        self.fset(c + 96, a[2:6])
        e.put32(c + 956, int(a[6], 0))
        if int(a[7], 0):
            p = self.block(16, fill=0)
            self.name(p, "Q%dp" % k)
        else:
            p = 0
        e.put32(c + 24, p)
        if int(a[8], 0):
            p = self.block(16, fill=0)
            self.name(p, "Q%dx" % k)
        else:
            p = 0
        e.put32(c + 2120, p)
        self.put16(e.u32(c + 28) + 18, int(a[9], 0))

    def make_car(self, a):
        e = self.e
        k = self.ncars
        c = self.block(CAR_SIZE, fill=0)
        b = self.block(96, fill=0)
        self.name(c, "Q%d" % k)
        self.name(b, "Q%db" % k)
        e.put32(b + 80, self.carvt)
        e.put32(c + 52, b)
        d = self.block(600, fill=0)
        self.name(d, "Q%dd" % k)
        e.put32(c + 44, d)
        r = self.block(32, fill=0)
        self.name(r, "Q%dr" % k)
        e.put32(c + 28, r)
        self.set_car(c, k, a)
        self.ncars += 1
        w = self.mworld
        n = e.u32(w + 28)
        e.put32(w + 44 + 4 * n, c)
        e.put32(w + 28, n + 1)

    # ---- dumps

    def dump_mvt(self):
        e = self.e
        if self.rnames is None:
            self.rnames = mun_names()
        for tag, main, system in VTABLES:
            for t, vt, n in ((tag, main, 28), (tag + "sys", system, 4)):
                s = "vt %s" % t
                for i in range(n):
                    d, _ix, fn = struct.unpack_from("<hhI", e.mem, vt + 8 * i)
                    nm = "-" if fn == 0 else sc.port_name(self.rnames.get(fn))
                    s += " %d:%d:%s" % (8 * i, d, nm)
                self.emit(s)

    def dump_mcreators(self):
        names = {0: "0", sc.F_BASIC: "basic", C_ROCKET: "rocket",
                 C_SMOKEBOMB: "smokebomb", C_SPIKES: "spikes"}
        self.emit("creators %s" % " ".join(
            names.get(self.e.u32(sc.CREATORS + 4 * k), "?")
            for k in range(4)))

    def dump_mglob(self):
        e = self.e
        h = e.u32(G_HANDLER)
        s = "mglob pools %s %s %s handler %s glare %d rke%s sbe%s dse%s" % (
            self.sym(e.u32(G_RKP)), self.sym(e.u32(G_SBP)),
            self.sym(e.u32(G_DSP)), self.sym(h), s32(e.u32(G_GLARE)),
            self.tlist(G_RKE), self.tlist(G_SBE), self.tlist(G_DSE))
        if h:
            s += " list" + self.plist(h)
        self.emit(s)

    # ---- ops

    def op(self, a):
        e = self.e
        o = a[0]
        if o == "initmun":
            self.emit("initmun")
            e.call(F_INITMUN)
        elif o == "closemun":
            self.emit("closemun")
            e.call(F_CLOSEMUN)
        elif o == "mvt":
            self.dump_mvt()
        elif o == "mcreators":
            self.dump_mcreators()
        elif o == "mglob":
            self.dump_mglob()
        elif o == "params":
            self.emit("params %s%s" % (a[1], self.words(PARAMS[a[1]], 7)))
        elif o == "car":
            self.make_car(a[1:])
        elif o == "carmod":
            c = self.ref(a[1])
            self.set_car(c, int(a[1][1:]), a[2:])
        elif o == "cd":
            c = self.ref(a[1])
            self.emit("car %s ebrake %08x" % (a[1],
                                              e.u32(e.u32(c + 44) + 592)))
        elif o == "colm":
            k = self.ref(a[1])
            e.put32(k + 88, self.smp if int(a[2], 0) else 0)
            self.fset(k + 16, a[3:6])
        elif o in ("sbnew", "dsnew", "rknew"):
            new, ctor = {"sbnew": (F_SBNEW, F_SBCTOR),
                         "dsnew": (F_DSNEW, F_DSCTOR),
                         "rknew": (F_RKNEW, F_RKCTOR)}[o]
            self.emit(o)
            p = e.call(new)
            r = e.call(ctor, p)
            self.emit("  -> %s" % self.sym(r))
        elif o == "blaunch":
            m, v = self.vec(a[2:18], 16), self.vec(a[18:22])
            self.emit("blaunch %s" % a[1])
            e.call(F_BLAUNCH, self.ref(a[1]), m, v)
        elif o == "rlaunch":
            m, v = self.vec(a[2:18], 16), self.vec(a[18:22])
            self.emit("rlaunch %s %s" % (a[1], a[22]))
            e.call(F_RLAUNCH, self.ref(a[1]), m, v, self.ref(a[22]))
        elif o == "explode":
            self.emit("explode %s %s %s" % (a[1], a[2], a[3]))
            e.call(F_EXPLODE, self.ref(a[1]), PARAMS[a[2]], int(a[3], 0))
        elif o == "belt":
            self.emit("belt %s" % a[1])
            e.call(F_BELT, self.ref(a[1]))
        elif o == "flat":
            m = self.vec(["0"] * 16, 16)
            e.call(F_FLAT, self.ref(a[1]), m)
            self.emit("flat %s%s" % (a[1], self.words(m, 16)))
        elif o == "backup":
            self.emit("backup %s %s" % (a[1], a[2]))
            self.vcall(self.ref(a[1]), 72, fargs=(int(a[2], 16),))
        elif o == "lifeend":
            self.emit("lifeend %s" % a[1])
            self.vcall(self.ref(a[1]), 216)
        elif o == "smoketype":
            r = self.vcall(self.ref(a[1]), 208)
            self.emit("smoketype %s -> %d" % (a[1], s32(r)))
        elif o in ("mdtor", "dbdtor"):
            self.emit("%s %s %s" % (o, a[1], a[2]))
            e.call(F_MDTOR if o == "mdtor" else F_DBDTOR, self.ref(a[1]),
                   int(a[2], 0))
        elif o == "efftick":
            self.emit("efftick %s" % a[1])
            e.fpr[12] = int(a[1], 16)
            e.call(F_EFFTICK, e.u32(G_HANDLER))
        elif o == "addeff":
            m = self.vec(a[2:18], 16)
            self.emit("addeff %s" % a[1])
            e.call(F_ADDEFF, e.u32(G_HANDLER), self.ref(a[1]), m)
        elif o == "es":
            e.put32(self.ref(a[1]) + 16, int(a[2], 0))
        elif o == "addem":
            lst = self.ref(a[1])
            for _ in range(int(a[2], 0)):
                p = self.block(sc.EMITTER_SIZE)
                self.name(p, self.next_name("E"))
                tail = e.u32(lst + 4)
                e.put32(tail, p)
                e.put32(lst + 4, p)
                e.put32(p + 4, tail)
                e.put32(p, lst)
        elif o == "md":
            m = self.ref(a[1])
            self.emit("mun %s bd %d" % (a[1], s32(e.u32(m + 1136))))
        elif o == "mds":
            m = self.ref(a[1])
            self.emit("spikes %s bd %d deploy %d" % (
                a[1], s32(e.u32(m + 1136)), s32(e.u32(m + 1152))))
        elif o == "mdr":
            m = self.ref(a[1])
            self.emit("rocket %s bd %d target %s yaw %08x" % (
                a[1], s32(e.u32(m + 1136)), self.sym(e.u32(m + 1152)),
                e.u32(m + 1156)))
        elif o == "mf":
            m = self.ref(a[1])
            if a[2] == "bd":
                e.put32(m + 1136, int(a[3], 0))
            elif a[2] == "deploy":
                e.put32(m + 1152, int(a[3], 0))
            elif a[2] == "target":
                e.put32(m + 1152, self.ref(a[3]))
            elif a[2] == "yaw":
                e.put32(m + 1156, int(a[3], 16))
            else:
                raise ValueError("munition field %s" % a[2])
        elif o == "tp":
            p = self.block(TP_SIZE, fill=0)
            self.name(p, self.next_name("TP"))
            self.fset(p, a[1:3])
            self.fset(p + 12, a[3:5])
            self.fset(p + 24, a[5:7])
        elif o == "near":
            self.nearq.append((int(a[1], 0), self.ref(a[2])))
        elif o == "atan":
            self.atanq += [int(x, 0) for x in a[1:]]
        elif o == "glare":
            e.put32(G_GLARE, int(a[1], 0))
        elif o == "hnull":
            self.saved_handler = e.u32(G_HANDLER)
            e.put32(G_HANDLER, 0)
        elif o == "hback":
            e.put32(G_HANDLER, self.saved_handler)
        else:
            sc.Model.op(self, a)


def model(lines):
    return Model().run(lines)


# ================================================================== script

F = sc.F
vec4 = sc.vec4
mat16 = sc.mat16
placed = sc.placed
elev = sc.elev
timer = sc.timer

H_CSSB = sc.hash_from("CS_SMOKEBOMB", M32)
H_CSRK = sc.hash_from("CS_Rocket", M32)


def car(ctl, mv, x, y, z=0.0, w=1.0, wheels=4, player=0, damage=0,
        finish=0):
    return "car|%d|%d|%s|%d|%d|%d|%d" % (ctl, mv, vec4(x, y, z, w), wheels,
                                         player, damage, finish)


def carmod(q, ctl, mv, x, y, z=0.0, w=1.0, wheels=4, player=0, damage=0,
           finish=0):
    return "carmod|%s|%d|%d|%s|%d|%d|%d|%d" % (q, ctl, mv,
                                               vec4(x, y, z, w), wheels,
                                               player, damage, finish)


def module():
    s = ["mvt", "params|sb", "params|ds", "params|rk", "mglob",
         "mcreators", "initmun", "mglob", "mcreators"]
    # The infos the constructors look for; DroppedSpikes uses the smoke
    # bomb's.
    s += sc.info("CS_SMOKEBOMB", H_CSSB, ah=0x00a00003, dh=0x00a00001,
                 com=(0.0, 0.0, 0.25), life=4.0, th=0x6666, mass=5.0)
    s += sc.info("CS_Rocket", H_CSRK, ah=0x00b00002, dh=0,
                 com=(0.0, 0.0, 0.0), life=8.0, th=0x6667, mass=2.0)
    s += ["load", "infos"]
    return s


def making():
    s = ["sbnew", "sd|SB0", "md|SB0", "dsnew", "sd|DS0", "mds|DS0",
         "rknew", "sd|RK0", "mdr|RK0", "cbl", "stats"]
    # Through the creators' table, as a replay or the chopper makes them.
    s += ["create|2|77|I0|beef0001", "create|3|78|I0|beef0002",
          "create|1|79|I1|beef0003", "sd|SB1", "sd|DS1", "mds|DS1",
          "sd|RK1", "mdr|RK1"]
    s += ["smoketype|SB0", "smoketype|DS0", "smoketype|RK0"]
    return s


def cars():
    # Q0: a player's car at hand, on its wheels, with damage: the hard
    # hit. Q1: an AI car on mellow movement 5 away. Q2: not moving. Q3:
    # 6 away, out of range. Q4: an AI car on another movement, 4 away.
    # Q5: a player's car 4.5 away: a soft hit. Q6: a player's car on AI
    # control, finished, no damage, 3 away: hard hit, nothing to do. Q7:
    # a player's car 4 away, struck with exactly 0.8 of the strength:
    # soft. Q8: a car on real control with no player, 2 away.
    return [car(1, 1, 11.0, 20.0, 0.5, 1.0, 4, 1, 1, 0),
            car(2, 4, 13.0, 24.0, 2.0, 1.0, 0, 0, 0, 0),
            car(1, 0, 10.0, 20.0, 0.0, 1.0, 4, 1, 1, 0),
            car(2, 1, 10.0, 26.0, 0.0, 1.0, 4, 0, 0, 0),
            car(2, 2, 10.0, 16.0, 0.0, 0.5, 2, 0, 0, 0),
            car(1, 1, 10.0, 15.5, 0.0, 1.0, 4, 1, 1, 0),
            car(2, 1, 7.0, 20.0, 0.0, 1.0, 4, 1, 0, 1),
            car(1, 1, 10.0, 24.0, 0.0, 1.0, 4, 1, 1, 0),
            car(1, 1, 10.0, 22.0, 0.0, 1.0, 4, 0, 0, 0)]


def launching():
    s = cars()
    # The smoke bomb dropped at (10, 20, 1).
    s += ["blaunch|SB0|%s|%s" % (placed(10.0, 20.0, 1.0),
                                 vec4(1.0, -2.0, -0.5, 0.0)),
          "sd|SB0", "md|SB0", "flat|SB0", "cbl", "stats"]
    s += ["blaunch|DS0|%s|%s" % (placed(10.0, 20.0, 0.25),
                                 vec4(0.0, 0.0, -1.0, 0.0)),
          "sd|DS0", "mds|DS0"]
    # The rocket: its yaw from the velocity, 45 degrees, then -135 from
    # an answer past 180.
    s += ["atan|8192", "rlaunch|RK0|%s|%s|Q0" % (placed(0.0, 0.0, 5.0),
                                                  vec4(3.0, 4.0, 0.0, 0.0)),
          "sd|RK0", "mdr|RK0"]
    s += ["atan|40960", "rlaunch|RK1|%s|%s|0" % (placed(1.0, 2.0, 3.0),
                                                  vec4(-3.0, -3.0, 0.0, 0.0)),
          "mdr|RK1"]
    return s


def warhead():
    s = ["explode|SB0|sb|0"]
    s += ["cd|Q%d" % k for k in range(9)]
    # A rocket's: the glare in a one-player race only; no zone camera.
    s += ["explode|SB0|rk|1", "mglob", "glare|0", "rp|2",
          "explode|SB0|rk|1", "mglob", "rp|1"]
    # The spikes': exactly at MinRange, just inside it and exactly
    # MaxRange away; an AI car on physics movement braked.
    s += [carmod("Q1", 2, 1, 12.0, 20.0, 0.0, 1.0, 0, 0, 0, 0),
          carmod("Q3", 1, 1, 10.0, 28.0, 0.0, 1.0, 4, 1, 0, 0),
          carmod("Q4", 2, 1, 14.0, 20.0, 0.0, 1.0, 4, 0, 0, 0),
          carmod("Q8", 1, 1, 11.75, 20.0, 0.0, 1.0, 4, 0, 0, 0),
          "explode|SB0|ds|2", "cd|Q1", "cd|Q4", "cd|Q8",
          carmod("Q8", 1, 1, 10.0, 22.0, 0.0, 1.0, 4, 0, 0, 0)]
    # An AI car with no movement, then none at all.
    s += [carmod("Q1", 2, 0, 12.0, 20.0, 0.0, 1.0, 0, 0, 0, 0),
          "explode|SB0|sb|0"]
    return s


def moving():
    s = []
    # A smoke bomb backed up: its collisions not looked at.
    s += [timer(0x1000), "backup|SB0|%s" % F(0.25), "md|SB0", "sf|SB0|ncol|1",
          "col|SB0|0|00000800|A0|0", "move|SB0|%s" % F(0.02), "md|SB0",
          "sd|SB0"]
    # Its collisions with no car; then with a car on the second, which has
    # a sample: no sound.
    s += ["sf|SB0|ncol|2", "col|SB0|0|00000800|0|0",
          "col|SB0|1|00000800|0|0", "move|SB0|%s" % F(0.02), "md|SB0"]
    s += ["col|SB0|1|00000900|0|A1",
          "colm|K3|1|%s" % "|".join(F(v) for v in (1.0, 2.0, 3.0)),
          "move|SB0|%s" % F(0.02), "cbl", "stats", "mglob"]
    s += ["ed|C%d" % k for k in range(3)]
    # SB1 hit with no sample: the smokeable's crash sound.
    s += ["blaunch|SB1|%s|%s" % (placed(30.0, 40.0, 2.0),
                                 vec4(0.0, 0.0, 0.0, 0.0)),
          "sf|SB1|ncol|1", "col|SB1|0|00000a00|A0|0",
          "colm|K4|0|%s" % "|".join(F(v) for v in (4.0, 5.0, 6.0)),
          "cnull|E1", "move|SB1|%s" % F(0.02), "cbl", "mglob"]
    # The spikes: an impulse deploys them; backed up, the Move goes on.
    s += ["impulse|DS0|%s|%s" % (vec4(1.0, 2.0, 3.0, 0.0),
                                 vec4(0.0, 0.0, 0.0, 0.0)), "mds|DS0",
          "backup|DS0|%s" % F(0.125), "move|DS0|%s" % F(0.02), "mds|DS0",
          "mf|DS0|deploy|0", "apply|DS0|%s|%s" % (vec4(1.0, 0.0, 0.0, 0.0),
                                                 vec4(0.0, 0.0, 0.0, 0.0)),
          "mds|DS0", "mf|DS0|deploy|0", "move|DS0|%s" % F(0.02), "mds|DS0"]
    return s


def belt():
    s = ["addem|DSE|2", "mglob"]
    # DS1 placed at (40, 50, 0.5).
    s += ["blaunch|DS1|%s|%s" % (placed(40.0, 50.0, 0.5),
                                 vec4(0.0, 0.0, 0.0, 0.0))]
    # No ground; too high over it; no route point.
    s += [elev(0, 0.0), "belt|DS1", elev(1, -0.75), "belt|DS1",
          elev(1, 0.0), "near|0|0", "belt|DS1"]
    # Points heading +y at x 38 (the spikes 2 to the right of it) and at
    # x 41 (1 to the left), widths 3 and 1.5.
    s += ["tp|%s|%s|%s|%s" % (vec4(38.0, 48.0), vec4(0.0, 1.0), F(2.5),
                               F(3.0)),
          "tp|%s|%s|%s|%s" % (vec4(41.0, 48.0), vec4(0.0, 1.0), F(1.5),
                               F(1.5)),
          "tp|%s|%s|%s|%s" % (vec4(38.5, 48.0), vec4(0.0, 1.0), F(1.0),
                               F(1.0)),
          "tp|%s|%s|%s|%s" % (vec4(40.0, 48.0), vec4(0.6, 0.8), F(2.5),
                               F(0.5)),
          "tp|%s|%s|%s|%s" % (vec4(42.0, 50.0), vec4(0.0, 1.0), F(2.0),
                               F(2.0)),
          "tp|%s|%s|%s|%s" % (vec4(40.0, 46.0), vec4(0.0, 1.0), F(1.25),
                               F(4.0))]
    # Right, inside: 1 to the edge; left, inside: 0.5 to the edge.
    s += [elev(1, 0.0), "near|1|TP0", "belt|DS1"]
    s += [elev(1, 0.0), "near|1|TP1", "belt|DS1"]
    # Right, past the edge; left across a slanted point; exactly on the
    # left edge; on the line.
    s += [elev(1, 0.0), "near|1|TP2", "belt|DS1"]
    s += [elev(1, 0.0), "near|1|TP3", "belt|DS1"]
    s += [elev(1, 0.0), "near|1|TP4", "belt|DS1"]
    s += [elev(1, 0.0), "near|1|TP5", "belt|DS1"]
    # Exactly a unit over the ground: laid.
    s += [elev(1, -0.25), "near|1|TP0", "belt|DS1"]
    # Deployed, its Move sets it off: the explosion and the belt.
    s += ["mf|DS1|deploy|1", elev(1, 0.0), "near|1|TP0",
          "move|DS1|%s" % F(0.02), "cbl", "stats", "mglob"]
    return s


def rocket():
    s = []
    # Backed up: the Move only clears the flag.
    s += [timer(0x2000), "backup|RK0|%s" % F(0.5), "mdr|RK0",
          "move|RK0|%s" % F(0.03), "mdr|RK0"]
    # Toward Q0 at (11, 20): a turn within 90 a second, climbing within
    # the limit.
    s += ["mf|RK0|yaw|%s" % F(60.0), elev(1, 4.5), "atan|10923|1200",
          "move|RK0|%s" % F(0.5), "mdr|RK0", "sd|RK0", "rd|R%d" % 2]
    # A turn past the limit, either way; a climb past it up and down.
    s += ["mf|RK0|yaw|%s" % F(-170.0), elev(1, 20.0), "atan|8192|3000",
          "move|RK0|%s" % F(0.1), "mdr|RK0"]
    s += ["mf|RK0|yaw|%s" % F(170.0), elev(1, -30.0), "atan|-24576|60000",
          "move|RK0|%s" % F(0.1), "mdr|RK0"]
    # The answers' own bits.
    s += [elev(1, 2.0), "move|RK0|%s" % F(0.05), "mdr|RK0", "sd|RK0"]
    # Struck: the target dropped, then set off by the next Move.
    s += ["impulse|RK0|%s|%s" % (vec4(5.0, 0.0, 0.0, 0.0),
                                 vec4(0.0, 0.0, 0.0, 0.0)), "mdr|RK0",
          "mf|RK0|target|Q0", "apply|RK0|%s|%s" % (vec4(0.0, 1.0, 0.0, 0.0),
                                                   vec4(0.0, 0.0, 0.0, 0.0)),
          "mdr|RK0", "addem|RKE|2", "move|RK0|%s" % F(0.05), "cbl", "stats",
          "mglob"]
    return s


def effects():
    s = []
    # The handler's step: the emitters not on dropped.
    s += ["es|C0|0", "es|C4|2", "efftick|%s" % F(0.02), "mglob"]
    # No handler: nothing goes off.
    s += ["hnull", "lifeend|DS0", "lifeend|RK1", "mglob", "hback"]
    # Added by hand, one copy failing.
    s += ["cnull|E3", "addeff|DSE|%s" % placed(1.0, 2.0, 3.0), "mglob"]
    s += ["efftick|%s" % F(0.0), "mglob"]
    # The spikes going off among the cars: no glare, no route point.
    s += ["glare|0", "lifeend|DS0", "mglob"]
    # A rocket among them outliving its eight seconds: Move's timers set
    # it off, with the glare.
    s += [timer(0x1000), "atan|0",
          "rlaunch|RK1|%s|%s|Q0" % (placed(10.0, 21.0, 1.0),
                                    vec4(1.0, 0.0, 0.0, 0.0)),
          timer(0x8e00), elev(1, 0.5), "move|RK1|%s" % F(0.02), "cbl",
          "stats", "mglob"]
    return s


def dtors():
    s = ["create|2|90|I0|beef0004", "create|3|91|I0|beef0005",
         "create|1|92|I1|beef0006", "create|2|93|I0|beef0007",
         "create|3|94|I0|beef0008", "create|1|95|I1|beef0009",
         "create|2|96|I0|beef000a", "create|3|97|I0|beef000b", "cbl"]
    # The base classes' destructors, keeping the slot and freeing it to
    # the smokeables' pool; the classes' own through the tables.
    s += ["dbdtor|SB2|0", "mdtor|DS2|0", "dbdtor|SB3|1", "mdtor|DS3|1",
          "cbl", "stats"]
    s += ["del|RK2|1", "del|DS0|3", "sysdel|RK3|1", "sysdel|SB4|1",
          "sysdel|DS4|0", "cbl", "stats"]
    s += ["closemun", "mglob", "mcreators", "closemun", "mglob"]
    return s


def script():
    return (module() + making() + launching() + warhead() + moving()
            + belt() + rocket() + effects() + dtors())


# ================================================================== build

def build_harness(tmp, name=NAME):
    return sc.hostbuild.build(tmp, SOURCES, name=name)


run_harness = sc.run_harness
diff = sc.diff
write_script = sc.write_script


# ============================================================= mutations

M = MUN
MUTATIONS = [
    # The module.
    ("params-sb", M, "{ 25, 10, 10, 5, 3, 6, 1 }", "{ 25, 10, 10, 5, 3, 6, 0 }"),
    ("params-ds", M, "{ 1, 0, 10, 5, 2, 8, 0 }", "{ 1, 0, 10, 5, 2, 7, 0 }"),
    ("params-rk", M, "{ 20, 20, 10, 8, 0, 6, 0 }", "{ 20, 20, 10, 8, 0, 6, 1 }"),
    ("sb-pool-slots", M, "(int)sizeof(SmokeBomb), 14,",
     "(int)sizeof(SmokeBomb), 15,"),
    ("rk-pool-slots", M, "(int)sizeof(Rocket), 3,", "(int)sizeof(Rocket), 4,"),
    ("ds-pool-slots", M, "(int)sizeof(DroppedSpikes), 8,",
     "(int)sizeof(DroppedSpikes), 9,"),
    ("sb-pool-num", M, "\"SmokeBombSlotPool\", 16);",
     "\"SmokeBombSlotPool\", 15);"),
    ("sb-creator-type", M,
     "smokeable_register_creator(ST_SMOKEBOMB, smokebomb_smokeable_creator);",
     "smokeable_register_creator(ST_ROCKET, smokebomb_smokeable_creator);"),
    ("sb-emitters-list", M, "afx_get_emitters(&SmokeBombEmitters,",
     "afx_get_emitters(&RocketEmitters,"),
    ("ds-emitters-hash", M,
     "afx_get_emitters(&DroppedSpikesEmitters, bchunk_hash(\"ROCKETEXPLD\"));",
     "afx_get_emitters(&DroppedSpikesEmitters, "
     "bchunk_hash(\"SMOKEBOMBEXPLD\"));"),
    ("fini-keep-pool", M, "        *pool = NULL;\n", ""),
    ("fini-keep-emitters", M, "    afx_delete_emitters(emitters);\n}", "}"),
    ("hmalloc-pool", M, "\"MunitionEffectsHandler\", 0,\n        16);",
     "\"MunitionEffectsHandler\", 0,\n        15);"),
    ("init-handler-prev", M, "    h->List.prev = &h->List;\n", ""),
    ("init-order", M, "    init_smoke_bomb();\n    init_rocket();",
     "    init_rocket();\n    init_smoke_bomb();"),
    ("close-order", M,
     "    fini_class(&SmokeBombSlotPool, &SmokeBombEmitters);\n"
     "    fini_class(&RocketSlotPool, &RocketEmitters);",
     "    fini_class(&RocketSlotPool, &RocketEmitters);\n"
     "    fini_class(&SmokeBombSlotPool, &SmokeBombEmitters);"),
    ("close-handler-flags", M,
     "munitioneffectshandler_destroy(TheMunitionEffectsHandler, 3);",
     "munitioneffectshandler_destroy(TheMunitionEffectsHandler, 2);"),
    ("close-keep-handler", M,
     "TheMunitionEffectsHandler, 3);\n    TheMunitionEffectsHandler = NULL;",
     "TheMunitionEffectsHandler, 3);"),
    ("rk-creator-tables", M,
     "    set_tables(&r->Base, ROCKET_VTABLE, ROCKET_SYSTEM_VTABLE);\n"
     "    return &r->Base.Base;",
     "    set_tables(&r->Base, MUNITION_VTABLE, ROCKET_SYSTEM_VTABLE);\n"
     "    return &r->Base.Base;"),
    ("sb-creator-tables", M,
     "    set_tables(b, SMOKEBOMB_VTABLE, SMOKEBOMB_SYSTEM_VTABLE);\n"
     "    return &b->Base;",
     "    set_tables(b, SMOKEBOMB_VTABLE, DROPPEDBOMB_SYSTEM_VTABLE);\n"
     "    return &b->Base;"),
    ("ds-creator-deploy", M,
     "    s->DeploySpikes = 0;\n    return &s->Base.Base;",
     "    return &s->Base.Base;"),
    ("set-tables-sys", M, "    m->Base.System._vtable = system_vt;\n", ""),
    ("min-s", M, "return ft < fs ? ft : fs;", "return ft < fs ? fs : ft;"),
    ("max-s", M, "return fs < ft ? ft : fs;", "return fs < ft ? fs : ft;"),
    ("bam-div", M, "ee_trunc_w(deg * 65536.0f) / 360);",
     "ee_trunc_w(deg * 65536.0f) / 361);"),

    # Munition.
    ("munition-init-bd", M, "    m->BackupDone = 0;\n    return m;",
     "    return m;"),
    ("munition-dtor-free", M,
     "    smokeable_destroy(&m->Base, 0);\n    if (flags & 1)",
     "    smokeable_destroy(&m->Base, 0);\n    if (flags & 2)"),
    ("explode-at-x", M, "    at.x = 0.0f;", "    at.x = 1.0f;"),
    ("explode-at-z", M, "    at.z = p->ArmZAdjust;",
     "    at.z = p->CoordZAdjust;"),
    ("explode-no-movement", M,
     "if (car->TheMovementMode == eNO_MOVEMENT)\n            continue;",
     "if (car->TheMovementMode == eNO_MOVEMENT && 0)\n            continue;"),
    ("explode-dist", M, "dist = sqrtf(dx * dx + dy * dy);",
     "dist = sqrtf(dx * dx + dy * dy + 1.0f);"),
    ("explode-range-le", M, "if (!(dist < p->MaxRange))",
     "if (!(dist <= p->MaxRange))"),
    ("explode-dir-z", M, "        dir.z = 0.0f;\n",
     "        dir.z = car->State.Position.z - pos->z;\n"),
    ("explode-dir-pad", M, "dir.pad = car->State.Position.pad - pos->pad;",
     "dir.pad = 0.0f;"),
    ("explode-minrange", M, "if (dist < p->MinRange)",
     "if (dist + 0.5f < p->MinRange)"),
    ("explode-interp-num", M, "* (p->MaxRange - dist)",
     "* (p->MaxRange - dist - 0.5f)"),
    ("explode-interp-den", M, "/ (p->MaxRange - p->MinRange);",
     "/ (p->MaxRange - p->MinRange + 1.0f);"),
    ("explode-interp-min", M, "            s = p->MinStrength\n",
     "            s = p->MaxStrength\n"),
    ("explode-wheels", M, "if (car->State.nWheelsTouchingGround > 0)",
     "if (car->State.nWheelsTouchingGround >= 0)"),
    ("explode-coordz", M, "dir.z = dir.z + p->CoordZAdjust;",
     "dir.z = dir.z + p->ArmZAdjust;"),
    ("explode-physmode-other", M,
     "((VtPhysicsModeFn)e->fn)(vt_this(body, e), NULL);",
     "((VtPhysicsModeFn)e->fn)(vt_this(body, e), body);"),
    ("explode-impulse-at", M,
     "((VtImpulseFn)e->fn)(vt_this(body, e), &dir, &at);",
     "((VtImpulseFn)e->fn)(vt_this(body, e), &dir, &dir);"),
    ("explode-player", M, "        if (car->pPlayer != NULL) {",
     "        if (car->pPlayer == NULL) {"),
    ("explode-glare-type", M, "if (type == MT_BANG_FLASH && TheRace",
     "if (type == MT_SMOKE_BOMB && TheRace"),
    ("explode-glare-players", M, "TheRaceParameters.NumPlayerCars == 1)",
     "TheRaceParameters.NumPlayerCars >= 1)"),
    ("explode-stop-share", M, "#define MUNITION_STOP_SHARE   0.8f",
     "#define MUNITION_STOP_SHARE   0.6f"),
    ("explode-stop-le", M, "if (!(p->MaxStrength * MUNITION_STOP_SHARE < s))",
     "if (!(p->MaxStrength * MUNITION_STOP_SHARE <= s))"),
    ("explode-no-wreck", M, "                gCarDamageWreckFn(car->pCarDamage);",
     "                (void)0;"),
    ("explode-ebrake-ctl", M,
     "if (car->TheControlMode == REAL_CONTROL\n                && gReal",
     "if (1\n                && gReal"),
    ("explode-ebrake-time", M, "#define MUNITION_EBRAKE_TIME  3.5f",
     "#define MUNITION_EBRAKE_TIME  3.0f"),
    ("explode-zone-flag", M, "if (p->bRequestZoneCamera != 0\n",
     "if (p->bRequestZoneCamera == 0\n"),
    ("explode-zone-finish", M,
     "&& car->pRacingCar->FinishReason == 0\n",
     "&& car->pRacingCar->FinishReason >= 0\n"),
    ("explode-zone-args", M, "gPlayerRequestZoneFn(car->pPlayer, 1, 0, 1, 1);",
     "gPlayerRequestZoneFn(car->pPlayer, 1, 0, 1, 0);"),
    ("explode-ai-ctl", M, "} else if (car->TheControlMode == AI_CONTROL\n",
     "} else if (car->TheControlMode != AI_CONTROL\n"),
    ("explode-ai-physics", M,
     "&& (car->TheMovementMode == PHYSICS_MOVEMENT\n",
     "&& (car->TheMovementMode == eNO_MOVEMENT\n"),
    ("explode-ai-mellow", M,
     "|| car->TheMovementMode == MELLOW_MOVEMENT)) {",
     "|| 0)) {"),
    ("explode-sound-pos", M,
     "    collision_sound_play_explosion(\n"
     "        body_vector(m, COLLISIONBODY_VT_GET_POSITION));",
     "    collision_sound_play_explosion(&at);"),
    ("launch-no-awaken", M,
     "    smokeable_awaken(&m->Base);\n    smokeable_activate", "    smokeable_activate"),
    ("launch-no-anchors", M,
     "    smokeable_activate_anchor_emitters(&m->Base);\n}", "}"),
    ("flat-z", M, "    out->v3.z = p->z;", "    out->v3.z = p->y;"),
    ("flat-w", M, "    out->v3.w = 1.0f;", "    out->v3.w = 0.5f;"),
    ("backup-flag", M, "((Munition *)(void *)b)->BackupDone = 1;",
     "((Munition *)(void *)b)->BackupDone = 2;"),
    ("backup-no-dyn", M, "    dynamiccollisionbody_backup(b, t);\n}", "}"),
    ("explode-no-handler", M,
     "    if (TheMunitionEffectsHandler == NULL)\n        return 0;\n"
     "    munition_get_flat_matrix(m, &mat);",
     "    munition_get_flat_matrix(m, &mat);"),
    ("explode-returns-0", M, "    munition_explode_warhead(m, p, type);\n"
     "    return 1;", "    munition_explode_warhead(m, p, type);\n"
     "    return 0;"),

    # DroppedBomb and SmokeBomb.
    ("db-dtor-free", M, "    munition_destroy(m, 0);\n    if (flags & 1)",
     "    munition_destroy(m, 0);\n    if (flags & 2)"),
    ("db-move-dt", M, "{\n    smokeable_move(b, dt);\n}",
     "{\n    smokeable_move(b, dt * 2.0f);\n}"),
    ("sb-new-info", M,
     "find_smokeable_info(bchunk_hash(\"CS_SMOKEBOMB\"));\n\n"
     "    droppedbomb_init(b,",
     "find_smokeable_info(bchunk_hash(\"CS_Rocket\"));\n\n"
     "    droppedbomb_init(b,"),
    ("sb-new-name", M,
     "droppedbomb_init(b, id, info, bchunk_hash(\"SMOKEBOMB\"));",
     "droppedbomb_init(b, id, info, bchunk_hash(\"ROCKET\"));"),
    ("sb-dtor-pool", M, "        bSlotFree(SmokeBombSlotPool, b);",
     "        bSlotFree(SmokeableSlotPool, b);"),
    ("sb-dtor-base-flags", M, "    droppedbomb_destroy(b, 0);",
     "    droppedbomb_destroy(b, 1);"),
    ("sb-life-type", M, "&SmokeBombExplodeParams, MT_SMOKE_BOMB);",
     "&SmokeBombExplodeParams, MT_BANG_FLASH);"),
    ("sb-life-list", M, "explode((Munition *)(void *)b, &SmokeBombEmitters,",
     "explode((Munition *)(void *)b, &RocketEmitters,"),
    ("sb-move-backup", M, "    if (m->BackupDone == 0) {\n        struct Car",
     "    if (1) {\n        struct Car"),
    ("sb-move-cars", M, "if (c1 == NULL && c2 == NULL)",
     "if (c1 == NULL || c2 == NULL)"),
    ("sb-move-sample", M, "            if (c->Sample == NULL)\n",
     "            if (c->Sample != NULL)\n"),
    ("sb-move-destroy-flags", M,
     "            body_on_lifetime_end(m);\n            body_destroy(m, 3);",
     "            body_on_lifetime_end(m);\n            body_destroy(m, 2);"),
    ("sb-move-no-life", M,
     "            body_on_lifetime_end(m);\n            body_destroy(m, 3);",
     "            body_destroy(m, 3);"),
    ("sb-move-clear-bd", M,
     "    m->BackupDone = 0;\n    droppedbomb_move(b, dt);",
     "    droppedbomb_move(b, dt);"),
    ("sb-smoke-type", M, "    return ST_SMOKEBOMB;", "    return ST_ROCKET;"),

    # DroppedSpikes.
    ("ds-new-name", M,
     "droppedbomb_init(&s->Base, id, info, bchunk_hash(\"SMOKEBOMB\"));",
     "droppedbomb_init(&s->Base, id, info, bchunk_hash(\"ROCKET\"));"),
    ("ds-new-deploy", M, "    s->DeploySpikes = 0;\n    return s;",
     "    return s;"),
    ("ds-dtor-pool", M, "        bSlotFree(DroppedSpikesSlotPool, s);",
     "        bSlotFree(SmokeableSlotPool, s);"),
    ("ds-dtor-base-flags", M, "    droppedbomb_destroy(&s->Base, 0);",
     "    droppedbomb_destroy(&s->Base, 1);"),
    ("ds-life-type", M, "&DroppedSpikesExplodeParams, MT_SPIKE_BOMB))",
     "&DroppedSpikesExplodeParams, MT_BANG_FLASH))"),
    ("ds-life-no-belt", M, "        droppedspikes_make_spike_belt(s);\n}",
     "        (void)s;\n}"),
    ("ds-move-or", M,
     "if (s->Base.BackupDone == 0 && s->DeploySpikes != 0) {",
     "if (s->Base.BackupDone == 0 || s->DeploySpikes != 0) {"),
    ("ds-move-deploy", M, "&& s->DeploySpikes != 0) {",
     "&& s->DeploySpikes == 0) {"),
    ("ds-move-clear-bd", M,
     "    s->Base.BackupDone = 0;\n    droppedbomb_move(b, dt);",
     "    droppedbomb_move(b, dt);"),
    ("ds-consider-ret", M,
     "->DeploySpikes = 1;\n    return 1.0f;",
     "->DeploySpikes = 1;\n    return 0.5f;"),
    ("ds-consider-deploy", M,
     "->DeploySpikes = 1;\n    return 1.0f;",
     "->DeploySpikes = 2;\n    return 1.0f;"),
    ("ds-apply-deploy", M,
     "->DeploySpikes = 1;\n}\n\n// `side`", "->DeploySpikes = 0;\n}\n\n// `side`"),
    ("belt-no-found", M, "if (found == 0 || 1.0f < pos->z - elev)",
     "if (1.0f < pos->z - elev)"),
    ("belt-height-le", M, "1.0f < pos->z - elev)", "1.0f <= pos->z - elev)"),
    ("belt-height", M, "|| 1.0f < pos->z", "|| 1.5f < pos->z"),
    ("belt-near-flags", M, "ALL_RACING_ROUTES, 2, 0.0f))",
     "ALL_RACING_ROUTES, 3, 0.0f))"),
    ("belt-side-x", M, "side = (pos->x - pt->Position.x) * pt->Direction.y",
     "side = (pos->x - pt->Position.x) * pt->Direction.x"),
    ("belt-side-y", M, "- (pos->y - pt->Position.y) * pt->Direction.x;",
     "- (pos->y - pt->Position.y) * pt->Direction.y;"),
    ("belt-side-ge", M, "    if (0.0f < side)\n        w = side",
     "    if (0.0f <= side)\n        w = side"),
    ("belt-right-width", M, "w = side - pt->RightWidth;",
     "w = side - pt->LeftWidth;"),
    ("belt-left-width", M, "w = -(side + pt->LeftWidth);",
     "w = -(side + pt->RightWidth);"),
    ("belt-w-lt", M, "    if (w < 0.0f)\n        return;",
     "    if (w <= 0.0f)\n        return;"),
    ("belt-dir-x", M, "dir.x = pt->Direction.y;", "dir.x = pt->Direction.x;"),
    ("belt-dir-y", M, "dir.y = -pt->Direction.x;", "dir.y = pt->Direction.x;"),
    ("belt-right-a", M, "        a = min_s(w, 2.0f);",
     "        a = min_s(w, 0.5f);"),
    ("belt-right-b", M, "        b = 2.0f;\n    } else {",
     "        b = 1.5f;\n    } else {"),
    ("belt-left-a", M, "        a = 2.0f;\n        b = min_s",
     "        a = 1.5f;\n        b = min_s"),
    ("belt-left-b", M, "        b = min_s(w, 2.0f);",
     "        b = min_s(w, 1.0f);"),
    ("belt-p2-neg", M, "pos, &dir, -b);", "pos, &dir, b);"),
    ("belt-strip-order", M, "(pCopManager, &p2, &p1, -1, 20.0f);",
     "(pCopManager, &p1, &p2, -1, 20.0f);"),
    ("belt-strip-time", M, "&p1, -1, 20.0f);", "&p1, -1, 25.0f);"),
    ("belt-strip-id", M, "&p1, -1, 20.0f);", "&p1, 0, 20.0f);"),
    ("ds-smoke-type", M, "    return ST_DROPPED_SPIKES;",
     "    return ST_SMOKEBOMB;"),

    # Rocket.
    ("rk-new-info", M, "find_smokeable_info(bchunk_hash(\"CS_Rocket\"));",
     "find_smokeable_info(bchunk_hash(\"CS_SMOKEBOMB\"));"),
    ("rk-new-name", M,
     "munition_init(&r->Base, id, info, bchunk_hash(\"ROCKET\"));",
     "munition_init(&r->Base, id, info, bchunk_hash(\"SMOKEBOMB\"));"),
    ("rk-dtor-pool", M, "        bSlotFree(RocketSlotPool, r);",
     "        bSlotFree(SmokeableSlotPool, r);"),
    ("rk-dtor-base-flags", M, "    munition_destroy(&r->Base, 0);",
     "    munition_destroy(&r->Base, 1);"),
    ("rk-life-params", M, "&RocketEmitters, &RocketExplodeParams,",
     "&RocketEmitters, &SmokeBombExplodeParams,"),
    ("rk-life-type", M, "&RocketExplodeParams,\n            MT_BANG_FLASH);",
     "&RocketExplodeParams,\n            MT_SMOKE_BOMB);"),
    ("rk-bam-degrees", M, "#define BAM_TO_DEGREES        0.0054931640625f",
     "#define BAM_TO_DEGREES        0.0055f"),
    ("rk-launch-atan", M,
     "make_relative_angle((float)bATan(v->x, v->y) * BAM_TO_DEGREES);",
     "make_relative_angle((float)bATan(v->y, v->x) * BAM_TO_DEGREES);"),
    ("rk-launch-relangle", M,
     "yaw = make_relative_angle((float)bATan(v->x, v->y) * BAM_TO_DEGREES);",
     "yaw = (float)bATan(v->x, v->y) * BAM_TO_DEGREES;"),
    ("rk-launch-target", M, "    r->Target = target;",
     "    r->Target = NULL;"),
    ("rk-move-backup", M,
     "    if (r->Base.BackupDone != 0) {\n        r->Base.BackupDone = 0;\n"
     "        return;\n    }\n", ""),
    ("rk-move-backup-keep", M,
     "        r->Base.BackupDone = 0;\n        return;", "        return;"),
    ("rk-move-no-target", M, "    if (r->Target == NULL) {",
     "    if (r->Target == NULL && 0) {"),
    ("rk-move-target-flags", M,
     "        body_destroy(r, 3);\n        return;\n    }\n"
     "    dynamiccollisionbody_begin_move",
     "        body_destroy(r, 2);\n        return;\n    }\n"
     "    dynamiccollisionbody_begin_move"),
    ("rk-move-height", M, "#define ROCKET_HEIGHT         0.9f",
     "#define ROCKET_HEIGHT         1.0f"),
    ("rk-move-dx", M, "d.x = r->Target->State.Position.x - pos->x;",
     "d.x = r->Target->State.Position.x + pos->x;"),
    ("rk-move-dy", M, "d.y = r->Target->State.Position.y - pos->y;",
     "d.y = r->Target->State.Position.y - pos->x;"),
    ("rk-move-turn-rate", M, "lim = dt * 90.0f;", "lim = dt * 80.0f;"),
    ("rk-move-turn-rel", M, "turn = make_relative_angle(ang - r->Yaw);",
     "turn = ang - r->Yaw;"),
    ("rk-move-clamp-hi", M, "turn = min_s(lim, max_s(turn, -lim));",
     "turn = max_s(turn, -lim);"),
    ("rk-move-clamp-lo", M, "turn = min_s(lim, max_s(turn, -lim));",
     "turn = min_s(lim, turn);"),
    ("rk-move-yaw", M, "r->Yaw = r->Yaw + turn;", "r->Yaw = ang;"),
    ("rk-move-vel-x", M,
     "vel->x = bCosBam(degrees_to_bam(-r->Yaw)) * 30.0f;",
     "vel->x = bCosBam(degrees_to_bam(-r->Yaw)) * 31.0f;"),
    ("rk-move-vel-y", M, "vel->y = -bSinBam(degrees_to_bam(-r->Yaw))",
     "vel->y = bSinBam(degrees_to_bam(-r->Yaw))"),
    ("rk-move-vel-y-angle", M, "-bSinBam(degrees_to_bam(-r->Yaw))",
     "-bSinBam(degrees_to_bam(r->Yaw))"),
    ("rk-move-climb", M, "max_s((elev - pos->z) * 12.0f, -25.0f)",
     "max_s((elev - pos->z) * 10.0f, -25.0f)"),
    ("rk-move-climb-hi", M, "vel->z = min_s(25.0f,", "vel->z = min_s(30.0f,"),
    ("rk-move-climb-lo", M, "* 12.0f, -25.0f));", "* 12.0f, -30.0f));"),
    ("rk-move-np-x", M, "np.x = vel->x * dt + pos->x;",
     "np.x = vel->x + pos->x;"),
    ("rk-move-np-z", M, "np.z = vel->z * dt + pos->z;",
     "np.z = vel->z * dt;"),
    ("rk-move-roty", M, "(uint16_t)bATan(vel->z, 30.0f));",
     "(uint16_t)bATan(vel->z, 25.0f));"),
    ("rk-move-rotz", M, "eRotateZ(&m, &m, degrees_to_bam(r->Yaw));",
     "eRotateZ(&m, &m, degrees_to_bam(-r->Yaw));"),
    ("rk-move-zero", M, "    zero.y = 0.0f;", "    zero.y = 1.0f;"),
    ("rk-move-state-vel", M, "(const bVector4 *)(const void *)vel, &zero);",
     "&zero, &zero);"),
    ("rk-move-matrix-pos", M, "    m.v3.y = np.y;", "    m.v3.y = np.x;"),
    ("rk-move-enabled", M, "    s->TheWorldObject.Enabled = 1;",
     "    s->TheWorldObject.Enabled = 0;"),
    ("rk-move-no-poschange", M, "    smokeable_position_changed(s);\n", ""),
    ("rk-move-no-svc", M, "    smokeable_service_emitters(s, &m);\n", ""),
    ("rk-move-no-timers", M, "    smokeable_check_timers(s);\n}\n\n// Struck",
     "}\n\n// Struck"),
    ("rk-consider-target", M,
     "    ((Rocket *)(void *)b)->Target = NULL;\n    return -57575.0f;",
     "    return -57575.0f;"),
    ("rk-consider-ret", M, "return -57575.0f;", "return 0.0f;"),
    ("rk-apply-target", M,
     "    ((Rocket *)(void *)b)->Target = NULL;\n}\n\nint32_t rocket_get",
     "}\n\nint32_t rocket_get"),
    ("rk-smoke-type", M, "    return ST_ROCKET;", "    return ST_SMOKEBOMB;"),

    # The effects handler.
    ("eff-destroy-loop", M, "    while (h->List.next != &h->List) {",
     "    if (h->List.next != &h->List) {"),
    ("eff-destroy-free", M, "    if (flags & 1)\n        bFree(h);",
     "    if (flags & 4)\n        bFree(h);"),
    ("eff-drop-flags", M, "acid_emitter_delete(e, 3);",
     "acid_emitter_delete(e, 1);"),
    ("eff-drop-remauto", M,
     "    acid_system_remove_auto_emitter(&WorldEffects, e);\n", ""),
    ("eff-tick-state", M, "        if (e->State == ACID_ON)",
     "        if (e->State >= ACID_ON)"),
    ("eff-add-skip-null", M, "        if (c == NULL)\n            continue;\n",
     ""),
    ("eff-add-state", M, "        c->State = ACID_ON;", "        c->State = 2;"),
    ("eff-add-matrix", M, "        c->LocalWorld = *m;\n", ""),
    ("eff-add-auto", M,
     "        acid_system_add_auto_emitter(&WorldEffects, c);\n", ""),
    ("eff-add-prev", M, "        p->Node.prev = &h->List;",
     "        p->Node.prev = head;"),
    ("eff-add-headprev", M, "        head->prev = &p->Node;\n", ""),

    # The tables.
    ("vt-backup", M, "E(munition_backup),", "E(dynamiccollisionbody_backup),"),
    ("vt-sb-move", M, "MUNITION_VT(smokebomb_vt_destroy, smokebomb_move,",
     "MUNITION_VT(smokebomb_vt_destroy, droppedbomb_move,"),
    ("vt-rk-dtor", M, "MUNITION_VT(rocket_vt_destroy, rocket_move,",
     "MUNITION_VT(munition_vt_destroy, rocket_move,"),
    ("vt-ds-dtor", M, "MUNITION_VT(droppedspikes_vt_destroy,",
     "MUNITION_VT(droppedbomb_vt_destroy,"),
    ("vt-sys-delta", M,
     "    int16_t  d = (int16_t)-(int)offsetof(Smokeable, System);",
     "    int16_t  d = (int16_t)(4 - (int)offsetof(Smokeable, System));"),
    ("vt-sys-resolve", M, "    t[3].fn = (VtFn)physicssystem_resolve_forces;",
     "    t[3].fn = NULL;"),
    ("vt-rk-sys-dtor", M, "ROCKET_SYSTEM_VTABLE,\n            (VtFn)rocket_vt_destroy);",
     "ROCKET_SYSTEM_VTABLE,\n            (VtFn)munition_vt_destroy);"),
    ("vt-sb-sys-dtor", M,
     "SMOKEBOMB_SYSTEM_VTABLE,\n            (VtFn)smokebomb_vt_destroy);",
     "SMOKEBOMB_SYSTEM_VTABLE,\n            (VtFn)droppedbomb_vt_destroy);"),
]

EQUIVALENT = {}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    lines = script()
    base = model(lines)
    indir = tempfile.TemporaryDirectory()
    scp = write_script(indir.name, lines)
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
        todo, SOURCES, NAME,
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
    ap.add_argument("--model-only", action="store_true")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None,
                             args.jobs))

    lines = script()
    got = model(lines)
    if args.model_only:
        print(NL.join(got))
        return
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
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
