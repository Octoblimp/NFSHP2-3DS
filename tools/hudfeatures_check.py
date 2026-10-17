#!/usr/bin/env python3
"""Cross-check 3DS Files/source/playerhud.c, which parts of the HUD a
player shows and showing them, against the retail image, SLES_507.31.

**The model** is retail's own: Player::DetermineHudFeatures (0x00178da0),
SetHudFeatures (0x001796b0), SetTrackMapMode (0x00178c90, the port's
name) and RenderTrackMap (0x00181c08), and under them IsNisPlaying, ShouldShowBustedText,
tCopManager::ShouldDisplayBustedText, RaceParameters::IsFreeRun, the
gauge helper (0x001795f8), SetTrackMapMode's three table searches,
bSPrintf, bStringHash and the whole Flailer runtime on INGAMEB's Flailer
chunk, loaded by LoaderFlailerChunk as tools/flailer_check.py does. The
colour SetHudFeatures gives player 2's race position (0x002fbb20) is
filled by running its initialiser, 0x001831d0. The harness
(tools/src/hudfeatures_test.c) runs playerhud.c over flailer.c, bui.c,
bchunk.c, copmanager.c and raceparams.c on the same bundle.

**The stubs** are the callees not ported and what the renderer answers:
SetFlailerScreenVisibility (both copies, 0x0014cbf8 and 0x0016eb68),
SetRearViewMirrorCameraMover, ClearHudAnimations, HudStartWrongWay,
FillInRaceOverMessages, RaceFinishedSpeech, NISOverlayManager::SetVisible,
InitializeFlailerTachometer, TrackMap's constructor, destructor and Render,
eGetView and ChooseLoadableTextures, each printing its arguments; the
camera's GetPOV, IsExteriorView and IsLookingBack, through a fake vtable
at +40, answer what the script says; bMalloc hands out zeroed memory;
and the Flailer text and bitmap sizes are flailer_check.py's.
ChooseLoadableTextures writes words made from the car and the units, the
same on both sides.

**Compared** are DetermineHudFeatures' answers, the stubs' calls in order,
and after each op every line that changed: each Player's HUD fields (the
pFlailer* pointers by object, the words as hex, the TrackMap with its mode
word), the four views' LetterBox, the race's display settings and every
Flailer object's bytes. Every pointer field starts at a dummy object, so
one nothing writes prints "stray" until something does.

**The script** walks DetermineHudFeatures down each of its cases and back,
then SetHudFeatures through each bit on and off in one- and two-player
races, Be A Cop, free run, time trials and point to point, with the
gauges' cameras and cars both ways, then SetTrackMapMode over every mode
in each kind of race, RenderTrackMap with a map and without one, and
last a few frames of UpdateHud's head, which
calls SetHudFeatures only when DetermineHudFeatures' answer changed.

    python tools/hudfeatures_check.py
    python tools/hudfeatures_check.py --mutate [--only a,b]
    python tools/hudfeatures_check.py --dump out/hudfeatures
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
import player_check                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/hudfeatures_test.c"
HUD = "3DS Files/source/playerhud.c"
SOURCES = [HARNESS, HUD, "3DS Files/source/flailer.c",
           "3DS Files/source/bprintf.c", "3DS Files/source/bui.c",
           "3DS Files/source/bchunk.c",
           "3DS Files/source/replay.c", "3DS Files/source/p32.c",
           "3DS Files/source/copmanager.c", "3DS Files/source/raceparams.c"]

GP = fc.GP
RP = 0x0031a898                         # TheRaceParameters
G_NUM = GP - 20920                      # Player::NumPlayers
G_BY_NUMBER = GP - 20936                # Player::pPlayersByNumber[2]
G_RACE = GP - 22272                     # pCurrentRace
G_RC = GP - 22216                       # pRaceCoordinator
G_FRAMES = GP - 19600                   # RealTimeFrames
G_TRACK = GP - 21952                    # CurrentTrackInfo
G_COPMGR = GP - 15620                   # pCopManager
EGGS = 0x0031d7e8                       # TheEasterEggs, the port's name

F_DETERMINE = 0x00178da0
F_SET = 0x001796b0
F_MAP = 0x00178c90
F_RENDER_MAP = 0x00181c08
F_COLOUR = 0x001831d0

S_SCREEN = (0x0014cbf8, 0x0016eb68)
S_MIRROR = 0x001767a8
S_CLEAR = 0x0017c7c8
S_WRONGWAY = 0x0017c888
S_RACEOVER = 0x00181558
S_NISVIS = 0x00182a48
S_TACH = 0x001434a0
S_MAP_NEW = 0x001babb8
S_MAP_DEL = 0x001badc8
S_MAP_RENDER = 0x001bade8
S_SPEECH = 0x00206ab8
S_TEXTURES = 0x001ee3c0
S_VIEW = 0x00107c90
S_MALLOC = 0x002577c0

PLAYER_SIZE = 2752
NUM_VIEWS = 4

HUD_SINGLE = 0xf1f1f8e5
HUD_TOP = 0xa8eb7af0
HUD_BOTTOM = 0x6283be92

LOADS = ["GLOBAL/INGAMEB.BUN"]

# The transcript's fields: name, kind (p an object, w a word, m the
# TrackMap) and count, at player_check.py's retail offsets.
HUD_FIELDS = [
    ("pFlailerSpeedNeedle", "p", 1), ("pFlailerTachNeedle", "p", 1),
    ("pFlailerTachGear", "p", 1), ("pFlailerTachGradient", "p", 1),
    ("pFlailerRacePosition", "p", 1), ("pFlailerBigRacePosition", "p", 1),
    ("pFlailerBigRacePosition2", "p", 1),
    ("pFlailerBigRaceExtension", "p", 1), ("pFlailerBigRaceTotal", "p", 1),
    ("pFlailerLapCounter", "p", 1), ("pFlailerLapTime", "p", 1),
    ("pFlailerBestLap", "p", 1), ("pFlailerRunningSplitTime", "p", 1),
    ("pFlailerCompSplitTime", "p", 1), ("pFlailerTireForce", "p", 4),
    ("pFlailerSpeedString", "p", 1), ("pFlailerSpeedString2", "p", 1),
    ("pFlailerGearString", "p", 1), ("pFlailerShiftUp", "p", 1),
    ("pFlailerShiftDown", "p", 1), ("pFlailerPursuitStar", "p", 1),
    ("pFlailerPursuitLevel", "p", 4), ("pFlailerPursuitX", "p", 3),
    ("PrevPursuitLevel", "w", 1), ("pFlailerTracker", "p", 7),
    ("pFlailerEventTitle", "p", 1), ("pFlailerEventScore", "p", 1),
    ("pFlailerScoreTitle", "p", 1), ("pFlailerScoreTotal", "p", 1),
    ("pFlailerMusicArtist", "p", 1), ("pFlailerMusicTitle", "p", 1),
    ("pFlailerMusicLabel", "p", 1), ("pFlailerMusicEA", "p", 1),
    ("pFlailerRadarLight", "p", 12), ("pFlailerDamageLight", "p", 5),
    ("pFlailerBeTheCopTickets", "p", 4),
    ("pFlailerLiveSplitStatus", "p", 4), ("pFlailerLiveSplitSwatch", "p", 4),
    ("pFlailerLiveSplitPos", "p", 4), ("pFlailerLiveSplitBG", "p", 4),
    ("pFlailerLiveSplitBar", "p", 1), ("pFlailerBeTheCopTime", "p", 1),
    ("pFlailerBeTheCopHelicopter", "p", 3),
    ("pFlailerBeTheCopRoadblock", "p", 3), ("pFlailerLeadTitle", "p", 1),
    ("pFlailerLeadTime", "p", 1), ("CurrentHudFeatures", "w", 1),
    ("TotalScore", "w", 1), ("pTrackMap", "m", 1),
    ("TimeTrackMapModeChanged", "w", 1), ("PursuitObjectPos", "w", 14),
    ("bRadarOffset", "w", 1), ("fInitialRadarY", "w", 1),
]
OFFSET = {n: off for n, off, _, _ in player_check.PLAYER_FIELDS}

# The script's names: retail offset and size.
RP_FIELDS = {
    "RaceType": (32, 4), "TTT": (36, 4), "P2P": (40, 4), "Laps": (44, 4),
    "NPC": (48, 4), "NAI": (52, 4), "MaxCops": (604, 4), "BeACop": (628, 4),
    "RVM": (748, 1), "Units": (749, 1), "Map1": (750, 1), "Map2": (751, 1),
    "MapC": (752, 1), "Leader": (753, 1),
}
PLAYER_SET = {
    "PN": (16, 4), "view": (24, 4), "hud": (32, 1), "pov": (36, 1),
    "pref": (48, 4), "new44": (76, 4), "tfr": (80, 4), "zone": (88, 4),
    "reset": (176, 4), "wrongway": (760, 4), "lookback": (764, 4),
    "chf": (768, 4), "screen": (772, 4), "ttmmc": (1532, 4),
    "score": (1524, 4), "radaroff": (2668, 4), "radary": (2672, 4),
    "prevpl": (OFFSET["PrevPursuitLevel"], 4),
}
CAR_HUD = {"tx": 20, "ty": 22, "sx": 56, "sy": 58, "stx": 60, "sty": 62,
           "rx": 64, "ry": 66}


def fbits(v):
    return struct.unpack("<I", struct.pack("<f", v))[0]


# ================================================================== script

def common():
    """The two players, their cars and cameras, and a race in progress."""
    s = ["g|np|1", "g|rc|3", "g|before|3", "g|stage|4", "g|racing|4",
         "g|frames|1000", "g|cop|1", "g|byn|0|0", "g|byn|1|1",
         "rp|RaceType|1", "rp|NPC|1", "rp|NAI|3", "rp|Laps|3", "rp|RVM|1",
         "rp|Units|0", "rp|Map1|0", "rp|Map2|7", "rp|MapC|8", "rp|Leader|2"]
    for k, (screen, ctype) in enumerate(((HUD_SINGLE, 7), (HUD_BOTTOM, 9))):
        s += ["pl|%d|PN|%d" % (k, k), "pl|%d|view|%d" % (k, k),
              "pl|%d|screen|%#x" % (k, screen), "pl|%d|car|1" % k,
              "pl|%d|cam|1" % k, "pl|%d|new44|1" % k,
              "cam|%d|type|1" % k, "cam|%d|pov|0" % k,
              "car|%d|type|%d" % (k, ctype), "car|%d|tx|%d" % (k, 30 + k),
              "car|%d|ty|%d" % (k, 40 - k), "car|%d|sx|50" % k,
              "car|%d|sy|-60" % k, "car|%d|stx|10" % k, "car|%d|sty|12" % k,
              "car|%d|rx|5" % k, "car|%d|ry|-7" % k,
              "car|%d|reason|%d" % (k, 3 + k)]
    return s


def s_determine():
    s = ["use|0"]

    def det(*env):
        s.extend(env)
        s.append("det")

    # No car, no screen, a camera zone, the demos, replays, after the race.
    det("pl|0|car|0")
    det("pl|0|car|1", "pl|0|screen|0")
    det("pl|0|screen|%#x" % HUD_SINGLE, "pl|0|zone|1")
    det("pl|0|zone|2")
    det("pl|0|zone|-1")
    s.append("pl|0|zone|0")
    for rc in (8, 9, 4, 7, 5, 0, 1, 2):
        det("g|rc|%d" % rc)
    s.append("g|rc|3")

    # A NIS of the player's own.
    det("pl|0|nis|1")
    det("rp|MaxCops|2")
    det("g|rc|6")
    det("g|rc|3", "rp|NAI|0")
    det("rp|NAI|3", "rp|Laps|0")
    det("rp|Laps|3", "pl|0|hud|1")
    det("pl|0|hud|3")
    det("pl|0|hud|2")
    det("pl|0|hud|0", "rp|BeACop|1")
    det("rp|BeACop|0", "rp|RaceType|2", "rp|Laps|0")
    s += ["rp|RaceType|1", "rp|Laps|3"]
    det("g|np|2")
    det("rp|Map2|6")
    det("rp|Map2|7", "rp|BeACop|1")
    det("rp|BeACop|0", "rp|MaxCops|0")
    det("g|rc|6")
    s += ["g|rc|3", "use|1"]
    det("pl|1|nis|1")
    s += ["pl|1|nis|0", "use|0"]
    det("pl|0|nis|0", "g|np|1")

    # Player 0's NIS, seen by player 1 in Be A Cop.
    s += ["use|1", "g|np|2", "rp|BeACop|1"]
    det("pl|0|nis|1")
    det("pl|0|nis|0")
    det("pl|0|nis|1", "rp|BeACop|0")
    det("rp|BeACop|1", "pl|1|PN|0")
    det("pl|1|PN|1", "g|np|1")
    s += ["pl|0|nis|0", "rp|BeACop|0", "use|0"]

    # Busted.
    det("g|pull|3|1|1")
    det("g|rc|6")
    det("g|rc|3", "g|pull|3|1|0")
    det("g|pull|3|0|1")
    det("g|pull|3|0|0", "g|pull|0|1|1")
    det("g|pull|0|0|0", "g|pull|7|1|1")
    det("g|cop|0")
    s += ["g|cop|1", "g|pull|7|0|0"]

    # The stages before the race.
    for st in (1, 2, 3, 0):
        det("g|stage|%d" % st)
    det("g|stage|3", "g|np|2")
    s += ["g|np|1", "g|stage|4"]

    # Finished.
    det("pl|0|tfr|100")
    det("g|np|2")
    det("pl|1|tfr|5")
    det("pl|1|tfr|0", "rp|Map2|6")
    det("rp|Map2|7", "rp|BeACop|1")
    s += ["rp|BeACop|0", "use|1"]
    det("pl|1|tfr|7")
    s += ["pl|1|tfr|0", "use|0"]
    det("g|np|1", "g|rc|5")
    s += ["pl|0|tfr|0", "g|rc|3"]

    # Paused.
    s.append("g|rc|6")
    for b in (1, 2, 3, 0, 6):
        det("g|before|%d" % b)
    s.append("g|before|3")
    det("pl|0|ttmmc|990")
    det("pl|0|ttmmc|941")
    det("pl|0|ttmmc|940")
    det("pl|0|ttmmc|1010")
    det("pl|0|ttmmc|0x80000000")
    det("pl|0|ttmmc|0", "g|before|1")
    s += ["g|before|3", "g|rc|3"]

    # HUD state 0: each preference and what takes it away.
    for pref in (0, 0x100, 0x4, 0x10, 0x200, 0x40, 0x8, 0xffffffff):
        det("pl|0|pref|%#x" % pref)
    det("cam|0|back|1")
    det("cam|0|back|0", "rp|Map1|6")
    det("rp|Map1|3", "rp|RVM|0")
    det("rp|RVM|1", "pl|0|lookback|1")
    det("pl|0|lookback|0", "rp|RaceType|2")
    det("rp|P2P|1")
    det("rp|P2P|0", "rp|RaceType|1", "rp|NAI|0")
    det("rp|NAI|3", "rp|Laps|0")
    det("rp|BeACop|1")
    det("rp|BeACop|0", "rp|Laps|3", "rp|TTT|12345")
    det("rp|TTT|0x7fffffff")
    det("rp|TTT|0", "rp|Leader|0")
    det("rp|Leader|2", "g|np|2")
    det("g|np|1", "rp|MaxCops|3")
    det("pl|0|lookback|1")
    det("pl|0|lookback|0", "pl|0|pref|0x200")
    det("pl|0|pref|0xffffffff", "pl|0|new44|0")
    det("pl|0|new44|1", "rp|MaxCops|0", "rp|BeACop|1")
    det("cam|0|lb|%#x" % fbits(1.0))
    det("cam|0|type|2")
    det("cam|0|type|1", "cam|0|lb|%#x" % fbits(0.5))
    det("cam|0|lb|%#x" % fbits(1.0), "pl|0|cam|0")
    det("pl|0|cam|1", "pl|0|PN|1")
    det("g|np|2")
    det("pl|0|PN|0")
    s += ["g|np|1", "rp|BeACop|0", "cam|0|lb|0"]
    # The gauges.
    det("pl|0|cam|0")
    det("pl|0|cam|1", "cam|0|pov|-1")
    det("cam|0|pov|0", "cam|0|ext|1")
    det("cam|0|ext|0", "rp|NPC|2")
    det("rp|NPC|1")
    det("rp|NPC|3")
    det("rp|NPC|1", "cam|0|pov|1")
    det("cam|0|pov|2")
    det("cam|0|pov|0", "pl|0|PN|0", "pl|0|pov|3")
    s.append("pl|0|pov|0")

    # The other HUD states.
    for st in (1, 2, 3, 4, -1):
        s.append("pl|0|hud|%d" % st)
        det("rp|MaxCops|0")
        det("rp|MaxCops|2")
        det("rp|BeACop|1")
        det("rp|BeACop|0", "g|np|2")
        s.append("g|np|1")
    s += ["pl|0|hud|2", "g|rc|5", "pl|0|tfr|9"]
    det()
    s += ["pl|0|tfr|0", "g|rc|3", "pl|0|hud|3"]
    det("cam|0|pov|1")
    s += ["cam|0|pov|0", "rp|MaxCops|0", "pl|0|hud|0"]

    # What every case gets at the end.
    det("pl|0|wrongway|1")
    det("pl|0|wrongway|0", "pl|0|reset|50")
    det("pl|0|reset|0x7fffffff")
    det("pl|0|reset|0", "rp|MaxCops|2", "g|np|2")
    det("pl|0|pref|0", "cam|0|back|1")
    s += ["use|1"]
    det("pl|1|pref|0xffffffff")
    det("pl|1|wrongway|1", "pl|1|reset|1")
    s += ["pl|1|wrongway|0", "pl|1|reset|0", "use|0", "g|np|1",
          "rp|MaxCops|0", "cam|0|back|0", "pl|0|pref|0"]
    return s


# SetHudFeatures' bits, each with what it takes alone.
BITS = [0x1, 0x2, 0x4, 0x8, 0x20, 0x40, 0x80, 0x200, 0x400, 0x1000,
        0x2000, 0x4000, 0x8000, 0x10000, 0x20000, 0x40000, 0x80000,
        0x100000, 0x200000, 0x800000, 0x1000000, 0x2000000, 0x4000000,
        0x8000000, 0x10000000]


def s_set_bits():
    """Every bit on alone and off again, then pairs, in a 1P race."""
    s = ["use|0"]
    for b in BITS:
        s += ["set|%#x" % b, "set|0"]
    s += ["set|0x40000", "set|0x40000", "set|0"]
    # Pairs that share objects or fields.
    for f in (0x408, 0x8, 0x400, 0x200 | 0x800000, 0x800000, 0x200,
              0x20 | 0x10000000, 0x40 | 0x10000000, 0x8000 | 0x4000000,
              0x8000 | 0x8000000, 0x4000000 | 0x8000000, 0x80 | 0x200,
              0x1000 | 0x80000, 0x80000, 0x1000 | 0x80000, 0x80000):
        s += ["set|%#x" % f]
    s.append("set|0")
    return s


def s_set_cases():
    s = ["use|0"]
    # The gauges: units, integrated, a car with no tach, two players.
    for env in (["car|0|integ|1"], ["rp|Units|1"], ["car|0|type|6"],
                ["car|0|integ|0", "g|np|2"], ["rp|Units|0"],
                ["g|np|1", "car|0|type|7"]):
        s += env + ["set|0x20", "set|0x40", "set|0x60", "set|0"]
    s += ["rp|Units|2", "set|0x40", "set|0x20", "set|0", "rp|Units|0"]

    # The in-car digits over the gauges and without them.
    s += ["set|0x20", "set|0x10000020", "set|0x20", "set|0x10000000",
          "set|0x10000040", "set|0"]

    # The race position for each player.
    s += ["g|np|2", "set|0x200", "set|0", "use|1", "set|0x200", "set|0",
          "use|0", "g|np|1"]

    # The lap block in each kind of race.
    for env in (["rp|P2P|1"], ["rp|P2P|0", "rp|RaceType|2"],
                ["rp|TTT|12345"], ["rp|P2P|1"], ["rp|RaceType|1"],
                ["rp|TTT|0x7fffffff"], ["rp|TTT|0", "rp|P2P|0", "g|np|2"],
                ["rp|BeACop|1"], ["rp|BeACop|0", "rp|Laps|0"],
                ["g|np|1"], ["rp|BeACop|1"],
                ["rp|Laps|3", "rp|RaceType|2",
                             "rp|TTT|777", "rp|BeACop|1"],
                ["rp|BeACop|0", "rp|RaceType|1", "rp|TTT|0"],
                ["rp|TTT|4321"]):
        s += env + ["set|0x8", "set|0x400", "set|0x408", "set|0"]
    s.append("rp|TTT|0")

    # The live split under each anchor and for each number of cars.
    for racing in (4, 3, 1, 0, 9):
        s += ["g|racing|%d" % racing, "set|0x800000", "set|0x800200",
              "set|0x200", "set|0"]
    s.append("g|racing|4")

    # The track map in each kind of race and HUD state.
    for env in (["rp|Map1|3"], ["rp|Map1|6"], ["pl|0|hud|1"],
                ["rp|Map1|4", "pl|0|hud|0"], ["g|np|2", "rp|Map2|6"],
                ["rp|Map2|7"], ["use|1"], ["use|0", "rp|BeACop|1"],
                ["rp|MapC|6"], ["rp|MapC|8", "rp|BeACop|0", "g|np|1",
                                "rp|Map1|9"]):
        s += env + ["set|0x1", "g|frames|2000", "set|0", "g|frames|1000"]
    s += ["rp|Map1|0"]

    # The pursuit meters, each over a level left from before.
    for f in (0x8000, 0x4000000, 0x8000000):
        s += ["pl|0|prevpl|3", "set|%#x" % f, "set|0"]
    s += ["pl|0|prevpl|3", "set|0x8000", "pl|0|prevpl|3", "set|0x8008000",
          "pl|0|prevpl|3", "set|0x4000000", "set|0"]

    # The score, the music and the race over.
    s += ["pl|0|score|-12345", "set|0x20000", "pl|0|score|7", "set|0",
          "set|0x20000", "set|0x60000", "set|0x40000", "set|0",
          "set|0x4", "car|0|reason|-2", "set|0", "set|0x4", "set|0",
          "car|0|reason|3"]

    # The wrong way, the reset prompt, the letterbox in each view.
    s += ["set|0x4000", "set|0", "set|0x10000", "set|0"]
    for v in (0, 2, 3):
        s += ["pl|0|view|%d" % v, "set|0x2000", "set|0"]
    s.append("pl|0|view|0")

    # The bars in each race.
    for env in (["g|np|1"], ["g|np|2"], ["g|stage|1"], ["g|stage|2"],
                ["g|stage|3"], ["use|1"], ["use|0", "rp|BeACop|1"],
                ["rp|BeACop|0", "g|np|0", "g|stage|4"]):
        s += env + ["set|0x2000000", "set|0"]
    s.append("g|np|1")

    # The radar under the mirror and away from it.
    s += ["set|0x80000", "set|0x81000", "set|0x1000", "set|0x81000",
          "set|0x80000", "set|0", "set|0x1000", "set|0x80000",
          "set|0x81000", "set|0"]
    s += ["pl|0|radaroff|1", "pl|0|radary|%#x" % fbits(12.5),
          "set|0x81000", "set|0x80000", "set|0"]
    s += ["g|np|2", "set|0x81000", "set|0", "g|np|1"]

    # Be The Cop for each player, the tracker, the egg, the NIS overlay.
    s += ["set|0x1000000", "set|0", "pl|0|PN|1", "set|0x1000000", "set|0",
          "pl|0|PN|0", "set|0x100000", "set|0", "g|egg|1", "set|0",
          "set|0x200000", "g|egg|0", "set|0"]

    # The screen and the mirror, from nothing and back to nothing.
    s += ["pl|0|chf|0x60", "set|0", "pl|0|chf|0x40000", "set|0x40000",
          "set|0x1040000", "set|0"]
    return s


def s_two_players():
    """Each bit on and off on the split screens, in a race and in Be A
    Cop, and the update for each player."""
    s = ["g|np|2", "rp|NPC|2", "pl|0|screen|%#x" % HUD_TOP]
    for cop in (0, 1):
        s.append("rp|BeACop|%d" % cop)
        for k in (0, 1):
            s.append("use|%d" % k)
            for b in BITS:
                s += ["set|%#x" % b, "set|0"]
            s += ["set|0x408", "set|0x800200", "set|0x8000", "set|0x4000000",
                  "set|0x20", "set|0x40", "set|0x1000000", "set|0"]
            s += ["pl|%d|pref|0xffffffff" % k, "rp|MaxCops|2", "upd", "upd",
                  "rp|MaxCops|0", "pl|%d|pref|0" % k, "upd", "set|0"]
    s += ["rp|BeACop|0", "use|0", "g|np|1", "rp|NPC|1",
          "pl|0|screen|%#x" % HUD_SINGLE]
    return s


def s_map():
    s = ["use|0", "rmap", "set|0x1", "rmap"]
    for env in ([], ["pl|0|PN|1"], ["pl|0|PN|0", "g|np|2"], ["use|1"],
                ["use|0", "rp|BeACop|1"], ["rp|BeACop|0", "g|np|1"]):
        s += env
        for m in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, -1):
            s.append("map|%d" % m)
            s.append("g|frames|%d" % (1000 + 7 * (m + 2)))
    s += ["use|1", "rmap", "use|0", "rmap", "set|0", "rmap", "map|3",
          "map|0", "g|frames|1000"]
    return s


def s_update():
    s = ["use|0", "pl|0|pref|0xffffffff", "rp|MaxCops|2", "pl|0|wrongway|1"]
    for st in (2, 3, 4):
        s += ["g|stage|%d" % st, "upd"]
    s += ["upd", "pl|0|wrongway|0", "upd", "cam|0|pov|1", "upd",
          "cam|0|pov|0", "rp|NPC|3", "upd", "g|rc|6", "upd", "g|rc|3",
          "pl|0|nis|1", "upd", "pl|0|nis|0", "pl|0|tfr|1", "upd",
          "pl|0|tfr|0", "pl|0|hud|1", "upd", "pl|0|hud|0", "upd",
          "pl|0|car|0", "upd"]
    return s


def script():
    s = ["load|%s" % (fc.SD / p) for p in LOADS]
    s += common()
    s += s_determine()
    s += s_set_bits()
    s += s_set_cases()
    s += s_two_players()
    s += s_map()
    s += s_update()
    s.append("order")
    return s


# =================================================================== model

class Model(fc.Model):
    def __init__(self):
        fc.Model.__init__(self)
        e = self.e
        self.lines = {}
        self.order_keys = []
        self.cur_player = 0

        e.write(RP, bytes(788))
        for g in (G_NUM, G_BY_NUMBER, G_BY_NUMBER + 4, G_FRAMES, G_COPMGR):
            e.put32(g, 0)
        e.call(F_COLOUR, limit=10000)

        self.race = e.alloc(64)
        self.rc = e.alloc(64)
        self.copmgr = e.alloc(312)
        self.track = e.alloc(16)
        self.eggs = e.alloc(512)
        e.put32(G_RACE, self.race)
        e.put32(G_RC, self.rc)
        e.put32(G_TRACK, self.track)
        e.put32(EGGS + 12, self.eggs)
        self.views = [e.alloc(128) for _ in range(NUM_VIEWS)]
        self.dummy = e.alloc(256)

        def fn(f):
            a = e.alloc(16)
            e.stub(a, f)
            return a

        vtbl = e.alloc(128)
        for off, f in ((56, self.s_pov), (64, self.s_ext),
                       (72, self.s_back)):
            e.write(vtbl + off, struct.pack("<h", 0))
            e.put32(vtbl + off + 4, fn(f))
        self.povs = [e.alloc(32) for _ in range(2)]
        self.pov_type = [0, 0]
        self.cam_ext = [0, 0]
        self.cam_back = [0, 0]

        self.players, self.cars, self.cams, self.nis = [], [], [], []
        for k in range(2):
            p = e.alloc(PLAYER_SIZE)
            for name, kind, count in HUD_FIELDS:
                if kind == "p":
                    for i in range(count):
                        e.put32(p + OFFSET[name] + 4 * i, self.dummy)
            nis = e.alloc(128)
            e.put32(p + 244, nis)
            car = e.alloc(64)
            e.put32(car + 12, e.alloc(1312))
            e.put32(car + 16, e.alloc(16))
            e.put32(car + 28, e.alloc(64))
            cam = e.alloc(256)
            e.put32(cam + 40, vtbl)
            self.players.append(p)
            self.cars.append(car)
            self.cams.append(cam)
            self.nis.append(nis)

        for a in S_SCREEN:
            e.stub(a, self.s_screen)
        e.stub(S_MIRROR, self.s_mirror)
        e.stub(S_CLEAR, self.s_clear)
        e.stub(S_WRONGWAY, self.s_wrongway)
        e.stub(S_RACEOVER, self.s_raceover)
        e.stub(S_NISVIS, self.s_nisvis)
        e.stub(S_TACH, self.s_tach)
        e.stub(S_MAP_NEW, self.s_map_new)
        e.stub(S_MAP_DEL, self.s_map_del)
        e.stub(S_MAP_RENDER, self.s_map_render)
        e.stub(S_SPEECH, self.s_speech)
        e.stub(S_TEXTURES, self.s_textures)
        e.stub(S_VIEW, self.s_view)
        e.stub(S_MALLOC, self.s_malloc)

    # ---- stubs

    def arg(self, em, i):
        return em.reg[4 + i] & M32

    def pname(self, a):
        if a == self.players[0]:
            return "p0"
        if a == self.players[1]:
            return "p1"
        return "p?"

    def player(self):
        return self.players[self.cur_player]

    def s_screen(self, em):
        self.emit("  screen %08x %d" % (self.arg(em, 0),
                                        s32(self.arg(em, 1))))

    def s_mirror(self, em):
        self.emit("  mirror %s %d" % (self.pname(self.arg(em, 0)),
                                      self.arg(em, 1)))

    def s_clear(self, em):
        self.emit("  clear %s" % self.pname(self.arg(em, 0)))

    def s_wrongway(self, em):
        self.emit("  wrongway %s" % self.pname(self.arg(em, 0)))

    def s_raceover(self, em):
        self.emit("  raceover %s" % self.pname(self.arg(em, 0)))

    def s_nisvis(self, em):
        o = self.arg(em, 0)
        self.emit("  nisvis %s %d" % (
            self.pname(self.player()) if o == self.player() + 2560 else "bad",
            self.arg(em, 1)))

    def s_tach(self, em):
        pts = self.arg(em, 2)
        self.emit("  tach %s %s %s" % (
            self.name(self.arg(em, 0)), self.name(self.arg(em, 1)),
            "pts" if pts == self.player() + 796 else "bad"))

    def s_map_new(self, em):
        this, t, c, p = (self.arg(em, i) for i in range(4))
        ok = p in self.players and c == self.e.u32(p + 4)
        self.emit("  newmap t%d c%d %s" % (t == self.track, ok,
                                           self.pname(p)))
        self.e.write(this, bytes(176))
        return this

    def s_map_del(self, em):
        m, flags = self.arg(em, 0), self.arg(em, 1)
        ok = m == self.e.u32(self.player() + 1528)
        self.emit("  delmap %s" % ("ok" if ok and flags == 3 else
                                   "bad" if not ok else "flags %d" % flags))

    def s_map_render(self, em):
        m = self.arg(em, 0)
        ok = m == self.e.u32(self.player() + 1528)
        self.emit("  rendermap %s" % ("ok" if ok else "bad"))

    def s_speech(self, em):
        c = self.arg(em, 0)
        self.emit("  speech c%d %d" % (c == self.e.u32(self.player() + 4),
                                       s32(self.arg(em, 1))))

    def s_textures(self, em):
        car, units, out = (s32(self.arg(em, i)) for i in range(3))
        self.emit("  textures %d %d" % (car, units))
        e = self.e
        out &= M32
        e.put32(out, 0x1000 + car * 16 + units)
        e.put32(out + 4, 0 if car % 3 == 0 else 0x2000 + car)
        e.put32(out + 8, 0x3000 + car)
        e.put32(out + 12, 0x4000 + units)

    def s_view(self, em):
        i = s32(self.arg(em, 0))
        self.emit("  view %d" % i)
        return self.views[i]

    def s_malloc(self, em):
        return self.e.alloc(s32(self.arg(em, 0)), align=16)

    def cam_index(self, m):
        return 0 if m == self.cams[0] else 1

    def s_pov(self, em):
        n = self.cam_index(self.arg(em, 0))
        self.emit("  pov %d" % s32(self.arg(em, 1)))
        if self.pov_type[n] < 0:
            return 0
        self.e.put32(self.povs[n], self.pov_type[n])
        return self.povs[n]

    def s_ext(self, em):
        self.emit("  ext")
        return self.cam_ext[self.cam_index(self.arg(em, 0))]

    def s_back(self, em):
        self.emit("  lookback")
        return self.cam_back[self.cam_index(self.arg(em, 0))]

    # ---- output

    def name(self, a):
        if a == 0:
            return "none"
        return self.obj_at.get(a, "stray")

    def note(self, key, text):
        old = self.lines.get(key)
        if old != text:
            self.lines[key] = text
            self.emit("  %s %s" % (key, text))

    def dump_player(self, n):
        e = self.e
        p = self.players[n]
        for name, kind, count in HUD_FIELDS:
            for i in range(count):
                a = p + OFFSET[name] + 4 * i
                key = ("p%d.%s[%d]" % (n, name, i) if count > 1
                       else "p%d.%s" % (n, name))
                v = e.u32(a)
                if kind == "p":
                    text = self.name(v)
                elif kind == "m":
                    text = "none" if v == 0 else "map:%d" % s32(e.u32(v + 160))
                else:
                    text = "%08x" % v
                self.note(key, text)

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

    def dump(self):
        self.dump_player(0)
        self.dump_player(1)
        for v in range(NUM_VIEWS):
            self.note("view%d" % v, "lb %d" % self.e.mem[self.views[v] + 5])
        self.note("gds", bytes(self.e.mem[RP + 748:RP + 756]).hex())
        self.dump_objects()

    # ---- ops

    def put(self, a, size, v):
        if size == 4:
            self.e.put32(a, v)
        elif size == 2:
            self.e.write(a, struct.pack("<H", v & 0xffff))
        else:
            self.e.mem[a] = v & 0xff

    def set_player(self, k, n, v):
        p = self.players[k]
        e = self.e
        if n in PLAYER_SET:
            off, size = PLAYER_SET[n]
            self.put(p + off, size, v)
        elif n == "car":
            e.put32(p + 4, self.cars[k] if v else 0)
        elif n == "cam":
            e.put32(p + 200, self.cams[k] if v else 0)
        elif n == "nis":
            e.put32(self.nis[k] + 68, v)
        else:
            raise ValueError(n)

    def set_cam(self, k, n, v):
        c = self.cams[k]
        if n == "type":
            self.e.put32(c + 8, v)
        elif n == "lb":
            self.e.put32(c + 124, v)
        elif n == "pov":
            self.pov_type[k] = s32(v)
        elif n == "ext":
            self.cam_ext[k] = v
        elif n == "back":
            self.cam_back[k] = v
        else:
            raise ValueError(n)

    def set_car(self, k, n, v):
        e = self.e
        c = self.cars[k]
        if n == "type":
            e.put32(e.u32(c + 16), v)
        elif n == "integ":
            e.put32(e.u32(c + 12) + 1232, v)
        elif n in CAR_HUD:
            self.put(e.u32(c + 12) + 1232 + CAR_HUD[n], 2, v)
        elif n == "reason":
            self.put(e.u32(c + 28) + 18, 2, v)
        else:
            raise ValueError(n)

    def set_global(self, a):
        e = self.e
        k, v = a[0], int(a[1], 0) & M32
        if k == "np":
            e.put32(G_NUM, v)
        elif k == "rc":
            e.put32(self.rc, v)
        elif k == "before":
            e.put32(self.rc + 24, v)
        elif k == "stage":
            e.put32(self.race, v)
        elif k == "racing":
            e.put32(self.race + 24, v)
        elif k == "frames":
            e.put32(G_FRAMES, v)
        elif k == "egg":
            e.put32(self.eggs + 48 + 56 * 4, v)
        elif k == "cop":
            e.put32(G_COPMGR, self.copmgr if v else 0)
        elif k == "pull":
            pl = self.copmgr + 88 + 28 * v
            e.put32(pl + 12, int(a[2], 0))
            e.put32(pl + 24, int(a[3], 0))
        elif k == "byn":
            who = int(a[2], 0)
            e.put32(G_BY_NUMBER + 4 * v, 0 if who < 0 else self.players[who])
        else:
            raise ValueError(k)

    def op(self, a):
        e = self.e
        o = a[0]
        if o == "load":
            self.load(a[1])
            return
        if o == "order":
            self.order()
            return
        v = lambda i: int(a[i], 0) & M32      # noqa: E731
        if o == "rp":
            off, size = RP_FIELDS[a[1]]
            self.put(RP + off, size, v(2))
        elif o == "pl":
            self.set_player(int(a[1]), a[2], v(3))
        elif o == "cam":
            self.set_cam(int(a[1]), a[2], v(3))
        elif o == "car":
            self.set_car(int(a[1]), a[2], v(3))
        elif o == "g":
            self.set_global(a[1:])
        elif o == "use":
            self.cur_player = int(a[1])
        elif o == "det":
            r = e.call(F_DETERMINE, self.player(), limit=1000000) & M32
            self.emit("  = %08x" % r)
        elif o == "set":
            e.call(F_SET, self.player(), s32(v(1)), limit=200000000)
        elif o == "map":
            e.call(F_MAP, self.player(), s32(v(1)), limit=1000000)
        elif o == "rmap":
            e.call(F_RENDER_MAP, self.player(), limit=1000000)
        elif o == "upd":
            # UpdateHud's head (0x0017ed18 to 0x0017ed34): SetHudFeatures
            # only when the answer differs from CurrentHudFeatures.
            p = self.player()
            r = e.call(F_DETERMINE, p, limit=1000000) & M32
            if r != e.u32(p + OFFSET["CurrentHudFeatures"]):
                e.call(F_SET, p, s32(r), limit=200000000)
        else:
            raise ValueError(o)
        self.dump()


def model(lines):
    return Model().run(lines)


# ================================================================= build

def build_harness(tmp, name="hudfeatures_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


run_harness = fc.run_harness
diff = pcc.diff
write_script = fc.write_script


# ============================================================= mutations

H = HUD
COP = "3DS Files/source/copmanager.c"
RPS = "3DS Files/source/raceparams.c"


def M(name, before, after, rel=H):
    return (name, rel, before, after)


MUTATIONS = [
    # DetermineHudFeatures: the early answers.
    M("det-no-car", "if (p->MyCar == NULL || p->HudScreenHash == 0)",
      "if (p->HudScreenHash == 0)"),
    M("det-no-screen", "if (p->MyCar == NULL || p->HudScreenHash == 0)",
      "if (p->MyCar == NULL)"),
    M("det-zone-positive", "    if (p->nZoneCurrent != 0)\n        return HUD_MUSIC;",
      "    if (p->nZoneCurrent > 0)\n        return HUD_MUSIC;"),
    M("det-demo-ai",
      "if (rc == RCSTATE_AI_DEMO_MODE || rc == RCSTATE_REPLAY_DEMO_MODE)",
      "if (rc == RCSTATE_REPLAY_DEMO_MODE)"),
    M("det-replay-auto",
      "if (rc == RCSTATE_INSTANT_REPLAY || rc == RCSTATE_POSTRACE)",
      "if (rc == RCSTATE_AUTO_REPLAY || rc == RCSTATE_POSTRACE)"),
    # The NIS case.
    M("det-nis-other-any-player",
      "(np == 2 && p->PlayerNumber == 1 && cop != 0",
      "(np == 2 && cop != 0"),
    M("det-nis-other-no-cop",
      "(np == 2 && p->PlayerNumber == 1 && cop != 0",
      "(np == 2 && p->PlayerNumber == 1"),
    M("det-nis-pursuit-pause",
      "if (rp->nMaxCops != 0 && rc != RCSTATE_PAUSE && np == 1)",
      "if (rp->nMaxCops != 0 && np == 1)"),
    M("det-nis-pursuit-np",
      "if (rp->nMaxCops != 0 && rc != RCSTATE_PAUSE && np == 1)",
      "if (rp->nMaxCops != 0 && rc != RCSTATE_PAUSE)"),
    M("det-nis-one-car",
      "        if (rp->NumPlayerCars + rp->NumAICars == 1\n"
      "            || race_parameters_is_free_run(rp) || state == 1",
      "        if (race_parameters_is_free_run(rp) || state == 1"),
    M("det-nis-state-2", "|| state == 1 || state == 3\n",
      "|| state == 1 || state == 2\n"),
    M("det-nis-overlay-pause",
      "        if (rc != RCSTATE_PAUSE)\n            f |= HUD_NIS_OVERLAY;",
      "        f |= HUD_NIS_OVERLAY;"),
    M("det-nis-bars-cop",
      "        if (np == 1 || cop != 0)\n            f |= HUD_CINEMA_BARS;",
      "        if (np == 1)\n            f |= HUD_CINEMA_BARS;"),
    M("det-nis-map-player",
      "        if (np != 2 || p->PlayerNumber != 0 || cop != 0\n",
      "        if (np != 2 || cop != 0\n"),
    M("det-nis-map-mode",
      "|| ds->TwoPlayerTrackMapMode == TRACKMAP_MODE_OFF)\n            return f;",
      "|| ds->OnePlayerTrackMapMode == TRACKMAP_MODE_OFF)\n            return f;"),
    # Busted, the stages, finished, paused.
    M("det-busted-pause",
      "return rc == RCSTATE_PAUSE ? HUD_MUSIC : HUD_MUSIC | HUD_NIS_OVERLAY;",
      "return HUD_MUSIC | HUD_NIS_OVERLAY;"),
    M("det-stage-prerace",
      "if (stage == RACE_STAGE_FLYBY || stage == RACE_STAGE_PRERACE)",
      "if (stage == RACE_STAGE_FLYBY)"),
    M("det-countdown-np", "if (stage == RACE_STAGE_COUNTDOWN && np == 1)",
      "if (stage == RACE_STAGE_COUNTDOWN)"),
    M("det-finished-rc",
      "if (p->TimeFinishedRacing != 0 && rc == RCSTATE_RACE_IN_PROGRESS)",
      "if (p->TimeFinishedRacing != 0)"),
    M("det-finished-other", "            || q->TimeFinishedRacing != 0\n", ""),
    M("det-finished-mode",
      "|| ds->TwoPlayerTrackMapMode == TRACKMAP_MODE_OFF)\n"
      "            return HUD_MUSIC | HUD_RACE_OVER;",
      "|| ds->OnePlayerTrackMapMode == TRACKMAP_MODE_OFF)\n"
      "            return HUD_MUSIC | HUD_RACE_OVER;"),
    M("det-pause-before",
      "if ((uint32_t)(pRaceCoordinator->BeforePauseRCState - 1) < 2)",
      "if ((uint32_t)(pRaceCoordinator->BeforePauseRCState - 1) < 3)"),
    M("det-pause-60", ">= 60) {", "> 60) {"),
    M("det-pause-keeps-time",
      "            p->TimeTrackMapModeChanged = 0;\n            return f;",
      "            return f;"),
    M("det-pause-unsigned",
      "if ((int32_t)((uint32_t)RealTimeFrames - p->TimeTrackMapModeChanged)",
      "if (((uint32_t)RealTimeFrames - p->TimeTrackMapModeChanged)"),
    # HUD state 0.
    M("det-tracker-lookback",
      "        if (m != NULL && m->vtbl->IsLookingBack(m))\n"
      "            f &= ~HUD_TRACKER;",
      "        (void)m;"),
    M("det-map-mode-np", "             : np == 2 ? ds->TwoPlayerTrackMapMode",
      "             : np == 1 ? ds->TwoPlayerTrackMapMode"),
    M("det-cop-lb-type", "            && m->Type == CM_DRIVE\n", ""),
    M("det-cop-lb-value", "DesiredLookBackParam == 1.0f)",
      "DesiredLookBackParam != 0.0f)"),
    M("det-cop-lb-player",
      "if (cop != 0 && p->PlayerNumber == 0 && m != NULL",
      "if (cop != 0 && m != NULL"),
    M("det-pref-lap", "        if (s & 0x100)\n            f |= HUD_LAP_TIME;",
      "        if (s & 0x8)\n            f |= HUD_LAP_TIME;"),
    M("det-pref-split", "        if (s & 0x4)\n            f |= HUD_SPLIT_TIMES;",
      "        if (s & 0x80)\n            f |= HUD_SPLIT_TIMES;"),
    M("det-pref-pos", "        if (s & 0x10)\n            f |= HUD_RACE_POSITION;",
      "        if (s & 0x200)\n            f |= HUD_RACE_POSITION;"),
    M("det-pref-best", "        if (s & 0x100)\n            f |= HUD_LAP_COUNTER;",
      "        if (s & 0x400)\n            f |= HUD_LAP_COUNTER;"),
    M("det-pref-0x100", "        if (s & 0x100)\n            f |= HUD_BEST_LAP;",
      "        (void)0;"),
    M("det-live-np", "if ((s & 0x200) && np == 1 && cop == 0",
      "if ((s & 0x200) && cop == 0"),
    M("det-live-ttt",
      "            && (rp->TimeTrialTime.PackedTime == 0\n"
      "                || rp->TimeTrialTime.PackedTime == 0x7fffffff)\n", ""),
    M("det-live-leader",
      "&& !race_parameters_is_free_run(rp) && ds->LeaderboardMode != 0)",
      "&& !race_parameters_is_free_run(rp))"),
    M("det-live-free",
      "&& !race_parameters_is_free_run(rp) && ds->LeaderboardMode != 0)",
      "&& ds->LeaderboardMode != 0)"),
    M("det-mirror-lookback",
      "if (ds->RearViewMirror != 0 && p->bLookBack == 0)",
      "if (ds->RearViewMirror != 0)"),
    M("det-tt-p2p",
      "if (rp->RaceType == RACE_TYPE_TIME_TRIAL && rp->Point2Point == 0)",
      "if (rp->RaceType == RACE_TYPE_TIME_TRIAL)"),
    M("det-one-car",
      "        if (rp->NumPlayerCars + rp->NumAICars == 1\n"
      "            || race_parameters_is_free_run(rp))\n"
      "            f &= ~HUD_RACE_POSITION;",
      "        if (race_parameters_is_free_run(rp))\n"
      "            f &= ~HUD_RACE_POSITION;"),
    M("det-pursuit-pref", "? HUD_PURSUIT : HUD_PURSUIT_HI;",
      "? HUD_PURSUIT_HI : HUD_PURSUIT;"),
    M("det-radar-lookback",
      "            if (p->bLookBack == 0)\n                f |= HUD_RADAR;",
      "            f |= HUD_RADAR;"),
    M("det-cop-p0-mask",
      "                f = (f & ~(HUD_LAP_TIME | HUD_SPLIT_TIMES | HUD_BEST_LAP\n",
      "                f = (f & ~(HUD_SPLIT_TIMES | HUD_BEST_LAP\n"),
    M("det-cop-p1-mask",
      "                f = (f & ~(HUD_SPLIT_TIMES | HUD_BEST_LAP | HUD_RACE_POSITION))",
      "                f = (f & ~(HUD_SPLIT_TIMES | HUD_RACE_POSITION))"),
    M("det-score-free",
      "if (!race_parameters_is_free_run(rp) && (cop == 0 || np != 2)",
      "if ((cop == 0 || np != 2)"),
    M("det-score-cop",
      "if (!race_parameters_is_free_run(rp) && (cop == 0 || np != 2)",
      "if (!race_parameters_is_free_run(rp) && cop == 0"),
    M("det-score-new44", "            && p->PlayerSettings.New44 != 0)",
      "            )"),
    M("det-gauge-pref",
      "        if (p->PlayerSettings.PreferredHudFeatures & 0x40)\n"
      "            f |= gauge_features(p);",
      "        f |= gauge_features(p);"),
    # The other HUD states and the end.
    M("det-state1-np", "        if (np == 1)\n            f |= HUD_TRACK_MAP;",
      "        f |= HUD_TRACK_MAP;"),
    M("det-state2-tfr",
      "if (rp->nMaxCops != 0 && cop == 0 && p->TimeFinishedRacing == 0)",
      "if (rp->nMaxCops != 0 && cop == 0)"),
    M("det-state3-gauges",
      "            f |= HUD_PURSUIT_HI;\n        f |= gauge_features(p);\n",
      "            f |= HUD_PURSUIT_HI;\n"),
    M("det-cop-mask",
      "        f &= ~(HUD_RACE_POSITION | HUD_PURSUIT | HUD_PURSUIT_HI);",
      "        f &= ~(HUD_RACE_POSITION | HUD_PURSUIT);"),
    M("det-np2-hi", "            f = (f & ~HUD_PURSUIT_HI) | HUD_PURSUIT;",
      "            f = f | HUD_PURSUIT;"),
    M("det-np2-tracker", "        f &= ~HUD_TRACKER;\n    }", "    }"),
    M("det-np2-p1-map",
      "    if (np == 2 && p->PlayerNumber == 1)\n        f &= ~HUD_TRACK_MAP;",
      "    if (p->PlayerNumber == 1)\n        f &= ~HUD_TRACK_MAP;"),
    M("det-reset-max", "if (reset != 0 && reset != 0x7fffffff)",
      "if (reset != 0)"),

    # The gauge helper.
    M("gauge-ext",
      "    if (m->vtbl->IsExteriorView(m))\n        return HUD_GAUGES_OUTSIDE;\n",
      ""),
    M("gauge-np2",
      "    if (TheRaceParameters.NumPlayerCars == 2)\n"
      "        return HUD_GAUGES_OUTSIDE;\n", ""),
    M("gauge-bumper-np",
      "if (pov->Type == POV_BUMPER && TheRaceParameters.NumPlayerCars == 1)",
      "if (pov->Type == POV_BUMPER)"),
    M("gauge-pov-index",
      "pov = m->vtbl->GetPOV(m, p->PlayerSettings.DriveCameraPOVIndex);",
      "pov = m->vtbl->GetPOV(m, 0);"),
    M("gauge-incar-outside", "    if (pov->Type == POV_INCAR)",
      "    if (pov->Type != POV_BUMPER)"),

    # RenderTrackMap.
    M("rmap-no-test",
      "    if (p->pTrackMap != NULL && gTrackMapRenderFn != NULL)\n"
      "        gTrackMapRenderFn(p->pTrackMap);",
      "    if (gTrackMapRenderFn != NULL)\n"
      "        gTrackMapRenderFn(p->pTrackMap);"),
    M("rmap-never",
      "        gTrackMapRenderFn(p->pTrackMap);", "        ;"),

    # SetTrackMapMode.
    M("map-1p-table",
      "static const int32_t OnePlayerModes[] = { 0, 1, 2, 3, 4, 6 };",
      "static const int32_t OnePlayerModes[] = { 0, 1, 2, 3, 4, 5 };"),
    M("map-miss-last", "    return modes[0];\n}", "    return modes[n - 1];\n}"),
    M("map-p1-off", "mode = p->PlayerNumber >= 1 ? TRACKMAP_MODE_OFF",
      "mode = p->PlayerNumber >= 2 ? TRACKMAP_MODE_OFF"),
    M("map-same-stamps", "    if (*stored != mode) {", "    {"),
    M("map-stamp",
      "        p->TimeTrackMapModeChanged = (uint32_t)RealTimeFrames;\n", ""),
    M("map-no-handoff",
      "    if (p->pTrackMap != NULL)\n        memcpy(",
      "    if (0)\n        memcpy("),
    M("map-cop-table", "static const int32_t BeTheCopModes[] = { 8, 6 };",
      "static const int32_t BeTheCopModes[] = { 7, 6 };"),

    # SetHudFeatures: the start.
    M("set-cur-keeps-gauges",
      "uint32_t cur = p->CurrentHudFeatures & ~(HUD_GAUGES | HUD_GAUGES_OUTSIDE);",
      "uint32_t cur = p->CurrentHudFeatures;"),
    M("set-no-clear",
      "    if (gPlayerClearHudAnimationsFn != NULL)\n"
      "        gPlayerClearHudAnimationsFn(p);\n", ""),
    M("set-screen-show-any",
      "        if (f != 0)\n            screen_visibility(h, FLAILER_SCREEN_VISIBLE);",
      "        screen_visibility(h, FLAILER_SCREEN_VISIBLE);"),
    M("set-screen-hide-never",
      "    } else if (f == 0) {\n        screen_visibility(h, FLAILER_SCREEN_INVISIBLE);",
      "    } else if (f == 1) {\n        screen_visibility(h, FLAILER_SCREEN_INVISIBLE);"),
    M("set-screen-old-word",
      "    p->CurrentHudFeatures = cur;\n", ""),
    M("set-mirror-always",
      "if ((chg & HUD_REAR_VIEW_MIRROR) && gPlayerSetRearViewMirrorCameraMoverFn)",
      "if (gPlayerSetRearViewMirrorCameraMoverFn)"),
    M("set-gauges-outside-first",
      "    if (chg & HUD_GAUGES)\n        show_gauges(",
      "    if ((chg & HUD_GAUGES) && !(chg & HUD_GAUGES_OUTSIDE))\n"
      "        show_gauges("),
    M("set-no-hide-gauges", "    else\n        hide_gauges(h);",
      "    else\n        (void)0;"),

    # The bumper gauges.
    M("gauges-off-list",
      "0x7be1e0f4, 0xc8842af9, 0x7bb54948, 0xcf9bf6f3,\n    };",
      "0x7be1e0f4, 0xc8842af9, 0x7bb54948,\n    };"),
    M("gauges-units", "TheRaceParameters.GlobalDisplaySettings.Units, &tex);",
      "0, &tex);"),
    M("gauges-speedo-y", "ay + hud_info_s16(ti, HUDINFO_SPEEDO_Y));",
      "ay + hud_info_s16(ti, HUDINFO_SPEEDO_X));"),
    M("gauges-shadow-texture",
      "flailer_change_texture(h, 0xd9098a4b, tex.Shadow);",
      "flailer_change_texture(h, 0xd9098a4b, tex.Speedo);"),
    M("gauges-integrated-sense", "if (hud_info_is_integrated(ti) == 0) {",
      "if (hud_info_is_integrated(ti) != 0) {"),
    M("gauges-gear-offset",
      "flailer_set_top_left_position(h, 0xf81dffa6, ax + stx + 18,",
      "flailer_set_top_left_position(h, 0xf81dffa6, ax + stx + 16,"),
    M("gauges-int-rpm-30", "                                          - 30);",
      "                                          - 20);"),
    M("gauges-int-tach-kept", "        flailer_set_visibility(h, 0x01223abd, 0);\n",
      ""),
    M("gauges-tach-gear-kept",
      "    p->pFlailerTachGear = NULL;\n    p->pFlailerGearString = find(h, 0xf81dffa6",
      "    p->pFlailerGearString = find(h, 0xf81dffa6"),
    M("gauges-shift-up-text",
      "p->pFlailerShiftUp = find(h, 0x7aa7a2a1, FLAILER_TYPE_BITMAP);",
      "p->pFlailerShiftUp = find(h, 0x7aa7a2a1, FLAILER_TYPE_TEXT);"),
    M("gauges-format-gear",
      "    set_format(p->pFlailerGearString, BUI_FMT_FIXEDWIDTH);\n}", "}"),
    M("gauges-no-tach", "    init_tachometer(p);\n    // Retail sets",
      "    // Retail sets"),
    M("gauges-v-ignored", "    set_visibility_all(h, on, sizeof on / sizeof on[0], v);\n"
      "    ChooseLoadableTextures(p->MyCar->pRideInfo->Type,",
      "    set_visibility_all(h, on, sizeof on / sizeof on[0], 1);\n"
      "    ChooseLoadableTextures(p->MyCar->pRideInfo->Type,"),

    # The third-person gauge.
    M("outside-kmh-is-mph",
      ": bchunk_hash(\"3RDPERSONGAUGE_KMH\");",
      ": bchunk_hash(\"3RDPERSONGAUGE_MPH\");"),
    M("outside-mph-np",
      "t = PlayerNumPlayers > 1 ? bchunk_hash(\"3RDPERSONGAUGE_MPH\")",
      "t = PlayerNumPlayers > 2 ? bchunk_hash(\"3RDPERSONGAUGE_MPH\")"),
    M("outside-format-dirty",
      "    or_format(p->pFlailerSpeedString, BUI_FMT_FIXEDWIDTH);\n"
      "    or_format(p->pFlailerSpeedString2, BUI_FMT_FIXEDWIDTH);\n}",
      "    set_format(p->pFlailerSpeedString, BUI_FMT_FIXEDWIDTH);\n"
      "    or_format(p->pFlailerSpeedString2, BUI_FMT_FIXEDWIDTH);\n}"),
    M("outside-speed-needle",
      "p->pFlailerSpeedNeedle = find(h, 0xc637891c, FLAILER_TYPE_BITMAP);",
      "p->pFlailerSpeedNeedle = find(h, 0x8d28acce, FLAILER_TYPE_BITMAP);"),

    # The in-car digits and the race position.
    M("incar-no-hide",
      "        if (v == 1) {\n            hide(p->pFlailerSpeedString);\n"
      "            hide(p->pFlailerSpeedString2);\n        }\n", ""),
    M("incar-format-set",
      "            or_format(p->pFlailerSpeedString, BUI_FMT_FIXEDWIDTH);\n"
      "        }\n    }\n\n    if (chg & HUD_RACE_POSITION)",
      "            set_format(p->pFlailerSpeedString, BUI_FMT_FIXEDWIDTH);\n"
      "        }\n    }\n\n    if (chg & HUD_RACE_POSITION)"),
    M("pos-colour-p0",
      "if (PlayerNumPlayers == 2 && p->PlayerNumber == 1) {\n"
      "            flailer_set_object_color",
      "if (PlayerNumPlayers == 2 && p->PlayerNumber == 0) {\n"
      "            flailer_set_object_color"),
    M("pos-colour", "{ 0.0f, 79.0f, 128.0f, 128.0f }",
      "{ 0.0f, 80.0f, 128.0f, 128.0f }"),
    M("pos-big2-visible",
      "        p->pFlailerBigRacePosition2 = find(h, 0x4c769c11",
      "        flailer_set_visibility(h, 0x4c769c11, v);\n"
      "        p->pFlailerBigRacePosition2 = find(h, 0x4c769c11"),

    # The lap block.
    M("lap-group-v", "        group_visibility(h, 0xb7a3bc7a, 0);",
      "        group_visibility(h, 0xb7a3bc7a, on);"),
    M("lap-lead-cop",
      "if (TheRaceParameters.BeACop == 0 && PlayerNumPlayers == 2 && on) {",
      "if (PlayerNumPlayers == 2 && on) {"),
    M("lap-lead-kept",
      "            p->pFlailerLeadTitle = NULL;\n"
      "            p->pFlailerLeadTime = NULL;\n", ""),
    M("lap-format-best",
      "        set_format(p->pFlailerBestLap, BUI_FMT_FIXEDWIDTH);\n", ""),
    M("lap-objects-off", "        if (on)\n            set_visibility_all(h, LapObjects,",
      "        if (1)\n            set_visibility_all(h, LapObjects,"),
    M("lap-free-counter-kept", "            p->pFlailerLapCounter = NULL;\n", ""),
    M("lap-labels-p2p", "rp->Point2Point != 0 ? 0x494ab : 0x494aa);",
      "rp->Point2Point != 0 ? 0x494aa : 0x494ab);"),
    M("lap-labels-target-tt",
      "    int32_t target = rp->RaceType == RACE_TYPE_TIME_TRIAL && tt != 0",
      "    int32_t target = tt != 0"),
    M("lap-labels-target-p2p",
      "        if (!target && rp->Point2Point != 0 && tt != 0",
      "        if (0 && rp->Point2Point != 0 && tt != 0"),
    M("lap-labels-target-cop",
      "        && tt != 0x7fffffff && rp->BeACop == 0;",
      "        && tt != 0x7fffffff;"),
    M("lap-labels-free-third",
      "(struct FlailerTextChunk *)o, 0x494a8);\n        return;",
      "(struct FlailerTextChunk *)o, 0x494da);\n        return;"),

    # The split times and the live split.
    M("split-visible", "        flailer_set_visibility(h, 0x89c3ac59, 0);",
      "        flailer_set_visibility(h, 0x89c3ac59, (int32_t)(f >> 7) & 1);"),
    M("live-anchor-swap", "(f & HUD_RACE_POSITION) ? 0x363392ae : 0x363392af",
      "(f & HUD_RACE_POSITION) ? 0x363392af : 0x363392ae"),
    M("live-dx-from-y", "        dx = ax - sx;", "        dx = ay - sy;"),
    M("live-racing-le",
      "if (pCurrentRace == NULL || pCurrentRace->NumRacingCars <= i)",
      "if (pCurrentRace == NULL || pCurrentRace->NumRacingCars < i)"),
    M("live-v-bit", "    int32_t v = (int32_t)(f >> 23) & 1;",
      "    int32_t v = (int32_t)(f >> 9) & 1;"),
    M("live-bar-kept",
      "    if (p->pFlailerLiveSplitBar != NULL)\n"
      "        flailerobject_set_visibility(p->pFlailerLiveSplitBar, v);",
      "    (void)0;"),
    M("live-trigger-pos",
      "    if (chg & (HUD_LIVE_SPLIT | HUD_RACE_POSITION))\n        show_live_split",
      "    if (chg & HUD_LIVE_SPLIT)\n        show_live_split"),
    M("live-status-format",
      "        set_format(p->pFlailerLiveSplitStatus[i], BUI_FMT_FIXEDWIDTH);\n",
      ""),

    # The track map.
    M("map-delete-kept", "            p->pTrackMap = NULL;\n        } else {",
      "        } else {"),
    M("map-state1-2",
      "                    && mode == TRACKMAP_MODE_OFF)\n                    mode = 2;",
      "                    && mode == TRACKMAP_MODE_OFF)\n                    mode = 3;"),
    M("map-cop-mode", "                mode = ds->BeTheCopTrackMapMode;",
      "                mode = ds->TwoPlayerTrackMapMode;"),

    # The tyres, the pursuit meters, the score, the music.
    M("tire-bit", "        v = (int32_t)(f >> 1) & 1;", "        v = (int32_t)f & 1;"),
    M("tire-order", "p->pFlailerTireForce[0] = find(h, 0x13be6877",
      "p->pFlailerTireForce[0] = find(h, 0x12420a8a"),
    M("pursuit-v-not-one",
      "    if (v != 1)\n        return;\n    p->pFlailerPursuitStar",
      "    p->pFlailerPursuitStar"),
    M("pursuit-alpha",
      "(struct FlailerBitmapChunk *)p->pFlailerPursuitLevel[i], 0,",
      "(struct FlailerBitmapChunk *)p->pFlailerPursuitLevel[i], 0x80,"),
    M("pursuit-level-visible",
      "            flailerobject_set_visibility(p->pFlailerPursuitLevel[i], 0);",
      "            flailerobject_set_visibility(p->pFlailerPursuitLevel[i], 1);"),
    M("pursuit-dummy-from-0",
      "d = find_numbered(h, dummy, i + 1, FLAILER_TYPE_BITMAP);",
      "d = find_numbered(h, dummy, i, FLAILER_TYPE_BITMAP);"),
    M("pursuit-pos-swap",
      "            p->PursuitObjectPos[i].x = d->X;\n"
      "            p->PursuitObjectPos[i].y = d->Y;",
      "            p->PursuitObjectPos[i].x = d->Y;\n"
      "            p->PursuitObjectPos[i].y = d->X;"),
    M("pursuit-prev-kept", "    p->PrevPursuitLevel = 0;\n", ""),
    M("pursuit-hi-bit", "\"PURSUIT_DUMMY_HI_%d\", (int32_t)(f >> 26) & 1);",
      "\"PURSUIT_DUMMY_HI_%d\", (int32_t)(f >> 27) & 1);"),
    M("pursuit-nis-dummy", "\"PURSUIT_DUMMY_NIS_%d\"", "\"PURSUIT_DUMMY_HI_%d\""),
    M("score-null-kept",
      "            p->pFlailerEventTitle = NULL;\n"
      "            p->pFlailerEventScore = NULL;\n", ""),
    M("score-no-hide", "            hide(p->pFlailerScoreTitle);\n", ""),
    M("score-unsigned", "snprintf(buf, sizeof buf, \"%d\", (int)p->TotalScore);",
      "snprintf(buf, sizeof buf, \"%u\", (unsigned)p->TotalScore);"),
    M("music-null-kept",
      "            p->pFlailerMusicTitle = NULL;\n"
      "            p->pFlailerMusicArtist = NULL;\n", ""),
    M("music-no-hide", "            hide(p->pFlailerMusicEA);\n", ""),

    # The race over, the wrong way, the reset prompt, the letterbox.
    M("over-objects-v", "        flailer_set_visibility(h, 0x76494c5b, 0);",
      "        flailer_set_visibility(h, 0x76494c5b, v);"),
    M("over-no-speech", "            if (gRaceFinishedSpeechFn != NULL)\n",
      "            if (0)\n"),
    M("over-group2", "        group_visibility(h, 0x97f9252a, v);\n", ""),
    M("wrongway-once",
      "            if (v == 1 && gPlayerHudStartWrongWayFn != NULL)\n"
      "                gPlayerHudStartWrongWayFn(p);\n        }\n",
      "        }\n        if (v == 1 && gPlayerHudStartWrongWayFn != NULL)\n"
      "            gPlayerHudStartWrongWayFn(p);\n"),
    M("reset-bit", "group_visibility(h, 0xf74c9d43, (int32_t)(f >> 16) & 1);",
      "group_visibility(h, 0xf74c9d43, (int32_t)(f >> 15) & 1);"),
    M("letterbox-view", "eGetView(p->ViewID)->LetterBox",
      "eGetView(0)->LetterBox"),

    # The bars.
    M("bars-sense", "v = (int32_t)((f >> 25) ^ 1) & 1;",
      "v = (int32_t)(f >> 25) & 1;"),
    M("bars-2p-cop",
      "            if (TheRaceParameters.BeACop == 0\n                && (pCurrentRace",
      "            if (1\n                && (pCurrentRace"),
    M("bars-2p-prerace",
      "                        && pCurrentRace->RaceStage != RACE_STAGE_PRERACE))) {",
      "                        ))) {"),
    M("bars-2p-player", "screen_visibility(p->PlayerNumber == 0 ? 0xaccbfcb8",
      "screen_visibility(p->PlayerNumber == 1 ? 0xaccbfcb8"),
    M("bars-2p-whole",
      "                screen_visibility(0x49c15518, FLAILER_SCREEN_INVISIBLE);",
      "                screen_visibility(0x49c15518, v);"),

    # The radar.
    M("radar-offset-np",
      "        p->bRadarOffset = 1;\n        mirror = (chg & HUD_REAR_VIEW_MIRROR) != 0;",
      "        mirror = (chg & HUD_REAR_VIEW_MIRROR) != 0;"),
    M("radar-mirror-f", "mirror = (chg & HUD_REAR_VIEW_MIRROR) != 0;",
      "mirror = (f & HUD_REAR_VIEW_MIRROR) != 0;"),
    M("radar-init-always", "if (p->fInitialRadarY == 0.0f && l0 != NULL) {",
      "if (l0 != NULL) {"),
    M("radar-first-each", "            first = 0;\n", ""),
    M("radar-down", "flailerobject_set_top_left_y(o, y + 70.0f);",
      "flailerobject_set_top_left_y(o, y + 60.0f);"),
    M("radar-up", "flailerobject_set_top_left_y(o, y - 70.0f);",
      "flailerobject_set_top_left_y(o, y + 70.0f);"),
    M("radar-np2-moves", "        if (PlayerNumPlayers != 1)\n            continue;",
      "        (void)0;"),
    M("radar-offset-skip", "            if (p->bRadarOffset != 0)\n                continue;",
      "            (void)0;"),

    # Be The Cop, the tracker, the egg, the NIS overlay, the last word.
    M("cop-p1-finds",
      "        if (p->PlayerNumber == 0) {\n            p->pFlailerBeTheCopHelicopter",
      "        if (p->PlayerNumber <= 1) {\n            p->pFlailerBeTheCopHelicopter"),
    M("cop-time-dirty",
      "    or_format(p->pFlailerBeTheCopTime, BUI_FMT_FIXEDWIDTH);\n}",
      "    set_format(p->pFlailerBeTheCopTime, BUI_FMT_FIXEDWIDTH);\n}"),
    M("cop-x-from-0", "h, \"BETHECOP_X_%d\", i + 1, FLAILER_TYPE_BITMAP);",
      "h, \"BETHECOP_X_%d\", i, FLAILER_TYPE_BITMAP);"),
    M("tracker-from-1", "find_numbered(h, \"TRACKER_%d\", i,",
      "find_numbered(h, \"TRACKER_%d\", i + 1,"),
    M("egg-number", "gEggIsOnFn != NULL && gEggIsOnFn(4) != 0);",
      "gEggIsOnFn != NULL && gEggIsOnFn(5) != 0);"),
    M("egg-on-change", "    flailer_set_group_visibility(h, 0x06d1f9fb,",
      "    if (chg) flailer_set_group_visibility(h, 0x06d1f9fb,"),
    M("nis-value-bool",
      "gNisOverlaySetVisibleFn(&p->mFlailerNIS, f & HUD_NIS_OVERLAY);",
      "gNisOverlaySetVisibleFn(&p->mFlailerNIS, (f & HUD_NIS_OVERLAY) != 0);"),
    M("chf-not-final", "    p->CurrentHudFeatures = f;\n}",
      "    p->CurrentHudFeatures = f & ~HUD_GAUGES;\n}"),

    # UpdateHud's head.
    M("upd-always-set",
      "    if (f != p->CurrentHudFeatures)\n        player_set_hud_features(p, f);",
      "    player_set_hud_features(p, f);"),

    # ShouldShowBustedText and IsFreeRun.
    M("busted-any",
      "copmanager_should_display_busted_text(pCopManager) != 0;", "1;"),
    M("busted-active",
      "if (pl[i].bActive && pl[i].bShouldDisplayBustedText)",
      "if (pl[i].bShouldDisplayBustedText)", COP),
    M("busted-seven", "for (i = 0; i < COPMANAGER_NUM_PULLOVERS; i++)",
      "for (i = 0; i < COPMANAGER_NUM_PULLOVERS - 1; i++)", COP),
    M("freerun-cop", "rp->NumLapsInRace == 0\n        && rp->BeACop == 0;",
      "rp->NumLapsInRace == 0;", RPS),
    M("freerun-type",
      "return rp->RaceType == RACE_TYPE_SINGLE_RACE && rp->NumLapsInRace == 0",
      "return rp->NumLapsInRace == 0", RPS),
]

EQUIVALENT = {
    # Every HUD state that sets PURSUIT_HI does so only under cop == 0, and
    # the gauges never return it, so Be A Cop's mask finds it clear.
    "det-cop-mask":
        "no HUD state sets PURSUIT_HI in Be A Cop; each needs cop == 0",
    # SetHudFeatures takes both gauge bits out of `cur` before the xor, so
    # a change in HUD_GAUGES means f holds it, and v is (f >> 5) & 1 == 1.
    "gauges-v-ignored":
        "chg & HUD_GAUGES means f has the bit, so v is always 1",
    # The music texts (0x6fc12a41, 0x3c374056, 0x1f87a436) and BUSTED
    # (0x76494c5b) are on BEST_LAP_TIMES, BEST_TOTAL_TIMES and the busted
    # screens, none of the three HUD screens, so the finds answer NULL and
    # the visibility call finds nothing to set.
    "music-null-kept":
        "the music texts are not on the HUD screens; the finds left NULL",
    "music-no-hide":
        "the EA text is not on the HUD screens; hide(NULL) does nothing",
    "over-objects-v":
        "BUSTED is not on the HUD screens; the call finds no object",
    # Group 0xbbbb857c holds exactly one object, 0x89af1a1e, on each HUD
    # screen, so starting the animation per object starts it once.
    "wrongway-once":
        "the wrong-way group has one object on each HUD screen",
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
