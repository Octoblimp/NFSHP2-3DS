#!/usr/bin/env python3
"""Cross-check 3DS Files/source/fredrace.c -- FrontendDatabase's race start
-- and the RaceParameters methods it calls (raceparams.c) against the retail
image, run in mipsemu.

The model is the image. These run as shipped:

  * StartSkipFEGame (0x00184bd8), StartRace (0x00184f68), SetupCarsForRace
    (0x00185690) and CalculateStartingPositions (0x00185fe8), with
    UseTheRaceEvent, IsChallengeGame, IsEventGame and GetSelectedRideInfo;
  * GenerateRandomRideInfo (0x00188218) with the inlined CarTypeInfo
    iterator, GetRandomSkin (0x00188460), PickCharacterNumberThatIsntRacing
    (0x001840a0), PickCopCharacterNumber (0x00185640), AreThereAnyCarsOfType
    (0x00183ed0) and OfColour (0x00183f68), the unused-skin pick
    (0x00184018), RideInfo::Init and DriverInfo's constructor;
  * SetRecordTimesToBeat (0x00184490), its loop over the players
    (0x001842a8) and HighScoreTable's four indexes (0x001868a0 to
    0x001869d0);
  * RaceParameters' AddDriverInfo (0x001eda40), GetDriverInfoByDriverNumber
    (0x001edb40), the eliminated drivers' restore (0x001edc50) and
    elimination (0x001edbc8), the model count (0x001ede08) and
    GetLocationIndex;
  * the Mode Selects' StartQuickRace (0x00216c18), with the express
    game's track pick (0x00216aa8), IsTrackUnlocked (0x0024b760),
    IsTrackAnEventReward (0x001ffaa8), EventTreeIsTrackUnlocked
    (0x001ffb18), MakeChallengeCarsAvailable, SetCarAvailability,
    AssignCarOfType and GetCarStatus (0x00187958);
  * and under them bRandom, bSetRandomSeed, GetSkinInfo, GetNumSkins,
    GetSkinNumber, GetTrackInfo, GetCharacterInfo and its hash lookup,
    bStrICmp, bStrCmp and bStringHash; InitFred, RaceParameters'
    defaults, LoaderCharacterInfo and LoaderTrackGeometry set the scene.

What the race start asks of the race events, the event trees and the game
flow is stubbed, on both sides alike, and prints itself: SetupFakeRace-
EventForChallengeKnockout, RaceEvent's GetStatus, ResetState,
GetRaceIndex, DriverEliminated and the starting positions (0x002022c0),
EventTrack::SetRace, the knockout's start positions and ranks, the
tournament's UserRank, the event tree, its event and the event's word and
opponents, MaybeSetSelectedCarForMultiTrackEvent, TheDemoModeReplay's two
calls, the reward-car count (0x001ff978) and ChangeGameFlow, and for the
quick race FlailerScreenList::StopMovie and EventTree's TrackIsAReward
and IsTrackUnlocked, over a list of trees the script sizes at gp-16712.
The script sets what each answers. bMalloc is a bump allocator and bFree
does nothing: the pick's list nodes are the image's alone. IsCarUnlocked, GetTranslatedString and the audio
options' defaults answer as fred_check's do, silently. The harness
(tools/src/fredrace_test.c) runs the port over the same script.

The data are GLOBALB's own -- its 64 car records and 235 skins, 66 track
records, the characters and TheDifficultyInfo -- changed field by field:
cars without geometry or skins, of other classes and usages, location
weights moved; skins' paint types; tracks' cop characters and records. The
race parameters, Fred, a second FrontendDatabase, the drivers' table and
the SkipFE words are varied around them, and the records start filled
with patterns so a byte one side leaves and the other writes shows.

After each op the transcript holds what changed: Fred and the second
database in 32-byte rows, TheRaceParameters' first 772 bytes in rows and
its last four words, each of the fourteen DriverInfos by field, the
scratch DriverInfo, ride and character list, TheRaceEvent's four words and
the seed.

    python tools/fredrace_check.py
    python tools/fredrace_check.py --mutate [--only a,b]
    python tools/fredrace_check.py --dump out/fredrace
"""
import argparse
import os
import random
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import mutpar
import physicscar_check as pcc
import retail_model
from mipsemu import M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/fredrace_test.c"
FRR = "3DS Files/source/fredrace.c"
RPC = "3DS Files/source/raceparams.c"
CFC = "3DS Files/source/configitems.c"
SOURCES = [HARNESS, FRR, RPC, CFC] + [
    "3DS Files/source/" + f for f in (
        "fred.c", "race.c", "characterinfo.c", "edisplay.c", "playersettings.c",
        "difficultyinfo.c", "cartypeinfo.c", "langtab.c", "realtime.c",
        "bticker.c", "joylog.c", "timer.c", "track.c",
        "terraintype.c", "cartrack.c", "carstate.c", "emath.c", "bmatrix.c",
        "terraintypetab.c", "bslotpool.c", "bvector.c", "bmath.c",
        "bmathtab.c", "bchunk.c", "p32.c", "quickrace.c")]

HARNESS_TIMEOUT = 600
GLOBALB = ROOT / "extracted-retail" / "GLOBAL" / "GLOBALB.BUN"

# ================================================================ the image

GP = 0x003358f0
FRED = 0x002fc050
FRED_SIZE = 0x114e0
RP = 0x0031a898
RP_COMMON = 772
DIT = 0x0031abb0
DI_SIZE = 24
NUM_DI = 14
SEED = 0x00332068
CURR_LANGUAGE = 0x0031c1c8
EV = 0x0031b600                   # TheRaceEvent
DIFFICULTY = 0x002f0080           # TheDifficultyInfo
DIFFICULTY_SIZE = 992
REPLAY = 0x002f0960               # TheDemoModeReplay's first word
NOT_TRANSLATED = 0x002bc958

SINIT_FRED = 0x00187c58
INIT_FRED = 0x00183820
RP_DEFAULTS = 0x001ed5c8
LOADER_CHAR = 0x001d9330
LOADER_TRACK = 0x00153608

START_SKIP_FE = 0x00184bd8
START_RACE = 0x00184f68
SETUP_CARS = 0x00185690
START_POSITIONS = 0x00185fe8
GENERATE_RIDE = 0x00188218
RANDOM_SKIN = 0x00188460
PICK_CHARACTER = 0x001840a0
PICK_COP = 0x00185640
ANY_OF_TYPE = 0x00183ed0
ANY_OF_COLOUR = 0x00183f68
UNUSED_SKIN = 0x00184018
RECORD_TIMES = 0x00184490
ALL_RECORD_TIMES = 0x001842a8
UNIQUE_TRACK = 0x001868a0
UNIQUE_LAP = 0x001868d8
TOTAL_INDEX = 0x00186938
LAP_INDEX = 0x001869d0
ADD_DRIVER = 0x001eda40
FIND_DRIVER = 0x001edb40
RESTORE = 0x001edc50
ELIMINATE = 0x001edbc8
TOO_MANY = 0x001ede08
LOCATION_INDEX = 0x001eddd8
DRIVER_CTOR = 0x00188610
RIDE_INIT = 0x00187dd0
USE_EVENT = 0x001841a8
IS_CHALLENGE = 0x001855f0
IS_EVENT = 0x00185618

IS_CAR_UNLOCKED = 0x0024b208
TRANSLATE = 0x0021e560
AUDIO_DEFAULTS = 0x001ef1c8
FAKE_KO = 0x001849f0
EV_STATUS = 0x00202658
EV_RESET = 0x00202698
EV_RACE_INDEX = 0x00202010
SET_RACE = 0x001fec20
KO_STATE = 0x002018a0
KO_START = 0x00200598
TOURNAMENT = 0x00201880
USER_RANK = 0x00200768
EVENT_TREE = 0x00185568
EVENT_NUMBER = 0x001fdfe8
EVENT_WORD = 0x00200f98
ELIMINATED = 0x00201708
RACER_INDEX = 0x00201558
KO_RANK = 0x00200220
EV_POSITIONS = 0x002022c0
MULTI_TRACK = 0x00184318
REPLAY_RESTORE = 0x0013f220
REPLAY_UNLOAD = 0x0013f0c0
REWARD_CARS = 0x001ff978
CHANGE_FLOW = 0x001680d8

START_QUICK = 0x00216c18
PICK_TRACK = 0x00216aa8
IS_UNLOCKED = 0x0024b760
IS_REWARD = 0x001ffaa8
TREES_UNLOCKED = 0x001ffb18
CAR_STATUS = 0x00187958
STOP_MOVIE = 0x0016d0a0
TREE_REWARD = 0x001ff6c8          # EventTree::TrackIsAReward
TREE_UNLOCKED = 0x001ff5c8        # EventTree::IsTrackUnlocked
BMALLOC = 0x002577c0
BFREE = 0x00257850
TREE_LIST = GP - 16712            # the event trees' bList

G_CARS = GP - 20616               # CarTypeInfoArray
G_SKINS = GP - 20612              # the skin table
G_NSKINS = GP - 20608

# The words the race start reads, by the script's names. pov is a byte the
# image reads with lbu; density and oncoming are floats, by their bits.
VARS = {
    "track": GP - 23256, "e3": GP - 23224, "skipfe": GP - 23220,
    "np": GP - 23216, "nai": GP - 23212, "laps": GP - 23208,
    "cops": GP - 23204, "tickets": GP - 23196, "roadblocks": GP - 23192,
    "heli": GP - 23188, "spikes": GP - 23184, "new624": GP - 23180,
    "beacop": GP - 23176, "pov": GP - 23172, "density": GP - 23164,
    "oncoming": GP - 23160, "racetype": GP - 23156, "diff": GP - 23148,
    "dp1type": GP - 23136, "dp2type": GP - 23132, "dp1skin": GP - 23128,
    "dp2skin": GP - 23124, "force": GP - 23116, "maxai": GP - 23112,
    "lang": CURR_LANGUAGE, "video": GP - 19612, "seed": SEED,
    "state": GP - 21420, "replay": REPLAY,
}

SPAN = 0x40000
SLOT_BASE = 0x01000000            # four chunk slots
CARS = 0x01200000
TRK = 0x01300000
SKN = 0x01340000
NAMES = 0x01410000
RIDE = 0x01420000                 # the scratch RideInfo
DI_SCR = 0x01420040               # the scratch DriverInfo
LIST = 0x01420080                 # the scratch character list
TREE = 0x01430000                 # the event tree, its event and opponents
EVT = 0x01431000
OPP = 0x01432000
KO = 0x01433000
TS = 0x01434000
ALT = 0x01500000                  # the second FrontendDatabase
TREES = 0x01440000                # the event trees' nodes, 16 bytes each
PICK = 0x01420100                 # the pick's 16-byte answer

CAR_REC = 1376
TRK_REC = 164
CAR_CHUNK, SKIN_CHUNK, TRACK_CHUNK = 0x34600, 0x34601, 0x34201
CHAR_CHUNK, BODY_CHUNK = 0x34300, 0x34301
DIFF_CHUNK = 0x34b00

# CarTypeInfo, retail's offsets.
GEOMETRY, COMP_GEOMETRY = 64, 96
NUM_SKINS, CAR_CLASS = 229, 230
MASS = 480
LOCATION_PROB = 1312
USAGE = 1336
SKINS = 1348
TORQUE = 704

# TrackInfo.
IS_VALID, P2P, HIGH_SCORE_INDEX, COP_HASH = 64, 67, 70, 84

# FrontendDatabase.
COPS_ON = 32                      # MainMenuOpts[1]
DISPLAY = 332
HIGH_SCORES = 1720
NUM_TOTAL_TIMES, NUM_LAP_TIMES = 7200, 800
ABORTED, GAME_TYPE, CURRENT_EVENT, NUM_PLAYERS = 67368, 67372, 67376, 67380
FPI = 67384
FPI_SIZE = 1744
SETTINGS = 1604
RIDES = 1652

# RaceParameters.
RPF = {
    "track": (0, 4), "weather": (4, 4), "tod": (8, 4), "dir": (12, 4),
    "density": (16, 4), "oncoming": (20, 4), "aidemo": (24, 4),
    "racetype": (32, 4), "ttt": (36, 4), "p2p": (40, 4), "laps": (44, 4),
    "np": (48, 4), "nai": (52, 4), "oppsel": (56, 4), "start0": (60, 1),
    "start1": (61, 1), "nfsmode": (596, 4), "treerace": (600, 4),
    "cops": (604, 4), "beacop": (628, 4), "copstr": (648, 4),
    "oppstr": (756, 4), "boost0": (764, 4), "boost1": (768, 4),
}


def bhash(s):
    h = 0xffffffff
    for c in s:
        h = (h * 33 + c) & M32
    return h


def fbits(x):
    return struct.unpack("<i", struct.pack("<f", x))[0]


# ================================================================ the data

def globalb_chunks():
    data = GLOBALB.read_bytes()
    out = {}
    off = 0
    while off + 8 <= len(data):
        cid, size = struct.unpack_from("<II", data, off)
        if cid in (CAR_CHUNK, SKIN_CHUNK, TRACK_CHUNK, CHAR_CHUNK, BODY_CHUNK,
                   DIFF_CHUNK) and cid not in out:
            out[cid] = data[off:off + 8 + size]
        off += 8 + size
    return out


