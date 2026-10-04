#!/usr/bin/env python3
"""Cross-check 3DS Files/source/hudnis.c, the rest of NISOverlayManager,
against the retail image, SLES_507.31.

**The model** is retail's own: NISOverlayManager's Start (0x00182488),
Update (0x001825f0), UpdateDateAndTime (0x00182748), SetVisible
(0x00182a48), StartArrest (0x001832f8), StartTicket (0x00183308) and
StartBusted (0x00228f10); and under them cPoint's SplineSeek (0x001daec8),
FlailerPrintf with bSPrintf, and the rest of the Flailer runtime on
INGAMEB's Flailer chunk. The harness (tools/src/hudnis_test.c) runs
hudnis.c over banim.c, flailer.c and bprintf.c on the same bundle.

**The stubs** are flailer_check.py's renderer answers, and the callees
the overlay does not own, scripted the same on both sides and logged:
sceCdReadClock (the eight bytes it writes and its answer),
sceScfGetLocalTimefromRTC (the bytes it is handed, and what it writes, if
anything), GetTranslatedString (the id and the answer),
RaceCoordinator::IsReplayDemoMode (whether it is asked of the coordinator,
and the answer) and SetFlailerScreenVisibility (the screen and the value).

**Compared** are the stubs' logs and, after each op, every line that
changed: the overlay's fields, both tracks' 48 bytes and every Flailer
object's bytes.

**The script** starts the overlay on each of its three screens and on one
without its objects, and runs it frame by frame as the tracks arrive; reads
every month and odd BCD in every field, a clock that fails or is busy, a
local time that overwrites it, and both languages; runs the date's
31-frame wait on each side and across the wrap; blinks the REC light on
each bit; and shows the overlay in every state, every race-coordinator
state and the replay demo, for the cop and not, one player and two.

    python tools/hudnis_check.py
    python tools/hudnis_check.py --mutate [--only a,b]
    python tools/hudnis_check.py --dump out/hudnis
"""
import argparse
import os
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flailer_check as fc              # noqa: E402
import hostbuild                        # noqa: E402
import physicscar_check as pcc          # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/hudnis_test.c"
HUDNIS = "3DS Files/source/hudnis.c"
SOURCES = [HARNESS, HUDNIS, "3DS Files/source/banim.c",
           "3DS Files/source/bmath.c", "3DS Files/source/bmathtab.c",
           "3DS Files/source/flailer.c", "3DS Files/source/bprintf.c",
           "3DS Files/source/bui.c", "3DS Files/source/bchunk.c"]

GP = fc.GP
RP = 0x0031a898                         # TheRaceParameters
RP_PLAYERS = 48                         # NumPlayerCars
RP_COP = 628                            # BeACop
RP_SIZE = 788
LANGUAGE = 0x0031c1c8                   # CurrLanguage
G_ELAPSED = GP - 19560                  # WorldTimeElapsed
G_WFRAMES = GP - 19564                  # WorldTimeFrames
G_RFRAMES = GP - 19600                  # RealTimeFrames
G_RC = GP - 22216                       # pRaceCoordinator

F_START = 0x00182488
F_UPDATE = 0x001825f0
F_DATE = 0x00182748
F_VISIBLE = 0x00182a48
F_ARREST = 0x001832f8
F_TICKET = 0x00183308
F_BUSTED = 0x00228f10
S_CLOCK = 0x0028dc48                    # sceCdReadClock
S_LOCAL = 0x002961d8                    # sceScfGetLocalTimefromRTC
S_XL = 0x0021e560                       # GetTranslatedString
S_DEMO = 0x001369a8                     # RaceCoordinator::IsReplayDemoMode
S_SCREEN = 0x0014cbf8                   # SetFlailerScreenVisibility

OVL_SIZE = 56
TRACK_SIZE = 48

SCREEN = 0x3ea89b7c                     # one player, and Be A Cop
TOP = 0xd4d25ee7                        # two players, the top half
BOTTOM = 0xc17316c9                     # and the bottom
HUD = 0xf1f1f8e5                        # a screen without the overlay's

BUSTED = "t:0x76494c5b"
POINTS = "t:0x233dfbe1"
DATE = "t:0x001450dd"
REC = "b:0x61cb41df"

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def F(v):
    return "%#x" % struct.unpack("<I", struct.pack("<f", v))[0]


def pattern(o):
    """The word a fresh block holds at offset o, as the harness's."""
    return 0x3f800000 + o * 16


# ================================================================== script

def clock(sec=0x45, mn=0x59, hr=0x23, day=0x31, mon=0x12, yr=0x04, stat=0,
          ret=1, pad=0):
    return "clock|%d|%#x|%#x|%#x|%#x|%#x|%#x|%#x|%#x" % (
        ret, stat, sec, mn, hr, pad, day, mon, yr)


def local(sec, mn, hr, day, mon, yr, stat=0, pad=0):
    return "local|%#x|%#x|%#x|%#x|%#x|%#x|%#x|%#x" % (
        stat, sec, mn, hr, pad, day, mon, yr)


def common():
    s = ["load|%s" % (fc.SD / "GLOBAL/INGAMEB.BUN")]
    # Every month but May and October has a name; those two show the
    # stub's default.
    s += ["xl|%#x|%s" % (0xe86c + i, m) for i, m in enumerate(MONTHS)
          if m not in ("May", "October")]
    s += ["g|elapsed|%s" % F(1.0 / 60), "g|rframes|1000", "g|wframes|0",
          "g|lang|0", "rp|BeACop|0", "rp|Players|1", "rc|3|0", clock(),
          "local|-"]
    # The tracks idle, as the constructor leaves them; the rest of their
    # words stay the pattern.
    s += ["t|0|44|0", "t|1|44|0"]
    return s


