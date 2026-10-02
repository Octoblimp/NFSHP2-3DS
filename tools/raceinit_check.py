#!/usr/bin/env python3
"""Cross-check 3DS Files/source/raceinit.c, the cars and the players a race
starts with, against the retail image itself, run in mipsemu.

The model is the image. CalculateRacerPositions (0x0014a020), AddRacingCar
(0x00149f10), RaceCoordinator::InitCars (0x0014a2c8) and InitPlayers
(0x00149cb8) run as shipped, and so do bStringHash, RaceParameters::
GetDriverInfo, NearestRoutePointInfo::IsValid and TrackPathCoordinate's
destructor under them. The harness (tools/src/raceinit_test.c) runs the
port over the same script, and the two transcripts are diffed.

Everything else under them is a stub that prints its arguments: bMalloc,
bPNode::Malloc, TrackPathCoordinate's two constructors and
UpdatePosition(along, side), TopologyCoordinate's constructor, destructor
and GetElevation, bATan, GetNumTrackPositionMarkers, GetTrackPositionMarker,
GetTrackInfo, Car's constructor, SetControlMode and SetMovementMode,
World's BuildCarTable, GetCarByNumber and AddTrafficCar, AddCopCarToRace,
Chopper's constructor and Player::InitForRace. A car's controller has a
fake vtable whose FindWhereIAm, GetCurrentRoute, GetCurrentRoutePoint and
SetCurrentRoute slots print too, two of them with a this-delta of 4.

The track path, the ground and bATan answer from mix(), a hash of their
arguments that the harness computes the same way. BuildCarTable fills the
table from CarList as it stands, the players' cars first, then the AI
racers', then the rest, so a broken link shows in the table as well as in
the walks the dump makes both ways along CarList and AICarList.

The script lays out the rest at retail's offsets: the World (gp-22120),
twelve 24-byte DriverInfos at TheRaceParameters+772, two Players, four
TrackRoutes in TheTrackRouteManager's slots, the two starting-marker lists,
the track info's OverrideStartingRouteForAI, the egg table at
*(0x0031d7f4), nDefaultMovementMode (gp-22960), and the player tables. The
model zeroes the stack before each call, so the NearestRoutePointInfo
InitCars leaves unset without an override reads 0, as the port's does.

Before the run, DriverInfo and RacerStartLocation are asserted in an ARM
compile of raceinit.h, when devkitARM is there.

    python tools/raceinit_check.py
    python tools/raceinit_check.py --mutate [--only a,b]
    python tools/raceinit_check.py --dump out/raceinit
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

HARNESS = "tools/src/raceinit_test.c"
RIN = "3DS Files/source/raceinit.c"
RIH = "3DS Files/source/raceinit.h"
RCE = "3DS Files/source/race.c"
SOURCES = [HARNESS, RIN, RCE, "3DS Files/source/airoute.c",
           "3DS Files/source/vtable.c"]

HARNESS_TIMEOUT = 120

ARM_GCC = Path("C:/devkitPro/devkitARM/bin/arm-none-eabi-gcc.exe")
CTRU_INCLUDE = Path("C:/devkitPro/libctru/include")

# ================================================================ the image

GP = 0x003358f0
CALC = 0x0014a020
ADD = 0x00149f10
INIT_CARS = 0x0014a2c8
INIT_PLAYERS = 0x00149cb8

B_MALLOC = 0x002577c0
PNODE_MALLOC = 0x00250680
TPC_CTOR = 0x002086b8
TPC_CTOR_AT = 0x002086f0
TPC_MOVE = 0x00208820
TPC_DTOR = 0x00208748
TOPO_CTOR = 0x00151c28
TOPO_DTOR = 0x00151c70
GET_ELEV = 0x00152070
B_ATAN = 0x0025a890
NUM_MARKERS = 0x001513c8
GET_MARKER = 0x00151408
GET_TRACK_INFO = 0x00153420
CAR_CTOR = 0x00130a48
SET_CONTROL = 0x00131410
SET_MOVEMENT = 0x00131618
BUILD_TABLE = 0x0014d338
BY_NUMBER = 0x0014d508
ADD_TRAFFIC = 0x0014e580
ADD_COP = 0x00227d78
CHOPPER = 0x001e7a90
INIT_FOR_RACE = 0x00181920

G_WORLD = GP - 22120
G_MMODE = GP - 22960
G_NUM = GP - 20920
G_BY_INDEX = GP - 20928

RP = 0x0031a898
RP_TRACK = RP
RP_DIR = RP + 12
RP_AIDEMO = RP + 24
RP_BEACOP = RP + 628
RP_DRV = RP + 772
RP_NDRV = RP + 776

EGG_PTR = 0x0031d7f4
ROUTE_MGR = 0x00314438      # the route slots are at +16 + 4n
NSLOT = 100

W_HELI = 24
W_TOTAL = 28
W_AIPOS = 32
W_COPPOS = 36
W_TRAFFICPOS = 40
W_TABLE = 44
W_BYTES = 5936
MAX_CARS = 14

C_CTRL = 40
DRV_BYTES = 24
P_NUMBER = 16
ROUTE_POINTS = 1064
POINT_BYTES = 112
TI_OVERRIDE = 124

VT_SET_ROUTE = 40
VT_GET_ROUTE = 48
VT_GET_POINT = 56
VT_FIND = 72
VT_ENTRIES = 14

NOBJ = 256
OBJ_BYTES = 4096
APOOL = 0x01000000
MISC = APOOL + NOBJ * OBJ_BYTES
WORLD = MISC
DRIVERS = MISC + 0x2000
NDRV = 12
PLAYERS = MISC + 0x2200
PLAYER_STRIDE = 0x100
NPLAYER = 2
NODES = MISC + 0x2400
NNODE = 256
CTRLS = MISC + 0x3400
FAKE_VT = MISC + 0x4400
BUF = MISC + 0x4500
NBUF = 9
MARKERS = MISC + 0x4600
NMARK = 16
TRACKINFO = MISC + 0x4a00
EGGS = MISC + 0x4b00
STUBS = MISC + 0x4d00       # the fake functions, eight bytes apart
ROUTES = 0x01200000
ROUTE_STRIDE = 0x20000
NROUTE = 4

PATTERN = 0xa5

MARKER_NAMES = ("ForwardStartingPosition", "BackwardStartingPosition")


def bstring_hash(s):
    h = 0xffffffff
    for ch in s.encode("latin-1"):
        h = (h * 33 + ch) & M32
    return h


MARKER_HASHES = tuple(bstring_hash(n) for n in MARKER_NAMES)


def arm_layout_check():
    """DriverInfo and RacerStartLocation in an ARM compile of raceinit.h.
    Returns 0 when they hold or devkitARM is not there."""
    if not ARM_GCC.exists():
        print("devkitARM not found; the ARM layout check is skipped")
        return 0
    lines = [
        "#include <stddef.h>",
        "#include \"raceinit.h\"",
        "_Static_assert(sizeof(RacerStartLocation) == 16, \"rsl\");",
        "_Static_assert(offsetof(DriverInfo, StartingPosition) == 3, \"pos\");",
        "_Static_assert(offsetof(DriverInfo, TheDriverType) == 4, \"type\");",
        "_Static_assert(offsetof(DriverInfo, EliminatedRank) == 20, \"rank\");",
        "_Static_assert(sizeof(DriverInfo) == 24, \"size\");",
    ]
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "raceinit_layout.c"
        src.write_text(NL.join(lines) + NL)
        r = subprocess.run(
            [str(ARM_GCC), "-fsyntax-only", "-march=armv6k", "-mtune=mpcore",
             "-mfloat-abi=hard", "-std=c11", "-I",
             str(ROOT / "3DS Files/source"), "-I", str(CTRU_INCLUDE),
             str(src)],
            capture_output=True, text=True)
    if r.returncode != 0:
        print("the ARM layout check failed:")
        print((r.stderr or r.stdout)[:3000])
        return 1
    print("ARM layout: DriverInfo is 24 bytes with EliminatedRank at 20, "
          "RacerStartLocation 16")
    return 0


def fx(w):
    """A float's bits, with every NaN the one "nan"."""
    w &= M32
    if (w & 0x7f800000) == 0x7f800000 and (w & 0x7fffff):
        return "nan"
    return "%08x" % w


