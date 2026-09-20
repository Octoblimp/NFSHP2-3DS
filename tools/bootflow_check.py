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

Usage:
    python tools/bootflow_check.py                  # all scenarios
    python tools/bootflow_check.py --scenario ntsc
    python tools/bootflow_check.py --dump out.txt   # keep both transcripts
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
           "3DS Files/source/gameflow.c"]

# ScreenMessage
MENUITEM_SELECT = 1
MENUITEM_PAD_LEFT, MENUITEM_PAD_RIGHT = 6, 7
MENUITEM_PAD_UP, MENUITEM_PAD_DOWN = 8, 9
MENUITEM_SQUARE = 10
SCREEN_ACTIVATE, SCREEN_UNACTIVATE = 11, 12
SCREEN_START_BUTTON = 13
SCREEN_BACK_BUTTON = 17
SCREEN_TICK = 18

FE_SOUND_MENU_CANCEL = 6

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
LANGUAGE = 0x632b068e
BOOT_AUTOLOAD = 0xfa2ac5c6
MUMBO_JUMBO = 0xdd4197c9
LOADING_TRACK = 0xd0131dd1
FIRSTLEGAL, SLIDE2, DISCLAIMER = 0x8139ec90, 0xa7227ae8, 0x8254cc20

PLANE_43, PLANE_LB, PRESS_START = 0x3acf2d73, 0xbfaebf79, 0xb070dbc9
MUMBO_PLANE = 0xdd479599
TEX_LEGAL, TEX_ANTIPIRACY = 0xa7ebc389, 0x38258033

STACK_DEPTH, NAME_LEN = 12, 32

# The world the harness simulates, same constants as tools/src/gameflow_test.c
MOVIE_FRAMES, LOADER_FRAMES, TEXTURE_POLLS, SAVE_POLLS = 5, 3, 2, 2

EALOGO_EN = "MOVIES\\INTRO\\EALOGO_EN.AVI"
NFSINTRO_EN = "MOVIES\\INTRO\\NFSINTRO_EN.AVI"


