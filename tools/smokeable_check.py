#!/usr/bin/env python3
"""Cross-check 3DS Files/source/smokeable.c and smokeableinfo.c, the
Smokeables (Smokeable.obj, retail 0x0021ec80 .. 0x002220e8), against the
retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own code: the loader and unloader of chunk slot
27 with MemoryImageLoad and FindSmokeableInfo; GetSmokeableSpawner and its
inverse; InitSmokeables, SpawnSmokeables, ClearSmokeables,
DeleteSmokeableCollisionBodies and DeleteFarAwaySmokeableCollisionBodies;
the creators' table, BasicSmokeableCreator, the two spawns and the delete;
ConvertToSmokeable and VirginSmokeable's constructor, destructor and
ConvertToSmokeable; Smokeable's constructor and destructor,
SetInitialPosition, Calibrate, Move (with the air drag), PositionChanged,
ServiceEmitters, CheckTimers, ActivateAnchorEmitters, ConsiderImpulse,
ConsiderSleeping, PutToSleep, Awaken, Break, DoesChildArtExist,
TouchingCar, the system table's ComputeAuxiliaries (and the motion class
under it) and every accessor -- the methods reached through their tables
as the game reaches them. bSPrintf, bStringHash, the lists' and nodes'
destructors and RemoveHead run as shipped. The harness
(tools/src/smokeable_test.c) runs the port's two files and vtable.c and
prints the same lines.

**The stubs**, logged and answered by the same rule on both sides: the
topology coordinate (its constructor and destructor, GetElevation from a
queue, the interest boxes); the slot pools (blocks named by their pool,
fullness and free slots scripted); bMalloc; the collision bodies (the
next id from a queue, the static and dynamic constructors putting the
body on CollisionBodyList's head and the destructors taking it off,
BuildBoundingVolumes from a queue, the debug name, the box, the caffeine
plot, Find walking the list, GetCollision scripted per body); the physics
system (ComputeAuxiliaries setting the speeds from a queue); the rigid
body (its constructor, Calibrate, the tensor, SetState copying, the force
and the impulse); the emitters (afxGetEmitters making (hash & 3) of them,
copies, the effect system's two lists, the destructor); bPNode's Malloc
and Free; the world object (the hash kept per object, art scripted);
the polyhedra (the pipeline's scripted, the rectangle's constructor, the
destructor); the collision sound, the colliding cars and the distance to
the closest player, scripted; bSin, bCos, bIdentity, bMulMatrix (a queue,
else the vector with w 1) and eOrthonormalizeMatrix (a queue, else a
copy); and MatchTerrainType by a rule.

**Compared** are the stubs' logs and, by field at retail's offsets, the
smokeables, the virgins, the rigid bodies and the emitter copies,
CollisionBodyList, SmokeableInfoList with each info's children, terrain
and emitters, the scenery instances InitSmokeables rewrites, the
collision stats and the globals, the creators and the three tables
(retail's entries named from its symbols, the port's from its functions).

Retail leaves a few lanes as the stack had them, which are not compared:
the angular momentum's w that SetInitialPosition passes (and so the
backup velocity's w), the momenta's w once ComputeAuxiliaries has stopped
a settled smokeable, and the air drag's point's w.

    python tools/smokeable_check.py
    python tools/smokeable_check.py --mutate [--only a,b]
    python tools/smokeable_check.py --dump out/smokeable
"""
import argparse
import os
import re
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

HARNESS = "tools/src/smokeable_test.c"
SMOKE = "3DS Files/source/smokeable.c"
SINFO = "3DS Files/source/smokeableinfo.c"
SOURCES = [HARNESS, SMOKE, SINFO, "3DS Files/source/vtable.c",
           "3DS Files/source/bprintf.c"]
HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = retail_model.RETAIL_GP
G_VSP = GP - 15872                      # VirginSmokeableSlotPool
G_SSP = GP - 15868                      # SmokeableSlotPool
G_AWAKE = GP - 15864                    # AwakeSmokeablesCount
G_SPAWNERS = GP - 15860                 # pSmokeableSpawners
G_NSPAWNERS = GP - 15856                # NumSmokeableSpawners
G_SIL = GP - 15848                      # SmokeableInfoList
G_CBL = GP - 17792                      # CollisionBodyList
G_RBP = GP - 22832                      # RigidBodySlotPool
G_WORLD = GP - 22120                    # pCurrentWorld
G_TIMER = GP - 19576                    # WorldTimer
G_LOOP = GP - 19552                     # WorldLoopCounter
CREATORS = 0x0031c1e0
NPLAYERS = 0x0031a8c8                   # TheRaceParameters.NumPlayerCars
SECTIONS = 0x002f8fe8                   # ScenerySectionHeaderTable
NSECTIONS = 300
STATS = 0x00319e90                      # TheCollisionStats
ZEROV, ZEROM = 0x00319ee0, 0x00319f30
EFFECTS = 0x002ef640                    # WorldEffects

F_REGISTER = 0x0021ec80
F_CREATE = 0x0021ec98
F_BASIC = 0x0021ecd0
F_SPAWN = 0x0021ed28
F_SPAWNM = 0x0021eef8
F_DELETE = 0x0021ef88
F_SPAWNER = 0x0021eff8
F_SPIDX = 0x0021f018
F_LOADER = 0x0021f080
F_UNLOADER = 0x0021f1d0
F_INIT = 0x0021f270
F_CLOSE = 0x0021f500
F_DELALL = 0x0021f508
F_FARWAY = 0x0021f610
F_FIND = 0x0021f8f8
F_SPAWNALL = 0x0021f930
F_CLEAR = 0x0021faa8
F_CONVERT = 0x0021fe90
F_VCONVERT = 0x00220178
F_SETINIT = 0x00220a00
F_CALIB = 0x00220c50
F_POSCH = 0x00220f80
F_SVC = 0x00221060
F_TIMERS = 0x00221170
F_ACTIVATE = 0x002212d8
F_SLEEPCHK = 0x00221540
F_SLEEP = 0x00221670
F_AWAKEN = 0x00221690
F_BREAK = 0x00221748
F_CHILDART = 0x00221868
F_TOUCHING = 0x00221ae8
F_SETGR = 0x00221e68
F_GETGR = 0x00221e70
F_GETTC = 0x00221e78
F_ALIVE = 0x00221eb0
F_SETBLINK = 0x00221fd0

VT_SMOKE, VT_SYS, VT_VIRGIN = 0x002bcb10, 0x002bcaf0, 0x002bcbf0

S_TCINIT = 0x00151c28
S_TCDTOR = 0x00151c70
S_ELEV = 0x00152070
S_INTEREST = 0x00136e00
S_UNINTEREST = 0x00151cd0
S_FULL = 0x00257d10
S_FREESLOTS = 0x00257d28
S_OMALLOC = 0x00257c80
S_FREE = 0x00257ca0
S_NEWPOOL = 0x00257c10
S_DELPOOL = 0x00257c48
S_BMALLOC = 0x00257690
S_NEXTID = 0x001d6e20
S_DEBUGNAME = 0x001d6e30
S_FINDBODY = 0x001d6ee8
S_GETCOL = 0x001d6f38
S_BBOX = 0x001d6c50
S_CAFFEINE = 0x001d6e10
S_SINIT = 0x001d86d8
S_SDTOR = 0x001d8738
S_DINIT = 0x001d6fa8
S_DDTOR = 0x001d7028
S_BUILDBV = 0x001d7158
S_UPDPOS = 0x001d72f0
S_BEGINMOVE = 0x001d7368
S_PSINIT = 0x0019c170
S_PSFINI = 0x0019c190
S_ADDCOMP = 0x0019c238
S_EULER = 0x0019c290
S_AUX = 0x0019c808
S_RBINIT = 0x0019c9b0
S_RBCAL = 0x0019cc40
S_RBINERTIA = 0x0019cc58
S_RBSTATE = 0x0019cc88
S_RBFORCE = 0x0019cd90
S_RBIMPULSE = 0x0019cf10
S_ACOPY = 0x00127228
S_AGETS = 0x001272e0
S_ADELALL = 0x00127368
S_ADDAUTO = 0x001274a0
S_REMAUTO = 0x00127688
S_EMDEL = 0x00124e20
S_PMALLOC = 0x00250680
S_PFREE = 0x002506b0
S_WOCTOR = 0x001cd760
S_WODTOR = 0x001cd828
S_WOHASH = 0x001cd8a0
S_ART = 0x001cd8d0
S_PIPE = 0x00219078
S_RECT = 0x00218290
S_VCDTOR = 0x001d3240
S_TERRAIN = 0x001d4498
S_DIST = 0x0014e440
S_CARS = 0x0021eb48
S_SOUND = 0x001e55a8
S_SIN = 0x0025a540
S_COS = 0x0025a610
S_IDENTITY = 0x0025ac68
S_MULVEC = 0x0025aed0
S_ORTHO = 0x0011bd90

PHYSICSSYSTEM_VTABLE = 0x00298708
STATIC_VTABLE = 0x0029be78
DYNAMIC_VTABLE = 0x0029bcd8

SMOKE_SIZE, VIRGIN_SIZE, RB_SIZE = 1136, 100, 384
INFO_SIZE, EMITTER_SIZE, PNODE_SIZE = 224, 192, 12
BODY_SIZE, COL_SIZE, RECT_SIZE = 84, 64, 2800
HEADER_SIZE, INST_SIZE, SINFO_SIZE = 56, 48, 40
NCARS = 2
SYMS = ROOT / "out" / "retail_syms.txt"


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def bitsf(u):
    return struct.unpack("<f", struct.pack("<I", u & M32))[0]


def F(f):
    return "%08x" % fbits(f)


def retail_names():
    out = {}
    for line in open(SYMS, encoding="utf-8"):
        if line.startswith("#") or line.startswith("-"):
            continue
        f = line.split()
        if len(f) < 7:
            continue
        out[int(f[0], 16)] = f[6]
    # Unnamed leaves the symbol table lists as "new": IsBlinking (lb v0,
    # 1123(a0)) and the empty OnLifetimeEnd.
    out[0x00221fd8] = "IsBlinking__9Smokeable"
    out[0x002212d0] = "OnLifetimeEnd__9Smokeable"
    return out


def port_name(mangled):
    """`Method__<n>Class...` as the port names it: class_method."""
    if mangled is None or mangled.startswith("_$_"):
        return "local"
    # The replay's: Smokeable's and VirginSmokeable's are ported (TASKS
    # 72d-2), the munitions' not yet.
    if mangled.startswith("DoSnapshot__") and not mangled.startswith(
            ("DoSnapshot__9Smokeable", "DoSnapshot__15VirginSmokeable")):
        return "-"
    m = re.match(r"^(\w+?)__(\d+)(\w+)$", mangled)
    if m is None:
        return "local"
    cls = m.group(3)[:int(m.group(2))].lower()
    meth = re.sub(r"(?<!^)([A-Z])", r"_\1", m.group(1)).lower()
    return "%s_%s" % (cls, meth)


# ================================================================== model

