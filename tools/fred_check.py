#!/usr/bin/env python3
"""Cross-check 3DS Files/source/fred.c, raceparams.c, characterinfo.c and
edisplay.c -- the frontend database, the race parameters, the character
data and the display offsets -- against the retail image, run in mipsemu.

The model is the image. These run as shipped:

  * _GLOBAL_$I$Fred (0x00187c58), FrontendDatabase's constructor
    (0x001836a0); InitFred (0x00183820) and InitWithDefaults (0x00183830),
    with every Data*::InitWithDefaults under it but the audio options';
    MakeChallengeCarsAvailable (0x00183af8); FrontendPlayerInfo's
    SetCarAvailability (0x001878e0), AssignCarOfType (0x00187a68),
    SetDefaultCarType (0x00187a78) and SetCharacterInfo (0x00187ce0), with
    GetNumSkins and GetSkinNumber under them; HighScoreTable's
    InitStatsTables (0x00186708);
  * _GLOBAL_$I$TheRaceParameters (0x001ee590), RaceParameters::
    InitWithDefaults (0x001ed5c8), tGlobalDisplaySettings' (0x001ee0a0),
    cPlayerSettings::ResetToDefaults and bRandomI;
  * LoaderCharacterInfo (0x001d9330), UnloaderCharacterInfo, and the five
    getters, with bStrICmp and bStringHash;
  * LoaderTrackGeometry (0x00153608) on GLOBALB's track table, and
    GetTrackInfo; eGetScreenDisplayOffsets and the set (0x001056d8).

Three calls out are stubbed, on both sides alike, and print themselves:
IsCarUnlocked (0x0024b208), the rewards nothing ports yet, answers by a
rule the script sets; GetTranslatedString(int) (0x0021e560) answers the
script's strings, and the image's "NOT TRANSLATED PROPERLY" for the rest;
DataAudioOptionsScreen::InitWithDefaults (0x001ef1c8) writes a pattern.
The harness (tools/src/fred_test.c) runs the port over the same script.

The data are GLOBALB's own -- its 64 car records, 66 track records, four
bodies and ten characters -- and then those changed field by field: cars
with no geometry, other usages, lock statuses, dash geometry, skin counts
from -1 to 12, skins past a byte; tracks made unique past the sixteen the
high scores number, invalid, renumbered and cut off; characters missing,
short and long. The globals the defaults read (SkipFE, bVersionE3, the
SkipFE display words, the default cars and skins, the POV index, the
language, the video mode and bDefaultSeed) are varied around them, and the
records start filled with patterns so a byte one side leaves and the other
writes shows.

After each op the transcript holds what changed: Fred in 32-byte rows,
TheRaceParameters' first 772 bytes in rows and its last four words (the
port's pointer is a host pointer, so those print by name), each of the
fourteen DriverInfos by field (the port keeps the demo's order), each
track record, and a line of globals.

    python tools/fred_check.py
    python tools/fred_check.py --mutate [--only a,b]
    python tools/fred_check.py --dump out/fred
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import physicscar_check as pcc
import retail_model
from mipsemu import M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/fred_test.c"
FRC = "3DS Files/source/fred.c"
RPC = "3DS Files/source/raceparams.c"
CIC = "3DS Files/source/characterinfo.c"
EDC = "3DS Files/source/edisplay.c"
PSC = "3DS Files/source/playersettings.c"
CFC = "3DS Files/source/configitems.c"
SOURCES = [HARNESS, FRC, RPC, CIC, EDC, PSC, CFC] + [
    "3DS Files/source/" + f for f in (
        "cartypeinfo.c", "langtab.c", "portlang.c", "realtime.c", "bticker.c", "joylog.c",
        "timer.c", "track.c",
        "terraintype.c", "cartrack.c", "carstate.c", "emath.c", "bmatrix.c",
        "terraintypetab.c", "bslotpool.c", "bvector.c", "bmath.c",
        "bmathtab.c", "bchunk.c", "p32.c")]

HARNESS_TIMEOUT = 300
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
OFFSETS = 0x002c79c0               # ScreenDisplayOffsets
NOT_TRANSLATED = 0x002bc958

SINIT_FRED = 0x00187c58
SINIT_RP = 0x001ee590
INIT_FRED = 0x00183820
CHALLENGE_CARS = 0x00183af8
RP_DEFAULTS = 0x001ed5c8
DISPLAY_DEFAULTS = 0x001ee0a0
STATS_TABLES = 0x00186708
SET_AVAILABILITY = 0x001878e0
ASSIGN_CAR = 0x00187a68
SET_DEFAULT_CAR = 0x00187a78
SET_CHARACTER = 0x00187ce0
SET_OFFSETS = 0x001056d8
LOADER_CHAR = 0x001d9330
UNLOADER_CHAR = 0x001d93b0
GET_BODY = 0x001d93f8
GET_CHAR_NAME = 0x001d9480
GET_CHAR_HASH = 0x001d9508
GET_CHAR_NUM = 0x001d9588
GET_CHAR = 0x001d9590
LOADER_TRACK = 0x00153608

IS_CAR_UNLOCKED = 0x0024b208
TRANSLATE = 0x0021e560
AUDIO_DEFAULTS = 0x001ef1c8

G_CARS = GP - 20616               # CarTypeInfoArray
G_TRACKS = GP - 21948             # TrackInfoTable
G_HIGHEST = GP - 21944            # HighestTrackNumber
G_BODY = GP - 17700               # pBodyTypeInfo
G_NBODY = GP - 17696
G_CHAR = GP - 17692               # pCharacterInfo
G_NCHAR = GP - 17688
G_CAL_X = GP - 16896              # DisplayCalibrationOriginalX
G_CAL_Y = GP - 16892

VARS = {
    "skipfe": GP - 23220, "e3": GP - 23224, "rearview": GP - 23168,
    "speedo": GP - 23152, "jump": GP - 23144, "zone": GP - 23140,
    "dp1type": GP - 23136, "dp2type": GP - 23132, "dp1skin": GP - 23128,
    "dp2skin": GP - 23124, "pov": GP - 23172, "lang": CURR_LANGUAGE,
    "video": GP - 19612, "seed": SEED,
}

FPI = FRED + 67384                # FrontendPlayers[0]
FPI_SIZE = 1744
GAME_TYPE = FRED + 67372
HIGH_SCORES = FRED + 1720

SPAN = 0x40000
SLOT_BASE = 0x01000000            # four chunk slots
CARS = 0x01200000
TRK = 0x01300000
STRS = 0x01400000
NAMES = 0x01410000
SCRATCH = 0x01420000

CAR_REC = 1376
TRK_REC = 164
CAR_CHUNK, TRACK_CHUNK = 0x34600, 0x34201
CHAR_CHUNK, BODY_CHUNK = 0x34300, 0x34301

# CarTypeInfo, retail's offsets.
GEOMETRY, DASH_GEOMETRY = 64, 128
NUM_SKINS = 229
USAGE, INITIAL_LOCK, COP_LOCK = 1336, 1340, 1344
SKINS = 1348

# TrackInfo.
IS_VALID, TRACK_NUMBER, SAME_AS, TIME_OF_DAY = 64, 65, 66, 68


def bhash(s):
    h = 0xffffffff
    for c in s:
        h = (h * 33 + c) & M32
    return h


# ================================================================ the data

def globalb_chunks():
    data = GLOBALB.read_bytes()
    out = {}
    off = 0
    while off + 8 <= len(data):
        cid, size = struct.unpack_from("<II", data, off)
        if cid in (CAR_CHUNK, TRACK_CHUNK, CHAR_CHUNK, BODY_CHUNK):
            out[cid] = data[off:off + 8 + size]
        off += 8 + size
    return out


class Tracks(object):
    """The track table as the script leaves it, to keep every scenario off
    the one path the image reads through NULL: a twin whose own record
    GetTrackInfo refuses, and InitWithDefaults' track 11."""

    def __init__(self, chunk):
        self.recs = bytearray(chunk[8:])
        self.high = len(self.recs) // TRK_REC

    def rec(self, i):
        if i <= 0 or i > self.high:
            return None
        r = self.recs[TRK_REC * (i - 1):TRK_REC * i]
        return r if r[0] else None

    def put(self, i, off, n, v):
        struct.pack_into("<" + {1: "b", 2: "h", 4: "i"}[n],
                         self.recs, TRK_REC * (i - 1) + off, v)

    def safe_stats(self):
        for i in range(1, self.high + 1):
            r = self.rec(i)
            if r is None or not r[IS_VALID]:
                continue
            tn, same = struct.unpack_from("<bb", r, TRACK_NUMBER)
            if tn != same:
                assert self.rec(same) is not None, "track %d's twin" % i

    def safe_defaults(self):
        self.safe_stats()
        assert self.rec(11) is not None, "no track 11"


