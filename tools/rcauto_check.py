#!/usr/bin/env python3
"""Cross-check 3DS Files/source/rcauto.c, the race coordinator's auto
replay, against the retail image, SLES_507.31 (TASKS 72g-4).

**The model** is retail's RaceCoordinator::RCStateAutoReplayCallback
(0x0014b848), SetUpAutoReplay (0x0014c0f8), CleanUpAutoReplay
(0x0014c148), CheckAutoReplayCam (0x0014c1f0) and SetUpAutoReplayCam
(0x0014c2d8), run in retail_model.RetailEmu. The harness
(tools/src/rcauto_test.c) runs rcauto.c.

**The stubs** print what they are asked, on both sides: the
ReplayManager's TakeSnapshot (0x0013e9f0), RestoreSnapshot by name
(0x0013e748) and DeleteSnapshot (0x0013e790); ChangeState (0x00149520)
and SendMessage (0x00149650); SetFlailerScreenVisibility (0x0014cbf8);
Player's DisableCameraMovers (0x00177558) and EnableCameraMovers
(0x001774a8); the type-changed handlers' reinstall (0x001543f0);
Car::GetRoutePoint (0x001332d8); PreviewRoute's constructor and
destructor (0x00164630, 0x00164848) and PreviewRoutePoint::GetPosition
(0x00164428); TrackPathCoordinate's constructor from a place
(0x002086f0); bMalloc and bFree; and TrackCarCameraMover's constructor
(0x00159130), which prints the camera record and the shake it is handed,
and its destructor (0x00159490).

**Differences made equal by hand.**

- Retail deletes the camera mover through its vtable, with 3; the port
  calls the mover's Destroy and then bFree. The model's stub at the
  destructor prints the destroy and, for the 1 bit, the free.
- Retail frees the record and the FOV table with __builtin_delete and
  __builtin_vec_delete, which jump to bFree, the model's stub.
- The bank points' and the FOV entries' fourth lane is the stack's in
  retail and 0 in the port; neither side prints it, nor the eye points'.
- The TrackPathCoordinates' destructors are retail's alone; the model's
  stub prints nothing.
- Retail reads a NULL highlight car's place from low memory, which the
  model zeroes; the port answers 0.
- The incident's TrackPathCoordinate gets mIncidentPoint's word as its x:
  a model address in retail, a host pointer's low word in the port. Both
  print TP for the route point.
- A call that would read through NULL is not made, on both sides: a
  rewind with no route, record or arrays, ACTIVATE on another
  pRaceCoordinator with no route on this one ("unsafe"), and the camera
  set up with no route ("no route").

**The script** sends every message in and out of range; sets up the
incident with each car, view and route point; cleans up every mix of
the six objects, on both coordinators; checks the route over each
answer of the constructor, point count and owner; sets the camera up
over each route, direction and pair of TrackPathCoordinates; activates
over each answer of the three snapshots and the route, from both
pRaceCoordinators; ticks across the capture's end and through the
rewinds, with each push; runs whole replays; and then random mixes.

    python tools/rcauto_check.py
    python tools/rcauto_check.py --mutate [--only a,b]
    python tools/rcauto_check.py --dump out/rcauto
"""
import argparse
import itertools
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

HARNESS = "tools/src/rcauto_test.c"
RA = "3DS Files/source/rcauto.c"
RH = "3DS Files/source/rcauto.h"
SOURCES = [HARNESS, RA]
HARNESS_TIMEOUT = 120

GP = retail_model.RETAIL_GP
P_REPLAY = GP - 22440
P_RC = GP - 22216               # pRaceCoordinator
PLAYERS = GP - 20928            # Player::pPlayersByIndex, two of them
NUM_PLAYERS = GP - 20920
WORLD_LOOP = GP - 19552         # WorldLoopCounter
RACE_PARAMS = 0x0031a898        # TheRaceParameters, TrackDirection at 12

F_CALLBACK = 0x0014b848
F_SETUP = 0x0014c0f8
F_CLEANUP = 0x0014c148
F_CHECK = 0x0014c1f0
F_SETUP_CAM = 0x0014c2d8

S_RESTORE_NAMED = 0x0013e748
S_DELETE_NAMED = 0x0013e790
S_TAKE = 0x0013e9f0
S_CHANGE = 0x00149520
S_SEND = 0x00149650
S_SCREEN = 0x0014cbf8
S_DISABLE = 0x00177558
S_ENABLE = 0x001774a8
S_HANDLERS = 0x001543f0
S_ROUTE_POINT = 0x001332d8
S_ROUTE_CTOR = 0x00164630
S_ROUTE_DTOR = 0x00164848
S_POSITION = 0x00164428
S_TPC = 0x002086f0
S_TPC_DTOR = 0x00208748
S_MALLOC = 0x002577c0
S_FREE = 0x00257850
S_MOVER_CTOR = 0x00159130
S_MOVER_DTOR = 0x00159490

NUM_PTS = 16
PT_SIZE = 24                    # PreviewRoutePoint
TRP_SIZE = 64                   # room for a TrackRoutePoint's widths
SLACK = 512
FILL = 0x3c
DUMP_VERTS = 12
SHAKE_SIZE = 560
MOVER_SIZE = 1136
MOVER_VTBL = 40                 # where the mover keeps its vtable