class Model(object):
    def __init__(self):
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True,
                                            eesqrt=True)
        self.out = []
        self.names = {}
        self.byname = {}
        self.fill = 0xcd
        self.count = {}
        self.rnames = None
        # the scripted answers
        self.elevq, self.bvq, self.auxq, self.mvq, self.orthq = \
            [], [], [], [], []
        self.idq = []
        self.nextid = 100
        self.full = {}
        self.freeslots = 32
        self.noart, self.pipes, self.cnull = set(), set(), set()
        self.dist = {}
        self.cols = {}
        self.colcars = {}
        self.wohash = {}
        self.creatorret = 0
        self.pending = []
        self.infochunks, self.spchunks = [], []
        self.ninfo = self.nspawner = 0
        self.sections = {}

        def tok(n, size=16):
            p = e.alloc(size, align=16)
            e.write(p, bytes(size))
            self.name(p, n)
            return p

        self.vp, self.sp, self.rp, self.xp = (tok("VP"), tok("SP"),
                                              tok("RP"), tok("XP"))
        self.pp = tok("PP")
        self.world = tok("W")
        self.cars = [tok("A%d" % k) for k in range(NCARS)]
        self.stub_creator = tok("CREATOR")
        e.stub(self.stub_creator, self.s_creator)
        self.stub_lifeend = tok("LIFEEND")
        e.stub(self.stub_lifeend, self.s_lifeend)
        for a, n in ((G_CBL, "CBL"), (G_SIL, "SIL"), (EFFECTS, "WE"),
                     (ZEROV, "ZV"), (ZEROM, "ZM")):
            self.name(a, n)
        for a in (G_CBL, G_SIL):
            e.put32(a, a)
            e.put32(a + 4, a)
        for a in (G_VSP, G_SSP, G_AWAKE, G_SPAWNERS, G_NSPAWNERS, G_TIMER,
                  G_LOOP):
            e.put32(a, 0)
        e.put32(G_RBP, self.rp)
        e.put32(G_WORLD, self.world)
        e.put32(NPLAYERS, 1)
        e.write(CREATORS, bytes(16))
        e.write(STATS, bytes(72))
        e.write(SECTIONS, bytes(4 * NSECTIONS))
        for a, fn in ((S_TCINIT, self.s_tcinit), (S_TCDTOR, self.s_tcdtor),
                      (S_ELEV, self.s_elev), (S_INTEREST, self.s_interest),
                      (S_UNINTEREST, self.s_uninterest),
                      (S_FULL, self.s_full), (S_FREESLOTS, self.s_freeslots),
                      (S_OMALLOC, self.s_omalloc), (S_FREE, self.s_free),
                      (S_NEWPOOL, self.s_newpool),
                      (S_DELPOOL, self.s_delpool),
                      (S_BMALLOC, self.s_bmalloc),
                      (S_NEXTID, self.s_nextid),
                      (S_DEBUGNAME, self.s_debugname),
                      (S_FINDBODY, self.s_findbody),
                      (S_GETCOL, self.s_getcol), (S_BBOX, self.s_bbox),
                      (S_CAFFEINE, self.s_caffeine),
                      (S_SINIT, self.s_sinit), (S_SDTOR, self.s_sdtor),
                      (S_DINIT, self.s_dinit), (S_DDTOR, self.s_ddtor),
                      (S_BUILDBV, self.s_buildbv),
                      (S_UPDPOS, self.s_updpos),
                      (S_BEGINMOVE, self.s_beginmove),
                      (S_PSINIT, self.s_psinit), (S_PSFINI, self.s_psfini),
                      (S_ADDCOMP, self.s_addcomp), (S_EULER, self.s_euler),
                      (S_AUX, self.s_aux), (S_RBINIT, self.s_rbinit),
                      (S_RBCAL, self.s_rbcal),
                      (S_RBINERTIA, self.s_rbinertia),
                      (S_RBSTATE, self.s_rbstate),
                      (S_RBFORCE, self.s_rbforce),
                      (S_RBIMPULSE, self.s_rbimpulse),
                      (S_ACOPY, self.s_acopy), (S_AGETS, self.s_agets),
                      (S_ADELALL, self.s_adelall),
                      (S_ADDAUTO, self.s_addauto),
                      (S_REMAUTO, self.s_remauto), (S_EMDEL, self.s_emdel),
                      (S_PMALLOC, self.s_pmalloc), (S_PFREE, self.s_pfree),
                      (S_WOCTOR, self.s_woctor), (S_WODTOR, self.s_wodtor),
                      (S_WOHASH, self.s_wohash), (S_ART, self.s_art),
                      (S_PIPE, self.s_pipe), (S_RECT, self.s_rect),
                      (S_VCDTOR, self.s_vcdtor),
                      (S_TERRAIN, self.s_terrain), (S_DIST, self.s_dist),
                      (S_CARS, self.s_cars), (S_SOUND, self.s_sound),
                      (S_SIN, self.s_sin), (S_COS, self.s_cos),
                      (S_IDENTITY, self.s_identity),
                      (S_MULVEC, self.s_mulvec), (S_ORTHO, self.s_ortho)):
            e.stub(a, fn)

    # ---- names and memory

    def name(self, p, n):
        self.names[p & M32] = n
        self.byname[n] = p & M32

    def emit(self, line):
        self.out.append(line)

    def sym(self, v):
        v &= M32
        if v == 0:
            return "0"
        if v == 0xcdcdcdcd:
            return "cd"
        return self.names.get(v, "?")

    def ref(self, n):
        if n == "0":
            return 0
        return self.byname[n]

    def words(self, a, n):
        return "".join(" %08x" % self.e.u32(a + 4 * i) for i in range(n))

    def block(self, size, fill=None):
        p = self.e.alloc(size, align=16)
        self.e.write(p, bytes([self.fill if fill is None else fill]) * size)
        return p

    def next_name(self, prefix):
        k = self.count.get(prefix, 0)
        self.count[prefix] = k + 1
        return "%s%d" % (prefix, k)

    def cstr(self, a):
        b = self.e.read(a, 64)
        return b.split(b"\0")[0].decode("latin-1")

    def s8(self, a):
        v = self.e.u8(a)
        return v - 256 if v & 0x80 else v

    def s16(self, a):
        v = self.e.u16(a)
        return v - 65536 if v & 0x8000 else v

    def put8(self, a, v):
        self.e.mem[a] = v & 0xff

    def put16(self, a, v):
        struct.pack_into("<H", self.e.mem, a, v & 0xffff)

    def fset(self, a, vals):
        for i, v in enumerate(vals):
            self.e.put32(a + 4 * i, int(v, 16))

    # ---- the list of bodies

    def cbl_insert(self, b):
        e = self.e
        head = e.u32(G_CBL)
        e.put32(G_CBL, b)
        e.put32(head + 4, b)
        e.put32(b, head)
        e.put32(b + 4, G_CBL)

    def cbl_remove(self, b):
        e = self.e
        nx, pv = e.u32(b), e.u32(b + 4)
        e.put32(pv, nx)
        e.put32(nx + 4, pv)

    def body_common(self, b, bid, typ, dyn, vt):
        self.put8(b + 12, typ)
        self.put8(b + 13, dyn)
        self.put16(b + 14, bid)
        self.put8(b + 16, 0)
        self.put8(b + 17, 7)
        self.put8(b + 18, 0)
        self.put8(b + 19, 7)
        self.e.put32(b + 80, vt)
        self.cbl_insert(b)

    # ---- stubs

    def s_tcinit(self, em):
        self.emit("  tcinit %s" % self.sym(em.reg[4]))
        return em.reg[4] & M32

    def s_tcdtor(self, em):
        self.emit("  tcdtor %s" % self.sym(em.reg[4]))

    def s_elev(self, em):
        e = self.e
        tc, pt, terr, nrm, found = (em.reg[r] & M32 for r in (4, 5, 6, 7, 8))
        fd, el, n = self.elevq.pop(0) if self.elevq else (
            1, 0x3f000000, (0, 0, 0x3f800000))
        if nrm:
            for i in range(3):
                e.put32(nrm + 4 * i, n[i])
        if found:
            e.put32(found, fd)
        self.emit("  elev %s%s terr %s -> %d %08x %08x %08x %08x" % (
            self.sym(tc), self.words(pt, 3), self.sym(terr), fd, el,
            n[0], n[1], n[2]))
        em.fpr[0] = el

    def s_interest(self, em):
        tc, pos, vel = (em.reg[r] & M32 for r in (4, 5, 6))
        self.emit("  interest %s %s%s %08x %s%s" % (
            self.sym(tc), self.sym(pos), self.words(pos, 3),
            em.fpr[12] & M32, self.sym(vel), self.words(vel, 3)))

    def s_uninterest(self, em):
        self.emit("  uninterest %s" % self.sym(em.reg[4]))

    def s_full(self, em):
        n = self.sym(em.reg[4])
        v = self.full.get(n, 0)
        self.emit("  full %s -> %d" % (n, v))
        return v

    def s_freeslots(self, em):
        self.emit("  freeslots %s -> %d" % (self.sym(em.reg[4]),
                                            self.freeslots))
        return self.freeslots

    def s_omalloc(self, em):
        pool = em.reg[4] & M32
        if pool == self.vp:
            p = self.block(VIRGIN_SIZE)
            self.name(p, self.next_name("V"))
        elif pool == self.sp:
            p = self.block(SMOKE_SIZE)
            n = self.next_name("S")
            self.name(p, n)
            for off, sfx in ((256, "sys"), (304, "tc"), (1008, "wo"),
                             (1040, "m"), (1104, "al"), (1112, "dl")):
                self.name(p + off, "%s.%s" % (n, sfx))
        elif pool == self.rp:
            p = self.block(RB_SIZE)
            n = self.next_name("R")
            self.name(p, n)
            for off, sfx in ((16, "X"), (32, "R"), (144, "v"), (160, "w"),
                             (288, "ibi")):
                self.name(p + off, "%s.%s" % (n, sfx))
        else:
            p = self.block(64)
            self.name(p, self.next_name("B"))
        self.emit("  omalloc %s -> %s" % (self.sym(pool), self.sym(p)))
        return p

    def s_free(self, em):
        self.emit("  free %s %s" % (self.sym(em.reg[4]),
                                    self.sym(em.reg[5])))

    def s_newpool(self, em):
        n = self.cstr(em.reg[6] & M32)
        self.emit("  newpool %d %d %s %d" % (s32(em.reg[4]), s32(em.reg[5]),
                                            n, s32(em.reg[7])))
        return {"VirginSmokeableSlotPool": self.vp,
                "SmokeableSlotPool": self.sp}.get(n, self.xp)

    def s_delpool(self, em):
        self.emit("  delpool %s" % self.sym(em.reg[4]))

    def s_bmalloc(self, em):
        p = self.block(RECT_SIZE)
        self.name(p, self.next_name("M"))
        self.emit("  bmalloc %d %d -> %s" % (s32(em.reg[4]), s32(em.reg[5]),
                                            self.sym(p)))
        return p

    def s_nextid(self, em):
        if self.idq:
            v = self.idq.pop(0)
        else:
            v = self.nextid
            self.nextid += 1
        self.emit("  nextid -> %d" % v)
        return v

    def s_debugname(self, em):
        self.emit("  name %s %s" % (self.sym(em.reg[4]),
                                    self.cstr(em.reg[5] & M32)))

    def s_findbody(self, em):
        e = self.e
        bid = s32(em.reg[4])
        b, r = e.u32(G_CBL), 0
        while b != G_CBL:
            if self.s16(b + 14) == bid:
                r = b
                break
            b = e.u32(b)
        self.emit("  find %d -> %s" % (bid, self.sym(r)))
        return r

    def s_getcol(self, em):
        b, i = em.reg[4] & M32, s32(em.reg[5])
        k = self.cols.get((self.sym(b), i), 0)
        self.emit("  getcol %s %d -> %s" % (self.sym(b), i, self.sym(k)))
        return k

    def s_bbox(self, em):
        self.emit("  bbox %s%s%s" % (self.sym(em.reg[4]),
                                     self.words(em.reg[5] & M32, 2),
                                     self.words(em.reg[6] & M32, 2)))

    def s_caffeine(self, em):
        m, p = em.reg[5] & M32, em.reg[6] & M32
        self.emit("  caffeine %s%s %s%s" % (self.sym(em.reg[4]),
                                            self.words(m, 16), self.sym(p),
                                            self.words(p, 3)))

    def s_sinit(self, em):
        b = em.reg[4] & M32
        self.emit("  sinit %s %d %d" % (self.sym(b), s32(em.reg[5]),
                                        s32(em.reg[6])))
        self.body_common(b, s32(em.reg[5]), s32(em.reg[6]), 0, STATIC_VTABLE)
        return b

    def s_sdtor(self, em):
        b = em.reg[4] & M32
        self.emit("  sdtor %s %d" % (self.sym(b), s32(em.reg[5])))
        self.cbl_remove(b)

    def s_dinit(self, em):
        e = self.e
        b = em.reg[4] & M32
        self.emit("  dinit %s %d %d %s" % (self.sym(b), s32(em.reg[5]),
                                           s32(em.reg[6]),
                                           self.sym(em.reg[7])))
        self.body_common(b, s32(em.reg[5]), s32(em.reg[6]), 1,
                         DYNAMIC_VTABLE)
        e.put32(b + 84, 0)
        e.put32(b + 88, em.reg[7] & M32)
        e.put32(b + 92, 0)
        e.put32(b + 96, 0)
        return b

    def s_ddtor(self, em):
        b = em.reg[4] & M32
        self.emit("  ddtor %s %d" % (self.sym(b), s32(em.reg[5])))
        self.cbl_remove(b)

    def s_buildbv(self, em):
        e = self.e
        b = em.reg[4] & M32
        v = self.bvq.pop(0) if self.bvq else [
            fbits(x) for x in (0.5, 1.5, 0.75, 1.25, -0.5, -0.5, -0.25, 0.0,
                               0.5, 0.5, 1.75, 0.0)]
        for i in range(4):
            e.put32(b + 208 + 4 * i, v[i])
        for i in range(8):
            e.put32(b + 224 + 4 * i, v[4 + i])
        self.emit("  buildbv %s" % self.sym(b))

    def s_updpos(self, em):
        self.emit("  updatepos %s" % self.sym(em.reg[4]))

    def s_beginmove(self, em):
        self.emit("  beginmove %s %08x" % (self.sym(em.reg[4]),
                                           em.fpr[12] & M32))

    def s_psinit(self, em):
        e = self.e
        s = em.reg[4] & M32
        self.emit("  psinit %s" % self.sym(s))
        e.put32(s, 0x11111111)
        e.put32(s + 4, 0x22222222)
        e.put32(s + 8, 0)
        e.put32(s + 12, PHYSICSSYSTEM_VTABLE)
        return s

    def s_psfini(self, em):
        self.emit("  psfini %s %d" % (self.sym(em.reg[4]), s32(em.reg[5])))

    def s_addcomp(self, em):
        self.emit("  addcomp %s %s" % (self.sym(em.reg[4]),
                                       self.sym(em.reg[5])))

    def s_euler(self, em):
        self.emit("  euler %s %08x" % (self.sym(em.reg[4]), em.fpr[12] & M32))

    def s_aux(self, em):
        e = self.e
        sysp = em.reg[4] & M32
        self.emit("  aux %s" % self.sym(sysp))
        if self.auxq:
            v = self.auxq.pop(0)
            rb = e.u32(sysp - 256 + 96)
            for i in range(4):
                e.put32(rb + 144 + 4 * i, v[i])
                e.put32(rb + 160 + 4 * i, v[4 + i])

    def s_rbinit(self, em):
        e = self.e
        rb, rbi = em.reg[4] & M32, em.reg[5] & M32
        self.emit("  rbinit %s %s" % (self.sym(rb), self.sym(rbi)))
        e.write(rb + 16, bytes(RB_SIZE - 16))
        e.put32(rb + 12, rbi)
        mass = e.u32(rbi)
        e.put32(rb + 280, mass)
        e.put32(rb + 284, fbits(bitsf(mass) * 0.5))
        for i in range(16):
            e.put32(rb + 288 + 4 * i, fbits(0.25 * i - 1.0))
        e.put32(rb + 272, 0x77)
        return rb

    def s_rbcal(self, em):
        self.emit("  rbcal %s %s" % (self.sym(em.reg[4]), self.sym(em.reg[5])))

    def s_rbinertia(self, em):
        self.emit("  rbinertia %s" % self.sym(em.reg[4]))

    def s_rbstate(self, em):
        e = self.e
        rb, x, r, p, l = (em.reg[i] & M32 for i in (4, 5, 6, 7, 8))
        self.emit("  rbstate %s%s%s%s%s" % (self.sym(rb), self.words(x, 4),
                                            self.words(r, 16),
                                            self.words(p, 4),
                                            self.words(l, 3)))
        for i in range(4):
            e.put32(rb + 16 + 4 * i, e.u32(x + 4 * i))
            e.put32(rb + 96 + 4 * i, e.u32(p + 4 * i))
        for i in range(16):
            e.put32(rb + 32 + 4 * i, e.u32(r + 4 * i))
        for i in range(3):
            e.put32(rb + 112 + 4 * i, e.u32(l + 4 * i))

    def s_rbforce(self, em):
        self.emit("  rbforce %s%s%s" % (self.sym(em.reg[4]),
                                        self.words(em.reg[5] & M32, 4),
                                        self.words(em.reg[6] & M32, 3)))

    def s_rbimpulse(self, em):
        self.emit("  rbimpulse %s%s%s" % (self.sym(em.reg[4]),
                                          self.words(em.reg[5] & M32, 4),
                                          self.words(em.reg[6] & M32, 4)))

    def s_acopy(self, em):
        src = em.reg[4] & M32
        if self.sym(src) in self.cnull:
            c = 0
        else:
            c = self.block(EMITTER_SIZE)
            self.name(c, self.next_name("C"))
        self.emit("  acopy %s -> %s" % (self.sym(src), self.sym(c)))
        return c

    def s_agets(self, em):
        e = self.e
        lst, h = em.reg[4] & M32, em.reg[5] & M32
        n = h & 3
        for k in range(n):
            p = self.block(EMITTER_SIZE)
            self.name(p, self.next_name("E"))
            e.put32(p + 8, (h + k) & M32)
            tail = e.u32(lst + 4)
            e.put32(tail, p)
            e.put32(lst + 4, p)
            e.put32(p + 4, tail)
            e.put32(p, lst)
        self.emit("  agets %s %08x -> %d" % (self.sym(lst), h, n))

    def s_adelall(self, em):
        lst = em.reg[4] & M32
        self.emit("  adelall %s" % self.sym(lst))
        self.e.put32(lst, lst)
        self.e.put32(lst + 4, lst)

    def s_addauto(self, em):
        self.emit("  addauto %s %s" % (self.sym(em.reg[4]),
                                       self.sym(em.reg[5])))

    def s_remauto(self, em):
        self.emit("  remauto %s %s" % (self.sym(em.reg[4]),
                                       self.sym(em.reg[5])))

    def s_emdel(self, em):
        self.emit("  emdel %s %d" % (self.sym(em.reg[4]), s32(em.reg[5])))

    def s_pmalloc(self, em):
        p = self.block(16)
        self.name(p, self.next_name("N"))
        self.emit("  pmalloc -> %s" % self.sym(p))
        return p

    def s_pfree(self, em):
        self.emit("  pfree %s" % self.sym(em.reg[4]))

    def s_woctor(self, em):
        o, h = em.reg[4] & M32, em.reg[5] & M32
        self.wohash[o] = h
        self.emit("  woctor %s %08x %s %d" % (self.sym(o), h,
                                              self.sym(em.reg[6]),
                                              s32(em.reg[7])))
        return o

    def s_wodtor(self, em):
        self.emit("  wodtor %s %d" % (self.sym(em.reg[4]), s32(em.reg[5])))

    def s_wohash(self, em):
        o = em.reg[4] & M32
        h = self.wohash.get(o, 0)
        self.emit("  wohash %s -> %08x" % (self.sym(o), h))
        return s32(h)                   # v0 as the EE has it, sign-extended

    def s_art(self, em):
        h = em.reg[4] & M32
        v = 0 if h in self.noart else 1
        self.emit("  art %08x -> %d" % (h, v))
        return v

    def s_pipe(self, em):
        h = em.reg[4] & M32
        r = self.pp if h in self.pipes else 0
        self.emit("  pipe %08x %s -> %s" % (h, self.sym(em.reg[5]),
                                            self.sym(r)))
        return r

    def s_rect(self, em):
        r = em.reg[4] & M32
        self.emit("  rect %s%s" % (self.sym(r), "".join(
            " %08x" % (em.fpr[12 + i] & M32) for i in range(6))))
        return r

    def s_vcdtor(self, em):
        self.emit("  vcdtor %s %d" % (self.sym(em.reg[4]), s32(em.reg[5])))

    def s_terrain(self, em):
        h = em.reg[4] & M32
        v = (h >> 4) % 9 - 1
        self.emit("  terrain %08x -> %d" % (h, v))
        return v

    def s_dist(self, em):
        p = em.reg[5] & M32
        v = self.dist.get(self.sym(p), 0x42c80000)
        self.emit("  dist %s %s -> %08x" % (self.sym(em.reg[4]), self.sym(p),
                                            v))
        em.fpr[0] = v

    def s_cars(self, em):
        e = self.e
        c, p1, p2 = (em.reg[r] & M32 for r in (4, 5, 6))
        a, b = self.colcars.get(c, (0, 0))
        e.put32(p1, a)
        e.put32(p2, b)
        self.emit("  cars %s -> %s %s" % (self.sym(c), self.sym(a),
                                          self.sym(b)))

    def s_sound(self, em):
        p = em.reg[4] & M32
        self.emit("  sound%s %s" % (self.words(p, 3), self.sym(em.reg[5])))

    def s_sin(self, em):
        a = em.reg[4] & 0xffff
        self.emit("  sin %d" % a)
        em.fpr[0] = fbits(a / 65536.0)

    def s_cos(self, em):
        a = em.reg[4] & 0xffff
        self.emit("  cos %d" % a)
        em.fpr[0] = fbits((65536 - a) / 65536.0)

    def s_identity(self, em):
        m = em.reg[4] & M32
        self.emit("  identity %s" % self.sym(m))
        for i in range(16):
            self.e.put32(m + 4 * i, 0x3f800000 if i % 5 == 0 else 0)

    def s_mulvec(self, em):
        e = self.e
        o, m, v = (em.reg[r] & M32 for r in (4, 5, 6))
        r = self.mvq.pop(0) if self.mvq else [e.u32(v), e.u32(v + 4),
                                              e.u32(v + 8), 0x3f800000]
        self.emit("  mulvec %s%s %s%s -> %08x %08x %08x %08x" % (
            self.sym(m), self.words(m, 16), self.sym(v), self.words(v, 3),
            r[0], r[1], r[2], r[3]))
        for i in range(4):
            e.put32(o + 4 * i, r[i])

    def s_ortho(self, em):
        e = self.e
        o, m = em.reg[4] & M32, em.reg[5] & M32
        self.emit("  ortho %s%s" % (self.sym(m), self.words(m, 12)))
        r = self.orthq.pop(0) if self.orthq else (
            [e.u32(m + 4 * i) for i in range(12)] + [0, 0, 0, 0x3f800000])
        for i in range(16):
            e.put32(o + 4 * i, r[i])

    def s_creator(self, em):
        s = self.creatorret
        self.emit("  creator %d %s %08x -> %s" % (
            s32(em.reg[4]), self.sym(em.reg[5]), em.reg[6] & M32,
            self.sym(s)))
        return s

    # A table's OnLifetimeEnd, logged (vtlife).
    def s_lifeend(self, em):
        self.emit("  lifeend %s" % self.sym(em.reg[4]))
        return 0

    # ---- dumps

    def body_fields(self, b):
        e = self.e
        return ("next %s prev %s poly %s type %d dyn %d id %d wit %d dis %d "
                "ncol %d acd %d bb%s vt %08x" % (
                    self.sym(e.u32(b)), self.sym(e.u32(b + 4)),
                    self.sym(e.u32(b + 8)), self.s8(b + 12),
                    self.s8(b + 13), self.s16(b + 14), self.s8(b + 16),
                    self.s8(b + 17), self.s8(b + 18), self.s8(b + 19),
                    self.words(b + 20, 4), e.u32(b + 80)))

    def plist(self, lst):
        e = self.e
        s, n, i = "", e.u32(lst), 0
        while n != lst and i < 64:
            s += " %s:%s<%s" % (self.sym(n), self.sym(e.u32(n + 8)),
                                self.sym(e.u32(n + 4)))
            n, i = e.u32(n), i + 1
        return s + " | %s<%s" % (self.sym(e.u32(lst)),
                                 self.sym(e.u32(lst + 4)))

    def tlist(self, lst):
        e = self.e
        s, n, i = "", e.u32(lst), 0
        while n != lst and i < 64:
            s += " %s<%s" % (self.sym(n), self.sym(e.u32(n + 4)))
            n, i = e.u32(n), i + 1
        return s + " | %s<%s" % (self.sym(e.u32(lst)),
                                 self.sym(e.u32(lst + 4)))

    def dump_smokeable(self, s):
        e = self.e
        self.emit(
            "smk %s %s mode %d tc %s sys %s body %s bt %08x brot%s bpos%s "
            "bvel%s cyl%s lbb%s ps %08x %08x %d %08x si %s as %08x bs %08x "
            "t %08x %08x %08x sp %s gr %08x en %08x wm%s al%s dl%s aa %d "
            "da %d awake %d blink %d" % (
                self.sym(s), self.body_fields(s), s32(e.u32(s + 84)),
                self.sym(e.u32(s + 88)), self.sym(e.u32(s + 92)),
                self.sym(e.u32(s + 96)), e.u32(s + 100),
                self.words(s + 112, 16), self.words(s + 176, 4),
                self.words(s + 192, 3), self.words(s + 208, 4),
                self.words(s + 224, 8), e.u32(s + 256), e.u32(s + 260),
                s32(e.u32(s + 264)), e.u32(s + 268),
                self.sym(e.u32(s + 272)), e.u32(s + 276), e.u32(s + 280),
                e.u32(s + 284), e.u32(s + 288), e.u32(s + 292),
                self.sym(e.u32(s + 296)), e.u32(s + 300), e.u32(s + 1020),
                self.words(s + 1040, 16), self.plist(s + 1104),
                self.plist(s + 1112), self.s8(s + 1120), self.s8(s + 1121),
                self.s8(s + 1122), self.s8(s + 1123)))

    def dump_virgin(self, v):
        e = self.e
        self.emit("vir %s %s sp %s si %s inst %s info %s" % (
            self.sym(v), self.body_fields(v), self.sym(e.u32(v + 84)),
            self.sym(e.u32(v + 88)), self.sym(e.u32(v + 92)),
            self.sym(e.u32(v + 96))))

    def dump_rb(self, rb, w):
        e = self.e
        s = ("rb %s rbi %s X%s R%s P%s L%s v%s w%s md %d mass %08x minv %08x "
             "ibi%s" % (self.sym(rb), self.sym(e.u32(rb + 12)),
                        self.words(rb + 16, 4), self.words(rb + 32, 16),
                        self.words(rb + 96, 3), self.words(rb + 112, 3),
                        self.words(rb + 144, 4), self.words(rb + 160, 4),
                        s32(e.u32(rb + 272)), e.u32(rb + 280),
                        e.u32(rb + 284), self.words(rb + 288, 16)))
        if w:
            s += " pw %08x lw %08x" % (e.u32(rb + 108), e.u32(rb + 124))
        self.emit(s)

    def dump_emitter(self, c):
        e = self.e
        self.emit("em %s state %d lw%s iv%s" % (
            self.sym(c), s32(e.u32(c + 16)), self.words(c + 48, 16),
            self.words(c + 112, 4)))

    def dump_cbl(self):
        e = self.e
        s, n, i = "cbl", e.u32(G_CBL), 0
        while n != G_CBL and i < 200:
            s += " %s<%s" % (self.sym(n), self.sym(e.u32(n + 4)))
            n, i = e.u32(n), i + 1
        s += " | %s<%s" % (self.sym(e.u32(G_CBL)), self.sym(e.u32(G_CBL + 4)))
        self.emit(s)

    def dump_stats(self):
        e = self.e
        self.emit("stats %d %d %d %d awake %d vp %s sp %s spawners %s %d" % (
            s32(e.u32(STATS + 28)), s32(e.u32(STATS + 32)),
            s32(e.u32(STATS + 64)), s32(e.u32(STATS + 68)),
            s32(e.u32(G_AWAKE)), self.sym(e.u32(G_VSP)),
            self.sym(e.u32(G_SSP)), self.sym(e.u32(G_SPAWNERS)),
            s32(e.u32(G_NSPAWNERS))))

    def dump_infos(self):
        e = self.e
        n, i = e.u32(G_SIL), 0
        while n != G_SIL and i < 64:
            self.emit("info %s<%s ch %s %s %s %s terr %d al%s dl%s" % (
                self.sym(n), self.sym(e.u32(n + 4)),
                self.sym(e.u32(n + 128)), self.sym(e.u32(n + 132)),
                self.sym(e.u32(n + 136)), self.sym(e.u32(n + 140)),
                s32(e.u32(n + 192)), self.tlist(n + 216),
                self.tlist(n + 208)))
            n, i = e.u32(n), i + 1
        self.emit("sil %s<%s" % (self.sym(e.u32(G_SIL)),
                                 self.sym(e.u32(G_SIL + 4))))

    def dump_section(self, s):
        e = self.e
        h, ninst, _ = self.sections[s]
        base = e.u32(h + 28)
        for i in range(ninst):
            p = base + INST_SIZE * i
            self.emit("inst %s excl %04x rot %s pos%s" % (
                self.sym(p), e.u16(p + 14),
                " ".join("%d" % self.s16(p + 28 + 2 * k) for k in range(9)),
                self.words(p + 16, 3)))

    def dump_vt(self):
        e = self.e
        if self.rnames is None:
            self.rnames = retail_names()
        for tag, vt, n in (("smk", VT_SMOKE, 28), ("sys", VT_SYS, 4),
                           ("vir", VT_VIRGIN, 26)):
            s = "vt %s" % tag
            for i in range(n):
                d, _ix, fn = struct.unpack_from("<hhI", e.mem, vt + 8 * i)
                nm = "-" if fn == 0 else port_name(self.rnames.get(fn))
                s += " %d:%d:%s" % (8 * i, d, nm)
            self.emit(s)

    def dump_creators(self):
        names = {0: "0", F_BASIC: "basic", self.stub_creator: "stub"}
        self.emit("creators %s" % " ".join(
            names.get(self.e.u32(CREATORS + 4 * k), "?") for k in range(4)))

    # ---- calls through the tables

    def vcall(self, obj, slot, *args, vptr=80, fargs=()):
        e = self.e
        vt = e.u32(obj + vptr)
        d = struct.unpack_from("<h", e.mem, vt + slot)[0]
        fn = e.u32(vt + slot + 4)
        for i, f in enumerate(fargs):
            e.fpr[12 + i] = f
        return e.call(fn, (obj + vptr - 80 + d) & M32 if vptr != 80
                      else (obj + d) & M32, *args)

    def vec(self, vals, n=4):
        p = self.e.alloc(64, align=16)
        self.e.write(p, bytes(64))
        for i in range(n):
            self.e.put32(p + 4 * i, int(vals[i], 16))
        return p

    # ---- the chunks

    def info_record(self, p, a):
        e = self.e
        # info|name|hash|ahash|dhash|nch|c0|c1|c2|c3|comx|comy|comz|pad|
        #      life|anchor|break|bounce|terrhash|friction|pad2|mass
        nm = a[0].encode("latin-1")[:23]
        e.write(p + 8, nm + b"\0")
        e.put32(p + 32, int(a[20], 16))
        e.put32(p + 112, int(a[1], 16))
        e.put32(p + 116, int(a[2], 16))
        e.put32(p + 120, int(a[3], 16))
        e.put32(p + 124, int(a[4], 0))
        for k in range(4):
            e.put32(p + 144 + 4 * k, int(a[5 + k], 16))
        for k in range(4):
            e.put32(p + 160 + 4 * k, int(a[9 + k], 16))
        for k, off in enumerate((176, 180, 184, 188)):
            e.put32(p + off, int(a[13 + k], 16))
        e.put32(p + 196, int(a[17], 16))
        e.put32(p + 200, int(a[18], 16))
        e.put32(p + 204, int(a[19], 16))

    def load_infos(self):
        e = self.e
        n = len(self.pending)
        c = self.block(16 + INFO_SIZE * n, fill=0)
        e.put32(c, 0x00034026)
        e.put32(c + 4, 8 + INFO_SIZE * n)
        for i, a in enumerate(self.pending):
            p = c + 16 + INFO_SIZE * i
            nm = "I%d" % self.ninfo
            self.ninfo += 1
            self.name(p, nm)
            for off, sfx in ((32, "rbi"), (160, "com"), (208, "dl"),
                             (216, "al")):
                self.name(p + off, "%s.%s" % (nm, sfx))
            self.info_record(p, a)
        self.pending = []
        self.infochunks.append(c)
        r = e.call(F_LOADER, c)
        self.emit("load %d -> %d" % (n, r))

    def load_spawners(self, recs):
        e = self.e
        c = self.block(8 + 8 * len(recs), fill=0)
        e.put32(c, 0x00034027)
        e.put32(c + 4, 8 * len(recs))
        for i, r in enumerate(recs):
            h, sec, inst = r.split(":")
            p = c + 8 + 8 * i
            self.name(p, "P%d" % self.nspawner)
            self.nspawner += 1
            e.put32(p, int(h, 16))
            self.put16(p + 4, int(sec, 0))
            self.put16(p + 6, int(inst, 0))
        self.spchunks.append(c)
        r = e.call(F_LOADER, c)
        self.emit("spawners %d -> %d" % (len(recs), r))

    # ---- ops

    def smokeable_field(self, s, f, v):
        e = self.e
        ints8 = {"wit": 16, "dis": 17, "ncol": 18, "acd": 19, "aa": 1120,
                 "da": 1121, "awake": 1122, "blink": 1123}
        words = {"as": 276, "bs": 280, "tcr": 284, "taw": 288, "tlc": 292,
                 "gr": 300, "en": 1020}
        if f in ints8:
            self.put8(s + ints8[f], int(v[0], 0))
        elif f in words:
            e.put32(s + words[f], int(v[0], 16))
        elif f == "sp":
            e.put32(s + 296, self.ref(v[0]))
        elif f == "si":
            e.put32(s + 272, self.ref(v[0]))
        else:
            raise ValueError("smokeable field %s" % f)

    def rb_field(self, rb, f, v):
        offs = {"X": (16, 4), "R": (32, 16), "P": (96, 4), "L": (112, 4),
                "v": (144, 4), "w": (160, 4), "mass": (280, 1),
                "minv": (284, 1)}
        off, n = offs[f]
        self.fset(rb + off, v[:n])

    def op(self, a):
        e = self.e
        o = a[0]
        if o == "info":
            self.pending.append(a[1:])
        elif o == "load":
            self.load_infos()
        elif o == "loadbad":
            c = self.block(16, fill=0)
            e.put32(c, int(a[1], 16))
            r = e.call(F_LOADER, c)
            r2 = e.call(F_UNLOADER, c)
            self.emit("loadbad %s -> %d %d" % (a[1], r, r2))
        elif o == "unload":
            r = e.call(F_UNLOADER, self.infochunks[int(a[1], 0)])
            self.emit("unload %s -> %d" % (a[1], r))
        elif o == "spawners":
            self.load_spawners(a[1:])
        elif o == "unsp":
            r = e.call(F_UNLOADER, self.spchunks[int(a[1], 0)])
            self.emit("unsp %s -> %d" % (a[1], r))
        elif o == "find":
            r = e.call(F_FIND, int(a[1], 16))
            self.emit("find %s -> %s" % (a[1], self.sym(r)))
        elif o == "spawner":
            r = e.call(F_SPAWNER, int(a[1], 0))
            self.emit("spawner %s -> %s" % (a[1], self.sym(r)))
        elif o == "spidx":
            r = e.call(F_SPIDX, self.ref(a[1]))
            self.emit("spidx %s -> %d" % (a[1], r))
        elif o == "sect":
            s, ninst, ninfo = (int(x, 0) for x in a[1:4])
            h = self.block(HEADER_SIZE, fill=0)
            self.name(h, "H%d" % s)
            inst = self.block(INST_SIZE * ninst, fill=0)
            info = self.block(SINFO_SIZE * ninfo, fill=0)
            for i in range(ninst):
                self.name(inst + INST_SIZE * i, "H%d.i%d" % (s, i))
                self.name(inst + INST_SIZE * i + 16, "H%d.i%d.p" % (s, i))
            for i in range(ninfo):
                self.name(info + SINFO_SIZE * i, "H%d.f%d" % (s, i))
            e.put32(h + 20, info)
            e.put32(h + 28, inst)
            e.put32(SECTIONS + 4 * s, h)
            self.sections[s] = (h, ninst, ninfo)
        elif o == "inst":
            # inst|s|i|bb0|bb1|bb2|bb3|bb4|bb5|info|excl|px|py|pz|r0..r8
            s, i = int(a[1], 0), int(a[2], 0)
            p = e.u32(self.sections[s][0] + 28) + INST_SIZE * i
            for k in range(6):
                self.put16(p + 2 * k, int(a[3 + k], 0))
            self.put16(p + 12, int(a[9], 0))
            self.put16(p + 14, int(a[10], 0))
            self.fset(p + 16, a[11:14])
            for k in range(9):
                self.put16(p + 28 + 2 * k, int(a[14 + k], 0))
        elif o == "sinfo":
            s, i = int(a[1], 0), int(a[2], 0)
            e.put32(e.u32(self.sections[s][0] + 20) + SINFO_SIZE * i,
                    int(a[3], 16))
        elif o == "unsect":
            e.put32(SECTIONS + 4 * int(a[1], 0), 0)
        elif o == "secdump":
            self.dump_section(int(a[1], 0))
        elif o == "other":
            b = self.block(BODY_SIZE)
            self.name(b, self.next_name("O"))
            self.body_common(b, int(a[2], 0), int(a[1], 0), 0, 0)
        elif o == "rp":
            e.put32(NPLAYERS, int(a[1], 0))
        elif o == "timer":
            e.put32(G_TIMER, int(a[1], 16))
        elif o == "loop":
            e.put32(G_LOOP, int(a[1], 0))
        elif o == "full":
            self.full[a[1]] = int(a[2], 0)
        elif o == "freeslots":
            self.freeslots = int(a[1], 0)
        elif o == "ids":
            self.idq += [int(x, 0) for x in a[1:]]
        elif o == "elev":
            self.elevq.append((int(a[1], 0), int(a[2], 16),
                               tuple(int(x, 16) for x in a[3:6])))
        elif o == "bv":
            self.bvq.append([int(x, 16) for x in a[1:13]])
        elif o == "aux":
            self.auxq.append([int(x, 16) for x in a[1:9]])
        elif o == "mv":
            self.mvq.append([int(x, 16) for x in a[1:5]])
        elif o == "orth":
            self.orthq.append([int(x, 16) for x in a[1:17]])
        elif o == "noart":
            self.noart.add(int(a[1], 16))
        elif o == "art":
            self.noart.discard(int(a[1], 16))
        elif o == "pipe":
            self.pipes.add(int(a[1], 16))
        elif o == "nopipe":
            self.pipes.discard(int(a[1], 16))
        elif o == "cnull":
            self.cnull.add(a[1])
        elif o == "dist":
            self.dist[a[1]] = int(a[2], 16)
        elif o == "col":
            # col|S0|i|timer|car|car
            k = self.block(COL_SIZE)
            self.name(k, self.next_name("K"))
            e.put32(k + 8, int(a[3], 16))
            self.cols[(a[1], int(a[2], 0))] = k
            self.colcars[k] = (self.ref(a[4]), self.ref(a[5]))
        elif o == "creatorret":
            self.creatorret = self.ref(a[1])
        elif o == "fill":
            self.fill = int(a[1], 16)
        elif o == "initsm":
            self.emit("initsm")
            e.call(F_INIT)
        elif o == "closesm":
            self.emit("closesm")
            e.call(F_CLOSE)
        elif o == "spawnall":
            self.emit("spawnall")
            e.call(F_SPAWNALL)
        elif o == "clear":
            self.emit("clear")
            e.call(F_CLEAR)
        elif o == "delall":
            self.emit("delall")
            e.call(F_DELALL)
        elif o == "farway":
            self.emit("farway")
            e.call(F_FARWAY)
        elif o == "register":
            fn = {"basic": F_BASIC, "stub": self.stub_creator, "0": 0}[a[2]]
            e.call(F_REGISTER, int(a[1], 0), fn)
        elif o == "creators":
            self.dump_creators()
        elif o == "create":
            self.emit("create %s %s %s %s" % tuple(a[1:5]))
            r = e.call(F_CREATE, int(a[1], 0), int(a[2], 0), self.ref(a[3]),
                       int(a[4], 16))
            self.emit("  -> %s" % self.sym(r))
        elif o == "spawn":
            # spawn|type|info|hash|x|y|z|ang
            p = self.vec(a[4:7] + ["0"], 4)
            self.emit("spawn %s %s %s %s" % (a[1], a[2], a[3], a[7]))
            r = e.call(F_SPAWN, int(a[1], 0), self.ref(a[2]), int(a[3], 16),
                       p, int(a[7], 0))
            self.emit("  -> %d" % r)
        elif o == "spawnm":
            m = self.vec(a[4:20], 16)
            self.emit("spawnm %s %s %s" % (a[1], a[2], a[3]))
            r = e.call(F_SPAWNM, int(a[1], 0), self.ref(a[2]),
                       int(a[3], 16), m)
            self.emit("  -> %d" % r)
        elif o == "delete":
            self.emit("delete %s %s" % (a[1], a[2]))
            e.call(F_DELETE, int(a[1], 0), self.ref(a[2]))
        elif o == "convert":
            self.emit("convert %s" % a[1])
            r = e.call(F_CONVERT, self.ref(a[1]))
            self.emit("  -> %s" % self.sym(r))
        elif o == "vconvert":
            self.emit("vconvert %s" % a[1])
            r = e.call(F_VCONVERT, self.ref(a[1]))
            self.emit("  -> %s" % self.sym(r))
        elif o == "del":
            self.emit("del %s %s" % (a[1], a[2]))
            self.vcall(self.ref(a[1]), 8, int(a[2], 0))
        elif o == "sysdel":
            self.emit("sysdel %s %s" % (a[1], a[2]))
            s = self.ref(a[1])
            vt = e.u32(s + 268)
            d = struct.unpack_from("<h", e.mem, vt + 8)[0]
            e.call(e.u32(vt + 12), (s + 256 + d) & M32, int(a[2], 0))
        elif o == "sys":
            self.emit("sys %s" % a[1])
            s = self.ref(a[1])
            vt = e.u32(s + 268)
            d = struct.unpack_from("<h", e.mem, vt + 16)[0]
            e.call(e.u32(vt + 20), (s + 256 + d) & M32)
        elif o == "move":
            self.emit("move %s %s" % (a[1], a[2]))
            self.vcall(self.ref(a[1]), 64, fargs=(int(a[2], 16),))
        elif o == "impulse":
            j, at = self.vec(a[2:6]), self.vec(a[6:10])
            self.emit("impulse %s" % a[1])
            self.vcall(self.ref(a[1]), 120, j, at)
            self.emit("  -> %08x" % (e.fpr[0] & M32))
        elif o == "apply":
            j, at = self.vec(a[2:6]), self.vec(a[6:10])
            self.emit("apply %s" % a[1])
            self.vcall(self.ref(a[1]), 128, j, at)
        elif o in ("sleepchk", "sleep", "awaken", "activate", "posch",
                   "calib", "timers"):
            fn = {"sleepchk": F_SLEEPCHK, "sleep": F_SLEEP,
                  "awaken": F_AWAKEN, "activate": F_ACTIVATE,
                  "posch": F_POSCH, "calib": F_CALIB,
                  "timers": F_TIMERS}[o]
            self.emit("%s %s" % (o, a[1]))
            e.call(fn, self.ref(a[1]))
        elif o in ("childart", "touching"):
            fn = {"childart": F_CHILDART, "touching": F_TOUCHING}[o]
            self.emit("%s %s" % (o, a[1]))
            r = e.call(fn, self.ref(a[1]))
            self.emit("  -> %d" % r)
        elif o == "brk":
            pieces = e.alloc(32, align=16)
            e.write(pieces, bytes(32))
            self.emit("brk %s" % a[1])
            r = e.call(F_BREAK, self.ref(a[1]), pieces)
            self.emit("  -> %d%s" % (r, "".join(
                " %s" % self.sym(e.u32(pieces + 4 * k)) for k in range(4))))
        elif o == "svc":
            m = self.vec(a[2:18], 16)
            self.emit("svc %s" % a[1])
            e.call(F_SVC, self.ref(a[1]), m)
        elif o == "setinit":
            # setinit|S|16 words|none or 4 words
            m = self.vec(a[2:18], 16)
            v = 0 if a[18] == "none" else self.vec(a[18:22])
            self.emit("setinit %s" % a[1])
            e.call(F_SETINIT, self.ref(a[1]), m, v)
        elif o == "setgr":
            e.fpr[12] = int(a[2], 16)
            e.call(F_SETGR, self.ref(a[1]))
        elif o == "vtlife":
            # The smokeable's table copied, OnLifetimeEnd logging.
            s = self.ref(a[1])
            vt = self.block(8 * 28, fill=0)
            e.write(vt, bytes(e.mem[VT_SMOKE:VT_SMOKE + 8 * 28]))
            e.put32(vt + 216 + 4, self.stub_lifeend)
            e.put32(s + 80, vt)
        elif o == "blink":
            e.call(F_SETBLINK, self.ref(a[1]), int(a[2], 0))
        elif o == "acc":
            s = self.ref(a[1])
            r = []
            for slot in (24, 32, 40, 160):
                r.append(self.sym(self.vcall(s, slot)))
            for slot in (136, 144, 168, 184, 208):
                r.append("%d" % self.vcall(s, slot))
            for slot in (152, 192, 200):
                self.vcall(s, slot)
                r.append("%08x" % (e.fpr[0] & M32))
            e.call(F_GETGR, s)
            r.append("%08x" % (e.fpr[0] & M32))
            r.append(self.sym(e.call(F_GETTC, s)))
            e.call(F_ALIVE, s)
            r.append("%08x" % (e.fpr[0] & M32))
            self.emit("acc %s %s" % (a[1], " ".join(r)))
            self.vcall(s, 216)
        elif o == "vacc":
            v = self.ref(a[1])
            self.emit("vacc %s %s %d" % (a[1], self.sym(self.vcall(v, 24)),
                                         self.vcall(v, 144)))
        elif o == "sf":
            self.smokeable_field(self.ref(a[1]), a[2], a[3:])
        elif o == "rf":
            self.rb_field(self.ref(a[1]), a[2], a[3:])
        elif o == "sd":
            self.dump_smokeable(self.ref(a[1]))
        elif o == "vd":
            self.dump_virgin(self.ref(a[1]))
        elif o == "rd":
            self.dump_rb(self.ref(a[1]), False)
        elif o == "rdw":
            self.dump_rb(self.ref(a[1]), True)
        elif o == "ed":
            self.dump_emitter(self.ref(a[1]))
        elif o == "cbl":
            self.dump_cbl()
        elif o == "stats":
            self.dump_stats()
        elif o == "infos":
            self.dump_infos()
        elif o == "vt":
            self.dump_vt()
        else:
            raise ValueError("unknown op %s" % o)

    def run(self, lines):
        for line in lines:
            self.op(line.split("|"))
        return self.out


