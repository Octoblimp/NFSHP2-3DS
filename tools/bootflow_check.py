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
the language screen, LanguageOptionsScreenBase (RetailLanguage).

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
           "3DS Files/source/banim.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c"]

# ScreenMessage
MENUITEM_SELECT = 1
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
(NONE, LOADING_FRONTEND, UNLOADING_FRONTEND, IN_FRONTEND,
 LOADING_TRACK_COMMON, LOADING_TRACK_SPECIFIC, RACING,
 UNLOADING_TRACK_SPECIFIC, UNLOADING_TRACK_COMMON, EXIT_DEMO_DISC) = range(10)

STATE_NAMES = [
    "NONE", "LOADING_FRONTEND", "UNLOADING_FRONTEND", "IN_FRONTEND",
    "LOADING_TRACK_COMMON", "LOADING_TRACK_SPECIFIC", "RACING",
    "UNLOADING_TRACK_SPECIFIC", "UNLOADING_TRACK_COMMON", "EXIT_DEMO_DISC",
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
BOOT_AUTOLOAD = 0xfa2ac5c6
MUMBO_JUMBO = 0xdd4197c9
LOADING_TRACK = 0xd0131dd1
FIRSTLEGAL, SLIDE2, DISCLAIMER = 0x8139ec90, 0xa7227ae8, 0x8254cc20

PLANE_43, PLANE_LB, PRESS_START = 0x3acf2d73, 0xbfaebf79, 0xb070dbc9
TITLE_IMAGE = 0xb73c8d23        # bStringHash("TITLE_IMAGE"), a group
MUMBO_PLANE = 0xdd479599
TEX_LEGAL, TEX_ANTIPIRACY = 0xa7ebc389, 0x38258033

STACK_DEPTH, NAME_LEN = 12, 32

# The world the harness simulates, same constants as tools/src/gameflow_test.c
MOVIE_FRAMES, LOADER_FRAMES, TEXTURE_POLLS, SAVE_POLLS = 5, 1, 2, 2
MAX_PENDING = 4

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
        self.begin_screen_fade_time = 0

        self.frontend_launch_type = sc["frontendLaunchType"]
        self.demo_mode_status = sc["demoModeStatus"]
        self.skip_movies = sc["skipMovies"]
        self.cops_on = 0
        self.video_mode = sc["videoMode"]
        self.demo_disc = sc["demoDiscActive"]
        self.force_legal = sc.get("forceLegal", 0)

        self.legal_timeout = 7.0
        self.antipiracy_timeout = 7.0
        self.begin_demo_timeout = 30.0

        # MumboJumboScreen / BootAutoLoader instance state; TitleScreen's
        # lives in the emulated image
        self.title = RetailTitle(self)
        self.loading = RetailLoading(self)
        self.language = RetailLanguage(self)
        self.m_state = 0
        self.m_timer = 0
        self.a_state = 0

        # the simulated world
        self.movie_playing = 0
        self.movie_left = 0
        self.tex_polls = 0
        self.save_polls = 0
        self.pending = []                 # loads in flight: (what, callback)
        self.loader_due = LOADER_FRAMES   # nothing lands before this frame
        self.active_item = ITEM_MENUITEM_1

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
                self.send(SCREEN_ACTIVATE, {"itemHash": found[1], "port": 0,
                                            "param": 0, "noise": 0})
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

    # Ten states; only LOADING_FRONTEND and UNLOADING_FRONTEND do anything.
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
        self.service()

    def begin_unloading_frontend(self):
        self.change_to_screen(None, 0)
        self.reset_stack()

    # -- LaunchFrontendMenus ----------------------------------------------
    def should_see_title_sequence(self):
        return 1 if 0 <= self.frontend_launch_type - 1 < 2 else 0

    def should_see_legal_mumbo_jumbo(self):
        return 0

    def should_see_language_select(self):
        if self.frontend_launch_type == 1 and self.curr_language == -1:
            return 1
        if self.demo_disc:
            return 0
        if self.video_mode != 0:       # MODE_NTSC never asks
            return 0
        return 1 if self.frontend_launch_type == 1 else 0

    def should_see_autoload(self):
        if self.demo_disc:
            return 0
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

    def consider_start_demo_mode(self, since):
        idle = f32(f32((self.real_timer - since) & 0xffffffff)
                   * f32(1.0 / 4000.0))
        if idle <= self.begin_demo_timeout:
            return
        self.say("demo mode")
        self.say("attract")

    # -- the boot screens ---------------------------------------------------
    def main_menu(self, msg, data):
        """NewMainMenu::HandleEvent, 0x00203768 -- SELECT and nothing else."""
        if msg != MENUITEM_SELECT:
            return
        if data["itemHash"] == ITEM_MENUITEM_1:
            self.cops_on = 1
            self.change_to_screen("Cops On Mode Select", 1)
        elif data["itemHash"] == ITEM_MENUITEM_2:
            self.cops_on = 0
            self.change_to_screen("Cops Off Mode Select", 1)
        elif data["itemHash"] == ITEM_MENUITEM_3:
            self.change_to_screen("Options", 1)

    def dispatch(self, kind, msg, data):
        if kind == "title":
            self.title.callback(msg, data)
        elif kind == "mainmenu":
            self.main_menu(msg, data)
        elif kind == "mumbo":
            self.mumbo(msg, data)
        elif kind == "autoload":
            self.autoload(msg, data)
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

    def autoload(self, msg, data):
        if msg == SCREEN_ACTIVATE:
            self.a_state = 1
            self.save_polls = 0
            self.movie_close()
            self.say("autoload start")
            return
        if msg == SCREEN_UNACTIVATE:
            self.a_state = 0
            return
        if msg != SCREEN_TICK:
            return
        if self.a_state in (1, 2):
            self.save_polls += 1
            if self.save_polls >= SAVE_POLLS:
                self.a_state = 0
                self.say("autoload done")
        if self.a_state == 0:
            self.move_back_screen(1)


# ------------------------------------------------------ retail's TitleScreen

RETAIL_GP = 0x003358f0
REAL_TIMER = RETAIL_GP - 19608          # RealTimer, 1/4000 s
SKIP_MOVIES = RETAIL_GP - 23036
THE_TITLE = RETAIL_GP - 21156           # the one TitleScreen instance
DEMO_DISC = 0x002effe0                  # DemoDiscManager, +0 is IsActive
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
    and bStringHash -- which is exactly the part the port rewrote.

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
            0x0012eaf0: lambda _e: f.sc.get("demoAttractMode", 0),
            0x00184de0: lambda _e: f.say("demo disc game"),
            # ConsiderStartDemoMode(&timer), the flow's -- it is not this
            # screen's, and is shared with the rest of the frontend.
            0x0016ed50: lambda _e: f.consider_start_demo_mode(
                e.u32(arg(0))),
        }
        for addr, fn in stubs.items():
            e.stub(addr, fn)

    def callback(self, msg, data):
        e, f = self.e, self.flow
        self._stubs()
        lang = f.curr_language if 0 <= f.curr_language <= 7 else 0
        e.put32(REAL_TIMER, f.real_timer)
        e.put32(SKIP_MOVIES, f.skip_movies)
        e.put32(DEMO_DISC, f.demo_disc)
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
            0x001ed5c8: nothing,
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
        e.put32(DEMO_DISC, f.demo_disc)
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