def mixw(a, b, salt, seed):
    h = (a * 0x9e3779b1 + b * 0x85ebca77 + salt * 0xc2b2ae3d
         + seed * 0x27d4eb2f) & M32
    return h ^ (h >> 15)


def mixf(a, b, salt, seed):
    h = mixw(a, b, salt, seed)
    return (h & 0x807fffff) | ((120 + ((h >> 23) & 15)) << 23)


def obj_at(i):
    return APOOL + OBJ_BYTES * i


def driver_at(i):
    return DRIVERS + DRV_BYTES * i


def player_at(i):
    return PLAYERS + PLAYER_STRIDE * i


def route_at(r):
    return ROUTES + ROUTE_STRIDE * r


def point_at(r, k):
    return route_at(r) + ROUTE_POINTS + POINT_BYTES * k


def marker_at(lst, j):
    return MARKERS + 24 * (NMARK * lst + j)


# ============================================================ the scenarios


def rbits(rnd):
    k = rnd.random()
    if k < 0.08:
        return rnd.choice((0x00000000, 0x80000000, 0x3f800000, 0xc2c80000,
                           0x7f7fffff, 0x00800000))
    return f_to_bits(rnd.uniform(-900.0, 900.0))


def h(w):
    return "0x%08x" % (w & M32)


def s_markers(rnd, n):
    """Markers for one or both lists: every slot of the first n, in any
    order, sometimes with a slot left out, a duplicate or extras."""
    out = []
    for lst in (0, 1):
        kind = rnd.choice(("full", "full", "missing", "dup", "few", "none",
                           "extra"))
        params = list(range(n))
        rnd.shuffle(params)
        if kind == "missing" and params:
            params.pop(rnd.randrange(len(params)))
            params.append(rnd.choice((n, n + 3, -1)))
        elif kind == "dup" and params:
            params.insert(rnd.randrange(len(params) + 1),
                          rnd.choice(params))
        elif kind == "few":
            params = params[:rnd.randrange(max(1, n))]
        elif kind == "none":
            params = []
        elif kind == "extra":
            params += [rnd.choice((n, 9, 11, -2))
                       for _ in range(rnd.randrange(1, 4))]
            rnd.shuffle(params)
        params = params[:NMARK]
        out.append("K %d %d" % (lst, len(params)))
        for j, p in enumerate(params):
            out.append("M %d %d %d %s %s" % (lst, j, p, h(rbits(rnd)),
                                            h(rbits(rnd))))
    return out


def s_buf(rnd):
    return ["L %d %s %s %s" % (k, h(rbits(rnd)), h(rbits(rnd)),
                               h(rbits(rnd))) for k in range(NBUF)]


def s_positions(rnd):
    """CalculateRacerPositions on its own: the markers in each direction,
    every shape of list, and the fallback; n from -1 to 8."""
    out = []
    for case in range(60):
        n = rnd.choice((8, 8, 8, 1, 2, 3, 5, 7, 0, -1))
        out.append("S dir %d" % rnd.choice((0, 1, 1, 2, -1)))
        out.append("S seed %d" % rnd.randrange(1 << 16))
        out += s_markers(rnd, max(n, 0))
        if rnd.random() < 0.5:
            out += s_buf(rnd)
        out.append("C %d" % n)
    return out


def s_add(rnd):
    """AddRacingCar on its own, under every control mode, and with
    nDefaultMovementMode left alone and changed."""
    out = []
    for case in range(50):
        if rnd.random() < 0.3:
            out += s_buf(rnd)
        if rnd.random() < 0.2:
            out.append("S mmode %d" % rnd.choice((0, 1, 2, 3, 5, 6)))
        if rnd.random() < 0.2:
            out.append("S seed %d" % rnd.randrange(1 << 16))
        out.append("A %d %d %d" % (rnd.randrange(NDRV),
                                   rnd.choice((1, 2, 2, 0, 3, 4)),
                                   rnd.randrange(NBUF)))
    return out


RANKS = (0, 0, 0, 0, -91, 1, 2, -1, 127, -128)
TYPES = (1, 2, 2, 2, 2, 3, 3, 4, 5, 0, 6, -1, 7)


def s_drivers(rnd):
    out = []
    n = rnd.choice((0, 1, 3, 6, 8, 8, 10, 12, 12))
    out.append("S ndrv %d" % n)
    order = list(range(1, 9))
    rnd.shuffle(order)
    for i in range(NDRV):
        if rnd.random() < 0.75 and order:
            pos = order.pop()
        else:
            pos = rnd.choice((0, 9, -1, 1, 4, 8, 120))
        out.append("D %d %d %d %d %d" % (i, rnd.choice(RANKS),
                                         rnd.randrange(-2, 16), pos,
                                         rnd.choice(TYPES)))
    return out


def s_routes(rnd):
    """The route slots, the routes' numbers and points, the override and
    what the first AI racer's controller answers."""
    out = []
    for r in range(NROUTE):
        out.append("P %d %d %d" % (r, rnd.choice((0, 5, 69, 70, -1, 30)),
                                   rnd.choice((0, 1, 10, 10, 1000))))
    for _ in range(rnd.randrange(1, 6)):
        out.append("R %d %d" % (rnd.choice((0, 1, 2, 7, 42, 99)),
                                rnd.randrange(-1, NROUTE)))
    out.append("S override %d" % rnd.choice((-1, -1, 0, 1, 2, 7, 42, 99,
                                             -5)))
    out.append("F %d %d %d" % (rnd.randrange(-1, NROUTE),
                               rnd.randrange(-1, NROUTE),
                               rnd.choice((-1, 0, 3, 9))))
    return out


