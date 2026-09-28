#!/usr/bin/env python3
r"""Cross-check the three frontend screens against a second implementation.

`3DS Files/source/bscreens.c` is the port of the three screens the main menu
leads to -- `CopsOnModeSelect` (0x00203d28), `CopsOffModeSelect` (0x002043d0)
and `tOptionsScreen` (0x001e09d0) on `OptionsScreenBase` (0x001e53d0). This
file is those three written again, in Python, from
`docs/formats/frontend-screens.md` and the disassembly it cites rather than
from the C. Both run the same scenarios and print the same transcript; the
diff is the test.

The screen-list scaffolding underneath -- `ChangeToScreen`, the stack, the
message pump -- is not written twice: `tools/bootflow_check.py` already
proved that half, and this imports its `Flow` and adds three screens to the
registry. What is written twice is everything new: which item does what, when
the exit animation is over, and what `StartQuickRace` fills in.

What this does NOT check is layout: whether `MI_3_MASK` really is the box
around the third label is a question about `FRONTB.BUN`, and
`tools/flailer_dump.py` answers it.

Usage:
    python tools/bscreens_check.py
    python tools/bscreens_check.py --scenario copson_quick
    python tools/bscreens_check.py --dump out.txt
"""
import argparse
import difflib
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                                    # noqa: E402
import bootflow_check as bf                         # noqa: E402
import banim_check as ba                            # noqa: E402

SOURCES = ["tools/src/bscreens_test.c",
           "3DS Files/source/bscreens.c",
           "3DS Files/source/gameflow.c",
           "3DS Files/source/banim.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c"]

SIXTIETH = 1.0 / 60.0

# The two ScreenMessages these screens turn on that the boot flow never saw,
# so bootflow_check.py has no name for them.
MENUITEM_HIGHLIGHT = 4
MENUITEM_UNHIGHLIGHT = 5

COPS_ON = 0x5b35f533
COPS_OFF = 0x033e7771
OPTIONS = 0x95ad096b


def item(n):
    """bStringHash("MENUITEM_n")."""
    return (0x52e039f2 + n) & 0xffffffff


def mask(n):
    """bStringHash("MI_n_MASK") -- 33**5 apart, one character moving."""
    return (0x6e34e350 + (n - 1) * 39135393) & 0xffffffff


# UnderscoreOffset / OverscoreOffset as each of the two SetupHighlights uses
# them. The Mode Selects drop the underscore three pixels below the box; the
# Options screen sits it right on the edge.
UNDER_MODE, OVER_MODE = -3.0, -6.0
UNDER_OPT, OVER_OPT = 0.0, -6.0

# How long each screen takes to leave is no longer a number in this file.
# tSlideOutAnimation asks the bundle which MENUITEM_i_GROUPs the screen
# defines and takes the longest of their durations, so 0.25 / 0.20 / 0.40
# now fall out of AUTHORED_ITEMS below. If those three seconds ever stop
# appearing in the transcript, either the bundle model or the kit is wrong,
# and the diff says which.
AUTHORED_ITEMS = {COPS_ON: 4, COPS_OFF: 3, OPTIONS: 7}

BLOOM_TEXT = 0xab671c9a
BLOOM_TEXT_2 = 0x1042eac3
SCROLLING_TEXT = 0x75980cf0
WHITEOUT_BAR = 0x70a404ec
MI_UNDERSCORE = 0x32c91dae
MI_OVERSCORE = 0xc671680c
UNDERSCORE_GROUP = 0x97bf4b25

MODE_MASKS = [mask(n) for n in range(1, 6)]
OPTION_MASKS = [mask(n) for n in range(1, 9)]