def model(lines):
    return Model().run(lines)


# ================================================================== script

def info(name, h, ah=0, dh=0, ch=(), com=(0.0, 0.0, 0.0), pad=0.0,
         life=0.0, anchor=0.0, brk=0.0, bounce=0.5, th=0x1234, fr=0.75,
         pad2=0, mass=10.0):
    c = list(ch) + [0] * (4 - len(ch))
    return ["info|%s|%08x|%08x|%08x|%d|%s|%s|%s|%s|%s|%s|%s|%s|%s|%08x|%s|"
            "%08x|%s" % (name, h, ah, dh, len(ch),
                         "|".join("%08x" % x for x in c),
                         F(com[0]), F(com[1]), F(com[2]), F(pad), F(life),
                         F(anchor), F(brk), F(bounce), th, F(fr), pad2,
                         F(mass))]


def vec4(*v):
    return "|".join(F(t) for t in v)


def mat16(*v):
    return "|".join(F(t) for t in v)


def placed(x, y, z, a=1.0):
    return mat16(a, 0.0, 0.0, 0.0, 0.0, a, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0,
                 x, y, z, 1.0)


def hash_from(s, seed):
    h = seed
    for ch in s:
        h = (h * 33 + ord(ch)) & M32
    return h


def elev(found, e, n=(0.0, 0.0, 1.0)):
    return "elev|%d|%s|%s" % (found, F(e), vec4(*n))


