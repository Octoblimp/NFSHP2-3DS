#!/usr/bin/env python3
"""Cross-check 3DS Files/source/sound.c against the retail image,
SLES_507.31.

**The model** is retail's own Sound.obj run in retail_model.RetailEmu:
InitializeSoundDriver (0x001ae608) and its wait for "common", the region
loader (0x001ae340), SoundDriverCallback (0x001ae3c8), LoadSoundRegionsInGame
and LoadSoundRegionsFrontEnd, the two IsSoundRegionLoadingComplete, the
region poll (0x001af308) through sound::Update, UnLoadSoundRegions,
sound::Update itself, UpdateVolumeMuffler, ScaleCategoryVolumes,
MuteCarSounds, sound::Mute and MuteReplay, GetInGameSample,
PlayCommonRegionSample, TriggerFinishLineSound, the two random helpers and
Set/GetAudioMode -- on retail's own statics (the region slots at
0x003139a8, gp-19068..gp-18892). The harness (tools/src/sound_test.c) runs
sound.c's, with SoundHooks.skip_missing 0.

**The fakes.** bSound is a fake on both sides that prints: Initialize (the
status it leaves is the script's `up`), SetPath, LoadRegion (a queue of
pending regions, or nothing when the script says the load fails), Update
(which hands the first pending region to the client when the script's
`auto` is on, through the callback Initialize was given), UnloadRegion,
Region, CommonRegion, SetMode and the sixteen category volumes. A region
is a name at +0, as retail's bRegion is. bRegion::Sample gives one sample
per region and name ("X..." names have none); bSample's SetCategory and
Play print. The jukebox's calls (LoadCartridge, Update, Pause,
SetSelection, Start, DefaultCategoryVolumes) print; so does every module
sound.c reaches through SoundHooks -- the speech, the SED wedge, the speech
noise, the collision sounds, the scapes, the car sounds and each car's
BaseCarSound::Mute (through its vtable, as retail calls it), the chopper,
the one-shots -- and bFileExists, eFlashScreen, bServiceFileSystem (which
moves the VBlank count on, every `vevery` calls), the Joylog's GetData and
AddData and GetDriverInfoByDriverNumber. The ticker is the script's.

**The script** brings the driver up and down, waits for "common" by every
VBlank pace, loads the in-game regions with and without a track and with
every pair of drivers -- out, eliminated, sharing a car, a car with no
sound -- and the frontend's, takes the regions in through the callback in
every order and by every event, polls them under a joylog replay and a
recording and past the twenty-second hang, unloads, runs sound::Update
round the 8 ms gate, the pause, the frontend and the mute with
DelayedStart's count, muffles under the post-race, a zone and a speech,
scales, mutes and un-mutes with each category volume, and plays the
samples. After an op the harness and the model print the same lines;
`dump` prints the statics, the slots and the fake bSound.

Retail waits for "common" with no end when it cannot come (no
COMMON.msh, or bSound up and the load refused); the port stops when
nothing is pending. The script does not ask for that.

    python tools/sound_check.py
    python tools/sound_check.py --mutate [--only a,b]
    python tools/sound_check.py --dump out/sound
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                        # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/sound_test.c"
SNDC = "3DS Files/source/sound.c"
SOURCES = [HARNESS, SNDC, "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c"]
HARNESS_TIMEOUT = 30
LIMIT = 2000000

GP = retail_model.RETAIL_GP
F = {
    "muffler": 0x001ae110, "getsample": 0x001ae280, "callback": 0x001ae3c8,
    "init": 0x001ae608, "ingame": 0x001ae798, "frontend": 0x001ae9a0,
    "real": 0x001af290, "iscomplete": 0x001af2e8, "unload": 0x001af420,
    "update": 0x001af4c0, "scale": 0x001af638, "mutecars": 0x001af6f8,
    "playcommon": 0x001af760, "mute": 0x001af850, "mutereplay": 0x001af940,
    "randi": 0x001af9a0, "randf": 0x001af9c0, "setmode": 0x001af9e0,
    "getmode": 0x001afa10, "finish": 0x001afb38,
}

SLOTS = 0x003139a8              # four of {char name[32]; int loaded;}
JB = 0x003115d0                 # the cJukeboxPlayer
SAVED = 0x00313878              # the saved volumes, 5 floats
DEMODISC = 0x002effe0           # TheDemoDiscManager.bActive
SE, ME, SPEECHEN = GP - 23056, GP - 23048, GP - 16552
BSOUND = GP - 13696
STATE, VBLANK, DT = GP - 21420, GP - 19616, GP - 19560
COORD, WORLD, TRACK = GP - 22216, GP - 22120, GP - 21952
NPLAYERS, PLAYERS = GP - 20920, GP - 20928
CARTYPES, REPLAY = GP - 20616, GP - 20668
DSEED = GP - 14472
S_INGAME, S_FE, S_COMMON = GP - 19012, GP - 19000, GP - 19020
S_DONE, S_PARAM, S_LOADING, S_START = (GP - 19064, GP - 19060, GP - 19056,
                                       GP - 19052)
S_DELAY, S_MUTED, S_SPEECHVOL = GP - 19028, GP - 19040, GP - 19024
S_MUFC, S_MUFT, S_LAST = GP - 19036, GP - 19032, GP - 18900
S_SCALE, S_SEED, S_MODE, S_PVU = (GP - 18896, GP - 19068, GP - 18892,
                                  GP - 18904)

# Callees that print a fixed line, by address.
SAY = {
    0x00209ff8: "speech update", 0x0020a230: "speech flush",
    0x002061e8: "sed update",
    0x00215770: "noise request", 0x00215780: "noise unload",
    0x002157c0: "noise update",
    0x001e51a8: "collision register", 0x001e51b0: "collision unregister",
    0x001e51b8: "collision update",
    0x001cebf0: "scape update",
    0x0018ea18: "carsounds",
    0x001eadb0: "chopper update",
    0x002091d0: "oneshot init", 0x00209268: "oneshot close",
    0x002092a0: "oneshot update",
    0x0027dff8: "jbupdate", 0x001afab8: "jbdefvol",
}
# ... and the mutes, by which register holds the flag.
SAY_A0 = {0x001cebf8: "scape mute", 0x00209320: "oneshot mute",
          0x001e51c0: "collision mute", 0x001aeab0: "jbstart",
          0x001af050: "jbselect"}
SAY_A1 = {0x0020a2b0: "speech mute", 0x002158a0: "noise mute",
          0x001ead80: "chopper mute", 0x0027e3e8: "jbpause"}
SILENT = [
    0x00278368,                     # bSound::DisablePrintf
    0x00270420,                     # bEffect::SetType
    0x00277980,                     # bSound::Driver
    0x0025d4f8,                     # bDriver::PlatSetEffectVolume
    0x0027af90,                     # bVoiceMgr::PrintVoiceUsage
]


def fbits(v):
    return struct.unpack("<I", struct.pack("<f", v))[0]


def ffrom(b):
    return struct.unpack("<f", struct.pack("<I", b & M32))[0]


# ================================================================= script

def script():
    s = []
    a = s.append
    ext = s.extend
    t = [1000]

    def at(tick):
        t[0] = tick
        a("tick|%d" % tick)

    def upd(n=1, step=20):
        # sound::Update past its 8 ms gate, n times.
        for _ in range(n):
            t[0] += step
            a("tick|%d" % t[0])
            a("update")

    def fresh():
        ext(["unload", "flush"])

    # The statics as the image has them, and every call before the driver.
    ext(["dump", "real", "iscomplete", "getmode", "getsample|FinishLine",
         "finish", "randi|100", "randf|3f800000", "update", "dump"])
    # Sound off: nothing.
    ext(["se|0", "init", "ingame|1", "dump", "frontend|2", "real",
         "iscomplete", "update", "dump", "unload", "mute|1", "mutereplay|1",
         "playcommon|MenuSelect|3f800000", "dump", "update", "dump",
         "se|1"])
    # The driver refused: bSound stays down, no wait, and the rest.
    ext(["up|0", "me|0", "init", "dump", "me|1", "init", "dump", "up|1"])
    # Up, "common" waited for at each pace: the VBlank every service or
    # every few, and bSound a few updates late.
    for every, late, vb in ((1, 1, 0), (2, 1, 0), (3, 4, 0), (1, 3, 5),
                            (2, 2, 4294967295), (1, 1, 7)):
        ext(["uncommon", "vblank|%d" % vb, "vevery|%d" % every,
             "auto|%d" % late, "init", "dump"])
    ext(["vevery|1", "auto|1", "speechen|1"])
    # Already in: no wait.
    ext(["init", "dump", "flush"])
    # The driver's seed is bDefaultSeed modulo 2^32 - 1, so the two at the
    # top tell -1 from any other range.
    ext(["dseed|4294967295", "init", "dump", "dseed|4294967294", "init",
         "dump", "dseed|305419896", "flush"])
    # common missing, but already in: the flash, and no wait.
    ext(["missing|common|1", "init", "dump", "missing|common|0"])
    # The callback's events, one by one.
    ext(["auto|0"])
    for ev in (0, 1, 3, 4, 7, 8, 9, 16, 0x102, -2, 2):
        a("event|%d|Foo" % ev)
    ext(["dump", "event|2|common", "dump", "event|8|common",
         "uncommon", "event|2|common", "dump"])
    # The frontend's region, held back, then let in.
    at(1000)
    ext(["frontend|7", "dump", "real", "iscomplete", "update", "dump"])
    at(1010)
    ext(["update", "arrive", "dump", "real", "iscomplete", "update", "dump",
         "update", "iscomplete", "dump"])
    ext(["getsample|FinishLine", "playcommon|MenuSelect|3f000000",
         "playcommon|XNone|3f800000", "dump"])
    fresh()
    a("dump")
    # In-game: no track, no drivers.
    ext(["track|@", "ingame|11", "dump", "arrive"])
    upd()
    a("dump")
    # In-game with the track and both drivers, in by update.
    ext(["cartype|1|corvette", "cartype|2|viper", "cartype|3|~",
         "cartype|4|InGame", "cartype|5|Desert", "track|Desert",
         "driver|0|1|0|1", "driver|1|1|0|2"])
    fresh()
    at(50000)
    ext(["auto|1", "ingame|12", "dump"])
    for _ in range(5):
        upd()
        a("dump")
    fresh()
    a("dump")
    # Every pair of drivers.
    drivers = ["0|0|0", "1|0|1", "1|1|1", "1|200|2", "1|0|3", "1|0|4",
               "1|0|5", "1|127|1", "1|0|2", "1|-1|1"]
    for d0 in drivers:
        for d1 in drivers[::2]:
            ext(["auto|0", "driver|0|" + d0, "driver|1|" + d1,
                 "ingame|13", "dump"])
            fresh()
    ext(["driver|0|1|0|1", "driver|1|1|0|1", "track|~", "ingame|14",
         "dump"])
    fresh()
    a("track|Desert")
    # The regions in out of order, by the event alone.
    ext(["driver|0|1|0|1", "driver|1|1|0|2", "auto|0", "ingame|15",
         "event|2|viper", "dump", "event|2|corvette", "dump",
         "event|8|InGame", "event|4|InGame", "dump", "event|2|InGame",
         "dump", "real", "event|2|Desert", "dump", "real", "iscomplete"])
    upd()
    a("dump")
    fresh()
    # A region that is not on the disc: the flash, and the wait goes on.
    ext(["missing|viper|1", "auto|1"])
    at(100000)
    a("ingame|16")
    upd(5)
    ext(["dump", "real"])
    at(119000)
    ext(["update", "dump"])
    at(120001)
    ext(["update", "dump"])
    at(120002)
    ext(["update", "dump"])
    fresh()
    # ... and at its edge: 19.6 s and 20 s still wait, 20.001 s does not.
    at(300000)
    a("ingame|50")
    upd(5)
    for tk in (319600, 320000, 320001):
        at(tk)
        ext(["update", "dump"])
    fresh()
    # ... and one bSound refuses.
    ext(["missing|viper|0", "fail|corvette|1"])
    at(130000)
    a("ingame|17")
    upd(4)
    a("dump")
    at(150001)
    ext(["update", "dump", "fail|corvette|0"])
    fresh()
    # The poll under the joylog: recording, then a replay that waits, then
    # one whose recording says they were not in.
    ext(["replay|0|0", "auto|0"])
    at(200000)
    a("ingame|18")
    for _ in range(4):
        upd()
        a("arrive")
    upd()
    a("dump")
    fresh()
    for every, late in ((1, 1), (2, 1), (1, 3), (3, 2)):
        ext(["replay|1|1", "vevery|%d" % every, "auto|%d" % late,
             "ingame|19"])
        upd()
        a("dump")
        fresh()
    ext(["vevery|1", "replay|1|7", "auto|1", "ingame|20"])
    upd()
    a("dump")
    fresh()
    ext(["replay|1|0", "auto|0"])
    at(210000)
    a("ingame|21")
    upd(2)
    a("arrive")
    upd()
    a("dump")
    at(230001)
    ext(["update", "dump"])
    fresh()
    ext(["replay|0|0", "auto|1"])
    # No done; the ticker's wrap.
    at(4294967000)
    ext(["frontend|22|1", "update", "dump", "update", "dump"])
    fresh()
    at(5000)
    a("frontend|23")
    at(4294967295)
    ext(["update", "dump"])
    fresh()
    # sound::Update round the 8 ms gate.
    ext(["auto|1", "track|@", "driver|0|0|0|0", "driver|1|0|0|0",
         "state|6"])
    at(300000)
    a("update")
    at(300008)
    a("update")
    at(300009)
    ext(["update", "dump"])
    at(300009)
    a("update")
    at(300017)
    a("update")
    at(300100)
    a("update")
    # DelayedStart's count: by dt, through zero, and held by the pause,
    # the frontend and the mute.
    ext(["dt|3d088889", "delay|3e800000", "world|1", "chopper|0"])
    for _ in range(10):
        upd()
        a("dump")
    for hold, back in (("paused|1", "paused|0"), ("state|3", "state|6"),
                       ("muted|1", "muted|0"), ("state|0", "state|6"),
                       ("state|4", "state|6")):
        ext([hold, "delay|3e800000"])
        upd()
        ext(["dump", back])
    for d, dt in (("80000000", "3d088889"), ("bf800000", "3d088889"),
                  ("00000000", "bd088889"), ("3c000000", "3c000000"),
                  ("3c000000", "3c000001"), ("3f800000", "00000000"),
                  ("3c000000", "80000000")):
        ext(["delay|" + d, "dt|" + dt])
        upd()
        a("dump")
    a("dt|3d088889")
    # The chopper and the world.
    for w, c in ((1, 1), (0, 1), (0, 0), (1, 0), (1, 1)):
        ext(["world|%d" % w, "chopper|%d" % c])
        upd()
    ext(["pvu|1"])
    upd()
    ext(["dump", "pvu|7", "se|0"])
    upd()
    ext(["dump", "se|1", "world|1", "chopper|0"])
    # The muffler: each case, each rate, from each side.
    ext(["race|7", "muffler", "dump", "muffler", "muffler", "muffler",
         "muffler", "muffler", "dump", "muted|1", "muffler", "dump",
         "muted|0", "race|6", "muffler", "muffler", "muffler", "dump"])
    ext(["players|1", "player|0|1|0|3e800000", "muffler", "dump",
         "player|0|0|1|3e800000", "muffler", "dump",
         "player|0|1|1|3e800000", "muffler", "muffler", "dump"])
    for _ in range(18):
        a("muffler")
    ext(["dump", "players|2", "player|0|0|0|3f000000",
         "player|1|1|1|3f400000", "muffler", "dump",
         "player|0|1|1|bf800000", "player|1|0|0|3e000000", "muffler",
         "dump", "player|0|1|1|bf800000", "player|1|1|1|bf800000",
         "muffler", "dump", "player|0|1|1|3f800000",
         "player|1|1|1|3e000000", "muffler", "dump",
         "player|0|0|1|3f800000", "player|1|1|7|3e000000", "muffler",
         "dump", "race|7", "muffler", "dump", "race|-1", "muffler", "dump",
         "muted|1", "muffler", "dump", "muted|0"])
    ext(["players|0", "sedplay|1", "state|6", "muffler", "muffler", "dump",
         "state|3", "muffler", "muffler", "muffler", "muffler", "muffler",
         "muffler", "muffler", "dump", "muted|1", "muffler", "dump",
         "muted|0", "players|1", "player|0|1|1|3f000000", "muffler", "dump",
         "players|0", "race|7", "muffler", "dump", "race|-1", "sedplay|0",
         "state|6"])
    for _ in range(10):
        a("muffler")
    a("dump")
    # Through sound::Update, in a race and in the frontend.
    ext(["players|1", "player|0|1|1|3e800000"])
    upd(3)
    ext(["dump", "state|3"])
    upd(3)
    ext(["dump", "players|0", "state|6"])
    upd(12)
    a("dump")
    # ScaleCategoryVolumes, by hand: the same scale twice, speech too.
    ext(["saved|0|3f000000", "saved|1|3e800000", "saved|2|3f400000",
         "saved|3|3f800000", "saved|4|3e000000", "savedsp|3f19999a",
         "scale|3f000000|0", "dump", "scale|3f000000|1", "scale|3f800000|1",
         "dump", "scale|3e800000|1", "scale|3e800000|0", "scale|bf800000|0",
         "scale|00000000|1", "scale|80000000|1", "dump", "scale|3f800000|2",
         "scale|3f000000|0"])
    # sound::Mute and MuteReplay, with each music volume and flag.
    ext(["cars|3|5", "world|1", "chopper|1", "jbcat|5"])
    for vol in ("3f800000", "00000000", "80000000", "bf800000"):
        for on in (1, 0, 2):
            ext(["catvol|5|" + vol, "mute|%d" % on, "dump"])
    ext(["catvol|5|3f800000", "jbcat|4", "catvol|4|00000000", "mute|0",
         "jbcat|16", "mute|0", "jbcat|5"])
    ext(["me|0", "mute|1", "mute|0", "me|1", "speechen|0", "mute|1",
         "mute|0", "speechen|1"])
    for cars, mask in ((0, 0), (1, 1), (2, 2), (5, 0x1f), (5, 0x0a)):
        ext(["cars|%d|%d" % (cars, mask), "mute|1", "mutereplay|0",
             "mutecars|1", "mutecars|-3"])
    ext(["chopper|0", "mute|1", "mutereplay|1", "dump", "world|0", "mute|0",
         "mutereplay|0", "mutecars|1", "dump", "world|1", "mute|0",
         "mutereplay|5", "dump", "mutereplay|0"])
    # The samples.
    ext(["frontend|30"])
    upd(2)
    ext(["getsample|FinishLine"])
    fresh()
    ext(["ingame|31", "getsample|FinishLine", "dump"])
    upd(3)
    ext(["getsample|FinishLine", "getsample|FinishLine", "getsample|XGone",
         "finish", "dump"])
    fresh()
    ext(["finish", "getsample|FinishLine", "dump"])
    ext(["playcommon|MenuSelect|3f800000", "playcommon|Ding|00000000",
         "playcommon|XNone|3f000000", "playcommon|Ding|bf800000"])
    # What the loads reset with no unload between.
    ext(["auto|1", "track|Desert", "driver|0|1|0|1", "driver|1|1|0|2",
         "ingame|40"])
    upd(5)
    ext(["getsample|FinishLine", "dump", "delay|3f800000", "muted|1",
         "track|@", "driver|0|0|0|0", "driver|1|0|0|0", "ingame|41", "dump",
         "getsample|FinishLine"])
    upd(2)
    ext(["getsample|FinishLine", "delay|3f800000", "muted|1",
         "frontend|42", "dump", "getsample|FinishLine"])
    upd(2)
    ext(["dump", "delay|3f800000", "muted|1", "unload", "dump", "flush",
         "muted|0"])
    # Random and the audio mode.
    ext(["seed|1", "randi|10", "randi|10", "randi|1", "randi|-5",
         "randi|2147483647", "randf|3f800000", "randf|42c80000",
         "randf|00000000", "randf|bf800000", "dump", "seed|0",
         "randi|1000", "randf|3f800000", "dump"])
    for m in (0, 1, 2, 3, -1):
        ext(["setmode|%d" % m, "getmode"])
    a("dump")
    return s


# ================================================================= model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        e.stub_bware()
        self.up = 1
        self.auto = 1
        self.ucount = 0
        self.vevery = 1
        self.vcount = 0
        self.tick = 0
        self.paused = 0
        self.jget = 0
        self.status = 0
        self.client = 0
        self.client_data = 0
        self.pend = []
        self.regions = {}               # name -> address
        self.registered = set()
        self.common = 0
        self.samples = {}               # id -> address
        self.sample_id = {}             # address -> id
        self.vol = [fbits(1.0)] * 16
        self.missing = set()
        self.failing = set()
        self.drivers = [None, None]
        self.cars = 0
        self.carmask = 0
        self.carnodes = []
        self.sound_car = {}

        self.bsound = e.alloc(512)
        e.put32(BSOUND, self.bsound)
        self.speech = e.alloc(2048)
        self.noise = e.alloc(64)
        self.coord = e.alloc(64)
        self.world = e.alloc(64)
        self.chopper = e.alloc(64)
        self.track = e.alloc(256)
        self.players = [e.alloc(256), e.alloc(256)]
        self.cartypes = e.alloc(1376 * 64)
        self.driverinfo = [e.alloc(64), e.alloc(64)]
        self.vtable = e.alloc(64)
        self.done = e.alloc(16)
        self.mutefn = e.alloc(16)
        self.sed = e.alloc(16)
        e.put32(WORLD, 0)
        e.put32(self.world, self.world)         # an empty car list
        e.put32(self.world + 24, 0)
        e.put32(COORD, 0)
        e.put32(TRACK, 0)
        e.put32(CARTYPES, self.cartypes)
        e.put32(PLAYERS, self.players[0])
        e.put32(PLAYERS + 4, self.players[1])
        e.put32(NPLAYERS, 0)
        e.put32(REPLAY, 0)
        e.put32(STATE, 0)
        e.put32(VBLANK, 0)
        e.put32(DT, 0)
        e.put32(DEMODISC, 0)
        e.put32(SE, 1)
        e.put32(ME, 0)
        e.put32(S_MUTED, 0)
        e.put32(S_DELAY, 0)
        e.put32(S_PVU, 0)
        e.put32(S_SPEECHVOL, fbits(-1.0))
        for i in range(5):
            e.put32(SAVED + 4 * i, 0)
        e.put32(JB + 8848, 0)
        # The vtable each BaseCarSound points at (+28): Mute is the entry
        # at +32, an offset to add to `this` and the function.
        e.mem[self.vtable + 32:self.vtable + 34] = b"\0\0"
        e.put32(self.vtable + 36, self.mutefn)

        for addr, text in SAY.items():
            e.stub(addr, self.say(text))
        for addr, text in SAY_A0.items():
            e.stub(addr, self.say_reg(text, 4))
        for addr, text in SAY_A1.items():
            e.stub(addr, self.say_reg(text, 5))
        for addr in SILENT:
            e.stub(addr, lambda em: 0)
        e.stub(0x002577c0, lambda em: em.alloc(max(s32(em.reg[4]), 4), 8))
        e.stub(0x00205888, self.sed_create)
        e.stub(0x00209ef0, lambda em: self.speech)  # speech::mgr_t
        e.stub(0x001b0188, lambda em: self.noise)   # SpeechNoise
        e.stub(0x0027dac8, self.jb_load)
        e.stub(0x00253718, self.str_cat)
        e.stub(0x00253560, self.str_cpy)
        e.stub(0x002535f8, self.str_cmp)
        e.stub(0x002545b8, self.file_exists)
        e.stub(0x001083f0, self.flash)
        e.stub(0x002539b8, self.service)
        e.stub(0x00250f38, lambda em: self.tick)
        e.stub(0x00250f48, self.ticker_diff)
        e.stub(0x00183358, self.jl_get)
        e.stub(0x00183498, self.jl_add)
        e.stub(0x001680b8, lambda em: self.paused)
        e.stub(0x001edb40, self.driver_info)
        e.stub(self.done, self.done_fn)
        e.stub(self.mutefn, self.car_mute)
        # bSound
        e.stub(0x00277820, self.b_init)
        e.stub(0x00278190, self.b_mode)
        e.stub(0x00277e38, self.b_path)
        e.stub(0x00277b00, self.b_load)
        e.stub(0x00277ea0, lambda em: self.status)
        e.stub(0x002778f8, self.b_update)
        e.stub(0x00277c00, self.b_unload)
        e.stub(0x00277a18, self.b_region)
        e.stub(0x002779e0, lambda em: self.common)
        e.stub(0x00277dc0, self.b_getvol)
        e.stub(0x00277cb0, self.b_setvol)
        e.stub(0x002719b8, self.b_sample)
        e.stub(0x00273618, self.b_cat)
        e.stub(0x00274080, self.b_play)

    def emit(self, s):
        self.out.append(s)

    def write_str(self, a, s):
        self.e.write(a, s.encode("latin-1") + b"\0")

    def cstr(self, a, n=256):
        b = bytearray()
        mem = self.e.mem
        while len(b) < n and mem[a]:
            b.append(mem[a])
            a += 1
        return b.decode("latin-1")

    def nested(self, fn, *args):
        """Call into the image from inside a stub, and put back what the
        stub's caller had."""
        e = self.e
        kept = (list(e.reg), list(e.fpr), e.hi, e.lo, e.hi1, e.lo1, e.sa,
                e.fcc, e.limit, e.icount)
        try:
            e.call(fn, *args, limit=LIMIT)
        finally:
            e.reg[:] = kept[0]
            e.fpr[:] = kept[1]
            (e.hi, e.lo, e.hi1, e.lo1, e.sa, e.fcc, e.limit,
             e.icount) = kept[2:]

    # ---- the printing stubs

    def say(self, text):
        def stub(em):
            self.emit("  " + text)
            return 0
        return stub

    def say_reg(self, text, r):
        def stub(em):
            self.emit("  %s %d" % (text, s32(em.reg[r])))
            return 0
        return stub

    def sed_create(self, em):
        self.emit("  sed create")
        return self.sed

    def jb_load(self, em):
        self.emit("  jbload %s %d" % (self.cstr(em.reg[5] & M32),
                                       1 if em.reg[6] & 0xff else 0))
        return 0

    def str_cat(self, em):
        r = em.reg
        s = self.cstr(r[5] & M32) + self.cstr(r[6] & M32)
        self.write_str(r[4] & M32, s)
        return r[4] & M32

    def str_cpy(self, em):
        r = em.reg
        self.write_str(r[4] & M32, self.cstr(r[5] & M32))
        return r[4] & M32

    def str_cmp(self, em):
        a, b = self.cstr(em.reg[4] & M32), self.cstr(em.reg[5] & M32)
        return (a > b) - (a < b)

    def file_exists(self, em):
        path = self.cstr(em.reg[4] & M32)
        self.emit("  exists %s" % path)
        return 0 if path in self.missing else 1

    def flash(self, em):
        r = em.reg
        self.emit("  flash %d %d %d %s %08x" % (
            s32(r[4]), s32(r[5]), s32(r[6]), self.cstr(r[7] & M32),
            em.fpr[12] & M32))
        return 0

    def service(self, em):
        self.emit("  service")
        self.vcount += 1
        if self.vcount >= self.vevery:
            self.vcount = 0
            em.put32(VBLANK, (em.u32(VBLANK) + 1) & M32)
        return 0

    def ticker_diff(self, em):
        a, b = em.reg[4] & M32, em.reg[5] & M32
        em.fpr[0] = fbits(float((b - a) & M32))
        return None

    def jl_get(self, em):
        self.emit("  jget %d %d" % (s32(em.reg[4]), s32(em.reg[5])))
        return self.jget

    def jl_add(self, em):
        r = em.reg
        self.emit("  jadd %d %d %d" % (s32(r[4]), s32(r[5]), s32(r[6])))
        return 0

    def driver_info(self, em):
        i = s32(em.reg[5])
        self.emit("  driver %d" % i)
        d = self.drivers[i] if 0 <= i < 2 else None
        if d is None:
            return 0
        a = self.driverinfo[i]
        e = self.e
        e.mem[a] = d[0] & 0xff
        e.put32(a + 12, d[1])
        return a

    def done_fn(self, em):
        self.emit("  done %d" % s32(em.reg[4]))
        return 0

    def car_mute(self, em):
        self.emit("  carmute %d %d" % (self.sound_car.get(em.reg[4] & M32, -1),
                                       s32(em.reg[5])))
        return 0

    # ---- the fake bSound

    def region_of(self, name, create=True):
        if name not in self.regions and create:
            a = self.e.alloc(64)
            self.write_str(a, name)
            self.regions[name] = a
        return self.regions.get(name, 0)

    def deliver(self):
        name = self.pend.pop(0)
        r = self.region_of(name)
        self.registered.add(name)
        if name == "common":
            self.common = r
        self.emit("  arrive %s" % name)
        if self.client:
            self.nested(self.client, 2, r, self.client_data)

    def b_init(self, em):
        self.emit("  binit")
        self.client = em.reg[5] & M32
        self.client_data = em.reg[6] & M32
        self.status = 1 if self.up else 0
        return 0

    def b_mode(self, em):
        self.emit("  bmode %d" % s32(em.reg[5]))
        return 0

    def b_path(self, em):
        self.emit("  bpath %s" % self.cstr(em.reg[5] & M32))
        return 0

    def b_load(self, em):
        name = self.cstr(em.reg[5] & M32)
        self.emit("  bload %s" % name)
        if self.status != 1 or name in self.failing or len(self.pend) == 8:
            return 0
        self.pend.append(name)
        return 1

    def b_update(self, em):
        # With `auto` k, a pending region comes in on the kth Update.
        self.emit("  bupdate")
        if self.status == 1 and self.auto and self.pend:
            self.ucount += 1
            if self.ucount >= self.auto:
                self.ucount = 0
                self.deliver()
        return 0

    def b_unload(self, em):
        name = self.cstr(em.reg[5] & M32)
        self.emit("  bunload %s" % name)
        if name in self.registered:
            self.registered.discard(name)
            if self.common == self.regions.get(name):
                self.common = 0
        return 0

    def b_region(self, em):
        name = self.cstr(em.reg[5] & M32)
        self.emit("  bregion %s" % name)
        return self.regions[name] if name in self.registered else 0

    def b_getvol(self, em):
        cat = em.reg[5] & M32
        em.fpr[0] = self.vol[cat] if cat < 16 else fbits(1.0)
        return None

    def b_setvol(self, em):
        cat = em.reg[5] & M32
        self.emit("  bvol %u %08x" % (cat, em.fpr[12] & M32))
        if cat < 16:
            self.vol[cat] = em.fpr[12] & M32
        return 0

    def rname(self, a):
        return self.cstr(a) if a else "(null)"

    def sid(self, a):
        return self.sample_id.get(a & M32, "(null)")

    def b_sample(self, em):
        r, name = em.reg[4] & M32, self.cstr(em.reg[5] & M32)
        self.emit("  bsample %s %s" % (self.rname(r), name))
        if not r or name.startswith("X"):
            return 0
        sid = "%s/%s" % (self.cstr(r), name)
        if sid not in self.samples:
            a = self.e.alloc(16)
            self.samples[sid] = a
            self.sample_id[a] = sid
        return self.samples[sid]

    def b_cat(self, em):
        self.emit("  bcat %s %u" % (self.sid(em.reg[4]), em.reg[5] & M32))
        return 0

    def b_play(self, em):
        f = em.fpr
        self.emit("  bplay %s %08x %08x %08x" % (
            self.sid(em.reg[4]), f[12] & M32, f[13] & M32, f[14] & M32))
        return 0

    # ---- the dump

    def dump(self):
        e = self.e
        u = e.u32
        self.emit("  mod loading=%d start=%u last=%u muffle=%08x,%08x "
                  "scale=%08x seed=%08x dseed=%08x mode=%d common=%d "
                  "ingame=%s fe=%s done=%d param=%d speech=%d pvu=%d" % (
                      s32(u(S_LOADING)), u(S_START), u(S_LAST), u(S_MUFC),
                      u(S_MUFT), u(S_SCALE), u(S_SEED), u(DSEED),
                      s32(u(S_MODE)), s32(u(S_COMMON)),
                      self.rname(u(S_INGAME)), self.rname(u(S_FE)),
                      1 if u(S_DONE) else 0, s32(u(S_PARAM)),
                      s32(u(SPEECHEN)), s32(u(S_PVU))))
        for i in range(4):
            a = SLOTS + 36 * i
            self.emit("  slot %d '%s' %d" % (i, self.cstr(a, 31),
                                             s32(u(a + 32))))
        self.emit("  jb delay=%08x muted=%d me=%d se=%d" % (
            u(S_DELAY), s32(u(S_MUTED)), s32(u(ME)), s32(u(SE))))
        names = sorted(self.registered, key=lambda n: self.regions[n])
        self.emit("  bs status=%d pending=%d%s common=%s regions=%s" % (
            self.status, len(self.pend),
            "".join(" " + p for p in self.pend), self.rname(self.common),
            "".join(n + "," for n in names)))
        self.emit("  vol " + " ".join("%08x" % v for v in self.vol))

    # ---- the ops

    def call(self, name, *args):
        return self.e.call(F[name], *args, limit=LIMIT)

    def set_cars(self):
        e = self.e
        prev = self.world
        self.sound_car = {}
        while len(self.carnodes) < self.cars:
            node = e.alloc(2200)
            snd = e.alloc(64)
            e.put32(snd + 28, self.vtable)
            self.carnodes.append((node, snd))
        for i in range(self.cars):
            node, snd = self.carnodes[i]
            e.put32(prev, node)
            has = (self.carmask >> i) & 1
            e.put32(node + 2132, snd if has else 0)
            self.sound_car[snd] = i
            prev = node
        e.put32(prev, self.world)

    def op(self, f):
        e = self.e
        n = []
        for x in f[1:]:
            try:
                n.append(int(x, 0))
            except ValueError:
                n.append(0)

        def arg(i):
            return n[i - 1] if i - 1 < len(n) else 0

        def fl(i):
            return int(f[i], 16) & M32

        def text(i):
            return "" if i >= len(f) or f[i] == "~" else f[i]

        o = f[0]
        if o == "init":
            self.call("init")
        elif o == "event":
            r = self.region_of(text(2))
            self.call("callback", arg(1), r, 0)
        elif o == "arrive":
            if self.pend:
                self.deliver()
        elif o in ("ingame", "frontend"):
            self.call(o, 0 if arg(2) else self.done, arg(1))
        elif o in ("real", "iscomplete", "getmode"):
            self.emit("  = %d" % self.call(o))
        elif o in ("unload", "update", "muffler", "finish"):
            self.call(o)
        elif o == "scale":
            e.fpr[12] = fl(1)
            self.call("scale", arg(2))
        elif o in ("mute", "mutereplay", "mutecars", "setmode"):
            self.call(o, arg(1))
        elif o == "getsample":
            buf = e.alloc(64)
            self.write_str(buf, text(1))
            self.emit("  = %s" % self.sid(self.call("getsample", buf)))
        elif o == "playcommon":
            buf = e.alloc(64)
            self.write_str(buf, text(1))
            e.fpr[12] = fl(2)
            self.call("playcommon", buf)
        elif o == "randi":
            self.emit("  = %d" % self.call("randi", arg(1)))
        elif o == "randf":
            e.fpr[12] = fl(1)
            self.call("randf")
            self.emit("  = %08x" % (e.fpr[0] & M32))
        elif o == "dump":
            self.dump()
        # ---- the world
        elif o == "se":
            e.put32(SE, arg(1))
        elif o == "me":
            e.put32(ME, arg(1))
        elif o == "speechen":
            e.put32(SPEECHEN, arg(1))
        elif o == "pvu":
            e.put32(S_PVU, arg(1))
        elif o == "up":
            self.up = arg(1)
        elif o == "auto":
            self.auto = arg(1)
            self.ucount = 0
        elif o == "flush":
            self.pend = []
            self.ucount = 0
        elif o == "uncommon":
            e.put32(S_COMMON, 0)
        elif o == "vblank":
            e.put32(VBLANK, arg(1) & M32)
        elif o == "missing":
            path = "sound\\%s.msh" % text(1)
            if arg(2):
                self.missing.add(path)
            else:
                self.missing.discard(path)
        elif o == "fail":
            if arg(2):
                self.failing.add(text(1))
            else:
                self.failing.discard(text(1))
        elif o == "state":
            e.put32(STATE, arg(1))
        elif o == "paused":
            self.paused = arg(1)
        elif o == "dt":
            e.put32(DT, fl(1))
        elif o == "tick":
            self.tick = arg(1) & M32
        elif o == "vevery":
            self.vevery = arg(1)
            self.vcount = 0
        elif o == "replay":
            e.put32(REPLAY, arg(1))
            self.jget = arg(2)
        elif o == "race":
            if arg(1) == -1:
                e.put32(COORD, 0)
            else:
                e.put32(self.coord, arg(1))
                e.put32(COORD, self.coord)
        elif o == "players":
            e.put32(NPLAYERS, arg(1))
        elif o == "player":
            p = self.players[arg(1)]
            e.put32(p + 144, arg(2))
            e.put32(p + 88, arg(3))
            e.put32(p + 148, fl(4))
        elif o == "track":
            if f[1] == "@":
                e.put32(TRACK, 0)
            else:
                self.write_str(self.track + 132, text(1))
                e.put32(TRACK, self.track)
        elif o == "driver":
            self.drivers[arg(1)] = (arg(3), arg(4)) if arg(2) else None
        elif o == "cartype":
            self.write_str(self.cartypes + 1376 * (arg(1) & 63) + 816,
                           text(2))
        elif o == "world":
            e.put32(WORLD, self.world if arg(1) else 0)
        elif o == "chopper":
            e.put32(self.world + 24, self.chopper if arg(1) else 0)
        elif o == "cars":
            self.cars = arg(1)
            self.carmask = arg(2)
            self.set_cars()
        elif o == "sedplay":
            e.put32(self.speech + 1452, arg(1))
        elif o == "catvol":
            if arg(1) < 16:
                self.vol[arg(1)] = fl(2)
        elif o == "saved":
            e.put32(SAVED + 4 * arg(1), fl(2))
        elif o == "savedsp":
            e.put32(S_SPEECHVOL, fl(1))
        elif o == "jbcat":
            e.put32(JB + 8848, arg(1))
        elif o == "delay":
            e.put32(S_DELAY, fl(1))
        elif o == "muted":
            e.put32(S_MUTED, arg(1))
        elif o == "seed":
            e.put32(S_SEED, arg(1) & M32)
        elif o == "dseed":
            e.put32(DSEED, arg(1) & M32)
        else:
            self.emit("  unknown op %s" % o)

    def run(self, lines):
        e = self.e
        for line in lines:
            self.emit("> " + line)
            sp = e.reg[29]
            self.op(line.split("|"))
            e.reg[29] = sp
        return self.out


