#!/usr/bin/env python3
r"""Cross-check the frontend animation layer against a second implementation.

`3DS Files/source/banim.c` is the port of the eight little classes that make
the frontend move -- `tCubic1D`, `AnimationGroup`, `tSlideAnimation` and its
two subclasses, `tExitScreenAnimation`, `tHighlightAnimation`,
`tAnimatedBlurb`, `feAnimAlphaElement` and `SelectionSet`. This file is those
eight written again, in Python, from `docs/formats/frontend-animation.md` and
the disassembly it cites rather than from the C. Both run the same scenarios
and print the same transcript; the diff is the test.

Two things make this worth doing rather than just eyeballing the C:

  * The maths is a cubic Hermite evaluated in single precision, and the
    interesting part is where it lands after a `cvt.w.s`. A model that
    computes in doubles agrees to six decimals and disagrees on the pixel, so
    everything below goes through `f32` after every operation -- the same
    discipline `bootflow_check.py` uses on the frame accumulator, for the
    same reason.

  * `bSin` is a five-term Taylor series over an argument first quantised to
    1/65536 of a turn. It returns 1.00000358 at the peak. Writing that twice
    is the only way to be sure the overshoot is the PS2's and not a typo.

What this does NOT check is layout -- whether `MI_3_MASK` really is the box
around the third label is a question about `FRONTB.BUN`, and
`tools/flailer_dump.py` answers it -- nor `FlailerTextChunk::ScaleAboutCenter`
(0x0013eb20), which is a hook here because it needs the font metrics; its
geometry is written up in the doc and belongs to the render layer.

Usage:
    python tools/banim_check.py
    python tools/banim_check.py --scenario blurb_interrupt
    python tools/banim_check.py --dump out.txt
"""
import argparse
import difflib
import os
import struct
import sys
import subprocess
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                                    # noqa: E402

SOURCES = ["tools/src/banim_test.c",
           "3DS Files/source/banim.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c"]

NL = chr(10)


def f32(x):
    """Round to single precision, which is all the R5900's FPU has."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


def i32(x):
    """Wrap to a signed 32-bit int, for the tick counter's subtractions."""
    x &= 0xffffffff
    return x - 0x100000000 if x >= 0x80000000 else x


def trunc(x):
    """cvt.w.s: truncate toward zero, whatever the rounding mode says."""
    return int(x)


def g9(x):
    """%.9g, the harness's float format."""
    return "%.9g" % x


# ------------------------------------------------------------------ hashing

def bhash(s, h=0xffffffff):
    for c in s.encode("latin-1"):
        h = (h * 33 + c) & 0xffffffff
    return h


SIXTIETH = f32(1.0 / 60.0)
TICK_SECONDS = f32(0.00025)
OFFSCREEN_X = f32(650.0)
STOPPED = 0x7fffffff

SLIDE_SLOTS = 10
MAX_GROUPS = 11

HL_TIME = f32(0.5)
HL_START_SCALE = f32(1.0)
HL_END_SCALE = f32(2.0)
HL_START_ALPHA = f32(128.0)
HL_END_ALPHA = f32(0.0)
HL_TIMEOUT = f32(4.0)
BLOOM_COLOR = 0x00000080

BLURB_MAX_TEXT = 256
WHITEOUT_TIME = f32(0.6)
IDLE_TIME = f32(0.5)
BLURB_SLIDE_TIME = f32(0.25)

SEL_MAX_ITEMS = 16

TYPE_ANY, TYPE_TEXT, TYPE_BITMAP = 0, 1, 2


# ------------------------------------------------------------------- output

OUT = []


def _out(line):
    OUT.append(line)


# Two sinks, because the transcript has two kinds of line in it and another
# checker wants only one of them. `emit` is what tools/src/banim_test.c's
# hook implementations print -- the Flailer traffic. `trace` is what the
# module itself puts through BAnimHooks::trace, which in the real game goes
# to the same console every other subsystem writes to. tools/bscreens_check.py
# imports this file for the animation kit, drops the hook lines and routes
# the traces into the game flow's transcript, which is exactly what
# bscreens.c's animTrace does on the C side.
EMIT = [_out]
TRACE = [_out]


def emit(line):
    if EMIT[0]:
        EMIT[0](line)


def trace(line):
    if TRACE[0]:
        TRACE[0](line)


# --------------------------------------------------------------- the world
#
# The same made-up screen tools/src/banim_test.c builds, written out the same
# way so the two are easy to compare by eye when they disagree.

W_MENU = 0xaaaa0001
W_EMPTY = 0xaaaa0002