def timer(t):
    return "timer|%08x" % t


# Hashes. H_DRAG is one of the two models dragged through the air.
H_SIGN, H_CONE, H_BARREL, H_FENCE = (0x5a1e0001, 0x5a1e0002, 0x5a1e0003,
                                     0x5a1e0006)
H_PIECE1, H_PIECE2, H_LOST = 0x5a1e0004, 0x5a1e0005, 0xdeadbeef
H_DRAG = 0x98c6023c


def data():
    s = ["infos", "stats", "vt"]
    s += info("Sign", H_SIGN, ah=0x00a00001, dh=0x00a00002,
              ch=(H_PIECE1, H_PIECE2), com=(0.25, -0.5, 1.5), pad=0.125,
              life=10.0, anchor=50.0, brk=200.0, th=0x7777, mass=25.0)
    s += info("Cone", H_CONE, ah=0, dh=0x00b00003, ch=(H_LOST,),
              com=(0.0, 0.0, 0.5), life=0.0, anchor=0.0, brk=15.0,
              th=0x1111, mass=2.0)
    s += info("Barrel", H_BARREL, ah=0x00c00002, dh=0,
              com=(0.0, 0.0, 0.75), life=5.0, anchor=20.0, brk=40.0,
              th=0x2222, pad2=0x100, mass=30.0)
    s += ["load", "infos"]
    s += info("Piece1", H_PIECE1, com=(0.1, 0.2, 0.3), th=0x3333, mass=3.0)
    s += info("Piece2_long_name_here", H_PIECE2, dh=0x00d00001,
              com=(-0.1, 0.0, 0.2), life=3.0, th=0x4444, mass=4.0)
    s += info("Fence", H_FENCE, ah=0x00e00003, dh=0x00e00001,
              com=(0.0, 0.5, 0.0), life=8.0, anchor=10.0, brk=0.0,
              th=0x5555, mass=50.0)
    s += ["load", "infos"]
    s += ["find|%08x" % h for h in (H_SIGN, H_PIECE2, H_LOST, 0)]
    s += ["loadbad|00034028", "loadbad|80034026"]
    # A chunk loaded and unloaded again: the list keeps the others. Its
    # Quad has four children; its Zero's hash is 0, which no empty child
    # slot looks for.
    s += info("Spare", 0x5a1e0099, th=0x9999)
    s += info("Zero", 0, th=0x9998)
    s += info("Quad", 0x5a1e0098, ch=(H_PIECE1, H_PIECE2, H_CONE, H_SIGN),
              th=0x9997)
    s += ["load", "infos", "unload|2", "infos", "find|5a1e0099"]
    return s


