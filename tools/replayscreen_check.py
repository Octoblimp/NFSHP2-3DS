#!/usr/bin/env python3
"""Cross-check 3DS Files/source/replayscreen.c, the screen over an instant
replay, against the retail image, SLES_507.31 (TASKS 72g-2).

**The model** is retail's own ReplayScreen run in retail_model.RetailEmu:
its constructor and destructor (0x001ebda8, 0x001ebf98), the markers
(0x001ec0c0, which the symbols call the constructor), ShouldWeBeWatchingNis,
StopWatchingNis, HasCameraMover, ChangeCameraMover, Tick, Update,
AddJoyHandlers, RemoveJoyHandlers, JoyHandler, GetTimelinePositionX,
SetFlailerBitmapPosition, Pause and JoyHandlerBridge (0x001ec490 ..
0x001ed4dc). Under them run bStrCmp, bSPrintf and bStringHash, and
FlailerBitmapChunk::CalculateWidth over the stubbed CalculateWidthFloat.
The harness (tools/src/replayscreen_test.c) runs replayscreen.c.

**The stubs** print what they are asked, on both sides:
SetFlailerScreenVisibility, FindFlailerObject, CalculateWidthFloat, the
objects' SetVisibility, SetTopLeftX and Y, the bitmaps' SetWidth, SetHeight
and SetColor, FlailerPrintf (formatted), FlailerSetLanguageID, IsNisPlaying,
NisManager's Create- and DeleteNisCameraCoordinator, RealDriver's
NitroActive, RadialBlurOnOff, bMalloc, DemoCameraCoordinator's and
DriveCameraMover's constructors and the destructors their vtables give,
PostMessage, GetRacingCar, Timer::PrintToString, GetFinishReasonID,
sound's MuteReplay and PlayCommonRegionSample, MakeFrontendSound, the help
menu's IsActive and its toggle (0x0016ca40), bIsThereACDInTheDrive,
AddJoyHandler, RemoveJoyHandler, the seven DemoModeReplay calls and
__builtin_delete. GetSnapshot and eGetView say nothing.

**Differences made equal by hand.** The port's seams stand where retail
calls a class the port has not got or reaches through a global: the help
menu, the demo replay, the disc test, the blur, the two camera
constructors. The coordinator's delete is one seam where retail calls the
vtable's destructor with 3; the model's destructor prints the free that
the harness's bFree does. A marker's snapshot posted with
RC_MOVE_REPLAY is a word in retail and the pointer truncated to one in
the port; both print it as the snapshot's label, or as a number.

**The script** builds the screen over every mix of what its constructor
reads; builds the markers from many lists of snapshots, with objects
missing; updates it over the races, the players, the finishes and the
demo's indicators; ticks it to the capture's end and past the four
seconds; sends every replay event in each state it tests; places the
time; and destroys it with each camera up. Then random mixes.

    python tools/replayscreen_check.py
    python tools/replayscreen_check.py --mutate [--only a,b]
    python tools/replayscreen_check.py --dump out/replayscreen
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
import mipsemu as me                    # noqa: E402
import mutpar                           # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/replayscreen_test.c"
RS = "3DS Files/source/replayscreen.c"
SOURCES = [HARNESS, RS, "3DS Files/source/bprintf.c"]
HARNESS_TIMEOUT = 120

GP = retail_model.RETAIL_GP
P_REPLAY = GP - 22440
P_RACE_COORD = GP - 22216
P_RACE = GP - 22272
PLAYERS = GP - 20936
NUM_PLAYERS = GP - 20920
FLOW = GP - 21324
G_WLC = GP - 19552              # WorldLoopCounter
G_WT = GP - 19576               # WorldTimer
G_RLC = GP - 19580              # RealLoopCounter
G_RTF = GP - 19600              # RealTimeFrames
G_RT = GP - 19608               # RealTimer
P2P = 0x0031a8c0                # TheRaceParameters.Point2Point
DMR = 0x002f0960                # TheDemoModeReplay
DDM = 0x002effe0                # TheDemoDiscManager
HELP_IDS = 0x0031a758

F_CTOR = 0x001ebda8
F_DTOR = 0x001ebf98
F_MARKERS = 0x001ec0c0
F_WATCH = 0x001ec490
F_STOPNIS = 0x001ec4c0
F_HAS = 0x001ec510
F_CHANGE = 0x001ec540
F_TICK = 0x001ec768
F_UPDATE = 0x001ec858
F_ADD = 0x001ecd80
F_REMOVE = 0x001ecea8
F_JOY = 0x001ecf58
F_POSX = 0x001ed410
F_BMPOS = 0x001ed448
F_PAUSE = 0x001ed498
F_BRIDGE = 0x001ed4c0

S_SCREENVIS = 0x0014cbf8
S_FIND = 0x00143d50
S_WIDTHF = 0x00141448
S_VIS = 0x00140728
S_X = 0x00140a20
S_Y = 0x00140a48
S_W = 0x001414c8
S_H = 0x00141528
S_COLOR = 0x00141288
S_PRINTF = 0x00143e70
S_LANG = 0x001449a8
S_NIS = 0x00176520
S_NIS_DEL = 0x001b2b90
S_NIS_NEW = 0x001b2af0
S_NITRO = 0x0013c318
S_VIEW = 0x00107c90
S_BLUR = 0x0010f1e0
S_MALLOC = 0x002577c0
S_DEMOCOORD = 0x0019a440
S_DRIVE = 0x0015c258
S_POST = 0x001496d8
S_RACINGCAR = 0x00149158
S_TIMER = 0x001a3b98
S_FINISHID = 0x00146788
S_SNAP = 0x0013e648
S_MUTE = 0x001af940
S_SAMPLE = 0x001af760
S_FESOUND = 0x0016e038
S_HELPACTIVE = 0x001e4170
S_HELPTOGGLE = 0x0016ca40
S_CD = 0x00255670
S_ADDJOY = 0x00154140
S_REMJOY = 0x001541e8
S_CANTEST = 0x0013f2d0
S_BEGINTEST = 0x0013f300
S_GOESON = 0x0013f310
S_SERVICE = 0x0013f430
S_END = 0x0013f4f0
S_BEGINREC = 0x0013f660
S_ENDREC = 0x0013f670
B_DELETE = 0x00114e98

NUM_SLOTS = 256
SLOT_SIZE = 1024
NUM_OBJS = 44
OBJ_SIZE = 80
MAX_SNAPS = 40
SNAP_SIZE = 64

OBJ_NAMES = ["TIMELINE", "TIME_MARKER", "INSTANT_REPLAY_MARKER",
             "DEMO_PLAYING", "DEMO_RECORDING", "DEMO_WANT_RECORDING",
             "ONE_PLAYER_ONLY", "LAP", "LAP_LABEL", "PLACE", "PLACE_LABEL",
             "TIME"]
OBJ_HASHES = [0xbd2bc882, 0xb8e8186f, 0xadaa0f01, 0xacf8f0b5, 0xd32490be,
              0x4b53438f, 0xc9b7f0c0, 0x6486623b, 0x51072bf1, 0x3405c44e,
              0x98071aa4, 0x15e0f0a8]
SCREEN = 0x60befaed
HIDDEN = 0xddce04a3

SNAP_NAMES = ["LAP_SNAPSHOT", "HIGHLIGHT_SNAPSHOT", "DEMO_MODE_SNAPSHOT",
              "INSTANT_REPLAY", "LAP_SNAPSHOT2", "INSTANT_REPLAY ", "",
              "DEMO_MODE_SNAPSHOt", "PURSUIT", "lap_snapshot"]
(N_LAP, N_HL, N_DEMO, N_INSTANT, N_LAP2, N_INSTANT_SP, N_EMPTY, N_DEMO_LC,
 N_PURSUIT, N_LAP_LC) = range(10)

(O_TIMELINE, O_TIME_MARKER, O_INSTANT, O_DPLAY, O_DREC, O_DWANT, O_ONE,
 O_LAP, O_LAPL, O_PLACE, O_PLACEL, O_TIME) = range(12)
ALL = (1 << NUM_OBJS) - 1


def LM(i):
    """LAP_MARKERi's object, i from 1."""
    return 12 + i - 1


def HM(i):
    """HIGHLIGHT_MARKERi's object, i from 1."""
    return 28 + i - 1


def bhash(s):
    h = 0xffffffff
    for c in s.encode("latin-1"):
        h = (h * 33 + c) & M32
    return h


def fb(v):
    return "0x%08x" % me.f_to_bits(v)


# ================================================================= the model