def model(lines):
    return Model().run(lines)


# ================================================================= build

def build_harness(tmp, name="sound_test"):
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


def write_script(d, lines):
    sc = Path(d) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    return sc


# ============================================================= mutations

def _m(name, before, after):
    return (name, SNDC, before, after)


IG_HEAD = ("void sound_load_regions_in_game(SoundModule* m, SoundDoneFn done,\n"
           "                                intptr_t param)\n{\n"
           "    const char* track;\n    int slot, i, j;\n\n")
FE_HEAD = ("void sound_load_regions_front_end(SoundModule* m, SoundDoneFn done,\n"
           "                                  intptr_t param)\n{\n"
           "    int i;\n\n")
IG_REST = ("    m->loadStart = bGetTicker();\n    if (!SoundEnabled)\n"
           "        return;\n    m->inGameRegion = NULL;\n"
           "    m->frontEndRegion = NULL;\n    m->jb->delayedStart = 0.0f;\n"
           "    m->jb->muted = 0;\n")
FE_REST = ("    m->loadStart = bGetTicker();\n    if (!SoundEnabled)\n"
           "        return;\n    m->inGameRegion = NULL;\n"
           "    m->frontEndRegion = NULL;\n    m->jb->delayedStart = 0.0f;\n"
           "    jb_music_set_selection(m->jb, m->audioOptions, JB_CAT_MENU_MUSIC);\n")
