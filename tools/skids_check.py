#!/usr/bin/env python3
"""Cross-check 3DS Files/source/skids.c (the skid marks' sets and clans,
TASKS 78) against the retail image itself, run in mipsemu.

The model is the image: SkidSegment's SetPoints, GetPoints and
GetEndPoints, SkidSet's constructor, destructor, AddSegment,
FinishedAddingSkids and GetLastPoints, CreateNewSkidSet, SkidMaker's
MakeSkid and MakeNoSkid, InitSkids, CloseSkids and DeleteThisSkid, and the
clans -- Clan's constructor, destructor and ExpandBoundingBox, InitClans,
FlushClans, CloseClans and GetClan (0x001aa788 .. 0x001abaa0) -- run as
shipped, with bStringHash, the bounding box functions, ~bPNode and the
list destructors under them -- and Wheel::MaybeMakeSkids (0x001a5520,
TASKS 78b), with bRotateVector and bNormalize under it, on four wheels at
retail's offsets. The harness (tools/src/skids_test.c) runs the port over
the same script, and the two transcripts are diffed.

Stubbed on both sides, each printing what it is given:
  - the slot pools (bNewSlotPool, bDeleteSlotPool, bMalloc(SlotPool *),
    bOMalloc, bFree(SlotPool *, void *), bIsSlotPoolFull): a pool hands out
    its lowest free slot, filled with 0xcd by bMalloc and by bOMalloc
    cleared when the pool's flags say so, and frees without touching it;
    the pool's flags word is the image's, so InitSkids' clearing of bit 0
    shows;
  - bPNode::Malloc and bPNode::Free, the lowest free of 1024 nodes;
  - GetTextureInfo, which answers one of four textures, or none, by the
    hash;
  - TopologyCoordinate::GetElevation (0x00152070), which answers the two
    heights the MaybeMakeSkids op gives, in turn, and 0 past them.
  The harness has its own copy of bRotateVector, wheel.c's, which it does
  not link; wheel_check holds wheel.c's to the image.

The script makes skids for eight makers on four cars (the Car's
GeometryPosition and VisibleViewBits at retail's offsets on the model
side): trails straight and curved, turns sharp enough to end a set, steps
of nothing, points past 4 m from the car, changes of terrain and of
visibility, intensities and widths past a byte; the clans' squares at
their edges and far off; a clan pool and a set pool run full; flushes,
closes and reopens; then MaybeMakeSkids' gates one at a time, wheels
rolling, pressing, drifting and broadside, every terrain, the ground
tilted under the edges, and a random drive of four wheels on two cars;
and then a long random drive of MakeSkid alone. After each op both
sides print a hash of the whole state: each maker's set, the pools'
flags, SkidSetList in order with every set's fields and segments, ClanList
in order with every clan's and its list, the textures and the two debug
switches. Every so often, and on a D, they print the state itself.

    python tools/skids_check.py
    python tools/skids_check.py --mutate [--only a,b] [--jobs N]
    python tools/skids_check.py --dump out/skids
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
import hostbuild                          # noqa: E402
import mutpar                             # noqa: E402
import physicscar_check as pcc            # noqa: E402
import retail_model                       # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)
M32 = 0xffffffff

HARNESS = "tools/src/skids_test.c"
SKC = "3DS Files/source/skids.c"
SOURCES = [HARNESS, SKC, "3DS Files/source/bvector.c",
           "3DS Files/source/bmath.c", "3DS Files/source/bmathtab.c",
           "3DS Files/source/terraintypetab.c"]
HARNESS_TIMEOUT = 120
LIMIT = 5000000

# ================================================================ the image

GP = 0x003358f0
INIT_SKIDS = 0x001ab118             # InitSkids__Fv
CLOSE_SKIDS = 0x001ab1d0            # CloseSkids__Fv
DELETE_THIS_SKID = 0x001ab228       # DeleteThisSkid__FP7SkidSet
MAKE_SKID = 0x001aaf50              # MakeSkid__9SkidMakerP8bVector3T1if
MAKE_NO_SKID = 0x001ab0f8           # MakeNoSkid__9SkidMaker
INIT_CLANS = 0x001ab618             # InitClans__Fv
FLUSH_CLANS = 0x001ab650            # FlushClans__Fv
CLOSE_CLANS = 0x001ab6a0            # CloseClans__Fv
GET_CLAN = 0x001ab6d0               # GetClan__FP8bVector3
SINIT_SKIDS = 0x001ab4b0            # _GLOBAL_$I$SetPoints__11SkidSegment..
SINIT_CLANS = 0x001aba70            # ClanList's

BNEWSLOTPOOL = 0x00257c10
BDELETESLOTPOOL = 0x00257c48
BMALLOC_POOL = 0x00257c60
BOMALLOC = 0x00257c80
BFREE_POOL = 0x00257ca0
BISFULL = 0x00257d10
PNODE_MALLOC = 0x00250680           # Malloc__6bPNode
PNODE_FREE = 0x002506b0             # Free__6bPNodePv
GET_TEXTURE_INFO = 0x001abf48       # GetTextureInfo__FUii
MAYBE_MAKE_SKIDS = 0x001a5520       # Wheel::MaybeMakeSkids(Car *, float)
GET_ELEVATION = 0x00152070          # TopologyCoordinate::GetElevation

G_WORLDTIME = GP - 19568
G_SKIDLIST = GP - 19208
G_SKIDPOOL = GP - 19200
G_PLOT = GP - 19196
G_PLOTPOINTS = GP - 19192
G_CLANLIST = GP - 19160
G_CLANPOOL = GP - 19152
SKID_TEX = 0x00311520
NUM_TERRAIN = 33

# Retail's offsets.
CAR_GEOMETRY_POSITION = 80
CAR_VISIBLE_VIEW_BITS = 1300
CAR_BLOWN_TIRE_BITS = 2124
WHEEL_WI = 12
WHEEL_CS = 24
WHEEL_MATRIX = 112
WHEEL_VELOCITY = 240
WHEEL_TERRAIN = 336
WHEEL_SLIPPING = 340
WHEEL_TOUCHING = 341
WHEEL_ZFORCE = 344
WHEEL_TRACTION = 360
WHEEL_MAKER = 384
WI_WIDTH = 16
WI_NUMBER = 20
CS_TOPOLOGY = 4
SET_LAST_NORMAL = 16
SET_LAST_LENGTH = 32
SET_CAR = 36
SET_BOTH = 40
SET_CLAN = 44
SET_NODE = 48
SET_MAKER = 52
SET_TERRAIN = 56
SET_POSITION = 64
SET_MAX = 80
SET_MIN = 96
SET_SEGMENTS = 112
SET_COUNT = 240
SET_CENTRE = 256
CLAN_LIST = 8
CLAN_HASH = 16
CLAN_TIME = 20
CLAN_POSITION = 32
CLAN_MIN = 48
CLAN_MAX = 64

# The model's memory, past the image.
POOL_H = 0x01000000                 # 64 bytes a pool header
POOL_MEM = 0x01010000               # 0x20000 a pool, 0x200 a slot
POOL_STRIDE = 0x20000
SLOT_STRIDE = 0x200
MAX_POOLS = 16
NODE_MEM = 0x01300000               # 16 bytes a node
NUM_NODES = 1024
MAKERS = 0x01310000                 # 16 bytes a maker
NUM_MAKERS = 8
CARS = 0x01320000                   # 0x1000 a car
NUM_CARS = 4
ARGS = 0x01330000                   # the position, then the delta
TEX = 0x01340000                    # 0x100 a texture
NUM_TEX = 4
WHEELS = 0x01350000                 # 0x200 a wheel
NUM_WHEELS = 4
WIS = 0x01360000                    # 0x40 a WheelInfo
CSS = 0x01370000                    # 0x40 a CarState
TOPO = 0x01380000                   # 16 bytes a topology, never read

SIZE_LABELS = {272: "skidset", 80: "clan"}
POOL_PREFIX = {"SkidSetSlotPool": "s", "ClanSlotPool": "c"}

FULL_EVERY = 100


def fb(v):
    """A Python float as float32 bits."""
    return struct.unpack("<I", struct.pack("<f", v))[0]


def bf(u):
    return struct.unpack("<f", struct.pack("<I", u & M32))[0]


def s32(v):
    v &= M32
    return v - (1 << 32) if v & 0x80000000 else v


def fnv(lines):
    h = 0x811c9dc5
    for l in lines:
        for c in (l + NL).encode("latin-1"):
            h = ((h ^ c) * 0x01000193) & M32
    return h


def tex_for(h):
    """GetTextureInfo's stubbed answer: texture 1..4, or 0 for none."""
    return (h >> 3) % (NUM_TEX + 1)


