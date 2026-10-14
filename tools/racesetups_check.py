#!/usr/bin/env python3
"""Cross-check 3DS Files/source/bsetup.c's other four race setups --
Single Race, Free Run, Lap Knockout and Knockout Setup -- against the
retail image, SLES_507.31.

**The model** is racesetup_check.py's, with the four classes' Callbacks
(0x001b8ae8, 0x001b8c98, 0x001b8f30, 0x001b9210) into BaseCallback
(0x001b7b20), their constructors and destructors (SingleRaceSetup
0x001b87d0, FreeRunSetup 0x001b8b20, LapKnockoutSetup 0x001b8cb8,
TrackKnockoutSetup 0x001b8f60), and the rows they add: OpponentGrid
(0x001b7748, 0x001b77d0), NumOpponents (0x001b77f0, 0x001b7860),
OpponentType (0x001b7908, 0x001b7950) and TrackSetting (0x001b7a10,
0x001b7a58). Be The Cop Setup's Callback (0x001b93d8) is in too, for an
UNACTIVATE that deletes a class other than the one its Callback names.

**The stubs** are racesetup_check.py's, and FlailerPrintf (0x00143e70),
which prints its text formatted (`printf`).

**The script** activates each screen with one car, two, none and three,
the cops on and off, from Fred's defaults; walks every row both ways
through its wraps; selects with one car and two and sends messages to the
exit; and unactivates. Then Single Race's fix-ups (two cars' One to None,
one car's None to One, neither with the cops), the opponent count off its
range and at Full Grid, the car count changed under a live screen, rows'
values poked, and UNACTIVATEs across the classes, over a leaked one and
with none. Retail reads unchecked where racesetup_check.py says; for these
rows too a value off its table is read past the end -- Tracks' 2 is
Damage's "Off" -- where bsetup.c reads 0, so the script refreshes none
(docs/formats/frontend-setup.md). The opponent count has no table: any
number prints.

    python tools/racesetups_check.py
    python tools/racesetups_check.py --mutate [--only a,b]
    python tools/racesetups_check.py --dump out/racesetups
"""
import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                        # noqa: E402
import physicscar_check as pcc          # noqa: E402
import racesetup_check as rsc           # noqa: E402
import setup_check as sc                # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = sc.ROOT
NL = sc.NL
FRED = sc.FRED
PINSTANCE = rsc.PINSTANCE
SCREEN = rsc.SCREEN
MENUITEM = rsc.MENUITEM
fbits = sc.fbits

SR, FR, LK, RK, BTC = 100, 101, 102, 103, 104
CALLBACKS = {SR: 0x001b8ae8, FR: 0x001b8c98, LK: 0x001b8f30,
             RK: 0x001b9210, BTC: 0x001b93d8}
VTABLES = {0x002b6910: SR, 0x002b68d0: FR, 0x002b68e0: LK,
           0x002b68f0: RK, 0x002b6900: BTC}
WORDS = {SR: 7, FR: 3, LK: 6, RK: 7, BTC: 5}
S_PRINTF = 0x00143e70

# Fred's blocks, and the defaults InitWithDefaults gives them (0x001b8af0,
# 0x001b8ca0, 0x001b9218, 0x001b8f38, 0x001b93e0).
OFF = {SR: 36, FR: 84, RK: 96, LK: 124, BTC: 64}
DEFAULTS = {SR: (2, 2, 0, 1, 3, 0, 1), FR: (3, 0, 1),
            RK: (7, 0, 1, 3, 0, 0, 1), LK: (4, 0, 1, 3, 0, 1),
            BTC: (2, 0, 1, 0, 1)}


# ================================================================== script

def smsg(k, m, item=0, port=0):
    return "smsg|%d|%d|%#x|%d" % (k, m, item, port)


def fredw(k, values):
    return "fredw|%d|%s" % (OFF[k], "|".join(str(v) for v in values))


def defaults():
    return [fredw(k, DEFAULTS[k]) for k in (SR, FR, RK, LK, BTC)]


