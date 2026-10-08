#!/usr/bin/env python3
"""Cross-check 3DS Files/source/rvmcam.c, the rear-view mirror's mover and
Player::SetRearViewMirrorCameraMover, against the retail image itself, run
in mipsemu.

The model is the image. RearViewMirrorCameraMover's constructor
(0x00158f78), destructor (0x00158fe0), Update (0x00158ff8) and
GetCarToFollow (0x0015fb08) run as shipped, through retail's vtable
(0x002b1b50) where the game goes through it, and so does
Player::SetRearViewMirrorCameraMover (0x001767a8), which deletes movers
through it with the flag 3. Under them run the CameraMover base, eGetView,
Camera::SetCameraMatrix and the matrix layer, over retail's own eView
table.

Stubs, each printing what it was given as the harness's stand-ins do:
ApplyCameraShake (0x00156560), which also adds the script's delta to the
matrix's translation, bMalloc (0x002577c0), which hands out the arena's
blocks in turn, and __builtin_delete and __builtin_vec_delete, which print
the block. Everything else the code reads is laid out in memory by the
script: the cars (GeometryPosition at 80, BodyMatrix at 144), the players
(MyCar at 4, RearViewMirrorViewID at 28, pRVMCameraMover at 212),
RVMOffsetInCar at 0x00334180, RealTimeElapsed at gp-19596 and
Camera::StopUpdating at gp-21808.

The transcript opens with RVMOffsetInCar as CameraMover.obj's static
init (0x0015f6d0) leaves it and as the port's starts.

Every camera, mover and block starts from a byte pattern, so what a call
leaves alone shows. A float prints as its bits, a NaN as "nan", and a
pointer by what it is.

    python tools/rvmcam_check.py
    python tools/rvmcam_check.py --mutate [--only a,b]
    python tools/rvmcam_check.py --dump out/rvmcam
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

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import mutpar
import physicscar_check as pcc
import retail_model
from mipsemu import M32, f_to_bits, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/rvmcam_test.c"
RVM = "3DS Files/source/rvmcam.c"
SOURCES = [HARNESS, RVM] + ["3DS Files/source/" + f for f in (
    "cammover.c", "camera.c", "eview.c", "emath.c", "bmatrix.c", "bmath.c",
    "bmathtab.c", "bvector.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
CAM_CTOR = 0x00156be0
RVM_CTOR = 0x00158f78
RVM_UPDATE = 0x00158ff8
RVM_VTBL = 0x002b1b50
BASE_VTBL = 0x002b1e50
SET_RVM = 0x001767a8
BMALLOC = 0x002577c0
SHAKE = 0x00156560
VEC_DELETE = 0x00114e90
DELETE = 0x00114e98
EMATH_SINIT = 0x0011bf70          # writes eMulVector's (0, 0, 0, 1)
CAM_SINIT = 0x0015f6d0            # CameraMover.obj's, RVMOffsetInCar's
RVM_OFFSET = 0x00334180
VIEWS = 0x002c95b0
VIEW_STRIDE = 128
NVIEWS = 10
V_CAMERA = 56
V_LIST = 60

G_STOP = GP - 21808               # Camera::StopUpdating
G_RTE = GP - 19596                # RealTimeElapsed

CAM_SIZE = 464
CAMS = 0x01000000
NCAM = 4
MOVS = 0x01010000
MOV_STRIDE = 64
NMOV = 3
ARENA = 0x01011000
NARENA = 8
CARS = 0x01020000
CAR_STRIDE = 0x1000
NCAR = 3
PLAYERS = 0x01030000
PLAYER_STRIDE = 0x1000
NPLAYER = 2

C_GPOS = 80
C_BODY = 144
P_CAR = 4
P_VIEW = 28
P_RVM = 212

PATTERN = 0xa5

# The vtable's slots, by the function's offset.
SLOTS = {
    "destroy": 12, "update": 20, "render": 28, "info": 52, "pov": 60,
    "ext": 68, "lookback": 76, "gap": 84, "car": 116, "target": 124,
}

F32 = np.float32


def fb(v):
    if isinstance(v, int):
        return v & M32
    return f_to_bits(v)


def h(v):
    return "%08x" % fb(v)


def fx(w):
    """A float's bits, with every NaN the one "nan"."""
    w &= M32
    if (w & 0x7f800000) == 0x7f800000 and (w & 0x7fffff):
        return "nan"
    return "%08x" % w


def bits_f(w):
    return F32(struct.unpack("<f", struct.pack("<I", w & M32))[0])


