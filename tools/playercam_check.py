#!/usr/bin/env python3
"""Cross-check 3DS Files/source/playercam.c, Player's camera functions,
against the retail image itself, run in mipsemu.

The model is the image. Player::ChangeCameraMover (0x00176ae8),
CycleDriveCameraPOVIndex (0x001786d0), RestoreCameraMover (0x00176948),
RemoveCameraMovers (0x00177430), EnableCameraMovers (0x001774a8) and
DisableCameraMovers (0x00177558) run as shipped. The harness
(tools/src/playercam_test.c) runs the port over the same script, and the
two transcripts are diffed.

Everything under them is a stub that prints its arguments: bMalloc
(0x002577c0), the constructors of the drive (0x0015c258), orbit
(0x00157e48), debug-world (0x0015b268), track-route-editor (0x0015c010),
zone-freeze (0x00160298), zone-preview (0x00161f98) and cubic (0x0015e7b0)
movers, DriveCameraMover::SetPOVIndex (0x0015c520), PreviewRoute's
destructor (0x00164848), BaseCameraCoordinator's Enable (0x00199b90) and
Disable (0x00199b48), NisManager's Delete (0x001b2b90), Enable
(0x001b2c20) and Disable (0x001b2bd0), and the driving line's two thunks
(0x00183208, 0x00183200). The movers and coordinators have a fake vtable
in memory whose slots are stubs too, and a mover's destructor frees it
when flag bit 0 says to, as the real ones do.

Types 15 and 16, the zone jumpers, are one seam in the port. The model
repoints jump-table words 15 and 16 (0x002b3b30) at a six-word thunk
that calls the harness's stand-in with (player, car, second) and goes on
at the common tail, 0x001773ec, with the result stored at 200.

The script lays out the rest: the Player (retail's offsets), four cars
with their RideInfo, World's car list at gp-22120 and SkipFE at
gp-23220. Two pools of movers: a0, a1, ... from bMalloc, and x0, x1, ...
the script makes to hand the player. Every mover and the Player start
from a byte pattern, so what a call leaves alone shows.

Two things the script steers round, since retail would crash there and
the port does not: RestoreCameraMover with nothing saved (retail calls
Enable through NULL), and the POV cycle's read of MyCar when there is no
car (the script keeps SkipFE set while MyCar is NULL). The debug-world
mover is never asked for when the car comes from an empty World, whose
"position" is World's own bytes.

    python tools/playercam_check.py
    python tools/playercam_check.py --mutate [--only a,b]
    python tools/playercam_check.py --dump out/playercam
"""
import argparse
import os
import random
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import physicscar_check as pcc
import retail_model
from mipsemu import M32, f_to_bits, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/playercam_test.c"
PCC = "3DS Files/source/playercam.c"
SOURCES = [HARNESS, PCC]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
CHANGE = 0x00176ae8
CYCLE = 0x001786d0
RESTORE = 0x00176948
REMOVE = 0x00177430
ENABLE = 0x001774a8
DISABLE = 0x00177558
TAIL = 0x001773ec
JUMP_TABLE = 0x002b3b30

B_MALLOC = 0x002577c0
DRIVE_CTOR = 0x0015c258
SET_POV = 0x0015c520
ORBIT_CTOR = 0x00157e48
DW_CTOR = 0x0015b268
TRE_CTOR = 0x0015c010
ZF_CTOR = 0x00160298
ZP_CTOR = 0x00161f98
CUBIC_CTOR = 0x0015e7b0
ROUTE_DTOR = 0x00164848
CO_ENABLE = 0x00199b90
CO_DISABLE = 0x00199b48
NIS_DELETE = 0x001b2b90
NIS_ENABLE = 0x001b2c20
NIS_DISABLE = 0x001b2bd0
LINE_ENABLE = 0x00183208
LINE_DISABLE = 0x00183200

G_SKIPFE = GP - 23220
G_WORLD = GP - 22120

# Retail's Player, by offset.
P_CAR = 4
P_VIEW = 24
P_POV = 36          # PlayerSettings (32) + 4, a byte
P_SPRING = 40
P_ROUTE = 136
P_CUR = 200
P_SAVED = 204
P_SAVED2 = 208
P_RVM = 212
P_DEMO = 216
P_COUNT = 220
P_NIS = 224
P_LINE = 228
P_MGR = 244
P_LOOK = 764

# The mover's, and its vtable's slots by the function's offset.
M_TYPE = 8
M_PLAYER = 28
M_VTBL = 40
M_LOOKBACK = 124    # DriveCameraMover::DesiredLookBackParam
SLOTS = {
    "destroy": 12, "update": 20, "render": 28, "addjoy": 36, "remjoy": 44,
    "info": 52, "pov": 60, "ext": 68, "lookback": 76, "gap": 84,
    "reset": 92, "enable": 100, "disable": 108, "car": 116, "target": 124,
}

NOBJ = 1024
NX = 256
OBJ_BYTES = 4096
APOOL = 0x01000000
XPOOL = APOOL + NOBJ * OBJ_BYTES
POVS = XPOOL + NX * OBJ_BYTES
POV_STRIDE = 128
MISC = POVS + (NOBJ + NX) * POV_STRIDE
PLAYER = MISC
PLAYER_BYTES = 4096
CARS = MISC + 0x1000
CAR_STRIDE = 0x400
NCAR = 4
RIDES = MISC + 0x2000
WORLD = MISC + 0x2100
CO_DEMO = MISC + 0x2200
CO_COUNT = MISC + 0x2300
CO_NIS = MISC + 0x2400
NIS_MGR = MISC + 0x2500
LINE = MISC + 0x2600
ROUTE = MISC + 0x2700
CINFO = MISC + 0x2800
CO_VTBL = MISC + 0x2900
MOV_VTBL = MISC + 0x2a00
THUNKS = MISC + 0x2b00
STUBS = MISC + 0x2c00       # the fake functions, eight bytes apart

PATTERN = 0xa5

FIELDS = {
    "car": (P_CAR, "car"), "view": (P_VIEW, "w"), "pov": (P_POV, "b"),
    "spring": (P_SPRING, "w"), "look": (P_LOOK, "w"),
    "route": (P_ROUTE, ROUTE), "cur": (P_CUR, "x"), "saved": (P_SAVED, "x"),
    "saved2": (P_SAVED2, "x"), "rvm": (P_RVM, "x"),
    "demo": (P_DEMO, CO_DEMO), "count": (P_COUNT, CO_COUNT),
    "nis": (P_NIS, CO_NIS), "line": (P_LINE, LINE),
}


