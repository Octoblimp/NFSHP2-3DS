#!/usr/bin/env python3
"""Cross-check 3DS Files/source/camera.c and the base of cammover.c against
the retail image itself, run in mipsemu.

The model is the image. Retail's Camera constructor (0x00156be0), its copy
constructor (0x00156cd0) and SetCameraMatrix (0x00156d68) run as shipped,
with the matrix layer under them. So do CameraMover's constructor
(0x001576e8), destructor (0x00157780), Enable (0x001577d8), Disable
(0x00157850), every slot of its vtable (0x002b1e50), the accessors,
GetCameraMoverTypeName (0x00157578), UpdateCameraMovers (0x0015ef28) and
RenderCameraMovers (0x0015eee0), over retail's own eView table with
eView::AttachCameraMover and eUpdateViewMode. The harness
(tools/src/cambase_test.c) runs the port over the same script, and the
two transcripts are diffed.

Only bFunkDoesServerExist is a stub: it answers 0, as no debug server does
for the shipped game. A second vtable, the base's with Update, Render,
Enable and Disable pointed at stubs that print their arguments and do
nothing else, stands in for a derived mover. The update and render loops
show which mover each one reached, and a destructor that went through the
vtable for Disable, where retail calls it directly, shows too.

Every camera and mover starts from a byte pattern, so what a call leaves
alone shows. A float prints as its bits, a NaN as "nan", and a pointer by
what it is: a camera or one of its keys' vectors, a mover, a view or its
list's head.

    python tools/cambase_check.py
    python tools/cambase_check.py --mutate [--only a,b]
    python tools/cambase_check.py --dump out/cambase
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

HARNESS = "tools/src/cambase_test.c"
CAMC = "3DS Files/source/camera.c"
MOVC = "3DS Files/source/cammover.c"
SOURCES = [HARNESS, CAMC, MOVC] + ["3DS Files/source/" + f for f in (
    "eview.c", "emath.c", "bmatrix.c", "bmath.c", "bmathtab.c",
    "bvector.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
CAM_CTOR = 0x00156be0
CAM_COPY = 0x00156cd0
CAM_SET = 0x00156d68
MOV_CTOR = 0x001576e8
MOV_DTOR = 0x00157780
MOV_ENABLE = 0x001577d8
MOV_DISABLE = 0x00157850
TYPE_NAME = 0x00157578
UPDATE_MOVERS = 0x0015ef28
RENDER_MOVERS = 0x0015eee0
GET_POSITION = 0x0015fcd0
GET_DIRECTION = 0x0015fcc0
SET_PLAYER = 0x0015fca0
FUNK_EXISTS = 0x0025d220
EMATH_SINIT = 0x0011bf70          # writes eMulVector's (0, 0, 0, 1)
BASE_VTBL = 0x002b1e50
VIEWS = 0x002c95b0                # eGetView: 0x002d0000 - 27216 + 128 * id
VIEW_STRIDE = 128
NVIEWS = 10
V_CAMERA = 56
V_LIST = 60
JOLLY = 0x002fa860                # the JollyRancher feed; NULL when shipped

G_STOP = GP - 21808               # Camera::StopUpdating
G_VIEWMODE = GP - 24888           # CurrentViewMode

CAM_SIZE = 464
MOV_SIZE = 44
CAMS = 0x01000000
NCAM = 12
MOVS = 0x01010000
MOV_STRIDE = 64
NMOV = 10
TEST_VTBL = 0x01020000
MATRIX = 0x01021000
STUB_UPDATE = 0x01022000
STUB_RENDER = 0x01022008
STUB_ENABLE = 0x01022010
STUB_DISABLE = 0x01022018

PATTERN = 0xa5
NAN_BITS = None

# The vtable's slots, by the function's offset.
SLOTS = {
    "destroy": 12, "update": 20, "render": 28, "addjoy": 36, "remjoy": 44,
    "info": 52, "pov": 60, "ext": 68, "lookback": 76, "gap": 84,
    "reset": 92, "enable": 100, "disable": 108, "car": 116, "target": 124,
}

# The camera's scalars a script can set, by retail's offset. `h` is a
# halfword; the rest are words.
CAM_FIELDS = {
    "clear": 432, "elapsed": 436, "last": 440, "carnot": 444, "dash": 448,
    "td": 112, "fd": 116, "dof": 120, "near": 124, "far": 128, "fov": 132,
}


def fb(v):
    if isinstance(v, int):
        return v & M32
    return f_to_bits(v)


def fbits(w):
    return struct.unpack("<f", struct.pack("<I", w & M32))[0]


def fx(w):
    """A float's bits, with every NaN the one "nan"."""
    w &= M32
    if (w & 0x7f800000) == 0x7f800000 and (w & 0x7fffff):
        return "nan"
    return "%08x" % w