def f_bits(x):
    return struct.unpack("<I", struct.pack("<f", float(F32(x))))[0]


def cam_at(k):
    return CAMS + CAM_SIZE * k


def mov_at(j):
    return MOVS + MOV_STRIDE * j


def arena_at(i):
    return ARENA + MOV_STRIDE * i


def car_at(i):
    return 0 if i < 0 else CARS + CAR_STRIDE * i


def player_at(i):
    return PLAYERS + PLAYER_STRIDE * i


def view_at(i):
    return VIEWS + VIEW_STRIDE * i


# ============================================================ the scenarios


def vec(*xs):
    return " ".join(h(x) for x in xs)


def gpos_line(rnd, i, pos=None):
    if pos is None:
        pos = [rnd.uniform(-600, 600), rnd.uniform(-600, 600),
               rnd.uniform(-20, 80)]
    return "K %d %s" % (i, vec(pos[0], pos[1], pos[2],
                               rnd.choice((1.0, 0.0, rnd.uniform(-2, 2)))))


def body_line(rnd, i, yaw=None, tilt=0.2):
    """Car `i`'s BodyMatrix: turned by `yaw` about z, tipped a little
    about the other two, its fourth column and row (0, 0, 0, 1) or off
    them."""
    if yaw is None:
        yaw = rnd.uniform(-math.pi, math.pi)
    p, r = rnd.uniform(-tilt, tilt), rnd.uniform(-tilt, tilt)
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(p), math.sin(p)
    cr, sr = math.cos(r), math.sin(r)
    rows = [[cy * cp, sy * cp, -sp],
            [cy * sp * sr - sy * cr, sy * sp * sr + cy * cr, cp * sr],
            [cy * sp * cr + sy * sr, sy * sp * cr - cy * sr, cp * cr]]
    t = [0.0, 0.0, 0.0]
    if rnd.random() < 0.2:
        t = [rnd.uniform(-3, 3) for _ in range(3)]
    ws = [0.0, 0.0, 0.0]
    if rnd.random() < 0.15:
        ws = [rnd.uniform(-0.5, 0.5) for _ in range(3)]
    words = []
    for row, wv in zip(rows, ws):
        words += row + [wv]
    words += t + [rnd.choice((1.0, 1.0, rnd.uniform(0.5, 2)))]
    return "M %d %s" % (i, vec(*words))


def cams(n):
    out = []
    for k in range(n):
        out += ["C %d" % k, "V %d %d" % (k, k)]
    return out


def offset_line(rnd):
    return "R %s" % vec(*rnd.choice((
        (0.0, 0.5, 0.0, 0.0),
        (-0.0, 0.5, -0.0, 0.0),
        (rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-1, 1),
         rnd.uniform(-1, 1)),
        (0.25, -0.75, 1.5, 3.0))))


def shake_line(rnd):
    return "H %s" % vec(*(rnd.choice((0.0, 0.0, rnd.uniform(-0.2, 0.2)))
                          for _ in range(4)))


def s_ctor(rnd):
    """Construction on each of the four views, with and without a car,
    the camera frozen and not, over what another mover left on the
    camera; two on one view; the vtable's other slots; then the
    destructor, frozen and not, in and out of the list's order."""
    out = cams(4)
    for i in range(8):
        out += [gpos_line(rnd, i % NCAR), body_line(rnd, i % NCAR)]
        car = -1 if i % 4 == 3 else i % NCAR
        j = i % NMOV
        view = i % 4
        out += ["Y %d %d %d %04x" % (view, (i + 1) % NCAR, rnd.choice((0, 1)),
                                     rnd.getrandbits(16)),
                "L %d %s %s" % (view, h(rnd.uniform(0.1, 2)),
                                h(rnd.uniform(100, 9000))),
                "Z %d" % (i % 3 == 2),
                "O %d %d %d" % (j, view, car), "G o%d" % j, "Z 0"]
        if i % 3 == 1:
            out += ["O %d %d %d" % ((j + 1) % NMOV, view, car),
                    "G o%d" % ((j + 1) % NMOV),
                    "Z %d" % (i % 2), "D o%d" % j, "Z 0",
                    "D o%d" % ((j + 1) % NMOV)]
        else:
            out += ["Z %d" % (i % 4 == 0), "D o%d" % j, "Z 0"]
    return out


