#!/usr/bin/env python3
"""Cross-check 3DS Files/source/endgame.c, the end of a race's screens,
against the retail image, SLES_507.31.

**The model** is retail's own END_GAME_SCREENS module run in
retail_model.RetailEmu: the ShouldSee tests (0x001dc6e8 .. 0x001dcac0),
EndGameScreens' BuildScreenList, constructor, destructor, GetNextScreen,
RemoveScreen, AdvanceScreen, AtRoot, MoveBackScreen, GetCurrentScreen,
ResumeScreens, SuspendScreens, AutosaveCompletedCallback and
SetAutosaveCallback with its bridge (0x001dcae0 .. 0x001dd070,
0x001e25e8); EndGameMenusBase's constructor, HandleEvent and destructor
(0x001dd080, 0x001dd0f0, 0x001e2558); the screens' callback (0x001dd278);
and EndGameMenu: its items' tests, constructor, InitLabels, MaybeRestart
and its callers, FindItem, the items' actions, HandleEvent and destructor
(0x001e11a8 .. 0x001e1dbc, 0x001e2270 .. 0x001e2338). Under them run
bStrCmp, FrontendDatabase's UseTheRaceEvent, UseTreeEvent, IsMultiTrack
and IsThereAnotherRace, GetCarTypeForPointsReward, the bPList and bNode
destructors and tHighlightAnimation's HandleMessage and destructor. The
harness (tools/src/endgame_test.c) runs endgame.c.

**The stubs** print what they are asked, on both sides: both
ChangeToScreens, SetFlailerScreenVisibility, FlailerSetVisibility,
FlailerSetLanguageID, GrayMenuItem, GetTranslatedString, SummonPopup
(every field of the PopupConfig but DismissParam and PopupID, which
retail leaves unwritten), PostMessage, SetAutosaveCompletionCallback,
bPNode's Malloc and Free, bMalloc, __builtin_delete, IsCarUnlocked,
tHighlightAnimation's constructor, Animate and SetCurrentMenuItem, and
RaceEvent's GetStatus, its reward test (0x00200b30), 0x00201db8,
0x00201bd8, 0x001f7458, 0x00201fb0, 0x00201b38 and IsThereAnotherRace.
bMemSet fills and ScreenStack::Print says nothing. The ten classes the
port does not have yet are their base on both sides; Tourney Standings'
can be a probe instead, whose Scroll, Tick and Render say they ran.

**Differences made equal by hand.** Retail tests none of
pEndGameScreens, the instance or pReplayManager before reading through
them; the port does. The model keeps the image's low memory zero, so
that a NULL list reads as an empty one at its root, as the port's tests
make it, and puts at address 4 a vtable whose HandleEvent does nothing,
for the callback's message to no instance. With no ReplayManager the
model's has its word at +12 set, so retail hides View Replay as the
port's NULL does. The scripts send SELECT to the base and fire the
autosave's bridge only while there is a list, and never take the
current screen off the list: those read freed or unmapped memory in
retail.

**The script** asks each test over every mix of what it reads; builds
the list over many races; walks, edits, resumes and suspends a list of
nine; sends the base and the callback every message, each screen's
ACTIVATE and UNACTIVATE among them; makes the menu for each kind of race
and sends it every message, SELECT on each item and the popups' dismiss
with each answer, autosave or not; then random mixes.

    python tools/endgame_check.py
    python tools/endgame_check.py --mutate [--only a,b]
    python tools/endgame_check.py --dump out/endgame
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
import mutpar                           # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/endgame_test.c"
EG = "3DS Files/source/endgame.c"
EH = "3DS Files/source/endgame.h"
SOURCES = [HARNESS, EG, "3DS Files/source/nfsrewards.c",
           "3DS Files/source/bprintf.c"]
HARNESS_TIMEOUT = 120

GP = retail_model.RETAIL_GP
FRED = 0x002fc050
F_GAME_TYPE = FRED + 0x1072c
F_NUM_PLAYER_CARS = FRED + 0x10734
F_AUTOSAVE = FRED + 4
F_POINTS_REWARD = 0x002fc3e0
F_TASK_REWARD = 0x002fc3e4
RP = 0x0031a898
EV = 0x0031b600
P_EGS = GP - 17628
P_INST = GP - 17568
P_REPLAY = GP - 22440
P_RACE_COORD = GP - 22216
FLAILER_LIST = GP - 21324

TESTS = [0x001dc6e8, 0x001dc720, 0x001dc758, 0x001dc850, 0x001dc898,
         0x001dc910, 0x001dc928, 0x001dc990, 0x001dc9f0, 0x001dca40,
         0x001dcaa8, 0x001dcab8, 0x001dcac0]
F_BUILD = 0x001dcae0
F_EGS_CTOR = 0x001dcd28
F_EGS_DTOR = 0x001dcda8
F_NEXT = 0x001dce18
F_REMOVE = 0x001dce40
F_ADVANCE = 0x001dcec8
F_AT_ROOT = 0x001dcee8
F_BACK = 0x001dcf00
F_CURRENT = 0x001dcf20
F_RESUME = 0x001dcf38
F_SUSPEND = 0x001dcfe8
F_AUTODONE = 0x001dd038
F_SETCB = 0x001dd070
F_BASE_CTOR = 0x001dd080
F_BASE_HE = 0x001dd0f0
F_BASE_DTOR = 0x001e2558
F_CALLBACK = 0x001dd278
F_MENU_CTOR = 0x001e12b8
F_LABELS = 0x001e15f0
F_RESTART = 0x001e1858
F_FIND = 0x001e1918
F_MENU_HE = 0x001e19e0
F_MENU_DTOR = 0x001e2270

VT_MENU = 0x002b8f38
VT_BASE = 0x002b9148

S_CHANGE = 0x0014cc78
S_LIST_CHANGE = 0x0016c4c0
S_VIS = 0x0014cbf8
S_OBJVIS = 0x00144968
S_LANG = 0x001449a8
S_GRAY = 0x0016d198
S_TR = 0x0021e560
S_SUMMON = 0x0016cd68
S_PRINT = 0x0016b470
S_POST = 0x001496d8
S_SETCB = 0x00247d98
S_PMALLOC = 0x00250680
S_PFREE = 0x002506b0
S_MALLOC = 0x002577c0
S_MEMSET = 0x00250340
B_DELETE = 0x00114e98
S_HL_CTOR = 0x00248870
S_HL_ITEM = 0x002488d0
S_HL_ANIM = 0x00248970
S_UNLOCKED = 0x0024b208
S_STATUS = 0x00202658
S_RTEST = 0x00200b30
S_ADVANCED = 0x00201db8
S_FELL = 0x00201bd8
S_OPENED = 0x001f7458
S_KEEP = 0x00201fb0
S_RESTARTEV = 0x00201b38
S_ANOTHER = 0x00202420
# The classes the port has not got: Points, Task, Events Unlocked, the
# Reward menu, Race Results, Tourney Standings, Best Lap, Best Total and
# the two Be The Cop Results.
CLASS_CTORS = [0x001de568, 0x001de6a8, 0x001df180, 0x001def38, 0x001dffe8,
               0x001dd5d0, 0x001ddc10, 0x001ddfd0, 0x001e0898, 0x001e0a10]
TOURNEY_CTOR = 0x001dd5d0

NUM_SLOTS = 4096
SLOT_SIZE = 256
NUM_NODES = 4096
NODE_SIZE = 16

NAMES = ["Points Rewards", "Task Rewards", "Events Unlocked", "Reward menu",
         "Race Results", "Tourney Standings", "Best Lap Times",
         "Best Total Times", "Autosave", "Be The Cop Results 1P",
         "Be The Cop Results 2P", "Lap Times 1P", "Lap Times 2P",
         "End Game Menu", "Nothing", "Pause Menu"]
N_AUTOSAVE, N_MENU = 8, 13
CLASS_NAMES = [0, 1, 2, 3, 4, 5, 6, 7, 9, 10, 13]

MENU = 0x1a64e903
ITEMS = [0x52e039f3 + i for i in range(6)]
OTHER_ITEMS = [0x52e039f2, 0x52e039f9, 0, MENU]
SCREENS = [0x7e420558, 0xab049b2b, 0x0532b6ff, MENU, 0x12345678]
MSGS = list(range(0, 26))
MSG_SELECT, MSG_HIGHLIGHT, MSG_ACTIVATE, MSG_UNACTIVATE = 1, 4, 11, 12
MSG_BACK, MSG_TICK, MSG_RENDER, MSG_DISMISS = 17, 18, 19, 21


# ================================================================ the script

BASE = ["fred|0|1|0|-1|-1", "rp|0|0|3|1|0|0", "ev|0|0|0|0",
        "evf|0|0|0|0|0", "rtest|0", "unlock|0", "replay|1|0", "cur|-1",
        "probe|0"]

# A race whose list has nine screens: every one but Be The Cop's.
NINE = ["fred|8|1|0|0|2", "rp|0|0|3|1|1|0", "ev|32|4|0|0",
        "evf|4|1|0|1|0", "unlock|1"]
PLAIN = ["fred|0|1|0|-1|-1", "rp|0|0|3|1|0|0", "ev|0|0|0|0",
         "evf|0|0|0|0|0", "unlock|0"]


def data_op(op, msg, item, port=0, param=0x5a, noise=0x5b):
    return "%s|%d|0x%x|%d|%d|%d" % (op, msg, item, port, param, noise)


def fred(gt=0, cars=1, auto=0, pts=-1, task=-1):
    return "fred|%d|%d|%d|%d|%d" % (gt, cars, auto, pts, task)


def rp(rtype=0, p2p=0, laps=3, cars=1, tree=0, cop=0):
    return "rp|%d|%d|%d|%d|%d|%d" % (rtype, p2p, laps, cars, tree, cop)


def script():
    s = list(BASE)

    # The tests.
    for cop in (0, 1, 2):
        for cars in (0, 1, 2, 3):
            s += [rp(cop=cop), fred(cars=cars), "t|0", "t|1"]
    for gt in (7, 8, 9, 10):
        for num in (30, 31, 32):
            for word in (0, 5):
                for nrew in (0, 1, 3, -1):
                    for st in (2, 3, 4):
                        for adv in (0, 2):
                            s += [fred(gt), "ev|%d|0|%d|%d" % (num, nrew, word),
                                  "evf|%d|%d|0|0|0" % (st, adv)]
                            for mask in (0, 1, 5, 7):
                                s += ["rtest|%d" % mask, "t|2"]
    for pts in list(range(-3, 21)) + [100, 0x7fffffff]:
        for un in (0, 1, 2):
            s += [fred(pts=pts), "unlock|%d" % un, "t|3"]
    for gt in (7, 8, 9):
        for st in (3, 4, 5):
            for adv in (0, 1, 3):
                for opened in (-1, 0, 1, 2):
                    s += [fred(gt), "evf|%d|%d|0|%d|0" % (st, adv, opened),
                          "t|4"]
    for task in (-1, 0, 1, 5, -2):
        s += [fred(task=task), "t|5"]
    for cop in (0, 1):
        for gt in (0, 5, 6, 7, 8, 9, 10):
            for typ in (0, 1, 2, 4):
                s += [rp(cop=cop), fred(gt), "ev|0|%d|0|0" % typ,
                      "t|6", "t|7", "t|9"]
            for p2p in (0, 1, 2):
                for laps in (0, 1, 2, 3):
                    s += [rp(p2p=p2p, laps=laps, cop=cop), "t|8"]
    for auto in (0, 1, -1, 2):
        s += [fred(auto=auto), "t|10", "t|11"]
    for gt in (5, 6, 7, -6):
        s += [fred(gt), "t|12"]
    s += PLAIN + ["unlock|0", "rtest|0"]

    # The list over many races.
    rnd = random.Random(0x3e1d)
    for _ in range(160):
        s += [fred(rnd.choice((0, 1, 4, 6, 8, 9)), rnd.choice((1, 2, 3)),
                   rnd.randrange(2), rnd.choice((-1, -1, 0, 3, 7)),
                   rnd.choice((-1, -1, 0, 2))),
              rp(rnd.randrange(7), rnd.randrange(2), rnd.choice((1, 3)),
                 rnd.choice((1, 2)), rnd.randrange(2), rnd.randrange(2)),
              "ev|%d|%d|%d|%d" % (rnd.choice((0, 31, 32)),
                                  rnd.choice((0, 1, 4)), rnd.randrange(3),
                                  rnd.randrange(2)),
              "evf|%d|%d|0|%d|0" % (rnd.randrange(2, 6), rnd.randrange(2),
                                    rnd.randrange(-1, 3)),
              "rtest|%d" % rnd.randrange(8), "unlock|%d" % rnd.randrange(2),
              "egs|%d" % rnd.randrange(-1, 3), "dump",
              "egsdtor|%d" % rnd.choice((1, 3)), "dump"]
    s += PLAIN + ["rtest|0"]

    # The destructor's flags, enabled or not.
    for f in (0, 1, 2, 3, -1):
        for en in (0, 1):
            s += ["egs|0"] + (["resume"] if en else []) + ["egsdtor|%d" % f,
                                                             "dump"]

    # Walking a list of nine.
    s += NINE + ["egs|1", "dump"]
    for _ in range(10):
        s += ["next", "current", "atroot", "advance", "dump"]
    for _ in range(10):
        s += ["back", "current", "atroot", "next", "dump"]
    # Taking screens off it, never the current one (the first).
    for k in (13, 5, 14, 0, 8, 7, 11, 3):
        s += ["advance", "back", "remove|%d" % k, "dump"]
    for k in (1, 2, 4, 6):
        s += ["remove|%d" % k, "dump"]
    s += ["egsdtor|3", "dump"]
    s += NINE + ["egs|0", "advance", "advance", "advance"]
    for k in (0, 1, 2, 13, 13, 5, 6):
        s += ["remove|%d" % k, "next", "current", "dump"]
    s += ["egsdtor|3"]
    # Two of a name: the first goes.
    s += NINE + ["egs|0", "insname|4|7", "insname|8|2", "insname|8|5",
                 "dump", "advance", "remove|4", "dump", "remove|8", "dump",
                 "remove|8", "dump", "remove|8", "dump", "egsdtor|3"]

    # Resume and suspend, and the autosave.
    s += PLAIN + ["egs|0", "dump"]
    s += ["suspend", "dump", "resume", "dump", "resume", "dump", "suspend",
          "dump", "suspend", "dump", "resume", "advance", "suspend",
          "resume", "dump", "egsdtor|3"]
    for pos in (0, 1):
        s += NINE + ["egs|0", "insname|8|%d" % pos, "insname|8|3"]
        if pos:
            s += ["advance"]
        s += ["dump", "resume", "dump", "fire", "dump", "suspend", "resume",
              "dump", "autodone", "dump", "setcb", "fire", "dump",
              "egsdtor|1", "dump"]
    s += PLAIN + ["egs|2", "autodone", "autodone", "dump", "setcb", "fire",
                  "fire", "dump", "egsdtor|3"]

    # The base: its constructor at the root, off it and with no list.
    s += NINE + ["egs|0"]
    for h in SCREENS:
        s += ["base|0x%x" % h, "dump", "bdtor|1"]
    s += ["advance"]
    for h in SCREENS[:2]:
        s += ["base|0x%x" % h, "dump", "bdtor|1"]
    s += ["egsdtor|3", "base|0x%x" % SCREENS[0], "dump", "bdtor|1"]
    for f in (0, 1, 2, 3, -1):
        s += ["base|0x77", "bdtor|%d" % f, "dump"]
    # Every message, at each place in the list.
    for start in range(4):
        for msg in MSGS:
            s += NINE + ["egs|0"] + ["advance"] * start
            s += ["base|0x%x" % MENU,
                  data_op("bh", msg, ITEMS[msg % 6], 1, 0x5a, 0x5b), "dump",
                  "egsdtor|3", "bdtor|3"]
    # SELECT up to the end, then BACK to the start.
    s += NINE + ["egs|0", "base|0x%x" % MENU]
    for _ in range(11):
        s += [data_op("bh", MSG_SELECT, ITEMS[0]), "dump"]
    for _ in range(11):
        s += [data_op("bh", MSG_BACK, 0, 0, 7, 9), "dump"]
    # SELECT onto the Autosave screen, and its callback.
    s += ["insname|8|1", "insname|8|3", "insname|8|3", "dump"]
    for _ in range(6):
        s += [data_op("bh", MSG_SELECT, ITEMS[0]), "dump", "fire", "dump"]
    s += ["egsdtor|3", "bdtor|3"]
    # BACK with no list.
    s += ["base|0x55", data_op("bh", MSG_BACK, 0, 0, 7, 9), "dump",
          "bdtor|3"]

    # The callback: each screen's class, with and without the probe.
    s += NINE + ["egs|0"]
    for probe in (0, 1):
        s += ["probe|%d" % probe]
        for k in list(range(len(NAMES))) + [-1]:
            s += ["cur|%d" % k,
                  data_op("cb", MSG_ACTIVATE, SCREENS[k % 5], 2, 3, 4),
                  "dump"]
            for msg in (6, 7, 8, 18, 19, 4, 0, 25):
                s += [data_op("cb", msg, ITEMS[1], 0, 1, 2), "dump"]
            s += [data_op("cb", MSG_UNACTIVATE, 0, 0, 1, 2), "dump"]
    s += ["probe|0"]
    # Messages to no instance.
    for msg in MSGS:
        s += [data_op("cb", msg, ITEMS[0], 0, 1, 2), "dump"]
    s += ["cur|-1", data_op("cb", MSG_UNACTIVATE, 0, 0, 1, 2)]
    # ACTIVATE twice, and with nothing up.
    s += ["cur|4", data_op("cb", MSG_ACTIVATE, SCREENS[1]), "dump",
          "cur|13", data_op("cb", MSG_ACTIVATE, MENU), "dump",
          "cur|-1", data_op("cb", MSG_ACTIVATE, MENU), "dump",
          "cur|14", data_op("cb", MSG_ACTIVATE, MENU), "dump",
          data_op("cb", MSG_UNACTIVATE, 0), "dump",
          data_op("cb", MSG_UNACTIVATE, 0), "dump"]
    # SELECT and BACK through the callback down the list.
    s += ["egsdtor|3"] + NINE + ["egs|0", "resume"]
    for i in range(10):
        s += ["cur|%d" % (13 if i == 9 else i % 8),
              data_op("cb", MSG_ACTIVATE, SCREENS[i % 5]),
              data_op("cb", MSG_SELECT, ITEMS[0]),
              data_op("cb", MSG_UNACTIVATE, 0), "dump"]
    s += ["cur|4", data_op("cb", MSG_ACTIVATE, SCREENS[1])]
    for _ in range(10):
        s += [data_op("cb", MSG_BACK, 0, 0, 3, 3), "dump"]
    s += [data_op("cb", MSG_UNACTIVATE, 0), "egsdtor|3", "cur|-1"]
    s += PLAIN + ["egs|0"]

    # The menu for each kind of race.
    for gt in (0, 4, 8, 9):
        for rtype in (0, 3, 4, 5, 6):
            for tree in (0, 1):
                for cop in (0, 1):
                    for another in (0, 1):
                        s += [fred(gt), rp(rtype, tree=tree, cop=cop),
                              "evf|0|0|0|0|%d" % another,
                              "menu|0x%x|%d" % (MENU, 9), "dump",
                              "mdtor|3"]
    s += [fred(0), rp()]
    for present, mute in ((0, 0), (1, 0), (1, 1), (1, -1), (0, 1)):
        s += ["replay|%d|%d" % (present, mute), "menu|0x%x|0" % SCREENS[4],
              "dump", "mdtor|3"]
    s += ["replay|1|0", rp(4), "evf|0|0|0|0|1", fred(4)]
    for f in (0, 1, 2, 3, -1):
        s += ["menu|0x%x|1" % MENU, "mdtor|%d" % f, "dump"]

    # InitLabels.
    for gt in (0, 8, 9, 4):
        for rtype in (0, 4, 5):
            for tree in (0, 1):
                for cop in (0, 1):
                    for another in (0, 1):
                        s += [fred(gt), rp(rtype, tree=tree, cop=cop),
                              "evf|0|0|0|0|%d" % another, "labels"]

    # Every message to the menu of each race kind.
    s += [fred(4), rp(4), "evf|0|0|0|0|1", "replay|1|0", "cur|13"]
    for msg in MSGS:
        items = (ITEMS + OTHER_ITEMS if msg in (MSG_SELECT, MSG_HIGHLIGHT)
                 else [ITEMS[0]])
        for item in items:
            for st in (0, 3, 7):
                s += ["menu|0x%x|5" % MENU, "mstate|%d" % st,
                      data_op("mh", msg, item, 1), "dump", "mdtor|3"]
    # SELECT on each item over the races, with two players or one.
    for gt, rtype, tree, cop, cars in ((4, 4, 0, 0, 1), (4, 4, 0, 0, 2),
                                       (8, 0, 1, 0, 1), (0, 0, 0, 1, 1),
                                       (9, 5, 1, 0, 2), (0, 0, 0, 0, 3)):
        for cur in (13, -1):
            s += [fred(gt), rp(rtype, cars=cars, tree=tree, cop=cop),
                  "cur|%d" % cur]
            for item in ITEMS:
                s += ["menu|0x%x|5" % MENU, data_op("mh", MSG_SELECT, item),
                      "dump", "mdtor|3"]
    s += ["cur|13"]
    # The popups' dismiss: each state, each answer, autosave or not.
    for gt in (0, 4, 8, 9):
        for auto in (0, 1):
            for fell in (0, 1, 2):
                for st in (-1, 0, 1, 2, 3, 4):
                    for param in (0, 1, -1, 2):
                        s += [fred(gt, auto=auto), "evf|0|0|%d|0|1" % fell,
                              "menu|0x%x|5" % MENU, "mstate|%d" % st,
                              data_op("mh", MSG_DISMISS, 0x037f3133, 0,
                                      param), "dump", "fire", "mdtor|3"]
    # BACK, at the root and off it, and with no list.
    s += [fred(4), "egsdtor|3"] + NINE + ["egs|0"]
    for adv in (0, 1, 3):
        s += ["advance"] * adv + ["menu|0x%x|5" % MENU]
        for _ in range(3):
            s += [data_op("mh", MSG_BACK, 0, 0, 7, 9), "dump"]
        s += ["mdtor|3"]
    s += ["egsdtor|3", "menu|0x%x|5" % MENU,
          data_op("mh", MSG_BACK, 0, 0, 7, 9), "dump", "mdtor|3"]
    s += PLAIN + ["egs|0"]
    # The bloom.
    s += ["menu|0x%x|0" % MENU]
    for msg in MSGS:
        s += [data_op("mh", msg, ITEMS[msg % 6]), "dump"]
    # MaybeRestart and FindItem.
    for cur in (13, -1):
        for t, m, st in ((0x30d45, 0x38271, 0), (-1, -1, 3), (5, 6, 9),
                         (0, 0, -1)):
            s += ["cur|%d" % cur, "restart|%d|%d|%d" % (t, m, st), "dump"]
    s += ["cur|13"]
    for h in ITEMS + OTHER_ITEMS:
        s += ["find|0x%x" % h]
    s += ["mdtor|3"]
    # A whole end: the list up, down to the menu, Quit with autosave.
    s += ["egsdtor|3", fred(4, auto=1)] + NINE[1:] + [
        "egs|0", "resume", "dump"]
    for k in (0, 1, 2, 3, 4, 5, 6, 7):
        s += ["cur|%d" % k, data_op("cb", MSG_ACTIVATE, SCREENS[k % 5]),
              data_op("cb", MSG_TICK, 0), data_op("cb", MSG_SELECT, 0),
              data_op("cb", MSG_UNACTIVATE, 0), "dump"]
    s += ["cur|13", data_op("cb", MSG_ACTIVATE, MENU, 0, 5), "dump",
          data_op("cb", MSG_HIGHLIGHT, ITEMS[5]),
          data_op("cb", MSG_SELECT, ITEMS[5]), "dump",
          data_op("cb", MSG_DISMISS, 0x037f3133, 0, 0), "dump",
          data_op("cb", MSG_SELECT, ITEMS[5]),
          data_op("cb", MSG_DISMISS, 0x037f3133, 0, 1), "dump", "fire",
          data_op("cb", MSG_UNACTIVATE, 0), "suspend", "dump",
          "egsdtor|3", "dump"]

    s += PLAIN + ["egs|0"]
    s += random_mix(random.Random(0xe9d), 1500)
    return s


def random_mix(rnd, n):
    s = []
    obj = None          # what `obj` is: None, "base" or "menu"
    inst = False        # an instance up
    for _ in range(n):
        if rnd.random() < 0.15:
            s.append(fred(rnd.choice((0, 1, 4, 6, 8, 9)),
                          rnd.choice((1, 2, 3)), rnd.randrange(2),
                          rnd.choice((-1, -1, 0, 5)),
                          rnd.choice((-1, -1, 0, 1))))
        if rnd.random() < 0.15:
            s.append(rp(rnd.randrange(7), rnd.randrange(2),
                        rnd.choice((1, 2, 3)), rnd.choice((1, 2)),
                        rnd.randrange(2), rnd.randrange(2)))
        if rnd.random() < 0.1:
            s.append("ev|%d|%d|%d|%d" % (rnd.choice((0, 30, 31, 32)),
                                         rnd.choice((0, 1, 4)),
                                         rnd.randrange(-1, 4),
                                         rnd.randrange(2)))
        if rnd.random() < 0.15:
            s.append("evf|%d|%d|%d|%d|%d" % (rnd.randrange(2, 6),
                                             rnd.randrange(3),
                                             rnd.randrange(2),
                                             rnd.randrange(-1, 3),
                                             rnd.randrange(2)))
        if rnd.random() < 0.1:
            s.append("rtest|%d" % rnd.randrange(16))
        if rnd.random() < 0.1:
            s.append("unlock|%d" % rnd.randrange(2))
        if rnd.random() < 0.1:
            s.append("replay|%d|%d" % (rnd.randrange(2), rnd.randrange(2)))
        if rnd.random() < 0.3:
            s.append("cur|%d" % rnd.randrange(-1, len(NAMES)))
        if rnd.random() < 0.1:
            s.append("probe|%d" % rnd.randrange(2))
        op = rnd.choice(("egs", "list", "list", "list", "t", "base", "bh",
                         "bh", "cb", "cb", "cb", "cb", "menu", "mh", "mh",
                         "mh", "labels", "restart", "find", "fire",
                         "insname"))
        msg = rnd.choice(MSGS + [MSG_SELECT] * 4 + [MSG_BACK] * 3
                         + [MSG_DISMISS] * 3 + [MSG_TICK] * 2)
        item = rnd.choice(ITEMS + OTHER_ITEMS)
        port = rnd.randrange(-1, 3)
        param = rnd.choice((0, 1, 1, -1, 2))
        noise = rnd.randrange(-1, 9)
        if op == "egs":
            s += ["egsdtor|3", "egs|%d" % rnd.randrange(3)]
        elif op == "list":
            s.append(rnd.choice(("build", "next", "advance", "atroot",
                                 "back", "current", "resume", "suspend",
                                 "autodone", "setcb")))
        elif op == "t":
            s.append("t|%d" % rnd.randrange(len(TESTS)))
        elif op == "base" or (op == "bh" and obj is None):
            if obj == "base":
                s.append("bdtor|3")
            elif obj == "menu":
                s.append("mdtor|3")
            s.append("base|0x%x" % rnd.choice(SCREENS))
            obj = "base"
        elif op == "bh":
            s.append(data_op("bh", msg, item, port, param, noise))
        elif op == "cb":
            if msg == MSG_ACTIVATE and inst:
                s.append(data_op("cb", MSG_UNACTIVATE, 0))
                inst = False
            s.append(data_op("cb", msg, item, port, param, noise))
            if msg == MSG_ACTIVATE:
                inst = True
            elif msg == MSG_UNACTIVATE:
                inst = False
        elif op == "menu" or (op in ("mh", "restart", "find")
                              and obj != "menu"):
            if obj == "base":
                s.append("bdtor|3")
            elif obj == "menu":
                s.append("mdtor|3")
            s.append("menu|0x%x|%d" % (rnd.choice(SCREENS),
                                       rnd.randrange(3)))
            obj = "menu"
        elif op == "mh":
            if rnd.random() < 0.3:
                s.append("mstate|%d" % rnd.randrange(-1, 5))
            s.append(data_op("mh", msg, item, port, param, noise))
        elif op == "labels":
            s.append("labels")
        elif op == "restart":
            s.append("restart|%d|%d|%d" % (rnd.randrange(0x30000, 0x40000),
                                           rnd.randrange(0x30000, 0x40000),
                                           rnd.randrange(-1, 5)))
        elif op == "find":
            s.append("find|0x%x" % item)
        elif op == "fire":
            s.append("fire")
        elif op == "insname":
            s.append("insname|%d|0" % N_AUTOSAVE)
        s.append("dump")
    return s


# ================================================================= the model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        self.slots = e.alloc(NUM_SLOTS * SLOT_SIZE, 256)
        self.slot_used = [False] * NUM_SLOTS
        self.nodes = e.alloc(NUM_NODES * NODE_SIZE)
        self.node_used = [False] * NUM_NODES
        self.names = []
        for nm in NAMES:
            a = e.alloc(32, 16)
            e.write(a, nm.encode() + b"\0")
            self.names.append(a)
        self.flist = e.alloc(512)
        self.screen = e.alloc(64)
        self.cfg = e.alloc(64)
        self.rc = e.alloc(64)
        self.replay = e.alloc(64)
        self.noreplay = e.alloc(64)
        self.data = e.alloc(16)
        self.trbuf = e.alloc(32)
        self.lbuf = e.alloc(64)
        for blk, n in ((self.flist, 512), (self.screen, 64), (self.cfg, 64),
                       (self.rc, 64), (self.replay, 64),
                       (self.noreplay, 64)):
            e.write(blk, bytes(n))
        e.put32(self.screen + 16, self.cfg)
        e.put32(self.noreplay + 12, 1)
        e.put32(FLAILER_LIST, self.flist)
        e.put32(P_RACE_COORD, self.rc)
        e.put32(P_REPLAY, self.replay)
        e.put32(P_EGS, 0)
        e.put32(P_INST, 0)
        for a in (F_GAME_TYPE, F_NUM_PLAYER_CARS, F_AUTOSAVE,
                  F_POINTS_REWARD, F_TASK_REWARD):
            e.put32(a, 0)
        for off in (32, 40, 44, 48, 600, 628):
            e.put32(RP + off, 0)
        e.write(EV + 104, bytes(20))
        # Low memory as a NULL list reads it, and a vtable for the
        # callback's message to no instance.
        e.write(0, bytes(64))
        self.null_vt = e.alloc(64)
        e.write(self.null_vt, bytes(64))
        self.f_nop = e.alloc(16)
        e.put32(self.null_vt + 20, self.f_nop)
        e.put32(4, self.null_vt)
        # The probe's vtable.
        self.f_scroll = e.alloc(16)
        self.f_tick = e.alloc(16)
        self.f_render = e.alloc(16)
        self.probe_vt = e.alloc(64)
        e.write(self.probe_vt, bytes(64))
        for i, fn in ((1, self.f_scroll), (2, F_BASE_HE), (3, self.f_tick),
                      (4, self.f_render), (5, F_BASE_DTOR)):
            e.put32(self.probe_vt + 8 * i + 4, fn)

        self.status = self.advanced = self.fell = 0
        self.opened = self.another = 0
        self.rmask = 0
        self.unlock = 0
        self.probe = False
        self.cb = None
        self.egs = None
        self.obj = None

        for a, fn in ((S_CHANGE, self.change),
                      (S_LIST_CHANGE, self.list_change),
                      (S_VIS, self.vis), (S_OBJVIS, self.objvis),
                      (S_LANG, self.lang), (S_GRAY, self.gray),
                      (S_TR, self.tr), (S_SUMMON, self.summon),
                      (S_PRINT, self.silent), (S_POST, self.post),
                      (S_SETCB, self.setcb), (S_PMALLOC, self.pmalloc),
                      (S_PFREE, self.pfree), (S_MALLOC, self.malloc),
                      (S_MEMSET, self.memset), (B_DELETE, self.delete),
                      (S_HL_CTOR, self.hl_ctor), (S_HL_ITEM, self.hl_item),
                      (S_HL_ANIM, self.hl_anim),
                      (S_UNLOCKED, self.unlocked),
                      (S_STATUS, self.ev_status), (S_RTEST, self.ev_rtest),
                      (S_ADVANCED, self.ev_advanced),
                      (S_FELL, self.ev_fell), (S_OPENED, self.ev_opened),
                      (S_KEEP, self.ev_keep),
                      (S_RESTARTEV, self.ev_restart),
                      (S_ANOTHER, self.ev_another),
                      (self.f_nop, self.silent),
                      (self.f_scroll, self.probe_say("scroll")),
                      (self.f_tick, self.probe_say("tick")),
                      (self.f_render, self.probe_say("render"))):
            e.stub(a, fn)
        for a in CLASS_CTORS:
            e.stub(a, self.class_ctor(a))

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

    def nested(self, fn, *args):
        e = self.e
        kept = (list(e.reg), list(e.fpr), e.hi, e.lo, e.hi1, e.lo1, e.sa,
                e.fcc, e.limit, e.icount)
        try:
            return e.call(fn, *args, limit=2000000)
        finally:
            e.reg[:] = kept[0]
            e.fpr[:] = kept[1]
            (e.hi, e.lo, e.hi1, e.lo1, e.sa, e.fcc, e.limit,
             e.icount) = kept[2:]

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

    def label(self, p):
        if p == 0:
            return "NULL"
        k = self.slot_of(p)
        if k < 0:
            return "?"
        return "m%d+%d" % (k, p - self.slots - k * SLOT_SIZE)

    def free_slot(self, p):
        k = self.slot_of(p)
        if k >= 0:
            self.slot_used[k] = False

    # ---- the stubs

    def silent(self, e):
        pass

    def change(self, e):
        self.emit("  change %s %d" % (self.cstr(self.arg(0)), self.sarg(1)))

    def list_change(self, e):
        self.emit("  change %s %d" % (self.cstr(self.arg(1)), self.sarg(2)))

    def vis(self, e):
        self.emit("  vis %08x %d" % (self.arg(0), self.sarg(1)))

    def objvis(self, e):
        self.emit("  objvis %08x %08x %d" % (self.arg(0), self.arg(1),
                                             self.sarg(2)))

    def lang(self, e):
        self.emit("  lang %08x %08x %x" % (self.arg(0), self.arg(1),
                                           self.arg(2)))

    def gray(self, e):
        self.emit("  gray %08x %d %08x" % (self.arg(0), self.sarg(1),
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
                     u(c + 12), self.cstr(msg),
                     u(c + 20), u(c + 24), u(c + 28), s32(u(c + 32)),
                     s32(u(c + 36)), s32(u(c + 40)), s32(u(c + 44)),
                     s32(u(c + 52)), s32(u(c + 56)), s32(u(c + 60)),
                     u(c + 68)))

    def post(self, e):
        self.emit("  post %s %d %d" % ("rc" if self.arg(0) == self.rc
                                       else "?", self.sarg(1), self.sarg(2)))

    def setcb(self, e):
        self.emit("  setcb")
        self.cb = self.arg(0)

    def pmalloc(self, e):
        for i in range(NUM_NODES):
            if not self.node_used[i]:
                self.node_used[i] = True
                self.emit("  pmalloc %d" % i)
                return self.nodes + i * NODE_SIZE
        raise RuntimeError("out of nodes")

    def node_alloc(self):
        for i in range(NUM_NODES):
            if not self.node_used[i]:
                self.node_used[i] = True
                return self.nodes + i * NODE_SIZE
        raise RuntimeError("out of nodes")

    def pfree(self, e):
        i = (self.arg(0) - self.nodes) // NODE_SIZE
        self.emit("  pfree %d" % i)
        self.node_used[i] = False

    def malloc(self, e):
        a = self.slot_alloc()
        self.emit("  malloc %d %s %d %d m%d" % (self.sarg(0),
                                               self.cstr(self.arg(1)),
                                               self.sarg(2), self.sarg(3),
                                               self.slot_of(a)))
        return a

    def memset(self, e):
        a, v, n = self.arg(0), self.arg(1), self.sarg(2)
        e.write(a, bytes([v & 0xFF]) * n)

    def delete(self, e):
        p = self.arg(0)
        self.emit("  delete %s" % self.label(p))
        self.free_slot(p)

    def hl_ctor(self, e):
        self.emit("  hl_init anim %s %08x %08x %x"
                  % (self.label(self.arg(0)), self.arg(1), self.arg(2),
                     self.arg(3)))

    def hl_item(self, e):
        self.emit("  hl_item anim %s %08x" % (self.label(self.arg(0)),
                                             self.arg(1)))

    def hl_anim(self, e):
        self.emit("  hl_anim anim %s" % self.label(self.arg(0)))

    def unlocked(self, e):
        self.emit("  unlocked %d %d" % (self.sarg(0), self.sarg(1)))
        return s32(self.unlock)

    def ev_status(self, e):
        self.emit("  status")
        return s32(self.status)

    def ev_rtest(self, e):
        i = self.sarg(1)
        self.emit("  rtest %d" % i)
        return (self.rmask >> i) & 1 if 0 <= i < 32 else 0

    def ev_advanced(self, e):
        self.emit("  advanced")
        return s32(self.advanced)

    def ev_fell(self, e):
        self.emit("  fell")
        return s32(self.fell)

    def ev_opened(self, e):
        self.emit("  opened")
        return s32(self.opened)

    def ev_keep(self, e):
        self.emit("  keep")

    def ev_restart(self, e):
        self.emit("  restartev")

    def ev_another(self, e):
        self.emit("  another")
        return s32(self.another)

    def class_ctor(self, at):
        def ctor(e):
            m, h = self.arg(0), self.arg(1)
            self.nested(F_BASE_CTOR, m, h)
            if self.probe and at == TOURNEY_CTOR:
                e.put32(m + 4, self.probe_vt)
            return m
        return ctor

    def probe_say(self, what):
        def say(e):
            self.emit("  %s %s %d" % (what, self.label(self.arg(0)),
                                      self.sarg(1)))
        return say

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

    def vt_name(self, vt):
        return {VT_BASE: "base", VT_MENU: "menu",
                self.probe_vt: "probe"}.get(vt, "?")

    def dump_egs(self):
        e = self.e
        u = e.u32
        g = self.egs
        if g is None:
            self.emit("  egs none")
            return
        head = g + 12
        names = []
        cur = -2
        n = u(head)
        i = 0
        while n != head:
            names.append(self.cstr(u(n + 8)))
            if n == u(g + 20):
                cur = i
            n = u(n)
            i += 1
        if u(g + 20) == head:
            cur = -1
        self.emit("  egs %d %08x %d [%s] cur %d z %s"
                  % (s32(u(g)), u(g + 4), s32(u(g + 8)), ",".join(names),
                     cur, " ".join("%x" % u(g + 24 + 4 * k)
                                   for k in range(12))))

    def dump_menu(self, what, p):
        u = self.e.u32
        vt = u(p + 4)
        line = "  %s %s %s %08x" % (what, self.label(p), self.vt_name(vt),
                                    u(p))
        if vt == VT_MENU:
            line += " state %d labels %s items" % (
                s32(u(p + 8)), " ".join("%x" % u(p + 44 + 4 * k)
                                        for k in range(15)))
            head = p + 104
            n = u(head)
            while n != head:
                line += " %s/%x/%08x/%d" % (self.label(n), u(n + 8),
                                            u(n + 12), s32(u(n + 16)))
                n = u(n)
        self.emit(line)

    def dump(self):
        u = self.e.u32
        self.dump_egs()
        self.emit("  pegs " + self.label(u(P_EGS)))
        inst = u(P_INST)
        if inst == 0:
            self.emit("  inst NULL")
        elif not self.slot_used[self.slot_of(inst)]:
            self.emit("  inst freed")
        else:
            self.dump_menu("inst", inst)
        if self.obj is None:
            self.emit("  obj NULL")
        elif not self.slot_used[self.slot_of(self.obj)]:
            self.emit("  obj freed")
        else:
            self.dump_menu("obj", self.obj)

    def name(self, i):
        return self.names[i if 0 <= i < len(NAMES) else 0]

    def op(self, a):
        e = self.e
        o = a[0]
        n = [int(x, 0) for x in a[1:]]
        if o == "fred":
            for addr, v in zip((F_GAME_TYPE, F_NUM_PLAYER_CARS, F_AUTOSAVE,
                                F_POINTS_REWARD, F_TASK_REWARD), n):
                e.put32(addr, v & M32)
        elif o == "rp":
            for off, v in zip((32, 40, 44, 48, 600, 628), n):
                e.put32(RP + off, v & M32)
        elif o == "ev":
            struct.pack_into("<h", e.mem, EV + 104, n[0])
            struct.pack_into("<h", e.mem, EV + 106, n[1])
            struct.pack_into("<h", e.mem, EV + 114, n[2])
            e.put32(EV + 120, n[3] & M32)
        elif o == "evf":
            (self.status, self.advanced, self.fell, self.opened,
             self.another) = n
        elif o == "rtest":
            self.rmask = n[0]
        elif o == "unlock":
            self.unlock = n[0]
        elif o == "replay":
            if n[0]:
                e.put32(P_REPLAY, self.replay)
                e.put32(self.replay + 12, n[1] & M32)
            else:
                e.put32(P_REPLAY, self.noreplay)
        elif o == "cur":
            if n[0] >= 0:
                e.put32(self.flist + 412, self.screen)
                e.put32(self.cfg + 8, self.name(n[0]))
            else:
                e.put32(self.flist + 412, 0)
        elif o == "probe":
            self.probe = bool(n[0])
        elif o == "egs":
            mem = self.slot_alloc()
            if e.call(F_EGS_CTOR, mem, n[0]) & M32 != mem:
                self.emit("  ctor returned another")
            self.egs = mem
        elif o == "egsdtor":
            if self.egs is not None:
                e.call(F_EGS_DTOR, self.egs, n[0])
                if not n[0] & 1:
                    self.free_slot(self.egs)
                self.egs = None
        elif self.egs is None and o in (
                "build", "next", "remove", "advance", "atroot", "back",
                "current", "resume", "suspend", "autodone", "setcb",
                "insname"):
            self.emit("  no egs")
        elif o == "build":
            e.call(F_BUILD, self.egs)
        elif o == "next":
            self.emit("  = %s" % self.cstr(e.call(F_NEXT, self.egs) & M32))
        elif o == "remove":
            e.call(F_REMOVE, self.egs, self.name(n[0]))
        elif o == "advance":
            e.call(F_ADVANCE, self.egs)
        elif o == "atroot":
            self.emit("  = %d" % e.call(F_AT_ROOT, self.egs))
        elif o == "back":
            e.call(F_BACK, self.egs)
        elif o == "current":
            self.emit("  = %s" % self.cstr(e.call(F_CURRENT, self.egs)
                                           & M32))
        elif o == "resume":
            e.call(F_RESUME, self.egs)
        elif o == "suspend":
            e.call(F_SUSPEND, self.egs)
        elif o == "autodone":
            e.call(F_AUTODONE, self.egs)
        elif o == "setcb":
            e.call(F_SETCB, self.egs)
        elif o == "insname":
            nd = self.node_alloc()
            head = self.egs + 12
            at = e.u32(head)
            pos = n[1]
            while pos > 0 and at != head:
                at = e.u32(at)
                pos -= 1
            e.put32(nd + 8, self.name(n[0]))
            prev = e.u32(at + 4)
            e.put32(nd, at)
            e.put32(nd + 4, prev)
            e.put32(prev, nd)
            e.put32(at + 4, nd)
        elif o == "t":
            self.emit("  = %d" % e.call(TESTS[n[0]]))
        elif o == "base":
            mem = self.slot_alloc()
            if e.call(F_BASE_CTOR, mem, n[0]) & M32 != mem:
                self.emit("  ctor returned another")
            self.obj = mem
        elif o == "bh":
            self.set_data(*n[1:5])
            e.call(F_BASE_HE, self.obj, n[0], self.data, limit=1000000)
            self.print_data()
        elif o == "bdtor":
            e.call(F_BASE_DTOR, self.obj, n[0])
            if not n[0] & 1:
                self.emit("  left " + self.vt_name(e.u32(self.obj + 4)))
                self.free_slot(self.obj)
            self.obj = None
        elif o == "cb":
            self.set_data(*n[1:5])
            e.call(F_CALLBACK, n[0], self.data, limit=1000000)
            self.print_data()
        elif o == "menu":
            mem = self.slot_alloc()
            self.set_data(0, 0, n[1], 0)
            if e.call(F_MENU_CTOR, mem, n[0], self.data,
                      limit=1000000) & M32 != mem:
                self.emit("  ctor returned another")
            self.obj = mem
            self.print_data()
        elif o == "mh":
            self.set_data(*n[1:5])
            e.call(F_MENU_HE, self.obj, n[0], self.data, limit=1000000)
            self.print_data()
        elif o == "mstate":
            e.put32(self.obj + 8, n[0] & M32)
        elif o == "mdtor":
            e.call(F_MENU_DTOR, self.obj, n[0], limit=1000000)
            if not n[0] & 1:
                self.emit("  left " + self.vt_name(e.u32(self.obj + 4)))
                self.free_slot(self.obj)
            self.obj = None
        elif o == "labels":
            e.write(self.lbuf, b"\x5a" * 60)
            e.call(F_LABELS, self.obj or 0, self.lbuf)
            self.emit("  labels " + " ".join(
                "%x" % e.u32(self.lbuf + 4 * k) for k in range(15)))
        elif o == "restart":
            e.call(F_RESTART, self.obj, n[0], n[1], n[2])
        elif o == "find":
            self.emit("  = " + self.label(e.call(F_FIND, self.obj, n[0])
                                          & M32))
        elif o == "fire":
            cb, self.cb = self.cb, None
            if cb is None:
                self.emit("  no cb")
            else:
                e.call(cb, limit=1000000)
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

def build_harness(tmp, name="endgame_test"):
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


def M(name, before, after, rel=EG):
    return (name, rel, before, after)


MUTATIONS = [
    # The screens' names.
    M("name-points", 'PointsRewardsScreen[] = "Points Rewards";',
      'PointsRewardsScreen[] = "Points rewards";'),
    M("name-task", 'TaskRewardsScreen[] = "Task Rewards";',
      'TaskRewardsScreen[] = "Task rewards";'),
    M("name-unlocked", '"Events Unlocked";', '"Events unlocked";'),
    M("name-reward", '"Reward menu";', '"Reward Menu";'),
    M("name-results", '"Race Results";', '"Race results";'),
    M("name-tourney", '"Tourney Standings";', '"Tourney standings";'),
    M("name-best-lap", '"Best Lap Times";', '"Best lap Times";'),
    M("name-best-total", '"Best Total Times";', '"Best total Times";'),
    M("name-autosave", '"Autosave";', '"AutoSave";'),
    M("name-btc1", '"Be The Cop Results 1P";', '"Be the Cop Results 1P";'),
    M("name-btc2", '"Be The Cop Results 2P";', '"Be The Cop Results 1P";'),
    M("name-lap1", '"Lap Times 1P";', '"Lap Times 2P";'),
    M("name-lap2", 'LapTimes2PScreen[] = "Lap Times 2P";',
      'LapTimes2PScreen[] = "Lap Times 1P";'),
    M("name-menu", '"End Game Menu";', '"End game Menu";'),

    # The header's hashes and IDs.
    M("h-letterbox", "LETTERBOX_SCREEN      0x49c15518u",
      "LETTERBOX_SCREEN      0x49c15519u", EH),
    M("h-previous", "OBJ_PREVIOUS          0xaf6f1cdcu",
      "OBJ_PREVIOUS          0xaf6f1cddu", EH),
    M("h-title", "OBJ_TITLE        0x5964eab1u", "OBJ_TITLE        0x5964eab0u",
      EH),
    M("h-bloom", "OBJ_BLOOM        0xab671c9au", "OBJ_BLOOM        0xab671c9bu",
      EH),
    M("h-item1", "ITEM_1           0x52e039f3u", "ITEM_1           0x52e039f2u",
      EH),
    M("h-popup", "POPUP_SCREEN          0x037f3133u",
      "POPUP_SCREEN          0x037f3134u", EH),
    M("h-ok", "LANG_OK               0x38277", "LANG_OK               0x38276",
      EH),
    M("h-cancel", "LANG_CANCEL           0x38278",
      "LANG_CANCEL           0x38279", EH),
    M("h-kind-quit", "END_GAME_ITEM_QUIT           5",
      "END_GAME_ITEM_QUIT           6", EH),
    M("h-kind-next", "END_GAME_ITEM_NEXT_RACE      0",
      "END_GAME_ITEM_NEXT_RACE      7", EH),
    M("h-state-quit", "MENU_STATE_QUIT           2", "MENU_STATE_QUIT           4",
      EH),
    M("h-state-next", "MENU_STATE_NEXT_RACE      3",
      "MENU_STATE_NEXT_RACE      5", EH),
    M("pool", "#define END_GAME_POOL 16", "#define END_GAME_POOL 15"),
    M("gray-enable", "#define GRAY_ENABLE 1", "#define GRAY_ENABLE 0"),
    M("gray-hide", "#define GRAY_HIDE   2", "#define GRAY_HIDE   3"),
    M("popup-flags", "(BPOPUP_HORIZONTAL | BPOPUP_CANCELABLE)",
      "(BPOPUP_CANCELABLE)"),
    M("items-6", "END_GAME_MENU_ITEM_1 + 4, END_GAME_MENU_ITEM_1 + 5,",
      "END_GAME_MENU_ITEM_1 + 4, END_GAME_MENU_ITEM_1 + 6,"),

    # The tests.
    M("btc1-cars", "Fred.NumPlayerCars == 1;", "Fred.NumPlayerCars >= 1;"),
    M("btc2-cars", "Fred.NumPlayerCars == 2;", "Fred.NumPlayerCars >= 2;"),
    M("btc1-cop", "return TheRaceParameters.BeACop && Fred.NumPlayerCars == 1",
      "return Fred.NumPlayerCars == 1"),
    M("reward-tree", "    if (!fred_use_tree_event(&Fred))" + NL
      + "        return 0;" + NL + "    if (ev->Number == 32)",
      "    if (ev->Number == 32)"),
    M("reward-32", "ev->Number == 32)", "ev->Number == 30)"),
    M("reward-31", "ev->Number == 31 && ev->EventWord == 0)",
      "ev->Number == 31)"),
    M("reward-31-word", "ev->EventWord == 0)", "ev->EventWord >= 0)"),
    M("reward-status-3", "race_event_status() >= 3 && race_event_reward_test",
      "race_event_status() > 3 && race_event_reward_test"),
    M("reward-test-order",
      "race_event_status() >= 3 && race_event_reward_test(i) == 0",
      "race_event_reward_test(i) == 0 && race_event_status() >= 3"),
    M("reward-test-0", "race_event_reward_test(i) == 0)",
      "race_event_reward_test(i) != 0)"),
    M("reward-test-i", "race_event_reward_test(i) == 0)",
      "race_event_reward_test(0) == 0)"),
    M("reward-nrew", "if (ev->NumRewards != 0)", "if (ev->NumRewards > 0)"),
    M("reward-status-lt3", "if (race_event_status() < 3)",
      "if (race_event_status() < 4)"),
    M("reward-adv", "    return race_event_status_advanced();" + NL + "}",
      "    return race_event_status_advanced() != 0;" + NL + "}"),
    M("points-none", "if (reward == -1)", "if (reward < 0)"),
    M("points-gt", "(reward), 3);", "(reward), 4);"),
    M("points-car", "is_car_unlocked(nfs_get_car_type_for_points_reward(reward)",
      "is_car_unlocked((reward)"),
    M("points-bool", "return is_car_unlocked(", "return !!is_car_unlocked("),
    M("unlocked-tree", "int32_t endgame_should_see_events_unlocked(void)" + NL
      + "{" + NL + "    if (!fred_use_tree_event(&Fred))" + NL
      + "        return 0;" + NL,
      "int32_t endgame_should_see_events_unlocked(void)" + NL + "{" + NL),
    M("unlocked-4", "if (race_event_status() != 4)",
      "if (race_event_status() < 4)"),
    M("unlocked-adv", "    if (!race_event_status_advanced())" + NL
      + "        return 0;" + NL, ""),
    M("unlocked-opened", "race_event_num_opened() > 0;",
      "race_event_num_opened() != 0;"),
    M("task", "TaskRewardEarned != -1;", "TaskRewardEarned >= 0;"),
    M("results-6", "endgame_should_see_race_results(void)" + NL + "{" + NL
      + "    int32_t t = Fred.GameType;" + NL + NL
      + "    if (TheRaceParameters.BeACop || t == 6)",
      "endgame_should_see_race_results(void)" + NL + "{" + NL
      + "    int32_t t = Fred.GameType;" + NL + NL
      + "    if (TheRaceParameters.BeACop)"),
    M("results-cop", "endgame_should_see_race_results(void)" + NL + "{" + NL
      + "    int32_t t = Fred.GameType;" + NL + NL
      + "    if (TheRaceParameters.BeACop || t == 6)",
      "endgame_should_see_race_results(void)" + NL + "{" + NL
      + "    int32_t t = Fred.GameType;" + NL + NL + "    if (t == 6)"),
    M("results-type", "Type != 1;" + NL + "    return 1;" + NL + "}" + NL + NL
      + "int32_t endgame_should_see_tourney",
      "Type != 2;" + NL + "    return 1;" + NL + "}" + NL + NL
      + "int32_t endgame_should_see_tourney"),
    M("results-9", "    if (t == 8 || t == 9)" + NL
      + "        return TheRaceEventFields.Type != 1;" + NL + "    return 1;"
      + NL + "}" + NL + NL + "int32_t endgame_should_see_tourney",
      "    if (t == 8)" + NL
      + "        return TheRaceEventFields.Type != 1;" + NL + "    return 1;"
      + NL + "}" + NL + NL + "int32_t endgame_should_see_tourney"),
    M("tourney-cop", "    if (TheRaceParameters.BeACop)" + NL
      + "        return 0;" + NL + "    if (t == 8 || t == 9)" + NL
      + "        return TheRaceEventFields.Type == 4;",
      "    if (t == 8 || t == 9)" + NL
      + "        return TheRaceEventFields.Type == 4;"),
    M("tourney-4", "Type == 4;", "Type == 2;"),
    M("tourney-9", "    if (t == 8 || t == 9)" + NL
      + "        return TheRaceEventFields.Type == 4;",
      "    if (t == 8)" + NL + "        return TheRaceEventFields.Type == 4;"),
    M("tourney-else", "Type == 4;" + NL + "    return 0;",
      "Type == 4;" + NL + "    return 1;"),
    M("lap-cop", "if (rp->BeACop || Fred.GameType == 6",
      "if (Fred.GameType == 6"),
    M("lap-6", "Fred.GameType == 6 || rp->Point2Point", "rp->Point2Point"),
    M("lap-p2p", "rp->Point2Point != 0)", "rp->Point2Point == 1)"),
    M("lap-laps", "rp->NumLapsInRace != 1;", "rp->NumLapsInRace > 1;"),
    M("total-6", "endgame_should_see_best_total_times(void)" + NL + "{" + NL
      + "    int32_t t = Fred.GameType;" + NL + NL
      + "    if (TheRaceParameters.BeACop || t == 6)",
      "endgame_should_see_best_total_times(void)" + NL + "{" + NL
      + "    int32_t t = Fred.GameType;" + NL + NL
      + "    if (TheRaceParameters.BeACop)"),
    M("total-type", "Type != 1;" + NL + "    return 1;" + NL + "}" + NL + NL
      + "int32_t endgame_should_auto_save",
      "Type > 1;" + NL + "    return 1;" + NL + "}" + NL + NL
      + "int32_t endgame_should_auto_save"),
    M("total-9", "    if (t == 8 || t == 9)" + NL
      + "        return TheRaceEventFields.Type != 1;" + NL + "    return 1;"
      + NL + "}" + NL + NL + "int32_t endgame_should_auto_save",
      "    if (t == 9)" + NL
      + "        return TheRaceEventFields.Type != 1;" + NL + "    return 1;"
      + NL + "}" + NL + NL + "int32_t endgame_should_auto_save"),
    M("autosave", "Fred.Autosave != 0;", "Fred.Autosave > 0;"),
    M("end-game", "endgame_should_see_end_game(void)" + NL + "{" + NL
      + "    return 1;", "endgame_should_see_end_game(void)" + NL + "{" + NL
      + "    return 0;"),
    M("not-6", "Fred.GameType != 6;", "Fred.GameType < 6;"),

    # The list.
    M("build-task", "add_screen(s, kEndGameTaskRewardsScreen);",
      "add_screen(s, kEndGamePointsRewardsScreen);"),
    M("build-order", "    if (endgame_should_see_race_results())" + NL
      + "        add_screen(s, kEndGameRaceResultsScreen);" + NL
      + "    if (endgame_should_see_tourney())" + NL
      + "        add_screen(s, kEndGameTourneyStandingsScreen);",
      "    if (endgame_should_see_tourney())" + NL
      + "        add_screen(s, kEndGameTourneyStandingsScreen);" + NL
      + "    if (endgame_should_see_race_results())" + NL
      + "        add_screen(s, kEndGameRaceResultsScreen);"),
    M("build-btc2", "add_screen(s, kEndGameBTCResults2PScreen);",
      "add_screen(s, kEndGameBTCResults1PScreen);"),
    M("build-lap", "add_screen(s, kEndGameBestLapTimesScreen);",
      "add_screen(s, kEndGameBestTotalTimesScreen);"),
    M("add-head", "    n->Node.next = head;" + NL
      + "    n->Node.prev = head->prev;" + NL
      + "    head->prev->next = &n->Node;" + NL + "    head->prev = &n->Node;",
      "    n->Node.prev = head;" + NL + "    n->Node.next = head->next;" + NL
      + "    head->next->prev = &n->Node;" + NL + "    head->next = &n->Node;"),
    M("ctor-type", "s->ContinueRaceType = continueType;",
      "s->ContinueRaceType = 0;"),
    M("ctor-pegs", "    pEndGameScreens = s;" + NL
      + "    endgame_screens_build", "    endgame_screens_build"),
    M("ctor-current", "s->CurrentScreen = s->ScreenList.next;",
      "s->CurrentScreen = &s->ScreenList;"),
    M("ctor-enabled", "s->ScreensEnabled = 0;" + NL + "    memset",
      "s->ScreensEnabled = 1;" + NL + "    memset"),
    M("ctor-zeroed", "    memset(s->Zeroed, 0, sizeof s->Zeroed);" + NL, ""),
    M("dtor-change", "    if (s->ScreensEnabled)" + NL
      + "        change_to_screen(NULL, 0);" + NL + "    pEndGameScreens",
      "    pEndGameScreens"),
    M("dtor-pegs", "    pEndGameScreens = NULL;" + NL + "    while", "    while"),
    M("dtor-flags", "    if (flags & 1)" + NL + "        bFree(s);",
      "    if (flags & 2)" + NL + "        bFree(s);"),
    M("dtor-nodes", "        remove_node(s->ScreenList.next);",
      "        s->ScreenList.next = &s->ScreenList;"),
    M("next-end", "return n == &s->ScreenList ? NULL : node_name(n);",
      "return n == s->CurrentScreen ? NULL : node_name(n);"),
    M("remove-all", "            remove_node(n);" + NL + "            return;",
      "            remove_node(n);"),
    M("remove-cmp", "if (strcmp(node_name(n), name) == 0) {",
      "if (strcmp(node_name(n), name) != 0) {"),
    M("remove-free", "    n->next->prev = n->prev;" + NL
      + "    bpnode_free(n);", "    n->next->prev = n->prev;"),
    M("advance-end", "    if (n != &s->ScreenList)" + NL
      + "        s->CurrentScreen = n;", "    s->CurrentScreen = n;"),
    M("at-root", "return s->CurrentScreen == s->ScreenList.next;",
      "return s->CurrentScreen == s->ScreenList.prev;"),
    M("back-root", "    if (s->CurrentScreen != s->ScreenList.next)" + NL
      + "        s->CurrentScreen = s->CurrentScreen->prev;",
      "    s->CurrentScreen = s->CurrentScreen->prev;"),
    M("current-head", "    if (s->CurrentScreen == &s->ScreenList)" + NL
      + "        return NULL;" + NL + "    return node_name",
      "    return node_name"),
    M("resume-enabled", "if (s == NULL || s->ScreensEnabled)",
      "if (s == NULL)"),
    M("resume-set", "    s->ScreensEnabled = 1;" + NL + "    cur", "    cur"),
    M("resume-autosave", "strcmp(cur, kEndGameAutosaveScreen) == 0) {",
      "strcmp(cur, kEndGameAutosaveScreen) != 0) {"),
    M("resume-advance", "        endgame_screens_advance_screen(s);" + NL
      + "        endgame_screens_remove_screen(s, kEndGameAutosaveScreen);",
      "        endgame_screens_remove_screen(s, kEndGameAutosaveScreen);"),
    M("resume-remove",
      "        endgame_screens_remove_screen(s, kEndGameAutosaveScreen);"
      + NL, ""),
    M("resume-push-auto", "change_to_screen(kEndGameAutosaveScreen, 1);",
      "change_to_screen(kEndGameAutosaveScreen, 0);"),
    M("resume-cb", "        endgame_screens_set_autosave_callback(s);" + NL
      + "    } else {", "    } else {"),
    M("resume-push", "change_to_screen(endgame_screens_get_current_screen(s), 1);",
      "change_to_screen(endgame_screens_get_current_screen(s), 0);"),
    M("resume-vis", "LETTERBOX_SCREEN, FLAILER_SCREEN_VISIBLE);",
      "LETTERBOX_SCREEN, FLAILER_SCREEN_INVISIBLE);"),
    M("suspend-enabled", "if (s == NULL || !s->ScreensEnabled)",
      "if (s == NULL)"),
    M("suspend-clear", "    s->ScreensEnabled = 0;" + NL
      + "    change_to_screen(NULL, 0);", "    change_to_screen(NULL, 0);"),
    M("suspend-vis", "                          FLAILER_SCREEN_INVISIBLE);",
      "                          FLAILER_SCREEN_VISIBLE);"),
    M("autodone-advance", "    endgame_screens_advance_screen(s);" + NL
      + "    change_to_screen(endgame_screens_get_current_screen(s), 0);" + NL
      + "}" + NL + NL + "// 0x001e25e8",
      "    change_to_screen(endgame_screens_get_current_screen(s), 0);" + NL
      + "}" + NL + NL + "// 0x001e25e8"),
    M("autodone-push",
      "    change_to_screen(endgame_screens_get_current_screen(s), 0);" + NL
      + "}" + NL + NL + "// 0x001e25e8",
      "    change_to_screen(endgame_screens_get_current_screen(s), 1);" + NL
      + "}" + NL + NL + "// 0x001e25e8"),
    M("bridge", "        endgame_screens_autosave_completed(pEndGameScreens);",
      "        ;"),
    M("setcb", "set_autosave_completion_callback(autosave_completed_bridge);",
      "set_autosave_completion_callback(NULL);"),

    # The base.
    M("base-vt", "    m->vt = &kEndGameMenusBaseVTable;" + NL
      + "    m->ScreenHash = hash;", "    m->vt = &kEndGameMenuVTable;" + NL
      + "    m->ScreenHash = hash;"),
    M("base-hash", "m->ScreenHash = hash;", "m->ScreenHash = hash + 1;"),
    M("base-prev", "? FLAILER_OBJECT_INVISIBLE" + NL
      + "                               : FLAILER_OBJECT_VISIBLE",
      "? FLAILER_OBJECT_VISIBLE" + NL
      + "                               : FLAILER_OBJECT_INVISIBLE"),
    M("base-prev-null", "s == NULL || endgame_screens_at_root(s)",
      "s != NULL && endgame_screens_at_root(s)"),
    M("select-autosave", "strcmp(next, kEndGameAutosaveScreen) == 0) {",
      "strcmp(next, kEndGameAutosaveScreen) != 0) {"),
    M("select-null", "if (next != NULL && strcmp(next,",
      "if (next != NULL && 0 && strcmp(next,"),
    M("select-order", "        endgame_screens_remove_screen(s, next);" + NL
      + "        endgame_screens_advance_screen(s);",
      "        endgame_screens_advance_screen(s);" + NL
      + "        endgame_screens_remove_screen(s, next);"),
    M("select-auto-push", "        change_to_screen(next, 0);" + NL
      + "        endgame_screens_set_autosave_callback(s);",
      "        change_to_screen(next, 1);" + NL
      + "        endgame_screens_set_autosave_callback(s);"),
    M("select-cb", "        endgame_screens_set_autosave_callback(s);" + NL
      + "        return;", "        return;"),
    M("select-advance", "    endgame_screens_advance_screen(s);" + NL
      + "    change_to_screen(next, 0);" + NL + "}",
      "    change_to_screen(next, 0);" + NL + "}"),
    M("select-push", "    change_to_screen(next, 0);" + NL + "}",
      "    change_to_screen(next, 1);" + NL + "}"),
    M("back-noise0", "    data->noise = 0;" + NL + "    if (s == NULL) {",
      "    if (s == NULL) {"),
    M("back-null-param", "        data->param = 0;" + NL + "        return;",
      "        return;"),
    M("back-cancel", "data->noise = BSND_MENU_CANCEL;", "data->noise = 5;"),
    M("back-was", "endgame_screens_get_current_screen(s) != was) {",
      "endgame_screens_get_current_screen(s) == was) {"),
    M("back-push", "        data->noise = BSND_MENU_CANCEL;" + NL
      + "        change_to_screen(endgame_screens_get_current_screen(s), 0);",
      "        data->noise = BSND_MENU_CANCEL;" + NL
      + "        change_to_screen(endgame_screens_get_current_screen(s), 1);"),
    M("back-param", "    data->param = 0;" + NL + "}" + NL + NL
      + "void endgame_menus_base_handle_event", "}" + NL + NL
      + "void endgame_menus_base_handle_event"),
    M("he-select", "    case BMSG_MENUITEM_SELECT:" + NL
      + "        base_select();", "    case BMSG_MENUITEM_HIGHLIGHT:" + NL
      + "        base_select();"),
    M("he-pad-up", "    case BMSG_MENUITEM_PAD_UP:" + NL
      + "    case BMSG_MENUITEM_PAD_DOWN:",
      "    case BMSG_MENUITEM_PAD_DOWN:"),
    M("he-pad-down", "    case BMSG_MENUITEM_PAD_DOWN:" + NL
      + "        data->noise = 0;", "        data->noise = 0;"),
    M("he-pad-left", "    case BMSG_MENUITEM_PAD_LEFT:" + NL
      + "    case BMSG_MENUITEM_PAD_RIGHT:",
      "    case BMSG_MENUITEM_PAD_RIGHT:"),
    M("he-scroll", "m->vt->Scroll(m, msg, data);", "m->vt->Tick(m, msg, data);"),
    M("he-tick", "m->vt->Tick(m, msg, data);", "m->vt->Render(m, msg, data);"),
    M("he-render", "m->vt->Render(m, msg, data);",
      "m->vt->Scroll(m, msg, data);"),
    M("base-dtor-vt", "    m->vt = &kEndGameMenusBaseVTable;" + NL
      + "    if (flags & 1)", "    if (flags & 1)"),
    M("base-dtor-flags", "    if (flags & 1)" + NL + "        bFree(m);",
      "    if (flags & 2)" + NL + "        bFree(m);"),

    # The callback and its classes.
    M("class-tourney", "END_GAME_CLASS_TOURNEY_STANDINGS, 8,",
      "END_GAME_CLASS_RACE_RESULTS, 8,"),
    M("class-results-size", "END_GAME_CLASS_RACE_RESULTS, 60,",
      "END_GAME_CLASS_RACE_RESULTS, 56,"),
    M("class-menu-size", "END_GAME_CLASS_MENU, 112,",
      "END_GAME_CLASS_MENU, 116,"),
    M("class-points-name", '"Points Rewards" },', '"Points Reward" },'),
    M("class-reward-name", '"EventRewardScreen" },',
      '"EventRewardsScreen" },'),
    M("class-btc2-name", '"BeACopResults2P" },', '"BeACopResults1P" },'),
    M("class-lap-name", '"BestLapTimes" },', '"BestLapTime" },'),
    M("class-cmp", "if (strcmp(name, c->Screen) != 0)",
      "if (strncmp(name, c->Screen, 4) != 0)"),
    M("class-menu", "if (c->Class == END_GAME_CLASS_MENU)",
      "if (c->Class == END_GAME_CLASS_RACE_RESULTS)"),
    M("class-menu-hash", "endgame_menu_construct(mem, data->itemHash, data);",
      "endgame_menu_construct(mem, data->itemHash + 1, data);"),
    M("class-ctor-hash", "[c->Class](mem, data->itemHash, data);",
      "[c->Class](mem, data->itemHash ^ 1, data);"),
    M("class-base-hash", "(EndGameMenusBase *)mem, data->itemHash);",
      "(EndGameMenusBase *)mem, data->itemHash ^ 1);"),
    M("cb-destroy", "m->vt->Destroy(m, 3);", "m->vt->Destroy(m, 2);"),
    M("cb-unactivate-null", "        pEndGameMenuInstance = NULL;" + NL
      + "    } else if", "    } else if"),
    M("cb-event", "        m->vt->HandleEvent(m, msg, data);" + NL
      + "    }" + NL + "}", "    }" + NL + "}"),
    M("cb-activate", "if (msg == BMSG_SCREEN_ACTIVATE) {",
      "if (msg == BMSG_SCREEN_START_BUTTON) {"),

    # The menu: its items.
    M("next-race", "return fred_is_multi_track(&Fred) && "
      "fred_is_there_another_race(&Fred);",
      "return fred_is_multi_track(&Fred) || "
      "fred_is_there_another_race(&Fred);"),
    M("restart-race-9", "    if (t == 8 || t == 9)" + NL
      + "        return fred_is_multi_track(&Fred);",
      "    if (t == 8)" + NL + "        return fred_is_multi_track(&Fred);"),
    M("restart-race-mt", "        return fred_is_multi_track(&Fred);" + NL
      + "    return 1;", "        return 0;" + NL + "    return 1;"),
    M("restart-event", "fred_is_multi_track(&Fred) || "
      "fred_use_the_race_event(&Fred);",
      "fred_is_multi_track(&Fred) && fred_use_the_race_event(&Fred);"),
    M("replay-mute", "gReplayMuteHighlightsFn(rm) == 0;",
      "gReplayMuteHighlightsFn(rm) <= 0;"),
    M("lap-times", "return !TheRaceParameters.BeACop;", "return 1;"),
    M("item-size", 'bMalloc(20, "EndGameMenuItem",',
      'bMalloc(24, "EndGameMenuItem",'),
    M("item-name", '"EndGameMenuItem",', '"EndGameMenuitem",'),
    M("item-tail", "    it->Node.next = head;" + NL
      + "    it->Node.prev = head->prev;" + NL
      + "    head->prev->next = &it->Node;" + NL
      + "    head->prev = &it->Node;",
      "    it->Node.prev = head;" + NL + "    it->Node.next = head->next;"
      + NL + "    head->next->prev = &it->Node;" + NL
      + "    head->next = &it->Node;"),
    M("item-label-next", "m->Labels[10], END_GAME_ITEM_NEXT_RACE",
      "m->Labels[11], END_GAME_ITEM_NEXT_RACE"),
    M("item-label-race", "m->Labels[1], END_GAME_ITEM_RESTART_RACE",
      "m->Labels[2], END_GAME_ITEM_RESTART_RACE"),
    M("item-label-event", "m->Labels[4], END_GAME_ITEM_RESTART_EVENT",
      "m->Labels[5], END_GAME_ITEM_RESTART_EVENT"),
    M("item-label-replay", "m->Labels[13], END_GAME_ITEM_VIEW_REPLAY",
      "m->Labels[12], END_GAME_ITEM_VIEW_REPLAY"),
    M("item-label-lap", "m->Labels[14], END_GAME_ITEM_LAP_TIMES",
      "m->Labels[13], END_GAME_ITEM_LAP_TIMES"),
    M("item-label-quit", "m->Labels[7], END_GAME_ITEM_QUIT",
      "m->Labels[8], END_GAME_ITEM_QUIT"),
    M("item-kind-event", "m->Labels[4], END_GAME_ITEM_RESTART_EVENT",
      "m->Labels[4], END_GAME_ITEM_RESTART_RACE"),
    M("item-order", "    if (has_restart_race())" + NL
      + "        add_item(m, m->Labels[1], END_GAME_ITEM_RESTART_RACE);" + NL
      + "    if (has_restart_event())" + NL
      + "        add_item(m, m->Labels[4], END_GAME_ITEM_RESTART_EVENT);",
      "    if (has_restart_event())" + NL
      + "        add_item(m, m->Labels[4], END_GAME_ITEM_RESTART_EVENT);" + NL
      + "    if (has_restart_race())" + NL
      + "        add_item(m, m->Labels[1], END_GAME_ITEM_RESTART_RACE);"),

    # The menu: its constructor.
    M("menu-vt", "    m->Base.vt = &kEndGameMenuVTable;" + NL
      + "    if ((a = anim()) != NULL)", "    if ((a = anim()) != NULL)"),
    M("menu-bloom-color", "(int32_t)BANIM_BLOOM_COLOR);",
      "(int32_t)BANIM_BLOOM_COLOR + 1);"),
    M("menu-param", "    data->param = 0;" + NL + NL
      + "    if (has_next_race())", "    if (has_next_race())"),
    M("menu-lang-label", "flailer_set_language_id(screen, item, "
      "(uint32_t)it->Label);", "flailer_set_language_id(screen, item, "
      "(uint32_t)it->Kind);"),
    M("menu-gray-enable", "gray_menu_item(item, GRAY_ENABLE,",
      "gray_menu_item(item, GRAY_HIDE,"),
    M("menu-gray-hide", "gray_menu_item(kMenuItems[placed], GRAY_HIDE,",
      "gray_menu_item(kMenuItems[placed], GRAY_ENABLE,"),
    M("menu-hash", "        it->Hash = item;" + NL, ""),
    M("menu-title", "END_GAME_MENU_OBJ_TITLE," + NL
      + "                            (uint32_t)m->Labels[0]);",
      "END_GAME_MENU_OBJ_TITLE," + NL
      + "                            (uint32_t)m->Labels[1]);"),

    # InitLabels.
    M("labels-ff", "memset(labels, 0xff,", "memset(labels, 0xfe,"),
    M("labels-10", "labels[10] = 0x4baf2;", "labels[10] = 0x4baf3;"),
    M("labels-11", "labels[11] = 0x382d5;", "labels[11] = 0x382d6;"),
    M("labels-12", "labels[12] = 0x382d4;", "labels[12] = 0x382d3;"),
    M("labels-13", "labels[13] = 0x30d43;", "labels[13] = 0x30d42;"),
    M("labels-14", "labels[14] = 0x4bd49;", "labels[14] = 0x4bd48;"),
    M("labels-4", "labels[4] = 0x30d4d;", "labels[4] = 0x30d4c;"),
    M("labels-5", "labels[5] = 0x38280;", "labels[5] = 0x38281;"),
    M("labels-6", "labels[6] = 0x38286;", "labels[6] = 0x38287;"),
    M("labels-tree", "if (rp->EventTreeRace) {", "if (!rp->EventTreeRace) {"),
    M("labels-tree-1", "    if (rp->EventTreeRace) {" + NL
      + "        labels[1] = 0x30d45;", "    if (rp->EventTreeRace) {" + NL
      + "        labels[1] = 0x30d44;"),
    M("labels-tree-2", "labels[3] = 0x3827c;" + NL
      + "        labels[0] = fred", "labels[3] = 0x3827d;" + NL
      + "        labels[0] = fred"),
    M("labels-tree-0", "? 0x30da4 : 0x30da6;", "? 0x30da6 : 0x30da4;"),
    M("labels-tree-another", "&& fred_is_there_another_race(&Fred)" + NL
      + "                    ?", "|| fred_is_there_another_race(&Fred)" + NL
      + "                    ?"),
    M("labels-gt9", "if (Fred.GameType == 9) {", "if (Fred.GameType == 8) {"),
    M("labels-7-9", "labels[7] = 0x38338;", "labels[7] = 0x38339;"),
    M("labels-8-9", "labels[8] = 0x38339;", "labels[8] = 0x38338;"),
    M("labels-7-8", "labels[7] = 0x3833a;", "labels[7] = 0x3833b;"),
    M("labels-8-8", "labels[8] = 0x3833b;", "labels[8] = 0x3833a;"),
    M("labels-9-tree", "labels[9] = 0x38287;", "labels[9] = 0x38286;"),
    M("labels-cop", "} else if (rp->BeACop) {", "} else if (0) {"),
    M("labels-cop-0", "labels[0] = 0x30da5;", "labels[0] = 0x30da4;"),
    M("labels-cop-1", "labels[1] = 0x30d51;", "labels[1] = 0x30d50;"),
    M("labels-cop-2", "labels[2] = 0x38281;", "labels[2] = 0x38280;"),
    M("labels-cop-3", "labels[3] = 0x38285;", "labels[3] = 0x38284;"),
    M("labels-cop-7", "labels[7] = 0x30d52;", "labels[7] = 0x30d53;"),
    M("labels-cop-8", "labels[8] = 0x38282;", "labels[8] = 0x38283;"),
    M("labels-cop-9", "labels[9] = 0x38283;", "labels[9] = 0x38282;"),
    M("labels-else-0", "        labels[0] = 0x30da4;" + NL
      + "        labels[1]", "        labels[0] = 0x30da6;" + NL
      + "        labels[1]"),
    M("labels-else-1", "labels[0] = 0x30da4;" + NL
      + "        labels[1] = 0x30d45;", "labels[0] = 0x30da4;" + NL
      + "        labels[1] = 0x30d46;"),
    M("labels-else-7", "labels[7] = 0x30d46;", "labels[7] = 0x30d45;"),
    M("labels-else-8", "labels[8] = 0x38272;", "labels[8] = 0x38271;"),
    M("labels-else-9", "labels[9] = 0x3827b;", "labels[9] = 0x3827c;"),

    # MaybeRestart.
    M("popup-buttons", "cfg.numButtons = 2;", "cfg.numButtons = 3;"),
    M("popup-flags-set", "cfg.flags = END_GAME_POPUP_FLAGS;",
      "cfg.flags = 0;"),
    M("popup-ok", "cfg.button[0] = END_GAME_LANG_OK;",
      "cfg.button[0] = END_GAME_LANG_CANCEL;"),
    M("popup-cancel", "cfg.button[1] = END_GAME_LANG_CANCEL;",
      "cfg.button[1] = END_GAME_LANG_OK;"),
    M("popup-b2", "cfg.button[2] = 0;", "cfg.button[2] = 1;"),
    M("popup-title", "cfg.title = title;", "cfg.title = message;"),
    M("popup-message", "cfg.message = translate(message);",
      "cfg.message = translate(title);"),
    M("popup-parent", "cfg.parent = current_screen();", "cfg.parent = NULL;"),
    M("popup-screen", "cfg.screen = END_GAME_POPUP_SCREEN;",
      "cfg.screen = END_GAME_POPUP_SCREEN + 1;"),
    M("popup-p0", "cfg.buttonParam[0] = 1;", "cfg.buttonParam[0] = 0;"),
    M("popup-p1", "cfg.buttonParam[1] = 0;", "cfg.buttonParam[1] = 1;"),
    M("popup-p2", "cfg.buttonParam[2] = 0;", "cfg.buttonParam[2] = 1;"),
    M("popup-cancel-param", "cfg.cancelParam = 0;", "cfg.cancelParam = 1;"),
    M("popup-start", "cfg.startButton = 1;", "cfg.startButton = 0;"),
    M("popup-port", "cfg.joyPort = -1;", "cfg.joyPort = 0;"),
    M("popup-timeout", "cfg.timeout = 0;", "cfg.timeout = 1;"),
    M("popup-state", "m->State = state;", "m->State = state + 1;"),
    M("popup-hide", "    set_screen_visibility(m->Base.ScreenHash, "
      "FLAILER_SCREEN_INVISIBLE);" + NL + "}",
      "    set_screen_visibility(m->Base.ScreenHash, "
      "FLAILER_SCREEN_VISIBLE);" + NL + "}"),
    M("find", "((EndGameMenuItem *)n)->Hash == hash)",
      "((EndGameMenuItem *)n)->Hash != hash)"),

    # The items' actions.
    M("act-next", "endgame_menu_maybe_restart(m, l[12], l[11],",
      "endgame_menu_maybe_restart(m, l[11], l[12],"),
    M("act-next-state", "                                   "
      "END_GAME_MENU_STATE_NEXT_RACE);",
      "                                   END_GAME_MENU_STATE_QUIT);"),
    M("act-race", "endgame_menu_maybe_restart(m, l[3], l[2],",
      "endgame_menu_maybe_restart(m, l[2], l[3],"),
    M("act-race-state", "                                   "
      "END_GAME_MENU_STATE_RESTART_RACE);",
      "                                   END_GAME_MENU_STATE_NEXT_RACE);"),
    M("act-event", "endgame_menu_maybe_restart(m, l[6], l[5],",
      "endgame_menu_maybe_restart(m, l[5], l[6],"),
    M("act-event-state", "                                   "
      "END_GAME_MENU_STATE_RESTART_EVENT);",
      "                                   END_GAME_MENU_STATE_RESTART_RACE);"),
    M("act-replay", "post(RC_START_REPLAY, 0);", "post(RC_START_REPLAY, 1);"),
    M("act-lap-cars", "TheRaceParameters.NumPlayerCars == 1",
      "TheRaceParameters.NumPlayerCars != 2"),
    M("act-lap-push", "                         1);" + NL + "        break;",
      "                         0);" + NL + "        break;"),
    M("act-quit", "endgame_menu_maybe_restart(m, l[9], l[8], "
      "END_GAME_MENU_STATE_QUIT);", "endgame_menu_maybe_restart(m, l[8], "
      "l[9], END_GAME_MENU_STATE_QUIT);"),
    M("act-quit-state", "l[9], l[8], END_GAME_MENU_STATE_QUIT);",
      "l[9], l[8], END_GAME_MENU_STATE_RESTART_EVENT);"),

    # The popups' answers.
    M("quit-race", "post(RC_QUIT_RACE, 0);", "post(RC_QUIT_RACE, 1);"),
    M("next-race-post", "post(RC_NEXT_RACE, 1);", "post(RC_NEXT_RACE, 0);"),
    M("dismiss-quit-param", "    case END_GAME_MENU_STATE_QUIT:" + NL
      + "        if (data->param == 0)", "    case END_GAME_MENU_STATE_QUIT:"
      + NL + "        if (data->param != 1)"),
    M("dismiss-quit-keep", "        if (fred_use_the_race_event(&Fred))" + NL
      + "            race_event_keep_state();" + NL
      + "        if (endgame_should_auto_save()) {",
      "        if (endgame_should_auto_save()) {"),
    M("dismiss-quit-auto", "        if (endgame_should_auto_save()) {",
      "        if (0) {"),
    M("dismiss-quit-push", "            change_to_screen(kEndGameAutosaveScreen, "
      "0);" + NL + "            set_autosave_completion_callback(quit_race);",
      "            change_to_screen(kEndGameAutosaveScreen, 1);" + NL
      + "            set_autosave_completion_callback(quit_race);"),
    M("dismiss-quit-cb", "set_autosave_completion_callback(quit_race);",
      "set_autosave_completion_callback(next_race);"),
    M("dismiss-quit-now", "            quit_race();", "            next_race();"),
    M("dismiss-race-param", "    case END_GAME_MENU_STATE_RESTART_RACE:" + NL
      + "        if (data->param == 0)",
      "    case END_GAME_MENU_STATE_RESTART_RACE:" + NL
      + "        if (data->param < 1)"),
    M("dismiss-race-keep", "            race_event_keep_state();" + NL
      + "        post(RC_RESTART_RACE, 0);", "        post(RC_RESTART_RACE, 0);"),
    M("dismiss-race-event", "        if (fred_use_the_race_event(&Fred))" + NL
      + "            race_event_keep_state();" + NL
      + "        post(RC_RESTART_RACE, 0);",
      "        race_event_keep_state();" + NL
      + "        post(RC_RESTART_RACE, 0);"),
    M("dismiss-race-post", "post(RC_RESTART_RACE, 0);",
      "post(RC_RESTART_RACE, 1);"),
    M("dismiss-event-param", "    case END_GAME_MENU_STATE_RESTART_EVENT:" + NL
      + "        if (data->param == 0)",
      "    case END_GAME_MENU_STATE_RESTART_EVENT:" + NL
      + "        if (data->param != 1)"),
    M("dismiss-event-restart", "        race_event_restart();" + NL, ""),
    M("dismiss-event-post", "        race_event_restart();" + NL
      + "        post(RC_NEXT_RACE, 0);", "        race_event_restart();" + NL
      + "        post(RC_NEXT_RACE, 1);"),
    M("dismiss-next-param", "    case END_GAME_MENU_STATE_NEXT_RACE:" + NL
      + "        if (data->param == 0)",
      "    case END_GAME_MENU_STATE_NEXT_RACE:" + NL
      + "        if (data->param <= 0)"),
    M("dismiss-next-fell", "!race_event_status_fell()",
      "race_event_status_fell()"),
    M("dismiss-next-auto", "endgame_should_auto_save() && "
      "!race_event_status_fell()", "!race_event_status_fell()"),
    M("dismiss-next-cb", "set_autosave_completion_callback(next_race);",
      "set_autosave_completion_callback(quit_race);"),
    M("dismiss-default", "    default:" + NL + "        return;" + NL
      + "    }" + NL + "    set_screen_visibility",
      "    default:" + NL + "        break;" + NL + "    }" + NL
      + "    set_screen_visibility"),
    M("dismiss-show", "    set_screen_visibility(m->Base.ScreenHash, "
      "FLAILER_SCREEN_VISIBLE);" + NL + "}",
      "    set_screen_visibility(m->Base.ScreenHash, "
      "FLAILER_SCREEN_INVISIBLE);" + NL + "}"),

    # The bloom and the menu's HandleEvent.
    M("hl-tick", "if (msg == BMSG_SCREEN_TICK) {",
      "if (msg == BMSG_SCREEN_RENDER) {"),
    M("hl-highlight", "} else if (msg == BMSG_MENUITEM_HIGHLIGHT) {",
      "} else if (msg == BMSG_MENUITEM_SELECT) {"),
    M("hl-item", "banim_highlight_set_item(a, h, data->itemHash);",
      "banim_highlight_set_item(a, h, data->itemHash + 1);"),
    M("mh-hl", "    highlight_handle_message(&m->Highlight, msg, data);"
      + NL, ""),
    M("mh-select", "        if (it != NULL && (uint32_t)it->Kind < "
      "END_GAME_MENU_NUM_ITEMS)" + NL + "            select_item(m, it);",
      "        if (it != NULL && (uint32_t)it->Kind < "
      "END_GAME_MENU_NUM_ITEMS - 1)" + NL + "            select_item(m, it);"),
    M("mh-back-move", "            endgame_screens_move_back_screen(s);" + NL
      + "            if (endgame", "            if (endgame"),
    M("mh-back-push", "            if (endgame_screens_get_current_screen(s) "
      "!= was)" + NL + "                change_to_screen("
      "endgame_screens_get_current_screen(s), 0);",
      "            if (endgame_screens_get_current_screen(s) != was)" + NL
      + "                change_to_screen("
      "endgame_screens_get_current_screen(s), 1);"),
    M("mh-back-param", "        data->param = 0;" + NL + "        break;" + NL
      + "    case BMSG_POPUP_DISMISS:", "        break;" + NL
      + "    case BMSG_POPUP_DISMISS:"),
    M("mh-dismiss", "        popup_dismissed(m, data);" + NL, ""),
    M("menu-dtor-free", "        bFree(n);" + NL + "    }" + NL
      + "    endgame_menus_base_destroy(b, flags);", "    }" + NL
      + "    endgame_menus_base_destroy(b, flags);"),
    M("menu-dtor-base", "    endgame_menus_base_destroy(b, flags);" + NL
      + "}", "    if (flags & 1)" + NL + "        bFree(b);" + NL + "}"),
]

EQUIVALENT = {
    "current-head": "the list is never empty -- ShouldSeeEndGame is 1, so "
                    "the End Game Menu is always on it -- and CurrentScreen "
                    "is the head only on an empty list; retail would read "
                    "the head's word at +8 as the name then",
    "labels-ff": "retail's bMemSet of 0xff (0x001e1610) is there, but each "
                 "of the three branches writes all fifteen words after it",
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
        todo, SOURCES, "endgame_test",
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