def cam_at(k):
    return CAMS + CAM_SIZE * k


def mov_at(j):
    return MOVS + MOV_STRIDE * j


def view_at(i):
    return VIEWS + VIEW_STRIDE * i


# ============================================================ the scenarios


def rmatrix(rnd):
    """A view matrix: a rotation by three random angles, with a random
    translation row -- and now and then a stray fourth column, a scaled
    third, or a zero one."""
    a, b, c = (rnd.uniform(-math.pi, math.pi) for _ in range(3))
    ca, sa, cb, sb, cc, sc = (math.cos(a), math.sin(a), math.cos(b),
                              math.sin(b), math.cos(c), math.sin(c))
    rot = [[cb * cc, cb * sc, -sb],
           [sa * sb * cc - ca * sc, sa * sb * sc + ca * cc, sa * cb],
           [ca * sb * cc + sa * sc, ca * sb * sc - sa * cc, ca * cb]]
    m = []
    for r in range(3):
        m += [rot[r][0], rot[r][1], rot[r][2], 0.0]
    m += [rnd.uniform(-500, 500), rnd.uniform(-500, 500),
          rnd.uniform(-50, 50), 1.0]
    k = rnd.random()
    if k < 0.1:
        for r in range(3):
            m[4 * r + 3] = rnd.uniform(-100, 100)
    elif k < 0.2:
        s = rnd.uniform(0.1, 10)
        for r in range(3):
            m[4 * r + 2] *= s
    elif k < 0.23:
        for r in range(3):
            m[4 * r + 2] = 0.0
    elif k < 0.26:
        m[12] = -0.0
        m[13] = -0.0
        m[14] = -0.0
    return [fb(x) for x in m]


ELAPSED = (1.0 / 60, 1.0 / 30, 0.5, 2.0, 1e-3, -0.25, 1.0, 37.5)


def s_camera(rnd):
    out = []
    for k in range(3):
        out.append("C %d" % k)
    for i in range(12):
        out.append("S 0 %08x %s" % (fb(rnd.choice(ELAPSED)),
                                    " ".join("%08x" % w for w in rmatrix(rnd))))
    # Scalars moved between frames, then the clear, then the frame after.
    for name, v in (("td", fb(25.0)), ("fd", fb(7.5)), ("dof", fb(3.25)),
                    ("near", fb(0.125)), ("far", fb(9000.0)), ("fov", 200)):
        out.append("F 1 %s %08x" % (name, v))
    for i in range(6):
        if i in (1, 4):
            out.append("F 1 clear 00000001")
        if i == 3:
            out.append("F 1 clear 00000007")
        out.append("S 1 %08x %s" % (fb(rnd.choice(ELAPSED)),
                                    " ".join("%08x" % w for w in rmatrix(rnd))))
    # Frozen: nothing moves, the clear included.
    out.append("F 2 clear 00000001")
    out.append("Z 1")
    out.append("S 2 %08x %s" % (fb(0.5), " ".join(
        "%08x" % w for w in rmatrix(rnd))))
    out.append("Z 0")
    out.append("S 2 %08x %s" % (fb(0.5), " ".join(
        "%08x" % w for w in rmatrix(rnd))))
    # Built while frozen: SetCameraMatrix does nothing, so what the
    # constructor stores itself is all there is.
    out.append("Z 1")
    out.append("C 6")
    out.append("Z 0")
    out.append("S 6 %08x %s" % (fb(0.5), " ".join(
        "%08x" % w for w in rmatrix(rnd))))
    # The copy constructor, from a source holding everything.
    for name, v in (("clear", 1), ("elapsed", fb(0.75)),
                    ("last", 0x12345678), ("carnot", 0x0badf00d),
                    ("dash", 0xffffffff)):
        out.append("F 1 %s %08x" % (name, v))
    out.append("P 3 1")
    out.append("P 4 0")
    return out


