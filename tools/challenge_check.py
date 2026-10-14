#!/usr/bin/env python3
"""Cross-check 3DS Files/source/bsetup.c's Challenge screen against the
retail image, SLES_507.31.

**The model** is retail's own ChallengeScreen: ChallengeScreenCallback
(0x001b6bd0), the constructor (0x001b5e30) and destructor (0x001b6068),
HandleScreenCallback (0x001b6688) with its inline SELECT, OnPadLeftRight,
OnMenuitemHighlight, SetupHighlight, ResyncBlurb, ResyncChangeables,
MaybeChangeRaceType and the helpers round them (MaybeChangeNumPlayers,
ValueChanger, MaybeChangeOpponentSkillLevel, RefreshOpponentSkillLevel,
MakeJoystickArrowsRight, StartTheRightMovie, FlailerSetTopLeftY(int, int,
float)) -- and the arrows class with its tfeSineWave and the real bSin,
all run in retail_model.RetailEmu on retail's Fred (0x002fc050) and
TheRaceParameters (0x0031a898). The harness is tools/src/setup_test.c,
the one setup_check.py runs, driving bsetup_challenge_callback through
its cmsg op.

**The stubs** are setup_check.py's: the animation kit at its retail
addresses, the Flailer calls, IsJoystickPluggedIn, StartMovie,
SetHelpOverride and the three FrontendDatabase calls.

**The script** activates the screen from Freds with each race type and
others, one player, two and others, skills in and off the table, cops on
and off and You're The Cop set and not, with the second pad in and out
and the first out too; ticks it; highlights each item and one more;
scrolls every item both ways through every wrap; selects on each item
from both ports with one player and two, with each race type on Setup and
You're The Cop's; sends every other message with and without an exit
running; and unactivates it with and without one, and twice. Retail reads
two things unchecked the script stays off: SetupHighlight's box on an item
the screen does not have (the stack's), and a message with no instance.

    python tools/challenge_check.py
    python tools/challenge_check.py --mutate [--only a,b]
    python tools/challenge_check.py --dump out/challenge
"""
import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                        # noqa: E402
import physicscar_check as pcc          # noqa: E402
import setup_check as sc                # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = sc.ROOT
NL = sc.NL
GP = sc.GP
FRED = sc.FRED
RP = sc.RP

PINSTANCE = GP - 18788          # ChallengeScreen's pInstance
F_CALLBACK = 0x001b6bd0

SCREEN = 0x2d62cfe2
MENUITEM = [0] + [0x52e039f2 + i for i in range(1, 6)]
PLAYERS_VALUE = 0x164eb99a
RACE_VALUE = 0x15dd325e
SKILL_VALUE = 0x53a607f5
LEFT_ARROW = sc.LEFT_ARROW
RIGHT_ARROW = sc.RIGHT_ARROW
MI_MASK = [0, 0x6e34e350]
MI_UNDERSCORE = sc.MI_UNDERSCORE
OTHER = MENUITEM[5]             # MENUITEM_5: a mask, and no item

fbits = sc.fbits
obj = sc.obj


# ================================================================== script

def msg(m, item=0, port=0):
    return "cmsg|%d|%#x|%d" % (m, item, port)


TICK = msg(18)


def screen_objects():
    return [
        obj(MENUITEM[1], 1, (40, 84, 300, 106), 95, 40.0),
        obj(MENUITEM[2], 1, (40, 138, 300, 161), 149, 40.0),
        obj(MENUITEM[3], 1, (40, 192, 181, 215), 203, 40.0),
        obj(MENUITEM[4], 1, (40, 246, 160, 269), 257, 40.0),
        obj(PLAYERS_VALUE, 1, (441, 84, 583, 106), 95, 441.0),
        obj(RACE_VALUE, 1, (430, 138, 590, 161), 149, 430.0),
        obj(SKILL_VALUE, 1, (451, 192, 577, 215), 203, 451.0),
        obj(LEFT_ARROW, 2, (394, 86, 410, 102), 94, 394.0),
        obj(RIGHT_ARROW, 2, (610, 86, 626, 102), 94, 610.0),
        obj(MI_MASK[1], 2, (0, 80, 640, 110), 95, 21.5),
        obj(MI_UNDERSCORE, 2, (30, 100, 620, 104), 102, 30.25),
        obj(OTHER, 1, (-7, -3, 11, 1), -1, -2.0),
    ]


def activate(dcs, police=1, beacop=0, joy1=0, joy0=1):
    return ["dcs|%s" % dcs, "police|%d" % police, "beacop|%d" % beacop,
            "joy|0|%d" % joy0, "joy|1|%d" % joy1, msg(11, SCREEN), "cdump"]


