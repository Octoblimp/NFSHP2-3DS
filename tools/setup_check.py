#!/usr/bin/env python3
"""Cross-check 3DS Files/source/bsetup.c, You're The Cop, against the retail
image, SLES_507.31.

**The model** is retail's own BeACopChallengeSetup -- Callback
(0x001b6f18), the constructor and destructor, HandleEvent, OnTick,
OnHighlight, OnScroll, ResyncChangeables, the blurb's pick (0x001b70d8)
and the helpers round them (MaybeChangeNumPlayers, ValueChanger,
MaybeChangeOpponentSkillLevel, RefreshOpponentSkillLevel,
MakeJoystickArrowsRight, StartTheRightMovie, FlailerSetTopLeftY(int, int,
float)) -- and the arrows class (0x0024a690..0x0024a880) with its
tfeSineWave and the real bSin, all run in retail_model.RetailEmu on
retail's Fred (0x002fc050) and TheRaceParameters (0x0031a898). The
harness (tools/src/setup_test.c) runs bsetup.c's.

**The stubs** print what they are asked, on both sides.

- The animation kit, at its retail addresses: SelectionSet's constructor,
  AddItems and SetCurrentItem; tAnimatedBlurb's constructor, NewText(int),
  Animate and destructor; tSlideInAnimation's constructor and destructor,
  tSlideAnimation's Animate and AddGroup; tHighlightAnimation's
  constructor, SetCurrentMenuItem and Animate; tExitScreenAnimation's
  constructor (which writes 0.75 into TotalTime), destructor and
  HandleMessages. The harness does not link banim.c: its banim_* print the
  same lines. The destructors that only free (SelectionSet's,
  tHighlightAnimation's) print nothing on either side.
- The Flailer calls: FindFlailerObject (a bitmap's chunk is a pointer the
  model hands out and maps back), the three chunk calls on it, and
  FlailerGetCenterY, GetBoundingBox, SetTopLeftY(int), GetTopLeftX,
  SetLanguageID, SetVisibility and GrayMenuItem.
- IsJoystickPluggedIn, StartMovie, SetHelpOverride (its table printed),
  and the three FrontendDatabase calls.

**The script** activates the screen from several Freds (one player, two,
three, a skill of 3, cops on and off), with the second pad in and out and
the first out too; ticks it at odd elapsed times so the pulse wraps, and
at one past a whole turn; highlights each item and one more; scrolls every
item both ways through both wraps; selects on each item from both ports
with one player and two, and one item outside the three; sends every other
message with and without an exit running; and unactivates it with and
without one; and BACKs out after changes with no SELECT, over a Fred
whose game type and count something else moved. Then a tfeSineWave on its
own, with bounds the arrows never use.

    python tools/setup_check.py
    python tools/setup_check.py --mutate [--only a,b]
    python tools/setup_check.py --dump out/setup
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                        # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/setup_test.c"
BSETUP = "3DS Files/source/bsetup.c"
SOURCES = [HARNESS, BSETUP, "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c"]
HARNESS_TIMEOUT = 30

GP = retail_model.RETAIL_GP
ELAPSED = GP - 19596            # RealTimeElapsed
PINSTANCE = GP - 18784          # BeACopChallengeSetup's pInstance
FRED = 0x002fc050
RP = 0x0031a898

F_CALLBACK = 0x001b6f18

SCREEN = 0xe55f1297
MENUITEM = [0, 0x52e039f3, 0x52e039f4, 0x52e039f5]
PLAYERS_VALUE = 0x164eb99a
SKILL_VALUE = 0x53a607f5
LEFT_ARROW = 0xd1cda594
RIGHT_ARROW = 0x9345e4a7
MI_MASK = [0, 0x6e34e350, 0x708a0bf1, 0x72df3492]
MI_UNDERSCORE = 0x32c91dae
MI_OVERSCORE = 0xc671680c
OTHER = 0x52e039f6              # MENUITEM_4, not on this screen's switch

# The kit.
K_SEL_CTOR, K_SEL_ADD, K_SEL_CUR, K_SEL_DTOR = (0x0016e120, 0x0016e1f8,
                                                0x0016e270, 0x0016e168)
K_BLURB_CTOR, K_BLURB_DTOR, K_BLURB_ANIM, K_BLURB_TEXT = (
    0x002491b0, 0x00249280, 0x00249348, 0x002494e8)
K_SLIDEIN_CTOR, K_SLIDEIN_DTOR = 0x00248fd0, 0x001b9ae0
K_SLIDE_ANIM, K_SLIDE_GROUP = 0x00248d20, 0x00248c60
K_HL_CTOR, K_HL_DTOR, K_HL_ITEM, K_HL_ANIM = (0x00248870, 0x002488b0,
                                              0x002488d0, 0x00248970)
K_EXIT_CTOR, K_EXIT_DTOR, K_EXIT_MSG = 0x002490d8, 0x001b9ad0, 0x00249128
EXIT_TOTAL = 0.75

# bWare.
B_MALLOC, B_DELETE = 0x002577c0, 0x00114e98

# The Flailer.
S_FIND = 0x00143d50
S_ALPHA = 0x001411d8
S_CENTERY = 0x00140930
S_CHUNKVIS = 0x00140728
S_CY = 0x00144860
S_BBOX = 0x00144280
S_TOPY = 0x00144458
S_TOPX = 0x00144140
S_LANG = 0x001449a8
S_VIS = 0x00144968
S_GRAY = 0x0016d198

S_JOY = 0x001542f0
S_MOVIE = 0x0016ce30
S_HELP = 0x0016d448
S_CARS, S_PRELOAD, S_RPSETUP = 0x00183af8, 0x00183ec0, 0x001862b0

# tfeSineWave, run for itself too: the arrows' is always 0 to 128.
T_WAVE_CTOR, T_WAVE_STEP, T_WAVE_VAL, T_WAVE_INT = (0x0024a5c0, 0x0024a5d8,
                                                    0x0024a610, 0x0024a668)


def fbits(v):
    return struct.unpack("<I", struct.pack("<f", v))[0]


def bitsf(u):
    return struct.unpack("<f", struct.pack("<I", u & M32))[0]


# ================================================================== script

def obj(h, kind, box=(0, 0, 0, 0), cy=0, x=0.0):
    return "obj|%#x|%d|%d|%d|%d|%d|%d|%#x" % ((h, kind) + tuple(box)
                                             + (cy, fbits(x)))


def msg(m, item=0, port=0):
    return "msg|%d|%#x|%d" % (m, item, port)


TICK = msg(18)


def screen_objects():
    return [
        obj(MENUITEM[1], 1, (40, 84, 300, 106), 95, 40.0),
        obj(MENUITEM[2], 1, (40, 138, 300, 161), 149, 40.0),
        obj(MENUITEM[3], 1, (40, 192, 181, 215), 203, 40.0),
        obj(PLAYERS_VALUE, 1, (441, 84, 583, 106), 95, 441.0),
        obj(SKILL_VALUE, 1, (451, 138, 577, 161), 149, 451.0),
        obj(LEFT_ARROW, 2, (394, 86, 410, 102), 94, 394.0),
        obj(RIGHT_ARROW, 2, (610, 86, 626, 102), 94, 610.0),
        obj(MI_MASK[1], 2, (0, 80, 640, 110), 95, 21.5),
        obj(MI_UNDERSCORE, 2, (30, 100, 620, 104), 102, 30.25),
        obj(OTHER, 1, (-7, -3, 11, 1), -1, -2.0),
    ]


def script():
    s = []
    s += screen_objects()
    s += ["dcs|1|3|1|1|0", "police|1", "joy|0|1", "joy|1|0",
          "elapsed|%#x" % fbits(1.0 / 60)]
    # One pad: the constructor puts the count at 1, which it already is.
    s += [msg(11, SCREEN), "dump", TICK, TICK, "dump"]
    s += [msg(4, MENUITEM[1]), "dump", TICK, "dump"]
    # Right and left on Players with one pad: no change, silent.
    s += [msg(7, MENUITEM[1]), msg(6, MENUITEM[1]), "dump"]
    # The second pad: the arrows come back, and the count moves.
    s += ["joy|1|1", TICK, "dump"]
    s += [msg(7, MENUITEM[1]), "dump", TICK]
    s += [msg(7, MENUITEM[1]), "dump", msg(6, MENUITEM[1]), "dump",
          msg(6, MENUITEM[1]), "dump"]
    s += [msg(7, MENUITEM[1]), "dump"]
    # Two players, and the second pad goes: back to 1 on the next tick,
    # and the line with it.
    s += ["joy|1|0", TICK, "dump", TICK, "dump"]
    # Skill Level, both ways through both wraps.
    s += [msg(4, MENUITEM[2]), "dump"]
    for d in (7, 7, 7, 6, 6, 6, 6):
        s += [msg(d, MENUITEM[2]), "dump"]
    s += [TICK, "dump"]
    # Setup, the other item, and scrolls that change nothing.
    s += [msg(4, MENUITEM[3]), "dump", msg(7, MENUITEM[3]),
          msg(6, MENUITEM[3]), TICK, "dump"]
    s += ["joy|1|1", TICK, "dump", msg(4, OTHER), "dump", TICK,
          msg(7, OTHER), "dump"]
    # Two players on another item, and the first pad out.
    s += [msg(4, MENUITEM[1]), msg(7, MENUITEM[1]), msg(4, MENUITEM[3]),
          TICK, "dump", "joy|0|0", TICK, "dump", "joy|0|1", "joy|1|1"]
    # The pulse: odd steps, a whole turn and a bit, a step back.
    s += [msg(4, MENUITEM[2])]
    for e in (0.0137, 0.2, 0.31, 0.628, 0.6283, 0.62831, 1.0, 2.5, -0.05,
              0.0, 1e-7, 0.33333334):
        s += ["elapsed|%#x" % fbits(e), TICK, "dump"]
    s += ["elapsed|%#x" % fbits(1.0 / 60)]
    # Messages with nothing to do.
    for m in (2, 3, 5, 8, 9, 10, 13, 14, 15, 16, 17, 19, 24):
        s += [msg(m, MENUITEM[1])]
    s += ["dump"]
    # SELECT with two players, from the second pad, on Skill Level.
    s += [msg(1, MENUITEM[2], 1), "dump"]
    # An exit runs: everything goes to it, and TICK to OnTick first.
    for m in (18, 1, 4, 6, 7, 8, 9, 17, 24, 18):
        s += [msg(m, MENUITEM[1])]
    s += ["dump", msg(12, SCREEN), "dump", msg(12, SCREEN), "dump"]

    # Cops off, a Fred with two players and one pad.
    s += ["dcs|2|4|0|2|1", "police|0", "joy|1|0", msg(11, SCREEN), "dump"]
    # One player from the second pad: refused. From the first: car select.
    s += [msg(1, MENUITEM[1], 1), "dump", msg(1, MENUITEM[1], 0), "dump",
          TICK, "dump", msg(12, SCREEN), "dump"]

    # Two players, both pads: every item from both ports.
    for item, port in ((MENUITEM[1], 1), (MENUITEM[2], 0), (MENUITEM[3], 1),
                       (OTHER, 0), (0, 0), (MENUITEM[1] - 1, 1),
                       (0xffffffff, 0)):
        s += ["dcs|2|3|5|1|2", "joy|1|1", msg(11, SCREEN),
              msg(4, MENUITEM[2]), msg(1, item, port), "dump",
              msg(12, SCREEN), "dump"]
    # One player selects Setup.
    s += ["dcs|1|3|7|1|1", msg(11, SCREEN), msg(4, MENUITEM[3]),
          msg(1, MENUITEM[3], 0), "dump", msg(12, SCREEN), "dump"]

    # Three players, then none; a skill of 3 reads the table's 0.
    s += ["dcs|3|3|1|1|3", "joy|1|1", msg(11, SCREEN), "dump",
          msg(4, MENUITEM[1]), msg(4, MENUITEM[2]), "dump",
          msg(1, MENUITEM[1], 1), "dump", msg(12, SCREEN), "dump"]
    s += ["dcs|0|3|1|1|0", "joy|1|1", msg(11, SCREEN), "dump",
          msg(4, MENUITEM[1]), msg(6, MENUITEM[1]), "dump",
          msg(12, SCREEN)]
    s += ["dcs|-4|3|1|1|0", "joy|1|0", msg(11, SCREEN), "dump",
          msg(4, MENUITEM[1]), msg(7, MENUITEM[1]), "dump",
          msg(12, SCREEN)]
    # The first pad out from the start.
    s += ["dcs|2|3|1|1|2", "joy|0|0", "joy|1|1", msg(11, SCREEN), "dump",
          msg(4, MENUITEM[1]), TICK, "dump", msg(1, MENUITEM[1], 0),
          "dump", msg(12, SCREEN), "dump"]
    # A fresh pulse stepped to exactly 6.283: no wrap, since Step asks
    # 6.283 < phase. Then a scroll on an item that is not the current one:
    # the line is the scrolled item's.
    s += ["joy|0|1", "dcs|1|3|1|1|0", msg(11, SCREEN), msg(4, MENUITEM[2]),
          "elapsed|0x3f20d845", TICK, "dump", "elapsed|0x3c888889",
          TICK, "dump", msg(4, MENUITEM[3]), msg(7, MENUITEM[2]), "dump",
          msg(6, MENUITEM[2]), "dump", msg(12, SCREEN)]
    # Another screen's hash in the ACTIVATE: everything is on it.
    s += [msg(11, 0x0badf00d), msg(4, MENUITEM[1]), TICK, "dump",
          msg(1, MENUITEM[3], 0), "dump", msg(12, 0x0badf00d), "dump"]

    # BACK after changes and no SELECT: only the destructor hands Fred the
    # settings, the count and the game type, over whatever Fred had.
    s += ["joy|0|1", "joy|1|1", "dcs|1|3|1|1|0", msg(11, SCREEN), "dump",
          msg(4, MENUITEM[1]), msg(7, MENUITEM[1]), msg(4, MENUITEM[2]),
          msg(7, MENUITEM[2]), "type|3", "cars|5", "dump", msg(12, SCREEN),
          "dump"]

    # No arrows on the screen, then only the right one.
    s += [obj(LEFT_ARROW, 0), obj(RIGHT_ARROW, 0), "joy|0|1", "joy|1|1",
          "dcs|1|3|1|1|0", msg(11, SCREEN), msg(4, MENUITEM[1]), TICK,
          "dump", msg(12, SCREEN)]
    s += [obj(RIGHT_ARROW, 2, (610, 86, 626, 102), 94, 610.0),
          obj(LEFT_ARROW, 1, (394, 86, 410, 102), 94, 394.0),
          msg(11, SCREEN), msg(4, MENUITEM[1]), TICK, "dump",
          msg(12, SCREEN)]
    # A value object that is not there, and brackets off the box's edges.
    s += [obj(PLAYERS_VALUE, 0), obj(MENUITEM[2], 1, (5, -40, 9, -2), -21),
          obj(MI_UNDERSCORE, 0), obj(MI_MASK[1], 0), msg(11, SCREEN),
          msg(4, MENUITEM[1]), msg(4, MENUITEM[2]), TICK, "dump",
          msg(1, MENUITEM[2], 0), "dump", msg(12, SCREEN), "dump"]

    # tfeSineWave by itself, off the arrows' 0 to 128: a low bound that is
    # not 0, bounds the wrong way round, negatives to truncate, and steps
    # through the wrap and back.
    for lo, hi, rate, steps in (
            (-20.0, 300.0, 3.5, (0.1, 0.5, 1.0, 0.0137, 2.0, -0.3, 0.0)),
            (200.0, -50.0, 10.0, (0.05, 0.3, 0.628, 0.6283)),
            (-100.0, -1.0, 1.0, (1.0, 1.5, 3.0, 0.783, 6.283))):
        s += ["wave|%#x|%#x|%#x" % (fbits(lo), fbits(hi), fbits(rate))]
        s += ["wstep|%#x" % fbits(d) for d in steps]
    return s


# =================================================================== model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        e.stub_bware()
        self.objs = {}
        self.joy = [0, 0]
        self.chunks = {}        # chunk address -> (screen, hash)
        self.chunk_of = {}      # hash -> chunk address
        self.inst = 0
        self.exit = 0
        self.data = e.alloc(16)
        self.wave = e.alloc(16)
        self.path_buf = e.alloc(64)
        e.put32(PINSTANCE, 0)
        e.put32(RP + 48, (-7) & M32)
        e.put32(RP + 596, (-9) & M32)
        for off in (8, 12, 16, 20, 24, 32, 0x1072c, 0x10734):
            e.put32(FRED + off, 0)
        for a, fn in (
                (B_MALLOC, self.malloc), (B_DELETE, lambda em: 0),
                (K_SEL_CTOR, self.say("  kit sel init")),
                (K_SEL_ADD, self.sel_add), (K_SEL_CUR, self.sel_cur),
                (K_SEL_DTOR, lambda em: 0),
                (K_BLURB_CTOR, self.blurb_ctor),
                (K_BLURB_DTOR, self.say("  kit blurb release")),
                (K_BLURB_ANIM, self.say("  kit blurb animate")),
                (K_BLURB_TEXT, self.blurb_text),
                (K_SLIDEIN_CTOR, self.slidein_ctor),
                (K_SLIDEIN_DTOR, self.slide_release),
                (K_SLIDE_ANIM, self.slide_anim),
                (K_SLIDE_GROUP, self.slide_group),
                (K_HL_CTOR, self.hl_ctor), (K_HL_DTOR, lambda em: 0),
                (K_HL_ITEM, self.hl_item), (K_HL_ANIM, self.hl_anim),
                (K_EXIT_CTOR, self.exit_ctor),
                (K_EXIT_DTOR, self.slide_release),
                (K_EXIT_MSG, self.exit_msg),
                (S_FIND, self.find_stub), (S_ALPHA, self.alpha),
                (S_CENTERY, self.centery), (S_CHUNKVIS, self.chunkvis),
                (S_CY, self.cy), (S_BBOX, self.bbox), (S_TOPY, self.topy),
                (S_TOPX, self.topx), (S_LANG, self.lang), (S_VIS, self.vis),
                (S_GRAY, self.gray), (S_JOY, self.joy_stub),
                (S_MOVIE, self.movie), (S_HELP, self.help),
                (S_CARS, self.fred_call("  fred cars")),
                (S_PRELOAD, self.fred_call("  fred preload")),
                (S_RPSETUP, self.fred_call("  fred rp setup"))):
            e.stub(a, fn)

    def emit(self, s):
        self.out.append(s)

    def say(self, line):
        def stub(em):
            self.emit(line)
            return 0
        return stub

    def cstr(self, a, n=200):
        b = bytearray()
        mem = self.e.mem
        while len(b) < n and mem[a]:
            b.append(mem[a])
            a += 1
        return b.decode("latin-1")

    def find(self, h):
        o = self.objs.get(h)
        return o if o and o["kind"] else None

    # ---- bWare

    def malloc(self, em):
        size = s32(em.reg[4])
        a = self.e.alloc(size)
        # bMalloc does not clear, so +28, the current item, is the heap's
        # until the first HIGHLIGHT; the port's starts at 0. Both act as
        # any item but MENUITEM_1 does, and the menu highlights one as the
        # screen opens.
        self.e.write(a, bytes(size))
        if size == 720:
            self.inst = a
        elif size == 28:
            self.exit = a
        else:
            self.emit("  malloc %d" % size)
        return a

    # ---- the kit

    def slide_name(self, a):
        if self.inst and a == self.inst + 600:
            return "slidein"
        if a and a == self.exit:
            return "exit"
        return "?%08x" % a

    def hl_name(self, a):
        if self.inst and a == self.inst + 620:
            return "hl1"
        if self.inst and a == self.inst + 652:
            return "hl2"
        return "?"

    def sel_add(self, em):
        r = em.reg
        n = s32(r[7])
        items = " ".join("%08x" % self.e.u32((r[6] & M32) + 4 * i)
                         for i in range(n))
        self.emit("  kit sel items %08x mode %d n %d %s" % (
            r[5] & M32, s32(self.e.u32((r[4] & M32) + 144)), n, items))
        return 0

    def sel_cur(self, em):
        self.emit("  kit sel current %08x" % (em.reg[5] & M32))
        return 0

    def blurb_ctor(self, em):
        r = em.reg
        self.emit("  kit blurb init %08x %08x %08x %08x" % (
            r[5] & M32, r[6] & M32, r[7] & M32, r[8] & M32))
        return r[4] & M32

    def blurb_text(self, em):
        self.emit("  kit blurb text %d" % s32(em.reg[5]))
        return 0

    def slidein_ctor(self, em):
        r = em.reg
        self.emit("  kit slidein init %08x %08x" % (r[5] & M32,
                                                   em.fpr[12] & M32))
        return r[4] & M32

    def slide_release(self, em):
        self.emit("  kit slide release %s" % self.slide_name(em.reg[4] & M32))
        return 0

    def slide_anim(self, em):
        self.emit("  kit slide animate %s" % self.slide_name(em.reg[4] & M32))
        return 0

    def slide_group(self, em):
        r, f = em.reg, em.fpr
        self.emit("  kit slide group %s %08x %08x %08x %08x %08x" % (
            self.slide_name(r[4] & M32), r[5] & M32, r[6] & M32,
            f[12] & M32, f[13] & M32, f[14] & M32))
        return 0

    def hl_ctor(self, em):
        r = em.reg
        self.emit("  kit hl init %s %08x %08x %08x" % (
            self.hl_name(r[4] & M32), r[5] & M32, r[6] & M32, r[7] & M32))
        return r[4] & M32

    def hl_item(self, em):
        r = em.reg
        self.emit("  kit hl item %s %08x" % (self.hl_name(r[4] & M32),
                                            r[5] & M32))
        return 0

    def hl_anim(self, em):
        self.emit("  kit hl animate %s" % self.hl_name(em.reg[4] & M32))
        return 0

    def exit_ctor(self, em):
        r = em.reg
        e = r[4] & M32
        self.exit = e
        self.e.put32(e + 16, fbits(EXIT_TOTAL))
        self.emit("  kit exit init %08x %s %d" % (
            r[5] & M32, self.cstr(r[6] & M32), s32(r[7])))
        return e

    def exit_msg(self, em):
        r = em.reg
        if (r[4] & M32) != self.exit:
            self.emit("  exit msg on %08x" % (r[4] & M32))
        if (r[6] & M32) != self.data:
            self.emit("  exit msg data %08x" % (r[6] & M32))
        self.emit("  kit exit msg %d" % s32(r[5]))
        # A mark of its own in the reply, so what the screen passes back
        # from it is checked too.
        self.e.put32(self.data + 8, (100 + s32(r[5])) & M32)
        self.e.put32(self.data + 12, 0)
        return 0

    # ---- the Flailer

    def chunk(self, h):
        if h not in self.chunk_of:
            a = self.e.alloc(16)
            self.chunk_of[h] = a
        return self.chunk_of[h]

    def find_stub(self, em):
        r = em.reg
        screen, h, t = r[4] & M32, r[5] & M32, s32(r[6])
        self.emit("  find %08x %08x %d" % (screen, h, t))
        o = self.find(h)
        if not o or (t != 0 and o["kind"] != t):
            return 0
        a = self.chunk(h)
        self.chunks[a] = (screen, h)
        return a

    def chunk_name(self, a):
        return self.chunks.get(a, (0xdeadbeef, a))

    def alpha(self, em):
        r = em.reg
        screen, h = self.chunk_name(r[4] & M32)
        self.emit("  alpha %08x %08x %d %d" % (screen, h, s32(r[5]),
                                               s32(r[6])))
        return 0

    def centery(self, em):
        screen, h = self.chunk_name(em.reg[4] & M32)
        self.emit("  centery %08x %08x %08x" % (screen, h,
                                               em.fpr[12] & M32))
        return 0

    def chunkvis(self, em):
        r = em.reg
        screen, h = self.chunk_name(r[4] & M32)
        self.emit("  chunkvis %08x %08x %d" % (screen, h, s32(r[5])))
        return 0

    def cy(self, em):
        r = em.reg
        self.emit("  cy %08x %08x" % (r[4] & M32, r[5] & M32))
        o = self.find(r[5] & M32)
        return (o["cy"] if o else 0) & M32

    def bbox(self, em):
        r = em.reg
        self.emit("  bbox %08x %08x" % (r[4] & M32, r[5] & M32))
        o = self.find(r[5] & M32)
        if o:
            for reg, v in zip((6, 7, 8, 9), o["box"]):
                self.e.put32(r[reg] & M32, v & M32)
        return 0

    def topy(self, em):
        r = em.reg
        self.emit("  topy %08x %08x %d" % (r[4] & M32, r[5] & M32,
                                           s32(r[6])))
        return 0

    def topx(self, em):
        r = em.reg
        self.emit("  topx %08x %08x" % (r[4] & M32, r[5] & M32))
        o = self.find(r[5] & M32)
        em.fpr[0] = o["x"] if o else 0
        return 0

    def lang(self, em):
        r = em.reg
        self.emit("  lang %08x %08x %d" % (r[4] & M32, r[5] & M32,
                                           s32(r[6])))
        return 0

    def vis(self, em):
        r = em.reg
        self.emit("  vis %08x %08x %d" % (r[4] & M32, r[5] & M32, s32(r[6])))
        return 0

    def gray(self, em):
        r = em.reg                      # (item, mode, screen)
        self.emit("  gray %08x %08x %d" % (r[6] & M32, r[4] & M32,
                                           s32(r[5])))
        return 0

    # ---- the rest

    def joy_stub(self, em):
        p = s32(em.reg[4])
        self.emit("  joy %d" % p)
        return self.joy[p] if p in (0, 1) else 0

    def movie(self, em):
        self.emit("  movie %s" % self.cstr(em.reg[5] & M32))
        return 0

    def help(self, em):
        a = em.reg[4] & M32
        if not a:
            self.emit("  help none")
            return 0
        ids = []
        while self.e.u32(a):
            ids.append(" %d" % s32(self.e.u32(a)))
            a += 4
        self.emit("  help" + "".join(ids))
        return 0

    def fred_call(self, line):
        def stub(em):
            if (em.reg[4] & M32) != FRED:
                self.emit("  not fred %08x" % (em.reg[4] & M32))
            self.emit(line)
            return 0
        return stub

    # ---- ops

    def dump(self):
        g = self.e.u32
        b = g(PINSTANCE)
        if not b:
            self.emit("  inst 0")
        else:
            self.emit("  inst 1 cur %08x data %d %d %d %d %d exit %d" % (
                (g(b + 28),) + tuple(s32(g(b + 4 + 4 * i)) for i in range(5))
                + (1 if g(b + 684) else 0,)))
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
        if o == "obj":
            self.objs[n[0] & M32] = {"kind": n[1], "box": n[2:6],
                                     "cy": n[6], "x": n[7] & M32}
        elif o == "joy":
            self.joy[n[0] & 1] = n[1]
        elif o == "dcs":
            for i, v in enumerate(n[:5]):
                e.put32(FRED + 8 + 4 * i, v & M32)
        elif o == "police":
            e.put32(FRED + 32, n[0] & M32)
        elif o == "type":
            e.put32(FRED + 0x1072c, n[0] & M32)
        elif o == "cars":
            e.put32(FRED + 0x10734, n[0] & M32)
        elif o == "wave":
            w = self.wave
            e.fpr[12], e.fpr[13], e.fpr[14] = (n[0] & M32, n[1] & M32,
                                               n[2] & M32)
            e.call(T_WAVE_CTOR, w)
            self.emit("  wave %08x %08x %08x %08x"
                      % tuple(e.u32(w + 4 * i) for i in range(4)))
        elif o == "wstep":
            w = self.wave
            e.fpr[12] = n[0] & M32
            e.call(T_WAVE_STEP, w)
            phase = e.u32(w + 12)
            e.call(T_WAVE_VAL, w)
            val = e.fpr[0] & M32
            iv = e.call(T_WAVE_INT, w)
            self.emit("  wave phase %08x val %08x int %d" % (phase, val, iv))
        elif o == "elapsed":
            e.put32(ELAPSED, n[0] & M32)
        elif o == "msg":
            d = self.data
            e.put32(d, n[1] & M32)
            e.put32(d + 4, n[2] & M32)
            e.put32(d + 8, 0x5a)
            e.put32(d + 12, 0x5b)
            e.call(F_CALLBACK, n[0], d, limit=2000000)
            self.emit("  data %d %d" % (s32(e.u32(d + 8)),
                                        s32(e.u32(d + 12))))
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


def model(lines):
    return Model().run(lines)


# ================================================================= build

def build_harness(tmp, name="setup_test"):
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


def write_script(d, lines):
    sc = Path(d) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    return sc


# ============================================================= mutations

S = BSETUP
H = "3DS Files/source/bsetup.h"
MUTATIONS = [
    # Fred's bytes.
    ("load-mode", S, "d->challengeMode = get32(p + 4);",
     "d->challengeMode = get32(p + 8);"),
    ("load-skill", S, "d->beACopSkill   = get32(p + 16);",
     "d->beACopSkill   = get32(p + 12);"),
    ("save-skill", S, "    put32(p + 16, d->beACopSkill);", "    (void)0;"),
    ("save-race", S, "put32(p + 8, d->raceMode);",
     "put32(p + 8, d->skillLevel);"),
    ("fred-type", S, "put32(fred + FRED_GAME_TYPE, gameType);",
     "put32(fred + FRED_GAME_TYPE, gameType + 1);"),
    ("fred-cars", S, "put32(fred + FRED_NUM_PLAYER_CARS, numPlayerCars);",
     "put32(fred + FRED_NUM_PLAYER_CARS, 1);"),
    ("fred-type-offset", H, "#define FRED_GAME_TYPE          0x1072c",
     "#define FRED_GAME_TYPE          0x10730"),
    ("fred-dcs-offset", H, "#define FRED_CHALLENGE_SCREEN   8 ",
     "#define FRED_CHALLENGE_SCREEN   12 "),
    ("game-type", H, "#define FRED_CHALLENGE_GAME_BE_A_COP  7",
     "#define FRED_CHALLENGE_GAME_BE_A_COP  8"),

    # tfeSineWave.
    ("wave-lo", S, "bsine_init(&r->pulse, 0.0f, 128.0f, 10.0f);",
     "bsine_init(&r->pulse, 1.0f, 128.0f, 10.0f);"),
    ("wave-hi", S, "bsine_init(&r->pulse, 0.0f, 128.0f, 10.0f);",
     "bsine_init(&r->pulse, 0.0f, 127.0f, 10.0f);"),
    ("wave-rate", S, "bsine_init(&r->pulse, 0.0f, 128.0f, 10.0f);",
     "bsine_init(&r->pulse, 0.0f, 128.0f, 9.0f);"),
    ("wave-phase0", S, "    w->phase = 0.0f;", "    w->phase = 0.5f;"),
    ("step-le", S, "if (BSINE_WRAP < w->phase)",
     "if (BSINE_WRAP <= w->phase)"),
    ("step-while", S, "if (BSINE_WRAP < w->phase)",
     "while (BSINE_WRAP < w->phase)"),
    ("step-no-wrap", S, "if (BSINE_WRAP < w->phase)", "if (0)"),
    ("step-mod", S, "w->phase = w->phase - BSINE_WRAP;",
     "w->phase = 0.0f;"),
    ("wrap-2pi", H, "#define BSINE_WRAP 6.283f",
     "#define BSINE_WRAP 6.2831855f"),
    ("val-span", S, "(w->hi - w->lo) * t", "w->hi * t"),
    ("val-phase", S, "bSinF(w->phase)", "bSinF(-w->phase)"),
    ("val-round", S, "return (int32_t)bsine_val(w);",
     "return (int32_t)(bsine_val(w) + 0.5f);"),

    # The arrows.
    ("find-left-any", S, "screen, left, 2)", "screen, left, 0)"),
    ("find-right-any", S, "screen, right, 2)", "screen, right, 0)"),
    ("init-no-set", S, "    barrows_set(s, r, 0);" + NL + "}" + NL + NL
     + "void barrows_set", "}" + NL + NL + "void barrows_set"),
    ("vis-inverted", S, "int visible = r->follow != 0;",
     "int visible = r->follow == 0;"),
    ("vis-left", S, "if (r->hasLeft) HOOK(s, setBitmapVisible",
     "if (0) HOOK(s, setBitmapVisible"),
    ("vis-right", S, "if (r->hasRight) HOOK(s, setBitmapVisible",
     "if (r->hasLeft) HOOK(s, setBitmapVisible"),
    ("tick-no-step", S, "    bsine_step(&r->pulse, s->gf->realElapsed);",
     "    (void)0;"),
    ("tick-follow", S, "    if (r->follow) {" + NL + "        int32_t y",
     "    if (1) {" + NL + "        int32_t y"),
    ("tick-y", S, "HOOK(s, setBitmapCenterY, r->screen, r->left, (float)y);",
     "HOOK(s, setBitmapCenterY, r->screen, r->left, (float)y + 0.5f);"),
    ("tick-right-alpha", S, "            HOOK(s, setBitmapAlpha, r->screen, "
     "r->right," + NL + "                 bsine_val_int(&r->pulse));",
     "            HOOK(s, setBitmapAlpha, r->screen, r->right, 128);"),
    ("tick-right-left", S, "        if (r->hasRight) {" + NL
     + "            HOOK(s, setBitmapAlpha",
     "        if (r->hasLeft) {" + NL + "            HOOK(s, setBitmapAlpha"),
    ("tick-no-vis", S, "    }" + NL + "    arrowsUpdateVisibility(s, r);"
     + NL + "}" + NL + NL + "void barrows_event",
     "    }" + NL + "}" + NL + NL + "void barrows_event"),
    ("event-any", S, "if (msg == BMSG_SCREEN_TICK) arrowsTick(s, r);",
     "arrowsTick(s, r);"),

    # The helpers.
    ("vc-hi-le", S, "if (hi < v) v = lo;", "if (hi <= v) v = lo;"),
    ("vc-lo-le", S, "if (v < lo) v = hi;", "if (v <= lo) v = hi;"),
    ("vc-clamp", S, "if (hi < v) v = lo;", "if (hi < v) v = hi;"),
    ("players-zero", S, "int32_t v = n > 0 ? n : 2;",
     "int32_t v = n >= 0 ? n : 2;"),
    ("players-wrap-1", S, "int32_t v = n > 0 ? n : 2;",
     "int32_t v = n > 0 ? n : 1;"),
    ("players-three", S, "if (v >= 3) v = 1;", "if (v > 3) v = 1;"),
    ("players-no-pad", S, "    if (!joystickPluggedIn(s, 1)) v = 1;",
     "    (void)0;"),
    ("players-pad0", S, "if (!joystickPluggedIn(s, 1)) v = 1;",
     "if (!joystickPluggedIn(s, 0)) v = 1;"),
    ("players-always", S, "if (d->numPlayers == v) return 0;",
     "if (0) return 0;"),
    ("skill-range", S, "valueChanger(old, d, 0, 2)",
     "valueChanger(old, d, 0, 3)"),
    ("skill-changed", S, "return *skill != old;", "return 1;"),
    ("mjar-or", S, "    if (joystickPluggedIn(s, 0) && joystickPluggedIn(s, 1)) "
     "return;" + NL + "    barrows_set(s, r, 0);",
     "    if (joystickPluggedIn(s, 0) || joystickPluggedIn(s, 1)) return;"
     + NL + "    barrows_set(s, r, 0);"),
    ("mjar-no-set", S, "    barrows_set(s, r, 0);" + NL
     + "    maybeChangeNumPlayers(s, d, 1);",
     "    maybeChangeNumPlayers(s, d, 1);"),
    ("mjar-count", S, "    maybeChangeNumPlayers(s, d, 1);" + NL + "}",
     "    maybeChangeNumPlayers(s, d, 2);" + NL + "}"),
    ("movie-swap", S, "HOOK(s, startMovie, s->gf->copsOn ?",
     "HOOK(s, startMovie, !s->gf->copsOn ?"),
    ("movie-name", S, "worldracing_ movie.AVI", "worldracing_movie.AVI"),
    ("skill-table", S, "{30015, 30016, 30017, 0}",
     "{30016, 30015, 30017, 0}"),
    ("help-table", S, "{805000, 805001, 805002, 805003, 0}",
     "{805000, 805001, 805002, 0, 0}"),
    ("help-kept", S, "    HOOK(s, setHelpOverride, NULL);", "    (void)0;"),

    # ResyncChangeables.
    ("resync-1-lang", S, "BSETUP_OBJ_PLAYERS_VALUE, 20003);",
     "BSETUP_OBJ_PLAYERS_VALUE, 20004);"),
    ("resync-2-lang", S, "BSETUP_OBJ_PLAYERS_VALUE, 20004);",
     "BSETUP_OBJ_PLAYERS_VALUE, 20003);"),
    ("resync-1-gray", S, "ITEM_SKILL, BSCR_GRAY_ENABLE);",
     "ITEM_SKILL, BSCR_GRAY_HIDE);"),
    ("resync-2-gray", S, "ITEM_SKILL, BSCR_GRAY_DISABLE);",
     "ITEM_SKILL, BSCR_GRAY_HIDE);"),
    ("resync-1-vis", S, "BSETUP_OBJ_SKILL_VALUE, 1);",
     "BSETUP_OBJ_SKILL_VALUE, 0);"),
    ("resync-2-vis", S, "BSETUP_OBJ_SKILL_VALUE, 0);",
     "BSETUP_OBJ_SKILL_VALUE, 1);"),
    ("resync-else", S, "    } else if (b->data.numPlayers == 2) {" + NL
     + "        HOOK(s, setLanguageID", "    } else {" + NL
     + "        HOOK(s, setLanguageID"),
    ("resync-skill-field", S, "refreshOpponentSkillLevel(s, b->screen, "
     "b->data.beACopSkill,", "refreshOpponentSkillLevel(s, b->screen, "
     "b->data.skillLevel,"),

    # The blurb.
    ("blurb-1p", S, "if (b->data.numPlayers == 1) id = 19000;",
     "if (b->data.numPlayers == 1) id = 19001;"),
    ("blurb-2p-else", S, "else if (b->data.numPlayers == 2) id = 19001;",
     "else id = 19001;"),
    ("blurb-skill-field", S, "if (b->data.beACopSkill == 0) id = 19002;",
     "if (b->data.skillLevel == 0) id = 19002;"),
    ("blurb-skill-1", S, "else if (b->data.beACopSkill == 1) id = 19003;",
     "else if (b->data.beACopSkill == 1) id = 19004;"),
    ("blurb-skill-else", S, "else if (b->data.beACopSkill == 2) id = 19004;",
     "else id = 19004;"),
    ("blurb-setup", S, "            id = 19005;", "            id = 19004;"),
    ("blurb-default", S, "        default:" + NL + "            break;" + NL
     + "    }" + NL + "    banim_blurb_new_text_id",
     "        default:" + NL + "            id = 19005;" + NL
     + "            break;" + NL + "    }" + NL
     + "    banim_blurb_new_text_id"),

    # The constructor.
    ("ctor-bar", S, "BSCR_OBJ_SCROLLING_TEXT, BSCR_OBJ_WHITEOUT_BAR);",
     "BSCR_OBJ_SCROLLING_TEXT, BSCR_OBJ_SCROLLING_TEXT);"),
    ("ctor-slide-x", S, "topLeftX(s, screen, BSCR_MI_MASK(1)));",
     "topLeftX(s, screen, BSCR_MI_MASK(2)));"),
    ("ctor-hl1-color", S, "0xab671c9au," + NL
     + "                         (int32_t)BANIM_BLOOM_COLOR);",
     "0xab671c9au, -1);"),
    ("ctor-hl2-color", S, "0x1042eac3u, -1);",
     "0x1042eac3u, (int32_t)BANIM_BLOOM_COLOR);"),
    ("ctor-hl-swap", S, "&b->highlight, screen, 0xab671c9au,",
     "&b->highlight, screen, 0x1042eac3u,"),
    ("ctor-arrows-swap", S, "barrows_init(s, &b->arrows, screen, "
     "BSETUP_OBJ_LEFT_ARROW," + NL + "                 BSETUP_OBJ_RIGHT_ARROW);",
     "barrows_init(s, &b->arrows, screen, BSETUP_OBJ_RIGHT_ARROW," + NL
     + "                 BSETUP_OBJ_LEFT_ARROW);"),
    ("ctor-no-load", S, "if (s->gf->fred) bsetup_challenge_load(",
     "if (0) bsetup_challenge_load("),
    ("ctor-no-fred", S, "    fredSetGame(s, FRED_CHALLENGE_GAME_BE_A_COP, "
     "b->data.numPlayers);" + NL + "    HOOK0(s, makeChallengeCarsAvailable);",
     "    HOOK0(s, makeChallengeCarsAvailable);"),
    ("ctor-no-cars", S, "    HOOK0(s, makeChallengeCarsAvailable);" + NL
     + "    HOOK0(s, preloadCars);", "    HOOK0(s, preloadCars);"),
    ("ctor-no-preload", S, "    HOOK0(s, preloadCars);" + NL, ""),
    ("ctor-mode", S, "bsel_set_indicator_mode(&b->sel, 1);",
     "bsel_set_indicator_mode(&b->sel, 0);"),
    ("ctor-items", S, "bsel_add_items(a, &b->sel, kBeACopMasks, 3);",
     "bsel_add_items(a, &b->sel, kBeACopMasks, 2);"),
    ("ctor-resync-first", S, "    makeJoystickArrowsRight(s, &b->data, "
     "&b->arrows);" + NL + "    beACopResync(s, b);" + NL
     + "    startTheRightMovie(s);", "    beACopResync(s, b);" + NL
     + "    makeJoystickArrowsRight(s, &b->data, &b->arrows);" + NL
     + "    startTheRightMovie(s);"),
    ("ctor-no-movie", S, "    startTheRightMovie(s);" + NL
     + "    b->exitActive = 0;", "    b->exitActive = 0;"),
    ("ctor-no-help", S, "HOOK(s, setHelpOverride, kBeACopHelp);",
     "(void)kBeACopHelp;"),

    # The destructor.
    ("dtor-exit-kept", S, "    if (b->exitActive) banim_slide_release(a, "
     "&b->exit.slide);", "    (void)0;"),
    ("dtor-exit-always", S, "    if (b->exitActive) banim_slide_release(a, "
     "&b->exit.slide);", "    banim_slide_release(a, &b->exit.slide);"),
    ("dtor-no-fred", S, "    fredSetGame(s, FRED_CHALLENGE_GAME_BE_A_COP, "
     "b->data.numPlayers);" + NL + "    if (s->gf->fred) bsetup_challenge_save("
     "&b->data, s->gf->fred);" + NL + "    HOOK(s, setHelpOverride, NULL);",
     "    if (s->gf->fred) bsetup_challenge_save(&b->data, s->gf->fred);"
     + NL + "    HOOK(s, setHelpOverride, NULL);"),
    ("dtor-no-save", S, "    if (s->gf->fred) bsetup_challenge_save("
     "&b->data, s->gf->fred);" + NL + "    HOOK(s, setHelpOverride, NULL);",
     "    HOOK(s, setHelpOverride, NULL);"),
    ("dtor-slidein", S, "    banim_slide_release(a, &b->slideIn);" + NL
     + "    banim_blurb_release", "    banim_blurb_release"),
    ("dtor-blurb", S, "    banim_blurb_release(a, &b->blurb);" + NL
     + "    memset(b, 0, sizeof(*b));", "    memset(b, 0, sizeof(*b));"),
    ("dtor-live", S, "    banim_blurb_release(a, &b->blurb);" + NL
     + "    memset(b, 0, sizeof(*b));", "    banim_blurb_release(a, "
     "&b->blurb);" + NL + "    b->exitActive = 0;"),

    # OnTick.
    ("tick-no-arrows", S, "    barrows_event(s, &b->arrows, BMSG_SCREEN_TICK);",
     "    (void)0;"),
    ("tick-no-hl2", S, "    banim_highlight_animate(a, &b->change);" + NL, ""),
    ("tick-1-or", S, "        if (joystickPluggedIn(s, 0) && joystickPluggedIn("
     "s, 1)) {", "        if (joystickPluggedIn(s, 0) || joystickPluggedIn("
     "s, 1)) {"),
    ("tick-1-follow", S, "            barrows_set(s, &b->arrows, "
     "BSETUP_OBJ_PLAYERS_VALUE);" + NL + "            return;",
     "            barrows_set(s, &b->arrows, BSETUP_OBJ_SKILL_VALUE);" + NL
     + "            return;"),
    ("tick-1-on", S, "            barrows_set(s, &b->arrows, "
     "BSETUP_OBJ_PLAYERS_VALUE);" + NL + "            return;" + NL
     + "        }", "            barrows_set(s, &b->arrows, "
     "BSETUP_OBJ_PLAYERS_VALUE);" + NL + "        }"),
    ("tick-1-no-hide", S, "        barrows_set(s, &b->arrows, 0);" + NL
     + "        if (maybeChangeNumPlayers", "        if (maybeChangeNumPlayers"),
    ("tick-1-no-blurb", S, "            beACopResync(s, b);" + NL
     + "            beACopBlurb(s, b, b->current);",
     "            beACopResync(s, b);"),
    ("tick-1-always", S, "        if (maybeChangeNumPlayers(s, &b->data, 1)) {",
     "        maybeChangeNumPlayers(s, &b->data, 1); {"),
    ("tick-else-or", S, "        if (joystickPluggedIn(s, 0) && "
     "joystickPluggedIn(s, 1)) return;" + NL + "        maybeChange",
     "        if (joystickPluggedIn(s, 0) || joystickPluggedIn(s, 1)) return;"
     + NL + "        maybeChange"),
    ("tick-else-if", S, "        maybeChangeNumPlayers(s, &b->data, 1);" + NL
     + "        beACopResync(s, b);" + NL + "    }",
     "        if (maybeChangeNumPlayers(s, &b->data, 1))" + NL
     + "        beACopResync(s, b);" + NL + "    }"),

    # OnHighlight.
    ("hl-under", S, "(int32_t)((float)box[3] + -3.0f)",
     "(int32_t)((float)box[3] + -2.0f)"),
    ("hl-under-right", S, "(int32_t)((float)box[3] + -3.0f)",
     "(int32_t)((float)box[2] + -3.0f)"),
    ("hl-over", S, "(int32_t)((float)box[1] - 6.0f)",
     "(int32_t)((float)box[1] - 5.0f)"),
    ("hl-over-left", S, "(int32_t)((float)box[1] - 6.0f)",
     "(int32_t)((float)box[0] - 6.0f)"),
    ("hl-bracket-swap", S, "HOOK(s, setTopLeftY, b->screen, "
     "BSCR_OBJ_MI_UNDERSCORE,", "HOOK(s, setTopLeftY, b->screen, "
     "BSCR_OBJ_MI_OVERSCORE,"),
    ("hl-current", S, "    b->current = item;", "    b->current = 0;"),
    ("hl-hl1", S, "banim_highlight_set_item(a, &b->highlight, item);",
     "banim_highlight_set_item(a, &b->change, item);"),
    ("hl-no-mjar", S, "            makeJoystickArrowsRight(s, &b->data, "
     "&b->arrows);" + NL + "            bsel_set_current",
     "            bsel_set_current"),
    ("hl-mask1", S, "bsel_set_current(a, &b->sel, BSCR_MI_MASK(1));",
     "bsel_set_current(a, &b->sel, BSCR_MI_MASK(2));"),
    ("hl-mask2", S, "bsel_set_current(a, &b->sel, BSCR_MI_MASK(2));",
     "bsel_set_current(a, &b->sel, BSCR_MI_MASK(3));"),
    ("hl-skill-follow", S, "            barrows_set(s, &b->arrows, "
     "BSETUP_OBJ_SKILL_VALUE);", "            barrows_set(s, &b->arrows, "
     "0);"),
    ("hl-setup-follow", S, "            barrows_set(s, &b->arrows, 0);" + NL
     + "            bsel_set_current", "            barrows_set(s, "
     "&b->arrows, BSETUP_OBJ_SKILL_VALUE);" + NL + "            bsel_set_current"),
    ("hl-setup-hl2", S, "banim_highlight_set_item(a, &b->change, 0);",
     "banim_highlight_set_item(a, &b->change, BSETUP_OBJ_SKILL_VALUE);"),

    # OnScroll.
    ("scroll-dir", S, "msg == BMSG_MENUITEM_PAD_LEFT ? -1 : 1;",
     "msg == BMSG_MENUITEM_PAD_LEFT ? 1 : -1;"),
    ("scroll-players-dir", S, "b->data.numPlayers + dir);",
     "b->data.numPlayers - dir);"),
    ("scroll-players-obj", S, "        object  = BSETUP_OBJ_PLAYERS_VALUE;",
     "        object  = BSETUP_OBJ_SKILL_VALUE;"),
    ("scroll-skill-field", S, "maybeChangeOpponentSkillLevel(dir, "
     "&b->data.beACopSkill);", "maybeChangeOpponentSkillLevel(dir, "
     "&b->data.skillLevel);"),
    ("scroll-noise-kept", S, "        data->noise = 0;" + NL
     + "        return;", "        return;"),
    ("scroll-noise-left", S, "data->noise = BSND_MENU_LEFT;",
     "data->noise = BSND_MENU_RIGHT;"),
    ("scroll-noise-right", S, "data->noise = BSND_MENU_RIGHT;",
     "data->noise = BSND_MENU_LEFT;"),
    ("scroll-no-hl2", S, "banim_highlight_set_item(clock(s), &b->change, "
     "object);", "(void)object;"),
    ("scroll-no-resync", S, "    beACopResync(s, b);" + NL
     + "    beACopBlurb(s, b, data->itemHash);", "    beACopBlurb(s, b, "
     "data->itemHash);"),
    ("scroll-blurb-current", S, "    beACopBlurb(s, b, data->itemHash);",
     "    beACopBlurb(s, b, b->current);"),

    # SELECT.
    ("sel-any-port", S, "(b->data.numPlayers == 1 && data->port == 0)",
     "(b->data.numPlayers == 1)"),
    ("sel-two-up", S, "|| b->data.numPlayers == 2))",
     "|| b->data.numPlayers >= 2))"),
    ("sel-no-save", S, "    if (s->gf->fred) bsetup_challenge_save("
     "&b->data, s->gf->fred);" + NL + "    numPlayers",
     "    numPlayers"),
    ("sel-no-fred", S, "    fredSetGame(s, FRED_CHALLENGE_GAME_BE_A_COP, "
     "numPlayers);", "    (void)0;"),
    ("sel-rp-mode", S, "HOOK(s, setRaceParameters, numPlayers, "
     "b->data.raceMode);", "HOOK(s, setRaceParameters, numPlayers, "
     "b->data.challengeMode);"),
    ("sel-range", S, "data->itemHash >= ITEM_PLAYERS && data->itemHash <= "
     "ITEM_SKILL", "data->itemHash == ITEM_PLAYERS"),
    ("sel-range-signed", S, "data->itemHash >= ITEM_PLAYERS && "
     "data->itemHash <= ITEM_SKILL", "(int32_t)data->itemHash >= "
     "(int32_t)ITEM_PLAYERS && (int32_t)data->itemHash <= (int32_t)ITEM_SKILL"),
    ("sel-car-1p", S, '"Select Car2P" : "Select Car"',
     '"Select Car" : "Select Car2P"'),
    ("sel-no-cars", S, "        HOOK0(s, makeChallengeCarsAvailable);" + NL
     + "        HOOK0(s, setupRace", "        HOOK0(s, setupRace"),
    ("sel-no-rpsetup", S, "        HOOK0(s, setupRaceParametersAfterRaceSetup);"
     + NL, ""),
    ("sel-setup-target", S, 'target = "Be The Cop Setup";',
     'target = "Single Race Setup";'),
    ("sel-group-dur", S, "BANIM_OFFSCREEN_X, b->exit.slide.totalTime);",
     "BANIM_OFFSCREEN_X, 0.5f);"),
    ("sel-group-x", S, "topLeftX(s, b->screen, BSCR_OBJ_MI_UNDERSCORE),",
     "topLeftX(s, b->screen, BSCR_OBJ_MI_OVERSCORE),"),
    ("sel-exit-off", S, "    b->exitActive = 1;", "    b->exitActive = 0;"),

    # HandleEvent and Callback.
    ("ev-tick-not-exiting", S, "    if (msg == BMSG_SCREEN_TICK) "
     "beACopTick(s, b);", "    if (msg == BMSG_SCREEN_TICK && "
     "!b->exitActive) beACopTick(s, b);"),
    ("ev-exit-falls", S, "            data->noise = noise;" + NL + "        }"
     + NL + "        return;", "            data->noise = noise;" + NL
     + "        }"),
    ("ev-exit-param", S, "            data->param = param;", "            (void)0;"),
    ("ev-exit-noise", S, "            data->noise = noise;", "            (void)0;"),
    ("ev-unhighlight", S, "        case BMSG_MENUITEM_HIGHLIGHT:",
     "        case BMSG_MENUITEM_UNHIGHLIGHT:"),
    ("ev-scroll-up", S, "        case BMSG_MENUITEM_PAD_RIGHT:" + NL
     + "            beACopScroll", "        case BMSG_MENUITEM_PAD_RIGHT:"
     + NL + "        case BMSG_MENUITEM_PAD_UP:" + NL + "            beACopScroll"),
    ("cb-screen", S, "beACopCtor(s, data ? data->itemHash : "
     "BSETUP_SCREEN_BEACOP);", "beACopCtor(s, BSETUP_SCREEN_BEACOP);"),
    ("cb-unactivate-twice", S, "            if (s->beACop.live) beACopDtor(s);",
     "            beACopDtor(s);"),
]

EQUIVALENT = {
    "event-any": "the arrows' HandleEvent has one caller, OnTick, and it "
                 "passes SCREEN_TICK",
    "skill-changed": "OnScroll's step is 1 or -1, and ValueChanger moves any "
                     "value by one of those or wraps it to the other end, "
                     "so the level always changes",
    "sel-range-signed": "MENUITEM_1 and MENUITEM_2 are 0x52e039f3 and "
                        "0x52e039f4, both below 0x80000000, so the signed "
                        "and unsigned ranges hold the same two hashes",
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
    scp = write_script(indir.name, lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, scp, out)
        if diff(base, out.read_text().splitlines(), quiet=True):
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
                    exe = build_harness(tmp)
                except SystemExit:
                    print("  %-44s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, scp, out)
                if rc == pcc.HARNESS_HUNG:
                    print("  %-44s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-44s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text().splitlines(), quiet=True)
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
        exe = build_harness(tmp)
        scp = write_script(tmp, lines)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(got) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(got, harness)
    print("%d ops, %d lines, %d differ" % (len(lines), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
