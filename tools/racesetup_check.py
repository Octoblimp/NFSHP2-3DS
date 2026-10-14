#!/usr/bin/env python3
"""Cross-check 3DS Files/source/bsetup.c's Be The Cop Setup against the
retail image, SLES_507.31.

**The model** is retail's own BeTheCopSetup: BaseCallback (0x001b7b20)
through its Callback (0x001b93d8), the constructors and destructors of
BeTheCopSetup (0x001b9248, 0x001b9348) and RaceSetupBaseClass (0x001b8390,
0x001b84f0), HandleMenuEvent (0x001b7ea8), Attach, BuildMenu,
ResyncChangeables, FindChangeable, GetIndexForMenuItem, SetupHighlight,
the three rows' MaybeChange and Refresh, ValueChanger; and the
tScrollingMenuList (0x00249c78..0x0024a888) with its tMenuAnimElements,
the arrows class and tfeSineWave with the real bSin -- all run in
retail_model.RetailEmu on retail's Fred (0x002fc050). The harness is
tools/src/setup_test.c, the one setup_check.py runs, driving
bsetup_btc_callback through its rmsg op.

**The stubs** are setup_check.py's -- the animation kit at its retail
addresses and the Flailer calls -- and these more:

- tHighlightAnimation::ForceStart and tSlideAnimation::IsFinished (what it
  answers is the script's `fin`);
- SplineSeek (0x001daec8), which banim_check.py checks: both sides print
  the spline's value, destination and state and the three arguments, then
  arrive at once;
- FlailerGetTopLeftY and FlailerObjectChunk::GetTopLeft (both print
  `gety`), FlailerObjectChunk::SetTopLeftY(float) (`sety`, which moves the
  object, so the scroller reads back what it wrote), FlailerSetClipToPoly
  and FlailerObjectChunk::SetClipToPoly (`clip`), FlailerSetAlpha
  (`setalpha`), and GrayMenuItem(char*, int, int, int) (`grayn`).

The chunks the model hands out carry their hash at +8, where
FindMenuElement reads it.

**The script** activates the screen from Freds with the defaults and
others, cops on and off; ticks it with the slide in running and finished,
at odd elapsed times; highlights each row; scrolls each both ways through
Traffic's wraps; pads up and down off both ends; moves rows off the
visible area both ways so the scroller seeks, and ticks the seek; selects
with one car, two and others; sends every message during the exit; and
unactivates with and without one, and twice. Retail reads unchecked in
four places the script stays off: a HIGHLIGHT on an item no row has, a
value off its row's table, a mask the screen does not have (the box is
the stack's), and a message with no instance. bsetup.c guards each; see
docs/formats/frontend-setup.md.

    python tools/racesetup_check.py
    python tools/racesetup_check.py --mutate [--only a,b]
    python tools/racesetup_check.py --dump out/racesetup
"""
import argparse
import os
import struct
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

PINSTANCE = GP - 18780          # RaceSetupBaseClass::pInstance
F_CALLBACK = 0x001b93d8
F_SCROLL_INIT = 0x0024a888      # _GLOBAL_$I: the mask table at 0x0031cfa0
F_DCS_DEFAULTS = 0x001b5e10     # DataChallengeScreen::InitWithDefaults
F_BTC_DEFAULTS = 0x001b93e0     # DataBeTheCopSetup's

SCREEN = 0xd1eadbca
MENUITEM = [0] + [0x52e039f2 + i for i in range(1, 10)]
MI_MASK = [0, 0x6e34e350, 0x708a0bf1, 0x72df3492, 0x75345d33, 0x778985d4,
           0x79deae75, 0x7c33d716, 0x7e88ffb7]
TEXT = [0] + [0x69a2c756 + i for i in range(1, 9)]
LEFT_ARROW, RIGHT_ARROW = 0xd1cda594, 0x9345e4a7
UP_ARROW, DOWN_ARROW, CLIP = 0xedf2e4ee, 0x20d73d01, 0xc67cfb4a
MI_UNDERSCORE, MI_OVERSCORE = 0x32c91dae, 0xc671680c
OTHER = 0x0badcafe

K_HL_FORCE = 0x00248ad0
K_SLIDE_FIN = 0x00248db0
S_SEEK = 0x001daec8
S_GETY = 0x00144168
S_CHUNK_TL = 0x00140978
S_CHUNK_SETY = 0x00140a48
S_CHUNK_CLIP = 0x00140a70
S_CLIP = 0x00144358
S_SETALPHA = 0x001448e8
S_GRAYN = 0x0016d2a8

fbits = sc.fbits


# ================================================================== script

def obj(h, kind, box=(0, 0, 0, 0), cy=0, x=0.0, y=0.0):
    return sc.obj(h, kind, box, cy, x) + "|%#x" % fbits(y)


def msg(m, item=0, port=0):
    return "rmsg|%d|%#x|%d" % (m, item, port)


TICK = msg(18)
YS = [0, 71.0, 107.0, 144.0, 181.0, 217.0, 254.0, 292.0, 330.0]