def script():
    s = []
    s += screen_objects()
    s += ["elapsed|%#x" % sc.fbits(1.0 / 60)]

    # The defaults, one pad, cops on.
    s += activate("1|3|1|1|0")
    s += [TICK, "cdump"]
    for item in MENUITEM[1:]:
        s += [msg(4, item), "cdump", TICK, "cdump"]
    # Players with one pad: no change, silent.
    s += [msg(4, MENUITEM[1]), msg(7, MENUITEM[1]), msg(6, MENUITEM[1]),
          "cdump"]
    # The second pad: the arrows come back, and the count moves both ways.
    s += ["joy|1|1", TICK, "cdump"]
    for d in (7, 7, 6, 6, 7):
        s += [msg(d, MENUITEM[1]), "cdump"]
    # Two players, and the second pad goes: back to 1 on the next tick,
    # and the line with it.
    s += ["joy|1|0", TICK, "cdump", TICK, "cdump"]
    # Two players on another item, and the pad goes.
    s += ["joy|1|1", msg(7, MENUITEM[1]), msg(4, MENUITEM[2]), "cdump",
          "joy|1|0", TICK, "cdump", "joy|1|1"]
    # Race Type, right through the wrap and left through it.
    s += [msg(4, MENUITEM[2]), "cdump"]
    for d in (7, 7, 7, 7, 7, 6, 6, 6, 6, 6, 6):
        s += [msg(d, MENUITEM[2]), "cdump"]
    # Skill Level, both ways through both wraps, cops on and off.
    s += [msg(4, MENUITEM[3]), "cdump"]
    for d in (7, 7, 7, 6, 6, 6, 6):
        s += [msg(d, MENUITEM[3]), "cdump"]
    s += ["police|0", msg(7, MENUITEM[3]), "cdump", msg(4, MENUITEM[3]),
          "cdump"]
    # Free Run with the cops off grays Skill Level; on, it does not.
    s += [msg(4, MENUITEM[2])]
    for d in (6, 7, 6, 6):
        s += [msg(d, MENUITEM[2]), "cdump"]
    s += ["police|1", msg(7, MENUITEM[2]), msg(6, MENUITEM[2]), "cdump",
          "police|0"]
    # Setup and the item off the screen's switch: nothing changes.
    s += [msg(4, MENUITEM[4]), msg(7, MENUITEM[4]), msg(6, MENUITEM[4]),
          "cdump", msg(4, OTHER), "cdump", msg(7, OTHER), msg(6, OTHER),
          TICK, "cdump"]
    # Scrolls on an item that is not the current one: the line is the
    # scrolled item's.
    s += [msg(4, MENUITEM[1]), msg(7, MENUITEM[2]), "cdump",
          msg(6, MENUITEM[3]), "cdump"]
    # The first pad out.
    s += ["joy|0|0", msg(4, MENUITEM[1]), TICK, "cdump", "joy|0|1"]
    # The pulse, through a wrap.
    for e in (0.0137, 0.628, 0.6283, 1.0, -0.05):
        s += ["elapsed|%#x" % fbits(e), TICK, "cdump"]
    s += ["elapsed|%#x" % fbits(1.0 / 60)]
    # Messages with nothing to do, BACK among them.
    for m in (0, 2, 3, 5, 8, 9, 10, 13, 14, 15, 16, 17, 19, 24):
        s += [msg(m, MENUITEM[1])]
    s += ["cdump"]
    # SELECT with two players, from the second pad, on Race Type.
    s += ["joy|1|1", msg(4, MENUITEM[1]), msg(7, MENUITEM[1]),
          msg(1, MENUITEM[2], 1), "cdump"]
    # An exit runs: everything goes to it, and TICK to the screen first.
    for m in (18, 1, 4, 6, 7, 8, 9, 17, 24, 18):
        s += [msg(m, MENUITEM[1])]
    s += ["cdump", msg(12, SCREEN), "cdump", msg(12, SCREEN), "cdump"]

    # Cops off, a Fred with two players and one pad.
    s += activate("2|4|0|2|1", police=0)
    # One player from the second pad: refused. From the first: car select.
    s += [msg(1, MENUITEM[1], 1), "cdump", msg(1, MENUITEM[1], 0), "cdump",
          TICK, "cdump", msg(12, SCREEN), "cdump"]

    # Setup with each race type, You're The Cop's, and two off the table.
    for mode in (3, 4, 5, 6, 7, 2, 9):
        s += activate("1|%d|1|1|0" % mode)
        s += [msg(4, MENUITEM[4]), msg(1, MENUITEM[4], 0), "cdump",
              msg(12, SCREEN), "cdump"]
    s += activate("2|5|1|0|2", beacop=1, joy1=1)
    s += [msg(4, MENUITEM[4]), msg(1, MENUITEM[4], 1), "cdump",
          msg(12, SCREEN), "cdump"]

    # Two players, both pads: every item from both ports, and items off it.
    for item, port in ((MENUITEM[1], 1), (MENUITEM[2], 0), (MENUITEM[3], 1),
                       (OTHER, 0), (0, 0), (MENUITEM[1] - 1, 1),
                       (0xffffffff, 0)):
        s += activate("2|3|5|1|2", joy1=1)
        s += [msg(4, MENUITEM[2]), msg(1, item, port), "cdump",
              msg(12, SCREEN), "cdump"]

    # You're The Cop set: no race type found, and Race Type does not move.
    s += activate("1|6|1|2|1", beacop=1)
    s += [msg(4, MENUITEM[2]), msg(7, MENUITEM[2]), msg(6, MENUITEM[2]),
          "cdump", msg(1, MENUITEM[2], 0), "cdump", msg(12, SCREEN),
          "cdump", "beacop|0"]

    # You're The Cop cleared under the screen: the index is still -1,
    # so right asks for the race type already set -- no change -- and
    # left for Free Run.
    s += activate("1|3|1|1|0", beacop=1)
    s += ["beacop|0", msg(4, MENUITEM[2]), msg(7, MENUITEM[2]), "cdump",
          msg(6, MENUITEM[2]), "cdump", msg(12, SCREEN)]

    # A race type off the table: the index is -1, so right is the first
    # and left the last.
    for mode in (7, 0):
        for d in (7, 6):
            s += activate("1|%d|1|0|0" % mode)
            s += [msg(4, MENUITEM[2]), msg(d, MENUITEM[2]), "cdump",
                  msg(d, MENUITEM[2]), "cdump", msg(12, SCREEN)]

    # Three players, none, and fewer; a skill off the table.
    s += activate("3|3|1|3|0", joy1=1)
    s += [msg(4, MENUITEM[1]), msg(4, MENUITEM[3]), "cdump",
          msg(1, MENUITEM[1], 1), "cdump", msg(7, MENUITEM[3]), "cdump",
          msg(12, SCREEN), "cdump"]
    s += activate("1|3|1|3|0", police=0)
    s += [msg(4, MENUITEM[3]), "cdump", msg(12, SCREEN)]
    s += activate("0|3|1|3|0", joy1=1)
    s += [msg(4, MENUITEM[1]), msg(6, MENUITEM[1]), "cdump",
          msg(4, MENUITEM[3]), msg(6, MENUITEM[3]), "cdump",
          msg(12, SCREEN)]
    s += activate("-4|3|1|1|0")
    s += [msg(4, MENUITEM[1]), msg(7, MENUITEM[1]), "cdump",
          msg(12, SCREEN)]
    # The first pad out from the start.
    s += activate("2|3|1|1|2", joy0=0, joy1=1)
    s += [msg(4, MENUITEM[1]), TICK, "cdump", msg(1, MENUITEM[1], 0),
          "cdump", msg(12, SCREEN), "cdump"]
    # Another screen's hash in the ACTIVATE: everything is on it.
    s += ["joy|0|1", "joy|1|0", msg(11, 0x0badf00d), msg(4, MENUITEM[1]),
          TICK, "cdump", msg(1, MENUITEM[4], 0), "cdump",
          msg(12, 0x0badf00d), "cdump"]

    # BACK after changes and no SELECT: only the destructor hands Fred the
    # settings and the count, over whatever Fred had; the game type stays.
    s += activate("1|3|1|1|0", joy1=1)
    s += [msg(4, MENUITEM[1]), msg(7, MENUITEM[1]), msg(4, MENUITEM[2]),
          msg(7, MENUITEM[2]), msg(4, MENUITEM[3]), msg(7, MENUITEM[3]),
          "type|9", "cars|5", "cdump", msg(17, MENUITEM[3]), "cdump",
          msg(12, SCREEN), "cdump"]

    # No arrows on the screen, then only the right one.
    s += [obj(LEFT_ARROW, 0), obj(RIGHT_ARROW, 0)]
    s += activate("1|3|1|1|0", joy1=1)
    s += [msg(4, MENUITEM[1]), TICK, "cdump", msg(12, SCREEN)]
    s += [obj(RIGHT_ARROW, 2, (610, 86, 626, 102), 94, 610.0),
          obj(LEFT_ARROW, 1, (394, 86, 410, 102), 94, 394.0)]
    s += activate("1|3|1|1|0", joy1=1)
    s += [msg(4, MENUITEM[2]), TICK, "cdump", msg(12, SCREEN)]
    # A value object that is not there, and brackets off the box's edges.
    s += [obj(RACE_VALUE, 0), obj(MENUITEM[2], 1, (5, -40, 9, -2), -21),
          obj(MI_UNDERSCORE, 0), obj(MI_MASK[1], 0)]
    s += activate("1|3|1|1|0")
    s += [msg(4, MENUITEM[1]), msg(4, MENUITEM[2]), msg(7, MENUITEM[2]),
          TICK, "cdump", msg(1, MENUITEM[2], 0), "cdump",
          msg(12, SCREEN), "cdump"]
    return s


