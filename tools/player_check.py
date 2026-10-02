#!/usr/bin/env python3
"""Cross-check 3DS Files/source/playerinit.c and nisoverlay.c, the
Player's lifetime and the NIS overlay it owns, against the retail image
itself, run in mipsemu.

The model is the image. Player's constructor (0x001751d8) and destructor
(0x00175bf0), InitForRace (0x00181920), PredetermineNisNumbers
(0x001819e0), CleanupAfterRace (0x00181970), CleanUpJumpCam (0x00176ab0)
and cPlayerSettings::ResetToDefaults (0x001edf90) run as shipped, and so do
NISOverlayManager's constructor (0x00182350), destructor (0x00182430),
SetScreen (0x001829a8) and Finish (0x00182948) under them, and bStrCpy.
The harness (tools/src/player_test.c) runs the port over the same script,
and the two transcripts are diffed.

Everything else under them is a stub that prints its arguments: bMalloc,
__builtin_delete and __builtin_vec_delete, TopologyCoordinate's
constructor and destructor, GetJoystickType, bSPrintf (which formats in
Python and prints nothing), NisManager's constructor, destructor and
Stop, Average's constructor and destructor, GetInGameSample,
FindFlailerObject, FlailerObjectChunk's GetTopLeft, SetScaleX, SetScaleY
and SetTopLeftY, FlailerGetScale, FlailerGetTopLeftY,
SetFlailerScreenVisibility, RealDriver::SetManualTransmission,
RadialBlurOff, Player's RemoveCameraMovers, SetInputMode,
CreateRandomNisArray, ResetFlailerMovement and SetHudFeatures, and the
destructors of PreviewRoute, VisibleDrivingLine and HudAnimator. The zone
sample has a fake vtable at +184 whose destructor slot is a stub too.
AutoPilotOff runs; it is a bare `jr ra`.

The script lays out the rest: two Players at retail's offsets, four cars
with a fake driver each, TheRaceParameters' words (0x0031a898) and its two
cPlayerSettings, and the gp words: the player tables, SkipFE, the POV byte
ResetToDefaults takes under it, WorldTimer and bResetGlare. Each Player is
filled before it is built, mostly with 0xa5 and sometimes with 0xff, 0x5a
or 0, and the bMalloc arena with 0xa5, so what a call leaves alone shows.
A NisManager's word at +68 says whether it plays.

The script keeps to what retail survives: no third player, no destructor
with none left, numbers 0 and 1, and CleanupAfterRace only with a car and
a NisManager. Retail's GetTopLeft on a missing score object reads the
object; the model's stub answers 0 for it and prints nothing, as the port
reads 0 without calling.

Before the run, every field the transcript names is asserted at its
retail offset in an ARM compile of player.h, when devkitARM is there.

    python tools/player_check.py
    python tools/player_check.py --mutate [--only a,b]
    python tools/player_check.py --dump out/player
"""
import argparse
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import physicscar_check as pcc
import retail_model
from mipsemu import M32, f_to_bits, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/player_test.c"
PIN = "3DS Files/source/playerinit.c"
NIS = "3DS Files/source/nisoverlay.c"
PLC = "3DS Files/source/player.c"
SOURCES = [HARNESS, PIN, NIS, PLC]

HARNESS_TIMEOUT = 120

ARM_GCC = Path("C:/devkitPro/devkitARM/bin/arm-none-eabi-gcc.exe")
CTRU_INCLUDE = Path("C:/devkitPro/libctru/include")

# ================================================================ the image

GP = 0x003358f0
CTOR = 0x001751d8
DTOR = 0x00175bf0
INIT_FOR_RACE = 0x00181920
CLEANUP = 0x00181970
PREDETERMINE = 0x001819e0
JUMP_CAM = 0x00176ab0
RESET_DEFAULTS = 0x001edf90

B_MALLOC = 0x002577c0
B_DELETE = 0x00114e98
B_VEC_DELETE = 0x00114e90
B_SPRINTF = 0x00251398
TOPO_CTOR = 0x00151c28
TOPO_DTOR = 0x00151c70
JOY_TYPE = 0x00154308
NIS_CTOR = 0x001b0fe0
NIS_DTOR = 0x001b1110
NIS_STOP = 0x001b1388
AVG_CTOR = 0x0018fbf0
AVG_DTOR = 0x0018fc68
GET_SAMPLE = 0x001ae280
FIND_FLAILER = 0x00143d50
GET_TOP_LEFT = 0x00140978
GET_SCALE = 0x001444e8
GET_TOP_Y = 0x00144168
SET_VIS = 0x0014cbf8
SET_SCALE_X = 0x001407d0
SET_SCALE_Y = 0x001407f8
SET_TOP_Y = 0x00140a48
SET_MANUAL = 0x0013b390
AUTO_PILOT_OFF = 0x001788b0
RADIAL_OFF = 0x0010f1b0
RM_CAMS = 0x00177430
SET_INPUT = 0x001776b0
RAND_NIS = 0x00181a28
RESET_FLAILER = 0x0017bd20
SET_HUD = 0x001796b0
ROUTE_DTOR = 0x00164848
LINE_DTOR = 0x00175030
HUD_DTOR = 0x0023b168

G_NUM = GP - 20920
G_BY_INDEX = GP - 20928
G_BY_NUMBER = GP - 20936
G_SKIPFE = GP - 23220
G_SKIPPOV = GP - 23172
G_TIMER = GP - 19576
G_GLARE = GP - 23564

RP = 0x0031a898
RP_AIDEMO = RP + 24
RP_REPLAY = RP + 28
RP_CARS = RP + 48
RP_BEACOP = RP + 628
RP_SETTINGS = RP + 652

PLAYER_BYTES = 2752
P_NUMBER = 16
P_SETTINGS = 32
P_ROUTE = 136
P_ZONE_SAMPLE = 140
P_AVG = 160
P_DC = 188
P_LINE = 228
P_MGR = 244
P_HUDS = 1540
P_CD = 1652
P_FOV = 1760
P_JUMP = 1764
P_TOPO = 1768
P_NIS = 2560
P_CAR = 4
# The F op's plain words, which the destructor zeroes: LastSpeed,
# PrevPursuitLevel, PrevTicketLevel and LastSpeedSet's bits.
P_WORDS = {"lastspeed": 1624, "pursuit": 1104, "ticket": 1108,
           "speedset": 1628}

O_SCREEN = 4
O_BUSTED = 20

C_PLAYER = 24
C_MODE = 32
C_DRIVER = 44
C_DRIVER_MODE = 988     # State (68) + DriverMode (920)

NIS_PLAYING = 68
SAMPLE_VTBL = 184

NOBJ = 4096
OBJ_BYTES = 1024
APOOL = 0x01000000
MISC = APOOL + NOBJ * OBJ_BYTES
PLAYERS = MISC
PLAYER_STRIDE = 0x1000
NPLAYER = 2
CARS = MISC + 0x2000
CAR_STRIDE = 0x400
NCAR = 4
DRIVERS = MISC + 0x3000
ROUTE = MISC + 0x3100
JUMP_ROUTE = MISC + 0x3140
ZONE_SAMPLE = MISC + 0x3200
ZS_VTBL = MISC + 0x3300
LINE = MISC + 0x3340
HUDS = MISC + 0x3400
NHUD = 20
BUSTED = MISC + 0x3600
SCORE_OBJS = MISC + 0x3640
RADAR_BEEP = MISC + 0x3700
STUBS = MISC + 0x3800       # the fake functions, eight bytes apart

PATTERN = 0xa5

SCORE_HASH = (0x464ba8ea, 0xd911beac, 0xf7f1cfb3, 0xf88dd0b1)