def s_update(rnd, frames):
    """The mirror behind a car moving round: the car's place and body
    changing each frame, the offset, the shake, the clock and the freeze
    changing on the way."""
    out = cams(4)
    view = rnd.choice((3, 3, 1))
    car = rnd.randrange(NCAR)
    pos = [rnd.uniform(-500, 500), rnd.uniform(-500, 500),
           rnd.uniform(-20, 80)]
    yaw = rnd.uniform(-math.pi, math.pi)
    out += [gpos_line(rnd, car, pos), body_line(rnd, car, yaw),
            offset_line(rnd), shake_line(rnd),
            "Y %d %d 1 %04x" % (view, (car + 1) % NCAR, rnd.getrandbits(16)),
            "O 0 %d %d" % (view, car)]
    vel = [rnd.uniform(-3, 3) for _ in range(3)]
    for i in range(frames):
        pos = [p + v for p, v in zip(pos, vel)]
        yaw += rnd.uniform(-0.1, 0.1)
        out += [gpos_line(rnd, car, pos), body_line(rnd, car, yaw)]
        k = rnd.random()
        if k < 0.06:
            out.append("T %s" % h(rnd.choice((0.0, 1 / 30.0, 1 / 60.0,
                                              rnd.uniform(0, 0.1)))))
        elif k < 0.10:
            out.append("Z %d" % rnd.choice((0, 0, 1)))
        elif k < 0.16:
            out.append(offset_line(rnd))
        elif k < 0.24:
            out.append(shake_line(rnd))
        elif k < 0.28:
            out.append("Y %d %d %d %04x" % (view, rnd.randrange(-1, NCAR),
                                            rnd.choice((0, 1)),
                                            rnd.getrandbits(16)))
        elif k < 0.31:
            out.append("L %d %s %s" % (view, h(rnd.uniform(0.1, 2)),
                                       h(rnd.uniform(100, 9000))))
        out.append("U o0")
    # Frozen over clip planes and a field of view another mover left:
    # the planes are set anyway, the field of view is not.
    out += ["L %d %s %s" % (view, h(0.25), h(5000.0)),
            "Y %d %d 1 1234" % (view, car), "Z 1", "U o0"]
    out += ["Z 0", "G o0", "D o0"]
    return out


def s_zeros(rnd):
    """Bodies, places and offsets of zeros of both signs and small whole
    numbers, so that what the turns and the products do to the sign of a
    zero shows."""
    out = cams(4) + ["O 2 3 1"]
    vals = (-0.0, 0.0, -0.0, 0.0, -1.0, 1.0, -0.5, 2.0)
    for i in range(160):
        out += ["K 1 %s" % vec(*(rnd.choice(vals) for _ in range(4))),
                "M 1 %s" % vec(*(rnd.choice(vals) for _ in range(16)))]
        if i % 4 == 0:
            out.append("R %s" % vec(*(rnd.choice(vals) for _ in range(4))))
        if i % 5 == 0:
            out.append("H %s" % vec(*(rnd.choice(vals) for _ in range(4))))
        out.append("U o2")
    # Two bodies a search over 20000 such frames found (2 in about 1500),
    # where eRotateZ's turn by 0 makes a -0 of the matrix +0: its -sin 0
    # is -0.
    out += ["H 80000000 80000000 80000000 80000000",
            "K 1 3f800000 c0000000 80000000 c0000000",
            "M 1 40000000 00000000 80000000 80000000 3f800000 3f800000 "
            "00000000 00000000 3f800000 00000000 00000000 bf000000 c0000000 "
            "80000000 c0000000 40000000",
            "R 00000000 80000000 00000000 00000000", "U o2",
            "K 1 80000000 80000000 80000000 bf000000",
            "M 1 3f800000 80000000 80000000 3f800000 80000000 00000000 "
            "00000000 bf800000 00000000 bf000000 00000000 40000000 bf800000 "
            "80000000 bf000000 40000000",
            "R c0000000 40000000 80000000 80000000", "U o2"]
    out += ["D o2"]
    return out