class Script(object):
    def __init__(self, ch):
        self.ch = ch
        self.ops = []
        self.trk = Tracks(ch[TRACK_CHUNK])

    def op(self, *parts):
        self.ops.append(" ".join(str(p) for p in parts))

    def load_all(self):
        """The four chunks into their places, as GLOBALB loads them."""
        self.op("K", 0, self.ch[BODY_CHUNK].hex())
        self.op("K", 1, self.ch[CHAR_CHUNK].hex())
        self.op("L", 0)
        self.op("L", 1)
        self.op("KC", self.ch[CAR_CHUNK][16:16 + 64 * CAR_REC].hex())
        self.op("KT", self.ch[TRACK_CHUNK].hex())
        self.trk = Tracks(self.ch[TRACK_CHUNK])
        self.trk.put(54, 0, 1, 0)       # the loader clears 54

    def car(self, t, off, n, v):
        self.op("cr", t, off, n, v)

    def track(self, i, off, n, v):
        self.trk.put(i, off, n, v)
        self.op("tr", i, off, n, v)

    def high(self, n):
        self.trk.high = n
        self.op("th", n)

    def I(self):
        self.trk.safe_defaults()
        self.op("I")

    def H(self):
        self.trk.safe_stats()
        self.op("H")

    def name(self, nid, s):
        self.op("n", "%x" % nid, "-" if s is None else (s + b"\0").hex())


PLAYER1, PLAYER2 = 0x27165, 0x27166
DISC_VARS = {"skipfe": 0, "e3": 0, "rearview": 1, "speedo": 1, "jump": 1,
             "zone": 1, "dp1type": 37, "dp2type": 37, "dp1skin": 1,
             "dp2skin": 1, "pov": 1, "lang": 0, "video": 0}


def reset_vars(s):
    for k, v in DISC_VARS.items():
        s.op("v", k, v)
    s.op("u", 0, 0, 0, 0)
    s.op("nr")
    s.op("w", 0)


def s_boot(ch):
    """What the boot does, over the image's own values: nothing set."""
    s = Script(ch)
    s.op("F", "00")
    s.op("SF")
    s.op("SR")
    s.load_all()
    s.name(PLAYER1, b"Player1")
    s.name(PLAYER2, b"Player2")
    s.I()
    s.op("R")
    s.op("C")
    s.op("D")
    for g in (7, 3, 0):
        s.op("G", g)
        s.op("C")
    s.H()
    # SkipFE on, with every word it reads at the image's own value.
    s.op("v", "skipfe", 1)
    s.op("D")
    s.op("R")
    s.I()
    return s.ops


def s_ctor(ch):
    """The constructors over patterns, so every byte they leave shows."""
    s = Script(ch)
    for b in ("ff", "a5", "81", "00"):
        s.op("F", b)
        s.op("SF")
        s.op("SR")
    s.op("F", "5a")
    s.op("SR")
    s.op("SF")
    return s.ops


def s_skipfe(ch):
    """The SkipFE words, the POV, the language, the video mode and the
    offsets, under InitWithDefaults and the two settings' defaults."""
    s = Script(ch)
    reset_vars(s)
    s.load_all()
    s.op("F", "c3")
    s.op("v", "skipfe", 1)
    s.op("v", "pov", 0x203)
    s.op("v", "rearview", 0)
    s.op("v", "speedo", 0x102)
    s.op("v", "jump", 0)
    s.op("v", "zone", 0x80)
    s.op("v", "dp1type", 21)          # dash geometry
    s.op("v", "dp2type", 23)
    s.op("v", "dp1skin", 3)
    s.op("v", "dp2skin", 7)           # not among the F50's
    s.I()
    s.op("R")
    s.op("D")
    s.op("v", "skipfe", 0)
    for lang in (0, 1, -1, 5):
        s.op("v", "lang", lang)
        s.op("D")
        s.op("R")
    s.op("o", 0, 56, 27)
    s.op("o", 1, -3, 9)
    for video in (0, 1):
        s.op("v", "video", video)
        s.op("F", "3c")
        s.I()
        s.op("E", 5 + video, -7)
        s.I()
    s.op("v", "skipfe", 7)
    s.op("v", "pov", 0xff)
    s.op("v", "rearview", -1)
    s.op("v", "jump", 0x1ff)
    s.I()
    s.op("D")
    s.op("R")
    return s.ops


