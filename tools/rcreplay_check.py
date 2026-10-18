#!/usr/bin/env python3
"""Cross-check 3DS Files/source/rcreplay.c, the race coordinator's instant
replay, against the retail image, SLES_507.31 (TASKS 72g-3).

**The model** is retail's RaceCoordinator::RCStateInstantReplayCallback
(0x0014b568) run in retail_model.RetailEmu. The harness
(tools/src/rcreplay_test.c) runs rcreplay.c.

**The stubs** print what they are asked, on both sides: the
ReplayManager's TakeSnapshot (0x0013e9f0), RestoreSnapshot by name
(0x0013e748) and by pointer (0x0013eb38) and DeleteSnapshot (0x0013e790);
ChangeState (0x00149520); Player's DisableCameraMovers (0x00177558) and
EnableCameraMovers (0x001774a8); TransientStats::GetDriver (0x00187080);
bMalloc; ReplayScreen's constructor, destructor, Tick and
ChangeCameraMover (0x001ebda8, 0x001ebf98, 0x001ec768, 0x001ec540);
sound::Mute (0x001af850); and the type-changed handlers' reinstall
(0x001543f0).

**Differences made equal by hand.** Retail reads ThePauseMenu unchecked;
the port answers player 0 without one, and the model's NULL reads low
memory, which is 0, so the same. Retail calls ChangeCameraMover on
MOVE_REPLAY with no screen test, and the port tests; the script never
sends MOVE_REPLAY without a screen. A snapshot posted as the param is a
word in retail and a pointer truncated to one in the port; both print it
as the snapshot's label, or as a number.

**The script** sends every message, in and out of range, with the end
screens up and not and a screen up and not; activates over each answer
of the snapshots, each chooser and each mix of the players' drivers and
finishes; and then random mixes.

    python tools/rcreplay_check.py
    python tools/rcreplay_check.py --mutate [--only a,b]
    python tools/rcreplay_check.py --dump out/rcreplay
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

HARNESS = "tools/src/rcreplay_test.c"
RR = "3DS Files/source/rcreplay.c"
RH = "3DS Files/source/rcreplay.h"
SOURCES = [HARNESS, RR]
HARNESS_TIMEOUT = 120

GP = retail_model.RETAIL_GP
P_REPLAY = GP - 22440
PLAYERS = GP - 20928            # Player::pPlayersByIndex
NUM_PLAYERS = GP - 20920
PAUSE_MENU = GP - 21064         # ThePauseMenu

F_IR = 0x0014b568

S_RESTORE_NAMED = 0x0013e748
S_DELETE_NAMED = 0x0013e790
S_TAKE = 0x0013e9f0
S_RESTORE = 0x0013eb38
S_CHANGE = 0x00149520
S_DISABLE = 0x00177558
S_ENABLE = 0x001774a8
S_DRIVER = 0x00187080
S_MALLOC = 0x002577c0
S_CTOR = 0x001ebda8
S_DTOR = 0x001ebf98
S_TICK = 0x001ec768
S_CAMERA = 0x001ec540
S_MUTE = 0x001af850
S_HANDLERS = 0x001543f0

NUM_SNAPS = 4
NUM_DRIVERS = 4
DRIVER_SIZE = 100

# ================================================================= the model


class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        self.rc = e.alloc(64, 16)
        self.rm = e.alloc(256, 16)
        self.pm = e.alloc(64, 16)
        self.players = e.alloc(2 * 256, 16)
        self.snaps = e.alloc(NUM_SNAPS * 64, 16)
        self.drivers = e.alloc(NUM_DRIVERS * DRIVER_SIZE, 16)
        self.screen = e.alloc(1024, 16)
        self.old_screen = e.alloc(16, 16)
        self.egs = e.alloc(16, 16)
        for blk, n in ((self.rc, 64), (self.rm, 256), (self.pm, 64),
                       (self.players, 512), (self.snaps, NUM_SNAPS * 64),
                       (self.drivers, NUM_DRIVERS * DRIVER_SIZE),
                       (self.screen, 1024)):
            e.write(blk, bytes(n))
        e.put32(P_REPLAY, self.rm)
        e.put32(PAUSE_MENU, self.pm)
        e.put32(NUM_PLAYERS, 0)
        for i in range(2):
            e.put32(PLAYERS + 4 * i, self.players + 256 * i)
        e.write(0, bytes(64))
        self.driver_on = [0] * NUM_DRIVERS
        self.ans = dict(take=0, lap=0, ir=0, present=0)

        for a, fn in ((S_RESTORE_NAMED, self.restore_named),
                      (S_DELETE_NAMED, self.delete_named),
                      (S_TAKE, self.take), (S_RESTORE, self.restore),
                      (S_CHANGE, self.change),
                      (S_DISABLE, self.ptr_say("disable")),
                      (S_ENABLE, self.ptr_say("enable")),
                      (S_DRIVER, self.driver), (S_MALLOC, self.malloc),
                      (S_CTOR, self.ctor), (S_DTOR, self.dtor),
                      (S_TICK, self.ptr_say("screen tick")),
                      (S_CAMERA, self.ptr_say("screen camera")),
                      (S_MUTE, self.mute), (S_HANDLERS, self.handlers)):
            e.stub(a, fn)

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
        named = {self.screen: "M", self.old_screen: "SCR", self.rm: "RM",
                 self.rc: "RC"}
        if p in named:
            return named[p]
        for base, size, n, fmt in ((self.players, 256, 2, "P%d"),
                                   (self.snaps, 64, NUM_SNAPS, "S%d")):
            if base <= p < base + size * n and (p - base) % size == 0:
                return fmt % ((p - base) // size)
        return "%d" % s32(p)

    # ---- the stubs

    def ptr_say(self, what):
        def fn(e):
            self.emit("  %s %s" % (what, self.label(self.arg(0))))
        return fn

    def restore_named(self, e):
        name = self.cstr(self.arg(1))
        self.emit("  restore %s %s" % (self.label(self.arg(0)), name))
        return {"LAP_SNAPSHOT": self.ans["lap"],
                "INSTANT_REPLAY": self.ans["ir"],
                "THE_PRESENT": self.ans["present"]}.get(name, 0)

    def delete_named(self, e):
        self.emit("  delete %s %s" % (self.label(self.arg(0)),
                                      self.cstr(self.arg(1))))
        return 0

    def take(self, e):
        self.emit("  take %s %s" % (self.label(self.arg(0)),
                                    self.cstr(self.arg(1))))
        return self.snaps if self.ans["take"] else 0

    def restore(self, e):
        self.emit("  restore %s %s" % (self.label(self.arg(0)),
                                       self.label(self.arg(1))))

    def change(self, e):
        self.emit("  change %s %d" % (self.label(self.arg(0)), self.sarg(1)))

    def driver(self, e):
        n = self.sarg(1)
        self.emit("  driver %d" % n)
        if 0 <= n < NUM_DRIVERS and self.driver_on[n]:
            return self.drivers + DRIVER_SIZE * n
        return 0

    def malloc(self, e):
        self.emit("  malloc %d %s %d %d" % (
            self.sarg(0), self.cstr(self.arg(1)), self.sarg(2),
            self.sarg(3)))
        return self.screen

    def ctor(self, e):
        self.emit("  screen ctor %s %d" % (self.label(self.arg(0)),
                                           self.sarg(1)))
        return self.arg(0)

    def dtor(self, e):
        self.emit("  screen dtor %s %d" % (self.label(self.arg(0)),
                                           self.sarg(1)))

    def mute(self, e):
        self.emit("  mute %d" % self.sarg(0))

    def handlers(self, e):
        self.emit("  type handlers")

    # ---- the ops

    def call(self, fn, *args):
        return self.e.call(fn, *args, limit=200000)

    def op(self, a):
        e = self.e
        op = a[0]
        v = [int(x, 0) for x in a[1:]] if op != "tag" else []
        if op == "tag":
            return
        if op == "rc":
            e.put32(self.rc + 40, self.egs if v[0] else 0)
            e.put32(self.rc + 44, self.old_screen if v[1] else 0)
        elif op == "players":
            e.put32(NUM_PLAYERS, v[0])
        elif op == "player":
            e.put32(self.players + 256 * v[0] + 16, v[1])
        elif op == "pmenu":
            e.put32(PAUSE_MENU, self.pm if v[0] else 0)
            e.put32(self.pm + 16, v[1])
        elif op == "driver":
            d = self.drivers + DRIVER_SIZE * v[0]
            self.driver_on[v[0]] = v[1]
            e.put32(d, v[2])
            e.put32(d + 4, v[3])
        elif op == "ans":
            for k, x in zip(("take", "lap", "ir", "present"), v):
                self.ans[k] = x
        elif op == "msg":
            r = self.call(F_IR, self.rc, v[0], v[1])
            self.emit("  -> %d" % s32(r))
        elif op == "move":
            r = self.call(F_IR, self.rc, 14, self.snaps + 64 * v[0])
            self.emit("  -> %d" % s32(r))
        elif op == "dump":
            self.emit("  screen %s" % self.label(e.u32(self.rc + 44)))
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
ACTIVATE, UNACTIVATE, TICK, SKIP_REPLAY, MOVE_REPLAY = 1, 2, 3, 11, 14


class Script(object):
    def __init__(self):
        self.lines = []

    def add(self, *lines):
        self.lines.extend(lines)

    def tag(self, text):
        self.add("tag|" + text)

    def rc(self, egs, screen):
        self.add("rc|%d|%d" % (egs, screen))

    def players(self, n, *numbers):
        self.add("players|%d" % n)
        for i, x in enumerate(numbers):
            self.add("player|%d|%d" % (i, x))

    def pmenu(self, chooser, on=1):
        self.add("pmenu|%d|%d" % (on, chooser))

    def drivers(self, *specs):
        """Each spec None for NULL, or (FinishPosition, UniqueDriveNumber),
        for driver numbers 0, 1, ... ; the rest NULL."""
        for n in range(NUM_DRIVERS):
            s = specs[n] if n < len(specs) else None
            if s is None:
                self.add("driver|%d|0|0|0" % n)
            else:
                self.add("driver|%d|1|%d|%d" % (n, s[0], s[1]))

    def ans(self, take, lap, ir, present):
        self.add("ans|%d|%d|%d|%d" % (take, lap, ir, present))

    def msg(self, m, param=0):
        self.add("msg|%d|%d" % (m, param), "dump")


def script():
    sc = Script()
    sc.players(2, 0, 1)
    sc.pmenu(0)
    sc.drivers((1, 0), (2, 1))
    sc.ans(1, 1, 1, 1)

    sc.tag("every message, each place")
    for egs in (0, 1):
        for screen in (0, 1):
            for m in [0, -1, 15, 16, 99, -100, 0x7fffffff] + MSGS:
                if m == MOVE_REPLAY and not screen:
                    continue
                sc.rc(egs, screen)
                sc.msg(m, 5)

    sc.tag("activate from the end screens")
    for lap in (0, 1, 2, -1):
        for take, ir in ((0, 0), (1, 1)):
            for screen in (0, 1):
                sc.ans(take, lap, ir, 1)
                sc.rc(1, screen)
                sc.msg(ACTIVATE)

    sc.tag("activate from the pause")
    for take in (0, 1):
        for ir in (0, 1, 7, -1):
            for lap in (0, 1):
                for screen in (0, 1):
                    sc.ans(take, lap, ir, 0)
                    sc.rc(0, screen)
                    sc.msg(ACTIVATE)

    sc.tag("the choosers")
    sc.ans(1, 1, 1, 1)
    for chooser in (1, -1, 0, 2, -2, 0x7fffffff, -0x80000000):
        for egs in (0, 1):
            sc.pmenu(chooser)
            sc.rc(egs, 0)
            sc.msg(ACTIVATE)
    sc.tag("no pause menu")
    for chooser in (1, -1):
        sc.pmenu(chooser, on=0)
        sc.rc(0, 0)
        sc.msg(ACTIVATE)
    sc.pmenu(0)

    sc.tag("the best finisher")
    sc.pmenu(-1)
    finishes = [None, (1, 0), (2, 1), (1, 7), (0, -3), (-5, 9),
                (0x7fffffff, 4), (-0x80000000, 6), (3, 3)]
    rnd = random.Random(7230)
    for n in (-1, 0, 1, 2):
        for numbers in ((0, 1), (1, 0), (0, 0), (2, 3), (-1, 1), (4, 0),
                        (3, 5)):
            for _ in range(6):
                specs = [rnd.choice(finishes) for _ in range(NUM_DRIVERS)]
                sc.players(n, *numbers)
                sc.drivers(*specs)
                sc.rc(rnd.randrange(2), 0)
                sc.msg(ACTIVATE)
    sc.tag("ties and order")
    for a, b in (((1, 10), (1, 20)), ((2, 10), (1, 20)), ((1, 10), (2, 20)),
                 (None, (5, 20)), ((5, 10), None), (None, None),
                 ((-1, 10), (-1, 20)), ((0, 10), (-1, 20))):
        for numbers in ((0, 1), (1, 0)):
            sc.players(2, *numbers)
            sc.drivers(a, b)
            sc.rc(0, 0)
            sc.msg(ACTIVATE)
    sc.players(2, 0, 1)
    sc.drivers((1, 0), (2, 1))
    sc.pmenu(0)

    sc.tag("unactivate")
    for n in (-1, 0, 1, 2):
        for screen in (0, 1):
            for egs in (0, 1):
                sc.players(n, 0, 1)
                sc.rc(egs, screen)
                sc.msg(UNACTIVATE, 3)

    sc.tag("tick")
    for screen in (0, 1):
        sc.rc(0, screen)
        sc.msg(TICK)

    sc.tag("skip")
    for egs in (0, 1):
        for present in (0, 1):
            for screen in (0, 1):
                sc.ans(1, 1, 1, present)
                sc.rc(egs, screen)
                sc.msg(SKIP_REPLAY, 9)

    sc.tag("move")
    for k in range(NUM_SNAPS):
        for egs in (0, 1):
            sc.rc(egs, 1)
            sc.add("move|%d" % k, "dump")
    for param in (0, 1, -1, 64, 0x7fffffff):
        sc.rc(0, 1)
        sc.msg(MOVE_REPLAY, param)

    sc.tag("a replay from the pause and back")
    sc.players(1, 0)
    sc.drivers((1, 0))
    sc.pmenu(-1)
    sc.ans(1, 0, 1, 1)
    sc.rc(0, 0)
    sc.msg(ACTIVATE)
    for _ in range(3):
        sc.msg(TICK)
    sc.add("move|2", "dump")
    sc.msg(SKIP_REPLAY)
    sc.msg(UNACTIVATE)
    sc.tag("a replay from the end screens and back")
    sc.add("rc|1|0")
    sc.ans(1, 1, 0, 0)
    sc.msg(ACTIVATE)
    sc.msg(TICK)
    sc.msg(SKIP_REPLAY)
    sc.msg(UNACTIVATE)

    random_mix(sc, random.Random(7231), 1500)
    return sc.lines


def random_mix(sc, rnd, n):
    """MOVE_REPLAY goes only with a screen set just before it: whether an
    ACTIVATE made one depends on what the snapshots answered."""
    sc.tag("random")
    egs = 0
    for _ in range(n):
        r = rnd.random()
        if r < 0.08:
            k = rnd.randrange(3)
            sc.players(k, *[rnd.randrange(-1, 5) for _ in range(2)])
        elif r < 0.14:
            sc.pmenu(rnd.choice((1, -1, 0, 2, -1, -1)))
        elif r < 0.22:
            sc.drivers(*[rnd.choice([None, None] + [
                (rnd.randrange(-2, 9), rnd.randrange(-2, 9))
                for _ in range(3)]) for _ in range(NUM_DRIVERS)])
        elif r < 0.32:
            sc.ans(*[rnd.choice((0, 1, 1)) for _ in range(4)])
        elif r < 0.42:
            egs = rnd.randrange(2)
            sc.rc(egs, rnd.randrange(2))
        elif r < 0.50:
            sc.rc(egs, 1)
            sc.add("move|%d" % rnd.randrange(NUM_SNAPS), "dump")
        else:
            m = rnd.choice(MSGS + [ACTIVATE, ACTIVATE, UNACTIVATE, TICK,
                                   SKIP_REPLAY, 0, 15])
            if m == MOVE_REPLAY:
                m = TICK
            sc.msg(m, rnd.randrange(-3, 4))


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


# ================================================================= build


def build_harness(tmp, name="rcreplay_test"):
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


def M(name, before, after, rel=RR):
    return (name, rel, before, after)


MUTATIONS = [
    # The constants.
    M("pool", "#define RC_POOL 16", "#define RC_POOL 17"),
    M("chooser-1", "#define RC_CHOOSER_PLAYER_1  1",
      "#define RC_CHOOSER_PLAYER_1  2"),
    M("chooser-best", "#define RC_CHOOSER_BEST     -1",
      "#define RC_CHOOSER_BEST     -2"),
    M("name-lap", '"LAP_SNAPSHOT"', '"LAP_SNAPSHOTS"', rel=RH),
    M("name-present", '"THE_PRESENT"', '"THE_PRESENTS"', rel=RH),
    M("name-ir", '"INSTANT_REPLAY"', '"INSTANT_REPLAYS"', rel=RH),
    M("name-screen", '"ReplayScreen"', '"ReplayScreem"', rel=RH),
    M("screen-size", "bMalloc(REPLAY_SCREEN_SIZE,",
      "bMalloc(REPLAY_SCREEN_SIZE + 4,"),
    M("screen-line", "RC_REPLAY_SCREEN_NAME, 0, RC_POOL",
      "RC_REPLAY_SCREEN_NAME, 1, RC_POOL"),

    # The best finisher.
    M("best-lt", "d->FinishPosition < best->FinishPosition",
      "d->FinishPosition <= best->FinishPosition"),
    M("best-gt", "d->FinishPosition < best->FinishPosition",
      "d->FinishPosition > best->FinishPosition"),
    M("best-first", "if (d != NULL && (best == NULL\n",
      "if (d != NULL && (best != NULL\n"),
    M("best-null", "if (d != NULL && (best == NULL",
      "if (d == NULL && (best == NULL"),
    M("best-loop", "    for (i = 0; i < PlayerNumPlayers; i++) {\n"
      "        const TransientStatsElement *d =",
      "    for (i = 1; i < PlayerNumPlayers; i++) {\n"
      "        const TransientStatsElement *d ="),
    M("best-loop-short", "    for (i = 0; i < PlayerNumPlayers; i++) {\n"
      "        const TransientStatsElement *d =",
      "    for (i = 0; i < PlayerNumPlayers - 1; i++) {\n"
      "        const TransientStatsElement *d ="),
    M("best-number", "PlayerPlayersByIndex[i]->PlayerNumber)",
      "i)"),
    M("best-udn", "best->UniqueDriveNumber : 0",
      "best->FinishPosition : 0"),
    M("best-none", "best->UniqueDriveNumber : 0",
      "best->UniqueDriveNumber : 1"),

    # The chooser.
    M("chooser-1-ret", "    if (chooser == RC_CHOOSER_PLAYER_1)\n"
      "        return 1;", "    if (chooser == RC_CHOOSER_PLAYER_1)\n"
      "        return 0;"),
    M("chooser-other", "    if (chooser != RC_CHOOSER_BEST)\n"
      "        return 0;", "    if (chooser != RC_CHOOSER_BEST)\n"
      "        return 1;"),
    M("chooser-ne", "if (chooser != RC_CHOOSER_BEST)",
      "if (chooser == RC_CHOOSER_BEST)"),
    M("no-pause-menu", "    if (ThePauseMenu == NULL)\n        return 0;",
      "    if (ThePauseMenu == NULL)\n        return 1;"),

    # The screen.
    M("disable-loop", "        player_disable_camera_movers(PlayerPlayersByIndex[i]);",
      "        player_disable_camera_movers(PlayerPlayersByIndex[0]);"),
    M("disable-none", "    for (i = 0; i < PlayerNumPlayers; i++)\n"
      "        player_disable_camera_movers",
      "    for (i = 1; i < PlayerNumPlayers; i++)\n"
      "        player_disable_camera_movers"),
    M("disable-enable", "        player_disable_camera_movers(",
      "        player_enable_camera_movers("),
    M("screen-player", "    pn = replay_player();", "    pn = 0;"),
    M("screen-player-late", "    pn = replay_player();\n"
      "    mem = bMalloc(",
      "    mem = bMalloc(REPLAY_SCREEN_SIZE, RC_REPLAY_SCREEN_NAME, 0, RC_POOL);\n"
      "    pn = replay_player();\n"
      "    (void)bMalloc("),
    M("screen-dropped", "    rc->pReplayScreen = replayscreen_construct(mem, pn);",
      "    (void)replayscreen_construct(mem, pn);"),

    # ACTIVATE.
    M("act-egs", "    if (rc->pEndGameScreens != NULL) {\n"
      "        if (!replaymgr_restore_snapshot_named",
      "    if (rc->pEndGameScreens == NULL) {\n"
      "        if (!replaymgr_restore_snapshot_named"),
    M("act-lap-not", "if (!replaymgr_restore_snapshot_named(rm, RC_REPLAY_LAP_SNAPSHOT))",
      "if (replaymgr_restore_snapshot_named(rm, RC_REPLAY_LAP_SNAPSHOT))"),
    M("act-lap-state", "            racecoordinator_change_state(rc, RCSTATE_POSTRACE);\n"
      "    } else",
      "            racecoordinator_change_state(rc, RCSTATE_PAUSE);\n"
      "    } else"),
    M("act-lap-return", "            racecoordinator_change_state(rc, RCSTATE_POSTRACE);\n"
      "    } else",
      "            { racecoordinator_change_state(rc, RCSTATE_POSTRACE); return; }\n"
      "    } else"),
    M("act-take", "replaymgr_take_snapshot(rm, RC_REPLAY_THE_PRESENT) == NULL",
      "replaymgr_take_snapshot(rm, RC_REPLAY_THE_PRESENT) != NULL"),
    M("act-take-or", "RC_REPLAY_THE_PRESENT) == NULL\n               ||",
      "RC_REPLAY_THE_PRESENT) == NULL\n               &&"),
    M("act-ir-not", "               || !replaymgr_restore_snapshot_named(",
      "               || replaymgr_restore_snapshot_named("),
    M("act-ir-name", "                      rm, RC_REPLAY_INSTANT_REPLAY)",
      "                      rm, RC_REPLAY_LAP_SNAPSHOT)"),
    M("act-pause-state", "        racecoordinator_change_state(rc, RCSTATE_PAUSE);\n"
      "        return;",
      "        racecoordinator_change_state(rc, RCSTATE_POSTRACE);\n"
      "        return;"),
    M("act-pause-return", "        racecoordinator_change_state(rc, RCSTATE_PAUSE);\n"
      "        return;",
      "        racecoordinator_change_state(rc, RCSTATE_PAUSE);\n"
      "        ;"),
    M("act-screen", "    }\n    make_screen(rc);", "    }\n    (void)make_screen;"),
    M("act-ret", "        instant_replay_activate(rc);\n        return 1;",
      "        instant_replay_activate(rc);\n        return 0;"),

    # UNACTIVATE.
    M("un-dtor-test", "        if (rc->pReplayScreen != NULL)\n"
      "            replayscreen_destroy",
      "        if (rc->pReplayScreen == NULL)\n"
      "            replayscreen_destroy"),
    M("un-dtor-flags", "replayscreen_destroy(rc->pReplayScreen, 3);",
      "replayscreen_destroy(rc->pReplayScreen, 1);"),
    M("un-clear", "        rc->pReplayScreen = NULL;\n        mute(1);",
      "        mute(1);"),
    M("un-mute", "        mute(1);", "        mute(0);"),
    M("un-mute-dropped", "        mute(1);", "        ;"),
    M("un-enable", "            player_enable_camera_movers(PlayerPlayersByIndex[i]);",
      "            player_disable_camera_movers(PlayerPlayersByIndex[i]);"),
    M("un-enable-first", "        for (i = 0; i < PlayerNumPlayers; i++)\n"
      "            player_enable_camera_movers",
      "        for (i = 1; i < PlayerNumPlayers; i++)\n"
      "            player_enable_camera_movers"),
    M("un-handlers", "            gRestoreTypeChangedHandlersFn();", "            ;"),
    M("un-ret", "            gRestoreTypeChangedHandlersFn();\n        return 1;",
      "            gRestoreTypeChangedHandlersFn();\n        return 0;"),

    # TICK.
    M("tick-test", "        if (rc->pReplayScreen != NULL)\n"
      "            replayscreen_tick",
      "        if (rc->pReplayScreen == NULL)\n"
      "            replayscreen_tick"),
    M("tick-ret", "            replayscreen_tick(rc->pReplayScreen);\n        return 1;",
      "            replayscreen_tick(rc->pReplayScreen);\n        return 0;"),

    # SKIP_REPLAY.
    M("skip-egs", "        if (rc->pEndGameScreens != NULL) {\n"
      "            racecoordinator_change_state(rc, RCSTATE_POSTRACE);\n"
      "            return 1;",
      "        if (rc->pEndGameScreens == NULL) {\n"
      "            racecoordinator_change_state(rc, RCSTATE_POSTRACE);\n"
      "            return 1;"),
    M("skip-post", "            racecoordinator_change_state(rc, RCSTATE_POSTRACE);\n"
      "            return 1;",
      "            racecoordinator_change_state(rc, RCSTATE_PAUSE);\n"
      "            return 1;"),
    M("skip-post-ret", "            racecoordinator_change_state(rc, RCSTATE_POSTRACE);\n"
      "            return 1;",
      "            racecoordinator_change_state(rc, RCSTATE_POSTRACE);\n"
      "            return 0;"),
    M("skip-restore", "        replaymgr_restore_snapshot_named(pReplayManager,\n"
      "                                         RC_REPLAY_THE_PRESENT);",
      "        ;"),
    M("skip-delete", "        replaymgr_delete_snapshot_named(pReplayManager,\n"
      "                                        RC_REPLAY_THE_PRESENT);",
      "        ;"),
    M("skip-pause", "        racecoordinator_change_state(rc, RCSTATE_PAUSE);\n"
      "        return 1;\n    case RC_TAKE",
      "        racecoordinator_change_state(rc, RCSTATE_NONE);\n"
      "        return 1;\n    case RC_TAKE"),
    M("skip-ret", "        racecoordinator_change_state(rc, RCSTATE_PAUSE);\n"
      "        return 1;\n    case RC_TAKE",
      "        racecoordinator_change_state(rc, RCSTATE_PAUSE);\n"
      "        return 0;\n    case RC_TAKE"),

    # The rest.
    M("auto-ret", "    case RC_TAKE_AUTOSNAPSHOT:\n        return 1;",
      "    case RC_TAKE_AUTOSNAPSHOT:\n        return 0;"),
    M("move-restore", "        replaymgr_restore_snapshot(pReplayManager,\n"
      "                                   (ReplaySnapshot *)(intptr_t)param);",
      "        ;"),
    M("move-camera", "            replayscreen_change_camera_mover(rc->pReplayScreen);",
      "            ;"),
    M("move-ret", "            replayscreen_change_camera_mover(rc->pReplayScreen);\n"
      "        return 1;",
      "            replayscreen_change_camera_mover(rc->pReplayScreen);\n"
      "        return 0;"),
    M("default-ret", "    default:\n        return 0;", "    default:\n        return 1;"),
    M("case-start", "    case RC_TAKE_AUTOSNAPSHOT:\n",
      "    case RC_TAKE_AUTOSNAPSHOT:\n    case RC_START_REPLAY:\n"),
    M("case-pause", "    case RC_TICK:\n        if",
      "    case RC_REQUEST_PAUSE:\n    case RC_TICK:\n        if"),
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
        todo, SOURCES, "rcreplay_test",
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