def s_axes(rnd):
    """The car square to the world's axes and turned by quarter turns
    about each, at the origin and away, where the turns' sines and
    cosines are exactly 0 and 1 and the signs of the zeros show."""
    out = cams(4) + ["O 1 3 2"]
    for pos in ((0.0, 0.0, 0.0), (-0.0, -0.0, -0.0), (10.0, -20.0, 3.0)):
        for rows in (((1, 0, 0), (0, 1, 0), (0, 0, 1)),
                     ((0, 1, 0), (-1, 0, 0), (0, 0, 1)),
                     ((-1, 0, 0), (0, -1, 0), (0, 0, 1)),
                     ((1, 0, 0), (0, 0, 1), (0, -1, 0)),
                     ((0, 0, -1), (0, 1, 0), (1, 0, 0))):
            words = []
            for r in rows:
                words += [float(x) for x in r] + [0.0]
            words += [0.0, 0.0, 0.0, 1.0]
            out += ["K 2 %s" % vec(pos[0], pos[1], pos[2], 1.0),
                    "M 2 %s" % vec(*words)]
            for off in ((0.0, 0.5, 0.0, 0.0), (-0.0, -0.0, -0.0, -0.0)):
                out += ["R %s" % vec(*off), "U o1"]
    out += ["D o1"]
    return out


def s_player(rnd):
    """SetRearViewMirrorCameraMover: a player with no mirror view; on and
    off and on again; with its mover on the view and another's ahead of
    it, or behind it; with its mover on another view, so the view's first
    goes too; the bit as the HUD passes it; and the new mover updated."""
    out = cams(4)
    for i in range(NCAR):
        out += [gpos_line(rnd, i), body_line(rnd, i)]
    out += [offset_line(rnd), shake_line(rnd)]
    # No mirror view: nothing happens, even to a mover it holds.
    out += ["O 0 3 0", "P 0 0 0 o0", "S 0 1", "S 0 0", "D o0"]
    # On, off, on, on: each time the last one goes.
    out += ["P 0 3 1 -", "S 0 1", "U a0", "S 0 0", "S 0 1", "S 0 40",
            "U a2", "G a2", "S 0 0", "S 0 0"]
    # Its mover on the view, another's ahead of it.
    out += ["O 0 3 2", "P 1 3 0 o0", "O 1 3 1", "S 1 1", "U a3"]
    # Its mover the other way round in the list.
    out += ["S 1 0", "O 1 3 1", "O 0 3 2", "P 1 3 0 o0", "S 1 80000000",
            "U a4"]
    # Its mover on another view, the mirror's view with one of its own.
    out += ["S 1 0", "O 0 1 2", "O 1 3 1", "P 1 3 2 o0", "S 1 0"]
    # Another player's mirror view, and no car (so no Update).
    out += ["O 2 2 0", "P 0 2 -1 -", "S 0 1", "G a5", "Z 1", "S 0 1",
            "Z 0", "G a6", "S 0 0"]
    return out