def s_unlock(ch):
    """MakeChallengeCarsAvailable under every game type, unlock rules and
    the E3 build's word."""
    s = Script(ch)
    reset_vars(s)
    s.load_all()
    s.op("F", "00")
    s.op("SF")
    rules = [(0, 0, 0, 0), (1, 0, 0, 3), (3, 1, 2, 5), (0, 0, 0, 1),
             (1, 7, 0, 2)]
    for e3 in (0, 1):
        s.op("v", "e3", e3)
        for rule in rules:
            s.op("u", *rule)
            for g in (0, 7, 3, 1, 10):
                s.op("G", g)
                s.op("C")
    s.op("u", 1, 1, 1, 4)
    s.op("v", "e3", 1)
    s.I()
    s.op("v", "e3", 0)
    s.I()
    return s.ops


def s_cars(ch):
    """The records changed field by field, then the availability, the
    rides and the defaults over them."""
    s = Script(ch)
    reset_vars(s)
    s.load_all()
    s.op("F", "00")
    s.op("SF")
    s.car(5, GEOMETRY, 1, 0)                  # no geometry: skipped
    s.car(0, USAGE, 4, 1)                     # a cop: one skin, by language
    s.car(2, NUM_SKINS, 1, 0)                 # no skins
    s.car(3, NUM_SKINS, 1, -1)                # fewer than none
    s.car(7, NUM_SKINS, 1, 10)
    for k, v in enumerate((9, 0xff, 0x80, 1, 7, 2, 3, 4, 5, 6)):
        s.car(7, SKINS + k, 1, v)
    s.car(9, NUM_SKINS, 1, 12)                # past the ten kept
    s.car(9, SKINS + 10, 1, 0x44)
    s.car(9, SKINS + 11, 1, 0x55)
    s.car(13, NUM_SKINS, 1, 11)
    for t, v in ((11, 0), (12, 1), (14, 2), (15, 3), (16, 5), (17, -1)):
        s.car(t, INITIAL_LOCK, 4, v)
    for t, v in ((31, 0), (32, 2), (33, 3), (34, 4), (4, -2)):
        s.car(t, COP_LOCK, 4, v)
    s.car(19, USAGE, 4, 1)                    # a racer made a cop
    s.car(31, USAGE, 4, 0)                    # and a cop made a racer
    s.car(20, DASH_GEOMETRY, 1, ord("D"))
    s.car(62, GEOMETRY, 1, 0)
    for lang in (0, 1):
        s.op("v", "lang", lang)
        for e3 in (0, 1):
            s.op("v", "e3", e3)
            for g in (0, 7, 3):
                s.op("G", g)
                s.op("C")
    s.op("u", 1, 0, 0, 4)
    s.op("G", 7)
    s.op("C")
    s.op("G", 2)
    s.op("C")
    s.op("u", 0, 0, 0, 0)
    # SetCarAvailability: every skin, one skin, a skin past a byte, a dash.
    for p, st, t, sk, da in ((0, 2, 9, -1, 1), (1, 0, 9, -1, 0),
                             (0, 1, 7, -1, 1), (0, 0, 2, -1, 1),
                             (1, 4, 3, -1, 0), (0, 0, 0, -1, 1),
                             (0, 3, 21, 300, 1), (1, 0, 23, 2, 1),
                             (1, 0, 20, -2, 7), (0, 0, 13, -1, 1)):
        s.op("A", p, st, t, sk, da)
    # AssignCarOfType: the skin found, not found, past the ten (the image
    # reads on into the record), past a byte; the dash every way.
    for p, mo, t, sk, da in ((0, 0, 9, 0x44, 1), (0, 1, 9, 0x55, 0),
                             (0, 2, 9, 3, 1), (0, 3, 9, 99, 1),
                             (0, 4, 7, 0x80, 1), (0, 5, 7, 0x180, 1),
                             (0, 6, 2, 1, 1), (1, 7, 23, 2, 1),
                             (1, 8, 23, 2, 0), (1, 9, 20, 0, 1),
                             (0, 10, 21, 44, 1), (1, 0, 3, 5, 1),
                             (0, 7, 13, 0, 1), (0, 8, 13, 9, 1)):
        s.op("O", p, mo, t, sk, da)
    s.op("T", 0, 21, 4, 1)
    s.op("T", 1, 9, 0x55, 0)
    s.op("T", 0, 7, 0xff, 1)
    s.op("A", 1, 0, 20, -1, 0)
    s.op("O", 1, 2, 20, 0, 1)
    s.op("T", 1, 20, 0, 1)
    # A negative count, from a fill: the skin asked for stands.
    s.op("F", "ff")
    s.op("O", 0, 3, 11, 77, 1)
    s.op("T", 1, 12, 0x105, 1)
    s.op("A", 0, 1, 11, 6, 0)
    s.op("O", 0, 4, 11, 6, 1)
    # SetCharacterInfo, in and out of range.
    for p, i in ((0, 3), (1, 9), (0, 10), (1, -1), (0, 0)):
        s.op("c", p, i)
    s.op("v", "dp1type", 9)
    s.op("v", "dp2type", 0)
    s.op("v", "dp1skin", 0x55)
    s.op("v", "dp2skin", -1)
    s.op("v", "skipfe", 1)
    s.I()
    s.op("v", "dp1type", 20)
    s.op("v", "dp2type", 7)
    s.op("v", "dp1skin", 0x100)
    s.op("v", "dp2skin", 0xff)
    s.I()
    s.op("v", "skipfe", 0)
    s.I()
    s.op("v", "dp1type", 7)
    s.op("v", "dp2type", 7)
    s.op("v", "dp1skin", -1)
    s.op("v", "dp2skin", 7)
    s.I()
    return s.ops


def s_tracks(ch):
    """InitStatsTables and the track select's defaults over tables changed
    record by record."""
    s = Script(ch)
    reset_vars(s)
    s.load_all()
    s.op("F", "00")
    s.op("SF")
    s.H()
    s.op("F", "77")
    s.H()
    # Every twin its own: thirty unique tracks, past the sixteen numbered.
    for i in (14, 15, 16, 24, 25, 26, 34, 35, 36, 44, 45, 46, 64, 65, 66):
        s.track(i, SAME_AS, 1, i)
    s.H()
    # Back to twins of other tracks, some invalid, one renumbered.
    s.track(15, SAME_AS, 1, 12)
    s.track(25, SAME_AS, 1, 31)
    s.track(12, IS_VALID, 1, 0)           # its twin still reads it
    s.track(22, TRACK_NUMBER, 1, 99)      # now a twin of itself
    s.track(42, IS_VALID, 1, 0)
    s.track(43, TRACK_NUMBER, 1, 13)      # a twin of 43, by 43
    s.track(43, SAME_AS, 1, 43)
    s.H()
    s.high(40)
    s.H()
    s.high(5)
    s.H()
    s.high(66)
    s.track(11, SAME_AS, 1, 13)
    s.track(11, TIME_OF_DAY, 2, 7)
    s.I()
    s.track(11, TIME_OF_DAY, 2, -3)
    s.track(11, IS_VALID, 1, 0)          # the stats skip it, the select
    s.track(11, SAME_AS, 1, -5)          # does not
    s.I()
    s.high(11)
    s.I()
    return s.ops


