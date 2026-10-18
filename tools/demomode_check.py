#!/usr/bin/env python3
"""Cross-check 3DS Files/source/demomode.c and rcdemo.c, attract mode's race
and the race coordinator's two demo states, against the retail image,
SLES_507.31 (TASKS 72h-2b).

**The model** is retail's BuildDemoTrackList (0x0016ec10), StartDemoMode
(0x0016ecd8), FrontendDatabase::StartDemoMode (0x00184d48) and
RaceCoordinator's RCStateAIDemoModeCallback (0x0014a8c0) and
RCStateReplayDemoModeCallback (0x0014aa38), run in retail_model.RetailEmu.
The harness (tools/src/demomode_test.c) runs demomode.c and rcdemo.c.

**The stubs** print what they are asked, on both sides: GetTrackInfo
(0x00153420), from a table the script fills; FrontendDatabase::StartRace
(0x00184f68); SetFlailerScreenVisibility (0x0014cbf8); AddJoyHandler and
RemoveJoyHandler (0x00154140, 0x001541e8); the coordinator's ChangeState,
SendMessage, ResumeDemoCameras and SuspendDemoCameras (0x00149520,
0x00149650, 0x0014a818, 0x0014a878); TheDemoModeReplay's BeginDemoMode,
EndDemoMode and TestGoesOn (0x0013f288, 0x0013f4f0, 0x0013f310); the
ReplayManager's RestoreSnapshot (0x0013eb38); the type-changed handlers'
reinstall (0x001543f0); and the demo camera's virtual destructor, through
its vtable.

**Differences made equal by hand.** StartDemoMode stops the menu's movie
in retail and the port's flow does it before the call (gameflow.c): the
model stubs StopMovie (0x0016d0a0) silently. Retail picks track 12 when
DemoDiscManager.bActive (0x002effe0) is set, and the port has no demo
disc: the model keeps it 0. Retail traps on an empty track list and the
port takes the first entry; the script never starts on one. Retail reads
pCurrentRace unchecked and the port answers 0 seconds without one; the
model's NULL reads low memory, which is 0, so the same.

**The script** sends every message, in and out of range, to both states
with the camera there and not; runs the AI demo's tick around its timeout
with each race time and each odd timeout; builds the track list from
every mix of the table; and starts the demo over each count, list and
direction.

    python tools/demomode_check.py
    python tools/demomode_check.py --mutate [--only a,b]
    python tools/demomode_check.py --dump out/demomode
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
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/demomode_test.c"
DM = "3DS Files/source/demomode.c"
DH = "3DS Files/source/demomode.h"
RD = "3DS Files/source/rcdemo.c"
RDH = "3DS Files/source/rcdemo.h"
SOURCES = [HARNESS, DM, RD]
HARNESS_TIMEOUT = 120

GP = retail_model.RETAIL_GP
P_REPLAY = GP - 22440                   # pReplayManager
P_RACE = GP - 22272                     # pCurrentRace
CONFIG_TRACK = GP - 23256               # TrackSelectedInConfigFile
HIGHEST = GP - 21944                    # HighestTrackNumber
NUM_TRACKS = GP - 21168                 # NumDemoableTracks
BUILT = GP - 21164
COUNT = GP - 21160
DIRECTION = GP - 23104                  # TrackDirectionForDemoMode
TIMEOUT = GP - 23096                    # DemoModeTimeout
DEMOABLE = 0x002fb288                   # DemoableTracks
FRED = 0x002fc050
FRED_STATUS = FRED + 384                # DemoModeStatus
FRED_GAME_TYPE = FRED + 67372
PARAMS = 0x0031a898                     # TheRaceParameters
DEMO_DISC = 0x002effe0                  # DemoDiscManager.bActive
DEMO_REPLAY = 0x002f0960                # TheDemoModeReplay
JOY_HANDLER = 0x0014a7f8                # RaceCoordinator's JoystickHandler

F_BUILD = 0x0016ec10
F_START = 0x0016ecd8
F_FRED = 0x00184d48
F_AI = 0x0014a8c0
F_RD = 0x0014aa38

S_TRACK_INFO = 0x00153420
S_START_RACE = 0x00184f68
S_STOP_MOVIE = 0x0016d0a0
S_VISIBILITY = 0x0014cbf8
S_ADD_JOY = 0x00154140
S_REMOVE_JOY = 0x001541e8
S_CHANGE = 0x00149520
S_SEND = 0x00149650
S_RESUME = 0x0014a818
S_SUSPEND = 0x0014a878
S_BEGIN = 0x0013f288
S_END = 0x0013f4f0
S_GOES = 0x0013f310
S_RESTORE = 0x0013eb38
S_HANDLERS = 0x001543f0

NUM_INFOS = 64
INFO_SIZE = 164
NUM_SNAPS = 4
MAX_TRACKS = 32
PARAMS_DUMPED = 652

# ================================================================= the model


class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        self.rc = e.alloc(64, 16)
        self.rm = e.alloc(256, 16)
        self.race = e.alloc(64, 16)
        self.snaps = e.alloc(NUM_SNAPS * 64, 16)
        self.cam = e.alloc(64, 16)
        self.vtbl = e.alloc(32, 16)
        self.dtor = e.alloc(16, 16)
        self.infos = e.alloc(NUM_INFOS * INFO_SIZE, 16)
        for blk, n in ((self.rc, 64), (self.rm, 256), (self.race, 64),
                       (self.snaps, NUM_SNAPS * 64), (self.cam, 64),
                       (self.vtbl, 32), (self.infos, NUM_INFOS * INFO_SIZE)):
            e.write(blk, bytes(n))
        e.write(0, bytes(64))
        e.put32(self.cam + 24, self.vtbl)
        e.put32(self.vtbl + 12, self.dtor)
        e.put32(P_REPLAY, self.rm)
        e.put32(P_RACE, 0)
        e.put32(DEMO_DISC, 0)
        e.put32(DIRECTION, 0)
        e.put32(TIMEOUT, 0x42f00000)            # 120.0
        e.put32(CONFIG_TRACK, M32)
        for a in (HIGHEST, NUM_TRACKS, BUILT, COUNT, FRED_STATUS,
                  FRED_GAME_TYPE):
            e.put32(a, 0)
        e.write(DEMOABLE, bytes(4 * MAX_TRACKS))
        e.write(PARAMS, bytes(PARAMS_DUMPED))
        self.info_on = [0] * NUM_INFOS
        self.goes = 0

        for a, fn in ((S_TRACK_INFO, self.track_info),
                      (S_START_RACE, self.ptr_say("start race")),
                      (S_STOP_MOVIE, lambda _e: None),
                      (S_VISIBILITY, self.visibility),
                      (S_ADD_JOY, self.add_joy),
                      (S_REMOVE_JOY, self.remove_joy),
                      (S_CHANGE, self.change), (S_SEND, self.send),
                      (S_RESUME, self.ptr_say("resume")),
                      (S_SUSPEND, self.ptr_say("suspend")),
                      (S_BEGIN, self.replay_say("begin demo")),
                      (S_END, self.replay_say("end demo")),
                      (S_GOES, self.goes_on), (S_RESTORE, self.restore),
                      (S_HANDLERS, self.handlers), (self.dtor, self.delete)):
            e.stub(a, fn)

    def emit(self, s):
        self.out.append(s)

    def arg(self, i):
        return self.e.reg[4 + i] & M32

    def sarg(self, i):
        return s32(self.e.reg[4 + i])

    def label(self, p):
        p &= M32
        if p == 0:
            return "NULL"
        named = {self.rc: "RC", self.rm: "RM", self.cam: "CAM", FRED: "FRED",
                 JOY_HANDLER: "H"}
        if p in named:
            return named[p]
        base = self.snaps
        if base <= p < base + 64 * NUM_SNAPS and (p - base) % 64 == 0:
            return "S%d" % ((p - base) // 64)
        return "%d" % s32(p)

    # ---- the stubs

    def ptr_say(self, what):
        def fn(e):
            self.emit("  %s %s" % (what, self.label(self.arg(0))))
        return fn

    def replay_say(self, what):
        """TheDemoModeReplay's methods; the port's take no `this`."""
        def fn(e):
            if self.arg(0) != DEMO_REPLAY:
                what_ = "%s on %s" % (what, self.label(self.arg(0)))
            else:
                what_ = what
            self.emit("  " + what_)
        return fn

    def track_info(self, e):
        i = self.sarg(0)
        self.emit("  track info %d" % i)
        if 0 <= i < NUM_INFOS and self.info_on[i]:
            return self.infos + INFO_SIZE * i
        return 0

    def visibility(self, e):
        self.emit("  vis %08x %d" % (self.arg(0), self.sarg(1)))

    def add_joy(self, e):
        self.emit("  add joy %d %d %s %s" % (
            self.sarg(0), self.sarg(1), self.label(self.arg(2)),
            self.label(self.arg(3))))

    def remove_joy(self, e):
        self.emit("  remove joy %d %d" % (self.sarg(0), self.sarg(1)))

    def change(self, e):
        self.emit("  change %s %d" % (self.label(self.arg(0)), self.sarg(1)))

    def send(self, e):
        self.emit("  send %s %d %d" % (self.label(self.arg(0)), self.sarg(1),
                                       self.sarg(2)))

    def goes_on(self, e):
        self.replay_say("goes on")(e)
        return self.goes

    def restore(self, e):
        self.emit("  restore %s %s" % (self.label(self.arg(0)),
                                       self.label(self.arg(1))))

    def handlers(self, e):
        self.emit("  type handlers")

    def delete(self, e):
        """The camera's virtual destructor, flags 3: delete it."""
        flags = self.sarg(1)
        self.emit("  camera delete %s%s" % (
            self.label(self.arg(0)), "" if flags == 3 else " flags %d" % flags))

    # ---- the dumps

    def dump_list(self):
        e = self.e
        self.emit("  built %d num %d count %d config %d highest %d" % (
            s32(e.u32(BUILT)), s32(e.u32(NUM_TRACKS)), s32(e.u32(COUNT)),
            s32(e.u32(CONFIG_TRACK)), s32(e.u32(HIGHEST))))
        self.emit("  tracks" + "".join(
            " %d" % s32(e.u32(DEMOABLE + 4 * i)) for i in range(MAX_TRACKS)))

    def dump_params(self):
        e = self.e
        for off in range(0, PARAMS_DUMPED, 4):
            self.emit("  rp %d %08x" % (off, e.u32(PARAMS + off)))
        self.emit("  gametype %d status %d" % (s32(e.u32(FRED_GAME_TYPE)),
                                               s32(e.u32(FRED_STATUS))))

    def dump_rc(self):
        self.emit("  cam %s status %d" % (self.label(self.e.u32(self.rc + 28)),
                                          s32(self.e.u32(FRED_STATUS))))

    # ---- the ops

    def call(self, fn, *args):
        return self.e.call(fn, *args, limit=200000)

    def op(self, a):
        e = self.e
        op = a[0]
        if op == "tag":
            return
        v = [int(x, 0) for x in a[1:]]
        if op == "info":
            self.info_on[v[0]] = v[1]
            e.mem[self.infos + INFO_SIZE * v[0] + 67] = v[2] & 0xff
        elif op == "list":
            for addr, x in zip((BUILT, NUM_TRACKS, COUNT, CONFIG_TRACK,
                                HIGHEST), v):
                e.put32(addr, x)
            for i in range(MAX_TRACKS):
                e.put32(DEMOABLE + 4 * i, 900 + i)
        elif op == "fill":
            for off in range(0, PARAMS_DUMPED, 4):
                e.put32(PARAMS + off, v[0] + off)
            e.put32(FRED_GAME_TYPE, v[0] + 1)
            e.put32(FRED_STATUS, v[0] + 2)
        elif op == "dir":
            e.put32(DIRECTION, v[0])
        elif op == "build":
            self.call(F_BUILD)
            self.dump_list()
        elif op == "start":
            self.call(F_START)
            self.dump_list()
            self.dump_params()
        elif op == "fred":
            self.call(F_FRED, FRED, v[0])
            self.dump_params()
        elif op == "race":
            e.put32(P_RACE, self.race if v[0] else 0)
            e.put32(self.race + 16, v[1])
        elif op == "timeout":
            e.put32(TIMEOUT, v[0])
        elif op == "cam":
            e.put32(self.rc + 28, self.cam if v[0] else 0)
        elif op == "goes":
            self.goes = v[0]
        elif op in ("ai", "rd"):
            r = self.call(F_AI if op == "ai" else F_RD, self.rc, v[0], v[1])
            self.emit("  -> %d" % s32(r))
            self.dump_rc()
        elif op == "move":
            r = self.call(F_RD, self.rc, 14, self.snaps + 64 * v[0])
            self.emit("  -> %d" % s32(r))
            self.dump_rc()
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