H_SCROLLING_TEXT = 0x75980cf0
H_WHITEOUT_BAR = 0x70a404ec
H_BLOOM_TEXT = 0xab671c9a
H_MI_UNDERSCORE = 0x32c91dae
H_UNDERSCORE_GRP = 0x97bf4b25


def H_MENUITEM(n):
    return (0x52e039f2 + n) & 0xffffffff


def H_GROUP(i):
    return bhash("MENUITEM_%d_GROUP" % i)


def H_MASK(i):
    return bhash("MI_%d_MASK" % i)


class Obj(object):
    def __init__(self, screen, name, group, otype, x, y, sx, sy, alpha,
                 lang=0, text=""):
        self.screen = screen
        self.name = name
        self.group = group
        self.type = otype
        self.x = f32(x)
        self.y = f32(y)
        self.scaleX = f32(sx)
        self.scaleY = f32(sy)
        self.alpha = list(alpha)
        self.visible = 1
        self.languageID = lang
        self.color = 0
        self.text = text

    def copy(self):
        o = Obj(self.screen, self.name, self.group, self.type, self.x,
                self.y, self.scaleX, self.scaleY, self.alpha)
        o.visible = self.visible
        o.languageID = self.languageID
        o.color = self.color
        o.text = self.text
        return o


def build_world():
    w = []
    for i in range(1, 6):
        w.append(Obj(W_MENU, H_MASK(i), H_GROUP(i), TYPE_BITMAP,
                     100.0, 50.0 + (i - 1) * 20.0, 1.0, 1.0,
                     [128, 128, 128, 128]))
    labels = [(1, 1.5, 3, "Quick Race"), (2, 1.5, 4, "Championship"),
              (3, 0.5, 5, "Hot Pursuit"), (4, 1.5, 6, "Options"),
              (5, 1.5, 7, "Quit")]
    for i, scale, lang, text in labels:
        w.append(Obj(W_MENU, H_MENUITEM(i), H_GROUP(i), TYPE_TEXT,
                     120.0, 50.0 + (i - 1) * 20.0, scale, scale,
                     [128, 0, 0, 0], lang, text))
    w.append(Obj(W_MENU, H_SCROLLING_TEXT, 0, TYPE_TEXT, 40.0, 200.0,
                 1.0, 1.0, [100, 0, 0, 0], 9, ""))
    w.append(Obj(W_MENU, H_WHITEOUT_BAR, 0, TYPE_BITMAP, 40.0, 198.0,
                 1.0, 1.0, [128, 96, 64, 32]))
    w.append(Obj(W_MENU, H_BLOOM_TEXT, 0, TYPE_TEXT, 0.0, 0.0, 1.0, 1.0,
                 [128, 0, 0, 0]))
    w.append(Obj(W_MENU, H_MI_UNDERSCORE, H_UNDERSCORE_GRP, TYPE_BITMAP,
                 95.0, 150.0, 1.0, 1.0, [128, 128, 128, 128]))
    return w