def s_chars(ch):
    """The character data's loader, unloader and getters, and the
    defaults with characters missing."""
    s = Script(ch)
    reset_vars(s)
    s.load_all()
    s.op("F", "00")
    names = [b"Rick", b"RICK", b"rick", b"Ri", b"Rickx", b"FatCop",
             b"fatcop", b"Cop", b"Liv", b"", b"Nobody", b"cop3"]
    bodies = [b"Male", b"MALE", b"Female", b"Cop", b"Cop3", b"cop3",
              b"Fem", b"", b"Rick"]
    for n in names:
        s.op("qc", (n + b"\0").hex())
    for n in bodies:
        s.op("qb", (n + b"\0").hex())
    for h in [bhash(n) for n in names] + [0x5d6aefdc, 0x9f61, 0]:
        s.op("qh", "%x" % h)
    for i in (-1, 0, 1, 9, 10, 100):
        s.op("qi", i)
    s.op("qn")
    # Unloaded: nothing found, and the defaults keep the players' own.
    s.op("U", 1)
    s.op("qn")
    s.op("qc", (b"Rick" + b"\0").hex())
    s.op("qi", 0)
    s.op("F", "61")
    s.I()
    s.op("U", 0)
    s.op("qb", (b"Male" + b"\0").hex())
    s.op("U", 2)
    # Short and odd chunks: one character, a size past a record, none, an
    # id neither loader takes.
    one = ch[CHAR_CHUNK][8:8 + 68]
    s.op("K", 2, (struct.pack("<II", CHAR_CHUNK, 68) + one).hex())
    s.op("L", 2)
    s.op("qn")
    s.op("qi", 1)
    s.I()
    s.op("K", 2, (struct.pack("<II", CHAR_CHUNK, 3 * 68 - 1)
                  + ch[CHAR_CHUNK][8:8 + 3 * 68]).hex())
    s.op("L", 2)
    s.op("qn")
    s.op("qc", (b"Ashley" + b"\0").hex())
    bodies = ch[BODY_CHUNK][8:]
    for size in (359, 540, 541):
        s.op("K", 3, (struct.pack("<II", BODY_CHUNK, size)
                      + bodies[:size]).hex())
        s.op("L", 3)
        s.op("qb", (b"Cop" + b"\0").hex())
        s.op("qb", (b"Female" + b"\0").hex())
    s.op("K", 3, (struct.pack("<II", BODY_CHUNK, 0)).hex())
    s.op("L", 3)
    s.op("qb", (b"Male" + b"\0").hex())
    s.op("K", 3, (struct.pack("<II", 0x34302, 68) + one).hex())
    s.op("L", 3)
    s.op("U", 3)
    s.op("L", 0)
    s.op("L", 1)
    s.op("qn")
    return s.ops


def s_names(ch):
    """The two players' names: short, exactly ten, eleven and past, empty,
    missing, over fills that show the eleventh byte."""
    s = Script(ch)
    reset_vars(s)
    s.load_all()
    cases = [(b"Player1", b"Player2"), (b"ABCDEFGHIJ", b"ABCDEFGHIJK"),
             (b"ABCDEFGHIJKLMNOP", b""), (None, b"x"), (None, None)]
    for b, (n1, n2) in zip(("00", "aa", "ff", "5c", "01"), cases):
        s.op("nr")
        s.name(PLAYER1, n1)
        s.name(PLAYER2, n2)
        s.op("F", b)
        s.I()
    return s.ops


def s_rp(ch):
    """The race parameters' defaults over patterns, and the seed they draw
    New780 from."""
    s = Script(ch)
    reset_vars(s)
    s.load_all()
    for seed in (0, 1, 0xffffffff, 0x12345678, 0x80000000):
        s.op("v", "seed", seed)
        s.op("F", "5a")
        s.op("R")
        s.op("R")
    s.op("F", "a5")
    s.op("SR")
    s.op("v", "skipfe", 1)
    s.op("v", "pov", 4)
    s.op("v", "speedo", 0)
    s.op("R")
    s.op("SR")
    return s.ops