MSGS = list(range(1, 15))
ACTIVATE, UNACTIVATE, TICK, SKIP, QUIT_RACE = 1, 2, 3, 4, 10
SKIP_REPLAY, TAKE_AUTOSNAPSHOT, MOVE_REPLAY = 11, 13, 14
ODD_MSGS = [0, -1, 15, 16, 99, -100, 0x7fffffff, -0x80000000]

# Float bits: 120.0, 0.0, -0.0, -1.0, 1.0, 0.00025, 60.0, the smallest
# denormal, +inf, -inf, a NaN, the largest float.
TIMEOUTS = [0x42f00000, 0x00000000, 0x80000000, 0xbf800000, 0x3f800000,
            0x39831270, 0x42700000, 0x00000001, 0x7f800000, 0xff800000,
            0x7fc00000, 0x7f7fffff]
# Race ticks: around 120 s (480000), around 60 s, and the extremes.
TIMES = [0, 1, -1, 479999, 480000, 480001, 480004, 480005, 239999, 240000,
         240001, 4000, 4001, 0x7fffffff, -0x80000000, 16777217, 16777219,
         -480001]


class Script(object):
    def __init__(self):
        self.lines = []

    def add(self, *lines):
        self.lines.extend(lines)

    def tag(self, text):
        self.add("tag|" + text)

    def info(self, i, on, p2p=0):
        self.add("info|%d|%d|%d" % (i, on, p2p))

    def table(self, specs):
        """Each spec None for no track, else its Point2Point byte."""
        for i in range(NUM_INFOS):
            s = specs[i] if i < len(specs) else None
            self.info(i, 0 if s is None else 1, 0 if s is None else s)

    def list(self, built, num, count, config, highest):
        self.add("list|%d|%d|%d|%d|%d" % (built, num, count, config, highest))

    def msg(self, which, m, param=0):
        self.add("%s|%d|%d" % (which, m, param))