# ================================================================== model


class Model(object):
    def __init__(self):
        self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        e = self.e
        e.stub(BNEWSLOTPOOL, self.st_newpool)
        e.stub(BDELETESLOTPOOL, self.st_delpool)
        e.stub(BMALLOC_POOL, lambda em: self.st_alloc("m"))
        e.stub(BOMALLOC, lambda em: self.st_alloc("o"))
        e.stub(BFREE_POOL, self.st_free)
        e.stub(BISFULL, self.st_isfull)
        e.stub(PNODE_MALLOC, self.st_node_new)
        e.stub(PNODE_FREE, self.st_node_free)
        e.stub(GET_TEXTURE_INFO, self.st_tex)
        e.stub(GET_ELEVATION, self.st_elev)
        self.heights = []
        self.out = []
        self.pools = []
        self.nodes = [False] * NUM_NODES
        e.write(POOL_H, bytes(0x400000))
        e.call(SINIT_SKIDS, limit=1000)
        e.call(SINIT_CLANS, limit=1000)
        for g in (G_SKIDPOOL, G_PLOT, G_PLOTPOINTS, G_CLANPOOL):
            e.put32(g, 0xa5a5a5a5 if g in (G_PLOT, G_PLOTPOINTS) else 0)
        e.write(SKID_TEX, bytes(4 * NUM_TERRAIN))
        e.put32(G_WORLDTIME, 1)

    def emit(self, s):
        self.out.append(s)

    def arg(self, i):
        return self.e.reg[(4, 5, 6, 7, 8)[i]] & M32

    def w(self, a):
        return self.e.u32(a)

    def cstr(self, a):
        s = bytearray()
        while True:
            b = self.e.u8(a + len(s))
            if b == 0:
                return s.decode("latin-1")
            s.append(b)

    # ---- labels ----------------------------------------------------------

    def pool_label(self, h):
        if h == 0:
            return "NULL"
        return "p%d" % ((h - POOL_H) // 64)

    def label(self, a):
        a &= M32
        if a == 0:
            return "NULL"
        if POOL_MEM <= a < POOL_MEM + POOL_STRIDE * MAX_POOLS:
            k, o = divmod(a - POOL_MEM, POOL_STRIDE)
            i, r = divmod(o, SLOT_STRIDE)
            if r == 0 and k < len(self.pools):
                return "%s%d" % (POOL_PREFIX.get(self.pools[k]["name"], "?"),
                                 i)
        if NODE_MEM <= a < NODE_MEM + 16 * NUM_NODES and a % 16 == 0:
            return "n%d" % ((a - NODE_MEM) // 16)
        if MAKERS <= a < MAKERS + 16 * NUM_MAKERS and a % 16 == 0:
            return "m%d" % ((a - MAKERS) // 16)
        if CARS <= a < CARS + 0x1000 * NUM_CARS and a % 0x1000 == 0:
            return "car%d" % ((a - CARS) // 0x1000)
        if WHEELS <= a < WHEELS + 0x200 * NUM_WHEELS \
                and a % 0x200 == WHEEL_MAKER:
            return "wm%d" % ((a - WHEELS) // 0x200)
        if TOPO <= a < TOPO + 16 * NUM_WHEELS and a % 16 == 0:
            return "topo%d" % ((a - TOPO) // 16)
        if TEX <= a < TEX + 0x100 * (NUM_TEX + 1) and a % 0x100 == 0:
            return "t%d" % ((a - TEX) // 0x100)
        return "?%08x" % a

    # ---- the stubs -------------------------------------------------------

    def st_newpool(self, em):
        size, n = s32(self.arg(0)), s32(self.arg(1))
        name, mem = self.cstr(self.arg(2)), s32(self.arg(3))
        k = len(self.pools)
        self.pools.append({"size": size, "n": n, "name": name,
                           "used": [False] * n})
        h = POOL_H + 64 * k
        self.e.write(h, bytes(64))
        self.e.put32(h + 20, 0x0f)
        self.emit("newpool p%d name=%s n=%d size=%s mem=%d" % (
            k, name, n, SIZE_LABELS.get(size, "%d" % size), mem))
        return h

    def st_delpool(self, em):
        h = self.arg(0)
        self.emit("delpool %s" % self.pool_label(h))
        if h:
            p = self.pools[(h - POOL_H) // 64]
            p["used"] = [False] * p["n"]

    def st_alloc(self, how):
        h = self.arg(0)
        k = (h - POOL_H) // 64
        p = self.pools[k]
        for i in range(p["n"]):
            if not p["used"][i]:
                p["used"][i] = True
                a = POOL_MEM + POOL_STRIDE * k + SLOT_STRIDE * i
                clear = how == "o" and self.w(h + 20) & 2
                self.e.write(a, (b"\0" if clear else b"\xcd") * p["size"])
                self.emit("alloc%s p%d slot=%d" % (how, k, i))
                return a
        self.emit("alloc%s p%d full" % (how, k))
        return 0

    def st_free(self, em):
        h, a = self.arg(0), self.arg(1)
        self.emit("free %s %s" % (self.pool_label(h), self.label(a)))
        k = (h - POOL_H) // 64
        if POOL_MEM <= a < POOL_MEM + POOL_STRIDE * MAX_POOLS:
            kk, o = divmod(a - POOL_MEM, POOL_STRIDE)
            if kk == k:
                self.pools[k]["used"][o // SLOT_STRIDE] = False

    def st_isfull(self, em):
        p = self.pools[(self.arg(0) - POOL_H) // 64]
        return 1 if all(p["used"]) else 0

    def st_node_new(self, em):
        for i in range(NUM_NODES):
            if not self.nodes[i]:
                self.nodes[i] = True
                a = NODE_MEM + 16 * i
                self.e.write(a, b"\xcd" * 16)
                return a
        raise SystemExit("model: out of nodes")

    def st_node_free(self, em):
        a = self.arg(0)
        self.nodes[(a - NODE_MEM) // 16] = False

    def st_tex(self, em):
        h, d, u = self.arg(0), s32(self.arg(1)), s32(self.arg(2))
        k = tex_for(h)
        a = TEX + 0x100 * k if k else 0
        self.emit("tex %08x def=%d unl=%d -> %s" % (h, d, u, self.label(a)))
        return a

    def st_elev(self, em):
        h = self.heights.pop(0) if self.heights else 0
        self.emit("elev %s %s t=%s n=%s -> %08x" % (
            self.label(self.arg(0)), self.vec(self.arg(1)),
            self.label(self.arg(2)), self.label(self.arg(3)), h))
        self.e.fpr[0] = h

    # ---- the state -------------------------------------------------------

    def vec(self, a):
        return "%08x,%08x,%08x" % (self.w(a), self.w(a + 4), self.w(a + 8))

    def walk(self, head, limit=2000):
        out = []
        n = self.w(head)
        while n != head:
            out.append(n)
            if len(out) > limit:
                out.append(None)
                break
            n = self.w(n)
        return out

    def state(self):
        e = self.e
        out = ["makers " + " ".join(
            ["m%d=%s" % (m, self.label(self.w(MAKERS + 16 * m)))
             for m in range(NUM_MAKERS)]
            + ["wm%d=%s" % (i, self.label(self.w(WHEELS + 0x200 * i
                                                 + WHEEL_MAKER)))
               for i in range(NUM_WHEELS)])]
        out.append("pools " + " ".join(
            "p%d=%x/%d" % (k, self.w(POOL_H + 64 * k + 20),
                           sum(p["used"]))
            for k, p in enumerate(self.pools)))
        out.append("globals skidpool=%s clanpool=%s plot=%d,%d" % (
            self.pool_label(self.w(G_SKIDPOOL)),
            self.pool_label(self.w(G_CLANPOOL)),
            s32(self.w(G_PLOT)), s32(self.w(G_PLOTPOINTS))))
        out.append("tex " + " ".join(
            self.label(self.w(SKID_TEX + 4 * i)) for i in range(NUM_TERRAIN)))
        sets = self.walk(G_SKIDLIST)
        out.append("sets " + " ".join(self.label(s) if s else "LOOP"
                                       for s in sets))
        for s in sets:
            if s is None:
                break
            n = s32(self.w(s + SET_COUNT))
            line = ("set %s car=%s both=%d clan=%s node=%s maker=%s terr=%d "
                    "n=%d pos=%s max=%s min=%s len=%08x centre=%s" % (
                        self.label(s), self.label(self.w(s + SET_CAR)),
                        s32(self.w(s + SET_BOTH)),
                        self.label(self.w(s + SET_CLAN)),
                        self.label(self.w(s + SET_NODE)),
                        self.label(self.w(s + SET_MAKER)),
                        s32(self.w(s + SET_TERRAIN)), n,
                        self.vec(s + SET_POSITION), self.vec(s + SET_MAX),
                        self.vec(s + SET_MIN), self.w(s + SET_LAST_LENGTH),
                        self.vec(s + SET_CENTRE)))
            if n >= 2:
                line += " normal=%s" % self.vec(s + SET_LAST_NORMAL)
            out.append(line)
            for i in range(max(0, min(n, 8))):
                g = s + SET_SEGMENTS + 16 * i
                out.append("  seg %d pos=%s d=%02x%02x%02x int=%02x" % (
                    i, self.vec(g), e.u8(g + 12), e.u8(g + 13), e.u8(g + 14),
                    e.u8(g + 15)))
        clans = self.walk(G_CLANLIST)
        out.append("clans " + " ".join(self.label(c) if c else "LOOP"
                                        for c in clans))
        for c in clans:
            if c is None:
                break
            members = [self.w(nd + 8) for nd in self.walk(c + CLAN_LIST)
                       if nd is not None]
            out.append("clan %s hash=%08x t=%d pos=%s min=%s max=%s sets=%s"
                       % (self.label(c), self.w(c + CLAN_HASH),
                          s32(self.w(c + CLAN_TIME)),
                          self.vec(c + CLAN_POSITION), self.vec(c + CLAN_MIN),
                          self.vec(c + CLAN_MAX),
                          ",".join(self.label(x) for x in members)))
        return out

    # ---- the ops ---------------------------------------------------------

    def put_vec(self, a, xs):
        for i, x in enumerate(xs):
            self.e.put32(a + 4 * i, x)
        self.e.put32(a + 12, 0x3f800000)

    def call(self, addr, *args):
        self.e.call(addr, *args, limit=LIMIT)
        return self.e.reg[2] & M32

    def run(self, ops):
        e = self.e
        for k, op in enumerate(ops):
            t = op.split()
            self.emit("> " + op)
            c = t[0]
            if c == "IC":
                self.call(INIT_CLANS)
            elif c == "IS":
                self.call(INIT_SKIDS)
            elif c == "CC":
                self.call(CLOSE_CLANS)
            elif c == "CS":
                self.call(CLOSE_SKIDS)
            elif c == "FC":
                self.call(FLUSH_CLANS)
            elif c == "W":
                e.put32(G_WORLDTIME, int(t[1]))
            elif c == "CAR":
                a = CARS + 0x1000 * int(t[1])
                self.put_vec(a + CAR_GEOMETRY_POSITION,
                             [int(x, 16) for x in t[2:5]])
                e.put32(a + CAR_VISIBLE_VIEW_BITS, int(t[5], 16))
            elif c == "MS":
                m, car = int(t[1]), int(t[2])
                v = [int(x, 16) for x in t[3:9]]
                self.put_vec(ARGS, v[0:3])
                self.put_vec(ARGS + 16, v[3:6])
                e.fpr[12] = int(t[10], 16)
                self.call(MAKE_SKID, MAKERS + 16 * m,
                          CARS + 0x1000 * car if car >= 0 else 0,
                          ARGS, ARGS + 16, int(t[9]))
            elif c == "MN":
                self.call(MAKE_NO_SKID, MAKERS + 16 * int(t[1]))
            elif c == "WH":
                i = int(t[1])
                wh, wi, cs = WHEELS + 0x200 * i, WIS + 0x40 * i, CSS + 0x40 * i
                e.put32(wh + WHEEL_WI, wi)
                e.put32(wh + WHEEL_CS, cs)
                e.put32(cs + CS_TOPOLOGY, TOPO + 16 * i)
                e.put32(wi + WI_NUMBER, int(t[2]))
                e.put32(wi + WI_WIDTH, int(t[3], 16))
                e.put32(wh + WHEEL_TERRAIN, int(t[4]))
                e.write(wh + WHEEL_SLIPPING, bytes([int(t[5]), int(t[6])]))
                e.put32(wh + WHEEL_ZFORCE, int(t[7], 16))
                e.put32(wh + WHEEL_TRACTION, int(t[8], 16))
                e.put32(wh + WHEEL_VELOCITY, int(t[9], 16))
                e.put32(wh + WHEEL_VELOCITY + 4, int(t[10], 16))
            elif c == "WM":
                wh = WHEELS + 0x200 * int(t[1])
                for j in range(16):
                    e.put32(wh + WHEEL_MATRIX + 4 * j, int(t[2 + j], 16))
            elif c == "BL":
                e.write(CARS + 0x1000 * int(t[1]) + CAR_BLOWN_TIRE_BITS,
                        bytes([int(t[2], 16)]))
            elif c == "MM":
                i, car = int(t[1]), int(t[2])
                e.fpr[12] = int(t[3], 16)
                self.heights = [int(t[4], 16), int(t[5], 16)]
                self.call(MAYBE_MAKE_SKIDS, WHEELS + 0x200 * i,
                          CARS + 0x1000 * car)
            elif c == "GC":
                self.put_vec(ARGS, [int(x, 16) for x in t[1:4]])
                self.emit("clan %s" % self.label(self.call(GET_CLAN, ARGS)))
            elif c == "DH":
                head = self.w(G_SKIDLIST)
                if head != G_SKIDLIST:
                    self.emit("delete %s" % self.label(head))
                    self.call(DELETE_THIS_SKID, head)
            elif c != "D":
                raise SystemExit("bad op %r" % op)
            st = self.state()
            if c == "D" or k % FULL_EVERY == 0:
                self.out.extend(st)
            self.emit("= %08x" % fnv(st))
        return self.out


def model(ops):
    return mutpar.model_cached(ops, lambda l: Model().run(l),
                               cut="# ---- cut")


# ================================================================ the script

def h(v):
    return "%08x" % fb(v)


class Script(object):
    def __init__(self):
        self.ops = []
        self.cars = {}

    def op(self, s):
        self.ops.append(s)

    def car(self, k, x, y, z, bits=0xffffffff):
        self.cars[k] = (x, y, z)
        self.op("CAR %d %s %s %s %08x" % (k, h(x), h(y), h(z), bits))

    def skid(self, m, car, p, d=(0.0, 0.15, 0.0), terr=1, inten=0.75):
        self.op("MS %d %d %s %s %s %s %s %s %d %s" % (
            m, car, h(p[0]), h(p[1]), h(p[2]), h(d[0]), h(d[1]), h(d[2]),
            terr, h(inten)))

    def follow(self, m, car, p, **kw):
        """The car over the point, then the skid."""
        self.car(car, p[0], p[1], p[2] + 0.3)
        self.skid(m, car, p, **kw)

    def wheel(self, i, wn=None, width=0.3, terr=1, slip=1, touch=1,
              zf=3000.0, tu=0.4, v=(0.0, 6.0)):
        self.op("WH %d %d %s %d %d %d %s %s %s %s" % (
            i, i if wn is None else wn, h(width), terr, slip, touch, h(zf),
            h(tu), h(v[0]), h(v[1])))

    def place(self, i, p, yaw=0.0, pitch=0.0, roll=0.0):
        """The wheel's world matrix: x the axle, y ahead, z up, then the
        place, as rows."""
        cy, sy = math.cos(yaw), math.sin(yaw)
        cp, sp = math.cos(pitch), math.sin(pitch)
        cr, sr = math.cos(roll), math.sin(roll)
        ahead = (-sy * cp, cy * cp, sp)
        axle = (cy * cr + sy * sp * sr, sy * cr - cy * sp * sr, -cp * sr)
        up = (axle[1] * ahead[2] - axle[2] * ahead[1],
              axle[2] * ahead[0] - axle[0] * ahead[2],
              axle[0] * ahead[1] - axle[1] * ahead[0])
        rows = (axle + (0.0,), ahead + (0.0,), up + (0.0,),
                (p[0], p[1], p[2], 1.0))
        self.op("WM %d %s" % (i, " ".join(h(x) for r in rows for x in r)))

    def maybe(self, i, car, ha=0.0, hb=0.0, dt=1.0 / 30.0):
        self.op("MM %d %d %s %s %s" % (i, car, h(dt), h(ha), h(hb)))


def s_basics(sc):
    sc.op("IC")
    sc.op("IS")
    sc.op("D")
    sc.op("IS")
    sc.op("IC")
    sc.op("W 100")
    # A straight trail along x in steps of 0.1 m: the points merge until
    # the pair passes 3 m, eight segments fill the set, and a new set goes
    # on from the last point.
    for i in range(140):
        sc.follow(0, 0, (5.0 + 0.1 * i, 3.0, 1.0))
    sc.op("D")
    sc.op("MN 0")
    # A step of nothing, on a set of one and on one of two and more.
    sc.follow(0, 0, (30.0, 3.0, 1.0))
    sc.follow(0, 0, (30.0, 3.0, 1.0))
    sc.follow(0, 0, (30.5, 3.0, 1.0))
    sc.follow(0, 0, (30.5, 3.0, 1.0))
    sc.follow(0, 0, (31.0, 3.0, 1.0))
    sc.op("D")


def s_curves(sc):
    # Circles of radius 2 .. 40 m in steps of 0.3 .. 1.2 m: at some the turn
    # each step passes 0.002 and at some it stays under; the tightest pass
    # 0.2 and end the set.
    sc.op("W 220")
    m = 1
    for r, step in ((40.0, 0.6), (20.0, 0.9), (9.0, 0.5), (6.0, 0.35),
                    (3.0, 1.2), (2.0, 0.3), (14.0, 1.1)):
        cx, cy = 100.0 + 3 * r, -50.0
        n = int(2 * math.pi * r / step) // 2
        for i in range(n):
            a = step * i / r
            sc.follow(m, 1, (cx + r * math.cos(a), cy + r * math.sin(a),
                             2.0 + 0.01 * i),
                      d=(0.12 * math.cos(a), 0.12 * math.sin(a), 0.0),
                      inten=0.4 + 0.5 * (i % 7) / 6)
        sc.op("MN %d" % m)
        sc.op("D")


def s_breaks(sc):
    sc.op("W 400")
    m, car = 2, 2
    x, y = -20.0, -20.0
    # A right-angled turn after four segments.
    for i in range(5):
        sc.follow(m, car, (x + 0.6 * i, y, 0.5))
    for i in range(1, 5):
        sc.follow(m, car, (x + 2.4, y + 0.6 * i, 0.5))
    sc.op("D")
    # The terrain changes, then the intensity of a new set is the last's.
    for i in range(6):
        sc.follow(m, car, (x + 2.4, y + 3.0 + 0.7 * i, 0.5),
                  terr=1 if i < 3 else 2, inten=0.2 + 0.1 * i)
    sc.op("D")
    # The car leaves player 2's view, then player 1's, then comes back.
    for i, bits in enumerate((0xffffffff, 0xfffffffb, 0xfffffff9, 0x6,
                              0x2, 0xffffffff, 0xfffffffd, 0x4, 0x6)):
        p = (x + 2.4 + 0.8 * i, y + 8.0, 0.5)
        sc.car(car, p[0], p[1], p[2] + 0.3, bits)
        sc.skid(m, car, p)
    sc.op("D")
    # Points 4 m from the car and past it, and a car of no one.
    sc.car(car, 0.0, 40.0, 0.0)
    sc.skid(m, car, (4.0, 40.0, 0.0))
    sc.skid(m, car, (4.001, 40.0, 0.0))
    sc.skid(m, car, (0.0, 40.0, -4.5))
    sc.skid(m, car, (2.0, 42.0, 2.0))
    sc.skid(m, car, (0.0, 44.01, 0.0))
    sc.skid(m, car, (0.0, 36.0, 0.0))
    sc.skid(m, car, (0.0, 35.5, 0.0))
    sc.skid(m, -1, (9.0, 40.0, 0.0))
    sc.skid(m, -1, (9.5, 40.0, 0.0))
    sc.op("D")
    # Intensities and widths past a byte.
    for i, (inten, d) in enumerate(((0.0, (0.0, 0.1, 0.0)),
                                    (1.0, (0.0, -0.1, 0.0)),
                                    (1.003, (2.5, 0.0, 0.0)),
                                    (1.01, (-2.5, 0.0, 0.0)),
                                    (-0.1, (0.0, 1.99, -1.99)),
                                    (0.5, (0.0, 0.0078125, -0.0078125)),
                                    (0.999, (0.3, 0.3, 0.3)))):
        sc.follow(3, 3, (60.0 + 0.9 * i, 60.0, 0.0), d=d, inten=inten)
    sc.op("D")
    # Turns either side of the limit, 1 - cos 36.87 degrees: two points
    # make the first pair, a third straight on moves the last point, and a
    # fourth turns.
    for k, deg in enumerate((36.0, 36.8, 36.86, 36.88, 37.0, 37.3, 38.0)):
        x0, y0 = -200.0, -100.0 + 10.0 * k
        th = math.radians(deg)
        for p in ((x0, y0), (x0 + 0.6, y0), (x0 + 1.2, y0),
                  (x0 + 1.2 + 0.6 * math.cos(th), y0 + 0.6 * math.sin(th)),
                  (x0 + 1.2 + 1.2 * math.cos(th), y0 + 1.2 * math.sin(th))):
            sc.follow(3, 3, (p[0], p[1], 0.0))
        sc.op("MN 3")
    sc.op("D")
    sc.op("DH")
    sc.op("DH")
    sc.op("D")


def s_clans(sc):
    # The squares' edges, both signs, and far enough to saturate.
    for x, y in ((0.0, 0.0), (-0.0, 0.0), (63.99998, 0.0), (64.0, 0.0),
                 (-0.00001, 0.0), (-64.0, 0.0), (-64.00001, 0.0),
                 (0.0, 63.99998), (0.0, 64.0), (0.0, -64.0), (1e-8, -1e-8),
                 (40000.0, 0.0), (-40000.0, 0.0), (0.0, 40000.0),
                 (0.0, -40000.0), (4194304.0, -4194304.0),
                 (2047.9, -2048.1)):
        sc.op("GC %s %s %s" % (h(x), h(y), h(1.5)))
    sc.op("W 900")
    sc.op("GC %s %s %s" % (h(0.0), h(0.0), h(0.0)))
    sc.op("D")
    # A short trail in each of 48 squares: the clan pool runs full, and the
    # oldest squares go with their sets, two of them still a maker's.
    for k in range(48):
        sc.op("W %d" % (1000 + 37 * k))
        cx = -1500.0 + 64.0 * (k % 9) + 20.0
        cy = 700.0 - 64.0 * (k // 9) - 13.0
        m = 4 + k % 2
        for i in range(3):
            sc.follow(m, k % 2, (cx + 0.5 * i, cy + 0.1 * i, 3.0))
        if k % 5 == 0:
            sc.op("MN %d" % m)
    sc.op("D")
    sc.op("W 9000")
    sc.op("GC %s %s %s" % (h(-1480.0 + 64.0), h(687.0), h(3.0)))
    sc.op("D")


def s_setpool(sc):
    # A zigzag in one square: each leg ends its set, and past 128 sets the
    # pool frees the tail's, a maker's own among them.
    sc.op("W 12000")
    x, y = 300.0, 300.0
    for k in range(150):
        dx, dy = (0.6, 0.0) if k % 2 == 0 else (0.0, 0.6)
        for i in range(3):
            x += dx
            y += dy
            sc.follow(6 + k % 2, 3, (x, y, 0.0))
        if k % 40 == 39:
            sc.op("D")
    sc.op("D")


def s_flush(sc):
    sc.op("FC")
    sc.op("D")
    sc.follow(6, 3, (310.0, 310.0, 0.0))
    sc.follow(6, 3, (310.6, 310.0, 0.0))
    sc.op("CC")
    sc.op("CS")
    sc.op("D")
    sc.op("CC")
    sc.op("CS")
    sc.op("IC")
    sc.op("IS")
    sc.op("D")
    sc.follow(6, 3, (311.2, 310.0, 0.0))
    sc.follow(6, 3, (311.8, 310.0, 0.0))
    sc.op("D")


def s_wheels(sc):
    """MaybeMakeSkids: the gates, then trails."""
    sc.op("W 30000")
    x0, y0 = 800.0, -600.0
    for i in range(NUM_WHEELS):
        sc.wheel(i)
        sc.place(i, (x0 + 30.0 * (i // 2) + 1.6 * (i % 2), y0, 0.35))
    sc.car(0, x0 + 0.8, y0, 0.6)
    sc.car(1, x0 + 30.8, y0, 0.6)
    sc.op("BL 0 00")
    sc.op("BL 1 00")
    sc.op("D")
    pos = [y0]

    def frame(i=0, car=0, step=0.4, yaw=0.0, ha=0.0, hb=0.0, z=0.35,
              pitch=0.0, roll=0.0, **kw):
        pos[0] += step
        x = x0 + 30.0 * car + 1.6 * (i % 2)
        sc.car(car, x0 + 30.0 * car + 0.8, pos[0], z + 0.25)
        sc.wheel(i, **kw)
        sc.place(i, (x, pos[0], z), yaw=yaw, pitch=pitch, roll=roll)
        sc.maybe(i, car, ha, hb)

    # One gate at a time, on wheel 0 going ahead.
    for kw in (dict(), dict(slip=0, zf=16.0, tu=0.5),
               dict(slip=0, zf=16.0001, tu=0.5), dict(slip=0),
               dict(slip=0, zf=-3000.0, tu=-0.4),
               dict(slip=0, zf=3000.0, tu=-0.4), dict(),
               dict(touch=0), dict(slip=2, touch=2), dict(v=(0.0, 1.0)),
               dict(v=(0.6, 0.8)), dict(v=(0.0, 1.0001)),
               dict(v=(-0.001, 1.0)), dict(v=(0.0, -6.0)),
               dict(v=(-1.0, 0.0)), dict(v=(80.0, 3.0))):
        frame(**kw)
    sc.op("D")
    # The blown tires: this wheel's bit, another's, all, and the top bit
    # under a signed shift, which reaches a wheel number past 7.
    for bits, wn in (("01", 0), ("02", 0), ("0e", 0), ("ff", 0), ("80", 0),
                     ("08", 3), ("80", 3), ("f7", 3), ("80", 8),
                     ("00", 0)):
        sc.op("BL 0 %s" % bits)
        frame(wn=wn)
    sc.op("D")
    # Rolling straight and pressing: nothing sideways, so the least
    # width and the least intensity.
    for k in range(12):
        frame(slip=0, v=(0.0, 8.0), step=0.27)
    sc.op("D")
    # A drift from straight to broadside, then back, the ground sloping
    # under the edges both ways.
    for k in range(40):
        a = math.radians(90.0 * math.sin(math.pi * k / 39.0))
        tilt = 0.04 * math.sin(0.7 * k)
        frame(slip=1 if k % 9 else 0, yaw=0.3 * math.sin(0.2 * k),
              v=(-9.0 * math.sin(a), 9.0 * math.cos(a)),
              ha=0.1 + tilt, hb=0.1 - tilt, step=0.3,
              width=0.25 + 0.01 * (k % 5))
    frame(touch=0)
    sc.op("D")
    # Every terrain, at 45 degrees: the width's multiplier, and the
    # puddle's nothing.
    for terr in range(NUM_TERRAIN):
        frame(terr=terr, v=(-5.0, 5.0), step=0.35, ha=0.02, hb=-0.01)
    frame(touch=0)
    sc.op("D")
    # Pitched and rolled; edges far apart in height; the wheel high over
    # the car; no width.
    for kw in (dict(pitch=0.3), dict(roll=0.25, pitch=-0.2, yaw=1.0),
               dict(ha=0.5, hb=-0.5), dict(ha=-3.0, hb=2.0),
               dict(ha=1e-6, hb=0.0), dict(z=8.0, ha=8.0, hb=8.0),
               dict(width=0.0), dict(), dict(width=1.2, v=(-7.0, 0.5))):
        frame(v=kw.pop("v", (-4.0, 6.0)), **kw)
    sc.op("D")
    # The other wheels, two to a car.
    for k in range(10):
        for i in range(NUM_WHEELS):
            frame(i=i, car=i // 2, step=0.2 if i % 2 else 0.0,
                  slip=(k + i) % 3 != 0, v=(-3.0 - i, 5.0 + k))
    sc.op("D")


def s_wheel_random(sc, n=300):
    rng = random.Random(0x5eed78b)
    cars = [[rng.uniform(-200, 200), rng.uniform(-200, 200), 0.0,
             rng.uniform(0, 2 * math.pi), 0.0, 8.0] for _ in range(2)]
    t = 40000
    for k in range(n):
        c = rng.randrange(2)
        x, y, z, yaw, slide, speed = cars[c]
        yaw += rng.gauss(0.0, 0.08)
        slide = max(-1.6, min(1.6, slide + rng.gauss(0.0, 0.15)))
        speed = max(0.0, min(60.0, speed + rng.gauss(0.0, 1.5)))
        step = speed / 30.0
        x -= step * math.sin(yaw + slide)
        y += step * math.cos(yaw + slide)
        z = 0.5 * math.sin(0.01 * x) + 0.3 * math.cos(0.013 * y)
        cars[c] = [x, y, z, yaw, slide, speed]
        if k % 10 == 0:
            t += rng.randrange(1, 60)
            sc.op("W %d" % t)
        if rng.random() < 0.02:
            sc.op("BL %d %02x" % (c, rng.choice((0, 0, 1, 2, 4, 8, 0x0f))))
        sc.car(c, x, y, z + 0.3)
        v = (-speed * math.sin(yaw + slide), speed * math.cos(yaw + slide))
        terr = rng.choice((1, 1, 1, 2, 3, 4, 6, 7, 0, 12))
        for side in (0, 1):
            i = 2 * c + side
            off = -0.8 if side == 0 else 0.8
            px = x + off * math.cos(yaw)
            py = y + off * math.sin(yaw)
            sc.wheel(i, terr=terr, slip=int(abs(slide) > 0.2
                                            or rng.random() < 0.1),
                     touch=int(rng.random() < 0.95),
                     zf=rng.uniform(0.0, 6000.0),
                     tu=rng.choice((0.0, 0.001, 0.003, 0.5, 1.0)),
                     width=rng.choice((0.2, 0.25, 0.3)), v=v)
            sc.place(i, (px, py, z), yaw=yaw,
                     pitch=rng.uniform(-0.05, 0.05),
                     roll=rng.uniform(-0.05, 0.05))
            g = 0.02 * math.sin(0.3 * px + 0.2 * py)
            sc.maybe(i, c, z + g, z - g)
    sc.op("D")


def s_random(sc, n=1500):
    rng = random.Random(0x5c1d)
    cars = [[rng.uniform(-300, 300), rng.uniform(-300, 300),
             rng.uniform(-5, 5), rng.uniform(0, 2 * math.pi)]
            for _ in range(NUM_CARS)]
    t = 20000
    for k in range(n):
        c = rng.randrange(NUM_CARS)
        x, y, z, a = cars[c]
        r = rng.random()
        if r < 0.05:
            a += rng.uniform(-2.0, 2.0)
        else:
            a += rng.gauss(0.0, 0.05)
        step = rng.choice((0.05, 0.12, 0.3, 0.6, 1.1, 2.5, 0.0))
        x += step * math.cos(a)
        y += step * math.sin(a)
        z += rng.uniform(-0.02, 0.02)
        cars[c] = [x, y, z, a]
        t += rng.randrange(0, 40)
        if k % 10 == 0:
            sc.op("W %d" % t)
        bits = 0xffffffff if rng.random() < 0.95 else rng.choice(
            (0xfffffffb, 0x6, 0x2, 0x0))
        sc.car(c, x, y, z + 0.4, bits)
        m = 2 * c + rng.randrange(2)
        if rng.random() < 0.08:
            sc.op("MN %d" % m)
            continue
        side = 0.8 if m % 2 else -0.8
        p = (x - side * math.sin(a), y + side * math.cos(a), z)
        if rng.random() < 0.02:
            p = (p[0] + 4.5, p[1], p[2])
        w = rng.choice((0.1, 0.15, 0.2))
        sc.skid(m, c, p, d=(-w * math.sin(a), w * math.cos(a), 0.0),
                terr=rng.choice((1, 1, 1, 2, 3, 6, 7)),
                inten=rng.uniform(0.1, 1.0))
        if rng.random() < 0.003:
            sc.op("FC")
        if rng.random() < 0.002:
            sc.op("DH")
    sc.op("D")


def script():
    sc = Script()
    for k in range(NUM_CARS):
        sc.car(k, 0.0, 0.0, 0.0)
    s_basics(sc)
    s_curves(sc)
    s_breaks(sc)
    s_clans(sc)
    s_setpool(sc)
    s_flush(sc)
    s_wheels(sc)
    s_wheel_random(sc)
    s_random(sc)
    sc.op("CC")
    sc.op("CS")
    sc.op("D")
    return sc.ops


# ---- cut: what follows is not the model's

# ================================================================= running

def build_harness(tmp, name="skids_test"):
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

S = SKC

MUTATIONS = [
    # ---- the constants and the lists
    ("k-turn", S, "SkidTurnLimit      = 0.2f;", "SkidTurnLimit      = 0.21f;"),
    ("k-straight", S, "SkidStraightLimit  = 0.002f;",
     "SkidStraightLimit  = 0.0025f;"),
    ("k-int", S, "SkidIntensityScale = 1.0f / 255.0f;",
     "SkidIntensityScale = 1.0f / 256.0f;"),
    ("l-head", S, "    head->prev = n;" + NL + "    n->prev = list;",
     "    n->prev = list;"),
    ("l-tail", S, "    tail->next = n;" + NL + "    list->prev = n;",
     "    list->prev = n;"),
    ("l-unlink", S, "    n->next->prev = n->prev;" + NL, ""),
    # ---- the both-views bit
    ("v-null", S, "if (car == NULL)" + NL + "        return 0;",
     "if (car == NULL)" + NL + "        return 1;"),
    ("v-bit1", S, "if (((bits >> 1) & 1u) == 0)",
     "if (((bits >> 0) & 1u) == 0)"),
    ("v-bit2", S, "(int32_t)((bits >> 2) & 1u)", "(int32_t)((bits >> 3) & 1u)"),
    ("v-and", S, "    if (((bits >> 1) & 1u) == 0)" + NL + "        return 0;"
     + NL, ""),
    # ---- SkidSegment
    ("sp-x", S, "(int8_t)ee_trunc_w(delta->x * 64.0f)",
     "(int8_t)ee_trunc_w(delta->x * 63.0f)"),
    ("sp-y", S, "(int8_t)ee_trunc_w(delta->y * 64.0f)",
     "(int8_t)ee_trunc_w(delta->z * 64.0f)"),
    ("sp-z", S, "(int8_t)ee_trunc_w(delta->z * 64.0f)",
     "(int8_t)ee_trunc_w(delta->y * 64.0f)"),
    ("sp-round", S, "(int8_t)ee_trunc_w(delta->x * 64.0f)",
     "(int8_t)lrintf(delta->x * 64.0f)"),
    ("sp-pos", S, "    s->Position[1] = pos->y;", "    s->Position[1] = pos->x;"),
    ("gp-dx", S, "delta->x = (float)s->DeltaPosition[0] * (1.0f / 64.0f);",
     "delta->x = (float)s->DeltaPosition[0] * (1.0f / 32.0f);"),
    ("gp-dz", S, "delta->z = (float)s->DeltaPosition[2] * (1.0f / 64.0f);",
     "delta->z = (float)s->DeltaPosition[1] * (1.0f / 64.0f);"),
    ("gp-null", S, "if (delta != NULL) {", "if (delta == NULL) {"),
    ("gp-pos", S, "    pos->z = s->Position[2];", "    pos->z = s->Position[1];"),
    # ---- SkidSet's constructor and destructor
    ("ct-terr", S, "s->TheTerrainType = terrain;", "s->TheTerrainType = 1;"),
    ("ct-maker", S, "s->pSkidMaker = maker;", "s->pSkidMaker = NULL;"),
    ("ct-car", S, "s->pCar = car;", "s->pCar = NULL;"),
    ("ct-both", S, "s->bVisibleToBothPlayers = visible_to_both_players(car);",
     "s->bVisibleToBothPlayers = 0;"),
    ("ct-pos", S, "    s->Position = *pos;", "    s->Position = *delta;"),
    ("ct-box", S, "bInitializeBoundingBox3At(&s->BBoxMin, &s->BBoxMax, pos);",
     "bInitializeBoundingBox3At(&s->BBoxMin, &s->BBoxMax, delta);"),
    ("ct-centre", S, "    s->Centre = *pos;", "    s->Centre = *delta;"),
    ("ct-clan-tail", S, "add_tail(&clan->SkidSetList, &node->Node);",
     "add_head(&clan->SkidSetList, &node->Node);"),
    ("ct-add", S, "    skidset_add_segment(s, pos, delta, intensity);" + NL
     + "    return s;", "    return s;"),
    ("dt-maker", S, "    if (s->pSkidMaker != NULL)" + NL
     + "        skidmaker_make_no_skid(s->pSkidMaker);" + NL, ""),
    ("dt-unlink", S, "    unlink_node(&s->pClanNode->Node);" + NL, ""),
    ("dt-free", S, "    if ((flags & 1) != 0)" + NL
     + "        bSlotFree(SkidSetSlotPool, s);",
     "    if ((flags & 1) == 0)" + NL + "        bSlotFree(SkidSetSlotPool, s);"),
    # ---- AddSegment
    ("as-n0", S, "    if (n > 0) {", "    if (n > 1) {"),
    ("as-way", S, "way.x = pos->x - last->Position[0];",
     "way.x = last->Position[0] - pos->x;"),
    ("as-len2", S, "len2 = (way.x * way.x + way.y * way.y) + way.z * way.z;",
     "len2 = way.x * way.x + way.y * way.y;"),
    ("as-step", S, "step = sqrtf(len2);", "step = len2;"),
    ("as-q", S, "        q = ee_div(1.0f, sqrtf(len2));",
     "        q = 1.0f / sqrtf(len2);"),
    ("as-norm", S, "        way.y *= q;" + NL, ""),
    ("as-n2", S, "    if (n >= 2) {", "    if (n >= 3) {"),
    ("as-turn", S, "float turn = 1.0f - ((way.x", "float turn = 0.5f - ((way.x"),
    ("as-dotz", S, "+ way.z * s->LastNormal.z);", "+ way.y * s->LastNormal.z);"),
    ("as-len", S, "float len = s->LastSegmentLength + step;",
     "float len = step;"),
    ("as-tlim", S, "if (SkidTurnLimit < turn) {", "if (0.25f < turn) {"),
    ("as-tfin", S, "            skidset_finished_adding_skids(s);" + NL
     + "            return 0;", "            return 0;"),
    ("as-tret", S, "            return 0;" + NL + "        }" + NL
     + "        if (len < 0.25f)",
     "            return 1;" + NL + "        }" + NL + "        if (len < 0.25f)"),
    ("as-short", S, "if (len < 0.25f)", "if (len < 0.2f)"),
    ("as-straight", S, "if (turn < SkidStraightLimit)",
     "if (turn < SkidStraightLimit * 2.0f)"),
    ("as-long", S, "if (3.0f < len)", "if (2.5f < len)"),
    ("as-long-off", S, "        if (3.0f < len)" + NL + "            merge = 0;"
     + NL, ""),
    ("as-mlen", S, "s->LastSegmentLength = s->LastSegmentLength + step;",
     "s->LastSegmentLength = step;"),
    ("as-full", S, "if (n == SKIDSET_MAX_SEGMENTS)",
     "if (n == SKIDSET_MAX_SEGMENTS - 1)"),
    ("as-normal-1", S, "        if (n + 1 >= 2)" + NL
     + "            s->LastNormal = way;", "        s->LastNormal = way;"),
    ("as-normal-off", S, "        if (n + 1 >= 2)" + NL
     + "            s->LastNormal = way;" + NL, ""),
    ("as-slen", S, "        s->LastSegmentLength = step;" + NL + "    }",
     "        s->LastSegmentLength = 0.0f;" + NL + "    }"),
    ("as-int", S, "ee_trunc_w(intensity * 255.0f)",
     "ee_trunc_w(intensity * 256.0f)"),
    ("as-int-round", S, "(uint8_t)ee_trunc_w(intensity * 255.0f)",
     "(uint8_t)lrintf(intensity * 255.0f)"),
    ("as-box", S, "bExpandBoundingBox3R(&s->BBoxMin, &s->BBoxMax, pos, step);",
     "bExpandBoundingBox3R(&s->BBoxMin, &s->BBoxMax, pos, 0.0f);"),
    ("as-clanbox", S, "    clan_expand_bounding_box(s->pClan, &s->BBoxMin, "
     "&s->BBoxMax);" + NL, ""),
    ("as-cx", S, "s->Centre.x = (s->BBoxMin.x + s->BBoxMax.x) * 0.5f;",
     "s->Centre.x = s->BBoxMax.x;"),
    ("as-cz", S, "s->Centre.z = (s->BBoxMin.z + s->BBoxMax.z) * 0.5f;",
     "s->Centre.z = (s->BBoxMin.y + s->BBoxMax.z) * 0.5f;"),
    ("as-ret", S, "    s->Centre.pad = (s->BBoxMin.pad + s->BBoxMax.pad) * 0.5f;"
     + NL + "    return 0;",
     "    s->Centre.pad = (s->BBoxMin.pad + s->BBoxMax.pad) * 0.5f;" + NL
     + "    return 1;"),
    # ---- FinishedAddingSkids, GetLastPoints, CreateNewSkidSet
    ("fa-maker", S, "        s->pSkidMaker->pSkidSet = NULL;" + NL, ""),
    ("fa-set", S, "        s->pSkidMaker = NULL;" + NL, ""),
    ("gl-index", S, "&s->SkidSegments[s->NumSkidSegments - 1], pos,",
     "&s->SkidSegments[0], pos,"),
    ("cn-tail", S, "SkidSet *tail = (SkidSet *)(void *)SkidSetList.prev;",
     "SkidSet *tail = (SkidSet *)(void *)SkidSetList.next;"),
    ("cn-unlink", S, "        unlink_node(&tail->Node);" + NL
     + "        skidset_destroy(tail, 3);", "        skidset_destroy(tail, 3);"),
    ("cn-flags", S, "skidset_destroy(tail, 3);", "skidset_destroy(tail, 2);"),
    ("cn-head", S, "    add_head(&SkidSetList, &s->Node);",
     "    add_tail(&SkidSetList, &s->Node);"),
    ("cn-omalloc", S, "skidset_construct((SkidSet *)bSlotMalloc(SkidSetSlotPool)",
     "skidset_construct((SkidSet *)bSlotOMalloc(SkidSetSlotPool)"),
    # ---- MakeSkid, MakeNoSkid
    ("ms-nocar", S, "    if (car != NULL) {" + NL + "        const bVector3 *g",
     "    if (0) {" + NL + "        const bVector3 *g"),
    ("ms-4", S, "if (4.0f < sqrtf(", "if (4.5f < sqrtf("),
    ("ms-4eq", S, "if (4.0f < sqrtf(", "if (4.0f <= sqrtf("),
    ("ms-dz", S, "float dz = g->z - pos->z;", "float dz = 0.0f;"),
    ("ms-dy", S, "sqrtf((dx * dx + dy * dy) + dz * dz)",
     "sqrtf(dx * dx + dz * dz)"),
    ("ms-new", S, "        m->pSkidSet = create_new_skid_set(m, car, pos, delta, "
     "terrain,", "        (void)create_new_skid_set(m, car, pos, delta, terrain,"),
    ("ms-vis", S, "    if (visible_to_both_players(car) == s->bVisibleToBothPlayers"
     + NL + "        && s->TheTerrainType == terrain",
     "    if (s->TheTerrainType == terrain"),
    ("ms-terr", S, "        && s->TheTerrainType == terrain" + NL, ""),
    ("ms-full", S, "skidset_add_segment(s, pos, delta, intensity) == 0)",
     "skidset_add_segment(s, pos, delta, intensity) <= 1)"),
    ("ms-reread", S, "    s = (SkidSet *)m->pSkidSet;" + NL
     + "    skidset_get_last_points", "    skidset_get_last_points"),
    ("ms-last-int", S, "                            last_intensity);",
     "                            intensity);"),
    ("ms-last-delta", S, "&last_pos, &last_delta, terrain,",
     "&last_pos, delta, terrain,"),
    ("ms-fin", S, "    skidset_finished_adding_skids(s);" + NL
     + "    s = create_new_skid_set(", "    s = create_new_skid_set("),
    ("ms-add", S, "    skidset_add_segment(s, pos, delta, intensity);" + NL
     + "    m->pSkidSet = s;", "    m->pSkidSet = s;"),
    ("ms-keep", S, "    m->pSkidSet = s;" + NL + "}", "}"),
    ("mn-off", S, "    if (m->pSkidSet != NULL)" + NL
     + "        skidset_finished_adding_skids((SkidSet *)m->pSkidSet);" + NL,
     ""),
    # ---- MaybeMakeSkids
    ("mk-hard-eq", S, "hard = 8.0f < w->ZForce", "hard = 8.0f <= w->ZForce"),
    ("mk-hard-k", S, "hard = 8.0f < w->ZForce", "hard = 9.0f < w->ZForce"),
    ("mk-hard-tu", S, "w->ZForce * w->TractionUsage;", "w->ZForce;"),
    ("mk-blown-off", S, "|| !w->TouchingGround || blown" + NL,
     "|| !w->TouchingGround" + NL),
    ("mk-blown-bit", S, ">> w->WI->WheelNumber) & 1;",
     ">> w->WI->WheelNumber) & 2;"),
    ("mk-blown-wn", S, ">> w->WI->WheelNumber) & 1;", ">> 0) & 1;"),
    ("mk-blown-sign", S, "((int32_t)(int8_t)car->BlownTireBits",
     "((int32_t)car->BlownTireBits"),
    ("mk-slip-only", S, "if (!(w->Slipping || hard)", "if (!w->Slipping"),
    ("mk-hard-only", S, "if (!(w->Slipping || hard)", "if (!hard"),
    ("mk-touch", S, "|| !w->TouchingGround || blown", "|| blown"),
    ("mk-speed-eq", S, "|| !(1.0f < sqrtf(w->Velocity.x",
     "|| !(1.0f <= sqrtf(w->Velocity.x"),
    ("mk-speed-y", S, "+ w->Velocity.y * w->Velocity.y)))",
     "+ w->Velocity.x * w->Velocity.x)))"),
    ("mk-noskid", S, "        skidmaker_make_no_skid(&w->TheSkidMaker);" + NL
     + "        return;", "        return;"),
    ("mk-across-x", S, "across.x = -w->Velocity.y;",
     "across.x = w->Velocity.y;"),
    ("mk-across-y", S, "across.y = w->Velocity.x;",
     "across.y = w->Velocity.y;"),
    ("mk-q", S, "q = ee_div(1.0f, sqrtf(len2));" + NL + "    across.x *= q;",
     "q = 1.0f;" + NL + "    across.x *= q;"),
    ("mk-q-y", S, "    across.y *= q;" + NL, ""),
    ("mk-ahead", S, "ahead = { 0.0f, 1.0f, 0.0f, 0.0f };",
     "ahead = { 1.0f, 0.0f, 0.0f, 0.0f };"),
    ("mk-ahead-z", S, "ahead = { 0.0f, 1.0f, 0.0f, 0.0f };",
     "ahead = { 0.0f, 1.0f, 0.5f, 0.0f };"),
    ("mk-abs", S, "d = fabsf((fwd.x * across.x + fwd.y * across.y) "
     "+ fwd.z * across.z);",
     "d = (fwd.x * across.x + fwd.y * across.y) + fwd.z * across.z;"),
    ("mk-dot-z", S, "+ fwd.z * across.z);", "+ fwd.z * across.y);"),
    ("mk-wide-off", S, "    if (d < 0.5f)" + NL + "        wide = 0.5f;" + NL,
     ""),
    ("mk-wide-k", S, "        wide = 0.5f;", "        wide = 0.4f;"),
    ("mk-wide-d", S, "    half = half * wide;" + NL, ""),
    ("mk-mult", S, "half = w->WI->Width * TerrainTypeInfoTable[w->Terrain]"
     ".SkidWidthMultiplier;", "half = w->WI->Width;"),
    ("mk-half", S, "    half = half * 0.5f;" + NL, ""),
    ("mk-norm1", S, "    bNormalize3To(&across, &across, half);" + NL + NL
     + "    // The two edges", NL + "    // The two edges"),
    ("mk-edge-b", S, "b.x = place->x - across.x;",
     "b.x = place->x + across.x;"),
    ("mk-edge-ay", S, "a.y = place->y + across.y;", "a.y = place->y;"),
    ("mk-edge-by", S, "b.y = place->y - across.y;", "b.y = place->y;"),
    ("mk-ha", S, "ha = edge_height(w, &a);", "ha = edge_height(w, &b);"),
    ("mk-topo", S, "((const CarState *)w->CS)->pTopologyCoordinate, pos,",
     "NULL, pos,"),
    ("mk-px", S, "point.x = place->x;", "point.x = a.x;"),
    ("mk-pz", S, "point.z = (ha + hb) * 0.5f;", "point.z = ha;"),
    ("mk-pz-place", S, "point.z = (ha + hb) * 0.5f;",
     "point.z = place->z;"),
    ("mk-tilt", S, "across.z = ha * 0.5f - hb * 0.5f;",
     "across.z = hb * 0.5f - ha * 0.5f;"),
    ("mk-tilt-off", S, "    across.z = ha * 0.5f - hb * 0.5f;" + NL, ""),
    ("mk-norm2", S, "    across.z = ha * 0.5f - hb * 0.5f;" + NL
     + "    bNormalize3To(&across, &across, half);",
     "    across.z = ha * 0.5f - hb * 0.5f;"),
    ("mk-press", S, "    if (!w->Slipping)" + NL
     + "        intensity = intensity * SkidPressOnly;" + NL, ""),
    ("mk-press-k", S, "SkidPressOnly      = 1.0f / 3.0f;",
     "SkidPressOnly      = 0.33f;"),
    ("mk-puddle", S, "if (w->Terrain == TERRAIN_TYPE_PUDDLE)",
     "if (w->Terrain == 5)"),
    ("mk-puddle-min", S, "        intensity = 0.0f;" + NL + "    else if",
     "        intensity = 0.0f;" + NL + "    if"),
    ("mk-min-k", S, "SkidMinIntensity   = 0.3f;",
     "SkidMinIntensity   = 0.25f;"),
    ("mk-min-off", S, "    else if (intensity < SkidMinIntensity)" + NL
     + "        intensity = SkidMinIntensity;" + NL, ""),
    ("mk-terr", S, "&point, &across, w->Terrain,", "&point, &across, 1,"),
    ("mk-car", S, "skidmaker_make_skid(&w->TheSkidMaker, car,",
     "skidmaker_make_skid(&w->TheSkidMaker, NULL,"),
    ("mk-delta", S, "&point, &across, w->Terrain,",
     "&point, &fwd, w->Terrain,"),
    # ---- InitSkids, CloseSkids, DeleteThisSkid
    ("is-once", S, "    if (SkidSetSlotPool == NULL) {", "    if (1) {"),
    ("is-slots", S, "SKIDSET_POOL_SLOTS, \"SkidSetSlotPool\",",
     "SKIDSET_POOL_SLOTS - 1, \"SkidSetSlotPool\","),
    ("is-mem", S, "\"SkidSetSlotPool\"," + NL + "                                       16);",
     "\"SkidSetSlotPool\"," + NL + "                                       15);"),
    ("is-flag", S, "        bClearSlotPoolFlag(SkidSetSlotPool, "
     "BSP_OVERFLOW_IF_FULL);" + NL, ""),
    ("is-texnull", S, "        SkidTextureInfo[i] = NULL;" + NL
     + "        if (name != NULL)", "        if (name != NULL)"),
    ("is-def", S, "GetTextureInfo(bchunk_hash(name), 1, 0);",
     "GetTextureInfo(bchunk_hash(name), 0, 0);"),
    ("is-hash", S, "GetTextureInfo(bchunk_hash(name), 1, 0);",
     "GetTextureInfo(bchunk_hash(name) ^ 8u, 1, 0);"),
    ("is-plot", S, "    PlotSkidsInCaffeine = 0;" + NL, ""),
    ("is-plot2", S, "    PlotSkidPointsInCaffeine = 0;" + NL, ""),
    ("cs-del", S, "        bDeleteSlotPool(SkidSetSlotPool);" + NL, ""),
    ("cs-null", S, "        SkidSetSlotPool = NULL;" + NL, ""),
    ("cs-tex", S, "i = NUM_TERRAIN_TYPES - 1; i >= 0; i--",
     "i = NUM_TERRAIN_TYPES - 1; i >= 2; i--"),
    ("dts-unlink", S, "    unlink_node(&s->Node);" + NL
     + "    skidset_destroy(s, 3);", "    skidset_destroy(s, 3);"),
    # ---- Clan
    ("cc-pos", S, "    c->Position = *pos;", "    c->Position.x = pos->x;"),
    ("cc-hash", S, "    c->Hash = hash;", "    c->Hash = hash + 1u;"),
    ("cc-box", S, "    bInitializeBoundingBox3At(&c->BBoxMin, &c->BBoxMax, pos);"
     + NL, ""),
    ("cd-loop", S, "    while (list->next != list)",
     "    if (list->next != list)"),
    ("cd-free", S, "    if ((flags & 1) != 0)" + NL
     + "        bSlotFree(ClanSlotPool, c);",
     "    if ((flags & 1) == 0)" + NL + "        bSlotFree(ClanSlotPool, c);"),
    ("ce-box", S, "bExpandBoundingBox3Box(&c->BBoxMin, &c->BBoxMax, mn, mx);",
     "bExpandBoundingBox3Box(&c->BBoxMin, &c->BBoxMax, mn, mn);"),
    ("ic-once", S, "    if (ClanSlotPool == NULL)" + NL
     + "        ClanSlotPool = bNewSlotPool",
     "    if (1)" + NL + "        ClanSlotPool = bNewSlotPool"),
    ("ic-slots", S, "CLAN_POOL_SLOTS,", "CLAN_POOL_SLOTS + 1,"),
    ("ic-mem", S, "\"ClanSlotPool\", 16);", "\"ClanSlotPool\", 0);"),
    ("fc-order", S, "for (n = ClanList.next; n != &ClanList; n = ClanList.next)",
     "for (n = ClanList.prev; n != &ClanList; n = ClanList.prev)"),
    ("fc-unlink", S, "        unlink_node(n);" + NL
     + "        clan_destroy((Clan *)(void *)n, 3);",
     "        clan_destroy((Clan *)(void *)n, 3);"),
    ("cl-flush", S, "        flush_clans();" + NL, ""),
    ("cl-null", S, "        ClanSlotPool = NULL;" + NL, ""),
    # ---- GetClan
    ("gc-trunc", S, "int32_t  x = ee_trunc_w(pos->x * 65536.0f);",
     "int32_t  x = (int32_t)(pos->x * 65536.0f);"),
    ("gc-y", S, "ee_trunc_w(pos->y * 65536.0f)", "ee_trunc_w(pos->z * 65536.0f)"),
    ("gc-scale", S, "ee_trunc_w(pos->x * 65536.0f)",
     "ee_trunc_w(pos->x * 32768.0f)"),
    ("gc-shift", S, "((uint32_t)(y >> 22) << 16)", "((uint32_t)(y >> 23) << 16)"),
    ("gc-sign", S, "((uint32_t)(y >> 22) << 16)", "(((uint32_t)y >> 22) << 16)"),
    ("gc-mask", S, "((uint32_t)(x >> 22) & 0xffffu)",
     "((uint32_t)(x >> 22) & 0x3ffu)"),
    ("gc-stamp", S, "            c->LastUpdateTime = WorldTime;" + NL, ""),
    ("gc-mru", S, "            unlink_node(n);" + NL
     + "            c->LastUpdateTime = WorldTime;" + NL
     + "            add_head(&ClanList, n);",
     "            c->LastUpdateTime = WorldTime;"),
    ("gc-tail", S, "bNode *tail = ClanList.prev;", "bNode *tail = ClanList.next;"),
    ("gc-tunlink", S, "        unlink_node(tail);" + NL
     + "        clan_destroy((Clan *)(void *)tail, 3);",
     "        clan_destroy((Clan *)(void *)tail, 3);"),
    ("gc-malloc", S, "clan_construct((Clan *)bSlotOMalloc(ClanSlotPool)",
     "clan_construct((Clan *)bSlotMalloc(ClanSlotPool)"),
    ("gc-head", S, "    add_head(&ClanList, &c->Node);" + NL + "    return c;",
     "    add_tail(&ClanList, &c->Node);" + NL + "    return c;"),
]

EQUIVALENT = {
    "ct-centre":
        "the constructor ends in AddSegment, which sets the centre from the "
        "box whatever it was",
    "as-normal-1":
        "LastNormal is read, and printed, only with two segments or more, "
        "and the second segment's way is written over the first's",
    "ms-reread":
        "the new-set path is reached only with the maker still holding the "
        "set: one that finished itself on a turn answered 0 and returned",
    "is-texnull":
        "the terrains without a skid texture are the same nine every time, "
        "so their entries are never anything but NULL",
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    indir = tempfile.TemporaryDirectory()
    lines, scp = write_inputs(indir.name)
    base_lines = model(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text(encoding="latin-1").splitlines()
        if diff(base_lines, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "skids_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base_lines, diff, EQUIVALENT, jobs)
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