def fbits(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def clamp16(n):
    return 0 if n < 0 else 16 if n > 16 else n


# ================================================================= the model


class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        self.rc = self.zalloc(256)
        self.rc2 = self.zalloc(256)
        self.rm = self.zalloc(256)
        self.players = self.zalloc(2 * 256)
        self.cars = self.zalloc(2 * 256)
        self.snap = self.zalloc(64)
        self.tp = self.zalloc(64)
        self.pts = self.zalloc(NUM_PTS * PT_SIZE)
        self.trp = self.zalloc(NUM_PTS * TRP_SIZE)
        self.om = self.zalloc(MOVER_SIZE)
        self.ocd = self.zalloc(256)
        self.ofov = self.zalloc(64 * 16)
        self.oroute = self.zalloc(32)
        self.obank = self.zalloc(48 * 16)
        self.oeye = self.zalloc(48 * 16)
        self.vtbl = self.zalloc(16)
        e.put32(self.vtbl + 12, S_MOVER_DTOR)
        e.write(0, bytes(256))
        e.put32(P_REPLAY, self.rm)
        e.put32(P_RC, self.rc)
        e.put32(NUM_PLAYERS, 0)
        e.put32(WORLD_LOOP, 0)
        e.put32(RACE_PARAMS + 12, 0)
        for i in range(2):
            e.put32(PLAYERS + 4 * i, self.players + 256 * i)
        for i in range(NUM_PTS):
            e.put32(self.pts + PT_SIZE * i + 4, self.trp + TRP_SIZE * i)
            e.put32(self.trp + TRP_SIZE * i + 24, fbits(2.5 + i))
            e.put32(self.trp + TRP_SIZE * i + 28, fbits(1.75 + 0.5 * i))
        self.blocks = {}
        self.oroute_n = 0
        self.ans = dict(take=0, auto=0, ir=0, present=0)
        self.rp_on = 0
        self.route_n = 0
        self.route_ret = 0
        self.tpcs = []
        self.next_tpc = 0

        for a, fn in ((S_RESTORE_NAMED, self.restore_named),
                      (S_DELETE_NAMED, self.delete_named),
                      (S_TAKE, self.take), (S_CHANGE, self.change),
                      (S_SEND, self.send), (S_SCREEN, self.screen),
                      (S_DISABLE, self.ptr_say("disable")),
                      (S_ENABLE, self.ptr_say("enable")),
                      (S_HANDLERS, self.handlers),
                      (S_ROUTE_POINT, self.route_point),
                      (S_ROUTE_CTOR, self.route_ctor),
                      (S_ROUTE_DTOR, self.route_dtor),
                      (S_POSITION, self.position), (S_TPC, self.tpc),
                      (S_TPC_DTOR, lambda e: None),
                      (S_MALLOC, self.malloc), (S_FREE, self.free),
                      (S_MOVER_CTOR, self.mover_ctor),
                      (S_MOVER_DTOR, self.mover_dtor)):
            e.stub(a, fn)

    def zalloc(self, n):
        p = self.e.alloc(n, 16)
        self.e.write(p, bytes(n))
        return p

    def emit(self, s):
        self.out.append(s)

    def cstr(self, a, n=64):
        if a == 0:
            return "NULL"
        b = bytearray()
        mem = self.e.mem
        while len(b) < n and mem[a]:
            b.append(mem[a])
            a += 1
        return b.decode("latin-1")

    def arg(self, i):
        return self.e.reg[4 + i] & M32

    def sarg(self, i):
        return s32(self.e.reg[4 + i])

    def label(self, p):
        p &= M32
        if p == 0:
            return "NULL"
        named = {self.rc: "RC", self.rc2: "RC2", self.rm: "RM",
                 self.tp: "TP", self.pts: "PTS", self.om: "OM",
                 self.ocd: "OCD", self.ofov: "OFOV", self.oroute: "OROUTE",
                 self.obank: "OBANK", self.oeye: "OEYE", self.snap: "S0"}
        if p in named:
            return named[p]
        for i in range(2):
            if p == self.players + 256 * i:
                return "P%d" % i
            if p == self.cars + 256 * i:
                return "C%d" % i
        if p in self.blocks:
            return "B%d" % self.blocks[p]
        return "%d" % s32(p)

    def known(self, p):
        return p != 0 and (p in self.blocks
                           or p in (self.ofov, self.obank, self.oeye))

    def verts(self, what, v, n):
        u = self.e.u32
        self.emit("  " + what + "".join(
            " %08x,%08x,%08x" % (u(v + 16 * i), u(v + 16 * i + 4),
                                 u(v + 16 * i + 8)) for i in range(n)))

    # ---- the stubs

    def ptr_say(self, what):
        def fn(e):
            self.emit("  %s %s" % (what, self.label(self.arg(0))))
        return fn

    def take(self, e):
        self.emit("  take %s %s" % (self.label(self.arg(0)),
                                    self.cstr(self.arg(1))))
        return self.snap if self.ans["take"] else 0

    def restore_named(self, e):
        name = self.cstr(self.arg(1))
        self.emit("  restore %s %s" % (self.label(self.arg(0)), name))
        return {"AUTO_REPLAY_SNAPSHOT": self.ans["auto"],
                "INSTANT_REPLAY": self.ans["ir"],
                "THE_PRESENT": self.ans["present"]}.get(name, 0)

    def delete_named(self, e):
        self.emit("  delete %s %s" % (self.label(self.arg(0)),
                                      self.cstr(self.arg(1))))
        return 0

    def change(self, e):
        self.emit("  change %s %d" % (self.label(self.arg(0)), self.sarg(1)))

    def send(self, e):
        self.emit("  send %s %d %d" % (self.label(self.arg(0)),
                                       self.sarg(1), self.sarg(2)))

    def screen(self, e):
        self.emit("  screen %08x %d" % (self.arg(0), self.sarg(1)))

    def handlers(self, e):
        self.emit("  type handlers")

    def route_point(self, e):
        self.emit("  route point %s %d" % (self.label(self.arg(0)),
                                           self.sarg(1)))
        return self.tp if self.rp_on else 0

    def route_ctor(self, e):
        pr = self.arg(0)
        self.emit("  route ctor %s %s %08x %08x" % (
            self.label(pr), self.label(self.arg(1)), e.fpr[12] & M32,
            e.fpr[13] & M32))
        if not self.route_ret:
            return 0
        e.put32(pr, self.pts)
        e.put32(pr + 4, self.route_n)
        return pr

    def route_dtor(self, e):
        self.emit("  route dtor %s %d" % (self.label(self.arg(0)),
                                          self.sarg(1)))

    def position(self, e):
        pt, o = self.arg(0), self.arg(1)
        along, across = e.fpr[12] & M32, e.fpr[13] & M32
        off = pt - self.pts
        if not (0 <= off < NUM_PTS * PT_SIZE and off % PT_SIZE == 0):
            self.emit("  pos ? %08x %08x" % (along, across))
            return
        k = off // PT_SIZE
        self.emit("  pos %d %08x %08x" % (k, along, across))
        e.write(o, struct.pack("<4f", 10.0 * k + 1.0, -3.0 * k + 2.0,
                               0.25 * k + 3.0, k + 0.5))

    def tpc(self, e):
        c, pos = self.arg(0), self.arg(1)
        x, y = e.u32(pos), e.u32(pos + 4)
        if x == self.tp:
            self.emit("  tpc TP %08x" % y)
        else:
            self.emit("  tpc %08x %08x" % (x, y))
        if self.next_tpc < len(self.tpcs):
            r, d = self.tpcs[self.next_tpc]
            self.next_tpc += 1
        else:
            r, d = 0, 0
        e.put32(c + 16, r)
        e.put32(c + 20, d)

    def malloc(self, e):
        size = self.sarg(0)
        p = e.alloc(size + SLACK, 16)
        e.write(p, bytes([FILL]) * (size + SLACK))
        self.blocks[p] = len(self.blocks)
        self.emit("  malloc %d %s %d %d -> %s" % (
            size, self.cstr(self.arg(1)), self.sarg(2), self.sarg(3),
            self.label(p)))
        return p

    def free(self, e):
        self.emit("  free %s" % self.label(self.arg(0)))

    def mover_dtor(self, e):
        m = self.arg(0)
        self.emit("  mover dtor %s" % self.label(m))
        if self.sarg(1) & 1:
            self.emit("  free %s" % self.label(m))

    def print_cd(self, cd):
        e = self.e

        def u(o):
            return e.u32(cd + o)

        def i(o):
            return s32(e.u32(cd + o))

        def lb(o):
            return self.label(e.u32(cd + o))

        self.emit("  cd %d %s %d %08x %08x %08x %08x %08x %d %d %08x %08x %08x"
                  " %08x %d %s %d %s %d %s %d %s %s %d %s" % (
                      i(0), lb(4), i(8), u(12), u(16), u(20), u(24), u(28),
                      i(32), i(36), u(40), u(44), u(48), u(52), i(56),
                      lb(60), i(64), lb(68), i(72), lb(76), i(80), lb(84),
                      lb(88), i(92), lb(96)))
        self.emit("  cd2 %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x"
                  " %08x %08x %d %08x %d %d" % (
                      u(100), u(104), u(108), u(112), u(116), u(120),
                      u(124), u(128), u(132), u(136), u(140), u(144),
                      i(148), u(152), i(156), i(160)))
        if self.known(u(60)):
            self.verts("fov", u(60), 32)
        if self.known(u(84)):
            self.verts("eye", u(84), clamp16(i(80)))
        if self.known(u(88)):
            self.verts("bank", u(88), clamp16(i(80)))

    def mover_ctor(self, e):
        m, cd = self.arg(0), self.arg(3)
        shake, focus = e.reg[8] & M32, s32(e.reg[9])
        self.emit("  mover ctor %s %d %s %s" % (
            self.label(m), self.sarg(1), self.label(self.arg(2)),
            self.label(cd)))
        if cd:
            self.print_cd(cd)
        nz = sum(1 for b in e.read(shake, SHAKE_SIZE) if b)
        self.emit("  shake %d %d focus %d" % (s32(e.u32(shake + 40)), nz,
                                              focus))
        e.put32(m + MOVER_VTBL, self.vtbl)
        return m

    # ---- the ops

    def call(self, fn, *args):
        return self.e.call(fn, *args, limit=400000)

    def coord(self, t):
        return self.rc2 if t == 2 else self.rc

    def car(self, c):
        return {1: self.cars, 2: self.cars + 256}.get(c, 0)

    def set_old(self, rc, v):
        e = self.e
        if v[1]:
            e.write(self.om, bytes(MOVER_SIZE))
            e.put32(self.om + MOVER_VTBL, self.vtbl)
        e.put32(rc + 52, self.om if v[1] else 0)
        if v[2]:
            e.write(self.ocd, bytes(256))
        e.put32(rc + 56, self.ocd if v[2] else 0)
        if v[3]:
            e.write(self.ofov, bytes(64 * 16))
        e.put32(rc + 120, self.ofov if v[3] else 0)
        if v[4]:
            e.write(self.oroute, bytes(32))
            e.put32(self.oroute, self.pts)
            e.put32(self.oroute + 4, self.oroute_n)
        e.put32(rc + 136, self.oroute if v[4] else 0)
        if v[5]:
            e.write(self.obank, bytes(48 * 16))
        e.put32(rc + 116, self.obank if v[5] else 0)
        if v[6]:
            e.write(self.oeye, bytes(48 * 16))
        e.put32(rc + 112, self.oeye if v[6] else 0)

    def dump_coord(self, name, rc):
        e = self.e
        u = e.u32
        self.emit("  %s rew %d mover %s cd %s ip %s view %d car %s car2 %s" % (
            name, s32(u(rc + 48)), self.label(u(rc + 52)),
            self.label(u(rc + 56)), self.label(u(rc + 60)), s32(u(rc + 132)),
            self.label(u(rc + 124)), self.label(u(rc + 128))))
        self.emit("  %s ic %08x %08x %08x %08x fin %08x %08x %08x %08x"
                  " start %08x %08x %08x %08x" % (
                      (name,) + tuple(u(rc + o) for o in range(64, 112, 4))))
        r = u(rc + 136)
        s = "  %s eye %s bank %s fov %s route %s" % (
            name, self.label(u(rc + 112)), self.label(u(rc + 116)),
            self.label(u(rc + 120)), self.label(r))
        if r:
            s += " n %d pts %s" % (s32(u(r + 4)), self.label(u(r)))
        self.emit(s)
        if self.known(u(rc + 112)):
            self.verts("eyes", u(rc + 112), DUMP_VERTS)
        if self.known(u(rc + 116)):
            self.verts("banks", u(rc + 116), DUMP_VERTS)

    def tick_unsafe(self):
        e = self.e
        rc = self.rc
        if s32(e.u32(self.rm + 84) - e.u32(WORLD_LOOP)) > 0:
            return False
        if s32(e.u32(rc + 48) + 1) >= 3:
            return False
        r = e.u32(rc + 136)
        if r == 0 or e.u32(rc + 56) == 0:
            return True
        return s32(e.u32(r + 4)) > 0 and (e.u32(rc + 116) == 0
                                          or e.u32(rc + 112) == 0)

    def op(self, a):
        e = self.e
        op = a[0]
        if op == "tag":
            return
        v = [int(x, 0) for x in a[1:]]
        if op == "car":
            c = self.cars + 256 * v[0] + 96
            for k in range(4):
                e.put32(c + 4 * k, v[1 + k])
        elif op == "prc":
            e.put32(P_RC, self.coord(v[0]))
        elif op == "players":
            e.put32(NUM_PLAYERS, v[0])
        elif op == "ans":
            for k, x in zip(("take", "auto", "ir", "present"), v):
                self.ans[k] = x
        elif op == "rp":
            self.rp_on = v[0]
        elif op == "route":
            self.route_n, self.route_ret = v[0], v[1]
        elif op == "width":
            t = self.trp + TRP_SIZE * v[0]
            e.put32(t + 24, v[1])
            e.put32(t + 28, v[2])
        elif op == "tpcs":
            self.tpcs = [(v[i], v[i + 1]) for i in range(0, len(v) - 1, 2)]
            self.next_tpc = 0
        elif op == "loops":
            e.put32(self.rm + 84, v[0])
            e.put32(WORLD_LOOP, v[1])
        elif op == "dir":
            e.put32(RACE_PARAMS + 12, v[0])
        elif op == "old":
            self.set_old(self.coord(v[0]), v)
        elif op == "oroute":
            self.oroute_n = v[0]
            e.put32(self.oroute + 4, v[0])
        elif op == "ocd":
            e.put32(self.ocd + 136, v[0])
        elif op == "rewinds":
            e.put32(self.coord(v[0]) + 48, v[1])
        elif op == "hl":
            rc = self.coord(v[0])
            e.put32(rc + 124, self.car(v[1]))
            e.put32(rc + 128, self.car(v[2]))
            e.put32(rc + 132, v[3])
        elif op == "msg":
            m = v[0]
            if ((m == 3 and self.tick_unsafe())
                    or (m == 1 and e.u32(P_RC) != self.rc
                        and e.u32(self.rc + 136) == 0)):
                self.emit("  unsafe")
                return
            r = self.call(F_CALLBACK, self.rc, m, v[1])
            self.emit("  -> %d" % s32(r))
        elif op == "setup":
            self.call(F_SETUP, self.rc, self.car(v[0]), self.car(v[1]), v[2])
        elif op == "cleanup":
            self.call(F_CLEANUP, self.coord(v[0]))
        elif op == "check":
            r = self.call(F_CHECK, self.coord(v[0]))
            self.emit("  -> %d" % s32(r))
        elif op == "setupcam":
            rc = self.coord(v[0])
            if e.u32(rc + 136) == 0:
                self.emit("  no route")
                return
            self.call(F_SETUP_CAM, rc)
        elif op == "dump":
            self.dump_coord("RC", self.rc)
            self.dump_coord("RC2", self.rc2)
        else:
            self.emit("  unknown op %s" % op)

    def run(self, lines):
        e = self.e
        for line in lines:
            self.emit("> " + line)
            sp = e.reg[29]
            self.op(line.split("|"))
            e.reg[29] = sp
        return self.out


# ================================================================ the script

ACTIVATE, UNACTIVATE, TICK, SKIP, TAKE_AUTO = 1, 2, 3, 4, 13
MSGS = list(range(1, 14))
ODD_MSGS = [0, -1, 14, 15, 99, -100, 0x7fffffff, -0x80000000]

PLACES = [(1.5, -2.25, 3.0, 1.0), (100.0, 200.5, -7.75, 0.0),
          (-0.0, 0.0, 12.5, 2.0), (1e6, -1e-3, 0.1, 1.0),
          (-55.5, 33.25, 0.0, -1.0), (0.3, 0.7, -0.9, 0.5)]
RATIOS = [0.0, 0.25, 0.5, 0.999, 1.0, -0.1, 1.5, 0.125]
DISTANCES = [0.0, 120.5, 3000.0, -50.0, 1e4, 7.25]
WIDTHS = [0.0, 3.5, -2.0, 10.25, 0.1]
PUSHES = [0.0, -0.0, 1.0, -2.5, 0.3, 1e-3, 100.0]


def fx(x):
    return "0x%08x" % fbits(x)


class Script(object):
    def __init__(self):
        self.lines = []

    def add(self, *lines):
        self.lines.extend(lines)

    def tag(self, text):
        self.add("tag|" + text)

    def car(self, k, place):
        self.add("car|%d|%s" % (k, "|".join(fx(x) for x in place)))

    def ans(self, take, auto, ir, present):
        self.add("ans|%d|%d|%d|%d" % (take, auto, ir, present))

    def tpcs(self, *pairs):
        self.add("tpcs" + "".join("|%s|%s" % (fx(r), fx(d))
                                  for r, d in pairs))

    def old(self, t, mover=0, cd=0, fov=0, route=0, bank=0, eye=0):
        self.add("old|%d|%d|%d|%d|%d|%d|%d" % (t, mover, cd, fov, route,
                                               bank, eye))

    def hl(self, t, c1, c2, view):
        self.add("hl|%d|%d|%d|%d" % (t, c1, c2, view))

    def width(self, k, left, right):
        self.add("width|%d|%s|%s" % (k, fx(left), fx(right)))

    def msg(self, m, param=0):
        self.add("msg|%d|%d" % (m, param), "dump")

    def do(self, what, t):
        self.add("%s|%d" % (what, t), "dump")


def random_tpcs(sc, rnd, n=3):
    sc.tpcs(*[(rnd.choice(RATIOS), rnd.choice(DISTANCES))
              for _ in range(n)])


def script():
    sc = Script()
    rnd = random.Random(7240)
    sc.add("players|2")
    sc.car(0, PLACES[0])
    sc.car(1, PLACES[1])
    sc.ans(0, 0, 0, 0)
    sc.add("loops|10|0")

    sc.tag("every message, idle")
    for m in ODD_MSGS + MSGS:
        sc.msg(m, 5)

    sc.tag("set up the incident")
    for c1 in (1, 2):
        for c2 in (0, 1, 2):
            for view in (0, 1, -1, 7):
                for rp in (0, 1):
                    sc.car(c1 - 1, rnd.choice(PLACES))
                    sc.add("rp|%d" % rp)
                    sc.add("setup|%d|%d|%d" % (c1, c2, view), "dump")

    sc.tag("clean up each mix")
    for t in (1, 2):
        for n in (0, 5):
            sc.add("oroute|%d" % n)
            for mask in range(64):
                sc.old(t, *[(mask >> k) & 1 for k in range(6)])
                sc.do("cleanup", t)

    sc.tag("check the route")
    for t in (1, 2):
        for ret in (0, 1):
            for n in (0, 1, 4, 5, 6, 16):
                for c in (0, 1, 2):
                    sc.old(t, *[rnd.randrange(2) for _ in range(6)])
                    sc.hl(t, c, rnd.randrange(3), rnd.randrange(-1, 3))
                    sc.add("route|%d|%d" % (n, ret))
                    random_tpcs(sc, rnd, rnd.choice((0, 1, 2, 3)))
                    sc.do("check", t)
    sc.tag("check twice")
    sc.add("route|6|1")
    for t in (1, 2, 1):
        random_tpcs(sc, rnd)
        sc.do("check", t)
        random_tpcs(sc, rnd)
        sc.do("check", t)

    sc.tag("set the camera up")
    for t in (1, 2):
        for d in (0, 1, 2, -1):
            for n in (-1, 0, 1, 5, 9, 16):
                sc.add("oroute|%d" % n)
                sc.old(t, route=1)
                sc.hl(t, rnd.randrange(3), rnd.randrange(3),
                      rnd.randrange(-1, 4))
                sc.add("dir|%d" % d)
                for k in rnd.sample(range(NUM_PTS), 3):
                    sc.width(k, rnd.choice(WIDTHS), rnd.choice(WIDTHS))
                random_tpcs(sc, rnd, rnd.choice((1, 2, 3, 3, 3)))
                sc.do("setupcam", t)
                sc.do("cleanup", t)
    sc.tag("the camera after a check")
    for d in (0, 1):
        for ip in (0, 1):
            sc.car(0, rnd.choice(PLACES))
            sc.add("rp|%d" % ip, "setup|1|2|3", "dir|%d" % d,
                   "route|7|1")
            random_tpcs(sc, rnd, 2)
            sc.do("check", 1)
            random_tpcs(sc, rnd)
            sc.do("setupcam", 1)
    sc.tag("no route")
    sc.old(1)
    sc.old(2)
    sc.do("setupcam", 1)
    sc.do("setupcam", 2)
    sc.add("dir|0")

    sc.tag("activate")
    sc.add("oroute|6")
    for prc in (1, 2):
        for take, auto, ir in itertools.product((0, 1), repeat=3):
            for n, ret in ((6, 1), (3, 1), (0, 0)):
                for players in (0, 1, 2):
                    sc.add("prc|%d" % prc, "players|%d" % players)
                    sc.old(1, route=rnd.randrange(2))
                    sc.old(2)
                    sc.hl(1, 1, 2, rnd.randrange(3))
                    sc.hl(2, 2, 1, 5)
                    sc.car(0, rnd.choice(PLACES))
                    sc.car(1, rnd.choice(PLACES))
                    sc.ans(take, auto, ir, 1)
                    sc.add("route|%d|%d" % (n, ret))
                    random_tpcs(sc, rnd, 5)
                    sc.msg(ACTIVATE, rnd.randrange(-2, 3))
                    sc.msg(UNACTIVATE)
    sc.tag("activate with no highlight car")
    sc.add("prc|1", "players|1", "route|5|1")
    sc.ans(1, 1, 1, 1)
    sc.hl(1, 0, 0, 2)
    random_tpcs(sc, rnd, 5)
    sc.msg(ACTIVATE)
    sc.msg(UNACTIVATE)

    sc.tag("tick")
    sc.add("prc|1", "players|2")
    sc.ans(1, 1, 1, 1)
    for end, world in ((10, 0), (1, 0), (0, 0), (0, 1), (-5, 3),
                       (0x7fffffff, -1), (-0x80000000, 1), (5, 5),
                       (-1, 0x7fffffff)):
        for rew in (-2, -1, 0, 1, 2, 3, 5):
            sc.hl(1, 1, 2, rnd.randrange(3))
            sc.add("route|%d|1" % rnd.choice((5, 8, 16)))
            random_tpcs(sc, rnd, 5)
            sc.msg(ACTIVATE)
            sc.add("loops|%d|%d" % (end, world),
                   "rewinds|1|%d" % rew)
            sc.msg(TICK)
            sc.msg(UNACTIVATE)
    sc.tag("tick on the old objects")
    for push in PUSHES:
        for rew in (0, 1, 2):
            for n in (0, 4, 16):
                sc.add("oroute|%d" % n)
                sc.old(1, mover=rnd.randrange(2), cd=1, route=1, bank=1,
                       eye=1)
                sc.add("ocd|%s" % fx(push), "rewinds|1|%d" % rew,
                       "loops|0|0")
                sc.hl(1, rnd.randrange(3), rnd.randrange(3),
                      rnd.randrange(4))
                sc.msg(TICK)
    sc.tag("tick with nothing to rewind into")
    for mask in range(16):
        sc.add("oroute|3")
        sc.old(1, 0, mask & 1, 0, (mask >> 1) & 1, (mask >> 2) & 1,
               (mask >> 3) & 1)
        sc.add("rewinds|1|0", "loops|0|0")
        sc.msg(TICK)
    sc.add("oroute|0")
    for mask in range(4):
        sc.old(1, 0, 1, 0, 1, mask & 1, (mask >> 1) & 1)
        sc.add("rewinds|1|1")
        sc.msg(TICK)

    sc.tag("whole replays")
    for prc in (1, 2):
        for n in (5, 9):
            sc.add("prc|%d" % prc, "players|%d" % rnd.randrange(3))
            sc.old(1, route=1)
            sc.add("oroute|%d" % n, "route|%d|1" % n, "loops|50|0")
            sc.ans(1, 1, 1, 1)
            sc.add("rp|1")
            sc.car(0, rnd.choice(PLACES))
            sc.add("setup|1|2|%d" % rnd.randrange(3))
            random_tpcs(sc, rnd, 5)
            sc.msg(ACTIVATE)
            sc.msg(TICK)
            for _ in range(4):
                sc.add("loops|50|60")
                sc.msg(TICK)
            sc.msg(SKIP, 1)
            sc.msg(TAKE_AUTO)
            sc.msg(UNACTIVATE)
    sc.add("prc|1")

    random_mix(sc, random.Random(7241), 2500)
    return sc.lines


def random_mix(sc, rnd, n):
    sc.tag("random")
    for _ in range(n):
        r = rnd.random()
        if r < 0.04:
            sc.car(rnd.randrange(2), rnd.choice(PLACES))
        elif r < 0.07:
            sc.add("prc|%d" % rnd.choice((1, 1, 2)))
        elif r < 0.10:
            sc.add("players|%d" % rnd.choice((-1, 0, 1, 2, 2)))
        elif r < 0.16:
            sc.ans(*[rnd.choice((0, 1, 1)) for _ in range(4)])
        elif r < 0.18:
            sc.add("rp|%d" % rnd.randrange(2))
        elif r < 0.23:
            sc.add("route|%d|%d" % (rnd.choice((0, 3, 4, 5, 6, 10, 16)),
                                    rnd.choice((0, 1, 1, 1))))
        elif r < 0.25:
            sc.width(rnd.randrange(NUM_PTS), rnd.choice(WIDTHS),
                     rnd.choice(WIDTHS))
        elif r < 0.30:
            random_tpcs(sc, rnd, rnd.randrange(6))
        elif r < 0.36:
            end = rnd.randrange(-3, 4)
            sc.add("loops|%d|%d" % (end, end + rnd.randrange(-2, 3)))
        elif r < 0.38:
            sc.add("dir|%d" % rnd.choice((0, 0, 1, 1, 2)))
        elif r < 0.43:
            sc.add("oroute|%d" % rnd.choice((0, 2, 5, 8, 16, -1)))
            sc.old(rnd.choice((1, 1, 2)),
                   *[rnd.choice((0, 1, 1)) for _ in range(6)])
        elif r < 0.45:
            sc.add("ocd|%s" % fx(rnd.choice(PUSHES)))
        elif r < 0.49:
            sc.add("rewinds|%d|%d" % (rnd.choice((1, 1, 2)),
                                      rnd.randrange(-3, 5)))
        elif r < 0.53:
            sc.hl(rnd.choice((1, 1, 2)), rnd.randrange(3), rnd.randrange(3),
                  rnd.randrange(-1, 4))
        elif r < 0.56:
            sc.add("setup|%d|%d|%d" % (rnd.randrange(1, 3), rnd.randrange(3),
                                       rnd.randrange(-1, 4)), "dump")
        elif r < 0.60:
            sc.do("cleanup", rnd.choice((1, 1, 2)))
        elif r < 0.65:
            sc.do("check", rnd.choice((1, 1, 2)))
        elif r < 0.70:
            sc.do("setupcam", rnd.choice((1, 1, 2)))
        else:
            m = rnd.choice(MSGS + [ACTIVATE, ACTIVATE, UNACTIVATE, TICK,
                                   TICK, TICK, SKIP, 0, 14])
            sc.msg(m, rnd.randrange(-3, 4))


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


# ================================================================= build


def build_harness(tmp, name="rcauto_test"):
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


def encode(lines):
    return NL.join(lines) + NL


# ============================================================ the mutations


def M(name, before, after, rel=RA):
    return (name, rel, before, after)


MUTATIONS = [
    # The constants.
    M("pool", "#define RC_POOL            16",
      "#define RC_POOL            17"),
    M("line-route", "#define RC_LINE_ROUTE      2504",
      "#define RC_LINE_ROUTE      2505"),
    M("line-cd", "#define RC_LINE_CD         2516",
      "#define RC_LINE_CD         2515"),
    M("line-fov", "#define RC_LINE_FOV        2517",
      "#define RC_LINE_FOV        2518"),
    M("line-bank", "#define RC_LINE_BANK       2524",
      "#define RC_LINE_BANK       2525"),
    M("line-eye", "#define RC_LINE_EYE        2525",
      "#define RC_LINE_EYE        2524"),
    M("bars", "#define RC_AUTO_BARS_SCREEN 0x49c15518u",
      "#define RC_AUTO_BARS_SCREEN 0x49c15519u"),
    M("rewinds-2", "#define RC_AUTO_REWINDS    3",
      "#define RC_AUTO_REWINDS    2"),
    M("rewinds-4", "#define RC_AUTO_REWINDS    3",
      "#define RC_AUTO_REWINDS    4"),
    M("radius", "#define RC_AUTO_ROUTE_RADIUS 100.0f",
      "#define RC_AUTO_ROUTE_RADIUS 101.0f"),
    M("points-4", "#define RC_AUTO_ROUTE_POINTS 5",
      "#define RC_AUTO_ROUTE_POINTS 4"),
    M("points-6", "#define RC_AUTO_ROUTE_POINTS 5",
      "#define RC_AUTO_ROUTE_POINTS 6"),
    M("eye-height", "#define RC_AUTO_EYE_HEIGHT 5.0f",
      "#define RC_AUTO_EYE_HEIGHT 4.0f"),
    M("fov", "#define RC_AUTO_FOV        40.0f",
      "#define RC_AUTO_FOV        45.0f"),
    M("near", "#define RC_AUTO_NEAR_CLIP  0.5f",
      "#define RC_AUTO_NEAR_CLIP  0.25f"),
    M("far", "#define RC_AUTO_FAR_CLIP   5000.0f",
      "#define RC_AUTO_FAR_CLIP   4000.0f"),
    M("vert-comp", "#define RC_AUTO_VERT_COMP  0.2f",
      "#define RC_AUTO_VERT_COMP  0.25f"),
    M("name-present", '"THE_PRESENT"', '"THE_PRESENTS"', rel=RH),
    M("name-auto", '"AUTO_REPLAY_SNAPSHOT"', '"AUTO_REPLAY_SNAPSHOTS"',
      rel=RH),
    M("name-ir", '"INSTANT_REPLAY"', '"INSTANT_REPLAYS"', rel=RH),
    M("name-file", '"..\\\\indep\\\\src\\\\racecoordinator.cpp"',
      '"..\\\\indep\\\\src\\\\racecoordinater.cpp"', rel=RH),
    M("name-mover", '"TrackCarCameraMover"', '"TrackCarCameraMovers"',
      rel=RH),
    M("size-route", "#define RC_AUTO_ROUTE_SIZE      24",
      "#define RC_AUTO_ROUTE_SIZE      28", rel=RH),
    M("size-cd", "#define RC_AUTO_CD_SIZE         164",
      "#define RC_AUTO_CD_SIZE         168", rel=RH),
    M("size-mover", "#define RC_AUTO_MOVER_SIZE      1136",
      "#define RC_AUTO_MOVER_SIZE      1140", rel=RH),
    M("fov-entries", "#define RC_AUTO_FOV_ENTRIES     32",
      "#define RC_AUTO_FOV_ENTRIES     31", rel=RH),

    # The helpers.
    M("car-place", "return car != NULL ? car->State.Position : zero;",
      "return zero;"),
    M("shake-cvs", "    shake.NumCVs = 2;", "    shake.NumCVs = 3;"),
    M("shake-cvs-gone", "    shake.NumCVs = 2;", "    ;"),
    M("mover-view", "                                       rc->mViewID, car,",
      "                                       0, car,"),
    M("mover-focus", "(CameraDataItems *)rc->mpCD, &shake,\n"
      "                                       1);",
      "(CameraDataItems *)rc->mpCD, &shake,\n"
      "                                       0);"),
    M("mover-pool", "mem = bMalloc(RC_AUTO_MOVER_SIZE, RC_AUTO_MOVER_NAME, 0, RC_POOL);",
      "mem = bMalloc(RC_AUTO_MOVER_SIZE, RC_AUTO_MOVER_NAME, 1, RC_POOL);"),
    M("verts-along", "            pt, &o, 0.0f, left ? -pt->pPoint->LeftWidth : 0.0f);",
      "            pt, &o, 1.0f, left ? -pt->pPoint->LeftWidth : 0.0f);"),
    M("verts-left-sign", "left ? -pt->pPoint->LeftWidth : 0.0f",
      "left ? pt->pPoint->LeftWidth : 0.0f"),
    M("verts-left-right", "left ? -pt->pPoint->LeftWidth : 0.0f",
      "left ? -pt->pPoint->RightWidth : 0.0f"),
    M("verts-line", "left ? -pt->pPoint->LeftWidth : 0.0f",
      "left ? -pt->pPoint->LeftWidth : 1.0f"),
    M("verts-bank-x", "        bank->x = 0.0f;\n        bank->y = 0.0f;\n"
      "        bank->z = 0.0f;\n        bank->pad = 0.0f;\n"
      "        o.z = o.z + RC_AUTO_EYE_HEIGHT;\n"
      "        ((bVector3 *)rc->mpEyeVerts)[i] = o;\n    }\n}",
      "        bank->x = 1.0f;\n        bank->y = 0.0f;\n"
      "        bank->z = 0.0f;\n        bank->pad = 0.0f;\n"
      "        o.z = o.z + RC_AUTO_EYE_HEIGHT;\n"
      "        ((bVector3 *)rc->mpEyeVerts)[i] = o;\n    }\n}"),
    M("verts-lift", "        o.z = o.z + RC_AUTO_EYE_HEIGHT;\n"
      "        ((bVector3 *)rc->mpEyeVerts)[i] = o;\n    }\n}",
      "        o.y = o.y + RC_AUTO_EYE_HEIGHT;\n"
      "        ((bVector3 *)rc->mpEyeVerts)[i] = o;\n    }\n}"),
    M("verts-first", "    for (i = 0; i < r->nPoints; i++) {\n"
      "        const PreviewRoutePoint *pt = &r->pPoints[i];\n"
      "        bVector3 *bank = &((bVector3 *)rc->mpBankVerts)[i];\n"
      "        bVector3 o;\n\n        preview_route_point_get_position_at(\n",
      "    for (i = 1; i < r->nPoints; i++) {\n"
      "        const PreviewRoutePoint *pt = &r->pPoints[i];\n"
      "        bVector3 *bank = &((bVector3 *)rc->mpBankVerts)[i];\n"
      "        bVector3 o;\n\n        preview_route_point_get_position_at(\n"),

    # The rewind.
    M("rewind-names", "first ? RC_AUTO_INSTANT_REPLAY\n"
      "                                           : RC_AUTO_SNAPSHOT);",
      "first ? RC_AUTO_SNAPSHOT\n"
      "                                           : RC_AUTO_INSTANT_REPLAY);"),
    M("rewind-no-delete", "    if (rc->mpCameraMover != NULL)\n"
      "        delete_mover(rc->mpCameraMover);\n    route_verts",
      "    if (rc->mpCameraMover == NULL)\n"
      "        delete_mover(rc->mpCameraMover);\n    route_verts"),
    M("rewind-verts", "    route_verts(rc, first);", "    route_verts(rc, !first);"),
    M("rewind-flip", "        cd->EnterHorizComp = -cd->EnterHorizComp;",
      "        cd->EnterHorizComp = cd->EnterHorizComp;"),
    M("rewind-clear", "        cd->EnterHorizComp = 0.0f;",
      "        cd->EnterHorizComp = 1.0f;"),
    M("rewind-push-if", "    if (first)\n        cd->EnterHorizComp",
      "    if (!first)\n        cd->EnterHorizComp"),
    M("rewind-car", "    rc->mpCameraMover = make_mover(rc, rc->mpHighlightCar2);",
      "    rc->mpCameraMover = make_mover(rc, rc->mpHighlightCar);"),
    M("rewind-kept", "    rc->mpCameraMover = make_mover(rc, rc->mpHighlightCar2);",
      "    (void)make_mover(rc, rc->mpHighlightCar2);"),

    # The incident's place.
    M("incident-word", "    memcpy(&o->x, &bits, sizeof bits);",
      "    o->x = 0.0f;"),
    M("incident-y", "    o->y = rc->mIncidentCoord.x;",
      "    o->y = rc->mIncidentCoord.y;"),

    # SetUpAutoReplay.
    M("setup-car2", "    rc->mpHighlightCar2 = car2;", "    rc->mpHighlightCar2 = car;"),
    M("setup-view", "    rc->mViewID = viewID;", "    rc->mViewID = 0;"),
    M("setup-find", "    rc->mIncidentPoint = car_get_route_point(car, 1);",
      "    rc->mIncidentPoint = car_get_route_point(car, 0);"),
    M("setup-coord", "    rc->mIncidentCoord = car->State.Position;",
      "    rc->mIncidentCoord.x = car->State.Position.x;"),

    # CleanUpAutoReplay.
    M("clean-mover-kept", "        delete_mover(rc->mpCameraMover);\n"
      "    rc->mpCameraMover = NULL;",
      "        delete_mover(rc->mpCameraMover);\n    ;"),
    M("clean-mover-gone", "    if (rc->mpCameraMover != NULL)\n"
      "        delete_mover(rc->mpCameraMover);\n"
      "    rc->mpCameraMover = NULL;",
      "    rc->mpCameraMover = NULL;"),
    M("clean-cd-kept", "    rc->mpCD = NULL;\n    if (rc->mpFOVtable",
      "    ;\n    if (rc->mpFOVtable"),
    M("clean-cd-free", "        bFree(rc->mpCD);", "        ;"),
    M("clean-fov-kept", "    rc->mpFOVtable = NULL;", "    ;"),
    M("clean-fov-free", "        bFree(rc->mpFOVtable);", "        ;"),
    M("clean-route-flags", "preview_route_destroy((PreviewRoute *)rc->mpRoute, 3);",
      "preview_route_destroy((PreviewRoute *)rc->mpRoute, 1);"),
    M("clean-route-kept", "    rc->mpRoute = NULL;\n    if (rc->mpBankVerts",
      "    ;\n    if (rc->mpBankVerts"),
    M("clean-bank-kept", "    rc->mpBankVerts = NULL;", "    ;"),
    M("clean-bank-free", "        bFree(rc->mpBankVerts);", "        ;"),
    M("clean-eye-kept", "    rc->mpEyeVerts = NULL;", "    ;"),
    M("clean-eye-free", "        bFree(rc->mpEyeVerts);", "        ;"),
    M("clean-eye-test", "    if (rc->mpEyeVerts != NULL)\n        bFree",
      "    if (rc->mpBankVerts != NULL)\n        bFree"),

    # CheckAutoReplayCam.
    M("check-first-clean", "    racecoordinator_clean_up_auto_replay(rc);\n"
      "    trackpath_coord_init_at(&final",
      "    trackpath_coord_init_at(&final"),
    M("check-order", "    trackpath_coord_init_at(&final, (const bVector2 *)&rc->mFinalPosition);\n"
      "    trackpath_coord_init_at(&start, (const bVector2 *)&rc->mStartPosition);\n"
      "    length",
      "    trackpath_coord_init_at(&start, (const bVector2 *)&rc->mStartPosition);\n"
      "    trackpath_coord_init_at(&final, (const bVector2 *)&rc->mFinalPosition);\n"
      "    length"),
    M("check-length", "    length = final.DistanceAroundTrack - start.DistanceAroundTrack;",
      "    length = start.DistanceAroundTrack - final.DistanceAroundTrack;"),
    M("check-ratio", "    length = final.DistanceAroundTrack - start.DistanceAroundTrack;",
      "    length = final.RatioAroundTrack - start.RatioAroundTrack;"),
    M("check-car", "    r = preview_route_init((PreviewRoute *)mem, rc->mpHighlightCar,",
      "    r = preview_route_init((PreviewRoute *)mem, rc->mpHighlightCar2,"),
    M("check-points", "r->nPoints < RC_AUTO_ROUTE_POINTS",
      "r->nPoints <= RC_AUTO_ROUTE_POINTS"),
    M("check-fail-clean", "        racecoordinator_clean_up_auto_replay(rc);\n"
      "        return 0;", "        return 0;"),
    M("check-ret", "        return 0;\n    }\n    return 1;\n}",
      "        return 0;\n    }\n    return 2;\n}"),

    # SetUpAutoReplayCam.
    M("cam-fov-iso", "    cd->IsFOVIso = 0;", "    cd->IsFOVIso = 1;"),
    M("cam-type", "    cd->Type = 0;", "    cd->Type = 1;"),
    M("cam-name", "    cd->Name = NULL;", "    ;"),
    M("cam-incident", "    trackpath_coord_init_at(&incident, &at);",
      "    trackpath_coord_init_at(&incident, (const bVector2 *)&rc->mIncidentCoord);"),
    M("cam-bank-line", "RC_AUTO_FILE, RC_LINE_BANK, RC_POOL);",
      "RC_AUTO_FILE, RC_LINE_EYE, RC_POOL);"),
    M("cam-num-eyes", "    cd->NumEyeVerts = r->nPoints;",
      "    cd->NumEyeVerts = r->nPoints - 1;"),
    M("cam-right", "                                            pt->pPoint->RightWidth);",
      "                                            pt->pPoint->LeftWidth);"),
    M("cam-dir", "    if (RaceParametersTrackDirection == 0) {",
      "    if (RaceParametersTrackDirection != 1) {"),
    M("cam-min", "        cd->MinAreaPercent = cd->MinPercent = start.RatioAroundTrack;",
      "        cd->MinAreaPercent = cd->MinPercent = final.RatioAroundTrack;"),
    M("cam-max", "        cd->MaxAreaPercent = cd->MaxPercent = final.RatioAroundTrack;",
      "        cd->MaxAreaPercent = cd->MaxPercent = start.RatioAroundTrack;"),
    M("cam-min-area", "        cd->MinAreaPercent = cd->MinPercent = start.RatioAroundTrack;",
      "        cd->MinPercent = start.RatioAroundTrack;"),
    M("cam-rev-min", "        cd->MinAreaPercent = cd->MinPercent = 1.0f - start.RatioAroundTrack;",
      "        cd->MinAreaPercent = cd->MinPercent = 1.0f - final.RatioAroundTrack;"),
    M("cam-rev-max", "        cd->MaxAreaPercent = cd->MaxPercent = 1.0f - final.RatioAroundTrack;",
      "        cd->MaxAreaPercent = cd->MaxPercent = final.RatioAroundTrack;"),
    M("cam-lock-eye", "    cd->LockEyeSpeedToCar = 1;", "    cd->LockEyeSpeedToCar = 0;"),
    M("cam-fov-table", "    cd->FOVTable = (bVector3 *)rc->mpFOVtable;",
      "    cd->FOVTable = NULL;"),
    M("cam-eye-speed", "    cd->EyeSplineSpeed = 0.0f;", "    cd->EyeSplineSpeed = 1.0f;"),
    M("cam-look-speed", "    cd->LookSplineSpeed = 0.0f;", "    ;"),
    M("cam-fov-speed", "    cd->FOVSplineSpeed = 0.0f;", "    ;"),
    M("cam-lock-look", "    cd->LockLookSpeedToCar = 0;", "    cd->LockLookSpeedToCar = 1;"),
    M("cam-backwards", "    cd->Backwards = 0;", "    cd->Backwards = 1;"),
    M("cam-fov-y", "        fov[i].y = 0.0f;", "        fov[i].y = 1.0f;"),
    M("cam-fov-z", "        fov[i].z = 0.0f;", "        ;"),
    M("cam-fov-first", "    for (i = 0; i < RC_AUTO_FOV_ENTRIES; i++) {",
      "    for (i = 1; i < RC_AUTO_FOV_ENTRIES; i++) {"),
    M("cam-eyes", "    cd->EyeVerts = (bVector3 *)rc->mpEyeVerts;",
      "    cd->EyeVerts = (bVector3 *)rc->mpBankVerts;"),
    M("cam-banks", "    cd->BankVerts = (bVector3 *)rc->mpBankVerts;",
      "    cd->BankVerts = (bVector3 *)rc->mpEyeVerts;"),
    M("cam-wipe-auto", "    cd->WipeAutoDisable = 0;", "    cd->WipeAutoDisable = 1;"),
    M("cam-num-look", "    cd->NumLookVerts = 0;", "    ;"),
    M("cam-look-verts", "    cd->LookVerts = NULL;", "    ;"),
    M("cam-spring-x", "    cd->SpringXVel = 0.0f;", "    ;"),
    M("cam-spring-y", "    cd->SpringYVel = 0.0f;", "    ;"),
    M("cam-spring-z", "    cd->SpringZVel = 0.0f;", "    ;"),
    M("cam-damp", "    cd->SpringDamp = 0.0f;", "    ;"),
    M("cam-const", "    cd->SpringConst = 0.0f;", "    ;"),
    M("cam-look-x", "    cd->LookOffsetX = 0.0f;", "    ;"),
    M("cam-look-y", "    cd->LookOffsetY = 0.0f;", "    ;"),
    M("cam-look-z", "    cd->LookOffsetZ = 0.0f;", "    ;"),
    M("cam-leave-vert", "    cd->LeaveVertComp = 0.0f;", "    ;"),
    M("cam-leave-horiz", "    cd->LeaveHorizComp = 0.0f;", "    ;"),
    M("cam-leave-set", "    cd->IsLeaveSet = 0;", "    ;"),
    M("cam-wipe", "    cd->WipeDistance = 0.0f;", "    ;"),
    M("cam-horiz", "    cd->WipeDistance = 0.0f;\n",
      "    cd->WipeDistance = 0.0f;\n    cd->EnterHorizComp = 0.0f;\n"),
    M("cam-car", "    rc->mpCameraMover = make_mover(rc, rc->mpHighlightCar);",
      "    rc->mpCameraMover = make_mover(rc, rc->mpHighlightCar2);"),

    # ACTIVATE.
    M("act-take", "replaymgr_take_snapshot(rm, RC_AUTO_THE_PRESENT) == NULL",
      "replaymgr_take_snapshot(rm, RC_AUTO_THE_PRESENT) != NULL"),
    M("act-final-late", "    rc->mFinalPosition = car_place(rc->mpHighlightCar);\n"
      "    if (!replaymgr_restore_snapshot_named(rm, RC_AUTO_SNAPSHOT))\n"
      "        return 0;\n",
      "    if (!replaymgr_restore_snapshot_named(rm, RC_AUTO_SNAPSHOT))\n"
      "        return 0;\n"
      "    rc->mFinalPosition = car_place(rc->mpHighlightCar);\n"),
    M("act-auto", "    if (!replaymgr_restore_snapshot_named(rm, RC_AUTO_SNAPSHOT))",
      "    if (replaymgr_restore_snapshot_named(rm, RC_AUTO_SNAPSHOT))"),
    M("act-ir", "    if (!replaymgr_restore_snapshot_named(rm, RC_AUTO_INSTANT_REPLAY))",
      "    if (replaymgr_restore_snapshot_named(rm, RC_AUTO_INSTANT_REPLAY))"),
    M("act-order", "    if (!replaymgr_restore_snapshot_named(rm, RC_AUTO_SNAPSHOT))\n"
      "        return 0;\n"
      "    if (!replaymgr_restore_snapshot_named(rm, RC_AUTO_INSTANT_REPLAY))",
      "    if (!replaymgr_restore_snapshot_named(rm, RC_AUTO_INSTANT_REPLAY))\n"
      "        return 0;\n"
      "    if (!replaymgr_restore_snapshot_named(rm, RC_AUTO_SNAPSHOT))"),
    M("act-start", "    rc->mStartPosition = car_place(rc->mpHighlightCar);",
      "    rc->mStartPosition = car_place(rc->mpHighlightCar2);"),
    M("act-check-rc", "    if (!racecoordinator_check_auto_replay_cam(pRaceCoordinator))",
      "    if (!racecoordinator_check_auto_replay_cam(rc))"),
    M("act-check-not", "    if (!racecoordinator_check_auto_replay_cam(pRaceCoordinator))",
      "    if (racecoordinator_check_auto_replay_cam(pRaceCoordinator))"),
    M("act-bars", "    screen_visibility(RC_AUTO_BARS_SCREEN, FLAILER_SCREEN_VISIBLE);",
      "    screen_visibility(RC_AUTO_BARS_SCREEN, FLAILER_SCREEN_INVISIBLE);"),
    M("act-rewinds", "    rc->mNumRewinds = 0;", "    rc->mNumRewinds = 1;"),
    M("act-rewinds-kept", "    rc->mNumRewinds = 0;", "    ;"),
    M("act-disable-first", "    for (i = 0; i < PlayerNumPlayers; i++)\n"
      "        player_disable_camera_movers",
      "    for (i = 1; i < PlayerNumPlayers; i++)\n"
      "        player_disable_camera_movers"),
    M("act-disable-enable", "        player_disable_camera_movers(PlayerPlayersByIndex[i]);",
      "        player_enable_camera_movers(PlayerPlayersByIndex[i]);"),
    M("act-cam", "    racecoordinator_set_up_auto_replay_cam(rc);\n    return 1;",
      "    return 1;"),
    M("act-state", "            racecoordinator_change_state(rc, RCSTATE_RACE_IN_PROGRESS);\n"
      "        return 1;\n    case RC_UNACTIVATE:",
      "            racecoordinator_change_state(rc, RCSTATE_PAUSE);\n"
      "        return 1;\n    case RC_UNACTIVATE:"),
    M("act-ret", "            racecoordinator_change_state(rc, RCSTATE_RACE_IN_PROGRESS);\n"
      "        return 1;\n    case RC_UNACTIVATE:",
      "            racecoordinator_change_state(rc, RCSTATE_RACE_IN_PROGRESS);\n"
      "        return 0;\n    case RC_UNACTIVATE:"),

    # TICK.
    M("tick-gt", "                  - (uint32_t)WorldLoopCounter) > 0)",
      "                  - (uint32_t)WorldLoopCounter) >= 0)"),
    M("tick-signed", "    if ((int32_t)((uint32_t)pReplayManager->EndCapturingLoopCount\n"
      "                  - (uint32_t)WorldLoopCounter) > 0)",
      "    if ((uint32_t)pReplayManager->EndCapturingLoopCount\n"
      "                  > (uint32_t)WorldLoopCounter)"),
    M("tick-count", "    rc->mNumRewinds++;\n", "    rc->mNumRewinds += 2;\n"),
    M("tick-ge", "    if (rc->mNumRewinds >= RC_AUTO_REWINDS) {",
      "    if (rc->mNumRewinds > RC_AUTO_REWINDS) {"),
    M("tick-skip", "        racecoordinator_send_message(rc, RC_SKIP, 0);",
      "        racecoordinator_send_message(rc, RC_SKIP_REPLAY, 0);"),
    M("tick-skip-param", "        racecoordinator_send_message(rc, RC_SKIP, 0);",
      "        racecoordinator_send_message(rc, RC_SKIP, 1);"),
    M("tick-skip-return", "        racecoordinator_send_message(rc, RC_SKIP, 0);\n"
      "        return;", "        racecoordinator_send_message(rc, RC_SKIP, 0);\n"
      "        ;"),
    M("tick-first", "    rewind(rc, rc->mNumRewinds == 1);",
      "    rewind(rc, rc->mNumRewinds == 2);"),
    M("tick-first-le", "    rewind(rc, rc->mNumRewinds == 1);",
      "    rewind(rc, rc->mNumRewinds <= 1);"),

    # UNACTIVATE and the rest.
    M("un-restore", "        replaymgr_restore_snapshot_named(pReplayManager,\n"
      "                                         RC_AUTO_THE_PRESENT);",
      "        ;"),
    M("un-delete", "        replaymgr_delete_snapshot_named(pReplayManager,\n"
      "                                        RC_AUTO_THE_PRESENT);",
      "        ;"),
    M("un-bars", "        screen_visibility(RC_AUTO_BARS_SCREEN, FLAILER_SCREEN_INVISIBLE);",
      "        screen_visibility(RC_AUTO_BARS_SCREEN, FLAILER_SCREEN_VISIBLE);"),
    M("un-clean", "        racecoordinator_clean_up_auto_replay(rc);\n"
      "        for (i = 0;", "        for (i = 0;"),
    M("un-enable", "            player_enable_camera_movers(PlayerPlayersByIndex[i]);",
      "            player_disable_camera_movers(PlayerPlayersByIndex[i]);"),
    M("un-enable-first", "        for (i = 0; i < PlayerNumPlayers; i++)\n"
      "            player_enable_camera_movers",
      "        for (i = 1; i < PlayerNumPlayers; i++)\n"
      "            player_enable_camera_movers"),
    M("un-handlers", "            gRestoreTypeChangedHandlersFn();", "            ;"),
    M("un-ret", "            gRestoreTypeChangedHandlersFn();\n        return 1;",
      "            gRestoreTypeChangedHandlersFn();\n        return 0;"),
    M("tick-ret", "        auto_replay_tick(rc);\n        return 1;",
      "        auto_replay_tick(rc);\n        return 0;"),
    M("skip-state", "    case RC_SKIP:\n"
      "        racecoordinator_change_state(rc, RCSTATE_RACE_IN_PROGRESS);",
      "    case RC_SKIP:\n"
      "        racecoordinator_change_state(rc, RCSTATE_POSTRACE);"),
    M("skip-ret", "        racecoordinator_change_state(rc, RCSTATE_RACE_IN_PROGRESS);\n"
      "        return 1;\n    case RC_TAKE",
      "        racecoordinator_change_state(rc, RCSTATE_RACE_IN_PROGRESS);\n"
      "        return 0;\n    case RC_TAKE"),
    M("auto-ret", "    case RC_TAKE_AUTOSNAPSHOT:\n        return 1;",
      "    case RC_TAKE_AUTOSNAPSHOT:\n        return 0;"),
    M("default-ret", "    default:\n        return 0;", "    default:\n        return 1;"),
    M("case-skip-replay", "    case RC_TAKE_AUTOSNAPSHOT:\n",
      "    case RC_TAKE_AUTOSNAPSHOT:\n    case RC_SKIP_REPLAY:\n"),
    M("case-pause", "    case RC_TICK:\n        auto",
      "    case RC_REQUEST_PAUSE:\n    case RC_TICK:\n        auto"),
]

EQUIVALENT = {
}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name


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
    scp = Path(scdir.name) / "script.txt"
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
        todo, SOURCES, "rcauto_test",
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
        scp = Path(tmp) / "script.txt"
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
    print("%d ops, %d lines, %d differ" % (len(sc), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
