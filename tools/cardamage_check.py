#!/usr/bin/env python3
"""Cross-check 3DS Files/source/cardamage.c -- CarDamage and BodyDamage,
retail 0x001b4760 .. 0x001b5c50 -- against the retail image, SLES_507.31,
run in mipsemu. eModel's environment mapping is loadertable_check.py's.

**The model** is retail's own code: LoaderBodyDamage and its unloader,
FindBodyDamageInfo, BodyDamageModel::Init and CallDamageVertexFunction,
DamageVertexFunction and its wrapper, BodyDamage's constructor,
destructor, SetALevelBodyDamageInfo, AddModel, SetDamage,
RepairAllDamage, the zone of a point, GetDamageAmount, the GetVisible*
and GetCompressed* getters, ApplyDamage and SetEnvironmentMapping;
CarDamage's constructor, destructor, item parts, AddDamage, item levels,
the damage to one zone, RethinkDamage, ApplyDamage, the wreck and
RepairAll; CallDamageVertexFunctionForEveryVertex (0x00104100) and
eStripData's GetNumVerts, GetElementXYZ, GetXYZ, SetXYZ and
GetElementRGBA, which the harness takes from estripdata.c; and
GetModelNumVertices and bStringHash,
over BodyDamageInfoList (gp-18832) and
BodyDamageList (gp-18824), which the script empties as retail's static
constructor does, and TheRaceParameters.DamageEnabled (0x0031a8d8). The
item table (0x00313b80), the three cars without windows (0x00313d60) and
the effects' scales (0x00313d78) are the image's own.

**The seams.** What CarDamage calls out of its object the model stubs and
the harness (tools/src/cardamage_test.c) stands in for, and both print the
call: eFindPositionMarker (0x001a7f78, which answers from the script's
markers by name and type), collision_sound::PlayGlass (0x001e5660),
Car::TriggerEffect (0x0011e2b8; the port's gCarTriggerEffectFn),
UpdateCarReplacementTextures (0x0011ff60), eModel::SetEnvironmentMapping
(0x0010cae0) and __builtin_delete (0x00114e98; the port's bFree). bMemSet
is native. The port's own seam, gESolidVerticesChangedFn at the end of
the walk, prints the solid in the harness; the model hooks the walk's
epilogue (0x00104260) and prints the solid it kept at 44(sp), which the
walk stores before its test for none.

**The layouts.** The script gives each info chunk, car, solid, model and
marker by its numbers; the model lays them out as the image does (a Car's
CarTypeInfo at 12, RideInfo at 16, position at 96 and render info at
1200; an eSolid's NumStrips at 52 and StripEntryTable at 176, and an
eStripEntry's Data at 8, Flags at 14 and NumVerts at 29) and the harness
builds the host's structs. A strip's packet is 1,024 bytes from a seed
(see the harness), the same bytes on both sides. A pointer prints as what
it is (see the harness).

**The script**: the loader's guard and the list over loads, unloads and
finds, with a name twice; cars of each window-less type and others; models
whose vertex counts match their info, do not, are 0, or have no solid,
and a name that is not there; the zone of a grid of points round the box
and on its diagonals, without an info and over a box with no width;
SetDamage over and under range and at the byte's edges; ApplyDamage either
side of its 0.02 and back at 0, with damage on and off; the items found on
markers, missing ones and ones of another car; hits on a car without an
info, below 0.05, below 0.2, and above, the zone change undone, levels
rising and falling, each zone at exactly the thresholds, the glass, the
effects, the textures and the windows' environment mapping; the wreck,
the repair, the destructor with and without the delete; random hits,
zones and repairs over five cars; and the vertices: strips of every
count from none to 30, in and past the groups of four, scuff strips and
a hidden one, under a body and a polys-only model, keys with dents and
without, colour steps up and down that wrap, each repeat count, zones at
the alpha's 64 and 65 of 128 and full, with the damage on and off, the
repair and the seam off; then random keys and strips under random damage,
each vertex and each packet's bytes dumped as it goes.

    python tools/cardamage_check.py
    python tools/cardamage_check.py --mutate [--only a,b]
"""
import argparse
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
from bhash import bhash                 # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/cardamage_test.c"
CDC = "3DS Files/source/cardamage.c"
ESD = "3DS Files/source/estripdata.c"
SOURCES = [HARNESS, CDC, ESD]
HARNESS_TIMEOUT = 120

GP = retail_model.RETAIL_GP
INFO_LIST = GP - 18832
BD_LIST = GP - 18824
DAMAGE_ON = 0x0031a8d8
BODY_DAMAGE_ID = 0x00034030

F_LOAD, F_UNLOAD, F_FIND = 0x001b4760, 0x001b47b0, 0x001b47e8
F_SETALEVEL, F_ADDMODEL = 0x001b4cd8, 0x001b4d10
F_SETDAMAGE, F_BREPAIR = 0x001b4d48, 0x001b4dc0
F_ZONE, F_AMOUNT = 0x001b4e10, 0x001b4f10
F_VISAT, F_VIS, F_CVIS, F_TOTAL = 0x001b5030, 0x001b5068, 0x001b50a8, \
    0x001b50c8
F_BAPPLY, F_BENV = 0x001b5108, 0x001b5250
F_CTOR, F_DTOR, F_PARTS, F_ADD = 0x001b54b0, 0x001b5538, 0x001b5598, \
    0x001b56b0
F_STATES, F_ADDZONE = 0x001b57a0, 0x001b58c8
F_RETHINK, F_APPLY, F_WRECK, F_REPAIR = 0x001b5a78, 0x001b5aa8, \
    0x001b5bc8, 0x001b5c20

S_FINDPM = 0x001a7f78
S_GLASS = 0x001e5660
S_EFFECT = 0x0011e2b8
S_TEXTURES = 0x0011ff60
S_ENVMAP = 0x0010cae0
W_END = 0x00104260
F_GETXYZ, F_GETRGBA = 0x0011c2b8, 0x0011c180
S_DELETE = 0x00114e98
S_MEMSET = 0x00250340

INFO = 84
CAR_SIZE = 2400
NSTRIP = 16
PACKET = 1024


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def H(f):
    """A float as its bits, for the script."""
    return "0x%08x" % fbits(f)


def X(v):
    return "0x%08x" % (v & M32)


# ================================================================== model

