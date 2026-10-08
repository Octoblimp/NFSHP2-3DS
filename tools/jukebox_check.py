#!/usr/bin/env python3
"""Cross-check 3DS Files/source/jukebox.c against the retail image,
SLES_507.31.

**The model** is retail's own code run in retail_model.RetailEmu: the
cartridge (cJukeboxCartridge), the player (cJukeboxPlayer, the one at
0x003115d0), sound::jukebox's Start, Stop, DelayedStart, IsPlaying,
SetSelection and the track-string getters, SaveVolumesForSpeech and the
saved-volume getter (0x001ae028), sound::Update, sound::Mute, and
DataAudioOptionsScreen's SetAudioDataFromSound, InitWithDefaults (with
GenreMgr::Populate) and the apply at 0x001ef120 -- on Fred's own block at
0x002fc0e4. The harness (tools/src/jukebox_test.c) runs jukebox.c's.

**The stubs.** Everything the jukebox asks of the sound driver is a stub
that prints, on both sides: the bSampleStream's creation (by its
SetSampleRate), destruction (by the virtual destructor Close calls through
the vtable at +184), and its Play by file and range, Play, Stop, Pause,
Fade, Cleanup, SetCategory and SetScaleVolume; the file's bOpen, bRead and
bClose, served from the scenario's cartridge; SetAudioMode. bSound's
category volumes are a table of sixteen, 1.0 to start, on both sides.
bAssertFail prints its line and ends the op, as retail's bBreak ends the
game. sound::Update's other callees (speech, the SED wedge, the car
sounds, the scapes, bSound::Update) are silent, and the ticker says 16 ms
have gone.

**The cartridges** are retail JUKEBOXM.JBC's header and index; a small
one of five categories with sync data, a tune listed twice, names cut
every way ExtractJukeboxTrackStrings can cut them, six genres and all six
statuses; and one of 130 tunes, past m_pTune's 128.

**The script** loads, closes and reloads them, plays the retail boot's
menu tune, runs the callbacks through play end, fade end and the buffer
events, the first-pick one-shots in the menu, a race and a pursuit, the
random first advance, the pause rules under each music volume, the
delayed start through sound::Update paused, muted and in the frontend,
sound::Mute under each enable and category volume, the playlist's statuses and genre mask, and each assert. After an op the
harness and the model print the same lines; `dump` prints the player,
its categories and tunes, the sound statics and Fred's 176 bytes.

    python tools/jukebox_check.py
    python tools/jukebox_check.py --mutate [--only a,b]
    python tools/jukebox_check.py --dump out/jukebox
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

HARNESS = "tools/src/jukebox_test.c"
JBC = "3DS Files/source/jukebox.c"
SOURCES = [HARNESS, JBC, "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c"]
HARNESS_TIMEOUT = 30
RETAIL_JBC = ROOT / "extracted-retail" / "SOUND" / "JUKEBOXM.JBC"

GP = retail_model.RETAIL_GP
JB = 0x003115d0                 # Jukebox
AO = 0x002fc0e4                 # Fred's DataAudioOptionsScreen
SE, ME = GP - 23056, GP - 23048
FIRST = (GP - 18928, GP - 18924, GP - 18920, GP - 18916)
DELAY, MUTED = GP - 19028, GP - 19040
STATE, VBLANK, DT = GP - 21420, GP - 19616, GP - 19560
COPS = 0x0031aaf4               # TheRaceParameters.nMaxCops
SAVED, SPEECH, KEY = 0x00313878, GP - 19024, GP - 18912
CHOPPER, VOICEUSAGE = GP - 22120, GP - 18904
DEMODISC = 0x002effe0           # TheDemoDiscManager.bActive

F = {
    "ctor": 0x001b0130,             # _GLOBAL_$I$Jukebox
    "load": 0x0027dac8, "close": 0x0027de40,
    "start": 0x0027d640, "starttune": 0x0027d6a8, "stopj": 0x0027d868,
    "fade": 0x0027d8f8, "fadeadv": 0x0027d9a0, "advance": 0x0027da30,
    "update": 0x0027dff8, "seton": 0x0027e170, "event": 0x0027e1d8,
    "stopplaying": 0x0027e340, "jpause": 0x0027e3e8,
    "startfading": 0x0027e490, "startplayingtune": 0x0027e530,
    "startplaying": 0x0027e6c8, "setvol": 0x0027e768,
    "tuneon": 0x0027e7d8, "tuneoff": 0x0027e900, "gettuneon": 0x0027ea28,
    "caton": 0x0027eb70, "catoff": 0x0027ec10, "pick": 0x0027eca8,
    "isplaying": 0x002801d8, "isfading": 0x00280180,
    "name": 0x0027c8e0, "offset": 0x0027ca00, "size": 0x0027cca8,
    "id": 0x0027cee8, "addcat": 0x0027d008, "addtune": 0x0027d220,
    "mstart": 0x001aeab0, "delayed": 0x001aec88, "mstop": 0x001aec90,
    "misplaying": 0x001aecb0, "select": 0x001af050,
    "artist": 0x001aeee0, "trackname": 0x001aee90, "label": 0x001aef30,
    "genre": 0x001aef80, "status": 0x001aefd0, "current": 0x001af040,
    "savedvol": 0x001ae028, "saved": 0x001af7e0,
    "defvol": 0x001afab8,
    "soundupdate": 0x001af4c0, "mute": 0x001af850,
    "fromsound": 0x001eef60, "defaults": 0x001ef1c8, "apply": 0x001ef120,
}
TRACK = ("artist", "trackname", "label", "genre")

# The sample's calls, by retail address: (name, how its arguments print).
SAMPLE_CALLS = [
    (0x00273ff8, "load"), (0x00274080, "play"), (0x00274618, "stop"),
    (0x00274488, "pause"), (0x00274868, "fade"), (0x00273360, "cleanup"),
    (0x00273618, "category"), (0x00273be8, "scale"),
]
# Callees that print nothing and return nothing worth having.
SILENT = [
    0x00257850,                     # bFree
    0x00114e98,                     # __builtin_delete
    0x00273280,                     # bSample::Initialize
    0x0025f510,                     # bSnd_SetLoadPath
    0x00278250,                     # bSound::Printf
    0x001af308, 0x00250f38,         # sound::Update's first call, bGetTicker
    0x00209ff8, 0x002061e8,         # speech update, cSEDWedge::Update
    0x0018ea18, 0x001e51b8,         # UpdateCarSounds, collision_sound
    0x002092a0, 0x001cebf0,         # sound3d_oneshot, sound_scape
    0x002157c0, 0x002778f8,         # SpeechNoise, bSound::Update
    0x001ae110, 0x00278190,         # UpdateVolumeMuffler, bSound::SetMode
    # sound::Mute's other callees: the speech and its noise, the scapes,
    # the car sounds, the one-shots, the collisions and the chopper.
    0x0020a2b0, 0x002158a0, 0x001cebf8, 0x001af6f8, 0x00209320,
    0x001e51c0, 0x001ead80,
]
ALLOCS = [0x002577c0, 0x0025e608, 0x0025e580, 0x00275c88]


def fbits(v):
    return struct.unpack("<I", struct.pack("<f", v))[0]


# ============================================================= cartridges

def jbc(rate, cats):
    idx = b""
    for name, tunes in cats:
        idx += struct.pack("<I60s", len(tunes), name.encode("latin-1"))
        for tname, off, size, sync in tunes:
            idx += struct.pack("<III84s", off, size, sync,
                               tname.encode("latin-1"))
    return struct.pack("<8I", 16, 2, rate, len(cats), len(idx), 0, 0, 0) + idx


def retail_cart():
    with open(RETAIL_JBC, "rb") as fh:
        head = fh.read(32)
        n = struct.unpack_from("<I", head, 16)[0]
        return head + fh.read(n)


def small_cart():
    return jbc(22050, [
        ("Menu", [
            ("Alpha Band-First Song-Label A-Rock-4", 0x1000, 0x8030, 0),
            ("Beta-Second--Techno-2", 0x9000, 0x10030, 1),
            ("Gamma-Third-L-Rock-5", 0x20000, 0x30, 2047),
            ("Delta", 0x30000, 100, 2048),
            ("Eps-Five-X-Jazz-1", 0x31000, 0x60, 4097),
            ("Zeta-Six-Y-Pop-3", 0x32000, 0x70, 0),
        ]),
        ("Race", [
            ("Beta-Second--Techno-2", 0x40000, 0x50, 0),
            ("Eta-Seven-", 0x41000, 0x80, 0),
            ("-Theta-Name-Lab-Metal-12x", 0x42000, 0x90, 0),
            ("Iota-Nine-Lab-Soul-0", 0x43000, 0xa0, 0),
            ("Kappa-Ten-Lab-Rock--4", 0x44000, 0xb0, 0),
        ]),
        ("Empty", []),
        ("Chase", [
            ("Lambda-Eleven-Lab-Rock-2", 0x50000, 0xc0, 0),
            ("Mu-Twelve-Lab-Pop-1", 0x51000, 0xd0, 8191),
            ("Nu-Thirteen-Lab-Jazz-5", 0x52000, 0xe0, 0),
            ("Xi-Fourteen-Lab-Techno-4", 0x53000, 0xf0, 0),
            ("Omicron-Fifteen-Lab-Rock-3", 0x54000, 0x100, 0),
            ("Sigma-Empty-L--4", 0x55000, 0x110, 0),
        ]),
        ("Last", [
            ("Pi-Sixteen-Lab-Soul-4", 0x60000, 0x110, 0),
            ("Rho-a-b-Rock-d-e-f-g-h-i-j-k-l-m", 0x61000, 0x120, 0),
        ]),
    ])


def big_cart():
    tunes = [("T%03d-N%03d--%s-%d" % (i, i, ("Rock", "Techno")[i % 2], i % 6),
              0x1000 * i, 0x40 + i, 0) for i in range(130)]
    # a genre there but empty, with only two before it
    tunes[3] = ("T003-N003-L--3", 0x3000, 0x43, 0)
    return jbc(32000, [("Big", tunes)])


CARTS = [retail_cart, small_cart, big_cart]


# ================================================================= script

def script():
    s = []
    a = s.append
    ext = s.extend
    # Before anything: the statics, and the player with no cartridge.
    ext(["dump", "name|0|0", "offset|1|0", "size|0|0", "id|0|0",
         "start|1", "stopj", "fade|500", "fadeadv|500", "advance",
         "update", "isplaying", "isfading", "misplaying", "pick",
         "stopplaying", "jpause|1", "startfading|10",
         "startplayingtune|0|0", "startplaying", "tuneon|0|0",
         "tuneoff|0|0", "gettuneon|0|0", "caton|0", "catoff|0",
         "track|0|0|1", "status|0|0", "current", "setvol|3f000000",
         "dump", "seton|0", "seton|0", "seton|1", "setvol|3f800000",
         "select|4", "dump"])
    for c in range(8):
        a("savedvol|%d" % c)
    # The driver down: LoadCartridge does nothing. Then no file.
    ext(["soundup|0", "cart|1", "load", "dump", "soundup|1", "cart|0",
         "load", "dump"])
    # The retail cartridge, as the boot loads it.
    ext(["cart|1", "load", "defvol", "dump", "load", "mode|1", "defaults",
         "dump"])
    for t in (0, 5, 22, 23):
        for f in range(4):
            a("track|0|%d|%d" % (t, f))
        a("status|0|%d" % t)
    ext(["name|0|5", "offset|0|5", "size|0|5", "id|0|5", "name|0|23",
         "name|1|0", "offset|0|99", "size|3|0", "id|0|40",
         "startplayingtune|0|99", "dump", "startplayingtune|3|1", "current"])
    # The frontend: SetSelection(5), the title's Start.
    ext(["state|3", "vblank|12345", "select|5", "dump", "mstart", "dump",
         "track|-1|-1|0", "track|-1|-1|1", "current", "misplaying",
         "event|128", "event|4", "dump", "update", "dump", "isplaying",
         "misplaying", "mstart", "event|64", "update", "event|8", "dump",
         "update", "dump", "event|4", "update", "mstart"])
    # Fading out, and the fade end.
    ext(["fade|1000", "isfading", "fade|1000", "fadeadv|10", "dump",
         "event|4", "update", "dump", "starttune|0|3|0", "event|4",
         "update", "fadeadv|250", "event|32", "dump", "update", "dump",
         "event|8", "update", "dump"])
    # Everything asked while a fade runs.
    ext(["starttune|0|2|1", "event|4", "update", "fade|800", "dump",
         "isplaying", "isfading", "jpause|1", "jpause|0", "startfading|300",
         "state|3", "misplaying", "state|6", "misplaying", "mstart", "dump",
         "stopplaying", "dump", "starttune|0|3|1", "event|4", "update",
         "fadeadv|200", "stopj", "dump", "starttune|0|4|1", "event|4",
         "isplaying", "dump", "starttune|0|5|1", "event|4", "update",
         "fade|500", "starttune|0|7|1", "event|4", "update", "dump",
         "fade|500", "event|32", "isfading", "dump",
         "starttune|0|1|1", "event|4", "update", "enable|1|0", "mstop",
         "dump", "enable|1|1", "stopj"])
    # The fallback: the menu's first pick is spent; the first advance.
    ext(["mstart", "dump", "stopj", "mstart", "dump", "stopj"])
    # A race, then a pursuit, each first pick once.
    ext(["state|6", "cops|0", "select|4", "dump", "mstart", "dump",
         "stopj", "mstart", "dump", "stopj", "cops|3", "select|4", "dump",
         "mstart", "dump", "stopj", "mstart", "stopj", "cops|0"])
    ext(["oneshots|1|1|1|0", "cops|1", "select|4", "stopj", "mstart", "dump",
         "stopj", "cops|0", "state|3", "select|5", "oneshots|1|1|1|0",
         "aob|50|0", "mstart", "dump", "stopj", "oneshots|1|1|1|0",
         "aob|50|4", "aob|175|0", "mstart", "dump", "stopj", "aob|175|0xff",
         "oneshots|0|0|0|0", "state|6"])
    # The pause rules: racing and menu music at 0, in and out of the
    # frontend, and IsPlaying with them.
    ext(["setcatvol|4|0", "setcatvol|5|3f000000", "saved", "dump",
         "savedvol|4", "savedvol|5", "savedvol|3", "starttune|0|1|1",
         "mstart", "misplaying", "state|3", "mstart", "misplaying",
         "setcatvol|5|0", "setcatvol|4|3f400000", "saved", "mstart",
         "state|6", "mstart", "misplaying", "setcatvol|5|80000000",
         "saved", "state|3", "mstart", "setcatvol|4|bf800000", "saved",
         "state|6", "misplaying", "setcatvol|4|3f800000",
         "setcatvol|5|3f800000", "setcatvol|6|3e800000",
         "setcatvol|16|3e800000", "saved", "dump"])
    # Each pause rule from a stop, so the Pauses reach the sample.
    for st in (3, 6):
        for v4 in ("0", "3f000000"):
            for v5 in ("0", "3f000000", "80000000"):
                ext(["setcatvol|4|" + v4, "setcatvol|5|" + v5, "saved",
                     "state|%d" % st, "stopj", "mstart", "misplaying"])
    ext(["setcatvol|4|3f800000", "setcatvol|5|3f800000", "saved"])
    # sound::Mute, the pause's: the flag, and the jukebox's Pause by the
    # volume of its category, up, down to nothing and below, under each
    # enable; and stopped, with no sample to pause.
    for se, me in ((0, 1), (1, 0), (1, 1)):
        a("enable|%d|%d" % (se, me))
        for cat in (5, 4):
            a("select|%d" % cat)
            for v in ("3f000000", "0", "bf800000"):
                a("setcatvol|%d|%s" % (cat, v))
                for on in (1, 0, 2):
                    ext(["starttune|0|1|1", "event|4", "update",
                         "mute|%d" % on, "dump"])
            a("setcatvol|%d|3f800000" % cat)
    ext(["enable|1|1", "stopj", "mute|1", "dump", "mute|0", "dump",
         "muted|0", "select|5"])
    # DelayedStart through sound::Update.
    ext(["stopj", "delayed|3fc00000", "dt|3f000000", "state|6",
         "soundupdate", "dump", "paused|1", "soundupdate", "dump",
         "paused|0", "muted|1", "soundupdate", "muted|0", "state|3",
         "soundupdate", "state|6", "soundupdate", "soundupdate", "dump",
         "soundupdate", "dump", "delayed|bf800000", "soundupdate", "dump",
         "delayed|0", "soundupdate", "event|4", "soundupdate", "dump",
         "enable|0|1", "delayed|3f000000", "soundupdate", "dump",
         "enable|1|1"])
    ext(["stopj", "delayed|3f800000", "dt|3ec00000", "state|6", "soundupdate",
         "muted|1", "soundupdate", "muted|0", "dump", "state|3", "soundupdate",
         "state|6", "dump", "soundupdate", "dump", "soundupdate", "dump",
         "stopj", "dt|3f000000"])
    # The volumes and the options block.
    ext(["setvol|3f000000", "dump", "setcatvol|0|3f000000",
         "setcatvol|1|3e000000", "setcatvol|2|3d000000",
         "setcatvol|3|3c000000", "fromsound|0", "dump", "mode|2",
         "fromsound|1", "dump", "aow|0|0x3f200000", "aow|4|0",
         "aow|24|0x3f100000", "aob|172|7", "aob|173|1", "apply", "dump",
         "mode|1"])
    ext(["aow|8|0x3e800000", "aow|12|0x3e400000", "aow|16|0x3e200000",
         "aow|20|0x3e100000", "aob|172|0xff", "aob|173|0xff", "apply", "dump",
         "setcatvol|15|3e000000", "setcatvol|14|3e000000", "dump"])
    for c in range(8):
        a("savedvol|%d" % c)
    ext(["defvol", "dump", "aob|173|0x80"])
    # Music off, sound off.
    ext(["enable|1|0", "mstart", "track|0|0|1", "status|0|0",
         "select|5", "mstop", "delayed|3f800000", "dump", "enable|0|1",
         "mstart", "enable|1|1", "mstop", "dump"])
    # Off and on.
    ext(["starttune|0|2|1", "event|4", "update", "seton|0", "dump",
         "starttune|0|3|1", "startplaying", "advance", "dump", "seton|1",
         "advance", "dump", "event|8", "update", "dump"])
    ext(["start|0", "event|4", "update", "event|8", "update", "dump",
         "start|2", "event|4", "update", "event|8", "update", "dump",
         "starttune|0|1|2", "event|4", "update", "event|8", "update", "dump"])
    # The small cartridge: close, reload, and everything it can say.
    ext(["close", "dump", "close", "event|8", "update", "dump", "event|32",
         "update", "dump", "event|128", "event|1", "event|16", "event|2",
         "update", "dump"])
    ext(["cart|2", "load", "dump", "defaults", "dump"])
    for c in range(6):
        for t in range(7):
            for f in range(4):
                a("track|%d|%d|%d" % (c, t, f))
            a("status|%d|%d" % (c, t))
            a("offset|%d|%d" % (c, t))
    ext(["track|4|1|1", "track|3|0|1", "track|4|1|1"])
    for tn in range(1, 5):
        a("id|0|%d" % tn)
    for cat in (5, 4):
        for cops in (0, 1):
            ext(["cops|%d" % cops, "select|%d" % cat, "dump"])
    # The genre mask.
    for mask in ("0x01", "0x02", "0x05", "0x80", "0"):
        ext(["aob|175|%s" % mask, "select|5", "dump"])
    ext(["aob|175|0xff", "aob|31|7", "aob|35|8", "aob|39|0xff",
         "aob|43|31", "select|5", "dump", "aob|30|0", "aob|34|6",
         "select|5", "dump"])
    ext(["defaults", "state|3", "select|5"])
    # The picker round the categories.
    for k in range(14):
        a("pick")
    ext(["dump", "catoff|0", "pick", "pick", "catoff|3", "catoff|4",
         "pick", "pick", "catoff|1", "pick", "caton|0", "caton|1",
         "caton|3", "caton|4", "catoff|9", "caton|5", "caton|6"])
    for c, t in ((0, 0), (0, 5), (0, 6), (1, 4), (1, 5), (3, 0), (5, 0),
                 (2, 0)):
        ext(["tuneoff|%d|%d" % (c, t), "gettuneon|%d|%d" % (c, t),
             "tuneon|%d|%d" % (c, t), "gettuneon|%d|%d" % (c, t)])
    ext(["tuneoff|0|1", "pick", "pick", "pick", "dump"])
    # The one-shots are spent; the small cartridge's first advance.
    ext(["starttune|0|4|1", "event|4", "update", "event|8", "update",
         "dump", "fadeadv|1", "event|32", "update", "dump"])
    # The first advance, from the smallest category, by three seeds.
    for seed in (1, 77, 31337):
        ext(["stopj", "oneshots|0|0|0|1", "vblank|%d" % seed,
             "starttune|3|0|1", "stopj", "mstart", "dump"])
    ext(["stopj", "oneshots|0|0|0|0"])
    # Adding by hand.
    ext(["addcat|Menu", "addcat|Race", "addcat|New One", "addcat|Last",
         "addtune|New One|Fresh-One-L-Rock-4|1|2|3|4",
         "addtune|Menu|Delta|5|6|7|8", "addtune|Other|Delta|9|10|11|12",
         "dump", "name|6|0", "id|1|5", "id|6|0", "offset|5|0",
         "size|6|1", "addtune|Last|Upsilon-Big-L-Rock-12|1|2|3|4",
         "status|3|2", "addtune|Last|Phi-X-L-Rock-3x|1|2|3|4", "status|3|3"])
    # The big cartridge: past 128 tunes, past 32 in the list.
    ext(["close", "cart|3", "load", "dump", "defaults", "dump",
         "select|5", "dump", "vblank|7", "state|3", "mstart", "dump",
         "track|0|127|1", "track|0|128|1", "status|0|100",
         "addtune|Big|Extra-One--Rock-1|1|2|3|4", "dump"])
    return s


# ================================================================= model

class Abort(Exception):
    pass


class Model(object):
    def __init__(self, carts):
        self.carts = carts
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        e.stub_bware()
        self.vol = [fbits(1.0)] * 16
        self.cart = 0
        self.pos = 0
        self.sound_up = 1
        self.mode = 0
        self.paused = 0
        self.fileobj = e.alloc(64)
        self.path = e.alloc(64)
        self.write_str(self.path, "SOUND\\JukeboxM.JBC")
        self.empty = e.alloc(16)
        self.vtable = e.alloc(64)
        self.dtor = e.alloc(16)
        self.speech = e.alloc(64)
        self.locals = e.alloc(64)
        self.strbuf = e.alloc(256)
        self.chopper = e.alloc(32)
        e.put32(self.vtable + 12, self.dtor)
        for a in SILENT:
            e.stub(a, lambda em: 0)
        for a in ALLOCS:
            e.stub(a, lambda em: em.alloc(max(s32(em.reg[4]), 4), 8))
        for addr, name in SAMPLE_CALLS:
            e.stub(addr, self.sample_stub(name))
        e.stub(self.dtor, lambda em: self.emit("  destroy"))
        e.stub(0x00280370, self.sample_ctor)
        e.stub(0x00280340, self.sample_rate)
        e.stub(0x00280298, lambda em: self.empty)       # bSound::GetPath
        e.stub(0x002544c0, self.b_open)
        e.stub(0x002547f0, self.b_read)
        e.stub(0x002544e8, lambda em: self.emit("  close"))
        e.stub(0x00250ac0, self.assert_fail)
        e.stub(0x00277ea0, lambda em: self.sound_up)
        e.stub(0x00277dc0, self.get_vol)
        e.stub(0x00277cb0, self.set_vol)
        e.stub(0x001afa10, lambda em: self.mode)
        e.stub(0x001af9e0, lambda em: self.emit(
            "  audiomode %d" % s32(em.reg[4])))
        e.stub(0x00250f48, self.ticker_diff)
        e.stub(0x00209ef0, lambda em: self.speech)
        e.stub(0x001b0188, lambda em: self.speech)
        e.stub(0x001680b8, lambda em: self.paused)
        e.put32(CHOPPER, 0)
        e.put32(VOICEUSAGE, 0)
        e.put32(DEMODISC, 0)
        e.call(F["ctor"], limit=10000)

    def emit(self, s):
        self.out.append(s)

    def write_str(self, a, s):
        self.e.write(a, s.encode("latin-1") + b"\0")

    def cstr(self, a, n=200):
        b = bytearray()
        mem = self.e.mem
        while len(b) < n and mem[a]:
            b.append(mem[a])
            a += 1
        return b.decode("latin-1")

    # ---- stubs

    def sample_stub(self, name):
        def stub(em):
            r = em.reg
            if name == "load":
                self.emit("  load %s %u %u" % (self.cstr(r[5] & M32),
                                               r[6] & M32, r[7] & M32))
            elif name == "play":
                self.emit("  play %08x %08x %08x" % (
                    em.fpr[12] & M32, em.fpr[13] & M32, em.fpr[14] & M32))
            elif name == "pause":
                self.emit("  pause %d" % (1 if r[5] & 0xff else 0))
            elif name == "fade":
                self.emit("  fade %08x %u" % (em.fpr[12] & M32, r[5] & M32))
            elif name == "category":
                self.emit("  category %u" % (r[5] & M32))
            elif name == "scale":
                self.emit("  scale %08x" % (em.fpr[12] & M32))
            else:
                self.emit("  " + name)
            return 0
        return stub

    def sample_ctor(self, em):
        a = em.reg[4] & M32
        em.put32(a + 184, self.vtable)
        return a

    def sample_rate(self, em):
        self.emit("  create %u" % (em.reg[5] & M32))
        return 0

    def b_open(self, em):
        self.emit("  open %s" % self.cstr(em.reg[4] & M32))
        if not self.cart:
            return 0
        self.pos = 0
        self.write_str(self.fileobj + 8, self.cstr(em.reg[4] & M32))
        return self.fileobj

    def b_read(self, em):
        buf, n = em.reg[5] & M32, s32(em.reg[6])
        self.emit("  read %u" % (n & M32))
        data = self.carts[self.cart - 1]
        chunk = data[self.pos:self.pos + n]
        chunk += b"\0" * (n - len(chunk))
        em.write(buf, chunk)
        self.pos += n
        return n

    def assert_fail(self, em):
        self.emit("  assert %d" % s32(em.reg[6]))
        raise Abort()

    def get_vol(self, em):
        cat = em.reg[5] & M32
        em.fpr[0] = self.vol[cat] if cat < 16 else fbits(1.0)
        return None

    def set_vol(self, em):
        cat = em.reg[5] & M32
        if cat < 16:
            self.vol[cat] = em.fpr[12] & M32
        return 0

    def ticker_diff(self, em):
        em.fpr[0] = fbits(16.0)
        return None

    # ---- the dump

    def dump(self):
        e = self.e
        u = e.u32
        cats, tunes = u(JB), u(JB + 68)
        self.emit("  player cats=%u tunes=%u file=%d sample=%d state=%u "
                  "keep=%u cur=%u,%u on=%u cat=%u vol=%08x trig=%u pbp=%u "
                  "last=%u" % (
                      cats, tunes, 1 if u(JB + 8776) else 0,
                      1 if u(JB + 8816) else 0, u(JB + 8820),
                      u(JB + 8824), u(JB + 8836), u(JB + 8840),
                      u(JB + 8844), u(JB + 8848), u(JB + 8852),
                      u(JB + 8856), u(JB + 8860), u(JB + 8864)))
        self.emit("  hdr " + " ".join(
            "%u" % u(JB + 8784 + 4 * i) for i in range(8)))
        for c in range(min(cats, 16)):
            p = u(JB + 4 + 4 * c)
            n = u(p + 4)
            idx = ",".join("%u" % u(p + 16 + 4 * t)
                           for t in range(min(n, 128)))
            self.emit("  cat %u %s n=%u use=%u last=%u idx=%s" % (
                c, self.cstr(u(p)), n, u(p + 8), u(p + 12), idx))
        for t in range(min(tunes, 128)):
            p = u(JB + 72 + 4 * t)
            self.emit("  tune %u %s use=%u size=%u off=%u sync=%u id=%u" % (
                t, self.cstr(u(p)), u(p + 4), u(p + 8), u(p + 12),
                u(p + 16), u(p + 20)))
        self.emit("  sound se=%d me=%d first=%d,%d,%d,%d delay=%08x "
                  "muted=%d saved=%s speech=%08x key=%d" % (
                      s32(u(SE)), s32(u(ME)), s32(u(FIRST[0])),
                      s32(u(FIRST[1])), s32(u(FIRST[2])), s32(u(FIRST[3])),
                      u(DELAY), s32(u(MUTED)),
                      ",".join("%08x" % u(SAVED + 4 * i) for i in range(5)),
                      u(SPEECH), s32(u(KEY))))
        self.emit("  vol " + " ".join("%08x" % v for v in self.vol))
        self.emit("  ao " + e.read(AO, 176).hex())

    # ---- the ops

    def call(self, name, *args):
        return self.e.call(F[name], *args, limit=2000000)

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

        o = f[0]
        if o == "load":
            self.call("load", JB, self.path, 0)
        elif o in ("close", "update", "stopj", "advance", "stopplaying",
                   "startplaying"):
            self.call(o, JB)
        elif o == "defaults":
            self.call("defaults", AO)
        elif o == "fromsound":
            self.call("fromsound", AO, arg(1))
        elif o == "apply":
            self.call("apply", AO)
        elif o == "select":
            self.call("select", arg(1))
        elif o == "mstart":
            self.call("mstart", 0)
        elif o == "mstop":
            self.call("mstop")
        elif o == "delayed":
            e.fpr[12] = fl(1)
            self.call("delayed")
        elif o == "misplaying":
            self.emit("  = %d" % (self.call("misplaying") & 0xff))
        elif o == "event":
            self.call("event", arg(1), 0x00100000, JB)
        elif o in ("start", "fade", "fadeadv", "seton", "jpause",
                   "startfading", "caton", "catoff"):
            self.call(o, JB, arg(1))
        elif o == "starttune":
            self.call("starttune", JB, arg(1), arg(2), arg(3))
        elif o == "setvol":
            e.fpr[12] = fl(1)
            self.call("setvol", JB)
        elif o in ("tuneon", "tuneoff", "startplayingtune"):
            self.call(o, JB, arg(1), arg(2))
        elif o == "gettuneon":
            self.emit("  = %d" % (self.call(o, JB, arg(1), arg(2)) & 0xff))
        elif o == "pick":
            c, t = self.locals, self.locals + 4
            e.put32(c, 0)
            e.put32(t, 0)
            r = self.call("pick", JB, c, t) & 0xff
            if r:
                self.emit("  = 1 %u %u" % (e.u32(c), e.u32(t)))
            else:
                self.emit("  = 0")
        elif o in ("isplaying", "isfading"):
            self.emit("  = %d" % (self.call(o, JB) & 0xff))
        elif o == "name":
            self.emit("  = %s" % self.cstr(
                self.call("name", JB, arg(1), arg(2)) & M32))
        elif o in ("offset", "size", "id"):
            self.emit("  = %u" % (self.call(o, JB, arg(1), arg(2)) & M32))
        elif o == "addcat":
            self.write_str(self.strbuf, f[1])
            self.emit("  = %d" % self.call("addcat", JB, self.strbuf))
        elif o == "addtune":
            self.write_str(self.strbuf, f[1])
            self.write_str(self.strbuf + 128, f[2])
            self.emit("  = %d" % self.call(
                "addtune", JB, self.strbuf, self.strbuf + 128,
                int(f[3], 0), int(f[4], 0), int(f[5], 0), int(f[6], 0)))
        elif o == "track":
            r = self.call(TRACK[arg(3)], arg(1), arg(2)) & M32
            self.emit("  = %s" % (self.cstr(r) if r else "(null)"))
        elif o == "status":
            self.emit("  = %d" % self.call("status", arg(1), arg(2)))
        elif o == "current":
            self.emit("  = %u" % (self.call("current") & M32))
        elif o == "savedvol":
            self.call("savedvol", arg(1))
            self.emit("  = %08x" % (e.fpr[0] & M32))
        elif o == "saved":
            self.call("saved")
        elif o == "setcatvol":
            if arg(1) < 16:
                self.vol[arg(1)] = fl(2)
        elif o == "soundupdate":
            self.call("soundupdate")
        elif o == "mute":
            # Mute reads TheChopperManager's chopper (+24) with no test of
            # the manager; Update's test of it wants it NULL.
            keep = e.u32(CHOPPER)
            e.put32(CHOPPER, self.chopper)
            try:
                self.call("mute", arg(1))
            finally:
                e.put32(CHOPPER, keep)
        elif o == "state":
            e.put32(STATE, arg(1))
        elif o == "cops":
            e.put32(COPS, arg(1))
        elif o == "vblank":
            e.put32(VBLANK, arg(1))
        elif o == "paused":
            self.paused = arg(1)
        elif o == "muted":
            e.put32(MUTED, arg(1))
        elif o == "dt":
            e.put32(DT, fl(1))
        elif o == "enable":
            e.put32(SE, arg(1))
            e.put32(ME, arg(2))
        elif o == "aob":
            e.mem[AO + arg(1)] = arg(2) & 0xff
        elif o == "aow":
            e.put32(AO + arg(1), arg(2))
        elif o == "mode":
            self.mode = arg(1)
        elif o == "soundup":
            self.sound_up = arg(1)
        elif o == "cart":
            self.cart = arg(1)
        elif o == "defvol":
            self.call("defvol")
        elif o == "oneshots":
            for i in range(4):
                e.put32(FIRST[i], arg(i + 1))
        elif o == "dump":
            self.dump()
        else:
            self.emit("  unknown op %s" % o)

    def run(self, lines):
        e = self.e
        for line in lines:
            self.emit("> " + line)
            sp = e.reg[29]
            try:
                self.op(line.split("|"))
            except Abort:
                pass
            e.reg[29] = sp
        return self.out


def model(lines, carts):
    return Model(carts).run(lines)


# ================================================================= build

def build_harness(tmp, name="jukebox_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, sc_path, cart_paths, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(sc_path)] +
                               [str(p) for p in cart_paths], stdout=fh,
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


def write_inputs(d, lines, carts):
    sc = Path(d) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    paths = []
    for i, c in enumerate(carts):
        p = Path(d) / ("cart%d.bin" % (i + 1))
        p.write_bytes(c)
        paths.append(p)
    return sc, paths


# ============================================================= mutations

def _m(name, before, after):
    return (name, JBC, before, after)


def _plays_on():
    """Every cell of the status table flipped, one at a time."""
    rows = ["0, 0, 0,", "0, 1, 0,", "0, 0, 1,",
            "1, 0, 0,", "1, 1, 0,", "1, 1, 1,"]
    out = []
    for r, row in enumerate(rows):
        cells = row.rstrip(",").split(", ")
        for c in range(3):
            flip = list(cells)
            flip[c] = "1" if flip[c] == "0" else "0"
            new = ", ".join(flip) + ","
            out.append(_m("plays-on-%d-%d" % (r, c),
                          "\n    %s\n" % row, "\n    %s\n" % new))
    return out


TUNE_AT = ("JBTune* jb_tune_at(JBPlayer* p, uint32_t cat, uint32_t tune,\n"
           "                          int line)\n{\n")
CHECKED = ("JBTune* jb_tune_checked(JBPlayer* p, uint32_t cat, uint32_t tune,\n"
           "                               int line)\n{\n")

MUTATIONS = [
    # ---- cartridge getters
    _m("tune-at-cat-bound", TUNE_AT + "    if (cat >= p->numCategories) {",
       TUNE_AT + "    if (cat > p->numCategories) {"),
    _m("tune-at-tune-bound",
       "    if (tune >= p->category[cat].numTunes) {\n"
       "        jb_fail(p, line + 1);\n        return NULL;\n    }\n"
       "    uint32_t id = p->category[cat].tuneIndex[tune];\n"
       "    return id < JB_MAX_TUNES ? &p->tune[id] : NULL;\n}\n\n"
       "const char* jb_tune_name",
       "    if (tune > p->category[cat].numTunes) {\n"
       "        jb_fail(p, line + 1);\n        return NULL;\n    }\n"
       "    uint32_t id = p->category[cat].tuneIndex[tune];\n"
       "    return id < JB_MAX_TUNES ? &p->tune[id] : NULL;\n}\n\n"
       "const char* jb_tune_name"),
    _m("tune-at-line-plus",
       "        jb_fail(p, line + 1);\n        return NULL;\n    }\n"
       "    uint32_t id = p->category[cat].tuneIndex[tune];\n"
       "    return id < JB_MAX_TUNES ? &p->tune[id] : NULL;\n}\n\n"
       "const char* jb_tune_name",
       "        jb_fail(p, line + 2);\n        return NULL;\n    }\n"
       "    uint32_t id = p->category[cat].tuneIndex[tune];\n"
       "    return id < JB_MAX_TUNES ? &p->tune[id] : NULL;\n}\n\n"
       "const char* jb_tune_name"),
    _m("name-line", "jb_tune_at(p, cat, tune, 45);\n    return t ? t->name",
       "jb_tune_at(p, cat, tune, 44);\n    return t ? t->name"),
    _m("name-field", "return t ? t->name : \"\";", "return t ? t->name + 1 : \"\";"),
    _m("offset-line", "jb_tune_at(p, cat, tune, 55);",
       "jb_tune_at(p, cat, tune, 54);"),
    _m("offset-round-2048", "((t->syncSize >> 11) << 11) + 2048",
       "((t->syncSize >> 11) << 11) + 2047"),
    _m("offset-no-round", "((t->syncSize >> 11) << 11) + 2048",
       "t->syncSize + 2048"),
    _m("offset-no-sync-test", "t->syncSize ? ((t->syncSize",
       "1 ? ((t->syncSize"),
    _m("offset-plus", "return t->offset + sync;", "return t->offset;"),
    _m("size-line", "jb_tune_at(p, cat, tune, 78);",
       "jb_tune_at(p, cat, tune, 77);"),
    _m("size-field", "return t ? t->size : 0;", "return t ? t->offset : 0;"),
    _m("id-line", "jb_tune_at(p, cat, tune, 98);",
       "jb_tune_at(p, cat, tune, 97);"),
    _m("id-field", "return t ? t->id : 0;", "return t ? t->syncSize : 0;"),
    _m("copy-name-cap", "if (n >= JB_NAME_MAX) {\n        n = JB_NAME_MAX - 1;",
       "if (n >= JB_NAME_MAX) {\n        n = JB_NAME_MAX - 2;"),

    # ---- AddCategory / AddTune
    _m("addcat-find", "if (strcmp(name, p->category[i].name) == 0) {\n"
       "            return (int32_t)i;",
       "if (strcmp(name, p->category[i].name) == 0 && 0) {\n"
       "            return (int32_t)i;"),
    _m("addcat-zero-count", "    c->numTunes = 0;\n    c->use = 1;\n",
       "    c->use = 1;\n"),
    _m("addcat-use", "    c->numTunes = 0;\n    c->use = 1;\n",
       "    c->numTunes = 0;\n    c->use = 0;\n"),
    _m("addcat-count", "    p->numCategories++;\n    return (int32_t)i;",
       "    return (int32_t)i;"),
    _m("addtune-find", "if (strcmp(name, p->tune[i].name) == 0) {\n"
       "            break;",
       "if (strcmp(name, p->tune[i].name) == 0 && 0) {\n"
       "            break;"),
    _m("addtune-limit", "if (i >= JB_MAX_TUNES) {\n            return -1;",
       "if (i >= JB_MAX_TUNES - 1) {\n            return -1;"),
    _m("addtune-limit-ret", "if (i >= JB_MAX_TUNES) {\n            return -1;",
       "if (i >= JB_MAX_TUNES) {\n            return 0;"),
    _m("addtune-offset", "t->offset = offset;", "t->offset = size;"),
    _m("addtune-size", "t->size = size;", "t->size = offset;"),
    _m("addtune-sync", "t->syncSize = sync;", "t->syncSize = 0;"),
    _m("addtune-id", "t->id = id;", "t->id = id + 1;"),
    _m("addtune-use", "    t->use = 1;\n    JBCategory*",
       "    t->use = 0;\n    JBCategory*"),
    _m("addtune-index", "c->tuneIndex[c->numTunes++] = i;",
       "c->tuneIndex[c->numTunes++] = 0;"),
    _m("addtune-last", "    c->lastTunePlayed = 0;\n    return (int32_t)i;",
       "    return (int32_t)i;"),
    _m("addtune-ret", "    c->lastTunePlayed = 0;\n    return (int32_t)i;",
       "    c->lastTunePlayed = 0;\n    return 0;"),

    # ---- player init / LoadCartridge / Close
    _m("init-on", "    p->on = 1;\n", "    p->on = 0;\n"),
    _m("init-category", "p->soundCategory = 0xFFFFFFFFu;",
       "p->soundCategory = 0;"),
    _m("init-volume", "    p->volume = 1.0f;\n", "    p->volume = 0.5f;\n"),
    _m("load-sound-up", "if (!H->sound_up(H->ctx)) {", "if (0) {"),
    _m("load-assert-301", "        jb_fail(p, 301);\n        return;\n",
       "        jb_fail(p, 300);\n        return;\n"),
    _m("load-loaded-test", "    if (jb_is_cartridge_loaded(p)) {\n"
       "        jb_fail(p, 301);",
       "    if (0) {\n        jb_fail(p, 301);"),
    _m("load-assert-306", "jb_fail(p, 306);", "jb_fail(p, 305);"),
    _m("load-open", "    p->fileOpen = true;\n    size_t n",
       "    size_t n"),
    _m("load-path", "    memcpy(p->path, path, n);\n    p->path[n] = 0;\n",
       "    memcpy(p->path, path, n);\n    p->path[n ? n - 1 : 0] = 0;\n"),
    _m("load-cat-count", "for (uint32_t c = 0; c < p->header[3]; c++) {",
       "for (uint32_t c = 0; c < p->header[3] && c < 1; c++) {"),
    _m("load-index-size", "    uint32_t size = p->header[4];\n",
       "    uint32_t size = p->header[4] / 2;\n"),
    _m("load-cat-name", "memcpy(cname, cat + 4, 60);",
       "memcpy(cname, cat + 5, 60);"),
    _m("load-cat-tunes", "uint32_t tunes = rd32(cat);",
       "uint32_t tunes = rd32(cat) ? rd32(cat) - 1 : 0;"),
    _m("load-tune-name", "memcpy(tname, tu + 12, 84);",
       "memcpy(tname, tu + 13, 84);"),
    _m("load-tune-fields", "rd32(tu), rd32(tu + 4),",
       "rd32(tu + 4), rd32(tu),"),
    _m("load-tune-sync", "rd32(tu + 8), 0);", "0, 0);"),
    _m("load-rate", "H->create(H->ctx, p->header[2]);",
       "H->create(H->ctx, p->header[1]);"),
    _m("load-sample", "        p->sample = true;\n    }\n}",
       "    }\n}"),
    _m("close-file", "    if (p->fileOpen) {\n        H->close",
       "    if (1) {\n        H->close"),
    _m("close-open-flag", "        p->file = NULL;\n        p->fileOpen = false;",
       "        p->file = NULL;"),
    _m("close-sample", "    if (p->sample) {\n        H->destroy",
       "    if (1) {\n        H->destroy"),
    _m("close-sample-flag", "        H->destroy(H->ctx);\n        p->sample = false;",
       "        H->destroy(H->ctx);"),
    _m("close-cats", "    p->numCategories = 0;\n    p->numTunes = 0;\n",
       "    p->numTunes = 0;\n"),
    _m("close-tunes", "    p->numCategories = 0;\n    p->numTunes = 0;\n",
       "    p->numCategories = 0;\n"),

    # ---- Start / Stop / Fade / Advance
    _m("start-keep", "    p->keepPlaying = keep;\n    if (jb_is_cartridge_loaded(p)) {\n"
       "        jb_advance(p);",
       "    p->keepPlaying = 1;\n    if (jb_is_cartridge_loaded(p)) {\n"
       "        jb_advance(p);"),
    _m("starttune-keep", "    p->keepPlaying = keep;\n    if (jb_is_cartridge_loaded(p)) {\n"
       "        if (jb_is_playing(p) || jb_is_fading(p)) {\n"
       "            jb_stop_playing(p);\n        }\n        jb_start_playing_tune",
       "    p->keepPlaying = 1;\n    if (jb_is_cartridge_loaded(p)) {\n"
       "        if (jb_is_playing(p) || jb_is_fading(p)) {\n"
       "            jb_stop_playing(p);\n        }\n        jb_start_playing_tune"),
    _m("starttune-stop", "            jb_stop_playing(p);\n        }\n"
       "        jb_start_playing_tune(p, cat, tune);",
       "        }\n        jb_start_playing_tune(p, cat, tune);"),
    _m("stop-stop", "            jb_stop_playing(p);\n        }\n"
       "        p->keepPlaying = 0;\n    }\n}\n\nvoid jb_fade_out(",
       "        }\n        p->keepPlaying = 0;\n    }\n}\n\nvoid jb_fade_out("),
    _m("stop-keep", "        p->keepPlaying = 0;\n    }\n}\n\nvoid jb_fade_out(",
       "    }\n}\n\nvoid jb_fade_out("),
    _m("fade-keep", "            jb_start_fading(p, ms);\n        }\n"
       "        p->keepPlaying = 0;",
       "            jb_start_fading(p, ms);\n        }"),
    _m("fade-ms", "            jb_start_fading(p, ms);\n        }\n"
       "        p->keepPlaying = 0;",
       "            jb_start_fading(p, ms + 1);\n        }\n"
       "        p->keepPlaying = 0;"),
    _m("fade-test", "        if (jb_is_playing(p) && !jb_is_fading(p)) {",
       "        if (0) {"),
    _m("fadeadv-test",
       "if (jb_is_cartridge_loaded(p) && jb_is_playing(p) && !jb_is_fading(p)) {",
       "if (0) {"),
    _m("advance-stop", "            jb_stop_playing(p);\n        }\n"
       "        jb_start_playing(p);",
       "        }\n        jb_start_playing(p);"),
    _m("advance-start", "        jb_start_playing(p);\n    }\n}\n\nbool jb_is_done_playing",
       "    }\n}\n\nbool jb_is_done_playing"),
    _m("done-playing-sample",
       "return p->sample && p->statePlay == JB_DONE_PLAYING;",
       "return p->statePlay == JB_DONE_PLAYING;"),
    _m("done-fading-sample",
       "return p->sample && p->statePlay == JB_DONE_FADING;",
       "return p->statePlay == JB_DONE_FADING;"),

    # ---- Update / SetOn / callback
    _m("update-fading", "if (p->statePlay == JB_FADING) {\n            H->cleanup",
       "if (p->statePlay == JB_PLAYING) {\n            H->cleanup"),
    _m("update-fading-state", "            H->cleanup(H->ctx);\n"
       "            p->statePlay = JB_NOTINUSE;\n        } else",
       "            H->cleanup(H->ctx);\n        } else"),
    _m("update-play-args", "H->play(H->ctx, 1.0f, 0.0f, 0.0f);",
       "H->play(H->ctx, 1.0f, 0.0f, 1.0f);"),
    _m("update-play", "            H->play(H->ctx, 1.0f, 0.0f, 0.0f);\n",
       ""),
    _m("update-trigger", "        p->trigger = 0;\n", ""),
    _m("update-done-fading",
       "    if (jb_is_done_fading(p)) {\n        H->cleanup(H->ctx);\n"
       "        p->statePlay = JB_NOTINUSE;\n    }\n",
       "    if (jb_is_done_fading(p)) {\n        H->cleanup(H->ctx);\n    }\n"),
    _m("update-done-playing-state",
       "        H->cleanup(H->ctx);\n        p->statePlay = JB_NOTINUSE;\n"
       "        if (p->keepPlaying == 1) {",
       "        H->cleanup(H->ctx);\n        if (p->keepPlaying == 1) {"),
    _m("update-keep", "if (p->keepPlaying == 1) {", "if (p->keepPlaying) {"),
    _m("update-restart", "        if (p->keepPlaying == 1) {\n"
       "            jb_start_playing(p);\n        }\n",
       ""),
    _m("seton-stop", "    if (!on && p->on) {\n        jb_stop(p);\n    }\n", ""),
    _m("seton-store", "    p->on = on;\n", ""),
    _m("event-buffered", "    case JB_EVENT_BUFFERED:\n    case JB_EVENT_BUFFERED2:\n",
       "    case JB_EVENT_BUFFERED2:\n"),
    _m("event-buffered2", "    case JB_EVENT_BUFFERED:\n    case JB_EVENT_BUFFERED2:\n",
       "    case JB_EVENT_BUFFERED:\n"),
    _m("event-fade-end", "        p->statePlay = JB_DONE_FADING;\n        break;",
       "        p->statePlay = JB_DONE_PLAYING;\n        break;"),
    _m("event-play-end", "        p->statePlay = JB_DONE_PLAYING;\n        break;",
       "        p->statePlay = JB_DONE_FADING;\n        break;"),
    _m("event-ignored", "    default:\n        break;\n    }\n}",
       "    default:\n        p->trigger = 1;\n        break;\n    }\n}"),

    # ---- StopPlaying / Pause / StartFading
    _m("stopplaying-line", "jb_fail(p, 574);", "jb_fail(p, 573);"),
    _m("stopplaying-fading",
       "    if (p->statePlay == JB_PLAYING || p->statePlay == JB_FADING) {\n"
       "        H->stop(H->ctx);",
       "    if (p->statePlay == JB_PLAYING) {\n        H->stop(H->ctx);"),
    _m("stopplaying-state", "        H->stop(H->ctx);\n        p->statePlay = JB_NOTINUSE;",
       "        H->stop(H->ctx);"),
    _m("pause-line", "jb_fail(p, 592);", "jb_fail(p, 591);"),
    _m("pause-fading",
       "    if (p->statePlay == JB_PLAYING || p->statePlay == JB_FADING) {\n"
       "        H->pause",
       "    if (p->statePlay == JB_PLAYING) {\n        H->pause"),
    _m("pause-arg", "H->pause(H->ctx, on != 0);", "H->pause(H->ctx, 1);"),
    _m("startfading-line", "jb_fail(p, 645);", "jb_fail(p, 644);"),
    _m("startfading-test", "    if (p->statePlay == JB_PLAYING) {\n        H->fade",
       "    if (p->statePlay != JB_NOTINUSE) {\n        H->fade"),
    _m("startfading-to", "H->fade(H->ctx, 0.0f, ms);", "H->fade(H->ctx, 1.0f, ms);"),
    _m("startfading-state", "        H->fade(H->ctx, 0.0f, ms);\n"
       "        p->statePlay = JB_FADING;",
       "        H->fade(H->ctx, 0.0f, ms);"),

    # ---- StartPlayingTune / StartPlaying
    _m("playtune-line", "jb_fail(p, 662);", "jb_fail(p, 661);"),
    _m("playtune-on", "    if (!p->on) {\n        return;\n    }\n    p->curCatNum",
       "    p->curCatNum"),
    _m("playtune-cur-first",
       "    p->curCatNum = cat;\n    p->curTuneNum = tune;\n"
       "    if (!jb_tune_at(p, cat, tune, 45)) {       // the Printf's GetTuneName\n"
       "        return;\n    }\n",
       "    if (!jb_tune_at(p, cat, tune, 45)) {       // the Printf's GetTuneName\n"
       "        return;\n    }\n"
       "    p->curCatNum = cat;\n    p->curTuneNum = tune;\n"),
    _m("playtune-cur-cat", "    p->curCatNum = cat;\n    p->curTuneNum = tune;\n",
       "    p->curCatNum = tune;\n    p->curTuneNum = tune;\n"),
    _m("playtune-cur-tune", "    p->curCatNum = cat;\n    p->curTuneNum = tune;\n",
       "    p->curCatNum = cat;\n    p->curTuneNum = cat;\n"),
    _m("playtune-48", "jb_tune_offset(p, cat, tune) + 48;",
       "jb_tune_offset(p, cat, tune) + 32;"),
    _m("playtune-size", "    uint32_t size = jb_tune_size(p, cat, tune);\n",
       "    uint32_t size = jb_tune_size(p, cat, tune) - 48;\n"),
    _m("playtune-category", "    H->set_category(H->ctx, p->soundCategory);\n"
       "    H->set_scale_volume(H->ctx, p->volume);\n",
       "    H->set_scale_volume(H->ctx, p->volume);\n"),
    _m("playtune-volume", "    H->set_category(H->ctx, p->soundCategory);\n"
       "    H->set_scale_volume(H->ctx, p->volume);\n",
       "    H->set_category(H->ctx, p->soundCategory);\n"),
    _m("playtune-state", "    H->set_scale_volume(H->ctx, p->volume);\n"
       "    p->statePlay = JB_PLAYING;\n",
       "    H->set_scale_volume(H->ctx, p->volume);\n"),
    _m("startplaying-line", "jb_fail(p, 736);", "jb_fail(p, 735);"),
    _m("setvol-store", "    p->volume = v;\n    if (p->sample) {",
       "    if (p->sample) {"),
    _m("setvol-sample", "    p->volume = v;\n    if (p->sample) {",
       "    p->volume = v;\n    if (1) {"),

    # ---- tune/category on-off
    _m("checked-cat-bound", CHECKED + "    if (cat >= p->numCategories) {",
       CHECKED + "    if (cat > p->numCategories) {"),
    _m("checked-line-plus",
       "        jb_fail(p, line + 1);\n        return NULL;\n    }\n"
       "    uint32_t id = p->category[cat].tuneIndex[tune];\n"
       "    return id < JB_MAX_TUNES ? &p->tune[id] : NULL;\n}\n\n"
       "void jb_set_tune_on",
       "        jb_fail(p, line + 2);\n        return NULL;\n    }\n"
       "    uint32_t id = p->category[cat].tuneIndex[tune];\n"
       "    return id < JB_MAX_TUNES ? &p->tune[id] : NULL;\n}\n\n"
       "void jb_set_tune_on"),
    _m("tuneon-line", "jb_tune_checked(p, cat, tune, 757);",
       "jb_tune_checked(p, cat, tune, 756);"),
    _m("tuneon-use", "        t->use = 1;\n    }\n}\n\nvoid jb_set_tune_off",
       "        t->use = 0;\n    }\n}\n\nvoid jb_set_tune_off"),
    _m("tuneoff-line", "jb_tune_checked(p, cat, tune, 767);",
       "jb_tune_checked(p, cat, tune, 766);"),
    _m("tuneoff-use", "        t->use = 0;\n    }\n}", "        t->use = 1;\n    }\n}"),
    _m("gettuneon-line", "jb_tune_checked(p, cat, tune, 777);",
       "jb_tune_checked(p, cat, tune, 776);"),
    _m("gettuneon-use", "return t && t->use;", "return t != NULL;"),
    _m("caton-line", "jb_fail(p, 790);", "jb_fail(p, 789);"),
    _m("caton-use", "    p->category[cat].use = 1;\n", "    p->category[cat].use = 0;\n"),
    _m("catoff-line", "jb_fail(p, 797);", "jb_fail(p, 796);"),
    _m("catoff-use", "    p->category[cat].use = 0;\n", "    p->category[cat].use = 1;\n"),

    # ---- PickNextTune
    _m("pick-cat-from", "for (uint32_t i = 1; i <= n; i++) {",
       "for (uint32_t i = 0; i < n; i++) {"),
    _m("pick-cat-last", "for (uint32_t i = 1; i <= n; i++) {",
       "for (uint32_t i = 1; i < n; i++) {"),
    _m("pick-cat-use", "        if (!k->use) {\n            continue;\n        }\n", ""),
    _m("pick-tune-from", "for (uint32_t j = 1; j <= k->numTunes; j++) {",
       "for (uint32_t j = 0; j < k->numTunes; j++) {"),
    _m("pick-tune-last", "for (uint32_t j = 1; j <= k->numTunes; j++) {",
       "for (uint32_t j = 1; j < k->numTunes; j++) {"),
    _m("pick-tune-use", "p->tune[id].use) {", "1) {"),
    _m("pick-last-cat", "            p->lastCategory = c;\n", ""),
    _m("pick-last-tune", "            k->lastTunePlayed = t;\n", ""),
    _m("pick-out-tune", "            *tune = t;\n", "            *tune = id;\n"),

    # ---- IsFading / IsPlaying / SetCategory
    _m("isfading-update", "    jb_update(p);\n    return p->statePlay == JB_FADING;",
       "    return p->statePlay == JB_FADING;"),
    _m("isplaying-update", "    jb_update(p);\n    return p->statePlay == JB_PLAYING || jb_is_fading(p);\n}\n\nvoid jb_set_category",
       "    return p->statePlay == JB_PLAYING || jb_is_fading(p);\n}\n\nvoid jb_set_category"),
    _m("isplaying-fading", "return p->statePlay == JB_PLAYING || jb_is_fading(p);\n}\n\nvoid jb_set_category",
       "return p->statePlay == JB_PLAYING;\n}\n\nvoid jb_set_category"),
    _m("setcat-store", "    p->soundCategory = cat;\n", ""),
    _m("setcat-sample", "    if (p->sample) {\n        H->set_category(H->ctx, cat);",
       "    if (1) {\n        H->set_category(H->ctx, cat);"),

    # ---- sound::jukebox state
    _m("saved-list", "{0, 1, 2, 5, 4};", "{0, 1, 2, 4, 5};"),
    _m("sinit-sound", "    s->soundEnabled = 1;\n", ""),
    _m("sinit-music", "    s->musicEnabled = 1;\n", ""),
    _m("sinit-menu", "    s->firstMenuTune = 1;\n", ""),
    _m("sinit-pursuit", "    s->firstPursuitTune = 1;\n", ""),
    _m("sinit-race", "    s->firstRaceTune = 1;\n", ""),
    _m("sinit-advance", "    s->firstAdvance = 1;\n", ""),
    _m("sinit-saved", "s->savedVolume[i] = -1.0f;", "s->savedVolume[i] = 0.0f;"),
    _m("sinit-speech", "    s->savedSpeechVolume = -1.0f;\n", ""),
    _m("sinit-catvol", "s->categoryVolume[i] = 1.0f;", "s->categoryVolume[i] = 0.5f;"),
    _m("sinit-key", "    s->trackKey = -1;\n", ""),
    _m("getcatvol-bound", "return cat < 16 ? s->categoryVolume[cat] : 1.0f;",
       "return cat < 16 ? s->categoryVolume[cat] : 0.0f;"),
    _m("setcatvol-store", "    if (cat < 16) {\n        s->categoryVolume[cat] = v;",
       "    if (cat < 15) {\n        s->categoryVolume[cat] = v;"),
    _m("saved-0", "case 0: return s->savedVolume[0];", "case 0: return s->savedVolume[1];"),
    _m("saved-1", "case 1: return s->savedVolume[1];", "case 1: return s->savedVolume[0];"),
    _m("saved-2", "case 2: return s->savedVolume[2];", "case 2: return s->savedVolume[1];"),
    _m("saved-4", "case 4: return s->savedVolume[4];", "case 4: return s->savedVolume[3];"),
    _m("saved-5", "case 5: return s->savedVolume[3];", "case 5: return s->savedVolume[4];"),
    _m("saved-default", "default: return 0.0f;", "default: return 1.0f;"),
    _m("defvol-music", "0.31f, 0.85f, 0.45f, 0.75f,", "0.31f, 0.45f, 0.85f, 0.75f,"),
    _m("defvol-sfx", "0.38f, 0.55f, 0.33f,", "0.55f, 0.38f, 0.33f,"),
    _m("defvol-speech", "0.45f, 0.75f,", "0.45f, 0.7f,"),
    _m("defvol-count", "for (uint32_t i = 0; i < 7; i++) {\n"
       "        jb_set_category_volume(s, i, kDefaultVolume[i]);",
       "for (uint32_t i = 0; i < 6; i++) {\n"
       "        jb_set_category_volume(s, i, kDefaultVolume[i]);"),
    _m("defvol-save", "    jb_save_volumes_for_speech(s);\n}\n\nstatic int jb_state",
       "}\n\nstatic int jb_state"),
    _m("speech-saved","s->savedSpeechVolume = jb_get_category_volume(s, 6);",
       "s->savedSpeechVolume = jb_get_category_volume(s, 5);"),

    # ---- first pick
    _m("first-menu-cat", "    if (cat == 5) {\n        if (s->firstMenuTune)",
       "    if (cat == 3) {\n        if (s->firstMenuTune)"),
    _m("first-menu-idx", "            return 5;", "            return 4;"),
    _m("first-menu-once", "            s->firstMenuTune = 0;\n", ""),
    _m("first-race-cat", "    if (cat == 4) {\n        if (jb_max_cops(s) > 0) {",
       "    if (cat == 2) {\n        if (jb_max_cops(s) > 0) {"),
    _m("first-cops", "        if (jb_max_cops(s) > 0) {\n            if (s->firstPursuitTune)",
       "        if (jb_max_cops(s) > 1) {\n            if (s->firstPursuitTune)"),
    _m("first-pursuit-idx", "return 14;", "return 13;"),
    _m("first-pursuit-once", "                s->firstPursuitTune = 0;\n", ""),
    _m("first-race-idx", "            return 7;", "            return 6;"),
    _m("first-race-once", "            s->firstRaceTune = 0;\n", ""),
    _m("genre-bit", "return 1u << ((uint32_t)genre & 31);",
       "return 1u << (((uint32_t)genre + 1) & 31);"),

    # ---- Start
    _m("mstart-sound", "if (!s->soundEnabled || !s->musicEnabled) {\n        return;\n    }\n    jb_update(p);",
       "if (!s->musicEnabled) {\n        return;\n    }\n    jb_update(p);"),
    _m("mstart-music", "if (!s->soundEnabled || !s->musicEnabled) {\n        return;\n    }\n    jb_update(p);",
       "if (!s->soundEnabled) {\n        return;\n    }\n    jb_update(p);"),
    _m("mstart-fading", "    if (p->statePlay == JB_PLAYING || jb_is_fading(p)) {\n        return;",
       "    if (p->statePlay == JB_PLAYING) {\n        return;"),
    _m("mstart-status", "& ao[JB_AO_GENRE_MASK]) && e[2]) {",
       "& ao[JB_AO_GENRE_MASK])) {"),
    _m("mstart-genre", "if (e && (jb_genre_bit((int8_t)e[3]) & ao[JB_AO_GENRE_MASK]) && e[2]) {",
       "if (e && e[2]) {"),
    _m("mstart-entry-tune", "(uint32_t)(int32_t)(int8_t)e[1], 1);",
       "(uint32_t)(int32_t)(int8_t)e[0], 1);"),
    _m("mstart-keep", "(uint32_t)(int32_t)(int8_t)e[1], 1);",
       "(uint32_t)(int32_t)(int8_t)e[1], 0);"),
    _m("mstart-advance-once", "            s->firstAdvance = 0;\n", ""),
    _m("mstart-advance-n", "while (n-- > 0) {", "while (n-- > 1) {"),
    _m("mstart-advance-count", "? p->category[p->curCatNum].numTunes : 0;",
       "? p->numTunes : 0;"),
    _m("mstart-advance-seed", "? s->world->vblank(s->world->ctx) : 0;",
       "? s->world->vblank(s->world->ctx) + 1 : 0;"),
    _m("mstart-start-keep", "        jb_start(p, 1);\n    }\n", "        jb_start(p, 0);\n    }\n"),
    _m("mstart-pause-race", "jb_saved_volume(s, 4) == 0.0f && !fe);",
       "jb_saved_volume(s, 4) == 0.0f && fe);"),
    _m("mstart-pause-race-cat", "jb_saved_volume(s, 4) == 0.0f && !fe);",
       "jb_saved_volume(s, 5) == 0.0f && !fe);"),
    _m("mstart-pause-menu", "jb_saved_volume(s, 5) == 0.0f && fe);",
       "jb_saved_volume(s, 5) == 0.0f && !fe);"),
    _m("mstart-pause-menu-cat", "jb_saved_volume(s, 5) == 0.0f && fe);",
       "jb_saved_volume(s, 4) == 0.0f && fe);"),
    _m("mstart-pause-order",
       "    jb_pause(p, jb_saved_volume(s, 4) == 0.0f && !fe);\n"
       "    jb_pause(p, jb_saved_volume(s, 5) == 0.0f && fe);\n",
       "    jb_pause(p, jb_saved_volume(s, 5) == 0.0f && fe);\n"
       "    jb_pause(p, jb_saved_volume(s, 4) == 0.0f && !fe);\n"),
    _m("mstart-pause-first", "    jb_pause(p, jb_saved_volume(s, 4) == 0.0f && !fe);\n", ""),
    _m("mstop-music", "    if (s->musicEnabled) {\n        jb_stop(&s->jukebox);",
       "    if (1) {\n        jb_stop(&s->jukebox);"),
    _m("delayed-store", "    s->delayedStart = seconds;\n", ""),
    _m("delayed-stop", "    s->delayedStart = seconds;\n    jb_music_stop(s);\n",
       "    s->delayedStart = seconds;\n"),
    _m("misplaying-fe-fading",
       "        return p->statePlay == JB_PLAYING || jb_is_fading(p);\n    }\n",
       "        return p->statePlay == JB_PLAYING;\n    }\n"),
    _m("misplaying-volume", "return playing && 0.0f < jb_saved_volume(s, 4);",
       "return playing && 0.0f <= jb_saved_volume(s, 4);"),
    _m("misplaying-volume-cat", "return playing && 0.0f < jb_saved_volume(s, 4);",
       "return playing && 0.0f < jb_saved_volume(s, 5);"),
    _m("misplaying-fe", "    if (jb_state(s) == JB_STATE_IN_FRONTEND) {\n        jb_update(p);",
       "    if (0) {\n        jb_update(p);"),

    # ---- SetSelection
    _m("select-music", "    if (!s->musicEnabled) {\n        return;\n    }\n"
       "    jb_set_category(p, (uint32_t)cat);",
       "    jb_set_category(p, (uint32_t)cat);"),
    _m("select-category", "    jb_set_category(p, (uint32_t)cat);\n", ""),
    _m("select-col-cops", "(jb_max_cops(s) > 0 ? 2 : 1)", "(jb_max_cops(s) > 0 ? 1 : 2)"),
    _m("select-col-menu", "cat == 5 ? 0 : -1;", "cat == 5 ? 0 : 0;"),
    _m("select-col-cat", "int col = cat == 4 ?", "int col = cat == 3 ?"),
    _m("select-row", "int k = (int8_t)e[2] * 3 + col;", "int k = (int8_t)e[2] * 2 + col;"),
    _m("select-top", "k >= 0 && k < 18 && kPlaysOn[k]", "k >= 0 && k < 17 && kPlaysOn[k]"),
    _m("select-genre", " &&\n                 (ao[JB_AO_GENRE_MASK] & jb_genre_bit((int8_t)e[3]));",
       ";"),
    _m("select-count", "    for (int32_t i = 0; i < n; i++) {\n        const uint8_t* e = ao + JB_AO_TUNE_LIST + 4 * i;\n        int k",
       "    for (int32_t i = 1; i < n; i++) {\n        const uint8_t* e = ao + JB_AO_TUNE_LIST + 4 * i;\n        int k"),
    _m("select-entry-cat", "        uint32_t c = (uint32_t)(int32_t)(int8_t)e[0];\n",
       "        uint32_t c = (uint32_t)(int32_t)(int8_t)e[1];\n"),
    _m("select-on", "        if (on) {\n            jb_set_tune_on(p, c, t);",
       "        if (!on) {\n            jb_set_tune_on(p, c, t);"),
] + _plays_on() + [
    # ---- track strings
    _m("extract-cache", "    if (key == s->trackKey) {\n        return s->track;\n    }\n", ""),
    _m("extract-key", "int32_t key = (int32_t)((uint32_t)cat << 16) + tune;",
       "int32_t key = cat + tune;"),
    _m("extract-key-store", "    s->trackKey = key;\n", ""),
    _m("extract-clear", "    memset(s->track, 0, sizeof s->track);\n", ""),
    _m("extract-cut", "            *c = 0;\n", ""),
    _m("extract-empty", "if (c[1] != 0 && n < 16) {", "if (n < 16) {"),
    _m("extract-first", "    s->track[0] = s->trackName;\n    int n = 1;",
       "    int n = 0;"),
    _m("track-music", "    if (!s->musicEnabled) {\n        return NULL;\n    }\n"
       "    if (cat == -1) {", "    if (cat == -1) {"),
    _m("track-cur-cat", "cat = (int)s->jukebox.curCatNum;", "cat = (int)s->jukebox.curTuneNum;"),
    _m("track-cur-tune", "tune = (int)s->jukebox.curTuneNum;", "tune = (int)s->jukebox.curCatNum;"),
    _m("track-field", "[field & 15];", "[field & 7];"),
    _m("strtolong-base", "v = v * 10 +", "v = v * 16 +"),
    _m("strtolong-digits", "while (*p >= '0' && *p <= '9') {",
       "while (*p >= '0' && *p <= '9' && v == 0) {"),
    _m("status-field", "jb_track_string(s, cat, tune, 4);", "jb_track_string(s, cat, tune, 3);"),
    _m("status-empty", "    if (!st || !*st) {\n        return 0;", "    if (!st || !*st) {\n        return 1;"),
    _m("current-track", "return s->jukebox.curTuneNum;\n}", "return s->jukebox.curCatNum;\n}"),

    # ---- per-frame
    _m("mupdate-sound", "    if (!s->soundEnabled) {\n        return;\n    }\n"
       "    jb_update(&s->jukebox);", "    jb_update(&s->jukebox);"),
    _m("mupdate-update", "    jb_update(&s->jukebox);\n    int paused", "    int paused"),
    _m("mupdate-paused", "if (paused || jb_state(s) == JB_STATE_IN_FRONTEND || s->muted) {",
       "if (jb_state(s) == JB_STATE_IN_FRONTEND || s->muted) {"),
    _m("mupdate-fe", "if (paused || jb_state(s) == JB_STATE_IN_FRONTEND || s->muted) {",
       "if (paused || s->muted) {"),
    _m("mupdate-muted", "if (paused || jb_state(s) == JB_STATE_IN_FRONTEND || s->muted) {",
       "if (paused || jb_state(s) == JB_STATE_IN_FRONTEND) {"),
    _m("mupdate-positive", "if (0.0f < s->delayedStart) {", "if (0.0f <= s->delayedStart) {"),
    _m("mupdate-count", "if (0.0f < s->delayedStart) {", "if (1) {"),
    _m("mupdate-dt", "s->delayedStart -= dt;", "s->delayedStart -= dt * 2.0f;"),
    _m("mupdate-fire", "if (s->delayedStart < 0.0f) {", "if (s->delayedStart <= 0.0f) {"),
    _m("mupdate-reset", "        s->delayedStart = 0.0f;\n    }\n}", "    }\n}"),

    # ---- DataAudioOptionsScreen
    _m("from-menu", "wrf(ao + JB_AO_MENU_MUSIC, jb_get_category_volume(s, 5));",
       "wrf(ao + JB_AO_MENU_MUSIC, jb_get_category_volume(s, 4));"),
    _m("from-racing", "wrf(ao + JB_AO_RACING_MUSIC, jb_get_category_volume(s, 4));",
       "wrf(ao + JB_AO_RACING_MUSIC, jb_get_category_volume(s, 5));"),
    _m("from-sfx", "wrf(ao + JB_AO_SFX, jb_get_category_volume(s, 0));",
       "wrf(ao + JB_AO_SFX, jb_get_category_volume(s, 1));"),
    _m("from-speech", "wrf(ao + JB_AO_SPEECH, jb_get_category_volume(s, 6));",
       "wrf(ao + JB_AO_SPEECH, jb_get_category_volume(s, 3));"),
    _m("from-engine", "wrf(ao + JB_AO_SFX_ENGINE, jb_get_category_volume(s, 2));",
       "wrf(ao + JB_AO_SFX_ENGINE, jb_get_category_volume(s, 3));"),
    _m("from-menu-sfx", "wrf(ao + JB_AO_SFX_MENU, jb_get_category_volume(s, 3));",
       "wrf(ao + JB_AO_SFX_MENU, jb_get_category_volume(s, 2));"),
    _m("from-tires", "wrf(ao + JB_AO_SFX_TIRES, jb_get_category_volume(s, 1));",
       "wrf(ao + JB_AO_SFX_TIRES, jb_get_category_volume(s, 0));"),
    _m("from-tunes", "    if (tunes) {\n        wr32(ao + JB_AO_NUM_TUNES, 0);",
       "    if (1) {\n        wr32(ao + JB_AO_NUM_TUNES, 0);"),
    _m("from-reset", "    if (tunes) {\n        wr32(ao + JB_AO_NUM_TUNES, 0);",
       "    if (tunes) {"),
    _m("from-cap", "if (n < JB_AO_MAX_TUNES) {", "if (n < JB_AO_MAX_TUNES - 1) {"),
    _m("from-cat", "e[0] = (uint8_t)c;", "e[0] = (uint8_t)t;"),
    _m("from-tune", "e[1] = (uint8_t)t;", "e[1] = (uint8_t)c;"),
    _m("from-status", "e[2] = (uint8_t)jb_track_status(s, (int)c, (int)t);",
       "e[2] = 5;"),
    _m("from-mode-lo", "    ao[JB_AO_AUDIO_MODE] = (uint8_t)audioMode;\n", ""),
    _m("from-mode-hi", "    ao[JB_AO_AUDIO_MODE + 1] = (uint8_t)(audioMode >> 8);\n", ""),
    _m("defaults-tunes", "jb_audio_from_sound(s, ao, 1, audioMode);",
       "jb_audio_from_sound(s, ao, 0, audioMode);"),
    _m("defaults-fav", "wr32(ao + JB_AO_FE_FAVOURITE, 5);", "wr32(ao + JB_AO_FE_FAVOURITE, 4);"),
    _m("defaults-mask", "ao[JB_AO_GENRE_MASK] = 0xff;", "ao[JB_AO_GENRE_MASK] = 0x7f;"),
    _m("defaults-song", "wr32(ao + JB_AO_SELECTED_SONG, 0);", "wr32(ao + JB_AO_SELECTED_SONG, 1);"),
    _m("defaults-ingame", "wr32(ao + JB_AO_INGAME_FAVOURITE, 0);",
       "wr32(ao + JB_AO_INGAME_FAVOURITE, 1);"),
    _m("defaults-genre", "ao[JB_AO_CURR_GENRE] = 0;", "ao[JB_AO_CURR_GENRE] = 1;"),
    _m("genre-field", "jb_track_string(s, (int8_t)e[0], (int8_t)e[1], 3);",
       "jb_track_string(s, (int8_t)e[0], (int8_t)e[1], 2);"),
    _m("genre-empty", "        if (!g || !*g) {\n            continue;\n        }\n",
       "        if (!g) {\n            continue;\n        }\n"),
    _m("genre-find", "if (strcmp(g, genre[k].name) == 0) {", "if (strcmp(g, genre[k].name) == 0 && 0) {"),
    _m("genre-store", "        e[3] = (uint8_t)k;\n", ""),
    _m("apply-menu", "jb_set_category_volume(s, 5, rdf(ao + JB_AO_MENU_MUSIC));",
       "jb_set_category_volume(s, 4, rdf(ao + JB_AO_MENU_MUSIC));"),
    _m("apply-racing", "jb_set_category_volume(s, 4, rdf(ao + JB_AO_RACING_MUSIC));",
       "jb_set_category_volume(s, 5, rdf(ao + JB_AO_RACING_MUSIC));"),
    _m("apply-sfx", "jb_set_category_volume(s, 0, rdf(ao + JB_AO_SFX));",
       "jb_set_category_volume(s, 1, rdf(ao + JB_AO_SFX));"),
    _m("apply-speech", "jb_set_category_volume(s, 6, rdf(ao + JB_AO_SPEECH));",
       "jb_set_category_volume(s, 3, rdf(ao + JB_AO_SPEECH));"),
    _m("apply-engine", "jb_set_category_volume(s, 2, rdf(ao + JB_AO_SFX_ENGINE));",
       "jb_set_category_volume(s, 3, rdf(ao + JB_AO_SFX_ENGINE));"),
    _m("apply-menu-sfx", "jb_set_category_volume(s, 3, rdf(ao + JB_AO_SFX_MENU));",
       "jb_set_category_volume(s, 2, rdf(ao + JB_AO_SFX_MENU));"),
    _m("apply-tires", "jb_set_category_volume(s, 1, rdf(ao + JB_AO_SFX_TIRES));",
       "jb_set_category_volume(s, 0, rdf(ao + JB_AO_SFX_TIRES));"),
    _m("apply-save", "    jb_save_volumes_for_speech(s);\n    jb_music_set_selection(s, ao, 5);",
       "    jb_music_set_selection(s, ao, 5);"),
    _m("apply-select", "    jb_save_volumes_for_speech(s);\n    jb_music_set_selection(s, ao, 5);",
       "    jb_save_volumes_for_speech(s);\n    jb_music_set_selection(s, ao, 4);"),
    _m("apply-mode-hi", "ao[JB_AO_AUDIO_MODE] | ao[JB_AO_AUDIO_MODE + 1] << 8);",
       "ao[JB_AO_AUDIO_MODE]);"),
    _m("apply-mode-sign", "return (int16_t)(ao[JB_AO_AUDIO_MODE]",
       "return (uint16_t)(ao[JB_AO_AUDIO_MODE]"),
    _m("mute-sound", "    if (!s->soundEnabled) return;\n    s->muted = on;",
       "    s->muted = on;"),
    _m("mute-flag", "    s->muted = on;\n    if (s->musicEnabled) {",
       "    if (s->musicEnabled) {"),
    _m("mute-music", "    s->muted = on;\n    if (s->musicEnabled) {",
       "    s->muted = on;\n    if (1) {"),
    _m("mute-flag-late", "    s->muted = on;\n    if (s->musicEnabled) {",
       "    if (s->musicEnabled) {\n        s->muted = on;"),
    _m("mute-strict", "int pause = 0.0f < jb_get_category_volume",
       "int pause = 0.0f <= jb_get_category_volume"),
    _m("mute-cat", "jb_get_category_volume(s, p->soundCategory)\n",
       "jb_get_category_volume(s, 5)\n"),
    _m("mute-down", "? on : (on ? on : 1);", "? on : 1;"),
    _m("mute-down-on", "? on : (on ? on : 1);", "? on : on;"),
    _m("mute-up", "? on : (on ? on : 1);", "? (on ? on : 1) : (on ? on : 1);"),
]
EQUIVALENT = {
    "mute-down": "with the category at nothing `on ? on : 1` is nonzero "
                 "either way, and cJukeboxPlayer::Pause takes a bool",
    "copy-name-cap":"a name off the cartridge is at most 84 bytes, a "
                     "category's 60; only a name made by hand reaches 96",
    "getcatvol-bound": "every caller asks for a category 0 to 6",
    "select-col-menu": "SetSelection is only ever called with 4 or 5",
    "track-field": "retail has a getter for each of fields 0 to 3 and the "
                   "status for 4; nothing asks for another",
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    lines = script()
    carts = [f() for f in CARTS]
    base = model(lines, carts)
    caught, survived, missing, equivalent = 0, [], [], []
    indir = tempfile.TemporaryDirectory()
    scp, cps = write_inputs(indir.name, lines, carts)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, scp, cps, out)
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
                rc = run_harness(exe, scp, cps, out)
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
    carts = [f() for f in CARTS]
    got = model(lines, carts)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp, cps = write_inputs(tmp, lines, carts)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, cps, out)
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