def f32(x):
    """C `float` arithmetic. The clock truncates, so the rounding matters."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


# TitleMoviesToPlay, 0x002f3770: eight language rows of two.
TITLE_MOVIES = [
    [(EALOGO_EN, 0), (NFSINTRO_EN, 1)],
    [("MOVIES\\INTRO\\EALOGO_FR.AVI", 0), (NFSINTRO_EN, 1)],
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
        self.frame_counter = 0
        self.accum = 0.0
        self.begin_screen_fade_time = 0

        self.frontend_launch_type = sc["frontendLaunchType"]
        self.demo_mode_status = sc["demoModeStatus"]
        self.skip_movies = sc["skipMovies"]
        self.cops_on = 0
        self.video_mode = sc["videoMode"]
        self.curr_language = sc["currLanguage"]
        self.demo_disc = sc["demoDiscActive"]
        self.force_legal = sc.get("forceLegal", 0)
        self.need_to_set_language = 0

        self.legal_timeout = 7.0
        self.antipiracy_timeout = 7.0
        self.begin_demo_timeout = 30.0

        # TitleScreen / MumboJumboScreen / BootAutoLoader instance state
        self.t_index = self.t_mode = 0
        self.t_timer = 0
        self.t_playing = 0
        self.m_state = 0
        self.m_timer = 0
        self.a_state = 0

        # the simulated world
        self.movie_left = 0
        self.tex_polls = 0
        self.save_polls = 0

    # -- transcript ------------------------------------------------------
    def say(self, line):
        self.out.append(line)

    # -- the registry ----------------------------------------------------
    # FlailerScreenConfig, the subset the boot names. `name` is the C++
    # literal, the hash is bStringHash of the authored name.
    SCREENS = [
        ("BootAutoload", BOOT_AUTOLOAD, "autoload"),
        ("Language Options Pre FE", LANGUAGE, "plain"),
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
        self.movie_left = MOVIE_FRAMES
        return 1

    def movie_drive(self):
        if self.movie_left > 0:
            self.movie_left -= 1
        return 1 if self.movie_left == 0 else 0

    def movie_close(self):
        self.movie_left = 0

    def resources_ready(self):
        return self.frame_counter >= LOADER_FRAMES

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
        data = {"itemHash": item_hash, "port": port, "param": 1, "noise": 0}
        if not self.send(msg, data):
            return 0
        self.sound(data["noise"])
        return 1

    def screen_event(self, msg, port=0):
        data = {"itemHash": self.screen[1] if self.screen else 0,
                "port": port, "param": 1, "noise": 0}
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
                self.say("ui enter %08x" % found[1])
                self.say("enter %s %08x" % (found[0], found[1]))
                self.send(SCREEN_ACTIVATE, {"itemHash": found[1], "port": 0,
                                            "param": 0, "noise": 0})
        return 1 if self.screen else 0

    def move_to_previous_screen(self, n, send_back, port):
        data = {"itemHash": self.screen[1] if self.screen else 0,
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

    def move_back_screen(self, n):
        return self.move_to_previous_screen(n, 1, 0)

    # -- the flow ----------------------------------------------------------
    def change_state(self, desired, _pending=NONE):
        self.desired = desired
        self.say("want %s" % STATE_NAMES[desired])

    # Ten states; only LOADING_FRONTEND and UNLOADING_FRONTEND do anything.
    def state_fns(self, state):
        if state == LOADING_FRONTEND:
            return (self.begin_loading_frontend, self.end_loading_frontend,
                    self.loop_loading_frontend)
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
        self.frame_counter += 1

    def frame(self, dt):
        self.advance_time(dt)
        self.service()
        if self.screen:
            self.send(SCREEN_TICK, {"itemHash": self.screen[1], "port": 0,
                                    "param": 0, "noise": 0})
        self.service()

    # -- GAMEFLOW_STATE_LOADING_FRONTEND -----------------------------------
    def begin_loading_frontend(self):
        self.begin_screen_fade_time = 0
        self.say("load FRONTEND\\FRONTA.BUN")
        if self.curr_language == -1:
            self.need_to_set_language = 1
        self.say("language %d" % (self.curr_language
                                  if self.curr_language >= 0 else 0))
        self.say("load FRONTEND\\FRONTB.BUN")

    def loop_loading_frontend(self):
        elapsed = (self.real_time - self.begin_screen_fade_time) & 0xffffffff
        if self.demo_disc and elapsed < 541:
            if elapsed >= 361:
                self.screen_visible(SLIDE2, 0)
                self.screen_visible(DISCLAIMER, 1)
            elif elapsed >= 181:
                self.screen_visible(FIRSTLEGAL, 0)
                self.screen_visible(SLIDE2, 1)
            return
        if not self.resources_ready():
            return
        if self.need_to_set_language:
            self.say("language %d" % -1)
            self.need_to_set_language = 0
        self.change_state(IN_FRONTEND)

    def end_loading_frontend(self):
        self.screen_visible(DISCLAIMER if self.demo_disc else LOADING_TRACK, 0)
        self.launch_frontend_menus()

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
            self.title(msg, data)
        elif kind == "mainmenu":
            self.main_menu(msg, data)
        elif kind == "mumbo":
            self.mumbo(msg, data)
        elif kind == "autoload":
            self.autoload(msg, data)

    def num_title_movies(self):
        return 1 if self.demo_disc else 2

    def title_movie(self, i):
        lang = self.curr_language
        if lang < 0 or lang > 7:
            lang = 0
        return TITLE_MOVIES[lang][0 if i < 0 or i > 1 else i]

    def title_open(self, index):
        name, letterboxed = self.title_movie(index)
        self.t_playing = 0
        if name is None:
            self.say("movie none %d" % index)
        elif self.movie_open(name):
            self.t_playing = 1
            self.say("movie open %s" % name)
        else:
            self.say("movie missing %s" % name)
        self.object_visible(TITLE, PLANE_LB if letterboxed else PLANE_43, 1)

    def title_drive(self):
        return 1 if not self.t_playing else self.movie_drive()

    def title(self, msg, data):
        if msg == SCREEN_ACTIVATE:
            self.t_index = 0
            self.t_playing = 0
            if self.skip_movies:
                self.t_mode = 1
                self.t_timer = self.real_timer
                self.say("jukebox 1")
                return
            self.t_mode = 2
            self.title_open(0)
            self.object_visible(TITLE, PRESS_START, 0)
            return

        if msg == SCREEN_UNACTIVATE:
            if self.t_playing:
                self.movie_close()
                self.t_playing = 0
            self.t_index = self.t_mode = 0
            self.t_timer = 0
            return

        if msg == SCREEN_TICK:
            if self.t_mode == 2:
                if self.title_drive() != 1:
                    return
                self.t_index += 1
                if self.demo_disc:
                    self.screen_visible(TITLE, 0)
                else:
                    self.object_visible(TITLE, PRESS_START, 1)
                if self.t_playing:
                    self.movie_close()
                    self.t_playing = 0
                self.object_visible(TITLE, PLANE_43, 0)
                self.object_visible(TITLE, PLANE_LB, 0)
                if self.t_index == self.num_title_movies():
                    self.t_timer = self.real_timer
                    self.t_mode = 1
                    self.say("title idle")
                    if not self.demo_disc:
                        self.say("jukebox 1")
                    return
                self.title_open(self.t_index)
                return
            if self.t_mode == 1:
                self.consider_start_demo_mode(self.t_timer)
            return

        if msg == MENUITEM_SELECT:
            # The EA logo cannot be skipped: during movie 0 the index is 0.
            if self.t_mode == 1 or (self.t_mode == 2 and self.t_index != 0):
                if self.demo_disc:
                    data["noise"] = 0
                    return
                self.change_to_screen("New Main Menu", 1)
            data["noise"] = 0
            return

        if msg in (MENUITEM_PAD_LEFT, MENUITEM_PAD_RIGHT, MENUITEM_PAD_UP,
                   MENUITEM_PAD_DOWN, MENUITEM_SQUARE, SCREEN_START_BUTTON):
            data["noise"] = 0
            return

        if msg == SCREEN_BACK_BUTTON:
            data["param"] = 0
            data["noise"] = 0

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
         haveIntroMovie=0, frames=40, dt=SIXTIETH, input=[]),
    dict(name="skipmovies", videoMode=1, currLanguage=0, skipMovies=1,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=0, frames=30, dt=SIXTIETH, input=[]),
    dict(name="relaunch", videoMode=1, currLanguage=0, skipMovies=0,
         frontendLaunchType=2, demoModeStatus=2, demoDiscActive=0,
         haveIntroMovie=0, frames=20, dt=SIXTIETH, input=[(10, "back")]),
    dict(name="demodisc", videoMode=1, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=1,
         haveIntroMovie=0, frames=700, dt=SIXTIETH, input=[]),
    dict(name="attract", videoMode=1, currLanguage=0, skipMovies=1,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=0, frames=40, dt=1.0, input=[]),
    dict(name="select", videoMode=1, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=0, frames=40, dt=SIXTIETH,
         input=[(14, "select"), (26, "select"), (32, "back"),
                (36, "back")]),
    dict(name="skipintro", videoMode=1, currLanguage=0, skipMovies=0,
         frontendLaunchType=1, demoModeStatus=0, demoDiscActive=0,
         haveIntroMovie=1, frames=40, dt=SIXTIETH,
         input=[(5, "select"), (10, "select")]),
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
]


def run_scenario(sc):
    out = ["scenario %s" % sc["name"]]
    f = Flow(sc, out)
    f.change_state(LOADING_FRONTEND)
    for frame in range(sc["frames"]):
        for at, what in sc["input"]:
            if at != frame:
                continue
            out.append("input %s" % what)
            if what == "select":
                f.screen_event(MENUITEM_SELECT, 0)
            elif what == "back":
                f.move_back_screen(1)
            elif what.startswith("item"):
                n = ord(what[4]) - ord("1")
                f.menu_item_event(MENUITEM_SELECT, ITEM_MENUITEM_1 + n, 0)
            elif what == "mumbo":
                f.push("New Main Menu")
                f.change_to_screen("Legal MumboJumbo", 0)
        f.frame(sc["dt"])
        out.append("frame %d %u %u" % (frame, f.real_time, f.real_timer))
    out.append("final %s %s %d cops %d"
               % (STATE_NAMES[f.current],
                  f.screen[0] if f.screen else "-", f.index, f.cops_on))
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
        exe = hostbuild.build(tmp, SOURCES, "gameflow_test")
        proc = subprocess.run([str(exe)] + [s["name"] for s in chosen],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr)
            sys.exit("gameflow_test failed")
        c_lines = proc.stdout.replace("\r\n", "\n").rstrip("\n").split("\n")

    py_lines = []
    for sc in chosen:
        py_lines.extend(run_scenario(sc))

    if args.dump:
        with open(args.dump + ".c.txt", "w") as fh:
            fh.write("\n".join(c_lines) + "\n")
        with open(args.dump + ".py.txt", "w") as fh:
            fh.write("\n".join(py_lines) + "\n")

    diff = list(difflib.unified_diff(c_lines, py_lines, "gameflow.c",
                                     "bootflow_check.py", lineterm=""))
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