def script():
    ch = globalb_chunks()
    return [s_boot(ch), s_ctor(ch), s_skipfe(ch), s_unlock(ch), s_cars(ch),
            s_tracks(ch), s_chars(ch), s_names(ch), s_rp(ch)]


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
        self.quiet = False
        self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        e = self.e
        e.stub(IS_CAR_UNLOCKED, self.is_car_unlocked)
        e.stub(TRANSLATE, self.translate)
        e.stub(AUDIO_DEFAULTS, self.audio_defaults)
        self.rule = (0, 0, 0, 0)
        self.names = []
        self.salt = 0
        self.records = 0
        self.shown_fred = bytes(FRED_SIZE)
        self.shown_rp = bytes(RP_COMMON)
        self.shown_tail = ""
        self.shown_di = [""] * NUM_DI
        self.shown_trk = bytes(SPAN)
        self.shown_g = ""
        self.shown_scratch = bytes(8)

    def emit(self, s):
        if not self.quiet:
            self.out.append(s)

    # ---- the stubs -------------------------------------------------------

    def is_car_unlocked(self, e):
        t, g = s32(e.reg[4]), s32(e.reg[5])
        a, b, c, m = self.rule
        r = int(m != 0 and ((t * a + g * b + c) & M32) % (m & M32) == 0)
        self.emit("u %d %d -> %d" % (t, g, r))
        return r

    def translate(self, e):
        nid = s32(e.reg[4])
        self.emit("n %x" % (nid & M32))
        for k, (i, s) in enumerate(self.names):
            if i == nid:
                if s is None:
                    return NOT_TRANSLATED
                a = NAMES + 64 * k
                e.write(a, bytes(64))
                e.write(a, s[:63])
                return a
        return NOT_TRANSLATED

    def audio_defaults(self, e):
        a = e.reg[4] & M32
        self.emit("a +%d" % (a - FRED))
        e.write(a, bytes((i * 7 + self.salt) & 0xff for i in range(176)))
        return None

    # ---- the prints ------------------------------------------------------

    def label(self, a):
        a &= M32
        if a == 0:
            return "NULL"
        if a == DIT:
            return "DIT"
        for k in range(4):
            base = SLOT_BASE + SPAN * k
            if base <= a < base + SPAN:
                return "k%d+%d" % (k, a - base)
        if CARS <= a < CARS + 64 * CAR_REC:
            return "cars+%d" % (a - CARS)
        if TRK <= a < TRK + SPAN:
            return "trk+%d" % (a - TRK)
        return "?"

    def rows(self, tag, cur, shown, width):
        out = bytearray(shown)
        for off in range(0, len(cur), 32):
            c = cur[off:off + 32]
            if c != shown[off:off + 32]:
                self.emit("%s %0*x %s" % (tag, width, off, c.hex()))
                out[off:off + len(c)] = c
        return bytes(out)

    def print_state(self):
        e = self.e
        self.shown_fred = self.rows("f", e.read(FRED, FRED_SIZE),
                                    self.shown_fred, 5)
        self.shown_rp = self.rows("r", e.read(RP, RP_COMMON), self.shown_rp,
                                  3)
        s = "rp %s %d %08x %08x" % (
            self.label(e.u32(RP + 772)), s32(e.u32(RP + 776)),
            e.u32(RP + 780), e.u32(RP + 784))
        if s != self.shown_tail:
            self.emit(s)
            self.shown_tail = s
        for i in range(NUM_DI):
            a = DIT + DI_SIZE * i
            b = e.read(a, DI_SIZE)
            elim, uniq, char, skill, start = struct.unpack_from("<5b", b, 0)
            s = "d %d %d %d %d %d %d %d %s %s" % (
                i, elim, uniq, char, skill, start, s32(e.u32(a + 8)),
                b[12:20].hex(), self.label(e.u32(a + 20)))
            if s != self.shown_di[i]:
                self.emit(s)
                self.shown_di[i] = s
        shown = bytearray(self.shown_trk)
        for i in range(self.records):
            a = 8 + TRK_REC * i
            r = e.read(TRK + a, TRK_REC)
            if r != self.shown_trk[a:a + TRK_REC]:
                self.emit("t %d %s" % (i + 1, r.hex()))
                shown[a:a + TRK_REC] = r
        self.shown_trk = bytes(shown)
        off = [s32(e.u32(OFFSETS + 4 * k)) for k in range(4)]
        s = ("g seed=%08x ox=%d oy=%d high=%d tab=%s ct=%s bt=%s nb=%d "
             "ci=%s nc=%d off=%d,%d,%d,%d" % (
                 e.u32(SEED), s32(e.u32(G_CAL_X)), s32(e.u32(G_CAL_Y)),
                 s32(e.u32(G_HIGHEST)), self.label(e.u32(G_TRACKS)),
                 self.label(e.u32(G_CARS)), self.label(e.u32(G_BODY)),
                 s32(e.u32(G_NBODY)), self.label(e.u32(G_CHAR)),
                 s32(e.u32(G_NCHAR)), off[0], off[1], off[2], off[3]))
        if s != self.shown_g:
            self.emit(s)
            self.shown_g = s
        sc = e.read(SCRATCH, 8)
        if sc != self.shown_scratch:
            self.emit("s %s" % sc.hex())
            self.shown_scratch = sc

    # ---- the ops ---------------------------------------------------------

    def call(self, addr, *args):
        # Sign-extended, as the EE's 64-bit registers hold an int.
        return self.e.call(addr, *[s32(a & M32) for a in args],
                           limit=50000000)

    def fill(self, b):
        e = self.e
        e.write(FRED, bytes([b]) * FRED_SIZE)
        e.write(RP, bytes([b]) * 788)
        e.write(DIT, bytes([b]) * (DI_SIZE * NUM_DI))
        e.write(SCRATCH, bytes([b]) * 8)
        e.put32(G_CAL_X, 0x01010101 * b)
        e.put32(G_CAL_Y, 0x01010101 * b)
        self.quiet = True
        self.print_state()
        self.quiet = False

    def string(self, h):
        b = bytes.fromhex(h)
        self.e.write(STRS, bytes(4096))
        self.e.write(STRS, b)
        return STRS

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
                elif op == "SF":
                    self.call(SINIT_FRED)
                elif op == "SR":
                    self.call(SINIT_RP)
                elif op == "I":
                    self.call(INIT_FRED)
                elif op == "C":
                    self.call(CHALLENGE_CARS, FRED)
                elif op == "R":
                    self.call(RP_DEFAULTS, RP)
                elif op == "D":
                    self.call(DISPLAY_DEFAULTS, SCRATCH)
                elif op == "H":
                    self.call(STATS_TABLES, HIGH_SCORES)
                elif op == "G":
                    e.put32(GAME_TYPE, int(a[0]))
                elif op == "A":
                    p, st, ty, sk, da = map(int, a)
                    self.call(SET_AVAILABILITY, FPI + FPI_SIZE * p, st, ty,
                              sk, da)
                elif op == "O":
                    p, mo, ty, sk, da = map(int, a)
                    self.call(ASSIGN_CAR, FPI + FPI_SIZE * p, mo, ty, sk, da)
                elif op == "T":
                    p, ty, sk, da = map(int, a)
                    self.call(SET_DEFAULT_CAR, FPI + FPI_SIZE * p, ty, sk, da)
                elif op == "c":
                    p, i = map(int, a)
                    self.call(SET_CHARACTER, FPI + FPI_SIZE * p, i)
                elif op == "E":
                    self.call(SET_OFFSETS, int(a[0]), int(a[1]))
                elif op == "K":
                    base = SLOT_BASE + SPAN * int(a[0])
                    e.write(base, bytes(SPAN))
                    e.write(base, bytes.fromhex(a[1]))
                    continue
                elif op in ("L", "U"):
                    k = int(a[0])
                    ret = self.call(LOADER_CHAR if op == "L" else
                                    UNLOADER_CHAR, SLOT_BASE + SPAN * k)
                    self.emit("%s %d -> %d" % (op, k, ret))
                elif op == "KC":
                    e.write(CARS, bytes(64 * CAR_REC))
                    e.write(CARS, bytes.fromhex(a[0]))
                    e.put32(G_CARS, CARS)
                elif op == "KT":
                    d = bytes.fromhex(a[0])
                    e.write(TRK, bytes(SPAN))
                    e.write(TRK, d)
                    self.records = (len(d) - 8) // TRK_REC
                    self.shown_trk = e.read(TRK, SPAN)
                    self.emit("KT -> %d" % self.call(LOADER_TRACK, TRK))
                elif op in ("cr", "tr"):
                    i, off, size, v = map(int, a)
                    base = (CARS + CAR_REC * i if op == "cr"
                            else TRK + 8 + TRK_REC * (i - 1))
                    e.write(base + off, (v & ((1 << (8 * size)) - 1))
                            .to_bytes(size, "little"))
                elif op == "th":
                    e.put32(G_HIGHEST, int(a[0]))
                elif op in ("qb", "qc"):
                    p = self.string(a[0] if a else "")
                    r = self.call(GET_BODY if op == "qb" else GET_CHAR_NAME,
                                  p)
                    self.emit("%s -> %s" % (op, self.label(r)))
                elif op == "qh":
                    r = self.call(GET_CHAR_HASH, int(a[0], 16))
                    self.emit("qh -> %s" % self.label(r))
                elif op == "qi":
                    r = self.call(GET_CHAR, int(a[0]))
                    self.emit("qi -> %s" % self.label(r))
                elif op == "qn":
                    self.emit("qn -> %d" % self.call(GET_CHAR_NUM))
                elif op == "v":
                    e.put32(VARS[a[0]], int(a[1], 0))
                elif op == "u":
                    self.rule = tuple(map(int, a))
                    continue
                elif op == "n":
                    self.names.append((s32(int(a[0], 16)), None
                                       if a[1] == "-" else
                                       bytes.fromhex(a[1])))
                    continue
                elif op == "nr":
                    self.names = []
                    continue
                elif op == "w":
                    self.salt = int(a[0])
                    continue
                elif op == "o":
                    m, x, y = map(int, a)
                    e.put32(OFFSETS + 8 * m, x)
                    e.put32(OFFSETS + 8 * m + 4, y)
                else:
                    raise SystemExit("bad op %r" % (t,))
                self.print_state()
        return self.out