def script():
    sc = Script()
    rnd = random.Random(7282)

    sc.tag("the direction and timeout as they start")
    sc.add("fill|0", "fred|3")

    sc.tag("every message, each state")
    sc.add("race|1|4000", "goes|1")
    for which in ("ai", "rd"):
        for cam in (0, 1):
            for m in ODD_MSGS + MSGS:
                sc.add("cam|%d" % cam)
                sc.msg(which, m, 5)
            sc.add("cam|1")
            sc.add("move|%d" % (cam + 1))

    sc.tag("the AI demo's timeout")
    for timeout in TIMEOUTS:
        sc.add("timeout|%d" % timeout)
        for t in TIMES:
            sc.add("race|1|%d" % t)
            sc.msg("ai", TICK)
        sc.add("race|0|480001")
        sc.msg("ai", TICK)
    for _ in range(300):
        sc.add("timeout|%d" % rnd.choice(
            TIMEOUTS + [rnd.getrandbits(32), 0x42f00000]))
        sc.add("race|%d|%d" % (rnd.random() < 0.9,
                               rnd.choice(TIMES + [s32(rnd.getrandbits(32)),
                                                   rnd.randrange(480100)])))
        sc.msg("ai", TICK)
    sc.add("timeout|%d" % 0x42f00000)

    sc.tag("the replay demo's tick")
    for goes in (0, 1, -1, 2, 0x7fffffff, -0x80000000):
        sc.add("goes|%d" % goes)
        sc.msg("rd", TICK, 3)

    sc.tag("the camera through unactivate")
    for which in ("ai", "rd"):
        for cam in (1, 0, 1):
            sc.add("cam|%d" % cam)
            sc.msg(which, UNACTIVATE, cam)
            sc.msg(which, UNACTIVATE)

    sc.tag("move")
    for k in range(NUM_SNAPS):
        for cam in (0, 1):
            sc.add("cam|%d" % cam, "move|%d" % k)
    for param in (0, 1, -1, 64, 0x7fffffff, -0x80000000):
        sc.msg("rd", MOVE_REPLAY, param)

    sc.tag("a demo through")
    for which, goes in (("ai", 1), ("rd", 1), ("rd", 0)):
        sc.add("cam|1", "race|1|0", "goes|%d" % goes)
        sc.msg(which, ACTIVATE)
        for t in (4000, 480000, 480004):
            sc.add("race|1|%d" % t)
            sc.msg(which, TICK)
        sc.msg(which, TAKE_AUTOSNAPSHOT)
        sc.msg(which, SKIP)
        sc.msg(which, QUIT_RACE)
        sc.msg(which, UNACTIVATE)

    sc.tag("the track list: the config's track")
    sc.table([0] * 10)
    for config in (0, 1, 5, 12, -2, 99, 0x7fffffff, -0x80000000):
        for built in (0, 1):
            sc.list(built, 3, 0, config, 9)
            sc.add("build")

    sc.tag("the track list: from the table")
    tables = [
        [0] * NUM_INFOS,
        [None] * NUM_INFOS,
        [1] * NUM_INFOS,
        [None, 0, 1, 0, None, 0, -1, 0, 0x80, 0, 2, 0],
        [0, 1] * 32,
        [None] + [0] * 40,
        [0x7f, 0, 0, 0, 0xff, 0],
    ]
    for _ in range(12):
        tables.append([rnd.choice((None, 0, 0, 1, -1, 0x80, 0x40))
                       for _ in range(NUM_INFOS)])
    for specs in tables:
        sc.table(specs)
        for highest in (-1, 0, 1, 2, 5, 11, 31, 32, 33, 40, 63, 64, 70):
            sc.list(0, 99, 0, -1, highest)
            sc.add("build")
        sc.list(1, 7, 0, -1, 40)
        sc.add("build")

    sc.tag("start: a built list")
    sc.add("dir|0")
    for num in (1, 2, 3, 7, 13, 31, 32):
        for count in (0, 1, 6, 7, 8, 13, 14, 100, 12345, 0x7ffffff8,
                      0x7ffffffc, 0x7fffffff):
            sc.add("fill|%d" % rnd.getrandbits(32))
            sc.list(1, num, count, rnd.choice((-1, 4)), 20)
            sc.add("start")

    sc.tag("start: built on the way")
    for specs in tables:
        if not any(s == 0 for s in specs[1:NUM_INFOS]):
            continue
        sc.table(specs)
        for count in (0, 7, 21, 0x7ffffff8):
            sc.add("fill|%d" % rnd.getrandbits(32))
            sc.list(0, 0, count, -1, 63)
            sc.add("start")
    sc.table([0] * NUM_INFOS)
    for config in (3, 0, 17, -2):
        sc.add("fill|%d" % rnd.getrandbits(32))
        sc.list(0, 0, 5, config, 9)
        sc.add("start")

    sc.tag("start: running on")
    sc.table([rnd.choice((None, 0, 1)) for _ in range(30)] + [0])
    sc.list(0, 0, 0, -1, 30)
    for _ in range(40):
        sc.add("start")

    sc.tag("start: each direction")
    for d in (0, 1, -1, 2, 7, 0x7fffffff, -0x80000000):
        sc.add("dir|%d" % d, "fill|%d" % rnd.getrandbits(32))
        sc.list(1, 5, d & 0xff, -1, 9)
        sc.add("start")
    sc.add("dir|0")

    sc.tag("FrontendDatabase::StartDemoMode")
    for track in (0, 1, 2, 12, 31, -1, 99, 0x7fffffff, -0x80000000):
        for seed in (0, 0xffffffff, rnd.getrandbits(32)):
            sc.add("fill|%d" % seed, "fred|%d" % track)
    for d in (1, -3):
        sc.add("dir|%d" % d, "fill|%d" % rnd.getrandbits(32), "fred|4")
    sc.add("dir|0")

    random_mix(sc, random.Random(7283), 1200)
    return sc.lines