class World(object):
    def __init__(self, objs=None):
        self.objs = build_world() if objs is None else objs

    def find(self, screen, name, otype=TYPE_ANY):
        for o in self.objs:
            if o.screen != screen or o.name != name:
                continue
            if otype != TYPE_ANY and o.type != otype:
                continue
            return o
        return None

    # -- the hooks, printing exactly what the C harness prints ------------

    def object_exists(self, screen, name, otype):
        return 1 if self.find(screen, name, otype) else 0

    def group_exists(self, screen, group, otype):
        if not group:
            return 0
        for o in self.objs:
            if o.screen != screen or o.group != group:
                continue
            if otype != TYPE_ANY and o.type != otype:
                continue
            return 1
        return 0

    def object_type(self, screen, name):
        o = self.find(screen, name)
        return o.type if o else TYPE_ANY

    def get_top_left(self, screen, name):
        o = self.find(screen, name)
        return (o.x, o.y) if o else (f32(0.0), f32(0.0))

    def set_top_left(self, screen, name, x, y):
        emit("hook settopleft %08x %d %d" % (name, trunc(x), trunc(y)))
        o = self.find(screen, name)
        if not o:
            return
        o.x = f32(x)
        o.y = f32(y)

    def set_group_pos(self, screen, group, master, x, y):
        emit("hook setgrouppos %08x %08x %d %d"
             % (group, master, trunc(x), trunc(y)))
        m = self.find(screen, master)
        if not m:
            return
        dx = f32(f32(x) - m.x)
        dy = f32(f32(y) - m.y)
        for o in self.objs:
            if o.screen != screen or o.group != group:
                continue
            o.x = f32(o.x + dx)
            o.y = f32(o.y + dy)
        if m.group != group:
            m.x = f32(x)
            m.y = f32(y)

    def set_visible(self, screen, name, v):
        emit("hook visible %08x %d" % (name, v))
        o = self.find(screen, name)
        if o:
            o.visible = v

    def get_alpha(self, screen, name, corner):
        o = self.find(screen, name)
        return o.alpha[corner] if o else 0

    def set_alpha(self, screen, name, corner, a):
        emit("hook alpha %08x %d %d" % (name, corner, a))
        o = self.find(screen, name)
        if o:
            o.alpha[corner] = a

    def set_language_id(self, screen, name, lid):
        emit("hook langid %08x %d" % (name, lid))
        o = self.find(screen, name)
        if o:
            o.languageID = lid

    def print_text(self, screen, name, s):
        emit('hook print %08x "%s"' % (name, s))
        o = self.find(screen, name, TYPE_TEXT)
        if o:
            o.text = s[:63]

    def copy_text(self, screen, dst, src):
        d = self.find(screen, dst, TYPE_TEXT)
        q = self.find(screen, src, TYPE_TEXT)
        emit('hook copytext %08x <- %08x "%s"'
             % (dst, src, q.text if q else ""))
        if d and q:
            d.text = q.text

    def scale_about_center(self, screen, name, scale):
        emit("hook scale %08x %s" % (name, g9(scale)))
        o = self.find(screen, name, TYPE_TEXT)
        if not o:
            return
        o.scaleX = scale
        o.scaleY = scale

    def set_color(self, screen, name, c):
        emit("hook color %08x %08x" % (name, c))
        o = self.find(screen, name)
        if o:
            o.color = c

    def get_scale(self, screen, name):
        o = self.find(screen, name)
        return (o.scaleX, o.scaleY) if o else (None, None)

    def translate(self, lid):
        return None if lid < 0 else "<string %d>" % lid

    def change_to_screen(self, name, push):
        emit("hook changetoscreen %s %d" % (name, push))


# ------------------------------------------------------------------- clock

class Anim(object):
    def __init__(self, world):
        self.w = world
        self.timer = 0
        self.elapsed = f32(0.0)

    def tick(self, dt):
        self.timer = i32(self.timer + trunc(f32(f32(dt) * f32(4000.0))))
        self.elapsed = f32(dt)

    def set_clock(self, timer, elapsed):
        self.timer = timer
        self.elapsed = f32(elapsed)

    def since(self, then):
        return f32(f32(i32(self.timer - then)) * TICK_SECONDS)


# ---------------------------------------------------------------- tCubic1D

class Spline(object):
    def __init__(self):
        self.val = f32(0.0)
        self.dval = f32(0.0)
        self.val_desired = f32(0.0)
        self.dval_desired = f32(0.0)
        self.coeff = [f32(0.0)] * 4
        self.time = f32(0.0)
        self.duration = f32(1.0)
        self.threshold = f32(1.0)
        self.state = 0
        self.flags = 0

    def make_coeffs(self):
        d = f32(self.val_desired - self.val)
        v = self.dval
        self.coeff[3] = self.val
        self.coeff[2] = v
        self.coeff[0] = f32(f32(v + self.dval_desired) - f32(d + d))
        self.coeff[1] = f32(f32(f32(d * f32(3.0)) - self.dval_desired)
                            - f32(v + v))

    def get_val(self, t):
        c = self.coeff
        return f32(f32(f32(f32(f32(f32(c[0] * t) + c[1]) * t) + c[2]) * t)
                   + c[3])

    def get_dval(self, t):
        c = self.coeff
        return f32(f32(f32(f32(f32(c[0] * t) * f32(3.0)) + f32(c[1] + c[1]))
                       * t) + c[2])

    def seek(self, dt):
        if self.state != 1:
            if self.state < 2 or self.state != 2:
                return
            self.time = f32(0.0)
            if self.flags == 0:
                self.state = 1
            self.make_coeffs()
        t = f32(self.time + f32(f32(dt) / self.duration))
        self.time = t
        if self.threshold <= t:
            if f32(1.0) <= self.threshold:
                self.val = self.val_desired
                self.dval = self.dval_desired
            self.state = 0
        else:
            self.val = self.get_val(t)
            self.dval = self.get_dval(t)


# ----------------------------------------------------------- AnimationGroup