def fx(w):
    """A float's bits, with every NaN the one "nan"."""
    w &= M32
    if (w & 0x7f800000) == 0x7f800000 and (w & 0x7fffff):
        return "nan"
    return "%08x" % w


def obj_at(i):
    return APOOL + OBJ_BYTES * i if i < NOBJ else XPOOL + OBJ_BYTES * (i - NOBJ)


def obj_name(i):
    return "a%d" % i if i < NOBJ else "x%d" % (i - NOBJ)


def car_at(i):
    return 0 if i < 0 else CARS + CAR_STRIDE * i


def ride_at(i):
    return RIDES + 16 * i


# ============================================================ the scenarios

TYPES = list(range(19)) + [25, -1, -2147483648]
POV_TYPES = (-1, 0, 1, 2, 3)


def rbits(rnd):
    k = rnd.random()
    if k < 0.1:
        return rnd.choice((0x00000000, 0x80000000, 0x3f800000, 0xc0800000,
                           0x7f7fffff, 0xff7fffff, 0x00000001, 0x7f800000,
                           0x7fc00000, 0xc0800001))
    return f_to_bits(rnd.uniform(-2000.0, 2000.0))


def rpos(rnd):
    return " ".join("%08x" % rbits(rnd) for _ in range(4))


def rcfg(rnd):
    return "%d %s" % (rnd.choice((1, 1, 1, 0)),
                      " ".join(str(rnd.choice(POV_TYPES)) for _ in range(4)))


def s_types(rnd):
    """Each type from nothing, with and without keep, then again over
    itself, from the player's car and from World's list."""
    out = ["K 0 %s" % rpos(rnd), "K 2 %s" % rpos(rnd), "W 2"]
    for car in (0, -1):
        if car < 0:
            out += ["S skip 1", "S car -1"]
        for t in TYPES:
            for keep in (0, 1):
                out += ["M", "S route 1", "S view %d" % rnd.randrange(4),
                        "C %d %d" % (t, keep), "C %d 0" % t, "C 0 %d" % keep]
    # From an empty World, everything but the debug-world mover.
    out += ["W -1"]
    for t in TYPES:
        if t != 2:
            out += ["M", "S route 1", "C %d 0" % t]
    out += ["M"]
    return out


def s_keep(rnd):
    """The saves: keep chains two deep, the zone freeze taking the one just
    kept, restores down to nothing, and the look back on a restored drive
    camera."""
    out = ["X 4", "S cur 0", "C 1 1", "C 13 1", "R", "R", "R",
           "S look 1", "X 1", "S cur 1", "C 4 1", "R", "S look 0", "C 17 1",
           "C 14 1", "S route 1", "C 14 1", "C 13 1", "R", "R", "R", "R",
           "M", "X 1", "X 4", "X 13", "S cur 2", "S saved 3", "S saved2 4",
           "C 1 1", "M", "X 1", "S saved 5", "S look 1", "R", "S look 7",
           "C 4 1", "R", "X 2", "X 3", "S saved 6", "S saved2 7", "C 16 1",
           "R", "R", "R", "M"]
    for _ in range(40):
        out.append("C %d %d" % (rnd.choice((1, 4, 13, 14, 15, 16, 17, 0, 3)),
                                rnd.choice((0, 1, 1))))
        if rnd.random() < 0.4:
            out.append("R")
        if rnd.random() < 0.2:
            out.append("S look %d" % rnd.choice((0, 1)))
    out.append("M")
    return out


def s_cycle(rnd):
    """The POV cycle over a fake drive camera: every index from -9 to 9
    under each combination of POVs, SkipFE, the dash and the camera's
    type."""
    out = ["X 1", "S cur 0"]
    cfgs = ["1 0 1 2 1", "1 1 1 1 1", "1 -1 -1 -1 -1", "1 1 3 1 2",
            "1 3 3 3 0", "1 -1 1 -1 2", "0 0 1 2 1", "1 1 -1 1 -1"]
    for _ in range(6):
        cfgs.append(rcfg(rnd))
    for cfg in cfgs:
        out.append("J %s" % cfg)
        for skip, dash in ((0, 0), (1, 0), (0, 1), (0, -1)):
            out += ["S skip %d" % skip, "H 0 %d" % dash]
            for i in range(-9, 10):
                out.append("Q %d" % i)
    out += ["S skip 0", "H 0 0", "J 1 0 1 2 1"]
    for t in (4, 0, 13, 17, 1):
        out += ["Y %d" % t, "Q 2", "Q -3"]
    out += ["S cur -1", "Q 5", "Q -6"]
    # The drive camera ChangeCameraMover builds, cycling from each stored
    # index under each set of defaults.
    for cfg in cfgs[:8]:
        out.append("F %s" % cfg)
        for pov in (-5, -1, 0, 1, 2, 3, 4, 7, 127, -128):
            out += ["S pov %d" % pov, "H 0 %d" % rnd.choice((0, 0, 1)),
                    "C 1 0", "C 0 0"]
    return out


def s_coords(rnd):
    """The coordinators, the mirror's mover and the driving line, through
    Enable, Disable and the deletes ChangeCameraMover starts with."""
    out = ["X 4", "S rvm 0"]
    for mask in range(16):
        out += ["S demo %d" % (mask & 1), "S count %d" % (mask >> 1 & 1),
                "S nis %d" % (mask >> 2 & 1), "S line %d" % (mask >> 3 & 1),
                "E", "D", "C 4 0", "E", "D", "C 4 0", "C 1 0", "E", "D"]
    out += ["S rvm -1", "E", "D", "M", "E", "D", "S demo 1", "S count 1",
            "S nis 1", "M", "E"]
    return out