# =================================================================== model

class Model(sc.Model):
    def __init__(self):
        sc.Model.__init__(self)
        e = self.e
        e.put32(PINSTANCE, 0)
        e.put32(FRED + 28, 0)

    def cdump(self):
        g = self.e.u32
        b = g(PINSTANCE)
        if not b:
            self.emit("  inst 0")
        else:
            self.emit("  inst 1 cur %08x data %d %d %d %d %d gti %d exit %d"
                      % ((g(b + 28),)
                         + tuple(s32(g(b + 4 * i)) for i in range(5))
                         + (s32(g(b + 24)), 1 if g(b + 684) else 0)))
            a = b + 688
            self.emit("  arrows %d %d %08x wave %08x %08x %08x %08x" % (
                1 if g(a + 4) else 0, 1 if g(a + 8) else 0, g(a + 12),
                g(a + 16), g(a + 20), g(a + 24), g(a + 28)))
        self.emit("  fred dcs %d %d %d %d %d type %d cars %d" % (
            tuple(s32(g(FRED + 8 + 4 * i)) for i in range(5))
            + (s32(g(FRED + 0x1072c)), s32(g(FRED + 0x10734)))))
        self.emit("  rp %d %d" % (s32(g(RP + 48)), s32(g(RP + 596))))

    def op(self, a):
        e = self.e
        o = a[0]
        n = [int(x, 0) for x in a[1:]]
        if o == "beacop":
            e.put32(FRED + 28, n[0] & M32)
        elif o == "cmsg":
            d = self.data
            e.put32(d, n[1] & M32)
            e.put32(d + 4, n[2] & M32)
            e.put32(d + 8, 0x5a)
            e.put32(d + 12, 0x5b)
            e.call(F_CALLBACK, n[0], d, limit=2000000)
            self.emit("  data %d %d" % (s32(e.u32(d + 8)),
                                        s32(e.u32(d + 12))))
        elif o == "cdump":
            self.cdump()
        else:
            sc.Model.op(self, a)