# The transcript's Player, in the harness's order: name, retail offset,
# kind (w a word, p a pointer, b a byte) and count. The TopologyCoordinate
# (1768, 704 bytes) only the stubs touch; the overlay (2560) has its own.
PLAYER_FIELDS = [
    ("NisFinishedCallback", 0, "p", 1), ("MyCar", 4, "p", 1),
    ("JoyPort", 8, "w", 1), ("JoyType", 12, "w", 1),
    ("PlayerNumber", 16, "w", 1), ("pOtherPlayer", 20, "p", 1),
    ("ViewID", 24, "w", 1), ("RearViewMirrorViewID", 28, "w", 1),
    ("PlayerSettings", 32, "b", 48), ("TimeFinishedRacing", 80, "w", 1),
    ("FinishAnimationLength", 84, "w", 1), ("nZoneCurrent", 88, "w", 1),
    ("nZonePrevious", 92, "w", 1), ("nZoneCredits", 96, "b", 8),
    ("tAutoZoneTimers", 104, "w", 8), ("pRoute", 136, "p", 1),
    ("pZoneSample", 140, "p", 1), ("bZoneMuffleSound", 144, "w", 1),
    ("fZoneMuffleVolume", 148, "w", 1), ("tIgnoreNextPovChange", 152, "w", 1),
    ("fFreezeZoneDelayTimer", 156, "w", 1), ("pAverageSpeedRatio", 160, "p", 1),
    ("tAverageSpeedTimer", 164, "w", 1), ("fMaxSpeedRatio", 168, "w", 1),
    ("LastTimeCarInTrouble", 172, "w", 1),
    ("TimeToDisplayResetPrompt", 176, "w", 1), ("New180", 180, "w", 1),
    ("tZoneSoundTimer", 184, "w", 1), ("DrivingControls", 188, "w", 1),
    ("nGlueCount", 192, "w", 1), ("PlayerInputMode", 196, "w", 1),
    ("pCameraMover", 200, "p", 1), ("pSavedCameraMover", 204, "p", 1),
    ("pSavedCameraMover2", 208, "p", 1), ("pRVMCameraMover", 212, "p", 1),
    ("pDemoCameraCoordinator", 216, "p", 1),
    ("pCountdownCameraCoordinator", 220, "p", 1),
    ("pNisCameraCoordinator", 224, "p", 1),
    ("pVisibleDrivingLine", 228, "p", 1), ("ArrestNisIndex", 232, "w", 1),
    ("TicketNisIndex", 236, "w", 1), ("NisFinishedCallbackParam", 240, "w", 1),
    ("pNisManager", 244, "p", 1), ("TicketNisNumbers", 248, "w", 32),
    ("TicketCameraNumbers", 376, "w", 32), ("ArrestNisNumbers", 504, "w", 32),
    ("ArrestCameraNumbers", 632, "w", 32), ("bWrongWay", 760, "w", 1),
    ("bLookBack", 764, "w", 1), ("CurrentHudFeatures", 768, "w", 1),
    ("HudScreenHash", 772, "w", 1), ("NisOverlayHash", 776, "w", 1),
    ("pFlailerSpeedNeedle", 780, "p", 1), ("pFlailerTachNeedle", 784, "p", 1),
    ("pFlailerTachGear", 788, "p", 1), ("pFlailerTachGradient", 792, "p", 1),
    ("FlailerTachPointList", 796, "b", 180),
    ("pFlailerRacePosition", 976, "p", 1),
    ("pFlailerBigRacePosition", 980, "p", 1),
    ("pFlailerBigRacePosition2", 984, "p", 1),
    ("pFlailerBigRaceExtension", 988, "p", 1),
    ("pFlailerBigRaceTotal", 992, "p", 1), ("pFlailerLapCounter", 996, "p", 1),
    ("pFlailerLapTime", 1000, "p", 1), ("pFlailerBestLap", 1004, "p", 1),
    ("pFlailerRunningSplitTime", 1008, "p", 1),
    ("pFlailerCompSplitTime", 1012, "p", 1),
    ("pFlailerTireForce", 1016, "p", 4), ("pFlailerSpeedString", 1032, "p", 1),
    ("pFlailerSpeedString2", 1036, "p", 1),
    ("pFlailerGearString", 1040, "p", 1), ("pFlailerShiftUp", 1044, "p", 1),
    ("pFlailerShiftDown", 1048, "p", 1), ("pFlailerCFPSString", 1052, "p", 1),
    ("pFlailerGFPSString", 1056, "p", 1), ("pFlailerPosString", 1060, "p", 1),
    ("pFlailerDistString", 1064, "p", 1),
    ("pFlailerDebugBacking", 1068, "p", 1),
    ("pFlailerPursuitStar", 1072, "p", 1),
    ("pFlailerPursuitLevel", 1076, "p", 4), ("pFlailerPursuitX", 1092, "p", 3),
    ("PrevPursuitLevel", 1104, "w", 1), ("PrevTicketLevel", 1108, "w", 1),
    ("pFlailerTracker", 1112, "p", 7), ("pFlailerReticle", 1140, "p", 1),
    ("pFlailerEventTitle", 1144, "p", 1), ("pFlailerEventScore", 1148, "p", 1),
    ("pFlailerScoreTitle", 1152, "p", 1), ("pFlailerScoreTotal", 1156, "p", 1),
    ("pFlailerMusicArtist", 1160, "p", 1), ("pFlailerMusicTitle", 1164, "p", 1),
    ("pFlailerMusicLabel", 1168, "p", 1), ("pFlailerMusicEA", 1172, "p", 1),
    ("pFlailerRadarLight", 1176, "p", 12),
    ("pFlailerNitrousLight", 1224, "p", 10),
    ("pFlailerDamageLight", 1264, "p", 5),
    ("pFlailerBeTheCopTickets", 1284, "p", 4),
    ("_flailers1300", 1300, "b", 68), ("pFlailerBeTheCopTime", 1368, "p", 1),
    ("pFlailerBeTheCopHelicopter", 1372, "p", 3),
    ("pFlailerBeTheCopRoadblock", 1384, "p", 3), ("_new1396", 1396, "b", 8),
    ("pRadarBeep", 1404, "p", 1), ("RadarTimer", 1408, "w", 1),
    ("strEventTitle", 1412, "b", 32), ("strEventScore", 1444, "b", 32),
    ("strPrevScore", 1476, "b", 32), ("HangTime", 1508, "w", 1),
    ("DriftTime", 1512, "w", 1), ("PosChangeTime", 1516, "w", 1),
    ("PositionFlag", 1520, "w", 1), ("TotalScore", 1524, "w", 1),
    ("pTrackMap", 1528, "p", 1), ("TimeTrackMapModeChanged", 1532, "w", 1),
    ("pRouteDisplayer", 1536, "p", 1), ("pHudAnimations", 1540, "p", 20),
    ("LastRacePosition", 1620, "w", 1), ("LastSpeed", 1624, "w", 1),
    ("LastSpeedSet", 1628, "w", 1), ("TopSpeed", 1632, "w", 1),
    ("bNewTopSpeed", 1636, "w", 1), ("bCheckTopSpeed", 1640, "w", 1),
    ("SpeedFactor", 1644, "w", 1), ("fBeginLapNumberExact", 1648, "w", 1),
    ("myCD", 1652, "p", 1), ("_pad1656", 1656, "b", 8),
    ("EyeVerts", 1664, "w", 12), ("BankVerts", 1712, "w", 12),
    ("FOVtable", 1760, "p", 1), ("pJumpCamRoute", 1764, "p", 1),
    ("mAutoReplayTimeMarker", 2472, "w", 1),
    ("mLastAutoReplayTime", 2476, "w", 1), ("mAutoReplayState", 2480, "w", 1),
    ("PursuitObjectPos", 2484, "w", 14), ("New2540", 2540, "w", 1),
    ("bCollisionDetected", 2544, "w", 1), ("bSmokeableHit", 2548, "w", 1),
    ("BestLapRecordData", 2552, "w", 1), ("BestTotalRecordData", 2556, "w", 1),
    ("lastCar", 2616, "p", 1), ("LastCrossingTime", 2620, "w", 1),
    ("bSegmentCollisionDetected", 2624, "w", 1),
    ("baPlaceReached", 2628, "w", 8), ("bShownMusicTitle", 2660, "w", 1),
    ("CurrentJukeboxIndex", 2664, "w", 1), ("bRadarOffset", 2668, "w", 1),
    ("fInitialRadarY", 2672, "w", 1), ("bPursuitOffset", 2676, "w", 1),
    ("fInitialPursuitY", 2680, "w", 1), ("PursuitOffsetState", 2684, "w", 1),
    ("numCleanLaps", 2688, "w", 1), ("HasHeardRaceOverSpeech", 2692, "w", 1),
    ("New2696", 2696, "w", 1), ("pFlailerScore", 2700, "p", 4),
    ("fScoreTop", 2716, "w", 4), ("tScoreAnimation", 2732, "w", 1),
    ("New2736", 2736, "w", 1), ("_pad2740", 2740, "b", 12),
]

NIS_FIELDS = [
    ("LastDateTimeUpdate", 0, "w", 1), ("ScreenHash", 4, "w", 1),
    ("State", 8, "w", 1), ("ScaleAnimationTrack", 12, "p", 1),
    ("AlphaAnimationTrack", 16, "p", 1), ("BustedDisplay", 20, "p", 1),
    ("New24", 24, "w", 1), ("sx", 28, "w", 1), ("sy", 32, "w", 1),
    ("ScaleX", 36, "w", 1), ("ScaleY", 40, "w", 1),
    ("SavedScaleX", 44, "w", 1), ("SavedScaleY", 48, "w", 1),
    ("SavedTopLeftY", 52, "w", 1),
]
NIS_BYTES = 56
TOPO_BYTES = 704


def field_bytes(kind, n):
    return n if kind == "b" else 4 * n


def check_tables():
    """The two tables tile their structs, the Player's round the topology
    and the overlay."""
    spans = sorted((off, off + field_bytes(k, n))
                   for _, off, k, n in PLAYER_FIELDS)
    spans += [(P_TOPO, P_TOPO + TOPO_BYTES), (P_NIS, P_NIS + NIS_BYTES)]
    spans.sort()
    at = 0
    for a, b in spans:
        assert a == at, "the Player's table has a gap or overlap at %d" % at
        at = b
    assert at == PLAYER_BYTES, "the Player's table ends at %d" % at
    at = 0
    for _, off, k, n in NIS_FIELDS:
        assert off == at, "the overlay's table breaks at %d" % at
        at = off + field_bytes(k, n)
    assert at == NIS_BYTES


def arm_layout_check():
    """Every field the transcript names, at its retail offset, in an ARM
    compile of player.h. Returns 0 when it holds or devkitARM is not
    there."""
    if not ARM_GCC.exists():
        print("devkitARM not found; the ARM layout check is skipped")
        return 0
    lines = ["#include <stddef.h>", "#include \"player.h\""]
    for name, off, _, _ in PLAYER_FIELDS:
        lines.append("_Static_assert(offsetof(struct Player, %s) == %d, "
                     "\"%s\");" % (name, off, name))
    for name, off, _, _ in NIS_FIELDS:
        lines.append("_Static_assert(offsetof(NISOverlayManager, %s) == %d, "
                     "\"%s\");" % (name, off, name))
    lines += [
        "_Static_assert(offsetof(struct Player, Topology) == %d, \"Topology\");"
        % P_TOPO,
        "_Static_assert(sizeof(TopologyCoordinate) == %d, \"topo size\");"
        % TOPO_BYTES,
        "_Static_assert(offsetof(struct Player, mFlailerNIS) == %d, \"nis\");"
        % P_NIS,
        "_Static_assert(sizeof(NISOverlayManager) == %d, \"nis size\");"
        % NIS_BYTES,
        "_Static_assert(sizeof(struct Player) == %d, \"size\");"
        % PLAYER_BYTES,
    ]
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "player_layout.c"
        src.write_text(NL.join(lines) + NL)
        r = subprocess.run(
            [str(ARM_GCC), "-fsyntax-only", "-march=armv6k", "-mtune=mpcore",
             "-mfloat-abi=hard", "-std=c11", "-I", str(ROOT / "3DS Files/source"),
             "-I", str(CTRU_INCLUDE), str(src)],
            capture_output=True, text=True)
    if r.returncode != 0:
        print("the ARM layout check failed:")
        print((r.stderr or r.stdout)[:3000])
        return 1
    print("ARM layout: %d Player fields and %d overlay fields at retail's "
          "offsets" % (len(PLAYER_FIELDS), len(NIS_FIELDS)))
    return 0


def fx(w):
    """A float's bits, with every NaN the one "nan"."""
    w &= M32
    if (w & 0x7f800000) == 0x7f800000 and (w & 0x7fffff):
        return "nan"
    return "%08x" % w


def obj_at(i):
    return APOOL + OBJ_BYTES * i


def player_at(i):
    return PLAYERS + PLAYER_STRIDE * i


def car_at(i):
    return CARS + CAR_STRIDE * i


def driver_at(i):
    return DRIVERS + 0x40 * i


def hud_at(i):
    return HUDS + 16 * i


def score_at(i):
    return SCORE_OBJS + 0x20 * i


# ============================================================ the scenarios

TIMERS = (0, 1, 2, 3999, 4000, 4001, 12345, 16777216, 16777217, 33554435,
          99999999, 0x7fffffff, -1, -4000, -16777217, -0x80000000)


def rbits(rnd):
    k = rnd.random()
    if k < 0.1:
        return rnd.choice((0x00000000, 0x80000000, 0x3f800000, 0xc0800000,
                           0x7f7fffff, 0xff7fffff, 0x00800000, 0x3f800001))
    return f_to_bits(rnd.uniform(-600.0, 600.0))


def rfill(rnd):
    """The byte a Player is filled with before it is built: mostly the
    pattern, and every bit set or clear for the fields the constructor
    masks."""
    return rnd.choice(("a5", "a5", "ff", "5a", "00"))


def s_flags(rnd):
    """The views and the HUD's hashes under every mix of the player cars,
    the two demo modes and Be A Cop, for one player and for two."""
    out = []
    for cars in (1, 2, 0, 3):
        for aidemo in (0, 1):
            for replay in (0, 1):
                for beacop in (0, 1, 7):
                    out += ["S cars %d" % cars, "S aidemo %d" % aidemo,
                            "S replay %d" % replay, "S beacop %d" % beacop,
                            "N 0 0 0", "N 1 1 1", "Z 1 2", "Z 0 3",
                            "N 1 1 1", "Z 1 2"]
    out += ["S cars 2", "S aidemo 0", "S replay 0", "S beacop 0",
            "N 0 1 1", "Z 0 2", "N 1 0 0", "N 0 3 1", "Z 0 2", "Z 1 3",
            "N 1 2 0", "N 0 0 0", "Z 1 3", "Z 0 3"]
    return out


def s_settings(rnd):
    """ResetToDefaults under SkipFE with each POV byte, and the settings
    the constructor copies by number."""
    out = []
    for skip in (0, 1, 2):
        for pov in (1, 0, 2, 3, 127, 128, 255):
            out += ["S skip %d" % skip, "S skippov %d" % pov, "R 0", "R 1"]
    for _ in range(6):
        for s in (0, 1):
            for _ in range(8):
                out.append("G %d %d %d" % (s, rnd.randrange(48),
                                           rnd.randrange(256)))
            for off in (8, 12, 16, 32, 36, 40, 44):
                if rnd.random() < 0.5:
                    out.append("H %d %d %08x" % (s, off,
                                                 rnd.getrandbits(32)))
        n0 = rnd.choice((0, 1))
        out += ["N 0 %d %d" % (rnd.randrange(4), n0),
                "N 1 %d %d" % (rnd.randrange(4), 1 - n0), "Z 0 2", "Z 1 2"]
        out += ["S skip %d" % rnd.choice((0, 1)), "R %d" % rnd.choice((0, 1)),
                "N 0 0 0", "N 1 1 1", "Z 1 2", "Z 0 2"]
    return out


