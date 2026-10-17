#!/usr/bin/env python3
"""Cross-check 3DS Files/source/hudrender.c, the HUD drawn each frame, and
racesplit.c's split times against the retail image, SLES_507.31.

**The model** is retail's own: Player::UpdateHud (0x0017ecf0), RenderHud
(0x0017f040), GetCurrentBestLapRecord (0x0017ef60), and under them the
score fade (0x0017d7c8), ConvertScoreString, DisplayDebugInfo,
GetLetterForGear, TriggerTimerWarningSound, Race::CalculateSplitTime,
Timer::SetTime and PrintToString, the RacingCar accessors,
GetFinishReasonID, DriverInfo::GetName, the short name's accessor
(0x00187ed8), tCopManager::GetPursuitLevelForHUD and GetNumTickets,
0x00224ec0, RaceParameters::NumEliminated, IsReplayDemoMode, bSPrintf
with its float conversions, bStringHash, DetermineHudFeatures and
SetHudFeatures as tools/hudfeatures_check.py runs them, and the whole
Flailer runtime on INGAMEB's Flailer chunk. The harness
(tools/src/hudrender_test.c) runs hudrender.c over playerhud.c,
racesplit.c, timer.c, flailer.c, bui.c, bchunk.c, copmanager.c and
raceparams.c on the same bundle.

**The stubs** are hudfeatures_check.py's, and the callees not ported,
each printing its arguments: HudDoAnimations, UpdateScoring, StartScore,
HudStartSpeedAnimation, HudStartGrowAnimation, UpdatePursuitMeter,
UpdateRadarDetector, DrawTracker, NISOverlayManager::Update,
GetTranslatedString (a string made from the id), GetCarByDriverNumber
(the script's car of that number), GetSkinInfo (a skin whose swatch is
made from the car and skin), Race::GetLapNumberExact (the script's
answer), TimeAroundTrackTable::GetTimeAroundTrack (64 seconds a lap and a
half more), GetCurrentZoneNumber (the script's), GetInGameSample and
bSample::Play.

**Compared** are the stubs' calls in order, GetCurrentBestLapRecord's
answers, and after each op every line that changed: hudfeatures_check.py's
Player fields, RenderHud's own (the speeds, positions, places reached, the
start bonus's text, the score animation's timer and the debug texts) and
every Flailer object's bytes. Every pointer field starts at a dummy object,
so one nothing writes prints "stray" until something does.

**The script** sets the players up as hudfeatures_check.py does, gives
them a race of six cars, a World of AI racers and cops and a cop manager,
then takes RenderHud through each section on its own -- the speedo and
tach, the lead, the lap time, the best lap, the splits, the leaderboard,
the lap counter, the race position, the tyres, the pursuit and radar
calls, Be The Cop, the NIS overlay, the trackers and the debug texts --
and last UpdateHud whole: the score fade, the start bonus in one- and
two-player races and the states that skip the scoring.

    python tools/hudrender_check.py
    python tools/hudrender_check.py --mutate [--only a,b]
    python tools/hudrender_check.py --dump out/hudrender
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

HARNESS = "tools/src/hudrender_test.c"
HUDRENDER = "3DS Files/source/hudrender.c"
RACESPLIT = "3DS Files/source/racesplit.c"
SOURCES = [HARNESS, HUDRENDER, RACESPLIT, "3DS Files/source/timer.c",
           "3DS Files/source/playerhud.c", "3DS Files/source/flailer.c",
           "3DS Files/source/bprintf.c", "3DS Files/source/bui.c",
           "3DS Files/source/bchunk.c",
           "3DS Files/source/replay.c", "3DS Files/source/p32.c",
           "3DS Files/source/copmanager.c", "3DS Files/source/raceparams.c"]

GP = fc.GP
RP = hc.RP
G_WORLD = GP - 22120                    # pCurrentWorld
G_TIMER = GP - 19576                    # WorldTimer
G_WFRAMES = GP - 19564                  # WorldTimeFrames
G_LOOP = GP - 19552                     # WorldLoopCounter
G_BY_INDEX = GP - 20928                 # Player::pPlayersByIndex[2]
G_FOLLOW = GP - 21532                   # CameraFollowDefaultCar
G_FOLLOW_CAR = GP - 21528               # CameraFollowThisCarInstead
G_LIVE = GP - 20944                     # LiveUpdateSplitTimeRate
G_SMF = GP - 20912                      # SpeedMinFactor
G_TACH = GP - 18380                     # TachTestRpm
G_DEBUG = GP - 20700                    # DisplayPlayerDebugInfo
G_CPU = GP - 23240                      # the CPU frame rate shown
G_GPU = GP - 23236                      # the GPU frame rate shown
G_WARN = GP - 13388                     # TriggerTimerWarningSound's second
LANGUAGE = 0x0031c1c8                   # TheLanguageManager's CurrLanguage

F_UPDATE = 0x0017ecf0
F_RENDER = 0x0017f040
F_BEST = 0x0017ef60
F_CONVERT = 0x0017e220                  # ConvertScoreString

S_ANIMS = 0x0017e038
S_SCORING = 0x0017e820
S_START_SCORE = 0x0017e558
S_SPEED_ANIM = 0x0017cd30
S_GROW_ANIM = 0x0017cb18
S_PURSUIT = 0x0017c380
S_RADAR = 0x0017be70
S_TRACKER = 0x0017c278
S_NIS_UPDATE = 0x001825f0
S_TRANSLATE = 0x0021e560
S_BY_DRIVER = 0x0014d5d0
S_SKIN = 0x00188180
S_LAP_EXACT = 0x00147d58
S_TATT = 0x00146b90
S_ZONE = 0x0014f8e0
S_SAMPLE = 0x001ae280
S_PLAY = 0x00274080

NCARS = 10
NPURSUITS = 3
NCOPS = 7
WORLD_MAX_CARS = 14

# RenderHud's and UpdateHud's own Player fields, after hudfeatures_check's:
# name, kind (p an object, w a word, s a string) and count.
RENDER_FIELDS = [
    ("pFlailerCFPSString", "p", 1), ("pFlailerGFPSString", "p", 1),
    ("pFlailerPosString", "p", 1), ("pFlailerDistString", "p", 1),
    ("strEventScore", "s", 1), ("PosChangeTime", "w", 1),
    ("PositionFlag", "w", 1), ("LastRacePosition", "w", 1),
    ("LastSpeed", "w", 1), ("TopSpeed", "w", 1), ("bNewTopSpeed", "w", 1),
    ("bCheckTopSpeed", "w", 1), ("SpeedFactor", "w", 1),
    ("baPlaceReached", "w", 8), ("tScoreAnimation", "w", 1),
    ("New2736", "w", 1),
]
OFFSET = hc.OFFSET

# The script's names: retail offset and size.
RP_FIELDS = dict(hc.RP_FIELDS)
RP_FIELDS.update({"New624": (624, 4)})
PLAYER_SET = dict(hc.PLAYER_SET)
PLAYER_SET.update({
    "trans": (35, 1), "split": (38, 1), "gender": (39, 1),
    "besttotal": (64, 4), "bestlap": (68, 4),
    "poschange": (OFFSET["PosChangeTime"], 4),
    "posflag": (OFFSET["PositionFlag"], 4),
    "lastpos": (OFFSET["LastRacePosition"], 4),
    "lastspeed": (OFFSET["LastSpeed"], 4),
    "topspeed": (OFFSET["TopSpeed"], 4),
    "newtop": (OFFSET["bNewTopSpeed"], 4),
    "checktop": (OFFSET["bCheckTopSpeed"], 4),
    "sf": (OFFSET["SpeedFactor"], 4),
    "tscore": (OFFSET["tScoreAnimation"], 4),
    "new2736": (OFFSET["New2736"], 4),
})
# A Car's words at retail's offsets: the CarState ones from 876 on are the
# port's plus four.
CAR_SET = {
    "idx": (8, 2), "px": (96, 4), "py": (100, 4), "pz": (104, 4),
    "odo": (936, 4), "speed": (960, 4), "gear": (968, 4), "rpm": (976, 4),
    "clutch": (984, 4), "render": (1192, 1),
}
CAR_WTU = 916
RC_SET = {
    "hbr": (6, 2), "laps": (9, 1), "pos": (10, 1), "reason": (18, 2),
    "clne": (20, 4), "flne": (32, 4), "time": (180, 4),
}
RC_TIMES = {"bct": 36, "run": 56, "prun": 76, "best": 96, "pbest": 116}
RACE_SET = {
    "stage": (0, 4), "start": (12, 4), "n": (24, 4), "fin": (28, 4),
    "laps": (1604, 4), "slb": (1618, 1), "flb": (1619, 1),
}

HUD_SINGLE = hc.HUD_SINGLE
HUD_TOP = hc.HUD_TOP
HUD_BOTTOM = hc.HUD_BOTTOM


def fbits(v):
    return struct.unpack("<I", struct.pack("<f", v))[0]


def F(v):
    return "%#x" % fbits(v)


# ================================================================== script

ALL_1P = (0x40 | 0x8 | 0x400 | 0x100 | 0x80 | 0x800000 | 0x200 | 0x2
          | 0x8000 | 0x80000 | 0x100000)


def common():
    """hudfeatures_check's two players, then a race of six cars, a World
    and a cop manager around them."""
    s = hc.common()
    s += ["car|0|reason|0", "car|1|reason|0", "g|wframes|1000",
          "g|loop|7", "g|timer|400000", "g|lang|0", "g|follow|1",
          "g|followcar|-1", "pn|0|ANDREW", "pn|1|P2",
          "g|byidx|0|0", "g|byidx|1|-1", "w|on|1", "w|heli|1",
          "rp|New624|1"]
    for c in range(NCARS):
        s += ["car|%d|idx|%d" % (c, c), "car|%d|type|%d" % (c, 3 + c % 5),
              "car|%d|skin|%d" % (c, c % 3), "car|%d|short|%#x"
              % (c, 0x4a000 + c), "car|%d|maxrpm|%s" % (c, F(8000.0)),
              "car|%d|redline|%s" % (c, F(6750.0)),
              "car|%d|driver|1" % c, "car|%d|render|1" % c]
    # The gauges' angles and ranges: MPH and KPH alike to begin with.
    for c in (0, 1):
        for off, v in ((4, 40.0), (8, 250.0), (24, 30.0), (28, 270.0),
                       (32, 20.0), (36, 300.0), (40, 0.0), (44, 180.0),
                       (48, 0.0), (52, 290.0)):
            s.append("car|%d|hud|%d|%s" % (c, off, F(v)))
    # The race: six cars, player 0's second.
    s += ["race|n|6", "race|fin|0", "race|laps|3", "race|slb|0",
          "race|flb|0", "race|start|1000", "race|stage|4"]
    for i, c in enumerate((2, 0, 3, 4, 1, 5)):
        s += ["race|car|%d|%d" % (i, c), "rc|%d|pos|%d" % (c, i + 1),
              "rc|%d|laps|1" % c,
              "rc|%d|clne|%s" % (c, F(1.5 - 0.0625 * i)),
              "rc|%d|flne|%s" % (c, F(1.5 - 0.0625 * i)),
              "rc|%d|bct|0|%d" % (c, 300000 + 1000 * i)]
    s += ["race|car|6|-1", "race|car|7|-1"]
    # The World: AI racers 2-5, cops 6-8, then traffic.
    s += ["w|ai|0", "w|cop|4", "w|traffic|7"]
    for i, c in enumerate((2, 3, 4, 5, 6, 7, 8)):
        s.append("w|table|%d|%d" % (i, c))
    return s


def s_gauges():
    s = ["use|0", "set|0x40"]
    # Speeds through the range, each frame popping the digits on a fifty.
    for v in (0.0, 10.0, 44.7, 45.0, 60.0, 80.5, 120.0, -12.0, 0.0):
        s += ["car|0|speed|%s" % F(v), "ren"]
    # The top speed: the first frame sets it from SpeedFactor, then a check
    # armed below SpeedMinFactor fires once the speed falls back.
    s += ["pl|0|topspeed|0", "pl|0|sf|%s" % F(0.75), "car|0|speed|%s"
          % F(10.0), "ren"]
    for v in (60.0, 75.0, 79.0, 78.0, 70.0, 20.0, 79.5, 79.4):
        s += ["car|0|speed|%s" % F(v), "ren"]
    s += ["rp|BeACop|1", "car|0|speed|%s" % F(10.0), "ren",
          "car|0|speed|%s" % F(79.0), "ren", "car|0|speed|%s" % F(78.0),
          "ren", "rp|BeACop|0", "pl|0|sf|%s" % F(0.95),
          "car|0|speed|%s" % F(10.0), "ren", "car|0|speed|%s" % F(80.0),
          "ren", "car|0|speed|%s" % F(79.0), "ren"]
    # Kilometres, and a dial that wraps through 360 both ways.
    s += ["rp|Units|1", "car|0|speed|%s" % F(30.0), "ren",
          "car|0|hud|32|%s" % F(300.0), "car|0|hud|36|%s" % F(60.0), "ren",
          "car|0|speed|%s" % F(75.0), "ren",
          "car|0|hud|32|%s" % F(-100.0), "car|0|hud|36|%s" % F(-50.0),
          "ren", "car|0|hud|32|%s" % F(20.0), "car|0|hud|36|%s" % F(300.0),
          "rp|Units|2", "ren", "rp|Units|0"]
    # The tach: the test rpm, the red line in gear, each gear, the clutch,
    # an automatic.
    s += ["car|0|rpm|%s" % F(3000.0), "ren", "car|0|rpm|%s" % F(7000.0),
          "ren", "pl|0|trans|1", "car|0|gear|3", "ren",
          "car|0|rpm|%s" % F(6750.0), "ren",
          "car|0|rpm|%s" % F(6749.5), "ren", "car|0|rpm|%s" % F(7000.0),
          "car|0|gear|0", "ren",
          "car|0|gear|3", "ren", "car|0|rpm|%s" % F(9000.0), "ren",
          "car|0|rpm|%s" % F(-50.0), "ren", "g|tach|%s" % F(4321.0), "ren",
          "g|tach|%s" % F(100.0)]
    for g in (-1, 1, 2, 4, 8, 9, -2):
        s += ["car|0|gear|%d" % g, "car|0|clutch|%d" % (g & 1), "ren"]
    s += ["car|0|redline|%s" % F(7777.0), "ren", "pl|0|trans|0", "ren",
          "car|0|gear|3", "car|0|clutch|1"]
    # The other gauges: the bumper view's angles, the in-car digits.
    s += ["set|0x20", "car|0|rpm|%s" % F(5000.0), "ren",
          "car|0|speed|%s" % F(50.0), "ren", "set|0x10000020",
          "car|0|speed|%s" % F(70.0), "pl|0|lastspeed|40", "ren",
          "set|0x10000000", "ren", "set|0", "ren", "set|0x40",
          "car|0|speed|%s" % F(0.0), "ren"]
    return s


def s_laps():
    s = ["use|0", "set|%#x" % (0x8 | 0x400 | 0x100 | 0x40)]
    # The lap time counting up, then down in a time trial.
    for t in (300000, 0, 0x7fffffff):
        s += ["rc|0|bct|0|%d" % t, "ren"]
    s += ["rc|0|bct|0|300000", "g|timer|410000", "ren",
          "rp|TTT|200000", "ren", "g|timer|303000", "ren",
          "rc|0|run|0|150000", "ren", "rc|0|run|0|0x7fffffff", "ren",
          "rc|0|run|0|150000", "g|timer|480000", "ren",
          "g|timer|465000", "ren", "g|timer|465100", "ren",
          "g|timer|468100", "ren", "g|timer|520000", "ren",
          "rp|TTT|0x7fffffff", "ren", "rp|TTT|0", "g|timer|400000"]
    # The best lap: the record, the car's best, a time trial, point to
    # point.
    s += ["pl|0|bestlap|0", "ren", "pl|0|bestlap|99000", "ren",
          "rc|0|best|0|88000", "ren", "rc|0|best|0|0x7fffffff", "ren",
          "rc|0|best|0|120000", "ren", "pl|0|bestlap|0x7fffffff",
          "rc|0|best|0|0", "ren", "rc|0|best|0|77000", "ren",
          "rp|RaceType|2", "ren", "rp|RaceType|1", "rp|P2P|1",
          "pl|0|besttotal|400123", "ren", "pl|0|besttotal|0", "ren",
          "rp|P2P|0", "race|flb|9", "ren", "race|flb|0",
          "rc|0|best|0|0"]
    for prev in (0, 1):
        s += ["best|%d" % prev, "rc|0|pbest|0|55000", "best|%d" % prev,
              "pl|0|bestlap|44000", "best|%d" % prev, "rc|0|pbest|0|0",
              "pl|0|bestlap|0", "rc|0|best|0|66000", "best|%d" % prev,
              "rc|0|best|0|0"]
    # The lap counter, around and point to point.
    s += ["rc|0|laps|0", "ren", "rc|0|laps|2", "race|laps|5", "ren",
          "rp|P2P|1", "race|bd|0|%s" % F(0.25), "g|lapx|%s" % F(0.125),
          "rc|0|clne|%s" % F(0.5), "ren", "rc|0|clne|%s" % F(0.0), "ren",
          "rc|0|clne|%s" % F(1.25), "ren", "g|lapx|%s" % F(1.0),
          "rc|0|clne|%s" % F(0.75), "ren", "g|lapx|%s" % F(0.0),
          "rc|0|clne|%s" % F(0.3337), "ren", "rp|P2P|0", "rc|0|laps|1",
          "race|laps|3", "rc|0|clne|%s" % F(1.5)]
    return s


def s_splits():
    s = ["use|0", "set|%#x" % (0x80 | 0x40)]
    s += ["rc|0|hbr|1", "rc|0|bct|1|398000", "rc|0|run|1|98000", "ren"]
    for st in (0, 1, 2, 3, 4):
        s += ["pl|0|split|%d" % st, "ren", "g|timer|399000", "ren",
              "g|timer|400000"]
    # Each comparison with and without its time.
    s += ["pl|0|split|2", "rc|0|pbest|1|97000", "ren", "rc|0|pbest|1|0",
          "pl|0|split|3", "rc|0|prun|1|99500", "ren", "pl|0|split|1",
          "rc|0|hbr|5", "rc|0|bct|0|398500", "rc|0|run|0|160000", "ren",
          "pl|0|bestlap|150000", "ren", "rc|0|hbr|0", "ren",
          "pl|0|bestlap|0", "pl|0|split|0"]
    # The leader compares against the second; a race of one against none.
    s += ["race|car|0|0", "race|car|1|2", "ren", "race|n|1", "ren",
          "race|n|2", "ren", "race|car|1|-1", "ren", "race|car|1|2",
          "race|n|6", "ren", "race|car|0|2", "race|car|1|0"]
    # A hidden comparison prints in the first 0.2 s past the line: hidden
    # by a frame with no region, then shown again.
    s += ["pl|0|split|0", "rc|0|bct|1|399500"]
    for tm in (399500, 400299, 400300, 400301):
        s += ["rc|0|hbr|-3", "ren", "rc|0|hbr|1", "g|timer|%d" % tm, "ren"]
    s += ["rc|0|hbr|0", "rc|0|bct|1|398000", "g|timer|400000"]

    # The comparison prints once when it shows, so each case is a frame
    # that hides it (no region) and one 0.1 s past the line, with the
    # times it compares changed between them.
    def fresh(i, *ops):
        return (["rc|0|hbr|-3", "ren"] + list(ops)
                + ["rc|0|bct|%d|399600" % i, "rc|0|hbr|%d" % i, "ren"])
    s += fresh(1, "pl|0|split|2", "rc|0|pbest|1|97000",
               "rc|0|prun|1|99500")
    s += fresh(1, "pl|0|split|3")
    s += fresh(1, "rc|0|prun|1|97250")
    # The best lap at the line, the previous best's against the best's;
    # then the record; then away from the line, where there is none.
    s += fresh(0, "pl|0|split|1", "pl|0|bestlap|150000",
               "rc|0|run|0|160000", "rc|0|best|0|88000",
               "rc|0|pbest|0|55000")
    s += fresh(0, "rc|0|pbest|0|0")
    s += fresh(1)
    # A region behind the line: -4 is region 1, -1 region 4 (unset).
    s += ["pl|0|split|3", "rc|0|hbr|-4", "ren", "rc|0|hbr|-1", "ren"]
    # Hidden 0.25 s past the line is too late to print; 0.175 s is not.
    s += ["rc|0|prun|1|96000", "rc|0|hbr|-3", "ren", "rc|0|bct|1|399000",
          "rc|0|hbr|1", "ren", "rc|0|hbr|-3", "ren", "rc|0|bct|1|399300",
          "rc|0|hbr|1", "ren"]
    # Shown, the live rate prints on its frames only.
    s += ["g|live|3", "g|loop|10", "rc|0|prun|1|95000", "ren", "g|loop|11",
          "rc|0|prun|1|94000", "ren", "g|loop|12", "ren", "g|live|0",
          "g|loop|7"]
    s += ["rc|0|pbest|1|0", "rc|0|prun|1|99500", "rc|0|best|0|0",
          "pl|0|bestlap|0", "rc|0|bct|0|398500", "pl|0|split|0",
          "rc|0|hbr|0", "rc|0|bct|1|398000", "ren"]
    # The live update rate and the loop counter.
    s += ["g|timer|399990", "ren", "g|live|3", "ren", "g|loop|9", "ren",
          "g|loop|10", "ren", "g|timer|399000", "ren", "g|live|0", "ren",
          "g|loop|7", "g|timer|400000"]
    # Out of date, unset, a region behind the line.
    s += ["g|timer|404000", "ren", "g|timer|400000", "rc|0|run|0|0", "ren",
          "rc|0|bct|0|0x7fffffff", "ren", "rc|0|hbr|-3", "ren",
          "rc|0|hbr|-5", "ren", "rc|0|hbr|0", "rc|0|bct|0|300000"]
    return s


def s_leaderboard():
    s = ["use|0", "set|%#x" % (0x800000 | 0x40)]
    for frames in (1000, 1050, 1200, 1499, 1600, 2100):
        s += ["g|wframes|%d" % frames, "ren"]
    s += ["g|wframes|1200"]
    # Each car's word: finished, pulled over, a lap and two either way.
    s += ["rc|3|reason|1", "ren", "rc|3|reason|3", "ren", "rc|3|reason|0",
          "cm|on|1", "cm|active|4|1", "ren", "cm|active|4|0",
          "rc|3|clne|%s" % F(2.5), "ren", "rc|3|clne|%s" % F(3.5), "ren",
          "rc|3|clne|%s" % F(0.25), "ren", "rc|3|clne|%s" % F(-0.75), "ren",
          "rc|3|clne|%s" % F(1.375), "rc|3|bct|0|0", "ren",
          "rc|3|bct|0|302000", "car|3|driver|0", "g|wframes|1000", "ren",
          "car|3|driver|1"]
    # Mode 2 follows the player down the order.
    s += ["rp|Leader|2"]
    for pos in (1, 2, 3, 4, 5, 6):
        s += ["rc|0|pos|%d" % pos, "g|wframes|1200", "ren",
              "g|wframes|1000", "ren", "g|wframes|1600", "ren"]
    s += ["race|n|3", "ren", "race|n|9", "race|car|6|-1", "ren",
          "race|n|6", "rp|Leader|1", "ren", "rc|0|pos|2",
          "g|wframes|1000"]
    # Splits by time with each car finished or not.
    s += ["g|wframes|1200", "rc|2|reason|1", "rc|2|time|90000", "ren",
          "rc|0|reason|1", "rc|0|time|95000", "ren", "rc|2|reason|0", "ren",
          "rc|0|reason|0", "ren"]
    return s


def s_position():
    s = ["use|0", "set|%#x" % (0x200 | 0x40)]
    for pos in (2, 2, 1, 3, 3, 6, 4):
        s += ["rc|0|pos|%d" % pos, "ren"]
    s += ["rp|RaceType|3", "race|fin|2", "ren", "rp|RaceType|4", "ren",
          "rp|RaceType|1", "race|fin|0", "pl|0|gender|1", "rc|0|pos|1",
          "ren", "rc|0|pos|2", "ren", "pl|0|gender|0", "rc|0|pos|1", "ren",
          "pl|0|posflag|-1", "ren", "pl|0|posflag|1", "rc|0|pos|2", "ren",
          "pl|0|posflag|0", "ren"]
    return s


def s_tyres():
    s = ["use|0", "set|0x42"]
    for vals in ((0.0, 0.25, 0.5, 0.85), (0.9, 0.95, 0.999, 1.0),
                 (1.5, -0.5, 0.8999, 0.91)):
        for i, v in enumerate(vals):
            s.append("car|0|wtu|%d|%s" % (i, F(v)))
        s.append("ren")
    return s


def s_pursuit():
    s = ["use|0", "cm|on|1", "set|0x8040"]
    s += ["ren", "cm|pur|0|chased|0", "cm|pur|0|level|3", "cm|list|0",
          "ren", "cm|pur|1|chased|5", "cm|pur|1|level|1", "cm|list|1.0",
          "ren", "cm|pur|0|chased|4", "ren", "cm|list|", "ren",
          "set|0x4000040", "cm|list|0", "cm|pur|0|chased|0", "ren",
          "set|0x8000040", "ren", "set|0x80040", "ren", "set|0x40",
          "ren"]
    return s


def s_be_the_cop():
    s = ["use|0", "cm|on|1", "rp|BeACop|1", "set|0x1000040",
          "cm|pci|0", "cm|cop|0|0", "cm|pur|0|chased|3", "cm|list|0"]
    for t in (125.5, 10.0, 9.95, 0.04, 0.0):
        s += ["cm|time|%s" % F(t), "ren"]
    # The helicopters: used, one on its way, the rest left. Three is all
    # there are: retail's Helicopter[3] on is Roadblock[0] on, which the
    # roadblock loop then sets again.
    for used, busy, heli in ((0, 0, 0), (1, 0, 0), (1, 1, 0), (2, 0, 1),
                             (2, 1, 0), (3, 0, 0)):
        s += ["cm|choppers|%d" % used, "cm|busy|%d" % busy,
              "w|heli960|%d" % heli, "ren"]
    s += ["cm|choppers|0", "cm|busy|0", "w|heli960|0", "w|heli|0", "ren",
          "w|heli|1", "rp|New624|0", "ren", "rp|New624|1"]
    # The roadblocks: used, one on its way while the pursuit asks for one.
    for used, n1560 in ((0, 0), (0, 1), (1, 1), (2, 0), (2, 1), (3, 1),
                        (4, 0)):
        s += ["cm|new0|%d" % used, "cm|pur|0|n1560|%d" % n1560, "ren"]
    s += ["cm|new0|0", "cm|pur|0|n1560|0", "cm|pci|-1", "ren", "cm|pci|0",
          "cm|cop|0|-1", "ren", "cm|cop|0|0"]
    # The chased car's damage.
    for d in (0.0, 0.1, 0.2, 0.45, 0.8, 0.99, 1.0, 1.5, -0.3):
        s += ["cm|dmg|3|%s" % F(d), "ren"]
    s += ["cm|pur|0|chased|-1", "ren", "cm|pur|0|chased|3",
          "cm|dmg|3|0"]
    # The tickets, the AI racers' in a race of one. Four is all there are:
    # retail's Tickets[4] on is pFlailerLiveSplitStatus on, NULL in a Be
    # The Cop game, where nothing sets LIVE_SPLIT or RACE_POSITION.
    s += ["cm|tickets|2|1", "ren", "cm|tickets|3|2", "cm|tickets|5|1",
          "ren", "w|table|1|-1", "ren", "w|table|1|3", "cm|tickets|4|0",
          "ren", "w|cop|2", "ren", "w|cop|4"]
    for k in range(NCARS):
        s.append("cm|tickets|%d|0" % k)
    s += ["ren", "rp|BeACop|0", "set|0x40"]
    return s


def s_nis_tracker():
    s = ["use|0", "cm|on|1", "set|0x200040", "ren", "pl|0|nis|1", "ren",
         "pl|0|nis|0", "g|pull|0|1|1", "ren", "g|pull|0|1|0", "ren",
         "set|0x100040", "ren", "race|stage|3", "ren", "race|stage|4"]
    s += ["car|3|render|0", "ren", "car|3|render|1", "w|traffic|10", "w|table|7|9", "w|table|8|1",
          "w|table|9|0", "ren", "w|ai|1", "ren", "w|ai|0", "w|cop|7",
          "ren", "w|cop|4", "w|traffic|4", "ren", "w|traffic|7", "set|0x40"]
    return s


def s_follow_debug():
    s = ["use|0", "set|%#x" % (0x200 | 0x40 | 0x2), "g|follow|0",
         "g|followcar|3", "car|3|speed|%s" % F(33.0), "ren",
         "g|followcar|-1", "ren", "g|followcar|42", "ren", "g|follow|1"]
    s += ["g|debug|1", "g|cpu|%s" % F(59.94), "g|gpu|%s" % F(29.97),
          "g|zone|7", "car|0|odo|%s" % F(12345.5), "car|0|px|%s"
          % F(-1234.5), "car|0|py|%s" % F(0.25), "car|0|pz|%s"
          % F(98765.0), "ren", "g|debug|0", "ren"]
    return s


def s_two_players():
    s = ["g|np|2", "rp|NPC|2", "pl|0|screen|%#x" % HUD_TOP,
         "pl|0|other|1", "pl|1|other|0", "g|byidx|1|1",
         "race|car|4|1", "rc|1|pos|5"]
    # Each always has the other: retail reads pOtherPlayer's car with no
    # check, in a two player race where there is always one.
    for k in (0, 1):
        s += ["use|%d" % k, "set|%#x" % (0x408 | 0x40 | 0x200)]
        s += ["ren", "rc|1|reason|1", "rc|1|time|80000", "ren",
              "rc|0|reason|1", "rc|0|time|81000", "ren", "rc|1|reason|0",
              "ren", "rc|0|reason|0", "rc|1|flne|%s" % F(1.75), "ren",
              "rc|1|flne|%s" % F(1.25), "ren"]
    # The lead shows with the lap counter alone.
    s += ["use|0", "set|%#x" % (0x400 | 0x40 | 0x200),
          "rc|1|flne|%s" % F(1.5), "ren", "rc|1|flne|%s" % F(1.25), "ren"]
    # Be The Cop's tickets: the other player's.
    s += ["use|0", "cm|on|1", "rp|BeACop|1", "set|0x1000040",
          "cm|pci|0", "cm|cop|0|0", "cm|tickets|1|2", "ren",
          "cm|tickets|1|4", "ren", "g|byidx|1|-1", "ren", "g|byidx|1|1",
          "cm|tickets|1|0", "rp|BeACop|0", "set|0"]
    s += ["use|1", "set|0", "use|0", "g|np|1", "rp|NPC|1",
          "pl|0|screen|%#x" % HUD_SINGLE, "pl|0|other|-1", "pl|1|other|-1",
          "g|byidx|1|-1"]
    return s


def s_update():
    """UpdateHud whole: the head, the score fade, the start bonus and the
    states that skip the scoring."""
    s = ["use|0", "pl|0|pref|0xffffffff", "pl|0|tscore|0x7fffffff", "upd",
         "upd"]
    # The score fade over its five seconds, with a hold after the fade out
    # has begun.
    for t in (398000, 396000, 390000, 385000, 382500, 381000, 383000,
              379000):
        s += ["pl|0|tscore|%d" % t, "upd"]
    # An unset stamp is skipped, even with WorldTimer a quarter second past
    # 0x7fffffff.
    s += ["g|timer|%d" % (0x7fffffff + 1001 - (1 << 32)), "upd",
          "g|timer|400000"]
    # The start bonus, once, for each place in a race of six.
    for pos in (1, 3, 6, 2):
        s += ["pl|0|new2736|0", "rc|0|pos|%d" % pos]
        for i in range(8):
            s.append("pl|0|place|%d|0" % i)
        s.append("upd")
    s += ["upd"]
    # Two players: the places a player starts ahead of.
    s += ["g|np|2", "rp|NPC|2"]
    for pos, n in ((1, 6), (2, 6), (6, 6), (3, 4)):
        s += ["pl|0|new2736|0", "rc|0|pos|%d" % pos, "race|n|%d" % n]
        for i in range(8):
            s.append("pl|0|place|%d|0" % i)
        s.append("upd")
    s += ["elim|2", "pl|0|new2736|0", "rc|0|pos|2", "upd", "elim|0",
          "g|np|1", "rp|NPC|1", "race|n|6"]
    # The states and stages that skip it.
    for env in (["g|rc|6"], ["g|rc|4"], ["g|rc|5"], ["g|rc|7"],
                ["g|rc|9"], ["g|rc|8"], ["g|rc|3", "race|stage|3"]):
        s += env + ["pl|0|new2736|0", "upd"]
    s += ["g|rc|3", "race|stage|4", "upd", "pl|0|car|0", "upd",
          "pl|0|car|1", "pl|0|pref|0", "upd"]
    # ConvertScoreString on its own: the table's, and the edges.
    for v in ("+2000", "-1000", "+0", "-500", "+10000", "250", "", "+", "-",
              "-0", "12a3", "--5", "+-5", " 5", "2147483647", "2147483648",
              "4294967295", "99999999999", "-2147483648", "007"):
        s.append("conv|%s" % v)
    return s


def script():
    s = ["load|%s" % (fc.SD / p) for p in hc.LOADS]
    s += common()
    s += s_gauges()
    s += s_laps()
    s += s_splits()
    s += s_leaderboard()
    s += s_position()
    s += s_tyres()
    s += s_pursuit()
    s += s_be_the_cop()
    s += s_nis_tracker()
    s += s_follow_debug()
    s += s_two_players()
    s += s_update()
    return s


# =================================================================== model

class Model(hc.Model):
    def __init__(self):
        hc.Model.__init__(self)
        e = self.e

        # Bigger than hudfeatures_check's: RenderHud reads deeper.
        self.race = e.alloc(1716)
        e.put32(hc.G_RACE, self.race)
        e.put32(self.race + 1712, self.dummy)   # the TimeAroundTrackTable
        self.copmgr = e.alloc(10600)
        self.world = e.alloc(44 + 4 * WORLD_MAX_CARS)
        self.heli = e.alloc(1024)
        e.put32(self.world + 24, self.heli)
        self.pursuits = [e.alloc(1600) for _ in range(NPURSUITS)]
        e.put32(self.copmgr + 44, self.copmgr + 44)
        e.put32(self.copmgr + 48, self.copmgr + 44)
        self.drivers = e.alloc(48)
        self.cops = [e.alloc(32) for _ in range(NCOPS)]
        self.skin = e.alloc(64)
        self.sample = e.alloc(64)
        self.strings = {}
        self.lapx = 0
        self.zone = 0
        self.cars, self.rcs, self.chars = [], [], []
        for c in range(NCARS):
            car = e.alloc(1216)
            cti = e.alloc(1400)
            rcar = e.alloc(192)
            drv = e.alloc(64)
            ch = e.alloc(40)
            e.put32(car + 12, cti)
            e.put32(car + 16, e.alloc(16))
            e.put32(car + 20, drv)
            e.put32(car + 28, rcar)
            e.put32(rcar, car)
            e.put32(cti + 1368, e.alloc(32))
            e.write(ch + 4, b"DRV%d\0" % c)
            self.cars.append(car)
            self.rcs.append(rcar)
            self.chars.append(ch)
        for g in (G_WORLD, G_TIMER, G_WFRAMES, G_LOOP, G_BY_INDEX,
                  G_BY_INDEX + 4, LANGUAGE):
            e.put32(g, 0)

        e.stub(S_ANIMS, self.s_anims)
        e.stub(S_SCORING, self.s_scoring)
        e.stub(S_START_SCORE, self.s_start_score)
        e.stub(S_SPEED_ANIM, self.s_speed_anim)
        e.stub(S_GROW_ANIM, self.s_grow_anim)
        e.stub(S_PURSUIT, self.s_pursuit)
        e.stub(S_RADAR, self.s_radar)
        e.stub(S_TRACKER, self.s_tracker)
        e.stub(S_NIS_UPDATE, self.s_nis_update)
        e.stub(S_TRANSLATE, self.s_translate)
        e.stub(S_BY_DRIVER, self.s_by_driver)
        e.stub(S_SKIN, self.s_skin)
        e.stub(S_LAP_EXACT, self.s_lap_exact)
        e.stub(S_TATT, self.s_tatt)
        e.stub(S_ZONE, self.s_zone)
        e.stub(S_SAMPLE, self.s_sample)
        e.stub(S_PLAY, self.s_play)

    # ---- stubs

    def car_name(self, a):
        if a == 0:
            return "none"
        if a in self.cars:
            return "car%d" % self.cars.index(a)
        return "car?"

    def s_anims(self, em):
        self.emit("  anims %s" % self.pname(self.arg(em, 0)))

    def s_scoring(self, em):
        self.emit("  scoring %s" % self.pname(self.arg(em, 0)))

    def s_start_score(self, em):
        self.emit("  startscore %s %d %d" % (
            self.pname(self.arg(em, 0)), s32(self.arg(em, 1)),
            s32(self.arg(em, 2))))

    def anim(self, em, what):
        self.emit("  %s %s %s %s %08x %d" % (
            what, self.pname(self.arg(em, 0)), self.name(self.arg(em, 1)),
            self.name(self.arg(em, 2)), self.arg(em, 3),
            self.arg(em, 4) & 0xff))

    def s_speed_anim(self, em):
        self.anim(em, "speedanim")

    def s_grow_anim(self, em):
        self.anim(em, "growanim")

    def s_pursuit(self, em):
        self.emit("  pursuitmeter %s %d" % (self.pname(self.arg(em, 0)),
                                            s32(self.arg(em, 1))))

    def s_radar(self, em):
        self.emit("  radar %s" % self.pname(self.arg(em, 0)))

    def s_tracker(self, em):
        self.emit("  tracker %s %s %d" % (
            self.pname(self.arg(em, 0)), self.car_name(self.arg(em, 1)),
            s32(self.arg(em, 2))))

    def s_nis_update(self, em):
        o = self.arg(em, 0)
        who = "bad"
        for p in self.players:
            if o == p + 2560:
                who = self.pname(p)
        self.emit("  nisupdate %s %d" % (who, self.arg(em, 1) & 0xff))

    def s_translate(self, em):
        i = s32(self.arg(em, 0))
        self.emit("  translate %x" % (i & M32))
        if i not in self.strings:
            a = self.e.alloc(16)
            self.e.write(a, b"T%x\0" % (i & M32))
            self.strings[i] = a
        return self.strings[i]

    def s_by_driver(self, em):
        n = s32(self.arg(em, 0))
        self.emit("  bydriver %d" % n)
        return self.cars[n] if 0 <= n < NCARS else 0

    def s_skin(self, em):
        t, k, d = (s32(self.arg(em, i)) for i in range(3))
        self.emit("  skin %d %d %d" % (t, k, d))
        self.e.put32(self.skin + 48, 0x5000 + 16 * t + k)
        return self.skin

    def s_lap_exact(self, em):
        self.emit("  lapexact %08x" % em.fpr[12])
        em.fpr[0] = self.lapx

    def s_tatt(self, em):
        lap = em.fpr[12]
        self.emit("  tatt %s %08x" % ("ok" if self.arg(em, 0) == self.dummy
                                      else "bad", lap))
        v = fc.f32(fc.f32(fc.bitsf(lap) * 64.0) + 0.5)
        self.ret_f(em, v)

    def s_zone(self, em):
        self.emit("  zone")
        return self.zone

    def s_sample(self, em):
        a = self.arg(em, 0)
        n = 0
        while self.e.mem[a + n]:
            n += 1
        self.emit("  sample %s" % bytes(self.e.mem[a:a + n]).decode())
        return self.sample

    def s_play(self, em):
        self.emit("  play %s %08x %08x %08x" % (
            "ok" if self.arg(em, 0) == self.sample else "bad",
            em.fpr[12], em.fpr[13], em.fpr[14]))

    # ---- output

    def dump_render(self, n):
        e = self.e
        p = self.players[n]
        for name, kind, count in RENDER_FIELDS:
            for i in range(count):
                a = p + OFFSET[name] + 4 * i
                key = ("p%d.%s[%d]" % (n, name, i) if count > 1
                       else "p%d.%s" % (n, name))
                if kind == "p":
                    text = self.name(e.u32(a))
                elif kind == "s":
                    k = 0
                    while k < 31 and e.mem[a + k]:
                        k += 1
                    text = '"%s"' % bytes(e.mem[a:a + k]).decode("latin-1")
                else:
                    text = "%08x" % e.u32(a)
                self.note(key, text)

    def dump(self):
        self.dump_player(0)
        self.dump_player(1)
        self.dump_render(0)
        self.dump_render(1)
        self.dump_objects()

    # ---- ops

    def car_or_none(self, v):
        v = s32(v)
        return self.cars[v] if 0 <= v < NCARS else 0

    def set_player(self, k, n, v, a=None):
        e = self.e
        p = self.players[k]
        if n in PLAYER_SET:
            off, size = PLAYER_SET[n]
            self.put(p + off, size, v)
        elif n == "other":
            v = s32(v)
            e.put32(p + 20, self.players[v] if v >= 0 else 0)
        elif n == "place":
            e.put32(p + 2628 + 4 * v, int(a[0], 0))
        else:
            hc.Model.set_player(self, k, n, v)

    def set_car(self, k, n, v, a=None):
        e = self.e
        c = self.cars[k]
        cti = e.u32(c + 12)
        if n in CAR_SET:
            off, size = CAR_SET[n]
            self.put(c + off, size, v)
        elif n == "wtu":
            e.put32(c + CAR_WTU + 4 * v, int(a[0], 0))
        elif n == "skin":
            self.put(e.u32(c + 16) + 5, 1, v)
        elif n == "short":
            e.put32(e.u32(cti + 1368) + 24, v)
        elif n == "maxrpm":
            e.put32(cti + 688 + 8, v)
        elif n == "redline":
            e.put32(cti + 688 + 4, v)
        elif n == "hud":
            e.put32(cti + 1232 + v, int(a[0], 0))
        elif n == "driver":
            e.put32(e.u32(c + 20) + 20, self.chars[k] if v else 0)
        else:
            hc.Model.set_car(self, k, n, v)

    def set_rc(self, k, n, v, a):
        r = self.rcs[k]
        if n in RC_SET:
            off, size = RC_SET[n]
            self.put(r + off, size, v)
        elif n in RC_TIMES:
            self.e.put32(r + RC_TIMES[n] + 4 * v, int(a[0], 0))
        else:
            raise ValueError(n)

    def set_race(self, n, v, a):
        e = self.e
        if n in RACE_SET:
            off, size = RACE_SET[n]
            self.put(self.race + off, size, v)
        elif n == "car":
            c = s32(int(a[0], 0))
            e.put32(self.race + 1572 + 4 * v,
                    self.rcs[c] if 0 <= c < NCARS else 0)
        elif n == "bd":
            e.put32(self.race + 1620 + 4 * v, int(a[0], 0))
        else:
            raise ValueError(n)

    def set_world(self, n, v, a):
        e = self.e
        w = self.world
        if n == "on":
            e.put32(G_WORLD, w if v else 0)
        elif n == "heli":
            e.put32(w + 24, self.heli if v else 0)
        elif n == "heli960":
            e.put32(self.heli + 960, v)
        elif n == "ai":
            e.put32(w + 32, v)
        elif n == "cop":
            e.put32(w + 36, v)
        elif n == "traffic":
            e.put32(w + 40, v)
        elif n == "table":
            e.put32(w + 44 + 4 * v, self.car_or_none(int(a[0], 0)))
        else:
            raise ValueError(n)

    def set_cop(self, n, a):
        e = self.e
        m = self.copmgr
        v = int(a[0], 0) & M32 if n != "list" and a and a[0] else 0
        if n == "on":
            e.put32(hc.G_COPMGR, m if v else 0)
        elif n == "new0":
            e.put32(m, v)
        elif n == "pci":
            e.put32(m + 12, v)
        elif n == "cop":
            pi = s32(int(a[1], 0))
            if pi < 0:
                e.put32(m + 16 + 4 * v, 0)
            else:
                e.put32(self.cops[v], self.pursuits[pi])
                e.put32(m + 16 + 4 * v, self.cops[v])
        elif n == "time":
            e.put32(m + 10480, v)
        elif n == "choppers":
            e.put32(m + 10492, v)
        elif n == "busy":
            e.put32(m + 312, v)
        elif n == "dmg":
            e.put32(m + 10420 + 4 * v, int(a[1], 0))
        elif n == "tickets":
            e.mem[m + 88 + 28 * v + 8] = int(a[1], 0) & 0xff
        elif n == "active":
            e.put32(m + 88 + 28 * v + 12, int(a[1], 0))
        elif n == "pur":
            pu = self.pursuits[v]
            f, x = a[1], int(a[2], 0) & M32
            if f == "chased":
                e.put32(pu + 16, self.car_or_none(x))
            elif f == "level":
                e.put32(pu + 1492, x)
            elif f == "n1560":
                e.put32(pu + 1560, x)
            else:
                raise ValueError(f)
        elif n == "list":
            # The pursuits linked in this order, after the list's own node.
            head = m + 44
            nodes = [self.pursuits[int(i)] for i in a[0].split(".") if i]
            chain = [head] + nodes + [head]
            for x, y in zip(chain, chain[1:]):
                e.put32(x, y)
                e.put32(y + 4, x)
        else:
            raise ValueError(n)

    def set_global(self, a):
        e = self.e
        k = a[0]
        v = lambda i: int(a[i], 0) & M32      # noqa: E731
        if k == "timer":
            e.put32(G_TIMER, v(1))
        elif k == "wframes":
            e.put32(G_WFRAMES, v(1))
        elif k == "loop":
            e.put32(G_LOOP, v(1))
        elif k == "follow":
            e.put32(G_FOLLOW, v(1))
        elif k == "followcar":
            e.put32(G_FOLLOW_CAR, v(1))
        elif k == "live":
            e.put32(G_LIVE, v(1))
        elif k == "smf":
            e.put32(G_SMF, v(1))
        elif k == "tach":
            e.put32(G_TACH, v(1))
        elif k == "debug":
            e.put32(G_DEBUG, v(1))
        elif k == "cpu":
            e.put32(G_CPU, v(1))
        elif k == "gpu":
            e.put32(G_GPU, v(1))
        elif k == "lang":
            e.put32(LANGUAGE, v(1))
        elif k == "zone":
            self.zone = v(1)
        elif k == "lapx":
            self.lapx = v(1)
        elif k == "byidx":
            who = s32(v(2))
            e.put32(G_BY_INDEX + 4 * v(1), 0 if who < 0 else self.players[who])
        else:
            hc.Model.set_global(self, a)

    def op(self, a):
        e = self.e
        o = a[0]
        if o == "load":
            self.load(a[1])
            return
        v = lambda i: int(a[i], 0) & M32      # noqa: E731
        if o == "rp":
            off, size = RP_FIELDS[a[1]]
            self.put(RP + off, size, v(2))
        elif o == "elim":
            # Two drivers, the first eliminated at rank N: the table
            # NumEliminated counts, 24-byte DriverInfos with the rank first.
            e.put32(RP + 772, self.drivers)
            e.put32(RP + 776, 2)
            e.mem[self.drivers] = v(1) & 0xff
        elif o == "pn":
            p = self.players[int(a[1])]
            e.write(p + 32 + 20, a[2].encode()[:11].ljust(12, b"\0"))
        elif o == "pl":
            self.set_player(int(a[1]), a[2], v(3), a[4:])
        elif o == "car":
            self.set_car(int(a[1]), a[2], v(3), a[4:])
        elif o == "rc":
            self.set_rc(int(a[1]), a[2], v(3), a[4:])
        elif o == "race":
            self.set_race(a[1], v(2), a[3:])
        elif o == "w":
            self.set_world(a[1], v(2), a[3:])
        elif o == "cm":
            self.set_cop(a[1], a[2:])
        elif o == "ren":
            e.call(F_RENDER, self.player(), limit=200000000)
        elif o == "upd":
            e.call(F_UPDATE, self.player(), limit=200000000)
        elif o == "best":
            r = e.call(F_BEST, self.player(), v(1), limit=1000000) & M32
            self.emit("  best %08x" % r)
        elif o == "conv":
            if not hasattr(self, "cbuf"):
                self.cbuf = e.alloc(64)
            e.write(self.cbuf, a[1].encode() + bytes(1))
            r = e.call(F_CONVERT, self.player(), self.cbuf, limit=1000000)
            self.emit("  conv %d" % r)
        elif o in ("cam", "g", "use", "set"):
            hc.Model.op(self, a)
            return
        else:
            raise ValueError(o)
        self.dump()


def model(lines):
    return Model().run(lines)


# ================================================================= build

def build_harness(tmp, name="hudrender_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


run_harness = fc.run_harness
diff = pcc.diff
write_script = fc.write_script


# ============================================================= mutations

H = HUDRENDER


def M(name, before, after, rel=H):
    return (name, rel, before, after)


R = RACESPLIT

MUTATIONS = [
    # The helpers.
    M("gear-letter-unknown", "    return 'X';", "    return 'N';"),
    M("gear-table-short", "    for (i = 0; i < 10; i++)\n        if (gear",
      "    for (i = 0; i < 9; i++)\n        if (gear"),
    M("warn-every-frame", "    if (s != sTimerWarningSecond) {",
      "    if (1) {"),
    M("warn-not-remembered", "        sTimerWarningSecond = s;\n", ""),
    M("best-p2p-lap-record", "    uint32_t rec = rp->Point2Point != 0",
      "    uint32_t rec = rp->Point2Point == 0"),
    M("best-time-trial-car",
      "if (rp->RaceType == RACE_TYPE_TIME_TRIAL || rp->Point2Point != 0)",
      "if (rp->Point2Point != 0)"),
    M("best-previous-swapped",
      "    t = previous ? racingcar_get_last_previous_best_lap_time(rc)",
      "    t = !previous ? racingcar_get_last_previous_best_lap_time(rc)"),
    M("best-unset-record",
      "    if (!timer_word_valid(rec) || (int32_t)t < (int32_t)rec)",
      "    if ((int32_t)t < (int32_t)rec)"),
    M("score-no-minus", "        sign = -1;\n", ""),
    M("score-plus-kept", "    } else if (s[0] == '+') {\n        s++;",
      "    } else if (s[0] == '+') {\n        s += 0;"),
    M("score-digits-to-9", "    while (*s >= '0' && *s <= '9')",
      "    while (*s >= '0' && *s < '9')"),
    M("fade-unset", "    if (p->tScoreAnimation.PackedTime == TIMER_UNSET)"
      "\n        return;\n", ""),
    M("fade-in-slower", "        a = ee_trunc_w((x + x) * 128.0f);",
      "        a = ee_trunc_w(x * 128.0f);"),
    M("fade-hold-to-4", "    } else if (0.5f < x && x <= 4.5f) {",
      "    } else if (0.5f < x && x <= 4.0f) {"),
    M("fade-out-slower",
      "        a = ee_trunc_w((1.0f - ((x - 4.5f) + (x - 4.5f))) * 128.0f);",
      "        a = ee_trunc_w((1.0f - (x - 4.5f)) * 128.0f);"),
    M("fade-never-ends",
      "            p->tScoreAnimation.PackedTime = TIMER_UNSET;\n", ""),

    # DisplayDebugInfo.
    M("debug-shown-when-off",
      "            (*o[i])->Visibility = DisplayPlayerDebugInfo != 0",
      "            (*o[i])->Visibility = DisplayPlayerDebugInfo == 0"),
    M("debug-km-scale", "car->State.Odometer * 0.001f",
      "car->State.Odometer * 0.01f"),
    M("debug-pos-places", '"%.0f %.0f %.0f s%d"', '"%.1f %.0f %.0f s%d"'),
    M("debug-fps-rounded", '"C: %dfps", ee_trunc_w(PreviousCpuFrameRate)',
      '"C: %dfps", (int32_t)(PreviousCpuFrameRate + 0.5f)'),

    # The gauges.
    M("needle-span-wrong-way", "(360.0f - a0) + a1;", "(360.0f - a1) + a0;"),
    M("needle-no-wrap", "        ang = ang - 360.0f;", "        ang = ang;"),
    M("needle-negative-added", "        ang = 360.0f - ang;",
      "        ang = 360.0f + ang;"),
    M("kph-factor", "spd = car->State.ForwardSpeed * 3.6f;",
      "spd = car->State.ForwardSpeed * 3.5f;"),
    M("mph-factor", "* 2.237f;", "* 2.236f;"),
    M("units-2-is-kph", "GlobalDisplaySettings.Units == 1) {",
      "GlobalDisplaySettings.Units != 0) {"),
    M("kph-mph-max", "        max = hud_info_f(ti, HUDINFO_KPH_MAX);",
      "        max = hud_info_f(ti, HUDINFO_MPH_MAX);"),
    M("topspeed-every-frame", "    if (p->TopSpeed == 0)\n",
      "    if (1)\n"),
    M("topspeed-never-armed", "        p->bCheckTopSpeed = 1;\n", ""),
    M("topspeed-be-the-cop",
      "    if (p->bCheckTopSpeed != 0 && TheRaceParameters.BeACop == 0",
      "    if (p->bCheckTopSpeed != 0"),
    M("topspeed-not-falling",
      "        && s1 < p->LastSpeed && p->TopSpeed < p->LastSpeed",
      "        && p->TopSpeed < p->LastSpeed"),
    M("topspeed-step", "p->SpeedFactor = p->SpeedFactor + 0.1f;",
      "p->SpeedFactor = p->SpeedFactor + 0.05f;"),
    M("topspeed-uncapped",
      "        if (1.0f < p->SpeedFactor)\n            p->SpeedFactor = 1.0f;\n",
      ""),
    M("topspeed-new-kept", "    p->bNewTopSpeed = 0;\n", ""),
    M("needle-under-min", "        if (spd < min)\n            n = 0.0f;\n", ""),
    M("needle-over-max", "        if (max < spd)\n            n = 1.0f;\n", ""),
    M("pop-from-150", "for (t = 100; t <= 400; t += 50)",
      "for (t = 150; t <= 400; t += 50)"),
    M("pop-in-car-too",
      "        if ((p->CurrentHudFeatures & HUD_GAUGES_IN_CAR) == 0) {",
      "        if (1) {"),
    M("pop-flag-0", "                                (uint32_t)WorldTimer, 1);",
      "                                (uint32_t)WorldTimer, 0);"),
    M("speed-signed", "    flailer_printf_chunk(TXT(p->pFlailerSpeedString), \"%3d\","
      "\n                             ee_trunc_w(fabsf(spd)));",
      "    flailer_printf_chunk(TXT(p->pFlailerSpeedString), \"%3d\","
      "\n                             ee_trunc_w(spd));"),
    M("lastspeed-unset-0", "        p->LastSpeed = 999;",
      "        p->LastSpeed = 0;"),
    M("tach-test-ignored",
      "float rpm = TachTestRpm == 100.0f ? car->State.RPM : TachTestRpm;",
      "float rpm = car->State.RPM;"),
    M("tach-below-0", "    if (r < 0.0f)\n        r = 0.0f;\n", ""),
    M("tach-over-1", "    if (1.0f < r)\n        r = 1.0f;\n", ""),
    M("tach-bumper-angle", "        a0 = 45.0f;", "        a0 = 40.0f;"),
    M("shift-auto-shown",
      "        if (p->PlayerSettings.TransmissionType != 1) {",
      "        if (p->PlayerSettings.TransmissionType == 2) {"),
    M("shift-at-red-line",
      "                e->RedLineRPM <= rpm && car->State.CurrentGear > 0",
      "                e->RedLineRPM < rpm && car->State.CurrentGear > 0"),
    M("shift-in-neutral", "&& car->State.CurrentGear > 0",
      "&& car->State.CurrentGear >= 0"),
    M("gradient-not-whole-500",
      "int32_t v = ee_trunc_w(e->RedLineRPM) / 500;",
      "float v = e->RedLineRPM / 500.0f;"),
    M("gradient-span", "float g = (float)v * 500.0f / e->MaxRPM * (a1 - a0);",
      "float g = (float)v * 500.0f / e->MaxRPM * a1;"),
    M("gear-colour-swapped",
      "                              car->State.ClutchEngaged != 0",
      "                              car->State.ClutchEngaged == 0"),

    # The lead, the lap time, the best lap.
    M("lead-sign", "buf[0] == '+' ? LANG_LEAD_AHEAD",
      "buf[0] == '-' ? LANG_LEAD_AHEAD"),
    M("lead-order", "    race_calculate_split_time(race, &t, other, rc);",
      "    race_calculate_split_time(race, &t, rc, other);"),
    M("lead-not-signed",
      "        flailertext_set_format_options(TXT(p->pFlailerLeadTime),"
      "\n                                       BUI_FMT_FIXEDWIDTH);",
      "        flailertext_set_format_options(TXT(p->pFlailerLeadTime), 0);"),
    M("lead-needs-lap-time",
      "    if ((p->CurrentHudFeatures & (HUD_LAP_TIME | HUD_LAP_COUNTER))"
      " && rc != NULL",
      "    if ((p->CurrentHudFeatures & HUD_LAP_TIME) && rc != NULL"),
    M("lap-first-half-second",
      "if ((float)(int32_t)t.PackedTime * 0.00025f < 3.0f) {",
      "if ((float)(int32_t)t.PackedTime * 0.00025f < 0.5f) {"),
    M("lap-last-unchecked",
      "            t.PackedTime = timer_word_valid(last) ? ttt - last\n"
      "                                                  : ttt - t.PackedTime;",
      "            t.PackedTime = ttt - last;"),
    M("lap-over-colour", "            flailertext_set_color(TXT(o), "
      "COLOUR_LAP_OVER);",
      "            flailertext_set_color(TXT(o), COLOUR_LAP_WARNING);"),
    M("lap-over-negative", "            t.PackedTime = 0u - t.PackedTime;\n",
      ""),
    M("lap-warn-from-5", "* 0.00025f < 10.0f) {\n            trigger",
      "* 0.00025f < 5.0f) {\n            trigger"),
    M("lap-no-sound", "            trigger_timer_warning_sound(&t);\n", ""),
    M("bestlap-dashes", '"--:--:--"', '"--:--"'),
    M("bestlap-previous",
      "        t.PackedTime = player_get_current_best_lap_record(p, 0);",
      "        t.PackedTime = player_get_current_best_lap_record(p, 1);"),

    # The splits.
    M("split-region-negative",
      "int32_t i = (rc->HighestBoundaryRegion + 5) % 5;",
      "int32_t i = rc->HighestBoundaryRegion % 5;"),
    M("split-shown-1s", "* 0.00025f < 5.0f\n        && timer_word_valid",
      "* 0.00025f < 1.0f\n        && timer_word_valid"),
    M("split-font", 'TXT(run)->FontHash = bchunk_hash("FONT_A");',
      'TXT(run)->FontHash = bchunk_hash("FONT_B");'),
    M("split-leader-needs-3", "            } else if (race->NumRacingCars >= 2\n",
      "            } else if (race->NumRacingCars >= 3\n"),
    M("split-best-any-region",
      "            if (i == 0\n                && timer_word_valid("
      "player_get_current_best_lap_record(p, 1))) {",
      "            if (timer_word_valid("
      "player_get_current_best_lap_record(p, 1))) {"),
    M("split-best-current",
      "                split.PackedTime = t76 - "
      "player_get_current_best_lap_record(p, 1);",
      "                split.PackedTime = t76 - "
      "player_get_current_best_lap_record(p, 0);"),
    M("split-prev-best-is-prev",
      "                split.PackedTime = t76\n"
      "                    - rc->PreviousBestRunningTimes[i].PackedTime;",
      "                split.PackedTime = t76\n"
      "                    - rc->PreviousRunningTimes[i].PackedTime;"),
    M("split-live-every-frame",
      "                print = LiveUpdateSplitTimeRate != 0\n"
      "                    && WorldLoopCounter % LiveUpdateSplitTimeRate == 0;",
      "                print = LiveUpdateSplitTimeRate != 0;"),
    M("split-fresh-0.3", "                        < 0.2f;",
      "                        < 0.3f;"),
    M("split-comparison-hidden", "            shown_cmp = 1;\n", ""),
    M("split-unsigned", "                print_time(&split, buf, "
      "TIMER_PRINT_SIGN);",
      "                print_time(&split, buf, 0);"),

    # The leaderboard.
    M("lb-names-50", "    if (WorldTimeFrames % 500 < 100",
      "    if (WorldTimeFrames % 500 < 50"),
    M("lb-car-name-even", "        if ((WorldTimeFrames / 500) & 1)",
      "        if (((WorldTimeFrames / 500) & 1) == 0)"),
    M("lb-own-name-is-driver",
      "        else if (c == rc)\n            s = p->PlayerSettings.PlayerName;",
      "        else if (0)\n            s = p->PlayerSettings.PlayerName;"),
    M("lb-reason-ignored", "    } else if (c->FinishReason != 0) {",
      "    } else if (0) {"),
    M("lb-pulled-over-ignored", "    } else if (car_pulled_over(car)) {",
      "    } else if (0) {"),
    M("lb-laps-floored",
      "        int32_t d = ee_trunc_w(c->CurrentLapNumberExact",
      "        int32_t d = (int32_t)floorf(c->CurrentLapNumberExact"),
    M("lb-lap-signed-plural", "(d < 0 ? -d : d) == 1 ? LANG_LAP",
      "d == 1 ? LANG_LAP"),
    M("lb-split-order", "            race_calculate_split_time(race, &t, rc, c);",
      "            race_calculate_split_time(race, &t, c, rc);"),
    M("lb-format-kept",
      "    flailertext_clear_format_options(TXT(st), BUI_FMT_FIXEDWIDTH);\n", ""),
    M("lb-mode2-start-1", "        start = 1 < s ? s : 2;",
      "        start = 1 < s ? s : 1;"),
    M("lb-mode2-unclamped",
      "        if (race->NumRacingCars - 2 < s)\n"
      "            s = race->NumRacingCars - 2;\n", ""),
    M("lb-row-skips", "        int32_t n = i != 0 ? start + i - 1 : 1;",
      "        int32_t n = i != 0 ? start + i : 1;"),
    M("lb-bar-on-others",
      "        if (c == rc && p->pFlailerLiveSplitBar != NULL) {",
      "        if (c != rc && p->pFlailerLiveSplitBar != NULL) {"),
    M("lb-skin-flag", "c->pCar->pRideInfo->SkinNumber, 1);",
      "c->pCar->pRideInfo->SkinNumber, 0);"),
    M("lb-pullovers-4",
      "    if (pCopManager == NULL || idx < 0 || idx >= 14)",
      "    if (pCopManager == NULL || idx < 0 || idx >= 4)"),

    # The lap counter, the race position, the tyres.
    M("lc-under-0", "        if (pct < 0.0f)\n            pct = 0.0f;\n", ""),
    M("lc-over-1", "        if (1.0f < pct)\n            pct = 1.0f;\n", ""),
    M("lc-two-places", '"%5.1f %%"', '"%5.2f %%"'),
    M("lc-laps-done", '"%d/%d", rc->NumLapsCompleted + 1,',
      '"%d/%d", rc->NumLapsCompleted,'),
    M("pos-flag-reversed",
      "            p->PositionFlag = pos < p->LastRacePosition ? 1 : -1;",
      "            p->PositionFlag = pos > p->LastRacePosition ? 1 : -1;"),
    M("pos-change-every-frame", "        if (p->LastRacePosition != pos) {",
      "        if (1) {"),
    M("pos-grow-shows-new",
      "                                                  : p->LastRacePosition);",
      "                                                  : pos);"),
    M("pos-grow-flag-reversed",
      "                                     pos < p->LastRacePosition);",
      "                                     pos > p->LastRacePosition);"),
    M("pos-knockout-total",
      "                             ? race->NumRacingCars\n"
      "                                   - race->NumRacingCarsFinished",
      "                             ? race->NumRacingCars"),
    M("pos-female-any-place",
      "if (p->PlayerSettings.PreferredGender == 1 && pos == 1)",
      "if (p->PlayerSettings.PreferredGender == 1)"),
    M("pos-extension-off-1", "(uint32_t)(LANG_PLACE_1ST + pos));",
      "(uint32_t)(LANG_PLACE_1ST + pos - 1));"),
    M("tyre-threshold", "        float thr = 0.9f;", "        float thr = 0.8f;"),
    M("tyre-grip-unscaled",
      "c = (uint32_t)ee_trunc_w(v / thr * 255.0f) + COLOUR_TYRE_GRIP;",
      "c = (uint32_t)ee_trunc_w(v * 255.0f) + COLOUR_TYRE_GRIP;"),
    M("tyre-slip-blue", "                                      * 255.0f) << 8)",
      "                                      * 255.0f) << 16)"),
    M("tyre-threshold-is-grip", "        if (v < thr)\n            c = ",
      "        if (v <= thr)\n            c = "),

    # The pursuit meter, the radar, Be The Cop.
    M("pursuit-hi-ignored",
      "(HUD_PURSUIT | HUD_PURSUIT_HI | HUD_PURSUIT_NIS)",
      "(HUD_PURSUIT | HUD_PURSUIT_NIS)"),
    M("pursuit-level-0",
      "            ? copmanager_get_pursuit_level_for_hud(pCopManager, car) : 0;",
      "            ? 0 : 0;"),
    M("radar-off",
      "    if ((p->CurrentHudFeatures & HUD_RADAR) && gUpdateRadarDetectorFn",
      "    if (0 && gUpdateRadarDetectorFn"),
    M("btc-whole-at-10", '10.0f < secs ? "%3.0f" : "%3.1f"',
      '10.0f <= secs ? "%3.0f" : "%3.1f"'),
    M("btc-heli-always-coming", "    if (!can_call_helicopter(m)) {",
      "    if (1) {"),
    M("btc-heli-out-ignored", "    if (out != 0)\n        return 0;\n", ""),
    M("btc-heli-new624-ignored",
      "    if (heli == NULL || TheRaceParameters.New624 == 0)",
      "    if (heli == NULL)"),
    M("btc-heli-busy-ignored",
      "    return copmanager_word(m, COPMANAGER_CHOPPER_BUSY) == 0;",
      "    return 1;"),
    M("btc-heli-ready-colour",
      "        set_bitmap_colour(p->pFlailerBeTheCopHelicopter[i], "
      "COLOUR_BTC_READY);",
      "        set_bitmap_colour(p->pFlailerBeTheCopHelicopter[i], "
      "COLOUR_BTC_SPENT);"),
    M("btc-roadblock-always-coming",
      "    if (pur != NULL && pur->RoadBlockStateMachine.State != ERBS_NONE) {",
      "    if (pur != NULL) {"),
    M("btc-roadblocks-unused", "    left = h->nBeACopNumRoadBlocks;\n",
      "    left = 0;\n"),
    M("btc-damage-by-4", "        n = ee_trunc_w(v * 5.0f);",
      "        n = ee_trunc_w(v * 4.0f);"),
    M("btc-damage-plus-1-over-1", "        if (v != 0.0f) {\n            n++;",
      "        if (v > 1.0f) {\n            n++;"),
    M("btc-damage-cap-4", "            if (!(n < 6))\n                n = 5;",
      "            if (!(n < 5))\n                n = 4;"),
    M("btc-damage-index-3", "            if (idx >= 0 && idx < 14)\n                v = ",
      "            if (idx >= 0 && idx < 3)\n                v = "),
    M("btc-tickets-1p-3", "        max = 4;", "        max = 3;"),
    M("btc-tickets-2p-4", "        max = 3;", "        max = 4;"),
    M("btc-tickets-ai-short",
      "for (i = 0; w != NULL && i < w->CopCarPos - w->AICarPos; i++) {",
      "for (i = 0; w != NULL && i < w->CopCarPos - w->AICarPos - 1; i++) {"),
    M("btc-tickets-2p-self",
      "        struct Player *o = PlayerPlayersByIndex[1];",
      "        struct Player *o = PlayerPlayersByIndex[0];"),
    M("btc-tickets-hidden",
      "        set_vis(p->pFlailerBeTheCopTickets[i], 1);",
      "        set_vis(p->pFlailerBeTheCopTickets[i], 0);"),

    # The NIS overlay, the trackers, the follow camera.
    M("nis-busted-ignored",
      "        && (player_is_nis_playing(p) || "
      "player_should_show_busted_text(p))",
      "        && player_is_nis_playing(p)"),
    M("nis-always-playing",
      "gNisOverlayUpdateFn(&p->mFlailerNIS, player_is_nis_playing(p) != 0);",
      "gNisOverlayUpdateFn(&p->mFlailerNIS, 1);"),
    M("track-none-hidden",
      "    for (i = 0; i < 7; i++)\n        set_vis(p->pFlailerTracker[i], 0);"
      "\n    if (w == NULL)", "    if (w == NULL)"),
    M("track-unrendered-drawn",
      "            if (c != NULL && c->RenderingEnabled != 0) {\n"
      "                if (gDrawTrackerFn != NULL)\n"
      "                    gDrawTrackerFn(p, c, j);\n"
      "                set_bitmap_colour(p->pFlailerTracker[j], "
      "COLOUR_TRACK_RACER);",
      "            if (c != NULL) {\n"
      "                if (gDrawTrackerFn != NULL)\n"
      "                    gDrawTrackerFn(p, c, j);\n"
      "                set_bitmap_colour(p->pFlailerTracker[j], "
      "COLOUR_TRACK_RACER);"),
    M("track-cops-as-racers",
      "set_bitmap_colour(p->pFlailerTracker[j], COLOUR_TRACK_COP);",
      "set_bitmap_colour(p->pFlailerTracker[j], COLOUR_TRACK_RACER);"),
    M("track-cops-from-0",
      "    if (w->TrafficCarPos - w->CopCarPos > 0 && j < 7) {\n        i = 0;",
      "    if (w->TrafficCarPos - w->CopCarPos > 0 && j < 7) {\n        i = 0;"
      "\n        j = 0;"),
    M("track-any-stage",
      "    if ((p->CurrentHudFeatures & HUD_TRACKER) && race != NULL\n"
      "        && race->RaceStage == RACE_STAGE_RACING) {",
      "    if ((p->CurrentHudFeatures & HUD_TRACKER) && race != NULL) {"),
    M("follow-ignored", "    if (CameraFollowDefaultCar == 0) {",
      "    if (0) {"),
    M("follow-own-type-info", "    ti = p->MyCar->pCarTypeInfo;",
      "    ti = car->pCarTypeInfo;"),

    # UpdateHud and the start bonus.
    M("upd-bonus-every-frame", "            if (p->New2736 == 0) {",
      "            if (1) {"),
    M("upd-scores-in-pause",
      "        if (s != RCSTATE_PAUSE && s != RCSTATE_INSTANT_REPLAY",
      "        if (s != RCSTATE_INSTANT_REPLAY"),
    M("upd-any-stage",
      "    if (race != NULL && race->RaceStage == RACE_STAGE_RACING\n",
      "    if (race != NULL\n"),
    M("upd-render-with-none",
      "    if (p->CurrentHudFeatures != 0)\n        player_render_hud(p);",
      "    player_render_hud(p);"),
    M("bonus-2p-eliminated",
      "        && race_parameters_num_eliminated(&TheRaceParameters) == 0) {",
      "        ) {"),
    M("bonus-2p-last-place",
      "        if (v == n)\n            v = rc->RacePosition - 2;",
      "        if (v == n)\n            v = rc->RacePosition - 1;"),
    M("bonus-2p-mark", "            mark_place_reached(p, n - k - 1);",
      "            mark_place_reached(p, n - k);"),
    M("bonus-score-index", "            int32_t idx = race->NumRacingCars + 14 - k;",
      "            int32_t idx = race->NumRacingCars + 15 - k;"),
    M("bonus-place-mark",
      "            mark_place_reached(p, race->NumRacingCars - 2 - k);",
      "            mark_place_reached(p, race->NumRacingCars - 1 - k);"),
    M("bonus-zero-scored", "        if (sum != 0) {", "        if (1) {"),
    M("bonus-kind", "gStartScoreFn(p, SCORING_START_BONUS, sum);",
      "gStartScoreFn(p, SCORING_START_BONUS + 1, sum);"),

    # racesplit.c.
    M("rs-last-lap-is-best", "    return boundary_timer(rc->RunningTimes,",
      "    return boundary_timer(rc->BestRunningTimes,", R),
    M("rs-previous-best-is-best",
      "    return boundary_timer(rc->PreviousBestRunningTimes,",
      "    return boundary_timer(rc->BestRunningTimes,", R),
    M("rs-boundary-unbounded",
      "    if (i < 0 || i >= RACE_MAX_BOUNDARIES) {", "    if (i < 0) {", R),
    M("rs-reasons-swapped", "    0x49448, 0x49445,", "    0x49445, 0x49448,", R),
    M("rs-both-done-reversed",
      "        out->PackedTime = b->RaceTime.PackedTime - "
      "a->RaceTime.PackedTime;",
      "        out->PackedTime = a->RaceTime.PackedTime - "
      "b->RaceTime.PackedTime;", R),
    M("rs-a-done-added", "        out->PackedTime = t.PackedTime - done_for(r, a);",
      "        out->PackedTime = t.PackedTime + done_for(r, a);", R),
    M("rs-b-done-taken", "        out->PackedTime = t.PackedTime + done_for(r, b);",
      "        out->PackedTime = t.PackedTime - done_for(r, b);", R),
    M("rs-a-done-exact",
      "        ta = time_around_track(r, (float)a->NumLapsCompleted);",
      "        ta = time_around_track(r, a->FinishedLapNumberExact);", R),
    M("rs-b-done-exact",
      "        tb = time_around_track(r, (float)b->NumLapsCompleted);",
      "        tb = time_around_track(r, b->FinishedLapNumberExact);", R),
    M("rs-neither-reversed", "        timer_set_time(out, tb - ta);",
      "        timer_set_time(out, ta - tb);", R),
    M("rs-done-from-0",
      "    return (uint32_t)WorldTimer - c->RaceTime.PackedTime\n"
      "           - r->StartTime.PackedTime;",
      "    return (uint32_t)WorldTimer - c->RaceTime.PackedTime;", R),
    M("rs-no-table",
      "    if (r->pTimeAroundTrackTable == NULL)\n        return 0.0f;",
      "    if (r->pTimeAroundTrackTable != NULL)\n        return 0.0f;", R),
]

# Mutations whose transcript cannot differ, with the reason.
EQUIVALENT = {
    "lead-not-signed":
        "SetHudFeatures sets BUI_FMT_FIXEDWIDTH on the lead time whenever it "
        "finds it, so RenderHud's OR of the same bit changes nothing; both "
        "set the dirty flag",
    "pos-grow-shows-new":
        "RenderHud stores the position into LastRacePosition just before "
        "the big position, so the two are equal there",
    "pos-grow-flag-reversed":
        "the same: pos and LastRacePosition are equal, so both tests are 0",
    "rs-boundary-unbounded":
        "the bound is the port's; retail reads past BoundaryCrossingTimes "
        "for a StartLineBoundaryNumber of 5 or more, which the script leaves "
        "out",
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