class Bundle(ba.World):
    """FRONTB.BUN as far as the animation kit can see it.

    The same objects tools/src/bscreens_test.c builds, and the same silences:
    the hooks that only write are not installed on the C side, so they must
    do nothing here too -- otherwise a second activation of the same screen
    would read back an alpha the port never wrote.
    """

    def __init__(self, flow=None):
        self.flow = flow
        objs = []
        for screen, n_items in sorted(AUTHORED_ITEMS.items()):
            for i in range(1, n_items + 1):
                y = 50.0 + (i - 1) * 20.0
                objs.append(ba.Obj(screen, mask(i), ba.H_GROUP(i),
                                   ba.TYPE_BITMAP, 100.0, y, 1.0, 1.0,
                                   [128] * 4))
                objs.append(ba.Obj(screen, item(i), ba.H_GROUP(i),
                                   ba.TYPE_TEXT, 120.0, y, 1.0, 1.0,
                                   [128] * 4))
            objs.append(ba.Obj(screen, MI_UNDERSCORE, UNDERSCORE_GROUP,
                               ba.TYPE_BITMAP, 95.0, 50.0, 1.0, 1.0,
                               [128] * 4))
            objs.append(ba.Obj(screen, MI_OVERSCORE, UNDERSCORE_GROUP,
                               ba.TYPE_BITMAP, 95.0, 44.0, 1.0, 1.0,
                               [128] * 4))
            objs.append(ba.Obj(screen, SCROLLING_TEXT, 0, ba.TYPE_TEXT,
                               40.0, 200.0, 1.0, 1.0, [128] * 4))
            objs.append(ba.Obj(screen, WHITEOUT_BAR, 0, ba.TYPE_BITMAP,
                               40.0, 198.0, 1.0, 1.0, [128] * 4))
            objs.append(ba.Obj(screen, BLOOM_TEXT, 0, ba.TYPE_TEXT,
                               0.0, 0.0, 1.0, 1.0, [128] * 4))
            objs.append(ba.Obj(screen, BLOOM_TEXT_2, 0, ba.TYPE_TEXT,
                               0.0, 0.0, 1.0, 1.0, [128] * 4))
        ba.World.__init__(self, objs)

    # Installed, and answering with the authored value rather than with
    # whatever a previous fade left behind.
    def get_alpha(self, screen, name, corner):
        return 128

    def get_scale(self, screen, name):
        return ba.f32(1.0), ba.f32(1.0)

    def translate(self, lid):
        return "<string %d>" % lid

    # Not installed on the C side: a null hook in BAnimHooks is a no-op.
    def set_visible(self, screen, name, v):
        pass

    def set_alpha(self, screen, name, corner, a):
        pass

    def set_language_id(self, screen, name, lid):
        pass

    def print_text(self, screen, name, s):
        pass

    def copy_text(self, screen, dst, src):
        pass

    def scale_about_center(self, screen, name, scale):
        pass

    def set_color(self, screen, name, c):
        pass

    # bscreens.c installs its own over whatever the bundle passes, because
    # ChangeToScreen (0x0014a438) is a free function on the one screen list.
    def change_to_screen(self, name, push):
        self.flow.change_to_screen(name, push)

FRED_EXPRESS, FRED_ULTIMATE, FRED_HOTPURSUIT = 2, 8, 9

# CopsOnModeSelect: Quick Race / You're The Cop / Challenge / Ultimate Road
# Racer, and a fifth case with no object on disc.
COPS_ON_ITEMS = [
    {"blurb": 10017, "act": "quick", "screen": None},
    {"blurb": 10014, "act": "beacop", "screen": "ChallengeBeACop"},
    {"blurb": 10012, "act": "challenge", "screen": "Challenge"},
    {"blurb": 10013, "act": "tree", "screen": "View Event Tree",
     "gameType": FRED_HOTPURSUIT, "treeType": 1},
    {"blurb": 10009, "act": "plain", "screen": "Options"},
]

COPS_OFF_ITEMS = [
    {"blurb": 10006, "act": "quick", "screen": None},
    {"blurb": 10007, "act": "challenge", "screen": "Challenge"},
    {"blurb": 10008, "act": "tree", "screen": "View Event Tree",
     "gameType": FRED_ULTIMATE, "treeType": 0},
    {"blurb": 10009, "act": "plain", "screen": "Options"},
]