class Group(object):
    def __init__(self, a, screen, group, master, start, end, duration):
        self.a = a
        self.screen = screen
        self.group = group
        self.master = master
        self.s = Spline()
        self.s.threshold = f32(1.0)
        self.s.flags = 1
        self.s.duration = f32(1.0)
        # SavedXPos/SavedYPos are ints: the constructor reads them through
        # FlailerGetTopLeftPosition's int overload (0x00141d28).
        self.saved_x, self.saved_y = a.w.get_top_left(screen, master)
        self.saved_x = f32(trunc(self.saved_x))
        self.saved_y = f32(trunc(self.saved_y))
        self.s.duration = f32(duration)
        self.setup(start, end)

    def place(self, x, y):
        if self.group == 0:
            self.a.w.set_top_left(self.screen, self.master,
                                  f32(trunc(x)), y)
        else:
            self.a.w.set_group_pos(self.screen, self.group, self.master,
                                   f32(trunc(x)), y)

    def setup(self, start, end):
        s = self.s
        start = f32(start)
        end = f32(end)
        s.val_desired = start
        s.flags = 0
        if start != s.val:
            s.state = 2
        s.state = 0
        s.val = s.val_desired
        s.val_desired = end
        s.dval = s.dval_desired
        if end != s.val:
            s.state = 2
        self.place(s.val, self.saved_y)
        trace("group %08x/%08x setup %d -> %d in %.3f"
             % (self.group, self.master, trunc(start), trunc(end),
                s.duration))

    def finished(self):
        return 1 if self.s.state == 0 else 0

    def animate(self):
        self.s.seek(self.a.elapsed)
        self.place(self.s.val, self.saved_y)

    def desired_x(self):
        return self.s.val_desired

    def release(self):
        self.place(self.saved_x, self.saved_y)


# ---------------------------------------------------------- tSlideAnimation

def slide_duration(i):
    return f32(f32(0.05) + f32(f32(i) * f32(0.05)))


class Slide(object):
    def __init__(self, a, screen):
        self.a = a
        self.screen = screen
        self.groups = []
        self.time_started = 0
        self.total_time = f32(0.0)

    def add_group(self, group, master, start, end, duration):
        duration = f32(duration)
        if self.total_time < duration:
            self.total_time = duration
        if len(self.groups) >= MAX_GROUPS:
            trace("slide overflow %08x" % group)
            return
        self.groups.append(Group(self.a, self.screen, group, master,
                                 start, end, duration))

    def start(self):
        self.time_started = self.a.timer

    def has_control(self):
        return (1 if self.time_started != 0
                and self.time_started != STOPPED else 0)

    def finished(self):
        if not self.has_control():
            return 0
        for g in self.groups:
            if not g.finished():
                return 0
        return 1

    def fraction(self):
        if not self.has_control():
            return f32(0.0)
        if self.finished():
            return f32(1.0)
        return f32(self.a.since(self.time_started) / self.total_time)

    def animate(self):
        if self.finished():
            return
        for g in self.groups:
            g.animate()

    def release(self):
        for g in self.groups:
            g.release()
        self.groups = []


def slide_in(a, screen, target_x):
    s = Slide(a, screen)
    for i in range(SLIDE_SLOTS):
        group = H_GROUP(i)
        master = H_MASK(i)
        if not a.w.group_exists(screen, group, TYPE_ANY):
            continue
        s.add_group(group, master,
                    f32(f32(640.0) + f32(f32(i) * f32(10.0))),
                    f32(target_x), slide_duration(i))
    s.time_started = a.timer
    trace("slidein %d groups -> %d" % (len(s.groups), trunc(f32(target_x))))
    return s


def slide_out(a, screen):
    s = Slide(a, screen)
    for i in range(SLIDE_SLOTS):
        group = H_GROUP(i)
        master = H_MASK(i)
        if not a.w.group_exists(screen, group, TYPE_ANY):
            continue
        x, _y = a.w.get_top_left(screen, master)
        s.add_group(group, master, x, OFFSCREEN_X, slide_duration(i))
    s.time_started = 0
    trace("slideout %d groups" % len(s.groups))
    return s


# ------------------------------------------------------ tExitScreenAnimation

class Exit(object):
    def __init__(self, a, screen, target):
        self.a = a
        self.slide = slide_out(a, screen)
        self.target = target
        self.slide.start()
        trace("exit start %s %.3fs" % (target, self.slide.total_time))

    def message(self, msg):
        """Returns (handled, param, noise) with None where nothing wrote."""
        noise = 0
        if msg == 17:
            return 0, 0, noise
        if 0 <= msg - 8 < 2:
            return 0, 1, noise
        if msg != 18:
            return 0, None, noise
        self.slide.animate()
        if not self.slide.finished():
            return 0, None, noise
        trace("exit finish %s" % self.target)
        self.a.w.change_to_screen(self.target, 1)
        return 1, None, noise