def nrows(k, cars, police):
    """How many rows the constructor attaches."""
    if k == SR:
        return 3 + (2 if cars == 1 or (cars == 2 and not police) else 0)
    if k == FR:
        return 2
    n = 4 if k == RK else 3
    if not police:
        n += 2 if cars == 1 else 1
    return n


STEPS = (7, 7, 7, 7, 7, 6, 6, 6, 6, 6)


def walk(k, n, steps=STEPS):
    """Highlight each row in turn, moving down to it, and step it."""
    s = [smsg(k, 4, MENUITEM[1])]
    for i in range(1, n + 1):
        if i > 1:
            s += [smsg(k, 9, MENUITEM[i - 1]), smsg(k, 4, MENUITEM[i])]
        for d in steps:
            s += [smsg(k, d, MENUITEM[i]), "sdump"]
    s += [smsg(k, 9, MENUITEM[n]), "sdump", smsg(k, 8, MENUITEM[n])]
    return s


def script():
    s = []
    s += rsc.screen_objects()
    s += ["fin|0", "elapsed|%#x" % fbits(1.0 / 60)]
    s += defaults() + ["sdump"]

    # Every screen, every car count and the cops both ways, from the
    # defaults each time.
    for k in (SR, FR, LK, RK):
        for cars, police in ((1, 0), (1, 1), (2, 0), (2, 1), (0, 0),
                             (3, 0)):
            s += defaults()
            s += ["cars|%d" % cars, "police|%d" % police, "fin|0",
                  smsg(k, 11, SCREEN), "sdump", smsg(k, 18), "fin|1",
                  smsg(k, 18), "sdump"]
            s += walk(k, nrows(k, cars, police))
            s += [smsg(k, 12, SCREEN), "sdump"]

    # SELECT with one car and two, then everything to the exit.
    for k in (SR, FR, LK, RK):
        for cars in (1, 2):
            s += ["cars|%d" % cars, "police|0", smsg(k, 11, SCREEN),
                  smsg(k, 4, MENUITEM[1]), smsg(k, 7, MENUITEM[1]),
                  smsg(k, 1, MENUITEM[1]), "sdump"]
            for m in (18, 1, 4, 6, 7, 8, 9, 18):
                s += [smsg(k, m, MENUITEM[1])]
            s += ["sdump", smsg(k, 12, SCREEN), "sdump"]

    # Single Race's fix-ups: two cars without the cops take One to None,
    # one car without them None to One; with the cops, or another count,
    # nothing changes. Each shows in what UNACTIVATE writes back.
    for cars, police, grid in ((2, 0, 1), (2, 0, 2), (2, 0, 0), (1, 0, 0),
                               (1, 0, 1), (1, 1, 0), (2, 1, 1), (0, 0, 1),
                               (0, 0, 0), (3, 0, 0)):
        s += [fredw(SR, (grid, 0, 1, 1, 3, 0, 1)), "cars|%d" % cars,
              "police|%d" % police, smsg(SR, 11, SCREEN), "sdump",
              smsg(SR, 12, SCREEN), "sdump"]
    # Grids that do not move: one car with the cops on None ([1] is 0),
    # and Full Grid and One once the car count has changed under it.
    s += [fredw(SR, (2, 0, 1, 1, 3, 0, 1)), "cars|1", "police|1",
          smsg(SR, 11, SCREEN), smsg(SR, 4, MENUITEM[1]),
          smsg(SR, 7, MENUITEM[1]), "sdump", smsg(SR, 6, MENUITEM[1]),
          "sdump", "police|0", "cars|3", smsg(SR, 7, MENUITEM[1]), "sdump",
          "cars|0", smsg(SR, 6, MENUITEM[1]), "sdump", "cars|2",
          smsg(SR, 7, MENUITEM[1]), "sdump", smsg(SR, 7, MENUITEM[1]),
          "sdump", smsg(SR, 6, MENUITEM[1]), "sdump", "cars|1",
          smsg(SR, 12, SCREEN), "sdump"]
    # Values poked under the screen: Opponents at None for one car, at One
    # for two, and Opponent Type, Catch-up, Traffic and Damage off their
    # ranges.
    s += [fredw(SR, DEFAULTS[SR]), "cars|1", "police|0",
          smsg(SR, 11, SCREEN), "spoke|0|0", smsg(SR, 4, MENUITEM[1]),
          smsg(SR, 7, MENUITEM[1]), "sdump", "cars|2", "spoke|0|1",
          smsg(SR, 6, MENUITEM[1]), "sdump", "cars|1", "spoke|2|5",
          smsg(SR, 9, MENUITEM[1]), smsg(SR, 4, MENUITEM[2]),
          smsg(SR, 7, MENUITEM[2]), "sdump", "spoke|2|-4",
          smsg(SR, 6, MENUITEM[2]), "sdump", "spoke|3|7",
          smsg(SR, 9, MENUITEM[2]), smsg(SR, 4, MENUITEM[3]),
          smsg(SR, 7, MENUITEM[3]), "sdump", "spoke|4|9",
          smsg(SR, 9, MENUITEM[3]), smsg(SR, 4, MENUITEM[4]),
          smsg(SR, 6, MENUITEM[4]), "sdump", smsg(SR, 12, SCREEN), "sdump"]

    # The opponent count: Full Grid at seven, a number below it, off the
    # range both ways at the start, and with two cars under the screen
    # (2 .. 6, and Full Grid at six).
    for k in (LK, RK):
        for count in (7, 3, 6, 9, -1, 0, 2, 8):
            block = list(DEFAULTS[k])
            block[0] = count
            s += [fredw(k, block), "cars|1", "police|0",
                  smsg(k, 11, SCREEN), "sdump", smsg(k, 4, MENUITEM[1]),
                  smsg(k, 7, MENUITEM[1]), "sdump", smsg(k, 6, MENUITEM[1]),
                  smsg(k, 6, MENUITEM[1]), "sdump", smsg(k, 12, SCREEN),
                  "sdump"]
        s += [fredw(k, DEFAULTS[k]), "cars|1", "police|0",
              smsg(k, 11, SCREEN), smsg(k, 4, MENUITEM[1]), "cars|2"]
        for d in (7, 7, 7, 7, 7, 7, 6, 6, 6, 6, 6, 6):
            s += [smsg(k, d, MENUITEM[1]), "sdump"]
        s += ["spoke|0|7", smsg(k, 7, MENUITEM[1]), "sdump", "spoke|0|1",
              smsg(k, 6, MENUITEM[1]), "sdump", "cars|1", "spoke|1|3",
              smsg(k, 9, MENUITEM[1]), smsg(k, 4, MENUITEM[2]),
              smsg(k, 7, MENUITEM[2]), "sdump", smsg(k, 12, SCREEN), "sdump"]
    # Tracks poked off its range, which the change wraps.
    s += [fredw(RK, (7, 0, 1, 3, 0, 1, 1)), "cars|2", "police|1",
          smsg(RK, 11, SCREEN), "sdump", smsg(RK, 4, MENUITEM[1]),
          smsg(RK, 9, MENUITEM[1]), smsg(RK, 4, MENUITEM[2]),
          smsg(RK, 9, MENUITEM[2]), smsg(RK, 4, MENUITEM[3]),
          smsg(RK, 7, MENUITEM[3]), "sdump", "spoke|5|-3",
          smsg(RK, 6, MENUITEM[3]), "sdump", smsg(RK, 12, SCREEN), "sdump"]

    # Each screen's last row left changed when it goes, so the block's
    # last word is written back changed. The word after Lap Knockout's six
    # (the audio options', Fred+148) is marked: nothing writes it.
    s += defaults() + ["fredw|148|12345"]
    for k in (SR, FR, LK, RK):
        for cars, police in ((1, 0), (2, 1)):
            n = nrows(k, cars, police)
            s += ["cars|%d" % cars, "police|%d" % police,
                  smsg(k, 11, SCREEN), smsg(k, 4, MENUITEM[1])]
            for i in range(2, n + 1):
                s += [smsg(k, 9, MENUITEM[i - 1]), smsg(k, 4, MENUITEM[i])]
            s += [smsg(k, 7, MENUITEM[n]), "sdump", smsg(k, 12, SCREEN),
                  "sdump"]
    s += ["fredw|148|0"]

    # UNACTIVATE deletes whichever class is live, through any Callback:
    # Single Race's through Be The Cop Setup's, Be The Cop Setup's through
    # Free Run's, and Knockout's through Lap Knockout's over a Lap
    # Knockout leaked by a second ACTIVATE. With none live, nothing.
    s += defaults() + ["cars|1", "police|0"]
    s += [smsg(SR, 11, SCREEN), smsg(SR, 4, MENUITEM[1]),
          smsg(SR, 7, MENUITEM[1]), smsg(BTC, 12, SCREEN), "sdump",
          smsg(BTC, 11, SCREEN), smsg(BTC, 4, MENUITEM[1]),
          smsg(BTC, 7, MENUITEM[1]), smsg(FR, 12, SCREEN), "sdump",
          smsg(LK, 11, SCREEN), smsg(LK, 4, MENUITEM[1]),
          smsg(LK, 7, MENUITEM[1]), smsg(RK, 11, SCREEN), "sdump",
          smsg(RK, 4, MENUITEM[1]), smsg(RK, 6, MENUITEM[1]),
          smsg(LK, 12, SCREEN), "sdump", smsg(RK, 12, SCREEN), "sdump",
          smsg(FR, 11, SCREEN), smsg(SR, 18), smsg(SR, 4, MENUITEM[2]),
          smsg(SR, 7, MENUITEM[2]), smsg(LK, 12, SCREEN), "sdump"]
    return s