MODE_CONFIG = {
    "copson": {
        "name": "Cops On Mode Select", "hash": COPS_ON,
        "movie": "MOVIES\\hotpursuit_movie.AVI",
        "doubleTick": True,
        "cases": 5, "items": COPS_ON_ITEMS,
    },
    # The space in "worldracing_ movie.AVI" is the shipped filename.
    "copsoff": {
        "name": "Cops Off Mode Select", "hash": COPS_OFF,
        "movie": "MOVIES\\worldracing_ movie.AVI",
        "doubleTick": False,
        "cases": 4, "items": COPS_OFF_ITEMS,
    },
}

# tOptionsScreen's seven. Four slide out first, three change on the spot.
OPTION_ITEMS = [
    {"blurb": 100020, "screen": "Audio Options", "now": False},
    {"blurb": 100021, "screen": "Joystick PreConfig", "now": False},
    {"blurb": 100022, "screen": "Display Options", "now": False,
     "display": True},
    {"blurb": 100023, "screen": "Phils Load Save", "now": True},
    {"blurb": 100024, "screen": "NameEntry", "now": False},
    {"blurb": 100025, "screen": "Credits", "now": True},
    {"blurb": 100026, "screen": "Language Options", "now": True},
]


def new_instance():
    # The animation kit's members are filled in by kit_construct; until then
    # the instance is the memset the constructors start with.
    return {"live": False, "screen": 0, "cur": 0, "blurb": 0,
            "transmission": 0, "ticks": 0, "exit": None, "exit_active": False,
            "sel": None, "blurb_anim": None, "bloom": None, "bloom2": None,
            "slide_in": None}