def s_walk(rnd, n):
    out = []
    car, skip, head, nx = 0, 0, 0, 0
    for _ in range(n):
        r = rnd.random()
        if r < 0.30:
            t = rnd.choice(TYPES + [1, 1, 1, 4, 4, 4, 0, 13, 14, 15, 16, 17])
            if t == 2 and car < 0 and head < 0:
                t = 4
            out.append("C %d %d" % (t, rnd.choice((0, 0, 1))))
        elif r < 0.36:
            out.append("Q %d" % rnd.randrange(-9, 10))
        elif r < 0.42:
            out.append("R")
        elif r < 0.44:
            out.append("M")
        elif r < 0.48:
            out.append(rnd.choice(("E", "D")))
        elif r < 0.52:
            c = rnd.randrange(-1, NCAR)
            if c < 0 and not skip:
                out.append("S skip 1")
                skip = 1
            out.append("S car %d" % c)
            car = c
        elif r < 0.55:
            v = rnd.choice((0, 0, 1, 2))
            if v == 0 and car < 0:
                continue
            out.append("S skip %d" % v)
            skip = v
        elif r < 0.64:
            f = rnd.choice(("view", "pov", "spring", "look", "route",
                            "route"))
            v = {"view": (0, 1, 2, 3, -1), "pov": (-5, -1, 0, 1, 2, 3, 5, 127),
                 "spring": (0, 1, 5, -1), "look": (0, 1, 1, 2),
                 "route": (0, 1)}[f]
            out.append("S %s %d" % (f, rnd.choice(v)))
        elif r < 0.72:
            if nx >= NX:
                continue
            out += ["X %d" % rnd.choice((1, 1, 4, 13, 0, 17, 3)),
                    "S %s %d" % (rnd.choice(("cur", "cur", "saved", "saved2",
                                             "rvm")), nx)]
            nx += 1
        elif r < 0.73:
            out.append("S %s -1" % rnd.choice(("cur", "saved", "saved2",
                                               "rvm")))
        elif r < 0.79:
            out.append("S %s %d" % (rnd.choice(("demo", "count", "nis",
                                                "line")), rnd.choice((0, 1))))
        elif r < 0.82:
            h = rnd.randrange(-1, NCAR)
            out.append("W %d" % h)
            head = h
        elif r < 0.86:
            out.append("H %d %d" % (rnd.randrange(NCAR),
                                    rnd.choice((0, 0, 1, -1))))
        elif r < 0.90:
            out.append("K %d %s" % (rnd.randrange(NCAR), rpos(rnd)))
        elif r < 0.93:
            out.append("F %s" % rcfg(rnd))
        elif r < 0.97:
            out.append("J %s" % rcfg(rnd))
        else:
            out.append("Y %d" % rnd.choice((1, 1, 4, 13, 0)))
    out.append("M")
    return out


def script():
    rnd = random.Random(0x91a7ca11)
    sc = [s_types(rnd), s_keep(rnd), s_cycle(rnd), s_coords(rnd)]
    for n in (300, 800, 1500):
        sc.append(s_walk(rnd, n))
    return sc


def encode(scenarios):
    lines = []
    for i, s in enumerate(scenarios):
        lines.append("B %d" % i)
        lines += s
    return NL.join(lines) + NL


# ================================================================ the model