ROWS = [(16384, 0, 0, 0, 16384, 0, 0, 0, 16384),
        (11585, 11585, 0, -11585, 11585, 0, 0, 0, 16384),
        (16000, 300, -200, -310, 15990, 100, 210, -95, 16380),
        (-16384, 0, 0, 0, -16384, 0, 0, 0, 16384)]


def inst(s, i, bb, nfo, excl, pos, rot):
    return "inst|%d|%d|%s|%d|%d|%s|%s" % (
        s, i, "|".join("%d" % x for x in bb), nfo, excl, vec4(*pos),
        "|".join("%d" % r for r in rot))


def scenery():
    s = ["sect|3|4|3", "sect|7|3|2", "sect|9|1|1"]
    for i in range(4):
        s += [inst(3, i, (-2 - i, -3, 0, 2 + i, 3, 4 + i), i % 3,
                   0x10 | (0x400 if i == 2 else 0),
                   (10.0 * i + 0.25, -5.0, 0.5 * i), ROWS[i])]
    for i in range(3):
        s += [inst(7, i, (-1, -1, 0, 1, 1, 2), i % 2,
                   0x10 | (1 if i == 1 else 0), (-20.0 - i, 7.5, 1.0),
                   ROWS[(i + 1) % 4])]
    s += [inst(9, 0, (0, 0, 0, 0, 0, 0), 0, 0x10, (1.0, 2.0, 3.0), ROWS[0])]
    s += ["sinfo|3|0|aaaa0000", "sinfo|3|1|aaaa0001",
          "sinfo|3|2|%08x" % H_DRAG, "sinfo|7|0|bbbb0000",
          "sinfo|7|1|bbbb0001", "sinfo|9|0|cccc0000"]
    # The spawners: one in a section not loaded (5), one whose info is
    # unknown, one out of two-player races (7:1's flag); the tenth shares
    # 7:2 with the unknown one.
    s += ["spawners|%08x:3:0|%08x:3:1|%08x:7:0|%08x:5:0|%08x:3:2|%08x:7:2|"
          "%08x:3:3|%08x:9:0|%08x:7:1|%08x:7:2"
          % (H_SIGN, H_FENCE, H_CONE, H_SIGN, H_BARREL, H_LOST, H_SIGN,
             H_BARREL, H_SIGN, H_FENCE)]
    s += ["stats", "spawner|0", "spawner|3", "spawner|-1", "spidx|P0",
          "spidx|P5", "spidx|0"]
    # InitSmokeables: the rotations orthonormalised and written back, cut
    # toward zero.
    s += ["orth|" + mat16(0.99999, 0.0001, -0.0002, 0.0, -0.00012, 0.9999,
                          0.00007, 0.0, 0.0002, -0.0001, 0.99997, 0.0,
                          9.0, 9.0, 9.0, 1.0)]
    s += ["orth|" + mat16(0.7071068, -0.7071068, 0.0, 0.0, 0.7071068,
                          0.7071068, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0,
                          0.0, 0.0, 0.0, 1.0)]
    s += ["initsm", "secdump|3", "secdump|7", "secdump|9", "closesm"]
    return s


def spawning():
    s = ["rp|2", "full|VP|0", "spawnall", "cbl", "stats", "infos",
         "creators", "secdump|3", "secdump|7"]
    s += ["vd|V%d" % k for k in range(7)]
    s += ["vacc|V0", "vacc|V2"]
    return s


def converting():
    s = [timer(0x1000), "full|SP|0", "cnull|E9"]
    # V0, the Sign: the ground under it, no raise; both pieces' art.
    s += [elev(1, 0.25), "convert|V0", "sd|S0", "rd|R0", "cbl", "stats"]
    s += ["ed|C%d" % k for k in range(3)]
    # V1, the Fence: the ground over it, raised, on a slope; one of its
    # anchors' copies fails. Its id past sixteen bits.
    s += ["ids|40000", elev(1, 3.0, (0.0, 0.6, 0.8)), "convert|V1",
          "sd|S1", "rd|R1"]
    # V2, the Cone: no ground found; its child's art missing.
    s += ["noart|%08x" % hash_from("_CHILD1", 0xbbbb0000), elev(0, 9.0),
          "convert|V2", "sd|S2"]
    # V3, the Barrel: a pipeline's polyhedron; the ground far below.
    s += ["pipe|%08x" % H_BARREL, elev(1, -30.0), "convert|V3", "sd|S3",
          "cbl", "stats", "secdump|3"]
    # The pool full: no smokeable -- the virgin kept by Convert, destroyed
    # by ConvertToSmokeable.
    s += ["full|SP|1", "vconvert|V4", "convert|V5", "full|SP|0", "cbl",
          "stats"]
    return s


def behaviour():
    s = ["acc|S0", "acc|S2", "acc|S3"]
    # The Sign: an impulse under its anchor, then one that pulls it loose.
    s += ["impulse|S0|%s|%s" % (vec4(1.0, 2.0, 3.0, 0.0),
                                vec4(0.5, 0.0, 0.0, 0.0))]
    s += ["impulse|S0|%s|%s" % (vec4(60.0, 10.0, -5.0, 0.0),
                                vec4(0.5, 0.25, 0.0, 1.0)),
          "sd|S0", "rd|R0", "stats"]
    # Loose, an impulse past what is left of its strength breaks it.
    s += ["impulse|S0|%s|%s" % (vec4(150.0, 50.0, -20.0, 0.0),
                                vec4(0.0, 0.0, 0.0, 0.0)), "sd|S0"]
    # The Cone has no anchor; the Barrel's wears down.
    s += ["impulse|S2|%s|%s" % (vec4(1.0, 0.5, 0.25, 0.0),
                                vec4(0.0, 0.0, 0.0, 0.0)), "sd|S2"]
    s += ["impulse|S3|%s|%s" % (vec4(30.0, 30.0, 30.0, 0.0),
                                vec4(0.1, 0.2, 0.3, 0.0)), "sd|S3"]
    # An impulse applied to one asleep does nothing.
    s += ["apply|S1|%s|%s" % (vec4(1.0, 1.0, 1.0, 0.0),
                              vec4(0.0, 0.0, 0.0, 1.0)),
          "apply|S0|%s|%s" % (vec4(1.0, -1.0, 2.0, 0.5),
                              vec4(0.25, 0.0, 0.0, 1.0))]
    s += ["acc|S0", "acc|S3"]
    # Move: the Sign awake, touching a car, steps of 0.035 / 4.
    s += [timer(0x3000), "rf|R0|v|" + vec4(2.0, 1.0, 0.5, 0.0),
          "rf|R0|w|" + vec4(0.5, 0.25, 0.125, 0.0),
          "sf|S0|ncol|1", "col|S0|0|00000800|A0|0",
          "move|S0|%s" % F(0.035), "sd|S0", "rd|R0", "ed|C0", "ed|C1"]
    # Again, faster: the anchors' velocities were set once.
    s += ["rf|R0|v|" + vec4(4.0, 3.0, 2.0, 0.0), "move|S0|%s" % F(0.01),
          "ed|C0", "ed|C1"]
    # The Barrel dragged through the air, blinking on an even frame.
    s += ["rf|R3|v|" + vec4(3.0, -4.0, 12.0, 0.5),
          "orth|" + mat16(*[0.5 + 0.0625 * i for i in range(16)]),
          "blink|S3|1", "loop|2", "move|S3|%s" % F(0.025), "sd|S3",
          "rd|R3"]
    s += ["loop|3", "mv|" + vec4(0.5, 0.25, -0.125, 1.0),
          "move|S3|%s" % F(0.0001), "sd|S3", "blink|S3|0"]
    # The Fence a second and a half old, unwitnessed: kept.
    s += [timer(0x2800), "timers|S1", "cbl", timer(0x3000)]
    # The Fence asleep and anchored, witnessed: nothing but the matrices;
    # its dynamic emitter untouched.
    s += ["sf|S1|wit|1", "move|S1|%s" % F(0.02), "sd|S1", "ed|C5"]
    # ... and unwitnessed, two seconds old: back to a virgin.
    s += ["sf|S1|wit|0", "timers|S1", "cbl", "stats", "vd|V7"]
    # The Sign broken in two.
    s += ["childart|S0", "brk|S0", "sd|S4", "sd|S5", "rd|R4", "cbl",
          "stats"]
    # Piece2 lives three seconds once awake; Piece1 for ever.
    # Its lifetime counts from its waking, not its making; the table's
    # OnLifetimeEnd is called.
    s += ["sf|S5|tcr|00000100", "vtlife|S5"]
    s += [timer(0x5000), "timers|S5", "acc|S5", timer(0x6000), "timers|S5",
          "timers|S4", "cbl", "stats"]
    # To sleep: the Barrel slow and long settled; the Cone still spinning.
    # First a car a second and a half ago, then a collision 0.4 old.
    s += [timer(0x9000), "sf|S3|ncol|1", "col|S3|0|00001000|0|0",
          "rf|R3|v|" + vec4(1.2, 0.0, 0.0, 0.0),
          "rf|R3|w|" + vec4(3.5, 0.0, 0.0, 0.0)]
    s += ["sf|S3|tlc|00007890", "sleepchk|S3", "sd|S3", "sf|S3|tlc|00000000"]
    s += ["col|S3|0|000089c0|0|0", "sleepchk|S3", "sd|S3",
          "col|S3|0|00001000|0|0"]
    s += ["sleepchk|S3", "sd|S3", "stats"]
    s += ["sf|S2|ncol|1", "col|S2|0|00001000|0|0",
          "rf|R2|v|" + vec4(0.1, 0.1, 0.1, 0.0),
          "rf|R2|w|" + vec4(3.0, 3.0, 3.0, 0.0), "sleepchk|S2",
          "col|S2|0|00008f00|0|0", "rf|R2|w|" + vec4(0.0, 0.0, 0.0, 0.0),
          "sleepchk|S2", "sd|S2", "stats", "awaken|S2", "sd|S2"]
    return s


def system():
    s = []
    # The system table's ComputeAuxiliaries: slowing, settled, moving.
    pl = ["rf|R2|P|" + vec4(1.0, 2.0, 3.0, 4.0),
          "rf|R2|L|" + vec4(5.0, 6.0, 7.0, 8.0)]
    s += pl + ["aux|%s|%s" % (vec4(0.5, 0.0, 0.0, 0.0),
                              vec4(0.0, 0.0, 0.0, 0.0)),
               "sys|S2", "rdw|R2"]
    s += pl + ["sf|S2|tlc|00008c00",
               "aux|%s|%s" % (vec4(0.1, 0.1, 0.1, 0.0),
                              vec4(0.1, 0.0, 0.1, 0.0)),
               "sys|S2", "rd|R2"]
    s += pl + ["aux|%s|%s" % (vec4(1.0, 0.0, 0.0, 0.0),
                              vec4(0.0, 0.0, 0.0, 0.0)),
               "sys|S2", "rdw|R2"]
    s += pl + ["aux|%s|%s" % (vec4(0.0, 0.0, 0.0, 0.0),
                              vec4(0.0, 0.8, 0.0, 0.0)),
               "sys|S2", "rdw|R2"]
    s += pl + ["sf|S2|ncol|0", "aux|%s|%s" % (vec4(0.1, 0.0, 0.0, 0.0),
                                             vec4(0.0, 0.0, 0.0, 0.0)),
               "sys|S2", "rdw|R2", "sf|S2|ncol|1"]
    # Just over 0.7; turning just over a quarter.
    s += pl + ["aux|%s|%s" % (vec4(0.75, 0.0, 0.0, 0.0),
                              vec4(0.0, 0.0, 0.0, 0.0)),
               "sys|S2", "rdw|R2"]
    s += pl + ["sf|S2|tlc|00008c00",
               "aux|%s|%s" % (vec4(0.1, 0.0, 0.0, 0.0),
                              vec4(0.0, 0.28, 0.0, 0.0)),
               "sys|S2", "rdw|R2"]
    s += pl + ["sf|S2|tlc|00001000",
               "aux|%s|%s" % (vec4(0.1, 0.1, 0.1, 0.0),
                              vec4(0.0, 0.2, 0.0, 0.0)),
               "sys|S2", "rdw|R2"]
    # The rest of the Cone's methods.
    s += ["posch|S2", "svc|S2|" + placed(1.0, 2.0, 3.0), "activate|S2",
          "svc|S2|" + placed(4.0, 5.0, 6.0, 0.5), "sd|S2"]
    s += ["setinit|S2|%s|%s" % (placed(7.0, 8.0, 9.0),
                                vec4(1.0, 2.0, 3.0, 0.5)), "sd|S2", "rd|R2"]
    s += ["setgr|S2|%s" % F(0.75),
          "setinit|S2|%s|none" % placed(-1.0, -2.0, 4.0), "sd|S2"]
    # A position whose w is not 1: the rotation's is.
    s += ["setinit|S2|%s|none" % mat16(1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0,
                                       0.0, 0.0, 0.0, 1.0, 0.0, 2.0, 3.0,
                                       4.0, 2.0), "sd|S2"]
    s += ["calib|S2", "childart|S2", "touching|S2", "col|S2|0|00001000|0|A1",
          "touching|S2", "acc|S2"]
    # The car on the second collision only.
    s += ["sf|S2|ncol|2", "col|S2|0|00001000|0|0", "col|S2|1|00001000|A0|0",
          "touching|S2", "sf|S2|ncol|1"]
    # Woken after the clock: a negative age.
    s += [timer(0x0800), "acc|S2", timer(0x9000)]
    return s