class Script(object):
    def __init__(self, ch):
        self.ch = ch
        self.ops = []

    def op(self, *parts):
        self.ops.append(" ".join(str(p) for p in parts))

    def load_all(self):
        """The chunks into their places, as GLOBALB loads them."""
        self.op("K", 0, self.ch[BODY_CHUNK].hex())
        self.op("K", 1, self.ch[CHAR_CHUNK].hex())
        self.op("L", 0)
        self.op("L", 1)
        self.op("KC", self.ch[CAR_CHUNK][16:16 + 64 * CAR_REC].hex())
        self.op("KT", self.ch[TRACK_CHUNK].hex())
        self.op("KS", self.ch[SKIN_CHUNK].hex())
        self.op("KD", self.ch[DIFF_CHUNK].hex())

    def car(self, t, off, n, v):
        self.op("cr", t, off, n, v)

    def carf(self, t, off, x):
        self.op("cr", t, off, 4, fbits(x))

    def track(self, i, off, n, v):
        self.op("tr", i, off, n, v)

    def skin(self, i, off, n, v):
        self.op("sk", i, off, n, v)

    def rp(self, name, v):
        off, n = RPF[name]
        self.op("rp", off, n, fbits(v) if isinstance(v, float) else v)

    def fr(self, k, off, n, v):
        self.op("fr", k, off, n, v)

    def game(self, k, g):
        self.fr(k, GAME_TYPE, 4, g)

    def ride(self, k, p, g, ty, skin, dash=0, vd=0):
        off = FPI + FPI_SIZE * p + RIDES + 8 * g
        self.fr(k, off, 4, ty)
        self.fr(k, off + 4, 4, (skin & 0xff) << 8 | (dash & 0xff) << 16
                | (vd & 0xff) << 24)

    def gender(self, k, p, g):
        self.fr(k, FPI + FPI_SIZE * p + SETTINGS + 7, 1, g)

    def setup(self, fill="00", seed=None):
        """The defaults over a fill: Fred's constructor and InitFred, then
        TheRaceParameters'."""
        self.op("F", fill)
        if seed is not None:
            self.op("v", "seed", seed)
        self.op("SF")
        self.op("I")
        self.op("R")


DISC_VARS = {
    "track": -1, "e3": 0, "skipfe": 0, "np": 1, "nai": 0, "laps": 8,
    "cops": 0, "tickets": 1, "roadblocks": 1, "heli": 1, "spikes": 1,
    "new624": 1, "beacop": 0, "pov": 1, "density": 0,
    "oncoming": fbits(0.5), "racetype": 1, "diff": 0, "dp1type": 37,
    "dp2type": 37, "dp1skin": 1, "dp2skin": 1, "force": -1, "maxai": 7,
    "lang": 0, "video": 0, "state": 0, "replay": 0,
}


def reset_vars(s):
    for k, v in DISC_VARS.items():
        s.op("v", k, v)
    for op in (("es", 0), ("ei", 0), ("ek", 0, 0), ("eu", 0), ("ew", 0),
               ("et", 0), ("ex",), ("er", 0), ("ev", 0, 1)):
        s.op(*op)
    for i in range(8):
        s.op("eo", i, i)
    for k in range(16):
        s.op("ec", k, 0, 0, 0)


def base(ch, fill="00", seed=None):
    s = Script(ch)
    reset_vars(s)
    s.load_all()
    s.setup(fill, seed)
    return s


def s_skipfe(ch):
    """StartSkipFEGame over the SkipFE words: the disc's, then the race
    sizes, the cops, the traffic, Be A Cop, the difficulty, the default
    cars, the POV, the seed and the game flow's state."""
    s = base(ch)
    s.op("SS", 0)
    s.op("v", "nai", 3)
    s.op("v", "cops", 2)
    s.op("v", "density", fbits(0.5))
    s.op("SS", 0)
    s.op("v", "np", 2)
    s.op("v", "nai", 7)                 # cut to six by StartRace
    s.op("v", "cops", 4)                # and none left by SetupCarsForRace
    s.op("v", "track", 21)
    s.op("SS", 0)
    s.op("v", "maxai", 2)
    s.op("v", "cops", 3)
    s.op("SS", 0)
    s.op("v", "maxai", 7)
    s.op("v", "beacop", 1)
    s.op("v", "track", 61)
    s.op("v", "diff", 2)
    s.op("v", "dp1type", 13)
    s.op("v", "dp2type", 45)
    s.op("v", "pov", 0x103)
    s.op("v", "np", 1)
    s.op("v", "nai", 4)
    s.op("SS", 0)
    s.op("v", "track", 23)              # point to point
    s.op("v", "state", 3)
    s.op("v", "diff", 1)
    s.op("v", "laps", 0)
    s.op("v", "racetype", 4)
    s.op("v", "heli", 0)
    s.op("v", "spikes", 7)
    s.op("v", "tickets", 0)
    s.op("v", "roadblocks", 5)
    s.op("v", "new624", 0)
    s.op("v", "oncoming", fbits(0.75))
    s.op("cp")
    s.game(1, 2)
    s.op("SS", 1)
    s.op("v", "beacop", 0)
    s.op("v", "track", 12)
    for seed in (1, 0x80000000, 0xdeadbeef):
        s.op("v", "seed", seed)
        s.op("R")
        s.op("SS", 0)
    s.op("v", "np", 0)
    s.op("v", "nai", 5)
    s.op("SS", 0)
    return s.ops


def s_gametypes(ch):
    """StartRace under every game type, on Fred and on a second database
    that differs from it, with the race event's answers varied."""
    s = base(ch)
    s.op("cp")
    s.ride(1, 0, 0, 13, 2)
    s.ride(1, 1, 0, 45, 3)
    s.fr(1, NUM_PLAYERS, 4, 2)
    s.fr(1, DISPLAY, 4, 0x04030201)
    s.fr(1, DISPLAY + 4, 4, 0x08070605)
    s.gender(1, 0, 5)
    s.gender(1, 1, 6)
    s.fr(0, NUM_PLAYERS, 4, 1)
    for g in range(11):
        s.ride(0, 0, g, (5 + 4 * g) % 46, 1, g & 1)
        s.ride(0, 1, g, (11 + 4 * g) % 46, 2)
        s.ride(1, 0, g, (21 + 2 * g) % 46, 1)
    s.op("ev", 3, 4)
    s.op("ei", 5)
    s.op("ek", 3, 4)
    s.op("es", 1)
    s.op("ew", 77)
    s.op("er", 3)
    s.fr(0, CURRENT_EVENT, 4, 6)
    s.fr(1, CURRENT_EVENT, 4, 9)
    for k in (0, 1):
        for g in range(11):
            s.op("R")
            s.rp("np", 1 + (g & 1))
            s.rp("nai", 3)
            s.rp("cops", g % 3)
            s.rp("oppstr", g % 3)
            s.rp("density", 0.25 if g & 2 else 0.0)
            s.game(0, g)
            s.game(1, (g + 5) % 11)
            s.op("SR", k)
    # The event's other types and answers.
    s.game(0, 4)
    s.game(1, 8)
    for typ, status, idx, tree in ((4, 2, 1, 1), (4, 0, 0, 0), (3, 2, 0, 1),
                                   (3, 2, -3, 0), (1, 2, 7, 1),
                                   (4, 2, 3, 1)):
        s.op("ev", typ, 3)
        s.op("es", status)
        s.op("ei", idx)
        s.op("et", tree)
        s.op("eu", 6)
        for k in (0, 1):
            s.op("R")
            s.rp("np", 2)
            s.rp("nai", 2)
            s.op("SR", k)
    # Knocked out drivers, the replay, the frontend's state, a dash, and a
    # tree for the games that do not ask for it.
    s.op("et", 1)
    s.op("ee", 0, 3)
    s.op("ee", 101, 2)
    s.op("ee", 102, 0)
    s.op("v", "replay", 1)
    s.op("v", "state", 3)
    s.ride(0, 0, 8, 21, 2, 1)
    s.ride(0, 0, 9, 23, 1, 0)
    for g in (4, 8, 9, 0):
        s.game(0, g)
        s.game(1, g)
        for k in (0, 1):
            s.op("R")
            s.rp("np", 2)
            s.rp("nai", 4)
            s.rp("cops", 1)
            s.rp("p2p", 0)
            s.rp("track", 13 if g == 8 else 22)
            s.op("SR", k)
    # The AI count against MaximumNumAICars and the players.
    s.op("ex")
    s.op("v", "replay", 0)
    s.game(0, 1)
    s.game(1, 1)
    for maxai, np_, nai in ((7, 1, 9), (3, 1, 5), (0, 2, 4), (8, 2, 8),
                            (-1, 1, 0)):
        s.op("v", "maxai", maxai)
        s.op("R")
        s.rp("np", np_)
        s.rp("nai", nai)
        s.op("SR", 0)
    return s.ops


def s_ai(ch):
    """SetupCarsForRace's racers: the skill draw, a forced type, the
    player's type, an event's opponents, the demo's random class, two
    players of other classes, cars taken away, and the eliminated."""
    s = base(ch, fill="00", seed=0x2468ace1)
    for oppstr in (0, 1, 2):
        for cops in (0, 2):
            s.op("R")
            s.rp("np", 1)
            s.rp("nai", 7)
            s.rp("cops", cops)
            s.rp("oppstr", oppstr)
            s.op("SC", 0)
    s.op("R")
    s.rp("nai", 5)
    s.op("v", "force", 13)
    s.op("SC", 0)
    s.op("v", "force", 4)               # a cop car
    s.op("SC", 0)
    s.op("v", "force", -1)
    s.rp("oppsel", 1)
    s.op("SC", 0)
    s.ride(0, 0, 0, 9, 3)
    s.op("SC", 1)
    s.op("cp")
    s.op("SC", 1)
    # An event's opponents.
    s.rp("oppsel", 2)
    s.op("et", 1)
    for i, idx in enumerate((3, 0, 7, 2, 2, 15, 1, 4)):
        s.op("eo", i, idx)
    for k, rec in enumerate(((13, 2, 3), (45, 0xff, 9), (37, 4, 0),
                             (21, 0x80, 0xff), (9, 1, 5), (0, 3, 1),
                             (35, 0xfe, 2), (41, 7, 8))):
        s.op("ec", k, *rec)
    s.op("ec", 15, 47, 0xff, 4)
    s.rp("nai", 7)
    s.op("SC", 0)
    s.op("SC", 1)
    s.rp("oppsel", 0)
    s.op("et", 0)
    # The demo picks a class at random.
    s.rp("aidemo", 1)
    s.rp("np", 2)
    for seed in (5, 6, 7):
        s.op("rq", "s", seed)
        s.op("SC", 0)
    s.rp("aidemo", 0)
    # Two players, the slower second; then the first.
    s.ride(0, 0, 0, 37, 1)
    s.ride(0, 1, 0, 9, 2)
    s.op("SC", 0)
    s.ride(0, 0, 0, 7, 1)
    s.ride(0, 1, 0, 39, 2)
    s.gender(0, 0, 1)
    s.gender(0, 1, 0)
    s.op("SC", 0)
    s.gender(0, 0, 0xff)
    s.gender(0, 1, 2)
    s.op("SC", 0)
    # No class 1 car left with geometry: the second draw takes any class.
    for t in (17, 23, 39, 45, 47):
        s.car(t, GEOMETRY, 1, 0)
    s.ride(0, 0, 0, 7, 1)
    s.ride(0, 1, 0, 2, 2)
    s.op("SC", 0)
    # A class with weights that do not add up.
    s.carf(2, LOCATION_PROB, 0.0)
    s.carf(33, LOCATION_PROB, 0.25)
    s.carf(0, LOCATION_PROB, -1.0)
    s.op("SC", 0)
    # Knocked out in an event: the counts and the ranks.
    s.game(0, 9)
    s.op("ee", 1, 4)
    s.op("ee", 100, 2)
    s.op("ee", 103, 0)
    s.op("ee", 104, 7)
    s.op("SC", 0)
    s.op("SC", 0)
    s.game(0, 0)
    s.op("ex")
    # Traffic, and none of it available.
    s.rp("density", 0.5)
    s.rp("track", 31)
    s.op("SC", 0)
    s.rp("density", -0.0005)
    s.op("SC", 0)
    s.rp("density", -0.25)
    for t in (50, 53, 58):
        s.car(t, NUM_SKINS, 1, 0)
    s.op("SC", 0)
    # More drivers than the grid: the cops cut, then none.
    s.rp("np", 2)
    s.rp("nai", 6)
    s.rp("cops", 3)
    s.op("SC", 0)
    s.rp("nai", 7)
    s.op("SC", 0)
    return s.ops


def s_cops(ch):
    """The cops: the cop car nearest the slowest class, the cop
    character by the track, and no cop car at all."""
    s = base(ch, seed=99)
    s.ride(0, 0, 0, 5, 1)               # class 0
    for track, cops in ((11, 2), (21, 3), (61, 1), (34, 4)):
        s.op("R")
        s.rp("track", track)
        s.rp("cops", cops)
        s.rp("nai", 2)
        s.op("SC", 0)
    s.track(21, COP_HASH, 4, 0)         # "Cop"
    s.track(22, COP_HASH, 4, bhash(b"Liv"))
    s.track(23, COP_HASH, 4, bhash(b"Nobody"))
    for track in (21, 22, 23):
        s.op("R")
        s.rp("track", track)
        s.rp("cops", 2)
        s.rp("beacop", 1)
        s.op("SC", 0)
    s.rp("np", 2)
    s.op("SC", 0)
    s.rp("np", 1)
    s.rp("beacop", 0)
    # Classes moved so that the nearest is not the first.
    s.car(32, CAR_CLASS, 1, 3)
    s.car(31, CAR_CLASS, 1, -2)
    s.car(33, CAR_CLASS, 1, 6)
    s.ride(0, 0, 0, 15, 1)              # class 3
    s.op("SC", 0)
    s.ride(0, 0, 0, 35, 1)              # class 4
    s.op("SC", 0)
    s.car(4, USAGE, 4, 0)
    s.car(34, GEOMETRY, 1, 0)
    s.op("SC", 0)
    for t in (31, 32, 33):
        s.car(t, USAGE, 4, 2)
    s.op("SC", 0)
    return s.ops