def random_mix(sc, rnd, n):
    """No start goes on a list that could come out empty: retail traps."""
    sc.tag("random")
    sc.table([0] * NUM_INFOS)
    for _ in range(n):
        r = rnd.random()
        if r < 0.05:
            sc.add("timeout|%d" % rnd.choice(TIMEOUTS))
        elif r < 0.12:
            sc.add("race|%d|%d" % (rnd.random() < 0.9, rnd.choice(TIMES)))
        elif r < 0.18:
            sc.add("cam|%d" % rnd.randrange(2))
        elif r < 0.22:
            sc.add("goes|%d" % rnd.choice((0, 1, 1, 2)))
        elif r < 0.26:
            sc.add("dir|%d" % rnd.choice((0, 0, 1, -1)))
        elif r < 0.30:
            sc.add("fill|%d" % rnd.getrandbits(32))
        elif r < 0.34:
            sc.list(rnd.randrange(2), rnd.randrange(1, 33),
                    rnd.randrange(1000), rnd.choice((-1, -1, 3)),
                    rnd.choice((1, 9, 40, 63)))
            sc.add(rnd.choice(("start", "build")))
        elif r < 0.37:
            sc.add("fred|%d" % rnd.randrange(-2, 40))
        elif r < 0.42:
            sc.add("move|%d" % rnd.randrange(NUM_SNAPS))
        else:
            sc.msg(rnd.choice(("ai", "rd")),
                   rnd.choice(MSGS + [TICK, TICK, TICK, 0, 15]),
                   rnd.randrange(-3, 4))


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