def s_grid(rnd, n):
    """InitCars over random driver tables, routes, eggs and Be A Cop,
    several to a scenario so the lists grow."""
    out = []
    for case in range(n):
        if rnd.random() < 0.6:
            out += s_drivers(rnd)
        if rnd.random() < 0.6:
            out += s_routes(rnd)
        if rnd.random() < 0.4:
            out += s_markers(rnd, 8)
        if rnd.random() < 0.3:
            out.append("E %d %d" % (rnd.choice((5, 5, 4, 6, 0)),
                                    rnd.choice((0, 1, -1, 0x100))))
        if rnd.random() < 0.3:
            out.append("S beacop %d" % rnd.choice((0, 1, 2)))
        if rnd.random() < 0.2:
            out.append("S dir %d" % rnd.choice((0, 1)))
        if rnd.random() < 0.2:
            out.append("S track %d" % rnd.randrange(-1, 40))
        if rnd.random() < 0.15:
            out.append("S mmode %d" % rnd.choice((1, 4, 6)))
        if rnd.random() < 0.3:
            out.append("S seed %d" % rnd.randrange(1 << 16))
        out.append("I")
    return out


def s_players(rnd):
    """InitPlayers after InitCars: by number and, under AIDemoMode, from
    the table."""
    out = []
    for case in range(25):
        out.append("B-")
        out += s_drivers(rnd)
        out += s_routes(rnd)
        out.append("I")
        for _ in range(rnd.randrange(1, 4)):
            out.append("S nplay %d" % rnd.choice((0, 1, 2, 2)))
            out.append("S aidemo %d" % rnd.choice((0, 0, 1, 2)))
            for i in range(NPLAYER):
                out.append("Q %d %d" % (i, rnd.choice((0, 1, 1, 0, 2, 5,
                                                       -1, 15))))
            out.append("J")
    return out


def s_walk(rnd, n):
    out = []
    for _ in range(n):
        k = rnd.random()
        if k < 0.25:
            out += s_drivers(rnd)
        elif k < 0.4:
            out += s_routes(rnd)
        elif k < 0.5:
            out += s_markers(rnd, rnd.choice((8, 8, 3)))
        elif k < 0.6:
            out.append("A %d %d %d" % (rnd.randrange(NDRV),
                                       rnd.choice((1, 2, 3)),
                                       rnd.randrange(NBUF)))
        elif k < 0.7:
            out.append("C %d" % rnd.choice((8, 4, 1)))
        elif k < 0.85:
            out.append("I")
        else:
            out.append("S nplay %d" % rnd.choice((1, 2)))
            out.append("S aidemo %d" % rnd.choice((0, 1)))
            out.append("Q %d %d" % (rnd.randrange(NPLAYER),
                                    rnd.choice((0, 1))))
            out.append("J")
    return out


def split(ops):
    """`B-` in a generator's ops starts a fresh scenario."""
    out, cur = [], []
    for ln in ops:
        if ln == "B-":
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(ln)
    if cur:
        out.append(cur)
    return out


