#!/usr/bin/env python3
"""Cross-check 3DS Files/source/rendercars.c (RenderCars and the two Car
helpers only it calls) against the retail image itself, run in mipsemu.

The model is the image: RenderCars (0x00124060) runs as shipped, with
0x00133190 (whether the car blinks in the view), 0x00135fb8 (the tyres'
and the brakes' matrices) and eIdentity. Four callees are stubs that
print their arguments, and the harness's stand-ins print the same:

- Car::IsPoofed and Car::IsBlinking, which answer from the scenario;
- CarRenderInfo::Render, which prints the four tyre and four brake
  matrices it was handed, since they are on the stack;
- Car::DamageAbove.

Any of them can move pCurrentWorld onto a later car at its k-th call, as
nothing in the game does yet, to show that both sides read it again for
every test of the loop. A pointer prints by what it is: a car, a car's
position or body matrix, the override's, the camera's eye or direction.

    python tools/rendercars_check.py
    python tools/rendercars_check.py --mutate [--only a,b]
    python tools/rendercars_check.py --dump out/rendercars
"""
import argparse
import itertools
import os
import random
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

HARNESS = "tools/src/rendercars_test.c"
RCC = "3DS Files/source/rendercars.c"
SOURCES = [HARNESS, RCC] + ["3DS Files/source/" + f for f in (
    "emath.c", "bmatrix.c", "bmath.c", "bmathtab.c", "bvector.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
RENDER_CARS = 0x00124060
IS_POOFED = 0x00133260
IS_BLINKING = 0x00133130
RENDER = 0x00120ef8
DAMAGE_ABOVE = 0x00135280

G_WORLD = GP - 22120              # pCurrentWorld
G_WTE = GP - 19560                # WorldTimeElapsed
G_FRAME = GP - 25260              # eFrameCounter
G_PLAYERS = GP - 20928            # Player::pPlayersByIndex[2]

# Retail's Car: the State's matrices where the demo has them, the rest
# 32 bytes on.
C_CTI = 12
C_POS = 80
C_BODY = 144
C_WHEEL = 240
C_BRAKE = 496
C_ENABLED = 1192                  # lb
C_RI = 1200
C_OVR = 1216                      # BodyMatrix; GeometryPosition at +64
O_BITS = 80                       # Override, Visible, Blinking at 80 84 88
CTI_WHEELS = 288                  # four of 32 bytes; the first 16 are read
CAM_HIDDEN = 444
CAM_EYE = 64
CAM_DIR = 80
V_CAMERA = 56
P_VIEWID = 24
P_ZONE = 88

WORLD = 0x01000000
VIEW = 0x01010000
CAM = 0x01011000
PLAYERS = (0x01012000, 0x01012400)
CTIS = 0x01020000
CTI_STRIDE = 0x200
NCTI = 4
CARS = 0x01100000
CAR_STRIDE = 0x600
MAXCARS = 128
RIS = 0x01400000
RI_STRIDE = 0x40

PATTERN = 0xa5
STACK_FILL = 0x77


def fb(v):
    if isinstance(v, int):
        return v & M32
    return f_to_bits(v)


def hexw(ws):
    return " ".join("%08x" % (w & M32) for w in ws)


def car_at(i):
    return CARS + CAR_STRIDE * i


# ============================================================ the scenarios


NAN = 0x7fc00000
SNAN = 0x7f800001
INF = 0x7f800000


class Sc(object):
    """One call. `cars` is a list of dicts: en (the byte), poof, blink
    (what the two stubs answer), ob vb bb (the override's three words),
    cti, ri (an index, -1 for NULL) and the 128 words of the wheels' and
    the brakes' matrices. `players` holds (view_id, zone) or None for
    each; `swap` is (who, k, j): at who's k-th call pCurrentWorld becomes
    car j."""

    def __init__(self, rnd, ncars=0, **kw):
        self.world = kw.get("world", True)
        self.view_id = kw.get("view_id", 0)
        self.hidden = kw.get("hidden", -1)
        self.players = kw.get("players", [None, None])
        self.wte = kw.get("wte", 1.0 / 60)
        self.frame = kw.get("frame", 1)
        self.swap = kw.get("swap", None)
        self.ctis = [[fb(rnd.uniform(-3.0, 3.0)) for _ in range(16)]
                     for _ in range(NCTI)]
        self.cars = []
        for i in range(ncars):
            self.cars.append(self.car(rnd, i))

    def car(self, rnd, i, **kw):
        c = dict(en=1, poof=0, blink=0, ob=0, vb=0xffffffff, bb=0,
                 cti=rnd.randrange(NCTI), ri=i)
        c["m"] = [fb(rnd.uniform(-50.0, 50.0)) for _ in range(128)]
        c.update(kw)
        return c

    def set_bits(self, c, which, on, rnd):
        """The view's bit of the word `which`, with every other bit
        random, and the bits a shift by 32 more or less would find the
        other way."""
        b = self.view_id & 31
        w = rnd.getrandbits(32)
        w &= ~(1 << b)
        if on:
            w |= 1 << b
        for other in (b + 1, b - 1):
            if 0 <= other < 32:
                w = (w | (1 << other)) if not on else (w & ~(1 << other))
        c[which] = w & M32

    def lines(self):
        out = ["S %x %x %x %x %x %x" % (
            self.view_id & M32, self.hidden & M32, 1 if self.world else 0,
            fb(self.wte), self.frame & M32, len(self.cars))]
        for k, p in enumerate(self.players):
            if p is None:
                out.append("P %x 0 0 0" % k)
            else:
                out.append("P %x 1 %x %x" % (k, p[0] & M32, p[1] & M32))
        for j, ws in enumerate(self.ctis):
            out.append("K %x %s" % (j, hexw(ws)))
        for i, c in enumerate(self.cars):
            out.append("C %x %x %x %x %x %x %x %x %x" % (
                i, c["en"] & 0xff, c["poof"] & M32, c["blink"] & M32,
                c["ob"], c["vb"], c["bb"], c["cti"], c["ri"] & M32))
            out.append("M %x %s" % (i, hexw(c["m"])))
        if self.swap:
            who, k, j = self.swap
            out.append("X %s %x %x" % (who, k, j))
        out.append("G")
        return out


WTES = [0.0, -0.0, 0.001, -0.001, 0x3a83126e, 0x3a831270, 0.0011, 1.0 / 60,
        -1.0 / 60, NAN, INF, 0xff800000]


def script():
    rnd = random.Random(0x5e4c)
    sc = []

    def mk(ncars=0, **kw):
        s = Sc(rnd, ncars, **kw)
        sc.append(s)
        return s

    # No world, an empty list, and one plain car in view 0.
    mk(3, world=False)
    mk(0)
    mk(1)
    for vid in (0, 1, 2, 3):
        mk(2, view_id=vid)

    # Every flag a car has, eight cars a call, in each view; in view 0
    # paused and on even frames as well.
    combos = list(itertools.product(
        (1, 0, 0xff, 0x80), (0, 1, 2, -1), (0, 1, -1),
        (0, 1), (0, 1), (0, 1)))
    timings = {0: ((1.0 / 60, 1), (0.0, 1), (1.0 / 60, 0), (1.0 / 60, 2))}
    for vid in (0, 1, 3, 31, 32, 33, -1, 0x7fffffff):
        for wte, frame in timings.get(vid, ((1.0 / 60, 1),)):
            for start in range(0, len(combos), 8):
                s = mk(0, view_id=vid, wte=wte, frame=frame)
                for i, (en, poof, blink, ob, vb, bb) in enumerate(
                        combos[start:start + 8]):
                    c = s.car(rnd, i, en=en, poof=poof, blink=blink)
                    s.set_bits(c, "ob", ob, rnd)
                    s.set_bits(c, "vb", vb, rnd)
                    s.set_bits(c, "bb", bb, rnd)
                    s.cars.append(c)

    # The blink's timing: a car IsBlinking says blinks, one whose bit
    # does, one the override keeps from blinking, and a plain one.
    for vid in (0, 33):
        for wte in WTES:
            for frame in (0, 1, 2, 3, 0xffffffff, 0x80000000):
                s = mk(0, view_id=vid, wte=wte, frame=frame)
                for i, (blink, ob, bb) in enumerate(
                        ((1, 0, 0), (0, 0, 1), (1, 1, 1), (0, 0, 0))):
                    c = s.car(rnd, i, blink=blink)
                    s.set_bits(c, "ob", ob, rnd)
                    s.set_bits(c, "bb", bb, rnd)
                    s.set_bits(c, "vb", 1, rnd)
                    s.cars.append(c)

    # The camera's own car, first, in the middle and last, and none.
    for h in (-1, 0, 2, 4, 5):
        mk(5, hidden=h)
    s = mk(3, hidden=1)
    s.cars[1]["en"] = 0

    # The cap: exactly 99, one over, a few over, and cars not drawn among
    # the first 99 that let later ones in.
    for n in (98, 99, 100, 105, 128):
        mk(n)
    s = mk(104)
    for i in (3, 40, 97):
        s.cars[i]["poof"] = 1
    s.cars[10]["en"] = 0
    s.cars[20]["vb"] = 0
    s = mk(102, hidden=50)
    s.cars[101]["ob"] = 0xffffffff
    s = mk(101, frame=0)
    for i in range(0, 101, 7):
        s.cars[i]["blink"] = 1

    # The players: which one is the view's, and its zone.
    zones = (0, 5, 6, 7, 8, -1, 0x106)
    for vid in (0, 1, 33):
        for z in zones:
            mk(2, view_id=vid, players=[(vid, z), None])
            mk(2, view_id=vid, players=[(vid + 1, z), (vid, z)])
            mk(2, view_id=vid, players=[(vid, z), (vid, 6)])
            mk(2, view_id=vid, players=[(vid + 1, 6), (vid + 2, z)])
            mk(2, view_id=vid, players=[None, (vid, z)])
            mk(2, view_id=vid, players=[(vid - 1, z), None])
            mk(2, view_id=vid, players=[(vid ^ 32, z), (vid, 7)])
        mk(2, view_id=vid, players=[None, None])

    # The render info: NULL, and one shared by two cars.
    s = mk(3)
    s.cars[1]["ri"] = -1
    s = mk(3)
    s.cars[2]["ri"] = 0

    # The world moved by a callee, onto a later car, at each of the four.
    for who in "pbrd":
        for k, j in ((1, 1), (1, 3), (2, 2), (2, 4), (3, 5), (5, 5)):
            s = mk(6, swap=(who, k, j))
            for c in s.cars:
                c["ob"] = 0
    # ... and where a car is not drawn: the loop's next test still reads
    # it again after the blink's call.
    s = mk(5, swap=("b", 2, 3))
    s.cars[1]["vb"] = 0
    s = mk(5, swap=("p", 1, 2))
    s.cars[0]["poof"] = 1
    s = mk(5, swap=("r", 1, 3), players=[(0, 6), None])

    # And at random.
    for n in range(400):
        vid = rnd.choice((0, 1, 2, 3, rnd.getrandbits(32)))
        players = []
        for k in range(2):
            if rnd.random() < 0.3:
                players.append(None)
            else:
                players.append((rnd.choice((vid, vid, vid + 1,
                                            rnd.getrandbits(32))),
                                rnd.choice((0, 5, 6, 7, 8,
                                            rnd.getrandbits(32)))))
        s = mk(0, view_id=vid, players=players,
               wte=rnd.choice(WTES + [rnd.uniform(-0.01, 0.01)]),
               frame=rnd.getrandbits(32))
        nc = rnd.randrange(9)
        for i in range(nc):
            c = s.car(rnd, i,
                      en=rnd.choice((1, 1, 1, 0, rnd.getrandbits(8))),
                      poof=rnd.choice((0, 0, 0, 1, s32(rnd.getrandbits(32)))),
                      blink=rnd.choice((0, 0, 1, s32(rnd.getrandbits(32)))),
                      ri=rnd.choice((i, i, i, -1, 0)))
            for which, p in (("ob", 0.3), ("vb", 0.85), ("bb", 0.3)):
                s.set_bits(c, which, rnd.random() < p, rnd)
            s.cars.append(c)
        if nc and rnd.random() < 0.3:
            s.hidden = rnd.randrange(-1, nc)
    return sc


# ================================================================ the model


class Model(object):
    def __init__(self):
        self.out = []
        self.e = retail_model.RetailEmu(ieee=True)
        e = self.e
        e.stub(IS_POOFED, self.poofed)
        e.stub(IS_BLINKING, self.blinking)
        e.stub(RENDER, self.render)
        e.stub(DAMAGE_ABOVE, self.damage)
        self.names = {}

    def emit(self, s):
        self.out.append(s)

    def arg(self, i):
        return self.e.reg[(4, 5, 6, 7, 8, 9, 10, 11)[i]] & M32

    def fill_stack(self):
        sp = self.e.reg[29] & M32
        self.e.write(sp - 16384, bytes([STACK_FILL]) * 16384)

    def ws(self, a, n):
        return hexw(self.e.u32(a + 4 * i) for i in range(n))

    # ---- the labels ------------------------------------------------------

    def register(self):
        n = {WORLD: "world", VIEW: "view", CAM + CAM_EYE: "cam.eye",
             CAM + CAM_DIR: "cam.dir"}
        for i in range(MAXCARS):
            c = car_at(i)
            n[c] = "car%d" % i
            n[c + C_POS] = "car%d.pos" % i
            n[c + C_BODY] = "car%d.body" % i
            n[c + C_OVR] = "car%d.obody" % i
            n[c + C_OVR + 64] = "car%d.opos" % i
            n[RIS + RI_STRIDE * i] = "ri%d" % i
        self.names = n

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        return self.names.get(a, "-")

    def car_index(self, a):
        return ((a & M32) - CARS) // CAR_STRIDE

    # ---- the stubs -------------------------------------------------------

    def after(self, who):
        self.calls[who] += 1
        sw = self.sc.swap
        if sw and sw[0] == who and self.calls[who] == sw[1]:
            self.e.put32(G_WORLD, car_at(sw[2]))

    def poofed(self, em):
        c = self.arg(0)
        v = self.sc.cars[self.car_index(c)]["poof"]
        self.emit("  poof %s -> %d" % (self.label(c), s32(v)))
        self.after("p")
        return s32(v)

    def blinking(self, em):
        c = self.arg(0)
        v = self.sc.cars[self.car_index(c)]["blink"]
        self.emit("  blink %s -> %d" % (self.label(c), s32(v)))
        self.after("b")
        return s32(v)

    def render(self, em):
        self.emit("  render %s %s %s %s %d %d | %s | %s" % (
            self.label(self.arg(0)), self.label(self.arg(1)),
            self.label(self.arg(2)), self.label(self.arg(3)),
            s32(self.arg(6)), s32(self.arg(7)),
            self.ws(self.arg(4), 64), self.ws(self.arg(5), 64)))
        self.after("r")

    def damage(self, em):
        self.emit("  dmg %s %s %s" % (
            self.label(self.arg(0)), self.label(self.arg(1)),
            self.label(self.arg(2))))
        self.after("d")

    # ---- the world -------------------------------------------------------

    def fill(self, a, n):
        self.e.write(a, bytes([PATTERN]) * n)

    def world(self, sc):
        e = self.e
        p = e.put32
        self.fill(WORLD, 64)
        self.fill(VIEW, 64)
        self.fill(CAM, 512)
        for a in PLAYERS:
            self.fill(a, 128)
        self.fill(CTIS, CTI_STRIDE * NCTI)
        self.fill(CARS, CAR_STRIDE * max(len(sc.cars), 1))

        p(VIEW, sc.view_id)
        p(VIEW + V_CAMERA, CAM)
        p(CAM + CAM_HIDDEN, car_at(sc.hidden) if sc.hidden >= 0 else 0)
        p(G_WORLD, WORLD if sc.world else 0)
        p(G_WTE, fb(sc.wte))
        p(G_FRAME, sc.frame)
        for k, pl in enumerate(sc.players):
            if pl is None:
                p(G_PLAYERS + 4 * k, 0)
            else:
                p(G_PLAYERS + 4 * k, PLAYERS[k])
                p(PLAYERS[k] + P_VIEWID, pl[0])
                p(PLAYERS[k] + P_ZONE, pl[1])
        for j, ws in enumerate(sc.ctis):
            for w in range(4):
                for q in range(4):
                    p(CTIS + CTI_STRIDE * j + CTI_WHEELS + 32 * w + 4 * q,
                      ws[4 * w + q])

        n = len(sc.cars)
        p(WORLD, car_at(0) if n else WORLD)
        p(WORLD + 4, car_at(n - 1) if n else WORLD)
        for i, c in enumerate(sc.cars):
            a = car_at(i)
            p(a, car_at(i + 1) if i + 1 < n else WORLD)
            p(a + 4, car_at(i - 1) if i else WORLD)
            p(a + C_CTI, CTIS + CTI_STRIDE * c["cti"])
            e.mem[a + C_ENABLED] = c["en"] & 0xff
            p(a + C_RI, RIS + RI_STRIDE * c["ri"] if c["ri"] >= 0 else 0)
            p(a + C_OVR + O_BITS, c["ob"])
            p(a + C_OVR + O_BITS + 4, c["vb"])
            p(a + C_OVR + O_BITS + 8, c["bb"])
            for q in range(64):
                p(a + C_WHEEL + 4 * q, c["m"][q])
                p(a + C_BRAKE + 4 * q, c["m"][64 + q])

    def run(self, scenarios):
        self.register()
        for n, sc in enumerate(scenarios):
            self.sc = sc
            self.calls = dict.fromkeys("pbrd", 0)
            self.world(sc)
            self.emit("R %d" % n)
            self.fill_stack()
            self.e.call(RENDER_CARS, VIEW, limit=2000000)
            self.emit("E %s" % self.label(self.e.u32(G_WORLD)))
        return self.out


# ================================================================ the build


def build_harness(tmp, name="rendercars_test"):
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
    return (name, RCC, before, after)


MUTATIONS = [
    # view_bit
    M("vb_mask_15", "view_id & 31u)) & 1u", "view_id & 15u)) & 1u"),
    M("vb_two_bits", "view_id & 31u)) & 1u", "view_id & 31u)) & 3u"),
    M("vb_bit_up", "(bits >> ((uint32_t)view_id & 31u))",
      "(bits >> (((uint32_t)view_id + 1u) & 31u))"),

    # car_is_blinking_in_view
    M("bv_over_ret", "        return 0;\n    if (car_is_blinking(c))",
      "        return 1;\n    if (car_is_blinking(c))"),
    M("bv_over_skip",
      "    if (view_bit(o->OverrideViewBits, view_id))\n        return 0;\n",
      ""),
    M("bv_over_word", "if (view_bit(o->OverrideViewBits, view_id))\n",
      "if (view_bit(o->VisibleViewBits, view_id))\n"),
    M("bv_blink_ret", "        return 1;\n    return view_bit",
      "        return 0;\n    return view_bit"),
    M("bv_blink_skip", "    if (car_is_blinking(c))\n        return 1;\n", ""),
    M("bv_bits_word", "view_bit(o->BlinkingViewBits, view_id) ? 1 : 0",
      "view_bit(o->VisibleViewBits, view_id) ? 1 : 0"),
    M("bv_bits_inv", "view_id) ? 1 : 0;", "view_id) ? 0 : 1;"),
    M("bv_bits_zero", "view_id) ? 1 : 0;", "view_id) ? 0 : 0;"),

    # car_get_render_wheel_matrices
    M("wm_over_inv",
      "if (view_bit(c->TheOverrideRenderingPosition.OverrideViewBits",
      "if (!view_bit(c->TheOverrideRenderingPosition.OverrideViewBits"),
    M("wm_over_word",
      "TheOverrideRenderingPosition.OverrideViewBits, view_id)) {",
      "TheOverrideRenderingPosition.VisibleViewBits, view_id)) {"),
    M("wm_ident_tire", "            eIdentity(&tires[i]);\n", ""),
    M("wm_ident_brake", "            eIdentity(&brakes[i]);\n", ""),
    M("wm_ident_both", "            eIdentity(&brakes[i]);\n",
      "            eIdentity(&tires[i]);\n"),
    M("wm_wheel0", "Wheels[i];", "Wheels[0];"),
    M("wm_wheel_next", "Wheels[i];", "Wheels[(i + 1) & 3];"),
    M("wm_tx", "tires[i].v3.x = w->PositionX;", "tires[i].v3.x = w->PositionY;"),
    M("wm_ty", "tires[i].v3.y = w->PositionY;", "tires[i].v3.y = w->PositionX;"),
    M("wm_tz", "tires[i].v3.z = w->PositionZ;", "tires[i].v3.z = w->Radius;"),
    M("wm_tw", "tires[i].v3.w = 1.0f;", "tires[i].v3.w = w->Radius;"),
    M("wm_bx", "brakes[i].v3.x = w->PositionX;",
      "brakes[i].v3.x = w->PositionZ;"),
    M("wm_by", "brakes[i].v3.y = w->PositionY;", "brakes[i].v3.y = 0.0f;"),
    M("wm_bz", "brakes[i].v3.z = w->PositionZ;",
      "brakes[i].v3.z = w->PositionY;"),
    M("wm_bw", "brakes[i].v3.w = 1.0f;", "brakes[i].v3.w = 0.0f;"),
    M("wm_over_n3", "for (i = 0; i < 4; i++) {\n            const WheelInfo",
      "for (i = 0; i < 3; i++) {\n            const WheelInfo"),
    M("wm_no_return",
      "        return;\n    }\n    for (i = 0; i < 4; i++) {\n        tires",
      "    }\n    for (i = 0; i < 4; i++) {\n        tires"),
    M("wm_copy_n3", "for (i = 0; i < 4; i++) {\n        tires[i] =",
      "for (i = 0; i < 3; i++) {\n        tires[i] ="),
    M("wm_copy_swap", "brakes[i] = c->State.BrakeMatrix[i];",
      "brakes[i] = c->State.WheelMatrix[i];"),
    M("wm_copy_idx", "tires[i] = c->State.WheelMatrix[i];",
      "tires[i] = c->State.WheelMatrix[0];"),
    M("wm_copy_bidx", "brakes[i] = c->State.BrakeMatrix[i];",
      "brakes[i] = c->State.BrakeMatrix[3 - i];"),

    # view_in_jump_cam
    M("jc_p0_null", "    if (p == NULL)\n        return 0;",
      "    if (p == NULL)\n        return 1;"),
    M("jc_p0_always_p1", "    if (view->ID != p->ViewID) {", "    if (1) {"),
    M("jc_p0_never_p1", "    if (view->ID != p->ViewID) {", "    if (0) {"),
    M("jc_p1_index", "p = PlayerPlayersByIndex[1];",
      "p = PlayerPlayersByIndex[0];"),
    M("jc_p1_id", "if (p == NULL || view->ID != p->ViewID)",
      "if (p == NULL)"),
    M("jc_p1_ret", "            return 0;\n    }\n    return p->",
      "            return 1;\n    }\n    return p->"),
    M("jc_zone6", "== PLAYER_ZONE_JUMP_CAM", "== 5"),
    M("jc_zone7", "== PLAYER_ZONE_AFTER_JUMP", "== 8"),
    M("jc_and", "\n        || p->nZoneCurrent", "\n        && p->nZoneCurrent"),
    M("jc_ge6", "return p->nZoneCurrent == PLAYER_ZONE_JUMP_CAM",
      "return p->nZoneCurrent >= PLAYER_ZONE_JUMP_CAM"),

    # render_cars
    M("rc_null_world", "    if (pCurrentWorld == NULL)\n        return;\n", ""),
    M("rc_world_once", [
        ("    hidden = (Car *)camera->CarNotToRender;\n",
         "    hidden = (Car *)camera->CarNotToRender;\n"
         "    World *w0 = pCurrentWorld;\n"),
        ("car != (Car *)&pCurrentWorld->CarList;",
         "car != (Car *)&w0->CarList;")], None),
    M("rc_next_prev", "car = (Car *)car->Link.next) {",
      "car = (Car *)car->Link.prev) {"),
    M("rc_left_98", "int32_t left = 99;", "int32_t left = 98;"),
    M("rc_left_100", "int32_t left = 99;", "int32_t left = 100;"),
    M("rc_left_lt", "left <= 0 ||", "left < 0 ||"),
    M("rc_left_early", [
        ("        left--;\n        car_get", "        car_get"),
        ("draw = car_is_poofed(car) ^ 1;",
         "draw = car_is_poofed(car) ^ 1;\n        left--;")], None),
    M("rc_left_never", "        left--;\n", ""),
    M("rc_hidden", "car == hidden || ", ""),
    M("rc_enabled", " || !car->RenderingEnabled", ""),
    M("rc_not_poof", "draw = car_is_poofed(car) ^ 1;",
      "draw = !car_is_poofed(car);"),
    M("rc_poof_raw", "draw = car_is_poofed(car) ^ 1;",
      "draw = car_is_poofed(car);"),
    M("rc_poof_low", "draw = car_is_poofed(car) ^ 1;",
      "draw = (car_is_poofed(car) & 1) ^ 1;"),
    M("rc_blink_or", "view->ID)\n            && !(fabsf",
      "view->ID)\n            || !(fabsf"),
    M("rc_blink_view", "car_is_blinking_in_view(car, view->ID)",
      "car_is_blinking_in_view(car, 0)"),
    M("rc_fabs", "!(fabsf(WorldTimeElapsed) <= 0.001f)",
      "!(WorldTimeElapsed <= 0.001f)"),
    M("rc_le_lt", "!(fabsf(WorldTimeElapsed) <= 0.001f)",
      "!(fabsf(WorldTimeElapsed) < 0.001f)"),
    M("rc_gt", "!(fabsf(WorldTimeElapsed) <= 0.001f)",
      "fabsf(WorldTimeElapsed) > 0.001f"),
    M("rc_not", "&& !(fabsf(WorldTimeElapsed) <= 0.001f))",
      "&& (fabsf(WorldTimeElapsed) <= 0.001f))"),
    M("rc_eps_up", "<= 0.001f)", "<= 0.0010001f)"),
    M("rc_eps_down", "<= 0.001f)", "<= 0.0009999f)"),
    M("rc_eps_double", "<= 0.001f)", "<= 0.001)"),
    M("rc_frame_bit", "eFrameCounter & 1u", "eFrameCounter & 2u"),
    M("rc_frame_inv", "(int32_t)(eFrameCounter & 1u)",
      "(int32_t)(~eFrameCounter & 1u)"),
    M("rc_frame_all", "(int32_t)(eFrameCounter & 1u)",
      "(int32_t)eFrameCounter"),
    M("rc_vis_inv", "if (!view_bit(o->VisibleViewBits",
      "if (view_bit(o->VisibleViewBits"),
    M("rc_vis_word", "if (!view_bit(o->VisibleViewBits",
      "if (!view_bit(o->BlinkingViewBits"),
    M("rc_vis_one", "            draw = 0;\n        if (!draw)",
      "            draw = 1;\n        if (!draw)"),
    M("rc_vis_skip", "        if (!view_bit(o->VisibleViewBits, view->ID))\n"
      "            draw = 0;\n", ""),
    M("rc_nodraw", "        if (!draw)\n            continue;\n", ""),
    M("rc_helper_view", "brakes, view->ID);", "brakes, 0);"),
    M("rc_over_word", "over = (int32_t)view_bit(o->OverrideViewBits",
      "over = (int32_t)view_bit(o->VisibleViewBits"),
    M("rc_over_view", "view_bit(o->OverrideViewBits, view->ID);",
      "view_bit(o->OverrideViewBits, 0);"),
    M("rc_pos_swap", "over ? &o->GeometryPosition\n"
      "                                  : &car->State.GeometryPosition,",
      "over ? &car->State.GeometryPosition\n"
      "                                  : &o->GeometryPosition,"),
    M("rc_pos_state", "over ? &o->GeometryPosition\n",
      "0 ? &o->GeometryPosition\n"),
    M("rc_body_swap", "over ? &o->BodyMatrix : &car->State.BodyMatrix",
      "over ? &car->State.BodyMatrix : &o->BodyMatrix"),
    M("rc_body_state", "over ? &o->BodyMatrix : &car->State.BodyMatrix",
      "&car->State.BodyMatrix"),
    M("rc_ri", "carrenderinfo_render(car->pRenderInfo, view,",
      "carrenderinfo_render((CarRenderInfo *)car, view,"),
    M("rc_view", "carrenderinfo_render(car->pRenderInfo, view,",
      "carrenderinfo_render(car->pRenderInfo, NULL,"),
    M("rc_tb_swap", "tires, brakes, 0, 0);", "brakes, tires, 0, 0);"),
    M("rc_flags", "tires, brakes, 0, 0);", "tires, brakes, 1, 0);"),
    M("rc_forced", "tires, brakes, 0, 0);", "tires, brakes, 0, 8);"),
    M("rc_jc_inv", "if (!view_in_jump_cam(view) && gCarDamageAboveFn",
      "if (view_in_jump_cam(view) && gCarDamageAboveFn"),
    M("rc_jc_skip", "if (!view_in_jump_cam(view) && gCarDamageAboveFn",
      "if (gCarDamageAboveFn"),
    M("rc_dmg_none", "gCarDamageAboveFn != NULL)", "gCarDamageAboveFn == NULL)"),
    M("rc_dmg_eye", "gCarDamageAboveFn(car, &camera->CurrentKey.Position,",
      "gCarDamageAboveFn(car, &camera->CurrentKey.Direction,"),
    M("rc_dmg_dir", "&camera->CurrentKey.Direction);",
      "&camera->CurrentKey.Position);"),
]

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
    print("%d scenarios, %d lines, %d differ" % (len(sc), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
