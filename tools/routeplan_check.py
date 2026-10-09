#!/usr/bin/env python3
"""Cross-check the route planners in 3DS Files/source/airouteplan.c --
ReturnToLastBranch, FindRoutesToTarget, FindPointsToTarget and
FindNearbySignpost -- against the retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own code: the four functions (0x001cc130,
0x001cc270, 0x001cc5d0, 0x001cc838), and under them, as shipped,
TrackRoutePoint::GetSignpost (0x001c14f8), Signpost::GetNewRoute
(0x001c0ff8) and GetNewRoutePoint (0x001c1020), and
TrackRoute::GetRelativePoint (0x001c1910). The routes are real ones in the
model's memory, the signposts sit where SignpostArray (gp-18376) points,
and TheTrackRouteManager's table (0x00314438 + 16) names the routes. The
harness (tools/src/routeplan_test.c) runs airouteplan.c and trackroute.c
over the same script and prints the same lines.

**The port's divergences**, which hooks make the model share:
  - GetRelativePoint handed no point answers none. The image works an
    index out of address 0 (a branch kept at a route's end has no point).
  - FindRoutesToTarget looks at a branch's point as it comes back with
    `heli`; with none it runs off, where the image reads address 44.
  - ReturnToLastBranch with the routes run out answers 0. The image
    compares a stale word for ever.
  - FindRoutesToTarget's look through the routes stops after twenty.
    The image's goes round for ever when Back is 0 or the deque is full.
  - FindRoutesToTarget gives up after ROUTEPLAN_MAX_WALK steps, as on
    running off. The image can walk a loop of routes for ever once its
    deque is full.

**Compared** are each call's answer, the info or the out list, and the
deques afterwards, every slot.

**The script** counts points to signposts each way, off the ends and from
no point; takes branches off empty, full and wrapped deques, with the
branch's route at the back, further in, and missing; walks to targets
over every sign value each way, past routes already taken, back from
signs 2 and 3 and from the helicopter's no-go points, off the ends, with
the deque full and wrapped, and round a loop until the walk gives up;
down a chain of 22 routes that fills both deques; to a target found on
the walk's last allowed step, and one step either side; lists points to
targets, at the target, past each sign, to the count's end; and then a
thousand random networks of four routes.

    python tools/routeplan_check.py
    python tools/routeplan_check.py --mutate [--only a,b]
    python tools/routeplan_check.py --dump out/routeplan
"""
import argparse
import os
import random
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
from mipsemu import M32, M64, MipsError, s32   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/routeplan_test.c"
PLAN = "3DS Files/source/airouteplan.c"
SOURCES = [HARNESS, PLAN,
           "3DS Files/source/trackroute.c",
           "3DS Files/source/trackpath.c",
           "3DS Files/source/quickspline.c",
           "3DS Files/source/bmem.c",
           "3DS Files/source/bmatrix.c",
           "3DS Files/source/bvector.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c",
           "3DS Files/source/bchunk.c",
           "3DS Files/source/vtable.c"]
HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = retail_model.RETAIL_GP
G_SIGNS = GP - 18376                    # SignpostArray
TRM = 0x00314438                        # TheTrackRouteManager

F_RTLB = 0x001cc130
F_ROUTES = 0x001cc270
F_POINTS = 0x001cc5d0
F_NEARBY = 0x001cc838

H_REL = 0x001c1910                      # GetRelativePoint's entry
H_RTLB_CMP = 0x001cc25c                 # bne a0,v0: the route at the back?
H_RTLB_RET = 0x001cc268                 # jr ra
H_LOOK0 = 0x001cc524                    # the look through the routes
H_LOOK = 0x001cc54c                     # bne a0,v0: at Back yet?
H_WALK = 0x001cc3ec                     # the walk's GetRelativePoint
H_EXAMINE = 0x001cc434                  # lbu v0,44(a0): the point's sign

NROUTES, NSIGNS, NOUT, MAXP = 24, 256, 16, 32
NNET = 4                                # the random networks' routes
ROUTE_SIZE, TABLE, PSIZE = 115752, 1064, 112
RING = 20
MAX_WALK = 0x11800
LIMIT = 20000000

A0, A1, A2, V0, SP = 4, 5, 6, 2, 29
NO_HELI = 0x4000


# ================================================================ the model