def s_names():
    return ["K %d" % t for t in range(-3, 21)] + ["K %d" % -0x7fffffff,
                                                  "K %d" % 0x7fffffff]


def s_movers(rnd, n_ops):
    """A random walk over ten movers on the ten views."""
    out = []
    for k in range(NVIEWS):
        out.append("C %d" % k)
        out.append("F %d carnot %08x" % (k, rnd.getrandbits(32)))
        out.append("F %d dash %08x" % (k, rnd.choice((0, 1, 5, 0xffffffff))))
        out.append("V %d %d" % (k, k))
    live = {}                     # mover -> its view, or -1
    for step in range(n_ops):
        r = rnd.random()
        j = rnd.randrange(NMOV)
        if r < 0.22 or j not in live:
            # A live mover is destroyed before it is built again, as the
            # game does; building over one still on a list would tie two
            # lists together.
            if j in live:
                out.append("D %d" % j)
            view = rnd.choice(list(range(NVIEWS)) + [-1, -1, 1, 1, 2, 3])
            t = rnd.choice((0, 1, 4, 5, 6, 12, 17, 18, -1))
            out.append("N %d %d %d" % (j, view, t))
            live[j] = view
        elif r < 0.34 and live[j] != -1:
            out.append("E %d" % j)
        elif r < 0.46:
            out.append("X %d" % j)
        elif r < 0.52 and live[j] != -1:
            out.append("v %d enable" % j)
        elif r < 0.58:
            out.append("v %d disable" % j)
        elif r < 0.63:
            out.append("D %d" % j)
        elif r < 0.66:
            out.append("v %d destroy" % j)
        elif r < 0.72 and live[j] != -1:
            out.append("Q %d" % j)
        elif r < 0.76:
            out.append("T %d %d" % (j, rnd.randrange(2)))
        elif r < 0.84:
            out.append("U")
        elif r < 0.9:
            out.append("R %d" % rnd.randrange(NVIEWS))
        elif r < 0.93:
            out.append("L %d %08x" % (j, rnd.getrandbits(32)))
        elif r < 0.96:
            out.append("Z %d" % rnd.randrange(2))
        elif live[j] != -1:
            f = rnd.choice(("carnot", "dash", "near", "far"))
            v = rnd.getrandbits(32) if f in ("carnot", "dash") else \
                fb(rnd.choice((0.25, 1.0, 3.0, 2500.0)))
            out.append("F %d %s %08x" % (rnd.randrange(NVIEWS), f, v))
            for v in ("update", "render", "addjoy", "remjoy", "reset"):
                out.append("v %d %s" % (j, v))
    out.append("Z 0")
    return out


def s_nocam(rnd):
    """The no-op virtuals and the queries on a detached mover, which reads
    no camera, and the queries a mover with a camera answers."""
    out = ["C 5", "V 5 5", "N 0 -1 1", "Q0 0", "N 1 5 4", "Q 1"]
    for v in ("update", "render", "addjoy", "remjoy", "reset", "disable",
              "destroy"):
        out.append("v 0 %s" % v)
    out.append("X 0")
    out.append("D 0")
    # Enable while frozen leaves the camera's two flags alone but still sets
    # its near plane; unfrozen, the mover's flags go back onto the camera.
    out += ["C 7", "V 7 7", "F 7 carnot 11111111", "F 7 dash 00000002",
            "N 2 7 1", "X 2", "F 7 carnot 22222222", "F 7 dash 00000003",
            "F 7 near 40400000", "Z 1", "E 2", "Z 0", "X 2",
            "F 7 near 40400000", "E 2", "D 2"]
    return out


