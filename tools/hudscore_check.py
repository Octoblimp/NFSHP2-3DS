#!/usr/bin/env python3
"""Cross-check 3DS Files/source/hudscore.c, the race's bonus scores,
against the retail image, SLES_507.31.

**The model** is retail's own: PlayScoreSound (0x00175100),
Player::StartScoreAnimation (0x0017d370), GetFinishBonus (0x0017e2d0),
both StartScore (0x0017e3b0, 0x0017e558) and UpdateScoring (0x0017e820);
and under them RaceCoordinator::IsReplayDemoMode, Collision's
GetCollidingCars and IsSmokeableInvolved, bSPrintf, everything
tools/hudanim_check.py runs (HudAnimator, AddToTotalScore,
ConvertScoreString, HudDoAnimations) and the Flailer runtime on INGAMEB's
Flailer chunk. The harness (tools/src/hudscore_test.c) runs hudscore.c
over hudanim.c and what hudanim_test.c links, on the same bundle.

**The stubs** are hudanim_check.py's bMalloc, and the callees the HUD
does not own, scripted the same on both sides and logged: Race::
GetRacingCar, Car::IsBlinking, CollisionBody::GetCollision (the body it
is asked of, by name), GetInGameSample, bSample::IsPlaying and Play,
GetTranslatedString ("TITLE" and the id) and the bodies' GetMassInverse,
through a vtable of their own. The harness's GetCollidingCars and
IsSmokeableInvolved are collision.c's, which tools/collision_check.py
checks.

**Compared** are the stubs' logs, GetFinishBonus's answers and, after
each op, every line that changed: hudanim_check.py's (each Player's
twenty animation slots, TotalScore and every Flailer object's bytes),
each Player's scoring fields and its three event strings, and
bResetGlare. StartScore builds its two colours on the stack and leaves
their fourth lanes as the stack held them, so the animators' Colour3.w
and DeltaColour3.w show as eeeeeeee on both sides; nothing draws them.

**The script** plays the sound in every coordinator state and for every
scoring, with the sound off and the sample missing or busy; asks every
finish bonus; flies the scores in for one player and for each half of two,
over a score still flying; runs StartScore over the table; and runs
UpdateScoring through a blinking car, every way a lap and a segment end
(time trials with and without a target, as the cop, point to point),
the top speed, knocks of every pairing and on each side of every limit,
smokeables, take-offs and landings across each air band and past the
int's range, and places taken, again, as the cop and at the two words
past the array's ends.

    python tools/hudscore_check.py
    python tools/hudscore_check.py --mutate [--only a,b]
    python tools/hudscore_check.py --dump out/hudscore
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
import hudanim_check as ha              # noqa: E402
import physicscar_check as pcc          # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/hudscore_test.c"
HUDSCORE = "3DS Files/source/hudscore.c"
SOURCES = [HARNESS, HUDSCORE, "3DS Files/source/vtable.c"] + ha.SOURCES[1:]

GP = fc.GP
RP = ha.RP
G_NUM = ha.G_NUM
G_TIMER = ha.G_TIMER
G_REAL = ha.G_REAL
G_SOUND = GP - 23056                    # SoundEnabled
G_GLARE = GP - 23564                    # bResetGlare
G_RC = GP - 22216                       # pRaceCoordinator

F_SOUND = 0x00175100
F_ANIM = 0x0017d370
F_BONUS = 0x0017e2d0
F_SCORE = 0x0017e3b0
F_SCOREV = 0x0017e558
F_UPDATE = 0x0017e820
S_RACING_CAR = 0x00149158               # Race::GetRacingCar
S_BLINKING = 0x00133130                 # Car::IsBlinking
S_COLLISION = 0x001d6f38                # CollisionBody::GetCollision
S_SAMPLE = 0x001ae280                   # GetInGameSample
S_PLAYING = 0x00274410                  # bSample::IsPlaying
S_PLAY = 0x00274080                     # bSample::Play
S_TRANSLATE = 0x0021e560                # GetTranslatedString

NUM_CARS = 4
CAR_SIZE = 1024
BODY_SIZE = 336
MASS_SLOT = 152                         # GetMassInverse
DELTA = 8

PLAYER_WORDS = dict(ha.PLAYER_WORDS, PositionFlag=1520,
                    LastRacePosition=1620, bNewTopSpeed=1636, New2540=2540,
                    bCollisionDetected=2544, bSmokeableHit=2548,
                    bSegment=2624, bShownMusicTitle=2660, numCleanLaps=2688,
                    HangTime=1508, tscore=2732,
                    **{"place%d" % i: 2628 + 4 * i for i in range(8)})
PLAYER_OBJECTS = dict(ha.PLAYER_OBJECTS, evscoreobj=1148, evtitleobj=1144)
PLAYER_STRINGS = ha.PLAYER_STRINGS
RP_WORDS = dict(ha.RP_WORDS, TTT=36, P2P=40)

HUD_SINGLE = ha.HUD_SINGLE
ALL = ha.ALL
EVT = ha.EVT
EVS = ha.EVS
SCO = ha.SCO

TICKS = ha.TICKS
T0 = 400000
F = ha.F
fbits = ha.fbits

# eScoring
BEAT_THE_COPS, TOP_SPEED, AIR, START_BONUS, TOOK_1ST = 0, 6, 11, 15, 16
QUOTA_FILLED = 27

RC_IN_PROGRESS = 3


# ================================================================== script

def common():
    s = ["load|%s" % (fc.SD / "GLOBAL/INGAMEB.BUN"), "g|np|1",
         "g|timer|%d" % T0, "g|real|123457", "g|sound|1", "rp|RaceType|1",
         "rp|Laps|3", "rcstate|%d" % RC_IN_PROGRESS, "sample|1",
         "playing|0"]
    for k in (1, 0):
        s += ["use|%d" % k, "pl|%d|PN|%d" % (k, k),
              "pl|%d|screen|%#x" % (k, HUD_SINGLE), "pl|%d|chf|%#x" % (k, ALL),
              "pl|%d|scoretotal|%s" % (k, SCO),
              "pl|%d|evscoreobj|%s" % (k, EVS),
              "pl|%d|evtitleobj|%s" % (k, EVT),
              "pl|%d|evscore|+1500" % k, "pl|%d|evtitle|NEAR MISS" % k,
              "pl|%d|prevscore|-250" % k, "pl|%d|score|1000" % k,
              "pl|%d|tscore|0x7fffffff" % k]
    for k in range(NUM_CARS):
        s += ["car|%d|player|%d" % (k, k if k < 2 else -1),
              "car|%d|wheels|4" % k,
              "car|%d|up|%s" % (k, "|".join(F(v) for v in (0, 0, 1, 0))),
              "body|%d|0|%d|%s" % (k, k, F(0.001 * (k + 1)))]
    s += ["use|0", "racing|-", "coll|-", "blink|0"]
    return s


def frames(t, *dts):
    s = []
    for dt in dts:
        s += ["g|timer|%d" % (t + dt), "do"]
    return s


def anim(pos, dpos, dpos2, scale, dscale, colour, dcolour):
    return "anim|" + "|".join(F(v) for v in (pos + dpos + dpos2 + scale
                                             + dscale + colour + dcolour))


def coll(b1, b2, mag, d):
    return "coll|%d|%d|%s|%s" % (b1, b2, F(mag), "|".join(F(v) for v in d))


def s_sound():
    s = []
    for st in range(10):
        s += ["rcstate|%d" % st, "sound|%d" % BEAT_THE_COPS]
    s += ["rcstate|%d" % RC_IN_PROGRESS]
    for e in range(30):
        s += ["sound|%d" % e]
    s += ["playing|1", "sound|%d" % TOP_SPEED, "playing|0",
          "sample|0", "sound|%d" % QUOTA_FILLED, "sample|1",
          "g|sound|0", "sound|%d" % TOOK_1ST, "g|sound|1",
          "sound|-1", "sound|31"]
    return s


def s_bonus():
    return ["bonus|%d" % k for k in (-1, 0, 1, 2, 3, 4, 8, 100)]


def s_anim():
    t = T0 + 20000
    s = ["g|timer|%d" % t]
    s += [anim((10.5, 20.25), (1, -2), (3.5, 4), (0.5, 2), (0.25, -0.5),
               (128, 64, 0, 7), (0, 64, 128, -3))]
    s += frames(t, 1000, 2000, 2500, 4000, 8000, 8001)
    # Over a score still flying: slot 10 adds strPrevScore first.
    t += 20000
    s += ["g|timer|%d" % t, "pl|0|evscore|+700",
          anim((530, 236), (0, 0), (90, -100), (0.7, 0.7), (0, 0),
               (128, 64, 0, 0), (0, 64, 128, 0)),
          "g|timer|%d" % (t + 100), "pl|0|evscore|-125",
          anim((-5.75, 1000.5), (7, 9), (-90, 100), (1.5, 1.25), (1, 1),
               (1, 2, 3, 4), (5, 6, 7, 8))]
    s += frames(t, 2100, 4200, 8200)
    # Two players: each half's y halved and moved down.
    t += 20000
    s += ["g|np|2", "g|timer|%d" % t]
    for k in (0, 1):
        s += ["use|%d" % k,
              anim((530, 236.5), (3, -20.5), (90, -100.25), (0.7, 0.7),
                   (0.125, 0), (128, 64, 0, 0), (0, 64, 128, 0))]
    s += ["use|0"]
    s += frames(t, 1000, 3000, 8000)
    # A player number neither half's.
    s += ["pl|0|PN|2", "g|timer|%d" % (t + 9000),
          anim((1, 2), (3, 4), (5, 6), (1, 1), (0, 0), (9, 9, 9, 9),
               (0, 0, 0, 0)),
          "pl|0|PN|0", "g|np|1"]
    s += frames(t, 20000)
    return s


def s_score():
    t = T0 + 100000
    s = ["g|timer|%d" % t]
    for e in (0, 1, 3, 7, 10, 14, 15, 16, 22, 23, 26, 29):
        t += 9000
        s += ["g|timer|%d" % t, "score|%d" % e]
        s += frames(t, 1000, 2000, 4000)
    t += 9000
    s += ["g|timer|%d" % t, "pl|0|evscore|+333", "scorev|%d|333" % AIR,
          "g|timer|%d" % (t + 50), "scorev|13|-7",
          "g|timer|%d" % (t + 100), "scorev|%d|5" % TOP_SPEED,
          "g|timer|%d" % (t + 150), "scorev|%d|1" % BEAT_THE_COPS]
    s += frames(t, 4000, 8000)
    # Back to back: the second adds the first.
    t += 20000
    s += ["g|timer|%d" % t, "score|3", "score|5", "score|2"]
    s += frames(t, 4000, 8000)
    # Two players.
    t += 20000
    s += ["g|np|2", "g|timer|%d" % t, "score|4", "use|1", "score|6",
          "use|0"]
    s += frames(t, 4000, 8000)
    s += ["g|np|1"]
    return s


def update(t):
    return ["g|timer|%d" % t, "update"]


def s_blink():
    t = T0 + 400000
    return (["pl|0|HangTime|%s" % F(5.5), "pl|0|bNewTopSpeed|1",
             "pl|0|PositionFlag|1", "pl|0|LastRacePosition|2",
             "car|0|wheels|0", "blink|1", "g|glare|0"]
            + update(t)
            + ["blink|0", "pl|0|bNewTopSpeed|0", "pl|0|PositionFlag|0",
               "car|0|wheels|4", "pl|0|HangTime|0"]
            + update(t + 10))


def lap(t, nl, pos, crossed=1, reason=0, coll=None, seg=None):
    s = ["racing|%d|%d|%d|%d" % (nl, pos, crossed, reason)]
    if coll is not None:
        s += ["pl|0|bCollisionDetected|%d" % coll]
    if seg is not None:
        s += ["pl|0|bSegment|%d" % seg]
    return s + update(t) + frames(t, 4000, 8000)


def s_laps():
    t = T0 + 500000
    s = []
    # Laps of a circuit race.
    for nl, pos, c, g in ((1, 3, 0, 1), (2, 1, 1, 1), (1, 1, 1, 0),
                          (3, 1, 1, 0), (2, 2, 1, 0), (0, 2, 1, 0),
                          (2, 2, 1, 1), (-1, 2, 1, 0), (1, 0, 1, 0),
                          (1, -1, 1, 0), (0, 1, 1, 0), (-1, 1, 1, 0)):
        t += 10000
        s += lap(t, nl, pos, coll=c, seg=g)
    # Not crossing, finished, no racing car.
    t += 10000
    s += lap(t, 1, 1, crossed=0, coll=0, seg=0)
    t += 10000
    s += lap(t, 1, 1, reason=2, coll=0, seg=0)
    t += 10000
    s += lap(t, 1, 1, crossed=-128, coll=0, seg=0)
    t += 10000
    s += lap(t, 1, 1, reason=-32768, coll=0, seg=0)
    t += 10000
    s += ["racing|-"] + update(t)
    # Time trials: a target makes it a segment, unless as the cop.
    s += ["rp|RaceType|2"]
    for ttt, cop in ((12345, 0), (0, 0), (0x7fffffff, 0), (12345, 1),
                     (1, 0), (0x80000000, 0), (0x7ffffffe, 0)):
        for c, g in ((0, 0), (1, 1)):
            t += 10000
            s += ["rp|TTT|%d" % ttt, "rp|BeACop|%d" % cop]
            s += lap(t, 2, 2, coll=c, seg=g)
    s += ["rp|RaceType|3", "rp|TTT|12345", "rp|BeACop|0"]
    t += 10000
    s += lap(t, 1, 2, coll=1, seg=0)
    # Point to point.
    s += ["rp|RaceType|1", "rp|TTT|0", "rp|P2P|1"]
    for c, g in ((0, 0), (1, 1), (1, 0), (0, 1)):
        t += 10000
        s += lap(t, 0, 4, coll=c, seg=g)
    s += ["rp|P2P|-1"]
    t += 10000
    s += lap(t, 0, 4, coll=0, seg=0)
    s += ["rp|P2P|0", "racing|-"]
    # The top speed, alone and after a lap.
    t += 10000
    s += ["pl|0|bNewTopSpeed|1"] + update(t) + frames(t, 4000, 8000)
    t += 10000
    s += lap(t, 2, 1, coll=1, seg=0)
    s += ["pl|0|bNewTopSpeed|-5"]
    t += 10000
    s += lap(t, 2, 3, coll=0, seg=0)
    s += ["pl|0|bNewTopSpeed|0", "racing|-"]
    return s


def knock(t, b1, b2, mag, d, smoke_hit=None, hang=None):
    s = []
    if smoke_hit is not None:
        s += ["pl|0|bSmokeableHit|%d" % smoke_hit]
    if hang is not None:
        s += ["pl|0|HangTime|%s" % hang]
    s += ["pl|0|bCollisionDetected|0", "pl|0|bSegment|0",
          "pl|0|New2540|1", coll(b1, b2, mag, d)]
    return s + update(t)


def s_knocks():
    t = T0 + 900000
    s = []
    side = (1, 0, 0.5, 9)
    # Body 2 is car 2's, which no player drives; body 3 a smokeable.
    s += ["body|2|0|2|%s" % F(0.002), "body|3|1|-1|%s" % F(0.0)]
    for b1, b2 in ((0, 2), (2, 0), (0, 0), (1, 2), (2, 1), (0, 3), (3, 0),
                   (3, 3), (0, 1), (1, 0)):
        t += 100
        s += knock(t, b1, b2, 20.0, side, smoke_hit=0)
        t += 100
        s += knock(t, b1, b2, 20.0, side)
    # The other body's mass.
    for m in (499.99997, 500.0, 500.00003, 0.0, -1.0, float("inf"),
              float("nan")):
        t += 100
        s += ["body|2|0|2|%s" % F(m)]
        s += knock(t, 0, 2, 20.0, side, smoke_hit=1)
        t += 100
        s += knock(t, 2, 0, 20.0, side)
    s += ["body|2|0|2|%s" % F(0.002), "body|0|0|0|%s" % F(1000.0)]
    t += 100
    s += knock(t, 0, 2, 20.0, side)
    t += 100
    s += knock(t, 2, 0, 20.0, side)
    s += ["body|0|0|0|%s" % F(0.001)]
    # In the air: no knock.
    for h in (F(1.0), "0x80000000", F(-2.0), "0x00000001"):
        t += 100
        s += knock(t, 0, 2, 20.0, side, hang=h)
    s += ["pl|0|HangTime|0"]
    # The direction against the car's up.
    for d in ((0, 0, 0.8, 0), (0, 0, 0.79999995, 0), (0, 0, -0.8, 0),
              (0, 0, -0.79999995, 0), (0, 0, 0, 0), (0, 0, -0.0, 5),
              (1, 1, 0.5, 0), (0, 0, 0.5, 100), (0, 0, float("nan"), 0),
              (0, 0, float("inf"), 0), (3, -2, 0.25, 0)):
        t += 100
        s += knock(t, 0, 2, 20.0, d)
    s += ["car|0|up|%s" % "|".join(F(v) for v in (0.5, -0.25, 0.75, 3))]
    for d in ((1, 1, 1, 0), (0.6, 0.6, 0.6, 0), (-1, 0, 0, 7),
              (0, 2, 0, 0), (0.4, 0.8, 0.1, 0)):
        t += 100
        s += knock(t, 0, 2, 20.0, d)
    s += ["car|0|up|%s" % "|".join(F(v) for v in (0, 0, 1, 0))]
    # The impulse.
    for mag in (8.3333, 8.333301, 8.3332, 0.0, -20.0, float("inf"),
                float("nan")):
        t += 100
        s += knock(t, 0, 2, mag, side)
    # Smokeables: hit once, then again.
    for k in (0, 1, 1, 0, 2, 1):
        t += 100
        s += ["pl|0|bSmokeableHit|%d" % k, coll(0, 3, 20.0, side)] + update(t)
    s += ["body|3|2|-1|%s" % F(0.0)]
    t += 100
    s += ["pl|0|bSmokeableHit|1", coll(0, 3, 20.0, side)] + update(t)
    # A knock of player 1's car, and its knock seen from player 0.
    s += ["use|1"]
    t += 100
    s += ["pl|1|bCollisionDetected|0", "pl|1|bSmokeableHit|1",
          coll(1, 2, 20.0, side)] + update(t)
    s += ["use|0"]
    t += 100
    s += ["pl|0|bSmokeableHit|1"] + update(t)
    s += ["coll|-", "body|3|1|-1|%s" % F(0.0)]
    t += 100
    s += ["pl|0|bSmokeableHit|1"] + update(t)
    # Both bodies are car 0's: the second's side wins, so the first's mass
    # is the other's.
    s += ["body|2|0|0|%s" % F(0.002), "body|0|0|0|%s" % F(1000.0)]
    for b1, b2 in ((0, 2), (2, 0)):
        t += 100
        s += knock(t, b1, b2, 20.0, side)
    s += ["body|2|0|2|%s" % F(0.002), "body|0|0|0|%s" % F(0.001)]
    # 1e8 - 1e8 + 0.5 is 0.5 added left to right and 0 the other way.
    s += ["car|0|up|%s" % "|".join(F(v) for v in (1e4, 1e4, 1, 0))]
    for d in ((1e4, -1e4, 0.5, 0), (-1e4, 1e4, -0.5, 0)):
        t += 100
        s += knock(t, 0, 2, 20.0, d)
    s += ["car|0|up|%s" % "|".join(F(v) for v in (0, 0, 1, 0))]
    s += ["coll|-"]
    return s


def s_air():
    t = T0 + 1500000
    s = []
    for secs in (0.39, 0.4, 0.5, 0.6, 0.79, 0.8, 1.0, 1.39, 1.4, 1.45, 1.5, 2.0, 10.0,
                 0.0, 0.2):
        t += 100000
        dt = int(round(secs * TICKS))
        s += ["car|0|wheels|0"] + update(t)
        s += update(t + dt // 2)
        s += ["car|0|wheels|4"] + update(t + dt)
        s += frames(t + dt, 4000, 8000)
    # Landing before the take-off, and far past it.
    for h in (F(1e6), F(-1e10), F(-3.0e5), F(150.0)):
        t += 100000
        s += ["pl|0|HangTime|%s" % h] + update(t)
        s += frames(t, 4000, 8000)
    # Landed with nothing timed: a -0 becomes 0.
    s += ["pl|0|HangTime|0x80000000"] + update(t + 9000)
    s += ["car|0|wheels|-1"] + update(t + 9100)
    s += ["car|0|wheels|0", "pl|0|HangTime|0x80000000"] + update(t + 9200)
    s += ["pl|0|HangTime|0x00000001"] + update(t + 9300)
    s += ["car|0|wheels|4", "pl|0|HangTime|0"] + update(t + 9400)
    # A negative timer.
    s += ["car|0|wheels|0"] + update(-40000)
    s += ["car|0|wheels|2"] + update(-35000)
    return s


def s_places():
    t = T0 + 4000000
    s = []
    for pf, lrp in ((1, 3), (1, 3), (5, 1), (0, 2), (-1, 2), (1, 7), (1, 8),
                    (1, 0), (1, 9), (1, 10), (1, -1), (1, 2), (1, 14),
                    (1, 11), (1, 13), (1, 12)):
        t += 10000
        s += ["pl|0|PositionFlag|%d" % pf, "pl|0|LastRacePosition|%d" % lrp]
        s += update(t) + frames(t, 4000, 8000)
    s += ["rp|BeACop|1"]
    for lrp in (4, 5):
        t += 10000
        s += ["pl|0|PositionFlag|1", "pl|0|LastRacePosition|%d" % lrp]
        s += update(t)
    s += ["rp|BeACop|0", "pl|0|place3|0", "pl|0|bSegment|0",
          "pl|0|bShownMusicTitle|0"]
    t += 10000
    s += ["pl|0|PositionFlag|1", "pl|0|LastRacePosition|4"] + update(t)
    return s


def s_all():
    """Everything in one frame, on two players."""
    t = T0 + 5000000
    s = ["g|np|2"]
    for k in (0, 1):
        s += ["use|%d" % k, "racing|1|1|1|0",
              "pl|%d|bCollisionDetected|0" % k, "pl|%d|bNewTopSpeed|1" % k,
              "pl|%d|HangTime|%s" % (k, F((t - 2000) * 0.00025)),
              "pl|%d|PositionFlag|1" % k, "pl|%d|LastRacePosition|6" % k,
              "pl|%d|place5|0" % k, coll(k, 2, 20.0, (1, 0, 0, 0))]
        s += update(t)
    s += frames(t, 1000, 3000, 4500, 9000)
    s += ["use|0", "g|np|1", "racing|-", "coll|-"]
    return s


def script():
    s = common()
    s += s_sound()
    s += s_bonus()
    s += s_anim()
    s += s_score()
    s += s_blink()
    s += s_laps()
    s += s_knocks()
    s += s_air()
    s += s_places()
    s += s_all()
    return s


# =================================================================== model

class Model(ha.Model):
    def __init__(self):
        ha.Model.__init__(self)
        e = self.e
        for g in (G_SOUND, G_GLARE):
            e.put32(g, 0)
        self.rc = e.alloc(16, align=16)
        e.put32(G_RC, self.rc)
        self.cars = [e.alloc(CAR_SIZE, align=16) for _ in range(NUM_CARS)]
        self.bodies = [e.alloc(BODY_SIZE, align=16) for _ in range(NUM_CARS)]
        self.mass = [0] * NUM_CARS
        self.vt = e.alloc(26 * 8, align=16)
        self.f_mass = e.alloc(16, align=16)
        e.write(self.vt + MASS_SLOT, struct.pack("<hhI", DELTA, 0,
                                                 self.f_mass))
        for k in range(NUM_CARS):
            e.write(self.cars[k], bytes(CAR_SIZE))
            e.write(self.bodies[k], bytes(BODY_SIZE))
            e.put32(self.bodies[k] + 80, self.vt)
            e.put32(self.cars[k] + 52, self.bodies[k])
        for k in range(2):
            e.put32(self.players[k] + 4, self.cars[k])
        self.witness = e.alloc(112, align=16)
        self.coll = e.alloc(112, align=16)
        e.write(self.coll, bytes(112))
        e.put32(self.coll + 84, self.witness)
        self.racing = e.alloc(192, align=16)
        e.write(self.racing, bytes(192))
        self.sample = e.alloc(16, align=16)
        self.title = e.alloc(32, align=16)
        self.racing_set = self.coll_set = 0
        self.blink = self.given = self.playing = 0
        e.stub(S_RACING_CAR,
               lambda em: self.racing if self.racing_set else 0)
        e.stub(S_BLINKING, lambda em: self.blink)
        e.stub(S_COLLISION, self.s_collision)
        e.stub(S_SAMPLE, self.s_sample)
        e.stub(S_PLAYING, self.s_playing)
        e.stub(S_PLAY, self.s_play)
        e.stub(S_TRANSLATE, self.s_translate)
        e.stub(self.f_mass, self.s_mass)

    # ---- stubs

    def body_index(self, a):
        return self.bodies.index(a) if a in self.bodies else -1

    def s_collision(self, em):
        self.emit("  getcoll B%d %d" % (self.body_index(em.reg[4] & M32),
                                        s32(em.reg[5])))
        return self.coll if self.coll_set else 0

    def s_sample(self, em):
        a = em.reg[4] & M32
        name = bytes(em.mem[a:a + 64]).split(b"\0")[0].decode("latin-1")
        self.emit('  sample "%s" -> %s' % (name, "S" if self.given
                                           else "none"))
        return self.sample if self.given else 0

    def s_playing(self, em):
        self.emit("  playing? -> %d" % self.playing)
        return self.playing

    def s_play(self, em):
        self.emit("  play %08x %08x %08x" % (em.fpr[12] & M32,
                                             em.fpr[13] & M32,
                                             em.fpr[14] & M32))

    def s_translate(self, em):
        i = s32(em.reg[4])
        self.emit("  translate %d" % i)
        self.e.write(self.title, ("TITLE %d" % i).encode() + b"\0")
        return self.title

    def s_mass(self, em):
        k = self.body_index((em.reg[4] - DELTA) & M32)
        self.emit("  mass B%d" % k)
        em.fpr[0] = self.mass[k] if k >= 0 else 0

    # ---- output

    def dump(self):
        e = self.e
        mem = e.mem
        for n, p in enumerate(self.players):
            for i in range(ha.NUM_SLOTS):
                a = e.u32(p + ha.ANIMS + 4 * i)
                key = "p%d.anim[%d]" % (n, i)
                if a == 0:
                    self.note(key, "none")
                    continue
                k = self.allocs.index(a) if a in self.allocs else -1
                tail = bytearray(mem[a + 80:a + ha.ANIM_SIZE])
                tail[220 - 80:224 - 80] = b"\xee" * 4
                tail[236 - 80:240 - 80] = b"\xee" * 4
                self.note(key, "a%d %s %s %s %s" % (
                    k, bytes(mem[a:a + 72]).hex(), self.name(e.u32(a + 72)),
                    self.name(e.u32(a + 76)), bytes(tail).hex()))
            self.note("p%d.TotalScore" % n, "%08x" % e.u32(p + ha.TOTAL))
            w = lambda o: s32(e.u32(p + o))       # noqa: E731
            self.note("p%d.scoring" % n, (
                "hang %08x pf %d lrp %d top %d n2540 %d coll %d smoke %d"
                " seg %d places %s music %d clean %d tscore %08x"
                % (e.u32(p + 1508), w(1520), w(1620), w(1636), w(2540),
                   w(2544), w(2548), w(2624),
                   " ".join("%d" % w(2628 + 4 * i) for i in range(8)),
                   w(2660), w(2688), e.u32(p + 2732))))
            strs = [bytes(mem[p + o:p + o + 32]).split(b"\0")[0]
                    .decode("latin-1") for o in (1412, 1444, 1476)]
            self.note("p%d.strings" % n, '"%s" "%s" "%s"' % tuple(strs))
            self.note("p%d.placewords" % n,
                      bytes(mem[p + 2620:p + 2684]).hex())
        self.note("glare", "%d" % s32(e.u32(G_GLARE)))
        self.dump_objects()

    # ---- ops

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
        p = self.player()
        v = lambda i: int(a[i], 0) & M32      # noqa: E731
        if o == "g" and a[1] in ("sound", "glare"):
            e.put32(G_SOUND if a[1] == "sound" else G_GLARE, v(2))
        elif o == "rp":
            e.put32(RP + RP_WORDS[a[1]], v(2))
        elif o == "rcstate":
            e.put32(self.rc, v(1))
        elif o == "sample":
            self.given = s32(v(1))
        elif o == "playing":
            self.playing = s32(v(1))
        elif o == "blink":
            self.blink = s32(v(1))
        elif o == "racing":
            self.racing_set = a[1] != "-"
            if self.racing_set:
                r = self.racing
                e.mem[r + 9] = v(1) & 0xff
                e.mem[r + 10] = v(2) & 0xff
                e.mem[r + 13] = v(3) & 0xff
                e.write(r + 18, struct.pack("<H", v(4) & 0xffff))
        elif o == "car":
            c = self.cars[int(a[1])]
            if a[2] == "player":
                k = int(a[3])
                e.put32(c + 24, self.players[k] if k >= 0 else 0)
            elif a[2] == "up":
                self.vec(c + 176, a[3:7])
            elif a[2] == "wheels":
                e.put32(c + 956, v(3))
            else:
                raise ValueError(a[2])
        elif o == "body":
            k = int(a[1])
            b = self.bodies[k]
            car = int(a[3])
            e.mem[b + 12] = v(2) & 0xff
            e.put32(b + 256, self.cars[car] if car >= 0 else 0)
            self.mass[k] = v(4)
        elif o == "coll":
            self.coll_set = a[1] != "-"
            if self.coll_set:
                e.put32(self.witness + 96, self.bodies[int(a[1])])
                e.put32(self.witness + 100, self.bodies[int(a[2])])
                e.put32(self.coll + 80, v(3))
                self.vec(self.coll + 96, a[4:8])
        elif o == "sound":
            e.call(F_SOUND, v(1), limit=1000000)
        elif o == "anim":
            w = self.vecs
            vecs = [self.vec(w + 16 * i, a[1 + 2 * i:3 + 2 * i])
                    for i in range(5)]
            colour = self.vec(w + 128, a[11:15])
            dcolour = self.vec(w + 144, a[15:19])
            e.call(F_ANIM, p, *(vecs + [colour, dcolour]), limit=2000000)
        elif o == "bonus":
            self.emit("  = %d" % e.call(F_BONUS, p, v(1), limit=1000000))
        elif o == "score":
            e.call(F_SCORE, p, v(1), limit=2000000)
        elif o == "scorev":
            e.call(F_SCOREV, p, v(1), v(2), limit=2000000)
        elif o == "update":
            e.call(F_UPDATE, p, limit=4000000)
        else:
            ha.Model.op(self, a)
            return
        self.dump()


def model(lines):
    return Model().run(lines)


# ================================================================= build

def build_harness(tmp, name="hudscore_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


run_harness = fc.run_harness
diff = pcc.diff
write_script = fc.write_script


# ============================================================= mutations

H = HUDSCORE


def M(name, before, after, rel=H):
    return (name, rel, before, after)


MUTATIONS = [
    # The sound.
    M("sound-ignores-enabled", "    if (!SoundEnabled)\n        return;\n", ""),
    M("sound-instant-replay", "    if (state == RCSTATE_INSTANT_REPLAY || ",
      "    if ("),
    M("sound-postrace", "|| state == RCSTATE_POSTRACE\n", "\n"),
    M("sound-auto-replay", "        || state == RCSTATE_AUTO_REPLAY\n", ""),
    M("sound-pause", "        || state == RCSTATE_AUTO_REPLAY\n",
      "        || state == RCSTATE_AUTO_REPLAY || state == RCSTATE_PAUSE\n"),
    M("sound-replay-demo",
      "        || racecoordinator_is_replay_demo_mode(pRaceCoordinator))",
      "        || 0)"),
    M("sound-not-beat", "    if (scoring != SCORING_BEAT_THE_COPS && ",
      "    if ("),
    M("sound-not-1st", "scoring != SCORING_TOOK_1ST_PLACE\n", "1\n"),
    M("sound-not-top", "        && scoring != SCORING_TOP_SPEED && ", "        && "),
    M("sound-not-quota", " && scoring != SCORING_QUOTA_FILLED)", ")"),
    M("sound-name", 'gGetInGameSampleFn("ScorePoints")',
      'gGetInGameSampleFn("ScorePoint")'),
    M("sound-ignores-playing",
      "    if (gSampleIsPlayingFn != NULL && gSampleIsPlayingFn(smp))\n"
      "        return;\n", ""),
    M("sound-volume", "gSamplePlayFn(smp, 1.0f, 0.0f, 0.0f);",
      "gSamplePlayFn(smp, 0.5f, 0.0f, 0.0f);"),
    M("sound-pan", "gSamplePlayFn(smp, 1.0f, 0.0f, 0.0f);",
      "gSamplePlayFn(smp, 1.0f, 1.0f, 0.0f);"),

    # The animation.
    M("anim-two-at-one", "    if (PlayerNumPlayers >= 2) {",
      "    if (PlayerNumPlayers >= 1) {"),
    M("anim-two-at-three", "    if (PlayerNumPlayers >= 2) {",
      "    if (PlayerNumPlayers >= 3) {"),
    M("anim-p0-no-half", "            at.y = at.y * 0.5f;\n"
      "            d.y = d.y * 0.5f;\n            d2.y = d2.y * 0.5f;\n"
      "            at.y = at.y + TWO_PLAYER_Y0;",
      "            d.y = d.y * 0.5f;\n            d2.y = d2.y * 0.5f;\n"
      "            at.y = at.y + TWO_PLAYER_Y0;"),
    M("anim-p0-dy", "            d.y = d.y * 0.5f;\n            d2.y = d2.y * 0.5f;\n"
      "            at.y = at.y + TWO_PLAYER_Y0;",
      "            d2.y = d2.y * 0.5f;\n            at.y = at.y + TWO_PLAYER_Y0;"),
    M("anim-p0-dy2", "            d2.y = d2.y * 0.5f;\n"
      "            at.y = at.y + TWO_PLAYER_Y0;",
      "            at.y = at.y + TWO_PLAYER_Y0;"),
    M("anim-p0-x", "            at.y = at.y * 0.5f;\n            d.y = d.y * 0.5f;\n"
      "            d2.y = d2.y * 0.5f;\n            at.y = at.y + TWO_PLAYER_Y0;",
      "            at.x = at.x * 0.5f;\n            d.y = d.y * 0.5f;\n"
      "            d2.y = d2.y * 0.5f;\n            at.y = at.y + TWO_PLAYER_Y0;"),
    M("anim-p1-dy", "            d.y = d.y * 0.5f;\n            d2.y = d2.y * 0.5f;\n"
      "            at.y = at.y + TWO_PLAYER_Y1;",
      "            d2.y = d2.y * 0.5f;\n            at.y = at.y + TWO_PLAYER_Y1;"),
    M("anim-p1-else", "        if (p->PlayerNumber == 1) {",
      "        else {"),
    M("anim-y0", "#define TWO_PLAYER_Y0     40.0f", "#define TWO_PLAYER_Y0     41.0f"),
    M("anim-y1", "#define TWO_PLAYER_Y1    280.0f", "#define TWO_PLAYER_Y1    240.0f"),
    M("anim-no-add", "    if (a->bActive)\n        player_add_to_total_score(p, p->strPrevScore);\n", ""),
    M("anim-add-always", "    if (a->bActive)\n        player_add_to_total_score",
      "    if (1)\n        player_add_to_total_score"),
    M("anim-add-event", "player_add_to_total_score(p, p->strPrevScore);",
      "player_add_to_total_score(p, p->strEventScore);"),
    M("anim-score-slot", "#define SLOT_SCORE 10", "#define SLOT_SCORE 9"),
    M("anim-title-slot", "#define SLOT_TITLE 11", "#define SLOT_TITLE 12"),
    M("anim-score-text", "                            p->pFlailerEventScore,",
      "                            p->pFlailerEventTitle,"),
    M("anim-title-text", "                            p->pFlailerEventTitle,",
      "                            p->pFlailerEventScore,"),
    M("anim-alpha", "&at, &d, &d2, scale, dscale, 0, 128.0f, colour,\n"
      "                         scale, dscale, 64, -64.0f, dcolour, 0.5f, 0.5f,\n"
      "                         1.0f, NULL, 0);\n    a = slot_animator",
      "&at, &d, &d2, scale, dscale, 1, 128.0f, colour,\n"
      "                         scale, dscale, 64, -64.0f, dcolour, 0.5f, 0.5f,\n"
      "                         1.0f, NULL, 0);\n    a = slot_animator"),
    M("anim-dalpha", "dscale, 0, 128.0f, colour,\n"
      "                         scale, dscale, 64, -64.0f, dcolour, 0.5f, 0.5f,\n"
      "                         1.0f, NULL, 0);\n    a = slot_animator",
      "dscale, 0, 127.0f, colour,\n"
      "                         scale, dscale, 64, -64.0f, dcolour, 0.5f, 0.5f,\n"
      "                         1.0f, NULL, 0);\n    a = slot_animator"),
    M("anim-alpha1", "                         scale, dscale, 64, -64.0f, dcolour, 0.5f, 0.5f,\n"
      "                         1.0f, NULL, 0);\n    p->tScoreAnimation",
      "                         scale, dscale, 63, -64.0f, dcolour, 0.5f, 0.5f,\n"
      "                         1.0f, NULL, 0);\n    p->tScoreAnimation"),
    M("anim-dalpha2", "                         scale, dscale, 64, -64.0f, dcolour, 0.5f, 0.5f,\n"
      "                         1.0f, NULL, 0);\n    p->tScoreAnimation",
      "                         scale, dscale, 64, -60.0f, dcolour, 0.5f, 0.5f,\n"
      "                         1.0f, NULL, 0);\n    p->tScoreAnimation"),
    M("anim-durations", "                         scale, dscale, 64, -64.0f, dcolour, 0.5f, 0.5f,\n"
      "                         1.0f, NULL, 0);\n    p->tScoreAnimation",
      "                         scale, dscale, 64, -64.0f, dcolour, 0.5f, 1.0f,\n"
      "                         0.5f, NULL, 0);\n    p->tScoreAnimation"),
    M("anim-real-timer", "                         1.0f, NULL, 0);\n    p->tScoreAnimation",
      "                         1.0f, NULL, 1);\n    p->tScoreAnimation"),
    M("anim-scale1-dscale", "&at, &d, &d2, scale, dscale, 0, 128.0f, colour,\n"
      "                         scale, dscale, 64, -64.0f, dcolour, 0.5f, 0.5f,\n"
      "                         1.0f, NULL, 0);\n    a = slot_animator",
      "&at, &d, &d2, scale, dscale, 0, 128.0f, colour,\n"
      "                         dscale, dscale, 64, -64.0f, dcolour, 0.5f, 0.5f,\n"
      "                         1.0f, NULL, 0);\n    a = slot_animator"),
    M("anim-colours-swapped", "0, 128.0f, colour,\n"
      "                         scale, dscale, 64, -64.0f, dcolour, 0.5f, 0.5f,\n"
      "                         1.0f, NULL, 0);\n    a = slot_animator",
      "0, 128.0f, dcolour,\n"
      "                         scale, dscale, 64, -64.0f, colour, 0.5f, 0.5f,\n"
      "                         1.0f, NULL, 0);\n    a = slot_animator"),
    M("anim-dpos2-is-dpos", "    hudanim_start_scored(a, (struct FlailerTextChunk *)(void *)\n"
      "                            p->pFlailerEventTitle,\n"
      "                         &at, &d, &d2,",
      "    hudanim_start_scored(a, (struct FlailerTextChunk *)(void *)\n"
      "                            p->pFlailerEventTitle,\n"
      "                         &at, &d, &d,"),
    M("anim-no-prev-copy", "    b_snprintf(p->strPrevScore, sizeof p->strPrevScore, \"%s\",\n"
      "               p->strEventScore);\n", ""),
    M("anim-prev-before-add", "    a = slot_animator(p, SLOT_SCORE);\n    if (a->bActive)",
      "    b_snprintf(p->strPrevScore, sizeof p->strPrevScore, \"%s\",\n"
      "               p->strEventScore);\n    a = slot_animator(p, SLOT_SCORE);\n    if (a->bActive)"),
    M("anim-title-up", "#define SCORE_TITLE_UP    20.0f", "#define SCORE_TITLE_UP    21.0f"),
    M("anim-title-down", "    at.y = at.y - SCORE_TITLE_UP;", "    at.y = at.y + SCORE_TITLE_UP;"),
    M("anim-no-stamp", "    p->tScoreAnimation.PackedTime = (uint32_t)WorldTimer;\n", ""),
    M("anim-stamp-real", "    p->tScoreAnimation.PackedTime = (uint32_t)WorldTimer;",
      "    p->tScoreAnimation.PackedTime = (uint32_t)RealTimer;"),
    M("anim-slots-order", "    a = slot_animator(p, SLOT_TITLE);\n    b_snprintf",
      "    b_snprintf"),

    # StartScore's place.
    M("default-x", "#define SCORE_X          530.0f", "#define SCORE_X          520.0f"),
    M("default-y", "#define SCORE_Y          236.0f", "#define SCORE_Y          246.0f"),
    M("default-scale", "#define SCORE_SCALE        0.7f", "#define SCORE_SCALE        0.75f"),
    M("default-scale-y", "    bVector2 scale = { SCORE_SCALE, SCORE_SCALE };",
      "    bVector2 scale = { SCORE_SCALE, 1.0f };"),
    M("default-dx2", "#define SCORE_DX2         90.0f", "#define SCORE_DX2         80.0f"),
    M("default-dy2", "#define SCORE_DY2       -100.0f", "#define SCORE_DY2        100.0f"),
    M("default-dpos", "    bVector2 dpos = { 0.0f, 0.0f };", "    bVector2 dpos = { 0.0f, 1.0f };"),
    M("default-dscale", "    bVector2 dscale = { 0.0f, 0.0f };",
      "    bVector2 dscale = { 0.5f, 0.0f };"),
    M("default-colour-r", "    bVector4 colour = { 128.0f, 64.0f, 0.0f, 0.0f };",
      "    bVector4 colour = { 127.0f, 64.0f, 0.0f, 0.0f };"),
    M("default-colour-b", "    bVector4 colour = { 128.0f, 64.0f, 0.0f, 0.0f };",
      "    bVector4 colour = { 128.0f, 64.0f, 8.0f, 0.0f };"),
    M("default-dcolour-g", "    bVector4 dcolour = { 0.0f, 64.0f, 128.0f, 0.0f };",
      "    bVector4 dcolour = { 0.0f, 60.0f, 128.0f, 0.0f };"),
    M("default-dcolour-r", "    bVector4 dcolour = { 0.0f, 64.0f, 128.0f, 0.0f };",
      "    bVector4 dcolour = { 4.0f, 64.0f, 128.0f, 0.0f };"),

    # The finish bonus.
    M("bonus-1", "            p, ScoreInfoTable[SCORING_1ST_PLACE_BONUS].Score);",
      "            p, ScoreInfoTable[SCORING_2ND_PLACE_BONUS].Score);"),
    M("bonus-3", "            p, ScoreInfoTable[SCORING_3RD_PLACE_BONUS].Score);",
      "            p, ScoreInfoTable[SCORING_2ND_PLACE_BONUS].Score);"),
    M("bonus-place-2", "    if (place == 2)", "    if (place == 4)"),
    M("bonus-else", "    return 0;\n}\n\n// Retail prints",
      "    return 1;\n}\n\n// Retail prints"),

    # StartScore.
    M("score-no-sound", "    play_score_sound(scoring);\n    b_snprintf(p->strEventScore",
      "    b_snprintf(p->strEventScore"),
    M("score-no-score", "    b_snprintf(p->strEventScore, sizeof p->strEventScore, \"%s\", info->Score);\n", ""),
    M("score-name", "               translate(info->NameId));",
      "               info->Name);"),
    M("score-no-title", "    b_snprintf(p->strEventTitle, sizeof p->strEventTitle, \"%s\",\n"
      "               translate(info->NameId));\n", ""),
    M("scorev-no-sound", "    (void)value;\n    play_score_sound(scoring);\n",
      "    (void)value;\n"),
    M("scorev-no-title", "    b_snprintf(p->strEventTitle, sizeof p->strEventTitle, \"%s\",\n"
      "               translate(ScoreInfoTable[scoring].NameId));\n", ""),
    M("scorev-prints-score", "    (void)value;\n",
      "    b_snprintf(p->strEventScore, sizeof p->strEventScore, \"%d\", value);\n"),

    # The blink.
    M("blink-no-hang", "        p->HangTime = 0.0f;\n        bResetGlare = 1;",
      "        bResetGlare = 1;"),
    M("blink-no-glare", "        bResetGlare = 1;\n        return;", "        return;"),
    M("blink-goes-on", "        bResetGlare = 1;\n        return;\n    }",
      "        bResetGlare = 1;\n    }"),

    # The laps.
    M("lap-reason", "    if (rc != NULL && rc->FinishReason == 0 && ",
      "    if (rc != NULL && "),
    M("lap-crossed", " && rc->CrossedFinishLine != 0)\n        score_lap", ")\n        score_lap"),
    M("lap-time-trial", "TheRaceParameters.RaceType == RACE_TYPE_TIME_TRIAL",
      "TheRaceParameters.RaceType != RACE_TYPE_TIME_TRIAL"),
    M("lap-ttt-unchecked", "        && timer_is_valid(&TheRaceParameters.TimeTrialTime))",
      "        )"),
    M("lap-ttt-nonzero", "        && timer_is_valid(&TheRaceParameters.TimeTrialTime))",
      "        && TheRaceParameters.TimeTrialTime.PackedTime != 0)"),
    M("lap-cop-ignored", "        timed = TheRaceParameters.BeACop == 0;", "        timed = 1;"),
    M("lap-p2p-ignored", "    if (timed || TheRaceParameters.Point2Point != 0) {",
      "    if (timed) {"),
    M("seg-no-score", "        if (!p->bSegmentCollisionDetected)\n            player_start_score(p, SCORING_CLEAN_SEGMENT);\n        p->bSegmentCollisionDetected = 0;\n        return;",
      "        p->bSegmentCollisionDetected = 0;\n        return;"),
    M("seg-always", "        if (!p->bSegmentCollisionDetected)\n            player_start_score(p, SCORING_CLEAN_SEGMENT);\n        p->bSegmentCollisionDetected = 0;\n        return;",
      "        player_start_score(p, SCORING_CLEAN_SEGMENT);\n        p->bSegmentCollisionDetected = 0;\n        return;"),
    M("seg-no-clear", "            player_start_score(p, SCORING_CLEAN_SEGMENT);\n        p->bSegmentCollisionDetected = 0;\n        return;",
      "            player_start_score(p, SCORING_CLEAN_SEGMENT);\n        return;"),
    M("seg-clears-collision", "            player_start_score(p, SCORING_CLEAN_SEGMENT);\n        p->bSegmentCollisionDetected = 0;\n        return;",
      "            player_start_score(p, SCORING_CLEAN_SEGMENT);\n        p->bSegmentCollisionDetected = 0;\n        p->bCollisionDetected = 0;\n        return;"),
    M("clean-lap-scoring", "        player_start_score(p, SCORING_CLEAN_LAP);",
      "        player_start_score(p, SCORING_CLEAN_SEGMENT);"),
    M("clean-lap-no-count", "        p->numCleanLaps = p->numCleanLaps + 1;\n", ""),
    M("led-position", "    } else if (rc->RacePosition == 1) {",
      "    } else if (rc->RacePosition <= 1) {"),
    M("led-first", "        player_start_score(p, rc->NumLapsCompleted == 1",
      "        player_start_score(p, rc->NumLapsCompleted <= 1"),
    M("led-swapped", "                                  ? SCORING_LED_FIRST_LAP\n"
      "                                  : SCORING_LED_A_LAP);",
      "                                  ? SCORING_LED_A_LAP\n"
      "                                  : SCORING_LED_FIRST_LAP);"),
    M("lap-seg-unchecked", "    } else if (!p->bSegmentCollisionDetected && rc->NumLapsCompleted > 0) {",
      "    } else if (rc->NumLapsCompleted > 0) {"),
    M("lap-seg-laps", "    } else if (!p->bSegmentCollisionDetected && rc->NumLapsCompleted > 0) {",
      "    } else if (!p->bSegmentCollisionDetected && rc->NumLapsCompleted >= 0) {"),
    M("lap-no-seg-clear", "    }\n    p->bSegmentCollisionDetected = 0;\n    p->bCollisionDetected = 0;\n}",
      "    }\n    p->bCollisionDetected = 0;\n}"),
    M("lap-no-coll-clear", "    p->bSegmentCollisionDetected = 0;\n    p->bCollisionDetected = 0;\n}",
      "    p->bSegmentCollisionDetected = 0;\n}"),
    M("top-ignored", "    if (p->bNewTopSpeed)\n        player_start_score(p, SCORING_TOP_SPEED);\n", ""),
    M("top-clears", "        player_start_score(p, SCORING_TOP_SPEED);\n",
      "        player_start_score(p, SCORING_TOP_SPEED);\n    p->bNewTopSpeed = 0;\n"),
    M("top-after-knock", "    if (p->bNewTopSpeed)\n        player_start_score(p, SCORING_TOP_SPEED);\n    score_knock(p, car);\n",
      "    score_knock(p, car);\n    if (p->bNewTopSpeed)\n        player_start_score(p, SCORING_TOP_SPEED);\n"),

    # The knocks.
    M("knock-body-index", "        &car->pDynamicCollisionBody->Dynamic.Body, 0);",
      "        &car->pDynamicCollisionBody->Dynamic.Body, 1);"),
    M("knock-which-car1", "    if (car1 != NULL && car1->pPlayer == p)\n        which = 0;\n", ""),
    M("knock-which-car2", "    if (car2 != NULL && car2->pPlayer == p)\n        which = 1;\n", ""),
    M("knock-which-any", "    if (car1 != NULL && car1->pPlayer == p)",
      "    if (car1 != NULL && car1->pPlayer != NULL)"),
    M("knock-which-order", "    if (car1 != NULL && car1->pPlayer == p)\n        which = 0;\n"
      "    if (car2 != NULL && car2->pPlayer == p)\n        which = 1;\n",
      "    if (car2 != NULL && car2->pPlayer == p)\n        which = 1;\n"
      "    if (car1 != NULL && car1->pPlayer == p)\n        which = 0;\n"),
    M("knock-stranger-keeps", "    if (which < 0) {\n        p->bSmokeableHit = 0;\n        return;",
      "    if (which < 0) {\n        return;"),
    M("knock-own-mass", "    other = which == 0 ? m2 : m1;", "    other = which == 0 ? m1 : m2;"),
    M("knock-mass-order", "    m1 = get_mass_inverse(c->pWitness->pBody1);\n"
      "    m2 = get_mass_inverse(c->pWitness->pBody2);",
      "    m2 = get_mass_inverse(c->pWitness->pBody2);\n"
      "    m1 = get_mass_inverse(c->pWitness->pBody1);"),
    M("knock-mass-le", "    if (!(other < KNOCK_MASS_INVERSE))",
      "    if (!(other <= KNOCK_MASS_INVERSE))"),
    M("knock-mass-limit", "#define KNOCK_MASS_INVERSE 500.0f", "#define KNOCK_MASS_INVERSE 499.0f"),
    M("knock-in-air", "    if (!(p->HangTime == 0.0f))\n        return;\n", ""),
    M("knock-level-hi", "    if (!(d < KNOCK_LEVEL) || ", "    if (!(d <= KNOCK_LEVEL) || "),
    M("knock-level-lo", "|| !(-KNOCK_LEVEL < d) ||", "|| !(-KNOCK_LEVEL <= d) ||"),
    M("knock-level-no-lo", "    if (!(d < KNOCK_LEVEL) || !(-KNOCK_LEVEL < d) || d == 0.0f)",
      "    if (!(d < KNOCK_LEVEL) || d == 0.0f)"),
    M("knock-level-zero", " || d == 0.0f)\n        return;", ")\n        return;"),
    M("knock-level", "#define KNOCK_LEVEL          0.8f", "#define KNOCK_LEVEL          0.75f"),
    M("knock-dot-w", "    return (a->x * b->x + a->y * b->y) + a->z * b->z;",
      "    return (a->x * b->x + a->y * b->y) + a->z * b->z + a->pad * b->w;"),
    M("knock-dot-order", "    return (a->x * b->x + a->y * b->y) + a->z * b->z;",
      "    return a->x * b->x + (a->y * b->y + a->z * b->z);"),
    M("knock-up-row1", "    d = dot3(&c->ImpulseDirection, &car->State.BodyMatrix.v2);",
      "    d = dot3(&c->ImpulseDirection, &car->State.BodyMatrix.v1);"),
    M("knock-total", "    d = dot3(&c->ImpulseDirection, &car->State.BodyMatrix.v2);",
      "    d = dot3(&c->TotalImpulse, &car->State.BodyMatrix.v2);"),
    M("knock-impulse-le", "    if (!(KNOCK_IMPULSE < c->TotalImpulseMagnitude))",
      "    if (!(KNOCK_IMPULSE <= c->TotalImpulseMagnitude))"),
    M("knock-impulse", "#define KNOCK_IMPULSE        8.3333f", "#define KNOCK_IMPULSE        8.3334f"),
    M("knock-no-coll", "    p->bCollisionDetected = 1;\n    p->bSegmentCollisionDetected = 1;",
      "    p->bSegmentCollisionDetected = 1;"),
    M("knock-no-seg", "    p->bSegmentCollisionDetected = 1;\n    p->New2540 = 0;",
      "    p->New2540 = 0;"),
    M("knock-no-2540", "    p->New2540 = 0;\n", ""),
    M("knock-smoke-ignored", "    if (collision_is_smokeable_involved(c)) {\n"
      "        if (!p->bSmokeableHit)\n            p->bSmokeableHit = 1;\n"
      "    } else {\n        p->bSmokeableHit = 0;\n    }",
      "    p->bSmokeableHit = 0;"),
    M("knock-smoke-toggle", "        if (!p->bSmokeableHit)\n            p->bSmokeableHit = 1;",
      "        p->bSmokeableHit = !p->bSmokeableHit;"),
    M("knock-smoke-keeps", "    } else {\n        p->bSmokeableHit = 0;\n    }\n}",
      "    }\n}"),

    # The air.
    M("air-wheels", "    if (car->State.nWheelsTouchingGround == 0) {",
      "    if (car->State.nWheelsTouchingGround <= 0) {"),
    M("air-restamps", "        if (p->HangTime == 0.0f)\n            p->HangTime = (float)WorldTimer * TICK_SECONDS;",
      "        p->HangTime = (float)WorldTimer * TICK_SECONDS;"),
    M("air-tick", "#define TICK_SECONDS 0.00025f", "#define TICK_SECONDS 0.0002501f"),
    M("air-landed-zero-kept", "    if (p->HangTime == 0.0f) {\n        p->HangTime = 0.0f;\n        return;",
      "    if (p->HangTime == 0.0f) {\n        return;"),
    M("air-rate", "#define AIR_PER_SECOND     250.0f", "#define AIR_PER_SECOND     251.0f"),
    M("air-step", "#define AIR_STEP              50", "#define AIR_STEP              25"),
    M("air-unstepped", "    air = air / AIR_STEP * AIR_STEP;\n", ""),
    M("air-ieee", "    air = ee_trunc_w(((float)WorldTimer * TICK_SECONDS - p->HangTime)\n"
      "                     * AIR_PER_SECOND);",
      "    air = (int32_t)(((float)WorldTimer * TICK_SECONDS - p->HangTime)\n"
      "                     * AIR_PER_SECOND);"),
    M("air-band-lo", "    if ((uint32_t)air - 100u < 100u) {", "    if ((uint32_t)air - 50u < 150u) {"),
    M("air-band-signed", "    if ((uint32_t)air - 100u < 100u) {", "    if (air - 100 < 100) {"),
    M("air-big-lo", "    if ((uint32_t)air - 200u < 150u) {", "    if ((uint32_t)air - 200u < 100u) {"),
    M("air-huge", "    if (air >= 350) {", "    if (air > 350) {"),
    M("air-scoring", "        player_start_score_value(p, SCORING_AIR, air);",
      "        player_start_score_value(p, SCORING_BIG_AIR, air);"),
    M("air-huge-scoring", "        player_start_score_value(p, SCORING_HUGE_AIR, air);",
      "        player_start_score_value(p, SCORING_BIG_AIR, air);"),
    M("air-no-text", "        b_snprintf(p->strEventScore, sizeof p->strEventScore, \"+%d\", air);\n"
      "        player_start_score_value(p, SCORING_AIR, air);",
      "        player_start_score_value(p, SCORING_AIR, air);"),
    M("air-text-unsigned", "        b_snprintf(p->strEventScore, sizeof p->strEventScore, \"+%d\", air);\n"
      "        player_start_score_value(p, SCORING_HUGE_AIR, air);",
      "        b_snprintf(p->strEventScore, sizeof p->strEventScore, \"%d\", air);\n"
      "        player_start_score_value(p, SCORING_HUGE_AIR, air);"),
    M("air-no-reset", "        player_start_score_value(p, SCORING_HUGE_AIR, air);\n    }\n    p->HangTime = 0.0f;",
      "        player_start_score_value(p, SCORING_HUGE_AIR, air);\n    }"),

    # The places.
    M("place-flag", "    if (p->PositionFlag > 0) {", "    if (p->PositionFlag != 0) {"),
    M("place-twice", "        if (reached != NULL && !*reached && !TheRaceParameters.BeACop) {",
      "        if (reached != NULL && !TheRaceParameters.BeACop) {"),
    M("place-cop", "        if (reached != NULL && !*reached && !TheRaceParameters.BeACop) {",
      "        if (reached != NULL && !*reached) {"),
    M("place-scoring", "            player_start_score(p, pos + SCORING_START_BONUS);",
      "            player_start_score(p, pos + SCORING_TOOK_1ST_PLACE);"),
    M("place-no-mark", "            *reached = 1;\n", ""),
    M("place-index", "p->baPlaceReached + 4 * (pos - 1));",
      "p->baPlaceReached + 4 * pos);"),
    M("place-lo", "    if (pos < -1 || ", "    if (pos < 0 || "),
    M("place-hi", "|| pos >= NUM_SCORE_INFOS - SCORING_START_BONUS)",
      "|| pos >= NUM_SCORE_INFOS - SCORING_START_BONUS - 1)"),
    M("place-flag-kept", "    }\n    p->PositionFlag = 0;\n}", "    }\n}"),
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