def s_no_screen():
    # Screen 0: Start and SetVisible return at once, Update still seeks
    # and sets, and the date still reads the clock.
    s = ["start", "arrest", "ticket", "busted", "update|1", "update|0",
         "visible|1", "visible|0", "o|last|0", "update|1", "date"]
    return s


def frames(n, playing=1, first=0, step=1):
    s = []
    for i in range(n):
        s += ["g|wframes|%d" % (first + i * step), "update|%d" % playing]
    return s


def s_start():
    s = ["o|screen|%#x" % SCREEN, "g|rframes|2000", "start"]
    # The tracks arrive over a quarter of a second, a frame at a time.
    s += frames(20)
    # Not playing: the REC light and the frame go.
    s += ["update|0", "update|1"]
    # The REC light blinks on bit 3 of the world frame.
    for w in (7, 8, 9, 15, 16, 23, 24, -8, -9, 0x7ffffff8, -1):
        s += ["g|wframes|%d" % w, "update|1"]
    # The date waits 31 real frames from the last.
    s += ["g|rframes|2030", "update|1", "g|rframes|2031", "update|1",
          "g|rframes|2061", "update|1", "g|rframes|2062", "update|1",
          "g|rframes|2000", "update|1"]
    # Across the wrap, and the far side of it.
    for last, now in ((0x7ffffff0, 0x7fffffff), (0x7ffffff0, -0x80000000),
                      (0x7ffffff0, -0x7ffffff3), (0xffffffff, 29),
                      (0xffffffff, 30), (1, -0x80000000),
                      (0x80000000, 0x7fffffff), (0x80000000, 30)):
        s += ["o|last|%#x" % last, "g|rframes|%d" % now, "update|1"]
    s += ["g|rframes|3000", "date"]
    # Start zeroes the last date before it reads the clock, so a clock that
    # fails or is busy leaves it 0.
    for kw in ({"ret": 0}, {"stat": 1}):
        s += ["o|last|0x1234", clock(**kw), "start", "g|rframes|3010",
              "update|1"]
    s += [clock()]
    # A step of 0, a negative one, a long one and a huge one.
    for e in (0.0, -0.1, 0.1, 1.0, 1e6, 1.0 / 60):
        s += ["g|elapsed|%s" % F(e), "update|1"]
    return s


def s_tracks():
    s = []
    # An alpha that is not a whole number, and past the ends.
    for v in (127.9, 0.99, 64.5, -0.5, -3.5, 300.0, 1e10, -1e10,
              float("nan"), float("inf"), 128.0):
        s += ["t|1|0|%s" % F(v), "t|1|44|0", "update|1"]
    # A scale mid-way.
    for v in (5.0, 3.25, 2.0, 0.5, 0.0, -1.0):
        s += ["t|0|0|%s" % F(v), "t|0|44|0", "update|1"]
    # Start when the tracks already sit where they are aimed: no state 2,
    # and the state they held is left until the snap.
    s += ["t|0|0|%s" % F(5.0), "t|0|44|0x00070003", "t|1|0|0",
          "t|1|44|0x00050001", "start"]
    s += ["t|1|0|0x80000000", "t|1|44|0x00030002", "start"]
    s += ["t|0|0|%s" % F(float("nan")), "start"] + frames(3)
    # A BUSTED! whose scale is already 5, and one that is NaN.
    s += ["pos|%s|%s|%s|%s|%s" % (BUSTED, F(317.0), F(174.0), F(5.0),
                                  F(5.0)), "start"] + frames(4)
    s += ["pos|%s|%s|%s|%s|%s" % (BUSTED, F(-12.5), F(1e6), F(float("nan")),
                                  F(0.25)), "start"] + frames(4)
    s += ["pos|%s|%s|%s|%s|%s" % (BUSTED, F(317.0), F(174.0), F(2.0),
                                  F(2.0)), "start"] + frames(16, first=40)
    # No BUSTED!: Update leaves both texts be, and still seeks.
    s += ["o|busted|none", "t|1|0|%s" % F(64.0), "t|1|44|0", "update|1",
          "o|points|none", "update|1", "o|busted|%s" % BUSTED,
          "o|points|%s" % POINTS, "update|1"]
    return s