def module():
    s = ["other|3|500"]
    # Deleting by id: a smokeable of another info, a negative id, a body
    # that is no smokeable, then one that is.
    s += ["delete|102|I0", "delete|-7|I0", "delete|-1|I0", "delete|500|I0",
          "delete|101|I1", "cbl", "stats"]
    # Spawning on the ground: an id past sixteen bits; no ground; the pool
    # full; by matrix.
    s += ["ids|40000", elev(1, 2.0, (0.0, 0.6, 0.8)),
          "spawn|0|I2|cafe0001|%s|%s|%s|8192" % (F(5.0), F(6.0), F(7.0)),
          "sd|S6", "rd|R6"]
    s += [elev(0, 2.0),
          "spawn|0|I2|cafe0001|%s|%s|%s|0" % (F(5.0), F(6.0), F(7.0))]
    s += ["full|SP|1", elev(1, 2.0),
          "spawn|0|I2|cafe0001|%s|%s|%s|0" % (F(5.0), F(6.0), F(7.0)),
          "spawnm|0|I3|cafe0002|" + placed(1.0, 1.0, 1.0), "full|SP|0"]
    s += [elev(1, -1.5, (0.6, 0.0, 0.8)),
          "spawn|0|I5|cafe0003|%s|%s|%s|49152" % (F(-5.0), F(0.0), F(1.0)),
          "sd|S7"]
    # The Fence's anchor met exactly: pulled loose.
    s += ["impulse|S7|%s|%s" % (vec4(6.0, 8.0, 0.0, 0.0),
                                vec4(0.0, -0.5, 0.0, 0.0)), "sd|S7"]
    s += ["spawnm|0|I3|cafe0002|" + placed(1.0, 1.0, 1.0), "sd|S8", "cbl",
          "stats"]
    # The creators' table.
    s += ["register|1|stub", "creatorret|S8", "creators",
          "create|1|77|I0|beef0001", "create|0|78|I3|beef0002",
          "register|1|0", "creators"]
    s += ["sysdel|S9|0", "del|S6|1", "del|V7|1", "cbl", "stats"]
    # Far away: too fast (S4), turned over (S10), long asleep and far
    # (S11); the pinned Barrel kept however fast. Kept: S8, fast and
    # tilted but under both, far but never woken; S12 old and far but
    # awake; S13 far but 42 seconds awake; S14 50 seconds but 110 away.
    s += ["spawnm|0|I3|cafe0004|" + placed(2.0, 2.0, 2.0),
          "spawnm|0|I3|cafe0005|" + placed(3.0, 3.0, 3.0),
          "spawnm|0|I3|cafe0006|" + placed(4.0, 4.0, 4.0),
          "spawnm|0|I3|cafe0008|" + placed(5.0, 4.0, 4.0),
          "spawnm|0|I3|cafe0009|" + placed(6.0, 4.0, 4.0),
          "rf|R4|v|" + vec4(1000.0, 100.0, 0.0, 0.0),
          "rf|R10|R|" + mat16(-60.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                              0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0),
          "rf|R3|v|" + vec4(2000.0, 0.0, 0.0, 0.0),
          "rf|R8|v|" + vec4(600.0, 0.0, 0.0, 0.0),
          "rf|R8|R|" + mat16(20.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                             0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0),
          "awaken|S11", "sleep|S11", "awaken|S12", "sf|S12|taw|00001000",
          "sf|S13|taw|0000cfc0", "sf|S14|taw|000052c0", timer(0x36000),
          "dist|R11.X|43480000", "dist|R3.X|43480000",
          "dist|R12.X|43480000", "dist|R13.X|43480000",
          "dist|R14.X|42dc0000", "dist|R8.X|43480000",
          "freeslots|10", "farway", "cbl", "stats"]
    s += ["freeslots|5", "farway", "cbl", "stats"]
    # Spawned, so no spawner to go back to however old and asleep.
    s += ["timers|S8", "cbl"]
    # The other model dragged through the air, raised, fast enough for the
    # interest box's cap.
    s += ["spawnm|0|I3|8ac70e76|" + placed(6.0, 6.0, 6.0), "awaken|S15",
          "sf|S15|gr|3f800000", "rf|R15|v|" + vec4(150.0, 0.0, 0.0, 0.0),
          "move|S15|%s" % F(0.015), "sd|S15"]
    # A Cone whose pieces' art is there: an impulse just its strength.
    s += ["spawnm|0|I1|cafe000b|" + placed(7.0, 6.0, 6.0),
          "impulse|S16|%s|%s" % (vec4(5.0, 5.0, 5.0, 0.0),
                                 vec4(0.0, 0.0, 0.0, 0.0)), "sd|S16"]
    # One made after DeleteSmokeableCollisionBodies goes with the clear.
    s += ["delall", "cbl", "stats",
          "spawnm|0|I3|cafe000a|" + placed(7.0, 7.0, 7.0), "cbl",
          "clear", "cbl", "stats", "infos", "farway",
          "clear", "unsp|0", "stats", "unload|0", "unload|1", "infos"]
    return s


def script():
    return (data() + scenery() + spawning() + converting() + behaviour()
            + system() + module())


# ================================================================== build

def build_harness(tmp, name="smokeable_test"):
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

