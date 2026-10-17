#!/usr/bin/env python3
"""Cross-check 3DS Files/source/hudanim.c, the HUD's animations, against
the retail image, SLES_507.31.

**The model** is retail's own: HudAnimator's constructor (0x0023b0f8),
its three StartAnimation (0x0023b1e0, 0x0023b498, 0x0023b5e0), both
DoAnimation (0x0023b788, 0x0023bb58) and FinishAnimation (0x0023bf60);
Player::ClearHudAnimations (0x0017c7c8), HudStartWrongWay (0x0017c888),
HudStartGrowAnimation (0x0017cb18), HudStartSpeedAnimation (0x0017cd30),
the text's and the bitmap's HudStartAnimation (0x0017cfb8, 0x0017d130),
HudDoAnimations (0x0017e038) and AddToTotalScore (0x0017e350); and under
them ConvertScoreString, bSPrintf, bStrToLong, bStrNCmp,
RaceParameters::IsFreeRun and the whole Flailer runtime on INGAMEB's
Flailer chunk, loaded as tools/flailer_check.py does. The harness
(tools/src/hudanim_test.c) runs hudanim.c over hudrender.c (for
ConvertScoreString), flailer.c, bprintf.c, bui.c, raceparams.c and the
rest hudrender.c links, on the same bundle.

**The stubs** are bMalloc (0x00257690), which hands out 288 bytes holding
a pattern by offset (each word 0x3f800000 plus sixteen times its offset)
and a dummy object in the two object pointers, so a field the constructor
or a start leaves alone shows as the heap's on both sides; and
flailer_check.py's text and bitmap sizes.

**Compared** are DoAnimation's answers and, after each op, every line that
changed: each Player's twenty animation slots (the animator's allocation
number, its 288 bytes in retail's order with the two object pointers by
name), TotalScore, and every Flailer object's bytes.

**The script** starts each animation and runs it frame by frame past its
end: the race position's grow and shrink with and without the position on
the HUD, the speed's with and without a speed string and a gauge, simple
texts and bitmaps in every slot (running, restarted, kept, finished),
WRONG WAY in a race, a free run, with the live split, and in both halves
of a two-player race, scored texts through their three phases on both
timers with their own string and the caller's, a phase and a type out of
range, ClearHudAnimations over every slot, and AddToTotalScore's strings.

    python tools/hudanim_check.py
    python tools/hudanim_check.py --mutate [--only a,b]
    python tools/hudanim_check.py --dump out/hudanim
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
import hudfeatures_check as hc          # noqa: E402
import physicscar_check as pcc          # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/hudanim_test.c"
HUDANIM = "3DS Files/source/hudanim.c"
SOURCES = [HARNESS, HUDANIM, "3DS Files/source/hudrender.c",
           "3DS Files/source/racesplit.c", "3DS Files/source/timer.c",
           "3DS Files/source/playerhud.c", "3DS Files/source/flailer.c",
           "3DS Files/source/bprintf.c", "3DS Files/source/bui.c",
           "3DS Files/source/bchunk.c", "3DS Files/source/copmanager.c",
           "3DS Files/source/replay.c", "3DS Files/source/p32.c",
           "3DS Files/source/raceparams.c"]

GP = fc.GP
RP = hc.RP                              # TheRaceParameters
G_NUM = hc.G_NUM                        # Player::NumPlayers
G_TIMER = GP - 19576                    # WorldTimer
G_REAL = GP - 19608                     # RealTimer

F_OBJECT = fc.F_OBJECT
F_SET_ALPHA = 0x00140ed0                # FlailerTextChunk::SetAlpha
F_MALLOC = 0x00257690                   # bMalloc(int, int)
F_CTOR = 0x0023b0f8
F_SCORED = 0x0023b1e0
F_DO = 0x0023b788
F_DO_SCORED = 0x0023bb58
F_FINISH = 0x0023bf60
F_CLEAR = 0x0017c7c8
F_WRONG = 0x0017c888
F_GROW = 0x0017cb18
F_SPEED = 0x0017cd30
F_TEXT = 0x0017cfb8
F_BITMAP = 0x0017d130
F_DO_ALL = 0x0017e038
F_ADD = 0x0017e350

PLAYER_SIZE = 2752
ANIM_SIZE = 288
NUM_SLOTS = 20
ANIMS = 1540                            # Player::pHudAnimations
TOTAL = 1524                            # Player::TotalScore
PLAYER_WORDS = {"PN": 16, "chf": 768, "screen": 772, "score": TOTAL}
PLAYER_OBJECTS = {"speedstr": 1032, "scoretotal": 1156}
PLAYER_STRINGS = {"evtitle": 1412, "evscore": 1444, "prevscore": 1476}
RP_WORDS = {"RaceType": 32, "Laps": 44, "BeACop": 628}

HUD_SINGLE = hc.HUD_SINGLE
HUD_GAUGES = 0x20
HUD_GAUGES_OUTSIDE = 0x40
HUD_RACE_POSITION = 0x200
HUD_LIVE_SPLIT = 0x800000
ALL = 0x0fffffff

# The HUD screen's objects.
SPD = "t:0x31f74338"                    # pFlailerSpeedString
SPD2 = "t:0x8cd4fda9"                   # pFlailerSpeedString2
BIG = "t:0x004e27a0"                    # pFlailerBigRacePosition
BIG2 = "t:0x4c769c11"                   # pFlailerBigRacePosition2
EVT = "t:0xa3ff1482"                    # pFlailerEventTitle
EVS = "t:0xa3e99d3c"                    # pFlailerEventScore
SCT = "t:0x5d8266dc"                    # pFlailerScoreTitle
SCO = "t:0x5d85afbe"                    # pFlailerScoreTotal
LAP = "t:0xfc1b498a"                    # pFlailerLapTime
WW = "b:0x89af1a1e"                     # WRONG WAY
NEEDLE = "b:0x8d28acce"                 # pFlailerSpeedNeedle

TICKS = 4000                            # WorldTimer's, a second
T0 = 400000


def fbits(v):
    return struct.unpack("<I", struct.pack("<f", v))[0]


def F(v):
    return "%#x" % fbits(v)


def pattern(o):
    return (0x3f800000 + o * 16) & M32


# ================================================================== script

def common():
    s = ["load|%s" % (fc.SD / "GLOBAL/INGAMEB.BUN"), "g|np|1",
         "g|timer|%d" % T0, "g|real|123457", "rp|RaceType|2", "rp|Laps|3"]
    for k in (1, 0):
        s += ["use|%d" % k, "pl|%d|PN|%d" % (k, k),
              "pl|%d|screen|%#x" % (k, HUD_SINGLE), "pl|%d|chf|%#x" % (k, ALL),
              "pl|%d|speedstr|%s" % (k, SPD), "pl|%d|scoretotal|%s" % (k, SCO),
              "pl|%d|evscore|+1500" % k, "pl|%d|evtitle|NEAR MISS" % k,
              "pl|%d|prevscore|-250" % k, "pl|%d|score|1000" % k]
    return s


def pos(o, x, y, sx=1.0, sy=1.0):
    return "pos|%s|%s|%s|%s|%s" % (o, F(x), F(y), F(sx), F(sy))


def frames(t, *dts, op="do"):
    """WorldTimer at t + each dt, and `op` at each."""
    s = []
    for dt in dts:
        s += ["g|timer|%d" % (t + dt), op]
    return s


def text(slot, o, frm, to, sf, st, af, at, dur, t=0):
    return "text|%d|%s|%s|%s|%s|%s|%d|%d|%s|%d" % (
        slot, o, "|".join(F(v) for v in frm), "|".join(F(v) for v in to),
        "|".join(F(v) for v in sf), "|".join(F(v) for v in st), af, at,
        F(dur), t)


def bitmap(slot, o, frm, to, sf, st, af, at, dur, keep, t=0):
    return "bitmap" + text(slot, o, frm, to, sf, st, af, at, dur, t)[4:] \
        + "|%d" % keep


def scored(slot, o, pos_, dpos, dpos2, scale, dscale, alpha, dalpha, colour,
           scale1, dscale2, alpha1, dalpha2, dcolour, d, s, real=0):
    v = lambda vs: "|".join(F(x) for x in vs)      # noqa: E731
    return ("scored|%d|%s|%s|%s|%s|%s|%s|%d|%s|%s|%s|%s|%d|%s|%s|%s|%s|%d"
            % (slot, o, v(pos_), v(dpos), v(dpos2), v(scale), v(dscale),
               alpha, F(dalpha), v(colour), v(scale1), v(dscale2), alpha1,
               F(dalpha2), v(dcolour), v(d), s, real))


def s_grow():
    t = T0
    s = [pos(BIG2, 321.75, 119.5, 1.25, 0.75), "alpha|%s|100" % BIG2,
         "g|timer|%d" % t, "grow|%s|%s|%d|1" % (BIG, BIG2, t)]
    s += frames(t, 0, 100, 400, 1000, 1999, 2000, 2400)
    # Without the race position on the HUD slot 0 stands still.
    t += 10000
    s += ["g|timer|%d" % t, "grow|%s|%s|%d|1" % (BIG, BIG2, t),
          "pl|0|chf|%#x" % (ALL & ~HUD_RACE_POSITION)]
    s += frames(t, 300, 2500)
    s += ["pl|0|chf|%#x" % HUD_RACE_POSITION]
    s += frames(t, 2600)
    # The shrink: down 100, faded in from nothing over a second, from a
    # place left of the origin.
    t += 10000
    s += [pos(BIG2, -17.75, -0.5, 2.0, 2.0), "alpha|%s|255" % BIG2,
          "g|timer|%d" % t, "grow|%s|%s|%d|0" % (BIG, BIG2, t)]
    s += frames(t, 0, 1, 1000, 2000, 3999, 4000, 4001)
    # A restart while running starts over.
    t += 10000
    s += ["alpha|%s|0" % BIG2, "g|timer|%d" % t,
          "grow|%s|%s|%d|1" % (BIG, BIG2, t)]
    s += frames(t, 500)
    s += ["grow|%s|%s|%d|0" % (BIG, BIG2, t)]
    s += frames(t, 1000, 3000, 5000, -1000)
    s += ["pl|0|chf|%#x" % ALL]
    return s


def s_speed():
    t = T0 + 50000
    s = ["pl|0|speedstr|none", "g|timer|%d" % t,
         "speed|%s|%s|%d|1" % (SPD2, SPD, t), "pl|0|speedstr|%s" % SPD,
         pos(SPD, 63.5, 200.25, 1.5, 0.5), "alpha|%s|128" % SPD,
         "speed|%s|%s|%d|1" % (SPD2, SPD, t), "pl|0|chf|%#x" % HUD_GAUGES]
    s += frames(t, 0, 800, 2000, 3999, 4000, 4100)
    t += 10000
    s += [pos(SPD, -3.0, 9.75, 0.75, 1.0), "g|timer|%d" % t,
          "speed|%s|%s|%d|0" % (SPD2, SPD, t),
          "pl|0|chf|%#x" % HUD_GAUGES_OUTSIDE]
    s += frames(t, 1200)
    s += ["pl|0|chf|%#x" % (ALL & ~(HUD_GAUGES | HUD_GAUGES_OUTSIDE))]
    s += frames(t, 2400)
    s += ["pl|0|chf|%#x" % ALL]
    s += frames(t, 2400, 4000)
    # Its own speed string need not be the one it grows from.
    t += 10000
    s += [pos(LAP, 400.5, 30.0, 1.0, 1.0), "g|timer|%d" % t,
          "speed|%s|%s|%d|1" % (SPD2, LAP, t)]
    s += frames(t, 2000)
    return s


def s_text():
    t = T0 + 100000
    s = ["g|timer|%d" % t]
    # Every slot HudDoAnimations runs, and those it does not.
    for slot in (2, 5, 8, 9, 14, 16, 17, 18, 19):
        s.append(text(slot, EVT, (10.0 + slot, 20.5), (-30.25, 100.0 - slot),
                      (1.0, 1.0), (0.5, 3.0), 200, 20 + slot, 0.25 * slot, t))
    s += frames(t, 0, 333, 1000, 2000, 4000, 9000, 20000, 40000)
    # Restarted while running, from a fainter start up to past 255.
    t += 50000
    s += ["g|timer|%d" % t,
          text(3, SCT, (0.0, 0.0), (64.0, -64.0), (2.0, 2.0), (2.0, 2.0),
               10, 300, 2.0, t)]
    s += frames(t, 1000)
    s += [text(3, SCT, (5.5, -5.5), (5.5, -5.5), (1.0, 2.0), (3.0, 0.25),
               255, 0, 0.5, t)]
    s += frames(t, 1500, 1700, 3000, 3001)
    # A clock gone backwards runs the line backwards.
    t += 10000
    s += ["g|timer|%d" % t,
          text(4, EVT, (100.0, 100.0), (150.0, 50.0), (1.0, 1.0),
               (0.5, 0.5), 128, 0, 1.0, t)]
    s += frames(t, -2000, -1, 0)
    return s


def s_bitmap():
    t = T0 + 200000
    s = ["g|timer|%d" % t, pos(NEEDLE, 1.0, 2.0),
         bitmap(16, NEEDLE, (40.5, 60.25), (80.0, 20.0), (1.0, 1.0),
                (0.25, 4.0), 128, 0, 1.5, 0, t)]
    s += frames(t, 0, 1000, 3000)
    # A start while running only makes the type simple.
    s += ["an|16|272|3",
          bitmap(16, NEEDLE, (0.0, 0.0), (1.0, 1.0), (1.0, 1.0), (1.0, 1.0),
                 1, 2, 9.0, 1, t)]
    s += frames(t, 5999, 6000, 6001)
    # Kept up at the end.
    t += 10000
    s += ["g|timer|%d" % t,
          bitmap(17, NEEDLE, (-9.75, 3.5), (12.0, -40.0), (2.0, 1.0),
                 (1.0, 2.0), 0, 255, 0.75, 1, t)]
    s += frames(t, 1500, 3000, 3001)
    # Restarted after the end.
    s += [bitmap(17, NEEDLE, (1.0, 1.0), (2.0, 2.0), (1.0, 1.0), (1.0, 1.0),
                 64, 32, 0.5, 0, t + 3001)]
    s += frames(t, 4000, 5001)
    return s


def s_wrong():
    t = T0 + 300000
    s = ["g|timer|%d" % t, "wrong"]
    s += frames(t, 0, 1000, 3999, 4000)
    # Still kept up, and a start while running is ignored.
    s += ["wrong"]
    s += frames(t, 5000)
    # A free run.
    t += 10000
    s += ["finish|15", "rp|RaceType|1", "rp|Laps|0", "g|timer|%d" % t,
          "wrong"]
    s += frames(t, 2000)
    # The live split without the race position, in a free run and not.
    s += ["finish|15", "pl|0|chf|%#x" % HUD_LIVE_SPLIT, "wrong"]
    s += frames(t, 2000)
    s += ["finish|15", "rp|Laps|3", "wrong"]
    s += frames(t, 2000)
    s += ["finish|15", "pl|0|chf|%#x" % (HUD_LIVE_SPLIT | HUD_RACE_POSITION),
          "wrong"]
    s += frames(t, 2000)
    s += ["pl|0|chf|%#x" % ALL]
    # Two players: each half its own place, and a third number neither.
    s += ["g|np|2"]
    for k, pn in ((0, 0), (1, 1), (0, 5)):
        s += ["use|%d" % k, "pl|%d|PN|%d" % (k, pn), "finish|15", "wrong"]
        s += frames(t, 3000)
    s += ["finish|15", "pl|0|PN|0", "use|1", "finish|15", "use|0",
          "g|np|1", "rp|RaceType|2"]
    return s


WHITE = (128.0, 128.0, 128.0, 128.0)


def s_scored():
    t = T0 + 400000
    s = ["g|timer|%d" % t, "new|10",
         scored(10, EVS, (200.5, 300.25), (-50.0, -100.0), (0.0, -40.5),
                (0.5, 0.5), (1.5, 1.0), 0, 128.0, (128.0, 64.0, 0.0, 0.0),
                (2.0, 1.5), (-1.0, -1.25), 128, -128.0,
                (0.0, 64.0, 128.0, 128.0), (0.5, 1.0, 0.5), "-")]
    # Phase 0 to its end, which moves to phase 1 on its own clock; then
    # phase 1 and phase 2, whose end adds strEventScore to the total.
    s += frames(t, 0, 1000, 1999, 2000, 2500, 5999, 6000, 7000, 7999, 8000,
                9000)
    # Its own string; phases ended a frame late carry the lateness on.
    t += 20000
    s += ["g|timer|%d" % t,
          scored(10, EVS, (10.0, 10.0), (5.0, 5.0), (5.0, 5.0), (1.0, 1.0),
                 (0.0, 0.0), 255, -255.0, WHITE, (1.0, 1.0), (0.0, 0.0), 255,
                 -100.0, (0.0, 0.0, 0.0, 0.0), (0.25, 0.25, 0.25), "-777")]
    s += frames(t, 1500, 1600, 3000, 4000, 4100)
    # The other three: the title, "SCORE" and "", on RealTimer's start.
    t += 20000
    s += ["g|timer|%d" % t, "g|real|%d" % (t - 2000)]
    for slot, o in ((11, EVT), (12, SCT), (13, SCO)):
        s += ["new|%d" % slot,
              scored(slot, o, (100.0, 50.0 + slot), (0.0, 10.0),
                     (20.0, 0.0), (1.0, 1.0), (0.25, 0.25), 64, 64.0,
                     (100.0, 100.0, 100.0, 0.0), (1.25, 1.25), (-1.0, -1.0),
                     128, -128.0, (28.0, 28.0, 28.0, 0.0), (1.0, 0.5, 1.0),
                     "-", slot & 1)]
    s += frames(t, 0, 2000, 5000, 7000, 9000, 11000, 15000)
    # A phase out of range starts over, unscaled by any duration.
    t += 20000
    s += ["g|timer|%d" % t,
          scored(10, EVS, (0.0, 0.0), (100.0, 100.0), (10.0, 10.0),
                 (1.0, 1.0), (1.0, 1.0), 0, 255.0, WHITE, (1.0, 1.0),
                 (1.0, 1.0), 255, -255.0, WHITE, (4.0, 4.0, 4.0), "+9")]
    s += frames(t, 200)
    s += ["an|10|256|5"]
    s += frames(t, 400)
    s += ["an|10|256|0xffffffff"]
    s += frames(t, 600, 16000)
    s += ["an|10|256|3", "g|timer|%d" % (t + 3000), "do", "an|10|256|2"]
    s += frames(t, 24000, 28000)
    # The wrong type does nothing, in either DoAnimation.
    s += [scored(10, EVS, (1.0, 1.0), (1.0, 1.0), (1.0, 1.0), (1.0, 1.0),
                 (1.0, 1.0), 1, 1.0, WHITE, (1.0, 1.0), (1.0, 1.0), 1, 1.0,
                 WHITE, (1.0, 1.0, 1.0), "+1"), "an|10|272|1"]
    s += frames(t, 29000)
    s += frames(t, 29500, op="do1|10")
    s += ["an|10|272|3", "an|11|272|3"]
    s += frames(t, 29500, op="do1|11")
    # No text: nothing drawn, and no end.
    t += 40000
    s += ["g|timer|%d" % t,
          scored(13, "none", (0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (1.0, 1.0),
                 (0.0, 0.0), 0, 0.0, WHITE, (1.0, 1.0), (0.0, 0.0), 0, 0.0,
                 WHITE, (0.25, 0.25, 0.25), "none")]
    s += frames(t, 2000, 4000, 8000)
    # Called directly, on a timer of its own and the caller's string.
    s += [scored(11, EVT, (3.0, 4.0), (5.0, 6.0), (7.0, 8.0), (1.0, 1.0),
                 (0.5, 0.5), 9, 10.0, (11.0, 12.0, 13.0, 14.0), (1.5, 1.5),
                 (0.5, 0.5), 15, 16.0, (17.0, 18.0, 19.0, 20.0),
                 (0.5, 0.5, 0.5), "-", 1)]
    for dt, st in ((0, "a"), (2000, "bb"), (4000, ""), (6000, "dddd"),
                   (6001, "e")):
        s.append("doscored|11|%d|%s" % (t + dt, st))
    # WorldTimer's start, run on times of the caller's while WorldTimer
    # stands still: x and y apart, and three phases of their own lengths.
    s += ["g|timer|%d" % t,
          scored(12, SCT, (30.0, 40.0), (10.0, -20.0), (-5.0, 15.0),
                 (0.5, 0.8), (0.25, -0.3), 20, 100.0,
                 (10.0, 20.0, 30.0, 40.0), (1.1, 0.9), (0.2, 0.4), 120,
                 -100.0, (5.0, 6.0, 7.0, 8.0), (0.25, 0.5, 0.75), "-")]
    for dt in (500, 1000, 2000, 3000, 4000, 5000, 6000):
        s.append("doscored|12|%d|x" % (t + dt))
    # Running, but a blink or no type at all.
    for ty in (2, 0):
        s += ["an|12|260|1", "an|12|272|%d" % ty,
              "doscored|12|%d|x" % (t + 500)]
    # The text-less one above answers 0 however late.
    s += ["doscored|13|%d|x" % (t + 99000)]
    return s


def s_finish():
    t = T0 + 500000
    s = ["g|timer|%d" % t,
         text(2, EVT, (1.0, 2.0), (3.0, 4.0), (1.0, 1.0), (2.0, 2.0), 10,
              20, 1.0, t), "finish|2", "finish|2",
         "g|timer|%d" % (t + 500), "do1|2", "g|timer|%d" % t,
         bitmap(6, NEEDLE, (5.5, 6.5), (-7.25, 8.0), (1.0, 1.0),
                (0.5, 0.25), 30, 230, 1.0, 0, t), "finish|6",
         bitmap(7, WW, (-3.5, 2.25), (40.0, 9.5), (1.5, 0.75),
                (0.5, 2.0), 100, 20, 1.0, 1, t), "finish|7",
         bitmap(16, NEEDLE, (5.5, 6.5), (-7.25, 8.0), (1.0, 1.0),
                (0.5, 0.5), 30, 230, 1.0, 0, t), "finish|16",
         bitmap(17, WW, (5.5, 6.5), (-7.25, 8.0), (1.0, 1.0),
                (0.5, 0.5), 30, 20, 1.0, 1, t), "finish|17",
         # A blink's bitmap at its first alpha.
         "an|17|272|2", "an|17|172|%s" % F(77.9), "finish|17",
         "an|17|172|%s" % F(-3.5), "finish|17",
         scored(10, EVS, (0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (1.0, 1.0),
                (0.0, 0.0), 0, 0.0, WHITE, (1.0, 1.0), (0.0, 0.0), 0, 0.0,
                WHITE, (1.0, 1.0, 1.0), "+1"), "finish|10",
         # A fresh one, and a simple one with nothing to move.
         "new|9", "finish|9", "an|9|272|1", "finish|9", "an|9|272|7",
         "finish|9",
         # A running blink is no simple animation.
         "an|17|260|1", "do1|17",
         # A bitmap started on a text's animator: the text comes first.
         bitmap(2, NEEDLE, (9.0, 9.0), (19.0, 29.0), (1.0, 1.0), (2.0, 2.0),
                40, 80, 1.0, 0, t), "g|timer|%d" % (t + 2000), "do1|2",
         "finish|2", "g|timer|%d" % t]
    return s


def s_clear():
    t = T0 + 600000
    s = ["g|timer|%d" % t,
         "grow|%s|%s|%d|1" % (BIG, BIG2, t),
         "speed|%s|%s|%d|1" % (SPD2, SPD, t)]
    for slot in (2, 14, 18, 19):
        s.append(text(slot, LAP, (1.0, 1.0), (2.0, 2.0), (1.0, 1.0),
                      (1.0, 1.0), 1, 2, 5.0, t))
    s += ["finish|15", "wrong",
          bitmap(16, NEEDLE, (5.0, 5.0), (6.0, 6.0), (1.0, 1.0), (1.0, 1.0),
                 1, 2, 5.0, 0, t)]
    for slot, o in ((10, EVS), (11, EVT), (12, SCT), (13, SCO)):
        s.append(scored(slot, o, (1.0, 1.0), (2.0, 2.0), (3.0, 3.0),
                        (1.0, 1.0), (0.0, 0.0), 1, 2.0, WHITE, (1.0, 1.0),
                        (0.0, 0.0), 3, 4.0, WHITE, (5.0, 5.0, 5.0), "-"))
    s += frames(t, 1000)
    # A running score counts strPrevScore in; 12 to 14 and 18 run on.
    s += ["clear", "clear"]
    s += frames(t, 2000)
    # A running score with no text to hide is still stopped.
    s += [scored(10, "none", (1.0, 1.0), (2.0, 2.0), (3.0, 3.0), (1.0, 1.0),
                 (0.0, 0.0), 1, 2.0, WHITE, (1.0, 1.0), (0.0, 0.0), 3, 4.0,
                 WHITE, (5.0, 5.0, 5.0), "-"), "clear", "clear"]
    # Player 1's own, from nothing.
    s += ["use|1", "clear", "grow|%s|%s|%d|0" % (BIG, BIG2, t), "clear",
          "use|0"]
    return s


def s_add():
    s = ["pl|0|score|1000"]
    for v in ("+250", "-5000", "+40", "abc", "", "-", "+", "12x5", "-0",
              "007", " 5", "2147483647", "+1", "-2147483648", "99999999999",
              "-99999999999"):
        s.append("add|%s" % v)
    s += ["pl|0|score|-50", "add|+10", "pl|0|scoretotal|none", "add|+5",
          "pl|0|scoretotal|%s" % SCO, "use|1", "add|-1", "add|+77",
          "use|0"]
    return s


def script():
    s = common()
    s += s_grow()
    s += s_speed()
    s += s_text()
    s += s_bitmap()
    s += s_wrong()
    s += s_scored()
    s += s_finish()
    s += s_clear()
    s += s_add()
    return s


# =================================================================== model

class Model(fc.Model):
    note = hc.Model.note
    dump_objects = hc.Model.dump_objects

    def __init__(self):
        fc.Model.__init__(self)
        e = self.e
        self.lines = {}
        e.write(RP, bytes(788))
        for g in (G_NUM, G_TIMER, G_REAL):
            e.put32(g, 0)
        self.dummy = e.alloc(256)
        self.players = [e.alloc(PLAYER_SIZE) for _ in range(2)]
        self.cur_player = 0
        self.allocs = []
        self.vecs = e.alloc(256, align=16)
        self.sbuf = e.alloc(64, align=16)
        self.tbuf = e.alloc(16, align=16)
        e.stub(F_MALLOC, self.s_malloc)

    def s_malloc(self, em):
        e = self.e
        size = s32(em.reg[4])
        if size != ANIM_SIZE:
            raise SystemExit("bad malloc %d" % size)
        a = e.alloc(size, align=16)
        for o in range(0, size, 4):
            e.put32(a + o, pattern(o))
        e.put32(a + 72, self.dummy)
        e.put32(a + 76, self.dummy)
        self.allocs.append(a)
        return a

    # ---- output

    def name(self, a):
        if a == 0:
            return "none"
        return self.obj_at.get(a, "stray")

    def dump(self):
        e = self.e
        mem = e.mem
        for n, p in enumerate(self.players):
            for i in range(NUM_SLOTS):
                a = e.u32(p + ANIMS + 4 * i)
                key = "p%d.anim[%d]" % (n, i)
                if a == 0:
                    self.note(key, "none")
                    continue
                k = self.allocs.index(a) if a in self.allocs else -1
                self.note(key, "a%d %s %s %s %s" % (
                    k, bytes(mem[a:a + 72]).hex(), self.name(e.u32(a + 72)),
                    self.name(e.u32(a + 76)),
                    bytes(mem[a + 80:a + ANIM_SIZE]).hex()))
            self.note("p%d.TotalScore" % n, "%08x" % e.u32(p + TOTAL))
        self.dump_objects()

    # ---- ops

    def player(self):
        return self.players[self.cur_player]

    def obj(self, s):
        screen = self.e.u32(self.player() + 772)
        for prefix, kind in (("t:", 1), ("b:", 2)):
            if s.startswith(prefix):
                return self.e.call(F_OBJECT, s32(screen), s32(int(s[2:], 0)),
                                   kind, limit=200000) & M32
        return 0

    def vec(self, at, vals):
        for i, v in enumerate(vals):
            self.e.put32(at + 4 * i, int(v, 0))
        return at

    def string(self, s, at=None):
        a = self.sbuf if at is None else at
        self.e.write(a, s.encode("latin-1") + b"\0")
        return a

    def slot(self, i):
        a = self.e.u32(self.player() + ANIMS + 4 * int(i, 0))
        if a == 0:
            self.emit("  no anim")
        return a

    def set_player(self, k, n, a):
        e = self.e
        p = self.players[k]
        if n in PLAYER_WORDS:
            e.put32(p + PLAYER_WORDS[n], int(a[0], 0))
        elif n in PLAYER_OBJECTS:
            e.put32(p + PLAYER_OBJECTS[n], self.obj(a[0]))
        elif n in PLAYER_STRINGS:
            v = a[0].encode("latin-1")[:31] if a else b""
            e.write(p + PLAYER_STRINGS[n], v.ljust(32, b"\0"))
        else:
            raise ValueError(n)

    def op(self, a):
        e = self.e
        o = a[0]
        if o == "load":
            self.load(a[1])
            return
        p = self.player()
        v = lambda i: int(a[i], 0) & M32      # noqa: E731
        sp = e.reg[29] & M32
        if o == "rp":
            e.put32(RP + RP_WORDS[a[1]], v(2))
        elif o == "g":
            e.put32({"np": G_NUM, "timer": G_TIMER, "real": G_REAL}[a[1]],
                    v(2))
        elif o == "use":
            self.cur_player = int(a[1])
        elif o == "pl":
            self.set_player(int(a[1]), a[2], a[3:])
        elif o == "pos":
            self.vec(self.obj(a[1]) + 48, a[2:6])
        elif o == "alpha":
            e.call(F_SET_ALPHA, self.obj(a[1]), v(2), limit=100000)
        elif o in ("grow", "speed"):
            e.call(F_GROW if o == "grow" else F_SPEED, p, self.obj(a[1]),
                   self.obj(a[2]), v(3), v(4), limit=1000000)
        elif o in ("text", "bitmap"):
            vf = self.vec(self.vecs, a[3:5])
            vt = self.vec(self.vecs + 16, a[5:7])
            vsf = self.vec(self.vecs + 32, a[7:9])
            vst = self.vec(self.vecs + 48, a[9:11])
            e.put32(sp, v(12))
            e.put32(sp + 8, v(14))
            if o == "bitmap":
                e.put32(sp + 16, v(15))
            e.fpr[12] = v(13)
            e.call(F_TEXT if o == "text" else F_BITMAP, p, int(a[1], 0),
                   self.obj(a[2]), vf, vt, vsf, vst, v(11), limit=1000000)
        elif o == "wrong":
            e.call(F_WRONG, p, limit=1000000)
        elif o == "clear":
            e.call(F_CLEAR, p, limit=1000000)
        elif o == "do":
            e.call(F_DO_ALL, p, limit=1000000)
        elif o == "add":
            e.call(F_ADD, p, self.string(a[1] if len(a) > 1 else ""),
                   limit=1000000)
        elif o == "new":
            at = p + ANIMS + 4 * int(a[1], 0)
            if e.u32(at) == 0:
                an = e.call(F_MALLOC, ANIM_SIZE, 16) & M32
                e.put32(at, e.call(F_CTOR, an, limit=10000) & M32)
        elif o == "scored":
            an = self.slot(a[1])
            if an == 0:
                return
            w = self.vecs
            vecs = [self.vec(w + 16 * i, a[k:k + 2])
                    for i, k in enumerate((3, 5, 7, 9, 11, 19, 21))]
            colour = self.vec(w + 128, a[15:19])
            dcolour = self.vec(w + 144, a[25:29])
            s = 0 if a[32] == "-" else self.string(a[32])
            for i, x in enumerate((colour, vecs[5], vecs[6], v(23), dcolour,
                                   s, v(33))):
                e.put32(sp + 8 * i, x)
            for r, k in ((12, 14), (13, 24), (14, 29), (15, 30), (16, 31)):
                e.fpr[r] = v(k)
            e.call(F_SCORED, an, self.obj(a[2]), *(vecs[:5] + [v(13)]),
                   limit=1000000)
        elif o == "doscored":
            an = self.slot(a[1])
            if an == 0:
                return
            e.put32(self.tbuf, v(2))
            r = e.call(F_DO_SCORED, an, self.tbuf,
                       self.string(a[3] if len(a) > 3 else ""),
                       limit=1000000)
            self.emit("  = %d" % r)
        elif o == "do1":
            an = self.slot(a[1])
            if an == 0:
                return
            self.emit("  = %d" % e.call(F_DO, an, e.u32(G_TIMER),
                                        limit=1000000))
        elif o == "finish":
            an = self.slot(a[1])
            if an == 0:
                return
            e.call(F_FINISH, an, limit=1000000)
        elif o == "an":
            an = self.slot(a[1])
            if an == 0:
                return
            e.put32(an + int(a[2], 0), v(3))
        else:
            raise ValueError(o)
        self.dump()


def model(lines):
    return Model().run(lines)


# ================================================================= build

def build_harness(tmp, name="hudanim_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


run_harness = fc.run_harness
diff = pcc.diff
write_script = fc.write_script


# ============================================================= mutations

H = HUDANIM


def M(name, before, after, rel=H):
    return (name, rel, before, after)


MUTATIONS = [
    # The helpers.
    M("place-x-untruncated", "o->X = (float)ee_trunc_w(pos->x);",
      "o->X = pos->x;"),
    M("place-y-untruncated", "o->Y = (float)ee_trunc_w(pos->y);",
      "o->Y = pos->y;"),
    M("place-scale-swapped", "o->ScaleX = scale->x;", "o->ScaleX = scale->y;"),
    M("colour-g-shift", "| (uint32_t)ee_trunc_w(c->y) << 8",
      "| (uint32_t)ee_trunc_w(c->y) << 9"),
    M("colour-b-shift", "| (uint32_t)ee_trunc_w(c->z) << 16;",
      "| (uint32_t)ee_trunc_w(c->z) << 17;"),
    M("colour-r-from-g", "return (uint32_t)ee_trunc_w(c->x)",
      "return (uint32_t)ee_trunc_w(c->y)"),
    M("lerp-x-no-t", "out->x = d->x * t + from->x;", "out->x = d->x + from->x;"),
    M("lerp-y-from-d", "out->y = d->y * t + from->y;", "out->y = d->y * t;"),
    M("lerp-z-from-x", "out->z = d->z * t + from->z;",
      "out->z = d->z * t + from->x;"),
    M("lerp-w-dropped", "out->w = d->w * t + from->w;", "out->w = 0.0f;"),
    M("add-x-only-a", "out->x = a->x + b->x;", "out->x = a->x;"),
    M("add-y-only-b", "out->y = a->y + b->y;", "out->y = b->y;"),
    M("add-z-only-b", "out->z = a->z + b->z;", "out->z = b->z;"),
    M("tick-seconds", "#define TICK_SECONDS 0.00025f",
      "#define TICK_SECONDS 0.0002501f"),

    # The constructor.
    M("init-no-new68", "    a->New68 = 0;\n    a->Type = 0;", "    a->Type = 0;"),
    M("init-no-type", "    a->Type = 0;\n    a->pText = NULL;",
      "    a->pText = NULL;"),
    M("init-no-text", "    a->pText = NULL;\n    a->pBitmap = NULL;\n    a->bHasString",
      "    a->pBitmap = NULL;\n    a->bHasString"),
    M("init-no-bitmap", "    a->pBitmap = NULL;\n    a->bHasString = 0;\n    a->bActive",
      "    a->bHasString = 0;\n    a->bActive"),
    M("init-no-has-string", "    a->bHasString = 0;\n    a->bActive = 0;\n    a->bKeepVisible",
      "    a->bActive = 0;\n    a->bKeepVisible"),
    M("init-no-active", "    a->bActive = 0;\n    a->bKeepVisible = 0;\n    a->Colour.x",
      "    a->bKeepVisible = 0;\n    a->Colour.x"),
    M("init-no-keep", "    a->bKeepVisible = 0;\n    a->Colour.x",
      "    a->Colour.x"),
    M("init-colour-x", "    a->Colour.x = 128.0f;\n    a->Colour.y = 64.0f;\n    a->Colour.z = 0.0f;\n    a->Colour.w = 0.0f;\n    memset",
      "    a->Colour.x = 127.0f;\n    a->Colour.y = 64.0f;\n    a->Colour.z = 0.0f;\n    a->Colour.w = 0.0f;\n    memset"),
    M("init-colour-y", "    a->Colour.y = 64.0f;\n    a->Colour.z = 0.0f;\n    a->Colour.w = 0.0f;\n    memset",
      "    a->Colour.y = 0.0f;\n    a->Colour.z = 0.0f;\n    a->Colour.w = 0.0f;\n    memset"),
    M("init-colour-w", "    a->Colour.w = 0.0f;\n    memset",
      "    a->Colour.w = 1.0f;\n    memset"),
    M("init-no-dcolour", "    memset(&a->DeltaColour, 0, sizeof a->DeltaColour);\n", ""),
    M("init-no-real-timer", "    a->bRealTimer = 0;\n}", "}"),
    M("new-no-init", "    hudanim_init(a);\n    return a;", "    return a;"),

    # The scored start.
    M("sc-type", "    a->Type = HUDANIM_SCORED;\n    a->Phase = 0;",
      "    a->Type = HUDANIM_SIMPLE;\n    a->Phase = 0;"),
    M("sc-no-phase", "    a->Type = HUDANIM_SCORED;\n    a->Phase = 0;",
      "    a->Type = HUDANIM_SCORED;"),
    M("sc-has-string-0", "        a->bHasString = 1;", "        a->bHasString = 0;"),
    M("sc-null-has-string", "        a->bHasString = 0;\n        a->String[0] = '\\0';",
      "        a->bHasString = 1;\n        a->String[0] = '\\0';"),
    M("sc-null-keeps-string", "        a->bHasString = 0;\n        a->String[0] = '\\0';",
      "        a->bHasString = 0;"),
    M("sc-string-short", 'b_snprintf(a->String, sizeof a->String, "%s", s);',
      'b_snprintf(a->String, 3, "%s", s);'),
    M("sc-pos-dpos", "    a->Pos = *pos;\n    a->DeltaPos = *dpos;\n    a->Alpha = alpha;",
      "    a->Pos = *dpos;\n    a->DeltaPos = *dpos;\n    a->Alpha = alpha;"),
    M("sc-dpos-dpos2", "    a->DeltaPos = *dpos;\n    a->Alpha = alpha;",
      "    a->DeltaPos = *dpos2;\n    a->Alpha = alpha;"),
    M("sc-alpha-alpha1", "    a->Alpha = alpha;\n    a->Scale = *scale;",
      "    a->Alpha = alpha1;\n    a->Scale = *scale;"),
    M("sc-scale-scale1", "    a->Scale = *scale;\n    a->pText = t;\n    a->DeltaScale = *dscale;\n    a->DeltaAlpha = dalpha;\n    a->Colour3",
      "    a->Scale = *scale1;\n    a->pText = t;\n    a->DeltaScale = *dscale;\n    a->DeltaAlpha = dalpha;\n    a->Colour3"),
    M("sc-no-text", "    a->pText = t;\n    a->DeltaScale = *dscale;\n    a->DeltaAlpha = dalpha;\n    a->Colour3",
      "    a->DeltaScale = *dscale;\n    a->DeltaAlpha = dalpha;\n    a->Colour3"),
    M("sc-dscale-dscale2", "    a->DeltaScale = *dscale;\n    a->DeltaAlpha = dalpha;\n    a->Colour3",
      "    a->DeltaScale = *dscale2;\n    a->DeltaAlpha = dalpha;\n    a->Colour3"),
    M("sc-dalpha-dalpha2", "    a->DeltaAlpha = dalpha;\n    a->Colour3",
      "    a->DeltaAlpha = dalpha2;\n    a->Colour3"),
    M("sc-colour-dcolour", "    a->Colour3 = *colour;", "    a->Colour3 = *dcolour;"),
    M("sc-dpos2-dpos", "    a->DeltaPos2 = *dpos2;", "    a->DeltaPos2 = *dpos;"),
    M("sc-scale1-scale", "    a->Scale1 = *scale1;", "    a->Scale1 = *scale;"),
    M("sc-dscale2-dscale", "    a->DeltaScale2 = *dscale2;", "    a->DeltaScale2 = *dscale;"),
    M("sc-alpha1-alpha", "    a->Alpha1 = alpha1;", "    a->Alpha1 = alpha;"),
    M("sc-dalpha2-dalpha", "    a->DeltaAlpha2 = dalpha2;", "    a->DeltaAlpha2 = dalpha;"),
    M("sc-dcolour-colour", "    a->DeltaColour3 = *dcolour;", "    a->DeltaColour3 = *colour;"),
    M("sc-d0-d1", "    a->Duration[0] = d0;", "    a->Duration[0] = d1;"),
    M("sc-d1-d2", "    a->Duration[1] = d1;", "    a->Duration[1] = d2;"),
    M("sc-d2-d0", "    a->Duration[2] = d2;", "    a->Duration[2] = d0;"),
    M("sc-no-real-timer", "    a->bRealTimer = real_timer;\n", ""),
    M("sc-timers-swapped", "now_seconds(real_timer ? RealTimer : WorldTimer)",
      "now_seconds(real_timer ? WorldTimer : RealTimer)"),
    M("sc-not-active", "    a->bActive = 1;\n    if (a->pText != NULL) {",
      "    if (a->pText != NULL) {"),
    M("sc-no-place", "        place(&a->pText->Object, &a->Pos, &a->Scale);\n        flailertext_set_alpha(a->pText, a->Alpha);\n        flailerobject_set_visibility(&a->pText->Object, 1);\n    }\n}",
      "        flailertext_set_alpha(a->pText, a->Alpha);\n        flailerobject_set_visibility(&a->pText->Object, 1);\n    }\n}"),
    M("sc-no-alpha", "        flailertext_set_alpha(a->pText, a->Alpha);\n        flailerobject_set_visibility(&a->pText->Object, 1);\n    }\n}",
      "        flailerobject_set_visibility(&a->pText->Object, 1);\n    }\n}"),
    M("sc-hidden", "        flailerobject_set_visibility(&a->pText->Object, 1);\n    }\n}",
      "        flailerobject_set_visibility(&a->pText->Object, 0);\n    }\n}"),

    # The text start.
    M("st-pos-dpos", "    a->Pos = *pos;\n    a->DeltaPos = *dpos;\n    a->Scale = *scale;",
      "    a->Pos = *dpos;\n    a->DeltaPos = *dpos;\n    a->Scale = *scale;"),
    M("st-dpos-pos", "    a->DeltaPos = *dpos;\n    a->Scale = *scale;\n    a->Alpha = alpha;\n    a->pText = t;",
      "    a->DeltaPos = *pos;\n    a->Scale = *scale;\n    a->Alpha = alpha;\n    a->pText = t;"),
    M("st-scale-dscale", "    a->Scale = *scale;\n    a->Alpha = alpha;\n    a->pText = t;",
      "    a->Scale = *dscale;\n    a->Alpha = alpha;\n    a->pText = t;"),
    M("st-alpha", "    a->Alpha = alpha;\n    a->pText = t;\n    a->DeltaScale = *dscale;\n    a->Type",
      "    a->Alpha = 0;\n    a->pText = t;\n    a->DeltaScale = *dscale;\n    a->Type"),
    M("st-no-text", "    a->pText = t;\n    a->DeltaScale = *dscale;\n    a->Type",
      "    a->DeltaScale = *dscale;\n    a->Type"),
    M("st-dscale-scale", "    a->DeltaScale = *dscale;\n    a->Type = HUDANIM_SIMPLE;",
      "    a->DeltaScale = *scale;\n    a->Type = HUDANIM_SIMPLE;"),
    M("st-type", "    a->Type = HUDANIM_SIMPLE;\n    a->DeltaAlpha = dalpha;",
      "    a->Type = HUDANIM_SCORED;\n    a->DeltaAlpha = dalpha;"),
    M("st-dalpha", "    a->Type = HUDANIM_SIMPLE;\n    a->DeltaAlpha = dalpha;",
      "    a->Type = HUDANIM_SIMPLE;\n    a->DeltaAlpha = -dalpha;"),
    M("st-colour-x", "    a->DeltaAlpha = dalpha;\n    a->Colour.x = 128.0f;",
      "    a->DeltaAlpha = dalpha;\n    a->Colour.x = 120.0f;"),
    M("st-colour-y", "    a->Colour.y = 64.0f;\n    a->Colour.z = 0.0f;\n    a->Colour.w = 0.0f;\n    a->DeltaColour.x",
      "    a->Colour.y = 32.0f;\n    a->Colour.z = 0.0f;\n    a->Colour.w = 0.0f;\n    a->DeltaColour.x"),
    M("st-colour-z", "    a->Colour.z = 0.0f;\n    a->Colour.w = 0.0f;\n    a->DeltaColour.x",
      "    a->Colour.z = 8.0f;\n    a->Colour.w = 0.0f;\n    a->DeltaColour.x"),
    M("st-colour-w", "    a->Colour.w = 0.0f;\n    a->DeltaColour.x",
      "    a->Colour.w = 2.0f;\n    a->DeltaColour.x"),
    M("st-dcolour-x", "    a->DeltaColour.x = 0.0f;", "    a->DeltaColour.x = 4.0f;"),
    M("st-dcolour-y", "    a->DeltaColour.y = 64.0f;", "    a->DeltaColour.y = 60.0f;"),
    M("st-dcolour-z", "    a->DeltaColour.z = 128.0f;", "    a->DeltaColour.z = 64.0f;"),
    M("st-dcolour-w", "    a->DeltaColour.w = 0.0f;", "    a->DeltaColour.w = 1.0f;"),
    M("st-duration", "    a->Duration[0] = duration;\n    a->StartSeconds = now_seconds(WorldTimer);\n    a->bActive = 1;\n    if (a->pText == NULL)",
      "    a->Duration[0] = duration * 2.0f;\n    a->StartSeconds = now_seconds(WorldTimer);\n    a->bActive = 1;\n    if (a->pText == NULL)"),
    M("st-real-timer", "    a->StartSeconds = now_seconds(WorldTimer);\n    a->bActive = 1;\n    if (a->pText == NULL)",
      "    a->StartSeconds = now_seconds(RealTimer);\n    a->bActive = 1;\n    if (a->pText == NULL)"),
    M("st-not-active", "    a->bActive = 1;\n    if (a->pText == NULL)",
      "    if (a->pText == NULL)"),
    M("st-no-place", "        return;\n    place(&a->pText->Object, &a->Pos, &a->Scale);\n",
      "        return;\n"),
    M("st-no-alpha", "    place(&a->pText->Object, &a->Pos, &a->Scale);\n    flailertext_set_alpha(a->pText, a->Alpha);\n    flailerobject_set_visibility(&a->pText->Object, 1);\n}",
      "    place(&a->pText->Object, &a->Pos, &a->Scale);\n    flailerobject_set_visibility(&a->pText->Object, 1);\n}"),
    M("st-hidden", "    flailertext_set_alpha(a->pText, a->Alpha);\n    flailerobject_set_visibility(&a->pText->Object, 1);\n}",
      "    flailertext_set_alpha(a->pText, a->Alpha);\n    flailerobject_set_visibility(&a->pText->Object, 0);\n}"),

    # The bitmap start.
    M("sb-type-after-check", "    a->Type = HUDANIM_SIMPLE;\n    if (a->bActive)\n        return;",
      "    if (a->bActive)\n        return;\n    a->Type = HUDANIM_SIMPLE;"),
    M("sb-restarts", "    a->Type = HUDANIM_SIMPLE;\n    if (a->bActive)\n        return;",
      "    a->Type = HUDANIM_SIMPLE;"),
    M("sb-pos-dpos", "    a->Pos = *pos;\n    a->Alpha = alpha;", "    a->Pos = *dpos;\n    a->Alpha = alpha;"),
    M("sb-alpha", "    a->Pos = *pos;\n    a->Alpha = alpha;", "    a->Pos = *pos;\n    a->Alpha = alpha / 2;"),
    M("sb-dpos", "    a->Alpha = alpha;\n    a->DeltaPos = *dpos;", "    a->Alpha = alpha;\n    a->DeltaPos = *pos;"),
    M("sb-scale", "    a->DeltaPos = *dpos;\n    a->Scale = *scale;\n    a->DeltaScale = *dscale;\n    a->DeltaAlpha = dalpha;\n    a->Duration[0] = duration;\n    a->StartSeconds = now_seconds(WorldTimer);\n    a->pBitmap",
      "    a->DeltaPos = *dpos;\n    a->Scale = *dscale;\n    a->DeltaScale = *dscale;\n    a->DeltaAlpha = dalpha;\n    a->Duration[0] = duration;\n    a->StartSeconds = now_seconds(WorldTimer);\n    a->pBitmap"),
    M("sb-dscale", "    a->DeltaScale = *dscale;\n    a->DeltaAlpha = dalpha;\n    a->Duration[0] = duration;\n    a->StartSeconds = now_seconds(WorldTimer);\n    a->pBitmap",
      "    a->DeltaScale = *scale;\n    a->DeltaAlpha = dalpha;\n    a->Duration[0] = duration;\n    a->StartSeconds = now_seconds(WorldTimer);\n    a->pBitmap"),
    M("sb-dalpha", "    a->DeltaAlpha = dalpha;\n    a->Duration[0] = duration;\n    a->StartSeconds = now_seconds(WorldTimer);\n    a->pBitmap",
      "    a->DeltaAlpha = 0.0f;\n    a->Duration[0] = duration;\n    a->StartSeconds = now_seconds(WorldTimer);\n    a->pBitmap"),
    M("sb-duration", "    a->Duration[0] = duration;\n    a->StartSeconds = now_seconds(WorldTimer);\n    a->pBitmap",
      "    a->Duration[0] = 1.0f;\n    a->StartSeconds = now_seconds(WorldTimer);\n    a->pBitmap"),
    M("sb-real-timer", "    a->StartSeconds = now_seconds(WorldTimer);\n    a->pBitmap",
      "    a->StartSeconds = now_seconds(RealTimer);\n    a->pBitmap"),
    M("sb-no-bitmap", "    a->pBitmap = b;\n    a->bActive = 1;", "    a->bActive = 1;"),
    M("sb-not-active", "    a->pBitmap = b;\n    a->bActive = 1;", "    a->pBitmap = b;"),
    M("sb-no-keep", "    a->bKeepVisible = keep;\n", ""),
    M("sb-no-place", "    place(&b->Object, &a->Pos, &a->Scale);\n", ""),
    M("sb-alpha-corner", "    flailerbitmap_set_alpha(b, a->Alpha, -1);",
      "    flailerbitmap_set_alpha(b, a->Alpha, 0);"),
    M("sb-hidden", "    flailerobject_set_visibility(&b->Object, 1);",
      "    flailerobject_set_visibility(&b->Object, 0);"),

    # DoAnimation(Timer).
    M("do-inactive-runs", "    if (!a->bActive)\n        return 0;\n    t = (now_seconds(WorldTimer)",
      "    t = (now_seconds(WorldTimer)"),
    M("do-real-timer", "t = (now_seconds(WorldTimer) - a->StartSeconds) / a->Duration[0];",
      "t = (now_seconds(RealTimer) - a->StartSeconds) / a->Duration[0];"),
    M("do-unclamped", "    if (1.0f < t)\n        t = 1.0f;\n    if (a->Type != HUDANIM_SIMPLE)",
      "    if (a->Type != HUDANIM_SIMPLE)"),
    M("do-any-type", "    if (a->Type != HUDANIM_SIMPLE)\n        return 0;\n    pos.x",
      "    if (a->Type == HUDANIM_SCORED)\n        return 0;\n    pos.x"),
    M("do-pos-x", "    pos.x = a->DeltaPos.x * t + a->Pos.x;\n    pos.y = a->DeltaPos.y * t + a->Pos.y;\n    alpha",
      "    pos.x = a->DeltaPos.x * t;\n    pos.y = a->DeltaPos.y * t + a->Pos.y;\n    alpha"),
    M("do-pos-y", "    pos.y = a->DeltaPos.y * t + a->Pos.y;\n    alpha",
      "    pos.y = a->DeltaPos.y + a->Pos.y;\n    alpha"),
    M("do-alpha-trunc-sum", "    alpha = a->Alpha + ee_trunc_w(a->DeltaAlpha * t);\n    scale.x",
      "    alpha = ee_trunc_w((float)a->Alpha + a->DeltaAlpha * t);\n    scale.x"),
    M("do-scale-x", "    scale.x = a->DeltaScale.x * t + a->Scale.x;\n    scale.y = a->DeltaScale.y * t + a->Scale.y;\n    if (a->pText != NULL) {\n        bVector4 c;",
      "    scale.x = a->Scale.x;\n    scale.y = a->DeltaScale.y * t + a->Scale.y;\n    if (a->pText != NULL) {\n        bVector4 c;"),
    M("do-scale-y", "    scale.y = a->DeltaScale.y * t + a->Scale.y;\n    if (a->pText != NULL) {\n        bVector4 c;",
      "    scale.y = a->DeltaScale.x * t + a->Scale.y;\n    if (a->pText != NULL) {\n        bVector4 c;"),
    M("do-bitmap-first", "    if (a->pText != NULL) {\n        bVector4 c;",
      "    if (a->pText != NULL && a->pBitmap == NULL) {\n        bVector4 c;"),
    M("do-text-no-place", "        place(&a->pText->Object, &pos, &scale);\n        flailertext_set_alpha(a->pText, alpha);\n        lerp4",
      "        flailertext_set_alpha(a->pText, alpha);\n        lerp4"),
    M("do-text-no-alpha", "        flailertext_set_alpha(a->pText, alpha);\n        lerp4",
      "        lerp4"),
    M("do-text-colour-end", "        lerp4(&c, &a->Colour, &a->DeltaColour, t);",
      "        lerp4(&c, &a->Colour, &a->DeltaColour, 1.0f);"),
    M("do-text-no-colour", "        flailertext_set_color(a->pText, colour_word(&c));\n        if (1.0f <= t) {",
      "        if (1.0f <= t) {"),
    M("do-text-never-ends", "        if (1.0f <= t) {\n            flailerobject_set_visibility(&a->pText->Object, 0);\n            a->bActive = 0;\n        }\n    } else if",
      "        if (1.0f < t) {\n            flailerobject_set_visibility(&a->pText->Object, 0);\n            a->bActive = 0;\n        }\n    } else if"),
    M("do-text-stays-up", "            flailerobject_set_visibility(&a->pText->Object, 0);\n            a->bActive = 0;\n        }\n    } else if",
      "            a->bActive = 0;\n        }\n    } else if"),
    M("do-text-stays-active", "            flailerobject_set_visibility(&a->pText->Object, 0);\n            a->bActive = 0;\n        }\n    } else if",
      "            flailerobject_set_visibility(&a->pText->Object, 0);\n        }\n    } else if"),
    M("do-bitmap-no-place", "        place(&a->pBitmap->Object, &pos, &scale);\n        flailerbitmap_set_alpha(a->pBitmap, alpha, -1);",
      "        flailerbitmap_set_alpha(a->pBitmap, alpha, -1);"),
    M("do-bitmap-no-alpha", "        place(&a->pBitmap->Object, &pos, &scale);\n        flailerbitmap_set_alpha(a->pBitmap, alpha, -1);",
      "        place(&a->pBitmap->Object, &pos, &scale);"),
    M("do-bitmap-never-ends", "        flailerbitmap_set_alpha(a->pBitmap, alpha, -1);\n        if (1.0f <= t) {",
      "        flailerbitmap_set_alpha(a->pBitmap, alpha, -1);\n        if (1.0f < t) {"),
    M("do-bitmap-stays-active", "            a->bActive = 0;\n            if (!a->bKeepVisible)\n                flailerobject_set_visibility(&a->pBitmap->Object, 0);\n        }\n    }\n    return 0;",
      "            if (!a->bKeepVisible)\n                flailerobject_set_visibility(&a->pBitmap->Object, 0);\n        }\n    }\n    return 0;"),
    M("do-bitmap-keep-reversed", "            if (!a->bKeepVisible)\n                flailerobject_set_visibility(&a->pBitmap->Object, 0);\n        }\n    }\n    return 0;",
      "            if (a->bKeepVisible)\n                flailerobject_set_visibility(&a->pBitmap->Object, 0);\n        }\n    }\n    return 0;"),
    M("do-answers-1", "        }\n    }\n    return 0;\n}\n\nint32_t hudanim_do_scored",
      "        }\n    }\n    return 1;\n}\n\nint32_t hudanim_do_scored"),

    # DoAnimation(Timer *, char *).
    M("ds-inactive-runs", "    if (!a->bActive)\n        return 0;\n    t = now_seconds((int32_t)time->PackedTime)",
      "    t = now_seconds((int32_t)time->PackedTime)"),
    M("ds-world-timer", "    t = now_seconds((int32_t)time->PackedTime) - a->StartSeconds;",
      "    t = now_seconds(WorldTimer) - a->StartSeconds;"),
    M("ds-negative-phase-divides", "    if (phase >= 0 && phase <= 2)", "    if (phase <= 2)"),
    M("ds-phase-3-divides", "    if (phase >= 0 && phase <= 2)", "    if (phase >= 0 && phase <= 3)"),
    M("ds-unclamped", "    if (1.0f < t)\n        t = 1.0f;\n    if (a->Type != HUDANIM_SCORED)",
      "    if (a->Type != HUDANIM_SCORED)"),
    M("ds-any-type", "    if (a->Type != HUDANIM_SCORED)\n        return 0;",
      "    if (a->Type == HUDANIM_SIMPLE)\n        return 0;"),
    M("ds-phase-signed", "    if ((uint32_t)phase >= 3)", "    if (phase >= 3)"),
    M("ds-phase-not-stored", "        a->Phase = phase = 0;", "        phase = 0;"),
    M("ds-p0-pos-x", "    if (phase == 0) {\n        pos.x = a->DeltaPos.x * t + a->Pos.x;",
      "    if (phase == 0) {\n        pos.x = a->DeltaPos.x + a->Pos.x;"),
    M("ds-p0-pos-y", "        pos.y = a->DeltaPos.y * t + a->Pos.y;\n        scale.x = a->DeltaScale.x * t + a->Scale.x;",
      "        pos.y = a->Pos.y;\n        scale.x = a->DeltaScale.x * t + a->Scale.x;"),
    M("ds-p0-scale-x", "        scale.x = a->DeltaScale.x * t + a->Scale.x;\n        scale.y = a->DeltaScale.y * t + a->Scale.y;\n        lerp4",
      "        scale.x = a->DeltaScale.x * t + a->Scale.y;\n        scale.y = a->DeltaScale.y * t + a->Scale.y;\n        lerp4"),
    M("ds-p0-scale-y", "        scale.y = a->DeltaScale.y * t + a->Scale.y;\n        lerp4",
      "        scale.y = a->DeltaScale.y + a->Scale.y;\n        lerp4"),
    M("ds-p0-colour", "        lerp4(&c, &a->Colour3, &a->DeltaColour3, t);",
      "        lerp4(&c, &a->Colour3, &a->DeltaColour3, 0.0f);"),
    M("ds-p0-alpha", "        lerp4(&c, &a->Colour3, &a->DeltaColour3, t);\n        alpha = a->Alpha + ee_trunc_w(a->DeltaAlpha * t);",
      "        lerp4(&c, &a->Colour3, &a->DeltaColour3, t);\n        alpha = a->Alpha + ee_trunc_w(a->DeltaAlpha2 * t);"),
    M("ds-p1-pos", "    } else if (phase == 1) {\n        pos.x = a->DeltaPos.x + a->Pos.x;",
      "    } else if (phase == 1) {\n        pos.x = a->Pos.x;"),
    M("ds-p1-pos-y", "        pos.y = a->DeltaPos.y + a->Pos.y;\n        scale = a->Scale1;",
      "        pos.y = a->DeltaPos2.y + a->Pos.y;\n        scale = a->Scale1;"),
    M("ds-p1-scale", "        scale = a->Scale1;", "        scale = a->Scale;"),
    M("ds-p1-colour", "        scale = a->Scale1;\n        add4(&c, &a->DeltaColour3, &a->Colour3);",
      "        scale = a->Scale1;\n        c = a->Colour3;"),
    M("ds-p1-alpha", "        alpha = a->Alpha1;\n    } else {", "        alpha = a->Alpha;\n    } else {"),
    M("ds-p2-pos-x", "        pos.x = (a->DeltaPos2.x * t + a->DeltaPos.x) + a->Pos.x;",
      "        pos.x = (a->DeltaPos2.x + a->DeltaPos.x) + a->Pos.x;"),
    M("ds-p2-pos-y", "        pos.y = (a->DeltaPos2.y * t + a->DeltaPos.y) + a->Pos.y;",
      "        pos.y = (a->DeltaPos2.y * t) + a->Pos.y;"),
    M("ds-p2-scale-x", "        scale.x = a->DeltaScale2.x * t + a->Scale1.x;",
      "        scale.x = a->DeltaScale2.x * t + a->Scale.x;"),
    M("ds-p2-scale-y", "        scale.y = a->DeltaScale2.y * t + a->Scale1.y;",
      "        scale.y = a->DeltaScale.y * t + a->Scale1.y;"),
    M("ds-p2-colour", "        add4(&c, &a->DeltaColour3, &a->Colour3);\n        alpha = a->Alpha1 + ee_trunc_w(a->DeltaAlpha2 * t);",
      "        lerp4(&c, &a->Colour3, &a->DeltaColour3, t);\n        alpha = a->Alpha1 + ee_trunc_w(a->DeltaAlpha2 * t);"),
    M("ds-p2-alpha", "        alpha = a->Alpha1 + ee_trunc_w(a->DeltaAlpha2 * t);",
      "        alpha = a->Alpha + ee_trunc_w(a->DeltaAlpha2 * t);"),
    M("ds-p2-dalpha", "        alpha = a->Alpha1 + ee_trunc_w(a->DeltaAlpha2 * t);",
      "        alpha = a->Alpha1 + ee_trunc_w(a->DeltaAlpha * t);"),
    M("ds-no-text-runs", "    if (a->pText == NULL)\n        return 0;\n    place(&a->pText->Object, &pos, &scale);",
      "    if (a->pText == NULL)\n        return 1;\n    place(&a->pText->Object, &pos, &scale);"),
    M("ds-no-place", "    place(&a->pText->Object, &pos, &scale);\n    flailertext_set_alpha(a->pText, alpha);\n    flailertext_set_string",
      "    flailertext_set_alpha(a->pText, alpha);\n    flailertext_set_string"),
    M("ds-no-alpha", "    flailertext_set_alpha(a->pText, alpha);\n    flailertext_set_string",
      "    flailertext_set_string"),
    M("ds-callers-string", "flailertext_set_string(a->pText, a->bHasString ? a->String : s);",
      "flailertext_set_string(a->pText, s);"),
    M("ds-own-string", "flailertext_set_string(a->pText, a->bHasString ? a->String : s);",
      "flailertext_set_string(a->pText, a->String);"),
    M("ds-no-colour", "    flailertext_set_color(a->pText, colour_word(&c));\n    if (!(1.0f <= t))",
      "    if (!(1.0f <= t))"),
    M("ds-never-ends", "    if (!(1.0f <= t))\n        return 0;", "    if (!(1.0f < t))\n        return 0;"),
    M("ds-ends-phase-1", "    if (phase == 2) {\n        flailerobject_set_visibility",
      "    if (phase == 1) {\n        flailerobject_set_visibility"),
    M("ds-end-stays-up", "        flailerobject_set_visibility(&a->pText->Object, 0);\n        a->bActive = 0;\n        return 1;",
      "        a->bActive = 0;\n        return 1;"),
    M("ds-end-stays-active", "        a->bActive = 0;\n        return 1;", "        return 1;"),
    M("ds-end-answers-0", "        a->bActive = 0;\n        return 1;", "        a->bActive = 0;\n        return 0;"),
    M("ds-next-from-now", "    a->StartSeconds = a->StartSeconds + a->Duration[phase];",
      "    a->StartSeconds = now_seconds((int32_t)time->PackedTime);"),
    M("ds-next-first-duration", "    a->StartSeconds = a->StartSeconds + a->Duration[phase];",
      "    a->StartSeconds = a->StartSeconds + a->Duration[0];"),
    M("ds-phase-stays", "    a->Phase = phase + 1;", "    a->Phase = phase;"),

    # FinishAnimation.
    M("fin-text-stays-up", "            flailerobject_set_visibility(&a->pText->Object, 0);\n            a->bActive = 0;\n        } else if (a->pBitmap != NULL) {\n            bVector2 pos, scale;",
      "            a->bActive = 0;\n        } else if (a->pBitmap != NULL) {\n            bVector2 pos, scale;"),
    M("fin-text-stays-active", "            flailerobject_set_visibility(&a->pText->Object, 0);\n            a->bActive = 0;\n        } else if (a->pBitmap != NULL) {\n            bVector2 pos, scale;",
      "            flailerobject_set_visibility(&a->pText->Object, 0);\n        } else if (a->pBitmap != NULL) {\n            bVector2 pos, scale;"),
    M("fin-bitmap-first", "        if (a->pText != NULL) {\n            flailerobject_set_visibility(&a->pText->Object, 0);\n            a->bActive = 0;\n        } else if (a->pBitmap != NULL) {",
      "        if (a->pText != NULL && a->pBitmap == NULL) {\n            flailerobject_set_visibility(&a->pText->Object, 0);\n            a->bActive = 0;\n        } else if (a->pBitmap != NULL) {"),
    M("fin-bitmap-pos-x", "            pos.x = a->DeltaPos.x + a->Pos.x;\n            pos.y",
      "            pos.x = a->Pos.x;\n            pos.y"),
    M("fin-bitmap-pos-y", "            pos.y = a->DeltaPos.y + a->Pos.y;\n            scale.x",
      "            pos.y = a->DeltaPos.y;\n            scale.x"),
    M("fin-bitmap-scale-x", "            scale.x = a->DeltaScale.x + a->Scale.x;",
      "            scale.x = a->Scale.x;"),
    M("fin-bitmap-scale-y", "            scale.y = a->DeltaScale.y + a->Scale.y;",
      "            scale.y = a->DeltaScale.x + a->Scale.y;"),
    M("fin-bitmap-no-place", "            place(&a->pBitmap->Object, &pos, &scale);\n", ""),
    M("fin-bitmap-first-alpha", "            flailerbitmap_set_alpha(a->pBitmap,\n                                    a->Alpha + ee_trunc_w(a->DeltaAlpha), -1);\n            a->bActive = 0;\n            if (!a->bKeepVisible)\n                flailerobject_set_visibility(&a->pBitmap->Object, 0);\n        }\n        break;",
      "            flailerbitmap_set_alpha(a->pBitmap, a->Alpha, -1);\n            a->bActive = 0;\n            if (!a->bKeepVisible)\n                flailerobject_set_visibility(&a->pBitmap->Object, 0);\n        }\n        break;"),
    M("fin-bitmap-stays-active", "            a->bActive = 0;\n            if (!a->bKeepVisible)\n                flailerobject_set_visibility(&a->pBitmap->Object, 0);\n        }\n        break;",
      "            if (!a->bKeepVisible)\n                flailerobject_set_visibility(&a->pBitmap->Object, 0);\n        }\n        break;"),
    M("fin-bitmap-always-hidden", "            if (!a->bKeepVisible)\n                flailerobject_set_visibility(&a->pBitmap->Object, 0);\n        }\n        break;",
      "            flailerobject_set_visibility(&a->pBitmap->Object, 0);\n        }\n        break;"),
    M("fin-simple-falls-through", "        }\n        break;\n    case HUDANIM_BLINK:", "        }\n    case HUDANIM_BLINK:"),
    M("fin-blink-colour-x", "ee_trunc_w(a->Colour.w), -1);", "ee_trunc_w(a->Colour.x), -1);"),
    M("fin-blink-nothing", "    case HUDANIM_BLINK:\n", "    case 99:\n"),
    M("fin-scored-stays-up", "    case HUDANIM_SCORED:\n        if (a->pText != NULL) {\n            flailerobject_set_visibility(&a->pText->Object, 0);\n",
      "    case HUDANIM_SCORED:\n        if (a->pText != NULL) {\n"),
    M("fin-scored-stays-active", "            flailerobject_set_visibility(&a->pText->Object, 0);\n            a->bActive = 0;\n        }\n        break;\n    }\n}",
      "            flailerobject_set_visibility(&a->pText->Object, 0);\n        }\n        break;\n    }\n}"),

    # ClearHudAnimations.
    M("cl-finishes-14", "        if ((uint32_t)(i - 12) < 3 || i == 18)",
      "        if ((uint32_t)(i - 12) < 2 || i == 18)"),
    M("cl-finishes-12", "        if ((uint32_t)(i - 12) < 3 || i == 18)",
      "        if ((uint32_t)(i - 13) < 2 || i == 18)"),
    M("cl-finishes-18", "        if ((uint32_t)(i - 12) < 3 || i == 18)",
      "        if ((uint32_t)(i - 12) < 3)"),
    M("cl-skips-19", "        if ((uint32_t)(i - 12) < 3 || i == 18)",
      "        if ((uint32_t)(i - 12) < 3 || i >= 18)"),
    M("cl-skips-0", "    for (i = 0; i < 20; i++) {\n        if ((uint32_t)",
      "    for (i = 1; i < 20; i++) {\n        if ((uint32_t)"),
    M("cl-score-slot-11", "        if (i == 10 && p->pHudAnimations[10]->bActive) {",
      "        if (i == 11 && p->pHudAnimations[10]->bActive) {"),
    M("cl-score-inactive-too", "        if (i == 10 && p->pHudAnimations[10]->bActive) {",
      "        if (i == 10) {"),
    M("cl-adds-event-score", "            player_add_to_total_score(p, p->strPrevScore);",
      "            player_add_to_total_score(p, p->strEventScore);"),
    M("cl-score-stays-active", "            p->pHudAnimations[10]->bActive = 0;\n", ""),
    M("cl-score-not-finished", "            p->pHudAnimations[10]->bActive = 0;\n        }\n        hudanim_finish(p->pHudAnimations[i]);",
      "            p->pHudAnimations[10]->bActive = 0;\n            continue;\n        }\n        hudanim_finish(p->pHudAnimations[i]);"),

    # HudStartWrongWay.
    M("ww-from-x", "    from.x = 258.0f;\n    from.y = 119.0f;", "    from.x = 257.0f;\n    from.y = 119.0f;"),
    M("ww-from-y", "    from.x = 258.0f;\n    from.y = 119.0f;", "    from.x = 258.0f;\n    from.y = 120.0f;"),
    M("ww-to-x", "    to.x = -105.0f;", "    to.x = -100.0f;"),
    M("ww-to-y", "    to.x = -105.0f;\n    to.y = -80.0f;", "    to.x = -105.0f;\n    to.y = -81.0f;"),
    M("ww-free-run-ignored", "    if (race_parameters_is_free_run(&TheRaceParameters)) {",
      "    if (0) {"),
    M("ww-free-run-x", "        to.x = -240.0f;", "        to.x = -241.0f;"),
    M("ww-free-run-y", "        to.y = -100.0f;", "        to.y = -101.0f;"),
    M("ww-live-split-alone", "    if ((p->CurrentHudFeatures & (HUD_LIVE_SPLIT | HUD_RACE_POSITION))\n        == HUD_LIVE_SPLIT) {",
      "    if ((p->CurrentHudFeatures & HUD_LIVE_SPLIT)\n        == HUD_LIVE_SPLIT) {"),
    M("ww-live-split-ignored", "    if ((p->CurrentHudFeatures & (HUD_LIVE_SPLIT | HUD_RACE_POSITION))\n        == HUD_LIVE_SPLIT) {",
      "    if (0) {"),
    M("ww-live-split-x", "        to.x = -95.0f;", "        to.x = -96.0f;"),
    M("ww-live-split-y", "        to.x = -95.0f;\n        to.y = -80.0f;", "        to.x = -95.0f;\n        to.y = -79.0f;"),
    M("ww-to-y-from-x", "    to.y = to.y + from.y;", "    to.y = to.y + from.x;"),
    M("ww-to-x-alone", "    to.x = to.x + from.x;", "    to.x = to.x + 0.0f;"),
    M("ww-scale-from", "    scale_from.x = scale_from.y = 1.0f;", "    scale_from.x = scale_from.y = 1.5f;"),
    M("ww-scale-to", "    scale_to.x = scale_to.y = 0.3f;", "    scale_to.x = scale_to.y = 0.25f;"),
    M("ww-scale-to-y", "    scale_to.x = scale_to.y = 0.3f;", "    scale_to.x = 0.3f;\n    scale_to.y = 0.35f;"),
    M("ww-two-players-at-3", "    if (PlayerNumPlayers >= 2) {", "    if (PlayerNumPlayers >= 3) {"),
    M("ww-one-player-too", "    if (PlayerNumPlayers >= 2) {", "    if (PlayerNumPlayers >= 1) {"),
    M("ww-halves-scale-from", "        scale_from.x = scale_from.y = 0.5f;", "        scale_from.x = scale_from.y = 1.0f;"),
    M("ww-halves-scale-to", "        scale_to.x = scale_to.y = 0.25f;", "        scale_to.x = scale_to.y = 0.3f;"),
    M("ww-p0-from-y", "            from.y = 125.0f;", "            from.y = 120.0f;"),
    M("ww-p0-to-x", "            from.y = 125.0f;\n            to.x = 128.0f;", "            from.y = 125.0f;\n            to.x = 129.0f;"),
    M("ww-p0-from-x", "            from.x = 258.0f;\n            from.y = 125.0f;", "            from.x = 250.0f;\n            from.y = 125.0f;"),
    M("ww-p0-to-y", "            from.y = 125.0f;\n            to.x = 128.0f;\n            to.y = from.y;",
      "            from.y = 125.0f;\n            to.x = 128.0f;\n            to.y = from.x;"),
    M("ww-p1-is-p0", "        if (p->PlayerNumber == 1) {", "        if (p->PlayerNumber == 0) {"),
    M("ww-p1-else", "        if (p->PlayerNumber == 1) {", "        else {"),
    M("ww-p1-from-x", "            from.x = 258.0f;\n            from.y = 350.0f;", "            from.x = 250.0f;\n            from.y = 350.0f;"),
    M("ww-p1-from-y", "            from.y = 350.0f;", "            from.y = 351.0f;"),
    M("ww-p1-to-x", "            from.y = 350.0f;\n            to.x = 128.0f;", "            from.y = 350.0f;\n            to.x = 127.0f;"),
    M("ww-p1-to-y", "            from.y = 350.0f;\n            to.x = 128.0f;\n            to.y = from.y;",
      "            from.y = 350.0f;\n            to.x = 128.0f;\n            to.y = 125.0f;"),
    M("ww-bitmap-hash", "#define WRONG_WAY_BITMAP 0x89af1a1eu", "#define WRONG_WAY_BITMAP 0x8d28acceu"),
    M("ww-slot", "    player_hud_start_bitmap_animation(p, 15,", "    player_hud_start_bitmap_animation(p, 16,"),
    M("ww-alpha-from", "                                      64, 64, 1.0f, (uint32_t)WorldTimer, 1);",
      "                                      0, 64, 1.0f, (uint32_t)WorldTimer, 1);"),
    M("ww-alpha-to", "                                      64, 64, 1.0f, (uint32_t)WorldTimer, 1);",
      "                                      64, 0, 1.0f, (uint32_t)WorldTimer, 1);"),
    M("ww-duration", "                                      64, 64, 1.0f, (uint32_t)WorldTimer, 1);",
      "                                      64, 64, 2.0f, (uint32_t)WorldTimer, 1);"),
    M("ww-not-kept", "                                      64, 64, 1.0f, (uint32_t)WorldTimer, 1);",
      "                                      64, 64, 1.0f, (uint32_t)WorldTimer, 0);"),

    # HudStartGrowAnimation.
    M("gr-pos-from-a", "    if (b == NULL)\n        return;\n    pos.x = b->Object.X;\n    pos.y = b->Object.Y;\n    scale.x = b->Object.ScaleX;\n    scale.y = b->Object.ScaleY;\n    alpha = flailertext_get_alpha(b);\n    if (grow) {\n        to.x = 0.0f",
      "    if (b == NULL)\n        return;\n    pos.x = a->Object.X;\n    pos.y = b->Object.Y;\n    scale.x = b->Object.ScaleX;\n    scale.y = b->Object.ScaleY;\n    alpha = flailertext_get_alpha(b);\n    if (grow) {\n        to.x = 0.0f"),
    M("gr-scale-y-from-x", "    scale.y = b->Object.ScaleY;\n    alpha = flailertext_get_alpha(b);\n    if (grow) {\n        to.x = 0.0f",
      "    scale.y = b->Object.ScaleX;\n    alpha = flailertext_get_alpha(b);\n    if (grow) {\n        to.x = 0.0f"),
    M("gr-alpha-from-a", "    alpha = flailertext_get_alpha(b);\n    if (grow) {\n        to.x = 0.0f",
      "    alpha = flailertext_get_alpha(a);\n    if (grow) {\n        to.x = 0.0f"),
    M("gr-flag-reversed", "    if (grow) {\n        to.x = 0.0f + pos.x;\n        to.y = -30.0f + pos.y;",
      "    if (!grow) {\n        to.x = 0.0f + pos.x;\n        to.y = -30.0f + pos.y;"),
    M("gr-up-30", "        to.y = -30.0f + pos.y;", "        to.y = -20.0f + pos.y;"),
    M("gr-up-x", "        to.x = 0.0f + pos.x;\n        to.y = -30.0f + pos.y;", "        to.x = 1.0f + pos.x;\n        to.y = -30.0f + pos.y;"),
    M("gr-grow-to-2", "        to.y = -30.0f + pos.y;\n        scale_to.x = scale_to.y = 2.0f;",
      "        to.y = -30.0f + pos.y;\n        scale_to.x = scale_to.y = 1.5f;"),
    M("gr-grow-fades-in", "                                        &scale_to, alpha, 0, 0.5f, time);",
      "                                        &scale_to, 0, alpha, 0.5f, time);"),
    M("gr-grow-duration", "                                        &scale_to, alpha, 0, 0.5f, time);",
      "                                        &scale_to, alpha, 0, 1.0f, time);"),
    M("gr-grow-slot", "        player_hud_start_text_animation(p, 0, a, &pos, &to, &scale,\n                                        &scale_to, alpha, 0, 0.5f, time);",
      "        player_hud_start_text_animation(p, 2, a, &pos, &to, &scale,\n                                        &scale_to, alpha, 0, 0.5f, time);"),
    M("gr-down-100", "        to.y = 100.0f + pos.y;\n        scale_to.x = scale_to.y = 0.5f;\n        player_hud_start_text_animation(p, 0,",
      "        to.y = 90.0f + pos.y;\n        scale_to.x = scale_to.y = 0.5f;\n        player_hud_start_text_animation(p, 0,"),
    M("gr-shrink-to", "        scale_to.x = scale_to.y = 0.5f;\n        player_hud_start_text_animation(p, 0,",
      "        scale_to.x = scale_to.y = 0.25f;\n        player_hud_start_text_animation(p, 0,"),
    M("gr-shrink-fades-out", "                                        &scale_to, 0, alpha, 1.0f, time);",
      "                                        &scale_to, alpha, 0, 1.0f, time);"),
    M("gr-shrink-duration", "                                        &scale_to, 0, alpha, 1.0f, time);",
      "                                        &scale_to, 0, alpha, 0.5f, time);"),
    M("gr-shrink-slot", "        player_hud_start_text_animation(p, 0, a, &pos, &to, &scale,\n                                        &scale_to, 0, alpha, 1.0f, time);",
      "        player_hud_start_text_animation(p, 1, a, &pos, &to, &scale,\n                                        &scale_to, 0, alpha, 1.0f, time);"),

    # HudStartSpeedAnimation.
    M("sp-no-speed-string", "    if (p->pFlailerSpeedString == NULL)\n        return;\n", ""),
    M("sp-pos-x-from-a", "    pos.x = b->Object.X;\n    pos.y = b->Object.Y;\n    scale.x = b->Object.ScaleX;\n    scale.y = b->Object.ScaleY;\n    alpha = flailertext_get_alpha(b);\n    if (grow) {\n        float w",
      "    pos.x = a->Object.X;\n    pos.y = b->Object.Y;\n    scale.x = b->Object.ScaleX;\n    scale.y = b->Object.ScaleY;\n    alpha = flailertext_get_alpha(b);\n    if (grow) {\n        float w"),
    M("sp-scale-x-from-y", "    scale.x = b->Object.ScaleX;\n    scale.y = b->Object.ScaleY;\n    alpha = flailertext_get_alpha(b);\n    if (grow) {\n        float w",
      "    scale.x = b->Object.ScaleY;\n    scale.y = b->Object.ScaleY;\n    alpha = flailertext_get_alpha(b);\n    if (grow) {\n        float w"),
    M("sp-alpha-from-a", "    alpha = flailertext_get_alpha(b);\n    if (grow) {\n        float w",
      "    alpha = flailertext_get_alpha(a);\n    if (grow) {\n        float w"),
    M("sp-width-of-a", "        float w = flailerobject_get_width_float(&b->Object);",
      "        float w = flailerobject_get_width_float(&a->Object);"),
    M("sp-height-is-width", "        float h = flailerobject_get_height_float(&b->Object);",
      "        float h = flailerobject_get_width_float(&b->Object);"),
    M("sp-grow-to-2", "        scale_to.x = scale_to.y = 2.0f;\n        // Scaled",
      "        scale_to.x = scale_to.y = 3.0f;\n        // Scaled"),
    M("sp-half-height", "        hh = h * 0.5f;", "        hh = h;"),
    M("sp-half-width", "        hw = w * 0.5f;", "        hw = w * 0.25f;"),
    M("sp-centre-y", "        to.y = (hh + hh * -scale_to.y) + pos.y;", "        to.y = (hh * -scale_to.y) + pos.y;"),
    M("sp-centre-x", "        to.x = (hw + hw * -scale_to.x) + pos.x;", "        to.x = (hh + hw * -scale_to.x) + pos.x;"),
    M("sp-down-100", "        to.y = 100.0f + pos.y;\n        scale_to.x = scale_to.y = 0.5f;\n    }",
      "        to.y = 50.0f + pos.y;\n        scale_to.x = scale_to.y = 0.5f;\n    }"),
    M("sp-shrink-to", "        scale_to.x = scale_to.y = 0.5f;\n    }", "        scale_to.x = scale_to.y = 0.75f;\n    }"),
    M("sp-slot", "    player_hud_start_text_animation(p, 1, a,", "    player_hud_start_text_animation(p, 0, a,"),
    M("sp-alpha-kept", "                                    alpha, 0, 1.0f, time);", "                                    alpha, alpha, 1.0f, time);"),
    M("sp-duration", "                                    alpha, 0, 1.0f, time);", "                                    alpha, 0, 0.5f, time);"),

    # The two HudStartAnimation.
    M("pt-dpos-x", "    dpos.x = to->x - from->x;\n    dpos.y = to->y - from->y;\n    dscale.x = scale_to->x - scale_from->x;\n    dscale.y = scale_to->y - scale_from->y;\n    hudanim_start_text",
      "    dpos.x = to->x;\n    dpos.y = to->y - from->y;\n    dscale.x = scale_to->x - scale_from->x;\n    dscale.y = scale_to->y - scale_from->y;\n    hudanim_start_text"),
    M("pt-dpos-y", "    dpos.y = to->y - from->y;\n    dscale.x = scale_to->x - scale_from->x;\n    dscale.y = scale_to->y - scale_from->y;\n    hudanim_start_text",
      "    dpos.y = from->y - to->y;\n    dscale.x = scale_to->x - scale_from->x;\n    dscale.y = scale_to->y - scale_from->y;\n    hudanim_start_text"),
    M("pt-dscale-x", "    dscale.x = scale_to->x - scale_from->x;\n    dscale.y = scale_to->y - scale_from->y;\n    hudanim_start_text",
      "    dscale.x = scale_to->x;\n    dscale.y = scale_to->y - scale_from->y;\n    hudanim_start_text"),
    M("pt-dscale-y", "    dscale.y = scale_to->y - scale_from->y;\n    hudanim_start_text",
      "    dscale.y = scale_to->x - scale_from->y;\n    hudanim_start_text"),
    M("pt-dalpha", "    hudanim_start_text(a, t, from, &dpos, scale_from, &dscale, alpha_from,\n                       (float)(int32_t)((uint32_t)alpha_to\n                                        - (uint32_t)alpha_from),",
      "    hudanim_start_text(a, t, from, &dpos, scale_from, &dscale, alpha_from,\n                       (float)(int32_t)((uint32_t)alpha_to),"),
    M("pt-alpha-to", "    hudanim_start_text(a, t, from, &dpos, scale_from, &dscale, alpha_from,",
      "    hudanim_start_text(a, t, from, &dpos, scale_from, &dscale, alpha_to,"),
    M("pt-duration", "                       duration);", "                       1.0f);"),
    M("pb-slot-new-each-time", "    HudAnimator *a = slot_animator(p, slot);\n    bVector2 dpos, dscale;\n\n    (void)time;\n    dpos.x = to->x - from->x;\n    dpos.y = to->y - from->y;\n    dscale.x = scale_to->x - scale_from->x;\n    dscale.y = scale_to->y - scale_from->y;\n    hudanim_start_bitmap",
      "    HudAnimator *a = (p->pHudAnimations[slot] = hudanim_new());\n    bVector2 dpos, dscale;\n\n    (void)time;\n    dpos.x = to->x - from->x;\n    dpos.y = to->y - from->y;\n    dscale.x = scale_to->x - scale_from->x;\n    dscale.y = scale_to->y - scale_from->y;\n    hudanim_start_bitmap"),
    M("pb-dpos-x", "    dpos.x = to->x - from->x;\n    dpos.y = to->y - from->y;\n    dscale.x = scale_to->x - scale_from->x;\n    dscale.y = scale_to->y - scale_from->y;\n    hudanim_start_bitmap",
      "    dpos.x = from->x - to->x;\n    dpos.y = to->y - from->y;\n    dscale.x = scale_to->x - scale_from->x;\n    dscale.y = scale_to->y - scale_from->y;\n    hudanim_start_bitmap"),
    M("pb-dpos-y", "    dpos.y = to->y - from->y;\n    dscale.x = scale_to->x - scale_from->x;\n    dscale.y = scale_to->y - scale_from->y;\n    hudanim_start_bitmap",
      "    dpos.y = to->y;\n    dscale.x = scale_to->x - scale_from->x;\n    dscale.y = scale_to->y - scale_from->y;\n    hudanim_start_bitmap"),
    M("pb-dscale-x", "    dscale.x = scale_to->x - scale_from->x;\n    dscale.y = scale_to->y - scale_from->y;\n    hudanim_start_bitmap",
      "    dscale.x = scale_to->x - scale_from->y;\n    dscale.y = scale_to->y - scale_from->y;\n    hudanim_start_bitmap"),
    M("pb-dscale-y", "    dscale.y = scale_to->y - scale_from->y;\n    hudanim_start_bitmap",
      "    dscale.y = scale_to->y;\n    hudanim_start_bitmap"),
    M("pb-dalpha", "    hudanim_start_bitmap(a, b, from, &dpos, scale_from, &dscale, alpha_from,\n                         (float)(int32_t)((uint32_t)alpha_to\n                                          - (uint32_t)alpha_from),",
      "    hudanim_start_bitmap(a, b, from, &dpos, scale_from, &dscale, alpha_from,\n                         (float)(int32_t)((uint32_t)alpha_from\n                                          - (uint32_t)alpha_to),"),
    M("pb-not-kept", "                         duration, keep);", "                         duration, 0);"),
    M("pb-duration", "                         duration, keep);", "                         1.0f, keep);"),
    M("slot-always-new", "    if (p->pHudAnimations[slot] == NULL)\n        p->pHudAnimations[slot] = hudanim_new();",
      "    p->pHudAnimations[slot] = hudanim_new();"),

    # HudDoAnimations.
    M("da-0-on-gauges", "        && (p->CurrentHudFeatures & HUD_RACE_POSITION))",
      "        && (p->CurrentHudFeatures & HUD_GAUGES))"),
    M("da-0-always", "        && (p->CurrentHudFeatures & HUD_RACE_POSITION))", "        )"),
    M("da-1-on-bumper-only", "        && (p->CurrentHudFeatures & (HUD_GAUGES | HUD_GAUGES_OUTSIDE)))",
      "        && (p->CurrentHudFeatures & HUD_GAUGES))"),
    M("da-1-on-dash-only", "        && (p->CurrentHudFeatures & (HUD_GAUGES | HUD_GAUGES_OUTSIDE)))",
      "        && (p->CurrentHudFeatures & HUD_GAUGES_OUTSIDE))"),
    M("da-1-always", "        && (p->CurrentHudFeatures & (HUD_GAUGES | HUD_GAUGES_OUTSIDE)))", "        )"),
    M("da-from-3", "    for (i = 2; i <= 8; i++)", "    for (i = 3; i <= 8; i++)"),
    M("da-to-7", "    for (i = 2; i <= 8; i++)", "    for (i = 2; i <= 7; i++)"),
    M("da-to-9", "    for (i = 2; i <= 8; i++)", "    for (i = 2; i <= 9; i++)"),
    M("da-real-timer", "    now.PackedTime = (uint32_t)WorldTimer;", "    now.PackedTime = (uint32_t)RealTimer;"),
    M("da-10-no-total", "        && hudanim_do_scored(p->pHudAnimations[10], &now, p->strEventScore))\n        player_add_to_total_score(p, p->strEventScore);",
      "        && hudanim_do_scored(p->pHudAnimations[10], &now, p->strEventScore))\n        ;"),
    M("da-10-adds-prev", "        player_add_to_total_score(p, p->strEventScore);",
      "        player_add_to_total_score(p, p->strPrevScore);"),
    M("da-10-shows-title", "        && hudanim_do_scored(p->pHudAnimations[10], &now, p->strEventScore))",
      "        && hudanim_do_scored(p->pHudAnimations[10], &now, p->strEventTitle))"),
    M("da-11-shows-score", "        hudanim_do_scored(p->pHudAnimations[11], &now, p->strEventTitle);",
      "        hudanim_do_scored(p->pHudAnimations[11], &now, p->strEventScore);"),
    M("da-12-empty", '        hudanim_do_scored(p->pHudAnimations[12], &now, "SCORE");',
      '        hudanim_do_scored(p->pHudAnimations[12], &now, "");'),
    M("da-13-score", '        hudanim_do_scored(p->pHudAnimations[13], &now, "");',
      '        hudanim_do_scored(p->pHudAnimations[13], &now, "SCORE");'),
    M("da-11-skipped", "    if (running(p->pHudAnimations[11]))\n", "    if (0)\n"),
    M("da-15-is-14", "    if (running(p->pHudAnimations[15]))\n        hudanim_do(p->pHudAnimations[15]);",
      "    if (running(p->pHudAnimations[14]))\n        hudanim_do(p->pHudAnimations[14]);"),
    M("da-16-skipped", "    for (i = 16; i <= 17; i++)", "    for (i = 17; i <= 17; i++)"),
    M("da-17-skipped", "    for (i = 16; i <= 17; i++)", "    for (i = 16; i <= 16; i++)"),
    M("da-18-run", "    for (i = 16; i <= 17; i++)", "    for (i = 16; i <= 18; i++)"),
    M("da-inactive-run", "    return a != NULL && a->bActive;", "    return a != NULL;"),

    # AddToTotalScore.
    M("at-subtracts", "                              + (uint32_t)player_convert_score_string(p, s));",
      "                              - (uint32_t)player_convert_score_string(p, s));"),
    M("at-no-floor", "    if (p->TotalScore < 0)\n        p->TotalScore = 0;\n", ""),
    M("at-floor-at-1", "    if (p->TotalScore < 0)\n        p->TotalScore = 0;\n",
      "    if (p->TotalScore < 1)\n        p->TotalScore = 1;\n"),
    M("at-hex", 'b_snprintf(buf, sizeof buf, "%d", p->TotalScore);',
      'b_snprintf(buf, sizeof buf, "%x", p->TotalScore);'),
    M("at-no-string", "        flailertext_set_string((struct FlailerTextChunk *)p->pFlailerScoreTotal,\n                               buf);",
      "        ;"),
]

EQUIVALENT = {
    "lerp-w-dropped":
        "lerp4's out->w goes into a local colour, and colour_word reads "
        "only x, y and z",
    "da-inactive-run":
        "every animator call HudDoAnimations makes checks bActive first and "
        "does nothing (the scored one answering 0) when it is clear",
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
