#!/usr/bin/env python3
r"""Cross-check the 3DS boot flow against a second implementation.

`3DS Files/source/gameflow.c` is the port of the PS2 boot sequence -- the
`GameFlowStateInfoTable` machine, the `FlailerScreenList` screen stack,
`LaunchFrontendMenus` and the three boot screens. This file is the same
sequence written again, in Python, from `docs/formats/boot-flow.md` and the
disassembly it cites rather than from the C. Both run the same scenarios
against the same simulated world and print the same transcript; the diff is
the test.

That only proves the two agree, which is worth less than it sounds -- see the
note at the end of HANDOFF.md. What it does catch is a misread: two people
reading `ServiceGameFlow`'s loop, or the push order in `LaunchFrontendMenus`,
or which of the two visibility enums is which, and disagreeing.

The title screen is not written again at all: it is retail's own
TitleScreen::Callback (0x0016f440) and everything under it, run on
SLES_507.31 by tools/mipsemu.py, with the calls out of the screen stubbed onto
this flow and its world. See RetailTitle. The same goes for the loading --
LoadGlobalChunks, the LOADING_FRONTEND state's Begin, Loop and End, the two
load callbacks and the LanguageManager under them (RetailLoading) -- and for
the language screen, LanguageOptionsScreenBase (RetailLanguage), for
BootAutoload -- BootAutoLoader, the memory card classes under it and the two
popups they speak through (RetailAutoload) -- for ConsiderStartDemoMode and
StartDemoMode, which run under the title's stubs, and for the menus' movie,
FlailerScreenList's StartMovie, UpdateMovie and StopMovie (RetailMovie).

Usage:
    python tools/bootflow_check.py                  # all scenarios
    python tools/bootflow_check.py --scenario ntsc
    python tools/bootflow_check.py --dump out.txt   # keep both transcripts
    python tools/bootflow_check.py --mutate [--only a,b]

--mutate breaks gameflow.c's title screen, loading and language screen one
way at a time and checks the diff notices. The Python side is retail's code,
so it is never mutated.
"""
import argparse
import difflib
import os
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                                    # noqa: E402

SOURCES = ["tools/src/gameflow_test.c",
           "3DS Files/source/gameflow.c",
           "3DS Files/source/bpopup.c",
           "3DS Files/source/memcard.c",
           "3DS Files/source/banim.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c"]

# ScreenMessage
MENUITEM_SELECT = 1
MENUITEM_HIGHLIGHT = 4
MENUITEM_PAD_LEFT, MENUITEM_PAD_RIGHT = 6, 7
MENUITEM_PAD_UP, MENUITEM_PAD_DOWN = 8, 9
MENUITEM_SQUARE = 10
SCREEN_ACTIVATE, SCREEN_UNACTIVATE = 11, 12
SCREEN_START_BUTTON = 13
SCREEN_BACK_BUTTON = 17
SCREEN_TICK = 18

FE_SOUND_MENU_UP, FE_SOUND_MENU_DOWN = 3, 4
FE_SOUND_MENU_SELECT, FE_SOUND_MENU_CANCEL = 5, 6

# The Noise an event starts with: what the JoyHandler raising it seeds.
JOY_NOISE = {MENUITEM_SELECT: FE_SOUND_MENU_SELECT,
             MENUITEM_PAD_UP: FE_SOUND_MENU_UP,
             MENUITEM_PAD_DOWN: FE_SOUND_MENU_DOWN}

# GameFlowState
# (retail's tenth, EXIT_DEMO_DISC, only the demo disc enters; the port has
# no demo disc and no such state)
(NONE, LOADING_FRONTEND, UNLOADING_FRONTEND, IN_FRONTEND,
 LOADING_TRACK_COMMON, LOADING_TRACK_SPECIFIC, RACING,
 UNLOADING_TRACK_SPECIFIC, UNLOADING_TRACK_COMMON) = range(9)

STATE_NAMES = [
    "NONE", "LOADING_FRONTEND", "UNLOADING_FRONTEND", "IN_FRONTEND",
    "LOADING_TRACK_COMMON", "LOADING_TRACK_SPECIFIC", "RACING",
    "UNLOADING_TRACK_SPECIFIC", "UNLOADING_TRACK_COMMON",
]

# Screens and objects, by bStringHash of their authored names.
TITLE = 0xb5761d00
NEW_MAIN_MENU = 0xae0f8aa1

# bStringHash of NEW_MAIN_MENU's three MENUITEM_n objects -- the constants
# NewMainMenu::HandleEvent (0x00203768) compares against.
ITEM_MENUITEM_1 = 0x52e039f3    # "Hot Pursuit"
ITEM_MENUITEM_2 = 0x52e039f4    # "World Racing"
ITEM_MENUITEM_3 = 0x52e039f5    # "Options"
ITEM_MENUITEM_6 = 0x52e039f8    # the language screen's last language
ITEM_MENUITEM_7 = 0x52e039f9    # ... and its Load All Languages
LANGUAGE = 0x632b068e
BOOT_AUTOLOAD = 0xfa2ac5c6      # and "Autosave"'s
LOAD_SAVE = 0x9829bfab          # "Phils Load Save"
MUMBO_JUMBO = 0xdd4197c9
LOADING_TRACK = 0xd0131dd1

PLANE_43, PLANE_LB, PRESS_START = 0x3acf2d73, 0xbfaebf79, 0xb070dbc9
TITLE_IMAGE = 0xb73c8d23        # bStringHash("TITLE_IMAGE"), a group
MUMBO_PLANE = 0xdd479599
TEX_LEGAL, TEX_ANTIPIRACY = 0xa7ebc389, 0x38258033

STACK_DEPTH, NAME_LEN = 12, 32

# The world the harness simulates, same constants as tools/src/gameflow_test.c
MOVIE_FRAMES, LOADER_FRAMES, TEXTURE_POLLS, REPLAY_FRAMES = 5, 1, 2, 3
MAX_PENDING = 4
PANEL_FRAMES = 90

EALOGO_EN = "MOVIES\\INTRO\\EALOGO_EN.AVI"
NFSINTRO_EN = "MOVIES\\INTRO\\NFSINTRO_EN.AVI"