# ================================================================= build


def build_harness(tmp, name="demomode_test"):
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


def M(name, before, after, rel=RD):
    return (name, rel, before, after)


MUTATIONS = [
    # demomode.c: the list.
    M("built-skip", "if (DemoTrackListBuilt != 0)\n        return;",
      "if (DemoTrackListBuilt == 0)\n        return;", rel=DM),
    M("built-set", "    DemoTrackListBuilt = 1;", "    DemoTrackListBuilt = 0;",
      rel=DM),
    M("config-none", "if (TrackSelectedInConfigFile != -1)",
      "if (TrackSelectedInConfigFile != 0)", rel=DM),
    M("config-slot", "DemoableTracks[0] = TrackSelectedInConfigFile;",
      "DemoableTracks[1] = TrackSelectedInConfigFile;", rel=DM),
    M("config-num", "NumDemoableTracks = 1;", "NumDemoableTracks = 2;",
      rel=DM),
    M("loop-from-0", "for (i = 1; i <= HighestTrackNumber; i++)",
      "for (i = 0; i <= HighestTrackNumber; i++)", rel=DM),
    M("loop-lt", "i <= HighestTrackNumber", "i < HighestTrackNumber", rel=DM),
    M("p2p-test", "t->Point2Point == 0", "t->Point2Point != 0", rel=DM),
    M("p2p-dropped", "t != NULL && t->Point2Point == 0 &&", "t != NULL &&",
      rel=DM),
    M("p2p-sign", "t->Point2Point == 0", "(t->Point2Point & 0x7f) == 0",
      rel=DM),
    M("cap", "n < DEMO_MODE_MAX_TRACKS)", "n < DEMO_MODE_MAX_TRACKS - 1)",
      rel=DM),
    M("cap-le", "n < DEMO_MODE_MAX_TRACKS)", "n <= DEMO_MODE_MAX_TRACKS)",
      rel=DM),
    M("num-set", "        NumDemoableTracks = n;",
      "        NumDemoableTracks = n + 1;", rel=DM),

    # demomode.c: the pick.
    M("step", "#define DEMO_TRACK_STEP       7", "#define DEMO_TRACK_STEP       8",
      rel=DM),
    M("count-after", "    count = DemoTrackCount;\n"
      "    DemoTrackCount = add32(count, DEMO_TRACK_STEP);",
      "    DemoTrackCount = add32(DemoTrackCount, DEMO_TRACK_STEP);\n"
      "    count = DemoTrackCount;", rel=DM),
    M("build-dropped", "    demomode_build_track_list();\n    count",
      "    count", rel=DM),
    M("pick", "DemoableTracks[count % NumDemoableTracks]",
      "DemoableTracks[(count + 1) % NumDemoableTracks]", rel=DM),
    M("start-dropped", "    fred_start_demo_mode(track);\n}",
      "    (void)track;\n}", rel=DM),

    # demomode.c: the race.
    M("fred-track", "rp->TrackNumber = track;", "rp->TrackNumber = track + 1;",
      rel=DM),
    M("fred-624", "rp->New624 = 1;", "rp->New624 = 0;", rel=DM),
    M("fred-game-type", "#define DEMO_GAME_TYPE        1",
      "#define DEMO_GAME_TYPE        2", rel=DM),
    M("fred-tod", "#define DEMO_TIME_OF_DAY      3",
      "#define DEMO_TIME_OF_DAY      2", rel=DM),
    M("fred-dir", "(eTrackDirection)TrackDirectionForDemoMode;",
      "(eTrackDirection)0;", rel=DM),
    M("fred-density", "#define DEMO_TRAFFIC_DENSITY  1.0f",
      "#define DEMO_TRAFFIC_DENSITY  0.5f", rel=DM),
    M("fred-oncoming", "#define DEMO_TRAFFIC_ONCOMING 0.5f",
      "#define DEMO_TRAFFIC_ONCOMING 1.0f", rel=DM),
    M("fred-cops", "#define DEMO_MAX_COPS         4",
      "#define DEMO_MAX_COPS         3", rel=DM),
    M("fred-weather", "rp->TrackWeather = 0;", "rp->TrackWeather = 1;",
      rel=DM),
    M("fred-event", "rp->EventTreeRace = 0;", "rp->EventTreeRace = 1;",
      rel=DM),
    M("fred-race-type", "#define DEMO_RACE_TYPE        1",
      "#define DEMO_RACE_TYPE        0", rel=DM),
    M("fred-ai", "rp->AIDemoMode = 1;", "rp->AIDemoMode = 0;", rel=DM),
    M("fred-replay", "rp->AIDemoMode = 1;",
      "rp->AIDemoMode = 1;\n    rp->ReplayDemoMode = 1;", rel=DM),
    M("fred-players", "rp->NumPlayerCars = 0;", "rp->NumPlayerCars = 1;",
      rel=DM),
    M("fred-laps", "rp->NumLapsInRace = 0;", "rp->NumLapsInRace = 2;",
      rel=DM),
    M("fred-ai-cars", "#define DEMO_NUM_AI_CARS      4",
      "#define DEMO_NUM_AI_CARS      5", rel=DM),
    M("fred-tickets", "rp->bTickets = 1;", "rp->bTickets = 0;", rel=DM),
    M("fred-roadblocks", "rp->bRoadBlocks = 1;", "rp->bRoadBlocks = 0;",
      rel=DM),
    M("fred-spikes", "rp->bSpikeStrips = 1;", "rp->bSpikeStrips = 0;",
      rel=DM),
    M("fred-heli", "rp->bHelicopter = 1;", "rp->bHelicopter = 0;", rel=DM),
    M("fred-bac-roadblocks", "rp->nNumBeACopRoadBlocks = 0;",
      "rp->nNumBeACopRoadBlocks = 1;", rel=DM),
    M("fred-bac-choppers", "rp->nNumBeACopChoppers = 0;",
      "rp->nNumBeACopChoppers = 1;", rel=DM),
    M("fred-status", "Fred.DemoModeStatus = DEMO_MODE_NO_STATUS;",
      "Fred.DemoModeStatus = DEMO_MODE_TIMEDOUT;", rel=DM),
    M("fred-start", "        gDemoModeStartRaceFn(&Fred);", "        ;", rel=DM),
    M("dir-init", "int32_t TrackDirectionForDemoMode = 0;",
      "int32_t TrackDirectionForDemoMode = 1;", rel=DM),
    M("timeout-init", "float   DemoModeTimeout = 120.0f;",
      "float   DemoModeTimeout = 0.5f;", rel=DM),
    M("status-timedout", "#define DEMO_MODE_TIMEDOUT   1",
      "#define DEMO_MODE_TIMEDOUT   3", rel=DH),
    M("status-skipped", "#define DEMO_MODE_SKIPPED    2",
      "#define DEMO_MODE_SKIPPED    3", rel=DH),

    # rcdemo.c: the helpers.
    M("seconds", "#define SECONDS_PER_TICK 0.00025f",
      "#define SECONDS_PER_TICK 0.00026f"),
    M("ports", "#define RC_DEMO_PORTS 2", "#define RC_DEMO_PORTS 1"),
    M("screen", "#define RC_DEMO_SCREEN 0xcc28b8a9u",
      "#define RC_DEMO_SCREEN 0xcc28b8aau", rel=RDH),
    M("act-vis", "    screen_visibility(RC_DEMO_SCREEN, 0);",
      "    screen_visibility(RC_DEMO_SCREEN, 1);"),
    M("act-event", "AddJoyHandler(port, JOY_EVENT_SKIP_DEMO_MODE,",
      "AddJoyHandler(port, JOY_EVENT_SKIP_DEMO_MODE + 1,"),
    M("act-obj", "racecoordinator_joystick_handler, rc);",
      "racecoordinator_joystick_handler, NULL);"),
    M("act-resume", "    racecoordinator_resume_demo_cameras(rc);\n}", "}"),
    M("un-vis", "    screen_visibility(RC_DEMO_SCREEN, 1);",
      "    screen_visibility(RC_DEMO_SCREEN, 0);"),
    M("un-remove", "        RemoveJoyHandler(port, JOY_EVENT_SKIP_DEMO_MODE);",
      "        ;"),
    M("un-delete-test", "    if (rc->pDemoCameraCoordinator != NULL\n",
      "    if (rc->pDemoCameraCoordinator == NULL\n"),
    M("un-delete", "        gCameraCoordinatorDeleteFn(rc->pDemoCameraCoordinator);",
      "        ;"),
    M("un-clear", "    rc->pDemoCameraCoordinator = NULL;\n}", "}"),
    M("quit-state", "racecoordinator_change_state(rc, RCSTATE_NONE);",
      "racecoordinator_change_state(rc, RCSTATE_PAUSE);"),
    M("quit-msg", "racecoordinator_send_message(rc, RC_QUIT_RACE, 0);",
      "racecoordinator_send_message(rc, RC_NEXT_RACE, 0);"),
    M("quit-order", "    racecoordinator_change_state(rc, RCSTATE_NONE);\n"
      "    racecoordinator_send_message(rc, RC_QUIT_RACE, 0);",
      "    racecoordinator_send_message(rc, RC_QUIT_RACE, 0);\n"
      "    racecoordinator_change_state(rc, RCSTATE_NONE);"),
    M("end-status", "    Fred.DemoModeStatus = status;",
      "    Fred.DemoModeStatus = 0;"),
    M("race-null", "        return 0.0f;", "        return 200.0f;"),
    M("race-unsigned", "(float)(int32_t)pCurrentRace->RaceTime.PackedTime",
      "(float)pCurrentRace->RaceTime.PackedTime"),

    # rcdemo.c: AI_DEMO_MODE.
    M("ai-le", "if (DemoModeTimeout < race_seconds())",
      "if (DemoModeTimeout <= race_seconds())"),
    M("ai-gt", "if (DemoModeTimeout < race_seconds())",
      "if (DemoModeTimeout > race_seconds())"),
    M("ai-act-ret", "    case RC_ACTIVATE:\n        demo_activate(rc);\n"
      "        return 1;",
      "    case RC_ACTIVATE:\n        demo_activate(rc);\n        return 0;"),
    M("ai-un-ret", "        demo_unactivate(rc);\n        return 1;",
      "        demo_unactivate(rc);\n        return 0;"),
    M("ai-tick-status", "            end_demo(rc, DEMO_MODE_TIMEDOUT);\n"
      "        return 1;\n    case RC_SKIP:\n        end_demo",
      "            end_demo(rc, DEMO_MODE_SKIPPED);\n"
      "        return 1;\n    case RC_SKIP:\n        end_demo"),
    M("ai-tick-ret", "            end_demo(rc, DEMO_MODE_TIMEDOUT);\n"
      "        return 1;\n    case RC_SKIP:\n        end_demo",
      "            end_demo(rc, DEMO_MODE_TIMEDOUT);\n"
      "        return 0;\n    case RC_SKIP:\n        end_demo"),
    M("ai-skip-status", "    case RC_SKIP:\n        end_demo(rc, DEMO_MODE_SKIPPED);",
      "    case RC_SKIP:\n        end_demo(rc, DEMO_MODE_TIMEDOUT);"),
    M("ai-skip-ret", "    case RC_SKIP:\n        end_demo(rc, DEMO_MODE_SKIPPED);\n"
      "        return 1;",
      "    case RC_SKIP:\n        end_demo(rc, DEMO_MODE_SKIPPED);\n"
      "        return 0;"),
    M("ai-skip-replay", "    case RC_SKIP:\n        end_demo(rc, DEMO_MODE_SKIPPED);",
      "    case RC_SKIP_REPLAY:\n    case RC_SKIP:\n"
      "        end_demo(rc, DEMO_MODE_SKIPPED);"),
    M("ai-quit-dropped", "        quit_race(rc);\n        return 1;\n"
      "    case RC_TAKE_AUTOSNAPSHOT:\n        return 1;\n    default:",
      "        return 1;\n"
      "    case RC_TAKE_AUTOSNAPSHOT:\n        return 1;\n    default:"),
    M("ai-quit-ret", "        quit_race(rc);\n        return 1;\n"
      "    case RC_TAKE_AUTOSNAPSHOT:\n        return 1;\n    default:",
      "        quit_race(rc);\n        return 0;\n"
      "    case RC_TAKE_AUTOSNAPSHOT:\n        return 1;\n    default:"),
    M("ai-auto-ret", "    case RC_TAKE_AUTOSNAPSHOT:\n        return 1;\n    default:",
      "    case RC_TAKE_AUTOSNAPSHOT:\n        return 0;\n    default:"),
    M("ai-move", "    case RC_TAKE_AUTOSNAPSHOT:\n        return 1;\n    default:",
      "    case RC_MOVE_REPLAY:\n    case RC_TAKE_AUTOSNAPSHOT:\n"
      "        return 1;\n    default:"),
    M("ai-default", "    default:\n        return 0;\n    }\n}\n\n",
      "    default:\n        return 1;\n    }\n}\n\n"),

    # rcdemo.c: REPLAY_DEMO_MODE.
    M("rd-begin", "        dmreplay_begin_demo_mode();\n", ""),
    M("rd-begin-order", "dmreplay_begin_demo_mode();\n        demo_activate(rc);",
      "demo_activate(rc);\n        dmreplay_begin_demo_mode();"),
    M("rd-act-ret", "        demo_activate(rc);\n        return 1;\n"
      "    case RC_UNACTIVATE:\n        demo_unactivate(rc);\n        dmreplay",
      "        demo_activate(rc);\n        return 0;\n"
      "    case RC_UNACTIVATE:\n        demo_unactivate(rc);\n        dmreplay"),
    M("rd-end", "        dmreplay_end_demo_mode();\n", ""),
    M("rd-end-order", "        demo_unactivate(rc);\n        dmreplay_end_demo_mode();",
      "        dmreplay_end_demo_mode();\n        demo_unactivate(rc);"),
    M("rd-handlers", "            gRestoreTypeChangedHandlersFn();", "            ;"),
    M("rd-un-ret", "            gRestoreTypeChangedHandlersFn();\n        return 1;",
      "            gRestoreTypeChangedHandlersFn();\n        return 0;"),
    M("rd-goes", "        if (!dmreplay_test_goes_on())",
      "        if (dmreplay_test_goes_on())"),
    M("rd-goes-status", "            end_demo(rc, DEMO_MODE_TIMEDOUT);\n"
      "        return 1;\n    case RC_SKIP:\n    case RC_SKIP_REPLAY:",
      "            end_demo(rc, DEMO_MODE_SKIPPED);\n"
      "        return 1;\n    case RC_SKIP:\n    case RC_SKIP_REPLAY:"),
    M("rd-tick-ret", "            end_demo(rc, DEMO_MODE_TIMEDOUT);\n"
      "        return 1;\n    case RC_SKIP:\n    case RC_SKIP_REPLAY:",
      "            end_demo(rc, DEMO_MODE_TIMEDOUT);\n"
      "        return 0;\n    case RC_SKIP:\n    case RC_SKIP_REPLAY:"),
    M("rd-skip-replay", "    case RC_SKIP:\n    case RC_SKIP_REPLAY:\n",
      "    case RC_SKIP:\n"),
    M("rd-skip", "    case RC_SKIP:\n    case RC_SKIP_REPLAY:\n",
      "    case RC_SKIP_REPLAY:\n"),
    M("rd-skip-status", "    case RC_SKIP_REPLAY:\n        end_demo(rc, DEMO_MODE_SKIPPED);",
      "    case RC_SKIP_REPLAY:\n        end_demo(rc, DEMO_MODE_TIMEDOUT);"),
    M("rd-skip-ret", "    case RC_SKIP_REPLAY:\n        end_demo(rc, DEMO_MODE_SKIPPED);\n"
      "        return 1;",
      "    case RC_SKIP_REPLAY:\n        end_demo(rc, DEMO_MODE_SKIPPED);\n"
      "        return 0;"),
    M("rd-quit-ret", "        quit_race(rc);\n        return 1;\n"
      "    case RC_TAKE_AUTOSNAPSHOT:\n        return 1;\n    case RC_MOVE_REPLAY:",
      "        quit_race(rc);\n        return 0;\n"
      "    case RC_TAKE_AUTOSNAPSHOT:\n        return 1;\n    case RC_MOVE_REPLAY:"),
    M("rd-auto-ret", "    case RC_TAKE_AUTOSNAPSHOT:\n        return 1;\n"
      "    case RC_MOVE_REPLAY:",
      "    case RC_TAKE_AUTOSNAPSHOT:\n        return 0;\n    case RC_MOVE_REPLAY:"),
    M("rd-pause", "    case RC_TAKE_AUTOSNAPSHOT:\n        return 1;\n"
      "    case RC_MOVE_REPLAY:",
      "    case RC_REQUEST_PAUSE:\n    case RC_TAKE_AUTOSNAPSHOT:\n"
      "        return 1;\n    case RC_MOVE_REPLAY:"),
    M("rd-restore", "        replaymgr_restore_snapshot(pReplayManager,\n"
      "                                   (ReplaySnapshot *)(intptr_t)param);",
      "        ;"),
    M("rd-restore-param", "(ReplaySnapshot *)(intptr_t)param);",
      "(ReplaySnapshot *)(intptr_t)(param + 64));"),
    M("rd-suspend", "        racecoordinator_suspend_demo_cameras(rc);\n", ""),
    M("rd-move-resume", "        racecoordinator_resume_demo_cameras(rc);\n"
      "        return 1;\n    default:", "        return 1;\n    default:"),
    M("rd-move-ret", "        racecoordinator_resume_demo_cameras(rc);\n"
      "        return 1;\n    default:",
      "        racecoordinator_resume_demo_cameras(rc);\n"
      "        return 0;\n    default:"),
    M("rd-default", "        racecoordinator_resume_demo_cameras(rc);\n"
      "        return 1;\n    default:\n        return 0;",
      "        racecoordinator_resume_demo_cameras(rc);\n"
      "        return 1;\n    default:\n        return 1;"),
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
        todo, SOURCES, "demomode_test",
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