# -------------------------------------------------------------------- bSin

# This file used to carry its own five-term series. bmath_check.py now has
# the same one, written from the same listing at 0x00241df8 and mutation-
# tested against 3DS Files/source/bmath.c, so there is no reason to keep two
# Python copies that can drift apart.
from bmath_check import bSinF as bsin                             # noqa: E402


# ---------------------------------------------------- tHighlightAnimation

class Highlight(object):
    def __init__(self, a, screen, text_object, target_color):
        self.a = a
        self.screen = screen
        self.timer = a.timer
        self.text_object = text_object
        self.target_color = target_color
        self.current_item = 0
        self.start_scale = HL_START_SCALE
        self.end_scale = HL_END_SCALE
        self.timeout = HL_TIMEOUT

    def set_item(self, item):
        self.current_item = item
        self.timer = self.a.timer
        sx, _sy = self.a.w.get_scale(self.screen, item)
        if sx is None:
            sx = f32(1.0)
        self.start_scale = f32(sx * HL_START_SCALE)
        sx, _sy = self.a.w.get_scale(self.screen, item)
        if sx is None:
            sx = f32(1.0)
        self.end_scale = f32(sx * HL_END_SCALE)
        trace("bloom item %08x scale %.3f..%.3f"
             % (item, self.start_scale, self.end_scale))

    def force_start(self):
        self.timer = self.a.timer

    def animate(self):
        t = self.a.since(self.timer)
        if t < HL_TIME:
            u = f32(f32(t * f32(1.57075)) / HL_TIME)
            s = bsin(u)
            alpha = f32(HL_START_ALPHA
                        + f32(f32(HL_END_ALPHA - HL_START_ALPHA) * bsin(u)))
            src = self.a.w.object_exists(self.screen, self.current_item,
                                         TYPE_TEXT)
            dst = self.a.w.object_exists(self.screen, self.text_object,
                                         TYPE_TEXT)
            if not src:
                if dst:
                    self.a.w.set_visible(self.screen, self.text_object, 0)
            elif dst:
                self.a.w.copy_text(self.screen, self.text_object,
                                   self.current_item)
                self.a.w.scale_about_center(
                    self.screen, self.text_object,
                    f32(self.start_scale
                        + f32(f32(self.end_scale - self.start_scale) * s)))
                self.a.w.set_alpha(self.screen, self.text_object, 0,
                                   trunc(alpha))
                if self.target_color != -1:
                    self.a.w.set_color(self.screen, self.text_object,
                                       self.target_color)
        if self.timeout < t:
            self.timer = self.a.timer


# ----------------------------------------------------- feAnimAlphaElement

class AlphaElement(object):
    def __init__(self, a, screen, obj):
        self.a = a
        self.screen = screen
        self.object = obj
        self.exists = a.w.object_exists(screen, obj, TYPE_ANY)
        self.is_bitmap = 0
        self.saved = [f32(0.0)] * 4
        if not self.exists:
            return
        self.is_bitmap = (1 if a.w.object_type(screen, obj) == TYPE_BITMAP
                          else 0)
        for i in range(4):
            v = a.w.get_alpha(screen, obj, i if self.is_bitmap else 0)
            self.saved[i] = f32(v)

    def set_scale(self, scale):
        if not self.exists:
            return
        scale = f32(scale)
        if not self.is_bitmap:
            self.a.w.set_alpha(self.screen, self.object, 0,
                               trunc(f32(self.saved[0] * scale)))
            return
        for i in range(4):
            self.a.w.set_alpha(self.screen, self.object, i,
                               trunc(f32(self.saved[i] * scale)))

    def release(self):
        self.set_scale(f32(1.0))


# ---------------------------------------------------------- tAnimatedBlurb

BLURB_SLIDING_IN, BLURB_WHITEOUT, BLURB_NEW_TEXT, BLURB_SETTLED = 0, 1, 2, 3