def s_dtor(rnd):
    """The destructor over every mix of what the player owns."""
    out = []
    for trial in range(40):
        both = trial % 3 == 2
        out.append("N 0 0 0 %s" % rfill(rnd))
        if both:
            out.append("N 1 1 1 %s" % rfill(rnd))
        for f in ("route", "jump", "zs", "line"):
            if rnd.random() < 0.5:
                out.append("F 0 %s 1" % f)
        for f in ("cd", "fov", "avg", "mgr"):
            if rnd.random() < 0.25:
                out.append("F 0 %s 0" % f)
        for k in range(NHUD):
            if rnd.random() < 0.3:
                out.append("A 0 %d 1" % k)
        if rnd.random() < 0.3:
            out.append("F 0 num %d" % rnd.choice((0, 1)))
        # The four words the destructor zeroes, which the constructor
        # zeroed too.
        for f in ("lastspeed", "pursuit", "ticket", "speedset"):
            if rnd.random() < 0.6:
                out.append("F 0 %s %08x" % (f, rnd.getrandbits(32)))
        out.append("J 0")
        if rnd.random() < 0.5:
            out += ["F 0 jump 1", "J 0"]
        if both and rnd.random() < 0.5:
            out += ["Z 1 %d" % rnd.choice((2, 3)),
                    "Z 0 %d" % rnd.choice((2, 3))]
        else:
            out.append("Z 0 %d" % rnd.choice((2, 3)))
            if both:
                out.append("Z 1 %d" % rnd.choice((2, 3)))
    return out


def s_race(rnd):
    """InitForRace and CleanupAfterRace, over each control mode, the
    settings' style and transmission, a NIS playing or not and the
    overlay's screen and BUSTED object."""
    out = ["N 0 0 0 %s" % rfill(rnd), "N 1 1 1 %s" % rfill(rnd)]
    for trial in range(60):
        i = rnd.randrange(2)
        k = rnd.randrange(NCAR)
        out += ["C %d %d" % (k, rnd.choice((0, 1, 1, 2, 3, -1))),
                "F %d style %d" % (i, rnd.choice((0, 1, 2, -1, 127, -128))),
                "F %d trans %d" % (i, rnd.choice((0, 1, 2, -1)))]
        out.append("I %d %d" % (i, k))
        if rnd.random() < 0.3:
            out.append("P %d" % i)
        out.append("W %d %d" % (i, rnd.choice((0, 0, 1, -1, 2))))
        if rnd.random() < 0.5:
            out.append("F %d busted %d" % (i, rnd.choice((0, 1))))
        if rnd.random() < 0.4:
            out.append("F %d ohash %08x" % (i, rnd.choice(
                (0, 0x3ea89b7c, 0xd4d25ee7, rnd.getrandbits(32)))))
        if rnd.random() < 0.3:
            out.append("F %d dc %08x" % (i, rnd.getrandbits(32)))
        if rnd.random() < 0.3:
            out.append("Q %08x %08x %08x" % (rbits(rnd), rbits(rnd),
                                             rbits(rnd)))
        out.append("U %d" % i)
    out += ["Z 0 2", "Z 1 2"]
    return out


def s_score(rnd):
    """The score display's four objects, each there or not, with their
    tops; the overlay's scale and top; WorldTimer's crossing time; the
    joystick type."""
    out = []
    for mask in range(16):
        out.append("O %d" % mask)
        for k in range(4):
            out.append("T %d %08x" % (k, rbits(rnd)))
        out += ["Q %08x %08x %08x" % (rbits(rnd), rbits(rnd), rbits(rnd)),
                "S timer %d" % TIMERS[mask], "S joy %d" % rnd.randrange(-5, 200),
                "N 0 %d %d %s" % (mask % 4, mask & 1, rfill(rnd)), "Z 0 2"]
    for t in TIMERS:
        out += ["S timer %d" % t, "N 1 1 1", "Z 1 3"]
    for _ in range(20):
        out += ["S timer %d" % rnd.randrange(-2 ** 31, 2 ** 31),
                "N 0 0 0", "Z 0 2"]
    return out


def s_walk(rnd, n):
    out = []
    built = [False, False]
    car = [None, None]
    mgr = [False, False]
    for _ in range(n):
        r = rnd.random()
        i = rnd.randrange(2)
        if r < 0.10:
            if built[i]:
                continue
            out.append("N %d %d %d %s" % (i, rnd.randrange(4),
                                          rnd.choice((0, 1)), rfill(rnd)))
            built[i], car[i], mgr[i] = True, None, True
        elif r < 0.15:
            if not built[i]:
                continue
            out.append("Z %d %d" % (i, rnd.choice((2, 3))))
            built[i] = False
        elif r < 0.27:
            if not built[i]:
                continue
            k = rnd.randrange(NCAR)
            out.append("I %d %d" % (i, k))
            car[i] = k
        elif r < 0.36:
            if not (built[i] and mgr[i] and car[i] is not None):
                continue
            out.append("U %d" % i)
            car[i] = None
        elif r < 0.40:
            if built[i]:
                out.append(rnd.choice(("P %d", "J %d")) % i)
        elif r < 0.44:
            out.append("R %d" % rnd.randrange(2))
        elif r < 0.52:
            out.append(rnd.choice((
                "S cars %d" % rnd.choice((1, 2, 2, 0)),
                "S aidemo %d" % rnd.choice((0, 0, 1)),
                "S replay %d" % rnd.choice((0, 0, 1)),
                "S beacop %d" % rnd.choice((0, 0, 1)),
                "S skip %d" % rnd.choice((0, 1)),
                "S skippov %d" % rnd.randrange(256),
                "S timer %d" % rnd.choice(TIMERS),
                "S joy %d" % rnd.randrange(100))))
        elif r < 0.58:
            s = rnd.randrange(2)
            if rnd.random() < 0.5:
                out.append("G %d %d %d" % (s, rnd.randrange(48),
                                           rnd.randrange(256)))
            else:
                out.append("H %d %d %08x" % (s, rnd.choice((8, 12, 16, 32,
                                                            36, 40, 44)),
                                             rnd.getrandbits(32)))
        elif r < 0.62:
            out.append("C %d %d" % (rnd.randrange(NCAR),
                                    rnd.choice((0, 1, 1, 2))))
        elif r < 0.66:
            out.append(rnd.choice((
                "O %d" % rnd.randrange(16),
                "T %d %08x" % (rnd.randrange(4), rbits(rnd)),
                "Q %08x %08x %08x" % (rbits(rnd), rbits(rnd), rbits(rnd)))))
        elif r < 0.86:
            if not built[i]:
                continue
            f = rnd.choice(("route", "jump", "zs", "line", "busted", "ohash",
                            "style", "trans", "num", "dc", "hud", "play",
                            "play", "cd", "fov", "avg", "mgr", "car", "words"))
            if f in ("route", "jump", "zs", "line", "busted"):
                out.append("F %d %s %d" % (i, f, rnd.choice((0, 1))))
            elif f == "words":
                out.append("F %d %s %08x" % (i, rnd.choice((
                    "lastspeed", "pursuit", "ticket", "speedset")),
                    rnd.getrandbits(32)))
            elif f == "ohash":
                out.append("F %d ohash %08x" % (i, rnd.choice(
                    (0, 0x3ea89b7c, rnd.getrandbits(32)))))
            elif f in ("style", "trans"):
                out.append("F %d %s %d" % (i, f, rnd.randrange(-128, 128)))
            elif f == "num":
                out.append("F %d num %d" % (i, rnd.choice((0, 1))))
            elif f == "dc":
                out.append("F %d dc %08x" % (i, rnd.getrandbits(32)))
            elif f == "hud":
                out.append("A %d %d %d" % (i, rnd.randrange(NHUD),
                                           rnd.choice((0, 1))))
            elif f == "play":
                out.append("W %d %d" % (i, rnd.choice((0, 1, 5))))
            elif f == "car":
                k = rnd.randrange(NCAR)
                out.append("F %d car %d" % (i, k))
                car[i] = k
            elif rnd.random() < 0.2:
                out.append("F %d %s 0" % (i, f))
                if f == "mgr":
                    mgr[i] = False
    for i in (0, 1):
        if built[i]:
            out.append("Z %d 2" % i)
    return out


def script():
    rnd = random.Random(0x91a7e2a1)
    sc = [s_flags(rnd), s_settings(rnd), s_dtor(rnd), s_race(rnd),
          s_score(rnd)]
    for n in (300, 800, 1500):
        sc.append(s_walk(rnd, n))
    return sc


def encode(scenarios):
    lines = []
    for i, s in enumerate(scenarios):
        lines.append("B %d" % i)
        lines += s
    return NL.join(lines) + NL


# ================================================================ the model