class Model(object):
    def __init__(self):
        self.out = []
        self.e = retail_model.RetailEmu(ieee=True)
        e = self.e
        assert e.u32(JUMP_TABLE + 4) == 0x00176c20
        assert e.u32(JUMP_TABLE + 60) == 0x00176ddc
        assert e.u32(JUMP_TABLE + 64) == 0x00177200
        self.nstub = 0
        for a, fn in ((B_MALLOC, self.s_malloc), (DRIVE_CTOR, self.s_drive),
                      (SET_POV, self.s_setpov), (ORBIT_CTOR, self.s_orbit),
                      (DW_CTOR, self.s_dw), (TRE_CTOR, self.s_tre),
                      (ZF_CTOR, self.s_zf), (ZP_CTOR, self.s_zp),
                      (CUBIC_CTOR, self.s_cubic),
                      (ROUTE_DTOR, self.s_routedel),
                      (CO_ENABLE, self.s_coen), (CO_DISABLE, self.s_codis),
                      (NIS_DELETE, self.s_nisdel),
                      (NIS_ENABLE, self.s_nisen),
                      (NIS_DISABLE, self.s_nisdis),
                      (LINE_ENABLE, self.s_lineen),
                      (LINE_DISABLE, self.s_linedis)):
            e.stub(a, fn)
        bad = self.fake(self.s_bad)
        # The movers' vtable, every this-delta 0.
        for off in SLOTS.values():
            e.put32(MOV_VTBL + off - 4, 0)
            e.put32(MOV_VTBL + off, bad)
        for name, fn in (("destroy", self.s_destroy), ("info", self.s_info),
                         ("pov", self.s_pov), ("enable", self.s_enable),
                         ("disable", self.s_disable)):
            e.put32(MOV_VTBL + SLOTS[name], self.fake(fn))
        # The coordinators', at +24: the destructor at 12.
        e.put32(CO_VTBL + 8, 0)
        e.put32(CO_VTBL + 12, self.fake(self.s_codel))
        for co in (CO_DEMO, CO_COUNT):
            e.put32(co + 24, CO_VTBL)
        # The zone jumpers' thunks.
        jump = self.fake(self.s_jump)
        for k in (0, 1):
            t = THUNKS + 32 * k
            words = [
                (17 << 21) | (4 << 11) | 0x21,          # addu a0,s1,zero
                (18 << 21) | (5 << 11) | 0x21,          # addu a1,s2,zero
                (3 << 26) | ((jump >> 2) & 0x3ffffff),  # jal jump
                (9 << 26) | (6 << 16) | k,              # addiu a2,zero,k
                (2 << 26) | ((TAIL >> 2) & 0x3ffffff),  # j TAIL
                (0x2b << 26) | (17 << 21) | (2 << 16) | P_CUR,  # sw v0,200(s1)
            ]
            for i, w in enumerate(words):
                e.put32(t + 4 * i, w)
            e.put32(JUMP_TABLE + 4 * (15 + k), t)

        self.names = {0: "null", PLAYER: "pl", WORLD: "w", WORLD + 96: "w.pos",
                      CO_DEMO: "cd", CO_COUNT: "cc", CO_NIS: "cn",
                      NIS_MGR: "nm", LINE: "ln", ROUTE: "rt", CINFO: "ci"}
        for i in range(NOBJ + NX):
            self.names[obj_at(i)] = obj_name(i)
            for k in range(4):
                self.names[POVS + POV_STRIDE * i + 32 * k] = \
                    "%s.p%d" % (obj_name(i), k)
        for i in range(NCAR):
            self.names[car_at(i)] = "k%d" % i
            self.names[car_at(i) + 96] = "k%d.pos" % i

    def fake(self, fn):
        a = STUBS + 8 * self.nstub
        self.nstub += 1
        self.e.stub(a, fn)
        return a

    def emit(self, s):
        self.out.append(s)

    def name(self, a):
        return self.names.get(a & M32, "?%08x" % (a & M32))

    def arg(self, i):
        return self.e.reg[(4, 5, 6, 7, 8, 9, 10, 11)[i]] & M32

    def w(self, a):
        return self.e.u32(a)

    def fill(self, a, n):
        self.e.write(a, bytes([PATTERN]) * n)

    def cstr(self, a):
        b = bytearray()
        while self.e.mem[a]:
            b.append(self.e.mem[a])
            a += 1
        return b.decode("latin-1")

    def index_of(self, a):
        if APOOL <= a < XPOOL and (a - APOOL) % OBJ_BYTES == 0:
            return (a - APOOL) // OBJ_BYTES
        if XPOOL <= a < POVS and (a - XPOOL) % OBJ_BYTES == 0:
            return NOBJ + (a - XPOOL) // OBJ_BYTES
        return None

    # ---- the arena -------------------------------------------------------

    def new_obj(self, i, kind):
        self.fill(obj_at(i), OBJ_BYTES)
        self.kind[i] = kind
        self.live[i] = True
        self.info[i] = self.definfo
        self.pov[i] = list(self.defpov)
        return obj_at(i)

    def new_a(self, kind):
        if self.nobj >= NOBJ:
            raise SystemExit("arena full")
        i = self.nobj
        self.nobj += 1
        return self.new_obj(i, kind)

    def built(self, m, kind, typ):
        i = self.index_of(m)
        if i is not None:
            self.kind[i] = kind
        self.e.put32(m + M_TYPE, typ)
        self.e.put32(m + M_VTBL, MOV_VTBL)
        return m

    # ---- the stubs -------------------------------------------------------

    def s_bad(self, e):
        raise SystemExit("a vtable slot the port never calls, at 0x%08x"
                         % (e.reg[31] & M32))

    def s_malloc(self, e):
        a = self.new_a("?")
        self.emit("  malloc %d %s %d %d -> %s"
                  % (s32(self.arg(0)), self.cstr(self.arg(1)),
                     s32(self.arg(2)), s32(self.arg(3)), self.name(a)))
        return a

    def s_destroy(self, e):
        m, flag = self.arg(0), s32(self.arg(1))
        self.emit("  destroy %s flag %d" % (self.name(m), flag))
        if flag & 1:
            self.emit("  free %s" % self.name(m))
            i = self.index_of(m)
            if i is not None:
                self.live[i] = False

    def s_info(self, e):
        m = self.arg(0)
        r = CINFO if self.info[self.index_of(m)] else 0
        self.emit("  info %s -> %s" % (self.name(m), self.name(r)))
        return r

    def s_pov(self, e):
        m, k = self.arg(0), s32(self.arg(1))
        i = self.index_of(m)
        r = 0
        if 0 <= k < 4 and self.pov[i][k] >= 0:
            r = POVS + POV_STRIDE * i + 32 * k
            e.put32(r, self.pov[i][k])
        self.emit("  getpov %s %d -> %s" % (self.name(m), k, self.name(r)))
        return r

    def s_enable(self, e):
        self.emit("  enable %s" % self.name(self.arg(0)))

    def s_disable(self, e):
        self.emit("  disable %s" % self.name(self.arg(0)))

    def s_drive(self, e):
        m = self.arg(0)
        self.emit("  drive %s view %d car %s pov %d speed %s lag %d lb %d"
                  " focus %d"
                  % (self.name(m), s32(self.arg(1)), self.name(self.arg(2)),
                     s32(self.arg(3)), fx(e.fpr[12]), s32(self.arg(4)),
                     s32(self.arg(5)), s32(self.arg(6))))
        return self.built(m, "drive", 1)

    def s_setpov(self, e):
        self.emit("  setpov %s %d" % (self.name(self.arg(0)),
                                      s32(self.arg(1))))

    def s_orbit(self, e):
        m = self.arg(0)
        self.emit("  orbit %s view %d car %s port %d"
                  % (self.name(m), s32(self.arg(1)), self.name(self.arg(2)),
                     s32(self.arg(3))))
        return self.built(m, "orbit", 4)

    def s_dw(self, e):
        m, pos, d = self.arg(0), self.arg(2), self.arg(3)
        w = self.w
        self.emit("  dw %s view %d pos %s dir %s port %d"
                  % (self.name(m), s32(self.arg(1)),
                     " ".join(fx(w(pos + 4 * i)) for i in range(4)),
                     " ".join(fx(w(d + 4 * i)) for i in range(3)),
                     s32(self.arg(4))))
        return self.built(m, "dw", 2)

    def s_tre(self, e):
        m = self.arg(0)
        self.emit("  tre %s view %d port %d"
                  % (self.name(m), s32(self.arg(1)), s32(self.arg(2))))
        return self.built(m, "tre", 3)

    def s_zf(self, e):
        m = self.arg(0)
        self.emit("  zf %s view %d car %s saved %s"
                  % (self.name(m), s32(self.arg(1)), self.name(self.arg(2)),
                     self.name(self.arg(3))))
        return self.built(m, "zf", 13)

    def s_zp(self, e):
        m = self.arg(0)
        self.emit("  zp %s view %d route %s pos %s"
                  % (self.name(m), s32(self.arg(1)), self.name(self.arg(2)),
                     self.name(self.arg(3))))
        return self.built(m, "zp", 14)

    def s_cubic(self, e):
        m = self.arg(0)
        self.emit("  cubic %s view %d car %s"
                  % (self.name(m), s32(self.arg(1)), self.name(self.arg(2))))
        return self.built(m, "cubic", 17)

    def s_jump(self, e):
        second = s32(self.arg(2))
        m = self.new_a("jump")
        self.emit("  jump %s car %s second %d -> %s"
                  % (self.name(self.arg(0)), self.name(self.arg(1)), second,
                     self.name(m)))
        return self.built(m, "jump", 15 + second)

    def s_routedel(self, e):
        self.emit("  routedel %s flag %d" % (self.name(self.arg(0)),
                                             s32(self.arg(1))))

    def s_codel(self, e):
        self.emit("  codel %s flag %d" % (self.name(self.arg(0)),
                                          s32(self.arg(1))))

    def s_coen(self, e):
        self.emit("  coen %s" % self.name(self.arg(0)))

    def s_codis(self, e):
        self.emit("  codis %s" % self.name(self.arg(0)))

    def s_nisdel(self, e):
        self.emit("  nisdel %s %s" % (self.name(self.arg(0)),
                                      self.name(self.arg(1))))

    def s_nisen(self, e):
        self.emit("  nisen %s %s" % (self.name(self.arg(0)),
                                     self.name(self.arg(1))))

    def s_nisdis(self, e):
        self.emit("  nisdis %s %s" % (self.name(self.arg(0)),
                                      self.name(self.arg(1))))

    def s_lineen(self, e):
        self.emit("  lineen %s" % self.name(self.arg(0)))

    def s_linedis(self, e):
        self.emit("  linedis %s" % self.name(self.arg(0)))

    # ---- the state -------------------------------------------------------

    def reset(self):
        e = self.e
        self.nobj = self.nx = 0
        self.kind = [None] * (NOBJ + NX)
        self.live = [False] * (NOBJ + NX)
        self.info = [0] * (NOBJ + NX)
        self.pov = [[-1] * 4 for _ in range(NOBJ + NX)]
        self.definfo = 1
        self.defpov = [0, 1, 2, 1]
        self.fill(POVS, POV_STRIDE * (NOBJ + NX))
        self.fill(PLAYER, PLAYER_BYTES)
        for off in (P_ROUTE, P_CUR, P_SAVED, P_SAVED2, P_RVM, P_DEMO,
                    P_COUNT, P_NIS, P_LINE, P_VIEW, P_SPRING, P_LOOK):
            e.put32(PLAYER + off, 0)
        e.put32(PLAYER + P_CAR, car_at(0))
        e.mem[PLAYER + P_POV] = 0
        e.put32(PLAYER + P_MGR, NIS_MGR)
        e.put32(G_SKIPFE, 0)
        self.fill(CARS, CAR_STRIDE * NCAR)
        for i in range(NCAR):
            self.fill(ride_at(i), 16)
            e.mem[ride_at(i) + 6] = 0
            e.put32(car_at(i) + 16, ride_at(i))
        e.put32(G_WORLD, WORLD)
        e.put32(WORLD, car_at(0))

    def set_field(self, f, v):
        e = self.e
        if f == "skip":
            e.put32(G_SKIPFE, v)
            return
        off, kind = FIELDS[f]
        a = PLAYER + off
        if kind == "car":
            e.put32(a, car_at(v))
        elif kind == "w":
            e.put32(a, v)
        elif kind == "b":
            e.mem[a] = v & 0xff
        elif kind == "x":
            e.put32(a, 0 if v < 0 else obj_at(NOBJ + v))
        else:
            e.put32(a, kind if v else 0)

    def set_cfg(self, i, t):
        self.info[i] = int(t[0])
        self.pov[i] = [int(x) for x in t[1:5]]

    # ---- the dumps -------------------------------------------------------

    def dump_obj(self, i):
        if not self.live[i]:
            return
        m = obj_at(i)
        typ = s32(self.w(m + M_TYPE))
        s = "  %s %s type %d player %s" % (obj_name(i), self.kind[i], typ,
                                           self.name(self.w(m + M_PLAYER)))
        if typ == 1:
            s += " lb %s" % fx(self.w(m + M_LOOKBACK))
        self.emit(s)

    def dump(self):
        w, p = self.w, PLAYER
        pov = self.e.mem[p + P_POV]
        self.emit("  pl car %s view %d pov %d spring %d look %d route %s"
                  " cur %s saved %s saved2 %s rvm %s demo %s count %s nis %s"
                  " line %s mgr %s"
                  % (self.name(w(p + P_CAR)), s32(w(p + P_VIEW)),
                     pov - 256 if pov & 0x80 else pov, s32(w(p + P_SPRING)),
                     s32(w(p + P_LOOK)), self.name(w(p + P_ROUTE)),
                     self.name(w(p + P_CUR)), self.name(w(p + P_SAVED)),
                     self.name(w(p + P_SAVED2)), self.name(w(p + P_RVM)),
                     self.name(w(p + P_DEMO)), self.name(w(p + P_COUNT)),
                     self.name(w(p + P_NIS)), self.name(w(p + P_LINE)),
                     self.name(w(p + P_MGR))))
        for i in range(self.nobj):
            self.dump_obj(i)
        for i in range(self.nx):
            self.dump_obj(NOBJ + i)

    # ---- the ops ---------------------------------------------------------

    def op(self, t):
        e = self.e
        c = t[0]
        lim = dict(limit=200000)
        if c == "S":
            self.set_field(t[1], int(t[2], 0))
        elif c == "W":
            i = int(t[1])
            e.put32(WORLD, WORLD if i < 0 else car_at(i))
        elif c == "H":
            e.mem[ride_at(int(t[1])) + 6] = int(t[2]) & 0xff
        elif c == "K":
            a = car_at(int(t[1])) + 96
            for i in range(4):
                e.put32(a + 4 * i, int(t[2 + i], 16))
        elif c == "F":
            self.definfo = int(t[1])
            self.defpov = [int(x) for x in t[2:6]]
        elif c == "I":
            self.set_cfg(NOBJ + int(t[1]), t[2:7])
        elif c == "J":
            i = self.index_of(self.w(PLAYER + P_CUR))
            if i is not None:
                self.set_cfg(i, t[1:6])
        elif c == "X":
            if self.nx >= NX:
                raise SystemExit("x pool full")
            m = self.new_obj(NOBJ + self.nx, "x")
            self.nx += 1
            self.emit("  new %s" % self.name(m))
            self.built(m, "x", int(t[1]))
        elif c == "Y":
            cur = self.w(PLAYER + P_CUR)
            if cur:
                e.put32(cur + M_TYPE, int(t[1]))
        elif c == "C":
            e.call(CHANGE, PLAYER, int(t[1]), int(t[2]), **lim)
        elif c == "Q":
            r = e.call(CYCLE, PLAYER, int(t[1]), **lim)
            self.emit("  cycle -> %d" % r)
        elif c == "R":
            if self.w(PLAYER + P_SAVED) == 0:
                self.emit("  nothing saved")
            else:
                e.call(RESTORE, PLAYER, **lim)
        elif c == "M":
            e.call(REMOVE, PLAYER, **lim)
        elif c == "E":
            e.call(ENABLE, PLAYER, **lim)
        elif c == "D":
            e.call(DISABLE, PLAYER, **lim)
        else:
            raise SystemExit("bad op %r" % (t,))
        self.dump()

    def run(self, scenarios):
        for i, sc in enumerate(scenarios):
            self.emit("B %d" % i)
            self.reset()
            for ln in sc:
                self.emit("> " + ln[:40])
                self.op(ln.split())
        return self.out