class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        self.slots = e.alloc(NUM_SLOTS * SLOT_SIZE, 256)
        self.slot_used = [False] * NUM_SLOTS
        self.objs = e.alloc(NUM_OBJS * OBJ_SIZE, 16)
        self.snaps = e.alloc(MAX_SNAPS * SNAP_SIZE, 16)
        self.players = e.alloc(2 * 256, 16)
        self.cars = e.alloc(2 * 64, 16)
        self.cartypes = e.alloc(2 * 1344, 16)
        self.rcs = e.alloc(2 * 32, 16)
        self.drivers = e.alloc(2 * 16, 16)
        self.nism = e.alloc(2 * 16, 16)
        self.nisc = e.alloc(2 * 16, 16)
        self.race = e.alloc(1700, 16)
        self.rc = e.alloc(64, 16)
        self.rm = e.alloc(128, 16)
        self.egs = e.alloc(16, 16)
        self.flow = e.alloc(512, 16)
        self.help = e.alloc(16, 16)
        self.view = e.alloc(16, 16)
        self.mover_vt = e.alloc(16, 16)
        self.coord_vt = e.alloc(16, 16)
        self.f_mover_dtor = e.alloc(16, 16)
        self.f_coord_dtor = e.alloc(16, 16)
        for blk, n in ((self.slots, NUM_SLOTS * SLOT_SIZE),
                       (self.objs, NUM_OBJS * OBJ_SIZE),
                       (self.snaps, MAX_SNAPS * SNAP_SIZE),
                       (self.players, 512), (self.cars, 128),
                       (self.cartypes, 2688), (self.rcs, 64),
                       (self.race, 1700), (self.rc, 64), (self.rm, 128),
                       (self.flow, 512), (self.mover_vt, 16),
                       (self.coord_vt, 16)):
            e.write(blk, bytes(n))
        e.put32(self.mover_vt + 12, self.f_mover_dtor)
        e.put32(self.coord_vt + 12, self.f_coord_dtor)
        e.put32(self.flow + 452, self.help)
        e.put32(FLOW, self.flow)
        e.put32(P_REPLAY, self.rm)
        e.put32(P_RACE_COORD, self.rc)
        e.put32(P_RACE, self.race)
        for i in range(2):
            p = self.players + 256 * i
            car = self.cars + 64 * i
            e.put32(PLAYERS + 4 * i, p)
            e.put32(p + 4, car)
            e.put32(p + 244, self.nism + 16 * i)
            e.put32(car + 12, self.cartypes + 1344 * i)
            e.put32(car + 44, self.drivers + 16 * i)
        for a in (NUM_PLAYERS, G_WLC, G_WT, G_RLC, G_RTF, G_RT, P2P,
                  DMR + 20, DMR + 24, DMR + 32):
            e.put32(a, 0)
        e.write(DDM + 30, bytes(4))
        e.write(0, bytes(64))

        self.obj_hash = list(OBJ_HASHES)
        self.obj_name = list(OBJ_NAMES)
        for i in range(1, 17):
            self.obj_name.append("LAP_MARKER%d" % i)
        for i in range(1, 17):
            self.obj_name.append("HIGHLIGHT_MARKER%d" % i)
        for nm in self.obj_name[12:]:
            self.obj_hash.append(bhash(nm))
        self.obj_width = [0] * NUM_OBJS
        self.obj_mask = 0
        self.num_snaps = 0
        self.nitro = [0, 0]
        self.nis = [0, 0]
        self.ans = dict(help=0, toggle=0, cd=0, cantest=0, goeson=0, nis=0)
        self.screen = 0

        for a, fn in ((S_SCREENVIS, self.screen_vis), (S_FIND, self.find),
                      (S_WIDTHF, self.widthf), (S_VIS, self.vis),
                      (S_X, self.fsay("x")), (S_Y, self.fsay("y")),
                      (S_W, self.fsay("w")), (S_H, self.fsay("h")),
                      (S_COLOR, self.color), (S_PRINTF, self.printf),
                      (S_LANG, self.lang), (S_NIS, self.nis_playing),
                      (S_NIS_DEL, self.nis_delete),
                      (S_NIS_NEW, self.nis_create), (S_NITRO, self.nitro_active),
                      (S_VIEW, lambda e: self.view), (S_BLUR, self.blur),
                      (S_MALLOC, self.malloc), (S_DEMOCOORD, self.democoord),
                      (S_DRIVE, self.drive), (S_POST, self.post),
                      (S_RACINGCAR, self.racingcar), (S_TIMER, self.timer),
                      (S_FINISHID, self.finishid), (S_SNAP, self.get_snap),
                      (S_MUTE, self.mute), (S_SAMPLE, self.sample),
                      (S_FESOUND, self.fesound),
                      (S_HELPACTIVE, self.help_active),
                      (S_HELPTOGGLE, self.help_toggle), (S_CD, self.cd),
                      (S_ADDJOY, self.addjoy), (S_REMJOY, self.remjoy),
                      (S_CANTEST, self.answer("dmr cantest", "cantest")),
                      (S_BEGINTEST, self.say("dmr begintest")),
                      (S_GOESON, self.answer("dmr goeson", "goeson")),
                      (S_SERVICE, self.service),
                      (S_END, self.say("dmr end")),
                      (S_BEGINREC, self.say("dmr beginrec")),
                      (S_ENDREC, self.endrec), (B_DELETE, self.delete),
                      (self.f_mover_dtor, self.dtor_say("mover dtor")),
                      (self.f_coord_dtor, self.dtor_say("coord delete"))):
            e.stub(a, fn)

    def emit(self, s):
        self.out.append(s)

    def cstr(self, a, n=256):
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

    def f12(self):
        return self.e.fpr[12] & M32

    # ---- the blocks

    def slot_of(self, p):
        if self.slots <= p < self.slots + NUM_SLOTS * SLOT_SIZE:
            return (p - self.slots) // SLOT_SIZE
        return -1

    def slot_alloc(self):
        for i in range(NUM_SLOTS):
            if not self.slot_used[i]:
                self.slot_used[i] = True
                a = self.slots + i * SLOT_SIZE
                self.e.write(a, b"\xcd" * SLOT_SIZE)
                return a
        raise RuntimeError("out of slots")

    def free_slot(self, p):
        k = self.slot_of(p)
        if k >= 0:
            self.slot_used[k] = False

    def label(self, p):
        p &= M32
        if p == 0:
            return "NULL"
        k = self.slot_of(p)
        if k >= 0:
            return "m%d+%d" % (k, p - self.slots - k * SLOT_SIZE)
        for base, size, n, fmt in (
                (self.objs, OBJ_SIZE, NUM_OBJS, "o%d"),
                (self.snaps, SNAP_SIZE, MAX_SNAPS, "S%d"),
                (self.players, 256, 2, "P%d"), (self.cars, 64, 2, "car%d"),
                (self.rcs, 32, 2, "rc%d"), (self.drivers, 16, 2, "D%d"),
                (self.nism, 16, 2, "N%d"), (self.nisc, 16, 2, "NC%d")):
            if base <= p < base + size * n and (p - base) % size == 0:
                return fmt % ((p - base) // size)
        return {self.race: "R", self.rc: "RC", self.rm: "RM",
                HELP_IDS: "HELP"}.get(p, "?")

    def word_label(self, w):
        w &= M32
        if (self.snaps <= w < self.snaps + MAX_SNAPS * SNAP_SIZE
                and (w - self.snaps) % SNAP_SIZE == 0):
            return "S%d" % ((w - self.snaps) // SNAP_SIZE)
        return "%d" % s32(w)

    def hash_name(self, h):
        h &= M32
        if h in self.obj_hash:
            return self.obj_name[self.obj_hash.index(h)]
        return {0x18b2dbc8: "PLAYER_NUMBER", 0xd53d9dbe: "TIME_LABEL",
                SCREEN: "SCREEN", HIDDEN: "HIDDEN"}.get(h, "0x%08x" % h)

    def index(self, p, base, size, n):
        if base <= p < base + size * n and (p - base) % size == 0:
            return (p - base) // size
        return -1

    # ---- the stubs

    def say(self, what):
        def fn(e):
            self.emit(what)
        return fn

    def answer(self, what, key):
        def fn(e):
            self.emit(what)
            return self.ans[key]
        return fn

    def dtor_say(self, what):
        def fn(e):
            p = self.arg(0)
            self.emit("%s %s" % (what, self.label(p)))
            if self.arg(1) & 1:
                self.emit("free %s" % self.label(p))
                self.free_slot(p)
        return fn

    def fsay(self, what):
        def fn(e):
            self.emit("%s %s 0x%08x" % (what, self.label(self.arg(0)),
                                        self.f12()))
        return fn

    def screen_vis(self, e):
        self.emit("screen %s %d" % (self.hash_name(self.arg(0)),
                                    self.sarg(1)))

    def find(self, e):
        h = self.arg(1)
        found = 0
        for i in range(NUM_OBJS):
            if self.obj_hash[i] == h and (self.obj_mask >> i) & 1:
                found = self.objs + OBJ_SIZE * i
                break
        self.emit("find %s %s %d -> %s" % (
            self.hash_name(self.arg(0)), self.hash_name(h), self.sarg(2),
            self.label(found)))
        return found

    def widthf(self, e):
        p = self.arg(0)
        i = self.index(p, self.objs, OBJ_SIZE, NUM_OBJS)
        self.emit("widthf %s" % self.label(p))
        e.fpr[0] = self.obj_width[i] if i >= 0 else 0

    def vis(self, e):
        self.emit("vis %s %d" % (self.label(self.arg(0)), self.sarg(1)))

    def color(self, e):
        self.emit("color %s 0x%08x" % (self.label(self.arg(0)), self.arg(1)))

    def printf(self, e):
        fmt = self.cstr(self.arg(2))
        k = 3
        out = []
        i = 0
        while i < len(fmt):
            c = fmt[i]
            if c == "%" and i + 1 < len(fmt):
                d = fmt[i + 1]
                i += 2
                if d == "d":
                    out.append("%d" % self.sarg(k))
                    k += 1
                elif d == "s":
                    out.append(self.cstr(self.arg(k)))
                    k += 1
                else:
                    out.append(d)
                continue
            out.append(c)
            i += 1
        self.emit("printf %s %s %s [%s]" % (
            self.hash_name(self.arg(0)), self.hash_name(self.arg(1)), fmt,
            "".join(out)))
        return 0

    def lang(self, e):
        self.emit("langid %s %s 0x%x" % (self.hash_name(self.arg(0)),
                                         self.hash_name(self.arg(1)),
                                         self.arg(2)))

    def nis_playing(self, e):
        p = self.arg(0)
        i = self.index(p, self.players, 256, 2)
        self.emit("nis %s" % self.label(p))
        return self.nis[i] if i >= 0 else 0

    def nis_delete(self, e):
        self.emit("nis delete %s %s" % (self.label(self.arg(0)),
                                        self.label(self.arg(1))))

    def nis_create(self, e):
        m = self.arg(0)
        i = self.index(m, self.nism, 16, 2)
        c = self.nisc + 16 * i if self.ans["nis"] and i >= 0 else 0
        self.emit("nis create %s %d -> %s" % (self.label(m), self.sarg(1),
                                              self.label(c)))
        return c

    def nitro_active(self, e):
        d = self.arg(0)
        i = self.index(d, self.drivers, 16, 2)
        self.emit("nitro %s" % self.label(d))
        return self.nitro[i] if i >= 0 else 0

    def blur(self, e):
        self.emit("blur %d" % self.sarg(0))

    def malloc(self, e):
        p = self.slot_alloc()
        self.emit("malloc %d %s %d %d -> %s" % (
            self.sarg(0), self.cstr(self.arg(1)), self.sarg(2),
            self.sarg(3), self.label(p)))
        return p

    def democoord(self, e):
        p = self.arg(0)
        self.emit("democoord %s %d %s" % (self.label(p), self.sarg(1),
                                          self.label(self.arg(2))))
        e.put32(p + 24, self.coord_vt)
        return p

    def drive(self, e):
        p = self.arg(0)
        self.emit("drive %s %d %s %d 0x%08x %d %d %d" % (
            self.label(p), self.sarg(1), self.label(self.arg(2)),
            self.sarg(3), self.f12(), self.sarg(4), self.sarg(5),
            self.sarg(6)))
        e.put32(p + 40, self.mover_vt)
        return p

    def post(self, e):
        self.emit("post %s %d %s" % (self.label(self.arg(0)), self.sarg(1),
                                     self.word_label(self.arg(2))))

    def racingcar(self, e):
        car = self.arg(1)
        i = self.index(car, self.cars, 64, 2)
        rc = self.rcs + 32 * i if i >= 0 else 0
        self.emit("racingcar %s %s -> %s" % (self.label(self.arg(0)),
                                             self.label(car),
                                             self.label(rc)))
        return rc

    def timer(self, e):
        t = e.u32(self.arg(0))
        self.emit("timer %d %d" % (t, self.sarg(2)))
        e.write(self.arg(1), ("T%d" % t).encode() + b"\0")

    def finishid(self, e):
        r = self.sarg(0)
        self.emit("finishid %d" % r)
        return 0x1000 + r

    def get_snap(self, e):
        k = self.sarg(1)
        if 0 <= k < self.num_snaps:
            return self.snaps + SNAP_SIZE * k
        return 0

    def mute(self, e):
        self.emit("mute %d" % self.sarg(0))

    def sample(self, e):
        self.emit("sample %s 0x%08x" % (self.cstr(self.arg(0)), self.f12()))

    def fesound(self, e):
        self.emit("fesound %d" % self.sarg(0))

    def help_active(self, e):
        self.emit("helpactive")
        return self.ans["help"]

    def help_toggle(self, e):
        lines = self.arg(1)
        ids = struct.unpack("<9i", self.e.read(lines, 36))
        self.emit("helptoggle %s %d [%s]" % (
            self.label(lines), self.sarg(2), " ".join(str(v) for v in ids)))
        return self.ans["toggle"]

    def cd(self, e):
        self.emit("cd")
        return self.ans["cd"]

    def addjoy(self, e):
        self.emit("addjoy %d %d %s %s" % (
            self.sarg(0), self.sarg(1),
            "bridge" if self.arg(2) == F_BRIDGE else "?",
            self.label(self.arg(3))))

    def remjoy(self, e):
        self.emit("remjoy %d %d" % (self.sarg(0), self.sarg(1)))

    def service(self, e):
        self.emit("dmr service %d" % self.sarg(1))

    def endrec(self, e):
        self.emit("dmr endrec %d" % self.sarg(1))

    def delete(self, e):
        p = self.arg(0)
        self.emit("free %s" % self.label(p))
        self.free_slot(p)

    # ---- the ops

    def set_snaps(self, spec):
        e = self.e
        self.num_snaps = 0
        if spec == "-":
            return
        for item in spec.split(";")[:MAX_SNAPS]:
            n, tm, end = (int(v, 0) for v in item.split(":"))
            a = self.snaps + SNAP_SIZE * self.num_snaps
            self.num_snaps += 1
            name = SNAP_NAMES[n] if 0 <= n < len(SNAP_NAMES) else ""
            e.write(a + 8, (name.encode() + bytes(32))[:32])
            e.put32(a + 40, tm)
            e.put32(a + 44, end)

    def marker(self, a):
        e = self.e
        return " [0x%08x 0x%08x %s %s]" % (
            e.u32(a), e.u32(a + 4), self.label(e.u32(a + 8)),
            self.label(e.u32(a + 12)))

    def dump(self):
        e = self.e
        s = self.screen
        w = [s32(e.u32(s + 4 * i)) for i in range(10)]
        self.emit("screen 0x%08x 0x%08x %d %d %d %d %d %d %d" % (
            e.u32(s), e.u32(s + 4), w[2], w[3], w[4], w[5], w[6], w[7],
            w[8]))
        n = s32(e.u32(s + 36))
        self.emit("laps %d%s" % (n, "".join(
            self.marker(s + 40 + 16 * i) for i in range(min(n, 16)))))
        n = s32(e.u32(s + 296))
        self.emit("highlights %d%s" % (n, "".join(
            self.marker(s + 300 + 16 * i) for i in range(min(n, 16)))))
        self.emit("objs %s %s %s %s" % tuple(
            self.label(e.u32(s + off)) for off in (556, 560, 564, 568)))
        self.emit("cams %s %s %s" % tuple(
            self.label(e.u32(s + off)) for off in (572, 576, 580)))
        self.emit("words %d %d %d %d %d" % (
            s32(e.u32(self.rm + 16)), s32(e.u32(self.rm + 20)),
            s32(e.u32(DMR + 20)),
            struct.unpack("<h", e.read(DDM + 30, 2))[0],
            struct.unpack("<h", e.read(DDM + 32, 2))[0]))

    def call(self, fn, *args, **kw):
        e = self.e
        if "f12" in kw:
            e.fpr[12] = kw["f12"] & M32
        return e.call(fn, *args, limit=2000000)

    def op(self, a):
        e = self.e
        op = a[0]
        v = [int(x, 0) for x in a[1:]] if op not in ("snaps", "tag") else []
        if op == "tag":
            return
        if op == "rm":
            for off, x in zip((16, 20, 84, 92, 96), v):
                e.put32(self.rm + off, x)
        elif op == "time":
            for g, x in zip((G_WLC, G_WT, G_RLC, G_RTF, G_RT), v):
                e.put32(g, x)
        elif op == "race":
            e.put32(self.race + 1604, v[0])
            e.put32(self.race + 24, v[1])
            e.put32(self.race + 16, v[2])
            e.put32(P2P, v[3])
        elif op == "players":
            e.put32(NUM_PLAYERS, v[0])
        elif op == "player":
            i = v[0]
            e.put32(self.players + 256 * i + 88, v[1])
            e.put32(self.cars + 64 * i + 32, v[2])
            e.put32(self.cartypes + 1344 * i + 1336, v[3])
            self.nitro[i] = v[4]
            self.nis[i] = v[5]
            rc = self.rcs + 32 * i
            e.write(rc + 9, bytes([v[6] & 0xff, v[7] & 0xff]))
            e.write(rc + 18, struct.pack("<H", v[8] & 0xffff))
        elif op == "objs":
            self.obj_mask = v[0]
        elif op == "objx":
            e.put32(self.objs + OBJ_SIZE * v[0] + 48, v[1])
            self.obj_width[v[0]] = v[2] & M32
        elif op == "snaps":
            self.set_snaps(a[1])
        elif op == "dmr":
            e.put32(DMR + 20, v[0])
            e.put32(DMR + 24, self.snaps + SNAP_SIZE * (MAX_SNAPS - 1)
                    if v[1] else 0)
            e.put32(DMR + 32, self.snaps + SNAP_SIZE * (MAX_SNAPS - 2)
                    if v[2] else 0)
        elif op == "ans":
            for k, x in zip(("help", "toggle", "cd", "cantest", "goeson",
                             "nis"), v):
                self.ans[k] = x
        elif op == "egs":
            e.put32(self.rc + 40, self.egs if v[0] else 0)
        elif op == "ctor":
            p = self.slot_alloc()
            self.screen = p
            r = self.call(F_CTOR, p, v[0])
            self.emit("-> %s" % self.label(r))
        elif op == "dtor":
            self.call(F_DTOR, self.screen, v[0])
        elif op == "markers":
            self.call(F_MARKERS, self.screen, v[0])
        elif op == "watch":
            self.emit("-> %d" % self.call(F_WATCH, self.screen))
        elif op == "stopnis":
            self.call(F_STOPNIS, self.screen)
        elif op == "has":
            self.emit("-> %d" % self.call(F_HAS, self.screen))
        elif op == "change":
            self.call(F_CHANGE, self.screen)
        elif op == "tick":
            self.call(F_TICK, self.screen)
        elif op == "update":
            self.call(F_UPDATE, self.screen)
        elif op == "add":
            self.call(F_ADD, self.screen, v[0])
        elif op == "remove":
            self.call(F_REMOVE, self.screen, v[0])
        elif op == "joy":
            self.call(F_JOY, self.screen, v[0], v[1], v[2])
        elif op == "bridge":
            self.call(F_BRIDGE, v[0], v[1], v[2], self.screen)
        elif op == "posx":
            self.emit("-> %d" % self.call(F_POSX, self.screen, f12=v[0]))
        elif op == "bmpos":
            obj = self.objs + OBJ_SIZE * v[0] if v[0] >= 0 else 0
            self.call(F_BMPOS, self.screen, obj, f12=v[1])
        elif op == "pause":
            self.call(F_PAUSE, self.screen, v[0])
        elif op == "dump":
            self.dump()
        else:
            self.emit("unknown op %s" % op)

    def run(self, lines):
        e = self.e
        for line in lines:
            self.emit("> " + line)
            sp = e.reg[29]
            self.op(line.split("|"))
            e.reg[29] = sp
        return self.out


# ================================================================ the script


class Script(object):
    def __init__(self):
        self.lines = []
        self.t = dict(wlc=1000, wt=100000, rlc=500, rtf=0, rt=1000000)

    def add(self, *lines):
        self.lines.extend(lines)

    def tag(self, text):
        self.add("tag|" + text)

    def time(self, **kw):
        self.t.update(kw)
        self.add("time|%(wlc)d|%(wt)d|%(rlc)d|%(rtf)d|%(rt)d" % self.t)

    def joy(self, ev, value=1, port=0, bridge=False, same_loop=False):
        if not same_loop:
            self.time(rlc=self.t["rlc"] + 1)
        self.add("%s|%d|%d|%d" % ("bridge" if bridge else "joy", port, ev,
                                  value))

    def base(self, players=1, snaps=None):
        self.add("rm|0|0|5000|40000|440000", "race|3|6|123456|0",
                 "players|%d" % players,
                 "player|0|0|0|0|0|0|1|2|0", "player|1|0|1|0|0|0|0|5|0",
                 "objs|%#x" % ALL,
                 "objx|0|%s|%s" % (fb(10.0), fb(200.0)),
                 snaps or STD_SNAPS, "dmr|0|0|0", "ans|0|0|1|0|1|1", "egs|0")
        self.time(wlc=1000, wt=100000, rlc=500, rtf=0, rt=1000000)


def snaps(*items):
    return "snaps|" + (";".join("%d:%d:%d" % it for it in items) or "-")


STD = [(N_LAP, 40000, 44000), (N_DEMO, 60000, 100000),
       (N_LAP, 120000, 124000), (N_HL, 130000, 150000),
       (N_INSTANT, 200000, 240000), (N_LAP, 250000, 254000),
       (N_DEMO, 300000, 320000), (N_INSTANT, 330000, 340000),
       (N_PURSUIT, 1, 2)]
STD_SNAPS = snaps(*STD)


def script():
    sc = Script()

    sc.tag("the constructor's times")
    sc.base()
    for begin, end in ((40000, 440000), (40000, 40000), (440000, 40000),
                       (0, 0), (-4000, 4000), (0, 1), (123457, 9876543),
                       (2000000000, 2000000000), (-2000000000, 2000000000),
                       (4001, 4000), (1, 0), (7, 7)):
        sc.add("rm|0|0|5000|%d|%d" % (begin, end), "ctor|0", "dump",
               "posx|%s" % fb(0.0), "posx|%s" % fb(55.5), "dtor|1")

    sc.tag("the timeline's object")
    sc.base()
    for x, w in ((10.0, 200.0), (10.7, 151.75), (-3.5, 0.0), (0.0, 1.0),
                 (639.9, 480.25), (-0.99, -20.5), (100.49, 3.999)):
        sc.add("objx|0|%s|%s" % (fb(x), fb(w)), "ctor|0", "dump",
               "posx|%s" % fb(30.0), "dtor|1")
    sc.add("objs|%#x" % (ALL & ~(1 << O_TIMELINE)), "ctor|0", "dump",
           "posx|%s" % fb(30.0), "dtor|1")
    sc.add("objs|%#x" % (ALL & ~(1 << O_TIME_MARKER)), "ctor|0", "dump",
           "update", "bmpos|%d|%s" % (O_TIME_MARKER, fb(20.0)), "dtor|1")
    for drop in (O_DPLAY, O_DREC, O_DWANT, O_ONE):
        sc.add("objs|%#x" % (ALL & ~(1 << drop)), "ctor|0", "dump",
               "dtor|1")
    sc.add("objs|0", "ctor|0", "dump", "update", "dtor|1")

    sc.tag("one player only")
    for players in (0, 1, 2, 3):
        sc.base(players=players)
        sc.add("ctor|0", "dump", "dtor|1")

    sc.tag("the cameras")
    sc.base(players=2)
    for zone, ctrl, nitro in ((0, 0, 0), (1, 0, 0), (5, 1, 0), (0, 1, 1),
                              (0, 1, 2), (0, 2, 1), (0, 1, 0), (-1, 1, 1),
                              (0, 3, 1), (-1, 0, 0), (-7, 1, 0)):
        sc.add("player|0|%d|%d|0|%d|0|1|2|0" % (zone, ctrl, nitro),
               "ctor|0", "dump")
        for _ in range(5):
            sc.joy(104)
            sc.add("dump")
        sc.add("dtor|1")
    sc.add("player|0|0|1|0|0|0|1|2|0")
    sc.add("player|1|1|1|0|1|0|0|5|0", "ctor|1", "dump")
    sc.joy(104)
    sc.add("dump", "change", "dump", "has", "watch", "dtor|1")

    sc.tag("the NIS's camera")
    sc.base(players=2)
    sc.add("player|0|0|0|0|0|1|1|2|0", "ctor|0", "dump", "watch", "has")
    sc.add("update", "dump")
    sc.add("player|0|0|0|0|0|0|1|2|0", "watch", "update", "dump")
    sc.add("player|0|0|0|0|0|1|1|2|0", "update", "dump")
    sc.add("stopnis", "dump", "stopnis", "has", "update", "dump")
    sc.joy(104)
    sc.add("dump")
    sc.add("ans|0|0|1|0|1|0", "change", "dump", "has", "update", "dump")
    sc.add("player|0|0|0|0|0|0|1|2|0", "update", "dump")
    sc.add("ans|0|0|1|0|1|1", "player|0|0|0|0|0|1|1|2|0", "update", "dump",
           "player|0|0|0|0|0|2|1|2|0", "watch", "update", "dump")
    sc.add("dtor|1")
    for nis in (0, 1):
        sc.add("player|0|0|0|0|0|%d|1|2|0" % nis, "ctor|0")
        for _ in range(4):
            sc.joy(104)
            sc.add("dump")
        sc.add("dtor|1")

    sc.tag("the markers")
    sc.base()
    sc.add("ctor|0", "dump")
    lists = [
        [],
        STD,
        [(N_LAP, 40000, 40000)] * 3,
        [(N_INSTANT, 50000, 60000), (N_LAP, 40000, 44000),
         (N_INSTANT, 70000, 80000), (N_INSTANT, 90000, 99000)],
        [(N_DEMO, 0, 400000), (N_DEMO, 440000, 40000),
         (N_DEMO, -40000, 1000000), (N_HL, 1, 2), (N_DEMO, 100000, 100000)],
        [(N_LAP2, 1, 2), (N_INSTANT_SP, 1, 2), (N_EMPTY, 1, 2),
         (N_DEMO_LC, 1, 2), (N_PURSUIT, 1, 2), (N_LAP_LC, 1, 2)],
        [(N_LAP, 40000 + 20000 * i, 41000 + 20000 * i) for i in range(15)]
        + [(N_INSTANT, 345000, 350000), (N_INSTANT, 1, 2)],
        [(N_DEMO, 40000 + 20000 * i, 50000 + 25000 * i) for i in range(16)]
        + [(N_HL, 1, 2)] * 3,
        [(N_HL, 40000, 80000)] * 5 + [(N_LAP, 400000, 404000)],
    ]
    for items in lists:
        sc.add(snaps(*items), "markers|1", "dump", "markers|0", "dump",
               "markers|1", "markers|1", "dump")
    sc.tag("markers whose objects are missing")
    sc.add(STD_SNAPS)
    for mask in (ALL & ~(1 << LM(2)), ALL & ~(1 << HM(1)),
                 ALL & ~(1 << O_INSTANT), ALL & ~((1 << LM(1)) | (1 << HM(2))),
                 ALL & ~(((1 << 16) - 1) << 12), ALL & ~(((1 << 16) - 1) << 28),
                 ALL):
        sc.add("objs|%#x" % mask, "markers|1", "dump")
    sc.tag("the stale markers")
    sc.add("objs|%#x" % ALL, "markers|1", "dump",
           "objs|%#x" % (ALL & ~(1 << LM(2)) & ~(1 << HM(1))),
           snaps((N_LAP, 1000, 2000), (N_LAP, 3000, 4000),
                 (N_DEMO, 5000, 6000)),
           "markers|1", "dump", "snaps|-", "markers|1", "dump",
           "markers|0", "dump")
    sc.add("dtor|1")

    sc.tag("the timeline's positions")
    sc.base()
    sc.add("ctor|0")
    for t in (10.0, 110.0, 60.0, 0.0, -5.0, 9.99, 10.01, 109.999, 500.0,
              -500.0, 35.4321, 85.0):
        sc.add("posx|%s" % fb(t), "bmpos|%d|%s" % (O_TIME_MARKER, fb(t)))
    sc.add("bmpos|-1|%s" % fb(20.0), "bmpos|%d|%s" % (O_TIMELINE, fb(40.0)))
    sc.add("dtor|1")

    sc.tag("the update")
    sc.base(players=2)
    sc.add("ctor|0", "update", "dump")
    for race in ("race|3|6|123456|0", "race|1|6|123456|0",
                 "race|3|6|123456|1", "race|0|1|0|0", "race|2|2|4000|0",
                 "race|3|3|99|0", "race|5|8|0xffffffff|0"):
        for p0 in ("player|0|0|0|0|0|0|0|1|0", "player|0|0|0|0|0|0|1|2|1",
                   "player|0|0|0|1|0|0|2|3|2", "player|0|0|0|0|0|0|3|4|3",
                   "player|0|0|0|0|0|0|9|1|4", "player|0|0|0|0|0|0|-1|0|-1",
                   "player|0|0|0|2|0|0|127|127|32767"):
            sc.add(race, p0, "update")
    sc.add("race|3|2|123456|0")
    for players, usage1 in ((1, 0), (1, 1), (2, 0), (2, 1), (3, 1), (0, 0)):
        sc.add("players|%d" % players,
               "player|1|0|1|%d|0|0|0|5|0" % usage1, "update")
    sc.add("players|2", "race|3|3|123456|0", "player|1|0|1|1|0|0|0|5|0",
           "update", "ctor|1", "update", "dtor|1")
    sc.tag("the update's objects missing")
    for drop in (O_LAP, O_LAPL, O_PLACE, O_PLACEL, O_TIME, O_TIME_MARKER):
        sc.add("objs|%#x" % (ALL & ~(1 << drop)),
               "player|0|0|0|0|0|0|1|2|0", "update",
               "player|0|0|0|1|0|0|1|2|2", "update")
    sc.add("objs|%#x" % ALL)
    sc.tag("the demo's indicators")
    for dmr in ("dmr|0|0|0", "dmr|1|0|0", "dmr|0|1|0", "dmr|0|0|1",
                "dmr|1|1|1", "dmr|-1|0|1"):
        sc.add(dmr)
        for rtf in (0, 12, 13, 23, 24, 25, 37, -1, -13, -24, 0x7fffffff,
                    -0x80000000):
            sc.time(rtf=rtf)
            sc.add("update")
    sc.add("dmr|0|0|0", "dtor|1")

    sc.tag("the tick")
    sc.base()
    sc.add("ctor|0")
    for paused, endcap, wlc, egs, rt in (
            (0, 5000, 1000, 0, 1000000), (0, 5000, 5000, 0, 1000000),
            (0, 5000, 6000, 0, 2000000), (1, 5000, 6000, 0, 2000000),
            (1, 5000, 6000, 1, 2016000), (1, 5000, 6000, 1, 2016001),
            (1, 5000, 6000, 1, 2015999), (1, 5000, 5000, 1, 3000000),
            (1, 5001, 5000, 1, 3000000), (0, 5000, 5000, 1, 9000000),
            (1, 5000, 4000, 1, 9000000), (1, -5, 0x7ffffffe, 1, 9000000),
            (0, 0x7fffffff, -2, 1, 9000000)):
        sc.add("rm|%d|0|%d|40000|440000" % (paused, endcap), "egs|%d" % egs)
        sc.time(wlc=wlc, rt=rt)
        sc.add("tick", "dump")
    sc.tag("the counters wrapping")
    sc.add("rm|0|0|2147483647|40000|440000", "egs|1")
    sc.time(wlc=-2, rt=0x7ffff000)
    sc.add("tick", "dump", "rm|1|0|2147483647|40000|440000")
    for rt in (-0x7fff0000, -0x80000000, 0x7ffff000 + 16000,
               0x7ffff000 + 16001):
        sc.time(rt=rt)
        sc.add("tick")
    sc.time(wlc=2147483647)
    sc.add("rm|1|0|-2|40000|440000", "tick", "dump")
    sc.tag("the tick over a demo snapshot")
    sc.add("rm|0|0|5000|40000|440000")
    sc.time(wlc=1000)
    for play, goes in ((0, 0), (1, 0), (1, 1), (1, 2), (1, -1), (0, 1)):
        sc.add("dmr|0|0|%d" % play, "ans|0|0|1|0|%d|1" % goes, "tick", "dump")
    sc.add("dmr|0|0|0", "dtor|1")

    sc.tag("the joystick's handlers")
    sc.base()
    sc.add("ctor|0", "add|0", "add|1", "add|2", "remove|0", "remove|1",
           "remove|-1", "dtor|1")

    sc.tag("skip and pause")
    sc.base()
    sc.add("ctor|0")
    for paused, endcap, wlc in ((0, 5000, 1000), (1, 5000, 1000),
                                (1, 5000, 5000), (1, 5000, 6000),
                                (0, 5000, 6000), (2, 5001, 5000)):
        sc.add("rm|%d|1|%d|40000|440000" % (paused, endcap))
        sc.time(wlc=wlc)
        sc.joy(99)
        sc.joy(100)
        sc.add("dump")
        sc.joy(100)
        sc.add("dump")

    sc.tag("skip and pause wrapping")
    for paused, endcap, wlc in ((1, 0x7fffffff, -2), (1, -2, 0x7fffffff),
                                (0, 0x7fffffff, -2)):
        sc.add("rm|%d|0|%d|40000|440000" % (paused, endcap),
               "ans|0|1|1|0|1|1")
        sc.time(wlc=wlc)
        sc.joy(100)
        sc.add("dump")
        sc.joy(106)
        sc.add("dump")
    sc.add("ans|0|0|1|0|1|1")

    sc.tag("the markers' buttons")
    sc.add("rm|0|0|5000|40000|440000", STD_SNAPS, "markers|1", "dump")
    for wt in (0, 40000, 44000, 44001, 120000, 124000, 124001, 200000,
               204000, 250000, 254000, 254001, 300000, 1000000, -4000,
               160000):
        sc.time(wt=wt)
        sc.joy(101)
        sc.joy(102)
    sc.add("snaps|-", "markers|1")
    sc.joy(101)
    sc.joy(102)
    sc.add("dmr|0|0|1")
    sc.joy(101)
    sc.joy(102)
    sc.add("dmr|0|0|0", STD_SNAPS, "objs|%#x" % (ALL & ~(1 << LM(1))),
           "markers|1", "dump")
    sc.time(wt=1000000)
    sc.joy(101)
    sc.time(wt=0)
    sc.joy(102)
    sc.add("objs|%#x" % ALL)
    sc.tag("a marker over the NIS")
    sc.add("player|0|0|0|0|0|1|1|2|0", "change", "dump")
    sc.time(wt=1000000)
    sc.joy(101)
    sc.add("dump", "update", "dump")
    sc.time(wt=0)
    sc.joy(102)
    sc.add("dump", "player|0|0|0|0|0|0|1|2|0", "update", "dump")

    sc.tag("the playback speed")
    for paused, slow in ((0, 0), (0, 1), (1, 0), (1, 1), (0, 2), (2, 0),
                         (0, -1)):
        sc.add("rm|%d|%d|5000|40000|440000" % (paused, slow))
        sc.joy(103)
        sc.add("dump")
    sc.add("dtor|1")

    sc.tag("the camera's target")
    for players in (1, 2, 3, 0):
        sc.base(players=players)
        sc.add("player|1|0|1|0|0|1|0|5|0", "ctor|0")
        sc.joy(105)
        sc.add("dump")
        sc.joy(105)
        sc.add("dump", "dtor|1")
    sc.base(players=2)
    sc.add("player|0|0|0|0|0|1|1|2|0", "ctor|1")
    sc.joy(105)
    sc.add("dump", "dtor|1")

    sc.tag("the help")
    sc.base()
    sc.add("ctor|0")
    for toggle, paused, endcap, wlc in ((1, 0, 5000, 1000), (0, 1, 5000, 1000),
                                        (2, 0, 5000, 1000), (1, 0, 5000, 5000),
                                        (0, 1, 5000, 6000), (-1, 1, 5001, 5000)):
        sc.add("rm|%d|0|%d|40000|440000" % (paused, endcap),
               "ans|0|%d|1|0|1|1" % toggle)
        sc.time(wlc=wlc)
        for value in (1, 0, 255):
            sc.joy(106, value)
            sc.add("dump")
    sc.tag("the help up")
    sc.add("rm|0|0|5000|40000|440000", "ans|1|1|1|0|1|1")
    sc.time(wlc=1000)
    for ev in range(99, 111):
        sc.joy(ev)
        sc.add("dump")
    sc.add("ans|0|0|1|0|1|1")

    sc.tag("one event a loop")
    sc.joy(99)
    sc.joy(99, same_loop=True)
    sc.joy(104, same_loop=True)
    sc.add("dump")
    sc.joy(98)
    sc.joy(104, same_loop=True)
    sc.joy(111)
    sc.joy(104, same_loop=True)
    sc.joy(0)
    sc.joy(200)
    sc.joy(-1)
    sc.add("dump")

    sc.tag("the timeline hidden")
    for _ in range(3):
        sc.joy(107)
        sc.add("dump")
    sc.add("dtor|1")
    sc.base()
    sc.add("ctor|0")
    sc.joy(107)
    sc.add("dtor|1")

    sc.tag("the demo's buttons")
    sc.base()
    sc.add("ctor|0")
    for cd in (1, 0, 2):
        for value in (1, 0, 0x101, 0x100, 2, 255):
            sc.add("ans|0|0|%d|0|1|1" % cd, "rm|1|0|5000|40000|440000")
            sc.joy(108, value)
            sc.add("dump")
    for cantest, play in ((0, 0), (1, 0), (1, 1), (2, 1), (0, 1)):
        sc.add("ans|0|0|1|%d|1|1" % cantest, "dmr|0|0|%d" % play,
               "rm|1|0|5000|40000|440000")
        sc.joy(109)
        sc.add("dump")
    for want, play, value in ((0, 0, 1), (0, 1, 1), (1, 0, 0), (1, 1, 0),
                              (5, 0, 1), (5, 1, 2), (0, 1, 0x100)):
        sc.add("dmr|%d|0|%d" % (want, play))
        sc.joy(110, value)
        sc.add("dump")
    sc.add("dmr|0|0|0")

    sc.tag("the bridge")
    for ev in range(98, 112):
        sc.joy(ev, 1, port=1, bridge=True)
        sc.add("dump")
    sc.joy(108, 0x1ff, bridge=True)
    sc.add("dtor|1")

    sc.tag("pause")
    sc.base()
    sc.add("ctor|0")
    for on in (1, 0, 2, -1, 0x100):
        sc.add("pause|%d" % on, "dump")
    sc.add("dtor|1")

    sc.tag("the destructor")
    for players, nis, mode_presses, hide, flags in (
            (1, 0, 0, 0, 1), (1, 0, 1, 0, 1), (1, 0, 2, 1, 1),
            (1, 0, 3, 0, 0), (1, 1, 0, 0, 1), (2, 1, 1, 1, 3),
            (1, 0, 0, 1, 2)):
        sc.base(players=players)
        sc.add("player|0|0|0|0|0|%d|1|2|0" % nis,
               "rm|1|1|5000|40000|440000", "dmr|1|1|1", "ctor|0")
        for _ in range(mode_presses):
            sc.joy(104)
        if hide:
            sc.joy(107)
        sc.add("dump", "dtor|%d" % flags)
        if not flags & 1:
            sc.add("dump")
        sc.add("dmr|0|0|0")

    random_mix(sc, random.Random(7206), 900)
    return sc.lines


def random_mix(sc, rnd, n):
    sc.tag("random mixes")
    sc.base(players=2)
    sc.add("ctor|0")
    names = list(range(len(SNAP_NAMES)))
    for _ in range(n):
        r = rnd.random()
        if r < 0.06:
            items = []
            laps = demos = 0
            for _ in range(rnd.randrange(0, 12)):
                nm = rnd.choice(names)
                if nm in (N_LAP, N_INSTANT):
                    if laps >= 14:
                        continue
                    laps += 1
                if nm == N_DEMO:
                    if demos >= 16:
                        continue
                    demos += 1
                tm = rnd.randrange(-40000, 480000)
                items.append((nm, tm, tm + rnd.randrange(-4000, 120000)))
            sc.add(snaps(*items))
        elif r < 0.10:
            mask = ALL
            for _ in range(rnd.randrange(0, 6)):
                mask &= ~(1 << rnd.randrange(NUM_OBJS))
            sc.add("objs|%#x" % mask)
        elif r < 0.15:
            begin = rnd.randrange(-8000, 200000)
            sc.add("rm|%d|%d|%d|%d|%d" % (
                rnd.choice((0, 0, 1, 2)), rnd.choice((0, 1, 2)),
                rnd.randrange(0, 4000), begin,
                begin + rnd.randrange(-4000, 600000)))
        elif r < 0.22:
            sc.time(wlc=rnd.randrange(0, 4000),
                    wt=rnd.randrange(-40000, 700000),
                    rtf=rnd.randrange(-100, 1000),
                    rt=sc.t["rt"] + rnd.randrange(0, 40000))
        elif r < 0.26:
            sc.add("race|%d|%d|%d|%d" % (
                rnd.randrange(0, 5), rnd.randrange(0, 9),
                rnd.randrange(0, 1 << 32), rnd.choice((0, 0, 1))))
        elif r < 0.29:
            sc.add("players|%d" % rnd.choice((1, 2, 2)))
        elif r < 0.35:
            sc.add("player|%d|%d|%d|%d|%d|%d|%d|%d|%d" % (
                rnd.randrange(2), rnd.choice((0, 0, 1)),
                rnd.choice((0, 1, 1, 2)), rnd.choice((0, 0, 1)),
                rnd.choice((0, 1)), rnd.choice((0, 0, 0, 1)),
                rnd.randrange(-1, 6), rnd.randrange(0, 9),
                rnd.randrange(-1, 6)))
        elif r < 0.38:
            sc.add("dmr|%d|%d|%d" % (rnd.choice((0, 1)), rnd.choice((0, 1)),
                                     rnd.choice((0, 0, 1))))
        elif r < 0.41:
            sc.add("ans|%d|%d|%d|%d|%d|%d" % (
                rnd.choice((0, 0, 0, 1)), rnd.choice((0, 1)),
                rnd.choice((0, 1, 1)), rnd.choice((0, 1)),
                rnd.choice((0, 1, 1)), rnd.choice((0, 1, 1, 1))))
        elif r < 0.43:
            sc.add("egs|%d" % rnd.choice((0, 1)))
        elif r < 0.62:
            sc.joy(rnd.randrange(98, 112), rnd.choice((0, 1, 1, 255)),
                   port=rnd.randrange(2), bridge=rnd.random() < 0.2,
                   same_loop=rnd.random() < 0.08)
        elif r < 0.72:
            sc.add("update")
        elif r < 0.80:
            sc.add("tick")
        elif r < 0.83:
            sc.add("markers|%d" % rnd.choice((0, 1, 1)))
        elif r < 0.85:
            sc.add("change")
        elif r < 0.86:
            sc.add("stopnis")
        elif r < 0.87:
            sc.add("has", "watch")
        elif r < 0.89:
            sc.add("posx|%s" % fb(rnd.uniform(-200.0, 800.0)))
        elif r < 0.90:
            sc.add("bmpos|%d|%s" % (rnd.randrange(-1, NUM_OBJS),
                                    fb(rnd.uniform(-50.0, 300.0))))
        elif r < 0.96:
            sc.add("dump")
        else:
            sc.add("dtor|%d" % rnd.choice((1, 1, 0)),
                   "ctor|%d" % rnd.randrange(2), "dump")
    sc.add("dump", "dtor|1")


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


# ================================================================= build

def build_harness(tmp, name="replayscreen_test"):
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


def M(name, before, after, rel=RS):
    return (name, rel, before, after)


MUTATIONS = [
    # The constants.
    M("seconds", "SECONDS       0.00025f", "SECONDS       0.00026f"),
    M("hash-timeline", "0xbd2bc882u", "0xbd2bc883u"),
    M("hash-time-marker", "0xb8e8186fu", "0xb8e8186eu"),
    M("hash-instant", "0xadaa0f01u", "0xadaa0f00u"),
    M("hash-demo-playing", "0xacf8f0b5u", "0xacf8f0b4u"),
    M("hash-demo-recording", "0xd32490beu", "0xd32490bfu"),
    M("hash-demo-want", "0x4b53438fu", "0x4b53438eu"),
    M("hash-one-player", "0xc9b7f0c0u", "0xc9b7f0c1u"),
    M("hash-player-number", "0x18b2dbc8u", "0x18b2dbc9u"),
    M("hash-lap", "0x6486623bu", "0x6486623au"),
    M("hash-lap-label", "0x51072bf1u", "0x51072bf0u"),
    M("hash-place", "0x3405c44eu", "0x3405c44fu"),
    M("hash-place-label", "0x98071aa4u", "0x98071aa5u"),
    M("hash-time", "0x15e0f0a8u", "0x15e0f0a9u"),
    M("hash-time-label", "0xd53d9dbeu", "0xd53d9dbfu"),
    M("time-label-id", "LABEL_ID            0x61a8a", "LABEL_ID            0x61a8b"),
    M("bar-height", "HEIGHT               8.0f", "HEIGHT               9.0f"),
    M("bar-y-highlight", "RS_BAR_Y_HIGHLIGHT          46",
      "RS_BAR_Y_HIGHLIGHT          47"),
    M("bar-y-other", "RS_BAR_Y_OTHER              40",
      "RS_BAR_Y_OTHER              41"),
    M("bar-color-highlight", "0x50a040c0u", "0x50a040c1u"),
    M("bar-color-other", "0x80f08020u", "0x80f08021u"),
    M("end-skip-seconds", "SECONDS         4.0f", "SECONDS         4.5f"),
    M("previous-slack", "SLACK           1.0f", "SLACK           1.5f"),
    M("blink-period", "PERIOD             24", "PERIOD             25"),
    M("blink-shown", "SHOWN_FROM         13", "SHOWN_FROM         12"),
    M("mover-size", "MOVER_SIZE  1008", "MOVER_SIZE  1009"),
    M("lookback-speed", "300.9f", "300.8f"),
    M("camera-types", "{ 0, 1, 2, 3 }", "{ 0, 1, 3, 2 }"),
    M("help-id", "802257, 0,", "802258, 0,"),
    M("help-end", "802257, 0,", "802257, 1,"),

    # The calls out.
    M("sample-volume", "(name, 1.0f)", "(name, 0.5f)"),
    M("show-value", "flailerobject_set_visibility(o, v);",
      "flailerobject_set_visibility(o, !v);"),

    # The constructor.
    M("ctor-screen", "screen_visibility(REPLAY_SCREEN_HASH, FLAILER_SCREEN_VISIBLE);"
      + NL + "    s->PlayerNumber",
      "screen_visibility(REPLAY_SCREEN_HASH, FLAILER_SCREEN_INVISIBLE);"
      + NL + "    s->PlayerNumber"),
    M("ctor-player", "s->PlayerNumber = playerNumber;", "s->PlayerNumber = 0;"),
    M("ctor-hide", "s->HideTimeline = 0;" + NL + "    s->LastJoyLoop",
      "s->HideTimeline = 1;" + NL + "    s->LastJoyLoop"),
    M("ctor-last-joy", "s->LastJoyLoop = 0;", "s->LastJoyLoop = 501;"),
    M("ctor-camera", "s->CameraMode = 0;", "s->CameraMode = 1;"),
    M("ctor-end", "(float)rm->EndOfTime * REPLAY_SCREEN_SECONDS;",
      "(float)(rm->EndOfTime + 1) * REPLAY_SCREEN_SECONDS;"),
    M("ctor-begin", "(float)rm->BeginningOfTime * REPLAY_SCREEN_SECONDS;",
      "(float)(rm->BeginningOfTime - 1) * REPLAY_SCREEN_SECONDS;"),
    M("ctor-end-le", "if (s->EndOfTime <= s->BeginningOfTime)",
      "if (s->EndOfTime < s->BeginningOfTime)"),
    M("ctor-end-second", "s->BeginningOfTime + 1.0f;",
      "s->BeginningOfTime + 2.0f;"),
    M("ctor-x-default", "s->TimelinePositionX = 10;",
      "s->TimelinePositionX = 11;"),
    M("ctor-w-default", "s->TimelineWidthX = 100;", "s->TimelineWidthX = 101;"),
    M("ctor-x-round", "(int32_t)o->X;", "(int32_t)(o->X + 0.5f);"),
    M("ctor-w-plus", "(struct FlailerBitmapChunk *)o);" + NL + "    }",
      "(struct FlailerBitmapChunk *)o) + 1;" + NL + "    }"),
    M("ctor-time-marker-type",
      "REPLAY_SCREEN_HASH, RS_TIME_MARKER, FLAILER_TYPE_BITMAP);",
      "REPLAY_SCREEN_HASH, RS_TIME_MARKER, FLAILER_TYPE_ANY);"),
    M("ctor-markers", "replayscreen_setup_markers(s, 1);" + NL + NL
      + "    s->pDemoModeIndicator[0]",
      "replayscreen_setup_markers(s, 0);" + NL + NL
      + "    s->pDemoModeIndicator[0]"),
    M("ctor-indicator-type", "RS_DEMO_PLAYING, FLAILER_TYPE_ANY);",
      "RS_DEMO_PLAYING, FLAILER_TYPE_BITMAP);"),
    M("ctor-indicator-order", "RS_DEMO_RECORDING, FLAILER_TYPE_ANY);",
      "RS_DEMO_WANT_RECORDING, FLAILER_TYPE_ANY);"),
    M("ctor-port-1", "replayscreen_add_joy_handlers(s, 1);",
      "replayscreen_add_joy_handlers(s, 0);"),
    M("ctor-one-player-type",
      "RS_ONE_PLAYER_ONLY," + NL + "                            FLAILER_TYPE_BITMAP);",
      "RS_ONE_PLAYER_ONLY," + NL + "                            FLAILER_TYPE_ANY);"),
    M("ctor-one-player", "PlayerNumPlayers == 1 ? 1 : 0",
      "PlayerNumPlayers <= 1 ? 1 : 0"),
    M("ctor-mute", "gSoundMuteReplayFn(0);" + NL + "    return s;",
      "gSoundMuteReplayFn(1);" + NL + "    return s;"),

    # The destructor.
    M("dtor-hidden", "if (s->HideTimeline)" + NL
      + "        screen_visibility(REPLAY_SCREEN_HIDDEN_HASH",
      "if (!s->HideTimeline)" + NL
      + "        screen_visibility(REPLAY_SCREEN_HIDDEN_HASH"),
    M("dtor-markers", "replayscreen_setup_markers(s, 0);" + NL
      + "    replayscreen_remove_joy_handlers(s, 0);",
      "replayscreen_remove_joy_handlers(s, 0);"),
    M("dtor-port-1", "replayscreen_remove_joy_handlers(s, 1);",
      "replayscreen_remove_joy_handlers(s, 0);"),
    M("dtor-pause", "replayscreen_pause(s, 0);" + NL
      + "    pReplayManager->SlowMotionFlag = 0;",
      "replayscreen_pause(s, 1);" + NL
      + "    pReplayManager->SlowMotionFlag = 0;"),
    M("dtor-slow", "pReplayManager->SlowMotionFlag = 0;" + NL
      + "    if (s->pDriveCameraMover",
      "pReplayManager->SlowMotionFlag = 1;" + NL
      + "    if (s->pDriveCameraMover"),
    M("dtor-mover", "if (s->pDriveCameraMover != NULL)" + NL
      + "        delete_drive_mover(s);" + NL + "    if",
      "if (0)" + NL + "        delete_drive_mover(s);" + NL + "    if"),
    M("dtor-demo-coord", "if (s->pDemoCameraCoordinator != NULL)" + NL
      + "        delete_demo_coordinator(s);" + NL
      + "    replayscreen_stop_watching_nis(s);",
      "if (0)" + NL + "        delete_demo_coordinator(s);" + NL
      + "    replayscreen_stop_watching_nis(s);"),
    M("dtor-nis", "delete_demo_coordinator(s);" + NL
      + "    replayscreen_stop_watching_nis(s);" + NL
      + "    if (gDemoModeReplayEndRecordingFn",
      "delete_demo_coordinator(s);" + NL
      + "    if (gDemoModeReplayEndRecordingFn"),
    M("dtor-end-recording", "gDemoModeReplayEndRecordingFn(0);" + NL
      + "    if (gDemoModeReplayEndDemoModeFn",
      "gDemoModeReplayEndRecordingFn(1);" + NL
      + "    if (gDemoModeReplayEndDemoModeFn"),
    M("dtor-end-demo", "gDemoModeReplayEndDemoModeFn();" + NL
      + "    DemoModeReplay_WantToBeErasingSnapshot = 0;",
      "DemoModeReplay_WantToBeErasingSnapshot = 0;"),
    M("dtor-want", "DemoModeReplay_WantToBeErasingSnapshot = 0;" + NL
      + "    if (flags & 1)",
      "DemoModeReplay_WantToBeErasingSnapshot = 1;" + NL
      + "    if (flags & 1)"),
    M("dtor-flags", "if (flags & 1)", "if (flags & 2)"),
    M("mover-free", "m->vtbl->Destroy(m);" + NL + "    bFree(m);",
      "m->vtbl->Destroy(m);"),

    # The markers.
    M("markers-hide-laps", "for (i = 0; i < s->NumLapMarkers; i++)" + NL
      + "        show(", "for (i = 1; i < s->NumLapMarkers; i++)" + NL
      + "        show("),
    M("markers-hide-hl", "for (i = 0; i < s->NumHighlightMarkers; i++)" + NL
      + "        show(", "for (i = 1; i < s->NumHighlightMarkers; i++)" + NL
      + "        show("),
    M("markers-build", "if (!build)", "if (build)"),
    M("markers-first", "pReplayManager, k++)", "pReplayManager, ++k)"),
    M("markers-lap-name", 'strcmp(snap->Name, "LAP_SNAPSHOT") == 0',
      'strncmp(snap->Name, "LAP_SNAPSHOT", 12) == 0'),
    M("markers-lap-number", '"LAP_MARKER%d", lap++', '"LAP_MARKER%d", ++lap'),
    M("markers-lap-type", "bchunk_hash(name)," + NL
      + "                                             FLAILER_TYPE_BITMAP);"
      + NL + "        } else if (strcmp(snap->Name, \"HIGHLIGHT_SNAPSHOT\")",
      "bchunk_hash(name)," + NL
      + "                                             FLAILER_TYPE_ANY);"
      + NL + "        } else if (strcmp(snap->Name, \"HIGHLIGHT_SNAPSHOT\")"),
    M("markers-demo-name", 'strcmp(snap->Name, "DEMO_MODE_SNAPSHOT") == 0',
      'strncmp(snap->Name, "DEMO_MODE_SNAPSHOT", 17) == 0'),
    M("markers-hl-number", '"HIGHLIGHT_MARKER%d",' + NL
      + "                       s->NumHighlightMarkers);",
      '"HIGHLIGHT_MARKER%d",' + NL
      + "                       s->NumHighlightMarkers - 1);"),
    M("markers-hl-type", "bchunk_hash(name)," + NL
      + "                                             FLAILER_TYPE_BITMAP);"
      + NL + "        } else if (!instant",
      "bchunk_hash(name)," + NL
      + "                                             FLAILER_TYPE_ANY);"
      + NL + "        } else if (!instant"),
    M("markers-instant-once", '} else if (!instant && strcmp(',
      '} else if (strcmp('),
    M("markers-instant-name", 'strcmp(snap->Name, "INSTANT_REPLAY") == 0',
      'strncmp(snap->Name, "INSTANT_REPLAY", 14) == 0'),
    M("markers-instant-flag", "instant = 1;", "instant = 0;"),
    M("markers-instant-type", "RS_INSTANT_REPLAY_MARKER," + NL
      + "                                             FLAILER_TYPE_BITMAP);",
      "RS_INSTANT_REPLAY_MARKER," + NL
      + "                                             FLAILER_TYPE_ANY);"),
    M("markers-no-object", "if (m == NULL || m->pObject == NULL)",
      "if (m == NULL)"),
    M("markers-end", "m->EndTime = (float)snap->EndTime",
      "m->EndTime = (float)snap->Time"),
    M("markers-begin", "m->BeginTime = (float)snap->Time",
      "m->BeginTime = (float)(snap->Time + 4000)"),
    M("markers-shown", "flailerobject_set_visibility(m->pObject, 1);",
      "flailerobject_set_visibility(m->pObject, 0);"),
    M("markers-lap-x", "(float)replayscreen_timeline_position_x(s, m->BeginTime));"
      + NL + "    }" + NL + "    for (i = 0; i < s->NumHighlightMarkers",
      "(float)replayscreen_timeline_position_x(s, m->EndTime));"
      + NL + "    }" + NL + "    for (i = 0; i < s->NumHighlightMarkers"),
    M("markers-bar-end", "w = replayscreen_timeline_position_x(s, m->EndTime);",
      "w = replayscreen_timeline_position_x(s, m->EndTime) + 1;"),
    M("markers-bar-begin", "w -= replayscreen_timeline_position_x(s, m->BeginTime);",
      "w -= s->TimelinePositionX;"),
    M("markers-bar-width", "flailerobject_set_width(m->pObject, (float)w);",
      "flailerobject_set_width(m->pObject, (float)(w + 1));"),
    M("markers-bar-kind",
      'if (strcmp(m->pSnapshot->Name, "HIGHLIGHT_SNAPSHOT") == 0) {',
      'if (strcmp(m->pSnapshot->Name, "HIGHLIGHT_SNAPSHOT") != 0) {'),

    # The NIS and the cameras.
    M("watch-nis", "player_is_nis_playing(player_of(s)) != 0;",
      "player_is_nis_playing(player_of(s)) == 1;"),
    M("stopnis-null", "if (s->pNisCameraCoordinator == NULL)" + NL
      + "        return;", "if (0)" + NL + "        return;"),
    M("stopnis-clear", "s->pNisCameraCoordinator = NULL;" + NL + "}",
      "}"),
    M("has-drive", "return s->pDriveCameraMover != NULL ||",
      "return 0 ||"),
    M("has-demo", "|| s->pDemoCameraCoordinator != NULL" + NL,
      "|| 0" + NL),
    M("has-nis", "|| s->pNisCameraCoordinator != NULL;", "|| 0;"),
    M("mover-align", '"DriveCameraMover", 0, 16);', '"DriveCameraMover", 0, 8);'),
    M("mover-arg-1", "gDriveCameraMoverFn(mem, 1, car,",
      "gDriveCameraMoverFn(mem, 0, car,"),
    M("mover-arg-5", "RS_LOOKBACK_SPEED, 0,", "RS_LOOKBACK_SPEED, 1,"),
    M("mover-arg-7", "lookBack, 1);", "lookBack, 0);"),
    M("blur-zone", "int32_t blur = p->nZoneCurrent != 0;",
      "int32_t blur = p->nZoneCurrent > 0;"),
    M("blur-control", "if (car->TheControlMode == REAL_CONTROL)",
      "if (car->TheControlMode != REAL_CONTROL)"),
    M("blur-nitro", "(RealDriver *)car->pCarDriver) != 0;",
      "(RealDriver *)car->pCarDriver) == 1;"),
    M("blur-value", "gReplayScreenRadialBlurFn(blur);",
      "gReplayScreenRadialBlurFn(!blur);"),
    M("change-mover-null", "delete_drive_mover(s);" + NL
      + "        s->pDriveCameraMover = NULL;", "delete_drive_mover(s);"),
    M("change-coord-null", "delete_demo_coordinator(s);" + NL
      + "        s->pDemoCameraCoordinator = NULL;",
      "delete_demo_coordinator(s);"),
    M("change-stop-nis", "replayscreen_stop_watching_nis(s);" + NL + NL
      + "    if (replayscreen_should_watch_nis(s)) {",
      "if (replayscreen_should_watch_nis(s)) {"),
    M("change-nis-arg", "gNisCreateCameraCoordinatorFn(p->pNisManager, 1)",
      "gNisCreateCameraCoordinatorFn(p->pNisManager, 0)"),
    M("change-nis-return", "return;" + NL + "    }" + NL + "    switch",
      "}" + NL + "    switch"),
    M("change-demo-size", "bMalloc(DEMO_CAMERA_COORDINATOR_SIZE,",
      "bMalloc(DEMO_CAMERA_COORDINATOR_SIZE + 4,"),
    M("change-demo-arg", "16)," + NL + "                1, car);",
      "16)," + NL + "                0, car);"),
    M("change-chase", "new_drive_mover(car, 1, 0);",
      "new_drive_mover(car, 0, 0);"),
    M("change-lookback", "new_drive_mover(car, 1, 1);",
      "new_drive_mover(car, 1, 0);"),
    M("change-bumper", "new_drive_mover(car, 0, 0);",
      "new_drive_mover(car, 0, 1);"),

    # The tick.
    M("tick-end", "if (loops_left(rm) <= 0 && !rm->PausedFlag) {",
      "if (loops_left(rm) < 0 && !rm->PausedFlag) {"),
    M("tick-paused", "&& !rm->PausedFlag) {", "&& rm->PausedFlag != 1) {"),
    M("tick-wrap", "return (int32_t)((uint32_t)rm->EndCapturingLoopCount" + NL
      + "                     - (uint32_t)WorldLoopCounter);",
      "return rm->EndCapturingLoopCount > WorldLoopCounter;"),
    M("tick-ended", "s->ReplayEndedTime = RealTimer;",
      "s->ReplayEndedTime = RealTimer + 1;"),
    M("tick-pause", "replayscreen_pause(s, 1);" + NL + "    }" + NL
      + "    rm = pReplayManager;",
      "replayscreen_pause(s, 2);" + NL + "    }" + NL
      + "    rm = pReplayManager;"),
    M("tick-egs", "pRaceCoordinator->pEndGameScreens != NULL",
      "pRaceCoordinator->pEndGameScreens == NULL"),
    M("tick-skip-end", "&& loops_left(rm) <= 0" + NL,
      "&& loops_left(rm) < 0" + NL),
    M("tick-skip-paused", "&& rm->PausedFlag" + NL + "        && RS_END",
      "&& 1" + NL + "        && RS_END"),
    M("tick-skip-le", "RS_END_SKIP_SECONDS" + NL + "               <",
      "RS_END_SKIP_SECONDS" + NL + "               <="),
    M("tick-timer-wrap", "(float)(int32_t)((uint32_t)RealTimer" + NL
      + "                                  - (uint32_t)s->ReplayEndedTime)",
      "((float)RealTimer - (float)s->ReplayEndedTime)"),
    M("tick-skip-param", "RC_SKIP_REPLAY, 0);" + NL + "    if (DemoModeReplay",
      "RC_SKIP_REPLAY, 1);" + NL + "    if (DemoModeReplay"),
    M("tick-goes-on", "? gDemoModeReplayTestGoesOnFn() : 1) != 1)",
      "? gDemoModeReplayTestGoesOnFn() : 1) == 0)"),
    M("tick-demo-pause", "replayscreen_pause(s, 1);" + NL + "}",
      "replayscreen_pause(s, 0);" + NL + "}"),

    # The indicators.
    M("blink-signed", "!(RealTimeFrames % RS_BLINK_PERIOD",
      "!((uint32_t)RealTimeFrames % RS_BLINK_PERIOD"),
    M("indicator-off", "flailerobject_set_visibility(o, 0);" + NL + "}",
      "flailerobject_set_visibility(o, 1);" + NL + "}"),
    M("indicator-null", "if (o == NULL)" + NL + "        return;" + NL
      + "    if (on)", "if (on)"),

    # The update.
    M("update-markers", "replayscreen_setup_markers(s, 1);" + NL
      + "    replayscreen_set_bitmap_position(",
      "replayscreen_setup_markers(s, 0);" + NL
      + "    replayscreen_set_bitmap_position("),
    M("update-time-marker", "(float)WorldTimer * REPLAY_SCREEN_SECONDS);" + NL
      + "    car = ", "(float)(WorldTimer + 4000) * REPLAY_SCREEN_SECONDS);"
      + NL + "    car = "),
    M("update-player-number", "s->PlayerNumber + 1);" + NL + NL,
      "s->PlayerNumber);" + NL + NL),
    M("update-lap-find",
      "lap = flailer_find_object(REPLAY_SCREEN_HASH, RS_LAP, FLAILER_TYPE_ANY);",
      "lap = flailer_find_object(REPLAY_SCREEN_HASH, RS_LAP_LABEL, FLAILER_TYPE_ANY);"),
    M("update-usage", "if (usage_type(car) == 1) {", "if (usage_type(car) != 0) {"),
    M("update-cop-lap", "show(lap, 0);", "show(lap, 1);"),
    M("update-cop-place-label", "show(placeLabel, 0);" + NL + "    } else {",
      "show(placeLabel, 1);" + NL + "    } else {"),
    M("update-lap-refind", "o = flailer_find_object(REPLAY_SCREEN_HASH, RS_LAP,"
      + NL + "                                FLAILER_TYPE_ANY);", "o = lap;"),
    M("update-one-lap", "if (pCurrentRace->NumLapsInRace == 1",
      "if (pCurrentRace->NumLapsInRace <= 1"),
    M("update-p2p", "|| TheRaceParameters.Point2Point)", "|| 0)"),
    M("update-lap-label-off", "show(o, 0);" + NL + "            show(lapLabel, 0);",
      "show(o, 0);" + NL + "            show(lapLabel, 1);"),
    M("update-lap-n", "int32_t n = rc->NumLapsCompleted + 1;",
      "int32_t n = rc->NumLapsCompleted;"),
    M("update-lap-on", "show(o, 1);" + NL + "            show(lapLabel, 1);",
      "show(o, 0);" + NL + "            show(lapLabel, 1);"),
    M("update-lap-cap", "if (n > pCurrentRace->NumLapsInRace)",
      "if (n > pCurrentRace->NumLapsInRace + 1)"),
    M("update-lap-print", '"%d/%d", n,', '"%d/%d", rc->NumLapsCompleted,'),
    M("update-cars", "cars = pCurrentRace->NumRacingCars;",
      "cars = pCurrentRace->NumRacingCars + 1;"),
    M("update-two-players", "if (PlayerNumPlayers >= 2) {",
      "if (PlayerNumPlayers == 2) {"),
    M("update-other", "int32_t other = (s->PlayerNumber + 1) % PlayerNumPlayers;",
      "int32_t other = (s->PlayerNumber + 2) % PlayerNumPlayers;"),
    M("update-other-usage", "usage_type(PlayerPlayersByNumber[other]->MyCar) == 1)",
      "usage_type(PlayerPlayersByNumber[other]->MyCar) == 0)"),
    M("update-cars-less", "cars--;", "cars -= 2;"),
    M("update-place-two", "if (cars >= 2) {", "if (cars > 2) {"),
    M("update-place-print", "rc->RacePosition, cars);",
      "rc->RacePosition + 1, cars);"),
    M("update-place-on", "show(place, 1);", "show(place, 0);"),
    M("update-place-off", "show(place, 0);" + NL + "            show(placeLabel, 0);"
      + NL + "        }", "show(place, 1);" + NL
      + "            show(placeLabel, 0);" + NL + "        }"),
    M("update-timer-flags", "timer_print_to_string(&t, buf, 0,",
      "timer_print_to_string(&t, buf, 1,"),
    M("update-time-type",
      "o = flailer_find_object(REPLAY_SCREEN_HASH, RS_TIME, FLAILER_TYPE_ANY);",
      "o = flailer_find_object(REPLAY_SCREEN_HASH, RS_TIME, FLAILER_TYPE_BITMAP);"),
    M("update-finish-3", "rc->FinishReason == 2 || rc->FinishReason == 3)",
      "rc->FinishReason == 2 || rc->FinishReason == 4)"),
    M("update-finish-2", "rc->FinishReason == 2 || rc->FinishReason == 3)",
      "rc->FinishReason == 1 || rc->FinishReason == 3)"),
    M("update-finish-hide", "show(o, 0);" + NL + "        flailer_set_language_id",
      "show(o, 1);" + NL + "        flailer_set_language_id"),
    M("update-finish-id", "rc->FinishReason));", "rc->FinishReason + 1));"),
    M("update-time-show", "show(o, 1);" + NL
      + '        flailer_printf(REPLAY_SCREEN_HASH, RS_TIME, "%s", buf);',
      "show(o, 0);" + NL
      + '        flailer_printf(REPLAY_SCREEN_HASH, RS_TIME, "%s", buf);'),
    M("update-indicator-0", "indicator(s->pDemoModeIndicator[0]," + NL
      + "              DemoModeReplay_pCurrentPlayingSnapshot != NULL);",
      "indicator(s->pDemoModeIndicator[0]," + NL
      + "              DemoModeReplay_pCurrentRecordingSnapshot != NULL);"),
    M("update-indicator-1", "indicator(s->pDemoModeIndicator[1],",
      "indicator(s->pDemoModeIndicator[2],"),
    M("update-indicator-2", "DemoModeReplay_WantToBeErasingSnapshot != 0);",
      "DemoModeReplay_WantToBeErasingSnapshot == 1);"),
    M("update-no-camera", "if (!replayscreen_has_camera_mover(s))",
      "if (0)"),
    M("update-nis-started", "if ((replayscreen_should_watch_nis(s) && s->",
      "if ((0 && s->"),
    M("update-nis-stopped", "|| (!replayscreen_should_watch_nis(s)" + NL,
      "|| (0" + NL),

    # The joystick's handlers.
    M("add-last", "ev <= JOY_EVENT_REPLAY_ERASE_DEMO; ev++)" + NL
      + "        AddJoyHandler", "ev < JOY_EVENT_REPLAY_ERASE_DEMO; ev++)" + NL
      + "        AddJoyHandler"),
    M("add-obj", "replayscreen_joy_handler_bridge, s);",
      "replayscreen_joy_handler_bridge, NULL);"),
    M("remove-first", "for (ev = JOY_EVENT_REPLAY_SKIP; ev <= JOY_EVENT_REPLAY_ERASE_DEMO; ev++)"
      + NL + "        RemoveJoyHandler",
      "for (ev = JOY_EVENT_REPLAY_PAUSE; ev <= JOY_EVENT_REPLAY_ERASE_DEMO; ev++)"
      + NL + "        RemoveJoyHandler"),

    # The markers' buttons.
    M("previous-slack-le", "if (RS_PREVIOUS_SLACK <", "if (RS_PREVIOUS_SLACK <="),
    M("previous-last", "            found = &s->LapMarkers[i];" + NL
      + "    return found;", "            return &s->LapMarkers[i];" + NL
      + "    return found;"),
    M("next-lt", "< s->LapMarkers[i].BeginTime)", "<= s->LapMarkers[i].BeginTime)"),
    M("next-first", "            return &s->LapMarkers[i];" + NL
      + "    return NULL;", "            return &s->LapMarkers[0];" + NL
      + "    return NULL;"),

    # The joystick.
    M("joy-help-any", "if (ev != JOY_EVENT_REPLAY_HELP && gReplayScreenHelpActiveFn",
      "if (gReplayScreenHelpActiveFn"),
    M("joy-help-active", "&& gReplayScreenHelpActiveFn())",
      "&& !gReplayScreenHelpActiveFn())"),
    M("joy-same-loop", "if (RealLoopCounter == s->LastJoyLoop)", "if (0)"),
    M("joy-last-loop", "s->LastJoyLoop = RealLoopCounter;", "(void)0;"),
    M("skip-sample", 'play_sample("MenuUpDown");' + NL
      + "        racecoordinator_post_message",
      'play_sample("MenuLeftRight");' + NL
      + "        racecoordinator_post_message"),
    M("skip-param", "RC_SKIP_REPLAY, 0);" + NL + "        break;",
      "RC_SKIP_REPLAY, 1);" + NL + "        break;"),
    M("pause-not-paused", "if (!rm->PausedFlag)" + NL
      + "            replayscreen_pause(s, 1);",
      "if (rm->PausedFlag != 1)" + NL
      + "            replayscreen_pause(s, 1);"),
    M("pause-at-end", "else if (loops_left(rm) > 0)",
      "else if (loops_left(rm) >= 0)"),
    M("pause-resume", "replayscreen_pause(s, 0);" + NL + "        break;" + NL
      + NL + "    case JOY_EVENT_REPLAY_PREVIOUS_MARKER:",
      "replayscreen_pause(s, 1);" + NL + "        break;" + NL
      + NL + "    case JOY_EVENT_REPLAY_PREVIOUS_MARKER:"),
    M("marker-sample", 'play_sample("MenuLeftRight");', 'play_sample("MenuUpDown");'),
    M("marker-demo", "if (DemoModeReplay_pCurrentPlayingSnapshot != NULL) {" + NL
      + "            if (gDemoModeReplayServiceDemoModeFn",
      "if (DemoModeReplay_pCurrentPlayingSnapshot == NULL) {" + NL
      + "            if (gDemoModeReplayServiceDemoModeFn"),
    M("marker-service-dir", "ev == JOY_EVENT_REPLAY_NEXT_MARKER);",
      "ev != JOY_EVENT_REPLAY_NEXT_MARKER);"),
    M("marker-swap", "? previous_marker(s)" + NL
      + "                                                    : next_marker(s);",
      "? next_marker(s)" + NL
      + "                                                    : previous_marker(s);"),
    M("marker-unpause", "replayscreen_pause(s, 0);" + NL
      + "        replayscreen_stop_watching_nis(s);" + NL
      + "        racecoordinator_post_message",
      "replayscreen_pause(s, 1);" + NL
      + "        replayscreen_stop_watching_nis(s);" + NL
      + "        racecoordinator_post_message"),
    M("marker-stop-nis", "replayscreen_stop_watching_nis(s);" + NL
      + "        racecoordinator_post_message(pRaceCoordinator, RC_MOVE_REPLAY,",
      "racecoordinator_post_message(pRaceCoordinator, RC_MOVE_REPLAY,"),
    M("marker-message", "RC_MOVE_REPLAY,", "RC_SKIP_REPLAY,"),
    M("speed-paused", "if (rm->PausedFlag) {", "if (rm->PausedFlag == 1) {"),
    M("speed-slow", "pReplayManager->SlowMotionFlag = 1;",
      "pReplayManager->SlowMotionFlag = 0;"),
    M("speed-toggle", "rm->SlowMotionFlag = rm->SlowMotionFlag ? 0 : 1;",
      "rm->SlowMotionFlag = rm->SlowMotionFlag == 1 ? 0 : 1;"),
    M("angle-wrap", "(s->CameraMode + 1) & 3;", "(s->CameraMode + 1) % 3;"),
    M("angle-sound", "frontend_sound(3);", "frontend_sound(4);"),
    M("angle-change", "replayscreen_change_camera_mover(s);" + NL
      + "        frontend_sound(3);", "frontend_sound(3);"),
    M("target-two", "if (PlayerNumPlayers != 2)", "if (PlayerNumPlayers < 2)"),
    M("target-stop-nis", "replayscreen_stop_watching_nis(s);" + NL
      + "        s->PlayerNumber = other;", "s->PlayerNumber = other;"),
    M("target-switch", "s->PlayerNumber = other;",
      "s->PlayerNumber = s->PlayerNumber;"),
    M("target-sound", "frontend_sound(5);" + NL + "        break;" + NL + NL
      + "    case JOY_EVENT_REPLAY_HELP:", "frontend_sound(3);" + NL
      + "        break;" + NL + NL + "    case JOY_EVENT_REPLAY_HELP:"),
    M("help-value", "(ReplayScreenHelpIDs, value)", "(ReplayScreenHelpIDs, 1)"),
    M("help-at-end", "if (loops_left(pReplayManager) <= 0)",
      "if (loops_left(pReplayManager) < 0)"),
    M("help-pause", "replayscreen_pause(s, active ? 1 : 0);",
      "replayscreen_pause(s, active);"),
    M("hide-toggle", "s->HideTimeline = s->HideTimeline == 0;",
      "s->HideTimeline = 1;"),
    M("hide-hidden-on", "FLAILER_SCREEN_VISIBLE);" + NL + "        } else {",
      "FLAILER_SCREEN_INVISIBLE);" + NL + "        } else {"),
    M("hide-screen-on", "screen_visibility(REPLAY_SCREEN_HASH, FLAILER_SCREEN_VISIBLE);"
      + NL + "        }", "screen_visibility(REPLAY_SCREEN_HASH, FLAILER_SCREEN_INVISIBLE);"
      + NL + "        }"),
    M("hide-sound", "frontend_sound(5);" + NL + "        break;" + NL + NL
      + "    case JOY_EVENT_REPLAY_MARK_DEMO:", "frontend_sound(3);" + NL
      + "        break;" + NL + NL + "    case JOY_EVENT_REPLAY_MARK_DEMO:"),
    M("mark-cd", "|| gReplayScreenIsThereACDFn())",
      "|| gReplayScreenIsThereACDFn() == 1)"),
    M("mark-value", "if (value) {", "if (value == 1) {"),
    M("mark-total", "DemoDiscManager_TotalTimeout = 32767;",
      "DemoDiscManager_TotalTimeout = 32766;"),
    M("mark-inactive", "DemoDiscManager_InactiveTimeout = 32767;",
      "DemoDiscManager_InactiveTimeout = 32766;"),
    M("mark-begin", "gDemoModeReplayBeginRecordingFn();" + NL
      + "        } else if", "(void)0;" + NL + "        } else if"),
    M("mark-end", "gDemoModeReplayEndRecordingFn(0);" + NL + "        }",
      "gDemoModeReplayEndRecordingFn(1);" + NL + "        }"),
    M("test-can", "|| !gDemoModeReplayCanTestFn())",
      "|| gDemoModeReplayCanTestFn() != 1)"),
    M("test-playing", "if (DemoModeReplay_pCurrentPlayingSnapshot == NULL) {",
      "if (DemoModeReplay_pCurrentPlayingSnapshot != NULL) {"),
    M("test-unpause", "replayscreen_pause(s, 0);" + NL + "        break;" + NL
      + NL + "    case JOY_EVENT_REPLAY_ERASE_DEMO:",
      "replayscreen_pause(s, 1);" + NL + "        break;" + NL
      + NL + "    case JOY_EVENT_REPLAY_ERASE_DEMO:"),
    M("erase-value", "if (!value)", "if (value != 1)"),
    M("erase-off", "DemoModeReplay_WantToBeErasingSnapshot = 0;" + NL
      + "        else if", "DemoModeReplay_WantToBeErasingSnapshot = 2;" + NL
      + "        else if"),
    M("erase-playing", "else if (DemoModeReplay_pCurrentPlayingSnapshot != NULL)",
      "else if (DemoModeReplay_pCurrentPlayingSnapshot == NULL)"),
    M("erase-on", "DemoModeReplay_WantToBeErasingSnapshot = 1;" + NL
      + "        break;", "DemoModeReplay_WantToBeErasingSnapshot = 2;" + NL
      + "        break;"),

    # The time's place.
    M("posx-width", "(float)s->TimelineWidthX" + NL,
      "(float)(s->TimelineWidthX + 1)" + NL),
    M("posx-round", "return (int32_t)((float)s->TimelineWidthX",
      "return (int32_t)(0.5f + (float)s->TimelineWidthX"),
    M("posx-span", "/ (s->EndOfTime - s->BeginningOfTime)))",
      "/ (s->EndOfTime - s->BeginningOfTime + 1.0f)))"),
    M("posx-begin", "* ((t - s->BeginningOfTime)", "* ((t - 0.0f)"),
    M("posx-x", "+ s->TimelinePositionX;", "- s->TimelinePositionX;"),
    M("bmpos-null", "if (b != NULL)" + NL + "        flailerobject_set_top_left_x(",
      "flailerobject_set_top_left_x("),
    M("pause-flag", "pReplayManager->PausedFlag = on;",
      "pReplayManager->PausedFlag = on != 0;"),
    M("pause-mute", "gSoundMuteReplayFn(on != 0);", "gSoundMuteReplayFn(on);"),
    M("bridge-value", "port, ev, value);", "port, ev, 1);"),
]

EQUIVALENT = {
    "bar-y-highlight": "a highlight marker's bar is green only for a "
                       "HIGHLIGHT_SNAPSHOT, and the highlight list holds only "
                       "DEMO_MODE_SNAPSHOTs; retail's test is as dead",
    "bar-color-highlight": "as bar-y-highlight",
    "tick-skip-paused": "Tick's first test pauses the replay whenever the "
                        "capture has ended, so PausedFlag is set by the "
                        "second; retail reads it again all the same",
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
        todo, SOURCES, "replayscreen_test",
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