def model(lines):
    return Model().run(lines)


# ============================================================= mutations

S = sc.BSETUP
H = "3DS Files/source/bsetup.h"
MUTATIONS = [
    # The tables.
    ("masks-four", S, "bsel_add_items(a, &c->sel, kChallengeMasks, 5);",
     "bsel_add_items(a, &c->sel, kChallengeMasks, 4);"),
    ("types-order", S, "FRED_CHALLENGE_GAME_SINGLE_RACE, "
     "FRED_CHALLENGE_GAME_KNOCKOUT," + NL + "    FRED_CHALLENGE_GAME_LAP_"
     "KNOCKOUT, FRED_CHALLENGE_GAME_FREE_RUN,",
     "FRED_CHALLENGE_GAME_SINGLE_RACE, FRED_CHALLENGE_GAME_LAP_KNOCKOUT,"
     + NL + "    FRED_CHALLENGE_GAME_KNOCKOUT, FRED_CHALLENGE_GAME_FREE_RUN,"),
    ("race-value", H, "#define BSETUP_OBJ_RACE_TYPE_VALUE   0x15dd325eu",
     "#define BSETUP_OBJ_RACE_TYPE_VALUE   0x15dd325fu"),
    ("beacop-offset", H, "#define FRED_MAIN_MENU_BEACOP   28",
     "#define FRED_MAIN_MENU_BEACOP   24"),
    ("free-run-type", H, "#define FRED_CHALLENGE_GAME_FREE_RUN      6",
     "#define FRED_CHALLENGE_GAME_FREE_RUN      8"),

    # ResyncChangeables.
    ("resync-sr", S, "case FRED_CHALLENGE_GAME_SINGLE_RACE: id = 20005;",
     "case FRED_CHALLENGE_GAME_SINGLE_RACE: id = 20006;"),
    ("resync-ko", S, "case FRED_CHALLENGE_GAME_KNOCKOUT: id = 20007;",
     "case FRED_CHALLENGE_GAME_KNOCKOUT: id = 20008;"),
    ("resync-lko", S, "case FRED_CHALLENGE_GAME_LAP_KNOCKOUT: id = 20008;",
     "case FRED_CHALLENGE_GAME_LAP_KNOCKOUT: id = 20007;"),
    ("resync-fr", S, "case FRED_CHALLENGE_GAME_FREE_RUN: id = 20006;",
     "case FRED_CHALLENGE_GAME_FREE_RUN: id = 20005;"),
    ("resync-race-object", S, "HOOK(s, setLanguageID, c->screen, "
     "BSETUP_OBJ_RACE_TYPE_VALUE, id);", "HOOK(s, setLanguageID, c->screen, "
     "BSETUP_OBJ_PLAYERS_VALUE, id);"),
    ("resync-1p", S, "        HOOK(s, setLanguageID, c->screen, "
     "BSETUP_OBJ_PLAYERS_VALUE, 20003);" + NL + "    else if",
     "        HOOK(s, setLanguageID, c->screen, BSETUP_OBJ_PLAYERS_VALUE, "
     "20004);" + NL + "    else if"),
    ("resync-2p-else", S, "    else if (c->data.numPlayers == 2)" + NL
     + "        HOOK(s, setLanguageID, c->screen, BSETUP_OBJ_PLAYERS_VALUE, "
     "20004);", "    else" + NL + "        HOOK(s, setLanguageID, c->screen, "
     "BSETUP_OBJ_PLAYERS_VALUE, 20004);"),
    ("resync-skill-field", S, "refreshOpponentSkillLevel(s, c->screen, "
     "c->data.skillLevel,", "refreshOpponentSkillLevel(s, c->screen, "
     "c->data.beACopSkill,"),
    ("resync-gray-mode", S, "    if (c->data.challengeMode == "
     "FRED_CHALLENGE_GAME_FREE_RUN" + NL + "        && !s->gf->copsOn) {",
     "    if (c->data.challengeMode == FRED_CHALLENGE_GAME_FREE_RUN) {"),
    ("resync-gray-cops", S, "        && !s->gf->copsOn) {",
     "        && s->gf->copsOn) {"),
    ("resync-gray-hide", S, "ITEM_CHAL_SKILL, BSCR_GRAY_DISABLE);",
     "ITEM_CHAL_SKILL, BSCR_GRAY_HIDE);"),
    ("resync-gray-vis", S, "        HOOK(s, setVisible, c->screen, "
     "BSETUP_OBJ_SKILL_VALUE, 0);" + NL + "    } else {",
     "        HOOK(s, setVisible, c->screen, BSETUP_OBJ_SKILL_VALUE, 1);"
     + NL + "    } else {"),
    ("resync-ungray", S, "ITEM_CHAL_SKILL, BSCR_GRAY_ENABLE);",
     "ITEM_CHAL_SKILL, BSCR_GRAY_DISABLE);"),

    # ResyncBlurb.
    ("blurb-1p", S, "if (c->data.numPlayers == 1) id = 19000;",
     "if (c->data.numPlayers == 1) id = 19001;"),
    ("blurb-2p-else", S, "else if (c->data.numPlayers == 2) id = 19001;",
     "else id = 19001;"),
    ("blurb-sr", S, "case FRED_CHALLENGE_GAME_SINGLE_RACE: id = 20010;",
     "case FRED_CHALLENGE_GAME_SINGLE_RACE: id = 20011;"),
    ("blurb-ko", S, "case FRED_CHALLENGE_GAME_KNOCKOUT: id = 20013;",
     "case FRED_CHALLENGE_GAME_KNOCKOUT: id = 20012;"),
    ("blurb-lko", S, "case FRED_CHALLENGE_GAME_LAP_KNOCKOUT: id = 20012;",
     "case FRED_CHALLENGE_GAME_LAP_KNOCKOUT: id = 20013;"),
    ("blurb-fr", S, "case FRED_CHALLENGE_GAME_FREE_RUN: id = 20011;",
     "case FRED_CHALLENGE_GAME_FREE_RUN: id = 20010;"),
    ("blurb-cops", S, "            if (s->gf->copsOn) {" + NL
     + "                if (c->data.skillLevel == 0) id = 19006;",
     "            if (!s->gf->copsOn) {" + NL
     + "                if (c->data.skillLevel == 0) id = 19006;"),
    ("blurb-cops-1", S, "else if (c->data.skillLevel == 1) id = 19007;",
     "else if (c->data.skillLevel == 1) id = 19008;"),
    ("blurb-cops-else", S, "else if (c->data.skillLevel == 2) id = 19008;",
     "else id = 19008;"),
    ("blurb-racers-0", S, "if (c->data.skillLevel == 0) id = 19002;",
     "if (c->data.skillLevel == 0) id = 19003;"),
    ("blurb-racers-else", S, "else if (c->data.skillLevel == 2) id = 19004;",
     "else id = 19004;"),
    ("blurb-skill-field", S, "if (c->data.skillLevel == 0) id = 19006;",
     "if (c->data.beACopSkill == 0) id = 19006;"),
    ("blurb-setup", S, "        case ITEM_CHAL_SETUP:" + NL
     + "            id = 19005;", "        case ITEM_CHAL_SETUP:" + NL
     + "            id = 19004;"),

    # MaybeChangeRaceType.
    ("rt-no-beacop", S, "    if (fredGet(s, FRED_MAIN_MENU_BEACOP)) return 0;"
     + NL + "    if (!(-1 < idx)) idx = 3;", "    if (!(-1 < idx)) idx = 3;"),
    ("rt-low-wrap", S, "if (!(-1 < idx)) idx = 3;", "if (!(-1 < idx)) idx = 0;"),
    ("rt-low-le", S, "if (!(-1 < idx)) idx = 3;", "if (!(0 < idx)) idx = 3;"),
    ("rt-high-wrap", S, "if (!(idx < 4)) idx = 0;", "if (!(idx < 4)) idx = 3;"),
    ("rt-same", S, "if (mode == c->data.challengeMode) return 0;",
     "if (0) return 0;"),
    ("rt-no-index", S, "    c->gameTypeIndex      = idx;" + NL, ""),
    ("rt-no-resync", S, "    c->data.challengeMode = mode;" + NL
     + "    challengeResync(s, c);" + NL + "    return 1;",
     "    c->data.challengeMode = mode;" + NL + "    return 1;"),

    # The constructor.
    ("ctor-bar", S, "&c->blurb, screen, BSCR_OBJ_SCROLLING_TEXT," + NL
     + "                     BSCR_OBJ_SCROLLING_TEXT, BSCR_OBJ_WHITEOUT_BAR);",
     "&c->blurb, screen, BSCR_OBJ_SCROLLING_TEXT," + NL
     + "                     BSCR_OBJ_SCROLLING_TEXT, BSCR_OBJ_SCROLLING_TEXT);"),
    ("ctor-hl-swap", S, "banim_highlight_init(a, &c->highlight, screen, "
     "0xab671c9au,", "banim_highlight_init(a, &c->highlight, screen, "
     "0x1042eac3u,"),
    ("ctor-load-late", S, "    c->screen = screen;" + NL
     + "    bsel_set_indicator_mode(&c->sel, 1);" + NL
     + "    bsel_add_items(a, &c->sel, kChallengeMasks, 5);" + NL
     + "    if (s->gf->fred) bsetup_challenge_load(&c->data, s->gf->fred);"
     + NL + "    else bsetup_challenge_defaults(&c->data);",
     "    c->screen = screen;" + NL
     + "    if (s->gf->fred) bsetup_challenge_load(&c->data, s->gf->fred);"
     + NL + "    else bsetup_challenge_defaults(&c->data);" + NL
     + "    bsel_set_indicator_mode(&c->sel, 1);" + NL
     + "    bsel_add_items(a, &c->sel, kChallengeMasks, 5);"),
    ("ctor-index-0", S, "    c->gameTypeIndex = -1;", "    c->gameTypeIndex = 0;"),
    ("ctor-index-beacop", S, "    if (!fredGet(s, FRED_MAIN_MENU_BEACOP))" + NL
     + "        for (i = 0; i < 4; i++)", "        for (i = 0; i < 4; i++)"),
    ("ctor-no-mjar", S, "    makeJoystickArrowsRight(s, &c->data, &c->arrows);"
     + NL + "    challengeResync(s, c);" + NL + "    startTheRightMovie(s);",
     "    challengeResync(s, c);" + NL + "    startTheRightMovie(s);"),
    ("ctor-help-always", S, "HOOK(s, setHelpOverride, s->gf->copsOn ? "
     "kBeACopHelp : NULL);", "HOOK(s, setHelpOverride, kBeACopHelp);"),
    ("ctor-no-fred", S, "    fredSetGame(s, c->data.challengeMode, "
     "c->data.numPlayers);" + NL, ""),
    ("ctor-fred-swap", S, "fredSetGame(s, c->data.challengeMode, "
     "c->data.numPlayers);", "fredSetGame(s, c->data.numPlayers, "
     "c->data.challengeMode);"),
    ("ctor-no-preload", S, "    HOOK0(s, preloadCars);" + NL
     + "    c->live = 1;", "    c->live = 1;"),

    # The destructor.
    ("dtor-exit-kept", S, "    if (c->exitActive) banim_slide_release(a, "
     "&c->exit.slide);" + NL + "    HOOK0(s, makeChallengeCarsAvailable);",
     "    HOOK0(s, makeChallengeCarsAvailable);"),
    ("dtor-no-cars", S, "    if (c->exitActive) banim_slide_release(a, "
     "&c->exit.slide);" + NL + "    HOOK0(s, makeChallengeCarsAvailable);",
     "    if (c->exitActive) banim_slide_release(a, &c->exit.slide);"),
    ("dtor-no-count", S, "        put32(fred + FRED_NUM_PLAYER_CARS, "
     "c->data.numPlayers);" + NL, ""),
    ("dtor-no-save", S, "        bsetup_challenge_save(&c->data, fred);"
     + NL + "    }", "    }"),
    ("dtor-game-type", S, "        put32(fred + FRED_NUM_PLAYER_CARS, "
     "c->data.numPlayers);" + NL, "        fredSetGame(s, "
     "c->data.challengeMode, c->data.numPlayers);" + NL),
    ("dtor-help-kept", S, "    HOOK(s, setHelpOverride, NULL);" + NL
     + "    banim_slide_release(a, &c->slideIn);" + NL
     + "    banim_blurb_release(a, &c->blurb);" + NL
     + "    memset(c, 0, sizeof(*c));",
     "    banim_slide_release(a, &c->slideIn);" + NL
     + "    banim_blurb_release(a, &c->blurb);" + NL
     + "    memset(c, 0, sizeof(*c));"),

    # The tick.
    ("tick-no-hl2", S, "    banim_highlight_animate(a, &c->change);" + NL
     + "    banim_blurb_animate(a, &c->blurb);" + NL + NL
     + "    if (c->current == ITEM_PLAYERS) {",
     "    banim_blurb_animate(a, &c->blurb);" + NL + NL
     + "    if (c->current == ITEM_PLAYERS) {"),
    ("tick-1-or", S, "            barrows_set(s, &c->arrows, "
     "BSETUP_OBJ_PLAYERS_VALUE);" + NL + "        } else {",
     "            barrows_set(s, &c->arrows, 0);" + NL + "        } else {"),
    ("tick-1-no-blurb", S, "                challengeResync(s, c);" + NL
     + "                challengeBlurb(s, c, ITEM_PLAYERS);",
     "                challengeResync(s, c);"),
    ("tick-1-return", S, "            barrows_set(s, &c->arrows, "
     "BSETUP_OBJ_PLAYERS_VALUE);" + NL + "        } else {",
     "            barrows_set(s, &c->arrows, BSETUP_OBJ_PLAYERS_VALUE);"
     + NL + "            return;" + NL + "        } else {"),
    ("tick-all-skip", S, "    if (joystickPluggedIn(s, 0) && "
     "joystickPluggedIn(s, 1)) return;" + NL + "    maybeChangeNumPlayers"
     "(s, &c->data, 1);" + NL + "    challengeResync(s, c);" + NL + "}",
     "}"),
    ("tick-all-if", S, "    maybeChangeNumPlayers(s, &c->data, 1);" + NL
     + "    challengeResync(s, c);" + NL + "}",
     "    if (maybeChangeNumPlayers(s, &c->data, 1))" + NL
     + "        challengeResync(s, c);" + NL + "}"),

    # OnMenuitemHighlight.
    ("hl-under", S, "    HOOK(s, setTopLeftY, c->screen, BSCR_OBJ_MI_UNDERSCORE,"
     + NL + "         (int32_t)((float)box[3] + -3.0f));",
     "    HOOK(s, setTopLeftY, c->screen, BSCR_OBJ_MI_UNDERSCORE," + NL
     + "         (int32_t)((float)box[3] + -2.0f));"),
    ("hl-over", S, "    HOOK(s, setTopLeftY, c->screen, BSCR_OBJ_MI_OVERSCORE,"
     + NL + "         (int32_t)((float)box[1] - 6.0f));",
     "    HOOK(s, setTopLeftY, c->screen, BSCR_OBJ_MI_OVERSCORE," + NL
     + "         (int32_t)((float)box[0] - 6.0f));"),
    ("hl-blurb-first", S, "    banim_highlight_set_item(a, &c->highlight, "
     "item);" + NL + "    c->current = item;" + NL
     + "    challengeBlurb(s, c, item);",
     "    challengeBlurb(s, c, item);" + NL
     + "    banim_highlight_set_item(a, &c->highlight, item);" + NL
     + "    c->current = item;"),
    ("hl-no-mjar", S, "            makeJoystickArrowsRight(s, &c->data, "
     "&c->arrows);" + NL + "            bsel_set_current(a, &c->sel, "
     "BSCR_MI_MASK(1));", "            bsel_set_current(a, &c->sel, "
     "BSCR_MI_MASK(1));"),
    ("hl-race-mask", S, "bsel_set_current(a, &c->sel, BSCR_MI_MASK(2));",
     "bsel_set_current(a, &c->sel, BSCR_MI_MASK(3));"),
    ("hl-race-arrows", S, "            barrows_set(s, &c->arrows, "
     "BSETUP_OBJ_RACE_TYPE_VALUE);", "            barrows_set(s, &c->arrows, "
     "0);"),
    ("hl-setup-mask", S, "bsel_set_current(a, &c->sel, BSCR_MI_MASK(4));",
     "bsel_set_current(a, &c->sel, BSCR_MI_MASK(3));"),

    # OnPadLeftRight.
    ("lr-dir", S, "    int32_t  dir     = msg == BMSG_MENUITEM_PAD_LEFT ? -1 : 1;"
     + NL + "    int      changed = 0;" + NL + "    uint32_t object  = 0;" + NL
     + NL + "    switch (data->itemHash) {",
     "    int32_t  dir     = msg == BMSG_MENUITEM_PAD_LEFT ? 1 : -1;"
     + NL + "    int      changed = 0;" + NL + "    uint32_t object  = 0;" + NL
     + NL + "    switch (data->itemHash) {"),
    ("lr-race-index", S, "maybeChangeRaceType(s, c, c->gameTypeIndex + dir);",
     "maybeChangeRaceType(s, c, c->data.challengeMode - 3 + dir);"),
    ("lr-race-object", S, "            object  = BSETUP_OBJ_RACE_TYPE_VALUE;",
     "            object  = 0;"),
    ("lr-skill-field", S, "maybeChangeOpponentSkillLevel(dir, "
     "&c->data.skillLevel);", "maybeChangeOpponentSkillLevel(dir, "
     "&c->data.beACopSkill);"),
    ("lr-noise-kept", S, "    if (!changed) {" + NL + "        data->noise = 0;"
     + NL + "        return;" + NL + "    }" + NL
     + "    if (msg == BMSG_MENUITEM_PAD_LEFT) data->noise = BSND_MENU_LEFT;"
     + NL + "    else if (msg == BMSG_MENUITEM_PAD_RIGHT) data->noise = "
     "BSND_MENU_RIGHT;" + NL + "    banim_highlight_set_item(clock(s), "
     "&c->change, object);",
     "    if (!changed) {" + NL + "        return;" + NL + "    }" + NL
     + "    if (msg == BMSG_MENUITEM_PAD_LEFT) data->noise = BSND_MENU_LEFT;"
     + NL + "    else if (msg == BMSG_MENUITEM_PAD_RIGHT) data->noise = "
     "BSND_MENU_RIGHT;" + NL + "    banim_highlight_set_item(clock(s), "
     "&c->change, object);"),
    ("lr-no-resync", S, "&c->change, object);" + NL
     + "    challengeResync(s, c);" + NL + "    challengeBlurb(s, c, "
     "data->itemHash);", "&c->change, object);" + NL
     + "    challengeBlurb(s, c, data->itemHash);"),
    ("lr-blurb-current", S, "    challengeResync(s, c);" + NL
     + "    challengeBlurb(s, c, data->itemHash);" + NL + "}" + NL + NL
     + "// SELECT (0x001b682c",
     "    challengeResync(s, c);" + NL
     + "    challengeBlurb(s, c, c->current);" + NL + "}" + NL + NL
     + "// SELECT (0x001b682c"),

    # SELECT.
    ("sel-any-port", S, "    if (!((c->data.numPlayers == 1 && data->port == 0)",
     "    if (!((c->data.numPlayers == 1)"),
    ("sel-no-save", S, "    if (s->gf->fred) bsetup_challenge_save(&c->data, "
     "s->gf->fred);" + NL + "    numPlayers = c->data.numPlayers;",
     "    numPlayers = c->data.numPlayers;"),
    ("sel-beacop", S, "                     ? FRED_CHALLENGE_GAME_BE_A_COP" + NL
     + "                     : c->data.challengeMode;",
     "                     ? c->data.challengeMode" + NL
     + "                     : c->data.challengeMode;"),
    ("sel-rp-mode", S, "HOOK(s, setRaceParameters, numPlayers, "
     "c->data.raceMode);", "HOOK(s, setRaceParameters, numPlayers, "
     "c->data.challengeMode);"),
    ("sel-sr", S, 'target = "Single Race Setup";',
     'target = "Free Run Setup";'),
    ("sel-ko", S, 'target = "Knockout Setup"; break;',
     'target = "Lap Knockout Setup"; break;'),
    ("sel-lko", S, 'target = "Lap Knockout Setup";' + NL,
     'target = "Knockout Setup";' + NL),
    ("sel-fr", S, 'case FRED_CHALLENGE_GAME_FREE_RUN: target = "Free Run '
     'Setup"; break;', 'case FRED_CHALLENGE_GAME_FREE_RUN: target = '
     '"Single Race Setup"; break;'),
    ("sel-btc", S, '                target = "Be The Cop Setup";' + NL
     + "                break;" + NL + "            default: break;",
     '                target = "Single Race Setup";' + NL
     + "                break;" + NL + "            default: break;"),
    ("sel-setup-rp", S, "            default: break;" + NL + "        }" + NL
     + "    } else {", "            default: break;" + NL + "        }" + NL
     + "        HOOK0(s, setupRaceParametersAfterRaceSetup);" + NL
     + "    } else {"),
    ("sel-car-1p", S, '        target = numPlayers == 2 ? "Select Car2P" : '
     '"Select Car";' + NL + "        HOOK0(s, setupRaceParametersAfterRace"
     "Setup);", '        target = numPlayers == 2 ? "Select Car" : '
     '"Select Car2P";' + NL + "        HOOK0(s, setupRaceParametersAfter"
     "RaceSetup);"),
    ("sel-no-rp", S, '"Select Car";' + NL
     + "        HOOK0(s, setupRaceParametersAfterRaceSetup);" + NL + "    }",
     '"Select Car";' + NL + "    }"),
    ("sel-exit-off", S, "    c->exitActive = 1;", "    c->exitActive = 0;"),
    ("sel-group-dur", S, "BANIM_OFFSCREEN_X, c->exit.slide.totalTime);",
     "BANIM_OFFSCREEN_X, 0.5f);"),

    # HandleScreenCallback and the callback.
    ("ev-arrows-tick", S, "    barrows_event(s, &c->arrows, msg);" + NL
     + "    if (msg == BMSG_SCREEN_TICK) challengeTick(s, c);",
     "    if (msg == BMSG_SCREEN_TICK) challengeTick(s, c);" + NL
     + "    barrows_event(s, &c->arrows, msg);"),
    ("ev-tick-not-exiting", S, "    if (msg == BMSG_SCREEN_TICK) "
     "challengeTick(s, c);", "    if (msg == BMSG_SCREEN_TICK && "
     "!c->exitActive) challengeTick(s, c);"),
    ("ev-exit-falls", S, "            data->noise = noise;" + NL
     + "        }" + NL + "        return;" + NL + "    }" + NL
     + "    if (!data) return;" + NL + "    switch (msg) {" + NL
     + "        case BMSG_MENUITEM_HIGHLIGHT:" + NL
     + "            challengeHighlight(",
     "            data->noise = noise;" + NL
     + "        }" + NL + "    }" + NL
     + "    if (!data) return;" + NL + "    switch (msg) {" + NL
     + "        case BMSG_MENUITEM_HIGHLIGHT:" + NL
     + "            challengeHighlight("),
    ("cb-screen", S, "challengeCtor(s, data ? data->itemHash : "
     "BSETUP_SCREEN_CHALLENGE);", "challengeCtor(s, BSETUP_SCREEN_CHALLENGE);"),
]