class Blurb(object):
    def __init__(self, a, screen, slide_text, fadeout, whiteout):
        self.a = a
        self.new_text_timer = 0
        x, _y = a.w.get_top_left(screen, slide_text)
        self.slide_in_text = Group(a, screen, 0, slide_text, OFFSCREEN_X, x,
                                   BLURB_SLIDE_TIME)
        self.fadeout_text = AlphaElement(a, screen, fadeout)
        self.whiteout_bar = AlphaElement(a, screen, whiteout)
        self.screen = screen
        self.slide_text = slide_text
        self.desired_x = self.slide_in_text.desired_x()
        self.idle_timer = 0
        self.animation_started = 0
        self.state = BLURB_SLIDING_IN
        self.latest = ""

    def new_text(self, s):
        if 0 <= self.state - BLURB_NEW_TEXT < 2:
            self.state = BLURB_WHITEOUT
            self.new_text_timer = self.a.timer
            self.animation_started = 0
        self.idle_timer = self.a.timer
        self.latest = ("" if s is None else s)[:BLURB_MAX_TEXT - 1]
        trace('blurb text "%s" state %d' % (self.latest, self.state))

    def new_text_id(self, lid):
        self.new_text(self.a.w.translate(lid))

    def animate(self):
        state = self.state
        whiteout = self.a.since(self.new_text_timer)
        idle = self.a.since(self.idle_timer)
        if state == BLURB_WHITEOUT:
            f = f32(1.0)
            if whiteout < WHITEOUT_TIME:
                f = f32(whiteout / WHITEOUT_TIME)
            self.fadeout_text.set_scale(f32(f32(1.0) - f))
            self.whiteout_bar.set_scale(f)
            if idle > IDLE_TIME:
                self.animation_started = 0
                self.state = BLURB_NEW_TEXT
                state = BLURB_NEW_TEXT
        if state in (BLURB_NEW_TEXT, BLURB_SLIDING_IN):
            self.fadeout_text.set_scale(f32(1.0))
            self.whiteout_bar.set_scale(f32(0.0))
            if not self.animation_started:
                self.a.w.set_language_id(self.screen, self.slide_text, 0)
                self.a.w.print_text(self.screen, self.slide_text,
                                    self.latest)
                self.slide_in_text.setup(OFFSCREEN_X, self.desired_x)
                self.animation_started = 1
            elif not self.slide_in_text.finished():
                self.slide_in_text.animate()
            else:
                self.state = BLURB_SETTLED

    def release(self):
        self.whiteout_bar.release()
        self.fadeout_text.release()
        self.slide_in_text.release()


# ------------------------------------------------------------- SelectionSet

class SelSet(object):
    def __init__(self, a, screen):
        self.a = a
        self.screen = screen
        self.items = [0] * SEL_MAX_ITEMS
        self.num_items = 0
        self.current = 0
        self.mode = 1
        self.indicator_mode = 0

    def _visible(self, obj, v):
        if not obj:
            return
        self.a.w.set_visible(self.screen, obj, v)

    def add_items(self, hashes):
        for h in hashes:
            found = h if self.a.w.object_exists(self.screen, h,
                                                TYPE_ANY) else 0
            if found:
                self._visible(found, 0 if self.indicator_mode == 0 else 1)
            if self.num_items < SEL_MAX_ITEMS:
                self.items[self.num_items] = found
            self.num_items += 1

    def set_current(self, obj):
        if self.mode != 1:
            return
        if self.current:
            self._visible(self.current,
                          0 if self.indicator_mode == 0 else 1)
        self.current = 0
        nxt = 0
        n = min(self.num_items, SEL_MAX_ITEMS)
        for i in range(n):
            if self.items[i] and self.items[i] == obj:
                nxt = self.items[i]
                break
        self.current = nxt
        if self.current:
            self._visible(self.current,
                          0 if self.indicator_mode != 0 else 1)
            trace("indicator %08x" % self.current)

    def update(self):
        pass


# ------------------------------------------------------------- reporting

def dump_masks(w):
    for i in range(1, 6):
        p = w.find(W_MENU, H_MASK(i))
        lab = w.find(W_MENU, H_MENUITEM(i))
        emit("  mask %d at %d,%d vis %d  label at %d,%d"
             % (i, trunc(p.x), trunc(p.y), p.visible, trunc(lab.x),
                trunc(lab.y)))


def dump_object(w, name, label):
    p = w.find(W_MENU, name)
    if not p:
        emit("  %s absent" % label)
        return
    emit('  %s at %d,%d vis %d alpha %d,%d,%d,%d scale %s lang %d '
         'color %08x "%s"'
         % (label, trunc(p.x), trunc(p.y), p.visible, p.alpha[0],
            p.alpha[1], p.alpha[2], p.alpha[3], g9(p.scaleX),
            p.languageID, p.color, p.text))


# ------------------------------------------------------------- scenarios