CB_LOOP = ("        if (strcmp(bregion_name(r), m->region[i].name) == 0)\n"
           "            m->region[i].loaded = 1;\n    load_next(m);\n")
WAIT = ("            if (last != vblank(m)) {\n"
        "                bsound_update(m->bsound);\n"
        "                last = vblank(m);\n            }\n"
        "            // The port's")
RWAIT = ("                if (last != vblank(m)) {\n"
         "                    bsound_update(m->bsound);\n"
         "                    last = vblank(m);\n                }\n")
GATE = "    if (!paused(m) && game_state(m) != JB_STATE_IN_FRONTEND && !jb->muted) {\n"
MUTE_TAIL = ("    CALL1(scape_mute, on);\n    sound_mute_car_sounds(m, on);\n"
             "    CALL1(oneshot_mute, on);\n    CALL1(collision_mute, on);\n"
             "    if (helicopter(m))\n        CALL1(chopper_mute, on);\n}\n\n"
             "void sound_mute_replay")
MR_TAIL = ("    m->jb->muted = on;\n    sound_mute_car_sounds(m, on);\n"
           "    CALL1(oneshot_mute, on);\n    CALL1(collision_mute, on);\n"
           "    CALL1(scape_mute, on);\n    if (helicopter(m))\n"
           "        CALL1(chopper_mute, on);\n}\n")