# ================================================================ the build


def build_harness(tmp, name="playercam_test"):
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


# ============================================================ the mutations


def M(name, rel, before, after=None):
    return (name, rel, before, after)


MUTATIONS = [
    # ChangeCameraMover: the coordinators
    M("chg_no_demo_del", PCC,
      "            gCameraCoordinatorDeleteFn(p->pDemoCameraCoordinator);\n", "        ;\n"),
    M("chg_demo_kept", PCC, "        p->pDemoCameraCoordinator = NULL;\n    }\n"
      "    if (p->pCountdownCameraCoordinator", "    }\n"
      "    if (p->pCountdownCameraCoordinator"),
    M("chg_no_count_del", PCC,
      "            gCameraCoordinatorDeleteFn(p->pCountdownCameraCoordinator);\n",
      "        ;\n"),
    M("chg_count_kept", PCC, "        p->pCountdownCameraCoordinator = NULL;\n",
      ""),
    M("chg_no_nis_del", PCC,
      "            gNisDeleteCameraCoordinatorFn(p->pNisManager,\n"
      "                                          p->pNisCameraCoordinator);\n",
      "        ;\n"),
    M("chg_nis_kept", PCC, "        p->pNisCameraCoordinator = NULL;\n", ""),
    M("chg_nis_mgr", PCC,
      "            gNisDeleteCameraCoordinatorFn(p->pNisManager,",
      "            gNisDeleteCameraCoordinatorFn(NULL,"),
    # ChangeCameraMover: the old mover
    M("chg_same_rebuilds", PCC,
      "    if (old != NULL && old->Type == type)\n        return;\n", ""),
    M("chg_same_before_coords", PCC,
      "    if (p->pDemoCameraCoordinator != NULL) {\n        if (gCameraCoordinatorDeleteFn != NULL)\n"
      "            gCameraCoordinatorDeleteFn(p->pDemoCameraCoordinator);",
      "    if (p->pCameraMover != NULL && p->pCameraMover->Type == type)\n        return;\n"
      "    if (p->pDemoCameraCoordinator != NULL) {\n        if (gCameraCoordinatorDeleteFn != NULL)\n"
      "            gCameraCoordinatorDeleteFn(p->pDemoCameraCoordinator);"),
    M("chg_car_always_world", PCC, "    if (car == NULL)\n        car = (struct Car *)",
      "    if (1)\n        car = (struct Car *)"),
    M("chg_car_never_world", PCC, "    if (car == NULL)\n        car = (struct Car *)",
      "    if (0)\n        car = (struct Car *)"),
    M("chg_car_world_prev", PCC, "pCurrentWorld->CarList.next;",
      "pCurrentWorld->CarList.prev;"),
    M("chg_keep_ignored", PCC, "        if (keep) {", "        if (0) {"),
    M("chg_keep_always", PCC, "        if (keep) {", "        if (1) {"),
    M("chg_keep_no_saved2", PCC,
      "            p->pSavedCameraMover2 = p->pSavedCameraMover;\n", ""),
    M("chg_keep_order", PCC,
      "            p->pSavedCameraMover2 = p->pSavedCameraMover;\n"
      "            p->pSavedCameraMover = old;\n",
      "            p->pSavedCameraMover = old;\n"
      "            p->pSavedCameraMover2 = p->pSavedCameraMover;\n"),
    M("chg_keep_no_disable", PCC, "            old->vtbl->Disable(old);\n", ""),
    M("chg_keep_enables", PCC, "            old->vtbl->Disable(old);",
      "            old->vtbl->Enable(old);"),
    M("chg_no_clear", PCC, "        }\n        p->pCameraMover = NULL;\n    }",
      "        }\n    }"),
    # the drive camera
    M("drv_size", PCC, "bMalloc((int)sizeof(DriveCameraMover),",
      "bMalloc((int)sizeof(DriveCameraMover) + 16,"),
    M("drv_name", PCC, "\"DriveCameraMover(Player)\"", "\"DriveCameraMover\""),
    M("drv_pool", PCC, "\"DriveCameraMover(Player)\", 0, 16);",
      "\"DriveCameraMover(Player)\", 0, 0);"),
    M("drv_view", PCC, "        drive_cam_init(d, p->ViewID, car,",
      "        drive_cam_init(d, 0, car,"),
    M("drv_car", PCC, "        drive_cam_init(d, p->ViewID, car,",
      "        drive_cam_init(d, p->ViewID, p->MyCar,"),
    M("drv_pov", PCC,
      "        drive_cam_init(d, p->ViewID, car,\n"
      "                       p->PlayerSettings.DriveCameraPOVIndex,",
      "        drive_cam_init(d, p->ViewID, car,\n                       0,"),
    M("drv_speed", PCC, "#define PLAYER_LOOKBACK_SPEED 300.9f",
      "#define PLAYER_LOOKBACK_SPEED 300.0f"),
    M("drv_spring", PCC, "                       p->PlayerSettings.CameraSpring, 0, 1);",
      "                       0, 0, 1);"),
    M("drv_lookback", PCC, "                       p->PlayerSettings.CameraSpring, 0, 1);",
      "                       p->PlayerSettings.CameraSpring, 1, 1);"),
    M("drv_focus", PCC, "                       p->PlayerSettings.CameraSpring, 0, 1);",
      "                       p->PlayerSettings.CameraSpring, 0, 0);"),
    M("drv_no_lb", PCC, "        d->DesiredLookBackParam = look_back_param(p);\n", ""),
    M("lb_inverted", PCC, "    return p->bLookBack ? 1.0f : 0.0f;",
      "    return p->bLookBack ? 0.0f : 1.0f;"),
    M("lb_one", PCC, "    return p->bLookBack ? 1.0f : 0.0f;",
      "    return p->bLookBack == 1 ? 1.0f : 0.0f;"),
    M("drv_no_store", PCC,
      "        p->PlayerSettings.DriveCameraPOVIndex =\n            (int8_t)player_cycle_drive_camera_pov_index(",
      "        (void)player_cycle_drive_camera_pov_index("),
    M("drv_cycle_zero", PCC,
      "                p, p->PlayerSettings.DriveCameraPOVIndex);",
      "                p, 0);"),
    # The cycle before the player has the camera, so it finds none.
    M("drv_cycle_unset", PCC, [
        ("        p->pCameraMover = &d->base;\n        d->DesiredLookBackParam",
         "        d->DesiredLookBackParam"),
        ("                p, p->PlayerSettings.DriveCameraPOVIndex);\n        break;",
         "                p, p->PlayerSettings.DriveCameraPOVIndex);\n"
         "        p->pCameraMover = &d->base;\n        break;")]),
    # the seams' cases
    M("dw_z", PCC, "            pos.z += 4.0f;", "            pos.z += 3.0f;"),
    M("dw_y", PCC, "            pos.z += 4.0f;", "            pos.y += 4.0f;"),
    M("dw_dir", PCC, "bVector3 dir = {0.0f, 0.0f, 1.0f, 0.0f};",
      "bVector3 dir = {0.0f, 1.0f, 0.0f, 0.0f};"),
    M("dw_size", PCC, "bMalloc(76, \"DebugWorldCameraMover\"",
      "bMalloc(80, \"DebugWorldCameraMover\""),
    M("dw_name", PCC, "\"DebugWorldCameraMover\"", "\"DebugWorldMover\""),
    M("joy_port", PCC, "#define PLAYER_CAM_JOY_PORT 1", "#define PLAYER_CAM_JOY_PORT 0"),
    M("tre_size", PCC, "bMalloc(44,", "bMalloc(48,"),
    M("tre_name", PCC, "\"TrackRouteEditorCameraMover\"", "\"TrackRouteEditor\""),
    M("zf_size", PCC, "bMalloc(872,", "bMalloc(876,"),
    M("zf_saved2", PCC, "                mem, p->ViewID, car, p->pSavedCameraMover);",
      "                mem, p->ViewID, car, p->pSavedCameraMover2);"),
    M("zf_car", PCC, "                mem, p->ViewID, car, p->pSavedCameraMover);",
      "                mem, p->ViewID, p->MyCar, p->pSavedCameraMover);"),
    M("zp_size", PCC, "bMalloc(1104,", "bMalloc(1100,"),
    M("zp_route", PCC, "                mem, p->ViewID, p->pRoute, &car->State.Position);",
      "                mem, p->ViewID, NULL, &car->State.Position);"),
    M("zp_pos", PCC, "                mem, p->ViewID, p->pRoute, &car->State.Position);",
      "                mem, p->ViewID, p->pRoute, &car->State.GeometryPosition);"),
    M("zp_no_routedel", PCC, "                gPreviewRouteDeleteFn(p->pRoute);\n", "        ;\n"),
    M("zp_route_kept", PCC, "            p->pRoute = NULL;\n", ""),
    M("jump_second", PCC, "                p, car, type == CM_ZONE_JUMPER2);",
      "                p, car, type == CM_ZONE_JUMPER);"),
    M("jump_car", PCC, "                p, car, type == CM_ZONE_JUMPER2);",
      "                p, p->MyCar, type == CM_ZONE_JUMPER2);"),
    M("jump2_orbits", PCC, "    case CM_ZONE_JUMPER:\n    case CM_ZONE_JUMPER2:\n",
      "    case CM_ZONE_JUMPER:\n"),
    M("cubic_size", PCC, "bMalloc(160,", "bMalloc(164,"),
    M("cubic_car", PCC, "            p->pCameraMover = gCubicCameraMoverFn(mem, p->ViewID, car);",
      "            p->pCameraMover = gCubicCameraMoverFn(mem, p->ViewID, p->MyCar);"),
    M("cubic_orbits", PCC, "    case CM_CUBIC_DAMPER:\n", "    case 99:\n"),
    M("freeze_orbits", PCC, "    case CM_ZONE_FREEZE:\n", "    case 98:\n"),
    M("none_orbits", PCC, "    case CM_NONE:\n        break;\n", ""),
    M("orb_size", PCC, "bMalloc((int)sizeof(OrbitCarCameraMover),",
      "bMalloc((int)sizeof(OrbitCarCameraMover) - 8,"),
    M("orb_name", PCC, "\"OrbitCarCameraMover\"", "\"OrbitCameraMover\""),
    M("orb_view", PCC, "        orbit_init(o, p->ViewID, car,", "        orbit_init(o, 1, car,"),
    M("orb_car", PCC, "        orbit_init(o, p->ViewID, car,", "        orbit_init(o, p->ViewID, p->MyCar,"),
    M("end_no_player", PCC, "        p->pCameraMover->pPlayer = p;\n", "        ;\n"),
    M("end_player_null", PCC, "        p->pCameraMover->pPlayer = p;",
      "        p->pCameraMover->pPlayer = NULL;"),
    # the POV cycle
    M("cyc_mask", PCC, "    index %= 4;\n", "    index &= 3;\n"),
    M("cyc_no_mod", PCC, "    index %= 4;\n", ""),
    M("cyc_no_type", PCC, "    if (m == NULL || m->Type != CM_DRIVE || m->vtbl",
      "    if (m == NULL || m->vtbl"),
    M("cyc_no_info", PCC, " || m->vtbl->GetCameraInfo(m) == NULL)\n        return index;",
      ")\n        return index;"),
    M("cyc_tries3", PCC, "    for (tries = 0; tries < 4; tries++) {",
      "    for (tries = 0; tries < 3; tries++) {"),
    M("cyc_fallback3", PCC, "    if (tries == 4)\n        index = 0;",
      "    if (tries == 3)\n        index = 0;"),
    M("cyc_no_fallback", PCC, "    if (tries == 4)\n        index = 0;\n", ""),
    M("cyc_fallback_one", PCC, "    if (tries == 4)\n        index = 0;",
      "    if (tries == 4)\n        index = 1;"),
    M("cyc_skip_ignored", PCC, "            && ((gPlayerCamSkipFE != NULL && *gPlayerCamSkipFE)",
      "            && ((0)"),
    M("cyc_dash_ignored", PCC, "                || p->MyCar->pRideInfo->HasDash\n", ""),
    M("cyc_bumper", PCC, "|| pov->Type == POV_BUMPER ", "|| pov->Type == POV_INCAR "),
    M("cyc_outside", PCC, "|| pov->Type == POV_OUTSIDE))",
      "|| pov->Type == 3))"),
    M("cyc_step", PCC, "        index = (index + 1) % 4;", "        index = (index + 3) % 4;"),
    M("cyc_step_mask", PCC, "        index = (index + 1) % 4;", "        index = (index + 1) & 3;"),
    M("cyc_no_set", PCC,
      "    drive_cam_set_pov_index((DriveCameraMover *)p->pCameraMover, index);\n", ""),
    # RestoreCameraMover
    M("rst_no_delete", PCC,
      "    if (p->pCameraMover != NULL)\n        delete_mover(p->pCameraMover);\n    m = p->pSavedCameraMover;",
      "    m = p->pSavedCameraMover;"),
    M("rst_no_pop", PCC, "    p->pSavedCameraMover = p->pSavedCameraMover2;\n", ""),
    M("rst_saved2_kept", PCC, "    p->pSavedCameraMover2 = NULL;\n    if (m != NULL && m->Type",
      "    if (m != NULL && m->Type"),
    M("rst_lb_any", PCC, "    if (m != NULL && m->Type == CM_DRIVE)\n",
      "    if (m != NULL)\n"),
    M("rst_no_lb", PCC,
      "        ((DriveCameraMover *)m)->DesiredLookBackParam = look_back_param(p);\n", "        ;\n"),
    M("rst_no_enable", PCC, "    if (m != NULL)\n        m->vtbl->Enable(m);\n", ""),
    M("rst_disables", PCC, "        m->vtbl->Enable(m);\n}", "        m->vtbl->Disable(m);\n}"),
    # RemoveCameraMovers
    M("rm_keep", PCC, "    player_change_camera_mover(p, CM_NONE, 0);",
      "    player_change_camera_mover(p, CM_NONE, 1);"),
    M("rm_saved_left", PCC,
      "        delete_mover(p->pSavedCameraMover);\n        p->pSavedCameraMover = NULL;\n",
      "        delete_mover(p->pSavedCameraMover);\n"),
    M("rm_saved_kept", PCC,
      "        delete_mover(p->pSavedCameraMover);\n        p->pSavedCameraMover = NULL;\n",
      "        p->pSavedCameraMover = NULL;\n"),
    M("rm_saved2_kept", PCC,
      "        delete_mover(p->pSavedCameraMover2);\n", ""),
    M("rm_saved2_left", PCC, "        p->pSavedCameraMover2 = NULL;\n    }\n}", "    }\n}"),
    # the deleting destructor
    M("del_no_destroy", PCC, "    m->vtbl->Destroy(m);\n    bFree(m);", "    bFree(m);"),
    M("del_no_free", PCC, "    m->vtbl->Destroy(m);\n    bFree(m);", "    m->vtbl->Destroy(m);"),
    # Enable and Disable
    M("en_no_cur", PCC, "        p->pCameraMover->vtbl->Enable(p->pCameraMover);\n", "        ;\n"),
    M("en_no_rvm", PCC, "        p->pRVMCameraMover->vtbl->Enable(p->pRVMCameraMover);\n", "        ;\n"),
    M("en_no_demo", PCC, "        gCameraCoordinatorEnableFn(p->pDemoCameraCoordinator);\n", "        ;\n"),
    M("en_no_count", PCC, "        gCameraCoordinatorEnableFn(p->pCountdownCameraCoordinator);\n", "        ;\n"),
    M("en_no_nis", PCC,
      "        gNisEnableCameraCoordinatorFn(p->pNisManager,\n"
      "                                      p->pNisCameraCoordinator);\n", "        ;\n"),
    M("en_no_line", PCC, "        gVisibleDrivingLineEnableFn(p->pVisibleDrivingLine);\n", "        ;\n"),
    M("en_line_disables", PCC, "        gVisibleDrivingLineEnableFn(p->pVisibleDrivingLine);",
      "        gVisibleDrivingLineDisableFn(p->pVisibleDrivingLine);"),
    M("en_order", PCC,
      "    if (p->pCameraMover != NULL)\n        p->pCameraMover->vtbl->Enable(p->pCameraMover);\n"
      "    if (p->pRVMCameraMover != NULL)\n        p->pRVMCameraMover->vtbl->Enable(p->pRVMCameraMover);\n",
      "    if (p->pRVMCameraMover != NULL)\n        p->pRVMCameraMover->vtbl->Enable(p->pRVMCameraMover);\n"
      "    if (p->pCameraMover != NULL)\n        p->pCameraMover->vtbl->Enable(p->pCameraMover);\n"),
    M("dis_no_cur", PCC, "        p->pCameraMover->vtbl->Disable(p->pCameraMover);\n", "        ;\n"),
    M("dis_no_rvm", PCC, "        p->pRVMCameraMover->vtbl->Disable(p->pRVMCameraMover);\n", "        ;\n"),
    M("dis_no_demo", PCC, "        gCameraCoordinatorDisableFn(p->pDemoCameraCoordinator);\n", "        ;\n"),
    M("dis_no_count", PCC, "        gCameraCoordinatorDisableFn(p->pCountdownCameraCoordinator);\n", "        ;\n"),
    M("dis_no_nis", PCC,
      "        gNisDisableCameraCoordinatorFn(p->pNisManager,\n"
      "                                       p->pNisCameraCoordinator);\n", "        ;\n"),
    M("dis_no_line", PCC, "        gVisibleDrivingLineDisableFn(p->pVisibleDrivingLine);\n", "        ;\n"),
    M("dis_rvm_enables", PCC, "        p->pRVMCameraMover->vtbl->Disable(p->pRVMCameraMover);",
      "        p->pRVMCameraMover->vtbl->Enable(p->pRVMCameraMover);"),
]