# ================================================================ the build


def build_harness(tmp, name="fred_test"):
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


def M(name, before, after, rel=FRC):
    return (name, rel, before, after)


MUTATIONS = [
    # fred.c: the constructor.
    M("ctor-audio-175", "    f->AudioOptionsScreenData[175] = 0;\n", ""),
    M("ctor-audio-byte-2", "        e[2] = 0;\n", ""),
    M("ctor-ride-type", "        r->Type = -1;\n", "        r->Type = 0;\n"),
    M("ctor-status-available",
      "            fpi->aCarStatus[i].nStatus = CAR_STATUS_HIDDEN;\n",
      "            fpi->aCarStatus[i].nStatus = CAR_STATUS_AVAILABLE;\n"),
    M("ctor-ten-laps", "        for (j = 0; j < 11; j++)\n",
      "        for (j = 0; j < 10; j++)\n"),
    M("ctor-one-player", "    for (p = 0; p < 2; p++) {\n        FrontendPlayerInfo *fpi",
      "    for (p = 0; p < 1; p++) {\n        FrontendPlayerInfo *fpi"),
    # The players' cars and characters.
    M("character-short-copy", "memcpy(&p->mCharacterInfo, ci, sizeof p->mCharacterInfo);",
      "memcpy(&p->mCharacterInfo, ci, sizeof p->mCharacterInfo - 4);"),
    M("offer-all-capped",
      "            cs->aSkins[cs->nSkins] = s;\n        cs->nSkins++;\n",
      "            cs->aSkins[cs->nSkins++] = s;\n"),
    M("offer-all-eleven", "        if (cs->nSkins < FRED_MAX_SKINS)\n",
      "        if (cs->nSkins <= FRED_MAX_SKINS)\n"),
    M("availability-dash-bool", "    cs->bDashAvailable = dash;\n",
      "    cs->bDashAvailable = dash != 0;\n"),
    M("availability-any-negative", "    if (skin == -1) {\n",
      "    if (skin < 0) {\n"),
    M("availability-skin-masked", "    cs->aSkins[0] = (uint8_t)skin;\n",
      "    cs->aSkins[0] = (uint8_t)(skin & 0x3f);\n"),
    M("ride-skin-byte", "skins[i] != skin)", "skins[i] != (uint8_t)skin)"),
    M("ride-negative-count", "    if (i == n)\n        skin = cs->aSkins[0];",
      "    if (i >= n)\n        skin = cs->aSkins[0];"),
    M("ride-dash-always",
      "        hasDash = CarTypeInfoArray[type].DashGeometryFilename[0] != 0;",
      "        hasDash = 1;"),
    M("ride-dash-unoffered",
      "    if (dash != 0 && cs->bDashAvailable != 0)\n",
      "    if (dash != 0)\n"),
    M("ride-vertex-damaged", "    ride->CanBeVertexDamaged = 0;\n",
      "    ride->CanBeVertexDamaged = 1;\n"),
    M("default-car-ten-modes",
      "    for (mode = 0; mode < FRED_NUM_GAME_MODES; mode++)\n        fpi_assign",
      "    for (mode = 0; mode < FRED_NUM_GAME_MODES - 1; mode++)\n        fpi_assign"),
    # MakeChallengeCarsAvailable.
    M("challenge-no-cop-game",
      "    if (f->GameType == GAME_TYPE_BE_A_COP) {\n",
      "    if (0) {\n"),
    M("challenge-every-car-valid",
      "    return ct->GeometryFilename[0] != 0;\n", "    return 1;\n"),
    M("challenge-cop-usage", "            if (ct->UsageType != 1)\n",
      "            if (ct->UsageType != 2)\n"),
    M("challenge-cop-lock", "                status = ct->BeACopLockStatus;\n",
      "                status = ct->InitialLockStatus;\n"),
    M("challenge-racer-game",
      "            else if (is_car_unlocked(type, 3))\n",
      "            else if (is_car_unlocked(type, f->GameType))\n"),
    M("challenge-cop-game-e3-swapped",
      "                status = ct->InitialLockStatus == CAR_STATUS_HIDDEN\n"
      "                    ? CAR_STATUS_HIDDEN : CAR_STATUS_AVAILABLE;",
      "                status = ct->InitialLockStatus == CAR_STATUS_HIDDEN\n"
      "                    ? CAR_STATUS_AVAILABLE : CAR_STATUS_HIDDEN;"),
    M("challenge-e3-traffic",
      "                status = ct->UsageType == 1 ? CAR_STATUS_HIDDEN\n",
      "                status = ct->UsageType == 2 ? CAR_STATUS_HIDDEN\n"),
    M("challenge-e3-ignored", "            else if (bVersionE3 == 0)\n"
      "                status = ct->InitialLockStatus;\n            else if",
      "            else if (1)\n"
      "                status = ct->InitialLockStatus;\n            else if"),
    M("challenge-one-player", "    for (p = 0; p < 2; p++) {\n        for (type",
      "    for (p = 0; p < 1; p++) {\n        for (type"),
    # InitStatsTables.
    M("stats-seventeen", "        numbered = next < 16;\n",
      "        numbered = next <= 16;\n"),
    M("stats-unnumbered", "        ti->HighScoreIndex = numbered ? (int16_t)k : 0;\n",
      "        ti->HighScoreIndex = (int16_t)k;\n"),
    M("stats-invalid-numbered",
      "        if (ti == NULL || !ti->IsValid\n"
      "            || ti->TrackNumber != ti->SameAsTrackNumber)",
      "        if (ti == NULL\n"
      "            || ti->TrackNumber != ti->SameAsTrackNumber)"),
    M("stats-twin-off-by-one",
      "            ti->HighScoreIndex = twin->HighScoreIndex;\n",
      "            ti->HighScoreIndex = twin->HighScoreIndex + 1;\n"),
    M("stats-lap-time",
      "        t->LapTimesTable[i].Time.PackedTime = 0x7fffffffu;\n",
      "        t->LapTimesTable[i].Time.PackedTime = 0x7ffffffeu;\n"),
    M("stats-no-clear",
      "    memset(t->TotalTimesTable, 0, sizeof t->TotalTimesTable);\n", ""),
    # The setup data.
    M("single-race-6", "    d[6] = 1;\n    d[1] = 2;\n", "    d[6] = 0;\n    d[1] = 2;\n"),
    M("free-run-0", "    d[0] = 3;\n", "    d[0] = 2;\n"),
    M("lap-knockout-5", "    d[5] = 1;\n", "    d[5] = 2;\n"),
    M("race-knockout-3", "    d[0] = 7;\n    d[3] = 3;\n", "    d[0] = 7;\n    d[3] = 2;\n"),
    M("select-track-number",
      "    d[0] = ti != NULL ? ti->SameAsTrackNumber : 0;\n",
      "    d[0] = ti != NULL ? ti->TrackNumber : 0;\n"),
    M("select-track-time-unsigned",
      "    d[3] = ti != NULL ? ti->TimeOfDay : 0;\n",
      "    d[3] = ti != NULL ? (uint16_t)ti->TimeOfDay : 0;\n"),
    M("event-select-2", "    d[2] = 1;\n    d[0] = 0;\n", "    d[2] = 0;\n    d[0] = 0;\n"),
    M("calibration-swapped", "    eGetScreenDisplayOffsets(&d[0], &d[1]);\n",
      "    eGetScreenDisplayOffsets(&d[1], &d[0]);\n"),
    M("calibration-originals-unset",
      "    eGetScreenDisplayOffsets(&DisplayCalibrationOriginalX,\n"
      "                             &DisplayCalibrationOriginalY);\n", ""),
    # InitWithDefaults.
    M("defaults-game-type", "    f->GameType = 0;\n", "    f->GameType = 7;\n"),
    M("defaults-characters-swapped",
      "        fpi_set_character_info_index(&f->FrontendPlayers[i], i);\n",
      "        fpi_set_character_info_index(&f->FrontendPlayers[i], 1 - i);\n"),
    M("defaults-dash-always", "    dash = config_skip_fe() != 0;\n",
      "    dash = 1;\n"),
    M("defaults-p2-no-dash", "DefaultPlayer2SkinIndex, 1);\n",
      "DefaultPlayer2SkinIndex, 0);\n"),
    M("defaults-p1-skin-as-p2",
      "(uint32_t)DefaultPlayer1SkinIndex, dash);\n",
      "(uint32_t)DefaultPlayer2SkinIndex, dash);\n"),
    M("defaults-points", "    p1->AccumulatedPoints = 0;\n", ""),
    M("defaults-two-cars", "    f->NumPlayerCars = 1;\n", "    f->NumPlayerCars = 2;\n"),
    M("defaults-size", "    f->SavedSizeofFred = (int32_t)sizeof(FrontendDatabase);\n",
      "    f->SavedSizeofFred = (int32_t)sizeof(FrontendDatabase) - 4;\n"),
    M("defaults-challenge-screen", "    f->ChallengeScreenData[1] = 3;\n",
      "    f->ChallengeScreenData[1] = 2;\n"),
    M("defaults-cop-setup", "    f->BeTheCopSetupData[0] = 2;\n",
      "    f->BeTheCopSetupData[0] = 1;\n"),
    M("defaults-audio-offset",
      "        gFredAudioOptionsDefaultsFn(f->AudioOptionsScreenData);\n",
      "        gFredAudioOptionsDefaultsFn(f->AudioOptionsScreenData + 4);\n"),
    M("defaults-main-menu", "    f->MainMenuOpts[1] = 1;\n",
      "    f->MainMenuOpts[1] = 0;\n"),
    M("defaults-hot-pursuit",
      "    memset(f->HotPursuitState, 0, sizeof f->HotPursuitState);\n", ""),
    M("defaults-ultimate", "    f->pUltimateState = 0;\n", ""),
    M("defaults-name-table",
      "    memset(f->HighScoreNameTable, 0, sizeof f->HighScoreNameTable);\n", ""),
    M("defaults-no-stats",
      "    high_score_table_init_stats_tables(&f->ChallengeHighScores);\n", ""),
    M("defaults-aborted", "    f->bRaceWasAborted = 0;\n", ""),
    M("name-ten", "#define FRED_NAME_COPY 11\n", "#define FRED_NAME_COPY 10\n"),
    M("name-past-terminator",
      "        if (src[i] == '\\0')\n            break;\n", ""),
    M("name-ids-swapped", "#define FRED_PLAYER1_NAME_ID 0x27165\n",
      "#define FRED_PLAYER1_NAME_ID 0x27166\n"),
    M("name-fallback", '    return s != NULL ? s : "NOT TRANSLATED PROPERLY";\n',
      '    return s != NULL ? s : "Not translated properly";\n'),
    # raceparams.c.
    M("rp-track", "    rp->TrackNumber = 11;\n", "    rp->TrackNumber = 12;\n", RPC),
    M("rp-oncoming", "    rp->TrafficOncoming = 0.5f;\n",
      "    rp->TrafficOncoming = 0.25f;\n", RPC),
    M("rp-start-2", "    rp->PlayerStartPosition[1] = 8;\n",
      "    rp->PlayerStartPosition[1] = 7;\n", RPC),
    M("rp-new624", "    rp->New624 = 1;\n", "    rp->New624 = 0;\n", RPC),
    M("rp-boost-0", "    rp->BoostScale[0] = 1.0f;\n",
      "    rp->BoostScale[0] = 0.5f;\n", RPC),
    M("rp-dit-kept", "    memset(DriverInfoTable, 0, sizeof DriverInfoTable);\n",
      "", RPC),
    M("rp-num-di", "    rp->NumDriverInfo = 0;\n", "    rp->NumDriverInfo = 1;\n",
      RPC),
    M("rp-p2-settings", "    player_settings_reset_to_defaults(&rp->PlayerSettings[1]);\n",
      "", RPC),
    M("rp-seed-range", "bRandomI(-1, &bDefaultSeed)",
      "bRandomI(0x7fffffff, &bDefaultSeed)", RPC),
    M("rp-new784", "    rp->New784 = 0;\n", "    rp->New784 = 1;\n", RPC),
    M("rp-display", "    global_display_settings_init_with_defaults(&rp->GlobalDisplaySettings);\n",
      "", RPC),
    M("display-rear-view", "(int8_t)(uint8_t)SkipFERearView : 1;",
      "(int8_t)(uint8_t)SkipFERearView : 0;", RPC),
    M("display-units-one",
      "(gCurrLanguageFn != NULL ? gCurrLanguageFn() : 0) != 0);",
      "(gCurrLanguageFn != NULL ? gCurrLanguageFn() : 0) == 1);", RPC),
    M("display-two-player-map", "    d->TwoPlayerTrackMapMode = 7;\n",
      "    d->TwoPlayerTrackMapMode = 6;\n", RPC),
    M("display-jump", "(int8_t)(uint8_t)SkipFEEnableJumpCam : 1;",
      "(int8_t)(uint8_t)SkipFEEnableJumpCam : 0;", RPC),
    M("display-zone-bool", "(int8_t)(uint8_t)SkipFEEnableZoneCam",
      "(int8_t)(SkipFEEnableZoneCam != 0)", RPC),
    M("sinit-ride-type", "        di->CurrentRideInfo.Type = -1;\n",
      "        di->CurrentRideInfo.Type = 0;\n", RPC),
    M("sinit-no-defaults",
      "    race_parameters_init_with_defaults(rp);\n    for", "    for", RPC),
    # characterinfo.c.
    M("body-stride", "(int32_t)(size / 180u);", "(int32_t)(size / 176u);", CIC),
    M("character-stride", "(int32_t)(size / 68u);", "(int32_t)(size / 64u);", CIC),
    M("loader-takes-any", "        return 1;\n    }\n    return 0;\n}\n\nint unloader",
      "        return 1;\n    }\n    return 1;\n}\n\nint unloader", CIC),
    M("unloader-count-kept",
      "        pCharacterInfo = NULL;\n        NumCharacterInfo = 0;\n",
      "        pCharacterInfo = NULL;\n", CIC),
    M("icmp-no-fold", "        v &= 0x5f;\n", "        ;\n", CIC),
    M("icmp-prefix",
      "        if (ca == 0 || cb == 0 || ca != cb)\n            return ca - cb;",
      "        if (ca == 0 || cb == 0 || ca != cb)\n"
      "            return ca == 0 || cb == 0 ? 0 : ca - cb;", CIC),
    M("body-last-missed",
      "    for (i = 0; i < NumBodyTypeInfo; i++) {\n",
      "    for (i = 0; i < NumBodyTypeInfo - 1; i++) {\n", CIC),
    M("hash-first-missed",
      "    for (i = 0; i < NumCharacterInfo; i++) {\n        if (bchunk_hash",
      "    for (i = 1; i < NumCharacterInfo; i++) {\n        if (bchunk_hash", CIC),
    M("index-past-end", "    if (i < 0 || i >= NumCharacterInfo)\n",
      "    if (i < 0 || i > NumCharacterInfo)\n", CIC),
    M("index-minus-one", "    if (i < 0 || i >= NumCharacterInfo)\n",
      "    if (i < -1 || i >= NumCharacterInfo)\n", CIC),
    # edisplay.c.
    M("offsets-pal-y", "    { 56, 27 },\n", "    { 56, 28 },\n", EDC),
    M("offsets-get-x-from-y", "    *x = ScreenDisplayOffsets[m][0];\n",
      "    *x = ScreenDisplayOffsets[m][1];\n", EDC),
    M("offsets-set-one-mode",
      "    int32_t m = GetVideoMode();\n\n    ScreenDisplayOffsets[m][0] = x;",
      "    int32_t m = 1;\n\n    ScreenDisplayOffsets[m][0] = x;", EDC),
    # The initial values the defaults read.
    M("config-dp1-type", "int32_t DefaultPlayer1CarType = 37;",
      "int32_t DefaultPlayer1CarType = 36;", CFC),
    M("config-dp2-skin", "int32_t DefaultPlayer2SkinIndex = 1;",
      "int32_t DefaultPlayer2SkinIndex = 2;", CFC),
    M("config-speedo", "int32_t SkipFESpeedoMode = 1;",
      "int32_t SkipFESpeedoMode = 2;", CFC),
    M("config-rear-view", "int32_t SkipFERearView = 1;",
      "int32_t SkipFERearView = 0;", CFC),
    M("config-zone", "int32_t SkipFEEnableZoneCam = 1;",
      "int32_t SkipFEEnableZoneCam = 0;", CFC),
    M("settings-pov", "uint8_t PlayerSkipFEPOVIndex = 1;",
      "uint8_t PlayerSkipFEPOVIndex = 2;", PSC),
    M("settings-lookback", "    s->Lookback = 1;\n", "    s->Lookback = 0;\n", PSC),
    M("settings-pov-default", "? (int8_t)PlayerSkipFEPOVIndex : 1;",
      "? (int8_t)PlayerSkipFEPOVIndex : 0;", PSC),
    M("seed", "uint32_t bDefaultSeed = 0x12345678u;",
      "uint32_t bDefaultSeed = 0x12345679u;", "3DS Files/source/bmath.c"),
]

EQUIVALENT = {}


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
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if text.count(probe) != 1:
            missing.append(name)
            print("  %-36s PATTERN %s" % (
                name, "NOT FOUND" if not text.count(probe) else "NOT UNIQUE"))
            continue
        new = text.replace(probe, repl, 1)
        try:
            hostbuild.write_source(path, new)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = build_harness(tmp)
                except SystemExit:
                    print("  %-36s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, scp, out)
                if rc == pcc.HARNESS_HUNG:
                    print("  %-36s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-36s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-36s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-36s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-36s SURVIVED" % name)
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

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None))

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
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