def script():
    rnd = random.Random(0x7e3a9c15)
    sc = [s_ctor(rnd), s_axes(rnd), s_player(rnd), s_zeros(rnd)]
    for n in (40, 120, 200):
        sc.append(s_update(rnd, n))
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
        e.stub(VEC_DELETE, self.s_free)
        e.stub(DELETE, self.s_free)
        e.stub(BMALLOC, self.s_malloc)
        e.stub(SHAKE, self.s_shake)
        e.call(EMATH_SINIT)
        e.call(CAM_SINIT, limit=200000)
        assert e.u32(RVM_VTBL + SLOTS["update"]) == RVM_UPDATE
        self.names = {0: "null", BASE_VTBL: "base", RVM_VTBL: "rvm"}
        for k in range(NCAM):
            c = cam_at(k)
            self.names[c] = "c%d" % k
            self.names[c + 96] = "c%d.tgt" % k
        for j in range(NMOV):
            self.names[mov_at(j)] = "o%d" % j
        for i in range(NARENA):
            self.names[arena_at(i)] = "a%d" % i
        for i in range(NCAR):
            self.names[car_at(i)] = "k%d" % i
        for i in range(NVIEWS):
            self.names[view_at(i)] = "v%d" % i
            self.names[view_at(i) + V_LIST] = "v%d.list" % i
        self.emit("offset %s" % self.vec4(RVM_OFFSET))

    def emit(self, s):
        self.out.append(s)

    def name(self, a):
        return self.names.get(a & M32, "?%08x" % (a & M32))

    def cstr(self, a):
        s = bytearray()
        while True:
            b = self.e.u8(a + len(s))
            if b == 0:
                return s.decode("latin-1")
            s.append(b)

    # ---- the stand-ins -------------------------------------------------

    def s_free(self, em):
        self.emit("  free %s" % self.name(em.reg[4] & M32))

    def s_malloc(self, em):
        if self.arena >= NARENA:
            raise SystemExit("arena full")
        a = arena_at(self.arena)
        self.arena += 1
        self.fill(a, MOV_STRIDE)
        self.emit("  malloc %s %d %d -> %s"
                  % (self.cstr(em.reg[5] & M32), s32(em.reg[6]),
                     s32(em.reg[7]), self.name(a)))
        em.reg[2] = a

    def s_shake(self, em):
        m = em.reg[5] & M32
        self.emit("  shake view %d" % s32(em.reg[4]))
        self.emit("    " + " ".join(fx(self.w(m + 4 * i)) for i in range(16)))
        with np.errstate(all="ignore"):
            for i in range(3):
                a = m + 48 + 4 * i
                self.e.put32(a, f_bits(bits_f(self.w(a))
                                       + bits_f(self.shake[i])))

    # ---- the memory ----------------------------------------------------

    def fill(self, a, n):
        self.e.write(a, bytes([PATTERN]) * n)

    def w(self, a):
        return self.e.u32(a)

    def put_words(self, a, t):
        for i, x in enumerate(t):
            self.e.put32(a + 4 * i, int(x, 16))

    def reset(self):
        e = self.e
        self.fill(CAMS, CAM_SIZE * NCAM)
        self.fill(MOVS, MOV_STRIDE * NMOV)
        self.fill(ARENA, MOV_STRIDE * NARENA)
        self.fill(CARS, CAR_STRIDE * NCAR)
        self.arena = 0
        for i in range(NPLAYER):
            p = player_at(i)
            self.fill(p, PLAYER_STRIDE)
            e.put32(p + P_CAR, 0)
            e.put32(p + P_VIEW, 0)
            e.put32(p + P_RVM, 0)
        for i in range(NVIEWS):
            v = view_at(i)
            e.put32(v + V_CAMERA, 0)
            e.put32(v + V_LIST, v + V_LIST)
            e.put32(v + V_LIST + 4, v + V_LIST)
        e.put32(G_STOP, 0)
        e.put32(G_RTE, fb(1.0 / 30.0))
        for k, x in enumerate((0.0, 0.5, 0.0, 0.0)):
            e.put32(RVM_OFFSET + 4 * k, fb(x))
        self.shake = [0, 0, 0, 0]

    # ---- the dumps -------------------------------------------------------

    def vec4(self, a):
        return " ".join(fx(self.w(a + 4 * i)) for i in range(4))

    def dump_key(self, tag, a):
        w = self.w
        self.emit("    %s m %s" % (tag, " ".join(fx(w(a + 4 * i))
                                                  for i in range(16))))
        self.emit("    %s p %s d %s t %s" % (tag, self.vec4(a + 64),
                                             self.vec4(a + 80),
                                             self.vec4(a + 96)))
        self.emit("    %s s %s fov %04x" % (
            tag, " ".join(fx(w(a + 112 + 4 * i)) for i in range(5)),
            self.e.u16(a + 132)))

    def dump_cam(self, c):
        w = self.w
        self.emit("  %s" % self.name(c))
        self.dump_key("cur", c)
        self.dump_key("prev", c + 144)
        self.dump_key("vel", c + 288)
        self.emit("    clear %08x elapsed %s last %08x carnot %s dash %08x"
                  % (w(c + 432), fx(w(c + 436)), w(c + 440),
                     self.name(w(c + 444)), w(c + 448)))

    def dump_mov(self, m):
        w = self.w
        self.emit("  %s type %d view %d en %d pview %s pcam %s player %08x"
                  " carnot %s dash %08x vtbl %s next %s prev %s car %s"
                  % (self.name(m), s32(w(m + 8)), s32(w(m + 12)),
                     s32(w(m + 16)), self.name(w(m + 20)),
                     self.name(w(m + 24)), w(m + 28), self.name(w(m + 32)),
                     w(m + 36), self.name(w(m + 40)), self.name(w(m)),
                     self.name(w(m + 4)), self.name(w(m + 44))))

    def dump_views(self):
        parts = []
        for i in range(NVIEWS):
            head = view_at(i) + V_LIST
            n, names = self.w(head), []
            while n != head and len(names) < 20:
                names.append(self.name(n))
                n = self.w(n)
            if names:
                parts.append("v%d:%s" % (i, ",".join(names)))
        self.emit("  views %s" % (" ".join(parts) or "-"))

    def dump_player(self, i):
        p = player_at(i)
        self.emit("  p%d view %d car %s rvm %s"
                  % (i, s32(self.w(p + P_VIEW)), self.name(self.w(p + P_CAR)),
                     self.name(self.w(p + P_RVM))))

    # ---- the ops ---------------------------------------------------------

    def mov_of(self, s):
        if s == "-":
            return 0
        if s[0] == "o":
            return mov_at(int(s[1:]))
        if s[0] == "a":
            return arena_at(int(s[1:]))
        raise SystemExit("bad mover %r" % s)

    def vcall(self, m, slot, *args):
        e = self.e
        vt = self.w(m + 40)
        delta = struct.unpack("<h", struct.pack("<H", e.u16(vt + slot - 4)))[0]
        fn = self.w(vt + slot)
        return e.call(fn, (m + delta) & M32, *args, limit=4000000)

    def query(self, m):
        e = self.e
        info = self.vcall(m, SLOTS["info"]) & M32
        pov0 = self.vcall(m, SLOTS["pov"], 0) & M32
        ext = self.vcall(m, SLOTS["ext"])
        lb = self.vcall(m, SLOTS["lookback"])
        self.vcall(m, SLOTS["gap"])
        gap = e.fpr[0]
        car = self.vcall(m, SLOTS["car"]) & M32
        tgt = self.vcall(m, SLOTS["target"]) & M32
        self.emit("  q %s info %s pov %s ext %d lb %d gap %s car %s tgt %s"
                  % (self.name(m), self.name(info), self.name(pov0), ext, lb,
                     fx(gap), self.name(car), self.name(tgt)))

    def op(self, t):
        e = self.e
        c = t[0]
        if c == "C":
            k = int(t[1])
            self.fill(cam_at(k), CAM_SIZE)
            e.call(CAM_CTOR, cam_at(k), limit=200000)
            self.dump_cam(cam_at(k))
        elif c == "Y":
            k = int(t[1])
            e.put32(cam_at(k) + 444, car_at(int(t[2])))
            e.put32(cam_at(k) + 448, int(t[3]))
            e.write(cam_at(k) + 132, struct.pack("<H", int(t[4], 16)))
        elif c == "L":
            k = int(t[1])
            e.put32(cam_at(k) + 124, int(t[2], 16))
            e.put32(cam_at(k) + 128, int(t[3], 16))
        elif c == "V":
            e.put32(view_at(int(t[1])) + V_CAMERA, cam_at(int(t[2])))
        elif c == "Z":
            e.put32(G_STOP, int(t[1]))
        elif c == "T":
            e.put32(G_RTE, int(t[1], 16))
        elif c == "R":
            self.put_words(RVM_OFFSET, t[1:5])
        elif c == "H":
            self.shake = [int(x, 16) for x in t[1:5]]
        elif c == "K":
            self.put_words(car_at(int(t[1])) + C_GPOS, t[2:6])
        elif c == "M":
            self.put_words(car_at(int(t[1])) + C_BODY, t[2:18])
        elif c == "O":
            j, view, car = (int(x) for x in t[1:4])
            m = mov_at(j)
            self.fill(m, MOV_STRIDE)
            r = e.call(RVM_CTOR, m, view, car_at(car), limit=2000000)
            self.emit("  -> %s" % self.name(r))
            self.dump_mov(m)
            self.dump_views()
            self.dump_cam(self.w(m + 24))
        elif c == "D":
            m = self.mov_of(t[1])
            cam = self.w(m + 24)
            self.vcall(m, SLOTS["destroy"], 0)
            self.dump_mov(m)
            self.dump_views()
            self.dump_cam(cam)
        elif c == "U":
            m = self.mov_of(t[1])
            self.vcall(m, SLOTS["update"])
            self.dump_mov(m)
            self.dump_cam(self.w(m + 24))
        elif c == "G":
            self.query(self.mov_of(t[1]))
        elif c == "P":
            p = player_at(int(t[1]))
            e.put32(p + P_VIEW, int(t[2]))
            e.put32(p + P_CAR, car_at(int(t[3])))
            e.put32(p + P_RVM, self.mov_of(t[4]))
        elif c == "S":
            i = int(t[1])
            p = player_at(i)
            e.call(SET_RVM, p, int(t[2], 16), limit=4000000)
            self.dump_player(i)
            self.dump_views()
            m = self.w(p + P_RVM)
            if m:
                self.dump_mov(m)
                self.dump_cam(self.w(m + 24))
        else:
            raise SystemExit("bad op %r" % (t,))

    def run(self, scenarios):
        for i, sc in enumerate(scenarios):
            self.emit("B %d" % i)
            self.reset()
            for ln in sc:
                if ln[0] not in "KM":
                    self.emit("> " + ln[:40])
                self.op(ln.split())
        return self.out