def screen_objects(ys=YS):
    s = []
    for i in range(1, 9):
        y = ys[i]
        s.append(obj(MENUITEM[i], 1, (153, int(y), 330, int(y) + 22),
                     int(y) + 11, 153.0, y))
        s.append(obj(TEXT[i], 1, (430, int(y), 560, int(y) + 22),
                     int(y) + 11, 430.0, y + 0.5))
        s.append(obj(MI_MASK[i], 2, (0, int(y) - 4, 640, int(y) + 26),
                     int(y) + 11, 21.5, y - 4.0))
    s += [obj(LEFT_ARROW, 2, (388, 75, 404, 91), 83, 388.0, 75.0),
          obj(RIGHT_ARROW, 2, (583, 76, 599, 92), 84, 583.0, 76.0),
          obj(UP_ARROW, 2, (300, 50, 316, 60), 55, 300.0, 50.0),
          obj(DOWN_ARROW, 2, (300, 360, 316, 370), 365, 300.0, 360.0),
          obj(CLIP, 2, (0, 60, 640, 360), 210, 0.0, 60.0),
          obj(MI_UNDERSCORE, 2, (30, 100, 620, 104), 102, 30.25, 100.0),
          obj(MI_OVERSCORE, 2, (30, 60, 620, 64), 62, 30.25, 60.0)]
    return s


def script():
    s = []
    # Fred's defaults, over garbage.
    s += ["dcs|9|9|9|9|9", "btc|9|9|9|9|9", "fdef", "dump", "rdump"]
    s += screen_objects()
    s += ["btc|2|0|1|0|1", "cars|1", "police|1", "fin|0",
          "elapsed|%#x" % fbits(1.0 / 60)]
    # The defaults, the photo's: Catch-up On, Traffic Minimum, Damage On.
    s += [msg(11, SCREEN), "rdump", TICK, "rdump", "fin|1", TICK, "rdump"]
    s += [msg(4, MENUITEM[1]), "rdump", TICK, "rdump"]
    # Catch-up both ways, and a row that is not there.
    s += [msg(7, MENUITEM[1]), "rdump", msg(6, MENUITEM[1]), "rdump",
          msg(6, MENUITEM[1]), "rdump", msg(7, OTHER), msg(6, MENUITEM[4]),
          "rdump"]
    # Up off the top: taken.
    s += [msg(8, MENUITEM[1]), "rdump"]
    # Down to Traffic, and round its four both ways.
    s += [msg(9, MENUITEM[1]), msg(4, MENUITEM[2]), "rdump"]
    for d in (7, 7, 7, 7, 7, 6, 6, 6, 6, 6):
        s += [msg(d, MENUITEM[2]), "rdump"]
    s += [msg(9, MENUITEM[2]), msg(4, MENUITEM[3]), "rdump"]
    # Damage, and down off the bottom: taken, and the mask stays.
    s += [msg(7, MENUITEM[3]), "rdump", msg(6, MENUITEM[3]), "rdump",
          msg(9, MENUITEM[3]), "rdump", msg(9, MENUITEM[3]), "rdump"]
    # Back up, one past the top.
    s += [msg(8, MENUITEM[3]), msg(4, MENUITEM[2]), msg(8, MENUITEM[2]),
          msg(4, MENUITEM[1]), msg(8, MENUITEM[1]), "rdump"]
    # The pulses: odd steps, a whole turn and a bit.
    for e in (0.0137, 0.31, 0.6283, 0.62831, 2.5, -0.05, 0.0, 0.33333334):
        s += ["elapsed|%#x" % fbits(e), TICK, "rdump"]
    s += ["elapsed|%#x" % fbits(1.0 / 60)]
    # Messages with nothing to do.
    for m in (2, 3, 5, 10, 13, 14, 15, 16, 17, 19, 24):
        s += [msg(m, MENUITEM[1])]
    s += ["rdump"]
    # SELECT with one car: car select; then everything goes to the exit.
    s += [msg(1, MENUITEM[2]), "rdump"]
    for m in (18, 1, 4, 6, 7, 8, 9, 17, 24, 18):
        s += [msg(m, MENUITEM[1])]
    s += ["rdump", msg(12, SCREEN), "rdump", msg(12, SCREEN), "rdump"]

    # Cops off, another Fred, two cars, and the slide in still running.
    s += ["btc|1|1|0|3|0", "cars|2", "police|0", "fin|0", msg(11, SCREEN),
          "rdump", msg(4, MENUITEM[2]), msg(7, MENUITEM[2]), "rdump",
          msg(6, MENUITEM[2]), msg(6, MENUITEM[2]), TICK, "rdump",
          msg(1, MENUITEM[1], 1), "rdump", TICK, msg(12, SCREEN), "rdump"]
    # Other car counts go to the one-player screen.
    for cars in (0, 3, -1):
        s += ["cars|%d" % cars, msg(11, SCREEN), msg(4, MENUITEM[1]),
              msg(1, MENUITEM[1]), "rdump", msg(12, SCREEN), "rdump"]
    # BACK with changes and no SELECT: the destructor still saves them.
    s += ["btc|2|0|1|0|1", "cars|1", "police|1", msg(11, SCREEN),
          msg(4, MENUITEM[1]), msg(7, MENUITEM[1]), msg(9, MENUITEM[1]),
          msg(4, MENUITEM[2]), msg(6, MENUITEM[2]), msg(9, MENUITEM[2]),
          msg(4, MENUITEM[3]), msg(7, MENUITEM[3]), "rdump",
          msg(12, SCREEN), "rdump"]
    # The first highlight on the third row places the mask at 2.
    s += [msg(11, SCREEN), msg(4, MENUITEM[3]), "rdump", msg(8, MENUITEM[3]),
          msg(4, MENUITEM[2]), "rdump", msg(12, SCREEN)]
    # The pad and the menu out of step: only the first highlight places the
    # mask, and the SelectionSet and brackets follow the mask.
    s += [msg(11, SCREEN), msg(4, MENUITEM[1]), msg(9, MENUITEM[1]),
          msg(9, MENUITEM[1]), msg(4, MENUITEM[2]), "rdump",
          msg(12, SCREEN)]
    # Toggles over values that are not 0 or 1.
    s += [msg(11, SCREEN), "rpoke|2|2", msg(4, MENUITEM[1]),
          msg(7, MENUITEM[1]), "rdump", "rpoke|4|-3", msg(9, MENUITEM[1]),
          msg(9, MENUITEM[2]), msg(4, MENUITEM[3]), msg(6, MENUITEM[3]),
          "rdump", msg(12, SCREEN), "rdump"]
    # An item moved behind the list's back: above the top, but its
    # destination is the top already, so the delta is 0 and nothing seeks.
    s += [msg(11, SCREEN),
          obj(MENUITEM[1], 1, (153, 20, 330, 42), 31, 153.0, 20.0),
          msg(4, MENUITEM[1]), "rdump", TICK, "rdump", msg(12, SCREEN)]
    s += screen_objects()

    # Rows off the visible area: the third far below MENUITEM_7, so the
    # list seeks up; then the first above MENUITEM_1, and it seeks down.
    ys = list(YS)
    ys[3] = 400.0
    s += screen_objects(ys)
    s += ["btc|2|0|1|0|1", "fin|1", msg(11, SCREEN), "rdump",
          msg(4, MENUITEM[1]), msg(9, MENUITEM[1]), msg(4, MENUITEM[2]),
          msg(9, MENUITEM[2]), msg(4, MENUITEM[3]), "rdump", TICK, "rdump",
          TICK, "rdump", msg(4, MENUITEM[3]), "rdump"]
    # UNACTIVATE there, moved: each object goes back to its SavedY.
    s += [msg(12, SCREEN), "rdump", msg(11, SCREEN), msg(4, MENUITEM[1]),
          msg(9, MENUITEM[1]), msg(4, MENUITEM[2]), msg(9, MENUITEM[2]),
          msg(4, MENUITEM[3]), TICK, "rdump"]
    s += [obj(MENUITEM[1], 1, (153, 20, 330, 42), 31, 153.0, 20.0),
          msg(8, MENUITEM[3]), msg(4, MENUITEM[2]), msg(8, MENUITEM[2]),
          msg(4, MENUITEM[1]), "rdump", TICK, "rdump", msg(12, SCREEN),
          "rdump"]
    s += screen_objects()

    # Another screen's hash in the ACTIVATE, and an ACTIVATE over a live
    # one: retail leaks the first, and both start the same.
    s += [msg(11, 0x0badf00d), msg(4, MENUITEM[1]), TICK, "rdump",
          msg(11, SCREEN), "rdump", msg(12, SCREEN), "rdump"]
    # No arrows, and a row's item and text not on the screen.
    s += [obj(LEFT_ARROW, 0), obj(RIGHT_ARROW, 0), obj(MENUITEM[2], 0),
          obj(TEXT[3], 0), obj(UP_ARROW, 0), obj(MI_UNDERSCORE, 0),
          msg(11, SCREEN), "rdump", msg(4, MENUITEM[1]), TICK,
          msg(7, MENUITEM[1]), "rdump", msg(1, MENUITEM[1]), "rdump",
          msg(12, SCREEN), "rdump"]
    return s