def sc_spline(threshold, flags, duration):
    s = Spline()
    s.val_desired = f32(100.0)
    s.duration = f32(duration)
    s.threshold = f32(threshold)
    s.flags = flags
    s.state = 2
    for i in range(14):
        s.seek(SIXTIETH)
        emit("step %2d state %d t %s val %s dval %s c %s %s %s %s"
             % (i, s.state, g9(s.time), g9(s.val), g9(s.dval),
                g9(s.coeff[0]), g9(s.coeff[1]), g9(s.coeff[2]),
                g9(s.coeff[3])))


def sc_bsin():
    angles = [0.0, 0.1, 0.5, 0.78539816, 1.0, 1.5707963, 1.5708, 2.0,
              3.1415927, 3.5, 4.712389, 4.712389, 5.5, 6.2831853, 7.0,
              -0.5, -1.5707963, 0.0099, 1.57075, 0.785375]
    for ang in angles:
        a = f32(ang)
        emit("bsin %s = %s" % (g9(a), g9(bsin(a))))


def sc_slide_in(a, screen, target_x, frames):
    s = slide_in(a, screen, f32(target_x))
    emit("total %s groups %d control %d"
         % (g9(s.total_time), len(s.groups), s.has_control()))
    for f in range(frames):
        a.tick(SIXTIETH)
        s.animate()
        emit("frame %d timer %d fin %d frac %s"
             % (f, a.timer, s.finished(), g9(s.fraction())))
    dump_masks(a.w)
    s.release()
    emit("released")
    dump_masks(a.w)


def sc_slide_out(a, start_it, frames):
    s = slide_out(a, W_MENU)
    emit("total %s groups %d control %d fin %d"
         % (g9(s.total_time), len(s.groups), s.has_control(), s.finished()))
    if start_it:
        s.start()
    for f in range(frames):
        a.tick(SIXTIETH)
        s.animate()
        emit("frame %d fin %d frac %s" % (f, s.finished(), g9(s.fraction())))
    dump_masks(a.w)


def sc_exit(a, with_underscore):
    e = Exit(a, W_MENU, "Cops On Mode Select")
    if with_underscore:
        x, _y = a.w.get_top_left(W_MENU, H_MI_UNDERSCORE)
        e.slide.add_group(H_UNDERSCORE_GRP, H_MI_UNDERSCORE, x,
                          OFFSCREEN_X, e.slide.total_time)
    emit("total %s groups %d" % (g9(e.slide.total_time), len(e.slide.groups)))
    for msg, label in ((17, "back"), (8, "up  "), (1, "sel ")):
        r, param, noise = e.message(msg)
        emit("%s -> %d param %d noise %d"
             % (label, r, -1 if param is None else param,
                -1 if noise is None else noise))
    done = 0
    f = 0
    while f < 40 and not done:
        a.tick(SIXTIETH)
        done, param, noise = e.message(18)
        emit("frame %d tick -> %d param %d noise %d"
             % (f, done, -1 if param is None else param,
                -1 if noise is None else noise))
        f += 1
    dump_masks(a.w)
    dump_object(a.w, H_MI_UNDERSCORE, "underscore")


def sc_highlight(a, item, frames):
    h = Highlight(a, W_MENU, H_BLOOM_TEXT, BLOOM_COLOR)
    h.set_item(item)
    for _f in range(frames):
        a.tick(SIXTIETH)
        h.animate()
    emit("timer %d start %s end %s"
         % (h.timer, g9(h.start_scale), g9(h.end_scale)))
    dump_object(a.w, H_BLOOM_TEXT, "bloom")


def sc_alpha(a, obj, label):
    e = AlphaElement(a, W_MENU, obj)
    emit("exists %d bitmap %d saved %s %s %s %s"
         % (e.exists, e.is_bitmap, g9(e.saved[0]), g9(e.saved[1]),
            g9(e.saved[2]), g9(e.saved[3])))
    for s in (1.0, 0.5, 0.25, 0.0, 1.0, 2.0):
        e.set_scale(f32(s))
    e.release()
    dump_object(a.w, obj, label)


def sc_blurb(a, interrupt):
    b = Blurb(a, W_MENU, H_SCROLLING_TEXT, H_SCROLLING_TEXT, H_WHITEOUT_BAR)
    emit("desired %s state %d" % (g9(b.desired_x), b.state))
    b.new_text("Race against three rivals.")
    for f in range(70):
        a.tick(SIXTIETH)
        if interrupt and f == 20:
            b.new_text("Outrun the cops.")
        if interrupt and f == 45:
            b.new_text_id(1234)
        b.animate()
        emit("frame %d state %d started %d"
             % (f, b.state, b.animation_started))
    dump_object(a.w, H_SCROLLING_TEXT, "blurb")
    dump_object(a.w, H_WHITEOUT_BAR, "bar")
    b.release()
    emit("released")
    dump_object(a.w, H_SCROLLING_TEXT, "blurb")
    dump_object(a.w, H_WHITEOUT_BAR, "bar")