class Model(object):
    def __init__(self):
        self.out = []
        self.e = retail_model.RetailEmu(ieee=True)
        e = self.e
        self.nstub = 0
        for a, fn in ((B_MALLOC, self.s_malloc), (B_DELETE, self.s_free),
                      (B_VEC_DELETE, self.s_free),
                      (B_SPRINTF, self.s_sprintf),
                      (TOPO_CTOR, self.s_topo), (TOPO_DTOR, self.s_topodel),
                      (JOY_TYPE, self.s_joytype), (NIS_CTOR, self.s_nisnew),
                      (NIS_DTOR, self.logger("nisdel", flag=True)),
                      (NIS_STOP, self.logger("nisstop")),
                      (AVG_CTOR, self.s_avg),
                      (AVG_DTOR, self.logger("avgdel", flag=True)),
                      (GET_SAMPLE, self.s_sample),
                      (FIND_FLAILER, self.s_find),
                      (GET_TOP_LEFT, self.s_topleft),
                      (GET_SCALE, self.s_getscale),
                      (GET_TOP_Y, self.s_gettop), (SET_VIS, self.s_vis),
                      (SET_SCALE_X, self.float_logger("scalex")),
                      (SET_SCALE_Y, self.float_logger("scaley")),
                      (SET_TOP_Y, self.float_logger("settop")),
                      (SET_MANUAL, self.s_manual),
                      (RADIAL_OFF, self.s_bluroff),
                      (RM_CAMS, self.logger("rmcams")),
                      (SET_INPUT, self.int_logger("inputmode")),
                      (RAND_NIS, self.int_logger("randnis")),
                      (RESET_FLAILER, self.logger("resetflailer")),
                      (SET_HUD, self.int_logger("hudfeat")),
                      (ROUTE_DTOR, self.logger("routedel", flag=True)),
                      (LINE_DTOR, self.logger("linedel", flag=True)),
                      (HUD_DTOR, self.logger("huddel", flag=True))):
            e.stub(a, fn)
        # AutoPilotOff is a bare return, and runs.
        assert e.u32(AUTO_PILOT_OFF) == 0x03e00008
        # The zone sample's vtable: the destructor at 12, this-delta 0.
        e.put32(ZONE_SAMPLE + SAMPLE_VTBL, ZS_VTBL)
        e.put32(ZS_VTBL + 8, 0)
        e.put32(ZS_VTBL + 12, self.fake(self.logger("sampledel", flag=True)))

        self.names = {0: "null", ROUTE: "rt", JUMP_ROUTE: "jr",
                      ZONE_SAMPLE: "zs", LINE: "ln", BUSTED: "bd",
                      RADAR_BEEP: "rb"}
        for i in range(NOBJ):
            self.names[obj_at(i)] = "a%d" % i
        for i in range(NPLAYER):
            self.names[player_at(i)] = "p%d" % i
            self.names[player_at(i) + P_TOPO] = "p%d.topo" % i
            self.names[player_at(i) + P_NIS] = "p%d.nis" % i
        for i in range(NCAR):
            self.names[car_at(i)] = "k%d" % i
            self.names[driver_at(i)] = "d%d" % i
        for i in range(NHUD):
            self.names[hud_at(i)] = "h%d" % i
        for i in range(4):
            self.names[score_at(i)] = "o%d" % i

    def fake(self, fn):
        a = STUBS + 8 * self.nstub
        self.nstub += 1
        self.e.stub(a, fn)
        return a

    def emit(self, s):
        self.out.append(s)

    def name(self, a):
        return self.names.get(a & M32, "?%08x" % (a & M32))

    def arg(self, i):
        return self.e.reg[(4, 5, 6, 7, 8, 9, 10, 11)[i]] & M32

    def w(self, a):
        return self.e.u32(a)

    def fill(self, a, n, byte=PATTERN):
        self.e.write(a, bytes([byte]) * n)

    def cstr(self, a):
        b = bytearray()
        while self.e.mem[a]:
            b.append(self.e.mem[a])
            a += 1
        return b.decode("latin-1")

    def index_of(self, a):
        if APOOL <= a < MISC and (a - APOOL) % OBJ_BYTES == 0:
            return (a - APOOL) // OBJ_BYTES
        return None

    # ---- the stubs -------------------------------------------------------

    def logger(self, what, flag=False):
        def fn(e):
            if flag:
                self.emit("  %s %s flag %d" % (what, self.name(self.arg(0)),
                                               s32(self.arg(1))))
            else:
                self.emit("  %s %s" % (what, self.name(self.arg(0))))
        return fn

    def int_logger(self, what):
        def fn(e):
            self.emit("  %s %s %d" % (what, self.name(self.arg(0)),
                                      s32(self.arg(1))))
        return fn

    def float_logger(self, what):
        def fn(e):
            self.emit("  %s %s %s" % (what, self.name(self.arg(0)),
                                      fx(e.fpr[12])))
        return fn

    def s_malloc(self, e):
        name = self.cstr(self.arg(1))
        if self.nobj >= NOBJ:
            raise SystemExit("arena full")
        i = self.nobj
        self.nobj += 1
        a = obj_at(i)
        self.fill(a, OBJ_BYTES)
        self.live[i] = True
        self.track[i] = name == "NISCubicAnimation"
        self.emit("  malloc %d %s %d %d -> %s"
                  % (s32(self.arg(0)), name, s32(self.arg(2)),
                     s32(self.arg(3)), self.name(a)))
        return a

    def s_free(self, e):
        a = self.arg(0)
        self.emit("  free %s" % self.name(a))
        i = self.index_of(a)
        if i is not None:
            self.live[i] = False

    def s_sprintf(self, e):
        fmt = self.cstr(self.arg(1))
        args = [self.arg(k) for k in range(2, 8)]
        out, i = [], 0
        while i < len(fmt):
            c = fmt[i]
            if c == "%" and i + 1 < len(fmt):
                d = fmt[i + 1]
                if d == "d":
                    out.append(str(s32(args.pop(0))))
                elif d == "s":
                    out.append(self.cstr(args.pop(0)))
                elif d == "%":
                    out.append("%")
                else:
                    raise SystemExit("bSPrintf format %r" % fmt)
                i += 2
                continue
            out.append(c)
            i += 1
        s = "".join(out).encode("latin-1") + b"\0"
        e.write(self.arg(0), s)
        return len(s) - 1

    def s_topo(self, e):
        self.emit("  topo %s" % self.name(self.arg(0)))
        return self.arg(0)

    def s_topodel(self, e):
        self.emit("  topodel %s flag %d" % (self.name(self.arg(0)),
                                            s32(self.arg(1))))

    def s_joytype(self, e):
        port = s32(self.arg(0))
        r = self.joybase + port
        self.emit("  joytype %d -> %d" % (port, r))
        return r

    def s_nisnew(self, e):
        m = self.arg(0)
        self.emit("  nisnew %s %s %d" % (self.name(m), self.cstr(self.arg(1)),
                                         s32(self.arg(2))))
        e.put32(m + NIS_PLAYING, 0)
        return m

    def s_avg(self, e):
        self.emit("  avg %s %d" % (self.name(self.arg(0)), s32(self.arg(1))))
        return self.arg(0)

    def s_sample(self, e):
        self.emit("  sample %s -> rb" % self.cstr(self.arg(0)))
        return RADAR_BEEP

    def s_find(self, e):
        screen, obj, typ = self.arg(0), self.arg(1), s32(self.arg(2))
        r = 0
        for k in range(4):
            if obj == SCORE_HASH[k] and (self.scoremask >> k) & 1:
                r = score_at(k)
        self.emit("  find %08x %08x %d -> %s" % (screen, obj, typ,
                                                 self.name(r)))
        return r

    def s_topleft(self, e):
        o, x, y = self.arg(0), self.arg(1), self.arg(2)
        if o == 0:
            # Retail would read the object; the port reads 0 for none.
            e.put32(x, 0)
            e.put32(y, 0)
            return
        self.emit("  topleft %s" % self.name(o))
        e.put32(x, 0x3f800000)
        top = 0
        for k in range(4):
            if o == score_at(k):
                top = self.scoretop[k]
        e.put32(y, top)

    def s_getscale(self, e):
        self.emit("  getscale %08x %08x" % (self.arg(0), self.arg(1)))
        e.put32(self.arg(2), self.nis_sx)
        e.put32(self.arg(3), self.nis_sy)

    def s_gettop(self, e):
        self.emit("  gettop %08x %08x" % (self.arg(0), self.arg(1)))
        e.fpr[0] = self.nis_top

    def s_vis(self, e):
        self.emit("  vis %08x %d" % (self.arg(0), s32(self.arg(1))))

    def s_manual(self, e):
        self.emit("  manual %s %d" % (self.name(self.arg(0)),
                                      s32(self.arg(1))))

    def s_bluroff(self, e):
        self.emit("  bluroff %d" % s32(self.arg(0)))

    # ---- the state -------------------------------------------------------

    def reset(self):
        e = self.e
        self.nobj = 0
        self.live = [False] * NOBJ
        self.track = [False] * NOBJ
        self.shown = [False] * NPLAYER
        for i in range(NPLAYER):
            self.fill(player_at(i), PLAYER_STRIDE)
        e.put32(G_NUM, 0)
        for k in range(2):
            e.put32(G_BY_INDEX + 4 * k, 0)
            e.put32(G_BY_NUMBER + 4 * k, 0)
        e.put32(G_GLARE, 0)
        e.put32(G_TIMER, 0)
        e.put32(G_SKIPFE, 0)
        e.mem[G_SKIPPOV] = 1
        e.put32(RP_CARS, 1)
        e.put32(RP_AIDEMO, 0)
        e.put32(RP_REPLAY, 0)
        e.put32(RP_BEACOP, 0)
        self.fill(RP_SETTINGS, 96)
        self.fill(CARS, CAR_STRIDE * NCAR)
        for k in range(NCAR):
            c = car_at(k)
            e.put32(c + C_PLAYER, 0)
            e.put32(c + C_MODE, 0)
            e.put32(c + C_DRIVER, driver_at(k))
            e.put32(c + C_DRIVER_MODE, 0)
        self.joybase = 40
        self.scoremask = 15
        self.scoretop = [f_to_bits(10.0 * (k + 1)) for k in range(4)]
        self.nis_sx = 0x3f000000
        self.nis_sy = 0x40000000
        self.nis_top = 0x41200000

    def set_global(self, f, v):
        e = self.e
        if f == "cars":
            e.put32(RP_CARS, v)
        elif f == "aidemo":
            e.put32(RP_AIDEMO, v)
        elif f == "replay":
            e.put32(RP_REPLAY, v)
        elif f == "beacop":
            e.put32(RP_BEACOP, v)
        elif f == "skip":
            e.put32(G_SKIPFE, v)
        elif f == "skippov":
            e.mem[G_SKIPPOV] = v & 0xff
        elif f == "timer":
            e.put32(G_TIMER, v)
        elif f == "joy":
            self.joybase = v
        else:
            raise SystemExit("bad global %s" % f)

    def set_field(self, i, f, t):
        e = self.e
        p = player_at(i)
        v = t[0]
        ptrs = {"route": (P_ROUTE, ROUTE), "jump": (P_JUMP, JUMP_ROUTE),
                "zs": (P_ZONE_SAMPLE, ZONE_SAMPLE), "line": (P_LINE, LINE),
                "busted": (P_NIS + O_BUSTED, BUSTED)}
        nulls = {"mgr": P_MGR, "cd": P_CD, "fov": P_FOV, "avg": P_AVG}
        if f in ptrs:
            off, a = ptrs[f]
            e.put32(p + off, a if int(v, 0) else 0)
        elif f in nulls:
            e.put32(p + nulls[f], 0)
        elif f == "car":
            k = int(v, 0)
            e.put32(p + P_CAR, 0 if k < 0 else car_at(k))
        elif f == "ohash":
            e.put32(p + P_NIS + O_SCREEN, int(v, 16))
        elif f == "style":
            e.mem[p + P_SETTINGS + 2] = int(v, 0) & 0xff
        elif f == "trans":
            e.mem[p + P_SETTINGS + 3] = int(v, 0) & 0xff
        elif f == "num":
            e.put32(p + P_NUMBER, int(v, 0))
        elif f == "dc":
            e.put32(p + P_DC, int(v, 16))
        elif f in P_WORDS:
            e.put32(p + P_WORDS[f], int(v, 16))
        else:
            raise SystemExit("bad field %s" % f)

    # ---- the dumps -------------------------------------------------------

    def dump_field(self, who, base, field):
        name, off, kind, n = field
        a = base + off
        s = "  %s %s" % (who, name)
        if kind == "b":
            s += " " + bytes(self.e.mem[a:a + n]).hex()
        elif kind == "w":
            s += "".join(" %08x" % self.w(a + 4 * k) for k in range(n))
        else:
            s += "".join(" " + self.name(self.w(a + 4 * k))
                         for k in range(n))
        self.emit(s)

    def dump_globals(self):
        w = self.w
        self.emit("  g num %d idx %s %s byn %s %s glare %d"
                  % (s32(w(G_NUM)), self.name(w(G_BY_INDEX)),
                     self.name(w(G_BY_INDEX + 4)), self.name(w(G_BY_NUMBER)),
                     self.name(w(G_BY_NUMBER + 4)), s32(w(G_GLARE))))

    def dump(self):
        mem = self.e.mem
        self.dump_globals()
        for k in range(NCAR):
            c = car_at(k)
            self.emit("  k%d player %s mode %08x"
                      % (k, self.name(self.w(c + C_PLAYER)),
                         self.w(c + C_DRIVER_MODE)))
        for k in range(2):
            a = RP_SETTINGS + 48 * k
            self.emit("  rs%d %s" % (k, bytes(mem[a:a + 48]).hex()))
        for i in range(NPLAYER):
            if not self.shown[i]:
                continue
            p = player_at(i)
            for f in PLAYER_FIELDS:
                self.dump_field("p%d" % i, p, f)
            for f in NIS_FIELDS:
                self.dump_field("p%d.nis" % i, p + P_NIS, f)
        for i in range(self.nobj):
            if self.live[i] and self.track[i]:
                a = obj_at(i)
                self.emit("  a%d track %s" % (i, bytes(mem[a:a + 48]).hex()))

    # ---- the ops ---------------------------------------------------------

    def op(self, t):
        e = self.e
        c = t[0]
        lim = dict(limit=200000)
        full = True
        if c == "S":
            self.set_global(t[1], int(t[2], 0))
            full = False
        elif c == "G":
            e.mem[RP_SETTINGS + 48 * int(t[1]) + int(t[2])] = int(t[3], 0) & 0xff
            full = False
        elif c == "H":
            e.put32(RP_SETTINGS + 48 * int(t[1]) + int(t[2]), int(t[3], 16))
            full = False
        elif c == "C":
            e.put32(car_at(int(t[1])) + C_MODE, int(t[2], 0))
            full = False
        elif c == "O":
            self.scoremask = int(t[1], 0)
            full = False
        elif c == "T":
            self.scoretop[int(t[1])] = int(t[2], 16)
            full = False
        elif c == "Q":
            self.nis_sx, self.nis_sy, self.nis_top = (int(x, 16)
                                                       for x in t[1:4])
            full = False
        elif c == "F":
            self.set_field(int(t[1]), t[2], t[3:])
            full = False
        elif c == "A":
            k = int(t[2])
            e.put32(player_at(int(t[1])) + P_HUDS + 4 * k,
                    hud_at(k) if int(t[3], 0) else 0)
            full = False
        elif c == "W":
            m = self.w(player_at(int(t[1])) + P_MGR)
            if self.index_of(m) is not None:
                e.put32(m + NIS_PLAYING, int(t[2], 0))
            full = False
        elif c == "N":
            i = int(t[1])
            self.fill(player_at(i), PLAYER_STRIDE,
                      int(t[4], 16) if len(t) > 4 else PATTERN)
            self.shown[i] = True
            r = e.call(CTOR, player_at(i), int(t[2], 0), int(t[3], 0), **lim)
            self.emit("  -> %s" % self.name(r))
        elif c == "Z":
            e.call(DTOR, player_at(int(t[1])), int(t[2], 0), **lim)
        elif c == "I":
            e.call(INIT_FOR_RACE, player_at(int(t[1])), car_at(int(t[2])),
                   **lim)
        elif c == "U":
            e.call(CLEANUP, player_at(int(t[1])), **lim)
        elif c == "P":
            e.call(PREDETERMINE, player_at(int(t[1])), **lim)
        elif c == "J":
            e.call(JUMP_CAM, player_at(int(t[1])), **lim)
        elif c == "R":
            e.call(RESET_DEFAULTS, RP_SETTINGS + 48 * int(t[1]), **lim)
        else:
            raise SystemExit("bad op %r" % (t,))
        if full:
            self.dump()
        else:
            self.dump_globals()

    def run(self, scenarios):
        for i, sc in enumerate(scenarios):
            self.emit("B %d" % i)
            self.reset()
            for ln in sc:
                self.emit("> " + ln[:40])
                self.op(ln.split())
        return self.out