def f32(x):
    """C `float` arithmetic. The clock truncates, so the rounding matters."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


def s32(v):
    v &= 0xffffffff
    return v - (1 << 32) if v & 0x80000000 else v


# TitleMoviesToPlay, retail 0x002fb750: eight language rows of two, held to
# the image by retail_title_movies().
TITLE_MOVIES_AT = 0x002fb750
TITLE_MOVIES = [
    [(EALOGO_EN, 0), (NFSINTRO_EN, 1)],
    [("MOVIES\\INTRO\\EALOGO_FR.AVI", 0), ("MOVIES\\INTRO\\NFSINTRO_FR.AVI", 1)],
    [("MOVIES\\INTRO\\EALOGO_GE.AVI", 0), (NFSINTRO_EN, 1)],
    [("MOVIES\\INTRO\\EALOGO_IT.AVI", 0), (NFSINTRO_EN, 1)],
    [("MOVIES\\INTRO\\EALOGO_SP.AVI", 0), (NFSINTRO_EN, 1)],
    [("MOVIES\\INTRO\\EALOGO_SW.AVI", 0), (NFSINTRO_EN, 1)],
    [(None, 0), (None, 0)],
    [(None, 0), (None, 0)],
]


class Flow(object):
    """ServiceGameFlow + FlailerScreenList + the three boot screens."""

    def __init__(self, sc, out):
        self.sc = sc
        self.out = out

        self.current = NONE
        self.desired = NONE
        self.names = [""] * STACK_DEPTH
        self.index = 0
        self.screen = None                # a (name, hash, kind) triple

        self.real_time = 0
        self.real_timer = 0
        self.real_elapsed = 0.0
        self.frame_counter = 0
        self.accum = 0.0

        self.frontend_launch_type = sc["frontendLaunchType"]
        self.demo_mode_status = sc["demoModeStatus"]
        self.skip_movies = sc["skipMovies"]
        self.cops_on = 0
        self.video_mode = sc["videoMode"]
        self.force_legal = sc.get("forceLegal", 0)

        self.legal_timeout = 7.0
        self.antipiracy_timeout = 7.0
        self.begin_demo_timeout = 30.0

        # MumboJumboScreen's instance state; the other screens' lives in the
        # emulated image
        self.title = RetailTitle(self)
        self.loading = RetailLoading(self)
        self.language = RetailLanguage(self)
        self.m_state = 0
        self.m_timer = 0

        # the simulated world
        self.movie_playing = 0
        self.movie_left = 0
        self.tex_polls = 0
        self.pending = []                 # loads in flight: (what, callback)
        self.loader_due = LOADER_FRAMES   # nothing lands before this frame
        self.active_item = ITEM_MENUITEM_1
        self.replays_left = sc.get("replays", 0)
        self.replay_due = 0
        self.in_game = 0                  # InGameFlag

        # FlailerScreenList's constructor, which makes the two popups, and
        # its movie
        self.autoload = RetailAutoload(self)
        self.movie = RetailMovie(self)
        self.mainmenu = RetailMainMenu(self)
        self.unlaunch = RetailUnlaunch(self)

    # CurrLanguage is the LanguageManager's +0, in the image, where retail's
    # code reads and writes it.
    @property
    def curr_language(self):
        return s32(retail_emu().u32(LANGUAGE_MANAGER))

    @curr_language.setter
    def curr_language(self, v):
        retail_emu().put32(LANGUAGE_MANAGER, v)

    # -- transcript ------------------------------------------------------
    def say(self, line):
        self.out.append(line)

    # -- the registry ----------------------------------------------------
    # FlailerScreenConfig, the subset the boot names. `name` is the C++
    # literal, the hash is bStringHash of the authored name.
    SCREENS = [
        ("BootAutoload", BOOT_AUTOLOAD, "autoload"),
        ("Language Options Pre FE", LANGUAGE, "language"),
        ("Title Screen", TITLE, "title"),
        ("New Main Menu", NEW_MAIN_MENU, "mainmenu"),
        ("Legal MumboJumbo", MUMBO_JUMBO, "mumbo"),
        ("Phils Load Save", LOAD_SAVE, "loadsave"),
        ("Autosave", BOOT_AUTOLOAD, "autosave"),
    ]

    def find_screen(self, name):
        if not name:
            return None
        for row in self.SCREENS:
            if row[0] == name:
                return row
        return None

    # -- the world -------------------------------------------------------
    def movie_open(self, path):
        present = path == EALOGO_EN or (self.sc["haveIntroMovie"]
                                        and path == NFSINTRO_EN)
        if not present:
            return 0
        self.movie_playing = 1
        self.movie_left = MOVIE_FRAMES
        return 1

    def movie_drive(self):
        if self.movie_left > 0:
            self.movie_left -= 1
        return 1 if self.movie_left == 0 else 0

    def movie_close(self):
        if self.movie_playing:
            self.say("movie close")
        self.movie_playing = 0
        self.movie_left = 0

    # The menus' movie, TheMoviePlayer as StartMovie and UpdateMovie drive
    # it -- the same player as the title's. Every movie a menu names is on
    # the disc, and Update answers 0 on its PANEL_FRAMES-th call, or with
    # nothing open. Same rules as wPanelOpen and wPanelUpdate.
    def panel_open(self, path):
        self.say("panel open %s" % path)
        self.movie_playing = 1
        self.movie_left = PANEL_FRAMES
        return 1

    def panel_update(self):
        if not self.movie_playing:
            return 0
        if self.movie_left > 0:
            self.movie_left -= 1
        if self.movie_left > 0:
            return 1
        self.say("panel end")
        return 0

    # The loader: a load asked for in a frame lands at its end, after the
    # flow's pass, and its callback runs then. One its callback asks for
    # lands a frame later. Same rules as wServiceLoads in the C harness.
    def queue_load(self, what, done):
        if not done:
            return
        if len(self.pending) >= MAX_PENDING:
            self.say("loader full %s" % what)
            return
        self.pending.append((what, done))

    def service_loads(self):
        if self.frame_counter < self.loader_due:
            return
        run, self.pending = self.pending, []
        for what, done in run:
            self.say("loaded %s" % what)
            self.loading.run(done)

    # TheDemoModeReplay (0x002f0960), +4 loading and +8 loaded: one starts
    # loading when ConsiderLaunching is asked while the scenario has any
    # left, and lands REPLAY_FRAMES frames later. Same as wServiceReplay.
    def replay_consider(self):
        e = retail_emu()
        if self.replays_left <= 0:
            return 0
        self.replays_left -= 1
        e.put32(DEMO_REPLAY + 4, 1)
        self.replay_due = self.frame_counter + REPLAY_FRAMES
        return 1

    def service_replay(self):
        e = retail_emu()
        if not e.u32(DEMO_REPLAY + 4) or self.frame_counter < self.replay_due:
            return
        e.put32(DEMO_REPLAY + 4, 0)
        e.put32(DEMO_REPLAY + 8, 1)
        self.say("replay loaded")

    # -- Flailer visibility ----------------------------------------------
    def screen_visible(self, screen, visible):
        self.say("vis screen %08x %d" % (screen, visible))

    def object_visible(self, screen, obj, visible):
        self.say("vis object %08x %08x %d" % (screen, obj, visible))

    def sound(self, ev):
        if ev:
            self.say("sound %d" % ev)

    # -- ScreenStack ------------------------------------------------------
    def push(self, name):
        if self.index >= STACK_DEPTH:
            self.say("stack overflow %s" % name)
            return
        self.names[self.index] = (name or "")[:NAME_LEN - 1]
        self.index += 1
        self.say("stack push %d %s" % (self.index, name or ""))

    def pop(self):
        if self.index == 0:
            return None
        self.index -= 1
        self.say("stack pop %d %s" % (self.index, self.names[self.index]))
        return self.names[self.index]

    def reset_stack(self):
        self.names = [""] * STACK_DEPTH
        self.index = 0
        self.say("stack reset")

    def stack_top(self):
        return self.names[self.index - 1] if self.index else ""

    # -- FlailerScreenList -------------------------------------------------
    def send(self, msg, data):
        if not self.screen:
            return 0
        self.say("msg %s %d" % (self.screen[0], msg))
        self.dispatch(self.screen[2], msg, data)
        return 1

    def menu_item_event(self, msg, item_hash, port=0):
        data = {"itemHash": item_hash, "port": port, "param": 1,
                "noise": JOY_NOISE.get(msg, 0)}
        if not self.send(msg, data):
            return 0
        self.sound(data["noise"])
        return 1

    def screen_event(self, msg, port=0):
        data = {"itemHash": self.screen[1] if self.screen else 0,
                "port": port, "param": 1, "noise": JOY_NOISE.get(msg, 0)}
        if not self.send(msg, data):
            return 0
        self.sound(data["noise"])
        return 1

    def change_to_screen(self, name, push_current):
        old = self.screen
        self.say("change %s %d" % (name if name is not None else "(null)",
                                   push_current))
        if old:
            self.screen_visible(old[1], 0)
            if push_current:
                self.push(old[0])
            self.send(SCREEN_UNACTIVATE, {"itemHash": old[1], "port": 0,
                                          "param": 0, "noise": 0})
            self.say("ui leave %08x" % old[1])
            self.say("leave %s %08x" % (old[0], old[1]))
            self.screen = None
        if name:
            found = self.find_screen(name)
            if not found:
                self.say("unregistered %s" % name)
            else:
                self.screen = found
                self.screen_visible(found[1], 1)
                self.say("enter %s %08x" % (found[0], found[1]))
                # FlailerScreen::Activate (0x0016a858): the FlailerMenu is
                # built before SCREEN_ACTIVATE, on its first item, and
                # activated after it.
                self.say("ui open %08x" % found[1])
                self.active_item = ITEM_MENUITEM_1
                # Param goes in as -1, and the noise is played after.
                data = {"itemHash": found[1], "port": 0, "param": -1,
                        "noise": 0}
                self.send(SCREEN_ACTIVATE, data)
                self.sound(data["noise"])
                self.say("ui enter %08x" % found[1])
        return 1 if self.screen else 0

    # MoveToPreviousScreen (0x0016c670). The block is memset, so ItemHash
    # is 0.
    def move_to_previous_screen(self, n, send_back, port):
        data = {"itemHash": 0,
                "port": port, "param": 1, "noise": FE_SOUND_MENU_CANCEL}
        if send_back:
            self.send(SCREEN_BACK_BUTTON, data)
            # read back AFTER the callback, so a screen can silence it
            self.sound(data["noise"])
        if data["param"] != 1:
            self.say("back vetoed")
            return 0
        name = ""
        for _ in range(n):
            p = self.pop()
            name = p or ""
            if p is None:
                break
        if not name:
            self.say("back to nothing")
            return 0
        self.change_to_screen(name, 0)
        return 1

    # MoveBackScreen (0x00170320): no SCREEN_BACK_BUTTON, port -1.
    def move_back_screen(self, n):
        return self.move_to_previous_screen(n, 0, -1)

    # FlailerScreenList::JoyHandler's BACK (0x0016cab0).
    def back_button(self, port):
        return self.move_to_previous_screen(1, 1, port)

    # -- the flow ----------------------------------------------------------
    def change_state(self, desired, _pending=NONE):
        self.desired = desired
        self.say("want %s" % STATE_NAMES[desired])

    # Nine states; only LOADING_FRONTEND and UNLOADING_FRONTEND do anything.
    # LOADING_FRONTEND's Loop is retail's, run with the demo disc off, where
    # it does nothing: the port has none.
    def state_fns(self, state):
        if state == LOADING_FRONTEND:
            return (self.loading.begin, self.loading.end, self.loading.loop)
        if state == UNLOADING_FRONTEND:
            return (self.begin_unloading_frontend, None, None)
        return (None, None, None)

    def service(self):
        for _ in range(64):
            if self.current != self.desired:
                _, end, _l = self.state_fns(self.current)
                if end:
                    self.say("end %s" % STATE_NAMES[self.current])
                    end()
                self.current = self.desired
                begin, _e, _l = self.state_fns(self.current)
                self.say("state %s" % STATE_NAMES[self.current])
                if begin:
                    self.say("begin %s" % STATE_NAMES[self.current])
                    begin()
            _b, _e, loop = self.state_fns(self.current)
            if loop:
                loop()
            if self.current == self.desired:
                return
        self.say("service stuck %s" % STATE_NAMES[self.current])

    def advance_time(self, dt):
        dt = f32(dt)
        self.accum = f32(self.accum + dt)
        n = int(f32(self.accum * f32(60.0)))
        self.real_time = (self.real_time + (n if n != 0 else 1)) & 0xffffffff
        self.accum = f32(self.accum - f32(f32(n) * f32(1.0 / 60.0)))
        self.real_timer = (self.real_timer
                           + int(f32(dt * f32(4000.0)))) & 0xffffffff
        # RealTimeElapsed (0x00323cdc), the second half of the clock. The
        # boot flow never reads it; the frontend spline integrator does.
        self.real_elapsed = dt
        self.frame_counter += 1

    def frame(self, dt):
        self.advance_time(dt)
        self.service()
        if self.screen:
            self.send(SCREEN_TICK, {"itemHash": self.screen[1], "port": 0,
                                    "param": 0, "noise": 0})
        # FlailerScreenList::Tick (0x0016cca8) ticks both popups after the
        # screen, up or not, and then the movie. The song monitor after it
        # is songmon_check.py's; the harness has no hook for it.
        self.autoload.tick_popups()
        self.movie.update()
        self.service()

    def begin_unloading_frontend(self):
        # 0x00168830: UnlaunchFrontendMenus, retail's (RetailUnlaunch), the
        # unloads, then ChangeGameFlow(LOADING_TRACK_COMMON, NONE) at
        # 0x00168920.
        self.unlaunch.run(self.sc.get("gameType", 0),
                          self.sc.get("raceDemo", 0))
        self.change_state(LOADING_TRACK_COMMON, NONE)

    # -- LaunchFrontendMenus ----------------------------------------------
    def should_see_title_sequence(self):
        return 1 if 0 <= self.frontend_launch_type - 1 < 2 else 0

    def should_see_legal_mumbo_jumbo(self):
        return 0

    def should_see_language_select(self):
        if self.frontend_launch_type == 1 and self.curr_language == -1:
            return 1
        if self.video_mode != 0:       # MODE_NTSC never asks
            return 0
        return 1 if self.frontend_launch_type == 1 else 0

    def should_see_autoload(self):
        return 1 if self.frontend_launch_type == 1 else 0

    def launch_frontend_menus(self):
        if self.frontend_launch_type == 2 and self.demo_mode_status == 2:
            self.reset_stack()
            self.change_to_screen("New Main Menu", 1)
            return
        stages = [("Title Screen", self.should_see_title_sequence),
                  ("Legal MumboJumbo", self.should_see_legal_mumbo_jumbo),
                  ("Language Options Pre FE", self.should_see_language_select),
                  ("BootAutoload", self.should_see_autoload)]
        for name, pred in stages:
            if pred():
                self.push(name)
        # LIFO, and this pops its own top: the last push is the first screen.
        name = self.stack_top()
        if self.pop() is None:
            pass
        self.change_to_screen(name, 0)

    # -- the boot screens ---------------------------------------------------
    def dispatch(self, kind, msg, data):
        if kind == "title":
            self.title.callback(msg, data)
        elif kind == "mainmenu":
            self.mainmenu.callback(msg, data)
        elif kind == "mumbo":
            self.mumbo(msg, data)
        elif kind in ("autoload", "loadsave", "autosave"):
            self.autoload.callback(msg, data, kind)
        elif kind == "language":
            self.language.callback(msg, data)

    # MumboJumboScreen (0x0016a8b0). Both ShouldSee* are `return 0` on the
    # disc, so without the port's forceLegalScreens switch state 0 pops
    # straight back out and states 1-4 never run.
    def should_see_legal_screen(self):
        return self.force_legal

    def should_see_antipiracy(self):
        return self.force_legal

    def texture_ready(self):
        self.tex_polls += 1
        return self.tex_polls >= TEXTURE_POLLS

    def mumbo_begin_panel(self, state, tex):
        self.m_state = state
        self.object_visible(MUMBO_JUMBO, MUMBO_PLANE, 0)
        self.say("tex load %08x" % tex)
        self.tex_polls = 0

    def mumbo_show_panel(self, state, tex):
        self.m_state = state
        self.say("tex change %08x %08x %08x" % (MUMBO_JUMBO, MUMBO_PLANE, tex))
        self.object_visible(MUMBO_JUMBO, MUMBO_PLANE, 1)
        self.m_timer = self.real_timer

    def mumbo_expired(self, timeout):
        return f32(f32((self.real_timer - self.m_timer) & 0xffffffff)
                   * f32(1.0 / 4000.0)) > timeout

    def mumbo(self, msg, data):
        if msg in (SCREEN_ACTIVATE, SCREEN_UNACTIVATE):
            self.m_state = 0
            self.m_timer = 0
            return
        if msg != SCREEN_TICK:
            return
        if self.m_state == 0:
            if self.should_see_legal_screen():
                self.mumbo_begin_panel(1, TEX_LEGAL)
            elif self.should_see_antipiracy():
                self.mumbo_begin_panel(3, TEX_ANTIPIRACY)
            else:
                self.move_back_screen(1)
        elif self.m_state == 1:
            if self.texture_ready():
                self.mumbo_show_panel(2, TEX_LEGAL)
        elif self.m_state == 2:
            if self.mumbo_expired(self.legal_timeout):
                self.say("tex unload %08x" % TEX_LEGAL)
                if self.should_see_antipiracy():
                    self.mumbo_begin_panel(3, TEX_ANTIPIRACY)
                else:
                    self.move_back_screen(1)
        elif self.m_state == 3:
            if self.texture_ready():
                self.mumbo_show_panel(4, TEX_ANTIPIRACY)
        elif self.m_state == 4:
            if self.mumbo_expired(self.antipiracy_timeout):
                self.say("tex unload %08x" % TEX_ANTIPIRACY)
                self.move_back_screen(1)


# ------------------------------------------------------ retail's TitleScreen

RETAIL_GP = 0x003358f0
REAL_TIMER = RETAIL_GP - 19608          # RealTimer, 1/4000 s
SKIP_MOVIES = RETAIL_GP - 23036
THE_TITLE = RETAIL_GP - 21156           # the one TitleScreen instance
# DemoDiscManager, +0 is IsActive. Held at 0 on the image: the port has no
# demo disc, so retail's code runs its other branches.
DEMO_DISC = 0x002effe0
LANGUAGE_MANAGER = 0x0031c1c8           # TheLanguageManager
CURR_LANGUAGE = LANGUAGE_MANAGER        # its +0
REAL_TIME = RETAIL_GP - 19604           # RealTime, 1/60 s
BEGIN_FADE = RETAIL_GP - 21400          # BeginScreenFadeTime
LOGO_FRENCH = RETAIL_GP - 21404         # the LOADING art is the French pair
DYNTEX_PACK = RETAIL_GP - 21432         # pDynamicTexturePack
LOAD_ALL_LANGUAGES = RETAIL_GP - 16016
LANGUAGE_INST = RETAIL_GP - 16972       # the language screen's instance
SCREEN_LIST = RETAIL_GP - 21324         # TheFlailerScreenList
LOADING_TEX = 0xab0e817d                # bStringHash("LOADING")

TITLE_CALLBACK = 0x0016f440

_EMU = None


def retail_emu():
    """One image for every scenario: loading it is the slow part."""
    global _EMU
    if _EMU is None:
        import retail_model
        _EMU = retail_model.RetailEmu()
    return _EMU


class RetailTitle(object):
    """TitleScreen, retail's, on the emulated image.

    Every call the screen makes out of itself is stubbed: onto the Flow (the
    screen list, the clock, attract mode) or its world (the movie), or into
    the port's trace line for it. What is left running is the screen's own
    code -- the constructor, HandleTick, HandleEvent, the PRESS START delay
    (0x0016f4f8), GetTitleMovieDescription and its tables, GetNumTitleMovies
    and bStringHash -- which is exactly the part the port rewrote, and
    ConsiderStartDemoMode (0x0016ed50) under HandleTick, and StartDemoMode
    (0x0016ecd8) under that. Its replay is the flow's world, its StopMovie is
    RetailMovie's, and FrontendDatabase::StartDemoMode is the port's
    "attract".

    Two of the trace lines are the port's and not calls: "title idle" when a
    tick takes mode from 2 to 1, and "title skip" when an event does. And the
    per-tick calls -- the TITLE_IMAGE group, PRESS START, the bloom's
    Animate -- are traced when their answer changes, as gameflow.c does.
    """

    def __init__(self, flow):
        self.flow = flow
        e = self.e = retail_emu()
        if not getattr(e, "title_inst", 0):
            e.title_inst = e.alloc(64)
            e.title_data = e.alloc(16)
            e.title_plane = e.alloc(256)
        e.put32(THE_TITLE, 0)
        self.playing = 0
        self.pending = None
        self.memo = {}

    def _stubs(self):
        e, f = self.e, self.flow

        def arg(i):
            return e.reg[4 + i] & 0xffffffff

        def cstr(a):
            return e.read(a, 64).split(b"\0")[0].decode() if a else None

        def once(key, value, line):
            if self.memo.get(key) != value:
                f.say(line)
            self.memo[key] = value

        def new(_e):                       # operator new, 0x002577c0
            return e.title_inst

        def set_visibility(_e):            # FlailerSetVisibility
            screen, obj, vis = arg(0), arg(1), arg(2)
            line = "vis object %08x %08x %d" % (screen, obj, vis)
            if obj == PRESS_START:
                once("press", vis, line)
            else:
                f.say(line)

        def set_group(_e):                 # FlailerSetGroupVisibility
            screen, group, vis = arg(0), arg(1), arg(2)
            once("group", vis, "vis group %08x %08x %d" % (screen, group, vis))

        def screen_visibility(_e):         # SetFlailerScreenVisibility
            # FlailerScreenVisibility: VISIBLE is 0, INVISIBLE is 1
            f.screen_visible(arg(0), 1 if arg(1) == 0 else 0)

        def change_to_screen(_e):          # ChangeToScreen, tail-called
            self.pending = (cstr(arg(0)), arg(1))

        def init_file(_e):                 # MoviePlayer::InitFile
            name = cstr(arg(1))
            self.playing = 0
            if name is None:
                f.say("movie none %d" % e.u32(e.title_inst + 8))
            elif f.movie_open(name):
                self.playing = 1
                f.say("movie open %s" % name)
            else:
                f.say("movie missing %s" % name)

        def close(_e):                     # MoviePlayer::Close
            if self.playing:
                f.movie_close()
            self.playing = 0

        def drive(_e):                     # TitleScreen::DriveMovie
            return f.movie_drive() if self.playing else 1

        def bloom_start(_e):               # tHighlightAnimation::ForceStart
            f.say("bloom start")
            self.memo.pop("animate", None)

        def bloom_animate(_e):             # tHighlightAnimation::Animate
            once("animate", 1, "bloom animate")

        def replay_consider(_e):
            launching = f.replay_consider()
            f.say("replay consider %d" % launching)
            return launching

        def replay_launch(_e):
            f.say("replay launch")
            e.put32(DEMO_REPLAY + 8, 0)

        stubs = {
            0x002577c0: new,
            0x00114e98: lambda _e: None,             # operator delete
            0x00248870: lambda _e: f.say(            # tHighlightAnimation()
                "bloom init %08x %08x %08x" % (arg(1), arg(2), arg(3))),
            0x002488b0: lambda _e: None,             # ~tHighlightAnimation
            0x002488d0: lambda _e: f.say(            # SetCurrentMenuItem
                "bloom item %08x" % arg(1)),
            0x00248ad0: bloom_start,
            0x00248970: bloom_animate,
            0x00144968: set_visibility,
            0x001454e8: set_group,
            0x0014cbf8: screen_visibility,
            0x0014cc78: change_to_screen,
            0x00143d50: lambda _e: e.title_plane,    # FindFlailerObject
            0x00237ad8: init_file,
            0x00237fc8: close,
            0x0016ee18: drive,
            0x001aeab0: lambda _e: f.say("jukebox %d" % arg(0)),
            # IsAttractMode, off the demo disc 0; StartDemoDiscGame, which
            # a trace line would give away if it were ever reached.
            0x0012eaf0: lambda _e: 0,
            0x00184de0: lambda _e: f.say("demo disc game"),
            # TheDemoModeReplay's ConsiderLaunching and Launch under
            # ConsiderStartDemoMode, and StartDemoMode's calls: StopMovie,
            # run as RetailMovie runs it, BuildDemoTrackList, which leaves
            # one track to pick, and FrontendDatabase::StartDemoMode, the
            # port's "attract".
            0x0013f120: replay_consider,
            0x0013f1c0: replay_launch,
            0x0016d0a0: lambda _e: f.movie.stop(),
            0x0016ec10: lambda _e: e.put32(NUM_DEMO_TRACKS, 1),
            0x00184d48: lambda _e: f.say("attract"),
        }
        for addr, fn in stubs.items():
            e.stub(addr, fn)
        # StartDemoMode's entry, the port's trace line
        e.hook(0x0016ecd8, lambda _e: f.say("demo mode"))

    def callback(self, msg, data):
        e, f = self.e, self.flow
        self._stubs()
        lang = f.curr_language if 0 <= f.curr_language <= 7 else 0
        e.put32(REAL_TIMER, f.real_timer)
        e.put32(SKIP_MOVIES, f.skip_movies)
        e.put32(DEMO_DISC, 0)
        # Clamped for the screen's table lookup, and put back after: the
        # LanguageManager is the flow's.
        saved = e.u32(CURR_LANGUAGE)
        e.put32(CURR_LANGUAGE, lang)
        if msg == SCREEN_ACTIVATE:
            self.memo = {}
        # ScreenCallbackData: ItemHash, Port, Param, Noise.
        d = e.title_data
        e.put32(d + 0, data["itemHash"])
        e.put32(d + 4, data["port"])
        e.put32(d + 8, data["param"])
        e.put32(d + 12, data["noise"])
        inst = e.u32(THE_TITLE)
        before = e.u32(inst + 12) if inst else 0

        self.pending = None
        e.call(TITLE_CALLBACK, msg, d, limit=200000)
        e.put32(CURR_LANGUAGE, saved)

        data["param"] = struct.unpack("<i", e.read(d + 8, 4))[0]
        data["noise"] = e.u32(d + 12)
        inst = e.u32(THE_TITLE)
        after = e.u32(inst + 12) if inst else 0
        if before == 2 and after == 1:
            if msg == SCREEN_TICK:
                f.say("title idle")
            elif msg == MENUITEM_SELECT:
                f.say("title skip")
        if self.pending:
            f.change_to_screen(*self.pending)


# --------------------------------------------- retail's loading and language

LOAD_GLOBAL_CHUNKS = 0x001682d0
BEGIN_LOADING_FRONTEND = 0x00168698
LOOP_LOADING_FRONTEND = 0x00168718
END_LOADING_FRONTEND = 0x001687a8
SET_CURR_LANGUAGE = 0x00100818          # TheLanguageManager.SetLanguage
LANGUAGE_CALLBACK = 0x001f1dd8          # LanguageOptionsScreenBase::Callback


def _cstr(e, a):
    return e.read(a, 64).split(b"\0")[0].decode() if a else None


class RetailLoading(object):
    """The frontend's loading, retail's, on the emulated image.

    LoadGlobalChunks (0x001682d0), BeginGameFlowLoadingFrontend (0x00168698),
    its Loop and End, the two callbacks the loads land in (0x00168668, then
    0x00168658), and under them the LanguageManager -- SetLanguage, its tail,
    Load/UnloadCurrentSpeech and the LOADING art swap (0x001681b0) -- all run
    as they are. What is stubbed is the loader, the file system, the texture
    packs, the sound and the Flailer calls, onto this flow and its world.

    The loader keeps the C harness's rules: LoadResourceFile queues its
    callback, and the flow's frame runs the queue at the frame's end. GLOBAL
    loads are the port's bundles at boot, and say nothing, as gameflow.c
    does not trace them either.
    """

    def __init__(self, flow):
        self.flow = flow
        e = self.e = retail_emu()
        # LanguageManager's constructor, 0x0021dfa8, and the globals the
        # loading code keeps: each scenario is a fresh boot.
        e.put32(LANGUAGE_MANAGER, 0xffffffff)
        for off in (4, 8, 12, 16, 20):
            e.put32(LANGUAGE_MANAGER + off, 0)
        for a in (LOGO_FRENCH, BEGIN_FADE, DYNTEX_PACK, LOAD_ALL_LANGUAGES,
                  LANGUAGE_INST):
            e.put32(a, 0)
        self.deferred = None

    def stubs(self):
        e, f = self.e, self.flow

        def arg(i):
            return e.reg[4 + i] & 0xffffffff

        def load_resource(_e):             # LoadResourceFile, 0x00199640
            path = _cstr(e, arg(0))
            if not path.startswith("GLOBAL\\"):
                f.say("load %s" % path)
            f.queue_load(path, arg(3))
            return e.alloc(16)

        def hot_chunk(_e):                 # the hot chunk's name, 0x00199720
            name = _cstr(e, arg(1))
            if not name.startswith("GLOBAL\\"):
                f.say("hot chunk %s" % name)

        def size_language_buffer(_e):      # 0x0021dfe8: +8 size, +16 buffer
            e.put32(arg(0) + 8, 0x10000)
            e.put32(arg(0) + 16, e.alloc(64))

        def lm_language():
            return s32(e.u32(LANGUAGE_MANAGER))

        def remap(_e):                     # 0x001ac548, the art swap
            # Two remaps a swap; the first is LOADING's, and the flag it
            # toggles afterwards is what it is changing to.
            if arg(0) == LOADING_TEX:
                f.say("logo art %d" % (e.u32(LOGO_FRENCH) ^ 1))

        def screen_visibility(_e):         # SetFlailerScreenVisibility
            # FlailerScreenVisibility: VISIBLE is 0, INVISIBLE is 1
            f.screen_visible(arg(0), 1 if arg(1) == 0 else 0)

        def sound_regions(_e):             # LoadSoundRegions, 0x001ae9a0
            f.say("load sound regions")
            f.queue_load("sound regions", arg(0))

        def launch(_e):                    # LaunchFrontendMenus, tail-called
            self.deferred = f.launch_frontend_menus

        def nothing(_e):
            return None

        stubs = {
            0x00199640: load_resource,
            0x00199720: hot_chunk,
            0x00199788: nothing,                     # ServiceResourceLoading
            0x00199818: lambda _e: 1,                # nothing left to load
            0x0021dfe8: size_language_buffer,
            0x002577c0: lambda _e: e.alloc(max(arg(0), 16)),   # new
            0x001ac0a8: lambda _e: arg(0),           # TexturePack()
            0x001ac608: nothing,                     # its file
            0x001ac3f0: lambda _e: 0,                # GetLoadedTexture
            0x001acc98: nothing,                     # LoadTexturesFromFile
            0x001acd90: nothing,                     # UnloadTextures
            0x001ac548: remap,
            0x00194a00: nothing,                     # the speech banks' stop
            0x001992a8: lambda _e: f.say(            # UnloadChunks
                "language unload %d" % lm_language()),
            0x002544c0: lambda _e: 1,                # bOpen
            0x00254550: lambda _e: 16,               # bFileSize
            0x002547f0: nothing,                     # bRead
            0x002544e8: nothing,                     # bClose
            0x00199280: lambda _e: f.say(            # LoadChunks
                "language %d" % lm_language()),
            0x001ae4d8: lambda _e: f.say("speech %d" % s32(arg(0))),
            0x001ae5e8: lambda _e: f.say("speech unload"),
            0x00141648: nothing,                     # FlailerUpdateLanguageText
            0x0014cbf8: screen_visibility,
            0x00144968: lambda _e: f.object_visible(arg(0), arg(1), arg(2)),
            0x00112858: lambda _e: f.say("display frame"),   # eDisplayFrame
            0x001ed5c8: lambda _e: f.say("race defaults"),
            0x00257988: lambda _e: e.alloc(16),
            0x00103e68: nothing,                     # End's five Inits
            0x0011db90: nothing,
            0x0016df60: nothing,
            0x00194fa8: nothing,
            0x00237688: nothing,
            0x0016f950: launch,
            0x001680d8: lambda _e: f.change_state(s32(arg(0))),  # ChangeGameFlow
            0x001ae9a0: sound_regions,
        }
        for addr, fn in stubs.items():
            e.stub(addr, fn)

    def run(self, addr, *args):
        e, f = self.e, self.flow
        self.stubs()
        e.put32(REAL_TIME, f.real_time)
        e.put32(DEMO_DISC, 0)
        self.deferred = None
        e.call(addr, *args, limit=200000)
        if self.deferred:
            d, self.deferred = self.deferred, None
            d()

    def load_global_chunks(self):
        self.run(LOAD_GLOBAL_CHUNKS)

    def set_curr_language(self, language):
        self.run(SET_CURR_LANGUAGE, LANGUAGE_MANAGER, language)

    def begin(self):
        self.run(BEGIN_LOADING_FRONTEND)

    def loop(self):
        self.run(LOOP_LOADING_FRONTEND)

    def end(self):
        self.run(END_LOADING_FRONTEND)


class RetailLanguage(object):
    """LanguageOptionsScreenBase, retail's, on the emulated image.

    Callback (0x001f1dd8), the constructor (0x001f1a78), HandleScreenCallback
    (0x001f1b08) and the destructor, with SetCurrLanguage running through
    RetailLoading's stubs. Stubbed: bMalloc, GrayMenuItem, GetActiveMenuItem
    (the highlight the scenario moved), FrontendDatabase::InitWithDefaults and
    MoveToPreviousScreen, which is deferred to the flow once the call is back
    -- MoveBackScreen (0x00170320) runs, so its arguments are retail's.

    The screen list is faked only as far as Callback reads it: pCurrent's
    config's name, the string it tells the two classes apart by.
    """

    def __init__(self, flow):
        self.flow = flow
        e = self.e = retail_emu()
        if not getattr(e, "lang_list", 0):
            e.lang_list = e.alloc(512)
            e.lang_node = e.alloc(64)
            e.lang_config = e.alloc(64)
            e.lang_name = e.alloc(64)
            e.lang_data = e.alloc(16)
        self.deferred = None

    def stubs(self):
        e, f = self.e, self.flow

        def arg(i):
            return e.reg[4 + i] & 0xffffffff

        def gray(_e):                      # GrayMenuItem(name, item, screen, mode)
            f.say("gray %08x %08x %d" % (arg(2), arg(1), s32(arg(3))))

        def back(_e):                      # MoveToPreviousScreen(list, n, send, port)
            n, send, port = s32(arg(1)), s32(arg(2)), s32(arg(3))
            self.deferred = lambda: f.move_to_previous_screen(n, send, port)
            return 1

        stubs = {
            0x00257690: lambda _e: e.alloc(max(arg(0), 16)),   # bMalloc
            0x0016d2a8: gray,
            0x0016d3f0: lambda _e: f.active_item,    # GetActiveMenuItem
            0x00183830: lambda _e: f.say("frontend defaults"),
            0x0016c670: back,
            0x00114e98: lambda _e: None,             # operator delete
        }
        for addr, fn in stubs.items():
            e.stub(addr, fn)

    def callback(self, msg, data):
        e, f = self.e, self.flow
        f.loading.stubs()
        self.stubs()
        e.put32(REAL_TIME, f.real_time)
        name = (f.screen[0] if f.screen else "").encode() + b"\0"
        e.write(e.lang_name, name)
        e.put32(e.lang_config + 8, e.lang_name)
        e.put32(e.lang_node + 16, e.lang_config)
        e.put32(e.lang_list + 412, e.lang_node)
        e.put32(SCREEN_LIST, e.lang_list)

        # ScreenCallbackData: ItemHash, Port, Param, Noise.
        d = e.lang_data
        e.put32(d + 0, data["itemHash"])
        e.put32(d + 4, data["port"])
        e.put32(d + 8, data["param"])
        e.put32(d + 12, data["noise"])
        all_before = e.u32(LOAD_ALL_LANGUAGES)

        self.deferred = None
        e.call(LANGUAGE_CALLBACK, msg, d, limit=200000)

        data["param"] = s32(e.u32(d + 8))
        data["noise"] = e.u32(d + 12)
        if not all_before and e.u32(LOAD_ALL_LANGUAGES):
            f.say("load all languages")
        if self.deferred:
            d, self.deferred = self.deferred, None
            d()


# ------------------------------------------------------ retail's BootAutoload

AUTOLOAD_CALLBACK = 0x00247ab0          # BootAutoLoader::Callback
AUTOLOAD_INST = RETAIL_GP - 15084       # its pInstance
LOADER_CTOR = 0x00246bd8                # MemcardLoader(this, hash, mode)
LSW_CALLBACK = 0x00247830               # LoadSaveWrapper::Callback
LSW_INST = RETAIL_GP - 15088            # its pInstance
AUTOSAVE_CALLBACK = 0x00247d00          # Autosaver::Callback
AUTOSAVE_INST = RETAIL_GP - 15080       # its pInstance
SET_AUTOSAVE_DONE = 0x00247d98          # SetAutosaveCompletionCallback
START_WRITE_CALL = 0x0024631c           # CHECK_IF_CARD_OK's jal StartWrite
START_WRITE = 0x00246b10
ITEM_SAVE, ITEM_LOAD, ITEM_AUTOSAVE = 0x52e039f3, 0x52e039f4, 0x52e039f5
REAL_ELAPSED = RETAIL_GP - 19596        # RealTimeElapsed, a float
FRED = 0x002fc050                       # TheFrontendDatabase
DEMO_REPLAY = 0x002f0960                # TheDemoModeReplay: +4 loading, +8 loaded
POPUP_CTOR, POPUP_SUMMON = 0x0016b478, 0x0016b660
POPUP_DISMISS, POPUP_TICK, POPUP_JOY = 0x0016b9c0, 0x0016ba50, 0x0016bac0
POPUP_SIZE = 512

SAVE_SIZE, CHECKSUM_OFFSET = 0x114e0, 0x114dc
FRED_LANGUAGE, FRED_CLEARED = 372, 904
FRED_AUTOSAVE = 4

# PadEvent, as the pad hands them to FlailerScreenList::JoyHandler.
JOY_UP, JOY_DOWN, JOY_LEFT, JOY_RIGHT = 3, 4, 5, 6
JOY_START, JOY_MENU_SELECT, JOY_MENU_BACK = 7, 9, 11

POPUP_SCREEN = 0x0ce3f7ce               # the memory card's popup, FRONTB.BUN
FONT_HEIGHT = 43.0                      # a2d444f6's
# Its text objects in the file's order: name, GroupHash, TopLeftY, ScaleY,
# MaxChars, Color. Same rows as kPopupObjs in tools/src/gameflow_test.c,
# the first two lines' MaxChars shortened as it says.
POPUP_OBJS = [
    (0xe0105664, 0x457755c9, 324.0, 0.75, 16, 0x80505050),
    (0xe0105663, 0x457755c9, 324.0, 0.75, 16, 0x80505050),
    (0x0783bebf, 0x5d6dd123, 98.0, 0.6, 29, 0x80505050),
    (0x0783bec0, 0x5d6dd123, 123.0, 0.6, 30, 0x80505050),
    (0x0783bec1, 0x5d6dd123, 148.0, 0.6, 40, 0x80505050),
    (0x0783bec2, 0x5d6dd123, 173.0, 0.6, 40, 0x80505050),
    (0x0783bec3, 0x5d6dd123, 198.0, 0.6, 40, 0x80505050),
    (0x0783bec4, 0x5d6dd123, 223.0, 0.6, 40, 0x80505050),
    (0x0783bec5, 0x5d6dd123, 248.0, 0.6, 40, 0x80505050),
    (0x0783bec6, 0x5d6dd123, 273.0, 0.6, 40, 0x80505050),
    (0x0783bec7, 0x5d6dd123, 298.0, 0.6, 40, 0x80505050),
    (0x85eda094, 0x457755c9, 41.0, 0.85, 19, 0x80646464),
    (0xab671c9a, 0x457755c9, 602.0, 0.75, 21, 0x80808080),
]

# The memory card, scripted: the Services the constructor's pump takes and
# the lastError it settles at, then what each job leaves -- VERIFY, the
# first CHECK_EXISTENCE and every later one (-1 the same), LOAD -- whether
# the file's checksum holds, the free KB, the Services a job takes and
# whether SetState takes one at all; then every VERIFY after the first (-1
# the same), SAVE and FORMAT. A card a FORMAT has left formatted verifies
# clean, has no file and has room; one a SAVE has written has the file.
# Same rows as kCards in the C harness.
CARD_FIELDS = ("pump", "settle", "verify", "check", "check2", "load",
               "goodSum", "freeKB", "busy", "refuse", "verify2", "save",
               "format")
CARDS = {
    "blank":       (1, 0, 0, 5, -1, 0, 1, 8192, 1, 0, -1, 0, 0),
    "good":        (1, 0, 0, 0, -1, 0, 1, 8192, 1, 0, -1, 0, 0),
    "badsum":      (1, 0, 0, 0, -1, 0, 0, 8192, 1, 0, -1, 0, 0),
    "loaderr":     (1, 0, 0, 0, -1, 3, 1, 8192, 1, 0, -1, 0, 0),
    "nocard":      (1, 3, 3, 3, -1, 3, 1, 0, 1, 0, -1, 0, 0),
    "unformatted": (1, 1, 1, 1, -1, 1, 1, 0, 1, 0, -1, 0, 0),
    "newcard":     (1, 0, 2, 5, -1, 0, 1, 8192, 1, 0, -1, 0, 0),
    "full":        (1, 0, 0, 5, -1, 0, 1, 10, 1, 0, -1, 0, 0),
    "tight":       (1, 0, 0, 5, -1, 0, 1, 75, 1, 0, -1, 0, 0),
    "checkerr":    (1, 0, 0, 3, -1, 0, 1, 8192, 1, 0, -1, 0, 0),
    "busy":        (3, 0, 0, 5, -1, 0, 1, 8192, 3, 0, -1, 0, 0),
    "slow":        (1, 0, 0, 5, -1, 0, 1, 8192, 6, 0, -1, 0, 0),
    "refuse":      (1, 0, 0, 5, -1, 0, 1, 8192, 1, 1, -1, 0, 0),
    "gone":        (1, 0, 0, 0, 5, 0, 1, 8192, 1, 0, -1, 0, 0),
    "swapped":     (1, 0, 0, 0, 2, 0, 1, 8192, 1, 0, -1, 0, 0),
    "pulled":      (1, 0, 0, 0, 3, 0, 1, 8192, 1, 0, -1, 0, 0),
    "savefail":    (1, 0, 0, 5, -1, 0, 1, 8192, 1, 0, -1, 3, 0),
    "savefull":    (1, 0, 0, 5, -1, 0, 1, 8192, 1, 0, -1, 4, 0),
    "badformat":   (1, 1, 1, 1, -1, 1, 1, 0, 1, 0, -1, 0, 3),
    "fixed":       (1, 1, 1, 1, -1, 1, 1, 0, 1, 0, 0, 0, 0),
    "yanked":      (1, 0, 0, 5, -1, 0, 1, 8192, 1, 0, 3, 0, 0),
    "goneafter":   (1, 0, 0, 0, 3, 0, 1, 8192, 1, 0, -1, 0, 0),
}

FS_SAVE, FS_LOAD, FS_CHECK, FS_FORMAT, FS_VERIFY = 1, 2, 3, 5, 7
FS_IN_PROGRESS, FS_ERROR = 15, 16
FS_LAST_ERROR, FS_VTABLE = 292, 376     # cDBFilesBase's mLastError, vtable
FS_FILE_EXISTS = 1460                   # what CHECK_EXISTENCE found


def save_image(good):
    """The save file a LOAD hands back, as wWriteSave writes it."""
    words = []
    for i in range(CHECKSUM_OFFSET // 4):
        v = SAVE_SIZE if i == 0 else (i * 2654435761) & 0xffffffff
        if i == FRED_LANGUAGE // 4:
            v = 3
        if i == FRED_CLEARED // 4:
            v = 7
        words.append(v)
    words.append((sum(words) + (0 if good else 1)) & 0xffffffff)
    return struct.pack("<%dI" % len(words), *words)


SAVES = {}


def translated(i):
    """GetTranslatedString's stand-ins, the same as aTranslate's."""
    if i in (0x24de3, 0x24df3):
        return ("<string %d> slot %%d needs %%d KB free, more than the card"
                " has left.@Try again?" % i)
    if i == 0x24df4:
        return ("<string %d> with nothing to fill in: a message long enough"
                " that it has to wrap onto another line.@ @And one more." % i)
    return ("<string %d> in slot %%d: a message long enough that it has to"
            " wrap onto another line.@ @And one more." % i)


def mips_words(*ws):
    return struct.pack("<%dI" % len(ws), *ws)


class RetailAutoload(object):
    """BootAutoload, retail's, on the emulated image, with its two popups.

    BootAutoLoader::Callback (0x00247ab0) and everything under it run as they
    are: the constructor and destructor, HandleEvent, MemcardLoader's state
    machine, MemcardTester, MemcardPrompter and its two builders,
    SavegameData, CalculateChecksum and OverwriteFred. So does tPopupMenu --
    its constructor, Summon, Dismiss, Tick, HandleJoy, FlailerMenuItem's
    recolouring -- and RenderTextIntoGroup's word wrap with WriteTextIntoChunk
    and GetScaledHeight under it. FlailerScreenList's JoyHandler and Tick are
    only the loop over the two popups, and are here.

    Stubbed: the Flailer calls (onto the popup screen's objects, which are
    faked chunks with the file's fields), GetTranslatedString (the stand-ins
    above), the allocators, the highlight animation, bSin, the movie,
    MoveBackScreen (deferred to the flow), OverwriteFred's six calls into
    the rest of the frontend, and cDBFileSys -- which is the scripted card:
    an object with its vtable at +376 whose six methods are Python. Service
    has to call the job's callback, back into retail code, which a stub
    cannot, so its entry is a hook in front of four instructions that jump
    to whatever the hook left in t9.

    Two things are the port's and set here. MANUAL is reached by handing the
    loader's constructor MANUAL, as memcard.c's `manual` does. And the two
    prompt builders leave CancelParam, DismissParam and PopupID as stack
    garbage, which DismissPopup's trace line prints: they are zeroed before
    SummonPopup, as the port zeroes them.
    """

    def __init__(self, flow):
        self.flow = flow
        e = self.e = retail_emu()
        if not getattr(e, "al_list", 0):
            e.al_list = e.alloc(512)
            e.al_node = e.alloc(64)
            e.al_config = e.alloc(64)
            e.al_name = e.alloc(64)
            e.al_data = e.alloc(16)
            e.al_font = e.alloc(1152)
            e.al_text = [e.alloc(256), e.alloc(256)]
            e.al_chunks = [e.alloc(128) for _ in POPUP_OBJS]
            # The card's vtable: an 8-byte entry a slot, a halfword delta
            # (0) and the method. Each method is a stub address in al_code,
            # except Service's, which is real code behind a hook.
            e.al_vtbl = e.alloc(256)
            e.al_code = e.alloc(256)
            e.al_svc = e.al_code + 128
            e.write(e.al_svc, mips_words(
                0x13200003,     # beq  t9,zero,+3
                0x00000000,     # nop
                0x03200008,     # jr   t9
                0x00000000,     # nop
                0x03e00008,     # jr   ra
                0x00000000))    # nop
            for slot, fn in ((8, 0), (16, None), (40, 8), (64, 16),
                             (168, 24), (176, 32)):
                e.put32(e.al_vtbl + slot, 0)
                e.put32(e.al_vtbl + slot + 4,
                        e.al_svc if fn is None else e.al_code + fn)
        if not getattr(e, "al_save", 0):
            # The port's question before the saver makes the file, which
            # retail never asks: CHECK_IF_CARD_OK's `jal StartWrite` goes to
            # a `jr t9` whose hook picks StartWrite or the question -- the
            # same DisplayYesNoMessage the overwrite's is (0x002462a4), with
            # 151023, 1 for yes and 0 for no, then PROMPT_TO_CREATE. Its
            # answers are retail's own. +128 is the Autosave screen's
            # completion callback, a stub, and +136 Quit's, which leaves the
            # screen up.
            e.al_save = e.alloc(256)
            e.al_ask = e.al_save + 16
            e.al_done = e.al_save + 128
            e.al_stay = e.al_save + 136
            e.write(e.al_save, mips_words(0x03200008, 0x00000000))
            e.write(e.al_ask, mips_words(
                0x27bdffe0,     # addiu sp,sp,-32
                0xffbf0010,     # sd    ra,16(sp)
                0xffb00000,     # sd    s0,0(sp)
                0x00808021,     # move  s0,a0
                0x8e020004,     # lw    v0,4(s0)      the tester
                0x0c091582,     # jal   GetSlotForMemcardDevice
                0x8c44000c,     # lw    a0,12(v0)     its device
                0x00404021,     # move  t0,v0         the slot
                0x8e040008,     # lw    a0,8(s0)      the prompter
                0x3c050002,     # lui   a1,0x0002
                0x34a54def,     # ori   a1,a1,0x4def  151023
                0x24060001,     # li    a2,1          yes
                0x00003821,     # move  a3,zero       no
                0x0c0917d8,     # jal   DisplayYesNoMessage
                0x00004821,     # move  t1,zero       no KB
                0x24020005,     # li    v0,5          PROMPT_TO_CREATE
                0xae020010,     # sw    v0,16(s0)
                0xdfbf0010,     # ld    ra,16(sp)
                0xdfb00000,     # ld    s0,0(sp)
                0x03e00008,     # jr    ra
                0x27bd0020))    # addiu sp,sp,32
            e.start_write_word = e.u32(START_WRITE_CALL)
        self.card = dict(zip(CARD_FIELDS,
                             CARDS[flow.sc.get("card") or "blank"]))
        self.fs = None
        self.formatted = 0              # the card, since a FORMAT
        self.saved = 0                  # ... since a SAVE
        self.deferred = None
        self.parent = [None, None]      # the name each popup reports to
        self.animated = [1, 1]          # "popup %d animate" said since Summon
        self.bloom_animated = 1         # "bloom animate", the menu's
        # Each boot starts with no loader, no replay and the objects as the
        # file has them; with no Load/Save or Autosave screen, and with
        # Fred cleared, as the C harness clears it.
        e.put32(AUTOLOAD_INST, 0)
        e.put32(LSW_INST, 0)
        e.put32(AUTOSAVE_INST, 0)
        e.write(FRED, bytes(SAVE_SIZE))
        e.put32(DEMO_REPLAY + 4, 0)
        e.put32(DEMO_REPLAY + 8, 0)
        for chunk, row in zip(e.al_chunks, POPUP_OBJS):
            e.write(chunk, bytes(128))
            e.put32(chunk + 12, row[1])
            e.write(chunk + 52, struct.pack("<f", row[2]))
            e.write(chunk + 60, struct.pack("<f", row[3]))
            e.put32(chunk + 84, row[4])
            e.put32(chunk + 92, row[5])
        e.write(e.al_font + 1056, struct.pack("<f", FONT_HEIGHT))
        # FlailerScreenList's constructor makes both popups.
        self.popups = [e.alloc(POPUP_SIZE), e.alloc(POPUP_SIZE)]
        for p in self.popups:
            e.write(p, bytes(POPUP_SIZE))
            self.run(POPUP_CTOR, p)

    # -- the popup screen's objects -------------------------------------------
    def obj_index(self, screen, obj):
        if screen != POPUP_SCREEN:
            return -1
        for i, row in enumerate(POPUP_OBJS):
            if row[0] == obj:
                return i
        return -1

    def chunk_obj(self, chunk):
        return POPUP_OBJS[self.e.al_chunks.index(chunk)][0]

    def popup_index(self, p):
        return self.popups.index(p)

    # -- the card ---------------------------------------------------------------
    def fs_error(self, v=None):
        e = self.e
        if v is not None:
            e.put32(self.fs["obj"] + FS_LAST_ERROR, v)
        return s32(e.u32(self.fs["obj"] + FS_LAST_ERROR))

    def service(self, e):
        """cDBFileSys::Service: the hook in front of the trampoline."""
        fs, card, f = self.fs, self.card, self.flow
        f.say("fs service %d %d" % (s32(e.reg[5]), s32(e.reg[6])))
        e.reg[25] = 0
        if not fs["job"]:
            if fs["pump"] > 0:
                fs["pump"] -= 1
                self.fs_error(FS_IN_PROGRESS if fs["pump"] > 0
                              else card["settle"])
            return
        fs["left"] -= 1
        if fs["left"] > 0:
            return
        job = fs["job"]
        if job == FS_VERIFY:
            if self.formatted:
                err = 0
            elif fs["verifies"] > 0 and card["verify2"] >= 0:
                err = card["verify2"]
            else:
                err = card["verify"]
            fs["verifies"] += 1
        elif job == FS_CHECK:
            if self.saved:
                err = 0
            elif self.formatted:
                err = 5
            elif fs["checks"] > 0 and card["check2"] >= 0:
                err = card["check2"]
            else:
                err = card["check"]
            fs["checks"] += 1
            e.put32(fs["obj"] + FS_FILE_EXISTS, 1 if err == 0 else 0)
        elif job == FS_SAVE:
            # What went to the card: Fred's size, its Autosave word and its
            # checksum.
            err = card["save"]
            if err == 0 and fs["data"] and fs["size"] >= SAVE_SIZE:
                d = fs["data"]
                f.say("fs saved %08x %08x %08x"
                      % (e.u32(d), e.u32(d + FRED_AUTOSAVE),
                         e.u32(d + CHECKSUM_OFFSET)))
                self.saved = 1
        elif job == FS_FORMAT:
            err = card["format"]
            if err == 0:
                self.formatted = 1
        elif job == FS_LOAD:
            err = card["load"]
            if err == 0 and fs["data"] and fs["size"] >= SAVE_SIZE:
                good = card["goodSum"]
                if good not in SAVES:
                    SAVES[good] = save_image(good)
                e.write(fs["data"], SAVES[good])
        else:
            err = 0
        self.fs_error(err)
        fs["job"] = 0
        f.say("fs done %d" % err)
        done, fs["done"] = fs["done"], 0
        if done:
            e.reg[25] = done
            e.reg[4] = fs["param"]

    def stubs(self):
        e, f = self.e, self.flow

        def arg(i):
            return e.reg[4 + i] & 0xffffffff

        def chunk_of(screen, obj, kind):
            i = self.obj_index(screen, obj)
            return e.al_chunks[i] if i >= 0 and kind in (0, 1) else 0

        # -- cDBFileSys ----------------------------------------------------
        def fs_new(_e):                    # the constructor, 0x0012dee0
            f.say("fs new")
            obj = arg(0)
            e.put32(obj + FS_VTABLE, e.al_vtbl)
            e.put32(obj + FS_FILE_EXISTS, 0)
            self.fs = dict(obj=obj, pump=self.card["pump"], job=0, left=0,
                           checks=0, verifies=0, done=0, param=0, data=0,
                           size=0)
            self.fs_error(FS_ERROR)
            return obj

        def fs_delete(_e):
            f.say("fs delete")

        def fs_file(_e):
            name = _cstr(e, arg(1))
            f.say("fs file %s %d" % (name if name is not None else "(null)",
                                     s32(arg(3))))
            self.fs["data"], self.fs["size"] = arg(2), s32(arg(3))

        def fs_calc(_e):
            size = s32(arg(1))
            f.say("fs calc %d" % size)
            return (size + 1023) // 1024 + 5

        def fs_free(_e):
            free = 8192 if self.formatted else self.card["freeKB"]
            f.say("fs free %d" % free)
            return free

        def fs_state(_e):
            f.say("fs state %d" % s32(arg(1)))
            if self.card["refuse"] or self.fs["job"]:
                return 0
            self.fs.update(job=s32(arg(1)), left=self.card["busy"],
                           done=arg(2), param=arg(3))
            self.fs_error(FS_IN_PROGRESS)
            return 1

        # -- the Flailer ------------------------------------------------------
        def screen_visibility(_e):         # SetFlailerScreenVisibility
            # FlailerScreenVisibility: VISIBLE is 0, INVISIBLE is 1
            f.screen_visible(arg(0), 1 if arg(1) == 0 else 0)

        def set_color(_e):                 # FlailerSetTextColor
            screen, obj, color = arg(0), arg(1), arg(2)
            f.say("color %08x %08x %08x" % (screen, obj, color))
            c = chunk_of(screen, obj, 1)
            if c:
                e.put32(c + 92, color)

        def printf(_e):                    # FlailerPrintf: only ever ""
            f.say("text %08x %08x %s" % (arg(0), arg(1), _cstr(e, arg(2))))

        def set_language_id(_e):
            f.say("language id %08x %08x %d" % (arg(0), arg(1), s32(arg(2))))

        def set_top_left_y(_e):            # FlailerSetTopLeftY(screen, obj, int)
            screen, obj, y = arg(0), arg(1), s32(arg(2))
            f.say("pos y %08x %08x %d" % (screen, obj, y))
            c = chunk_of(screen, obj, 0)
            if c:
                e.write(c + 52, struct.pack("<f", float(y)))

        def by_group(_e):                  # FindFlailerObjectByGroup
            screen, group, kind, after = arg(0), arg(1), s32(arg(2)), arg(3)
            if screen != POPUP_SCREEN or kind not in (0, 1):
                return 0
            start = e.al_chunks.index(after) + 1 if after else 0
            for i in range(start, len(POPUP_OBJS)):
                if POPUP_OBJS[i][1] == group:
                    return e.al_chunks[i]
            return 0

        def set_visibility(_e):            # FlailerObjectChunk::SetVisibility
            f.object_visible(POPUP_SCREEN, self.chunk_obj(arg(0)), s32(arg(1)))

        def set_string(_e):                # FlailerTextChunk::SetString
            f.say("text %08x %08x %s" % (POPUP_SCREEN, self.chunk_obj(arg(0)),
                                         _cstr(e, arg(1))))

        def translate(_e):                 # GetTranslatedString
            buf = e.al_text[0]
            e.al_text.reverse()
            e.write(buf, translated(s32(arg(0))).encode() + b"\0")
            return buf

        # -- the highlight -----------------------------------------------------
        # A popup's, at +108, or the Load/Save menu's, which says less.
        def is_popup(this):
            return this - 108 in self.popups

        def bloom_init(_e):                # tHighlightAnimation(screen, obj, color)
            if not is_popup(arg(0)):
                f.say("bloom init %08x %08x %08x" % (arg(1), arg(2), arg(3)))
                self.bloom_animated = 0
            return arg(0)

        def bloom_item(_e):                # tHighlightAnimation::SetCurrentMenuItem
            if not is_popup(arg(0)):
                f.say("bloom item %08x" % arg(1))
                self.bloom_animated = 0
                return
            p = arg(0) - 108
            f.say("popup %d bloom %08x %08x"
                  % (self.popup_index(p), e.u32(arg(0)), arg(1)))

        def bloom_animate(_e):             # tHighlightAnimation::Animate
            if not is_popup(arg(0)):
                if not self.bloom_animated:
                    f.say("bloom animate")
                self.bloom_animated = 1
                return
            i = self.popup_index(arg(0) - 108)
            if not self.animated[i]:
                f.say("popup %d animate" % i)
            self.animated[i] = 1

        # -- the Load/Save menu's slide, which the port has not ----------------
        def slide_init(_e):                # tSlideOnScreen(screen, a, b, c)
            f.say("slide init %08x %08x %08x %08x"
                  % (arg(1), arg(2), arg(3), e.reg[8] & 0xffffffff))
            return arg(0)

        # -- the Autosave screen's completion callback, the race's end's ------
        def autosave_done(_e):
            f.say("autosave done")
            self.deferred = lambda: f.change_to_screen("New Main Menu", 0)

        def autosave_stay(_e):
            f.say("autosave done")

        # -- the rest ------------------------------------------------------------
        def memset(_e):
            a, v, n = arg(0), arg(1) & 0xff, s32(arg(2))
            e.write(a, bytes([v]) * n)
            return a

        def memcpy(_e):
            d, s_, n = arg(0), arg(1), s32(arg(2))
            e.write(d, e.read(s_, n))
            return d

        def strlen(_e):
            return len(e.read(arg(0), 4096).split(b"\0")[0])

        def move_back(_e):                 # MoveBackScreen(n)
            n = s32(arg(0))
            self.deferred = lambda: f.move_back_screen(n)

        def fred_loaded(_e):               # OverwriteFred's tail, Commit
            f.say("fred loaded %08x %08x %u %d"
                  % (e.u32(FRED), e.u32(FRED + CHECKSUM_OFFSET),
                     e.u32(FRED + FRED_CLEARED),
                     s32(e.u32(FRED + FRED_LANGUAGE))))

        def nothing(_e):
            return None

        stubs = {
            0x0012dee0: fs_new,
            e.al_code + 0: fs_delete,
            e.al_code + 8: fs_file,
            e.al_code + 16: fs_calc,
            e.al_code + 24: fs_free,
            e.al_code + 32: fs_state,
            0x002577c0: lambda _e: e.alloc(max(s32(arg(0)), 16)),  # new
            0x00114e98: nothing,                     # delete
            0x00257c80: lambda _e: e.alloc(128),     # bOMalloc, the items
            0x001836a0: lambda _e: arg(0),           # FrontendDatabase()
            0x00187ba8: nothing,                     # ~FrontendDatabase
            0x0016d0a0: lambda _e: f.movie.stop(),   # StopMovie, retail's
            0x00170320: move_back,
            0x001fe988: nothing,                     # OverwriteFred's calls
            0x001ef120: nothing,
            0x00154308: nothing,
            0x00155000: nothing,
            0x001f4b10: fred_loaded,
            0x0021e560: translate,
            0x0014cbf8: screen_visibility,
            0x0016e038: lambda _e: f.sound(s32(arg(0))),   # MakeFrontendSound
            0x00143f88: set_color,
            0x00143d50: lambda _e: chunk_of(arg(0), arg(1), s32(arg(2))),
            0x00143dd8: by_group,
            0x00140728: set_visibility,
            0x00140e20: set_string,
            0x0013fe18: lambda _e: e.al_font,        # FindFont
            0x00144458: set_top_left_y,
            0x00143e70: printf,
            0x001449a8: set_language_id,
            0x00248870: bloom_init,
            0x002488d0: bloom_item,
            0x00248970: bloom_animate,
            0x00257690: lambda _e: e.alloc(max(s32(arg(0)), 16)),  # bMalloc
            0x0016eb68: screen_visibility,           # FlailerSetScreenVisibility
            0x001ee918: slide_init,
            0x001eead8: lambda _e: f.say("slide appear"),
            0x001eea80: lambda _e: f.say("slide disappear"),
            0x001ee9f8: nothing,                     # tSlideOnScreen::Tick
            0x001ee9a8: nothing,                     # ~tSlideOnScreen
            e.al_done: autosave_done,
            e.al_stay: autosave_stay,
            0x0025a5e0: nothing,                     # bSin, thrown away
            0x00250340: memset,                      # bMemSet
            0x00296ec4: memset,
            0x00250288: memcpy,                      # bMemCpy
            0x00253520: strlen,                      # bStrLen
        }
        for addr, fn in stubs.items():
            e.stub(addr, fn)

        def summon(_e):                    # Summon's entry
            i = self.popup_index(arg(0))
            node = e.u32(arg(1) + 8)
            config = e.u32(node + 16) if node else 0
            self.parent[i] = _cstr(e, e.u32(config + 8)) if config else None
            self.animated[i] = 0
            f.say("popup %d summon" % i)

        def dismiss(_e):                   # Dismiss's entry
            f.say("popup %d dismiss %d %d" % (self.popup_index(arg(0)),
                                              s32(arg(1)), s32(arg(2))))

        def to_parent(reg):                # the jalr to the parent's callback
            def hook(_e):
                name = self.parent[self.popup_index(e.reg[reg] & 0xffffffff)]
                f.say("msg %s %d" % (name or "?", s32(arg(0))))
            return hook

        def unset_garbage(_e):             # at the builders' SummonPopup
            for off in (44, 48, 64):
                e.put32(arg(1) + off, 0)

        def hidden(_e):                    # RenderTextIntoGroup's raw store
            f.object_visible(POPUP_SCREEN, self.chunk_obj(e.reg[3] & 0xffffffff),
                             0)

        def manual(_e):                    # MemcardLoader(this, hash, mode)
            if f.sc.get("manual"):
                e.reg[6] = 0

        def ask_create(_e):                # the `jr t9` StartWrite's jal is to
            inst = e.u32(AUTOSAVE_INST)
            # Only CHECK_IF_CARD_OK's call (state 2) asks; 15 and 16 write.
            asks = (f.sc.get("askCreate") and inst and arg(0) == inst + 8
                    and e.u32(arg(0) + 16) == 2)
            e.reg[25] = e.al_ask if asks else START_WRITE

        e.put32(START_WRITE_CALL, 0x0c000000 | (e.al_save >> 2))
        hooks = {
            e.al_save: ask_create,
            e.al_svc: self.service,
            POPUP_SUMMON: summon,
            POPUP_DISMISS: dismiss,
            0x0016b7c8: to_parent(17),     # Summon's, s1 the popup
            0x0016ba24: to_parent(16),     # Dismiss's, s0
            0x0016bc70: to_parent(17),     # HandleJoy's, s1
            0x00245f44: unset_garbage,     # DisplayMessage
            0x002460bc: unset_garbage,     # DisplayYesNoMessage
            0x00144dd8: hidden,
            LOADER_CTOR: manual,
        }
        for addr, fn in hooks.items():
            e.hook(addr, fn)

    def unhook(self):
        for addr in (self.e.al_svc, POPUP_SUMMON, POPUP_DISMISS, 0x0016b7c8,
                     0x0016ba24, 0x0016bc70, 0x00245f44, 0x002460bc,
                     0x00144dd8, LOADER_CTOR, self.e.al_save):
            self.e.hooks.pop(addr, None)
        self.e.put32(START_WRITE_CALL, self.e.start_write_word)

    def run(self, addr, *args):
        e, f = self.e, self.flow
        # The stubs are this class's only while it runs: the language screen
        # calls MoveBackScreen, the new and delete it stubs are its own, and so
        # on.
        saved = dict(e.stubs)
        self.stubs()
        e.put32(REAL_TIMER, f.real_timer)
        e.write(REAL_ELAPSED, struct.pack("<f", f.real_elapsed))
        e.put32(DEMO_DISC, 0)
        # TheFlailerScreenList, as far as this code reads it: the popups and
        # pCurrent, whose config names the screen and holds its callback.
        name = (f.screen[0] if f.screen else "").encode() + b"\0"
        e.write(e.al_name, name)
        e.put32(e.al_config + 8, e.al_name)
        e.put32(e.al_config + 12, self.CALLBACKS.get(f.screen[2], 0)
                if f.screen else 0)
        e.put32(e.al_node + 16, e.al_config)
        e.put32(e.al_list + 392, self.popups[0])
        e.put32(e.al_list + 396, self.popups[1])
        e.put32(e.al_list + 412, e.al_node if f.screen else 0)
        e.put32(SCREEN_LIST, e.al_list)
        self.deferred = None
        try:
            r = e.call(addr, *args, limit=2000000)
        finally:
            self.unhook()
            e.stubs.clear()
            e.stubs.update(saved)
        if self.deferred:
            d, self.deferred = self.deferred, None
            d()
        return r

    # The screens this class runs, by kind: BootAutoload, Options' Load/Save
    # and the race's end's Autosave.
    CALLBACKS = {"autoload": AUTOLOAD_CALLBACK, "loadsave": LSW_CALLBACK,
                 "autosave": AUTOSAVE_CALLBACK}

    def callback(self, msg, data, kind="autoload"):
        e = self.e
        # ScreenCallbackData: ItemHash, Port, Param, Noise.
        d = e.al_data
        e.put32(d + 0, data["itemHash"])
        e.put32(d + 4, data["port"])
        e.put32(d + 8, data["param"])
        e.put32(d + 12, data["noise"])
        self.run(self.CALLBACKS[kind], msg, d)
        data["param"] = s32(e.u32(d + 8))
        data["noise"] = e.u32(d + 12)

    # FlailerScreenList::Tick's share (0x0016cca8): both popups, up or not.
    def tick_popups(self):
        for p in self.popups:
            self.run(POPUP_TICK, p)

    # JoyHandler's share (0x0016cab0): every popup that is up and listening
    # to the port hears the event, and then the screen does not.
    def joy(self, port, ev, pressed=1):
        e = self.e
        taken = 0
        for p in self.popups:
            if not e.u32(p):
                continue
            jp = s32(e.u32(p + 60))
            if jp != port and jp != -1:
                continue
            self.run(POPUP_JOY, p, port, ev, pressed)
            taken = 1
        return taken


# ----------------------------------------------------- retail's panel movie

START_MOVIE = 0x0016ce30                # FlailerScreenList::StartMovie
UPDATE_MOVIE = 0x0016d028               # ... UpdateMovie
STOP_MOVIE = 0x0016d0a0                 # ... StopMovie
IN_GAME = RETAIL_GP - 21424             # InGameFlag
NUM_DEMO_TRACKS = RETAIL_GP - 21168     # NumDemoableTracks
MAINMENU_MOVIE = 0x002bc430             # "MOVIES\\mainmenu_movie.AVI"
OPTIONS_MOVIE = 0x002ba010              # "MOVIES\\options_movie_new.AVI"


class RetailMovie(object):
    """FlailerScreenList's movie, retail's, on the emulated image.

    StartMovie, UpdateMovie and StopMovie run as they are, on the list's
    +460..+484 -- RetailAutoload's list, since there is one. Stubbed:
    GetTextureInfo, whose six answers are one fake TextureInfo with +144 set,
    so that +460, the gate, is; and TheMoviePlayer's Close, InitFile and
    Update, onto the world's panel movie.

    A run keeps every register, so another class's stub can make one in the
    middle of retail code: BootAutoLoader's constructor and StartDemoMode
    call StopMovie that way.
    """

    def __init__(self, flow):
        self.flow = flow
        e = self.e = retail_emu()
        if not getattr(e, "mv_info", 0):
            e.mv_info = e.alloc(256)
            e.put32(e.mv_info + 144, 1)
        # Each boot starts with no movie.
        e.write(e.al_list + 460, bytes(28))

    def stubs(self):
        e, f = self.e, self.flow

        def init_file(_e):                 # MoviePlayer::InitFile
            f.panel_open(_cstr(e, e.reg[5] & 0xffffffff))

        stubs = {
            0x001abf48: lambda _e: e.mv_info,         # GetTextureInfo
            0x00237fc8: lambda _e: f.movie_close(),   # MoviePlayer::Close
            0x00237ad8: init_file,                    # its answer unread
            0x002380a8: lambda _e: f.panel_update(),  # MoviePlayer::Update
        }
        for addr, fn in stubs.items():
            e.stub(addr, fn)
        # ... and the three themselves, which the callers' stubs run here
        for addr in (START_MOVIE, UPDATE_MOVIE, STOP_MOVIE):
            e.stubs.pop(addr, None)

    def run(self, addr, *args):
        e, f = self.e, self.flow
        kept = (list(e.reg), list(e.fpr), e.hi, e.lo, e.hi1, e.lo1, e.sa,
                e.fcc, e.limit, e.icount)
        saved = dict(e.stubs)
        self.stubs()
        e.put32(SKIP_MOVIES, f.skip_movies)
        e.put32(IN_GAME, f.in_game)
        try:
            e.call(addr, e.al_list, *args, limit=100000)
        finally:
            e.stubs.clear()
            e.stubs.update(saved)
            e.reg[:] = kept[0]
            e.fpr[:] = kept[1]
            (e.hi, e.lo, e.hi1, e.lo1, e.sa, e.fcc, e.limit,
             e.icount) = kept[2:]

    def start(self, name):
        self.run(START_MOVIE, name)

    def update(self):
        self.run(UPDATE_MOVIE)

    def stop(self):
        self.run(STOP_MOVIE)



# ------------------------------------------------------ retail's main menu

MAIN_MENU_CALLBACK = 0x00216a10         # NewMainMenu::Callback
MAIN_MENU_INST = RETAIL_GP - 16132      # its pInstance
COPS_ON = FRED + 32                     # Fred.MainMenuOpts.mPolice
EASTER_EGGS = 0x0031d7e8                # TheEasterEggs, the port's name
MI_UNDERSCORE = 0x32c91dae              # the bracket under the item
MI_OVERSCORE = 0xc671680c               # and over it
# The box FlailerGetBoundingBox answers for every mask: the brackets are
# said relative to it, as the offsets the port hands its hook.
HL_TOP, HL_BOTTOM = 100, 140


class RetailMainMenu(object):
    """NewMainMenu, retail's, on the emulated image.

    Callback (0x00216a10), the constructor (0x00216460), the destructor
    (0x00216598), HandleEvent (0x00216638) and OnTick (0x00216718) run as
    they are, and GetPopupActiveState on RetailAutoload's list. StartMovie
    runs as RetailMovie runs it. TheEasterEggs' Start and Stop are the
    port's "eggs 1" and "eggs 0", FlailerSetGroupVisibility its "vis group",
    and ChangeToScreen, tail-called, is deferred to the flow, as the title's
    is.

    The four members are the port's animation kit, which banim_check
    holds to retail's on its own. Here their calls are said as the port
    traces them:
      - the constructors: "blurb init" (the screen and three objects),
        "bloom init" (the screen, the object and the colour) and "slide in"
        (the screen, the object FlailerGetTopLeftX measured, and the X it
        answered, 0.0 as the harness's world does); SelectionSet's is
        silent, and AddItems is "sel items", with the IndicatorMode the
        constructor stored and the table's entries;
      - the destructors, silent but tAnimatedBlurb's, the last, which is
        "menu kit released";
      - the three Animates in OnTick, "menu animate" once a constructor;
      - OnHighlight's first call, the bloom's SetCurrentMenuItem, "bloom
        item";
      - jukebox Start(1), "jukebox 1".
    Stubbed silently, because the port owes them:
      - FrontendDatabase::MakeChallengeCarsAvailable and
        RaceParameters::InitWithDefaults;
      - ConsiderStartDemoMode in OnTick. StartDemoMode has no race in the
        port yet, so all it could do there is stop the menu's movie. Without
        this stub, half a minute on the main menu would start attract mode
        here and not in the port; `menuidle` spends forty seconds there.
    tHelpMenu::IsActive answers 0: no help menu is ported. The rest of
    OnTick shows the Easter egg group only once TheEasterEggs' +4 is set,
    and nothing sets it here, as nothing hands it the pad. Were it reached,
    its sound and FlailerSetLanguageID would show in the transcript.

    HighlightMenuItem runs. FlailerGetBoundingBox answers the same box for
    any mask (HL_TOP, HL_BOTTOM), and the two SetTopLeftYs are said as one
    "brackets" line, each bracket's Y less the edge it was put against --
    the offsets, as the port's moveBrackets hook takes them. NewText is its
    "blurb" and SelectionSet::SetCurrentItem its "bracket" trace.

    CopsOn is Fred's +32. The flow's is put in before each run and read
    back after, so the flow's is the one "final" prints.
    """

    def __init__(self, flow):
        self.flow = flow
        e = self.e = retail_emu()
        if not getattr(e, "mm_inst", 0):
            e.mm_inst = e.alloc(640)
            e.mm_data = e.alloc(16)
        # Each boot starts with no main menu and no egg unlocked.
        e.put32(MAIN_MENU_INST, 0)
        e.write(EASTER_EGGS, bytes(12))
        self.pending = None
        self.hl_mask, self.hl_under = 0, 0.0
        self.top_left_obj, self.animated = 0, 0

    def stubs(self):
        e, f = self.e, self.flow

        def arg(i):
            return e.reg[4 + i] & 0xffffffff

        def change_to_screen(_e):          # ChangeToScreen, tail-called
            self.pending = (_cstr(e, arg(0)), arg(1))

        def set_group(_e):                 # FlailerSetGroupVisibility
            f.say("vis group %08x %08x %d" % (arg(0), arg(1), arg(2)))

        def language_id(_e):               # FlailerSetLanguageID
            f.say("language id %08x %08x %08x" % (arg(0), arg(1), arg(2)))

        def bounding_box(_e):              # FlailerGetBoundingBox
            # Ints, as HighlightMenuItem converts them with cvt.s.w: left,
            # top, right and bottom through a2, a3, t0 and t1.
            self.hl_mask = arg(1)
            for i, v in ((2, 0), (3, HL_TOP), (4, 0), (5, HL_BOTTOM)):
                e.put32(arg(i), v)

        def top_left_y(_e):                # FlailerSetTopLeftY
            y = e.f(12)
            if arg(1) == MI_UNDERSCORE:
                self.hl_under = y - HL_BOTTOM
            elif arg(1) == MI_OVERSCORE:
                f.say("brackets %08x %08x %.1f %.1f"
                      % (arg(0), self.hl_mask, self.hl_under, y - HL_TOP))
            else:
                f.say("top left y %08x %08x %.1f" % (arg(0), arg(1), y))

        def new_text(_e):                  # tAnimatedBlurb::NewText
            # The blurb is the instance's +4; +0 is the screen.
            f.say("blurb %08x %d" % (e.u32(arg(0) - 4), arg(1)))

        def blurb_ctor(_e):                # tAnimatedBlurb(screen, 3 objects)
            self.animated = 0
            f.say("blurb init %08x %08x %08x %08x"
                  % (arg(1), arg(2), arg(3), arg(4)))

        def top_left_x(_e):                # FlailerGetTopLeftX
            self.top_left_obj = arg(1)
            e.set_f(0, 0.0)

        def slide_in(_e):                  # tSlideInAnimation(screen, x)
            f.say("slide in %08x %08x %.1f"
                  % (arg(1), self.top_left_obj, e.f(12)))

        def add_items(_e):                 # SelectionSet::AddItems
            # IndicatorMode is SelectionSet's +144.
            f.say("sel items %08x mode %d %s"
                  % (arg(1), s32(e.u32(arg(0) + 144)),
                     " ".join("%08x" % e.u32(arg(2) + 4 * i)
                              for i in range(s32(arg(3))))))

        def animate(_e):                   # the three Animates, once
            if not self.animated:
                f.say("menu animate")
            self.animated = 1

        silent = (
            0x002488b0,                    # ~tHighlightAnimation
            0x001b9ae0,                    # ~tSlideInAnimation
            0x0016e120, 0x0016e168,        # SelectionSet, ~
            0x0016ed50,                    # ConsiderStartDemoMode
        )
        stubs = {addr: (lambda _e: None) for addr in silent}
        stubs.update({
            0x00183af8: lambda _e: f.say("challenge cars"),
            0x001ed5c8: lambda _e: f.say("race defaults"),
            0x002491b0: blurb_ctor,
            0x00249280: lambda _e: f.say("menu kit released"),
            0x00248870: lambda _e: f.say(            # tHighlightAnimation()
                "bloom init %08x %08x %08x" % (arg(1), arg(2), arg(3))),
            0x00144140: top_left_x,
            0x00248fd0: slide_in,
            0x0016e1f8: add_items,
            0x001aeab0: lambda _e: f.say("jukebox %d" % arg(0)),
            0x00249348: animate,           # the Animates: blurb, bloom,
            0x00248970: animate,           # slide-in
            0x00248d20: animate,
            0x002488d0: lambda _e: f.say(            # SetCurrentMenuItem
                "bloom item %08x" % arg(1)),
            0x002577c0: lambda _e: e.mm_inst,          # operator new
            0x00114e98: lambda _e: None,               # operator delete
            START_MOVIE: lambda _e: f.movie.start(arg(1)),
            0x0024f488: lambda _e: f.say("eggs 1"),    # TheEasterEggs.Start
            0x0024f610: lambda _e: f.say("eggs 0"),    # ... Stop
            0x001454e8: set_group,
            0x0014cc78: change_to_screen,
            0x001e4170: lambda _e: 0,                  # tHelpMenu::IsActive
            0x0016e038: lambda _e: f.sound(arg(0)),    # MakeFrontendSound
            0x001449a8: language_id,
            0x0024f968: lambda _e: f.say("eggs 0024f968"),
            0x00144280: bounding_box,
            0x001b9ae8: top_left_y,
            0x002494e8: new_text,
            0x0016e270: lambda _e: f.say("bracket %08x" % arg(1)),
        })
        for addr, fn in stubs.items():
            e.stub(addr, fn)
        # GetPopupActiveState runs, on the list RetailAutoload keeps.
        e.stubs.pop(0x0016ce00, None)

    def callback(self, msg, data):
        e, f = self.e, self.flow
        saved = dict(e.stubs)
        self.stubs()
        e.put32(REAL_TIMER, f.real_timer)
        e.put32(COPS_ON, f.cops_on)
        e.put32(e.al_list + 392, f.autoload.popups[0])
        e.put32(e.al_list + 396, f.autoload.popups[1])
        e.put32(SCREEN_LIST, e.al_list)
        # ScreenCallbackData: ItemHash, Port, Param, Noise.
        d = e.mm_data
        e.put32(d + 0, data["itemHash"])
        e.put32(d + 4, data["port"])
        e.put32(d + 8, data["param"])
        e.put32(d + 12, data["noise"])
        self.pending = None
        try:
            e.call(MAIN_MENU_CALLBACK, msg, d, limit=200000)
        finally:
            e.stubs.clear()
            e.stubs.update(saved)
        data["param"] = s32(e.u32(d + 8))
        data["noise"] = e.u32(d + 12)
        f.cops_on = e.u32(COPS_ON)
        if self.pending:
            p, self.pending = self.pending, None
            f.change_to_screen(*p)


# ------------------------------------------ retail's UnlaunchFrontendMenus

UNLAUNCH = 0x0016fa80                   # UnlaunchFrontendMenus
GAME_TYPE = FRED + 0x1072c              # Fred.GameType (0x0030c77c)
RACE_PARAMS = 0x0031a898                # TheRaceParameters
LAUNCH_TYPE = RETAIL_GP - 21132         # FrontendLaunchType


def _nested(e, fn):
    """fn, which may run retail code of its own, with every register kept
    for the run it was called from."""
    kept = (list(e.reg), list(e.fpr), e.hi, e.lo, e.hi1, e.lo1, e.sa,
            e.fcc, e.limit, e.icount)
    try:
        fn()
    finally:
        e.reg[:] = kept[0]
        e.fpr[:] = kept[1]
        (e.hi, e.lo, e.hi1, e.lo1, e.sa, e.fcc, e.limit,
         e.icount) = kept[2:]


class RetailUnlaunch(object):
    """UnlaunchFrontendMenus (0x0016fa80), retail's, on the emulated image.

    It runs as it is, and so do PopUntil and PopScreens, on RetailAutoload's
    list with the Flow's stack copied into its first 388 bytes, over
    Fred.GameType and TheRaceParameters' AIDemoMode (+24) and ReplayDemoMode
    (+28) from the scenario: raceDemo 1 is the first, 2 the second.
    Stubbed: ScreenStack::Print, a debug dump; Pop, the Flow's, which says
    so, with the copy kept in step; ChangeToScreen, the Flow's;
    SetMainScreen, not ported; jukebox::Stop, "jukebox 0" as the port's hook
    says it; StopMovie, RetailMovie's, after "unlaunch" and the launch type
    the store before it left; and tNewSongMonitor::Reset, "song monitor
    reset". The tHelpMenu at +452 is NULL: the port has none.
    """

    def __init__(self, flow):
        self.flow = flow
        self.e = retail_emu()

    def run(self, game_type, demo):
        e, f = self.e, self.flow
        lst = e.al_list

        def arg(i):
            return e.reg[4 + i] & 0xffffffff

        def pop(_e):                       # ScreenStack::Pop
            if e.u32(arg(0) + 384) == 0:
                return 0
            f.pop()
            e.put32(arg(0) + 384, f.index)
            return arg(0) + NAME_LEN * f.index

        def change(_e):                    # ChangeToScreen
            name = _cstr(e, arg(1)) if arg(1) else None
            push = arg(2)
            _nested(e, lambda: f.change_to_screen(name, push))

        def stop_movie(_e):                # StopMovie, after the store
            f.frontend_launch_type = s32(e.u32(LAUNCH_TYPE))
            f.say("unlaunch %d" % f.frontend_launch_type)
            _nested(e, f.movie.stop)

        for i in range(STACK_DEPTH):
            name = f.names[i].encode()[:NAME_LEN - 1]
            e.write(lst + NAME_LEN * i, name + bytes(NAME_LEN - len(name)))
        e.put32(lst + 384, f.index)
        e.put32(lst + 452, 0)
        e.put32(SCREEN_LIST, lst)
        e.put32(GAME_TYPE, game_type & 0xffffffff)
        e.put32(RACE_PARAMS + 24, 1 if demo == 1 else 0)
        e.put32(RACE_PARAMS + 28, 1 if demo == 2 else 0)
        e.put32(LAUNCH_TYPE, 0xdeadbeef)

        stubs = {
            0x0016b470: lambda _e: None,                  # ScreenStack::Print
            0x0016b438: pop,
            0x0016c4c0: change,
            0x0016c3a8: lambda _e: None,                  # SetMainScreen
            0x001aec90: lambda _e: f.say("jukebox 0"),    # jukebox::Stop
            STOP_MOVIE: stop_movie,
            0x0016bde8: lambda _e: f.say("song monitor reset"),
        }
        saved = dict(e.stubs)
        for addr, fn in stubs.items():
            e.stub(addr, fn)
        try:
            e.call(UNLAUNCH, limit=100000)
        finally:
            e.stubs.clear()
            e.stubs.update(saved)
        if e.u32(lst + 384) != f.index:
            f.say("unlaunch stack %d, the flow's %d"
                  % (e.u32(lst + 384), f.index))


SIXTIETH = 1.0 / 60.0

# BootAutoload takes 365 frames at 1/60 and 8 at a second a frame on a blank
# card; the rows written before it ran add them. See BOOT60 in the C harness.
BOOT60, BOOT1 = 365, 8


def card_row(name, frames, dt=1.0, **kw):
    """A row for the card and replay scenarios: NTSC, movies skipped."""
    row = dict(name=name, videoMode=1, currLanguage=0, skipMovies=1,
               frontendLaunchType=1, demoModeStatus=0,
               haveIntroMovie=0, frames=frames, dt=dt, input=[])
    row.update(kw)
    return row


def save_row(name, frames, input, **kw):
    """A row for the saver: back from a race with a demo waiting, so on the
    main menu with no BootAutoload, at a second a frame."""
    return card_row(name, frames, frontendLaunchType=2, demoModeStatus=2,
                    input=input, **kw)


# Same rows as kScenarios[] in tools/src/gameflow_test.c.
SCENARIOS = [
    dict(name="ntsc", videoMode=1, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0,
         haveIntroMovie=0, frames=BOOT60 + 40, dt=SIXTIETH, input=[]),
    dict(name="pal", videoMode=0, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0,
         haveIntroMovie=0, frames=BOOT60 + 40, dt=SIXTIETH, input=[]),
    dict(name="nolang", videoMode=1, currLanguage=-1, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0,
         haveIntroMovie=0, frames=BOOT60 + 40, dt=SIXTIETH,
         input=[(BOOT60 + 10, "back"), (BOOT60 + 14, "item5")]),
    dict(name="skipmovies", videoMode=1, currLanguage=0, skipMovies=1,
         frontendLaunchType=1, demoModeStatus=0,
         haveIntroMovie=0, frames=BOOT60 + 30, dt=SIXTIETH, input=[]),
    dict(name="relaunch", videoMode=1, currLanguage=0, skipMovies=0,
         frontendLaunchType=2, demoModeStatus=2,
         haveIntroMovie=0, frames=20, dt=SIXTIETH, input=[(10, "back")]),
    dict(name="attract", videoMode=1, currLanguage=0, skipMovies=1,
         frontendLaunchType=1, demoModeStatus=0,
         haveIntroMovie=0, frames=BOOT1 + 40, dt=1.0, input=[]),
    dict(name="select", videoMode=1, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0,
         haveIntroMovie=0, frames=BOOT60 + 300, dt=SIXTIETH,
         input=[(BOOT60 + 14, "select"), (BOOT60 + 20, "back"), (BOOT60 + 260, "back"),
                (BOOT60 + 270, "select"), (BOOT60 + 282, "select"),
                (BOOT60 + 288, "back"), (BOOT60 + 292, "back")]),
    dict(name="skipintro", videoMode=1, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0,
         haveIntroMovie=1, frames=BOOT60 + 300, dt=SIXTIETH,
         input=[(BOOT60 + 5, "select"), (BOOT60 + 10, "select"), (BOOT60 + 20, "select"),
                (BOOT60 + 21, "start"), (BOOT60 + 262, "select")]),
    dict(name="skipidle", videoMode=1, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0,
         haveIntroMovie=1, frames=BOOT1 + 50, dt=1.0, input=[(BOOT1 + 10, "select")]),
    dict(name="restidle", videoMode=1, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0,
         haveIntroMovie=0, frames=BOOT1 + 50, dt=1.0, input=[]),
    dict(name="mainmenu", videoMode=1, currLanguage=0, skipMovies=1,
         frontendLaunchType=1, demoModeStatus=0,
         haveIntroMovie=0, frames=BOOT60 + 280, dt=SIXTIETH,
         input=[(BOOT60 + 250, "select"), (BOOT60 + 254, "item3"),
                (BOOT60 + 258, "back"), (BOOT60 + 262, "item1")]),
    dict(name="leavefe", videoMode=1, currLanguage=0, skipMovies=1,
         frontendLaunchType=1, demoModeStatus=0,
         haveIntroMovie=0, frames=BOOT60 + 270, dt=SIXTIETH,
         input=[(BOOT60 + 250, "select"), (BOOT60 + 254, "item1"),
                (BOOT60 + 260, "race")]),
] + [
    dict(name="leavegt%s%s" % (str(gt).replace("-", "m"), "d%d" % d if d else ""),
         videoMode=1, currLanguage=0, skipMovies=1,
         frontendLaunchType=1, demoModeStatus=0,
         haveIntroMovie=0, frames=BOOT60 + 270, dt=SIXTIETH,
         gameType=gt, raceDemo=d,
         input=[(BOOT60 + 250, "select"), (BOOT60 + 254, "item1"),
                (BOOT60 + 256, "pushvet"), (BOOT60 + 257, "pushqr"),
                (BOOT60 + 260, "race")])
    for gt, d in ((-1, 0), (1, 0), (2, 0), (5, 0), (7, 0), (8, 0), (9, 0),
                  (10, 0), (2, 1), (8, 2), (0, 1))
] + [
    dict(name="mumbo", videoMode=1, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0,
         haveIntroMovie=0, frames=BOOT60 + 30, dt=SIXTIETH, input=[(BOOT60 + 12, "mumbo")]),
    # The same with the two dead predicates turned on, so the legal and
    # anti-piracy panels and their 7-second timers actually run.
    dict(name="legal", videoMode=1, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0,
         haveIntroMovie=0, forceLegal=1, frames=BOOT1 + 40, dt=1.0,
         input=[(BOOT1 + 5, "mumbo")]),
    dict(name="french", videoMode=1, currLanguage=1, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0,
         haveIntroMovie=0, frames=BOOT60 + 30, dt=SIXTIETH, input=[]),
    dict(name="palselect", videoMode=0, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0,
         haveIntroMovie=0, frames=BOOT60 + 30, dt=SIXTIETH, input=[(BOOT60 + 8, "item2")]),
    dict(name="palback", videoMode=0, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0,
         haveIntroMovie=0, frames=BOOT60 + 30, dt=SIXTIETH,
         input=[(BOOT60 + 7, "hl4"), (BOOT60 + 8, "back")]),
    dict(name="palall", videoMode=0, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0,
         haveIntroMovie=0, frames=BOOT60 + 30, dt=SIXTIETH, input=[(BOOT60 + 8, "item7")]),
    dict(name="palsame", videoMode=0, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0,
         haveIntroMovie=0, frames=BOOT60 + 30, dt=SIXTIETH, input=[(BOOT60 + 8, "item1")]),
    dict(name="palrevert", videoMode=0, currLanguage=1, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0,
         haveIntroMovie=0, frames=BOOT60 + 30, dt=SIXTIETH, input=[(BOOT60 + 8, "item1")]),

    # BootAutoload's card, NTSC with the movies skipped, at a second a frame
    # unless the row says otherwise. See kScenarios[] for each.
    card_row("good", 20, currLanguage=1, card="good"),
    card_row("badsum", 20, card="badsum"),
    card_row("loaderr", 20, card="loaderr"),
    card_row("nocard", 16, card="nocard", input=[(4, "select")]),
    card_row("unformatted", 16, card="unformatted"),
    card_row("newcard", 16, card="newcard"),
    card_row("fullno", 16, card="full",
             input=[(7, "up"), (7, "down"), (7, "back"), (8, "select")]),
    card_row("fullyes", 24, card="full",
             input=[(7, "left"), (8, "select"), (13, "left"), (13, "left"), (14, "start")]),
    card_row("tight", 16, card="tight"),
    card_row("checkerr", 16, card="checkerr",
             input=[(7, "right"), (8, "select")]),
    card_row("busy", 20, card="busy"),
    card_row("slow", 24, card="slow"),
    card_row("refuse", 12, card="refuse"),
    card_row("goodslow", 400, dt=SIXTIETH, card="good"),
    card_row("manualno", 14, card="good", manual=1, input=[(7, "select")]),
    card_row("manualyes", 24, card="good", manual=1,
             input=[(7, "left"), (8, "select")]),
    card_row("manualhalf", 40, dt=0.5, card="good", manual=1,
             input=[(9, "left"), (10, "select")]),
    card_row("manualgone", 20, card="gone", manual=1,
             input=[(7, "left"), (8, "select")]),
    card_row("manualswap", 20, card="swapped", manual=1,
             input=[(7, "left"), (8, "select")]),
    card_row("manualpull", 20, card="pulled", manual=1,
             input=[(7, "left"), (8, "select"), (12, "select")]),
    card_row("manualbad", 24, card="badsum", manual=1,
             input=[(7, "left"), (8, "select"), (16, "select")]),
    card_row("manualnocard", 20, card="nocard", manual=1,
             input=[(6, "left"), (7, "select"), (11, "select")]),
    card_row("manualnone", 14, manual=1),
    # ConsiderStartDemoMode: a replay to show.
    card_row("replay", BOOT1 + 44, replays=1),
    # The menus' movie: its loops, the same name again, another in its
    # place, and the title's movie sharing its player.
    card_row("menumovie", BOOT60 + 500, dt=SIXTIETH, skipMovies=0,
             input=[(BOOT60 + 270, "select"), (BOOT60 + 480, "ingame"),
                    (BOOT60 + 490, "outgame")]),
    card_row("menuagain", BOOT60 + 400, dt=SIXTIETH, skipMovies=0,
             input=[(BOOT60 + 270, "select"), (BOOT60 + 274, "item3"),
                    (BOOT60 + 278, "back"), (BOOT60 + 290, "optionsmovie"),
                    (BOOT60 + 300, "optionsmovie")]),
    card_row("menuidle", BOOT1 + 60, skipMovies=0,
             input=[(BOOT1 + 16, "select"), (BOOT1 + 18, "back")]),
    card_row("attractmovie", BOOT1 + 40, skipMovies=0,
             input=[(BOOT1 + 12, "optionsmovie")]),
    # The main menu's highlight, before Options and after it.
    card_row("menuhighlight", BOOT60 + 300, dt=SIXTIETH, skipMovies=0,
             input=[(BOOT60 + 270, "select"), (BOOT60 + 272, "hi2"),
                    (BOOT60 + 273, "hi3"), (BOOT60 + 274, "hi9"),
                    (BOOT60 + 275, "item3"), (BOOT60 + 278, "back"),
                    (BOOT60 + 280, "hi1"), (BOOT60 + 282, "hi2")]),
    # The race asked for from the main menu with its movie playing.
    card_row("leavemovie", BOOT60 + 320, dt=SIXTIETH, skipMovies=0,
             gameType=2,
             input=[(BOOT60 + 270, "select"), (BOOT60 + 300, "race")]),
    # MemcardSaver: Options' Load/Save over the main menu, or the race's
    # end's Autosave. See kScenarios[] for each.
    save_row("lssave", 24, [(3, "loadsave"), (5, "picksave"), (20, "back")]),
    save_row("lsoverwriteyes", 24, [(3, "loadsave"), (5, "picksave"),
                                    (9, "left"), (10, "select")], card="good"),
    save_row("lsoverwriteno", 16, [(3, "loadsave"), (5, "picksave"),
                                   (9, "select")], card="good"),
    save_row("lsnocardno", 16, [(3, "loadsave"), (5, "picksave"),
                                (9, "select")], card="nocard"),
    save_row("lsnocardyes", 24, [(3, "loadsave"), (5, "picksave"),
                                 (9, "left"), (10, "select"), (16, "select")],
             card="nocard"),
    save_row("lsformatyes", 36, [(3, "loadsave"), (5, "picksave"),
                                 (9, "left"), (10, "select")],
             card="unformatted"),
    save_row("lsformatno", 16, [(3, "loadsave"), (5, "picksave"),
                                (9, "select")], card="unformatted"),
    save_row("lsbadformat", 40, [(3, "loadsave"), (5, "picksave"),
                                 (9, "left"), (10, "select"), (18, "left"),
                                 (19, "select"), (28, "select")],
             card="badformat"),
    save_row("lsfixed", 24, [(3, "loadsave"), (5, "picksave"), (9, "left"),
                             (10, "select")], card="fixed"),
    save_row("lsfull", 16, [(3, "loadsave"), (5, "picksave"), (9, "select")],
             card="full"),
    save_row("lssavefail", 36, [(3, "loadsave"), (5, "picksave"),
                                (12, "left"), (13, "select"), (24, "select")],
             card="savefail"),
    save_row("lssavefull", 20, [(3, "loadsave"), (5, "picksave"),
                                (12, "select")], card="savefull"),
    save_row("lsnewcard", 20, [(3, "loadsave"), (5, "picksave")],
             card="newcard"),
    save_row("lsgone", 24, [(3, "loadsave"), (5, "picksave"), (9, "left"),
                            (10, "select"), (16, "select")],
             card="goneafter"),
    save_row("lscheckerr", 16, [(3, "loadsave"), (5, "picksave")],
             card="checkerr"),
    save_row("lsfilegone", 24, [(3, "loadsave"), (5, "picksave"), (9, "left"),
                                (10, "select")], card="gone"),
    save_row("lsautoon", 20, [(3, "loadsave"), (5, "asright")]),
    save_row("lsautooff", 24, [(3, "loadsave"), (5, "asleft"),
                               (16, "asright"), (18, "picksave")]),
    save_row("lsautonocard", 16, [(3, "loadsave"), (5, "asright"),
                                  (9, "select")], card="nocard"),
    save_row("lsskip", 32, [(2, "fredautosave"), (3, "loadsave"),
                            (5, "picksave"), (9, "select"), (11, "select"),
                            (15, "select"), (17, "left"), (18, "select")],
             card="nocard"),
    save_row("lsload", 24, [(3, "loadsave"), (5, "pickload"), (9, "left"),
                            (10, "select")], card="good"),
    save_row("lslite", 12, [(3, "loadsave"), (5, "litesave"),
                            (7, "liteauto"), (9, "back")]),
    save_row("lsmovie", 8, [(3, "optionsmovie"), (4, "loadsave")],
             skipMovies=0),
    save_row("lssaveslow", 400, [(3, "loadsave"), (5, "picksave")],
             dt=SIXTIETH),
    save_row("asblank", 16, [(3, "autosave")]),
    save_row("ascb", 16, [(3, "autosave"), (4, "autosavecb")]),
    save_row("asstay", 16, [(3, "autosave"), (4, "autosavestay")]),
    save_row("ascreateyes", 20, [(3, "autosave"), (4, "autosavecb"),
                                 (7, "left"), (8, "select")], askCreate=1),
    save_row("ascreateno", 16, [(3, "autosave"), (4, "autosavecb"),
                                (7, "select")], askCreate=1),
    save_row("ascreateskip", 20, [(2, "fredautosave"), (3, "autosave"),
                                  (4, "autosavecb"), (7, "select"),
                                  (9, "left"), (10, "select")], askCreate=1),
    save_row("ascreatenew", 20, [(3, "autosave"), (4, "autosavecb"),
                                 (7, "left"), (8, "select")],
             card="newcard", askCreate=1),
    save_row("ascreateyank", 20, [(3, "autosave"), (4, "autosavecb"),
                                  (7, "left"), (8, "select"), (12, "select")],
             card="yanked", askCreate=1),
    save_row("asoverwrite", 20, [(3, "autosave"), (4, "autosavecb"),
                                 (7, "left"), (8, "select")],
             card="good", askCreate=1),
    save_row("asunformatted", 16, [(3, "autosave"), (4, "autosavecb"),
                                   (7, "select")],
             card="unformatted", askCreate=1),
]


def retail_title_movies():
    """TITLE_MOVIES against the table in SLES_507.31: the differences."""
    import retail_model
    e = retail_model.RetailEmu()
    bad = []
    for lang in range(8):
        for i in range(2):
            a = TITLE_MOVIES_AT + 8 * (lang * 2 + i)
            p = e.u32(a)
            name = e.read(p, 64).split(b"\0")[0].decode() if p else None
            got = (name, e.u32(a + 4))
            if got != TITLE_MOVIES[lang][i]:
                bad.append("TitleMoviesToPlay[%d][%d] is %r in retail, %r here"
                           % (lang, i, got, TITLE_MOVIES[lang][i]))
    return bad


def run_scenario(sc):
    out = ["scenario %s" % sc["name"]]
    f = Flow(sc, out)
    # InitializeEverything's LoadGlobalChunks, then the scenario's language:
    # -1 written over the LanguageManager, anything else set through it.
    f.loading.load_global_chunks()
    if sc["currLanguage"] == -1:
        out.append("input no language")
        f.curr_language = -1
    elif sc["currLanguage"] != 0:
        out.append("input language %d" % sc["currLanguage"])
        f.loading.set_curr_language(sc["currLanguage"])
    f.change_state(LOADING_FRONTEND)
    for frame in range(sc["frames"]):
        for at, what in sc["input"]:
            if at != frame:
                continue
            out.append("input %s" % what)
            # The pad's events go to a popup that is up before the screen.
            if what in ("loadsave", "autosave"):
                f.push("New Main Menu")
                f.change_to_screen("Phils Load Save" if what == "loadsave"
                                   else "Autosave", 0)
            elif what in ("picksave", "pickload"):
                f.menu_item_event(MENUITEM_SELECT, ITEM_SAVE if what[4] == "s"
                                  else ITEM_LOAD, 0)
            elif what in ("asleft", "asright"):
                f.menu_item_event(MENUITEM_PAD_LEFT if what[2] == "l"
                                  else MENUITEM_PAD_RIGHT, ITEM_AUTOSAVE, 0)
            elif what in ("litesave", "liteauto"):
                f.menu_item_event(MENUITEM_HIGHLIGHT, ITEM_SAVE
                                  if what[4] == "s" else ITEM_AUTOSAVE, 0)
            elif what == "fredautosave":
                retail_emu().put32(FRED + FRED_AUTOSAVE, 1)
            elif what == "autosavecb":
                f.autoload.run(SET_AUTOSAVE_DONE, retail_emu().al_done)
            elif what == "autosavestay":
                f.autoload.run(SET_AUTOSAVE_DONE, retail_emu().al_stay)
            elif what == "select":
                if not f.autoload.joy(0, JOY_MENU_SELECT):
                    f.screen_event(MENUITEM_SELECT, 0)
            elif what == "start":
                if not f.autoload.joy(0, JOY_START):
                    f.screen_event(SCREEN_START_BUTTON, 0)
            elif what == "back":
                if not f.autoload.joy(0, JOY_MENU_BACK):
                    f.back_button(0)
            elif what in ("left", "right", "up", "down"):
                f.autoload.joy(0, {"left": JOY_LEFT, "right": JOY_RIGHT,
                                   "up": JOY_UP, "down": JOY_DOWN}[what])
            elif what.startswith("item"):
                n = ord(what[4]) - ord("1")
                f.menu_item_event(MENUITEM_SELECT, ITEM_MENUITEM_1 + n, 0)
            elif what.startswith("hl"):
                f.active_item = ITEM_MENUITEM_1 + ord(what[2]) - ord("1")
            elif what.startswith("hi"):
                n = ord(what[2]) - ord("1")
                f.active_item = ITEM_MENUITEM_1 + n
                f.menu_item_event(MENUITEM_HIGHLIGHT, ITEM_MENUITEM_1 + n, 0)
            elif what.startswith("slow"):
                f.loader_due = int(what[4:])
            elif what == "optionsmovie":
                f.movie.start(OPTIONS_MOVIE)
            elif what == "ingame":
                f.in_game = 1
            elif what == "outgame":
                f.in_game = 0
            elif what == "race":
                f.change_state(UNLOADING_FRONTEND, NONE)
            elif what == "mumbo":
                f.push("New Main Menu")
                f.change_to_screen("Legal MumboJumbo", 0)
            elif what == "pushvet":
                f.push("View Event Tree")
            elif what == "pushqr":
                f.push("Quick Race")
        f.frame(sc["dt"])
        f.service_loads()
        f.service_replay()
        out.append("frame %d %u %u" % (frame, f.real_time, f.real_timer))
    out.append("final %s %s %d cops %d language %d autosave %08x"
               % (STATE_NAMES[f.current],
                  f.screen[0] if f.screen else "-", f.index, f.cops_on,
                  f.curr_language, retail_emu().u32(FRED + FRED_AUTOSAVE)))
    # Whatever is still open, as the next boot would find it.
    if f.screen and f.screen[2] in RetailAutoload.CALLBACKS:
        f.autoload.callback(SCREEN_UNACTIVATE, {"itemHash": f.screen[1],
                                                "port": 0, "param": 0,
                                                "noise": 0}, f.screen[2])
    return out


HARNESS_TIMEOUT = 60
HARNESS_HUNG = -9999


def c_transcript(exe, chosen):
    """gameflow_test's transcript, or its exit code if it failed."""
    try:
        proc = subprocess.run([str(exe)] + [s["name"] for s in chosen],
                              capture_output=True, text=True,
                              timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        return HARNESS_HUNG
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        return proc.returncode
    return proc.stdout.replace("\r\n", "\n").rstrip("\n").split("\n")


def count_diff(c_lines, py_lines):
    diff = list(difflib.unified_diff(c_lines, py_lines, "gameflow.c",
                                     "bootflow_check.py", lineterm=""))
    ndiff = sum(1 for d in diff if d[:1] in "+-" and d[:3] not in ("+++", "---"))
    return diff, ndiff


# The title screen broken one way at a time, in gameflow.c; each must change
# the transcript. (name, file, before, after), written with plain newlines.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GF = "3DS Files/source/gameflow.c"
NL = "\n"
MUTATIONS = [
    # 0x0016f4f8: four seconds, at 1/4000 s a tick.
    ("gate-three-seconds", GF,
     "* 0.00025f > 4.0f", "* 0.00025f > 3.0f"),
    ("gate-scale", GF,
     "* 0.00025f > 4.0f", "* 0.0005f > 4.0f"),
    ("gate-starts-during-movies", GF,
     "    if (rest && !titlePressStartSet(t)) t->pressStart = gf->realTimer;",
     "    if (!titlePressStartSet(t)) t->pressStart = gf->realTimer;"),
    ("gate-not-on-select", GF,
     "if (!titlePressStartReady(gf)) {",
     "if (0) {"),
    ("gate-early-select-clicks", GF,
     "                    data->noise = 0;" + NL
     + "                    break;" + NL
     + "                }" + NL
     + "                t->timer = gf->realTimer;" + NL
     + "                // Noise is left alone",
     "                    break;" + NL
     + "                }" + NL
     + "                t->timer = gf->realTimer;" + NL
     + "                // Noise is left alone"),
    ("gate-press-start-hidden", GF,
     "        objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_PRESS_START, ready);",
     "        objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_PRESS_START, 0);"),
    # The skip: stop the movie, stay on the title.
    ("skip-leaves-title", GF,
     "                trace(gf, \"title skip\");",
     "                trace(gf, \"title skip\");" + NL
     + "                bgf_change_to_screen(gf, \"New Main Menu\", 1);"),
    ("skip-ealogo-too", GF,
     "                if (t->movieIndex == 0) {",
     "                if (0) {"),
    ("skip-movie-left-open", GF,
     "                titleCloseMovie(gf);" + NL
     + "                t->mode  = 1;",
     "                t->mode  = 1;"),
    ("skip-no-bloom-start", GF,
     "                titleBloomStart(gf);" + NL
     + "                trace(gf, \"title skip\");",
     "                trace(gf, \"title skip\");"),
    ("skip-keeps-timer", GF,
     "                t->mode  = 1;" + NL
     + "                t->timer = gf->realTimer;" + NL
     + "                titleBloomStart(gf);",
     "                t->mode  = 1;" + NL
     + "                titleBloomStart(gf);"),
    # The constructor, 0x0016f000.
    ("ctor-copyright-shown", GF,
     "    objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_COPYRIGHT, 0);" + NL
     + "    objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_MOVIE_PLANE_LB, 0);",
     "    objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_MOVIE_PLANE_LB, 0);"),
    ("ctor-plane-43-shown", GF,
     "    objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_MOVIE_PLANE_43, 0);" + NL
     + "    objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_COPYRIGHT, 0);",
     "    objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_COPYRIGHT, 0);"),
    ("ctor-skipmovies-silent", GF,
     "        t->mode = 1;" + NL + "        HOOK_VOID(gf, jukebox, 1);",
     "        t->mode = 1;"),
    ("ctor-bloom-item", GF,
     "    titleBloomSetItem(gf, BGF_OBJ_PRESS_START);",
     "    titleBloomSetItem(gf, BGF_OBJ_ANIMATING_ITEM);"),
    ("ctor-planes-swapped", GF,
     "d->letterboxed ? BGF_OBJ_MOVIE_PLANE_LB" + NL
     + "                                 : BGF_OBJ_MOVIE_PLANE_43",
     "d->letterboxed ? BGF_OBJ_MOVIE_PLANE_43" + NL
     + "                                 : BGF_OBJ_MOVIE_PLANE_LB"),
    # HandleTick, 0x0016f1f0.
    ("tick-image-always", GF,
     "    rest = t->mode != 2;", "    rest = 1;"),
    ("tick-plane-43-left", GF,
     "            objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_MOVIE_PLANE_43, 0);"
     + NL
     + "            objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_MOVIE_PLANE_LB, 0);",
     "            objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_MOVIE_PLANE_LB, 0);"),
    ("tick-one-movie-short", GF,
     "            if (t->movieIndex == bgf_num_title_movies(gf)) {",
     "            if (t->movieIndex + 1 >= bgf_num_title_movies(gf)) {"),
    ("tick-rest-silent", GF,
     "                HOOK_VOID(gf, jukebox, 1);",
     "                (void)0;"),
    ("tick-rest-keeps-timer", GF,
     "                t->mode    = 1;" + NL
     + "                t->timer   = gf->realTimer;",
     "                t->mode    = 1;"),
    ("tick-no-bloom", GF,
     "        titleBloomAnimate(gf);" + NL + "    }",
     "    }"),
    ("tick-no-demo-mode", GF,
     "        bgf_consider_start_demo_mode(gf, &t->timer);",
     "        (void)0;"),
    # HandleEvent, 0x0016eef8.
    ("event-back-allowed", GF,
     "            data->param = 0;   // veto",
     "            data->param = 1;   // veto"),
    ("event-start-clicks", GF,
     "        case BMSG_SCREEN_START_BUTTON:" + NL
     + "            data->noise = 0;   // swallow the UI click",
     "        case BMSG_SCREEN_START_BUTTON:" + NL
     + "            data->noise = 1;   // swallow the UI click"),
]

MUTATIONS += [
    # LoadGlobalChunks, 0x001682d0.
    ("lgc-no-english", GF,
     "    bgf_set_curr_language(gf, 0);   // l_ENGLISH, through 0x00100808",
     "    (void)0;"),
    ("lgc-loading-hidden", GF,
     "    screenVisible(gf, BGF_SCREEN_LOADING_TRACK, 1);",
     "    screenVisible(gf, BGF_SCREEN_LOADING_TRACK, 0);"),
    ("lgc-no-copyright", GF,
     "    objectVisible(gf, BGF_SCREEN_LOADING_TRACK, BGF_OBJ_COPYRIGHT, 1);",
     "    (void)0;"),
    # BeginGameFlowLoadingFrontend, 0x00168698, and its callbacks.
    ("begin-no-callback", GF,
     "    loadResource(gf, \"FRONTEND\\\\FRONTB.LZC\", frontendLoaded);",
     "    loadResource(gf, \"FRONTEND\\\\FRONTB.LZC\", NULL);"),
    ("begin-callback-on-fronta", GF,
     "    loadResource(gf, \"FRONTEND\\\\FRONTA.BUN\", NULL);",
     "    loadResource(gf, \"FRONTEND\\\\FRONTA.BUN\", frontendLoaded);"),
    ("loaded-no-speech", GF,
     "    loadCurrentSpeech(gf);" + NL
     + "    trace(gf, \"load sound regions\");",
     "    trace(gf, \"load sound regions\");"),
    ("loaded-sounds-at-once", GF,
     "    if (gf->hooks.loadSoundRegions)" + NL
     + "        gf->hooks.loadSoundRegions(gf->hooks.user, frontendSoundsLoaded);",
     "    if (0)" + NL
     + "        gf->hooks.loadSoundRegions(gf->hooks.user, frontendSoundsLoaded);"),
    ("sounds-wrong-state", GF,
     "    bgf_change_state(gf, BGF_IN_FRONTEND, BGF_NONE);",
     "    bgf_change_state(gf, BGF_UNLOADING_FRONTEND, BGF_NONE);"),
    # BeginGameFlowUnloadingFrontEnd's last call, 0x00168920.
    ("unload-stays", GF,
     "    HOOK_VOID0(gf, unloadFrontEnd);" + NL
     + "    bgf_change_state(gf, BGF_LOADING_TRACK_COMMON, BGF_NONE);",
     "    HOOK_VOID0(gf, unloadFrontEnd);"),
    ("unload-wrong-state", GF,
     "    bgf_change_state(gf, BGF_LOADING_TRACK_COMMON, BGF_NONE);" + NL
     + "}",
     "    bgf_change_state(gf, BGF_LOADING_TRACK_SPECIFIC, BGF_NONE);" + NL
     + "}"),
    # UnlaunchFrontendMenus, 0x0016fa80.
    ("unload-no-unlaunch", GF,
     "    bgf_unlaunch_frontend_menus(gf);" + NL
     + "    HOOK_VOID0(gf, closeSelectCar);",
     "    HOOK_VOID0(gf, closeSelectCar);"),
    ("unlaunch-keeps-screen", GF,
     "    bgf_pop_screens(gf, 0);" + NL
     + "    bgf_change_to_screen(gf, NULL, 0);",
     "    bgf_pop_screens(gf, 0);"),
    ("unlaunch-pops-one", GF,
     "    bgf_pop_screens(gf, 0);" + NL
     + "    bgf_change_to_screen(gf, NULL, 0);",
     "    bgf_pop_screens(gf, 1);" + NL
     + "    bgf_change_to_screen(gf, NULL, 0);"),
    ("unlaunch-change-first", GF,
     "    if (gameType == 8 || gameType == 9)" + NL
     + "        bgf_pop_until(gf, \"View Event Tree\");" + NL
     + "    else if (gameType >= 2 && gameType < 8)" + NL
     + "        bgf_pop_until(gf, \"New Main Menu\");" + NL
     + "    bgf_pop_screens(gf, 0);" + NL
     + "    bgf_change_to_screen(gf, NULL, 0);",
     "    bgf_change_to_screen(gf, NULL, 0);" + NL
     + "    if (gameType == 8 || gameType == 9)" + NL
     + "        bgf_pop_until(gf, \"View Event Tree\");" + NL
     + "    else if (gameType >= 2 && gameType < 8)" + NL
     + "        bgf_pop_until(gf, \"New Main Menu\");" + NL
     + "    bgf_pop_screens(gf, 0);"),
    ("unlaunch-gt8-only", GF,
     "    if (gameType == 8 || gameType == 9)",
     "    if (gameType == 8)"),
    ("unlaunch-gt9-only", GF,
     "    if (gameType == 8 || gameType == 9)",
     "    if (gameType == 9)"),
    ("unlaunch-gt-from1", GF,
     "    else if (gameType >= 2 && gameType < 8)",
     "    else if (gameType >= 1 && gameType < 8)"),
    ("unlaunch-gt-from3", GF,
     "    else if (gameType >= 2 && gameType < 8)",
     "    else if (gameType >= 3 && gameType < 8)"),
    ("unlaunch-gt-to7", GF,
     "    else if (gameType >= 2 && gameType < 8)",
     "    else if (gameType >= 2 && gameType < 7)"),
    ("unlaunch-gt-unbounded", GF,
     "    else if (gameType >= 2 && gameType < 8)",
     "    else if (gameType >= 2)"),
    ("unlaunch-gt-unsigned", GF,
     "    else if (gameType >= 2 && gameType < 8)",
     "    else if ((unsigned)gameType - 2u < 6u || gameType < 0)"),
    ("unlaunch-tree-mainmenu", GF,
     "        bgf_pop_until(gf, \"View Event Tree\");",
     "        bgf_pop_until(gf, \"New Main Menu\");"),
    ("unlaunch-mainmenu-tree", GF,
     "        bgf_pop_until(gf, \"New Main Menu\");" + NL
     + "    bgf_pop_screens(gf, 0);",
     "        bgf_pop_until(gf, \"View Event Tree\");" + NL
     + "    bgf_pop_screens(gf, 0);"),
    ("unlaunch-music-plays", GF,
     "    HOOK_VOID(gf, jukebox, 0);" + NL
     + "    gf->frontendLaunchType = demo ? 2 : 3;",
     "    gf->frontendLaunchType = demo ? 2 : 3;"),
    ("unlaunch-music-late", GF,
     "    HOOK_VOID(gf, jukebox, 0);" + NL
     + "    gf->frontendLaunchType = demo ? 2 : 3;" + NL
     + "    trace(gf, \"unlaunch %d\", gf->frontendLaunchType);",
     "    gf->frontendLaunchType = demo ? 2 : 3;" + NL
     + "    trace(gf, \"unlaunch %d\", gf->frontendLaunchType);" + NL
     + "    HOOK_VOID(gf, jukebox, 0);"),
    ("unlaunch-demo-swapped", GF,
     "    gf->frontendLaunchType = demo ? 2 : 3;",
     "    gf->frontendLaunchType = demo ? 3 : 2;"),
    ("unlaunch-demo-ignored", GF,
     "    gf->frontendLaunchType = demo ? 2 : 3;",
     "    gf->frontendLaunchType = 3;"),
    ("unlaunch-launch-type-1", GF,
     "    gf->frontendLaunchType = demo ? 2 : 3;",
     "    gf->frontendLaunchType = demo ? 2 : 1;"),
    ("unlaunch-movie-plays", GF,
     "    bgf_stop_movie(gf);                // 0x0016fb74, after the launch type" + NL,
     ""),
    ("unlaunch-movie-first", GF,
     "    HOOK_VOID(gf, jukebox, 0);" + NL
     + "    gf->frontendLaunchType = demo ? 2 : 3;" + NL
     + "    trace(gf, \"unlaunch %d\", gf->frontendLaunchType);" + NL
     + "    bgf_stop_movie(gf);                // 0x0016fb74, after the launch type",
     "    bgf_stop_movie(gf);" + NL
     + "    HOOK_VOID(gf, jukebox, 0);" + NL
     + "    gf->frontendLaunchType = demo ? 2 : 3;" + NL
     + "    trace(gf, \"unlaunch %d\", gf->frontendLaunchType);"),
    ("unlaunch-no-songmon-reset", GF,
     "    HOOK_VOID0(gf, songMonitorReset);" + NL,
     ""),
    ("unlaunch-songmon-first", GF,
     "    HOOK_VOID(gf, jukebox, 0);" + NL
     + "    gf->frontendLaunchType",
     "    HOOK_VOID0(gf, songMonitorReset);" + NL
     + "    HOOK_VOID(gf, jukebox, 0);" + NL
     + "    gf->frontendLaunchType"),
    ("unlaunch-resets-stack", GF,
     "    bgf_pop_screens(gf, 0);" + NL
     + "    bgf_change_to_screen(gf, NULL, 0);",
     "    bgf_reset_stack(gf);" + NL
     + "    bgf_change_to_screen(gf, NULL, 0);"),
    # End, 0x001687a8.
    ("end-copyright-left", GF,
     "    objectVisible(gf, BGF_SCREEN_LOADING_TRACK, BGF_OBJ_COPYRIGHT, 0);",
     "    (void)0;"),
    ("end-loading-left", GF,
     "    screenVisible(gf, BGF_SCREEN_LOADING_TRACK, 0);" + NL
     + "    objectVisible(gf, BGF_SCREEN_LOADING_TRACK, BGF_OBJ_COPYRIGHT, 0);",
     "    objectVisible(gf, BGF_SCREEN_LOADING_TRACK, BGF_OBJ_COPYRIGHT, 0);"),
    # The LanguageManager: SetLanguage 0x0021e0d0 and its tail 0x0021e1e0.
    ("lang-same-reloads", GF,
     "    if (language == old) return;" + NL
     + "    // The outgoing table's chunks go first",
     "    // The outgoing table's chunks go first"),
    ("lang-no-unload", GF,
     "    if (old != -1) trace(gf, \"language unload %d\", old);",
     "    (void)0;"),
    ("lang-speech-kept", GF,
     "    if (gf->speechLoaded) {" + NL
     + "        unloadSpeech(gf);" + NL
     + "        loadCurrentSpeech(gf);" + NL
     + "    }",
     "    (void)0;"),
    ("lang-logo-one-way", GF,
     "    if ((language == 1) != (gf->logoFrench != 0)) {",
     "    if (language == 1 && !gf->logoFrench) {"),
    ("speech-while-unset", GF,
     "    if (gf->currLanguage == -1 || gf->speechLoaded) return;",
     "    if (gf->speechLoaded) return;"),
    # LanguageOptionsScreenBase, 0x001f1a78 and 0x001f1b08.
    ("ctor-load-all-shown", GF,
     "    grayMenuItem(gf, flailer, BGF_ITEM_MENUITEM_7, 2);",
     "    (void)0;"),
    ("select-load-all-ignored", GF,
     "                if (item != BGF_ITEM_MENUITEM_7) return;" + NL
     + "                gf->loadAllLanguages = 1;",
     "                return;" + NL
     + "                gf->loadAllLanguages = 1;"),
    ("select-no-defaults", GF,
     "    if (!l->fromOptions) trace(gf, \"frontend defaults\");",
     "    (void)0;"),
    ("select-stays", GF,
     "    if (!l->fromOptions) trace(gf, \"frontend defaults\");" + NL
     + "    bgf_move_back_screen(gf, 1);",
     "    if (!l->fromOptions) trace(gf, \"frontend defaults\");"),
    ("back-not-vetoed", GF,
     "            data->param = 0;" + NL
     + "            if (gf->currLanguage == -1) return;",
     "            if (gf->currLanguage == -1) return;"),
    ("back-while-unset", GF,
     "            data->param = 0;" + NL
     + "            if (gf->currLanguage == -1) return;",
     "            data->param = 0;"),
    ("back-ignores-highlight", GF,
     "            item = activeMenuItem(gf);",
     "            item = data->itemHash;"),
    # MoveBackScreen and the pad's BACK.
    ("move-back-sends-button", GF,
     "return bgf_move_to_previous_screen(gf, n, 0, -1);",
     "return bgf_move_to_previous_screen(gf, n, 1, 0);"),
    ("back-button-silent", GF,
     "return bgf_move_to_previous_screen(gf, 1, 1, port);",
     "return bgf_move_to_previous_screen(gf, 1, 0, port);"),
    ("back-names-screen", GF,
     "    data.noise = BSND_MENU_CANCEL;" + NL + NL
     + "    if (sendBackButton) {",
     "    data.noise = BSND_MENU_CANCEL;" + NL
     + "    if (gf->screen) data.itemHash = gf->screen->hash;" + NL + NL
     + "    if (sendBackButton) {"),
    # FlailerScreen::Activate's order.
    ("menu-after-activate", GF,
     "            HOOK_VOID(gf, openScreen, n);" + NL
     + "            memset(&data, 0, sizeof(data));" + NL
     + "            data.itemHash = n->hash;" + NL
     + "            // The reply: a Param other than -1 puts the menu on item" + NL
     + "            // Param - 1 (Select Track answers its time of day's item)." + NL
     + "            // The noise is played after the callback, as BACK's is." + NL
     + "            data.param = -1;" + NL
     + "            bgf_send(gf, BMSG_SCREEN_ACTIVATE, &data);",
     "            memset(&data, 0, sizeof(data));" + NL
     + "            data.itemHash = n->hash;" + NL
     + "            data.param = -1;" + NL
     + "            bgf_send(gf, BMSG_SCREEN_ACTIVATE, &data);" + NL
     + "            HOOK_VOID(gf, openScreen, n);"),
]

MC = "3DS Files/source/memcard.c"
BP = "3DS Files/source/bpopup.c"
CHECK_WAIT = "    if (t->active || !waited(l->gf, l->timer, 2.0f)) return;" + NL
CHECK_ERR = "    err = t->fs ? t->fs->lastError : BMC_NO_CARD;" + NL
MUTATIONS += [
    # BootAutoLoader's loader: the timers, 0x00247320 and on.
    ("mc-check-three-seconds", MC,
     CHECK_WAIT + CHECK_ERR + "    if (err == BMC_NOT_FORMATTED) {",
     CHECK_WAIT.replace("2.0f", "3.0f") + CHECK_ERR
     + "    if (err == BMC_NOT_FORMATTED) {"),
    ("mc-read-three-seconds", MC,
     CHECK_WAIT + CHECK_ERR + "    if (err == BMC_OK && savegameVerify(",
     CHECK_WAIT.replace("2.0f", "3.0f") + CHECK_ERR
     + "    if (err == BMC_OK && savegameVerify("),
    ("mc-status-three-seconds", MC,
     CHECK_WAIT + CHECK_ERR + "    switch ((unsigned)err",
     CHECK_WAIT.replace("2.0f", "3.0f") + CHECK_ERR
     + "    switch ((unsigned)err"),
    ("mc-check-ignores-job", MC,
     CHECK_WAIT + CHECK_ERR + "    if (err == BMC_NOT_FORMATTED) {",
     "    if (!waited(l->gf, l->timer, 2.0f)) return;" + NL + CHECK_ERR
     + "    if (err == BMC_NOT_FORMATTED) {"),
    ("mc-leave-three-seconds", MC,
     "if (waited(l->gf, l->timer, 4.0f)) l->state = BMC_LOADER_DONE;",
     "if (waited(l->gf, l->timer, 3.0f)) l->state = BMC_LOADER_DONE;"),
    ("mc-waited-scale", MC,
     "(gf->realTimer - start) * 0.00025f", "(gf->realTimer - start) * 0.0005f"),
    # MemcardTester, 0x002457c0 and on.
    ("mc-tester-no-pump", MC,
     "    while (t->fs->lastError == BMC_ERROR",
     "    while (0 && t->fs->lastError == BMC_ERROR"),
    ("mc-pump-past-busy", MC,
     "    while (t->fs->lastError == BMC_ERROR || t->fs->lastError == BMC_IN_PROGRESS",
     "    while (t->fs->lastError == BMC_ERROR"),
    ("mc-tick-no-service", MC,
     "        if (l->tester->active) testerEvent(l->tester, BMSG_SCREEN_TICK);",
     "        (void)0;"),
    ("mc-service-while-idle", MC,
     "        if (l->tester->active) testerEvent(l->tester, BMSG_SCREEN_TICK);",
     "        testerEvent(l->tester, BMSG_SCREEN_TICK);"),
    ("mc-refused-stays-active", MC,
     "    if (!t->fs->vt->setState(t->fs, state, testerDone, t)) t->active = 0;",
     "    (void)t->fs->vt->setState(t->fs, state, testerDone, t);"),
    ("mc-verify-inverted", MC,
     "    return memcard_checksum(s->local) == get32(",
     "    return memcard_checksum(s->local) != get32("),
    ("mc-checksum-short", MC,
     "    for (int i = 0; i < BMC_CHECKSUM_OFFSET / 4; i++)",
     "    for (int i = 1; i < BMC_CHECKSUM_OFFSET / 4; i++)"),
    ("mc-fred-keeps-cleared", MC,
     "    put32(fred + BMC_FRED_CLEARED, 0);", "    (void)0;"),
    ("mc-fred-file-language", MC,
     "    put32(fred + BMC_FRED_LANGUAGE, (uint32_t)gf->currLanguage);",
     "    (void)0;"),
    # MemcardPrompter, 0x00245e30 and 0x00245f60.
    ("mc-slot-from-zero", MC,
     "    args[0] = slot + 1;" + NL + "    args[1] = slot + 1;",
     "    args[0] = slot;" + NL + "    args[1] = slot;"),
    ("mc-yesno-no-kb", MC,
     "    nargs   = (id == MSG_NO_SPACE || id == MSG_NO_CARD_KB) ? 2",
     "    nargs   = (id == MSG_NO_SPACE || id == MSG_NO_CARD_KB) ? 1"),
    ("mc-no-dismiss-first", MC,
     "    bpopup_dismiss(gf, 0);" + NL + "    // Every id gets the slot",
     "    // Every id gets the slot"),
    ("mc-message-selectable", MC,
     "    cfg.flags          = BPOPUP_HORIZONTAL | BPOPUP_NO_SELECT;",
     "    cfg.flags          = BPOPUP_HORIZONTAL;"),
    ("mc-message-untitled", MC,
     "    cfg.title          = PROMPT_TITLE;" + NL
     + "    bpopup_summon(gf, &cfg);" + NL + "}" + NL + NL
     + "// DisplayYesNoMessage",
     "    cfg.title          = 0;" + NL
     + "    bpopup_summon(gf, &cfg);" + NL + "}" + NL + NL
     + "// DisplayYesNoMessage"),
    ("mc-yesno-vertical", MC,
     "    cfg.flags          = BPOPUP_HORIZONTAL | BPOPUP_BUTTONS_BELOW;",
     "    cfg.flags          = BPOPUP_BUTTONS_BELOW;"),
    ("mc-yesno-buttons-inline", MC,
     "    cfg.flags          = BPOPUP_HORIZONTAL | BPOPUP_BUTTONS_BELOW;",
     "    cfg.flags          = BPOPUP_HORIZONTAL;"),
    ("mc-yesno-starts-yes", MC,
     "    cfg.buttonParam[2] = 0;" + NL + "    cfg.startButton    = 1;",
     "    cfg.buttonParam[2] = 0;" + NL + "    cfg.startButton    = 0;"),
    ("mc-yesno-params-swapped", MC,
     "    cfg.buttonParam[0] = yesParam;" + NL
     + "    cfg.buttonParam[1] = noParam;",
     "    cfg.buttonParam[0] = noParam;" + NL
     + "    cfg.buttonParam[1] = yesParam;"),
    ("mc-yesno-labels-swapped", MC,
     "    cfg.button[0]      = PROMPT_YES;" + NL
     + "    cfg.button[1]      = PROMPT_NO;",
     "    cfg.button[0]      = PROMPT_NO;" + NL
     + "    cfg.button[1]      = PROMPT_YES;"),
    # The loader's states, 0x002bee80.
    ("mc-check-new-card-refused", MC,
     "    } else if (err == BMC_OK || err == BMC_NEW_CARD) {",
     "    } else if (err == BMC_OK) {"),
    ("mc-refused-check-goes-on", MC,
     "        if (!testerCheckForSavegameFile(t)) l->state = BMC_LOADER_DONE;",
     "        (void)testerCheckForSavegameFile(t);"),
    ("mc-boot-asks-overwrite", MC,
     "        if (l->loadMode == BMC_LOAD_BOOT)" + NL
     + "            loaderStartRead(l);",
     "        if (0)" + NL + "            loaderStartRead(l);"),
    ("mc-manual-reads-at-once", MC,
     "        if (l->loadMode == BMC_LOAD_BOOT)" + NL
     + "            loaderStartRead(l);",
     "        if (1)" + NL + "            loaderStartRead(l);"),
    ("mc-no-space-unchecked", MC,
     "            if (freeKB < need) {", "            if (0) {"),
    ("mc-no-space-at-exact", MC,
     "            if (freeKB < need) {", "            if (freeKB <= need) {"),
    ("mc-no-space-shows-free", MC,
     "                loaderAsk(l, MSG_NO_SPACE, 0, 1, need,",
     "                loaderAsk(l, MSG_NO_SPACE, 0, 1, freeKB,"),
    ("mc-checkerr-no-kb", MC,
     "        int need = fs ? fs->vt->calcFreeSpaceRequired(fs, BMC_SAVE_SIZE) : 0;",
     "        int need = 0;"),
    ("mc-unformatted-noisy", MC,
     "        l->endState = 1;" + NL
     + "        loaderLeaveQuietly(l, MSG_UNFORMATTED);" + NL
     + "    } else if (err == BMC_OK",
     "        l->endState = 1;" + NL
     + "        loaderLeave(l, MSG_UNFORMATTED);" + NL
     + "    } else if (err == BMC_OK"),
    ("mc-nofile-noisy", MC,
     "        l->endState = 2;" + NL
     + "        loaderLeaveQuietly(l, MSG_NO_FILE);" + NL
     + "    } else if (l->loadMode",
     "        l->endState = 2;" + NL
     + "        loaderLeave(l, MSG_NO_FILE);" + NL
     + "    } else if (l->loadMode"),
    ("mc-nocard-quiet", MC,
     "        loaderLeave(l, MSG_NO_CARD);",
     "        loaderLeaveQuietly(l, MSG_NO_CARD);"),
    ("mc-loadfailed-quiet", MC,
     "        loaderLeave(l, MSG_LOAD_FAILED);",
     "        loaderLeaveQuietly(l, MSG_LOAD_FAILED);"),
    ("mc-newcard-quiet", MC,
     "            loaderLeave(l, MSG_NEW_CARD);",
     "            loaderLeaveQuietly(l, MSG_NEW_CARD);"),
    ("mc-retry-gives-up", MC,
     "                if (data->param == 0)" + NL
     + "                    loaderStartLoadSequence(l);",
     "                if (data->param == 0)" + NL
     + "                    l->state = BMC_LOADER_DONE;"),
    ("mc-retry-no-stays", MC,
     "                else if (data->param == 1)" + NL
     + "                    l->state = BMC_LOADER_DONE;",
     "                else if (data->param == 1)" + NL
     + "                    (void)0;"),
    ("mc-overwrite-no-stays", MC,
     "                } else if (data->param == 3) {" + NL
     + "                    l->state = BMC_LOADER_DONE;",
     "                } else if (data->param == 3) {" + NL
     + "                    (void)0;"),
    ("mc-overwrite-no-check", MC,
     "                    testerCheckForSavegameFile(l->tester);",
     "                    (void)0;"),
    ("mc-dismiss-clicks", MC,
     "                data->noise = 0;" + NL + "                break;" + NL
     + "            case BMC_LOADER_PROMPT_RETRY:",
     "                break;" + NL + "            case BMC_LOADER_PROMPT_RETRY:"),
    ("mc-done-leaves-popup", MC,
     "            prompterClear(l->prompter);" + NL + "            return 1;",
     "            return 1;"),
    # BootAutoLoader itself, 0x00247ab0 and 0x00247978.
    ("mc-autoload-plays-on", MC,
     "    bgf_stop_movie(gf);                // 0x00247934" + NL
     + "    b->state = 1;",
     "    b->state = 1;"),
    ("mc-autoload-stays", MC,
     "    if (msg == BMSG_SCREEN_TICK && b->state == 0) bgf_move_back_screen(gf, 1);",
     "    (void)gf;"),
    ("mc-autoload-back-two", MC,
     "b->state == 0) bgf_move_back_screen(gf, 1);",
     "b->state == 0) bgf_move_back_screen(gf, 2);"),
    ("mc-autoload-leaks", GF,
     "            if (gf->autoloadActive) memcard_boot_autoloader_destroy(&gf->autoload);",
     "            (void)0;"),
    ("mc-autoload-always-boot", GF,
     "                                         gf->autoloadManual);",
     "                                         0);"),
    # MemcardSaver: 0x00246110, the cancel 0x002469e0, and its states.
    ("mc-saver-finish-keeps-autosave", MC,
     "    if (notSaved == 1 && !s->keepAutosave) setAutosave(s->gf, 0);",
     "    (void)0;"),
    ("mc-saver-finish-ignores-keep", MC,
     "    if (notSaved == 1 && !s->keepAutosave) setAutosave(s->gf, 0);",
     "    if (notSaved == 1) setAutosave(s->gf, 0);"),
    ("mc-cancel-never-asks", MC,
     "    if (autosaveOn(s->gf) && s->keepAutosave == 1) {",
     "    if (0) {"),
    ("mc-cancel-ignores-keep", MC,
     "    if (autosaveOn(s->gf) && s->keepAutosave == 1) {",
     "    if (autosaveOn(s->gf)) {"),
    ("mc-cancel-ignores-autosave", MC,
     "    if (autosaveOn(s->gf) && s->keepAutosave == 1) {",
     "    if (s->keepAutosave == 1) {"),
    ("mc-skip-params-swapped", MC,
     "prompterYesNo(s->prompter, MSG_NO_SAVE, 2, 3,",
     "prompterYesNo(s->prompter, MSG_NO_SAVE, 3, 2,"),
    ("mc-skip-yes-asks-again", MC,
     "                if (s->state == BMC_SAVER_PROMPT_RETRY) {",
     "                if (1) {"),
    ("mc-retry-no-skips-ask", MC,
     "                if (s->state == BMC_SAVER_PROMPT_RETRY) {",
     "                if (0) {"),
    ("mc-retry-yes-stays", MC,
     "            } else if (data->param == 3) {" + NL
     + "                saverStartSaveSequence(s);",
     "            } else if (data->param == 3) {" + NL
     + "                (void)0;"),
    ("mc-saver-error-stale-timer", MC,
     "    s->state = BMC_SAVER_SHOWING_ERROR;" + NL
     + "    s->timer = s->gf->realTimer;",
     "    s->state = BMC_SAVER_SHOWING_ERROR;"),
    ("mc-saver-error-one-second", MC,
     "if (waited(s->gf, s->timer, 2.0f)) saverCancel(s);",
     "if (waited(s->gf, s->timer, 1.0f)) saverCancel(s);"),
    ("mc-saver-status-one-second", MC,
     "if (waited(s->gf, s->timer, 2.0f)) s->state = BMC_SAVER_DONE;",
     "if (waited(s->gf, s->timer, 1.0f)) s->state = BMC_SAVER_DONE;"),
    ("mc-saver-check-two-seconds", MC,
     "    if (s->tester->active || !waited(s->gf, s->timer, 1.0f)) return;",
     "    if (s->tester->active || !waited(s->gf, s->timer, 2.0f)) return;"),
    ("mc-saver-unformatted-retries", MC,
     "        saverAsk(s, MSG_FORMAT_ASK, 7, 6, 0, BMC_SAVER_FORMAT_PROMPT);" + NL
     + "    } else if (err == BMC_OK || err == BMC_NEW_CARD) {",
     "        saverAskRetry(s, MSG_NO_CARD_RETRY, 0);" + NL
     + "    } else if (err == BMC_OK || err == BMC_NEW_CARD) {"),
    ("mc-saver-format-params-swapped", MC,
     "        saverAsk(s, MSG_FORMAT_ASK, 7, 6, 0, BMC_SAVER_FORMAT_PROMPT);" + NL
     + "    } else if (err == BMC_OK || err == BMC_NEW_CARD) {",
     "        saverAsk(s, MSG_FORMAT_ASK, 6, 7, 0, BMC_SAVER_FORMAT_PROMPT);" + NL
     + "    } else if (err == BMC_OK || err == BMC_NEW_CARD) {"),
    ("mc-saver-new-card-refused", MC,
     "    } else if (err == BMC_OK || err == BMC_NEW_CARD) {" + NL
     + "        s->state = BMC_SAVER_CHECK_IF_CARD_OK;",
     "    } else if (err == BMC_OK) {" + NL
     + "        s->state = BMC_SAVER_CHECK_IF_CARD_OK;"),
    ("mc-saver-no-card-errors", MC,
     "    } else {" + NL + "        saverAskRetry(s, MSG_NO_CARD_RETRY, 0);"
     + NL + "    }" + NL + "}",
     "    } else {" + NL + "        saverShowError(s, MSG_NO_CARD_SLOT1);"
     + NL + "    }" + NL + "}"),
    ("mc-card-ok-not-found-errors", MC,
     "    if (err != BMC_OK && err != BMC_FILE_NOT_FOUND) {",
     "    if (err != BMC_OK) {"),
    ("mc-card-ok-error-ignored", MC,
     "    if (err != BMC_OK && err != BMC_FILE_NOT_FOUND) {",
     "    if (0) {"),
    ("mc-overwrite-never-asked", MC,
     "    } else if (fs->fileExists) {", "    } else if (0) {"),
    ("mc-overwrite-params-swapped", MC,
     "        saverAsk(s, MSG_SAVE_OVERWRITE, 5, 4, 0,",
     "        saverAsk(s, MSG_SAVE_OVERWRITE, 4, 5, 0,"),
    ("mc-saver-no-space-unchecked", MC,
     "        if (freeKB < need)" + NL
     + "            saverAskRetry(s, MSG_NO_SPACE, need);",
     "        if (0)" + NL
     + "            saverAskRetry(s, MSG_NO_SPACE, need);"),
    ("mc-saver-no-space-shows-free", MC,
     "            saverAskRetry(s, MSG_NO_SPACE, need);",
     "            saverAskRetry(s, MSG_NO_SPACE, freeKB);"),
    ("mc-create-never-asked", MC,
     "        else if (s->askCreate)", "        else if (0)"),
    ("mc-create-always-asked", MC,
     "        else if (s->askCreate)", "        else if (1)"),
    ("mc-create-params-swapped", MC,
     "saverAsk(s, MSG_CREATE, 1, 0, 0, BMC_SAVER_PROMPT_TO_CREATE);",
     "saverAsk(s, MSG_CREATE, 0, 1, 0, BMC_SAVER_PROMPT_TO_CREATE);"),
    ("mc-write-one-second", MC,
     "    if (s->tester->active || !waited(s->gf, s->timer, 2.0f)) return;"
     + NL + "    err = saverError(s);" + NL + "    if (err == BMC_OK) {",
     "    if (s->tester->active || !waited(s->gf, s->timer, 1.0f)) return;"
     + NL + "    err = saverError(s);" + NL + "    if (err == BMC_OK) {"),
    ("mc-saved-no-message", MC,
     "        prompterDisplayMessage(s->prompter, MSG_SAVED, saverSlot(s), 0);",
     "        (void)0;"),
    ("mc-write-full-plain-retry", MC,
     "    } else if (err == BMC_INSUFFICIENT_FREE_SPACE) {",
     "    } else if (0) {"),
    ("mc-write-full-no-kb", MC,
     "        saverAskRetry(s, MSG_NO_SPACE," + NL
     + "                      fs->vt->calcFreeSpaceRequired(fs, BMC_SAVE_SIZE));",
     "        saverAskRetry(s, MSG_NO_SPACE," + NL + "                      0);"),
    ("mc-before-format-unchecked", MC,
     "    if (err == BMC_NOT_FORMATTED)" + NL
     + "        saverStartFormat(s);",
     "    if (1)" + NL + "        saverStartFormat(s);"),
    ("mc-before-format-ok-formats", MC,
     "    else if (err == BMC_OK || err == BMC_NEW_CARD)" + NL
     + "        saverShowError(s, MSG_NEW_CARD);",
     "    else if (err == BMC_NEW_CARD)" + NL
     + "        saverShowError(s, MSG_NEW_CARD);"),
    ("mc-format-one-second", MC,
     "    if (s->tester->active || !waited(s->gf, s->timer, 2.0f)) return;"
     + NL + "    if (saverError(s) == BMC_OK)",
     "    if (s->tester->active || !waited(s->gf, s->timer, 1.0f)) return;"
     + NL + "    if (saverError(s) == BMC_OK)"),
    ("mc-format-ok-writes", MC,
     "    if (saverError(s) == BMC_OK)" + NL
     + "        saverStartSaveSequence(s);",
     "    if (saverError(s) == BMC_OK)" + NL + "        saverStartWrite(s);"),
    ("mc-format-retry-params-swapped", MC,
     "        saverAsk(s, MSG_FORMAT_RETRY, 9, 8, 0,",
     "        saverAsk(s, MSG_FORMAT_RETRY, 8, 9, 0,"),
    ("mc-before-overwrite-not-found-writes", MC,
     "    else if (err == BMC_OK)" + NL + "        saverStartWrite(s);",
     "    else if (err == BMC_OK || err == BMC_FILE_NOT_FOUND)" + NL
     + "        saverStartWrite(s);"),
    ("mc-before-create-new-card-writes", MC,
     "    if (err == BMC_NEW_CARD)" + NL
     + "        saverShowError(s, MSG_NEW_CARD);" + NL
     + "    else if (err == BMC_OK || err == BMC_FILE_NOT_FOUND)",
     "    if (0)" + NL
     + "        saverShowError(s, MSG_NEW_CARD);" + NL
     + "    else if (err == BMC_OK || err == BMC_FILE_NOT_FOUND)"),
    ("mc-before-create-no-card-errors", MC,
     "        saverAskRetry(s, MSG_NO_CARD_RETRY, 0);" + NL
     + "    else" + NL + "        saverShowError(s, MSG_NO_CARD_SLOT1);" + NL
     + "}" + NL + NL + "int memcard_saver_event",
     "        saverShowError(s, MSG_NO_CARD_SLOT1);" + NL
     + "    else" + NL + "        saverShowError(s, MSG_NO_CARD_SLOT1);" + NL
     + "}" + NL + NL + "int memcard_saver_event"),
    ("mc-saver-tick-no-service", MC,
     "        if (s->tester->active) testerEvent(s->tester, BMSG_SCREEN_TICK);",
     "        (void)0;"),
    ("mc-saver-done-leaves-popup", MC,
     "        if (s->state == BMC_SAVER_DONE) {" + NL
     + "            prompterClear(s->prompter);",
     "        if (s->state == BMC_SAVER_DONE) {"),
    ("mc-saver-dismiss-clicks", MC,
     "            data->noise = 0;" + NL + "            break;" + NL
     + "        case BMC_SAVER_PROMPT_SKIP:",
     "            break;" + NL + "        case BMC_SAVER_PROMPT_SKIP:"),
    ("mc-create-no-cancels-quietly", MC,
     "            if (data->param == 0)" + NL + "                saverCancel(s);",
     "            if (data->param == 0)" + NL
     + "                s->state = BMC_SAVER_DONE;"),
    ("mc-create-yes-writes-at-once", MC,
     "                saverRecheck(s, BMC_SAVER_CHECK_BEFORE_CREATE, 0);",
     "                saverStartWrite(s);"),
    ("mc-overwrite-yes-verifies", MC,
     "                saverRecheck(s, BMC_SAVER_CHECK_BEFORE_OVERWRITE, 1);",
     "                saverRecheck(s, BMC_SAVER_CHECK_BEFORE_OVERWRITE, 0);"),
    ("mc-overwrite-no-stays-up", MC,
     "            else if (data->param == 4)" + NL + "                saverCancel(s);",
     "            else if (data->param == 4)" + NL + "                (void)0;"),
    ("mc-format-yes-unchecked", MC,
     "            if (data->param == 7)" + NL
     + "                saverRecheck(s, BMC_SAVER_CHECK_BEFORE_FORMAT, 0);",
     "            if (data->param == 7)" + NL + "                saverStartFormat(s);"),
    ("mc-format-no-stays-up", MC,
     "            else if (data->param == 6)" + NL + "                saverCancel(s);",
     "            else if (data->param == 6)" + NL + "                (void)0;"),
    ("mc-format-retry-no-stays-up", MC,
     "            else if (data->param == 8)" + NL + "                saverCancel(s);",
     "            else if (data->param == 8)" + NL + "                (void)0;"),
    ("mc-recheck-no-message", MC,
     "    prompterDisplayMessage(s->prompter, MSG_CHECKING, saverSlot(s), 0);"
     + NL + "    s->state = state;",
     "    s->state = state;"),
    # LoadSaveWrapper, 0x00247830 and its constructor 0x00247378.
    ("lsw-autosave-line-inverted", MC,
     "autosaveOn(w->gf) ? BMC_LANG_AUTOSAVE_ON" + NL
     + "                                    : BMC_LANG_AUTOSAVE_OFF",
     "autosaveOn(w->gf) ? BMC_LANG_AUTOSAVE_OFF" + NL
     + "                                    : BMC_LANG_AUTOSAVE_ON"),
    ("lsw-back-stays-hidden", MC,
     "    screenVisible(w->gf, w->screenHash, 1);" + NL
     + "    lswSlide(w, \"appear\");" + NL + "    w->state = 0;" + NL
     + "    lswAutosaveLine(w);",
     "    lswSlide(w, \"appear\");" + NL + "    w->state = 0;" + NL
     + "    lswAutosaveLine(w);"),
    ("lsw-back-keeps-autosave-line", MC,
     "    w->state = 0;" + NL + "    lswAutosaveLine(w);" + NL + "}",
     "    w->state = 0;" + NL + "}"),
    ("lsw-save-menu-shown", MC,
     "    screenVisible(w->gf, w->screenHash, 0);" + NL + "    saverStart(",
     "    saverStart("),
    ("lsw-save-no-slide", MC,
     "    lswSlide(w, \"disappear\");" + NL + "}", "}"),
    ("lsw-pick-save-drops-autosave", MC,
     "                lswStartSave(w, 1);", "                lswStartSave(w, 0);"),
    ("lsw-toggle-keeps-autosave", MC,
     "            if (autosaveOn(gf)) lswStartSave(w, 0);",
     "            if (autosaveOn(gf)) lswStartSave(w, 1);"),
    ("lsw-toggle-off-saves", MC,
     "            if (autosaveOn(gf)) lswStartSave(w, 0);",
     "            lswStartSave(w, 0);"),
    ("lsw-toggle-no-line", MC,
     "            setAutosave(gf, !autosaveOn(gf));" + NL
     + "            lswAutosaveLine(w);",
     "            setAutosave(gf, !autosaveOn(gf));"),
    ("lsw-toggle-silent", MC,
     "            data->noise = 2;", "            data->noise = 0;"),
    ("lsw-load-ignored", MC,
     "            } else if (data->itemHash == BMC_ITEM_LOAD) {",
     "            } else if (0) {"),
    ("lsw-load-menu-shown", MC,
     "                w->state = 2;" + NL
     + "                screenVisible(gf, w->screenHash, 0);",
     "                w->state = 2;"),
    ("lsw-load-back-hidden", MC,
     "            if (memcard_loader_event(&w->loader, msg, data) == 1)" + NL
     + "                lswBackToMenu(w);",
     "            if (memcard_loader_event(&w->loader, msg, data) == 1)" + NL
     + "                w->state = 0;"),
    ("lsw-save-back-hidden", MC,
     "            if (memcard_saver_event(&w->saver, msg, data) == 1)" + NL
     + "                lswBackToMenu(w);",
     "            if (memcard_saver_event(&w->saver, msg, data) == 1)" + NL
     + "                w->state = 0;"),
    ("lsw-menu-live-while-saving", MC,
     "                lswBackToMenu(w);" + NL + "            return;" + NL
     + "        case 2:",
     "                lswBackToMenu(w);" + NL + "            break;" + NL
     + "        case 2:"),
    ("lsw-no-highlight", MC,
     "    lswHighlight(w, msg, data);" + NL + "    switch (msg) {",
     "    switch (msg) {"),
    ("lsw-init-no-line", MC,
     "    w->screenHash = screenHash;" + NL + "    lswAutosaveLine(w);",
     "    w->screenHash = screenHash;"),
    ("lsw-init-movie-plays", MC,
     "    bgf_stop_movie(gf);                // 0x00247468" + NL, ""),
    ("lsw-leaks", GF,
     "            if (gf->loadSaveActive) memcard_load_save_destroy(&gf->loadSave);",
     "            (void)0;"),
    # Autosaver, 0x00247d00, its constructor 0x00247b48 and 0x00247d98.
    ("as-never-asks", MC,
     "    a->saver.askCreate = gf->saveAskCreate;", "    a->saver.askCreate = 0;"),
    ("as-drops-autosave", MC,
     "    saverStart(&a->saver, &a->tester, &a->prompter, 1);",
     "    saverStart(&a->saver, &a->tester, &a->prompter, 0);"),
    ("as-never-done", MC,
     "    if (memcard_saver_event(&a->saver, msg, data) == 1) a->state = 0;",
     "    (void)memcard_saver_event(&a->saver, msg, data);"),
    ("as-done-ignores-callback", MC,
     "    if (a->done) {", "    if (0) {"),
    ("as-done-back-two", MC,
     "        bgf_move_back_screen(gf, 1);" + NL + "    }" + NL + "}",
     "        bgf_move_back_screen(gf, 2);" + NL + "    }" + NL + "}"),
    ("as-runs-after-done", MC,
     "    if (a->state != 1) return;", "    (void)0;"),
    ("as-leaks", GF,
     "            if (gf->autosaverActive) memcard_autosaver_destroy(&gf->autosaver);",
     "            (void)0;"),
    ("as-callback-not-kept", GF,
     "        gf->autosaver.done = cb;" + NL + "        return;",
     "        return;"),
    # tPopupMenu: Summon 0x0016b660, Dismiss 0x0016b9c0, HandleJoy 0x0016bac0.
    ("popup-clear-order", BP,
     "    itemClearState(gf, &p->items[2], BMENU_HIGHLIGHTED);" + NL
     + "    itemClearState(gf, &p->items[1], BMENU_HIGHLIGHTED);" + NL
     + "    itemClearState(gf, &p->items[0], BMENU_HIGHLIGHTED);",
     "    itemClearState(gf, &p->items[0], BMENU_HIGHLIGHTED);" + NL
     + "    itemClearState(gf, &p->items[1], BMENU_HIGHLIGHTED);" + NL
     + "    itemClearState(gf, &p->items[2], BMENU_HIGHLIGHTED);"),
    ("popup-screen-hidden", BP,
     "    screenVisible(gf, p->cfg.screen, 1);", "    (void)0;"),
    ("popup-no-active-msg", BP,
     "    popupSend(gf, p, BMSG_POPUP_ACTIVE, &data);", "    (void)0;"),
    ("popup-start-first", BP,
     "    p->current = (uint32_t)p->cfg.startButton;", "    p->current = 0u;"),
    ("popup-no-reset-saved", BP,
     "        itemResetSaved(gf, it);" + NL
     + "        itemClearState(gf, it, BMENU_HIGHLIGHTED);",
     "        itemClearState(gf, it, BMENU_HIGHLIGHTED);"),
    ("popup-no-highlight", BP,
     "    highlightCurrent(gf, p);" + NL + NL + "    y = bpopup_render",
     NL + "    y = bpopup_render"),
    ("popup-buttons-not-moved", BP,
     "    if (p->cfg.flags & BPOPUP_BUTTONS_BELOW)", "    if (0)"),
    ("popup-gap-nine", BP, "        + 10;", "        + 9;"),
    ("popup-labels-first", BP,
     "p->cfg.numButtons == 0 ? 0 : p->cfg.button[i]",
     "p->cfg.numButtons == 0 ? 0 : p->cfg.button[0]"),
    ("popup-untitled", BP,
     "    setLanguageID(gf, p->cfg.screen, BPOPUP_OBJ_TITLE, p->cfg.title);",
     "    setLanguageID(gf, p->cfg.screen, BPOPUP_OBJ_TITLE, 0);"),
    ("popup-bloom-first", BP,
     "    popupBloomItem(gf, p, currentItem(p)->hash);" + NL
     + "    p->tracedAnimate = 0;",
     "    popupBloomItem(gf, p, BPOPUP_OBJ_BUTTON1);" + NL
     + "    p->tracedAnimate = 0;"),
    ("popup-dismiss-keeps-screen", BP,
     "    if (!(p->cfg.flags & BPOPUP_KEEP_VISIBLE))" + NL
     + "        screenVisible(gf, p->cfg.screen, 0);",
     "    (void)0;"),
    ("popup-dismiss-silent", BP,
     "    data.noise = BSND_MENU_SELECT;", "    data.noise = BSND_NONE;"),
    ("popup-updown-horizontal", BP,
     "            case BJOY_SCROLL_UP:    ev = 0;                break;" + NL
     + "            case BJOY_SCROLL_DOWN:  ev = 0;                break;" + NL,
     ""),
    ("popup-left-is-down", BP,
     "            case BJOY_SCROLL_LEFT:  ev = BJOY_SCROLL_UP;   break;",
     "            case BJOY_SCROLL_LEFT:  ev = BJOY_SCROLL_DOWN; break;"),
    ("popup-right-is-up", BP,
     "            case BJOY_SCROLL_RIGHT: ev = BJOY_SCROLL_DOWN; break;",
     "            case BJOY_SCROLL_RIGHT: ev = BJOY_SCROLL_UP;   break;"),
    ("popup-up-no-wrap", BP,
     "            if ((int32_t)p->current < 0) p->current = n - 1;",
     "            if ((int32_t)p->current < 0) p->current = 0;"),
    ("popup-down-no-wrap", BP,
     "            if (!((int32_t)p->current < (int32_t)n)) p->current = 0;",
     "            if (!((int32_t)p->current < (int32_t)n)) p->current = n - 1;"),
    ("popup-up-silent", BP,
     "popupMoved(gf, p, port, BMSG_POPUP_NEXT, BSND_MENU_LEFT);",
     "popupMoved(gf, p, port, BMSG_POPUP_NEXT, BSND_NONE);"),
    ("popup-down-says-next", BP,
     "popupMoved(gf, p, port, BMSG_POPUP_PREV, BSND_MENU_RIGHT);",
     "popupMoved(gf, p, port, BMSG_POPUP_NEXT, BSND_MENU_RIGHT);"),
    ("popup-select-first-param", BP,
     "                uint32_t i = p->current % n;", "                uint32_t i = 0;"),
    ("popup-select-ignores-noselect", BP,
     "            if (!(p->cfg.flags & BPOPUP_NO_SELECT))", "            if (1)"),
    ("popup-back-dismisses", BP,
     "        case BJOY_MENU_BACK:" + NL
     + "            if (p->cfg.flags & BPOPUP_CANCELABLE)",
     "        case BJOY_MENU_BACK:" + NL + "            if (1)"),
    ("popup-start-ignored", BP,
     "        case BJOY_START:" + NL + "        case BJOY_MENU_SELECT:",
     "        case BJOY_MENU_SELECT:"),
    ("popup-joy-passes-on", BP, "        taken = 1;", "        taken = 0;"),
    ("popup-highlight-colour", BP,
     "#define ITEM_COLOR_HIGHLIGHT 0x80004080u",
     "#define ITEM_COLOR_HIGHLIGHT 0x00004080u"),
    ("popup-saved-colour-lost", BP,
     "        case 1u:  c = it->savedColor;          break;",
     "        case 1u:  c = ITEM_COLOR_GRAYED;       break;"),
    # RenderTextIntoGroup, 0x00144b58.
    ("rt-wrap-late", BP,
     "} else if (n < maxc - 2 && (n++, *p != '@')) {",
     "} else if (n < maxc - 1 && (n++, *p != '@')) {"),
    ("rt-at-not-break", BP,
     "            if (rtIsSpace(*p) || *p == '@') {",
     "            if (rtIsSpace(*p)) {"),
    ("rt-at-not-forced", BP, "(n++, *p != '@')", "(n++, 1)"),
    ("rt-break-kept", BP,
     "                p = lastBreak + 1;", "                p = lastBreak;"),
    ("rt-max-chars-first", BP,
     "                maxc = rtMaxChars(gf, screen, chunks[cur]);",
     "                (void)0;"),
    ("rt-hides-none", BP,
     "    for (i = next; i < count; i++) setVisible(gf, screen, chunks[i], 0);",
     "    (void)0;"),
    ("rt-bottom-of-last", BP,
     "    last = (next < RT_MAX_CHUNKS && chunks[next]) ? chunks[next]",
     "    last = 0 ? chunks[next]"),
    ("rt-height-dropped", BP,
     "        height = a->hooks.textScaledHeight(a->hooks.user, screen, last);",
     "        height = 0.0f;"),
    # ConsiderStartDemoMode, 0x0016ed50.
    ("demo-no-wait-loading", GF,
     "    if (gf->replayLoading) return;", "    (void)0;"),
    ("demo-never-plays", GF,
     "    if (gf->replayLoaded) {", "    if (0) {"),
    ("demo-replay-no-race", GF,
     "        HOOK_VOID0(gf, replayLaunch);" + NL + "    } else {",
     "        HOOK_VOID0(gf, replayLaunch);" + NL + "        return;" + NL
     + "    } else {"),
    ("demo-launching-races", GF,
     "        if (launching) return;", "        (void)launching;"),
    # The menus' movie: FlailerScreenList's StartMovie, UpdateMovie and
    # StopMovie (0x0016ce30, 0x0016d028, 0x0016d0a0), and their callers.
    ("movie-skip-ignored", GF,
     "    if (gf->skipMovies) return;" + NL + "    if (gf->panelMovie) {",
     "    if (gf->panelMovie) {"),
    ("movie-same-reopens", GF,
     "        if (strcmp(name, gf->panelMovieName) == 0) return;",
     "        (void)0;"),
    ("movie-loops-first-name", GF,
     "        gf->hooks.panelMovieOpen(gf->hooks.user, gf->panelMovieName);",
     "        gf->hooks.panelMovieOpen(gf->hooks.user, "
     "\"MOVIES\\\\mainmenu_movie.AVI\");"),
    ("movie-in-game-plays-on", GF,
     "    if (gf->hooks.inGame && gf->hooks.inGame(gf->hooks.user)) {",
     "    if (0) {"),
    ("movie-plays-once", GF,
     "        || gf->hooks.panelMovieUpdate(gf->hooks.user) == 1)",
     "        || 1)"),
    ("movie-reopens-every-frame", GF,
     "        || gf->hooks.panelMovieUpdate(gf->hooks.user) == 1)",
     "        || gf->hooks.panelMovieUpdate(gf->hooks.user) == 2)"),
    ("movie-stop-keeps-gate", GF,
     "    HOOK_VOID0(gf, movieClose);" + NL + "    gf->panelMovie = 0;",
     "    HOOK_VOID0(gf, movieClose);"),
    ("movie-stop-leaves-open", GF,
     "    HOOK_VOID0(gf, movieClose);" + NL + "    gf->panelMovie = 0;",
     "    gf->panelMovie = 0;"),
    ("movie-before-screen", GF,
     "    bgf_service(gf);" + NL
     + "    if (gf->screen) {" + NL
     + "        BScreenCallbackData data;" + NL
     + "        memset(&data, 0, sizeof(data));" + NL
     + "        data.itemHash = gf->screen->hash;" + NL
     + "        bgf_send(gf, BMSG_SCREEN_TICK, &data);" + NL
     + "    }" + NL
     + "    // FlailerScreenList::Tick (0x0016cca8) ticks both popups after the"
     + NL + "    // screen, up or not, then the movie and the song monitor." + NL
     + "    bpopup_tick(gf);" + NL
     + "    bgf_update_movie(gf);",
     "    bgf_service(gf);" + NL
     + "    bgf_update_movie(gf);" + NL
     + "    if (gf->screen) {" + NL
     + "        BScreenCallbackData data;" + NL
     + "        memset(&data, 0, sizeof(data));" + NL
     + "        data.itemHash = gf->screen->hash;" + NL
     + "        bgf_send(gf, BMSG_SCREEN_TICK, &data);" + NL
     + "    }" + NL
     + "    bpopup_tick(gf);"),
    ("movie-demo-plays-on", GF,
     "    bgf_stop_movie(gf);                // StartDemoMode's first call"
     + NL, ""),
    ("movie-demo-stops-late", GF,
     "    bgf_stop_movie(gf);                // StartDemoMode's first call"
     + NL + "    HOOK_VOID0(gf, startDemoMode);",
     "    HOOK_VOID0(gf, startDemoMode);" + NL + "    bgf_stop_movie(gf);"),
    ("movie-main-menu-silent", GF,
     "    bgf_start_movie(gf, \"MOVIES\\\\mainmenu_movie.AVI\");" + NL
     + "    HOOK_VOID(gf, easterEggs, 1);",
     "    HOOK_VOID(gf, easterEggs, 1);"),
    # NewMainMenu: TheEasterEggs started, and the "Unlocked Easter Egg"
    # group hidden, in the constructor; both undone in the destructor.
    ("main-menu-eggs-never-start", GF,
     "    HOOK_VOID(gf, easterEggs, 1);",
     "    (void)0;"),
    ("main-menu-eggs-never-stop", GF,
     "    HOOK_VOID(gf, easterEggs, 0);",
     "    (void)0;"),
    ("main-menu-egg-group-shown", GF,
     "    HOOK_VOID(gf, easterEggs, 1);" + NL
     + "    groupVisible(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_GROUP_EASTER_EGG, 0);",
     "    HOOK_VOID(gf, easterEggs, 1);" + NL
     + "    groupVisible(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_GROUP_EASTER_EGG, 1);"),
    ("main-menu-egg-hidden-before-movie", GF,
     "    bgf_start_movie(gf, \"MOVIES\\\\mainmenu_movie.AVI\");" + NL
     + "    HOOK_VOID(gf, easterEggs, 1);" + NL
     + "    groupVisible(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_GROUP_EASTER_EGG, 0);",
     "    groupVisible(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_GROUP_EASTER_EGG, 0);"
     + NL + "    bgf_start_movie(gf, \"MOVIES\\\\mainmenu_movie.AVI\");" + NL
     + "    HOOK_VOID(gf, easterEggs, 1);"),
    ("main-menu-dtor-keeps-group", GF,
     "    HOOK_VOID(gf, easterEggs, 0);" + NL
     + "    groupVisible(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_GROUP_EASTER_EGG, 0);",
     "    HOOK_VOID(gf, easterEggs, 0);"),
    ("main-menu-dtor-hides-first", GF,
     "    HOOK_VOID(gf, easterEggs, 0);" + NL
     + "    groupVisible(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_GROUP_EASTER_EGG, 0);",
     "    groupVisible(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_GROUP_EASTER_EGG, 0);"
     + NL + "    HOOK_VOID(gf, easterEggs, 0);"),
    ("main-menu-never-active", GF,
     "    m->active = 1;",
     "    (void)m;"),
    # Its BACK: Param and Noise both cleared -- a veto without a sound.
    ("main-menu-back-noisy", GF,
     "            data->noise = 0;" + NL
     + "            data->param = 0;" + NL
     + "            break;" + NL
     + "        case BMSG_SCREEN_TICK:",
     "            data->param = 0;" + NL
     + "            break;" + NL
     + "        case BMSG_SCREEN_TICK:"),
    ("main-menu-back-allowed", GF,
     "            data->noise = 0;" + NL
     + "            data->param = 0;" + NL
     + "            break;" + NL
     + "        case BMSG_SCREEN_TICK:",
     "            data->noise = 0;" + NL
     + "            break;" + NL
     + "        case BMSG_SCREEN_TICK:"),
    ("main-menu-cops-on-off", GF,
     "                    gf->copsOn = 1;",
     "                    gf->copsOn = 0;"),
    # Its OnHighlight: HighlightMenuItem's brackets, blurb and SelectionSet,
    # for the three items and nothing else.
    ("main-menu-highlight-ignored", GF,
     "            mainMenuHighlight(gf, data->itemHash);",
     "            (void)0;"),
    ("main-menu-highlight-wrong-mask", GF,
     "mainMenuHighlightItem(gf, BGF_MI_2_MASK, BGF_BLURB_MENUITEM_2);",
     "mainMenuHighlightItem(gf, BGF_MI_1_MASK, BGF_BLURB_MENUITEM_2);"),
    ("main-menu-highlight-wrong-blurb", GF,
     "mainMenuHighlightItem(gf, BGF_MI_3_MASK, BGF_BLURB_MENUITEM_3);",
     "mainMenuHighlightItem(gf, BGF_MI_3_MASK, BGF_BLURB_MENUITEM_1);"),
    ("main-menu-highlight-falls-through", GF,
     "BGF_BLURB_MENUITEM_1);" + NL
     + "            break;" + NL
     + "        case BGF_ITEM_MENUITEM_2:",
     "BGF_BLURB_MENUITEM_1);" + NL
     + "        case BGF_ITEM_MENUITEM_2:"),
    ("main-menu-highlight-default-moves", GF,
     "BGF_BLURB_MENUITEM_3);" + NL
     + "            break;" + NL
     + "        default:" + NL
     + "            break;",
     "BGF_BLURB_MENUITEM_3);" + NL
     + "            break;" + NL
     + "        default:" + NL
     + "            mainMenuHighlightItem(gf, BGF_MI_1_MASK, "
     + "BGF_BLURB_MENUITEM_1);" + NL
     + "            break;"),
    ("main-menu-brackets-swapped", GF,
     "BGF_SCREEN_NEW_MAIN_MENU, mask, -3.0f, -6.0f);",
     "BGF_SCREEN_NEW_MAIN_MENU, mask, -6.0f, -3.0f);"),
    ("main-menu-overscore-added", GF,
     "BGF_SCREEN_NEW_MAIN_MENU, mask, -3.0f, -6.0f);",
     "BGF_SCREEN_NEW_MAIN_MENU, mask, -3.0f, 6.0f);"),
    ("main-menu-blurb-first", GF,
     "    HOOK_VOID(gf, moveBrackets, BGF_SCREEN_NEW_MAIN_MENU, mask, -3.0f, "
     + "-6.0f);" + NL
     + "    if (a) banim_blurb_new_text_id(a, &m->blurb, blurb);" + NL
     + "    HOOK_VOID(gf, setBlurb, BGF_SCREEN_NEW_MAIN_MENU, blurb);",
     "    if (a) banim_blurb_new_text_id(a, &m->blurb, blurb);" + NL
     + "    HOOK_VOID(gf, setBlurb, BGF_SCREEN_NEW_MAIN_MENU, blurb);" + NL
     + "    HOOK_VOID(gf, moveBrackets, BGF_SCREEN_NEW_MAIN_MENU, mask, -3.0f, "
     + "-6.0f);"),
    ("main-menu-highlight-no-blurb", GF,
     "    HOOK_VOID(gf, setBlurb, BGF_SCREEN_NEW_MAIN_MENU, blurb);" + NL,
     ""),
    ("main-menu-highlight-no-select-set", GF,
     "    trace(gf, \"bracket %08x\", (unsigned)mask);" + NL,
     ""),
    # The constructor's four members, in retail's order, and the jukebox
    # between SelectionSet's constructor and its items.
    ("main-menu-blurb-wrong-bar", GF,
     "BGF_OBJ_SCROLLING_TEXT, BGF_OBJ_WHITEOUT_BAR);",
     "BGF_OBJ_WHITEOUT_BAR, BGF_OBJ_SCROLLING_TEXT);"),
    ("main-menu-bloom-wrong-object", GF,
     "    menuBloomInit(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_OBJ_ANIMATING_ITEM,",
     "    menuBloomInit(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_OBJ_PRESS_START,"),
    ("main-menu-bloom-wrong-color", GF,
     "                  BANIM_BLOOM_COLOR);" + NL + "    menuSlideInInit(",
     "                  0xffffffffu);" + NL + "    menuSlideInInit("),
    ("main-menu-bloom-before-blurb", GF,
     "    menuBlurbInit(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_OBJ_SCROLLING_TEXT,"
     + NL + "                  BGF_OBJ_SCROLLING_TEXT, BGF_OBJ_WHITEOUT_BAR);"
     + NL + "    menuBloomInit(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_OBJ_ANIMATING_ITEM,"
     + NL + "                  BANIM_BLOOM_COLOR);",
     "    menuBloomInit(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_OBJ_ANIMATING_ITEM,"
     + NL + "                  BANIM_BLOOM_COLOR);"
     + NL + "    menuBlurbInit(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_OBJ_SCROLLING_TEXT,"
     + NL + "                  BGF_OBJ_SCROLLING_TEXT, BGF_OBJ_WHITEOUT_BAR);"),
    ("main-menu-slide-wrong-mask", GF,
     "    menuSlideInInit(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_MI_1_MASK);",
     "    menuSlideInInit(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_MI_2_MASK);"),
    ("main-menu-slide-first", GF,
     "    menuBlurbInit(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_OBJ_SCROLLING_TEXT,"
     + NL + "                  BGF_OBJ_SCROLLING_TEXT, BGF_OBJ_WHITEOUT_BAR);"
     + NL + "    menuBloomInit(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_OBJ_ANIMATING_ITEM,"
     + NL + "                  BANIM_BLOOM_COLOR);"
     + NL + "    menuSlideInInit(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_MI_1_MASK);",
     "    menuSlideInInit(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_MI_1_MASK);"
     + NL + "    menuBlurbInit(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_OBJ_SCROLLING_TEXT,"
     + NL + "                  BGF_OBJ_SCROLLING_TEXT, BGF_OBJ_WHITEOUT_BAR);"
     + NL + "    menuBloomInit(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_OBJ_ANIMATING_ITEM,"
     + NL + "                  BANIM_BLOOM_COLOR);"),
    ("main-menu-no-challenge-cars", GF,
     "    trace(gf, \"challenge cars\");" + NL
     + "    HOOK_VOID0(gf, challengeCars);",
     "    HOOK_VOID0(gf, challengeCars);"),
    ("main-menu-no-race-defaults", GF,
     "    HOOK_VOID0(gf, challengeCars);" + NL
     + "    trace(gf, \"race defaults\");",
     "    HOOK_VOID0(gf, challengeCars);"),
    ("main-menu-defaults-swapped", GF,
     "    trace(gf, \"challenge cars\");" + NL
     + "    HOOK_VOID0(gf, challengeCars);" + NL
     + "    trace(gf, \"race defaults\");",
     "    trace(gf, \"race defaults\");" + NL
     + "    trace(gf, \"challenge cars\");" + NL
     + "    HOOK_VOID0(gf, challengeCars);"),
    ("loading-no-race-defaults", GF,
     "    // answer is kept for a debug print." + NL
     + "    trace(gf, \"race defaults\");",
     "    // answer is kept for a debug print."),
    ("main-menu-jukebox-silent", GF,
     "    HOOK_VOID(gf, jukebox, 1);    // the main menu's", "    (void)0;"),
    ("main-menu-jukebox-stops", GF,
     "    HOOK_VOID(gf, jukebox, 1);    // the main menu's",
     "    HOOK_VOID(gf, jukebox, 0);"),
    ("main-menu-jukebox-late", GF,
     "    HOOK_VOID(gf, jukebox, 1);    // the main menu's" + NL
     + "    // IndicatorMode 1",
     "    // IndicatorMode 1"),
    ("main-menu-indicator-mode-0", GF,
     "    bsel_set_indicator_mode(&m->sel, 1);",
     "    bsel_set_indicator_mode(&m->sel, 0);"),
    ("main-menu-indicator-after-items", GF,
     "    bsel_set_indicator_mode(&m->sel, 1);" + NL
     + "    menuSelAddItems(gf, BGF_SCREEN_NEW_MAIN_MENU, kMainMenuMasks, 5);",
     "    menuSelAddItems(gf, BGF_SCREEN_NEW_MAIN_MENU, kMainMenuMasks, 5);"
     + NL + "    bsel_set_indicator_mode(&m->sel, 1);"),
    ("main-menu-three-masks", GF,
     "kMainMenuMasks, 5);", "kMainMenuMasks, 3);"),
    ("main-menu-masks-short", GF,
     "    BGF_MI_1_MASK, BGF_MI_2_MASK, BGF_MI_3_MASK, BGF_MI_4_MASK, "
     + "BGF_MI_5_MASK,",
     "    BGF_MI_1_MASK, BGF_MI_2_MASK, BGF_MI_3_MASK, 0, 0,"),
    # OnHighlight's first call, the echo, with every hash; OnTick's three
    # Animates; the destructor's members, after the eggs.
    ("main-menu-no-echo", GF,
     "    menuBloomSetItem(gf, itemHash);" + NL + "    switch (itemHash) {",
     "    switch (itemHash) {"),
    ("main-menu-echo-last", GF,
     "    menuBloomSetItem(gf, itemHash);" + NL + "    switch (itemHash) {"
     + NL + "        case BGF_ITEM_MENUITEM_1:" + NL
     + "            mainMenuHighlightItem(gf, BGF_MI_1_MASK, BGF_BLURB_MENUITEM_1);"
     + NL + "            break;",
     "    switch (itemHash) {"
     + NL + "        case BGF_ITEM_MENUITEM_1:" + NL
     + "            mainMenuHighlightItem(gf, BGF_MI_1_MASK, BGF_BLURB_MENUITEM_1);"
     + NL + "            menuBloomSetItem(gf, itemHash);"
     + NL + "            break;"),
    ("main-menu-echo-known-only", GF,
     "    menuBloomSetItem(gf, itemHash);" + NL + "    switch (itemHash) {"
     + NL + "        case BGF_ITEM_MENUITEM_1:" + NL,
     "    switch (itemHash) {" + NL + "        case BGF_ITEM_MENUITEM_1:" + NL
     + "            menuBloomSetItem(gf, itemHash);" + NL),
    ("main-menu-no-tick", GF,
     "            mainMenuTick(gf);", "            (void)0;"),
    ("main-menu-dtor-keeps-kit", GF,
     "    trace(gf, \"menu kit released\");" + NL, ""),
    ("main-menu-kit-before-eggs", GF,
     "    HOOK_VOID(gf, easterEggs, 0);" + NL
     + "    groupVisible(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_GROUP_EASTER_EGG, 0);"
     + NL + "    if (a) {" + NL
     + "        banim_slide_release(a, &m->slideIn);" + NL
     + "        banim_blurb_release(a, &m->blurb);" + NL
     + "    }" + NL
     + "    trace(gf, \"menu kit released\");" + NL,
     "    if (a) {" + NL
     + "        banim_slide_release(a, &m->slideIn);" + NL
     + "        banim_blurb_release(a, &m->blurb);" + NL
     + "    }" + NL
     + "    trace(gf, \"menu kit released\");" + NL
     + "    HOOK_VOID(gf, easterEggs, 0);" + NL
     + "    groupVisible(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_GROUP_EASTER_EGG, 0);"
     + NL),
]


# Mutations that survive because they change nothing the transcript can tell.
# back-names-screen: nothing the boot reaches reads ItemHash on BACK -- the
# title, the language screen and the main menu do not -- so it is kept as
# retail's memset and not as a behaviour.
# mc-loadfailed-quiet: the message before LOAD_FAILED is "Loading", taken
# down in READING_FILE, which the loader silences as it does READY_TO_LEAVE
# -- so its two orders sound the same there, and the port keeps retail's.
# mc-autoload-plays-on: BootAutoload is the first screen of the boot, before
# the main menu starts the first panel movie, so its StopMovie never finds
# one; the movie it is for is the Options screen's, whose manual load is
# not ported.
# lsw-menu-live-while-saving: while the saver works the wrapper's menu is
# hidden and a popup is up, which takes every button (popup-joy-passes-on),
# so the only message that reaches the menu's half is TICK -- and the bloom
# it animates is on the hidden screen and traced once per item.
EQUIVALENT = {"back-names-screen", "mc-loadfailed-quiet",
              "mc-autoload-plays-on", "lsw-menu-live-while-saving"}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    py_lines = []
    for sc in SCENARIOS:
        py_lines.extend(run_scenario(sc))
    with tempfile.TemporaryDirectory() as tmp:
        base = c_transcript(hostbuild.build(tmp, SOURCES, "gameflow_test"),
                            SCENARIOS)
    if not isinstance(base, list) or count_diff(base, py_lines)[1]:
        print("base already differs -- fix that before mutating")
        return 1

    caught, survived, missing, equivalent = 0, [], [], []
    for name, rel, before, after in todo:
        path = os.path.join(ROOT, rel)
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
        crlf = "\r\n" in text
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if text.count(probe) != 1:
            missing.append(name)
            print("  %-34s PATTERN %s" % (
                name, "NOT FOUND" if not text.count(probe) else "NOT UNIQUE"))
            continue
        try:
            hostbuild.write_source(path, text.replace(probe, repl, 1))
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = hostbuild.build(tmp, SOURCES, "gameflow_test")
                except SystemExit:
                    print("  %-34s did not compile (caught)" % name)
                    caught += 1
                    continue
                got = c_transcript(exe, SCENARIOS)
            if got == HARNESS_HUNG:
                print("  %-34s hung the harness (caught)" % name)
                caught += 1
            elif not isinstance(got, list):
                print("  %-34s crashed the harness (caught)" % name)
                caught += 1
            else:
                n = count_diff(got, py_lines)[1]
                if n:
                    print("  %-34s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-34s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-34s SURVIVED" % name)
                    survived.append(name)
        finally:
            try:
                hostbuild.write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))

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
    ap.add_argument("--scenario", action="append",
                    help="one scenario name; repeatable (default: all)")
    ap.add_argument("--dump", help="write both transcripts next to this path")
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    args = ap.parse_args()

    bad = retail_title_movies()
    for line in bad:
        print(line)
    if bad:
        return 1

    if args.mutate:
        return mutate_pass(args.only.split(",") if args.only else None)

    names = args.scenario or [s["name"] for s in SCENARIOS]
    chosen = [s for s in SCENARIOS if s["name"] in names]
    if len(chosen) != len(names):
        sys.exit("unknown scenario in %s" % names)

    with tempfile.TemporaryDirectory() as tmp:
        c_lines = c_transcript(hostbuild.build(tmp, SOURCES, "gameflow_test"),
                               chosen)
        if not isinstance(c_lines, list):
            sys.exit("gameflow_test failed")

    py_lines = []
    for sc in chosen:
        py_lines.extend(run_scenario(sc))

    if args.dump:
        with open(args.dump + ".c.txt", "w") as fh:
            fh.write("\n".join(c_lines) + "\n")
        with open(args.dump + ".py.txt", "w") as fh:
            fh.write("\n".join(py_lines) + "\n")

    diff, ndiff = count_diff(c_lines, py_lines)
    for line in diff[:80]:
        print(line)
    if len(diff) > 80:
        print("... %d more diff lines" % (len(diff) - 80))
    print("%d scenarios, %d lines, %d differ"
          % (len(chosen), len(c_lines), ndiff))
    return 1 if ndiff else 0


if __name__ == "__main__":
    sys.exit(main())