def script():
    rnd = random.Random(0x8b1e2c07)
    sc = [s_positions(rnd), s_add(rnd)]
    for n in (4, 8, 12):
        sc.append(s_grid(rnd, n))
    sc += split(s_players(rnd))
    for n in (40, 80):
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
        self.nstub = 0
        for a, fn in ((B_MALLOC, self.s_malloc),
                      (PNODE_MALLOC, self.s_pnode),
                      (TPC_CTOR, self.s_tpc), (TPC_CTOR_AT, self.s_tpcat),
                      (TPC_MOVE, self.s_tpcmove),
                      (TOPO_CTOR, self.s_topo), (TOPO_DTOR, self.s_topodel),
                      (GET_ELEV, self.s_elev), (B_ATAN, self.s_atan),
                      (NUM_MARKERS, self.s_nmark), (GET_MARKER, self.s_mark),
                      (GET_TRACK_INFO, self.s_trackinfo),
                      (CAR_CTOR, self.s_car), (SET_CONTROL, self.s_ctl),
                      (SET_MOVEMENT, self.s_move),
                      (BUILD_TABLE, self.s_table),
                      (BY_NUMBER, self.s_bynum),
                      (ADD_TRAFFIC, self.s_traffic), (ADD_COP, self.s_cop),
                      (CHOPPER, self.s_chopper),
                      (INIT_FOR_RACE, self.s_ifr)):
            e.stub(a, fn)
        # TrackPathCoordinate's destructor runs: with flag 2 it returns.
        assert e.u32(TPC_DTOR) == 0x30a50001
        self.mmode0 = e.u32(G_MMODE)
        assert self.mmode0 == 4
        # The controllers' fake vtable.
        e.write(FAKE_VT, bytes(8 * VT_ENTRIES))
        for slot, delta, fn in ((VT_SET_ROUTE, 4, self.v_setroute),
                                (VT_GET_ROUTE, 0, self.v_getroute),
                                (VT_GET_POINT, 4, self.v_getpoint),
                                (VT_FIND, 0, self.v_find)):
            e.write(FAKE_VT + slot, struct.pack("<hh", delta, 0))
            e.put32(FAKE_VT + slot + 4, self.fake(fn))

        self.names = {0: "null", WORLD: "w"}
        for i in range(NOBJ):
            self.names[obj_at(i)] = "a%d" % i
            self.names[CTRLS + 16 * i] = "c%d" % i
            self.names[CTRLS + 16 * i + 4] = "c%d+4" % i
        for i in range(NNODE):
            self.names[NODES + 16 * i] = "n%d" % i
        for i in range(NDRV):
            self.names[driver_at(i)] = "d%d" % i
        for i in range(NPLAYER):
            self.names[player_at(i)] = "p%d" % i
        for i in range(NBUF):
            self.names[BUF + 16 * i] = "b%d" % i

    def fake(self, fn):
        a = STUBS + 8 * self.nstub
        self.nstub += 1
        self.e.stub(a, fn)
        return a

    def emit(self, s):
        self.out.append(s)

    def name(self, a):
        a &= M32
        n = self.names.get(a)
        if n is not None:
            return n
        if ROUTES <= a < ROUTES + NROUTE * ROUTE_STRIDE:
            r, off = divmod(a - ROUTES, ROUTE_STRIDE)
            if off == 0:
                return "r%d" % r
            off -= ROUTE_POINTS
            if 0 <= off < 1024 * POINT_BYTES and off % POINT_BYTES == 0:
                return "r%d.%d" % (r, off // POINT_BYTES)
        return "s"

    def arg(self, i):
        return self.e.reg[(4, 5, 6, 7, 8, 9, 10, 11)[i]] & M32

    def w(self, a):
        return self.e.u32(a)

    def fill(self, a, n, byte=PATTERN):
        self.e.write(a, bytes([byte]) * n)

    def cstr(self, a):
        b = bytearray()
        while self.e.mem[a]:
            b.append(self.e.mem[a])
            a += 1
        return b.decode("latin-1")

    def index_of(self, a):
        if APOOL <= a < MISC and (a - APOOL) % OBJ_BYTES == 0:
            return (a - APOOL) // OBJ_BYTES
        return None

    def mixf(self, a, b, salt):
        return mixf(a, b, salt, self.seed)

    # ---- the stubs -------------------------------------------------------

    def s_malloc(self, e):
        name = self.cstr(self.arg(1))
        if self.nobj >= NOBJ:
            raise SystemExit("arena full")
        i = self.nobj
        self.nobj += 1
        a = obj_at(i)
        self.fill(a, OBJ_BYTES)
        self.mode[i] = -1
        self.driver[i] = -1
        self.emit("  malloc %d %s %d %d -> %s"
                  % (s32(self.arg(0)), name, s32(self.arg(2)),
                     s32(self.arg(3)), self.name(a)))
        return a

    def s_pnode(self, e):
        if self.nnode >= NNODE:
            raise SystemExit("node pool full")
        a = NODES + 16 * self.nnode
        self.nnode += 1
        self.fill(a, 16)
        self.emit("  pnode -> %s" % self.name(a))
        return a

    def s_tpc(self, e):
        c = self.arg(0)
        self.emit("  tpc")
        self.fill(c, 40)
        e.put32(c, self.mixf(1, 0, 11))
        e.put32(c + 4, self.mixf(2, 0, 11))
        return c

    def s_tpcat(self, e):
        c, pos = self.arg(0), self.arg(1)
        x, y = self.w(pos), self.w(pos + 4)
        self.emit("  tpcat %s %s" % (fx(x), fx(y)))
        self.fill(c, 40)
        e.put32(c, x)
        e.put32(c + 4, y)
        e.put32(c + 20, self.mixf(x, y, 3))
        e.put32(c + 24, self.mixf(x, y, 4))
        e.put32(c + 28, self.mixf(x, y, 5))
        return c

    def s_tpcmove(self, e):
        c = self.arg(0)
        a, s = e.fpr[12] & M32, e.fpr[13] & M32
        self.emit("  tpcmove %s %s" % (fx(a), fx(s)))
        e.put32(c, self.mixf(a, s, 6 + 2 * self.ntpc))
        e.put32(c + 4, self.mixf(a, s, 7 + 2 * self.ntpc))
        self.ntpc += 1

    def s_topo(self, e):
        self.emit("  topo")
        self.topo_at = self.arg(0)
        return self.arg(0)

    def s_topodel(self, e):
        self.emit("  topodel %s"
                  % ("same" if self.arg(0) == self.topo_at else "other"))

    def s_elev(self, e):
        tc, pt = self.arg(0), self.arg(1)
        x, y, z = self.w(pt), self.w(pt + 4), self.w(pt + 8)
        r = self.mixf(x ^ z, y, 9)
        self.emit("  elev %s %s %s %s %d%d%d -> %s"
                  % ("same" if tc == self.topo_at else "other", fx(x), fx(y),
                     fx(z), self.arg(2) != 0, self.arg(3) != 0,
                     self.arg(4) != 0, fx(r)))
        e.fpr[0] = r

    def s_atan(self, e):
        x, y = e.fpr[12] & M32, e.fpr[13] & M32
        r = s32(mixw(x, y, 10, self.seed))
        self.emit("  atan %s %s -> %d" % (fx(x), fx(y), r))
        return r

    def s_nmark(self, e):
        hsh = self.arg(0)
        n = 0
        for k in range(2):
            if hsh == MARKER_HASHES[k]:
                n = self.nmarks[k]
        self.emit("  nmark %08x -> %d" % (hsh, n))
        return n

    def s_mark(self, e):
        hsh, i = self.arg(0), s32(self.arg(1))
        for k in range(2):
            if hsh == MARKER_HASHES[k] and 0 <= i < self.nmarks[k]:
                self.emit("  mark %08x %d -> m%d.%d" % (hsh, i, k, i))
                return marker_at(k, i)
        self.emit("  mark %08x %d -> null" % (hsh, i))
        return 0

    def s_trackinfo(self, e):
        self.emit("  trackinfo %d" % s32(self.arg(0)))
        return TRACKINFO

    def s_car(self, e):
        c, d, pos, angle = (self.arg(k) for k in range(4))
        self.emit("  car %s %s %s %s %s %s angle %d dist %s"
                  % (self.name(c), self.name(d), self.name(pos),
                     fx(self.w(pos)), fx(self.w(pos + 4)),
                     fx(self.w(pos + 8)), s32(angle), fx(e.fpr[12])))
        k = self.index_of(c)
        if k is None:
            raise SystemExit("a car outside the arena")
        di = None
        if DRIVERS <= d < DRIVERS + DRV_BYTES * NDRV \
                and (d - DRIVERS) % DRV_BYTES == 0:
            di = (d - DRIVERS) // DRV_BYTES
        self.driver[k] = -1 if di is None else di
        e.put32(CTRLS + 16 * k + 8, FAKE_VT)
        e.put32(c + C_CTRL, CTRLS + 16 * k)
        return c

    def s_ctl(self, e):
        c, m = self.arg(0), s32(self.arg(1))
        self.emit("  ctl %s %d" % (self.name(c), m))
        k = self.index_of(c)
        if k is not None:
            self.mode[k] = m

    def s_move(self, e):
        self.emit("  move %s %d" % (self.name(self.arg(0)),
                                    s32(self.arg(1))))

    def walk_cars(self, limit=64):
        out = []
        p = self.w(WORLD)
        while p != WORLD and len(out) < limit:
            out.append(p)
            p = self.w(p)
        return out

    def s_table(self, e):
        w = self.arg(0)
        self.emit("  table %s" % self.name(w))
        cars = self.walk_cars()
        table, np, nai = [], 0, 0
        for pas in range(3):
            for c in cars:
                m = self.mode[self.index_of(c)]
                want = (m == 1 if pas == 0 else m == 2 if pas == 1
                        else m not in (1, 2))
                if want and len(table) < MAX_CARS:
                    table.append(c)
                    if pas == 0:
                        np += 1
                    elif pas == 1:
                        nai += 1
        for i in range(MAX_CARS):
            e.put32(w + W_TABLE + 4 * i, table[i] if i < len(table) else 0)
        e.put32(w + W_TOTAL, len(table))
        e.put32(w + W_AIPOS, np)
        e.put32(w + W_COPPOS, np + nai)
        e.put32(w + W_TRAFFICPOS, np + nai)

    def s_bynum(self, e):
        w, n = self.arg(0), s32(self.arg(1))
        r = 0
        for c in self.walk_cars():
            d = self.driver[self.index_of(c)]
            if d >= 0:
                num = self.e.mem[driver_at(d) + 1]
                if (num - 256 if num > 127 else num) == n:
                    r = c
                    break
        self.emit("  bynum %s %d -> %s" % (self.name(w), n, self.name(r)))
        return r

    def s_traffic(self, e):
        self.emit("  traffic %s %s" % (self.name(self.arg(0)),
                                       self.name(self.arg(1))))

    def s_cop(self, e):
        self.emit("  cop %s %d" % (self.name(self.arg(0)),
                                   s32(self.arg(1))))

    def s_chopper(self, e):
        self.emit("  chopper %s" % self.name(self.arg(0)))
        return self.arg(0)

    def s_ifr(self, e):
        self.emit("  ifr %s %s" % (self.name(self.arg(0)),
                                   self.name(self.arg(1))))

    def v_find(self, e):
        self.emit("  find %s" % self.name(self.arg(0)))

    def v_getroute(self, e):
        self.emit("  getroute %s %d -> %s"
                  % (self.name(self.arg(0)), s32(self.arg(1)),
                     self.name(self.find_route)))
        return self.find_route

    def v_getpoint(self, e):
        self.emit("  getpoint %s %d -> %s"
                  % (self.name(self.arg(0)), s32(self.arg(1)),
                     self.name(self.find_point)))
        return self.find_point

    def v_setroute(self, e):
        self.emit("  setroute %s %s %s"
                  % (self.name(self.arg(0)), self.name(self.arg(1)),
                     self.name(self.arg(2))))

    # ---- the state -------------------------------------------------------

    def reset(self):
        e = self.e
        self.nobj = 0
        self.nnode = 0
        self.mode = [-1] * NOBJ
        self.driver = [-1] * NOBJ
        e.write(WORLD, bytes(W_BYTES))
        e.put32(WORLD, WORLD)
        e.put32(WORLD + 4, WORLD)
        e.put32(WORLD + 8, WORLD + 8)
        e.put32(WORLD + 12, WORLD + 8)
        e.put32(G_WORLD, WORLD)
        self.fill(DRIVERS, DRV_BYTES * NDRV)
        e.put32(RP_DRV, DRIVERS)
        e.put32(RP_NDRV, 0)
        e.put32(RP_TRACK, 1)
        e.put32(RP_DIR, 0)
        e.put32(RP_AIDEMO, 0)
        e.put32(RP_BEACOP, 0)
        e.put32(G_MMODE, self.mmode0)
        e.write(MARKERS, bytes(24 * NMARK * 2))
        self.nmarks = [0, 0]
        for r in range(NROUTE):
            e.write(route_at(r), bytes(ROUTE_POINTS))
        e.write(ROUTE_MGR + 16, bytes(4 * NSLOT))
        e.write(TRACKINFO, bytes(164))
        e.put32(TRACKINFO + TI_OVERRIDE, -1 & M32)
        self.fill(BUF, 16 * NBUF)
        e.put32(EGG_PTR, EGGS)
        e.write(EGGS, bytes(48 + 56 * 8))
        self.find_route = 0
        self.find_point = 0
        self.seed = 0
        self.ntpc = 0
        self.topo_at = None
        e.put32(G_NUM, 0)
        for i in range(NPLAYER):
            e.put32(G_BY_INDEX + 4 * i, player_at(i))
            e.put32(player_at(i) + P_NUMBER, i)

    def set_global(self, f, v):
        e = self.e
        regs = {"dir": RP_DIR, "track": RP_TRACK, "aidemo": RP_AIDEMO,
                "beacop": RP_BEACOP, "ndrv": RP_NDRV,
                "override": TRACKINFO + TI_OVERRIDE, "mmode": G_MMODE,
                "nplay": G_NUM}
        if f in regs:
            e.put32(regs[f], v & M32)
        elif f == "seed":
            self.seed = v & M32
        else:
            raise SystemExit("bad global %s" % f)

    # ---- the dump --------------------------------------------------------

    def dump(self):
        w = self.w
        cars = self.walk_cars()
        back = []
        p = w(WORLD + 4)
        while p != WORLD and len(back) < 64:
            back.append(p)
            p = w(p + 4)
        self.emit("  list" + "".join(" " + self.name(c) for c in cars)
                  + " |" + "".join(" " + self.name(c) for c in back))
        fwd = []
        p = w(WORLD + 8)
        while p != WORLD + 8 and len(fwd) < 64:
            fwd.append("%s:%s" % (self.name(p), self.name(w(p + 8))))
            p = w(p)
        back = []
        p = w(WORLD + 12)
        while p != WORLD + 8 and len(back) < 64:
            back.append(self.name(p))
            p = w(p + 4)
        self.emit("  ai" + "".join(" " + x for x in fwd) + " |"
                  + "".join(" " + x for x in back))
        self.emit("  heli %s total %d ai %d cop %d traffic %d"
                  % (self.name(w(WORLD + W_HELI)), s32(w(WORLD + W_TOTAL)),
                     s32(w(WORLD + W_AIPOS)), s32(w(WORLD + W_COPPOS)),
                     s32(w(WORLD + W_TRAFFICPOS))))
        self.emit("  carstable" + "".join(
            " " + self.name(w(WORLD + W_TABLE + 4 * i))
            for i in range(MAX_CARS)))
        for i in range(NBUF):
            a = BUF + 16 * i
            self.emit("  b%d %s %s %s %s" % (i, fx(w(a)), fx(w(a + 4)),
                                            fx(w(a + 8)), fx(w(a + 12))))

    # ---- the ops ---------------------------------------------------------

    def call(self, fn, *args):
        e = self.e
        sp = e.reg[29] & M32
        e.write(sp - 0x4000, bytes(0x4000))
        e.call(fn, *args, limit=2000000)

    def op(self, t):
        e = self.e
        c = t[0]
        if c == "S":
            self.set_global(t[1], int(t[2], 0))
            return
        n = [int(x, 0) for x in t[1:]]
        if c == "D":
            d = driver_at(n[0])
            e.mem[d] = n[1] & 0xff
            e.mem[d + 1] = n[2] & 0xff
            e.mem[d + 4] = n[3] & 0xff
            e.put32(d + 8, n[4] & M32)
            return
        if c == "K":
            self.nmarks[n[0]] = n[1]
            return
        if c == "M":
            m = marker_at(n[0], n[1])
            e.put32(m + 12, n[2] & M32)
            e.put32(m + 16, n[3])
            e.put32(m + 20, n[4])
            return
        if c == "R":
            e.put32(ROUTE_MGR + 16 + 4 * n[0],
                    0 if n[1] < 0 else route_at(n[1]))
            return
        if c == "P":
            e.write(route_at(n[0]) + 10, struct.pack("<h", n[1]))
            e.put32(route_at(n[0]) + 16, n[2] & M32)
            return
        if c == "F":
            self.find_route = 0 if n[0] < 0 else route_at(n[0])
            self.find_point = (0 if n[1] < 0 or n[2] < 0
                               else point_at(n[1], n[2]))
            return
        if c == "E":
            e.put32(EGGS + 48 + 56 * n[0], n[1] & M32)
            return
        if c == "Q":
            e.put32(player_at(n[0]) + P_NUMBER, n[1] & M32)
            return
        if c == "L":
            a = BUF + 16 * n[0]
            e.put32(a, n[1])
            e.put32(a + 4, n[2])
            e.put32(a + 8, n[3])
            return
        if c == "C":
            # Sign-extended, as the EE's 64-bit compares want it.
            self.call(CALC, n[0], BUF)
        elif c == "A":
            self.call(ADD, driver_at(n[0]), BUF + 16 * n[2], n[1] & M32)
        elif c == "I":
            self.call(INIT_CARS, 0)
        elif c == "J":
            self.call(INIT_PLAYERS, 0)
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


def build_harness(tmp, name="raceinit_test"):
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
    # CalculateRacerPositions: the markers
    M("crp_dir_flipped", RIN, "RaceParametersTrackDirection == TRACK_DIRECTION_FORWARD\n",
      "RaceParametersTrackDirection != TRACK_DIRECTION_FORWARD\n"),
    M("crp_name_forward", RIN, "? \"ForwardStartingPosition\"", "? \"ForwardStartingPositions\""),
    M("crp_name_backward", RIN, ": \"BackwardStartingPosition\");", ": \"ForwardStartingPosition\");"),
    M("crp_count_gt", RIN, "    if (count >= n) {", "    if (count > n) {"),
    M("crp_markers_unset", RIN, "        fromMarkers = 1;\n", "        fromMarkers = 0;\n"),
    M("crp_found_kept", RIN, [
        ("    int      found, fromMarkers = 0;", "    int      found = 0, fromMarkers = 0;"),
        ("            found = 0;\n            for (j = 0;", "            for (j = 0;")]),
    M("crp_j_from_one", RIN, "for (j = 0; j < count; j++) {", "for (j = 1; j < count; j++) {"),
    M("crp_param_off", RIN, "if (m->Param == i) {", "if (m->Param == i + 1) {"),
    M("crp_marker_x", RIN, "locs[i].Position.x = m->Position.x;", "locs[i].Position.x = m->Position.y;"),
    M("crp_marker_y", RIN, "locs[i].Position.y = m->Position.y;", "locs[i].Position.y = m->Position.x;"),
    M("crp_last_marker_wins", RIN,
      "                    locs[i].Position.y = m->Position.y;\n                    break;\n",
      "                    locs[i].Position.y = m->Position.y;\n"),
    M("crp_missing_spoils_nothing", RIN,
      "                fromMarkers = 0;\n                break;\n", "                break;\n"),
    M("crp_missing_goes_on", RIN,
      "                fromMarkers = 0;\n                break;\n", "                fromMarkers = 0;\n"),
    # CalculateRacerPositions: the fallback
    M("crp_no_tpc", RIN, "        trackpath_coord_init(&tpc);\n", ""),
    M("crp_step_9", RIN, "            d += 10.0f;\n", "            d += 9.0f;\n"),
    M("crp_steps_to_90", RIN, "} while (d < 100.0f);", "} while (d < 90.0f);"),
    M("crp_steps_to_110", RIN, "} while (d < 100.0f);", "} while (d <= 100.0f);"),
    M("crp_step_side", RIN, "trackpath_coord_update_position_along(&tpc, d, 0.0f);",
      "trackpath_coord_update_position_along(&tpc, d, 1.0f);"),
    M("crp_pair_16", RIN, "(float)(i / 2) * 17.0f + 100.0f", "(float)(i / 2) * 16.0f + 100.0f"),
    M("crp_pair_base", RIN, "(float)(i / 2) * 17.0f + 100.0f", "(float)(i / 2) * 17.0f + 90.0f"),
    M("crp_no_pairs", RIN, "(float)(i / 2) * 17.0f", "(float)i * 17.0f"),
    M("crp_side_swap", RIN, "(i & 1) ? -3.0f : 3.0f", "(i & 1) ? 3.0f : -3.0f"),
    M("crp_side_two", RIN, "(i & 1) ? -3.0f : 3.0f", "(i & 1) ? -3.0f : 2.0f"),
    M("crp_path_x", RIN, "            locs[i].Position.x = tpc.Position.x;",
      "            locs[i].Position.x = tpc.Position.y;"),
    M("crp_path_y", RIN, "            locs[i].Position.y = tpc.Position.y;",
      "            locs[i].Position.y = tpc.Position.x;"),
    # CalculateRacerPositions: the heights
    M("crp_no_topo", RIN, "    topology_init(&tc);\n", ""),
    M("crp_no_topo_destroy", RIN, "    topology_destroy(&tc);\n", ""),
    M("crp_z_seed_one", RIN, "    z = 0.0f;\n", "    z = 1.0f;\n"),
    M("crp_z_not_seeded", RIN,
      "        locs[i].Position.z = z;\n        z = topology_get_elevation",
      "        z = topology_get_elevation"),
    M("crp_z_not_stored", RIN,
      "        locs[i].Position.z = z;\n    }\n    topology_destroy",
      "    }\n    topology_destroy"),
    M("crp_elev_terrain", RIN, "&locs[i].Position, NULL, NULL, NULL);",
      "&locs[i].Position, &j, NULL, NULL);"),
    M("crp_heights_from_one", RIN,
      "    for (i = 0; i < n; i++) {\n        locs[i].Position.z = z;",
      "    for (i = 1; i < n; i++) {\n        locs[i].Position.z = z;"),
    # AddRacingCar
    M("add_tpc_no_position", RIN,
      "    trackpath_coord_init_at(&tpc,\n                            (const bVector2 *)(const void *)&loc->Position);",
      "    trackpath_coord_init(&tpc);"),
    M("add_atan_swapped", RIN, "bATan(tpc.PathDirection.x, tpc.PathDirection.y);",
      "bATan(tpc.PathDirection.y, tpc.PathDirection.x);"),
    M("add_heading_shifted", RIN, "heading = (uint16_t)bATan(tpc.PathDirection.x, tpc.PathDirection.y);",
      "heading = (uint16_t)(bATan(tpc.PathDirection.x, tpc.PathDirection.y) >> 1);"),
    M("add_malloc_name", RIN, "\"Car\", 0, CAR_MEMORY_POOL", "\"car\", 0, CAR_MEMORY_POOL"),
    M("add_malloc_flags", RIN, "\"Car\", 0, CAR_MEMORY_POOL", "\"Car\", 1, CAR_MEMORY_POOL"),
    M("add_malloc_pool", RIN, "\"Car\", 0, CAR_MEMORY_POOL", "\"Car\", 0, 0"),
    M("add_pos_null", RIN, "c = car_construct(c, info, &loc->Position, heading,",
      "c = car_construct(c, info, NULL, heading,"),
    M("add_angle_zero", RIN, "info, &loc->Position, heading,", "info, &loc->Position, 0,"),
    M("add_dist_zero", RIN, "                      tpc.DistanceAroundTrack);", "                      0.0f);"),
    M("add_control_fixed", RIN, "car_set_control_mode(c, mode);", "car_set_control_mode(c, REAL_CONTROL);"),
    M("add_ai_physics", RIN, "mode == AI_CONTROL ? nDefaultMovementMode",
      "mode == AI_CONTROL ? PHYSICS_MOVEMENT"),
    M("add_other_mellow", RIN, "                                                : PHYSICS_MOVEMENT);",
      "                                                : MELLOW_MOVEMENT);"),
    M("add_movement_test", RIN, "mode == AI_CONTROL ? nDefaultMovementMode",
      "mode != REAL_CONTROL ? nDefaultMovementMode"),
    M("add_list_from_head", RIN, "    tail = w->CarList.prev;\n", "    tail = w->CarList.next;\n"),
    M("add_list_tail_next", RIN, "    tail->Link.next = &c->Link;\n", ""),
    M("add_list_head_prev", RIN, "    w->CarList.prev = c;\n", ""),
    M("add_list_car_prev", RIN, "    c->Link.prev = &tail->Link;\n", ""),
    M("add_list_car_next", RIN, "    c->Link.next = (CarNode *)(void *)&w->CarList;\n", ""),
    M("add_ai_test", RIN, "    if (mode == AI_CONTROL) {\n        bPNode",
      "    if (mode != REAL_CONTROL) {\n        bPNode"),
    M("add_ai_from_head", RIN, "        bNode  *last = w->AICarList.prev;",
      "        bNode  *last = w->AICarList.next;"),
    M("add_ai_object", RIN, "        node->Object = c;\n", ""),
    M("add_ai_last_next", RIN, "        last->next = &node->Node;\n", ""),
    M("add_ai_head_prev", RIN, "        w->AICarList.prev = node;\n", ""),
    M("add_ai_node_next", RIN, "        node->Node.next = (bNode *)(void *)&w->AICarList;\n", ""),
    M("add_ai_node_prev", RIN, "        node->Node.prev = last;\n", ""),
    M("default_movement", RIN, "int32_t nDefaultMovementMode = MELLOW_MOVEMENT;",
      "int32_t nDefaultMovementMode = PHYSICS_MOVEMENT;"),
    # InitCars: the grid
    M("ic_grid_seven", RIH, "#define RACEINIT_GRID_SLOTS 8", "#define RACEINIT_GRID_SLOTS 7"),
    M("ic_positions_to_seven", RIN, "for (pos = 1; pos <= RACEINIT_GRID_SLOTS; pos++) {",
      "for (pos = 1; pos < RACEINIT_GRID_SLOTS; pos++) {"),
    M("ic_grid_drivers_short", RIN,
      "        for (i = 0; i < RaceParametersNumDriverInfo; i++) {\n            DriverInfo *d",
      "        for (i = 0; i < RaceParametersNumDriverInfo - 1; i++) {\n            DriverInfo *d"),
    M("ic_rank_ge", RIN, "if (d->EliminatedRank > 0 ||", "if (d->EliminatedRank >= 0 ||"),
    M("ic_rank_unsigned", RIN, "if (d->EliminatedRank > 0 ||", "if ((uint8_t)d->EliminatedRank > 0 ||"),
    M("ic_rank_ignored", RIN, "if (d->EliminatedRank > 0 || d->StartingPosition != pos)",
      "if (d->StartingPosition != pos)"),
    M("ic_position_off", RIN, "d->StartingPosition != pos)", "d->StartingPosition != pos - 1)"),
    M("ic_player_type", RIN, "if (d->TheDriverType == DRIVER_TYPE_PLAYER)",
      "if (d->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR)"),
    M("ic_ai_type", RIN, "else if (d->TheDriverType == DRIVER_TYPE_AI_RACER)",
      "else if (d->TheDriverType != DRIVER_TYPE_PLAYER)"),
    M("ic_player_slot", RIN, "add_racing_car(d, &locs[pos - 1], REAL_CONTROL);",
      "add_racing_car(d, &locs[0], REAL_CONTROL);"),
    M("ic_ai_slot", RIN, "add_racing_car(d, &locs[pos - 1], AI_CONTROL);",
      "add_racing_car(d, &locs[0], AI_CONTROL);"),
    M("ic_player_mode", RIN, "add_racing_car(d, &locs[pos - 1], REAL_CONTROL);",
      "add_racing_car(d, &locs[pos - 1], AI_CONTROL);"),
    M("ic_ai_mode", RIN, "add_racing_car(d, &locs[pos - 1], AI_CONTROL);",
      "add_racing_car(d, &locs[pos - 1], REAL_CONTROL);"),
    M("ic_every_driver", RIN,
      "                add_racing_car(d, &locs[pos - 1], AI_CONTROL);\n            break;\n",
      "                add_racing_car(d, &locs[pos - 1], AI_CONTROL);\n"),
    M("ic_others_skipped", RIN,
      "                add_racing_car(d, &locs[pos - 1], AI_CONTROL);\n            break;\n",
      "                add_racing_car(d, &locs[pos - 1], AI_CONTROL);\n            else\n                continue;\n            break;\n"),
    M("ic_no_first_table", RIN, "    world_build_car_table(pCurrentWorld);\n\n    // The AI",
      "\n    // The AI"),
    # InitCars: the routes
    M("ic_track_one", RIN, "track_get_info(RaceParametersTrackNumber)", "track_get_info(1)"),
    M("ic_override_gt", RIN, "if (ti->OverrideStartingRouteForAI >= 0) {",
      "if (ti->OverrideStartingRouteForAI > 0) {"),
    M("ic_override_slot", RIN, "pTrackRoutes[ti->OverrideStartingRouteForAI];",
      "pTrackRoutes[ti->OverrideStartingRouteForAI ^ 1];"),
    M("ic_start_route_null", RIN, "        start.Route = r;\n", "        start.Route = NULL;\n"),
    M("ic_start_point_one", RIN, "&r->TrackRoutePointTable[0]", "&r->TrackRoutePointTable[1]"),
    M("ic_racers_from_zero", RIN, "pCurrentWorld->CarTable[pCurrentWorld->AICarPos + i]",
      "pCurrentWorld->CarTable[i]"),
    M("ic_racers_short", RIN,
      "i < pCurrentWorld->CopCarPos - pCurrentWorld->AICarPos; i++) {",
      "i < pCurrentWorld->CopCarPos - pCurrentWorld->AICarPos - 1; i++) {"),
    M("ic_every_racer_tested", RIN, "if (i == 0 && !nrpi_is_valid(&start)) {",
      "if (!nrpi_is_valid(&start)) {"),
    M("ic_valid_ignored", RIN, "if (i == 0 && !nrpi_is_valid(&start)) {", "if (i == 0) {"),
    M("ic_no_find", RIN, "            ((RaceInitFindFn)e->fn)(vt_this(ctl, e));\n", ""),
    M("ic_find_slot", RIN, "e = vt_slot(ctl->_vtable, CARCONTROLLER_VT_FIND_WHERE_I_AM);",
      "e = vt_slot(ctl->_vtable, CARCONTROLLER_VT_GET_CURRENT_ROUTE_POINT);"),
    M("ic_getroute_slot", RIN, "e = vt_slot(ctl->_vtable, CARCONTROLLER_VT_GET_CURRENT_ROUTE);",
      "e = vt_slot(ctl->_vtable, CARCONTROLLER_VT_SET_CURRENT_ROUTE);"),
    M("ic_getroute_flag", RIN, "start.Route = ((RaceInitGetRouteFn)e->fn)(vt_this(ctl, e), 1);",
      "start.Route = ((RaceInitGetRouteFn)e->fn)(vt_this(ctl, e), 0);"),
    M("ic_getpoint_flag", RIN, "start.Point = ((RaceInitGetPointFn)e->fn)(vt_this(ctl, e), 1);",
      "start.Point = ((RaceInitGetPointFn)e->fn)(vt_this(ctl, e), 0);"),
    M("ic_getpoint_no_delta", RIN, "start.Point = ((RaceInitGetPointFn)e->fn)(vt_this(ctl, e), 1);",
      "start.Point = ((RaceInitGetPointFn)e->fn)(ctl, 1);"),
    M("ic_route_not_kept", RIN, "start.Route = ((RaceInitGetRouteFn)e->fn)(vt_this(ctl, e), 1);",
      "((RaceInitGetRouteFn)e->fn)(vt_this(ctl, e), 1);"),
    M("ic_point_not_kept", RIN, "start.Point = ((RaceInitGetPointFn)e->fn)(vt_this(ctl, e), 1);",
      "((RaceInitGetPointFn)e->fn)(vt_this(ctl, e), 1);"),
    M("ic_setroute_no_delta", RIN, "((RaceInitSetRouteFn)e->fn)(vt_this(ctl, e), start.Route,",
      "((RaceInitSetRouteFn)e->fn)(ctl, start.Route,"),
    M("ic_setroute_point", RIN, "start.Route,\n                                        start.Point);",
      "start.Route,\n                                        NULL);"),
    M("ic_setroute_route", RIN, "(vt_this(ctl, e), start.Route,\n",
      "(vt_this(ctl, e), NULL,\n"),
    # InitCars: the traffic, the cops and the helicopter
    M("ic_traffic_drivers_from_one", RIN,
      "    for (i = 0; i < RaceParametersNumDriverInfo; i++) {\n        DriverInfo *d = race_parameters_get_driver_info(i);\n\n        if (d->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR)",
      "    for (i = 1; i < RaceParametersNumDriverInfo; i++) {\n        DriverInfo *d = race_parameters_get_driver_info(i);\n\n        if (d->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR)"),
    M("ic_traffic_rank_skipped", RIN,
      "\n        if (d->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR) {",
      "\n        if (d->EliminatedRank > 0)\n            continue;\n        if (d->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR) {"),
    M("ic_traffic_type", RIN, "if (d->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR) {",
      "if (d->TheDriverType == DRIVER_TYPE_AI_RACER) {"),
    M("ic_traffic_world", RIN, "world_add_traffic_car(pCurrentWorld, d);", "world_add_traffic_car(NULL, d);"),
    M("ic_cop_only", RIN,
      "} else if (d->TheDriverType == DRIVER_TYPE_COP\n                   || d->TheDriverType == DRIVER_TYPE_SUPER_COP) {",
      "} else if (d->TheDriverType == DRIVER_TYPE_COP) {"),
    M("ic_super_cop_only", RIN,
      "} else if (d->TheDriverType == DRIVER_TYPE_COP\n                   || d->TheDriverType == DRIVER_TYPE_SUPER_COP) {",
      "} else if (d->TheDriverType == DRIVER_TYPE_SUPER_COP) {"),
    M("ic_cops_not_counted", RIN, "            cops++;\n", ""),
    M("ic_cop_flag", RIN, "gAddCopCarToRaceFn(d, 0);", "gAddCopCarToRaceFn(d, 1);"),
    M("ic_no_second_table", RIN, "    world_build_car_table(pCurrentWorld);\n\n    if ((cops",
      "\n    if ((cops"),
    M("ic_heli_cops_only", RIN,
      "(cops != 0 || (gEggIsOnFn != NULL && gEggIsOnFn(EGG_HELICOPTER)))", "(cops != 0)"),
    M("ic_heli_always", RIN,
      "(cops != 0 || (gEggIsOnFn != NULL && gEggIsOnFn(EGG_HELICOPTER)))",
      "(cops != 0 || gEggIsOnFn != NULL)"),
    M("ic_heli_egg_four", RIH, "#define EGG_HELICOPTER 5", "#define EGG_HELICOPTER 4"),
    M("ic_heli_size", RIH, "#define CHOPPER_SIZE 976", "#define CHOPPER_SIZE 977"),
    M("ic_heli_name", RIN, "\"Chopper\", 0,", "\"chopper\", 0,"),
    M("ic_heli_flags", RIN, "\"Chopper\", 0,", "\"Chopper\", 1,"),
    M("ic_heli_pool", RIN, "\"Chopper\", 0,\n                                               CAR_MEMORY_POOL)",
      "\"Chopper\", 0,\n                                               0)"),
    M("ic_heli_not_kept", RIN, "        w->Helicopter = gChopperCtorFn(", "        (void)gChopperCtorFn("),
    M("ic_beacop_without_cops", RIN, "if (cops != 0 && RaceParametersBeACop && gAddCopCarToRaceFn != NULL)",
      "if (RaceParametersBeACop && gAddCopCarToRaceFn != NULL)"),
    M("ic_beacop_ignored", RIN, "if (cops != 0 && RaceParametersBeACop && gAddCopCarToRaceFn != NULL)",
      "if (cops != 0 && gAddCopCarToRaceFn != NULL)"),
    M("ic_beacop_flag", RIN, "gAddCopCarToRaceFn(NULL, 1);", "gAddCopCarToRaceFn(NULL, 0);"),
    M("ic_beacop_driver", RIN, "gAddCopCarToRaceFn(NULL, 1);",
      "gAddCopCarToRaceFn(race_parameters_get_driver_info(0), 1);"),
    # InitPlayers
    M("ip_one_player", RIN, "for (i = 0; i < PlayerNumPlayers; i++) {", "for (i = 0; i < 1; i++) {"),
    M("ip_first_player", RIN, "struct Player *p = PlayerPlayersByIndex[i];",
      "struct Player *p = PlayerPlayersByIndex[0];"),
    M("ip_aidemo_ignored", RIN, "if (RaceParametersAIDemoMode) {", "if (0) {"),
    M("ip_aidemo_no_number", RIN,
      "player_init_for_race(p, w->CarTable[w->AICarPos\n                                                + p->PlayerNumber]);",
      "player_init_for_race(p, w->CarTable[w->AICarPos]);"),
    M("ip_aidemo_from_zero", RIN, "w->CarTable[w->AICarPos\n", "w->CarTable[0\n"),
    M("ip_bynum_index", RIN, "world_get_car_by_number(pCurrentWorld, p->PlayerNumber);",
      "world_get_car_by_number(pCurrentWorld, i);"),
    M("ip_null_car", RIN, "            if (c != NULL)\n                player_init_for_race(p, c);",
      "            player_init_for_race(p, c);"),
    # GetDriverInfo
    M("gdi_first", RCE, "    return &RaceParametersDriverInfo[i];", "    return &RaceParametersDriverInfo[0];"),
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

    layout = arm_layout_check()
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
    sys.exit(1 if (n or rc or layout) else 0)


if __name__ == "__main__":
    main()
