#!/usr/bin/env python3
"""Cross-check 3DS Files/source/cardamageabove.c (Car::DamageAbove and
Car::DamageCap) against the retail image itself, run in mipsemu.

The model is the image: DamageAbove (0x00135280) and DamageCap
(0x00135490) run as shipped, with bStringHash, ePoly's constructor and
eMulMatrix. Four callees are stubs that print their arguments, and the
harness's stand-ins print the same:

- Player::IsNisPlaying and tCopManager::IsBeingPursued, which answer from
  the scenario;
- GetTextureInfo, which prints the hash it was asked for and answers a
  texture or NULL;
- ePoly::Render3D, which prints the poly as it reads it (each vertex's x,
  y and z, the four colours, each UV's u and v) and the matrix's words.

ePoly's destructor is a stub that prints nothing; the port has no call
for it. A scenario either calls DamageAbove, with a car, an eye and a
direction, or DamageCap alone with its three arguments, which is the only
way to reach the cap's replay size: DamageAbove draws only in a race in
progress. After the call both print the car's fAngleToCamera, the frame
memory's position and the failure count and amount.

Every float is finite. A NaN's bits are the host's on the harness side
and the model's on the other, and an eye at the car divides by zero.

    python tools/cardamageabove_check.py
    python tools/cardamageabove_check.py --mutate [--only a,b]
    python tools/cardamageabove_check.py --dump out/cardamageabove
"""
import argparse
import math
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