# ================================================================ the build


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


def build_harness(tmp, name="rvmcam_test"):
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


def M(name, before, after, rel=RVM):
    return (name, rel, before, after)


MUTATIONS = [
    # The offset and the vtable.
    M("off-y", "bVector3 RVMOffsetInCar = { 0.0f, 0.5f, 0.0f, 0.0f };",
      "bVector3 RVMOffsetInCar = { 0.0f, 0.25f, 0.0f, 0.0f };"),
    M("off-x", "bVector3 RVMOffsetInCar = { 0.0f, 0.5f, 0.0f, 0.0f };",
      "bVector3 RVMOffsetInCar = { 0.5f, 0.5f, 0.0f, 0.0f };"),
    M("vt-car", "return ((RearViewMirrorCameraMover *)m)->pCar;",
      "return NULL;"),
    M("vt-update", "    rvm_update_thunk," + NL,
      "    camera_mover_nothing," + NL),
    M("vt-destroy", "    rvm_destroy_thunk," + NL,
      "    camera_mover_destroy," + NL),

    # The constructor.
    M("ctor-type", "camera_mover_init(&m->base, viewID, CM_REAR_VIEW_MIRROR);",
      "camera_mover_init(&m->base, viewID, CM_BUMPER);"),
    M("ctor-vtbl", "    m->base.vtbl = &RearViewMirrorCameraMoverVtbl;" + NL
      + "    m->pCar = car;", "    m->pCar = car;"),
    M("ctor-car", "    m->pCar = car;", "    m->pCar = NULL;"),
    M("ctor-carnot", "        cam->CarNotToRender = car;",
      "        cam->CarNotToRender = NULL;"),
    M("ctor-carnot-frozen", "    if (!CameraStopUpdating)" + NL
      + "        cam->CarNotToRender = car;", "    cam->CarNotToRender = car;"),
    M("ctor-dash", "        cam->RenderDash = 0;", "        cam->RenderDash = 1;"),
    M("ctor-dash-frozen", "    if (!CameraStopUpdating)" + NL
      + "        cam->RenderDash = 0;", "    cam->RenderDash = 0;"),
    M("ctor-dash-lost", "    if (!CameraStopUpdating)" + NL
      + "        cam->RenderDash = 0;" + NL, ""),
    M("ctor-ret", "        cam->RenderDash = 0;" + NL + "    return m;",
      "        cam->RenderDash = 0;" + NL + "    return NULL;"),

    # The destructor.
    M("dtor-base", "    camera_mover_destroy(&m->base);" + NL + "}", "}"),

    # Update.
    M("up-gpos-x", "toCar.v3.x = -car->State.GeometryPosition.x;",
      "toCar.v3.x = car->State.GeometryPosition.x;"),
    M("up-gpos-y", "toCar.v3.y = -car->State.GeometryPosition.y;",
      "toCar.v3.y = -car->State.GeometryPosition.x;"),
    M("up-gpos-z", "toCar.v3.z = -car->State.GeometryPosition.z;",
      "toCar.v3.z = -car->State.GeometryPosition.y;"),
    M("up-gpos-w", "toCar.v3.z = -car->State.GeometryPosition.z;",
      "toCar.v3.z = -car->State.GeometryPosition.z;"
      + " toCar.v3.w = -car->State.GeometryPosition.pad;"),
    M("up-transpose", "eTransposeMatrix(&body, &car->State.BodyMatrix);",
      "body = car->State.BodyMatrix;"),
    M("up-rotx", "eRotateX(&body, &body, RVM_QUARTER);",
      "eRotateX(&body, &body, (uint16_t)-RVM_QUARTER);"),
    M("up-roty", "eRotateY(&body, &body, RVM_QUARTER);",
      "eRotateY(&body, &body, (uint16_t)-RVM_QUARTER);"),
    M("up-rotz", "    eRotateZ(&body, &body, 0);" + NL, ""),
    M("up-rot-order", "    eRotateX(&body, &body, RVM_QUARTER);" + NL
      + "    eRotateY(&body, &body, RVM_QUARTER);",
      "    eRotateY(&body, &body, RVM_QUARTER);" + NL
      + "    eRotateX(&body, &body, RVM_QUARTER);"),
    M("up-mul-order", "eMulMatrix(&mat, &toCar, &body);",
      "eMulMatrix(&mat, &body, &toCar);"),
    M("up-off-x", "mat.v3.x = mat.v3.x + RVMOffsetInCar.x;",
      "mat.v3.x = mat.v3.x - RVMOffsetInCar.x;"),
    M("up-off-y", "mat.v3.y = mat.v3.y + RVMOffsetInCar.y;",
      "mat.v3.y = mat.v3.y + RVMOffsetInCar.x;"),
    M("up-off-z", "mat.v3.z = mat.v3.z + RVMOffsetInCar.z;",
      "mat.v3.z = RVMOffsetInCar.z + mat.v3.y;"),
    M("up-off-w", "mat.v3.z = mat.v3.z + RVMOffsetInCar.z;",
      "mat.v3.z = mat.v3.z + RVMOffsetInCar.z;"
      + " mat.v3.w = mat.v3.w + RVMOffsetInCar.pad;"),
    M("up-fov", "#define RVM_FOV   20000", "#define RVM_FOV   20001"),
    M("up-fov-frozen", "    if (!CameraStopUpdating)" + NL
      + "        cam->CurrentKey.FieldOfView = RVM_FOV;",
      "    cam->CurrentKey.FieldOfView = RVM_FOV;"),
    M("up-far", "#define RVM_FAR_Z 192.0f", "#define RVM_FAR_Z 191.0f"),
    M("up-near", "#define RVM_NEAR_Z 0.75f", "#define RVM_NEAR_Z 0.5f"),
    M("up-near-frozen", "    cam->CurrentKey.NearZ = RVM_NEAR_Z;",
      "    if (!CameraStopUpdating)" + NL
      + "        cam->CurrentKey.NearZ = RVM_NEAR_Z;"),
    M("up-far-lost", "    cam->CurrentKey.FarZ = RVM_FAR_Z;" + NL, ""),
    M("up-shake-view", "apply_camera_shake(m->base.ViewID, &mat);",
      "apply_camera_shake(3, &mat);"),
    M("up-shake-lost", "    apply_camera_shake(m->base.ViewID, &mat);" + NL,
      ""),
    M("up-clock", "camera_set_matrix(m->base.pCamera, &mat, RealTimeElapsed);",
      "camera_set_matrix(m->base.pCamera, &mat, 1.0f / 30.0f);"),

    # SetRearViewMirrorCameraMover.
    M("pl-noview", "    if (p->RearViewMirrorViewID == 0)" + NL
      + "        return;" + NL, ""),
    M("pl-own", "        delete_mover(p->pRVMCameraMover);" + NL, ""),
    M("pl-keep", "        p->pRVMCameraMover = NULL;" + NL + "    }" + NL
      + "    view", "    }" + NL + "    view"),
    M("pl-first", "        delete_mover((CameraMover *)n);" + NL, ""),
    M("pl-first-head", "if (n != &view->CameraMoverList && n != NULL)",
      "if (n != NULL)"),
    M("pl-getview", "view = eGetView(p->RearViewMirrorViewID);",
      "view = eGetView(EVIEW_ID_PLAYER1_RVM);"),
    M("pl-on", "    if (on) {", "    if (on & 1) {"),
    M("pl-on-not", "    if (on) {", "    if (1) {"),
    M("pl-name", "\"RearViewMirrorCameraMover\", 0, 16);",
      "\"RVMCameraMover\", 0, 16);"),
    M("pl-pool", "\"RearViewMirrorCameraMover\", 0, 16);",
      "\"RearViewMirrorCameraMover\", 0, 0);"),
    M("pl-flags", "\"RearViewMirrorCameraMover\", 0, 16);",
      "\"RearViewMirrorCameraMover\", 1, 16);"),
    M("pl-ctor-view", "(RearViewMirrorCameraMover *)mem, p->RearViewMirrorViewID,",
      "(RearViewMirrorCameraMover *)mem, EVIEW_ID_PLAYER1_RVM,"),
    M("pl-car", "            p->MyCar)->base;", "            NULL)->base;"),
    M("pl-store", "        p->pRVMCameraMover = &rvm_camera_mover_init(",
      "        (void)&rvm_camera_mover_init("),
]

EQUIVALENT = {
    "vt-destroy": "the destructor's own vtable store is the base "
                  "destructor's first store's to overwrite",
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    base = model_cached(sc)
    scdir = tempfile.TemporaryDirectory()
    scp = Path(scdir.name) / "scenarios.txt"
    scp.write_text(encode(sc))
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text().splitlines()
        if diff(base, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "rvmcam_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs)
    scdir.cleanup()
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

    sc = script()
    lines = model_cached(sc)
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