SIXTIETH = 1.0 / 60.0

# Same rows as kScenarios[] in tools/src/gameflow_test.c.
SCENARIOS = [
    dict(name="ntsc", videoMode=1, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=0, frames=40, dt=SIXTIETH, input=[]),
    dict(name="pal", videoMode=0, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=0, frames=40, dt=SIXTIETH, input=[]),
    dict(name="nolang", videoMode=1, currLanguage=-1, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=0, frames=40, dt=SIXTIETH,
         input=[(10, "back"), (14, "item5")]),
    dict(name="skipmovies", videoMode=1, currLanguage=0, skipMovies=1,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=0, frames=30, dt=SIXTIETH, input=[]),
    dict(name="relaunch", videoMode=1, currLanguage=0, skipMovies=0,
         frontendLaunchType=2, demoModeStatus=2, demoDiscActive=0,
         haveIntroMovie=0, frames=20, dt=SIXTIETH, input=[(10, "back")]),
    dict(name="demodisc", videoMode=1, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=1,
         haveIntroMovie=0, frames=700, dt=SIXTIETH,
         input=[(0, "slow600")]),
    dict(name="attract", videoMode=1, currLanguage=0, skipMovies=1,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=0, frames=40, dt=1.0, input=[]),
    dict(name="select", videoMode=1, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=0, frames=300, dt=SIXTIETH,
         input=[(14, "select"), (270, "select"), (282, "select"),
                (288, "back"), (292, "back")]),
    dict(name="skipintro", videoMode=1, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=1, frames=300, dt=SIXTIETH,
         input=[(5, "select"), (10, "select"), (20, "select"),
                (21, "start"), (262, "select")]),
    dict(name="skipidle", videoMode=1, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=1, frames=50, dt=1.0, input=[(10, "select")]),
    dict(name="restidle", videoMode=1, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=0, frames=50, dt=1.0, input=[]),
    dict(name="mainmenu", videoMode=1, currLanguage=0, skipMovies=1,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=0, frames=40, dt=SIXTIETH,
         input=[(4, "select"), (8, "item3"), (12, "back"), (16, "item1")]),
    dict(name="mumbo", videoMode=1, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=0, frames=30, dt=SIXTIETH, input=[(12, "mumbo")]),
    # The same with the two dead predicates turned on, so the legal and
    # anti-piracy panels and their 7-second timers actually run.
    dict(name="legal", videoMode=1, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=0, forceLegal=1, frames=40, dt=1.0,
         input=[(5, "mumbo")]),
    dict(name="french", videoMode=1, currLanguage=1, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=0, frames=30, dt=SIXTIETH, input=[]),
    dict(name="palselect", videoMode=0, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=0, frames=30, dt=SIXTIETH, input=[(8, "item2")]),
    dict(name="palback", videoMode=0, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=0, frames=30, dt=SIXTIETH,
         input=[(7, "hl4"), (8, "back")]),
    dict(name="palall", videoMode=0, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=0, frames=30, dt=SIXTIETH, input=[(8, "item7")]),
    dict(name="palsame", videoMode=0, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=0, frames=30, dt=SIXTIETH, input=[(8, "item1")]),
    dict(name="palrevert", videoMode=0, currLanguage=1, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=0, frames=30, dt=SIXTIETH, input=[(8, "item1")]),
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
            if what == "select":
                f.screen_event(MENUITEM_SELECT, 0)
            elif what == "start":
                f.screen_event(SCREEN_START_BUTTON, 0)
            elif what == "back":
                f.back_button(0)
            elif what.startswith("item"):
                n = ord(what[4]) - ord("1")
                f.menu_item_event(MENUITEM_SELECT, ITEM_MENUITEM_1 + n, 0)
            elif what.startswith("hl"):
                f.active_item = ITEM_MENUITEM_1 + ord(what[2]) - ord("1")
            elif what.startswith("slow"):
                f.loader_due = int(what[4:])
            elif what == "mumbo":
                f.push("New Main Menu")
                f.change_to_screen("Legal MumboJumbo", 0)
        f.frame(sc["dt"])
        f.service_loads()
        out.append("frame %d %u %u" % (frame, f.real_time, f.real_timer))
    out.append("final %s %s %d cops %d language %d"
               % (STATE_NAMES[f.current],
                  f.screen[0] if f.screen else "-", f.index, f.cops_on,
                  f.curr_language))
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
     "if (!titlePressStartReady(gf) || gf->demoDiscActive) {",
     "if (gf->demoDiscActive) {"),
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
     "                if (!gf->demoDiscActive) HOOK_VOID(gf, jukebox, 1);",
     "                (void)0;"),
    ("tick-rest-keeps-timer", GF,
     "                t->mode    = 1;" + NL
     + "                t->timer   = gf->realTimer;",
     "                t->mode    = 1;"),
    ("tick-no-bloom", GF,
     "        titleBloomAnimate(gf);" + NL + "    }",
     "    }"),
    ("tick-no-demo-mode", GF,
     "            bgf_consider_start_demo_mode(gf, t->timer);",
     "            (void)0;"),
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
     "        screenVisible(gf, BGF_SCREEN_LOADING_TRACK, 1);",
     "        screenVisible(gf, BGF_SCREEN_LOADING_TRACK, 0);"),
    ("lgc-no-copyright", GF,
     "        objectVisible(gf, BGF_SCREEN_LOADING_TRACK, BGF_OBJ_COPYRIGHT, 1);",
     "        (void)0;"),
    ("lgc-demo-disclaimer-first", GF,
     "        screenVisible(gf, BGF_SCREEN_FIRSTLEGAL, 1);",
     "        screenVisible(gf, BGF_SCREEN_DISCLAIMER, 1);"),
    # BeginGameFlowLoadingFrontend, 0x00168698, and its callbacks.
    ("begin-fade-zero", GF,
     "    gf->beginScreenFadeTime = gf->realTime;",
     "    gf->beginScreenFadeTime = 0;"),
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
    # The Loop's slideshow, 0x00168718.
    ("loop-541", GF,
     "if (!gf->demoDiscActive || elapsed >= 541) return;",
     "if (!gf->demoDiscActive || elapsed >= 540) return;"),
    ("loop-361", GF,
     "    if (elapsed >= 361) {", "    if (elapsed >= 362) {"),
    ("loop-181", GF,
     "    } else if (elapsed >= 181) {", "    } else if (elapsed >= 180) {"),
    ("loop-slide2-kept", GF,
     "        screenVisible(gf, BGF_SCREEN_SLIDE2, 0);" + NL
     + "        screenVisible(gf, BGF_SCREEN_DISCLAIMER, 1);",
     "        screenVisible(gf, BGF_SCREEN_DISCLAIMER, 1);"),
    # End, 0x001687a8.
    ("end-copyright-left", GF,
     "        objectVisible(gf, BGF_SCREEN_LOADING_TRACK, BGF_OBJ_COPYRIGHT, 0);",
     "        (void)0;"),
    ("end-loading-left", GF,
     "        screenVisible(gf, BGF_SCREEN_LOADING_TRACK, 0);" + NL
     + "        objectVisible(gf, BGF_SCREEN_LOADING_TRACK, BGF_OBJ_COPYRIGHT, 0);",
     "        objectVisible(gf, BGF_SCREEN_LOADING_TRACK, BGF_OBJ_COPYRIGHT, 0);"),
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
     + "            bgf_send(gf, BMSG_SCREEN_ACTIVATE, &data);",
     "            memset(&data, 0, sizeof(data));" + NL
     + "            data.itemHash = n->hash;" + NL
     + "            bgf_send(gf, BMSG_SCREEN_ACTIVATE, &data);" + NL
     + "            HOOK_VOID(gf, openScreen, n);"),
]

# Mutations that survive because they change nothing the transcript can tell.
# back-names-screen: nothing the boot reaches reads ItemHash on BACK -- the
# title and the language screen do not -- so it is kept as retail's memset
# and not as a behaviour.
EQUIVALENT = {"back-names-screen"}


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