def s_helpers(ch):
    """The helpers called alone: the ride draw, the skins, the character
    and cop picks, the record indexes and times, and RaceParameters'
    driver methods."""
    s = base(ch, seed=0x1234)
    # GenerateRandomRideInfo at each location, usage and class.
    for track in (11, 25, 36, 44, 52, 63, 5, 75):
        s.rp("track", track)
        s.op("LI")
        for usage in (0, 1, 2, 3):
            for cls in (-1, 0, 1, 2, 3, 4, 5):
                s.op("rd", -1, 0x11, 0x22, 0x33, 0x44)
                s.op("GR", usage, cls)
    s.rp("track", 11)
    s.carf(13, LOCATION_PROB, 0.0005)
    s.carf(35, LOCATION_PROB, 3.0)
    s.carf(37, LOCATION_PROB, -2.5)
    s.carf(41, LOCATION_PROB, 0.5)
    for k in range(12):
        s.op("GR", 0, 4)
    s.carf(43, LOCATION_PROB, -0.5)
    s.carf(35, LOCATION_PROB, 0.0)
    s.carf(41, LOCATION_PROB, 0.0)
    s.op("GR", 0, 4)
    s.carf(37, LOCATION_PROB, 0.0)
    s.carf(43, LOCATION_PROB, 0.0)
    s.op("GR", 0, 4)                    # 0.0005 in all
    s.carf(13, LOCATION_PROB, -0.0008)
    s.op("GR", 0, 4)
    s.carf(13, LOCATION_PROB, 0.0015)
    s.op("GR", 0, 4)
    # GetRandomSkin: a cop by language, no skins, a negative count.
    for lang in (0, 1, 2):
        s.op("v", "lang", lang)
        for t in (4, 31, 13, 57):
            s.op("GS", t)
    s.car(13, NUM_SKINS, 1, 0)
    s.op("GS", 13)
    s.car(15, NUM_SKINS, 1, 10)
    for k in range(10):
        s.car(15, SKINS + k, 1, 0x10 + k)
    for k in range(6):
        s.op("GS", 15)
    s.op("v", "lang", 0)
    # The character list.
    for lst, n, g in (((0, 1, 2, 3, 4, 5, 6, 7), 8, -1),
                      ((0, 1, 2, 3, 4, 5, 6, 7), 8, 0),
                      ((0, 1, 2, 3, 4, 5, 6, 7), 8, 1),
                      ((-1, -1, 2, 3, 4, 5, 6, 7), 8, 0),
                      ((-1, 1, -1, 8, 9, 0, 6, 7), 8, 1),
                      ((1, 0, 4, 5, -1, -1, -1, -1), 4, 1),
                      ((-1, -1, -1, -1, -1, -1, -1, -1), 8, -1),
                      ((3, 2, 1, 0, 7, 6, 5, 4), 0, -1),
                      ((9, 8, 1, 0, 7, 6, 5, 4), 3, 0),
                      ((2, 3, 4, 5, 6, 7, 8, 9), 8, 2)):
        s.op("ls", *lst)
        s.op("PN", n, g)
        s.op("PN", n, g)
    # The cop character by track.
    s.track(12, COP_HASH, 4, 0)
    s.track(14, COP_HASH, 4, bhash(b"FatCop"))
    s.track(15, COP_HASH, 4, bhash(b"Nobody"))
    for track in (11, 12, 14, 15, 21):
        s.rp("track", track)
        s.op("PK")
    # Drivers in the table, by hand.
    s.op("rq", "n", 0)
    for u, ty, rt, sk, ch_, skill, start in (
            (0, 1, 37, 1, 0, -2, 3), (100, 2, 13, 2, 3, 4, 0),
            (101, 2, 9, 4, 5, 1, 0), (50, 3, 51, 0xff, -1, -1, 0),
            (10, 4, 33, 1, 8, -1, 0), (1, 1, 7, 3, 1, -2, 5),
            (102, 2, 15, 1, 12, 2, 0), (103, 2, 41, 2, -1, 0, 0)):
        s.op("rd", rt, 0, sk, 0, 1 if ty == 1 else 0)
        s.op("DC", u, ty, ch_, skill, start)
        s.op("AD")
    for t, sk in ((37, 1), (37, 2), (13, 2), (9, 4), (51, 3), (51, -1),
                  (99, 1), (-1, 0), (2, 6), (2, 5)):
        s.op("AT", t)
        s.op("AC", t, sk)
    s.skin(0, 40, 4, 8)                 # type 7 skin 2 takes 37's paint
    s.op("AC", 7, 2)
    s.op("NS", 0)                       # the table's first entry for all
    s.op("AC", 9, 4)
    s.op("NS", 235)
    for t in (13, 9, 37, 4, 51):
        s.op("PU", t)
    for n in (0, 1, 100, 103, 50, 10, 7, -1, 104):
        s.op("FD", n)
    s.op("EL", 100, 3)
    s.op("EL", 100, 5)                  # already out
    s.op("EL", 1, 2)
    s.op("EL", 50, 1)
    s.op("EL", 103, -1)                 # a rank below 0 counts as in
    s.op("EL", 103, 0)
    s.op("EL", 77, 1)
    s.op("AT", 13)
    s.op("AC", 13, 2)
    s.op("RE")
    s.op("EL", 101, 4)
    s.op("dt", 4, "rank", -3)
    s.op("RE")
    # The model count.
    for rt, sk, vd in ((37, 1, 0), (37, 1, 1), (21, 1, 0), (50, 1, 0),
                       (0, 0, 0), (63, 0, 0)):
        s.op("rd", rt, 0, sk, 0, vd)
        s.op("TM")
    s.op("rq", "n", 13)
    s.op("dt", 8, "rt", 21)
    s.op("dt", 9, "rt", 23)
    s.op("dt", 10, "rt", 25)
    s.op("dt", 11, "rt", 29)
    s.op("dt", 12, "rt", 35)
    s.op("dt", 12, "rv", 1)
    s.op("dt", 13, "rank", 2)
    for rt in (37, 43, 21, 47, 57):
        s.op("rd", rt, 0, 1, 0, 0)
        s.op("TM")
    s.op("dt", 13, "rank", 0)
    s.op("rd", 47, 0, 1, 0, 0)
    s.op("TM")
    s.op("dt", 2, "rank", 1)
    s.op("TM")
    s.op("rq", "n", 14)
    s.op("AD")
    s.op("rq", "n", 8)
    # RideInfo::Init.
    s.op("RI", 21, 300, 1, 0)
    s.op("RI", -5, -2, 0x101, 7)
    # The record indexes.
    for t in (11, 12, 14, 21, 23, 66, 36, 45):
        s.op("hu", t)
    s.track(14, IS_VALID, 1, 0)
    s.op("hu", 14)
    s.track(14, IS_VALID, 1, 1)
    for laps in range(-1, 13):
        s.op("hl", laps)
    for t, c, d, laps in ((11, 0, 0, 1), (12, 4, 1, 10), (24, 2, 7, 3),
                          (61, 3, -1, 9), (36, 1, 0, 2)):
        s.op("ht", t, c, d, laps)
        s.op("hp", t, c, d)
    # The record times, on both databases.
    s.op("cp")
    for g in (0, 3, 4, 5, 7):
        s.ride(1, 0, g, 5, 1)
        s.ride(1, 1, g, 15, 1)
    s.op("hs", 0)
    s.op("hs", 1)
    s.fr(1, HIGH_SCORES + 8 * 33, 4, 0x55555555)
    for track, laps, d in ((11, 3, 0), (12, 0, 1), (21, 10, 0), (36, 3, 0),
                           (66, 7, 2)):
        s.rp("track", track)
        s.rp("laps", laps)
        s.rp("dir", d)
        for k in (0, 1):
            for g in (0, 3, 5):
                s.game(0, g)
                s.game(1, 7 - g)
                s.op("RT", k, 0)
                s.op("RT", k, 1)
        s.rp("np", 2)
        s.op("RA", 1)
        s.rp("np", 0)
        s.op("RA", 0)
        s.rp("np", 1)
    return s.ops


def s_positions(ch):
    """CalculateStartingPositions over tables built by hand: positions
    already held, the eliminated, cops and traffic, ties, and a full
    grid."""
    s = base(ch)
    rows = ((0, 1, 37, 0), (100, 2, 13, 0), (101, 2, 45, 0),
            (102, 2, 9, 2), (50, 3, 51, 0), (10, 4, 33, 0),
            (103, 2, 13, 0), (1, 1, 21, 0), (104, 2, 23, 7),
            (105, 2, 0, 0), (106, 2, 41, 0), (107, 5, 4, 0))
    for game in (0, 4):
        s.game(0, game)
        s.op("rq", "n", 0)
        for u, ty, rt, start in rows:
            s.op("rd", rt, 0, 1, 0, 0)
            s.op("DC", u, ty, 0, 0, start)
            s.op("AD")
        s.op("CP", 0)
        s.op("CP", 0)
    s.game(0, 0)
    s.op("dt", 3, "rank", 2)
    for i in range(12):
        s.op("dt", i, "start", 0)
    s.op("dt", 9, "type", 0)
    s.op("dt", 10, "type", -1)
    s.op("CP", 0)
    s.carf(41, TORQUE + 12, 9999.0)
    s.carf(45, MASS, 0.5)
    for i in range(12):
        s.op("dt", i, "start", 0)
    s.op("CP", 1)
    s.op("rq", "n", 3)
    s.op("CP", 0)
    return s.ops


def s_patterns(ch):
    """The race start over a fill that differs from the defaults, so the
    stale bytes of the drivers' table show."""
    s = base(ch, fill="a5", seed=0x0badf00d)
    for i in range(14):
        s.op("dt", i, "rank", 0)
    s.op("dt", 5, "rank", 3)
    s.op("dt", 13, "rank", 1)
    s.rp("np", 1)
    s.rp("nai", 7)
    s.rp("cops", 0)
    s.op("SC", 0)
    s.op("F", "5c")
    s.op("SF")
    s.op("I")
    s.op("R")
    s.rp("density", 1.0)
    s.op("SR", 0)
    s.op("SS", 0)
    return s.ops


def s_holes(ch):
    """What the mutation pass found the others leave alone: the game-type
    tests called by themselves, a grid of exactly nine, one cop at the
    strength whose two skill tables part, the table's last car and a car
    with no skins in a draw, an invalid track that still has a high score
    index, a torque curve that peaks at its last point, totals that
    differ between the two databases, a NumPlayerCars below 0, no driver
    at all before the cops, two cop cars that tie, a cop car with no
    geometry, one AI racer over the limit, a traffic car and a driver
    knocked out at rank 1 in the model count, and a driver past the
    table's end."""
    s = base(ch, seed=0x2468)
    # UseTheRaceEvent, IsChallengeGame and IsEventGame alone: StartRace
    # tests GameType 2 beside IsChallengeGame, so it cannot tell 2 apart.
    s.op("cp")
    for g in range(-1, 12):
        s.game(0, g)
        s.op("GT", 0)
    s.game(1, 9)
    s.op("GT", 1)
    s.game(0, 0)
    # Players, AI and cops at exactly nine: the cops are cut to none.
    s.rp("np", 1)
    s.rp("nai", 7)
    s.rp("cops", 1)
    s.op("SC", 0)
    # One cop and five AI at OpponentStrength 2, the only strength whose
    # skill table with cops differs from the one without.
    for seed in (1, 77, 0x13579bdf):
        s.op("v", "seed", seed)
        s.op("R")
        s.rp("oppstr", 2)
        s.rp("nai", 5)
        s.rp("cops", 1)
        s.op("SC", 0)
    # Car 63, the table's last, with a weight the disc does not give it: as
    # traffic, then as a class 4 racer. Then car 13 with a weight and no
    # skins, which the draw passes over.
    s.op("R")
    s.rp("track", 11)
    s.carf(63, LOCATION_PROB, 5.0)
    for k in range(6):
        s.op("GR", 2, -1)
    s.car(63, USAGE, 4, 0)
    for k in range(6):
        s.op("GR", 0, 4)
    s.car(63, USAGE, 4, 2)
    s.carf(63, LOCATION_PROB, 0.0)
    s.car(13, NUM_SKINS, 1, 0)
    s.carf(13, LOCATION_PROB, 50.0)
    for k in range(6):
        s.op("GR", 0, 4)
    s.car(13, NUM_SKINS, 1, 8)
    s.carf(13, LOCATION_PROB, 1.0)
    # The torque curve's last point the highest of two AI racers'.
    s.op("rq", "n", 0)
    for u, rt in ((100, 41), (101, 13)):
        s.op("rd", rt, 0, 1, 0, 0)
        s.op("DC", u, 2, 0, 0, 0)
        s.op("AD")
    s.carf(41, TORQUE + 28, 1000.0)
    s.carf(13, TORQUE + 32, 1000000.0)
    s.op("CP", 0)
    s.op("rq", "n", 0)
    # The records: each database's totals its own, and an invalid track
    # that keeps a high score index.
    s.op("cp")
    s.op("hs", 0)
    s.op("hs", 1, 1)
    s.track(14, HIGH_SCORE_INDEX, 2, 9)
    for valid in (0, 1):
        s.track(14, IS_VALID, 1, valid)
        s.op("hu", 14)
        for track, laps in ((14, 3), (11, 3), (21, 10)):
            s.rp("track", track)
            s.rp("laps", laps)
            s.op("RT", 0, 0)
            s.op("RT", 1, 0)
    # A NumPlayerCars below 0 and no one else: the count puts it back to 0,
    # and with no driver the slowest class stays 5, which car 31 is moved
    # to.
    s.op("R")
    s.rp("density", 0.0)
    s.rp("np", -1)
    s.rp("nai", 0)
    s.rp("cops", 1)
    s.car(31, CAR_CLASS, 1, 5)
    s.op("SC", 0)
    s.car(31, CAR_CLASS, 1, 3)
    # A class 2 player, then car 34, the class 2 cop, with no geometry: 31
    # and 33 tie a class away, and the first of them wins.
    s.op("R")
    s.rp("density", 0.0)
    s.ride(0, 0, 0, 11, 1)
    s.rp("nai", 2)
    s.rp("cops", 1)
    s.op("SC", 0)
    s.car(34, GEOMETRY, 1, 0)
    s.op("SC", 0)
    s.car(34, GEOMETRY, 1, ord("C"))
    # One AI racer more than MaximumNumAICars, with room on the grid.
    s.op("v", "maxai", 3)
    s.op("R")
    s.rp("np", 1)
    s.rp("nai", 4)
    s.op("SR", 0)
    s.op("v", "maxai", 7)
    # Six drivers by hand, one of them traffic, for the model count: then
    # the sixth a racer knocked out at rank 1, then back in; and a driver
    # left past the table's end.
    s.op("rq", "n", 0)
    for u, ty, rt in ((0, 1, 13), (100, 2, 45), (101, 2, 37), (102, 2, 21),
                      (103, 2, 9), (50, 3, 50)):
        s.op("rd", rt, 0, 1, 0, 0)
        s.op("DC", u, ty, 0, 0, 0)
        s.op("AD")
    s.op("rd", 13, 0, 1, 0, 0)
    s.op("TM")
    s.op("dt", 5, "rt", 41)
    s.op("dt", 5, "type", 2)
    s.op("dt", 5, "rank", 1)
    s.op("TM")
    s.op("dt", 5, "rank", 0)
    s.op("TM")
    s.op("rq", "n", 5)
    s.op("FD", 50)
    s.op("rq", "n", 0)
    return s.ops