# =================================================================== model

class Model(rsc.Model):
    def __init__(self):
        rsc.Model.__init__(self)
        e = self.e
        for i in range(36, 148, 4):
            e.put32(FRED + i, 0)
        e.stub(S_PRINTF, self.printf)

    def malloc(self, em):
        size = s32(em.reg[4])
        a = self.e.alloc(size)
        self.e.write(a, bytes(size))
        if size in (776, 784, 788, 792):
            self.inst = a
        elif size == 28:
            self.exit = a
        elif size not in (44, 64):
            self.emit("  malloc %d" % size)
        return a

    def printf(self, em):
        r = em.reg
        text = self.cstr(r[6] & M32) % s32(r[7])
        self.emit("  printf %08x %08x %s" % (r[4] & M32, r[5] & M32, text))
        return len(text)

    def sdump(self):
        g = self.e.u32
        b = g(PINSTANCE)
        if not b:
            self.emit("  inst 0")
        else:
            kind = VTABLES.get(g(b + 760), 0)
            data = b + 764
            self.emit("  inst 1 kind %d cur %08x data%s exit %d" % (
                kind, g(b + 12), "".join(" %d" % s32(g(data + 4 * i))
                                         for i in range(WORDS.get(kind, 0))),
                1 if g(b + 248) else 0))
            self.body(b, data)
        line = "  fred"
        for name, k in (("sr", SR), ("btc", BTC), ("fr", FR), ("rk", RK),
                        ("lk", LK)):
            line += " " + name + "".join(
                " %d" % s32(g(FRED + OFF[k] + 4 * i)) for i in range(WORDS[k]))
        self.emit(line + " next %d cars %d" % (s32(g(FRED + 148)),
                                                 s32(g(FRED + 0x10734))))

    def op(self, a):
        e = self.e
        o = a[0]
        n = [int(x, 0) for x in a[1:]]
        if o == "smsg":
            d = self.data
            e.put32(d, n[2] & M32)
            e.put32(d + 4, n[3] & M32)
            e.put32(d + 8, 0x5a)
            e.put32(d + 12, 0x5b)
            e.call(CALLBACKS[n[0]], n[1], d, limit=4000000)
            self.emit("  data %d %d" % (s32(e.u32(d + 8)),
                                        s32(e.u32(d + 12))))
        elif o == "fredw":
            for i, v in enumerate(n[1:]):
                e.put32(FRED + n[0] + 4 * i, v & M32)
        elif o == "spoke":
            e.put32(e.u32(PINSTANCE) + 764 + 4 * (n[0] % 7), n[1] & M32)
        elif o == "sdump":
            self.sdump()
        else:
            rsc.Model.op(self, a)