EQUIVALENT = {
    "ctor-load-late": "SelectionSet's indicator mode and AddItems read "
                      "neither the screen's data nor Fred, so the copy "
                      "either side of them shows nowhere",
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    lines = script()
    base = model(lines)
    caught, survived, missing, equivalent = 0, [], [], []
    indir = tempfile.TemporaryDirectory()
    scp = sc.write_script(indir.name, lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = sc.build_harness(tmp, name="challenge_test")
        out = Path(tmp) / "base.txt"
        sc.run_harness(exe, scp, out)
        if sc.diff(base, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for m in todo:
        name, rel, before, after = m
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if text.count(probe) != 1:
            missing.append(name)
            print("  %-44s PATTERN %s" % (
                name, "NOT FOUND" if not text.count(probe) else "NOT UNIQUE"))
            continue
        new = text.replace(probe, repl, 1)
        try:
            hostbuild.write_source(path, new)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = sc.build_harness(tmp, name="challenge_test")
                except SystemExit:
                    print("  %-44s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = sc.run_harness(exe, scp, out)
                if rc == pcc.HARNESS_HUNG:
                    print("  %-44s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-44s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = sc.diff(base, out.read_text().splitlines(), quiet=True)
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
    indir.cleanup()

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

    lines = script()
    got = model(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = sc.build_harness(tmp, name="challenge_test")
        scp = sc.write_script(tmp, lines)
        out = Path(tmp) / "harness.txt"
        rc = sc.run_harness(exe, scp, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(got) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = sc.diff(got, harness)
    print("%d ops, %d lines, %d differ" % (len(lines), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