class Model:
    def __init__(self):
        e = self.e = retail_model.RetailEmu(ieee=True)
        self.lines = []
        self.routes = [e.alloc(ROUTE_SIZE, 16) for _ in range(NROUTES)]
        self.signs = e.alloc(12 * NSIGNS, 16)
        e.put32(G_SIGNS, self.signs)
        for k, r in enumerate(self.routes):
            e.put32(TRM + 16 + 4 * k, r)
        self.rq = e.alloc(92, 16)
        self.bq = e.alloc(172, 16)
        self.info = e.alloc(16, 16)
        self.tgt = e.alloc(16, 16)
        self.out = e.alloc(8 * NOUT, 16)
        self.dummy = e.alloc(PSIZE, 16)
        e.put32(self.dummy + 44, 0xff)
        self.force = False
        self.looks = 0
        self.walk = 0
        self.stats = dict(nullstep=0, examine=0, rtlb_empty=0, looks=0,
                          walk=0, found=0, lost=0)
        e.hook(H_REL, self.h_rel)
        e.hook(H_RTLB_CMP, self.h_rtlb_cmp)
        e.hook(H_RTLB_RET, self.h_rtlb_ret)
        e.hook(H_LOOK0, self.h_look0)
        e.hook(H_LOOK, self.h_look)
        e.hook(H_WALK, self.h_walk)
        e.hook(H_EXAMINE, self.h_examine)
        e.hook(F_ROUTES, self.h_routes)

    # ---- the divergences --------------------------------------------------

    def h_rel(self, e):
        if e.reg[A1] & M32:
            return
        r = e.reg[A0] & M32
        n = s32(e.u32(r + 16))
        e.reg[A1] = (r + TABLE + (PSIZE * (n - 1) if e.reg[A2] else 0)) & M64
        self.stats["nullstep"] += 1

    def h_examine(self, e):
        if e.reg[A0] & M32 == 0:
            e.reg[A0] = self.dummy
            self.stats["examine"] += 1

    def empty(self, q, items):
        e = self.e
        off = 4 * items if items == RING else 8 * RING
        return e.u32(q + off + 8) == 0 and e.u32(q + off) == e.u32(q + off + 4)

    def h_rtlb_cmp(self, e):
        if self.empty(e.reg[A2] & M32, RING):
            self.force = True
            e.reg[V0] = e.reg[A0]
            self.stats["rtlb_empty"] += 1

    def h_rtlb_ret(self, e):
        if self.force:
            self.force = False
            e.reg[V0] = 0

    def h_look0(self, e):
        self.looks = 0

    def h_look(self, e):
        self.looks += 1
        if self.looks >= RING and e.reg[A0] != e.reg[V0]:
            e.reg[V0] = e.reg[A0]
            self.stats["looks"] += 1

    def h_routes(self, e):
        self.walk = 0

    def h_walk(self, e):
        self.walk += 1
        if self.walk > MAX_WALK:
            e.put32((e.reg[SP] & M32) + 180, 0)
            if self.walk == MAX_WALK + 1:
                self.stats["walk"] += 1

    # ---- names ------------------------------------------------------------

    def rname(self, a):
        if a == 0:
            return "0"
        for k, r in enumerate(self.routes):
            if a == r:
                return "r%d" % k
        return "?"

    def pname(self, a):
        if a == 0:
            return "0"
        for k, r in enumerate(self.routes):
            t = r + TABLE
            if t <= a < t + 1024 * PSIZE and (a - t) % PSIZE == 0:
                return "r%d.p%d" % (k, (a - t) // PSIZE)
        return "?"

    def route_of(self, v):
        return 0 if v < 0 else self.routes[v]

    def point_of(self, v):
        if v < 0:
            return 0
        return self.routes[v // 1024] + TABLE + PSIZE * (v % 1024)

    def put_info(self, a, r, p):
        self.e.put32(a, self.route_of(r))
        self.e.put32(a + 4, self.point_of(p))

    def info_str(self, a):
        e = self.e
        return "%s %s" % (self.rname(e.u32(a)), self.pname(e.u32(a + 4)))

    def rq_str(self):
        e, q = self.e, self.rq
        return "  rq %d %d %d %s" % (
            s32(e.u32(q + 80)), s32(e.u32(q + 84)), s32(e.u32(q + 88)),
            " ".join(self.rname(e.u32(q + 4 * i)) for i in range(RING)))

    def bq_str(self):
        e, q = self.e, self.bq
        return "  bq %d %d %d %s" % (
            s32(e.u32(q + 160)), s32(e.u32(q + 164)), s32(e.u32(q + 168)),
            " ".join("%s,%s" % (self.rname(e.u32(q + 8 * i)),
                                self.pname(e.u32(q + 8 * i + 4)))
                     for i in range(RING)))

    def call(self, f, *args):
        return self.e.call(f, *[a & M64 for a in args], limit=LIMIT)

    # ---- the ops ----------------------------------------------------------

    def run(self, t):
        e = self.e
        op = t[0]
        L = self.lines.append
        L(op)
        a = [int(x) for x in t[1:]] if op != "pb" else None
        if op == "clr":
            for r in self.routes:
                e.mem[r:r + ROUTE_SIZE] = bytes(ROUTE_SIZE)
            e.mem[self.signs:self.signs + 12 * NSIGNS] = bytes(12 * NSIGNS)
            for r in self.routes:
                for i in range(a[0]):
                    e.put32(r + TABLE + PSIZE * i + 44, 0xff)
        elif op == "rt":
            e.put32(self.routes[a[0]] + 16, a[1])
        elif op == "pb":
            k, i = int(t[1]), int(t[2])
            e.put32(self.routes[k] + TABLE + PSIZE * i + 44, int(t[3], 16))
        elif op == "sg":
            s = self.signs + 12 * a[0]
            e.mem[s] = a[1] & 0xff
            e.mem[s + 1] = a[2] & 0xff
            e.mem[s + 2] = a[3] & 0xff
            e.mem[s + 3] = (a[3] >> 8) & 0xff
        elif op == "rq":
            e.put32(self.rq + 80, a[0])
            e.put32(self.rq + 84, a[1])
            e.put32(self.rq + 88, a[2])
            for i in range(RING):
                e.put32(self.rq + 4 * i, self.route_of(a[3 + i]))
        elif op == "bq":
            e.put32(self.bq + 160, a[0])
            e.put32(self.bq + 164, a[1])
            e.put32(self.bq + 168, a[2])
            for i in range(RING):
                self.put_info(self.bq + 8 * i, a[3 + 2 * i], a[4 + 2 * i])
        elif op == "nearby":
            self.put_info(self.info, a[0], a[1])
            r = self.call(F_NEARBY, self.info, a[2])
            L("  -> %d %s" % (r, self.info_str(self.info)))
        elif op == "points":
            self.put_info(self.info, a[0], a[1])
            self.put_info(self.tgt, a[2], a[3])
            e.mem[self.out:self.out + 8 * NOUT] = bytes(8 * NOUT)
            r = self.call(F_POINTS, self.info, self.tgt, self.out, a[4],
                          a[5], a[6])
            L("  -> %u %s" % (r & M32, " ".join(
                "%s,%s" % (self.rname(e.u32(self.out + 8 * i)),
                           self.pname(e.u32(self.out + 8 * i + 4)))
                for i in range(NOUT))))
        elif op == "routes":
            self.put_info(self.info, a[0], a[1])
            r = self.call(F_ROUTES, self.info, self.route_of(a[2]), self.rq,
                          a[3], a[4])
            self.stats["found" if r else "lost"] += 1
            L("  -> %d" % r)
            L(self.rq_str())
        elif op == "rtlb":
            self.put_info(self.info, a[0], a[1])
            r = self.call(F_RTLB, self.info, self.bq, self.rq)
            L("  -> %d %s" % (r, self.info_str(self.info)))
            L(self.bq_str())
            L(self.rq_str())
        else:
            raise ValueError(op)


def model(lines):
    m = Model()
    for ln in lines:
        m.run(ln.split("|"))
    return m


# ================================================================ the script

def P(k, i):
    return k * 1024 + i


def clr(maxp=MAXP):
    return ["clr|%d" % maxp]


def rt(k, n):
    return ["rt|%d|%d" % (k, n)]


def pb(k, i, bits):
    return ["pb|%d|%d|%x" % (k, i, bits & M32)]


def sg(i, route, flags, point):
    return ["sg|%d|%d|%d|%d" % (i, route, flags, point)]


def rq(front=0, back=0, full=0, items=None):
    items = list(items or []) + [-1] * (RING - len(items or []))
    return ["rq|%d|%d|%d|%s" % (front, back, full,
                                "|".join(str(v) for v in items))]


def bq(front=0, back=0, full=0, items=None):
    items = list(items or []) + [(-1, -1)] * (RING - len(items or []))
    return ["bq|%d|%d|%d|%s" % (front, back, full, "|".join(
        "%d|%d" % (r, p) for r, p in items))]


def nearby(k, i, fwd):
    return ["nearby|%d|%d|%d" % (k, -1 if i < 0 else P(k, i), fwd)]


def points(s, g, count, fwd, heli):
    return ["points|%d|%d|%d|%d|%d|%d|%d" % (
        s[0], P(*s), g[0], -1 if g[1] < 0 else P(*g), count, fwd, heli)]


def routes(s, target, fwd, heli):
    return ["routes|%d|%d|%d|%d|%d" % (s[0], P(*s), target, fwd, heli)]


def rtlb(r, p):
    return ["rtlb|%d|%d" % (r, p)]


def sign_at(k, i, s, heli=0):
    return pb(k, i, s | (NO_HELI if heli else 0))


def network(lens, signs, marks=(), heli=()):
    """`lens` points per route; `signs` {sign: (route, flags, point)};
    `marks` (route, point, sign); `heli` (route, point) no-go points."""
    out = clr()
    for k, n in enumerate(lens):
        out += rt(k, n)
    for s, (r, f, p) in sorted(signs.items()):
        out += sg(s, r, f, p)
    hs = set(heli)
    for k, i, s in marks:
        out += sign_at(k, i, s, (k, i) in hs)
        hs.discard((k, i))
    for k, i in sorted(hs):
        out += pb(k, i, 0xff | NO_HELI)
    return out


FWDS = (0, 1, 2)


def nearbys():
    out = network([10, 6, 0, 3], {0: (1, 0, 0)},
                  marks=[(0, 3, 0), (0, 7, 0), (1, 0, 0)])
    for fwd in FWDS + (-1,):
        for i in range(-1, 13):
            out += nearby(0, i, fwd)
        for i in range(0, 7):
            out += nearby(1, i, fwd)
        out += nearby(2, 0, fwd)
        out += nearby(3, 2, fwd)
    return out


def rtlbs():
    out = network([10, 10, 10, 10], {})
    b3 = [(0, P(0, 4)), (1, P(1, 2)), (2, -1)]
    cases = [
        # (bq state, rq state)
        ((0, 0, 0, b3), (0, 3, 0, [0, 1, 2])),          # no branch
        ((0, 3, 0, b3), (0, 3, 0, [0, 1, 2])),          # r0 under two
        ((1, 3, 0, b3), (0, 3, 0, [0, 1, 2])),          # r1 under one
        ((2, 3, 0, b3), (0, 3, 0, [0, 1, 2])),          # r2 at the back
        ((0, 3, 0, b3), (0, 2, 0, [1, 2])),             # r0 missing
        ((0, 3, 0, b3), (0, 0, 0, [0, 1])),             # no routes
        ((0, 3, 0, b3), (5, 5, 1, [0, 1, 2, 3] * 5)),   # routes full
        ((0, 3, 0, b3), (0, 0, 1, [3] * 19 + [0])),     # full, back 0
        ((0, 3, 0, b3), (3, 0, 0, [9] * 0 + [-1] * 3 + [3] * 16 + [0])),
        ((19, 1, 0, [(0, P(0, 1))] + [(3, 3)] * 18 + [(1, P(1, 9))]),
         (0, 2, 0, [0, 1])),                            # front 19
        ((7, 7, 1, [(k % 4, P(k % 4, k)) for k in range(20)]),
         (0, 4, 0, [0, 1, 2, 3])),                      # branches full
        ((4, 4, 1, [(3, -1)] * 20), (0, 1, 0, [3])),
        ((4, 4, 0, [(3, -1)] * 20), (0, 1, 0, [3])),    # empty, front 4
    ]
    for (bf, bb, bfu, bi), (rf, rb, rfu, ri) in cases:
        bi = [(r, p if p != 3 else P(r, 3)) for r, p in bi]
        out += bq(bf, bb, bfu, bi)
        out += rq(rf, rb, rfu, ri)
        out += rtlb(3, P(3, 0))
        # Once more on what the first left.
        out += rtlb(-1, -1)
    return out


def routes_basic():
    out = []
    # r0 --s0 (sign v) at p4--> r1.p2; r1 --s1 at p6--> r2.p0 (the target).
    for v in range(8):
        for back in (0, 8):
            out += network([10, 10, 10, 10],
                           {0: (1, v | back, 2), 1: (2, v | back, 0)},
                           marks=[(0, 4, 0), (1, 6, 1)])
            for fwd in FWDS:
                for tgt in (0, 1, 2, 3, -1):
                    out += rq()
                    out += routes((0, 1), tgt, fwd, 0)
                    out += rq()
                    out += routes((0, 8), tgt, fwd, 0)
    # A sign to a route already taken: passed by, or back to the branch.
    for v in range(8):
        out += network([12, 12, 12, 12],
                       {0: (1, 0, 0), 1: (0, v, 5), 2: (2, 0, 3)},
                       marks=[(0, 2, 0), (1, 4, 1), (0, 6, 2)])
        for fwd in (0, 1):
            out += rq()
            out += routes((0, 0), 2, fwd, 0)
            out += rq()
            out += routes((0, 0), 3, fwd, 0)
    return out


def routes_heli():
    out = []
    # The no-go point on the branch's route sends the walk back.
    for hp in range(0, 12, 2):
        out += network([12, 12, 12, 12],
                       {0: (1, 0, 0), 1: (2, 1, 0), 2: (3, 0, 0)},
                       marks=[(0, 3, 0), (1, 5, 1), (0, 9, 2)],
                       heli=[(1, hp), (0, 11)])
        for heli in FWDS:
            for tgt in (2, 3):
                out += rq()
                out += routes((0, 0), tgt, 1, heli)
    # A branch kept at the end of a route: stepped from, and looked at.
    for v in (0, 1, 2, 3):
        out += network([8, 8, 8, 8],
                       {0: (1, 0, 0), 1: (0, v, 0)},
                       marks=[(0, 7, 0), (1, 3, 1)],
                       heli=[(1, 2)])
        for heli in (0, 1):
            out += rq()
            out += routes((0, 5), 3, 1, heli)
            out += rq()
            out += routes((0, 0), 3, 0, heli)
    return out


def routes_deques():
    out = network([10, 10, 10, 10], {0: (1, 0, 0), 1: (2, 1, 0),
                                     2: (3, 0, 4)},
                  marks=[(0, 3, 0), (1, 5, 1), (2, 2, 2)])
    states = [
        (0, 0, 0, []), (0, 0, 1, [0] * 20), (0, 0, 1, [3] * 20),
        (0, 0, 1, [2] * 20), (5, 5, 1, [1] * 20), (5, 5, 1, [-1] * 20),
        (0, 19, 0, [-1] * 19), (0, 18, 0, [-1] * 18), (7, 3, 0, [-1] * 20),
        (12, 0, 0, [-1] * 12 + [2] + [-1] * 7),
        (12, 0, 0, [1] + [-1] * 19), (12, 0, 0, [-1] * 20),
        (3, 3, 0, [1, 2] * 10), (19, 19, 0, []), (19, 0, 0, [-1] * 19 + [1]),
    ]
    for st in states:
        for tgt in (0, 1, 2, 3):
            for fwd in (0, 1):
                out += rq(*st)
                out += routes((0, 0), tgt, fwd, 1)
                # And again on what it left.
                out += routes((0, 0), tgt, fwd, 0)
    return out


def routes_loop():
    """The routes full of a third route: r0 and r1 send the walk to each
    other for ever, and the walk gives up."""
    out = network([10, 10, 10, 10], {0: (1, 0, 0), 1: (0, 0, 0)},
                  marks=[(0, 2, 0), (1, 2, 1)])
    out += rq(0, 0, 1, [3] * 20)
    out += routes((0, 0), 2, 1, 0)
    out += rq(0, 0, 1, [3] * 20)
    out += routes((0, 0), 2, 1, 1)
    return out


def routes_chain():
    """Twenty-two routes in a row, each one's p1 signed to the next: the
    routes fill at r19, the branches at r20, and r20's is dropped. A no-go
    point (or a sign 3 back to r0) on r21 sends the walk back to r19's
    branch, whose p3 is signed to r22."""
    out = clr()
    for k in range(23):
        out += rt(k, 4)
    for k in range(21):
        out += sg(k, k + 1, 0, 0)
        out += pb(k, 1, k)
    out += sg(21, 22, 0, 0)
    out += pb(19, 3, 21)
    out += sg(22, 0, 3, 0)
    for heli in (0, 1):
        out += pb(21, 1, 0xff | NO_HELI if heli else 22)
        for tgt in (22, -1, 21):
            out += rq()
            out += routes((0, 0), tgt, 1, heli)
    return out


def routes_long():
    """r0's p0 .. p79 are signed to r1, whose no-go point at p`n` sends the
    walk back to r0 after n steps; r0's p80 is signed to the target. At
    n = 896 the target turns up on the walk's 0x11800th step."""
    out = clr(1024)
    out += rt(0, 100) + rt(1, 1024) + rt(2, 10)
    out += sg(0, 1, 0, 0) + sg(1, 2, 0, 0)
    for i in range(80):
        out += pb(0, i, 0)
    out += pb(0, 80, 1)
    for n in (895, 896, 897):
        out += pb(1, n - 1, 0xff)
        out += pb(1, n, 0xff | NO_HELI)
        out += rq()
        out += routes((0, 0), 2, 1, 1)
    # Shorter: the target 1,020 steps on.
    out += pb(1, 897, 0xff)
    out += pb(1, 1020, 0)
    out += sg(0, 2, 0, 0)
    out += rq()
    out += routes((1, 0), 2, 1, 0)
    return out


def points_basic():
    out = []
    for v in range(8):
        for back in (0, 8):
            out += network([12, 12, 12, 12],
                           {0: (1, v | back, 2), 1: (2, v | back, 0),
                            2: (0, v | back, 9)},
                           marks=[(0, 4, 0), (1, 6, 1), (0, 1, 2)],
                           heli=[(2, 5)])
            for fwd in FWDS:
                for g in ((0, 4), (0, 9), (1, 2), (2, 3), (2, 7), (3, 3),
                          (0, -1)):
                    for count in (0, 1, 5, 15):
                        for heli in (0, 1):
                            out += points((0, 0), g, count, fwd, heli)
                            out += points((0, 11), g, count, fwd, heli)
    # The start is the target; the start a no-go point.
    out += network([12, 12, 12, 12], {}, heli=[(0, 3)])
    for heli in (0, 1, 2):
        out += points((0, 3), (0, 3), 5, 1, heli)
        out += points((0, 3), (1, 3), 5, 1, heli)
        out += points((0, 3), (0, 8), 5, 1, heli)
        out += points((0, 3), (0, 1), 5, 0, heli)
        out += ["points|0|%d|1|%d|5|1|%d" % (P(0, 3), P(0, 3), heli)]
    return out


def rand_net(rng):
    lens = [rng.choice((0, 1, 2, 4, 6, 8, 10, 12, 16, 20, 24, MAXP))
            for _ in range(NNET)]
    nsigns = rng.choice((1, 3, 6, 12))
    out = clr()
    for k, n in enumerate(lens):
        out += rt(k, n)
    for s in range(nsigns):
        out += sg(s, rng.randrange(NNET), rng.randrange(0x80),
                  rng.choice((0, rng.randrange(MAXP), rng.randrange(8))))
    psign = rng.choice((0.1, 0.25, 0.5))
    pheli = rng.choice((0.0, 0.05, 0.15))
    for k in range(NNET):
        for i in range(MAXP):
            bits = 0xff
            if rng.random() < psign:
                bits = rng.randrange(nsigns)
            if rng.random() < pheli:
                bits |= NO_HELI
            if rng.random() < 0.1:
                bits |= rng.choice((0x8000, 0x3f00, 0x10000000, 0xbfff00))
            if bits != 0xff:
                out += pb(k, i, bits)
    return out, lens


def rand_point(rng, lens, null=False):
    k = rng.randrange(NNET)
    if null and rng.random() < 0.05:
        return (k, -1)
    return (k, rng.randrange(max(1, min(MAXP, lens[k] + 2))))


def rand_rq(rng):
    if rng.random() < 0.6:
        return rq()
    items = [rng.choice((-1, 0, 1, 2, 3)) for _ in range(RING)]
    f = rng.randrange(RING)
    b = rng.choice((f, rng.randrange(RING), 0))
    return rq(f, b, int(rng.random() < 0.3), items)


def rand_bq(rng, lens):
    items = [rand_point(rng, lens, True) for _ in range(RING)]
    items = [(k, -1 if i < 0 else P(k, i)) for k, i in items]
    f = rng.randrange(RING)
    b = rng.choice((f, rng.randrange(RING), (f + 1) % RING))
    return bq(f, b, int(rng.random() < 0.3), items)


def randoms(rng, n=1000):
    out = []
    for _ in range(n):
        net, lens = rand_net(rng)
        out += net
        for _ in range(2):
            k, i = rand_point(rng, lens, True)
            out += nearby(k, i, rng.choice(FWDS))
        for _ in range(3):
            g = rand_point(rng, lens, True)
            s = rand_point(rng, lens)
            if rng.random() < 0.1:
                g = s
            out += points(s, g, rng.choice((0, 1, 2, 5, 8, 15)),
                          rng.choice(FWDS), rng.choice(FWDS))
        for _ in range(2):
            out += rand_rq(rng)
            out += routes(rand_point(rng, lens), rng.randrange(-1, NNET),
                          rng.choice(FWDS), rng.choice(FWDS))
        out += rand_bq(rng, lens)
        out += rand_rq(rng)
        k, i = rand_point(rng, lens, True)
        out += rtlb(k, -1 if i < 0 else P(k, i))
    return out


def script():
    rng = random.Random(0x7a3e)
    return (nearbys() + rtlbs() + routes_basic() + routes_heli()
            + routes_deques() + routes_loop() + routes_chain()
            + routes_long() + points_basic()
            + randoms(rng))


# ================================================================= running

def build_harness(tmp, name="routeplan_test"):
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

def M(name, before, after):
    return (name, PLAN, before, after)


MUTATIONS = [
    # The routes deque.
    M("empty_full", "return !r->Full && r->Front == r->Back;",
      "return r->Front == r->Back;"),
    M("empty_ne", "return !r->Full && r->Front == r->Back;",
      "return !r->Full && r->Front != r->Back;"),
    M("push_full", "    if (r->Full)\n        return;\n    r->Item[r->Back]",
      "    r->Item[r->Back]"),
    M("push_no_store", "    r->Item[r->Back] = route;\n", ""),
    M("push_wrap", "if (r->Back == ROUTEPLAN_RING)\n        r->Back = 0;",
      "if (r->Back == ROUTEPLAN_RING - 1)\n        r->Back = 0;"),
    M("push_no_full", "r->Full = r->Back == r->Front;", "r->Full = 0;"),
    M("contain_no_empty",
      "    if (routes_empty(r))\n        return 0;\n    i = r->Front;",
      "    i = r->Front;"),
    M("contain_from_0", "    i = r->Front;", "    i = 0;"),
    M("contain_hit", "if (r->Item[i] == route)\n            return 1;",
      "if (r->Item[i] == route)\n            return 0;"),
    M("contain_back", "if (i == r->Back)\n            return 0;",
      "if (i == r->Back)\n            return 1;"),
    M("contain_order",
      "        if (i == r->Back)\n            return 0;\n"
      "        if (i == ROUTEPLAN_RING)\n            i = 0;\n",
      "        if (i == ROUTEPLAN_RING)\n            i = 0;\n"
      "        if (i == r->Back)\n            return 0;\n"),
    M("contain_19", "for (n = 0; n < ROUTEPLAN_RING; n++) {",
      "for (n = 0; n < ROUTEPLAN_RING - 1; n++) {"),
    M("contain_wrap", "if (i == ROUTEPLAN_RING)\n            i = 0;",
      "if (i == ROUTEPLAN_RING - 1)\n            i = 0;"),
    M("contain_out", "    }\n    return 0;\n}\n\n// GetRelativePoint",
      "    }\n    return 1;\n}\n\n// GetRelativePoint"),
    M("relative_null", "    if (p == NULL)\n        return NULL;\n"
      "    return troute_get_relative_point",
      "    return troute_get_relative_point"),

    # ReturnToLastBranch.
    M("rtlb_empty_full", "if (!b->Full && b->Front == b->Back)\n        return 0;",
      "if (b->Front == b->Back)\n        return 0;"),
    M("rtlb_empty_1", "if (!b->Full && b->Front == b->Back)\n        return 0;",
      "if (!b->Full && b->Front == b->Back)\n        return 1;"),
    M("rtlb_take_back", "*info = b->Item[b->Front];",
      "*info = b->Item[b->Back == 0 ? ROUTEPLAN_RING - 1 : b->Back - 1];"),
    M("rtlb_no_pop", "    b->Front++;\n    if (b->Front == ROUTEPLAN_RING)\n"
      "        b->Front = 0;\n", ""),
    M("rtlb_wrap", "if (b->Front == ROUTEPLAN_RING)\n        b->Front = 0;",
      "if (b->Front == ROUTEPLAN_RING - 1)\n        b->Front = 0;"),
    M("rtlb_full", "    b->Full = 0;\n    route = info->Route;",
      "    route = info->Route;"),
    M("rtlb_route", "route = info->Route;", "route = b->Item[0].Route;"),
    M("rtlb_routes_empty",
      "        if (routes_empty(r))\n            return 0;\n        if (r->Item",
      "        if (routes_empty(r))\n            return 1;\n        if (r->Item"),
    M("rtlb_peek_wrap",
      "r->Item[r->Back == 0 ? ROUTEPLAN_RING - 1 : r->Back - 1] == route",
      "r->Item[r->Back == 0 ? 0 : r->Back - 1] == route"),
    M("rtlb_peek_back",
      "r->Item[r->Back == 0 ? ROUTEPLAN_RING - 1 : r->Back - 1] == route",
      "r->Item[r->Back] == route"),
    M("rtlb_found", "== route)\n            return 1;\n        r->Back",
      "== route)\n            return 0;\n        r->Back"),
    M("rtlb_pop_wrap",
      "r->Back = r->Back == 0 ? ROUTEPLAN_RING - 1 : r->Back - 1;",
      "r->Back = r->Back == 0 ? 0 : r->Back - 1;"),
    M("rtlb_pop_full", "        r->Full = 0;\n    }\n}", "    }\n}"),

    # FindRoutesToTarget.
    M("routes_no_start",
      "    routes_push(routes, start->Route);\n    if (cur.Route == target)",
      "    if (cur.Route == target)"),
    M("routes_start_0", "    if (cur.Route == target)\n        return 1;",
      "    if (cur.Route == target)\n        return 0;"),
    M("routes_start_skip", "    if (cur.Route == target)\n        return 1;\n",
      ""),
    M("routes_dir", "if (fwd ? !back : back) {\n                TrackRoute *to",
      "if (fwd ? back : !back) {\n                TrackRoute *to"),
    M("routes_dir_fwd", "if (fwd ? !back : back) {\n                TrackRoute *to",
      "if (!back) {\n                TrackRoute *to"),
    M("routes_sign_mask",
      "uint32_t    sign = s->Flags & SIGNPOST_SIGN_MASK;",
      "uint32_t    sign = s->Flags & 3;"),
    M("routes_to_no_push",
      "                if (to == target) {\n"
      "                    routes_push(routes, to);\n",
      "                if (to == target) {\n"),
    M("routes_to_0", "routes_push(routes, to);\n                    return 1;",
      "routes_push(routes, to);\n                    return 0;"),
    M("routes_to_target", "if (to == target) {", "if (to == cur.Route) {"),
    M("routes_contain", "if (!routes_contain(routes, to)) {",
      "if (routes_contain(routes, to)) {"),
    M("routes_contain_never", "if (!routes_contain(routes, to)) {",
      "if (1) {"),
    M("routes_no_push_to",
      "                    routes_push(routes, to);\n"
      "                    if (sign != SIGN_ALWAYS_TAKE) {",
      "                    if (sign != SIGN_ALWAYS_TAKE) {"),
    M("routes_branch_3", "if (sign != SIGN_ALWAYS_TAKE) {",
      "if (sign != SIGN_STOP) {"),
    M("routes_branch_2", "if (sign != SIGN_ALWAYS_TAKE) {",
      "if (sign == SIGN_ALWAYS_TAKE) {"),
    M("routes_branch_here",
      "                        cur.Point = troute_get_relative_point(cur.Route,\n"
      "                                                              cur.Point, fwd);\n",
      ""),
    M("routes_branch_dir",
      "cur.Point, fwd);\n                        if (!b.Full) {",
      "cur.Point, !fwd);\n                        if (!b.Full) {"),
    M("routes_branch_full", "if (!b.Full) {", "if (1) {"),
    M("routes_branch_front",
      "b.Front = b.Front == 0 ? ROUTEPLAN_RING - 1",
      "b.Front = b.Front == 0 ? 0"),
    M("routes_branch_no_full", "b.Full = b.Back == b.Front;", "b.Full = 0;"),
    M("routes_branch_start", "b.Item[b.Front] = cur;",
      "b.Item[b.Front] = *start;"),
    M("routes_jump_route", "                    cur.Route = to;\n", ""),
    M("routes_jump_point",
      "cur.Point = signpost_get_new_route_point(s);\n                } else if",
      "cur.Point = troute_get_relative_point(cur.Route, cur.Point, fwd);\n"
      "                } else if"),
    M("routes_back_2",
      "} else if (sign == SIGN_ALWAYS_TAKE || sign == SIGN_STOP) {",
      "} else if (sign == SIGN_ALWAYS_TAKE) {"),
    M("routes_back_3",
      "} else if (sign == SIGN_ALWAYS_TAKE || sign == SIGN_STOP) {",
      "} else if (sign == SIGN_STOP) {"),
    M("routes_back_any",
      "} else if (sign == SIGN_ALWAYS_TAKE || sign == SIGN_STOP) {",
      "} else {"),
    M("routes_back_ret",
      "                    if (!ai_return_to_last_branch(&cur, &b, routes))\n"
      "                        break;",
      "                    if (ai_return_to_last_branch(&cur, &b, routes))\n"
      "                        break;"),
    M("routes_back_ignore",
      "                    if (!ai_return_to_last_branch(&cur, &b, routes))\n"
      "                        break;",
      "                    ai_return_to_last_branch(&cur, &b, routes);"),
    M("routes_walk_never", "if (++walk > ROUTEPLAN_MAX_WALK)",
      "if (++walk < 0)"),
    M("routes_walk_short", "if (++walk > ROUTEPLAN_MAX_WALK)",
      "if (++walk > 1000)"),
    M("routes_walk_ge", "if (++walk > ROUTEPLAN_MAX_WALK)",
      "if (++walk >= ROUTEPLAN_MAX_WALK)"),
    M("routes_step_dir", "cur.Point = relative(cur.Route, cur.Point, fwd);",
      "cur.Point = relative(cur.Route, cur.Point, !fwd);"),
    M("routes_heli", "if (heli && (cur.Point->Bits & TRP_NO_HELISHEET) != 0\n"
      "            && (!ai",
      "if (!heli && (cur.Point->Bits & TRP_NO_HELISHEET) != 0\n"
      "            && (!ai"),
    M("routes_heli_bit",
      "(cur.Point->Bits & TRP_NO_HELISHEET) != 0\n            && (!ai",
      "(cur.Point->Bits & TRP_NO_HELISHEET) == 0\n            && (!ai"),
    M("routes_heli_ret",
      "            && (!ai_return_to_last_branch(&cur, &b, routes)\n",
      "            && (ai_return_to_last_branch(&cur, &b, routes)\n"),
    M("routes_heli_null",
      "&cur, &b, routes)\n                || cur.Point == NULL))",
      "&cur, &b, routes)))"),
    M("routes_end_back", "    routes->Back = routes->Front;\n", ""),
    M("routes_end_full", "    routes->Full = 0;\n    return 0;", "    return 0;"),
    M("routes_end_1", "    routes->Full = 0;\n    return 0;",
      "    routes->Full = 0;\n    return 1;"),

    # FindPointsToTarget.
    M("points_same_route", "if (start->Point == target->Point) {",
      "if (start->Route == target->Route) {"),
    M("points_same_start", "        *out = *target;\n", "        *out = *start;\n"),
    M("points_same_0", "        *out = *target;\n        return 1;",
      "        *out = *target;\n        return 0;"),
    M("points_heli_start",
      "if (heli && (start->Point->Bits & TRP_NO_HELISHEET) != 0)",
      "if (!heli && (start->Point->Bits & TRP_NO_HELISHEET) != 0)"),
    M("points_heli_start_n",
      "(start->Point->Bits & TRP_NO_HELISHEET) != 0)\n        return 0;",
      "(start->Point->Bits & TRP_NO_HELISHEET) != 0)\n        return 1;"),
    M("points_dir",
      "if (fwd ? !back : back) {\n                uint32_t sign",
      "if (fwd ? back : !back) {\n                uint32_t sign"),
    M("points_stop_2", "if (sign == SIGN_STOP) {\n                    cur.Point = NULL;",
      "if (sign == SIGN_FASTER) {\n                    cur.Point = NULL;"),
    M("points_stop_keep",
      "                    cur.Point = NULL;\n                    step = 0;\n",
      "                    step = 0;\n"),
    M("points_stop_step",
      "cur.Point = NULL;\n                    step = 0;",
      "cur.Point = NULL;\n                    step = 1;"),
    M("points_always", "} else if (sign == SIGN_ALWAYS_TAKE) {\n"
      "                    take = 1;",
      "} else if (sign == SIGN_ALWAYS_TAKE) {\n"
      "                    take = 0;"),
    M("points_routes_dir", "&routes,\n                                             fwd, heli);",
      "&routes,\n                                             !fwd, heli);"),
    M("points_routes_heli", "&routes,\n                                             fwd, heli);",
      "&routes,\n                                             fwd, 0);"),
    M("points_routes_cur", "ai_find_routes_to_target(&cur, target->Route,",
      "ai_find_routes_to_target(&cur, cur.Route,"),
    M("points_routes_start", "ai_find_routes_to_target(&cur, target->Route,",
      "ai_find_routes_to_target(start, target->Route,"),
    M("points_routes_empty", "if (routes_empty(&routes))\n                        return n;",
      "if (routes_empty(&routes))\n                        return 0;"),
    M("points_routes_empty_go",
      "                    if (routes_empty(&routes))\n"
      "                        return n;\n", ""),
    M("points_take_ne", "take = routes.Item[routes.Front]\n                           ==",
      "take = routes.Item[routes.Front]\n                           !="),
    M("points_take_next", "take = routes.Item[routes.Front]",
      "take = routes.Item[(routes.Front + 1) % ROUTEPLAN_RING]"),
    M("points_take_step", "                if (take) {\n                    step = 0;",
      "                if (take) {\n                    step = 1;"),
    M("points_take_route",
      "                    cur.Route = signpost_get_new_route(s);\n"
      "                    cur.Point = signpost_get_new_route_point(s);\n"
      "                }\n            }\n        }\n        if (step)",
      "                    cur.Point = signpost_get_new_route_point(s);\n"
      "                }\n            }\n        }\n        if (step)"),
    M("points_step_dir",
      "cur.Point = troute_get_relative_point(cur.Route, cur.Point, fwd);",
      "cur.Point = troute_get_relative_point(cur.Route, cur.Point, !fwd);"),
    M("points_heli", "        if (heli && (cur.Point->Bits & TRP_NO_HELISHEET) != 0)\n"
      "            return n;",
      "        if (!heli && (cur.Point->Bits & TRP_NO_HELISHEET) != 0)\n"
      "            return n;"),
    M("points_out_stay", "*out++ = cur;", "*out = cur;"),
    M("points_target_off", "if (cur.Point == target->Point || !(n < count))",
      "if (!(n < count))"),
    M("points_target_route", "if (cur.Point == target->Point || !(n < count))",
      "if (cur.Route == target->Route || !(n < count))"),
    M("points_count_le", "if (cur.Point == target->Point || !(n < count))",
      "if (cur.Point == target->Point || !(n <= count))"),
    M("points_count_off", "if (cur.Point == target->Point || !(n < count))",
      "if (cur.Point == target->Point || n == count)"),

    # FindNearbySignpost.
    M("nearby_0", "int32_t n = 1;", "int32_t n = 0;"),
    M("nearby_ret_1", "            return n;\n        info->Point",
      "            return 1;\n        info->Point"),
    M("nearby_dir", "info->Point,\n                                                fwd);",
      "info->Point,\n                                                !fwd);"),
    M("nearby_no_inc", "        n++;\n    }\n    return 0;\n}\n", "    }\n    return 0;\n}\n"),
    M("nearby_end_n", "        n++;\n    }\n    return 0;\n}\n",
      "        n++;\n    }\n    return n;\n}\n"),
]

EQUIVALENT = {
    "contain_no_empty":
        "the look only runs with the start's route on the deque (pushed, "
        "or the deque already full), and ReturnToLastBranch answers 1 only "
        "with the branch's route at the back, so the deque is never empty "
        "there; the test is the image's own (0x001cc4ec)",
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
    base = model(lines).lines
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
        todo, SOURCES, "routeplan_test",
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
        t0 = time.monotonic()
        m = model(lines)
        got = m.lines
        took = time.monotonic() - t0
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
    print("model %.0f s; %s" % (took, " ".join(
        "%s=%d" % kv for kv in sorted(m.stats.items()))))
    print("%d ops, %d lines, %d differ" % (len(lines), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