def s_date():
    s = ["g|rframes|5000"]
    # Every month, in BCD and out of it.
    for mon in (0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09,
                0x10, 0x11, 0x12, 0x13, 0x0a, 0x0b, 0x0c, 0x0d, 0x1f, 0x20,
                0x99, 0xff, 0x80):
        s += [clock(mon=mon), "date"]
    # Odd BCD in every other field.
    for kw in (dict(day=0x00), dict(day=0x09), dict(day=0xff),
               dict(day=0x1a), dict(yr=0x00), dict(yr=0x99), dict(yr=0xa5),
               dict(yr=0xff), dict(hr=0x00, mn=0x00, sec=0x00),
               dict(hr=0xff, mn=0x0f, sec=0xf0), dict(sec=0x60),
               dict(mn=0x9f), dict(pad=0xff), dict(hr=0x24, sec=0x59)):
        s += [clock(**kw), "date"]
    # A clock that fails, or answers busy.
    for kw in (dict(ret=0), dict(ret=-1), dict(ret=2), dict(stat=1),
               dict(stat=0x80), dict(stat=0xff), dict(stat=1, ret=0)):
        s += [clock(mon=0x07, **kw), "g|rframes|%d" % (5100 + len(s)),
              "date"]
    # The local time overwrites the clock's bytes.
    s += [clock(), local(0x01, 0x02, 0x03, 0x04, 0x05, 0x06), "date",
          local(0x59, 0x59, 0x23, 0x28, 0x02, 0x00, stat=0x55, pad=0x66),
          "date", local(0xff, 0xff, 0xff, 0xff, 0xff, 0xff), "date",
          clock(stat=1), "date", "local|-", clock(), "date"]
    # Each language.
    for lang in (1, 2, 5, -1, 0x100, 0):
        s += ["g|lang|%d" % lang, clock(mon=0x03, day=0x07), "date"]
    # A long name is cut at the text's end; an empty one prints nothing.
    s += ["xl|0xe877|DecemberDecemberDecember", clock(), "date",
          "g|lang|1", "date", "g|lang|0", "xl|0xe877|", "date",
          "xl|0xe877|December", "date"]
    # The time last when RealTimeFrames is negative.
    s += ["g|rframes|-5", "date", "g|rframes|5200"]
    return s


def s_visible():
    s = ["o|screen|%#x" % SCREEN]
    # Every overlay state, on and off.
    for st in (0, 1, 2, 3, 4, -1, 7):
        s += ["o|state|%d" % st]
        for on in (1, 0, 2, 0xffffffff, 0x100):
            s += ["visible|%#x" % on]
    # The cop and not, one player and two.
    for cop, n in ((0, 1), (1, 1), (1, 2), (1, 0), (2, 1), (-1, 1), (1, -1),
                   (0, 2), (1, 1)):
        s += ["rp|BeACop|%d" % cop, "rp|Players|%d" % n]
        for st in (1, 2, 3):
            s += ["o|state|%d" % st, "visible|1", "visible|0"]
    # Every coordinator state, and the replay demo.
    for rc in list(range(10)) + [-1, 100]:
        for demo in (0, 1):
            s += ["rc|%d|%d" % (rc, demo), "o|state|1", "visible|1",
                  "o|state|3", "visible|1", "visible|0"]
    s += ["rc|3|0", "rp|BeACop|0", "rp|Players|1"]
    return s


def s_starts():
    s = []
    for op in ("arrest", "ticket", "busted"):
        s += ["o|state|0", op, "visible|1"] + frames(3, first=100)
    s += ["rp|BeACop|1", "busted", "visible|1", "ticket", "visible|1",
          "rp|BeACop|0"]
    return s


def s_screens():
    s = []
    for scr in (TOP, BOTTOM, HUD, SCREEN):
        s += ["o|screen|%#x" % scr, "g|rframes|%d" % (8000 + len(s)),
              "busted", "visible|1"] + frames(4, first=200)
        s += ["update|0", "o|state|1", "visible|1", "visible|0", "date"]
    return s


def script():
    s = common()
    s += s_no_screen()
    s += s_start()
    s += s_tracks()
    s += s_date()
    s += s_visible()
    s += s_starts()
    s += s_screens()
    return s


# =================================================================== model