class Screens(bf.Flow):
    """The three screens, on top of the boot flow's screen list."""

    # Only these three are registered, so every other destination they name
    # -- Challenge, View Event Tree, Audio Options -- comes out
    # "unregistered", which is what the port can honestly claim today.
    SCREENS = [
        ("Cops On Mode Select", COPS_ON, "copson"),
        ("Cops Off Mode Select", COPS_OFF, "copsoff"),
        ("Options", OPTIONS, "options"),
    ]

    def __init__(self, sc, out):
        bf.Flow.__init__(self, sc, out)
        self.cops_on = sc["copsOn"]
        self.be_a_cop = 0
        self.game_type = 0
        self.num_player_cars = 0
        self.tree_type = 0
        self.boost = 0
        self.inst = {"copson": new_instance(), "copsoff": new_instance(),
                     "options": new_instance()}
        # One clock for the module, re-slaved to the flow's before every
        # entry point, because RealTimer and RealTimeElapsed are one global
        # each. banim's own trace goes into this transcript -- that is what
        # bscreens.c's animTrace does -- and the hook traffic is dropped,
        # because tools/banim_check.py is what checks that.
        self.anim = ba.Anim(Bundle(self))
        ba.EMIT[0] = None
        ba.TRACE[0] = self.say

    def clock(self):
        self.anim.set_clock(ba.i32(self.real_timer), self.real_elapsed)
        return self.anim

    def top_left_x(self, screen, obj):
        return self.anim.w.get_top_left(screen, obj)[0]

    # -- the animation kit, as each constructor builds it ----------------
    def kit_construct(self, inst, masks):
        a = self.clock()
        inst["sel"] = ba.SelSet(a, inst["screen"])
        inst["sel"].indicator_mode = 1
        inst["sel"].add_items(masks)
        inst["blurb_anim"] = ba.Blurb(a, inst["screen"], SCROLLING_TEXT,
                                      SCROLLING_TEXT, WHITEOUT_BAR)
        inst["bloom"] = ba.Highlight(a, inst["screen"], BLOOM_TEXT,
                                     ba.BLOOM_COLOR)
        inst["slide_in"] = ba.slide_in(a, inst["screen"],
                                       self.top_left_x(inst["screen"],
                                                       mask(1)))

    def kit_destruct(self, inst):
        a = self.clock()
        if inst["exit_active"]:
            inst["exit"].slide.release()
        inst["slide_in"].release()
        inst["blurb_anim"].release()
        del a

    def kit_tick(self, inst):
        a = self.clock()
        inst["sel"].update()
        inst["blurb_anim"].animate()
        inst["bloom"].animate()
        if inst["bloom2"] is not None:
            inst["bloom2"].animate()
        inst["slide_in"].animate()
        del a

    # -- the hooks -------------------------------------------------------
    def hook_gray(self, screen, it, mode):
        self.say("hook gray %08x %08x %d" % (screen, it, mode))

    def hook_blurb(self, screen, blurb):
        self.say("hook blurb %08x %d" % (screen, blurb))

    def hook_brackets(self, screen, m, under, over):
        self.say("hook brackets %08x %08x %.1f %.1f"
                 % (screen, m, under, over))

    def hook_movie(self, path):
        self.say("hook movie %s" % path)

    def hook_movie_stop(self):
        self.say("hook movie stop")

    def hook_jukebox(self, start):
        self.say("hook jukebox %d" % start)

    def hook_display_start(self):
        self.say("hook display start")

    def hook_quick_race(self, p):
        self.say("hook quickrace type %d cars %d track %d traffic %.2f %.2f "
                 "race %d p2p %d laps %d ai %d start %d train %d obj %d %d"
                 % (p["gameType"], p["fredNumPlayerCars"], p["trackNumber"],
                    p["trafficDensity"], p["trafficOncoming"], p["raceType"],
                    p["point2Point"], p["numLapsInRace"], p["numAICars"],
                    p["playerStartPosition"], p["trainingLinesEnabled"],
                    p["hasObjective"], p["objectiveCleared"]))
        self.say("hook quickrace tree %d maxcops %d tickets %d blocks %d "
                 "spikes %d heli %d arrest %d copblocks %d chopper %d "
                 "copstr %d oppstr %d boost %d %.1f %.1f gearbox %d"
                 % (p["eventTreeRace"], p["maxCops"], p["tickets"],
                    p["roadBlocks"], p["spikeStrips"], p["helicopter"],
                    p["ticketsBeforeArrest"], p["numBeACopRoadBlocks"],
                    p["numBeACopChoppers"], p["copStrength"],
                    p["opponentStrength"], p["boost"], p["boostScale"][0],
                    p["boostScale"][1], p["transmissionType"]))

    # -- shared ----------------------------------------------------------
    @staticmethod
    def item_index(item_hash, cases):
        """MENUITEM_n -> n, or 0. An unsigned range check on hash - MENUITEM_1."""
        i = (item_hash - item(1)) & 0xffffffff
        return i + 1 if i < cases else 0

    def set_current_item(self, inst, m, under, over):
        inst["cur"] = m
        self.hook_brackets(inst["screen"], m, under, over)
        inst["sel"].set_current(m)
        self.say("bracket %08x" % m)

    def set_blurb(self, inst, blurb):
        inst["blurb"] = blurb
        inst["blurb_anim"].new_text_id(blurb)
        self.hook_blurb(inst["screen"], blurb)
        self.say("blurb %d" % blurb)

    # -- StartChangeToScreen ---------------------------------------------
    def exit_start(self, inst, name):
        a = self.clock()
        inst["exit"] = ba.Exit(a, inst["screen"], name or "")
        inst["exit"].slide.add_group(UNDERSCORE_GROUP, MI_UNDERSCORE,
                                     self.top_left_x(inst["screen"],
                                                     MI_UNDERSCORE),
                                     ba.OFFSCREEN_X,
                                     inst["exit"].slide.total_time)
        inst["exit_active"] = True

    def exit_messages(self, inst, msg, data):
        e = inst["exit"]
        done, param, noise = e.message(msg)
        if param is not None:
            data["param"] = param
        if noise is not None:
            data["noise"] = noise
        return done != 0

    # -- StartQuickRace (0x00203ae0) -------------------------------------
    def quick_race_params(self, transmission):
        cops = 1 if self.cops_on else 0
        return {
            "trackNumber": 0,               # PickTrackNumberForExpressGame
            "trafficDensity": 0.33, "trafficOncoming": 0.5,
            "raceType": 1,
            "point2Point": 0,               # GetTrackInfo(track)[67]
            "numLapsInRace": 2, "numPlayerCars": 1,
            "numAICars": 3 if cops else 7,
            "playerStartPosition": 2 if cops else 8,
            "trainingLinesEnabled": 0, "hasObjective": 0,
            "objectiveCleared": 1,
            "eventTreeRace": 0,
            "maxCops": 4 if cops else 0,
            "tickets": cops, "roadBlocks": cops, "spikeStrips": cops,
            "helicopter": cops,
            "ticketsBeforeArrest": 2 if cops else 0,
            "numBeACopRoadBlocks": 0, "numBeACopChoppers": 0,
            "copStrength": 1, "opponentStrength": 1,
            "boost": 1, "boostScale": [1.0, 1.0],
            "gameType": FRED_EXPRESS, "fredNumPlayerCars": 1,
            "transmissionType": 1 if transmission else 0,
        }

    def start_quick_race(self, inst):
        p = self.quick_race_params(inst["transmission"])
        self.hook_movie_stop()
        self.say("quickrace cops=%d transmission=%d aicars=%d maxcops=%d "
                 "start=%d" % (1 if self.cops_on else 0,
                               p["transmissionType"], p["numAICars"],
                               p["maxCops"], p["playerStartPosition"]))
        self.hook_quick_race(p)

    # -- the two Mode Selects ---------------------------------------------
    def mode_construct(self, cfg, inst, screen):
        inst.clear()
        inst.update(new_instance())
        inst["live"] = True
        inst["screen"] = screen
        self.hook_movie(cfg["movie"])
        # Both Mode Selects pass the same five-entry table however many
        # items they have.
        self.kit_construct(inst, MODE_MASKS)
        self.hook_jukebox(1)
        self.say("%s ctor %08x" % (cfg["name"], screen))

    def mode_destruct(self, cfg, inst):
        self.say("%s dtor" % cfg["name"])
        self.kit_destruct(inst)
        inst.clear()
        inst.update(new_instance())

    def mode_highlight(self, cfg, inst, data):
        n = self.item_index(data["itemHash"], cfg["cases"])
        # SetCurrentMenuItem takes the RAW hash and runs before the range
        # check, so an item the switch does not know about still blooms.
        inst["bloom"].set_item(data["itemHash"])
        if not n:
            return
        self.set_current_item(inst, mask(n), UNDER_MODE, OVER_MODE)
        self.set_blurb(inst, cfg["items"][n - 1]["blurb"])

    def mode_select(self, cfg, inst, data):
        n = self.item_index(data["itemHash"], cfg["cases"])
        if not n:
            return
        it = cfg["items"][n - 1]
        self.say("select MENUITEM_%d" % n)
        act = it["act"]
        if act == "quick":
            # Split screen has its own path; on a second pad this item does
            # nothing and eats the click.
            if data["port"] != 0:
                data["noise"] = 0
                return
            self.start_quick_race(inst)
            return
        if act == "beacop":
            self.be_a_cop = 1
        elif act == "challenge":
            self.boost = 1
            self.be_a_cop = 0
        elif act == "tree":
            if data["port"] != 0:
                data["noise"] = 0
                return
            self.game_type = it["gameType"]
            self.num_player_cars = 1
            self.tree_type = it["treeType"]
        self.exit_start(inst, it["screen"])

    def mode_handle(self, cfg, inst, msg, data):
        if msg == bf.SCREEN_TICK:
            self.kit_tick(inst)
            inst["ticks"] += 1
        if inst["exit_active"]:
            self.exit_messages(inst, msg, data)
            return
        if msg == MENUITEM_HIGHLIGHT:
            self.mode_highlight(cfg, inst, data)
            return
        if msg < MENUITEM_UNHIGHLIGHT:
            if msg == bf.MENUITEM_SELECT:
                self.mode_select(cfg, inst, data)
            return
        # The msg >= 5 arm tests for SCREEN_TICK a second time, so
        # CopsOnModeSelect runs OnTick twice a tick and CopsOffModeSelect
        # once. Nothing observable depends on it; the counter holds it still.
        if msg == bf.SCREEN_TICK and cfg["doubleTick"]:
            self.kit_tick(inst)
            inst["ticks"] += 1

    def mode_callback(self, kind, msg, data):
        cfg = MODE_CONFIG[kind]
        inst = self.inst[kind]
        if msg == bf.SCREEN_ACTIVATE:
            self.mode_construct(cfg, inst, data["itemHash"])
            return
        if msg == bf.SCREEN_UNACTIVATE:
            if inst["live"]:
                self.mode_destruct(cfg, inst)
            return
        if not inst["live"]:
            self.say("%s message with no instance" % cfg["name"])
            return
        self.mode_handle(cfg, inst, msg, data)

    def joy(self, port, joy_event, pressed):
        if joy_event != 23 or port != 0:
            return
        for kind in ("copson", "copsoff"):
            if self.inst[kind]["live"]:
                self.inst[kind]["transmission"] = pressed

    # -- the Options screen ------------------------------------------------
    def options_construct(self, inst, screen):
        inst.clear()
        inst.update(new_instance())
        inst["live"] = True
        inst["screen"] = screen
        self.kit_construct(inst, OPTION_MASKS)
        # The second bloom, with colour -1: the copy keeps whatever
        # colour the object it was copied from had.
        inst["bloom2"] = ba.Highlight(self.clock(), screen,
                                      BLOOM_TEXT_2, -1)
        self.hook_movie("MOVIES\\options_movie_new.AVI")
        self.say("Options ctor %08x" % screen)
        # On NTSC there is no language to pick, so MENUITEM_7 is disabled
        # AND hidden -- GrayMenuItem's mode 2 does both.
        if self.video_mode == 1:
            self.hook_gray(screen, item(7), 2)
            self.say("gray MENUITEM_7 hide (NTSC)")

    def options_destruct(self, inst):
        self.say("Options dtor")
        self.kit_destruct(inst)
        inst.clear()
        inst.update(new_instance())

    def options_highlight(self, inst, data, override):
        m = override
        # Both highlight animations, on the raw hash, before anything else.
        inst["bloom"].set_item(data["itemHash"])
        inst["bloom2"].set_item(data["itemHash"])
        if not m:
            n = self.item_index(data["itemHash"], 7)
            # Out of range leaves the mask at 0 and the rest runs anyway.
            m = mask(n) if n else 0
        self.set_current_item(inst, m, UNDER_OPT, OVER_OPT)

    def options_select(self, inst, data):
        dest, now = "", False
        n = self.item_index(data["itemHash"], 7)
        if n:
            it = OPTION_ITEMS[n - 1]
            dest, now = it["screen"], it["now"]
            self.say("select MENUITEM_%d" % n)
            if it.get("display"):
                self.hook_display_start()
                self.say("display options start")
        else:
            self.say("select unknown %08x" % data["itemHash"])
        if now:
            self.change_to_screen(dest, 1)
            return True
        self.exit_start(inst, dest)
        return False

    def options_handle(self, inst, msg, data):
        if msg == MENUITEM_HIGHLIGHT:
            n = self.item_index(data["itemHash"], 7)
            if n:
                self.set_blurb(inst, OPTION_ITEMS[n - 1]["blurb"])
            return False
        if msg < MENUITEM_UNHIGHLIGHT:
            if msg == bf.MENUITEM_SELECT:
                return self.options_select(inst, data)
            return False
        if msg == bf.SCREEN_TICK:
            # The blurb is animated twice a tick on this screen: once here
            # and once in FirstCrackAtMessage. Both call sites are in the
            # disassembly, and the second does nothing new because RealTimer
            # has not moved between them.
            inst["blurb_anim"].animate()
            inst["ticks"] += 1
        return False

    def options_first_crack(self, inst, msg, data):
        # The base gets every message first and runs the highlight itself.
        if msg == MENUITEM_HIGHLIGHT:
            self.options_highlight(inst, data, 0)
        elif msg == bf.SCREEN_TICK:
            self.kit_tick(inst)
        if inst["exit_active"]:
            self.exit_messages(inst, msg, data)
            return
        self.options_handle(inst, msg, data)

    def options_callback(self, msg, data):
        inst = self.inst["options"]
        if msg == bf.SCREEN_ACTIVATE:
            self.options_construct(inst, data["itemHash"])
            return
        if msg == bf.SCREEN_UNACTIVATE:
            if inst["live"]:
                self.options_destruct(inst)
            return
        if not inst["live"]:
            self.say("Options message with no instance")
            return
        self.options_first_crack(inst, msg, data)

    # -- FlailerScreenConfig::Callback -------------------------------------
    def dispatch(self, kind, msg, data):
        if kind in ("copson", "copsoff"):
            self.mode_callback(kind, msg, data)
        elif kind == "options":
            self.options_callback(msg, data)