MUTATIONS = [
    # ---- the statics
    _m("init-muffle", "    m->muffleCurrent = 1.0f;\n    m->muffleTarget",
       "    m->muffleCurrent = 0.5f;\n    m->muffleTarget"),
    _m("init-target", "    m->muffleTarget = 1.0f;\n    m->lastScale",
       "    m->muffleTarget = 0.5f;\n    m->lastScale"),
    _m("init-lastscale", "    m->lastScale = -1.0f;", "    m->lastScale = 1.0f;"),
    _m("init-audiomode", "    m->audioMode = 1;\n    m->speechEnabled",
       "    m->audioMode = 0;\n    m->speechEnabled"),
    _m("init-speechen", "    m->speechEnabled = 1;\n    s_instance",
       "    m->speechEnabled = 0;\n    s_instance"),

    # ---- the callback and the loader
    _m("next-loaded", "if (m->region[i].name[0] != '\\0' && !m->region[i].loaded) {\n"
       "            bsound_set_path",
       "if (m->region[i].name[0] != '\\0') {\n            bsound_set_path"),
    _m("next-named", "if (m->region[i].name[0] != '\\0' && !m->region[i].loaded) {\n"
       "            bsound_set_path",
       "if (!m->region[i].loaded) {\n            bsound_set_path"),
    _m("next-path", "            bsound_set_path(m->bsound, sound_path(m));\n"
       "            load_region(m, m->region[i].name);\n            return;",
       "            load_region(m, m->region[i].name);\n            return;"),
    _m("next-all", "            load_region(m, m->region[i].name);\n            return;",
       "            load_region(m, m->region[i].name);"),
    _m("load-ext", "    strcat(path, SOUND_EXT);\n", ""),
    _m("load-dir", "    copy_name(path, SOUND_DIR);", "    copy_name(path, \"sound/\");"),
    _m("load-exists", "    if (!exists)\n        flash(", "    if (0)\n        flash("),
    _m("load-flash-colour", "flash(m, 0, 0, 250,", "flash(m, 0, 0, 255,"),
    _m("load-flash-time", "\"Cannot Find Sound Region\", 1.0f);",
       "\"Cannot Find Sound Region\", 2.0f);"),
    _m("load-skip-missing", "    if (!(H && H->skip_missing))\n        return;",
       "    if (0)\n        return;"),
    _m("cb-event", "    if (event != BSOUND_REGION_LOADED)\n        return;",
       "    if (event == BSOUND_SAMPLE_STOPPED)\n        return;"),
    _m("cb-common", "    if (r == bsound_common_region(m->bsound))\n"
       "        m->commonLoaded = 1;\n", ""),
    _m("cb-slots", "    for (i = 0; i < SOUND_REGIONS; i++)\n" + CB_LOOP,
       "    for (i = 0; i < SOUND_REGIONS - 1; i++)\n" + CB_LOOP),
    _m("cb-match", CB_LOOP, CB_LOOP.replace("== 0)", "!= 0)")),
    _m("cb-next", CB_LOOP, CB_LOOP.replace("    load_next(m);\n", "")),

    # ---- InitializeSoundDriver
    _m("drv-se", "    if (!SoundEnabled)\n        return;\n    m->seed",
       "    m->seed"),
    _m("drv-seed", "bRandomI(-1, &bDefaultSeed)", "bRandomI(-2, &bDefaultSeed)"),
    _m("drv-seed-own", "bRandomI(-1, &bDefaultSeed)", "bRandomI(-1, &m->seed)"),
    _m("drv-init-cb", "bsound_init(m->bsound, m->driver, sound_driver_callback, m);",
       "bsound_init(m->bsound, m->driver, NULL, m);"),
    _m("drv-mode", "    sound_set_audio_mode(m, 1);\n", "    sound_set_audio_mode(m, 2);\n"),
    _m("drv-path", "    bsound_set_path(m->bsound, sound_path(m));\n"
       "    load_region(m, \"common\");",
       "    load_region(m, \"common\");"),
    _m("drv-common", "    load_region(m, \"common\");", "    load_region(m, \"COMMON\");"),
    _m("drv-status", "if (bsound_get_status(m->bsound) == 1 && !m->commonLoaded) {",
       "if (!m->commonLoaded) {"),
    _m("drv-loaded", "if (bsound_get_status(m->bsound) == 1 && !m->commonLoaded) {",
       "if (bsound_get_status(m->bsound) == 1) {"),
    _m("drv-last", "        uint32_t last = 0;\n        do {",
       "        uint32_t last = vblank(m);\n        do {"),
    _m("drv-vblank", WAIT, "            bsound_update(m->bsound);\n            // The port's"),
    _m("drv-keep", WAIT, WAIT.replace("                last = vblank(m);\n", "")),
    _m("drv-service", "            CALL0(service_files);\n            if (last != vblank(m)) {\n"
       "                bsound_update(m->bsound);\n                last = vblank(m);\n"
       "            }\n            // The port's",
       "            if (last != vblank(m)) {\n"
       "                bsound_update(m->bsound);\n                last = vblank(m);\n"
       "            }\n            CALL0(service_files);\n            // The port's"),
    _m("drv-music", "    if (m->jb->musicEnabled)\n        jb_load_cartridge",
       "    if (1)\n        jb_load_cartridge"),
    _m("drv-cart", "\"SOUND\\\\JukeboxM.JBC\"", "\"SOUND\\\\JukeboxMDemoDisk.JBC\""),
    _m("drv-cart-flag", "\"SOUND\\\\JukeboxM.JBC\", false);", "\"SOUND\\\\JukeboxM.JBC\", true);"),
    _m("drv-sed", "    CALL0(sed_create);\n", ""),
    _m("drv-defvol", "    jb_default_category_volumes(m->jb);\n", ""),

    # ---- LoadSoundRegionsInGame
    _m("ig-done", IG_HEAD + "    m->done = done;", IG_HEAD + "    m->done = NULL;"),
    _m("ig-param", IG_HEAD + "    m->done = done;\n    m->doneParam = param;",
       IG_HEAD + "    m->done = done;\n    m->doneParam = param + 1;"),
    _m("ig-loading", IG_HEAD + "    m->done = done;\n    m->doneParam = param;\n"
       "    m->loading = 1;\n",
       IG_HEAD + "    m->done = done;\n    m->doneParam = param;\n"),
    _m("ig-start", IG_REST, IG_REST.replace("    m->loadStart = bGetTicker();\n", "")),
    _m("ig-se-early", IG_HEAD + "    m->done = done;",
       IG_HEAD + "    if (!SoundEnabled)\n        return;\n    m->done = done;"),
    _m("ig-ingame", IG_REST, IG_REST.replace("    m->inGameRegion = NULL;\n", "")),
    _m("ig-delay", IG_REST, IG_REST.replace("    m->jb->delayedStart = 0.0f;\n", "")),
    _m("ig-muted", IG_REST, IG_REST.replace("    m->jb->muted = 0;\n", "")),
    _m("ig-selection", "jb_music_set_selection(m->jb, m->audioOptions, JB_CAT_RACING_MUSIC);",
       "jb_music_set_selection(m->jb, m->audioOptions, JB_CAT_MENU_MUSIC);"),
    _m("ig-clear-name", "        m->region[i].name[0] = '\\0';\n        m->region[i].loaded = 0;\n"
       "    }\n    copy_name(m->region[0].name, \"InGame\");",
       "        m->region[i].loaded = 0;\n    }\n    copy_name(m->region[0].name, \"InGame\");"),
    _m("ig-clear-loaded", "        m->region[i].loaded = 0;\n    }\n"
       "    copy_name(m->region[0].name, \"InGame\");",
       "    }\n    copy_name(m->region[0].name, \"InGame\");"),
    _m("ig-name", "    copy_name(m->region[0].name, \"InGame\");",
       "    copy_name(m->region[0].name, \"Ingame\");"),
    _m("ig-track-slot", "        slot = 2;\n", "        slot = 1;\n"),
    _m("ig-track-copy", "        copy_name(m->region[1].name, track);\n", ""),
    _m("ig-two-drivers", "    for (i = 0; i < 2; i++) {\n        const char* car",
       "    for (i = 0; i < 1; i++) {\n        const char* car"),
    _m("ig-driver-number", "H->driver_region(H->ctx, i)", "H->driver_region(H->ctx, 1 - i)"),
    _m("ig-empty-car", "if (car == NULL || car[0] == '\\0')", "if (car == NULL)"),
    _m("ig-search", "        for (j = 0; j < SOUND_REGIONS; j++) {",
       "        for (j = 1; j < SOUND_REGIONS; j++) {"),
    _m("ig-search-track", "        for (j = 0; j < SOUND_REGIONS; j++) {",
       "        for (j = 0; j < 1; j++) {"),
    _m("ig-found", "        if (!found)\n            copy_name", "        if (1)\n            copy_name"),
    _m("ig-load-first", "    load_region(m, m->region[0].name);\n    CALL0(collision_register);",
       "    load_region(m, m->region[slot - 1].name);\n    CALL0(collision_register);"),
    _m("ig-collision", "    CALL0(collision_register);\n", ""),
    _m("ig-noise", "    CALL0(noise_request);\n", ""),
    _m("ig-oneshot", "    CALL0(oneshot_init);\n", ""),
    _m("ig-order", "    CALL0(collision_register);\n    CALL0(noise_request);\n",
       "    CALL0(noise_request);\n    CALL0(collision_register);\n"),

    # ---- LoadSoundRegionsFrontEnd
    _m("fe-done", FE_HEAD + "    m->done = done;", FE_HEAD + "    m->done = NULL;"),
    _m("fe-param", FE_HEAD + "    m->done = done;\n    m->doneParam = param;",
       FE_HEAD + "    m->done = done;\n    m->doneParam = 0;"),
    _m("fe-loading", FE_HEAD + "    m->done = done;\n    m->doneParam = param;\n"
       "    m->loading = 1;\n",
       FE_HEAD + "    m->done = done;\n    m->doneParam = param;\n"),
    _m("fe-start", FE_REST, FE_REST.replace("    m->loadStart = bGetTicker();\n", "")),
    _m("fe-se", FE_REST, FE_REST.replace("    if (!SoundEnabled)\n        return;\n", "")),
    _m("fe-ingame", FE_REST, FE_REST.replace("    m->inGameRegion = NULL;\n", "")),
    _m("fe-delay", FE_REST, FE_REST.replace("    m->jb->delayedStart = 0.0f;\n", "")),
    _m("fe-selection", "jb_music_set_selection(m->jb, m->audioOptions, JB_CAT_MENU_MUSIC);",
       "jb_music_set_selection(m->jb, m->audioOptions, JB_CAT_RACING_MUSIC);"),
    _m("fe-clear", "    copy_name(m->region[0].name, \"FrontEnd\");",
       "    m->region[3].name[0] = 'x';\n    copy_name(m->region[0].name, \"FrontEnd\");"),
    _m("fe-name", "    copy_name(m->region[0].name, \"FrontEnd\");",
       "    copy_name(m->region[0].name, \"Frontend\");"),
    _m("fe-muted", "    load_region(m, m->region[0].name);\n    m->jb->muted = 0;\n}",
       "    load_region(m, m->region[0].name);\n}"),

    # ---- the completion tests and the poll
    _m("real-se", "    if (!SoundEnabled)\n        return 1;", "    if (!SoundEnabled)\n        return 0;"),
    _m("real-named", "        if (m->region[i].name[0] != '\\0' && !m->region[i].loaded)\n"
       "            return 0;",
       "        if (!m->region[i].loaded)\n            return 0;"),
    _m("real-loaded", "        if (m->region[i].name[0] != '\\0' && !m->region[i].loaded)\n"
       "            return 0;",
       "        if (m->region[i].name[0] != '\\0' && m->region[i].loaded < 0)\n"
       "            return 0;"),
    _m("iscomplete", "    return !m->loading;", "    return m->loading;"),
    _m("poll-loading", "    if (!m->loading)\n        return;\n    if (H && H->joylog_replaying",
       "    if (H && H->joylog_replaying"),
    _m("poll-get-args", "H->joylog_get(H->ctx, 1, 5)", "H->joylog_get(H->ctx, 1, 4)"),
    _m("poll-wait", "        if (ready) {\n            uint32_t last = 0;",
       "        if (!ready) {\n            uint32_t last = 0;"),
    _m("poll-wait-last", "        if (ready) {\n            uint32_t last = 0;",
       "        if (ready) {\n            uint32_t last = vblank(m);"),
    _m("poll-wait-vblank", RWAIT, "                bsound_update(m->bsound);\n"),
    _m("poll-wait-service", "                CALL0(service_files);\n" + RWAIT, RWAIT),
    _m("poll-add-args", "H->joylog_add(H->ctx, ready, 1, 5);", "H->joylog_add(H->ctx, ready, 1, 4);"),
    _m("poll-add-value", "H->joylog_add(H->ctx, ready, 1, 5);", "H->joylog_add(H->ctx, !ready, 1, 5);"),
    _m("hang-limit", "    if (20.0f < bGetTickerDifference", "    if (19.5f < bGetTickerDifference"),
    _m("hang-scale", "bGetTicker()) * 0.001f) {", "bGetTicker()) * 0.00101f) {"),
    _m("hang-from", "bGetTickerDifference(m->loadStart, bGetTicker()) * 0.001f",
       "bGetTickerDifference(m->lastUpdate, bGetTicker()) * 0.001f"),
    _m("hang-flash", "flash(m, 128, 84, 0, \"Hang loading sound\", 0.5f);",
       "flash(m, 128, 84, 0, \"Hang loading sound\", 1.0f);"),
    _m("hang-ready", "        ready = 1;\n    }\n    if (ready) {", "    }\n    if (ready) {"),
    _m("poll-clear", "        m->loading = 0;\n        if (m->done != NULL) {",
       "        if (m->done != NULL) {"),
    _m("poll-done-once", "            m->done(m->doneParam);\n            m->done = NULL;",
       "            m->done(m->doneParam);"),
    _m("poll-done-param", "            m->done(m->doneParam);", "            m->done(0);"),

    # ---- UnLoadSoundRegions
    _m("un-se", "    if (!SoundEnabled)\n        return;\n    CALL0(collision_unregister);",
       "    CALL0(collision_unregister);"),
    _m("un-collision", "    CALL0(collision_unregister);\n", ""),
    _m("un-noise", "    CALL0(noise_unload);\n", ""),
    _m("un-flush", "    CALL0(speech_flush);\n", ""),
    _m("un-oneshot", "    CALL0(oneshot_close);\n", ""),
    _m("un-order", "    for (i = SOUND_REGIONS - 1; i >= 0; i--) {",
       "    for (i = 0; i < SOUND_REGIONS; i++) {"),
    _m("un-named", "        if (m->region[i].name[0] != '\\0') {\n"
       "            bsound_unload_region",
       "        if (1) {\n            bsound_unload_region"),
    _m("un-name", "            m->region[i].name[0] = '\\0';\n            m->region[i].loaded = 0;\n"
       "        }\n    }",
       "            m->region[i].loaded = 0;\n        }\n    }"),
    _m("un-loaded", "            m->region[i].loaded = 0;\n        }\n    }",
       "        }\n    }"),
    _m("un-ingame", "        }\n    }\n    m->inGameRegion = NULL;\n", "        }\n    }\n"),
    _m("un-delay", "    m->frontEndRegion = NULL;\n    m->jb->delayedStart = 0.0f;\n}\n\n"
       "// ---",
       "    m->frontEndRegion = NULL;\n}\n\n// ---"),

    # ---- sound::Update
    _m("upd-poll-after", "    poll_regions(m);\n    if (!SoundEnabled)\n        return;",
       "    if (!SoundEnabled)\n        return;\n    poll_regions(m);"),
    _m("upd-gate", "    if (!(8.0f < bGetTickerDifference", "    if (!(9.0f < bGetTickerDifference"),
    _m("upd-gate-eq", "    if (!(8.0f < bGetTickerDifference", "    if (!(8.0f <= bGetTickerDifference"),
    _m("upd-last", "    m->lastUpdate = bGetTicker();\n", ""),
    _m("upd-speech", "    CALL0(speech_update);\n", ""),
    _m("upd-sed", "    CALL0(sed_update);\n", ""),
    _m("upd-jb", "    jb_update(&jb->jukebox);\n", ""),
    _m("upd-order", "    CALL0(speech_update);\n    CALL0(sed_update);\n",
       "    CALL0(sed_update);\n    CALL0(speech_update);\n"),
    _m("upd-paused", GATE, GATE.replace("!paused(m) && ", "")),
    _m("upd-frontend", GATE, GATE.replace("game_state(m) != JB_STATE_IN_FRONTEND && ", "")),
    _m("upd-muted", GATE, GATE.replace(" && !jb->muted", "")),
    _m("upd-carsounds", "        CALL0(car_sounds_update);\n", ""),
    _m("upd-delay-pos", "        if (0.0f < jb->delayedStart)", "        if (0.0f <= jb->delayedStart)"),
    _m("upd-delay-dt", "jb->delayedStart -= ", "jb->delayedStart += "),
    _m("upd-delay-neg", "        if (jb->delayedStart < 0.0f) {", "        if (jb->delayedStart <= 0.0f) {"),
    _m("upd-start-arg", "jb_music_start(jb, m->audioOptions, 0);", "jb_music_start(jb, m->audioOptions, 1);"),
    _m("upd-delay-reset", "            jb->delayedStart = 0.0f;\n        }\n", "        }\n"),
    _m("upd-collision", "        CALL0(collision_update);\n", ""),
    _m("upd-oneshot", "        CALL0(oneshot_update);\n", ""),
    _m("upd-scape", "        CALL0(scape_update);\n", ""),
    _m("upd-noise", "        CALL0(noise_update);\n", ""),
    _m("upd-order2", "        CALL0(scape_update);\n        CALL0(noise_update);\n",
       "        CALL0(noise_update);\n        CALL0(scape_update);\n"),
    _m("upd-chopper", "        if (helicopter(m))\n            CALL0(chopper_update);",
       "        CALL0(chopper_update);"),
    _m("upd-bsound", "    bsound_update(m->bsound);\n    sound_update_volume_muffler(m);",
       "    sound_update_volume_muffler(m);"),
    _m("upd-muffler", "    bsound_update(m->bsound);\n    sound_update_volume_muffler(m);",
       "    bsound_update(m->bsound);"),
    _m("upd-pvu", "        m->printVoiceUsage = 0;\n", ""),

    # ---- the muffler
    _m("smooth-up", "        return up;", "        return b;"),
    _m("smooth-down", "        return down;", "        return b;"),
    _m("smooth-down-step", "    down = a - step;", "    down = a - step * 0.5f;"),
    _m("muf-rate", "    float rate = 0.1f;", "    float rate = 0.11f;"),
    _m("muf-volume", "    float volume = -1.0f;", "    float volume = 0.0f;"),
    _m("muf-any", "        any = any || (muffle && zone);", "        any = muffle && zone;"),
    _m("muf-zone", "        any = any || (muffle && zone);", "        any = any || muffle;"),
    _m("muf-first", "        if (any && volume == -1.0f)", "        if (any)"),
    _m("muf-first-any", "        if (any && volume == -1.0f)", "        if (volume == -1.0f)"),
    _m("muf-post-muted", "    if (!m->jb->muted\n        && (H && H->race_state",
       "    if (1\n        && (H && H->race_state"),
    _m("muf-post-state", "H->race_state(H->ctx) : -1) == 7) {", "H->race_state(H->ctx) : -1) == 6) {"),
    _m("muf-post-none", "H->race_state(H->ctx) : -1) == 7) {", "H->race_state(H->ctx) : 7) == 7) {"),
    _m("muf-post-target", "        m->muffleTarget = 0.5f;", "        m->muffleTarget = 0.6f;"),
    _m("muf-zone-muted", "    } else if (!m->jb->muted && any) {", "    } else if (any) {"),
    _m("muf-zone-rate", "        rate = 0.05f;", "        rate = 0.06f;"),
    _m("muf-zone-target", "        m->muffleTarget = volume;", "        m->muffleTarget = 0.5f;"),
    _m("muf-speech-muted", "    } else if (!m->jb->muted && H && H->speech_sed_playing",
       "    } else if (H && H->speech_sed_playing"),
    _m("muf-speech-race", "JB_STATE_IN_FRONTEND ? 0.95f : 0.3f;", "JB_STATE_IN_FRONTEND ? 0.9f : 0.3f;"),
    _m("muf-speech-fe", "JB_STATE_IN_FRONTEND ? 0.95f : 0.3f;", "JB_STATE_IN_FRONTEND ? 0.95f : 0.35f;"),
    _m("muf-speech-state", "game_state(m) != JB_STATE_IN_FRONTEND ? 0.95f",
       "game_state(m) == JB_STATE_IN_FRONTEND ? 0.95f"),
    _m("muf-else-rate", "        rate = 0.2f;", "        rate = 0.25f;"),
    _m("muf-else-target", "        rate = 0.2f;\n        m->muffleTarget = 1.0f;",
       "        rate = 0.2f;\n        m->muffleTarget = 0.9f;"),
    _m("muf-same", "        if (!(v == m->muffleCurrent)) {", "        if (1) {"),
    _m("muf-store", "            m->muffleCurrent = v;\n", ""),
    _m("muf-speech-too", "            sound_scale_category_volumes(m, v, 0);",
       "            sound_scale_category_volumes(m, v, 1);"),

    # ---- ScaleCategoryVolumes
    _m("scale-same", "    if (!(scale == m->lastScale)) {", "    if (1) {"),
    _m("scale-cats", "{0, 1, 2, 5, 4};", "{0, 1, 2, 4, 5};"),
    _m("scale-count", "        for (i = 0; i < 5; i++)\n            bsound_set_category_volume",
       "        for (i = 0; i < 4; i++)\n            bsound_set_category_volume"),
    _m("scale-saved", "jb->savedVolume[i] * scale);", "jb->savedVolume[i]);"),
    _m("scale-speech-cat", "bsound_set_category_volume(m->bsound, JB_CAT_SPEECH,",
       "bsound_set_category_volume(m->bsound, JB_CAT_MENU_SFX,"),
    _m("scale-speech-flag", "speechToo ? jb->savedSpeechVolume * scale\n"
       "                                             : jb->savedSpeechVolume",
       "speechToo ? jb->savedSpeechVolume\n"
       "                                             : jb->savedSpeechVolume * scale"),
    _m("scale-store", "    m->lastScale = scale;\n", ""),
    _m("scale-store-inside", "                                             : jb->savedSpeechVolume);\n"
       "    }\n    m->lastScale = scale;",
       "                                             : jb->savedSpeechVolume);\n"
       "        m->lastScale = scale;\n    }"),

    # ---- sound::Mute, MuteReplay, MuteCarSounds
    _m("mute-se", "    if (!SoundEnabled)\n        return;\n    jb->muted = on;",
       "    jb->muted = on;"),
    _m("mute-store", "    if (!SoundEnabled)\n        return;\n    jb->muted = on;",
       "    if (!SoundEnabled)\n        return;"),
    _m("mute-music", "    if (jb->musicEnabled) {\n        JBPlayer* p", "    if (1) {\n        JBPlayer* p"),
    _m("mute-vol", "        if (!(0.0f < bsound_get_category_volume", "        if ((0.0f < bsound_get_category_volume"),
    _m("mute-vol-on", "            && on == 0)\n            pause = 1;", "            )\n            pause = 1;"),
    _m("mute-vol-cat", "bsound_get_category_volume(m->bsound, p->soundCategory)",
       "bsound_get_category_volume(m->bsound, JB_CAT_MENU_MUSIC)"),
    _m("mute-pause", "        jb_pause(p, (uint32_t)pause);", "        jb_pause(p, (uint32_t)on);"),
    _m("mute-speechen", "    if (m->speechEnabled) {\n        CALL1(speech_mute, on);",
       "    if (1) {\n        CALL1(speech_mute, on);"),
    _m("mute-speech", "        CALL1(speech_mute, on);\n", ""),
    _m("mute-noise", "        CALL1(noise_mute, on);\n", ""),
    _m("mute-scape", MUTE_TAIL, MUTE_TAIL.replace("    CALL1(scape_mute, on);\n", "", 1)),
    _m("mute-cars", MUTE_TAIL, MUTE_TAIL.replace("    sound_mute_car_sounds(m, on);\n", "", 1)),
    _m("mute-oneshot", MUTE_TAIL, MUTE_TAIL.replace("    CALL1(oneshot_mute, on);\n", "", 1)),
    _m("mute-collision", MUTE_TAIL, MUTE_TAIL.replace("    CALL1(collision_mute, on);\n", "", 1)),
    _m("mute-chopper", MUTE_TAIL, MUTE_TAIL.replace("    if (helicopter(m))\n        CALL1", "    CALL1", 1)),
    _m("mute-order", MUTE_TAIL, MUTE_TAIL.replace(
        "    CALL1(scape_mute, on);\n    sound_mute_car_sounds(m, on);\n",
        "    sound_mute_car_sounds(m, on);\n    CALL1(scape_mute, on);\n", 1)),
    _m("mr-se", "    if (!SoundEnabled)\n        return;\n" + MR_TAIL, MR_TAIL),
    _m("mr-store", MR_TAIL, MR_TAIL.replace("    m->jb->muted = on;\n", "")),
    _m("mr-cars", MR_TAIL, MR_TAIL.replace("    sound_mute_car_sounds(m, on);\n", "")),
    _m("mr-oneshot", MR_TAIL, MR_TAIL.replace("    CALL1(oneshot_mute, on);\n", "")),
    _m("mr-collision", MR_TAIL, MR_TAIL.replace("    CALL1(collision_mute, on);\n", "")),
    _m("mr-scape", MR_TAIL, MR_TAIL.replace("    CALL1(scape_mute, on);\n", "")),
    _m("mr-chopper", MR_TAIL, MR_TAIL.replace("    if (helicopter(m))\n        CALL1", "    CALL1")),
    _m("mr-order", MR_TAIL, MR_TAIL.replace(
        "    CALL1(collision_mute, on);\n    CALL1(scape_mute, on);\n",
        "    CALL1(scape_mute, on);\n    CALL1(collision_mute, on);\n")),
    _m("mc-null", "        if (s != NULL && H->car_sound_mute)", "        if (H->car_sound_mute)"),
    _m("mc-count", "    for (i = 0; i < n; i++) {\n        void* s", "    for (i = 1; i < n; i++) {\n        void* s"),
    _m("mc-on", "            H->car_sound_mute(H->ctx, s, on);", "            H->car_sound_mute(H->ctx, s, on != 0);"),

    # ---- the samples, random, the mode
    _m("gs-cache", "    if (m->inGameRegion == NULL) {\n        m->inGameRegion = bsound_region",
       "    if (1) {\n        m->inGameRegion = bsound_region"),
    _m("gs-name", "bsound_region(m->bsound, \"InGame\");", "bsound_region(m->bsound, \"FrontEnd\");"),
    _m("gs-null", "        if (m->inGameRegion == NULL)\n            return NULL;\n", ""),
    _m("pc-se", "    if (!SoundEnabled)\n        return;\n    s = bregion_sample", "    s = bregion_sample"),
    _m("pc-region", "s = bregion_sample(bsound_common_region(m->bsound), name);",
       "s = bregion_sample(bsound_region(m->bsound, \"common\"), name);"),
    _m("pc-cat", "    bsample_set_category(s, JB_CAT_MENU_SFX);\n    bsample_play(s, volume",
       "    bsample_set_category(s, JB_CAT_SFX);\n    bsample_play(s, volume"),
    _m("pc-play", "    bsample_play(s, volume, 0.0f, 0.0f);", "    bsample_play(s, 1.0f, 0.0f, 0.0f);"),
    _m("fin-name", "\"FinishLine\"", "\"Finishline\""),
    _m("fin-null", "    if (s != NULL)\n        bsample_play(s, 1.0f", "    if (1)\n        bsample_play(s, 1.0f"),
    _m("fin-volume", "        bsample_play(s, 1.0f, 0.0f, 0.0f);\n}", "        bsample_play(s, 0.5f, 0.0f, 0.0f);\n}"),
    _m("rand-seed", "    return bRandomI(range, &m->seed);", "    return bRandomI(range, &bDefaultSeed);"),
    _m("randf-seed", "    return bRandomF(range, &m->seed);", "    return bRandomF(range, &bDefaultSeed);"),
    _m("mode-bsound", "    bsound_set_mode(m->bsound, mode);\n", ""),
    _m("mode-store", "    m->audioMode = mode;\n", ""),
    _m("mode-get", "    return m->audioMode;", "    return m->audioMode != 0;"),
]
EQUIVALENT = {
    "ig-empty-car": "four slots, and at most three are named before the "
                    "second driver, so an empty name always matches an "
                    "empty slot and is skipped either way",
    "muf-post-none": "the -1 is the port's guard for a hook main.c always "
                     "fills; retail reads the race state itself",
}


def mutate_pass(only):
    todo = MUTATIONS
    if only is not None:
        todo = [m for m in MUTATIONS if m[0] in only]
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
        if diff(base, out.read_text().splitlines(), quiet=True):
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
        harness = out.read_text().splitlines()

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