# Mutants that cannot change what either side computes, each with why.
EQUIVALENT = {
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    hostbuild.recover()
    m = Model()
    sc = script()
    base = m.run(sc)
    caught, survived, missing, equivalent = 0, [], [], []
    scdir = tempfile.TemporaryDirectory()
    scp = Path(scdir.name) / "scenarios.txt"
    scp.write_text(encode(sc))
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, scp, out)
        if diff(base, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for mut in todo:
        name, rel, before, after = mut
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        edits = before if isinstance(before, list) else [(before, after)]
        new, bad = text, None
        for b, a in edits:
            probe = b.replace(NL, "\r\n") if crlf else b
            repl = a.replace(NL, "\r\n") if crlf else a
            if new.count(probe) != 1:
                bad = "NOT FOUND" if not new.count(probe) else "NOT UNIQUE"
                break
            new = new.replace(probe, repl, 1)
        if bad:
            missing.append(name)
            print("  %-44s PATTERN %s" % (name, bad))
            continue
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
    scdir.cleanup()

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

    m = Model()
    sc = script()
    lines = m.run(sc)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = Path(tmp) / "scenarios.txt"
        scp.write_text(encode(sc))
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(lines, harness)
    ops = sum(len(s) for s in sc)
    print("%d scenarios, %d ops, %d lines, %d differ"
          % (len(sc), ops, len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