# --------------------------------------------------------------- scenarios
#
# Kept in step with kScenarios[] in tools/src/bscreens_test.c by hand; the
# diff says at once when they drift.
def S(name, screen, video, cops, frames, inputs):
    return {"name": name, "screen": screen, "videoMode": video,
            "copsOn": cops, "frames": frames, "input": inputs,
            # what bf.Flow.__init__ reads and this never uses
            "frontendLaunchType": 1, "demoModeStatus": 0, "skipMovies": 0,
            "currLanguage": 0, "demoDiscActive": 0, "haveIntroMovie": 0}


SCENARIOS = [
    S("copson_highlight", "Cops On Mode Select", 1, 1, 8,
      [(1, "h1"), (2, "h2"), (3, "h3"), (4, "h4"), (5, "h5"), (6, "hx")]),
    S("copson_challenge", "Cops On Mode Select", 1, 1, 24,
      [(2, "h3"), (3, "s3")]),
    S("copson_quick", "Cops On Mode Select", 1, 1, 8,
      [(2, "h1"), (3, "s1")]),
    S("copson_gearbox", "Cops On Mode Select", 1, 1, 8,
      [(1, "xon"), (2, "h1"), (3, "s1")]),
    S("copson_gearbox_off", "Cops On Mode Select", 1, 1, 8,
      [(1, "xon"), (2, "xoff"), (3, "s1")]),
    S("copson_port1", "Cops On Mode Select", 1, 1, 10,
      [(2, "P1"), (4, "P4"), (6, "P3")]),
    S("copson_locked", "Cops On Mode Select", 1, 1, 24,
      [(2, "s4"), (4, "back"), (6, "up"), (8, "down")]),
    S("copson_options", "Cops On Mode Select", 1, 1, 24, [(2, "s5")]),
    S("copsoff_highlight", "Cops Off Mode Select", 1, 0, 8,
      [(1, "h1"), (2, "h2"), (3, "h3"), (4, "h4")]),
    S("copsoff_worldchamp", "Cops Off Mode Select", 1, 0, 20,
      [(2, "h3"), (3, "s3")]),
    S("copsoff_quick", "Cops Off Mode Select", 1, 0, 8,
      [(2, "h1"), (3, "s1")]),
    S("options_pal", "Options", 0, 0, 10,
      [(1, "h1"), (2, "h3"), (3, "h5"), (4, "h7"), (5, "hx")]),
    S("options_ntsc", "Options", 1, 0, 6, [(1, "h7")]),
    S("options_audio", "Options", 0, 0, 32, [(2, "h1"), (3, "s1")]),
    S("options_display", "Options", 0, 0, 32, [(2, "h3"), (3, "s3")]),
    S("options_credits", "Options", 0, 0, 8, [(2, "h6"), (3, "s6")]),
    S("options_unknown", "Options", 0, 0, 32, [(2, "hx"), (3, "sx")]),
]