# ================================================================ the build


def build_harness(tmp, name="player_test"):
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


# ============================================================ the mutations


def M(name, rel, before, after=None):
    return (name, rel, before, after)


NIH = "3DS Files/source/nisoverlay.h"

MUTATIONS = [
    # the constructor: the Timers and the members
    M("ctor_pov_timer", PIN, "    p->tIgnoreNextPovChange.PackedTime = 0;\n", ""),
    M("ctor_trouble_timer", PIN, "    p->LastTimeCarInTrouble.PackedTime = 0;\n", ""),
    M("ctor_prompt_timer", PIN, "    p->TimeToDisplayResetPrompt.PackedTime = 0;\n", ""),
    M("ctor_zone_sound_timer", PIN, "    p->tZoneSoundTimer.PackedTime = 0;\n", ""),
    M("ctor_no_topo", PIN, "    topology_init(&p->Topology);\n", ""),
    M("ctor_no_overlay", PIN, "    nisoverlay_init(&p->mFlailerNIS);\n", ""),
    M("ctor_score_anim", PIN, "    p->tScoreAnimation.PackedTime = 0x7fffffffu;",
      "    p->tScoreAnimation.PackedTime = 0x7ffffffeu;"),
    # the tables
    M("ctor_index_one", PIN, "    if (PlayerNumPlayers < 2)\n        PlayerPlayersByIndex",
      "    if (PlayerNumPlayers < 1)\n        PlayerPlayersByIndex"),
    M("ctor_no_count", PIN, "    PlayerNumPlayers++;\n", ""),
    M("ctor_no_by_number", PIN, "        PlayerPlayersByNumber[number] = p;\n", ""),
    M("ctor_settings_zero", PIN, "        p->PlayerSettings = RaceParametersPlayerSettings[number];",
      "        p->PlayerSettings = RaceParametersPlayerSettings[0];"),
    M("ctor_no_settings", PIN, "        p->PlayerSettings = RaceParametersPlayerSettings[number];\n", ""),
    M("ctor_other_kept", PIN, "    p->pOtherPlayer = NULL;\n", ""),
    M("ctor_no_link", PIN, "    if (PlayerNumPlayers == 2) {", "    if (0) {"),
    M("ctor_link_one", PIN,
      "        PlayerPlayersByIndex[1]->pOtherPlayer = PlayerPlayersByIndex[0];\n", ""),
    # the identity and the zones
    M("ctor_joy_port", PIN, "    p->JoyPort = port;", "    p->JoyPort = 0;"),
    M("ctor_joy_type", PIN, "    p->JoyType = GetJoystickType(port);",
      "    p->JoyType = GetJoystickType(0);"),
    M("ctor_number", PIN, "    p->PlayerNumber = number;", "    p->PlayerNumber = 0;"),
    M("ctor_input_mode", PIN, "    p->PlayerInputMode = 0;\n", ""),
    M("ctor_finished", PIN, "    p->TimeFinishedRacing = 0;\n", ""),
    M("ctor_finish_anim", PIN, "    p->FinishAnimationLength = 0;\n", ""),
    M("ctor_lap_record", PIN, "    p->BestLapRecordData = 0;\n", ""),
    M("ctor_total_record", PIN, "    p->BestTotalRecordData = 0;\n", ""),
    M("ctor_zone_current", PIN, "    p->nZoneCurrent = 0;\n", ""),
    M("ctor_zone_previous", PIN, "    p->nZonePrevious = 0;\n", ""),
    M("ctor_zone_sample", PIN, "    p->pZoneSample = NULL;\n", ""),
    M("ctor_muffle", PIN, "    p->bZoneMuffleSound = 0;\n", ""),
    M("ctor_muffle_volume", PIN, "    p->fZoneMuffleVolume = 0.0f;", "    p->fZoneMuffleVolume = 1.0f;"),
    M("ctor_freeze", PIN, "    p->fFreezeZoneDelayTimer = 0.0f;\n", ""),
    M("ctor_credits", PIN, "        p->nZoneCredits[i] = 0;\n", ""),
    M("ctor_credits_seven", PIN,
      "    for (i = 0; i < 8; i++) {\n        p->tAutoZoneTimers[i].PackedTime = 0;\n        p->nZoneCredits",
      "    for (i = 0; i < 7; i++) {\n        p->tAutoZoneTimers[i].PackedTime = 0;\n        p->nZoneCredits"),
    # the views
    M("view_cars_below", PIN, "    if (RaceParametersNumPlayerCars != 2) {\n        p->ViewID = 1;",
      "    if (RaceParametersNumPlayerCars < 2) {\n        p->ViewID = 1;"),
    M("view_single", PIN, "        p->ViewID = 1;\n        p->RearViewMirrorViewID = 3;",
      "        p->ViewID = 0;\n        p->RearViewMirrorViewID = 3;"),
    M("mirror_single", PIN, "        p->RearViewMirrorViewID = 3;", "        p->RearViewMirrorViewID = 0;"),
    M("view_split", PIN, "        p->ViewID = number == 0 ? 1 : 2;",
      "        p->ViewID = number == 1 ? 1 : 2;"),
    M("mirror_split", PIN, "        p->RearViewMirrorViewID = 0;\n    }",
      "        p->RearViewMirrorViewID = 3;\n    }"),
    # the cameras and the hashes
    M("ctor_route_kept", PIN, "    p->pRoute = NULL;\n    p->pCameraMover = NULL;",
      "    p->pCameraMover = NULL;"),
    M("ctor_mover_kept", PIN, "    p->pCameraMover = NULL;\n    p->pSavedCameraMover = NULL;",
      "    p->pSavedCameraMover = NULL;"),
    M("ctor_saved2_kept", PIN, "    p->pSavedCameraMover2 = NULL;\n", ""),
    M("ctor_rvm_kept", PIN, "    p->pRVMCameraMover = NULL;\n", ""),
    M("ctor_demo_kept", PIN, "    p->pDemoCameraCoordinator = NULL;\n", ""),
    M("ctor_count_kept", PIN, "    p->pCountdownCameraCoordinator = NULL;\n", ""),
    M("ctor_nis_coord_kept", PIN, "    p->pNisCameraCoordinator = NULL;\n", ""),
    M("ctor_line_kept", PIN, "    p->pVisibleDrivingLine = NULL;\n    p->CurrentHudFeatures",
      "    p->CurrentHudFeatures"),
    M("ctor_features_kept", PIN, "    p->CurrentHudFeatures = 0;\n", ""),
    M("ctor_hud_hash_kept", PIN, "    p->HudScreenHash = 0;\n    p->NisOverlayHash = 0;\n",
      "    p->NisOverlayHash = 0;\n"),
    M("ctor_nis_hash_kept", PIN, "    p->HudScreenHash = 0;\n    p->NisOverlayHash = 0;\n",
      "    p->HudScreenHash = 0;\n"),
    M("hash_replay_only", PIN, "    if (!RaceParametersAIDemoMode && !RaceParametersReplayDemoMode) {",
      "    if (!RaceParametersReplayDemoMode) {"),
    M("hash_aidemo_only", PIN, "    if (!RaceParametersAIDemoMode && !RaceParametersReplayDemoMode) {",
      "    if (!RaceParametersAIDemoMode) {"),
    M("hash_cars_one", PIN, "        if (RaceParametersNumPlayerCars != 2) {\n            p->HudScreenHash",
      "        if (RaceParametersNumPlayerCars == 1) {\n            p->HudScreenHash"),
    M("hash_split_swapped", PIN, "        } else if (number == 0) {", "        } else if (number == 1) {"),
    M("hud_single", PIN, "#define PLAYER_HUD_SINGLE      0xf1f1f8e5u",
      "#define PLAYER_HUD_SINGLE      0xf1f1f8e6u"),
    M("nis_single", PIN, "#define PLAYER_NIS_SINGLE      0x3ea89b7cu",
      "#define PLAYER_NIS_SINGLE      0x3ea89b7du"),
    M("hud_split_top", PIN, "#define PLAYER_HUD_SPLIT_TOP   0xa8eb7af0u",
      "#define PLAYER_HUD_SPLIT_TOP   0xa8eb7af1u"),
    M("nis_split_top", PIN, "#define PLAYER_NIS_SPLIT_TOP   0xd4d25ee7u",
      "#define PLAYER_NIS_SPLIT_TOP   0xd4d25ee8u"),
    M("hud_split_bot", PIN, "#define PLAYER_HUD_SPLIT_BOT   0x6283be92u",
      "#define PLAYER_HUD_SPLIT_BOT   0x6283be93u"),
    M("nis_split_bot", PIN, "#define PLAYER_NIS_SPLIT_BOT   0xc17316c9u",
      "#define PLAYER_NIS_SPLIT_BOT   0xc17316cau"),
    M("nis_be_a_cop", PIN, "#define PLAYER_NIS_BE_A_COP    0x3ea89b7cu",
      "#define PLAYER_NIS_BE_A_COP    0x3ea89b7du"),
    M("beacop_ignored", PIN, "    if (RaceParametersBeACop)\n", "    if (0)\n"),
    M("beacop_one", PIN, "    if (RaceParametersBeACop)\n", "    if (RaceParametersBeACop == 1)\n"),
    M("beacop_hud", PIN, "        p->NisOverlayHash = PLAYER_NIS_BE_A_COP;",
      "        p->HudScreenHash = PLAYER_NIS_BE_A_COP;"),
    M("set_screen_hud", PIN, "    nisoverlay_set_screen(&p->mFlailerNIS, p->NisOverlayHash);",
      "    nisoverlay_set_screen(&p->mFlailerNIS, p->HudScreenHash);"),
    M("set_screen_before_beacop", PIN, [
        ("    if (RaceParametersBeACop)\n        p->NisOverlayHash = PLAYER_NIS_BE_A_COP;\n"
         "    nisoverlay_set_screen(&p->mFlailerNIS, p->NisOverlayHash);\n",
         "    nisoverlay_set_screen(&p->mFlailerNIS, p->NisOverlayHash);\n"
         "    if (RaceParametersBeACop)\n        p->NisOverlayHash = PLAYER_NIS_BE_A_COP;\n")]),
    # the flailer words
    M("speed_needle_kept", PIN, "    p->pFlailerSpeedNeedle = NULL;\n", ""),
    M("tach_gradient_kept", PIN, "    p->pFlailerTachGradient = NULL;\n", ""),
    M("shift_down_kept", PIN, "    p->pFlailerShiftDown = NULL;\n", ""),
    M("big_race2_written", PIN, "    // Not pFlailerBigRacePosition2 or pFlailerDebugBacking.\n",
      "    p->pFlailerBigRacePosition2 = NULL;\n"),
    M("debug_backing_written", PIN, "    // Not pFlailerBigRacePosition2 or pFlailerDebugBacking.\n",
      "    p->pFlailerDebugBacking = NULL;\n"),
    M("big_race_total_kept", PIN, "    p->pFlailerBigRaceTotal = NULL;\n", ""),
    M("comp_split_kept", PIN, "    p->pFlailerCompSplitTime = NULL;\n", ""),
    M("tire_three", PIN, "    for (i = 0; i < 4; i++)\n        p->pFlailerTireForce[i] = NULL;",
      "    for (i = 0; i < 3; i++)\n        p->pFlailerTireForce[i] = NULL;"),
    M("dist_string_kept", PIN, "    p->pFlailerDistString = NULL;\n", ""),
    M("pursuit_star_kept", PIN, "    p->pFlailerPursuitStar = NULL;\n", ""),
    M("pursuit_level_three", PIN, "    for (i = 0; i < 4; i++)\n        p->pFlailerPursuitLevel[i] = NULL;",
      "    for (i = 0; i < 3; i++)\n        p->pFlailerPursuitLevel[i] = NULL;"),
    M("pursuit_x_two", PIN, "    for (i = 0; i < 3; i++)\n        p->pFlailerPursuitX[i] = NULL;",
      "    for (i = 0; i < 2; i++)\n        p->pFlailerPursuitX[i] = NULL;"),
    M("event_title_kept", PIN, "    p->pFlailerEventTitle = NULL;\n", ""),
    M("music_ea_kept", PIN, "    p->pFlailerMusicEA = NULL;\n", ""),
    M("reticle_kept", PIN, "    p->pFlailerReticle = NULL;\n", ""),
    M("position_flag_kept", PIN, "    p->PositionFlag = 0;\n", ""),
    M("pos_change_kept", PIN, "    p->PosChangeTime = 0.0f;\n", ""),
    M("hang_time_kept", PIN, "    p->HangTime = 0.0f;\n", ""),
    M("drift_time_written", PIN, "    p->HangTime = 0.0f;\n",
      "    p->HangTime = 0.0f;\n    p->DriftTime = 0.0f;\n"),
    M("total_score_kept", PIN, "    p->TotalScore = 0;\n", ""),
    M("top_speed_kept", PIN, "    p->TopSpeed = 0;\n", ""),
    M("new_top_speed_kept", PIN, "    p->bNewTopSpeed = 0;\n", ""),
    M("begin_lap_kept", PIN, "    p->fBeginLapNumberExact = 0.0f;\n", ""),
    M("route_displayer_kept", PIN, "    p->pRouteDisplayer = NULL;\n", ""),
    M("my_car_kept", PIN, "    p->MyCar = NULL;\n    p->pTrackMap = NULL;", "    p->pTrackMap = NULL;"),
    M("track_map_kept", PIN, "    p->pTrackMap = NULL;\n", ""),
    M("track_map_time_kept", PIN, "    p->TimeTrackMapModeChanged = 0;\n", ""),
    # the NIS manager and the NIS numbers
    M("nis_name_number", PIN, "\"Player%d\", (int)(1 - number));", "\"Player%d\", (int)number);"),
    M("nis_size", PIN, "bMalloc(320, \"NisManager\", 0, 16);", "bMalloc(324, \"NisManager\", 0, 16);"),
    M("nis_name", PIN, "bMalloc(320, \"NisManager\", 0, 16);", "bMalloc(320, \"NISManager\", 0, 16);"),
    M("nis_pool", PIN, "bMalloc(320, \"NisManager\", 0, 16);", "bMalloc(320, \"NisManager\", 0, 0);"),
    M("nis_number", PIN, "gNewNisManagerFn(mem, name, number);", "gNewNisManagerFn(mem, name, 1 - number);"),
    M("arrest_index", PIN, "    p->ArrestNisIndex = -1;\n    p->NisFinishedCallback = NULL;",
      "    p->ArrestNisIndex = 0;\n    p->NisFinishedCallback = NULL;"),
    M("ticket_index", PIN, "    p->TicketNisIndex = -1;\n    for (i = 0; i < 32; i++) {",
      "    p->TicketNisIndex = 0;\n    for (i = 0; i < 32; i++) {"),
    M("callback_kept", PIN, "    p->NisFinishedCallback = NULL;\n", ""),
    M("callback_param_kept", PIN, "    p->NisFinishedCallbackParam = 0;\n", ""),
    M("nis_numbers_31", PIN, "    for (i = 0; i < 32; i++) {\n        p->TicketNisNumbers[i] = 0;",
      "    for (i = 0; i < 31; i++) {\n        p->TicketNisNumbers[i] = 0;"),
    M("ticket_numbers_kept", PIN, "        p->TicketNisNumbers[i] = 0;\n", ""),
    M("ticket_cameras_kept", PIN, "        p->TicketCameraNumbers[i] = 0;\n", ""),
    M("arrest_numbers_kept", PIN, "        p->ArrestNisNumbers[i] = 0;\n", ""),
    M("arrest_cameras_kept", PIN, "        p->ArrestCameraNumbers[i] = 0;\n", ""),
    M("glue_kept", PIN, "    p->nGlueCount = 0;\n", ""),
    # the Average, the jump cam's two and the HUD animators
    M("avg_size", PIN, "bMalloc((int)sizeof(Average), PLAYER_CPP, 520, 16);",
      "bMalloc(24, PLAYER_CPP, 520, 16);"),
    M("avg_line", PIN, "PLAYER_CPP, 520, 16);", "PLAYER_CPP, 521, 16);"),
    M("avg_slots", PIN, "average_init((Average *)mem, 10);", "average_init((Average *)mem, 9);"),
    M("max_speed_kept", PIN, "    p->fMaxSpeedRatio = 0.0f;\n", ""),
    M("huds_19", PIN, "    for (i = 19; i >= 0; i--)\n        p->pHudAnimations[i] = NULL;",
      "    for (i = 19; i >= 1; i--)\n        p->pHudAnimations[i] = NULL;"),
    M("last_race_position_kept", PIN, "    p->LastRacePosition = 0;\n", ""),
    M("collision_kept", PIN, "    p->bCollisionDetected = 0;\n", ""),
    M("new180_kept", PIN, "    p->New180 = 0.0f;\n", ""),
    M("cd_size", PIN, "bMalloc(164, PLAYER_CPP, 531, 16);", "bMalloc(160, PLAYER_CPP, 531, 16);"),
    M("cd_line", PIN, "bMalloc(164, PLAYER_CPP, 531, 16);", "bMalloc(164, PLAYER_CPP, 530, 16);"),
    M("fov_count", PIN, "bMalloc((int)(32 * sizeof(bVector3)),", "bMalloc((int)(31 * sizeof(bVector3)),"),
    M("fov_line", PIN, "PLAYER_CPP, 532, 16);", "PLAYER_CPP, 533, 16);"),
    M("jump_route_kept", PIN, "    p->pJumpCamRoute = NULL;\n    p->bWrongWay = 0;",
      "    p->bWrongWay = 0;"),
    M("wrong_way_kept", PIN, "    p->bWrongWay = 0;\n", ""),
    M("look_back_kept", PIN, "    p->bLookBack = 0;\n", ""),
    M("auto_replay_state_kept", PIN, "    p->mAutoReplayState = 0;\n", ""),
    M("auto_replay_time_kept", PIN, "    p->mLastAutoReplayTime = 0.0f;\n", ""),
    M("auto_replay_marker_written", PIN, "    p->mLastAutoReplayTime = 0.0f;\n",
      "    p->mLastAutoReplayTime = 0.0f;\n    p->mAutoReplayTimeMarker = 0.0f;\n"),
    M("event_score_text", PIN, "snprintf(p->strEventScore, sizeof p->strEventScore, \"0\");",
      "snprintf(p->strEventScore, sizeof p->strEventScore, \"1\");"),
    M("prev_score_text", PIN, "snprintf(p->strPrevScore, sizeof p->strPrevScore, \"0\");",
      "snprintf(p->strPrevScore, sizeof p->strPrevScore, \"1\");"),
    M("prev_score_cleared", PIN, "snprintf(p->strPrevScore, sizeof p->strPrevScore, \"0\");",
      "memset(p->strPrevScore, 0, sizeof p->strPrevScore);\n    p->strPrevScore[0] = '0';"),
    M("event_title_written", PIN, "    snprintf(p->strPrevScore, sizeof p->strPrevScore, \"0\");\n",
      "    snprintf(p->strPrevScore, sizeof p->strPrevScore, \"0\");\n"
      "    snprintf(p->strEventTitle, sizeof p->strEventTitle, \"0\");\n"),
    M("smokeable_kept", PIN, "    p->bSmokeableHit = 0;\n", ""),
    # the light arrays
    M("radar_lights_11", PIN, "    for (i = 11; i >= 0; i--)", "    for (i = 10; i >= 0; i--)"),
    M("nitrous_lights_9", PIN, "    for (i = 9; i >= 0; i--)", "    for (i = 8; i >= 0; i--)"),
    M("damage_lights_4", PIN, "    for (i = 4; i >= 0; i--)", "    for (i = 3; i >= 0; i--)"),
    M("tickets_3", PIN, "    for (i = 3; i >= 0; i--)", "    for (i = 2; i >= 0; i--)"),
    M("trackers_6", PIN, "    for (i = 6; i >= 0; i--)", "    for (i = 5; i >= 0; i--)"),
    M("places_7", PIN, "    for (i = 7; i >= 0; i--)", "    for (i = 6; i >= 0; i--)"),
    M("helicopters_2", PIN, "    for (i = 0; i < 3; i++) {\n        p->pFlailerBeTheCopHelicopter",
      "    for (i = 0; i < 2; i++) {\n        p->pFlailerBeTheCopHelicopter"),
    M("roadblocks_kept", PIN, "        p->pFlailerBeTheCopRoadblock[i] = NULL;\n", ""),
    # the radar beep and the rest
    M("radar_beep_name", PIN, "gGetInGameSampleFn(\"RadarBeep\")", "gGetInGameSampleFn(\"RadarBeeps\")"),
    M("radar_beep_none", PIN,
      "    p->pRadarBeep = gGetInGameSampleFn != NULL\n        ? gGetInGameSampleFn(\"RadarBeep\") : NULL;",
      "    p->pRadarBeep = NULL;"),
    M("ctor_last_speed_kept", PIN, "    p->RadarTimer.PackedTime = 0;\n    p->LastSpeed = 0;\n",
      "    p->RadarTimer.PackedTime = 0;\n"),
    M("ctor_prev_pursuit_kept", PIN, "    p->PrevPursuitLevel = 0;\n    p->PrevTicketLevel = 0;\n    p->LastSpeedSet",
      "    p->PrevTicketLevel = 0;\n    p->LastSpeedSet"),
    M("ctor_prev_ticket_kept", PIN, "    p->PrevTicketLevel = 0;\n    p->LastSpeedSet = 0.0f;\n    p->lastCar",
      "    p->LastSpeedSet = 0.0f;\n    p->lastCar"),
    M("ctor_last_speed_set_kept", PIN, "    p->LastSpeedSet = 0.0f;\n    p->lastCar = NULL;\n",
      "    p->lastCar = NULL;\n"),
    M("last_car_kept", PIN, "    p->lastCar = NULL;\n", ""),
    M("segment_kept", PIN, "    p->bSegmentCollisionDetected = 0;\n", ""),
    M("music_title_kept", PIN, "    p->bShownMusicTitle = 0;\n", ""),
    M("cop_time_kept", PIN, "    p->pFlailerBeTheCopTime = NULL;\n", ""),
    M("radar_offset_kept", PIN, "    p->bRadarOffset = 0;\n", ""),
    M("initial_radar_kept", PIN, "    p->fInitialRadarY = 0.0f;\n", ""),
    M("pursuit_offset_kept", PIN, "    p->bPursuitOffset = 0;\n", ""),
    M("initial_pursuit_kept", PIN, "    p->fInitialPursuitY = 0.0f;\n", ""),
    M("pursuit_state_written", PIN, "    p->numCleanLaps = 0;\n",
      "    p->numCleanLaps = 0;\n    p->PursuitOffsetState = 0;\n"),
    M("clean_laps_kept", PIN, "    p->numCleanLaps = 0;\n", ""),
    M("race_over_speech_kept", PIN, "    p->HasHeardRaceOverSpeech = 0;\n", ""),
    M("new2696_kept", PIN, "    p->New2696 = 0;\n", ""),
    M("speed_factor", PIN, "#define PLAYER_SPEED_FACTOR    0.9f", "#define PLAYER_SPEED_FACTOR    0.8f"),
    M("crossing_unscaled", PIN, "(float)WorldTimer * 0.00025f * 4000.0f + 0.5f);",
      "(float)WorldTimer + 0.5f);"),
    M("crossing_one_product", PIN, "(float)WorldTimer * 0.00025f * 4000.0f + 0.5f);",
      "(float)WorldTimer * (0.00025f * 4000.0f) + 0.5f);"),
    M("crossing_no_round", PIN, "(float)WorldTimer * 0.00025f * 4000.0f + 0.5f);",
      "(float)WorldTimer * 0.00025f * 4000.0f);"),
    M("crossing_cast", PIN, "p->LastCrossingTime.PackedTime = (uint32_t)ee_trunc_w(",
      "p->LastCrossingTime.PackedTime = (uint32_t)(int32_t)("),
    M("jukebox", PIN, "    p->CurrentJukeboxIndex = -1;", "    p->CurrentJukeboxIndex = 0;"),
    M("dc_steering_kept", PIN, "    p->DrivingControls &= ~(PLAYER_DC_STEERING | PLAYER_DC_THROTTLE",
      "    p->DrivingControls &= ~(PLAYER_DC_THROTTLE"),
    M("dc_throttle_kept", PIN, "    p->DrivingControls &= ~(PLAYER_DC_STEERING | PLAYER_DC_THROTTLE",
      "    p->DrivingControls &= ~(PLAYER_DC_STEERING"),
    M("dc_ebrake_kept", PIN, "                            | PLAYER_DC_EBRAKE);", "                            );"),
    M("dc_cleared", PIN, "    p->DrivingControls &= ~(", "    p->DrivingControls = ~(~0u | "),
    M("new2540", PIN, "    p->New2540 = 1;", "    p->New2540 = 0;"),
    M("check_top_speed", PIN, "    p->bCheckTopSpeed = 1;", "    p->bCheckTopSpeed = 0;"),
    # the score display
    M("score_find_order", PIN, [
        ("    p->pFlailerScore[1] = find_score_object(PLAYER_SCORE_OBJECT1);\n"
         "    p->pFlailerScore[0] = find_score_object(PLAYER_SCORE_OBJECT0);\n",
         "    p->pFlailerScore[0] = find_score_object(PLAYER_SCORE_OBJECT0);\n"
         "    p->pFlailerScore[1] = find_score_object(PLAYER_SCORE_OBJECT1);\n")]),
    M("score_screen", PIN, "#define PLAYER_SCORE_SCREEN    0x49c15518u", "#define PLAYER_SCORE_SCREEN    0x49c15519u"),
    M("score_bitmap", PIN, "#define PLAYER_FLAILER_BITMAP  2", "#define PLAYER_FLAILER_BITMAP  1"),
    M("score_object1", PIN, "#define PLAYER_SCORE_OBJECT1   0x464ba8eau", "#define PLAYER_SCORE_OBJECT1   0x464ba8ebu"),
    M("score_object3", PIN, "#define PLAYER_SCORE_OBJECT3   0xf88dd0b1u", "#define PLAYER_SCORE_OBJECT3   0xf88dd0b2u"),
    M("score_top_order", PIN, [
        ("    p->fScoreTop[1] = score_object_top(p->pFlailerScore[1]);\n"
         "    p->fScoreTop[0] = score_object_top(p->pFlailerScore[0]);\n",
         "    p->fScoreTop[0] = score_object_top(p->pFlailerScore[0]);\n"
         "    p->fScoreTop[1] = score_object_top(p->pFlailerScore[1]);\n")]),
    M("score_top2_base", PIN, "                      - p->fScoreTop[0];", "                      - p->fScoreTop[1];"),
    M("score_top3_base", PIN, "                      - p->fScoreTop[1];", "                      - p->fScoreTop[0];"),
    M("score_top2_absolute", PIN, "    p->fScoreTop[2] = score_object_top(p->pFlailerScore[2])\n"
      "                      - p->fScoreTop[0];",
      "    p->fScoreTop[2] = score_object_top(p->pFlailerScore[2]);"),
    M("score_top_x", PIN, "        gFlailerChunkGetTopLeftFn(o, &x, &y);\n    return y;",
      "        gFlailerChunkGetTopLeftFn(o, &x, &y);\n    return x;"),
    M("score_top_unguarded", PIN, "    if (o != NULL && gFlailerChunkGetTopLeftFn != NULL)",
      "    if (gFlailerChunkGetTopLeftFn != NULL)"),
    M("score_top_none", PIN, "    float x = 0.0f, y = 0.0f;", "    float x = 0.0f, y = 1.0f;"),
    M("new2736_kept", PIN, "    p->New2736 = 0;\n", ""),
    # ResetToDefaults
    M("rd_rumble", PIN, "    s->Rumble = 1;", "    s->Rumble = 0;"),
    M("rd_hud_state", PIN, "    s->PlayersHudState = 0;\n", ""),
    M("rd_style", PIN, "    s->DrivingStyle = 0;\n", ""),
    M("rd_transmission", PIN, "    s->TransmissionType = 0;\n", ""),
    M("rd_skip_ignored", PIN,
      "    s->DriveCameraPOVIndex = gPlayerCamSkipFE != NULL && *gPlayerCamSkipFE\n",
      "    s->DriveCameraPOVIndex = 0\n"),
    M("rd_pov_default", PIN, "        ? (int8_t)PlayerSkipFEPOVIndex : 1;", "        ? (int8_t)PlayerSkipFEPOVIndex : 0;"),
    M("rd_pov_skip", PIN, "        ? (int8_t)PlayerSkipFEPOVIndex : 1;", "        ? 1 : 1;"),
    M("rd_split", PIN, "    s->SplitTimeType = 0;\n", ""),
    M("rd_lookback", PIN, "    s->Lookback = 1;", "    s->Lookback = 0;"),
    M("rd_gender", PIN, "    s->PreferredGender = 0;\n", ""),
    M("rd_new7", PIN, "    s->New7 = 0;\n", ""),
    M("rd_spring", PIN, "    s->CameraSpring = 0;\n", ""),
    M("rd_name", PIN, "    strcpy(s->PlayerName, \"PLAYER\");", "    strcpy(s->PlayerName, \"PLAYER1\");"),
    M("rd_name_cleared", PIN, "    strcpy(s->PlayerName, \"PLAYER\");",
      "    memset(s->PlayerName, 0, sizeof s->PlayerName);\n    strcpy(s->PlayerName, \"PLAYER\");"),
    M("rd_features", PIN, "    s->PreferredHudFeatures = 853;", "    s->PreferredHudFeatures = 852;"),
    M("rd_new44", PIN, "    s->New44 = 1;", "    s->New44 = 0;"),
    M("rd_new40", PIN, "    s->New40 = 1;", "    s->New40 = 0;"),
    M("rd_total_record", PIN, "    s->BestTotalTimeRecord.PackedTime = 0;\n", ""),
    M("rd_lap_record", PIN, "    s->BestLapTimeRecord.PackedTime = 0;\n", ""),
    # CleanUpJumpCam
    M("jc_no_delete", PIN, "        gPreviewRouteDeleteFn(p->pJumpCamRoute);\n", "        ;\n"),
    M("jc_kept", PIN, "    p->pJumpCamRoute = NULL;\n}", "}"),
    # the destructor
    M("d_no_reset_flailer", PIN, "        gPlayerResetFlailerMovementFn(p);\n", "        ;\n"),
    M("d_hud_features", PIN, "        gPlayerSetHudFeaturesFn(p, 0);", "        gPlayerSetHudFeaturesFn(p, 1);"),
    M("d_order", PIN, [
        ("    if (gPlayerResetFlailerMovementFn != NULL)\n        gPlayerResetFlailerMovementFn(p);\n"
         "    if (gPlayerSetHudFeaturesFn != NULL)\n        gPlayerSetHudFeaturesFn(p, 0);\n",
         "    if (gPlayerSetHudFeaturesFn != NULL)\n        gPlayerSetHudFeaturesFn(p, 0);\n"
         "    if (gPlayerResetFlailerMovementFn != NULL)\n        gPlayerResetFlailerMovementFn(p);\n")]),
    M("d_no_route", PIN, "        gPreviewRouteDeleteFn(p->pRoute);\n", "        ;\n"),
    M("d_no_sample", PIN, "        gSampleDeleteFn(p->pZoneSample);\n", "        ;\n"),
    M("d_no_cd", PIN, "        bFree(p->myCD);\n", "        ;\n"),
    M("d_cd_unguarded", PIN, "    if (p->myCD != NULL)\n        bFree(p->myCD);", "    bFree(p->myCD);"),
    M("d_no_fov", PIN, "        bFree(p->FOVtable);\n", "        ;\n"),
    M("d_fov_unguarded", PIN, "    if (p->FOVtable != NULL)\n        bFree(p->FOVtable);", "    bFree(p->FOVtable);"),
    M("d_no_jump_cam", PIN, "    player_clean_up_jump_cam(p);\n    if (p->pVisibleDrivingLine",
      "    if (p->pVisibleDrivingLine"),
    M("d_no_line", PIN, "            gVisibleDrivingLineDeleteFn(p->pVisibleDrivingLine);\n", "            ;\n"),
    M("d_line_kept", PIN, "        p->pVisibleDrivingLine = NULL;\n    }\n    if (p->pNisManager",
      "    }\n    if (p->pNisManager"),
    M("d_no_nis", PIN, "        gDeleteNisManagerFn(p->pNisManager);\n", "        ;\n"),
    M("d_avg_flag", PIN, "        average_destroy(p->pAverageSpeedRatio, 3);",
      "        average_destroy(p->pAverageSpeedRatio, 2);"),
    M("d_avg_unguarded", PIN,
      "    if (p->pAverageSpeedRatio != NULL)\n        average_destroy(p->pAverageSpeedRatio, 3);",
      "    average_destroy(p->pAverageSpeedRatio, 3);"),
    M("d_huds_19", PIN, "    for (i = 0; i < 20; i++)\n        if (p->pHudAnimations[i] != NULL",
      "    for (i = 0; i < 19; i++)\n        if (p->pHudAnimations[i] != NULL"),
    M("d_huds_unguarded", PIN, "        if (p->pHudAnimations[i] != NULL && gHudAnimatorDeleteFn != NULL)",
      "        if (gHudAnimatorDeleteFn != NULL)"),
    M("d_no_count", PIN, "    PlayerNumPlayers--;\n", ""),
    M("d_last_speed_kept", PIN, "    PlayerNumPlayers--;\n    p->LastSpeed = 0;\n", "    PlayerNumPlayers--;\n"),
    M("d_prev_pursuit_kept", PIN,
      "    p->PrevPursuitLevel = 0;\n    p->PrevTicketLevel = 0;\n    if (PlayerNumPlayers >= 0",
      "    p->PrevTicketLevel = 0;\n    if (PlayerNumPlayers >= 0"),
    M("d_prev_ticket_kept", PIN, "    p->PrevTicketLevel = 0;\n    if (PlayerNumPlayers >= 0",
      "    if (PlayerNumPlayers >= 0"),
    M("d_index_zero", PIN, "        PlayerPlayersByIndex[PlayerNumPlayers] = NULL;",
      "        PlayerPlayersByIndex[0] = NULL;"),
    M("d_index_kept", PIN, "        PlayerPlayersByIndex[PlayerNumPlayers] = NULL;\n", "        ;\n"),
    M("d_last_speed_set_kept", PIN, "    p->LastSpeedSet = 0.0f;\n    if (p->PlayerNumber",
      "    if (p->PlayerNumber"),
    M("d_by_number_kept", PIN, "        PlayerPlayersByNumber[p->PlayerNumber] = NULL;\n", "        ;\n"),
    M("d_glare", PIN, "    bResetGlare = 1;", "    bResetGlare = 0;"),
    M("d_overlay_flag", PIN, "    nisoverlay_destroy(&p->mFlailerNIS, 2);", "    nisoverlay_destroy(&p->mFlailerNIS, 3);"),
    M("d_no_overlay", PIN, "    nisoverlay_destroy(&p->mFlailerNIS, 2);\n", ""),
    M("d_no_topo", PIN, "    topology_destroy(&p->Topology);\n", ""),
    M("d_free_always", PIN, "    if (flags & 1)\n        bFree(p);\n}", "    bFree(p);\n}"),
    M("d_free_never", PIN, "    if (flags & 1)\n        bFree(p);\n}", "}"),
    # PredetermineNisNumbers
    M("pd_ticket_type", PIN, "        gPlayerCreateRandomNisArrayFn(p, 1);", "        gPlayerCreateRandomNisArrayFn(p, 2);"),
    M("pd_arrest_type", PIN, "        gPlayerCreateRandomNisArrayFn(p, 2);", "        gPlayerCreateRandomNisArrayFn(p, 1);"),
    M("pd_ticket_index", PIN, "    p->TicketNisIndex = -1;\n    if (gPlayerCreateRandomNisArrayFn",
      "    p->TicketNisIndex = 0;\n    if (gPlayerCreateRandomNisArrayFn"),
    M("pd_arrest_index", PIN, "    p->ArrestNisIndex = -1;\n}", "    p->ArrestNisIndex = 0;\n}"),
    # InitForRace
    M("ifr_car_player", PIN, "    c->pPlayer = p;\n", ""),
    M("ifr_my_car", PIN, "    p->MyCar = c;\n", ""),
    M("ifr_mode_transmission", PIN, "    c->State.DriverMode = p->PlayerSettings.DrivingStyle;",
      "    c->State.DriverMode = p->PlayerSettings.TransmissionType;"),
    M("ifr_mode_unsigned", PIN, "    c->State.DriverMode = p->PlayerSettings.DrivingStyle;",
      "    c->State.DriverMode = (uint8_t)p->PlayerSettings.DrivingStyle;"),
    M("ifr_real_any", PIN, "    if (c->TheControlMode == REAL_CONTROL)", "    if (c->TheControlMode != 0)"),
    M("ifr_transmission_style", PIN, "            p->PlayerSettings.TransmissionType);",
      "            p->PlayerSettings.DrivingStyle);"),
    M("ifr_no_predetermine", PIN, "    player_predetermine_nis_numbers(p);\n}\n\nvoid player_cleanup",
      "}\n\nvoid player_cleanup"),
    # CleanupAfterRace
    M("cl_blur_view", PIN, "        gRadialBlurOffFn(p->PlayerNumber);", "        gRadialBlurOffFn(p->ViewID);"),
    M("cl_no_remove", PIN, "    player_remove_camera_movers(p);\n", ""),
    M("cl_order", PIN, [
        ("    if (gRadialBlurOffFn != NULL)\n        gRadialBlurOffFn(p->PlayerNumber);\n"
         "    player_remove_camera_movers(p);\n",
         "    player_remove_camera_movers(p);\n"
         "    if (gRadialBlurOffFn != NULL)\n        gRadialBlurOffFn(p->PlayerNumber);\n")]),
    M("cl_playing_ignored", PIN, "        && gNisManagerIsPlayingFn(p->pNisManager)) {", "        ) {"),
    M("cl_no_stop", PIN, "            gNisManagerStopFn(p->pNisManager);\n", "            ;\n"),
    M("cl_no_finish", PIN, "        nisoverlay_finish(&p->mFlailerNIS);\n", ""),
    M("cl_finish_always", PIN, "        nisoverlay_finish(&p->mFlailerNIS);\n    }\n",
      "    }\n    nisoverlay_finish(&p->mFlailerNIS);\n"),
    M("cl_input_mode", PIN, "        gPlayerSetInputModeFn(p, 0);", "        gPlayerSetInputModeFn(p, 1);"),
    M("cl_my_car_kept", PIN, "    p->MyCar = NULL;\n    if (c != NULL)", "    if (c != NULL)"),
    M("cl_car_player_kept", PIN, "        c->pPlayer = NULL;\n", "        ;\n"),
    # the overlay's tracks
    M("track_duration", NIS, "    t->duration = 1.0f;", "    t->duration = 0.0f;"),
    M("track_threshold", NIS, "    t->arrivalThreshold = 1.0f;", "    t->arrivalThreshold = 0.5f;"),
    M("track_flags", NIS, "    t->flags = 1;", "    t->flags = 0;"),
    M("track_val", NIS, "    t->val = 0.0f;\n", ""),
    M("track_dval", NIS, "    t->dval = 0.0f;\n", ""),
    M("track_val_desired", NIS, "    t->valDesired = 0.0f;\n", ""),
    M("track_dval_desired", NIS, "    t->dvalDesired = 0.0f;\n", ""),
    M("track_state", NIS, "    t->state = 0;\n", ""),
    M("track_time_written", NIS, "    t->state = 0;\n", "    t->state = 0;\n    t->time = 0.0f;\n"),
    M("track_size", NIS, "bMalloc(48, \"NISCubicAnimation\", 0, 16);", "bMalloc(52, \"NISCubicAnimation\", 0, 16);"),
    M("track_name", NIS, "bMalloc(48, \"NISCubicAnimation\", 0, 16);", "bMalloc(48, \"NISCubic\", 0, 16);"),
    M("track_pool", NIS, "bMalloc(48, \"NISCubicAnimation\", 0, 16);", "bMalloc(48, \"NISCubicAnimation\", 0, 0);"),
    # the overlay's constructor and destructor
    M("oi_state", NIS, "    o->State = FLAILER_NIS_IDLE;", "    o->State = FLAILER_NIS_BUSTED;"),
    M("oi_one_track", NIS, "    o->AlphaAnimationTrack = new_track();",
      "    o->AlphaAnimationTrack = o->ScaleAnimationTrack;"),
    M("oi_track_order", NIS, [
        ("    o->ScaleAnimationTrack = new_track();\n    o->AlphaAnimationTrack = new_track();\n",
         "    o->AlphaAnimationTrack = new_track();\n    o->ScaleAnimationTrack = new_track();\n")]),
    M("oi_scale_y", NIS, "    o->ScaleY = 1.0f;", "    o->ScaleY = 0.5f;"),
    M("oi_scale_x", NIS, "    o->ScaleX = 1.0f;", "    o->ScaleX = 0.5f;"),
    M("oi_sx_kept", NIS, "    o->sx = 0.0f;\n", ""),
    M("oi_sy_kept", NIS, "    o->sy = 0.0f;\n", ""),
    M("od_scale_kept", NIS, "    bFree(o->ScaleAnimationTrack);\n", ""),
    M("od_alpha_kept", NIS, "    bFree(o->AlphaAnimationTrack);\n", ""),
    # SetScreen
    M("ss_screen_kept", NIS, "    o->ScreenHash = screen;\n", ""),
    M("ss_object", NIH, "#define NISOVERLAY_BUSTED_OBJECT 0x76494c5bu",
      "#define NISOVERLAY_BUSTED_OBJECT 0x76494c5cu"),
    M("ss_saved_x_from_y", NIS, "    o->SavedScaleX = sx;", "    o->SavedScaleX = sy;"),
    M("ss_saved_y_from_x", NIS, "    o->SavedScaleY = sy;", "    o->SavedScaleY = sx;"),
    M("ss_one_scale_call", NIS,
      "    sx = 1.0f;\n    sy = 1.0f;\n    if (gFlailerGetScaleFn != NULL)\n"
      "        gFlailerGetScaleFn(o->ScreenHash, NISOVERLAY_BUSTED_OBJECT, &sx, &sy);\n", ""),
    M("ss_top_screen", NIS, "        ? gFlailerGetTopLeftYFn(o->ScreenHash, NISOVERLAY_BUSTED_OBJECT)",
      "        ? gFlailerGetTopLeftYFn(0, NISOVERLAY_BUSTED_OBJECT)"),
    M("ss_no_top", NIS, "    o->SavedTopLeftY = gFlailerGetTopLeftYFn != NULL\n",
      "    o->SavedTopLeftY = 0\n"),
    # Finish
    M("fin_no_screen_test", NIS, "    if (o->ScreenHash == 0)\n        return;\n", ""),
    M("fin_visible", NIS, "#define NISOVERLAY_SCREEN_INVISIBLE 1", "#define NISOVERLAY_SCREEN_INVISIBLE 0"),
    M("fin_no_vis", NIS, "    if (gSetFlailerScreenVisibilityFn != NULL)\n"
      "        gSetFlailerScreenVisibilityFn(o->ScreenHash,\n"
      "                                      NISOVERLAY_SCREEN_INVISIBLE);\n", ""),
    M("fin_no_busted_test", NIS, "    if (o->BustedDisplay == NULL)\n        return;\n", ""),
    M("fin_scale_x", NIS, "        gFlailerChunkSetScaleXFn(o->BustedDisplay, o->SavedScaleX);",
      "        gFlailerChunkSetScaleXFn(o->BustedDisplay, o->SavedScaleY);"),
    M("fin_scale_y", NIS, "        gFlailerChunkSetScaleYFn(o->BustedDisplay, o->SavedScaleY);",
      "        gFlailerChunkSetScaleYFn(o->BustedDisplay, o->SavedScaleX);"),
    M("fin_top", NIS, "        gFlailerChunkSetTopLeftYFn(o->BustedDisplay, o->SavedTopLeftY);",
      "        gFlailerChunkSetTopLeftYFn(o->BustedDisplay, o->ScaleY);"),
]