class Model(fc.Model):
    def __init__(self):
        fc.Model.__init__(self)
        e = self.e
        self.lines = {}
        e.write(RP, bytes(RP_SIZE))
        for g in (G_ELAPSED, G_WFRAMES, G_RFRAMES, LANGUAGE):
            e.put32(g, 0)
        self.rc = e.alloc(64, align=16)
        e.write(self.rc, bytes(64))
        e.put32(G_RC, self.rc)
        self.tracks = [e.alloc(TRACK_SIZE, align=16) for _ in range(2)]
        for t in self.tracks:
            for o in range(0, TRACK_SIZE, 4):
                e.put32(t + o, pattern(o))
        self.ovl = o = e.alloc(OVL_SIZE, align=16)
        e.write(o, bytes(OVL_SIZE))
        e.put32(o, pattern(0))
        e.put32(o + 12, self.tracks[0])
        e.put32(o + 16, self.tracks[1])
        for off in (28, 32, 36, 40):
            e.put32(o + off, pattern(off))
        self.xlbuf = e.alloc(256, align=16)
        self.clock = bytes(8)
        self.clock_ret = 0
        self.local = None
        self.xl = {}
        self.demo = 0
        e.stub(S_CLOCK, self.s_clock)
        e.stub(S_LOCAL, self.s_local)
        e.stub(S_XL, self.s_xl)
        e.stub(S_DEMO, self.s_demo)
        e.stub(S_SCREEN, self.s_screen)

    # ---- stubs

    def s_clock(self, em):
        self.e.write(em.reg[4] & M32, self.clock)
        self.emit("  clock %s -> %d" % (self.clock.hex(), self.clock_ret))
        return self.clock_ret & M32

    def s_local(self, em):
        a = em.reg[4] & M32
        self.emit("  local %s" % bytes(self.e.mem[a:a + 8]).hex())
        if self.local is not None:
            self.e.write(a, self.local)

    def s_xl(self, em):
        i = em.reg[4] & M32
        t = self.xl.get(i, "M%x" % i)
        self.emit("  xl %#x -> %s" % (i, t))
        self.e.write(self.xlbuf, t.encode("latin-1") + b"\0")
        return self.xlbuf

    def s_demo(self, em):
        a = em.reg[4] & M32
        self.emit("  demo? %d -> %d" % (1 if a == self.rc else 0,
                                        self.demo))
        return self.demo & M32

    def s_screen(self, em):
        self.emit("  screen %08x vis %d" % (em.reg[4] & M32,
                                            s32(em.reg[5] & M32)))

    # ---- output

    def note(self, key, text):
        if self.lines.get(key) != text:
            self.lines[key] = text
            self.emit("  %s %s" % (key, text))

    def dump_objects(self):
        mem = self.e.mem
        for p in self.projects:
            for i, (a, n) in enumerate(p.objects):
                text = bytes(mem[a + 8:a + 44]).hex() + " "
                if mem[a + 40] == 1 and n >= 100:
                    k = self.text_len(a)
                    text += '%s "%s"' % (bytes(mem[a + 48:a + 100]).hex(),
                                         bytes(mem[a + 100:a + 100 + k])
                                         .decode("latin-1"))
                else:
                    text += bytes(mem[a + 48:a + n]).hex()
                self.note("obj %d:%d" % (p.n, i), text)
                # A drawn frame clears DirtyFlag, so the next dump shows
                # only what the next op stamps.
                mem[a + 43] = 0

    def track_name(self, a):
        if a in self.tracks:
            return "t%d" % self.tracks.index(a)
        return "stray"

    def dump(self):
        e = self.e
        o = self.ovl
        g = e.u32
        self.note("ovl", "last %08x screen %08x state %d tracks %s %s "
                  "busted %s points %s sx %08x sy %08x scale %08x %08x" % (
                      g(o), g(o + 4), s32(g(o + 8)),
                      self.track_name(g(o + 12)), self.track_name(g(o + 16)),
                      self.name(g(o + 20)), self.name(g(o + 24)),
                      g(o + 28), g(o + 32), g(o + 36), g(o + 40)))
        for k, t in enumerate(self.tracks):
            self.note("t%d" % k, bytes(e.mem[t:t + TRACK_SIZE]).hex())
        self.dump_objects()

    # ---- ops

    def obj(self, s):
        screen = self.e.u32(self.ovl + 4)
        for prefix, kind in (("t:", 1), ("b:", 2)):
            if s.startswith(prefix):
                return self.e.call(fc.F_OBJECT, s32(screen),
                                   s32(int(s[2:], 0)), kind,
                                   limit=200000) & M32
        return 0

    def op(self, a):
        e = self.e
        o = a[0]
        ovl = self.ovl
        v = lambda i: int(a[i], 0) & M32      # noqa: E731
        if o == "load":
            self.load(a[1])
            return
        if o == "o":
            n = a[1]
            if n in ("busted", "points"):
                e.put32(ovl + (20 if n == "busted" else 24), self.obj(a[2]))
            else:
                e.put32(ovl + {"last": 0, "screen": 4, "state": 8, "sx": 28,
                               "sy": 32, "scalex": 36, "scaley": 40}[n],
                        v(2))
        elif o == "t":
            e.put32(self.tracks[int(a[1])] + int(a[2], 0), v(3))
        elif o == "g":
            e.put32({"elapsed": G_ELAPSED, "rframes": G_RFRAMES,
                     "wframes": G_WFRAMES, "lang": LANGUAGE}[a[1]], v(2))
        elif o == "rp":
            e.put32(RP + {"BeACop": RP_COP, "Players": RP_PLAYERS}[a[1]],
                    v(2))
        elif o == "rc":
            e.put32(self.rc, v(1))
            self.demo = s32(v(2))
        elif o == "clock":
            self.clock_ret = s32(v(1))
            self.clock = bytes(int(x, 0) & 0xff for x in a[2:10])
        elif o == "local":
            self.local = (None if a[1] == "-"
                          else bytes(int(x, 0) & 0xff for x in a[1:9]))
        elif o == "xl":
            self.xl[v(1)] = a[2]
        elif o == "pos":
            at = self.obj(a[1]) + 48
            for i in range(4):
                e.put32(at + 4 * i, v(2 + i))
        elif o in ("start", "arrest", "ticket", "busted", "date"):
            e.call({"start": F_START, "arrest": F_ARREST,
                    "ticket": F_TICKET, "busted": F_BUSTED,
                    "date": F_DATE}[o], ovl, limit=4000000)
        elif o == "update":
            e.call(F_UPDATE, ovl, 1 if v(1) else 0, limit=4000000)
        elif o == "visible":
            e.call(F_VISIBLE, ovl, v(1), limit=1000000)
        else:
            raise ValueError(o)
        self.dump()


def model(lines):
    return Model().run(lines)


# ================================================================= build