def model(lines):
    return Model().run(lines)


# ============================================================= mutations

S = sc.BSETUP
H = "3DS Files/source/bsetup.h"
MUTATIONS = [
    # Fred's blocks.
    ("off-sr", H, "#define FRED_SINGLE_RACE_SETUP    36",
     "#define FRED_SINGLE_RACE_SETUP    40"),
    ("off-fr", H, "#define FRED_FREE_RUN_SETUP       84",
     "#define FRED_FREE_RUN_SETUP       88"),
    ("off-rk", H, "#define FRED_RACE_KNOCKOUT_SETUP  96",
     "#define FRED_RACE_KNOCKOUT_SETUP  100"),
    ("off-lk", H, "#define FRED_LAP_KNOCKOUT_SETUP   124",
     "#define FRED_LAP_KNOCKOUT_SETUP   128"),
    ("load-from", S, "r->data[i] = fredGet(s, off + 4 * i);",
     "r->data[i] = fredGet(s, off + 4 * i + 4);"),
    ("save-to", S, "put32(s->gf->fred + off + 4 * i, r->data[i]);",
     "put32(s->gf->fred + off + 4 * i, r->data[0]);"),

    # The rows.
    ("grid-table", S, "{30011, 30010, 30012};", "{30010, 30011, 30012};"),
    ("random-same", S, "{30013, 30014};", "{30014, 30013};"),
    ("grid-1p-up", S, "        if (old == 1) *value = 2;",
     "        if (old == 1) *value = 0;"),
    ("grid-1p-down", S, "        else if (old == 2) *value = 1;",
     "        else if (old == 2) *value = 0;"),
    ("grid-2p-up", S, "        if (old == 0) *value = 2;",
     "        if (old == 0) *value = 1;"),
    ("grid-2p-down", S, "        else if (old == 2) *value = 0;",
     "        else if (old == 2) *value = 1;"),
    ("grid-cars", S, "    } else if (cars == 2) {",
     "    } else if (cars >= 2) {"),
    ("grid-changed", S, "    return *value != old;" + NL + "}" + NL + NL
     + "// MaybeChangeNumOpponents", "    return 1;" + NL + "}" + NL + NL
     + "// MaybeChangeNumOpponents"),
    ("numopp-max", S, "FRED_NUM_PLAYER_CARS) == 2 ? 6 : 7;",
     "FRED_NUM_PLAYER_CARS) == 2 ? 7 : 7;"),
    ("numopp-max-1p", S, "FRED_NUM_PLAYER_CARS) == 2 ? 6 : 7;",
     "FRED_NUM_PLAYER_CARS) == 2 ? 6 : 8;"),
    ("numopp-lo", S, "FRED_NUM_PLAYER_CARS) == 2 ? 2 : 3;",
     "FRED_NUM_PLAYER_CARS) == 2 ? 3 : 3;"),
    ("numopp-lo-1p", S, "FRED_NUM_PLAYER_CARS) == 2 ? 2 : 3;",
     "FRED_NUM_PLAYER_CARS) == 2 ? 2 : 2;"),
    ("opptype-range", S, "static int maybeChangeOpponentType(BSetup* s, "
     "BRaceSetup* r, int32_t dir," + NL + "                                   "
     "int32_t* value)" + NL + "{" + NL + "    int32_t old = *value;" + NL
     + "    (void)s;" + NL + "    (void)r;" + NL
     + "    *value = valueChanger(old, dir, 0, 1);",
     "static int maybeChangeOpponentType(BSetup* s, BRaceSetup* r, int32_t "
     "dir," + NL + "                                   int32_t* value)" + NL
     + "{" + NL + "    int32_t old = *value;" + NL + "    (void)s;" + NL
     + "    (void)r;" + NL + "    *value = valueChanger(old, dir, 0, 2);"),
    ("track-range", S, "static int maybeChangeTrackSetting(BSetup* s, "
     "BRaceSetup* r, int32_t dir," + NL + "                                   "
     "int32_t* value)" + NL + "{" + NL + "    int32_t old = *value;" + NL
     + "    (void)s;" + NL + "    (void)r;" + NL
     + "    *value = valueChanger(old, dir, 0, 1);",
     "static int maybeChangeTrackSetting(BSetup* s, BRaceSetup* r, int32_t "
     "dir," + NL + "                                   int32_t* value)" + NL
     + "{" + NL + "    int32_t old = *value;" + NL + "    (void)s;" + NL
     + "    (void)r;" + NL + "    *value = valueChanger(old, dir, 1, 1);"),
    ("grid-refresh-n", S, "refreshFrom(s, r, kGrid, 3, value, text);",
     "refreshFrom(s, r, kGrid, 2, value, text);"),
    ("opptype-refresh", S, "static void refreshOpponentType(BSetup* s, "
     "BRaceSetup* r, int32_t value," + NL + "                                "
     "uint32_t text)" + NL + "{" + NL + "    refreshFrom(s, r, kRandomSame, 2,",
     "static void refreshOpponentType(BSetup* s, BRaceSetup* r, int32_t "
     "value," + NL + "                                uint32_t text)" + NL
     + "{" + NL + "    refreshFrom(s, r, kOffOn, 2,"),
    ("track-refresh", S, "static void refreshTrackSetting(BSetup* s, "
     "BRaceSetup* r, int32_t value," + NL + "                                "
     "uint32_t text)" + NL + "{" + NL + "    refreshFrom(s, r, kRandomSame, 2,",
     "static void refreshTrackSetting(BSetup* s, BRaceSetup* r, int32_t "
     "value," + NL + "                                uint32_t text)" + NL
     + "{" + NL + "    refreshFrom(s, r, kOffOn, 2,"),
    ("numopp-full-id", S, "HOOK(s, setLanguageID, r->screen, text, 30012);",
     "HOOK(s, setLanguageID, r->screen, text, 30011);"),
    ("numopp-full-ge", S, "if (value == numOpponentsMax(s)) {",
     "if (value >= numOpponentsMax(s)) {"),
    ("numopp-no-clear", S, "    HOOK(s, setLanguageID, r->screen, text, 0);"
     + NL + "    snprintf", "    snprintf"),
    ("numopp-fmt", S, '"%d", (int)value);', '"%d", (int)value + 1);'),
    ("numopp-no-print", S, "    HOOK(s, printText, r->screen, text, str);",
     "    (void)0;"),

    # SingleRaceSetup.
    ("sr-load-n", S, "raceSetupLoad(s, r, FRED_SINGLE_RACE_SETUP, 7);",
     "raceSetupLoad(s, r, FRED_SINGLE_RACE_SETUP, 6);"),
    ("sr-2p-police", S, "    if (cars == 2 && !police) {",
     "    if (cars == 2) {"),
    ("sr-fix-2p", S, "        if (r->data[0] == 1) r->data[0] = 0;",
     "        (void)0;"),
    ("sr-fix-1p", S, "        if (!police && r->data[0] == 0) r->data[0] = 1;",
     "        if (r->data[0] == 0) r->data[0] = 1;"),
    ("sr-fix-1p-off", S, "        if (!police && r->data[0] == 0) "
     "r->data[0] = 1;", "        (void)0;"),
    ("sr-1p-cars", S, "    } else if (cars == 1) {" + NL
     + "        if (!police", "    } else if (cars != 2) {" + NL
     + "        if (!police"),
    ("sr-2p-type", S, "                        refreshOpponentType, "
     "&r->data[2]);" + NL + "    } else if (cars == 1) {",
     "                        refreshOpponentType, &r->data[1]);" + NL
     + "    } else if (cars == 1) {"),
    ("sr-1p-grid", S, "                        refreshOpponentGrid," + NL
     + "                        police ? &r->data[1] : &r->data[0]);",
     "                        refreshOpponentGrid," + NL
     + "                        police ? &r->data[0] : &r->data[1]);"),
    ("sr-2p-grid", S, "        raceSetupAttach(r, 30002, 30500, "
     "maybeChangeOpponentGrid," + NL + "                        "
     "refreshOpponentGrid, &r->data[0]);", "        raceSetupAttach(r, "
     "30002, 30500, maybeChangeOpponentGrid," + NL + "                        "
     "refreshOpponentGrid, &r->data[1]);"),
    ("sr-catchup", S, "                    &r->data[3]);" + NL
     + "    raceSetupAttach(r, 30006, 30503, maybeChangeTraffic, "
     "refreshTraffic," + NL + "                    police ? &r->data[5]",
     "                    &r->data[4]);" + NL + "    raceSetupAttach(r, "
     "30006, 30503, maybeChangeTraffic, refreshTraffic," + NL
     + "                    police ? &r->data[5]"),
    ("sr-traffic", S, "police ? &r->data[5] : &r->data[4]);",
     "police ? &r->data[4] : &r->data[5]);"),
    ("sr-damage", S, "                    &r->data[6]);" + NL
     + "    raceSetupBuildMenu(s, r, \"Single Race Setup\");",
     "                    &r->data[5]);" + NL
     + "    raceSetupBuildMenu(s, r, \"Single Race Setup\");"),
    ("sr-name", S, "raceSetupBuildMenu(s, r, \"Single Race Setup\");",
     "raceSetupBuildMenu(s, r, \"Single Race\");"),
    ("sr-no-resync", S, "\"Single Race Setup\");" + NL
     + "    raceSetupResync(s, r);", "\"Single Race Setup\");"),

    # FreeRunSetup.
    ("fr-load-n", S, "raceSetupLoad(s, r, FRED_FREE_RUN_SETUP, 3);",
     "raceSetupLoad(s, r, FRED_FREE_RUN_SETUP, 2);"),
    ("fr-traffic", S, "refreshTraffic," + NL + "                    police"
     " ? &r->data[1] : &r->data[0]);", "refreshTraffic," + NL +
     "                    police ? &r->data[0] : &r->data[1]);"),
    ("fr-damage", S, "                    &r->data[2]);" + NL
     + "    raceSetupBuildMenu(s, r, \"Free Run Setup\");",
     "                    &r->data[1]);" + NL
     + "    raceSetupBuildMenu(s, r, \"Free Run Setup\");"),
    ("fr-name", S, "raceSetupBuildMenu(s, r, \"Free Run Setup\");",
     "raceSetupBuildMenu(s, r, \"Free Run\");"),

    # The knockouts.
    ("ko-load-rk", S, "if (race) raceSetupLoad(s, r, "
     "FRED_RACE_KNOCKOUT_SETUP, 7);", "if (race) raceSetupLoad(s, r, "
     "FRED_RACE_KNOCKOUT_SETUP, 6);"),
    ("ko-load-lk", S, "else raceSetupLoad(s, r, FRED_LAP_KNOCKOUT_SETUP, 6);",
     "else raceSetupLoad(s, r, FRED_LAP_KNOCKOUT_SETUP, 5);"),
    ("ko-police", S, "    if (!police) {" + NL + "        if (cars == 1)",
     "    if (1) {" + NL + "        if (cars == 1)"),
    ("ko-cars", S, "        if (cars == 1)" + NL
     + "            raceSetupAttach(r, 30002",
     "        if (cars >= 1)" + NL + "            raceSetupAttach(r, 30002"),
    ("ko-numopp-value", S, "refreshNumOpponents, &r->data[0]);",
     "refreshNumOpponents, &r->data[1]);"),
    ("ko-type-value", S, "refreshOpponentType, &r->data[1]);",
     "refreshOpponentType, &r->data[2]);"),
    ("ko-catchup", S, "                    &r->data[2]);" + NL
     + "    raceSetupAttach(r, 30006, 30503, maybeChangeTraffic, "
     "refreshTraffic," + NL + "                    police ? &r->data[4]",
     "                    &r->data[3]);" + NL + "    raceSetupAttach(r, "
     "30006, 30503, maybeChangeTraffic, refreshTraffic," + NL
     + "                    police ? &r->data[4]"),
    ("ko-traffic", S, "police ? &r->data[4] : &r->data[3]);",
     "police ? &r->data[3] : &r->data[4]);"),
    ("ko-tracks-race", S, "    if (race)" + NL
     + "        raceSetupAttach(r, 30007", "    if (!race)" + NL
     + "        raceSetupAttach(r, 30007"),
    ("ko-tracks-blurb", S, "raceSetupAttach(r, 30007, 30505,",
     "raceSetupAttach(r, 30007, 30504,"),
    ("ko-tracks-value", S, "refreshTrackSetting, &r->data[5]);",
     "refreshTrackSetting, &r->data[6]);"),
    ("ko-damage", S, "race ? &r->data[6] : &r->data[5]);",
     "race ? &r->data[5] : &r->data[5]);"),
    ("ko-damage-lk", S, "race ? &r->data[6] : &r->data[5]);",
     "race ? &r->data[6] : &r->data[4]);"),
    ("ko-names", S, "race ? \"Knockout Setup\" : \"Lap Knockout Setup\"",
     "race ? \"Lap Knockout Setup\" : \"Knockout Setup\""),

    # The destructors and BaseCallback.
    ("dtor-no-save", S, "    raceSetupSave(s, r, off, n);" + NL
     + "    HOOK0(s, setupRaceParametersAfterRaceSetup);",
     "    HOOK0(s, setupRaceParametersAfterRaceSetup);"),
    ("dtor-no-rp", S, "    HOOK0(s, setupRaceParametersAfterRaceSetup);"
     + NL + "    raceSetupDtor(s, r);", "    raceSetupDtor(s, r);"),
    ("dtor-cars", S, "    HOOK0(s, setupRaceParametersAfterRaceSetup);"
     + NL + "    raceSetupDtor(s, r);", "    HOOK0(s, "
     "setupRaceParametersAfterRaceSetup);" + NL + "    HOOK0(s, "
     "makeChallengeCarsAvailable);" + NL + "    raceSetupDtor(s, r);"),
    ("dtor-sr-n", S, "raceSetupBlockDtor(s, FRED_SINGLE_RACE_SETUP, 7);",
     "raceSetupBlockDtor(s, FRED_SINGLE_RACE_SETUP, 6);"),
    ("dtor-fr-off", S, "raceSetupBlockDtor(s, FRED_FREE_RUN_SETUP, 3);",
     "raceSetupBlockDtor(s, FRED_SINGLE_RACE_SETUP, 3);"),
    ("dtor-lk-n", S, "raceSetupBlockDtor(s, FRED_LAP_KNOCKOUT_SETUP, 6);",
     "raceSetupBlockDtor(s, FRED_LAP_KNOCKOUT_SETUP, 7);"),
    ("dtor-rk-off", S, "raceSetupBlockDtor(s, FRED_RACE_KNOCKOUT_SETUP, 7);",
     "raceSetupBlockDtor(s, FRED_LAP_KNOCKOUT_SETUP, 7);"),
    ("cb-ctor-sr", S, "case BSETUP_RACE_SINGLE: singleRaceCtor(s, screen); "
     "break;", "case BSETUP_RACE_SINGLE: freeRunCtor(s, screen); break;"),
    ("cb-ctor-ko", S, "case BSETUP_RACE_KNOCKOUT: knockoutCtor(s, screen, 1);",
     "case BSETUP_RACE_KNOCKOUT: knockoutCtor(s, screen, 0);"),
    ("cb-kind", S, "            s->race.kind = kind;",
     "            s->race.kind = BSETUP_RACE_BE_THE_COP;"),
    ("cb-dtor-by-callback", S, "            switch (s->race.kind) {",
     "            switch (kind) {"),
    ("cb-fr", S, "raceSetupCallback(gf, msg, data, BSETUP_RACE_FREE_RUN);",
     "raceSetupCallback(gf, msg, data, BSETUP_RACE_SINGLE);"),
    ("cb-lk", S, "raceSetupCallback(gf, msg, data, BSETUP_RACE_LAP_KNOCKOUT);",
     "raceSetupCallback(gf, msg, data, BSETUP_RACE_KNOCKOUT);"),
    ("cb-unactivate-dead", S, "            if (!s->race.live) break;",
     "            (void)0;"),
]

EQUIVALENT = {}


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
        exe = sc.build_harness(tmp, name="racesetups_test")
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
