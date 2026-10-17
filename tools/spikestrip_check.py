#!/usr/bin/env python3
"""Cross-check 3DS Files/source/spikestrip.c, the spike strips, and
worldobject.c, the world objects their belt pieces are, against the
retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own code: tCopManager::AddSpikeStrip
(0x002276d0) and so tSpikeStrip's constructor (0x00241378), Init
(0x002414e8) and the twenty belt pieces' constructor (0x002419f8) with
WorldObject's (0x001cd760) and bStringHash under it; MonitorSpikeBelts
(0x00227758) with Update (0x002417b8), BlinkBlinkPoof (0x00241880),
AICarController's force_pull_over (0x001908d8) and the strip's and the
pieces' destructors (0x00241430, 0x00241a48) with WorldObject's
(0x001cd828), reached through their tables; InitWorldObjects
(0x001cd918) and CloseWorldObjects (0x001cd948); and the default
constructor (0x00241308), which the cop manager's replay snapshot uses
(TASKS 72e-3). The harness
(tools/src/spikestrip_test.c) runs spikestrip.c, worldobject.c and
vtable.c and prints the same lines.

**The stubs**, logged and answered by the same rule on both sides:
bOMalloc (a block of 0xcd, named by its pool), bFree, bNewSlotPool and
bDeleteSlotPool; eModel::Init and its destructor; GetVectorOnTrack (a
scripted queue of points, else the input's x, y and x / 4);
World::GetDistanceToClosestPlayer's bVector2 form and Car::IsBlinking
(scripted by car); eMulMatrix (the wheel's matrix logged by name and the
body's by its sixteen words; the product a mix of both);
DoSegmentsIntersect (its eight floats logged, a scripted queue of
answers); Car::TriggerTireBlowOut (the bits added, the count their
population); Player::RequestZone and StartScore; IsBeingPursued (scripted
by car); CreatePullover; and the controller's ForceBoost, through a table
of the checker's own with a this-adjustment of 16.

**Compared** are the stubs' logs and, on `strip`, `edump`, `wdump`,
`list` and `cars`, every field of a strip and of each of its twenty
pieces at retail's offsets -- the padding included, which the image never
writes -- WorldObjectList and the manager's list both ways, and each
car's blown tires and its controller's forced action and pull-over time.

**The script** builds and destroys world objects with and without a
matrix; lays strips of every length from none to past twenty pieces,
on the level, sloped, straight up and with both ends together; counts
their lives down through the blink to the end, with a NaN and with no
lifetime; and runs the manager's watch over cars out of range, blinking,
off to the side, and on the strip with each set of wheels down, as AI
racers, players, the player's own cop and traffic, in Be A Cop and not,
at each difficulty, with tires already blown and not. Last, it builds
two strips with the default constructor, from a dirty pool and a clean
one.

    python tools/spikestrip_check.py
    python tools/spikestrip_check.py --mutate [--only a,b]
    python tools/spikestrip_check.py --dump out/spikestrip
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

HARNESS = "tools/src/spikestrip_test.c"
SPIKE = "3DS Files/source/spikestrip.c"
WOBJ = "3DS Files/source/worldobject.c"
SOURCES = [HARNESS, SPIKE, WOBJ, "3DS Files/source/vtable.c"]
HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = retail_model.RETAIL_GP
RP = 0x0031a898                         # TheRaceParameters
RP_BEACOP = 628
G_WTE = GP - 19560                      # WorldTimeElapsed
G_WORLD = GP - 22120                    # pCurrentWorld
G_SSP = GP - 15636                      # SpikeStripSlotPool
G_EMP = GP - 25200                      # eModelSlotPool
G_WOL = GP - 18120                      # WorldObjectList (prev at +4)
G_WOP = GP - 18112                      # WorldObjectSlotPool

F_ADD = 0x002276d0
F_DFLT = 0x00241308                     # tSpikeStrip(void)
F_MON = 0x00227758
F_INIT = 0x002414e8
F_UPDATE = 0x002417b8
F_POOF = 0x00241880
F_ECTOR = 0x002419f8
F_WOCTOR = 0x001cd760
F_WODTOR = 0x001cd828
F_INITWO = 0x001cd918
F_CLOSEWO = 0x001cd948

S_OMALLOC = 0x00257c80
S_FREE = 0x00257ca0
S_NEWPOOL = 0x00257c10
S_DELPOOL = 0x00257c48
S_MINIT = 0x0010c558
S_MDTOR = 0x00114cf0
S_GVOT = 0x001cb350
S_DIST = 0x0014e3e8
S_BLINK = 0x00133130
S_EMUL = 0x0011b248
S_DSI = 0x00230f00
S_BLOW = 0x00135040
S_ZONE = 0x00177c88
S_SCORE = 0x0017e3b0
S_PURSUED = 0x00227438
S_PULL = 0x00226f30
S_PIXEL = 0x00107600                    # eView::GetPixelSize(bVector3 *, f)
S_CURVIEW = 0x00107ca8                  # eGetCurrentView
S_CLASSIFY = 0x0010ccb0                 # ClassifyAABB
S_LIGHT = 0x00115978                    # elSetupLightContext
S_MRENDER = 0x0010dc80                  # eModel::Render
F_RENDER = 0x001cd998                   # WorldObject::Render
F_RENDERALL = 0x001cdb20                # RenderWorldObjects
G_FPOS = GP - 19388                     # CurrentBufferPos
G_FEND = GP - 19384                     # CurrentBufferEnd
G_FFAIL = GP - 19372                    # FrameMallocFailed
G_FAMOUNT = GP - 19368                  # FrameMallocFailAmount

NCARS = 6
NCOPS = 7
CAR_SIZE = 2304
WORLD_SIZE = 5936
MGR_SIZE = 10516
STRIP_SIZE = 2304
EL0, EL_SIZE = 48, 112
BOOST_DELTA = 16
VT_BOOST = 96
FRAME_SIZE = 4096
NVIEWS, VIEW_SIZE, CAMERA_SIZE = 2, 128, 464
NSOLIDS, SOLID_SIZE = 4, 192

C_DRIVER, C_PLAYER, C_RACING, C_CTL = 20, 24, 28, 40
C_POS, C_VEL, C_BODY, C_WHEEL = 96, 112, 144, 240
C_TOUCH, C_FWD, C_BLOWN, C_NBLOWN = 848, 960, 2124, 2125
CTL_ACT, CTL_POT = 528, 548
M_COPIDX, M_COPS, M_LIST, M_DIFF = 12, 16, 80, 10476


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def bitsf(u):
    return struct.unpack("<f", struct.pack("<I", u & M32))[0]


def F(f):
    return "%08x" % fbits(f)


def popcount(v):
    return bin(v).count("1")


# ================================================================== model

class Model(object):
    def __init__(self):
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True,
                                            eesqrt=True)
        self.out = []
        self.names = {}
        self.strips, self.elems, self.wos = [], [], []
        self.nmodels = self.nblocks = 0
        self.gvq, self.dsq = [], []
        self.fill = 0xcd
        self.dist = [0] * NCARS
        self.blinking = [0] * NCARS
        self.pursued = [0] * NCARS
        self.models, self.pixq, self.clsq = [], [], []
        self.curview = 0
        self.fbase = e.alloc(FRAME_SIZE, align=16)
        e.write(self.fbase, bytes(FRAME_SIZE))

        def tok(n, size=16):
            p = e.alloc(size, align=16)
            e.write(p, bytes(size))
            self.names[p] = n
            return p

        self.ssp = tok("SSP")
        self.emp = tok("EMP")
        self.wop = tok("WOP")
        self.pu = tok("PU")
        e.put32(G_SSP, self.ssp)
        e.put32(G_EMP, self.emp)
        e.put32(G_WOP, 0)
        e.put32(G_WOL, G_WOL)
        e.put32(G_WOL + 4, G_WOL)
        self.names[G_WOL] = "WOL"
        self.world = tok("W", WORLD_SIZE)
        e.put32(G_WORLD, self.world)
        self.mgr = tok("M", MGR_SIZE)
        self.names[self.mgr + M_LIST] = "M.sl"
        self.mreset()
        e.write(RP, bytes(1024))
        # The controllers' table: ForceBoost at 96, this + 16.
        self.boost_fn = e.alloc(16, align=16)
        self.vt = e.alloc(128, align=16)
        e.write(self.vt, bytes(128))
        struct.pack_into("<hhI", e.mem, self.vt + VT_BOOST, BOOST_DELTA, 0,
                         self.boost_fn)
        e.stub(self.boost_fn, self.s_boost)
        self.cars, self.players, self.racers = [], [], []
        self.ctls, self.drivers = [], []
        for k in range(NCARS):
            car = tok("A%d" % k, CAR_SIZE)
            self.players.append(tok("P%d" % k))
            self.racers.append(tok("R%d" % k))
            ctl = tok("C%d" % k, 640)
            self.names[ctl + BOOST_DELTA] = "C%d+%d" % (k, BOOST_DELTA)
            drv = tok("D%d" % k, 32)
            e.put32(car + C_DRIVER, drv)
            e.put32(car + C_CTL, ctl)
            e.put32(ctl + 8, self.vt)
            for w in range(4):
                self.names[car + C_WHEEL + 64 * w] = "A%d.w%d" % (k, w)
            self.cars.append(car)
            self.ctls.append(ctl)
            self.drivers.append(drv)
        self.cops = [tok("T%d" % i, 128) for i in range(NCOPS)]
        self.views = []
        for k in range(NVIEWS):
            v = tok("V%d" % k, VIEW_SIZE)
            e.put32(v + 56, tok("K%d" % k, CAMERA_SIZE))
            e.put32(v + 68, tok("V%d.wv" % k, 64))
            e.put32(v + 80, tok("V%d.clip" % k, 64))
            self.views.append(v)
        self.solids = []
        for k in range(NSOLIDS):
            s = tok("L%d" % k, SOLID_SIZE)
            self.names[s + 64] = "L%d.min" % k
            self.names[s + 80] = "L%d.max" % k
            self.solids.append(s)
        for a, fn in ((S_OMALLOC, self.s_omalloc), (S_FREE, self.s_free),
                      (S_NEWPOOL, self.s_newpool),
                      (S_DELPOOL, self.s_delpool),
                      (S_MINIT, self.s_minit), (S_MDTOR, self.s_mdtor),
                      (S_GVOT, self.s_gvot), (S_DIST, self.s_dist),
                      (S_BLINK, self.s_blink), (S_EMUL, self.s_emul),
                      (S_DSI, self.s_dsi), (S_BLOW, self.s_blow),
                      (S_ZONE, self.s_zone), (S_SCORE, self.s_score),
                      (S_PURSUED, self.s_pursued), (S_PULL, self.s_pull),
                      (S_PIXEL, self.s_pixel), (S_CURVIEW, self.s_curview),
                      (S_CLASSIFY, self.s_classify),
                      (S_LIGHT, self.s_light),
                      (S_MRENDER, self.s_mrender)):
            e.stub(a, fn)

    def mreset(self):
        self.e.put32(self.mgr + M_LIST, self.mgr + M_LIST)
        self.e.put32(self.mgr + M_LIST + 4, self.mgr + M_LIST)

    def emit(self, line):
        self.out.append(line)

    def sym(self, v):
        v &= M32
        if v == 0:
            return "0"
        if v == 0xcdcdcdcd:
            return "cd"
        if self.fbase <= v < self.fbase + FRAME_SIZE:
            return "F+%d" % (v - self.fbase)
        return self.names.get(v, "?")

    def pool(self, v):
        return self.sym(v)

    def words(self, a, n):
        return "".join(" %08x" % self.e.u32(a + 4 * i) for i in range(n))

    def block(self, size):
        p = self.e.alloc(size, align=16)
        self.e.write(p, bytes([self.fill]) * size)
        return p

    def cstr(self, a):
        b = self.e.read(a, 64)
        return b.split(b"\0")[0].decode("latin-1")

    def car_of(self, a, off=0):
        for k, c in enumerate(self.cars):
            if c + off == a & M32:
                return k
        return -1

    # ---- stubs

    def s_omalloc(self, em):
        pool = em.reg[4] & M32
        if pool == self.ssp:
            p = self.block(STRIP_SIZE)
            n = len(self.strips)
            self.names[p] = "S%d" % n
            for k in range(20):
                el = p + EL0 + EL_SIZE * k
                self.names[el] = "S%d.%d" % (n, k)
                self.names[el + 32] = "S%d.%d.m" % (n, k)
                self.names[el + 80] = "S%d.%d.p" % (n, k)
            self.names[p + 8] = "S%d.start" % n
            self.names[p + 16] = "S%d.end" % n
            self.strips.append(p)
        elif pool == self.emp:
            p = self.block(32)
            self.names[p] = "E%d" % self.nmodels
            self.nmodels += 1
            self.models.append(p)
        else:
            p = self.block(4096)
            self.names[p] = "B%d" % self.nblocks
            self.nblocks += 1
        self.emit("  omalloc %s -> %s" % (self.pool(pool), self.sym(p)))
        return p

    def s_free(self, em):
        self.emit("  free %s %s" % (self.pool(em.reg[4]),
                                    self.sym(em.reg[5])))

    def s_newpool(self, em):
        self.emit("  newpool %d %d %s %d" % (
            s32(em.reg[4]), s32(em.reg[5]), self.cstr(em.reg[6] & M32),
            s32(em.reg[7])))
        return self.wop

    def s_delpool(self, em):
        self.emit("  delpool %s" % self.pool(em.reg[4]))

    def s_minit(self, em):
        m = em.reg[4] & M32
        self.emit("  model init %s hash %08x name %08x solid %s" % (
            self.sym(m), em.reg[5] & M32, self.e.u32(m + 8),
            self.sym(self.e.u32(m + 12))))

    def s_mdtor(self, em):
        self.emit("  model dtor %s flags %d" % (self.sym(em.reg[4]),
                                                s32(em.reg[5])))

    def s_gvot(self, em):
        e = self.e
        out, a = em.reg[4] & M32, em.reg[5] & M32
        ix, iy = e.u32(a), e.u32(a + 4)
        if self.gvq:
            x, y, z = self.gvq.pop(0)
        else:
            x, y, z = ix, iy, fbits(bitsf(ix) * 0.25)
        e.put32(out, x)
        e.put32(out + 4, y)
        e.put32(out + 8, z)
        self.emit("  gvot %s %08x %08x -> %08x %08x %08x" % (
            self.sym(a), ix, iy, x, y, z))

    def s_dist(self, em):
        k = self.car_of(em.reg[5], C_POS)
        bits = self.dist[k] if k >= 0 else 0
        self.emit("  dist %s %s -> %08x" % (
            "W" if em.reg[4] & M32 == self.world else "?",
            "?" if k < 0 else "A%d" % k, bits))
        em.fpr[0] = bits

    def s_blink(self, em):
        k = self.car_of(em.reg[4])
        self.emit("  blinking %s -> %d" % (self.sym(em.reg[4]),
                                           self.blinking[k]))
        return self.blinking[k]

    def s_blow(self, em):
        e = self.e
        car, bits = em.reg[4] & M32, s32(em.reg[5])
        self.emit("  blowout %s %d" % (self.sym(car), bits))
        b = (e.u8(car + C_BLOWN) | bits) & 0xff
        e.mem[car + C_BLOWN] = b
        e.mem[car + C_NBLOWN] = popcount(b)

    def s_emul(self, em):
        e = self.e
        o, a, b = (em.reg[r] & M32 for r in (4, 5, 6))
        self.emit("  emul %s%s" % (self.sym(a), self.words(b, 16)))
        aw = [e.u32(a + 4 * i) for i in range(16)]
        bw = [e.u32(b + 4 * i) for i in range(16)]
        for i in range(16):
            e.put32(o + 4 * i, aw[i] * 3 + bw[15 - i])

    def s_dsi(self, em):
        v = self.dsq.pop(0) if self.dsq else 0
        ws = "".join(self.words(em.reg[r] & M32, 2) for r in (4, 5, 6, 7))
        self.emit("  dsi%s -> %d" % (ws, v))
        return v

    def s_zone(self, em):
        self.emit("  zone %s %d %d %d %d" % (
            self.sym(em.reg[4]), s32(em.reg[5]), s32(em.reg[6]),
            s32(em.reg[7]), s32(em.reg[8])))
        return 0

    def s_score(self, em):
        self.emit("  score %s %d" % (self.sym(em.reg[4]), s32(em.reg[5])))

    def s_pursued(self, em):
        k = self.car_of(em.reg[5])
        self.emit("  pursued %s %s -> %d" % (
            self.sym(em.reg[4]), self.sym(em.reg[5]), self.pursued[k]))
        return self.pu if self.pursued[k] else 0

    def s_pull(self, em):
        self.emit("  pullover %s %s %s %d" % (
            self.sym(em.reg[4]), self.sym(em.reg[5]), self.sym(em.reg[6]),
            s32(em.reg[7])))

    def s_boost(self, em):
        self.emit("  boost %s %08x" % (self.sym(em.reg[4]), em.fpr[12]
                                       & M32))

    def s_pixel(self, em):
        v = self.pixq.pop(0) if self.pixq else 100
        p = em.reg[5] & M32
        self.emit("  pix %s %s%s %08x -> %d" % (
            self.sym(em.reg[4]), self.sym(p), self.words(p, 3),
            em.fpr[12] & M32, v))
        return v

    def s_curview(self, em):
        self.emit("  curview -> %s" % self.sym(self.curview))
        return self.curview

    def s_classify(self, em):
        v = self.clsq.pop(0) if self.clsq else 1
        self.emit("  classify %s %s%s -> %d" % (
            self.sym(em.reg[4]), self.sym(em.reg[5]),
            self.words(em.reg[6] & M32, 16), v))
        return v

    def s_light(self, em):
        lc, m, hack, eye, view = (em.reg[r] & M32 for r in (4, 5, 6, 7, 8))
        self.emit("  light %s %s%s %s%s %s" % (
            self.sym(lc), self.sym(m), self.words(m, 16), self.sym(hack),
            self.words(eye, 4), self.sym(view)))
        return 1

    def s_mrender(self, em):
        m = em.reg[5] & M32
        self.emit("  mrender %s %s%s %s %d" % (
            self.sym(em.reg[4]), self.sym(m), self.words(m, 16),
            self.sym(em.reg[6]), s32(em.reg[7])))

    # ---- dumps

    def dump_list(self):
        e = self.e
        lst = self.mgr + M_LIST
        s, n, i = "slist", e.u32(lst), 0
        while n != lst and i < 64:
            s += " %s<%s" % (self.sym(n), self.sym(e.u32(n + 4)))
            n, i = e.u32(n), i + 1
        s += " | %s<%s" % (self.sym(e.u32(lst)), self.sym(e.u32(lst + 4)))
        self.emit(s)
        s, n, i = "wolist", e.u32(G_WOL), 0
        while n != G_WOL and i < 400:
            s += " %s<%s" % (self.sym(n), self.sym(e.u32(n + 4)))
            n, i = e.u32(n), i + 1
        s += " | %s<%s" % (self.sym(e.u32(G_WOL)),
                           self.sym(e.u32(G_WOL + 4)))
        self.emit(s)

    def wo_fields(self, o):
        e = self.e
        return (" next %s prev %s model %s en %08x light %08x pad%s m%s" % (
            self.sym(e.u32(o)), self.sym(e.u32(o + 4)),
            self.sym(e.u32(o + 8)), e.u32(o + 12), e.u32(o + 16),
            self.words(o + 20, 3), self.words(o + 32, 16)))

    def dump_elem(self, el):
        self.emit("el %s%s vptr %08x pad%s" % (
            self.sym(el), self.wo_fields(el), self.e.u32(el + 96),
            self.words(el + 100, 3)))

    def dump_strip(self, s):
        e = self.e
        self.emit("strip %s vptr %08x next %s prev %s start %08x %08x end "
                  "%08x %08x id %d blink %d timer %08x life %08x n %d pad%s"
                  " tail%s" % (
                      self.sym(s), e.u32(s + 2288), self.sym(e.u32(s)),
                      self.sym(e.u32(s + 4)), e.u32(s + 8), e.u32(s + 12),
                      e.u32(s + 16), e.u32(s + 20), s32(e.u32(s + 24)),
                      s32(e.u32(s + 28)), e.u32(s + 32), e.u32(s + 36),
                      s32(e.u32(s + 40)), self.words(s + 44, 1),
                      self.words(s + 2292, 3)))
        for k in range(20):
            self.dump_elem(s + EL0 + EL_SIZE * k)

    def dump_cars(self):
        e = self.e
        for k in range(NCARS):
            c, ctl = self.cars[k], self.ctls[k]
            self.emit("car A%d blown %02x n %02x act %d pot %08x" % (
                k, e.u8(c + C_BLOWN), e.u8(c + C_NBLOWN),
                s32(e.u32(ctl + CTL_ACT)), e.u32(ctl + CTL_POT)))

    # ---- ops

    def car_field(self, k, a):
        e = self.e
        c, f = self.cars[k], a[0]

        def putf(addr, vals):
            for i, v in enumerate(vals):
                e.put32(addr + 4 * i, int(v, 16))

        if f == "type":
            e.put32(self.drivers[k] + 8, int(a[1], 0))
        elif f == "player":
            e.put32(c + C_PLAYER, self.players[k] if int(a[1], 0) else 0)
        elif f == "racing":
            e.put32(c + C_RACING, self.racers[k] if int(a[1], 0) else 0)
        elif f == "ctl":
            e.put32(c + C_CTL, self.ctls[k] if int(a[1], 0) else 0)
        elif f == "pos":
            putf(c + C_POS, a[1:4])
        elif f == "vel":
            putf(c + C_VEL, a[1:4])
        elif f == "body":
            putf(c + C_BODY, a[1:13])
        elif f == "wheel":
            putf(c + C_WHEEL + 64 * int(a[1], 0), a[2:18])
        elif f == "touch":
            e.mem[c + C_TOUCH + int(a[1], 0)] = int(a[2], 0) & 0xff
        elif f == "fwd":
            putf(c + C_FWD, a[1:2])
        elif f == "blown":
            e.mem[c + C_BLOWN] = int(a[1], 0) & 0xff
        elif f == "nblown":
            e.mem[c + C_NBLOWN] = int(a[1], 0) & 0xff
        elif f == "dist":
            self.dist[k] = int(a[1], 16)
        elif f == "blinking":
            self.blinking[k] = int(a[1], 0)
        elif f == "pursued":
            self.pursued[k] = int(a[1], 0)
        elif f == "act":
            e.put32(self.ctls[k] + CTL_ACT, int(a[1], 0))
        elif f == "pot":
            putf(self.ctls[k] + CTL_POT, a[1:2])
        else:
            raise ValueError("car field %s" % f)

    def vec2(self, a):
        p = self.e.alloc(16, align=16)
        self.e.put32(p, int(a[0], 16))
        self.e.put32(p + 4, int(a[1], 16))
        return p

    def vcall(self, obj, vptr_off, flags):
        e = self.e
        vt = e.u32(obj + vptr_off)
        delta = struct.unpack_from("<h", e.mem, vt + 8)[0]
        e.call(e.u32(vt + 12), obj + delta, flags)

    def op(self, a):
        e = self.e
        o = a[0]
        if o == "wte":
            e.put32(G_WTE, int(a[1], 16))
        elif o == "beacop":
            e.put32(RP + RP_BEACOP, int(a[1], 0))
        elif o == "ncars":
            e.put32(self.world + 28, int(a[1], 0))
        elif o == "table":
            e.put32(self.world + 44 + 4 * int(a[1], 0),
                    self.cars[int(a[2], 0)])
        elif o == "copidx":
            e.put32(self.mgr + M_COPIDX, int(a[1], 0))
        elif o == "diff":
            e.put32(self.mgr + M_DIFF, int(a[1], 0))
        elif o == "cop":
            i = int(a[1], 0)
            e.put32(self.mgr + M_COPS + 4 * i, self.cops[i])
            e.put32(self.cops[i] + 4, self.cars[int(a[2], 0)])
        elif o == "cf":
            self.car_field(int(a[1], 0), a[2:])
        elif o == "gv":
            self.gvq.append(tuple(int(x, 16) for x in a[1:4]))
        elif o == "ds":
            self.dsq.append(int(a[1], 0))
        elif o == "fill":
            self.fill = int(a[1], 16)
        elif o == "dsclear":
            self.dsq = []
        elif o == "mreset":
            self.mreset()
        elif o == "initwo":
            self.emit("initwo")
            e.call(F_INITWO)
            self.emit("  pool %s" % self.sym(e.u32(G_WOP)))
        elif o == "closewo":
            self.emit("closewo")
            e.call(F_CLOSEWO)
            self.emit("  pool %s" % self.sym(e.u32(G_WOP)))
        elif o == "add":
            pa, pb = self.vec2(a[1:3]), self.vec2(a[3:5])
            self.emit("add")
            e.fpr[12] = int(a[6], 16)
            e.call(F_ADD, self.mgr, pa, pb, int(a[5], 0))
        elif o == "init":
            i = int(a[1], 0)
            pa, pb = self.vec2(a[2:4]), self.vec2(a[4:6])
            self.emit("init S%d" % i)
            e.fpr[12] = int(a[7], 16)
            e.call(F_INIT, self.strips[i], pa, pb, int(a[6], 0))
        elif o == "monitor":
            self.emit("monitor")
            e.call(F_MON, self.mgr)
        elif o == "update":
            i = int(a[1], 0)
            self.emit("update S%d" % i)
            r = e.call(F_UPDATE, self.strips[i])
            self.emit("  -> %d" % r)
        elif o == "poof":
            i = int(a[1], 0)
            self.emit("poof S%d" % i)
            e.call(F_POOF, self.strips[i])
        elif o == "dflt":
            self.emit("dflt")
            e.reg[4] = self.ssp
            p = self.s_omalloc(e)
            e.call(F_DFLT, p)
            self.dump_strip(p)
        elif o == "dtor":
            i, fl = int(a[1], 0), int(a[2], 0)
            self.emit("dtor S%d %d" % (i, fl))
            self.vcall(self.strips[i], 2288, fl)
        elif o == "elem":
            p = self.block(EL_SIZE)
            n = "X%d" % len(self.elems)
            self.names[p] = n
            self.names[p + 32] = n + ".m"
            self.names[p + 80] = n + ".p"
            self.elems.append(p)
            self.emit("elem %s" % n)
            e.call(F_ECTOR, p)
        elif o == "edel":
            i, fl = int(a[1], 0), int(a[2], 0)
            self.emit("edel X%d %d" % (i, fl))
            self.vcall(self.elems[i], 96, fl)
        elif o == "wo":
            p = self.block(96)
            n = "O%d" % len(self.wos)
            self.names[p] = n
            self.names[p + 32] = n + ".m"
            self.names[p + 80] = n + ".p"
            self.wos.append(p)
            mp = 0
            if a[3] != "none":
                mp = self.e.alloc(64, align=16)
                for i in range(16):
                    e.put32(mp + 4 * i, int(a[3 + i], 16))
            self.emit("wo %s" % n)
            e.call(F_WOCTOR, p, int(a[1], 16), mp, int(a[2], 0))
        elif o == "wonull":
            e.put32(self.wos[int(a[1], 0)] + 8, 0)
        elif o == "wodel":
            i, fl = int(a[1], 0), int(a[2], 0)
            self.emit("wodel O%d %d" % (i, fl))
            e.call(F_WODTOR, self.wos[i], fl)
        elif o == "list":
            self.dump_list()
        elif o == "strip":
            self.dump_strip(self.strips[int(a[1], 0)])
        elif o == "edump":
            self.dump_elem(self.elems[int(a[1], 0)])
        elif o == "wdump":
            p = self.wos[int(a[1], 0)]
            self.emit("wo %s%s" % (self.sym(p), self.wo_fields(p)))
        elif o == "cars":
            self.dump_cars()
        elif o == "view":
            # view|k|eye x|y|z|the WorldScreenClipMatrix's 16 words
            v = self.views[int(a[1], 0)]
            cam, clip = e.u32(v + 56), e.u32(v + 80)
            for i in range(3):
                e.put32(cam + 64 + 4 * i, int(a[2 + i], 16))
            for i in range(16):
                e.put32(clip + 4 * i, int(a[5 + i], 16))
        elif o == "curview":
            self.curview = self.views[int(a[1], 0)]
        elif o == "frame":
            # frame|start|room|failed|amount
            pos = self.fbase + int(a[1], 0)
            e.put32(G_FPOS, pos)
            e.put32(G_FEND, pos + int(a[2], 0))
            e.put32(G_FFAIL, int(a[3], 0))
            e.put32(G_FAMOUNT, int(a[4], 0))
        elif o == "fdump":
            self.emit("frame pos %d end %d failed %d amount %d" % (
                e.u32(G_FPOS) - self.fbase, e.u32(G_FEND) - self.fbase,
                s32(e.u32(G_FFAIL)), e.u32(G_FAMOUNT)))
        elif o == "msolid":
            s = int(a[2], 0)
            e.put32(e.u32(self.wos[int(a[1], 0)] + 8) + 12,
                    self.solids[s] if s >= 0 else 0)
        elif o == "allsolid":
            for m in self.models:
                e.put32(m + 12, self.solids[int(a[1], 0)])
        elif o == "pix":
            self.pixq.append(int(a[1], 0))
        elif o == "cls":
            self.clsq.append(int(a[1], 0))
        elif o == "wen":
            e.put32(self.wos[int(a[1], 0)] + 12, int(a[2], 0))
        elif o == "render":
            i, k = int(a[1], 0), int(a[2], 0)
            self.emit("render O%d V%d" % (i, k))
            e.call(F_RENDER, self.wos[i], self.views[k])
        elif o == "renderall":
            k = int(a[1], 0)
            self.emit("renderall V%d" % k)
            e.call(F_RENDERALL, self.views[k])
        else:
            raise ValueError("unknown op %s" % o)

    def run(self, lines):
        for line in lines:
            self.op(line.split("|"))
        return self.out


def model(lines):
    return Model().run(lines)


# ================================================================== script

NAN, INF = float("nan"), float("inf")


def gv(*p):
    return ["gv|%s|%s|%s" % tuple(F(v) for v in p)]


def add(ax, ay, bx, by, rid, life):
    return ["add|%s|%s|%s|%s|%d|%s" % (F(ax), F(ay), F(bx), F(by), rid,
                                       F(life))]


def lay(p0, p1, rid, life, ends=(1.0, 2.0, 3.0, 4.0)):
    return gv(*p0) + gv(*p1) + add(*ends, rid=rid, life=life)


def cf(k, field, *vals):
    out = []
    for v in vals:
        out.append(F(v) if isinstance(v, float) else str(v))
    return ["cf|%d|%s|%s" % (k, field, "|".join(out))]


def wheel(k, w, base):
    vals = [base + 0.125 * i for i in range(16)]
    return cf(k, "wheel", w, *vals)


def car(k, x, y, z=0.5, dist=100.0, typ=0):
    s = cf(k, "pos", x, y, z) + cf(k, "vel", 20.0 + k, -3.0 + k, 0.25)
    s += cf(k, "body", *[0.5 * k + 0.0625 * i - 0.3 for i in range(12)])
    for w in range(4):
        s += wheel(k, w, 10.0 * k + w) + ["cf|%d|touch|%d|1" % (k, w)]
    s += cf(k, "dist", dist) + ["cf|%d|type|%d" % (k, typ),
                                "cf|%d|blinking|0" % k,
                                "cf|%d|pursued|0" % k,
                                "cf|%d|blown|0" % k, "cf|%d|nblown|0" % k]
    s += cf(k, "fwd", 25.0) + cf(k, "pot", 1e7) + ["cf|%d|act|-1" % k]
    return s


def ds(*v):
    return ["ds|%d" % x for x in v]


def world_objects():
    s = ["list", "initwo", "list"]
    s += ["wo|12345678|0|none", "wdump|0"]
    mat = [F(v) for v in (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0,
                          1.0, 0.0, 5.5, -3.25, 2.0, 1.0)]
    s += ["wo|deadbeef|1|" + "|".join(mat), "wdump|1", "wo|0|7|none",
          "list"]
    s += ["wodel|1|0", "list", "wdump|1", "wodel|0|1", "list",
          "wodel|2|3", "list"]
    # Bit 0 alone frees; and an object with no model.
    s += ["wo|0badf00d|0|none", "wo|00000001|-1|none", "list", "wodel|3|2",
          "wonull|4", "wodel|4|1", "list"]
    s += ["elem", "edump|0", "list", "elem", "list", "edel|0|1", "list",
          "edump|0", "edel|1|0", "list", "edump|1"]
    return s


GEOMETRY = [
    # p0, p1: the two ends on the road
    ((0.0, 0.0, 0.0), (6.5, 0.0, 0.0)),
    ((10.0, 20.0, 1.0), (13.0, 24.0, 1.5)),
    ((-5.0, -5.0, 0.0), (30.0, 40.0, 2.0)),
    ((1.0, 1.0, 1.0), (1.0, 1.0, 1.0)),
    ((0.0, 0.0, 0.0), (0.0, 0.0, 5.0)),
    ((100.0, -50.0, 3.0), (100.3, -50.2, 3.0)),
    ((0.0, 0.0, 0.0), (13.0, 0.0, 0.0)),
    ((0.0, 0.0, 0.0), (13.65, 0.0, 0.0)),
    ((0.0, 0.0, 0.0), (0.65, 0.0, 0.0)),
    ((7.0, -2.0, 0.25), (-1.0, 4.0, -0.75)),
    ((0.0, 0.0, 0.0), (0.0, -9.75, 0.0)),
    ((3.0, 3.0, 0.0), (3.0, 3.0, -4.0)),
    # Ends whose length rounds by the order the squares are summed in.
    ((-17.68, 0.3, -18.5), (-2.65, -17.21, -16.37)),
    ((15.02, -7.45, 7.81), (3.77, 3.2, -1.75)),
    ((13.15, -13.54, -19.08), (18.04, 1.13, -14.14)),
    ((0.0, 0.0, 0.0), (1e-3, 7.77, 3.1e-2)),
]
LIVES = [5.0, 0.0, -1.0, NAN, 0.25, 1.0, INF, 3.0, 2.0, 0.5, 1e-30, 9.0,
         4.0, 4.0, 4.0, 4.0]


def laying():
    s = ["wte|%s" % F(0.25)]
    for i, (p0, p1) in enumerate(GEOMETRY):
        # The game's pool zero-fills; two strips come from a dirty one.
        s += ["fill|%s" % ("cd" if i in (3, 11) else "0")]
        s += lay(p0, p1, 100 + i, LIVES[i],
                 (i * 1.5, -i * 0.5, i * 2.0 + 1.0, 3.0))
        s += ["strip|%d" % i, "list"]
    s += ["fill|0"]
    # No queued points: the ends as given, z a quarter of x.
    n = len(GEOMETRY)
    s += add(3.0, 4.0, 9.0, 12.0, -7, 4.0) + ["strip|%d" % n]
    s += add(-3.0, 4.0, -3.0, 4.0, 0x7fffffff, 1.0) + ["strip|%d" % (n + 1),
                                                       "list"]
    return s


def lifetimes():
    s = ["wte|%s" % F(0.25)]
    s += ["update|0", "update|0", "strip|0"]
    s += ["update|4", "strip|4"]
    s += ["wte|%s" % F(0.75)]
    for _ in range(4):
        s += ["update|4", "strip|4"]
    s += ["update|1", "update|2", "update|3", "strip|1", "strip|3"]
    s += ["poof|1", "strip|1", "update|1", "strip|1", "update|1"]
    s += ["wte|%s" % F(2.0), "update|1", "strip|1"]
    s += ["wte|%s" % F(1.0), "update|5", "strip|5", "update|5", "update|5"]
    s += ["wte|%s" % F(NAN), "update|0", "strip|0", "update|0", "strip|0"]
    s += ["wte|%s" % F(0.5), "update|6", "strip|6", "update|10", "strip|10"]
    # A blinking strip laid again keeps its blink.
    s += gv(2.0, 2.0, 0.0) + gv(5.0, 6.0, 0.0)
    s += ["init|1|%s|%s|%s|%s|55|%s" % (F(1.0), F(1.0), F(4.0), F(5.0),
                                        F(8.0)), "strip|1"]
    s += gv(0.0, 0.0, 0.0) + gv(30.0, 0.0, 0.0)
    s += ["init|8|%s|%s|%s|%s|-3|%s" % (F(0.0), F(0.0), F(30.0), F(0.0),
                                        F(-2.0)), "strip|8"]
    s += ["dtor|2|0", "list", "strip|2", "dtor|3|1", "list"]
    return s


def monitors():
    s = ["mreset", "wte|%s" % F(0.125), "beacop|0", "copidx|0", "diff|0",
         "cop|0|5", "cop|1|4"]
    for k in range(NCARS):
        s += car(k, 5.0, 2.0 + k)
    s += ["cf|5|player|1"]
    # The strip, (0, 0) to (10, 0), its middle (5, 0).
    s += gv(0.0, 0.0, 0.0) + gv(10.0, 0.0, 0.0)
    s += add(0.0, 0.0, 10.0, 0.0, 9, 100.0)
    st = len(GEOMETRY) + 2

    def mon(*answers):
        return ds(*answers) + ["monitor", "cars", "dsclear"]

    # ---- no cars, then the ones the checks pass over
    s += ["ncars|0", "monitor"]
    s += ["ncars|4", "table|0|0", "table|1|1", "table|2|2", "table|3|3"]
    s += cf(0, "dist", 250.0) + ["cf|1|blinking|1"] + cf(2, "pos", 5.0,
                                                          40.0, 0.0)
    s += ["cf|3|type|2", "cf|3|touch|2|0"]
    s += mon(1, 0, 1)
    # Its tires again: those bits are blown, so nothing; then one more,
    # with two already blown, blown with no reaction.
    s += mon(1, 0, 1) + mon(0, 1, 0)
    s += cf(0, "dist", 249.99998) + cf(2, "pos", 5.0, 39.999996, 0.0)
    s += ["cf|0|touch|0|0", "cf|0|touch|1|0", "cf|0|touch|2|0",
          "cf|0|touch|3|0"]
    s += ["cf|2|touch|3|0", "cf|2|type|2", "cf|2|pursued|1"]
    s += ["cf|3|blown|0", "cf|3|nblown|0x80"]
    s += mon(0, 0, 1, 1, 0, 0)
    s += ["cf|3|nblown|0", "cf|3|blown|0", "cf|3|pursued|1", "cf|2|blown|0",
          "cf|2|nblown|0"]
    s += mon(0, 0, 1, 1, 1, 1)
    s += ["cf|3|blown|0", "cf|3|nblown|0", "cf|3|pursued|0",
          "cf|3|ctl|1"] + cf(3, "pot", 2.5)
    s += mon(0, 0, 0, 0, 1, 0, 0)

    # ---- Be A Cop: the difficulties, the racer chased and not
    s += ["beacop|1", "ncars|1", "table|0|3", "cf|3|act|-1"]
    s += cf(3, "pot", 1e7)
    for d in (0, 1, 2):
        s += ["diff|%d" % d, "cf|3|blown|0", "cf|3|nblown|0"]
        s += ["cf|3|racing|%d" % (d & 1), "cf|3|pursued|%d" % (d >> 1)]
        s += mon(1, 1, 1)
    s += ["cf|3|blown|0", "cf|3|nblown|0", "cf|3|racing|1",
          "cf|3|pursued|1", "diff|1"] + mon(0, 0, 1)

    # ---- players, the player's cop, traffic
    s += ["beacop|0", "ncars|1", "table|0|4", "cf|4|player|1"]
    for typ, fwd, pursued in ((0, 25.0, 0), (0, 20.0, 1), (1, NAN, 0),
                              (0, 20.000002, 1), (3, 30.0, 0),
                              (2, 30.0, 1)):
        s += ["cf|4|type|%d" % typ, "cf|4|pursued|%d" % pursued,
              "cf|4|blown|0", "cf|4|nblown|0"] + cf(4, "fwd", fwd)
        s += mon(1, 0, 0, 0)
    s += ["cf|4|player|0", "cf|4|type|3", "cf|4|blown|0", "cf|4|nblown|0"]
    s += mon(0, 0, 0, 1)
    s += ["beacop|1", "copidx|0", "ncars|2", "table|0|5", "table|1|4",
          "cf|4|player|1", "cf|4|racing|1", "cf|4|type|0",
          "cf|4|pursued|1", "cf|5|type|1"]
    s += ["cf|4|blown|0", "cf|4|nblown|0"] + mon(1, 0, 0, 0, 0, 1, 0, 0)
    s += ["copidx|1", "cf|5|blown|0", "cf|5|nblown|0", "cf|4|blown|0",
          "cf|4|nblown|0"] + cf(4, "fwd", 5.0)
    s += mon(0, 0, 1, 0, 0, 0, 1, 0)
    s += ["cop|1|5", "cf|5|player|0", "cf|5|blown|0", "cf|5|nblown|0"]
    s += mon(0, 1, 0, 0, 0, 0, 0, 0)

    # ---- a strip that ends during the watch, and two strips
    s += ["beacop|0", "ncars|1", "table|0|3", "cf|3|type|2",
          "cf|3|pursued|0"]
    s += gv(20.0, 0.0, 0.0) + gv(20.0, 6.0, 0.0)
    s += add(20.0, 0.0, 20.0, 6.0, 10, 0.0)
    s += ["list", "poof|%d" % (st + 1), "wte|%s" % F(2.5)]
    s += ["cf|3|blown|0", "cf|3|nblown|0"] + mon(0, 1, 0, 0)
    s += ["list"]
    s += gv(20.0, 0.0, 0.0) + gv(20.0, 6.0, 0.0)
    s += add(4.0, -1.0, 6.0, 1.0, 11, 0.0)
    s += ["wte|%s" % F(0.125), "cf|3|blown|0", "cf|3|nblown|0"]
    s += mon(0, 0, 0, 1, 1, 0, 0, 0)
    s += ["list", "strip|%d" % st]
    return s


def rendering():
    o = sum(1 for x in world_objects() if x.startswith("wo|"))
    a, b, c, d = o, o + 1, o + 2, o + 3

    def view(k, eye, base, step):
        return ["view|%d|%s|%s" % (
            k, "|".join(F(v) for v in eye),
            "|".join(F(base + step * i) for i in range(16)))]

    def mat(i):
        return "|".join(F(0.25 * j - 1.0 + 3.0 * i) for j in range(16))

    def r(i, k):
        return ["render|%d|%d" % (i, k)]

    s = view(0, (12.5, -7.25, 3.0), 0.5, 0.25)
    s += view(1, (-40.0, 8.5, -1.5), -2.0, 0.375)
    s += ["curview|0", "frame|0|%d|0|0" % 4096]
    # Unlit, lit, lit by a negative, and one with no matrix.
    s += ["wo|51515151|0|" + mat(0), "wo|52525252|1|" + mat(1),
          "wo|53535353|-3|" + mat(2), "wo|54545454|0|none"]
    # No solid: out of sight, once it is big enough to ask.
    s += r(a, 0) + ["pix|1"] + r(a, 0) + ["fdump"]
    s += ["msolid|%d|0" % a, "msolid|%d|1" % b, "msolid|%d|2" % c,
          "msolid|%d|3" % d]
    # The pixel size at its boundary, at 0, below it and at the ends.
    for px in (1, 2, -5, 0, 3, 0x7fffffff, -0x80000000):
        s += ["pix|%d" % px] + r(a, 0)
    s += ["fdump"]
    # ClassifyAABB's answers; the current view not the one drawn.
    for cl in (0, 1, 2, -1):
        s += ["cls|%d" % cl] + r(a, 1)
    s += ["curview|1"] + r(a, 0) + r(b, 0) + ["curview|0"] + r(b, 1)
    s += r(c, 1) + r(c, 0) + ["fdump"]
    s += ["cls|0"] + r(b, 0) + ["pix|1"] + r(c, 0)
    s += ["msolid|%d|-1" % b] + r(b, 0) + ["msolid|%d|1" % b]
    # Frame memory: the matrix's 64 bytes and the light context's 288,
    # each failing with room for exactly that and drawing with a byte more.
    for start, room, obj in ((16, 64, a), (16, 65, a), (0, 0, a),
                             (0, 64, b), (32, 352, b), (32, 353, b),
                             (48, 65, b), (48, 128, c), (0, 1, a)):
        s += ["frame|%d|%d|0|%d" % (start, room, start * 3)] + r(obj, 0)
        s += ["fdump"]
    # Already failed this frame; the amount wraps.
    s += ["frame|0|10|1|4294967200"] + r(b, 0) + r(a, 0) + ["fdump"]
    # RenderWorldObjects: the strips' pieces, then these four, some off.
    s += ["allsolid|2", "wen|%d|0" % a, "wen|%d|2" % b, "wen|%d|-1" % c,
          "wen|%d|1" % d]
    s += ["frame|0|4096|0|0", "pix|1", "cls|0", "renderall|0", "fdump"]
    s += ["frame|0|4096|0|0", "curview|1", "renderall|0", "fdump"]
    s += ["frame|0|2048|0|0", "renderall|1", "fdump", "curview|0"]
    return s


def defaults():
    # The replay's constructor (72e-3): from a dirty pool and a clean one,
    # every field but the table and the pieces' left as the pool had it.
    return ["fill|cd", "dflt", "fill|0", "dflt", "list"]


def script():
    s = world_objects() + laying() + lifetimes() + monitors() + rendering()
    s += defaults()
    s += ["closewo", "list", "renderall|0", "initwo", "list"]
    return s


# ================================================================== build

def build_harness(tmp, name="spikestrip_test"):
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

S = SPIKE
W = WOBJ
MUTATIONS = [
    # ---- WorldObject
    ("wo_name_kept", W, "    m->NameHash = 0;\n", ""),
    ("wo_solid_kept", W, "    m->Solid = NULL;\n", ""),
    ("wo_enabled_always", W,
     "    } else {\n        o->Enabled = 0;\n",
     "    } else {\n        o->Enabled = 1;\n"),
    ("wo_no_matrix", W, "        o->Matrix = *matrix;\n", ""),
    ("wo_light_0", W, "    o->AddLighting = add_lighting;\n",
     "    o->AddLighting = 0;\n"),
    ("wo_head_insert", W,
     "    tail = WorldObjectList.prev;\n    tail->next = &o->Node;\n"
     "    WorldObjectList.prev = &o->Node;\n    o->Node.prev = tail;\n"
     "    o->Node.next = &WorldObjectList;\n",
     "    tail = WorldObjectList.next;\n    tail->prev = &o->Node;\n"
     "    WorldObjectList.next = &o->Node;\n"
     "    o->Node.next = tail;\n    o->Node.prev = &WorldObjectList;\n"),
    ("wo_prev_list", W, "    o->Node.prev = tail;\n",
     "    o->Node.prev = &WorldObjectList;\n"),
    ("wo_dtor_null_model", W,
     "    if (o->pModel != NULL)\n        model_destroy(", "    model_destroy("),
    ("wo_dtor_model_0", W, "        model_destroy((eModel *)o->pModel, 3);",
     "        model_destroy((eModel *)o->pModel, 0);"),
    ("wo_dtor_no_unlink", W,
     "    prev->next = next;\n    next->prev = prev;\n", ""),
    ("wo_dtor_half_unlink", W, "    next->prev = prev;\n", ""),
    ("wo_dtor_any_flag", W,
     "    if (flags & 1)\n        bSlotFree(WorldObjectSlotPool, o);",
     "    if (flags)\n        bSlotFree(WorldObjectSlotPool, o);"),
    ("wo_dtor_no_free", W,
     "    if (flags & 1)\n        bSlotFree(WorldObjectSlotPool, o);", ""),
    ("wo_pool_64", W, "sizeof(WorldObject), 128,", "sizeof(WorldObject), 64,"),
    ("wo_pool_num", W, '"WorldObjectSlotPool", 16);',
     '"WorldObjectSlotPool", 0);'),
    ("wo_close_flags_0", W,
     "worldobject_destruct((WorldObject *)(void *)WorldObjectList.next, 3);",
     "worldobject_destruct((WorldObject *)(void *)WorldObjectList.next, 0);"),
    ("wo_close_no_delete", W, "    bDeleteSlotPool(WorldObjectSlotPool);\n",
     ""),
    ("wo_close_kept", W, "    WorldObjectSlotPool = NULL;\n", ""),

    # ---- the belt pieces
    ("el_name", S, 'bchunk_hash("SPIKEBELT_00")', 'bchunk_hash("SPIKEBELT_01")'),
    ("el_light", S, '"SPIKEBELT_00"), NULL, 0);', '"SPIKEBELT_00"), NULL, 1);'),
    ("el_no_vptr", S,
     "    worldobject_construct(&e->Base, bchunk_hash(\"SPIKEBELT_00\"), NULL, 0);\n"
     "    e->vptr = TSPIKESTRIPRENDERELEMENT_VTABLE;\n",
     "    worldobject_construct(&e->Base, bchunk_hash(\"SPIKEBELT_00\"), NULL, 0);\n"),
    ("eldtor_flags", S, "    worldobject_destruct(&e->Base, 0);",
     "    worldobject_destruct(&e->Base, flags);"),
    ("eldtor_no_free", S,
     "    if (flags & 1)\n        bSlotFree(WorldObjectSlotPool, e);", ""),
    ("eldtor_pool", S, "        bSlotFree(WorldObjectSlotPool, e);",
     "        bSlotFree(SpikeStripSlotPool, e);"),

    # ---- the constructor and Init
    ("ctor_19", S,
     "    for (k = 0; k < TSPIKESTRIP_MAX_ELEMENTS; k++)\n"
     "        tspikestriprenderelement_construct(&s->Elements[k]);\n"
     "    tspikestrip_init",
     "    for (k = 0; k < TSPIKESTRIP_MAX_ELEMENTS - 1; k++)\n"
     "        tspikestriprenderelement_construct(&s->Elements[k]);\n"
     "    tspikestrip_init"),
    ("ctor_no_vptr", S,
     "    s->vptr = TSPIKESTRIP_VTABLE;\n    for (k = 0; k < TSPIKESTRIP_MAX"
     "_ELEMENTS; k++)\n        tspikestriprenderelement_construct(&s->Elements"
     "[k]);\n    tspikestrip_init",
     "    for (k = 0; k < TSPIKESTRIP_MAX"
     "_ELEMENTS; k++)\n        tspikestriprenderelement_construct(&s->Elements"
     "[k]);\n    tspikestrip_init"),
    # The replay's default constructor (72e-3).
    ("dflt_19", S,
     "    for (k = 0; k < TSPIKESTRIP_MAX_ELEMENTS; k++)\n"
     "        tspikestriprenderelement_construct(&s->Elements[k]);\n"
     "    return s;",
     "    for (k = 0; k < TSPIKESTRIP_MAX_ELEMENTS - 1; k++)\n"
     "        tspikestriprenderelement_construct(&s->Elements[k]);\n"
     "    return s;"),
    ("dflt_from_1", S,
     "    for (k = 0; k < TSPIKESTRIP_MAX_ELEMENTS; k++)\n"
     "        tspikestriprenderelement_construct(&s->Elements[k]);\n"
     "    return s;",
     "    for (k = 1; k < TSPIKESTRIP_MAX_ELEMENTS; k++)\n"
     "        tspikestriprenderelement_construct(&s->Elements[k]);\n"
     "    return s;"),
    ("dflt_no_vptr", S,
     "tspikestrip_construct_default(tSpikeStrip *s)\n{\n    int32_t k;\n\n"
     "    s->vptr = TSPIKESTRIP_VTABLE;\n",
     "tspikestrip_construct_default(tSpikeStrip *s)\n{\n    int32_t k;\n\n"),
    ("init_no_id", S, "    s->nRoadBlockID = id;\n", ""),
    ("init_no_life", S, "    s->fLifetime = lifetime;\n", ""),
    ("init_ends_swapped", S,
     "    get_vector_on_track(&p0, &s->v2Start);\n"
     "    get_vector_on_track(&p1, &s->v2End);\n",
     "    get_vector_on_track(&p1, &s->v2End);\n"
     "    get_vector_on_track(&p0, &s->v2Start);\n"),
    ("init_gvot_raw", S, "    get_vector_on_track(&p0, &s->v2Start);",
     "    get_vector_on_track(&p0, a);"),
    ("len_sum_order", S, "    len = sqrtf((dx * dx + dy * dy) + dz * dz);",
     "    len = sqrtf(dx * dx + (dy * dy + dz * dz));"),
    ("len_no_z", S, "    len = sqrtf((dx * dx + dy * dy) + dz * dz);",
     "    len = sqrtf(dx * dx + dy * dy);"),
    ("inv_plain", S, "    inv = ee_div(1.0f, len);", "    inv = 1.0f / len;"),
    ("dir_sign", S, "    dir.x = (p1.x - p0.x) * inv;",
     "    dir.x = (p0.x - p1.x) * inv;"),
    ("dir_z_0", S, "    dir.z = (p1.z - p0.z) * inv;", "    dir.z = 0.0f;"),
    ("n_round", S, "    n = ee_trunc_w(len * 1.5384616f);",
     "    n = ee_trunc_w(len * 1.5384616f + 0.5f);"),
    ("n_const", S, "len * 1.5384616f)", "len * 1.5384615f)"),
    ("n_clamp_22", S, "    if (!(n < 21))\n", "    if (!(n < 22))\n"),
    ("n_clamp_19", S,
     "    if (!(n < 21))\n        s->nNumElements = TSPIKESTRIP_MAX_ELEMENTS;",
     "    if (!(n < 21))\n        s->nNumElements = 19;"),
    ("first_step_gone", S,
     "    p0.x = p0.x + dir.x * 0.65f;\n    p0.y = p0.y + dir.y * 0.65f;\n"
     "    p0.z = p0.z + dir.z * 0.65f;\n    if (!(n < 21))",
     "    if (!(n < 21))"),
    ("step_06", S,
     "        p0.x = p0.x + dir.x * 0.65f;\n        p0.y",
     "        p0.x = p0.x + dir.x * 0.6f;\n        p0.y"),
    ("up_down", S, "    up.z = 1.0f;\n", "    up.z = -1.0f;\n"),
    ("side_order", S, "    cross3(&side, &up, &dir);",
     "    cross3(&side, &dir, &up);"),
    ("up2_order", S, "    cross3(&up2, &dir, &side);",
     "    cross3(&up2, &side, &dir);"),
    ("q_plain", S,
     "    q = 0.0f + ee_div(1.0f, sqrtf((side.x * side.x + side.y * side.y)",
     "    q = 0.0f + (1.0f / sqrtf((side.x * side.x + side.y * side.y)"),
    ("q_unnormalised", S, "    side.y = side.y * q;\n", ""),
    ("cross_z_lane", S, "    float z = a->x * b->y - b->x * a->y;",
     "    float z = a->x * b->y + b->x * a->y;"),
    ("row_w_1", S, "    r->w = 0.0f;", "    r->w = 1.0f;"),
    ("v3_w_0", S, "        o->Matrix.v3.w = 1.0f;", "        o->Matrix.v3.w = 0.0f;"),
    ("rows_swapped", S,
     "        o->Matrix.v0 = r0;\n        o->Matrix.v1 = r1;\n",
     "        o->Matrix.v0 = r1;\n        o->Matrix.v1 = r0;\n"),
    ("enabled_2", S, "        o->Enabled = 1;\n        p0.x",
     "        o->Enabled = 2;\n        p0.x"),

    # ---- Update and BlinkBlinkPoof
    ("blink_lt", S, "        if (t <= 0.0f)\n            done = 1;",
     "        if (t < 0.0f)\n            done = 1;"),
    ("blink_no_store", S, "        s->fBlinkTimer = t;\n", ""),
    ("blink_all20", S,
     "        for (k = 0; k < s->nNumElements; k++) {\n"
     "            WorldObject *o = &s->Elements[k].Base;\n\n"
     "            o->Enabled = o->Enabled == 0;",
     "        for (k = 0; k < TSPIKESTRIP_MAX_ELEMENTS; k++) {\n"
     "            WorldObject *o = &s->Elements[k].Base;\n\n"
     "            o->Enabled = o->Enabled == 0;"),
    ("blink_on", S, "            o->Enabled = o->Enabled == 0;",
     "            o->Enabled = 1;"),
    ("blink_not_done", S, "        return done;\n", "        return 0;\n"),
    ("life_le", S, "    if (0.0f < s->fLifetime) {",
     "    if (0.0f <= s->fLifetime) {"),
    ("life_lt", S,
     "        if (t <= 0.0f)\n            tspikestrip_blink_blink_poof(s);",
     "        if (t < 0.0f)\n            tspikestrip_blink_blink_poof(s);"),
    ("life_no_store", S, "        s->fLifetime = t;\n", ""),
    ("life_done", S,
     "            tspikestrip_blink_blink_poof(s);\n    }\n    return 0;",
     "            tspikestrip_blink_blink_poof(s);\n    }\n"
     "    return s->bIsBlinking;"),
    ("poof_1", S, "    s->fBlinkTimer = 2.0f;", "    s->fBlinkTimer = 1.0f;"),
    ("poof_no_flag", S, "    s->bIsBlinking = 1;\n", ""),

    # ---- the destructor
    ("dtor_forward", S,
     "    for (k = TSPIKESTRIP_MAX_ELEMENTS - 1; k >= 0; k--) {",
     "    for (k = 0; k < TSPIKESTRIP_MAX_ELEMENTS; k++) {"),
    ("dtor_flags", S, "        ((DtorFn)v->fn)(vt_this(e, v), 0);",
     "        ((DtorFn)v->fn)(vt_this(e, v), flags);"),
    ("dtor_no_free", S,
     "    if (flags & 1)\n        bSlotFree(SpikeStripSlotPool, s);", ""),
    ("dtor_19", S,
     "    for (k = TSPIKESTRIP_MAX_ELEMENTS - 1; k >= 0; k--) {",
     "    for (k = TSPIKESTRIP_MAX_ELEMENTS - 1; k > 0; k--) {"),

    # ---- AddSpikeStrip
    ("add_tail", S,
     "    old = m->SpikeStripList.Next;\n    m->SpikeStripList.Next = &s->Node;\n"
     "    old->Prev = &s->Node;\n    s->Node.Prev = &m->SpikeStripList;\n"
     "    s->Node.Next = old;\n",
     "    old = m->SpikeStripList.Prev;\n    m->SpikeStripList.Prev = &s->Node;\n"
     "    old->Next = &s->Node;\n    s->Node.Next = &m->SpikeStripList;\n"
     "    s->Node.Prev = old;\n"),
    ("add_prev_old", S, "    s->Node.Prev = &m->SpikeStripList;",
     "    s->Node.Prev = old;"),
    ("add_no_back", S, "    old->Prev = &s->Node;\n", ""),

    # ---- MonitorSpikeBelts
    ("mon_no_unlink", S, "            pv->Next = nx;\n            nx->Prev = pv;\n",
     ""),
    ("mon_dtor_0", S, "            ((DtorFn)v->fn)(vt_this(s, v), 3);",
     "            ((DtorFn)v->fn)(vt_this(s, v), 0);"),
    ("mon_done_watched", S,
     "            ((DtorFn)v->fn)(vt_this(s, v), 3);\n            continue;\n",
     "            ((DtorFn)v->fn)(vt_this(s, v), 3);\n"),
    ("mon_mid_quarter", S, "        mid.x = start.x + d.x * 0.5f;",
     "        mid.x = start.x + d.x * 0.25f;"),
    ("mon_d_reversed", S, "        d.x = s->v2End.x - s->v2Start.x;",
     "        d.x = s->v2Start.x - s->v2End.x;"),
    ("mon_cars_minus_1", S, "        for (i = 0; i < ncars; i++)",
     "        for (i = 0; i < ncars - 1; i++)"),
    ("car_dist_le", S, "              w, (const bVector2 *)(const void *)pos) < 250.0f))",
     "              w, (const bVector2 *)(const void *)pos) <= 250.0f))"),
    ("car_no_blink", S, "    if (car_is_blinking(car))\n        return;\n", ""),
    ("car_mid_le", S, "    if (!(sqrtf(dx * dx + dy * dy) < 40.0f))",
     "    if (!(sqrtf(dx * dx + dy * dy) <= 40.0f))"),
    ("car_mid_squared", S, "    if (!(sqrtf(dx * dx + dy * dy) < 40.0f))",
     "    if (!(dx * dx + dy * dy < 40.0f))"),
    ("car_mid_x_only", S, "    dy = mid->y - pos->y;\n", "    dy = 0.0f;\n"),
    ("car_mv_unscaled", S, "    mv.x = car->State.Velocity.x * wte;",
     "    mv.x = car->State.Velocity.x;"),
    ("car_mv_y_x", S, "    mv.y = car->State.Velocity.y * wte;",
     "    mv.y = car->State.Velocity.x * wte;"),
    ("car_body_w0", S, "    body.v3.w = 1.0f;", "    body.v3.w = 0.0f;"),
    ("car_body_v3", S, "    body.v3.x = pos->x;",
     "    body.v3.x = car->State.BodyMatrix.v3.x;"),
    ("car_body_row", S, "    body.v1 = car->State.BodyMatrix.v1;",
     "    body.v1 = car->State.BodyMatrix.v0;"),
    ("car_all_wheels", S,
     "        if (car->State.WheelTouchingGround[k] == 0)\n            continue;\n",
     ""),
    ("car_wheel_0", S, "eMulMatrix(&r, &car->State.WheelMatrix[k], &body);",
     "eMulMatrix(&r, &car->State.WheelMatrix[0], &body);"),
    ("car_p_y", S, "        p.y = r.v3.y;", "        p.y = r.v3.z;"),
    ("car_dsi_order", S, "        if (do_segments_intersect(&p, &mv, start, d))",
     "        if (do_segments_intersect(start, d, &p, &mv))"),
    ("car_bit_shift", S, "            bits |= 1 << k;", "            bits |= 2 << k;"),
    ("car_subset_any", S, "    if ((car->BlownTireBits & bits) == bits)",
     "    if ((car->BlownTireBits & bits) != 0)"),
    ("car_old_after", S,
     "    old = (int8_t)car->NumBlownTires;\n"
     "    car_trigger_tire_blow_out(car, bits);\n",
     "    car_trigger_tire_blow_out(car, bits);\n"
     "    old = (int8_t)car->NumBlownTires;\n"),
    ("car_react_always", S, "    if (old != 0)\n        return;\n    react", "    react"),

    # ---- the reaction
    ("react_ai_not", S,
     "    if (car->MyDriver->TheDriverType == DRIVER_TYPE_AI_RACER) {",
     "    if (car->MyDriver->TheDriverType != DRIVER_TYPE_AI_RACER) {"),
    ("react_pull_2", S, "                                            3.0f);",
     "                                            2.0f);"),
    ("react_no_pull", S,
     "            aicarcontroller_force_pull_over((AICarController *)(void *)ctl,\n"
     "                                            3.0f);\n", ""),
    ("react_boost_05", S, "            force_boost(ctl, 0.4f);",
     "            force_boost(ctl, 0.5f);"),
    ("react_table", S, "{ 0.3f, 0.4f, 0.5f }", "{ 0.4f, 0.3f, 0.5f }"),
    ("react_table_top", S, "{ 0.3f, 0.4f, 0.5f }", "{ 0.3f, 0.4f, 0.6f }"),
    ("react_beacop_pull", S,
     "        } else {\n            force_boost(ctl, BeACopSpikeBoost",
     "        } else {\n            aicarcontroller_force_pull_over("
     "(AICarController *)(void *)ctl, 3.0f);\n"
     "            force_boost(ctl, BeACopSpikeBoost"),
    ("zone_le", S, "20.0f < car->State.ForwardSpeed",
     "20.0f <= car->State.ForwardSpeed"),
    ("zone_any_car", S,
     "    } else if (car->pPlayer != NULL && 20.0f < car->State.ForwardSpeed) {",
     "    } else if (20.0f < car->State.ForwardSpeed) {"),
    ("zone_args", S, "PLAYER_ZONE_SLOMO_SHORT, 0, 1, 1);",
     "PLAYER_ZONE_SLOMO_SHORT, 1, 1, 1);"),
    ("zone_after_ai", S,
     "    } else if (car->pPlayer != NULL && 20.0f < car->State.ForwardSpeed) {",
     "    }\n    if (car->pPlayer != NULL && 20.0f < car->State.ForwardSpeed) {"),
    ("cop_index_0", S, "        Car           *copcar = m->Cops[m->nPlayerCopIndex]->pMyCar;",
     "        Car           *copcar = m->Cops[0]->pMyCar;"),
    ("cop_player_own", S, "        struct Player *pl = copcar->pPlayer;",
     "        struct Player *pl = car->pPlayer;"),
    ("cop_not_copcar", S, "        if (car == copcar) {", "        if (car != copcar) {"),
    ("cop_no_pullover", S,
     "            create_pullover(m, car);\n"
     "            player_start_score(pl, SCORING_BLEW_YOUR_TIRES);",
     "            player_start_score(pl, SCORING_BLEW_YOUR_TIRES);"),
    ("cop_scores_swapped", S, "player_start_score(pl, SCORING_BLEW_YOUR_TIRES);",
     "player_start_score(pl, SCORING_BLEW_THE_TIRES);"),
    ("cop_no_racing", S,
     "        } else if (car->pRacingCar != NULL\n"
     "                   && copmanager_is_being_pursued(m, car) != NULL) {",
     "        } else if (copmanager_is_being_pursued(m, car) != NULL) {"),
    ("cop_not_pursued", S, "                   && copmanager_is_being_pursued(m, car) != NULL) {",
     "                   && copmanager_is_being_pursued(m, car) == NULL) {"),
    ("free_no_player", S,
     "    } else if ((car->pPlayer != NULL\n"
     "                || car->MyDriver->TheDriverType == DRIVER_TYPE_AI_RACER)",
     "    } else if ((car->MyDriver->TheDriverType == DRIVER_TYPE_AI_RACER)"),
    ("free_no_ai", S,
     "                || car->MyDriver->TheDriverType == DRIVER_TYPE_AI_RACER)\n"
     "               && copmanager_is_being_pursued(m, car) == NULL) {",
     "               )\n"
     "               && copmanager_is_being_pursued(m, car) == NULL) {"),
    ("free_pursued", S, "               && copmanager_is_being_pursued(m, car) == NULL) {",
     "               && copmanager_is_being_pursued(m, car) != NULL) {"),
    ("pullover_args", S, "        gCopManagerCreatePulloverFn(m, NULL, car, 0);",
     "        gCopManagerCreatePulloverFn(m, NULL, car, 1);"),
    ("boost_no_delta", S, "    ((ForceBoostFn)e->fn)(vt_this(ctl, e), f);",
     "    ((ForceBoostFn)e->fn)(ctl, f);"),
    # ---- WorldObject::Render, RenderWorldObjects
    ("ren_pix_le", W, "20.0f) < 2)", "20.0f) <= 2)"),
    ("ren_pix_lt1", W, "20.0f) < 2)", "20.0f) < 1)"),
    ("ren_pix_radius", W, "20.0f)", "20.5f)"),
    ("ren_pix_point", W, "&o->Matrix.v3", "&o->Matrix.v2"),
    ("ren_pix_curview", W, "            view, (const bVector3 *)",
     "            eGetCurrentView(), (const bVector3 *)"),
    ("ren_vis_nosolid", W, "    if (s == NULL)\n        return 0;",
     "    if (s == NULL)\n        return 1;"),
    ("ren_vis_wv", W, "eGetCurrentView()->WorldScreenClipMatrix",
     "eGetCurrentView()->WorldViewMatrix"),
    ("ren_vis_order", W,
     "eMulMatrix(&clip, matrix, eGetCurrentView()->WorldScreenClipMatrix);",
     "eMulMatrix(&clip, eGetCurrentView()->WorldScreenClipMatrix, matrix);"),
    ("ren_vis_gt0", W, "&clip) != 0;", "&clip) > 0;"),
    ("ren_vis_eq2", W, "&clip) != 0;", "&clip) == 2;"),
    ("ren_vis_minmax", W, "&s->AABBMin, &s->AABBMax",
     "&s->AABBMax, &s->AABBMin"),
    ("ren_frame_48", W, "eframe_malloc(64)", "eframe_malloc(48)"),
    ("ren_light_256", W, "eframe_malloc(288)", "eframe_malloc(256)"),
    ("ren_no_copy", W, "    *m = o->Matrix;\n", ""),
    ("ren_m_fail", W, "    if (m == NULL)\n        return;\n",
     "    if (m == NULL)\n        m = &o->Matrix;\n"),
    ("ren_lit_inverted", W, "if (o->AddLighting == 0) {",
     "if (o->AddLighting != 0) {"),
    ("ren_lit_positive", W, "if (o->AddLighting == 0) {",
     "if (o->AddLighting <= 0) {"),
    ("ren_lc_fail", W, "    if (lc == NULL)\n        return;\n", ""),
    ("ren_eye_w", W, "    eye.w = 1.0f;", "    eye.w = 0.0f;"),
    ("ren_eye_x", W, "eye.x = cam->CurrentKey.Position.x;",
     "eye.x = cam->CurrentKey.Position.y;"),
    ("ren_eye_z", W, "eye.z = cam->CurrentKey.Position.z;",
     "eye.z = cam->CurrentKey.Direction.z;"),
    ("ren_hack_clip", W, "view->WorldViewMatrix, &eye",
     "view->WorldScreenClipMatrix, &eye"),
    ("ren_light_curview", W, "&eye, view);", "&eye, eGetCurrentView());"),
    ("ren_light_world", W, "el_setup_light_context(lc, m,",
     "el_setup_light_context(lc, &o->Matrix,"),
    ("ren_flags_4", W, "gEModelRenderFn(m, matrix, light, 0);",
     "gEModelRenderFn(m, matrix, light, 4);"),
    ("ren_lit_no_lc", W, "model_render((eModel *)o->pModel, m, lc);",
     "model_render((eModel *)o->pModel, m, NULL);"),
    ("ren_unlit_world", W, "model_render((eModel *)o->pModel, m, NULL);",
     "model_render((eModel *)o->pModel, &o->Matrix, NULL);"),
    ("all_enabled_gt0", W, "if (o->Enabled != 0)", "if (o->Enabled > 0)"),
    ("all_enabled_eq1", W, "if (o->Enabled != 0)", "if (o->Enabled == 1)"),
    ("all_every", W,
     "        if (o->Enabled != 0)\n            worldobject_render(o, view);",
     "        worldobject_render(o, view);"),
    ("all_curview", W, "            worldobject_render(o, view);",
     "            worldobject_render(o, eGetCurrentView());"),
    ("all_reverse", W,
     "n = WorldObjectList.next; n != &WorldObjectList; n = n->next",
     "n = WorldObjectList.prev; n != &WorldObjectList; n = n->prev"),
]

EQUIVALENT = {
    "inv_plain": "ee_div differs from IEEE only when the length is 0, "
                 "and then the count is 0 either way: no piece is written",
}


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
        todo, SOURCES, "spikestrip_test",
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
    got = model(lines)
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