def s_quickrace(ch):
    """StartQuickRace (0x00216c18) as the Mode Selects call it: Hot
    Pursuit's and World Racing's over gearbox words and seeds, the cops word
    at odd values; the config file's track with the default car, track 0,
    one the table lacks (its record is read at NULL) and a point to point;
    the pick alone over seeds; GetCarStatus; and quick races over a filled
    database."""
    s = base(ch)
    for cops, trans, seed in ((1, 0, 1), (0, 1, 2), (1, -1, 0xdeadbeef),
                              (0, 2, 0x80000000), (-1, 0, 7),
                              (2, 0x100, 12345), (0, 0, 99), (1, 1, 31337)):
        s.op("v", "seed", seed)
        s.fr(0, COPS_ON, 4, cops)
        s.op("QR", trans)
    # Twenty more draws of the random ride.
    for i in range(20):
        s.op("v", "seed", (i * 0x2545f491 + 3) & M32)
        s.op("QR", 0)
    s.op("v", "track", 21)
    s.op("QR", 0)
    s.op("v", "dp1type", 13)
    s.op("v", "dp1skin", 3)
    s.fr(0, COPS_ON, 4, 0)
    s.op("QR", 1)
    for track in (23, 0, 99, 66):
        s.op("v", "track", track)
        s.op("QR", 0)
    s.op("v", "track", -1)
    for i in range(24):
        s.op("v", "seed", (i * 0x9e3779b9 + 1) & M32)
        s.op("PT")
    for t in (0, 1, 13, 37, 63, 64, 70):
        s.op("CS", t)
    for fill, seed in (("ff", 5), ("5a", 0x1234)):
        s.setup(fill, seed)
        s.op("QR", 3)
        s.fr(0, COPS_ON, 4, 0)
        s.op("QR", 0)
    return s.ops


def s_tracklocks(ch):
    """The express game's pick under the event trees: one, three and five
    trees, each setting tracks aside as rewards (the answers any word) and
    unlocking some of them, then none again. IsTrackUnlocked and the two
    loops alone over tracks from -1 to 200 both ways, the pick over seeds
    and a quick race under each."""
    rnd = random.Random(0x216aa8)
    s = base(ch)
    for n in (1, 3, 5, 0):
        s.op("tn", n)
        for tree in range(n):
            for track in range(-2, 72):
                for d in (0, 1):
                    if rnd.random() < 0.25:
                        s.op("ta", tree, track, d, rnd.choice(
                            (1, 2, -1, 0x100, 0x80000000)))
                    if rnd.random() < 0.5:
                        s.op("tu", tree, track, d, rnd.choice(
                            (1, 3, -1, 0x10000)))
        for track in (-1, 0, 1, 5, 17, 33, 54, 65, 70, 127, 200):
            for d in (0, 1):
                s.op("IU", track, d)
        for i in range(6):
            s.op("v", "seed", rnd.getrandbits(32))
            s.op("PT")
        s.fr(0, COPS_ON, 4, n & 1)
        s.op("QR", 0)
    return s.ops


def script():
    ch = globalb_chunks()
    return [s_skipfe(ch), s_gametypes(ch), s_ai(ch), s_cops(ch),
            s_helpers(ch), s_positions(ch), s_patterns(ch), s_holes(ch),
            s_quickrace(ch), s_tracklocks(ch)]


def encode(scenarios):
    lines = []
    for i, s in enumerate(scenarios):
        lines.append("B %d" % i)
        lines += s
    return NL.join(lines) + NL


# ================================================================ the model

DT_FIELDS = {
    "rank": (0, 1), "uniq": (1, 1), "char": (2, 1), "skill": (3, 1),
    "start": (4, 1), "type": (8, 4), "rt": (12, 4), "ri": (16, 1),
    "rs": (17, 1), "rd": (18, 1), "rv": (19, 1),
}