UNKNOWN_ITEM = 0xdeadbeef


def do_input(f, what):
    f.say("input %s" % what)
    if what == "back":
        f.back_button(0)
    elif what == "up":
        f.menu_item_event(bf.MENUITEM_PAD_UP, item(1), 0)
    elif what == "down":
        f.menu_item_event(bf.MENUITEM_PAD_DOWN, item(1), 0)
    elif what == "xon":
        f.joy(0, 23, 1)
    elif what == "xoff":
        f.joy(0, 23, 0)
    elif what == "hx":
        f.menu_item_event(MENUITEM_HIGHLIGHT, UNKNOWN_ITEM, 0)
    elif what == "sx":
        f.menu_item_event(bf.MENUITEM_SELECT, UNKNOWN_ITEM, 0)
    elif what[0] == "h":
        f.menu_item_event(MENUITEM_HIGHLIGHT, item(int(what[1])), 0)
    elif what[0] == "s":
        f.menu_item_event(bf.MENUITEM_SELECT, item(int(what[1])), 0)
    elif what[0] == "P":
        f.menu_item_event(bf.MENUITEM_SELECT, item(int(what[1])), 1)


def run_scenario(sc):
    out = ["scenario %s" % sc["name"]]
    f = Screens(sc, out)
    f.change_to_screen(sc["screen"], 0)
    for frame in range(sc["frames"]):
        for at, what in sc["input"]:
            if at == frame:
                do_input(f, what)
        f.frame(SIXTIETH)
        out.append("frame %d %u %u" % (frame, f.real_time, f.real_timer))
    out.append("final screen %s cops %d beacop %d gametype %d cars %d "
               "tree %d boost %d ticks %d %d %d"
               % (f.screen[0] if f.screen else "-", f.cops_on, f.be_a_cop,
                  f.game_type, f.num_player_cars, f.tree_type, f.boost,
                  f.inst["copson"]["ticks"], f.inst["copsoff"]["ticks"],
                  f.inst["options"]["ticks"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", action="append",
                    help="one scenario name; repeatable (default: all)")
    ap.add_argument("--dump", help="write both transcripts next to this path")
    args = ap.parse_args()

    names = args.scenario or [s["name"] for s in SCENARIOS]
    chosen = [s for s in SCENARIOS if s["name"] in names]
    if len(chosen) != len(names):
        sys.exit("unknown scenario in %s" % names)

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, "bscreens_test")
        proc = subprocess.run([str(exe)] + [s["name"] for s in chosen],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr)
            sys.exit("bscreens_test failed")
        c_lines = proc.stdout.replace("\r\n", "\n").rstrip("\n").split("\n")

    py_lines = []
    for sc in chosen:
        py_lines.extend(run_scenario(sc))

    if args.dump:
        with open(args.dump + ".c.txt", "w") as fh:
            fh.write("\n".join(c_lines) + "\n")
        with open(args.dump + ".py.txt", "w") as fh:
            fh.write("\n".join(py_lines) + "\n")

    diff = list(difflib.unified_diff(c_lines, py_lines, "bscreens.c",
                                     "bscreens_check.py", lineterm=""))
    ndiff = sum(1 for d in diff if d[:1] in "+-" and d[:3] not in ("+++", "---"))
    for line in diff[:80]:
        print(line)
    if len(diff) > 80:
        print("... %d more diff lines" % (len(diff) - 80))
    print("%d scenarios, %d lines, %d differ"
          % (len(chosen), len(c_lines), ndiff))
    return 1 if ndiff else 0


if __name__ == "__main__":
    sys.exit(main())