HARNESS = "tools/src/cardamageabove_test.c"
CDA = "3DS Files/source/cardamageabove.c"
SOURCES = [HARNESS, CDA] + ["3DS Files/source/" + f for f in (
    "epoly.c", "emath.c", "bmatrix.c", "bmath.c", "bmathtab.c",
    "bvector.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
DAMAGE_ABOVE = 0x00135280
DAMAGE_CAP = 0x00135490
IS_NIS_PLAYING = 0x00176520
IS_BEING_PURSUED = 0x00227438
GET_TEXTURE_INFO = 0x001abf48
RENDER_3D = 0x0010ff88
EPOLY_DTOR = 0x00114db8

G_PLAYERS = GP - 20928            # Player::pPlayersByIndex[2]
G_RC = GP - 22216                 # pRaceCoordinator
G_CM = GP - 15620                 # pCopManager
G_POS = GP - 19388                # CurrentBufferPos
G_END = GP - 19384                # CurrentBufferEnd
G_FAILED = GP - 19372             # FrameMallocFailed
G_AMOUNT = GP - 19368             # FrameMallocFailAmount
BE_A_COP = 0x0031ab0c             # TheRaceParameters.BeACop
OBJECT_POINTS = 0x00333e60
DAMAGE_ABOVE_MATRIX = 0x00333f30

# Retail's Car.
C_INDEX = 8                       # lh
C_CTI = 12
C_DRIVER = 20
C_PLAYER = 24
C_POS = 96
C_BODY = 144
C_ANGLE = 2192
DRV_TYPE = 8
CTI_USAGE = 1336
CM_DAMAGE = 10420
NUM_DAMAGE = 14

CAR = 0x01000000
CTI = 0x01001000
DRIVER = 0x01002000
PLAYERS = (0x01003000, 0x01003400)
EYE = 0x01004000
DIR = 0x01004010
CM = 0x01010000
RC = 0x01020000
TEX = 0x01030000
FRAME = 0x01040000
FRAME_BYTES = 1024
PURSUIT = 0x01050000

PATTERN = 0xa5
STACK_FILL = 0x77


def fb(v):
    if isinstance(v, int):
        return v & M32
    return f_to_bits(v)


def f32(v):
    return struct.unpack("<f", struct.pack("<f", v))[0]


def hexw(ws):
    return " ".join("%08x" % (w & M32) for w in ws)


# ============================================================ the scenarios

RETAIL_POINTS = [(0, 0, 0), (3, 0, 3), (0, -3, 3), (-3, 0, 3), (0, 3, 3),
                 (1, 0, 4), (0, -1, 4), (-1, 0, 4), (0, 1, 4),
                 (3, 0, 9), (0, -3, 9), (-3, 0, 9), (0, 3, 9)]
RETAIL_MATRIX = [0.5, 0, 0, 0, 0, 0.5, 0, 0, 0, 0, 0.5, 0, 0, 0, 1, 1]


def rotation(rnd):
    """A body matrix: a random turn, as rows, the fourth row anything."""
    a, b, c = (rnd.uniform(-math.pi, math.pi) for _ in range(3))
    ca, sa, cb, sb, cc, sc = (math.cos(a), math.sin(a), math.cos(b),
                              math.sin(b), math.cos(c), math.sin(c))
    rows = [(cb * cc, cb * sc, -sb),
            (sa * sb * cc - ca * sc, sa * sb * sc + ca * cc, sa * cb),
            (ca * sb * cc + sa * sc, ca * sb * sc - sa * cc, ca * cb)]
    out = []
    for r in rows:
        out += [fb(r[0]), fb(r[1]), fb(r[2]), fb(rnd.uniform(-1, 1))]
    out += [fb(rnd.uniform(-500, 500)) for _ in range(4)]
    return out


class Sc(object):
    """One call. `kind` is "G" (DamageAbove) or "A" (DamageCap alone,
    with `cap` = (pursued, damage, distance))."""

    def __init__(self, rnd, **kw):
        self.kind = kw.get("kind", "G")
        self.players = kw.get("players", [(1, 0), (0, 0)])
        self.beacop = kw.get("beacop", 1)
        self.rc = kw.get("rc", 1)
        self.state = kw.get("state", 3)
        self.cm = kw.get("cm", 1)
        self.pursued = kw.get("pursued", 0)
        self.tex = kw.get("tex", 1)
        self.nobuf = kw.get("nobuf", 0)
        self.fpos = kw.get("fpos", 0x40)
        self.fend = kw.get("fend", 0x300)
        self.failed = kw.get("failed", 0)
        self.amount = kw.get("amount", 0x10)
        self.index = kw.get("index", rnd.randrange(NUM_DAMAGE))
        self.dtype = kw.get("dtype", 2)
        self.player = kw.get("player", 0)
        self.usage = kw.get("usage", 0)
        pos = kw.get("pos", [rnd.uniform(-2000, 2000) for _ in range(3)])
        self.pos = [fb(v) for v in pos] + [fb(kw.get("posw",
                                                     rnd.uniform(-2, 2)))]
        self.body = kw.get("body", rotation(rnd))
        eye = kw.get("eye")
        if eye is None:
            off = kw.get("off", [rnd.uniform(-150, 150) for _ in range(3)])
            eye = [f32(f32(pos[k]) + off[k]) for k in range(3)]
        self.eye = [fb(v) for v in eye] + [fb(rnd.uniform(-2, 2))]
        d = kw.get("dir")
        if d is None:
            d = [rnd.gauss(0, 1) for _ in range(3)]
            n = math.sqrt(sum(x * x for x in d)) or 1.0
            d = [x / n for x in d]
        self.dir = [fb(v) for v in d] + [fb(rnd.uniform(-2, 2))]
        self.damage = kw.get("damage")
        if self.damage is None:
            self.damage = [fb(rnd.choice((0.0, 0.0, rnd.uniform(0, 1))))
                           for _ in range(NUM_DAMAGE)]
        self.points = kw.get("points")
        if self.points is None:
            self.points = []
            for p in RETAIL_POINTS:
                self.points += [fb(float(p[0])), fb(float(p[1])),
                                fb(float(p[2])), 0]
        self.matrix = kw.get("matrix", [fb(float(v)) for v in RETAIL_MATRIX])
        self.cap = kw.get("cap", (0, 0.0, 0.0))

    def lines(self):
        out = []
        s = ["S"]
        for present, nis in self.players:
            s += ["%x" % present, "%x" % (nis & M32)]
        s += ["%x" % (v & M32) for v in (
            self.beacop, self.rc, self.state, self.cm, self.pursued,
            self.tex, self.nobuf, self.fpos, self.fend, self.failed,
            self.amount)]
        out.append(" ".join(s))
        out.append("C %x %x %x %x %s %s" % (
            self.index & M32, self.dtype & M32, self.player, self.usage & M32,
            hexw(self.pos), hexw(self.body)))
        out.append("E %s %s" % (hexw(self.eye), hexw(self.dir)))
        out.append("D %s" % hexw(self.damage))
        out.append("O %s %s" % (hexw(self.points), hexw(self.matrix)))
        if self.kind == "A":
            p, dmg, dist = self.cap
            out.append("A %x %x %x" % (p & M32, fb(dmg), fb(dist)))
        else:
            out.append("G")
        return out


DAMAGES = [0.0, -0.0, 1e-30, 0.001, 0.25, 0.5, 0.999, 1.0, 1.5, 7.0, -0.25,
           -1.0, 0x00000001, 0x80000001, 100.0]
DISTANCES = [0.0, -0.0, 0.25, 0.5, 1.0, -0.5, 1.5, 0x00000001, 1e-7, 3.0]


def script():
    rnd = random.Random(0xda7a)
    sc = []

    def mk(**kw):
        s = Sc(rnd, **kw)
        sc.append(s)
        return s

    # The gates, one at a time, on a car that passes the rest.
    mk()
    for p0 in ((0, 0), (1, 0), (1, 1), (1, -1), (1, 0x100), (0, 1)):
        for p1 in ((0, 0), (1, 0), (1, 1), (0, 1), (1, 0x80000000)):
            mk(players=[p0, p1])
    for b in (0, 1, -1, 2, 0x100, 0x80000000):
        mk(beacop=b)
    for st in list(range(10)) + [0x103, -3, 0xffffffff]:
        mk(state=st)
    mk(rc=0)
    mk(cm=0)
    mk(cm=0, rc=0)
    for dt in (0, 1, 2, 3, 4, 5, 0x102, -2):
        for pl in (0, 1):
            for usage in (0, 1, 2, -1, 0x101):
                mk(dtype=dt, player=pl, usage=usage)

    # The angle on its own: the eye ahead, behind, to each side, above,
    # and the cross product's z at 0 both ways.
    for off, d in (((10, 0, 0), (1, 0, 0)), ((-10, 0, 0), (1, 0, 0)),
                   ((0, 10, 0), (1, 0, 0)), ((0, -10, 0), (1, 0, 0)),
                   ((0, 0, 10), (1, 0, 0)), ((0, 0, -10), (0, 0, 1)),
                   ((3, 4, 0), (0, 1, 0)), ((-3, -4, 0), (0, 1, 0)),
                   ((5, 0, 5), (-1, 0, 0)), ((0, 5, 0), (0, -1, 0)),
                   ((0, 5, 0), (0, 0, 0)), ((7, 7, 7), (0.6, 0.8, 0)),
                   ((1e-3, 0, 0), (1, 0, 0)), ((1e4, 0, 0), (0, 1, 0))):
        for beacop in (0, 1):
            mk(off=off, dir=d, beacop=beacop)

    # The distance: under, at and over 200, either way along each axis.
    for r in (0.5, 50.0, 100.0, 199.99, 200.0, 200.01, 400.0, 1e4):
        for axis in range(3):
            for sign in (1, -1):
                off = [0.0, 0.0, 0.0]
                off[axis] = sign * r
                mk(off=off)
    mk(off=(115.47, 115.47, 115.47))
    mk(off=(115.4701, 115.4701, 115.4701))

    # The damage and whether a cop is on the car, every car index.
    for idx in range(NUM_DAMAGE):
        for d in (0.0, 0.5):
            for p in (0, 1):
                dmg = [fb(rnd.uniform(0, 1)) for _ in range(NUM_DAMAGE)]
                dmg[idx] = fb(d)
                mk(index=idx, damage=dmg, pursued=p)
    for d in DAMAGES:
        for p in (0, 1, 0x80000000):
            dmg = [fb(rnd.uniform(0, 1)) for _ in range(NUM_DAMAGE)]
            dmg[5] = fb(d)
            mk(index=5, damage=dmg, pursued=p)

    # The texture, and the frame memory: none, too little by one, just
    # enough, a failure already counted.
    for tex in (0, 1):
        for d in (0.0, 0.5):
            dmg = [fb(d)] * NUM_DAMAGE
            mk(tex=tex, damage=dmg)
    for fpos, fend in ((0x40, 0x80), (0x40, 0x81), (0x40, 0x7f),
                       (0x40, 0x40), (0x80, 0x40), (0, 0x41), (0x100, 0x3ff),
                       (0x3c0, 0x400)):
        for failed, amount in ((0, 0), (1, 0x40), (0, 0xffffffc0)):
            mk(fpos=fpos, fend=fend, failed=failed, amount=amount)
    mk(nobuf=1)
    mk(nobuf=1, failed=1, amount=0x80)

    # The points and the matrix at random, the pads too.
    for n in range(20):
        pts = [fb(rnd.uniform(-5, 5)) for _ in range(13 * 4)]
        if n & 1:
            pts[4:8] = [fb(3.0), fb(0.0), fb(3.0), fb(rnd.uniform(-1, 1))]
        mat = [fb(rnd.uniform(-2, 2)) for _ in range(16)]
        dmg = [fb(rnd.choice((0.0, rnd.uniform(0, 1))))
               for _ in range(NUM_DAMAGE)]
        mk(points=pts, matrix=mat, damage=dmg, pursued=n & 2)

    # The cap alone: every state, so the replay's size, and its arguments
    # beyond what DamageAbove hands it.
    for st in list(range(10)) + [0x104, 0x107, -4]:
        for d in (0.0, 0.5):
            mk(kind="A", state=st, cap=(0, d, 0.5))
    for d in DAMAGES:
        for dist in DISTANCES:
            mk(kind="A", cap=(rnd.choice((0, 1, 2, -1)), d, dist))
    for p in (0, 1, 0x100, 0x80000000, -1):
        mk(kind="A", cap=(p, 0.25, 0.75))
    mk(kind="A", nobuf=1, cap=(1, 0.5, 0.5))
    mk(kind="A", tex=0, cap=(1, 0.0, 0.5))

    # And at random.
    for n in range(500):
        kw = {}
        kw["players"] = [(rnd.random() < 0.6, rnd.random() < 0.05),
                         (rnd.random() < 0.2, rnd.random() < 0.05)]
        kw["beacop"] = rnd.random() < 0.9
        kw["state"] = rnd.choice((3, 3, 3, 3, 2, 4, 7))
        kw["cm"] = rnd.random() < 0.95
        kw["pursued"] = rnd.random() < 0.5
        kw["tex"] = rnd.random() < 0.95
        kw["dtype"] = rnd.choice((2, 2, 1, 3, 4))
        kw["player"] = rnd.random() < 0.5
        kw["usage"] = rnd.choice((0, 0, 1, 2))
        kw["off"] = [rnd.uniform(-1, 1) * rnd.choice((5, 50, 300))
                     for _ in range(3)]
        if n % 5 == 0:
            kw["kind"] = "A"
            kw["state"] = rnd.choice((3, 4, 7, 0))
            kw["cap"] = (rnd.choice((0, 1)),
                         rnd.choice((0.0, rnd.uniform(0, 1.2))),
                         rnd.uniform(-0.2, 1.2))
        mk(**kw)
    return sc


# ================================================================ the model


class Model(object):
    def __init__(self):
        self.out = []
        self.e = retail_model.RetailEmu(ieee=True)
        e = self.e
        e.stub(IS_NIS_PLAYING, self.nis)
        e.stub(IS_BEING_PURSUED, self.pursued)
        e.stub(GET_TEXTURE_INFO, self.texture)
        e.stub(RENDER_3D, self.render)
        e.stub(EPOLY_DTOR, lambda em: None)

    def emit(self, s):
        self.out.append(s)

    def arg(self, i):
        return self.e.reg[(4, 5, 6, 7)[i]] & M32

    def ws(self, a, n):
        return [self.e.u32(a + 4 * i) for i in range(n)]

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        names = {CAR: "car", CM: "cm", TEX: "tex", PLAYERS[0]: "p0",
                 PLAYERS[1]: "p1"}
        if a in names:
            return names[a]
        if FRAME <= a < FRAME + FRAME_BYTES:
            return "f+%x" % (a - FRAME)
        return "-"

    # ---- the stubs -------------------------------------------------------

    def nis(self, em):
        p = self.arg(0)
        v = self.sc.players[p == PLAYERS[1]][1]
        self.emit("  nis %s -> %x" % (self.label(p), v & M32))
        return s32(v)

    def pursued(self, em):
        self.emit("  pursued %s %s -> %x" % (
            self.label(self.arg(0)), self.label(self.arg(1)),
            self.sc.pursued & M32))
        return PURSUIT if self.sc.pursued else 0

    def texture(self, em):
        self.emit("  tex %08x %x %x -> %s" % (
            self.arg(0), self.arg(1), self.arg(2),
            "tex" if self.sc.tex else "null"))
        return TEX if self.sc.tex else 0

    def render(self, em):
        p, tex, m, flags = (self.arg(i) for i in range(4))
        verts = []
        for k in range(4):
            verts += self.ws(p + 16 + 16 * k, 3)
        uvs = []
        for k in range(4):
            uvs += self.ws(p + 80 + 12 * k, 2)
        self.emit("  render %s %s %x | %s | %s | %s | %s" % (
            self.label(tex), self.label(m), flags, hexw(verts),
            hexw(self.ws(p + 128, 4)), hexw(uvs), hexw(self.ws(m, 16))))

    # ---- the world -------------------------------------------------------

    def fill(self, a, n):
        self.e.write(a, bytes([PATTERN]) * n)

    def put_words(self, a, ws):
        for i, w in enumerate(ws):
            self.e.put32(a + 4 * i, w)

    def world(self, sc):
        e = self.e
        p = e.put32
        self.fill(CAR, 2304)
        self.fill(CTI, 2048)
        self.fill(DRIVER, 64)
        self.fill(CM, CM_DAMAGE + 4 * NUM_DAMAGE + 64)
        self.fill(RC, 16)
        self.fill(FRAME, FRAME_BYTES)

        for k, (present, nis) in enumerate(sc.players):
            p(G_PLAYERS + 4 * k, PLAYERS[k] if present else 0)
        p(BE_A_COP, sc.beacop)
        p(G_RC, RC if sc.rc else 0)
        p(RC, sc.state)
        p(G_CM, CM if sc.cm else 0)
        if sc.nobuf:
            p(G_POS, 0)
            p(G_END, 0)
        else:
            p(G_POS, FRAME + sc.fpos)
            p(G_END, FRAME + sc.fend)
        p(G_FAILED, sc.failed)
        p(G_AMOUNT, sc.amount)

        e.mem[CAR + C_INDEX] = sc.index & 0xff
        e.mem[CAR + C_INDEX + 1] = (sc.index >> 8) & 0xff
        p(CAR + C_CTI, CTI)
        p(CAR + C_DRIVER, DRIVER)
        p(DRIVER + DRV_TYPE, sc.dtype)
        p(CAR + C_PLAYER, PLAYERS[0] if sc.player else 0)
        p(CTI + CTI_USAGE, sc.usage)
        self.put_words(CAR + C_POS, sc.pos)
        self.put_words(CAR + C_BODY, sc.body)
        self.put_words(EYE, sc.eye)
        self.put_words(DIR, sc.dir)
        self.put_words(CM + CM_DAMAGE, sc.damage)
        self.put_words(OBJECT_POINTS, sc.points)
        self.put_words(DAMAGE_ABOVE_MATRIX, sc.matrix)

    def end(self):
        e = self.e
        pos = e.u32(G_POS)
        self.emit("E %08x %s %x %x" % (
            e.u32(CAR + C_ANGLE),
            "none" if pos == 0 else self.label(pos),
            e.u32(G_FAILED), e.u32(G_AMOUNT)))

    def run(self, scenarios):
        for n, sc in enumerate(scenarios):
            self.sc = sc
            self.world(sc)
            self.emit("R %d" % n)
            sp = self.e.reg[29] & M32
            self.e.write(sp - 16384, bytes([STACK_FILL]) * 16384)
            if sc.kind == "A":
                pursued, dmg, dist = sc.cap
                self.e.fpr[12] = fb(dmg)
                self.e.fpr[13] = fb(dist)
                self.e.call(DAMAGE_CAP, CAR, pursued & M32, limit=2000000)
            else:
                self.e.call(DAMAGE_ABOVE, CAR, EYE, DIR, limit=2000000)
            self.end()
        return self.out


# ================================================================ the build


def build_harness(tmp, name="cardamageabove_test"):
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


def encode(scenarios):
    lines = []
    for s in scenarios:
        lines += s.lines()
    return NL.join(lines) + NL


diff = pcc.diff


# ============================================================ the mutations


def M(name, before, after=None):
    return (name, CDA, before, after)


MUTATIONS = [
    # the constants
    M("k_dist_scale", "#define DISTANCE_SCALE  0.005f",
      "#define DISTANCE_SCALE  0.0051f"),
    M("k_size_near", "#define CAP_SIZE_NEAR   0.05f",
      "#define CAP_SIZE_NEAR   0.06f"),
    M("k_size_replay", "#define CAP_SIZE_REPLAY 0.1f",
      "#define CAP_SIZE_REPLAY 0.11f"),
    M("k_side", "#define COLOUR_SIDE           0xff00aa00u",
      "#define COLOUR_SIDE           0xff00ab00u"),
    M("k_side_p", "#define COLOUR_SIDE_PURSUED   0xffcc0000u",
      "#define COLOUR_SIDE_PURSUED   0xffcc0001u"),
    M("k_dmg", "#define COLOUR_DAMAGE         0xff005599u",
      "#define COLOUR_DAMAGE         0xfe005599u"),
    M("k_dmg_p", "#define COLOUR_DAMAGE_PURSUED 0xff995500u",
      "#define COLOUR_DAMAGE_PURSUED 0xff995501u"),

    # the angle
    M("a_way_flip", "dx = eye->x - pos->x;", "dx = pos->x - eye->x;"),
    M("a_way_y", "dy = eye->y - pos->y;", "dy = eye->y - pos->x;"),
    M("a_way_z", "dz = eye->z - pos->z;", "dz = eye->z;"),
    M("a_len_noz", "len = sqrtf((dx * dx + dy * dy) + dz * dz);",
      "len = sqrtf(dx * dx + dy * dy);"),
    M("a_len_order", "len = sqrtf((dx * dx + dy * dy) + dz * dz);",
      "len = sqrtf(dx * dx + (dy * dy + dz * dz));"),
    M("a_inv_div", "    nx = dx * inv;", "    nx = dx / len;"),
    M("a_ny", "ny = dy * inv;", "ny = dx * inv;"),
    M("a_nz", "nz = dz * inv;", "nz = dz;"),
    M("a_dot_order",
      "dot = (direction->x * nx + direction->y * ny) + direction->z * nz;",
      "dot = direction->x * nx + (direction->y * ny + direction->z * nz);"),
    M("a_dot_noz",
      "dot = (direction->x * nx + direction->y * ny) + direction->z * nz;",
      "dot = (direction->x * nx + direction->y * ny);"),
    M("a_cross_flip", "cz = direction->x * ny - nx * direction->y;",
      "cz = nx * direction->y - direction->x * ny;"),
    M("a_cross_x", "cz = direction->x * ny - nx * direction->y;",
      "cz = direction->y * nz - ny * direction->z;"),
    M("a_plus2", "a = (dot + 1.0f) * 0.5f;", "a = (dot + 2.0f) * 0.5f;"),
    M("a_half", "a = (dot + 1.0f) * 0.5f;", "a = dot + 1.0f;"),
    M("a_lt", "if (0.0f <= cz)", "if (0.0f < cz)"),
    M("a_ge", "if (0.0f <= cz)", "if (cz <= 0.0f)"),
    M("a_noneg", "        a = -a;\n", ""),
    M("a_nostore", "    c->fAngleToCamera = a;\n", ""),
    M("a_store_late", [
        ("    c->fAngleToCamera = a;\n\n    if (PlayerPlayersByIndex[0]",
         "\n    if (PlayerPlayersByIndex[0]"),
        ("    pursued = copmanager_is_being_pursued",
         "    c->fAngleToCamera = a;\n    pursued = copmanager_is_being_pursued")],
      None),

    # the gates
    M("g_p0_null", "    if (PlayerPlayersByIndex[0] != NULL\n        && ",
      "    if (PlayerPlayersByIndex[0] == NULL\n        || "),
    M("g_p0_skip", "        && player_is_nis_playing(PlayerPlayersByIndex[0]))\n"
      "        return;\n", "        && 0)\n        return;\n"),
    M("g_p1_idx", "player_is_nis_playing(PlayerPlayersByIndex[1]))",
      "player_is_nis_playing(PlayerPlayersByIndex[0]))"),
    M("g_p1_skip", "        && player_is_nis_playing(PlayerPlayersByIndex[1]))\n"
      "        return;\n", "        && 0)\n        return;\n"),
    M("g_beacop_inv", "if (!TheRaceParameters.BeACop)",
      "if (TheRaceParameters.BeACop)"),
    M("g_beacop_low", "if (!TheRaceParameters.BeACop)",
      "if (!(TheRaceParameters.BeACop & 0xff))"),
    M("g_state_eq", "               != RCSTATE_RACE_IN_PROGRESS)",
      "               == RCSTATE_RACE_IN_PROGRESS)"),
    M("g_state_2", "               != RCSTATE_RACE_IN_PROGRESS)",
      "               != RCSTATE_PRERACE)"),
    M("g_state_low", "        || racecoordinator_get_current_state(pRaceCoordinator)\n"
      "               != RCSTATE_RACE_IN_PROGRESS)",
      "        || (racecoordinator_get_current_state(pRaceCoordinator) & 0xff)\n"
      "               != RCSTATE_RACE_IN_PROGRESS)"),
    M("g_cm_skip", "    if (pCopManager == NULL)\n        return;\n", ""),
    M("g_driver_eq", "TheDriverType != DRIVER_TYPE_AI_RACER) {",
      "TheDriverType == DRIVER_TYPE_AI_RACER) {"),
    M("g_driver_1", "TheDriverType != DRIVER_TYPE_AI_RACER) {",
      "TheDriverType != DRIVER_TYPE_PLAYER) {"),
    M("g_player_inv", "        if (c->pPlayer == NULL)\n",
      "        if (c->pPlayer != NULL)\n"),
    M("g_player_skip", "        if (c->pPlayer == NULL)\n            return;\n",
      ""),
    M("g_usage_inv", "UsageType == CAR_USAGE_TYPE_COP)",
      "UsageType != CAR_USAGE_TYPE_COP)"),
    M("g_usage_0", "UsageType == CAR_USAGE_TYPE_COP)", "UsageType == 0)"),

    # the distance
    M("d_way_eye", "    dx = pos->x - eye->x;\n", "    dx = pos->x;\n"),
    M("d_noz", "dist = sqrtf((dx * dx + dy * dy) + dz * dz) * DISTANCE_SCALE;",
      "dist = sqrtf(dx * dx + dy * dy) * DISTANCE_SCALE;"),
    M("d_order", "dist = sqrtf((dx * dx + dy * dy) + dz * dz) * DISTANCE_SCALE;",
      "dist = sqrtf(dx * dx + (dy * dy + dz * dz)) * DISTANCE_SCALE;"),
    M("d_min_skip", "    if (dist < 0.0f)\n        dist = 0.0f;\n", ""),
    M("d_max_skip", "    if (1.0f < dist)\n        dist = 1.0f;\n", ""),
    M("d_max_09", "    if (1.0f < dist)\n        dist = 1.0f;\n",
      "    if (0.9f < dist)\n        dist = 0.9f;\n"),
    M("d_pursued_inv", "pursued = copmanager_is_being_pursued(pCopManager, c) != NULL;",
      "pursued = copmanager_is_being_pursued(pCopManager, c) == NULL;"),
    M("d_damage_idx", "pCopManager->fCarDamage[c->CarIndex]",
      "pCopManager->fCarDamage[c->CarIndex + 1]"),
    M("d_damage_0", "pCopManager->fCarDamage[c->CarIndex]",
      "pCopManager->fCarDamage[0]"),
    M("d_args_swap", "fCarDamage[c->CarIndex], dist);",
      "fCarDamage[c->CarIndex], 0.0f);"),

    # the cap's setup
    M("c_tex_name", "bchunk_hash(\"WHITE16X16_NOALPHA\")",
      "bchunk_hash(\"WHITE16X16\")"),
    M("c_tex_default", "\"WHITE16X16_NOALPHA\"), 0, 0);",
      "\"WHITE16X16_NOALPHA\"), 1, 0);"),
    M("c_size_once", "s = (distance + distance) + CAP_SIZE_NEAR;",
      "s = distance + CAP_SIZE_NEAR;"),
    M("c_size_order", "s = (distance + distance) + CAP_SIZE_NEAR;",
      "s = distance + (distance + CAP_SIZE_NEAR);"),
    M("c_replay_4", "if (st == RCSTATE_INSTANT_REPLAY || st == RCSTATE_POSTRACE)",
      "if (st == RCSTATE_POSTRACE)"),
    M("c_replay_7", "if (st == RCSTATE_INSTANT_REPLAY || st == RCSTATE_POSTRACE)",
      "if (st == RCSTATE_INSTANT_REPLAY)"),
    M("c_replay_5", "if (st == RCSTATE_INSTANT_REPLAY || st == RCSTATE_POSTRACE)",
      "if (st == RCSTATE_AUTO_REPLAY || st == RCSTATE_POSTRACE)"),
    M("c_uv1", "    p.UVs[1][0] = 0.0f;\n", "    p.UVs[1][0] = 1.0f;\n"),
    M("c_uv1v", "    p.UVs[1][1] = 1.0f;\n", "    p.UVs[1][1] = 0.0f;\n"),
    M("c_uv2", "    p.UVs[2][0] = 1.0f;\n", "    p.UVs[2][0] = 0.0f;\n"),
    M("c_uv3", "    p.UVs[3][0] = 1.0f;\n", "    p.UVs[3][0] = 0.0f;\n"),
    M("c_uv3v", "    p.UVs[3][1] = 0.0f;\n", "    p.UVs[3][1] = 1.0f;\n"),
    M("c_frame_size", "eframe_malloc(64);", "eframe_malloc(48);"),
    M("c_frame_skip", "    if (m == NULL)\n        return;\n",
      "    if (m == NULL)\n        m = &local;\n"),
    M("c_local_row2", "local.v2 = c->State.BodyMatrix.v2;",
      "local.v2 = c->State.BodyMatrix.v1;"),
    M("c_local_w", "    local.v3.w = 1.0f;\n", "    local.v3.w = 0.0f;\n"),
    M("c_local_y", "local.v3.y = c->State.Position.y;",
      "local.v3.y = c->State.GeometryPosition.y;"),
    M("c_mul_order",
      "eMulMatrix(m, (const bMatrix4 *)(const void *)DamageAboveMatrix,\n"
      "               &local);",
      "eMulMatrix(m, &local,\n"
      "               (const bMatrix4 *)(const void *)DamageAboveMatrix);"),
    M("c_side_inv", "side = pursued ? COLOUR_SIDE_PURSUED : COLOUR_SIDE;",
      "side = pursued ? COLOUR_SIDE : COLOUR_SIDE_PURSUED;"),

    # the whole sides
    M("w_zero_ne", "if (damage == 0.0f) {", "if (damage != 0.0f) {"),
    M("w_zero_le", "if (damage == 0.0f) {", "if (damage <= 0.0f) {"),
    M("w_v1", "cap_point(&p.Vertices[1], &op[1 + i], s);",
      "cap_point(&p.Vertices[1], &op[1 + (i + 1) % 4], s);"),
    M("w_v2", "cap_point(&p.Vertices[2], &op[1 + (i + 1) % 4], s);\n"
      "            cap_point(&p.Vertices[3], &op[0], s);",
      "cap_point(&p.Vertices[2], &op[1 + i], s);\n"
      "            cap_point(&p.Vertices[3], &op[0], s);"),
    M("w_v3", "            cap_point(&p.Vertices[3], &op[0], s);\n"
      "            cap_colours(&p, side);",
      "            cap_point(&p.Vertices[3], &op[1], s);\n"
      "            cap_colours(&p, side);"),
    M("w_n3", "        for (i = 0; i < 4; i++) {\n            cap_point",
      "        for (i = 0; i < 3; i++) {\n            cap_point"),

    # the damaged sides
    M("e_edge_point", "edge[k].x = op[1 + k].x - op[0].x;",
      "edge[k].x = op[1 + k].x;"),
    M("e_edge_w", "edge[k].w = op[1 + k].w - op[0].w;",
      "edge[k].w = op[1 + k].w;"),
    M("e_len_noz", "len = sqrtf((edge[0].x * edge[0].x + edge[0].y * edge[0].y)\n"
      "                    + edge[0].z * edge[0].z);",
      "len = sqrtf(edge[0].x * edge[0].x + edge[0].y * edge[0].y);"),
    M("e_len_1", "edge[0].x * edge[0].x + edge[0].y * edge[0].y)",
      "edge[1].x * edge[1].x + edge[0].y * edge[0].y)"),
    M("e_f", "f = len * damage;", "f = damage;"),
    M("e_unit_skip", "            edge[k].y = edge[k].y * inv;\n", ""),
    M("e_unit_div", "            edge[k].z = edge[k].z * inv;\n",
      "            edge[k].z = edge[k].z / len;\n"),
    M("e_v1", "            cap_point(&p.Vertices[1], &op[0], s);\n            at.x",
      "            cap_point(&p.Vertices[1], &op[1], s);\n            at.x"),
    M("e_at2_j", "at.x = edge[j].x * f + op[0].x;", "at.x = edge[i].x * f + op[0].x;"),
    M("e_at2_f", "at.y = edge[j].y * f + op[0].y;", "at.y = edge[j].y + op[0].y;"),
    M("e_at3_i", "at.z = edge[i].z * f + op[0].z;", "at.z = edge[j].z * f + op[0].z;"),
    M("e_at3_op", "at.x = edge[i].x * f + op[0].x;", "at.x = edge[i].x * f;"),
    M("e_dmg_colour", "cap_colours(&p, pursued ? COLOUR_DAMAGE_PURSUED : COLOUR_DAMAGE);",
      "cap_colours(&p, pursued ? COLOUR_DAMAGE : COLOUR_DAMAGE_PURSUED);"),
    M("e_rest_v0", "p.Vertices[0] = p.Vertices[3];", "p.Vertices[0] = p.Vertices[2];"),
    M("e_rest_v1", "p.Vertices[1] = p.Vertices[2];", "p.Vertices[1] = p.Vertices[3];"),
    M("e_rest_v2", "cap_point(&p.Vertices[2], &op[1 + j], s);",
      "cap_point(&p.Vertices[2], &op[1 + i], s);"),
    M("e_rest_v3", "cap_point(&p.Vertices[3], &op[1 + i], s);\n            cap_colours",
      "cap_point(&p.Vertices[3], &op[1 + j], s);\n            cap_colours"),
    M("e_rest_skip", "cap_point(&p.Vertices[3], &op[1 + i], s);\n"
      "            cap_colours(&p, side);\n            cap_render(&p, tex, m);\n",
      "cap_point(&p.Vertices[3], &op[1 + i], s);\n"
      "            cap_colours(&p, side);\n"),
    M("e_j", "const int32_t j = (i + 1) % 4;", "const int32_t j = (i + 3) % 4;"),

    # the square, the points and the render
    M("q_v0", "cap_point(&p.Vertices[0], &op[1], s);",
      "cap_point(&p.Vertices[0], &op[0], s);"),
    M("q_v2", "cap_point(&p.Vertices[2], &op[3], s);",
      "cap_point(&p.Vertices[2], &op[4], s);"),
    M("q_skip", "    cap_colours(&p, side);\n    cap_render(&p, tex, m);\n}",
      "}"),
    M("p_w", "o->w = p->w * s;", "o->w = p->w;"),
    M("p_z", "o->z = p->z * s;", "o->z = p->z;"),
    M("p_pad", "op[k].w = ObjectPoints[k].pad;", "op[k].w = 0.0f;"),
    M("p_colour_g", "p->Colours[k][1] = (uint8_t)(colour >> 8);",
      "p->Colours[k][1] = (uint8_t)(colour >> 16);"),
    M("p_colour_a", "p->Colours[k][3] = (uint8_t)(colour >> 24);",
      "p->Colours[k][3] = 0x80;"),
    M("p_flags", "gEPolyRender3DFn(p, tex, m, 0);",
      "gEPolyRender3DFn(p, tex, m, 1);"),
]

# The pads reach only the vertices' fourth lane, which Render3D does not
# read and the transcript does not print; nor does an edge's. The
# distance's floor is retail's, and nothing reaches it.
EQUIVALENT = {
    "d_min_skip": "a root of a sum of squares is never below 0",
    "e_edge_w": "the edges' w lane is never read",
    "p_w": "the vertices' w lane is never read",
    "p_pad": "the pads reach only the w lane",
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
    print("%d scenarios, %d lines, %d differ" % (len(sc), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
