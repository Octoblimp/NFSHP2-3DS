#!/usr/bin/env python3
"""Cross-check 3DS Files/source/chopper.c, the police helicopter's object
(12k-2), against the retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own code: Chopper's constructor (0x001e7a90),
destructor (0x001e7b80), ClearVariables (0x001e7c38), FollowThisCar
(0x001e7f80), AttackCar (0x001e8040), AdjustBombTarget (0x001e8140),
ShiftTarget (0x001e81d8), FindUnobstructedSpot (0x001e82c0),
FindGroundHeight (0x001e8358), PlaceChopperInWorld (0x001e83b0),
RemoveChopperFromWorld (0x001e84a8), ChopperBehindCar (0x001e84f0),
RotateToChopperCoord (0x001e8540) with RotateVector (0x002313e0) and
bSinCos under it, GetMaxDeceleration (0x001e8560), AbortBombingRun
(0x001eadf0), Mute (0x001ead80), UpdateSound (0x001eadb0),
FindChopperPointFromScratch (0x001e8798), FindChopperRoutePoint
(0x001e87e8), CalcMatrix (0x001ea3f8) with bIdentity and eRotateX, Y
and Z under it, and the WorldObject update (0x001ea578); bStringHash and
the bombing runs' table (0x0031a7c8) as shipped. The harness
(tools/src/chopper_test.c) runs chopper.c, coputil.c, emath.c, bmath.c
and bmatrix.c and prints the same lines.

**The stubs**, logged and answered by the same rule on both sides: the
TopologyCoordinate's constructor, destructor, SetInterestBBox,
ClearInterestBBox and GetElevation; the TrackPathCoordinate's
constructor, ResetPosition and the manager's CompareDistances; bOMalloc,
__builtin_delete, and WorldObject's constructor and destructor;
afxGetEmitters and afxDeleteEmitters; HasSignposts; Car::GetRoute and
GetRoutePoint; GuessTargetDestinations, GetNextRoutePoint and
GetNearestRoutePoint; HeliSheet::FindZValue; TrackRoute::FindClosestPoint,
TrackRoutePoint::GetSignpost and Signpost::GetNewRoute; and
sound::CreateChopperSound, whose sound's table is the checker's own, with
a this-adjustment of 8.

**The port's divergences**, which the model is made to share:
  - With no sound (gCreateChopperSoundFn NULL) the port skips every call
    through it. Retail always builds one and calls it unguarded, so the
    model hands the calls to a silent sound of its own.
  - FindUnobstructedSpot's flags word starts at 0 in the port. Retail's
    first FindZValue may miss and leave it as the stack had it, so the
    model zeroes that word on entry.

**Compared** are the stubs' logs, each method's result, and after each
call every field of the helicopter at retail's offsets, the padding
included.

**The script** builds helicopters with each demo flag and the egg on and
off, with and without a sound, and frees them with and without delete;
clears one after scrambling it; follows cars from every plan with and
without the egg's word, a sheet and signposts; starts bombing runs of
each type from each plan, at speeds and distances either side of the
run's lead, ahead of the car and behind it; shifts targets past points
the sheet does not cover; walks to open ground over runs of covered
polygons, misses included; and places, removes, turns and rebuilds the
helicopter's matrix at angles round the circle and past it.

    python tools/chopper_check.py
    python tools/chopper_check.py --mutate [--only a,b]
    python tools/chopper_check.py --dump out/chopper
"""
import argparse
import math
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

HARNESS = "tools/src/chopper_test.c"
CHOP = "3DS Files/source/chopper.c"
COPUTIL = "3DS Files/source/coputil.c"
SOURCES = [HARNESS, CHOP, COPUTIL, "3DS Files/source/emath.c",
           "3DS Files/source/bmath.c", "3DS Files/source/bmathtab.c",
           "3DS Files/source/bmatrix.c",
           "3DS Files/source/vtable.c"]
HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = retail_model.RETAIL_GP
G_SHEET = GP - 17128                    # TheHeliSheet
G_WORLD = GP - 22120                    # pCurrentWorld
G_WOP = GP - 18112                      # WorldObjectSlotPool
RP = 0x0031a898                         # TheRaceParameters
EGGS = 0x0031d7f4                       # the egg table's pointer
TPM = 0x0031bc38                        # TheTrackPathManager

F_CTOR = 0x001e7a90
F_DTOR = 0x001e7b80
F_CLEAR = 0x001e7c38
F_FOLLOW = 0x001e7f80
F_ATTACK = 0x001e8040
F_ADJUST = 0x001e8140
F_SHIFT = 0x001e81d8
F_SPOT = 0x001e82c0
F_GROUND = 0x001e8358
F_PLACE = 0x001e83b0
F_REMOVE = 0x001e84a8
F_BEHIND = 0x001e84f0
F_ROTATE = 0x001e8540
F_DECEL = 0x001e8560
F_SCRATCH = 0x001e8798
F_ROUTEPT = 0x001e87e8
F_MATRIX = 0x001ea3f8
F_WOBJ = 0x001ea578
F_MUTE = 0x001ead80
F_USOUND = 0x001eadb0
F_ABORT = 0x001eadf0

S_TOPO_CTOR = 0x00151c28
S_TOPO_DTOR = 0x00151c70
S_BBOX = 0x00151d30
S_CLEARBB = 0x00151cd0
S_ELEV = 0x00152070
S_TP_CTOR = 0x002086b8
S_TP_RESET = 0x00208838
S_CMP = 0x00208598
S_OMALLOC = 0x00257c80
S_DELETE = 0x00114e98
S_WOCTOR = 0x001cd760
S_WODTOR = 0x001cd828
S_AFXGET = 0x001272e0
S_AFXDEL = 0x00127368
S_TLIST_DTOR = 0x00124bf0
S_HASSIGN = 0x001c2fe8
S_GETROUTE = 0x001332a8
S_GETPOINT = 0x001332d8
S_GUESS = 0x001cbb70
S_NEXT = 0x001cb960
S_ZVAL = 0x001ebad8
S_NEAREST = 0x001cb7a0
S_CLOSEST = 0x001c1b48
S_GETSIGN = 0x001c14f8
S_NEWROUTE = 0x001c0ff8
S_SNDNEW = 0x00215098

CHOPPER_SIZE = 976
CAR_SIZE = 2304
WORLD_SIZE = 5936
NCARS, NROUTES, NPOINTS, PER_ROUTE = 3, 4, 24, 6
SND_DELTA = 8

NO_HELISHEET = 0x4000


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def bitsf(u):
    return struct.unpack("<f", struct.pack("<I", u & M32))[0]


def fx(f):
    return "%08x" % fbits(f)


# ================================================================ the model