def script():
    rnd = random.Random(0x7cab5e01)
    sc = [s_camera(rnd), s_names(), s_nocam(rnd)]
    for n in (40, 120, 400, 400):
        sc.append(s_movers(rnd, n))
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
        e.stub(FUNK_EXISTS, lambda em: 0)
        e.stub(STUB_UPDATE, self.rec_update)
        e.stub(STUB_RENDER, self.rec_render)
        e.stub(STUB_ENABLE, lambda em: self.emit(
            "  enable %s" % self.name(self.arg(0))))
        e.stub(STUB_DISABLE, lambda em: self.emit(
            "  disable %s" % self.name(self.arg(0))))
        e.put32(JOLLY, 0)
        # The emulator runs no static constructors, and eMulVector (under
        # the camera's Position) adds its vector into the (0, 0, 0, 1) at
        # 0x002dc400 that the one at 0x0011bf70 writes. So that one runs.
        e.call(EMATH_SINIT)
        # The test vtable: the base's, with Update and Render recorded.
        for off in range(0, 132, 4):
            e.put32(TEST_VTBL + off, e.u32(BASE_VTBL + off))
        e.put32(TEST_VTBL + SLOTS["update"], STUB_UPDATE)
        e.put32(TEST_VTBL + SLOTS["render"], STUB_RENDER)
        e.put32(TEST_VTBL + SLOTS["enable"], STUB_ENABLE)
        e.put32(TEST_VTBL + SLOTS["disable"], STUB_DISABLE)
        self.names = {0: "null", BASE_VTBL: "base", TEST_VTBL: "test"}
        for k in range(NCAM):
            c = cam_at(k)
            self.names[c] = "c%d" % k
            self.names[c + 64] = "c%d.pos" % k
            self.names[c + 80] = "c%d.dir" % k
            self.names[c + 96] = "c%d.tgt" % k
        for j in range(NMOV):
            self.names[mov_at(j)] = "m%d" % j
        for i in range(NVIEWS):
            self.names[view_at(i)] = "v%d" % i
            self.names[view_at(i) + V_LIST] = "v%d.list" % i

    def emit(self, s):
        self.out.append(s)

    def name(self, a):
        return self.names.get(a & M32, "?%08x" % (a & M32))

    def arg(self, i):
        return self.e.reg[(4, 5, 6, 7)[i]] & M32

    def rec_update(self, em):
        self.emit("  update %s" % self.name(self.arg(0)))

    def rec_render(self, em):
        self.emit("  render %s %s" % (self.name(self.arg(0)),
                                      self.name(self.arg(1))))

    def fill(self, a, n):
        self.e.write(a, bytes([PATTERN]) * n)

    def w(self, a):
        return self.e.u32(a)

    def reset(self):
        """Every scenario starts over: views empty, cameras patterned."""
        e = self.e
        self.fill(CAMS, CAM_SIZE * NCAM)
        self.fill(MOVS, MOV_STRIDE * NMOV)
        for i in range(NVIEWS):
            v = view_at(i)
            e.put32(v + V_CAMERA, 0)
            e.put32(v + V_LIST, v + V_LIST)
            e.put32(v + V_LIST + 4, v + V_LIST)
        e.put32(G_STOP, 0)
        e.put32(G_VIEWMODE, 0)

    # ---- the dumps -------------------------------------------------------

    def dump_key(self, tag, a, matrix=True):
        w = self.w
        if matrix:
            self.emit("    %s m %s" % (tag, " ".join(fx(w(a + 4 * i))
                                                      for i in range(16))))
        self.emit("    %s p %s d %s t %s" % (
            tag, " ".join(fx(w(a + 64 + 4 * i)) for i in range(4)),
            " ".join(fx(w(a + 80 + 4 * i)) for i in range(4)),
            " ".join(fx(w(a + 96 + 4 * i)) for i in range(4))))
        self.emit("    %s s %s fov %04x pad %s" % (
            tag, " ".join(fx(w(a + 112 + 4 * i)) for i in range(5)),
            self.e.u16(a + 132),
            "".join("%02x" % self.e.mem[a + 134 + i] for i in range(10))))

    def dump_cam(self, k):
        c = cam_at(k)
        w = self.w
        self.emit("  c%d" % k)
        self.dump_key("cur", c)
        self.dump_key("prev", c + 144)
        self.dump_key("vel", c + 288)
        self.emit("    clear %08x elapsed %s last %08x carnot %08x dash %08x"
                  % (w(c + 432), fx(w(c + 436)), w(c + 440), w(c + 444),
                     w(c + 448)))

    def dump_mov(self, j):
        m = mov_at(j)
        w = self.w
        self.emit("  m%d type %d view %d en %d pview %s pcam %s player %08x"
                  " carnot %08x dash %08x vtbl %s next %s prev %s"
                  % (j, s32(w(m + 8)), s32(w(m + 12)), s32(w(m + 16)),
                     self.name(w(m + 20)), self.name(w(m + 24)), w(m + 28),
                     w(m + 32), w(m + 36), self.name(w(m + 40)),
                     self.name(w(m)), self.name(w(m + 4))))
        c = w(m + 24)
        if c:
            self.emit("    cam %s near %s far %s carnot %08x dash %08x"
                      % (self.name(c), fx(w(c + 124)), fx(w(c + 128)),
                         w(c + 444), w(c + 448)))

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
        self.emit("  views %s mode %d" % (" ".join(parts) or "-",
                                          s32(self.w(G_VIEWMODE))))

    # ---- the ops ---------------------------------------------------------

    def vcall(self, j, slot, *args):
        e = self.e
        m = mov_at(j)
        vt = self.w(m + 40)
        delta = struct.unpack("<h", struct.pack("<H", e.u16(vt + slot - 4)))[0]
        fn = self.w(vt + slot)
        return e.call(fn, (m + delta) & M32, *args, limit=200000)

    def query(self, j):
        e = self.e
        m = mov_at(j)
        info = self.vcall(j, SLOTS["info"])
        pov0 = self.vcall(j, SLOTS["pov"], 0)
        pov3 = self.vcall(j, SLOTS["pov"], 3)
        ext = self.vcall(j, SLOTS["ext"])
        lb = self.vcall(j, SLOTS["lookback"])
        self.vcall(j, SLOTS["gap"])
        gap = e.fpr[0]
        car = self.vcall(j, SLOTS["car"])
        tgt = self.vcall(j, SLOTS["target"])
        pos = e.call(GET_POSITION, m)
        dirn = e.call(GET_DIRECTION, m)
        self.emit("  q m%d info %s pov %s %s ext %d lb %d gap %s car %s"
                  " tgt %s pos %s dir %s"
                  % (j, self.name(info), self.name(pov0), self.name(pov3),
                     ext, lb, fx(gap), self.name(car), self.name(tgt),
                     self.name(pos), self.name(dirn)))

    def query_detached(self, j):
        e = self.e
        info = self.vcall(j, SLOTS["info"])
        pov0 = self.vcall(j, SLOTS["pov"], 0)
        ext = self.vcall(j, SLOTS["ext"])
        lb = self.vcall(j, SLOTS["lookback"])
        self.vcall(j, SLOTS["gap"])
        gap = e.fpr[0]
        car = self.vcall(j, SLOTS["car"])
        self.emit("  q0 m%d info %s pov %s ext %d lb %d gap %s car %s"
                  % (j, self.name(info), self.name(pov0), ext, lb, fx(gap),
                     self.name(car)))

    def op(self, t):
        e = self.e
        c = t[0]
        if c == "B":
            self.reset()
            return
        if c == "C":
            k = int(t[1])
            self.fill(cam_at(k), CAM_SIZE)
            e.call(CAM_CTOR, cam_at(k), limit=200000)
            self.dump_cam(k)
        elif c == "P":
            d, s = int(t[1]), int(t[2])
            self.fill(cam_at(d), CAM_SIZE)
            e.call(CAM_COPY, cam_at(d), cam_at(s), limit=200000)
            self.dump_cam(d)
            self.dump_cam(s)
        elif c == "F":
            k, off, v = int(t[1]), CAM_FIELDS[t[2]], int(t[3], 16)
            if t[2] == "fov":
                e.mem[cam_at(k) + off] = v & 0xff
                e.mem[cam_at(k) + off + 1] = (v >> 8) & 0xff
            else:
                e.put32(cam_at(k) + off, v)
        elif c == "S":
            k, el = int(t[1]), int(t[2], 16)
            for i in range(16):
                e.put32(MATRIX + 4 * i, int(t[3 + i], 16))
            e.fpr[12] = el
            e.call(CAM_SET, cam_at(k), MATRIX, limit=200000)
            self.dump_cam(k)
        elif c == "Z":
            e.put32(G_STOP, int(t[1]))
        elif c == "V":
            e.put32(view_at(int(t[1])) + V_CAMERA, cam_at(int(t[2])))
        elif c == "K":
            a = e.call(TYPE_NAME, int(t[1])) & M32
            s = bytearray()
            while e.mem[a + len(s)]:
                s.append(e.mem[a + len(s)])
            self.emit("  name %d %s" % (int(t[1]), s.decode("latin-1")))
        elif c == "N":
            j, view, ty = int(t[1]), int(t[2]), int(t[3])
            self.fill(mov_at(j), MOV_STRIDE)
            e.call(MOV_CTOR, mov_at(j), view, ty, limit=200000)
            self.dump_mov(j)
            self.dump_views()
        elif c in "EXD":
            j = int(t[1])
            fn = {"E": MOV_ENABLE, "X": MOV_DISABLE, "D": MOV_DTOR}[c]
            e.call(fn, mov_at(j), 0, limit=200000)
            self.dump_mov(j)
            self.dump_views()
        elif c == "v":
            j, slot = int(t[1]), SLOTS[t[2]]
            if t[2] == "render":
                self.vcall(j, slot, view_at(3))
            elif t[2] == "destroy":
                self.vcall(j, slot, 0)
            else:
                self.vcall(j, slot)
            self.dump_mov(j)
            self.dump_views()
        elif c == "Q":
            self.query(int(t[1]))
        elif c == "Q0":
            self.query_detached(int(t[1]))
        elif c == "T":
            e.put32(mov_at(int(t[1])) + 40,
                    TEST_VTBL if int(t[2]) else BASE_VTBL)
        elif c == "U":
            e.call(UPDATE_MOVERS, limit=400000)
            self.emit("  updated")
        elif c == "R":
            e.call(RENDER_MOVERS, view_at(int(t[1])), limit=200000)
            self.emit("  rendered v%d" % int(t[1]))
        elif c == "L":
            e.call(SET_PLAYER, mov_at(int(t[1])), int(t[2], 16))
            self.dump_mov(int(t[1]))
        else:
            raise SystemExit("bad op %r" % (t,))

    def run(self, scenarios):
        for i, sc in enumerate(scenarios):
            self.emit("B %d" % i)
            self.op(["B"])
            for ln in sc:
                self.emit("> " + ln[:40])
                self.op(ln.split())
        return self.out