# Mutants that cannot change what either side computes, each with why.
EQUIVALENT = {
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    hostbuild.recover()
    m = Model()
    sc = script()
    base = m.run(sc)
    caught, survived, missing, equivalent = 0, [], [], []
    scdir = tempfile.TemporaryDirectory()
    scp = Path(scdir.name) / "scenarios.txt"
    scp.write_text(encode(sc))
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, scp, out)
        if diff(base, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for mut in todo:
        name, rel, before, after = mut
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        edits = before if isinstance(before, list) else [(before, after)]
        new, bad = text, None
        for b, a in edits:
            probe = b.replace(NL, "\r\n") if crlf else b
            repl = a.replace(NL, "\r\n") if crlf else a
            if new.count(probe) != 1:
                bad = "NOT FOUND" if not new.count(probe) else "NOT UNIQUE"
                break
            new = new.replace(probe, repl, 1)
        if bad:
            missing.append(name)
            print("  %-44s PATTERN %s" % (name, bad))
            continue
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
    scdir.cleanup()

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

    check_tables()
    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None))

    layout = arm_layout_check()
    m = Model()
    sc = script()
    lines = m.run(sc)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = Path(tmp) / "scenarios.txt"
        scp.write_text(encode(sc))
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(lines, harness)
    ops = sum(len(s) for s in sc)
    print("%d scenarios, %d ops, %d lines, %d differ"
          % (len(sc), ops, len(harness), n))
    sys.exit(1 if (n or rc or layout) else 0)


if __name__ == "__main__":
    main()