class Model(object):
    def __init__(self):
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True,
                                            eesqrt=True)
        self.out = []
        e.stub(S_FINDPM, self.find_pm)
        e.stub(S_GLASS, lambda e: self.emit("  glass %s"
                                            % self.label(e.reg[4])))
        e.stub(S_EFFECT, self.effect)
        e.stub(S_TEXTURES, lambda e: self.emit("  textures %s"
                                               % self.label(e.reg[4])))
        e.stub(S_ENVMAP, lambda e: self.emit("  envmap %s %08x %d" % (
            self.label(e.reg[4]), e.reg[5] & M32, s32(e.reg[6]))))
        e.hook(W_END, self.walked)
        e.stub(S_DELETE, lambda e: self.emit("  delete %s"
                                             % self.label(e.reg[4])))

        def memset(e):
            a, v, n = e.reg[4] & M32, e.reg[5] & 0xff, s32(e.reg[6])
            e.mem[a:a + n] = bytes([v]) * n
            return a
        e.stub(S_MEMSET, memset)
        self.reset()

    def emit(self, line):
        self.out.append(line)

    # ---- the stubs

    def find_pm(self, e):
        name, typ, prev = (e.reg[r] & M32 for r in (4, 5, 6))
        self.emit("  pm %08x %08x %s" % (name, typ, self.label(prev)))
        for m, n, t in self.marks:
            if n == name and t == typ:
                return m
        return 0

    def effect(self, e):
        self.emit("  effect %s fx=%d scale=%08x where=%d at=%s" % (
            self.label(e.reg[4]), s32(e.reg[5]), e.fpr[12] & M32,
            s32(e.reg[6]), self.label(e.reg[7])))

    def walked(self, e):
        s = e.u32((e.reg[29] & M32) + 44)
        if s != 0 and self.seam:
            self.emit("  changed %s" % self.label(s))

    # ---- the objects

    def reset(self):
        e = self.e
        e.reset_heap()
        for h in (INFO_LIST, BD_LIST):
            e.put32(h, h)
            e.put32(h + 4, h)
        e.put32(DAMAGE_ON, 1)
        self.lab = {INFO_LIST: "IH", BD_LIST: "BH"}
        self.info, self.car, self.dmg = {}, {}, {}
        self.solid, self.model = {}, {}
        self.marks = []
        self.seam = True
        self.scratch = e.alloc(16, align=16)

    def name(self, label, addr):
        for a in [a for a, v in self.lab.items()
                  if v == label or v.startswith(label + ".")]:
            del self.lab[a]
        self.lab[addr] = label

    def label(self, v):
        v &= M32
        if v == 0:
            return "0"
        return self.lab.get(v, "?")

    def string(self, s):
        b = s.encode("latin-1") + b"\0"
        p = self.e.alloc(len(b) + 8, align=8)
        self.e.write(p, b)
        return p

    def floats(self, *bits):
        p = self.e.alloc(4 * len(bits) + 16, align=16)
        for i, b in enumerate(bits):
            self.e.put32(p + 4 * i, b)
        return p

    # ---- dumps

    def dump_list(self, name, head, limit):
        e = self.e
        for nm, off in ((name, 0), (name + " back", 4)):
            parts = []
            n, steps = e.u32(head + off), 0
            while n != head and steps < limit:
                lb = self.label(n)
                parts.append(lb)
                if lb in ("?", "0"):
                    break
                n = e.u32(n + off)
                steps += 1
            self.emit("  %s%s" % (nm, "".join(" " + p for p in parts)))

    def dump_infos(self):
        self.dump_list("infos", INFO_LIST, 32 + 2)

    def dump_bodies(self):
        self.dump_list("bodies", BD_LIST, 8 + 2)

    def dump_damage(self, c):
        e = self.e
        d = self.dmg[c]
        b = d + 8
        self.emit("  d%d car=%s base=%08x items=%08x applied=%08x" % (
            c, self.label(e.u32(d)), e.u32(d + 4), e.u32(d + 204),
            e.u32(d + 208)))
        self.emit("  d%d zones=%s total=%u" % (
            c, e.read(b + 8, 32).hex(), e.u16(b + 40)))
        self.emit("  d%d shown=%s total=%u" % (
            c, e.read(b + 42, 32).hex(), e.u16(b + 74)))
        parts = ",".join(str(x) for x in struct.unpack_from(
            "<15b", e.mem, d + 212))
        n = s32(e.u32(b + 76))
        self.emit("  d%d alevel=%s models=%d parts=%s" % (
            c, self.label(e.u32(b + 192)), n, parts))
        for i in range(max(0, min(n, 4))):
            m = b + 80 + 28 * i
            self.emit("  d%d.m%d bd=%s model=%s info=%s nv=%d polys=%d "
                      "rep=%d key=%d" % (
                          c, i, self.label(e.u32(m)),
                          self.label(e.u32(m + 4)),
                          self.label(e.u32(m + 8)), s32(e.u32(m + 12)),
                          s32(e.u32(m + 16)), s32(e.u32(m + 20)),
                          s32(e.u32(m + 24))))

    # ---- the ops

    def call_f(self, fn, *args, f12=None, f13=None):
        e = self.e
        if f12 is not None:
            e.fpr[12] = f12
        if f13 is not None:
            e.fpr[13] = f13
        return e.call(fn, *args)

    def run(self, a):
        e = self.e
        o = a[0]
        c = int(a[1], 0) if len(a) > 1 else 0
        U = lambda i: int(a[i], 0) & M32           # noqa: E731
        I = lambda i: s32(int(a[i], 0))            # noqa: E731
        if o == "reset":
            self.reset()
            self.emit("reset")
        elif o == "enabled":
            e.put32(DAMAGE_ON, I(1))
            self.emit("enabled %d" % I(1))
        elif o == "info":
            nkeys = I(6)
            size = 8 + INFO + 4 * nkeys
            p = e.alloc(size + 16, align=16)
            e.write(p, b"\xcd" * (size + 16))
            e.put32(p, U(2))
            e.put32(p + 4, INFO + 4 * nkeys)
            bi = p + 8
            nm = a[3].encode("latin-1")[:31]
            e.write(bi + 8, nm + bytes(32 - len(nm)))
            e.put32(bi + 40, U(4))
            e.put32(bi + 68, I(5))
            e.put32(bi + 72, nkeys)
            for j, off in enumerate((44, 48, 52, 56, 60, 64)):
                e.put32(bi + off, U(7 + j))
            self.info[c] = p
            self.name("i%d" % c, bi)
            self.lab[bi + INFO] = "i%d.keys" % c
        elif o in ("load", "unload"):
            r = e.call(F_LOAD if o == "load" else F_UNLOAD, self.info[c])
            self.emit("%s i%d -> %d" % (o, c, r))
            bi = self.info[c] + 8
            self.emit("  i%d keys=%s vi=%s" % (c, self.label(e.u32(bi + 76)),
                                              self.label(e.u32(bi + 80))))
            self.dump_infos()
        elif o == "find":
            self.emit("find %08x -> %s" % (U(1),
                                           self.label(e.call(F_FIND, I(1)))))
        elif o == "car":
            car = e.alloc(CAR_SIZE, align=16)
            e.write(car, bytes(CAR_SIZE))
            cti = e.alloc(128, align=16)
            e.write(cti, bytes(128))
            nm = a[3].encode("latin-1")[:31]
            e.write(cti + 32, nm)
            ride = e.alloc(16, align=16)
            e.write(ride, bytes(16))
            e.put32(ride, I(2))
            ri = e.alloc(16, align=16)
            d = e.alloc(240, align=16)
            e.write(d, b"\xcd" * 240)
            e.put32(car + 12, cti)
            e.put32(car + 16, ride)
            e.put32(car + 1200, ri)
            self.car[c], self.dmg[c] = car, d
            self.name("c%d" % c, car)
            self.lab[car + 96] = "c%d.pos" % c
            self.name("ri%d" % c, ri)
            self.name("d%d" % c, d)
            self.lab[d + 8] = "d%d.b" % c
            for i in range(4):
                self.lab[d + 88 + 28 * i] = "d%d.m%d" % (c, i)
            self.emit("car c%d type=%d base=%s" % (c, I(2), a[3]))
            r = e.call(F_CTOR, d, car)
            self.emit("  -> %s" % self.label(r))
            self.dump_damage(c)
            self.dump_bodies()
        elif o == "solid":
            s = e.alloc(192, align=16)
            e.write(s, bytes(192))
            struct.pack_into("<h", e.mem, s + 56, I(2))
            t = e.alloc(64 * NSTRIP, align=16)
            e.write(t, bytes(64 * NSTRIP))
            e.put32(s + 176, t)
            self.solid[c] = s
            self.name("s%d" % c, s)
        elif o == "strip":
            s = self.solid[c]
            n = struct.unpack_from("<h", e.mem, s + 52)[0]
            ent = e.u32(s + 176) + 64 * n
            d = e.alloc(PACKET, align=16)
            e.write(d, packet(I(2), U(4)))
            e.put32(ent + 8, d)
            struct.pack_into("<HH", e.mem, ent + 12, PACKET // 16, U(3) & 0xffff)
            e.mem[ent + 29] = I(2) & 0xff
            struct.pack_into("<h", e.mem, s + 52, n + 1)
        elif o == "verts":
            s = self.solid[c]
            self.emit("verts s%d" % c)
            sc = self.scratch
            for j in range(struct.unpack_from("<h", e.mem, s + 52)[0]):
                ent = e.u32(s + 176) + 64 * j
                d = e.u32(ent + 8)
                self.emit("  s%d.%d flags=%04x sum=%08x" % (
                    c, j, e.u16(ent + 14), fnv(e.read(d, PACKET))))
                for v in range(e.u8(ent + 29)):
                    e.call(F_GETXYZ, d, v, sc, sc + 4, sc + 8)
                    e.call(F_GETRGBA, d, v, sc + 12)
                    self.emit("  s%d.%d.%d %08x %08x %08x %04x" % (
                        c, j, v, e.u32(sc), e.u32(sc + 4), e.u32(sc + 8),
                        e.u16(e.u32(sc + 12))))
        elif o == "key":
            e.put32(self.info[c] + 8 + INFO + 4 * I(2), U(3))
        elif o == "model":
            if c not in self.model:
                m = e.alloc(32, align=16)
                e.write(m, bytes(32))
                self.model[c] = m
                self.name("m%d" % c, m)
            e.put32(self.model[c] + 12, 0 if I(2) < 0 else self.solid[I(2)])
        elif o == "marker":
            m = e.alloc(32, align=16)
            e.write(m, bytes(32))
            e.put32(m + 8, U(1))
            e.put32(m + 12, U(2))
            for j in range(3):
                e.put32(m + 16 + 4 * j, U(3 + j))
            self.name("p%d" % len(self.marks), m)
            self.marks.append((m, U(1), U(2)))
        elif o == "seam":
            self.seam = bool(I(1))
        elif o == "alevel":
            self.emit("alevel d%d %s" % (c, a[2]))
            b = self.dmg[c] + 8
            e.call(F_SETALEVEL, b, self.string(a[2]))
            self.emit("  -> %s" % self.label(e.u32(b + 192)))
        elif o == "add":
            self.emit("add d%d m%d %s %d" % (c, I(2), a[3], I(4)))
            e.call(F_ADDMODEL, self.dmg[c] + 8, self.model[I(2)],
                   self.string(a[3]), I(4))
            self.dump_damage(c)
        elif o == "parts":
            self.emit("parts d%d" % c)
            e.call(F_PARTS, self.dmg[c])
            self.dump_damage(c)
        elif o == "hit":
            self.emit("hit d%d %08x %08x %08x %08x" % (c, U(2), U(3), U(4),
                                                      U(5)))
            at = self.floats(U(2), U(3), U(4), 0)
            self.call_f(F_ADD, self.dmg[c], at, f12=U(5))
            self.dump_damage(c)
        elif o == "zone":
            self.emit("zone d%d %d %08x %08x" % (c, I(2), U(3), U(4)))
            self.call_f(F_ADDZONE, self.dmg[c], I(2), f12=U(3), f13=U(4))
            self.dump_damage(c)
        elif o == "states":
            self.emit("states d%d -> %08x" % (
                c, e.call(F_STATES, self.dmg[c]) & M32))
        elif o in ("rethink", "apply", "wreck", "repair"):
            self.emit("%s d%d" % (o, c))
            e.call({"rethink": F_RETHINK, "apply": F_APPLY,
                    "wreck": F_WRECK, "repair": F_REPAIR}[o], self.dmg[c])
            self.dump_damage(c)
        elif o in ("bapply", "brepair"):
            self.emit("%s d%d" % (o, c))
            e.call(F_BAPPLY if o == "bapply" else F_BREPAIR,
                   self.dmg[c] + 8)
            self.dump_damage(c)
        elif o == "setdmg":
            self.emit("setdmg d%d %d %08x" % (c, I(2), U(3)))
            self.call_f(F_SETDAMAGE, self.dmg[c] + 8, I(2), f12=U(3))
            self.dump_damage(c)
        elif o == "getzone":
            at = self.floats(U(2), U(3))
            self.emit("getzone d%d %08x %08x -> %d" % (
                c, U(2), U(3), e.call(F_ZONE, self.dmg[c] + 8, at)))
        elif o in ("amount", "visat"):
            at = self.floats(U(2), U(3))
            e.call(F_AMOUNT if o == "amount" else F_VISAT, self.dmg[c] + 8,
                   at)
            self.emit("%s d%d %08x %08x -> %08x" % (o, c, U(2), U(3),
                                                    e.fpr[0] & M32))
        elif o == "vis":
            e.call(F_VIS, self.dmg[c] + 8, I(2))
            self.emit("vis d%d %d -> %08x" % (c, I(2), e.fpr[0] & M32))
        elif o == "cvis":
            r = e.call(F_CVIS, self.dmg[c] + 8, I(2))
            self.emit("cvis d%d %d -> %d" % (c, I(2), r & 0xff))
        elif o == "total":
            e.call(F_TOTAL, self.dmg[c] + 8)
            self.emit("total d%d -> %08x" % (c, e.fpr[0] & M32))
        elif o == "benv":
            self.emit("benv d%d %08x %d" % (c, U(2), I(3)))
            e.call(F_BENV, self.dmg[c] + 8, I(2), I(3))
        elif o == "destroy":
            self.emit("destroy d%d %d" % (c, I(2)))
            e.call(F_DTOR, self.dmg[c], I(2))
            self.dump_bodies()
        elif o == "dump":
            self.emit("dump d%d" % c)
            self.dump_damage(c)
        elif o == "lists":
            self.emit("lists")
            self.dump_infos()
            self.dump_bodies()
        else:
            raise ValueError(o)


def lcg(state):
    return (state * 1103515245 + 12345) & M32


def colour_at(n, i):
    """Where vertex i's colour is in a packet of n vertices."""
    p = 28 + n * 12 + 4
    if n % 4 and n >= 4:
        p += 4
    p += n * 8 + 4
    if n % 2 and n >= 2:
        p += 4
    return p + 4 + 2 * i


def packet(n, seed):
    """A strip's packet of n vertices, as the harness makes it."""
    d = bytearray(PACKET)
    st = seed & M32
    for i in range(PACKET // 4):
        st = lcg(st)
        struct.pack_into("<f", d, 4 * i, (((st >> 16) % 2001) - 1000) / 64.0)
    d[4] = n & 0xff
    for i in range(n):
        st = lcg(st)
        struct.pack_into("<H", d, colour_at(n, i), (st >> 16) & 0xffff)
    return bytes(d)


def fnv(data):
    h = 2166136261
    for x in data:
        h = ((h ^ x) * 16777619) & M32
    return h


def model(lines):
    m = Model()
    for ln in lines:
        m.run(ln.split("|"))
    return m.out


# ================================================================ the script

# The items' marker hashes, by index (0x00313b80).
ITEM_HASH = [0x05f63788, 0xc52bf01b, 0x725758bf, 0x494ed280, 0xa7e6ea53,
             0xa532fc46, 0xd947f346, 0x02b52399, 0x7b220ddf, 0x1b0763a0,
             0xe7e4ef49, 0x4cdebfca, 0x60f8b13c, 0x0ab88f5d, 0x68100815]

# The box most infos share: x -1..1, y -2.5..2.5.
BOX = (-1.0, -2.5, 1.0, 2.5)


class Script(object):
    def __init__(self):
        self.lines = []

    def op(self, *a):
        self.lines.append("|".join(str(x) for x in a))

    def info(self, k, name, nverts, nkeys=3, box=BOX, typ=BODY_DAMAGE_ID,
             h=None):
        self.op("info", k, X(typ), name, X(bhash(name) if h is None else h),
                nverts, nkeys, *[H(v) for v in box], H(0.0), H(0.25))

    def car(self, c, typ, base):
        self.op("car", c, typ, base)

    def solid(self, k, nverts):
        self.op("solid", k, nverts)

    def strip(self, k, nverts, flags, seed):
        self.op("strip", k, nverts, X(flags), X(seed))

    def keys(self, k, keys):
        for i, v in enumerate(keys):
            self.op("key", k, i, X(v))

    def hit(self, c, x, y, z, amount):
        self.op("hit", c, H(x), H(y), H(z), H(amount))

    def zone(self, c, z, amount, impact):
        self.op("zone", c, z, H(amount), H(impact))

    def setdmg(self, c, z, amount):
        self.op("setdmg", c, z, H(amount))

    def marker(self, item, base, x, y, z=0.5):
        self.op("marker", X(ITEM_HASH[item]), X(bhash(base)), H(x), H(y),
                H(z))


def list_cases(sc):
    sc.op("reset")
    sc.info(0, "VIPER_A", 120)
    sc.info(1, "VIPER_B", 80)
    sc.info(2, "VIPER_C", 40, nkeys=0)
    sc.info(3, "VIPER_A", 60)                      # the name again
    sc.info(4, "WRONG", 10, typ=BODY_DAMAGE_ID + 1)
    sc.info(5, "HIGH", 10, typ=BODY_DAMAGE_ID | 0x80000000)
    for k in range(6):
        sc.op("load", k)
    for nm in ("VIPER_A", "VIPER_B", "VIPER_C", "WRONG", "HIGH", "NONE"):
        sc.op("find", X(bhash(nm)))
    sc.op("unload", 4)
    sc.op("unload", 1)
    sc.op("find", X(bhash("VIPER_B")))
    sc.op("load", 1)
    sc.op("unload", 0)
    sc.op("find", X(bhash("VIPER_A")))
    sc.op("load", 0)
    sc.op("find", X(bhash("VIPER_A")))
    sc.op("unload", 2)
    sc.op("unload", 3)
    sc.op("unload", 1)
    sc.op("unload", 0)
    sc.op("lists")


def setup(sc):
    """Infos, solids and models the car cases share."""
    sc.op("reset")
    sc.info(0, "VIPER_A", 120)
    sc.info(1, "VIPER_B", 80)
    sc.info(2, "FLAT_A", 30, box=(0.5, -2.0, 0.5, 2.0))
    sc.info(3, "THIN_A", 30, box=(-1.0, 1.0, 1.0, 1.0))
    sc.info(4, "BUS_A", 200, box=(-1.5, -6.0, 1.5, 6.0))
    for k in range(5):
        sc.op("load", k)
    for k, nverts in enumerate((120, 80, 99, 0, 200)):
        sc.solid(k, nverts)
    for m, s in ((0, 0), (1, 1), (2, 2), (3, 3), (4, -1), (5, 4), (6, 0)):
        sc.op("model", m, s)


def model_cases(sc):
    setup(sc)
    sc.car(0, 1, "VIPER")
    sc.car(1, 0x13, "BUS")
    sc.op("alevel", 0, "VIPER_A")
    sc.op("alevel", 1, "NOPE")
    sc.op("add", 0, 0, "VIPER_A", 0)
    sc.op("add", 0, 1, "VIPER_B", 0)
    sc.op("add", 0, 2, "VIPER_A", 1)               # 99 vertices, not 120
    sc.op("add", 0, 4, "VIPER_A", 1)               # no solid
    sc.op("add", 1, 3, "VIPER_A", 1)               # no vertices
    sc.op("add", 1, 6, "NOPE", 0)                  # no info
    sc.op("seam", 0)
    sc.op("add", 1, 0, "VIPER_A", 0)
    sc.op("seam", 1)
    sc.info(5, "ZERO_A", 0)
    sc.op("load", 5)
    sc.op("add", 1, 3, "ZERO_A", 0)               # none, and an info of none
    sc.op("alevel", 1, "BUS_A")
    sc.op("lists")
    # The environment mapping straight, over each body's models.
    for c, h, on in ((0, ITEM_HASH[11], 0), (0, ITEM_HASH[11], 1),
                     (1, ITEM_HASH[8], 0), (1, 0x33333333, 7)):
        sc.op("benv", c, X(h), on)
    # ApplyDamage over models with no info.
    for c in (0, 1):
        sc.setdmg(c, 3, 1.0)
        sc.op("bapply", c)


def zone_cases(sc):
    setup(sc)
    sc.car(0, 1, "VIPER")
    sc.car(1, 1, "VIPER")
    sc.car(2, 1, "FLAT")
    sc.car(3, 1, "THIN")
    sc.op("alevel", 0, "VIPER_A")
    sc.op("alevel", 2, "FLAT_A")
    sc.op("alevel", 3, "THIN_A")
    for i in range(13):
        for j in range(13):
            x = -1.5 + 3.0 * i / 12
            y = -3.0 + 6.0 * j / 12
            sc.op("getzone", 0, H(x), H(y))
    # The diagonals and the box's edges and corners, exactly.
    for t in (0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0):
        x = -1.0 + 2.0 * t
        for y in (-2.5 + 5.0 * t, 2.5 - 5.0 * t, -2.5, 2.5):
            sc.op("getzone", 0, H(x), H(y))
        sc.op("getzone", 0, H(-1.0), H(-2.5 + 5.0 * t))
        sc.op("getzone", 0, H(1.0), H(-2.5 + 5.0 * t))
    for x, y in ((0.0, 0.0), (1e30, 0.0), (-1e30, 0.0), (0.0, 1e30),
                 (0.0, -1e30), (1e30, 1e30), (-0.0, -0.0)):
        sc.op("getzone", 0, H(x), H(y))
        sc.op("getzone", 1, H(x), H(y))
        sc.op("getzone", 2, H(x), H(y))
        sc.op("getzone", 3, H(x), H(y))
    for x, y in ((0.4, 0.0), (0.6, 1.0), (0.5, -1.9), (0.7, 2.5),
                 (0.3, -3.0)):
        sc.op("getzone", 2, H(x), H(y))
        sc.op("getzone", 3, H(x), H(y + 0.5))
    for x in (-1.0, 0.0, 0.5, 1.0, 2.0):            # 0 / 0 on the flat box
        sc.op("getzone", 3, H(x), H(1.0))
    # The amounts, on and off.
    # Zones 4, 12, 20 and 28 are the points' below.
    for z, v in ((1, 0.5), (4, 0.375), (8, 1.0), (12, 0.625), (16, 0.25),
                 (20, 0.875), (24, 0.75), (28, 0.5), (31, 0.1)):
        sc.setdmg(0, z, v)
    for on in (1, 0, 1):
        sc.op("enabled", on)
        for x, y in ((1.0, 0.0), (0.0, -2.5), (-1.0, 0.0), (0.0, 2.5),
                     (0.3, 0.3)):
            sc.op("amount", 0, H(x), H(y))
            sc.op("visat", 0, H(x), H(y))
            sc.op("amount", 1, H(x), H(y))
            sc.op("visat", 1, H(x), H(y))
        for z in (0, 1, 8, 16, 24, 31):
            sc.op("vis", 0, z)
            sc.op("cvis", 0, z)
        sc.op("total", 0)
        sc.op("total", 1)


def setdamage_cases(sc):
    setup(sc)
    sc.car(0, 1, "VIPER")
    sc.op("alevel", 0, "VIPER_A")
    sc.op("add", 0, 0, "VIPER_A", 0)
    for v in (0.5, 1.5, -0.5, 0.999, 1.0 / 128, 0.0078, 0.0, 1.0,
              127.5 / 128, 1e30, -1e30, 2.0 / 128):
        sc.setdmg(0, 3, v)
    # ApplyDamage either side of 0.02 (81.92 of 4096) and back at 0.
    for z, n in ((0, 10), (1, 40), (2, 30), (3, 2), (2, 31), (4, 1),
                 (5, 0), (0, 0), (1, 0), (2, 0), (3, 0), (4, 0)):
        sc.setdmg(0, z, n / 128.0)
        sc.op("bapply", 0)
    # Applied left small by an ApplyDamage on the way down, then 0.
    for n in (100, 10, 0):
        sc.setdmg(0, 6, n / 128.0)
        sc.op("bapply", 0)
    sc.setdmg(0, 7, 100 / 128.0)
    sc.op("enabled", 0)
    sc.op("bapply", 0)
    sc.op("total", 0)
    sc.op("enabled", 1)
    sc.op("bapply", 0)
    sc.op("brepair", 0)
    for z in range(0, 32, 3):
        sc.setdmg(0, z, 0.9)
    sc.op("brepair", 0)


def item_markers(sc, base, box, items):
    """Markers for `items`, spread round the box's sides."""
    x0, y0, x1, y1 = box
    sides = [(x1, None), (None, y0), (x0, None), (None, y1)]
    for n, i in enumerate(items):
        t = ((n * 7) % 15 + 0.5) / 15
        side = sides[n % 4]
        x = side[0] if side[0] is not None else x0 + (x1 - x0) * t
        y = side[1] if side[1] is not None else y0 + (y1 - y0) * t
        sc.marker(i, base, x * 0.95, y * 0.95)


def item_cases(sc):
    setup(sc)
    cars = ((0, 1, "VIPER", "VIPER_A", BOX), (1, 0x13, "BUS", "BUS_A",
                                               (-1.5, -6.0, 1.5, 6.0)),
            (2, 0x14, "VIPER", "VIPER_A", BOX), (3, 0x1f, "VIPER", "VIPER_A",
                                                 BOX),
            (4, 0x12, "VIPER", "VIPER_A", BOX))
    item_markers(sc, "VIPER", BOX, range(15))
    item_markers(sc, "BUS", (-1.5, -6.0, 1.5, 6.0), [0, 1, 4, 8, 9, 14])
    # A marker by the right name and another car's type, and one without
    # an item.
    sc.marker(2, "OTHER", 0.0, 2.0)
    sc.op("marker", X(0x12345678), X(bhash("VIPER")), H(0.5), H(0.5),
          H(0.0))
    for c, typ, base, alevel, box in cars:
        sc.car(c, typ, base)
        sc.op("parts", c)                          # no info yet: -1s
        sc.hit(c, 1.0, 0.0, 0.3, 0.5)              # and no zone
        sc.op("alevel", c, alevel)
        sc.op("add", c, 0 if c != 1 else 5, alevel, 0)
        sc.op("add", c, 1, "VIPER_B", 0)
        sc.op("parts", c)
    for c, _, _, _, box in cars:
        sc.op("states", c)
        x0, y0, x1, y1 = box
        # Light, below the break, and harder, round the car.
        for n, amount in enumerate((0.01, 0.05, 0.1, 0.19, 0.2, 0.3, 0.5,
                                    0.8, 1.2, 0.25, 0.6)):
            t = (n * 5 % 11 + 0.5) / 11
            pts = ((x1, y0 + (y1 - y0) * t), (x0 + (x1 - x0) * t, y0),
                   (x0, y1 - (y1 - y0) * t), (x1 - (x1 - x0) * t, y1))
            x, y = pts[n % 4]
            sc.hit(c, x, y, 0.3, amount)
            sc.op("states", c)
    # Straight at the zones: down, a break by a light impact, and at 0.2.
    sc.zone(0, 5, -0.3, 1.0)
    sc.zone(0, 5, -2.0, 1.0)
    sc.zone(0, 5, 0.3, 0.1)
    sc.zone(0, 5, 0.3, 0.2)
    sc.zone(0, 5, 0.3, 0.19999)
    sc.zone(0, 5, 0.0, 1.0)
    sc.zone(0, 31, 1.0, 1.0)
    sc.zone(0, 0, 1.0, 1.0)
    sc.op("enabled", 0)
    sc.hit(0, 1.0, 0.0, 0.0, 1.0)
    # Below 0 on an empty zone, with the levels off: nothing to change.
    sc.setdmg(0, 0, 0.0)
    sc.zone(0, 0, -0.5, 1.0)
    sc.zone(0, 12, 0.6, 1.0)
    sc.op("states", 0)
    sc.op("rethink", 0)
    sc.op("enabled", 1)
    sc.op("rethink", 0)
    sc.op("apply", 0)
    # Each zone up through the items' thresholds, in 128ths: on 0.25, 0.5
    # and 0.75, and either side of the rest.
    for z in range(32):
        sc.op("repair", 0)
        was = 0
        for n in (31, 32, 33, 44, 45, 46, 57, 58, 63, 64, 65, 83, 84, 85, 89,
                  90, 95, 96, 97, 108, 109, 121, 122, 123, 128):
            sc.zone(0, z, (n - was) / 128.0, 1.0)
            was = n
    for c in range(5):
        sc.op("wreck", c)
        sc.op("states", c)
        sc.op("repair", c)
        sc.op("wreck", c)
    sc.op("lists")
    sc.op("destroy", 1, 0)
    sc.op("destroy", 0, 1)
    sc.op("destroy", 3, 3)
    sc.op("destroy", 2, 2)
    sc.op("lists")


def random_cases(sc, rng):
    setup(sc)
    item_markers(sc, "VIPER", BOX, range(15))
    item_markers(sc, "BUS", (-1.5, -6.0, 1.5, 6.0), range(0, 15, 2))
    types = (1, 0x13, 0x14, 0x1f, 7)
    for c in range(5):
        base = "BUS" if c == 1 else "VIPER"
        sc.car(c, types[c], base)
        sc.op("alevel", c, "BUS_A" if c == 1 else "VIPER_A")
        sc.op("add", c, 5 if c == 1 else 0, "BUS_A" if c == 1 else "VIPER_A",
              0)
        sc.op("parts", c)
    for _ in range(700):
        c = rng.randrange(5)
        r = rng.random()
        if r < 0.55:
            x = rng.uniform(-2.0, 2.0)
            y = rng.uniform(-7.0, 7.0)
            amount = rng.choice((rng.uniform(0.0, 0.3), rng.uniform(0.0, 1.5),
                                 0.05, 0.2))
            sc.hit(c, x, y, rng.uniform(-1.0, 1.0), amount)
        elif r < 0.8:
            sc.zone(c, rng.randrange(32), rng.uniform(-0.5, 0.7),
                    rng.choice((rng.uniform(0.0, 0.4), 1.0)))
        elif r < 0.85:
            sc.setdmg(c, rng.randrange(32), rng.uniform(-0.2, 1.2))
        elif r < 0.88:
            sc.op("repair", c)
        elif r < 0.9:
            sc.op("wreck", c)
        elif r < 0.93:
            sc.op("rethink", c)
        elif r < 0.95:
            sc.op("bapply", c)
        elif r < 0.97:
            sc.op("enabled", rng.choice((0, 1, 1)))
        else:
            sc.op("states", c)
            sc.op("total", c)
    for c in range(5):
        sc.op("destroy", c, c & 1)
    sc.op("lists")


def key(rep, zone, step=0, dx=0, dy=0, dz=0):
    """A BodyDamageInfo key: the repeat count, the zone, the colour step
    and the dent, each field as DamageVertexFunction takes it apart."""
    return ((rep & 7) | (zone & 31) << 3 | (step & 63) << 8 | (dx & 63) << 14
            | (dy & 63) << 20 | (dz & 63) << 26)


def cover(keys, n, rng):
    """`keys`, and random ones after them, for n vertices exactly."""
    out, have = [], 0
    for k in keys:
        if have >= n:
            break
        r = min(k & 7, n - have - 1)
        out.append((k & ~7) | r)
        have += r + 1
    while have < n:
        r = min(rng.randrange(8), n - have - 1)
        out.append(key(r, rng.randrange(32), rng.randrange(-32, 32),
                       *(rng.choice((0, 0, rng.randrange(-32, 32)))
                         for _ in range(3))))
        have += r + 1
    return out


def damage(sc, c, zones):
    for z, n in zones:
        sc.setdmg(c, z, n / 128.0)


def vertex_cases(sc, rng):
    sc.op("reset")
    body = ((4, 0), (7, 0), (1, 0), (13, 0), (0, 0), (2, 0x400), (3, 0x800),
            (30, 0x80), (5, 0), (8, 0x800), (6, 0))
    scuffs = ((5, 0x800), (3, 0xc00), (0, 0x800), (6, 0x800), (4, 0),
              (1, 0x400))
    nb = sum(n for n, _ in body)
    ns = sum(n for n, _ in scuffs)
    kb = cover([key(0, 0), key(1, 1, step=5), key(2, 2, step=-7),
                key(0, 3, dx=31, dy=-32, dz=1), key(3, 4, step=31, dx=-1),
                key(1, 5, step=-32, dz=-32), key(0, 6, dy=1),
                key(7, 7, step=1, dx=5, dy=5, dz=5), key(4, 31, step=-1),
                key(2, 16, step=2, dx=-32, dy=31, dz=-1), key(5, 8, step=-3),
                key(0, 24, step=31, dx=31, dy=31, dz=31),
                key(6, 9, step=-32, dx=-32, dy=-32, dz=-32)], nb, rng)
    ks = cover([key(1, 1), key(0, 2, step=4, dx=3), key(2, 3),
                key(3, 4, step=-6), key(0, 5)], ns, rng)
    sc.info(0, "BODY_A", nb, nkeys=len(kb))
    sc.info(1, "SCUFF_A", ns, nkeys=len(ks))
    sc.keys(0, kb)
    sc.keys(1, ks)
    sc.op("load", 0)
    sc.op("load", 1)
    sc.solid(0, nb)
    for j, (n, f) in enumerate(body):
        sc.strip(0, n, f, 0x5eed0000 + j)
    sc.solid(1, ns)
    for j, (n, f) in enumerate(scuffs):
        sc.strip(1, n, f, 0x5cff0000 + j)
    sc.op("model", 0, 0)
    sc.op("model", 1, 1)
    sc.op("verts", 0)
    sc.op("verts", 1)
    sc.car(0, 1, "VIPER")
    sc.op("add", 0, 0, "BODY_A", 0)
    sc.op("add", 0, 1, "SCUFF_A", 1)
    sc.op("verts", 0)
    sc.op("verts", 1)
    # Each step's zones: the alpha either side of half, full, and a
    # change below the walk's 0.02 that ApplyDamage lets pass.
    steps = (
        ((1, 64), (2, 65), (3, 128), (4, 1), (5, 100), (6, 127), (7, 50),
         (8, 33), (9, 90), (16, 70), (24, 128), (31, 20), (0, 128)),
        ((1, 65), (2, 64), (3, 0), (4, 128), (5, 3), (7, 0), (16, 0),
         (24, 64), (31, 128), (0, 0)),
        ((1, 66),),
        ((1, 128), (2, 128), (3, 128), (4, 128), (5, 128), (6, 128),
         (7, 128), (8, 128), (9, 128)),
    )
    for zones in steps:
        damage(sc, 0, zones)
        sc.op("bapply", 0)
        sc.op("verts", 0)
        sc.op("verts", 1)
    sc.op("enabled", 0)
    sc.op("bapply", 0)
    sc.op("verts", 0)
    sc.op("verts", 1)
    sc.op("enabled", 1)
    sc.op("bapply", 0)
    sc.op("verts", 0)
    sc.op("seam", 0)
    sc.op("brepair", 0)
    sc.op("seam", 1)
    sc.op("verts", 0)
    sc.op("verts", 1)
    sc.op("wreck", 0)
    sc.op("verts", 0)
    sc.op("verts", 1)
    sc.op("repair", 0)
    sc.op("verts", 0)
    sc.op("verts", 1)


def random_vertex_cases(sc, rng):
    sc.op("reset")
    for c in range(3):
        strips = [(rng.choice((0, 1, 2, 3, 4, 5, 8, 11, 16, 29, 30)),
                   rng.choice((0, 0, 0x800, 0xc00, 0x80, 0x400)))
                  for _ in range(rng.randrange(1, NSTRIP + 1))]
        n = sum(v for v, _ in strips)
        ks = cover([], n, rng)
        sc.info(c, "RAND%d_A" % c, n, nkeys=len(ks), box=(-1.0, -2.5, 1.0, 2.5))
        sc.keys(c, ks)
        sc.op("load", c)
        sc.solid(c, n)
        for j, (v, f) in enumerate(strips):
            sc.strip(c, v, f, rng.randrange(1 << 32))
        sc.op("model", c, c)
        sc.car(c, 1, "VIPER")
        sc.op("alevel", c, "RAND%d_A" % c)
        sc.op("add", c, c, "RAND%d_A" % c, rng.choice((0, 0, 1)))
        sc.op("verts", c)
    for _ in range(90):
        c = rng.randrange(3)
        r = rng.random()
        if r < 0.6:
            damage(sc, c, [(rng.randrange(32), rng.randrange(129))
                           for _ in range(rng.randrange(1, 12))])
            sc.op("bapply", c)
        elif r < 0.75:
            sc.hit(c, rng.uniform(-1.5, 1.5), rng.uniform(-3.0, 3.0), 0.0,
                   rng.uniform(0.0, 1.5))
        elif r < 0.82:
            sc.op("repair", c)
        elif r < 0.86:
            sc.op("wreck", c)
        elif r < 0.92:
            sc.op("enabled", rng.choice((0, 1, 1)))
            sc.op("bapply", c)
        else:
            sc.op("brepair", c)
        sc.op("verts", c)


def script():
    sc = Script()
    list_cases(sc)
    model_cases(sc)
    zone_cases(sc)
    setdamage_cases(sc)
    item_cases(sc)
    random_cases(sc, random.Random(0x1b4760))
    vertex_cases(sc, random.Random(0x104100))
    random_vertex_cases(sc, random.Random(0x1b48d0))
    return sc.lines


# ================================================================= running

def build_harness(tmp, name="cardamage_test"):
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

P = CDC


def M(name, before, after, rel=P):
    return (name, rel, before, after)


MUTATIONS = [
    # -- the constants and tables
    M("cd-zone-scale", "ZONE_SCALE      0.0078125f",
      "ZONE_SCALE      0.0079f"),
    M("cd-total-scale", "TOTAL_SCALE     0.000244140625f",
      "TOTAL_SCALE     0.000245f"),
    M("cd-tolerance", "APPLY_TOLERANCE 0.02f", "APPLY_TOLERANCE 0.03f"),
    M("cd-min-hit", "MIN_HIT         0.05f", "MIN_HIT         0.06f"),
    M("cd-min-break", "MIN_BREAK       0.2f", "MIN_BREAK       0.21f"),
    M("cd-wreck-impact", "WRECK_IMPACT    9999.0f",
      "WRECK_IMPACT    0.1f"),
    M("cd-thresh-1", "{  0, 0x05f63788u, { 0.0f, 0.25f,",
      "{  0, 0x05f63788u, { 0.0f, 0.26f,"),
    M("cd-thresh-2", "{  1, 0xc52bf01bu, { 0.0f, 0.25f, 0.5f,",
      "{  1, 0xc52bf01bu, { 0.0f, 0.25f, 0.51f,"),
    M("cd-thresh-3", "{  2, 0x725758bfu, { 0.0f, 0.25f, 0.5f,  0.75f }",
      "{  2, 0x725758bfu, { 0.0f, 0.25f, 0.5f,  0.76f }"),
    M("cd-thresh-0", "{  3, 0x494ed280u, { 0.0f,",
      "{  3, 0x494ed280u, { 0.01f,"),
    M("cd-thresh-35", "{  4, 0xa7e6ea53u, { 0.0f, 0.25f, 0.35f,",
      "{  4, 0xa7e6ea53u, { 0.0f, 0.25f, 0.36f,"),
    M("cd-thresh-65", "{  7, 0x02b52399u, { 0.0f, 0.25f, 0.45f, 0.65f }",
      "{  7, 0x02b52399u, { 0.0f, 0.25f, 0.45f, 0.66f }"),
    M("cd-thresh-14", "0.0f, 0.7f,  0.85f, 0.95f }",
      "0.0f, 0.7f,  0.85f, 0.96f }"),
    M("cd-envmapped-8", "0x7b220ddfu, { 0.0f, 0.25f, 0.5f,  0.75f }, 1,",
      "0x7b220ddfu, { 0.0f, 0.25f, 0.5f,  0.75f }, 0,"),
    M("cd-envmapped-0", "0x05f63788u, { 0.0f, 0.25f, 0.5f,  0.75f }, 0,",
      "0x05f63788u, { 0.0f, 0.25f, 0.5f,  0.75f }, 1,"),
    M("cd-effect-13", "0.75f }, 1, 25 }", "0.75f }, 1, 24 }"),
    M("cd-effect-14", "0.95f }, 0,  6 }", "0.95f }, 0,  7 }"),
    M("cd-hash-5", "0xa532fc46u", "0xa532fc47u"),
    M("cd-nowin-type", "{ 0x14, 0x03ff0000u }", "{ 0x15, 0x03ff0000u }"),
    M("cd-nowin-mask", "{ 0x1f, 0x03ff0000u }", "{ 0x1f, 0x00ff0000u }"),
    M("cd-effect-scale", "{ 0.0f, 0.1f, 0.4f, 1.0f }",
      "{ 0.0f, 0.1f, 0.5f, 1.0f }"),
    M("cd-effect-scale-0", "{ 0.0f, 0.1f, 0.4f, 1.0f }",
      "{ 0.1f, 0.1f, 0.4f, 1.0f }"),
    M("cd-item-level", "(word >> (2 * item)) & 3u", "(word >> (2 * item)) & 1u"),
    # -- the infos
    M("cd-load-id", "        return 0;\n    info = (BodyDamageInfo *)(void *)"
      "(chunk + 8);\n    last",
      "        ;\n    info = (BodyDamageInfo *)(void *)(chunk + 8);\n    last"),
    M("cd-unload-id", "        return 0;\n    info = (BodyDamageInfo *)(void *)"
      "(chunk + 8);\n    info->Node.prev",
      "        ;\n    info = (BodyDamageInfo *)(void *)(chunk + 8);\n"
      "    info->Node.prev"),
    M("cd-load-tail", "    BodyDamageInfoList.prev = &info->Node;\n", ""),
    M("cd-load-keys", "(uint32_t *)(void *)(info + 1);",
      "(uint32_t *)(void *)info;"),
    M("cd-load-vi", "    info->pVertexIndices = NULL;\n", ""),
    M("cd-unload-next", "    info->Node.next->prev = info->Node.prev;\n", ""),
    M("cd-find-ne", "if (info->NameHash == name_hash)",
      "if (info->NameHash != name_hash)"),
    # -- the models
    M("cd-model-nv0", "    if (m->NumVertices == 0)\n        return;\n", ""),
    M("cd-model-nv-mismatch", "if (m->NumVertices != info->NumVertices) {",
      "if (0) {"),
    M("cd-model-mismatch-keep",
      "    if (m->NumVertices != info->NumVertices) {\n"
      "        m->pBodyDamageInfo = NULL;\n",
      "    if (m->NumVertices != info->NumVertices) {\n"),
    M("cd-model-polys", "m->DamagePolysOnly = polys_only;",
      "m->DamagePolysOnly = 0;"),
    M("cd-model-null-info", "    m->pBodyDamageInfo = NULL;\n    m->pBodyDamage",
      "    m->pBodyDamage"),
    M("cd-call-repeat", "    m->RepeatCount = 0;\n    m->KeyNum = 0;",
      "    m->RepeatCount = 2;\n    m->KeyNum = 0;"),
    M("cd-call-key", "m->KeyNum = 0;", "m->KeyNum = 1;"),
    M("cd-call-null", "    if (m->pBodyDamageInfo == NULL)\n        return;\n"
      "    m->RepeatCount", "    m->RepeatCount"),
    # -- DamageVertexFunction
    M("cd-dent-scale", "DENT_SCALE      0.02f", "DENT_SCALE      0.021f"),
    M("cd-vf-repeat", "if ((int32_t)(key & 7u) == m->RepeatCount) {",
      "if ((int32_t)(key & 3u) == m->RepeatCount) {"),
    M("cd-vf-keynum", "m->KeyNum++;", "m->KeyNum += 2;"),
    M("cd-vf-repcount", "m->RepeatCount++;", "m->RepeatCount += 2;"),
    M("cd-vf-zone", "zone = (int32_t)((key & 0xffu) >> 3);",
      "zone = (int32_t)((key & 0x7fu) >> 3);"),
    M("cd-vf-applied", "applied = (float)b->CompressedAppliedDamageAmounts[zone]",
      "applied = (float)b->CompressedDamageAmounts[zone]"),
    M("cd-vf-visible", "visible = bodydamage_get_visible_damage_amount(b, zone);",
      "visible = (float)b->CompressedDamageAmounts[zone] * ZONE_SCALE;"),
    M("cd-vf-polys-only", "if (delta != 0.0f && m->DamagePolysOnly == 0) {",
      "if (delta != 0.0f && m->DamagePolysOnly != 0) {"),
    M("cd-vf-dent-mask", "if ((key & 0xffffc000u) != 0) {",
      "if ((key & 0xfff00000u) != 0) {"),
    M("cd-vf-dent-x", "(int32_t)(key << 12) >> 26", "(int32_t)(key << 13) >> 26"),
    M("cd-vf-dent-y", "(int32_t)(key << 6) >> 26", "(int32_t)(key << 7) >> 26"),
    M("cd-vf-dent-z", "(float)((int32_t)key >> 26)",
      "(float)((int32_t)(key >> 26))"),
    M("cd-vf-dent-delta", "* DENT_SCALE * delta;\n            pos->y",
      "* DENT_SCALE * visible;\n            pos->y"),
    M("cd-vf-step", "step = ((int32_t)(key << 18) >> 26) * 8;",
      "step = ((int32_t)(key << 18) >> 26) * 4;"),
    M("cd-vf-step-shift", "(ee_trunc_w((float)step * visible) >> 3)",
      "(ee_trunc_w((float)step * visible) / 8)"),
    M("cd-vf-step-applied", "- (ee_trunc_w((float)step * applied) >> 3);",
      "- (ee_trunc_w((float)step * visible) >> 3);"),
    M("cd-vf-colour-step", "(uint32_t)d * 0x421u", "(uint32_t)d * 0x420u"),
    M("cd-vf-colour-add", "*colour = (uint16_t)(*colour - (uint32_t)d",
      "*colour = (uint16_t)(*colour + (uint32_t)d"),
    M("cd-vf-polys", "    if (polys != 0) {\n        int32_t a",
      "    if (polys == 0) {\n        int32_t a"),
    M("cd-vf-alpha-scale", "a = ee_trunc_w(visible * 256.0f);",
      "a = ee_trunc_w(visible * 254.0f);"),
    M("cd-vf-alpha-half", "if (a < 129)", "if (a < 128)"),
    M("cd-vf-alpha-off", "*colour = (uint16_t)(*colour & 0x7fffu);",
      "*colour = (uint16_t)(*colour & 0x3fffu);"),
    M("cd-vf-alpha-on", "*colour = (uint16_t)(*colour | 0x8000u);",
      "*colour = (uint16_t)(*colour | 0xc000u);"),
    M("cd-vf-shows", "return visible != 0.0f;", "return delta != 0.0f;"),
    M("cd-call-walk", "    ecall_damage_vertex_function_for_every_vertex(m->pModel, m,\n"
      "                                                  damage_vertex_function);\n",
      ""),
    # -- the walk and eStripData (estripdata.c)
    M("esd-num-verts", "return d[4];", "return d[5];", rel=ESD),
    M("esd-full", "int32_t full = n >> 2;", "int32_t full = n >> 3;", rel=ESD),
    M("esd-in-group", "if (i < full << 2) {", "if (i <= full << 2) {", rel=ESD),
    M("esd-group-size", "        p += (size_t)((i >> 2) * 48 + 4);\n        off[0]",
      "        p += (size_t)((i >> 2) * 44 + 4);\n        off[0]", rel=ESD),
    M("esd-group-word", "        p += (size_t)((i >> 2) * 48 + 4);\n        off[0]",
      "        p += (size_t)((i >> 2) * 48);\n        off[0]", rel=ESD),
    M("esd-group-y", "off[1] = p + (size_t)(lane * 4 + 16);",
      "off[1] = p + (size_t)(lane * 4 + 12);", rel=ESD),
    M("esd-group-z", "off[2] = p + (size_t)(lane * 4 + 32);",
      "off[2] = p + (size_t)(lane * 4 + 36);", rel=ESD),
    M("esd-tail-full", "    if (full != 0)\n        p +=", "    if (1)\n        p +=",
      rel=ESD),
    M("esd-tail-word", "    p += 4;\n    off[0]", "    off[0]", rel=ESD),
    M("esd-tail-y", "off[1] = p + (size_t)((rem + lane) * 4);",
      "off[1] = p + (size_t)((rem + lane + 1) * 4);", rel=ESD),
    M("esd-tail-z", "off[2] = p + (size_t)((rem * 2 + lane) * 4);",
      "off[2] = p + (size_t)((rem * 3 + lane) * 4);", rel=ESD),
    M("esd-rgba-xyz", "p += (size_t)(n * 12 + 4);", "p += (size_t)(n * 12 + 8);",
      rel=ESD),
    M("esd-rgba-xyz-word", "if ((n >> 2) << 2 < n && (n >> 2) != 0)",
      "if ((n >> 2) << 2 < n)", rel=ESD),
    M("esd-rgba-st", "p += (size_t)(n * 8 + 4);", "p += (size_t)(n * 8 + 8);",
      rel=ESD),
    M("esd-rgba-st-word", "if ((n >> 1) << 1 < n && (n >> 1) != 0)",
      "if ((n >> 1) << 1 < n)", rel=ESD),
    M("esd-rgba-end", "return p + 4 + (size_t)(i * 2);",
      "return p + (size_t)(i * 2);", rel=ESD),
    M("esd-set-z", "    memcpy(d + off[2], &z, 4);\n", "", rel=ESD),
    M("esd-strips", "for (i = 0; i < n; i++) {", "for (i = 0; i < n - 1; i++) {",
      rel=ESD),
    M("esd-verts", "for (v = 0; v < nv; v++) {", "for (v = 1; v < nv; v++) {",
      rel=ESD),
    M("esd-polys", "int32_t      polys = e->Flags & ESTRIP_SCUFFS;",
      "int32_t      polys = e->Flags & 0x0c00u;", rel=ESD),
    M("esd-any", "any |= fn(", "any = fn(", rel=ESD),
    M("esd-set-back", "            estripdata_set_xyz(d, v, pos.x, pos.y, pos.z);\n",
      "", rel=ESD),
    M("esd-flags", "        if (polys != 0) {\n            if (any != 0)",
      "        if (1) {\n            if (any != 0)", rel=ESD),
    M("esd-show", "if (any != 0)\n                e->Flags", "if (any == 0)\n"
      "                e->Flags", rel=ESD),
    M("esd-seam", "if (gESolidVerticesChangedFn != NULL)",
      "if (gESolidVerticesChangedFn != NULL && n > 0)", rel=ESD),
    # -- the body damage
    M("cd-bd-tail", "    BodyDamageList.prev = &b->Node;\n", ""),
    M("cd-bd-total", "    b->CompressedTotalDamage = 0;\n"
      "    b->CompressedTotalAppliedDamage = 0;\n",
      "    b->CompressedTotalAppliedDamage = 0;\n"),
    M("cd-bd-applied-total", "    b->CompressedTotalAppliedDamage = 0;\n", ""),
    M("cd-bd-applied", "memset(b->CompressedAppliedDamageAmounts, 0,",
      "memset(b->CompressedAppliedDamageAmounts, 1,"),
    M("cd-bd-nmodels", "b->NumBodyDamageModels = 0;",
      "b->NumBodyDamageModels = 1;"),
    M("cd-bd-alevel", "    b->pALevelBodyDamageInfo = NULL;\n}", "}"),
    M("cd-destruct-repair", "    bodydamage_repair_all(b);\n"
      "    b->Node.prev->next", "    b->Node.prev->next"),
    M("cd-destruct-unlink", "    b->Node.next->prev = b->Node.prev;\n", ""),
    M("cd-add-model-slot", "model_init(&b->BodyDamageModels[n],",
      "model_init(&b->BodyDamageModels[0],"),
    M("cd-set-hi", "if (1.0f < amount)\n        amount = 1.0f;",
      "if (1.5f < amount)\n        amount = 1.5f;"),
    M("cd-set-lo", "    if (amount < 0.0f)\n        amount = 0.0f;\n", ""),
    M("cd-set-scale", "v = ee_trunc_w(amount * 128.0f);",
      "v = ee_trunc_w(amount * 127.0f);"),
    M("cd-set-round", "v = ee_trunc_w(amount * 128.0f);",
      "v = ee_trunc_w(amount * 128.0f + 0.5f);"),
    M("cd-set-total", "(b->CompressedTotalDamage + v - *p);",
      "(b->CompressedTotalDamage + v);"),
    M("cd-repair-apply", "    b->CompressedTotalDamage = 0;\n"
      "    bodydamage_apply_damage(b);\n", "    b->CompressedTotalDamage = 0;\n"),
    M("cd-repair-zones", "for (i = 0; i < BODYDAMAGE_ZONES; i++)\n"
      "        bodydamage_set_damage(b, i, 0.0f);",
      "for (i = 1; i < BODYDAMAGE_ZONES; i++)\n"
      "        bodydamage_set_damage(b, i, 0.0f);"),
    # -- the zone of a point
    M("cd-zone-null", "    if (info == NULL)\n        return -1;",
      "    if (info == NULL)\n        return 0;"),
    M("cd-zone-u-width", "info->BBoxMax.x - info->BBoxMin.x)",
      "info->BBoxMax.x)"),
    M("cd-zone-v-off", "v = ee_div(at[1] - info->BBoxMin.y,",
      "v = ee_div(at[1] + info->BBoxMin.y,"),
    M("cd-zone-v-div", "v = ee_div(at[1] - info->BBoxMin.y, "
      "info->BBoxMax.y - info->BBoxMin.y);",
      "v = (at[1] - info->BBoxMin.y) / (info->BBoxMax.y - info->BBoxMin.y);"),
    M("cd-zone-u8", "iu = ee_trunc_w(u * 8.0f);", "iu = ee_trunc_w(u * 7.0f);"),
    M("cd-zone-v8", "iv = ee_trunc_w(v * 8.0f);", "iv = ee_trunc_w(v * 9.0f);"),
    M("cd-zone-iu0", "    if (iu < 0)\n        iu = 0;\n", ""),
    M("cd-zone-iv0", "    if (iv < 0)\n        iv = 0;\n", ""),
    M("cd-zone-iv7", "if (7 < iv)\n        iv = 7;", "if (8 < iv)\n        iv = 8;"),
    M("cd-zone-iu7", "if (7 < iu)\n        iu = 7;", "if (6 < iu)\n        iu = 6;"),
    M("cd-zone-diag", "if (!(v < u)) {", "if (!(v <= u)) {"),
    M("cd-zone-anti-far", "        if (!(1.0f - v < u))\n            return iv + 16;",
      "        if (!(1.0f - v <= u))\n            return iv + 16;"),
    M("cd-zone-anti-near", "    if (!(1.0f - v < u))\n        return 16 - iu;",
      "    if (!(1.0f - v <= u))\n        return 16 - iu;"),
    M("cd-zone-16", "return iv + 16;", "return iv + 17;"),
    M("cd-zone-24", "return iu + 24;", "return iu + 23;"),
    M("cd-zone-16-iu", "return 16 - iu;", "return 15 - iu;"),
    M("cd-zone-8-iv", "return 8 - iv;", "return 7 - iv;"),
    # -- the getters
    M("cd-amount-applied", "    return (float)b->CompressedDamageAmounts[zone]"
      " * ZONE_SCALE;\n}\n\nfloat bodydamage_get_visible_damage_amount_at",
      "    return (float)b->CompressedAppliedDamageAmounts[zone]"
      " * ZONE_SCALE;\n}\n\nfloat bodydamage_get_visible_damage_amount_at"),
    M("cd-visat-off", "        return 0.0f;\n"
      "    return bodydamage_get_damage_amount(b, at);",
      "        ;\n    return bodydamage_get_damage_amount(b, at);"),
    M("cd-vis-off", "        return 0.0f;\n"
      "    return (float)b->CompressedDamageAmounts[zone] * ZONE_SCALE;\n}\n\n"
      "uint8_t",
      "        ;\n"
      "    return (float)b->CompressedDamageAmounts[zone] * ZONE_SCALE;\n}\n\n"
      "uint8_t"),
    M("cd-cvis-off", "        return 0;\n"
      "    return b->CompressedDamageAmounts[zone];",
      "        ;\n    return b->CompressedDamageAmounts[zone];"),
    M("cd-total-off", "        return 0.0f;\n    // `lhu`",
      "        ;\n    // `lhu`"),
    # -- ApplyDamage
    M("cd-apply-equal", "    if (visible == applied)\n        return;\n", ""),
    M("cd-apply-zero", "\n        && bodydamage_get_visible_total_damage(b) "
      "!= 0.0f)", ")"),
    M("cd-apply-fabs", "fabsf(bodydamage_get_visible_total_damage(b)\n"
      "                                  - applied)",
      "(bodydamage_get_visible_total_damage(b)\n"
      "                                  - applied)"),
    M("cd-apply-walk", "model_call_vertex_function(&b->BodyDamageModels[i]);",
      "model_call_vertex_function(&b->BodyDamageModels[0]);"),
    M("cd-apply-total", "total = (uint16_t)(total + v);",
      "total = (uint16_t)v;"),
    M("cd-apply-visible", "uint8_t v = bodydamage_get_compressed_visible_"
      "damage_amount(b, i);", "uint8_t v = b->CompressedDamageAmounts[i];"),
    M("cd-benv-model", "emodel_set_environment_mapping(b->BodyDamageModels[i]"
      ".pModel, hash,", "emodel_set_environment_mapping(b->BodyDamageModels[0]"
      ".pModel, hash,"),
    # -- CarDamage's constructor, destructor and parts
    M("cd-ctor-items", "    d->BreakableCarItemDamageAmounts = 0;\n"
      "    d->AppliedBreakableCarItemDamageAmounts = 0;\n",
      "    d->AppliedBreakableCarItemDamageAmounts = 0;\n"),
    M("cd-ctor-applied", "    d->AppliedBreakableCarItemDamageAmounts = 0;\n"
      "    d->pCar = c;\n", "    d->pCar = c;\n"),
    M("cd-ctor-hash", "d->CarBaseNameHash = bchunk_hash(c->pCarTypeInfo->"
      "BaseModelName);", "d->CarBaseNameHash = 0;"),
    M("cd-ctor-zones", "for (i = CARDAMAGE_ITEMS - 1; i >= 0; i--)",
      "for (i = CARDAMAGE_ITEMS - 1; i > 0; i--)"),
    M("cd-destroy-items", "    d->BreakableCarItemDamageAmounts = 0;\n"
      "    cardamage_apply_damage(d);\n    bodydamage_destruct",
      "    cardamage_apply_damage(d);\n    bodydamage_destruct"),
    M("cd-destroy-apply", "    cardamage_apply_damage(d);\n"
      "    bodydamage_destruct", "    bodydamage_destruct"),
    M("cd-destroy-flag", "if (flags & 1)", "if (flags & 2)"),
    M("cd-parts-reset", "        d->ItemZones[i] = -1;\n        m = ", "        m = "),
    M("cd-parts-hash", "eFindPositionMarker(BreakableCarItemInfos[i]."
      "PositionHash,", "eFindPositionMarker(BreakableCarItemInfos[0]."
      "PositionHash,"),
    # -- AddDamage
    M("cd-add-off", "if (RaceParametersDamageEnabled == 0 || amount < MIN_HIT)",
      "if (amount < MIN_HIT)"),
    M("cd-add-min", "amount < MIN_HIT)", "amount <= MIN_HIT)"),
    M("cd-add-no-zone", "    if (zone < 0)\n        return;\n"
      "    cardamage_add_zone", "    cardamage_add_zone"),
    M("cd-add-first-impact", "cardamage_add_zone(d, zone, amount, amount);",
      "cardamage_add_zone(d, zone, amount, 1.0f);"),
    M("cd-add-half", "part = amount * 0.5f;", "part = amount * 0.25f;"),
    M("cd-add-ring", "for (i = 1; i < 5; i++) {", "for (i = 1; i < 4; i++) {"),
    M("cd-add-up-wrap", "(zone + i) & 31", "(zone + i) & 15"),
    M("cd-add-down", "(zone - i) & 31", "(zone + i + 16) & 31"),
    M("cd-add-ring-impact", "(zone + i) & 31, part, amount);",
      "(zone + i) & 31, part, part);"),
    M("cd-add-decay", "        part *= 0.5f;\n", "        part *= 0.6f;\n"),
    M("cd-add-apply", "        part *= 0.5f;\n    }\n    cardamage_apply_damage(d);",
      "        part *= 0.5f;\n    }"),
    # -- the item levels
    M("cd-states-skip", "        if (d->ItemZones[i] < 0)\n            continue;\n",
      ""),
    M("cd-states-top", "if (v < t[3])", "if (v <= t[3])"),
    M("cd-states-low", "for (k = 2; k > 0 && v < t[k]; k--)",
      "for (k = 2; k > 1 && v < t[k]; k--)"),
    M("cd-states-le", "for (k = 2; k > 0 && v < t[k]; k--)",
      "for (k = 2; k > 0 && v <= t[k]; k--)"),
    M("cd-states-type", "if (kNoWindows[i].Type == type)",
      "if (kNoWindows[i].Type != type)"),
    M("cd-states-types", "    for (i = 0; i < 3; i++)\n        if (kNoWindows",
      "    for (i = 0; i < 2; i++)\n        if (kNoWindows"),
    # -- the damage to one zone
    M("cd-zone-old-applied", "float old = (float)b->CompressedDamageAmounts[zone]",
      "float old = (float)b->CompressedAppliedDamageAmounts[zone]"),
    M("cd-zone-max0", "    if (now < 0.0f)\n        now = 0.0f;\n", ""),
    M("cd-zone-min1", "    if (1.0f < now)\n        now = 1.0f;\n", ""),
    M("cd-zone-same", "    if (old == now)\n        return;\n", ""),
    M("cd-zone-states-eq", "    if (states == d->BreakableCarItemDamageAmounts)\n"
      "        return;\n", ""),
    M("cd-zone-revert", "        bodydamage_set_damage(b, zone, old);\n", ""),
    M("cd-zone-break", "if (impact < MIN_BREAK) {", "if (impact <= MIN_BREAK) {"),
    M("cd-zone-level-skip", "        if (level == item_level(d->BreakableCarItem"
      "DamageAmounts, i))\n            continue;\n", ""),
    M("cd-zone-glass", "if (level == 1)\n            collision_sound_play_glass",
      "if (level >= 1)\n            collision_sound_play_glass"),
    M("cd-zone-glass-pos", "collision_sound_play_glass(&d->pCar->State.Position);",
      "collision_sound_play_glass(NULL);"),
    M("cd-zone-fx-scale", "kEffectScale[level],", "kEffectScale[3],"),
    M("cd-zone-store", "    d->BreakableCarItemDamageAmounts = states;\n", ""),
    # -- Rethink, ApplyDamage, the wreck and the repair
    M("cd-rethink-store", "    d->BreakableCarItemDamageAmounts = cardamage_"
      "compute_item_states(d);\n", ""),
    M("cd-rethink-apply", "cardamage_compute_item_states(d);\n"
      "    cardamage_apply_damage(d);", "cardamage_compute_item_states(d);"),
    M("cd-capply-body", "    bodydamage_apply_damage(&d->TheBodyDamage);\n"
      "    if (d->Breakable", "    if (d->Breakable"),
    M("cd-capply-eq", "        == d->AppliedBreakableCarItemDamageAmounts)\n"
      "        return;", "        == d->AppliedBreakableCarItemDamageAmounts\n"
      "        && 0)\n        return;"),
    M("cd-capply-skip", "        if (level == item_level(d->AppliedBreakable"
      "CarItemDamageAmounts, i))\n            continue;\n", ""),
    M("cd-capply-env", "if (BreakableCarItemInfos[i].EnvMapped)", "if (1)"),
    M("cd-capply-on", "                level == 0);", "                level != 0);"),
    M("cd-capply-mask", "& ~(3u << (2 * i)))", "& ~(1u << (2 * i)))"),
    M("cd-capply-tex", "    carrenderinfo_update_car_replacement_textures(d->"
      "pCar->pRenderInfo);\n", ""),
    M("cd-wreck-zones", "for (i = 0; i < BODYDAMAGE_ZONES; i++)\n"
      "        cardamage_add_zone(d, i, 1.0f, WRECK_IMPACT);",
      "for (i = 1; i < BODYDAMAGE_ZONES; i++)\n"
      "        cardamage_add_zone(d, i, 1.0f, WRECK_IMPACT);"),
    M("cd-wreck-amount", "cardamage_add_zone(d, i, 1.0f, WRECK_IMPACT);",
      "cardamage_add_zone(d, i, 0.5f, WRECK_IMPACT);"),
    M("cd-wreck-rethink", "WRECK_IMPACT);\n    cardamage_rethink_damage(d);",
      "WRECK_IMPACT);"),
    M("cd-repairall-rethink", "bodydamage_repair_all(&d->TheBodyDamage);\n"
      "    cardamage_rethink_damage(d);",
      "bodydamage_repair_all(&d->TheBodyDamage);"),
]

EQUIVALENT = {
    "cd-thresh-0":
        "An item's first threshold is never read: the level is 0 when the "
        "damage is under the second, which the loop stops at.",
    "cd-states-skip":
        "An item without a zone would read the byte before the zones, the "
        "top byte of the body's list node's back pointer, which is 0 on the "
        "PS2 (RAM is under 32 MB) and on the host's heap, so its level is 0 "
        "either way.",
    "cd-parts-reset":
        "Each item's zone is -1 from the constructor, and a later "
        "FindItemParts finds the same markers, so an item with no marker "
        "is still -1 without the reset; only a marker that went away "
        "between two calls would tell, and the car's markers load with it.",
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
        todo, SOURCES, "cardamage_test",
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