class Model:
    def __init__(self):
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True,
                                            eesqrt=True)
        self.lines = []
        self.names = {}
        self.H = None
        self.cars = [self.block(CAR_SIZE, "C%d" % i) for i in range(NCARS)]
        self.world = self.block(WORLD_SIZE, "WORLD")
        e.put32(self.world + 44, self.cars[0])
        e.put32(G_WORLD, self.world)
        self.routes = [self.block(64, "R%d" % i) for i in range(NROUTES)]
        self.points = [self.block(112, "P%d" % i) for i in range(NPOINTS)]
        self.signs = [self.block(16, "S%d" % i) for i in range(NPOINTS)]
        self.sheet = self.block(536, "SHEET")
        self.wo = self.block(96, "WO")
        self.snd = self.block(32, "SND")
        self.pool = self.block(16, "WOP")
        e.put32(G_WOP, self.pool)
        self.names[TPM] = "TPM"
        self.eggs = self.block(400, None)
        e.put32(EGGS, self.eggs)
        for a in (RP + 24, RP + 28):
            e.put32(a, 0)
        e.put32(G_SHEET, 0)
        self.sound_on = 1
        self.q = dict(signs=1, elev=0.0, terrain=0, cmp=0.0, guess=[],
                      near=0, near_info=(0, 0), newroute=0)
        self.car_route = [(0, 0)] * NCARS
        self.zhit = [0] * NPOINTS
        self.zflags = [0] * NPOINTS
        self.closest = [0] * NROUTES
        self.loud = self.table(True)
        self.silent_vt = self.table(False)
        self.silent = self.block(32, None)
        e.put32(self.silent + 28, self.silent_vt)
        self.install()

    def block(self, size, name):
        a = self.e.alloc(size, 16)
        self.e.write(a, bytes(size))
        if name:
            self.names[a] = name
        return a

    # The sound's table: five entries of {delta, index, fn}, the fns stub
    # addresses of the checker's own. The silent one logs nothing.
    def table(self, loud):
        e = self.e
        vt = self.block(40, None)
        kinds = ("dtor", "activate", "update", "mute")
        for i, k in enumerate(kinds):
            fn = self.block(16, None)
            e.write(vt + 8 * (i + 1), struct.pack("<hhI", SND_DELTA, 0, fn))
            e.stub(fn, self.snd_stub(k) if loud else (lambda e_: None))
        return vt

    def snd_stub(self, kind):
        def fn(e):
            this = "SND%+d" % (s32(e.reg[4]) - self.snd)
            if kind == "update":
                self.log("snd_update %s %s %u %s" % (
                    this, fx(e.f(12)), e.reg[5] & 0xffff, fx(e.f(13))))
            else:
                self.log("snd_%s %s %d" % (kind, this, s32(e.reg[5])))
        return fn

    def log(self, s):
        self.lines.append("  " + s)

    def name(self, a):
        a &= M32
        if a == 0:
            return "NULL"
        if self.H is not None:
            rel = {0: "H", 8: "H.topo", 712: "H.dust", 752: "H.tp",
                   832: "H.pos"}
            if a - self.H in rel:
                return rel[a - self.H]
        return self.names.get(a, "?")

    def addr(self, n):
        if n == "NULL":
            return 0
        i = int(n[1:])
        return {"C": self.cars, "R": self.routes, "P": self.points}[n[0]][i]

    def pidx(self, a):
        return self.points.index(a & M32)

    def f32(self, a):
        return bitsf(self.e.u32(a))

    # ---- the stubs --------------------------------------------------------

    def install(self):
        e = self.e
        r = e.reg
        L = self.log
        n = self.name

        def topo_ctor(e):
            L("topo_init %s" % n(r[4]))

        def topo_dtor(e):
            L("topo_dtor %s" % n(r[4]))

        def bbox(e):
            p = r[5] & M32
            L("topo_bbox %s %s %s %s %s %s" % (
                n(r[4]), n(p), fx(self.f32(p)), fx(self.f32(p + 4)),
                fx(e.f(12)), n(r[6])))

        def clearbb(e):
            L("topo_clear %s" % n(r[4]))

        def elev(e):
            p = r[5] & M32
            L("topo_elev %s %s %s %s %s %s %s" % (
                n(r[4]), fx(self.f32(p)), fx(self.f32(p + 4)),
                fx(self.f32(p + 8)), "T" if r[6] & M32 else "NULL",
                n(r[7]), n(r[8])))
            if r[6] & M32:
                e.put32(r[6] & M32, self.q["terrain"])
            e.set_f(0, self.q["elev"])

        def tp_ctor(e):
            a = r[4] & M32
            L("tp_init %s" % n(a))
            e.write(a, bytes(40))
            e.put32(a + 24, fbits(1.0))
            return a

        def tp_reset(e):
            a, p = r[4] & M32, r[5] & M32
            L("tp_reset %s %s %s %s" % (n(a), n(p), fx(self.f32(p)),
                                        fx(self.f32(p + 4))))
            e.put32(a + 8, 0)

        def cmp(e):
            L("tp_cmp %s %s %s" % (n(r[4]), fx(e.f(12)), fx(e.f(13))))
            e.set_f(0, self.q["cmp"])

        def omalloc(e):
            L("omalloc %s" % n(r[4]))
            e.write(self.wo, b"\xcd" * 96)
            return self.wo

        def delete(e):
            L("free %s" % n(r[4]))

        def woctor(e):
            L("wo_ctor %s %08x %s %d" % (n(r[4]), r[5] & M32, n(r[6]),
                                         s32(r[7])))
            return r[4] & M32

        def wodtor(e):
            L("wo_dtor %s %d" % (n(r[4]), s32(r[5])))

        def afxget(e):
            L("afx_get %s %08x" % (n(r[4]), r[5] & M32))

        def afxdel(e):
            L("afx_del %s" % n(r[4]))

        def hassign(e):
            L("has_signposts")
            return self.q["signs"]

        def getroute(e):
            c = self.cars.index(r[4] & M32)
            L("get_route %s %d" % (n(r[4]), s32(r[5])))
            return self.car_route[c][0]

        def getpoint(e):
            c = self.cars.index(r[4] & M32)
            L("get_point %s %d" % (n(r[4]), s32(r[5])))
            return self.car_route[c][1]

        def guess(e):
            out = r[4] & M32
            L("guess %u %s %s %s %d" % (r[5] & M32, n(r[6]), n(r[7]),
                                        fx(e.f(12)), s32(r[8])))
            for i, (ro, po) in enumerate(self.q["guess"]):
                e.put32(out + 8 * i, ro)
                e.put32(out + 8 * i + 4, po)
            return len(self.q["guess"])

        def nxt(e):
            info = r[4] & M32
            ro, po = e.u32(info), e.u32(info + 4)
            L("next %s %s" % (n(ro), n(po)))
            i = self.pidx(po) + 1
            e.put32(info, self.routes[i // PER_ROUTE])
            e.put32(info + 4, self.points[i])

        def zval(e):
            i = self.pidx(r[5])
            L("zval %s %s %s %s" % (n(r[4]), n(r[5]), n(r[6]),
                                    "F" if r[7] & M32 else "NULL"))
            if not self.zhit[i]:
                return 0
            if r[6] & M32:
                e.put32(r[6] & M32, fbits(1.0))
            if r[7] & M32:
                e.put32(r[7] & M32, self.zflags[i])
            return 1

        def nearest(e):
            p = r[5] & M32
            L("nearest %s %s %s %d %d %s" % (
                n(p), fx(self.f32(p)), fx(self.f32(p + 4)), s32(r[6]),
                s32(r[7]), fx(e.f(12))))
            if not self.q["near"]:
                return 0
            ro, po = self.q["near_info"]
            e.put32(r[4] & M32, ro)
            e.put32((r[4] & M32) + 4, po)
            return 1

        def closest(e):
            i = self.routes.index(r[4] & M32)
            L("closest %s %s %s %d %s" % (n(r[4]), n(r[5]), fx(e.f(12)),
                                          s32(r[6]), fx(e.f(13))))
            return self.closest[i]

        def getsign(e):
            L("get_sign %s" % n(r[4]))
            return self.signs[self.pidx(r[4])]

        def newroute(e):
            L("new_route %s" % n(r[4]))
            return self.q["newroute"]

        def sndnew(e):
            if not self.sound_on:
                return 0
            L("snd_new %s" % n(r[4]))
            e.write(self.snd, bytes(32))
            e.put32(self.snd + 28, self.loud)
            return self.snd

        def nothing(e):
            return None

        # The flags word FindZValue writes: 0 to start with, as the port's.
        def spot_entry(e):
            e.put32((r[29] - 80 + 16) & M32, 0)

        for a, f in ((S_TOPO_CTOR, topo_ctor), (S_TOPO_DTOR, topo_dtor),
                     (S_BBOX, bbox), (S_CLEARBB, clearbb), (S_ELEV, elev),
                     (S_TP_CTOR, tp_ctor), (S_TP_RESET, tp_reset),
                     (S_CMP, cmp), (S_OMALLOC, omalloc), (S_DELETE, delete),
                     (S_WOCTOR, woctor), (S_WODTOR, wodtor),
                     (S_AFXGET, afxget), (S_AFXDEL, afxdel),
                     (S_TLIST_DTOR, nothing), (S_HASSIGN, hassign),
                     (S_GETROUTE, getroute), (S_GETPOINT, getpoint),
                     (S_GUESS, guess), (S_NEXT, nxt), (S_ZVAL, zval),
                     (S_NEAREST, nearest), (S_CLOSEST, closest),
                     (S_GETSIGN, getsign), (S_NEWROUTE, newroute),
                     (S_SNDNEW, sndnew)):
            e.stub(a, f)
        e.hook(F_SPOT, spot_entry)

    # ---- the dump ---------------------------------------------------------

    def dump(self):
        e, h, n = self.e, self.H, self.name
        u = lambda o: e.u32(h + o)                     # noqa: E731
        i = lambda o: s32(e.u32(h + o))                # noqa: E731
        x = lambda o: "%08x" % e.u32(h + o)            # noqa: E731
        out = self.lines
        out.append("dump plan %d mm %d think %s car %s" % (
            i(728), i(732), x(720), n(u(724))))
        out.append("  route %s %s target %s %s old %s %s td %s" % (
            n(u(736)), n(u(740)), n(u(744)), n(u(748)), n(u(796)),
            n(u(800)), x(792)))
        out.append("  bomb %d %d %s %d timeout %s stuck %s total %d" % (
            i(804), i(808), x(812), i(816), x(820), x(824), i(828)))
        out.append("  pos %s %s %s %s" % (x(832), x(836), x(840), x(844)))
        out.append("  mat " + " ".join(x(848 + 4 * k) for k in range(16)))
        out.append("  speed %s acc %s %s roll %s %s yaw %s pitch %s %s" % (
            x(912), x(916), x(920), x(924), x(928), x(932), x(936),
            x(940)))
        out.append("  rot %s zv %s gz %s dust %d n960 %d" % (
            x(944), x(948), x(952), i(956), i(960)))
        out.append("  tp %s %s %s %s %s %s %s %s %s %s" % (
            x(752), x(756), n(u(760)), x(764), x(768), x(772), x(776),
            x(780), n(u(784)), x(788)))
        out.append("  snd %s wo %s dust %s %s pad %s" % (
            n(u(0)), n(u(4)), n(u(712)), n(u(716)),
            " ".join("%02x" % b for b in e.read(h + 964, 12))))

    # ---- the ops ----------------------------------------------------------

    def with_sound(self, fn):
        """Retail calls the sound unguarded; with none, the port skips the
        call, which the model shares by lending it a silent one."""
        e, h = self.e, self.H
        if e.u32(h) != 0:
            return fn()
        e.put32(h, self.silent)
        try:
            return fn()
        finally:
            e.put32(h, 0)

    def run(self, t):
        e = self.e
        op = t[0]
        self.lines.append(op)
        if op == "q":
            self.answer(t)
            return
        if op == "car":
            c = self.cars[int(t[1])]
            for k, o in enumerate((96, 100, 104)):
                e.put32(c + o, int(t[2 + k], 16))
            struct.pack_into("<H", e.mem, c + 932, int(t[5]))
            e.put32(c + 964, int(t[6], 16))
            e.put32(c + 2036, int(t[7], 16))
            return
        if op == "point":
            p = self.points[int(t[1])]
            e.put32(p, int(t[2], 16))
            e.put32(p + 4, int(t[3], 16))
            e.put32(p + 20, int(t[4], 16))
            e.put32(p + 44, int(t[5], 16))
            return
        h = self.H
        if op == "new":
            h = self.H = e.alloc(CHOPPER_SIZE, 16)
            e.write(h, b"\xcd" * CHOPPER_SIZE)
            self.log("ret %s" % self.name(e.call(F_CTOR, h)))
        elif op == "del":
            e.call(F_DTOR, h, int(t[1]))
            return
        elif op == "clear":
            e.call(F_CLEAR, h)
        elif op == "follow":
            self.log("ret %d" % e.call(F_FOLLOW, h, self.addr(t[1])))
        elif op == "attack":
            self.log("ret %d" % e.call(F_ATTACK, h, int(t[1])))
        elif op == "adjust":
            e.call(F_ADJUST, h)
        elif op == "shift":
            e.set_f(12, bitsf(int(t[1], 16)))
            e.call(F_SHIFT, h)
        elif op == "spot":
            e.call(F_SPOT, h)
        elif op == "ground":
            self.log("ret %d" % e.call(F_GROUND, h))
        elif op == "place":
            v = self.vec(t[1], t[2])
            e.set_f(12, bitsf(int(t[3], 16)))
            self.with_sound(lambda: e.call(F_PLACE, h, v))
        elif op == "remove":
            self.with_sound(lambda: e.call(F_REMOVE, h))
            self.log("wo %d" % s32(e.u32(self.wo + 12)))
        elif op == "behind":
            self.log("ret %d" % e.call(F_BEHIND, h))
        elif op == "rotate":
            v = self.vec(t[1], t[2])
            o = self.vec("0", "0")
            e.call(F_ROTATE, h, o, v)
            self.log("out %08x %08x" % (e.u32(o), e.u32(o + 4)))
            e.call(F_ROTATE, h, v, v)
            self.log("same %08x %08x" % (e.u32(v), e.u32(v + 4)))
        elif op == "maxdecel":
            e.call(F_DECEL, h)
            self.log("ret %s" % fx(e.f(0)))
        elif op == "abort":
            e.call(F_ABORT, h)
        elif op == "mute":
            self.with_sound(lambda: e.call(F_MUTE, h, int(t[1])))
        elif op == "usound":
            self.with_sound(lambda: e.call(F_USOUND, h))
        elif op == "scratch":
            e.call(F_SCRATCH, h)
        elif op == "routepoint":
            e.call(F_ROUTEPT, h)
        elif op == "matrix":
            e.call(F_MATRIX, h)
        elif op == "wobj":
            e.call(F_WOBJ, h)
            self.log("wo %d " % s32(e.u32(self.wo + 12)) + " ".join(
                "%08x" % e.u32(self.wo + 32 + 4 * k) for k in range(16)))
        elif op == "set":
            self.set_field(t)
        else:
            raise SystemExit("no op %s" % op)
        self.dump()

    def vec(self, xs, ys):
        v = self.e.alloc(16, 16)
        self.e.put32(v, int(xs, 16))
        self.e.put32(v + 4, int(ys, 16))
        return v

    def set_field(self, t):
        e, h = self.e, self.H
        f = t[1]
        word = {"plan": 728, "n960": 960, "bomb": 804, "mm": 732,
                "salvos": 808, "launcher": 816, "total": 828, "dust": 956}
        flt = {"yaw": 932, "roll": 924, "pitch": 936, "gz": 952,
               "td": 792, "tpd": 772, "think": 720, "nsalvo": 812,
               "timeout": 820, "stuck": 824, "speed": 912, "droll": 928,
               "dpitch": 940, "rot": 944, "zv": 948}
        if f in word:
            e.put32(h + word[f], int(t[2]))
        elif f in flt:
            e.put32(h + flt[f], int(t[2], 16))
        elif f == "acc":
            e.put32(h + 916, int(t[2], 16))
            e.put32(h + 920, int(t[3], 16))
        elif f == "car":
            e.put32(h + 724, self.addr(t[2]))
        elif f == "pos":
            for k in range(3):
                e.put32(h + 832 + 4 * k, int(t[2 + k], 16))
        elif f == "chop":
            e.put32(h + 736, self.addr(t[2]))
            e.put32(h + 740, self.addr(t[3]))
        elif f == "target":
            e.put32(h + 744, self.addr(t[2]))
            e.put32(h + 748, self.addr(t[3]))
        else:
            raise SystemExit("no field %s" % f)

    def answer(self, t):
        e, q = self.e, self.q
        k = t[1]
        if k == "egg":
            e.put32(self.eggs + 328, int(t[2]))
        elif k == "demo":
            e.put32(RP + 24, int(t[2]))
            e.put32(RP + 28, int(t[3]))
        elif k == "sheet":
            e.put32(G_SHEET, self.sheet if int(t[2]) else 0)
        elif k == "signs":
            q["signs"] = int(t[2])
        elif k == "elev":
            q["elev"] = bitsf(int(t[2], 16))
            q["terrain"] = int(t[3])
        elif k == "cmp":
            q["cmp"] = bitsf(int(t[2], 16))
        elif k == "carroute":
            self.car_route[int(t[2])] = (self.addr(t[3]), self.addr(t[4]))
        elif k == "guess":
            q["guess"] = [(self.addr(t[i]), self.addr(t[i + 1]))
                          for i in range(2, len(t) - 1, 2)]
        elif k == "zval":
            self.zhit[int(t[2])] = int(t[3])
            self.zflags[int(t[2])] = int(t[4], 16)
        elif k == "near":
            q["near"] = int(t[2])
            q["near_info"] = (self.addr(t[3]), self.addr(t[4]))
        elif k == "closest":
            self.closest[int(t[2])] = self.addr(t[3])
        elif k == "newroute":
            q["newroute"] = self.addr(t[2])
        elif k == "sound":
            self.sound_on = int(t[2])
        else:
            raise SystemExit("no answer %s" % k)


def model(lines):
    m = Model()
    for ln in lines:
        m.run(ln.split("|"))
    return m.lines


# ================================================================ the script

def F(v):
    return fx(v)


def setup():
    """The cars, the routes' points, and default answers."""
    out = []
    for i in range(NCARS):
        out.append("car|%d|%s|%s|%s|%d|%s|%s" % (
            i, F(100.0 * i + 3.5), F(-40.0 * i + 7.25), F(12.0 + i),
            [0, 16384, 50000][i], F([30.0, 55.5, 0.0][i]),
            F(1000.0 + 37.5 * i)))
    for i in range(NPOINTS):
        bits = 0xff | (0x3f << 8) | (0x3f << 22) | 0x8000
        if i % 5 == 2:
            bits |= NO_HELISHEET
        if i % 7 == 3:
            bits &= ~0xff
            bits |= i
        out.append("point|%d|%s|%s|%s|%08x" % (
            i, F(10.0 * i - 50.0), F(3.0 * i + 1.0), F(8.0 + i * 0.75),
            bits))
    out += ["q|carroute|%d|R%d|P%d" % (i, i, PER_ROUTE * i + 1)
            for i in range(NCARS)]
    out += ["q|elev|%s|3" % F(4.5), "q|cmp|%s" % F(-12.0),
            "q|near|1|R2|P13", "q|newroute|R3", "q|sheet|1", "q|signs|1"]
    for i in range(NPOINTS):
        out.append("q|zval|%d|1|%x" % (i, 0 if i % 4 else 2))
    return out


def life():
    out = []
    for egg in (0, 1):
        for ai in (0, 1, 7):
            for rep in (0, 1, -1):
                out += ["q|egg|%d" % egg, "q|demo|%d|%d" % (ai, rep), "new",
                        "del|%d" % (3 if (ai + rep) % 2 else 2)]
    out += ["q|egg|1", "q|demo|0|0", "q|sound|0", "new", "set|car|C0", "place|%s|%s|%s"
            % (F(1.0), F(2.0), F(3.0)), "mute|1", "usound", "remove",
            "del|1", "q|sound|1", "q|egg|0"]
    # ClearVariables over a scrambled helicopter.
    out += ["new", "set|plan|2", "set|car|C2", "set|n960|1",
            "set|pos|%s|%s|%s" % (F(5.0), F(-6.0), F(7.0)),
            "set|yaw|%s" % F(33.0), "set|roll|%s" % F(-4.0),
            "set|pitch|%s" % F(9.0), "set|gz|%s" % F(3.0),
            "set|td|%s" % F(40.0), "set|bomb|3", "set|chop|R1|P7",
            "set|target|R2|P14", "set|tpd|%s" % F(88.0), "attack|1",
            "set|mm|1", "set|salvos|5", "set|launcher|2", "set|total|9",
            "set|dust|1", "set|think|%s" % F(0.75),
            "set|nsalvo|%s" % F(1.25), "set|timeout|%s" % F(3.0),
            "set|stuck|%s" % F(0.5), "set|speed|%s" % F(41.0),
            "set|acc|%s|%s" % (F(-2.0), F(6.5)), "set|droll|%s" % F(11.0),
            "set|dpitch|%s" % F(-7.0), "set|rot|%s" % F(0.25),
            "set|zv|%s" % F(-1.5), "clear", "del|3"]
    return out


def follows():
    out = ["new"]
    for n960 in (0, 1):
        for sheet in (0, 1):
            for signs in (0, 1):
                for car in ("NULL", "C1", "C0"):
                    for plan in range(-1, 8):
                        out += ["q|sheet|%d" % sheet, "q|signs|%d" % signs,
                                "set|plan|%d" % plan, "set|car|C2",
                                "set|n960|%d" % n960, "follow|%s" % car]
    out += ["q|sheet|1", "q|signs|1", "set|n960|0", "del|3"]
    return out


def attacks(rng):
    out = ["new", "set|chop|R1|P8", "set|pos|%s|%s|%s" % (
        F(20.0), F(-15.0), F(30.0))]
    # Every plan, with and without a car.
    for plan in range(-1, 8):
        for car in ("NULL", "C1"):
            if plan == 0 and car == "NULL":
                continue                # retail reads through it
            out += ["set|plan|%d" % plan, "set|car|%s" % car,
                    "set|n960|0", "attack|2"]
    # The run itself: each type, speed and distance.
    guesses = ["q|guess",
               "q|guess|R0|P2",
               "q|guess|R0|P2|R0|P3",
               "q|guess|R1|P7|R1|P12|R2|P13",
               "q|guess|R0|P2|R1|P7|R1|P12|R2|P17|R3|P22",
               "q|guess|R0|P2|R1|P7|R1|P12|R2|P17|R3|P19"]
    k = 0
    for typ in range(5):
        for vel in (0.0, 20.0, 49.0, 50.0, 70.0, 101.5, float("nan")):
            for cmpv in (-1.0, 0.0, 3.0, float("nan")):
                k += 1
                cpx = rng.choice((10.0, 120.0, -300.0, 3.5))
                out += ["car|1|%s|%s|%s|%d|%s|%s" % (
                    F(cpx), F(rng.uniform(-200, 200)), F(5.0),
                    rng.randrange(65536), F(vel), F(500.0)),
                    "q|cmp|%s" % F(cmpv), guesses[k % len(guesses)],
                    "set|plan|0", "set|car|C1", "attack|%d" % typ]
    # AdjustBombTarget's edge: TargetDistance + 24 against the lead.
    out += ["car|1|%s|%s|%s|0|%s|%s" % (F(0.0), F(0.0), F(0.0), F(60.0),
                                         F(0.0)), guesses[3]]
    for typ in (0, 2, 4):
        ahead = [2.0, 2.0, 1.5, 2.0, 1.0][typ] * 60.0
        lead = max(ahead, 100.0)
        for td in (lead - 24.0, lead - 24.0001, lead - 23.9999, -500.0,
                   float("nan"), lead):
            out += ["set|bomb|%d" % typ, "set|td|%s" % F(td), "adjust"]
    out.append("del|3")
    return out


def shifts():
    out = ["new", "set|car|C2", "set|target|R3|P20"]
    for g in ("q|guess",
              "q|guess|R0|P2",
              "q|guess|R0|P2|R0|P7",
              "q|guess|R0|P7|R0|P2",
              "q|guess|R0|P2|R1|P12|R2|P17|R3|P22|R3|P23",
              "q|guess|R0|P2|R1|P12|R2|P17|R3|P22|R3|P2",
              "q|guess|R0|P3|R2|P13|R3|P19",
              "q|guess|R0|P2|R2|P13|R3|P19|R3|P20"):
        for d in (0.0, 150.0, -3.0):
            out += [g, "shift|%s" % F(d)]
    out.append("del|3")
    return out


def spots():
    """Runs of covered polygons to walk over, misses included."""
    out = ["new"]
    cases = [
        (0, []),                              # a first-try miss
        (0, [(0, 1, 0)]),                     # a hit, open ground
        (0, [(0, 1, 1), (1, 1, 0)]),
        (0, [(0, 1, 3), (1, 1, 1), (2, 1, 2), (3, 1, 0xfe)]),
        (4, [(4, 1, 1), (5, 0, 0), (6, 1, 0)]),   # a miss after a hit
        (7, [(7, 1, 0xff), (8, 0, 0), (9, 0, 0), (10, 1, 0x10)]),
        (12, [(12, 1, 5), (13, 1, 7), (14, 1, 9), (15, 1, 4)]),
        (18, [(18, 0, 0), (19, 0, 0)]),       # a first-try miss again
    ]
    for start, run in cases:
        out += ["q|zval|%d|0|0" % i for i in range(NPOINTS)]
        for i, hit, fl in run:
            out.append("q|zval|%d|%d|%x" % (i, hit, fl))
        out += ["set|target|R%d|P%d" % (start // PER_ROUTE, start),
                "set|td|%s" % F(17.5), "spot"]
    out += ["q|zval|%d|1|0" % i for i in range(NPOINTS)]
    # AttackCar through to the walk.
    out += ["q|zval|13|1|1", "q|zval|14|1|1", "q|guess|R2|P12|R2|P13",
            "set|chop|R0|P1",
            "car|2|%s|%s|%s|0|%s|%s" % (F(0.0), F(0.0), F(0.0), F(90.0),
                                         F(0.0)),
            "set|plan|0", "set|car|C2", "set|td|%s" % F(0.0), "attack|1"]
    out += ["q|zval|13|1|0", "q|zval|14|1|2", "del|3"]
    return out


def world_ops(rng):
    out = ["new", "set|car|C1"]
    for z, ter in ((4.5, 3), (-2.25, 0), (float("inf"), 7), (0.0, -1)):
        out += ["q|elev|%s|%d" % (F(z), ter), "set|gz|%s" % F(z * 2 + 1),
                "set|pos|%s|%s|%s" % (F(z), F(-z), F(9.0)), "ground"]
    for ang in (0, 1, 182, 16384, 32767, 32768, 49152, 65535):
        for near in (0, 1):
            out += ["car|1|%s|%s|%s|%d|%s|%s" % (
                F(rng.uniform(-500, 500)), F(rng.uniform(-500, 500)),
                F(rng.uniform(-10, 40)), ang, F(33.0), F(10.0)),
                "q|near|%d|R%d|P%d" % (near, ang % 4, ang % 24),
                "q|elev|%s|%d" % (F(rng.uniform(-5, 50)), ang % 9),
                "set|roll|%s" % F(rng.uniform(-30, 30)),
                "set|pitch|%s" % F(rng.uniform(-30, 30)),
                "set|droll|%s" % F(rng.uniform(-30, 30)),
                "set|dpitch|%s" % F(rng.uniform(-30, 30)),
                "set|speed|%s" % F(rng.uniform(0, 90)),
                "place|%s|%s|%s" % (F(rng.uniform(-900, 900)),
                                    F(rng.uniform(-900, 900)),
                                    F(rng.uniform(0, 80))),
                "wobj", "remove"]
    for c in (-1.0, 0.0, -0.0, 1e-30, -1e-30, 5.0, float("nan"),
              float("-inf")):
        out += ["q|cmp|%s" % F(c), "set|tpd|%s" % F(c * 3 + 1),
                "behind"]
    for plan in range(-1, 8):
        out += ["set|plan|%d" % plan, "maxdecel", "abort"]
    for i in (0, 1, -1, 7):
        out += ["mute|%d" % i]
    out += ["usound"]
    out.append("del|3")
    return out


def routes():
    out = ["new"]
    for near in (0, 1):
        out += ["q|near|%d|R1|P9" % near, "set|chop|R0|P0",
                "set|pos|%s|%s|%s" % (F(1.5), F(2.5), F(3.5)), "scratch"]
    # The chopper's point: P3 has a signpost, P4 none.
    for cp in ("P3", "P4", "P10"):
        for first in ("NULL", "P5"):
            for second in ("NULL", "P20"):
                for near in (0, 1):
                    out += ["q|closest|0|%s" % first,
                            "q|closest|1|%s" % first,
                            "q|closest|3|%s" % second,
                            "q|newroute|R3",
                            "q|near|%d|R2|P15" % near,
                            "set|chop|R%d|%s" % (int(cp[1:]) // PER_ROUTE,
                                                 cp),
                            "routepoint"]
    out.append("del|3")
    return out


def matrices(rng):
    out = ["new"]
    angles = [0.0, 1.0, -1.0, 90.0, 179.99, 180.0, 180.01, 270.0, 359.9,
              360.0, 361.0, -720.5, 1e6, -1e6, 32767.0, 0.0001,
              # 180 - Yaw is 359/65536, whose sum with 360 rounds up to a
              # whole BAM: the one place where `< 0` is not `< 1`.
              180.0 - 359.0 / 65536.0]
    for k in range(60):
        out += ["set|roll|%s" % F(rng.choice(angles + [rng.uniform(-400,
                                                                    400)])),
                "set|pitch|%s" % F(rng.choice(angles + [rng.uniform(-400,
                                                                     400)])),
                "set|yaw|%s" % F(rng.choice(angles + [rng.uniform(-400,
                                                                   400)])),
                "set|pos|%s|%s|%s" % (F(rng.uniform(-3000, 3000)),
                                      F(rng.uniform(-3000, 3000)),
                                      F(rng.uniform(-50, 200))),
                "matrix"]
        if k % 10 == 0:
            out.append("wobj")
    for yaw in angles + [45.0, -45.0, 123.456]:
        for v in ((1.0, 0.0), (0.0, 1.0), (-3.5, 7.25), (1e-3, -2e4)):
            out += ["set|yaw|%s" % F(yaw), "rotate|%s|%s" % (F(v[0]),
                                                              F(v[1]))]
    out.append("del|0")
    return out


def script():
    rng = random.Random(0xc40)
    return (setup() + life() + follows() + attacks(rng) + shifts()
            + spots() + world_ops(rng) + routes() + matrices(rng))


# ================================================================= running

def build_harness(tmp, name="chopper_test"):
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

C = CHOP
CH = "3DS Files/source/chopper.h"
U = COPUTIL
MUTATIONS = [
    # ---- the constructor
    ("ctor_topo", C, "    topology_init(&h->TopologyCoord);\n", ""),
    ("ctor_dust_next", C, "h->DustEmitters.next = &h->DustEmitters;",
     "h->DustEmitters.next = NULL;"),
    ("ctor_dust_prev", C, "h->DustEmitters.prev = &h->DustEmitters;",
     "h->DustEmitters.prev = NULL;"),
    ("ctor_tp", C, "    trackpath_coord_init(&h->TP);\n", ""),
    ("ctor_wo_name", C, '"TRACK_HELICOPTER"', '"TRACK_HELICOPTERS"'),
    ("ctor_wo_matrix", C, "bchunk_hash(\"TRACK_HELICOPTER\"),\n"
     "                                        NULL, 1);",
     "bchunk_hash(\"TRACK_HELICOPTER\"),\n"
     "                                        &h->Matrix, 1);"),
    ("ctor_wo_light", C, "                                        NULL, 1);",
     "                                        NULL, 0);"),
    ("ctor_wo_store", C, "h->WorldObj = worldobject_construct(wo,",
     "h->WorldObj = wo; (void)worldobject_construct(wo + 1,"),
    ("ctor_sound", C, "? gCreateChopperSoundFn(h) : NULL;", "? NULL : NULL;"),
    ("ctor_dust_hash", C, '"XEM_HELI_DUST"', '"XEM_HELI_DUSTS"'),
    ("ctor_clear", C, "    chopper_clear_variables(h);\n    h->Plan", "    h->Plan"),
    ("ctor_plan", C, "h->Plan = CHOPPLAN_EATING_DONUTS;\n    if (TheRace",
     "h->Plan = CHOPPLAN_END_CHASE;\n    if (TheRace"),
    ("ctor_aidemo", C, "if (TheRaceParameters.AIDemoMode == 0\n        && ",
     "if ("),
    ("ctor_replay", C, "        && TheRaceParameters.ReplayDemoMode == 0\n", ""),
    ("ctor_egg_num", C, "gEggIsOnFn(EGG_HELICOPTER)",
     "gEggIsOnFn(EGG_HELICOPTER + 1)"),
    ("ctor_egg_test", C, "gEggIsOnFn(EGG_HELICOPTER) != 0)",
     "gEggIsOnFn(EGG_HELICOPTER) == 0)"),
    ("ctor_n960", C, "        h->New960 = 1;\n    return h;",
     "        h->New960 = 2;\n    return h;"),
    # ---- the destructor
    ("dtor_afx", C, "    afx_delete_emitters(&h->DustEmitters);\n", ""),
    ("dtor_snd_slot", C, "sound_slot(h, CHOPPERSOUND_VT_DTOR)",
     "sound_slot(h, CHOPPERSOUND_VT_MUTE)"),
    ("dtor_snd_flags", C, "vt_this(h->pChopperSound, e), 3);",
     "vt_this(h->pChopperSound, e), 1);"),
    ("dtor_wo_flags", C, "worldobject_destruct(h->WorldObj, 3);",
     "worldobject_destruct(h->WorldObj, 1);"),
    ("dtor_topo", C, "    topology_destroy(&h->TopologyCoord);\n", ""),
    ("dtor_free", C, "if (flags & 1)\n        bFree(h);",
     "if (flags & 2)\n        bFree(h);"),
    # ---- ClearVariables
    ("clr_think", C, "    h->TimeUntilThink = 0.0f;\n    h->CurrentPos.x",
     "    h->CurrentPos.x"),
    ("clr_posx", C, "    h->CurrentPos.x = 0.0f;\n", ""),
    ("clr_car", C, "    h->CurrentCar = NULL;\n    h->MoveMode",
     "    h->MoveMode"),
    ("clr_mm", C, "h->MoveMode = CHOPMOVE_PURSUIT;",
     "h->MoveMode = CHOPMOVE_ROTATE;"),
    ("clr_tr", C, "    h->TargetRoute = NULL;\n    h->TargetPoint = NULL;\n",
     "    h->TargetPoint = NULL;\n"),
    ("clr_tp", C, "    h->TargetPoint = NULL;\n    h->ChopperRoute = NULL;\n",
     "    h->ChopperRoute = NULL;\n"),
    ("clr_cr", C, "    h->ChopperRoute = NULL;\n    h->ChopperPoint = NULL;\n",
     "    h->ChopperPoint = NULL;\n"),
    ("clr_cp", C, "    h->ChopperPoint = NULL;\n    h->OldCarRoute = NULL;\n",
     "    h->OldCarRoute = NULL;\n"),
    ("clr_or", C, "    h->OldCarRoute = NULL;\n", ""),
    ("clr_op", C, "    h->OldCarPoint = NULL;\n", ""),
    ("clr_posy", C, "    h->CurrentPos.y = 0.0f;\n", ""),
    ("clr_posz", C, "    h->CurrentPos.z = 0.0f;\n", ""),
    ("clr_ident", C, "    bIdentity(&h->Matrix);\n", ""),
    ("clr_tp_reset", C, "    trackpath_coord_reset_position(&h->TP, (const "
     "bVector2 *)&h->CurrentPos);\n    h->New960", "    h->New960"),
    ("clr_n960", C, "    h->New960 = 0;\n", ""),
    ("clr_timeout", C, "    h->Timeout = CHOPPER_TIMEOUT;\n    h->Speed",
     "    h->Speed"),
    ("clr_timeout_val", CH, "#define CHOPPER_TIMEOUT 25.0f",
     "#define CHOPPER_TIMEOUT 25.5f"),
    ("clr_speed", C, "    h->Speed = 0.0f;\n    h->Acceleration.x",
     "    h->Acceleration.x"),
    ("clr_accx", C, "    h->Acceleration.x = 0.0f;\n", ""),
    ("clr_accy", C, "    h->Acceleration.y = 0.0f;\n", ""),
    ("clr_roll", C, "    h->Roll = 0.0f;\n    h->DesiredRoll = 0.0f;\n"
     "    h->Yaw", "    h->DesiredRoll = 0.0f;\n    h->Yaw"),
    ("clr_droll", C, "    h->DesiredRoll = 0.0f;\n    h->Yaw", "    h->Yaw"),
    ("clr_yaw", C, "    h->Yaw = 0.0f;\n", ""),
    ("clr_pitch", C, "    h->Pitch = 0.0f;\n    h->DesiredPitch = 0.0f;\n"
     "    h->RotRate", "    h->DesiredPitch = 0.0f;\n    h->RotRate"),
    ("clr_dpitch", C, "    h->DesiredPitch = 0.0f;\n    h->RotRate",
     "    h->RotRate"),
    ("clr_rot", C, "    h->RotRate = 0.0f;\n", ""),
    ("clr_zv", C, "    h->ZVelocity = 0.0f;\n", ""),
    ("clr_gz", C, "    h->GroundZ = 0.0f;\n", ""),
    ("clr_dust", C, "    h->EmitDust = 0;\n", ""),
    ("clr_td", C, "    h->TargetDistance = 0.0f;\n", ""),
    ("clr_bomb", C, "h->BombRunType = CHOPATTACK_ROCKET;",
     "h->BombRunType = CHOPATTACK_SMOKE_BOMB_1;"),
    ("clr_salvos", C, "    h->NumSalvosReleased = 0;\n    h->NextLauncher",
     "    h->NextLauncher"),
    ("clr_launcher", C, "    h->NextLauncher = 0;\n", ""),
    ("clr_nsalvo", C, "    h->TimeUntilNextSalvo = 0.0f;\n    h->TotalSalvos",
     "    h->TotalSalvos"),
    ("clr_total", C, "    h->TotalSalvos = 0;\n", ""),
    ("clr_stuck", C, "    h->StuckTime = 0.0f;\n", ""),
    # ---- FollowThisCar
    ("fol_n960", C, "if (h->New960 != 0)", "if (h->New960 == 0)"),
    ("fol_table", C, "car = pCurrentWorld->CarTable[0];",
     "car = pCurrentWorld->CarTable[1];"),
    ("fol_sheet", C, "if (TheHeliSheet == NULL || !signposts_present())",
     "if (!signposts_present())"),
    ("fol_signs", C, "if (TheHeliSheet == NULL || !signposts_present())",
     "if (TheHeliSheet == NULL)"),
    ("fol_order", C, "if (TheHeliSheet == NULL || !signposts_present())",
     "if (!signposts_present() || TheHeliSheet == NULL)"),
    ("fol_null", C, "    if (car == NULL) {", "    if (car != NULL) {"),
    ("fol_start", C, "if (h->Plan == CHOPPLAN_START_CHASE\n"
     "            || h->Plan == CHOPPLAN_EATING_DONUTS) {",
     "if (h->Plan == CHOPPLAN_EATING_DONUTS) {"),
    ("fol_donuts", C, "if (h->Plan == CHOPPLAN_START_CHASE\n"
     "            || h->Plan == CHOPPLAN_EATING_DONUTS) {",
     "if (h->Plan == CHOPPLAN_START_CHASE) {"),
    ("fol_nullcar", C, "            h->CurrentCar = NULL;\n", ""),
    ("fol_eat", C, "            h->Plan = CHOPPLAN_EATING_DONUTS;\n"
     "        } else {", "            h->Plan = CHOPPLAN_START_CHASE;\n"
     "        } else {"),
    ("fol_end", C, "h->Plan = CHOPPLAN_END_CHASE;",
     "h->Plan = CHOPPLAN_PURSUIT;"),
    ("fol_ne_eat", C, "if (h->Plan != CHOPPLAN_EATING_DONUTS\n"
     "            && h->Plan != CHOPPLAN_START_CHASE)",
     "if (h->Plan != CHOPPLAN_START_CHASE)"),
    ("fol_ne_start", C, "if (h->Plan != CHOPPLAN_EATING_DONUTS\n"
     "            && h->Plan != CHOPPLAN_START_CHASE)",
     "if (h->Plan != CHOPPLAN_EATING_DONUTS)"),
    ("fol_ret0", C, "            return 0;\n        h->CurrentCar = car;",
     "            return 1;\n        h->CurrentCar = car;"),
    ("fol_setcar", C, "        h->CurrentCar = car;\n", ""),
    ("fol_plan", C, "h->Plan = CHOPPLAN_START_CHASE;\n    }",
     "h->Plan = CHOPPLAN_HEAD_TO_STAKEOUT;\n    }"),
    ("fol_think", C, "    h->TimeUntilThink = 0.0f;\n    return 1;",
     "    h->TimeUntilThink = 1.0f;\n    return 1;"),
    ("fol_ret1", C, "    h->TimeUntilThink = 0.0f;\n    return 1;",
     "    h->TimeUntilThink = 0.0f;\n    return 2;"),
    ("fol_ret_early", C, "if (TheHeliSheet == NULL || !signposts_present())\n"
     "        return 0;", "if (TheHeliSheet == NULL || !signposts_present())\n"
     "        return 1;"),
    # ---- AttackCar
    ("att_plan", C, "if (h->Plan != CHOPPLAN_PURSUIT) {",
     "if (h->Plan != CHOPPLAN_HEAD_TO_STAKEOUT) {"),
    ("att_car", C, "        if (h->CurrentCar != NULL)\n",
     "        if (h->CurrentCar != NULL && h->Plan != 4)\n"),
    ("att_no_follow", C, "            chopper_follow_this_car(h, h->CurrentCar);"
     "\n", ""),
    ("att_ret0", C, "        return 0;\n    }\n    h->TimeUntilNextSalvo",
     "        return 1;\n    }\n    h->TimeUntilNextSalvo"),
    ("att_salvo", C, "h->TimeUntilNextSalvo = 0.0f;\n    h->Timeout",
     "h->TimeUntilNextSalvo = 1.0f;\n    h->Timeout"),
    ("att_timeout", C, "h->Timeout = CHOPPER_TIMEOUT;\n    car",
     "h->Timeout = 0.0f;\n    car"),
    ("att_dx", C, "dx = car->State.Position.x - h->CurrentPos.x;",
     "dx = car->State.Position.x + h->CurrentPos.x;"),
    ("att_dy", C, "dy = car->State.Position.y - h->CurrentPos.y;",
     "dy = car->State.Position.x - h->CurrentPos.y;"),
    ("att_plan4", C, "h->Plan = CHOPPLAN_BOMBING_RUN;",
     "h->Plan = CHOPPLAN_END_CHASE;"),
    ("att_type", C, "h->BombRunType = type;", "h->BombRunType = type & 3;"),
    ("att_salvos", C, "h->NumSalvosReleased = 0;\n    h->TargetDistance",
     "h->NumSalvosReleased = 1;\n    h->TargetDistance"),
    ("att_sqrt", C, "sqrtf(dx * dx + dy * dy)", "(dx * dx + dy * dy)"),
    ("att_behind", C, "if (chopper_behind_car(h))\n",
     "if (!chopper_behind_car(h))\n"),
    ("att_neg", C, "h->TargetDistance = -h->TargetDistance;",
     "h->TargetDistance = h->TargetDistance;"),
    ("att_tr", C, "h->TargetRoute = h->ChopperRoute;",
     "h->TargetRoute = NULL;"),
    ("att_oldr", C, "h->OldCarRoute = car_get_route(h->CurrentCar, FIND_ROUTE);",
     "h->OldCarRoute = car_get_route(h->CurrentCar, 0);"),
    ("att_oldp", C, "h->OldCarPoint = car_get_route_point(h->CurrentCar, "
     "FIND_ROUTE);", "h->OldCarPoint = car_get_route_point(h->CurrentCar, 0);"),
    ("att_adjust", C, "    chopper_adjust_bomb_target(h);\n    return 1;",
     "    return 1;"),
    ("att_ret1", C, "    chopper_adjust_bomb_target(h);\n    return 1;",
     "    chopper_adjust_bomb_target(h);\n    return 2;"),
    # ---- AdjustBombTarget
    ("adj_type", C, "&BombRunBehaviours[h->BombRunType]",
     "&BombRunBehaviours[h->BombRunType & 3]"),
    ("adj_ahead", C, "b->Ahead * h->CurrentCar->State.VelocityMagnitude",
     "b->Ahead + h->CurrentCar->State.VelocityMagnitude"),
    ("adj_min_cmp", C, "if (ahead < BOMB_MIN_AHEAD)",
     "if (ahead > BOMB_MIN_AHEAD)"),
    ("adj_min_val", C, "#define BOMB_MIN_AHEAD     100.0f",
     "#define BOMB_MIN_AHEAD     100.5f"),
    ("adj_slack", C, "#define BOMB_TARGET_SLACK  24.0f",
     "#define BOMB_TARGET_SLACK  24.5f"),
    ("adj_le", C, "if (h->TargetDistance + BOMB_TARGET_SLACK < ahead) {",
     "if (h->TargetDistance + BOMB_TARGET_SLACK <= ahead) {"),
    ("adj_sub", C, "if (h->TargetDistance + BOMB_TARGET_SLACK < ahead) {",
     "if (h->TargetDistance - BOMB_TARGET_SLACK < ahead) {"),
    ("adj_nan", C, "if (h->TargetDistance + BOMB_TARGET_SLACK < ahead) {",
     "if (!(ahead <= h->TargetDistance + BOMB_TARGET_SLACK)) {"),
    ("adj_shift", C, "chopper_shift_target(h, ahead);",
     "chopper_shift_target(h, ahead + 1.0f);"),
    ("adj_spot", C, "        chopper_find_unobstructed_spot(h);\n    }\n}",
     "    }\n}"),
    ("tab_ahead0", C, "{ CM_ROCKET,         2.0f,",
     "{ CM_ROCKET,         2.5f,"),
    ("tab_ahead1", C, "{ CM_SMOKEBOMB,      2.0f,",
     "{ CM_SMOKEBOMB,      2.5f,"),
    ("tab_ahead2", C, "{ CM_SMOKEBOMB,      1.5f,",
     "{ CM_SMOKEBOMB,      1.75f,"),
    ("tab_ahead3", C, "{ CM_DROPPED_SPIKES, 2.0f,",
     "{ CM_DROPPED_SPIKES, 2.5f,"),
    ("tab_ahead4", C, "{ CM_DROPPED_SPIKES, 1.0f,",
     "{ CM_DROPPED_SPIKES, 1.25f,"),
    # ---- ShiftTarget
    ("sh_route_flag", C, "TrackRoute *route = car_get_route(h->CurrentCar, "
     "FIND_ROUTE);", "TrackRoute *route = car_get_route(h->CurrentCar, 0);"),
    ("sh_point_flag", C, "TrackRoutePoint *point = car_get_route_point("
     "h->CurrentCar, FIND_ROUTE);",
     "TrackRoutePoint *point = car_get_route_point(h->CurrentCar, 0);"),
    ("sh_count", C, "ai_guess_target_destinations(out, 5,",
     "ai_guess_target_destinations(out, 4,"),
    ("sh_slack", C, "dist + BOMB_TARGET_SLACK, 1);", "dist, 1);"),
    ("sh_fwd", C, "dist + BOMB_TARGET_SLACK, 1);",
     "dist + BOMB_TARGET_SLACK, 0);"),
    ("sh_td", C, "h->TargetDistance = dist;\n",
     "h->TargetDistance = dist + 1.0f;\n"),
    ("sh_bit", C, "(out[i].Point->Bits & TRP_NO_HELISHEET) == 0",
     "(out[i].Point->Bits & TRP_NO_HELISHEET) != 0"),
    ("sh_tp", C, "h->TargetPoint = out[i].Point;",
     "h->TargetPoint = out[0].Point;"),
    ("sh_tr", C, "h->TargetRoute = out[i].Route;",
     "h->TargetRoute = out[0].Route;"),
    ("sh_noreturn", C, "            h->TargetRoute = out[i].Route;\n"
     "            return;\n", "            h->TargetRoute = out[i].Route;\n"),
    ("sh_loop", C, "for (i = 0; i < n; i++) {",
     "for (i = 0; i + 1 < n; i++) {"),
    # ---- FindUnobstructedSpot
    ("sp_route", C, "info.Route = h->TargetRoute;",
     "info.Route = h->ChopperRoute;"),
    ("sp_sheet", C, "helisheet_find_z_value(TheHeliSheet,",
     "helisheet_find_z_value(NULL,"),
    ("sp_bit", C, "if ((flags & 1) == 0)", "if ((flags & 3) == 0)"),
    ("sp_flags0", C, "    uint32_t flags = 0;", "    uint32_t flags = 1;"),
    ("sp_len", C, "h->TargetDistance + info.Point->Length;",
     "h->TargetDistance - info.Point->Length;"),
    ("sp_store_r", C, "    h->TargetRoute = info.Route;\n"
     "    h->TargetPoint = info.Point;\n}",
     "    h->TargetPoint = info.Point;\n}"),
    ("sp_store_p", C, "    h->TargetRoute = info.Route;\n"
     "    h->TargetPoint = info.Point;\n}",
     "    h->TargetRoute = info.Route;\n}"),
    # ---- AbortBombingRun
    ("ab_cmp", C, "if (h->Plan == CHOPPLAN_BOMBING_RUN)\n"
     "        h->Plan = CHOPPLAN_PURSUIT;",
     "if (h->Plan != CHOPPLAN_BOMBING_RUN)\n        h->Plan = CHOPPLAN_PURSUIT;"),
    ("ab_val", C, "if (h->Plan == CHOPPLAN_BOMBING_RUN)\n"
     "        h->Plan = CHOPPLAN_PURSUIT;",
     "if (h->Plan == CHOPPLAN_BOMBING_RUN)\n        h->Plan = CHOPPLAN_END_CHASE;"),
    # ---- FindGroundHeight
    ("gr_x", C, "pt.x = h->CurrentPos.x;", "pt.x = h->CurrentPos.y;"),
    ("gr_y", C, "pt.y = h->CurrentPos.y;", "pt.y = h->CurrentPos.x;"),
    ("gr_z", C, "pt.z = h->GroundZ;", "pt.z = h->CurrentPos.z;"),
    ("gr_store", C, "h->GroundZ = topology_get_elevation(",
     "(void)topology_get_elevation("),
    ("gr_ret", C, "    return terrain;", "    return terrain + 1;"),
    # ---- Place and Remove
    ("pl_act", C, "    sound_activate(h, 1);\n", "    sound_activate(h, 0);\n"),
    ("pl_x", C, "h->CurrentPos.x = pos->x;", "h->CurrentPos.x = pos->y;"),
    ("pl_z", C, "h->CurrentPos.z = z;", "h->CurrentPos.z = z + 1.0f;"),
    ("pl_pitch", C, "    h->Pitch = 0.0f;\n    h->DesiredPitch = 0.0f;\n"
     "    h->Roll = 0.0f;", "    h->DesiredPitch = 0.0f;\n    h->Roll = 0.0f;"),
    ("pl_dpitch", C, "    h->DesiredPitch = 0.0f;\n    h->Roll = 0.0f;",
     "    h->Roll = 0.0f;"),
    ("pl_roll", C, "    h->Roll = 0.0f;\n    h->DesiredRoll = 0.0f;\n"
     "    h->Speed", "    h->DesiredRoll = 0.0f;\n    h->Speed"),
    ("pl_droll", C, "    h->DesiredRoll = 0.0f;\n    h->Speed = 0.0f;\n"
     "    h->CurrentPos.y", "    h->Speed = 0.0f;\n    h->CurrentPos.y"),
    ("pl_speed", C, "    h->Speed = 0.0f;\n    h->CurrentPos.y",
     "    h->CurrentPos.y"),
    ("pl_y", C, "h->CurrentPos.y = pos->y;", "h->CurrentPos.y = pos->x;"),
    ("pl_yaw", C, "h->CurrentCar->State.Angle * 0.0054931640625f",
     "h->CurrentCar->State.Angle * 0.0055f"),
    ("pl_tp", C, "    trackpath_coord_reset_position(&h->TP, (const bVector2 "
     "*)&h->CurrentPos);\n    topology_set", "    topology_set"),
    ("pl_bbox_r", C, "(const bVector2 *)&h->CurrentPos, 1.0f, NULL);",
     "(const bVector2 *)&h->CurrentPos, 2.0f, NULL);"),
    ("pl_bbox", C, "    topology_set_interest_bbox(&h->TopologyCoord,\n"
     "                               (const bVector2 *)&h->CurrentPos, 1.0f, "
     "NULL);\n", ""),
    ("pl_gz", C, "h->GroundZ = h->CurrentCar->State.Position.z;",
     "h->GroundZ = h->CurrentCar->State.Position.y;"),
    ("pl_ground", C, "    chopper_find_ground_height(h);\n"
     "    chopper_find_point_from_scratch(h);\n    chopper_calc_matrix(h);",
     "    chopper_find_point_from_scratch(h);\n    chopper_calc_matrix(h);"),
    ("pl_scratch", C, "    chopper_find_point_from_scratch(h);\n"
     "    chopper_calc_matrix(h);", "    chopper_calc_matrix(h);"),
    ("pl_matrix", C, "    chopper_find_point_from_scratch(h);\n"
     "    chopper_calc_matrix(h);", "    chopper_find_point_from_scratch(h);"),
    ("rm_en", C, "h->WorldObj->Enabled = 0;", "h->WorldObj->Enabled = 2;"),
    ("rm_act", C, "    sound_activate(h, 0);\n", "    sound_activate(h, 1);\n"),
    ("rm_clear", C, "    topology_clear_interest_bbox(&h->TopologyCoord);\n",
     ""),
    # ---- the sound
    ("snd_act_slot", C, "e = sound_slot(h, CHOPPERSOUND_VT_ACTIVATE);",
     "e = sound_slot(h, CHOPPERSOUND_VT_MUTE);"),
    ("snd_act_arg", C, "vt_this(h->pChopperSound, e), on);",
     "vt_this(h->pChopperSound, e), !on);"),
    ("mu_slot", C, "sound_slot(h, CHOPPERSOUND_VT_MUTE)",
     "sound_slot(h, CHOPPERSOUND_VT_ACTIVATE)"),
    ("mu_arg", C, "vt_this(h->pChopperSound, e), i);",
     "vt_this(h->pChopperSound, e), i + 1);"),
    ("us_a", C, "1.0f, 0, 1.0f);", "0.5f, 0, 1.0f);"),
    ("us_b", C, "1.0f, 0, 1.0f);", "1.0f, 1, 1.0f);"),
    ("us_c", C, "1.0f, 0, 1.0f);", "1.0f, 0, 0.5f);"),
    # ---- BehindCar, Rotate, MaxDeceleration
    ("be_a", C, "&TheTrackPathManager, h->TP.DistanceAroundTrack,",
     "&TheTrackPathManager, h->TP.RatioAroundTrack,"),
    ("be_b", C, "h->CurrentCar->TheTrackPathCoordinate.DistanceAroundTrack)",
     "h->CurrentCar->TheTrackPathCoordinate.RatioAroundTrack)"),
    ("be_lt", C, "           <= 0.0f;", "           < 0.0f;"),
    ("be_ge", C, "           <= 0.0f;", "           >= 0.0f;"),
    ("rot_360", C, "rotate_vector(out, v, 360.0f - h->Yaw);",
     "rotate_vector(out, v, h->Yaw);"),
    ("de_cmp", C, "(uint32_t)(h->Plan - 1) < 2u", "(uint32_t)(h->Plan - 1) < 3u"),
    ("de_sub", C, "(uint32_t)(h->Plan - 1) < 2u", "(uint32_t)(h->Plan - 2) < 2u"),
    ("de_signed", C, "(uint32_t)(h->Plan - 1) < 2u", "(h->Plan - 1) < 2"),
    ("de_a", C, "return -120.0f;", "return -121.0f;"),
    ("de_b", C, "return -60.0f;", "return -61.0f;"),
    # ---- the route points
    ("sc_which", C, "ALL_RACING_ROUTES, ROUTE_FLAGS,",
     "(RoutesToSearch)(ALL_RACING_ROUTES + 1), ROUTE_FLAGS,"),
    ("sc_flags", C, "#define ROUTE_FLAGS        6", "#define ROUTE_FLAGS        7"),
    ("sc_dist", C, "                                   0.0f)) {",
     "                                   1.0f)) {"),
    ("sc_r", C, "        h->ChopperRoute = info.Route;\n"
     "        h->ChopperPoint = info.Point;\n",
     "        h->ChopperPoint = info.Point;\n"),
    ("sc_p", C, "        h->ChopperRoute = info.Route;\n"
     "        h->ChopperPoint = info.Point;\n",
     "        h->ChopperRoute = info.Route;\n"),
    ("rp_radius", C, "#define ROUTE_POINT_RADIUS 24.0f",
     "#define ROUTE_POINT_RADIUS 25.0f"),
    ("rp_dist", C, "ROUTE_POINT_RADIUS, ROUTE_FLAGS, 0.0f);\n    if (p == NULL &&",
     "ROUTE_POINT_RADIUS, ROUTE_FLAGS, 1.0f);\n    if (p == NULL &&"),
    ("rp_nosign", C, "if (p == NULL && trpoint_has_signpost(h->ChopperPoint)) {",
     "if (p == NULL) {"),
    ("rp_sign", C, "if (p == NULL && trpoint_has_signpost(h->ChopperPoint)) {",
     "if (p == NULL && !trpoint_has_signpost(h->ChopperPoint)) {"),
    ("rp_null", C, "if (p == NULL && trpoint_has_signpost(h->ChopperPoint)) {",
     "if (trpoint_has_signpost(h->ChopperPoint)) {"),
    ("rp_route2", C, "        p = troute_find_closest_point(route,\n",
     "        p = troute_find_closest_point(h->ChopperRoute,\n"),
    ("rp_scratch", C, "    if (p == NULL) {\n"
     "        chopper_find_point_from_scratch(h);\n        return;\n    }\n",
     "    if (p == NULL)\n        return;\n"),
    ("rp_p", C, "    h->ChopperPoint = p;\n    h->ChopperRoute = route;",
     "    h->ChopperRoute = route;"),
    ("rp_r", C, "    h->ChopperPoint = p;\n    h->ChopperRoute = route;",
     "    h->ChopperPoint = p;"),
    # ---- CalcMatrix and the WorldObject
    ("mx_scale", C, "#define CHOPPER_SCALE      1.1f",
     "#define CHOPPER_SCALE      1.0f"),
    ("mx_raise", C, "#define CHOPPER_RAISE      2.3f",
     "#define CHOPPER_RAISE      2.0f"),
    ("mx_180", C, "yaw = 180.0f - h->Yaw;", "yaw = h->Yaw - 180.0f;"),
    ("mx_v0", C, "m.v0.x = CHOPPER_SCALE;", "m.v0.x = 1.0f;"),
    ("mx_v1", C, "m.v1.y = CHOPPER_SCALE;", "m.v1.y = 1.0f;"),
    ("mx_v2", C, "m.v2.z = CHOPPER_SCALE;", "m.v2.z = 1.0f;"),
    ("mx_lt", C, "if (yaw < 0.0f)", "if (yaw < 1.0f)"),
    ("mx_wrap", C, "yaw = yaw + 360.0f;", "yaw = yaw + 180.0f;"),
    ("mx_rx", C, "eRotateX(&m, &m, deg_to_bam(h->Roll));",
     "eRotateX(&m, &m, deg_to_bam(-h->Roll));"),
    ("mx_ry", C, "deg_to_bam(360.0f - h->Pitch)", "deg_to_bam(h->Pitch)"),
    ("mx_rz", C, "eRotateZ(&m, &m, deg_to_bam(yaw));",
     "eRotateY(&m, &m, deg_to_bam(yaw));"),
    ("mx_order", C, "    eRotateX(&m, &m, deg_to_bam(h->Roll));\n"
     "    eRotateY(&m, &m, deg_to_bam(360.0f - h->Pitch));\n",
     "    eRotateY(&m, &m, deg_to_bam(360.0f - h->Pitch));\n"
     "    eRotateX(&m, &m, deg_to_bam(h->Roll));\n"),
    ("mx_tx", C, "m.v3.x = h->CurrentPos.x;", "m.v3.x = h->CurrentPos.y;"),
    ("mx_ty", C, "m.v3.y = h->CurrentPos.y;", "m.v3.y = h->CurrentPos.x;"),
    ("mx_tz", C, "m.v3.z = h->CurrentPos.z + CHOPPER_RAISE;",
     "m.v3.z = h->CurrentPos.z;"),
    ("mx_store", C, "    h->Matrix = m;\n", "    h->Matrix.v3 = m.v3;\n"),
    ("mx_bam_div", C, "ee_trunc_w(deg * 65536.0f) / 360)",
     "ee_trunc_w(deg * 65536.0f) / 361)"),
    ("mx_bam_float", C, "(uint16_t)(ee_trunc_w(deg * 65536.0f) / 360)",
     "(uint16_t)ee_trunc_w(deg * (65536.0f / 360.0f))"),
    ("wo_mat", C, "    h->WorldObj->Matrix = h->Matrix;\n", ""),
    ("wo_en", C, "h->WorldObj->Enabled = 1;", "h->WorldObj->Enabled = 2;"),
    # ---- RotateVector
    ("rv_y", U, "out->y = y * c - x * s;", "out->y = y * c + x * s;"),
    ("rv_x", U, "out->x = x * c + y * s;", "out->x = x * c - y * s;"),
    ("rv_alias", U, "out->x = x * c + y * s;",
     "out->x = x * c + v->y * s;"),
    ("rv_bam", U, "(uint16_t)(ee_trunc_w(deg * 65536.0f) / 360)",
     "(uint16_t)(ee_trunc_w(deg * 65536.0f) / 361)"),
    ("rv_sc", U, "bSinCos(&s, &c,", "bSinCos(&c, &s,"),
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
    lines, scp = write_inputs(indir.name)
    base = model(lines)
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
        todo, SOURCES, "chopper_test",
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