S = SMOKE
I = SINFO
MUTATIONS = [
    # The helpers.
    ("seconds-scale", S, "           * 0.00025f;", "           * 0.00026f;"),
    ("seconds-unsigned", S,
     "    return (float)(int32_t)((uint32_t)WorldTimer - t->PackedTime)",
     "    return (float)((uint32_t)WorldTimer - t->PackedTime)"),
    ("length-z", S, "    return sqrtf((x * x + y * y) + z * z);",
     "    return sqrtf((x * x + y * y) + z);"),
    ("min-swap", S, "    return ft < fs ? ft : fs;", "    return ft < fs ? fs : ft;"),
    ("max-swap", S, "    return fs < ft ? ft : fs;", "    return fs < ft ? fs : ft;"),
    ("pinned-word", S, "    return w != 0;", "    return (w & 0xff) != 0;"),
    ("rot-scale", S, "    const float k = 1.0f / 16384.0f;",
     "    const float k = 1.0f / 16383.0f;"),
    ("rot-y", S, "(float)inst->Rotation[3 * i + 1] * k;",
     "(float)inst->Rotation[3 * i + 2] * k;"),
    ("rot-w", S, "        row[i]->w = 0.0f;\n", ""),
    # The module.
    ("create-type", S, "    return SmokeableCreators[type](id, info, name_hash);",
     "    return SmokeableCreators[0](id, info, name_hash);"),
    ("spawn-found", S, "    if (found == 0 || bIsSlotPoolFull(SmokeableSlotPool)) {",
     "    if (bIsSlotPoolFull(SmokeableSlotPool)) {"),
    ("spawn-full", S, "    if (found == 0 || bIsSlotPoolFull(SmokeableSlotPool)) {",
     "    if (found == 0) {"),
    ("spawn-id16", S, "    id = (int16_t)collisionbody_get_next_id();\n"
     "    s = smokeable_create(type, id, info, name_hash);\n"
     "    z = (-s",
     "    id = collisionbody_get_next_id();\n"
     "    s = smokeable_create(type, id, info, name_hash);\n"
     "    z = (-s"),
    ("spawn-com", S, "    z = (-s->Dynamic.LocalBBMin.z - s->SI->CenterOfMass[2]) * n.z;",
     "    z = (-s->Dynamic.LocalBBMin.z + s->SI->CenterOfMass[2]) * n.z;"),
    ("spawn-cos", S, "    a.x = bCosBam(ang);", "    a.x = bSinBam(ang);"),
    ("spawn-lift", S, "    z = z + 0.06f;", "    z = z + 0.05f;"),
    ("spawn-b-y", S, "    b.y = a.z * n.x - n.z * a.x;", "    b.y = n.z * a.x - a.z * n.x;"),
    ("spawn-c-x", S, "    c.x = b.y * n.z - n.y * b.z;", "    c.x = b.y * n.z;"),
    ("spawn-v0", S, "    m.v0.x = c.x;", "    m.v0.x = b.x;"),
    ("spawn-v2", S, "    m.v2.y = n.y;", "    m.v2.y = n.x;"),
    ("spawn-z", S, "    m.v3.z = z;", "    m.v3.z = pos->z;"),
    ("spawn-destroy", S, "    smokeable_set_initial_position(s, &m, NULL);\n"
     "    topology_destroy(&tc);\n    return id;",
     "    smokeable_set_initial_position(s, &m, NULL);\n    return id;"),
    ("spawnm-full", S, "    if (bIsSlotPoolFull(SmokeableSlotPool))\n        return -1;\n"
     "    id = (int16_t)collisionbody_get_next_id();\n"
     "    s = smokeable_create(type, id, info, name_hash);\n"
     "    smokeable_set_initial_position(s, m, NULL);",
     "    id = (int16_t)collisionbody_get_next_id();\n"
     "    s = smokeable_create(type, id, info, name_hash);\n"
     "    smokeable_set_initial_position(s, m, NULL);"),
    ("delete-neg", S, "    if ((int16_t)id < 0)\n        return;", "    if ((int16_t)id < -1)\n        return;"),
    ("delete-type", S, "    if (b == NULL || b->Type != 1", "    if (b == NULL || b->Type != 2"),
    ("delete-info", S, "        || ((Smokeable *)(void *)b)->SI != info)\n        return;",
     "        )\n        return;"),
    ("delete-flags", S, "    body_destroy(b, 3);\n}\n\n// The position",
     "    body_destroy(b, 1);\n}\n\n// The position"),
    ("init-null", S, "        if (h == NULL)\n            continue;\n"
     "        inst = &h->pSceneryInstance[sp->SceneryInstanceNumber];\n"
     "        instance_rotation(&m, inst);",
     "        if (h == NULL)\n            break;\n"
     "        inst = &h->pSceneryInstance[sp->SceneryInstanceNumber];\n"
     "        instance_rotation(&m, inst);"),
    ("init-ortho", S, "        eOrthonormalizeMatrix(&m, &m);\n        inst->Rotation[0]",
     "        inst->Rotation[0]"),
    ("init-scale", S, "        inst->Rotation[4] = (int16_t)ee_trunc_w(m.v1.y * 16384.0f);",
     "        inst->Rotation[4] = (int16_t)ee_trunc_w(m.v1.y * 16383.0f);"),
    ("init-row", S, "        inst->Rotation[6] = (int16_t)ee_trunc_w(m.v2.x * 16384.0f);",
     "        inst->Rotation[6] = (int16_t)ee_trunc_w(m.v1.x * 16384.0f);"),
    ("init-round", S, "        inst->Rotation[8] = (int16_t)ee_trunc_w(m.v2.z * 16384.0f);",
     "        inst->Rotation[8] = (int16_t)lrintf(m.v2.z * 16384.0f);"),
    ("move-unlink", S, "    prev->Link.next = next;\n    next->Link.prev = prev;\n    tail = list->Link.prev;",
     "    prev->Link.next = next;\n    tail = list->Link.prev;"),
    ("move-tail", S, "    tail->Link.next = b;\n    list->Link.prev = b;",
     "    list->Link.prev = b;"),
    ("move-end", S, "    b->Link.next = list;", "    b->Link.next = tail;"),
    ("destroy-head", S, "        b->Link.next = head;\n        b->Link.prev = BODY_END;",
     "        b->Link.next = head;\n        b->Link.prev = head;"),
    ("destroy-flags", S, "        b->Link.prev = BODY_END;\n        body_destroy(b, 3);",
     "        b->Link.prev = BODY_END;\n        body_destroy(b, 2);"),
    ("delall-virgin", S, "        if (b->Type == 2 || b->Type == 1)",
     "        if (b->Type == 1)"),
    ("delall-smoke", S, "        if (b->Type == 2 || b->Type == 1)",
     "        if (b->Type == 2)"),
    ("far-pool", S, "    if (SmokeableSlotPool == NULL)\n        return;\n    list.Link.next", "    list.Link.next"),
    ("far-type", S, "        next = b->Link.next;\n        if (b->Type != 1)\n            continue;\n"
     "        v = body_vector",
     "        next = b->Link.next;\n        if (b->Type == 0)\n            continue;\n"
     "        v = body_vector"),
    ("far-speed", S, "        if (1000.0f < length3(v->x, v->y, v->z)",
     "        if (100.0f < length3(v->x, v->y, v->z)"),
    ("far-pinned", S, "            && !info_pinned(((Smokeable *)(void *)b)->SI))\n",
     "            )\n"),
    ("far-rot", S, "        if (50.0f < fabsf(body_rotation(b)->v0.x))",
     "        if (50.0f < body_rotation(b)->v0.x)"),
    ("far-rot-lim", S, "        if (50.0f < fabsf(body_rotation(b)->v0.x))",
     "        if (5.0f < fabsf(body_rotation(b)->v0.x))"),
    ("far-free", S, "    if (bCountFreeSlots(SmokeableSlotPool) < 10) {",
     "    if (bCountFreeSlots(SmokeableSlotPool) < 11) {"),
    ("far-awake", S, "            if (s->Awake != 0)\n                continue;\n            t =",
     "            t ="),
    ("far-valid", S, "            t = timer_is_valid(&s->TimeAwoken) ? seconds_since(&s->TimeAwoken)\n"
     "                                               : 0.0f;",
     "            t = seconds_since(&s->TimeAwoken);"),
    ("far-age", S, "            if (45.0f < t && 120.0f < d && !info_pinned(s->SI))",
     "            if (40.0f < t && 120.0f < d && !info_pinned(s->SI))"),
    ("far-dist", S, "            if (45.0f < t && 120.0f < d && !info_pinned(s->SI))",
     "            if (45.0f < t && 100.0f < d && !info_pinned(s->SI))"),
    ("far-pinned2", S, "            if (45.0f < t && 120.0f < d && !info_pinned(s->SI))",
     "            if (45.0f < t && 120.0f < d)"),
    ("far-destroy", S, "                move_to_list(&list, b);\n        }\n    }\n    destroy_list(&list);",
     "                move_to_list(&list, b);\n        }\n    }"),
    ("spawn-dyn", S, "        afx_get_emitters(&si->DynamicEmitterList,\n"
     "                         si->DynamicEmitterGroupNameHash);",
     "        afx_get_emitters(&si->DynamicEmitterList,\n"
     "                         si->AnchorEmitterGroupNameHash);"),
    ("spawn-vcount", S, "                                           NumSmokeableSpawners,\n",
     "                                           NumSmokeableSpawners + 1,\n"),
    ("spawn-count", S, "    SmokeableSlotPool = bNewSlotPool((int)sizeof(Smokeable), 32,",
     "    SmokeableSlotPool = bNewSlotPool((int)sizeof(Smokeable), 31,"),
    ("spawn-reg", S, "    smokeable_register_creator(ST_BASIC_SMOKEABLE, smokeable_basic_creator);\n", ""),
    ("spawn-null", S, "        if (h == NULL)\n            continue;\n"
     "        inst = &h->pSceneryInstance[sp->SceneryInstanceNumber];\n"
     "        if (TheRaceParameters",
     "        if (h == NULL)\n            break;\n"
     "        inst = &h->pSceneryInstance[sp->SceneryInstanceNumber];\n"
     "        if (TheRaceParameters"),
    ("spawn-2p", S, "        if (TheRaceParameters.NumPlayerCars == 2",
     "        if (TheRaceParameters.NumPlayerCars == 1"),
    ("spawn-excl", S, "            && (inst->ExcludeFlags & 1) != 0)",
     "            && (inst->ExcludeFlags & 2) != 0)"),
    ("spawn-info", S, "        if (find_smokeable_info(sp->SmokeableInfoHash) == NULL)\n            continue;\n", ""),
    ("clear-delall", S, "    delete_smokeable_collision_bodies();\n    if (VirginSmokeableSlotPool", "    if (VirginSmokeableSlotPool"),
    ("clear-vnull", S, "        VirginSmokeableSlotPool = NULL;\n", ""),
    ("clear-snull", S, "        SmokeableSlotPool = NULL;\n    }\n    for", "    }\n    for"),
    ("clear-anchor", S, "        afx_delete_emitters(&si->AnchorEmitterList);\n", ""),
    ("convert-destroy", S, "    if (b != NULL)\n        body_destroy(b, 3);", "    if (s != NULL)\n        body_destroy(b, 3);"),
    # VirginSmokeable.
    ("virgin-id", S, "~(int32_t)(spawner - pSmokeableSpawners), 2);",
     "-(int32_t)(spawner - pSmokeableSpawners), 2);"),
    ("virgin-type", S, "~(int32_t)(spawner - pSmokeableSpawners), 2);",
     "~(int32_t)(spawner - pSmokeableSpawners), 1);"),
    ("virgin-vt", S, "    v->Static.Body._vtable = VIRGINSMOKEABLE_VTABLE;\n    cs->", "    cs->"),
    ("virgin-count", S, "    cs->NumVirginSmokeableCollisionBodies++;\n", ""),
    ("virgin-high", S, "    if (cs->HighestNumVirginSmokeableCollisionBodies\n"
     "        < cs->NumVirginSmokeableCollisionBodies)",
     "    if (cs->HighestNumVirginSmokeableCollisionBodies\n"
     "        <= cs->NumVirginSmokeableCollisionBodies - 2)"),
    ("virgin-spawner", S, "    v->pSmokeableSpawner = spawner;\n", ""),
    ("virgin-excl", S, "    inst->ExcludeFlags &= 0xffef;", "    inst->ExcludeFlags &= 0xffdf;"),
    ("virgin-info", S, "    v->pSceneryInfo = &h->pSceneryInfo[inst->SceneryInfoNumber];",
     "    v->pSceneryInfo = &h->pSceneryInfo[0];"),
    ("virgin-name", S, '"VirginSmokeable%s"', '"VirginSmokable%s"'),
    ("virgin-poly", S, "    v->Static.Body.pPoly = NULL;\n", ""),
    ("virgin-dis", S, "    v->Static.Body.CollisionsDisabled = 0;\n", "    v->Static.Body.CollisionsDisabled = 1;\n"),
    ("virgin-acd", S, "    v->Static.Body.ActiveCollisionDetection = 0;\n    mn.x",
     "    v->Static.Body.ActiveCollisionDetection = 1;\n    mn.x"),
    ("virgin-bb", S, "    mx.y = (float)inst->BBox.BBoxMax[1];", "    mx.y = (float)inst->BBox.BBoxMax[0];"),
    ("virgin-ident", S, "    bIdentity(&m);\n", ""),
    ("vdel-count", S, "    TheCollisionStats.NumVirginSmokeableCollisionBodies--;\n", ""),
    ("vdel-excl", S, "    v->pSceneryInstance->ExcludeFlags |= 0x10;", "    v->pSceneryInstance->ExcludeFlags |= 0x20;"),
    ("vdel-flags", S, "    staticcollisionbody_destroy(&v->Static, 0);", "    staticcollisionbody_destroy(&v->Static, 1);"),
    ("vdel-free", S, "    if (flags & 1)\n        bSlotFree(VirginSmokeableSlotPool, v);",
     "    if (flags & 2)\n        bSlotFree(VirginSmokeableSlotPool, v);"),
    ("vconv-full", S, "    if (bIsSlotPoolFull(SmokeableSlotPool))\n        return NULL;", ""),
    ("vconv-pos", S, "    m.v3.y = inst->Position[1];", "    m.v3.y = inst->Position[0];"),
    ("vconv-hash", S, "v->pSceneryInfo->NameHash[0]);", "v->pSceneryInfo->NameHash[1]);"),
    ("vconv-smoke", S, "    if (body_int(s, SMOKEABLE_VT_GET_SMOKE_TYPE) == 0) {",
     "    if (body_int(s, SMOKEABLE_VT_GET_SMOKE_TYPE) != 0) {"),
    ("vconv-found", S, "        if (found != 0) {\n            raise", "        if (1) {\n            raise"),
    ("vconv-com", S, "        + s->SI->CenterOfMass[2]) * n.z))",
     "        - s->SI->CenterOfMass[2]) * n.z))"),
    ("vconv-lift", S, "                    + 0.05f;", "                    + 0.06f;"),
    ("vconv-pos-raise", S, "            if (0.0f < raise) {", "            if (0.0f <= raise) {"),
    ("vconv-gr", S, "                s->GroundRaise = raise;\n", ""),
    ("vconv-z", S, "                m.v3.z = m.v3.z + raise;\n", ""),
    ("vconv-spawner", S, "    s->pSmokeableSpawner = v->pSmokeableSpawner;\n", ""),
    # Smokeable.
    ("copy-null", S, "        if (c == NULL)\n            continue;\n", ""),
    ("copy-state", S, "        c->State = 1;", "        c->State = 2;"),
    ("copy-head", S, "        head->prev = &node->Node;\n        node->Node.next", "        node->Node.next"),
    ("copy-obj", S, "        node->Object = c;", "        node->Object = e;"),
    ("init-type", S, "    dynamiccollisionbody_init(&s->Dynamic, id, 1, &s->TC);",
     "    dynamiccollisionbody_init(&s->Dynamic, id, 2, &s->TC);"),
    ("init-sysvt", S, "    s->System._vtable = SMOKEABLE_SYSTEM_VTABLE;\n    topology_init", "    topology_init"),
    ("init-wo", S, "    worldobject_construct(&s->TheWorldObject, name_hash, NULL, 0);",
     "    worldobject_construct(&s->TheWorldObject, name_hash, NULL, 1);"),
    ("init-anchor", S, "    s->AnchorEmitterList.next = &s->AnchorEmitterList;\n", ""),
    ("init-count", S, "    cs->NumSmokeableCollisionBodies++;\n", ""),
    ("init-high", S, "        < cs->NumSmokeableCollisionBodies)", "        < cs->NumSmokeableCollisionBodies - 1)"),
    ("init-rbi", S, "                        &info->RBI);", "                        NULL);"),
    ("init-mode", S, "    s->Dynamic.PhysicsMode = 1;", "    s->Dynamic.PhysicsMode = 0;"),
    ("init-acd", S, "    s->Dynamic.Body.ActiveCollisionDetection = 0;\n    s->Dynamic.pSystem",
     "    s->Dynamic.Body.ActiveCollisionDetection = 1;\n    s->Dynamic.pSystem"),
    ("init-created", S, "    s->TimeCreated.PackedTime = (uint32_t)WorldTimer;",
     "    s->TimeCreated.PackedTime = (uint32_t)WorldTimer + 1;"),
    ("init-name", S, '"Smokeable%s", info->Name);', '"Smokable%s", info->Name);'),
    ("init-pipe", S, "    if (pp != NULL)\n        s->Dynamic.Body.pPoly", "    if (pp == NULL)\n        s->Dynamic.Body.pPoly"),
    ("init-rect", S, "            1.5f, -1.5f, 1.5f, -1.5f, 1.5f, -1.5f);",
     "            1.5f, -1.5f, 1.5f, -1.5f, 1.0f, -1.5f);"),
    ("init-bv", S, "    dynamiccollisionbody_build_bounding_volumes(&s->Dynamic);\n", ""),
    ("init-comp", S, "    physicssystem_add_component(&s->System,\n"
     "                                (PhysicsComponent *)(void *)rb);\n", ""),
    ("init-anchor-str", S, "    s->AnchorStrength = info->AnchorStrength;",
     "    s->AnchorStrength = info->BreakingStrength;"),
    ("init-gr", S, "    s->GroundRaise = 0.0f;\n    s->BreakingStrength", "    s->BreakingStrength"),
    ("init-child", S, "    if (!smokeable_does_child_art_exist(s))\n        s->BreakingStrength = 0.0f;\n", ""),
    ("init-calib", S, "    smokeable_calibrate(s);\n    s->AnchorEmittersAdded = 0;",
     "    s->AnchorEmittersAdded = 0;"),
    ("init-dynhash", S, "    if (info->DynamicEmitterGroupNameHash != 0)",
     "    if (info->AnchorEmitterGroupNameHash != 0)"),
    ("init-dynlist", S, "        copy_emitters(s, &s->DynamicEmitterList, 1);",
     "        copy_emitters(s, &s->DynamicEmitterList, 0);"),
    ("drain-free", S, "        bpnode_free(node);\n", ""),
    ("drain-added", S, "        if (*added != 0)\n", "        if (*added == 1)\n"),
    ("drain-null", S, "        if (e != NULL)\n            acid_emitter_delete(e, 3);",
     "        acid_emitter_delete(e, 3);"),
    ("drain-flags", S, "            acid_emitter_delete(e, 3);", "            acid_emitter_delete(e, 1);"),
    ("sdel-count", S, "    TheCollisionStats.NumSmokeableCollisionBodies--;\n", ""),
    ("sdel-pipe", S, "    if (find_pipeline_polyhedron(s->SI->NameHash, NULL) == NULL\n"
     "        && s->Dynamic.Body.pPoly != NULL)",
     "    if (s->Dynamic.Body.pPoly != NULL)"),
    ("sdel-dyn", S, "    drain_emitters(s, &s->DynamicEmitterList, &s->DynamicEmittersAdded);",
     "    drain_emitters(s, &s->DynamicEmitterList, &s->AnchorEmittersAdded);"),
    ("sdel-wo", S, "    worldobject_destruct(&s->TheWorldObject, 2);",
     "    worldobject_destruct(&s->TheWorldObject, 3);"),
    ("sdel-tc", S, "    topology_destroy(&s->TC);\n    physicssystem_fini", "    physicssystem_fini"),
    ("sdel-free", S, "    if (flags & 1)\n        bSlotFree(SmokeableSlotPool, s);",
     "    if (flags & 2)\n        bSlotFree(SmokeableSlotPool, s);"),
    ("sip-rw", S, "    r.v3.w = 1.0f;\n    l.x", "    l.x"),
    ("sip-pw", S, "    p.w = 1.0f;\n    if (vel", "    p.w = 0.0f;\n    if (vel"),
    ("sip-mass", S, "        p.y = vel->y * mass;", "        p.y = vel->y;"),
    ("sip-com", S, "    pos.y = pos.y + t.y;", "    pos.y = pos.y - t.y;"),
    ("sip-gr", S, "    w.v3.z = w.v3.z - s->GroundRaise;", "    w.v3.z = w.v3.z + s->GroundRaise;"),
    ("sip-en", S, "    s->TheWorldObject.Enabled = 1;\n    s->Dynamic.BackupPosition.x",
     "    s->Dynamic.BackupPosition.x"),
    ("sip-brot", S, "    s->Dynamic.BackupRotation = r;", "    s->Dynamic.BackupRotation = *m;"),
    ("sip-btime", S, "    s->Dynamic.BackupTime = 5000.0f;", "    s->Dynamic.BackupTime = 0.0f;"),
    ("sip-aux", S, "    ((VtVoidFn)e->fn)(vt_this(&s->System, e));\n    dynamiccollisionbody_update_position",
     "    dynamiccollisionbody_update_position"),
    ("sip-upd", S, "    dynamiccollisionbody_update_position(&s->Dynamic);\n    for (n = s->AnchorEmitterList",
     "    for (n = s->AnchorEmitterList"),
    ("sip-dynlw", S, "        node_emitter(n)->LocalWorld = *m;\n}", "        ;\n}"),
    ("calib-inertia", S, "    rigidbody_calculate_inertia_tensor(rigid_body(s));\n", ""),
    ("drag-coef", S, "SmokeableAirDragCoefficient = 0.01f;", "SmokeableAirDragCoefficient = 0.02f;"),
    ("drag-sign", S, "    float    k = -length3(v.x, v.y, v.z) * SmokeableAirDragCoefficient;",
     "    float    k = length3(v.x, v.y, v.z) * SmokeableAirDragCoefficient;"),
    ("drag-y", S, "    f.y = v.y * k;", "    f.y = v.x * k;"),
    ("drag-at", S, "    at.z = 0.0f;\n    at.w = 0.0f;", "    at.z = 1.0f;\n    at.w = 0.0f;"),
    # Move.
    ("move-begin", S, "    dynamiccollisionbody_begin_move(&s->Dynamic, dt);\n", ""),
    ("move-awake", S, "    if (s->Awake != 0) {\n        int32_t drag", "    if (1) {\n        int32_t drag"),
    ("move-calib", S, "        smokeable_calibrate(s);\n        rigid_body(s)->MotionDamping", "        rigid_body(s)->MotionDamping"),
    ("move-damp", S, "        rigid_body(s)->MotionDamping = 1;", "        rigid_body(s)->MotionDamping = 0;"),
    ("move-hash-a", S, "                == SMOKEABLE_DRAG_HASH_A\n", "                == SMOKEABLE_DRAG_HASH_B\n"),
    ("move-hash-b", S, "                   == SMOKEABLE_DRAG_HASH_B)", "                   == SMOKEABLE_DRAG_HASH_A)"),
    ("move-steps", S, "        n = ee_trunc_w(ee_div(dt, SmokeableMaxTimeStep)) + 1;",
     "        n = ee_trunc_w(ee_div(dt, SmokeableMaxTimeStep));"),
    ("move-step", S, "SmokeableMaxTimeStep        = 0.01f;", "SmokeableMaxTimeStep        = 0.02f;"),
    ("move-h", S, "        h = ee_div(dt, (float)n);", "        h = dt;"),
    ("move-drag", S, "            if (drag)\n", "            if (!drag)\n"),
    ("move-ortho", S, "            eOrthonormalizeMatrix(&rb->State.R, &rb->State.R);\n", ""),
    ("move-sleep", S, "        smokeable_consider_sleeping(s);\n", ""),
    ("move-posch", S, "        smokeable_position_changed(s);\n        if", "        if"),
    ("move-touch", S, "            s->TimeLastCarContact.PackedTime = (uint32_t)WorldTimer;\n    }",
     "            ;\n    }"),
    ("move-com", S, "    m.v3.y = rb->State.X.y - t.y;", "    m.v3.y = rb->State.X.y + t.y;"),
    ("move-gr", S, "    m.v3.z = m.v3.z - s->GroundRaise;\n    if", "    if"),
    ("move-blink", S, "    if (body_int(s, COLLISIONBODY_VT_IS_BLINKING) != 0\n        && (WorldLoopCounter & 1) == 0) {",
     "    if (body_int(s, COLLISIONBODY_VT_IS_BLINKING) != 0\n        && (WorldLoopCounter & 1) != 0) {"),
    ("move-blink2", S, "    if (body_int(s, COLLISIONBODY_VT_IS_BLINKING) != 0\n        && (WorldLoopCounter & 1) == 0) {",
     "    if ((WorldLoopCounter & 1) == 0) {"),
    ("move-disable", S, "        s->TheWorldObject.Enabled = 0;\n    } else {", "    } else {"),
    ("move-emitpos", S, "    m.v3.z = m.v3.z + t.z;\n    m.v3.w = 1.0f;\n    smokeable_service_emitters",
     "    m.v3.w = 1.0f;\n    smokeable_service_emitters"),
    ("move-timers", S, "    if (smokeable_check_timers(s))\n        return;\n", "    smokeable_check_timers(s);\n"),
    ("move-anchor", S, "    if (s->AnchorStrength == 0.0f) {\n        float r", "    if (s->AnchorStrength != 0.0f) {\n        float r"),
    ("move-decay", S, "SmokeableGroundRaiseDecay   = 0.5f;", "SmokeableGroundRaiseDecay   = 0.25f;"),
    ("move-clamp", S, "        if (r < 0.0f)\n            s->GroundRaise = 0.0f;", ""),
    ("posch-min", S, "    float           r = min_s(s->Dynamic.CylinderBaseHeight,",
     "    float           r = max_s(s->Dynamic.CylinderBaseHeight,"),
    ("posch-scale", S, "length3(v->x, v->y, v->z) * 0.05f, 6.0f);", "length3(v->x, v->y, v->z) * 0.04f, 6.0f);"),
    ("posch-cap", S, "length3(v->x, v->y, v->z) * 0.05f, 6.0f);", "length3(v->x, v->y, v->z) * 0.05f, 5.0f);"),
    ("posch-r", S, "    r = r + sp;\n", ""),
    ("posch-upd", S, "    dynamiccollisionbody_update_position(&s->Dynamic);\n}\n\nvoid smokeable_service",
     "}\n\nvoid smokeable_service"),
    ("svc-awake", S, "    if (s->Awake == 0)\n        return;\n    v = body_vector", "    v = body_vector"),
    ("svc-lw", S, "        e->LocalWorld = *m;\n", ""),
    ("svc-vz", S, "        e->InheritVelocity.z = v->z;\n        e->InheritVelocity.w = 0.0f;\n    }\n    if",
     "        e->InheritVelocity.z = v->y;\n        e->InheritVelocity.w = 0.0f;\n    }\n    if"),
    ("svc-added", S, "    if (s->AnchorEmittersAdded != 1)\n        return;",
     "    if (s->AnchorEmittersAdded == 0)\n        return;"),
    ("svc-two", S, "    s->AnchorEmittersAdded = 2;", "    s->AnchorEmittersAdded = 1;"),
    ("timers-spawner", S, "    if (s->pSmokeableSpawner != NULL && !timer_is_valid(&s->TimeAwoken)",
     "    if (!timer_is_valid(&s->TimeAwoken)"),
    ("timers-awoken", S, "    if (s->pSmokeableSpawner != NULL && !timer_is_valid(&s->TimeAwoken)",
     "    if (s->pSmokeableSpawner != NULL"),
    ("timers-wit", S, "        && s->Dynamic.Body.NumWitnesses == 0\n", "\n"),
    ("timers-two", S, "        && 2.0f < seconds_since(&s->TimeCreated)) {",
     "        && 1.0f < seconds_since(&s->TimeCreated)) {"),
    ("timers-revirgin", S, "        virginsmokeable_init(\n            (VirginSmokeable *)bSlotOMalloc(VirginSmokeableSlotPool),\n"
     "            s->pSmokeableSpawner);\n", ""),
    ("timers-life0", S, "    if (timer_is_valid(&s->TimeAwoken) && s->SI->Lifetime != 0.0f",
     "    if (timer_is_valid(&s->TimeAwoken)"),
    ("timers-life", S, "        && s->SI->Lifetime <= seconds_since(&s->TimeAwoken)) {",
     "        && s->SI->Lifetime < seconds_since(&s->TimeCreated)) {"),
    ("timers-end", S, "        ((VtVoidFn)e->fn)(vt_this(s, e));\n        body_destroy(s, 3);",
     "        body_destroy(s, 3);"),
    ("anchors-flag", S, "    s->AnchorEmittersAdded = 1;\n}", "    s->AnchorEmittersAdded = 2;\n}"),
    ("anchors-add", S, "        acid_system_add_auto_emitter(&WorldEffects, node_emitter(n));\n    s->AnchorEmittersAdded = 1;",
     "        ;\n    s->AnchorEmittersAdded = 1;"),
    # ConsiderImpulse.
    ("ci-awake", S, "    if (s->Awake == 0) {\n        float as", "    if (s->Awake != 0) {\n        float as"),
    ("ci-zero", S, "        if (as == 0.0f) {\n            smokeable_awaken(s);",
     "        if (as == 1.0f) {\n            smokeable_awaken(s);"),
    ("ci-com-y", S, "            a.y = at->y + si->CenterOfMass[1];", "            a.y = at->y;"),
    ("ci-cross", S, "            c.z = a.x * j->y - j->x * a.y;", "            c.z = a.x * j->y + j->x * a.y;"),
    ("ci-max", S, "            m = max_s(length3(c.x, c.y, c.z), length3(j->x, j->y, j->z));",
     "            m = min_s(length3(c.x, c.y, c.z), length3(j->x, j->y, j->z));"),
    ("ci-lt", S, "            if (m < as)\n                return 1.0f;", "            if (m <= as)\n                return 1.0f;"),
    ("ci-ret", S, "            if (m < as)\n                return 1.0f;", "            if (m < as)\n                return 0.0f;"),
    ("ci-f", S, "            f = ee_div(as, m);", "            f = ee_div(m, as);"),
    ("ci-sound", S, "            collision_sound_play_smokeable(\n"
     "                body_vector(s, COLLISIONBODY_VT_GET_POSITION), s->SI);\n", ""),
    ("ci-imp", S, "            imp.x = j->x * -f;", "            imp.x = j->x * f;"),
    ("ci-pt", S, "            pt.z = 0.0f - si->CenterOfMass[2];", "            pt.z = si->CenterOfMass[2];"),
    ("ci-pt-w", S, "            pt.pad = 1.0f - si->Padding;", "            pt.pad = 0.0f - si->Padding;"),
    ("ci-awaken", S, "            smokeable_awaken(s);\n            s->AnchorStrength = 0.0f;",
     "            s->AnchorStrength = 0.0f;"),
    ("ci-anchor", S, "            s->AnchorStrength = 0.0f;\n            e = vt_slot",
     "            e = vt_slot"),
    ("ci-apply", S, "            ((VtImpulseFn)e->fn)(vt_this(s, e), &imp, &pt);\n", ""),
    ("ci-emit", S, "            smokeable_activate_anchor_emitters(s);\n        }", "        }"),
    ("ci-bs0", S, "    if (bs == 0.0f)\n        return f;", "    if (bs < 0.0f)\n        return f;"),
    ("ci-sum", S, "    sum = f * ((fabsf(j->x) + fabsf(j->y)) + fabsf(j->z));",
     "    sum = ((fabsf(j->x) + fabsf(j->y)) + fabsf(j->z));"),
    ("ci-sum-z", S, "    sum = f * ((fabsf(j->x) + fabsf(j->y)) + fabsf(j->z));",
     "    sum = f * (fabsf(j->x) + fabsf(j->y));"),
    ("ci-le", S, "    if (bs <= sum) {", "    if (bs < sum) {"),
    ("ci-broken", S, "        s->BreakingStrength = -1.0f;", "        s->BreakingStrength = 0.0f;"),
    ("ci-bf", S, "        f = ee_div(-f * bs, sum);", "        f = ee_div(f * bs, sum);"),
    ("ci-half", S, "        s->BreakingStrength = bs - sum * 0.5f;", "        s->BreakingStrength = bs - sum;"),
    # Sleep and wake.
    ("cs-car", S, "    if (!(2.0f < seconds_since(&s->TimeLastCarContact)))\n        return;\n    if (s->Dynamic",
     "    if (!(1.0f < seconds_since(&s->TimeLastCarContact)))\n        return;\n    if (s->Dynamic"),
    ("cs-ncol", S, "    if (s->Dynamic.Body.NumCollisions == 0)\n        return;\n    c =", "    c ="),
    ("cs-age", S, "    if (!(0.5f < seconds_since(&c->CollisionTime)))", "    if (!(0.25f < seconds_since(&c->CollisionTime)))"),
    ("cs-v", S, "rb->Velocity.z) < 1.5f))", "rb->Velocity.z) < 1.0f))"),
    ("cs-w", S, "                  rb->AngularVelocity.z) < 4.0f))", "                  rb->AngularVelocity.z) < 3.0f))"),
    ("sleep-awake", S, "    s->Awake = 0;\n    s->Dynamic.Body.ActiveCollisionDetection = 0;\n    AwakeSmokeablesCount--;",
     "    s->Dynamic.Body.ActiveCollisionDetection = 0;\n    AwakeSmokeablesCount--;"),
    ("sleep-acd", S, "    s->Dynamic.Body.ActiveCollisionDetection = 0;\n    AwakeSmokeablesCount--;",
     "    AwakeSmokeablesCount--;"),
    ("sleep-count", S, "    AwakeSmokeablesCount--;\n", ""),
    ("sleep-box", S, "    topology_clear_interest_bbox(&s->TC);\n", ""),
    ("wake-acd", S, "    s->Dynamic.Body.ActiveCollisionDetection = 1;\n    s->Awake = 1;", "    s->Awake = 1;"),
    ("wake-count", S, "    AwakeSmokeablesCount++;\n", ""),
    ("wake-once", S, "    if (s->DynamicEmittersAdded == 0) {", "    if (1) {"),
    ("wake-flag", S, "        s->DynamicEmittersAdded = 1;\n    }", "    }"),
    ("wake-valid", S, "    if (!timer_is_valid(&s->TimeAwoken))\n        s->TimeAwoken.PackedTime = (uint32_t)WorldTimer;",
     "    s->TimeAwoken.PackedTime = (uint32_t)WorldTimer;"),
    # Breaking.
    ("brk-digit", S, "        name[6] = (char)('1' + i);\n        h =", "        name[6] = (char)('0' + i);\n        h ="),
    ("brk-seed", S, "        h = bchunk_hash_from(name,\n                             worldobject_get_name_hash(&s->TheWorldObject));",
     "        h = bchunk_hash(name);"),
    ("brk-child", S, "s->SI->pChildren[i], h);", "s->SI->pChildren[0], h);"),
    ("brk-mat", S, "        smokeable_set_initial_position(c, &s->TheWorldObject.Matrix, NULL);\n        smokeable_awaken(c);",
     "        smokeable_awaken(c);"),
    ("brk-awaken", S, "        smokeable_awaken(c);\n        pieces[i]", "        pieces[i]"),
    ("brk-destroy", S, "    body_destroy(s, 3);\n    return n;", "    return n;"),
    ("art-digit", S, "        name[6] = (char)('1' + i);\n        if", "        name[6] = (char)('2' + i);\n        if"),
    ("art-ret", S, "            return 0;\n    }\n    return 1;", "            return 1;\n    }\n    return 1;"),
    # The system table's slot 16.
    ("mc-fast", S, "    if (0.7f < v || 0.7f < w)", "    if (0.7f < v)"),
    ("mc-fast-lim", S, "    if (0.7f < v || 0.7f < w)", "    if (0.8f < v || 0.7f < w)"),
    ("mc-ncol", S, "    if (s->Dynamic.Body.NumCollisions == 0)\n        return 0;", ""),
    ("mc-slow", S, "    if (0.25f < v || 0.25f < w)", "    if (0.25f < v || 0.3f < w)"),
    ("mc-car", S, "    return 2.0f < seconds_since(&s->TimeLastCarContact) ? 1 : 2;",
     "    return 2.0f < seconds_since(&s->TimeLastCarContact) ? 2 : 1;"),
    ("aux-first", S, "    physicssystem_compute_auxiliaries(&s->System);\n    switch",
     "    switch"),
    ("aux-damp", S, "        rb->State.P.y = rb->State.P.y * 0.95f;", "        rb->State.P.y = rb->State.P.y * 0.9f;"),
    ("aux-damp-l", S, "        rb->State.L.z = rb->State.L.z * 0.95f;", "        rb->State.L.z = rb->State.L.z;"),
    ("aux-stop", S, "        rb->State.P.x = 0.0f;\n", ""),
    ("aux-stop-l", S, "        rb->State.L = rb->State.P;\n", ""),
    ("aux-again", S, "    if (changed)\n        physicssystem_compute_auxiliaries", "    if (!changed)\n        physicssystem_compute_auxiliaries"),
    ("touch-c2", S, "        if (c1 != NULL || c2 != NULL)", "        if (c1 != NULL)"),
    ("touch-i", S, "            collisionbody_get_collision(&s->Dynamic.Body, i), &c1, &c2);",
     "            collisionbody_get_collision(&s->Dynamic.Body, 0), &c1, &c2);"),
    # The accessors and the table.
    ("ta-valid", S, "    if (!timer_is_valid(&s->TimeAwoken))\n        return 0.0f;\n", ""),
    ("blink-set", S, "    s->Blinking = (int8_t)on;", "    s->Blinking = 1;"),
    ("ai-awake", S, "    if (s->Awake != 0)\n        rigidbody_apply_impulse", "    if (1)\n        rigidbody_apply_impulse"),
    ("ace", S, "    return b->CollisionsDisabled == 0;", "    return b->CollisionsDisabled != 0;"),
    ("mi-anchor", S, "        return rigid_body(s)->Mass_inv;\n    return 0.0f;", "        return rigid_body(s)->Mass_inv;\n    return 1.0f;"),
    ("iti-anchor", S, "    if (s->AnchorStrength == 0.0f)\n        return &rigid_body(s)->I_body_inv;",
     "    if (s->AnchorStrength != 0.0f)\n        return &rigid_body(s)->I_body_inv;"),
    ("moveable", S, "    return ((Smokeable *)(void *)b)->AnchorStrength == 0.0f;",
     "    return ((Smokeable *)(void *)b)->AnchorStrength != 0.0f;"),
    ("bounce", S, "    return ((Smokeable *)(void *)b)->SI->Bounciness;", "    return ((Smokeable *)(void *)b)->SI->Friction;"),
    ("vt-slot", S, "    E(smokeable_get_friction),\n    E(smokeable_get_smoke_type),",
     "    E(smokeable_get_smoke_type),\n    E(smokeable_get_friction),"),
    ("vt-sys", S, "    smokeable_system_vt[2].delta = d;\n", ""),
    ("vt-virgin", S, "    E(virginsmokeable_get_position),\n    E(staticcollisionbody_get_velocity),",
     "    E(staticcollisionbody_get_velocity),\n    E(virginsmokeable_get_position),"),
    # The data side.
    ("spawner-neg", I, "    if (i < 0)\n        return NULL;", "    if (i < -1)\n        return NULL;"),
    ("spidx-null", I, "        return -1;\n    return (int32_t)(s - pSmokeableSpawners);",
     "        return 0;\n    return (int32_t)(s - pSmokeableSpawners);"),
    ("mil-terrain", I, "    si->TheTerrainType = t;", "    si->TheTerrainType = 0;"),
    ("mil-dyn", I, "    si->DynamicEmitterList.prev = &si->DynamicEmitterList;\n", ""),
    ("rec-align", I, "(((uintptr_t)c + 23) & ~(uintptr_t)15);", "(((uintptr_t)c + 8) & ~(uintptr_t)15);"),
    ("rec-used", I, "    *n = (int32_t)((bchunk_u32(c + 4) - used)", "    *n = (int32_t)((bchunk_u32(c + 4))"),
    ("load-type", I, "    if (type == 0x00034026u) {\n        int32_t  n, i, k;",
     "    if (type == 0x00034025u) {\n        int32_t  n, i, k;"),
    ("load-tail", I, "            SmokeableInfoList.prev = &si->Node;\n", ""),
    ("load-mil", I, "            smokeableinfo_memory_image_load(si);\n", ""),
    ("load-k", I, "            for (k = 0; k < 4; k++)", "            for (k = 0; k < 3; k++)"),
    ("load-k0", I, "                if (si->ChildNameHashes[k] != 0)\n", ""),
    ("load-sp", I, "        pSmokeableSpawners = (SmokeableSpawner *)(void *)(chunk + 8);",
     "        pSmokeableSpawners = (SmokeableSpawner *)(void *)(chunk + 16);"),
    ("load-nsp", I, "        NumSmokeableSpawners = (int32_t)(bchunk_u32(chunk + 4) >> 3);",
     "        NumSmokeableSpawners = (int32_t)(bchunk_u32(chunk + 4) >> 2);"),
    ("load-ret", I, "        return 1;\n    }\n    return 0;\n}\n\nint smokeable_unloader",
     "        return 1;\n    }\n    return 1;\n}\n\nint smokeable_unloader"),
    ("unload-next", I, "            prev->next = next;\n", ""),
    ("unload-sp", I, "        pSmokeableSpawners = NULL;\n", ""),
    ("unload-n", I, "        NumSmokeableSpawners = 0;\n", ""),
    ("find-hash", I, "        if (((SmokeableInfo *)(void *)n)->NameHash == hash)",
     "        if (((SmokeableInfo *)(void *)n)->NameHash != hash)"),
]

EQUIVALENT = {
    "rec-used": "the alignment's padding is under one record, so a chunk "
                "of whole records counts the same",
    "delete-flags": "Smokeable's destructor tests only bit 0",
    "vconv-pos-raise": "a raise of exactly 0 sets GroundRaise to the 0 it "
                       "has and adds 0 to the height",
    "drain-null": "no node holds a NULL emitter: copy_emitters skips a "
                  "failed copy",
    "move-timers": "past CheckTimers' destroy only GroundRaise is written, "
                   "in the freed slot, which the next init sets again",
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
        todo, SOURCES, "smokeable_test",
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