# =================================================================== model

class Model(sc.Model):
    def __init__(self):
        sc.Model.__init__(self)
        e = self.e
        self.fin = 0
        e.put32(PINSTANCE, 0)
        for i in range(5):
            e.put32(FRED + 64 + 4 * i, 0)
        e.call(F_SCROLL_INIT)
        for a, fn in (
                (K_HL_FORCE, self.hl_force), (K_SLIDE_FIN, self.slide_fin),
                (S_SEEK, self.seek), (S_GETY, self.gety),
                (S_CHUNK_TL, self.chunk_tl), (S_CHUNK_SETY, self.chunk_sety),
                (S_CHUNK_CLIP, self.chunk_clip), (S_CLIP, self.clip),
                (S_SETALPHA, self.setalpha), (S_GRAYN, self.grayn)):
            e.stub(a, fn)

    # ---- bWare

    def malloc(self, em):
        size = s32(em.reg[4])
        a = self.e.alloc(size)
        self.e.write(a, bytes(size))
        if size == 784:
            self.inst = a
        elif size == 28:
            self.exit = a
        elif size not in (44, 64):
            self.emit("  malloc %d" % size)
        return a

    # ---- the kit

    def slide_name(self, a):
        if self.inst and a == self.inst + 164:
            return "slidein"
        if a and a == self.exit:
            return "exit"
        return "?%08x" % a

    def hl_name(self, a):
        if self.inst and a == self.inst + 184:
            return "hl1"
        if self.inst and a == self.inst + 216:
            return "hl2"
        return "?"

    def hl_force(self, em):
        self.emit("  kit hl force %s" % self.hl_name(em.reg[4] & M32))
        return 0

    def slide_fin(self, em):
        self.emit("  kit slide finished %s"
                  % self.slide_name(em.reg[4] & M32))
        return self.fin

    def seek(self, em):
        a = em.reg[4] & M32
        g = self.e.u32
        st = struct.unpack("<h", struct.pack("<H", g(a + 44) & 0xffff))[0]
        self.emit("  seek %08x %08x %d %08x %08x %08x" % (
            g(a), g(a + 8), st, em.fpr[12] & M32, em.fpr[13] & M32,
            em.fpr[14] & M32))
        self.e.put32(a, g(a + 8))
        self.e.write(a + 44, b"\0\0")
        return 0

    # ---- the Flailer

    def chunk(self, h):
        a = sc.Model.chunk(self, h)
        self.e.put32(a + 8, h)
        return a

    def ybits(self, h):
        o = self.find(h)
        return o.get("y", 0) if o else 0

    def gety(self, em):
        r = em.reg
        self.emit("  gety %08x %08x" % (r[4] & M32, r[5] & M32))
        em.fpr[0] = self.ybits(r[5] & M32)
        return 0

    def chunk_tl(self, em):
        r = em.reg
        screen, h = self.chunk_name(r[4] & M32)
        self.emit("  gety %08x %08x" % (screen, h))
        o = self.find(h)
        self.e.put32(r[5] & M32, o["x"] if o else 0)
        self.e.put32(r[6] & M32, self.ybits(h))
        return 0

    def chunk_sety(self, em):
        screen, h = self.chunk_name(em.reg[4] & M32)
        y = em.fpr[12] & M32
        self.emit("  sety %08x %08x %08x" % (screen, h, y))
        o = self.find(h)
        if o:
            o["y"] = y
        return 0

    def chunk_clip(self, em):
        r = em.reg
        screen, h = self.chunk_name(r[4] & M32)
        self.emit("  clip %08x %08x %08x" % (screen, h, r[5] & M32))
        return 0

    def clip(self, em):
        r = em.reg
        self.emit("  clip %08x %08x %08x" % (r[4] & M32, r[5] & M32,
                                             r[6] & M32))
        return 0

    def setalpha(self, em):
        r = em.reg
        self.emit("  setalpha %08x %08x %d" % (r[4] & M32, r[5] & M32,
                                               s32(r[6])))
        return 0

    def grayn(self, em):
        r = em.reg                      # (name, item, screen, mode)
        self.emit("  grayn %s %08x %08x %d" % (
            self.cstr(r[4] & M32), r[6] & M32, r[5] & M32, s32(r[7])))
        return 0

    # ---- ops

    def body(self, b, data):
        """The rows (each value by its place in `data`), the arrows, the
        scroller and each of its elements."""
        g = self.e.u32
        head = b + 4
        n = g(head)
        while n != head:
            v = g(n + 20)
            self.emit("  row %08x %08x %d v%d=%d %d" % (
                g(n + 8), g(n + 12), s32(g(n + 16)),
                s32(v - data) // 4, s32(g(v)), s32(g(n + 40))))
            n = g(n)
        a = b + 308
        self.emit("  arrows %d %d %08x wave %08x %08x %08x %08x" % (
            1 if g(a + 4) else 0, 1 if g(a + 8) else 0, g(a + 12),
            g(a + 16), g(a + 20), g(a + 24), g(a + 28)))
        sl = b + 252
        self.emit("  scroll mask %d top %08x bottom %08x n %d wave %08x "
                  "%08x %08x %08x arrows %08x %08x clip %08x" % (
                      s32(g(sl + 20)), g(sl + 12), g(sl + 16),
                      s32(g(sl + 52)), g(sl + 24), g(sl + 28),
                      g(sl + 32), g(sl + 36), g(sl + 40), g(sl + 44),
                      g(sl + 48)))
        head = sl + 4
        n = g(head)
        while n != head:
            st = struct.unpack("<h", struct.pack(
                "<H", g(n + 56) & 0xffff))[0]
            self.emit("  el %08x saved %08x val %08x des %08x st %d" % (
                self.chunk_name(g(n + 60))[1], g(n + 8), g(n + 12),
                g(n + 20), st))
            n = g(n)

    def rdump(self):
        g = self.e.u32
        b = g(PINSTANCE)
        if not b:
            self.emit("  inst 0")
        else:
            data = b + 764
            self.emit("  inst 1 cur %08x btc %d %d %d %d %d exit %d" % (
                (g(b + 12),) + tuple(s32(g(data + 4 * i)) for i in range(5))
                + (1 if g(b + 248) else 0,)))
            self.body(b, data)
        self.emit("  fred btc %d %d %d %d %d cars %d" % (
            tuple(s32(g(FRED + 64 + 4 * i)) for i in range(5))
            + (s32(g(FRED + 0x10734)),)))

    def op(self, a):
        e = self.e
        o = a[0]
        n = [int(x, 0) for x in a[1:]]
        if o == "obj":
            sc.Model.op(self, a[:9])
            self.objs[n[0] & M32]["y"] = (n[8] & M32) if len(n) > 8 else 0
        elif o == "btc":
            for i, v in enumerate(n[:5]):
                e.put32(FRED + 64 + 4 * i, v & M32)
        elif o == "fin":
            self.fin = n[0]
        elif o == "fdef":
            # FrontendDatabase::InitWithDefaults' two setup blocks.
            e.call(F_DCS_DEFAULTS, FRED + 8)
            e.call(F_BTC_DEFAULTS, FRED + 64)
        elif o == "rpoke":
            e.put32(e.u32(PINSTANCE) + 764 + 4 * (n[0] % 5), n[1] & M32)
        elif o == "rmsg":
            d = self.data
            e.put32(d, n[1] & M32)
            e.put32(d + 4, n[2] & M32)
            e.put32(d + 8, 0x5a)
            e.put32(d + 12, 0x5b)
            e.call(F_CALLBACK, n[0], d, limit=4000000)
            self.emit("  data %d %d" % (s32(e.u32(d + 8)),
                                        s32(e.u32(d + 12))))
        elif o == "rdump":
            self.rdump()
        else:
            sc.Model.op(self, a)


def model(lines):
    return Model().run(lines)


# ============================================================= mutations

S = sc.BSETUP
H = "3DS Files/source/bsetup.h"
MUTATIONS = [
    # Fred's block.
    ("btc-default-grid", S, "    d->opponentGrid = 2;",
     "    d->opponentGrid = 1;"),
    ("btc-default-catchup", S, "    d->catchup      = 1;",
     "    d->catchup      = 0;"),
    ("btc-default-damage", S, "    d->damage       = 1;",
     "    d->damage       = 0;"),
    ("btc-load-traffic", S, "    d->traffic      = get32(p + 12);",
     "    d->traffic      = get32(p + 8);"),
    ("btc-save-damage", S, "    put32(p + 16, d->damage);", "    (void)0;"),
    ("btc-offset", H, "#define FRED_BE_THE_COP_SETUP   64",
     "#define FRED_BE_THE_COP_SETUP   68"),

    # The scroller.
    ("el-saved", S, "    el->savedY                 = topLeftY(s, l->screen, "
     "object);", "    el->savedY                 = 0.0f;"),
    ("el-des", S, "    el->yAnim.valDesired       = el->savedY;",
     "    el->yAnim.valDesired       = 0.0f;"),
    ("el-val", S, "    el->yAnim.val              = el->yAnim.valDesired;",
     "    el->yAnim.val              = 0.0f;"),
    ("el-state", S, "    el->yAnim.state            = 0;",
     "    el->yAnim.state            = 2;"),
    ("scroll-wave", S, "bsine_init(&l->arrowAnimator, 0.0f, 128.0f, 10.0f);",
     "bsine_init(&l->arrowAnimator, 0.0f, 128.0f, 5.0f);"),
    ("scroll-top", S, "    l->top         = topLeftY(s, screen, first);",
     "    l->top         = topLeftY(s, screen, last);"),
    ("scroll-mask0", S, "    l->currentMask = -1;", "    l->currentMask = 0;"),
    ("scroll-init-alpha", S, "    HOOK(s, setAlpha, screen, down, "
     "bsine_val_int(&l->arrowAnimator));", "    (void)0;"),
    ("add-unfound", S, "    if (!findObject(s, l->screen, object, 0)) return;",
     "    (void)0;"),
    ("add-no-clip", S, "    HOOK(s, setClipToPoly, l->screen, object, "
     "l->clipPoly);", "    (void)0;"),
    ("release-order", S, "    for (int i = 0; i < l->numElements; i++) {"
     + NL + "        BMenuAnimElement* el = &l->elements[i];" + NL
     + "        HOOK(s, setObjectTopLeftY, l->screen, el->object, "
     "el->savedY);", "    for (int i = l->numElements - 1; i >= 0; i--) {"
     + NL + "        BMenuAnimElement* el = &l->elements[i];" + NL
     + "        HOOK(s, setObjectTopLeftY, l->screen, el->object, "
     "el->savedY);"),
    ("release-val", S, "HOOK(s, setObjectTopLeftY, l->screen, el->object, "
     "el->savedY);", "HOOK(s, setObjectTopLeftY, l->screen, el->object, "
     "el->yAnim.val);"),
    ("delta-state", S, "if (el->yAnim.valDesired != el->yAnim.val) "
     "el->yAnim.state = 2;", "el->yAnim.state = 2;"),
    ("delta-sign", S, "    d = y - el->yAnim.valDesired;",
     "    d = el->yAnim.valDesired - y;"),
    ("desired-first-only", S, "    for (int i = 0; i < l->numElements; i++)"
     + NL + "        elementApplyDeltaY(&l->elements[i], d);",
     "    elementApplyDeltaY(el, d);"),
    ("current-le", S, "    if (y < l->top) scrollSetDesiredTopLeftY",
     "    if (y <= l->top) scrollSetDesiredTopLeftY"),
    ("current-bottom", S, "else if (l->bottom < y) scrollSetDesiredTopLeftY"
     "(s, l, object, l->bottom);", "else if (l->bottom < y) "
     "scrollSetDesiredTopLeftY(s, l, object, l->top);"),
    ("tick-no-sety", S, "        HOOK(s, setObjectTopLeftY, l->screen, "
     "el->object, el->yAnim.val);", "        (void)0;"),
    ("tick-down-alpha", S, "    HOOK(s, setAlpha, l->screen, l->downArrow,"
     + NL + "         bsine_val_int(&l->arrowAnimator));", "    (void)0;"),
    ("hl-always", S, "    if (l->currentMask != -1) return;", "    (void)0;"),
    ("hl-2", S, "        case BSCR_ITEM_MENUITEM(2): l->currentMask = 1;",
     "        case BSCR_ITEM_MENUITEM(2): l->currentMask = 2;"),
    ("hl-3", S, "        case BSCR_ITEM_MENUITEM(3): l->currentMask = 2;",
     "        case BSCR_ITEM_MENUITEM(3): l->currentMask = 1;"),
    ("mask-off", S, "return (uint32_t)l->currentMask < 7 ? "
     "kScrollMasks[l->currentMask] : 0;", "return (uint32_t)l->currentMask < 7 "
     "? kScrollMasks[l->currentMask] : kScrollMasks[0];"),
    ("down-min", S, "int32_t n = l->numMenuItemsToScroll < 7 ? "
     "l->numMenuItemsToScroll : 7;", "int32_t n = 7;"),
    ("down-clamp", S, "    if (!(l->currentMask < n)) l->currentMask = n - 1;",
     "    if (!(l->currentMask < n)) l->currentMask = n;"),
    ("up-clamp", S, "    if (l->currentMask < 0) l->currentMask = 0;",
     "    (void)0;"),
    ("show-up", S, "    if (l->numMenuItemsToScroll < 8) return 0;" + NL
     + "    for (int i = 0; i < l->numElements; i++)" + NL
     + "        if (l->elements[i].yAnim.valDesired < l->top) return 1;",
     "    for (int i = 0; i < l->numElements; i++)" + NL
     + "        if (l->elements[i].yAnim.valDesired < l->top) return 1;"),
    ("ev-up-down", S, "        case BMSG_MENUITEM_PAD_UP: scrollMoveMaskUp(l); "
     "break;", "        case BMSG_MENUITEM_PAD_UP: scrollMoveMaskDown(l); "
     "break;"),
    ("ev-hl-no-current", S, "            scrollSetCurrentObject(s, l, "
     "data->itemHash);", "            (void)0;"),
    ("ev-no-vis", S, "            HOOK(s, setVisible, l->screen, l->upArrow, "
     "scrollShowUpArrow(l));", "            (void)0;"),

    # The rows.
    ("offon", S, "{30008, 30009};", "{30009, 30008};"),
    ("traffic-table", S, "{30018, 30019, 30020, 30008};",
     "{30018, 30019, 30020, 30009};"),
    ("traffic-range", S, "*value = valueChanger(old, dir, 0, 3);",
     "*value = valueChanger(old, dir, 0, 2);"),
    ("traffic-changed", S, "    return *value != old;" + NL + "}" + NL + NL
     + "// RefreshCatchup", "    return 1;" + NL + "}" + NL + NL
     + "// RefreshCatchup"),
    ("catchup-flip", S, "static int maybeChangeCatchup(BSetup* s, BRaceSetup* "
     "r, int32_t dir," + NL + "                              int32_t* value)"
     + NL + "{" + NL + "    (void)s;" + NL + "    (void)r;" + NL
     + "    (void)dir;" + NL + "    *value = *value == 0;",
     "static int maybeChangeCatchup(BSetup* s, BRaceSetup* r, int32_t dir,"
     + NL + "                              int32_t* value)" + NL + "{" + NL
     + "    (void)s;" + NL + "    (void)r;" + NL + "    (void)dir;" + NL
     + "    *value = 1 - *value;"),
    ("damage-no-change", S, "static int maybeChangeDamage(BSetup* s, "
     "BRaceSetup* r, int32_t dir," + NL + "                             "
     "int32_t* value)" + NL + "{" + NL + "    (void)s;" + NL + "    (void)r;"
     + NL + "    (void)dir;" + NL + "    *value = *value == 0;" + NL
     + "    return 1;", "static int maybeChangeDamage(BSetup* s, BRaceSetup* "
     "r, int32_t dir," + NL + "                             int32_t* value)"
     + NL + "{" + NL + "    (void)s;" + NL + "    (void)r;" + NL
     + "    (void)dir;" + NL + "    *value = *value == 0;" + NL
     + "    return 0;"),
    ("attach-order", S, "    raceSetupAttach(r, 30005, 30502, "
     "maybeChangeCatchup, refreshCatchup," + NL + "                    "
     "&r->btc.catchup);" + NL + "    raceSetupAttach(r, 30006, 30503, "
     "maybeChangeTraffic, refreshTraffic," + NL + "                    "
     "&r->btc.traffic);", "    raceSetupAttach(r, 30006, 30503, "
     "maybeChangeTraffic, refreshTraffic," + NL + "                    "
     "&r->btc.traffic);" + NL + "    raceSetupAttach(r, 30005, 30502, "
     "maybeChangeCatchup, refreshCatchup," + NL + "                    "
     "&r->btc.catchup);"),
    ("attach-blurb", S, "raceSetupAttach(r, 30101, 30504,",
     "raceSetupAttach(r, 30101, 30503,"),
    ("attach-value", S, "&r->btc.damage);", "&r->btc.catchup);"),
    ("row-index-default", S, "        if (kRowItems[i] == item) return i;"
     + NL + "    return 0;", "        if (kRowItems[i] == item) return i;"
     + NL + "    return 1;"),

    # BuildMenu.
    ("build-mode", S, "    bsel_set_indicator_mode(&r->sel, 1);" + NL
     + "    bsel_add_items(a, &r->sel, kRowMasks, BRACESETUP_MAX_ROWS);",
     "    bsel_set_indicator_mode(&r->sel, 0);" + NL
     + "    bsel_add_items(a, &r->sel, kRowMasks, BRACESETUP_MAX_ROWS);"),
    ("build-items-n", S, "bsel_add_items(a, &r->sel, kRowMasks, "
     "BRACESETUP_MAX_ROWS);", "bsel_add_items(a, &r->sel, kRowMasks, "
     "r->numRows);"),
    ("build-gray-mode", S, "HOOK(s, grayMenuItemNamed, name, r->screen, "
     "c->menuItem, 1);", "HOOK(s, grayMenuItemNamed, name, r->screen, "
     "c->menuItem, 0);"),
    ("build-rest-mode", S, "HOOK(s, grayMenuItemNamed, name, r->screen, "
     "kRowItems[i], 2);", "HOOK(s, grayMenuItemNamed, name, r->screen, "
     "kRowItems[i], 0);"),
    ("build-rest-text", S, "        HOOK(s, setVisible, r->screen, "
     "kRowTexts[i], 0);", "        (void)0;"),
    ("build-text-vis-1", S, "        HOOK(s, setVisible, r->screen, "
     "c->changeText, 1);" + NL + "        HOOK(s, grayMenuItemNamed",
     "        HOOK(s, grayMenuItemNamed"),
    ("build-text-vis-2", S, "c->languageID);" + NL + "        HOOK(s, "
     "setVisible, r->screen, c->changeText, 1);", "c->languageID);"),
    ("build-text-item", S, "        HOOK(s, setVisible, r->screen, "
     "c->changeText, 1);" + NL + "        HOOK(s, grayMenuItemNamed",
     "        HOOK(s, setVisible, r->screen, c->menuItem, 1);" + NL
     + "        HOOK(s, grayMenuItemNamed"),
    ("build-add-order", S, "    scrollAddObjects(s, &r->scroller, kRowTexts, "
     "r->numRows);" + NL + "    scrollAddObjects(s, &r->scroller, kRowItems, "
     "r->numRows);", "    scrollAddObjects(s, &r->scroller, kRowItems, "
     "r->numRows);" + NL + "    scrollAddObjects(s, &r->scroller, kRowTexts, "
     "r->numRows);"),
    ("build-name", S, 'raceSetupBuildMenu(s, r, "Be The Cop Setup");',
     'raceSetupBuildMenu(s, r, "Be The Cop");'),
    ("text-hash", S, "0x69a2c757u, 0x69a2c758u, 0x69a2c759u,",
     "0x69a2c757u, 0x69a2c759u, 0x69a2c758u,"),

    # The constructor and destructor.
    ("ctor-scroll-last", S, "scrollInit(s, &r->scroller, screen, "
     "BSCR_ITEM_MENUITEM(1)," + NL + "               BSCR_ITEM_MENUITEM(7),",
     "scrollInit(s, &r->scroller, screen, BSCR_ITEM_MENUITEM(1)," + NL
     + "               BSCR_ITEM_MENUITEM(8),"),
    ("ctor-no-clip", S, "    HOOK(s, setClipToPoly, screen, "
     "BSETUP_OBJ_RIGHT_ARROW," + NL + "         BSETUP_OBJ_CLIP_POLY);",
     "    (void)0;"),
    ("ctor-no-resync", S, "\"Be The Cop Setup\");" + NL
     + "    raceSetupResync(s, r);", "\"Be The Cop Setup\");"),
    ("ctor-no-load", S, "if (s->gf->fred) btcLoad(&r->btc, s->gf->fred);",
     "if (0) btcLoad(&r->btc, s->gf->fred);"),
    ("dtor-no-save", S, "    if (s->gf->fred) btcSave(&r->btc, s->gf->fred);",
     "    (void)0;"),
    ("dtor-order", S, "    HOOK0(s, setupRaceParametersAfterRaceSetup);" + NL
     + "    HOOK0(s, makeChallengeCarsAvailable);" + NL
     + "    raceSetupDtor(s, r);", "    HOOK0(s, makeChallengeCarsAvailable);"
     + NL + "    HOOK0(s, setupRaceParametersAfterRaceSetup);" + NL
     + "    raceSetupDtor(s, r);"),
    ("dtor-no-help", S, "    HOOK(s, setHelpOverride, NULL);" + NL
     + "    if (r->exitActive)", "    if (r->exitActive)"),
    ("dtor-no-scroll", S, "    scrollRelease(s, &r->scroller);" + NL,
     ""),

    # HandleMenuEvent.
    ("ev-tick-hl", S, "    if (msg == BMSG_SCREEN_TICK) {" + NL
     + "        banim_highlight_animate(a, &r->highlight);",
     "    if (0) {" + NL + "        banim_highlight_animate(a, &r->highlight);"),
    ("ev-arrows-after-exit", S, "    barrows_event(s, &r->arrows, msg);" + NL
     + "    if (r->exitActive) {", "    if (r->exitActive) {"),
    ("ev-scroll-after", S, "    if (!data) return;" + NL
     + "    scrollEvent(s, &r->scroller, msg, data);" + NL,
     "    if (!data) return;" + NL),
    ("sel-2p", S, "fredGet(s, FRED_NUM_PLAYER_CARS) == 2 ? \"Select Car2P\"",
     "fredGet(s, FRED_NUM_PLAYER_CARS) >= 2 ? \"Select Car2P\""),
    ("sel-no-arrows", S, "                                  "
     "r->exit.slide.totalTime);" + NL + "            barrows_set(s, "
     "&r->arrows, 0);", "                                  "
     "r->exit.slide.totalTime);"),
    ("hl-no-blurb", S, "            if (c) banim_blurb_new_text_id(a, "
     "&r->blurb, c->blurbID);", "            (void)0;"),
    ("hl-no-current", S, "            r->current = data->itemHash;",
     "            (void)0;"),
    ("hl-arrows-item", S, "            barrows_set(s, &r->arrows, "
     "kRowTexts[idx]);", "            barrows_set(s, &r->arrows, "
     "kRowItems[idx]);"),
    ("hl-box-item", S, "            raceSetupHighlightBox(s, r, "
     "scrollCurrentMask(&r->scroller));", "            "
     "raceSetupHighlightBox(s, r, kRowMasks[idx]);"),
    ("hl-hl2-item", S, "            banim_highlight_set_item(a, &r->change, "
     "kRowTexts[idx]);", "            banim_highlight_set_item(a, &r->change, "
     "kRowItems[idx]);"),
    ("box-under", S, "    HOOK(s, setTopLeftY, r->screen, "
     "BSCR_OBJ_MI_UNDERSCORE," + NL + "         (int32_t)((float)box[3] + "
     "-3.0f));" + NL + "    HOOK(s, setTopLeftY, r->screen, "
     "BSCR_OBJ_MI_OVERSCORE," + NL + "         (int32_t)((float)box[1] - "
     "6.0f));" + NL + "}" + NL + NL + "// The constructor (0x001b8390)",
     "    HOOK(s, setTopLeftY, r->screen, BSCR_OBJ_MI_UNDERSCORE," + NL
     + "         (int32_t)((float)box[3] + -2.0f));" + NL
     + "    HOOK(s, setTopLeftY, r->screen, BSCR_OBJ_MI_OVERSCORE," + NL
     + "         (int32_t)((float)box[1] - 6.0f));" + NL + "}" + NL + NL
     + "// The constructor (0x001b8390)"),
    ("lr-dir", S, "int32_t dir = msg == BMSG_MENUITEM_PAD_LEFT ? -1 : 1;"
     + NL + "            c           = findRow",
     "int32_t dir = msg == BMSG_MENUITEM_PAD_LEFT ? 1 : -1;" + NL
     + "            c           = findRow"),
    ("lr-silent-kept", S, "            if (!c->change(s, r, dir, c->value)) {"
     + NL + "                data->noise = 0;",
     "            if (!c->change(s, r, dir, c->value)) {" + NL
     + "                (void)0;"),
    ("lr-noise", S, "            data->noise = msg == BMSG_MENUITEM_PAD_LEFT ? "
     "BSND_MENU_LEFT", "            data->noise = msg == "
     "BMSG_MENUITEM_PAD_RIGHT ? BSND_MENU_LEFT"),
    ("lr-no-force", S, "            banim_highlight_force_start(a, "
     "&r->change);", "            (void)0;"),
    ("up-any", S, "            if (data->itemHash == BSCR_ITEM_MENUITEM(1)) "
     "data->param = 1;", "            data->param = 1;"),
    ("down-last", S, "if (!(rowIndex(data->itemHash) < r->numRows - 1)) "
     "data->param = 1;", "if (!(rowIndex(data->itemHash) < r->numRows)) "
     "data->param = 1;"),
    ("tick-slide-always", S, "            if (!banim_slide_finished("
     "&r->slideIn))" + NL + "                banim_slide_animate(a, "
     "&r->slideIn);", "            banim_slide_animate(a, &r->slideIn);"),
    ("tick-no-blurb", S, "        case BMSG_SCREEN_TICK:" + NL
     + "            banim_blurb_animate(a, &r->blurb);", "        case "
     "BMSG_SCREEN_TICK:"),
    ("cb-screen", S, "screen = data ? data->itemHash : "
     "BSETUP_SCREEN_RACE_SETUP;", "screen = BSETUP_SCREEN_RACE_SETUP;"),
    ("cb-unactivate-twice", S, "            if (!s->race.live) break;",
     "            (void)0;"),
    ("cb-dtor-default", S, "                default: btcDtor(s); break;",
     "                default: break;"),
]

EQUIVALENT = {
    "mask-off": "the mask is -1 at GetCurrentMenuMask only after a "
                "HIGHLIGHT on an item Highlight's switch lacks, and every "
                "row's item is in it: an item with no row, where retail "
                "reads BlurbID through a null pointer",
    "row-index-default": "the default is read by HIGHLIGHT, on an item with "
                         "no row (the same null read), and by PAD_DOWN, "
                         "where with three rows 0 and 1 both answer 'not "
                         "the last'",
    "traffic-changed": "Traffic's step is 1 or -1, and ValueChanger moves "
                       "any value by one of those or wraps it to the other "
                       "end, so it always changes",
    "lr-silent-kept": "no row's Change answers 0: Catch-up's and Damage's "
                      "always answer 1, and Traffic's always changes",
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
        exe = sc.build_harness(tmp)
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
                    exe = sc.build_harness(tmp)
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
        exe = sc.build_harness(tmp, name="racesetup_test")
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