class Model(object):
    def __init__(self):
        self.out = []
        self.quiet = False
        self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        e = self.e
        stubs = {
            IS_CAR_UNLOCKED: lambda e: 0,
            TRANSLATE: lambda e: NOT_TRANSLATED,
            AUDIO_DEFAULTS: self.audio_defaults,
            FAKE_KO: lambda e: self.say("fake %s" % self.flabel(e.reg[4])),
            EV_STATUS: lambda e: self.answer("st -> %d", self.status),
            EV_RESET: lambda e: self.say("rs"),
            EV_RACE_INDEX: lambda e: self.answer("ri -> %d", self.race_index),
            SET_RACE: self.set_race,
            KO_STATE: lambda e: KO,
            KO_START: self.ko_start,
            TOURNAMENT: lambda e: TS,
            USER_RANK: lambda e: self.answer("ur -> %d", self.user_rank),
            EVENT_TREE: lambda e: TREE if self.tree else 0,
            EVENT_NUMBER: self.event_number,
            EVENT_WORD: lambda e: self.answer("ew -> %d", self.word),
            ELIMINATED: self.eliminated,
            RACER_INDEX: lambda e: s32(e.reg[5]),
            KO_RANK: self.ko_rank,
            EV_POSITIONS: lambda e: self.say("esp"),
            MULTI_TRACK: lambda e: self.say("ms %s"
                                            % self.flabel(e.reg[4])),
            REPLAY_RESTORE: lambda e: self.say("dr"),
            REPLAY_UNLOAD: lambda e: self.say("du"),
            REWARD_CARS: lambda e: self.answer("rw -> %d", self.reward),
            CHANGE_FLOW: lambda e: self.say("cg %d %d" % (
                s32(e.reg[4]), s32(e.reg[5]))),
            STOP_MOVIE: lambda e: self.say("sm"),
            TREE_REWARD: lambda e: self.tree_answer("ta", self.reward_tab),
            TREE_UNLOCKED: lambda e: self.tree_answer("tu",
                                                      self.unlocked_tab),
            BMALLOC: lambda e: e.alloc(max(s32(e.reg[4]), 0) + 16, align=16),
            BFREE: lambda e: None,
        }
        for a, fn in stubs.items():
            e.stub(a, fn)
        self.status = self.race_index = self.user_rank = 0
        self.word = self.reward = 0
        self.tree = 0
        self.reward_tab = {}
        self.unlocked_tab = {}
        self.ko = [0, 0]
        self.elim = {}
        self.shown_fred = bytes(FRED_SIZE)
        self.shown_alt = bytes(FRED_SIZE)
        self.shown_rp = bytes(RP_COMMON)
        self.shown_tail = ""
        self.shown_di = [""] * NUM_DI
        self.shown = {}
        e.put32(TREE + 52, OPP)
        self.set_trees(0)

    def emit(self, s):
        if not self.quiet:
            self.out.append(s)

    # ---- the stubs -------------------------------------------------------

    def say(self, s):
        self.emit(s)
        return None

    def answer(self, fmt, v):
        self.emit(fmt % v)
        return v

    def flabel(self, a):
        a &= M32
        return {FRED: "Fred", ALT: "alt"}.get(a, "?")

    def audio_defaults(self, e):
        a = e.reg[4] & M32
        e.write(a, bytes((i * 7) & 0xff for i in range(176)))
        return None

    def set_race(self, e):
        idx = (s32(e.reg[4]) - (EV + 212)) // 4
        self.emit("sr %d %s" % (idx, "RP" if e.reg[5] & M32 == RP else "?"))
        return None

    def ko_start(self, e):
        p = s32(e.reg[5])
        v = self.ko[p] if p in (0, 1) else 0
        self.emit("ko %d -> %d" % (p, v))
        return v

    def tree_answer(self, tag, tab):
        e = self.e
        tree = ((e.reg[4] & M32) - TREES) // 16
        track, d = s32(e.reg[5]), s32(e.reg[6])
        v = tab.get((tree, track & 0xff, d & 1), 0)
        self.emit("%s %d %d %d -> %d" % (tag, tree, track, d, v))
        return v

    def set_trees(self, n):
        """The bList at gp-16712 over n nodes: next at 0, prev at 4."""
        e = self.e
        nodes = [TREES + 16 * i for i in range(n)]
        ring = [TREE_LIST] + nodes
        for i, a in enumerate(ring):
            e.put32(a, ring[(i + 1) % len(ring)])
            e.put32(a + 4, ring[i - 1])

    def event_number(self, e):
        self.emit("en %d" % s32(e.reg[5]))
        return EVT

    def eliminated(self, e):
        n = s32(e.reg[5])
        r = int(n in self.elim)
        self.emit("de %d -> %d" % (n, r))
        return r

    def ko_rank(self, e):
        n = s32(e.reg[5])
        r = self.elim.get(n, 0)
        self.emit("rk %d -> %d" % (n, r))
        return r

    # ---- the prints ------------------------------------------------------

    def label(self, a):
        a &= M32
        if a == 0:
            return "NULL"
        for k in range(4):
            base = SLOT_BASE + SPAN * k
            if base <= a < base + SPAN:
                return "k%d+%d" % (k, a - base)
        if CARS <= a < CARS + 64 * CAR_REC:
            return "cars+%d" % (a - CARS)
        if TRK <= a < TRK + SPAN:
            return "trk+%d" % (a - TRK)
        if DIT <= a < DIT + DI_SIZE * NUM_DI and (a - DIT) % DI_SIZE == 0:
            return "DIT[%d]" % ((a - DIT) // DI_SIZE)
        return "?"

    def rows(self, tag, cur, shown, width):
        out = bytearray(shown)
        for off in range(0, len(cur), 32):
            c = cur[off:off + 32]
            if c != shown[off:off + 32]:
                self.emit("%s %0*x %s" % (tag, width, off, c.hex()))
                out[off:off + len(c)] = c
        return bytes(out)

    def di_text(self, a):
        e = self.e
        b = e.read(a, DI_SIZE)
        elim, uniq, char, skill, start = struct.unpack_from("<5b", b, 0)
        return "%d %d %d %d %d %d %s %s" % (
            elim, uniq, char, skill, start, s32(e.u32(a + 8)),
            b[12:20].hex(), self.label(e.u32(a + 20)))

    def line(self, key, s):
        if self.shown.get(key) != s:
            self.emit(s)
            self.shown[key] = s

    def print_state(self):
        e = self.e
        self.shown_fred = self.rows("f", e.read(FRED, FRED_SIZE),
                                    self.shown_fred, 5)
        self.shown_alt = self.rows("a", e.read(ALT, FRED_SIZE),
                                   self.shown_alt, 5)
        self.shown_rp = self.rows("r", e.read(RP, RP_COMMON), self.shown_rp,
                                  3)
        tail = e.u32(RP + 772)
        self.line("tail", "rp %s %d %08x %08x" % (
            "DIT" if tail == DIT else self.label(tail),
            s32(e.u32(RP + 776)), e.u32(RP + 780), e.u32(RP + 784)))
        for i in range(NUM_DI):
            s = "d %d %s" % (i, self.di_text(DIT + DI_SIZE * i))
            if s != self.shown_di[i]:
                self.emit(s)
                self.shown_di[i] = s
        self.line("y", "y " + self.di_text(DI_SCR))
        self.line("x", "x " + e.read(RIDE, 8).hex())
        self.line("l", "l " + " ".join(
            "%d" % s32(e.u32(LIST + 4 * i)) for i in range(8)))
        ev = e.read(EV + 106, 18)
        self.line("e", "e %d %d %d %d" % (
            struct.unpack_from("<h", ev, 0)[0],
            struct.unpack_from("<h", ev, 6)[0],
            struct.unpack_from("<h", ev, 12)[0],
            struct.unpack_from("<i", ev, 14)[0]))
        self.line("g", "g seed=%08x" % e.u32(SEED))

    # ---- the ops ---------------------------------------------------------

    def call(self, addr, *args):
        # Sign-extended, as the EE's 64-bit registers hold an int.
        return self.e.call(addr, *[s32(a & M32) for a in args],
                           limit=200000000)

    def fill(self, b):
        e = self.e
        for a, n in ((FRED, FRED_SIZE), (ALT, FRED_SIZE), (RP, 788),
                     (DIT, DI_SIZE * NUM_DI), (RIDE, 8), (DI_SCR, DI_SIZE),
                     (LIST, 32)):
            e.write(a, bytes([b]) * n)
        for off, n in ((106, 2), (112, 2), (118, 2), (120, 4)):
            e.write(EV + off, bytes([b]) * n)
        self.quiet = True
        self.print_state()
        self.quiet = False

    def put(self, a, n, v):
        self.e.write(a, (v & ((1 << (8 * n)) - 1)).to_bytes(n, "little"))

    def fk(self, k):
        return ALT if int(k) else FRED

    def run(self, scenarios):
        e = self.e
        for n, sc in enumerate(scenarios):
            self.emit("B %d" % n)
            for ln in sc:
                self.emit("> " + ln[:40])
                t = ln.split()
                op, a = t[0], t[1:]
                if op == "F":
                    self.fill(int(a[0], 16))
                    continue
                elif op == "K":
                    base = SLOT_BASE + SPAN * int(a[0])
                    e.write(base, bytes(SPAN))
                    e.write(base, bytes.fromhex(a[1]))
                    continue
                elif op == "L":
                    k = int(a[0])
                    ret = self.call(LOADER_CHAR, SLOT_BASE + SPAN * k)
                    self.emit("L %d -> %d" % (k, ret))
                elif op == "KC":
                    e.write(CARS, bytes(64 * CAR_REC))
                    e.write(CARS, bytes.fromhex(a[0]))
                    e.put32(G_CARS, CARS)
                elif op == "KT":
                    d = bytes.fromhex(a[0])
                    e.write(TRK, bytes(SPAN))
                    e.write(TRK, d)
                    self.emit("KT -> %d" % self.call(LOADER_TRACK, TRK))
                elif op == "KS":
                    d = bytes.fromhex(a[0])
                    e.write(SKN, bytes(SPAN))
                    e.write(SKN, d)
                    e.put32(G_SKINS, SKN + 8)
                    e.put32(G_NSKINS, (len(d) - 8) >> 6)
                elif op == "KD":
                    e.write(DIFFICULTY, bytes.fromhex(a[0])[8:])
                elif op == "NS":
                    e.put32(G_NSKINS, int(a[0]))
                elif op in ("cr", "tr", "sk"):
                    i, off, size, v = map(int, a)
                    base = {"cr": CARS + CAR_REC * i,
                            "tr": TRK + 8 + TRK_REC * (i - 1),
                            "sk": SKN + 8 + 64 * i}[op]
                    self.put(base + off, size, v)
                elif op == "fr":
                    k, off, size, v = map(int, a)
                    self.put(self.fk(k) + off, size, v)
                elif op == "rp":
                    off, size, v = map(int, a)
                    self.put(RP + off, size, v)
                elif op == "rq":
                    off = {"n": 776, "s": 780, "w": 784}[a[0]]
                    e.put32(RP + off, int(a[1], 0))
                elif op == "dt":
                    off, size = DT_FIELDS[a[1]]
                    self.put(DIT + DI_SIZE * int(a[0]) + off, size,
                             int(a[2]))
                elif op == "v":
                    e.put32(VARS[a[0]], int(a[1], 0))
                elif op == "cp":
                    e.write(ALT, e.read(FRED, FRED_SIZE))
                elif op == "hs":
                    base = self.fk(a[0]) + HIGH_SCORES
                    salt = int(a[1]) if len(a) > 1 else 0
                    b = bytearray()
                    for i in range(NUM_TOTAL_TIMES):
                        b += struct.pack("<Ihh", 7 * i + 1 + 0x1000 * salt,
                                         i, -i)
                    for i in range(NUM_LAP_TIMES):
                        b += struct.pack("<Ihh", 0x10000 + 3 * i, -i, i)
                    e.write(base, bytes(b))
                elif op == "rd":
                    ty, inst, sk, da, vd = map(int, a)
                    self.put(RIDE, 4, ty)
                    e.write(RIDE + 4, bytes(x & 0xff
                                            for x in (inst, sk, da, vd)))
                elif op == "ls":
                    for i, v in enumerate(map(int, a)):
                        e.put32(LIST + 4 * i, v)
                elif op == "es":
                    self.status = int(a[0])
                    continue
                elif op == "ei":
                    self.race_index = int(a[0])
                    continue
                elif op == "ek":
                    self.ko = [int(a[0]), int(a[1])]
                    continue
                elif op == "eu":
                    self.user_rank = int(a[0])
                    continue
                elif op == "ew":
                    self.word = int(a[0])
                    continue
                elif op == "et":
                    self.tree = int(a[0])
                    continue
                elif op == "ee":
                    self.elim[int(a[0])] = int(a[1])
                    continue
                elif op == "ex":
                    self.elim = {}
                    continue
                elif op == "er":
                    self.reward = int(a[0])
                    continue
                elif op == "eo":
                    self.put(EVT + 156 + 2 * int(a[0]), 2, int(a[1]))
                    continue
                elif op == "ec":
                    k, ty, sk, skill = map(int, a)
                    e.write(OPP + 4 * k, bytes((ty & 0xff, sk & 0xff,
                                                skill & 0xff, 0)))
                    continue
                elif op == "ev":
                    self.put(EV + 106, 2, int(a[0]))
                    self.put(EV + 112, 2, int(a[1]))
                elif op == "SF":
                    self.call(SINIT_FRED)
                elif op == "I":
                    self.call(INIT_FRED)
                elif op == "R":
                    self.call(RP_DEFAULTS, RP)
                elif op == "SS":
                    self.call(START_SKIP_FE, self.fk(a[0]))
                elif op == "SR":
                    self.call(START_RACE, self.fk(a[0]))
                elif op == "SC":
                    self.call(SETUP_CARS, self.fk(a[0]))
                elif op == "CP":
                    self.call(START_POSITIONS, self.fk(a[0]))
                elif op == "RT":
                    self.call(RECORD_TIMES, self.fk(a[0]), int(a[1]))
                elif op == "RA":
                    self.call(ALL_RECORD_TIMES, self.fk(a[0]))
                elif op == "GR":
                    r = self.call(GENERATE_RIDE, RIDE, int(a[0]), int(a[1]))
                    self.emit("GR -> %d" % r)
                elif op == "GS":
                    r = self.call(RANDOM_SKIN, CARS + CAR_REC * int(a[0]))
                    self.emit("GS -> %d" % r)
                elif op == "PN":
                    r = self.call(PICK_CHARACTER, LIST, int(a[0]), int(a[1]))
                    self.emit("PN -> %d" % r)
                elif op == "PK":
                    self.emit("PK -> %d" % self.call(PICK_COP, 0))
                elif op == "AT":
                    self.emit("AT -> %d" % self.call(ANY_OF_TYPE, int(a[0])))
                elif op == "AC":
                    self.emit("AC -> %d" % self.call(
                        ANY_OF_COLOUR, int(a[0]), int(a[1])))
                elif op == "PU":
                    self.emit("PU -> %d" % self.call(UNUSED_SKIN, int(a[0])))
                elif op == "hu":
                    self.emit("h -> %d" % self.call(UNIQUE_TRACK, 0,
                                                    int(a[0])))
                elif op == "hl":
                    self.emit("h -> %d" % self.call(UNIQUE_LAP, 0, int(a[0])))
                elif op == "ht":
                    t_, c, d, laps = map(int, a)
                    self.emit("h -> %d" % self.call(TOTAL_INDEX, 0, t_, c, d,
                                                    laps))
                elif op == "hp":
                    t_, c, d = map(int, a)
                    self.emit("h -> %d" % self.call(LAP_INDEX, 0, t_, c, d))
                elif op == "DC":
                    u, ty, ch_, skill, start = map(int, a)
                    self.call(DRIVER_CTOR, DI_SCR, u, ty, RIDE, ch_, skill,
                              start)
                elif op == "AD":
                    self.call(ADD_DRIVER, RP, DI_SCR)
                elif op == "FD":
                    r = self.call(FIND_DRIVER, RP, int(a[0]))
                    self.emit("FD -> %s" % self.label(r))
                elif op == "RE":
                    self.call(RESTORE, RP)
                elif op == "EL":
                    r = self.call(ELIMINATE, RP, int(a[0]), int(a[1]))
                    self.emit("EL -> %s" % self.label(r))
                elif op == "TM":
                    self.emit("TM -> %d" % self.call(TOO_MANY, RP, RIDE))
                elif op == "LI":
                    self.emit("LI -> %d" % self.call(LOCATION_INDEX, RP))
                elif op == "RI":
                    ty, sk, da, vd = map(int, a)
                    self.call(RIDE_INIT, RIDE, ty, sk, da, vd)
                elif op == "tn":
                    self.set_trees(int(a[0]))
                    continue
                elif op in ("ta", "tu"):
                    tree, track, d, v = map(int, a)
                    tab = self.reward_tab if op == "ta" else self.unlocked_tab
                    tab[(tree, track & 0xff, d & 1)] = s32(v & M32)
                    continue
                elif op == "QR":
                    self.call(START_QUICK, int(a[0]))
                elif op == "PT":
                    e.write(PICK, bytes(16))
                    self.call(PICK_TRACK, PICK)
                    self.emit("PT -> %d %d" % (s32(e.u32(PICK + 8)),
                                               s32(e.u32(PICK + 12))))
                elif op == "IU":
                    t_, d = int(a[0]), int(a[1])
                    self.emit("IU -> %d %d %d" % (
                        self.call(IS_UNLOCKED, t_, d),
                        self.call(IS_REWARD, t_, d),
                        self.call(TREES_UNLOCKED, t_, d)))
                elif op == "CS":
                    self.emit("CS -> %d" % s32(self.call(
                        CAR_STATUS, FRED + FPI, int(a[0]))))
                elif op == "GT":
                    k = self.fk(a[0])
                    self.emit("GT -> %d %d %d" % (
                        self.call(USE_EVENT, k), self.call(IS_CHALLENGE, k),
                        self.call(IS_EVENT, k)))
                else:
                    raise SystemExit("bad op %r" % (t,))
                self.print_state()
        return self.out


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py): the script, the tools, the ELF and
    GLOBALB.BUN."""
    return mutpar.model_cached(encode(sc).splitlines(),
                               lambda s: Model().run(sc), data=(GLOBALB,),
                               cut=MUTATIONS_HEADER)


# ================================================================ the build


def build_harness(tmp, name="fredrace_test"):
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


def M(name, before, after, rel=FRR):
    return (name, rel, before, after)


QRC = "3DS Files/source/quickrace.c"
FRC = "3DS Files/source/fred.c"


MUTATIONS = [
    # The game types.
    M("use_event_4", "return t == 4 || (t >= 8 && t < 10);",
      "return t == 5 || (t >= 8 && t < 10);"),
    M("use_event_10", "return t == 4 || (t >= 8 && t < 10);",
      "return t == 4 || (t >= 8 && t <= 10);"),
    M("challenge_lo", "return f->GameType >= 3 && f->GameType < 8;",
      "return f->GameType >= 2 && f->GameType < 8;"),
    M("challenge_hi", "return f->GameType >= 3 && f->GameType < 8;",
      "return f->GameType >= 3 && f->GameType < 7;"),
    M("event_game", "return f->GameType >= 8 && f->GameType < 10;",
      "return f->GameType >= 9 && f->GameType < 10;"),
    # The drivers.
    M("ride_init_vd", "r->CanBeVertexDamaged = (int8_t)vertexDamage;",
      "r->CanBeVertexDamaged = (int8_t)dash;"),
    M("ride_init_inst", "    r->InstanceIndex = 0;\n}\n\nvoid driver_info_init",
      "    r->InstanceIndex = 1;\n}\n\nvoid driver_info_init"),
    M("driver_start", "d->StartingPosition = (int8_t)startPos;",
      "d->StartingPosition = (int8_t)0;"),
    M("driver_rank", "d->EliminatedRank = 0;\n    d->CurrentRideInfo = *ride;",
      "d->EliminatedRank = 1;\n    d->CurrentRideInfo = *ride;"),
    M("driver_charinfo", "d->pCharacterInfo = get_character_info(character);",
      "d->pCharacterInfo = get_character_info(character + 1);"),
    M("driver_skill", "d->SkillLevel = (int8_t)skill;",
      "d->SkillLevel = (int8_t)(skill + 1);"),
    M("skin_cop", "return cartypeinfo_get_skin_number(ct, 0);", "return 1;"),
    M("skin_none", "if (ct->NumAvailableSkins == 0)\n        return 0;",
      "if (ct->NumAvailableSkins == 0)\n        return 1;"),
    M("skin_draw",
      "return ct->AvailableSkins[bRandomI(ct->NumAvailableSkins, &bDefaultSeed)];",
      "return ct->AvailableSkins[(bRandomI(ct->NumAvailableSkins, &bDefaultSeed) + 1) % ct->NumAvailableSkins];"),
    M("next_geometry",
      "if (ct->UsageType != usage || ct->GeometryFilename[0] == 0)\n            continue;",
      "if (ct->UsageType != usage)\n            continue;"),
    M("next_class_any", "if (carClass != -1 && ct->CarClass != carClass)",
      "if (ct->CarClass != carClass)"),
    M("next_skins", "if (cartypeinfo_get_num_skins(ct) > 0)",
      "if (cartypeinfo_get_num_skins(ct) >= 0)"),
    M("next_64", "while (*i < 64) {", "while (*i < 63) {"),
    M("gen_threshold", "if (fabsf(total) <= 0.001f)\n        return 0;",
      "if (fabsf(total) <= 0.0f)\n        return 0;"),
    M("gen_fabs", "if (fabsf(total) <= 0.001f)\n        return 0;",
      "if (total <= 0.001f)\n        return 0;"),
    M("gen_flags",
      "r->CanBeVertexDamaged = 0;\n            r->InstanceIndex = 0;\n            r->HasDash = 0;",
      "r->CanBeVertexDamaged = 0;\n            r->InstanceIndex = 0;\n            r->HasDash = 1;"),
    M("gen_type", "r->Type = ct->Type;", "r->Type = ct->Type + 1;"),
    M("upper", "v &= 0x5f;", "v &= 0x7f;"),
    M("pick_skip", "if (list[i] == -1)\n            continue;",
      "if (list[i] == -2)\n            continue;"),
    M("pick_gender_any", "if (gender != -1) {", "if (gender != -2) {"),
    M("pick_female", "if (male ? gender != 0 : gender != 1)",
      "if (male ? gender != 0 : gender == 0)"),
    M("pick_male", "if (male ? gender != 0 : gender != 1)",
      "if (male ? gender == 1 : gender != 1)"),
    M("pick_take", "list[i] = -1;\n            return c;",
      "list[i] = -2;\n            return c;"),
    M("pick_none", "    return 0;\n}\n\nint32_t pick_cop_character_number",
      "    return -1;\n}\n\nint32_t pick_cop_character_number"),
    M("cop_hash0", 'hash = bchunk_hash("Cop");', 'hash = bchunk_hash("FatCop");'),
    M("cop_none", "return ci != NULL ? ci->CharacterNumber : -1;",
      "return ci != NULL ? ci->CharacterNumber : 0;"),
    M("any_type_rank",
      "if (d->EliminatedRank == 0 && d->CurrentRideInfo.Type == type)",
      "if (d->CurrentRideInfo.Type == type)"),
    M("paint_default", "cartypeinfo_get_skin_info(type, skin, 1);",
      "cartypeinfo_get_skin_info(type, skin, 0);"),
    M("colour_rank",
      "if (d->EliminatedRank != 0)\n            continue;\n        if (paint_type",
      "if (0)\n            continue;\n        if (paint_type"),
    M("colour_cmp", "d->CurrentRideInfo.SkinNumber) == paint)",
      "d->CurrentRideInfo.SkinNumber) != paint)"),
    M("unused_tries", "for (tries = 0; tries < 100; tries++) {\n        skin",
      "for (tries = 0; tries < 1; tries++) {\n        skin"),
    M("unused_break",
      "if (!are_there_any_cars_of_colour(type, skin))\n            break;",
      "if (are_there_any_cars_of_colour(type, skin))\n            break;"),
    # The records.
    M("track_valid", "if (t == NULL || t->IsValid == 0)", "if (t == NULL)"),
    M("lap_table", "{ 1, 2, 3, 4, 5, 6, 7, 8, 10 }",
      "{ 1, 2, 3, 4, 5, 6, 7, 8, 9 }"),
    M("lap_none", "            return i;\n    return 0;",
      "            return i;\n    return 8;"),
    M("total_450", "_track_index(track) * 450", "_track_index(track) * 400"),
    M("total_laps", "_lap_index(laps) * 5", "_lap_index(laps) * 4"),
    M("total_dir", "(direction != 0) * 45", "direction * 45"),
    M("total_class", "carClass * 90", "carClass * 80"),
    M("lap_50", "_track_index(track) * 50", "_track_index(track) * 40"),
    M("lap_class", "carClass * 10", "carClass * 9"),
    M("lap_dir", "(direction != 0) * 5;", "direction * 5;"),
    M("rt_gametype",
      "fpi_get_selected_ride_info(&f->FrontendPlayers[player], Fred.GameType);",
      "fpi_get_selected_ride_info(&f->FrontendPlayers[player], f->GameType);"),
    M("rt_player",
      "fpi_get_selected_ride_info(&f->FrontendPlayers[player], Fred.GameType);",
      "fpi_get_selected_ride_info(&Fred.FrontendPlayers[player], Fred.GameType);"),
    M("rt_laps", "    if (laps != 0)\n        ps->BestTotalTimeRecord",
      "    if (laps >= 0)\n        ps->BestTotalTimeRecord"),
    M("rt_lap_record",
      "ps->BestLapTimeRecord = f->ChallengeHighScores.LapTimesTable[",
      "ps->BestTotalTimeRecord = f->ChallengeHighScores.LapTimesTable["),
    M("rt_table",
      "ps->BestTotalTimeRecord = f->ChallengeHighScores.TotalTimesTable[",
      "ps->BestTotalTimeRecord = Fred.ChallengeHighScores.TotalTimesTable["),
    M("rta_np",
      "for (p = 0; p < TheRaceParameters.NumPlayerCars; p++)\n        fred_set_record",
      "for (p = 0; p < 1; p++)\n        fred_set_record"),
    # The starting positions.
    M("pa_max", "if (ct->Engine.TorqueCurveTable[k] > perf)",
      "if (ct->Engine.TorqueCurveTable[k] < perf)"),
    M("pa_k9", "for (k = 0; k < 9; k++)\n        if (ct->Engine",
      "for (k = 0; k < 8; k++)\n        if (ct->Engine"),
    M("pa_mass", "perf = perf / ct->Body.Mass;", "perf = perf * ct->Body.Mass;"),
    M("pa_gear", "ct->DriveTrain.GearRatios[2];", "ct->DriveTrain.GearRatios[1];"),
    M("pa_final", "ct->DriveTrain.FinalDrive[1];", "ct->DriveTrain.FinalDrive[0];"),
    M("pa_wheel", "return perf / ct->Wheels[3].Radius;",
      "return perf / ct->Wheels[0].Radius;"),
    M("cp_event",
      "if (fred_use_the_race_event(f) && gRaceEventStartingPositionsFn != NULL)",
      "if (gRaceEventStartingPositionsFn != NULL)"),
    M("cp_skip_rank",
      "if (d->EliminatedRank != 0 || d->StartingPosition != 0)",
      "if (d->StartingPosition != 0)"),
    M("cp_skip_start",
      "if (d->EliminatedRank != 0 || d->StartingPosition != 0)",
      "if (d->EliminatedRank != 0)"),
    M("cp_type_hi", "if (d->TheDriverType >= DRIVER_TYPE_TRAFFIC_CAR",
      "if (d->TheDriverType > DRIVER_TYPE_TRAFFIC_CAR"),
    M("cp_type_lo", "|| d->TheDriverType <= DRIVER_TYPE_NONE)",
      "|| d->TheDriverType < DRIVER_TYPE_NONE)"),
    M("cp_sort", "if (perf[j] < perf[j + 1]) {", "if (perf[j] > perf[j + 1]) {"),
    M("cp_sort_ties", "if (perf[j] < perf[j + 1]) {",
      "if (perf[j] <= perf[j + 1]) {"),
    M("cp_passes",
      "for (i = 0; i < n; i++) {\n        for (j = 0; j < n - 1; j++) {",
      "for (i = 0; i < 1; i++) {\n        for (j = 0; j < n - 1; j++) {"),
    M("cp_pos9", "for (pos = 1; pos < 9; pos++) {",
      "for (pos = 1; pos < 8; pos++) {"),
    M("cp_pos1", "for (pos = 1; pos < 9; pos++) {",
      "for (pos = 0; pos < 9; pos++) {"),
    M("cp_held", "== pos)\n                    break;",
      "!= pos)\n                    break;"),
    # The knocked out.
    M("cd_event",
      "if (fred_use_the_race_event(f) && gRaceEventDriverEliminatedFn != NULL",
      "if (gRaceEventDriverEliminatedFn != NULL"),
    M("cd_rank",
      "race_parameters_eliminate_driver(&TheRaceParameters, number, rank);",
      "race_parameters_eliminate_driver(&TheRaceParameters, number, 1);"),
    M("cd_count", "    (*count)++;\n}", "    (*count) += 2;\n}"),
    # The AI's rides.
    M("ai_opp2", "if (rp->OpponentSelect == 2) {",
      "if (rp->OpponentSelect == 3) {"),
    M("ai_opp_skin", "if (skin < 0)\n            skin = pick_unused_skin(rec[0]);",
      "if (skin < -1)\n            skin = pick_unused_skin(rec[0]);"),
    M("ai_opp_signed", "skin = (int8_t)rec[1];", "skin = rec[1];"),
    M("ai_opp_skill", "*skill = rec[2];\n        return;",
      "*skill = rec[1];\n        return;"),
    M("ai_opp_type", "ride->Type = rec[0];", "ride->Type = rec[0] + 1;"),
    M("ai_skill_cops", "SkillLevelDistribution[rp->nMaxCops < 1]",
      "SkillLevelDistribution[rp->nMaxCops < 2]"),
    M("ai_skill_cops_swap", "SkillLevelDistribution[rp->nMaxCops < 1]",
      "SkillLevelDistribution[rp->nMaxCops >= 1]"),
    M("ai_skill_strength", "[rp->nMaxCops < 1][rp->OpponentStrength];",
      "[rp->nMaxCops < 1][0];"),
    M("ai_skill_k", "*skill = k;\n                break;",
      "*skill = k + 1;\n                break;"),
    M("ai_force", "if (type != -1 || rp->OpponentSelect == 1) {",
      "if (type != -1) {"),
    M("ai_force_player",
      "type = fpi_get_selected_ride_info(&Fred.FrontendPlayers[0],",
      "type = fpi_get_selected_ride_info(&Fred.FrontendPlayers[1],"),
    M("ai_force_skin", "ride->SkinNumber = (int8_t)pick_unused_skin(type);",
      "ride->SkinNumber = (int8_t)1;"),
    M("ai_attempts", "for (attempt = 0; attempt < 500; attempt++) {",
      "for (attempt = 0; attempt < 1; attempt++) {"),
    M("ai_gens", "} while (gens < 1001", "} while (gens < 1"),
    M("ai_first", "*firstGen = 1;\n                cls = minClass;",
      "*firstGen = 1;\n                cls = maxClass;"),
    M("ai_second", "*secondGen = 1;\n                cls = maxClass;",
      "*secondGen = 1;\n                cls = minClass;"),
    M("ai_random_cls",
      "cls = bRandomI(maxClass - minClass + 1, &bDefaultSeed)",
      "cls = bRandomI(maxClass - minClass + 2, &bDefaultSeed)"),
    M("ai_fallback",
      "if (ride->Type == -1)\n                generate_random_ride_info",
      "if (ride->Type == -2)\n                generate_random_ride_info"),
    M("ai_type_attempt",
      "if (attempt < 100 && are_there_any_cars_of_type(ride->Type))",
      "if (attempt < 50 && are_there_any_cars_of_type(ride->Type))"),
    M("ai_colour_attempt", "if (attempt < 200\n", "if (attempt < 150\n"),
    M("ai_ok", "if (ok)\n            break;", "if (!ok)\n            break;"),
    # SetupCarsForRace.
    M("sc_restore",
      "race_parameters_restore_eliminated(rp);\n    bSetRandomSeed",
      "bSetRandomSeed"),
    M("sc_seed", "bSetRandomSeed((uint32_t)rp->New780, &bDefaultSeed);",
      "bSetRandomSeed((uint32_t)rp->New784, &bDefaultSeed);"),
    M("sc_list", "        list[i] = i;", "        list[i] = 7 - i;"),
    M("sc_cops9",
      "if (rp->NumPlayerCars + rp->NumAICars + rp->nMaxCops >= 9) {",
      "if (rp->NumPlayerCars + rp->NumAICars + rp->nMaxCops >= 10) {"),
    M("sc_cops8", "rp->nMaxCops = 8 - (rp->NumPlayerCars + rp->NumAICars);",
      "rp->nMaxCops = 9 - (rp->NumPlayerCars + rp->NumAICars);"),
    M("sc_cops0", "if (rp->nMaxCops < 0)\n            rp->nMaxCops = 0;",
      "if (rp->nMaxCops < 0)\n            rp->nMaxCops = 1;"),
    M("sc_aidemo", "if (rp->AIDemoMode == 0) {\n        int32_t numPlayers",
      "if (1) {\n        int32_t numPlayers"),
    M("sc_player_gender", "list, 8, p->mPlayerSettings.PreferredGender);",
      "list, 8, -1);"),
    M("sc_beacop", "if (rp->BeACop != 0 && i == 0)", "if (rp->BeACop != 0)"),
    M("sc_beacop_off", "if (rp->BeACop != 0 && i == 0)", "if (0)"),
    M("sc_vd", "sel->CanBeVertexDamaged = 1;", "sel->CanBeVertexDamaged = 0;"),
    M("sc_player_ride", "sel = fpi_get_selected_ride_info(p, Fred.GameType);",
      "sel = fpi_get_selected_ride_info(p, f->GameType);"),
    M("sc_player_skill", "DRIVER_TYPE_PLAYER, sel, c, -2,",
      "DRIVER_TYPE_PLAYER, sel, c, -1,"),
    M("sc_player_start", "rp->PlayerStartPosition[i]);",
      "rp->PlayerStartPosition[0]);"),
    M("sc_np", "    rp->NumPlayerCars = count;\n", "\n"),
    M("sc_class_demo", "minClass = maxClass = bRandomI(5, &bDefaultSeed);",
      "minClass = maxClass = bRandomI(4, &bDefaultSeed);"),
    M("sc_class_np1", "} else if (rp->NumPlayerCars == 1) {",
      "} else if (rp->NumPlayerCars == 2) {"),
    M("sc_class_min", "minClass = c1 < c0 ? c1 : c0;",
      "minClass = c1 < c0 ? c0 : c1;"),
    M("sc_class_max", "maxClass = c1 < c0 ? c0 : c1;",
      "maxClass = c1 < c0 ? c1 : c0;"),
    M("sc_class_p1", "&Fred.FrontendPlayers[1], f->GameType)->Type);",
      "&Fred.FrontendPlayers[0], f->GameType)->Type);"),
    M("sc_ai_char", "pick_character_number_that_isnt_racing(list, 8, -1);",
      "pick_character_number_that_isnt_racing(list, 7, -1);"),
    M("sc_ai_number", "i + 100, DRIVER_TYPE_AI_RACER",
      "i + 101, DRIVER_TYPE_AI_RACER"),
    M("sc_ai_start", "&ride, c, skill,\n                         0);",
      "&ride, c, skill,\n                         1);"),
    M("sc_ai_count", "    rp->NumAICars = count;\n", "\n"),
    M("sc_traffic_thresh",
      "numTraffic = fabsf(rp->TrafficDensity) <= 0.001f ? 0 : 6;",
      "numTraffic = fabsf(rp->TrafficDensity) <= 0.0f ? 0 : 6;"),
    M("sc_traffic_fabs",
      "numTraffic = fabsf(rp->TrafficDensity) <= 0.001f ? 0 : 6;",
      "numTraffic = rp->TrafficDensity <= 0.001f ? 0 : 6;"),
    M("sc_traffic_6", "<= 0.001f ? 0 : 6;", "<= 0.001f ? 0 : 5;"),
    M("sc_traffic_tries",
      "for (tries = 0; tries < 100; tries++) {\n            generate_random_ride_info",
      "for (tries = 0; tries < 1; tries++) {\n            generate_random_ride_info"),
    M("sc_traffic_skin", "ride.SkinNumber = -1;", "ride.SkinNumber = 0;"),
    M("sc_traffic_number", "i + 50, DRIVER_TYPE_TRAFFIC_CAR",
      "i + 51, DRIVER_TYPE_TRAFFIC_CAR"),
    M("sc_lowest", "int32_t lowest = 5;", "int32_t lowest = 4;"),
    M("sc_lowest_lt", "if (c < lowest)\n                lowest = c;",
      "if (c > lowest)\n                lowest = c;"),
    M("sc_cop_geometry",
      "if (ct->UsageType != CAR_USAGE_TYPE_COP\n                    || ct->GeometryFilename[0] == 0)",
      "if (ct->UsageType != CAR_USAGE_TYPE_COP)"),
    M("sc_cop_lt", "if (dThis < dBest) {", "if (dThis <= dBest) {"),
    M("sc_cop_abs", "if (dBest < 0)\n                    dBest = -dBest;", ""),
    M("sc_cop_ride", "ride_info_init(&ride, best, 1, 0, 0);",
      "ride_info_init(&ride, best, 2, 0, 0);"),
    M("sc_cop_number", "i + 10, DRIVER_TYPE_COP", "i + 11, DRIVER_TYPE_COP"),
    M("sc_cop_char",
      "int32_t ch = pick_cop_character_number(rp->TrackNumber);",
      "int32_t ch = 8;"),
    M("sc_positions", "    fred_calculate_starting_positions(f);\n}", "}"),
    # StartRace.
    M("sr_ko_type",
      "if (f->GameType == 4) {\n        TheRaceEventFields.NumPlayers",
      "if (f->GameType == 5) {\n        TheRaceEventFields.NumPlayers"),
    M("sr_status", "if (status != 2 && gRaceEventResetStateFn != NULL)",
      "if (status != 1 && gRaceEventResetStateFn != NULL)"),
    M("sr_np_else",
      "    } else {\n        TheRaceEventFields.NumPlayers = (int16_t)f->NumPlayerCars;\n    }",
      "    }"),
    M("sr_mod", "gEventTrackSetRaceFn(index % tracks, rp);",
      "gEventTrackSetRaceFn(index, rp);"),
    M("sr_ko3", "if (TheRaceEventFields.Type == 3\n",
      "if (TheRaceEventFields.Type == 4\n"),
    M("sr_ko_index", "? gRaceEventGetRaceIndexFn() : 0) != 0) {",
      "? gRaceEventGetRaceIndexFn() : 0) == 0) {"),
    M("sr_ko1", "rp->PlayerStartPosition[1] = (int8_t)s1;",
      "rp->PlayerStartPosition[1] = (int8_t)s0;"),
    M("sr_tour", "if (TheRaceEventFields.Type == 4\n",
      "if (TheRaceEventFields.Type == 3\n"),
    M("sr_tour_status",
      "               == 2)\n            rp->PlayerStartPosition[0]",
      "               == 1)\n            rp->PlayerStartPosition[0]"),
    M("sr_word0", "TheRaceEventFields.EventWord = 0;\n",
      "TheRaceEventFields.EventWord = 1;\n"),
    M("sr_word_event",
      "if (fred_use_the_race_event(f) && gFredEventWordFn != NULL)",
      "if (gFredEventWordFn != NULL)"),
    M("sr_boost_type", "if (fred_is_challenge_game(f) || f->GameType == 2) {",
      "if (fred_is_challenge_game(f) || f->GameType == 1) {"),
    M("sr_boost_gametype", "&Fred.FrontendPlayers[p], Fred.GameType)->Type);",
      "&Fred.FrontendPlayers[p], f->GameType)->Type);"),
    M("sr_boost_strength", ".BoostScale[rp->OpponentStrength][cls];",
      ".BoostScale[0][cls];"),
    M("sr_boost_np",
      "for (p = 0; p < rp->NumPlayerCars; p++) {\n            int32_t cls",
      "for (p = 0; p < 1; p++) {\n            int32_t cls"),
    M("sr_boost_one",
      "} else if (!fred_is_event_game(f) && f->GameType == 1) {",
      "} else if (!fred_is_event_game(f) && f->GameType == 0) {"),
    M("sr_boost_1", "rp->BoostScale[1] = 1.0f;\n        rp->BoostScale[0] = 1.0f;",
      "rp->BoostScale[1] = 0.5f;\n        rp->BoostScale[0] = 1.0f;"),
    M("sr_maxai", "if (MaximumNumAICars < rp->NumAICars)\n",
      "if (MaximumNumAICars < rp->NumAICars - 1)\n"),
    M("sr_9", "if (rp->NumAICars + rp->NumPlayerCars >= 9)",
      "if (rp->NumAICars + rp->NumPlayerCars >= 10)"),
    M("sr_8", "rp->NumAICars = 8 - rp->NumPlayerCars;",
      "rp->NumAICars = 7 - rp->NumPlayerCars;"),
    M("sr_p2p",
      "if (t != NULL && t->Point2Point != 0)\n            rp->Point2Point = 1;",
      "if (t != NULL && t->Point2Point != 0)\n            rp->Point2Point = 2;"),
    M("sr_display", "rp->GlobalDisplaySettings = f->DisplayOptionsData;",
      "rp->GlobalDisplaySettings = Fred.DisplayOptionsData;"),
    M("sr_ps0",
      "rp->PlayerSettings[0] = Fred.FrontendPlayers[0].mPlayerSettings;",
      "rp->PlayerSettings[0] = f->FrontendPlayers[0].mPlayerSettings;"),
    M("sr_ps1",
      "rp->PlayerSettings[1] = Fred.FrontendPlayers[1].mPlayerSettings;",
      "rp->PlayerSettings[1] = f->FrontendPlayers[1].mPlayerSettings;"),
    M("sr_pov", "rp->PlayerSettings[0].DriveCameraPOVIndex = 3;",
      "rp->PlayerSettings[0].DriveCameraPOVIndex = 2;"),
    M("sr_pov_event", "if (fred_is_event_game(f)) {\n        const DriverInfo",
      "if (1) {\n        const DriverInfo"),
    M("sr_pov_driver", "race_parameters_find_driver(rp, 0);",
      "race_parameters_find_driver(rp, 1);"),
    M("sr_records",
      "    fred_set_all_record_times_to_beat(f);\n    // ChooseHudTextures",
      "    // ChooseHudTextures"),
    M("sr_ms", "gFredMaybeSetSelectedCarForMultiTrackEventFn(f);\n    if (gDemo",
      "(void)0;\n    if (gDemo"),
    M("sr_tree_race",
      "rp->EventTreeRace = Fred.GameType == 8 || Fred.GameType == 9;",
      "rp->EventTreeRace = f->GameType == 8 || f->GameType == 9;"),
    M("sr_reward", "? gEventRewardCarsUnlockedFn() : 0;",
      "? gEventRewardCarsUnlockedFn() + 1 : 0;"),
    M("sr_flow", "gFredChangeGameFlowFn(state == FLOW_IN_FRONTEND",
      "gFredChangeGameFlowFn(state != FLOW_IN_FRONTEND"),
    M("sr_aborted", "f->bRaceWasAborted = 0;", "f->bRaceWasAborted = 1;"),
    # StartSkipFEGame.
    M("ss_track", "if (track == -1)\n        track = 12;",
      "if (track == -1)\n        track = 11;"),
    M("ss_np_f", "    f->NumPlayerCars = SkipFENumPlayerCars;\n", "\n"),
    M("ss_tod", "rp->TrackTimeOfDay = 3;\n    rp->TrafficDensity",
      "rp->TrackTimeOfDay = 2;\n    rp->TrafficDensity"),
    M("ss_density", "rp->TrafficDensity = SkipFETrafficDensity;",
      "rp->TrafficDensity = SkipFETrafficOncoming;"),
    M("ss_oncoming", "rp->TrafficOncoming = SkipFETrafficOncoming;",
      "rp->TrafficOncoming = SkipFETrafficDensity;"),
    M("ss_racetype", "rp->RaceType = SkipFERaceType;", "rp->RaceType = 1;"),
    M("ss_laps", "rp->NumLapsInRace = SkipFENumLaps;",
      "rp->NumLapsInRace = 8;"),
    M("ss_np", "rp->NumPlayerCars = SkipFENumPlayerCars;",
      "rp->NumPlayerCars = 1;"),
    M("ss_nai", "rp->NumAICars = SkipFENumAICars;", "rp->NumAICars = 0;"),
    M("ss_cops", "rp->nMaxCops = SkipFEMaxCops;", "rp->nMaxCops = 0;"),
    M("ss_tickets", "rp->bTickets = SkipFETickets;", "rp->bTickets = 1;"),
    M("ss_roadblocks", "rp->bRoadBlocks = SkipFERoadBlocks;",
      "rp->bRoadBlocks = 1;"),
    M("ss_heli", "rp->bHelicopter = SkipFEHelicopter;",
      "rp->bHelicopter = SkipFESpikeStrips;"),
    M("ss_spikes", "rp->bSpikeStrips = SkipFESpikeStrips;",
      "rp->bSpikeStrips = SkipFEHelicopter;"),
    M("ss_624", "rp->New624 = SkipFENew624;", "rp->New624 = 1;"),
    M("ss_weather", "rp->TrackWeather = 0;", "rp->TrackWeather = 1;"),
    M("ss_dir", "rp->TrackDirection = 0;", "rp->TrackDirection = 1;"),
    M("ss_beacop", "rp->BeACop = SkipFEBeACop;", "rp->BeACop = 0;"),
    M("ss_ttt", "if (rp->BeACop != 0)\n        rp->TimeTrialTime",
      "if (rp->BeACop == 0)\n        rp->TimeTrialTime"),
    M("ss_ttt_val", "(uint32_t)(int32_t)1200000.5f;",
      "(uint32_t)(int32_t)1200001.5f;"),
    M("ss_start1", "(int8_t)((uint8_t)SkipFENumAICars + 2);",
      "(int8_t)((uint8_t)SkipFENumAICars + 3);"),
    M("ss_start0", "(int8_t)((uint8_t)SkipFENumAICars + 1);",
      "(int8_t)((uint8_t)SkipFENumAICars + 0);"),
    M("ss_oppstr", "rp->OpponentStrength = diff;", "rp->OpponentStrength = 0;"),
    M("ss_copstr", "rp->CopStrength = diff;", "rp->CopStrength = 0;"),
    M("ss_boost0", "[diff][car_class(DefaultPlayer1CarType)];",
      "[diff][car_class(DefaultPlayer2CarType)];"),
    M("ss_boost1", "[diff][car_class(DefaultPlayer2CarType)];",
      "[diff][car_class(DefaultPlayer1CarType)];"),
    M("ss_boost_diff",
      "rp->BoostScale[0] = TheDifficultyInfo.AINonExplicitMode\n        .BoostScale[diff]",
      "rp->BoostScale[0] = TheDifficultyInfo.AINonExplicitMode\n        .BoostScale[0]"),
    M("ss_fred", "    fred_start_race(&Fred);\n}", "    fred_start_race(f);\n}"),
    # RaceParameters.
    M("add_14",
      "if (rp->NumDriverInfo >= RACE_PARAMETERS_MAX_DRIVERS)\n        return;",
      "if (rp->NumDriverInfo >= RACE_PARAMETERS_MAX_DRIVERS - 1)\n        return;",
      RPC),
    M("add_inc", "    rp->NumDriverInfo++;", "    rp->NumDriverInfo += 2;", RPC),
    M("find_eq", "if (rp->pDriverInfoTable[i].UniqueDriverNumber == number)",
      "if (rp->pDriverInfoTable[i].UniqueDriverNumber != number)", RPC),
    M("find_n",
      "for (i = 0; i < rp->NumDriverInfo; i++)\n        if (rp->pDriverInfoTable[i].Unique",
      "for (i = 0; i <= rp->NumDriverInfo; i++)\n        if (rp->pDriverInfoTable[i].Unique",
      RPC),
    M("restore_rank", "if (d->EliminatedRank <= 0)\n            continue;",
      "if (d->EliminatedRank == 0)\n            continue;", RPC),
    M("restore_player", "rp->NumPlayerCars++;", "rp->NumPlayerCars += 2;", RPC),
    M("restore_ai", "rp->NumAICars++;", "rp->NumAICars += 2;", RPC),
    M("restore_clear", "        d->EliminatedRank = 0;\n    }\n}",
      "        d->EliminatedRank = 1;\n    }\n}", RPC),
    M("elim_gt", "if (d == NULL || d->EliminatedRank > 0)\n        return d;",
      "if (d == NULL || d->EliminatedRank >= 0)\n        return d;", RPC),
    M("elim_set", "d->EliminatedRank = (int8_t)rank;",
      "d->EliminatedRank = (int8_t)(rank + 1);", RPC),
    M("elim_player", "rp->NumPlayerCars--;", "rp->NumPlayerCars -= 2;", RPC),
    M("elim_ai", "rp->NumAICars--;", "rp->NumAICars -= 2;", RPC),
    M("tm_le", "for (i = 0; i <= n; i++) {", "for (i = 0; i < n; i++) {", RPC),
    M("tm_rank", "&& rp->pDriverInfoTable[i].EliminatedRank > 0)",
      "&& rp->pDriverInfoTable[i].EliminatedRank > 1)", RPC),
    M("tm_stale",
      "r = i < n ? &rp->pDriverInfoTable[i].CurrentRideInfo : ride;",
      "r = i <= n ? &rp->pDriverInfoTable[i].CurrentRideInfo : ride;", RPC),
    M("tm_traffic",
      "if (ct == NULL || ct->UsageType == CAR_USAGE_TYPE_TRAFFIC)",
      "if (ct == NULL)", RPC),
    M("tm_vd", "if (r->CanBeVertexDamaged != 0) {\n            models++;",
      "if (r->CanBeVertexDamaged != 0) {\n            models += 2;", RPC),
    M("tm_j_rank", "if (dj->EliminatedRank > 0\n                || dj->",
      "if (0\n                || dj->", RPC),
    M("tm_j_vd", "|| dj->CurrentRideInfo.CanBeVertexDamaged != 0)",
      "|| 0)", RPC),
    M("tm_cmp", "cj->CompressedGeometryFilename) == 0)",
      "cj->CompressedGeometryFilename) != 0)", RPC),
    M("tm_6", "return models >= 6;", "return models >= 5;", RPC),
    M("loc_6", "return loc == 6 ? 4 : loc - 1;",
      "return loc == 5 ? 4 : loc - 1;", RPC),
    M("loc_num", "return rp->TrackNumber / 10;",
      "return rp->TrackNumber / 11;", RPC),
    # The quick race.
    M("qr_no_defaults", "race_parameters_init_with_defaults(rp);\n    if",
      "(void)rp;\n    if", QRC),
    M("qr_no_stop", "        gQuickRaceStopMovieFn();", "        ;", QRC),
    M("qr_stop_after", "    if (gQuickRaceStopMovieFn != NULL)\n"
      "        gQuickRaceStopMovieFn();\n    cops = f->MainMenuOpts[1];",
      "    cops = f->MainMenuOpts[1];", QRC),
    M("qr_cops_word", "cops = f->MainMenuOpts[1];",
      "cops = f->MainMenuOpts[0];", QRC),
    M("qr_gametype", "f->GameType = GAME_TYPE_EXPRESS;", "f->GameType = 1;",
      QRC),
    M("qr_np", "f->NumPlayerCars = 1;", "f->NumPlayerCars = 2;", QRC),
    M("qr_track", "rp->TrackNumber = pick.Track;",
      "rp->TrackNumber = pick.Track + 1;", QRC),
    M("qr_dir", "rp->TrackDirection = (eTrackDirection)pick.Direction;",
      "rp->TrackDirection = (eTrackDirection)0;", QRC),
    M("qr_info", "ti = track_get_info(pick.Track);",
      "ti = track_get_info(pick.Track + 1);", QRC),
    M("qr_tod", "ti != NULL ? ti->TimeOfDay : 0;",
      "ti != NULL ? ti->TimeOfDay + 1 : 0;", QRC),
    M("qr_tod_null", "ti != NULL ? ti->TimeOfDay : 0;",
      "ti != NULL ? ti->TimeOfDay : 1;", QRC),
    M("qr_p2p", "ti != NULL ? ti->Point2Point : 0;",
      "ti != NULL ? !ti->Point2Point : 0;", QRC),
    M("qr_p2p_null", "ti != NULL ? ti->Point2Point : 0;",
      "ti != NULL ? ti->Point2Point : 1;", QRC),
    M("qr_ai_cops", "rp->NumAICars = cops != 0 ? 3 : 7;",
      "rp->NumAICars = cops != 0 ? 4 : 7;", QRC),
    M("qr_ai_world", "rp->NumAICars = cops != 0 ? 3 : 7;",
      "rp->NumAICars = cops != 0 ? 3 : 6;", QRC),
    M("qr_ai_test", "rp->NumAICars = cops != 0 ? 3 : 7;",
      "rp->NumAICars = cops > 0 ? 3 : 7;", QRC),
    M("qr_grid", "(int8_t)((uint8_t)rp->NumAICars + 1);",
      "(int8_t)((uint8_t)rp->NumAICars + 2);", QRC),
    M("qr_grid_0", "(int8_t)((uint8_t)rp->NumAICars + 1);",
      "(int8_t)((uint8_t)rp->NumAICars);", QRC),
    M("qr_boost1", "rp->BoostScale[1] = 1.0f;", "rp->BoostScale[1] = 0.5f;",
      QRC),
    M("qr_maxcops", "cops != 0 ? 4 : 0;", "cops != 0 ? 3 : 0;", QRC),
    M("qr_tickets", "cops != 0 ? 2 : 0;", "cops != 0 ? 1 : 0;", QRC),
    M("qr_tickets_off", "cops != 0 ? 2 : 0;", "cops != 0 ? 2 : 1;", QRC),
    M("qr_density", "rp->TrafficDensity = 0.33f;",
      "rp->TrafficDensity = 0.34f;", QRC),
    M("qr_oncoming", "rp->TrafficOncoming = 0.5f;",
      "rp->TrafficOncoming = 0.33f;", QRC),
    M("qr_boost0", "rp->BoostScale[0] = 1.0f;", "rp->BoostScale[0] = 2.0f;",
      QRC),
    M("qr_copstr", "rp->CopStrength = 1;", "rp->CopStrength = 2;", QRC),
    M("qr_racetype", "rp->RaceType = 1;", "rp->RaceType = 0;", QRC),
    M("qr_laps", "rp->NumLapsInRace = 2;", "rp->NumLapsInRace = 3;", QRC),
    M("qr_treerace", "rp->EventTreeRace = 0;", "rp->EventTreeRace = 1;",
      QRC),
    M("qr_oppstr", "rp->OpponentStrength = 1;", "rp->OpponentStrength = 0;",
      QRC),
    M("qr_boost", "rp->Boost = 1;", "rp->Boost = 0;", QRC),
    M("qr_rp_np", "rp->NumPlayerCars = 1;", "rp->NumPlayerCars = 2;", QRC),
    M("qr_roadblocks", "rp->bRoadBlocks = cops;",
      "rp->bRoadBlocks = cops != 0;", QRC),
    M("qr_spikes", "rp->bSpikeStrips = cops;", "rp->bSpikeStrips = 1;", QRC),
    M("qr_new624", "rp->New624 = cops;", "rp->New624 = cops != 0;", QRC),
    M("qr_heli", "rp->bHelicopter = cops;", "rp->bHelicopter = 0;", QRC),
    M("qr_bac_rb", "rp->nNumBeACopRoadBlocks = 0;",
      "rp->nNumBeACopRoadBlocks = cops;", QRC),
    M("qr_bac_ch", "rp->nNumBeACopChoppers = 0;",
      "rp->nNumBeACopChoppers = cops;", QRC),
    M("qr_ticketsflag", "rp->bTickets = cops;", "rp->bTickets = 1;", QRC),
    M("qr_objective", "rp->HasObjective = 0;", "rp->HasObjective = 1;", QRC),
    M("qr_sobjective", "rp->sObjective[0] = 0;", "rp->sObjective[0] = 'x';",
      QRC),
    M("qr_training", "rp->TrainingLinesEnabled = 0;",
      "rp->TrainingLinesEnabled = 1;", QRC),
    M("qr_no_challenge", "fred_make_challenge_cars_available(f);",
      "(void)f;", QRC),
    M("qr_config_test", "    fred_make_challenge_cars_available(f);\n"
      "    if (TrackSelectedInConfigFile >= 0) {",
      "    fred_make_challenge_cars_available(f);\n"
      "    if (TrackSelectedInConfigFile > 0) {", QRC),
    M("qr_config_status", "fpi_set_car_availability(p0, CAR_STATUS_AVAILABLE,",
      "fpi_set_car_availability(p0, 1,", QRC),
    M("qr_config_skins", "DefaultPlayer1CarType, -1, 1);",
      "DefaultPlayer1CarType, 1, 1);", QRC),
    M("qr_config_dash", "DefaultPlayer1CarType, -1, 1);",
      "DefaultPlayer1CarType, -1, 0);", QRC),
    M("qr_config_type", "fpi_assign_car_of_type(p0, f->GameType, "
      "DefaultPlayer1CarType,",
      "fpi_assign_car_of_type(p0, f->GameType, DefaultPlayer2CarType,", QRC),
    M("qr_config_skin", "(uint32_t)DefaultPlayer1SkinIndex, 0);",
      "(uint32_t)DefaultPlayer1SkinIndex + 1, 0);", QRC),
    M("qr_config_mode", "fpi_assign_car_of_type(p0, f->GameType, "
      "DefaultPlayer1CarType,",
      "fpi_assign_car_of_type(p0, 0, DefaultPlayer1CarType,", QRC),
    M("qr_ride_type", "ride.Type = -1;", "ride.Type = 0;", QRC),
    M("qr_ride_usage", "generate_random_ride_info(&ride, CAR_USAGE_TYPE_RACING,",
      "generate_random_ride_info(&ride, 1,", QRC),
    M("qr_ride_status", "while (fpi_get_car_status(p0, ride.Type) != "
      "CAR_STATUS_AVAILABLE);",
      "while (0);", QRC),
    M("qr_ride_skin", "(uint32_t)(int32_t)ride.SkinNumber, 0);",
      "(uint32_t)(int32_t)ride.SkinNumber + 1, 0);", QRC),
    M("qr_ride_dash", "(uint32_t)(int32_t)ride.SkinNumber, 0);",
      "(uint32_t)(int32_t)ride.SkinNumber, 1);", QRC),
    M("qr_trans", "(int8_t)(transmission != 0);", "(int8_t)transmission;",
      QRC),
    M("qr_trans_sign", "(int8_t)(transmission != 0);",
      "(int8_t)(transmission > 0);", QRC),
    M("qr_no_start", "    fred_start_race(f);\n}", "    (void)f;\n}", QRC),
    # The pick.
    M("pk_config_test", "    if (TrackSelectedInConfigFile >= 0) {\n"
      "        out->Track", "    if (TrackSelectedInConfigFile > 0) {\n"
      "        out->Track", QRC),
    M("pk_config_dir", "out->Track = TrackSelectedInConfigFile;\n"
      "        out->Direction = 0;",
      "out->Track = TrackSelectedInConfigFile;\n"
      "        out->Direction = 1;", QRC),
    M("pk_last", "for (i = 0; i <= HighestTrackNumber; i++)",
      "for (i = 0; i < HighestTrackNumber; i++)", QRC),
    M("pk_same", "is_track_unlocked(ti->SameAsTrackNumber, direction)",
      "is_track_unlocked(ti->TrackNumber, direction)", QRC),
    M("pk_number", "list[n].Track = ti->TrackNumber;",
      "list[n].Track = ti->SameAsTrackNumber;", QRC),
    M("pk_dir", "list[n].Direction = direction;",
      "list[n].Direction = 1 - direction;", QRC),
    M("pk_order", "for (direction = 0; direction < 2; direction++)",
      "for (direction = 1; direction >= 0; direction--)", QRC),
    M("pk_one_dir", "for (direction = 0; direction < 2; direction++)",
      "for (direction = 0; direction < 1; direction++)", QRC),
    M("pk_lock", "if (!is_track_unlocked(ti->SameAsTrackNumber, direction))",
      "if (0)", QRC),
    M("pk_random", "*out = list[bRandomI(n, &bDefaultSeed)];",
      "*out = list[n - 1 - bRandomI(n, &bDefaultSeed)];", QRC),
    M("pk_random_n", "*out = list[bRandomI(n, &bDefaultSeed)];",
      "*out = list[bRandomI(n > 1 ? n - 1 : n, &bDefaultSeed)];", QRC),
    # The locks.
    M("lk_reward_ret", "            return 1;\n    return 0;\n}",
      "            return 2;\n    return 0;\n}", QRC),
    M("lk_reward_first", "    for (tree = 0; tree < gNumEventTrees; tree++)\n"
      "        if (tree_track_is_a_reward",
      "    for (tree = 1; tree < gNumEventTrees; tree++)\n"
      "        if (tree_track_is_a_reward", QRC),
    M("lk_unlocked_tree", "    for (tree = 0; tree < gNumEventTrees; tree++) {",
      "    for (tree = 1; tree < gNumEventTrees; tree++) {", QRC),
    M("lk_skip", "        if (!tree_track_is_a_reward(tree, track, "
      "direction))\n            continue;",
      "        if (0)\n            continue;", QRC),
    M("lk_bool", "gEventTreeIsTrackUnlockedFn(tree, track, direction) != 0;",
      "gEventTreeIsTrackUnlockedFn(tree, track, direction);", QRC),
    M("lk_tree_arg", "gEventTreeIsTrackUnlockedFn(tree, track, direction) "
      "!= 0;", "gEventTreeIsTrackUnlockedFn(0, track, direction) != 0;", QRC),
    M("lk_none", "        return gEventTreeIsTrackUnlockedFn(tree, track, "
      "direction) != 0;\n    }\n    return 1;",
      "        return gEventTreeIsTrackUnlockedFn(tree, track, "
      "direction) != 0;\n    }\n    return 0;", QRC),
    M("lk_unlocked", "        return event_tree_is_track_unlocked(track, "
      "direction);\n    return 1;",
      "        return 1;\n    return 1;", QRC),
    M("lk_unlocked_else", "        return event_tree_is_track_unlocked(track, "
      "direction);\n    return 1;",
      "        return event_tree_is_track_unlocked(track, "
      "direction);\n    return 0;", QRC),
    M("cs_index", "(const uint8_t *)p + type * (int32_t)sizeof(CarStatus)",
      "(const uint8_t *)p + (type + 1) * (int32_t)sizeof(CarStatus)", FRC),
]

EQUIVALENT = {
    # The driver being placed is in the table with StartingPosition 0 until
    # it is given one, so slot 0 is always held and the search moves on.
    "cp_pos1": "the driver being placed holds slot 0 itself",
    # StartQuickRace's GameType is 2 and its NumPlayerCars 1, so StartRace,
    # which it always ends with, sets BoostScale[0] from the difficulty
    # table, and EventTreeRace from the GameType, over what it stored;
    # nothing between reads either.
    "qr_boost0": "StartRace sets BoostScale[0] again for the express game",
    "qr_treerace": "StartRace sets EventTreeRace again",
    # GenerateRandomRideInfo writes the ride's Type whenever a racing car
    # has a chance at the track's location, which on the disc every
    # location has; the -1 is read only when none has, and then the loop
    # asks the status of the word before the table.
    "qr_ride_type": "the draw always writes Type with the disc's cars",
    # MakeChallengeCarsAvailable, which StartQuickRace calls just before the
    # draw, sets bDashAvailable 0 on every car with geometry, and the draw
    # takes only cars with geometry, so the dash asked for is never given.
    "qr_ride_dash": "MakeChallengeCarsAvailable has just cleared every "
                    "drawable car's bDashAvailable",
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    hostbuild.recover()
    sc = script()
    base = model_cached(sc)
    scdir = tempfile.TemporaryDirectory()
    scp = Path(scdir.name) / "scenarios.txt"
    scp.write_text(encode(sc))
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text().splitlines()
        if diff(base, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "fredrace_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs)
    scdir.cleanup()
    return mutpar.summarize(todo, only, EQUIVALENT, tally)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--jobs", type=int, metavar="N",
                    help="with --mutate, mutants at once (default %d)"
                    % mutpar.JOBS)
    ap.add_argument("--dump", metavar="PREFIX")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None,
                             args.jobs))

    sc = script()
    lines = model_cached(sc)
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
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