# ================================================================ the build


def build_harness(tmp, name="cambase_test"):
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
    # camera.c
    M("ctor_far_5000", CAMC, "    c->CurrentKey.FarZ = 10000.0f;",
      "    c->CurrentKey.FarZ = 5000.0f;"),
    M("ctor_clear_1", CAMC, "    c->ClearVelocity = 0;\n    c->CarNotToRender",
      "    c->ClearVelocity = 1;\n    c->CarNotToRender"),
    M("ctor_no_clear", CAMC, "    c->ClearVelocity = 0;\n    c->CarNotToRender",
      "    c->CarNotToRender"),
    M("ctor_last", CAMC, "    c->LastUpdateTime = 0x80000000u;",
      "    c->LastUpdateTime = 0;"),
    M("ctor_elapsed", CAMC, "    c->ElapsedTime = 1.0f;\n",
      "    c->ElapsedTime = 0.5f;\n"),
    M("ctor_fov", CAMC, "    c->CurrentKey.FieldOfView = 14075;",
      "    c->CurrentKey.FieldOfView = 14076;"),
    M("ctor_fourth_col", CAMC, "    m.v2.z = -1.0f;  m.v2.w = 100.0f;",
      "    m.v2.z = -1.0f;  m.v2.w = 0.0f;"),
    M("ctor_one_set", CAMC,
      "    camera_set_matrix(c, &m, 1.0f);\n    camera_set_matrix(c, &m, 1.0f);",
      "    camera_set_matrix(c, &m, 1.0f);"),
    M("copy_clear_kept", CAMC, "    dst->ClearVelocity = 0;",
      "    dst->ClearVelocity = src->ClearVelocity;"),
    M("copy_no_clear", CAMC, "    dst->ClearVelocity = 0;\n", ""),
    M("copy_last", CAMC,
      "    dst->LastUpdateTime = 0x80000000u;\n    dst->ClearVelocity",
      "    dst->LastUpdateTime = src->LastUpdateTime;\n    dst->ClearVelocity"),
    M("copy_dash", CAMC, "    dst->RenderDash = src->RenderDash;", ""),
    M("copy_no_vel", CAMC, "    dst->VelocityKey = src->VelocityKey;", ""),
    M("set_no_freeze", CAMC, "    if (CameraStopUpdating)\n        return;\n",
      ""),
    M("set_clear_ignored", CAMC, "    if (c->ClearVelocity) {", "    if (0) {"),
    M("set_clear_kept", CAMC,
      "        c->ClearVelocity = 0;\n        c->PreviousKey",
      "        c->PreviousKey"),
    M("set_clear_no_copy", CAMC,
      "        c->PreviousKey = c->CurrentKey;\n    }", "    }"),
    M("set_clear_top", CAMC, [
        ("    c->ElapsedTime = elapsed;\n    cur->Matrix = *m;",
         "    c->ElapsedTime = elapsed;\n    if (c->ClearVelocity) {\n"
         "        c->ClearVelocity = 0;\n"
         "        c->PreviousKey = c->CurrentKey;\n    }\n"
         "    cur->Matrix = *m;"),
        ("    if (c->ClearVelocity) {\n        c->ClearVelocity = 0;\n"
         "        c->PreviousKey = c->CurrentKey;\n    }\n\n    // Every",
         "\n    // Every")]),
    M("set_clear_before_target", CAMC, [
        ("    cur->Target.x = cur->Position.x +",
         "    if (c->ClearVelocity) {\n        c->ClearVelocity = 0;\n"
         "        c->PreviousKey = c->CurrentKey;\n    }\n"
         "    cur->Target.x = cur->Position.x +"),
        ("    if (c->ClearVelocity) {\n        c->ClearVelocity = 0;\n"
         "        c->PreviousKey = c->CurrentKey;\n    }\n\n    // Every",
         "\n    // Every")]),
    M("set_pos_negate", CAMC, "    cur->Position.x = 0.0f - cur->Position.x;",
      "    cur->Position.x = -cur->Position.x;"),
    M("set_pos_w", CAMC, "    cur->Position.pad = 1.0f - cur->Position.pad;",
      "    cur->Position.pad = 0.0f - cur->Position.pad;"),
    M("set_col_keep", CAMC, "    t.v1.w = 0.0f;\n", ""),
    M("set_dir_w", CAMC, "    cur->Direction.pad = t.v2.w * k;",
      "    cur->Direction.pad = 0.0f;"),
    M("set_tgt", CAMC,
      "    cur->Target.y = cur->Position.y + cur->Direction.y * cur->TargetDistance;",
      "    cur->Target.y = cur->Position.y + cur->Direction.y;"),
    M("set_vel_inv", CAMC, "    inv = 1.0f / elapsed;", "    inv = elapsed;"),
    M("set_elapsed", CAMC, "    c->ElapsedTime = elapsed;\n", ""),
    # cammover.c
    M("name_unknown", MOVC, "        return \"CM_UNKNOWN(?)\";",
      "        return MOVER_NAMES[0];"),
    M("name_signed", MOVC,
      "    if ((unsigned)t >= sizeof MOVER_NAMES / sizeof MOVER_NAMES[0])",
      "    if ((int)t >= (int)(sizeof MOVER_NAMES / sizeof MOVER_NAMES[0]))"),
    M("mctor_far", MOVC, "    cam->CurrentKey.FarZ = 10000.0f;",
      "    cam->CurrentKey.FarZ = 5000.0f;"),
    M("mctor_no_vtbl", MOVC, "    m->vtbl = &CameraMoverBaseVtbl;\n    m->Type",
      "    m->Type"),
    M("mctor_player", MOVC, "    m->pPlayer = 0;\n", ""),
    M("mctor_enabled", MOVC, "    m->Enabled = 0;\n    m->pPlayer", "    m->pPlayer"),
    M("mctor_detached_cam", MOVC, "        m->pCamera = 0;\n", ""),
    M("mctor_detached_dash", MOVC, "        m->RenderDash = 0;\n        return;",
      "        return;"),
    M("mctor_no_enable", MOVC, "    m->pCamera = cam;\n    camera_mover_enable(m);",
      "    m->pCamera = cam;"),
    M("mctor_dash", MOVC, "    m->RenderDash = cam->RenderDash;",
      "    m->RenderDash = 0;"),
    M("dtor_no_vtbl", MOVC,
      "    m->vtbl = &CameraMoverBaseVtbl;\n    camera_mover_disable(m);",
      "    camera_mover_disable(m);"),
    M("dtor_no_disable", MOVC,
      "    m->vtbl = &CameraMoverBaseVtbl;\n    camera_mover_disable(m);",
      "    m->vtbl = &CameraMoverBaseVtbl;"),
    M("dtor_virtual_disable", MOVC,
      "    m->vtbl = &CameraMoverBaseVtbl;\n    camera_mover_disable(m);",
      "    m->vtbl->Disable(m);\n    m->vtbl = &CameraMoverBaseVtbl;"),
    M("enable_twice", MOVC, "    if (m->Enabled)\n        return;\n", ""),
    M("enable_flags_frozen", MOVC,
      "    if (!CameraStopUpdating) {\n        m->pCamera->CarNotToRender",
      "    {\n        m->pCamera->CarNotToRender"),
    M("enable_near", MOVC, "    m->pCamera->CurrentKey.NearZ = 0.5f;",
      "    m->pCamera->CurrentKey.NearZ = 1.0f;"),
    M("enable_no_attach", MOVC,
      "    eview_attach_camera_mover(m->pView, &m->Node);", ""),
    M("disable_twice", MOVC, "    if (!m->Enabled)\n        return;\n", ""),
    M("disable_no_carnot", MOVC,
      "    m->CarNotToRender = m->pCamera->CarNotToRender;\n", ""),
    M("disable_no_unattach", MOVC,
      "    eview_unattach_camera_mover(m->pView, &m->Node);", ""),
    M("base_ext_0", MOVC, "{ (void)m; return 1; }", "{ (void)m; return 0; }"),
    M("base_gap", MOVC, "return 0.7f; }", "return 3.0f; }"),
    M("base_lb_1", MOVC,
      "static int base_is_looking_back(CameraMover *m) { (void)m; return 0; }",
      "static int base_is_looking_back(CameraMover *m) { (void)m; return 1; }"),
    M("base_target", MOVC, "    return &m->pCamera->CurrentKey.Target;",
      "    return &m->pCamera->CurrentKey.Position;"),
    M("base_slots_swapped", MOVC,
      "    base_is_exterior_view,\n    base_is_looking_back,\n    base_get_wall_gap,\n"
      "    camera_mover_nothing,       // ResetState\n    camera_mover_enable,\n"
      "    camera_mover_disable,\n    base_get_car_to_follow,",
      "    base_is_looking_back,\n    base_is_exterior_view,\n    base_get_wall_gap,\n"
      "    camera_mover_nothing,       // ResetState\n    camera_mover_enable,\n"
      "    camera_mover_disable,\n    base_get_car_to_follow,"),
    M("base_enable_slot", MOVC,
      "    camera_mover_nothing,       // ResetState\n    camera_mover_enable,\n"
      "    camera_mover_disable,\n    base_get_car_to_follow,\n    base_get_target,",
      "    camera_mover_nothing,       // ResetState\n    camera_mover_disable,\n"
      "    camera_mover_disable,\n    base_get_car_to_follow,\n    base_get_target,"),
    M("get_position_dir", MOVC,
      "    return &m->pCamera->CurrentKey.Position;\n}\n\nconst bVector3 *camera_mover_get_direction",
      "    return &m->pCamera->CurrentKey.Direction;\n}\n\nconst bVector3 *camera_mover_get_direction"),
    M("set_player_none", MOVC, "    m->pPlayer = player;", "    (void)player;"),
    M("update_all", MOVC,
      "        CameraMover *m = first_mover(eGetView(i));\n\n        if (m)\n"
      "            m->vtbl->Update(m);",
      "        bNode *n;\n\n        for (n = eGetView(i)->CameraMoverList.next;"
      " n != &eGetView(i)->CameraMoverList; n = n->next)\n"
      "            ((CameraMover *)n)->vtbl->Update((CameraMover *)n);"),
    M("update_nine", MOVC, "    for (i = 0; i < EVIEW_NUM_VIEWS; i++) {",
      "    for (i = 0; i < EVIEW_NUM_VIEWS - 1; i++) {"),
    M("update_from_one", MOVC, "    for (i = 0; i < EVIEW_NUM_VIEWS; i++) {",
      "    for (i = 1; i < EVIEW_NUM_VIEWS; i++) {"),
    M("render_none", MOVC, "        m->vtbl->Render(m, view);", "        (void)m;"),
    M("first_is_last", MOVC,
      "    bNode *n = v->CameraMoverList.next;\n\n    return n != &v->CameraMoverList ? (CameraMover *)n : 0;",
      "    bNode *n = v->CameraMoverList.prev;\n\n    return n != &v->CameraMoverList ? (CameraMover *)n : 0;"),
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