def sc_selset(a, indicator_mode):
    s = SelSet(a, W_MENU)
    s.indicator_mode = indicator_mode
    s.add_items([H_MASK(i) for i in range(1, 7)])
    emit("items %d" % s.num_items)
    for i in range(6):
        emit("  slot %d %08x" % (i, s.items[i]))
    for target in (H_MASK(3), H_MASK(1), H_MASK(6), 0xdeadbeef):
        s.set_current(target)
        emit("current %08x" % s.current)
    s.mode = 0
    s.set_current(H_MASK(2))
    emit("current %08x" % s.current)
    s.update()
    dump_masks(a.w)


SCENARIOS = [
    ("spline_normal",   lambda a: sc_spline(1.0, 0, 0.1)),
    ("spline_early",    lambda a: sc_spline(0.5, 0, 0.1)),
    ("spline_late",     lambda a: sc_spline(1.5, 0, 0.1)),
    ("spline_stuck",    lambda a: sc_spline(1.0, 1, 0.1)),
    ("bsin",            lambda a: sc_bsin()),
    ("slidein",         lambda a: sc_slide_in(a, W_MENU, 100.0, 36)),
    ("slidein_far",     lambda a: sc_slide_in(a, W_MENU, -40.0, 36)),
    ("slidein_empty",   lambda a: sc_slide_in(a, W_EMPTY, 100.0, 4)),
    ("slideout",        lambda a: sc_slide_out(a, 1, 36)),
    ("slideout_idle",   lambda a: sc_slide_out(a, 0, 36)),
    ("exit",            lambda a: sc_exit(a, 0)),
    ("exit_underscore", lambda a: sc_exit(a, 1)),
    ("highlight",       lambda a: sc_highlight(a, H_MENUITEM(1), 40)),
    ("highlight_small", lambda a: sc_highlight(a, H_MENUITEM(3), 40)),
    ("highlight_loop",  lambda a: sc_highlight(a, H_MENUITEM(2), 250)),
    ("highlight_gone",  lambda a: sc_highlight(a, 0xdeadbeef, 8)),
    ("alpha_text",      lambda a: sc_alpha(a, H_SCROLLING_TEXT, "blurb")),
    ("alpha_bitmap",    lambda a: sc_alpha(a, H_WHITEOUT_BAR, "bar")),
    ("alpha_gone",      lambda a: sc_alpha(a, 0xdeadbeef, "gone")),
    ("blurb",           lambda a: sc_blurb(a, 0)),
    ("blurb_interrupt", lambda a: sc_blurb(a, 1)),
    ("selset_mode0",    lambda a: sc_selset(a, 0)),
    ("selset_mode1",    lambda a: sc_selset(a, 1)),
]


def model(names):
    del OUT[:]
    for name, run in SCENARIOS:
        if names and name not in names:
            continue
        emit("scenario %s" % name)
        a = Anim(World())
        a.set_clock(1000000, f32(0.0))
        run(a)
    return NL.join(OUT) + NL


# ------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scenario", action="append",
                    help="run only this scenario (repeatable)")
    ap.add_argument("--dump", help="write both transcripts next to this path")
    args = ap.parse_args()

    names = args.scenario or []
    for n in names:
        if n not in [s[0] for s in SCENARIOS]:
            sys.exit("unknown scenario: %s" % n)

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="banim_test")
        r = subprocess.run([str(exe)] + names, capture_output=True,
                           text=True)
        if r.returncode != 0:
            sys.exit("harness failed (%d):%s%s" % (r.returncode, NL,
                                                   r.stderr))
        port = r.stdout.replace(chr(13) + NL, NL)

    ours = model(names)

    if args.dump:
        with open(args.dump + ".port.txt", "w", newline=NL) as fh:
            fh.write(port)
        with open(args.dump + ".model.txt", "w", newline=NL) as fh:
            fh.write(ours)

    a = port.splitlines()
    b = ours.splitlines()
    diff = [ln for ln in difflib.unified_diff(a, b, "port", "model",
                                              lineterm="", n=1)]
    n = len([ln for ln in diff
             if ln[:1] in "+-" and not ln.startswith(("+++", "---"))])
    count = len(names) if names else len(SCENARIOS)
    print("%d scenarios, %d lines, %d differ" % (count, len(a), n))
    if diff:
        print(NL.join(diff[:120]))
        if len(diff) > 120:
            print("... %d more diff lines" % (len(diff) - 120))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
