#!/usr/bin/env python3
"""Cross-check 3DS Files/source/pausemenu.c, the pause menu, against the
retail image, SLES_507.31.

**The model** is retail's own PAUSE_MAIN module run in
retail_model.RetailEmu: ChooseWhoSelectedMenuItem, PauseMenu's
constructor, destructor, EnterPause, ExitPause, Activate, DeActivate,
AllPlayerJoysticksPluggedIn, CheckJoysticks, MaybeRestart, MaybeQuit,
MaybeResume and MenuCallback, and PauseMenuCallback (0x00170560 to
0x001710f4); and under them tHighlightAnimation's destructor and its new
HandleMessage (0x00248ae0), and 0x0016fdb0, which answers 0. The harness
(tools/src/pausemenu_test.c) runs pausemenu.c.

**The stubs** print what they are asked, on both sides: GrayMenuItem,
SetScreenFilterPort, PortStopForce, ChangeToScreen,
SetFlailerScreenVisibility, FlailerSetLanguageID, GetTranslatedString,
SummonPopup (every field of the PopupConfig but DismissParam and PopupID,
which retail leaves unwritten), RequestUnPause, 0x001543f0 (the restore of
the type-changed handlers), IsJoystickPluggedIn, IsFreeRun,
AreAllPlayersFinishedRacing, tHighlightAnimation's constructor, Animate
and SetCurrentMenuItem, and __builtin_delete.

**One difference is made equal by hand.** Retail's MaybeResume reads the
pausing player's port with no test; the port's answers 0 for no player.
The model puts a port no script uses at address 8, where retail's read of
a NULL player lands, so both say no.

**The script** builds the menu over 0xcd bytes and deletes it with every
flag; enters the pause from every port over each pair of players by
number, NULL ones and two on one port among them; activates it over every
RaceParameters mix, free run or not, the race finished or not, and each
replay; asks whether every pad is in, with IsJoystickPluggedIn answering
0, 1, 2 and -1; summons both popups for each kind of race, with and
without a screen up; resumes from every port; and sends MenuCallback,
PauseMenuCallback and the bloom every message in every state, SELECT on
every item and the dismiss of both popups with each answer; then random
mixes.

    python tools/pausemenu_check.py
    python tools/pausemenu_check.py --mutate [--only a,b]
    python tools/pausemenu_check.py --dump out/pausemenu
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

HARNESS = "tools/src/pausemenu_test.c"
PM = "3DS Files/source/pausemenu.c"
PM_H = "3DS Files/source/pausemenu.h"
SOURCES = [HARNESS, PM]
HARNESS_TIMEOUT = 60

GP = retail_model.RETAIL_GP
RP = 0x0031a898
P_REPLAY = GP - 22440
P_CURRENT_RACE = GP - 22272
P_RACE_COORD = GP - 22216
FLAILER_LIST = GP - 21324
THE_PAUSE_MENU = GP - 21064
BY_NUMBER = GP - 20936
BY_INDEX = GP - 20928
NUM_PLAYERS = GP - 20920

F_WHO = 0x00170560
F_CTOR = 0x00170580
F_DTOR = 0x001705e0
F_ENTER = 0x00170638
F_EXIT = 0x00170720
F_ACTIVATE = 0x00170738
F_DEACTIVATE = 0x00170958
F_PLUGGED = 0x00170968
F_CHECK = 0x001709d8
F_RESTART = 0x001709e0
F_QUIT = 0x00170b08
F_RESUME = 0x00170c30
F_MENU = 0x00170c90
F_CALLBACK = 0x00171060
F_HL_MSG = 0x00248ae0

S_GRAY = 0x0016d198
S_FILTER = 0x0016d4c8
S_STOP_FORCE = 0x0012c240
S_CHANGE = 0x0014cc78
S_VIS = 0x0014cbf8
S_LANG = 0x001449a8
S_TR = 0x0021e560
S_SUMMON = 0x0016cd68
S_UNPAUSE = 0x00174e00
S_RESTORE = 0x001543f0
S_PLUGGED = 0x001542f0
S_FREE_RUN = 0x001ee390
S_FINISHED = 0x001490b0
S_HL_CTOR = 0x00248870
S_HL_ANIM = 0x00248970
S_HL_ITEM = 0x002488d0
B_DELETE = 0x00114e98

NUM_PLAYER_BLOCKS = 4
PLAYER_SIZE = 96
NUM_PORTS = 8
# Where a NULL player's JoyPort is read: a port no script asks for.
NULL_PLAYER_PORT = 0x7eadbeef

SCREEN = 0x605d2bf1
POPUP = 0x037f3133
ITEMS = [0x52e039f3 + i for i in range(8)]
OTHER_ITEMS = [0x52e039f2, 0x52e039fb, 0, SCREEN]
MSGS = list(range(0, 26))
MSG_SELECT, MSG_HIGHLIGHT = 1, 4
MSG_ACTIVATE, MSG_UNACTIVATE = 11, 12
MSG_START, MSG_BACK, MSG_TICK, MSG_DISMISS = 13, 17, 18, 21


def fill(n, seed):
    return bytes((seed + i * 7) & 0xFF for i in range(n))


# ================================================================ the script

BASE = [
    "player|0|0|0|16", "player|1|1|1|64", "player|2|2|0|112",
    "player|3|3|1|160", "bynum|0|1", "byidx|1|0|1", "pset|200", "rc|0",
    "cur|1", "replay|0|0", "rp|1|0|0|0", "free|0", "fin|0",
]


def pm(state=1, hash_=SCREEN, port=0, opt=-1, rep=-1, player=0):
    return "pm|%d|0x%x|%d|%d|%d|%d" % (state, hash_, port, opt, rep, player)


def plugs(*v):
    return ["plug|%d|%d" % (i, v[i] if i < len(v) else 1)
            for i in range(NUM_PORTS)]


def data_op(op, msg, item, port=0, param=0x5a, noise=0x5b):
    return "%s|%d|0x%x|%d|%d|%d" % (op, msg, item, port, param, noise)


def script():
    s = list(BASE)

    # The constructor and the destructor.
    s += ["ctor", "dump"]
    for f in (0, 1, 2, 3, -1, 0x100):
        s += ["dtor|%d" % f]

    # EnterPause: each pair of players by number, then two on one port.
    for a, b in ((0, 1), (1, 0), (-1, 1), (0, -1), (-1, -1), (2, 3),
                 (1, 1), (3, 2)):
        for port in (-1, 0, 1, 2, 3, 5):
            s += ["bynum|%d|%d" % (a, b), pm(0, 0, 7, 7, 7, 3),
                  "enter|%d" % port, "dump"]
    s += ["player|1|0|1|64"]
    for a, b in ((0, 1), (1, 0), (-1, 1)):
        for port in (0, 1):
            s += ["bynum|%d|%d" % (a, b), pm(2, 5, 3, 1, 2, 2),
                  "enter|%d" % port, "dump"]
    s += ["player|1|1|1|64", "bynum|0|1"]

    # ExitPause and DeActivate.
    for st in range(5):
        s += [pm(st, 0x1234, 3, 1, 2, 1), "exit", "dump"]
        s += [pm(st, 0x1234, 3, 1, 2, 1), "deactivate", "dump"]

    # Activate over every mix.
    for cars in (1, 2):
        for obj in (0, 1):
            for tree in (0, 1):
                for cop in (0, 1):
                    for free in (0, 1):
                        for fin in (0, 1):
                            s += ["rp|%d|%d|%d|%d" % (cars, obj, tree, cop),
                                  "free|%d" % free, "fin|%d" % fin,
                                  pm(0, 0, 1), "activate|0x%x" % SCREEN,
                                  "dump"]
    s += ["rp|1|0|0|0", "free|0", "fin|0"]
    for cnt, mute in ((0, 0), (1, 0), (1, 1), (3, 0), (0, 1), (-1, 0),
                      (2, 5)):
        s += ["replay|%d|%d" % (cnt, mute), pm(3, 0, 1),
              "activate|0x12345678", "dump"]
    s += ["replay|0|0", "rp|1|2|0|0", "activate|0x%x" % SCREEN,
          "rp|1|0|0|3", "activate|0x%x" % SCREEN, "fin|7",
          "activate|0x%x" % SCREEN, "fin|0", "rp|1|0|0|0"]

    # AllPlayerJoysticksPluggedIn.
    for n, a, b in ((0, 0, 1), (1, 0, 1), (1, 1, 0), (2, 0, 1), (2, 1, 0),
                    (2, 2, 3), (1, 3, 2)):
        for v in ((1, 1, 1, 1), (0, 1, 1, 1), (1, 0, 1, 1), (2, 1, 1, 1),
                  (1, 2, 1, 1), (-1, 1, 1, 1), (3, 3, 3, 3),
                  (1, 1, 0, 2), (0, 0, 0, 0)):
            s += ["byidx|%d|%d|%d" % (n, a, b)] + plugs(*v) + ["plugged"]
    s += ["byidx|1|0|1"] + plugs()
    s += ["check", "dump"]

    # MaybeRestart and MaybeQuit for each kind of race.
    for tree in (0, 1):
        for cop in (0, 1):
            for free in (0, 1):
                for obj in (0, 1):
                    for cur in (0, 1):
                        s += ["rp|2|%d|%d|%d" % (obj, tree, cop),
                              "free|%d" % free, "cur|%d" % cur]
                        s += [pm(1, 0x1111, 2), "restart", "dump"]
                        s += [pm(1, 0x2222, 3), "quit", "dump"]
    s += ["rp|1|0|0|0", "free|0", "cur|1"]
    for n, v in ((1, (0, 1)), (1, (1, 0)), (2, (1, 0)), (2, (0, 1)),
                 (2, (2, 1)), (0, (0, 0))):
        s += ["byidx|%d|0|1" % n] + plugs(*v)
        s += [pm(1, 0x3333, 0), "restart", "dump"]
        s += [pm(1, 0x4444, 1), "quit", "dump"]
    s += ["byidx|1|0|1"] + plugs()

    # MaybeResume.
    for player in (-1, 0, 1, 2, 3):
        for port in (-1, 0, 1, 2, 3):
            s += [pm(1, SCREEN, 9, 1, 1, player), "resume|%d" % port,
                  "dump"]
    for v in ((0, 1), (1, 0), (2, 2)):
        s += ["byidx|2|0|1"] + plugs(*v)
        for player in (-1, 0, 1):
            s += [pm(1, SCREEN, 0, 1, 1, player), "resume|0", "resume|1"]
    s += ["byidx|1|0|1"] + plugs()

    # ChooseWhoSelectedMenuItem.
    for n, a, b in ((0, 0, 1), (1, 0, 1), (1, 2, 1), (2, 0, 1), (2, 3, 2)):
        for port in (-1, 0, 1, 3):
            s += ["byidx|%d|%d|%d" % (n, a, b), "who|%d" % port]
    s += ["byidx|1|0|1"]

    # MenuCallback: every message in every state.
    for msg in MSGS:
        items = (ITEMS + OTHER_ITEMS if msg == MSG_SELECT
                 else [ITEMS[0], 0])
        for st in range(5):
            for item in items:
                s += [pm(st, SCREEN, 0, 7, 7, 0),
                      data_op("menu", msg, item, 0), "dump"]

    # SELECT on each item over the race kinds and the players.
    for cars in (1, 2, 3):
        for cop in (0, 1):
            for n, a, b in ((1, 0, 1), (2, 1, 0), (0, 2, 3)):
                s += ["rp|%d|0|0|%d" % (cars, cop),
                      "byidx|%d|%d|%d" % (n, a, b)]
                for item in ITEMS:
                    for port in (0, 1):
                        s += [pm(1, SCREEN, 1, 7, 7, 1),
                              data_op("menu", MSG_SELECT, item, port),
                              "dump"]
    s += ["rp|1|0|0|0", "byidx|1|0|1"]

    # START over the players and the pads.
    for player in (-1, 0, 1):
        for port in (0, 1, 2):
            for v in ((1, 1), (0, 1), (1, 0)):
                s += ["byidx|2|0|1"] + plugs(*v)
                for st in (0, 1, 2):
                    s += [pm(st, SCREEN, 1, 7, 7, player),
                          data_op("menu", MSG_START, 0, port, 0x5a, 0x5b),
                          "dump"]
    s += ["byidx|1|0|1"] + plugs()

    # The popups' dismiss, with each answer, over the players.
    for n, a, b in ((1, 0, 1), (2, 0, 1), (2, 1, 0), (1, 2, 3), (2, 2, 3),
                    (0, 0, 1)):
        for st in range(5):
            for param in (0, 1, -1, 2, 3):
                s += ["byidx|%d|%d|%d" % (n, a, b), "pset|200",
                      pm(st, 0x5555, 1, 7, 7, 1),
                      data_op("menu", MSG_DISMISS, POPUP, 0, param), "dump"]
    s += ["byidx|1|0|1", "pset|200"]

    # PauseMenuCallback.
    for msg in MSGS:
        for st in range(5):
            for rcport in (0, 1):
                s += ["rc|%d" % rcport, pm(st, 0x6666, 3, 7, 7, 2),
                      data_op("cb", msg, SCREEN if st & 1 else 0x77777777,
                              1, 0x5a, 0x5b), "dump"]
    for st in range(5):
        s += ["bynum|1|0", "rc|1", pm(st, 0, 3, 7, 7, 2),
              data_op("cb", MSG_ACTIVATE, SCREEN, 1), "dump",
              data_op("cb", MSG_SELECT, ITEMS[2], 1), "dump",
              data_op("cb", MSG_SELECT, ITEMS[1], 1), "dump",
              data_op("cb", MSG_DISMISS, POPUP, 1, 0), "dump",
              data_op("cb", MSG_SELECT, ITEMS[6], 1), "dump",
              data_op("cb", MSG_DISMISS, POPUP, 1, 1), "dump",
              data_op("cb", MSG_START, 0, 1), "dump",
              data_op("cb", MSG_UNACTIVATE, SCREEN, 1), "dump"]
    s += ["bynum|0|1", "rc|0"]

    # The bloom.
    for msg in MSGS:
        s += ["hl|%d|0x%x" % (msg, ITEMS[msg % 8])]

    s += random_mix(random.Random(0x9a05e), 1500)
    return s


def random_mix(rnd, n):
    s = []
    for _ in range(n):
        for i in range(NUM_PLAYER_BLOCKS):
            if rnd.random() < 0.2:
                s.append("player|%d|%d|%d|%d" % (i, rnd.randrange(-1, 4),
                                                 rnd.randrange(2),
                                                 rnd.randrange(256)))
        if rnd.random() < 0.3:
            s.append("bynum|%d|%d" % (rnd.randrange(-1, 4),
                                      rnd.randrange(-1, 4)))
        if rnd.random() < 0.3:
            s.append("byidx|%d|%d|%d" % (rnd.randrange(3),
                                         rnd.randrange(4),
                                         rnd.randrange(4)))
        if rnd.random() < 0.3:
            s.append("plug|%d|%d" % (rnd.randrange(NUM_PORTS),
                                     rnd.choice((0, 1, 1, 1, 2))))
        if rnd.random() < 0.3:
            s.append("rp|%d|%d|%d|%d" % (rnd.randrange(1, 4),
                                         rnd.randrange(2), rnd.randrange(2),
                                         rnd.randrange(2)))
        if rnd.random() < 0.2:
            s.append("free|%d" % rnd.randrange(2))
        if rnd.random() < 0.2:
            s.append("fin|%d" % rnd.randrange(2))
        if rnd.random() < 0.2:
            s.append("replay|%d|%d" % (rnd.randrange(3), rnd.randrange(2)))
        if rnd.random() < 0.2:
            s.append("rc|%d" % rnd.randrange(-1, 4))
        if rnd.random() < 0.2:
            s.append("cur|%d" % rnd.randrange(2))
        if rnd.random() < 0.2:
            s.append("pset|%d" % rnd.randrange(256))
        if rnd.random() < 0.4:
            s.append(pm(rnd.randrange(5),
                        rnd.choice((SCREEN, 0, 0x12345678)),
                        rnd.randrange(-1, 4), rnd.randrange(-1, 4),
                        rnd.randrange(-1, 4), rnd.randrange(-1, 4)))
        port = rnd.randrange(-1, 4)
        op = rnd.choice(("enter", "exit", "activate", "deactivate",
                         "plugged", "restart", "quit", "resume", "who",
                         "menu", "menu", "menu", "cb", "cb", "hl"))
        if op in ("enter", "resume", "who"):
            s.append("%s|%d" % (op, port))
        elif op == "activate":
            s.append("activate|0x%x" % rnd.choice((SCREEN, 0x12345678)))
        elif op in ("menu", "cb"):
            msg = rnd.choice(MSGS + [MSG_SELECT] * 6 + [MSG_DISMISS] * 3
                             + [MSG_START] * 2)
            s.append(data_op(op, msg, rnd.choice(ITEMS + OTHER_ITEMS),
                             port, rnd.randrange(-1, 3),
                             rnd.randrange(-1, 9)))
        elif op == "hl":
            s.append("hl|%d|0x%x" % (rnd.choice(MSGS), rnd.choice(ITEMS)))
        else:
            s.append(op)
        s.append("dump")
    return s


# ================================================================= the model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        self.pm = e.alloc(64)
        self.players = e.alloc(NUM_PLAYER_BLOCKS * PLAYER_SIZE)
        self.rc = e.alloc(160)
        self.replay = e.alloc(256)
        self.race = e.alloc(64)
        self.flist = e.alloc(512)
        self.screen = e.alloc(64)
        self.data = e.alloc(16)
        self.trbuf = e.alloc(32)
        for blk, n in ((self.pm, 64), (self.players,
                                       NUM_PLAYER_BLOCKS * PLAYER_SIZE),
                       (self.rc, 160), (self.replay, 256), (self.race, 64),
                       (self.flist, 512)):
            e.write(blk, bytes(n))
        e.put32(THE_PAUSE_MENU, self.pm)
        e.put32(P_RACE_COORD, self.rc)
        e.put32(P_REPLAY, self.replay)
        e.put32(P_CURRENT_RACE, self.race)
        e.put32(FLAILER_LIST, self.flist)
        for a in (BY_NUMBER, BY_NUMBER + 4, BY_INDEX, BY_INDEX + 4,
                  NUM_PLAYERS):
            e.put32(a, 0)
        for off in (48, 80, 600, 628):
            e.put32(RP + off, 0)
        e.write(RP + 652, bytes(96))
        e.put32(8, NULL_PLAYER_PORT)
        self.plugged = [1] * NUM_PORTS
        self.free_run = self.finished = 0

        for a, fn in ((S_GRAY, self.gray), (S_FILTER, self.filter),
                      (S_STOP_FORCE, self.stop_force),
                      (S_CHANGE, self.change), (S_VIS, self.vis),
                      (S_LANG, self.lang), (S_TR, self.tr),
                      (S_SUMMON, self.summon), (S_UNPAUSE, self.unpause),
                      (S_RESTORE, self.restore),
                      (S_PLUGGED, self.is_plugged),
                      (S_FREE_RUN, self.is_free_run),
                      (S_FINISHED, self.is_finished),
                      (S_HL_CTOR, self.hl_ctor), (S_HL_ANIM, self.hl_anim),
                      (S_HL_ITEM, self.hl_item), (B_DELETE, self.delete)):
            e.stub(a, fn)

    def emit(self, s):
        self.out.append(s)

    def cstr(self, a, n=256):
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

    def player_at(self, i):
        return 0 if i < 0 else self.players + PLAYER_SIZE * i

    def player_index(self, p):
        for i in range(NUM_PLAYER_BLOCKS):
            if p == self.players + PLAYER_SIZE * i:
                return i
        return -1 if p == 0 else 99

    # ---- the stubs

    def gray(self, e):
        self.emit("  gray %08x %d %08x" % (self.arg(0), self.sarg(1),
                                           self.arg(2)))

    def filter(self, e):
        self.emit("  filter %s %d" % (self.cstr(self.arg(0)), self.sarg(1)))

    def stop_force(self, e):
        self.emit("  stopforce %d" % self.sarg(0))

    def change(self, e):
        self.emit("  change %s %d" % (self.cstr(self.arg(0)), self.sarg(1)))

    def vis(self, e):
        self.emit("  vis %08x %d" % (self.arg(0), self.sarg(1)))

    def lang(self, e):
        self.emit("  lang %08x %08x %x" % (self.arg(0), self.arg(1),
                                           self.arg(2)))

    def tr(self, e):
        i = self.arg(0)
        self.emit("  tr %x" % i)
        e.write(self.trbuf, ("T%x" % i).encode() + b"\0")
        return self.trbuf

    def summon(self, e):
        c = self.arg(1)
        u = e.u32
        parent = u(c + 8)
        msg = u(c + 16)
        self.emit("  summon %d %x %s %08x %s %x %x %x %d %d %d %d %d %d %d %x"
                  % (s32(u(c)), u(c + 4),
                     "NULL" if parent == 0
                     else "cur" if parent == self.screen else "?",
                     u(c + 12), "NULL" if msg == 0 else self.cstr(msg),
                     u(c + 20), u(c + 24), u(c + 28), s32(u(c + 32)),
                     s32(u(c + 36)), s32(u(c + 40)), s32(u(c + 44)),
                     s32(u(c + 52)), s32(u(c + 56)), s32(u(c + 60)),
                     u(c + 68)))

    def unpause(self, e):
        self.emit("  unpause %s %d" % ("rc" if self.arg(0) == self.rc
                                       else "?", self.sarg(1)))

    def restore(self, e):
        self.emit("  restore")

    def is_plugged(self, e):
        p = self.sarg(0)
        self.emit("  isplug %d" % p)
        return (self.plugged[p] if 0 <= p < NUM_PORTS else 0) & M32

    def is_free_run(self, e):
        self.emit("  freerun %s" % ("rp" if self.arg(0) == RP else "?"))
        return self.free_run & M32

    def is_finished(self, e):
        self.emit("  finished %s" % ("race" if self.arg(0) == self.race
                                     else "?"))
        return self.finished & M32

    def hl_ctor(self, e):
        self.emit("  hl_init anim %d %08x %08x %x"
                  % (self.arg(0) - self.pm, self.arg(1), self.arg(2),
                     self.arg(3)))

    def hl_anim(self, e):
        self.emit("  hl_anim anim %d" % (self.arg(0) - self.pm))

    def hl_item(self, e):
        self.emit("  hl_item anim %d %08x" % (self.arg(0) - self.pm,
                                             self.arg(1)))

    def delete(self, e):
        self.emit("  delete %s" % ("pm" if self.arg(0) == self.pm else "?"))

    # ---- the ops

    def set_data(self, item, port, param, noise):
        e = self.e
        e.put32(self.data, item & M32)
        e.put32(self.data + 4, port & M32)
        e.put32(self.data + 8, param & M32)
        e.put32(self.data + 12, noise & M32)

    def print_data(self):
        u = self.e.u32
        d = self.data
        self.emit("  data %08x %d %d %d" % (u(d), s32(u(d + 4)),
                                            s32(u(d + 8)), s32(u(d + 12))))

    def dump(self):
        u = self.e.u32
        m = self.pm
        self.emit("  pm %d %08x %d %d %d %d"
                  % (s32(u(m)), u(m + 4), s32(u(m + 8)), s32(u(m + 12)),
                     s32(u(m + 16)), self.player_index(u(m + 20))))
        b = self.e.read(RP + 652, 96)
        self.emit("  pset " + b[:48].hex() + " " + b[48:].hex())

    def op(self, a):
        e = self.e
        o = a[0]
        n = [int(x, 0) for x in a[1:]]
        if o == "player":
            p = self.player_at(n[0])
            e.put32(p + 8, n[1] & M32)
            e.put32(p + 16, n[2] & M32)
            e.write(p + 32, fill(48, n[3]))
        elif o == "bynum":
            e.put32(BY_NUMBER, self.player_at(n[0]))
            e.put32(BY_NUMBER + 4, self.player_at(n[1]))
        elif o == "byidx":
            e.put32(NUM_PLAYERS, n[0] & M32)
            e.put32(BY_INDEX, self.player_at(n[1]))
            e.put32(BY_INDEX + 4, self.player_at(n[2]))
        elif o == "pset":
            e.write(RP + 652, fill(96, n[0]))
        elif o == "plug":
            self.plugged[n[0]] = n[1]
        elif o == "rp":
            for off, v in zip((48, 80, 600, 628), n):
                e.put32(RP + off, v & M32)
        elif o == "free":
            self.free_run = n[0]
        elif o == "fin":
            self.finished = n[0]
        elif o == "replay":
            e.put32(self.replay + 140, n[0] & M32)
            e.put32(self.replay + 12, n[1] & M32)
        elif o == "rc":
            e.put32(self.rc + 20, n[0] & M32)
        elif o == "cur":
            e.put32(self.flist + 412, self.screen if n[0] else 0)
        elif o == "pm":
            m = self.pm
            for off, v in zip((0, 4, 8, 12, 16), n):
                e.put32(m + off, v & M32)
            e.put32(m + 20, self.player_at(n[5]))
        elif o == "ctor":
            e.write(self.pm, b"\xcd" * 56)
            if e.call(F_CTOR, self.pm) & M32 != self.pm:
                self.emit("  ctor returned another")
        elif o == "dtor":
            e.call(F_DTOR, self.pm, n[0])
        elif o == "enter":
            e.call(F_ENTER, self.pm, n[0])
        elif o == "exit":
            e.call(F_EXIT, self.pm)
        elif o == "activate":
            e.call(F_ACTIVATE, self.pm, n[0])
        elif o == "deactivate":
            e.call(F_DEACTIVATE, self.pm)
        elif o == "plugged":
            self.emit("  = %d" % e.call(F_PLUGGED, self.pm))
        elif o == "check":
            e.call(F_CHECK, self.pm)
        elif o == "restart":
            e.call(F_RESTART, self.pm)
        elif o == "quit":
            e.call(F_QUIT, self.pm)
        elif o == "resume":
            self.emit("  = %d" % e.call(F_RESUME, self.pm, n[0]))
        elif o == "who":
            self.set_data(0, n[0], 0, 0)
            self.emit("  = %d" % e.call(F_WHO, self.data))
        elif o == "menu":
            self.set_data(*n[1:5])
            e.call(F_MENU, self.pm, n[0], self.data, limit=100000)
            self.print_data()
        elif o == "cb":
            self.set_data(*n[1:5])
            e.call(F_CALLBACK, n[0], self.data, limit=100000)
            self.print_data()
        elif o == "hl":
            self.set_data(n[1], 0, 0, 0)
            e.call(F_HL_MSG, self.pm + 24, n[0], self.data)
        elif o == "dump":
            self.dump()
        else:
            raise ValueError(o)

    def run(self, lines):
        e = self.e
        for line in lines:
            self.emit("> " + line)
            sp = e.reg[29]
            self.op(line.split("|"))
            e.reg[29] = sp
        return self.out


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


# ================================================================= build

def build_harness(tmp, name="pausemenu_test"):
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


def M(name, before, after, rel=PM):
    return (name, rel, before, after)


MUTATIONS = [
    # The screens' names.
    M("name-menu", '"Pause Menu";', '"Pause menu";'),
    M("name-opt", '"Pause Options";', '"Pause options";'),
    M("name-audio", '"Pause audio";', '"Pause Audio";'),
    M("name-disp", '"Pause display";', '"Pause Display";'),
    M("name-debug", '"Debug Menu";', '"Debug menu";'),
    M("name-obj", 'Screen[] = "Race Objective";',
      'Screen[] = "Race objective";'),
    M("name-obj2", '"Race Objective 2PBAC";', '"Race Objective 2PBAc";'),
    M("name-bac", '"Pause BAC controls";', '"Pause BAC Controls";'),

    # The header's hashes and IDs.
    M("h-screen", "PAUSE_MENU_SCREEN          0x605d2bf1u",
      "PAUSE_MENU_SCREEN          0x605d2bf2u", PM_H),
    M("h-resume", "PAUSE_MENU_ITEM_RESUME     0x52e039f3u",
      "PAUSE_MENU_ITEM_RESUME     0x52e039fbu", PM_H),
    M("h-restart", "PAUSE_MENU_ITEM_RESTART    0x52e039f4u",
      "PAUSE_MENU_ITEM_RESTART    0x52e039fbu", PM_H),
    M("h-options", "PAUSE_MENU_ITEM_OPTIONS    0x52e039f5u",
      "PAUSE_MENU_ITEM_OPTIONS    0x52e039fbu", PM_H),
    M("h-replay", "PAUSE_MENU_ITEM_REPLAY     0x52e039f6u",
      "PAUSE_MENU_ITEM_REPLAY     0x52e039fbu", PM_H),
    M("h-objective", "PAUSE_MENU_ITEM_OBJECTIVE  0x52e039f7u",
      "PAUSE_MENU_ITEM_OBJECTIVE  0x52e039fbu", PM_H),
    M("h-cop", "PAUSE_MENU_ITEM_COP_CONTROLS 0x52e039f8u",
      "PAUSE_MENU_ITEM_COP_CONTROLS 0x52e039fbu", PM_H),
    M("h-quit", "PAUSE_MENU_ITEM_QUIT       0x52e039f9u",
      "PAUSE_MENU_ITEM_QUIT       0x52e039fbu", PM_H),
    M("h-debug", "PAUSE_MENU_ITEM_DEBUG      0x52e039fau",
      "PAUSE_MENU_ITEM_DEBUG      0x52e039fbu", PM_H),
    M("h-bloom", "PAUSE_MENU_OBJ_BLOOM       0xab671c9au",
      "PAUSE_MENU_OBJ_BLOOM       0xab671c9bu", PM_H),
    M("h-popup", "PAUSE_POPUP_SCREEN         0x037f3133u",
      "PAUSE_POPUP_SCREEN         0x037f3134u", PM_H),
    M("h-yes", "PAUSE_LANG_YES             0x38273",
      "PAUSE_LANG_YES             0x38275", PM_H),
    M("h-no", "PAUSE_LANG_NO              0x38274",
      "PAUSE_LANG_NO              0x38275", PM_H),

    # The popups' flags.
    M("rflags", "#define RESTART_POPUP_FLAGS (BPOPUP_HORIZONTAL | "
      "BPOPUP_CANCELABLE)", "#define RESTART_POPUP_FLAGS (BPOPUP_HORIZONTAL)"),
    M("qflags", "(BPOPUP_HORIZONTAL | BPOPUP_CANCELABLE | BPOPUP_KEEP_VISIBLE)",
      "(BPOPUP_HORIZONTAL | BPOPUP_CANCELABLE)"),

    # View Replay's mode.
    M("rm-count", "|| gReplayNumInstantReplaySnapshotsFn(rm) == 0)",
      "|| gReplayNumInstantReplaySnapshotsFn(rm) < 0)"),
    M("rm-off1", "gReplayNumInstantReplaySnapshotsFn(rm) == 0)" + NL
      + "        return GRAY_DISABLE;",
      "gReplayNumInstantReplaySnapshotsFn(rm) == 0)" + NL
      + "        return GRAY_HIDE;"),
    M("rm-mute", "&& gReplayMuteHighlightsFn(rm) != 0)",
      "&& gReplayMuteHighlightsFn(rm) == 0)"),
    M("rm-off2", "gReplayMuteHighlightsFn(rm) != 0)" + NL
      + "        return GRAY_DISABLE;",
      "gReplayMuteHighlightsFn(rm) != 0)" + NL
      + "        return GRAY_ENABLE;"),
    M("rm-on", "    return GRAY_ENABLE;" + NL + "}",
      "    return GRAY_HIDE;" + NL + "}"),

    # The bloom.
    M("hl-tick", "if (msg == BMSG_SCREEN_TICK) {",
      "if (msg == BMSG_SCREEN_RENDER) {"),
    M("hl-hi", "} else if (msg == BMSG_MENUITEM_HIGHLIGHT) {",
      "} else if (msg == BMSG_MENUITEM_UNHIGHLIGHT) {"),
    M("hl-item", "banim_highlight_set_item(a, h, data->itemHash);",
      "banim_highlight_set_item(a, h, (uint32_t)data->port);"),

    # The constructor and the destructor.
    M("ct-screen", "banim_highlight_init(a, &m->Highlight, PAUSE_MENU_SCREEN,",
      "banim_highlight_init(a, &m->Highlight, PAUSE_POPUP_SCREEN,"),
    M("ct-obj", "PAUSE_MENU_OBJ_BLOOM," + NL,
      "PAUSE_MENU_ITEM_DEBUG," + NL),
    M("ct-color", "(int32_t)BANIM_BLOOM_COLOR);", "(int32_t)-1);"),
    M("ct-rep", "m->ReplayChooser = -1;", "m->ReplayChooser = 0;"),
    M("ct-state", "m->State = PAUSE_MENU_STATE_NONE;" + NL
      + "    m->ScreenHash = 0;",
      "m->State = PAUSE_MENU_STATE_MENU;" + NL + "    m->ScreenHash = 0;"),
    M("ct-hash", "    m->ScreenHash = 0;" + NL + "    m->Port = -1;",
      "    m->ScreenHash = 1;" + NL + "    m->Port = -1;"),
    M("ct-port", "    m->Port = -1;" + NL + "    m->OptionsChooser = -1;",
      "    m->Port = 0;" + NL + "    m->OptionsChooser = -1;"),
    M("ct-opt", "m->OptionsChooser = -1;", "m->OptionsChooser = 0;"),
    M("ct-player", "    m->OptionsChooser = -1;" + NL
      + "    m->PausingPlayer = NULL;",
      "    m->OptionsChooser = -1;" + NL
      + "    m->PausingPlayer = PlayerPlayersByIndex[0];"),
    M("ct-ret", "    return m;" + NL + "}", "    return NULL;" + NL + "}"),
    M("dt-flag", "if (flags & 1)", "if (flags & 2)"),

    # EnterPause.
    M("en-clear", "    m->PausingPlayer = NULL;" + NL + "    m->Port = port;",
      "    m->Port = port;"),
    M("en-port", "    m->Port = port;" + NL + "    p0",
      "    m->Port = port + 1;" + NL + "    p0"),
    M("en-p0", "if (p0 != NULL && p0->JoyPort == port)",
      "if (p0 != NULL && p0->JoyPort != port)"),
    M("en-p0set", "        m->PausingPlayer = p0;",
      "        m->PausingPlayer = p1;"),
    M("en-else", "    else if (p1 != NULL && p1->JoyPort == m->Port)",
      "    if (p1 != NULL && p1->JoyPort == m->Port)"),
    M("en-p1", "p1->JoyPort == m->Port)", "p1->JoyPort != m->Port)"),
    M("en-p1set", "        m->PausingPlayer = p1;" + NL + "    if (p0",
      "        m->PausingPlayer = p0;" + NL + "    if (p0"),
    M("en-sf0", "port_stop_force(p0->JoyPort);", "port_stop_force(port);"),
    M("en-sf1", "port_stop_force(p1->JoyPort);", "port_stop_force(port);"),
    M("en-sf1nul", "    if (p1 != NULL)" + NL + "        port_stop_force",
      "    if (p0 != NULL)" + NL + "        port_stop_force"),
    M("en-f-drop", "    set_screen_filter_port(kPauseDebugMenuScreen, m->Port);"
      + NL, ""),
    M("en-f-port", "set_screen_filter_port(kPauseMenuScreen, m->Port);",
      "set_screen_filter_port(kPauseMenuScreen, -1);"),
    M("en-f-order",
      "    set_screen_filter_port(kPauseRaceObjectiveScreen, m->Port);" + NL
      + "    set_screen_filter_port(kPauseRaceObjective2PBACScreen, m->Port);",
      "    set_screen_filter_port(kPauseRaceObjective2PBACScreen, m->Port);"
      + NL + "    set_screen_filter_port(kPauseRaceObjectiveScreen, m->Port);"),

    # ExitPause.
    M("ex-state", "    m->State = PAUSE_MENU_STATE_NONE;" + NL
      + "    m->Port = -1;",
      "    m->State = PAUSE_MENU_STATE_MENU;" + NL + "    m->Port = -1;"),
    M("ex-port", "    m->Port = -1;" + NL + "    m->PausingPlayer = NULL;"
      + NL + "}",
      "    m->Port = 0;" + NL + "    m->PausingPlayer = NULL;" + NL + "}"),
    M("ex-player", "    m->PausingPlayer = NULL;" + NL + "}" + NL + NL
      + "void pause_menu_activate", "}" + NL + NL + "void pause_menu_activate"),

    # Activate.
    M("ac-hash", "m->ScreenHash = hash;", "m->ScreenHash = hash ^ 1;"),
    M("ac-state", "m->ScreenHash = hash;" + NL
      + "    m->State = PAUSE_MENU_STATE_MENU;",
      "m->ScreenHash = hash;" + NL + "    m->State = PAUSE_MENU_STATE_RESTART;"),
    M("ac-rep-item", "gray_menu_item(PAUSE_MENU_ITEM_REPLAY, replay_mode(),",
      "gray_menu_item(PAUSE_MENU_ITEM_OPTIONS, replay_mode(),"),
    M("ac-obj-or", "rp->HasObjective || rp->BeACop ?",
      "rp->HasObjective && rp->BeACop ?"),
    M("ac-obj-cop", "rp->HasObjective || rp->BeACop ?",
      "rp->HasObjective || rp->EventTreeRace ?"),
    M("ac-obj-hide", "rp->HasObjective || rp->BeACop ? GRAY_ENABLE : GRAY_HIDE",
      "rp->HasObjective || rp->BeACop ? GRAY_ENABLE : GRAY_DISABLE"),
    M("ac-cop", "rp->BeACop ? GRAY_ENABLE : GRAY_HIDE, m->ScreenHash);",
      "rp->HasObjective ? GRAY_ENABLE : GRAY_HIDE, m->ScreenHash);"),
    M("ac-cop-hide", "rp->BeACop ? GRAY_ENABLE : GRAY_HIDE, m->ScreenHash);",
      "rp->BeACop ? GRAY_ENABLE : GRAY_DISABLE, m->ScreenHash);"),
    M("ac-quit", "? GRAY_DISABLE : GRAY_ENABLE,", "? GRAY_HIDE : GRAY_ENABLE,"),
    M("ac-quit-race", "race_are_all_players_finished_racing(pCurrentRace)" + NL,
      "!race_are_all_players_finished_racing(pCurrentRace)" + NL),
    M("ac-debug", "gray_menu_item(PAUSE_MENU_ITEM_DEBUG, GRAY_HIDE,",
      "gray_menu_item(PAUSE_MENU_ITEM_DEBUG, GRAY_DISABLE,"),
    M("ac-free", "if (race_parameters_is_free_run(&TheRaceParameters)) {" + NL
      + "        quit = 0x30d48;",
      "if (!race_parameters_is_free_run(&TheRaceParameters)) {" + NL
      + "        quit = 0x30d48;"),
    M("ac-q0", "quit = 0x30d48;", "quit = 0x30d49;"),
    M("ac-r0", "resume = 0x30d4c;", "resume = 0x30d4d;"),
    M("ac-s0", "restart = 0x30d4e;", "restart = 0x30d4f;"),
    M("ac-tree", "} else if (rp->EventTreeRace) {" + NL
      + "        quit = 0x30d4a;",
      "} else if (rp->HasObjective) {" + NL + "        quit = 0x30d4a;"),
    M("ac-q1", "quit = 0x30d4a;", "quit = 0x30d4b;"),
    M("ac-r1", "resume = 0x30d4b;", "resume = 0x30d4c;"),
    M("ac-s1", "restart = 0x30d45;" + NL + "    } else if (rp->BeACop)",
      "restart = 0x30d46;" + NL + "    } else if (rp->BeACop)"),
    M("ac-cop2", "} else if (rp->BeACop) {" + NL + "        quit = 0x30d52;",
      "} else if (rp->HasObjective) {" + NL + "        quit = 0x30d52;"),
    M("ac-q2", "quit = 0x30d52;", "quit = 0x30d53;"),
    M("ac-r2", "resume = 0x30d50;", "resume = 0x30d51;"),
    M("ac-s2", "restart = 0x30d51;", "restart = 0x30d52;"),
    M("ac-q3", "quit = 0x30d46;", "quit = 0x30d47;"),
    M("ac-r3", "resume = 0x30d4f;", "resume = 0x30d4e;"),
    M("ac-s3", "restart = 0x30d45;" + NL + "    }" + NL + "    flailer",
      "restart = 0x30d44;" + NL + "    }" + NL + "    flailer"),
    M("ac-l-quit", "flailer_set_language_id(m->ScreenHash, PAUSE_MENU_ITEM_QUIT,",
      "flailer_set_language_id(m->ScreenHash, PAUSE_MENU_ITEM_DEBUG,"),
    M("ac-l-res", "PAUSE_MENU_ITEM_RESUME," + NL
      + "                            (uint32_t)resume);",
      "PAUSE_MENU_ITEM_RESUME," + NL
      + "                            (uint32_t)restart);"),
    M("ac-l-rst", "flailer_set_language_id(m->ScreenHash, "
      "PAUSE_MENU_ITEM_RESTART,",
      "flailer_set_language_id(hash ^ 2, PAUSE_MENU_ITEM_RESTART,"),

    # DeActivate.
    M("de-hash", "    m->ScreenHash = 0;" + NL
      + "    m->State = PAUSE_MENU_STATE_MENU;",
      "    m->ScreenHash = 1;" + NL + "    m->State = PAUSE_MENU_STATE_MENU;"),
    M("de-state", "    m->ScreenHash = 0;" + NL
      + "    m->State = PAUSE_MENU_STATE_MENU;",
      "    m->ScreenHash = 0;" + NL + "    m->State = PAUSE_MENU_STATE_NONE;"),

    # AllPlayerJoysticksPluggedIn.
    M("pl-init", "int32_t ok = 1;", "int32_t ok = 3;"),
    M("pl-and", "(ok & IsJoystickPluggedIn", "(ok | IsJoystickPluggedIn"),
    M("pl-ne", "             != 0;", "             == 0;"),
    M("pl-n", "for (i = 0; i < PlayerNumPlayers; i++)" + NL + "        ok",
      "for (i = 0; i < 1; i++)" + NL + "        ok"),
    M("pl-port", "IsJoystickPluggedIn(PlayerPlayersByIndex[i]->JoyPort)",
      "IsJoystickPluggedIn(PlayerPlayersByIndex[0]->JoyPort)"),

    # The popup's config.
    M("su-n", "cfg.numButtons = 2;", "cfg.numButtons = 3;"),
    M("su-flags", "cfg.flags = flags;", "cfg.flags = flags | 4;"),
    M("su-parent", "cfg.parent = gFlailerCurrentScreenFn != NULL "
      "? gFlailerCurrentScreenFn()", "cfg.parent = 0 ? gFlailerCurrentScreenFn()"),
    M("su-screen", "cfg.screen = PAUSE_POPUP_SCREEN;",
      "cfg.screen = PAUSE_MENU_SCREEN;"),
    M("su-msg", "cfg.message = translate(message);",
      "cfg.message = translate(title);"),
    M("su-b0", "cfg.button[0] = PAUSE_LANG_YES;",
      "cfg.button[0] = PAUSE_LANG_NO;"),
    M("su-b1", "cfg.button[1] = PAUSE_LANG_NO;",
      "cfg.button[1] = PAUSE_LANG_YES;"),
    M("su-b2", "cfg.button[2] = 0;", "cfg.button[2] = PAUSE_LANG_NO;"),
    M("su-p0", "cfg.buttonParam[0] = yesParam;", "cfg.buttonParam[0] = 1;"),
    M("su-p1", "cfg.buttonParam[1] = 0;", "cfg.buttonParam[1] = 1;"),
    M("su-p2", "cfg.buttonParam[2] = 0;", "cfg.buttonParam[2] = 1;"),
    M("su-cancel", "cfg.cancelParam = 0;", "cfg.cancelParam = 1;"),
    M("su-start", "cfg.startButton = 1;", "cfg.startButton = 0;"),
    M("su-joy", "cfg.joyPort = m->Port;", "cfg.joyPort = -1;"),
    M("su-timeout", "cfg.timeout = 0;", "cfg.timeout = 1;"),
    M("su-title", "cfg.title = title;", "cfg.title = message;"),

    # MaybeRestart.
    M("rs-plug", "    if (!pause_menu_all_player_joysticks_plugged_in(m))"
      + NL + "        return;" + NL,
      "    if (0)" + NL + "        return;" + NL),
    M("rs-free", "if (race_parameters_is_free_run(&TheRaceParameters)) {" + NL
      + "        message = 0x3827f;",
      "if (!race_parameters_is_free_run(&TheRaceParameters)) {" + NL
      + "        message = 0x3827f;"),
    M("rs-m0", "message = 0x3827f;", "message = 0x38280;"),
    M("rs-t0", "title = 0x38289;", "title = 0x3828a;"),
    M("rs-tree", "} else if (!rp->EventTreeRace && rp->BeACop) {",
      "} else if (rp->BeACop) {"),
    M("rs-cop", "!rp->EventTreeRace && rp->BeACop",
      "!rp->EventTreeRace && rp->HasObjective"),
    M("rs-m1", "message = 0x38281;", "message = 0x38283;"),
    M("rs-t1", "title = 0x38285;", "title = 0x38286;"),
    M("rs-m2", "message = 0x38271;", "message = 0x38270;"),
    M("rs-t2", "title = 0x38279;", "title = 0x3827a;"),
    M("rs-flags", "summon(m, RESTART_POPUP_FLAGS,", "summon(m, QUIT_POPUP_FLAGS,"),
    M("rs-yes", "PAUSE_MENU_STATE_RESTART, message, title);",
      "PAUSE_MENU_STATE_QUIT, message, title);"),
    M("rs-state", "    m->State = PAUSE_MENU_STATE_RESTART;" + NL
      + "    set_screen",
      "    m->State = PAUSE_MENU_STATE_QUIT;" + NL + "    set_screen"),
    M("rs-vis", "    m->State = PAUSE_MENU_STATE_RESTART;" + NL
      + "    set_screen_visibility(m->ScreenHash, FLAILER_SCREEN_INVISIBLE);",
      "    m->State = PAUSE_MENU_STATE_RESTART;" + NL
      + "    set_screen_visibility(m->ScreenHash, FLAILER_SCREEN_VISIBLE);"),

    # MaybeQuit.
    M("qu-plug", "    int32_t message, title;" + NL + NL
      + "    if (race_parameters_is_free_run(&TheRaceParameters)) {" + NL
      + "        message = 0x3827d;",
      "    int32_t message, title;" + NL + NL
      + "    if (!pause_menu_all_player_joysticks_plugged_in(m))" + NL
      + "        return;" + NL
      + "    if (race_parameters_is_free_run(&TheRaceParameters)) {" + NL
      + "        message = 0x3827d;"),
    M("qu-free", "if (race_parameters_is_free_run(&TheRaceParameters)) {" + NL
      + "        message = 0x3827d;",
      "if (!race_parameters_is_free_run(&TheRaceParameters)) {" + NL
      + "        message = 0x3827d;"),
    M("qu-m0", "message = 0x3827d;", "message = 0x3827c;"),
    M("qu-t0", "title = 0x38288;", "title = 0x38287;"),
    M("qu-tree", "} else if (rp->EventTreeRace) {" + NL
      + "        message = 0x3827e;",
      "} else if (rp->HasObjective) {" + NL + "        message = 0x3827e;"),
    M("qu-m1", "message = 0x3827e;", "message = 0x38280;"),
    M("qu-t1", "title = 0x38284;", "title = 0x38283;"),
    M("qu-cop", "} else if (rp->BeACop) {" + NL + "        message = 0x38282;",
      "} else if (rp->HasObjective) {" + NL + "        message = 0x38282;"),
    M("qu-m2", "message = 0x38282;", "message = 0x38281;"),
    M("qu-t2", "title = 0x38283;", "title = 0x38284;"),
    M("qu-m3", "message = 0x38272;", "message = 0x38273;"),
    M("qu-t3", "title = 0x3827b;", "title = 0x3827c;"),
    M("qu-yes", "PAUSE_MENU_STATE_QUIT, message, title);",
      "PAUSE_MENU_STATE_RESTART, message, title);"),
    M("qu-state", "    m->State = PAUSE_MENU_STATE_QUIT;" + NL
      + "    set_screen",
      "    m->State = PAUSE_MENU_STATE_RESTART;" + NL + "    set_screen"),
    M("qu-vis", "    m->State = PAUSE_MENU_STATE_QUIT;" + NL
      + "    set_screen_visibility(m->ScreenHash, FLAILER_SCREEN_INVISIBLE);",
      "    m->State = PAUSE_MENU_STATE_QUIT;" + NL
      + "    set_screen_visibility(m->ScreenHash, FLAILER_SCREEN_VISIBLE);"),

    # MaybeResume.
    M("re-plug", "    if (!pause_menu_all_player_joysticks_plugged_in(m))"
      + NL + "        return 0;",
      "    if (0)" + NL + "        return 0;"),
    M("re-port", "m->PausingPlayer->JoyPort != port)",
      "m->PausingPlayer->JoyPort != m->Port)"),
    M("re-ret0", "        return 0;" + NL + "    request_unpause",
      "        return 1;" + NL + "    request_unpause"),
    M("re-reason", "request_unpause(UNPAUSE_REASON_RESUME_RACE);",
      "request_unpause(UNPAUSE_REASON_RESTART_RACE);"),
    M("re-restore", "    if (gRestoreTypeChangedHandlersFn != NULL)" + NL
      + "        gRestoreTypeChangedHandlersFn();" + NL,
      ""),
    M("re-ret", "        gRestoreTypeChangedHandlersFn();" + NL
      + "    return 1;",
      "        gRestoreTypeChangedHandlersFn();" + NL + "    return 2;"),

    # ChooseWhoSelectedMenuItem.
    M("wh-n", "if (PlayerNumPlayers == 2)" + NL + "        return data->port;",
      "if (PlayerNumPlayers >= 1)" + NL + "        return data->port;"),
    M("wh-port", "return data->port;", "return data->port + 1;"),
    M("wh-idx", "return PlayerPlayersByIndex[0]->JoyPort;",
      "return PlayerPlayersByIndex[1]->JoyPort;"),

    # SELECT.
    M("si-res-port", "pause_menu_maybe_resume(m, data->port);" + NL
      + "        break;",
      "pause_menu_maybe_resume(m, m->Port);" + NL + "        break;"),
    M("si-res", "    case PAUSE_MENU_ITEM_RESUME:",
      "    case PAUSE_MENU_ITEM_DEBUG + 1:"),
    M("si-rst", "    case PAUSE_MENU_ITEM_RESTART:",
      "    case PAUSE_MENU_ITEM_RESTART + 8:"),
    M("si-opt-who", "m->OptionsChooser = pause_choose_who_selected_menu_item",
      "m->ReplayChooser = pause_choose_who_selected_menu_item"),
    M("si-opt-scr", "change_to_screen(kPauseOptionsScreen, 0);",
      "change_to_screen(kPauseOptionsScreen, 1);"),
    M("si-rep-who", "m->ReplayChooser = pause_choose_who_selected_menu_item",
      "m->OptionsChooser = pause_choose_who_selected_menu_item"),
    M("si-rep", "request_unpause(UNPAUSE_REASON_INSTANT_REPLAY);",
      "request_unpause(UNPAUSE_REASON_QUIT_RACE);"),
    M("si-obj-n", "if (rp->NumPlayerCars == 2 && rp->BeACop)",
      "if (rp->NumPlayerCars >= 2 && rp->BeACop)"),
    M("si-obj-cop", "if (rp->NumPlayerCars == 2 && rp->BeACop)",
      "if (rp->NumPlayerCars == 2 && rp->HasObjective)"),
    M("si-obj-2", "change_to_screen(kPauseRaceObjective2PBACScreen, 0);",
      "change_to_screen(kPauseRaceObjectiveScreen, 0);"),
    M("si-obj-1", "change_to_screen(kPauseRaceObjectiveScreen, 0);",
      "change_to_screen(kPauseRaceObjective2PBACScreen, 0);"),
    M("si-bac", "change_to_screen(kPauseBACControlsScreen, 0);",
      "change_to_screen(kPauseBACControlsScreen, 1);"),
    M("si-quit", "    case PAUSE_MENU_ITEM_QUIT:" + NL
      + "        pause_menu_maybe_quit(m);",
      "    case PAUSE_MENU_ITEM_QUIT:" + NL
      + "        pause_menu_maybe_restart(m);"),
    M("si-debug", "change_to_screen(kPauseDebugMenuScreen, 0);",
      "change_to_screen(kPauseDebugMenuScreen, 1);"),
    M("si-fall", "        change_to_screen(kPauseBACControlsScreen, 0);" + NL
      + "        break;",
      "        change_to_screen(kPauseBACControlsScreen, 0);"),

    # The popups' dismiss.
    M("pd-state2", "if (m->State == PAUSE_MENU_STATE_RESTART) {",
      "if (m->State == PAUSE_MENU_STATE_QUIT + 1) {"),
    M("pd-param", "if (data->param != 0) {" + NL + "            for",
      "if (data->param > 0) {" + NL + "            for"),
    M("pd-loop-n", "for (i = 0; i < PlayerNumPlayers; i++) {",
      "for (i = 0; i < 1; i++) {"),
    M("pd-idx", "struct Player *p = PlayerPlayersByIndex[i];",
      "struct Player *p = PlayerPlayersByIndex[0];"),
    M("pd-num", "TheRaceParameters.PlayerSettings[p->PlayerNumber] =",
      "TheRaceParameters.PlayerSettings[i] ="),
    M("pd-reason", "request_unpause(UNPAUSE_REASON_RESTART_RACE);",
      "request_unpause(UNPAUSE_REASON_RESUME_RACE);"),
    M("pd-ret2", "request_unpause(UNPAUSE_REASON_RESTART_RACE);" + NL
      + "            return;",
      "request_unpause(UNPAUSE_REASON_RESTART_RACE);"),
    M("pd-vis2", "        set_screen_visibility(m->ScreenHash, "
      "FLAILER_SCREEN_VISIBLE);" + NL + "    } else if",
      "        set_screen_visibility(m->ScreenHash, "
      "FLAILER_SCREEN_INVISIBLE);" + NL + "    } else if"),
    M("pd-state3", "} else if (m->State == PAUSE_MENU_STATE_QUIT) {",
      "} else if (m->State >= PAUSE_MENU_STATE_QUIT) {"),
    M("pd-param3", "if (data->param != 0) {" + NL
      + "            request_unpause(UNPAUSE_REASON_QUIT_RACE);",
      "if (data->param == 1) {" + NL
      + "            request_unpause(UNPAUSE_REASON_QUIT_RACE);"),
    M("pd-quit", "request_unpause(UNPAUSE_REASON_QUIT_RACE);",
      "request_unpause(UNPAUSE_REASON_INSTANT_REPLAY);"),
    M("pd-ret3", "request_unpause(UNPAUSE_REASON_QUIT_RACE);" + NL
      + "            return;",
      "request_unpause(UNPAUSE_REASON_QUIT_RACE);"),
    M("pd-vis3", "        set_screen_visibility(m->ScreenHash, "
      "FLAILER_SCREEN_VISIBLE);" + NL + "        set_screen_visibility("
      "PAUSE_POPUP_SCREEN",
      "        set_screen_visibility(m->ScreenHash, "
      "FLAILER_SCREEN_INVISIBLE);" + NL + "        set_screen_visibility("
      "PAUSE_POPUP_SCREEN"),
    M("pd-popup", "set_screen_visibility(PAUSE_POPUP_SCREEN, "
      "FLAILER_SCREEN_INVISIBLE);",
      "set_screen_visibility(PAUSE_POPUP_SCREEN, FLAILER_SCREEN_VISIBLE);"),
    M("pd-else", "    } else {" + NL + "        return;" + NL + "    }" + NL
      + "    m->State = PAUSE_MENU_STATE_MENU;",
      "    }" + NL + "    m->State = PAUSE_MENU_STATE_MENU;"),
    M("pd-final", "        return;" + NL + "    }" + NL
      + "    m->State = PAUSE_MENU_STATE_MENU;",
      "        return;" + NL + "    }" + NL
      + "    m->State = PAUSE_MENU_STATE_NONE;"),

    # MenuCallback.
    M("mc-hl", "    pause_highlight_handle_message(&m->Highlight, msg, data);"
      + NL, ""),
    M("mc-sel-state", "if (m->State == PAUSE_MENU_STATE_MENU)" + NL
      + "            select_item(m, data);",
      "if (m->State != PAUSE_MENU_STATE_NONE)" + NL
      + "            select_item(m, data);"),
    M("mc-sel", "case BMSG_MENUITEM_SELECT:", "case BMSG_MENUITEM_ACTIVATE:"),
    M("mc-sel-brk", "            select_item(m, data);" + NL + "        break;",
      "            select_item(m, data);"),
    M("mc-back", "case BMSG_SCREEN_BACK_BUTTON:",
      "case BMSG_SCREEN_SELECT_BUTTON:"),
    M("mc-back-noise", "        data->noise = 0;" + NL
      + "        data->param = 0;",
      "        data->noise = 1;" + NL + "        data->param = 0;"),
    M("mc-back-param", "        data->noise = 0;" + NL
      + "        data->param = 0;",
      "        data->noise = 0;" + NL + "        data->param = 1;"),
    M("mc-start", "case BMSG_SCREEN_START_BUTTON:",
      "case BMSG_SCREEN_SELECT_BUTTON:"),
    M("mc-start-port", "if (pause_menu_maybe_resume(m, data->port))",
      "if (pause_menu_maybe_resume(m, m->Port))"),
    M("mc-start-noise", "data->noise = BSND_MENU_START;",
      "data->noise = BSND_MENU_START + 1;"),
    M("mc-start-param", "            data->noise = BSND_MENU_START;" + NL
      + "        data->param = 1;",
      "            data->noise = BSND_MENU_START;" + NL
      + "        data->param = 0;"),
    M("mc-dismiss", "case BMSG_POPUP_DISMISS:", "case BMSG_POPUP_ACTIVE:"),

    # PauseMenuCallback.
    M("pc-act", "if (msg == BMSG_SCREEN_ACTIVATE) {",
      "if (msg == BMSG_MENUITEM_ACTIVATE) {"),
    M("pc-state", "if (ThePauseMenu->State == PAUSE_MENU_STATE_NONE)",
      "if (ThePauseMenu->State != PAUSE_MENU_STATE_MENU)"),
    M("pc-port", "pRaceCoordinator->PausedJoystickPort);",
      "pRaceCoordinator->PausedJoystickPort + 1);"),
    M("pc-hash", "pause_menu_activate(ThePauseMenu, data->itemHash);",
      "pause_menu_activate(ThePauseMenu, PAUSE_MENU_SCREEN);"),
    M("pc-param", "        data->param = 0;" + NL
      + "    } else if (msg == BMSG_SCREEN_UNACTIVATE)",
      "        data->param = 1;" + NL
      + "    } else if (msg == BMSG_SCREEN_UNACTIVATE)"),
    M("pc-unact", "} else if (msg == BMSG_SCREEN_UNACTIVATE) {",
      "} else if (msg == BMSG_MENUITEM_UNACTIVATE) {"),
    M("pc-de", "pause_menu_deactivate(ThePauseMenu);",
      "pause_menu_exit_pause(ThePauseMenu);"),
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
        todo, SOURCES, "pausemenu_test",
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