def build_harness(tmp, name="hudnis_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


run_harness = fc.run_harness
diff = pcc.diff
write_script = fc.write_script


# ============================================================= mutations

H = HUDNIS


def M(name, before, after, rel=H):
    return (name, rel, before, after)


MUTATIONS = [
    # The tracks.
    M("track-seconds", "#define TRACK_SECONDS  0.25f", "#define TRACK_SECONDS  0.3f"),
    M("scale-from", "#define SCALE_FROM     5.0f", "#define SCALE_FROM     4.0f"),
    M("alpha-from", "#define ALPHA_FROM     0.0f", "#define ALPHA_FROM     1.0f"),
    M("alpha-to", "#define ALPHA_TO     128.0f", "#define ALPHA_TO     127.0f"),
    M("aim-no-state", "    if (!(v == t->val))\n        t->state = 2;\n", ""),
    M("aim-always", "    if (!(v == t->val))\n        t->state = 2;", "    t->state = 2;"),
    M("aim-state-1", "        t->state = 2;", "        t->state = 1;"),
    M("aim-no-target", "    t->valDesired = v;\n", ""),
    M("snap-no-val", "    t->val = t->valDesired;\n", ""),
    M("snap-no-dval", "    t->dval = t->dvalDesired;\n", ""),
    M("snap-state-kept", "    t->dval = t->dvalDesired;\n    t->state = 0;\n", "    t->dval = t->dvalDesired;\n"),
    M("start-flags-kept", "    t->flags = 0;\n", ""),
    M("start-duration-kept", "    t->duration = TRACK_SECONDS;\n", ""),
    M("start-no-snap", "    track_aim(t, from);\n    track_snap(t);\n", "    track_aim(t, from);\n"),
    M("start-no-from", "    track_aim(t, from);\n    track_snap(t);\n", "    track_snap(t);\n"),

    # Start.
    M("start-no-screen-test", "    if (s == 0)\n        return;\n    o->LastDateTimeUpdate = 0;",
      "    o->LastDateTimeUpdate = 0;"),
    M("start-last-kept", "    o->LastDateTimeUpdate = 0;\n", ""),
    M("start-no-date", "    o->LastDateTimeUpdate = 0;\n    nisoverlay_update_date_and_time(o);\n",
      "    o->LastDateTimeUpdate = 0;\n"),
    M("start-screen-hidden", "#define NISOVERLAY_SCREEN_VISIBLE 0", "#define NISOVERLAY_SCREEN_VISIBLE 1"),
    M("start-no-screen-vis", "        gSetFlailerScreenVisibilityFn(s, NISOVERLAY_SCREEN_VISIBLE);", "        ;"),
    M("start-busted-bitmap", "    o->BustedDisplay = flailer_find_object(s, NISOVERLAY_BUSTED_OBJECT,\n                                           FLAILER_TYPE_TEXT);",
      "    o->BustedDisplay = flailer_find_object(s, NISOVERLAY_BUSTED_OBJECT,\n                                           FLAILER_TYPE_BITMAP);"),
    M("start-points-busted", "    o->PointsDisplay = flailer_find_object(s, NISOVERLAY_POINTS_OBJECT,",
      "    o->PointsDisplay = flailer_find_object(s, NISOVERLAY_BUSTED_OBJECT,"),
    M("start-points-kept", "    o->PointsDisplay = flailer_find_object(s, NISOVERLAY_POINTS_OBJECT,\n                                           FLAILER_TYPE_TEXT);\n", ""),
    M("start-sx-y", "    o->sx = flailer_get_top_left_x(s,", "    o->sx = flailer_get_top_left_y(s,"),
    M("start-sy-x", "    o->sy = flailer_get_top_left_y(s,", "    o->sy = flailer_get_top_left_x(s,"),
    M("start-sx-points", "    o->sx = flailer_get_top_left_x(s, NISOVERLAY_BUSTED_OBJECT);",
      "    o->sx = flailer_get_top_left_x(s, NISOVERLAY_POINTS_OBJECT);"),
    M("start-scale-swapped", "&o->ScaleX, &o->ScaleY);", "&o->ScaleY, &o->ScaleX);"),
    M("start-scale-to-y", "    track_start(o->ScaleAnimationTrack, SCALE_FROM, o->ScaleX);",
      "    track_start(o->ScaleAnimationTrack, SCALE_FROM, o->ScaleY);"),
    M("start-tracks-swapped", "    track_start(o->AlphaAnimationTrack, ALPHA_FROM, ALPHA_TO);",
      "    track_start(o->ScaleAnimationTrack, ALPHA_FROM, ALPHA_TO);"),

    # Update.
    M("update-y-x", "        flailerobject_set_top_left_y(o->BustedDisplay, o->sy);",
      "        flailerobject_set_top_left_y(o->BustedDisplay, o->sx);"),
    M("update-no-y", "        flailerobject_set_top_left_y(o->BustedDisplay, o->sy);\n", ""),
    M("update-scale-x", "        flailerobject_set_scale_y(o->BustedDisplay, o->ScaleY);",
      "        flailerobject_set_scale_y(o->BustedDisplay, o->ScaleX);"),
    M("update-no-scale-y", "        flailerobject_set_scale_y(o->BustedDisplay, o->ScaleY);\n", ""),
    M("update-scale-alpha", "                                         o->ScaleAnimationTrack->val);",
      "                                         o->AlphaAnimationTrack->val);"),
    M("update-scale-target", "                                         o->ScaleAnimationTrack->val);",
      "                                         o->ScaleAnimationTrack->valDesired);"),
    M("update-alpha-rounded", "        a = ee_trunc_w(o->AlphaAnimationTrack->val);\n        flailertext_set_alpha(text(o->BustedDisplay), a);",
      "        a = (int32_t)(o->AlphaAnimationTrack->val + 0.5f);\n        flailertext_set_alpha(text(o->BustedDisplay), a);"),
    M("update-alpha-c-cast", "        a = ee_trunc_w(o->AlphaAnimationTrack->val);\n        // Retail",
      "        a = (int32_t)o->AlphaAnimationTrack->val;\n        // Retail"),
    M("update-no-busted-alpha", "        flailertext_set_alpha(text(o->BustedDisplay), a);\n", ""),
    M("update-no-points-alpha", "            flailertext_set_alpha(text(o->PointsDisplay), a);", "            ;"),
    M("update-seek-scale-twice", "    bspline_seek(o->AlphaAnimationTrack, WorldTimeElapsed);",
      "    bspline_seek(o->ScaleAnimationTrack, WorldTimeElapsed);"),
    M("update-no-seek", "    bspline_seek(o->ScaleAnimationTrack, WorldTimeElapsed);\n", ""),
    M("update-seek-half", "    bspline_seek(o->AlphaAnimationTrack, WorldTimeElapsed);",
      "    bspline_seek(o->AlphaAnimationTrack, WorldTimeElapsed * 0.5f);"),
    M("update-seek-before", "    if (o->BustedDisplay != NULL) {\n        int32_t a;\n",
      "    bspline_seek(o->ScaleAnimationTrack, WorldTimeElapsed);\n    if (o->BustedDisplay != NULL) {\n        int32_t a;\n"),
    M("update-date-30", "#define DATE_EVERY     31", "#define DATE_EVERY     30"),
    M("update-date-32", "#define DATE_EVERY     31", "#define DATE_EVERY     32"),
    M("update-date-unsigned", "    if (!((int32_t)((uint32_t)RealTimeFrames - o->LastDateTimeUpdate)\n          < DATE_EVERY))",
      "    if (!(((uint32_t)RealTimeFrames - o->LastDateTimeUpdate)\n          < DATE_EVERY))"),
    M("update-date-no-wrap", "    if (!((int32_t)((uint32_t)RealTimeFrames - o->LastDateTimeUpdate)\n          < DATE_EVERY))",
      "    if (!((int64_t)RealTimeFrames - (int64_t)(int32_t)o->LastDateTimeUpdate\n          < DATE_EVERY))"),
    M("update-no-date", "        nisoverlay_update_date_and_time(o);\n    if (!playing", "        ;\n    if (!playing"),
    M("update-blink-16", "(WorldTimeFrames & 8)", "(WorldTimeFrames & 16)"),
    M("update-blink-4", "(WorldTimeFrames & 8)", "(WorldTimeFrames & 4)"),
    M("update-no-blink", "    if (!playing || (WorldTimeFrames & 8))", "    if (!playing)"),
    M("update-rec-playing-ignored", "    if (!playing || (WorldTimeFrames & 8))", "    if (WorldTimeFrames & 8)"),
    M("update-rec-object", "        flailer_set_visibility(o->ScreenHash, NISOVERLAY_REC_LIGHT,\n                               FLAILER_OBJECT_VISIBLE);",
      "        flailer_set_visibility(o->ScreenHash, NISOVERLAY_FRAME,\n                               FLAILER_OBJECT_VISIBLE);"),
    M("update-rec-never-shown", "        flailer_set_visibility(o->ScreenHash, NISOVERLAY_REC_LIGHT,\n                               FLAILER_OBJECT_VISIBLE);",
      "        flailer_set_visibility(o->ScreenHash, NISOVERLAY_REC_LIGHT,\n                               FLAILER_OBJECT_INVISIBLE);"),
    M("update-frame-always", "                           playing ? FLAILER_OBJECT_VISIBLE\n                                   : FLAILER_OBJECT_INVISIBLE);",
      "                           FLAILER_OBJECT_VISIBLE);"),
    M("update-frame-inverted", "                           playing ? FLAILER_OBJECT_VISIBLE\n                                   : FLAILER_OBJECT_INVISIBLE);",
      "                           playing ? FLAILER_OBJECT_INVISIBLE\n                                   : FLAILER_OBJECT_VISIBLE);"),

    # UpdateDateAndTime.
    M("date-ret-ignored", "    if (gCdReadClockFn == NULL || gCdReadClockFn(&c) == 0)",
      "    if (gCdReadClockFn == NULL || (gCdReadClockFn(&c), 0))"),
    M("date-ret-positive", "    if (gCdReadClockFn == NULL || gCdReadClockFn(&c) == 0)",
      "    if (gCdReadClockFn == NULL || gCdReadClockFn(&c) <= 0)"),
    M("date-stat-ignored", "    if (c.stat != 0)\n        return;\n", ""),
    M("date-stat-low-bit", "    if (c.stat != 0)", "    if (c.stat & 1)"),
    M("date-no-local", "    if (gScfGetLocalTimeFn != NULL)\n        gScfGetLocalTimeFn(&c);\n", ""),
    M("date-local-first", "    if (c.stat != 0)\n        return;\n    if (gScfGetLocalTimeFn != NULL)\n        gScfGetLocalTimeFn(&c);\n",
      "    if (gScfGetLocalTimeFn != NULL)\n        gScfGetLocalTimeFn(&c);\n    if (c.stat != 0)\n        return;\n"),
    M("date-bcd-hex", "    return (b >> 4) * 10 + (b & 15);", "    return (b >> 4) * 16 + (b & 15);"),
    M("date-bcd-low", "    return (b >> 4) * 10 + (b & 15);", "    return (b >> 4) * 10 + (b & 7);"),
    M("date-bcd-capped", "    return (b >> 4) * 10 + (b & 15);", "    return ((b >> 4) % 10) * 10 + (b & 15) % 10;"),
    M("date-month-day", "    month = bcd(c.month);", "    month = bcd(c.day);"),
    M("date-day-month", "    day = bcd(c.day);", "    day = bcd(c.month);"),
    M("date-year-pad", "    year = bcd(c.year);", "    year = bcd(c.pad);"),
    M("date-hour-minute", "    hour = bcd(c.hour);", "    hour = bcd(c.minute);"),
    M("date-minute-second", "    minute = bcd(c.minute);", "    minute = bcd(c.second);"),
    M("date-second-pad", "    second = bcd(c.second);", "    second = bcd(c.pad);"),
    M("date-month-signed", "    if ((uint32_t)(month - 2) < 11)", "    if (month - 2 < 11)"),
    M("date-month-10", "    if ((uint32_t)(month - 2) < 11)", "    if ((uint32_t)(month - 2) < 10)"),
    M("date-month-12", "    if ((uint32_t)(month - 2) < 11)", "    if ((uint32_t)(month - 2) < 12)"),
    M("date-month-offset", "        id = FEBRUARY_ID + (month - 2);", "        id = FEBRUARY_ID + (month - 1);"),
    M("date-january", "#define JANUARY_ID   0xe86c", "#define JANUARY_ID   0xe86b"),
    M("date-february", "#define FEBRUARY_ID  0xe86d", "#define FEBRUARY_ID  0xe86c"),
    M("date-lang-ignored", "    if (gCurrLanguageFn != NULL && gCurrLanguageFn() != 0)",
      "    if (0)"),
    M("date-lang-positive", "    if (gCurrLanguageFn != NULL && gCurrLanguageFn() != 0)",
      "    if (gCurrLanguageFn != NULL && gCurrLanguageFn() > 0)"),
    M("date-lang-1", "    if (gCurrLanguageFn != NULL && gCurrLanguageFn() != 0)",
      "    if (gCurrLanguageFn != NULL && gCurrLanguageFn() == 1)"),
    M("date-other-format", "NISOVERLAY_DATE_OBJECT, \"%d %s 20%02d\",", "NISOVERLAY_DATE_OBJECT, \"%d %s 20%2d\","),
    M("date-english-format", "NISOVERLAY_DATE_OBJECT, \"%s %d 20%02d\",", "NISOVERLAY_DATE_OBJECT, \"%s %02d 20%02d\","),
    M("date-english-order", "                       name, day, year);", "                       name, year, day);"),
    M("date-other-order", "                       day, name, year);", "                       year, name, day);"),
    M("date-time-format", "\"%02d:%02d:%02d\",", "\"%02d:%02d:%d\","),
    M("date-time-order", "                   hour, minute, second);", "                   second, minute, hour);"),
    M("date-on-time", "        flailer_printf(o->ScreenHash, NISOVERLAY_DATE_OBJECT, \"%s %d 20%02d\",",
      "        flailer_printf(o->ScreenHash, NISOVERLAY_TIME_OBJECT, \"%s %d 20%02d\","),
    M("date-no-time", "    flailer_printf(o->ScreenHash, NISOVERLAY_TIME_OBJECT, \"%02d:%02d:%02d\",\n                   hour, minute, second);\n", ""),
    M("date-last-kept", "    o->LastDateTimeUpdate = (uint32_t)RealTimeFrames;\n}", "}"),
    M("date-last-plus-one", "    o->LastDateTimeUpdate = (uint32_t)RealTimeFrames;\n}", "    o->LastDateTimeUpdate = (uint32_t)RealTimeFrames + 1;\n}"),

    # SetVisible.
    M("vis-no-screen-test", "    if (o->ScreenHash == 0 || in_replay())", "    if (in_replay())"),
    M("vis-replay-ignored", "    if (o->ScreenHash == 0 || in_replay())", "    if (o->ScreenHash == 0)"),
    M("vis-instant-replay", "    return state == RCSTATE_INSTANT_REPLAY || state == RCSTATE_POSTRACE",
      "    return state == RCSTATE_PAUSE || state == RCSTATE_POSTRACE"),
    M("vis-postrace", "|| state == RCSTATE_POSTRACE", "|| state == RCSTATE_PRERACE"),
    M("vis-auto-replay", "           || state == RCSTATE_AUTO_REPLAY", "           || state == RCSTATE_AI_DEMO_MODE"),
    M("vis-no-demo", "           || state == RCSTATE_AUTO_REPLAY\n           || racecoordinator_is_replay_demo_mode(pRaceCoordinator);",
      "           || state == RCSTATE_AUTO_REPLAY;"),
    M("vis-demo-first", "    return state == RCSTATE_INSTANT_REPLAY || state == RCSTATE_POSTRACE\n           || state == RCSTATE_AUTO_REPLAY\n           || racecoordinator_is_replay_demo_mode(pRaceCoordinator);",
      "    return racecoordinator_is_replay_demo_mode(pRaceCoordinator)\n           || state == RCSTATE_INSTANT_REPLAY || state == RCSTATE_POSTRACE\n           || state == RCSTATE_AUTO_REPLAY;"),
    M("vis-off-shown", "    if (!on) {\n        flailer_set_group_visibility(o->ScreenHash, NISOVERLAY_GROUP,\n                                     FLAILER_OBJECT_INVISIBLE);",
      "    if (!on) {\n        flailer_set_group_visibility(o->ScreenHash, NISOVERLAY_GROUP,\n                                     FLAILER_OBJECT_VISIBLE);"),
    M("vis-off-falls-through", "                                     FLAILER_OBJECT_INVISIBLE);\n        return;\n    }",
      "                                     FLAILER_OBJECT_INVISIBLE);\n    }"),
    M("vis-on-low-byte", "    if (!on) {", "    if (!(on & 0xff)) {"),
    M("vis-ticket-only", "    if (o->State == FLAILER_NIS_TICKET || o->State == FLAILER_NIS_ARREST) {",
      "    if (o->State == FLAILER_NIS_TICKET) {"),
    M("vis-arrest-only", "    if (o->State == FLAILER_NIS_TICKET || o->State == FLAILER_NIS_ARREST) {",
      "    if (o->State == FLAILER_NIS_ARREST) {"),
    M("vis-idle-shown", "    if (o->State == FLAILER_NIS_TICKET || o->State == FLAILER_NIS_ARREST) {",
      "    if (o->State != FLAILER_NIS_BUSTED) {"),
    M("vis-group-hidden", "        flailer_set_group_visibility(o->ScreenHash, NISOVERLAY_GROUP,\n                                     FLAILER_OBJECT_VISIBLE);\n        show_points(o);",
      "        flailer_set_group_visibility(o->ScreenHash, NISOVERLAY_GROUP,\n                                     FLAILER_OBJECT_INVISIBLE);\n        show_points(o);"),
    M("vis-ticket-no-points", "                                     FLAILER_OBJECT_VISIBLE);\n        show_points(o);\n", "                                     FLAILER_OBJECT_VISIBLE);\n"),
    M("vis-busted-group-shown", "    } else if (o->State == FLAILER_NIS_BUSTED) {\n        flailer_set_group_visibility(o->ScreenHash, NISOVERLAY_GROUP,\n                                     FLAILER_OBJECT_INVISIBLE);",
      "    } else if (o->State == FLAILER_NIS_BUSTED) {\n        flailer_set_group_visibility(o->ScreenHash, NISOVERLAY_GROUP,\n                                     FLAILER_OBJECT_VISIBLE);"),
    M("vis-busted-hidden", "        flailer_set_visibility(o->ScreenHash, NISOVERLAY_BUSTED_OBJECT,\n                               FLAILER_OBJECT_VISIBLE);",
      "        flailer_set_visibility(o->ScreenHash, NISOVERLAY_BUSTED_OBJECT,\n                               FLAILER_OBJECT_INVISIBLE);"),
    M("vis-busted-order", "        flailer_set_group_visibility(o->ScreenHash, NISOVERLAY_GROUP,\n                                     FLAILER_OBJECT_INVISIBLE);\n        flailer_set_visibility(o->ScreenHash, NISOVERLAY_BUSTED_OBJECT,\n                               FLAILER_OBJECT_VISIBLE);",
      "        flailer_set_visibility(o->ScreenHash, NISOVERLAY_BUSTED_OBJECT,\n                               FLAILER_OBJECT_VISIBLE);\n        flailer_set_group_visibility(o->ScreenHash, NISOVERLAY_GROUP,\n                                     FLAILER_OBJECT_INVISIBLE);"),
    M("vis-busted-no-points", "NISOVERLAY_BUSTED_OBJECT,\n                               FLAILER_OBJECT_VISIBLE);\n        show_points(o);\n    }",
      "NISOVERLAY_BUSTED_OBJECT,\n                               FLAILER_OBJECT_VISIBLE);\n    }"),
    M("points-cop-ignored", "    if (TheRaceParameters.BeACop != 0\n        && TheRaceParameters.NumPlayerCars == 1)",
      "    if (TheRaceParameters.NumPlayerCars == 1)"),
    M("points-players-ignored", "    if (TheRaceParameters.BeACop != 0\n        && TheRaceParameters.NumPlayerCars == 1)",
      "    if (TheRaceParameters.BeACop != 0)"),
    M("points-cop-positive", "    if (TheRaceParameters.BeACop != 0\n", "    if (TheRaceParameters.BeACop > 0\n"),
    M("points-players-le", "        && TheRaceParameters.NumPlayerCars == 1)", "        && TheRaceParameters.NumPlayerCars <= 1)"),
    M("points-object", "    flailer_set_visibility(o->ScreenHash, NISOVERLAY_POINTS_OBJECT, v);",
      "    flailer_set_visibility(o->ScreenHash, NISOVERLAY_BUSTED_OBJECT, v);"),

    # The three Start*.
    M("arrest-ticket", "    o->State = FLAILER_NIS_ARREST;", "    o->State = FLAILER_NIS_TICKET;"),
    M("ticket-arrest", "    o->State = FLAILER_NIS_TICKET;\n    nisoverlay_start(o);", "    o->State = FLAILER_NIS_ARREST;\n    nisoverlay_start(o);"),
    M("busted-arrest", "    o->State = FLAILER_NIS_BUSTED;", "    o->State = FLAILER_NIS_ARREST;"),
    M("busted-no-start", "    o->State = FLAILER_NIS_BUSTED;\n    nisoverlay_start(o);", "    o->State = FLAILER_NIS_BUSTED;"),
    M("arrest-state-after", "    o->State = FLAILER_NIS_ARREST;\n    nisoverlay_start(o);", "    nisoverlay_start(o);\n    o->State = FLAILER_NIS_ARREST;"),
]

EQUIVALENT = {
    "arrest-state-after":
        "Start reads nothing of State and calls nothing that does, so State "
        "is the same whether it is set before Start or after.",
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
        if diff(base, out.read_text(encoding="latin-1").splitlines(),
                quiet=True):
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
                n = diff(base, out.read_text(encoding="latin-1")
                         .splitlines(), quiet=True)
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
        harness = out.read_text(encoding="latin-1").splitlines()

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
